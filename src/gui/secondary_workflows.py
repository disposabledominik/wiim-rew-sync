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

from src.gui.shared_helpers import build_peq_settings
from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode

if TYPE_CHECKING:
    from src.adapters.safe_write import SafeWrite
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
        profile_recalled(list): List of CanonicalFilter loaded from a profile.
        undo_complete(bool, str): Success flag and message after undo.
    """

    # --- Signals ---
    profile_recalled = Signal(list)
    undo_complete = Signal(bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bridge: AsyncBridge | None = None
        self._wiim_adapter_factory: Callable[[str], WiiMAdapter] | None = None
        self._safe_write_factory: Callable[[WiiMAdapter], SafeWrite] | None = None
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
            backup_manager: The backup manager instance for state snapshots.

        Requirements: 8.1.
        """
        self._bridge = bridge
        self._wiim_adapter_factory = wiim_adapter_factory
        self._safe_write_factory = safe_write_factory
        self._backup_manager = backup_manager
        logger.info("SecondaryWorkflowManager configured with adapter factories")

    @property
    def is_configured(self) -> bool:
        """Return True if configure() has been called with valid dependencies."""
        return (
            self._bridge is not None
            and self._wiim_adapter_factory is not None
            and self._safe_write_factory is not None
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
            self.profile_recalled.emit([])
            return

        logger.info(
            "Profile recall: loaded %d filters from profile '%s' (%s)",
            len(filters),
            profile_name,
            channel_mode,
        )
        self.profile_recalled.emit(filters)

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
        """Execute undo via SafeWrite with backup data.

        Reads the backup file, reconstructs PEQSettings, and writes them
        back to the device using the Safe_Write_Protocol.
        """
        assert self._safe_write_factory is not None
        assert self._current_adapter is not None

        path = Path(backup_path) if isinstance(backup_path, str) else backup_path

        # Check if backup file exists (Req 8.5)
        if not path or not path.exists():
            logger.error("Undo requested but backup file not found: %s", path)
            self.undo_complete.emit(False, "No backup available")
            return

        try:
            # Read and parse backup using shared helpers
            from src.gui.shared_helpers import load_backup_json, parse_backup_filters

            backup_data = load_backup_json(path)
            filters, channel_mode, filters_l, filters_r = parse_backup_filters(backup_data)

            # Build PEQSettings from parsed filters — pass filters_l/filters_r
            # explicitly so L/R mode never reconstructs the channel split
            # positionally from the combined list.
            settings = build_peq_settings(
                source_name, filters, channel_mode,
                filters_l=filters_l, filters_r=filters_r,
            )

            # Execute SafeWrite with the restored settings
            safe_write = self._safe_write_factory(self._current_adapter)
            await safe_write.execute(source_name, settings)

            self.undo_complete.emit(True, "Previous filters restored")
            logger.info("Undo last push: completed successfully")
        except Exception as exc:
            logger.exception("Undo last push failed")
            self.undo_complete.emit(False, str(exc))
