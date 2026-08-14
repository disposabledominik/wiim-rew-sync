"""OS-appropriate application data directory resolution."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

APP_NAME = "wiim-rew-sync"


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


def to_display_path(path: str) -> str:
    """Return ``path`` normalized to forward slashes for display.

    ``str(Path(...))`` renders native backslash separators on Windows, while
    ``QFileDialog`` always returns "/"-separated paths — showing both forms
    in the same UI (e.g. Settings paths) looks inconsistent. Forward slashes
    are valid on Windows for all downstream ``pathlib``/Win32 consumers, so
    normalizing to "/" everywhere is safe.

    Args:
        path: A path string, or "" (returned unchanged).

    Returns:
        The path with "/" separators, or "" if ``path`` is empty.
    """
    if not path:
        return ""
    return Path(path).as_posix()
