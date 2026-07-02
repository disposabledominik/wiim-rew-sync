"""Unit tests for BackupManager."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceCapabilities
from src.models.channel_mode import ChannelMode
from src.models.errors import BackupError
from src.models.peq import PEQSettings
from src.repository.backup_manager import BackupManager


@pytest.fixture
def capabilities() -> DeviceCapabilities:
    """Minimal capabilities fixture with a known UUID."""
    return DeviceCapabilities(
        supports_peq=True,
        max_filters=10,
        model="WiiM Pro",
        firmware="4.8.6",
        uuid="test-device-uuid-1234",
    )


@pytest.fixture
def stereo_settings() -> PEQSettings:
    """Stereo PEQ settings with one band."""
    return PEQSettings(
        source_name="wifi",
        enabled=True,
        channel_mode=ChannelMode.STEREO,
        bands=[
            CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=3.0, q=1.41),
        ],
    )


@pytest.fixture
def backup_manager(tmp_path: Path) -> BackupManager:
    """BackupManager with a temporary storage root."""
    return BackupManager(storage_root=tmp_path)


class TestCreateBackup:
    """Tests for BackupManager.create_backup."""

    def test_creates_valid_json_with_correct_fields(
        self,
        backup_manager: BackupManager,
        stereo_settings: PEQSettings,
        capabilities: DeviceCapabilities,
        tmp_path: Path,
    ) -> None:
        """create_backup writes valid JSON with all required BackupRecord fields."""
        path = backup_manager.create_backup(stereo_settings, capabilities, "pre_write")

        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))

        # Required BackupRecord fields
        assert data["profile_type"] == "backup"
        assert data["trigger"] == "pre_write"
        assert data["device_uuid"] == "test-device-uuid-1234"
        assert data["firmware_version"] == "4.8.6"
        assert data["channel_mode"] == "stereo"
        assert "timestamp" in data
        # ISO 8601 check: must contain 'T' separator
        assert "T" in data["timestamp"]
        # Filters are present
        assert data["filters"] is not None
        assert len(data["filters"]) == 1
        assert data["filters"][0]["frequency_hz"] == 1000.0

    def test_backup_stored_in_backups_directory(
        self,
        backup_manager: BackupManager,
        stereo_settings: PEQSettings,
        capabilities: DeviceCapabilities,
        tmp_path: Path,
    ) -> None:
        """Backup file is stored under backups/<device_uuid>/."""
        path = backup_manager.create_backup(stereo_settings, capabilities, "pre_write")

        # Relative to storage root
        relative = path.relative_to(tmp_path)
        parts = relative.parts
        assert parts[0] == "backups"
        assert parts[1] == "test-device-uuid-1234"
        assert parts[2].endswith(".json")

    def test_lr_mode_backup(
        self,
        backup_manager: BackupManager,
        capabilities: DeviceCapabilities,
    ) -> None:
        """L/R mode settings are backed up with filters_l and filters_r."""
        lr_settings = PEQSettings(
            source_name="wifi",
            enabled=True,
            channel_mode=ChannelMode.LR,
            bands_l=[
                CanonicalFilter(type="PEAK", frequency_hz=500.0, gain_db=2.0, q=1.0),
            ],
            bands_r=[
                CanonicalFilter(type="PEAK", frequency_hz=2000.0, gain_db=-1.5, q=0.7),
            ],
        )

        path = backup_manager.create_backup(lr_settings, capabilities, "pre_rollback")
        data = json.loads(path.read_text(encoding="utf-8"))

        assert data["trigger"] == "pre_rollback"
        assert data["filters"] is None
        assert data["filters_l"] is not None
        assert data["filters_r"] is not None
        assert len(data["filters_l"]) == 1
        assert len(data["filters_r"]) == 1

    def test_lr_mode_both_channels_populated_roundtrips(
        self,
        backup_manager: BackupManager,
        capabilities: DeviceCapabilities,
    ) -> None:
        """L/R backup with both channels populated validates and round-trips correctly."""
        lr_settings = PEQSettings(
            source_name="wifi",
            enabled=True,
            channel_mode=ChannelMode.LR,
            bands_l=[
                CanonicalFilter(type="PEAK", frequency_hz=250.0, gain_db=1.5, q=2.0),
                CanonicalFilter(type="PEAK", frequency_hz=4000.0, gain_db=-2.0, q=1.0),
            ],
            bands_r=[
                CanonicalFilter(type="PEAK", frequency_hz=800.0, gain_db=-3.0, q=0.5),
            ],
        )

        path = backup_manager.create_backup(lr_settings, capabilities, "pre_write")
        data = json.loads(path.read_text(encoding="utf-8"))

        # Verify the BackupRecord is valid by re-parsing it
        from src.models.profile import BackupRecord

        record = BackupRecord(**data)

        # Channel mode mapped to "left" as sentinel for L/R data
        assert record.channel_mode == ChannelMode.LR
        assert record.filters is None
        assert record.filters_l is not None
        assert record.filters_r is not None
        assert len(record.filters_l) == 2
        assert len(record.filters_r) == 1
        # Round-trip: filter values preserved
        assert record.filters_l[0].frequency_hz == 250.0
        assert record.filters_r[0].frequency_hz == 800.0

    def test_lr_mode_empty_bands_r_raises_backup_error(
        self,
        backup_manager: BackupManager,
        capabilities: DeviceCapabilities,
    ) -> None:
        """L/R mode with empty bands_r raises BackupError."""
        lr_settings = PEQSettings(
            source_name="wifi",
            enabled=True,
            channel_mode=ChannelMode.LR,
            bands_l=[
                CanonicalFilter(type="PEAK", frequency_hz=500.0, gain_db=2.0, q=1.0),
            ],
            bands_r=[],
        )

        with pytest.raises(BackupError, match="both bands_l and bands_r must be populated"):
            backup_manager.create_backup(lr_settings, capabilities, "pre_write")

    def test_lr_mode_none_bands_l_raises_backup_error_not_typeerror(
        self,
        backup_manager: BackupManager,
        capabilities: DeviceCapabilities,
    ) -> None:
        """L/R mode settings with bands_l=None raise BackupError, not TypeError.

        RoomFit-derived PEQSettings (not per-channel) can reach create_backup
        with bands_l/bands_r as None rather than an empty list -- regression
        for issue #62's do-undo-roomfit crash (`len(None)` in the error
        message). model_construct() bypasses pydantic validation to build
        this otherwise-unreachable-via-normal-construction state.
        """
        lr_settings = PEQSettings.model_construct(
            source_name="wifi",
            enabled=True,
            channel_mode=ChannelMode.LR,
            name="",
            bands=[],
            bands_l=None,
            bands_r=None,
        )

        with pytest.raises(BackupError, match="both bands_l and bands_r must be populated"):
            backup_manager.create_backup(lr_settings, capabilities, "pre_write")


class TestRetentionPolicy:
    """Tests for the MAX 20 per device retention policy."""

    def test_20th_backup_succeeds(
        self,
        backup_manager: BackupManager,
        stereo_settings: PEQSettings,
        capabilities: DeviceCapabilities,
    ) -> None:
        """Creating 20 backups for a device succeeds without deletion."""
        paths: list[Path] = []
        for _ in range(20):
            p = backup_manager.create_backup(stereo_settings, capabilities, "pre_write")
            paths.append(p)

        # All 20 should exist
        existing = backup_manager.list_backups(capabilities.uuid)
        assert len(existing) == 20

    def test_21st_triggers_deletion_of_oldest(
        self,
        backup_manager: BackupManager,
        stereo_settings: PEQSettings,
        capabilities: DeviceCapabilities,
    ) -> None:
        """The 21st backup triggers deletion of the oldest backup."""
        paths: list[Path] = []
        for _ in range(20):
            p = backup_manager.create_backup(stereo_settings, capabilities, "pre_write")
            paths.append(p)

        first_backup = paths[0]
        assert first_backup.exists()

        # Create 21st
        backup_manager.create_backup(stereo_settings, capabilities, "pre_write")

        # Oldest should be gone
        assert not first_backup.exists()
        # Still at max 20
        existing = backup_manager.list_backups(capabilities.uuid)
        assert len(existing) == 20

    def test_deletion_failure_raises_backup_error(
        self,
        backup_manager: BackupManager,
        stereo_settings: PEQSettings,
        capabilities: DeviceCapabilities,
    ) -> None:
        """If oldest backup cannot be deleted, BackupError is raised."""
        # Create 20 backups
        for _ in range(20):
            backup_manager.create_backup(stereo_settings, capabilities, "pre_write")

        # Patch Path.unlink to raise OSError
        with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
            with pytest.raises(BackupError, match="Failed to delete oldest backup"):
                backup_manager.create_backup(stereo_settings, capabilities, "pre_write")


class TestListBackups:
    """Tests for BackupManager.list_backups."""

    def test_sorted_oldest_first(
        self,
        backup_manager: BackupManager,
        stereo_settings: PEQSettings,
        capabilities: DeviceCapabilities,
    ) -> None:
        """list_backups returns paths sorted oldest-first (by filename)."""
        paths: list[Path] = []
        for _ in range(5):
            p = backup_manager.create_backup(stereo_settings, capabilities, "pre_write")
            paths.append(p)

        listed = backup_manager.list_backups(capabilities.uuid)
        assert len(listed) == 5
        # Should be in creation order (oldest first)
        assert listed == paths

    def test_empty_for_unknown_device(
        self,
        backup_manager: BackupManager,
    ) -> None:
        """list_backups returns empty list for a device with no backups."""
        result = backup_manager.list_backups("nonexistent-uuid")
        assert result == []
