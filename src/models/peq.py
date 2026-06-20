"""PEQ band and settings models for WiiM device communication."""

from typing import Literal

from pydantic import BaseModel, field_validator

from src.models.canonical import CanonicalFilter


class PEQBand(BaseModel):
    """WiiM-level representation of a single EQ band."""

    band_number: int  # 1-12 (10 on older firmware, 12 on Amp Ultra)
    letter: str  # "a"-"l"
    mode: int  # -1, 0, 1, 2, 3, 5
    frequency: float  # 10-22000
    q: float  # 0.01-24
    gain: float  # -12 to +12

    @field_validator("band_number")
    @classmethod
    def band_number_in_range(cls, v: int) -> int:
        """Band number must be between 1 and 12."""
        if not (1 <= v <= 12):
            raise ValueError(f"band_number must be 1-12, got {v}")
        return v


class PEQSettings(BaseModel):
    """Full PEQ state for one source on a device.

    For stereo mode: ``bands`` holds the shared filter list.
    For L/R mode: ``bands_l`` and ``bands_r`` hold per-channel filters;
    ``bands`` is left empty.

    NOTE: ``channel_mode`` here uses "stereo"/"lr" (device state).
    ``Profile.channel_mode`` uses "stereo"/"left"/"right" (saved snapshot).
    Conversion between the two happens in the profile repository layer.
    """

    source_name: str
    enabled: bool = True
    channel_mode: Literal["stereo", "lr"]
    name: str = ""
    bands: list[CanonicalFilter] = []
    bands_l: list[CanonicalFilter] = []
    bands_r: list[CanonicalFilter] = []
