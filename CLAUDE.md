# CLAUDE.md

**All development happens on the `development` branch unless the user explicitly names a different
branch for a specific task.** This means every pull request's **base branch must be `development`,
not `main`** — `main` only receives merges from `development` (e.g. when cutting a release). If a PR
was opened against `main` by mistake, retarget it (`base` branch update) rather than closing and
reopening.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

WiiM ↔ REW PEQ Sync Tool — a local-first desktop app (PySide6 GUI + CLI) that transfers parametric
EQ (PEQ) and RoomFit filter configs between Room EQ Wizard (REW) and WiiM devices on the LAN. No
cloud, no telemetry, no accounts. Target users are non-technical audiophiles.

Design principles that drive most design decisions in this codebase:
1. Safety before convenience — never write to a device without backup and verification.
2. All data flows through the Canonical Filter Model — direct REW→WiiM translation is forbidden.
3. Capability-driven — detect what each device supports rather than assuming.
4. Recoverability — automatic rollback on verification failure.

## Commands

The documented dev workflow runs in **WSL2 Ubuntu bash** (using `python3`/`pip3`).

```bash
# Targeted test (primary workflow during development — fast, ~5s)
python3 -m pytest src/tests/test_<module>.py -v --no-cov

# Multiple related files after touching shared code
python3 -m pytest src/tests/test_a.py src/tests/test_b.py --no-cov -q

# Lint / type check
python3 -m ruff check src/
python3 -m mypy src/translator src/models   # strict mode lives here
python3 -m mypy src/   # complete type check — zero-error gate, run before calling a task done

# Install deps (only if pyproject.toml changed)
pip3 install -e ".[dev]"

# Run the app
python packaging/entry_gui.py         # GUI
wiim-rew-sync list-devices            # CLI (see README for full command list)
```

**Full suite takes 10-20 min on WSL and will time out agent commands.** Never pipe pytest/ruff/mypy
output (`| tail`, `| grep`, etc.) — only run the full suite (`python3 -m pytest --no-header -q`) as
a final, optional gate, and expect it to time out even when everything passes (no `FAILED` lines =
treat as passing). GUI integration tests (`test_wizard_integration.py`, `test_gui_*.py`) are slow
(~25s each) — run the specific class/test you need, not the whole file.

Task completion gate (mandatory steps 1-3):
1. `pytest` for the touched module(s) passes
2. `ruff check src/` — zero errors
3. `mypy src/` — zero errors (translator/models additionally run under strict-mode overrides; see pyproject.toml)

**Known noise:** with coverage enabled, Qt-based tests (GUI pages, wizard controller, dialogs) show
`ERROR` during pytest-cov's SQLite combine step on WSL2's `/mnt/c/` filesystem. Not real failures —
they pass individually with `--no-cov`. Don't investigate; read the `X passed, Y failed` line only.

## Architecture

```
src/
├── adapters/     # WiiM HTTP adapter, REW HTTP adapter (network I/O)
├── translator/   # REW ↔ Canonical ↔ WiiM translation engine — stateless, ≥90% coverage required
├── models/       # pydantic domain models (CanonicalFilter is the hub)
├── repository/   # local JSON profile storage + backup manager
├── discovery/    # mDNS (zeroconf) then subnet-scan fallback
├── gui/          # PySide6 — pages (wizard steps), dialogs, components, panels, views
├── cli/          # CLI entry point (original proof-of-concept, still used for scripting)
├── logging/      # three rotating logs: app.log, wiim_api.log, rew_api.log
└── tests/        # flat, one test_<module>.py per module (no subdirectories)
```

- **Canonical model is the hub.** Every conversion goes REW→Canonical→WiiM or WiiM→Canonical→REW.
  Never translate REW directly to WiiM payloads or vice versa.
- **Adapters are injected via constructor** — enables mocking in tests; never instantiate an
  adapter inside business logic.
- **GUI has zero business logic.** No network calls or data manipulation in `src/gui/`; it only
  calls into translator/adapters/repository through a bridge.
- **Every device write follows the 5-step safety protocol** (full detail in
  [docs/architecture.md](docs/architecture.md)): Backup → Write → Read Back → Verify →
  Commit/Rollback. No exceptions.
- Phase status: Models/Translator, Network/Discovery, Adapters/Repository, and CLI proof-of-concept
  are complete and hardware-validated. GUI layer is built and under continuous hardware-backed QA;
  current status/counts live in [docs/backlog.md](docs/backlog.md)'s Hardware QA Sign-off item and
  [docs/smoke_test_issues.md](docs/smoke_test_issues.md) — check those rather than this line, which
  is deliberately not pinned to a snapshot date/count so it can't go stale the way it previously did.

## Code quality discipline

This codebase has a history of GUI pages accumulating business logic and of the same
parsing/validation/conversion logic getting reimplemented in more than one place. Before adding
code, actively guard against both:

- **Before adding logic to `src/gui/`** (pages, dialogs, components, views), ask: would this need
  Qt to test? If no, it belongs in `translator/`, `repository/`, `adapters/`, or `utils/`, and the
  GUI should call it through the bridge as a thin pass-through — not reimplement it inline.
- **Before writing a new helper, parser, or validation function, search for an existing one first**
  (`translator/`, `utils/`, `models/`). Duplicating logic that already exists elsewhere (e.g.
  re-parsing a field format, re-implementing a float-tolerance check instead of using
  `utils/fp_compare.py`) is the recurring smell in this codebase — extend or reuse, don't re-add.
