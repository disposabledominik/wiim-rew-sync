"""Unit tests for OS-appropriate application data directory resolution (src/utils/app_dirs.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.utils.app_dirs import APP_NAME, get_app_data_dir


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
        with patch.dict("os.environ", {}, clear=True):
            result = get_app_data_dir()
        assert result == Path.home() / f".{APP_NAME}"

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
        with patch.dict("os.environ", {}, clear=True):
            result = get_app_data_dir()
        expected = Path.home() / ".local" / "share" / APP_NAME
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
