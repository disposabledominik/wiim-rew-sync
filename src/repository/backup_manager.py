"""Backup manager — automatic pre-write/pre-rollback device state snapshots."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from src.models.capabilities import DeviceCapabilities
from src.models.errors import BackupError
from src.models.peq import PEQSettings
from src.models.profile import BackupRecord


class BackupManager:
    """Manages automatic backup lifecycle for device EQ state.

    Backups are stored under ``storage_root/backups/<device_uuid>/`` as
    individual JSON files named by ISO 8601 timestamp. They are NOT
    visible in the profile library.
    """

    MAX_BACKUPS_PER_DEVICE = 20

    def __init__(self, storage_root: Path) -> None:
        self._backup_dir = storage_root / "backups"

    def create_backup(
        self,
        settings: PEQSettings,
        capabilities: DeviceCapabilities,
        trigger: Literal["pre_write", "pre_rollback"],
    ) -> Path:
        """Write a BackupRecord JSON file and enforce retention.

        If creating this backup would exceed MAX_BACKUPS_PER_DEVICE for
        the device UUID, the oldest backup is deleted first. If deletion
        of the oldest backup fails, BackupError is raised and the entire
        operation is aborted.

        Returns the path to the newly created backup file.

        Raises:
            BackupError: if retention cleanup fails or file cannot be written.
        """
        device_uuid = capabilities.uuid
        device_dir = self._backup_dir / device_uuid
        device_dir.mkdir(parents=True, exist_ok=True)

        # Enforce retention BEFORE writing the new file
        existing = self.list_backups(device_uuid)
        if len(existing) >= self.MAX_BACKUPS_PER_DEVICE:
            oldest = existing[0]
            try:
                oldest.unlink()
            except OSError as exc:
                raise BackupError(
                    f"Failed to delete oldest backup {oldest}: {exc}"
                ) from exc

        # Build the BackupRecord
        timestamp = datetime.now(UTC).isoformat()
        channel_mode: Literal["stereo", "left", "right"] = (
            "stereo" if settings.channel_mode == "stereo" else "left"
        )

        # Map PEQSettings bands to BackupRecord filter fields
        if settings.channel_mode == "stereo":
            filters = settings.bands if settings.bands else None
            filters_l = None
            filters_r = None
        else:
            filters = None
            filters_l = settings.bands_l if settings.bands_l else None
            filters_r = settings.bands_r if settings.bands_r else None

        record = BackupRecord(
            name=f"backup_{device_uuid}_{timestamp}",
            channel_mode=channel_mode,
            filters=filters,
            filters_l=filters_l,
            filters_r=filters_r,
            timestamp=timestamp,
            device_uuid=device_uuid,
            firmware_version=capabilities.firmware,
            trigger=trigger,
            profile_type="backup",
        )

        # Write to disk with filesystem-safe filename
        safe_ts = timestamp.replace(":", "-")
        backup_path = device_dir / f"{safe_ts}.json"

        try:
            backup_path.write_text(
                json.dumps(record.model_dump(), indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            raise BackupError(
                f"Failed to write backup file {backup_path}: {exc}"
            ) from exc

        return backup_path

    def list_backups(self, device_uuid: str) -> list[Path]:
        """Return backup paths for a device UUID, sorted oldest-first."""
        device_dir = self._backup_dir / device_uuid
        if not device_dir.exists():
            return []
        backups = sorted(device_dir.glob("*.json"))
        return backups
