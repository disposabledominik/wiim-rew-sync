"""Shared warning-box construction -- bold header + body inside a warning frame.

Extracted from the push-confirmation flow's clamping/mode-mismatch warning
frames so every dialog that needs to show a "this will do X, are you sure"
style warning (or an informational caveat) builds it the same way, instead
of hand-rolling the same `QFrame`/`class="warningBox"` scaffolding per
caller.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QLayout, QVBoxLayout

from src.gui.constants import SPACING_SM


def make_warning_box(
    header_text: str,
    body_text: str,
    *,
    frame_object_name: str = "",
    body_object_name: str = "",
    body_rich_text: bool = True,
) -> QFrame:
    """Build a `class="warningBox"`-styled QFrame with a bold header and body.

    Args:
        header_text: Short heading, rendered as "⚠ {header_text}".
        body_text: Word-wrapped warning body.
        frame_object_name: Optional Qt object name for the returned frame.
        body_object_name: Optional Qt object name for the body label.
        body_rich_text: Whether `body_text` should be interpreted as HTML
            (True) or displayed verbatim as plain text (False) -- plain text
            avoids accidentally rendering "<"/"&" characters that can appear
            in summaries built from arbitrary values (e.g. clamped numbers).

    Returns:
        A QFrame ready to add to a dialog's layout.
    """
    frame = QFrame()
    if frame_object_name:
        frame.setObjectName(frame_object_name)
    frame.setProperty("class", "warningBox")
    layout = QVBoxLayout(frame)
    layout.setSpacing(SPACING_SM)

    header = QLabel(f"<b>⚠ {header_text}</b>")
    header.setTextFormat(Qt.TextFormat.RichText)
    header.setProperty("class", "warning")
    layout.addWidget(header)

    body = QLabel(body_text)
    if body_object_name:
        body.setObjectName(body_object_name)
    body.setWordWrap(True)
    body.setTextFormat(
        Qt.TextFormat.RichText if body_rich_text else Qt.TextFormat.PlainText
    )
    layout.addWidget(body)

    return frame


def add_optional_warning_box(
    layout: QLayout,
    warning: tuple[str, str] | None,
    *,
    frame_object_name: str = "",
    body_object_name: str = "",
) -> None:
    """Append a `make_warning_box()` frame to `layout` if `warning` is given.

    Shared by dialogs (e.g. ``DevicePickerDialog``, ``DeviceInfoDialog``)
    that let a caller fold a preceding standalone confirmation into this
    dialog by passing an optional ``(header, body_html)`` tuple, instead of
    each dialog repeating the same "if warning is not None: unpack, build,
    add" block inline.

    Args:
        layout: Layout to append the warning box to (no-op if `warning`
            is None).
        warning: Optional (header, body_html) pair, or None to skip.
        frame_object_name: Optional Qt object name for the warning frame.
        body_object_name: Optional Qt object name for the warning body label.
    """
    if warning is None:
        return
    header_text, body_text = warning
    layout.addWidget(
        make_warning_box(
            header_text,
            body_text,
            frame_object_name=frame_object_name,
            body_object_name=body_object_name,
        )
    )
