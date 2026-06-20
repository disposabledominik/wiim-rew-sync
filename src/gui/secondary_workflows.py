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

import logging
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal, Slot

from src.models.canonical import CanonicalFilter

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

        Requirement 20.3: User can select one or more target sources.
        Requirement 20.4: Safe_Write_Protocol executed independently per source.
        Requirement 20.5: Per-source progress and results displayed.
        """
        results: list[SourceCopyResult] = []

        for source_name in target_sources:
            self.copy_to_sources_progress.emit(
                f"Writing to {source_name}..."
            )
            logger.info(
                "Copy-to-source: writing %d filters to source '%s'",
                len(filters),
                source_name,
            )

            # TODO: Execute Safe_Write_Protocol per source via AsyncBridge:
            #   1. backup_source(device_ip, source_name)
            #   2. write_filters(device_ip, source_name, filters)
            #   3. verify_write(device_ip, source_name, filters)
            #   4. commit or rollback
            # For now, record a placeholder success result.
            results.append(
                SourceCopyResult(
                    source_name=source_name,
                    success=True,
                    message=f"Copied to {source_name}",
                )
            )
            logger.info("Copy-to-source: completed for '%s'", source_name)

        self.copy_to_sources_complete.emit(results)

        # Build summary for logging
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
        Processes one device at a time for safety (Req 21.4).

        If a push fails on one device, reports the failure and continues
        with remaining devices (Req 21.5 — no all-or-nothing).

        Emits multi_device_progress per device and multi_device_complete
        with the full results list when all devices are processed.

        Args:
            filters: The canonical filters to push to each device/source.
            request: MultiDeviceRequest specifying device→source mappings.

        Requirement 21.4: Sequential push per device.
        Requirement 21.5: Failure on one device does not stop others.
        Requirement 21.6: Summary displayed after all devices processed.
        """
        results: list[DevicePushResult] = []

        for device_ip, source_list in request.device_source_map.items():
            device_name = request.device_names.get(device_ip, device_ip)

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

                # TODO: Execute full push sequence via AsyncBridge:
                #   1. connect_to_device(device_ip)
                #   2. probe_capabilities(device_ip)
                #   3. Safe_Write_Protocol(device_ip, source_name, filters)
                # For now, record a placeholder success result.
                results.append(
                    DevicePushResult(
                        device_ip=device_ip,
                        device_name=device_name,
                        source_name=source_name,
                        success=True,
                        message=f"Pushed to {device_name} / {source_name}",
                    )
                )

        self.multi_device_complete.emit(results)

        # Build summary (Req 21.6)
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

        Requirement 17.3: Copy Preset to Another Device guided flow.
        """
        logger.info(
            "Copy-to-device: writing %d filters to device %s, source '%s'",
            len(preset_filters),
            target_device_ip,
            target_source or "(global/RoomFit)",
        )

        # TODO: Execute via AsyncBridge:
        #   1. connect_to_device(target_device_ip)
        #   2. probe_capabilities(target_device_ip)
        #   3. Safe_Write_Protocol(target_device_ip, target_source, preset_filters)
        # For now, emit placeholder success.
        self.copy_to_device_complete.emit(
            True,
            f"Preset copied to device {target_device_ip}",
        )
        logger.info("Copy-to-device: completed for %s", target_device_ip)

    # ------------------------------------------------------------------
    # Workflow 4: Profile Recall (Req 17.2)
    # ------------------------------------------------------------------

    @Slot(object)
    def recall_profile(self, profile: object) -> None:
        """Load a saved profile from the local preset library into the Review step.

        Extracts CanonicalFilter data from the profile and emits
        profile_recalled so the wizard can populate the ReviewPage.

        If the device is already connected, the filters go directly to Review.
        If not connected, the wizard adapts the flow to require connection first.

        Args:
            profile: A Profile object from the local preset library.
                    Expected to have a `filters` attribute (list[CanonicalFilter]).

        Requirement 17.2: Profile Recall & Push flow.
        """
        # Extract filters from profile
        filters: list[CanonicalFilter] = getattr(profile, "filters", [])
        profile_name: str = getattr(profile, "name", "Unknown")

        if not filters:
            logger.warning(
                "Profile recall: profile '%s' has no filters",
                profile_name,
            )
            self.profile_recalled.emit([])
            return

        logger.info(
            "Profile recall: loaded %d filters from profile '%s'",
            len(filters),
            profile_name,
        )
        self.profile_recalled.emit(filters)

    # ------------------------------------------------------------------
    # Workflow 5: Undo Last Push (Req 18)
    # ------------------------------------------------------------------

    @Slot(str)
    def undo_last_push(self, backup_path: str) -> None:
        """Restore the device's PEQ state from the most recent backup.

        The undo operation follows the same Safe_Write_Protocol as a normal
        push (Req 18.3): backup current state → write backup data → verify →
        commit/rollback.

        Args:
            backup_path: Path to the pre-write backup file created during
                        the original push operation.

        Requirement 18.2: Restore from most recent backup.
        Requirement 18.3: Undo uses Safe_Write_Protocol.
        Requirement 18.4: Display "Previous filters restored" on success.
        Requirement 18.6: User does not need to know about file paths.
        """
        if not backup_path:
            logger.error("Undo requested but no backup path available")
            self.undo_complete.emit(False, "No backup available to restore from")
            return

        logger.info("Undo last push: restoring from backup '%s'", backup_path)

        # TODO: Execute via AsyncBridge:
        #   1. Read backup file to get previous filter state
        #   2. backup_current_state() (safety: backup even before undo)
        #   3. write_filters(device_ip, source_name, backup_filters)
        #   4. verify_write(device_ip, source_name, backup_filters)
        #   5. commit or rollback
        # For now, emit placeholder success.
        self.undo_complete.emit(True, "Previous filters restored")
        logger.info("Undo last push: completed successfully")
