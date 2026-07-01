"""PEQ settings model for WiiM device communication."""

from __future__ import annotations

from pydantic import BaseModel, model_validator

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

    @model_validator(mode="after")
    def check_band_keys_match_channel_mode(self) -> PEQSettings:
        """Enforce channel-mode/band-key consistency.

        Mirrors Profile.check_filter_keys_match_channel_mode -- stereo mode
        must not carry per-channel bands, and L/R mode must not carry the
        shared `bands` list, so a caller can't silently end up with both
        (or neither) populated.
        """
        if self.channel_mode == ChannelMode.STEREO:
            if self.bands_l or self.bands_r:
                raise ValueError("Stereo PEQSettings must not have 'bands_l'/'bands_r'")
        else:  # ChannelMode.LR
            if self.bands:
                raise ValueError("L/R PEQSettings must not have 'bands'")
        return self
