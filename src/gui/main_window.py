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
from typing import Literal

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QHBoxLayout,
    QMainWindow,
    QMenuBar,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.gui.app_settings import AppSettings
from src.gui.async_bridge import AsyncBridge
from src.gui.components.sidebar_nav import SidebarNav
from src.gui.components.status_banner import StatusBanner
from src.gui.components.step_indicator import StepIndicator
from src.gui.constants import MAX_CONTENT_WIDTH, MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH
from src.gui.dialogs.crash_dialog import CrashDialog
from src.gui.dialogs.onboarding_overlay import OnboardingOverlay
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
    SecondaryWorkflowManager,
    SourceCopyResult,
)
from src.gui.theme import ThemeManager
from src.gui.views.help_view import HelpView
from src.gui.views.my_presets_view import MyPresetsView
from src.gui.views.presets_device_view import PresetsDeviceView
from src.gui.views.settings_view import SettingsView
from src.gui.wizard_controller import FlowType, WizardController, WizardStep
from src.utils.app_dirs import get_log_dir

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
        self._stacked_widget.setMaximumWidth(MAX_CONTENT_WIDTH)
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

        # --- 4. Navigation ---
        self._step_indicator.step_clicked.connect(self._on_step_indicator_clicked)
        self._sidebar_nav.navigation_requested.connect(self._on_navigation_requested)

    # ------------------------------------------------------------------
    # Page → Controller handlers
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_device_selected(self, device_ip: str) -> None:
        """Handle device selection from ConnectPage.

        Stores the device in wizard state and triggers capability probing.
        """
        self._wizard_controller.state.selected_device = device_ip
        # TODO: Trigger capability probe via bridge
        # self._bridge.run_async(probe_device_capabilities(device_ip))
        logger.info("Device selected: %s", device_ip)

    @Slot()
    def _on_refresh_requested(self) -> None:
        """Handle refresh/rescan request from ConnectPage."""
        self._connect_page.set_scanning(True)
        # TODO: Trigger discovery via bridge
        # self._bridge.run_async(discover_devices())
        logger.debug("Discovery refresh requested")

    @Slot(str)
    def _on_eq_type_selected(self, eq_type: str) -> None:
        """Handle EQ type selection — set flow type and advance.

        Args:
            eq_type: Either "peq" or "roomfit".
        """
        if eq_type == "peq":
            self._wizard_controller.set_flow_type(FlowType.PEQ)
        elif eq_type == "roomfit":
            self._wizard_controller.set_flow_type(FlowType.ROOMFIT)

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
        # TODO: Trigger file parsing via bridge or local translator
        logger.info("File import requested: %s", path)

    @Slot()
    def _on_device_pull_requested(self) -> None:
        """Handle pull-from-device request from FiltersPage."""
        # TODO: Trigger PEQ pull via bridge
        logger.info("Device pull requested")

    @Slot()
    def _on_rew_api_pull_requested(self) -> None:
        """Handle pull-from-REW-API request from FiltersPage."""
        # TODO: Trigger REW API pull via bridge
        logger.info("REW API pull requested")

    @Slot()
    def _on_push_requested(self) -> None:
        """Handle push request from ReviewPage — advance to Push step."""
        self._wizard_controller.advance(summary="Push")

    @Slot()
    def _on_export_requested(self) -> None:
        """Handle export request from ReviewPage."""
        # TODO: Trigger file export dialog and write
        logger.info("Export as REW file requested")

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
        self._secondary_workflows.undo_last_push(backup_path)

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
        """Handle device capabilities — determine flow and advance.

        Implements auto-advance logic:
        - PEQ-only device (roomfit_level < 2): skip EQ_TYPE step
        - RoomFit-capable: advance to EQ_TYPE

        Args:
            caps: DeviceCapabilities object from the probe.
        """
        # Store capabilities (caps has roomfit_level, source_names, etc.)
        roomfit_level = getattr(caps, "roomfit_level", 0)

        if roomfit_level < 2:
            # PEQ-only device — skip EQ_TYPE step (Req 1.10)
            self._wizard_controller.set_flow_type(FlowType.PEQ_ONLY)
            self._wizard_controller.advance(summary="Connected")
        else:
            # Device supports RoomFit — show EQ_TYPE choice (Req 1.9)
            self._wizard_controller.advance(summary="Connected")

        # Update sidebar with device info
        device_name = getattr(caps, "device_name", "WiiM Device")
        self._sidebar_nav.set_device_info(device_name, connected=True)

        # Populate SourcePage with available sources if present
        source_names = getattr(caps, "source_names", [])
        active_source = getattr(caps, "active_source", "")
        if source_names:
            self._source_page.set_sources(source_names, active_source)

    @Slot(object)
    def _on_peq_ready(self, peq_data: object) -> None:
        """Handle PEQ data ready — populate FiltersPage or advance.

        Args:
            peq_data: PEQ settings object containing filter data.
        """
        # TODO: Extract filters from peq_data and populate filters page
        # self._filters_page.show_warnings(warnings) if applicable
        logger.info("PEQ data ready")

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

    @Slot(str)
    def _on_navigation_requested(self, view_key: str) -> None:
        """Handle sidebar navigation request — switch QStackedWidget page.

        When 'home' is selected, returns to the current wizard step page.
        Otherwise navigates to the corresponding secondary view.

        Args:
            view_key: Navigation target key from SidebarNav.
        """
        if view_key == "home":
            # Return to current wizard step
            self._on_step_changed(self._wizard_controller.current_step)
            return

        if view_key in PAGE_INDICES:
            self._stacked_widget.setCurrentIndex(PAGE_INDICES[view_key])

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

        Requirement 20.1: Offer "Copy to another source" action.
        Requirement 20.2: Display other available sources as selectable targets.
        """
        # TODO: Open a source picker dialog (multi-select) showing available sources
        # For now, log and emit placeholder via workflow manager
        state = self._wizard_controller.state
        current_source = state.selected_source
        filters = state.current_filters

        if not filters:
            self._status_banner.show_error("No filters loaded to copy")
            return

        logger.info(
            "Copy-to-source requested (current source: '%s', %d filters)",
            current_source,
            len(filters),
        )

        # TODO: Show source picker dialog, collect target_sources from user
        # target_sources = SourcePickerDialog.get_sources(
        #     parent=self,
        #     available_sources=state.available_sources,
        #     exclude=[current_source],
        # )
        # if target_sources:
        #     self._secondary_workflows.copy_to_sources(filters, target_sources)
        self._status_banner.show_info(
            "Copy to another source: source picker not yet implemented"
        )

    @Slot()
    def _on_multi_device_requested(self) -> None:
        """Handle ReviewPage "Apply to multiple devices" button click.

        Opens a device picker (multi-select, pre-checking current device),
        then for each device opens a source picker, then triggers
        apply_to_devices with sequential push.

        Requirement 21.1: Offer option only when >1 device discovered.
        Requirement 21.2: Display all discovered devices as checkboxes.
        Requirement 21.3: User specifies target source per device.
        """
        state = self._wizard_controller.state
        filters = state.current_filters

        if not filters:
            self._status_banner.show_error("No filters loaded to push")
            return

        logger.info(
            "Multi-device push requested (%d filters)",
            len(filters),
        )

        # TODO: Show device picker dialog (multi-select)
        # Then for each selected device, show source picker
        # request = MultiDeviceRequest(
        #     device_source_map={...},
        #     device_names={...},
        # )
        # self._secondary_workflows.apply_to_devices(filters, request)
        self._status_banner.show_info(
            "Apply to multiple devices: device picker not yet implemented"
        )

    @Slot(list)
    def _on_copy_to_device_requested(self, items: list) -> None:
        """Handle PresetsDeviceView "Copy to Another Device" action.

        Opens a device picker for the target device, then a source picker
        (for PEQ), then executes copy_preset_to_device per item.

        Requirement 17.3: Copy Preset to Another Device guided flow.

        Args:
            items: List of PresetItem objects selected for copying.
        """
        if not items:
            return

        logger.info(
            "Copy-to-device requested: %d items selected",
            len(items),
        )

        # TODO: Show device picker dialog for target device selection
        # target_device_ip = DevicePickerDialog.get_device(parent=self, ...)
        # target_source = SourcePickerDialog.get_source(parent=self, ...)
        # For each item:
        #   preset_filters = fetch/extract filters from item
        #   self._secondary_workflows.copy_preset_to_device(
        #       preset_filters, target_device_ip, target_source
        #   )
        self._status_banner.show_info(
            "Copy to another device: device picker not yet implemented"
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
        # Check for unsaved changes
        if self._has_unsaved_changes():
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

