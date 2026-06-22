"""GUI design constants: colors, typography, spacing, and sizing.

Defines the visual design tokens used by theme.py and QSS stylesheets.
Values follow Fluent Design principles (Microsoft's design language for Windows 11)
with WiiM brand teal as the accent color.

Both light and dark mode color sets are provided. The active set is selected
by ThemeManager at runtime based on user preference or OS detection.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Color Palette
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ColorScheme:
    """Color set for a single theme mode (light or dark)."""

    # Accent
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_subtle: str

    # Semantic
    success: str
    error: str
    warning: str

    # Surfaces
    background: str
    surface: str
    surface_hover: str
    card: str

    # Text
    text_primary: str
    text_secondary: str
    text_disabled: str
    text_on_accent: str

    # Borders
    border: str
    border_subtle: str

    # Status banner backgrounds
    banner_info: str
    banner_success: str
    banner_error: str
    banner_warning: str


COLORS_LIGHT = ColorScheme(
    # Accent - WiiM brand teal
    accent="#00B4D8",
    accent_hover="#0096B7",
    accent_pressed="#007A96",
    accent_subtle="#E6F8FC",
    # Semantic
    success="#2E7D32",
    error="#C62828",
    warning="#F57C00",
    # Surfaces
    background="#F5F5F5",
    surface="#FFFFFF",
    surface_hover="#F0F0F0",
    card="#FFFFFF",
    # Text
    text_primary="#1A1A1A",
    text_secondary="#616161",
    text_disabled="#9E9E9E",
    text_on_accent="#FFFFFF",
    # Borders
    border="#E0E0E0",
    border_subtle="#EEEEEE",
    # Status banner backgrounds
    banner_info="#F5F5F5",
    banner_success="#E8F5E9",
    banner_error="#FFEBEE",
    banner_warning="#FFF3E0",
)

COLORS_DARK = ColorScheme(
    # Accent - WiiM brand teal (slightly brighter for dark mode)
    accent="#00B4D8",
    accent_hover="#33C5E1",
    accent_pressed="#66D6EA",
    accent_subtle="#1A2E33",
    # Semantic
    success="#66BB6A",
    error="#EF5350",
    warning="#FFA726",
    # Surfaces
    background="#1E1E1E",
    surface="#2D2D2D",
    surface_hover="#3A3A3A",
    card="#2D2D2D",
    # Text
    text_primary="#F5F5F5",
    text_secondary="#B0B0B0",
    text_disabled="#6E6E6E",
    text_on_accent="#FFFFFF",
    # Borders
    border="#404040",
    border_subtle="#333333",
    # Status banner backgrounds
    banner_info="#2D2D2D",
    banner_success="#1B3A1B",
    banner_error="#3A1B1B",
    banner_warning="#3A2E1B",
)

# Convenience aliases matching the design doc top-level names
ACCENT_COLOR: str = "#00B4D8"
"""WiiM brand teal - primary accent throughout the UI."""

ACCENT_HOVER: str = "#0096B7"
"""Darker accent for hover states."""

SUCCESS_COLOR: str = "#2E7D32"
"""Green for success banners and checkmarks."""

ERROR_COLOR: str = "#C62828"
"""Red for error banners and critical states."""

WARNING_COLOR: str = "#F57C00"
"""Orange for warnings and clamping indicators."""

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

MAX_CONTENT_WIDTH: int = 1200
"""Maximum content area width in pixels (prevents overly stretched layouts)."""

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
