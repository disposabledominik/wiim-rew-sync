"""Unit tests for the shared wiim_commands encoding helpers.

encode_wiim_command/expect_dict_response back ~24 call sites across
wiim_adapter.py and capability_prober.py -- covered directly here since a
regression in either would otherwise only surface indirectly through those
much larger test suites.
"""

from __future__ import annotations

import json
from urllib.parse import unquote

import pytest

from src.adapters.wiim_commands import PLUGIN_URI, encode_wiim_command, expect_dict_response
from src.models.errors import WiiMResponseError


def _decode(command: str) -> tuple[str, dict[str, object]]:
    """Split '<Command>:<url-encoded JSON>' back into (command, payload dict)."""
    prefix, encoded = command.split(":", 1)
    return prefix, json.loads(unquote(encoded))


class TestEncodeWiimCommand:
    """encode_wiim_command's payload-shape rules."""

    def test_always_includes_plugin_uri(self) -> None:
        _, payload = _decode(encode_wiim_command("EQv2GetNewList"))
        assert payload["pluginURI"] == PLUGIN_URI

    def test_command_prefix(self) -> None:
        command = encode_wiim_command("EQv2GetNewList")
        assert command.startswith("EQv2GetNewList:")

    def test_source_name_omitted_by_default(self) -> None:
        _, payload = _decode(encode_wiim_command("EQGetLV2SourceBandEx"))
        assert "source_name" not in payload

    def test_source_name_empty_string_is_included_explicitly(self) -> None:
        """RoomFit's global status query passes source_name="" deliberately --
        a distinct case from omitting the key entirely."""
        _, payload = _decode(encode_wiim_command("EQGetLV2SourceBandEx", source_name=""))
        assert payload["source_name"] == ""

    def test_source_name_populated(self) -> None:
        _, payload = _decode(
            encode_wiim_command("EQGetLV2SourceBandEx", source_name="wifi")
        )
        assert payload["source_name"] == "wifi"

    def test_eq_level_omitted_by_default(self) -> None:
        _, payload = _decode(encode_wiim_command("EQGetLV2SourceBandEx"))
        assert "EQLevel" not in payload

    def test_eq_level_populated(self) -> None:
        _, payload = _decode(
            encode_wiim_command("EQGetLV2SourceBandEx", source_name="", eq_level=2)
        )
        assert payload["EQLevel"] == 2

    def test_extra_fields_merged(self) -> None:
        _, payload = _decode(
            encode_wiim_command("EQv2Delete", {"Name": "My Preset"}, eq_level=2)
        )
        assert payload["Name"] == "My Preset"
        assert payload["EQLevel"] == 2
        assert payload["pluginURI"] == PLUGIN_URI

    def test_no_extra_fields_still_valid(self) -> None:
        _, payload = _decode(encode_wiim_command("EQv2GetNewList", eq_level=1))
        assert payload == {"pluginURI": PLUGIN_URI, "EQLevel": 1}

    def test_roomfit_rejects_real_source_name(self) -> None:
        """A real source_name is never valid for any EQLevel:2 (RoomFit)
        command -- the device silently accepts it but targets an orphaned
        per-source slot instead of the real RoomFit buffer, which is exactly
        how a past regression slipped through undetected (docs/corrections.md,
        2026-07-04)."""
        with pytest.raises(ValueError, match="source_name"):
            encode_wiim_command("EQGetLV2SourceBandEx", source_name="wifi", eq_level=2)

    def test_roomfit_allows_empty_source_name(self) -> None:
        _, payload = _decode(
            encode_wiim_command("EQGetLV2SourceBandEx", source_name="", eq_level=2)
        )
        assert payload["source_name"] == ""

    def test_roomfit_allows_omitted_source_name(self) -> None:
        _, payload = _decode(encode_wiim_command("EQv2SourceLoad", eq_level=2))
        assert "source_name" not in payload

    def test_roomfit_band_command_rejects_omitted_source_name(self) -> None:
        """Omitting source_name for a RoomFit band/toggle command -- rather
        than passing "" -- is the actual mistake that caused a real
        regression (every device lost RoomFit detection, docs/corrections.md
        2026-07-04). The guard must reject this direction too, not just a
        real-value source_name, or a new call site could reintroduce it."""
        with pytest.raises(ValueError, match="source_name"):
            encode_wiim_command("EQGetLV2SourceBandEx", eq_level=2)
        with pytest.raises(ValueError, match="source_name"):
            encode_wiim_command("EQSetLV2SourceBand", eq_level=2)
        with pytest.raises(ValueError, match="source_name"):
            encode_wiim_command("EQChangeSourceFX", eq_level=2)
        with pytest.raises(ValueError, match="source_name"):
            encode_wiim_command("EQSourceOff", eq_level=2)

    def test_roomfit_unclassified_command_rejects_omitted_source_name(self) -> None:
        """A hypothetical new RoomFit (EQLevel:2) command that hasn't been
        classified into either _ROOMFIT_REQUIRES_EMPTY_SOURCE_NAME or
        _ROOMFIT_REQUIRES_OMITTED_SOURCE_NAME must raise loudly, not silently
        default to "omission is fine" -- that implicit fallback is exactly
        what let the original regression through undetected."""
        with pytest.raises(ValueError, match="not classified"):
            encode_wiim_command("SomeFutureRoomFitCommand", eq_level=2)

    def test_peq_still_allows_real_source_name(self) -> None:
        """The guard is RoomFit-specific (eq_level=2) -- PEQ (eq_level=1 or
        omitted) keeps allowing a real source_name."""
        _, payload = _decode(
            encode_wiim_command("EQGetLV2SourceBandEx", source_name="wifi", eq_level=1)
        )
        assert payload["source_name"] == "wifi"


class TestExpectDictResponse:
    """expect_dict_response's pass-through/raise behavior."""

    def test_dict_passes_through_unchanged(self) -> None:
        response = {"EQStat": "On"}
        assert expect_dict_response(response, "EQGetLV2SourceBandEx") is response

    def test_non_dict_raises_with_context(self) -> None:
        with pytest.raises(WiiMResponseError, match="EQGetLV2SourceBandEx"):
            expect_dict_response("unknown command", "EQGetLV2SourceBandEx")

    def test_non_dict_raises_with_type_name(self) -> None:
        with pytest.raises(WiiMResponseError, match="str"):
            expect_dict_response("unknown command", "EQv2GetNewList")
