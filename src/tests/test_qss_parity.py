"""Structural-parity guard for the dark/light QSS theme files.

fluent_dark.qss and fluent_light.qss are meant to differ only in color
values and their header comment. This test fails fast if a future change
introduces a selector, property, or property-order drift between the two
files, instead of leaving that drift to be found during manual QA.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from check_qss_parity import _DARK_QSS, _LIGHT_QSS, _normalize  # type: ignore[import-not-found]


def test_dark_and_light_qss_are_structurally_identical() -> None:
    """Selectors, property lists, and property order must match exactly."""
    dark_lines = _normalize(_DARK_QSS.read_text(encoding="utf-8"))
    light_lines = _normalize(_LIGHT_QSS.read_text(encoding="utf-8"))

    assert dark_lines == light_lines, (
        "fluent_dark.qss and fluent_light.qss have drifted structurally. "
        "Run `python3 scripts/check_qss_parity.py` for a full diff."
    )
