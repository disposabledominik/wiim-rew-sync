#!/usr/bin/env python3
"""Verify fluent_dark.qss and fluent_light.qss are structurally identical.

The two theme files are meant to differ only in color values (and the header
comment, which documents each theme's own palette). Every selector, property
list, and property order must otherwise match line-for-line — that's what
makes the files easy to diff and keeps a color change from silently drifting
into a structural one.

Usage:
    python3 scripts/check_qss_parity.py

Exits non-zero and prints a unified diff (with colors masked out) if the
files have drifted structurally.
"""

from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

_STYLES_DIR = Path(__file__).resolve().parent.parent / "src" / "gui" / "assets" / "styles"
_DARK_QSS = _STYLES_DIR / "fluent_dark.qss"
_LIGHT_QSS = _STYLES_DIR / "fluent_light.qss"

_HEX_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
_RGBA_RE = re.compile(r"rgba?\([^)]*\)")
_HEADER_COMMENT_RE = re.compile(r"\A/\*.*?\*/\n*", re.DOTALL)


def extract_rule_property(qss_text: str, selector: str, prop: str) -> str:
    """Extract `prop`'s value from the QSS rule anchored by `selector`.

    Anchored to a real selector boundary (`selector` directly followed by
    `{`, allowing whitespace/newlines in between) rather than a bare
    substring search, so a selector that's a literal prefix of a later,
    unrelated one (e.g. adding `::item:hover:disabled` after an existing
    `::item:hover` rule) can't silently match the wrong rule and return the
    wrong value with no test failure to signal it.

    Shared by test_qss_parity.py and test_smoke_fixed_issues.py so this
    "regex a `selector { ... }` block, then pull one property out of it"
    logic isn't hand-rolled independently in each test file.
    """
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", qss_text, re.DOTALL)
    assert match is not None, f"no rule found for selector {selector!r}"
    prop_match = re.search(rf"{re.escape(prop)}:\s*([^;]+);", match.group(1))
    assert prop_match is not None, f"{prop!r} not found in the rule for {selector!r}"
    return prop_match.group(1).strip()


def _normalize(qss_text: str) -> list[str]:
    """Mask color values and strip the leading header comment block.

    The header comment intentionally differs (theme name, palette reference,
    which file is the "structure" anchor) — that's expected, not drift.
    """
    body = _HEADER_COMMENT_RE.sub("", qss_text, count=1)
    masked = _HEX_COLOR_RE.sub("#COLOR", body)
    masked = _RGBA_RE.sub("#COLOR", masked)
    return masked.splitlines(keepends=True)


def check_parity() -> int:
    """Compare the two theme files structurally. Returns a process exit code."""
    if not _DARK_QSS.is_file() or not _LIGHT_QSS.is_file():
        print(f"error: expected both {_DARK_QSS} and {_LIGHT_QSS} to exist", file=sys.stderr)
        return 2

    dark_lines = _normalize(_DARK_QSS.read_text(encoding="utf-8"))
    light_lines = _normalize(_LIGHT_QSS.read_text(encoding="utf-8"))

    if dark_lines == light_lines:
        print("OK: fluent_dark.qss and fluent_light.qss are structurally identical.")
        return 0

    diff = difflib.unified_diff(
        dark_lines,
        light_lines,
        fromfile="fluent_dark.qss (colors masked)",
        tofile="fluent_light.qss (colors masked)",
    )
    print("".join(diff), file=sys.stderr)
    print(
        "\nerror: fluent_dark.qss and fluent_light.qss have structural differences "
        "beyond color values and the header comment. Align selectors, property "
        "lists, and property order between the two files.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(check_parity())
