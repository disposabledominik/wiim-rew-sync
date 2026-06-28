"""RewPullView — embedded "Pull from REW" screen.

Lets the user pick a Stereo or L/R measurement from a running REW session
and import its filters. Replaces the previous MeasurementPickerDialog modal
for the sidebar entry point so navigation behaves consistently with the
other sidebar destinations (Presets on Device, My Saved Presets).

The view does NOT talk to REW directly. MainWindow drives it via
:meth:`set_connecting`, :meth:`set_measurements`, and :meth:`set_message`,
and reacts to the :attr:`measurement_selected` / :attr:`back_requested`
signals.

Requirements referenced: 5.2, 5.7.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.adapters.rew_http_client import MeasurementSummary
from src.gui.components.page_layout import (
    build_centered_content,
    make_empty_state_icon,
    make_page_title,
)
from src.gui.constants import SPACING_LG, SPACING_MD, SPACING_SM

#: Tall enough to show ~8-10 measurement rows before scrolling kicks in,
#: since a real REW library can hold 60+ measurements.
_LIST_MIN_HEIGHT = 220


class RewPullView(QWidget):
    """Embedded screen for selecting REW measurement(s) to import filters from.

    A Stereo/L-R toggle switches between a single measurement list (Stereo)
    and two side-by-side Left/Right lists (L/R), both populated from the
    same measurement list. While waiting on REW or when there is nothing to
    show (no measurements, connection error), a placeholder message is
    shown instead of the picker.

    Signals:
        measurement_selected(object): Emitted with a single MeasurementSummary
            (Stereo) or a (left, right) tuple (L/R) when the user confirms.
        back_requested(): User clicked Back/Cancel — caller should navigate
            away and reset any in-progress REW pull state.
    """

    measurement_selected = Signal(object)
    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None, show_title: bool = True) -> None:
        """Initialize the view.

        Args:
            parent: Parent widget (may be None).
            show_title: Whether to show the "Pull from REW" title. Pass
                False when embedding inside a page that already has its
                own title (e.g. FiltersPage's "Import REW Filters").
        """
        super().__init__(parent)
        self.setObjectName("RewPullView")
        self._setup_ui()
        self._title.setVisible(show_title)
        self._showing_picker = False
        self.set_connecting()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def showing_picker(self) -> bool:
        """Whether the Stereo/L-R picker is currently shown (vs. a placeholder).

        Tracked as explicit state rather than QWidget.isVisible(), since the
        latter is always False until the view's whole ancestor chain has
        actually been shown (e.g. in headless tests).
        """
        return self._showing_picker

    def set_connecting(self) -> None:
        """Show the "Connecting to REW..." placeholder."""
        self.set_message("Connecting to REW...")

    def set_message(self, text: str, icon: str = "") -> None:
        """Show a placeholder message instead of the measurement picker.

        Used for the connecting state, "no measurements found", and
        connection errors.

        Args:
            text: Message to display.
            icon: Optional large icon glyph to show above the message
                (e.g. ICON_NO_CONNECTION, ICON_NO_DATA from page_layout).
                Omit for transient states like "Connecting..." where an
                icon would just flash briefly.
        """
        self._showing_picker = False
        self._message_label.setText(text)
        self._icon_label.setText(icon)
        self._icon_label.setVisible(bool(icon))
        self._content_widget.setVisible(False)
        self._placeholder_widget.setVisible(True)

    def set_measurements(self, measurements: list[MeasurementSummary]) -> None:
        """Populate the picker with the given measurements and show it.

        Args:
            measurements: List of available REW measurements.
        """
        self._showing_picker = True
        self._stereo_radio.setChecked(True)
        self._list_widget.clear()
        self._list_left.clear()
        self._list_right.clear()

        for list_widget in (self._list_widget, self._list_left, self._list_right):
            for measurement in measurements:
                item = QListWidgetItem(measurement.name)
                item.setData(Qt.ItemDataRole.UserRole, measurement)
                list_widget.addItem(item)

        self._pages.setCurrentIndex(0)
        self._update_continue_enabled()
        self._placeholder_widget.setVisible(False)
        self._content_widget.setVisible(True)

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the view layout: placeholder state + toggle/picker state."""
        container_layout, container = build_centered_content(self)

        self._title = make_page_title("Pull from REW", container, object_name="view_title")
        # Pin to its sizeHint so it never absorbs leftover vertical space —
        # otherwise QLabel's default vertical-center text alignment makes
        # the title appear to drift downward whenever the placeholder state
        # (which has less content than the picker) is showing.
        self._title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        container_layout.addWidget(self._title)

        self._placeholder_widget = self._build_placeholder()
        self._placeholder_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        container_layout.addWidget(self._placeholder_widget)

        self._content_widget = self._build_content()
        self._content_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        container_layout.addWidget(self._content_widget)

    def _build_placeholder(self) -> QWidget:
        """Build the connecting/info/error placeholder state."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(SPACING_MD)

        self._icon_label = make_empty_state_icon("", object_name="RewPullPlaceholderIcon")
        self._icon_label.setVisible(False)
        layout.addWidget(self._icon_label)

        self._message_label = QLabel("Connecting to REW...")
        self._message_label.setObjectName("rew_pull_message")
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setProperty("class", "secondary")
        self._message_label.setWordWrap(True)
        layout.addWidget(self._message_label)

        back_btn = QPushButton("Back")
        back_btn.setObjectName("btn_rew_pull_placeholder_back")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setProperty("class", "secondary")
        back_btn.clicked.connect(self.back_requested.emit)
        layout.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        return widget

    def _build_content(self) -> QWidget:
        """Build the Stereo/L-R toggle + stacked picker + action bar state."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_MD)

        header = QLabel("Choose measurement(s) to import filters from:")
        header.setWordWrap(True)
        layout.addWidget(header)

        # --- Stereo / L-R toggle ---
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(SPACING_LG)
        self._mode_group = QButtonGroup(widget)

        self._stereo_radio = QRadioButton("Stereo (one measurement)")
        self._stereo_radio.setChecked(True)
        self._lr_radio = QRadioButton("L/R (separate Left and Right measurements)")
        self._mode_group.addButton(self._stereo_radio)
        self._mode_group.addButton(self._lr_radio)

        toggle_row.addWidget(self._stereo_radio)
        toggle_row.addWidget(self._lr_radio)
        toggle_row.addStretch()
        layout.addLayout(toggle_row)

        # --- Stacked pages: Stereo (1 list) vs L/R (2 lists) ---
        self._pages = QStackedWidget()

        self._list_widget = self._build_list("rew_pull_measurement_list")
        self._list_widget.itemDoubleClicked.connect(self._on_continue_clicked)
        self._pages.addWidget(self._list_widget)

        lr_page = QWidget()
        lr_layout = QHBoxLayout(lr_page)
        lr_layout.setContentsMargins(0, 0, 0, 0)
        lr_layout.setSpacing(SPACING_MD)

        self._list_left = self._build_list("rew_pull_measurement_list_left")
        self._list_right = self._build_list("rew_pull_measurement_list_right")
        lr_layout.addLayout(self._labeled_column("Left Channel", self._list_left))
        lr_layout.addLayout(self._labeled_column("Right Channel", self._list_right))
        self._pages.addWidget(lr_page)

        layout.addWidget(self._pages, 1)

        self._stereo_radio.toggled.connect(self._on_mode_toggled)

        # --- Action bar ---
        actions_bar = QHBoxLayout()
        actions_bar.setSpacing(SPACING_SM)

        back_btn = QPushButton("Back")
        back_btn.setObjectName("btn_rew_pull_back")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setProperty("class", "secondary")
        back_btn.clicked.connect(self.back_requested.emit)
        actions_bar.addWidget(back_btn)

        actions_bar.addStretch()

        self._continue_btn = QPushButton("Continue")
        self._continue_btn.setObjectName("btn_rew_pull_continue")
        self._continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._continue_btn.setProperty("class", "primary")
        self._continue_btn.clicked.connect(self._on_continue_clicked)
        actions_bar.addWidget(self._continue_btn)

        layout.addLayout(actions_bar)

        return widget

    def _build_list(self, object_name: str) -> QListWidget:
        """Build an empty single-selection measurement list widget."""
        list_widget = QListWidget()
        list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        list_widget.setObjectName(object_name)
        list_widget.setProperty("class", "selectableList")
        list_widget.setMinimumHeight(_LIST_MIN_HEIGHT)
        list_widget.itemSelectionChanged.connect(self._update_continue_enabled)
        return list_widget

    def _labeled_column(self, label_text: str, list_widget: QListWidget) -> QVBoxLayout:
        """Wrap a list widget with a heading label above it."""
        column = QVBoxLayout()
        column.setSpacing(SPACING_SM)
        label = QLabel(label_text)
        label.setProperty("class", "fieldLabel")
        column.addWidget(label)
        column.addWidget(list_widget)
        return column

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    @property
    def is_lr_mode(self) -> bool:
        """Whether the L/R toggle is currently selected."""
        return self._lr_radio.isChecked()

    def selected_measurement(self) -> MeasurementSummary | None:
        """Return the selected Stereo measurement, or None if unselected."""
        items = self._list_widget.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.ItemDataRole.UserRole)  # type: ignore[no-any-return]

    def selected_measurements_lr(
        self,
    ) -> tuple[MeasurementSummary, MeasurementSummary] | None:
        """Return the (left, right) selected measurements, or None if incomplete."""
        left_items = self._list_left.selectedItems()
        right_items = self._list_right.selectedItems()
        if not left_items or not right_items:
            return None
        return (
            left_items[0].data(Qt.ItemDataRole.UserRole),
            right_items[0].data(Qt.ItemDataRole.UserRole),
        )

    def selection(
        self,
    ) -> MeasurementSummary | tuple[MeasurementSummary, MeasurementSummary] | None:
        """Return the current selection per the active Stereo/L-R toggle."""
        if self.is_lr_mode:
            return self.selected_measurements_lr()
        return self.selected_measurement()

    def _on_mode_toggled(self, _checked: bool) -> None:
        """Switch the visible page when the Stereo/L-R toggle changes."""
        self._pages.setCurrentIndex(1 if self.is_lr_mode else 0)
        self._update_continue_enabled()

    def _update_continue_enabled(self) -> None:
        """Enable Continue only when the current mode's selection is complete."""
        self._continue_btn.setEnabled(self.selection() is not None)

    def _on_continue_clicked(self) -> None:
        """Validate the selection and emit measurement_selected if complete."""
        result = self.selection()
        if result is None:
            message = (
                "Please select both a Left and Right measurement before continuing."
                if self.is_lr_mode
                else "Please select a measurement before continuing."
            )
            QMessageBox.warning(self, "No Selection", message)
            return
        self.measurement_selected.emit(result)
