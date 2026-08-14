"""PresetsDeviceView — browse PEQ presets and RoomFit profiles on device.

Displays two sections (PEQ Presets, RoomFit Profiles) fetched from the
connected device. Supports multi-select for batch operations: export,
save to local library, and copy to another device. Shows an empty state
when no device is connected.

Requirements referenced: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 15.8,
15.9, 15.10, 15.11, 15.12, 8.5, 8.6, 10.9.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QPoint, Qt, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.components.action_button import make_action_button
from src.gui.components.list_item_style import build_preset_list_item, style_selectable_list
from src.gui.components.page_layout import (
    ICON_NO_CONNECTION,
    build_centered_content,
    center_column,
    make_empty_state_icon,
    make_page_title,
)
from src.gui.constants import (
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
        is_custom: True only for the synthetic "Custom" row (see
            build_custom_peq_item) representing the device's live/unnamed
            active PEQ config. Read at dispatch time to route actions that
            need a real saved-preset name (e.g. Delete, or the source-side
            read behind Export/Save/Copy) differently -- an intrinsic field
            rather than a name comparison, so a real preset that happens to
            also be named "Custom" is never confused with it.
    """

    name: str
    channel_mode: str = "Stereo"
    preset_type: Literal["PEQ", "RoomFit"] = "PEQ"
    is_custom: bool = False


CUSTOM_PEQ_NAME = "Custom"


def build_custom_peq_item(channel_mode: str, name: str = CUSTOM_PEQ_NAME) -> PresetItem:
    """Synthetic PresetItem for the device's live/unnamed active PEQ config.

    Shown whenever a PEQ preset fetch resolves with active_name == "" -- the
    hardware-confirmed signal that the live config on this source was written
    directly (EQSetLV2SourceBand) rather than loaded from a saved preset,
    orphaning the device's own name association (docs/corrections.md,
    2026-07-05). Named "Custom" to match WiiM Home's own terminology for
    this state. Shared by PresetsDeviceView and FiltersPage's merged Device
    list so both surface it identically (#165c).

    Args:
        channel_mode: Channel mode label for the row.
        name: Display name. Defaults to "Custom", but build_peq_rows passes
            the device's real reported Name on an enumeration-unsupported
            device instead (see that function's enumeration_supported
            branch) -- it's still routed as `is_custom=True` either way,
            since without enumeration this app has no way to confirm the
            name corresponds to a real, separately-manageable saved preset.
    """
    return PresetItem(
        name=name or CUSTOM_PEQ_NAME, channel_mode=channel_mode, preset_type="PEQ", is_custom=True
    )


def build_peq_rows(
    items: list[PresetItem],
    active_name: str | None,
    active_channel_mode: str,
    active_enabled: bool = True,
    enumeration_supported: bool = True,
) -> list[tuple[PresetItem, bool, bool]]:
    """PEQ items paired with (is_active, is_eq_off) flags, with a synthetic
    row prepended for the live config when appropriate. Shared by
    PresetsDeviceView and FiltersPage's merged Device list so the "when does
    Custom appear" rule can't drift between the two call sites (#165c).

    active_enabled reflects the source's real-time PEQ on/off toggle
    (EQStat) -- independent of which Name is stored, since a source can have
    a saved or custom config selected while PEQ itself is switched off for
    that source. Only the active row's is_eq_off can ever be True; every
    other row is unaffected since it isn't what's currently loaded anyway.

    enumeration_supported=True (the common case): `items` is a real,
    complete saved-preset list, so a synthetic "Custom" row only makes sense
    when active_name == "" -- the hardware-confirmed signal that the live
    config doesn't match any saved preset (see build_custom_peq_item).

    enumeration_supported=False: `items` is always empty (there is no way to
    list saved presets on this device/model at all -- see
    DeviceCapabilities.supports_profile_enumeration), so there is no
    enumerated list to compare the live config against in the first place.
    The live config is then the *only* PEQ information available for this
    source, and must always get a row when known (active_name is not None)
    -- using the device's real reported Name if it has one, or "Custom" if
    not. Comparing only against active_name == "" here would silently drop
    a device that already has a *named* live config (e.g. set via WiiM
    Home before this app was ever used) from the list entirely, since
    "" was the only condition that ever produced a row.
    """
    rows: list[tuple[PresetItem, bool, bool]] = [
        (item, item.name == active_name, item.name == active_name and not active_enabled)
        for item in items
    ]
    if not enumeration_supported:
        if active_name is not None:
            rows.insert(
                0,
                (
                    build_custom_peq_item(active_channel_mode, active_name),
                    # Always active: items is [] whenever enumeration_supported
                    # is False, so this synthetic row is the only row and is
                    # by definition the active one -- unlike the enumeration-
                    # supported branch above, there's no other row to compare
                    # active_name against.
                    True,
                    not active_enabled,
                ),
            )
    elif active_name == "":
        rows.insert(0, (build_custom_peq_item(active_channel_mode), True, not active_enabled))
    return rows


