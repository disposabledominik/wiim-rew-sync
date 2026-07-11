"""
Capability prober — runtime detection of WiiM device features.

Probes the connected device through the WiiMHttpClient and populates a
DeviceCapabilities object.  All probes are best-effort: any failure is caught,
logged, and the affected capability is set to its most conservative (safest)
default value.

Probing sequence (read-only -- no probe writes to the device; 2026-07-10
redesign, docs/corrections.md):
  1. getStatusEx            -> model, firmware, uuid, mac_address
  2. getAudioInputEnable    -> source_names
  3. GetAcousticCapability  -> supports_roomfit* (declarative), rc_version
  4. EQGetLV2BandEx         -> supports_peq, supports_lr_filters, max_filters
  5. EQv2GetNewList         -> supports_profile_enumeration
  6. RoomFit fallback probe -> supports_roomfit* (only when step 3
                               unavailable; read-only)
  7. GetMultiroomInfo       -> role

supports_batch_write is NOT probed: it starts as None ("unknown") and the
first real push attempts the batch form, falling back to sequential and
recording the outcome (WiiMAdapter.write_peq) -- the old probe performed a
real EQSetLV2Band write at connect time.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from src.adapters.wiim_commands import PLUGIN_URI, encode_wiim_command
from src.adapters.wiim_http import WiiMHttpClient
from src.models.capabilities import DeviceCapabilities
from src.models.device_capability_file import (
    find_entry,
    get_cached_capability_file,
    merge_into,
)
from src.utils.device_identity import is_wiim_device

logger = logging.getLogger("wiim_rew_sync.wiim_api")


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

        # Step 1: getStatusEx — identity
        await self._probe_status(caps)

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

        # Step 2: getAudioInputEnable — source list
        await self._probe_source_names(caps)

        # Step 3: GetAcousticCapability — declarative subsystem report
        # (single read-only call; RoomFit support comes from here on devices
        # that support the command, replacing the old per-command probe)
        acoustic_ok = await self._probe_acoustic_capability(caps)

        # Step 4: EQGetLV2BandEx — PEQ confirmation & band model
        # (always runs: max_filters and channelMode/supports_lr_filters come
        # from the live band read regardless of what step 3 declared, and it
        # doubles as the PEQ probe on devices without GetAcousticCapability)
        await self._probe_peq(caps)

        # Step 5: EQv2GetNewList — profile enumeration
        await self._probe_profile_enumeration(caps)

        # Step 6: RoomFit fallback probe — only when GetAcousticCapability
        # was unavailable (read-only; no write test exists anymore, see
        # _probe_roomfit's docstring)
        if not acoustic_ok:
            await self._probe_roomfit(caps)

        # Step 7: GetMultiroomInfo — multiroom role
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
        automatically gets capability-file overrides, the default max-bands
        cap (Requirement 7, file-configurable via `"default_max_bands"`,
        #167c), and the source-name fallback (#167b) applied here, with no
        per-caller changes needed. Models absent from the file are returned
        unchanged (full generic probed behaviour).
        """
        loaded = get_cached_capability_file()
        entry = find_entry(caps.model, loaded.entries)
        return merge_into(caps, entry, default_max_bands=loaded.default_max_bands)

    async def _probe_status(self, caps: DeviceCapabilities) -> dict[str, Any]:
        """Probe getStatusEx for device identity."""
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

        return resp

    async def _probe_source_names(self, caps: DeviceCapabilities) -> None:
        """Probe getAudioInputEnable for the device's real enabled source list.

        Replaces the previous getStatusEx 'InputList' parsing, confirmed dead
        on every tested device. getAudioInputEnable returns each input's
        'mode' (the exact source_name value PEQ/RoomFit commands use) and
        whether it's enabled (shown/switchable in the WiiM app), correctly
        excluding hardware-capability entries like 'udisk' that aren't real
        PEQ sources. WiiM Mini returns "unknown command" -- it falls through
        to the merge_into()/capability-file fallback instead (#167).
        """
        try:
            resp = await self._client.command("getAudioInputEnable")
        except Exception:
            logger.warning("getAudioInputEnable probe failed.", exc_info=True)
            return

        if isinstance(resp, str) and "unknown" in resp.lower():
            logger.info("Device has no getAudioInputEnable; using fallback source list.")
            return

        if not isinstance(resp, dict):
            logger.warning("getAudioInputEnable returned non-dict: %r", resp)
            return

        audio_inputs = resp.get("audioInput", [])
        if isinstance(audio_inputs, list):
            caps.source_names = [
                str(item["mode"])
                for item in audio_inputs
                if isinstance(item, dict) and item.get("enable") == 1 and "mode" in item
            ]

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

        # A dict alone is NOT proof of PEQ support: generic LinkPlay firmware
        # answers every EQGetLV2* command with a stock tone-control dict
        # ({"Bass": 0, "EQEnable": 0, "Treble": 0} -- confirmed against real
        # hardware, docs/corrections.md 2026-07-10), which the old
        # isinstance() check accepted as a PEQ device. Require actual band
        # data, same as _probe_roomfit()'s has_bands check.
        has_bands = "EQBand" in resp or "EQBandL" in resp or "EQBandR" in resp
        if not has_bands:
            logger.info(
                "EQGetLV2BandEx returned a dict without band data (%r keys); "
                "PEQ unsupported (generic LinkPlay tone-control response).",
                sorted(resp.keys()),
            )
            caps.supports_peq = False
            caps.supports_lr_filters = False
            return

        # Valid response means PEQ is supported
        caps.supports_peq = True

        # Requirement 2.3: determine supports_lr_filters from channelMode field
        # If channelMode field exists in response, device supports L/R channel PEQ
        caps.supports_lr_filters = "channelMode" in resp

        # Dynamically detect max_filters by counting distinct band letter prefixes
        # in the band response (e.g. a_mode, b_mode, ... l_mode → 12 bands).
        # This count reflects bands available in the device's *current* channel
        # mode at probe time -- per-channel if probed in L/R mode, total if
        # probed in Stereo mode -- confirmed against real hardware
        # (docs/corrections.md, 2026-07-03), matching max_filters' own
        # per-channel-in-L/R semantics, so either key below yields the right
        # number. A device probed in L/R mode has EQBandL/EQBandR and no
        # EQBand -- counting only EQBand was why a 10-band fallback used to
        # exist here.
        eq_band: list[dict[str, object]] = (
            resp.get("EQBand") or resp.get("EQBandL") or resp.get("EQBandR") or []
        )
        band_letters: set[str] = set()
        for entry in eq_band:
            pn = str(entry.get("param_name", ""))
            if "_" in pn:
                band_letters.add(pn.split("_")[0])
        if not band_letters:
            # Band keys exist but hold no parseable a_mode-style entries:
            # not a real EqNp PEQ engine. Never invent a 10-band default for
            # a device that demonstrated none (docs/corrections.md,
            # 2026-07-10 -- the old fallback turned generic-LinkPlay
            # responses into supports_peq=True, max_filters=10).
            caps.supports_peq = False
            caps.supports_lr_filters = False
            caps.max_filters = 0
            return
        caps.max_filters = len(band_letters)

    async def _probe_acoustic_capability(self, caps: DeviceCapabilities) -> bool:
        """Probe GetAcousticCapability -- one read-only declarative report.

        Returns True when the device answered with the real capability
        schema, meaning RoomFit support was determined here and the
        per-command fallback probe (_probe_roomfit) can be skipped.

        Response shapes (all hardware-confirmed, docs/wiim_api_notes.md and
        docs/device_capability_examples/, 2026-07-10):
          - Full schema dict with PEQ/RC/GEQ/... subsystem blocks -- most
            WiiM devices.
          - {"status": "Failed"} -- device has no acoustic-capability
            subsystem at all (WiiM Mini).
          - "unknown command" -- generic LinkPlay firmware.

        RC presence means the full RoomFit workflow works: the band buffer
        is readable, and EQSourceSave persists. There is deliberately no
        write test -- the old level-4 write probe performed a real
        EQSourceSave with live-audio risk (#190) and was removed; every real
        write goes through RoomFitSafeWrite's backup/verify/rollback, which
        catches a genuinely write-incapable device at push time with full
        recovery. RC.Version is stored on caps.rc_version (discriminates the
        out-of-scope RoomCorr* command family's behavior).
        """
        try:
            resp = await self._client.command("GetAcousticCapability")
        except Exception:
            logger.info(
                "GetAcousticCapability probe failed; falling back to "
                "per-command RoomFit probing.",
                exc_info=True,
            )
            return False

        if not isinstance(resp, dict) or "status" in resp:
            # "unknown command" (str) or {"status": "Failed"} -- no
            # declarative data; caller falls back to _probe_roomfit().
            return False
        if "PEQ" not in resp and "RC" not in resp:
            # A dict, but not the capability schema -- treat as unsupported
            # rather than concluding "no RoomFit" from an unknown shape.
            logger.info(
                "GetAcousticCapability returned an unrecognised shape "
                "(%r keys); falling back to per-command RoomFit probing.",
                sorted(resp.keys()),
            )
            return False

        rc_block = resp.get("RC")
        if isinstance(rc_block, dict):
            caps.supports_roomfit = True
            caps.supports_roomfit_read = True
            caps.supports_roomfit_write = True
            caps.rc_version = str(rc_block.get("Version", ""))
        else:
            caps.supports_roomfit = False
            caps.supports_roomfit_read = False
            caps.supports_roomfit_write = False
        return True

    async def _probe_profile_enumeration(self, caps: DeviceCapabilities) -> None:
        """Probe EQv2GetNewList for profile enumeration support.

        Requirement 2.5: determine supports_profile_enumeration by attempting
        EQv2GetNewList -- the command list_peq_profiles() actually uses at
        runtime. EQGetLV2List is confirmed non-functional on current firmware
        (docs/wiim_api_notes.md, "Dead commands -- do not use") -- it always
        returns {"status":"Failed"}, which is still a dict, so the old
        isinstance(resp, dict) check reported success purely by coincidence.
        """
        try:
            resp = await self._client.command(
                encode_wiim_command("EQv2GetNewList", eq_level=1)
            )
        except Exception:
            logger.warning(
                "EQv2GetNewList probe failed; profile enumeration assumed unsupported.",
                exc_info=True,
            )
            caps.supports_profile_enumeration = False
            return

        # A real success response is {"custom": [...], "preset": [...]}, present
        # even when empty. A confirmed-dead/unsupported command instead returns
        # "unknown command" (a string) or {"status":"Failed"} (a dict) -- require
        # both expected keys rather than just rejecting "status", so an
        # unrelated/malformed dict shape (e.g. "{}") doesn't also read as success.
        caps.supports_profile_enumeration = (
            isinstance(resp, dict) and "custom" in resp and "preset" in resp
        )

    async def _probe_roomfit(self, caps: DeviceCapabilities) -> None:
        """Fallback RoomFit probe -- read-only, for devices without
        GetAcousticCapability (see _probe_acoustic_capability above).

        RoomFit uses the standard LV2 PEQ commands with EQLevel: 2 added to
        the JSON payload. There are NO separate getRoomFitStatus/
        getRoomFitBands/setRoomFitBands commands (docs/corrections.md
        2026-06-14).

        Detection is two read-only steps:
          1. EQv2GetNewList + EQLevel:2 -- an empty "custom" list is THE
             no-RoomFit signal (docs/wiim_api_notes.md, Capability
             detection): RoomFit-less devices (WiiM Mini) do NOT return
             "unknown command", they return a valid-looking
             {"custom": [], "preset": []} and silently accept every
             subsequent RoomFit command against dead storage
             (docs/corrections.md, 2026-07-10).
          2. EQGetLV2SourceBandEx + EQLevel:2 + source_name="" -- the global
             band buffer must actually be readable.

        Write capability is set equal to read capability -- there is
        deliberately no write test. The old level-4 probe performed a real
        EQSourceSave (plus an elaborate EQStat/Name capture-restore guard,
        #175/#177/#190) and was removed 2026-07-10; every real write goes
        through RoomFitSafeWrite's backup/verify/rollback, which catches a
        genuinely write-incapable device at push time with full recovery.
        """
        caps.supports_roomfit = False
        caps.supports_roomfit_read = False
        caps.supports_roomfit_write = False

        # Step 1: profile list -- empty "custom" means no RoomFit
        try:
            resp = await self._client.command(
                encode_wiim_command("EQv2GetNewList", eq_level=2)
            )
            if isinstance(resp, str) and "unknown" in resp.lower():
                return
            if not isinstance(resp, dict):
                return
            if not resp.get("custom"):
                return
            caps.supports_roomfit = True
        except Exception:
            logger.info("RoomFit probe (EQv2GetNewList+EQLevel:2) failed.")
            return

        # Step 2: band-buffer read -- RoomFit's global scope requires an
        # explicit empty source_name (docs/wiim_api_notes.md's "source_name
        # & EQLevel Reference"; omitting the key entirely fails against real
        # hardware and once caused a RoomFit-detection regression).
        try:
            band_resp = await self._client.command(
                encode_wiim_command("EQGetLV2SourceBandEx", source_name="", eq_level=2)
            )
            if not isinstance(band_resp, dict):
                return
            has_bands = (
                "EQBand" in band_resp
                or "EQBandL" in band_resp
                or "EQBandR" in band_resp
            )
            if not has_bands:
                return
            caps.supports_roomfit_read = True
            caps.supports_roomfit_write = True
        except Exception:
            logger.info(
                "RoomFit probe (EQGetLV2SourceBandEx+EQLevel:2) failed."
            )

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
