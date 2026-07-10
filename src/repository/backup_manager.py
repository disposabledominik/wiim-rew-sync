"""Backup manager — automatic pre-write/pre-rollback device state snapshots."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceCapabilities
from src.models.channel_mode import ChannelMode
from src.models.errors import BackupError
from src.models.peq import PEQSettings
from src.models.profile import BackupRecord


def load_backup_json(path: Path) -> dict[str, Any]:
    """Read and parse a backup JSON file.

    Used by both PEQ undo (SecondaryWorkflowManager) and RoomFit undo
    (RoomFitSafeWrite.undo()) to avoid duplicating the file-read + json.loads
    call.

    Raises:
        ValueError: if the file does not contain a JSON object.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Backup file {path} does not contain a JSON object")
    return data


def parse_backup_filters(
    backup_data: dict[str, Any],
) -> tuple[
    list[CanonicalFilter], ChannelMode, list[CanonicalFilter] | None, list[CanonicalFilter] | None
]:
    """Parse a backup JSON dict into filters, channel_mode, and per-channel lists.

    Used by both PEQ undo (SecondaryWorkflowManager) and RoomFit undo
    (RoomFitSafeWrite.undo()) to avoid duplicating backup parsing logic.

    Args:
        backup_data: Parsed JSON dict from a backup file.

    Returns:
        Tuple of (combined_filters, channel_mode, filters_l, filters_r).
        filters_l/filters_r are None for stereo backups. For L/R backups,
        callers must use filters_l/filters_r directly rather than
        re-splitting combined_filters (the combined list is positional
        concatenation and must not be treated as authoritative per-channel
        data).
    """
    channel_mode_raw = backup_data.get("channel_mode", "stereo")
    mode = ChannelMode.from_profile(str(channel_mode_raw))

    if mode.is_lr:
        filters_l_raw = backup_data.get("filters_l", [])
        filters_r_raw = backup_data.get("filters_r", [])
        filters_l = [CanonicalFilter(**f) for f in filters_l_raw]
        filters_r = [CanonicalFilter(**f) for f in filters_r_raw]
        filters = filters_l + filters_r
        return filters, ChannelMode.LR, filters_l, filters_r

    filters_raw = backup_data.get("filters", [])
    return [CanonicalFilter(**f) for f in filters_raw], ChannelMode.STEREO, None, None


def parse_backup_restore_metadata(
    backup_data: dict[str, Any],
) -> tuple[str | None, bool | None, bool | None, bool | None]:
    """Extract both subsystems' pre-push selection/enable-state restore metadata.

    Returns (pre_write_active_profile, pre_write_roomfit_enabled,
    was_new_profile, pre_write_peq_enabled). The first three are RoomFit-only
    (read by RoomFitSafeWrite.undo()); the fourth is PEQ-only (read by
    SafeWrite.undo()) -- each caller unpacks all four and uses only the
    fields relevant to its own subsystem. Each value is None if absent --
    true for the other subsystem's backups (which never set it) and for any
    backup file created before these fields existed, so an old-format file
    degrades gracefully instead of raising.
    """
    return (
        backup_data.get("pre_write_active_profile"),
        backup_data.get("pre_write_roomfit_enabled"),
        backup_data.get("was_new_profile"),
        backup_data.get("pre_write_peq_enabled"),
    )


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
        *,
        pre_write_active_profile: str | None = None,
        pre_write_roomfit_enabled: bool | None = None,
        was_new_profile: bool | None = None,
        pre_write_peq_enabled: bool | None = None,
    ) -> Path:
        """Write a BackupRecord JSON file and enforce retention.

        If creating this backup would exceed MAX_BACKUPS_PER_DEVICE for
        the device UUID, the oldest backup is deleted first. If deletion
        of the oldest backup fails, BackupError is raised and the entire
        operation is aborted.

        Four keyword-only params carry restore metadata (see BackupRecord):
        the first three are RoomFit-only (PEQ callers omit them); the fourth,
        ``pre_write_peq_enabled``, is PEQ-only (RoomFit callers omit it).
        When ``was_new_profile`` is True, ``settings`` is expected to carry no
        real bands (an empty stereo PEQSettings used purely as a metadata
        carrier, since there's no prior content to snapshot for a brand-new
        profile) -- only the three RoomFit restore-metadata fields matter for
        that backup.

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

        # Map PEQSettings bands to BackupRecord filter fields. Identity
        # check, not truthiness: settings.bands is typed as always-a-list
        # (never None), so `if settings.bands else None` would coalesce a
        # genuinely-empty-but-intentional bands=[] (the new-profile RoomFit
        # metadata-only backup case) into None, which the Profile validator
        # then rejects for stereo mode ("must have 'filters' key").
        if settings.channel_mode == ChannelMode.STEREO:
            filters = settings.bands if settings.bands is not None else None
            filters_l = None
            filters_r = None
        else:
            # L/R mode: both bands_l and bands_r must be populated. Some
            # callers (e.g. RoomFit, which isn't per-channel) can hand us
            # settings where these are None rather than an empty list --
            # normalise with `or []` here, matching the rest of the codebase
            # (see safe_write.py, shared_helpers.py).
            bands_l = settings.bands_l or []
            bands_r = settings.bands_r or []
            if not bands_l or not bands_r:
                raise BackupError(
                    "Cannot backup L/R mode settings: both bands_l and bands_r "
                    "must be populated, but got "
                    f"bands_l={len(bands_l)} bands, "
                    f"bands_r={len(bands_r)} bands."
                )
            filters = None
            filters_l = bands_l
            filters_r = bands_r

        # Channel mode for BackupRecord (Profile model)
        record_channel_mode = settings.channel_mode

        record = BackupRecord(
            name=f"backup_{device_uuid}_{timestamp}",
            channel_mode=record_channel_mode,
            filters=filters,
            filters_l=filters_l,
            filters_r=filters_r,
            timestamp=timestamp,
            device_uuid=device_uuid,
            firmware_version=capabilities.firmware,
            trigger=trigger,
            profile_type="backup",
            pre_write_active_profile=pre_write_active_profile,
            pre_write_roomfit_enabled=pre_write_roomfit_enabled,
            was_new_profile=was_new_profile,
            pre_write_peq_enabled=pre_write_peq_enabled,
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
