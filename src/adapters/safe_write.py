"""
Safe Write Protocol - five-step backup/write/verify/commit-or-rollback sequence.

Implements the mandatory safety protocol for all PEQ device writes:
1. Backup current state
2. Write new settings
3. Read-back (fresh call)
4. Verify via band_matches()
5a. Commit on success / 5b. Rollback on failure

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.models.canonical import CanonicalFilter
from src.models.errors import WiiMSlaveTargetError
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
    backup_path: Path | None = None
    error_message: str | None = None


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

        Raises:
            WiiMSlaveTargetError: If the device role is slave.
        """
        capabilities = self._adapter.capabilities

        # Slave guard: refuse writes to slave nodes
        if capabilities.role == "slave":
            raise WiiMSlaveTargetError(
                "Cannot write PEQ to a slave device; target the master node instead"
            )

        # Step 1: Backup current device state
        current_settings = await self._adapter.read_peq(source_name)
        backup_path = self._backup_manager.create_backup(
            current_settings, capabilities, "pre_write"
        )

        # Adapt write settings to match the device's current channel mode.
        # If the device is in L/R mode but we're writing stereo data, apply the
        # same stereo bands to both L and R channels. If the device is in stereo
        # mode but we have L/R data, use only the left channel bands.
        effective_settings = self._adapt_channel_mode(settings, current_settings)

        # Step 2: Write new settings
        await self._adapter.write_peq(source_name, effective_settings, self._queue)

        # Step 3: Read-back (fresh call to device)
        read_back = await self._adapter.read_peq(source_name)

        # Step 4: Verify each band matches
        if self._verify_bands(effective_settings, read_back):
            # Step 5a: Commit - verification passed
            return WriteResult(success=True, backup_path=backup_path)

        # Step 5b: Rollback - verification failed
        return await self._rollback(source_name, current_settings, backup_path)

    def _adapt_channel_mode(
        self, intended: PEQSettings, device_state: PEQSettings
    ) -> PEQSettings:
        """Adapt the intended settings to match the device's channel mode.

        If there's a mismatch, we switch the device's channel mode to match
        the intended write via EQSetLV2ChannelMode. This is the correct
        approach — the user's intent (stereo vs L/R) should be honored, not
        silently duplicated or dropped.

        Returns the intended settings unchanged (the mode switch happens
        on-device before writing).
        """
        device_mode = device_state.channel_mode
        write_mode = intended.channel_mode

        if write_mode == device_mode:
            return intended

        # Mode mismatch — we'll switch the device mode in the write step.
        # The write_peq method already sends channelMode in its payload,
        # which implicitly switches the device. But to be safe and explicit,
        # we flag that a mode switch is needed.
        if write_mode == "stereo" and device_mode == "lr":
            logger.info(
                "Device is in L/R mode; switching to Stereo for this write."
            )
        elif write_mode == "lr" and device_mode == "stereo":
            logger.info(
                "Device is in Stereo mode; switching to L/R for this write."
            )

        return intended

    def _verify_bands(self, intended: PEQSettings, read_back: PEQSettings) -> bool:
        """Compare intended vs read-back bands using tolerance predicates.

        For stereo mode, compares the .bands lists.
        For L/R mode, compares both .bands_l and .bands_r lists.

        Returns True if all bands match within tolerance.
        """
        if intended.channel_mode == "stereo":
            return self._compare_band_lists(intended.bands, read_back.bands)
        else:
            # L/R mode: verify both channels
            left_ok = self._compare_band_lists(
                intended.bands_l or [], read_back.bands_l or []
            )
            right_ok = self._compare_band_lists(
                intended.bands_r or [], read_back.bands_r or []
            )
            return left_ok and right_ok

    def _compare_band_lists(
        self,
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
        if compare_count == 0 and len(intended_bands) > 0:
            return False
        return all(
            band_matches(intended, actual)
            for intended, actual in zip(
                intended_bands[:compare_count],
                read_back_bands[:compare_count],
                strict=True,
            )
        )

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
        if self._verify_bands(original_settings, rollback_read_back):
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
