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

5. Transitive dead-code chains: if dead method A is the ONLY caller of
   private helper B, then B is unreachable too — but B still has a real,
   literal `self.B(...)` reference sitting in A's source, so vulture (which
   only checks "does a reference exist," not "does the code containing that
   reference ever run") will never flag B on its own. Concrete case found
   here: FilterTable.set_comparison() (already flagged dead-but-tested) is
   the sole caller of _populate_comparison(), which is in turn the sole
   caller of _filters_differ() and _apply_highlight_style() — a whole
   3-method dead subtree behind one flagged entry point, all belonging to
   the shelved "Profile Comparison & Diffing" feature (docs/backlog.md).
   _propagate_transitive_deadness() below builds a repo-wide call index
   once (_build_call_index()), then fixed-point-iterates: for every private
   (_-prefixed) method, if literally every call site of it falls inside an
   already-confirmed-dead method's body range, it's dead too, and joins the
   dead set for the next iteration — which is what catches multi-level
   chains (A -> B -> C), not just one hop. A method with even one call site
   outside a dead range is correctly left alone (FilterTable.clear()'s own
   sibling OnboardingOverlay._dismiss() has two callers, one dead
   (_on_skip) and one live (_on_get_started) — verified NOT to be flagged,
   since it's still reachable through the live path). Scoped to private
   methods and matched by name repo-wide rather than per-class, so it
   carries blind spot #3's name-collision caveat doubled: verify by hand.

6. Framework-invoked callbacks/validators: pydantic calls a
   @field_validator/@model_validator-decorated method automatically on
   every model construction/mutation — never by name from our own code, so
   a reference-counting tool always sees it as orphaned. Same shape as the
   Qt event-override callbacks already excluded via
   _FRAMEWORK_CALLBACK_NAMES (closeEvent, etc.), except validator method
   names vary per model rather than being a fixed set, so this one is
   collected dynamically: _collect_validator_decorated_names() AST-walks
   every class body for the two decorators and excludes any matching name
   before it ever reaches the orphaned/test-only buckets. Concrete cases
   found here: CanonicalFilter.frequency_in_range/q_must_be_positive,
   PEQSettings.check_band_keys_match_channel_mode,
   Profile.check_filter_keys_match_channel_mode.

7. Trivial dead symbol with its literal(s) hand-duplicated inline
   elsewhere: a property/method/module-level constant can be genuinely
   unused *as a symbol* while the exact value(s) it exists to centralize
   are hand-typed again at another call site instead of calling it — in
   which case deleting it throws away the one place the logic was
   centralized and leaves the duplicate behind, when the real fix is
   making that call site use the symbol instead. Doesn't look like a
   duplication problem from vulture's output alone (it just looks like
   ordinary dead code), so nothing else here would catch it. Concrete
   cases found here: ChannelMode.wire_value's "Stereo"/"L/R" return values
   were hand-duplicated in WiiMAdapter.write_roomfit; wiim_api_logger/
   rew_api_logger's logging.getLogger("wiim_rew_sync.wiim_api"/"...rew_api")
   construction was hand-duplicated at 6 call sites across src/adapters/
   and src/translator/. _defining_statement_literals() extracts the
   literal(s) from a trivial dead symbol's single-return/if-else/simple-
   Assign body; _inline_literal_duplicate_hits() then greps the rest of
   the codebase for lines where those literals recur together (2+ shared
   literals) or, for a single-literal definition, where that one literal
   recurs verbatim elsewhere (only attempted if it's not a short/common
   value, to keep noise down). A hit means "verify whether this should be
   consolidated instead of deleted," not "this is definitely duplicated" —
   coincidental shared literals happen; and a miss doesn't clear a
   candidate either, since a *multi-statement* duplicate (found here:
   REWGenerator.generate_lr_files()'s path-derivation + double-generate +
   warning-merge sequence, hand-duplicated in primary_workflows.py) has no
   single literal-bearing statement for this check to key off, and still
   needs the human "does this dead symbol's logic shape recur elsewhere"
   look this script's docstring already asks for.

