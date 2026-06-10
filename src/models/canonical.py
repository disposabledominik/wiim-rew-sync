"""Canonical Filter Model — the single normalised intermediate representation."""

from typing import Literal

from pydantic import BaseModel, field_validator

FilterType = Literal["PEAK", "LS", "HS", "OFF"]


class CanonicalFilter(BaseModel):
    """A single EQ band in canonical (normalised) form.

    All import and export operations convert to/from this model.
    """

    type: FilterType
    frequency_hz: float
    gain_db: float
    q: float

    @field_validator("frequency_hz")
    @classmethod
    def frequency_in_range(cls, v: float) -> float:
        """Frequency must be between 10 Hz and 22 kHz."""
        if not (10.0 <= v <= 22000.0):
            raise ValueError(f"frequency_hz {v} out of range 10-22000 Hz")
        return v

    @field_validator("q")
    @classmethod
    def q_must_be_positive(cls, v: float) -> float:
        """Q factor must be greater than zero."""
        if v <= 0:
            raise ValueError(f"q must be > 0, got {v}")
        return v
