"""Import Dialog — file selection, parsing, preview table, and validation warnings.

Provides a QDialog that lets the user select a REW EQ text file, parses it using
TranslationEngine, displays a preview table of parsed filters, and returns the
accepted filter list to the caller.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.models.canonical import CanonicalFilter
from src.models.errors import ParseError, ValidationError
from src.translator._warnings import ValidationWarning
from src.translator.rew_parser import REWParser

# Orange colour for warning-highlighted rows
_WARNING_ORANGE = QColor(255, 165, 0, 80)


class ImportDialog(QDialog):
    """Dialog for importing a REW EQ text file with preview and validation.

    Opens a file dialog, parses the selected file, shows a preview table with
    any validation warnings highlighted, and returns the parsed filters on accept.
    """

    def __init__(self, max_filters: int = 10, parent: QWidget | None = None) -> None:
        """Initialize the import dialog.

        Args:
            max_filters: Maximum number of filters the device supports.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._max_filters = max_filters
        self._filters: list[CanonicalFilter] = []
        self._warnings: list[ValidationWarning] = []

        self.setWindowTitle("Import REW EQ File")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the dialog layout."""
        layout = QVBoxLayout(self)

        # File path label
        self._file_label = QLabel("No file selected")
        layout.addWidget(self._file_label)

        # Error label (hidden by default)
        self._error_label = QLabel()
        self._error_label.setProperty("class", "error")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        layout.addWidget(self._error_label)

        # Preview table
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["#", "Type", "Freq (Hz)", "Gain (dB)", "Q"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        header = self._table.horizontalHeader()
        if header is not None:
            header.setStretchLastSection(True)
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table)

        # Warning banner (hidden by default)
        self._warning_banner = QWidget()
        self._warning_banner.setProperty("class", "card")
        banner_layout = QVBoxLayout(self._warning_banner)
        banner_layout.setContentsMargins(8, 8, 8, 8)

        self._warning_text = QLabel()
        self._warning_text.setWordWrap(True)
        banner_layout.addWidget(self._warning_text)

        checkbox_row = QHBoxLayout()
        self._ack_checkbox = QCheckBox("I understand and want to proceed")
        self._ack_checkbox.stateChanged.connect(self._on_ack_changed)
        checkbox_row.addWidget(self._ack_checkbox)
        banner_layout.addLayout(checkbox_row)

        self._warning_banner.hide()
        layout.addWidget(self._warning_banner)

        # Button box
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._accept_button = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        if self._accept_button is not None:
            self._accept_button.setText("Accept")
            self._accept_button.setEnabled(False)
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

    def _on_ack_changed(self, state: int) -> None:
        """Enable/disable Accept button based on acknowledgement checkbox."""
        if self._accept_button is not None:
            self._accept_button.setEnabled(state == Qt.CheckState.Checked.value)

    def _populate_table(self) -> None:
        """Fill the preview table with parsed filters."""
        self._table.setRowCount(len(self._filters))

        # Build a set of warning indices for highlighting
        warning_fields: set[str] = set()
        for w in self._warnings:
            warning_fields.add(w.field)

        for row, filt in enumerate(self._filters):
            items = [
                QTableWidgetItem(str(row + 1)),
                QTableWidgetItem(filt.type),
                QTableWidgetItem(f"{filt.frequency_hz:.1f}"),
                QTableWidgetItem(f"{filt.gain_db:.2f}"),
                QTableWidgetItem(f"{filt.q:.4f}"),
            ]

            # Highlight rows that exceed max_filters in orange
            is_over_limit = row >= self._max_filters

            for col, item in enumerate(items):
                if is_over_limit:
                    item.setBackground(_WARNING_ORANGE)
                self._table.setItem(row, col, item)

    def _show_over_limit_warning(self) -> None:
        """Show the inline warning banner when filters exceed max_filters."""
        count = len(self._filters)
        self._warning_text.setText(
            f"This file contains {count} filters, but the device supports "
            f"a maximum of {self._max_filters}. Only the first "
            f"{self._max_filters} filters will be applied."
        )
        self._warning_banner.show()
        self._ack_checkbox.setChecked(False)
        if self._accept_button is not None:
            self._accept_button.setEnabled(False)

    def _load_and_parse(self, path: Path) -> bool:
        """Load and parse the selected file.

        Returns True if parsing succeeded, False otherwise.
        """
        self._file_label.setText(f"File: {path.name}")

        try:
            parser = REWParser()
            filters, warnings = parser.parse_file_with_warnings(path)
        except (ParseError, ValidationError, OSError) as exc:
            self._error_label.setText(f"Error: {exc}")
            self._error_label.show()
            self._table.setRowCount(0)
            if self._accept_button is not None:
                self._accept_button.setEnabled(False)
            return False

        self._filters = filters
        self._warnings = warnings
        self._error_label.hide()

        # Populate preview table
        self._populate_table()

        # Check over-limit condition
        if len(self._filters) > self._max_filters:
            self._show_over_limit_warning()
        else:
            self._warning_banner.hide()
            if self._accept_button is not None:
                self._accept_button.setEnabled(len(self._filters) > 0)

        return True

    def exec(self) -> int:
        """Override exec to show file dialog first.

        If the user cancels the file dialog, the import dialog is also cancelled.
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select REW EQ File",
            "",
            "REW EQ Files (*.txt);;All Files (*)",
        )

        if not file_path:
            return QDialog.DialogCode.Rejected.value

        path = Path(file_path)
        self._load_and_parse(path)

        return super().exec()

    def get_accepted_filters(self) -> list[CanonicalFilter] | None:
        """Return the parsed filters if accepted, None if cancelled."""
        if self.result() == QDialog.DialogCode.Accepted.value:
            return self._filters
        return None

    @staticmethod
    def get_filters(
        max_filters: int = 10, parent: QWidget | None = None
    ) -> list[CanonicalFilter] | None:
        """Show the dialog and return parsed filters, or None if cancelled.

        This is the main entry point for using the import dialog.

        Args:
            max_filters: Maximum number of filters the device supports.
            parent: Optional parent widget.

        Returns:
            List of CanonicalFilter on accept, None on cancel.
        """
        dialog = ImportDialog(max_filters=max_filters, parent=parent)
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted.value:
            return dialog._filters
        return None