None of this proves a flagged symbol is safe to delete, including hits from
blind spot #4/#5's mechanical checks — a signal with zero connect() sites
today could still be part of a public API a plugin/future caller is meant
to use, and "reachable only from already-dead code" is exactly the
propagation this script does, not independent confirmation. Every single
candidate this script prints, in every section, needs a human to actually
look at the call site before anything is removed — this script narrows
down where to look, it does not decide for you. Before deleting anything,
also check: is
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
import io
import re
import shutil
import subprocess
import sys
import tokenize
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
# never just to silence the tool. (Round 1's three entries -- set_dimmed,
# FilterTable.clear(), get_peq_enabled -- were all reversed and removed in
# round 2's dead-code pass; see docs/smoke_test_issues.md #267/#237 and
# docs/backlog.md's PEQ/RoomFit toggle entry. A keep list is a snapshot of a
# decision, not a permanent exemption -- see _stale_keep_names() below.)
_KNOWN_INTENTIONAL_KEEPS: dict[str, str] = {}

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
    double = f'"{name}"'
    single = f"'{name}'"
    hits = []
    for root in _SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if _TESTS_DIR in path.parents:
                continue
            text = path.read_text(encoding="utf-8")
            if double in text or single in text:
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


_VALIDATOR_DECORATOR_NAMES = {"field_validator", "model_validator"}


def _decorator_base_name(dec: ast.expr) -> str | None:
    """Bare decorator name, whether written as @name, @name(...), or
    @module.name(...) -- handles the @classmethod-stacked-with-
    @field_validator(...) shape pydantic validators actually use."""
    if isinstance(dec, ast.Call):
        dec = dec.func
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return dec.attr
    return None


def _collect_validator_decorated_names() -> set[str]:
    """Names of every method decorated with @field_validator/@model_validator.

    Blind spot #6: pydantic calls these automatically, never by name from
    our own code, so vulture always flags them as orphaned. Built
    dynamically (unlike _FRAMEWORK_CALLBACK_NAMES's fixed Qt-event list)
    since validator method names vary per model.
    """
    names: set[str] = set()
    for root in _SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if _TESTS_DIR in path.parents:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for item in node.body:
                    if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if any(
                        _decorator_base_name(dec) in _VALIDATOR_DECORATOR_NAMES
                        for dec in item.decorator_list
                    ):
                        names.add(item.name)
    return names


def _collect_signal_definitions() -> dict[str, list[str]]:
    """Map every `name = Signal(...)` class attribute to its defining file:class.

    Only looks at `ClassDef` bodies (not e.g. module-level Signal() calls,
    which don't occur in this codebase) across the scan roots, tests
    excluded — a signal's own definition being test-only isn't a thing.
    Handles both plain (`name = Signal(...)`) and annotated
    (`name: Signal = Signal(...)`) assignment forms — only the former occurs
    in this codebase today, but nothing here should silently miss the latter.
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
                    call: ast.expr | None
                    if isinstance(item, ast.Assign):
                        call = item.value
                        targets: list[ast.expr] = list(item.targets)
                    elif isinstance(item, ast.AnnAssign):
                        call = item.value
                        targets = [item.target] if call is not None else []
                    else:
                        continue
                    if not isinstance(call, ast.Call):
                        continue
                    func = call.func
                    func_name = (
                        func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                    )
                    if func_name != "Signal":
                        continue
                    for target in targets:
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


def _signal_emit_sites(name: str) -> list[tuple[str, int]]:
    """Find `.<name>.emit(` call sites in production code, as (file, lineno).

    Used by _signals_emitted_by_dead_methods() to check whether a signal is
    ALSO emitted by some other, still-live method — not just the
    already-orphaned one being propagated from.
    """
    pattern = re.compile(rf"\.{re.escape(name)}\.emit\(")
    hits = []
    for root in _SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if _TESTS_DIR in path.parents:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if pattern.search(line):
                    hits.append((str(path.relative_to(_REPO_ROOT)), lineno))
    return hits


def _find_function_node(path: Path, lineno: int) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Find the function/method matching vulture's reported line.

    Matches either the `def` line itself or any of its decorators' lines --
    vulture reports a *decorated* function/property at its first decorator's
    line (e.g. `@property` at line 29, `def wire_value` at line 30 reports
    as line 29), not the `def` line, which a `node.lineno`-only match
    silently misses. Found via ChannelMode.wire_value while adding blind
    spot #7 -- pre-existing, also affects any decorated method looked up by
    blind spot #4/#5's transitive checks below.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.lineno == lineno or any(dec.lineno == lineno for dec in node.decorator_list):
            return node
    return None


def _method_line_range(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[int, int]:
    """Return (first_line, last_line) covering a function node's full body."""
    return node.lineno, node.end_lineno or node.lineno


