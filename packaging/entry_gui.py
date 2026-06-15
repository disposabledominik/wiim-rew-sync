"""GUI entry point for PyInstaller-packaged WiiM <-> REW PEQ Sync.

This thin launcher script is the entry point that PyInstaller packages.
It sets up logging, creates the Qt application, starts the async bridge,
and runs the main window.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Launch the WiiM <-> REW PEQ Sync GUI application.

    Returns:
        Exit code (0 for success).
    """
    from src.logging.setup import configure_logging, ensure_logs_directory
    from src.utils.app_dirs import get_app_data_dir

    # --- Ensure required directories exist ---
    app_data = get_app_data_dir()
    logs_dir = app_data / "logs"

    try:
        ensure_logs_directory(logs_dir)
    except RuntimeError as exc:
        # Requirement 19.2: display error and abort if logs dir cannot be created
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1

    try:
        profiles_dir = app_data / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            f"FATAL: Cannot create profile storage directory "
            f"'{profiles_dir}': {exc}",
            file=sys.stderr,
        )
        return 1

    # --- Configure logging ---
    configure_logging(logs_dir)

    # --- Start Qt application ---
    from PySide6.QtWidgets import QApplication

    from src.gui.async_bridge import AsyncBridge
    from src.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("WiiM-REW-Sync")
    app.setOrganizationName("wiim-rew-sync")

    bridge = AsyncBridge()
    bridge.start()

    window = MainWindow(async_bridge=bridge)
    window.show()

    exit_code = app.exec()

    bridge.shutdown()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
