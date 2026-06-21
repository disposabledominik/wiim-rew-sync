"""FilterTable — read-only filter display with stretch columns.

Displays parametric EQ filter bands in a table that expands to fill
available width. Supports stereo display, L/R tabbed display, and
comparison (diff) mode with visual indicators for disabled bands and
clamped values.

Requirements referenced: 5.1, 5.2, 5.3, 5.5, 19.2, 19.3.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.gui.constants import WARNING_COLOR
from src.models.canonical import CanonicalFilter

_HEADERS = ["Band", "Type", "Freq", "Gain", "Q"]

_DISABLED_OPACITY = 0.5
_HIGHLIGHT_ALPHA = 40  # Accent background alpha for comparison highlights


class FilterTable(QWidget):
    """Read-only filter table with fixed column widths.

    Displays CanonicalFilter bands with support for:
    - Simple stereo display with optional clamping indicators
    - L/R tabbed display via QTabWidget
    - Comparison (diff) view highlighting changed bands

    The table is centered horizontally and constrained to a max width
    of ~400px for compact readability.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FilterTable")

        # Let table expand to fill available parent space
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self._container = QWidget(self)
        self._container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(0)

        outer_layout.addWidget(self._container)

        # Lazily created widgets
        self._table: QTableWidget | None = None
        self._tab_widget: QTabWidget | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_filters(
        self,
        filters: list[CanonicalFilter],
        clamping_map: dict[int, list[str]] | None = None,
    ) -> None:
        """Populate the table with filter bands.

        Args:
            filters: List of CanonicalFilter instances (index = band number - 1).
            clamping_map: Optional mapping of band index (0-based) to list of
                clamping reason strings. Clamped bands show an orange dot
                indicator with a tooltip.
        """
        self._clear_widgets()
        table = self._create_table()
        self._container_layout.addWidget(table)
        self._table = table
        self._populate_table(table, filters, clamping_map)

    def set_lr_filters(
        self,
        left: list[CanonicalFilter],
        right: list[CanonicalFilter],
        clamping_map: dict[int, list[str]] | None = None,
    ) -> None:
        """Display L/R channels as tabbed sections.

        Args:
            left: Filters for the left channel.
            right: Filters for the right channel.
            clamping_map: Optional clamping map applied to both channels.
        """
        self._clear_widgets()
        tab_widget = QTabWidget(self._container)
        tab_widget.setObjectName("FilterTableTabs")

        left_table = self._create_table()
        self._populate_table(left_table, left, clamping_map)
        tab_widget.addTab(left_table, "L")

        right_table = self._create_table()
        self._populate_table(right_table, right, clamping_map)
        tab_widget.addTab(right_table, "R")

        self._container_layout.addWidget(tab_widget)
        self._tab_widget = tab_widget

    def set_comparison(
        self,
        before: list[CanonicalFilter],
        after: list[CanonicalFilter],
    ) -> None:
        """Show diff view highlighting changed bands.

        Changed rows get an accent background highlight. The gain column
        shows the difference as "+X.X dB" or "-X.X dB".

        Args:
            before: Filters representing the current/device state.
            after: Filters representing the incoming/new state.
        """
        self._clear_widgets()
        table = self._create_table()
        self._container_layout.addWidget(table)
        self._table = table
        self._populate_comparison(table, before, after)

    def clear(self) -> None:
        """Remove all data and widgets."""
        self._clear_widgets()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _clear_widgets(self) -> None:
        """Remove existing table or tab widget from the container."""
        if self._table is not None:
            self._container_layout.removeWidget(self._table)
            self._table.deleteLater()
            self._table = None
        if self._tab_widget is not None:
            self._container_layout.removeWidget(self._tab_widget)
            self._tab_widget.deleteLater()
            self._tab_widget = None

    def _create_table(self) -> QTableWidget:
        """Create a configured QTableWidget with stretch columns."""
        table = QTableWidget(0, len(_HEADERS), self._container)
        table.setObjectName("FilterTableGrid")
        table.setHorizontalHeaderLabels(_HEADERS)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Columns stretch to fill available width
        header = table.horizontalHeader()
        header.setStretchLastSection(True)
        for col in range(len(_HEADERS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)

        # Disable horizontal scrollbar — all columns visible
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        return table

    def _populate_table(
        self,
        table: QTableWidget,
        filters: list[CanonicalFilter],
        clamping_map: dict[int, list[str]] | None = None,
    ) -> None:
        """Fill table rows from filter list.

        Args:
            table: Target QTableWidget.
            filters: Filter data to display.
            clamping_map: Optional clamping indicators.
        """
        table.setRowCount(len(filters))

        for row, filt in enumerate(filters):
            is_disabled = filt.type == "OFF"
            is_clamped = clamping_map is not None and row in clamping_map

            # Band number (1-based)
            band_item = QTableWidgetItem(str(row + 1))
            band_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
            table.setItem(row, 0, band_item)

            # Filter type
            type_text = self._format_type(filt)
            type_item = QTableWidgetItem(type_text)
            type_item.setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            table.setItem(row, 1, type_item)

            # Frequency
            freq_text = self._format_frequency(filt.frequency_hz)
            freq_item = QTableWidgetItem(freq_text)
            freq_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            table.setItem(row, 2, freq_item)

            # Gain
            gain_text = self._format_gain(filt.gain_db)
            if is_clamped:
                reasons = clamping_map[row] if clamping_map else []
                gain_text = f"\u25cf {gain_text}"  # Orange dot prefix
            gain_item = QTableWidgetItem(gain_text)
            gain_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            if is_clamped and clamping_map is not None:
                reasons = clamping_map[row]
                tooltip = "Clamped: " + "; ".join(reasons)
                gain_item.setToolTip(tooltip)
                gain_item.setForeground(QColor(WARNING_COLOR))
            table.setItem(row, 3, gain_item)

            # Q factor
            q_text = f"{filt.q:.2f}"
            q_item = QTableWidgetItem(q_text)
            q_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            table.setItem(row, 4, q_item)

            # Disabled/OFF bands at reduced opacity
            if is_disabled:
                self._apply_disabled_style(table, row)

    def _populate_comparison(
        self,
        table: QTableWidget,
        before: list[CanonicalFilter],
        after: list[CanonicalFilter],
    ) -> None:
        """Fill table with comparison data, highlighting changes.

        Args:
            table: Target QTableWidget.
            before: Current/device filters.
            after: Incoming/new filters.
        """
        # Use the longer list length to handle mismatched sizes
        row_count = max(len(before), len(after))
        table.setRowCount(row_count)

        for row in range(row_count):
            before_filt = before[row] if row < len(before) else None
            after_filt = after[row] if row < len(after) else None

            # Determine if this row changed
            changed = self._filters_differ(before_filt, after_filt)

            # Use after filter for display (the incoming state)
            display_filt = after_filt or before_filt
            if display_filt is None:
                continue

            is_disabled = display_filt.type == "OFF"

            # Band number
            band_item = QTableWidgetItem(str(row + 1))
            band_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
            table.setItem(row, 0, band_item)

            # Type
            type_item = QTableWidgetItem(self._format_type(display_filt))
            type_item.setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            table.setItem(row, 1, type_item)

            # Frequency
            freq_item = QTableWidgetItem(self._format_frequency(display_filt.frequency_hz))
            freq_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            table.setItem(row, 2, freq_item)

            # Gain with diff indicator
            gain_text = self._format_gain(display_filt.gain_db)
            if changed and before_filt is not None and after_filt is not None:
                diff = after_filt.gain_db - before_filt.gain_db
                if abs(diff) > 0.01:
                    diff_str = f"+{diff:.1f}" if diff > 0 else f"{diff:.1f}"
                    gain_text = f"{gain_text} ({diff_str} dB)"
            gain_item = QTableWidgetItem(gain_text)
            gain_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            table.setItem(row, 3, gain_item)

            # Q
            q_item = QTableWidgetItem(f"{display_filt.q:.2f}")
            q_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            table.setItem(row, 4, q_item)

            # Highlight changed rows
            if changed:
                self._apply_highlight_style(table, row)

            # Disabled styling (applied after highlight for proper layering)
            if is_disabled:
                self._apply_disabled_style(table, row)

    def _filters_differ(
        self,
        a: CanonicalFilter | None,
        b: CanonicalFilter | None,
    ) -> bool:
        """Check if two filters differ in any visible parameter."""
        if a is None or b is None:
            return True
        return (
            a.type != b.type
            or abs(a.frequency_hz - b.frequency_hz) > 0.01
            or abs(a.gain_db - b.gain_db) > 0.01
            or abs(a.q - b.q) > 0.001
        )

    def _apply_disabled_style(self, table: QTableWidget, row: int) -> None:
        """Apply 0.5 opacity visual to a disabled/OFF band row."""
        for col in range(table.columnCount()):
            item = table.item(row, col)
            if item is not None:
                color = item.foreground().color()
                color.setAlphaF(_DISABLED_OPACITY)
                item.setForeground(color)

    def _apply_highlight_style(self, table: QTableWidget, row: int) -> None:
        """Apply accent background to a changed row in comparison mode."""
        from src.gui.constants import ACCENT_COLOR

        highlight = QColor(ACCENT_COLOR)
        highlight.setAlpha(_HIGHLIGHT_ALPHA)
        for col in range(table.columnCount()):
            item = table.item(row, col)
            if item is not None:
                item.setBackground(highlight)

    @staticmethod
    def _format_type(filt: CanonicalFilter) -> str:
        """Format filter type for display."""
        type_labels: dict[str, str] = {
            "PEAK": "PK",
            "LS": "LS",
            "HS": "HS",
            "LP": "LP",
            "HP": "HP",
            "OFF": "OFF",
            "UNKNOWN": "??",
        }
        return type_labels.get(filt.type, filt.type)

    @staticmethod
    def _format_frequency(hz: float) -> str:
        """Format frequency value with appropriate units."""
        if hz >= 1000:
            return f"{hz / 1000:.2f} kHz"
        return f"{hz:.0f} Hz"

    @staticmethod
    def _format_gain(gain_db: float) -> str:
        """Format gain value with sign and unit."""
        if gain_db >= 0:
            return f"+{gain_db:.1f} dB"
        return f"{gain_db:.1f} dB"
