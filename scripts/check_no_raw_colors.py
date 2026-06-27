#!/usr/bin/env python3
"""Guard against new hardcoded colors creeping back into src/gui/*.py.

Color *values* belong in exactly two places: the QSS theme files
(fluent_dark.qss / fluent_light.qss) for anything styleable via a QSS
selector, and src/gui/constants.py for the handful of runtime QColor()
calculations that QSS can't express (see constants.py's module docstring).
Every other .py file under src/gui/ should reference those constants
rather than hardcoding a hex literal or an (r, g, b[, a]) QColor() call --
that's exactly the kind of theme-blind regression this script catches
(see WARNING_COLOR_LIGHT/DARK and the import_dialog.py _WARNING_ORANGE fix
this script was written alongside).

Usage:
    python3 scripts/check_no_raw_colors.py

Exits non-zero and prints each offending file:line if a new hardcoded
color is found outside the allowlisted files.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_GUI_DIR = Path(__file__).resolve().parent.parent / "src" / "gui"

# These files are the sanctioned source of truth for color values and are
# exempt from the scan.
_ALLOWLISTED_FILES = {"constants.py", "theme.py"}


# Only match hex colors written as quoted string literals (e.g. "#00B4D8")
# -- a bare '#' followed by digits in a comment (e.g. "smoke #112") is not
# a color and must not be flagged.
_HEX_COLOR_RE = re.compile(
    r"""['"]#[0-9A-Fa-f]{3}['"]|['"]#[0-9A-Fa-f]{6}['"]|['"]#[0-9A-Fa-f]{8}['"]"""
)
_QCOLOR_INT_RE = re.compile(r"QColor\(\s*\d")


def _iter_target_files() -> list[Path]:
    return [
        path
        for path in _GUI_DIR.rglob("*.py")
        if path.name not in _ALLOWLISTED_FILES
    ]


def find_violations() -> list[str]:
    """Return a list of "file:line: snippet" violation strings."""
    violations: list[str] = []
    for path in _iter_target_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _HEX_COLOR_RE.search(line) or _QCOLOR_INT_RE.search(line):
                rel = path.relative_to(_GUI_DIR.parent.parent)
                violations.append(f"{rel}:{lineno}: {line.strip()}")
    return violations


def main() -> int:
    violations = find_violations()
    if not violations:
        print("OK: no hardcoded colors found outside constants.py/theme.py.")
        return 0

    print("error: hardcoded color(s) found outside constants.py/theme.py:", file=sys.stderr)
    for violation in violations:
        print(f"  {violation}", file=sys.stderr)
    print(
        "\nAdd a named constant to src/gui/constants.py (with light/dark "
        "variants if the color must differ by theme, resolved via "
        "src.gui.theme.get_active_theme()) instead of hardcoding the value.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
