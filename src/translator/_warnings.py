"""Shared warning dataclass for the translator package (breaks circular imports)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.models.canonical import CanonicalFilter


@dataclass
class ValidationWarning:
    """Warning emitted when a value is clamped during translation."""

    field: str
    message: str
    original_value: Any
    clamped_value: Any | None = None


@dataclass
class SkippedBand:
    """A band with no usable WiiM translation, or excluded for exceeding the band limit.

    Rendered as a disabled, unnumbered ("N/A") row in the Review table rather than
    being silently omitted, so the user can see what didn't make it across and why.
    Frequency/gain/Q are populated when the original values are known (e.g. a band
    truncated for exceeding the device's band limit); left None when the source
    filter type itself has no WiiM translation (e.g. Notch, Modal, All-pass).
    """

    original_type: str
    reason: str
    frequency_hz: float | None = None
    gain_db: float | None = None
    q: float | None = None


# A single display row: either a usable filter or a placeholder for a skipped one.
# Order is preserved structurally by list position -- no separate index bookkeeping.
FilterRow = CanonicalFilter | SkippedBand
