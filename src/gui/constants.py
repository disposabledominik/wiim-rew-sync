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

import platform

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


def _detect_font_family() -> str:
    """Return platform-appropriate font family stack.

    Windows: Segoe UI Variable (Windows 11) with Segoe UI fallback.
    macOS: SF Pro with system-ui fallback.
    Linux: system-ui sans-serif.
    """
    system = platform.system()
    if system == "Windows":
        return "Segoe UI Variable, Segoe UI, sans-serif"
    if system == "Darwin":
        return "SF Pro, -apple-system, system-ui, sans-serif"
    # Linux and other platforms
    return "system-ui, Ubuntu, Cantarell, sans-serif"


FONT_FAMILY: str = _detect_font_family()
"""Platform-detected font family stack for QSS font-family property."""

FONT_SIZE_BODY: int = 14
"""Body text size in pixels (minimum per Req 10.4)."""

FONT_SIZE_HEADING: int = 20
"""Section heading size in pixels."""

FONT_SIZE_CAPTION: int = 12
"""Caption and secondary label size in pixels."""

FONT_SIZE_TITLE: int = 26
"""Page/view title size in pixels."""

FONT_WEIGHT_NORMAL: int = 400
"""Normal font weight."""

FONT_WEIGHT_SEMIBOLD: int = 600
"""Semibold font weight for emphasis."""

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
# Border Radii
# ---------------------------------------------------------------------------

CARD_RADIUS: int = 8
"""Card and panel corner radius in pixels."""

BUTTON_RADIUS: int = 6
"""Button corner radius in pixels."""

INPUT_RADIUS: int = 4
"""Input field corner radius in pixels."""

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

MIN_WINDOW_WIDTH: int = 800
"""Minimum application window width in pixels."""

MIN_WINDOW_HEIGHT: int = 600
"""Minimum application window height in pixels."""

LIST_ITEM_HEIGHT: int = 44
"""Minimum list item height in pixels (comfortable click/touch target)."""

STEP_INDICATOR_HEIGHT: int = 56
"""Step indicator bar height in pixels."""

STATUS_BANNER_HEIGHT: int = 44
"""Status banner height in pixels."""

# ---------------------------------------------------------------------------
# Filter Table Column Widths
# ---------------------------------------------------------------------------

FILTER_COL_BAND: int = 50
"""Band number column width in pixels."""

FILTER_COL_TYPE: int = 80
"""Filter type column width in pixels."""

FILTER_COL_FREQ: int = 120
"""Frequency column width in pixels."""

FILTER_COL_GAIN: int = 110
"""Gain (dB) column width in pixels."""

FILTER_COL_Q: int = 80
"""Q factor column width in pixels."""

FILTER_TABLE_MAX_WIDTH: int = 600
"""Maximum filter table width in pixels."""

# ---------------------------------------------------------------------------
# Animation Timing (milliseconds)
# ---------------------------------------------------------------------------

ANIMATION_FAST: int = 150
"""Fast transitions (hover, focus)."""

ANIMATION_NORMAL: int = 250
"""Normal transitions (expand, collapse)."""

ANIMATION_SLOW: int = 400
"""Slow transitions (page enter, overlay fade)."""

AUTO_DISMISS_MS: int = 5000
"""Auto-dismiss delay for success status banners."""

LONG_OPERATION_MS: int = 3000
"""Threshold for showing supplementary "This may take a moment..." message."""
