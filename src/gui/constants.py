"""GUI design constants: colors, typography, spacing, and sizing.

Defines the visual design tokens used by QSS stylesheets (see
src/gui/assets/styles/fluent_dark.qss and fluent_light.qss) and by the small
number of widgets that need a color value at runtime (e.g. dynamically built
rich-text strings) rather than via QSS class/property selectors.

Theme color *palettes* live exclusively in the QSS files now — there is no
Python-side ColorScheme/COLORS_LIGHT/COLORS_DARK mirror to keep in sync. Only
add a color constant here if it is genuinely needed outside of QSS.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Color Palette
# ---------------------------------------------------------------------------

# Convenience aliases matching the design doc top-level names.
# Only ACCENT_COLOR and WARNING_COLOR_* remain — they're used for runtime
# QColor() calculations (table cell foreground, search highlight) that
# QSS classes can't express. Color choices for everything else live in
# fluent_dark.qss / fluent_light.qss.
ACCENT_COLOR: str = "#00B4D8"
"""WiiM brand teal - primary accent throughout the UI (same in both themes)."""

WARNING_COLOR_LIGHT: str = "#F57C00"
"""Orange for warnings and clamping indicators (light theme).

Matches the ``warning`` value documented in fluent_light.qss's header.
"""

WARNING_COLOR_DARK: str = "#FFA726"
"""Orange for warnings and clamping indicators (dark theme).

Matches the ``warning`` value documented in fluent_dark.qss's header.
Use :func:`src.gui.theme.get_active_theme` to pick between the two at
runtime rather than hardcoding one.
"""

# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------

FONT_SIZE_CAPTION: int = 12
"""Caption and secondary label size in pixels."""

# ---------------------------------------------------------------------------
# Spacing
# ---------------------------------------------------------------------------

SPACING_XS: int = 4
"""Extra-small spacing in pixels (tight element gaps)."""

SPACING_SM: int = 8
"""Small spacing in pixels (within components)."""

SPACING_MD: int = 16
"""Medium spacing in pixels (between components)."""

SPACING_LG: int = 24
"""Large spacing in pixels (between sections)."""

SPACING_XL: int = 32
"""Extra-large spacing in pixels (major section breaks)."""

# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------

MAX_CONTENT_WIDTH: int = 760
"""Maximum content area width in pixels (prevents overly stretched layouts).

Most pages are single-column forms/lists that looked sparse and over-spread
at the old 1200px cap; 760 comfortably fits that content without feeling
cramped, and is close enough to what's actually available at the app's
default 1000x700 window size (minus sidebar/margins) that the app's visual
width stays consistent whether or not the user resizes.
"""

SIDEBAR_EXPANDED: int = 200
"""Sidebar width in pixels when fully expanded (icons + labels)."""

SIDEBAR_COLLAPSED: int = 48
"""Sidebar width in pixels when collapsed (icons only)."""

MIN_WINDOW_WIDTH: int = 900
"""Minimum application window width in pixels.

Empirically validated (offscreen Qt measurement, accounting for the
SIDEBAR_EXPANDED width the step indicator's content column loses) to keep
the longest stepper label ("Name Profile", RoomFit flow) from eliding: it
starts eliding below ~870px, so 900px leaves a small margin for font-metric
variance across platforms.
"""

MIN_WINDOW_HEIGHT: int = 600
"""Minimum application window height in pixels."""

LIST_ITEM_HEIGHT: int = 44
"""Minimum list item height in pixels (comfortable click/touch target)."""

LIST_ITEM_SPACING: int = 2
"""Gap in pixels between rows in every selectable list (QListWidget.setSpacing()).

Small enough to read as one continuous list, but enough that adjoining
multi-selected rows' highlight rects stay visually distinct from each other
rather than fusing into one solid block. Applied uniformly by
:func:`src.gui.components.list_item_style.style_selectable_list` so every
list in the app carries the same gap."""

STEP_INDICATOR_HEIGHT: int = 56
"""Step indicator bar height in pixels."""

STATUS_BANNER_HEIGHT: int = 44
"""Status banner height in pixels."""

# ---------------------------------------------------------------------------
# Filter Table Column Widths
# ---------------------------------------------------------------------------

FILTER_TABLE_MAX_WIDTH: int = 760
"""Maximum filter table width in pixels (matches MAX_CONTENT_WIDTH so the
table fills the full content column)."""

# ---------------------------------------------------------------------------
# Animation Timing (milliseconds)
# ---------------------------------------------------------------------------

ANIMATION_NORMAL: int = 250
"""Normal transitions (expand, collapse)."""

AUTO_DISMISS_MS: int = 5000
"""Auto-dismiss delay for success status banners."""
