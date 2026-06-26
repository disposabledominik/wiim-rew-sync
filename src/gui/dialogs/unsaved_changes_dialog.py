"""Unsaved Changes Dialog - confirmation when navigating away with pending changes.

Triggered when the user has modified filter settings and attempts to close the
application or navigate away from the current wizard step. Offers three actions:
Save (persist changes first), Discard (leave without saving), or Cancel (stay).

Requirement 12.5: WHEN the user has unsaved filter changes and attempts to
navigate away or close the App, THE App SHALL prompt with an "Unsaved changes"
confirmation dialog.
"""

from __future__ import annotations

from typing import Literal

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


class UnsavedChangesDialog(QDialog):
    """Modal dialog prompting the user to save, discard, or cancel.

    Shown when unsaved filter changes exist and the user attempts to
    navigate away or close the application.

    Use the static ``confirm_discard()`` method for standard usage.
    """

    def __init__(self, parent: QWidget | None) -> None:
        """Initialize the unsaved changes dialog.

        Args:
            parent: Parent widget (may be None).
        """
        super().__init__(parent)
        self.setWindowTitle("Unsaved Changes")
        self.setMinimumWidth(400)
        self.setModal(True)

        self._result: Literal["save", "discard", "cancel"] = "cancel"
        self._setup_ui()

    @property
    def choice(self) -> Literal["save", "discard", "cancel"]:
        """The user's choice after the dialog closes."""
        return self._result

    def _setup_ui(self) -> None:
        """Build the dialog layout."""
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING_MD)
        layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)

        # --- Header with warning icon + title ---
        header_layout = QHBoxLayout()
        header_layout.setSpacing(SPACING_SM)

        icon_label = QLabel("\u26a0")  # Warning sign unicode
        icon_label.setObjectName("warning_icon")
        icon_label.setProperty("class", "warning")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(icon_label)

        title_label = QLabel("Unsaved Changes")
        title_label.setObjectName("dialog_title")
        title_label.setProperty("class", "title")
        title_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(title_label, 1)

        layout.addLayout(header_layout)

        # --- Message ---
        message_label = QLabel(
            "You have unsaved filter changes. What would you like to do?"
        )
        message_label.setObjectName("dialog_message")
        message_label.setWordWrap(True)
        message_label.setProperty("class", "caption")
        layout.addWidget(message_label)

        # --- Spacer ---
        layout.addSpacing(SPACING_SM)

        # --- Buttons ---
        button_layout = QHBoxLayout()
        button_layout.setSpacing(SPACING_SM)

        # Cancel button (ghost/text style) - leftmost
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("cancel_button")
        self._cancel_btn.setProperty("class", "ghost")
        self._cancel_btn.clicked.connect(self._on_cancel)
        button_layout.addWidget(self._cancel_btn)

        button_layout.addStretch(1)

        # Discard button (destructive/warning)
        self._discard_btn = QPushButton("Discard")
        self._discard_btn.setObjectName("discard_button")
        self._discard_btn.setProperty("class", "danger")
        self._discard_btn.clicked.connect(self._on_discard)
        button_layout.addWidget(self._discard_btn)

        # Save button (primary/accent)
        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("save_button")
        self._save_btn.setProperty("class", "primary")
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self._on_save)
        button_layout.addWidget(self._save_btn)

        layout.addLayout(button_layout)

    def _on_save(self) -> None:
        """Handle Save button click."""
        self._result = "save"
        self.accept()

    def _on_discard(self) -> None:
        """Handle Discard button click."""
        self._result = "discard"
        self.accept()

    def _on_cancel(self) -> None:
        """Handle Cancel button click."""
        self._result = "cancel"
        self.reject()

    @staticmethod
    def confirm_discard(parent: QWidget | None) -> Literal["save", "discard", "cancel"]:
        """Show the unsaved changes dialog and return the user's choice.

        This is the primary entry point for standard usage.

        Args:
            parent: Parent widget (may be None).

        Returns:
            "save" if the user wants to save first,
            "discard" if the user wants to leave without saving,
            "cancel" if the user wants to stay on the current page.
        """
        dialog = UnsavedChangesDialog(parent)
        dialog.exec()
        return dialog.choice
