"""PEQ settings model for WiiM device communication."""

from typing import Literal

from pydantic import BaseModel

from src.models.canonical import CanonicalFilter


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
