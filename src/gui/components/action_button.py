"""Shared button construction — consistent styling triad and text eliding.

Every action button in the app should be built via :func:`make_action_button`
so it gets the same `objectName` + `class` + pointing-hand-cursor treatment
that drives the shared QSS stylesheets, and so its label elides gracefully
instead of clipping when the window is narrowed (native ``QPushButton``
painting has no built-in ellipsis).
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton, QWidget

from src.gui.components.eliding_text import ElidingTextMixin


class ElidingPushButton(ElidingTextMixin, QPushButton):
    """A QPushButton whose label elides to fit its current width.

    The full label is kept internally and restored whenever there's enough
    room; only the *displayed* text is ever shortened. If the caller hasn't
    set an explicit tooltip, the full label is shown as a tooltip fallback
    while the text is elided (and cleared again once it isn't).
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_eliding(text)

    def _available_text_width(self) -> int:
        """Width available for the label, excluding Qt's own button chrome.

        Uses the style's own content-rect calculation (not a hardcoded
        padding guess) so this stays correct if the QSS padding ever
        changes.
        """
        option = QStyleOptionButton()
        self.initStyleOption(option)
        content_rect = self.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, option, self
        )
        return content_rect.width()

    def sizeHint(self) -> QSize:
        """See :meth:`ElidingTextMixin.sizeHint`."""
        return super().sizeHint()


def make_action_button(
    text: str,
    *,
    object_name: str,
    style_class: str,
    tooltip: str = "",
    parent: QWidget | None = None,
) -> ElidingPushButton:
    """Build an :class:`ElidingPushButton` with the standard styling triad.

    Args:
        text: Button label.
        object_name: Qt object name (for QSS targeting and test lookups).
        style_class: QSS `class` property value (e.g. "primary", "secondary",
            "danger", "ghost", "success", "warning", "linkButton").
        tooltip: Optional explicit tooltip. Left unset, the button falls back
            to showing its full label as a tooltip only while elided.
        parent: Optional parent widget.

    Returns:
        A configured, unparented-if-parent-is-None ElidingPushButton.
    """
    button = ElidingPushButton(text, parent)
    button.setObjectName(object_name)
    button.setProperty("class", style_class)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        button.setToolTip(tooltip)
    return button
