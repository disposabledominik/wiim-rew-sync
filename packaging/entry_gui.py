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
    from pathlib import Path

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

    # --- Enable high-DPI scaling (for Windows 11 clarity) ---
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # --- Start Qt application ---
    from PySide6.QtGui import QIcon

    from src.gui.async_bridge import AsyncBridge
    from src.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("WiiM-REW-Sync")
    app.setOrganizationName("wiim-rew-sync")

    # Set app icon (visible in taskbar)
    # In PyInstaller bundle, resources are extracted to sys._MEIPASS
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parent.parent

    icon_path = base_path / "src" / "gui" / "assets" / "icons" / "app_icon.svg"
    if not icon_path.exists():
        # Fallback: try .ico (bundled alongside)
        icon_path = base_path / "src" / "gui" / "assets" / "icons" / "app_icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    bridge = AsyncBridge()
    bridge.start()

    window = MainWindow(async_bridge=bridge)
    window.show()

    exit_code = app.exec()

    bridge.shutdown()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
