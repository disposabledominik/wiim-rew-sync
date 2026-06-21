"""Secondary workflow orchestration for multi-source, multi-device, and undo operations.

Encapsulates the logic for workflows that extend beyond the primary wizard:
- Copy to another source (Req 20)
- Apply to multiple devices (Req 21)
- Copy preset to another device (Req 17.3, 15.11)
- Profile recall from My Saved Presets (Req 17.2)
- Undo last push (Req 18)

These workflows are self-contained operations launched from ReviewPage, PushPage,
PresetsDeviceView, or MyPresetsView. They do NOT create new wizard steps in the
StepIndicator — they are modal sub-flows or inline operations.

Requirements referenced: 17.1, 17.2, 17.3, 18.1, 18.2, 18.3, 18.4, 18.6,
    20.1, 20.2, 20.3, 20.4, 20.5, 21.1, 21.2, 21.3, 21.4, 21.5, 21.6.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, Slot

from src.models.canonical import CanonicalFilter
from src.models.peq import PEQSettings

if TYPE_CHECKING:
    from src.adapters.safe_write import SafeWrite
    from src.adapters.wiim_adapter import WiiMAdapter
    from src.gui.async_bridge import AsyncBridge
    from src.repository.backup_manager import BackupManager

logger = logging.getLogger("wiim_rew_sync.secondary_workflows")


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceCopyResult:
    """Result of copying filters to a single source.

    Attributes:
        source_name: Target source that was written to.
        success: Whether the write succeeded.
        message: Human-readable status or error message.
    """

    source_name: str
    success: bool
    message: str = ""


@dataclass(frozen=True, slots=True)
class DevicePushResult:
    """Result of pushing filters to a single device.

    Attributes:
        device_ip: IP address of the target device.
        device_name: Display name of the target device.
        source_name: Target source on the device.
        success: Whether the push succeeded.
        message: Human-readable status or error message.
    """

    device_ip: str
    device_name: str
    source_name: str
    success: bool
    message: str = ""


@dataclass(slots=True)
class MultiDeviceRequest:
    """Request parameters for apply-to-multiple-devices workflow.

    Attributes:
        device_source_map: Mapping of device IP to list of target sources.
        device_names: Mapping of device IP to display name (for UI feedback).
    """

    device_source_map: dict[str, list[str]] = field(default_factory=dict)
    device_names: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SecondaryWorkflowManager
# ---------------------------------------------------------------------------


class SecondaryWorkflowManager(QObject):
    """Orchestrates secondary workflows: copy-to-source, multi-device, profile recall, undo.

    This manager coordinates multi-step operations that go beyond the primary
    wizard flow. It does NOT perform direct network calls; actual I/O is
    delegated to the AsyncBridge (TODO when adapter methods are available).

    The manager emits progress and completion signals that the MainWindow
    connects to for UI updates (StatusBanner messages, dialogs, etc.).

    Signals:
        copy_to_sources_progress(str): Per-source progress message during copy.
        copy_to_sources_complete(list): List of SourceCopyResult when done.
        multi_device_progress(str): Per-device progress message.
        multi_device_complete(list): List of DevicePushResult when done.
        copy_to_device_complete(bool, str): Success flag and message for preset copy.
        profile_recalled(list): List of CanonicalFilter loaded from a profile.
        undo_complete(bool, str): Success flag and message after undo.
    """

    # --- Signals ---
    copy_to_sources_progress = Signal(str)
    copy_to_sources_complete = Signal(list)
    multi_device_progress = Signal(str)
    multi_device_complete = Signal(list)
    copy_to_device_complete = Signal(bool, str)
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
        The factories allow per-device adapter creation for multi-device operations.

        Args:
            bridge: The AsyncBridge for run_async calls.
            wiim_adapter_factory: Factory creating a WiiMAdapter for a given IP.
            safe_write_factory: Factory creating a SafeWrite from a WiiMAdapter.
            backup_manager: The backup manager instance for state snapshots.

        Requirements: 8.1, 9.3, 10.3, 15.3.
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
        capability probing creates a WiiMAdapter). Used by copy_to_sources
        and undo_last_push which operate on the currently connected device.

        Args:
            adapter: The WiiMAdapter for the currently connected device,
                    or None to clear.
        """
        self._current_adapter = adapter

    # ------------------------------------------------------------------
    # Workflow 1: Copy to Another Source (Req 20)
    # ------------------------------------------------------------------

    @Slot(list, list)
    def copy_to_sources(
        self,
        filters: list[CanonicalFilter],
        target_sources: list[str],
    ) -> None:
        """Copy current filters to one or more target sources on the same device.

        For each target source, executes the Safe_Write_Protocol independently:
        backup target source → write → verify → commit/rollback.

        Emits copy_to_sources_progress per source and copy_to_sources_complete
        with the full results list when all sources are processed.

        Args:
            filters: The canonical filters to push to each target source.
            target_sources: List of source names to copy filters to.

        Requirements: 9.3, 9.4, 9.5, 9.6, 9.7.
        """
        assert self._bridge is not None
        self._bridge.run_async(self._do_copy_to_sources(filters, target_sources))

    async def _do_copy_to_sources(
        self,
        filters: list[CanonicalFilter],
        target_sources: list[str],
    ) -> None:
        """Execute copy-to-sources with fault isolation per source.

        Each source is written independently — one failure does NOT stop
        remaining sources (Req 9.7).
        """
        assert self._safe_write_factory is not None
        assert self._current_adapter is not None

        results: list[SourceCopyResult] = []
        safe_write = self._safe_write_factory(self._current_adapter)

        for source_name in target_sources:
            self.copy_to_sources_progress.emit(f"Writing to {source_name}...")
            logger.info(
                "Copy-to-source: writing %d filters to source '%s'",
                len(filters),
                source_name,
            )

            try:
                settings = PEQSettings(
                    source_name=source_name,
                    channel_mode="stereo",
                    bands=filters,
                )
                await safe_write.execute(source_name, settings)
                results.append(
                    SourceCopyResult(
                        source_name=source_name,
                        success=True,
                        message=f"Copied to {source_name}",
                    )
                )
                logger.info("Copy-to-source: completed for '%s'", source_name)
            except Exception as exc:
                logger.exception("Copy-to-source failed for '%s'", source_name)
                results.append(
                    SourceCopyResult(
                        source_name=source_name,
                        success=False,
                        message=str(exc),
                    )
                )

        self.copy_to_sources_complete.emit(results)

        succeeded = sum(1 for r in results if r.success)
        failed = len(results) - succeeded
        logger.info(
            "Copy-to-sources complete: %d succeeded, %d failed",
            succeeded,
            failed,
        )

    # ------------------------------------------------------------------
    # Workflow 2: Apply to Multiple Devices (Req 21)
    # ------------------------------------------------------------------

    @Slot(list, object)
    def apply_to_devices(
        self,
        filters: list[CanonicalFilter],
        request: MultiDeviceRequest,
    ) -> None:
        """Apply filters to multiple devices sequentially.

        For each device, connects, probes, and writes to the specified sources.
        Processes one device at a time for safety.

        If a push fails on one device, reports the failure and continues
        with remaining devices (fault isolation).

        Emits multi_device_progress per device and multi_device_complete
        with the full results list when all devices are processed.

        Args:
            filters: The canonical filters to push to each device/source.
            request: MultiDeviceRequest specifying device→source mappings.

        Requirements: 10.3, 10.4, 10.5, 10.6, 10.7.
        """
        assert self._bridge is not None
        self._bridge.run_async(self._do_apply_to_devices(filters, request))

    async def _do_apply_to_devices(
        self,
        filters: list[CanonicalFilter],
        request: MultiDeviceRequest,
    ) -> None:
        """Execute multi-device push with fault isolation per device.

        Each device is processed independently — one failure does NOT stop
        remaining devices (Req 10.7).
        """
        assert self._wiim_adapter_factory is not None
        assert self._safe_write_factory is not None

        results: list[DevicePushResult] = []

        for device_ip, source_list in request.device_source_map.items():
            device_name = request.device_names.get(device_ip, device_ip)

            try:
                self.multi_device_progress.emit(
                    f"Connecting to {device_name}..."
                )
                adapter = self._wiim_adapter_factory(device_ip)
                safe_write = self._safe_write_factory(adapter)

                for source_name in source_list:
                    self.multi_device_progress.emit(
                        f"Pushing to {device_name} / {source_name}..."
                    )
                    logger.info(
                        "Multi-device push: %s (%s) / source '%s'",
                        device_name,
                        device_ip,
                        source_name,
                    )

                    settings = PEQSettings(
                        source_name=source_name,
                        channel_mode="stereo",
                        bands=filters,
                    )
                    await safe_write.execute(source_name, settings)

                    results.append(
                        DevicePushResult(
                            device_ip=device_ip,
                            device_name=device_name,
                            source_name=source_name,
                            success=True,
                            message=f"Pushed to {device_name} / {source_name}",
                        )
                    )
            except Exception as exc:
                logger.exception(
                    "Multi-device push failed for %s (%s)", device_name, device_ip
                )
                # Record failure for all remaining sources on this device
                for source_name in source_list:
                    # Only add if not already recorded as success
                    already_recorded = any(
                        r.device_ip == device_ip and r.source_name == source_name
                        for r in results
                    )
                    if not already_recorded:
                        results.append(
                            DevicePushResult(
                                device_ip=device_ip,
                                device_name=device_name,
                                source_name=source_name,
                                success=False,
                                message=str(exc),
                            )
                        )

        self.multi_device_complete.emit(results)

        succeeded = sum(1 for r in results if r.success)
        total = len(results)
        failed = total - succeeded
        if failed > 0:
            logger.warning(
                "Multi-device complete: %d of %d succeeded, %d failed",
                succeeded,
                total,
                failed,
            )
        else:
            logger.info(
                "Multi-device complete: all %d device/source pairs succeeded",
                total,
            )

    # ------------------------------------------------------------------
    # Workflow 3: Copy Preset to Another Device (Req 17.3, 15.11)
    # ------------------------------------------------------------------

    @Slot(object, str)
    def copy_preset_to_device(
        self,
        preset_filters: list[CanonicalFilter],
        target_device_ip: str,
        target_source: str = "",
    ) -> None:
        """Copy a device preset to a different device.

        Connects to the target device, selects the target source, and
        writes the preset filters via Safe_Write_Protocol.

        Args:
            preset_filters: Filters from the source preset to write.
            target_device_ip: IP address of the target device.
            target_source: Target source name on the device (PEQ only).
                          Empty string for RoomFit (device-global).

        Requirements: 15.3, 15.4, 15.5, 15.6.
        """
        assert self._bridge is not None
        self._bridge.run_async(
            self._do_copy_preset_to_device(preset_filters, target_device_ip, target_source)
        )

    async def _do_copy_preset_to_device(
        self,
        filters: list[CanonicalFilter],
        target_ip: str,
        source_name: str,
    ) -> None:
        """Execute copy-preset-to-device via SafeWrite on target device."""
        assert self._wiim_adapter_factory is not None
        assert self._safe_write_factory is not None

        try:
            adapter = self._wiim_adapter_factory(target_ip)
            safe_write = self._safe_write_factory(adapter)

            settings = PEQSettings(
                source_name=source_name,
                channel_mode="stereo",
                bands=filters,
            )
            await safe_write.execute(source_name, settings)

            self.copy_to_device_complete.emit(
                True, f"Filters applied to {target_ip}"
            )
            logger.info("Copy-to-device: completed for %s", target_ip)
        except Exception as exc:
            logger.exception("Copy-to-device failed for %s", target_ip)
            self.copy_to_device_complete.emit(False, str(exc))

    # ------------------------------------------------------------------
    # Workflow 4: Profile Recall (Req 17.2)
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
        channel_mode: str = getattr(profile, "channel_mode", "stereo")

        # Extract filters based on channel mode
        if channel_mode in ("left", "right"):
            # L/R profile: combine both channels into flat list
            filters_l: list[CanonicalFilter] = getattr(profile, "filters_l", None) or []
            filters_r: list[CanonicalFilter] = getattr(profile, "filters_r", None) or []
            filters = filters_l + filters_r
        else:
            # Stereo profile
            filters = getattr(profile, "filters", None) or []

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

    # ------------------------------------------------------------------
    # Workflow 5: Undo Last Push (Req 18)
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
            # Read backup data from JSON file
            backup_data = json.loads(path.read_text(encoding="utf-8"))

            # Reconstruct PEQSettings from backup record
            channel_mode_raw = backup_data.get("channel_mode", "stereo")
            # BackupRecord uses "stereo"/"left"/"right"; PEQSettings uses "stereo"/"lr"
            peq_channel_mode: str = (
                "stereo" if channel_mode_raw == "stereo" else "lr"
            )

            if peq_channel_mode == "stereo":
                filters_raw = backup_data.get("filters", [])
                bands = [CanonicalFilter(**f) for f in filters_raw]
                settings = PEQSettings(
                    source_name=source_name,
                    channel_mode="stereo",
                    bands=bands,
                )
            else:
                filters_l_raw = backup_data.get("filters_l", [])
                filters_r_raw = backup_data.get("filters_r", [])
                bands_l = [CanonicalFilter(**f) for f in filters_l_raw]
                bands_r = [CanonicalFilter(**f) for f in filters_r_raw]
                settings = PEQSettings(
                    source_name=source_name,
                    channel_mode="lr",
                    bands_l=bands_l,
                    bands_r=bands_r,
                )

            # Execute SafeWrite with the restored settings
            safe_write = self._safe_write_factory(self._current_adapter)
            await safe_write.execute(source_name, settings)

            self.undo_complete.emit(True, "Previous filters restored")
            logger.info("Undo last push: completed successfully")
        except Exception as exc:
            logger.exception("Undo last push failed")
            self.undo_complete.emit(False, str(exc))
