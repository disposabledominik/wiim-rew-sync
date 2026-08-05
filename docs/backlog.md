# Backlog — Deferred Features & Tech Debt

Items moved here from active specs, or noted during code quality audits. Not planned for the
current release but may be reconsidered in future versions. Backend support may already exist
(noted per item).

Items are listed highest-priority-first (safety/correctness gaps, then infra/process gaps, then
low-priority tech debt). Each item's `## N.` number is a stable identifier, not a priority rank --
code comments, docstrings, and `docs/smoke_test_issues.md` rows cite items by this number (e.g.
"docs/backlog.md item 3"), so numbers are never reassigned even when an item's position in this
list changes as priorities shift. Reordered 2026-08-02; no numbers changed, item 6 added. Item 7
added 2026-08-05.

---

## 3. Multi-Source Push: No Automatic Rollback on Partial Failure (Known Limitation)

**What:** `PrimaryWorkflowManager._do_push()`'s PEQ flow writes to each of
`state.selected_sources` in sequence and aborts on the first failure. Each individual source's
write still goes through the full `SafeWrite` 5-step protocol — but if source N fails after
sources 1..N-1 already succeeded, there is no cross-source rollback: the already-written sources
are left in their new state. CLAUDE.md's design principles ("Safety before convenience" /
"automatic rollback on verification failure") read as applying at the whole-push level, not just
per-source, so this is a real gap, not just a UX rough edge.

