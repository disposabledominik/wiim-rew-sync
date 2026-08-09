# CLAUDE.md

All work happens on the `development` branch unless a different branch is explicitly named.
PRs target `development`; `main` only receives merges from `development` before cutting a release.

## Project

WiiM ↔ REW PEQ Sync Tool — a local-first desktop app (PySide6 GUI + CLI) that transfers parametric
EQ (PEQ) and RoomFit filter configs between Room EQ Wizard (REW) and WiiM devices on the LAN. No
cloud, no telemetry, no accounts.

Design principles that drive most design decisions in this codebase:
1. Safety before convenience — never write to a device without backup and verification.
2. All data flows through the Canonical Filter Model — direct REW→WiiM translation is forbidden.
3. Capability-driven — detect what each device supports rather than assuming.
4. Recoverability — automatic rollback on verification failure.

## Commands

Dev workflow runs in **WSL2 Ubuntu bash** (`python3`/`pip3`).

```bash
python3 -m pytest src/tests/test_<module>.py -v --no-cov     # targeted test, ~5s — primary workflow
python3 -m ruff check src/
python3 -m mypy src/                        # zero-error gate
python3 -m mypy src/translator src/models   # strict mode (pyproject.toml overrides)
```

**Never pipe pytest/ruff/mypy output.** Full suite (`pytest --no-header -q`) takes 10-20 min on WSL
and will time out agent commands — run it only as a final, optional gate; absence of `FAILED` lines
means it passed. Qt-based tests show spurious `ERROR` during pytest-cov's SQLite combine step on
WSL2's `/mnt/c/` filesystem — not real failures, don't investigate; they pass individually with
`--no-cov`.

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

Adapters are injected via constructor — never instantiated inside business logic. Every device
write follows the 5-step safety protocol (full detail in `docs/architecture.md`): Backup → Write →
Read Back → Verify → Commit/Rollback. No exceptions.

## Before writing any code

1. **Search before building.** Before writing any helper, parser, validator, conversion, or UI
   pattern: grep `src/translator/`, `src/utils/`, `src/models/`, `src/adapters/`,
   `src/gui/components/`. Reuse and consolidate code rather than reinvent.

2. **Check the layer.** Logic that doesn't require Qt to test belongs in `translator/`,
   `repository/`, `adapters/`, or `utils/`, not `src/gui/` — GUI is a thin pass-through through
   the bridge.

3. **Read existing examples first.** For any new GUI element, read at least two existing examples
   of the same type before writing a line.

4. **When changing a cross-cutting convention, update everything that assumes the old one in the
   same commit.** grep `docs/`, `scripts/`, CI workflows, tests.

## Before calling a task done

Re-run the gate (Commands, above) on the touched module(s) with fresh evidence — targeted pytest,
`ruff check src/`, `mypy src/` — all passing, zero errors. Not "should still pass"; actually run it.

**After a non-trivial change, also run `/code-review` or `/simplify` on the diff** — the concrete
checkpoint for catching duplication, dead code, and over-engineered abstractions before they land.

**After any non-trivial change, also ask:**
- Did I fix the root cause, or a symptom? If the same class of bug could exist at another call
  site, grep for all of them and fix them now.
- Does anything in `docs/`, tests, or other code now assume behavior I just changed?
- Do any documents, including the in-app User Guide, need to be updated?

**After any session that renames, moves, or deletes something structural** (a module, helper,
pattern, or named symbol referenced in `CLAUDE.md`): run `/update-claude-md` and address any
findings before closing the session.

**After a smoke test session that surfaces a recurring problem, or every ~5 PRs:** run
`/review-claude-md` for a fuller check covering stale references, missing rules, and redundant
rules.

## Fixing a bug

1. **Audit the full category, not just the reported instance.** Grep for every call site in the
   same structural class (e.g. every place that calls `write_roomfit()`, every navigation path that
   calls `setCurrentIndex()`).

2. **Fix the root cause.** A third instance of the same bug is a signal to add a structural guard:
   a scan-based test, a runtime assertion in a central helper, or a single required code path.
   `TestNoDirectWriteBypass` (`test_safe_write.py`) is the model for this.

3. **Check all parallel flows.** A fix that covers the wizard push path must also cover: CLI
   commands, Copy to Another Device, Presets on Device sidebar actions, Undo, and any other
   relevant paths.

## Writing tests

A test must assert a specific output or side effect and cover at least one failure path — checking
only that a function exists, doesn't raise, or accepts valid input isn't enough.