def _enclosing_function(path: Path, lineno: int) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Find the innermost function/method whose body range contains `lineno`.

    Unlike _find_function_node() (which matches vulture's exact `def` line),
    this locates the test function that *contains* an arbitrary reference
    line, for _classify_test_impact() below.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    best: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start, end = _method_line_range(node)
        if start <= lineno <= end:
            best_span = _method_line_range(best)[1] - _method_line_range(best)[0] if best else None
            if best_span is None or (end - start) < best_span:
                best = node
    return best


def _references_name(node: ast.AST, dead_name: str) -> bool:
    """Whether `dead_name` appears as a bare name or attribute access anywhere in `node`."""
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute) and n.attr == dead_name:
            return True
        if isinstance(n, ast.Name) and n.id == dead_name:
            return True
    return False


def _mentions_tainted(expr: ast.expr, tainted: set[str]) -> bool:
    """Whether `expr` reads any name in `tainted` (see _classify_test_impact)."""
    return any(isinstance(n, ast.Name) and n.id in tainted for n in ast.walk(expr))


def _assigned_names(target: ast.expr) -> list[str]:
    """Names bound by an assignment target — handles plain `x = ...` and
    tuple/list unpacking (`x, y = ...`)."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for elt in target.elts for name in _assigned_names(elt)]
    return []


def _flatten_statements(stmts: list[ast.stmt]) -> list[ast.stmt]:
    """Flatten a statement list in source order, descending into if/for/
    while/with/try block bodies (not into nested function/class defs) —
    enough to track assignment order through the control-flow shapes this
    repo's tests actually use (most commonly `with pytest.raises(...):`).
    """
    out: list[ast.stmt] = []
    for stmt in stmts:
        out.append(stmt)
        if isinstance(stmt, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            out.extend(_flatten_statements(stmt.body))
            out.extend(_flatten_statements(stmt.orelse))
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            out.extend(_flatten_statements(stmt.body))
        elif isinstance(stmt, ast.Try):
            out.extend(_flatten_statements(stmt.body))
            for handler in stmt.handlers:
                out.extend(_flatten_statements(handler.body))
            out.extend(_flatten_statements(stmt.orelse))
            out.extend(_flatten_statements(stmt.finalbody))
    return out


def _classify_test_impact(dead_name: str, test_file: Path, around_line: int) -> tuple[str, str]:
    """Classify a test's relationship to a dead symbol as 'obsolete' (safe to
    delete the whole test) or 'repair' (also covers other still-live
    behaviour -- trim, don't delete).

    Heuristic: walks the enclosing test function's statements in source
    order, tracking which local variables are "tainted" by a value that
    derives from an expression referencing dead_name (this codebase's
    dominant test shape is `result = await x.dead_name(...); assert result
    == ...`, where the assert itself never mentions dead_name by name — a
    naive "does the assert's own text mention it" check misses this
    entirely). 'obsolete' if every `assert` references dead_name directly
    or via a tainted variable; 'repair' if at least one doesn't. If there
    are no assert statements at all (e.g. a bare `with pytest.raises(...):
    await x.dead_name(...)`), 'obsolete' only if dead_name was referenced
    somewhere in the function, otherwise a conservative 'repair: verify by
    hand'. Known limitation, found while validating this against round 2's
    manual audit: a *void* dead method (e.g. FilterTable.set_comparison(),
    called as a bare statement with no return value) taints nothing, so a
    test that calls it and then asserts on a side effect elsewhere (e.g. a
    row widget's styling property) always reads as 'repair' here even when
    the whole test is really about that one call — there's no data-flow
    signal to key off for a side-effecting call the way there is for
    `result = await x.dead_name(...); assert result == ...`. Also fooled by
    indirection through a helper function (not tracked) or name shadowing.
    Like every other section this script prints, still needs a human look,
    not a mechanical delete.
    """
    node = _enclosing_function(test_file, around_line)
    if node is None:
        return "repair", "could not locate enclosing test function -- verify by hand"

    stmts = _flatten_statements(node.body)
    tainted: set[str] = set()
    references_dead_name = False
    for stmt in stmts:
        expr: ast.expr | None = None
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            expr = stmt.value
        elif isinstance(stmt, ast.Expr):
            expr = stmt.value
        if expr is None:
            continue
        if _references_name(expr, dead_name) or _mentions_tainted(expr, tainted):
            references_dead_name = True
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    tainted.update(_assigned_names(target))
            elif isinstance(stmt, ast.AnnAssign):
                tainted.update(_assigned_names(stmt.target))

    asserts = [s for s in stmts if isinstance(s, ast.Assert)]
    if not asserts:
        if references_dead_name:
            return (
                "obsolete",
                "no plain assert, but the only meaningful statement(s) "
                "reference the dead symbol (e.g. pytest.raises)",
            )
        return "repair", "no assert statements found -- verify by hand"

    unrelated = sum(
        1
        for a in asserts
        if not (_references_name(a.test, dead_name) or _mentions_tainted(a.test, tainted))
    )
    if unrelated == 0:
        return "obsolete", "every assert references the dead symbol"
    return (
        "repair",
        f"{unrelated} assert(s) unrelated to '{dead_name}' -- trim only the "
        f"{dead_name}-specific lines",
    )


def _find_assign_node(path: Path, lineno: int) -> ast.Assign | ast.AnnAssign | None:
    """Find a module-level (or class-level) Assign/AnnAssign whose line
    matches vulture's reported line -- AnnAssign (`x: T = ...`) is this
    codebase's actual shape for module-level convenience constants like
    wiim_api_logger, found missing here until caught by running the script.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.lineno == lineno:
            return node
    return None


def _dead_symbol_node(file: str, lineno: int, kind: str) -> ast.AST | None:
    """Resolve a vulture hit to its AST node, dispatching on vulture's reported kind.

    `property` is its own vulture kind, distinct from `method` (confirmed
    via ChannelMode.wire_value, an `@property` — this was missed entirely
    until caught by actually running the script against real candidates).
    """
    path = _REPO_ROOT / file
    if kind in ("method", "function", "property"):
        return _find_function_node(path, lineno)
    if kind in ("variable", "attribute"):
        return _find_assign_node(path, lineno)
    return None


def _defining_statement_literals(node: ast.AST) -> set[str] | None:
    """Extract literal(s) from a trivial dead symbol's defining statement.

    Blind spot #7. Targets three shapes: a property/method whose (docstring-
    stripped) body is a single `return <expr>` where `<expr>` is a literal,
    a ternary (`"a" if cond else "b"` — ChannelMode.wire_value's actual
    shape), or a two-branch if/else *statement* both returning constants;
    and a module-level `Assign`/`AnnAssign` whose RHS is a literal or a call
    with only literal arguments (e.g. `logging.getLogger("...")`). Returns
    None for anything else -- deliberately narrow, this is a duplicate-value
    hint, not a general dead code check.

    Known limitation, found while validating this against
    wiim_api_logger/rew_api_logger (round 2's other blind-spot-#7 case): if
    the RHS references a *named* constant instead of a literal directly
    (`logging.getLogger(LOGGER_WIIM_API)`, not
    `logging.getLogger("wiim_rew_sync.wiim_api")`), this returns None --
    resolving one level of named-constant indirection would need tracking
    module-level constant definitions across files, out of scope for what's
    meant to be a narrow, mechanical hint. That case still needed (and got)
    a by-hand check, same as every other section this script prints.
    """
    literals: set[str] = set()

    def collect(expr: ast.expr | None) -> bool:
        if expr is None:
            return False
        if isinstance(expr, ast.Constant) and isinstance(expr.value, (str, int, float)):
            literals.add(str(expr.value))
            return True
        if isinstance(expr, ast.IfExp):
            return collect(expr.body) and collect(expr.orelse)
        if isinstance(expr, ast.Call) and all(isinstance(a, ast.Constant) for a in expr.args):
            found = False
            for a in expr.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, (str, int, float)):
                    literals.add(str(a.value))
                    found = True
            return found
        return False

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]  # drop a leading docstring
        if len(body) == 1 and isinstance(body[0], ast.Return):
            return literals if collect(body[0].value) else None
        if (
            len(body) == 1
            and isinstance(body[0], ast.If)
            and len(body[0].body) == 1
            and len(body[0].orelse) == 1
            and isinstance(body[0].body[0], ast.Return)
            and isinstance(body[0].orelse[0], ast.Return)
        ):
            ok = collect(body[0].body[0].value) and collect(body[0].orelse[0].value)
            return literals if ok else None
        return None
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        return literals if collect(node.value) else None
    return None


