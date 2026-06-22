"""Shared helper functions for GUI layer operations.

Eliminates duplication across main_window.py and secondary_workflows.py
for channel-mode handling, filter splitting, PEQSettings construction,
and Profile building.
"""

from __future__ import annotations

from typing import Any

from src.models.canonical import CanonicalFilter
from src.models.peq import PEQSettings
from src.models.profile import Profile


def extract_filters(peq_settings: PEQSettings) -> tuple[list[CanonicalFilter], str]:
    """Extract combined filter list and normalized channel_mode from PEQSettings.

    Returns:
        Tuple of (combined_filters, channel_mode) where channel_mode is
        "L/R" or "Stereo".
    """
    if peq_settings.channel_mode == "lr":
        filters = (peq_settings.bands_l or []) + (peq_settings.bands_r or [])
        return filters, "L/R"
    return list(peq_settings.bands), "Stereo"


def split_lr_filters(
    filters: list[CanonicalFilter],
) -> tuple[list[CanonicalFilter], list[CanonicalFilter]]:
    """Split a combined L+R filter list into (left, right) halves."""
    mid = len(filters) // 2
    return filters[:mid], filters[mid:]


def is_lr_mode(channel_mode: str) -> bool:
    """Check if a channel mode string represents L/R (dual-channel) mode.

    Handles all variants: "lr", "l/r", "L/R", "left", "right".
    """
    return channel_mode.lower() in ("lr", "l/r", "left", "right")


def build_peq_settings(
    source_name: str,
    filters: list[CanonicalFilter],
    channel_mode: str,
) -> PEQSettings:
    """Construct PEQSettings with correct channel splitting.

    For L/R mode: splits filters evenly into bands_l and bands_r.
    For stereo: uses the full list as bands.
    """
    if is_lr_mode(channel_mode):
        left, right = split_lr_filters(filters)
        return PEQSettings(
            source_name=source_name,
            channel_mode="lr",
            bands_l=left,
            bands_r=right,
        )
    return PEQSettings(
        source_name=source_name,
        channel_mode="stereo",
        bands=filters,
    )


def build_profile(
    name: str,
    filters: list[CanonicalFilter],
    channel_mode: str,
) -> Profile:
    """Sanitize name and construct Profile with correct channel mode.

    Removes filesystem-unsafe characters from name.
    For L/R mode: splits filters into filters_l/filters_r.
    For stereo: uses filters directly.
    """
    safe_name = name.translate(str.maketrans("", "", '/\\:*?"<>|'))
    if not safe_name:
        safe_name = "Untitled Preset"

    if is_lr_mode(channel_mode):
        left, right = split_lr_filters(filters)
        return Profile(
            name=safe_name,
            channel_mode="left",
            filters_l=left,
            filters_r=right,
        )
    return Profile(
        name=safe_name,
        channel_mode="stereo",
        filters=filters,
    )


def parse_backup_filters(backup_data: dict[str, Any]) -> tuple[list[CanonicalFilter], str]:
    """Parse a backup JSON dict into a filter list and channel_mode.

    Used by both PEQ undo (SecondaryWorkflowManager) and RoomFit undo
    (MainWindow) to avoid duplicating backup parsing logic.

    Args:
        backup_data: Parsed JSON dict from a backup file.

    Returns:
        Tuple of (filters, channel_mode) where channel_mode is "lr" or "stereo".
    """
    channel_mode_raw = backup_data.get("channel_mode", "stereo")

    if channel_mode_raw in ("left", "right"):
        filters_l_raw = backup_data.get("filters_l", [])
        filters_r_raw = backup_data.get("filters_r", [])
        filters = [CanonicalFilter(**f) for f in filters_l_raw] + [
            CanonicalFilter(**f) for f in filters_r_raw
        ]
        return filters, "lr"

    filters_raw = backup_data.get("filters", [])
    return [CanonicalFilter(**f) for f in filters_raw], "stereo"


# ---------------------------------------------------------------------------
# Import validation — truncation and clamping detection
# ---------------------------------------------------------------------------

# WiiM hardware limits
_GAIN_MIN: float = -12.0
_GAIN_MAX: float = 12.0
_Q_MIN: float = 0.01
_Q_MAX: float = 24.0


def validate_filters_for_device(
    filters: list[CanonicalFilter],
    max_filters: int = 10,
) -> tuple[list[CanonicalFilter], list[str], dict[int, list[str]]]:
    """Validate and prepare filters for a WiiM device.

    Checks for:
    - More filters than device supports (truncates to max_filters)
    - Gain values outside ±12 dB (flags for clamping)
    - Q values outside 0.01-24 (flags for clamping)

    Does NOT modify gain/Q values — only flags them. Actual clamping is done
    by the WiiM generator at write time.

    Args:
        filters: List of CanonicalFilter objects from import.
        max_filters: Device's maximum supported bands (default 10).

    Returns:
        Tuple of:
        - truncated_filters: filters capped to max_filters
        - warnings: list of human-readable warning strings for the UI
        - clamping_map: dict mapping band index (0-based) to list of
          clamping reasons (for ReviewPage orange indicators)
    """
    warnings: list[str] = []
    clamping_map: dict[int, list[str]] = {}

    # Truncation check
    if len(filters) > max_filters:
        warnings.append(
            f"Imported {len(filters)} filters but device supports {max_filters}. "
            f"Only the first {max_filters} will be used."
        )
        filters = filters[:max_filters]

    # Gain/Q clamping check (per band)
    for i, f in enumerate(filters):
        reasons: list[str] = []

        if f.gain_db > _GAIN_MAX:
            reasons.append(
                f"gain {f.gain_db:+.1f} dB will be clamped to +{_GAIN_MAX:.0f} dB"
            )
        elif f.gain_db < _GAIN_MIN:
            reasons.append(
                f"gain {f.gain_db:+.1f} dB will be clamped to {_GAIN_MIN:.0f} dB"
            )

        if f.q > _Q_MAX:
            reasons.append(f"Q {f.q:.2f} will be clamped to {_Q_MAX}")
        elif f.q < _Q_MIN:
            reasons.append(f"Q {f.q:.4f} will be clamped to {_Q_MIN}")

        if reasons:
            clamping_map[i] = reasons

    # Summarize clamping
    if clamping_map:
        n_clamped = len(clamping_map)
        warnings.append(
            f"{n_clamped} band(s) have values outside WiiM limits and will be clamped on push."
        )

    return filters, warnings, clamping_map
