"""PEQ band and settings models for WiiM device communication."""

from typing import Literal

from pydantic import BaseModel, field_validator

from src.models.canonical import CanonicalFilter


class PEQBand(BaseModel):
    """WiiM-level representation of a single EQ band."""

    band_number: int  # 1-10
    letter: str  # "a"-"j"
    mode: int  # -1, 0, 1, 2
    frequency: float  # 10-22000
    q: float  # 0.01-24
    gain: float  # -12 to +12

    @field_validator("band_number")
    @classmethod
    def band_number_in_range(cls, v: int) -> int:
        """Band number must be between 1 and 10."""
        if not (1 <= v <= 10):
            raise ValueError(f"band_number must be 1-10, got {v}")
        return v


class PEQSettings(BaseModel):
    """Full PEQ state for one source on a device."""

    source_name: str
    enabled: bool = True
    channel_mode: Literal["stereo", "left", "right"]
    name: str = ""
    bands: list[CanonicalFilter] = []
