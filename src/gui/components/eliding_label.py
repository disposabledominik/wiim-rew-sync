"""ElidingLabel — a QLabel whose text elides to fit its current width.

Plain ``QLabel``s don't elide; if the container narrows past the text's
natural width, Qt just clips it (part of the label silently disappears)
instead of shortening it gracefully. This mirrors
:class:`~src.gui.components.action_button.ElidingPushButton`'s behavior for
labels, via the shared :class:`~src.gui.components.eliding_text.ElidingTextMixin`.
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QLabel, QWidget

from src.gui.components.eliding_text import ElidingTextMixin


class ElidingLabel(ElidingTextMixin, QLabel):
    """A QLabel whose text elides to fit its current width.

    The full text is kept internally and restored whenever there's enough
    room; only the *displayed* text is ever shortened. If the caller hasn't
    set an explicit tooltip, the full text is shown as a tooltip fallback
    while it's elided (and cleared again once it isn't).
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_eliding(text)

    def _available_text_width(self) -> int:
        """Width available for the label text, inside its content margins."""
        return self.contentsRect().width()

    def sizeHint(self) -> QSize:
        """See :meth:`ElidingTextMixin.sizeHint`."""
        return super().sizeHint()
