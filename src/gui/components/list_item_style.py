"""Shared styling and behavior for every selectable QListWidget in the app.

Three responsibilities live here:

1. style_selectable_list() -- the one place every list's shared visual
   convention (selection/hover styling class, alternating row shading, and
   the gap between rows) is applied, so no list can drift from another by
   forgetting one of the three.
2. Row builders for the "currently active on this device" styling used by
   NameProfilePage's RoomFit profile list, PresetsDeviceView's combined
   preset/profile list (#165/#165c), FiltersPage's merged Device-panel list,
   and the local-preset row format shared by MyPresetsView and FiltersPage's
   Local Library panel -- so independently-built lists stay visually
   consistent by construction rather than by convention.
3. resolve_batch_targets()/show_list_context_menu() -- the shared
   right-click-context-menu scaffold (selection-batching rule + itemAt/
   None-check/exec boilerplate) used by both MyPresetsView and
   PresetsDeviceView, so the "does this action apply to just the clicked
   item, or the whole multi-selection" rule can't drift between the two.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMenu

from src.gui.constants import ACCENT_COLOR, LIST_ITEM_HEIGHT, LIST_ITEM_SPACING
from src.models.canonical import CanonicalFilter
from src.models.profile import Profile

if TYPE_CHECKING:
    # Only for typing -- avoids a runtime circular import, since
    # presets_device_view.py imports apply_active_item_style from here.
    from src.gui.views.presets_device_view import PresetItem


def style_selectable_list(list_widget: QListWidget) -> None:
    """Apply the app's one shared visual convention to a selectable list.

    Sets the "selectableList" QSS class (hover/selection tint + left-border
    accent, see fluent_dark.qss/fluent_light.qss), turns on alternating row
    shading, and applies the standard inter-row gap -- the three properties
    that had drifted independently across the app's various QListWidget
    instances (some had alternating rows but no gap, others a gap but no
    alternating rows, others neither) before every list started calling this
    instead of setting its own subset by hand.
    """
    list_widget.setProperty("class", "selectableList")
    list_widget.setAlternatingRowColors(True)
    list_widget.setSpacing(LIST_ITEM_SPACING)


def size_list_item(item: QListWidgetItem) -> None:
    """Give a list item the app's standard comfortable row height.

    Shared so every plain-text row (not just the custom-widget ones) gets
    the same click/touch target and vertically-centered text as the rest
    of the app, instead of falling back to Qt's tighter auto-computed
    height.
    """
    item.setSizeHint(QSize(0, LIST_ITEM_HEIGHT))


def apply_active_item_style(item: QListWidgetItem, is_active: bool) -> None:
    """Apply the "active" bold/accent/tooltip treatment to a list item.

    The caller is responsible for the item's text (including any "(active)"
    suffix) -- that's the primary, color-independent signal; this only adds
    the reinforcing visual cue, and does nothing if `is_active` is False.
    """
    if not is_active:
        return
    font = item.font()
    font.setBold(True)
    item.setFont(font)
    item.setForeground(QColor(ACCENT_COLOR))
    item.setToolTip("Currently active on this device")


def build_preset_list_item(
    item: PresetItem, is_active: bool, is_eq_off: bool = False
) -> QListWidgetItem:
    """Build a QListWidgetItem for a device preset/profile row.

    Format: "Name  [ChannelMode]  [Type]", with a "(active)" text suffix --
    the primary, color-independent signal -- plus apply_active_item_style's
    bold/accent reinforcement when `is_active`. The item's UserRole data is
    set to `item` itself; callers needing a different payload (e.g. a
    synthetic sentinel) should overwrite it with setData() after this call.

    Args:
        is_active: Whether this row's Name matches the source's/device's
            current active config -- see build_preset_list_item's callers
            (build_peq_rows, _populate_roomfit_list) for how that's decided.
        is_eq_off: Only meaningful when `is_active` is True. The device
            reports a Name (or lack of one) independent of whether that
            config is actually being applied to audio right now -- "(active)"
            alone would claim it's live even when the PEQ/RoomFit toggle for
            that scope is off. When True, the suffix becomes
            "(active, PEQ off)"/"(active, RoomFit off)" instead of plain
            "(active)", read from `item.preset_type` since a single shared
            list can mix both types.
    """
    text = f"{item.name}  [{item.channel_mode}]  [{item.preset_type}]"
    if is_active:
        if is_eq_off:
            off_label = "PEQ off" if item.preset_type == "PEQ" else "RoomFit off"
            text = f"{text}  (active, {off_label})"
        else:
            text = f"{text}  (active)"
    list_item = QListWidgetItem(text)
    apply_active_item_style(list_item, is_active)
    list_item.setData(Qt.ItemDataRole.UserRole, item)
    size_list_item(list_item)
    return list_item


def preset_row_text(profile: Profile) -> str:
    """Build the display text for a locally-saved preset/profile row.

    Format: "Name  [Stereo: N bands]" or "Name  [L: N bands / R: M bands]" --
    the count of *enabled* bands per channel (type != "OFF"), not the raw
    slot count. A Profile saved from a device read (the common case, via
    _do_preset_save()) always carries exactly capabilities.max_filters
    slots -- read_peq()/parse_wiim_band_array() parse the device's full
    fixed-size band array 1:1, and any slot the user hasn't configured
    comes back as a mode=-1 ("OFF") placeholder, not omitted -- so counting
    raw list length here would show every preset as having the device's max
    band count regardless of how many filters it actually uses. Shared by
    build_local_preset_list_item() and by MyPresetsView's inline-rename
    flow, which restores a row's text from this same function once editing
    ends.
    """
    if profile.channel_mode.is_lr:
        left = _active_band_count(profile.filters_l)
        right = _active_band_count(profile.filters_r)
        summary = f"L: {_band_count_text(left)} / R: {_band_count_text(right)}"
    else:
        total = _active_band_count(profile.filters)
        summary = f"{profile.channel_mode.display_value}: {_band_count_text(total)}"
    return f"{profile.name}  [{summary}]"


def _active_band_count(filters: list[CanonicalFilter] | None) -> int:
    """Count bands that aren't the "OFF" placeholder type."""
    return sum(1 for f in filters or [] if f.type != "OFF")


