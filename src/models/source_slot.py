"""Source-slot diagnostic model for the EQGetSourceModes overview."""

from __future__ import annotations

from pydantic import BaseModel


class SourceSlotInfo(BaseModel):
    """One row of a device's live per-source PEQ buffer, as reported by
    ``EQGetSourceModes`` (docs/wiim_api_notes.md, "Source Discovery").

    ``is_known_source`` is False for slots whose ``source_name`` does not
    match one of the device's real inputs (``DeviceCapabilities.source_names``)
    -- typically garbage left behind by a comma-joined or otherwise invalid
    write (docs/smoke_test_issues.md #194). These rows are permanent: no
    known command removes a slot once written (docs/corrections.md,
    2026-07-10), so this model is read-only diagnostic data, never a
    candidate for a delete operation.
    """

    source_name: str
    name: str = ""
    enabled: bool = False
    channel_mode: str = ""
    is_known_source: bool = True
