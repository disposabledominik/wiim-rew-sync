"""Profile management panel with local and device profile tabs.

Provides a UI shell for all nine CRUD+tag profile operations and device
preset management. Emits signals for all mutations — does NOT perform any
storage or network I/O directly.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.models.capabilities import DeviceCapabilities
from src.models.profile import Profile


class ProfilePanel(QWidget):
    """Profile management panel with local profiles and device profiles tabs.

    Signals:
        profile_load_requested: Emitted when user wants to load a local profile
            into the EQ table. Payload: Profile object.
        profile_save_requested: Emitted when user wants to save current EQ state
            as a local profile. Payload: profile name (str).
        profile_rename_requested: Emitted when user wants to rename a profile.
            Payload: (old_name, new_name).
        profile_delete_requested: Emitted when user wants to delete a local profile.
            Payload: profile name (str).
        profile_duplicate_requested: Emitted when user wants to duplicate a profile.
            Payload: (source_name, new_name).
        profile_add_tag_requested: Emitted when user wants to add a tag.
            Payload: (profile_name, tag).
        profile_remove_tag_requested: Emitted when user wants to remove a tag.
            Payload: (profile_name, tag).
        device_profile_load_requested: Emitted when user wants to load a device
            preset into live DSP. Payload: profile name (str).
        device_profile_delete_requested: Emitted when user wants to delete a device
            preset. Payload: profile name (str).
    """

    profile_load_requested = Signal(object)  # Profile
    profile_save_requested = Signal(str)  # profile_name
    profile_rename_requested = Signal(str, str)  # old_name, new_name
    profile_delete_requested = Signal(str)  # profile_name
    profile_duplicate_requested = Signal(str, str)  # source_name, new_name
    profile_add_tag_requested = Signal(str, str)  # profile_name, tag
    profile_remove_tag_requested = Signal(str, str)  # profile_name, tag
    device_profile_load_requested = Signal(str)  # profile_name
    device_profile_delete_requested = Signal(str)  # profile_name

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the profile panel.

        Args:
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self._profiles: list[Profile] = []
        self._device_profiles: list[dict[str, str]] = []
        self._device_channel_mode: str = "Stereo"
        self._setup_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the panel layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._tab_widget = QTabWidget()
        self._setup_local_tab()
        self._setup_device_tab()
        layout.addWidget(self._tab_widget)

    def _setup_local_tab(self) -> None:
        """Build the local profiles tab with list and CRUD+tag buttons."""
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)

        # Profile list
        self._local_list = QListWidget()
        self._local_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        tab_layout.addWidget(self._local_list)

        # CRUD buttons row
        crud_row = QHBoxLayout()
        self._save_btn = QPushButton("Save")
        self._load_btn = QPushButton("Load")
        self._rename_btn = QPushButton("Rename")
        self._delete_btn = QPushButton("Delete")
        self._duplicate_btn = QPushButton("Duplicate")

        for btn in (
            self._save_btn,
            self._load_btn,
            self._rename_btn,
            self._delete_btn,
            self._duplicate_btn,
        ):
            crud_row.addWidget(btn)

        crud_row.addStretch()
        tab_layout.addLayout(crud_row)

        # Tag management row
        tag_row = QHBoxLayout()
        tag_row.addWidget(QLabel("Tag:"))
        self._tag_input = QLineEdit()
        self._tag_input.setPlaceholderText("Enter tag...")
        self._tag_input.setMaximumWidth(200)
        tag_row.addWidget(self._tag_input)

        self._add_tag_btn = QPushButton("Add Tag")
        self._remove_tag_btn = QPushButton("Remove Tag")
        tag_row.addWidget(self._add_tag_btn)
        tag_row.addWidget(self._remove_tag_btn)
        tag_row.addStretch()
        tab_layout.addLayout(tag_row)

        self._tab_widget.addTab(tab, "Local Profiles")

    def _setup_device_tab(self) -> None:
        """Build the device profiles tab with list and load/delete buttons."""
        self._device_tab = QWidget()
        tab_layout = QVBoxLayout(self._device_tab)

        # Device profile list
        self._device_list = QListWidget()
        self._device_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        tab_layout.addWidget(self._device_list)

        # Action buttons row
        actions_row = QHBoxLayout()
        self._device_load_btn = QPushButton("Load to DSP")
        self._device_delete_btn = QPushButton("Delete")
        actions_row.addWidget(self._device_load_btn)
        actions_row.addWidget(self._device_delete_btn)
        actions_row.addStretch()
        tab_layout.addLayout(actions_row)

        self._tab_widget.addTab(self._device_tab, "Device Profiles")
        # Hidden by default until capabilities confirm support
        self._tab_widget.setTabVisible(1, False)

    # ------------------------------------------------------------------
    # Signal Connections
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """Wire internal widget signals to handler methods."""
        self._save_btn.clicked.connect(self._on_save_clicked)
        self._load_btn.clicked.connect(self._on_load_clicked)
        self._rename_btn.clicked.connect(self._on_rename_clicked)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        self._duplicate_btn.clicked.connect(self._on_duplicate_clicked)
        self._add_tag_btn.clicked.connect(self._on_add_tag_clicked)
        self._remove_tag_btn.clicked.connect(self._on_remove_tag_clicked)
        self._device_load_btn.clicked.connect(self._on_device_load_clicked)
        self._device_delete_btn.clicked.connect(self._on_device_delete_clicked)

    # ------------------------------------------------------------------
    # Local Profile Handlers
    # ------------------------------------------------------------------

    def _on_save_clicked(self) -> None:
        """Handle Save button click — prompt for profile name and emit signal."""
        name, ok = QInputDialog.getText(
            self, "Save Profile", "Profile name:", QLineEdit.EchoMode.Normal, ""
        )
        if ok and name.strip():
            self.profile_save_requested.emit(name.strip())

    def _on_load_clicked(self) -> None:
        """Handle Load button click — emit selected profile for loading."""
        profile = self._get_selected_local_profile()
        if profile is None:
            return

        if not self._check_mode_mismatch(profile, self._device_channel_mode):
            return

        self.profile_load_requested.emit(profile)

    def _on_rename_clicked(self) -> None:
        """Handle Rename button click — prompt for new name and emit signal."""
        profile = self._get_selected_local_profile()
        if profile is None:
            return

        new_name, ok = QInputDialog.getText(
            self,
            "Rename Profile",
            "New name:",
            QLineEdit.EchoMode.Normal,
            profile.name,
        )
        if ok and new_name.strip() and new_name.strip() != profile.name:
            self.profile_rename_requested.emit(profile.name, new_name.strip())

    def _on_delete_clicked(self) -> None:
        """Handle Delete button click — confirm and emit signal."""
        profile = self._get_selected_local_profile()
        if profile is None:
            return

        reply = QMessageBox.question(
            self,
            "Delete Profile",
            f"Delete profile '{profile.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.profile_delete_requested.emit(profile.name)

    def _on_duplicate_clicked(self) -> None:
        """Handle Duplicate button click — prompt for new name and emit signal."""
        profile = self._get_selected_local_profile()
        if profile is None:
            return

        new_name, ok = QInputDialog.getText(
            self,
            "Duplicate Profile",
            "New name:",
            QLineEdit.EchoMode.Normal,
            f"{profile.name} (copy)",
        )
        if ok and new_name.strip():
            self.profile_duplicate_requested.emit(profile.name, new_name.strip())

    def _on_add_tag_clicked(self) -> None:
        """Handle Add Tag button click — emit tag addition signal."""
        profile = self._get_selected_local_profile()
        if profile is None:
            return

        tag = self._tag_input.text().strip()
        if not tag:
            return

        self.profile_add_tag_requested.emit(profile.name, tag)
        self._tag_input.clear()

    def _on_remove_tag_clicked(self) -> None:
        """Handle Remove Tag button click — emit tag removal signal."""
        profile = self._get_selected_local_profile()
        if profile is None:
            return

        tag = self._tag_input.text().strip()
        if not tag:
            return

        self.profile_remove_tag_requested.emit(profile.name, tag)
        self._tag_input.clear()

    # ------------------------------------------------------------------
    # Device Profile Handlers
    # ------------------------------------------------------------------

    def _on_device_load_clicked(self) -> None:
        """Handle device Load button click — emit device profile load signal."""
        item = self._device_list.currentItem()
        if item is None:
            return

        profile_name = item.data(256)  # Qt.ItemDataRole.UserRole == 256
        if profile_name:
            self.device_profile_load_requested.emit(profile_name)

    def _on_device_delete_clicked(self) -> None:
        """Handle device Delete button click — confirm and emit signal."""
        item = self._device_list.currentItem()
        if item is None:
            return

        profile_name = item.data(256)  # Qt.ItemDataRole.UserRole
        if not profile_name:
            return

        reply = QMessageBox.question(
            self,
            "Delete Device Profile",
            f"Delete device preset '{profile_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.device_profile_delete_requested.emit(profile_name)

    # ------------------------------------------------------------------
    # Public Slots
    # ------------------------------------------------------------------

    def on_capabilities_ready(self, capabilities: DeviceCapabilities) -> None:
        """Slot: configure panel based on device capabilities.

        Shows or hides the device profiles tab based on
        ``supports_profile_enumeration``.

        Args:
            capabilities: Probed device capabilities.
        """
        show_device_tab = capabilities.supports_profile_enumeration
        self._tab_widget.setTabVisible(1, show_device_tab)

        # Track device channel mode for mismatch checks
        if capabilities.supports_channel_peq:
            self._device_channel_mode = "L/R"
        else:
            self._device_channel_mode = "Stereo"

    def on_profiles_updated(self, profiles: list[Profile]) -> None:
        """Slot: refresh local profile list with current profile data.

        Args:
            profiles: Complete list of locally-stored profiles.
        """
        self._profiles = profiles
        self._local_list.clear()

        for profile in profiles:
            display_text = profile.name
            if profile.tags:
                tags_str = ", ".join(profile.tags)
                display_text = f"{profile.name}  [{tags_str}]"

            item = QListWidgetItem(display_text)
            item.setData(256, profile.name)  # Qt.ItemDataRole.UserRole
            self._local_list.addItem(item)

    def on_device_profiles_ready(self, device_profiles: list[dict[str, str]]) -> None:
        """Slot: refresh device profile list.

        Each dict is expected to have at least 'name' and optionally
        'channel_mode' keys.

        Args:
            device_profiles: List of device preset descriptors.
        """
        self._device_profiles = device_profiles
        self._device_list.clear()

        for dp in device_profiles:
            name = dp.get("name", "Unknown")
            mode = dp.get("channel_mode", "")
            display_text = f"{name}  ({mode})" if mode else name

            item = QListWidgetItem(display_text)
            item.setData(256, name)  # Qt.ItemDataRole.UserRole
            self._device_list.addItem(item)

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _get_selected_local_profile(self) -> Profile | None:
        """Get the Profile object for the currently selected local list item.

        Returns:
            The selected Profile, or None if nothing is selected.
        """
        item = self._local_list.currentItem()
        if item is None:
            return None

        profile_name = item.data(256)  # Qt.ItemDataRole.UserRole
        for profile in self._profiles:
            if profile.name == profile_name:
                return profile
        return None

    def _check_mode_mismatch(self, profile: Profile, device_mode: str) -> bool:
        """Check whether loading a profile would create a channel mode mismatch.

        Shows a warning dialog if a Stereo profile is loaded onto a device in
        L/R mode (or vice versa). The user can choose to proceed or cancel.

        Args:
            profile: The profile being loaded.
            device_mode: Current device channel mode ("Stereo" or "L/R").

        Returns:
            True if the operation should proceed, False to cancel.
        """
        profile_is_stereo = profile.channel_mode == "stereo"
        device_is_stereo = device_mode == "Stereo"

        if profile_is_stereo == device_is_stereo:
            return True

        # Mode mismatch detected
        if profile_is_stereo:
            msg = (
                f"Profile '{profile.name}' is a Stereo profile, but the device "
                "is currently in L/R mode.\n\nLoad anyway?"
            )
        else:
            msg = (
                f"Profile '{profile.name}' is an L/R profile, but the device "
                "is currently in Stereo mode.\n\nLoad anyway?"
            )

        reply = QMessageBox.warning(
            self,
            "Channel Mode Mismatch",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes
