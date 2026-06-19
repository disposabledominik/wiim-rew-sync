"""Support bundle generator for the WiiM ↔ REW PEQ Sync Tool.

Creates a timestamped ZIP archive containing logs, config, device info,
and version data for diagnostic/support purposes.

Privacy: SHALL NOT include user filter data, profiles, or backup files.
"""

from __future__ import annotations

import importlib.metadata
import json
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile


def generate_support_bundle(
    output_path: Path,
    log_dir: Path,
    settings_path: Path | None = None,
    capabilities: object | None = None,
) -> Path:
    """Generate a support bundle ZIP for diagnostics.

    Creates a timestamped ``.zip`` containing:
      - All log files (current + most recent ``.1`` archive if it exists)
      - The app's settings/config file (if ``settings_path`` is provided and exists)
      - A ``device_info.json`` with capabilities dump (if ``capabilities`` is provided)
      - A ``version.txt`` containing the app version string

    SHALL NOT include user filter data, profiles, or backup files (privacy).

    Args:
        output_path: Directory where the ZIP file will be created.
        log_dir: Directory containing the log files.
        settings_path: Optional path to the app's settings/config file.
        capabilities: Optional device capabilities object.  If it has a
            ``model_dump()`` method (pydantic model), that is used for
            serialisation; otherwise ``str()`` is used.

    Returns:
        The :class:`Path` to the created ZIP file.
    """
    timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%d-%H%M%S")
    zip_name = f"wiim-rew-sync-support-{timestamp}.zip"
    zip_path = output_path / zip_name

    # Ensure the output directory exists
    output_path.mkdir(parents=True, exist_ok=True)

    # Log files to include (current + .1 archive)
    log_files = [
        "app.log",
        "app.log.1",
        "wiim_api.log",
        "wiim_api.log.1",
        "rew_api.log",
        "rew_api.log.1",
    ]

    with ZipFile(zip_path, "w") as zf:
        # Add log files (skip missing ones gracefully)
        for log_file in log_files:
            log_path = log_dir / log_file
            if log_path.is_file():
                zf.write(log_path, arcname=f"logs/{log_file}")

        # Add settings file if provided and exists
        if settings_path is not None and settings_path.is_file():
            zf.write(settings_path, arcname=f"config/{settings_path.name}")

        # Add device capabilities dump
        if capabilities is not None:
            if hasattr(capabilities, "model_dump"):
                caps_data = capabilities.model_dump()  # type: ignore[union-attr]
            else:
                caps_data = str(capabilities)
            zf.writestr(
                "device_info.json",
                json.dumps(caps_data, indent=2, default=str),
            )

        # Add version.txt
        version = _get_app_version()
        zf.writestr("version.txt", version)

    return zip_path


def _get_app_version() -> str:
    """Retrieve the application version string.

    Tries ``importlib.metadata`` first; falls back to hardcoded "0.1.0".
    """
    try:
        return importlib.metadata.version("wiim-rew-sync")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"
