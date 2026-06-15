"""Main application window for WiiM <-> REW PEQ Sync.

Provides the top-level layout with placeholder panels, a diagnostics dock,
status bar with progress indicator, and connection to the AsyncBridge for
clean shutdown.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QMainWindow,
    QProgressBar,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.gui.async_bridge import AsyncBridge
from src.gui.panels.device_panel import DevicePanel
from src.gui.panels.eq_panel import EQPanel


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
            +-- DevicePanel placeholder (fixed height ~120px)
            +-- QSplitter (horizontal)
            |   +-- SourceModePanel placeholder (fixed width ~200px)
            |   +-- EQPanel placeholder (fills remaining)
            +-- ActionBar placeholder (fixed height ~50px)
            +-- QTabWidget
                +-- ProfilePanel placeholder tab

    Also includes:
        - QDockWidget for diagnostics (hidden by default, toggle via View menu)
        - Status bar with indeterminate QProgressBar
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

        # Action bar placeholder (fixed height ~50px)
        action_bar = _make_placeholder("[Action Bar]")
        action_bar.setMinimumHeight(40)
        action_bar.setMaximumHeight(60)
        main_splitter.addWidget(action_bar)

        # Tab widget for profiles
        tab_widget = QTabWidget()
        profile_tab = _make_placeholder("[Profile Panel]")
        tab_widget.addTab(profile_tab, "Profiles")
        main_splitter.addWidget(tab_widget)

        # Set stretch factors: device + action fixed, middle + tabs fill
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setStretchFactor(2, 0)
        main_splitter.setStretchFactor(3, 1)

        self.setCentralWidget(main_splitter)

    def _setup_dock_widget(self) -> None:
        """Create the diagnostics dock widget (hidden by default)."""
        self._diagnostics_dock = QDockWidget("Diagnostics", self)
        self._diagnostics_dock.setObjectName("diagnostics_dock")

        diagnostics_content = _make_placeholder("[Diagnostics Panel]")
        self._diagnostics_dock.setWidget(diagnostics_content)

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
        """Connect AsyncBridge signals to status bar indicators and panels."""
        self._bridge.operation_started.connect(self._on_operation_started)
        self._bridge.operation_finished.connect(self._on_operation_finished)
        self._bridge.progress_update.connect(self._on_progress_update)

        # Device panel wiring
        self._bridge.discovery_complete.connect(self._device_panel.on_discovery_complete)
        # TODO: Wire refresh_requested to actual discovery coroutine in a later task
        self._device_panel.refresh_requested.connect(self._on_device_refresh_requested)

        # EQ panel wiring
        self._bridge.capabilities_ready.connect(self._eq_panel.on_capabilities_ready)
        self._bridge.peq_ready.connect(self._eq_panel.on_peq_ready)

    def _on_device_refresh_requested(self) -> None:
        """Handle device panel refresh request.

        TODO: Call self._bridge.run_async(discover_devices()) once discovery
        is wired into the GUI layer.
        """

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

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close by shutting down the async bridge.

        Args:
            event: The close event.
        """
        self._bridge.shutdown()
        super().closeEvent(event)
