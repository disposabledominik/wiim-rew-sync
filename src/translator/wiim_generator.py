"""Canonical filter list → WiiM EQBand flat parameter array generator.

Converts a list of CanonicalFilter objects into the 40-entry flat parameter
list expected by the WiiM LV2 PEQ API (EQSetLV2Band / EQSetLV2SourceBand).

Output format: [mode_1, freq_1, gain_1, q_1, mode_2, freq_2, gain_2, q_2, ..., mode_10, ...]

Mode mapping (Canonical → WiiM LV2):
    "OFF"  → -1
    "PEAK" → 1
    "LS"   → 0
    "HS"   → 2
    "LP"   → 3
    "HP"   → 5

Clamping rules (logs WARNING per clip):
    gain: clamped to [-12.0, +12.0]
    Q:    clamped to [0.01, 24.0]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.models.canonical import CanonicalFilter, FilterType
from src.models.channel_mode import ChannelMode, is_lr_mode
from src.models.constants import DEFAULT_MAX_BANDS, GAIN_MAX, GAIN_MIN, Q_MAX, Q_MIN
from src.translator._warnings import FilterRow, SkippedBand, ValidationWarning
from src.utils.clamping import clamp, clamp_with_warning

logger = logging.getLogger("wiim_rew_sync.app")

# Canonical type -> WiiM LV2 mode integer
_TYPE_TO_MODE: dict[FilterType, int] = {
    "OFF": -1,
    "PEAK": 1,
    "LS": 0,
    "HS": 2,
    "LP": 3,
    "HP": 5,
}

# Private aliases for module-internal use (shorter names in clamping logic)
_GAIN_MIN = GAIN_MIN
_GAIN_MAX = GAIN_MAX
_Q_MIN = Q_MIN
_Q_MAX = Q_MAX

# Default OFF band values
_OFF_FREQ: float = 1000.0
_OFF_GAIN: float = 0.0
_OFF_Q: float = 1.0

# Number of decimal places the WiiM API likes for filter values.
_WIIM_VALUE_PRECISION: int = 3


def generate_wiim_band_array(
    filters: list[CanonicalFilter],
    max_bands: int = DEFAULT_MAX_BANDS,
) -> tuple[list[float], list[ValidationWarning]]:
    """Convert a list of CanonicalFilters to a WiiM flat parameter array.

    Parameters
    ----------
    filters:
        List of CanonicalFilter objects. If fewer than max_bands, remaining
        bands are padded as OFF. If more than max_bands, truncated with a
        logged WARNING.
    max_bands:
        Number of bands the device supports (default 10 for backward compat).

    Returns
    -------
    tuple[list[float], list[ValidationWarning]]
        A tuple of (max_bands*4-entry flat parameter list, list of validation
        warnings for any clamping that occurred).
    """
    warnings: list[ValidationWarning] = []

    # Truncate if more filters than device supports
    if len(filters) > max_bands:
        logger.warning(
            "Received %d filters; truncating to %d bands", len(filters), max_bands
        )
        warnings.append(
            ValidationWarning(
                field="filters",
                message=f"Received {len(filters)} filters; truncated to {max_bands} bands",
                original_value=len(filters),
                clamped_value=max_bands,
            )
        )
        filters = filters[:max_bands]

    result: list[float] = []

    for i, f in enumerate(filters):
        if f.type == "UNKNOWN":
            if f.raw_mode is not None:
                mode = float(f.raw_mode)
            else:
                mode = float(_TYPE_TO_MODE["OFF"])
                logger.warning(
                    "Band %d: UNKNOWN filter with no raw_mode, falling back to OFF",
                    i + 1,
                )
        else:
            mode = float(_TYPE_TO_MODE[f.type])
        freq = f.frequency_hz
        gain = f.gain_db
        q = f.q

        # Clamp gain
        clamped_gain, gain_reason = clamp_with_warning(
            gain, _GAIN_MIN, _GAIN_MAX, "gain", unit=" dB", signed=True
        )
        if gain_reason is not None:
            logger.warning("Band %d: %s", i + 1, gain_reason)
            warnings.append(
                ValidationWarning(
                    field=f"band_{i + 1}_gain",
                    message=f"Band {i + 1}: {gain_reason}",
                    original_value=gain,
                    clamped_value=clamped_gain,
                )
            )
        gain = clamped_gain

        # Clamp Q
        clamped_q, q_reason = clamp_with_warning(q, _Q_MIN, _Q_MAX, "Q")
        if q_reason is not None:
            logger.warning("Band %d: %s", i + 1, q_reason)
            warnings.append(
                ValidationWarning(
                    field=f"band_{i + 1}_q",
                    message=f"Band {i + 1}: {q_reason}",
                    original_value=q,
                    clamped_value=clamped_q,
                )
            )
        q = clamped_q

        result.extend(
            [
                mode,
                round(freq, _WIIM_VALUE_PRECISION),
                round(gain, _WIIM_VALUE_PRECISION),
                round(q, _WIIM_VALUE_PRECISION),
            ]
        )

    # Pad remaining bands as OFF
    bands_to_pad = max_bands - len(filters)
    for _ in range(bands_to_pad):
        result.extend([float(_TYPE_TO_MODE["OFF"]), _OFF_FREQ, _OFF_GAIN, _OFF_Q])

    return result, warnings


def clamp_filters_for_verification(
    filters: list[CanonicalFilter], max_bands: int = DEFAULT_MAX_BANDS
) -> list[CanonicalFilter]:
    """Return filters truncated/clamped exactly as generate_wiim_band_array()
    will write them to the device, for use as the write-verification baseline.

    SafeWrite compares its "intended" bands against what the device reads
    back -- but generate_wiim_band_array() clamps out-of-range gain/Q at
    write time without mutating the caller's CanonicalFilter list. Comparing
    the *pre*-clamp intended values against the device's (necessarily
    post-clamp) read-back guarantees a false-positive mismatch -- and
    therefore a spurious rollback -- on every band that needed clamping.
    Does not log: generate_wiim_band_array() already logs each clamp/
    truncation when it actually performs the write.
    """
    truncated = filters[:max_bands]
    clamped: list[CanonicalFilter] = []
    for f in truncated:
        gain = clamp(f.gain_db, _GAIN_MIN, _GAIN_MAX)
        q = clamp(f.q, _Q_MIN, _Q_MAX)
        if gain != f.gain_db or q != f.q:
            clamped.append(f.model_copy(update={"gain_db": gain, "q": q}))
        else:
            clamped.append(f)
    return clamped


# ---------------------------------------------------------------------------
# Import validation -- truncation and clamping detection
# ---------------------------------------------------------------------------

_DEVICE_FILTER_TYPES = {"PEAK", "LS", "HS", "LP", "HP"}


def find_unsupported_filter_types(
    filters: list[CanonicalFilter],
    supported_filter_types: list[str] | None,
) -> set[str]:
    """Return the device-unsupported filter types present in `filters`.

    Shared by validate_filters_for_device (import-time warning/skip) and
    the copy-to-device write path (secondary_workflows.py), which needs the
    same "would this type work on this device" check as a fail-fast
    pre-write gate rather than a skip-and-warn one -- a device that
    silently mis-stores an unsupported LP/HP mode value could pass a naive
    write+read-back verification without ever applying the intended
    filter, so copy-to-device must refuse instead of guessing.

    Args:
        filters: Filters to check.
        supported_filter_types: Device's supported canonical filter types
            (DeviceCapabilities.supported_filter_types). Empty/None means
            "no restriction" (matches validate_filters_for_device).

    Returns:
        Set of unsupported filter-type strings found (empty if none, or if
        supported_filter_types is empty/None).
    """
    if not supported_filter_types:
        return set()
    allowed = set(supported_filter_types)
    return {
        f.type for f in filters
        if f.type in _DEVICE_FILTER_TYPES and f.type not in allowed
    }


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
    by generate_wiim_band_array() at write time.

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
    # boundary logic generate_wiim_band_array() applies at write time, so
    # this pre-write detection can't drift from what actually gets clamped.
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


@dataclass
class ReviewValidationResult:
    """Result of resolve_review_validation() -- what a caller needs to
    populate a filter-review UI and update its own channel/filter state.

    Only one of the two field groups is populated per call, mirroring
    resolve_channel_split()'s own "empty when not applicable" contract
    (models/channel_mode.py) rather than a tagged union -- not a new
    pattern, just consistent with the sibling function this one is modeled
    on: stereo mode leaves filters_l/filters_r/clamping_l/clamping_r/
    rows_l/rows_r at their empty defaults; L/R mode leaves clamping_map/
    rows at theirs. current_filters is always populated (the combined,
    authoritative list) regardless of mode.
    """

    warnings: list[str]
    resolved_channel_mode: ChannelMode
    current_filters: list[CanonicalFilter]
    clamping_map: dict[int, list[str]] = field(default_factory=dict)
    rows: list[FilterRow] = field(default_factory=list)
    filters_l: list[CanonicalFilter] = field(default_factory=list)
    filters_r: list[CanonicalFilter] = field(default_factory=list)
    clamping_l: dict[int, list[str]] = field(default_factory=dict)
    clamping_r: dict[int, list[str]] = field(default_factory=dict)
    rows_l: list[FilterRow] = field(default_factory=list)
    rows_r: list[FilterRow] = field(default_factory=list)


def resolve_review_validation(
    peq_data: object,
    channel_mode: ChannelMode,
    current_filters: list[CanonicalFilter],
    pending_rows: list[FilterRow],
    pending_rows_l: list[FilterRow],
    pending_rows_r: list[FilterRow],
    max_filters: int,
    supported_filter_types: list[str] | None,
) -> ReviewValidationResult | None:
    """Validate filters against device limits ahead of populating a review UI.

    Branches on channel mode (smoke #28): explicit L/R bands supplied by
    peq_data, wizard-state L/R without explicit bands (a guard against an
    invariant break, see below), or stereo.

    Args:
        peq_data: PEQ settings object or filter list from the operation --
            duck-typed via getattr(), since callers may pass either a
            PEQSettings-like object (channel_mode/bands_l/bands_r
            attributes) or a plain filter list.
        channel_mode: The caller's current channel mode (e.g. wizard state),
            used only when peq_data doesn't carry explicit L/R bands.
        current_filters: Combined filter list to validate in the stereo case.
        pending_rows/pending_rows_l/pending_rows_r: Prior-attempt display
            rows to preserve skip placeholders from, or an empty list if
            none are pending -- converted to validate_filters_for_device()'s
            own None-means-"use filters" convention internally.
        max_filters: Device's maximum supported bands.
        supported_filter_types: Device's supported canonical filter types,
            or None for no restriction.

    Returns:
        None if the L/R-without-explicit-bands guard fired -- every producer
        of this data in L/R mode is expected to always supply explicit
        bands_l/bands_r; reaching this case means that invariant broke, so
        this refuses to guess a channel split instead of silently showing
        wrong-channel data (same class of bug as smoke #92/#93). Already
        logged when this happens; the caller only needs to surface an error
        to the user and stop.

        Otherwise, a ReviewValidationResult with the resolved channel mode
        and validated filters.
    """
    peq_channel = getattr(peq_data, "channel_mode", None)
    bands_l = getattr(peq_data, "bands_l", None)
    bands_r = getattr(peq_data, "bands_r", None)

    if (
        peq_channel is not None
        and is_lr_mode(peq_channel)
        and bands_l is not None
        and bands_r is not None
    ):
        validated_l, warnings_l, clamping_l, rows_l = validate_filters_for_device(
            list(bands_l), max_filters, pending_rows_l or None, supported_filter_types,
        )
        validated_r, warnings_r, clamping_r, rows_r = validate_filters_for_device(
            list(bands_r), max_filters, pending_rows_r or None, supported_filter_types,
        )
        all_warnings = [f"Left: {w}" for w in warnings_l] + [
            f"Right: {w}" for w in warnings_r
        ]
        return ReviewValidationResult(
            warnings=all_warnings,
            resolved_channel_mode=ChannelMode.LR,
            current_filters=validated_l + validated_r,
            filters_l=validated_l,
            filters_r=validated_r,
            clamping_l=clamping_l,
            clamping_r=clamping_r,
            rows_l=rows_l,
            rows_r=rows_r,
        )

    if channel_mode.is_lr:
        # Every producer of this data in L/R mode always supplies explicit
        # bands_l/bands_r -- reaching here means that invariant broke;
        # refuse to guess a channel split instead of silently showing
        # wrong-channel data (same class of bug as smoke #92/#93).
        logger.error(
            "L/R mode without explicit bands_l/bands_r — refusing "
            "to guess channel split"
        )
        return None

    validated, all_warnings, clamping_map, rows = validate_filters_for_device(
        current_filters, max_filters, pending_rows or None, supported_filter_types,
    )
    return ReviewValidationResult(
        warnings=all_warnings,
        resolved_channel_mode=channel_mode,
        current_filters=validated,
        clamping_map=clamping_map,
        rows=rows,
    )
