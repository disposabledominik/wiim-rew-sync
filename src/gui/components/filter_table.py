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

from src.gui.constants import ACCENT_COLOR, WARNING_COLOR_DARK, WARNING_COLOR_LIGHT
from src.gui.theme import get_active_theme
from src.models.canonical import CanonicalFilter
from src.models.constants import GAIN_MAX, GAIN_MIN, Q_MAX, Q_MIN
from src.translator._warnings import FilterRow, SkippedBand

_HEADERS = ["Band", "Type", "Freq", "Gain", "Q"]

_SKIPPED_OPACITY = 0.45
_HIGHLIGHT_ALPHA = 40  # Accent background alpha for comparison highlights
_NA_LABEL = "N/A"
# QTabWidget::pane's QSS chrome (1px border + 8px padding on each side, see
# fluent_dark.qss/fluent_light.qss) isn't reflected in tabBar().sizeHint() or
# any table metric -- set_lr_filters() must add it explicitly to the height
# budget or the tab content clips by this many px with the vertical
# scrollbar forced off.
_TAB_PANE_CHROME = 18


class FilterTable(QWidget):
    """Read-only filter table with fixed column widths.

    Displays CanonicalFilter bands with support for:
    - Simple stereo display with optional clamping indicators
    - L/R tabbed display via QTabWidget
    - Comparison (diff) view highlighting changed bands

    Expands to fill its parent's available width (see
    `FILTER_TABLE_MAX_WIDTH` in `src/gui/constants.py` for the width cap
    the caller, `ReviewPage`, applies) rather than sizing to its content.
    Height is different: it grows only up to the natural height needed to
    show every row without internal scrolling (recomputed on every
    set_filters/set_lr_filters/set_comparison call), then stops -- there's
    no value in an empty-looking table stretching to fill a tall window
    once all its rows are already visible.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FilterTable")
        # Expanding (not the default Preferred) so the table grows to fill
        # spare space given to it by the caller's layout instead of sizing
        # down to its content's sizeHint.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

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
        rows: list[FilterRow] | None = None,
        notes_map: dict[int, list[str]] | None = None,
    ) -> None:
        """Populate the table with filter bands.

        Args:
            filters: List of CanonicalFilter instances (index = band number - 1).
            clamping_map: Optional mapping of band index (0-based) to list of
                clamping reason strings. Clamped bands show an orange dot
                indicator with a tooltip.
            rows: Optional display rows in original order, interleaving
                SkippedBand placeholders for unsupported/truncated bands.
                When omitted, every entry in `filters` gets a sequential
                band number, matching the previous (pre-B3) behavior.
            notes_map: Optional mapping of band index (0-based) to list of
                conversion-note strings — values REW didn't specify and had to
                be substituted (e.g. the fixed Q applied to a bare LP/HP).
                Shown as a distinct (non-warning) indicator with a tooltip.
        """
        self._clear_widgets()
        table = self._create_table()
        self._container_layout.addWidget(table)
        self._table = table
        self._populate_table(table, filters, clamping_map, rows, notes_map)
        self._apply_natural_max_height(table)

    def set_lr_filters(
        self,
        left: list[CanonicalFilter],
        right: list[CanonicalFilter],
        clamping_map_l: dict[int, list[str]] | None = None,
        clamping_map_r: dict[int, list[str]] | None = None,
        rows_l: list[FilterRow] | None = None,
        rows_r: list[FilterRow] | None = None,
        notes_map_l: dict[int, list[str]] | None = None,
        notes_map_r: dict[int, list[str]] | None = None,
    ) -> None:
        """Display L/R channels as tabbed sections.

        Args:
            left: Filters for the left channel.
            right: Filters for the right channel.
            clamping_map_l: Optional clamping map for the left channel.
            clamping_map_r: Optional clamping map for the right channel.
            rows_l: Optional display rows for the left channel (see set_filters).
            rows_r: Optional display rows for the right channel (see set_filters).
            notes_map_l: Optional conversion-notes map for the left channel.
            notes_map_r: Optional conversion-notes map for the right channel.
        """
        self._clear_widgets()
        tab_widget = QTabWidget(self._container)
        tab_widget.setObjectName("FilterTableTabs")

        left_table = self._create_table()
        self._populate_table(left_table, left, clamping_map_l, rows_l, notes_map_l)
        tab_widget.addTab(left_table, "Left Channel")

        right_table = self._create_table()
        self._populate_table(right_table, right, clamping_map_r, rows_r, notes_map_r)
        tab_widget.addTab(right_table, "Right Channel")

        self._container_layout.addWidget(tab_widget)
        self._tab_widget = tab_widget
        tallest_table_height = max(
            self._natural_table_height(left_table), self._natural_table_height(right_table)
        )
        tab_bar_height = tab_widget.tabBar().sizeHint().height()
        self.setMaximumHeight(tallest_table_height + tab_bar_height + _TAB_PANE_CHROME)

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
        self._apply_natural_max_height(table)

    def clear(self) -> None:
        """Remove all data and widgets."""
        self._clear_widgets()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_natural_max_height(self, table: QTableWidget) -> None:
        """Cap self's height to *table*'s natural (all-rows-visible) height."""
        self.setMaximumHeight(self._natural_table_height(table))

    @staticmethod
    def _natural_table_height(table: QTableWidget) -> int:
        """Height needed to show every row of *table* without scrolling.

        `verticalHeader().length()` is the sum of all row heights (not just
        the visible ones), so this is accurate even before the table has
        been shown/laid out on screen.
        """
        header_height = table.horizontalHeader().height()
        rows_height = table.verticalHeader().length()
        frame = 2 * table.frameWidth()
        return header_height + rows_height + frame

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
        # Disable vertical scrollbar too -- the widget's height is always capped
        # to _natural_table_height() right after populating, so every row is
        # already visible; ScrollBarAsNeeded could still fire a needless
        # scrollbar if that estimate is ever a couple px short of the real
        # content height (QSS border/padding isn't fully reflected in
        # frameWidth()). Safe to force off here because the height is fully
        # computed/controlled by this class, not sized by the user.
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        return table

    def _populate_table(
        self,
        table: QTableWidget,
        filters: list[CanonicalFilter],
        clamping_map: dict[int, list[str]] | None = None,
        rows: list[FilterRow] | None = None,
        notes_map: dict[int, list[str]] | None = None,
    ) -> None:
        """Fill table rows from filter list, interleaving skipped placeholders.

        Args:
            table: Target QTableWidget.
            filters: Filter data to display (used directly when `rows` is None).
            clamping_map: Optional clamping indicators, keyed by band number
                (0-based, counting only the valid/numbered rows).
            rows: Optional display rows in original order; SkippedBand entries
                render as unnumbered, crossed-out placeholders.
            notes_map: Optional conversion-note indicators, keyed the same way
                as clamping_map.
        """
        display_rows: list[FilterRow] = rows if rows is not None else list(filters)
        table.setRowCount(len(display_rows))

        band_number = 0
        for table_row, entry in enumerate(display_rows):
            if isinstance(entry, SkippedBand):
                self._populate_skipped_row(table, table_row, entry)
                continue

            self._populate_filter_row(
                table, table_row, entry, band_number, clamping_map, notes_map
            )
            band_number += 1

    def _populate_filter_row(
        self,
        table: QTableWidget,
        row: int,
        filt: CanonicalFilter,
        band_number: int,
        clamping_map: dict[int, list[str]] | None,
        notes_map: dict[int, list[str]] | None = None,
    ) -> None:
        """Fill one row for a usable filter, at the given band number."""
        is_clamped = clamping_map is not None and band_number in clamping_map

        # Band number (1-based)
        band_item = QTableWidgetItem(str(band_number + 1))
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

        # Gain \u2014 cell shows the value that will actually be written (clamped
        # if needed); tooltip carries the original value and the reason.
        gain_clamped = False
        if is_clamped and clamping_map is not None:
            reasons = clamping_map[band_number]
            gain_clamped = any("gain" in r.lower() for r in reasons)
        display_gain = (
            max(GAIN_MIN, min(GAIN_MAX, filt.gain_db)) if gain_clamped else filt.gain_db
        )
        gain_text = self._format_gain(display_gain)
        if gain_clamped:
            gain_text = f"\u25cf {gain_text}"  # Orange dot prefix
        gain_item = QTableWidgetItem(gain_text)
        gain_item.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        if gain_clamped and clamping_map is not None:
            gain_reasons = [r for r in clamping_map[band_number] if "gain" in r.lower()]
            gain_item.setToolTip(
                f"Original: {self._format_gain(filt.gain_db)}. "
                + "Clamped: " + "; ".join(gain_reasons)
            )
            gain_item.setForeground(self._warning_color())
        table.setItem(row, 3, gain_item)

        # Q factor \u2014 same cell/tooltip swap as gain
        q_clamped = False
        if is_clamped and clamping_map is not None:
            reasons = clamping_map[band_number]
            q_clamped = any("q" in r.lower() for r in reasons)
        band_notes = notes_map.get(band_number, []) if notes_map else []
        display_q = max(Q_MIN, min(Q_MAX, filt.q)) if q_clamped else filt.q
        q_text = f"{display_q:.2f}"
        if q_clamped or band_notes:
            q_text = f"\u25cf {q_text}"  # Dot prefix (orange=clamped, accent=note)
        q_item = QTableWidgetItem(q_text)
        q_item.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        if q_clamped and clamping_map is not None:
            q_reasons = [r for r in clamping_map[band_number] if "q" in r.lower()]
            q_item.setToolTip(
                f"Original: {filt.q:.2f}. Clamped: " + "; ".join(q_reasons)
            )
            q_item.setForeground(self._warning_color())
        elif band_notes:
            q_item.setToolTip("Note: " + "; ".join(band_notes))
            q_item.setForeground(self._note_color())
        table.setItem(row, 4, q_item)

    def _populate_skipped_row(
        self, table: QTableWidget, row: int, skipped: SkippedBand
    ) -> None:
        """Fill one row for a band with no WiiM translation, or cut for the band cap.

        Rendered unnumbered ("N/A"), crossed-out and dimmed, with the reason
        shown on hover.
        """
        band_item = QTableWidgetItem(_NA_LABEL)
        band_item.setTextAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        table.setItem(row, 0, band_item)

        type_item = QTableWidgetItem(skipped.original_type)
        type_item.setTextAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        table.setItem(row, 1, type_item)

        freq_text = (
            self._format_frequency(skipped.frequency_hz)
            if skipped.frequency_hz is not None
            else "\u2014"
        )
        freq_item = QTableWidgetItem(freq_text)
        freq_item.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        table.setItem(row, 2, freq_item)

        gain_text = (
            self._format_gain(skipped.gain_db) if skipped.gain_db is not None else "\u2014"
        )
        gain_item = QTableWidgetItem(gain_text)
        gain_item.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        table.setItem(row, 3, gain_item)

        q_text = f"{skipped.q:.2f}" if skipped.q is not None else "\u2014"
        q_item = QTableWidgetItem(q_text)
        q_item.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        table.setItem(row, 4, q_item)

        self._apply_skipped_style(table, row, skipped.reason)

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

    @staticmethod
    def _warning_color() -> QColor:
        """Return the clamping-warning foreground color for the active theme."""
        hex_color = (
            WARNING_COLOR_DARK if get_active_theme() == "dark" else WARNING_COLOR_LIGHT
        )
        return QColor(hex_color)

    @staticmethod
    def _note_color() -> QColor:
        """Return the conversion-note foreground color (accent, not a warning)."""
        return QColor(ACCENT_COLOR)

    def _apply_skipped_style(self, table: QTableWidget, row: int, reason: str) -> None:
        """Apply crossed-out, dimmed styling and a reason tooltip to a skipped row."""
        for col in range(table.columnCount()):
            item = table.item(row, col)
            if item is None:
                continue
            font = item.font()
            font.setStrikeOut(True)
            item.setFont(font)
            color = item.foreground().color()
            color.setAlphaF(_SKIPPED_OPACITY)
            item.setForeground(color)
            item.setToolTip(reason)

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
