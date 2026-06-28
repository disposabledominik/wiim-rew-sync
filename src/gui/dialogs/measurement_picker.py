"""Measurement Picker Dialog - REW measurement selection modal.

Presents REW measurements for the user to choose from, with a Stereo/L-R
toggle deciding whether one or two measurements are selected. Used in the
REW API pull workflow (Requirement 5.2, 5.7).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.adapters.rew_http_client import MeasurementSummary
from src.gui.constants import SPACING_LG, SPACING_MD, SPACING_SM

#: Tall enough to show ~8-10 measurement rows before scrolling kicks in,
#: since a real REW library can hold 60+ measurements.
_LIST_MIN_HEIGHT = 220


class MeasurementPickerDialog(QDialog):
    """Modal dialog for selecting REW measurement(s) for Stereo or L/R import.

    A Stereo/L-R toggle at the top switches between a single measurement
    list (Stereo) and two side-by-side Left/Right lists (L/R), both
    populated from the same ``measurements`` list. This replaces the
    previous flow of an up-front "Channel Mode" dialog followed by one or
    two sequential single-measurement dialogs.

    Each list keeps Qt's built-in incremental keyboard search (typing while
    a list has focus jumps to the first matching item), which covers "type
    to find an entry" for large REW libraries without extra plumbing.

    Use the static ``get_measurements()`` method for standard usage.
    """

    def __init__(
        self,
        parent: QWidget | None,
        measurements: list[MeasurementSummary],
    ) -> None:
        """Initialize the measurement picker dialog.

        Args:
            parent: Parent widget (may be None).
            measurements: List of available REW measurements to display.
        """
        super().__init__(parent)
        self.setWindowTitle("Select REW Measurement")
        self.setMinimumWidth(560)
        self.setMinimumHeight(420)
        self.setModal(True)

        self._setup_ui(measurements)

    def _setup_ui(self, measurements: list[MeasurementSummary]) -> None:
        """Build the dialog layout: toggle + stacked Stereo/L-R pages."""
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING_MD)

        header = QLabel("Choose measurement(s) to import filters from:")
        header.setWordWrap(True)
        layout.addWidget(header)

        # --- Stereo / L-R toggle ---
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(SPACING_LG)
        self._mode_group = QButtonGroup(self)

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

        self._list_widget = self._build_list(measurements, "measurement_list")
        self._list_widget.itemDoubleClicked.connect(self.accept)
        self._pages.addWidget(self._list_widget)

        lr_page = QWidget()
        lr_layout = QHBoxLayout(lr_page)
        lr_layout.setContentsMargins(0, 0, 0, 0)
        lr_layout.setSpacing(SPACING_MD)

        self._list_left = self._build_list(measurements, "measurement_list_left")
        self._list_right = self._build_list(measurements, "measurement_list_right")
        lr_layout.addLayout(self._labeled_column("Left Channel", self._list_left))
        lr_layout.addLayout(self._labeled_column("Right Channel", self._list_right))
        self._pages.addWidget(lr_page)

        layout.addWidget(self._pages, 1)

        self._stereo_radio.toggled.connect(self._on_mode_toggled)

        # Button box (Ok / Cancel)
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._button_box.setObjectName("button_box")
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

        self._update_ok_enabled()

    def _build_list(self, measurements: list[MeasurementSummary], object_name: str) -> QListWidget:
        """Build a single-selection measurement list widget."""
        list_widget = QListWidget()
        list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        list_widget.setObjectName(object_name)
        list_widget.setProperty("class", "selectableList")
        list_widget.setMinimumHeight(_LIST_MIN_HEIGHT)

        for measurement in measurements:
            item = QListWidgetItem(measurement.name)
            item.setData(Qt.ItemDataRole.UserRole, measurement)
            list_widget.addItem(item)

        list_widget.itemSelectionChanged.connect(self._update_ok_enabled)
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

    def _on_mode_toggled(self, _checked: bool) -> None:
        """Switch the visible page when the Stereo/L-R toggle changes."""
        self._pages.setCurrentIndex(1 if self.is_lr_mode else 0)
        self._update_ok_enabled()

    def _update_ok_enabled(self) -> None:
        """Enable OK only when the current mode's required selection(s) are made."""
        ok_btn = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        if not ok_btn:
            return
        ok_btn.setEnabled(self.selection() is not None)

    # ------------------------------------------------------------------
    # Public API
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

    def accept(self) -> None:
        """Validate that the current mode's required selection(s) are made."""
        if self.selection() is None:
            message = (
                "Please select both a Left and Right measurement before continuing."
                if self.is_lr_mode
                else "Please select a measurement before continuing."
            )
            QMessageBox.warning(self, "No Selection", message)
            return
        super().accept()

    @staticmethod
    def get_measurements(
        parent: QWidget | None,
        measurements: list[MeasurementSummary],
    ) -> MeasurementSummary | tuple[MeasurementSummary, MeasurementSummary] | None:
        """Show the measurement picker and return the selection, or None if cancelled.

        Args:
            parent: Parent widget (may be None).
            measurements: List of available REW measurements.

        Returns:
            A single ``MeasurementSummary`` (Stereo), a
            ``(left, right)`` tuple of ``MeasurementSummary`` (L/R), or
            ``None`` if the dialog was cancelled.
        """
        dialog = MeasurementPickerDialog(parent, measurements)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selection()
        return None
