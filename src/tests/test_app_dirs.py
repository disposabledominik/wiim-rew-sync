"""Unit tests for OS-appropriate application data directory resolution (src/utils/app_dirs.py)."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from src.utils.app_dirs import APP_NAME, ensure_app_directories, get_app_data_dir, get_log_dir


class TestWindowsPath:
    """Tests for Windows platform detection."""

    @patch("src.utils.app_dirs.platform.system", return_value="Windows")
    def test_returns_appdata_path_when_set(self, _mock_system: object) -> None:
        """APPDATA env var is used when available on Windows."""
        with patch.dict("os.environ", {"APPDATA": r"C:\Users\test\AppData\Roaming"}):
            result = get_app_data_dir()
        assert result == Path(r"C:\Users\test\AppData\Roaming") / APP_NAME

    @patch("src.utils.app_dirs.platform.system", return_value="Windows")
    def test_falls_back_to_home_when_appdata_unset(self, _mock_system: object) -> None:
        """Falls back to ~/.wiim-rew-sync when APPDATA is not set."""
        fake_home = Path("/home/testuser")
        with patch.dict("os.environ", {}, clear=True):
            with patch("src.utils.app_dirs.Path.home", return_value=fake_home):
                result = get_app_data_dir()
        assert result == fake_home / f".{APP_NAME}"

    @patch("src.utils.app_dirs.platform.system", return_value="Windows")
    def test_path_ends_with_app_name(self, _mock_system: object) -> None:
        """Windows path always ends with the app name."""
        with patch.dict("os.environ", {"APPDATA": r"C:\Users\test\AppData\Roaming"}):
            result = get_app_data_dir()
        assert result.name == APP_NAME


class TestMacOSPath:
    """Tests for macOS (Darwin) platform detection."""

    @patch("src.utils.app_dirs.platform.system", return_value="Darwin")
    def test_returns_library_application_support(self, _mock_system: object) -> None:
        """macOS returns ~/Library/Application Support/wiim-rew-sync."""
        result = get_app_data_dir()
        expected = Path.home() / "Library" / "Application Support" / APP_NAME
        assert result == expected

    @patch("src.utils.app_dirs.platform.system", return_value="Darwin")
    def test_path_ends_with_app_name(self, _mock_system: object) -> None:
        """macOS path always ends with the app name."""
        result = get_app_data_dir()
        assert result.name == APP_NAME


class TestLinuxPath:
    """Tests for Linux/POSIX platform detection."""

    @patch("src.utils.app_dirs.platform.system", return_value="Linux")
    @patch("src.utils.app_dirs.sys.platform", "linux")
    def test_returns_default_xdg_data_path(self, _mock_system: object) -> None:
        """Linux defaults to ~/.local/share/wiim-rew-sync."""
        fake_home = Path("/home/testuser")
        with patch.dict("os.environ", {}, clear=True):
            with patch("src.utils.app_dirs.Path.home", return_value=fake_home):
                result = get_app_data_dir()
        expected = fake_home / ".local" / "share" / APP_NAME
        assert result == expected

    @patch("src.utils.app_dirs.platform.system", return_value="Linux")
    @patch("src.utils.app_dirs.sys.platform", "linux")
    def test_respects_xdg_data_home(self, _mock_system: object) -> None:
        """XDG_DATA_HOME override is respected on Linux."""
        with patch.dict("os.environ", {"XDG_DATA_HOME": "/custom/data"}):
            result = get_app_data_dir()
        assert result == Path("/custom/data") / APP_NAME

    @patch("src.utils.app_dirs.platform.system", return_value="Linux")
    @patch("src.utils.app_dirs.sys.platform", "linux")
    def test_path_ends_with_app_name_default(self, _mock_system: object) -> None:
        """Linux default path always ends with the app name."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("src.utils.app_dirs.Path.home", return_value=Path("/home/testuser")):
                result = get_app_data_dir()
        assert result.name == APP_NAME

    @patch("src.utils.app_dirs.platform.system", return_value="Linux")
    @patch("src.utils.app_dirs.sys.platform", "linux")
    def test_path_ends_with_app_name_xdg(self, _mock_system: object) -> None:
        """Linux XDG path always ends with the app name."""
        with patch.dict("os.environ", {"XDG_DATA_HOME": "/opt/share"}):
            result = get_app_data_dir()
        assert result.name == APP_NAME


class TestAppName:
    """Sanity check on APP_NAME constant."""

    def test_app_name_value(self) -> None:
        assert APP_NAME == "wiim-rew-sync"


class TestEnsureAppDirectories:
    """Tests for the first-run setup function ensure_app_directories()."""

    def test_creates_all_subdirectories(self, tmp_path: Path) -> None:
        """All three required subdirectories are created on first call."""
        with patch("src.utils.app_dirs.get_app_data_dir", return_value=tmp_path):
            result = ensure_app_directories()

        assert result == tmp_path
        assert (tmp_path / "logs").is_dir()
        assert (tmp_path / "profiles").is_dir()
        assert (tmp_path / "backups").is_dir()

    def test_idempotent_when_directories_exist(self, tmp_path: Path) -> None:
        """Calling ensure_app_directories() when dirs already exist is a no-op."""
        # Pre-create the directories
        (tmp_path / "logs").mkdir()
        (tmp_path / "profiles").mkdir()
        (tmp_path / "backups").mkdir()

        with patch("src.utils.app_dirs.get_app_data_dir", return_value=tmp_path):
            result = ensure_app_directories()

        assert result == tmp_path
        assert (tmp_path / "logs").is_dir()
        assert (tmp_path / "profiles").is_dir()
        assert (tmp_path / "backups").is_dir()

    def test_raises_runtime_error_on_os_error(self, tmp_path: Path) -> None:
        """OSError during directory creation is re-raised as RuntimeError."""
        with patch("src.utils.app_dirs.get_app_data_dir", return_value=tmp_path):
            with patch.object(Path, "mkdir", side_effect=OSError("Permission denied")):
                with pytest.raises(RuntimeError, match=re.escape(str(tmp_path))):
                    ensure_app_directories()


class TestGetLogDir:
    """Tests for get_log_dir() with optional settings override."""

    def test_returns_override_path_when_valid_directory(self, tmp_path: Path) -> None:
        """A valid, existing directory override is returned directly."""
        custom_dir = tmp_path / "custom_logs"
        custom_dir.mkdir()
        result = get_log_dir(settings_override=str(custom_dir))
        assert result == custom_dir

    def test_falls_back_to_default_when_override_is_none(self) -> None:
        """None override returns the default logs path."""
        result = get_log_dir(settings_override=None)
        expected = get_app_data_dir() / "logs"
        assert result == expected

    def test_falls_back_to_default_when_override_is_empty_string(self) -> None:
        """Empty string override returns the default logs path."""
        result = get_log_dir(settings_override="")
        expected = get_app_data_dir() / "logs"
        assert result == expected

    def test_falls_back_to_default_when_override_path_does_not_exist(self) -> None:
        """Non-existent override path returns the default logs path."""
        result = get_log_dir(settings_override="/nonexistent/path/to/logs")
        expected = get_app_data_dir() / "logs"
        assert result == expected

    def test_default_path_ends_with_logs(self) -> None:
        """The default log directory is always named 'logs'."""
        result = get_log_dir()
        assert result.name == "logs"
