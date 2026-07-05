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

from src.gui.components.list_item_style import apply_active_item_style
from src.gui.components.page_layout import (
    ICON_NO_CONNECTION,
    build_centered_content,
    center_column,
    make_empty_state_icon,
    make_page_title,
)
from src.gui.constants import (
    LIST_ITEM_HEIGHT,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
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
        delete_requested(list): User wants to permanently delete selected
            items from the connected device.
    """

    export_requested = Signal(list)
    save_to_my_presets = Signal(list)
    load_into_editor = Signal(object)
    copy_to_device_requested = Signal(list)
    apply_to_sources_requested = Signal(str, list)
    delete_requested = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PresetsDeviceView")

        self._peq_items: list[PresetItem] = []
        self._roomfit_items: list[PresetItem] = []
        self._active_peq_name: str = ""
        self._active_roomfit_name: str = ""

        self._setup_ui()
        # Start in empty state
        self.set_no_device()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_peq_presets(self, presets: list[PresetItem], active_name: str = "") -> None:
        """Populate the PEQ Presets section.

        Args:
            presets: List of PresetItem objects for PEQ presets.
            active_name: Name of the preset currently active on this source,
                if any (#165c) -- highlighted distinctly from selection.
        """
        self._peq_items = list(presets)
        self._active_peq_name = active_name
        self._show_content_state()
        self._populate_peq_list()

    def set_roomfit_profiles(
        self, profiles: list[PresetItem], active_name: str = ""
    ) -> None:
        """Populate the RoomFit Profiles section.

        Args:
            profiles: List of PresetItem objects for RoomFit profiles.
            active_name: Name of the profile currently active on the device,
                if any (#165c) -- highlighted distinctly from selection.
        """
        self._roomfit_items = list(profiles)
        self._active_roomfit_name = active_name
        self._show_content_state()
        # Mirrors set_roomfit_hidden()'s setVisible(False) -- without this,
        # the section stays hidden forever after the first non-RoomFit device
        # connection in a session, even once a RoomFit-capable device connects
        # afterward (#168).
        self._roomfit_section.setVisible(True)
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
        container_layout, container = build_centered_content(self)

        # Title — pinned to its sizeHint so it doesn't absorb leftover
        # vertical space (see RewPullView, which documents why that matters:
        # QLabel's default vertical-center alignment makes the title drift
        # whenever the visible state has less content than the other state).
        title = make_page_title("Presets on Device", container, object_name="view_title")
        title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        container_layout.addWidget(title)

        # Empty state widget — Expanding so it (not the title) absorbs the
        # leftover vertical space, letting its AlignCenter layout actually
        # center the icon/message in the available page area.
        self._empty_widget = self._build_empty_state()
        self._empty_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        container_layout.addWidget(self._empty_widget)

        # Content widget (shown when device connected)
        self._content_widget = QWidget()
        self._content_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
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

    def _build_empty_state(self) -> QWidget:
        """Build the 'no device connected' empty state."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(SPACING_MD)

        icon_label = make_empty_state_icon(
            ICON_NO_CONNECTION, object_name="PresetsDeviceEmptyIcon"
        )
        layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        message = QLabel("Connect a device to browse its presets and profiles")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setProperty("class", "secondary")
        message.setWordWrap(True)
        layout.addWidget(message)

        center_column(layout)
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
        header.setProperty("class", "subheading")
        layout.addWidget(header)

        # Unavailable message (Req 15.10)
        self._peq_unavailable_label = QLabel(
            "Device presets not available on this model"
        )
        self._peq_unavailable_label.setProperty("class", "warning")
        self._peq_unavailable_label.setWordWrap(True)
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
        self._peq_list.setProperty("class", "selectableList")
        self._peq_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._peq_list.setAlternatingRowColors(True)
        self._peq_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._peq_list.itemSelectionChanged.connect(self._on_peq_selection_changed)
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
        header.setProperty("class", "subheading")
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
        self._roomfit_list.setProperty("class", "selectableList")
        self._roomfit_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._roomfit_list.setAlternatingRowColors(True)
        self._roomfit_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._roomfit_list.itemSelectionChanged.connect(self._on_roomfit_selection_changed)
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
        self._export_btn.setProperty("class", "primary")
        self._export_btn.clicked.connect(self._on_export_clicked)
        layout.addWidget(self._export_btn)

        # Save to My Presets
        self._save_btn = QPushButton("Save to My Presets")
        self._save_btn.setObjectName("btn_save_presets")
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setProperty("class", "secondary")
        self._save_btn.clicked.connect(self._on_save_clicked)
        layout.addWidget(self._save_btn)

        # Load into Editor
        self._load_btn = QPushButton("Load into Editor")
        self._load_btn.setObjectName("btn_load_editor")
        self._load_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._load_btn.setProperty("class", "secondary")
        self._load_btn.clicked.connect(self._on_load_clicked)
        layout.addWidget(self._load_btn)

        # Copy to Another Device
        self._copy_btn = QPushButton("Copy to Another Device")
        self._copy_btn.setObjectName("btn_copy_device")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setProperty("class", "secondary")
        self._copy_btn.clicked.connect(self._on_copy_clicked)
        layout.addWidget(self._copy_btn)

        # Delete — irreversible, hardware-side, so styled distinctly (Req 15.x)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("btn_delete_preset")
        self._delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_btn.setProperty("class", "danger")
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        layout.addWidget(self._delete_btn)

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
            list_item = self._build_list_item(item, item.name == self._active_peq_name)
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
            list_item = self._build_list_item(
                item, item.name == self._active_roomfit_name
            )
            self._roomfit_list.addItem(list_item)

        self._update_action_buttons()

    def _build_list_item(self, item: PresetItem, is_active: bool) -> QListWidgetItem:
        """Build a QListWidgetItem for a preset/profile, optionally marked as
        currently-active on the device (#165c).

        The "(active)" text label is the primary signal (self-explanatory,
        doesn't rely on color perception); bold/accent styling is
        reinforcement, not the only cue -- matching NameProfilePage's
        equivalent convention (#165a). This is visually distinct from
        QListWidget's own click-selection highlighting (background color),
        which is untouched and orthogonal.
        """
        text = self._format_item_text(item)
        list_item = QListWidgetItem(f"{text}  (active)" if is_active else text)
        apply_active_item_style(list_item, is_active)
        list_item.setData(Qt.ItemDataRole.UserRole, item)
        list_item.setSizeHint(list_item.sizeHint().expandedTo(
            list_item.sizeHint().__class__(0, LIST_ITEM_HEIGHT)
        ))
        return list_item

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
        self._delete_btn.setEnabled(has_selection)

    # ------------------------------------------------------------------
    # Search/filter handlers
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_peq_search_changed(self, text: str) -> None:
        """Filter PEQ list based on search input."""
        self._populate_peq_list(filter_text=text)

    @Slot()
    def _on_peq_selection_changed(self) -> None:
        """Handle PEQ list selection — clear RoomFit selection for mutual exclusion."""
        if self._peq_list.selectedItems():
            self._roomfit_list.clearSelection()
        self._update_action_buttons()

    @Slot()
    def _on_roomfit_selection_changed(self) -> None:
        """Handle RoomFit list selection — clear PEQ selection for mutual exclusion."""
        if self._roomfit_list.selectedItems():
            self._peq_list.clearSelection()
        self._update_action_buttons()

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

    @Slot()
    def _on_delete_clicked(self) -> None:
        """Emit delete_requested with selected items."""
        selected = self._get_all_selected_items()
        if selected:
            self.delete_requested.emit(selected)
