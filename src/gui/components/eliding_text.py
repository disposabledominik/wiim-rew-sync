"""Shared reactive-eliding behavior for buttons and labels.

Both :class:`~src.gui.components.action_button.ElidingPushButton` and
:class:`~src.gui.components.eliding_label.ElidingLabel` need the same
full-text/tooltip bookkeeping and resize-driven re-eliding; this mixin holds
that shared logic so it isn't reimplemented twice. Subclasses provide
``_available_text_width()`` since a button's usable width (inside its style
chrome) is computed differently from a plain label's.
"""

from __future__ import annotations

from typing import cast

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics, QResizeEvent


class ElidingTextMixin:
    """Mix into a ``QWidget`` subclass exposing ``text``/``setText``/``setToolTip``/``font``.

    Must appear before the QWidget base in the subclass's MRO
    (``class Foo(ElidingTextMixin, QWidget)``).
    """

    _full_text: str
    _explicit_tooltip: str

    def _init_eliding(self, text: str) -> None:
        """Initialize eliding state and set the initial label, if any."""
        self._full_text = ""
        self._explicit_tooltip = ""
        if text:
            self.setText(text)

    def setText(self, text: str) -> None:
        """Remember the full label and display it in full.

        Deliberately does *not* elide here: at construction time (and any
        other pre-layout call) the widget's geometry is whatever default/stale
        value it happens to have, not a real available width. Eliding against
        that would bake a too-small size hint into the widget before the
        layout ever assigns it a real size — eliding only happens reactively,
        from `resizeEvent`, once real geometry exists.
        """
        self._full_text = text
        super().setText(text)  # type: ignore[misc]
        if not self._explicit_tooltip:
            super().setToolTip("")  # type: ignore[misc]

    def setToolTip(self, text: str) -> None:
        """Record an explicit tooltip so the elide fallback never overwrites it."""
        self._explicit_tooltip = text
        super().setToolTip(text)  # type: ignore[misc]

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Re-elide the label now that the widget has a real width."""
        super().resizeEvent(event)  # type: ignore[misc]
        self._apply_elide()

    def _apply_elide(self) -> None:
        """Elide `_full_text` to fit, or show it in full if there's room."""
        if not self._full_text:
            return

        available = self._available_text_width()
        if available <= 0:
            new_text = self._full_text
        else:
            metrics = QFontMetrics(self.font())  # type: ignore[attr-defined]
            new_text = metrics.elidedText(
                self._full_text, Qt.TextElideMode.ElideRight, available
            )

        # Skip redundant identical writes -- setText() always invalidates the
        # size hint and requests a re-layout, so calling it on every resize
        # tick (even with an unchanged string) needlessly triggers extra
        # layout passes.
        if new_text == super().text():  # type: ignore[misc]
            return
        super().setText(new_text)  # type: ignore[misc]
        if not self._explicit_tooltip:
            super().setToolTip(  # type: ignore[misc]
                self._full_text if new_text != self._full_text else ""
            )

    def _available_text_width(self) -> int:
        """Width available for the label. Overridden by subclasses."""
        raise NotImplementedError

    def sizeHint(self) -> QSize:
        """Report the size the *full* label wants, not the currently-elided text.

        Without this, a widget that's been elided narrow keeps that shrunken
        size hint forever afterward -- since layouts only reclaim space a
        widget's sizeHint says it wants, widening the window again would
        never restore the full label because Qt still thinks the elided text
        is all the widget ever needs (the widget stays too-narrow until the
        app is restarted). Computing the hint against the full text lets the
        layout offer full width back whenever it's available; resizeEvent
        will re-elide again if it turns out there still isn't enough room.
        """
        current = super().text()  # type: ignore[misc]
        if not self._full_text or current == self._full_text:
            return cast(QSize, super().sizeHint())  # type: ignore[misc]
        super().setText(self._full_text)  # type: ignore[misc]
        hint = cast(QSize, super().sizeHint())  # type: ignore[misc]
        super().setText(current)  # type: ignore[misc]
        return hint
