"""Profile and backup record models with channel-mode validation."""

from typing import Literal

from pydantic import BaseModel, model_validator

from src.models.canonical import CanonicalFilter


class Profile(BaseModel):
    """A named, locally-stored JSON snapshot of a PEQ filter set."""

    schema_version: int = 1
    name: str
    channel_mode: Literal["stereo", "left", "right"]
    filters: list[CanonicalFilter] | None = None
    filters_l: list[CanonicalFilter] | None = None
    filters_r: list[CanonicalFilter] | None = None
    tags: list[str] = []

    @model_validator(mode="after")
    def check_filter_keys_match_channel_mode(self) -> "Profile":
        """Enforce channel-mode/filter-key consistency.

        Stereo mode: only `filters` must be set.
        Left/Right mode: only `filters_l` and `filters_r` must be set.
        """
        if self.channel_mode == "stereo":
            if self.filters is None:
                raise ValueError("Stereo profile must have 'filters' key")
            if self.filters_l is not None or self.filters_r is not None:
                raise ValueError("Stereo profile must not have 'filters_l'/'filters_r'")
        else:  # "left" or "right"
            if self.filters_l is None or self.filters_r is None:
                raise ValueError("L/R profile must have 'filters_l' and 'filters_r'")
            if self.filters is not None:
                raise ValueError("L/R profile must not have 'filters' key")
        return self


class BackupRecord(Profile):
    """Automatically-created JSON snapshot taken before any write operation."""

    timestamp: str  # ISO 8601
    device_uuid: str
    firmware_version: str
    trigger: Literal["pre_write", "pre_rollback"]
    profile_type: Literal["backup"] = "backup"
