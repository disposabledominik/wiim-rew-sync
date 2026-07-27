"""Unit tests for src/utils/support_bundle.py.

Covers:
  1. Verify zip contains expected files when all inputs provided
  2. Verify zip handles missing log files gracefully (no crash)
  3. Verify no profile/backup data leaks into the bundle
  4. Verify zip filename matches expected pattern
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from zipfile import ZipFile

import pytest
from pydantic import BaseModel

from src.utils.support_bundle import generate_support_bundle

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeCapabilities(BaseModel):
    """Minimal pydantic model mimicking DeviceCapabilities for testing."""

    supports_peq: bool = True
    max_filters: int = 10
    model: str = "WiiM Pro"
    mac_address: str = ""
    uuid: str = ""


@pytest.fixture()
def log_dir(tmp_path: Path) -> Path:
    """Create a temporary log directory with sample log files."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "app.log").write_text("app log content", encoding="utf-8")
    (logs / "app.log.1").write_text("app log archive", encoding="utf-8")
    (logs / "wiim_api.log").write_text("wiim api log content", encoding="utf-8")
    (logs / "wiim_api.log.1").write_text("wiim api archive", encoding="utf-8")
    (logs / "rew_api.log").write_text("rew api log content", encoding="utf-8")
    (logs / "rew_api.log.1").write_text("rew api archive", encoding="utf-8")
    return logs


@pytest.fixture()
def settings_file(tmp_path: Path) -> Path:
    """Create a temporary settings file."""
    settings = tmp_path / "settings.json"
    settings.write_text('{"theme": "dark"}', encoding="utf-8")
    return settings


@pytest.fixture()
def output_dir(tmp_path: Path) -> Path:
    """Output directory for generated bundles."""
    out = tmp_path / "output"
    out.mkdir()
    return out


# ---------------------------------------------------------------------------
# 1. Verify zip contains expected files when all inputs provided
# ---------------------------------------------------------------------------


class TestBundleContents:
    def test_contains_all_log_files(
        self, output_dir: Path, log_dir: Path, settings_file: Path
    ) -> None:
        caps = FakeCapabilities()
        result = generate_support_bundle(output_dir, log_dir, settings_file, caps)

        with ZipFile(result) as zf:
            names = zf.namelist()

        assert "logs/app.log" in names
        assert "logs/app.log.1" in names
        assert "logs/wiim_api.log" in names
        assert "logs/wiim_api.log.1" in names
        assert "logs/rew_api.log" in names
        assert "logs/rew_api.log.1" in names

    def test_contains_settings_file(
        self, output_dir: Path, log_dir: Path, settings_file: Path
    ) -> None:
        result = generate_support_bundle(output_dir, log_dir, settings_file)

        with ZipFile(result) as zf:
            names = zf.namelist()

        assert "config/settings.json" in names

    def test_contains_device_info_json(
        self, output_dir: Path, log_dir: Path
    ) -> None:
        caps = FakeCapabilities()
        result = generate_support_bundle(output_dir, log_dir, capabilities=caps)

        with ZipFile(result) as zf:
            names = zf.namelist()
            content = json.loads(zf.read("device_info.json"))

        assert "device_info.json" in names
        assert content["supports_peq"] is True
        assert content["max_filters"] == 10
        assert content["model"] == "WiiM Pro"

    def test_contains_version_txt(self, output_dir: Path, log_dir: Path) -> None:
        result = generate_support_bundle(output_dir, log_dir)

        with ZipFile(result) as zf:
            version = zf.read("version.txt").decode("utf-8")

        # Version should be a non-empty string
        assert version
        # Should look like a version (e.g. "0.1.0", or a setuptools_scm dev
        # version like "0.3.dev18+g69e8453ba" for an untagged/pre-release
        # commit -- not always 3 dot-separated components).
        assert re.match(r"\d+(\.\d+)+", version)

    def test_returns_path_to_zip(self, output_dir: Path, log_dir: Path) -> None:
        result = generate_support_bundle(output_dir, log_dir)
        assert result.exists()
        assert result.suffix == ".zip"


# ---------------------------------------------------------------------------
# 2. Verify zip handles missing log files gracefully (no crash)
# ---------------------------------------------------------------------------


