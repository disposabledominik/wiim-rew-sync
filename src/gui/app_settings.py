"""Application settings persistence.

Manages user preferences (theme, paths, behavior toggles) via a JSON file
in the OS-appropriate app data directory. Handles missing or corrupt files
gracefully by returning sensible defaults.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from src.utils.app_dirs import get_app_data_dir

logger = logging.getLogger("wiim_rew_sync.app_settings")

_SETTINGS_FILENAME = "settings.json"


@dataclass
class AppSettings:
    """Persisted application settings.

    All fields have safe defaults so the app can start even when
    settings.json is missing or corrupt.
    """

    # Appearance
    theme: str = "System"  # "Light", "Dark", or "System"

    # Paths (empty string = use platform default)
    log_directory: str = ""
    presets_directory: str = ""
    # Default starting directory for both REW file import (Filters step) and
    # REW file export dialogs.
    rew_folder: str = ""

    # Behavior
    discovery_timeout: int = 5
    dry_run_default: bool = True  # Req 23.6: enabled for first-time users
    first_run_complete: bool = False
    sidebar_collapsed: bool = False

    # ------------------------------------------------------------------
    # Class methods
    # ------------------------------------------------------------------

    @classmethod
    def settings_path(cls) -> Path:
        """Return the absolute path to settings.json in the app data directory."""
        return get_app_data_dir() / _SETTINGS_FILENAME

    @classmethod
    def load(cls) -> AppSettings:
        """Load settings from disk, returning defaults if the file is missing or corrupt.

        Returns:
            An AppSettings instance populated from settings.json, or fresh
            defaults when the file cannot be read or parsed.
        """
        path = cls.settings_path()

        if not path.exists():
            logger.debug("Settings file not found at %s; using defaults.", path)
            return cls()

        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "Failed to read settings from %s (%s); using defaults.", path, exc
            )
            return cls()

        if not isinstance(data, dict):
            logger.warning("Settings file does not contain a JSON object; using defaults.")
            return cls()

        # One-time migration: "rew_export_folder" was renamed to "rew_folder"
        # (#176, it now drives both REW import and export dialogs) -- without
        # this, an existing settings.json from before the rename would be
        # silently dropped by the known_fields filter below, reverting a
        # user's configured default folder back to "" on upgrade.
        if "rew_export_folder" in data and "rew_folder" not in data:
            data = {**data, "rew_folder": data["rew_export_folder"]}

        # Only pick known fields, ignoring unknown keys for forward compat
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def save(self) -> None:
        """Persist current settings to settings.json.

        Creates the parent directory if it does not exist.
        """
        path = self.settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        data = asdict(self)
        text = json.dumps(data, indent=2, ensure_ascii=False)
        path.write_text(text, encoding="utf-8")
        logger.debug("Settings saved to %s", path)

    @classmethod
    def reset_to_defaults(cls) -> AppSettings:
        """Return a fresh AppSettings instance with all default values."""
        return cls()
