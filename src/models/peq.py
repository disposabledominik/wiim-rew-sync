"""PEQ settings model for WiiM device communication."""

from __future__ import annotations

from pydantic import BaseModel, model_validator

from src.models.canonical import CanonicalFilter
from src.models.channel_mode import (
    ChannelMode,
    ChannelModeField,
    coerce_channel_mode,
    is_lr_mode,
    require_lr_filters,
)


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


def extract_filters(peq_settings: PEQSettings) -> tuple[list[CanonicalFilter], ChannelMode]:
    """Extract combined filter list and channel_mode from PEQSettings.

    A plain function rather than a PEQSettings method deliberately: many
    call sites (and their tests) pass a duck-typed stand-in for PEQSettings
    with only channel_mode/bands/bands_l/bands_r set, and attribute access
    keeps working against those the same way a method call would not.

    Returns:
        Tuple of (combined_filters, channel_mode).
    """
    if is_lr_mode(peq_settings.channel_mode):
        filters = (peq_settings.bands_l or []) + (peq_settings.bands_r or [])
        return filters, ChannelMode.LR
    return list(peq_settings.bands), ChannelMode.STEREO


def build_peq_settings(
    source_name: str,
    filters: list[CanonicalFilter],
    channel_mode: str | ChannelMode,
    filters_l: list[CanonicalFilter] | None = None,
    filters_r: list[CanonicalFilter] | None = None,
) -> PEQSettings:
    """Construct PEQSettings with correct channel splitting.

    For L/R mode: requires explicit filters_l/filters_r (raises ValueError
    if missing -- never guesses a channel split).
    For stereo: uses the full list as bands.

    Raises:
        ValueError: L/R mode without explicit filters_l/filters_r.
    """
    mode = coerce_channel_mode(channel_mode)

    if mode.is_lr:
        left, right = require_lr_filters(filters_l, filters_r)
        return PEQSettings(
            source_name=source_name,
            channel_mode=ChannelMode.LR,
            bands_l=left,
            bands_r=right,
        )
    return PEQSettings(
        source_name=source_name,
        channel_mode=ChannelMode.STEREO,
        bands=filters,
    )
