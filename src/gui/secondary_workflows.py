"""Secondary workflow orchestration for profile recall and undo operations.

Encapsulates the logic for workflows that extend beyond the primary wizard:
- Profile recall from My Saved Presets (Req 17.2)
- Undo last push (Req 18)

These workflows are self-contained operations launched from PushPage or
MyPresetsView. They do NOT create new wizard steps in the StepIndicator —
they are modal sub-flows or inline operations.

Note: "Copy to another source" (Req 20) and "Apply to multiple devices"
(Req 21) were never wired to any UI trigger and have been removed as dead
code (code quality audit, 2026-06-28) — see docs/backlog.md if those
features are revisited. "Copy preset to another device" (Req 15.11,
17.3) is implemented directly in MainWindow
(_do_copy_presets_batch_multi / _do_copy_preset_to_device), not here.

Requirements referenced: 17.2, 18.1, 18.2, 18.3, 18.4, 18.6.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, Slot

from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode
from src.repository.backup_manager import load_backup_json, parse_backup_restore_metadata

if TYPE_CHECKING:
    from src.adapters.safe_write import RoomFitSafeWrite, SafeWrite
    from src.adapters.wiim_adapter import WiiMAdapter
    from src.gui.async_bridge import AsyncBridge
    from src.repository.backup_manager import BackupManager

logger = logging.getLogger("wiim_rew_sync.secondary_workflows")


# ---------------------------------------------------------------------------
# SecondaryWorkflowManager
# ---------------------------------------------------------------------------


class SecondaryWorkflowManager(QObject):
    """Orchestrates secondary workflows: profile recall and undo.

    This manager coordinates multi-step operations that go beyond the primary
    wizard flow. It does NOT perform direct network calls; actual I/O is
    delegated to the AsyncBridge.

    The manager emits progress and completion signals that the MainWindow
    connects to for UI updates (StatusBanner messages, dialogs, etc.).

    Signals:
        profile_recalled(list, str): List of CanonicalFilter loaded from a
            profile, and the profile's name (for the Filters step tooltip,
            #162d).
        undo_complete(bool, str): Success flag and message after undo.
        source_slots_ready(list): SourceSlotInfo rows from the current
            device's EQGetSourceModes overview (diagnostic-only).
        source_slots_error(str): Error message when the slot overview
            couldn't be fetched (e.g. device doesn't support the command).
    """

    # --- Signals ---
    profile_recalled = Signal(list, str)
    undo_complete = Signal(bool, str)
    source_slots_ready = Signal(list)
    source_slots_error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bridge: AsyncBridge | None = None
        self._wiim_adapter_factory: Callable[[str], WiiMAdapter] | None = None
        self._safe_write_factory: Callable[[WiiMAdapter], SafeWrite] | None = None
        self._roomfit_safe_write_factory: Callable[[WiiMAdapter], RoomFitSafeWrite] | None = None
        self._backup_manager: BackupManager | None = None
        self._current_adapter: WiiMAdapter | None = None

    # ------------------------------------------------------------------
    # Configuration (adapter injection for async execution)
    # ------------------------------------------------------------------

    def configure(
        self,
        bridge: AsyncBridge,
        wiim_adapter_factory: Callable[[str], WiiMAdapter],
        safe_write_factory: Callable[[WiiMAdapter], SafeWrite],
        roomfit_safe_write_factory: Callable[[WiiMAdapter], RoomFitSafeWrite],
        backup_manager: BackupManager,
    ) -> None:
        """Inject adapter dependencies for real async workflow execution.

        Called from MainWindow._on_capabilities_ready after adapters are created.

        Args:
            bridge: The AsyncBridge for run_async calls.
            wiim_adapter_factory: Factory creating a WiiMAdapter for a given IP.
                Currently unused by any remaining workflow, retained for
                future per-device adapter needs.
            safe_write_factory: Factory creating a SafeWrite from a WiiMAdapter.
            roomfit_safe_write_factory: Factory creating a RoomFitSafeWrite
                from a WiiMAdapter, for undo_roomfit().
            backup_manager: The backup manager instance for state snapshots.

        Requirements: 8.1.
        """
        self._bridge = bridge
        self._wiim_adapter_factory = wiim_adapter_factory
        self._safe_write_factory = safe_write_factory
        self._roomfit_safe_write_factory = roomfit_safe_write_factory
        self._backup_manager = backup_manager
        logger.info("SecondaryWorkflowManager configured with adapter factories")

    @property
    def is_configured(self) -> bool:
        """Return True if configure() has been called with valid dependencies."""
        return (
            self._bridge is not None
            and self._wiim_adapter_factory is not None
            and self._safe_write_factory is not None
            and self._roomfit_safe_write_factory is not None
            and self._backup_manager is not None
        )

    def set_current_adapter(self, adapter: WiiMAdapter | None) -> None:
        """Set the current device adapter for same-device workflows.

        Called from MainWindow whenever the active device changes (after
        capability probing creates a WiiMAdapter). Used by undo_last_push,
        which operates on the currently connected device.

        Args:
            adapter: The WiiMAdapter for the currently connected device,
                    or None to clear.
        """
        self._current_adapter = adapter

    # ------------------------------------------------------------------
    # Workflow: Profile Recall (Req 17.2)
    # ------------------------------------------------------------------

    @Slot(object)
    def recall_profile(self, profile: object) -> None:
        """Load a saved profile from the local preset library into the Review step.

        Extracts CanonicalFilter data from the profile and emits
        profile_recalled so the wizard can populate the ReviewPage.
        Handles both stereo (profile.filters) and L/R (profile.filters_l + filters_r).

        Args:
            profile: A Profile object from the local preset library.

        Requirement 17.2: Profile Recall & Push flow.
        """
        profile_name: str = getattr(profile, "name", "Unknown")
        channel_mode = getattr(profile, "channel_mode", ChannelMode.STEREO)
        if isinstance(channel_mode, str):
            channel_mode = ChannelMode.from_any(channel_mode)

        # Extract filters based on channel mode
        if channel_mode.is_lr:
            # L/R profile: combine both channels into flat list
            filters_l: list[CanonicalFilter] = getattr(profile, "filters_l", None) or []
            filters_r: list[CanonicalFilter] = getattr(profile, "filters_r", None) or []
            filters = filters_l + filters_r
            # Store separate L/R lists in wizard state so downstream never re-splits
            self._store_lr_state(filters_l, filters_r)
        else:
            # Stereo profile
            filters = getattr(profile, "filters", None) or []
            # Clear L/R state for stereo profiles
            self._store_lr_state([], [])

        if not filters:
            logger.warning(
                "Profile recall: profile '%s' has no filters",
                profile_name,
            )
            self.profile_recalled.emit([], profile_name)
            return

        logger.info(
            "Profile recall: loaded %d filters from profile '%s' (%s)",
            len(filters),
            profile_name,
            channel_mode,
        )
        self.profile_recalled.emit(filters, profile_name)

    def _store_lr_state(
        self, filters_l: list[CanonicalFilter], filters_r: list[CanonicalFilter]
    ) -> None:
        """Store L/R filter lists in the parent MainWindow's wizard state.

        This avoids the need for naive 50/50 splitting when consumers
        need separate channel lists.
        """
        # Access wizard state through the parent (MainWindow)
        parent = self.parent()
        if parent is not None and hasattr(parent, "wizard_controller"):
            state = parent.wizard_controller.state
            state.filters_l = filters_l
            state.filters_r = filters_r

    # ------------------------------------------------------------------
    # Workflow: Undo Last Push (Req 18)
    # ------------------------------------------------------------------

    @Slot(str)
    def undo_last_push(self, source_name: str, backup_path: str | Path = "") -> None:
        """Restore the device's PEQ state from the most recent backup.

        The undo operation follows the same Safe_Write_Protocol as a normal
        push: backup current state → write backup data → verify →
        commit/rollback.

        Args:
            source_name: The source name to restore (needed for SafeWrite).
            backup_path: Path to the pre-write backup file created during
                        the original push operation.

        Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6.
        """
        assert self._bridge is not None
        self._bridge.run_async(self._do_undo(source_name, backup_path))

    async def _do_undo(self, source_name: str, backup_path: str | Path) -> None:
        """Execute undo via SafeWrite.undo(), which restores both the
        source's previous bands and its previous enable-state (backup
        parsing and PEQSettings reconstruction live inside SafeWrite.undo()
        now, not here -- see its docstring).
        """
        assert self._safe_write_factory is not None
        assert self._current_adapter is not None

        path = Path(backup_path) if isinstance(backup_path, str) else backup_path

        # Check if backup file exists (Req 8.5)
        if not path or not path.is_file():
            logger.error("Undo requested but backup file not found: %s", path)
            self.undo_complete.emit(False, "No backup available")
            return

        try:
            safe_write = self._safe_write_factory(self._current_adapter)
            result = await safe_write.undo(path, source_name)

            if result.success:
                self.undo_complete.emit(True, "Previous filters restored")
                logger.info("Undo last push: completed successfully")
            else:
                error_msg = result.error_message or "Unknown error"
                self.undo_complete.emit(False, error_msg)
                logger.error("Undo last push failed: %s", error_msg)
        except Exception as exc:
            logger.exception("Undo last push failed")
            self.undo_complete.emit(False, str(exc))

    @Slot(str)
    def undo_roomfit(self, backup_path: str, source_name: str, profile_name: str) -> None:
        """Restore a RoomFit profile from backup."""
        assert self._bridge is not None
        self._bridge.run_async(
            self._do_undo_roomfit(backup_path, source_name, profile_name)
        )

    async def _do_undo_roomfit(
        self, backup_path: str, source_name: str, profile_name: str
    ) -> None:
        """Restore a RoomFit profile from backup — thin pass-through to
        RoomFitSafeWrite.undo(), which owns all orchestration (backup
        parsing, new-vs-overwrite branching, selection/enable-state
        restore to the state before the *original* push). No widget
        access here (moved out of MainWindow, docs/backlog.md item 2 Phase
        D) -- results reported via undo_complete, same signal
        undo_last_push()/_do_undo() above already use.
        """
        assert self._bridge is not None
        assert self._roomfit_safe_write_factory is not None
        assert self._current_adapter is not None

        path = Path(backup_path) if backup_path else Path(".")
        if not path.exists() or not path.is_file():
            self.undo_complete.emit(False, "No backup available for undo")
            return

        try:
            self._bridge.progress_update.emit(f"Restoring '{profile_name}'...")
            roomfit_safe_write = self._roomfit_safe_write_factory(self._current_adapter)
            result = await roomfit_safe_write.undo(path, source_name, profile_name)
            if not result.success:
                self.undo_complete.emit(
                    False, result.error_message or "RoomFit undo verification failed"
                )
                return
            # was_new_profile determines what undo() actually did: for a
            # brand-new profile it skips the bands-restore entirely (there
            # was nothing to restore) and only re-activates the
            # previously-active profile, leaving the new one on the device.
            # Read the same metadata undo() itself used, so the message
            # matches what happened instead of always claiming a restore.
            _, _, was_new_profile, _ = parse_backup_restore_metadata(
                load_backup_json(path)
            )
            if was_new_profile is True:
                message = (
                    f"Original profile re-activated. Profile '{profile_name}' was "
                    "kept, but deactivated."
                )
            else:
                message = f"Profile '{profile_name}' restored from backup"
            self.undo_complete.emit(True, message)
        except Exception as exc:
            logger.exception("RoomFit undo failed")
            self.undo_complete.emit(False, str(exc))

    @Slot(str)
    def undo_multi_source(self, backup_paths_str: str) -> None:
        """Undo a multi-source push by restoring each source's backup."""
        assert self._bridge is not None
        self._bridge.run_async(self._do_undo_multi_source(backup_paths_str))

    async def _do_undo_multi_source(self, backup_paths_str: str) -> None:
        """Undo a multi-source push by restoring each source's backup.

        Args:
            backup_paths_str: Semicolon-separated "source=/path" entries.

        Note (pre-existing behavior, preserved as-is by this move --
        docs/backlog.md item 2 Phase D): undo_last_push() below only
        *schedules* each source's real restore via run_async() and returns
        immediately, so this method's own succeeded/failed tally and
        undo_complete emit reflect scheduling success, not each source's
        actual outcome -- which arrives later via undo_last_push's own
        undo_complete emit (per source), potentially after this method's
        own summary already fired. Characterized in
        test_smoke_regression_operations.py before this move; not fixed
        here.
        """
        assert self._bridge is not None
        entries = [e.strip() for e in backup_paths_str.split(";") if e.strip()]
        succeeded = 0
        failed = 0

        for entry in entries:
            if "=" not in entry:
                continue
            source_name, bp = entry.split("=", 1)
            source_name = source_name.strip()
            bp = bp.strip()

            try:
                self._bridge.progress_update.emit(f"Restoring {source_name}...")
                self.undo_last_push(source_name, bp)
                succeeded += 1
            except Exception:
                logger.exception("Undo source '%s' failed", source_name)
                failed += 1

        if failed == 0:
            self.undo_complete.emit(True, f"All {succeeded} source(s) restored from backup")
        else:
            self.undo_complete.emit(False, f"{succeeded} restored, {failed} failed")

    # ------------------------------------------------------------------
    # Workflow: Source-Slot Overview (#194 follow-up diagnostic)
    # ------------------------------------------------------------------

    @Slot()
    def fetch_source_slots(self) -> None:
        """Fetch the current device's live per-source PEQ slot overview.

        Read-only diagnostic (EQGetSourceModes) -- surfaces garbage slots
        left behind by invalid source_name writes. Not a new MainWindow
        `_do_*` method: this orchestration lives here, per backlog #7's
        rule that new orchestration must not grow MainWindow further.
        """
        assert self._bridge is not None
        self._bridge.run_async(self._do_fetch_source_slots())

    async def _do_fetch_source_slots(self) -> None:
        if self._current_adapter is None:
            self.source_slots_error.emit("No device connected")
            return
        try:
            slots = await self._current_adapter.get_source_slot_overview()
            self.source_slots_ready.emit(slots)
        except Exception as exc:
            logger.warning("Source-slot overview fetch failed: %s", exc)
            self.source_slots_error.emit(str(exc))
