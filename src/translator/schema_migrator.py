"""Profile schema migration — upgrades raw profile dicts to the current schema version."""

from __future__ import annotations

from collections.abc import Callable

from src.models.errors import SchemaVersionError

CURRENT_SCHEMA_VERSION = 1


def _migrate_v0_to_v1(raw: dict[str, object]) -> dict[str, object]:
    """Migrate a version-0 profile dict to version 1.

    Adds ``schema_version: 1`` and ``tags: []`` if missing.
    """
    raw["schema_version"] = 1
    if "tags" not in raw:
        raw["tags"] = []
    return raw


_MIGRATIONS: dict[int, Callable[[dict[str, object]], dict[str, object]]] = {
    0: _migrate_v0_to_v1,
}


def migrate_profile(raw: dict[str, object]) -> dict[str, object]:
    """Migrate a raw profile dict to the current schema version.

    - If ``schema_version`` == CURRENT_SCHEMA_VERSION: return as-is (no-op).
    - If ``schema_version`` < CURRENT_SCHEMA_VERSION: apply migrations sequentially.
    - If ``schema_version`` > CURRENT_SCHEMA_VERSION: raise SchemaVersionError (future version).
    - If ``schema_version`` is missing: assume version 0, apply all migrations.
    - If ``schema_version`` is negative: raise SchemaVersionError.
    """
    version = raw.get("schema_version", 0)

    if not isinstance(version, int):
        raise SchemaVersionError(
            f"schema_version must be an integer, got {type(version).__name__}"
        )

    if version < 0:
        raise SchemaVersionError(
            f"schema_version cannot be negative (got {version})"
        )

    if version > CURRENT_SCHEMA_VERSION:
        raise SchemaVersionError(
            f"Cannot migrate from future schema version {version} "
            f"(current is {CURRENT_SCHEMA_VERSION})"
        )

    if version == CURRENT_SCHEMA_VERSION:
        return raw

    # Apply migrations sequentially from current version to target
    while version < CURRENT_SCHEMA_VERSION:
        migration_fn = _MIGRATIONS.get(version)
        if migration_fn is None:
            raise SchemaVersionError(
                f"No migration path from schema version {version}"
            )
        raw = migration_fn(raw)
        next_version = raw.get("schema_version", version + 1)
        if isinstance(next_version, int):
            version = next_version
        else:
            version = version + 1

    return raw
