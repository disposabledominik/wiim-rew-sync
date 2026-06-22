"""Shared helper functions for GUI layer operations.

Eliminates duplication across main_window.py and secondary_workflows.py
for channel-mode handling, filter splitting, PEQSettings construction,
and Profile building.
"""

from __future__ import annotations

from typing import Any

from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode
from src.models.constants import GAIN_MAX, GAIN_MIN, Q_MAX, Q_MIN
from src.models.peq import PEQSettings
from src.models.profile import Profile


def extract_filters(peq_settings: PEQSettings) -> tuple[list[CanonicalFilter], ChannelMode]:
    """Extract combined filter list and channel_mode from PEQSettings.

    Returns:
        Tuple of (combined_filters, channel_mode).
    """
    if is_lr_mode(peq_settings.channel_mode):
        filters = (peq_settings.bands_l or []) + (peq_settings.bands_r or [])
        return filters, ChannelMode.LR
    return list(peq_settings.bands), ChannelMode.STEREO


def split_lr_filters(
    filters: list[CanonicalFilter],
) -> tuple[list[CanonicalFilter], list[CanonicalFilter]]:
    """Split a combined L+R filter list into (left, right) halves.

    DEPRECATED: Only used as a last-resort fallback when no explicit L/R
    data is available. Prefer using state.filters_l/filters_r directly.
    """
    mid = len(filters) // 2
    return filters[:mid], filters[mid:]


def get_lr_filters(
    state: object,
    combined: list[CanonicalFilter],
) -> tuple[list[CanonicalFilter], list[CanonicalFilter]]:
    """Get L/R filter lists from wizard state, with fallback to naive split.

    Prefers explicit state.filters_l/filters_r (set during validation).
    Only falls back to 50/50 split when state doesn't have separate lists.

    Args:
        state: WizardState object with filters_l/filters_r fields.
        combined: The combined filter list for fallback splitting.

    Returns:
        Tuple of (left_filters, right_filters).
    """
    left = getattr(state, "filters_l", None) or []
    right = getattr(state, "filters_r", None) or []
    if left or right:
        return left, right
    # Last resort: naive split (only for legacy paths)
    return split_lr_filters(combined)


def is_lr_mode(channel_mode: str | ChannelMode) -> bool:
    """Check if a channel mode represents L/R (dual-channel) mode.

    Accepts both ChannelMode enum values and legacy string variants.
    Handles all variants: "lr", "l/r", "L/R", "left", "right", ChannelMode.LR.
    """
    if isinstance(channel_mode, ChannelMode):
        return channel_mode.is_lr
    return ChannelMode.from_any(channel_mode).is_lr


def build_peq_settings(
    source_name: str,
    filters: list[CanonicalFilter],
    channel_mode: str | ChannelMode,
    filters_l: list[CanonicalFilter] | None = None,
    filters_r: list[CanonicalFilter] | None = None,
) -> PEQSettings:
    """Construct PEQSettings with correct channel splitting.

    For L/R mode: uses explicit filters_l/filters_r if provided, otherwise
    splits combined list evenly (fallback for equal-length channels).
    For stereo: uses the full list as bands.
    """
    mode = (
        channel_mode
        if isinstance(channel_mode, ChannelMode)
        else ChannelMode.from_any(channel_mode)
    )

    if mode.is_lr:
        if filters_l is not None and filters_r is not None:
            left, right = filters_l, filters_r
        else:
            left, right = split_lr_filters(filters)
        return PEQSettings(
            source_name=source_name,
            channel_mode=ChannelMode.LR,
            bands_l=left,
            bands_r=right,
        )
    return PEQSettings(
        source_name=source_name,
        channel_mode=ChannelMode.STEREO,
        bands=filters,
    )


def build_profile(
    name: str,
    filters: list[CanonicalFilter],
    channel_mode: str | ChannelMode,
    filters_l: list[CanonicalFilter] | None = None,
    filters_r: list[CanonicalFilter] | None = None,
) -> Profile:
    """Sanitize name and construct Profile with correct channel mode.

    Removes filesystem-unsafe characters from name.
    For L/R mode: uses explicit filters_l/filters_r if provided, otherwise
    splits combined list (fallback for equal-length channels).
    For stereo: uses filters directly.
    """
    safe_name = name.translate(str.maketrans("", "", '/\\:*?"<>|'))
    if not safe_name:
        safe_name = "Untitled Preset"

    mode = (
        channel_mode
        if isinstance(channel_mode, ChannelMode)
        else ChannelMode.from_any(channel_mode)
    )

    if mode.is_lr:
        if filters_l is not None and filters_r is not None:
            left, right = filters_l, filters_r
        else:
            left, right = split_lr_filters(filters)
        return Profile(
            name=safe_name,
            channel_mode=ChannelMode.LR,
            filters_l=left,
            filters_r=right,
        )
    return Profile(
        name=safe_name,
        channel_mode=ChannelMode.STEREO,
        filters=filters,
    )


def parse_backup_filters(backup_data: dict[str, Any]) -> tuple[list[CanonicalFilter], ChannelMode]:
    """Parse a backup JSON dict into a filter list and channel_mode.

    Used by both PEQ undo (SecondaryWorkflowManager) and RoomFit undo
    (MainWindow) to avoid duplicating backup parsing logic.

    Args:
        backup_data: Parsed JSON dict from a backup file.

    Returns:
        Tuple of (filters, channel_mode).
    """
    channel_mode_raw = backup_data.get("channel_mode", "stereo")
    mode = ChannelMode.from_profile(str(channel_mode_raw))

    if mode.is_lr:
        filters_l_raw = backup_data.get("filters_l", [])
        filters_r_raw = backup_data.get("filters_r", [])
        filters = [CanonicalFilter(**f) for f in filters_l_raw] + [
            CanonicalFilter(**f) for f in filters_r_raw
        ]
        return filters, ChannelMode.LR

    filters_raw = backup_data.get("filters", [])
    return [CanonicalFilter(**f) for f in filters_raw], ChannelMode.STEREO


# ---------------------------------------------------------------------------
# Import validation — truncation and clamping detection
# ---------------------------------------------------------------------------

# Private aliases for module-internal use
_GAIN_MIN = GAIN_MIN
_GAIN_MAX = GAIN_MAX
_Q_MIN = Q_MIN
_Q_MAX = Q_MAX


def validate_filters_for_device(
    filters: list[CanonicalFilter],
    max_filters: int = 10,
) -> tuple[list[CanonicalFilter], list[str], dict[int, list[str]]]:
    """Validate and prepare filters for a WiiM device.

    Checks for:
    - More filters than device supports (truncates to max_filters)
    - Gain values outside +/-12 dB (flags for clamping)
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
