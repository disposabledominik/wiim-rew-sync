"""
Safe Write Protocol - five-step backup/write/verify/commit-or-rollback sequence.

Implements the mandatory safety protocol for all PEQ device writes:
1. Backup current state
2. Write new settings
3. Read-back (fresh call)
4. Verify via band_matches()
5a. Commit on success / 5b. Rollback on failure

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode
from src.models.peq import PEQSettings
from src.repository.backup_manager import (
    load_backup_json,
    parse_backup_filters,
    parse_backup_restore_metadata,
)
from src.translator.wiim_generator import clamp_filters_for_verification
from src.utils.fp_compare import band_matches

if TYPE_CHECKING:
    from src.adapters.command_queue import WiiMCommandQueue
    from src.adapters.wiim_adapter import WiiMAdapter
    from src.repository.backup_manager import BackupManager

logger = logging.getLogger("wiim_rew_sync.app")


@dataclass
class WriteResult:
    """Result of a safe write operation."""

    success: bool
    rollback_success: bool | None = None  # None if no rollback needed
    backup_path: Path | str | None = None
    error_message: str | None = None
    # Populated only on success, from the same read-back used to verify the
    # write -- so the UI can show exactly what's on the device, not just what
    # was intended. Left None on failure: the rolled-back/deleted state isn't
    # useful to show, only the failure message is.
    read_back: PEQSettings | None = None


def compare_band_lists(
    intended_bands: list[CanonicalFilter],
    read_back_bands: list[CanonicalFilter],
) -> bool:
    """Compare two band lists element by element using band_matches.

    If the device returns more bands than were written (e.g. 12-band device
    with 10-band write), only the first N written bands are verified. Extra
    bands on the device are ignored (they retain their previous values and
    are not part of this write's intent).
    """
    # Verify up to the number of intended bands
    compare_count = min(len(intended_bands), len(read_back_bands))
    if compare_count == 0:
        # Vacuous pass is only legitimate when both sides are genuinely
        # empty (e.g. a write that clears all bands). Any other empty
        # overlap — intended bands the device didn't echo back, or
        # read-back bands when none were intended — is a verification
        # failure, not nothing-to-compare.
        return len(intended_bands) == 0 and len(read_back_bands) == 0
    return all(
        band_matches(intended, actual)
        for intended, actual in zip(
            intended_bands[:compare_count],
            read_back_bands[:compare_count],
            strict=True,
        )
    )


def _clamped_for_verification(settings: PEQSettings, max_bands: int) -> PEQSettings:
    """Build the write-verification baseline: settings as they'll actually
    land on the device, not as originally imported.

    generate_wiim_band_array() truncates to max_bands and clamps out-of-range
    gain/Q at write time without mutating the caller's CanonicalFilter list.
    Comparing against the original, pre-clamp values would guarantee a
    mismatch (and a spurious rollback) for every band that needed clamping.
    """
    if settings.channel_mode == ChannelMode.STEREO:
        return PEQSettings(
            source_name=settings.source_name,
            channel_mode=ChannelMode.STEREO,
            bands=clamp_filters_for_verification(settings.bands, max_bands),
        )
    return PEQSettings(
        source_name=settings.source_name,
        channel_mode=ChannelMode.LR,
        bands_l=clamp_filters_for_verification(settings.bands_l or [], max_bands),
        bands_r=clamp_filters_for_verification(settings.bands_r or [], max_bands),
    )


def verify_bands(intended: PEQSettings, read_back: PEQSettings) -> bool:
    """Compare intended vs read-back bands using tolerance predicates.

    For stereo mode, compares the .bands lists.
    For L/R mode, compares both .bands_l and .bands_r lists.

    Returns True if all bands match within tolerance.
    """
    if intended.channel_mode == ChannelMode.STEREO:
        return compare_band_lists(intended.bands, read_back.bands)
    else:
        # L/R mode: verify both channels
        left_ok = compare_band_lists(intended.bands_l or [], read_back.bands_l or [])
        right_ok = compare_band_lists(intended.bands_r or [], read_back.bands_r or [])
        return left_ok and right_ok


def _describe_first_mismatch(intended: PEQSettings, read_back: PEQSettings) -> str:
    """Find and describe the first band that fails verification, for logging.

    Best-effort diagnostic only -- never raises, never affects control flow.
    verify_bands() above remains the single source of truth for pass/fail.
    """
    channels: list[tuple[str, list[CanonicalFilter], list[CanonicalFilter]]]
    if intended.channel_mode == ChannelMode.STEREO:
        channels = [("stereo", intended.bands, read_back.bands)]
    else:
        channels = [
            ("L", intended.bands_l or [], read_back.bands_l or []),
            ("R", intended.bands_r or [], read_back.bands_r or []),
        ]

    for label, intended_bands, actual_bands in channels:
        # Mirror compare_band_lists() exactly: it only ever looks at the
        # first compare_count bands of each side, so a length difference
        # alone is NOT a failure (e.g. a 12-band device read-back vs a
        # 10-band intended write -- see TestBandCountTolerance). Checking
        # length before content here previously produced a misleading
        # "band count mismatch" message that masked the real cause (a
        # clamped value, in the case this diagnostic was added to debug).
        compare_count = min(len(intended_bands), len(actual_bands))
        if compare_count == 0:
            if len(intended_bands) == 0 and len(actual_bands) == 0:
                continue  # vacuous pass, matches compare_band_lists()
            return (
                f"channel={label}: nothing to compare "
                f"(intended={len(intended_bands)}, read_back={len(actual_bands)}) -- "
                f"compare_band_lists() fails whenever exactly one side is empty"
            )
        for i in range(compare_count):
            want, got = intended_bands[i], actual_bands[i]
            if not band_matches(want, got):
                return (
                    f"channel={label} band={i}: intended "
                    f"type={want.type} freq={want.frequency_hz} gain={want.gain_db} "
                    f"q={want.q} vs read_back "
                    f"type={got.type} freq={got.frequency_hz} gain={got.gain_db} q={got.q}"
                )
        # All compare_count bands matched -- this channel did not cause the
        # failure (compare_band_lists() ignores any extra bands beyond
        # compare_count), even if intended/read_back lengths differ. Move on
        # to the next channel rather than reporting a false cause.
    return "no per-band mismatch found (unexpected -- verify_bands() said it failed)"


class SafeWrite:
    """Five-step safe write protocol for PEQ device writes.

    Ensures every write is backed up, verified, and rolled back on failure.

    Device-visible contract (redesigned 2026-07-06 -- mirrors
    RoomFitSafeWrite, see docs/corrections.md):
      - Success: PEQ is turned on for ``source_name`` if it was off, via a
        deliberate, confirmed command (``enable_peq()``) -- not left to an
        unconfirmed API side effect. This is the intended behavior: a user
        pushing PEQ filters through this app wants them audible.
      - Failure (verification mismatch + rollback, or the critical
        manual-recovery path): the source's enable-state *before this call*
        is restored -- a failed push must have no lasting device-visible
        effect.
      - ``undo()`` (a separate, later user action) restores the *original
        push's* full pre-state: previous bands and previous enable-state.

    Args:
        adapter: WiiMAdapter for device read/write operations.
        backup_manager: BackupManager for creating state snapshots.
        queue: Optional command queue for sequential writes.
    """

    def __init__(
        self,
        adapter: WiiMAdapter,
        backup_manager: BackupManager,
        queue: WiiMCommandQueue | None = None,
    ) -> None:
        self._adapter = adapter
        self._backup_manager = backup_manager
        self._queue = queue

    async def execute(
        self,
        source_name: str,
        settings: PEQSettings,
        on_stage: Callable[[str], None] | None = None,
    ) -> WriteResult:
        """Execute the five-step safe write protocol.

        Steps:
            1. Backup current device state
            2. Write new settings to device
            3. Read-back device state (fresh call)
            4. Verify each band matches intended settings
            5a. Commit (return success) OR
            5b. Rollback (restore backup state, verify rollback)

        See the class docstring for the enable-state device-visible
        contract: success turns PEQ on for ``source_name`` if it was off;
        failure restores the source's original enable-state.

        Args:
            source_name: Audio input source (e.g. "wifi", "bluetooth").
            settings: PEQ settings to write to the device.
            on_stage: Optional callback invoked with one of "backing_up",
                "writing", "verifying", "done" as each step begins -- lets a
                caller (e.g. the GUI's push stepper) reflect real progress
                instead of only a start/end signal. Not called with "done"
                on failure; the caller is expected to treat whichever stage
                it last saw as the one that failed (see #189).

        Returns:
            WriteResult indicating success/failure and rollback status.
        """
        capabilities = self._adapter.capabilities

        # Step 1: Backup current device state
        if on_stage is not None:
            on_stage("backing_up")
        current_settings = await self._adapter.read_peq(source_name)
        backup_path = self._backup_manager.create_backup(
            current_settings, capabilities, "pre_write",
            pre_write_peq_enabled=current_settings.enabled,
        )

        # Step 2: Write new settings. WiiMAdapter.write_peq() sets channelMode
        # inline as part of the same EQSetLV2SourceBand write.
        if on_stage is not None:
            on_stage("writing")
        await self._adapter.write_peq(source_name, settings, self._queue)

        # Step 3: Read-back (fresh call to device)
        if on_stage is not None:
            on_stage("verifying")
        read_back = await self._adapter.read_peq(source_name)

        # Step 4: Verify each band matches. Compare against what was
        # *actually* written (post-truncation/clamping), not the raw
        # imported values -- otherwise any band that needed clamping would
        # always read back "different" from its pre-clamp original and
        # fail verification spuriously.
        verify_settings = _clamped_for_verification(settings, capabilities.max_filters)
        if verify_bands(verify_settings, read_back):
            # Step 5a: Commit - verification passed. Turn PEQ on if it was
            # off -- deliberate, confirmed command, best-effort so a
            # verified-correct write still reports success even if this
            # polish step hiccups (mirrors RoomFitSafeWrite's success-path
            # enable_roomfit() call).
            try:
                await self._adapter.enable_peq(source_name)
            except Exception:
                logger.warning(
                    "Failed to enable PEQ on source '%s' after successful "
                    "push; device may still show PEQ off.",
                    source_name,
                    exc_info=True,
                )
            if on_stage is not None:
                on_stage("done")
            return WriteResult(success=True, backup_path=backup_path, read_back=read_back)

        # Step 5b: Rollback - verification failed
        logger.warning(
            "PEQ write verification failed for source '%s': %s",
            source_name,
            _describe_first_mismatch(verify_settings, read_back),
        )
        return await self._rollback(source_name, current_settings, backup_path)

    async def _rollback(
        self,
        source_name: str,
        original_settings: PEQSettings,
        backup_path: Path,
    ) -> WriteResult:
        """Execute rollback: restore original state and verify.

        Creates a pre_rollback backup of the current (post-failed-write) state,
        writes the original settings back, and verifies the rollback.

        Args:
            source_name: Audio input source.
            original_settings: The backed-up settings to restore.
            backup_path: Path to the pre_write backup file.

        Returns:
            WriteResult with rollback status.

        # TODO (low-priority tech debt): restoring via write_peq() below takes the
        # same one-band-per-call sequential path as the forward write on non-batch
        # devices -- it is not a separately-atomic path. If the failed write did
        # not change channelMode, this rollback write can itself be interrupted
        # mid-sequence, leaving a third state matching neither the original nor
        # the attempted write. Narrow corner case (non-batch device AND a mode
        # switch involved). See docs/corrections.md, 2026-07-04.
        """
        capabilities = self._adapter.capabilities

        # Create pre_rollback backup of current (corrupted) state
        current_state = await self._adapter.read_peq(source_name)
        self._backup_manager.create_backup(current_state, capabilities, "pre_rollback")

        # Write backup state back via queue
        await self._adapter.write_peq(source_name, original_settings, self._queue)

        # Restore the source's original enable-state -- a failed push must
        # have no lasting device-visible effect, regardless of whether the
        # band rollback below verifies successfully. Best-effort, mirrors
        # RoomFitSafeWrite's failure-path enable-state restore.
        try:
            await self._adapter.set_peq_enabled(source_name, original_settings.enabled)
        except Exception:
            logger.warning(
                "Failed to restore PEQ enable-state to %s on source '%s' "
                "after rollback.",
                "On" if original_settings.enabled else "Off",
                source_name,
                exc_info=True,
            )

        # Verify rollback succeeded. Same reasoning as the primary write
        # verify above: original_settings may carry more bands than
        # max_filters (the device can report more bands than this app
        # writes -- see clamp_filters_for_verification's docstring), and
        # write_peq() truncates to max_filters when restoring it.
        rollback_read_back = await self._adapter.read_peq(source_name)
        verify_original = _clamped_for_verification(original_settings, capabilities.max_filters)
        if verify_bands(verify_original, rollback_read_back):
            return WriteResult(
                success=False,
                rollback_success=True,
                backup_path=backup_path,
                error_message="Write verification failed; original state restored.",
            )

        # Rollback failed - CRITICAL
        logger.critical(
            "Rollback FAILED. Manual recovery required. Backup file: %s",
            backup_path,
        )
        return WriteResult(
            success=False,
            rollback_success=False,
            backup_path=backup_path,
            error_message=(
                f"Write verification AND rollback failed. "
                f"Manual recovery required. Backup: {backup_path}"
            ),
        )

    async def undo(
        self,
        backup_path: str | Path,
        source_name: str,
        on_stage: Callable[[str], None] | None = None,
    ) -> WriteResult:
        """Undo a previously-successful PEQ push using its backup file.

        Restores the source's previous bands (via ``execute()``, the normal
        write/verify/rollback protocol) and its previous enable-state
        together.

        This can't just delegate to ``execute()`` alone: ``execute()``'s own
        success path always turns PEQ on (a direct push implies consent to
        hear it), but undo is restoring a *previous* state that might have
        been disabled -- trusting ``execute()`` alone here would incorrectly
        force PEQ on during every undo. So the enable-state captured in the
        backup is applied as a correction *after* ``execute()`` returns,
        mirroring ``RoomFitSafeWrite.undo()``'s equivalent correction of its
        own ``execute()``'s always-activate success path.

        Args:
            backup_path: Path to the backup JSON file the original push created.
            source_name: Audio input source to restore.
            on_stage: Optional callback forwarded to the bands-restore
                ``execute()`` call (see its own ``on_stage`` for the contract).

        Returns:
            WriteResult from the bands-restore ``execute()`` call.
        """
        path = Path(backup_path)
        backup_data = load_backup_json(path)
        filters, channel_mode, filters_l, filters_r = parse_backup_filters(backup_data)
        # No "empty backup" guard here (unlike RoomFitSafeWrite.undo()): a PEQ
        # source with zero bands is a legitimate state (flat EQ, no filters
        # applied), and parse_backup_filters() can't distinguish "backup
        # legitimately captured zero bands" from "backup is malformed" --
        # both parse to an empty list. Rejecting the former would make undo
        # impossible for a push that happened while a source had no filters.
        _, _, _, pre_write_peq_enabled = parse_backup_restore_metadata(backup_data)

        if channel_mode.is_lr:
            settings = PEQSettings(
                source_name=source_name,
                channel_mode=ChannelMode.LR,
                bands_l=filters_l or [],
                bands_r=filters_r or [],
            )
        else:
            settings = PEQSettings(
                source_name=source_name,
                channel_mode=ChannelMode.STEREO,
                bands=filters,
            )

        result = await self.execute(source_name, settings, on_stage=on_stage)
        if not result.success:
            return result

        if pre_write_peq_enabled is not None:
            try:
                await self._adapter.set_peq_enabled(source_name, pre_write_peq_enabled)
            except Exception:
                logger.warning(
                    "Failed to restore PEQ enable-state to %s on source "
                    "'%s' after undo.",
                    "On" if pre_write_peq_enabled else "Off",
                    source_name,
                    exc_info=True,
                )

        return result


class RoomFitSafeWrite:
    """Verify-and-rollback wrapper for RoomFit named-profile writes.

    Unlike PEQ's SafeWrite, a RoomFit write targets a *named* profile that
    may or may not have existed before this write — so rollback has two
    shapes instead of one:
      - Profile already existed: restore its previous bands (RESTORE).
      - Profile is brand-new: delete the profile we just created (DELETE_NEW),
        since there's no prior state to go back to.

    Device-visible contract (redesigned 2026-07-05 -- see docs/corrections.md):
      - Success: ``profile_name`` becomes the device's active/selected
        profile and RoomFit is turned on if it was off, via deliberate,
        confirmed commands (not left to an unconfirmed API side effect).
        This is the intended behavior, not a suppressed side effect --
        a user pushing a RoomFit profile through this app wants it applied.
      - Failure (verification mismatch + rollback, or the critical
        manual-recovery path): the profile that was active and RoomFit's
        on/off state *before this call* are restored -- a failed push must
        have no lasting device-visible effect.
      - ``undo()`` (a separate, later user action) restores the *original
        push's* full pre-state: previous bands (if an existing profile was
        overwritten), previous selection, and previous on/off state. It
        never deletes a profile created by a new-profile push (kept in
        storage for the user to manage via "Presets on Device").

    Args:
        adapter: WiiMAdapter for device read/write operations.
        backup_manager: BackupManager for creating state snapshots of an
            overwritten profile's previous bands, and RoomFit's pre-write
            selection/enable state (used by ``undo()``).
    """

    def __init__(self, adapter: WiiMAdapter, backup_manager: BackupManager) -> None:
        self._adapter = adapter
        self._backup_manager = backup_manager

    async def execute(
        self,
        source_name: str,
        profile_name: str,
        filters: list[CanonicalFilter],
        channel_mode: ChannelMode,
        filters_l: list[CanonicalFilter] | None = None,
        filters_r: list[CanonicalFilter] | None = None,
        on_stage: Callable[[str], None] | None = None,
    ) -> WriteResult:
        """Write a RoomFit profile, then verify and roll back on mismatch.

        See the class docstring for the success/failure device-visible
        contract.

        Args:
            source_name: Audio input source (e.g. "wifi").
            profile_name: Name of the RoomFit profile to write.
            filters: Stereo-mode filters (ignored when channel_mode is LR).
            channel_mode: ChannelMode for the write.
            filters_l: Left channel filters (required when channel_mode is LR).
            filters_r: Right channel filters (required when channel_mode is LR).
            on_stage: Optional callback invoked with one of "backing_up",
                "writing", "verifying", "done" as each step begins (see
                ``SafeWrite.execute``'s ``on_stage`` for the full contract;
                not called with "done" on failure).

        Returns:
            WriteResult indicating success/failure and rollback status.
            ``backup_path`` is always populated on success (including a
            new-profile push, which backs up an empty-bands metadata-only
            record purely so ``undo()`` can later restore selection/enable
            state -- there's no prior content to restore for a new profile).
        """
        # These two reads are independent (one inspects the active-profile
        # buffer, the other lists saved profiles) -- run concurrently rather
        # than paying two sequential round trips on every push/undo, matching
        # the same asyncio.gather() pattern already used for independent
        # device reads elsewhere (smoke #174, _do_list_presets()).
        # return_exceptions=True so a get_roomfit_status() failure (handled
        # below as best-effort/non-fatal) can't cancel the still-required
        # list_roomfit_profiles() call, and vice versa.
        if on_stage is not None:
            on_stage("backing_up")
        status_result, profiles_result = await asyncio.gather(
            self._adapter.get_roomfit_status(),
            self._adapter.list_roomfit_profiles(source_name),
            return_exceptions=True,
        )

        if isinstance(status_result, BaseException):
            original_active_name = ""
            original_enabled = False
            logger.warning(
                "Failed to read RoomFit status before writing '%s'; "
                "active-profile and enable-state restore will be skipped "
                "if this write fails.",
                profile_name,
                exc_info=status_result,
            )
        else:
            original_enabled, original_active_name = status_result

        if isinstance(profiles_result, BaseException):
            logger.warning(
                "Failed to list RoomFit profiles before writing '%s'.",
                profile_name,
                exc_info=profiles_result,
            )
            return WriteResult(
                success=False,
                backup_path=None,
                error_message=f"Could not list RoomFit profiles: {profiles_result}",
            )

        existing_profiles = profiles_result
        existing_names = {p.get("Name", "") for p in existing_profiles}
        is_new = profile_name not in existing_names

        existing_settings: PEQSettings | None = None
        if not is_new:
            existing_settings = await self._adapter.read_roomfit(source_name, profile_name)
            backup_path = self._backup_manager.create_backup(
                existing_settings,
                self._adapter.capabilities,
                "pre_write",
                pre_write_active_profile=original_active_name,
                pre_write_roomfit_enabled=original_enabled,
                was_new_profile=False,
            )
        else:
            # No prior bands to snapshot -- back up an empty stereo
            # PEQSettings purely as a carrier for the three restore-metadata
            # fields undo() needs; bands are meaningless here.
            backup_path = self._backup_manager.create_backup(
                PEQSettings(source_name=source_name, channel_mode=ChannelMode.STEREO, bands=[]),
                self._adapter.capabilities,
                "pre_write",
                pre_write_active_profile=original_active_name,
                pre_write_roomfit_enabled=original_enabled,
                was_new_profile=True,
            )

        if on_stage is not None:
            on_stage("writing")
        await self._adapter.write_roomfit(
            source_name,
            profile_name,
            filters,
            channel_mode=channel_mode,
            filters_l=filters_l,
            filters_r=filters_r,
        )

        if channel_mode.is_lr:
            intended = PEQSettings(
                source_name=source_name,
                channel_mode=ChannelMode.LR,
                bands_l=filters_l or [],
                bands_r=filters_r or [],
            )
        else:
            intended = PEQSettings(
                source_name=source_name,
                channel_mode=ChannelMode.STEREO,
                bands=filters,
            )

        # write_roomfit() truncates/clamps via the same generate_wiim_band_array()
        # SafeWrite's PEQ path uses -- verify against that baseline, not the raw
        # imported values (see clamp_filters_for_verification's docstring).
        verify_intended = _clamped_for_verification(
            intended, self._adapter.capabilities.max_filters
        )

        if on_stage is not None:
            on_stage("verifying")
        read_back = await self._adapter.read_roomfit(source_name, profile_name)
        if verify_bands(verify_intended, read_back):
            # Success: make the newly-written profile active and turn
            # RoomFit on if it was off -- deliberate, confirmed commands,
            # best-effort so a verified-correct write still reports success
            # even if this polish step hiccups (matches the existing
            # restore_roomfit_active_profile best-effort pattern).
            try:
                await self._adapter.load_roomfit_profile(profile_name)
            except Exception:
                logger.warning(
                    "Failed to activate RoomFit profile '%s' after successful "
                    "push; device may still show a different profile selected.",
                    profile_name,
                    exc_info=True,
                )
            try:
                await self._adapter.enable_roomfit()
            except Exception:
                logger.warning(
                    "Failed to enable RoomFit after successful push of '%s'; "
                    "device may still show RoomFit off.",
                    profile_name,
                    exc_info=True,
                )

            if self._adapter.capabilities.roomfit_level < 4:
                old_level = self._adapter.capabilities.roomfit_level
                self._adapter.capabilities.roomfit_level = 4
                self._adapter.capabilities.supports_roomfit_write = True
                logger.info(
                    "RoomFit write succeeded at previously-unconfirmed level %d; "
                    "upgrading roomfit_level to 4 for this session.",
                    old_level,
                )

            if on_stage is not None:
                on_stage("done")
            return WriteResult(success=True, backup_path=backup_path, read_back=read_back)

        logger.warning(
            "RoomFit write verification failed for profile '%s' (source '%s'): %s",
            profile_name,
            source_name,
            _describe_first_mismatch(verify_intended, read_back),
        )

        if is_new:
            await self._adapter.delete_roomfit_profile(profile_name)
            await self._adapter.restore_roomfit_selection_and_enable_state(
                original_active_name, original_enabled, profile_name,
                context=f"writing '{profile_name}'",
            )
            return WriteResult(
                success=False,
                rollback_success=True,
                backup_path=None,
                error_message=(
                    f"RoomFit profile '{profile_name}' verification failed; "
                    f"the new profile was removed."
                ),
            )

        assert existing_settings is not None
        await self._adapter.write_roomfit(
            source_name,
            profile_name,
            existing_settings.bands,
            channel_mode=existing_settings.channel_mode,
            filters_l=existing_settings.bands_l,
            filters_r=existing_settings.bands_r,
        )
        rollback_read_back = await self._adapter.read_roomfit(source_name, profile_name)
        verify_existing = _clamped_for_verification(
            existing_settings, self._adapter.capabilities.max_filters
        )
        rollback_ok = verify_bands(verify_existing, rollback_read_back)
        if rollback_ok:
            await self._adapter.restore_roomfit_selection_and_enable_state(
                original_active_name, original_enabled, profile_name,
                context=f"writing '{profile_name}'",
            )
            return WriteResult(
                success=False,
                rollback_success=True,
                backup_path=backup_path,
                error_message=(
                    f"RoomFit profile '{profile_name}' verification failed; "
                    f"original profile restored."
                ),
            )

        logger.critical(
            "RoomFit rollback FAILED for profile '%s'. Manual recovery required. "
            "Backup file: %s",
            profile_name,
            backup_path,
        )
        # Runs even on this critical-failure path -- at this point
        # profile_name's on-device state is unverified/possibly-corrupt, so
        # leaving the last-known-good original_active_name selected (and
        # RoomFit's original enable state) is safer than leaving an
        # unverified profile active, even though a technician diagnosing the
        # failure won't see profile_name still "selected".
        await self._adapter.restore_roomfit_selection_and_enable_state(
            original_active_name, original_enabled, profile_name,
            context=f"writing '{profile_name}'",
        )
        return WriteResult(
            success=False,
            rollback_success=False,
            backup_path=backup_path,
            error_message=(
                f"RoomFit profile '{profile_name}' verification AND restore "
                f"failed. Manual recovery required. Backup: {backup_path}"
            ),
        )

    async def undo(
        self,
        backup_path: str | Path,
        source_name: str,
        profile_name: str,
        on_stage: Callable[[str], None] | None = None,
    ) -> WriteResult:
        """Undo a previously-successful RoomFit push using its backup file.

        Restores:
          - The profile's previous bands, if the original push overwrote an
            existing profile (``was_new_profile`` False/None in the
            backup). For a push that created a brand-new profile, this step
            is skipped entirely -- undo is non-destructive and never
            deletes a profile the user might want to keep (they can remove
            it via "Presets on Device" if unwanted).
          - Whatever profile was active before the ORIGINAL push
            (``pre_write_active_profile``).
          - RoomFit's on/off state as it was before the ORIGINAL push
            (``pre_write_roomfit_enabled``).

        The selection/enable-state restore always runs *last*, even after a
        bands-restore: that inner restore is itself a full push through
        ``execute()``, whose own success path activates `profile_name` --
        correct only when `profile_name` was also the profile active before
        the original push. When the original push overwrote a *different*,
        non-active profile, the selection restore below corrects that.

        Backward compatibility: a backup file written before this fields'
        introduction has all three restore-metadata fields as `None` --
        selection/enable-state restore is then skipped entirely (bands-only
        restore, matching pre-redesign behavior) rather than guessing.

        Args:
            backup_path: Path to the backup JSON file the original push created.
            source_name: Audio input source (only used for read_roomfit's
                PEQSettings.source_name attribution -- RoomFit is global).
            profile_name: Name of the profile to restore bands into (ignored
                if the backup indicates a new-profile push).
            on_stage: Optional callback forwarded to the bands-restore
                ``execute()`` call (see its own ``on_stage`` for the
                contract); not invoked at all for a new-profile-push undo,
                which skips the bands-restore step entirely.

        Returns:
            WriteResult. For a new-profile-push undo: success with no bands
            touched. For an overwrite-push undo: whatever `execute()`
            returns for the bands-restore write.
        """
        path = Path(backup_path)
        backup_data = load_backup_json(path)
        pre_write_active_profile, pre_write_roomfit_enabled, was_new_profile, _ = (
            parse_backup_restore_metadata(backup_data)
        )

        result: WriteResult | None = None
        if was_new_profile is not True:
            # Covers False and None (old-format backups only ever existed
            # for the overwrite case) -- restore bands via the normal
            # execute() protocol.
            bands, channel_mode, filters_l, filters_r = parse_backup_filters(backup_data)
            if not bands:
                return WriteResult(success=False, error_message="Backup contains no filters")
            result = await self.execute(
                source_name, profile_name, bands,
                channel_mode=channel_mode,
                filters_l=filters_l,
                filters_r=filters_r,
                on_stage=on_stage,
            )
            if not result.success:
                return result

        if pre_write_active_profile is not None:
            await self._adapter.restore_roomfit_selection_and_enable_state(
                pre_write_active_profile, pre_write_roomfit_enabled, profile_name,
                context=f"undoing push to '{profile_name}'",
            )

        return result if result is not None else WriteResult(success=True, backup_path=None)
