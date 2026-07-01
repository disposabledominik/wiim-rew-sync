"""Shared helper functions for GUI layer operations.

Eliminates duplication across main_window.py and secondary_workflows.py
for channel-mode handling, filter splitting, PEQSettings construction,
and Profile building.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode
from src.models.constants import DEFAULT_MAX_BANDS, GAIN_MAX, GAIN_MIN, Q_MAX, Q_MIN
from src.models.peq import PEQSettings
from src.models.profile import Profile
from src.translator._warnings import FilterRow, SkippedBand
from src.utils.clamping import clamp_with_warning


def extract_filters(peq_settings: PEQSettings) -> tuple[list[CanonicalFilter], ChannelMode]:
    """Extract combined filter list and channel_mode from PEQSettings.

    Returns:
        Tuple of (combined_filters, channel_mode).
    """
    if is_lr_mode(peq_settings.channel_mode):
        filters = (peq_settings.bands_l or []) + (peq_settings.bands_r or [])
        return filters, ChannelMode.LR
    return list(peq_settings.bands), ChannelMode.STEREO


def _require_lr_filters(
    filters_l: list[CanonicalFilter] | None,
    filters_r: list[CanonicalFilter] | None,
) -> tuple[list[CanonicalFilter], list[CanonicalFilter]]:
    """Require explicit per-channel filter lists; never guess a split.

    Raises:
        ValueError: if either filters_l or filters_r is missing. There is
            no safe way to reconstruct a channel boundary from a combined
            list — a positional 50/50 split is correct only by coincidence
            when both channels happen to have equal length, and silently
            wrong otherwise.
    """
    if filters_l is None or filters_r is None:
        raise ValueError(
            "L/R filters missing; refusing to guess channel split"
        )
    return filters_l, filters_r


def get_lr_filters(
    state: object,
    combined: list[CanonicalFilter],
) -> tuple[list[CanonicalFilter], list[CanonicalFilter]]:
    """Get L/R filter lists from wizard state.

    Prefers explicit state.filters_l/filters_r (set during validation).

    Args:
        state: WizardState object with filters_l/filters_r fields.
        combined: Unused; retained for call-site compatibility.

    Returns:
        Tuple of (left_filters, right_filters).

    Raises:
        ValueError: if state has no filters_l/filters_r set.
    """
    del combined
    left = getattr(state, "filters_l", None)
    right = getattr(state, "filters_r", None)
    return _require_lr_filters(left, right)


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

    For L/R mode: requires explicit filters_l/filters_r (raises ValueError
    if missing — never guesses a channel split).
    For stereo: uses the full list as bands.

    Raises:
        ValueError: L/R mode without explicit filters_l/filters_r.
    """
    mode = (
        channel_mode
        if isinstance(channel_mode, ChannelMode)
        else ChannelMode.from_any(channel_mode)
    )

    if mode.is_lr:
        left, right = _require_lr_filters(filters_l, filters_r)
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
    For L/R mode: requires explicit filters_l/filters_r (raises ValueError
    if missing — never guesses a channel split).
    For stereo: uses filters directly.

    Raises:
        ValueError: L/R mode without explicit filters_l/filters_r.
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
        left, right = _require_lr_filters(filters_l, filters_r)
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


