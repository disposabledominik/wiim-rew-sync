"""Shared WiiM LV2 PEQ/RoomFit command encoding, used by WiiMAdapter and CapabilityProber.

Both classes independently build ``{"pluginURI": ..., "source_name": ..., "EQLevel": ...}``
payloads and URL-encode them into ``httpapi.asp`` command strings. This module is the single
place that shape lives, so a real-device correction (e.g. dropping ``source_name`` from RoomFit
payloads) only needs to happen once.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from src.models.errors import WiiMResponseError

# LV2 plugin URI used by all WiiM PEQ/RoomFit commands.
PLUGIN_URI = "http://moddevices.com/plugins/caps/EqNp"

# RoomFit (EQLevel:2) commands, split by which source_name shape each requires
# -- both sets are exhaustive transcriptions of docs/wiim_api_notes.md's
# "source_name & EQLevel Reference" table, and every eq_level=2 call in this
# codebase must appear in exactly one of them (enforced below). Band-buffer/
# DSP-toggle commands need source_name="" (present, empty) -- omitting it was
# the actual root cause of a past RoomFit-detection regression (docs/
# corrections.md, 2026-07-04). Profile CRUD commands need source_name omitted
# entirely. Neither set may be inferred from the other: this is a closed,
# doc-driven classification, not an allowlist with an "anything else is fine"
# fallback -- a new RoomFit command that isn't added to either set raises
# immediately instead of silently defaulting to the wrong shape, which is
# exactly how the omission mistake above went undetected.
_ROOMFIT_REQUIRES_EMPTY_SOURCE_NAME = frozenset({
    "EQGetLV2SourceBandEx",
    "EQSetLV2SourceBand",
    "EQChangeSourceFX",
    "EQSourceOff",
})
_ROOMFIT_REQUIRES_OMITTED_SOURCE_NAME = frozenset({
    "EQv2SourceLoad",
    "EQv2Delete",
    "EQv2GetNewList",
    "EQSourceSave",
})


def encode_wiim_command(
    command: str,
    extra: dict[str, Any] | None = None,
    *,
    source_name: str | None = None,
    eq_level: int | None = None,
) -> str:
    """Build a full '<Command>:<url-encoded JSON>' string for the shared
    pluginURI(+source_name)(+EQLevel) payload shape used by nearly every
    WiiM LV2 PEQ/RoomFit command.

    source_name is included only when explicitly given. For RoomFit
    (eq_level=2): band read/write and the DSP on/off toggle require source_name=""
    (present, empty -- confirmed against real hardware); profile CRUD commands
    (EQv2SourceLoad/EQv2Delete/EQv2GetNewList/EQSourceSave) omit it entirely.
    See docs/wiim_api_notes.md's "source_name & EQLevel Reference". eq_level is
    included only when given (omission defaults to PEQ/EQLevel:1 on the device).

    Raises:
        ValueError: source_name containing a comma -- a multi-value string is
            never a valid WiiM source; the device silently stores a permanent
            junk slot for it (docs/smoke_test_issues.md #194). Split the
            selection and issue one command per source instead.
        ValueError: eq_level=2 (RoomFit) with a real (non-empty) source_name --
            the device silently accepts this but targets an orphaned per-source
            slot instead of the real RoomFit buffer. Also raised the other way:
            a band-buffer/DSP-toggle command (see
            _ROOMFIT_REQUIRES_EMPTY_SOURCE_NAME) with source_name omitted --
            that's the actual mistake that caused a past regression, not the
            real-value case. Also raised for any eq_level=2 command not
            classified into either _ROOMFIT_REQUIRES_EMPTY_SOURCE_NAME or
            _ROOMFIT_REQUIRES_OMITTED_SOURCE_NAME -- a new RoomFit command must
            be classified there first, per docs/wiim_api_notes.md's "source_name
            & EQLevel Reference", rather than silently defaulting to whichever
            shape happens to not raise. There is no legitimate RoomFit call
            shape any of these three branches would reject.
    """
    if source_name is not None and "," in source_name:
        raise ValueError(
            f"source_name must be a single source, got the multi-value string "
            f"{source_name!r} for {command!r}. The device silently stores a "
            f"permanent junk slot for any string it receives (docs/"
            f"wiim_api_notes.md \"Key rules\"; docs/smoke_test_issues.md #194) "
            f"-- split the selection and issue one command per source."
        )
    if eq_level == 2 and source_name:
        raise ValueError(
            f"RoomFit (EQLevel:2) commands must omit source_name or pass \"\", "
            f"never a real value -- got {source_name!r} for {command!r}. See "
            f"docs/wiim_api_notes.md's source_name & EQLevel Reference."
        )
    if eq_level == 2 and source_name is None:
        if command in _ROOMFIT_REQUIRES_EMPTY_SOURCE_NAME:
            raise ValueError(
                f"RoomFit (EQLevel:2) {command!r} requires source_name=\"\" "
                f"(present, empty) -- omitting it entirely fails against real "
                f"hardware and was the root cause of a past RoomFit-detection "
                f"regression. See docs/wiim_api_notes.md's source_name & "
                f"EQLevel Reference."
            )
        if command not in _ROOMFIT_REQUIRES_OMITTED_SOURCE_NAME:
            raise ValueError(
                f"RoomFit (EQLevel:2) command {command!r} is not classified in "
                f"either _ROOMFIT_REQUIRES_EMPTY_SOURCE_NAME or "
                f"_ROOMFIT_REQUIRES_OMITTED_SOURCE_NAME (wiim_commands.py) -- "
                f"add it to whichever one matches docs/wiim_api_notes.md's "
                f"source_name & EQLevel Reference before using it."
            )
    if eq_level == 2 and source_name == "" and command in _ROOMFIT_REQUIRES_OMITTED_SOURCE_NAME:
        raise ValueError(
            f"RoomFit (EQLevel:2) {command!r} requires source_name to be "
            f"omitted entirely, not passed as \"\" -- got source_name='' for "
            f"{command!r}. See docs/wiim_api_notes.md's source_name & EQLevel "
            f"Reference."
        )
    payload: dict[str, Any] = {"pluginURI": PLUGIN_URI}
    if source_name is not None:
        payload["source_name"] = source_name
    if eq_level is not None:
        payload["EQLevel"] = eq_level
    if extra:
        payload.update(extra)
    return f"{command}:{quote(json.dumps(payload))}"


def expect_dict_response(response: object, context: str) -> dict[str, Any]:
    """Raise WiiMResponseError with a consistent message if response isn't a dict."""
    if not isinstance(response, dict):
        raise WiiMResponseError(
            f"Expected JSON dict from {context}, got: {type(response).__name__}"
        )
    return response


def expect_list_response(response: object, context: str) -> list[Any]:
    """Raise WiiMResponseError with a consistent message if response isn't a list."""
    if not isinstance(response, list):
        raise WiiMResponseError(
            f"Expected a JSON list from {context}, got: {type(response).__name__}"
        )
    return response
