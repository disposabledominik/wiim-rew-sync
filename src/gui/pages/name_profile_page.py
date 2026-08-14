"""RoomFit profile naming page.

Displays a text input for the user to name a RoomFit profile before push.
Shows existing profiles for reference (clickable to reuse a name) and warns
when overwriting the active profile or a different existing one.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QWidget,
)

from src.gui.components.action_button import make_action_button
from src.gui.components.list_item_style import (
    apply_active_item_style,
    size_list_item,
    style_selectable_list,
)
from src.gui.components.page_layout import build_centered_content, make_page_title
from src.gui.constants import (
    SPACING_MD,
    SPACING_SM,
)
from src.utils.device_name import (
    DEVICE_NAME_RULE_TEXT,
    has_invalid_device_name_chars,
    sanitize_device_name,
)

_EXISTING_WARNING = (
    "A profile named '{name}' already exists. Saving will overwrite its "
    "stored filters."
)
_ACTIVE_WARNING = (
    "This is your active profile. Saving will overwrite its stored filters "
    "with the ones you've selected -- since it's already active, this also "
    "updates what's currently playing."
)
_CHAR_WARNING = (
    f"Only {DEVICE_NAME_RULE_TEXT} are allowed in a device profile name. "
    "Other characters will be removed when you save."
)


class NameProfilePage(QWidget):
    """RoomFit profile naming before push.

    Allows the user to enter a profile name (max 32 characters), or click an
    existing profile below to reuse its name. Every save now unconditionally
    makes the saved profile active and turns RoomFit on if it was off (see
    the always-visible caption below the Save button) -- so the inline
    warning here is purely about data loss: it fires when the name matches
    an existing profile (active or not), since saving overwrites that
    profile's stored filters.

    Signals:
        name_confirmed: Emitted with the profile name when the user clicks Save.
    """

    name_confirmed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._active_profile: str = ""
        self._existing_profiles: list[str] = []

        layout, container = build_centered_content(self)
        layout.setSpacing(SPACING_MD)

        # Title
        title = make_page_title(
            "Name Your Profile", container, object_name="NameProfilePageTitle"
        )
        layout.addWidget(title)

        # Helper text
        helper = QLabel("Choose a name for this RoomFit profile")
        helper.setProperty("class", "secondary")
        layout.addWidget(helper)

        # Text input
        self._name_input = QLineEdit()
        self._name_input.setMaxLength(32)
        self._name_input.setPlaceholderText("Profile name (max 32 characters)")
        self._name_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._name_input)

        # Character-set warning (hidden unless the typed name currently
        # contains a character the device naming API doesn't accept -- see
        # src/utils/device_name.py). Disallowed characters are stripped
        # automatically on save, this is advance notice of that, not a hard
        # block on typing.
        self._char_warning_label = QLabel(_CHAR_WARNING)
        self._char_warning_label.setWordWrap(True)
        self._char_warning_label.setProperty("class", "warning")
        self._char_warning_label.setVisible(False)
        layout.addWidget(self._char_warning_label)

        # Warning label (hidden by default; text swaps between the active-
        # profile and existing-non-active-profile cases, see classify())
        self._warning_label = QLabel(_ACTIVE_WARNING)
        self._warning_label.setWordWrap(True)
        self._warning_label.setProperty("class", "warning")
        self._warning_label.setVisible(False)
        layout.addWidget(self._warning_label)

        # Always-visible clarification -- unconditional regardless of which
        # name is chosen: RoomFitSafeWrite.execute() always activates the
        # pushed profile and enables RoomFit on success (see
        # docs/wiim_api_notes.md's RoomFit "Write workflow" section). Placed
        # right after the input it clarifies, not after the Save button --
        # it's a caveat about what typing a name and saving will do, so it
        # reads naturally before the user reaches the action itself.
        activation_note = QLabel(
            "<b>NOTE:</b> Saving will make this profile active on your device, "
            "turning RoomFit on if it's currently off."
        )
        activation_note.setProperty("class", "caption")
        activation_note.setWordWrap(True)
        layout.addWidget(activation_note)

        # Existing profiles section
        profiles_heading = QLabel("Existing Profiles")
        profiles_heading.setProperty("class", "subheading")
        layout.addSpacing(SPACING_SM)
        layout.addWidget(profiles_heading)

        self._profiles_list = QListWidget()
        self._profiles_list.setObjectName("NameProfileExistingList")
        style_selectable_list(self._profiles_list)
        self._profiles_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._profiles_list.setMaximumHeight(150)
        self._profiles_list.itemClicked.connect(self._on_profile_item_clicked)
        layout.addWidget(self._profiles_list)

        # Leading stretch pins Save to the bottom of the page, matching the
        # primary button's position on every other wizard step.
        layout.addStretch()

        # Save button
        self._save_button = make_action_button(
            "Save", object_name="NameProfileSaveButton", style_class="primary"
        )
        self._save_button.setEnabled(False)
        self._save_button.clicked.connect(self._on_save_clicked)
        layout.addWidget(self._save_button, alignment=Qt.AlignmentFlag.AlignRight)

    def action_buttons(self) -> list[QWidget]:
        """Return buttons that should be disabled while an operation is in progress."""
        return [self._save_button]

    @property
    def active_profile(self) -> str:
        """The currently-active RoomFit profile name, or "" if none/unknown."""
        return self._active_profile

    def classify(self, name: str) -> Literal["none", "existing", "active"]:
        """How *name* relates to the currently-known profiles on this device.

        Shared by the inline warning label and the caller's pre-save confirm
        dialog (main_window.py::_on_name_confirmed) so both agree on when a
        save would overwrite something, without re-deriving the comparison
        in two places.
        """
        if not name:
            return "none"
        if name == self._active_profile:
            return "active"
        if name in self._existing_profiles:
            return "existing"
        return "none"

    def set_existing_profiles(
        self, profiles: list[str], active_profile: str = ""
    ) -> None:
        """Populate the existing profiles list and mark the active profile.

        The active entry gets a "(active)" text suffix plus bold/accent
        styling -- the text label is the primary signal (self-explanatory,
        doesn't rely on color perception); styling is reinforcement, not the
        only cue (#165).

        Args:
            profiles: List of existing RoomFit profile names on the device.
            active_profile: Name of the currently-active profile (empty if none).
        """
        self._active_profile = active_profile
        self._existing_profiles = list(profiles)
        self._profiles_list.clear()
        for name in profiles:
            is_active = name == active_profile
            item = QListWidgetItem(f"{name} (active)" if is_active else name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            apply_active_item_style(item, is_active)
            size_list_item(item)
            self._profiles_list.addItem(item)

        # Re-evaluate warning in case input already has text
        self._on_text_changed(self._name_input.text())

    def _on_profile_item_clicked(self, item: QListWidgetItem) -> None:
        """Populate the name field with the clicked profile's raw name.

        Purely local -- the profile names were already fetched once (via
        set_existing_profiles()) before this page is shown, so this doesn't
        trigger another device query.
        """
        name = item.data(Qt.ItemDataRole.UserRole)
        if name:
            self._name_input.setText(name)

    def _on_text_changed(self, text: str) -> None:
        """Handle text input changes: enable/disable Save and show/hide warnings."""
        stripped = text.strip()
        self._char_warning_label.setVisible(has_invalid_device_name_chars(stripped))

        # Existing/active-profile warning and the Save-enabled state both key
        # off the name as it will actually be saved (post-sanitization), not
        # the raw typed text -- otherwise a name that only differs from an
        # existing profile by disallowed characters would misleadingly show
        # no overwrite warning.
        sanitized = sanitize_device_name(stripped).strip()
        self._save_button.setEnabled(bool(sanitized))

        kind = self.classify(sanitized)
        if kind == "active":
            self._warning_label.setText(_ACTIVE_WARNING)
            self._warning_label.setVisible(True)
        elif kind == "existing":
            self._warning_label.setText(_EXISTING_WARNING.format(name=sanitized))
            self._warning_label.setVisible(True)
        else:
            self._warning_label.setVisible(False)

    def _on_save_clicked(self) -> None:
        """Emit name_confirmed with the sanitized, trimmed profile name.

        Strips any character the device naming API doesn't accept (see
        src/utils/device_name.py) so a push never fails on a rejected name.
        """
        name = sanitize_device_name(self._name_input.text().strip()).strip()
        if name:
            self.name_confirmed.emit(name)