- **After a non-trivial change, run `/code-review` or `/simplify` on the diff before calling the
  task done.** This is the concrete checkpoint for catching duplication, dead code, and
  over-engineered abstractions before they land.

## Domain rules (non-negotiable)

- **Never invent undocumented WiiM endpoints.** Only use what's in
  [docs/wiim_api_notes.md](docs/wiim_api_notes.md) or confirmed by the capability prober.
- **WiiM PEQ uses the LV2 EqNp plugin family** (`EQGetLV2BandEx`, `EQSetLV2Band`,
  `EQGetLV2SourceBandEx`, `EQSetLV2SourceBand`). Do not mix in the older `GetPEQBandsEx`/
  `SetPEQBandEx` family. Channel mode strings on the wire are exactly `"Stereo"` / `"L/R"`
  (`EQBand` vs `EQBandL`/`EQBandR`). JSON payloads must be URL-encoded before appending to
  `httpapi.asp?command=...`.
- **Never auto-select a REW measurement** — the user must explicitly pick one; always reference by
  UUID, never by index (index numbers are unstable). REW being unreachable is non-fatal: catch
  connection-refused and show "REW not connected", app keeps working via file import/export.
- **RoomFit is global** (applies to all inputs) — never show a per-source selector for it, even
  though the API takes a `source_name` param internally. **PEQ presets are also global** — a preset
  saved on one source can be loaded onto any source via `EQv2SourceLoad`.
- **Mark assumptions** with `# ASSUMPTION:` comments; log them in
  [docs/corrections.md](docs/corrections.md) if one later turns out wrong. If endpoint behavior is
  uncertain, stop, document it in corrections.md, add a `# TODO:`, set the capability flag to the
  safe/conservative value, and continue with only confirmed functionality.
- **Every GUI bug found during smoke testing must be logged to
  [docs/smoke_test_issues.md](docs/smoke_test_issues.md)** (row with issue #, description, status,
  test status). Fixing an issue or adding its regression test updates that same row's status in the
  same commit — never one without the other.
- **Every network call needs an explicit timeout (default 5s).** Never let a WiiM or REW HTTP call
  block indefinitely — see the existing pattern in `src/adapters/`.
- **Never reference WiiM/LinkPlay app internals in checked-in docs, comments, commits, or scripts** —
  no decompiled class/method names, smali paths, APK contents, or app UI/architecture. Findings go in
  as observed API behavior confirmed via hardware testing (`docs/corrections.md`), not as "found by
  decompiling X."
- **`docs/wiim_api_notes.md` is a spec, not a lab notebook.** State the current command/rule only —
  no test-campaign narrative, per-device iteration, or "previously believed X, revised to Y" framing.
  Investigation history, hypotheses, and hardware-test trails belong in `docs/corrections.md`;
  `wiim_api_notes.md` should only ever point at it (`docs/corrections.md`, `<date>`), never restate it.

## Common pitfalls

- ASCII hyphen `-` only — no en-dash/unicode minus (ruff RUF001-3).
- `caplog` needs `logger.propagate = True` around the assertion (loggers default to
  `propagate=False`); reset in `finally`.
- httpx exceptions are `httpx.TimeoutException` / `httpx.ConnectError`, not stdlib names.
- Strict-mypy modules (`src/translator/*`, `src/models/*`) want `dict[str, object]`, not bare `dict`.
- Hypothesis imports go at top of file, never mid-file (E402).
- **This codebase docstrings every public module/class/function** (existing convention, not
  enforced by lint) — match it on new public API even though the general default elsewhere is to
  skip comments.
- **GUI tests that mock `AsyncBridge.run_async` must close the coroutine they swallow.** Use
  `mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)`
  ([conftest.py:20](src/tests/conftest.py:20)) instead of a plain `MagicMock()` — otherwise the
  un-awaited coroutine triggers a "never awaited" `RuntimeWarning` only when garbage collected,
  which is often during an unrelated *later* test. Also explicitly `.close()` any window/dialog the
  test opens, so it doesn't stay alive past the test.
- **Any blocking modal (`QMessageBox`, a custom `QDialog.exec()`) will hang a test run until a
  human clicks it if a test path reaches it unmocked.** `QMessageBox.question/warning/critical/
  information` are auto-answered for every test by an autouse fixture
  ([conftest.py:62](src/tests/conftest.py:62), same pattern as `_suppress_unsaved_changes_dialog`
  right above it) — you don't need to mock these yourself unless a test cares about a specific
  answer (the No/decline branch, or asserting the dialog was/wasn't shown), in which case patch
  `PySide6.QtWidgets.QMessageBox.<method>` locally; it layers correctly over the fixture's default.
  **Custom `QDialog` subclasses are not covered by that fixture** (`QuickSetupDialog`,
  `DevicePickerDialog`, pickers, etc.) — each must still be mocked
  individually at its own static factory method (e.g. `QuickSetupDialog.get_setup`) in any test
  whose code path reaches it. If you add a new modal dialog and a test starts hanging (or a real
  window pops up during `pytest`), this is almost always the cause — extend the autouse fixture for
  a new `QMessageBox` method, or add the per-test static-method mock for a new custom dialog; don't
  work around it by clicking through it manually.

## Steering docs

[.kiro/steering/](.kiro/steering) has the full, unabridged versions of the above plus things you'll
rarely need: the complete numbered domain-rules list, workflow phase gates, and the parallel
sub-agent dispatch/collision-analysis rules for orchestrating multi-task waves. Read the relevant
one when a task touches that territory; don't load all four by default.
