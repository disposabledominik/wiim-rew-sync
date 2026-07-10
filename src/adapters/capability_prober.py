"""
Capability prober — runtime detection of WiiM device features.

Probes the connected device through the WiiMHttpClient and populates a
DeviceCapabilities object.  All probes are best-effort: any failure is caught,
logged, and the affected capability is set to its most conservative (safest)
default value.

Probing sequence:
  1. getStatusEx        -> model, firmware, uuid, mac_address
  2. getAudioInputEnable -> source_names
  3. EQGetLV2BandEx     -> supports_peq, supports_lr_filters
  4. EQSetLV2Band (batch) -> supports_batch_write
  5. EQGetLV2List       -> supports_profile_enumeration
  6. RoomFit levels 0-4 -> roomfit_level, supports_roomfit*
  7. GetMultiroomInfo   -> role

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

        # Step 2: getAudioInputEnable — source list
        await self._probe_source_names(caps)

        # Step 3: EQGetLV2BandEx — PEQ support & channel mode
        await self._probe_peq(caps)

        # Step 4: Batch write test
        await self._probe_batch_write(caps, status)

        # Step 5: EQGetLV2List — profile enumeration
        await self._probe_profile_enumeration(caps)

        # Step 6: RoomFit sequential probe (levels 0-4)
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
        avoid altering device state during probing. The write-back preserves
        the band *values* but not the live source's "this equals saved preset
        X" Name association: a raw EQSetLV2Band write drops it even with
        byte-identical bands (confirmed on real hardware, docs/corrections.md
        2026-07-05 -- the same mechanism as the RoomFit level-4 probe fix,
        #175, just via a plain write instead of save-then-delete). The read
        response itself echoes which source is live (`source_name`), so the
        pre-probe Name is restored via EQv2SourceLoad scoped to that same
        source once the write attempt is done -- PEQ's EQv2SourceLoad
        requires an explicit source_name (unlike RoomFit's global one) or it
        silently targets whatever's live instead (docs/corrections.md,
        2026-07-03).

        `_probe_batch_write()` runs before the wizard's source is chosen, so
        it has no source_name of its own to scope the read/write to -- this
        is why it uses the bare/live-source commands rather than the
        per-source ones `write_peq()` uses in production.

        This capture-then-restore shape is duplicated (not shared) with
        `_probe_roomfit()`'s level-4 probe below and with
        `WiiMAdapter.restore_roomfit_active_profile()` -- deliberately, not
        an oversight: this prober has no `WiiMAdapter` instance yet (probing
        determines the capabilities an adapter would need to be constructed
        with), so it can't call that shared helper and talks to `self._client`
        directly instead. If a third probe ever needs this pattern, consider
        a small `CapabilityProber`-local helper before copying this block
        again.
        """
        if not caps.supports_peq:
            caps.supports_batch_write = False
            return

        original_active_name = ""
        live_source_name = ""
        write_issued = False
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
            original_active_name = str(read_resp.get("Name", ""))
            live_source_name = str(read_resp.get("source_name", ""))

            if not eq_band:
                caps.supports_batch_write = False
                return

            # Build the write payload — write the same data back
            command = encode_wiim_command(
                "EQSetLV2Band", {"channelMode": channel_mode, "EQBand": eq_band}
            )
            write_issued = True
            resp = await self._client.command(command)

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
        finally:
            # Restore the live source's pre-probe Name association, if the
            # write was actually attempted and there was a name to restore --
            # see the docstring above. Run even if the write itself raised,
            # since a client-side timeout doesn't guarantee the device didn't
            # still apply it.
            if write_issued and original_active_name and live_source_name:
                try:
                    await self._client.command(
                        encode_wiim_command(
                            "EQv2SourceLoad",
                            {"Name": original_active_name},
                            source_name=live_source_name,
                        )
                    )
                except Exception:
                    logger.warning(
                        "Failed to restore PEQ active preset %r on source %r "
                        "after batch-write capability probe; device may show "
                        "no active preset until the user re-selects one.",
                        original_active_name, live_source_name,
                        exc_info=True,
                    )

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

        The level-4 write test has observable side effects on the device
        (it saves and deletes a throwaway profile) -- both the pre-probe
        active profile Name and the pre-probe DSP on/off state (EQStat) are
        captured before the test and restored afterward (#177, #190), so a
        routine capability probe never leaves the device in a different
        state than it found it.

        Live-audio safety (#190): what's applied to actual playback when
        RoomFit is enabled is the persisted, *selected* named profile, not
        the transient working buffer -- and a profile stays selected even
        while disabled. If EQStat is "Off" but a real profile is selected,
        the level-4 test is skipped entirely rather than attempted and
        restored afterward, since restoring after the fact can't undo audio
        that was already audible. `roomfit_level` then stays at 3 (write
        unconfirmed) for that connection.
        """
        caps.roomfit_level = 0
        caps.supports_roomfit = False
        caps.supports_roomfit_read = False
        caps.supports_roomfit_write = False

        # Level 1: EQv2GetNewList with EQLevel: 2
        try:
            resp = await self._client.command(
                encode_wiim_command("EQv2GetNewList", eq_level=2)
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

        # Level 2: EQGetLV2SourceBandEx with EQLevel: 2 and an explicit empty
        # source_name -- RoomFit's band read/write requires source_name="" per
        # docs/wiim_api_notes.md's "source_name & EQLevel Reference" (omitting
        # the key entirely, as a prior pass mistakenly did, fails against real
        # hardware and was the root cause of a RoomFit-detection regression).
        try:
            band_resp = await self._client.command(
                encode_wiim_command("EQGetLV2SourceBandEx", source_name="", eq_level=2)
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
        #
        # The buffer "adopts" whatever name it's saved under (RoomFit Write
        # workflow, docs/wiim_api_notes.md) -- saving to this throwaway name
        # and then deleting that same name orphans the buffer from whatever
        # profile was genuinely active before the probe ran: a subsequent
        # status read's Name comes back "", and the WiiM app itself shows
        # RoomFit as deselected (confirmed on real hardware, docs/
        # corrections.md 2026-07-05). Capture the pre-probe active name from
        # the level 2 read above and restore it via EQv2SourceLoad once
        # cleanup is done, so a routine capability probe doesn't silently
        # deactivate the user's actual RoomFit selection.
        original_active_name = str(band_resp.get("Name", ""))
        original_eqstat_on = band_resp.get("EQStat") == "On"

        # SAFETY (#190): what's actually applied to live audio when EQStat
        # is "On" is the persisted, *named* profile that's currently
        # selected -- not the transient working buffer this probe reads and
        # writes. A profile stays "selected" even while EQStat is "Off"
        # (docs/wiim_api_notes.md's DSP on/off toggle section), so a device
        # can have RoomFit disabled while a named profile with completely
        # unknown -- possibly extreme -- filter values sits selected
        # underneath. Something in this test's sequence (`EQSourceSave`
        # below, or the `EQv2SourceLoad` name-restore in the `finally` block)
        # can flip EQStat from "Off" to "On" as an undocumented side effect
        # -- curl reproduction (docs/corrections.md, 2026-07-06) confirmed
        # `EQv2SourceLoad` alone does this and `EQSourceSave` alone does not,
        # making the `finally` block's own restore call the more likely
        # culprit than the `EQSourceSave` call this comment originally named.
        # Exact mechanism aside, if EQStat flips while a real profile is
        # selected, its actual filter values become audible -- a genuine
        # hearing/speaker-damage risk at loud volume, not a cosmetic one.
        # There is no way to test write capability here without risking
        # exactly that, so when EQStat is "Off" *and* a real profile is
        # selected, skip the live write test entirely rather than try to
        # race the side effect after the fact. `roomfit_level` stays at 3
        # (write unconfirmed) until the device is probed again with RoomFit
        # already enabled (e.g. after the user enables it in the WiiM Home
        # app, which is the only supported way to toggle it -- see "Not
        # implemented" above) -- "safety before convenience" (CLAUDE.md).
        #
        # Safe to proceed when EQStat is already "On" (whatever's selected is
        # already audible; this test cannot introduce new audible content,
        # only relabel-and-restore the same bytes -- confirmed unchanged
        # end-to-end on real hardware, docs/corrections.md 2026-07-05) or
        # when EQStat is "Off" with nothing selected (`original_active_name`
        # empty -- a fresh/never-configured device has no real profile whose
        # content could be exposed).
        if not original_eqstat_on and original_active_name:
            logger.info(
                "Skipping RoomFit level 4 write-capability test: EQStat is "
                "Off but profile %r is still selected -- testing write here "
                "risks briefly applying its real filter values to live "
                "audio if this test's sequence re-enables it as a side "
                "effect.",
                original_active_name,
            )
            return

        _PROBE_PROFILE_NAME = "__wiim_rew_sync_probe__"
        save_issued = False
        try:
            # Save buffer contents to a temporary profile (no source_name --
            # see the level 2 probe above).
            save_issued = True
            save_resp = await self._client.command(
                encode_wiim_command(
                    "EQSourceSave", {"Name": _PROBE_PROFILE_NAME}, eq_level=2
                )
            )
            if isinstance(save_resp, str) and "unknown" in save_resp.lower():
                return

            caps.roomfit_level = 4
            caps.supports_roomfit_write = True

        except Exception:
            logger.info("RoomFit level 4 probe (EQSourceSave+EQLevel:2) failed.")
            # Keep at whatever level was last confirmed (level 3)
        finally:
            # Restore RoomFit's DSP on/off toggle to its pre-probe state FIRST
            # (#190), ahead of the delete/name-restore cleanup below. By this
            # point the guard above has already ruled out the one case where
            # a wrong EQStat could expose a real, unknown profile's filter
            # values (Off-with-something-selected) -- so this restore is
            # defense-in-depth, not the primary safeguard: it holds even if
            # the guard's reasoning about which states are "safe" turns out
            # to be incomplete. Every extra round-trip before correcting
            # EQStat (delete, then load) widens whatever window remains for
            # no benefit -- especially the `EQv2SourceLoad` name-restore that
            # follows, confirmed (docs/corrections.md, 2026-07-06) to
            # unconditionally turn EQStat back on -- so this call goes out
            # immediately, before either of them. Unconditional (not gated on
            # save_issued): the property must hold even if the read that
            # populated original_eqstat_on was somehow stale, and the command
            # is a cheap no-op if EQStat was never touched.
            try:
                await self._client.command(
                    encode_wiim_command(
                        "EQChangeSourceFX" if original_eqstat_on else "EQSourceOff",
                        source_name="",
                        eq_level=2,
                    )
                )
            except Exception:
                logger.warning(
                    "Failed to restore RoomFit on/off state (was %s) after "
                    "capability probe; device may show RoomFit as %s instead.",
                    "On" if original_eqstat_on else "Off",
                    "Off" if original_eqstat_on else "On",
                    exc_info=True,
                )
            # Cleanup: delete the temporary probe profile (best-effort). Run
            # this unconditionally once the save command was issued -- a
            # timeout or error response doesn't guarantee the device didn't
            # still create the profile before the failure, so skipping
            # cleanup on those paths would leak it permanently.
            if save_issued:
                try:
                    await self._client.command(
                        encode_wiim_command(
                            "EQv2Delete", {"Name": _PROBE_PROFILE_NAME}, eq_level=2
                        )
                    )
                except Exception:
                    logger.debug(
                        "RoomFit probe cleanup (EQv2Delete) failed; non-critical."
                    )
            # Restore the buffer's pre-probe name association, if it had
            # one -- see the comment above the original_active_name capture
            # above. Deliberately NOT nested under `if save_issued:`: the
            # buffer's Name can change independently of whether the throwaway
            # save succeeded (e.g. the level-2 read itself already loaded
            # something), so this must run whenever cleanup runs, not only
            # when a profile was created to clean up.
            if original_active_name:
                try:
                    await self._client.command(
                        encode_wiim_command(
                            "EQv2SourceLoad",
                            {"Name": original_active_name},
                            eq_level=2,
                        )
                    )
                except Exception:
                    logger.warning(
                        "Failed to restore RoomFit active profile %r after "
                        "capability probe; device may show no active "
                        "profile until the user re-selects one.",
                        original_active_name,
                        exc_info=True,
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
