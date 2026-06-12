"""
Capability prober — runtime detection of WiiM device features.

Probes the connected device through the WiiMHttpClient and populates a
DeviceCapabilities object.  All probes are best-effort: any failure is caught,
logged, and the affected capability is set to its most conservative (safest)
default value.

Probing sequence:
  1. getStatusEx        -> model, firmware, uuid, mac_address, source_names
  2. EQGetLV2BandEx     -> supports_peq, supports_channel_peq
  3. EQSetLV2Band (batch) -> supports_batch_write
  4. EQGetLV2List       -> supports_profile_enumeration
  5. RoomFit levels 0-4 -> roomfit_level, supports_roomfit*
  6. GetMultiroomInfo   -> role

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from src.adapters.wiim_http import WiiMHttpClient
from src.models.capabilities import DeviceCapabilities

logger = logging.getLogger("wiim_rew_sync.wiim_api")

# Known WiiM device project prefixes.
# Requirement 2.10: never hard-code capabilities by model name alone — but we
# DO use the project field to distinguish WiiM from generic LinkPlay.
# ASSUMPTION: All WiiM devices have a project field starting with "WiiM_".
WIIM_PROJECT_PREFIXES = (
    "WiiM_Mini",
    "WiiM_Pro",
    "WiiM_Amp",
    "WiiM_Ultra",
    "WiiM_Sound",
)

PLUGIN_URI = "http://moddevices.com/plugins/caps/EqNp"


def _is_wiim_device(project: str) -> bool:
    """Return True if the project field indicates a WiiM device."""
    return any(project.startswith(prefix) for prefix in WIIM_PROJECT_PREFIXES)


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
        is_wiim = _is_wiim_device(caps.model)

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
            return caps

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

        # max_filters for WiiM is always 10 (if PEQ is supported)
        caps.max_filters = 10 if caps.supports_peq else 0

        return caps

    # ------------------------------------------------------------------
    # Internal probe steps
    # ------------------------------------------------------------------

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
            import json

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
            caps.supports_channel_peq = False
            return

        if not isinstance(resp, dict):
            logger.warning("EQGetLV2BandEx returned non-dict: %r", resp)
            caps.supports_peq = False
            caps.supports_channel_peq = False
            return

        # Valid response means PEQ is supported
        caps.supports_peq = True

        # Requirement 2.3: determine supports_channel_peq from channelMode field
        # If channelMode field exists in response, device supports channel PEQ
        caps.supports_channel_peq = "channelMode" in resp

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
            import json

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

        Level 0: no RoomFit at all (default)
        Level 1: getRoomFitStatus returns non-error response
        Level 2: getRoomFitBands returns readable filter data
        Level 3: filter data is parseable (implicit from level 2 success)
        Level 4: setRoomFitBands (write) succeeds
        """
        # ASSUMPTION: RoomFit API uses getRoomFitStatus, getRoomFitBands, and
        # setRoomFitBands commands. These are partially undocumented (see
        # docs/wiim_api_notes.md "RoomFit API (Experimental)" section).

        caps.roomfit_level = 0
        caps.supports_roomfit = False
        caps.supports_roomfit_read = False
        caps.supports_roomfit_write = False

        # Level 1: Check if RoomFit is present
        try:
            resp = await self._client.command("getRoomFitStatus")
            if isinstance(resp, str) and "unknown" in resp.lower():
                # Device doesn't support RoomFit
                return
            # Non-error response -- level 1 at minimum
            caps.roomfit_level = 1
            caps.supports_roomfit = True
        except Exception:
            logger.info("RoomFit level 1 probe (getRoomFitStatus) failed.")
            return

        # Level 2: Check if RoomFit bands are readable
        try:
            resp = await self._client.command("getRoomFitBands")
            if isinstance(resp, str) and "unknown" in resp.lower():
                return
            if isinstance(resp, dict):
                caps.roomfit_level = 2
                caps.supports_roomfit_read = True
            else:
                # Non-dict, non-error string — treat as success at level 2
                # if it's not an error indicator
                if isinstance(resp, str) and resp.strip():
                    caps.roomfit_level = 2
                    caps.supports_roomfit_read = True
        except Exception:
            logger.info("RoomFit level 2 probe (getRoomFitBands) failed.")
            return

        # Level 3: Data is parseable (implicit from level 2 success with dict)
        if caps.roomfit_level >= 2 and isinstance(resp, dict):
            caps.roomfit_level = 3

        # Level 4: Write test — attempt setRoomFitBands with current data
        try:
            # Read current data and write it back unchanged
            if isinstance(resp, dict):
                import json

                payload = quote(json.dumps(resp))
                write_resp = await self._client.command(f"setRoomFitBands:{payload}")
                if isinstance(write_resp, str) and "unknown" in write_resp.lower():
                    return
                caps.roomfit_level = 4
                caps.supports_roomfit_write = True
        except Exception:
            logger.info("RoomFit level 4 probe (setRoomFitBands) failed.")
            # Keep at whatever level was last confirmed

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