def load_backup_json(path: Path) -> dict[str, Any]:
    """Read and parse a backup JSON file.

    Used by both PEQ undo (SecondaryWorkflowManager) and RoomFit undo
    (MainWindow) to avoid duplicating the file-read + json.loads call.

    Raises:
        ValueError: if the file does not contain a JSON object.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Backup file {path} does not contain a JSON object")
    return data


def parse_backup_filters(
    backup_data: dict[str, Any],
) -> tuple[
    list[CanonicalFilter], ChannelMode, list[CanonicalFilter] | None, list[CanonicalFilter] | None
]:
    """Parse a backup JSON dict into filters, channel_mode, and per-channel lists.

    Used by both PEQ undo (SecondaryWorkflowManager) and RoomFit undo
    (MainWindow) to avoid duplicating backup parsing logic.

    Args:
        backup_data: Parsed JSON dict from a backup file.

    Returns:
        Tuple of (combined_filters, channel_mode, filters_l, filters_r).
        filters_l/filters_r are None for stereo backups. For L/R backups,
        callers must use filters_l/filters_r directly rather than
        re-splitting combined_filters (the combined list is positional
        concatenation and must not be treated as authoritative per-channel
        data).
    """
    channel_mode_raw = backup_data.get("channel_mode", "stereo")
    mode = ChannelMode.from_profile(str(channel_mode_raw))

    if mode.is_lr:
        filters_l_raw = backup_data.get("filters_l", [])
        filters_r_raw = backup_data.get("filters_r", [])
        filters_l = [CanonicalFilter(**f) for f in filters_l_raw]
        filters_r = [CanonicalFilter(**f) for f in filters_r_raw]
        filters = filters_l + filters_r
        return filters, ChannelMode.LR, filters_l, filters_r

    filters_raw = backup_data.get("filters", [])
    return [CanonicalFilter(**f) for f in filters_raw], ChannelMode.STEREO, None, None


# ---------------------------------------------------------------------------
# Import validation — truncation and clamping detection
# ---------------------------------------------------------------------------

# Private aliases for module-internal use
_GAIN_MIN = GAIN_MIN
_GAIN_MAX = GAIN_MAX
_Q_MIN = Q_MIN
_Q_MAX = Q_MAX


_DEVICE_FILTER_TYPES = {"PEAK", "LS", "HS", "LP", "HP"}


def validate_filters_for_device(
    filters: list[CanonicalFilter],
    max_filters: int = DEFAULT_MAX_BANDS,
    rows: list[FilterRow] | None = None,
    supported_filter_types: list[str] | None = None,
) -> tuple[list[CanonicalFilter], list[str], dict[int, list[str]], list[FilterRow]]:
    """Validate and prepare filters for a WiiM device.

    Checks for:
    - Filter types this device doesn't support (skips them; see
      supported_filter_types below)
    - More filters than device supports (truncates to max_filters)
    - Gain values outside +/-12 dB (flags for clamping)
    - Q values outside 0.01-24 (flags for clamping)

    Does NOT modify gain/Q values — only flags them. Actual clamping is done
    by the WiiM generator at write time.

    Args:
        filters: List of CanonicalFilter objects from import.
        max_filters: Device's maximum supported bands (default 10).
        rows: Optional display rows in original order (from REWParser's
            *_with_rows methods), used to mark truncated-away bands as
            disabled placeholders instead of dropping them silently. When
            omitted, defaults to `filters` itself (no prior skips to preserve).
        supported_filter_types: Device's supported canonical filter types
            (DeviceCapabilities.supported_filter_types, e.g. from the device
            capability file -- a WiiM Mini entry without "LP"/"HP" listed).
            Empty/None means "no restriction" (every device-probe path that
            doesn't set this stays exactly as before this check existed).

    Returns:
        Tuple of:
        - truncated_filters: filters capped to max_filters, with
          type-unsupported bands already removed
        - warnings: list of human-readable warning strings for the UI
        - clamping_map: dict mapping band index (0-based) to list of
          clamping reasons (for ReviewPage orange indicators)
        - rows: display rows with any skipped/truncated-away bands converted
          to SkippedBand placeholders, in original order
    """
    if rows is None:
        rows = list(filters)

    warnings: list[str] = []
    clamping_map: dict[int, list[str]] = {}

    # Device filter-type support check — runs before band-limit truncation
    # so an unsupported-type band doesn't consume a slot it could never use.
    # OFF/UNKNOWN aren't "filter types" needing device support, so they're
    # left alone regardless of what's listed.
    if supported_filter_types:
        allowed = set(supported_filter_types)
        unsupported_types: set[str] = set()
        type_filtered_rows: list[FilterRow] = []
        kept_filters: list[CanonicalFilter] = []
        for row in rows:
            if (
                isinstance(row, CanonicalFilter)
                and row.type in _DEVICE_FILTER_TYPES
                and row.type not in allowed
            ):
                unsupported_types.add(row.type)
                type_filtered_rows.append(
                    SkippedBand(
                        original_type=row.type,
                        reason=f"'{row.type}' filter type is not supported on this device",
                        frequency_hz=row.frequency_hz,
                        gain_db=row.gain_db,
                        q=row.q,
                    )
                )
            else:
                type_filtered_rows.append(row)
                if isinstance(row, CanonicalFilter):
                    kept_filters.append(row)
        rows = type_filtered_rows
        filters = kept_filters
        if unsupported_types:
            warnings.append(
                "Filter type(s) "
                + ", ".join(sorted(unsupported_types))
                + " are not supported on this device and were skipped."
            )

    # Truncation check
    if len(filters) > max_filters:
        excess_count = len(filters) - max_filters
        warnings.append(
            f"Imported {len(filters)} filters but device supports {max_filters}. "
            f"Only the first {max_filters} will be used."
        )
        filters = filters[:max_filters]

        # Mark the trailing excess CanonicalFilter rows as truncated
        # placeholders, preserving their original position among any
        # earlier skip placeholders already present.
        remaining = excess_count
        new_rows: list[FilterRow] = []
        for row in reversed(rows):
            if remaining > 0 and isinstance(row, CanonicalFilter):
                new_rows.append(
                    SkippedBand(
                        original_type=row.type,
                        reason=f"Exceeds device's {max_filters}-band limit",
                        frequency_hz=row.frequency_hz,
                        gain_db=row.gain_db,
                        q=row.q,
                    )
                )
                remaining -= 1
            else:
                new_rows.append(row)
        rows = list(reversed(new_rows))

    # Gain/Q clamping check (per band) -- uses the same clamp_with_warning()
    # boundary logic the WiiM generator applies at write time, so this
    # pre-write detection can't drift from what actually gets clamped.
    for i, f in enumerate(filters):
        reasons: list[str] = []

        _, gain_reason = clamp_with_warning(
            f.gain_db, _GAIN_MIN, _GAIN_MAX, "gain", unit=" dB", signed=True
        )
        if gain_reason is not None:
            reasons.append(gain_reason)

        _, q_reason = clamp_with_warning(f.q, _Q_MIN, _Q_MAX, "Q")
        if q_reason is not None:
            reasons.append(q_reason)

        if reasons:
            clamping_map[i] = reasons

    # Summarize clamping
    if clamping_map:
        n_clamped = len(clamping_map)
        warnings.append(
            f"{n_clamped} band(s) have values outside WiiM limits and will be clamped on push."
        )

    return filters, warnings, clamping_map, rows
