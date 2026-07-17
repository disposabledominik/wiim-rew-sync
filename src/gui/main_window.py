"""Main application window — wizard-driven single-pane interface.

Replaces the old splitter-based MainWindow. Serves as the application shell
with SidebarNav, StepIndicator, QStackedWidget content area, StatusBanner,
and a diagnostics dock widget.

Requirements referenced: 14.1, 14.2, 14.4, 14.5, 10.1, 10.6, 24.6,
    10.5, 10.11, 10.12, 10.13, 13.1-13.6, 26.1-26.7.
"""

from __future__ import annotations

import html
import json
import logging
import sys
import traceback
from collections.abc import Callable, Coroutine
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, cast

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
from src.adapters.safe_write import RoomFitSafeWrite, SafeWrite, WriteResult
from src.adapters.wiim_adapter import WiiMAdapter
from src.adapters.wiim_http import WiiMHttpClient
from src.discovery.discovery_module import DiscoveryModule
from src.gui.adapter_factories import (
    make_capability_prober,
    make_rew_client,
    make_wiim_adapter,
    make_wiim_http_client,
)
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
from src.gui.dialogs.preset_type_dialog import PresetTypeDialog
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
from src.gui.primary_workflows import EmptyPresetFiltersError, PrimaryWorkflowManager
from src.gui.secondary_workflows import (
    SecondaryWorkflowManager,
)
from src.gui.shared_helpers import read_preset_preview
from src.gui.theme import ThemeManager
from src.gui.views.help_view import HelpView
from src.gui.views.my_presets_view import MyPresetsView
from src.gui.views.presets_device_view import PresetsDeviceView
from src.gui.views.rew_pull_view import RewPullView
from src.gui.views.settings_view import SettingsView
from src.gui.wizard_controller import (
    FlowType,
    WizardController,
    WizardState,
    WizardStep,
    parse_source_list,
)
from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceCapabilities, DeviceInfo
from src.models.channel_mode import ChannelMode, get_lr_filters, is_lr_mode
from src.models.constants import DEFAULT_MAX_BANDS, DEFAULT_SOURCE, DEFAULT_SOURCE_NAMES
from src.models.errors import (
    ParseError,
    REWNotConnectedError,
    ValidationError,
    WiiMConnectionError,
    WiiMTimeoutError,
)
from src.models.peq import PEQSettings, build_peq_settings, extract_filters
from src.models.profile import build_profile
from src.repository.backup_manager import (
    BackupManager,
    load_backup_json,
    parse_backup_restore_metadata,
)
from src.repository.profile_repository import ProfileRepository
from src.utils.app_dirs import get_app_data_dir, get_log_dir
from src.utils.device_name import sanitize_device_name

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

