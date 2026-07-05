"""Shared styling for "currently active on this device" list items.

Used by both NameProfilePage's RoomFit profile list and PresetsDeviceView's
combined preset/profile list (#165/#165c) so the two independently-built
lists stay visually consistent by construction rather than by convention.
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QListWidgetItem

from src.gui.constants import ACCENT_COLOR


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
