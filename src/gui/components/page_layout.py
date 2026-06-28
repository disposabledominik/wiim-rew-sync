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

#: Icon for empty/placeholder states where a required connection is missing
#: (no device connected, REW API unreachable) — kept identical across views
#: so the user learns one visual language for "go connect something".
ICON_NO_CONNECTION = "\U0001F50C"  # power plug

#: Icon for empty states where the connection itself is fine but there is
#: simply nothing to act on yet (e.g. REW is running but no measurements
#: are loaded).
ICON_NO_DATA = "\U0001F3DC️"  # desert


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


def make_empty_state_icon(icon: str, object_name: str = "") -> QLabel:
    """Build a large, consistently-sized icon label for empty/placeholder states.

    All empty-state icons across the app (Presets on Device with no
    device, Pull from REW with no API/no measurements, etc.) share the
    "emptyStateIcon" QSS class so they render at the same size — previously
    only the Presets on Device icon was styled this way (via a one-off
    object-name rule), so other placeholder states had no icon at all.
    """
    label = QLabel(icon)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setProperty("class", "emptyStateIcon")
    if object_name:
        label.setObjectName(object_name)
    return label


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
