"""Unit tests for the device capability file loader and merge logic."""

from __future__ import annotations

import json
from pathlib import Path

from src.models.capabilities import DeviceCapabilities
from src.models.constants import DEFAULT_MAX_BANDS, DEFAULT_SOURCE_NAMES
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
        loaded = load_capability_file(tmp_path / "does_not_exist.json")
        assert loaded.entries == {}
        assert loaded.default_max_bands == DEFAULT_MAX_BANDS

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
        loaded = load_capability_file(path)
        assert "WiiM_Pro" in loaded.entries
        assert loaded.entries["WiiM_Pro"].supports_roomfit is True
        assert loaded.entries["WiiM_Pro"].max_bands == 10

    def test_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        """Unparseable JSON is logged and skipped, never raises."""
        path = tmp_path / "device_capabilities.json"
        path.write_text("{not valid json", encoding="utf-8")
        loaded = load_capability_file(path)
        assert loaded.entries == {}

    def test_missing_models_key_returns_empty(self, tmp_path: Path) -> None:
        """A file without a top-level 'models' object yields no entries."""
        path = tmp_path / "device_capabilities.json"
        _write_file(path, {"unrelated": "data"})
        loaded = load_capability_file(path)
        assert loaded.entries == {}

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
        loaded = load_capability_file(path)
        assert "Broken_Model" not in loaded.entries
        assert "WiiM_Pro" in loaded.entries

    def test_default_max_bands_absent_uses_built_in_default(self, tmp_path: Path) -> None:
        """No 'default_max_bands' key in the file -> the built-in constant."""
        path = tmp_path / "device_capabilities.json"
        _write_file(path, {"models": {}})
        loaded = load_capability_file(path)
        assert loaded.default_max_bands == DEFAULT_MAX_BANDS

    def test_default_max_bands_valid_value_is_used(self, tmp_path: Path) -> None:
        """A valid 'default_max_bands' key overrides the built-in constant."""
        path = tmp_path / "device_capabilities.json"
        _write_file(path, {"models": {}, "default_max_bands": 8})
        loaded = load_capability_file(path)
        assert loaded.default_max_bands == 8

    def test_default_max_bands_invalid_degrades_to_built_in(self, tmp_path: Path) -> None:
        """A non-int or non-positive 'default_max_bands' logs a warning and
        falls back to the built-in constant, never crashes."""
        path = tmp_path / "device_capabilities.json"
        _write_file(path, {"models": {}, "default_max_bands": "not-a-number"})
        loaded = load_capability_file(path)
        assert loaded.default_max_bands == DEFAULT_MAX_BANDS

        _write_file(path, {"models": {}, "default_max_bands": 0})
        loaded = load_capability_file(path)
        assert loaded.default_max_bands == DEFAULT_MAX_BANDS

        _write_file(path, {"models": {}, "default_max_bands": -5})
        loaded = load_capability_file(path)
        assert loaded.default_max_bands == DEFAULT_MAX_BANDS


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

    def test_empty_source_names_falls_back_to_default_list(self) -> None:
        """Empty source_names (e.g. WiiM Mini, no getAudioInputEnable and no
        capability-file `sources` override) gets DEFAULT_SOURCE_NAMES (#167b)."""
        caps = DeviceCapabilities(supports_peq=True, source_names=[])
        result = merge_into(caps, None)
        assert result.source_names == list(DEFAULT_SOURCE_NAMES)

    def test_nonempty_source_names_not_overridden_by_default(self) -> None:
        """A real probed source list is left alone -- the fallback only
        applies when source_names ends up empty."""
        caps = DeviceCapabilities(supports_peq=True, source_names=["wifi", "optical"])
        result = merge_into(caps, None)
        assert result.source_names == ["wifi", "optical"]

    def test_default_max_bands_parameter_caps_probed_count(self) -> None:
        """default_max_bands (from the capability file's "default_max_bands"
        key, #167c) replaces the built-in DEFAULT_MAX_BANDS when no per-model
        max_bands override exists."""
        caps = DeviceCapabilities(supports_peq=True, max_filters=10)
        result = merge_into(caps, None, default_max_bands=8)
        assert result.max_filters == 8

    def test_per_model_max_bands_wins_over_default_max_bands(self) -> None:
        """A per-model max_bands override is more specific and still wins
        over the file-wide default_max_bands."""
        caps = DeviceCapabilities(supports_peq=True, max_filters=12)
        entry = CapabilityFileEntry(max_bands=12)
        result = merge_into(caps, entry, default_max_bands=8)
        assert result.max_filters == 12

    def test_supports_roomfit_false_alone_cascades_downward(self) -> None:
        """supports_roomfit=False must clear read/write too (#161).

        The three booleans must stay internally consistent: a device whose
        subsystem is overridden away can't be readable or writable.
        """
        caps = DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            supports_roomfit_read=True,
            supports_roomfit_write=True,
        )
        entry = CapabilityFileEntry(supports_roomfit=False)
        result = merge_into(caps, entry)
        assert result.supports_roomfit is False
        assert result.supports_roomfit_read is False
        assert result.supports_roomfit_write is False

    def test_supports_roomfit_read_false_clears_write(self) -> None:
        """supports_roomfit_read=False cascades to write, keeps subsystem."""
        caps = DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            supports_roomfit_read=True,
            supports_roomfit_write=True,
        )
        entry = CapabilityFileEntry(supports_roomfit_read=False)
        result = merge_into(caps, entry)
        assert result.supports_roomfit is True
        assert result.supports_roomfit_read is False
        assert result.supports_roomfit_write is False

    def test_legacy_roomfit_level_maps_onto_booleans(self) -> None:
        """A user-edited capability file from before the 2026-07-10 redesign
        may still carry the legacy 0-4 roomfit_level -- it maps onto the
        three booleans (>=1 supported, >=2 read, >=4 write)."""
        caps = DeviceCapabilities(supports_peq=True)
        entry = CapabilityFileEntry(roomfit_level=2)
        result = merge_into(caps, entry)
        assert result.supports_roomfit is True
        assert result.supports_roomfit_read is True
        assert result.supports_roomfit_write is False

    def test_legacy_roomfit_level_zero_means_no_roomfit(self) -> None:
        caps = DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            supports_roomfit_read=True,
            supports_roomfit_write=True,
        )
        entry = CapabilityFileEntry(roomfit_level=0)
        result = merge_into(caps, entry)
        assert result.supports_roomfit is False
        assert result.supports_roomfit_read is False
        assert result.supports_roomfit_write is False

    def test_explicit_boolean_wins_over_legacy_roomfit_level(self) -> None:
        """When one entry carries both the legacy level and an explicit
        boolean, the boolean wins for its own field."""
        caps = DeviceCapabilities(supports_peq=True)
        entry = CapabilityFileEntry(roomfit_level=4, supports_roomfit_write=False)
        result = merge_into(caps, entry)
        assert result.supports_roomfit is True
        assert result.supports_roomfit_read is True
        assert result.supports_roomfit_write is False