**Regression tests** must reproduce the specific hardware-observed condition. A test that would
have passed *before* the bug is not a regression test. For multi-path bugs, add a scan-based test
that catches future bypasses automatically rather than writing N nearly-identical per-site tests.

Assert the right thing:
- Layout jitter: assert real on-screen geometry (`widget.pos().y()`), not `sizeHint()`.
- L/R correctness: assert per-channel content at distinguishable frequencies, not just list length.
- Call verification: assert parameter values and call order, not just that a mock was called.

**GUI test patterns:**
- Mock `AsyncBridge.run_async` using `close_coroutine_tree` from `conftest.py`, not plain
  `MagicMock()`. Un-awaited coroutines produce `RuntimeWarning` in unrelated later tests.
- Explicitly `.close()` every window opened during a test.
- `QMessageBox` methods are auto-answered by the autouse fixture. Custom `QDialog` subclasses
  are not — mock their static factory method individually. Hanging test = unmocked modal.
- `caplog` requires `logger.propagate = True`; reset in `finally`.

## Domain rules

- **Canonical model only.** REW→Canonical→WiiM and WiiM→Canonical→REW. No direct translation.
- **Every device write: Backup → Write → Read Back → Verify → Commit/Rollback. No exceptions.**
  Any call to `adapter.write_peq()` or `adapter.write_roomfit()` outside `safe_write.py` violates
  this. `TestNoDirectWriteBypass` enforces it in CI.
- **Never invent undocumented WiiM endpoints.** Only use what's in `docs/wiim_api_notes.md` or
  confirmed by the capability prober.
- **WiiM PEQ uses the LV2 EqNp plugin family** (`EQGetLV2BandEx`, `EQSetLV2Band`,
  `EQGetLV2SourceBandEx`, `EQSetLV2SourceBand`). Do not mix in the older `GetPEQBandsEx`/
  `SetPEQBandEx` family. Channel mode strings on the wire are exactly `"Stereo"` / `"L/R"`
  (`EQBand` vs `EQBandL`/`EQBandR`). JSON payloads must be URL-encoded before appending to
  `httpapi.asp?command=...`.
- **PEQ storage is per-source; PEQ presets are global.** Each source has independent PEQ filter
  storage per mode (stereo or L/R), but a preset saved on one source can be loaded onto any source
  via `EQv2SourceLoad`.
- **RoomFit is global.** A single buffer, not per-source. Never show a per-source selector for it.
- **`source_name` and `EQLevel` are not symmetric across command families.** Consult the
  `source_name & EQLevel Reference` table in `docs/wiim_api_notes.md` before writing any new
  RoomFit call site. Use `encode_wiim_command()` in `wiim_commands.py` — it enforces correct form.
- **Any probe or write-back-unchanged operation that touches a source's bands or buffer must
  capture and restore `Name` and `EQStat` afterward.** A raw band write, even with byte-identical
  content, drops the source's `Name` association. An `EQv2SourceLoad` unconditionally turns
  `EQStat` on. See `WiiMAdapter.restore_roomfit_selection_and_enable_state()` and
  `read_peq_preset_preview()` for the reference implementations.
- **Never auto-select a REW measurement.** User picks explicitly; reference by UUID only. REW
  unreachable is non-fatal — show "REW not connected", keep working via file import.
- **Every network call: explicit timeout (default 5s).** No indefinite blocking.
- **Mark uncertain behavior** with `# ASSUMPTION:`, log in `docs/corrections.md`, set capability
  flag conservatively, add `# TODO:`, proceed with only confirmed behavior.
- **Every hardware-detected GUI bug goes in `docs/smoke_test_issues.md`** (issue #, description,
  status, test status). Fix and regression test update the same row in the same commit.
- **Never reference WiiM/LinkPlay app internals in checked-in docs, comments, commits, or scripts**
  — no decompiled class/method names, smali paths, APK contents, or app UI/architecture. Findings
  go in as observed API behavior confirmed via hardware testing (`docs/corrections.md`), not as
  "found by decompiling X."

## Common pitfalls

- ASCII hyphen only — no en-dash/unicode minus (ruff RUF001-3).
- httpx exceptions: `httpx.TimeoutException` / `httpx.ConnectError`, not stdlib names.
- Strict-mypy (`src/translator/*`, `src/models/*`): `dict[str, object]`, not bare `dict`.
- Hypothesis imports: top of file, never mid-file (E402).
- Every public module/class/function gets a docstring — convention, not enforced by lint.
- Round all filter values to 3 decimal places before writing to a device. Use `fp_compare.py`
  tolerances (not exact equality) when verifying read-back values.
