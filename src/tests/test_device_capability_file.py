"""Unit tests for the device capability file loader and merge logic."""

from __future__ import annotations

import json
from pathlib import Path

from src.models.capabilities import DeviceCapabilities
from src.models.device_capability_file import (
    CapabilityFileEntry,
    find_entry,
    load_capability_file,
    merge_into,
)


def _write_file(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


class TestLoadCapabilityFile:
    """Loading and validating the device capability file."""

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """A non-existent path returns an empty entry map, not an error."""
        entries = load_capability_file(tmp_path / "does_not_exist.json")
        assert entries == {}

    def test_loads_valid_entries(self, tmp_path: Path) -> None:
        """Valid models load into CapabilityFileEntry objects."""
        path = tmp_path / "device_capabilities.json"
        _write_file(
            path,
            {
                "models": {
                    "WiiM_Pro": {
                        "supports_roomfit": True,
                        "max_bands": 10,
                    }
                }
            },
        )
        entries = load_capability_file(path)
        assert "WiiM_Pro" in entries
        assert entries["WiiM_Pro"].supports_roomfit is True
        assert entries["WiiM_Pro"].max_bands == 10

    def test_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        """Unparseable JSON is logged and skipped, never raises."""
        path = tmp_path / "device_capabilities.json"
        path.write_text("{not valid json", encoding="utf-8")
        entries = load_capability_file(path)
        assert entries == {}

    def test_missing_models_key_returns_empty(self, tmp_path: Path) -> None:
        """A file without a top-level 'models' object yields no entries."""
        path = tmp_path / "device_capabilities.json"
        _write_file(path, {"unrelated": "data"})
        entries = load_capability_file(path)
        assert entries == {}

    def test_malformed_entry_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        """One malformed model entry is skipped; valid siblings still load."""
        path = tmp_path / "device_capabilities.json"
        _write_file(
            path,
            {
                "models": {
                    "Broken_Model": {"max_bands": "not-a-number"},
                    "WiiM_Pro": {"max_bands": 10},
                }
            },
        )
        entries = load_capability_file(path)
        assert "Broken_Model" not in entries
        assert "WiiM_Pro" in entries


class TestFindEntry:
    """Matching a probed model string against capability-file entries."""

    def setup_method(self) -> None:
        self.entries = {
            "WiiM_Mini": CapabilityFileEntry(aliases=["Muzo_Mini"]),
        }

    def test_exact_key_match(self) -> None:
        assert find_entry("WiiM_Mini", self.entries) is not None

    def test_alias_match(self) -> None:
        assert find_entry("Muzo_Mini", self.entries) is not None

    def test_case_insensitive(self) -> None:
        assert find_entry("wiim_mini", self.entries) is not None

    def test_space_underscore_insensitive(self) -> None:
        assert find_entry("WiiM Mini", self.entries) is not None

    def test_no_match_returns_none(self) -> None:
        assert find_entry("WiiM_Ultra", self.entries) is None

    def test_empty_model_returns_none(self) -> None:
        assert find_entry("", self.entries) is None


class TestMergeInto:
    """Applying capability-file overrides onto probed DeviceCapabilities."""

    def test_no_entry_keeps_probed_values_except_band_cap(self) -> None:
        """With no matching entry, only the 10-band default cap applies."""
        caps = DeviceCapabilities(
            supports_peq=True, supports_roomfit=True, max_filters=12
        )
        result = merge_into(caps, None)
        assert result.supports_roomfit is True
        assert result.max_filters == 10

    def test_entry_overrides_listed_fields(self) -> None:
        """Fields present on the entry override the probed values."""
        caps = DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            supports_lr_filters=False,
            max_filters=10,
        )
        entry = CapabilityFileEntry(
            supports_roomfit=False,
            supports_lr_filters=True,
            supported_filter_types=["PEAK", "LP"],
            sources=["wifi", "optical"],
        )
        result = merge_into(caps, entry)
        assert result.supports_roomfit is False
        assert result.supports_lr_filters is True
        assert result.supported_filter_types == ["PEAK", "LP"]
        assert result.source_names == ["wifi", "optical"]

    def test_max_bands_is_a_ceiling_not_an_override(self) -> None:
        """max_bands never raises max_filters above what was actually probed."""
        caps = DeviceCapabilities(supports_peq=True, max_filters=8)
        entry = CapabilityFileEntry(max_bands=12)
        result = merge_into(caps, entry)
        assert result.max_filters == 8

    def test_max_bands_lowers_probed_count(self) -> None:
        """max_bands can lower the probed count below the 10-band default."""
        caps = DeviceCapabilities(supports_peq=True, max_filters=10)
        entry = CapabilityFileEntry(max_bands=4)
        result = merge_into(caps, entry)
        assert result.max_filters == 4

    def test_max_bands_allows_full_probed_count_above_default(self) -> None:
        """max_bands>=probed lets a 12-band device keep all 12 (Amp Ultra case)."""
        caps = DeviceCapabilities(supports_peq=True, max_filters=12)
        entry = CapabilityFileEntry(max_bands=12)
        result = merge_into(caps, entry)
        assert result.max_filters == 12

    def test_unsupported_peq_skips_band_cap(self) -> None:
        """Devices without PEQ support are left at max_filters=0."""
        caps = DeviceCapabilities(supports_peq=False, max_filters=0)
        result = merge_into(caps, None)
        assert result.max_filters == 0
