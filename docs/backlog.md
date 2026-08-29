# Backlog — Deferred Features & Tech Debt

Items moved here from active specs, or noted during code quality audits. Not planned for the
current release but may be reconsidered in future versions. Backend support may already exist
(noted per item).

Items are listed highest-priority-first (safety/correctness gaps, then infra/process gaps, then
low-priority tech debt). Each item's `## N.` number is a stable identifier, not a priority rank --
code comments, docstrings, and `docs/smoke_test_issues.md` rows cite items by this number (e.g.
"docs/backlog.md item 3"), so numbers are never reassigned even when an item's position in this
list changes as priorities shift. Reordered 2026-08-02; no numbers changed, item 6 added. Item 7
added 2026-08-05. Item 8 added 2026-08-29. Item 5 archived 2026-08-29 (resolved 2026-08); its
number was kept, not reused, since it's cited by number outside this file. Items 9-10 added
2026-08-29. Item 1 archived 2026-08-29 (QA sign-off completed).

**At a glance** (priority order; full detail in each item below):

| # | Item | Status |
|---|------|--------|
| 3 | Multi-source push has no automatic rollback across sources on partial failure (manual per-source Undo exists) | Implemented (2026-08-29); manual hardware retest pending |
| 9 | Push page doesn't update its main-view card on a device connection failure; only a status banner shows it | (a) Implemented (2026-08-29); (b) not started |
| 6 | CI only tests Ubuntu/Python 3.12 while release builds ship Windows/macOS/Linux | Not started |
| 4 | Backup files don't record which source they were taken from | Not started |
| 2 | `DevicePickerDialog`/`DeviceInfoDialog` duplicate their optional-warning boilerplate | Not started |
| 7 | No confirmation prompt when switching EQ type clears loaded filters | Not started |
| 8 | Profile JSON's `channel_mode: "left"` sentinel is a misleading name for L/R mode | Not started |
| 10 | Candidate list: activate/rename/enable-toggle actions for "Presets on Device" (speculative, not committed) | Not started |

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

