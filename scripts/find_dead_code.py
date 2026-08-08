#!/usr/bin/env python3
"""Find candidate dead code in src/, tuned to this repo's own blind spots.

This is an advisory tool, not a CI gate — every hit below still needs a human
to triage it. It exists because a plain `vulture` run misses/mis-flags things
in ways specific to this codebase, discovered while auditing GUI dead code
(2026-08): see docs/backlog.md and the PR that added this script for the
concrete cases (FiltersPage.show_error()/show_warnings(), DeviceCard's whole
error-state subsystem, OnboardingOverlay._on_skip(), WizardController.can_push()
— all real, all invisible to a naive scan for one of three reasons:

1. Test-only reachable: the method has a real caller, but only its own unit
   test — a plain vulture run (or any reference-counting tool) sees that as
   "used" and stays silent. Fix: exclude src/tests/ from the scan entirely
   (not just from being counted as a "use"), so only production call sites
   count. This catches most of what this script is for.

2. Dynamic dispatch: MainWindow._forward_to_preset_views() calls
   getattr(view, method_name)(*args) with a string method name — no literal
   `.set_peq_presets(` anywhere for vulture (or grep) to find, even though
   it's genuinely called every time a device's presets are fetched. Fix:
   also search for the method name as a quoted string literal before
   trusting a "no references" verdict.

3. Cross-class name collision: vulture matches by attribute name only, not
   by the receiver's type. FiltersPage.show_error() stayed invisible for a
   long time because StatusBanner.show_error() — a different class,
   genuinely called everywhere — shares the name; one real call site clears
   the name for every class that happens to share it. This can't be fully
   automated without real type inference, so this script instead lists every
   method name shared by 2+ GUI classes as a "verify by hand" set.

None of this proves a flagged symbol is safe to delete. Before deleting
anything this script reports, also check: is there a code comment or
docs/backlog.md / docs/smoke_test_issues.md entry documenting a deliberate
keep (a cheap fallback, dormant infra for a feature that might return)? If
so, add it to _KNOWN_INTENTIONAL_KEEPS below instead of re-flagging it every
run — with a comment citing the source, not just the name.

Usage:
    python3 scripts/find_dead_code.py

Requires vulture (dev dependency, see pyproject.toml). Install once with:
    pip3 install -e ".[dev]"
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
_TESTS_DIR = _SRC / "tests"
_GUI_DIR = _SRC / "gui"

# Symbols already investigated and deliberately kept even though nothing
# calls them today. Add a name here only alongside a citation of *why* —
# never just to silence the tool.
_KNOWN_INTENTIONAL_KEEPS: dict[str, str] = {
    "set_dimmed": (
        "StepIndicator — docs/smoke_test_issues.md #267: kept as the cheaper "
        "fallback if hiding the step indicator for sidebar pages is ever "
        "dialed back to muting it instead."
    ),
    "clear": (
        "FilterTable.clear() — docs/smoke_test_issues.md #237: dormant today, "
        "but its setMaximumHeight()-reset bug was fixed and kept correct for "
        "whoever wires up a clear-then-repopulate path next."
    ),
    "get_peq_enabled": (
        "WiiMAdapter — docs/backlog.md 'PEQ / RoomFit Enable/Disable Toggle "
        "in GUI': backend kept available in case that explicitly-declined "
        "GUI feature is reactivated."
    ),
}

# Qt/pydantic hook names a framework calls by convention, never by name in
# our own code — always false positives for a reference-counting tool.
_FRAMEWORK_CALLBACK_NAMES = [
    "closeEvent", "showEvent", "hideEvent", "resizeEvent", "moveEvent",
    "mousePressEvent", "mouseReleaseEvent", "mouseMoveEvent", "mouseDoubleClickEvent",
    "keyPressEvent", "keyReleaseEvent", "paintEvent", "eventFilter",
    "dragEnterEvent", "dropEvent", "wheelEvent", "contextMenuEvent",
    "focusInEvent", "focusOutEvent", "sizeHint", "minimumSizeHint",
    "__enter__", "__exit__",
]

_VULTURE_LINE_RE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+): unused (?P<kind>\w+) '(?P<name>[^']+)'"
)


def _run_vulture() -> list[str]:
    """Run vulture against src/, excluding tests, and return raw output lines.

    Excluding src/tests/ from the *scan* (not just treating a test call as
    "not a real use") is what surfaces methods only ever called by their own
    unit test — see this module's docstring, blind spot #1.
    """
    if shutil.which("vulture") is None and subprocess.run(
        [sys.executable, "-m", "vulture", "--version"], capture_output=True
    ).returncode != 0:
        print(
            "error: vulture is not installed. Run: pip3 install -e \".[dev]\"",
            file=sys.stderr,
        )
        sys.exit(2)

    cmd = [
        sys.executable, "-m", "vulture", str(_SRC),
        "--exclude", str(_TESTS_DIR),
        "--min-confidence", "60",
        "--ignore-names", ",".join(_FRAMEWORK_CALLBACK_NAMES),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    if result.returncode not in (0, 3):  # vulture: 0 = clean, 3 = findings
        print(result.stderr, file=sys.stderr)
        sys.exit(2)
    return [line for line in result.stdout.splitlines() if line.strip()]


def _extract_name(line: str) -> str | None:
    m = _VULTURE_LINE_RE.match(line)
    return m.group("name") if m else None


def _string_literal_hits(name: str) -> list[str]:
    """Grep production code for `name` as a quoted string literal.

    Catches this repo's actual dynamic-dispatch pattern (blind spot #2) —
    a method invoked only via getattr(obj, "name") has no literal `.name(`
    for vulture or a plain grep to find.
    """
    needle = f'"{name}"'
    hits = []
    for path in _SRC.rglob("*.py"):
        if _TESTS_DIR in path.parents:
            continue
        if needle in path.read_text(encoding="utf-8"):
            hits.append(str(path.relative_to(_REPO_ROOT)))
    return hits


def _collect_shared_method_names() -> dict[str, list[str]]:
    """Map every method name defined on 2+ different classes under src/gui.

    Blind spot #3: vulture matches call sites by attribute name only, not by
    receiver type, so a real caller of any one class's method clears the
    name for every other class that happens to share it. This doesn't prove
    anything is dead — it's a "don't fully trust vulture's silence on these,
    check each class's own call sites by hand" list.
    """
    # A set, not a list: a property/setter pair (two FunctionDefs, same name,
    # same class -- e.g. @selected_source.getter/@selected_source.setter)
    # must not count as two "owners" of the name.
    owners: dict[str, set[str]] = defaultdict(set)
    for path in _GUI_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not item.name.startswith("__"):
                            owners[item.name].add(f"{path.relative_to(_REPO_ROOT)}:{node.name}")
    return {name: sorted(classes) for name, classes in owners.items() if len(classes) > 1}


def main() -> int:
    print("Running vulture against src/ (src/tests/ excluded from the scan)...\n")
    raw_lines = _run_vulture()

    definite: list[str] = []
    maybe_dynamic: list[tuple[str, list[str]]] = []
    known_keep: list[str] = []

    for line in raw_lines:
        name = _extract_name(line)
        if name is None:
            continue
        if name in _KNOWN_INTENTIONAL_KEEPS:
            known_keep.append(line)
            continue
        hits = _string_literal_hits(name)
        if hits:
            maybe_dynamic.append((line, hits))
        else:
            definite.append(line)

    print(f"=== {len(definite)} candidate(s) — no string-literal reference found ===")
    for line in definite:
        print(line)

    print(
        f"\n=== {len(maybe_dynamic)} candidate(s) — also appear as a string "
        "literal elsewhere ==="
    )
    print("(possible getattr()/dynamic-dispatch use — verify before deleting)")
    for line, hits in maybe_dynamic:
        print(line)
        for h in hits:
            print(f"    referenced as a string literal in: {h}")

    if known_keep:
        print(
            f"\n=== {len(known_keep)} known, already-reviewed, intentionally "
            "kept (see _KNOWN_INTENTIONAL_KEEPS) ==="
        )
        for line in known_keep:
            print(line)

    shared = _collect_shared_method_names()
    if shared:
        print(f"\n=== {len(shared)} method name(s) shared by 2+ GUI classes ===")
        print(
            "A real caller of any ONE class's copy hides every other class's "
            "same-named copy from ever being flagged. Cross-check candidates "
            "above against this list by hand — this is how FiltersPage."
            "show_error() stayed invisible while StatusBanner.show_error() "
            "(genuinely used) existed."
        )
        for name, classes in sorted(shared.items()):
            print(f"  {name}: {', '.join(classes)}")

    print(
        "\nEvery hit above still needs a human to check: (1) getattr()/string "
        "dispatch, (2) a same-named sibling class masking it, (3) a comment or "
        "docs/backlog.md entry documenting a deliberate keep (cite it in "
        "_KNOWN_INTENTIONAL_KEEPS if so), (4) for GUI page/view public "
        "methods specifically, whether it's a deliberate test-only seam "
        "(e.g. MainWindow's page/view properties) vs. a real orphaned "
        "feature. See CLAUDE.md's 'Dead code detection' section."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
