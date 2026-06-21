"""Main application window — wizard-driven single-pane interface.

Replaces the old splitter-based MainWindow. Serves as the application shell
with SidebarNav, StepIndicator, QStackedWidget content area, StatusBanner,
and a diagnostics dock widget.

Requirements referenced: 14.1, 14.2, 14.4, 14.5, 10.1, 10.6, 24.6,
    10.5, 10.11, 10.12, 10.13, 13.1-13.6, 26.1-26.7.
"""

from __future__ import annotations

import logging
import sys
import traceback
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, Literal

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMenuBar,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.adapters.capability_prober import CapabilityProber
from src.adapters.rew_http_client import REWHttpApiClient
from src.adapters.safe_write import SafeWrite
from src.adapters.wiim_adapter import WiiMAdapter
from src.adapters.wiim_http import WiiMHttpClient
from src.discovery.discovery_module import DiscoveryModule
from src.gui.app_settings import AppSettings
from src.gui.async_bridge import AsyncBridge
from src.gui.components.sidebar_nav import SidebarNav
from src.gui.components.status_banner import StatusBanner
from src.gui.components.step_indicator import StepIndicator
from src.gui.constants import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH
from src.gui.dialogs.crash_dialog import CrashDialog
from src.gui.dialogs.device_picker import DevicePickerDialog
from src.gui.dialogs.measurement_picker import MeasurementPickerDialog
from src.gui.dialogs.onboarding_overlay import OnboardingOverlay
from src.gui.dialogs.source_picker import SourcePickerDialog
from src.gui.dialogs.unsaved_changes_dialog import UnsavedChangesDialog
from src.gui.operation_feedback import OperationFeedbackManager
from src.gui.pages.connect_page import ConnectPage
from src.gui.pages.eq_type_page import EQTypePage
from src.gui.pages.filters_page import FiltersPage
from src.gui.pages.name_profile_page import NameProfilePage
from src.gui.pages.push_page import PushPage
from src.gui.pages.review_page import ReviewPage
from src.gui.pages.source_page import SourcePage
from src.gui.panels.diagnostics_panel import DiagnosticsPanel
from src.gui.secondary_workflows import (
    DevicePushResult,
    MultiDeviceRequest,
    SecondaryWorkflowManager,
    SourceCopyResult,
)
from src.gui.theme import ThemeManager
from src.gui.views.help_view import HelpView
from src.gui.views.my_presets_view import MyPresetsView
from src.gui.views.presets_device_view import PresetsDeviceView
from src.gui.views.settings_view import SettingsView
from src.gui.wizard_controller import FlowType, WizardController, WizardStep
from src.models.capabilities import DeviceInfo
from src.models.errors import (
    ParseError,
    REWNotConnectedError,
    ValidationError,
    WiiMConnectionError,
    WiiMTimeoutError,
)
from src.models.peq import PEQSettings
from src.repository.backup_manager import BackupManager
from src.repository.profile_repository import ProfileRepository
from src.utils.app_dirs import get_app_data_dir, get_log_dir

logger = logging.getLogger("wiim_rew_sync.app")

# Page/view indices in the QStackedWidget
PAGE_INDICES: dict[str, int] = {
    "connect": 0,
    "eq_type": 1,
    "source": 2,
    "filters": 3,
    "review": 4,
    "name_profile": 5,
    "push": 6,
    "presets_device": 7,
    "my_presets": 8,
    "settings": 9,
    "help": 10,
}


def _crash_handler(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: object,
) -> None:
    """Global exception handler installed via sys.excepthook.

    Logs the unhandled exception and shows the CrashDialog (Req 24.6).
    """
    # Format traceback for logging
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
    logger.critical("Unhandled exception:\n%s", "".join(tb_lines))

    log_path = str(get_log_dir() / "app.log")
    error_message = f"{exc_type.__name__}: {exc_value}"

    try:
        CrashDialog.show_crash(
            parent=None,
            error_message=error_message,
            log_path=log_path,
        )
    except Exception:
        # If crash dialog itself fails, at least we logged it above
        logger.debug("Crash dialog display failed (app may be in unstable state)")


