"""Unit tests for the schema migrator module."""

from __future__ import annotations

import pytest

from src.models.errors import SchemaVersionError
from src.translator.schema_migrator import CURRENT_SCHEMA_VERSION, migrate_profile


class TestMigrateProfile:
    """Tests for migrate_profile()."""

    def test_current_version_is_noop(self) -> None:
        """A dict with schema_version == CURRENT returns unchanged."""
        raw = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "name": "my_profile",
            "channel_mode": "stereo",
            "filters": [],
            "tags": ["room-a"],
        }
        result = migrate_profile(raw)
        assert result is raw  # same object, no copy needed
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION
        assert result["tags"] == ["room-a"]

    def test_missing_version_migrates_to_current(self) -> None:
        """A dict without schema_version is treated as version 0 and migrated."""
        raw: dict[str, object] = {
            "name": "old_profile",
            "channel_mode": "stereo",
            "filters": [],
        }
        result = migrate_profile(raw)
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION
        assert result["tags"] == []

    def test_version_0_migrates_to_current(self) -> None:
        """A dict with schema_version=0 gets upgraded to current."""
        raw = {
            "schema_version": 0,
            "name": "legacy_profile",
            "channel_mode": "stereo",
            "filters": [],
        }
        result = migrate_profile(raw)
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION
        assert result["tags"] == []

    def test_version_0_preserves_existing_tags(self) -> None:
        """Migration from v0 does not overwrite existing tags."""
        raw = {
            "schema_version": 0,
            "name": "tagged_profile",
            "channel_mode": "stereo",
            "filters": [],
            "tags": ["existing-tag"],
        }
        result = migrate_profile(raw)
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION
        assert result["tags"] == ["existing-tag"]

    def test_future_version_raises_schema_version_error(self) -> None:
        """A dict with schema_version > CURRENT raises SchemaVersionError."""
        raw = {
            "schema_version": 99,
            "name": "future_profile",
        }
        with pytest.raises(SchemaVersionError, match="future schema version 99"):
            migrate_profile(raw)

    def test_negative_version_raises_schema_version_error(self) -> None:
        """A dict with a negative schema_version raises SchemaVersionError."""
        raw = {
            "schema_version": -1,
            "name": "bad_profile",
        }
        with pytest.raises(SchemaVersionError, match="cannot be negative"):
            migrate_profile(raw)
