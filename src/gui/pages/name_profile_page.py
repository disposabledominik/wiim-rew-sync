"""RoomFit profile naming page.

Displays a text input for the user to name a RoomFit profile before push.
Shows existing profiles for reference and warns when overwriting the active profile.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.constants import (
    MAX_CONTENT_WIDTH,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
)


class NameProfilePage(QWidget):
    """RoomFit profile naming before push.

    Allows the user to enter a profile name (max 32 characters). Displays
    existing profiles for reference and warns when the name matches the
    currently-active profile (overwriting triggers deactivation).

    Signals:
        name_confirmed: Emitted with the profile name when the user clicks Save.
    """

    name_confirmed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._active_profile: str = ""

        # Outer layout to constrain width
        outer_layout = QVBoxLayout(self)
        outer_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Content container with max width
        container = QWidget()
        container.setMaximumWidth(MAX_CONTENT_WIDTH)
        container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        outer_layout.addWidget(container)

        # Container layout
        layout = QVBoxLayout(container)
        layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)
        layout.setSpacing(SPACING_MD)

        # Title
        title = QLabel("Name Your Profile")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setProperty("class", "title")
        layout.addWidget(title)

        # Helper text
        helper = QLabel("Choose a name for this RoomFit profile")
        helper.setAlignment(Qt.AlignmentFlag.AlignCenter)
        helper.setProperty("class", "caption")
        layout.addWidget(helper)

        # Text input
        self._name_input = QLineEdit()
        self._name_input.setMaxLength(32)
        self._name_input.setPlaceholderText("Profile name (max 32 characters)")
        self._name_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._name_input)

        # Warning label (hidden by default)
        self._warning_label = QLabel(
            "This will overwrite the active profile and may deactivate RoomFit. "
            "You can save with a new name instead."
        )
        self._warning_label.setWordWrap(True)
        self._warning_label.setProperty("class", "warning")
        self._warning_label.setVisible(False)
        layout.addWidget(self._warning_label)

        # Existing profiles section
        profiles_heading = QLabel("Existing Profiles")
        profiles_heading.setProperty("class", "subheading")
        layout.addSpacing(SPACING_SM)
        layout.addWidget(profiles_heading)

        self._profiles_list = QListWidget()
        self._profiles_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._profiles_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._profiles_list.setMaximumHeight(150)
        layout.addWidget(self._profiles_list)

        # Save button
        self._save_button = QPushButton("Save")
        self._save_button.setEnabled(False)
        self._save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_button.setProperty("class", "primary")
        self._save_button.clicked.connect(self._on_save_clicked)
        layout.addWidget(self._save_button, alignment=Qt.AlignmentFlag.AlignCenter)

        # Stretch at bottom
        layout.addStretch()

    def set_existing_profiles(
        self, profiles: list[str], active_profile: str = ""
    ) -> None:
        """Populate the existing profiles list and mark the active profile.

        Args:
            profiles: List of existing RoomFit profile names on the device.
            active_profile: Name of the currently-active profile (empty if none).
        """
        self._active_profile = active_profile
        self._profiles_list.clear()
        for name in profiles:
            display = f"{name} (active)" if name == active_profile else name
            self._profiles_list.addItem(display)

        # Re-evaluate warning in case input already has text
        self._on_text_changed(self._name_input.text())

    def _on_text_changed(self, text: str) -> None:
        """Handle text input changes: enable/disable Save and show/hide warning."""
        stripped = text.strip()
        self._save_button.setEnabled(bool(stripped))

        # Show warning when name matches active profile
        show_warning = (
            bool(stripped)
            and bool(self._active_profile)
            and stripped == self._active_profile
        )
        self._warning_label.setVisible(show_warning)

    def _on_save_clicked(self) -> None:
        """Emit name_confirmed with the trimmed profile name."""
        name = self._name_input.text().strip()
        if name:
            self.name_confirmed.emit(name)