class MainWindow(QMainWindow):
    """Application shell: sidebar + content stack + status banner.

    Layout:
        QMainWindow
        +-- MenuBar (File, View, Help)
        +-- Central Widget (QHBoxLayout)
        |   +-- SidebarNav (left, collapsible)
        |   +-- QVBoxLayout (right content area)
        |       +-- StepIndicator (top, fixed height)
        |       +-- QStackedWidget (center, fills)
        |       +-- StatusBanner (bottom, fixed height)
        +-- QDockWidget (Diagnostics, hidden by default)
    """

    def __init__(self, async_bridge: AsyncBridge | None = None) -> None:
        """Initialize the main window.

        Args:
            async_bridge: The async bridge for background operations.
                         If None, a new one is created and started.
        """
        super().__init__()

        # --- Install global crash handler (Req 24.6) ---
        sys.excepthook = _crash_handler

        # --- Load settings ---
        self._settings = AppSettings.load()

        # --- Async bridge (dependency injection) ---
        if async_bridge is None:
            self._bridge = AsyncBridge(self)
            self._bridge.start()
        else:
            self._bridge = async_bridge

        # --- Backend adapter instances (Req 14.1-14.6) ---
        # Eagerly created at startup:
        self._discovery_module = DiscoveryModule(
            timeout=float(self._settings.discovery_timeout),
        )
        self._rew_client = REWHttpApiClient()
        presets_dir = (
            Path(self._settings.presets_directory)
            if self._settings.presets_directory
            else get_app_data_dir()
        )
        self._profile_repository = ProfileRepository(storage_root=presets_dir)
        self._backup_manager = BackupManager(storage_root=presets_dir)

        # Lazily created on device selection (Req 14.2, 14.3):
        self._wiim_http_client: WiiMHttpClient | None = None
        self._capability_prober: CapabilityProber | None = None
        self._wiim_adapter: WiiMAdapter | None = None
        self._safe_write: SafeWrite | None = None
        self._device_caps: object | None = None

        # Discovered devices cache (populated by discovery, used by device picker)
        self._discovered_devices: list[DeviceInfo] = []

        # --- Window properties ---
        self.setWindowTitle("WiiM \u2194 REW PEQ Sync")
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.resize(1000, 700)

        # --- Create controller ---
        self._wizard_controller = WizardController(self)

        # --- Build UI ---
        self._setup_central_widget()
        self._setup_dock_widget()
        self._setup_menus()

        # --- Operation feedback manager (Req 13.1-13.6) ---
        self._feedback_manager = OperationFeedbackManager(
            self._status_banner, parent=self
        )

        # --- Apply initial settings state ---
        self._apply_settings()

        # --- Wire wizard/page/bridge signals ---
        self._wire_signals()

        # --- Wire operation feedback to bridge ---
        self._wire_operation_feedback()

        # --- Wire settings signals ---
        self._connect_settings_signals()

        # --- Wire onboarding signals ---
        self._connect_onboarding_signals()

        # --- Keyboard shortcuts and accessibility (Req 26.1-26.7) ---
        self._setup_keyboard_shortcuts()
        self._setup_accessibility()

        # --- Secondary workflows (Req 17, 18, 20, 21) ---
        self._setup_secondary_workflows()

        # --- Initialize step indicator with default flow ---
        sequence = self._wizard_controller.get_steps()
        labels = [step.value.replace("_", " ").title() for step in sequence]
        self._step_indicator.set_steps(labels)
        self._step_indicator.set_current(0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def bridge(self) -> AsyncBridge:
        """Access the async bridge instance."""
        return self._bridge

    @property
    def wizard_controller(self) -> WizardController:
        """Access the wizard controller."""
        return self._wizard_controller

    @property
    def stacked_widget(self) -> QStackedWidget:
        """Access the central stacked widget."""
        return self._stacked_widget

    @property
    def sidebar_nav(self) -> SidebarNav:
        """Access the sidebar navigation widget."""
        return self._sidebar_nav

    @property
    def step_indicator(self) -> StepIndicator:
        """Access the step indicator widget."""
        return self._step_indicator

    @property
    def status_banner(self) -> StatusBanner:
        """Access the status banner widget."""
        return self._status_banner

    @property
    def settings(self) -> AppSettings:
        """Access the loaded application settings."""
        return self._settings

    @property
    def feedback_manager(self) -> OperationFeedbackManager:
        """Access the operation feedback manager."""
        return self._feedback_manager

    @property
    def secondary_workflows(self) -> SecondaryWorkflowManager:
        """Access the secondary workflow manager."""
        return self._secondary_workflows

    # ------------------------------------------------------------------
    # Page / View accessors
    # ------------------------------------------------------------------

    @property
    def connect_page(self) -> ConnectPage:
        """Access the connect page."""
        return self._connect_page

    @property
    def eq_type_page(self) -> EQTypePage:
        """Access the EQ type page."""
        return self._eq_type_page

    @property
    def source_page(self) -> SourcePage:
        """Access the source page."""
        return self._source_page

    @property
    def filters_page(self) -> FiltersPage:
        """Access the filters page."""
        return self._filters_page

    @property
    def review_page(self) -> ReviewPage:
        """Access the review page."""
        return self._review_page

    @property
    def name_profile_page(self) -> NameProfilePage:
        """Access the name profile page."""
        return self._name_profile_page

    @property
    def push_page(self) -> PushPage:
        """Access the push page."""
        return self._push_page

    @property
    def presets_device_view(self) -> PresetsDeviceView:
        """Access the presets on device view."""
        return self._presets_device_view

    @property
    def my_presets_view(self) -> MyPresetsView:
        """Access the my presets view."""
        return self._my_presets_view

    @property
    def settings_view(self) -> SettingsView:
        """Access the settings view."""
        return self._settings_view

    @property
    def help_view(self) -> HelpView:
        """Access the help view."""
        return self._help_view

    @property
    def onboarding_overlay(self) -> OnboardingOverlay:
        """Access the onboarding overlay."""
        return self._onboarding_overlay

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_central_widget(self) -> None:
        """Build the central widget: sidebar + content area."""
        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # --- Sidebar (left) ---
        self._sidebar_nav = SidebarNav()
        root_layout.addWidget(self._sidebar_nav)

        # --- Content area (right) ---
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Step indicator (top) — fixed height, anchored position (Req 10.11)
        self._step_indicator = StepIndicator()
        self._step_indicator.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        content_layout.addWidget(self._step_indicator)

        # Stacked widget (center, stretch) — reserve minimum height (Req 10.12)
        self._stacked_widget = QStackedWidget()
        self._stacked_widget.setMinimumHeight(400)
        content_layout.addWidget(self._stacked_widget, stretch=1)

        # Status banner (bottom) — fixed height, anchored position (Req 10.11)
        self._status_banner = StatusBanner()
        self._status_banner.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        content_layout.addWidget(self._status_banner)

        root_layout.addLayout(content_layout, stretch=1)

        # --- Instantiate and register all pages/views ---
        self._create_pages()
        self._register_pages()

        # --- Onboarding overlay (parented to central widget) ---
        self._onboarding_overlay = OnboardingOverlay(central)
        self._onboarding_overlay.setVisible(False)

    def _create_pages(self) -> None:
        """Instantiate all wizard pages and secondary views."""
        # Wizard pages
        self._connect_page = ConnectPage()
        self._eq_type_page = EQTypePage()
        self._source_page = SourcePage()
        self._filters_page = FiltersPage()
        self._review_page = ReviewPage()
        self._name_profile_page = NameProfilePage()
        self._push_page = PushPage()

        # Secondary views
        self._presets_device_view = PresetsDeviceView()
        self._my_presets_view = MyPresetsView()
        self._settings_view = SettingsView()
        self._help_view = HelpView()

    def _register_pages(self) -> None:
        """Add all pages/views to the QStackedWidget in PAGE_INDICES order."""
        # Order MUST match PAGE_INDICES values (0-10)
        pages: list[QWidget] = [
            self._connect_page,       # 0: connect
            self._eq_type_page,       # 1: eq_type
            self._source_page,        # 2: source
            self._filters_page,       # 3: filters
            self._review_page,        # 4: review
            self._name_profile_page,  # 5: name_profile
            self._push_page,          # 6: push
            self._presets_device_view,  # 7: presets_device
            self._my_presets_view,     # 8: my_presets
            self._settings_view,      # 9: settings
            self._help_view,          # 10: help
        ]
        for page in pages:
            self._stacked_widget.addWidget(page)

    def _setup_dock_widget(self) -> None:
        """Create the diagnostics dock widget (hidden by default)."""
        self._diagnostics_dock = QDockWidget("Diagnostics", self)
        self._diagnostics_dock.setObjectName("diagnostics_dock")

        self._diagnostics_panel = DiagnosticsPanel()
        self._diagnostics_dock.setWidget(self._diagnostics_panel)

        self.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self._diagnostics_dock
        )
        self._diagnostics_dock.setVisible(False)

    def _setup_menus(self) -> None:
        """Create the menu bar: File, View, Help."""
        menu_bar: QMenuBar = self.menuBar()

        # --- File menu ---
        file_menu = menu_bar.addMenu("&File")

        import_action = QAction("&Import...", self)
        import_action.setShortcut("Ctrl+O")
        file_menu.addAction(import_action)

        export_action = QAction("&Export...", self)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # --- View menu ---
        view_menu = menu_bar.addMenu("&View")

        self._diagnostics_action = QAction("&Diagnostics", self)
        self._diagnostics_action.setCheckable(True)
        self._diagnostics_action.setChecked(False)
        self._diagnostics_action.toggled.connect(self._diagnostics_dock.setVisible)
        self._diagnostics_dock.visibilityChanged.connect(
            self._diagnostics_action.setChecked
        )
        view_menu.addAction(self._diagnostics_action)

        # --- Help menu ---
        help_menu = menu_bar.addMenu("&Help")

        about_action = QAction("&About", self)
        help_menu.addAction(about_action)

        user_guide_action = QAction("&User Guide", self)
        user_guide_action.setShortcut("F1")
        user_guide_action.triggered.connect(self._on_user_guide_triggered)
        help_menu.addAction(user_guide_action)

    # ------------------------------------------------------------------
    # Signal Wiring (Req 14.1, 14.3, 14.6)
    # ------------------------------------------------------------------

    def _wire_signals(self) -> None:
        """Connect page signals, WizardController, AsyncBridge, and navigation.

        This is the central wiring hub that connects:
        1. Page signals → WizardController / AsyncBridge handlers
        2. WizardController signals → UI updates (StepIndicator, QStackedWidget)
        3. AsyncBridge signals → page updates
        4. Navigation signals (StepIndicator, SidebarNav)
        """
        # --- 1. Page → Controller / Bridge handlers ---
        self._connect_page.device_selected.connect(self._on_device_selected)
        self._connect_page.refresh_requested.connect(self._on_refresh_requested)
        self._eq_type_page.eq_type_selected.connect(self._on_eq_type_selected)
        self._source_page.source_selected.connect(self._on_source_selected)
        self._filters_page.filters_accepted.connect(self._on_filters_accepted)
        self._filters_page.file_import_requested.connect(self._on_file_import_requested)
        self._filters_page.device_pull_requested.connect(self._on_device_pull_requested)
        self._filters_page.rew_api_pull_requested.connect(self._on_rew_api_pull_requested)
        self._filters_page.roomfit_profile_selected.connect(self._on_roomfit_profile_selected)
        self._review_page.push_requested.connect(self._on_push_requested)
        self._review_page.export_rew_requested.connect(self._on_export_requested)
        self._name_profile_page.name_confirmed.connect(self._on_name_confirmed)
        self._push_page.undo_requested.connect(self._on_undo_requested)
        self._push_page.done_acknowledged.connect(self._on_done_acknowledged)

        # --- 2. WizardController → UI updates ---
        self._wizard_controller.step_changed.connect(self._on_step_changed)
        self._wizard_controller.flow_type_changed.connect(self._on_flow_type_changed)
        self._wizard_controller.wizard_reset.connect(self._on_wizard_reset)
        self._wizard_controller.step_summary_updated.connect(
            self._on_step_summary_updated
        )

        # --- 3. AsyncBridge → handlers ---
        self._bridge.discovery_complete.connect(self._on_discovery_complete)
        self._bridge.capabilities_ready.connect(self._on_capabilities_ready)
        self._bridge.peq_ready.connect(self._on_peq_ready)
        self._bridge.write_complete.connect(self._on_write_complete)
        self._bridge.operation_error.connect(self._on_operation_error)
        self._bridge.progress_update.connect(self._on_progress_update)
        self._bridge.rew_measurements_ready.connect(self._on_measurements_listed)
        self._bridge.rew_filters_ready.connect(self._on_rew_filters_ready)

        # --- 4. Navigation ---
        self._step_indicator.step_clicked.connect(self._on_step_indicator_clicked)
        self._sidebar_nav.navigation_requested.connect(self._on_navigation_requested)

        # --- 5. HelpView close button ---
        self._help_view.close_requested.connect(self._on_help_close_requested)

    # ------------------------------------------------------------------
    # Page → Controller handlers
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_device_selected(self, device_ip: str) -> None:
        """Handle device selection from ConnectPage.

        Stores the device in wizard state and triggers capability probing.
        Creates WiiMHttpClient and CapabilityProber for the selected device,
        then launches an async probe via the bridge.
        """
        if self._is_busy():
            return

        self._wizard_controller.state.selected_device = device_ip

        # Lazily create device-specific adapters (Req 14.2, 14.3)
        self._wiim_http_client = WiiMHttpClient(device_ip)
        self._capability_prober = CapabilityProber(self._wiim_http_client)

        self._bridge.run_async(
            self._bridge_wrapper("capability_probe", self._do_probe())
        )
        logger.info("Device selected: %s", device_ip)

    @Slot()
    def _on_refresh_requested(self) -> None:
        """Handle refresh/rescan request from ConnectPage."""
        if self._is_busy():
            return

        self._connect_page.set_scanning(True)
        self._bridge.run_async(
            self._bridge_wrapper("discovery", self._do_discovery())
        )
        logger.debug("Discovery refresh requested")

    @Slot(str)
    def _on_eq_type_selected(self, eq_type: str) -> None:
        """Handle EQ type selection — set flow type and advance.

        Args:
            eq_type: Either "peq" or "roomfit".
        """
        if eq_type == "peq":
            self._wizard_controller.set_flow_type(FlowType.PEQ)
            self._filters_page.set_roomfit_mode(False)
        elif eq_type == "roomfit":
            self._wizard_controller.set_flow_type(FlowType.ROOMFIT)
            self._filters_page.set_roomfit_mode(True)
            # Populate RoomFit profile dropdown from device
            self._bridge.run_async(
                self._bridge_wrapper("list_roomfit", self._do_list_roomfit_profiles())
            )

        self._wizard_controller.advance(summary=eq_type.upper())

    @Slot(str, str)
    def _on_source_selected(self, source_name: str, channel_mode: str) -> None:
        """Handle source selection — store in state and advance.

        Args:
            source_name: Selected audio source name.
            channel_mode: Channel mode ("Stereo", "Left", "Right").
        """
        state = self._wizard_controller.state
        state.selected_source = source_name
        state.channel_mode = channel_mode
        self._wizard_controller.advance(summary=source_name)

    @Slot()
    def _on_filters_accepted(self) -> None:
        """Handle user accepting filters (with or without warnings) — advance."""
        self._wizard_controller.advance(summary="Filters loaded")

    @Slot(str)
    def _on_file_import_requested(self, path: str) -> None:
        """Handle file import request from FiltersPage.

        Args:
            path: Path to the REW text file.
        """
        if self._is_busy():
            return

        self._bridge.run_async(
            self._bridge_wrapper("file_import", self._do_file_import(path))
        )
        logger.info("File import requested: %s", path)

    @Slot()
    def _on_device_pull_requested(self) -> None:
        """Handle pull-from-device request from FiltersPage."""
        if self._is_busy():
            return

        # Precondition: adapter must be available (device connected)
        if self._wiim_adapter is None:
            self._status_banner.show_error("No device connected")
            return

        # Precondition: source must be selected (for PEQ flows)
        # RoomFit is device-global, so default to "wifi" if no source explicitly set
        source_name = self._wizard_controller.state.selected_source
        if not source_name:
            # Default for RoomFit or when source step was skipped
            self._wizard_controller.state.selected_source = "wifi"

        self._status_banner.show_progress("Pulling filters from device...")
        self._bridge.run_async(
            self._bridge_wrapper("device_pull", self._do_device_pull())
        )
        logger.info("Device pull requested")

    @Slot()
    def _on_rew_api_pull_requested(self) -> None:
        """Handle pull-from-REW-API request from FiltersPage."""
        if self._is_busy():
            return

        self._status_banner.show_progress("Connecting to REW...")
        self._bridge.run_async(
            self._bridge_wrapper("rew_list", self._do_rew_list_measurements())
        )
        logger.info("REW API pull requested")

    @Slot(str)
    def _on_roomfit_profile_selected(self, profile_name: str) -> None:
        """Handle RoomFit profile selection from FiltersPage dropdown.

        Reads the selected profile's filters from the device and advances
        to the Review page.

        Args:
            profile_name: Name of the RoomFit profile chosen by the user.
        """
        if self._is_busy():
            return

        if self._wiim_adapter is None:
            self._status_banner.show_error("No device connected")
            return

        self._wizard_controller.state.roomfit_profile_name = profile_name
        self._status_banner.show_progress(f"Loading RoomFit profile '{profile_name}'...")
        self._bridge.run_async(
            self._bridge_wrapper(
                "roomfit_pull", self._do_roomfit_pull(profile_name)
            )
        )
        logger.info("RoomFit profile selected: %s", profile_name)

    @Slot()
    def _on_push_requested(self) -> None:
        """Handle push request from ReviewPage — advance to Push step and execute push.

        Guards against concurrent operations, advances the wizard to the PUSH
        step, then launches the SafeWrite protocol via AsyncBridge.

        Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
        """
        if self._is_busy():
            return

        self._wizard_controller.advance(summary="Push")
        self._bridge.run_async(
            self._bridge_wrapper("push", self._do_push())
        )

    @Slot()
    def _on_export_requested(self) -> None:
        """Handle export request from ReviewPage — open file dialog and write REW file.

        For stereo mode: single file via QFileDialog.
        For L/R mode: dual-file export via ExportDialog (smoke #29).
        Ensures .txt extension is appended when missing (smoke #30).

        Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
        """
        if self._is_busy():
            return

        state = self._wizard_controller.state
        channel_mode = (state.channel_mode or "Stereo").lower()
        filters = state.current_filters

        if channel_mode in ("l/r", "lr"):
            # L/R mode: use ExportDialog for dual-file selection (smoke #29)
            from src.gui.dialogs.export_dialog import ExportDialog

            paths = ExportDialog.get_paths(channel_mode="lr", parent=self)
            if paths is None:
                logger.debug("L/R export cancelled by user")
                return

            path_l, path_r = paths
            # Split filters into L/R halves
            mid = len(filters) // 2
            filters_l = filters[:mid]
            filters_r = filters[mid:]

            self._bridge.run_async(
                self._bridge_wrapper(
                    "export_lr",
                    self._do_export_lr(filters_l, filters_r, path_l, path_r),
                )
            )
            logger.info("Export as L/R REW files requested: %s, %s", path_l, path_r)
        else:
            # Stereo mode: single file dialog
            default_dir = self._settings.rew_export_folder or str(Path.home())

            path, _ = QFileDialog.getSaveFileName(
                self,
                "Export REW EQ File",
                default_dir,
                "REW EQ Files (*.txt)",
            )

            # User cancelled the dialog
            if not path:
                logger.debug("Export cancelled by user")
                return

            # Ensure .txt extension (smoke #30)
            if not path.lower().endswith(".txt"):
                path += ".txt"

            self._bridge.run_async(
                self._bridge_wrapper("export", self._do_export(filters, path))
            )
            logger.info("Export as REW file requested: %s", path)

    @Slot(str)
    def _on_name_confirmed(self, name: str) -> None:
        """Handle RoomFit profile name confirmation — store and advance.

        Args:
            name: The profile name chosen by the user.
        """
        self._wizard_controller.state.roomfit_profile_name = name
        self._wizard_controller.advance(summary=name)

    @Slot()
    def _on_undo_requested(self) -> None:
        """Handle undo request from PushPage — restore from last backup.

        Requirement 18.1: Prominent "Undo" action available after push.
        Requirement 18.2: Restore from most recent backup.
        """
        backup_path = getattr(self._wizard_controller.state, "last_backup_path", "")
        source_name = getattr(self._wizard_controller.state, "selected_source", "")
        self._secondary_workflows.undo_last_push(source_name, backup_path)

    @Slot()
    def _on_done_acknowledged(self) -> None:
        """Handle OK click after push — return to Filters step for next action."""
        self._wizard_controller.go_to_step(WizardStep.FILTERS)

    # ------------------------------------------------------------------
    # WizardController → UI update handlers
    # ------------------------------------------------------------------

    @Slot(object)
    def _on_step_changed(self, step: object) -> None:
        """Handle step change — update StepIndicator and switch QStackedWidget page.

        Args:
            step: The new WizardStep enum value.
        """
        if not isinstance(step, WizardStep):
            return

        # Map WizardStep to PAGE_INDICES key
        step_to_page_key: dict[WizardStep, str] = {
            WizardStep.CONNECT: "connect",
            WizardStep.EQ_TYPE: "eq_type",
            WizardStep.SOURCE: "source",
            WizardStep.FILTERS: "filters",
            WizardStep.REVIEW: "review",
            WizardStep.NAME_PROFILE: "name_profile",
            WizardStep.PUSH: "push",
        }

        page_key = step_to_page_key.get(step)
        if page_key and page_key in PAGE_INDICES:
            self._stacked_widget.setCurrentIndex(PAGE_INDICES[page_key])

        # Update StepIndicator current position
        sequence = self._wizard_controller.get_steps()
        if step in sequence:
            step_index = sequence.index(step)
            self._step_indicator.set_current(step_index)

    @Slot(object)
    def _on_flow_type_changed(self, flow_type: object) -> None:
        """Handle flow type change — update StepIndicator labels.

        Args:
            flow_type: The new FlowType enum value.
        """
        if not isinstance(flow_type, FlowType):
            return

        # Rebuild step labels in the indicator
        sequence = self._wizard_controller.get_steps()
        labels = [step.value.replace("_", " ").title() for step in sequence]
        self._step_indicator.set_steps(labels)

        # Replay completed step summaries (rebuilding wiped them)
        for step, summary in self._wizard_controller.completed_steps.items():
            if step in sequence:
                index = sequence.index(step)
                self._step_indicator.set_completed(index, summary)

        # Re-apply current step highlighting
        current = self._wizard_controller.current_step
        if current in sequence:
            self._step_indicator.set_current(sequence.index(current))

    @Slot()
    def _on_wizard_reset(self) -> None:
        """Handle wizard reset — clear all pages and return to Connect."""
        self._connect_page.clear()
        self._filters_page.clear_results()
        self._push_page.reset()
        self._stacked_widget.setCurrentIndex(PAGE_INDICES["connect"])

        # Rebuild step indicator for default PEQ flow
        sequence = self._wizard_controller.get_steps()
        labels = [step.value.replace("_", " ").title() for step in sequence]
        self._step_indicator.set_steps(labels)
        self._step_indicator.set_current(0)

    @Slot(object, str)
    def _on_step_summary_updated(self, step: object, summary: str) -> None:
        """Handle step summary update — show summary on StepIndicator.

        Args:
            step: The WizardStep whose summary changed.
            summary: The summary text to display.
        """
        if not isinstance(step, WizardStep):
            return

        sequence = self._wizard_controller.get_steps()
        if step in sequence:
            index = sequence.index(step)
            self._step_indicator.set_completed(index, summary)

    # ------------------------------------------------------------------
    # AsyncBridge → Page update handlers
    # ------------------------------------------------------------------

    @Slot(list)
    def _on_discovery_complete(self, devices: list) -> None:
        """Handle discovery results — populate ConnectPage.

        Implements auto-advance: if single device found, ConnectPage
        auto-selects it (emits device_selected internally).

        Args:
            devices: List of device info dicts from discovery.
        """
        self._connect_page.set_scanning(False)
        self._connect_page.set_devices(devices)

    @Slot(object)
    def _on_capabilities_ready(self, caps: object) -> None:
        """Handle device capabilities — create adapters, determine flow, and advance.

        After storing capabilities:
        1. Creates WiiMAdapter and SafeWrite (Req 14.2, 14.3)
        2. Checks for empty source_names (Req 2.7) — error if none
        3. Determines flow type based on roomfit_level
        4. Advances the wizard

        Args:
            caps: DeviceCapabilities object from the probe.
        """
        # Store capabilities (caps has roomfit_level, source_names, etc.)
        roomfit_level = getattr(caps, "roomfit_level", 0)

        # Create WiiMAdapter and SafeWrite now that we have a connected client (Req 14.2, 14.3)
        assert self._wiim_http_client is not None
        self._wiim_adapter = WiiMAdapter(self._wiim_http_client, caps)  # type: ignore[arg-type]
        self._safe_write = SafeWrite(self._wiim_adapter, self._backup_manager)

        # Configure SecondaryWorkflowManager with adapter factories (Req 8.1, 9.3, 10.3, 15.3)
        self._secondary_workflows.configure(
            bridge=self._bridge,
            wiim_adapter_factory=lambda ip: WiiMAdapter(
                WiiMHttpClient(ip), caps,  # type: ignore[arg-type]
            ),
            safe_write_factory=lambda adapter: SafeWrite(adapter, self._backup_manager),
            backup_manager=self._backup_manager,
        )
        self._secondary_workflows.set_current_adapter(self._wiim_adapter)

        # Check for empty source_names — device reports no audio sources (Req 2.7)
        source_names = getattr(caps, "source_names", [])
        if not source_names:
            # Fallback: use model-based source mapping when device doesn't report
            # InputList (smoke #35). Only include sources that actually exist on
            # the device model. See docs/wiim_api_notes.md for model capabilities.
            model_lower = (getattr(caps, "model", "") or "").lower()
            if "mini" in model_lower:
                source_names = ["wifi", "bluetooth"]
            elif "pro" in model_lower or "ultra" in model_lower:
                source_names = ["wifi", "bluetooth", "line-in", "optical", "HDMI"]
            elif "amp" in model_lower:
                source_names = ["wifi", "bluetooth", "line-in", "optical", "HDMI"]
            else:
                # Generic fallback for unknown models
                source_names = ["wifi", "bluetooth", "line-in", "optical", "HDMI"]
            logger.warning(
                "Device reported no source_names; using model-based defaults "
                "(model=%s): %s",
                model_lower,
                source_names,
            )

        # Store capabilities for later use (smoke #35, #36)
        self._device_caps = caps

        # Determine flow type and advance wizard
        # Guard: some devices may incorrectly report roomfit_level >= 2 due to
        # firmware variations. Use model name as secondary check (smoke #36).
        model_str = (getattr(caps, "model", "") or "").lower()
        roomfit_blocked_models = ("mini",)  # Models known to not support RoomFit
        is_roomfit_blocked = any(m in model_str for m in roomfit_blocked_models)

        if roomfit_level < 2 or is_roomfit_blocked:
            # PEQ-only device — skip EQ_TYPE step (Req 1.10)
            if is_roomfit_blocked and roomfit_level >= 2:
                logger.warning(
                    "Device model '%s' reports roomfit_level=%d but RoomFit is "
                    "not supported on this model; forcing PEQ_ONLY flow (smoke #36)",
                    model_str,
                    roomfit_level,
                )
            self._wizard_controller.set_flow_type(FlowType.PEQ_ONLY)
            self._wizard_controller.advance(summary="Connected")
        else:
            # Device supports RoomFit — show EQ_TYPE choice (Req 1.9)
            self._wizard_controller.advance(summary="Connected")

        # Update sidebar with device info
        device_name = caps.model or "WiiM Device"
        # Try to get the friendly name from discovered devices list
        selected_ip = self._wizard_controller.state.selected_device
        for d in self._discovered_devices:
            if d.ip == selected_ip:
                device_name = d.name
                break
        self._sidebar_nav.set_device_info(device_name, connected=True)

        # Populate SourcePage with available sources
        active_source = getattr(caps, "active_source", "")
        self._source_page.set_sources(source_names, active_source)

    @Slot(object)
    def _on_peq_ready(self, peq_data: object) -> None:
        """Handle PEQ data ready — populate ReviewPage and advance wizard.

        After device pull or file import emits peq_ready, this handler
        populates the ReviewPage with the loaded filters and advances
        the wizard to the REVIEW step.

        For L/R channel mode, splits the combined filter list and uses
        set_lr_filters() to show separate L/R tabs (fix for smoke #28).

        Args:
            peq_data: PEQ settings object or filter list from the operation.
        """
        filters = self._wizard_controller.state.current_filters
        count = len(filters)

        if count > 0:
            # Populate ReviewPage — branch on channel mode (smoke #28)
            state = self._wizard_controller.state
            channel = state.channel_mode or "Stereo"

            # Check if peq_data carries explicit L/R bands
            peq_channel = getattr(peq_data, "channel_mode", None)
            bands_l = getattr(peq_data, "bands_l", None)
            bands_r = getattr(peq_data, "bands_r", None)

            if peq_channel == "lr" and bands_l and bands_r:
                # Use explicit L/R bands from the PEQSettings object
                self._review_page.set_lr_filters(list(bands_l), list(bands_r))
            elif channel.lower() in ("l/r", "lr"):
                # Fallback: split combined list evenly
                mid = len(filters) // 2
                self._review_page.set_lr_filters(filters[:mid], filters[mid:])
            else:
                self._review_page.set_filters(filters)

            # Set summary info
            device_ip = state.selected_device or "Unknown"
            source = state.selected_source or "wifi"

            # Try to get friendly device name
            device_name = device_ip
            for d in self._discovered_devices:
                if d.ip == device_ip:
                    device_name = d.name
                    break

            active_bands = sum(1 for f in filters if getattr(f, "enabled", True))
            self._review_page.set_summary(device_name, source, channel, active_bands)

            # Enable device comparison if we have device state
            device_filters = getattr(state, "device_filters", None)
            self._review_page.set_device_state_available(device_filters is not None)

            # Advance wizard to REVIEW step
            self._wizard_controller.advance(summary=f"{count} filters")

            # Show success in status banner (delayed so finish_operation clear passes)
            QTimer.singleShot(
                150, lambda: self._status_banner.show_success(
                    f"{count} filters loaded — ready for review"
                )
            )
        else:
            QTimer.singleShot(
                150, lambda: self._status_banner.show_info(
                    "Device has no active filters. Try importing from a REW file instead.",
                    auto_dismiss=0,
                )
            )

        logger.info("PEQ data ready: %d filters", count)

    @Slot(object)
    def _on_write_complete(self, result: object) -> None:
        """Handle write result — update PushPage with success or failure.

        Args:
            result: WriteResult object from safe write protocol.
        """
        success = getattr(result, "success", False)
        backup_path = getattr(result, "backup_path", "")

        if success:
            self._push_page.set_success(backup_path)
            self._wizard_controller.state.last_backup_path = backup_path
            self._status_banner.show_success("Filters pushed successfully")
        else:
            error_msg = getattr(result, "error", "Unknown error")
            critical = getattr(result, "critical", False)
            self._push_page.set_failure(error_msg, backup_path, critical)
            self._status_banner.show_error(f"Push failed: {error_msg}")

    @Slot(str, str)
    def _on_operation_error(self, error_type: str, message: str) -> None:
        """Handle operation error — show in StatusBanner.

        Args:
            error_type: Error category/type identifier.
            message: Human-readable error message.
        """
        self._status_banner.show_error(message)
        logger.error("Operation error [%s]: %s", error_type, message)

    @Slot(str)
    def _on_progress_update(self, message: str) -> None:
        """Handle progress update — show in StatusBanner.

        Args:
            message: Progress status message.
        """
        self._status_banner.show_progress(message)

    @Slot(list)
    def _on_measurements_listed(self, measurements: list) -> None:
        """Handle REW measurements listed — open picker dialog for user selection.

        After the bridge emits rew_measurements_ready with the measurement list,
        this handler opens MeasurementPickerDialog for the user to choose one.
        On selection, triggers _do_rew_get_filters via the bridge.

        Requirements: 5.2, 5.7.

        Args:
            measurements: List of MeasurementSummary objects from REW API.
        """
        # Open the measurement picker dialog
        measurement = MeasurementPickerDialog.get_measurement(self, measurements)

        # User cancelled the dialog
        if measurement is None:
            self._status_banner.show_info("Selection cancelled", auto_dismiss=3000)
            return

        # Fetch filters for the selected measurement
        self._bridge.run_async(
            self._bridge_wrapper("rew_filters", self._do_rew_get_filters(measurement.uuid))
        )
        logger.info("REW measurement selected: %s", measurement.name)

    @Slot(list)
    def _on_rew_filters_ready(self, filters: list) -> None:
        """Handle REW filters fetched — store in wizard state and populate FiltersPage.

        Args:
            filters: List of CanonicalFilter objects from the REW measurement.
        """
        self._wizard_controller.state.current_filters = filters
        self._bridge.peq_ready.emit(filters)

        if filters:
            self._status_banner.show_success(
                f"{len(filters)} filters loaded from REW measurement"
            )
        else:
            self._status_banner.show_info("No filters found in REW measurement")

    # ------------------------------------------------------------------
    # Error mapping & bridge wrapper (Req 12.1-12.4)
    # ------------------------------------------------------------------

    def _map_error(self, exc: Exception) -> str:
        """Map technical exceptions to user-friendly messages.

        Returns a plain-language message suitable for display in the
        StatusBanner. Never returns None and never raises.

        Args:
            exc: The caught exception from an adapter call.

        Returns:
            A user-friendly error message string.
        """
        mapping: dict[type, str] = {
            WiiMTimeoutError: "Device not responding",
            WiiMConnectionError: "Could not reach device",
            REWNotConnectedError: "REW is not connected",
            FileNotFoundError: "File not found",
            PermissionError: "Permission denied",
        }
        # Check exact type matches first (order matters: subclasses before bases)
        for exc_type, message in mapping.items():
            if isinstance(exc, exc_type):
                return message

        # Dynamic messages that include exception details
        if isinstance(exc, ParseError):
            return f"Could not read file: {exc}"
        if isinstance(exc, ValidationError):
            return f"Invalid data: {exc}"
        if isinstance(exc, OSError):
            return "File could not be written"

        # Generic fallback for unmapped exception types
        return "An unexpected error occurred"

    async def _bridge_wrapper(self, operation_name: str, coro: Coroutine[Any, Any, Any]) -> None:
        """Wrap an adapter coroutine with error mapping and signal emission.

        Catches all exceptions, logs the full traceback to the app log,
        and emits ``operation_error`` with a user-friendly message.

        Subclasses/handlers call this via:
            self._bridge.run_async(self._bridge_wrapper("discovery", self._do_discovery()))

        Args:
            operation_name: Human-readable label for logging (e.g. "discovery").
            coro: The awaitable adapter coroutine to execute.
        """
        try:
            await coro
        except Exception as exc:
            logger.exception("Operation '%s' failed", operation_name)
            self._bridge.operation_error.emit(
                type(exc).__name__,
                self._map_error(exc),
            )

    def _is_busy(self) -> bool:
        """Check if an async operation is already in progress.

        Returns True (and logs a warning) if the feedback manager indicates
        an active operation, meaning the new trigger should be ignored.
        """
        if self._feedback_manager.is_active:
            logger.warning("Operation ignored: another operation is in progress")
            return True
        return False

    # ------------------------------------------------------------------
    # Async operation coroutines (Req 1.1-1.7, 2.1-2.7)
    # ------------------------------------------------------------------

    async def _do_discovery(self) -> None:
        """Run device discovery and emit results via bridge signal.

        Calls DiscoveryModule.discover() and transforms each DeviceInfo
        into a dict with keys "name", "ip", "model" for the ConnectPage.
        """
        devices = await self._discovery_module.discover()
        # Cache raw DeviceInfo objects for device picker dialogs
        self._discovered_devices = devices
        device_list = [
            {"name": d.name, "ip": d.ip, "model": d.model}
            for d in devices
        ]
        self._bridge.discovery_complete.emit(device_list)

    async def _do_probe(self) -> None:
        """Run capability probing and emit results via bridge signal.

        Calls CapabilityProber.probe() and emits the DeviceCapabilities
        object for flow-type determination and wizard advancement.
        """
        assert self._capability_prober is not None
        caps = await self._capability_prober.probe()
        self._bridge.capabilities_ready.emit(caps)

    async def _do_file_import(self, path: str) -> None:
        """Parse a REW EQ text file and populate filters.

        Calls REWParser.parse_file_with_warnings() for full result including
        skipped bands. Stores filters in wizard state, shows warnings if any.

        Args:
            path: Path to the REW text file.
        """
        from src.translator.rew_parser import REWParser

        file_path = Path(path)
        parser = REWParser()
        filters, warnings = parser.parse_file_with_warnings(file_path)

        # Store in wizard state
        self._wizard_controller.state.current_filters = filters

        # Notify FiltersPage of success via peq_ready signal
        self._bridge.peq_ready.emit(filters)

        # If there were skipped/unsupported bands, show info message
        if warnings:
            skip_count = len(warnings)
            self._bridge.progress_update.emit(
                f"{len(filters)} filters loaded, {skip_count} unsupported band(s) skipped"
            )

    async def _do_device_pull(self) -> None:
        """Pull PEQ settings from the connected device.

        Reads PEQ bands via WiiMAdapter, converts to CanonicalFilter list,
        stores in wizard state, and emits result signal.
        """
        assert self._wiim_adapter is not None
        source_name = self._wizard_controller.state.selected_source

        peq_settings = await self._wiim_adapter.read_peq(source_name)

        # Extract filters based on channel mode
        if peq_settings.channel_mode == "lr":
            # For L/R mode, combine both channels
            filters = (peq_settings.bands_l or []) + (peq_settings.bands_r or [])
        else:
            filters = peq_settings.bands

        # Store in wizard state
        self._wizard_controller.state.current_filters = filters
        self._wizard_controller.state.device_filters = filters

        # Emit result signal
        self._bridge.peq_ready.emit(peq_settings)

    async def _do_roomfit_pull(self, profile_name: str) -> None:
        """Pull RoomFit profile filters from the device.

        Reads the named RoomFit profile via WiiMAdapter, stores filters
        in wizard state, and emits peq_ready to advance to Review.

        Args:
            profile_name: Name of the RoomFit profile to read.
        """
        assert self._wiim_adapter is not None
        source_name = self._wizard_controller.state.selected_source or "wifi"

        peq_settings = await self._wiim_adapter.read_roomfit(source_name, profile_name)

        # Extract filters based on channel mode
        if peq_settings.channel_mode == "lr":
            filters = (peq_settings.bands_l or []) + (peq_settings.bands_r or [])
        else:
            filters = peq_settings.bands

        # Store in wizard state
        self._wizard_controller.state.current_filters = filters
        self._wizard_controller.state.device_filters = filters

        # Emit result signal (triggers _on_peq_ready → Review page)
        self._bridge.peq_ready.emit(peq_settings)

    async def _do_load_peq_preset(self, preset_name: str) -> None:
        """Load a named PEQ preset from device and emit peq_ready.

        Loads the preset via EQv2SourceLoad then reads the resulting bands.

        Args:
            preset_name: Name of the PEQ preset to load.
        """
        assert self._wiim_adapter is not None
        source_name = self._wizard_controller.state.selected_source or "wifi"

        # Load the preset onto the current source
        await self._wiim_adapter.load_peq_profile(source_name, preset_name)

        # Read back the resulting PEQ state
        peq_settings = await self._wiim_adapter.read_peq(source_name)

        # Extract filters
        if peq_settings.channel_mode == "lr":
            filters = (peq_settings.bands_l or []) + (peq_settings.bands_r or [])
        else:
            filters = peq_settings.bands

        # Store in wizard state
        self._wizard_controller.state.current_filters = filters
        self._wizard_controller.state.device_filters = filters

        # Emit result signal
        self._bridge.peq_ready.emit(peq_settings)

    async def _do_copy_preset_to_device(
        self,
        preset_name: str,
        preset_type: str,
        target_ip: str,
        target_source: str,
    ) -> None:
        """Read a preset from current device and save it as a named preset on target.

        1. Reads preset filters from the currently connected device
        2. Connects to target device
        3. Saves as a named preset (same name) on the target device

        Args:
            preset_name: Name of the preset/profile to copy.
            preset_type: "PEQ" or "RoomFit".
            target_ip: IP address of the target device.
            target_source: Target source name on the remote device.
        """
        assert self._wiim_adapter is not None

        source_name = self._wizard_controller.state.selected_source or "wifi"

        # Step 1: Read filters from current device
        if preset_type == "RoomFit":
            peq_settings = await self._wiim_adapter.read_roomfit(
                source_name, preset_name
            )
            if peq_settings.channel_mode == "lr":
                filters = (peq_settings.bands_l or []) + (peq_settings.bands_r or [])
            else:
                filters = peq_settings.bands
        else:
            # Load PEQ preset, then read
            await self._wiim_adapter.load_peq_profile(source_name, preset_name)
            peq_settings = await self._wiim_adapter.read_peq(source_name)
            if peq_settings.channel_mode == "lr":
                filters = (peq_settings.bands_l or []) + (peq_settings.bands_r or [])
            else:
                filters = peq_settings.bands

        if not filters:
            self._status_banner.show_error(f"Preset '{preset_name}' has no filters to copy")
            return

        # Step 2: Connect to target device and save as named preset
        target_client = WiiMHttpClient(target_ip)
        try:
            target_caps = await CapabilityProber(target_client).probe()
            target_adapter = WiiMAdapter(target_client, target_caps)

            if preset_type == "RoomFit":
                # RoomFit: write as RoomFit profile on target (smoke #34)
                await target_adapter.write_roomfit(target_source, preset_name, filters)
            else:
                # PEQ: write filters then save as named PEQ preset
                settings = PEQSettings(
                    source_name=target_source,
                    channel_mode="stereo",
                    bands=filters,
                )
                safe_write = SafeWrite(target_adapter, self._backup_manager)
                await safe_write.execute(target_source, settings)
                await target_adapter.save_peq_profile(target_source, preset_name)

            self._status_banner.show_success(
                f"Preset '{preset_name}' saved to {target_ip} on source '{target_source}'"
            )
        finally:
            await target_client.close()

    async def _do_copy_presets_batch(
        self,
        items: list,
        target_ip: str,
        target_source: str,
    ) -> None:
        """Copy multiple presets to a target device sequentially (smoke #33).

        Processes each preset in order within a single async coroutine to
        avoid concurrent run_async calls clobbering each other.

        Args:
            items: List of PresetItem objects to copy.
            target_ip: IP address of the target device.
            target_source: Target source name on the remote device.
        """
        succeeded = 0
        failed = 0

        for item in items:
            preset_name = getattr(item, "name", "")
            preset_type = getattr(item, "preset_type", "PEQ")
            if not preset_name:
                continue

            try:
                await self._do_copy_preset_to_device(
                    preset_name, preset_type, target_ip, target_source
                )
                succeeded += 1
            except Exception:
                logger.exception(
                    "Copy preset '%s' to %s failed", preset_name, target_ip
                )
                failed += 1

        # Show summary result
        total = succeeded + failed
        if failed == 0:
            self._status_banner.show_success(
                f"All {total} preset(s) copied to {target_ip}"
            )
        else:
            self._status_banner.show_error(
                f"Copied {succeeded} of {total} presets ({failed} failed)"
            )

    async def _do_preset_export(
        self, preset_name: str, preset_type: str, path: str
    ) -> None:
        """Read a preset from device and export as REW file.

        Args:
            preset_name: Name of the preset to export.
            preset_type: "PEQ" or "RoomFit".
            path: Destination file path.
        """
        assert self._wiim_adapter is not None
        source_name = self._wizard_controller.state.selected_source or "wifi"

        # Read preset filters from device
        if preset_type == "RoomFit":
            peq_settings = await self._wiim_adapter.read_roomfit(source_name, preset_name)
            if peq_settings.channel_mode == "lr":
                filters = (peq_settings.bands_l or []) + (peq_settings.bands_r or [])
            else:
                filters = peq_settings.bands
        else:
            await self._wiim_adapter.load_peq_profile(source_name, preset_name)
            peq_settings = await self._wiim_adapter.read_peq(source_name)
            if peq_settings.channel_mode == "lr":
                filters = (peq_settings.bands_l or []) + (peq_settings.bands_r or [])
            else:
                filters = peq_settings.bands

        if not filters:
            self._status_banner.show_error(f"Preset '{preset_name}' has no filters to export")
            return

        # Export via REWGenerator
        from src.translator.rew_generator import REWGenerator

        generator = REWGenerator()
        warnings = generator.generate_file(filters, Path(path))

        if warnings:
            self._bridge.progress_update.emit(
                f"Exported '{preset_name}' ({len(warnings)} band(s) skipped)"
            )
        else:
            self._bridge.progress_update.emit(
                f"Exported '{preset_name}' to {Path(path).name}"
            )

    async def _do_preset_save(self, preset_name: str, preset_type: str) -> None:
        """Read a preset from device and save to local profile repository.

        Args:
            preset_name: Name of the preset to save.
            preset_type: "PEQ" or "RoomFit".
        """
        assert self._wiim_adapter is not None
        source_name = self._wizard_controller.state.selected_source or "wifi"

        # Read preset filters from device
        if preset_type == "RoomFit":
            peq_settings = await self._wiim_adapter.read_roomfit(source_name, preset_name)
            if peq_settings.channel_mode == "lr":
                filters = (peq_settings.bands_l or []) + (peq_settings.bands_r or [])
            else:
                filters = peq_settings.bands
        else:
            await self._wiim_adapter.load_peq_profile(source_name, preset_name)
            peq_settings = await self._wiim_adapter.read_peq(source_name)
            if peq_settings.channel_mode == "lr":
                filters = (peq_settings.bands_l or []) + (peq_settings.bands_r or [])
            else:
                filters = peq_settings.bands

        if not filters:
            self._status_banner.show_error(f"Preset '{preset_name}' has no filters to save")
            return

        # Save to local profile repository as a Profile object
        from src.models.profile import Profile

        profile = Profile(
            name=preset_name,
            channel_mode="stereo",
            filters=filters,
        )
        self._profile_repository.save(profile)

        # Refresh MyPresetsView so the new preset is visible (smoke #31)
        all_profiles = self._profile_repository.list()
        self._my_presets_view.set_presets(all_profiles)

        self._status_banner.show_success(f"Saved '{preset_name}' to My Presets")

    async def _do_rew_list_measurements(self) -> None:
        """List available measurements from REW API.

        Calls REWHttpApiClient.list_measurements() and emits the result.
        If empty, emits an info message instead of the measurement list.
        """
        measurements = await self._rew_client.list_measurements()

        if not measurements:
            self._bridge.progress_update.emit("No measurements found in REW")
            return

        # Emit measurement list for the picker dialog
        self._bridge.rew_measurements_ready.emit(measurements)

    async def _do_rew_get_filters(self, uuid: str) -> None:
        """Fetch filters for a specific REW measurement.

        Calls REWHttpApiClient.get_filters(uuid), stores in wizard state,
        and emits result signal.

        Args:
            uuid: The measurement UUID selected by the user.
        """
        filters = await self._rew_client.get_filters(uuid)

        # Store in wizard state
        self._wizard_controller.state.current_filters = filters

        # Emit result signal
        self._bridge.rew_filters_ready.emit(filters)

    async def _do_push(self) -> None:
        """Execute SafeWrite protocol to push filters to device.

        Constructs PEQSettings from wizard state (source_name, channel_mode,
        current_filters), emits progress updates for each protocol stage,
        and emits write_complete on success.

        Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
        """
        assert self._safe_write is not None

        state = self._wizard_controller.state
        source_name = state.selected_source
        filters = state.current_filters
        channel_mode = state.channel_mode.lower()

        # Build PEQSettings from wizard state
        if channel_mode == "lr":
            # Split filters evenly between L and R channels
            mid = len(filters) // 2
            settings = PEQSettings(
                source_name=source_name,
                channel_mode="lr",
                bands_l=filters[:mid],
                bands_r=filters[mid:],
            )
        else:
            settings = PEQSettings(
                source_name=source_name,
                channel_mode="stereo",
                bands=filters,
            )

        # Emit progress for backup stage
        self._bridge.progress_update.emit("Backing up...")

        # Execute the five-step safe write protocol
        result = await self._safe_write.execute(source_name, settings)

        if result.success:
            self._bridge.progress_update.emit("Writing...")
            self._bridge.progress_update.emit("Verifying...")
            self._bridge.write_complete.emit(result)
        else:
            # Emit the write_complete with failure result so PushPage can show status
            self._bridge.write_complete.emit(result)

    async def _do_export(self, filters: list, path: str) -> None:
        """Generate a REW EQ text file from current filters.

        Calls REWGenerator.generate_file() and emits progress_update with
        success message. Includes skip count if any bands were skipped.

        Args:
            filters: List of CanonicalFilter objects to export.
            path: Destination file path chosen by the user.

        Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
        """
        from src.translator.rew_generator import REWGenerator

        generator = REWGenerator()
        file_path = Path(path)
        warnings = generator.generate_file(filters, file_path)

        if warnings:
            skip_count = len(warnings)
            self._bridge.progress_update.emit(
                f"File exported successfully ({skip_count} unsupported band(s) skipped)"
            )
        else:
            self._bridge.progress_update.emit("File exported successfully")

    async def _do_export_lr(
        self,
        filters_l: list,
        filters_r: list,
        path_l: Path,
        path_r: Path,
    ) -> None:
        """Generate two REW EQ text files for L/R channel mode (smoke #29).

        Uses REWGenerator.generate_file() for each channel independently.

        Args:
            filters_l: Left channel CanonicalFilter list.
            filters_r: Right channel CanonicalFilter list.
            path_l: Destination path for left channel file.
            path_r: Destination path for right channel file.
        """
        from src.translator.rew_generator import REWGenerator

        generator = REWGenerator()
        warnings_l = generator.generate_file(filters_l, path_l)
        warnings_r = generator.generate_file(filters_r, path_r)

        total_warnings = len(warnings_l) + len(warnings_r)
        if total_warnings:
            self._bridge.progress_update.emit(
                f"L/R files exported ({total_warnings} unsupported band(s) skipped)"
            )
        else:
            self._bridge.progress_update.emit(
                f"L/R files exported: {path_l.name} and {path_r.name}"
            )

    def _load_device_presets(self) -> None:
        """Fetch and display device presets in the PresetsDeviceView.

        If no device is connected, shows the empty state. Otherwise
        fetches preset list via the adapter and populates the view.
        """
        if self._wiim_adapter is None:
            self._presets_device_view.set_no_device()
            return

        # Check if profile enumeration is supported
        caps = getattr(self._wiim_adapter, "capabilities", None)
        if caps and not getattr(caps, "supports_profile_enumeration", False):
            self._presets_device_view.set_peq_unavailable()
            return

        # Fetch presets asynchronously
        self._bridge.run_async(
            self._bridge_wrapper("list_presets", self._do_list_presets())
        )

    async def _do_list_roomfit_profiles(self) -> None:
        """Fetch RoomFit profile names and populate FiltersPage dropdown."""
        assert self._wiim_adapter is not None

        source_name = self._wizard_controller.state.selected_source or "wifi"
        try:
            if self._wiim_adapter.capabilities.roomfit_level >= 1:
                profiles = await self._wiim_adapter.list_roomfit_profiles(source_name)
                profile_names = [p.get("Name", "") for p in profiles if p.get("Name")]
                self._filters_page.set_roomfit_profiles(profile_names)
            else:
                self._filters_page.set_roomfit_profiles([])
        except Exception:
            logger.warning("Failed to list RoomFit profiles for dropdown", exc_info=True)
            self._filters_page.set_roomfit_profiles([])

    async def _do_list_presets(self) -> None:
        """Fetch device PEQ preset list and RoomFit profiles, populate PresetsDeviceView."""
        assert self._wiim_adapter is not None

        source_name = self._wizard_controller.state.selected_source or "wifi"
        from src.gui.views.presets_device_view import PresetItem

        # Fetch PEQ presets
        try:
            if self._wiim_adapter.capabilities.supports_profile_enumeration:
                peq_presets = await self._wiim_adapter.list_peq_profiles(source_name)
                peq_items = [
                    PresetItem(
                        name=p.get("Name", "Unnamed"),
                        preset_type="PEQ",
                        channel_mode=p.get("channelMode", "Stereo"),
                    )
                    for p in peq_presets
                ]
                self._presets_device_view.set_peq_presets(peq_items)
            else:
                self._presets_device_view.set_peq_unavailable()
        except Exception:
            logger.warning("Failed to list PEQ presets", exc_info=True)
            self._presets_device_view.set_peq_unavailable()

        # Fetch RoomFit profiles
        try:
            if self._wiim_adapter.capabilities.roomfit_level >= 1:
                rf_profiles = await self._wiim_adapter.list_roomfit_profiles(source_name)
                rf_items = [
                    PresetItem(
                        name=p.get("Name", "Unnamed"),
                        preset_type="RoomFit",
                        channel_mode=p.get("channelMode", "Stereo"),
                    )
                    for p in rf_profiles
                ]
                self._presets_device_view.set_roomfit_profiles(rf_items)
            else:
                self._presets_device_view.set_roomfit_hidden()
        except Exception:
            logger.warning("Failed to list RoomFit profiles", exc_info=True)
            self._presets_device_view.set_roomfit_hidden()

    # ------------------------------------------------------------------
    # Navigation handlers
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_step_indicator_clicked(self, index: int) -> None:
        """Handle step indicator backward navigation click.

        Args:
            index: Zero-based index of the clicked step in the current sequence.
        """
        sequence = self._wizard_controller.get_steps()
        if 0 <= index < len(sequence):
            target_step = sequence[index]
            self._wizard_controller.go_to_step(target_step)

    @Slot()
    def _on_help_close_requested(self) -> None:
        """Handle HelpView close button — navigate back to the current wizard step."""
        self._on_step_changed(self._wizard_controller.current_step)

    @Slot(str)
    def _on_navigation_requested(self, view_key: str) -> None:
        """Handle sidebar navigation request — switch QStackedWidget page.

        When 'home' is selected, returns to the current wizard step page.
        Otherwise navigates to the corresponding secondary view.

        Args:
            view_key: Navigation target key from SidebarNav.
        """
        logger.debug("Navigation requested: %s", view_key)
        if view_key == "home":
            # Return to current wizard step
            self._on_step_changed(self._wizard_controller.current_step)
            return

        if view_key in PAGE_INDICES:
            self._stacked_widget.setCurrentIndex(PAGE_INDICES[view_key])

        # Trigger data fetch for views that need it
        if view_key == "presets_device":
            self._load_device_presets()
        elif view_key == "my_presets":
            # Refresh local presets from repository (smoke #31)
            all_profiles = self._profile_repository.list()
            self._my_presets_view.set_presets(all_profiles)

    # ------------------------------------------------------------------
    # Settings Wiring
    # ------------------------------------------------------------------

    def _apply_settings(self) -> None:
        """Apply saved settings on startup.

        1. Theme via ThemeManager
        2. Sidebar collapsed state
        3. Dry Run default on ReviewPage
        4. Onboarding overlay when first_run_complete is False
        5. Populate SettingsView with current values
        """
        # 1. Apply theme (Req 25.4)
        app = QApplication.instance()
        if app is not None:
            self._theme_manager = ThemeManager(app)  # type: ignore[arg-type]
            theme_mode = self._settings.theme.lower()
            if theme_mode not in ("light", "dark", "system"):
                theme_mode = "system"
            self._theme_manager.apply_theme(theme_mode)  # type: ignore[arg-type]

        # 2. Sidebar collapsed state
        self._sidebar_nav.set_collapsed(self._settings.sidebar_collapsed)

        # 3. Set Dry Run default from settings (Req 24.15)
        self._review_page.set_dry_run(self._settings.dry_run_default)

        # 4. Show onboarding overlay when first_run_complete is False (Req 23.1, 23.5)
        if not self._settings.first_run_complete:
            self._onboarding_overlay.setVisible(True)
            self._onboarding_overlay.raise_()

        # 5. Populate SettingsView with current settings
        self._settings_view.set_settings({
            "theme": self._settings.theme,
            "log_directory": self._settings.log_directory,
            "presets_directory": self._settings.presets_directory,
            "rew_export_folder": self._settings.rew_export_folder,
            "discovery_timeout": self._settings.discovery_timeout,
            "dry_run_default": self._settings.dry_run_default,
            "last_device": self._settings.last_device,
        })

    def _connect_settings_signals(self) -> None:
        """Connect SettingsView signals to persistence logic."""
        # Theme change: apply immediately + persist
        self._settings_view.theme_changed.connect(self._on_theme_changed)

        # General settings change: update fields + persist
        self._settings_view.settings_changed.connect(self._on_settings_changed)

        # Show onboarding again from Settings support section
        self._settings_view.show_onboarding_requested.connect(
            self._on_show_onboarding_requested
        )

    def _connect_onboarding_signals(self) -> None:
        """Connect OnboardingOverlay signals to settings persistence."""
        self._onboarding_overlay.get_started_clicked.connect(
            self._on_onboarding_get_started
        )
        self._onboarding_overlay.skip_clicked.connect(self._on_onboarding_skip)

    @Slot(str)
    def _on_theme_changed(self, theme: str) -> None:
        """Apply theme change and persist to settings.

        Args:
            theme: Theme name from SettingsView ("Light", "Dark", "System").
        """
        theme_mode = theme.lower()
        if theme_mode not in ("light", "dark", "system"):
            theme_mode = "system"
        if hasattr(self, "_theme_manager"):
            self._theme_manager.apply_theme(theme_mode)  # type: ignore[arg-type]
        self._settings.theme = theme
        self._settings.save()

    @Slot(dict)
    def _on_settings_changed(self, settings_dict: dict) -> None:
        """Update AppSettings fields from SettingsView and persist.

        Args:
            settings_dict: Dict of current settings values from the view.
        """
        self._settings.log_directory = settings_dict.get(
            "log_directory", self._settings.log_directory
        )
        self._settings.presets_directory = settings_dict.get(
            "presets_directory", self._settings.presets_directory
        )
        self._settings.rew_export_folder = settings_dict.get(
            "rew_export_folder", self._settings.rew_export_folder
        )
        self._settings.discovery_timeout = settings_dict.get(
            "discovery_timeout", self._settings.discovery_timeout
        )
        self._settings.dry_run_default = settings_dict.get(
            "dry_run_default", self._settings.dry_run_default
        )
        self._settings.save()

    @Slot()
    def _on_show_onboarding_requested(self) -> None:
        """Show the onboarding overlay again (from Settings > Support)."""
        self._onboarding_overlay.setVisible(True)
        self._onboarding_overlay.raise_()

    @Slot()
    def _on_onboarding_get_started(self) -> None:
        """Handle onboarding Get Started: mark complete, save, navigate to connect."""
        self._settings.first_run_complete = True
        self._settings.save()
        # Navigate to connect page (first wizard step)
        self._stacked_widget.setCurrentIndex(PAGE_INDICES["connect"])

    @Slot()
    def _on_onboarding_skip(self) -> None:
        """Handle onboarding Skip: mark complete and save settings."""
        self._settings.first_run_complete = True
        self._settings.save()

    @Slot()
    def _on_user_guide_triggered(self) -> None:
        """Switch stacked widget to help view (Help > User Guide)."""
        self._stacked_widget.setCurrentIndex(PAGE_INDICES["help"])

    # ------------------------------------------------------------------
    # Operation Feedback Wiring (Req 13.1-13.6)
    # ------------------------------------------------------------------

    def _wire_operation_feedback(self) -> None:
        """Connect AsyncBridge operation signals to feedback manager.

        Ensures that:
        - Buttons are disabled immediately on operation start
        - Loading state is shown within 100ms
        - Long-operation message after 3s
        - Cancel button after 2s
        - Buttons re-enabled on finish
        """
        self._bridge.operation_started.connect(self._on_bridge_operation_started)
        self._bridge.operation_finished.connect(self._on_bridge_operation_finished)

    @Slot()
    def _on_bridge_operation_started(self) -> None:
        """Handle bridge operation_started — activate feedback manager."""
        self._feedback_manager.start_operation("Processing...")

    @Slot()
    def _on_bridge_operation_finished(self) -> None:
        """Handle bridge operation_finished — deactivate feedback manager."""
        self._feedback_manager.finish_operation()

    # ------------------------------------------------------------------
    # Keyboard Shortcuts and Accessibility (Req 26.1-26.7)
    # ------------------------------------------------------------------

    def _setup_keyboard_shortcuts(self) -> None:
        """Configure keyboard shortcuts for common actions.

        Shortcuts:
        - Ctrl+R: Refresh devices (trigger discovery)
        - Ctrl+Enter: Confirm/push on ReviewPage
        - Escape: Dismiss help panel if visible
        - Ctrl+O is already handled by the File > Import menu action.
        """
        # Ctrl+R — Refresh devices (Req 26.5)
        shortcut_refresh = QShortcut(QKeySequence("Ctrl+R"), self)
        shortcut_refresh.activated.connect(self._on_shortcut_refresh)

        # Ctrl+Enter — Confirm/push (Req 26.5)
        shortcut_confirm = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut_confirm.activated.connect(self._on_shortcut_confirm)

        # Escape — Dismiss help panel or cancel operation
        shortcut_escape = QShortcut(QKeySequence("Escape"), self)
        shortcut_escape.activated.connect(self._on_shortcut_escape)

    def _setup_accessibility(self) -> None:
        """Set accessible names and focus policies on interactive elements.

        Ensures:
        - All major widgets have accessible names (Req 26.4)
        - Logical focus policy for keyboard navigation (Req 26.1, 26.2)
        - Tab order follows visual reading order (Req 26.3)
        """
        # Accessible names on major components
        self._sidebar_nav.setAccessibleName("Navigation sidebar")
        self._step_indicator.setAccessibleName("Wizard progress indicator")
        self._stacked_widget.setAccessibleName("Main content area")
        self._status_banner.setAccessibleName("Status messages")

        # Accessible names on pages
        self._connect_page.setAccessibleName("Connect to device")
        self._eq_type_page.setAccessibleName("Select EQ type")
        self._source_page.setAccessibleName("Select audio source")
        self._filters_page.setAccessibleName("Load filters")
        self._review_page.setAccessibleName("Review filters")
        self._name_profile_page.setAccessibleName("Name profile")
        self._push_page.setAccessibleName("Push to device")

        # Accessible names on views
        self._presets_device_view.setAccessibleName("Presets on device")
        self._my_presets_view.setAccessibleName("My saved presets")
        self._settings_view.setAccessibleName("Application settings")
        self._help_view.setAccessibleName("Help and user guide")

        # Focus policies — StrongFocus on key interactive elements (Req 26.1)
        self._sidebar_nav.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._step_indicator.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Set logical tab order following visual reading order (Req 26.3)
        # Sidebar → StepIndicator → Content (stacked widget) → StatusBanner
        self.setTabOrder(self._sidebar_nav, self._step_indicator)
        self.setTabOrder(self._step_indicator, self._stacked_widget)
        self.setTabOrder(self._stacked_widget, self._status_banner)

    @Slot()
    def _on_shortcut_refresh(self) -> None:
        """Handle Ctrl+R — trigger device refresh/discovery."""
        # Only trigger if on the connect page or as a general refresh
        self._connect_page.set_scanning(True)
        logger.debug("Keyboard shortcut: Ctrl+R — Refresh devices")

    @Slot()
    def _on_shortcut_confirm(self) -> None:
        """Handle Ctrl+Enter — trigger push/confirm on ReviewPage."""
        current_index = self._stacked_widget.currentIndex()
        if current_index == PAGE_INDICES["review"]:
            self._review_page.push_requested.emit()
            logger.debug("Keyboard shortcut: Ctrl+Enter — Push confirmed")

    @Slot()
    def _on_shortcut_escape(self) -> None:
        """Handle Escape — dismiss help panel if visible, cancel active operation."""
        current_index = self._stacked_widget.currentIndex()
        if current_index == PAGE_INDICES["help"]:
            # Return to current wizard step (dismiss help view)
            self._on_step_changed(self._wizard_controller.current_step)
            logger.debug("Keyboard shortcut: Escape — Help panel dismissed")
        elif self._feedback_manager.is_active:
            # Cancel active operation
            self._feedback_manager.cancel_requested.emit()
            logger.debug("Keyboard shortcut: Escape — Operation cancelled")

    # ------------------------------------------------------------------
    # Secondary Workflows (Req 17, 18, 20, 21)
    # ------------------------------------------------------------------

    def _setup_secondary_workflows(self) -> None:
        """Create the SecondaryWorkflowManager and wire all secondary workflow signals.

        Connects:
        - ReviewPage "Copy to another source" → copy_to_sources flow
        - ReviewPage "Apply to multiple devices" → apply_to_devices flow
        - PresetsDeviceView "Copy to Another Device" → copy_preset_to_device flow
        - MyPresetsView "Load" → profile recall → populate ReviewPage
        - PushPage "Undo" → undo_last_push flow
        - SecondaryWorkflowManager completion signals → UI updates
        """
        self._secondary_workflows = SecondaryWorkflowManager(parent=self)

        # --- Inbound: page/view actions → workflow manager ---
        self._review_page.copy_to_source_requested.connect(
            self._on_copy_to_source_requested
        )
        self._review_page.multi_device_requested.connect(
            self._on_multi_device_requested
        )
        self._presets_device_view.copy_to_device_requested.connect(
            self._on_copy_to_device_requested
        )
        self._presets_device_view.export_requested.connect(
            self._on_preset_export_requested
        )
        self._presets_device_view.save_to_my_presets.connect(
            self._on_preset_save_requested
        )
        self._presets_device_view.load_into_editor.connect(
            self._on_preset_load_into_editor
        )
        self._my_presets_view.load_requested.connect(
            self._on_profile_load_requested
        )

        # --- Outbound: workflow manager signals → UI updates ---
        self._secondary_workflows.copy_to_sources_progress.connect(
            self._on_copy_to_sources_progress
        )
        self._secondary_workflows.copy_to_sources_complete.connect(
            self._on_copy_to_sources_complete
        )
        self._secondary_workflows.multi_device_progress.connect(
            self._on_multi_device_progress
        )
        self._secondary_workflows.multi_device_complete.connect(
            self._on_multi_device_complete
        )
        self._secondary_workflows.copy_to_device_complete.connect(
            self._on_copy_to_device_complete
        )
        self._secondary_workflows.profile_recalled.connect(
            self._on_profile_recalled
        )
        self._secondary_workflows.undo_complete.connect(
            self._on_undo_complete
        )

    # --- Inbound handlers (page/view → workflow trigger) ---

    @Slot()
    def _on_copy_to_source_requested(self) -> None:
        """Handle ReviewPage "Copy to another source" button click.

        Opens a source picker (multi-select) showing all device sources
        except the currently selected one, then triggers copy_to_sources.

        Requirement 9.1: Offer "Copy to another source" action.
        Requirement 9.2: Display other available sources as selectable targets.
        """
        state = self._wizard_controller.state
        current_source = state.selected_source
        filters = state.current_filters

        if not filters:
            self._status_banner.show_error("No filters loaded to copy")
            return

        # Get available sources from device capabilities
        if self._wiim_adapter is None:
            self._status_banner.show_error("No device connected")
            return

        available_sources = self._wiim_adapter.capabilities.source_names
        if not available_sources:
            self._status_banner.show_error("No sources available on device")
            return

        # Open source picker dialog (excludes current source)
        target_sources = SourcePickerDialog.get_sources(
            self, available_sources, current_source
        )

        # User cancelled the dialog
        if target_sources is None:
            return

        logger.info(
            "Copy-to-source: copying %d filters to %s",
            len(filters),
            target_sources,
        )
        self._secondary_workflows.copy_to_sources(filters, target_sources)

    @Slot()
    def _on_multi_device_requested(self) -> None:
        """Handle ReviewPage "Apply to multiple devices" button click.

        Opens a device picker (multi-select) showing discovered devices
        (excluding the current one), then triggers apply_to_devices with
        each selected device mapped to all its available sources.

        Requirement 10.1: Offer option only when >1 device discovered.
        Requirement 10.2: Display all discovered devices as checkboxes.
        """
        state = self._wizard_controller.state
        filters = state.current_filters

        if not filters:
            self._status_banner.show_error("No filters loaded to push")
            return

        # Get current device IP to exclude from picker
        current_ip = state.selected_device or ""

        # Need discovered devices for the picker
        if not self._discovered_devices:
            self._status_banner.show_error("No other devices discovered")
            return

        # Open device picker dialog (excludes current device)
        selected_devices = DevicePickerDialog.get_devices(
            self, self._discovered_devices, current_ip
        )

        # User cancelled the dialog
        if selected_devices is None:
            return

        # Build MultiDeviceRequest: each selected device → current source as default
        current_source = state.selected_source
        device_source_map: dict[str, list[str]] = {}
        device_names: dict[str, str] = {}

        for device in selected_devices:
            # Use current source as the target source for each device
            device_source_map[device.ip] = [current_source] if current_source else []
            device_names[device.ip] = device.name

        request = MultiDeviceRequest(
            device_source_map=device_source_map,
            device_names=device_names,
        )

        logger.info(
            "Multi-device push: %d devices selected, %d filters",
            len(selected_devices),
            len(filters),
        )
        self._secondary_workflows.apply_to_devices(filters, request)

    @Slot(list)
    def _on_copy_to_device_requested(self, items: list) -> None:
        """Handle PresetsDeviceView "Copy to Another Device" action.

        Opens a device picker for the target device selection, then
        executes copy_preset_to_device for each selected item.

        Requirement 15.1: User selects target device from discovered list.
        Requirement 15.2: Copy preset filters to the selected target device.

        Args:
            items: List of PresetItem objects selected for copying.
        """
        if not items:
            return

        # Get current device IP to exclude from picker
        state = self._wizard_controller.state
        current_ip = state.selected_device or ""

        # Need discovered devices for the picker
        if not self._discovered_devices:
            self._status_banner.show_error("No other devices discovered")
            return

        # Open device picker dialog for single target device selection
        selected_devices = DevicePickerDialog.get_devices(
            self, self._discovered_devices, current_ip
        )

        # User cancelled the dialog
        if selected_devices is None:
            return

        # Use the first selected device as the target
        target_device = selected_devices[0]
        target_ip = target_device.ip
        # Use current source as default for PEQ target
        target_source = state.selected_source

        logger.info(
            "Copy-to-device: %d items to %s (%s)",
            len(items),
            target_device.name,
            target_ip,
        )

        # Process all items in a single async operation to avoid clobbering (smoke #33)
        self._bridge.run_async(
            self._bridge_wrapper(
                "copy_presets_to_device",
                self._do_copy_presets_batch(items, target_ip, target_source or "wifi"),
            )
        )

    @Slot(object)
    def _on_profile_load_requested(self, profile: object) -> None:
        """Handle MyPresetsView "Load" action — recall profile into ReviewPage.

        Loads the profile's filters and navigates to the Review step.
        If no device is connected, the flow adapts to require connection first.

        Requirement 17.2: Profile Recall & Push flow.

        Args:
            profile: Profile object from the local preset library.
        """
        logger.info("Profile load requested: %s", getattr(profile, "name", "unknown"))
        self._secondary_workflows.recall_profile(profile)

    @Slot(list)
    def _on_preset_export_requested(self, items: list) -> None:
        """Handle PresetsDeviceView "Export as REW File" for selected presets.

        Reads each preset's filters from device, then exports as REW text file.

        Args:
            items: List of PresetItem objects selected for export.
        """
        if not items:
            return

        # Open save dialog
        default_dir = self._settings.rew_export_folder or str(Path.home())
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Preset as REW File",
            str(Path(default_dir) / f"{items[0].name}.txt"),
            "REW EQ Files (*.txt)",
        )
        if not path:
            logger.debug("Export preset cancelled by user")
            return

        # Read first item's filters from device, then export
        item = items[0]
        preset_name = getattr(item, "name", "")
        preset_type = getattr(item, "preset_type", "PEQ")
        self._status_banner.show_progress(f"Exporting '{preset_name}'...")
        self._bridge.run_async(
            self._bridge_wrapper(
                "preset_export",
                self._do_preset_export(preset_name, preset_type, path),
            )
        )
        logger.info("Preset export requested: %s -> %s", preset_name, path)

    @Slot(list)
    def _on_preset_save_requested(self, items: list) -> None:
        """Handle PresetsDeviceView "Save to My Presets" for selected items.

        Reads filters from device for each selected item and saves to local
        profile repository.

        Args:
            items: List of PresetItem objects selected for saving.
        """
        if not items:
            return

        item = items[0]
        preset_name = getattr(item, "name", "")
        preset_type = getattr(item, "preset_type", "PEQ")
        self._status_banner.show_progress(f"Saving '{preset_name}' to My Presets...")
        self._bridge.run_async(
            self._bridge_wrapper(
                "preset_save",
                self._do_preset_save(preset_name, preset_type),
            )
        )
        logger.info("Preset save requested: %s", [i.name for i in items])

    @Slot(object)
    def _on_preset_load_into_editor(self, item: object) -> None:
        """Handle PresetsDeviceView "Load into Editor" for a single preset.

        Reads the preset's filters from the device and loads them into
        the wizard Review page.

        Args:
            item: PresetItem object to load.
        """
        name = getattr(item, "name", "")
        preset_type = getattr(item, "preset_type", "PEQ")

        if not name:
            return

        if self._wiim_adapter is None:
            self._status_banner.show_error("No device connected")
            return

        self._status_banner.show_progress(f"Loading preset '{name}'...")
        if preset_type == "RoomFit":
            self._bridge.run_async(
                self._bridge_wrapper("load_preset", self._do_roomfit_pull(name))
            )
        else:
            # PEQ preset: load it via EQv2SourceLoad then read
            self._bridge.run_async(
                self._bridge_wrapper("load_preset", self._do_load_peq_preset(name))
            )
        logger.info("Preset load into editor: %s (type=%s)", name, preset_type)

    # --- Outbound handlers (workflow manager → UI updates) ---

    @Slot(str)
    def _on_copy_to_sources_progress(self, message: str) -> None:
        """Show copy-to-sources progress in the StatusBanner.

        Args:
            message: Progress message (e.g. "Writing to optical...").
        """
        self._status_banner.show_progress(message)

    @Slot(list)
    def _on_copy_to_sources_complete(self, results: list) -> None:
        """Handle copy-to-sources completion — show summary in StatusBanner.

        Requirement 20.5: Per-source progress and results displayed.

        Args:
            results: List of SourceCopyResult objects.
        """
        succeeded = sum(1 for r in results if isinstance(r, SourceCopyResult) and r.success)
        failed = len(results) - succeeded

        if failed == 0:
            summary_parts = [
                r.source_name for r in results
                if isinstance(r, SourceCopyResult) and r.success
            ]
            self._status_banner.show_success(
                f"Copied to {len(summary_parts)} source(s): "
                + ", ".join(summary_parts)
            )
        else:
            self._status_banner.show_error(
                f"Copy complete: {succeeded} succeeded, {failed} failed"
            )

    @Slot(str)
    def _on_multi_device_progress(self, message: str) -> None:
        """Show multi-device push progress in the StatusBanner.

        Args:
            message: Progress message (e.g. "Pushing to WiiM Pro / wifi...").
        """
        self._status_banner.show_progress(message)

    @Slot(list)
    def _on_multi_device_complete(self, results: list) -> None:
        """Handle multi-device push completion — show summary.

        Requirement 21.6: Summary after all devices processed.

        Args:
            results: List of DevicePushResult objects.
        """
        succeeded = sum(
            1 for r in results if isinstance(r, DevicePushResult) and r.success
        )
        total = len(results)
        failed = total - succeeded

        if failed == 0:
            self._status_banner.show_success(
                f"All {total} device/source pairs updated successfully"
            )
        else:
            self._status_banner.show_error(
                f"{succeeded} of {total} devices updated successfully. "
                f"{failed} failed (see details)"
            )

    @Slot(bool, str)
    def _on_copy_to_device_complete(self, success: bool, message: str) -> None:
        """Handle copy-to-device completion.

        Args:
            success: Whether the copy succeeded.
            message: Human-readable result message.
        """
        if success:
            self._status_banner.show_success(message)
        else:
            self._status_banner.show_error(message)

    @Slot(list)
    def _on_profile_recalled(self, filters: list) -> None:
        """Handle profile recall — populate ReviewPage and navigate.

        Loads the recalled filters into the wizard state and ReviewPage,
        then navigates to the Review step.

        Requirement 17.2: Profile Recall loads into Review step.

        Args:
            filters: List of CanonicalFilter objects from the recalled profile.
        """
        if not filters:
            self._status_banner.show_error("Profile contains no filters")
            return

        # Store filters in wizard state
        state = self._wizard_controller.state
        state.current_filters = filters

        # Populate ReviewPage with the recalled filters
        self._review_page.set_filters(filters)

        # Update summary (use current connection info if available)
        device = state.selected_device or "No device"
        source = state.selected_source or "Not selected"
        channel = state.channel_mode or "Stereo"
        active_bands = sum(1 for f in filters if getattr(f, "enabled", True))
        self._review_page.set_summary(device, source, channel, active_bands)

        # Navigate to Review step
        self._stacked_widget.setCurrentIndex(PAGE_INDICES["review"])
        self._status_banner.show_success(
            f"Profile loaded: {active_bands} bands ready for review"
        )

    @Slot(bool, str)
    def _on_undo_complete(self, success: bool, message: str) -> None:
        """Handle undo completion — show result in StatusBanner.

        Requirement 18.4: Display "Previous filters restored" on success.

        Args:
            success: Whether the undo succeeded.
            message: Human-readable result message.
        """
        if success:
            self._status_banner.show_success(message)
        else:
            self._status_banner.show_error(f"Undo failed: {message}")

    # ------------------------------------------------------------------
    # Close Event
    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close: check unsaved changes and shutdown bridge.

        If the wizard has modified filter state, prompt the user before
        closing. Always shuts down the AsyncBridge on close.
        """
        # Check for unsaved changes (skip if _skip_unsaved_prompt is set, e.g. in tests)
        if not getattr(self, "_skip_unsaved_prompt", False) and self._has_unsaved_changes():
            choice: Literal["save", "discard", "cancel"] = (
                UnsavedChangesDialog.confirm_discard(self)
            )
            if choice == "cancel":
                event.ignore()
                return
            # "save" or "discard" - proceed with close
            # (save logic would be handled by task 11.2 wiring)

        # Save sidebar collapse state
        self._settings.sidebar_collapsed = self._sidebar_nav.collapsed
        self._settings.save()

        # Shutdown the async bridge
        self._bridge.shutdown()

        logger.info("Application closed.")
        event.accept()

    def _has_unsaved_changes(self) -> bool:
        """Check if there are unsaved filter changes in the wizard.

        Returns:
            True if the wizard controller has filters that haven't been
            pushed/saved, False otherwise.
        """
        # The wizard state has filters loaded but not yet pushed/saved
        state = self._wizard_controller.state
        return len(state.current_filters) > 0

