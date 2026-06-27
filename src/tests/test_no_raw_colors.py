"""Regression guard: no hardcoded colors outside constants.py/theme.py.

Hardcoded hex literals and QColor(r, g, b[, a]) calls in src/gui/*.py are
exactly the kind of theme-blind bug fixed for WARNING_COLOR_LIGHT/DARK and
import_dialog.py's old _WARNING_ORANGE -- correct in one theme, wrong in
the other, and invisible to the QSS structural-parity check since they
live in Python, not QSS. This test fails fast if a new one is introduced.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from check_no_raw_colors import find_violations  # type: ignore[import-not-found]


def test_no_hardcoded_colors_outside_constants_and_theme() -> None:
    """Color values must live in constants.py (Python) or the QSS files."""
    violations = find_violations()

    assert not violations, (
        "Hardcoded color(s) found outside constants.py/theme.py:\n"
        + "\n".join(violations)
        + "\n\nAdd a named constant to src/gui/constants.py instead."
    )
