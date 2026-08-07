"""Shared page chrome for wizard pages and sidebar views.

Every wizard step page and every sidebar-navigable view (Presets on Device,
My Saved Presets, Settings, etc.) builds its title and
content column through this module instead of hand-rolling its own
QVBoxLayout/QLabel boilerplate. Before this existed, pages had drifted to
four different title font sizes and some had no title at all — going
through one shared builder is what keeps that from happening again.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

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

    Uses a stretch-widget-stretch "sandwich" (not
    outer_layout.setAlignment(...)) to center the column: a blanket
    alignment call on a widget's own top-level layout sizes its single
    child (`content`) to sizeHint() instead of stretching it, so on any
    page whose content doesn't happen to contain a wide/Expanding-policy
    child, `content` collapses to the width of its narrowest content and
    visibly drifts off to one side instead of spanning the column (smoke
    #179 -- PushPage was the first page compact enough on every child to
    expose this; it was always latent here). The stretch sandwich avoids
    depending on children's sizeHint entirely: `content` has an Expanding
    horizontal size policy, so it always fills up to MAX_CONTENT_WIDTH, and
    the two stretches only absorb genuine leftover space beyond that cap.
    """
    outer_layout = QVBoxLayout(page)
    outer_layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)
    outer_layout.setSpacing(0)

    content = QWidget(page)
    content.setMaximumWidth(MAX_CONTENT_WIDTH)
    content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(SPACING_LG)

    # Side spacers use the default (0) stretch factor and `content` uses 1
    # -- Qt then grows `content` first (up to its maximumWidth cap) before
    # giving any surplus to the spacers, which is what actually centers it
    # once it hits the cap. Giving all three equal/no stretch factors (the
    # more "obvious" version of this idiom) instead lets the spacers win the
    # surplus and squeezes `content` down to its children's bare sizeHint.
    centering_row = QHBoxLayout()
    centering_row.setContentsMargins(0, 0, 0, 0)
    centering_row.addStretch()
    centering_row.addWidget(content, 1)
    centering_row.addStretch()
    outer_layout.addLayout(centering_row)

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


def center_column(layout: QVBoxLayout) -> None:
    """Vertically center *layout*'s children via stretches, not layout alignment.

    Do not call layout.setAlignment(...) on a layout that contains a
    word-wrapped QLabel -- it switches Qt to size that child via sizeHint()
    computed at an unbounded width, which under-reports the height needed
    once the label is actually wrapped at its real (narrower) width, silently
    clipping the text (smoke #180). Call this instead, after all children
    have been added. Center non-wrapping children individually via
    addWidget(w, alignment=Qt.AlignmentFlag.AlignHCenter); add word-wrapped
    labels with a plain addWidget(label) call, relying on the label's own
    setAlignment(AlignCenter) for text centering within its full-width box.
    """
    layout.insertStretch(0, 1)
    layout.addStretch(1)


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
