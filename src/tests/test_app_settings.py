"""Unit tests for AppSettings dataclass and settings file I/O."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from src.gui.app_settings import AppSettings


class TestDefaults:
    """AppSettings default values meet product requirements."""

    def test_theme_defaults_to_system(self) -> None:
        settings = AppSettings()
        assert settings.theme == "System"

    def test_log_directory_defaults_to_empty(self) -> None:
        settings = AppSettings()
        assert settings.log_directory == ""

    def test_presets_directory_defaults_to_empty(self) -> None:
        settings = AppSettings()
        assert settings.presets_directory == ""

    def test_rew_export_folder_defaults_to_empty(self) -> None:
        settings = AppSettings()
        assert settings.rew_export_folder == ""

    def test_discovery_timeout_defaults_to_5(self) -> None:
        settings = AppSettings()
        assert settings.discovery_timeout == 5

    def test_dry_run_default_is_true_for_first_time_users(self) -> None:
        """Req 23.6: Dry Run enabled for first-time users."""
        settings = AppSettings()
        assert settings.dry_run_default is True

    def test_first_run_complete_defaults_to_false(self) -> None:
        settings = AppSettings()
        assert settings.first_run_complete is False

    def test_sidebar_collapsed_defaults_to_false(self) -> None:
        settings = AppSettings()
        assert settings.sidebar_collapsed is False


class TestSettingsPath:
    """settings_path() returns the correct location."""

    def test_returns_path_object(self) -> None:
        result = AppSettings.settings_path()
        assert isinstance(result, Path)

    def test_ends_with_settings_json(self) -> None:
        result = AppSettings.settings_path()
        assert result.name == "settings.json"

    def test_uses_app_data_dir(self) -> None:
        with patch("src.gui.app_settings.get_app_data_dir", return_value=Path("/fake/dir")):
            result = AppSettings.settings_path()
        assert result == Path("/fake/dir/settings.json")


class TestLoad:
    """AppSettings.load() file I/O behavior."""

    def test_returns_defaults_when_file_missing(self, tmp_path: Path) -> None:
        """Missing settings.json returns defaults without error."""
        with patch("src.gui.app_settings.get_app_data_dir", return_value=tmp_path):
            settings = AppSettings.load()
        assert settings == AppSettings()

    def test_loads_saved_values(self, tmp_path: Path) -> None:
        """Successfully loads previously saved settings."""
        data = {
            "theme": "Dark",
            "log_directory": "/var/log/custom",
            "discovery_timeout": 10,
            "first_run_complete": True,
            "dry_run_default": False,
        }
        (tmp_path / "settings.json").write_text(json.dumps(data), encoding="utf-8")

        with patch("src.gui.app_settings.get_app_data_dir", return_value=tmp_path):
            settings = AppSettings.load()

        assert settings.theme == "Dark"
        assert settings.log_directory == "/var/log/custom"
        assert settings.discovery_timeout == 10
        assert settings.first_run_complete is True
        assert settings.dry_run_default is False

    def test_returns_defaults_on_corrupt_json(self, tmp_path: Path) -> None:
        """Corrupt JSON gracefully returns defaults and logs a warning."""
        (tmp_path / "settings.json").write_text("not valid json{{{", encoding="utf-8")

        with patch("src.gui.app_settings.get_app_data_dir", return_value=tmp_path):
            settings = AppSettings.load()

        assert settings == AppSettings()

    def test_returns_defaults_on_non_object_json(self, tmp_path: Path) -> None:
        """JSON array or primitive returns defaults."""
        (tmp_path / "settings.json").write_text("[1, 2, 3]", encoding="utf-8")

        with patch("src.gui.app_settings.get_app_data_dir", return_value=tmp_path):
            settings = AppSettings.load()

        assert settings == AppSettings()

    def test_ignores_unknown_keys(self, tmp_path: Path) -> None:
        """Unknown keys in JSON are silently ignored (forward compat)."""
        data = {"theme": "Light", "unknown_future_field": True}
        (tmp_path / "settings.json").write_text(json.dumps(data), encoding="utf-8")

        with patch("src.gui.app_settings.get_app_data_dir", return_value=tmp_path):
            settings = AppSettings.load()

        assert settings.theme == "Light"
        # No attribute error, and other fields keep defaults
        assert settings.discovery_timeout == 5

    def test_logs_warning_on_corrupt_file(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A warning is logged when the settings file is corrupt."""
        (tmp_path / "settings.json").write_text("{invalid", encoding="utf-8")

        logger = logging.getLogger("wiim_rew_sync.app_settings")
        logger.propagate = True
        try:
            with caplog.at_level(logging.WARNING, logger="wiim_rew_sync.app_settings"):
                with patch("src.gui.app_settings.get_app_data_dir", return_value=tmp_path):
                    AppSettings.load()
            assert "Failed to read settings" in caplog.text
        finally:
            logger.propagate = False

    def test_handles_os_error_gracefully(self, tmp_path: Path) -> None:
        """OSError during file read returns defaults."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{}", encoding="utf-8")

        with patch("src.gui.app_settings.get_app_data_dir", return_value=tmp_path):
            with patch.object(Path, "read_text", side_effect=OSError("Permission denied")):
                settings = AppSettings.load()

        assert settings == AppSettings()


class TestSave:
    """AppSettings.save() writes to disk correctly."""

    def test_creates_settings_file(self, tmp_path: Path) -> None:
        """save() creates the settings.json file."""
        with patch("src.gui.app_settings.get_app_data_dir", return_value=tmp_path):
            settings = AppSettings(theme="Dark")
            settings.save()

        assert (tmp_path / "settings.json").exists()

    def test_written_json_is_valid(self, tmp_path: Path) -> None:
        """save() produces valid JSON."""
        with patch("src.gui.app_settings.get_app_data_dir", return_value=tmp_path):
            settings = AppSettings(theme="Light")
            settings.save()

        text = (tmp_path / "settings.json").read_text(encoding="utf-8")
        data = json.loads(text)
        assert isinstance(data, dict)
        assert data["theme"] == "Light"

    def test_creates_parent_directory_if_missing(self, tmp_path: Path) -> None:
        """save() creates the parent directory when it doesn't exist."""
        nested = tmp_path / "subdir" / "appdata"
        with patch("src.gui.app_settings.get_app_data_dir", return_value=nested):
            settings = AppSettings()
            settings.save()

        assert (nested / "settings.json").exists()


