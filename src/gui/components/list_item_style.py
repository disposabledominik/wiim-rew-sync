"""Shared styling for "currently active on this device" list items.

Used by both NameProfilePage's RoomFit profile list and PresetsDeviceView's
combined preset/profile list (#165/#165c), and by FiltersPage's merged
Device-panel list, so all three independently-built lists stay visually
consistent by construction rather than by convention.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QListWidgetItem

from src.gui.constants import ACCENT_COLOR, LIST_ITEM_HEIGHT

if TYPE_CHECKING:
    # Only for typing -- avoids a runtime circular import, since
    # presets_device_view.py imports apply_active_item_style from here.
    from src.gui.views.presets_device_view import PresetItem


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
    list_item.setSizeHint(QSize(0, LIST_ITEM_HEIGHT))
    return list_item