def _band_count_text(count: int) -> str:
    """Format a band count with correct singular/plural, e.g. '1 band', '2 bands'."""
    return f"{count} band" if count == 1 else f"{count} bands"


def build_local_preset_list_item(profile: Profile) -> QListWidgetItem:
    """Build a QListWidgetItem for a locally-saved preset/profile row.

    Plain text (see preset_row_text()), styled identically to
    build_preset_list_item()'s device-side rows -- same font, height, and
    selection behavior -- rather than a bespoke multi-widget row, so the
    "My Saved Presets" list and the Filters step's Local Library panel
    (which shares this row format, see filters_page.py) can't visually
    drift from the rest of the app's lists.
    """
    list_item = QListWidgetItem(preset_row_text(profile))
    list_item.setData(Qt.ItemDataRole.UserRole, profile)
    size_list_item(list_item)
    return list_item


def resolve_batch_targets(list_widget: QListWidget, item: QListWidgetItem) -> list[Any]:
    """Resolve which item(s) a right-click context-menu action should act on.

    Right-clicking in Qt does not clear an existing multi-selection, so if
    the right-clicked item is part of one, the action batches over the full
    selection -- otherwise it would silently drop every selected item except
    the one under the cursor, contradicting a toolbar button's own batch
    behavior on the same selection. Otherwise, the action applies to just
    the clicked item, ignoring a selection it isn't part of. Shared by
    MyPresetsView and PresetsDeviceView's context menus so this rule can't
    drift between the two (each menu builder still applies its own type-
    specific logic, e.g. is_batch/has_custom, on top of this).

    Returns each target's UserRole payload (a Profile or PresetItem
    depending on the caller), not the QListWidgetItem itself. Items with no
    UserRole payload are skipped, matching PresetsDeviceView's toolbar-path
    guard (_get_all_selected_items()) so the two batch paths can't diverge
    in failure mode.
    """
    selected = list_widget.selectedItems()
    if item in selected and len(selected) > 1:
        return [
            data
            for selected_item in selected
            if (data := selected_item.data(Qt.ItemDataRole.UserRole)) is not None
        ]
    data = item.data(Qt.ItemDataRole.UserRole)
    return [data] if data is not None else []


def show_list_context_menu(
    list_widget: QListWidget,
    position: QPoint,
    build_menu: Callable[[QListWidgetItem], QMenu],
) -> None:
    """Show a right-click context menu for the item at position, if any.

    Shared "itemAt -> None-check -> build -> exec" scaffold for every
    list's context menu, so this boilerplate (and any future fix to it,
    e.g. a mapToGlobal offset correction) can't diverge between lists.
    `build_menu` receives the clicked QListWidgetItem and returns the menu
    to show -- the caller owns whatever selection-batching logic it needs
    (see resolve_batch_targets()).
    """
    item = list_widget.itemAt(position)
    if item is None:
        return
    menu = build_menu(item)
    menu.exec(list_widget.viewport().mapToGlobal(position))