def build_roomfit_rows(
    items: list[PresetItem],
    active_name: str,
    active_enabled: bool = True,
) -> list[tuple[PresetItem, bool, bool]]:
    """RoomFit items paired with (is_active, is_eq_off) flags.

    No synthetic row is ever prepended here, unlike build_peq_rows -- RoomFit
    has no "live but unnamed" concept distinct from its named profiles, only
    ever a currently-active one among them. active_enabled reflects
    RoomFit's global on/off toggle, mirroring build_peq_rows's active_enabled
    semantics. Shared by PresetsDeviceView and FiltersPage's merged Device
    list so the active/eq-off rule can't drift between the two call sites,
    same rationale as build_peq_rows (#165c).
    """
    return [
        (item, item.name == active_name, item.name == active_name and not active_enabled)
        for item in items
    ]


# ---------------------------------------------------------------------------
# Main view widget
# ---------------------------------------------------------------------------


class PresetsDeviceView(QWidget):
    """Browse PEQ presets and RoomFit profiles on the connected device.

    The view does NOT perform network calls directly. Data is supplied
    via :meth:`set_peq_presets` and :meth:`set_roomfit_profiles`. Actions
    are communicated outward via signals -- available both from the bottom
    action bar and from a right-click context menu on either list (see
    _build_context_menu), matching My Saved Presets' context menu.

    Signals:
        export_requested(list): User wants to export selected items as REW files.
        save_to_my_presets(list): Save selected items to local preset library.
        copy_to_device_requested(list): Copy selected items to another device.
        delete_requested(list): User wants to permanently delete selected
            items from the connected device.
    """

    export_requested = Signal(list)
    save_to_my_presets = Signal(list)
    copy_to_device_requested = Signal(list)
    delete_requested = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PresetsDeviceView")

        self._peq_items: list[PresetItem] = []
        self._roomfit_items: list[PresetItem] = []
        # None = not yet known (distinct from "" = confirmed no active
        # preset name) -- only "" shows the synthetic "Custom" row.
        self._active_peq_name: str | None = None
        self._active_peq_channel_mode: str = "Stereo"
        self._active_peq_enabled: bool = True
        self._peq_enumeration_supported: bool = True
        self._active_roomfit_name: str = ""
        self._active_roomfit_enabled: bool = True

        self._setup_ui()
        # Start in empty state
        self.set_no_device()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def action_buttons(self) -> list[QWidget]:
        """Return buttons that should be disabled while an operation is in progress."""
        return [
            self._export_btn,
            self._save_btn,
            self._copy_btn,
            self._delete_btn,
        ]

    def set_peq_presets(
        self,
        presets: list[PresetItem],
        active_name: str | None = None,
        active_channel_mode: str = "Stereo",
        active_enabled: bool = True,
        source_name: str = "",
        enumeration_supported: bool = True,
    ) -> None:
        """Populate the PEQ Presets section.

        Args:
            presets: List of PresetItem objects for PEQ presets.
            active_name: Name of the preset currently active on this source,
                if known (#165c) -- highlighted distinctly from selection.
                "" means the device confirmed the live config doesn't match
                any saved preset -- shown as a synthetic "Custom" row
                instead (see build_custom_peq_item). None (the default)
                means this isn't known yet -- no highlight, no Custom row.
            active_channel_mode: Channel mode of the live active config,
                used only to label the synthetic "Custom" row when
                active_name is "".
            active_enabled: Whether PEQ (EQStat) is actually switched on for
                this source right now -- independent of active_name/which
                config is stored, since a source can have a name/custom
                config selected while PEQ itself is toggled off. When False,
                the active row's "(active)" suffix becomes
                "(active, PEQ off)" instead (see build_peq_rows).
            source_name: The source this list/active state was fetched for
                (`state.primary_source`), shown as a caption under the
                section header so it's clear "Custom"/"(active)" reflect
                this one source, not the device's currently-playing input --
                this view has no source picker of its own, and can be
                reached (via the sidebar) before the user has ever visited
                the Source wizard step. Empty hides the caption.
            enumeration_supported: Whether `presets` is a real, complete
                saved-preset list (DeviceCapabilities.supports_profile_enumeration).
                When False, `presets` is always empty and the live config
                (active_name, whatever it is -- "" or a real device-assigned
                Name) is the only PEQ information available, so it must
                always get a row rather than only when active_name == ""
                (see build_peq_rows).
        """
        self._peq_items = list(presets)
        self._active_peq_name = active_name
        self._active_peq_channel_mode = active_channel_mode
        self._active_peq_enabled = active_enabled
        self._peq_enumeration_supported = enumeration_supported
        self._peq_source_label.setText(f"Showing live PEQ status for source: {source_name}")
        self._peq_source_label.setVisible(bool(source_name))
        self._show_content_state()
        self._populate_peq_list()

    def set_roomfit_profiles(
        self, profiles: list[PresetItem], active_name: str = "", active_enabled: bool = True
    ) -> None:
        """Populate the RoomFit Profiles section.

        Args:
            profiles: List of PresetItem objects for RoomFit profiles.
            active_name: Name of the profile currently active on the device,
                if any (#165c) -- highlighted distinctly from selection.
            active_enabled: Whether RoomFit is actually switched on right
                now -- independent of which profile is selected, since a
                profile can be selected while RoomFit itself is toggled off.
                When False, the active row's "(active)" suffix becomes
                "(active, RoomFit off)" instead.
        """
        self._roomfit_items = list(profiles)
        self._active_roomfit_name = active_name
        self._active_roomfit_enabled = active_enabled
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
        """Show message when the device has no usable PEQ info at all (Req 15.10).

        Emitted by PrimaryWorkflowManager.refresh_presets() when the device
        doesn't support PEQ, or does but the live-config read that would
        back a synthetic "Custom" row failed outright -- not merely because
        named-preset enumeration is unsupported, since that case still
        surfaces the live config as "Custom" via set_peq_presets().
        """
        self._peq_items = []
        self._peq_unavailable_label.setVisible(True)
        self._peq_list.setVisible(False)
        self._peq_search.setVisible(False)
        self._peq_source_label.setVisible(False)

    def set_roomfit_hidden(self) -> None:
        """Hide the RoomFit section when the device has no RoomFit support (Req 15.11)."""
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

        # Caption: which source this section's "Custom"/"(active)" state
        # reflects -- PEQ is per-source and this view has no source picker
        # of its own (see set_peq_presets()'s source_name docstring).
        self._peq_source_label = QLabel("")
        self._peq_source_label.setProperty("class", "secondary")
        self._peq_source_label.setVisible(False)
        layout.addWidget(self._peq_source_label)

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
        style_selectable_list(self._peq_list)
        self._peq_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._peq_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._peq_list.itemSelectionChanged.connect(self._on_peq_selection_changed)
        self._peq_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._peq_list.customContextMenuRequested.connect(
            lambda position: self._show_context_menu(self._peq_list, position)
        )
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
        style_selectable_list(self._roomfit_list)
        self._roomfit_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._roomfit_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._roomfit_list.itemSelectionChanged.connect(self._on_roomfit_selection_changed)
        self._roomfit_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._roomfit_list.customContextMenuRequested.connect(
            lambda position: self._show_context_menu(self._roomfit_list, position)
        )
        layout.addWidget(self._roomfit_list)

        return section

    def _build_actions_bar(self) -> QWidget:
        """Build the bottom action buttons bar."""
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, SPACING_MD, 0, 0)
        layout.setSpacing(SPACING_SM)

        # Export as REW File
        self._export_btn = make_action_button(
            "Export as REW File", object_name="btn_export_rew", style_class="primary"
        )
        self._export_btn.clicked.connect(self._on_export_clicked)
        layout.addWidget(self._export_btn)

        # Save to My Presets
        self._save_btn = make_action_button(
            "Save to My Presets", object_name="btn_save_presets", style_class="secondary"
        )
        self._save_btn.clicked.connect(self._on_save_clicked)
        layout.addWidget(self._save_btn)

        # Copy to Another Device
        self._copy_btn = make_action_button(
            "Copy to Another Device", object_name="btn_copy_device", style_class="secondary"
        )
        self._copy_btn.clicked.connect(self._on_copy_clicked)
        layout.addWidget(self._copy_btn)

        # Delete — irreversible, hardware-side, so styled distinctly (Req 15.x)
        self._delete_btn = make_action_button(
            "Delete", object_name="btn_delete_preset", style_class="danger"
        )
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        layout.addWidget(self._delete_btn)

        layout.addStretch()

        return bar

    # ------------------------------------------------------------------
    # List population
    # ------------------------------------------------------------------

    def _populate_peq_list(self, filter_text: str = "") -> None:
        """Populate the PEQ list widget from stored items.

        Prepends a synthetic "Custom" row (see build_custom_peq_item) when
        the live PEQ config on this source has no saved-preset name.
        Selectable like any other row -- Export/Save/Copy all work on it via
        a plain live read instead of the named-preset preview/restore dance
        (see WiiMAdapter.read_preset_preview_or_live). Delete is the
        exception: _update_action_buttons() disables it whenever the
        selection includes a custom item, since there's no saved preset to
        delete (#165c).

        Args:
            filter_text: Optional filter string for search.
        """
        self._peq_list.clear()
        self._peq_unavailable_label.setVisible(False)
        self._peq_list.setVisible(True)

        # Show search field when > 10 items (Req 10.9)
        self._peq_search.setVisible(len(self._peq_items) > 10)

        rows = build_peq_rows(
            self._peq_items,
            self._active_peq_name,
            self._active_peq_channel_mode,
            self._active_peq_enabled,
            self._peq_enumeration_supported,
        )

        for item, is_active, is_eq_off in rows:
            if filter_text and filter_text.lower() not in item.name.lower():
                continue
            list_item = build_preset_list_item(item, is_active, is_eq_off)
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

        rows = build_roomfit_rows(
            self._roomfit_items, self._active_roomfit_name, self._active_roomfit_enabled
        )
        for item, is_active, is_eq_off in rows:
            if filter_text and filter_text.lower() not in item.name.lower():
                continue
            list_item = build_preset_list_item(item, is_active, is_eq_off)
            self._roomfit_list.addItem(list_item)

        self._update_action_buttons()

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, list_widget: QListWidget, position: QPoint) -> None:
        """Show right-click context menu for the item at position.

        Shared by both the PEQ and RoomFit lists -- which list is passed in
        by the caller (see the customContextMenuRequested connections in
        _build_peq_section/_build_roomfit_section), matching My Saved
        Presets' equivalent context menu (MyPresetsView._show_context_menu).
        """
        item = list_widget.itemAt(position)
        if item is None:
            return

        menu = self._build_context_menu(list_widget, item)
        menu.exec(list_widget.viewport().mapToGlobal(position))

    def _build_context_menu(self, list_widget: QListWidget, item: QListWidgetItem) -> QMenu:
        """Build (without showing) the context menu for *item* in *list_widget*.

        Mirrors the toolbar's action set exactly: Export as REW File, Save
        to My Presets, Copy to Another Device, Delete. Right-clicking in Qt
        does not clear an existing multi-selection, so every action batches
        over the full selection when the right-clicked item is part of one
        -- otherwise they'd silently drop every selected item except the one
        under the cursor, contradicting the toolbar buttons' batch behavior
        on the same selection (same rationale as
        MyPresetsView._build_context_menu). Delete is disabled whenever the
        batch includes the synthetic "Custom" row (#165c) -- there's no
        saved preset on the device to delete, matching
        _update_action_buttons()'s toolbar-button logic.
        """
        selected = list_widget.selectedItems()
        if item in selected and len(selected) > 1:
            batch_targets = [i.data(Qt.ItemDataRole.UserRole) for i in selected]
        else:
            batch_targets = [item.data(Qt.ItemDataRole.UserRole)]
        has_custom = any(target.is_custom for target in batch_targets)

        menu = QMenu(self)
        menu.setObjectName("PresetsDeviceContextMenu")

        export_action = QAction("Export as REW File", menu)
        export_action.triggered.connect(
            lambda: self.export_requested.emit(batch_targets)
        )
        menu.addAction(export_action)

        save_action = QAction("Save to My Presets", menu)
        save_action.triggered.connect(
            lambda: self.save_to_my_presets.emit(batch_targets)
        )
        menu.addAction(save_action)

        copy_action = QAction("Copy to Another Device", menu)
        copy_action.triggered.connect(
            lambda: self.copy_to_device_requested.emit(batch_targets)
        )
        menu.addAction(copy_action)

        menu.addSeparator()

        delete_action = QAction("Delete", menu)
        delete_action.setEnabled(not has_custom)
        delete_action.triggered.connect(
            lambda: self.delete_requested.emit(batch_targets)
        )
        menu.addAction(delete_action)

        return menu

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
        """Enable/disable action buttons based on current selection.

        Delete is disabled whenever the synthetic "Custom" row (#165c) is
        part of the selection -- there's no saved preset on the device to
        delete, unlike Export/Save/Copy, which all work on it via a plain
        live read (see build_custom_peq_item).
        """
        selected = self._get_all_selected_items()
        has_selection = len(selected) > 0
        has_custom = any(item.is_custom for item in selected)

        self._export_btn.setEnabled(has_selection)
        self._save_btn.setEnabled(has_selection)
        self._copy_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection and not has_custom)

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
