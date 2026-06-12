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

# Hardware limits
_GAIN_MIN: float = -12.0
_GAIN_MAX: float = 12.0
_Q_MIN: float = 0.01
_Q_MAX: float = 24.0

# Default OFF band values
_OFF_FREQ: float = 1000.0
_OFF_GAIN: float = 0.0
_OFF_Q: float = 1.0

# Total number of bands the WiiM API expects
_MAX_BANDS: int = 10


def generate_wiim_band_array(
    filters: list[CanonicalFilter],
) -> tuple[list[float], list[ValidationWarning]]:
    """Convert a list of CanonicalFilters to a WiiM 40-entry flat parameter array.

    Parameters
    ----------
    filters:
        List of 1-10 CanonicalFilter objects. If fewer than 10, remaining
        bands are padded as OFF. If more than 10, truncated to 10 with a
        logged WARNING.

    Returns
    -------
    tuple[list[float], list[ValidationWarning]]
        A tuple of (40-entry flat parameter list, list of validation warnings
        for any clamping that occurred).
    """
    warnings: list[ValidationWarning] = []

    # Truncate if more than 10 filters
    if len(filters) > _MAX_BANDS:
        logger.warning(
            "Received %d filters; truncating to %d bands", len(filters), _MAX_BANDS
        )
        warnings.append(
            ValidationWarning(
                field="filters",
                message=f"Received {len(filters)} filters; truncated to {_MAX_BANDS} bands",
                original_value=len(filters),
                clamped_value=_MAX_BANDS,
            )
        )
        filters = filters[:_MAX_BANDS]

    result: list[float] = []

    for i, f in enumerate(filters):
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

        result.extend([mode, freq, gain, q])

    # Pad remaining bands as OFF
    bands_to_pad = _MAX_BANDS - len(filters)
    for _ in range(bands_to_pad):
        result.extend([float(_TYPE_TO_MODE["OFF"]), _OFF_FREQ, _OFF_GAIN, _OFF_Q])

    return result, warnings