class TestMissingFiles:
    def test_empty_log_dir_does_not_crash(self, output_dir: Path, tmp_path: Path) -> None:
        empty_log_dir = tmp_path / "empty_logs"
        empty_log_dir.mkdir()

        result = generate_support_bundle(output_dir, empty_log_dir)

        assert result.exists()
        with ZipFile(result) as zf:
            names = zf.namelist()
        # Only version.txt should be present
        assert "version.txt" in names
        assert "logs/app.log" not in names

    def test_partial_log_files(self, output_dir: Path, tmp_path: Path) -> None:
        partial_logs = tmp_path / "partial_logs"
        partial_logs.mkdir()
        (partial_logs / "app.log").write_text("just app log", encoding="utf-8")

        result = generate_support_bundle(output_dir, partial_logs)

        with ZipFile(result) as zf:
            names = zf.namelist()

        assert "logs/app.log" in names
        assert "logs/app.log.1" not in names
        assert "logs/wiim_api.log" not in names

    def test_missing_settings_file_does_not_crash(
        self, output_dir: Path, log_dir: Path
    ) -> None:
        nonexistent = Path("/nonexistent/settings.json")
        result = generate_support_bundle(output_dir, log_dir, settings_path=nonexistent)

        assert result.exists()
        with ZipFile(result) as zf:
            names = zf.namelist()
        assert "config/settings.json" not in names

    def test_none_capabilities_does_not_crash(
        self, output_dir: Path, log_dir: Path
    ) -> None:
        result = generate_support_bundle(output_dir, log_dir, capabilities=None)

        assert result.exists()
        with ZipFile(result) as zf:
            names = zf.namelist()
        assert "device_info.json" not in names


# ---------------------------------------------------------------------------
# 3. Verify no profile/backup data leaks into the bundle
# ---------------------------------------------------------------------------


class TestPrivacy:
    def test_no_profile_files_in_bundle(
        self, output_dir: Path, log_dir: Path
    ) -> None:
        # Put profile-like files adjacent to log files (simulating app data dir)
        profiles_dir = log_dir.parent / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "my_preset.json").write_text('{"name": "preset"}', encoding="utf-8")

        result = generate_support_bundle(output_dir, log_dir)

        with ZipFile(result) as zf:
            names = zf.namelist()

        # No profile data should be present
        for name in names:
            assert "profile" not in name.lower()
            assert "preset" not in name.lower()

    def test_no_backup_files_in_bundle(
        self, output_dir: Path, log_dir: Path
    ) -> None:
        # Put backup-like files adjacent to log files
        backups_dir = log_dir.parent / "backups"
        backups_dir.mkdir()
        (backups_dir / "backup_20240101.json").write_text("{}", encoding="utf-8")

        result = generate_support_bundle(output_dir, log_dir)

        with ZipFile(result) as zf:
            names = zf.namelist()

        for name in names:
            assert "backup" not in name.lower()

    def test_log_dir_files_only_include_expected_names(
        self, output_dir: Path, log_dir: Path
    ) -> None:
        # Add some extra files in the log dir that shouldn't be picked up
        (log_dir / "user_filters.json").write_text("{}", encoding="utf-8")
        (log_dir / "secret_data.txt").write_text("secret", encoding="utf-8")

        result = generate_support_bundle(output_dir, log_dir)

        with ZipFile(result) as zf:
            names = zf.namelist()

        # Only explicitly-listed log files should be included
        log_names = [n for n in names if n.startswith("logs/")]
        allowed = {
            "logs/app.log",
            "logs/app.log.1",
            "logs/wiim_api.log",
            "logs/wiim_api.log.1",
            "logs/rew_api.log",
            "logs/rew_api.log.1",
        }
        assert set(log_names).issubset(allowed)


# ---------------------------------------------------------------------------
# 4. Verify zip filename matches expected pattern
# ---------------------------------------------------------------------------


