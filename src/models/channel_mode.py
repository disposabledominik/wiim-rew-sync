"""ChannelMode enum — canonical representation of stereo vs L/R channel mode.

Eliminates string-based channel mode comparisons throughout the codebase.
All conversions between wire format, profile format, and display format
are centralised in this enum's properties.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BeforeValidator

from src.models.canonical import CanonicalFilter


class ChannelMode(Enum):
    """Canonical channel mode for PEQ settings.

    Two possible states:
    - STEREO: single shared filter set for both channels.
    - LR: independent left and right channel filter sets.
    """

    STEREO = "stereo"
    LR = "lr"

    @property
    def wire_value(self) -> str:
        """Value sent to/received from the WiiM API."""
        return "Stereo" if self == ChannelMode.STEREO else "L/R"

    @property
    def profile_value(self) -> str:
        """Value stored in Profile JSON (legacy format compatibility).

        Stereo profiles use "stereo"; L/R profiles use "left" as the sentinel
        indicating dual-channel data is present.
        """
        return "stereo" if self == ChannelMode.STEREO else "left"

    @property
    def display_value(self) -> str:
        """Human-readable value for UI display."""
        return "Stereo" if self == ChannelMode.STEREO else "L/R"

    @property
    def is_lr(self) -> bool:
        """Return True if this is dual-channel (L/R) mode."""
        return self == ChannelMode.LR

    @classmethod
    def from_wire(cls, value: str) -> ChannelMode:
        """Parse a WiiM API channelMode value.

        Accepts: "Stereo", "L/R".
        """
        if value == "L/R":
            return cls.LR
        return cls.STEREO

    @classmethod
    def from_profile(cls, value: str) -> ChannelMode:
        """Parse a Profile JSON channel_mode value.

        Accepts: "stereo", "left", "right".
        "left" and "right" are legacy sentinels meaning L/R data is present.
        """
        if value in ("left", "right"):
            return cls.LR
        return cls.STEREO

    @classmethod
    def from_any(cls, value: str) -> ChannelMode:
        """Parse any known channel mode string variant.

        Handles all legacy formats: "stereo", "Stereo", "lr", "l/r", "L/R",
        "left", "right", "LR".
        """
        normalised = value.strip().lower()
        if normalised in ("lr", "l/r", "left", "right"):
            return cls.LR
        return cls.STEREO


def coerce_channel_mode(value: str | ChannelMode) -> ChannelMode:
    """Coerce str or ChannelMode -> ChannelMode.

    Used both as a Pydantic BeforeValidator for model fields (below) and by
    is_lr_mode() -- the single place this str-or-ChannelMode coercion is
    implemented, so the two callers can't drift apart.
    """
    if isinstance(value, ChannelMode):
        return value
    return ChannelMode.from_any(value)


# Annotated type for use in Pydantic model fields.
# Accepts str or ChannelMode at runtime and coerces to ChannelMode.
ChannelModeField = Annotated[ChannelMode, BeforeValidator(coerce_channel_mode)]


def is_lr_mode(channel_mode: str | ChannelMode) -> bool:
    """Check if a channel mode represents L/R (dual-channel) mode.

    Accepts both ChannelMode enum values and legacy string variants.
    Handles all variants: "lr", "l/r", "L/R", "left", "right", ChannelMode.LR.
    """
    return coerce_channel_mode(channel_mode).is_lr


def require_lr_filters(
    filters_l: list[CanonicalFilter] | None,
    filters_r: list[CanonicalFilter] | None,
) -> tuple[list[CanonicalFilter], list[CanonicalFilter]]:
    """Require explicit per-channel filter lists; never guess a split.

    Shared by PEQSettings/Profile construction from a combined filter list
    plus channel mode (see build_peq_settings/build_profile).

    Raises:
        ValueError: if either filters_l or filters_r is missing. There is
            no safe way to reconstruct a channel boundary from a combined
            list -- a positional 50/50 split is correct only by coincidence
            when both channels happen to have equal length, and silently
            wrong otherwise.
    """
    if filters_l is None or filters_r is None:
        raise ValueError("L/R filters missing; refusing to guess channel split")
    return filters_l, filters_r


def get_lr_filters(state: object) -> tuple[list[CanonicalFilter], list[CanonicalFilter]]:
    """Get L/R filter lists from wizard state.

    Requires explicit state.filters_l/filters_r (set during validation) --
    never guesses a channel split.

    Args:
        state: WizardState object with filters_l/filters_r fields.

    Returns:
        Tuple of (left_filters, right_filters).

    Raises:
        ValueError: if state has no filters_l/filters_r set.
    """
    left = getattr(state, "filters_l", None)
    right = getattr(state, "filters_r", None)
    return require_lr_filters(left, right)