_LITERAL_DUP_WINDOW = 15  # lines


def _inline_literal_duplicate_hits(literals: set[str], *, exclude_file: Path) -> list[str]:
    """Grep production code (excluding `exclude_file`) for a hand-duplicated
    copy of `literals` -- 2+ of them appearing within a
    _LITERAL_DUP_WINDOW-line span of each other (e.g. one literal per
    if/else branch, the shape ChannelMode.wire_value's duplicate actually
    took -- same-line-only co-occurrence missed it entirely), or, for a
    single-literal definition, that one literal recurring verbatim
    elsewhere (skipped if it's short/common, to keep noise down). Heuristic
    -- see blind spot #7; a hit isn't proof, a miss doesn't clear it either.
    """
    if not literals:
        return []
    min_hits = 1 if len(literals) == 1 else 2
    if min_hits == 1 and len(next(iter(literals))) < 4:
        return []
    hits: list[str] = []
    for root in _SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if _TESTS_DIR in path.parents or path == exclude_file:
                continue
            lit_lines: dict[str, list[int]] = defaultdict(list)
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                for lit in literals:
                    if f'"{lit}"' in line or f"'{lit}'" in line:
                        lit_lines[lit].append(lineno)
            if len(lit_lines) < min_hits:
                continue
            last_reported = -_LITERAL_DUP_WINDOW - 1
            for anchor in sorted({ln for lns in lit_lines.values() for ln in lns}):
                if anchor <= last_reported + _LITERAL_DUP_WINDOW:
                    continue  # already covered by the previous window reported below
                covered = {
                    lit
                    for lit, lns in lit_lines.items()
                    if any(anchor <= ln <= anchor + _LITERAL_DUP_WINDOW for ln in lns)
                }
                if len(covered) >= min_hits:
                    hits.append(f"{path.relative_to(_REPO_ROOT)}:{anchor}")
                    last_reported = anchor
    return hits