class TestAnonymization:
    def test_ip_scrubbed_from_logs(self, output_dir: Path, tmp_path: Path) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "wiim_api.log").write_text(
            "REQ #1 -> GET https://192.168.1.42/httpapi.asp?command=getStatusEx\n"
            "RESP #1 <- 200 body={\"DeviceName\":\"Living Room\"}",
            encoding="utf-8",
        )

        result = generate_support_bundle(output_dir, logs)

        with ZipFile(result) as zf:
            content = zf.read("logs/wiim_api.log").decode("utf-8")

        assert "192.168.1.42" not in content
        assert "Living Room" not in content

    def test_same_value_maps_to_same_token_across_log_files(
        self, output_dir: Path, tmp_path: Path
    ) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "app.log").write_text("Device selected: 192.168.1.42", encoding="utf-8")
        (logs / "wiim_api.log").write_text(
            "REQ #1 -> GET https://192.168.1.42/httpapi.asp", encoding="utf-8"
        )

        result = generate_support_bundle(output_dir, logs)

        with ZipFile(result) as zf:
            app_content = zf.read("logs/app.log").decode("utf-8")
            wiim_content = zf.read("logs/wiim_api.log").decode("utf-8")

        app_token = app_content.split("Device selected: ")[1]
        assert app_token.startswith("IP-")
        assert app_token in wiim_content

    def test_settings_username_path_scrubbed(
        self, output_dir: Path, log_dir: Path, tmp_path: Path
    ) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(
            '{"rew_folder": "/home/dominik/rew-exports"}', encoding="utf-8"
        )

        result = generate_support_bundle(output_dir, log_dir, settings)

        with ZipFile(result) as zf:
            content = zf.read("config/settings.json").decode("utf-8")

        assert "dominik" not in content
        assert "rew-exports" in content

    def test_device_info_mac_and_uuid_scrubbed(
        self, output_dir: Path, log_dir: Path
    ) -> None:
        caps = FakeCapabilities(mac_address="AA:BB:CC:DD:EE:FF", uuid="FF31F09E0000")
        result = generate_support_bundle(output_dir, log_dir, capabilities=caps)

        with ZipFile(result) as zf:
            content = json.loads(zf.read("device_info.json"))

        assert content["model"] == "WiiM Pro"
        assert content["mac_address"] != "AA:BB:CC:DD:EE:FF"
        assert content["mac_address"].startswith("MAC-")
        assert content["uuid"] != "FF31F09E0000"
        assert content["uuid"].startswith("NAME-")

    def test_two_different_ips_get_two_different_tokens(
        self, output_dir: Path, tmp_path: Path
    ) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "app.log").write_text(
            "device a 192.168.1.1, device b 192.168.1.2", encoding="utf-8"
        )

        result = generate_support_bundle(output_dir, logs)

        with ZipFile(result) as zf:
            content = zf.read("logs/app.log").decode("utf-8")

        tokens = {w.rstrip(",") for w in content.split() if w.startswith("IP-")}
        assert len(tokens) == 2

    def test_multiline_log_scrubbed_line_by_line_with_consistent_tokens(
        self, output_dir: Path, tmp_path: Path
    ) -> None:
        """Logs are streamed and scrubbed one line at a time (not loaded whole
        into memory) -- verify that still preserves both line structure and
        cross-line token consistency for a file with many lines."""
        logs = tmp_path / "logs"
        logs.mkdir()
        lines = [f"REQ #{i} -> GET https://192.168.1.42/httpapi.asp" for i in range(500)]
        (logs / "app.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = generate_support_bundle(output_dir, logs)

        with ZipFile(result) as zf:
            content = zf.read("logs/app.log").decode("utf-8")

        scrubbed_lines = content.splitlines()
        assert len(scrubbed_lines) == 500
        tokens = {line.rsplit("https://", 1)[1].split("/")[0] for line in scrubbed_lines}
        assert len(tokens) == 1
        assert "192.168.1.42" not in content


class TestFilenamePattern:
    def test_filename_matches_pattern(self, output_dir: Path, log_dir: Path) -> None:
        result = generate_support_bundle(output_dir, log_dir)

        pattern = r"^wiim-rew-sync-support-\d{4}-\d{2}-\d{2}-\d{6}\.zip$"
        assert re.match(pattern, result.name), (
            f"Filename '{result.name}' does not match pattern '{pattern}'"
        )

    def test_filename_contains_date(self, output_dir: Path, log_dir: Path) -> None:
        result = generate_support_bundle(output_dir, log_dir)

        # Extract date portion
        match = re.search(r"(\d{4}-\d{2}-\d{2})", result.name)
        assert match is not None

    def test_filename_starts_with_prefix(self, output_dir: Path, log_dir: Path) -> None:
        result = generate_support_bundle(output_dir, log_dir)
        assert result.name.startswith("wiim-rew-sync-support-")

    def test_filename_ends_with_zip(self, output_dir: Path, log_dir: Path) -> None:
        result = generate_support_bundle(output_dir, log_dir)
        assert result.name.endswith(".zip")
