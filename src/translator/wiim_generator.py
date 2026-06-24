"""Canonical filter list → WiiM EQBand flat parameter array generator.

Converts a list of CanonicalFilter objects into the 40-entry flat parameter
list expected by the WiiM LV2 PEQ API (EQSetLV2Band / EQSetLV2SourceBand).

Output format: [mode_1, freq_1, gain_1, q_1, mode_2, freq_2, gain_2, q_2, ..., mode_10, ...]

Mode mapping (Canonical → WiiM LV2):
    "OFF"  → -1
    "PEAK" → 1
    "LS"   → 0
    "HS"   → 2

Clamping rules (logs WARNING per clip):
    gain: clamped to [-12.0, +12.0]
    Q:    clamped to [0.01, 24.0]
"""

from __future__ import annotations

import logging

from src.models.canonical import CanonicalFilter, FilterType
from src.models.constants import GAIN_MAX, GAIN_MIN, Q_MAX, Q_MIN
from src.translator._warnings import ValidationWarning

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

# Total number of bands the WiiM API expects
_MAX_BANDS: int = 10


def generate_wiim_band_array(
    filters: list[CanonicalFilter],
    max_bands: int = 10,
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
        if gain > _GAIN_MAX:
            logger.warning(
                "Band %d: gain %.2f dB exceeds +12 dB limit, clamping to +12.0 dB",
                i + 1,
                gain,
            )
            warnings.append(
                ValidationWarning(
                    field=f"band_{i + 1}_gain",
                    message=f"Band {i + 1}: gain {gain:.2f} dB clamped to +12.0 dB",
                    original_value=gain,
                    clamped_value=_GAIN_MAX,
                )
            )
            gain = _GAIN_MAX
        elif gain < _GAIN_MIN:
            logger.warning(
                "Band %d: gain %.2f dB exceeds -12 dB limit, clamping to -12.0 dB",
                i + 1,
                gain,
            )
            warnings.append(
                ValidationWarning(
                    field=f"band_{i + 1}_gain",
                    message=f"Band {i + 1}: gain {gain:.2f} dB clamped to -12.0 dB",
                    original_value=gain,
                    clamped_value=_GAIN_MIN,
                )
            )
            gain = _GAIN_MIN

        # Clamp Q
        if q > _Q_MAX:
            logger.warning(
                "Band %d: Q %.4f exceeds 24.0 limit, clamping to 24.0",
                i + 1,
                q,
            )
            warnings.append(
                ValidationWarning(
                    field=f"band_{i + 1}_q",
                    message=f"Band {i + 1}: Q {q:.4f} clamped to 24.0",
                    original_value=q,
                    clamped_value=_Q_MAX,
                )
            )
            q = _Q_MAX
        elif q < _Q_MIN:
            logger.warning(
                "Band %d: Q %.4f below 0.01 limit, clamping to 0.01",
                i + 1,
                q,
            )
            warnings.append(
                ValidationWarning(
                    field=f"band_{i + 1}_q",
                    message=f"Band {i + 1}: Q {q:.4f} clamped to 0.01",
                    original_value=q,
                    clamped_value=_Q_MIN,
                )
            )
            q = _Q_MIN

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