def _stale_keep_names(raw_lines: list[str]) -> list[str]:
    """Names in _KNOWN_INTENTIONAL_KEEPS that vulture no longer even flags --
    i.e. the symbol became genuinely used, or was already deleted, since the
    keep was recorded. Doesn't prove the keep is wrong on its own; a nudge
    to re-verify it still applies (round 2 found all 3 of round 1's keeps
    had become stale this way).
    """
    flagged_names = {_extract_name(line) for line in raw_lines}
    return [name for name in _KNOWN_INTENTIONAL_KEEPS if name not in flagged_names]


def _build_call_index() -> dict[str, list[tuple[str, int]]]:
    """Single repo pass: map every identifier appearing as `.identifier(`
    anywhere (scan roots + tests) to its (file, lineno) occurrences.

    Built once and reused by _propagate_transitive_deadness() below instead
    of re-scanning per candidate — with several hundred private methods in
    this codebase, a fresh repo scan per candidate would be far slower for
    no benefit.

    Uses tokenize, not a raw-text regex, specifically so a comment or
    docstring mentioning `.method_name(` (e.g. "# see obj._old_helper() for
    context") is never counted as a real call site — a phantom call site
    from a comment would silently keep a genuinely dead private method out
    of _propagate_transitive_deadness()'s all-call-sites-are-dead check
    (found in review). Falls back to skipping a file entirely if it fails to
    tokenize (should not happen for valid Python, but a corrupt/non-UTF8
    file must not crash the whole scan).
    """
    index: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for root in [*_SCAN_ROOTS, _TESTS_DIR]:
        for path in root.rglob("*.py"):
            rel = str(path.relative_to(_REPO_ROOT))
            source = path.read_text(encoding="utf-8")
            try:
                tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
            except (tokenize.TokenError, SyntaxError, IndentationError):
                continue
            code_tokens = [
                t
                for t in tokens
                if t.type not in (tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE)
            ]
            for i in range(len(code_tokens) - 2):
                dot, name, paren = code_tokens[i], code_tokens[i + 1], code_tokens[i + 2]
                if (
                    dot.type == tokenize.OP
                    and dot.string == "."
                    and name.type == tokenize.NAME
                    and paren.type == tokenize.OP
                    and paren.string == "("
                ):
                    index[name.string].append((rel, name.start[0]))
    return index


