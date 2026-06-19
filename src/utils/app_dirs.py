"""OS-appropriate application data directory resolution and first-run setup."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

APP_NAME = "wiim-rew-sync"

#: Subdirectories created during first-run setup.
_SUBDIRECTORIES: tuple[str, ...] = ("logs", "profiles", "backups")


def get_log_dir(settings_override: str | None = None) -> Path:
    """Return the directory where log files are stored.

    Args:
        settings_override: If a non-empty string pointing to an existing
            directory, that path is returned directly.  Otherwise the
            default ``get_app_data_dir() / "logs"`` is used.

    Returns:
        A :class:`Path` to the log directory.
    """
    if settings_override and Path(settings_override).is_dir():
        return Path(settings_override)
    return get_app_data_dir() / "logs"


def get_app_data_dir() -> Path:
    """Return the OS-appropriate application data directory.

    - Windows: %APPDATA%/wiim-rew-sync
    - macOS:   ~/Library/Application Support/wiim-rew-sync
    - Linux:   ~/.local/share/wiim-rew-sync
    """
    system = platform.system()

    if system == "Windows":
        # Use APPDATA on Windows; fallback to ~/.wiim-rew-sync if unavailable
        import os

        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME
        return Path.home() / f".{APP_NAME}"

    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME

    # Linux and other POSIX systems
    # Respect XDG_DATA_HOME if set
    if sys.platform != "win32":
        import os

        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            return Path(xdg_data) / APP_NAME

    return Path.home() / ".local" / "share" / APP_NAME


def ensure_app_directories() -> Path:
    """Create the application data directory and required subdirectories.

    This function is intended to be called once at application startup
    (first-run setup). It is idempotent — calling it when directories
    already exist is a safe no-op.

    Creates:
        - ``<app_data>/logs/``     — rotating log files
        - ``<app_data>/profiles/`` — saved user profiles
        - ``<app_data>/backups/``  — automatic pre-write backups

    Returns:
        The base application data directory path.

    Raises:
        RuntimeError: If any directory cannot be created, with a message
            describing the path and the underlying OS error (Requirement 19.2).
    """
    base_dir = get_app_data_dir()

    for subdir_name in _SUBDIRECTORIES:
        target = base_dir / subdir_name
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"Cannot create application directory '{target}': {exc}"
            ) from exc

    return base_dir
