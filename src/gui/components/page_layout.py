"""Shared page chrome for wizard pages and sidebar views.

Every wizard step page and every sidebar-navigable view (Presets on Device,
My Saved Presets, Pull from REW, Settings, etc.) builds its title and
content column through this module instead of hand-rolling its own
QVBoxLayout/QLabel boilerplate. Before this existed, pages had drifted to
four different title font sizes and some had no title at all — going
through one shared builder is what keeps that from happening again.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from src.gui.constants import MAX_CONTENT_WIDTH, SPACING_LG


def build_centered_content(page: QWidget) -> tuple[QVBoxLayout, QWidget]:
    """Set `page`'s layout to the standard centered, width-capped column.

    Returns the inner content layout (which the caller keeps adding widgets
    to) and the content wrapper widget itself.
    """
    outer_layout = QVBoxLayout(page)
    outer_layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)
    outer_layout.setSpacing(0)
    outer_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

    content = QWidget(page)
    content.setMaximumWidth(MAX_CONTENT_WIDTH)
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(SPACING_LG)
    outer_layout.addWidget(content)

    return content_layout, content


def make_page_title(
    text: str, parent: QWidget | None = None, object_name: str = ""
) -> QLabel:
    """Build a QLabel styled as the standard page/view title.

    Left-aligned (Qt's default) within the caller's centered content
    column — do not call setAlignment(AlignCenter) on the result. Forcing
    vertical centering on a title sharing a layout with a
    Fixed/Expanding-policy split below it is what previously caused title
    text to visually drift between a page's states (see RewPullView).
    """
    title = QLabel(text, parent)
    if object_name:
        title.setObjectName(object_name)
    title.setProperty("class", "sectionTitle")
    return title