**Why deferred:** Backup paths for all sources written before the failure are collected and
surfaced (smoke #242), so the *user* can undo each succeeded source with one click today — the
gap that remains is *automatic* rollback, not recoverability. Auto-invoking undo on sources 1..N-1
when source N fails risks a rollback-of-a-rollback failure and is a large enough decision (does a
failed auto-rollback also need its own critical-recovery UI?) to warrant its own design pass, so
it's still deferred.

**Status:** Partially addressed (smoke #242, `c132304`). `PushPage.set_failure()` now shows an
accurate "N source(s) not restored" message instead of the misleading "device safely restored"
line, and offers a one-click Undo for the sources that were actually written (via
`WriteResult.partial_backup_paths` + the existing multi-source undo path) — closing the
"document/expose the manual-undo path" option below. Automatic cross-source rollback is still not
implemented.

**To reactivate:** Decide whether automatic cross-source rollback is wanted on top of the current
one-click manual Undo, and how it should behave if that rollback itself fails. Implement in
`PrimaryWorkflowManager._do_push()`'s PEQ branch.

---

## 5. Operation Feedback: Overlapping Operations Can Race (Found via `/code-review ultra`)

**What:** `OperationFeedbackManager` (`src/gui/operation_feedback.py`) tracks exactly one
in-flight operation via a single `_is_active` flag and one `_prior_enabled` button-state
snapshot, both overwritten wholesale on every `start_operation()` call. If an operation is
cancelled (`_on_cancel_clicked()` calls `finish_operation()` immediately) while its underlying
coroutine keeps running in the background — since Cancel only resets the UI and does not
actually stop the coroutine — and a second, unrelated operation starts before that first
coroutine's `finally` block fires its own `operation_finished` signal, the stray late signal
calls `finish_operation()` again and restores buttons using the *second* operation's snapshot,
not the first's. This can re-enable or re-disable buttons out of step with what's actually
running.

**Why deferred:** Found during a `/simplify`/`/code-review ultra --fix` cleanup pass on an
unrelated diff (smoke `docs/smoke_test_issues.md` #243/#244); fixing it properly touches two
separate concerns — (a) giving each `start_operation()` call an identity (a token returned by
`start_operation()` that `finish_operation(token)` must match to actually apply, so a
stale/mismatched call is a no-op) and (b) the more fundamental gap that Cancel doesn't cancel
the underlying coroutine at all, which a token-based fix would paper over rather than resolve.
Both are design decisions bigger than a quality-cleanup pass's scope, and the app's current
one-op-at-a-time model means this is a narrow race window in practice, not a routinely-hit bug.
Independently re-confirmed (still unfixed) during a 2026-08-02 codebase review.

**Status:** Not started.

**To reactivate:** Add an opaque operation token to `start_operation()`'s return value and
require `finish_operation(token)` (and the hard-timeout path) to match it before restoring
button state — a mismatched/stale token means a no-op. Separately, decide whether Cancel should
actually cancel the in-flight coroutine (e.g. via `asyncio.Task.cancel()` plumbed through
`AsyncBridge`) rather than only resetting the UI early.

---

## 6. CI Test Matrix: Single OS/Python Version Tests a 3-Platform Release (Found During Codebase Review)

**What:** `.github/workflows/ci.yml`'s `lint-type-test` job runs on `ubuntu-latest` with Python
3.12 only — no `strategy.matrix`. `.github/workflows/release.yml` builds and ships PyInstaller
binaries for Windows, macOS, and Linux from a `vX.Y.Z` tag, and `pyproject.toml` sets no upper
Python bound. So two of the three shipped platforms (Windows, macOS), and any Python version
above 3.12 a user's environment might resolve to, get zero automated test coverage before a
release build is cut — only the Linux/3.12 combination is verified by CI.

**Why it matters:** Platform-specific bugs (path separators, `QFileDialog` behavior, subprocess
calls like `settings_view.py`'s `/usr/bin/open` vs `/usr/bin/xdg-open` branch) can only be caught
by hardware/manual QA today, and `docs/backlog.md` item 1 already notes only the Windows build has
been hardware-verified so far — macOS and Linux builds currently ship on test coverage from a
different OS entirely.

**Why deferred:** Each additional matrix entry adds real CI minutes and maintenance (GUI tests
need `QT_QPA_PLATFORM=offscreen` plus platform-specific Qt runtime libs, as `ci.yml` already
installs for Ubuntu); a full 3-OS x N-Python matrix is likely overkill for a solo/small-team
project's PR-gate CI. Not a bug fix — a deliberate infra-investment tradeoff to make once, not
something to bolt on reactively per PR.

**Status:** Not started.

**To reactivate:** Add at least one non-Linux `strategy.matrix` entry (e.g. `windows-latest`,
mirroring the Qt-offscreen/library-install steps `release.yml` already uses for that OS) to
`lint-type-test`, rather than a full matrix — enough to catch a platform-specific regression
before a tag build, without multiplying CI cost per entry added.

---

## 4. Backup Files Have No Source Identifier (Found During PR Review)

**What:** `BackupManager.create_backup()` takes a `PEQSettings` (which carries `source_name`), but
never persists that source name anywhere in the resulting `BackupRecord` — `name` is
`backup_{device_uuid}_{timestamp}`, and the file itself is named only `{timestamp}.json` under a
per-device-UUID directory (`backup_manager.py`). Nothing in the filename or JSON content ties a
backup to the source it was taken from.

**Why it matters:** The CLI's `restore-backup` command (smoke #241) requires `--source` as a
separate argument precisely because the backup file can't supply it. In practice this only works
reliably when restoring from the exact path the app just printed on a failure. Browsing the backup
directory later — e.g. to pick the right file among several from a partial multi-source failure
(smoke #242) — gives no way to tell which backup belongs to which source.

**Why deferred:** A schema change (`BackupRecord` gaining a `source_name` field, or the filename
being stemmed with it) needs migration handling for existing backup files on users' machines, and
is out of scope for the PR that surfaced it. Not blocking, since the current callers (GUI Undo,
CLI `restore-backup`) always have the source name available from elsewhere when they need it.

**Status:** Not started.

**To reactivate:** Add `source_name: str | None` to `BackupRecord` (optional, so old backup files
without it still validate), have `create_backup()` populate it from `settings.source_name`, and
consider stemming the filename with it too for at-a-glance browsing. Update `restore-backup` to
default `--source` from the backup file when present, keeping the flag for older files.

---

## 1. Hardware QA Sign-off

**What:** Full-flow validation against real WiiM device(s) covering GUI-era scenarios that can't
be automated (multiroom groups, RoomFit push with naming, device reboot mid-write, etc.) — see
`docs/qa_signoff.md` §5.

**Status:** Kept open at the device owner's request. `docs/qa.md`, the pre-GUI `docs/qa_signoff.md`,
and `docs/smoke_test_procedure.md` have been consolidated into one current `docs/qa_signoff.md`
(manual QA & sign-off guide, automated-gate checklist, scenario traceability matrix). One
genuinely `OPEN` issue remains in `docs/smoke_test_issues.md` (#119, an intermittent
window-restore-from-maximized clipping bug — low severity, needs a consistent repro); the
automated suite is at 1500+ tests across 60 files.

**To reactivate:** Close out #119 and formally fill in `docs/qa_signoff.md`'s sign-off form with
current test counts/coverage.

---

## 2. Shared Base/Mixin for "Optional Embedded Warning" Dialogs (Tech Debt)

**What:** `DevicePickerDialog` and `QuickSetupDialog` each independently carry an optional
`warning: tuple[str, str] | None` constructor param. The shared "build a warning box" logic is
already extracted (`src/gui/components/warning_box.py`, `add_optional_warning_box()`), but the
`warning` param itself, its docstring, and the `setMinimumWidth(420 if warning else ...)`
width-bump convention are still hand-duplicated in each dialog's `__init__`/static factory.

**Why deferred:** Only two dialogs need this pattern; a third would justify extracting a shared
base (`WarningDialogBase`/`OptionalWarningMixin`) with real confidence about the right shape.

**Status:** Not started. Low priority, low risk (remaining duplication is boilerplate, not
behavior).

**To reactivate:** If a third dialog needs an embedded optional warning, extract a shared
`__init__`-level mixin/base covering the `warning` param, docstring, and width-bump logic, and
migrate `DevicePickerDialog`/`QuickSetupDialog` onto it at the same time.

---

## 7. No Confirmation Prompt Before Change-Time Checkmark Invalidation (UX Decision)

**What:** Since the `#246` Stage 2 lazy-invalidation redesign (PR #20), changing an earlier answer
(picking a different EQ type, or a different source set / channel mode) silently invalidates the
downstream steps' checkmarks -- and, for an EQ-type switch, also clears the loaded filter payload --
with no confirmation prompt. Only a *device* switch with unpushed filter work prompts
(`_confirm_device_switch`, smoke `#248`/`#249`), because that is the one change that destroys real
payload plus device-scoped state rather than mostly checkmarks.

**Why deferred:** Deliberately scoped out of PR #20 (its review's decision R7): the EQ-type/source
handlers destroy little of value (re-checking a step is cheap; filters survive a source change),
and prompting on every changed answer would make ordinary corrections feel heavyweight. Whether the
EQ-type switch specifically deserves a prompt (it *does* clear loaded filters) is a UX judgment
call best made after real-world use.

**Status:** Not started. Low priority.

**To reactivate:** If users report losing loaded filters to an accidental EQ-type switch, add a
confirmation prompt to `_on_eq_type_selected` gated on the same "unsaved work" predicate as the
device-switch prompt (`_has_unsaved_changes`), reusing the existing `QMessageBox.question`
pattern. Source/channel changes should stay prompt-free (nothing but checkmarks is lost).

---

## Completed / Closed Items (Archive)

### CI Release Pipeline (No Published Download Path)
**Completed.** `.github/workflows/ci.yml` runs ruff/mypy/pip-audit/pytest on every PR and on
pushes to `development`; `.github/workflows/release.yml` builds the three PyInstaller targets on
their respective OS runners on a `vX.Y.Z` tag push and attaches them, plus `SHA256SUMS.txt`, to a
draft GitHub Release. `README.md`'s Getting Started section links the published downloads directly,
and `docs/release_process.md` documents the cut-a-release checklist. Remaining known gap: macOS
builds are unsigned (Gatekeeper workaround documented in `packaging/README.md`), and only the
Windows build has been hardware-verified so far.

### MainWindow God-Object — Extract Business Logic from GUI Layer (Tech Debt)
**Completed:** 2026-07-19. `src/gui/main_window.py` shrank from ~4,739 to 3,760 lines. All
originally-flagged `_do_*` business-logic methods (network I/O / data manipulation that had been
living in the GUI layer, against CLAUDE.md's "no network calls or data manipulation in GUI
components") moved out to `PrimaryWorkflowManager`/`SecondaryWorkflowManager`
(`src/gui/primary_workflows.py`/`secondary_workflows.py`), following the existing manager pattern:
injected factories via `configure()`, completion signals, no direct Qt widget access. This
included the higher-risk safety-critical group (`_do_push`, undo, copy-to-device) that was
originally deferred pending a dedicated effort — that effort happened, preceded by a 4-pass
adversarial plan review. `src/gui/shared_helpers.py` was deleted, its logic redistributed into
`models/`/`repository/`/`translator/`. A `src/gui/adapter_factories.py` module now owns all direct
adapter instantiation, enforced by a repo-wide grep-guard test. A subsequent multi-round
`/code-review ultra` pass (see PR #1 for full discussion; commits `dc72487`, `a02b55f`, `128e0df`,
`fe87a06`) found and fixed a family of empty-L/R-channel bugs spanning `write_peq`/`write_roomfit`/
push/copy paths (an empty-but-present channel must be honored as "no filters for that channel" at
read/rollback boundaries, but rejected at push/write-intent boundaries — the two were previously
conflated), plus DI-surface, dead-code, and duplication cleanups
(`resolve_channel_split()`/`resolve_roomfit_channel_kwargs()` centralizing L/R-split handling,
`ProfileRepository.rename()`'s case-sensitivity fix, `encode_multi_source_backup_paths()`, and
others). No further extraction phases are planned; `docs/corrections.md` has the hardware-relevant
findings from this effort (e.g. the removed "mini"-substring RoomFit fallback, 2026-07-18 row).
A 2026-08-02 codebase review found and fixed one further leak (`main_window.py`'s
`_on_local_preset_copy_to_device_requested()` calling `build_peq_settings()`/`extract_filters()`
directly instead of delegating to `SecondaryWorkflowManager` -- that validation logic now lives in
`_do_copy_local_profile_to_devices()` instead).

### Adapters Instantiated Directly in `main_window.py` (Tech Debt)
**Completed:** 2026-07-17. 4 sites in `main_window.py` called
`WiiMHttpClient(...)`/`CapabilityProber(...)`/`WiiMAdapter(...)`/`REWHttpApiClient()` directly,
against CLAUDE.md's constructor-injection rule. Fixed via `src/gui/adapter_factories.py` plus 4
constructor-injected factory params on `MainWindow.__init__`, with a grep-based guard test
(`test_gui_adapter_injection.py`) failing CI if anything outside `adapter_factories.py`
instantiates these classes directly.

### `ProfileRepository.list()` Shadows Builtin (Tech Debt)
**Completed:** 2026-07-14. Renamed to `list_all()`, removing the `import builtins` workaround.

### PEQ / RoomFit Enable/Disable Toggle in GUI
**Closed:** 2026-07-14. Explicit product decision (2026-07-02) not to build it — the WiiM Home app
already covers this. Backend support remains available if reactivated:
`WiiMAdapter.enable_peq()`/`disable_peq()`/`get_peq_enabled()` and CLI `peq-toggle` are
implemented; the RoomFit DSP toggle (`EQChangeSourceFX`/`EQSourceOff` at `EQLevel:2`, empty
`source_name`) is hardware-confirmed but not wired into `WiiMAdapter`/GUI.

### HP/LP Capability Detection and Write-Time Validation
**Closed:** 2026-07-14. The functional problem (warning/skipping unsupported filter types at write
time) is already solved by `DeviceCapabilities.supported_filter_types`
(`src/models/capabilities.py`) and `validate_filters_for_device()`. Only *dynamic runtime probing*
for a not-yet-catalogued no-HP/LP device remains undone — revisit if such a device appears.

### Profile Comparison & Diffing
**Closed:** 2026-07-14. Future-phase feature, not MVP, no active demand. Revisit if requested.

### Advanced Filter Types
**Closed:** 2026-07-14. All-Pass filters and specialized shelf variants are blocked on WiiM
firmware support that doesn't exist yet. Revisit if WiiM ships new filter types.

### On-Device Preset/Profile Rename via `EQv2Rename`
**Closed:** 2026-07-14. No user request; the existing save-as-new+delete-old workaround covers the
need. `EQv2Rename` is hardware-confirmed working (`docs/corrections.md`, 2026-07-10) for both PEQ
presets and RoomFit profiles if reactivated.

### Packaged `.exe` Shows a Brief Window Flash on Launch
**Closed:** 2026-07-14. Root cause understood (PyInstaller onefile build extracts the bundled
runtime to a temp folder on every launch); the only fix (onedir build) was explicitly declined by
the device owner (2026-07-11) in favor of a single portable `.exe`. Revisit only if reconsidered.

### Rethink Source Discovery
**Completed:** 2026-07-04, shipped in commit `6bc189d`. `getAudioInputEnable` returns each input's
real `source_name` plus an enabled/shown flag, correctly excluding non-addressable entries.
`CapabilityProber._probe_source_names()` uses this directly; devices without it (WiiM Mini) fall
back to the existing per-model capability table.

### RoomFit DSP Toggle — API Investigation
**Completed:** 2026-07-02. `EQChangeSourceFX`/`EQSourceOff` at `EQLevel:2` toggle RoomFit when
`source_name` is the empty string (not omitted or populated). Confirmed round-trip against real
hardware (`docs/corrections.md`, 2026-07-02).

### Backward-Compat `ValidationError` Re-export in wiim_parser
**Completed:** 2026-06-28. Removed the dead re-export from `src/translator/wiim_parser.py` after
confirming zero real importers.

### Test coverage for hardware-testing findings
**Completed.** Automated tests added for all API behaviors discovered during manual hardware
validation.

### Channel Mode Enum
**Completed:** 2025-07-01. Introduced `ChannelMode` enum (`src/models/channel_mode.py`) with
`STEREO`/`LR` values and `wire_value`/`profile_value`/`display_value`/`is_lr` properties; replaced
38+ string comparison sites across 15 files.

### Remove Redundant `state.current_filters` for L/R Mode
**Completed:** 2025-07-01. Added a computed `WizardState.filters` property combining
`filters_l`/`filters_r` in L/R mode, eliminating desync risk.

### Dark/Light Style Consolidation
**Completed.** Refactored dark and light styles for consistency; removed unnecessary inline
styles.
