"""Theme manager for loading and applying QSS stylesheets.

Supports light, dark, and system-detected themes with dynamic switching.
QSS files are loaded from ``src/gui/assets/styles/``.
"""

from __future__ import annotations

import logging
import platform
import subprocess
import sys
from pathlib import Path
from typing import Literal

from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

# Resolve the assets/styles and assets/icons directories relative to this module.
_STYLES_DIR = Path(__file__).resolve().parent / "assets" / "styles"
_ICONS_DIR = Path(__file__).resolve().parent / "assets" / "icons"

# Placeholder QSS files use in url(...) references (e.g. the combo-box
# drop-down chevron) instead of a baked-in relative path -- Qt resolves a
# stylesheet's relative url()s against the process's current working
# directory, not the .qss file's own location, so a literal relative path
# would break depending on how the packaged app happens to be launched.
# _load_stylesheet() substitutes this for the real absolute path below.
_ICONS_DIR_TOKEN = "%ICONS_DIR%"  # noqa: S105 -- a QSS placeholder, not a secret

# The combo-box down-arrow icon is theme-specific (light/dark stroke color),
# but fluent_dark.qss/fluent_light.qss must stay byte-identical apart from
# color values (enforced by test_qss_parity.py, which only masks colors --
# not filenames). So the QSS references this token instead of a literal
# chevron_down_dark.svg/chevron_down_light.svg, and _load_stylesheet()
# resolves it to the right filename for the theme actually being loaded.
_CHEVRON_ICON_TOKEN = "%CHEVRON_ICON%"  # noqa: S105 -- a QSS placeholder, not a secret

ThemeMode = Literal["light", "dark", "system"]

# Dynamic property set on the QApplication instance recording the last
# *resolved* light/dark theme (never "system"). Widgets that need a runtime
# QColor (rather than a QSS class) read this via get_active_theme() instead
# of duplicating OS theme-detection logic.
_RESOLVED_THEME_PROPERTY = "wiimRewSyncResolvedTheme"


class ThemeManager:
    """Loads and applies QSS stylesheets based on OS preference or user override.

    Parameters
    ----------
    app : QApplication
        The application instance to apply stylesheets to.

    """

    def __init__(self, app: QApplication) -> None:
        self._app = app

    def apply_theme(self, mode: ThemeMode) -> None:
        """Load and apply the appropriate QSS stylesheet.

        Parameters
        ----------
        mode : ThemeMode
            One of ``"light"``, ``"dark"``, or ``"system"``.
            When ``"system"`` is specified, the OS preference is detected
            automatically via :meth:`detect_system_theme`.

        """
        if mode == "system":
            resolved = self.detect_system_theme()
        else:
            resolved = mode

        qss_filename = f"fluent_{resolved}.qss"
        qss_path = _STYLES_DIR / qss_filename

        stylesheet = self._load_stylesheet(qss_path, resolved)
        self._app.setStyleSheet(stylesheet)
        self._app.setProperty(_RESOLVED_THEME_PROPERTY, resolved)
        logger.info("Applied theme: %s (resolved from mode=%s)", resolved, mode)

    def detect_system_theme(self) -> Literal["light", "dark"]:
        """Detect the operating system dark/light mode preference.

        Returns
        -------
        Literal["light", "dark"]
            The detected system theme. Falls back to ``"light"`` when
            detection is unavailable or fails.

        """
        system = platform.system()

        if system == "Windows":
            return self._detect_windows_theme()
        if system == "Darwin":
            return self._detect_macos_theme()

        # Linux / other: fall back to light
        return "light"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_stylesheet(path: Path, resolved: Literal["light", "dark"]) -> str:
        """Read a QSS file from disk.

        Returns an empty string if the file does not exist yet (graceful
        handling during development when stylesheets haven't been created).

        Args:
            path: The .qss file to load.
            resolved: The theme being loaded ("light" or "dark"), used to
                pick the right file for placeholders like %CHEVRON_ICON%
                that must resolve differently per theme.
        """
        if not path.exists():
            logger.warning(
                "QSS stylesheet not found: %s. Applying empty stylesheet.", path
            )
            return ""

        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("Failed to read stylesheet: %s", path)
            return ""

        # Qt's url() always wants forward slashes, even on Windows.
        text = text.replace(_ICONS_DIR_TOKEN, _ICONS_DIR.as_posix())
        return text.replace(_CHEVRON_ICON_TOKEN, f"chevron_down_{resolved}.svg")

    @staticmethod
    def _detect_windows_theme() -> Literal["light", "dark"]:
        """Check Windows registry for ``AppsUseLightTheme``.

        Key: ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize``
        Value: ``AppsUseLightTheme`` (DWORD) -- 0 means dark, 1 means light.
        """
        if sys.platform != "win32":
            return "light"

        try:
            import winreg

            key_path = (
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return "light" if value == 1 else "dark"
        except (ImportError, OSError):
            logger.debug("Windows theme detection failed, defaulting to light.")
            return "light"

    @staticmethod
    def _detect_macos_theme() -> Literal["light", "dark"]:
        """Check macOS defaults for dark mode via ``defaults read``.

        Reads ``NSGlobalDomain AppleInterfaceStyle``. If the key is absent
        or has a value other than ``"Dark"``, light mode is assumed.
        """
        try:
            result = subprocess.run(
                ["/usr/bin/defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and "dark" in result.stdout.strip().lower():
                return "dark"
        except (OSError, subprocess.TimeoutExpired):
            logger.debug("macOS theme detection failed, defaulting to light.")

        return "light"


def get_active_theme() -> Literal["light", "dark"]:
    """Return the resolved light/dark theme of the running application.

    Widgets that need a runtime ``QColor`` (e.g. table cell foreground)
    rather than a QSS class/property selector call this instead of
    re-implementing OS theme detection. Falls back to ``"light"`` if no
    theme has been applied yet (e.g. a widget constructed in a test without
    going through :class:`ThemeManager`).
    """
    app = QApplication.instance()
    if app is None:
        return "light"
    resolved = app.property(_RESOLVED_THEME_PROPERTY)
    return resolved if resolved in ("light", "dark") else "light"