# Canonical EQ_TYPE step summary wording, used by every entry point that
# completes this step (normal flow, sidebar jump, QuickSetupDialog) so they
# never drift independently again (#162).
_EQ_TYPE_SUMMARY: dict[str, str] = {"peq": "PEQ", "roomfit": "RoomFit"}


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

    def __init__(
        self,
        async_bridge: AsyncBridge | None = None,
        *,
        rew_client_factory: Callable[[], REWHttpApiClient] = make_rew_client,
        wiim_http_client_factory: Callable[[str], WiiMHttpClient] = make_wiim_http_client,
        capability_prober_factory: Callable[
            [WiiMHttpClient], CapabilityProber
        ] = make_capability_prober,
        wiim_adapter_factory: Callable[
            [WiiMHttpClient, DeviceCapabilities], WiiMAdapter
        ] = make_wiim_adapter,
    ) -> None:
        """Initialize the main window.

        Args:
            async_bridge: The async bridge for background operations.
                         If None, a new one is created and started.
            rew_client_factory: Constructs the REW HTTP API client.
                Overridable for tests; defaults to the real adapter
                (src.gui.adapter_factories.make_rew_client).
            wiim_http_client_factory: Constructs a WiiM HTTP client for a
                given device IP. Overridable for tests; defaults to the
                real adapter (make_wiim_http_client).
            capability_prober_factory: Constructs a capability prober for a
                given WiiM HTTP client. Overridable for tests; defaults to
                the real adapter (make_capability_prober).
            wiim_adapter_factory: Constructs a WiiM adapter for a given
                client + probed capabilities. Overridable for tests;
                defaults to the real adapter (make_wiim_adapter). Distinct
                from the per-connection `wiim_adapter_factory` lambda passed
                to PrimaryWorkflowManager/SecondaryWorkflowManager below --
                that one captures a specific `caps` value per device
                connection and calls this one internally.
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

        # --- Adapter construction factories (dependency injection; see
        # src/gui/adapter_factories.py and test_gui_adapter_injection.py) ---
        self._rew_client_factory = rew_client_factory
        self._wiim_http_client_factory = wiim_http_client_factory
        self._capability_prober_factory = capability_prober_factory
        self._wiim_adapter_factory = wiim_adapter_factory

        # --- Backend adapter instances (Req 14.1-14.6) ---
        # Eagerly created at startup:
        self._discovery_module = DiscoveryModule(
            timeout=float(self._settings.discovery_timeout),
        )
        self._rew_client = self._rew_client_factory()
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
        self._roomfit_safe_write: RoomFitSafeWrite | None = None
        self._device_caps: object | None = None
        # Set via _on_name_profiles_ready from get_roomfit_status() (#165) --
        # whether RoomFit is currently on. Not currently read anywhere:
        # _on_name_confirmed's overwrite-confirmation dialog is driven by
        # NameProfilePage.classify() instead, not this flag.
        self._roomfit_enabled: bool = False

        # --- Window properties ---
        self.setWindowTitle("WiiM \u2194 REW PEQ Sync")
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.resize(1000, 700)

        # --- Create controller ---
        self._wizard_controller = WizardController(self)

        # --- Primary workflows (discovery, probing, file import) ---
        # Configured eagerly, unlike SecondaryWorkflowManager: none of these
        # workflows need a live device adapter (see primary_workflows.py).
        self._primary_workflows = PrimaryWorkflowManager(parent=self)
        self._primary_workflows.configure(
            bridge=self._bridge,
            discovery_module=self._discovery_module,
            wizard_controller=self._wizard_controller,
            bridge_wrapper=self._bridge_wrapper,
            rew_client=self._rew_client,
            profile_repository=self._profile_repository,
        )

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

        # --- Primary workflows: presets_ready signal wiring (Phase 1b) ---
        self._setup_primary_workflows()

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
        self._bridge.stage_changed.connect(self._on_stage_changed)
        self._bridge.push_round_changed.connect(self._on_push_round_changed)
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
        state.last_pushed_filters = []
        # A stale "what current_filters came from" string from the previous
        # device must not linger into this one (#162d).
        state.filters_origin = ""
        # A stale "RoomFit is active" flag from the previous device must not
        # linger either, even though nothing currently reads it (see the
        # __init__ comment) -- reset defensively so device B's state is
        # never contaminated by device A's, until populate_name_profiles()
        # re-fetches device B's real status.
        self._roomfit_enabled = False
        # Clear completed steps beyond CONNECT
        for step in (
            WizardStep.EQ_TYPE,
            WizardStep.SOURCE,
            WizardStep.FILTERS,
            WizardStep.REVIEW,
            WizardStep.PUSH,
        ):
            state.completed_steps.pop(step, None)
            state.completed_step_tooltips.pop(step, None)

        # Lazily create device-specific adapters (Req 14.2, 14.3)
        self._wiim_http_client = self._wiim_http_client_factory(device_ip)
        self._capability_prober = self._capability_prober_factory(self._wiim_http_client)

        # Bump generation so a still-in-flight probe from a previous device
        # selection is discarded instead of advancing the wizard out from
        # under the user (see _do_probe).
        generation = self._primary_workflows.bump_probe_generation()
        self._primary_workflows.probe(self._capability_prober, generation)
        logger.info("Device selected: %s", device_ip)

    @Slot()
    def _on_refresh_requested(self) -> None:
        """Handle refresh/rescan request from ConnectPage."""
        if self._is_busy():
            return

        self._connect_page.set_scanning(True)
        self._primary_workflows.discover()
        logger.debug("Discovery refresh requested")

    # ------------------------------------------------------------------
    # Step-summary helpers -- shared by every entry point that completes a
    # wizard step (normal flow, sidebar jump, QuickSetupDialog), so the same
    # step always shows the same wording regardless of path (#162).
    # ------------------------------------------------------------------

    def _lookup_device_name(self, ip: str | None, default: str) -> str:
        """Friendly device name for `ip` from the current discovery list, or
        `default` if not found -- shared by every call site that needs a
        device name for display (step summaries, default export/preset
        filenames), so they can't independently drift (#176)."""
        for d in self._primary_workflows.discovered_devices:
            if d.ip == ip:
                return d.name
        return default

    def _device_prefixed_name(self, base_name: str) -> str:
        """Prefix `base_name` with the connected device's friendly name, so
        exported/saved files stay unambiguous across multiple devices.

        Always resolves against the currently connected device
        (`state.selected_device`) -- every call site means exactly that, so
        this takes no device-IP override.
        """
        device_name = self._lookup_device_name(
            self._wizard_controller.state.selected_device, "WiiM"
        )
        return f"{device_name} - {base_name}"

    def _resolve_connect_summary(self) -> str:
        """Friendly device name for the Connect step -- same on every entry point."""
        caps = self._device_caps
        selected_ip = self._wizard_controller.state.selected_device
        return self._lookup_device_name(selected_ip, getattr(caps, "model", "") or "WiiM Device")

    def _compute_source_summary(self, source_name: str) -> tuple[str, str]:
        """(summary, tooltip) for the Sources step -- same on every entry point.

        Single source -> its name, no tooltip. All available sources ->
        "All sources", with a tooltip listing them. Otherwise -> "N sources"
        with a tooltip listing them.
        """
        sources = parse_source_list(source_name)
        if not sources:
            return "", ""
        available = list(getattr(self._device_caps, "source_names", []) or [])
        if len(sources) == 1:
            return sources[0], ""
        if available and set(sources) == set(available):
            return "All sources", ", ".join(sources)
        return f"{len(sources)} sources", ", ".join(sources)

    def _apply_source_summary(self, state: WizardState, source_name: str) -> None:
        """Set completed_steps[SOURCE] + its tooltip together, out of the
        normal advance() flow -- used by the two out-of-sequence completion
        paths (sidebar jump, QuickSetupDialog) where SOURCE isn't
        necessarily the step currently being transitioned through. Dict
        writes only, no signal emission -- both callers already replay-emit
        every completed step's summary+tooltip once they're done.
        """
        summary, tooltip = self._compute_source_summary(source_name)
        state.completed_steps[WizardStep.SOURCE] = summary
        state.completed_step_tooltips[WizardStep.SOURCE] = tooltip

    def _resolve_filters_summary(self, n_filters: int) -> str:
        """Standardize on the most informative existing wording everywhere.

        0 -> "Loaded" (no count to show); 1 -> "1 filter" (singular);
        N -> "N filters".
        """
        if not n_filters:
            return "Loaded"
        return f"{n_filters} filter" if n_filters == 1 else f"{n_filters} filters"

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
            self._primary_workflows.refresh_roomfit_dropdown()

        # A stale "what current_filters came from" string from before this EQ
        # type switch must not linger into the new flow (#162d/#173) -- mirrors
        # the same clearing _on_device_selected already does on device switch.
        self._wizard_controller.state.filters_origin = ""
        self._wizard_controller.advance(
            summary=_EQ_TYPE_SUMMARY.get(eq_type, eq_type.upper())
        )

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

        summary, tooltip = self._compute_source_summary(source_name)
        self._wizard_controller.advance(summary=summary, tooltip=tooltip)

    @Slot()
    def _on_filters_accepted(self) -> None:
        """Handle user accepting filters (with or without warnings) — advance."""
        state = self._wizard_controller.state
        summary = self._resolve_filters_summary(len(state.current_filters))
        self._wizard_controller.advance(summary=summary, tooltip=state.filters_origin)

    @Slot(str)
    def _on_file_import_requested(self, path: str) -> None:
        """Handle file import request from FiltersPage.

        Args:
            path: Path to the REW text file.
        """
        if self._is_busy():
            return

        self._primary_workflows.import_file(path)
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

        self._primary_workflows.import_file_lr(path_l, path_r)
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

        # No source-selection guard needed here: _do_device_pull reads
        # state.primary_source, which already defaults to DEFAULT_SOURCE
        # when no source was selected (RoomFit is device-global, or the
        # source step was skipped).
        self._status_banner.show_progress("Pulling filters from device...")
        self._primary_workflows.pull_device()
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
        self._primary_workflows.list_rew_measurements()
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
        self._primary_workflows.pull_roomfit(profile_name)
        logger.info("RoomFit profile selected: %s", profile_name)

    @Slot(bool)
    def _on_dry_run_toggled(self, enabled: bool) -> None:
        """Handle dry run toggle — update wizard state.

        The first time a user turns Dry Run off while it's still the global
        default, offer to disable that default for future sessions too
        (smoke #182) -- non-technical users are unlikely to find this in
        Settings on their own. Only fires while the default is still on, so
        it won't repeat once they've answered.
        """
        self._wizard_controller.state.dry_run = enabled
        if not enabled and self._settings.dry_run_default:
            if self._confirm_action(
                "Disable Dry Run by Default?",
                "Dry Run is on by default for new sessions, so nothing is "
                "pushed to your device unless you turn it off each time.\n\n"
                "Turn off this default now? You can re-enable it later in "
                "Settings.",
            ):
                self._settings.dry_run_default = False
                self._settings.save()
                self._populate_settings_view()

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
            sources = state.selected_sources
            source_info = ", ".join(sources) if sources else state.primary_source
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

        Every push now unconditionally makes the pushed profile active and
        turns RoomFit on if it was off (RoomFitSafeWrite.execute()) -- that
        consequence applies regardless of which name is chosen, so it's
        surfaced via NameProfilePage's always-visible caption, not this
        dialog. What this dialog still confirms is purely the *data-loss*
        risk of overwriting stored content:
        - The active profile: overwriting it replaces its stored filters
          with the ones just selected, which also updates what's currently
          playing since it's already the active profile.
        - A different, non-active existing profile: overwriting it loses
          that profile's stored filters (no live-audio distinction from the
          active case anymore -- both now activate on save).

        Args:
            name: The profile name chosen by the user.
        """
        kind = self._name_profile_page.classify(name)
        if kind == "active":
            if not self._confirm_action(
                "Overwrite Active Profile",
                f"'{name}' is your currently active profile. Saving will overwrite "
                "its stored filters with the ones you've selected, updating what's "
                "playing right now. Continue?",
            ):
                return
        elif kind == "existing":
            if not self._confirm_action(
                "Overwrite Existing Profile",
                f"A profile named '{name}' already exists. Saving will overwrite "
                "its stored filters and make it the active profile on your device, "
                "turning RoomFit on if it's off. Continue?",
            ):
                return
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

        if self._wizard_controller.flow_type == FlowType.ROOMFIT:
            # RoomFit undo: restore backed-up bands to the same profile name
            source_name = self._wizard_controller.state.primary_source
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
                source_name = self._wizard_controller.state.primary_source
                self._secondary_workflows.undo_last_push(source_name, backup_path)

    async def _do_undo_roomfit(
        self, backup_path: str, source_name: str, profile_name: str
    ) -> None:
        """Restore a RoomFit profile from backup — thin pass-through to
        RoomFitSafeWrite.undo(), which owns all orchestration (backup
        parsing, new-vs-overwrite branching, selection/enable-state
        restore to the state before the *original* push). GUI layer
        performs no data manipulation (CLAUDE.md).
        """
        assert self._wiim_adapter is not None

        path = Path(backup_path) if backup_path else Path(".")
        if not path.exists() or not path.is_file():
            self._status_banner.show_error("No backup available for undo")
            return

        try:
            self._bridge.progress_update.emit(f"Restoring '{profile_name}'...")
            roomfit_safe_write = RoomFitSafeWrite(self._wiim_adapter, self._backup_manager)
            result = await roomfit_safe_write.undo(path, source_name, profile_name)
            if not result.success:
                self._status_banner.show_error(
                    result.error_message or "RoomFit undo verification failed"
                )
                return
            self._clear_pushed_snapshot()
            self._push_page.mark_undo_complete(True)
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
                self._status_banner.show_success(
                    f"Original profile re-activated. Profile '{profile_name}' was "
                    "kept, but deactivated."
                )
            else:
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

        if succeeded > 0:
            self._clear_pushed_snapshot()

        if failed == 0:
            self._push_page.mark_undo_complete(True)
            self._status_banner.show_success(
                f"All {succeeded} source(s) restored from backup"
            )
        else:
            self._status_banner.show_error(
                f"Undo: {succeeded} restored, {failed} failed"
            )

    def _clear_pushed_snapshot(self) -> None:
        """Forget the last-successful-push snapshot after an undo.

        Once a push is undone, the device no longer reflects what
        last_pushed_filters recorded, so the unsaved-changes check must
        consider the wizard dirty again.
        """
        self._wizard_controller.state.last_pushed_filters = []

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

        # Replay completed step summaries + tooltips (rebuilding wiped them)
        tooltips = self._wizard_controller.state.completed_step_tooltips
        for step, summary in self._wizard_controller.completed_steps.items():
            if step in sequence:
                index = sequence.index(step)
                self._step_indicator.set_completed(index, summary, tooltips.get(step, ""))

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

    @Slot(object, str, str)
    def _on_step_summary_updated(self, step: object, summary: str, tooltip: str = "") -> None:
        """Handle step summary update — show summary + tooltip on StepIndicator.

        Args:
            step: The WizardStep whose summary changed.
            summary: The summary text to display.
            tooltip: Optional longer text shown on hover.
        """
        if not isinstance(step, WizardStep):
            return

        sequence = self._wizard_controller.get_steps()
        if step in sequence:
            index = sequence.index(step)
            self._step_indicator.set_completed(index, summary, tooltip)

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
        3. Determines flow type based on RoomFit read support
        4. Advances the wizard

        Args:
            caps: DeviceCapabilities object from the probe.
        """
        # Store capabilities (caps has supports_roomfit*, source_names, etc.)
        roomfit_readable = bool(getattr(caps, "supports_roomfit_read", False))

        # @Slot(object) erases the static type to satisfy PySide6's signal
        # registration -- probe() itself is properly typed as returning
        # DeviceCapabilities, so this narrows once here rather than
        # suppressing mypy separately at each of the two call sites below
        # that need the real type.
        device_caps = cast(DeviceCapabilities, caps)

        # Create WiiMAdapter and SafeWrite now that we have a connected client (Req 14.2, 14.3)
        assert self._wiim_http_client is not None
        self._wiim_adapter = self._wiim_adapter_factory(self._wiim_http_client, device_caps)
        self._safe_write = SafeWrite(self._wiim_adapter, self._backup_manager)
        self._roomfit_safe_write = RoomFitSafeWrite(self._wiim_adapter, self._backup_manager)

        # Configure SecondaryWorkflowManager with adapter factories (Req 8.1, 9.3, 10.3, 15.3)
        self._secondary_workflows.configure(
            bridge=self._bridge,
            wiim_adapter_factory=lambda ip: self._wiim_adapter_factory(
                self._wiim_http_client_factory(ip), device_caps
            ),
            safe_write_factory=lambda adapter: SafeWrite(adapter, self._backup_manager),
            backup_manager=self._backup_manager,
        )
        self._secondary_workflows.set_current_adapter(self._wiim_adapter)
        self._primary_workflows.set_current_adapter(self._wiim_adapter)

        # Source names: resolved once, centrally, in merge_into() (#167) --
        # real enumeration via getAudioInputEnable where the device supports
        # it, falling back to DEFAULT_SOURCE_NAMES otherwise. caps.source_names
        # is guaranteed non-empty by the time probe()/merge_into() returns.
        source_names = getattr(caps, "source_names", [])

        # Store capabilities for later use (smoke #35, #36) -- set before
        # _resolve_connect_summary() below, which reads self._device_caps.
        self._device_caps = caps
        device_name = self._resolve_connect_summary()

        # Determine flow type and advance wizard
        # Guard: some devices may incorrectly report RoomFit support due to
        # firmware variations. Use model name as secondary check (smoke #36).
        model_str = (getattr(caps, "model", "") or "").lower()
        roomfit_blocked_models = ("mini",)  # Models known to not support RoomFit
        is_roomfit_blocked = any(m in model_str for m in roomfit_blocked_models)

        if not roomfit_readable or is_roomfit_blocked:
            # PEQ-only device — skip EQ_TYPE step (Req 1.10)
            if is_roomfit_blocked and roomfit_readable:
                logger.warning(
                    "Device model '%s' reports RoomFit read support but "
                    "RoomFit is not supported on this model; forcing "
                    "PEQ_ONLY flow (smoke #36)",
                    model_str,
                )
            self._wizard_controller.set_flow_type(FlowType.PEQ_ONLY)
            self._wizard_controller.advance(summary=device_name)
        else:
            # Device supports RoomFit — show EQ_TYPE choice (Req 1.9)
            self._wizard_controller.advance(summary=device_name)

        # Update sidebar with device info, warning if displayed capabilities
        # aren't purely from live device probing (capability-file override
        # and/or generic/conservative fallback defaults)
        capability_warning = ""
        if getattr(caps, "capability_file_override", False) or getattr(
            caps, "used_generic_capabilities", False
        ):
            capability_warning = (
                "Some capabilities are from a capability-file override or "
                "generic defaults, not the device itself — see Diagnostics "
                "for details."
            )
        self._sidebar_nav.set_device_info(
            device_name, connected=True, capability_warning=capability_warning
        )

        # Populate SourcePage with available sources
        active_source = getattr(caps, "active_source", "")
        self._source_page.set_sources(source_names, active_source)

        # Gate L/R channel mode by device capability (post capability-file
        # merge — see device_capability_file.py) so the option is never
        # presented as available on a device that doesn't support it.
        self._filters_page.set_lr_enabled(getattr(caps, "supports_lr_filters", False))

        # Populate diagnostics panel capabilities display
        self._diagnostics_panel.on_capabilities_ready(caps)  # type: ignore[arg-type]

    def _clear_pending_lr_rows(self) -> None:
        """Reset pending L/R skip-row/conversion-note state.

        Shared by _validate_and_populate_review's L/R-success and
        L/R-without-bands-guard branches, plus _on_peq_ready's count==0
        early reset — this exact 4-field reset used to be duplicated three
        times.
        """
        state = self._wizard_controller.state
        state.pending_rows_l = []
        state.pending_rows_r = []
        state.pending_conversion_notes_l = {}
        state.pending_conversion_notes_r = {}

    def _clear_pending_stereo_rows(self) -> None:
        """Reset pending stereo skip-row/conversion-note state.

        Shared by _validate_and_populate_review's stereo-success branch and
        _on_peq_ready's count==0 early reset — this exact 2-field reset
        used to be duplicated twice.
        """
        state = self._wizard_controller.state
        state.pending_rows = []
        state.pending_conversion_notes = {}

    def _validate_and_populate_review(
        self, peq_data: object, state: WizardState
    ) -> tuple[list[str], int] | None:
        """Validate filters against device limits and populate ReviewPage.

        Branches on channel mode (smoke #28): explicit L/R bands supplied
        by peq_data, wizard-state L/R without explicit bands (a guard
        against an invariant break, see below), or stereo.

        Returns:
            (warnings, validated_count) on success, or None if the
            L/R-without-bands guard fired — it already showed its own
            error banner; the caller must return without advancing the
            wizard.
        """
        from src.translator.wiim_generator import validate_filters_for_device

        # Determine device max_filters and supported filter types
        max_filters = DEFAULT_MAX_BANDS
        supported_filter_types: list[str] | None = None
        if self._device_caps is not None:
            # merge_into() (#167c) guarantees max_filters is always a valid
            # positive int once capabilities are resolved -- no "or
            # DEFAULT_MAX_BANDS" fallback needed here; that used to be a
            # second, independently-drifting copy of the same default.
            max_filters = getattr(self._device_caps, "max_filters", DEFAULT_MAX_BANDS)
            supported_filter_types = (
                getattr(self._device_caps, "supported_filter_types", None) or None
            )

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
                list(bands_l), max_filters, state.pending_rows_l or None,
                supported_filter_types,
            )
            validated_r, warnings_r, clamping_r, rows_r = validate_filters_for_device(
                list(bands_r), max_filters, state.pending_rows_r or None,
                supported_filter_types,
            )
            notes_l = state.pending_conversion_notes_l
            notes_r = state.pending_conversion_notes_r
            self._clear_pending_lr_rows()

            # Merge warnings — prefix with channel so the combined status
            # text (joined with " | ") doesn't leave the user guessing
            # which side a truncation/clamping warning applies to.
            all_warnings = [f"Left: {w}" for w in warnings_l] + [
                f"Right: {w}" for w in warnings_r
            ]

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
            self._clear_pending_lr_rows()
            return None
        else:
            # Stereo: validate the full list
            validated, all_warnings, clamping_map, rows = validate_filters_for_device(
                state.current_filters, max_filters, state.pending_rows or None,
                supported_filter_types,
            )
            notes = state.pending_conversion_notes
            self._clear_pending_stereo_rows()
            state.current_filters = validated
            self._review_page.set_filters(validated, clamping_map, rows, notes)

        return all_warnings, len(state.current_filters)

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
        state = self._wizard_controller.state
        count = len(state.current_filters)

        if count == 0:
            # No filters at all — nothing to show, so any pending skip rows
            # from this attempt are moot. Reset so they don't leak into a
            # later unrelated flow.
            self._clear_pending_lr_rows()
            self._clear_pending_stereo_rows()
            # Also clear the sidebar-load one-shot flag here -- the else
            # branch below is the only other place that resets it, so a
            # sidebar load that resolves to zero filters would otherwise
            # leave it stuck True and incorrectly jump a later, unrelated
            # peq_ready straight to Review instead of advancing normally.
            self._sidebar_load_in_progress = False
            QTimer.singleShot(
                150, lambda: self._status_banner.show_info(
                    "Device has no active filters. Try importing from a REW file instead.",
                    auto_dismiss=0,
                )
            )
        else:
            result = self._validate_and_populate_review(peq_data, state)
            if result is None:
                return
            all_warnings, validated_count = result

            # Advance wizard to REVIEW step
            if getattr(self, "_sidebar_load_in_progress", False):
                # Sidebar load: navigate directly to Review (smoke #87)
                self._sidebar_load_in_progress = False
                self._jump_to_review()
            else:
                self._wizard_controller.advance(
                    summary=self._resolve_filters_summary(validated_count),
                    tooltip=state.filters_origin,
                )

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
            read_back = getattr(result, "read_back", None)
            filters: list[Any] | None = None
            filters_l: list[Any] | None = None
            filters_r: list[Any] | None = None
            if read_back is not None:
                if read_back.channel_mode == ChannelMode.LR:
                    filters_l = read_back.bands_l
                    filters_r = read_back.bands_r
                else:
                    filters = read_back.bands
            self._push_page.set_success(
                backup_path, filters=filters, filters_l=filters_l, filters_r=filters_r
            )
            self._wizard_controller.state.last_backup_path = backup_path
            self._wizard_controller.state.last_pushed_filters = list(
                self._wizard_controller.state.current_filters
            )
            # Mark PUSH step as completed in the step indicator
            self._wizard_controller.set_step_summary(WizardStep.PUSH, "Done")
            # Undo is always shown for a successful RoomFit push now (not
            # just overwrites) -- RoomFitSafeWrite.execute() always creates
            # a backup, even for a brand-new profile, since there's always
            # a selection/enable-state change to potentially undo even when
            # there are no prior bands to restore. PushPage.set_success()
            # already unconditionally shows the Undo button.
            self._status_banner.show_success("Filters pushed successfully")
            logger.info("Push succeeded. Backup: %s", backup_path or "(none)")
        else:
            error_msg = getattr(result, "error_message", None) or "Unknown error"
            # rollback_success is None when the write failed before any backup/
            # rollback was attempted (e.g. bad profile name); False means the
            # rollback restore itself failed too -- the only state that needs
            # the "Critical: Manual recovery required" UI, not just any failure.
            critical = getattr(result, "rollback_success", None) is False
            self._push_page.set_failure(error_msg, backup_path, critical)
            self._status_banner.show_error(f"Push failed: {error_msg}")
            logger.error(
                "Push failed (critical=%s): %s. Backup: %s",
                critical,
                error_msg,
                backup_path or "(none)",
            )

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
            self._sidebar_load_in_progress = False
            self._status_banner.show_info(info_text)
            self._show_rew_pull_message(info_text, icon=ICON_NO_DATA)
            return

        self._status_banner.show_progress(message)

    @Slot(str)
    def _on_stage_changed(self, stage: str) -> None:
        """Advance the Push page's stepper as SafeWrite reports real progress.

        Args:
            stage: One of "backing_up", "writing", "verifying", "done" (see
                SafeWrite.execute's/RoomFitSafeWrite.execute's on_stage arg).
        """
        self._push_page.set_stage(stage)

    @Slot(str, int, int)
    def _on_push_round_changed(self, source_name: str, index: int, total: int) -> None:
        """Show which source/round a multi-source push is currently on.

        Args:
            source_name: The source currently being written to.
            index: 1-based index of this source among the selected sources.
            total: Total number of sources being pushed to.
        """
        self._push_page.set_push_round(source_name, index, total)

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
            self._primary_workflows.get_rew_filters_lr(
                measurement_l.uuid, measurement_r.uuid,
                measurement_l.name, measurement_r.name,
            )
            logger.info(
                "REW L/R measurements selected: L=%s, R=%s",
                measurement_l.name,
                measurement_r.name,
            )
        else:
            measurement = result
            self._primary_workflows.get_rew_filters(measurement.uuid, measurement.name)
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
        if isinstance(exc, EmptyPresetFiltersError):
            return str(exc)
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

    def _run_profile_action(
        self, action: Callable[[], object], success_message: str, failure_verb: str
    ) -> None:
        """Run a synchronous ProfileRepository action, showing success/error
        feedback.

        Shared by MyPresetsView's rename/duplicate/delete handlers and the
        save-to-presets flow -- these are local-disk I/O, not network calls,
        so they don't need the async bridge/dispatch pattern used elsewhere;
        this only consolidates the repeated try/except/refresh/banner shape.

        Args:
            action: Zero-arg callable performing the repository write (and
                anything that must only happen on success, e.g. logging).
            success_message: Shown in the status banner on success.
            failure_verb: Prefixes the error banner, e.g. "Rename failed: {exc}".
        """
        try:
            action()
            self._refresh_presets_view()
            self._status_banner.show_success(success_message)
        except Exception as exc:
            self._status_banner.show_error(f"{failure_verb} failed: {exc}")

    def _save_filters_to_presets(
        self, name: str, filters: list[CanonicalFilter], channel_mode: str | ChannelMode
    ) -> None:
        """Save filters to local profile repository (shared by all save triggers).

        Sanitizes the name for filesystem safety, constructs a Profile with
        correct channel mode, persists it, and refreshes the MyPresetsView.

        Args:
            name: Desired preset name (will be sanitized for filesystem and
                for the WiiM device naming rule, since any local preset can
                later be pushed to a device).
            filters: Combined filter list from wizard state.
            channel_mode: Channel mode (ChannelMode enum or legacy string).
        """
        state = self._wizard_controller.state
        name = sanitize_device_name(name).strip()
        profile = build_profile(
            name, filters, channel_mode,
            filters_l=state.filters_l,
            filters_r=state.filters_r,
        )

        def _save() -> None:
            self._profile_repository.save(profile)
            logger.info("Saved preset: %s (%s)", profile.name, channel_mode)

        self._run_profile_action(
            _save, f"Saved '{profile.name}' to My Presets", "Save"
        )

    def _refresh_presets_view(self) -> None:
        """Refresh MyPresetsView from the profile repository."""
        all_profiles = self._profile_repository.list_all()
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
            source = state.selected_source or DEFAULT_SOURCE
            default_name = self._device_prefixed_name(source)

            paths = ExportDialog.get_paths(
                channel_mode="lr",
                default_name=default_name,
                default_dir=self._settings.rew_folder,
                parent=self,
            )
            if paths is None:
                logger.debug("L/R export cancelled by user")
                return

            assert isinstance(paths, tuple)
            path_l, path_r = paths
            # Use stored L/R lists; fallback only for defensive safety
            state = self._wizard_controller.state
            filters_l, filters_r = get_lr_filters(state)

            self._primary_workflows.export_file_lr(filters_l, filters_r, path_l, path_r)
            logger.info("Export L/R REW: %s, %s", path_l, path_r)
        else:
            # Stereo mode: single file dialog
            state = self._wizard_controller.state
            default_name = self._device_prefixed_name(state.selected_source or DEFAULT_SOURCE)
            default_dir = self._settings.rew_folder or str(Path.home())
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Export REW EQ File",
                str(Path(default_dir) / f"{default_name}.txt"),
                "REW EQ Files (*.txt)",
            )
            if not path:
                logger.debug("Export cancelled by user")
                return

            # Ensure .txt extension
            if not path.lower().endswith(".txt"):
                path += ".txt"

            self._primary_workflows.export_file(filters, path)
            logger.info("Export REW: %s", path)

    # ------------------------------------------------------------------
    # Async operation coroutines (Req 1.1-1.7, 2.1-2.7)
    # ------------------------------------------------------------------

    # _do_discovery, _do_probe, _do_file_import, _do_file_import_lr,
    # _do_device_pull, _do_roomfit_pull, _do_load_peq_preset, _do_export,
    # _do_export_lr moved to PrimaryWorkflowManager
    # (src/gui/primary_workflows.py) — docs/backlog.md item 2, Phases 1-2.
    # Dispatch from _on_refresh_requested/_on_device_selected/
    # _on_file_import_requested/_on_file_import_lr_requested/
    # _on_device_pull_requested/_on_roomfit_profile_selected/
    # _on_preset_load_into_editor/_export_filters_as_rew now calls the
    # manager directly.

    async def _read_preset_to_copy(
        self, preset_name: str, preset_type: str
    ) -> tuple[list[CanonicalFilter], ChannelMode, PEQSettings] | None:
        """Read+preview a preset from the currently connected (source) device.

        Shared by both copy flows so the read/preview -- which briefly loads
        the preset onto the source device's live DSP and restores it after,
        see #166 -- happens exactly once per preset, not once per target
        device it's copied to (#171).

        Returns None (after showing an error banner) if the preset has no
        filters to copy.
        """
        assert self._wiim_adapter is not None
        source_name = self._wizard_controller.state.primary_source

        # Reading (previewing + restoring) -- the confirmation dialog in
        # _on_copy_to_device_requested already warned the user this briefly
        # changes what's playing, see #166.
        peq_settings = await read_preset_preview(
            self._wiim_adapter, preset_type, source_name, preset_name
        )
        filters, channel_mode = extract_filters(peq_settings)

        if not filters:
            self._status_banner.show_error(
                f"Preset '{preset_name}' has no filters to copy"
            )
            return None

        return filters, channel_mode, peq_settings

    async def _do_copy_preset_to_device(
        self,
        preset_name: str,
        preset_type: str,
        target_ip: str,
        target_source: str,
        filters: list[CanonicalFilter],
        channel_mode: ChannelMode,
        peq_settings: PEQSettings,
    ) -> None:
        """Write an already-read preset to a target device, as a named preset.

        1. Connects to target device
        2. Writes + verifies (SafeWrite/RoomFitSafeWrite)
        3. Saves as a named preset (same name) on the target device

        The read/preview step happens once, earlier, via
        _read_preset_to_copy() -- shared across every target device this
        preset is being copied to (#171).

        Args:
            preset_name: Name of the preset/profile to copy.
            preset_type: "PEQ" or "RoomFit".
            target_ip: IP address of the target device.
            target_source: Target source name on the remote device.
            filters: Filters read from the source preset (see _read_preset_to_copy).
            channel_mode: Channel mode of the source preset.
            peq_settings: Full PEQSettings read from the source preset (carries
                bands_l/bands_r for L/R mode).
        """
        # Connect to target device and save as named preset
        target_client = self._wiim_http_client_factory(target_ip)
        try:
            target_caps = await self._capability_prober_factory(target_client).probe()
            target_adapter = self._wiim_adapter_factory(target_client, target_caps)

            if preset_type == "RoomFit":
                # RoomFit: write as RoomFit profile on target (smoke #34, #79),
                # verified and rolled back on mismatch via RoomFitSafeWrite --
                # same protocol as the main Push flow (smoke #153), not a bare
                # write_roomfit() with no verification at all.
                roomfit_safe_write = RoomFitSafeWrite(target_adapter, self._backup_manager)
                if is_lr_mode(channel_mode):
                    # Use the L/R bands just read from the source preset —
                    # not wizard state, which may be stale or unrelated to
                    # this preset (e.g. never populated in this session).
                    result = await roomfit_safe_write.execute(
                        target_source, preset_name, filters,
                        channel_mode=ChannelMode.LR,
                        filters_l=peq_settings.bands_l,
                        filters_r=peq_settings.bands_r,
                    )
                else:
                    result = await roomfit_safe_write.execute(
                        target_source, preset_name, filters,
                        channel_mode=ChannelMode.STEREO,
                    )
                if not result.success:
                    raise RuntimeError(
                        result.error_message or "RoomFit copy verification failed"
                    )
            else:
                # PEQ: write filters (verified via SafeWrite, smoke #153), then
                # save as named PEQ preset -- only if the write actually verified.
                settings = build_peq_settings(
                    target_source, filters, channel_mode,
                    filters_l=peq_settings.bands_l,
                    filters_r=peq_settings.bands_r,
                )
                safe_write = SafeWrite(target_adapter, self._backup_manager)
                result = await safe_write.execute(target_source, settings)
                if not result.success:
                    raise RuntimeError(
                        result.error_message or "PEQ copy verification failed"
                    )
                await target_adapter.save_peq_profile(
                    target_source, preset_name
                )

            self._status_banner.show_success(
                f"Preset '{preset_name}' saved to {target_ip} on source '{target_source}'"
            )
        finally:
            await target_client.close()

    async def _write_preset_copies_to_devices(
        self,
        reads: list[tuple[str, str, list[CanonicalFilter], ChannelMode, PEQSettings]],
        target_devices: list[DeviceInfo],
        target_source: str,
    ) -> tuple[int, int]:
        """Write each already-read preset to every target device.

        Shared by `_do_copy_presets_batch_multi` (reads come from the live
        source device) and `_do_copy_local_profile_to_devices` (reads come
        from a locally saved Profile, no source device involved) -- both
        write via the identical `_do_copy_preset_to_device` primitive per
        (read, device) pair, so that loop/exception-handling/progress-emit
        logic lives exactly once.

        Args:
            reads: List of (preset_name, preset_type, filters, channel_mode,
                peq_settings) tuples, one per already-read preset.
            target_devices: List of discovered device objects to copy to.
            target_source: Target source name on each remote device.

        Returns:
            Tuple of (succeeded, failed) copy-operation counts.
        """
        succeeded = 0
        failed = 0

        for preset_name, preset_type, filters, channel_mode, peq_settings in reads:
            for device in target_devices:
                self._bridge.progress_update.emit(
                    f"Copying '{preset_name}' to {device.name}..."
                )
                try:
                    await self._do_copy_preset_to_device(
                        preset_name, preset_type, device.ip, target_source,
                        filters, channel_mode, peq_settings,
                    )
                    succeeded += 1
                except Exception:
                    logger.exception(
                        "Copy preset '%s' to %s failed", preset_name, device.ip
                    )
                    failed += 1

        return succeeded, failed

    async def _do_copy_presets_batch_multi(
        self,
        items: list[Any],
        target_devices: list[DeviceInfo],
        target_source: str,
    ) -> None:
        """Copy presets to multiple target devices (smoke #73 fix).

        Iterates over all presets, reading (and previewing) each once from the
        source device, then writes that single read to every target device.
        Presets are the outer loop and devices the inner loop specifically so
        the read/preview step -- which briefly flips the source device's live
        audio, see #166 -- happens once per preset rather than once per
        (preset, device) pair (#171).

        Args:
            items: List of PresetItem objects to copy.
            target_devices: List of discovered device objects to copy to.
            target_source: Target source name on each remote device.
        """
        reads: list[tuple[str, str, list[CanonicalFilter], ChannelMode, PEQSettings]] = []
        read_failed = 0

        for item in items:
            preset_name = getattr(item, "name", "")
            preset_type = getattr(item, "preset_type", "PEQ")
            if not preset_name:
                continue

            self._bridge.progress_update.emit(f"Reading '{preset_name}'...")
            try:
                read_result = await self._read_preset_to_copy(preset_name, preset_type)
            except Exception:
                logger.exception("Read preset '%s' for copy failed", preset_name)
                self._bridge.progress_update.emit(
                    f"Failed to read '{preset_name}' -- skipping"
                )
                read_failed += len(target_devices)
                continue
            if read_result is None:
                read_failed += len(target_devices)
                continue
            filters, channel_mode, peq_settings = read_result
            reads.append((preset_name, preset_type, filters, channel_mode, peq_settings))

        succeeded, write_failed = await self._write_preset_copies_to_devices(
            reads, target_devices, target_source
        )
        failed = read_failed + write_failed

        # Show summary result
        n_items = len(items)
        n_devices = len(target_devices)
        total_ops = n_items * n_devices
        if failed == 0:
            self._status_banner.show_success(
                f"{n_items} preset(s) copied to {n_devices} device(s)"
            )
        else:
            self._status_banner.show_error(
                f"Copied {succeeded} of {total_ops} operations ({failed} failed)"
            )

    async def _do_copy_local_profile_to_devices(
        self,
        profile_name: str,
        preset_type: str,
        target_devices: list[DeviceInfo],
        target_source: str,
        filters: list[CanonicalFilter],
        channel_mode: ChannelMode,
        peq_settings: PEQSettings,
    ) -> None:
        """Copy a locally saved profile's already-in-hand filters to devices.

        Unlike `_do_copy_presets_batch_multi`, there's no source device to
        read from -- the filters already came from a local Profile -- so
        this is a single-entry `reads` list around the same shared
        `_write_preset_copies_to_devices` write primitive.

        Args:
            profile_name: Name of the local profile being copied.
            preset_type: "PEQ" or "RoomFit", chosen via PresetTypeDialog.
            target_devices: List of discovered device objects to copy to.
            target_source: Target source name on each remote device.
            filters: Filters from the local Profile.
            channel_mode: Channel mode of the local Profile.
            peq_settings: Full PEQSettings built from the local Profile.
        """
        reads = [(profile_name, preset_type, filters, channel_mode, peq_settings)]
        succeeded, failed = await self._write_preset_copies_to_devices(
            reads, target_devices, target_source
        )

        n_devices = len(target_devices)
        if failed == 0:
            self._status_banner.show_success(
                f"'{profile_name}' copied to {n_devices} device(s)"
            )
        else:
            self._status_banner.show_error(
                f"Copied to {succeeded} of {n_devices} device(s) ({failed} failed)"
            )

    # _do_delete_presets moved to PrimaryWorkflowManager
    # (src/gui/primary_workflows.py) — docs/backlog.md item 2, Phase 5.
    # Dispatch from _on_preset_delete_requested now calls the manager
    # directly; results arrive via presets_delete_complete, see
    # _on_presets_delete_complete.

    # _do_preset_export, _do_preset_save, _do_rew_list_measurements,
    # _do_rew_get_filters, _do_rew_get_filters_lr moved to
    # PrimaryWorkflowManager (src/gui/primary_workflows.py) —
    # docs/backlog.md item 2, Phase 3. Dispatch from
    # _on_preset_export_requested/_on_preset_save_requested/
    # _on_rew_api_pull_requested/_on_rew_pull_requested/
    # _dispatch_measurement_selection now calls the manager directly.

    async def _do_push(self) -> None:
        """Execute push to device — PEQ via SafeWrite, or RoomFit via write_roomfit.

        For PEQ flow: constructs PEQSettings and uses SafeWrite protocol.
        Pushes to ALL selected sources (state.selected_sources).
        For RoomFit flow: uses write_roomfit with the named profile.

        Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
        """
        # Safety net: never write to device in dry-run mode
        if self._wizard_controller.state.dry_run:
            logger.warning("_do_push called in dry-run mode — aborting write")
            return

        assert self._wiim_adapter is not None

        state = self._wizard_controller.state
        filters = state.current_filters
        channel_mode = state.channel_mode
        flow_type = self._wizard_controller.flow_type

        # The push flow is the one deliberately multi-source operation:
        # one write per selected source. Empty selection falls back to the
        # single default source (#194).
        source_list = state.selected_sources or [state.primary_source]

        logger.info(
            "Push initiated: flow=%s, channel=%s, filters=%d, sources=%s",
            flow_type.value, channel_mode.value, len(filters), source_list,
        )

        on_stage = self._bridge.stage_changed.emit

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

            assert self._roomfit_safe_write is not None
            try:
                self._bridge.progress_update.emit(
                    f"Writing RoomFit profile '{profile_name}'..."
                )
                if channel_mode.is_lr:
                    # Use stored L/R lists if available (avoids naive 50/50 split)
                    left, right = get_lr_filters(state)
                    result = await self._roomfit_safe_write.execute(
                        source_name,
                        profile_name,
                        filters,
                        channel_mode=ChannelMode.LR,
                        filters_l=left,
                        filters_r=right,
                        on_stage=on_stage,
                    )
                else:
                    result = await self._roomfit_safe_write.execute(
                        source_name,
                        profile_name,
                        filters,
                        channel_mode=ChannelMode.STEREO,
                        on_stage=on_stage,
                    )

                if result.success:
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
                    self._bridge.push_round_changed.emit(
                        source_name, i + 1, len(source_list)
                    )

                settings = build_peq_settings(
                    source_name, filters, channel_mode,
                    filters_l=state.filters_l,
                    filters_r=state.filters_r,
                )
                result = await self._safe_write.execute(source_name, settings, on_stage=on_stage)
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
                    # Same filters/channel_mode were pushed to every source
                    # in this loop, so the last source's read-back is
                    # representative of what's now on every one of them.
                    read_back=last_result.read_back,
                )
                self._bridge.write_complete.emit(result)

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
        self._primary_workflows.list_presets()

    def _populate_name_profile_page(self) -> None:
        """Fetch RoomFit profile names and populate NameProfilePage list.

        Called when the wizard navigates to the NAME_PROFILE step.
        """
        if self._wiim_adapter is None:
            self._name_profile_page.set_existing_profiles([])
            return

        self._primary_workflows.populate_name_profiles()

    # _do_populate_name_profiles, _do_list_roomfit_profiles moved to
    # PrimaryWorkflowManager (src/gui/primary_workflows.py) —
    # docs/backlog.md item 2, Phase 4. Dispatch from
    # _populate_name_profile_page/_on_eq_type_selected now calls the
    # manager directly; results arrive via name_profiles_ready/
    # filters_roomfit_profiles_ready, see _on_name_profiles_ready/
    # _on_filters_roomfit_profiles_ready.

    # _read_active_name_or_default, _do_list_presets, _peq_name_for_highlight,
    # _roomfit_name_for_highlight moved to PrimaryWorkflowManager
    # (src/gui/primary_workflows.py) as refresh_presets() and its helpers —
    # docs/backlog.md item 3, Phase 1b. See _on_peq_presets_ready /
    # _on_peq_presets_unavailable / _on_roomfit_profiles_ready /
    # _on_roomfit_profiles_hidden below for the thin pass-through into
    # PresetsDeviceView that replaced this method's direct widget writes.

    @Slot(list, str)
    def _on_peq_presets_ready(self, items: list[Any], active_name: str) -> None:
        """Forward PrimaryWorkflowManager.peq_presets_ready into the view."""
        self._presets_device_view.set_peq_presets(items, active_name)

    @Slot()
    def _on_peq_presets_unavailable(self) -> None:
        """Forward PrimaryWorkflowManager.peq_presets_unavailable into the view."""
        self._presets_device_view.set_peq_unavailable()

    @Slot(list, str)
    def _on_roomfit_profiles_ready(self, items: list[Any], active_name: str) -> None:
        """Forward PrimaryWorkflowManager.roomfit_profiles_ready into the view."""
        self._presets_device_view.set_roomfit_profiles(items, active_name)

    @Slot()
    def _on_roomfit_profiles_hidden(self) -> None:
        """Forward PrimaryWorkflowManager.roomfit_profiles_hidden into the view."""
        self._presets_device_view.set_roomfit_hidden()

    @Slot(list, str, bool)
    def _on_name_profiles_ready(
        self, profile_names: list[str], active_profile: str, roomfit_enabled: bool
    ) -> None:
        """Forward PrimaryWorkflowManager.name_profiles_ready into NameProfilePage."""
        self._name_profile_page.set_existing_profiles(profile_names, active_profile)
        self._roomfit_enabled = roomfit_enabled

    @Slot(list)
    def _on_filters_roomfit_profiles_ready(self, profile_names: list[str]) -> None:
        """Forward PrimaryWorkflowManager.filters_roomfit_profiles_ready into FiltersPage."""
        self._filters_page.set_roomfit_profiles(profile_names)

    @Slot(int, int)
    def _on_presets_delete_complete(self, succeeded: int, failed: int) -> None:
        """Forward PrimaryWorkflowManager.presets_delete_complete into the status banner."""
        if failed == 0:
            self._status_banner.show_success(f"{succeeded} preset(s) deleted")
        else:
            self._status_banner.show_error(f"Deleted {succeeded}, {failed} failed")

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
            response = await self._wiim_adapter.raw_command(command)
            # Format the response as JSON if possible
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
        self._primary_workflows.list_rew_measurements()

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
        6. Seed FiltersPage's default REW import browse folder
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
        self._populate_settings_view()

        # 6. Seed the Filters step's REW import browse dialogs with the
        # configured default folder (Req 24.11); the page remembers whatever
        # the user navigates to for the rest of the session on top of this.
        self._filters_page.set_default_import_folder(self._settings.rew_folder)

    def _populate_settings_view(self) -> None:
        """Push current AppSettings values into SettingsView's controls.

        SettingsView.set_settings() repopulates every field from the dict
        passed in (no "keep current value" fallback), so it can never be
        called with a partial dict -- always route through this helper
        (called from _apply_settings() at startup and again after any
        settings change made outside the Settings view itself, e.g. the
        Dry Run default toggle prompt) so all fields stay in sync.
        """
        log_dir = self._settings.log_directory or str(get_log_dir())
        presets_dir = (
            self._settings.presets_directory or str(self._profile_repository.storage_root)
        )
        self._settings_view.set_settings({
            "theme": self._settings.theme,
            "log_directory": log_dir,
            "presets_directory": presets_dir,
            "rew_folder": self._settings.rew_folder,
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
        self._settings.rew_folder = settings_dict.get(
            "rew_folder", self._settings.rew_folder
        )
        self._settings.discovery_timeout = settings_dict.get(
            "discovery_timeout", self._settings.discovery_timeout
        )
        self._settings.dry_run_default = settings_dict.get(
            "dry_run_default", self._settings.dry_run_default
        )
        self._settings.save()
        self._filters_page.set_default_import_folder(self._settings.rew_folder)

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
        # Route through the controller (not a direct setCurrentIndex) so
        # Connect's re-entry invalidates completed_steps for Connect and
        # every step after it in the sequence -- otherwise later steps stay
        # checked with stale context while Connect alone shows uncompleted,
        # breaking the "no checked step may follow an unchecked one"
        # invariant (docs/smoke_test_issues.md).
        self._wizard_controller.go_to_step(WizardStep.CONNECT)

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
            "<li>Import/export REW EQ text files, or pull live from REW's HTTP API</li>"
            "<li>Read/write PEQ (per-source) and RoomFit (whole-device) filters "
            "via WiiM HTTP API, gated by detected device capabilities</li>"
            "<li>Stereo and L/R channel mode support</li>"
            "<li>Local preset library with backup and undo</li>"
            "<li>Multi-source and multi-device operations</li>"
            "<li>Backup &rarr; write &rarr; verify, with automatic rollback "
            "on every device write</li>"
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
        """Handle Ctrl+R — trigger device refresh/discovery.

        Delegates to _on_refresh_requested (the same handler the Connect
        page's Retry/rescan buttons use) so all three paths actually
        re-trigger discovery instead of only toggling the scanning UI state.
        """
        self._on_refresh_requested()
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
    # Primary Workflows — presets_ready signal wiring (Phase 1b)
    # ------------------------------------------------------------------

    def _setup_primary_workflows(self) -> None:
        """Wire PrimaryWorkflowManager's view-bound signals to their widgets.

        The manager itself is constructed and configured earlier, in
        __init__, right after WizardController (discover/probe/import_file
        need no view wiring at all — they emit through AsyncBridge's
        existing signals, already connected elsewhere). This method connects
        the four signals refresh_presets() added in Phase 1b, the two
        RoomFit-dropdown signals added in Phase 4, and the delete-presets
        completion signal added in Phase 5.
        """
        self._primary_workflows.peq_presets_ready.connect(self._on_peq_presets_ready)
        self._primary_workflows.peq_presets_unavailable.connect(
            self._on_peq_presets_unavailable
        )
        self._primary_workflows.roomfit_profiles_ready.connect(
            self._on_roomfit_profiles_ready
        )
        self._primary_workflows.roomfit_profiles_hidden.connect(
            self._on_roomfit_profiles_hidden
        )
        self._primary_workflows.name_profiles_ready.connect(
            self._on_name_profiles_ready
        )
        self._primary_workflows.filters_roomfit_profiles_ready.connect(
            self._on_filters_roomfit_profiles_ready
        )
        self._primary_workflows.presets_delete_complete.connect(
            self._on_presets_delete_complete
        )

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
        self._presets_device_view.delete_requested.connect(
            self._on_preset_delete_requested
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
        self._my_presets_view.copy_to_device_requested.connect(
            self._on_local_preset_copy_to_device_requested
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
        self._diagnostics_panel.source_slots_requested.connect(
            self._secondary_workflows.fetch_source_slots
        )

        # --- Outbound: workflow manager signals → UI updates ---
        self._secondary_workflows.profile_recalled.connect(
            self._on_profile_recalled
        )
        self._secondary_workflows.undo_complete.connect(
            self._on_undo_complete
        )
        self._secondary_workflows.source_slots_ready.connect(
            self._diagnostics_panel.on_source_slots_ready
        )
        self._secondary_workflows.source_slots_error.connect(
            self._diagnostics_panel.on_source_slots_error
        )

    # --- Inbound handlers (page/view → workflow trigger) ---

    @Slot(list)
    def _on_copy_to_device_requested(self, items: list[Any]) -> None:
        """Handle PresetsDeviceView "Copy to Another Device" action.

        Opens a device picker (with the source-read and target-write
        warnings folded into it as a single combined dialog, instead of two
        separate confirmations shown beforehand) for the target device
        selection, then executes _do_copy_presets_batch_multi for each
        selected item.

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
        if not self._primary_workflows.discovered_devices:
            self._status_banner.show_error("No other devices discovered")
            return

        preview_body = self._preset_preview_warning_html(items)
        activation_body = self._copy_activation_warning_html(items)
        bodies = [b for b in (preview_body, activation_body) if b]
        warning = (
            ("This Will Change Device State", "<br><br>".join(bodies))
            if bodies
            else None
        )

        # Open device picker dialog for target device selection, with the
        # combined warning embedded above the list
        selected_devices = DevicePickerDialog.get_devices(
            self, self._primary_workflows.discovered_devices, current_ip, warning
        )

        # User cancelled the dialog
        if selected_devices is None:
            return

        # Copy to ALL selected devices (smoke #73 — was using only first device)
        # Single source only: the target of a preset copy is one source slot on
        # each remote device, never the local multi-select push fan-out (#194).
        target_source = state.primary_source

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
                    items, selected_devices, target_source
                ),
            )
        )

    @Slot(object)
    def _on_local_preset_copy_to_device_requested(self, profile: object) -> None:
        """Handle MyPresetsView "Copy to Another Device" action.

        A locally saved Profile carries no record of whether it originated
        as a PEQ preset or a RoomFit profile (see build_profile /
        Profile in src/models/profile.py), so unlike the device-to-device
        copy flow, this asks the user which target write-mode to use before
        picking devices. There's also no live source device to read from
        here -- the filters are already in hand -- so there's no source-read
        warning to show; the target-write warning (identical concern to the
        device-to-device flow) is folded into the device picker dialog once
        the type is known, instead of shown as a separate confirmation step.

        Args:
            profile: Profile object selected in My Saved Presets.
        """
        if not self._primary_workflows.discovered_devices:
            self._status_banner.show_error("No other devices discovered")
            return

        preset_type = PresetTypeDialog.get_type(self)
        if preset_type is None:
            return

        from src.gui.views.presets_device_view import PresetItem

        name: str = getattr(profile, "name", "")
        channel_mode_value = getattr(profile, "channel_mode", ChannelMode.STEREO)
        filters_value = getattr(profile, "filters", None)
        filters_l_value = getattr(profile, "filters_l", None)
        filters_r_value = getattr(profile, "filters_r", None)

        preview_item = PresetItem(
            name=name,
            channel_mode=channel_mode_value.display_value,
            preset_type=preset_type,
        )
        activation_body = self._copy_activation_warning_html([preview_item])
        warning = (
            ("Copy Will Change Target Device(s)", activation_body)
            if activation_body
            else None
        )

        selected_devices = DevicePickerDialog.get_devices(
            self, self._primary_workflows.discovered_devices, "", warning
        )
        if selected_devices is None:
            return

        state = self._wizard_controller.state
        target_source = state.primary_source

        peq_settings = build_peq_settings(
            target_source,
            filters_value or [],
            channel_mode_value,
            filters_l=filters_l_value,
            filters_r=filters_r_value,
        )
        filters, channel_mode = extract_filters(peq_settings)

        logger.info(
            "Copy local preset '%s' (%s) to %d device(s)",
            name, preset_type, len(selected_devices),
        )

        self._bridge.run_async(
            self._bridge_wrapper(
                "copy_local_preset_to_devices",
                self._do_copy_local_profile_to_devices(
                    name, preset_type, selected_devices, target_source,
                    filters, channel_mode, peq_settings,
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
        source = state.selected_source or DEFAULT_SOURCE
        channel = state.channel_mode
        preset_name = self._device_prefixed_name(f"{source} ({channel.display_value})")

        self._save_filters_to_presets(preset_name, filters, channel)

    @Slot(str, str)
    def _on_profile_rename_requested(self, old_name: str, new_name: str) -> None:
        """Handle MyPresetsView rename action."""
        self._run_profile_action(
            lambda: self._profile_repository.rename(old_name, new_name),
            f"Renamed '{old_name}' to '{new_name}'",
            "Rename",
        )

    @Slot(str)
    def _on_profile_duplicate_requested(self, name: str) -> None:
        """Handle MyPresetsView duplicate action."""
        new_name = sanitize_device_name(f"{name} (copy)").strip()
        self._run_profile_action(
            lambda: self._profile_repository.duplicate(name, new_name),
            f"Duplicated '{name}'",
            "Duplicate",
        )

    @Slot(str)
    def _on_profile_delete_requested(self, name: str) -> None:
        """Handle MyPresetsView delete action.

        Confirms before deleting, matching the equivalent safety check on
        the device-side preset delete (`_on_preset_delete_requested`) --
        this one is a local, in-app-storage deletion, not a device write.
        """
        if not self._confirm_action(
            "Delete Preset?",
            f"Permanently delete '{name}' from My Presets?\n\nThis cannot be undone.",
        ):
            return

        self._run_profile_action(
            lambda: self._profile_repository.delete(name),
            f"Deleted '{name}'",
            "Delete",
        )

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

        if not self._confirm_preset_preview(items):
            return

        item = items[0]
        preset_name = getattr(item, "name", "")
        preset_type = getattr(item, "preset_type", "PEQ")
        channel_mode = getattr(item, "channel_mode", "Stereo")

        # Device-prefixed only for the destination filename -- preset_name
        # itself stays exactly as the device reports it, since it's also the
        # on-device lookup key passed to PrimaryWorkflowManager.export_preset below.
        export_default_name = self._device_prefixed_name(preset_name)

        # Use the same dialog pattern as ReviewPage export
        if is_lr_mode(channel_mode):
            from src.gui.dialogs.export_dialog import ExportDialog

            paths = ExportDialog.get_paths(
                channel_mode="lr",
                default_name=export_default_name,
                default_dir=self._settings.rew_folder,
                parent=self,
            )
            if paths is None:
                logger.debug("L/R preset export cancelled")
                return
            # Pass base path (first path's stem without _L suffix)
            assert isinstance(paths, tuple)
            path_l, _path_r = paths
            # Use the left path — _do_preset_export (on PrimaryWorkflowManager)
            # handles L/R splitting internally
            export_path = str(path_l.parent / path_l.stem.replace("_L", "")) + ".txt"
        else:
            default_dir = self._settings.rew_folder or str(Path.home())
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Export Preset as REW File",
                str(Path(default_dir) / f"{export_default_name}.txt"),
                "REW EQ Files (*.txt)",
            )
            if not path:
                logger.debug("Preset export cancelled")
                return
            if not path.lower().endswith(".txt"):
                path += ".txt"
            export_path = path

        self._status_banner.show_progress(f"Exporting '{preset_name}'...")
        self._primary_workflows.export_preset(preset_name, preset_type, export_path)
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

        if not self._confirm_preset_preview(items):
            return

        item = items[0]
        preset_name = getattr(item, "name", "")
        preset_type = getattr(item, "preset_type", "PEQ")
        # Device-prefixed only for the locally-saved Profile's name --
        # preset_name itself stays exactly as the device reports it, since
        # it's also the on-device lookup key _do_preset_save reads with.
        saved_name = self._device_prefixed_name(preset_name)
        self._status_banner.show_progress(f"Saving '{preset_name}' to My Presets...")
        self._primary_workflows.save_preset(preset_name, preset_type, saved_name)
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

        # Check if wizard state is complete enough to load. The read-preview
        # warning is passed through so it's folded into QuickSetupDialog when
        # that dialog is about to show, instead of confirmed as a separate
        # step beforehand (only shown standalone when nothing else is
        # missing, matching today's single-dialog behavior for that case).
        if not self._ensure_wizard_state_for_load(preview_items=[item]):
            return

        # Set flag so _on_peq_ready navigates directly to Review (smoke #87)
        self._sidebar_load_in_progress = True
        self._status_banner.show_progress(f"Loading preset '{name}'...")
        if preset_type == "RoomFit":
            self._primary_workflows.pull_roomfit(name, operation_name="load_preset")
        else:
            # PEQ preset: load it via EQv2SourceLoad then read
            self._primary_workflows.load_peq_preset(name)
        logger.info("Preset load into editor: %s (type=%s)", name, preset_type)

    def _format_preset_names(self, items: list[Any]) -> str:
        """Bullet-list "Name (Type)" for each item, shared by every preset
        confirmation dialog (delete, preview-activation)."""
        return "\n".join(
            f"• {getattr(i, 'name', '')} ({getattr(i, 'preset_type', 'PEQ')})"
            for i in items
        )

    def _html_bullet_list(self, items: list[Any]) -> str:
        """HTML-safe bullet list for a confirmation dialog body.

        Preset names come from the device, not a trusted local source --
        escape before embedding in an HTML-flavored message (Qt auto-detects
        rich text from <br>/<b> tags), and swap _format_preset_names()'s
        \\n-joined separators for <br> since raw newlines aren't rendered as
        line breaks in HTML.
        """
        return html.escape(self._format_preset_names(items)).replace("\n", "<br>")

    def _confirm_action(
        self, title: str, message: str, *, rich_text: bool = False
    ) -> bool:
        """Shared Yes/No confirmation dialog, default button No.

        Uses the same styled yellow warning-box treatment as
        DevicePickerDialog/QuickSetupDialog, rather than a plain
        QMessageBox, so every "this will change state" confirmation in the
        app reads consistently.

        Args:
            title: Warning box header text.
            message: Warning body text. Plain text by default; pass
                rich_text=True when message was deliberately built as HTML
                (e.g. via _html_bullet_list(), which already escapes any
                dynamic values before embedding them).
            rich_text: Whether `message` should be interpreted as HTML.
        """
        from src.gui.dialogs.warning_confirm_dialog import WarningConfirmDialog

        return WarningConfirmDialog.confirm(self, title, message, rich_text=rich_text)

    def _preset_preview_warning_html(self, items: list[Any]) -> str | None:
        """Build the warning body for `_confirm_preset_preview()` (below), and
        for `DevicePickerDialog`'s embedded warning in the copy-to-device
        flow. Returns None when there's nothing to warn about (all-RoomFit
        selection) -- see `_confirm_preset_preview()`'s docstring for why
        RoomFit is excluded.
        """
        peq_items = [i for i in items if getattr(i, "preset_type", "PEQ") != "RoomFit"]
        if not peq_items:
            return None
        names_html = self._html_bullet_list(peq_items)
        return (
            f"Reading the filters in: <br><b>{names_html}</b>"
            "<br>preset will temporarily enable it on your device's current input. The "
            "original filters will be restored after the read completes."
        )

    def _confirm_preset_preview(self, items: list[Any]) -> bool:
        """Warn that reading these PEQ presets' filters will briefly change what's
        playing on the device (#166). RoomFit items are excluded -- RoomFit's
        API working buffer is claimed to be decoupled from its DSP on/off
        state during a read-only preview (docs/wiim_api_notes.md), but this
        specific claim, unlike the write-side behavior this app now builds
        on, has not been independently re-verified on real hardware and
        shares the same risk pattern as #190's confirmed-wrong assumption
        (`# ASSUMPTION:`). Shared by every read-only preset action (copy,
        export, save-to-My-Presets, load-into-editor) -- only about the
        *source* device's brief read, not any device being written to (see
        `_copy_activation_warning_html()` for Copy-to-Device's separate,
        write-side concern, folded directly into `DevicePickerDialog`
        rather than shown as its own standalone confirm).
        """
        body = self._preset_preview_warning_html(items)
        if body is None:
            return True
        return self._confirm_action(
            "Preset Will Briefly Activate on Device",
            f"{body}<br><br>Continue?",
            rich_text=True,
        )

    def _copy_activation_warning_html(self, items: list[Any]) -> str | None:
        """Build the warning body for `DevicePickerDialog`'s embedded warning
        in both copy-to-device flows -- copying preset(s) makes each one
        active on its target device(s), turning PEQ/RoomFit on there if it's
        off (the same behavior as the main Push flow, applied here for
        consistency since "Copy to Another Device" writes via the identical
        SafeWrite.execute()/RoomFitSafeWrite.execute() paths). Distinct from
        `_preset_preview_warning_html()`, which only concerns the
        source-side read; this concerns the target-side write. Returns None
        when there's nothing to warn about (empty list).

        Covers both preset types in one body rather than a separate builder
        per type: PresetsDeviceView enforces mutual exclusion between its PEQ
        and RoomFit lists (selecting in one clears the other), so `items`
        today only ever contains one type -- but a single shared,
        type-generic builder avoids the "second near-identical text builder"
        drift a bolted-on PEQ-only sibling would repeat, and is already
        correct if that mutual-exclusion constraint is ever relaxed.
        """
        roomfit_items = [i for i in items if getattr(i, "preset_type", "PEQ") == "RoomFit"]
        peq_items = [i for i in items if getattr(i, "preset_type", "PEQ") != "RoomFit"]
        if not roomfit_items and not peq_items:
            return None

        paragraphs = []
        if roomfit_items:
            names_html = self._html_bullet_list(roomfit_items)
            paragraphs.append(
                f"Copying: <br><b>{names_html}</b>"
                "<br>will make it the active RoomFit profile on the target device(s), "
                "turning RoomFit on there if it's currently off."
            )
        if peq_items:
            names_html = self._html_bullet_list(peq_items)
            paragraphs.append(
                f"Copying: <br><b>{names_html}</b>"
                "<br>will make it the active PEQ preset on the target device(s), "
                "turning PEQ on there if it's currently off."
            )

        return "<br><br>".join(paragraphs)

    @Slot(list)
    def _on_preset_delete_requested(self, items: list[Any]) -> None:
        """Handle PresetsDeviceView "Delete" for selected items.

        Confirms with the user before deleting -- this is an irreversible,
        hardware-side removal, unlike the local-library delete on MyPresetsView.

        Args:
            items: List of PresetItem objects selected for deletion.
        """
        if not items:
            return

        if not self._confirm_action(
            "Delete Preset(s)",
            f"Permanently delete the following from the device?\n\n"
            f"{self._format_preset_names(items)}\n\nThis cannot be undone.",
        ):
            return

        self._primary_workflows.delete_presets(items)
        logger.info("Preset delete requested: %s", [getattr(i, "name", "") for i in items])

    # --- Outbound handlers (workflow manager → UI updates) ---

    @Slot(list, str)
    def _on_profile_recalled(
        self, filters: list[CanonicalFilter], profile_name: str = ""
    ) -> None:
        """Handle profile recall — populate ReviewPage and navigate.

        Loads the recalled filters into the wizard state and ReviewPage,
        then navigates to the Review step. Uses L/R display when channel_mode
        was set by _on_profile_load_requested.

        Requirement 17.2: Profile Recall loads into Review step.

        Args:
            filters: List of CanonicalFilter objects from the recalled profile.
            profile_name: Name of the recalled profile, for the Filters step
                tooltip (#162d). Defaults to "" so direct callers passing
                only filters (e.g. existing tests) stay compatible.
        """
        if not filters:
            self._status_banner.show_error("Profile contains no filters")
            return

        # Store filters in wizard state
        state = self._wizard_controller.state
        state.current_filters = filters
        if profile_name:
            state.filters_origin = f"My Presets: {profile_name}"

        # Populate ReviewPage with the recalled filters (L/R aware)
        channel = state.channel_mode
        if channel.is_lr:
            # Use stored L/R lists (set by recall_profile before emitting signal)
            left, right = get_lr_filters(state)
            self._review_page.set_lr_filters(left, right)
        else:
            self._review_page.set_filters(filters)

        active_bands = sum(1 for f in filters if getattr(f, "enabled", True))

        # Navigate to Review step — update both wizard state and stacked widget
        # so that subsequent navigation/step_changed doesn't override (smoke #87)
        self._jump_to_review()

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
        self._push_page.mark_undo_complete(success)
        if success:
            self._clear_pushed_snapshot()
            self._status_banner.show_success(message)
        else:
            self._status_banner.show_error(f"Undo failed: {message}")

    # ------------------------------------------------------------------
    # Quick Setup helper (smoke #87)
    # ------------------------------------------------------------------

    def _ensure_wizard_state_for_load(
        self, preview_items: list[Any] | None = None
    ) -> bool:
        """Check wizard state is complete for loading filters; show dialog if not.

        If no device is connected, shows error and returns False.
        If EQ type or source is missing, shows QuickSetupDialog.
        On cancel, returns False. On confirm, updates wizard state, marks
        EQ_TYPE/SOURCE/FILTERS steps completed, and returns True.

        Args:
            preview_items: Optional preset items to show the read-preview
                warning for (see `_confirm_preset_preview`). When
                QuickSetupDialog is about to be shown, the warning is folded
                into it instead of shown as a separate step beforehand; when
                nothing is missing, it's shown standalone exactly as before
                (only `_on_preset_load_into_editor` passes this -- the other
                two callers have no source-read to warn about).

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
                # Already at or past Filters -- all state is populated
                if preview_items is not None and not self._confirm_preset_preview(
                    preview_items
                ):
                    return False
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
            if preview_items is not None and not self._confirm_preset_preview(
                preview_items
            ):
                return False
            # All prior steps should be marked completed
            self._mark_prior_steps_completed(state)
            return True

        # Show dialog — source list and RoomFit support come from the
        # connected device's (capability-file-merged) capabilities; fall back
        # to the shared generic list (#167b) only when no device/capabilities
        # are available yet (e.g. loading a My Presets profile before ever
        # connecting) -- not a third, independently-drifting UI-widget scrape.
        device_caps = self._device_caps
        available_sources = list(
            getattr(device_caps, "source_names", []) or DEFAULT_SOURCE_NAMES
        )
        supports_roomfit = bool(getattr(device_caps, "supports_roomfit", True))

        current_eq_type = "roomfit" if flow_type == FlowType.ROOMFIT else "peq"
        current_sources = state.selected_sources or None

        warning = None
        if preview_items is not None:
            body = self._preset_preview_warning_html(preview_items)
            if body is not None:
                warning = ("Preset Will Briefly Activate on Device", body)

        result = QuickSetupDialog.get_setup(
            self,
            need_eq_type=need_eq_type,
            need_source=need_source,
            available_sources=available_sources,
            current_eq_type=current_eq_type,
            current_sources=current_sources,
            supports_roomfit=supports_roomfit,
            warning=warning,
        )

        if result is None:
            return False

        eq_type, sources = result

        # Apply EQ type to wizard state
        if need_eq_type:
            self._wizard_controller.set_flow_type(
                FlowType.ROOMFIT if eq_type == "roomfit" else FlowType.PEQ
            )

        # Apply source to wizard state (PEQ only)
        if self._wizard_controller.flow_type != FlowType.ROOMFIT and sources:
            state.selected_sources = list(sources)

        # Delegate to the single shared function that marks CONNECT/EQ_TYPE/
        # SOURCE/FILTERS completed consistently, instead of reimplementing
        # that logic a third time with its own literals (#162) -- EQ_TYPE and
        # SOURCE are genuinely missing from completed_steps at this point
        # (that's why the dialog was shown), so this sets them for the first
        # time rather than skipping them via the "already completed" guard.
        self._mark_prior_steps_completed(state)

        return True

    def _mark_prior_steps_completed(self, state: object) -> None:
        """Mark CONNECT, EQ_TYPE, SOURCE, FILTERS steps as completed if not already.

        Called when all info is already present so the step indicator shows
        proper checkmarks when navigating to Review from sidebar.

        The guard ("only set if not already completed") is right for
        CONNECT/EQ_TYPE/SOURCE, which represent sticky prior decisions that
        genuinely shouldn't change just because this function runs again --
        but wrong for FILTERS, which represents "what's loaded right now"
        and must always reflect current reality. Without recomputing FILTERS
        unconditionally, a repeat "Load into Editor" after the first would
        keep showing the count from whatever was loaded the first time
        (#162d) -- this function runs once before a sidebar load dispatches
        (stale data) and once after it completes (correct data); nothing
        repaints between those two calls, so recomputing both times is safe.
        """
        assert isinstance(state, WizardState)
        flow_type = self._wizard_controller.flow_type

        # CONNECT step — always mark if device is selected
        if WizardStep.CONNECT not in state.completed_steps and state.selected_device:
            state.completed_steps[WizardStep.CONNECT] = self._resolve_connect_summary()

        # EQ_TYPE step — only exists in PEQ and ROOMFIT flows (not PEQ_ONLY)
        if flow_type == FlowType.PEQ and WizardStep.EQ_TYPE not in state.completed_steps:
            state.completed_steps[WizardStep.EQ_TYPE] = _EQ_TYPE_SUMMARY["peq"]
        elif flow_type == FlowType.ROOMFIT and WizardStep.EQ_TYPE not in state.completed_steps:
            state.completed_steps[WizardStep.EQ_TYPE] = _EQ_TYPE_SUMMARY["roomfit"]

        # SOURCE step — only needed for PEQ/PEQ_ONLY flows (not ROOMFIT)
        if flow_type != FlowType.ROOMFIT and WizardStep.SOURCE not in state.completed_steps:
            source = state.selected_source or DEFAULT_SOURCE
            state.selected_source = source
            self._apply_source_summary(state, source)

        # FILTERS step — always recompute, see docstring above.
        n_filters = len(state.current_filters)
        state.completed_steps[WizardStep.FILTERS] = self._resolve_filters_summary(n_filters)
        state.completed_step_tooltips[WizardStep.FILTERS] = state.filters_origin

    def _jump_to_review(self) -> None:
        """Navigate straight to the Review step with indicators filled in.

        Shared by the sidebar-load path (_on_peq_ready) and the profile-load
        completion handler (_on_profile_recalled) -- both need to mark prior
        steps completed, jump the wizard state and stacked widget straight to
        Review, and replay every completed step's summary/tooltip through the
        step indicator (smoke #87), rather than reimplementing that sequence
        at each call site.

        Switching the page fires currentChanged, which _sync_navigation_chrome
        handles centrally (step pill highlight + undim, sidebar reset to
        "home") -- no manual sync needed here.

        Routes through ``go_to_step()`` rather than assigning
        ``state.current_step``/``setCurrentIndex`` directly, so REVIEW and
        anything after it in the sequence (NAME_PROFILE, PUSH) is properly
        invalidated in ``completed_steps`` and its StepIndicator badge
        cleared -- otherwise a stale PUSH/NAME_PROFILE completion left over
        from a previous, unrelated push stays checked while REVIEW itself is
        freshly (re-)entered, violating "no checked step may follow an
        unchecked one" (docs/smoke_test_issues.md #238). This transiently
        clears CONNECT/EQ_TYPE/SOURCE/FILTERS badges too, since they aren't
        back in ``completed_steps`` yet at that point -- but nothing repaints
        before ``_mark_prior_steps_completed`` and the replay loop below
        restore them, same reasoning as the FILTERS-recompute note above.
        """
        state = self._wizard_controller.state
        self._wizard_controller.go_to_step(WizardStep.REVIEW)
        self._mark_prior_steps_completed(state)
        tooltips = state.completed_step_tooltips
        for step, summary in state.completed_steps.items():
            self._wizard_controller.step_summary_updated.emit(
                step, summary, tooltips.get(step, "")
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
            choice: Literal["discard", "cancel"] = UnsavedChangesDialog.confirm_discard(self)
            if choice == "cancel":
                event.ignore()
                return
            # "discard" - proceed with close

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
        # Dirty means filters are loaded AND they don't match the snapshot
        # taken at the last successful push (e.g. never pushed, edited again
        # since, or undone since -- see last_pushed_filters docstring).
        state = self._wizard_controller.state
        return (
            len(state.current_filters) > 0
            and state.current_filters != state.last_pushed_filters
        )

