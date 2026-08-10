"""Main application window — wizard-driven single-pane interface.

Replaces the old splitter-based MainWindow. Serves as the application shell
with SidebarNav, StepIndicator, QStackedWidget content area, StatusBanner,
and a diagnostics dock widget.

Requirements referenced: 14.1, 14.2, 14.4, 14.5, 10.1, 10.6, 24.6,
    10.5, 10.11, 10.12, 10.13, 13.1-13.6, 26.1-26.7.
"""

from __future__ import annotations

import html
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
    QInputDialog,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.adapters.capability_prober import CapabilityProber
from src.adapters.rew_http_client import MeasurementSummary, REWHttpApiClient
from src.adapters.wiim_adapter import WiiMAdapter
from src.adapters.wiim_http import WiiMHttpClient
from src.discovery.discovery_module import DiscoveryModule
from src.gui.adapter_factories import (
    make_capability_prober,
    make_rew_client,
    make_roomfit_safe_write,
    make_safe_write,
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
from src.gui.theme import ThemeManager
from src.gui.views.help_view import HelpView
from src.gui.views.my_presets_view import MyPresetsView
from src.gui.views.presets_device_view import PresetItem, PresetsDeviceView
from src.gui.views.rew_pull_view import RewPullView
from src.gui.views.settings_view import SettingsView
from src.gui.wizard_controller import (
    FiltersSource,
    FlowType,
    WizardController,
    WizardState,
    WizardStep,
    parse_source_list,
)
from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceCapabilities
from src.models.channel_mode import (
    ChannelMode,
    coerce_channel_mode,
    is_lr_mode,
    require_lr_filters,
)
from src.models.constants import DEFAULT_MAX_BANDS, DEFAULT_SOURCE
from src.models.errors import (
    ParseError,
    REWNotConnectedError,
    ValidationError,
    WiiMConnectionError,
    WiiMTimeoutError,
)
from src.models.profile import build_profile
from src.repository.backup_manager import BackupManager, is_multi_source_backup_path
from src.repository.profile_repository import ProfileRepository
from src.utils.app_dirs import get_app_data_dir, get_log_dir
from src.utils.device_name import sanitize_device_name
from src.utils.paths import ensure_suffix
from src.utils.version import get_app_version

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
# sidebar_nav.set_active_key()/step_indicator.setVisible()/set_view()
# call sites scattered across every navigation handler in this class).
_PAGE_INDEX_TO_KEY: dict[int, str] = {v: k for k, v in PAGE_INDICES.items()}
_PAGE_KEY_TO_STEP: dict[str, WizardStep] = {v: k for k, v in _STEP_TO_PAGE_KEY.items()}

# Sidebar destinations that replace the wizard page on screen (as opposed to
# "home", which returns to wherever the wizard currently is, and "help",
# which opens a separate window and never touches the stacked widget).
_SIDEBAR_DESTINATION_KEYS: frozenset[str] = frozenset(
    {"presets_device", "my_presets", "settings"}
)

# Canonical EQ_TYPE step summary wording, used by every entry point that
# completes this step so they never drift independently again (#162).
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
                defaults to the real adapter (make_wiim_adapter). This is
                the same callable passed as `target_adapter_factory` to
                SecondaryWorkflowManager.configure() below -- construction
                is identical for the currently-connecting device and an
                unfamiliar copy-to-device target, so one factory serves
                both.
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
        # Built once, shared by both PrimaryWorkflowManager and
        # SecondaryWorkflowManager's configure() calls below -- avoids
        # defining the same two lambdas twice (branch-quality review,
        # 2026-07-17). Delegates construction to adapter_factories.py, the
        # one file allowed to name these classes directly (mirrors the
        # WiiMAdapter/WiiMHttpClient/CapabilityProber/REWHttpApiClient
        # factories just below).
        self._safe_write_factory = lambda adapter: make_safe_write(
            adapter, self._backup_manager
        )
        self._roomfit_safe_write_factory = lambda adapter: make_roomfit_safe_write(
            adapter, self._backup_manager
        )

        # Lazily created on device selection (Req 14.2, 14.3):
        self._wiim_http_client: WiiMHttpClient | None = None
        self._capability_prober: CapabilityProber | None = None
        self._wiim_adapter: WiiMAdapter | None = None
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

        # Snapshot of (current_filters, filters_l, filters_r, channel_mode)
        # as of the last time the Filters step was completed -- lets
        # _on_filters_accepted() detect an actual change-of-selection the
        # same way _on_source_changed() does for the Source step (see that
        # method), so re-confirming Filters with a *different* filter set
        # after navigating back invalidates the now-stale Review/Push
        # checkmarks instead of leaving them in place (docs/smoke_test_issues.md,
        # QA issue #8). None until the Filters step is completed once.
        self._last_confirmed_filters_signature: tuple[object, ...] | None = None

        # --- Primary workflows (discovery, probing, file import, push) ---
        # Configured eagerly (SecondaryWorkflowManager is configured eagerly
        # too, in _setup_secondary_workflows() below): only push() needs a
        # live device adapter, obtained the same way every other
        # adapter-dependent workflow here does -- set_current_adapter(),
        # once a device is selected and probed (see primary_workflows.py).
        self._primary_workflows = PrimaryWorkflowManager(parent=self)
        self._primary_workflows.configure(
            bridge=self._bridge,
            discovery_module=self._discovery_module,
            wizard_controller=self._wizard_controller,
            bridge_wrapper=self._bridge_wrapper,
            rew_client=self._rew_client,
            profile_repository=self._profile_repository,
            safe_write_factory=self._safe_write_factory,
            roomfit_safe_write_factory=self._roomfit_safe_write_factory,
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
        self._rebuild_step_indicator()

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
        sidebar_nav.set_active_key(), step_indicator.setVisible(), and
        step_indicator.set_view() in the right combination, and several
        of them didn't (hence #138, #142, #144, #147, and the step-pill
        case reported after those: clicking a finished step pill while
        viewing a sidebar destination left both highlighted at once).
        Deriving the correct chrome purely from the page index that just
        became current, in one place wired to currentChanged, means a new
        navigation path can't reintroduce this bug class just by
        forgetting one of those calls — there's nothing left to forget.

        A sidebar destination (Presets on Device, My Saved Presets,
        Settings) has no entry point *into* the wizard of its own — the
        user reaches the wizard again only via the sidebar's "Setup
        Wizard" (home) entry, never by interacting with the breadcrumb —
        so the step indicator is hidden entirely there rather than merely
        dimmed: a still-visible, still-clickable wizard breadcrumb over an
        unrelated page reads as "you're still in the wizard" and wastes
        vertical space that page could use instead. Hiding it also frees
        that row for the QStackedWidget (stretch=1 in the layout), so the
        destination view grows to fill it automatically.
        """
        page_key = _PAGE_INDEX_TO_KEY.get(index)
        if page_key is None:
            return

        if page_key in _SIDEBAR_DESTINATION_KEYS:
            self._sidebar_nav.set_active_key(page_key)
            self._step_indicator.setVisible(False)
            return

        step = _PAGE_KEY_TO_STEP.get(page_key)
        if step is None:
            return

        self._sidebar_nav.set_active_key("home")
        self._step_indicator.setVisible(True)
        sequence = self._wizard_controller.get_steps()
        if step in sequence:
            frontier = self._wizard_controller.frontier_step
            self._step_indicator.set_view(
                sequence.index(step), sequence.index(frontier)
            )

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

        # Tracks whether FiltersPage's embedded RewPullView is currently
        # driving an in-flight REW pull, so late listing results/errors
        # arriving after the user has moved on are ignored rather than
        # resurrecting a stale picker.
        self._active_rew_pull_view: RewPullView | None = None

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
        self._filters_page.device_presets_requested.connect(
            self._on_device_presets_requested
        )
        self._filters_page.local_profiles_requested.connect(
            self._on_local_profiles_requested
        )
        self._filters_page.device_item_selected.connect(self._on_device_item_selected)
        self._filters_page.local_profile_selected.connect(self._on_local_profile_selected)
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
        self._wizard_controller.steps_invalidated.connect(
            self._on_steps_invalidated
        )

        # --- 3. AsyncBridge → handlers ---
        self._bridge.discovery_complete.connect(self._on_discovery_complete)
        self._bridge.discovery_progress.connect(self._on_discovery_progress)
        self._bridge.capabilities_ready.connect(self._on_capabilities_ready)
        self._bridge.peq_ready.connect(self._on_peq_ready)
        self._bridge.write_complete.connect(self._on_write_complete)
        self._bridge.operation_error.connect(self._on_operation_error)
        self._bridge.probe_abandoned.connect(self._on_probe_abandoned)
        self._bridge.discovery_abandoned.connect(self._on_discovery_abandoned)
        self._bridge.rew_list_abandoned.connect(self._on_rew_list_abandoned)
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

        Re-selecting the already-connected device is a no-op past the busy
        check -- nothing about the session is invalid, so prior context
        (filters, source, completed steps) is left untouched and the probe
        still runs (capabilities can change server-side, and the probe is
        cheap and generation-guarded regardless).

        Selecting a *different* device resets flow type and clears
        source/filter/step state so the previous device's context doesn't
        leak (smoke #87 — re-connect should re-ask source; #246 follow-up
        bugs 1b/1c — the field list and step-invalidation are centralized in
        ``WizardState.clear_device_scoped_state()``/``invalidate_from()`` so
        this call site can't drift from them the way the old hand-rolled
        versions did).
        """
        if self._is_busy():
            return

        state = self._wizard_controller.state
        if device_ip != state.selected_device:
            # Switching devices is the one change-time invalidation that
            # destroys real payload (loaded/imported filters), not just
            # step checkmarks -- so it alone warrants a confirmation when
            # unpushed filter work would be lost. Declining aborts the
            # switch entirely (no state change, no adapter swap, no probe).
            if state.selected_device is not None and self._has_unsaved_changes():
                if not self._confirm_action(
                    "Switch device?",
                    "Switching devices clears the filters you have loaded "
                    "and your progress after the Connect step.\n\n"
                    "Push them to the current device first if you want to "
                    "keep them. Switch anyway?",
                ):
                    return
            # This explicit invalidate_after(CONNECT) stays even though
            # set_flow_type() below now invalidates orphaned steps on its
            # own (docs/smoke_test_issues.md #266) -- that only fires when
            # flow_type actually *changes*, but a device switch must
            # invalidate everything after CONNECT regardless, since it's
            # the *device* that's invalid now, not the flow choice (e.g.
            # switching between two RoomFit-capable devices leaves
            # flow_type at PEQ both before and after, so set_flow_type()'s
            # own check would see no change and invalidate nothing). Run
            # using the *old* (pre-switch) flow's sequence, before
            # resetting flow_type below -- a step that only exists in the
            # old flow (e.g. NAME_PROFILE, RoomFit-only) would otherwise be
            # invisible to get_steps() once flow_type has already changed.
            self._wizard_controller.invalidate_after(WizardStep.CONNECT)
            state.clear_device_scoped_state()
            self._wizard_controller.set_flow_type(FlowType.PEQ)
            state.selected_device = device_ip
            # The Filters step's Device panel caches the previous device's
            # PEQ/RoomFit lists independently of WizardState -- clear it too,
            # or browsing back to that panel could show (and let the user
            # load) presets by a name that belongs to the old device, not
            # the newly connected one.
            self._filters_page.clear_device_presets()
            # FiltersPage keeps its own Stereo/L-R radio selection independent
            # of state.channel_mode (it's the source of truth for a fresh
            # import, not a mirror of it) -- without this, switching devices
            # while L/R was selected leaves the radio on L/R even though
            # clear_device_scoped_state() just reset state.channel_mode to
            # STEREO, so the page's controls would misrepresent state until
            # the user's next import self-corrects it. Only matters for the
            # RoomFit flow, which has no SOURCE step to force a resync.
            self._filters_page.set_channel_mode("stereo")
            # A stale "RoomFit is active" flag from the previous device must
            # not linger either, even though nothing currently reads it (see
            # the __init__ comment) -- reset defensively so device B's state
            # is never contaminated by device A's, until
            # populate_name_profiles() re-fetches device B's real status.
            self._roomfit_enabled = False
            # _confirm_filters_selection()'s own change-detection cache:
            # already harmless without this (the first filter load on
            # device B always differs in value from whatever device A last
            # confirmed, so invalidate_after(FILTERS) still fires
            # correctly), but reset it explicitly anyway so the cache can
            # never silently carry meaning across a device switch if its
            # comparison logic changes later.
            self._last_confirmed_filters_signature = None

        # Lazily create device-specific adapters (Req 14.2, 14.3)
        self._wiim_http_client = self._wiim_http_client_factory(device_ip)
        self._capability_prober = self._capability_prober_factory(self._wiim_http_client)

        # Bump generation so a still-in-flight probe from a previous device
        # selection is discarded instead of advancing the wizard out from
        # under the user (see _do_probe).
        generation = self._primary_workflows.bump_probe_generation()
        self._connect_page.mark_connecting(device_ip)
        self._primary_workflows.probe(self._capability_prober, generation, device_ip)
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
    # wizard step, so the same step always shows the same wording regardless
    # of path (#162).
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

    def _capability_warning_text(self) -> str:
        """Warning text when displayed capabilities aren't purely from live
        device probing (capability-file override and/or generic fallback
        defaults), empty otherwise -- shared by the sidebar glyph and the
        device-info popover so the two can't drift."""
        caps = self._device_caps
        if getattr(caps, "capability_file_override", False) or getattr(
            caps, "used_generic_capabilities", False
        ):
            return (
                "Some capabilities are from a capability-file override or "
                "generic defaults, not the device itself — see Diagnostics "
                "for details."
            )
        return ""

    def _show_device_info(self) -> None:
        """Show the read-only device-details popover for the sidebar header.

        Replaces the header's old go-to-Connect behavior (PR #19 review,
        D2): a details dialog gives the capability warning a real home
        instead of hijacking the header tooltip, and the Connect pill
        already covers navigation.
        """
        from src.gui.dialogs.device_info_dialog import DeviceInfoDialog

        selected_ip = self._wizard_controller.state.selected_device
        if not selected_ip:
            return

        DeviceInfoDialog.show_info(
            self,
            self._resolve_connect_summary(),
            getattr(self._device_caps, "model", ""),
            selected_ip,
            self._capability_warning_text(),
        )

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

        Change detection (lazy invalidation, #246): re-confirming the EQ
        type the wizard already has just advances, keeping every downstream
        checkmark. An actual switch invalidates the steps after EQ_TYPE --
        ``WizardController.set_flow_type()`` itself owns that invalidation
        now (docs/smoke_test_issues.md #266), so this handler only needs to
        clear the loaded filter payload, not re-derive which steps to pop.

        Args:
            eq_type: Either "peq" or "roomfit".
        """
        new_flow = FlowType.ROOMFIT if eq_type == "roomfit" else FlowType.PEQ

        if new_flow != self._wizard_controller.flow_type:
            # PEQ and RoomFit are different pipelines: the loaded filter
            # payload (and its origin/rows/notes) from the flow being left
            # must not carry into the new one (#162d/#173) -- same
            # centralized clear the device switch uses, not a hand-picked
            # field subset that can drift (#246 bug-1b class).
            self._wizard_controller.state.clear_filter_payload()

        self._wizard_controller.set_flow_type(new_flow)
        self._wizard_controller.advance(
            summary=_EQ_TYPE_SUMMARY.get(eq_type, eq_type.upper())
        )

    @Slot(str, str)
    def _on_source_selected(self, source_name: str, channel_mode: str) -> None:
        """Handle source selection — store in state and advance.

        Change detection (lazy invalidation, #246): re-confirming the
        already-selected sources and channel mode just advances, keeping
        downstream checkmarks. An actual change invalidates the steps after
        SOURCE (filter data itself survives — filters aren't source-scoped
        until push).

        Args:
            source_name: Comma-separated audio source name(s).
            channel_mode: Channel mode ("Stereo", "Left", "Right").
        """
        state = self._wizard_controller.state
        new_sources = parse_source_list(source_name)
        new_mode = ChannelMode.from_any(channel_mode)

        # Compare as sets: the selection is a set of sources, so the same
        # sources arriving in a different order is not a change and must not
        # invalidate downstream checkmarks.
        if set(new_sources) != set(state.selected_sources) or new_mode != state.channel_mode:
            self._wizard_controller.invalidate_after(WizardStep.SOURCE)

        state.selected_source = source_name
        state.channel_mode = new_mode

        summary, tooltip = self._compute_source_summary(source_name)
        self._wizard_controller.advance(summary=summary, tooltip=tooltip)

    def _confirm_filters_selection(self) -> None:
        """Invalidate REVIEW/PUSH if the filter selection changed since last seen.

        Mirrors _on_source_selected's change-detection (see that method):
        picking a different filter set (a different device/local preset, or
        a fresh file import) than what Review/Push last saw invalidates
        those downstream steps, so browsing back to Filters, changing the
        selection, and advancing again can't leave a stale Review/Push
        checkmark in place -- unlike Source's own state field, which still
        holds the previous confirmed value at compare time,
        `state.current_filters` is already overwritten by the producer
        (file import/device pull/preset load) well before any advance-past-
        FILTERS handler runs, so the "previous confirmed" value has to be
        tracked separately in `_last_confirmed_filters_signature` rather
        than read back off wizard state itself.

        Called from every path that advances past FILTERS -- _on_peq_ready
        (device pull / file import, the common case), _on_profile_recalled
        (Local Library), and _on_filters_accepted (the warnings-
        acknowledgment path) -- not just the last of those. A version of
        this fix that only ran from _on_filters_accepted left Review/Push
        staleness undetected for every filter change that didn't happen to
        trigger a truncation/clamping warning, i.e. almost all of them.
        """
        state = self._wizard_controller.state
        # Value comparison, not identity: CanonicalFilter is an unfrozen
        # pydantic BaseModel with no custom __eq__, so its auto-generated
        # one compares fields, and tuple.__eq__ compares element-wise -- two
        # distinct CanonicalFilter objects with identical field values (e.g.
        # from re-importing the same file twice) already compare equal, so
        # that case correctly does NOT invalidate. The one known imprecision
        # is float exactness: a value that round-trips through JSON and
        # comes back sub-epsilon different from the original would compare
        # unequal here even though utils/fp_compare's tolerance would call
        # it the same filter -- accepted as a safe-side false positive
        # (an extra invalidation, never a missed one), not worth pulling in
        # fp_compare's write-verification tolerance for this comparison.
        new_signature = (
            tuple(state.current_filters),
            tuple(state.filters_l),
            tuple(state.filters_r),
            state.channel_mode,
        )
        if new_signature != self._last_confirmed_filters_signature:
            self._wizard_controller.invalidate_after(WizardStep.FILTERS)
        self._last_confirmed_filters_signature = new_signature

    @Slot()
    def _on_filters_accepted(self) -> None:
        """Handle user accepting filters (with or without warnings) — advance."""
        state = self._wizard_controller.state
        # Order matters: invalidate first (may clear REVIEW/PUSH), then
        # advance (re-marks FILTERS complete) -- same order at the other two
        # _confirm_filters_selection() call sites.
        self._confirm_filters_selection()

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
        """Handle FiltersPage's source dropdown switching to "Pull from REW API".

        Populates FiltersPage's embedded RewPullView (already showing its
        "Connecting..." state — see FiltersPage._on_source_index_changed).
        A successful selection advances the wizard normally.
        """
        if self._is_busy():
            return

        self._active_rew_pull_view = self._filters_page.rew_pull_view
        self._status_banner.show_progress("Connecting to REW...")
        self._primary_workflows.list_rew_measurements()
        logger.info("REW API pull requested")

    @Slot()
    def _on_device_presets_requested(self) -> None:
        """Handle FiltersPage switching to the Device source panel.

        Triggers the same PEQ-preset/RoomFit-profile fetch "Presets on
        Device" uses (_load_device_presets) -- both consume the broadcast
        peq_presets_ready/roomfit_profiles_ready signals, forwarded to both
        views by _on_peq_presets_ready/_on_roomfit_profiles_ready.
        """
        if self._is_busy():
            return
        if self._wiim_adapter is None:
            return
        self._primary_workflows.list_presets()

    @Slot()
    def _on_local_profiles_requested(self) -> None:
        """Handle FiltersPage switching to the Local Library source panel."""
        self._filters_page.set_local_profiles(self._profile_repository.list_all())

    @Slot(object)
    def _on_device_item_selected(self, item: object) -> None:
        """Handle a Device-panel merged-list selection from FiltersPage.

        Reads (which device API is called to fetch filters) branch on the
        selected PresetItem's own preset_type -- not the wizard's current
        flow_type -- since the merged list intentionally offers both PEQ
        presets and RoomFit profiles regardless of which flow is active (a
        saved preset's origin doesn't have to match the flow pushing it;
        the Canonical Filter Model doesn't care which device API wrote it).

        The eventual *write* path (_do_push) does key off flow_type, though
        -- so picking an item whose type disagrees with the active flow
        must sync flow_type to match, or Push would later write a RoomFit
        profile through the PEQ path (or vice versa). Only touches flow_type
        when it actually needs to change, and never downgrades PEQ_ONLY
        (RoomFit-incapable devices) to plain PEQ: a RoomFit item can only
        ever appear in this list when supports_roomfit is true, which is
        mutually exclusive with PEQ_ONLY, so PEQ_ONLY only needs protecting
        on the "PEQ item picked" branch.

        No wizard-state pre-check (EQ type / source chosen) needed here --
        with QuickSetupDialog gone, this handler is only reachable from the
        Filters step itself, so both are already set by the time a user can
        select anything in this panel.

        Args:
            item: PresetItem selected from the merged Device list.
        """
        if self._is_busy():
            return

        name = getattr(item, "name", "")
        preset_type = getattr(item, "preset_type", "PEQ")
        if not name:
            return

        if self._wiim_adapter is None:
            self._status_banner.show_error("No device connected")
            return

        if not self._confirm_preset_preview([item]):
            return

        # set_flow_type() itself invalidates whatever's orphaned by the
        # switch (docs/smoke_test_issues.md #266's confirmed root cause was
        # this exact call site changing flow_type with no invalidation at
        # all -- SOURCE, PEQ-only, survived as a stale completed_steps
        # entry across a load-a-RoomFit-preset-here switch). No hand-rolled
        # invalidate_after needed here now; the shared path handles it.
        current_flow = self._wizard_controller.flow_type
        if preset_type == "RoomFit" and current_flow != FlowType.ROOMFIT:
            self._wizard_controller.set_flow_type(FlowType.ROOMFIT)
        elif preset_type != "RoomFit" and current_flow == FlowType.ROOMFIT:
            self._wizard_controller.set_flow_type(FlowType.PEQ)

        self._apply_channel_mode_from_item(item)
        self._status_banner.show_progress(f"Loading preset '{name}'...")
        if preset_type == "RoomFit":
            self._wizard_controller.state.roomfit_profile_name = name
            self._primary_workflows.pull_roomfit(name, operation_name="load_preset")
        else:
            self._primary_workflows.load_peq_preset(name)
        logger.info("Device preset selected: %s (type=%s)", name, preset_type)

    @Slot(object)
    def _on_local_profile_selected(self, profile: object) -> None:
        """Handle a Local Library selection from FiltersPage.

        No wizard-state pre-check needed here either, for the same reason as
        _on_device_item_selected: only reachable from the Filters step.

        Args:
            profile: Profile object selected from the Local Library list.
        """
        if self._is_busy():
            return

        logger.info("Local profile selected: %s", getattr(profile, "name", "unknown"))
        self._apply_channel_mode_from_item(profile)
        self._secondary_workflows.recall_profile(profile)

    def _apply_channel_mode_from_item(self, item: object) -> None:
        """Set state.channel_mode from a selected PresetItem/Profile's own
        channel_mode field.

        Shared by _on_device_item_selected and _on_local_profile_selected --
        neither the Device panel nor the Local Library panel has a
        Stereo/L-R toggle of its own, since the channel mode is already
        known from the selected preset/profile itself.
        """
        self._wizard_controller.state.channel_mode = coerce_channel_mode(
            getattr(item, "channel_mode", ChannelMode.STEREO)
        )

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
            channel = state.channel_mode.display_value
            if flow_type == FlowType.ROOMFIT:
                # RoomFit applies globally, not per-source (CLAUDE.md) — naming
                # a source here would be misleading, and selected_sources may
                # still hold stale values from an earlier PEQ run anyway.
                self._push_page.set_dry_run_result(
                    f"Dry run complete: {band_count} bands validated "
                    f"({channel}). No changes were written to device."
                )
            else:
                sources = state.selected_sources
                source_info = ", ".join(sources) if sources else state.primary_source
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
            self._primary_workflows.push()

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
        self._primary_workflows.push()

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
        self._push_page.start_undo()

        if self._wizard_controller.flow_type == FlowType.ROOMFIT:
            # RoomFit undo: restore backed-up bands to the same profile name
            source_name = self._wizard_controller.state.primary_source
            profile_name = self._wizard_controller.state.roomfit_profile_name
            self._secondary_workflows.undo_roomfit(backup_path, source_name, profile_name)
        else:
            # PEQ undo: handle multi-source backup paths (smoke #77)
            if is_multi_source_backup_path(backup_path):
                # Multi-source undo
                self._secondary_workflows.undo_multi_source(backup_path)
            else:
                # Single source undo (legacy format)
                source_name = self._wizard_controller.state.primary_source
                self._secondary_workflows.undo_last_push(source_name, backup_path)

    def _clear_pushed_snapshot(self) -> None:
        """Forget the last-successful-push snapshot after an undo.

        Once a push is undone, the device no longer reflects what
        last_pushed_filters recorded, so the unsaved-changes check must
        consider the wizard dirty again.
        """
        self._wizard_controller.state.last_pushed_filters = []

    @Slot()
    def _on_done_acknowledged(self) -> None:
        """Handle OK click after push — return to Filters step for next action.

        "OK" is a deliberate end-of-cycle action, not browsing, so REVIEW
        and PUSH are explicitly invalidated (go_to_step itself is purely
        navigational under lazy invalidation). FILTERS keeps its checkmark
        (the loaded filters are still valid); the frontier becomes REVIEW,
        and the next advance chain re-enters PUSH fresh so its stale
        result view gets reset on the way in.
        """
        self._wizard_controller.invalidate_from(WizardStep.REVIEW)
        self._wizard_controller.go_to_step(WizardStep.FILTERS)

    # ------------------------------------------------------------------
    # WizardController → UI update handlers
    # ------------------------------------------------------------------

    @Slot(object)
    def _on_step_changed(self, step: object) -> None:
        """Handle step change — switch QStackedWidget page and run entry
        side effects for freshly entered (not-yet-completed) steps.

        Args:
            step: The new WizardStep enum value.
        """
        if not isinstance(step, WizardStep):
            return

        # Switching the stacked widget's page fires currentChanged, which
        # _sync_navigation_chrome handles centrally (showing the step
        # indicator, setting its view/frontier indices, and resetting the
        # sidebar highlight to "home") — no need to duplicate any of that
        # here.
        page_key = _STEP_TO_PAGE_KEY.get(step)
        if page_key and page_key in PAGE_INDICES:
            self._stacked_widget.setCurrentIndex(PAGE_INDICES[page_key])

        # Entry side effects run only when the step is entered fresh (not
        # in completed_steps — the completed set is a prefix of the
        # sequence, so "not completed" means this is the frontier).
        # Browsing back to a completed step must not re-run them: a
        # completed PUSH keeps its result view on screen, and a completed
        # NAME_PROFILE must not have the name that was actually pushed
        # overwritten by a repopulate. Known trade-off: browsing away
        # mid-PUSH and returning re-clears an un-pushed dry-run result;
        # acceptable, dry-run is cheap to re-run.
        if step not in self._wizard_controller.completed_steps:
            # Reset Push page when entering the PUSH step (clear stale dry
            # run results)
            if step == WizardStep.PUSH:
                self._push_page.reset()

            # Populate NameProfilePage when entering that step (RoomFit flow)
            if step == WizardStep.NAME_PROFILE:
                self._populate_name_profile_page()

    @Slot(object)
    def _on_flow_type_changed(self, flow_type: object) -> None:
        """Handle flow type change — update StepIndicator labels.

        Args:
            flow_type: The new FlowType enum value.
        """
        if not isinstance(flow_type, FlowType):
            return

        # Rebuild labels + replay completed summaries and view/frontier
        self._rebuild_step_indicator()

    @Slot()
    def _on_wizard_reset(self) -> None:
        """Handle wizard reset — clear all pages and return to Connect."""
        self._connect_page.clear()
        self._filters_page.clear_results()
        self._push_page.reset()
        self._sidebar_nav.set_device_info("", connected=False)
        self._stacked_widget.setCurrentIndex(PAGE_INDICES["connect"])

        # Rebuild step indicator for default PEQ flow
        self._rebuild_step_indicator()

    @Slot()
    def _on_steps_invalidated(self) -> None:
        """Re-render the step indicator after a change-time invalidation.

        ``WizardController.invalidate_from()`` mutates completed_steps
        without a per-step signal, so views resync in full here.
        """
        self._render_step_indicator()

    def _rebuild_step_indicator(self) -> None:
        """Rebuild the StepIndicator's labels for the current flow's
        sequence, then resync all state (completed flags, view, frontier).

        Shared by startup, wizard reset, and flow-type switches — the
        three places the step *labels* can change.
        """
        sequence = self._wizard_controller.get_steps()
        labels = [step.value.replace("_", " ").title() for step in sequence]
        self._step_indicator.set_steps(labels)
        self._render_step_indicator()

    def _render_step_indicator(self) -> None:
        """Fully resync the StepIndicator from the controller's state.

        Pushes every step's completed flag + summary/tooltip, then the
        view (current step) and frontier indices. Used wherever the
        completed set may have changed wholesale (flow-type switch,
        change-time invalidation) rather than through the incremental
        ``step_summary_updated`` path.
        """
        sequence = self._wizard_controller.get_steps()
        completed = self._wizard_controller.completed_steps
        tooltips = self._wizard_controller.state.completed_step_tooltips

        entries: list[tuple[str, str] | None] = [
            (completed[step], tooltips.get(step, "")) if step in completed else None
            for step in sequence
        ]

        frontier = sequence.index(self._wizard_controller.frontier_step)
        current = self._wizard_controller.current_step
        if current in sequence:
            view = sequence.index(current)
        else:
            # Transient only: current_step belongs to a flow being switched
            # away from. Render the frontier as the view rather than
            # guessing an arbitrary index -- and log it, since a repeat
            # points at a caller invalidating without finishing navigation.
            logger.warning(
                "Step %s not in the current %s sequence; rendering frontier",
                current,
                self._wizard_controller.flow_type,
            )
            view = frontier
        self._step_indicator.sync(entries, view, frontier)

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

        The background scan that produces this result is a one-shot task
        started when Connect was entered/refreshed -- nothing cancels it if
        the user picks a device from progressive results and moves on
        before it finishes. Discarding a result that arrives after the
        wizard has left Connect avoids feeding a stale device list into an
        invisible ConnectPage, whose auto-select would otherwise re-emit
        ``device_selected`` for the already-connected device and trigger a
        pointless re-probe (the probe itself is now also guarded in
        ``_on_capabilities_ready``, but skipping it here avoids the wasted
        network round-trip entirely -- smoke #266 investigation).

        NOTE: this step-check is local to this handler, not a structural
        guarantee like the capability probe's ``probe_generation`` counter --
        a future consumer of this same discovery result would need its own
        copy of this guard rather than inheriting one.

        Args:
            devices: List of device info dicts from discovery.
        """
        self._connect_page.set_scanning(False)
        if self._wizard_controller.current_step != WizardStep.CONNECT:
            logger.debug(
                "Discovery completed after leaving Connect step (now %s); "
                "discarding results",
                self._wizard_controller.current_step,
            )
            return
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
        4. Advances the wizard -- but only if the wizard is still actually
           on the Connect step (see the guard below).

        Args:
            caps: DeviceCapabilities object from the probe.
        """
        selected_device = self._wizard_controller.state.selected_device
        if selected_device is not None:
            self._connect_page.mark_connected(selected_device)

        # Store capabilities (caps has supports_roomfit*, source_names, etc.)
        roomfit_readable = bool(getattr(caps, "supports_roomfit_read", False))

        # @Slot(object) erases the static type to satisfy PySide6's signal
        # registration -- probe() itself is properly typed as returning
        # DeviceCapabilities, so this narrows once here rather than
        # suppressing mypy separately at each of the two call sites below
        # that need the real type.
        device_caps = cast(DeviceCapabilities, caps)

        # Create WiiMAdapter now that we have a connected client (Req 14.2, 14.3).
        # SafeWrite/RoomFitSafeWrite are no longer cached here -- every
        # reader (push, undo, copy-to-device) now builds them on demand via
        # the factories passed to PrimaryWorkflowManager.configure()/
        # SecondaryWorkflowManager.configure() below.
        assert self._wiim_http_client is not None
        self._wiim_adapter = self._wiim_adapter_factory(self._wiim_http_client, device_caps)

        # SecondaryWorkflowManager itself is configured eagerly in
        # _setup_secondary_workflows() (__init__) -- only the "current
        # device" pointer, used by same-device workflows like
        # undo_last_push, updates here on each successful connect.
        self._secondary_workflows.set_current_adapter(self._wiim_adapter)
        self._primary_workflows.set_current_adapter(self._wiim_adapter)

        # If a device switch left the Filters step's Device panel showing,
        # clear_device_presets() (called synchronously in _on_device_selected,
        # before this adapter existed) deliberately did not refetch -- do it
        # now that the new device's adapter is actually live.
        if self._filters_page.current_source == FiltersSource.DEVICE:
            self._primary_workflows.list_presets()

        # Source names: resolved once, centrally, in merge_into() (#167) --
        # real enumeration via getAudioInputEnable where the device supports
        # it, falling back to DEFAULT_SOURCE_NAMES otherwise. caps.source_names
        # is guaranteed non-empty by the time probe()/merge_into() returns.
        source_names = getattr(caps, "source_names", [])

        # Store capabilities for later use (smoke #35, #36) -- set before
        # _resolve_connect_summary() below, which reads self._device_caps.
        self._device_caps = caps
        device_name = self._resolve_connect_summary()

        # Determine flow type and advance wizard. caps.supports_roomfit_read
        # is already corrected for devices known to incorrectly report
        # RoomFit support (smoke #36, WiiM Mini/Muzo_Mini) -- CapabilityProber
        # detects this generically (empty RoomFit profile list / no acoustic-
        # capability subsystem, docs/corrections.md 2026-07-10) and the
        # device_capabilities.json entry provides an explicit override for
        # that exact model, so there's no model-name special-casing to do
        # here.
        #
        # advance() always completes *whatever step is currently active* --
        # it has no notion of "the step this probe was for". A probe can
        # resolve after the wizard has already moved past Connect (e.g. a
        # late-arriving background discovery result re-selecting the
        # already-connected device, smoke #266 investigation), and an
        # unguarded advance() here would then silently mark the user's
        # *current* step (Source, Filters, ...) completed with a bogus
        # device-name summary and yank them forward one step. Only drive
        # the wizard when Connect is still genuinely the active step;
        # everything above this point (adapter, sidebar, source list,
        # diagnostics) is safe/desirable to refresh unconditionally.
        if self._wizard_controller.current_step == WizardStep.CONNECT:
            if not roomfit_readable:
                # PEQ-only device — skip EQ_TYPE step (Req 1.10). This
                # call site has no explicit invalidation of its own -- the
                # `current_step == CONNECT` guard above narrows the window,
                # but doesn't rule out a *manual* re-probe of an
                # already-connected device (the intentional no-op branch in
                # _on_device_selected) reporting different RoomFit support
                # than a prior, still-completed EQ_TYPE/NAME_PROFILE flow on
                # the same device. set_flow_type() itself invalidates
                # whatever's orphaned by that (docs/smoke_test_issues.md
                # #266), so nothing extra is needed here.
                self._wizard_controller.set_flow_type(FlowType.PEQ_ONLY)
                self._wizard_controller.advance(summary=device_name)
            else:
                # Device supports RoomFit — show EQ_TYPE choice (Req 1.9)
                self._wizard_controller.advance(summary=device_name)
        else:
            logger.info(
                "Capabilities probe for %s resolved after the wizard left "
                "Connect (now on %s); refreshing device data without "
                "advancing",
                device_name,
                self._wizard_controller.current_step,
            )

        # Update sidebar with device info, warning if displayed capabilities
        # aren't purely from live device probing (capability-file override
        # and/or generic/conservative fallback defaults)
        self._sidebar_nav.set_device_info(
            device_name,
            connected=True,
            capability_warning=self._capability_warning_text(),
        )

        # Populate SourcePage with available sources. set_sources()
        # legitimately changes Continue's enabled state (a default source
        # gets pre-checked) while this probe operation may still be
        # in flight -- tell the feedback manager so finish_operation()
        # restores *this* state rather than the stale pre-probe snapshot
        # (smoke #250).
        active_source = getattr(caps, "active_source", "")
        self._source_page.set_sources(source_names, active_source)
        self._feedback_manager.note_button_state_changed(self._source_page.continue_button())

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

        Thin pass-through to translator.wiim_generator.resolve_review_validation()
        (the actual validation/branching logic, moved out of src/gui/ per
        CLAUDE.md's "GUI has zero business logic" rule -- round-4 review
        finding #7, 2026-07-19) plus this class's own state/widget updates.

        Returns:
            (warnings, validated_count) on success, or None if the
            L/R-without-bands guard fired — it already showed its own
            error banner; the caller must return without advancing the
            wizard.
        """
        from src.translator.wiim_generator import resolve_review_validation

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

        # Read pending-rows/notes state before resolve_review_validation()'s
        # result is used to clear it below -- order matters, the validated
        # result is built from these fields' pre-clear values.
        result = resolve_review_validation(
            peq_data,
            state.channel_mode,
            state.current_filters,
            state.pending_rows,
            state.pending_rows_l,
            state.pending_rows_r,
            max_filters,
            supported_filter_types,
        )

        if result is None:
            # Logged inside resolve_review_validation() already; this only
            # needs to surface it to the user and reset pending state.
            self._status_banner.show_error(
                "Could not determine L/R channel data for this source"
            )
            self._clear_pending_lr_rows()
            return None

        state.channel_mode = result.resolved_channel_mode
        state.current_filters = result.current_filters

        if result.resolved_channel_mode.is_lr:
            state.filters_l = result.filters_l
            state.filters_r = result.filters_r
            notes_l = state.pending_conversion_notes_l
            notes_r = state.pending_conversion_notes_r
            self._clear_pending_lr_rows()
            self._review_page.set_lr_filters(
                result.filters_l,
                result.filters_r,
                result.clamping_l,
                result.clamping_r,
                result.rows_l,
                result.rows_r,
                notes_l,
                notes_r,
            )
        else:
            notes = state.pending_conversion_notes
            self._clear_pending_stereo_rows()
            self._review_page.set_filters(
                result.current_filters, result.clamping_map, result.rows, notes
            )

        return result.warnings, len(state.current_filters)

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

            self._confirm_filters_selection()
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
            # Snapshot through state.filters so the operand matches what
            # _has_unsaved_changes compares -- in L/R mode that is
            # filters_l + filters_r, not current_filters.
            self._wizard_controller.state.last_pushed_filters = list(
                self._wizard_controller.state.filters
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
            # >0 only on a multi-source PEQ push where earlier sources
            # succeeded before this one failed (smoke #242) -- those sources
            # were left written, not rolled back. partial_backup_paths (kept
            # separate from backup_path, which stays this failing source's
            # own backup for the critical-recovery display above) is their
            # encoded backup string; record it the same way a successful
            # push does, so _on_undo_requested's existing
            # is_multi_source_backup_path() branch lets the user Undo them.
            partial_sources = getattr(result, "partial_sources", 0) or 0
            partial_backup_paths = getattr(result, "partial_backup_paths", None)
            if partial_sources and partial_backup_paths:
                self._wizard_controller.state.last_backup_path = partial_backup_paths
            self._push_page.set_failure(error_msg, backup_path, critical, partial_sources)
            self._status_banner.show_error(f"Push failed: {error_msg}")
            logger.error(
                "Push failed (critical=%s, partial_sources=%d): %s. Backup: %s",
                critical,
                partial_sources,
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
            self._show_rew_pull_message(message, icon=ICON_NO_CONNECTION)

        # A failed discovery scan or capability probe leaves the scanning
        # indicator/clicked card stuck forever with no other reset path --
        # only relevant while Connect is still the active step (mirrors
        # _on_capabilities_ready's own guard); a no-op otherwise, since both
        # calls only touch state actually showing "scanning"/"connecting".
        # _AbandonGuard deliberately skips firing discovery_abandoned/
        # probe_abandoned for a genuine error (as opposed to cancellation or
        # a stale-generation discard) so their "cancelled"/empty-state
        # framing can't run ahead of and clobber this handler's real error
        # message -- this is where that cleanup happens instead.
        if self._wizard_controller.current_step == WizardStep.CONNECT:
            self._connect_page.cancel_scanning()
            self._connect_page.reset_connecting()

    @Slot(str)
    def _on_probe_abandoned(self, device_ip: str) -> None:
        """Handle a capability probe that ended without a result.

        Fires when a cancellable probe is cancelled (Escape/Cancel) or
        discarded as stale (the user selected a different device before it
        resolved) -- neither path emits capabilities_ready or
        operation_error, so without this the clicked device's card would
        keep pulsing "connecting" forever. Scoped to *device_ip* (rather
        than reset_connecting()'s "every connecting card") so an unrelated
        card that's still genuinely probing isn't touched.

        Args:
            device_ip: IP of the device whose probe was abandoned.
        """
        self._connect_page.reset_connecting_for(device_ip)

    @Slot()
    def _on_discovery_abandoned(self) -> None:
        """Handle a discovery scan cancelled before it completed.

        discovery_complete (the only other place that hides the scanning
        indicator) never fires for a cancelled scan, so without this the
        "Scanning for devices..." UI would stay shown indefinitely after
        Escape/Cancel even though the operation has actually stopped.
        Delegates to ConnectPage.cancel_scanning() rather than a bare
        set_scanning(False) -- the latter is meant to always be paired with
        a set_devices() call right after (which discovery_complete
        provides but a cancellation never reaches), so calling it alone
        here would leave the page blank when no devices were found yet.
        """
        self._connect_page.cancel_scanning()

    @Slot()
    def _on_rew_list_abandoned(self) -> None:
        """Handle a REW measurement fetch cancelled before it completed.

        Mirrors _on_probe_abandoned/_on_discovery_abandoned: neither
        rew_measurements_ready nor the info-message branch of
        _do_rew_list_measurements fires for a cancelled fetch, so without
        this the embedded RewPullView would stay showing "Connecting..."
        forever after Escape/Cancel.
        """
        self._show_rew_pull_message("Measurement fetch cancelled.")

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
        """Handle REW measurements listed — populate the embedded RewPullView.

        _on_rew_api_pull_requested sets _active_rew_pull_view before kicking
        off the listing request, so a late result arriving after the user
        has navigated away is ignored (view is None). Navigates back to the
        Filters page if the user wandered off while REW was being queried.
        Stereo returns one MeasurementSummary, L/R returns a (left, right)
        tuple — see _dispatch_measurement_selection.

        Requirements: 5.2, 5.7.

        Args:
            measurements: List of MeasurementSummary objects from REW API.
        """
        view = self._active_rew_pull_view
        if view is None:
            return
        self._stacked_widget.setCurrentIndex(PAGE_INDICES["filters"])
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
        self._stacked_widget.setCurrentIndex(PAGE_INDICES["filters"])
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
                back_requested instead (see _on_filters_rew_pull_back_requested).
        """
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

    def _run_batch_profile_action(
        self, names: list[str], action: Callable[[str], object], failure_verb: str
    ) -> tuple[int, int]:
        """Run a synchronous ProfileRepository action per name in *names*,
        refreshing once afterward. Sibling of `_run_profile_action` for the
        one local-repository action that batches over a multi-select
        (`_on_profile_delete_requested`) instead of running once -- kept
        separate rather than folded into `_run_profile_action` since a
        partial-failure batch needs a materially different interface
        (per-item callable, (succeeded, failed) counts) than that method's
        single callable mapped to one success/one failure outcome.

        A per-item failure doesn't stop the batch; refreshing unconditionally
        afterward (even if every item failed) matters because the repo may
        have changed regardless (e.g. a concurrent rename), and stale UI is
        worse than one extra read. Returns the (succeeded, failed) counts --
        unlike `_run_profile_action`, the caller decides the status banner
        wording, since that legitimately differs per action and per count.

        Args:
            names: Preset names to run *action* against.
            action: Callable taking one name, performing the repository write.
            failure_verb: Logged per item on failure, e.g. "Delete".
        """
        succeeded = 0
        for name in names:
            try:
                action(name)
                succeeded += 1
            except Exception:
                logger.warning("%s local preset %r failed", failure_verb, name, exc_info=True)
        self._refresh_presets_view()
        return succeeded, len(names) - succeeded

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
        try:
            profile = build_profile(
                name, filters, channel_mode,
                filters_l=state.filters_l,
                filters_r=state.filters_r,
            )
        except ValueError as exc:
            self._status_banner.show_error(f"Save failed: {exc}")
            return

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

    def _prompt_stereo_export_path(self, title: str, default_name: str) -> str | None:
        """Show the stereo REW-export save dialog; return the confirmed
        .txt path, or None if the user cancelled.

        Shared by _export_filters_as_rew's and _on_preset_export_requested's
        stereo branches -- both built this exact dialog-and-suffix sequence
        independently before this extraction.
        """
        default_dir = self._settings.rew_folder or str(Path.home())
        path, _ = QFileDialog.getSaveFileName(
            self,
            title,
            str(Path(default_dir) / f"{default_name}.txt"),
            "REW EQ Files (*.txt)",
        )
        if not path:
            return None
        return str(ensure_suffix(Path(path), ".txt"))

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
            try:
                filters_l, filters_r = require_lr_filters(state.filters_l, state.filters_r)
            except ValueError as exc:
                self._status_banner.show_error(f"Export failed: {exc}")
                return

            self._primary_workflows.export_file_lr(filters_l, filters_r, path_l, path_r)
            logger.info("Export L/R REW: %s, %s", path_l, path_r)
        else:
            # Stereo mode: single file dialog
            state = self._wizard_controller.state
            default_name = self._device_prefixed_name(state.selected_source or DEFAULT_SOURCE)
            path = self._prompt_stereo_export_path("Export REW EQ File", default_name)
            if path is None:
                logger.debug("Export cancelled by user")
                return

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
    # _on_device_pull_requested/_on_device_item_selected/
    # _export_filters_as_rew now calls the manager directly.

    # _read_preset_to_copy, _write_preset_to_adapter,
    # _write_preset_copies_to_devices, _do_copy_presets_batch_multi,
    # _do_copy_local_profiles_to_devices moved to SecondaryWorkflowManager
    # (src/gui/secondary_workflows.py) — docs/backlog.md item 2, Phase D.
    # (_do_copy_preset_to_device, also moved here at Phase D, was deleted --
    # round-4 review finding #10 -- once _write_preset_to_adapter became the
    # actual production write primitive and it had zero remaining callers.)
    # Dispatch from _on_copy_to_device_requested/
    # _on_local_preset_copy_to_device_requested now calls the manager
    # directly; results arrive via the shared copy_batch_complete signal
    # (both dispatch paths report the same shape, see _on_copy_batch_complete).

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
    # _on_rew_api_pull_requested/_dispatch_measurement_selection now calls
    # the manager directly.

    def _load_device_presets(self) -> None:
        """Fetch and display device presets in the PresetsDeviceView.

        If no device is connected, shows the empty state. Otherwise
        fetches PEQ presets and RoomFit profiles via
        PrimaryWorkflowManager.list_presets(), which independently gates
        each on its own capability (supports_peq/supports_profile_enumeration
        for PEQ, supports_roomfit for RoomFit -- see refresh_presets()) and
        emits peq_presets_ready/peq_presets_unavailable and
        roomfit_profiles_ready/roomfit_profiles_hidden accordingly.

        Deliberately does NOT pre-check supports_profile_enumeration here
        and bail out early -- that used to skip the RoomFit fetch too,
        since both were only reachable past this one early return. Profile
        enumeration and RoomFit support are independent capabilities; a
        device lacking only the former still gets its RoomFit profiles
        listed, and its live PEQ config still surfaces as a synthetic
        "Custom" row via refresh_presets()'s own supports_peq fallback.
        """
        if self._wiim_adapter is None:
            self._presets_device_view.set_no_device()
            return

        self._primary_workflows.list_presets()

    def _populate_name_profile_page(self) -> None:
        """Fetch RoomFit profile names and populate NameProfilePage list.

        Called when the wizard navigates to the NAME_PROFILE step.
        """
        if self._wiim_adapter is None:
            self._name_profile_page.set_existing_profiles([])
            return

        self._primary_workflows.populate_name_profiles()

    # _do_populate_name_profiles moved to PrimaryWorkflowManager
    # (src/gui/primary_workflows.py) — docs/backlog.md item 2, Phase 4.
    # Dispatch from _populate_name_profile_page now calls the manager
    # directly; results arrive via name_profiles_ready, see
    # _on_name_profiles_ready.

    # _do_list_presets, _peq_active_info_or_default, _roomfit_active_info_or_default
    # moved to PrimaryWorkflowManager (src/gui/primary_workflows.py) as
    # refresh_presets() and its helpers — docs/backlog.md item 3, Phase 1b.
    # See _on_peq_presets_ready / _on_peq_presets_unavailable /
    # _on_roomfit_profiles_ready / _on_roomfit_profiles_hidden below for the
    # thin pass-through into PresetsDeviceView that replaced this method's
    # direct widget writes.

    def _forward_to_preset_views(self, method_name: str, *args: object) -> None:
        """Call the same method with the same args on both views that mirror
        device PEQ/RoomFit state -- PresetsDeviceView (the sidebar page) and
        FiltersPage's Device panel -- shared by every
        PrimaryWorkflowManager preset-fetch signal handler below so a third
        consumer, if one is ever added, only needs wiring in one place."""
        getattr(self._presets_device_view, method_name)(*args)
        getattr(self._filters_page, method_name)(*args)

    @Slot(list, object, str, bool, str, bool)
    def _on_peq_presets_ready(
        self,
        items: list[Any],
        active_name: str | None,
        active_channel_mode: str,
        active_enabled: bool,
        source_name: str,
        enumeration_supported: bool,
    ) -> None:
        """Forward PrimaryWorkflowManager.peq_presets_ready into both consuming views."""
        self._forward_to_preset_views(
            "set_peq_presets",
            items,
            active_name,
            active_channel_mode,
            active_enabled,
            source_name,
            enumeration_supported,
        )

    @Slot()
    def _on_peq_presets_unavailable(self) -> None:
        """Forward PrimaryWorkflowManager.peq_presets_unavailable into both consuming views."""
        self._forward_to_preset_views("set_peq_unavailable")

    @Slot(list, str, bool)
    def _on_roomfit_profiles_ready(
        self, items: list[Any], active_name: str, active_enabled: bool
    ) -> None:
        """Forward PrimaryWorkflowManager.roomfit_profiles_ready into both consuming views."""
        self._forward_to_preset_views("set_roomfit_profiles", items, active_name, active_enabled)

    @Slot()
    def _on_roomfit_profiles_hidden(self) -> None:
        """Forward PrimaryWorkflowManager.roomfit_profiles_hidden into both consuming views."""
        self._forward_to_preset_views("set_roomfit_hidden")

    @Slot(list, str, bool)
    def _on_name_profiles_ready(
        self, profile_names: list[str], active_profile: str, roomfit_enabled: bool
    ) -> None:
        """Forward PrimaryWorkflowManager.name_profiles_ready into NameProfilePage."""
        self._name_profile_page.set_existing_profiles(profile_names, active_profile)
        self._roomfit_enabled = roomfit_enabled

    @Slot(int, int)
    def _on_presets_delete_complete(self, succeeded: int, failed: int) -> None:
        """Forward PrimaryWorkflowManager.presets_delete_complete into the status banner."""
        if failed == 0:
            self._status_banner.show_success(f"{succeeded} preset(s) deleted")
        else:
            self._status_banner.show_error(f"Deleted {succeeded}, {failed} failed")

    @Slot(int, int)
    def _on_presets_export_complete(self, succeeded: int, failed: int) -> None:
        """Forward PrimaryWorkflowManager.presets_export_complete into the status banner."""
        if failed == 0:
            self._status_banner.show_success(f"{succeeded} preset(s) exported")
        else:
            self._status_banner.show_error(f"Exported {succeeded}, {failed} failed")

    @Slot(int, int)
    def _on_presets_save_complete(self, succeeded: int, failed: int) -> None:
        """Forward PrimaryWorkflowManager.presets_save_complete into the status banner."""
        if failed == 0:
            self._status_banner.show_success(f"{succeeded} preset(s) saved to My Presets")
        else:
            self._status_banner.show_error(f"Saved {succeeded}, {failed} failed")

    # ------------------------------------------------------------------
    # Navigation handlers
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_step_indicator_clicked(self, index: int) -> None:
        """Handle a step-pill navigation click (a completed step, or the
        frontier pill while browsing elsewhere). Pure browsing -- destroys
        nothing (lazy invalidation, #246).

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

        self._primary_workflows.raw_command(command)

    @Slot(str)
    def _on_navigation_requested(self, view_key: str) -> None:
        """Handle sidebar navigation request — switch QStackedWidget page.

        When 'home' is selected, returns to the wizard frontier ("Setup
        Wizard"). 'device_info' shows the read-only device popover. Otherwise
        navigates to the corresponding secondary view.

        Args:
            view_key: Navigation target key from SidebarNav.
        """
        logger.debug("Navigation requested: %s", view_key)
        # Sidebar highlight + step-indicator visibility are synced centrally
        # by _sync_navigation_chrome (wired to currentChanged) — this
        # handler only needs to decide which page to switch to.
        if view_key == "home":
            # "Setup Wizard" returns to the frontier -- where the user left
            # off. Two distinct cases:
            # - The user was already at the frontier and just visited a
            #   secondary view (e.g. Settings): restore the stacked page
            #   only, WITHOUT re-running entry side effects (Push page
            #   dry-run/result reset, Name Profile repopulate) -- returning
            #   from Settings is not re-entering the step.
            # - The user browsed back to an earlier step first: a real jump
            #   through go_to_step(frontier), so the indicator and entry
            #   side effects stay correct.
            frontier = self._wizard_controller.frontier_step
            if self._wizard_controller.current_step != frontier:
                self._wizard_controller.go_to_step(frontier)
                return
            page_key = _STEP_TO_PAGE_KEY.get(frontier)
            if page_key and page_key in PAGE_INDICES:
                self._stacked_widget.setCurrentIndex(PAGE_INDICES[page_key])
            return

        if view_key == "device_info":
            # Sidebar device header: read-only details popover (PR #19
            # review, D2) -- the Connect pill covers navigation.
            self._show_device_info()
            return

        if view_key == "help":
            # Open Help as a separate window (smoke #112). Doesn't replace
            # the current page, so the step indicator's visibility is
            # untouched.
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
        # the step indicator and sidebar chrome stay in sync. On first run
        # nothing is completed yet, so this is a plain navigation to the
        # frontier (go_to_step is purely navigational under lazy
        # invalidation, #246).
        self._wizard_controller.go_to_step(WizardStep.CONNECT)

    @Slot()
    def _on_user_guide_triggered(self) -> None:
        """Open the Help window (Help > User Guide or sidebar Help)."""
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    @Slot()
    def _on_about_triggered(self) -> None:
        """Show About dialog (Help > About)."""
        version = get_app_version()
        QMessageBox.about(
            self,
            "About WiiM \u2194 REW PEQ Sync",
            "<h3>WiiM \u2194 REW PEQ Sync</h3>"
            f"<p><b>Version {version}</b></p>"
            '<p><a href="https://github.com/disposabledominik/wiim-rew-sync">'
            "github.com/disposabledominik/wiim-rew-sync</a></p>"
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
        - Cancel button after 2s, for operations marked cancellable at their
          _dispatch() call site (reads/local-file operations only -- never
          device writes, see docs/architecture.md's "Why writes are never
          user-cancellable")
        - Buttons re-enabled on finish
        - Escape/Cancel-click requests actually stop a cancellable
          operation's Future, via AsyncBridge.request_cancel()
        """
        self._bridge.operation_started.connect(self._on_bridge_operation_started)
        self._bridge.operation_finished.connect(self._on_bridge_operation_finished)
        self._feedback_manager.cancel_requested.connect(self._bridge.request_cancel)

        # All pages/views are created once and persist for the app's
        # lifetime (see _create_pages/_register_pages), so their action
        # buttons can be collected and registered a single time here rather
        # than re-registered on every navigation.
        action_buttons: list[QWidget] = []
        for page_or_view in (
            self._connect_page,
            self._source_page,
            self._filters_page,
            self._review_page,
            self._name_profile_page,
            self._push_page,
            self._presets_device_view,
            self._my_presets_view,
            self._settings_view,
            self._filters_page.rew_pull_view,
        ):
            action_buttons.extend(page_or_view.action_buttons())
        self._feedback_manager.register_action_buttons(action_buttons)

    @Slot(bool, int)
    def _on_bridge_operation_started(self, cancellable: bool, token: int) -> None:
        """Handle bridge operation_started — activate feedback manager.

        *token* isn't needed here -- a start always represents the newest
        dispatch by definition, so there's nothing to compare it against
        (see _on_bridge_operation_finished, which does need it).
        """
        del token
        self._feedback_manager.start_operation("Processing...", cancellable=cancellable)

    @Slot(int)
    def _on_bridge_operation_finished(self, token: int) -> None:
        """Handle bridge operation_finished — deactivate feedback manager.

        Ignores a stale *token*: a signal handler for one operation's own
        result can synchronously dispatch a second, unrelated operation
        before the first operation's own operation_finished has been
        processed (e.g. _on_capabilities_ready dispatching list_presets()).
        Qt delivers queued signals in emission order, so that second
        dispatch supersedes AsyncBridge's tracking before this handler runs
        for the first operation's finish -- acting on it here would
        incorrectly tear down feedback-manager/UI state for the second,
        still-running operation. See AsyncBridge._current's docstring.
        """
        if not self._bridge.is_current_operation(token):
            logger.debug(
                "Ignoring stale operation_finished (token %d, superseded by a "
                "newer dispatch)",
                token,
            )
            return
        self._feedback_manager.finish_operation()

    # ------------------------------------------------------------------
    # Keyboard Shortcuts and Accessibility (Req 26.1-26.7)
    # ------------------------------------------------------------------

    def _setup_keyboard_shortcuts(self) -> None:
        """Configure keyboard shortcuts for common actions.

        Shortcuts:
        - Ctrl+R: Refresh devices (trigger discovery)
        - Escape: Dismiss help panel if visible
        - Ctrl+O is already handled by the File > Import menu action.
        """
        # Ctrl+R — Refresh devices (Req 26.5)
        shortcut_refresh = QShortcut(QKeySequence("Ctrl+R"), self)
        shortcut_refresh.activated.connect(self._on_shortcut_refresh)

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
    def _on_shortcut_escape(self) -> None:
        """Handle Escape — dismiss help dialog if visible, cancel active operation.

        request_cancel() is itself a no-op when the active operation isn't
        cancellable (e.g. a device write), so Escape correctly does nothing
        observable in that case rather than falsely claiming to cancel it.
        """
        if self._help_dialog.isVisible():
            self._help_dialog.hide()
            logger.debug("Keyboard shortcut: Escape — Help dialog dismissed")
        elif self._feedback_manager.is_active:
            self._feedback_manager.request_cancel()
            logger.debug("Keyboard shortcut: Escape — Operation cancel requested")

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
        self._primary_workflows.presets_delete_complete.connect(
            self._on_presets_delete_complete
        )
        self._primary_workflows.presets_export_complete.connect(
            self._on_presets_export_complete
        )
        self._primary_workflows.presets_save_complete.connect(
            self._on_presets_save_complete
        )

    # ------------------------------------------------------------------
    # Secondary Workflows (Req 17, 18, 20, 21)
    # ------------------------------------------------------------------

    def _setup_secondary_workflows(self) -> None:
        """Create the SecondaryWorkflowManager and wire its signals.

        Connects:
        - PresetsDeviceView "Copy to Another Device" → dispatched from
          MainWindow's own _do_copy_presets_batch_multi, which calls the
          read/write primitives on SecondaryWorkflowManager
          (_read_preset_to_copy / _write_preset_to_adapter).
        - FiltersPage Local Library selection → profile recall → populate ReviewPage
        - PushPage "Undo" → undo_last_push flow
        - SecondaryWorkflowManager completion signals → UI updates

        Note: "Copy to another source" / "Apply to multiple devices" had no
        UI wiring and the corresponding SecondaryWorkflowManager methods
        were removed as dead code (code quality audit, 2026-06-28).
        """
        self._secondary_workflows = SecondaryWorkflowManager(parent=self)

        # Per-item failure detail lines for the copy-to-device workflows,
        # accumulated from copy_item_failed and consumed by
        # _on_copy_batch_complete. Reset by each dispatch handler
        # (_on_copy_to_device_requested / _on_local_preset_copy_to_device_requested)
        # right before starting a new batch.
        self._copy_batch_failures: list[str] = []

        # Configured eagerly, like PrimaryWorkflowManager above: every
        # argument here is a device-agnostic factory/callable already built
        # in __init__, not tied to whichever device the Connect step probes.
        # "My Saved Presets" and its Copy to Another Device action are local-
        # file / self-contained-dialog workflows (the target device is picked
        # inside the dialog itself) that must not require a prior Connect-step
        # probe -- gating this behind _on_capabilities_ready made
        # copy_local_profiles_to_devices()/copy_presets_to_devices() raise a
        # bare AssertionError in _dispatch() (self._bridge is None) whenever
        # the user opened My Saved Presets before connecting to any device.
        self._secondary_workflows.configure(
            bridge=self._bridge,
            bridge_wrapper=self._bridge_wrapper,
            safe_write_factory=self._safe_write_factory,
            roomfit_safe_write_factory=self._roomfit_safe_write_factory,
            wiim_http_client_factory=self._wiim_http_client_factory,
            capability_prober_factory=self._capability_prober_factory,
            target_adapter_factory=self._wiim_adapter_factory,
        )

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
        self._presets_device_view.delete_requested.connect(
            self._on_preset_delete_requested
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
        self._secondary_workflows.undo_multi_source_complete.connect(
            self._on_undo_multi_source_complete
        )
        self._secondary_workflows.source_slots_ready.connect(
            self._diagnostics_panel.on_source_slots_ready
        )
        self._secondary_workflows.source_slots_error.connect(
            self._diagnostics_panel.on_source_slots_error
        )
        self._secondary_workflows.copy_batch_complete.connect(
            self._on_copy_batch_complete
        )
        self._secondary_workflows.copy_item_failed.connect(
            self._on_copy_item_failed
        )

    # --- Inbound handlers (page/view → workflow trigger) ---

    @Slot(list)
    def _on_copy_to_device_requested(self, items: list[Any]) -> None:
        """Handle PresetsDeviceView "Copy to Another Device" action.

        Opens a device picker (with the source-read and target-write
        warnings folded into it as a single combined dialog, instead of two
        separate confirmations shown beforehand) for the target device
        selection, then dispatches SecondaryWorkflowManager
        .copy_presets_to_devices() for each selected item.

        Requirement 15.1: User selects target device from discovered list.
        Requirement 15.2: Copy preset filters to the selected target device.

        Args:
            items: List of PresetItem objects selected for copying.
        """
        if not items:
            return

        renamed_items = self._prompt_custom_item_name(items)
        if renamed_items is None:
            return  # user cancelled the name prompt
        items = renamed_items

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

        # Process all items across all selected devices in a single async operation.
        # source_name and target_source are the same wizard-state value here --
        # the source device's active source is assumed to name the same slot
        # on each target device.
        self._copy_batch_failures = []
        self._secondary_workflows.copy_presets_to_devices(
            items, selected_devices, target_source, target_source
        )

    def _prompt_custom_item_name(self, items: list[Any]) -> list[Any] | None:
        """If `items` includes the synthetic "Custom" row (#165c), ask the
        user for a real name to save it under on the target device(s) --
        "Custom" itself isn't a name the device assigned, unlike every other
        item here. Returns `items` unchanged (same list, not a copy) when no
        custom item is present, a new list with the custom item renamed
        (its `is_custom` flag preserved, since that still drives the
        *source*-side read in SecondaryWorkflowManager) if the user
        confirms, or None if the prompt is cancelled -- distinct from an
        empty list, which the caller would otherwise treat as "nothing to
        copy" rather than "cancelled."
        """
        for i, item in enumerate(items):
            if not getattr(item, "is_custom", False):
                continue

            new_name, ok = QInputDialog.getText(
                self,
                "Name This Configuration",
                "This device configuration isn't saved under a name yet. "
                "Enter a name to save it as on the target device:",
            )
            new_name = new_name.strip()
            if not ok or not new_name:
                return None
            renamed = items[:]
            renamed[i] = PresetItem(
                name=new_name,
                channel_mode=item.channel_mode,
                preset_type=item.preset_type,
                is_custom=True,
            )
            # At most one custom item can appear (the merged Device list only
            # ever contains one synthetic "Custom" row), so stop after the
            # first match instead of scanning the rest of `items`.
            return renamed
        return items

    @Slot(list)
    def _on_local_preset_copy_to_device_requested(self, profiles: list[Any]) -> None:
        """Handle MyPresetsView "Copy to Another Device" action.

        A locally saved Profile carries no record of whether it originated
        as a PEQ preset or a RoomFit profile (see build_profile /
        Profile in src/models/profile.py), so unlike the device-to-device
        copy flow, this asks the user which target write-mode to use once
        -- applied to every selected profile -- before picking devices.
        There's also no live source device to read from here -- the filters
        are already in hand -- so there's no source-read warning to show;
        the target-write warning (identical concern to the device-to-device
        flow) is folded into the device picker dialog once the type is
        known, instead of shown as a separate confirmation step.

        Args:
            profiles: Profile objects selected in My Saved Presets.
        """
        if not profiles:
            return
        if not self._primary_workflows.discovered_devices:
            self._status_banner.show_error("No other devices discovered")
            return

        preset_type = PresetTypeDialog.get_type(self)
        if preset_type is None:
            return

        preview_items = [
            PresetItem(
                name=getattr(profile, "name", ""),
                channel_mode=getattr(
                    profile, "channel_mode", ChannelMode.STEREO
                ).display_value,
                preset_type=preset_type,
            )
            for profile in profiles
        ]
        activation_body = self._copy_activation_warning_html(preview_items)
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

        logger.info(
            "Copy %d local preset(s) (%s) to %d device(s)",
            len(profiles), preset_type, len(selected_devices),
        )

        # Passed as raw Profile fields, not a pre-built PEQSettings --
        # build_peq_settings()/extract_filters() and the incomplete-L/R-split
        # ValueError case they can raise are SecondaryWorkflowManager's job,
        # not MainWindow's (CLAUDE.md: "GUI has zero business logic").
        profiles_data = [
            (
                getattr(profile, "name", ""),
                getattr(profile, "channel_mode", ChannelMode.STEREO),
                getattr(profile, "filters", None),
                getattr(profile, "filters_l", None),
                getattr(profile, "filters_r", None),
            )
            for profile in profiles
        ]
        self._copy_batch_failures = []
        self._secondary_workflows.copy_local_profiles_to_devices(
            profiles_data, preset_type, selected_devices, target_source,
        )

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

    @Slot(list)
    def _on_profile_delete_requested(self, names: list[str]) -> None:
        """Handle MyPresetsView delete action -- single or multi-select batch.

        Confirms before deleting, matching the equivalent safety check on
        the device-side preset delete (`_on_preset_delete_requested`) --
        this one is a local, in-app-storage deletion, not a device write.
        A partial failure (e.g. one preset already removed by a concurrent
        change) still deletes the rest and reports a "X succeeded, Y failed"
        status instead of aborting the whole batch, matching
        `_on_preset_delete_requested`'s device-side convention.
        """
        if not names:
            return

        if len(names) == 1:
            message = f"Permanently delete '{names[0]}' from My Presets?\n\nThis cannot be undone."
        else:
            bullet_list = "\n".join(f"• {name}" for name in names)
            message = (
                f"Permanently delete the following {len(names)} presets from "
                f"My Presets?\n\n{bullet_list}\n\nThis cannot be undone."
            )
        if not self._confirm_action("Delete Preset(s)", message):
            return

        succeeded, failed = self._run_batch_profile_action(
            names, lambda name: self._profile_repository.delete(name), "Delete"
        )
        if failed:
            self._status_banner.show_error(
                f"Deleted {succeeded} preset(s), {failed} failed."
            )
        elif succeeded == 1:
            self._status_banner.show_success(f"Deleted '{names[0]}'")
        else:
            self._status_banner.show_success(f"Deleted {succeeded} presets")

    @Slot(list)
    def _on_preset_export_requested(self, items: list[Any]) -> None:
        """Handle PresetsDeviceView "Export as REW File" for selected presets.

        A single selected item keeps the existing per-file save dialog
        (exact filename control). Multiple selected items instead pick one
        destination folder, then each preset is exported to its own
        device-prefixed filename inside it -- every selected item gets
        exported, not just the first (previously silently dropped the rest
        despite Export being enabled for a multi-select; #165c follow-up).

        Args:
            items: List of PresetItem objects selected for export.
        """
        if not items:
            return

        if not self._confirm_preset_preview(items):
            return

        if len(items) == 1:
            self._export_one_preset_with_dialog(items[0])
        else:
            self._export_presets_to_folder(items)

    def _preset_item_identity(self, item: object) -> tuple[str, str, bool]:
        """Return (name, preset_type, is_custom) read off a PresetItem-like
        object -- the three fields every export/save request tuple needs
        regardless of how its destination path is computed, read the same
        way by _export_one_preset_with_dialog, _export_presets_to_folder,
        and _on_preset_save_requested so the three can't drift on which
        getattr default they fall back to."""
        return (
            getattr(item, "name", ""),
            getattr(item, "preset_type", "PEQ"),
            getattr(item, "is_custom", False),
        )

    def _export_one_preset_with_dialog(self, item: object) -> None:
        """Single-item export: existing per-file dialog, exact filename control."""
        preset_name, preset_type, is_custom = self._preset_item_identity(item)
        channel_mode = getattr(item, "channel_mode", "Stereo")

        # Device-prefixed only for the destination filename -- preset_name
        # itself stays exactly as the device reports it, since it's also the
        # on-device lookup key passed to PrimaryWorkflowManager.export_presets below.
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
            export_path_or_none = self._prompt_stereo_export_path(
                "Export Preset as REW File", export_default_name
            )
            if export_path_or_none is None:
                logger.debug("Preset export cancelled")
                return
            export_path = export_path_or_none

        self._status_banner.show_progress(f"Exporting '{preset_name}'...")
        self._primary_workflows.export_presets(
            [(preset_name, preset_type, export_path, is_custom)]
        )
        logger.info("Preset export requested: %s -> %s", preset_name, export_path)

    def _export_presets_to_folder(self, items: list[Any]) -> None:
        """Multi-item export: one destination folder picked once, each
        preset auto-named inside it from its own device-prefixed name (no
        per-file dialog -- picking N filenames one at a time doesn't scale,
        and Copy/Delete don't ask per-item either)."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Export Presets To Folder",
            self._settings.rew_folder or str(Path.home()),
        )
        if not folder:
            logger.debug("Multi-preset export cancelled")
            return

        requests = []
        for item in items:
            name, preset_type, is_custom = self._preset_item_identity(item)
            path = str(Path(folder) / f"{self._device_prefixed_name(name)}.txt")
            requests.append((name, preset_type, path, is_custom))
        self._status_banner.show_progress(f"Exporting {len(requests)} preset(s)...")
        self._primary_workflows.export_presets(requests)
        logger.info(
            "Batch preset export requested: %d preset(s) -> %s", len(requests), folder
        )

    @Slot(list)
    def _on_preset_save_requested(self, items: list[Any]) -> None:
        """Handle PresetsDeviceView "Save to My Presets" for selected items.

        Reads filters from device for each selected item and saves to local
        profile repository -- every selected item, not just the first
        (#165c follow-up). No dialog needed regardless of selection size:
        the saved name is always auto-derived from the device name, same as
        the single-item case always was.

        Args:
            items: List of PresetItem objects selected for saving.
        """
        if not items:
            return

        if not self._confirm_preset_preview(items):
            return

        requests = []
        for item in items:
            name, preset_type, is_custom = self._preset_item_identity(item)
            # Device-prefixed only for the locally-saved Profile's name --
            # `name` itself stays exactly as the device reports it, since
            # it's also the on-device lookup key the read uses.
            local_name = self._device_prefixed_name(name)
            requests.append((name, preset_type, local_name, is_custom))
        if len(requests) == 1:
            self._status_banner.show_progress(f"Saving '{requests[0][0]}' to My Presets...")
        else:
            self._status_banner.show_progress(
                f"Saving {len(requests)} preset(s) to My Presets..."
            )
        self._primary_workflows.save_presets(requests)
        logger.info("Preset save requested: %s", [name for name, *_ in requests])

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
        DevicePickerDialog, rather than a plain QMessageBox, so every
        "this will change state" confirmation in the app reads consistently.

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
        flow. Returns None when there's nothing to warn about (all-RoomFit,
        or the synthetic "Custom" row, selection) -- see
        `_confirm_preset_preview()`'s docstring for why RoomFit is excluded;
        "Custom" (#165c) is excluded for the same reason a live read is
        preferred over the named-preset path in the first place -- it's
        already live, so reading it never "temporarily activates" anything.
        """
        peq_items = [
            i
            for i in items
            if getattr(i, "preset_type", "PEQ") != "RoomFit"
            and not getattr(i, "is_custom", False)
        ]
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
        export, save-to-My-Presets, Filters-step Device selection) -- only
        about the *source* device's brief read, not any device being written
        to (see `_copy_activation_warning_html()` for Copy-to-Device's
        separate, write-side concern, folded directly into
        `DevicePickerDialog` rather than shown as its own standalone confirm).
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
        """Handle profile recall — populate ReviewPage and advance.

        Loads the recalled filters into the wizard state and ReviewPage,
        then advances to the Review step (only reachable from the Filters
        step's Local Library selection, so a plain advance() is correct
        here -- same normal-advance path every other filters producer uses).
        Uses L/R display when channel_mode was set by
        _on_local_profile_selected.

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
            try:
                left, right = require_lr_filters(state.filters_l, state.filters_r)
            except ValueError as exc:
                self._status_banner.show_error(f"Could not load preset: {exc}")
                return
            self._review_page.set_lr_filters(left, right)
        else:
            self._review_page.set_filters(filters)

        active_bands = sum(1 for f in filters if getattr(f, "enabled", True))

        self._confirm_filters_selection()
        self._wizard_controller.advance(
            summary=self._resolve_filters_summary(len(filters)),
            tooltip=state.filters_origin,
        )

        self._status_banner.show_success(
            f"Profile loaded: {active_bands} bands ready for review"
        )

    @Slot(bool, str)
    def _on_undo_complete(self, success: bool, message: str) -> None:
        """Handle undo completion — show result on PushPage and StatusBanner.

        Requirement 18.4: Display "Previous filters restored" on success.

        Args:
            success: Whether the undo succeeded.
            message: Human-readable result message.
        """
        if success:
            self._push_page.set_undo_success(message)
            self._clear_pushed_snapshot()
            self._status_banner.show_success(message)
        else:
            self._push_page.set_undo_failure(message)
            self._status_banner.show_error(f"Undo failed: {message}")

    @Slot(int, int, str)
    def _on_undo_multi_source_complete(
        self, succeeded: int, failed: int, message: str
    ) -> None:
        """Handle multi-source undo completion — show result on PushPage
        and StatusBanner.

        Unlike _on_undo_complete's binary success flag, a multi-source undo
        can partially succeed: the pushed-filters snapshot must be cleared
        whenever any source was actually restored (succeeded > 0), which is
        independent of whether the banner shows success (failed == 0) —
        these conditions only coincide for the single-source undo paths.

        Args:
            succeeded: Number of sources actually restored (each source's
                real SafeWrite.undo() outcome, awaited directly -- see
                SecondaryWorkflowManager._do_undo_multi_source docstring).
            failed: Number of sources whose restore failed.
            message: Human-readable result summary.
        """
        if succeeded > 0:
            self._clear_pushed_snapshot()
        if failed == 0:
            self._push_page.set_undo_success(message)
            self._status_banner.show_success(message)
        else:
            self._push_page.set_undo_failure(message)
            self._status_banner.show_error(message)

    def _on_copy_item_failed(self, detail: str) -> None:
        """Handle SecondaryWorkflowManager.copy_item_failed — accumulate a
        per-item failure detail line for the current copy batch.

        Consumed by _on_copy_batch_complete once the whole batch finishes;
        reset to [] by each dispatch handler right before starting a new
        batch (_on_copy_to_device_requested /
        _on_local_preset_copy_to_device_requested).
        """
        self._copy_batch_failures.append(detail)

    @Slot(int, int, int, int, str)
    def _on_copy_batch_complete(
        self, n_items: int, n_devices: int, succeeded: int, failed: int, item_label: str
    ) -> None:
        """Handle SecondaryWorkflowManager.copy_batch_complete — show result
        in StatusBanner (smoke #73, #78).

        item_label ("preset"/"profile") lets the success message name what
        was actually copied instead of always saying "preset(s)", which was
        wrong for a local-Profile-to-device copy (smoke #269 follow-up).

        On any failure, also shows the per-item detail lines accumulated via
        copy_item_failed in a dialog -- the StatusBanner's aggregate count
        alone doesn't say which device/item failed or why (e.g. "device
        doesn't support RoomFit" vs. a connection drop), which left the user
        no way to tell a capability mismatch from a transient failure
        without reading app.log.
        """
        total_ops = n_items * n_devices
        if failed == 0:
            self._status_banner.show_success(
                f"{n_items} {item_label}(s) copied to {n_devices} device(s)"
            )
            return

        self._status_banner.show_error(
            f"Copied {succeeded} of {total_ops} operations ({failed} failed)"
        )
        if self._copy_batch_failures:
            QMessageBox.warning(
                self,
                "Some Copies Failed",
                "Nothing was written to a device for these failed "
                "operations:\n\n"
                + "\n".join(f"• {line}" for line in self._copy_batch_failures),
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
        # Read through state.filters (not current_filters directly): in L/R
        # mode the real payload lives in filters_l/filters_r, which the
        # accessor prefers -- checking only current_filters would miss
        # unpushed L/R-only work, silently destroying it on device switch
        # or app close (the same field-subset gap class as #247).
        state = self._wizard_controller.state
        filters = state.filters
        return len(filters) > 0 and filters != state.last_pushed_filters

