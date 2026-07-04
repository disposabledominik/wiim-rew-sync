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

    source_name is included only when explicitly given -- RoomFit's
    per-buffer commands omit it entirely (confirmed against the WiiM app);
    its two device-global toggle commands pass "" explicitly, a distinct,
    deliberate case from omitting the key altogether. eq_level is included
    only when given (omission defaults to PEQ/EQLevel:1 on the device).
    """
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
