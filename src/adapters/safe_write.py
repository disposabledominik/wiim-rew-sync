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

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode
from src.models.peq import PEQSettings
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


class SafeWrite:
    """Five-step safe write protocol for PEQ device writes.

    Ensures every write is backed up, verified, and rolled back on failure.

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

    async def execute(self, source_name: str, settings: PEQSettings) -> WriteResult:
        """Execute the five-step safe write protocol.

        Steps:
            1. Backup current device state
            2. Write new settings to device
            3. Read-back device state (fresh call)
            4. Verify each band matches intended settings
            5a. Commit (return success) OR
            5b. Rollback (restore backup state, verify rollback)

        Args:
            source_name: Audio input source (e.g. "wifi", "bluetooth").
            settings: PEQ settings to write to the device.

        Returns:
            WriteResult indicating success/failure and rollback status.
        """
        capabilities = self._adapter.capabilities

        # Step 1: Backup current device state
        current_settings = await self._adapter.read_peq(source_name)
        backup_path = self._backup_manager.create_backup(
            current_settings, capabilities, "pre_write"
        )

        # Step 2: Write new settings. If the device's current channel mode
        # differs from settings.channel_mode, WiiMAdapter.write_peq() switches
        # the device's mode (via _set_channel_mode) before writing the bands.
        await self._adapter.write_peq(source_name, settings, self._queue)

        # Step 3: Read-back (fresh call to device)
        read_back = await self._adapter.read_peq(source_name)

        # Step 4: Verify each band matches
        if verify_bands(settings, read_back):
            # Step 5a: Commit - verification passed
            return WriteResult(success=True, backup_path=backup_path)

        # Step 5b: Rollback - verification failed
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
        """
        capabilities = self._adapter.capabilities

        # Create pre_rollback backup of current (corrupted) state
        current_state = await self._adapter.read_peq(source_name)
        self._backup_manager.create_backup(current_state, capabilities, "pre_rollback")

        # Write backup state back via queue
        await self._adapter.write_peq(source_name, original_settings, self._queue)

        # Verify rollback succeeded
        rollback_read_back = await self._adapter.read_peq(source_name)
        if verify_bands(original_settings, rollback_read_back):
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


class RoomFitSafeWrite:
    """Verify-and-rollback wrapper for RoomFit named-profile writes.

    Unlike PEQ's SafeWrite, a RoomFit write targets a *named* profile that
    may or may not have existed before this write — so rollback has two
    shapes instead of one:
      - Profile already existed: restore its previous bands (RESTORE).
      - Profile is brand-new: delete the profile we just created (DELETE_NEW),
        since there's no prior state to go back to.

    Args:
        adapter: WiiMAdapter for device read/write operations.
        backup_manager: BackupManager for creating state snapshots of an
            overwritten profile's previous bands.
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
    ) -> WriteResult:
        """Write a RoomFit profile, then verify and roll back on mismatch.

        Args:
            source_name: Audio input source (e.g. "wifi").
            profile_name: Name of the RoomFit profile to write.
            filters: Stereo-mode filters (ignored when channel_mode is LR).
            channel_mode: ChannelMode for the write.
            filters_l: Left channel filters (required when channel_mode is LR).
            filters_r: Right channel filters (required when channel_mode is LR).

        Returns:
            WriteResult indicating success/failure and rollback status.
        """
        existing_profiles = await self._adapter.list_roomfit_profiles(source_name)
        existing_names = {p.get("Name", "") for p in existing_profiles}
        is_new = profile_name not in existing_names

        backup_path: Path | str | None = None
        existing_settings: PEQSettings | None = None
        if not is_new:
            existing_settings = await self._adapter.read_roomfit(
                source_name, profile_name
            )
            backup_path = self._backup_manager.create_backup(
                existing_settings, self._adapter.capabilities, "pre_write"
            )

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

        read_back = await self._adapter.read_roomfit(source_name, profile_name)
        if verify_bands(intended, read_back):
            return WriteResult(success=True, backup_path=backup_path)

        if is_new:
            await self._adapter.delete_roomfit_profile(profile_name)
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
        rollback_ok = verify_bands(existing_settings, rollback_read_back)
        if rollback_ok:
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
        return WriteResult(
            success=False,
            rollback_success=False,
            backup_path=backup_path,
            error_message=(
                f"RoomFit profile '{profile_name}' verification AND restore "
                f"failed. Manual recovery required. Backup: {backup_path}"
            ),
        )