class TestSaveLoadRoundtrip:
    """Round-trip save → load preserves all values."""

    def test_all_fields_preserved(self, tmp_path: Path) -> None:
        """Every field survives a save + load cycle."""
        original = AppSettings(
            theme="Dark",
            log_directory="/tmp/logs",
            presets_directory="/tmp/presets",
            rew_export_folder="/tmp/rew",
            discovery_timeout=10,
            dry_run_default=False,
            first_run_complete=True,
            sidebar_collapsed=True,
        )

        with patch("src.gui.app_settings.get_app_data_dir", return_value=tmp_path):
            original.save()
            loaded = AppSettings.load()

        assert loaded == original

    def test_default_roundtrip(self, tmp_path: Path) -> None:
        """Default settings survive a save + load cycle."""
        with patch("src.gui.app_settings.get_app_data_dir", return_value=tmp_path):
            AppSettings().save()
            loaded = AppSettings.load()

        assert loaded == AppSettings()


class TestResetToDefaults:
    """reset_to_defaults() returns a fresh default instance."""

    def test_returns_default_instance(self) -> None:
        result = AppSettings.reset_to_defaults()
        assert result == AppSettings()

    def test_returns_new_instance(self) -> None:
        """Each call returns a new independent instance."""
        a = AppSettings.reset_to_defaults()
        b = AppSettings.reset_to_defaults()
        assert a is not b
        assert a == b
