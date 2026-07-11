"""Per-model WiiM device capability overrides, loaded from an editable file.

Lets the user or developer adjust app behaviour for specific WiiM models
without code changes -- e.g. correcting a misprobed band count, or
pre-declaring support for a model released after this app version. Models
not listed in the file keep the fully runtime-probed generic behaviour
unchanged (Requirement 6, Requirement 7).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from src.models.capabilities import DeviceCapabilities
from src.models.constants import DEFAULT_MAX_BANDS, DEFAULT_SOURCE_NAMES
from src.utils.app_dirs import get_app_data_dir

logger = logging.getLogger("wiim_rew_sync.app")

_USER_FILENAME = "device_capabilities.json"


class CapabilityFileEntry(BaseModel):
    """One model's capability overrides from the device capability file.

    All fields are optional. Only fields present (non-None) override the
    runtime-probed `DeviceCapabilities`; everything else keeps the probed
    value.
    """

    aliases: list[str] = []
    supports_roomfit: bool | None = None
    supports_roomfit_read: bool | None = None
    supports_roomfit_write: bool | None = None
    # Legacy key from the pre-2026-07-10 schema (the removed 0-4 ladder).
    # Still accepted so user-edited capability files survive upgrades --
    # merge_into() maps it onto the three booleans above when they aren't
    # set explicitly.
    roomfit_level: int | None = None
    supports_lr_filters: bool | None = None
    supports_profile_enumeration: bool | None = None
    supports_batch_write: bool | None = None
    max_bands: int | None = None
    supported_filter_types: list[str] | None = None
    sources: list[str] | None = None
    source_aliases: dict[str, str] | None = None


def bundled_capability_file_path() -> Path:
    """Return the path to the default capability file shipped with the app."""
    return Path(__file__).resolve().parent / "assets" / "device_capabilities.json"


def user_capability_file_path() -> Path:
    """Return the path to the user-editable capability file copy."""
    return get_app_data_dir() / _USER_FILENAME


def ensure_user_capability_file() -> Path:
    """Seed the user-editable capability file from the bundled default if missing.

    Idempotent -- never overwrites an existing user copy, so manual edits
    survive across app restarts and upgrades.
    """
    user_path = user_capability_file_path()
    if user_path.exists():
        return user_path

    bundled_path = bundled_capability_file_path()
    if not bundled_path.exists():
        return user_path

    try:
        user_path.parent.mkdir(parents=True, exist_ok=True)
        user_path.write_text(
            bundled_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    except OSError as exc:
        logger.warning(
            "Could not seed device capability file at %s (%s); "
            "falling back to bundled defaults.",
            user_path,
            exc,
        )
    return user_path


@dataclass
class LoadedCapabilityFile:
    """The result of loading the device capability file: per-model overrides
    plus the optional global default-max-bands override (#167c)."""

    entries: dict[str, CapabilityFileEntry]
    default_max_bands: int


def load_capability_file(path: Path) -> LoadedCapabilityFile:
    """Load and validate the device capability file.

    Malformed entries are logged and skipped rather than raising -- a bad
    file degrades to "no overrides" (full generic probed behaviour) for the
    affected model(s), never a crash, per the Uncertainty Protocol
    (.kiro/steering/rules.md #18). The same applies to `default_max_bands`:
    missing or invalid values degrade to the built-in `DEFAULT_MAX_BANDS`.
    """
    if not path.exists():
        return LoadedCapabilityFile(entries={}, default_max_bands=DEFAULT_MAX_BANDS)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "Failed to read device capability file %s (%s); ignoring.", path, exc
        )
        return LoadedCapabilityFile(entries={}, default_max_bands=DEFAULT_MAX_BANDS)

    models = raw.get("models", {}) if isinstance(raw, dict) else {}
    if not isinstance(models, dict):
        logger.warning(
            "Device capability file %s has no 'models' object; ignoring.", path
        )
        models = {}

    entries: dict[str, CapabilityFileEntry] = {}
    for model_key, model_data in models.items():
        try:
            entries[model_key] = CapabilityFileEntry.model_validate(model_data)
        except ValidationError as exc:
            logger.warning(
                "Skipping malformed device capability entry '%s' in %s: %s",
                model_key,
                path,
                exc,
            )

    default_max_bands = (
        raw.get("default_max_bands", DEFAULT_MAX_BANDS)
        if isinstance(raw, dict)
        else DEFAULT_MAX_BANDS
    )
    is_valid = (
        isinstance(default_max_bands, int)
        and not isinstance(default_max_bands, bool)
        and default_max_bands > 0
    )
    if not is_valid:
        if default_max_bands != DEFAULT_MAX_BANDS:
            logger.warning(
                "Invalid default_max_bands in %s; using built-in default.", path
            )
        default_max_bands = DEFAULT_MAX_BANDS

    return LoadedCapabilityFile(entries=entries, default_max_bands=default_max_bands)


