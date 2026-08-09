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

4. Orphaned Qt signal chains: a signal can be "referenced" (defined, emitted,
   even connected to a real slot) at every individual link and still be
   entirely unreachable, because reachability of a *signal* depends on
   whether anything ever triggers the code that emits it — a control-flow
   question, not a reference-count one, which is what vulture (and grep)
   check. Two concrete cases found here:
     - DeviceCard.retry_clicked is defined, emitted internally by
       _on_retry_clicked, and even exercised by a test — but nothing in
       production ever calls `.retry_clicked.connect(...)`, so the emit
       always fires into nothing. Mechanically catchable: find every
       `name = Signal(...)` definition, then search for
       `.name.connect(` anywhere in production; zero hits is a strong
       dead-signal signal. See _collect_signal_definitions()/
       _signal_connect_sites() below.
     - OnboardingOverlay.skip_clicked *is* connected to a real slot
       (MainWindow._on_onboarding_skip) — but the only thing that ever
       emits it is _on_skip(), which vulture already flags as orphaned
       (nothing calls it either). The connection can never fire. This is
       one hop of transitive propagation from an already-confirmed-dead
       method to whatever signal it emits: see
       _signals_emitted_by_dead_methods() below, which re-parses each
       already-orphaned method's body for `self.<name>.emit(...)` calls
       and reports what's connected to that signal as similarly suspect.
       This only propagates one hop (dead method -> its emitted signal ->
       what's connected to it); it does not chase further, e.g. whether
       that connected slot is itself otherwise reachable.

None of this proves a flagged symbol is safe to delete, including hits from
blind spot #4's mechanical checks — a signal with zero connect() sites
today could still be part of a public API a plugin/future caller is meant
to use, and "emitted only by dead code" is exactly the propagation this
script does, not independent confirmation. Every single candidate this
script prints, in every section, needs a human to actually look at the
call site before anything is removed — this script narrows down where to
look, it does not decide for you. Before deleting anything, also check: is
there a code comment or docs/backlog.md / docs/smoke_test_issues.md entry
documenting a deliberate keep (a cheap fallback, dormant infra for a
feature that might return)? If so, add it to _KNOWN_INTENTIONAL_KEEPS below
instead of re-flagging it every run — with a comment citing the source, not
just the name.

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
# The real GUI entry point (packaging/entry_gui.py) lives outside src/ and
# does its src imports deferred/indented (inside main()), so it's easy to
# forget when picking scan roots. Scanning src/ alone produced a real false
# positive here once: configure_logging() looked unused because its only
# production caller is entry_gui.py, invisible to a src/-only scan.
_PACKAGING = _REPO_ROOT / "packaging"
_SCAN_ROOTS = [_SRC, _PACKAGING]

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
    """Run vulture against src/ + packaging/, excluding tests, and return raw
    output lines.

    Excluding src/tests/ from the *scan* (not just treating a test call as
    "not a real use") is what surfaces methods only ever called by their own
    unit test — see this module's docstring, blind spot #1. Scanning
    packaging/ too (not just src/) avoids the false positive documented at
    _PACKAGING's definition above.
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
        sys.executable, "-m", "vulture", *(str(root) for root in _SCAN_ROOTS),
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
    for root in _SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if _TESTS_DIR in path.parents:
                continue
            if needle in path.read_text(encoding="utf-8"):
                hits.append(str(path.relative_to(_REPO_ROOT)))
    return hits


def _test_reference_hits(name: str) -> list[str]:
    """Grep src/tests/ for `name` as a whole identifier (attribute or bare).

    Tells you which test file:line(s) call a dead-code candidate directly —
    exactly the repeated pattern this repo hit (show_error()/show_warnings()/
    set_comparison()/set_error()/reset_to_defaults()/can_push()/etc. all had
    zero production callers but a real, passing unit test calling them
    directly). Deleting the production symbol without also touching these
    lines leaves a NameError/AttributeError waiting in the test suite —
    this is blind spot #1 from this module's docstring, made actionable.
    """
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    hits = []
    for path in sorted(_TESTS_DIR.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}: {line.strip()}")
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


def _collect_signal_definitions() -> dict[str, list[str]]:
    """Map every `name = Signal(...)` class attribute to its defining file:class.

    Only looks at `ClassDef` bodies (not e.g. module-level Signal() calls,
    which don't occur in this codebase) across the scan roots, tests
    excluded — a signal's own definition being test-only isn't a thing.
    """
    owners: dict[str, list[str]] = defaultdict(list)
    for root in _SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if _TESTS_DIR in path.parents:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for item in node.body:
                    if not isinstance(item, ast.Assign):
                        continue
                    call = item.value
                    if not isinstance(call, ast.Call):
                        continue
                    func = call.func
                    func_name = (
                        func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                    )
                    if func_name != "Signal":
                        continue
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            owners[target.id].append(f"{path.relative_to(_REPO_ROOT)}:{node.name}")
    return owners


def _signal_connect_sites(name: str, *, include_tests: bool) -> list[str]:
    """Find `.<name>.connect(` call sites — the only syntax Qt signal wiring
    in this codebase uses. `include_tests=True` also searches src/tests/,
    used only to give context (e.g. "only a test connects this"), never to
    decide whether a signal counts as reachable in production.
    """
    pattern = re.compile(rf"\.{re.escape(name)}\.connect\(")
    roots = [*_SCAN_ROOTS, _TESTS_DIR] if include_tests else _SCAN_ROOTS
    hits = []
    for root in roots:
        for path in root.rglob("*.py"):
            if not include_tests and _TESTS_DIR in path.parents:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if pattern.search(line):
                    hits.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}")
    return hits


def _find_function_node(path: Path, lineno: int) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Find the function/method whose `def` line matches vulture's reported line."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno == lineno:
            return node
    return None


def _emitted_signal_names(node: ast.AST) -> set[str]:
    """Walk a function body for `self.<name>.emit(...)` calls, return the names."""
    names = set()
    for call in ast.walk(node):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
            continue
        if call.func.attr != "emit":
            continue
        emit_target = call.func.value
        if isinstance(emit_target, ast.Attribute):
            names.add(emit_target.attr)
    return names


def _signals_emitted_by_dead_methods(orphaned_lines: list[str]) -> dict[str, tuple[str, list[str]]]:
    """For each already-orphaned method, find signals it emits, and what's
    connected to those signals elsewhere.

    Second half of blind spot #4: propagates "this method is unreachable"
    one hop forward to "so is any signal only it ever emits, and so is
    whatever's connected to that signal" — the OnboardingOverlay.skip_clicked
    case. Only propagates one hop; doesn't chase further from there.

    Returns {signal_name: (emitting_method_location, [connect_site, ...])},
    limited to signals with at least one real connect() site (otherwise
    blind spot #4's other half, _collect_signal_definitions(), already
    covers it as a zero-connect signal).
    """
    result: dict[str, tuple[str, list[str]]] = {}
    for line in orphaned_lines:
        m = _VULTURE_LINE_RE.match(line)
        if m is None or m.group("kind") not in ("method", "function"):
            continue
        path = _REPO_ROOT / m.group("file")
        lineno = int(m.group("line"))
        node = _find_function_node(path, lineno)
        if node is None:
            continue
        for signal_name in _emitted_signal_names(node):
            connect_sites = _signal_connect_sites(signal_name, include_tests=False)
            if connect_sites:
                emitter = f"{m.group('file')}:{lineno} ({m.group('name')})"
                result[signal_name] = (emitter, connect_sites)
    return result


def main() -> int:
    print("Running vulture against src/ (src/tests/ excluded from the scan)...\n")
    raw_lines = _run_vulture()

    orphaned: list[str] = []
    test_only: list[tuple[str, list[str]]] = []
    maybe_dynamic: list[tuple[str, list[str]]] = []
    known_keep: list[str] = []

    for line in raw_lines:
        name = _extract_name(line)
        if name is None:
            continue
        if name in _KNOWN_INTENTIONAL_KEEPS:
            known_keep.append(line)
            continue
        prod_hits = _string_literal_hits(name)
        if prod_hits:
            maybe_dynamic.append((line, prod_hits))
            continue
        test_hits = _test_reference_hits(name)
        if test_hits:
            test_only.append((line, test_hits))
        else:
            orphaned.append(line)

    print(
        f"=== {len(orphaned)} candidate(s) — orphaned everywhere, including "
        "tests ==="
    )
    print("(no production caller, no test caller — safest to delete outright)")
    for line in orphaned:
        print(line)

    print(
        f"\n=== {len(test_only)} candidate(s) — dead in production, but "
        "still called by test(s) ==="
    )
    print(
        "(deleting the production symbol also means removing/updating these "
        "test lines, or the suite breaks)"
    )
    for line, hits in test_only:
        print(line)
        for h in hits:
            print(f"    {h}")

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

    signal_defs = _collect_signal_definitions()
    zero_connect: list[tuple[str, list[str], list[str]]] = []
    for name, defined_at in sorted(signal_defs.items()):
        if _signal_connect_sites(name, include_tests=False):
            continue
        test_sites = _signal_connect_sites(name, include_tests=True)
        zero_connect.append((name, defined_at, test_sites))
    if zero_connect:
        print(
            f"\n=== {len(zero_connect)} signal(s) with zero .connect() sites "
            "in production ==="
        )
        print(
            "(defined, maybe even emitted, but nothing outside the class "
            "subscribes to it — see blind spot #4 in this module's "
            "docstring, the DeviceCard.retry_clicked case)"
        )
        for name, defined_at, test_sites in zero_connect:
            print(f"  {name}: defined at {', '.join(defined_at)}")
            if test_sites:
                print(f"    connected only in test(s): {', '.join(test_sites)}")

    emitted_by_dead = _signals_emitted_by_dead_methods(orphaned)
    if emitted_by_dead:
        print(
            f"\n=== {len(emitted_by_dead)} signal(s) emitted only by an "
            "already-orphaned method ==="
        )
        print(
            "(the emit() call is real and so is the connect() below, but "
            "nothing ever calls the method that would trigger the emit — "
            "see blind spot #4, the OnboardingOverlay.skip_clicked case. "
            "This propagates only one hop; the connected slot itself isn't "
            "re-checked for reachability)"
        )
        for name, (emitter, connect_sites) in sorted(emitted_by_dead.items()):
            print(f"  {name}: only emitted by {emitter}")
            for site in connect_sites:
                print(f"    connected at: {site}")

    print(
        "\nEvery hit above still needs a human to check: (1) getattr()/string "
        "dispatch, (2) a same-named sibling class masking it, (3) a comment or "
        "docs/backlog.md entry documenting a deliberate keep (cite it in "
        "_KNOWN_INTENTIONAL_KEEPS if so), (4) for GUI page/view public "
        "methods specifically, whether it's a deliberate test-only seam "
        "(e.g. MainWindow's page/view properties) vs. a real orphaned "
        "feature, (5) for the 'dead in production, still tested' group, "
        "whether the test lines listed should be deleted with the symbol or "
        "rewritten to exercise it a different way, (6) for the signal "
        "sections, whether the connected slot does something worth keeping "
        "reachable another way. This script narrows down where to look, it "
        "does not decide for you — nothing above should be deleted without "
        "that check. See CLAUDE.md's 'Dead code detection' section."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
