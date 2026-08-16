"""Structural-parity guard for the dark/light QSS theme files.

fluent_dark.qss and fluent_light.qss are meant to differ only in color
values and their header comment. This test fails fast if a future change
introduces a selector, property, or property-order drift between the two
files, instead of leaving that drift to be found during manual QA.
"""

from __future__ import annotations

import re
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


def _rule_property(qss_text: str, selector: str, prop: str) -> str:
    """Extract `prop`'s value from the first QSS rule containing `selector`."""
    start = qss_text.index(selector)
    block_start = qss_text.index("{", start)
    block_end = qss_text.index("}", block_start)
    block = qss_text[block_start:block_end]
    match = re.search(rf"{re.escape(prop)}:\s*([^;]+);", block)
    assert match is not None, f"{prop!r} not found in the rule for {selector!r}"
    return match.group(1).strip()


def test_checkable_list_keyboard_focus_matches_mouse_hover() -> None:
    """A checkable list's keyboard-current row must look like a mouse-hovered one.

    Regression test: checkableList (DevicePickerDialog) had a ::item:hover
    rule but no ::item:focus rule, so arrow-key/Space keyboard navigation
    fell back to Qt's unstyled default dotted focus rectangle instead of
    the same background a mouse hover shows -- the two input methods gave
    visibly different feedback for the same "this is the current row"
    concept.
    """
    for qss_path in (_DARK_QSS, _LIGHT_QSS):
        text = qss_path.read_text(encoding="utf-8")
        hover_bg = _rule_property(
            text, 'QListWidget[class="checkableList"]::item:hover', "background-color"
        )
        focus_bg = _rule_property(
            text, 'QListWidget[class="checkableList"]::item:focus', "background-color"
        )
        assert hover_bg == focus_bg, (
            f"{qss_path.name}: checkableList's ::item:focus background "
            f"({focus_bg}) doesn't match ::item:hover ({hover_bg})"
        )
