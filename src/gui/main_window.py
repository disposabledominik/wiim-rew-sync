"""Main application window for WiiM <-> REW PEQ Sync.

Provides the top-level layout with real panels, a diagnostics dock,
status bar with progress indicator, connection to the AsyncBridge, and
controller logic that wires all async operations together.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.gui.async_bridge import AsyncBridge
from src.gui.dialogs.error_dialog import ErrorDialog
from src.gui.panels.action_bar import ActionBar
from src.gui.panels.device_panel import DevicePanel
from src.gui.panels.diagnostics_panel import DiagnosticsPanel
from src.gui.panels.eq_panel import EQPanel
from src.gui.panels.profile_panel import ProfilePanel
from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceCapabilities, DeviceInfo

logger = logging.getLogger("wiim_rew_sync.app")


def _make_placeholder(label_text: str) -> QWidget:
    """Create a placeholder QWidget with a centered label.

    Args:
        label_text: Text to display in the placeholder.

    Returns:
        A QWidget containing a centered QLabel.
    """
    widget = QWidget()
    layout = QVBoxLayout(widget)
    label = QLabel(label_text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(label)
    return widget


class MainWindow(QMainWindow):
    """Main application window.

    Layout:
        QMainWindow
        +-- QSplitter (vertical)
            +-- DevicePanel (fixed height ~120px)
            +-- QSplitter (horizontal)
            |   +-- SourceModePanel placeholder (fixed width ~200px)
            |   +-- EQPanel (fills remaining)
            +-- ActionBar (fixed height ~50px)
            +-- QTabWidget
                +-- ProfilePanel tab

    Also includes:
        - QDockWidget for diagnostics (hidden by default, toggle via View menu)
        - Status bar with indeterminate QProgressBar
        - Controller logic for all async operations
    """

    def __init__(self, async_bridge: AsyncBridge | None = None) -> None:
        """Initialize the main window.

        Args:
            async_bridge: The async bridge for background operations.
                         If None, a new one is created and started.
        """
        super().__init__()

        # --- Async bridge ---
        if async_bridge is None:
            self._bridge = AsyncBridge(self)
            self._bridge.start()
        else:
            self._bridge = async_bridge

        # --- Controller state ---
        self._selected_device: DeviceInfo | None = None
        self._capabilities: DeviceCapabilities | None = None
        self._current_filters: list[CanonicalFilter] = []
        self._dry_run_mode: bool = False

        # --- Window properties ---
        self.setWindowTitle("WiiM \u2194 REW PEQ Sync")
        self.resize(1200, 800)

        # --- Build UI ---
        self._setup_central_widget()
        self._setup_dock_widget()
        self._setup_status_bar()
        self._setup_menus()
        self._connect_signals()

    @property
    def bridge(self) -> AsyncBridge:
        """Access the async bridge instance."""
        return self._bridge

    @property
    def device_panel(self) -> DevicePanel:
        """Access the device panel widget."""
        return self._device_panel

    @property
    def eq_panel(self) -> EQPanel:
        """Access the EQ panel widget."""
        return self._eq_panel

    @property
    def action_bar(self) -> ActionBar:
        """Access the action bar widget."""
        return self._action_bar

    @property
    def profile_panel(self) -> ProfilePanel:
        """Access the profile panel widget."""
        return self._profile_panel

    def _setup_central_widget(self) -> None:
        """Build the central widget with the vertical splitter layout."""
        # Top-level vertical splitter
        main_splitter = QSplitter(Qt.Orientation.Vertical)

        # Device panel (fixed height ~120px)
        self._device_panel = DevicePanel()
        self._device_panel.setMinimumHeight(100)
        self._device_panel.setMaximumHeight(140)
        main_splitter.addWidget(self._device_panel)

        # Horizontal splitter for source mode + EQ panel
        h_splitter = QSplitter(Qt.Orientation.Horizontal)

        source_mode_panel = _make_placeholder("[Source Mode Panel]")
        source_mode_panel.setMinimumWidth(180)
        source_mode_panel.setMaximumWidth(250)
        h_splitter.addWidget(source_mode_panel)

        self._eq_panel = EQPanel()
        h_splitter.addWidget(self._eq_panel)

        # Set stretch factors: source mode fixed, EQ fills
        h_splitter.setStretchFactor(0, 0)
        h_splitter.setStretchFactor(1, 1)

        main_splitter.addWidget(h_splitter)

        # Action bar (fixed height ~50px)
        self._action_bar = ActionBar()
        self._action_bar.setMinimumHeight(40)
        self._action_bar.setMaximumHeight(60)
        main_splitter.addWidget(self._action_bar)

        # Tab widget for profiles
        tab_widget = QTabWidget()
        self._profile_panel = ProfilePanel()
        tab_widget.addTab(self._profile_panel, "Profiles")
        main_splitter.addWidget(tab_widget)

        # Set stretch factors: device + action fixed, middle + tabs fill
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setStretchFactor(2, 0)
        main_splitter.setStretchFactor(3, 1)

        self.setCentralWidget(main_splitter)

    @property
    def diagnostics_panel(self) -> DiagnosticsPanel:
        """Access the diagnostics panel widget."""
        return self._diagnostics_panel

    def _setup_dock_widget(self) -> None:
        """Create the diagnostics dock widget (hidden by default)."""
        self._diagnostics_dock = QDockWidget("Diagnostics", self)
        self._diagnostics_dock.setObjectName("diagnostics_dock")

        self._diagnostics_panel = DiagnosticsPanel()
        self._diagnostics_dock.setWidget(self._diagnostics_panel)

        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._diagnostics_dock)
        self._diagnostics_dock.setVisible(False)

    def _setup_status_bar(self) -> None:
        """Set up the status bar with an indeterminate progress bar."""
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)  # Indeterminate mode
        self._progress_bar.setMaximumWidth(200)
        self._progress_bar.setVisible(False)

        self.statusBar().addPermanentWidget(self._progress_bar)

    def _setup_menus(self) -> None:
        """Create the menu bar with a View menu."""
        view_menu = self.menuBar().addMenu("&View")

        self._diagnostics_action = QAction("&Diagnostics", self)
        self._diagnostics_action.setCheckable(True)
        self._diagnostics_action.setChecked(False)
        self._diagnostics_action.toggled.connect(self._diagnostics_dock.setVisible)
        self._diagnostics_dock.visibilityChanged.connect(self._diagnostics_action.setChecked)

        view_menu.addAction(self._diagnostics_action)

    def _connect_signals(self) -> None:
        """Connect all signals: bridge, panels, and action bar."""
        # --- AsyncBridge -> status bar ---
        self._bridge.operation_started.connect(self._on_operation_started)
        self._bridge.operation_finished.connect(self._on_operation_finished)
        self._bridge.progress_update.connect(self._on_progress_update)

        # --- AsyncBridge -> panels ---
        self._bridge.discovery_complete.connect(self._device_panel.on_discovery_complete)
        self._bridge.capabilities_ready.connect(self._on_capabilities_ready)
        self._bridge.peq_ready.connect(self._on_peq_ready)
        self._bridge.write_complete.connect(self._on_write_complete)
        self._bridge.operation_error.connect(self._on_operation_error)

        # --- DevicePanel signals ---
        self._device_panel.refresh_requested.connect(self._on_device_refresh_requested)
        self._device_panel.device_selected.connect(self._on_device_selected)

        # --- EQPanel signals ---
        self._eq_panel.pull_requested.connect(self._on_eq_pull_requested)
        self._eq_panel.roomfit_pull_requested.connect(self._on_roomfit_pull_requested)
        self._eq_panel.roomfit_push_requested.connect(self._on_roomfit_push_requested)

        # --- ActionBar signals ---
        self._action_bar.import_requested.connect(self._on_import_requested)
        self._action_bar.export_requested.connect(self._on_export_requested)
        self._action_bar.pull_requested.connect(self._on_action_pull_requested)
        self._action_bar.push_requested.connect(self._on_push_requested)
        self._action_bar.dry_run_toggled.connect(self._on_dry_run_toggled)

        # --- ProfilePanel signals ---
        self._profile_panel.profile_save_requested.connect(self._on_profile_save_requested)
        self._profile_panel.profile_load_requested.connect(self._on_profile_load_requested)

    # ------------------------------------------------------------------
    # Status Bar Handlers
    # ------------------------------------------------------------------

    def _on_operation_started(self) -> None:
        """Show the progress bar when an operation starts."""
        self._progress_bar.setVisible(True)

    def _on_operation_finished(self) -> None:
        """Hide the progress bar when an operation finishes."""
        self._progress_bar.setVisible(False)
        self.statusBar().clearMessage()

    def _on_progress_update(self, message: str) -> None:
        """Display a progress message in the status bar.

        Args:
            message: Human-readable status message.
        """
        self.statusBar().showMessage(message)

    # ------------------------------------------------------------------
    # Discovery Flow
    # ------------------------------------------------------------------

    def _on_device_refresh_requested(self) -> None:
        """Handle device panel refresh request - run discovery via bridge."""
        self._bridge.run_async(self._do_discover())

    async def _do_discover(self) -> None:
        """Run device discovery and emit results.

        Creates a DiscoveryModule, runs discover(), and emits
        discovery_complete with the results.
        """
        try:
            from src.discovery.discovery_module import DiscoveryModule

            module = DiscoveryModule(timeout=5.0)
            devices = await module.discover()
            self._bridge.discovery_complete.emit(devices)
        except Exception as exc:
            self._bridge.operation_error.emit(type(exc).__name__, str(exc))

    # ------------------------------------------------------------------
    # Device Selection Flow
    # ------------------------------------------------------------------

    def _on_device_selected(self, device_info: object) -> None:
        """Handle device selection - probe capabilities via bridge.

        Args:
            device_info: The selected DeviceInfo object.
        """
        if not isinstance(device_info, DeviceInfo):
            return

        self._selected_device = device_info
        self._action_bar.set_device_selected(True)
        self._bridge.run_async(self._do_probe(device_info))

    async def _do_probe(self, device_info: DeviceInfo) -> None:
        """Probe device capabilities and emit results.

        Args:
            device_info: Device to probe.
        """
        try:
            from src.adapters.capability_prober import CapabilityProber
            from src.adapters.wiim_http import WiiMHttpClient

            client = WiiMHttpClient(device_info.ip, timeout=5.0)
            try:
                prober = CapabilityProber(client)
                capabilities = await prober.probe()
                self._bridge.capabilities_ready.emit(capabilities)
            finally:
                await client.close()
        except Exception as exc:
            self._bridge.operation_error.emit(type(exc).__name__, str(exc))

    def _on_capabilities_ready(self, capabilities: object) -> None:
        """Handle capabilities ready - update all panels.

        Args:
            capabilities: The probed DeviceCapabilities object.
        """
        if not isinstance(capabilities, DeviceCapabilities):
            return

        self._capabilities = capabilities

        # Update panels
        self._eq_panel.on_capabilities_ready(capabilities)
        self._profile_panel.on_capabilities_ready(capabilities)
        self._action_bar.set_capabilities(capabilities)
        self._action_bar.set_source_selected(False)
        self._diagnostics_panel.on_capabilities_ready(capabilities)

    # ------------------------------------------------------------------
    # Pull Flow
    # ------------------------------------------------------------------

    def _on_eq_pull_requested(self, source: str, channel: str) -> None:
        """Handle EQ panel pull request.

        Args:
            source: Source name (e.g. "wifi").
            channel: Channel mode string.
        """
        self._action_bar.set_source_selected(True)
        self._bridge.run_async(self._do_pull(source, channel))

    def _on_action_pull_requested(self) -> None:
        """Handle action bar pull request - use current EQ panel source."""
        source = self._eq_panel._source_combo.currentText()
        channel = self._eq_panel._channel_combo.currentText()
        if not source:
            self._bridge.operation_error.emit("ValueError", "No source selected")
            return
        self._action_bar.set_source_selected(True)
        self._bridge.run_async(self._do_pull(source, channel))

    async def _do_pull(self, source: str, channel: str) -> None:
        """Read PEQ from device and emit results.

        Args:
            source: Source name (e.g. "wifi").
            channel: Channel mode string (for future L/R support).
        """
        try:
            from src.adapters.wiim_adapter import WiiMAdapter
            from src.adapters.wiim_http import WiiMHttpClient

            if self._selected_device is None or self._capabilities is None:
                self._bridge.operation_error.emit("ValueError", "No device selected")
                return

            client = WiiMHttpClient(self._selected_device.ip, timeout=5.0)
            try:
                adapter = WiiMAdapter(client, self._capabilities)
                settings = await adapter.read_peq(source)
                self._bridge.peq_ready.emit(settings)
            finally:
                await client.close()
        except Exception as exc:
            self._bridge.operation_error.emit(type(exc).__name__, str(exc))

    def _on_peq_ready(self, settings: object) -> None:
        """Handle PEQ settings received - update EQ panel and state.

        Args:
            settings: The PEQSettings object from the device.
        """
        from src.models.peq import PEQSettings

        if not isinstance(settings, PEQSettings):
            return

        self._eq_panel.on_peq_ready(settings)
        self._current_filters = settings.bands if settings.bands else []
        self._action_bar.set_filters_loaded(len(self._current_filters) > 0)

    # ------------------------------------------------------------------
    # Push Flow
    # ------------------------------------------------------------------

    def _on_push_requested(self) -> None:
        """Handle push request - write PEQ to device via safe write."""
        if self._dry_run_mode:
            self._do_dry_run_push()
            return

        source = self._eq_panel._source_combo.currentText()
        if not source:
            self._bridge.operation_error.emit("ValueError", "No source selected")
            return

        if not self._current_filters:
            self._bridge.operation_error.emit("ValueError", "No filters to push")
            return

        from src.models.peq import PEQSettings

        settings = PEQSettings(
            source_name=source,
            enabled=True,
            channel_mode="stereo",
            bands=self._current_filters,
        )
        self._bridge.run_async(self._do_push(source, settings))

    def _do_dry_run_push(self) -> None:
        """Execute dry-run push - generate band array and show warnings.

        No safe-write, no backup, no network. Displays clamping warnings
        in a QMessageBox.
        """
        from src.translator import TranslationEngine

        if not self._current_filters:
            QMessageBox.information(self, "Dry Run", "No filters loaded.")
            return

        max_bands = 10
        if self._capabilities is not None:
            max_bands = self._capabilities.max_filters or 10

        _band_array, warnings = TranslationEngine.generate_wiim_band_array(
            self._current_filters, max_bands=max_bands
        )

        if warnings:
            warning_lines = [f"- {w.field}: {w.message}" for w in warnings]
            msg = "Dry Run completed with clamping warnings:\n\n" + "\n".join(warning_lines)
        else:
            msg = (
                f"Dry Run completed successfully.\n\n"
                f"{len(self._current_filters)} filter(s) would be written "
                f"to the device with no clamping."
            )

        QMessageBox.information(self, "Dry Run Result", msg)

    async def _do_push(self, source: str, settings: object) -> None:
        """Execute safe write protocol and emit results.

        Args:
            source: Source name (e.g. "wifi").
            settings: PEQ settings to write.
        """
        try:
            from src.adapters.safe_write import SafeWrite
            from src.adapters.wiim_adapter import WiiMAdapter
            from src.adapters.wiim_http import WiiMHttpClient
            from src.models.peq import PEQSettings
            from src.repository.backup_manager import BackupManager
            from src.utils.app_dirs import get_app_data_dir

            if self._selected_device is None or self._capabilities is None:
                self._bridge.operation_error.emit("ValueError", "No device selected")
                return

            if not isinstance(settings, PEQSettings):
                self._bridge.operation_error.emit("TypeError", "Invalid settings type")
                return

            client = WiiMHttpClient(self._selected_device.ip, timeout=5.0)
            try:
                adapter = WiiMAdapter(client, self._capabilities)
                backup_mgr = BackupManager(get_app_data_dir())
                safe_write = SafeWrite(adapter, backup_mgr)
                result = await safe_write.execute(source, settings)
                self._bridge.write_complete.emit(result)
            finally:
                await client.close()
        except Exception as exc:
            self._bridge.operation_error.emit(type(exc).__name__, str(exc))

    def _on_write_complete(self, result: object) -> None:
        """Handle write completion - show success/failure notification.

        Args:
            result: The WriteResult object.
        """
        from src.adapters.safe_write import WriteResult

        if not isinstance(result, WriteResult):
            return

        if result.success:
            self.statusBar().showMessage("Push successful", 5000)
            self._action_bar.enable_preset_save(True)

            # If user requested preset save, do it now
            if self._action_bar.preset_save_requested and self._action_bar.preset_name:
                self._save_as_preset(self._action_bar.preset_name)
        else:
            msg = result.error_message or "Write failed"
            if result.rollback_success:
                msg += "\n\nOriginal state has been restored."
            elif result.rollback_success is False:
                msg += "\n\nROLLBACK ALSO FAILED. Manual recovery required."
            QMessageBox.critical(self, "Push Failed", msg)

    def _save_as_preset(self, preset_name: str) -> None:
        """Save current PEQ state as a named device preset.

        Args:
            preset_name: Name for the device preset.
        """
        source = self._eq_panel._source_combo.currentText()
        if not source or self._selected_device is None:
            return
        self._bridge.run_async(self._do_save_preset(source, preset_name))

    async def _do_save_preset(self, source: str, preset_name: str) -> None:
        """Save PEQ as device preset via adapter.

        Args:
            source: Source name.
            preset_name: Preset name to save as.
        """
        try:
            from src.adapters.wiim_adapter import WiiMAdapter
            from src.adapters.wiim_http import WiiMHttpClient

            if self._selected_device is None or self._capabilities is None:
                return

            client = WiiMHttpClient(self._selected_device.ip, timeout=5.0)
            try:
                adapter = WiiMAdapter(client, self._capabilities)
                await adapter.save_peq_profile(source, preset_name)
                self.statusBar().showMessage(f"Preset '{preset_name}' saved", 5000)
            finally:
                await client.close()
        except Exception as exc:
            self._bridge.operation_error.emit(type(exc).__name__, str(exc))

    # ------------------------------------------------------------------
    # Import Flow
    # ------------------------------------------------------------------

    def _on_import_requested(self) -> None:
        """Handle import request - open ImportDialog."""
        from src.gui.dialogs.import_dialog import ImportDialog

        max_filters = 10
        if self._capabilities is not None and self._capabilities.max_filters > 0:
            max_filters = self._capabilities.max_filters

        filters = ImportDialog.get_filters(max_filters=max_filters, parent=self)
        if filters is not None:
            self._current_filters = filters
            self._action_bar.set_filters_loaded(True)

            # Update EQ panel with imported filters
            from src.models.peq import PEQSettings

            source = self._eq_panel._source_combo.currentText() or "imported"
            settings = PEQSettings(
                source_name=source,
                enabled=True,
                channel_mode="stereo",
                bands=filters,
            )
            self._eq_panel.on_peq_ready(settings)
            self.statusBar().showMessage(
                f"Imported {len(filters)} filter(s)", 5000
            )

    # ------------------------------------------------------------------
    # Export Flow
    # ------------------------------------------------------------------

    def _on_export_requested(self) -> None:
        """Handle export request - open ExportDialog and write file."""
        from src.gui.dialogs.export_dialog import ExportDialog
        from src.translator import TranslationEngine

        if not self._current_filters:
            QMessageBox.information(self, "Export", "No filters to export.")
            return

        channel_mode = "stereo"
        if self._capabilities is not None and self._capabilities.supports_channel_peq:
            channel = self._eq_panel._channel_combo.currentText()
            if channel in ("Left", "Right"):
                channel_mode = "lr"

        paths = ExportDialog.get_paths(channel_mode=channel_mode, parent=self)
        if paths is None:
            return

        max_filters = 10
        if self._capabilities is not None and self._capabilities.max_filters > 0:
            max_filters = self._capabilities.max_filters

        try:
            if isinstance(paths, tuple):
                # L/R export
                TranslationEngine.generate_rew_file(
                    self._current_filters, paths[0], max_filters=max_filters
                )
                TranslationEngine.generate_rew_file(
                    self._current_filters, paths[1], max_filters=max_filters
                )
            else:
                TranslationEngine.generate_rew_file(
                    self._current_filters, paths, max_filters=max_filters
                )
            self.statusBar().showMessage("Export complete", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))

    # ------------------------------------------------------------------
    # RoomFit Flows
    # ------------------------------------------------------------------

    def _on_roomfit_pull_requested(self, source: str, profile: str) -> None:
        """Handle RoomFit pull request.

        Args:
            source: Source name.
            profile: RoomFit profile name.
        """
        self._bridge.run_async(self._do_roomfit_pull(source, profile))

    async def _do_roomfit_pull(self, source: str, profile: str) -> None:
        """Read RoomFit from device and emit results.

        Args:
            source: Source name.
            profile: RoomFit profile name.
        """
        try:
            from src.adapters.wiim_adapter import WiiMAdapter
            from src.adapters.wiim_http import WiiMHttpClient

            if self._selected_device is None or self._capabilities is None:
                self._bridge.operation_error.emit("ValueError", "No device selected")
                return

            client = WiiMHttpClient(self._selected_device.ip, timeout=5.0)
            try:
                adapter = WiiMAdapter(client, self._capabilities)
                settings = await adapter.read_roomfit(source, profile)
                self._bridge.peq_ready.emit(settings)
            finally:
                await client.close()
        except Exception as exc:
            self._bridge.operation_error.emit(type(exc).__name__, str(exc))

    def _on_roomfit_push_requested(self, source: str, profile: str) -> None:
        """Handle RoomFit push request.

        Args:
            source: Source name.
            profile: RoomFit profile name.
        """
        if not self._current_filters:
            self._bridge.operation_error.emit("ValueError", "No filters to push to RoomFit")
            return
        self._bridge.run_async(
            self._do_roomfit_push(source, profile, self._current_filters)
        )

    async def _do_roomfit_push(
        self, source: str, profile: str, filters: list[CanonicalFilter]
    ) -> None:
        """Write RoomFit to device.

        Args:
            source: Source name.
            profile: RoomFit profile name.
            filters: Filters to write.
        """
        try:
            from src.adapters.wiim_adapter import WiiMAdapter
            from src.adapters.wiim_http import WiiMHttpClient

            if self._selected_device is None or self._capabilities is None:
                self._bridge.operation_error.emit("ValueError", "No device selected")
                return

            client = WiiMHttpClient(self._selected_device.ip, timeout=5.0)
            try:
                adapter = WiiMAdapter(client, self._capabilities)
                await adapter.write_roomfit(source, profile, filters)
                self.statusBar().showMessage(
                    f"RoomFit '{profile}' written successfully", 5000
                )
            finally:
                await client.close()
        except Exception as exc:
            self._bridge.operation_error.emit(type(exc).__name__, str(exc))

    # ------------------------------------------------------------------
    # Profile Flows
    # ------------------------------------------------------------------

    def _on_profile_save_requested(self, name: str) -> None:
        """Handle profile save request.

        Args:
            name: Profile name to save as.
        """
        if not self._current_filters:
            QMessageBox.information(self, "Save Profile", "No filters to save.")
            return

        try:
            from src.models.profile import Profile
            from src.repository.profile_repository import ProfileRepository
            from src.utils.app_dirs import get_app_data_dir

            profile = Profile(
                name=name,
                channel_mode="stereo",
                filters=self._current_filters,
            )
            repo = ProfileRepository(get_app_data_dir())
            repo.save(profile)
            self._refresh_profile_list()
            self.statusBar().showMessage(f"Profile '{name}' saved", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", str(exc))

    def _on_profile_load_requested(self, profile: object) -> None:
        """Handle profile load request - populate EQ panel.

        Args:
            profile: The Profile object to load.
        """
        from src.models.peq import PEQSettings
        from src.models.profile import Profile

        if not isinstance(profile, Profile):
            return

        filters = profile.filters or []
        self._current_filters = filters
        self._action_bar.set_filters_loaded(len(filters) > 0)

        source = self._eq_panel._source_combo.currentText() or profile.name
        settings = PEQSettings(
            source_name=source,
            enabled=True,
            channel_mode="stereo",
            bands=filters,
        )
        self._eq_panel.on_peq_ready(settings)
        self.statusBar().showMessage(f"Profile '{profile.name}' loaded", 5000)

    def _refresh_profile_list(self) -> None:
        """Refresh the profile panel's list from the repository."""
        try:
            from src.repository.profile_repository import ProfileRepository
            from src.utils.app_dirs import get_app_data_dir

            repo = ProfileRepository(get_app_data_dir())
            profiles = repo.list()
            self._profile_panel.on_profiles_updated(profiles)
        except Exception as exc:
            logger.warning("Failed to refresh profiles: %s", exc)

    # ------------------------------------------------------------------
    # Dry Run
    # ------------------------------------------------------------------

    def _on_dry_run_toggled(self, active: bool) -> None:
        """Handle dry run toggle.

        Args:
            active: Whether dry run is now active.
        """
        self._dry_run_mode = active

    # ------------------------------------------------------------------
    # Error Handling
    # ------------------------------------------------------------------

    def _on_operation_error(self, error_type: str, message: str) -> None:
        """Handle operation errors - show ErrorDialog with appropriate severity.

        Maps error_type to severity and title, then shows the ErrorDialog.
        All errors are also logged at ERROR or CRITICAL level.

        Args:
            error_type: Exception type name.
            message: Human-readable error message.
        """
        from src.gui.dialogs.error_dialog import Severity

        # --- Error type mapping ---
        _ERROR_MAP: dict[str, tuple[Severity, str]] = {
            "WiiMConnectionError": ("ERROR", "Device Offline"),
            "WiiMTimeoutError": ("ERROR", "Device Offline"),
            "WiiMResponseError": ("ERROR", "Communication Error"),
            "ParseError": ("ERROR", "Parse Error"),
            "ValidationError": ("WARNING", "Validation Warning"),
            "SchemaVersionError": ("ERROR", "Profile Incompatible"),
            "ProfileNotFoundError": ("ERROR", "Profile Not Found"),
            "BackupError": ("ERROR", "Backup Failed"),
            "VerificationError": ("ERROR", "Write Verification Failed"),
            "RollbackError": ("CRITICAL", "\u26a0 Critical: Device State May Be Incorrect"),
            "REWNotConnectedError": ("WARNING", "REW Not Connected"),
            "REWMeasurementNotFoundError": ("ERROR", "Measurement Not Found"),
        }

        severity: Severity
        title: str
        severity, title = _ERROR_MAP.get(error_type, ("ERROR", "Error"))

        # Log at appropriate level
        if severity == "CRITICAL":
            logger.critical("Operation error [%s]: %s", error_type, message)
        else:
            logger.error("Operation error [%s]: %s", error_type, message)

        # For RollbackError, extract backup path from message if present
        backup_path: str | None = None
        if error_type == "RollbackError":
            backup_path = self._extract_backup_path(message)

        # Show dialog
        ErrorDialog.show_error(
            severity,
            title,
            message,
            backup_path=backup_path,
            parent=self,
        )

    @staticmethod
    def _extract_backup_path(message: str) -> str | None:
        """Extract a file path from a RollbackError message.

        Looks for common path patterns in the message string.

        Args:
            message: The error message that may contain a backup file path.

        Returns:
            Extracted path string, or None if not found.
        """
        import re

        # Match Unix or Windows absolute paths
        match = re.search(r'(/[\w./_-]+\.json|[A-Z]:\\[\w.\\_-]+\.json)', message)
        if match:
            return match.group(0)
        return None

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close by shutting down the async bridge.

        Args:
            event: The close event.
        """
        self._bridge.shutdown()
        super().closeEvent(event)
