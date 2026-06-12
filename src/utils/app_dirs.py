"""OS-appropriate application data directory resolution."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

APP_NAME = "wiim-rew-sync"


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
