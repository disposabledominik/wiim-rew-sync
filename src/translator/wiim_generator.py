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

from src.models.canonical import CanonicalFilter, FilterType
from src.models.constants import DEFAULT_MAX_BANDS, GAIN_MAX, GAIN_MIN, Q_MAX, Q_MIN
from src.translator._warnings import ValidationWarning
from src.utils.clamping import clamp_with_warning

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
        gain = min(max(f.gain_db, _GAIN_MIN), _GAIN_MAX)
        q = min(max(f.q, _Q_MIN), _Q_MAX)
        if gain != f.gain_db or q != f.q:
            clamped.append(f.model_copy(update={"gain_db": gain, "q": q}))
        else:
            clamped.append(f)
    return clamped
