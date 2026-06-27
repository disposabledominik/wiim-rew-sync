"""
Capability prober — runtime detection of WiiM device features.

Probes the connected device through the WiiMHttpClient and populates a
DeviceCapabilities object.  All probes are best-effort: any failure is caught,
logged, and the affected capability is set to its most conservative (safest)
default value.

Probing sequence:
  1. getStatusEx        -> model, firmware, uuid, mac_address, source_names
  2. EQGetLV2BandEx     -> supports_peq, supports_lr_filters
  3. EQSetLV2Band (batch) -> supports_batch_write
  4. EQGetLV2List       -> supports_profile_enumeration
  5. RoomFit levels 0-4 -> roomfit_level, supports_roomfit*
  6. GetMultiroomInfo   -> role

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote

from src.adapters.wiim_http import WiiMHttpClient
from src.models.capabilities import DeviceCapabilities
from src.models.device_capability_file import find_entry, get_cached_entries, merge_into
from src.utils.device_identity import is_wiim_device

logger = logging.getLogger("wiim_rew_sync.wiim_api")

PLUGIN_URI = "http://moddevices.com/plugins/caps/EqNp"


class CapabilityProber:
    """Probe a WiiM device for its full runtime capability set.

    All probes are non-throwing: any exception is caught, logged, and the
    affected capability defaults to the most conservative value.

    Args:
        client: An initialised WiiMHttpClient pointing at the target device.
    """

    def __init__(self, client: WiiMHttpClient) -> None:
        self._client = client

    async def probe(self) -> DeviceCapabilities:
        """Probe the device and return its capabilities.

        Never raises — all errors produce safe defaults.
        """
        caps = DeviceCapabilities()

        # Step 1: getStatusEx — identity & source list
        status = await self._probe_status(caps)

        # Determine if this is a WiiM device
        is_wiim = is_wiim_device(caps.model)

        if not is_wiim:
            # Generic LinkPlay or unrecognised — all-conservative defaults
            logger.info(
                "Device model '%s' is not a recognised WiiM device; "
                "returning conservative defaults.",
                caps.model,
            )
            caps.max_filters = 0
            caps.supports_peq = False
            # Still probe multiroom role (useful for any LinkPlay device)
            await self._probe_multiroom(caps)
            return self._apply_capability_file(caps)

        # Step 2: EQGetLV2BandEx — PEQ support & channel mode
        await self._probe_peq(caps)

        # Step 3: Batch write test
        await self._probe_batch_write(caps, status)

        # Step 4: EQGetLV2List — profile enumeration
        await self._probe_profile_enumeration(caps)

        # Step 5: RoomFit sequential probe (levels 0-4)
        await self._probe_roomfit(caps)

        # Step 6: GetMultiroomInfo — multiroom role
        await self._probe_multiroom(caps)

        # max_filters is set dynamically by _probe_peq(); ensure 0 if PEQ unsupported
        if not caps.supports_peq:
            caps.max_filters = 0

        return self._apply_capability_file(caps)

    # ------------------------------------------------------------------
    # Internal probe steps
    # ------------------------------------------------------------------

    def _apply_capability_file(self, caps: DeviceCapabilities) -> DeviceCapabilities:
        """Apply device-capability-file overrides for the probed model, if any.

        This is the single merge point (Requirement 6): every caller of
        `probe()` -- CLI commands, GUI connect flow, secondary workflows --
        automatically gets capability-file overrides and the 10-band default
        cap (Requirement 7) applied here, with no per-caller changes needed.
        Models absent from the file are returned unchanged (full generic
        probed behaviour).
        """
        entries = get_cached_entries()
        entry = find_entry(caps.model, entries)
        return merge_into(caps, entry)

    async def _probe_status(self, caps: DeviceCapabilities) -> dict[str, Any]:
        """Probe getStatusEx for device identity and source names."""
        try:
            resp = await self._client.command("getStatusEx")
        except Exception:
            logger.warning("getStatusEx probe failed; using defaults.", exc_info=True)
            return {}

        if not isinstance(resp, dict):
            logger.warning("getStatusEx returned non-dict: %r", resp)
            return {}

        caps.model = str(resp.get("project", ""))
        caps.firmware = str(resp.get("Release", ""))
        caps.uuid = str(resp.get("uuid", ""))
        caps.mac_address = str(resp.get("MAC", resp.get("mac", "")))

        # Parse InputList for source_names
        input_list_raw = resp.get("InputList", "")
        if isinstance(input_list_raw, list):
            caps.source_names = [str(s) for s in input_list_raw]
        elif isinstance(input_list_raw, str) and input_list_raw:
            # InputList is often a JSON-encoded string, e.g. '["wifi","bluetooth"]'
            try:
                parsed = json.loads(input_list_raw)
                if isinstance(parsed, list):
                    caps.source_names = [str(s) for s in parsed]
            except (json.JSONDecodeError, ValueError):
                logger.warning("Could not parse InputList: %r", input_list_raw)

        return resp

    async def _probe_peq(self, caps: DeviceCapabilities) -> None:
        """Probe EQGetLV2BandEx for PEQ and channel-mode support."""
        try:
            # Requirement 2.2: determine supports_peq by attempting EQGetLV2BandEx
            # Rule 5: JSON payloads must be URL-encoded
            encoded_uri = quote(PLUGIN_URI)
            resp = await self._client.command(f"EQGetLV2BandEx:{encoded_uri}")
        except Exception:
            logger.warning("EQGetLV2BandEx probe failed; PEQ assumed unsupported.", exc_info=True)
            caps.supports_peq = False
            caps.supports_lr_filters = False
            return

        if not isinstance(resp, dict):
            logger.warning("EQGetLV2BandEx returned non-dict: %r", resp)
            caps.supports_peq = False
            caps.supports_lr_filters = False
            return

        # Valid response means PEQ is supported
        caps.supports_peq = True

        # Requirement 2.3: determine supports_lr_filters from channelMode field
        # If channelMode field exists in response, device supports L/R channel PEQ
        caps.supports_lr_filters = "channelMode" in resp

        # Dynamically detect max_filters by counting distinct band letter prefixes
        # in the EQBand response (e.g. a_mode, b_mode, ... l_mode → 12 bands).
        # ASSUMPTION: this count reflects bands available in the device's
        # *current* channel mode at probe time (i.e. per-channel if probed
        # while in L/R mode, total if probed while in Stereo mode) rather than
        # two independent per-channel limits. Unverified against real hardware
        # in both modes.
        # TODO: confirm by comparing EQGetLV2BandEx (Stereo) vs
        # EQGetLV2SourceBandEx (L/R) band-letter counts on the same device.
        # See docs/corrections.md 2026-06-27.
        eq_band: list[dict[str, object]] = resp.get("EQBand", [])
        band_letters: set[str] = set()
        for entry in eq_band:
            pn = str(entry.get("param_name", ""))
            if "_" in pn:
                band_letters.add(pn.split("_")[0])
        caps.max_filters = len(band_letters) if band_letters else 10

    async def _probe_batch_write(
        self, caps: DeviceCapabilities, status: dict[str, Any]
    ) -> None:
        """Probe batch write by attempting a 10-band EQSetLV2Band payload.

        Requirement 2.4: determine supports_batch_write by attempting a write
        of all 10 bands in a single EQSetLV2Band payload.

        NOTE: We first read current state, then write it back unchanged to
        avoid altering device state during probing.
        """
        if not caps.supports_peq:
            caps.supports_batch_write = False
            return

        try:
            # Read current bands first so we can write them back unchanged
            encoded_uri = quote(PLUGIN_URI)
            read_resp = await self._client.command(f"EQGetLV2BandEx:{encoded_uri}")

            if not isinstance(read_resp, dict):
                caps.supports_batch_write = False
                return

            # Extract the current band data to write back
            eq_band = read_resp.get("EQBand", [])
            channel_mode = read_resp.get("channelMode", "Stereo")

            if not eq_band:
                caps.supports_batch_write = False
                return

            # Build the write payload — write the same data back
            payload: dict[str, Any] = {
                "pluginURI": PLUGIN_URI,
                "channelMode": channel_mode,
                "EQBand": eq_band,
            }
            encoded_payload = quote(json.dumps(payload))
            resp = await self._client.command(f"EQSetLV2Band:{encoded_payload}")

            # Success if we get "OK" or a dict response without error
            if isinstance(resp, str) and resp.strip().lower() == "ok":
                caps.supports_batch_write = True
            elif isinstance(resp, dict):
                # Some firmware returns a dict on success
                caps.supports_batch_write = True
            else:
                caps.supports_batch_write = False

        except Exception:
            logger.warning(
                "Batch write probe failed; sequential writes assumed.", exc_info=True
            )
            caps.supports_batch_write = False

    async def _probe_profile_enumeration(self, caps: DeviceCapabilities) -> None:
        """Probe EQGetLV2List for profile enumeration support.

        Requirement 2.5: determine supports_profile_enumeration by attempting
        EQGetLV2List.
        """
        try:
            encoded_uri = quote(PLUGIN_URI)
            resp = await self._client.command(f"EQGetLV2List:{encoded_uri}")
        except Exception:
            logger.warning(
                "EQGetLV2List probe failed; profile enumeration assumed unsupported.",
                exc_info=True,
            )
            caps.supports_profile_enumeration = False
            return

        if isinstance(resp, dict):
            # Valid response — profile enumeration is supported
            caps.supports_profile_enumeration = True
        else:
            caps.supports_profile_enumeration = False

    async def _probe_roomfit(self, caps: DeviceCapabilities) -> None:
        """Probe RoomFit capability levels 0-4 sequentially.

        Requirement 2.6: determine roomfit_level using a sequential probe
        sequence; the level is set to the highest confirmed level.

        RoomFit uses the standard LV2 PEQ commands with EQLevel: 2 added to
        the JSON payload. There are NO separate getRoomFitStatus/getRoomFitBands/
        setRoomFitBands commands (see docs/corrections.md 2026-06-14).

        Level 0: no RoomFit at all (default)
        Level 1: EQv2GetNewList + EQLevel:2 returns valid JSON (not "unknown command")
        Level 2: EQGetLV2SourceBandEx + EQLevel:2 returns band data with EQBand/EQBandL/EQBandR
        Level 3: implicit from level 2 — band data is parseable (response is dict with bands)
        Level 4: EQSetLV2SourceBand + EQSourceSave + EQLevel:2 both succeed (write + save)
        """
        caps.roomfit_level = 0
        caps.supports_roomfit = False
        caps.supports_roomfit_read = False
        caps.supports_roomfit_write = False

        # Level 1: EQv2GetNewList with EQLevel: 2
        try:
            list_payload = json.dumps({"pluginURI": PLUGIN_URI, "EQLevel": 2})
            resp = await self._client.command(
                f"EQv2GetNewList:{quote(list_payload)}"
            )
            if isinstance(resp, str) and "unknown" in resp.lower():
                # Device doesn't support RoomFit
                return
            if not isinstance(resp, dict):
                return
            # Valid JSON response — level 1
            caps.roomfit_level = 1
            caps.supports_roomfit = True
        except Exception:
            logger.info("RoomFit level 1 probe (EQv2GetNewList+EQLevel:2) failed.")
            return

        # Level 2: EQGetLV2SourceBandEx with EQLevel: 2
        try:
            read_payload = json.dumps({
                "pluginURI": PLUGIN_URI,
                "source_name": "wifi",
                "EQLevel": 2,
            })
            band_resp = await self._client.command(
                f"EQGetLV2SourceBandEx:{quote(read_payload)}"
            )
            if not isinstance(band_resp, dict):
                return
            # Check for band data keys
            has_bands = (
                "EQBand" in band_resp
                or "EQBandL" in band_resp
                or "EQBandR" in band_resp
            )
            if not has_bands:
                return
            caps.roomfit_level = 2
            caps.supports_roomfit_read = True
        except Exception:
            logger.info(
                "RoomFit level 2 probe (EQGetLV2SourceBandEx+EQLevel:2) failed."
            )
            return

        # Level 3: Implicit — band data is parseable (dict with band keys confirmed above)
        caps.roomfit_level = 3

        # Level 4: Write test — EQSourceSave with EQLevel: 2
        # Instead of writing all bands back (which can exceed the device's URL
        # length limit for L/R mode with 12 bands — HTTP 431), we only test
        # that EQSourceSave works. The buffer already has data from our level 2
        # read, so saving it to a temp profile name confirms write capability.
        _PROBE_PROFILE_NAME = "__wiim_rew_sync_probe__"
        try:
            # Save buffer contents to a temporary profile
            save_payload = json.dumps({
                "pluginURI": PLUGIN_URI,
                "source_name": "wifi",
                "Name": _PROBE_PROFILE_NAME,
                "EQLevel": 2,
            })
            save_resp = await self._client.command(
                f"EQSourceSave:{quote(save_payload)}"
            )
            if isinstance(save_resp, str) and "unknown" in save_resp.lower():
                return

            caps.roomfit_level = 4
            caps.supports_roomfit_write = True

            # Cleanup: delete the temporary probe profile (best-effort)
            try:
                delete_payload = json.dumps({
                    "pluginURI": PLUGIN_URI,
                    "Name": _PROBE_PROFILE_NAME,
                    "EQLevel": 2,
                })
                await self._client.command(
                    f"EQv2Delete:{quote(delete_payload)}"
                )
            except Exception:
                logger.debug(
                    "RoomFit probe cleanup (EQv2Delete) failed; non-critical."
                )

        except Exception:
            logger.info("RoomFit level 4 probe (EQSourceSave+EQLevel:2) failed.")
            # Keep at whatever level was last confirmed (level 3)

    async def _probe_multiroom(self, caps: DeviceCapabilities) -> None:
        """Probe GetMultiroomInfo for multiroom role.

        Requirement 2.7: determine the device's multiroom role.
        """
        try:
            resp = await self._client.command("GetMultiroomInfo")
        except Exception:
            logger.warning(
                "GetMultiroomInfo probe failed; assuming solo.", exc_info=True
            )
            caps.role = "solo"
            return

        if not isinstance(resp, dict):
            caps.role = "solo"
            return

        # Parse role: 0=solo, 1=master, 2=slave
        # See docs/wiim_api_notes.md: "Role: 0=solo, 1=master, 2=slave"
        role_value = resp.get("role", resp.get("Role", 0))
        try:
            role_int = int(role_value)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            role_int = 0

        if role_int == 1:
            caps.role = "master"
        elif role_int == 2:
            caps.role = "slave"
        else:
            caps.role = "solo"
