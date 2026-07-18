"""Profile and backup record models with channel-mode validation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, model_validator

from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode, ChannelModeField, resolve_channel_split


class Profile(BaseModel):
    """A named, locally-stored JSON snapshot of a PEQ filter set."""

    schema_version: int = 1
    name: str
    channel_mode: ChannelModeField = ChannelMode.STEREO
    filters: list[CanonicalFilter] | None = None
    filters_l: list[CanonicalFilter] | None = None
    filters_r: list[CanonicalFilter] | None = None
    tags: list[str] = []

    @model_validator(mode="after")
    def check_filter_keys_match_channel_mode(self) -> Profile:
        """Enforce channel-mode/filter-key consistency.

        Stereo mode: only `filters` must be set.
        L/R mode: only `filters_l` and `filters_r` must be set.
        """
        if self.channel_mode == ChannelMode.STEREO:
            if self.filters is None:
                raise ValueError("Stereo profile must have 'filters' key")
            if self.filters_l is not None or self.filters_r is not None:
                raise ValueError("Stereo profile must not have 'filters_l'/'filters_r'")
        else:  # ChannelMode.LR
            if self.filters_l is None or self.filters_r is None:
                raise ValueError("L/R profile must have 'filters_l' and 'filters_r'")
            if self.filters is not None:
                raise ValueError("L/R profile must not have 'filters' key")
        return self

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Override to serialize channel_mode as its profile_value string."""
        data = super().model_dump(**kwargs)
        cm = data.get("channel_mode")
        if isinstance(cm, ChannelMode):
            data["channel_mode"] = cm.profile_value
        return data

    def band_counts(self) -> tuple[int, int]:
        """Count active and total bands for this profile.

        A band is considered active if its gain is non-zero.

        For L/R profiles, returns per-channel counts (each channel
        separately, using the left channel as representative).

        Returns:
            Tuple of (active_band_count, total_band_count).
        """
        if self.channel_mode == ChannelMode.STEREO:
            filters = self.filters or []
        else:
            filters = self.filters_l or []

        total = len(filters)
        active = sum(1 for f in filters if f.gain_db != 0.0)
        return active, total


class BackupRecord(Profile):
    """Automatically-created JSON snapshot taken before any write operation."""

    timestamp: str  # ISO 8601
    device_uuid: str
    firmware_version: str
    trigger: Literal["pre_write", "pre_rollback"]
    profile_type: Literal["backup"] = "backup"

    # RoomFit-only restore metadata (Optional; None for PEQ backups and any
    # backup file created before this field's introduction -- old-format
    # files degrade gracefully rather than failing validation).
    pre_write_active_profile: str | None = None
    pre_write_roomfit_enabled: bool | None = None
    was_new_profile: bool | None = None

    # PEQ's independent analog of pre_write_roomfit_enabled -- kept separate
    # (not reused) since a backup record must unambiguously identify which
    # subsystem's enable-state it carries. None for RoomFit backups and any
    # backup file created before this field's introduction.
    pre_write_peq_enabled: bool | None = None


def build_profile(
    name: str,
    filters: list[CanonicalFilter],
    channel_mode: str | ChannelMode,
    filters_l: list[CanonicalFilter] | None = None,
    filters_r: list[CanonicalFilter] | None = None,
) -> Profile:
    """Sanitize name and construct Profile with correct channel mode.

    Removes filesystem-unsafe characters from name.
    For L/R mode: requires explicit filters_l/filters_r (raises ValueError
    if missing -- never guesses a channel split).
    For stereo: uses filters directly.

    Raises:
        ValueError: L/R mode without explicit filters_l/filters_r.
    """
    safe_name = name.translate(str.maketrans("", "", '/\\:*?"<>|'))
    if not safe_name:
        safe_name = "Untitled Preset"

    mode, left, right = resolve_channel_split(channel_mode, filters_l, filters_r)

    if mode.is_lr:
        return Profile(
            name=safe_name,
            channel_mode=ChannelMode.LR,
            filters_l=left,
            filters_r=right,
        )
    return Profile(
        name=safe_name,
        channel_mode=ChannelMode.STEREO,
        filters=filters,
    )
