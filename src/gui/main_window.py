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
from types import TracebackType
from typing import Any, Literal

from PySide6.QtCore import QSize, Qt, QTimer, Slot
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
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
from src.adapters.rew_http_client import MeasurementSummary, REWHttpApiClient
from src.adapters.safe_write import SafeWrite, WriteResult
from src.adapters.wiim_adapter import WiiMAdapter
from src.adapters.wiim_http import WiiMHttpClient
from src.discovery.discovery_module import DiscoveryModule
from src.gui.app_settings import AppSettings
from src.gui.async_bridge import AsyncBridge
from src.gui.components.page_layout import ICON_NO_CONNECTION, ICON_NO_DATA
from src.gui.components.sidebar_nav import SidebarNav
from src.gui.components.status_banner import StatusBanner
from src.gui.components.step_indicator import StepIndicator
from src.gui.constants import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH
from src.gui.dialogs.crash_dialog import CrashDialog
from src.gui.dialogs.device_picker import DevicePickerDialog
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
    SecondaryWorkflowManager,
)
from src.gui.shared_helpers import (
    build_peq_settings,
    build_profile,
    extract_filters,
    get_lr_filters,
    is_lr_mode,
)
from src.gui.theme import ThemeManager
from src.gui.views.help_view import HelpView
from src.gui.views.my_presets_view import MyPresetsView
from src.gui.views.presets_device_view import PresetsDeviceView
from src.gui.views.rew_pull_view import RewPullView
from src.gui.views.settings_view import SettingsView
from src.gui.wizard_controller import FlowType, WizardController, WizardStep
from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceInfo
from src.models.channel_mode import ChannelMode
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
    "rew_api": 10,
}

# Maps WizardStep -> PAGE_INDICES key, used to switch the QStackedWidget
# to the page for a given wizard step.
_STEP_TO_PAGE_KEY: dict[WizardStep, str] = {
    WizardStep.CONNECT: "connect",
    WizardStep.EQ_TYPE: "eq_type",
    WizardStep.SOURCE: "source",
    WizardStep.FILTERS: "filters",
    WizardStep.REVIEW: "review",
    WizardStep.NAME_PROFILE: "name_profile",
    WizardStep.PUSH: "push",
}

# Reverse lookups used by _sync_navigation_chrome (see its docstring for why
# this single, signal-driven hook replaced a dozen hand-maintained
# sidebar_nav.set_active_key()/step_indicator.set_dimmed()/set_current()
# call sites scattered across every navigation handler in this class).
_PAGE_INDEX_TO_KEY: dict[int, str] = {v: k for k, v in PAGE_INDICES.items()}
_PAGE_KEY_TO_STEP: dict[str, WizardStep] = {v: k for k, v in _STEP_TO_PAGE_KEY.items()}

# Sidebar destinations that replace the wizard page on screen (as opposed to
# "home", which returns to wherever the wizard currently is, and "help",
# which opens a separate window and never touches the stacked widget).
_SIDEBAR_DESTINATION_KEYS: frozenset[str] = frozenset(
    {"presets_device", "my_presets", "settings", "rew_api"}
)