def _collect_private_method_defs() -> dict[str, list[tuple[str, str, int, int]]]:
    """Map every private (_-prefixed, non-dunder) method name to its
    [(file, class, start_line, end_line), ...] definitions under the scan
    roots (production only — a helper only ever *defined* in a test isn't
    the shape this check is for).
    """
    defs: dict[str, list[tuple[str, str, int, int]]] = defaultdict(list)
    for root in _SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if _TESTS_DIR in path.parents:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            rel = str(path.relative_to(_REPO_ROOT))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for item in node.body:
                    if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    name = item.name
                    if name.startswith("__") or not name.startswith("_"):
                        continue
                    start, end = _method_line_range(item)
                    defs[name].append((rel, node.name, start, end))
    return defs


def _propagate_transitive_deadness(
    seed_lines: list[str], call_index: dict[str, list[tuple[str, int]]]
) -> list[tuple[str, list[str], str]]:
    """Fixed-point pass: a private helper whose EVERY call site falls inside
    an already-confirmed-dead method's body is dead too, even though it has
    a real syntactic reference (from inside that dead method) that keeps
    vulture from ever flagging it directly on its own. Multi-level chains
    (A dead -> B dead because only A calls it -> C dead because only B
    calls it) are caught by iterating to a fixed point, not just one hop.

    Scoped to private (_-prefixed) methods, matched by name across the whole
    repo rather than per-class — carries the identical name-collision
    caveat as blind spot #3 (two unrelated classes' same-named private
    helper would be conflated: if either class's copy has ANY live call
    site, neither copy propagates, which is the safe failure direction, but
    a false "still alive" is possible this way too — same as blind spot #3,
    results here need the same by-hand verification, doubly so).
    """
    dead_ranges: dict[str, list[tuple[int, int]]] = defaultdict(list)
    dead_keys: set[tuple[str, str]] = set()
    for line in seed_lines:
        m = _VULTURE_LINE_RE.match(line)
        if m is None or m.group("kind") not in ("method", "function"):
            continue
        path = _REPO_ROOT / m.group("file")
        node = _find_function_node(path, int(m.group("line")))
        if node is None:
            continue
        dead_ranges[m.group("file")].append(_method_line_range(node))
        dead_keys.add((m.group("file"), m.group("name")))

    private_defs = _collect_private_method_defs()
    found: list[tuple[str, list[str], str]] = []
    changed = True
    while changed:
        changed = False
        for name, defs in private_defs.items():
            sites = call_index.get(name, [])
            if not sites:
                continue  # vulture's base pass already covers zero-reference names
            for file, cls, start, end in defs:
                key = (file, name)
                if key in dead_keys:
                    continue
                if all(
                    any(s <= lineno <= e for s, e in dead_ranges.get(f, []))
                    for f, lineno in sites
                ):
                    location = f"{file}:{start}: transitively dead method '{name}' ({cls})"
                    call_site_strs = [f"{f}:{lineno}" for f, lineno in sites]
                    found.append((location, call_site_strs, f"{file}:{cls}"))
                    dead_keys.add(key)
                    dead_ranges[file].append((start, end))
                    changed = True
    return found


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
    """For each already-orphaned method, find signals it emits ONLY it emits,
    and what's connected to those signals elsewhere.

    Second half of blind spot #4: propagates "this method is unreachable"
    one hop forward to "so is any signal only it ever emits, and so is
    whatever's connected to that signal" — the OnboardingOverlay.skip_clicked
    case. Only propagates one hop; doesn't chase further from there.

    "Only it emits" is checked, not assumed: a signal is exclusion-listed
    unless EVERY `.<name>.emit(` call site in production falls inside an
    already-orphaned method's body range. Missing this check was a real bug
    (found in review) — a signal emitted by both a dead method and a live
    one elsewhere would still get reported as "only emitted by the dead
    method", which could lead to deleting a signal/slot pair a live call
    site still genuinely fires.

    Returns {signal_name: (emitting_method_location, [connect_site, ...])},
    limited to signals with at least one real connect() site (otherwise
    blind spot #4's other half, _collect_signal_definitions(), already
    covers it as a zero-connect signal).
    """
    dead_ranges: dict[str, list[tuple[int, int]]] = defaultdict(list)
    emitters: list[tuple[str, int, str]] = []
    for line in orphaned_lines:
        m = _VULTURE_LINE_RE.match(line)
        if m is None or m.group("kind") not in ("method", "function"):
            continue
        path = _REPO_ROOT / m.group("file")
        lineno = int(m.group("line"))
        node = _find_function_node(path, lineno)
        if node is None:
            continue
        dead_ranges[m.group("file")].append(_method_line_range(node))
        emitters.append((m.group("file"), lineno, m.group("name")))

    result: dict[str, tuple[str, list[str]]] = {}
    for file, lineno, name in emitters:
        node = _find_function_node(_REPO_ROOT / file, lineno)
        if node is None:
            continue
        for signal_name in _emitted_signal_names(node):
            connect_sites = _signal_connect_sites(signal_name, include_tests=False)
            if not connect_sites:
                continue
            emit_sites = _signal_emit_sites(signal_name)
            emitted_outside_dead_methods = any(
                not any(s <= eline <= e for s, e in dead_ranges.get(efile, []))
                for efile, eline in emit_sites
            )
            if emitted_outside_dead_methods:
                continue
            emitter = f"{file}:{lineno} ({name})"
            result[signal_name] = (emitter, connect_sites)
    return result


