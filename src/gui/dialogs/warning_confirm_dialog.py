"""Warning Confirm Dialog - styled Yes/No confirmation with a warning box.

Shared replacement for plain `QMessageBox.question()` confirmations that
warn about a state-changing or destructive action -- gives every such
confirmation the same `make_warning_box()` yellow-bordered treatment already
used by DevicePickerDialog, QuickSetupDialog, and PushConfirmation, instead
of an unstyled native message box.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout, QWidget

from src.gui.components.warning_box import make_warning_box
from src.gui.constants import SPACING_MD


class WarningConfirmDialog(QDialog):
    """Yes/No confirmation dialog with a styled warning box.

    Use the static ``confirm()`` method for standard usage.
    """

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        rich_text: bool = False,
    ) -> None:
        """Initialize the dialog.

        Args:
            parent: Parent widget (may be None).
            title: Warning box header text (rendered as "⚠ {title}").
            message: Warning body text. Plain text by default -- newlines are
                preserved, but HTML-special characters are not interpreted as
                markup, since most callers' messages may contain arbitrary
                values. Pass rich_text=True when the caller has built a
                deliberate HTML string (e.g. with <br>/<b>) from
                already-escaped dynamic values.
            rich_text: Whether `message` should be interpreted as HTML.
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.setModal(True)
        self._setup_ui(title, message, rich_text)

    def _setup_ui(self, title: str, message: str, rich_text: bool) -> None:
        """Build the dialog layout."""
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING_MD)

        layout.addWidget(
            make_warning_box(
                title,
                message,
                frame_object_name="warning_confirm_frame",
                body_object_name="warning_confirm_label",
                body_rich_text=rich_text,
            )
        )

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        button_box.setObjectName("button_box")
        no_button = button_box.button(QDialogButtonBox.StandardButton.No)
        if no_button is not None:
            no_button.setDefault(True)
            no_button.setFocus()
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    @staticmethod
    def confirm(
        parent: QWidget | None, title: str, message: str, *, rich_text: bool = False
    ) -> bool:
        """Show the dialog and return True if the user clicked Yes.

        Args:
            parent: Parent widget (may be None).
            title: Warning box header text.
            message: Warning body text.
            rich_text: Whether `message` should be interpreted as HTML.

        Returns:
            True if user clicked Yes, False if they clicked No/closed it.
        """
        dialog = WarningConfirmDialog(parent, title, message, rich_text=rich_text)
        return dialog.exec() == QDialog.DialogCode.Accepted