**Status:** Implemented (2026-08-29). `PrimaryWorkflowManager._do_push()`'s PEQ loop now
auto-rolls-back the already-succeeded sources when a later source fails, via a new shared
`restore_entries()`/`restore_one()` pair in `safe_write.py` — the same primitive
`SecondaryWorkflowManager._do_undo_multi_source()` (manual Undo) now also calls, so the two paths
can't drift apart. `WriteResult.partial_sources`/`partial_backup_paths` were repurposed (not
duplicated) to mean "sources whose own auto-rollback failed and still need manual action" rather
than "all N-1 prior successes" — auto-rollback succeeding for all of them now correctly hides the
Undo button instead of always offering it. A new `auto_rollback_attempted` field lets
`PushPage.set_failure()` distinguish "fully auto-restored," "partially auto-restored, Undo covers
the rest," and the original "nothing to roll back yet" cases. Progress during the rollback
sub-loop reuses the existing `push_round_changed` signal and `PushPage._rollback_mode` flag
(no new signal needed) rather than `start_undo()`'s badge/stepper-reset, since this happens inside
an in-progress push, not a separate run. Automated tests: `TestRestoreOne`/`TestRestoreEntries`
(`test_safe_write.py`), extended `TestPushMultiSourcePartialFailure`
(`test_gui_push_export.py`), new `PushPage.set_failure()`/`set_push_round()` UI-state tests
(`test_gui_pages.py`), and the pre-existing `_do_undo_multi_source` characterization suite
(`test_smoke_regression_operations.py`, `test_gui_integration_secondary.py`) all pass unmodified
in behavior, now backed by the shared primitive. **Manual hardware retest still required** (a real
mid-rollback connection drop can't be simulated in CI) — see docs/backlog.md item 1's
hardware-QA-owner convention.

**To reactivate:** N/A — implemented. If a future review finds the rollback-of-a-rollback UX
(critical message naming the specific source whose auto-rollback failed) needs refinement, start
from `PrimaryWorkflowManager._finalize_push_failure()`.

---

## 9. Push Page's Main Card Doesn't Reflect a Device Connection Failure (Found During Q&A)

**What:** Two related gaps in how `PushPage` (`src/gui/pages/push_page.py`) surfaces push
failures, found while scoping a user-reported UX complaint:

- **(a) Connection failure during push never reaches the main card.** `PrimaryWorkflowManager
  ._do_push()` deliberately does not wrap `SafeWrite.execute()` in try/except (comment at
  `primary_workflows.py:1526-1536`: connection-drop exceptions "propagate to `_bridge_wrapper`
  unchanged"), and `SafeWrite.execute()` itself (`safe_write.py:248-328`) has no try/except around
  its read/write steps either. So a `WiiMConnectionError`/timeout mid-push propagates straight out,
  is caught by `MainWindow._bridge_wrapper`'s catch-all (`main_window.py:2373-2380`), mapped to a
  message, and shown only via `StatusBanner.show_error()` (`src/gui/components/status_banner.py`)
  — the app's toast/status-bar equivalent. `write_complete` is never emitted in this path, so
  `PushPage.set_failure()` never runs. The page's stage stepper (`PushPage.set_stage()`,
  `push_page.py:135-164`) stays frozen on whichever step ("Backing up"/"Writing"/"Verifying") was
  active when the connection dropped, rendered as permanently "active" with no failure indication,
  while the actual error only appears in the separately-dismissible status banner. This is
  currently tested-as-intended, not an accidental gap:
  `TestPushException.test_push_exception_emits_operation_error`
  (`src/tests/test_gui_push_export.py:319-337`) asserts only `operation_error` fires here.
- **(b) Partial multi-source failure summary is a count, not a per-source list.**
  `PushPage.set_failure()` already shows "N source(s) not restored" (see item 3 above for the
  broader rollback gap this is part of), but not which sources succeeded/failed by name — even
  though `encode_multi_source_backup_paths()` already encodes `(source_name, path)` pairs; they're
  decoded only for the Undo action, not for display.

**Why it matters:** A user watching a push that fails on a connection drop sees a stuck-looking
progress stepper in the main view and has to notice/read a separate banner to learn what actually
happened and that the operation is over — confusing, since the main content area is the natural
place to look for the outcome of what it was just showing progress for.

**Why deferred:** (b) not started; surfaced during a 2026-08-29 Q&A/backlog-scoping session, not
yet scheduled.

**Status:** (a) Implemented (2026-08-29). `_do_push()`'s PEQ loop now catches
`WiiMConnectionError`/`WiiMResponseError`/`BackupError` around the `safe_write.execute()` call
(narrow domain-exception catch, mirroring `SafeWrite._rollback()`'s own precedent, not a blanket
`except Exception` — an unexpected bug still surfaces via `_bridge_wrapper`'s traceback logging)
and routes the failure through `_finalize_push_failure()` (the same shared method item 3's
auto-rollback uses) so `write_complete` fires and `PushPage.set_failure()` runs instead of leaving
the stepper frozen. A new `WriteResult.verified` field (default `True`) fixes a correctness issue
found while implementing this: the non-critical failure branch used to unconditionally claim
"device safely restored," which was only ever true for the two pre-existing cases reaching it
(rollback ran and succeeded, or nothing was ever written) — a connection-drop-mid-write is a third
case where the device's actual state is genuinely unknown, so `set_failure(verified=False)` now
shows "device state unknown" instead. A 2026-08-29 code review (PR #37) found two follow-on gaps
in this same change, both fixed in the same PR: (1) `set_failure()`'s `elif` chain checked
`partial_sources`/`auto_rollback_attempted` before `not verified`, so on a multi-source push where
a prior source's own auto-rollback outcome was also nonzero, the current failing source's
`verified=False` signal was silently swallowed — fixed by appending an "unconfirmed, state
unknown" caveat to those branches' detail text instead of treating `verified` as its own exclusive
branch. (2) RoomFit's `except Exception` block was *not* actually already correct as first
claimed — it built `WriteResult` without `verified=False`, so a RoomFit connection drop still
showed "device safely restored." Both fixed; the RoomFit regression test now asserts
`emitted.verified is False` instead of only `success`/`error_message`. A follow-up `/code-review
ultra` pass on that fix found two more small gaps, also fixed in the same PR: (3) the fully-
auto-restored branch (`auto_rollback_attempted > 0`, `partial_sources == 0`) showed this failing
source's own backup path via `_backup_path_label` with no confirming text explaining it, unlike
every other branch that shows a backup path — fixed by appending the same "safely restored"
confirmation used elsewhere, only when this source's own backup actually exists. (4) `restore_one()`
(the extraction that replaced `_restore_backup()`'s inline logic) dropped the pre-existing
`logger.info` confirmation on a successful restore — restored, reworded to match the shared
primitive's existing failure-log wording. The duplicated "state unknown" caveat text (two call
sites) was also hoisted into one class constant. Automated tests: `TestPushConnectionFailure`
(`test_gui_push_export.py`), `PushPage.set_failure(verified=False)` UI-state tests including the
two swallowed-signal cases and the backup-path-confirmation cases (`test_gui_pages.py`),
`TestRestoreOne::test_undo_success_logs_confirmation` (`test_safe_write.py`). **(b) still not
started** — `set_failure()` still shows a
count ("N source(s)...") rather than per-source names; `partial_backup_paths` is decoded only for
the Undo action. **Manual hardware retest required for (a)** (a real mid-write connection drop
can't be simulated in CI) — see docs/backlog.md item 1's hardware-QA-owner convention.

**To reactivate:** (a) is done. For (b), decode `partial_backup_paths` in `set_failure()` and
render source names instead of just a count — small, GUI-only.

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

## 2. Shared Base/Mixin for "Optional Embedded Warning" Dialogs (Tech Debt)

**What:** `DevicePickerDialog` and `DeviceInfoDialog` each independently carry an optional
warning constructor param (`warning: tuple[str, str] | None` and `warning_text: str`
respectively). The shared "build a warning box" logic is already extracted
(`src/gui/components/warning_box.py`, `add_optional_warning_box()`), but the param itself, its
docstring, and the `setMinimumWidth(420 if warning else ...)` width-bump convention are still
hand-duplicated in each dialog's `__init__`/static factory. (`QuickSetupDialog`, a third former
consumer of this same pattern, was removed as part of the Filters-step source-dropdown redesign
that eliminated its only remaining callers — back down to the original two dialogs.)

**Why deferred:** Only two dialogs need this pattern; a third would justify extracting a shared
base (`WarningDialogBase`/`OptionalWarningMixin`) with real confidence about the right shape.

**Status:** Not started. Low priority, low risk (remaining duplication is boilerplate, not
behavior).

**To reactivate:** If a third dialog needs an embedded optional warning, extract a shared
`__init__`-level mixin/base covering the warning param, docstring, and width-bump logic, and
migrate `DevicePickerDialog`/`DeviceInfoDialog` onto it at the same time.

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

## 8. Profile JSON `channel_mode: "left"` Sentinel Is a Misleading Name (Found During Q&A)

**What:** `ChannelMode.profile_value` (`src/models/channel_mode.py`) serializes L/R-mode profiles
with `"channel_mode": "left"` in the on-disk Profile JSON -- not `"lr"` or `"L/R"`. `"right"` is
also accepted on read as an equivalent legacy alias. Both predate this repo's tracked git history
(present already in the root commit, before the `ChannelMode` enum consolidated the scattered
string comparisons around it) and there is no recorded rationale for the choice.

**Why it matters:** Read cold -- by a new contributor, or in a saved preset file a user opens --
`"left"` reads as "this is the left channel," not "this profile has both L and R channels." Purely
a naming/readability issue; the current value round-trips correctly and no functional bug is known.

**Why deferred:** Low priority, no user-facing symptom. `"left"` is baked into every profile a user
has already saved to disk, so `from_profile`/`from_any` would need to keep accepting it as a legacy
read value indefinitely regardless of what the write side changes to -- this is a rename, not a bug
fix, and the payoff (readability) doesn't yet outweigh the churn of touching test literals for no
behavior change.

**Status:** Not started.

**To reactivate:** Change `ChannelMode.profile_value`'s `LR` branch to a clearer literal (e.g.
`"lr"`), keeping `"left"`/`"right"` accepted in `from_profile`/`from_any` as legacy read-only
aliases. Expected footprint (~25-30 lines, mostly test literals, confirmed by grep 2026-08-29):
`src/models/channel_mode.py` (profile_value + docstrings, ~6-8 lines); tests --
`test_models.py` (7), `test_profile_repository.py` (2), `test_wiim_adapter.py` (2),
`test_safe_write.py` (1), `test_smoke_regression_operations.py` (7); `docs/data_models.md` (~6
lines, sections 198-199/252/265/280). `src/cli/main.py`'s `--channel left/right` flag,
`wiim_adapter.py`, and `wiim_parser.py` are a separate "which channel" vocabulary that maps into
`ChannelMode` rather than storing the literal string, and are unaffected.

---

## 10. Candidate List: "Presets on Device" Activate/Rename/Enable-Toggle Actions (Speculative — Not Committed)

**What:** Three feature ideas for `PresetsDeviceView` (`src/gui/views/presets_device_view.py`),
raised during a 2026-08-29 Q&A session. Listed here purely so they aren't lost -- **there is no
commitment to build any of this**; each needs confirmed demand or an explicit product decision
before it's scoped as real work.

- **(a) Activate a named PEQ preset onto a source** (load-and-leave-active, not the load-then-
  restore preview `read_peq_preset_preview()` already does for Export/Save/Copy). `WiiMAdapter
  .load_peq_profile()` already wraps `EQv2SourceLoad` and is reusable, but a true "activate" needs
  its own flow that intentionally skips the restore-afterward step, and must respect the
  documented rule that `EQv2SourceLoad` unconditionally turns `EQStat` on (see CLAUDE.md).
  RoomFit has an equivalent (`load_roomfit_profile`), same caveat.
- **(b) Rename named PEQ presets and RoomFit profiles.** `EQv2Rename` is hardware-confirmed
  working for both (`docs/wiim_api_notes.md`; see the archived "On-Device Preset/Profile Rename"
  item below), but no adapter method wraps it yet. Being a metadata write rather than a filter
  write, it likely doesn't need the full `safe_write.py` Backup->Write->Read-Back->Verify->Rollback
  protocol -- a simpler flow should suffice.
- **(c) Toggle enable/disable PEQ and/or RoomFit from this view.** Backend already exists
  (`enable_peq()`/`disable_peq()`, `enable_roomfit()`/`disable_roomfit()`), but this explicitly
  reopens a prior product decision: see the archived "PEQ / RoomFit Enable/Disable Toggle in GUI"
  item below, closed 2026-07-14 as "explicit product decision (2026-07-02) not to build it -- the
  WiiM Home app already covers this." Re-adding it means deliberately revisiting that decision,
  not just implementing it.

**Why it matters:** (a) and (b) fill real gaps in what "Presets on Device" can do today (list,
load-for-preview, export, save-to-library, copy-to-device, delete -- but not activate-in-place or
rename); (c) is a UX convenience question, not a gap.

**Why deferred:** Speculative. No confirmed user demand yet for (a)/(b); (c) was explicitly
decided against once already.

**Status:** Not started -- candidate list only.

**To reactivate:** Confirm real demand (or, for (c), a deliberate reversal of the 2026-07-02
decision) for each sub-item independently before scoping -- they don't need to ship together.
Rough complexity if pursued: (a) medium (new adapter-level activate flow + GUI + tests), (b)
medium (new adapter method(s) for PEQ and RoomFit + rename dialog + wiring + tests), (c) small
(GUI toggle + wiring, since adapter methods already exist) if the product decision is reversed.

---

## Completed / Closed Items (Archive)

### 1. Hardware QA Sign-off
**Completed:** 2026-08-29. `docs/qa_signoff.md`'s sign-off form (§7) is filled in and signed by
the device owner (disposabledominik): all automated quality gates pass, all applicable manual
tests (§4) pass or have logged failures, every scenario in the §5 traceability matrix resolves to
a passing test or a documented/waived gap, and the verdict is checked "PASS — ready to release."
Tested against WiiM Sound (x2 firmware builds), WiiM Amp Ultra, WiiM Amp Pro, and WiiM Mini.
**Note:** `docs/smoke_test_issues.md` #119 (intermittent window-restore-from-maximized clipping,
low severity, no consistent repro) is still listed `OPEN` there — it was not separately closed out
or explicitly listed under this sign-off's "Waived gaps," it's carried as an accepted low-severity
known issue rather than a release blocker. If a consistent repro turns up, fix it and update #119's
row in the same commit per CLAUDE.md's rule, but it does not block this item's completion. Item
number kept (not reused) — cited by number in this file's own history note and possibly elsewhere.

### 5. Operation Feedback: Overlapping Operations Can Race (Found via `/code-review ultra`)
**Completed:** 2026-08. `OperationFeedbackManager` (`src/gui/operation_feedback.py`) tracked
exactly one in-flight operation via a single `_is_active` flag and one `_prior_enabled`
button-state snapshot, both overwritten wholesale on every `start_operation()` call. If an
operation was cancelled (`_on_cancel_clicked()` called `finish_operation()` immediately) while its
underlying coroutine kept running in the background -- Cancel only reset the UI, it didn't stop
the coroutine -- and a second, unrelated operation started before that first coroutine's `finally`
block fired its own `operation_finished` signal, the stray late signal called `finish_operation()`
again and restored buttons using the *second* operation's snapshot, not the first's. Found during a
`/simplify`/`/code-review ultra --fix` cleanup pass (smoke `docs/smoke_test_issues.md` #243/#244),
independently re-confirmed during a 2026-08-02 codebase review. Fixed without the token-based
identity scheme originally sketched: `AsyncBridge.run_async()` now accepts `cancellable: bool` and
tracks the current `Future`; `_dispatch()` in both workflow managers threads it through, opt-in per
call site (reads/local-file operations only -- device writes stay non-cancellable by default, the
safe direction). `OperationFeedbackManager.request_cancel()` (shared by the Cancel button and
Escape) now actually cancels that Future via a new `AsyncBridge.request_cancel()`, and -- this is
what closes the race -- no longer calls `finish_operation()` itself; the real `operation_finished`
signal (fired once the cancelled coroutine's `finally` block actually unwinds) is the only thing
that resets UI state, so a second operation starting in the gap can no longer have its snapshot
stomped by a stale finish. See `src/gui/async_bridge.py`, `src/gui/operation_feedback.py`. Item
number kept (not reused) -- cited by number in `docs/architecture.md`, `test_main_window_settings.py`,
`test_gui_operation_timeout.py`.

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
`WiiMAdapter.enable_peq()`/`disable_peq()` and CLI `peq-toggle` are implemented; the RoomFit DSP
toggle (`EQChangeSourceFX`/`EQSourceOff` at `EQLevel:2`, empty `source_name`) is hardware-confirmed
but not wired into `WiiMAdapter`/GUI. (`get_peq_enabled()` itself was removed in the 2026-08
dead-code pass — confirmed a genuine duplicate of the `EQStat == "On"` check `read_peq()` already
does via the same `EQGetLV2SourceBandEx` call, not a unique capability; re-add it directly from that
pattern if this ever gets reactivated.)

### HP/LP Capability Detection and Write-Time Validation
**Closed:** 2026-07-14. The functional problem (warning/skipping unsupported filter types at write
time) is already solved by `DeviceCapabilities.supported_filter_types`
(`src/models/capabilities.py`) and `validate_filters_for_device()`. Only *dynamic runtime probing*
for a not-yet-catalogued no-HP/LP device remains undone — revisit if such a device appears.

### Profile Comparison & Diffing
**Closed:** 2026-07-14. Future-phase feature, not MVP, no active demand. The dormant implementation
(`FilterTable.set_comparison`/`_populate_comparison`/`_filters_differ`/`_apply_highlight_style`,
plus its QSS/tests) was removed entirely in the 2026-08 dead-code pass — it was unreachable (no
caller ever wired it up) and had been for a while. Revisiting means reimplementing from scratch,
not reactivating dormant code.

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
