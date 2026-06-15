"""Export Dialog — file path selection for stereo or L/R channel export.

Provides a QDialog that collects export file path(s) from the user.
For stereo mode: a single save path. For L/R mode: two path fields with
automatic _L.txt / _R.txt suffix handling.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ExportDialog(QDialog):
    """Dialog for selecting export file path(s).

    Stereo mode: single file path via QFileDialog.
    L/R mode: two path fields pre-filled with _L.txt / _R.txt suffixes.
    """

    def __init__(
        self,
        channel_mode: str = "stereo",
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the export dialog.

        Args:
            channel_mode: Either "stereo" (single file) or "lr" (two files).
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._channel_mode = channel_mode
        self._export_path: Path | None = None
        self._export_path_l: Path | None = None
        self._export_path_r: Path | None = None

        self.setWindowTitle("Export REW EQ File")
        self.setMinimumWidth(500)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the dialog layout based on channel mode."""
        layout = QVBoxLayout(self)

        if self._channel_mode == "lr":
            self._setup_lr_ui(layout)
        else:
            self._setup_stereo_ui(layout)

        # Button box
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._export_button = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        if self._export_button is not None:
            self._export_button.setText("Export")
            self._export_button.setEnabled(False)
        self._button_box.accepted.connect(self._on_accept)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

    def _setup_stereo_ui(self, layout: QVBoxLayout) -> None:
        """Set up UI for stereo mode (single path)."""
        label = QLabel("Export path:")
        layout.addWidget(label)

        row = QHBoxLayout()
        self._stereo_path_edit = QLineEdit()
        self._stereo_path_edit.setPlaceholderText("Select export file...")
        self._stereo_path_edit.setReadOnly(True)
        row.addWidget(self._stereo_path_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_stereo)
        row.addWidget(browse_btn)

        layout.addLayout(row)

    def _setup_lr_ui(self, layout: QVBoxLayout) -> None:
        """Set up UI for L/R mode (two paths)."""
        # Left channel
        label_l = QLabel("Left channel export path:")
        layout.addWidget(label_l)

        row_l = QHBoxLayout()
        self._left_path_edit = QLineEdit()
        self._left_path_edit.setPlaceholderText("Select left channel file...")
        self._left_path_edit.setReadOnly(True)
        row_l.addWidget(self._left_path_edit)

        browse_l_btn = QPushButton("Browse...")
        browse_l_btn.clicked.connect(self._browse_left)
        row_l.addWidget(browse_l_btn)

        layout.addLayout(row_l)

        # Right channel
        label_r = QLabel("Right channel export path:")
        layout.addWidget(label_r)

        row_r = QHBoxLayout()
        self._right_path_edit = QLineEdit()
        self._right_path_edit.setPlaceholderText("Select right channel file...")
        self._right_path_edit.setReadOnly(True)
        row_r.addWidget(self._right_path_edit)

        browse_r_btn = QPushButton("Browse...")
        browse_r_btn.clicked.connect(self._browse_right)
        row_r.addWidget(browse_r_btn)

        layout.addLayout(row_r)

    def _browse_stereo(self) -> None:
        """Open a save file dialog for stereo export."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export REW EQ File",
            "",
            "REW EQ Files (*.txt);;All Files (*)",
        )
        if file_path:
            path = Path(file_path)
            # Ensure .txt extension
            if path.suffix.lower() != ".txt":
                path = path.with_suffix(".txt")
            self._stereo_path_edit.setText(str(path))
            self._export_path = path
            self._update_export_button()

    def _browse_left(self) -> None:
        """Open a save file dialog for left channel."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Left Channel EQ File",
            "",
            "REW EQ Files (*.txt);;All Files (*)",
        )
        if file_path:
            path = Path(file_path)
            # Ensure _L.txt suffix
            if not path.stem.endswith("_L"):
                path = path.with_stem(path.stem + "_L")
            if path.suffix.lower() != ".txt":
                path = path.with_suffix(".txt")
            self._left_path_edit.setText(str(path))
            self._export_path_l = path

            # Auto-fill right channel if empty
            if hasattr(self, "_right_path_edit") and not self._right_path_edit.text():
                right_path = path.with_stem(path.stem.replace("_L", "_R"))
                self._right_path_edit.setText(str(right_path))
                self._export_path_r = right_path

            self._update_export_button()

    def _browse_right(self) -> None:
        """Open a save file dialog for right channel."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Right Channel EQ File",
            "",
            "REW EQ Files (*.txt);;All Files (*)",
        )
        if file_path:
            path = Path(file_path)
            # Ensure _R.txt suffix
            if not path.stem.endswith("_R"):
                path = path.with_stem(path.stem + "_R")
            if path.suffix.lower() != ".txt":
                path = path.with_suffix(".txt")
            self._right_path_edit.setText(str(path))
            self._export_path_r = path
            self._update_export_button()

    def _update_export_button(self) -> None:
        """Enable the Export button when all required paths are set."""
        if self._export_button is None:
            return

        if self._channel_mode == "lr":
            enabled = self._export_path_l is not None and self._export_path_r is not None
        else:
            enabled = self._export_path is not None

        self._export_button.setEnabled(enabled)

    def _on_accept(self) -> None:
        """Handle the Export button click."""
        self.accept()

    def get_export_paths(self) -> Path | tuple[Path, Path] | None:
        """Return the selected export path(s), or None if cancelled.

        Returns:
            Path for stereo mode, tuple[Path, Path] for L/R mode, None if cancelled.
        """
        if self.result() != QDialog.DialogCode.Accepted.value:
            return None

        if self._channel_mode == "lr":
            if self._export_path_l is not None and self._export_path_r is not None:
                return (self._export_path_l, self._export_path_r)
            return None
        else:
            return self._export_path

    @staticmethod
    def get_paths(
        channel_mode: str = "stereo",
        parent: QWidget | None = None,
    ) -> Path | tuple[Path, Path] | None:
        """Show dialog and return export path(s), or None if cancelled.

        This is the main entry point for using the export dialog.

        Args:
            channel_mode: Either "stereo" or "lr".
            parent: Optional parent widget.

        Returns:
            Path (stereo), tuple[Path, Path] (L/R), or None if cancelled.
        """
        dialog = ExportDialog(channel_mode=channel_mode, parent=parent)
        dialog.exec()
        return dialog.get_export_paths()