def _crash_handler(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    """Global exception handler installed via sys.excepthook.

    Logs the unhandled exception to app.log (with flush for persistence)
    and shows the CrashDialog (Req 24.6).
    """
    # Format traceback for logging
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
    tb_text = "".join(tb_lines)
    logger.critical("Unhandled exception:\n%s", tb_text)

    # Flush all handlers to ensure the crash is persisted to disk
    for handler in logger.handlers:
        handler.flush()

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
        # Bumped on every device selection; lets a stale/superseded capability
        # probe (e.g. user selects a second device before the first probe
        # resolves) detect that it's no longer current and avoid corrupting
        # wizard state (double-advance, wrong "Connected" step).
        self._probe_generation = 0

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

        # --- Wire wizard/page/bridge signals ---
        self._wire_signals()

        # --- Apply initial settings state (AFTER signals are wired) ---
        self._apply_settings()

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

        # --- Warm up secondary pages' layouts (see _warm_up_stacked_pages) ---
        QTimer.singleShot(0, self._warm_up_stacked_pages)

    def _warm_up_stacked_pages(self) -> None:
        """Force every QStackedWidget page to its real size and re-layout.

        QStackedLayout only resizes its *current* widget — every other
        page keeps whatever stale geometry/layout cache it had at
        construction time (before the window had a real on-screen
        size/DPI) until the user first navigates to it. That first visit
        can land with lists and button rows visibly squished, self-curing
        only once a later window resize forces a real relayout (a plain
        maximize/restore "fixes" it). Resizing every page to the stack's
        actual content size and re-activating its layout right after the
        window is shown gives each page a correct layout pass up front,
        without touching visibility (so this can't double-fire
        ConnectPage's showEvent-driven discovery or any other show/hide
        side effect).
        """
        target_size = self._stacked_widget.size()
        for i in range(self._stacked_widget.count()):
            page = self._stacked_widget.widget(i)
            if page is not None:
                self._resize_and_relayout_page(page, target_size)

    @staticmethod
    def _resize_and_relayout_page(page: QWidget, size: QSize) -> None:
        """Resize `page` and force a full re-layout of its widget tree.

        Shared by _warm_up_stacked_pages (every page, once at startup) and
        _resync_current_page_geometry (one page, every time it becomes
        current) — both exist to work around the same QStackedLayout
        behavior (it only resizes its *current* widget on a window
        resize), just at different moments.
        """
        page.resize(size)
        layout = page.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()

    @Slot(int)
    def _resync_current_page_geometry(self, index: int) -> None:
        """Force the newly-current stacked page to a correct, fresh layout.

        _warm_up_stacked_pages only runs once, right after the window is
        first shown. But QStackedLayout keeps resizing only the *current*
        widget on every subsequent window resize too — so a page that sits
        non-current through one or more resizes (e.g. the user visits it
        once while empty, navigates away, the window settles into its
        final size, then the user revisits it after it has real content)
        drifts stale again despite the one-time warm-up. Re-running the
        same resize + layout re-activate every time a page becomes current
        keeps every page's geometry honest, not just at startup.
        """
        page = self._stacked_widget.widget(index)
        if page is not None:
            self._resize_and_relayout_page(page, self._stacked_widget.size())

    @Slot(int)
    def _sync_navigation_chrome(self, index: int) -> None:
        """Keep the sidebar highlight and step-indicator pill in lockstep
        with whichever page is actually on screen.

        Every navigation path in this app — sidebar clicks, the wizard's
        own advance()/go_to_step(), step-pill clicks, "Back" from a
        secondary view, and the various "jump straight to Review"
        shortcuts (#144, #147) — ends with
        QStackedWidget.setCurrentIndex(). Before this hook existed, every
        one of those handlers had to remember to separately call
        sidebar_nav.set_active_key(), step_indicator.set_dimmed(), and
        step_indicator.set_current() in the right combination, and several
        of them didn't (hence #138, #142, #144, #147, and the step-pill
        case reported after those: clicking a finished step pill while
        viewing a sidebar destination left both highlighted at once).
        Deriving the correct chrome purely from the page index that just
        became current, in one place wired to currentChanged, means a new
        navigation path can't reintroduce this bug class just by
        forgetting one of those calls — there's nothing left to forget.
        """
        page_key = _PAGE_INDEX_TO_KEY.get(index)
        if page_key is None:
            return

        if page_key in _SIDEBAR_DESTINATION_KEYS:
            self._sidebar_nav.set_active_key(page_key)
            self._step_indicator.set_dimmed(True)
            return

        step = _PAGE_KEY_TO_STEP.get(page_key)
        if step is None:
            return

        self._sidebar_nav.set_active_key("home")
        self._step_indicator.set_dimmed(False)
        sequence = self._wizard_controller.get_steps()
        if step in sequence:
            self._step_indicator.set_current(sequence.index(step))

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
        self._stacked_widget.currentChanged.connect(self._resync_current_page_geometry)
        self._stacked_widget.currentChanged.connect(self._sync_navigation_chrome)

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
        self._rew_pull_view = RewPullView()

        # Tracks which RewPullView instance (sidebar vs. embedded in
        # FiltersPage) is currently driving an in-flight REW pull, so
        # listing results/errors get routed back to the right one.
        self._active_rew_pull_view: RewPullView | None = None
        self._active_rew_pull_page_index: int = PAGE_INDICES["rew_api"]

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
            self._rew_pull_view,      # 10: rew_api
        ]
        for page in pages:
            self._stacked_widget.addWidget(page)

    def _setup_dock_widget(self) -> None:
        """Create standalone windows for Help and Diagnostics.

        These open as separate OS-level windows with native title bar controls
        (minimize, maximize, close) per smoke #112.
        """
        # --- Diagnostics window ---
        self._diagnostics_dialog = QDialog(self)
        self._diagnostics_dialog.setWindowTitle("Diagnostics")
        self._diagnostics_dialog.setObjectName("DiagnosticsDialog")
        self._diagnostics_dialog.resize(700, 500)
        diag_layout = QVBoxLayout(self._diagnostics_dialog)
        diag_layout.setContentsMargins(0, 0, 0, 0)
        self._diagnostics_panel = DiagnosticsPanel()
        diag_layout.addWidget(self._diagnostics_panel)

        # Keep a hidden dock for backward compat with view menu action wiring
        self._diagnostics_dock = QDockWidget("Diagnostics", self)
        self._diagnostics_dock.setObjectName("diagnostics_dock")
        self._diagnostics_dock.setVisible(False)
        self._diagnostics_dock.setAllowedAreas(Qt.DockWidgetArea.NoDockWidgetArea)
        self.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self._diagnostics_dock
        )

        # --- Help window ---
        self._help_dialog = QDialog(self)
        self._help_dialog.setWindowTitle("User Guide")
        self._help_dialog.setObjectName("HelpDialog")
        self._help_dialog.resize(750, 600)
        help_layout = QVBoxLayout(self._help_dialog)
        help_layout.setContentsMargins(0, 0, 0, 0)
        help_layout.addWidget(self._help_view)
        # Ensure HelpView is visible (it may have been hidden by QStackedWidget)
        self._help_view.setVisible(True)

    def _setup_menus(self) -> None:
        """Create the menu bar: File, View, Help."""
        menu_bar: QMenuBar = self.menuBar()

        # --- File menu ---
        file_menu = menu_bar.addMenu("&File")

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # --- View menu ---
        view_menu = menu_bar.addMenu("&View")

        self._diagnostics_action = QAction("&Diagnostics", self)
        self._diagnostics_action.setCheckable(False)
        self._diagnostics_action.triggered.connect(self._show_diagnostics_window)
        view_menu.addAction(self._diagnostics_action)

        # --- Help menu ---
        help_menu = menu_bar.addMenu("&Help")

        about_action = QAction("&About", self)
        about_action.triggered.connect(self._on_about_triggered)
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
        self._filters_page.file_import_lr_requested.connect(self._on_file_import_lr_requested)
        self._filters_page.device_pull_requested.connect(self._on_device_pull_requested)
        self._filters_page.rew_api_pull_requested.connect(self._on_rew_api_pull_requested)
        self._filters_page.roomfit_profile_selected.connect(self._on_roomfit_profile_selected)
        self._review_page.push_requested.connect(self._on_push_requested)
        self._review_page.export_rew_requested.connect(self._on_export_requested)
        self._review_page.save_preset_requested.connect(self._on_review_save_preset)
        self._review_page.dry_run_toggled.connect(self._on_dry_run_toggled)
        self._name_profile_page.name_confirmed.connect(self._on_name_confirmed)
        self._push_page.undo_requested.connect(self._on_undo_requested)
        self._push_page.done_acknowledged.connect(self._on_done_acknowledged)
        self._push_page.export_requested.connect(self._on_export_requested)
        self._push_page.save_preset_requested.connect(self._on_review_save_preset)

        # --- 2. WizardController → UI updates ---
        self._wizard_controller.step_changed.connect(self._on_step_changed)
        self._wizard_controller.flow_type_changed.connect(self._on_flow_type_changed)
        self._wizard_controller.wizard_reset.connect(self._on_wizard_reset)
        self._wizard_controller.step_summary_updated.connect(
            self._on_step_summary_updated
        )

        # --- 3. AsyncBridge → handlers ---
        self._bridge.discovery_complete.connect(self._on_discovery_complete)
        self._bridge.discovery_progress.connect(self._on_discovery_progress)
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

        # --- 6. Diagnostics panel ---
        self._diagnostics_panel.raw_command_requested.connect(
            self._on_raw_command_requested
        )

    # ------------------------------------------------------------------
    # Page → Controller handlers
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_device_selected(self, device_ip: str) -> None:
        """Handle device selection from ConnectPage.

        Stores the device in wizard state and triggers capability probing.
        Creates WiiMHttpClient and CapabilityProber for the selected device,
        then launches an async probe via the bridge.

        Resets flow type and clears source/step state so previous context
        doesn't leak (smoke #87 — re-connect should re-ask source).
        """
        if self._is_busy():
            return

        # Reset flow type and clear prior step state
        self._wizard_controller.set_flow_type(FlowType.PEQ)
        state = self._wizard_controller.state
        state.selected_device = device_ip
        state.selected_source = ""
        state.current_filters = []
        # Clear completed steps beyond CONNECT
        state.completed_steps.pop(WizardStep.EQ_TYPE, None)
        state.completed_steps.pop(WizardStep.SOURCE, None)
        state.completed_steps.pop(WizardStep.FILTERS, None)
        state.completed_steps.pop(WizardStep.REVIEW, None)
        state.completed_steps.pop(WizardStep.PUSH, None)

        # Lazily create device-specific adapters (Req 14.2, 14.3)
        self._wiim_http_client = WiiMHttpClient(device_ip)
        self._capability_prober = CapabilityProber(self._wiim_http_client)

        # Bump generation so a still-in-flight probe from a previous device
        # selection is discarded instead of advancing the wizard out from
        # under the user (see _do_probe).
        self._probe_generation += 1
        generation = self._probe_generation

        self._bridge.run_async(
            self._bridge_wrapper(
                "capability_probe",
                self._do_probe(self._capability_prober, generation),
            )
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
            source_name: Comma-separated audio source name(s).
            channel_mode: Channel mode ("Stereo", "Left", "Right").
        """
        state = self._wizard_controller.state
        state.selected_source = source_name
        state.channel_mode = ChannelMode.from_any(channel_mode)

        # Build summary label showing selected source(s)
        sources = [s.strip() for s in source_name.split(",") if s.strip()]
        if len(sources) == 1:
            summary = sources[0]
        else:
            summary = f"{len(sources)} sources"
        self._wizard_controller.advance(summary=summary)

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

    @Slot(str, str)
    def _on_file_import_lr_requested(self, path_l: str, path_r: str) -> None:
        """Handle L/R file import request from FiltersPage.

        Parses both files and combines them into a single filter list with
        L/R channel mode set in wizard state.

        Args:
            path_l: Path to the left channel REW text file.
            path_r: Path to the right channel REW text file.
        """
        if self._is_busy():
            return

        self._bridge.run_async(
            self._bridge_wrapper(
                "file_import_lr", self._do_file_import_lr(path_l, path_r)
            )
        )
        logger.info("L/R file import requested: L=%s, R=%s", path_l, path_r)

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
        """Handle FiltersPage's source toggle switching to "Pull from REW API".

        Populates FiltersPage's embedded RewPullView (already showing its
        "Connecting..." state — see FiltersPage._on_source_toggled) rather
        than the sidebar's standalone instance. Unlike the sidebar shortcut,
        a successful selection advances the wizard normally instead of
        jumping straight to Review (_sidebar_load_in_progress stays False).
        """
        if self._is_busy():
            return

        self._active_rew_pull_view = self._filters_page.rew_pull_view
        self._active_rew_pull_page_index = PAGE_INDICES["filters"]
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

    @Slot(bool)
    def _on_dry_run_toggled(self, enabled: bool) -> None:
        """Handle dry run toggle — update wizard state."""
        self._wizard_controller.state.dry_run = enabled

    @Slot()
    def _on_push_requested(self) -> None:
        """Handle push request from ReviewPage — advance and execute push.

        For dry run: advance to PUSH step and show preview result (no device write).
        For PEQ flow: advance to PUSH step and execute immediately.
        For RoomFit flow: advance to NAME_PROFILE step first (push happens
        after user confirms the profile name via _on_name_confirmed).

        Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
        """
        if self._is_busy():
            return

        state = self._wizard_controller.state
        flow_type = self._wizard_controller.flow_type

        # Dry run: show preview result without writing to device (smoke #80)
        if state.dry_run:
            # For RoomFit, skip NAME_PROFILE step — go directly to PUSH
            if flow_type == FlowType.ROOMFIT:
                # Advance twice: REVIEW → NAME_PROFILE → PUSH
                self._wizard_controller.advance(summary="Dry Run")
                self._wizard_controller.advance(summary="Dry Run")
            else:
                # PEQ: advance once: REVIEW → PUSH
                self._wizard_controller.advance(summary="Dry Run")
            filters = state.current_filters
            band_count = len(filters)
            sources = [s.strip() for s in (state.selected_source or "wifi").split(",") if s.strip()]
            source_info = ", ".join(sources) if sources else "wifi"
            channel = state.channel_mode.display_value
            self._push_page.set_dry_run_result(
                f"Dry run complete: {band_count} bands validated for "
                f"{source_info} ({channel}). No changes were written to device."
            )
            return

        if flow_type == FlowType.ROOMFIT:
            # RoomFit: advance to NAME_PROFILE — push deferred until name confirmed
            self._wizard_controller.advance(summary="Ready")
        else:
            # PEQ: advance to PUSH and execute immediately
            self._wizard_controller.advance(summary="Push")
            self._bridge.run_async(
                self._bridge_wrapper("push", self._do_push())
            )

    @Slot()
    def _on_export_requested(self) -> None:
        """Handle export request from ReviewPage — delegate to shared helper.

        Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
        """
        if self._is_busy():
            return

        state = self._wizard_controller.state
        channel_mode = state.channel_mode
        filters = state.current_filters

        self._export_filters_as_rew(filters, channel_mode)

    @Slot(str)
    def _on_name_confirmed(self, name: str) -> None:
        """Handle RoomFit profile name confirmation — store, advance, and push.

        Args:
            name: The profile name chosen by the user.
        """
        self._wizard_controller.state.roomfit_profile_name = name
        self._wizard_controller.advance(summary=name)
        # Now execute the actual push (deferred from _on_push_requested)
        self._bridge.run_async(
            self._bridge_wrapper("push", self._do_push())
        )

    @Slot()
    def _on_undo_requested(self) -> None:
        """Handle undo request from PushPage — restore from last backup.

        For PEQ: delegates to SecondaryWorkflowManager (SafeWrite restore).
        Supports multi-source undo when backup_path contains semicolons.
        For RoomFit: reads backup, writes bands back to the same profile name.

        Requirement 18.1: Prominent "Undo" action available after push.
        Requirement 18.2: Restore from most recent backup.
        """
        backup_path = self._wizard_controller.state.last_backup_path
        source_name_raw = self._wizard_controller.state.selected_source or "wifi"

        if self._wizard_controller.flow_type == FlowType.ROOMFIT:
            # RoomFit undo: restore backed-up bands to the same profile name
            source_name = source_name_raw.split(",")[0].strip()
            profile_name = self._wizard_controller.state.roomfit_profile_name
            self._bridge.run_async(
                self._bridge_wrapper(
                    "undo_roomfit",
                    self._do_undo_roomfit(backup_path, source_name, profile_name),
                )
            )
        else:
            # PEQ undo: handle multi-source backup paths (smoke #77)
            # Format: "source1=/path/to/backup1;source2=/path/to/backup2"
            if ";" in backup_path or "=" in backup_path:
                # Multi-source undo
                self._bridge.run_async(
                    self._bridge_wrapper(
                        "undo_multi_source",
                        self._do_undo_multi_source(backup_path),
                    )
                )
            else:
                # Single source undo (legacy format)
                source_name = source_name_raw.split(",")[0].strip()
                self._secondary_workflows.undo_last_push(source_name, backup_path)

    async def _do_undo_roomfit(
        self, backup_path: str, source_name: str, profile_name: str
    ) -> None:
        """Restore a RoomFit profile from backup.

        Reads the backup JSON via shared parse_backup_filters helper, then
        writes the filters back to the same profile name via write_roomfit.
        """
        assert self._wiim_adapter is not None
        from src.gui.shared_helpers import parse_backup_filters

        path = Path(backup_path) if backup_path else Path(".")
        if not path.exists() or not path.is_file():
            self._status_banner.show_error("No backup available for undo")
            return

        try:
            import json

            backup_data = json.loads(path.read_text(encoding="utf-8"))
            bands, _channel_mode, _filters_l, _filters_r = parse_backup_filters(backup_data)

            if not bands:
                self._status_banner.show_error("Backup contains no filters")
                return

            self._bridge.progress_update.emit(f"Restoring '{profile_name}'...")
            await self._wiim_adapter.write_roomfit(source_name, profile_name, bands)
            self._status_banner.show_success(
                f"Profile '{profile_name}' restored from backup"
            )
        except Exception as exc:
            logger.exception("RoomFit undo failed")
            self._status_banner.show_error(f"Undo failed: {exc}")

    async def _do_undo_multi_source(self, backup_paths_str: str) -> None:
        """Undo a multi-source push by restoring each source's backup.

        Args:
            backup_paths_str: Semicolon-separated "source=/path" entries.
        """
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
                self._secondary_workflows.undo_last_push(source_name, bp)
                succeeded += 1
            except Exception:
                logger.exception("Undo source '%s' failed", source_name)
                failed += 1

        if failed == 0:
            self._status_banner.show_success(
                f"All {succeeded} source(s) restored from backup"
            )
        else:
            self._status_banner.show_error(
                f"Undo: {succeeded} restored, {failed} failed"
            )

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

        Also clears completion badges for steps that are no longer in the
        wizard's completed_steps dict (back-navigation invalidation).

        Args:
            step: The new WizardStep enum value.
        """
        if not isinstance(step, WizardStep):
            return

        # Switching the stacked widget's page fires currentChanged, which
        # _sync_navigation_chrome handles centrally (undimming the step
        # pill, setting its current index, and resetting the sidebar
        # highlight to "home") — no need to duplicate any of that here.
        page_key = _STEP_TO_PAGE_KEY.get(step)
        if page_key and page_key in PAGE_INDICES:
            self._stacked_widget.setCurrentIndex(PAGE_INDICES[page_key])

        # Reset Push page when entering the PUSH step (clear stale dry run results)
        if step == WizardStep.PUSH:
            self._push_page.reset()

        # Populate NameProfilePage when entering that step (RoomFit flow)
        if step == WizardStep.NAME_PROFILE:
            self._populate_name_profile_page()

        # Clear completion badges for steps no longer in completed_steps
        # (back-navigation invalidation) — independent of chrome sync above.
        sequence = self._wizard_controller.get_steps()
        completed = self._wizard_controller.completed_steps

        if step in sequence:
            step_index = sequence.index(step)
            for i, s in enumerate(sequence):
                if s not in completed and i != step_index:
                    self._step_indicator.clear_completed(i)

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
    def _on_discovery_complete(self, devices: list[Any]) -> None:
        """Handle discovery results — populate ConnectPage.

        Implements auto-advance: if single device found, ConnectPage
        auto-selects it (emits device_selected internally).

        Args:
            devices: List of device info dicts from discovery.
        """
        self._connect_page.set_scanning(False)
        self._connect_page.set_devices(devices)

    @Slot(list)
    def _on_discovery_progress(self, devices: list[Any]) -> None:
        """Handle progressive discovery updates — add new device cards.

        Called as devices are found during parallel discovery. Updates the
        ConnectPage incrementally without waiting for discovery to complete.

        Args:
            devices: Cumulative list of all devices found so far.
        """
        self._connect_page.update_devices(devices)

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

        # Source names: WiiM API has no reliable source enumeration endpoint.
        # getStatusEx may or may not include InputList (see corrections.md 2026-06-12).
        # The PEQ engine accepts ANY source name, so showing extra sources is harmless —
        # the user just picks which input to apply EQ to.
        # Source names are model-dependent (see docs/wiim_api_notes.md):
        #   Mini: wifi, bluetooth, line-in
        #   Pro/Pro Plus/Amp/Ultra: wifi, bluetooth, line-in, optical, HDMI
        #   Sound/Sound Lite: wifi, bluetooth, auxIn (NOT line-in)
        # We show a superset; extras just sit unused in device PEQ slots.
        source_names = getattr(caps, "source_names", [])
        if not source_names:
            source_names = ["wifi", "bluetooth", "line-in", "auxIn", "optical", "HDMI"]
            logger.info(
                "Device reported no source_names; showing all known WiiM sources"
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
        device_name = getattr(caps, "model", "") or "WiiM Device"
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

        # Gate L/R channel mode by device capability (post capability-file
        # merge — see device_capability_file.py) so the option is never
        # presented as available on a device that doesn't support it.
        self._filters_page.set_lr_enabled(getattr(caps, "supports_lr_filters", False))

        # Populate diagnostics panel capabilities display
        self._diagnostics_panel.on_capabilities_ready(caps)  # type: ignore[arg-type]

    @Slot(object)
    def _on_peq_ready(self, peq_data: object) -> None:
        """Handle PEQ data ready — validate, populate ReviewPage, and advance wizard.

        After device pull or file import emits peq_ready, this handler:
        1. Validates filters against device limits (truncation + clamping)
        2. Populates the ReviewPage with the validated filters
        3. Advances the wizard to the REVIEW step

        For L/R channel mode, splits the combined filter list and uses
        set_lr_filters() to show separate L/R tabs (fix for smoke #28).

        Args:
            peq_data: PEQ settings object or filter list from the operation.
        """
        from src.gui.shared_helpers import validate_filters_for_device

        state = self._wizard_controller.state
        filters = state.current_filters
        count = len(filters)

        if count == 0:
            # No filters at all — nothing to show, so any pending skip rows
            # from this attempt are moot. Reset so they don't leak into a
            # later unrelated flow.
            state.pending_rows = []
            state.pending_rows_l = []
            state.pending_rows_r = []
            state.pending_conversion_notes = {}
            state.pending_conversion_notes_l = {}
            state.pending_conversion_notes_r = {}

        if count > 0:
            # Determine device max_filters
            max_filters = 10  # Default
            if self._device_caps is not None:
                max_filters = getattr(self._device_caps, "max_filters", 10) or 10

            # Populate ReviewPage — branch on channel mode (smoke #28)
            channel = state.channel_mode

            # Check if peq_data carries explicit L/R bands
            peq_channel = getattr(peq_data, "channel_mode", None)
            bands_l = getattr(peq_data, "bands_l", None)
            bands_r = getattr(peq_data, "bands_r", None)

            if (
                peq_channel is not None
                and is_lr_mode(peq_channel)
                and bands_l is not None
                and bands_r is not None
            ):
                # Update wizard state to reflect actual L/R mode from device
                state.channel_mode = ChannelMode.LR
                channel = ChannelMode.LR

                # Validate each channel independently
                validated_l, warnings_l, clamping_l, rows_l = validate_filters_for_device(
                    list(bands_l), max_filters, state.pending_rows_l or None
                )
                validated_r, warnings_r, clamping_r, rows_r = validate_filters_for_device(
                    list(bands_r), max_filters, state.pending_rows_r or None
                )
                notes_l = state.pending_conversion_notes_l
                notes_r = state.pending_conversion_notes_r
                state.pending_rows_l = []
                state.pending_rows_r = []
                state.pending_conversion_notes_l = {}
                state.pending_conversion_notes_r = {}

                # Merge warnings
                all_warnings = warnings_l + warnings_r

                # Update state with truncated filters and separate L/R lists
                state.current_filters = validated_l + validated_r
                state.filters_l = validated_l
                state.filters_r = validated_r

                self._review_page.set_lr_filters(
                    validated_l,
                    validated_r,
                    clamping_l,
                    clamping_r,
                    rows_l,
                    rows_r,
                    notes_l,
                    notes_r,
                )
            elif channel.is_lr:
                # Every producer of peq_ready in L/R mode (file_import_lr,
                # device_pull, roomfit_pull, rew_get_filters_lr) always
                # supplies explicit bands_l/bands_r — read_peq/read_roomfit
                # raise rather than return L/R mode without both. Reaching
                # this branch means that invariant broke; refuse to guess
                # a channel split instead of silently writing wrong-channel
                # data (same class of bug as smoke #92/#93).
                logger.error(
                    "L/R mode without explicit bands_l/bands_r — refusing "
                    "to guess channel split"
                )
                self._status_banner.show_error(
                    "Could not determine L/R channel data for this source"
                )
                state.pending_rows_l = []
                state.pending_rows_r = []
                state.pending_conversion_notes_l = {}
                state.pending_conversion_notes_r = {}
                return
            else:
                # Stereo: validate the full list
                validated, all_warnings, clamping_map, rows = validate_filters_for_device(
                    filters, max_filters, state.pending_rows or None
                )
                notes = state.pending_conversion_notes
                state.pending_rows = []
                state.pending_conversion_notes = {}
                state.current_filters = validated
                self._review_page.set_filters(validated, clamping_map, rows, notes)

            # Set summary info
            device_ip = state.selected_device or "Unknown"
            source = state.selected_source or "wifi"

            # Try to get friendly device name
            device_name = device_ip
            for d in self._discovered_devices:
                if d.ip == device_ip:
                    device_name = d.name
                    break

            validated_count = len(state.current_filters)
            active_bands = sum(
                1 for f in state.current_filters if getattr(f, "enabled", True)
            )
            self._review_page.set_summary(device_name, source, channel.display_value, active_bands)

            # Advance wizard to REVIEW step
            if getattr(self, "_sidebar_load_in_progress", False):
                # Sidebar load: navigate directly to Review (smoke #87)
                self._sidebar_load_in_progress = False
                state = self._wizard_controller.state
                state.current_step = WizardStep.REVIEW
                # Mark all prior steps as completed for step indicator
                self._mark_prior_steps_completed(state)
                # Emit step summaries for the step indicator
                for step, summary in state.completed_steps.items():
                    self._wizard_controller.step_summary_updated.emit(step, summary)
                # Switching the page fires currentChanged, which
                # _sync_navigation_chrome handles centrally (step pill
                # highlight + undim, sidebar reset to "home") — no manual
                # sync needed here.
                self._stacked_widget.setCurrentIndex(PAGE_INDICES["review"])
            else:
                self._wizard_controller.advance(summary=f"{validated_count} filters")

            # Show warnings or success in status banner
            if all_warnings:
                warning_text = " | ".join(all_warnings)
                QTimer.singleShot(
                    150, lambda: self._status_banner.show_info(
                        warning_text, auto_dismiss=0
                    )
                )
            else:
                QTimer.singleShot(
                    150, lambda: self._status_banner.show_success(
                        f"{validated_count} filters loaded — ready for review"
                    )
                )
        else:
            QTimer.singleShot(
                150, lambda: self._status_banner.show_info(
                    "Device has no active filters. Try importing from a REW file instead.",
                    auto_dismiss=0,
                )
            )

        logger.info(
            "PEQ data ready: %d raw filters, %d after validation, channel=%s",
            count,
            len(self._wizard_controller.state.current_filters),
            self._wizard_controller.state.channel_mode.value,
        )

    @Slot(object)
    def _on_write_complete(self, result: object) -> None:
        """Handle write result — update PushPage with success or failure.

        Args:
            result: WriteResult object from safe write protocol.
        """
        success = getattr(result, "success", False)
        backup_path = str(getattr(result, "backup_path", "") or "")

        if success:
            self._push_page.set_success(backup_path)
            self._wizard_controller.state.last_backup_path = backup_path
            # Mark PUSH step as completed in the step indicator
            self._wizard_controller.state.completed_steps[WizardStep.PUSH] = "Done"
            self._wizard_controller.step_summary_updated.emit(WizardStep.PUSH, "Done")
            # Hide Undo for RoomFit when writing a NEW profile (no backup to restore)
            if self._wizard_controller.flow_type == FlowType.ROOMFIT and not backup_path:
                self._push_page._undo_button.setVisible(False)
            self._status_banner.show_success("Filters pushed successfully")
        else:
            error_msg = getattr(result, "error_message", None) or "Unknown error"
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

        if self._active_rew_pull_view is not None:
            self._sidebar_load_in_progress = False
            self._show_rew_pull_message(message, icon=ICON_NO_CONNECTION)

    @Slot(str)
    def _on_progress_update(self, message: str) -> None:
        """Handle progress update — show in StatusBanner.

        Also routes raw command responses to the diagnostics panel
        (to avoid cross-thread GUI access from async worker).

        Args:
            message: Progress status message.
        """
        # Intercept raw command responses (smoke #85 — thread-safe delivery)
        if message.startswith("__raw_response__"):
            response_text = message[len("__raw_response__"):]
            self._diagnostics_panel.on_raw_response(response_text)
            return

        # Terminal informational results (e.g. "no measurements found") must not
        # render as an indeterminate, non-dismissible spinner — show_progress()
        # never auto-dismisses and has no close button, so it looks stuck.
        if message.startswith("__info__"):
            info_text = message[len("__info__"):]
            self._status_banner.show_info(info_text)
            self._show_rew_pull_message(info_text, icon=ICON_NO_DATA)
            return

        self._status_banner.show_progress(message)

    @Slot(list)
    def _on_measurements_listed(self, measurements: list[Any]) -> None:
        """Handle REW measurements listed — populate whichever RewPullView is active.

        The sidebar's "Pull from REW" entry and FiltersPage's "Pull from
        REW API" source toggle each set _active_rew_pull_view /
        _active_rew_pull_page_index before kicking off the listing request
        (see _on_rew_pull_requested / _on_rew_api_pull_requested), so this
        handler doesn't need to know which one triggered it. Navigates back
        to the relevant page if the user wandered off while REW was being
        queried. Stereo returns one MeasurementSummary, L/R returns a
        (left, right) tuple — see _dispatch_measurement_selection.

        Requirements: 5.2, 5.7.

        Args:
            measurements: List of MeasurementSummary objects from REW API.
        """
        view = self._active_rew_pull_view
        if view is None:
            return
        self._stacked_widget.setCurrentIndex(self._active_rew_pull_page_index)
        view.set_measurements(measurements)

    def _show_rew_pull_message(self, message: str, icon: str = "") -> None:
        """Show a terminal message (no-measurements/error) on the active RewPullView.

        Clears _active_rew_pull_view since no more measurements are coming
        for this attempt — matches _dispatch_measurement_selection's cancel
        handling.

        Args:
            message: Message to display in place of the picker.
            icon: Optional large icon glyph (ICON_NO_CONNECTION for REW
                being unreachable, ICON_NO_DATA for "REW is fine but has
                nothing loaded") shown above the message.
        """
        view = self._active_rew_pull_view
        if view is None:
            return
        self._stacked_widget.setCurrentIndex(self._active_rew_pull_page_index)
        view.set_message(message, icon=icon)
        self._active_rew_pull_view = None

    def _dispatch_measurement_selection(
        self,
        result: MeasurementSummary | tuple[MeasurementSummary, MeasurementSummary],
    ) -> None:
        """Fetch filters for a confirmed measurement selection.

        Args:
            result: A single MeasurementSummary (Stereo) or a (left, right)
                tuple (L/R) — RewPullView only emits measurement_selected
                once a valid selection is made; cancellation goes through
                back_requested instead (see _on_rew_pull_back_requested /
                _on_filters_rew_pull_back_requested).
        """
        # Only now check wizard-state completeness (device/EQ type/source) —
        # showing QuickSetupDialog here, after a concrete selection, rather
        # than before browsing REW's measurement list.
        if not self._ensure_wizard_state_for_load():
            return

        # The picker's job is done — any later error fetching filters shows
        # in the status banner only, same as a failed file import.
        self._active_rew_pull_view = None

        if isinstance(result, tuple):
            measurement_l, measurement_r = result
            self._bridge.run_async(
                self._bridge_wrapper(
                    "rew_filters_lr",
                    self._do_rew_get_filters_lr(measurement_l.uuid, measurement_r.uuid),
                )
            )
            logger.info(
                "REW L/R measurements selected: L=%s, R=%s",
                measurement_l.name,
                measurement_r.name,
            )
        else:
            measurement = result
            self._bridge.run_async(
                self._bridge_wrapper(
                    "rew_filters", self._do_rew_get_filters(measurement.uuid)
                )
            )
            logger.info("REW measurement selected: %s", measurement.name)

    @Slot(list)
    def _on_rew_filters_ready(self, filters: list[CanonicalFilter]) -> None:
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
            REWNotConnectedError: (
                "REW is not connected. Please ensure REW is running and "
                "its HTTP API is enabled (localhost:4735)."
            ),
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
    # Shared action helpers (used by multiple trigger points)
    # ------------------------------------------------------------------

    def _save_filters_to_presets(
        self, name: str, filters: list[CanonicalFilter], channel_mode: str | ChannelMode
    ) -> None:
        """Save filters to local profile repository (shared by all save triggers).

        Sanitizes the name for filesystem safety, constructs a Profile with
        correct channel mode, persists it, and refreshes the MyPresetsView.

        Args:
            name: Desired preset name (will be sanitized for filesystem).
            filters: Combined filter list from wizard state.
            channel_mode: Channel mode (ChannelMode enum or legacy string).
        """
        state = self._wizard_controller.state
        profile = build_profile(
            name, filters, channel_mode,
            filters_l=state.filters_l,
            filters_r=state.filters_r,
        )

        self._profile_repository.save(profile)

        # Refresh MyPresetsView
        self._refresh_presets_view()

        self._status_banner.show_success(
            f"Saved '{profile.name}' to My Presets"
        )
        logger.info("Saved preset: %s (%s)", profile.name, channel_mode)

    def _refresh_presets_view(self) -> None:
        """Refresh MyPresetsView from the profile repository."""
        all_profiles = self._profile_repository.list()
        self._my_presets_view.set_presets(all_profiles)

    def _export_filters_as_rew(
        self, filters: list[CanonicalFilter], channel_mode: str | ChannelMode
    ) -> None:
        """Show export dialog and write REW file(s) (shared by all export triggers).

        For stereo: single file dialog -> single .txt file.
        For L/R: ExportDialog with dual paths -> two .txt files (_L, _R).

        Args:
            filters: Combined filter list.
            channel_mode: Channel mode (ChannelMode enum or legacy string).
        """
        if is_lr_mode(channel_mode):
            # L/R mode: use ExportDialog for dual-file selection
            from src.gui.dialogs.export_dialog import ExportDialog

            # Build a default filename from device name + source
            state = self._wizard_controller.state
            device_name = "WiiM"
            for d in self._discovered_devices:
                if d.ip == state.selected_device:
                    device_name = d.name
                    break
            source = state.selected_source or "wifi"
            default_name = f"{device_name} - {source}"

            paths = ExportDialog.get_paths(
                channel_mode="lr", default_name=default_name, parent=self
            )
            if paths is None:
                logger.debug("L/R export cancelled by user")
                return

            assert isinstance(paths, tuple)
            path_l, path_r = paths
            # Use stored L/R lists; fallback only for defensive safety
            state = self._wizard_controller.state
            filters_l, filters_r = get_lr_filters(state, filters)

            self._bridge.run_async(
                self._bridge_wrapper(
                    "export_lr",
                    self._do_export_lr(filters_l, filters_r, path_l, path_r),
                )
            )
            logger.info("Export L/R REW: %s, %s", path_l, path_r)
        else:
            # Stereo mode: single file dialog
            default_dir = self._settings.rew_export_folder or str(Path.home())
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Export REW EQ File",
                default_dir,
                "REW EQ Files (*.txt)",
            )
            if not path:
                logger.debug("Export cancelled by user")
                return

            # Ensure .txt extension
            if not path.lower().endswith(".txt"):
                path += ".txt"

            self._bridge.run_async(
                self._bridge_wrapper("export", self._do_export(filters, path))
            )
            logger.info("Export REW: %s", path)

    # ------------------------------------------------------------------
    # Async operation coroutines (Req 1.1-1.7, 2.1-2.7)
    # ------------------------------------------------------------------

    async def _do_discovery(self) -> None:
        """Run device discovery and emit results via bridge signal.

        Uses progressive discovery — devices appear in the UI as soon as
        they're found rather than waiting for the full scan to complete.
        """

        def _on_found(devices: list[DeviceInfo]) -> None:
            """Progressive callback — emit partial results to the UI."""
            device_list = [
                {"name": d.name, "ip": d.ip, "model": d.model}
                for d in devices
            ]
            self._bridge.discovery_progress.emit(device_list)

        devices = await self._discovery_module.discover(on_found=_on_found)
        # Cache raw DeviceInfo objects for device picker dialogs
        self._discovered_devices = devices
        device_list = [
            {"name": d.name, "ip": d.ip, "model": d.model}
            for d in devices
        ]
        self._bridge.discovery_complete.emit(device_list)

    async def _do_probe(self, prober: CapabilityProber, generation: int) -> None:
        """Run capability probing and emit results via bridge signal.

        Calls CapabilityProber.probe() and emits the DeviceCapabilities
        object for flow-type determination and wizard advancement.

        The *prober* instance and *generation* are passed in explicitly
        (rather than read from ``self``) so a probe started for a previously
        selected device can't pick up a different device's prober if the
        user reselects before this one resolves. If *generation* no longer
        matches the most recent selection, the result is discarded —
        otherwise a stale probe could advance the wizard for a device the
        user already navigated away from, corrupting the Connect step's
        completed/checkmark state.

        Args:
            prober: The CapabilityProber for the device this probe targets.
            generation: Snapshot of ``self._probe_generation`` at selection time.
        """
        caps = await prober.probe()
        if generation != self._probe_generation:
            logger.debug(
                "Discarding stale capability probe result (generation %d, current %d)",
                generation,
                self._probe_generation,
            )
            return
        self._bridge.capabilities_ready.emit(caps)

    async def _do_file_import(self, path: str) -> None:
        """Parse a REW EQ text file and populate filters.

        Calls REWParser.parse_file_with_rows() for full result including
        skipped bands. Stores filters in wizard state, shows warnings if any.

        Args:
            path: Path to the REW text file.
        """
        from src.translator.rew_parser import REWParser

        file_path = Path(path)
        parser = REWParser()
        filters, warnings, rows, notes = parser.parse_file_with_rows(file_path)

        # Store in wizard state — explicitly set Stereo channel mode (smoke #72)
        self._wizard_controller.state.current_filters = filters
        self._wizard_controller.state.channel_mode = ChannelMode.STEREO
        self._wizard_controller.state.pending_rows = rows
        self._wizard_controller.state.pending_conversion_notes = notes

        # Notify FiltersPage of success via peq_ready signal
        self._bridge.peq_ready.emit(filters)

        # If there were skipped/unsupported bands, show info message
        if warnings:
            skip_count = len(warnings)
            self._bridge.progress_update.emit(
                f"{len(filters)} filters loaded, {skip_count} unsupported band(s) skipped"
            )

    async def _do_file_import_lr(self, path_l: str, path_r: str) -> None:
        """Parse two REW EQ text files as L/R channels.

        Parses each file independently, combines into a flat filter list (L+R),
        and sets channel_mode to "L/R" in wizard state.

        Args:
            path_l: Path to the left channel REW text file.
            path_r: Path to the right channel REW text file.
        """
        from src.translator.rew_parser import REWParser

        parser = REWParser()
        filters_l, warnings_l, rows_l, notes_l = parser.parse_file_with_rows(Path(path_l))
        filters_r, warnings_r, rows_r, notes_r = parser.parse_file_with_rows(Path(path_r))

        # Combine L+R into flat list and set L/R channel mode
        filters = filters_l + filters_r
        self._wizard_controller.state.current_filters = filters
        self._wizard_controller.state.channel_mode = ChannelMode.LR
        self._wizard_controller.state.pending_rows_l = rows_l
        self._wizard_controller.state.pending_rows_r = rows_r
        self._wizard_controller.state.pending_conversion_notes_l = notes_l
        self._wizard_controller.state.pending_conversion_notes_r = notes_r

        # Emit peq_ready with a pseudo-PEQSettings-like object carrying L/R bands
        peq_data = PEQSettings(
            source_name=self._wizard_controller.state.selected_source or "wifi",
            channel_mode=ChannelMode.LR,
            bands_l=filters_l,
            bands_r=filters_r,
        )
        self._bridge.peq_ready.emit(peq_data)

        total_warnings = len(warnings_l) + len(warnings_r)
        if total_warnings:
            self._bridge.progress_update.emit(
                f"L/R import: Left {len(filters_l)} bands ({len(warnings_l)} skipped), "
                f"Right {len(filters_r)} bands ({len(warnings_r)} skipped)"
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
        filters, _ = extract_filters(peq_settings)

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

        peq_settings = await self._wiim_adapter.read_roomfit(
            source_name, profile_name
        )

        # Extract filters based on channel mode
        filters, _ = extract_filters(peq_settings)

        # Store in wizard state
        self._wizard_controller.state.current_filters = filters
        self._wizard_controller.state.device_filters = filters

        # Emit result signal (triggers _on_peq_ready -> Review page)
        self._bridge.peq_ready.emit(peq_settings)

    async def _do_load_peq_preset(self, preset_name: str) -> None:
        """Load a named PEQ preset from device and emit peq_ready.

        Loads the preset via EQv2SourceLoad then reads the resulting bands.
        Sets channel_mode in wizard state from the device response to avoid
        stale L/R state from a previous load (smoke #111).

        Args:
            preset_name: Name of the PEQ preset to load.
        """
        assert self._wiim_adapter is not None
        source_name = self._wizard_controller.state.selected_source or "wifi"

        # Load the preset onto the current source
        await self._wiim_adapter.load_peq_profile(source_name, preset_name)

        # Read back the resulting PEQ state
        peq_settings = await self._wiim_adapter.read_peq(source_name)

        # Determine channel_mode from the device data and update wizard state
        peq_channel = getattr(peq_settings, "channel_mode", None)
        if is_lr_mode(peq_channel) if peq_channel else False:
            self._wizard_controller.state.channel_mode = ChannelMode.LR
        else:
            self._wizard_controller.state.channel_mode = ChannelMode.STEREO

        # Extract filters
        filters, _ = extract_filters(peq_settings)

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
            filters, channel_mode = extract_filters(peq_settings)
        else:
            # Load PEQ preset, then read
            await self._wiim_adapter.load_peq_profile(source_name, preset_name)
            peq_settings = await self._wiim_adapter.read_peq(source_name)
            filters, channel_mode = extract_filters(peq_settings)

        if not filters:
            self._status_banner.show_error(
                f"Preset '{preset_name}' has no filters to copy"
            )
            return

        # Step 2: Connect to target device and save as named preset
        target_client = WiiMHttpClient(target_ip)
        try:
            target_caps = await CapabilityProber(target_client).probe()
            target_adapter = WiiMAdapter(target_client, target_caps)

            if preset_type == "RoomFit":
                # RoomFit: write as RoomFit profile on target (smoke #34, #79)
                if is_lr_mode(channel_mode):
                    # Use the L/R bands just read from the source preset —
                    # not wizard state, which may be stale or unrelated to
                    # this preset (e.g. never populated in this session).
                    await target_adapter.write_roomfit(
                        target_source, preset_name, filters,
                        channel_mode="lr",
                        filters_l=peq_settings.bands_l,
                        filters_r=peq_settings.bands_r,
                    )
                else:
                    await target_adapter.write_roomfit(
                        target_source, preset_name, filters
                    )
            else:
                # PEQ: write filters then save as named PEQ preset
                settings = build_peq_settings(
                    target_source, filters, channel_mode,
                    filters_l=peq_settings.bands_l,
                    filters_r=peq_settings.bands_r,
                )
                safe_write = SafeWrite(target_adapter, self._backup_manager)
                await safe_write.execute(target_source, settings)
                await target_adapter.save_peq_profile(
                    target_source, preset_name
                )

            self._status_banner.show_success(
                f"Preset '{preset_name}' saved to {target_ip} on source '{target_source}'"
            )
        finally:
            await target_client.close()

    async def _do_copy_presets_batch(
        self,
        items: list[Any],
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

    async def _do_copy_presets_batch_multi(
        self,
        items: list[Any],
        target_devices: list[DeviceInfo],
        target_source: str,
    ) -> None:
        """Copy presets to multiple target devices (smoke #73 fix).

        Iterates over all target devices and copies all preset items to each.

        Args:
            items: List of PresetItem objects to copy.
            target_devices: List of discovered device objects to copy to.
            target_source: Target source name on each remote device.
        """
        succeeded = 0
        failed = 0
        total_ops = len(items) * len(target_devices)

        for device in target_devices:
            target_ip = device.ip
            device_name = device.name
            self._bridge.progress_update.emit(
                f"Copying to {device_name}..."
            )
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
        n_items = len(items)
        n_devices = len(target_devices)
        if failed == 0:
            self._status_banner.show_success(
                f"{n_items} preset(s) copied to {n_devices} device(s)"
            )
        else:
            self._status_banner.show_error(
                f"Copied {succeeded} of {total_ops} operations ({failed} failed)"
            )

    async def _do_preset_export(
        self, preset_name: str, preset_type: str, path: str
    ) -> None:
        """Read a preset from device and export as REW file.

        For L/R mode, generates two files (_L.txt and _R.txt) from the base path.

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
        else:
            await self._wiim_adapter.load_peq_profile(source_name, preset_name)
            peq_settings = await self._wiim_adapter.read_peq(source_name)

        from src.translator.rew_generator import REWGenerator

        generator = REWGenerator()
        file_path = Path(path)

        # Ensure .txt extension
        if file_path.suffix.lower() != ".txt":
            file_path = file_path.with_suffix(".txt")

        if is_lr_mode(peq_settings.channel_mode):
            # L/R mode: generate two files
            filters_l = peq_settings.bands_l or []
            filters_r = peq_settings.bands_r or []

            if not filters_l and not filters_r:
                self._status_banner.show_error(
                    f"Preset '{preset_name}' has no filters to export"
                )
                return

            left_path = file_path.with_stem(file_path.stem + "_L")
            right_path = file_path.with_stem(file_path.stem + "_R")
            warnings_l = generator.generate_file(filters_l, left_path)
            warnings_r = generator.generate_file(filters_r, right_path)
            total_warnings = len(warnings_l) + len(warnings_r)

            if total_warnings:
                self._bridge.progress_update.emit(
                    f"Exported '{preset_name}' L/R ({total_warnings} band(s) skipped)"
                )
            else:
                self._bridge.progress_update.emit(
                    f"Exported '{preset_name}' as {left_path.name} and {right_path.name}"
                )
        else:
            # Stereo mode: single file
            filters = peq_settings.bands
            if not filters:
                self._status_banner.show_error(
                    f"Preset '{preset_name}' has no filters to export"
                )
                return

            warnings = generator.generate_file(filters, file_path)
            if warnings:
                self._bridge.progress_update.emit(
                    f"Exported '{preset_name}' ({len(warnings)} band(s) skipped)"
                )
            else:
                self._bridge.progress_update.emit(
                    f"Exported '{preset_name}' to {file_path.name}"
                )

    async def _do_preset_save(self, preset_name: str, preset_type: str) -> None:
        """Read a preset from device and save to local profile repository.

        Uses build_profile helper for consistent Profile construction.
        Note: the helper is safe to call here because AsyncBridge signals
        are delivered via QueuedConnection (thread-safe).

        Args:
            preset_name: Name of the preset to save.
            preset_type: "PEQ" or "RoomFit".
        """
        assert self._wiim_adapter is not None
        source_name = self._wizard_controller.state.selected_source or "wifi"

        # Read preset filters from device
        if preset_type == "RoomFit":
            peq_settings = await self._wiim_adapter.read_roomfit(
                source_name, preset_name
            )
        else:
            await self._wiim_adapter.load_peq_profile(source_name, preset_name)
            peq_settings = await self._wiim_adapter.read_peq(source_name)

        # Determine channel mode and filter list
        filters, channel_mode = extract_filters(peq_settings)

        if not filters:
            self._status_banner.show_error(
                f"Preset '{preset_name}' has no filters to save"
            )
            return

        # Save directly (Profile construction + file write is thread-safe)
        # For L/R, pass explicit channel lists from peq_settings
        profile = build_profile(
            preset_name, filters, channel_mode,
            filters_l=peq_settings.bands_l,
            filters_r=peq_settings.bands_r,
        )

        self._profile_repository.save(profile)
        # UI updates via progress_update signal (thread-safe)
        self._bridge.progress_update.emit(
            f"Saved '{profile.name}' to My Presets"
        )

    async def _do_rew_list_measurements(self) -> None:
        """List available measurements from REW API.

        Calls REWHttpApiClient.list_measurements() and emits the result.
        If empty, emits an info message instead of the measurement list.
        """
        measurements = await self._rew_client.list_measurements()

        if not measurements:
            self._sidebar_load_in_progress = False
            self._bridge.progress_update.emit(
                "__info__No measurements found in REW. "
                "Load or import measurement(s) in REW's Measurements pane, then try again."
            )
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
        filters, rows, notes = await self._rew_client.get_filters_with_rows(uuid)

        # Store in wizard state
        self._wizard_controller.state.current_filters = filters
        self._wizard_controller.state.channel_mode = ChannelMode.STEREO
        self._wizard_controller.state.pending_rows = rows
        self._wizard_controller.state.pending_conversion_notes = notes

        # Emit result signal
        self._bridge.rew_filters_ready.emit(filters)

    async def _do_rew_get_filters_lr(self, uuid_l: str, uuid_r: str) -> None:
        """Fetch filters for Left and Right REW measurements.

        Calls get_filters for each UUID, combines into L+R format,
        and emits peq_ready with the combined result.

        Args:
            uuid_l: UUID of the Left channel measurement.
            uuid_r: UUID of the Right channel measurement.
        """
        from src.translator._warnings import SkippedBand

        filters_l, rows_l, notes_l = await self._rew_client.get_filters_with_rows(uuid_l)
        filters_r, rows_r, notes_r = await self._rew_client.get_filters_with_rows(uuid_r)

        # Combine L+R into flat list and set L/R channel mode
        filters = filters_l + filters_r
        self._wizard_controller.state.current_filters = filters
        self._wizard_controller.state.channel_mode = ChannelMode.LR
        self._wizard_controller.state.pending_rows_l = rows_l
        self._wizard_controller.state.pending_rows_r = rows_r
        self._wizard_controller.state.pending_conversion_notes_l = notes_l
        self._wizard_controller.state.pending_conversion_notes_r = notes_r

        # Emit peq_ready with a PEQSettings carrying L/R bands
        peq_data = PEQSettings(
            source_name=self._wizard_controller.state.selected_source or "wifi",
            channel_mode=ChannelMode.LR,
            bands_l=filters_l,
            bands_r=filters_r,
        )
        self._bridge.peq_ready.emit(peq_data)

        skipped_l = sum(1 for r in rows_l if isinstance(r, SkippedBand))
        skipped_r = sum(1 for r in rows_r if isinstance(r, SkippedBand))
        if skipped_l or skipped_r:
            self._bridge.progress_update.emit(
                f"L/R import: Left {len(filters_l)} bands ({skipped_l} skipped), "
                f"Right {len(filters_r)} bands ({skipped_r} skipped)"
            )

    async def _do_push(self) -> None:
        """Execute push to device — PEQ via SafeWrite, or RoomFit via write_roomfit.

        For PEQ flow: constructs PEQSettings and uses SafeWrite protocol.
        Pushes to ALL selected sources (comma-separated in state.selected_source).
        For RoomFit flow: uses write_roomfit with the named profile.

        Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
        """
        # Safety net: never write to device in dry-run mode
        if self._wizard_controller.state.dry_run:
            logger.warning("_do_push called in dry-run mode — aborting write")
            return

        assert self._wiim_adapter is not None

        state = self._wizard_controller.state
        source_names_raw = state.selected_source or "wifi"
        filters = state.current_filters
        channel_mode = state.channel_mode
        flow_type = self._wizard_controller.flow_type

        logger.info(
            "Push initiated: flow=%s, channel=%s, filters=%d, source=%s",
            flow_type.value, channel_mode.value, len(filters), source_names_raw,
        )

        # Parse comma-separated sources into a list
        source_list = [s.strip() for s in source_names_raw.split(",") if s.strip()]
        if not source_list:
            source_list = ["wifi"]

        self._bridge.progress_update.emit("Backing up...")

        if flow_type == FlowType.ROOMFIT:
            # RoomFit: write as named profile via write_roomfit
            # RoomFit is device-global, so source doesn't matter — use first
            source_name = source_list[0]
            profile_name = state.roomfit_profile_name
            if not profile_name:
                result = WriteResult(
                    success=False, error_message="No profile name specified", backup_path=None
                )
                self._bridge.write_complete.emit(result)
                return

            try:
                # Check if profile already exists — if so, back up its bands first
                backup_path: str | None = None
                existing_profiles = await self._wiim_adapter.list_roomfit_profiles(
                    source_name
                )
                existing_names = [p.get("Name", "") for p in existing_profiles]

                if profile_name in existing_names:
                    # Read existing profile bands for backup
                    self._bridge.progress_update.emit(
                        f"Backing up existing '{profile_name}'..."
                    )
                    # Load profile into buffer then read
                    existing_settings = await self._wiim_adapter.read_roomfit(
                        source_name, profile_name
                    )
                    # Store backup via BackupManager
                    caps = self._wiim_adapter.capabilities
                    bp = self._backup_manager.create_backup(
                        existing_settings, caps, trigger="pre_write"
                    )
                    backup_path = str(bp)

                # Write new bands to the named profile (respecting channel mode)
                self._bridge.progress_update.emit(
                    f"Writing RoomFit profile '{profile_name}'..."
                )
                if channel_mode.is_lr:
                    # Use stored L/R lists if available (avoids naive 50/50 split)
                    left, right = get_lr_filters(state, filters)
                    await self._wiim_adapter.write_roomfit(
                        source_name,
                        profile_name,
                        filters,
                        channel_mode=ChannelMode.LR,
                        filters_l=left,
                        filters_r=right,
                    )
                else:
                    await self._wiim_adapter.write_roomfit(
                        source_name, profile_name, filters
                    )

                result = WriteResult(
                    success=True,
                    backup_path=Path(backup_path) if backup_path else None,
                )
                self._bridge.progress_update.emit(
                    f"RoomFit profile '{profile_name}' saved"
                )
                self._bridge.write_complete.emit(result)
            except Exception as exc:
                result = WriteResult(success=False, error_message=str(exc), backup_path=None)
                self._bridge.write_complete.emit(result)
        else:
            # PEQ: use SafeWrite protocol — push to ALL selected sources
            assert self._safe_write is not None

            last_result = None
            backup_paths: list[str] = []
            for i, source_name in enumerate(source_list):
                if len(source_list) > 1:
                    self._bridge.progress_update.emit(
                        f"Pushing to {source_name} ({i + 1}/{len(source_list)})..."
                    )

                settings = build_peq_settings(
                    source_name, filters, channel_mode,
                    filters_l=state.filters_l,
                    filters_r=state.filters_r,
                )
                result = await self._safe_write.execute(source_name, settings)
                last_result = result

                # Collect backup path for undo (smoke #77)
                bp_path = result.backup_path
                if bp_path:
                    backup_paths.append(f"{source_name}={bp_path}")

                if not result.success:
                    # Abort on first failure
                    self._bridge.write_complete.emit(result)
                    return

            # All sources succeeded — store all backup paths as semicolon-joined
            if last_result and last_result.success:
                # Encode multi-source backup paths for undo
                # Format: "source1=/path;source2=/path" — consumed by _do_undo_multi_source
                combined_backup = ";".join(backup_paths) if backup_paths else None
                result = WriteResult(
                    success=True,
                    backup_path=combined_backup,
                )
                self._bridge.progress_update.emit("Verifying...")
                self._bridge.write_complete.emit(result)

    async def _do_export(self, filters: list[CanonicalFilter], path: str) -> None:
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
        filters_l: list[CanonicalFilter],
        filters_r: list[CanonicalFilter],
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

    def _populate_name_profile_page(self) -> None:
        """Fetch RoomFit profile names and populate NameProfilePage list.

        Called when the wizard navigates to the NAME_PROFILE step.
        """
        if self._wiim_adapter is None:
            self._name_profile_page.set_existing_profiles([])
            return

        self._bridge.run_async(
            self._bridge_wrapper(
                "list_roomfit_for_naming",
                self._do_populate_name_profiles(),
            )
        )

    async def _do_populate_name_profiles(self) -> None:
        """Fetch RoomFit profiles and populate the NameProfilePage."""
        assert self._wiim_adapter is not None
        source_name = self._wizard_controller.state.selected_source or "wifi"

        try:
            if self._wiim_adapter.capabilities.roomfit_level >= 1:
                profiles = await self._wiim_adapter.list_roomfit_profiles(source_name)
                profile_names = [p.get("Name", "") for p in profiles if p.get("Name")]
                # TODO: detect active profile name (not currently available from API)
                self._name_profile_page.set_existing_profiles(profile_names, "")
            else:
                self._name_profile_page.set_existing_profiles([])
        except Exception:
            logger.warning("Failed to list RoomFit profiles for naming", exc_info=True)
            self._name_profile_page.set_existing_profiles([])

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
        """Handle HelpView close button — close the help dialog window."""
        self._help_dialog.hide()

    @Slot()
    def _show_diagnostics_window(self) -> None:
        """Open the Diagnostics window as a separate OS window."""
        self._diagnostics_dialog.show()
        self._diagnostics_dialog.raise_()
        self._diagnostics_dialog.activateWindow()

    @Slot(str)
    def _on_raw_command_requested(self, command: str) -> None:
        """Handle raw command from Diagnostics panel — send to device and show response."""
        if self._wiim_adapter is None:
            self._diagnostics_panel.on_raw_response("Error: No device connected")
            return

        self._bridge.run_async(
            self._bridge_wrapper("raw_command", self._do_raw_command(command))
        )

    async def _do_raw_command(self, command: str) -> None:
        """Execute a raw httpapi command against the connected device.

        Args:
            command: The command string (e.g. "getStatusEx").
        """
        assert self._wiim_adapter is not None

        try:
            client = self._wiim_adapter._client
            response = await client.command(command)
            # Format the response as JSON if possible
            import json
            if isinstance(response, dict):
                formatted = json.dumps(response, indent=2, ensure_ascii=False)
            else:
                formatted = str(response)
            # Emit via signal to avoid cross-thread GUI access (smoke #85 segfault fix)
            self._bridge.progress_update.emit(f"__raw_response__{formatted}")
        except Exception as exc:
            self._bridge.progress_update.emit(f"__raw_response__Error: {exc}")

    @Slot(str)
    def _on_navigation_requested(self, view_key: str) -> None:
        """Handle sidebar navigation request — switch QStackedWidget page.

        When 'home' is selected, returns to the current wizard step page.
        When 'connect' is selected, navigates directly to the Connect step.
        Otherwise navigates to the corresponding secondary view.

        Args:
            view_key: Navigation target key from SidebarNav.
        """
        logger.debug("Navigation requested: %s", view_key)
        # Sidebar highlight + step-pill dimming are synced centrally by
        # _sync_navigation_chrome (wired to currentChanged) — this handler
        # only needs to decide which page to switch to.
        if view_key == "home":
            # Return to current wizard step's page. Unlike _on_step_changed
            # (the real step-transition handler), this must not re-run entry
            # side effects such as resetting the Push page's dry-run/result
            # state or repopulating Name Profile — the user is just coming
            # back from a secondary view (e.g. Settings), not re-entering
            # the step.
            step = self._wizard_controller.current_step
            page_key = _STEP_TO_PAGE_KEY.get(step)
            if page_key and page_key in PAGE_INDICES:
                self._stacked_widget.setCurrentIndex(PAGE_INDICES[page_key])
            return

        if view_key == "connect":
            # Navigate to Connect step via wizard controller (same as step indicator click)
            self._wizard_controller.go_to_step(WizardStep.CONNECT)
            return

        if view_key == "rew_api":
            # REW API pull — trigger measurement listing workflow
            self._on_rew_pull_requested()
            return

        if view_key == "help":
            # Open Help as a separate window (smoke #112). Doesn't replace
            # the current page, so the step indicator isn't dimmed.
            self._on_user_guide_triggered()
            return

        if view_key in PAGE_INDICES:
            self._stacked_widget.setCurrentIndex(PAGE_INDICES[view_key])

        # Trigger data fetch for views that need it
        if view_key == "presets_device":
            self._load_device_presets()
        elif view_key == "my_presets":
            # Refresh local presets from repository (smoke #31)
            self._refresh_presets_view()

    def _on_rew_pull_requested(self) -> None:
        """Handle sidebar 'Pull from REW' click — start the listing workflow.

        Navigates to the embedded RewPullView, then connects to REW and
        lists measurements; the Stereo/L-R choice is made on that page once
        the list arrives (see _on_measurements_listed). Wizard-state
        completeness (device/EQ type/source) is only checked once the user
        has actually picked a measurement — see _dispatch_measurement_selection
        — so browsing REW's measurement list never triggers QuickSetupDialog
        up front, matching Presets on Device / My Saved Presets.
        """
        if self._is_busy():
            return

        self._stacked_widget.setCurrentIndex(PAGE_INDICES["rew_api"])
        self._rew_pull_view.set_connecting()
        self._active_rew_pull_view = self._rew_pull_view
        self._active_rew_pull_page_index = PAGE_INDICES["rew_api"]

        # Set flag so _on_peq_ready navigates directly to Review
        self._sidebar_load_in_progress = True
        self._status_banner.show_progress("Connecting to REW...")
        self._bridge.run_async(
            self._bridge_wrapper("rew_list", self._do_rew_list_measurements())
        )

    @Slot(object)
    def _on_rew_pull_measurement_selected(
        self, result: MeasurementSummary | tuple[MeasurementSummary, MeasurementSummary]
    ) -> None:
        """Handle measurement selection from the embedded RewPullView.

        Args:
            result: A single MeasurementSummary (Stereo) or a (left, right)
                tuple (L/R) from RewPullView.measurement_selected.
        """
        self._dispatch_measurement_selection(result)

    @Slot()
    def _on_rew_pull_back_requested(self) -> None:
        """Handle Back/Cancel from the sidebar's embedded RewPullView."""
        self._sidebar_load_in_progress = False
        self._active_rew_pull_view = None
        # Only announce a cancellation if the user backed out of an actual
        # selection — the placeholder state already shows its own message
        # (connecting, no measurements found, connection error).
        if self._rew_pull_view.showing_picker:
            self._status_banner.show_info("Selection cancelled", auto_dismiss=3000)
        step = self._wizard_controller.current_step
        page_key = _STEP_TO_PAGE_KEY.get(step)
        if page_key and page_key in PAGE_INDICES:
            self._stacked_widget.setCurrentIndex(PAGE_INDICES[page_key])

    @Slot()
    def _on_filters_rew_pull_back_requested(self) -> None:
        """Handle Back/Cancel from FiltersPage's embedded RewPullView.

        FiltersPage already flips its own source toggle back to File Import
        (see FiltersPage._on_rew_pull_back_requested) — this only clears the
        shared in-flight tracking so a late REW response doesn't resurrect
        the picker after the user has moved on.
        """
        self._active_rew_pull_view = None

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
        log_dir = self._settings.log_directory or str(get_log_dir())
        presets_dir = (
            self._settings.presets_directory or str(self._profile_repository.storage_root)
        )
        rew_export = self._settings.rew_export_folder
        self._settings_view.set_settings({
            "theme": self._settings.theme,
            "log_directory": log_dir,
            "presets_directory": presets_dir,
            "rew_export_folder": rew_export,
            "discovery_timeout": self._settings.discovery_timeout,
            "dry_run_default": self._settings.dry_run_default,
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

        # Generate support bundle from Settings support section
        self._settings_view.support_bundle_requested.connect(
            self._on_support_bundle_requested
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
    def _on_settings_changed(self, settings_dict: dict[str, Any]) -> None:
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
    def _on_support_bundle_requested(self) -> None:
        """Generate a support bundle ZIP and offer to save it."""
        from src.utils.support_bundle import generate_support_bundle

        log_dir = get_log_dir()
        settings_path = (
            self._settings.settings_path()
            if hasattr(self._settings, "settings_path")
            else None
        )

        # Ask user where to save
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Support Bundle",
            str(Path.home() / "wiim-rew-sync-support.zip"),
            "ZIP files (*.zip)",
        )
        if not save_path:
            return

        save_file = Path(save_path)
        output_dir = save_file.parent

        try:
            bundle_path = generate_support_bundle(
                output_path=output_dir,
                log_dir=log_dir,
                settings_path=settings_path,
            )
            # Rename to user's chosen filename if different
            if bundle_path != save_file:
                bundle_path.rename(save_file)
                bundle_path = save_file
            self._status_banner.show_success(
                f"Support bundle saved: {bundle_path.name}"
            )
        except Exception as exc:
            logger.exception("Failed to generate support bundle")
            self._status_banner.show_error(
                f"Failed to generate support bundle: {exc}"
            )

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
        """Open the Help window (Help > User Guide or sidebar Help)."""
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    @Slot()
    def _on_about_triggered(self) -> None:
        """Show About dialog (Help > About)."""
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.about(
            self,
            "About WiiM \u2194 REW PEQ Sync",
            "<h3>WiiM \u2194 REW PEQ Sync</h3>"
            "<p><b>Version 0.1.0</b></p>"
            "<p>Transfer parametric EQ and RoomFit filter configurations "
            "between Room EQ Wizard (REW) and WiiM devices on your local network.</p>"
            "<p><b>Features:</b></p>"
            "<ul>"
            "<li>Import/export REW EQ text files</li>"
            "<li>Read/write PEQ and RoomFit filters via WiiM HTTP API</li>"
            "<li>Stereo and L/R channel mode support</li>"
            "<li>Local preset library with backup and undo</li>"
            "<li>Multi-source and multi-device operations</li>"
            "</ul>"
            "<p><small>Local-first \u2022 No cloud \u2022 No telemetry</small></p>"
            "<hr>"
            "<p><small><b>Trademark Notice:</b> "
            "WiiM\u00AE is a trademark of Linkplay Technology Inc. "
            "REW (Room EQ Wizard) is developed by John Mulcahy. "
            "This tool is an independent project and is not affiliated with, "
            "endorsed by, or sponsored by Linkplay Technology or the REW project."
            "</small></p>"
            "<p><small>Licensed under MIT License. "
            "This software is provided as-is with no warranty. "
            "The authors assume no responsibility for any damage to your "
            "devices. Use at your own risk.</small></p>",
        )

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
        """Handle Escape — dismiss help dialog if visible, cancel active operation."""
        if self._help_dialog.isVisible():
            self._help_dialog.hide()
            logger.debug("Keyboard shortcut: Escape — Help dialog dismissed")
        elif self._feedback_manager.is_active:
            # Cancel active operation
            self._feedback_manager.cancel_requested.emit()
            logger.debug("Keyboard shortcut: Escape — Operation cancelled")

    # ------------------------------------------------------------------
    # Secondary Workflows (Req 17, 18, 20, 21)
    # ------------------------------------------------------------------

    def _setup_secondary_workflows(self) -> None:
        """Create the SecondaryWorkflowManager and wire its signals.

        Connects:
        - PresetsDeviceView "Copy to Another Device" → handled directly by
          MainWindow's own _do_copy_presets_batch_multi /
          _do_copy_preset_to_device (not via SecondaryWorkflowManager).
        - MyPresetsView "Load" → profile recall → populate ReviewPage
        - PushPage "Undo" → undo_last_push flow
        - SecondaryWorkflowManager completion signals → UI updates

        Note: "Copy to another source" / "Apply to multiple devices" had no
        UI wiring and the corresponding SecondaryWorkflowManager methods
        were removed as dead code (code quality audit, 2026-06-28).
        """
        self._secondary_workflows = SecondaryWorkflowManager(parent=self)

        # --- Inbound: page/view actions → workflow manager ---
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
        self._my_presets_view.rename_requested.connect(
            self._on_profile_rename_requested
        )
        self._my_presets_view.duplicate_requested.connect(
            self._on_profile_duplicate_requested
        )
        self._my_presets_view.delete_requested.connect(
            self._on_profile_delete_requested
        )
        self._rew_pull_view.measurement_selected.connect(
            self._on_rew_pull_measurement_selected
        )
        self._rew_pull_view.back_requested.connect(
            self._on_rew_pull_back_requested
        )
        self._filters_page.rew_pull_view.measurement_selected.connect(
            self._on_rew_pull_measurement_selected
        )
        self._filters_page.rew_pull_view.back_requested.connect(
            self._on_filters_rew_pull_back_requested
        )

        # --- Outbound: workflow manager signals → UI updates ---
        self._secondary_workflows.profile_recalled.connect(
            self._on_profile_recalled
        )
        self._secondary_workflows.undo_complete.connect(
            self._on_undo_complete
        )

    # --- Inbound handlers (page/view → workflow trigger) ---

    @Slot(list)
    def _on_copy_to_device_requested(self, items: list[Any]) -> None:
        """Handle PresetsDeviceView "Copy to Another Device" action.

        Opens a device picker for the target device selection, then
        executes _do_copy_presets_batch_multi for each selected item.

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

        # Copy to ALL selected devices (smoke #73 — was using only first device)
        target_source = state.selected_source

        logger.info(
            "Copy-to-device: %d items to %d device(s)",
            len(items),
            len(selected_devices),
        )

        # Process all items across all selected devices in a single async operation
        self._bridge.run_async(
            self._bridge_wrapper(
                "copy_presets_to_devices",
                self._do_copy_presets_batch_multi(
                    items, selected_devices, target_source or "wifi"
                ),
            )
        )

    @Slot(object)
    def _on_profile_load_requested(self, profile: object) -> None:
        """Handle MyPresetsView "Load" action — recall profile into ReviewPage.

        Loads the profile's filters and navigates to the Review step.
        If wizard state is incomplete (no EQ type/source), shows QuickSetupDialog
        to collect missing info before loading (smoke #87).

        Requirement 17.2: Profile Recall & Push flow.

        Args:
            profile: Profile object from the local preset library.
        """
        logger.info("Profile load requested: %s", getattr(profile, "name", "unknown"))

        # Check if wizard state is complete enough to load
        if not self._ensure_wizard_state_for_load():
            return

        # Set channel_mode in wizard state from profile BEFORE recall emits
        channel_mode = getattr(profile, "channel_mode", ChannelMode.STEREO)
        if isinstance(channel_mode, str):
            channel_mode = ChannelMode.from_any(channel_mode)
        self._wizard_controller.state.channel_mode = channel_mode
        self._secondary_workflows.recall_profile(profile)

    @Slot()
    def _on_review_save_preset(self) -> None:
        """Handle ReviewPage 'Save to My Presets' — save current filters locally.

        Uses the shared _save_filters_to_presets helper for consistent behavior
        regardless of which view triggers the save.
        """
        state = self._wizard_controller.state
        filters = state.current_filters
        if not filters:
            self._status_banner.show_error("No filters to save")
            return

        # Generate a default preset name from device + source
        device_name = "WiiM"
        for d in self._discovered_devices:
            if d.ip == state.selected_device:
                device_name = d.name
                break
        source = state.selected_source or "wifi"
        channel = state.channel_mode
        preset_name = f"{device_name} - {source} ({channel.display_value})"

        self._save_filters_to_presets(preset_name, filters, channel)

    @Slot(str, str)
    def _on_profile_rename_requested(self, old_name: str, new_name: str) -> None:
        """Handle MyPresetsView rename action."""
        try:
            self._profile_repository.rename(old_name, new_name)
            self._refresh_presets_view()
            self._status_banner.show_success(f"Renamed '{old_name}' to '{new_name}'")
        except Exception as exc:
            self._status_banner.show_error(f"Rename failed: {exc}")

    @Slot(str)
    def _on_profile_duplicate_requested(self, name: str) -> None:
        """Handle MyPresetsView duplicate action."""
        try:
            new_name = f"{name} (copy)"
            self._profile_repository.duplicate(name, new_name)
            self._refresh_presets_view()
            self._status_banner.show_success(f"Duplicated '{name}'")
        except Exception as exc:
            self._status_banner.show_error(f"Duplicate failed: {exc}")

    @Slot(str)
    def _on_profile_delete_requested(self, name: str) -> None:
        """Handle MyPresetsView delete action."""
        try:
            self._profile_repository.delete(name)
            self._refresh_presets_view()
            self._status_banner.show_success(f"Deleted '{name}'")
        except Exception as exc:
            self._status_banner.show_error(f"Delete failed: {exc}")

    @Slot(list)
    def _on_preset_export_requested(self, items: list[Any]) -> None:
        """Handle PresetsDeviceView "Export as REW File" for selected presets.

        Shows the appropriate file dialog (stereo or L/R based on item metadata),
        then reads from device and writes to file.

        Args:
            items: List of PresetItem objects selected for export.
        """
        if not items:
            return

        item = items[0]
        preset_name = getattr(item, "name", "")
        preset_type = getattr(item, "preset_type", "PEQ")
        channel_mode = getattr(item, "channel_mode", "Stereo")

        # Use the same dialog pattern as ReviewPage export
        if is_lr_mode(channel_mode):
            from src.gui.dialogs.export_dialog import ExportDialog

            paths = ExportDialog.get_paths(
                channel_mode="lr", default_name=preset_name, parent=self
            )
            if paths is None:
                logger.debug("L/R preset export cancelled")
                return
            # Pass base path (first path's stem without _L suffix)
            assert isinstance(paths, tuple)
            path_l, _path_r = paths
            # Use the left path — _do_preset_export handles L/R splitting internally
            export_path = str(path_l.parent / path_l.stem.replace("_L", "")) + ".txt"
        else:
            default_dir = self._settings.rew_export_folder or str(Path.home())
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Export Preset as REW File",
                str(Path(default_dir) / f"{preset_name}.txt"),
                "REW EQ Files (*.txt)",
            )
            if not path:
                logger.debug("Preset export cancelled")
                return
            if not path.lower().endswith(".txt"):
                path += ".txt"
            export_path = path

        self._status_banner.show_progress(f"Exporting '{preset_name}'...")
        self._bridge.run_async(
            self._bridge_wrapper(
                "preset_export",
                self._do_preset_export(preset_name, preset_type, export_path),
            )
        )
        logger.info("Preset export requested: %s -> %s", preset_name, export_path)

    @Slot(list)
    def _on_preset_save_requested(self, items: list[Any]) -> None:
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
        the wizard Review page. Shows QuickSetupDialog if wizard state
        is incomplete (smoke #87).

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

        # Check if wizard state is complete enough to load
        if not self._ensure_wizard_state_for_load():
            return

        # Set flag so _on_peq_ready navigates directly to Review (smoke #87)
        self._sidebar_load_in_progress = True
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

    @Slot(list)
    def _on_profile_recalled(self, filters: list[CanonicalFilter]) -> None:
        """Handle profile recall — populate ReviewPage and navigate.

        Loads the recalled filters into the wizard state and ReviewPage,
        then navigates to the Review step. Uses L/R display when channel_mode
        was set by _on_profile_load_requested.

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

        # Populate ReviewPage with the recalled filters (L/R aware)
        channel = state.channel_mode
        if channel.is_lr:
            # Use stored L/R lists (set by recall_profile before emitting signal)
            left, right = get_lr_filters(state, filters)
            self._review_page.set_lr_filters(left, right)
        else:
            self._review_page.set_filters(filters)

        # Update summary (use current connection info if available)
        device = state.selected_device or "No device"
        source = state.selected_source or "Not selected"
        active_bands = sum(1 for f in filters if getattr(f, "enabled", True))
        self._review_page.set_summary(device, source, channel.display_value, active_bands)

        # Navigate to Review step — update both wizard state and stacked widget
        # so that subsequent navigation/step_changed doesn't override (smoke #87)
        self._mark_prior_steps_completed(state)
        self._wizard_controller.state.current_step = WizardStep.REVIEW
        # Switching the page fires currentChanged, which
        # _sync_navigation_chrome handles centrally (step pill highlight +
        # undim, sidebar reset to "home") — no manual sync needed here.
        self._stacked_widget.setCurrentIndex(PAGE_INDICES["review"])

        # Emit step summaries for the step indicator (smoke #87)
        for step, summary in state.completed_steps.items():
            self._wizard_controller.step_summary_updated.emit(step, summary)

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
    # Quick Setup helper (smoke #87)
    # ------------------------------------------------------------------

    def _ensure_wizard_state_for_load(self) -> bool:
        """Check wizard state is complete for loading filters; show dialog if not.

        If no device is connected, shows error and returns False.
        If EQ type or source is missing, shows QuickSetupDialog.
        On cancel, returns False. On confirm, updates wizard state, marks
        EQ_TYPE/SOURCE/FILTERS steps completed, and returns True.

        Returns:
            True if state is ready for loading, False if cancelled or blocked.
        """
        from src.gui.dialogs.quick_setup_dialog import QuickSetupDialog

        state = self._wizard_controller.state

        # Must have a device
        if state.selected_device is None:
            self._status_banner.show_error("Connect to a device first")
            return False

        # If user is already at FILTERS step or beyond, all context is set
        current_step = self._wizard_controller.current_step
        sequence = self._wizard_controller.get_steps()
        if current_step in sequence:
            current_idx = sequence.index(current_step)
            filters_idx = (
                sequence.index(WizardStep.FILTERS)
                if WizardStep.FILTERS in sequence
                else -1
            )
            if filters_idx >= 0 and current_idx >= filters_idx:
                # Already at or past Filters — all state is populated
                self._mark_prior_steps_completed(state)
                return True

        # Determine what's missing
        flow_type = self._wizard_controller.flow_type

        # EQ_TYPE is only needed if the device supports both PEQ and RoomFit
        # (PEQ_ONLY flow has no EQ_TYPE step, so it's never "needed")
        need_eq_type = (
            WizardStep.EQ_TYPE not in state.completed_steps
            and flow_type == FlowType.PEQ  # Only PEQ flow has EQ_TYPE step
        )

        # For PEQ/PEQ_ONLY flow, need source if SOURCE step not completed
        need_source = (
            WizardStep.SOURCE not in state.completed_steps
            and flow_type != FlowType.ROOMFIT
        )
        # If EQ_TYPE is already completed as RoomFit, no source needed
        if not need_eq_type and flow_type == FlowType.ROOMFIT:
            need_source = False

        # Nothing missing — proceed
        if not need_eq_type and not need_source:
            # All prior steps should be marked completed
            self._mark_prior_steps_completed(state)
            return True

        # Show dialog — source list and RoomFit support come from the
        # connected device's (capability-file-merged) capabilities; fall back
        # to the generic list only when no device/capabilities are available.
        device_caps = self._device_caps
        available_sources = list(getattr(device_caps, "source_names", []) or [])
        if not available_sources:
            available_sources = list(self._source_page._source_checkboxes.keys())
        supports_roomfit = bool(getattr(device_caps, "supports_roomfit", True))

        current_eq_type = "roomfit" if flow_type == FlowType.ROOMFIT else "peq"
        current_sources = (
            [s.strip() for s in state.selected_source.split(",") if s.strip()]
            if state.selected_source
            else None
        )

        result = QuickSetupDialog.get_setup(
            self,
            need_eq_type=need_eq_type,
            need_source=need_source,
            available_sources=available_sources,
            current_eq_type=current_eq_type,
            current_sources=current_sources,
            supports_roomfit=supports_roomfit,
        )

        if result is None:
            return False

        eq_type, sources = result

        # Apply EQ type to wizard state
        if need_eq_type:
            if eq_type == "roomfit":
                self._wizard_controller.set_flow_type(FlowType.ROOMFIT)
                state.completed_steps[WizardStep.EQ_TYPE] = "RoomFit"
            else:
                self._wizard_controller.set_flow_type(FlowType.PEQ)
                state.completed_steps[WizardStep.EQ_TYPE] = "PEQ"

        # Apply source to wizard state (PEQ only)
        current_flow = self._wizard_controller.flow_type
        if current_flow != FlowType.ROOMFIT and sources:
            state.selected_source = ",".join(sources)
            state.completed_steps[WizardStep.SOURCE] = ",".join(sources)

        # Mark FILTERS as completed (we're loading filters from sidebar)
        state.completed_steps[WizardStep.FILTERS] = "Loaded from preset"

        return True

    def _mark_prior_steps_completed(self, state: object) -> None:
        """Mark CONNECT, EQ_TYPE, SOURCE, FILTERS steps as completed if not already.

        Called when all info is already present so the step indicator shows
        proper checkmarks when navigating to Review from sidebar.
        """
        from src.gui.wizard_controller import WizardState

        assert isinstance(state, WizardState)
        flow_type = self._wizard_controller.flow_type

        # CONNECT step — always mark if device is selected
        if WizardStep.CONNECT not in state.completed_steps and state.selected_device:
            state.completed_steps[WizardStep.CONNECT] = "Connected"

        # EQ_TYPE step — only exists in PEQ and ROOMFIT flows (not PEQ_ONLY)
        if flow_type == FlowType.PEQ and WizardStep.EQ_TYPE not in state.completed_steps:
            state.completed_steps[WizardStep.EQ_TYPE] = "PEQ"
        elif flow_type == FlowType.ROOMFIT and WizardStep.EQ_TYPE not in state.completed_steps:
            state.completed_steps[WizardStep.EQ_TYPE] = "RoomFit"

        # SOURCE step — only needed for PEQ/PEQ_ONLY flows (not ROOMFIT)
        if flow_type != FlowType.ROOMFIT and WizardStep.SOURCE not in state.completed_steps:
            source = state.selected_source or "wifi"
            if not source:
                source = "wifi"
            state.selected_source = source
            state.completed_steps[WizardStep.SOURCE] = source

        # FILTERS step
        if WizardStep.FILTERS not in state.completed_steps:
            n_filters = len(state.current_filters)
            state.completed_steps[WizardStep.FILTERS] = (
                f"{n_filters} filters" if n_filters else "Loaded"
            )

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

