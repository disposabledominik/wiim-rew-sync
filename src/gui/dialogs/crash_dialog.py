"""Crash Dialog - unhandled exception dialog with log path and support bundle.

Displays a user-friendly error message when the app encounters an unhandled
exception. Provides the log file path for easy access, a "View Logs" button,
and a "Generate Support Bundle" button so the user can package diagnostics
in one click (Req 24.6, 24.7, 24.13).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.gui.constants import (
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
)


class CrashDialog(QDialog):
    """Unhandled exception dialog with log path and support bundle action.

    Displays "The app encountered an unexpected error" along with the log
    file path and provides actions for viewing logs and generating a support
    bundle. The dialog is modal and non-dismissable except via the buttons.

    Use the static ``show_crash()`` method for standard usage.
    """

    # Return value constants
    CLOSE = "close"
    VIEW_LOGS = "view_logs"
    SUPPORT_BUNDLE = "support_bundle"

    def __init__(
        self,
        parent: QWidget | None,
        error_message: str,
        log_path: str,
    ) -> None:
        """Initialize the crash dialog.

        Args:
            parent: Parent widget (may be None).
            error_message: The error/exception message to display.
            log_path: Path to the log file for the user to reference.
        """
        super().__init__(parent)
        self.setWindowTitle("Unexpected Error")
        self.setMinimumWidth(480)
        self.setModal(True)
        # Non-dismissable except via buttons - remove close button from title bar
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint
        )

        self._result_action: str = self.CLOSE
        self._setup_ui(error_message, log_path)

    @property
    def result_action(self) -> str:
        """The action the user selected (close, view_logs, or support_bundle)."""
        return self._result_action

    def _setup_ui(self, error_message: str, log_path: str) -> None:
        """Build the dialog layout."""
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING_MD)

        # --- Error icon + header ---
        header_layout = QHBoxLayout()
        header_layout.setSpacing(SPACING_SM)

        error_icon = QLabel("\u26a0")  # Warning sign (triangle with !)
        error_icon.setObjectName("crash_error_icon")
        error_icon.setProperty("class", "warning")
        error_icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        header_layout.addWidget(error_icon)

        header_label = QLabel("Unexpected Error")
        header_label.setObjectName("crash_header_label")
        header_label.setProperty("class", "title")
        header_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(header_label, 1)

        layout.addLayout(header_layout)

        # --- Description ---
        description = QLabel("The app encountered an unexpected error.")
        description.setObjectName("crash_description_label")
        description.setWordWrap(True)
        layout.addWidget(description)

        # --- Error message (monospace, code-style) ---
        error_label = QLabel(error_message)
        error_label.setObjectName("crash_error_message")
        error_label.setProperty("class", "card")
        error_label.setWordWrap(True)
        error_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(error_label)

        # --- Log file path (selectable for easy copy) ---
        log_path_header = QLabel("Log file:")
        log_path_header.setProperty("class", "subheading")
        layout.addWidget(log_path_header)

        log_path_label = QLabel(log_path)
        log_path_label.setObjectName("crash_log_path_label")
        log_path_label.setProperty("class", "caption")
        log_path_label.setWordWrap(True)
        log_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        layout.addWidget(log_path_label)

        layout.addSpacing(SPACING_LG - SPACING_MD)

        # --- Action buttons ---
        button_layout = QHBoxLayout()
        button_layout.setSpacing(SPACING_SM)

        # "View Logs" button (secondary style)
        view_logs_btn = QPushButton("View Logs")
        view_logs_btn.setObjectName("crash_view_logs_btn")
        view_logs_btn.setProperty("buttonStyle", "secondary")
        view_logs_btn.clicked.connect(self._on_view_logs)
        button_layout.addWidget(view_logs_btn)

        # "Generate Support Bundle" button (secondary style)
        support_btn = QPushButton("Generate Support Bundle")
        support_btn.setObjectName("crash_support_bundle_btn")
        support_btn.setProperty("buttonStyle", "secondary")
        support_btn.clicked.connect(self._on_support_bundle)
        button_layout.addWidget(support_btn)

        button_layout.addStretch(1)

        # "Close" button (primary style, closes the dialog)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("crash_close_btn")
        close_btn.setProperty("buttonStyle", "primary")
        close_btn.setDefault(True)
        close_btn.setFocus()
        close_btn.clicked.connect(self._on_close)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _on_view_logs(self) -> None:
        """Handle View Logs button click."""
        self._result_action = self.VIEW_LOGS
        self.accept()

    def _on_support_bundle(self) -> None:
        """Handle Generate Support Bundle button click."""
        self._result_action = self.SUPPORT_BUNDLE
        self.accept()

    def _on_close(self) -> None:
        """Handle Close button click."""
        self._result_action = self.CLOSE
        self.accept()

    @staticmethod
    def show_crash(
        parent: QWidget | None,
        error_message: str,
        log_path: str,
    ) -> str:
        """Show the crash dialog and return the user's chosen action.

        This is the primary entry point for displaying the crash dialog
        (Req 24.7). The dialog is modal and blocks until the user clicks
        one of the action buttons.

        Args:
            parent: Parent widget (may be None if GUI is in unstable state).
            error_message: The exception message or description.
            log_path: Path to the primary log file (app.log).

        Returns:
            One of "close", "view_logs", or "support_bundle" indicating
            which action the user selected.
        """
        dialog = CrashDialog(parent, error_message, log_path)
        dialog.exec()
        return dialog.result_action
