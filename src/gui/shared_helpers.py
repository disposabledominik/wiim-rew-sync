"""Shared helper functions for GUI layer operations.

Eliminates duplication across main_window.py and secondary_workflows.py
for channel-mode handling, filter splitting, PEQSettings construction,
and Profile building.
"""

from __future__ import annotations

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