def main() -> int:
    """Run vulture, bucket its findings by blind-spot category, and print a
    human-triaged report. Returns 0 once the report has printed -- a genuine
    vulture failure exits earlier via sys.exit() in _run_vulture(). This is
    a report, not a pass/fail gate (see the module docstring for why it
    isn't wired into CI)."""
    print("Running vulture against src/ (src/tests/ excluded from the scan)...\n")
    raw_lines = _run_vulture()

    validator_names = _collect_validator_decorated_names()
    framework_validators: list[str] = []
    orphaned: list[str] = []
    test_only: list[tuple[str, list[str]]] = []
    maybe_dynamic: list[tuple[str, list[str]]] = []
    known_keep: list[str] = []

    for line in raw_lines:
        name = _extract_name(line)
        if name is None:
            continue
        if name in validator_names:
            framework_validators.append(line)
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

    if framework_validators:
        print(
            f"=== {len(framework_validators)} framework-invoked (pydantic "
            "validator) — never flagged, do not delete ==="
        )
        print(
            "(called automatically by pydantic on model construction/"
            "mutation, not from our own code — see blind spot #6)"
        )
        for line in framework_validators:
            print(line)
        print()

    literal_dup_hits: list[tuple[str, list[str]]] = []
    for line in orphaned + [test_line for test_line, _hits in test_only]:
        m = _VULTURE_LINE_RE.match(line)
        if m is None:
            continue
        node = _dead_symbol_node(m.group("file"), int(m.group("line")), m.group("kind"))
        if node is None:
            continue
        literals = _defining_statement_literals(node)
        if not literals:
            continue
        hits = _inline_literal_duplicate_hits(literals, exclude_file=_REPO_ROOT / m.group("file"))
        if hits:
            literal_dup_hits.append((line, hits))
    if literal_dup_hits:
        print(
            f"=== {len(literal_dup_hits)} trivial dead symbol(s) with matching "
            "literals found elsewhere — check for an inline duplicate before "
            "deleting ==="
        )
        print(
            "(heuristic — see blind spot #7. A hit doesn't prove a duplicate; "
            "a miss doesn't prove there isn't one)"
        )
        for line, hits in literal_dup_hits:
            print(line)
            for h in hits:
                print(f"    possible inline duplicate at: {h}")
        print()

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
        "test lines, or the suite breaks — [OBSOLETE]/[REPAIR] below is a "
        "heuristic classification of which, see _classify_test_impact())"
    )
    for line, hits in test_only:
        print(line)
        dead_name = _extract_name(line) or ""
        for h in hits:
            path_str, lineno_str, _content = h.split(":", 2)
            hit_path = _REPO_ROOT / path_str
            verdict, reason = _classify_test_impact(dead_name, hit_path, int(lineno_str))
            tag = "[OBSOLETE]" if verdict == "obsolete" else f"[REPAIR: {reason}]"
            print(f"    {h} {tag}")

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

    stale_keeps = _stale_keep_names(raw_lines)
    if stale_keeps:
        print(
            f"\n=== {len(stale_keeps)} entr(y/ies) in _KNOWN_INTENTIONAL_KEEPS "
            "that vulture no longer flags ==="
        )
        print("(verify the keep reason still applies, or remove the stale entry)")
        for name in stale_keeps:
            print(f"  {name}: {_KNOWN_INTENTIONAL_KEEPS[name]}")

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

    print("\nBuilding a repo-wide call index for transitive dead-code propagation...")
    call_index = _build_call_index()
    seed_lines = orphaned + [line for line, _hits in test_only] + known_keep
    transitive = _propagate_transitive_deadness(seed_lines, call_index)
    if transitive:
        print(
            f"\n=== {len(transitive)} private method(s) — dead only because "
            "their sole caller(s) are dead code ==="
        )
        print(
            "(every call site of these falls inside an already-dead method's "
            "body -- see blind spot #5 in this module's docstring. A real "
            "reference exists, from inside code that never runs, so vulture "
            "won't flag these on its own)"
        )
        for location, call_sites, _cls in transitive:
            print(location)
            for site in call_sites:
                print(f"    called only from (dead): {site}")

    print(
        "\nEvery hit above still needs a human to check: (1) getattr()/string "
        "dispatch, (2) a same-named sibling class masking it, (3) a comment or "
        "docs/backlog.md entry documenting a deliberate keep (cite it in "
        "_KNOWN_INTENTIONAL_KEEPS if so), (4) for GUI page/view public "
        "methods specifically, whether it's a deliberate test-only seam "
        "(e.g. MainWindow's page/view properties) vs. a real orphaned "
        "feature, (5) for the 'dead in production, still tested' group, "
        "whether the [OBSOLETE]/[REPAIR] tag agrees with a real look at the "
        "test (it's a heuristic, not a guarantee), (6) for the signal "
        "sections, whether the connected slot does something worth keeping "
        "reachable another way, (7) for the transitive-propagation section, "
        "whether the private helper's name collides with an unrelated "
        "class's same-named method (same caveat as (2), doubled), (8) for "
        "the literal-duplicate section, whether the flagged symbol should "
        "be consolidated into its inline duplicate instead of deleted (a "
        "miss doesn't clear a candidate either — a multi-statement "
        "duplicate has no single literal to key off, see blind spot #7). "
        "This script narrows down where to look, it does not decide for "
        "you — nothing above should be deleted without that check. See "
        "CLAUDE.md's 'Dead code detection' section."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
