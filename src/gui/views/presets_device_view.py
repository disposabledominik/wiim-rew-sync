"""PresetsDeviceView — browse PEQ presets and RoomFit profiles on device.

Displays two sections (PEQ Presets, RoomFit Profiles) fetched from the
connected device. Supports multi-select for batch operations: export,
save to local library, load into editor, and copy to another device.
Shows an empty state when no device is connected.

Requirements referenced: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 15.8,
15.9, 15.10, 15.11, 15.12, 8.5, 8.6, 10.9.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.constants import (
    ACCENT_COLOR,
    ACCENT_HOVER,
    CARD_RADIUS,
    LIST_ITEM_HEIGHT,
    MAX_CONTENT_WIDTH,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
    WARNING_COLOR,
)

# ---------------------------------------------------------------------------
# Data model for preset/profile items displayed in the list
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PresetItem:
    """Lightweight data object representing a device preset or profile.

    Attributes:
        name: Display name of the preset/profile.
        channel_mode: One of "Stereo", "L/R", or "Unknown".
        preset_type: Distinguishes PEQ presets from RoomFit profiles.
    """

    name: str
    channel_mode: str = "Stereo"
    preset_type: Literal["PEQ", "RoomFit"] = "PEQ"


# ---------------------------------------------------------------------------
# Main view widget
# ---------------------------------------------------------------------------


class PresetsDeviceView(QWidget):
    """Browse PEQ presets and RoomFit profiles on the connected device.

    The view does NOT perform network calls directly. Data is supplied
    via :meth:`set_peq_presets` and :meth:`set_roomfit_profiles`. Actions
    are communicated outward via signals.

    Signals:
        export_requested(list): User wants to export selected items as REW files.
        save_to_my_presets(list): Save selected items to local preset library.
        load_into_editor(object): Load a single item into the wizard editor.
        copy_to_device_requested(list): Copy selected items to another device.
        apply_to_sources_requested(str, list): Apply a PEQ preset to sources.
    """

    export_requested = Signal(list)
    save_to_my_presets = Signal(list)
    load_into_editor = Signal(object)
    copy_to_device_requested = Signal(list)
    apply_to_sources_requested = Signal(str, list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PresetsDeviceView")

        self._peq_items: list[PresetItem] = []
        self._roomfit_items: list[PresetItem] = []

        self._setup_ui()
        # Start in empty state
        self.set_no_device()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_peq_presets(self, presets: list[PresetItem]) -> None:
        """Populate the PEQ Presets section.

        Args:
            presets: List of PresetItem objects for PEQ presets.
        """
        self._peq_items = list(presets)
        self._show_content_state()
        self._populate_peq_list()

    def set_roomfit_profiles(self, profiles: list[PresetItem]) -> None:
        """Populate the RoomFit Profiles section.

        Args:
            profiles: List of PresetItem objects for RoomFit profiles.
        """
        self._roomfit_items = list(profiles)
        self._show_content_state()
        self._populate_roomfit_list()

    def set_no_device(self) -> None:
        """Show the empty state when no device is connected."""
        self._peq_items = []
        self._roomfit_items = []
        self._content_widget.setVisible(False)
        self._empty_widget.setVisible(True)
        self._update_action_buttons()

    def set_peq_unavailable(self) -> None:
        """Show message when device doesn't support profile enumeration (Req 15.10)."""
        self._peq_items = []
        self._peq_unavailable_label.setVisible(True)
        self._peq_list.setVisible(False)
        self._peq_search.setVisible(False)

    def set_roomfit_hidden(self) -> None:
        """Hide the RoomFit section when roomfit_level == 0 (Req 15.11)."""
        self._roomfit_items = []
        self._roomfit_section.setVisible(False)

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the view layout."""
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)
        root_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # Container with max width constraint
        container = QWidget()
        container.setMaximumWidth(MAX_CONTENT_WIDTH)
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(SPACING_LG)

        # Title
        title = QLabel("Presets on Device")
        title.setObjectName("view_title")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        container_layout.addWidget(title)

        # Empty state widget
        self._empty_widget = self._build_empty_state()
        container_layout.addWidget(self._empty_widget)

        # Content widget (shown when device connected)
        self._content_widget = QWidget()
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(SPACING_LG)

        # PEQ Presets section
        peq_section = self._build_peq_section()
        content_layout.addWidget(peq_section)

        # RoomFit Profiles section
        self._roomfit_section = self._build_roomfit_section()
        content_layout.addWidget(self._roomfit_section)

        # Action buttons bar
        self._actions_bar = self._build_actions_bar()
        content_layout.addWidget(self._actions_bar)

        container_layout.addWidget(self._content_widget)
        root_layout.addWidget(container)

    def _build_empty_state(self) -> QWidget:
        """Build the 'no device connected' empty state."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(SPACING_MD)

        icon_label = QLabel("\U0001F50C")  # Plug emoji as placeholder icon
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("font-size: 48px;")
        layout.addWidget(icon_label)

        message = QLabel("Connect a device to browse its presets and profiles")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setStyleSheet("font-size: 14px; color: #616161;")
        message.setWordWrap(True)
        layout.addWidget(message)

        return widget

    def _build_peq_section(self) -> QWidget:
        """Build the PEQ Presets section with search and list."""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_SM)

        # Section header
        header = QLabel("PEQ Presets")
        header.setObjectName("section_header_peq")
        header.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(header)

        # Unavailable message (Req 15.10)
        self._peq_unavailable_label = QLabel(
            "Device presets not available on this model"
        )
        self._peq_unavailable_label.setStyleSheet(
            f"color: {WARNING_COLOR}; font-style: italic; padding: {SPACING_SM}px;"
        )
        self._peq_unavailable_label.setVisible(False)
        layout.addWidget(self._peq_unavailable_label)

        # Search field (shown when > 10 items, Req 10.9)
        self._peq_search = QLineEdit()
        self._peq_search.setPlaceholderText("Search PEQ presets...")
        self._peq_search.setClearButtonEnabled(True)
        self._peq_search.setVisible(False)
        self._peq_search.textChanged.connect(self._on_peq_search_changed)
        layout.addWidget(self._peq_search)

        # List widget with multi-select
        self._peq_list = QListWidget()
        self._peq_list.setObjectName("peq_preset_list")
        self._peq_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._peq_list.setAlternatingRowColors(True)
        self._peq_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._peq_list.itemSelectionChanged.connect(self._update_action_buttons)
        layout.addWidget(self._peq_list)

        return section

    def _build_roomfit_section(self) -> QWidget:
        """Build the RoomFit Profiles section with search and list."""
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_SM)

        # Section header
        header = QLabel("RoomFit Profiles")
        header.setObjectName("section_header_roomfit")
        header.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(header)

        # Search field (shown when > 10 items, Req 10.9)
        self._roomfit_search = QLineEdit()
        self._roomfit_search.setPlaceholderText("Search RoomFit profiles...")
        self._roomfit_search.setClearButtonEnabled(True)
        self._roomfit_search.setVisible(False)
        self._roomfit_search.textChanged.connect(self._on_roomfit_search_changed)
        layout.addWidget(self._roomfit_search)

        # List widget with multi-select
        self._roomfit_list = QListWidget()
        self._roomfit_list.setObjectName("roomfit_profile_list")
        self._roomfit_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._roomfit_list.setAlternatingRowColors(True)
        self._roomfit_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._roomfit_list.itemSelectionChanged.connect(self._update_action_buttons)
        layout.addWidget(self._roomfit_list)

        return section

    def _build_actions_bar(self) -> QWidget:
        """Build the bottom action buttons bar."""
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, SPACING_MD, 0, 0)
        layout.setSpacing(SPACING_SM)

        # Export as REW File
        self._export_btn = QPushButton("Export as REW File")
        self._export_btn.setObjectName("btn_export_rew")
        self._export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {ACCENT_COLOR};"
            f"  color: white;"
            f"  border: none;"
            f"  border-radius: {CARD_RADIUS}px;"
            f"  padding: {SPACING_SM}px {SPACING_MD}px;"
            f"  font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background-color: {ACCENT_HOVER}; }}"
            f"QPushButton:disabled {{ background-color: #CCCCCC; color: #888888; }}"
        )
        self._export_btn.clicked.connect(self._on_export_clicked)
        layout.addWidget(self._export_btn)

        # Save to My Presets
        self._save_btn = QPushButton("Save to My Presets")
        self._save_btn.setObjectName("btn_save_presets")
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: transparent;"
            f"  color: {ACCENT_COLOR};"
            f"  border: 1px solid {ACCENT_COLOR};"
            f"  border-radius: {CARD_RADIUS}px;"
            f"  padding: {SPACING_SM}px {SPACING_MD}px;"
            f"  font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background-color: {ACCENT_COLOR}1A; }}"
            f"QPushButton:disabled {{ color: #CCCCCC; border-color: #CCCCCC; }}"
        )
        self._save_btn.clicked.connect(self._on_save_clicked)
        layout.addWidget(self._save_btn)

        # Load into Editor
        self._load_btn = QPushButton("Load into Editor")
        self._load_btn.setObjectName("btn_load_editor")
        self._load_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._load_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: transparent;"
            f"  color: {ACCENT_COLOR};"
            f"  border: 1px solid {ACCENT_COLOR};"
            f"  border-radius: {CARD_RADIUS}px;"
            f"  padding: {SPACING_SM}px {SPACING_MD}px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {ACCENT_COLOR}1A; }}"
            f"QPushButton:disabled {{ color: #CCCCCC; border-color: #CCCCCC; }}"
        )
        self._load_btn.clicked.connect(self._on_load_clicked)
        layout.addWidget(self._load_btn)

        # Copy to Another Device
        self._copy_btn = QPushButton("Copy to Another Device")
        self._copy_btn.setObjectName("btn_copy_device")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: transparent;"
            f"  color: {ACCENT_COLOR};"
            f"  border: 1px solid {ACCENT_COLOR};"
            f"  border-radius: {CARD_RADIUS}px;"
            f"  padding: {SPACING_SM}px {SPACING_MD}px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {ACCENT_COLOR}1A; }}"
            f"QPushButton:disabled {{ color: #CCCCCC; border-color: #CCCCCC; }}"
        )
        self._copy_btn.clicked.connect(self._on_copy_clicked)
        layout.addWidget(self._copy_btn)

        layout.addStretch()

        return bar

    # ------------------------------------------------------------------
    # List population
    # ------------------------------------------------------------------

    def _populate_peq_list(self, filter_text: str = "") -> None:
        """Populate the PEQ list widget from stored items.

        Args:
            filter_text: Optional filter string for search.
        """
        self._peq_list.clear()
        self._peq_unavailable_label.setVisible(False)
        self._peq_list.setVisible(True)

        # Show search field when > 10 items (Req 10.9)
        self._peq_search.setVisible(len(self._peq_items) > 10)

        for item in self._peq_items:
            if filter_text and filter_text.lower() not in item.name.lower():
                continue
            list_item = QListWidgetItem()
            list_item.setText(self._format_item_text(item))
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            list_item.setSizeHint(list_item.sizeHint().expandedTo(
                list_item.sizeHint().__class__(0, LIST_ITEM_HEIGHT)
            ))
            self._peq_list.addItem(list_item)

        self._update_action_buttons()

    def _populate_roomfit_list(self, filter_text: str = "") -> None:
        """Populate the RoomFit list widget from stored items.

        Args:
            filter_text: Optional filter string for search.
        """
        self._roomfit_list.clear()

        # Show search field when > 10 items (Req 10.9)
        self._roomfit_search.setVisible(len(self._roomfit_items) > 10)

        for item in self._roomfit_items:
            if filter_text and filter_text.lower() not in item.name.lower():
                continue
            list_item = QListWidgetItem()
            list_item.setText(self._format_item_text(item))
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            list_item.setSizeHint(list_item.sizeHint().expandedTo(
                list_item.sizeHint().__class__(0, LIST_ITEM_HEIGHT)
            ))
            self._roomfit_list.addItem(list_item)

        self._update_action_buttons()

    @staticmethod
    def _format_item_text(item: PresetItem) -> str:
        """Format display text for a list item with badges.

        Format: "Name  [ChannelMode]  [Type]"
        """
        return f"{item.name}  [{item.channel_mode}]  [{item.preset_type}]"

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _show_content_state(self) -> None:
        """Switch from empty state to content state."""
        self._empty_widget.setVisible(False)
        self._content_widget.setVisible(True)

    def _get_all_selected_items(self) -> list[PresetItem]:
        """Get all currently selected PresetItems from both lists."""
        selected: list[PresetItem] = []

        for item in self._peq_list.selectedItems():
            data = item.data(Qt.ItemDataRole.UserRole)
            if data is not None:
                selected.append(data)

        for item in self._roomfit_list.selectedItems():
            data = item.data(Qt.ItemDataRole.UserRole)
            if data is not None:
                selected.append(data)

        return selected

    @Slot()
    def _update_action_buttons(self) -> None:
        """Enable/disable action buttons based on current selection."""
        selected = self._get_all_selected_items()
        has_selection = len(selected) > 0
        single_selected = len(selected) == 1

        self._export_btn.setEnabled(has_selection)
        self._save_btn.setEnabled(has_selection)
        self._load_btn.setEnabled(single_selected)
        self._copy_btn.setEnabled(has_selection)

    # ------------------------------------------------------------------
    # Search/filter handlers
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_peq_search_changed(self, text: str) -> None:
        """Filter PEQ list based on search input."""
        self._populate_peq_list(filter_text=text)

    @Slot(str)
    def _on_roomfit_search_changed(self, text: str) -> None:
        """Filter RoomFit list based on search input."""
        self._populate_roomfit_list(filter_text=text)

    # ------------------------------------------------------------------
    # Action button handlers
    # ------------------------------------------------------------------

    @Slot()
    def _on_export_clicked(self) -> None:
        """Emit export_requested with selected items."""
        selected = self._get_all_selected_items()
        if selected:
            self.export_requested.emit(selected)

    @Slot()
    def _on_save_clicked(self) -> None:
        """Emit save_to_my_presets with selected items."""
        selected = self._get_all_selected_items()
        if selected:
            self.save_to_my_presets.emit(selected)

    @Slot()
    def _on_load_clicked(self) -> None:
        """Emit load_into_editor with the single selected item."""
        selected = self._get_all_selected_items()
        if len(selected) == 1:
            self.load_into_editor.emit(selected[0])

    @Slot()
    def _on_copy_clicked(self) -> None:
        """Emit copy_to_device_requested with selected items."""
        selected = self._get_all_selected_items()
        if selected:
            self.copy_to_device_requested.emit(selected)
