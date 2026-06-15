"""EQ display panel with source selector, channel mode, and filter tables.

Provides PEQ and RoomFit tabs with read-only filter tables. Emits signals
for pull/push operations - does NOT perform any network I/O directly.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceCapabilities
from src.models.peq import PEQSettings

_FILTER_TABLE_COLUMNS = ["Band", "Type", "Frequency (Hz)", "Gain (dB)", "Q"]
_DEFAULT_MAX_FILTERS = 10


class EQPanel(QWidget):
    """EQ display panel with source selector, channel mode, and PEQ/RoomFit tabs.

    Signals:
        pull_requested: Emitted when PEQ Pull is clicked. Payload: (source_name, channel_mode).
        roomfit_pull_requested: Emitted when RoomFit Pull is clicked.
            Payload: (source_name, profile_name).
        roomfit_push_requested: Emitted when RoomFit Push is clicked.
            Payload: (source_name, profile_name).
    """

    pull_requested = Signal(str, str)
    roomfit_pull_requested = Signal(str, str)
    roomfit_push_requested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the EQ panel.

        Args:
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self._max_filters = _DEFAULT_MAX_FILTERS
        self._capabilities: DeviceCapabilities | None = None
        self._setup_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the panel layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Top row: source selector + channel mode
        top_row = QHBoxLayout()

        top_row.addWidget(QLabel("Source:"))
        self._source_combo = QComboBox()
        self._source_combo.setMinimumWidth(120)
        self._source_combo.setPlaceholderText("Select source...")
        top_row.addWidget(self._source_combo)

        top_row.addSpacing(16)

        top_row.addWidget(QLabel("Channel:"))
        self._channel_combo = QComboBox()
        self._channel_combo.addItems(["Stereo", "Left", "Right"])
        self._channel_combo.setEnabled(False)
        top_row.addWidget(self._channel_combo)

        top_row.addStretch()
        layout.addLayout(top_row)

        # Tab widget: PEQ + RoomFit
        self._tab_widget = QTabWidget()
        self._setup_peq_tab()
        self._setup_roomfit_tab()
        layout.addWidget(self._tab_widget)

    def _setup_peq_tab(self) -> None:
        """Build the PEQ tab with pull button and filter table."""
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)

        # Controls row
        controls = QHBoxLayout()
        self._peq_pull_btn = QPushButton("Pull from Device")
        self._peq_pull_btn.setEnabled(False)
        controls.addWidget(self._peq_pull_btn)
        controls.addStretch()
        tab_layout.addLayout(controls)

        # Filter table
        self._peq_table = self._create_filter_table()
        tab_layout.addWidget(self._peq_table)

        self._tab_widget.addTab(tab, "PEQ")

    def _setup_roomfit_tab(self) -> None:
        """Build the RoomFit tab with profile controls and filter table."""
        self._roomfit_tab = QWidget()
        tab_layout = QVBoxLayout(self._roomfit_tab)

        # Profile selector row
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile:"))
        self._roomfit_profile_combo = QComboBox()
        self._roomfit_profile_combo.setMinimumWidth(150)
        self._roomfit_profile_combo.setPlaceholderText("Select profile...")
        profile_row.addWidget(self._roomfit_profile_combo)

        self._roomfit_refresh_btn = QPushButton("Refresh")
        profile_row.addWidget(self._roomfit_refresh_btn)
        profile_row.addStretch()
        tab_layout.addLayout(profile_row)

        # Action buttons row
        actions_row = QHBoxLayout()
        self._roomfit_pull_btn = QPushButton("Pull from Device")
        self._roomfit_pull_btn.setEnabled(False)
        actions_row.addWidget(self._roomfit_pull_btn)

        self._roomfit_push_btn = QPushButton("Push to Device")
        self._roomfit_push_btn.setEnabled(False)
        actions_row.addWidget(self._roomfit_push_btn)

        actions_row.addSpacing(16)
        actions_row.addWidget(QLabel("New profile:"))
        self._roomfit_name_input = QLineEdit()
        self._roomfit_name_input.setPlaceholderText("Profile name...")
        self._roomfit_name_input.setMaximumWidth(200)
        actions_row.addWidget(self._roomfit_name_input)

        actions_row.addStretch()
        tab_layout.addLayout(actions_row)

        # Filter table
        self._roomfit_table = self._create_filter_table()
        tab_layout.addWidget(self._roomfit_table)

        self._tab_widget.addTab(self._roomfit_tab, "RoomFit")
        # Hidden by default until capabilities say otherwise
        self._tab_widget.setTabVisible(1, False)

    def _create_filter_table(self) -> QTableWidget:
        """Create a read-only filter table widget.

        Returns:
            Configured QTableWidget with standard EQ columns.
        """
        table = QTableWidget()
        table.setColumnCount(len(_FILTER_TABLE_COLUMNS))
        table.setHorizontalHeaderLabels(_FILTER_TABLE_COLUMNS)
        table.setRowCount(self._max_filters)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        self._clear_table(table)
        return table

    # ------------------------------------------------------------------
    # Signal Connections
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """Wire internal widget signals."""
        self._peq_pull_btn.clicked.connect(self._on_peq_pull_clicked)
        self._roomfit_pull_btn.clicked.connect(self._on_roomfit_pull_clicked)
        self._roomfit_push_btn.clicked.connect(self._on_roomfit_push_clicked)

    def _on_peq_pull_clicked(self) -> None:
        """Handle PEQ Pull button click."""
        source = self._source_combo.currentText()
        if not source:
            return
        channel = self._channel_combo.currentText()
        self.pull_requested.emit(source, channel)

    def _on_roomfit_pull_clicked(self) -> None:
        """Handle RoomFit Pull button click."""
        source = self._source_combo.currentText()
        profile = self._roomfit_profile_combo.currentText()
        if not source or not profile:
            return
        if self._check_deactivation_warning(profile):
            self.roomfit_pull_requested.emit(source, profile)

    def _on_roomfit_push_clicked(self) -> None:
        """Handle RoomFit Push button click."""
        source = self._source_combo.currentText()
        profile = self._roomfit_profile_combo.currentText()
        if not source or not profile:
            return
        if self._check_deactivation_warning(profile):
            self.roomfit_push_requested.emit(source, profile)

    # ------------------------------------------------------------------
    # Public Slots
    # ------------------------------------------------------------------

    def on_capabilities_ready(self, capabilities: DeviceCapabilities) -> None:
        """Slot: configure panel based on device capabilities.

        Populates the source list, enables/disables channel mode and RoomFit tab.

        Args:
            capabilities: Probed device capabilities.
        """
        self._capabilities = capabilities

        # Update max filters
        if capabilities.max_filters > 0:
            self._max_filters = capabilities.max_filters
            self._peq_table.setRowCount(self._max_filters)
            self._roomfit_table.setRowCount(self._max_filters)

        # Populate source selector
        self._source_combo.clear()
        for name in capabilities.source_names:
            self._source_combo.addItem(name)
        # No pre-selection
        self._source_combo.setCurrentIndex(-1)

        # Channel mode
        self._channel_combo.setEnabled(capabilities.supports_channel_peq)
        if not capabilities.supports_channel_peq:
            self._channel_combo.setCurrentIndex(0)  # Force Stereo

        # PEQ pull button
        self._peq_pull_btn.setEnabled(capabilities.supports_peq)

        # RoomFit tab visibility and button states
        show_roomfit = capabilities.roomfit_level >= 1
        self._tab_widget.setTabVisible(1, show_roomfit)
        if show_roomfit:
            self._roomfit_pull_btn.setEnabled(capabilities.roomfit_level >= 2)
            self._roomfit_push_btn.setEnabled(capabilities.roomfit_level >= 4)

    def on_peq_ready(self, settings: PEQSettings) -> None:
        """Slot: populate the PEQ filter table with device state.

        Args:
            settings: PEQ settings pulled from the device.
        """
        bands = settings.bands
        self._populate_filter_table(self._peq_table, bands)

    def on_roomfit_profiles_ready(self, profiles: list[str]) -> None:
        """Slot: populate the RoomFit profile dropdown.

        Args:
            profiles: List of profile names from the device.
        """
        self._roomfit_profile_combo.clear()
        for name in profiles:
            self._roomfit_profile_combo.addItem(name)
        # No pre-selection
        self._roomfit_profile_combo.setCurrentIndex(-1)

    def on_roomfit_ready(self, settings: PEQSettings) -> None:
        """Slot: populate the RoomFit filter table with device state.

        Args:
            settings: RoomFit settings pulled from the device.
        """
        bands = settings.bands
        self._populate_filter_table(self._roomfit_table, bands)

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _populate_filter_table(
        self, table: QTableWidget, bands: list[CanonicalFilter]
    ) -> None:
        """Fill a filter table with canonical filter data.

        Args:
            table: The QTableWidget to populate.
            bands: List of canonical filters to display.
        """
        table.setRowCount(max(self._max_filters, len(bands)))
        self._clear_table(table)

        for row, band in enumerate(bands):
            self._set_band_row(table, row, band)

    def _set_band_row(
        self, table: QTableWidget, row: int, band: CanonicalFilter
    ) -> None:
        """Set a single row in the filter table.

        Args:
            table: Target table widget.
            row: Row index.
            band: The canonical filter for this band.
        """
        is_off = band.type == "OFF"
        is_unknown = band.type == "UNKNOWN"

        items = [
            str(row + 1),
            band.type,
            f"{band.frequency_hz:.1f}",
            f"{band.gain_db:+.2f}",
            f"{band.q:.4f}",
        ]

        grey = QColor(128, 128, 128)
        italic_font = QFont()
        italic_font.setItalic(True)

        for col, text in enumerate(items):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            if is_off:
                item.setForeground(grey)
                item.setFont(italic_font)
            elif is_unknown:
                item.setForeground(grey)
                item.setToolTip("Unsupported filter type")

            table.setItem(row, col, item)

    def _clear_table(self, table: QTableWidget) -> None:
        """Clear all cells in a filter table.

        Args:
            table: The table to clear.
        """
        for row in range(table.rowCount()):
            for col in range(table.columnCount()):
                table.setItem(row, col, QTableWidgetItem(""))

    def _check_deactivation_warning(self, profile_name: str) -> bool:
        """Check whether saving to the active profile requires a deactivation warning.

        Placeholder implementation - always returns True (proceed).
        The actual dialog will be implemented in a later task.

        Args:
            profile_name: The target RoomFit profile name.

        Returns:
            True if the operation should proceed, False to cancel.
        """
        # TODO: Implement actual deactivation warning dialog (later task)
        _ = profile_name
        return True