def _normalize_model(value: str) -> str:
    """Normalize a model string for matching (case/space/underscore-insensitive).

    Mirrors the normalisation already used by
    ``src.utils.device_identity.is_wiim_device`` so capability-file keys work
    whether firmware reports "WiiM_Mini" or "WiiM Mini".
    """
    return value.strip().lower().replace(" ", "_")


def find_entry(
    model: str, entries: dict[str, CapabilityFileEntry]
) -> CapabilityFileEntry | None:
    """Find the capability entry matching a probed device model.

    Matches the canonical model key or any alias, case/space/underscore-insensitively.
    """
    if not model:
        return None
    needle = _normalize_model(model)
    for key, entry in entries.items():
        if _normalize_model(key) == needle:
            return entry
        if any(_normalize_model(alias) == needle for alias in entry.aliases):
            return entry
    return None


def merge_into(
    capabilities: DeviceCapabilities,
    entry: CapabilityFileEntry | None,
    default_max_bands: int = DEFAULT_MAX_BANDS,
) -> DeviceCapabilities:
    """Apply capability-file overrides onto probed capabilities, returning it.

    Fields absent from `entry` (or when `entry` is None) keep their probed
    value. `max_filters` gets the `default_max_bands` cap (Requirement 7,
    optionally overridden file-wide via the capability file's
    `"default_max_bands"` key, #167c) unless the entry states a `max_bands`
    for this model -- which acts as a ceiling on the probed count, never
    raising it past physical reality (see the note above
    `min(entry.max_bands, capabilities.max_filters)` below).
    """
    if entry is not None:
        capabilities.capability_file_override = True
        # Legacy roomfit_level (removed 0-4 ladder) maps onto the three
        # booleans, but an explicit boolean in the same entry always wins.
        if entry.roomfit_level is not None:
            level = entry.roomfit_level
            if entry.supports_roomfit is None:
                capabilities.supports_roomfit = level >= 1
            if entry.supports_roomfit_read is None:
                capabilities.supports_roomfit_read = level >= 2
            if entry.supports_roomfit_write is None:
                capabilities.supports_roomfit_write = level >= 4
        if entry.supports_roomfit is not None:
            capabilities.supports_roomfit = entry.supports_roomfit
        if entry.supports_roomfit_read is not None:
            capabilities.supports_roomfit_read = entry.supports_roomfit_read
        if entry.supports_roomfit_write is not None:
            capabilities.supports_roomfit_write = entry.supports_roomfit_write
        if entry.supports_lr_filters is not None:
            capabilities.supports_lr_filters = entry.supports_lr_filters
        if entry.supports_profile_enumeration is not None:
            capabilities.supports_profile_enumeration = entry.supports_profile_enumeration
        if entry.supports_batch_write is not None:
            capabilities.supports_batch_write = entry.supports_batch_write
        if entry.supported_filter_types is not None:
            capabilities.supported_filter_types = entry.supported_filter_types
        if entry.sources is not None:
            capabilities.source_names = entry.sources
        if entry.source_aliases is not None:
            capabilities.source_aliases = entry.source_aliases

    # Keep the three RoomFit booleans internally consistent after overrides:
    # a device whose subsystem is absent can't be readable/writable, and one
    # that isn't readable can't be writable. (The old roomfit_level ladder
    # needed a whole reconciliation block here; with the booleans as the
    # only state, this downward cascade is all that's left.)
    if not capabilities.supports_roomfit:
        capabilities.supports_roomfit_read = False
    if not capabilities.supports_roomfit_read:
        capabilities.supports_roomfit_write = False

    # Fall back to the generic source list (#167b) when neither the runtime
    # probe (getAudioInputEnable) nor a capability-file `sources` override
    # produced anything -- e.g. WiiM Mini, which supports neither.
    if not capabilities.source_names:
        capabilities.source_names = list(DEFAULT_SOURCE_NAMES)
        capabilities.used_generic_capabilities = True

    if not capabilities.supports_peq:
        return capabilities

    if entry is not None and entry.max_bands is not None:
        # The file's max_bands is a ceiling, not an absolute override: it can
        # lower the probed band count (e.g. force a stricter cap for a known
        # model) but never raise it past what the device actually reported,
        # since probing reflects the real number of usable PEQ slots on the
        # connected firmware (e.g. WiiM Amp Ultra has 10 bands on older
        # firmware and 12 on firmware 20260409+ -- see docs/corrections.md).
        capabilities.max_filters = min(entry.max_bands, capabilities.max_filters)
    else:
        capabilities.max_filters = min(capabilities.max_filters, default_max_bands)

    return capabilities


_cached_capability_file: LoadedCapabilityFile | None = None


def get_cached_capability_file(force_reload: bool = False) -> LoadedCapabilityFile:
    """Return the process-wide cached capability file (entries + default_max_bands).

    Loaded once (seeding the user copy from the bundled default on first
    access) and cached for the lifetime of the process -- restarting the app
    is what picks up manual edits, matching the existing `AppSettings`
    load-once-at-startup convention.
    """
    global _cached_capability_file
    if _cached_capability_file is None or force_reload:
        path = ensure_user_capability_file()
        _cached_capability_file = load_capability_file(path)
    return _cached_capability_file
