"""Measurement Picker Dialog - single-select REW measurement modal.

Presents a list of REW measurements for the user to choose from.
Used in the REW API pull workflow (Requirement 5.2, 5.7).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from src.adapters.rew_http_client import MeasurementSummary


class MeasurementPickerDialog(QDialog):
    """Modal dialog for selecting a single REW measurement.

    Displays measurement names in a single-selection list and returns
    the selected MeasurementSummary on accept, or None on cancel.

    Use the static ``get_measurement()`` method for standard usage.
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
        self.setMinimumWidth(380)
        self.setMinimumHeight(300)
        self.setModal(True)

        self._setup_ui(measurements)

    def _setup_ui(self, measurements: list[MeasurementSummary]) -> None:
        """Build the dialog layout."""
        layout = QVBoxLayout(self)

        # Header label
        header = QLabel("Choose a measurement to import filters from:")
        header.setWordWrap(True)
        layout.addWidget(header)

        # Measurement list (single selection)
        self._list_widget = QListWidget()
        self._list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list_widget.setObjectName("measurement_list")

        for measurement in measurements:
            item = QListWidgetItem(measurement.name)
            item.setData(Qt.ItemDataRole.UserRole, measurement)
            self._list_widget.addItem(item)

        # Double-click to accept
        self._list_widget.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self._list_widget, 1)

        # Button box (Ok / Cancel)
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.setObjectName("button_box")
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def selected_measurement(self) -> MeasurementSummary | None:
        """Return the currently selected measurement, or None if nothing selected."""
        items = self._list_widget.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.ItemDataRole.UserRole)  # type: ignore[return-value]

    def accept(self) -> None:
        """Validate that a measurement is selected before accepting."""
        if self.selected_measurement() is None:
            QMessageBox.warning(
                self,
                "No Selection",
                "Please select a measurement before continuing.",
            )
            return
        super().accept()

    @staticmethod
    def get_measurement(
        parent: QWidget | None,
        measurements: list[MeasurementSummary],
    ) -> MeasurementSummary | None:
        """Show the measurement picker and return the selected measurement.

        Convenience static method that creates the dialog, executes it
        modally, and returns the result.

        Args:
            parent: Parent widget (may be None).
            measurements: List of available REW measurements.

        Returns:
            The selected MeasurementSummary if accepted, or None if cancelled.
        """
        dialog = MeasurementPickerDialog(parent, measurements)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selected_measurement()
        return None
