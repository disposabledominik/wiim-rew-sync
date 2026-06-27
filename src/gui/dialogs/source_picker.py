"""Source Picker Dialog - modal dialog for selecting target audio sources.

Presents a checkable list of available audio sources (excluding the current
source) and returns the user's selection. Used by the copy-to-sources
secondary workflow (Requirements 9.1, 9.2).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from src.gui.constants import SPACING_MD


class SourcePickerDialog(QDialog):
    """Modal dialog for selecting one or more target audio sources.

    Displays all available sources except the currently active one,
    each with a checkbox. The user must select at least one source
    before accepting.

    Use the static ``get_sources()`` method for standard usage.
    """

    def __init__(
        self,
        parent: QWidget | None,
        available_sources: list[str],
        exclude: str,
    ) -> None:
        """Initialize the source picker dialog.

        Args:
            parent: Parent widget (may be None).
            available_sources: All source names available on the device.
            exclude: Source name to exclude (the currently active source).
        """
        super().__init__(parent)
        self.setWindowTitle("Select Target Sources")
        self.setMinimumWidth(320)
        self.setModal(True)

        self._setup_ui(available_sources, exclude)

    def _setup_ui(self, available_sources: list[str], exclude: str) -> None:
        """Build the dialog layout with a checkable source list."""
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING_MD)

        # Header label
        header = QLabel("Select sources to copy filters to:")
        header.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(header)

        # Checkable source list
        self._list_widget = QListWidget()
        self._list_widget.setObjectName("source_list")
        self._list_widget.setProperty("class", "selectableList")

        for source in available_sources:
            if source == exclude:
                continue
            item = QListWidgetItem(source)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self._list_widget.addItem(item)

        layout.addWidget(self._list_widget)

        # Button box (Ok / Cancel)
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._button_box.setObjectName("button_box")
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

    def selected_sources(self) -> list[str]:
        """Return the list of checked source names.

        Returns:
            List of source name strings that have been checked by the user.
        """
        sources: list[str] = []
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                sources.append(item.text())
        return sources

    def accept(self) -> None:
        """Validate at least one source is selected before accepting.

        If no sources are checked, shows a warning message box and
        prevents the dialog from closing.
        """
        if not self.selected_sources():
            QMessageBox.warning(
                self,
                "No Sources Selected",
                "Please select at least one target source.",
            )
            return
        super().accept()

    @staticmethod
    def get_sources(
        parent: QWidget | None,
        available_sources: list[str],
        exclude: str,
    ) -> list[str] | None:
        """Show the source picker dialog and return selected sources.

        Convenience static method that creates the dialog, executes it
        modally, and returns the result.

        Args:
            parent: Parent widget (may be None).
            available_sources: All source names available on the device.
            exclude: Source name to exclude (the currently active source).

        Returns:
            List of selected source names if the user accepted,
            or None if the user cancelled.
        """
        dialog = SourcePickerDialog(parent, available_sources, exclude)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selected_sources()
        return None
