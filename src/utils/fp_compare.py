"""Floating-point tolerance predicates for EQ band verification.

Used by the Safe Write Protocol to compare intended vs. read-back filter values.

A small relative epsilon (1e-9) is added to each tolerance to absorb unavoidable
IEEE 754 representation error (e.g. |1000.0 - 1000.1| slightly exceeds 0.1 in
binary64). This ensures that values which are nominally at the boundary are
correctly accepted.
"""

from __future__ import annotations

from src.models.canonical import CanonicalFilter

# ---------------------------------------------------------------------------
# Tolerance constants
# ---------------------------------------------------------------------------

FREQ_TOLERANCE_HZ: float = 0.1
"""Frequency must match within ±0.1 Hz."""

GAIN_TOLERANCE_DB: float = 0.05
"""Gain must match within ±0.05 dB."""

Q_TOLERANCE: float = 0.01
"""Q factor must match within ±0.01."""

_FP_EPS: float = 1e-9
"""Small epsilon to absorb IEEE 754 representation noise at boundaries."""


# ---------------------------------------------------------------------------
# Scalar predicates
# ---------------------------------------------------------------------------


def freq_matches(a: float, b: float) -> bool:
    """Return True if two frequency values are within FREQ_TOLERANCE_HZ."""
    return abs(a - b) <= FREQ_TOLERANCE_HZ + _FP_EPS


def gain_matches(a: float, b: float) -> bool:
    """Return True if two gain values are within GAIN_TOLERANCE_DB."""
    return abs(a - b) <= GAIN_TOLERANCE_DB + _FP_EPS


def q_matches(a: float, b: float) -> bool:
    """Return True if two Q factor values are within Q_TOLERANCE."""
    return abs(a - b) <= Q_TOLERANCE + _FP_EPS


# ---------------------------------------------------------------------------
# Band-level predicate
# ---------------------------------------------------------------------------


def band_matches(intended: CanonicalFilter, read_back: CanonicalFilter) -> bool:
    """Return True if an intended filter matches a read-back filter within tolerance.

    OFF bands require only a type match (frequency, gain, and Q are ignored).
    All other bands require type equality AND all three scalar predicates to pass.
    """
    if intended.type != read_back.type:
        return False
    if intended.type == "OFF":
        return True
    return (
        freq_matches(intended.frequency_hz, read_back.frequency_hz)
        and gain_matches(intended.gain_db, read_back.gain_db)
        and q_matches(intended.q, read_back.q)
    )
