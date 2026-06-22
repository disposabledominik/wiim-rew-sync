"""PEQ settings model for WiiM device communication."""

from __future__ import annotations

from pydantic import BaseModel

from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode, ChannelModeField


class PEQSettings(BaseModel):
    """Full PEQ state for one source on a device.

    For stereo mode: ``bands`` holds the shared filter list.
    For L/R mode: ``bands_l`` and ``bands_r`` hold per-channel filters;
    ``bands`` is left empty.
    """

    source_name: str
    enabled: bool = True
    channel_mode: ChannelModeField = ChannelMode.STEREO
    name: str = ""
    bands: list[CanonicalFilter] = []
    bands_l: list[CanonicalFilter] = []
    bands_r: list[CanonicalFilter] = []
