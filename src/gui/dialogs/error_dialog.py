"""Error Dialog - severity-specific error display for all failure modes.

Provides a QDialog with severity-specific icons, optional copyable backup
path (for critical rollback failures), and step-by-step recovery instructions.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStyle,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

Severity = Literal["INFO", "WARNING", "ERROR", "CRITICAL"]

_RECOVERY_STEPS = (
    "<b>Manual recovery steps:</b><ol>"
    "<li>Open the JSON backup file listed above in a text editor.</li>"
    "<li>Use the WiiM app or the diagnostics panel to manually "
    "re-enter the filter values from the backup.</li>"
    "<li>Alternatively, use the CLI: <code>--set-filters</code> with "
    "the backup file path.</li>"
    "</ol>"
)


class ErrorDialog(QDialog):
    """Modal error dialog with severity-specific icon and optional details.

    Severity levels:
        INFO - Informational notice (blue circle icon).
        WARNING - Non-fatal issue (yellow triangle icon).
        ERROR - Operation failed (red circle icon).
        CRITICAL - Rollback failure requiring manual recovery.

    For CRITICAL severity, the dialog includes:
        - A copyable QLineEdit with the backup file path.
        - Step-by-step manual recovery instructions.
    """

    def __init__(
        self,
        severity: Severity,
        title: str,
        message: str,
        *,
        backup_path: str | None = None,
        recovery_steps: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the error dialog.

        Args:
            severity: One of INFO, WARNING, ERROR, CRITICAL.
            title: Dialog window title / header text.
            message: Human-readable error description.
            backup_path: For CRITICAL errors - path to backup file (copyable).
            recovery_steps: HTML recovery instructions. Uses default if None.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._severity = severity
        self._backup_path = backup_path

        self.setWindowTitle(title)
        self.setMinimumWidth(450)
        self.setModal(True)

        self._setup_ui(title, message, backup_path, recovery_steps)

    @property
    def severity(self) -> Severity:
        """Return the dialog severity level."""
        return self._severity

    @property
    def backup_path(self) -> str | None:
        """Return the backup path if provided."""
        return self._backup_path

    def _setup_ui(
        self,
        title: str,
        message: str,
        backup_path: str | None,
        recovery_steps: str | None,
    ) -> None:
        """Build the dialog layout."""
        layout = QVBoxLayout(self)

        # --- Header row: icon + title ---
        header_layout = QHBoxLayout()

        icon_label = QLabel()
        style = self.style()
        if style is not None:
            pixmap = style.standardIcon(self._get_icon_enum()).pixmap(48, 48)
            icon_label.setPixmap(pixmap)
        icon_label.setFixedSize(52, 52)
        header_layout.addWidget(icon_label)

        header_text = QLabel(f"<h3>{title}</h3>")
        header_text.setWordWrap(True)
        header_layout.addWidget(header_text, 1)

        layout.addLayout(header_layout)

        # --- Message body ---
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(message_label)

        # --- CRITICAL: backup path (copyable) ---
        if self._severity == "CRITICAL" and backup_path:
            layout.addSpacing(8)

            path_header = QLabel("<b>Backup file path:</b>")
            layout.addWidget(path_header)

            self._path_edit = QLineEdit(backup_path)
            self._path_edit.setReadOnly(True)
            self._path_edit.setObjectName("backup_path_edit")
            # Select all on focus for easy copy
            self._path_edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            self._path_edit.mousePressEvent = lambda _: self._path_edit.selectAll()  # type: ignore[method-assign]
            layout.addWidget(self._path_edit)

        # --- CRITICAL: recovery instructions ---
        if self._severity == "CRITICAL":
            layout.addSpacing(8)

            steps_html = recovery_steps if recovery_steps else _RECOVERY_STEPS
            self._recovery_browser = QTextBrowser()
            self._recovery_browser.setObjectName("recovery_browser")
            self._recovery_browser.setHtml(steps_html)
            self._recovery_browser.setOpenExternalLinks(False)
            self._recovery_browser.setMaximumHeight(160)
            layout.addWidget(self._recovery_browser)

        # --- Button box ---
        layout.addSpacing(12)
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

        # Focus OK button for accessibility
        ok_btn = button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setFocus()

    def _get_icon_enum(self) -> QStyle.StandardPixmap:
        """Map severity to a QStyle standard pixmap."""
        mapping: dict[Severity, QStyle.StandardPixmap] = {
            "INFO": QStyle.StandardPixmap.SP_MessageBoxInformation,
            "WARNING": QStyle.StandardPixmap.SP_MessageBoxWarning,
            "ERROR": QStyle.StandardPixmap.SP_MessageBoxCritical,
            "CRITICAL": QStyle.StandardPixmap.SP_MessageBoxCritical,
        }
        return mapping.get(self._severity, QStyle.StandardPixmap.SP_MessageBoxCritical)

    @staticmethod
    def show_error(
        severity: Severity,
        title: str,
        message: str,
        *,
        backup_path: str | None = None,
        recovery_steps: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Create and display the error dialog modally.

        Convenience static method for fire-and-forget error display.

        Args:
            severity: One of INFO, WARNING, ERROR, CRITICAL.
            title: Dialog window title.
            message: Human-readable error description.
            backup_path: For CRITICAL - path to backup file.
            recovery_steps: HTML recovery instructions.
            parent: Optional parent widget.
        """
        dialog = ErrorDialog(
            severity,
            title,
            message,
            backup_path=backup_path,
            recovery_steps=recovery_steps,
            parent=parent,
        )
        dialog.exec()
