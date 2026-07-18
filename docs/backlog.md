# Backlog — Deferred Features & Tech Debt

Items moved here from active specs, or noted during code quality audits. Not planned for the
current release but may be reconsidered in future versions. Backend support may already exist
(noted per item).

---

## 1. Hardware QA Sign-off

**Originally:** `docs/qa_signoff.md` final verdict (2026-06-15)

**What:** Full-flow validation against real WiiM device(s) covering the GUI-era scenarios that can't be automated (multiroom groups, RoomFit push with naming, device reboot mid-write, etc. — see `docs/qa.md` and `docs/qa_signoff.md` §5).

**Why deferred:** Requires physical hardware sessions.

**Status:** ✅ Largely superseded by events, not "pending" anymore. `docs/qa_signoff.md` itself is a frozen pre-GUI snapshot (2026-06-15, 470 tests, translator-only coverage) and hasn't been re-run/updated since, but extensive GUI-era hardware/manual QA has happened since via a different mechanism: `docs/smoke_test_issues.md` now tracks 168 logged issues, of which 162 are `FIXED`, 3 `WONTFIX`, 1 `REASSIGNED`, and only **one remains genuinely `OPEN`** (#119, an intermittent window-restore-from-maximized clipping bug — low severity, needs a consistent repro). The automated suite has grown to 1181 tests (confirmed 2026-07-04) from the 470 at the original sign-off. CLAUDE.md's own phase-status line still says GUI-era hardware QA is "ongoing," which is technically true (#119 open, and `docs/wiim_api_notes.md`/`docs/corrections.md` hardware investigations are still adding findings weekly as of 2026-07-04) but understates how much has actually been validated against real devices at this point.

**Status update (2026-07-13):** `docs/qa.md`, the pre-GUI `docs/qa_signoff.md`, and
`docs/smoke_test_procedure.md` have been consolidated into a single, current `docs/qa_signoff.md` —
a manual QA & sign-off guide with automated-gate checklist, a manual test procedure corrected against
the current GUI (`src/gui/pages/filters_page.py`, `presets_device_view.py`, `my_presets_view.py`,
etc.), and a scenario traceability matrix.

**Status update (2026-07-14):** Kept open at the device owner's request, pending a fresh manual QA
pass — #119 needs to be closed out and the blank sign-off form in the new `docs/qa_signoff.md`
needs to be filled in with current numbers before this can be retired for good.

**To reactivate:** Close out #119 and formally fill in `docs/qa_signoff.md`'s sign-off form with
current test counts/coverage.

---

## 2. MainWindow God-Object — Extract Business Logic from GUI Layer (Tech Debt)

**Originally:** Code quality audit (2026-06-28)

**What:** `src/gui/main_window.py` is ~4,470 lines (grown from ~4,270 at the
last audit, confirmed 2026-07-11 during the RoomFit-capability-model/
prober-redesign pass; grown further to 4,739 lines by 2026-07-14). 25 of its `async def _do_*` methods call adapters/repository
directly (network I/O + data manipulation in a GUI class), violating
`.kiro/steering/rules.md` rule #14 ("Separate UI from business logic
strictly. No network calls or data manipulation in GUI components").
`SecondaryWorkflowManager` (`src/gui/secondary_workflows.py`) already
demonstrates the target pattern (QObject-based manager, injected adapter
factories via `.configure()`, signals for completion, no direct Qt
widget access) — extraction should follow that template, either as a
new `PrimaryWorkflowOrchestrator` or by growing `SecondaryWorkflowManager`.

**Candidate methods to extract** (read-only / state-reporting, low risk):
`_do_discovery`, `_do_probe`, `_do_file_import`, `_do_file_import_lr`,
`_do_device_pull`, `_do_roomfit_pull`, `_do_load_peq_preset`,
`_do_list_presets`, `_do_list_roomfit_profiles`,
`_do_populate_name_profiles`, `_do_rew_list_measurements`,
`_do_rew_get_filters`, `_do_rew_get_filters_lr`, `_do_export`,
`_do_export_lr`, `_do_preset_export`, `_do_preset_save`, `_do_raw_command`.
**Added since the original audit, same low-risk shape** (confirmed
2026-07-04): `_do_delete_presets` — thin per-item dispatch to
`delete_peq_profile`/`delete_roomfit_profile`, though note it's a
destructive write rather than read-only, so worth an explicit test pass
if extracted.

**Must stay in MainWindow** (too risky/entangled to move yet): `_do_push`
(the safety-critical core push path), `_do_undo_roomfit`,
`_do_undo_multi_source`, `_do_copy_preset_to_device`/
`_do_copy_presets_batch_multi`/`_do_copy_local_profile_to_devices` (the live
"Copy to Another Device" feature — do not confuse with the deleted
`SecondaryWorkflowManager` methods of similar names, removed in the
2026-06-28 code quality audit as unreachable dead code). **Correction
(2026-07-14):** the batch method's actual name is
`_do_copy_presets_batch_multi`, not `_do_copy_presets_batch` as an earlier
version of this entry stated; `_do_copy_local_profile_to_devices` was also
missing from this list despite being in the same risk category.

**Mechanism to preserve:** all `_do_*` methods are invoked via
`self._bridge.run_async(self._bridge_wrapper(name, self._do_x(...)))`
from `_on_*` Qt slot handlers — this signal/bridge wiring pattern must be
preserved; only the method body + adapter calls move to the new class,
which then emits its own completion signal back to MainWindow's `_on_*`
handlers (same shape as `SecondaryWorkflowManager.undo_complete` etc.).

**Why deferred:** Not a correctness bug — current code works. Effort is
~Medium, best done incrementally (4-6 methods per pass) rather than
big-bang, to keep each step independently testable.

**Status:** ✅ Done (2026-07-14) except `_do_raw_command`, permanently
deferred (see below). `PrimaryWorkflowManager` (`src/gui/primary_workflows.py`)
now owns `_do_discovery`/`_do_probe`/`_do_file_import`/`_do_file_import_lr`/
`_do_list_presets` (Phase 1, the last as `refresh_presets()`/`list_presets()`),
`_do_device_pull`/`_do_roomfit_pull`/`_do_load_peq_preset`/`_do_export`/
`_do_export_lr` (Phase 2), `_do_rew_list_measurements`/`_do_rew_get_filters`/
`_do_rew_get_filters_lr`/`_do_preset_export`/`_do_preset_save` (Phase 3),
`_do_populate_name_profiles`/`_do_list_roomfit_profiles` (Phase 4), and
`_do_delete_presets` (Phase 5), plus the discovered-devices cache and
probe-generation counter that existed only to serve Phase 1's methods.
`main_window.py` dropped from 4,739 to 4,169 lines across twelve commits,
with `test_gui_integration_primary.py` extended to cover all eighteen
methods. The PEQ/RoomFit concurrent-fetch behavior
(#174) is preserved via four separate signals (`peq_presets_ready`/
`peq_presets_unavailable`/`roomfit_profiles_ready`/`roomfit_profiles_hidden`)
rather than one combined result, since the two fetches complete and update
the view independently. Phase 2 introduced three small helpers once enough
entry points existed to justify them — `_dispatch()` (collapses the
repeated assert/assert/run_async dispatch line, now used by all seventeen
entry points), `_require_adapter()` and `_require_wizard_state()` (collapse
the repeated adapter/wizard-controller asserts). Phase 3 added a fourth,
`_require_rew_client()` (same shape, three call sites), plus
`EmptyPresetFiltersError` — `_do_preset_export`/`_do_preset_save` were the
only two methods in this whole extraction that touched a GUI widget
directly (`status_banner.show_error(...)` on the empty-filters branch); they
now raise this exception instead, which flows through the existing
`_bridge_wrapper` → `_map_error` → `operation_error` path already used for
`ParseError`/`ValidationError`, so the manager needed no new signal for it.
Phase 3 also found and fixed a pre-existing 3x duplication: the
"read-preset-preview, dispatching on preset_type" block was copy-pasted in
`_do_preset_export`, `_do_preset_save`, and the not-yet-moved
`_read_preset_to_copy` (used by the Copy-to-Device flow) — extracted to
`read_preset_preview()` in `src/gui/shared_helpers.py` and all three call
sites switched to it, including `_read_preset_to_copy`, which stays in
MainWindow.

Phase 4 (the RoomFit-dropdown group) needed genuine design work rather than
a verbatim move: `_do_populate_name_profiles`/`_do_list_roomfit_profiles`
write to two different widgets (`NameProfilePage`/`FiltersPage`) with two
different payload shapes, so the existing `roomfit_profiles_ready`/
`roomfit_profiles_hidden` pair (already wired to `PresetsDeviceView` via
`refresh_presets()`) couldn't be reused without misrouting data — two new,
distinctly-named signals were added instead
(`name_profiles_ready(list, str, bool)`/`filters_roomfit_profiles_ready(list)`).
Investigating `_do_populate_name_profiles`'s `self._roomfit_enabled`
side-effect turned up a pre-existing dead-state bug: it's written in four
places but read in zero — `_on_name_confirmed`'s overwrite-confirmation
dialog is actually driven by `NameProfilePage.classify()`, and two stale
comments claimed `_roomfit_enabled` gates that dialog when it doesn't
(confirmed by a test, `test_191_name_confirmed_dialog_shown_even_when_roomfit_disabled`,
which sets it `False` and asserts the dialog still fires). Fixed the
misleading comments in the same commit; left the dead attribute itself
alone (removing or wiring it into real gating logic would be a behavior
change beyond "move this method" — flagging here in case a future pass
wants to pick it up).

**Phase 5** was a follow-up code-quality pass prompted by the user asking
"did we really remove all application logic, why is it still huge" after
Phase 4 — a fresh audit found three loose ends, addressed on their own
merits rather than by mechanically reapplying the "move to
PrimaryWorkflowManager" template everywhere:
- `_do_delete_presets` was flagged as a low-risk candidate in the original
  2026-06-28 audit but was simply missed by Phases 1-4 — moved now, same
  shape as everything else. Its two completion paths (success,
  partial-failure) called `status_banner` directly rather than raising an
  exception, so it needed a new `presets_delete_complete(int, int)` signal
  rather than the `EmptyPresetFiltersError` pattern from Phase 3.
- Five direct `self._profile_repository.*` calls in `_on_*` handlers
  (rename/duplicate/delete/save-to-presets) were **not** moved to
  `PrimaryWorkflowManager` — these are synchronous local-disk I/O, not
  network calls, so the async bridge/dispatch pattern doesn't fit; moving
  them would have added cross-file indirection without reducing
  complexity. Instead, the exact try/except/refresh/banner shape
  duplicated three times across the rename/duplicate/delete handlers was
  consolidated into one `_run_profile_action()` private helper, which also
  absorbed the fourth call site (`_save_filters_to_presets`) — that one
  had no try/except at all, so a failing save previously propagated
  uncaught instead of showing an error banner like its siblings; now
  fixed for free.
- `_on_peq_ready` (182 lines, the largest method in the file) was **not**
  moved either — it's a synchronous Qt slot reacting to data a signal
  already delivered, making no adapter/network calls itself (the actual
  validation math already lives in `shared_helpers.validate_filters_for_device()`).
  Decomposed in place into `_validate_and_populate_review()` plus two tiny
  `_clear_pending_lr_rows()`/`_clear_pending_stereo_rows()` helpers, which
  also deduped a pending-state reset block copy-pasted three times (L/R
  fields) and twice (stereo fields) across the original method. Verified
  against the full existing 177-test surface across three test files
  before committing, plus one new test for a previously-uncovered guard
  path (L/R mode without explicit bands_l/bands_r).

**To reactivate:** Only `_do_raw_command` remains as a genuine standalone
candidate (diagnostics-only, zero test coverage, low value) — permanently
deferred per its own low-value note, not worth a phase on its own.

**Post-Phase-5 audit (2026-07-14):** confirmed via a full sweep of every
remaining `self._wiim_adapter.`/`self._profile_repository.`/`self._rew_client.`
call site in `main_window.py` that the six "Must stay in MainWindow"
methods above are the *only* remaining business-logic extraction
candidates — everything else outside them is either already-consolidated
(`_run_profile_action`'s three call sites), `_do_raw_command`, or a single
harmless attribute read (`_profile_repository.storage_root`, used only to
seed a file-dialog default path, not data manipulation). If those six were
ever extracted, `_read_preset_to_copy` (32 lines) and
`_write_preset_copies_to_devices` (46 lines) would go with them — both
exist solely to serve the copy-to-device methods and have no other
callers. Exact current sizes: `_do_push` 127, `_do_copy_preset_to_device`
85, `_do_copy_presets_batch_multi` 63, `_do_copy_local_profile_to_devices`
55, `_do_undo_roomfit` 49, `_do_undo_multi_source` 38, plus the two shared
helpers above — **495 lines total** (~12% of the file), which would drop
`main_window.py` from 4,169 to roughly 3,674 lines. **Decision (2026-07-14):
not pursued at the time** — this group runs through the 5-step safety
protocol (Backup → Write → Read Back → Verify → Rollback), and CLAUDE.md's
"Safety before convenience" principle argued for a much more careful,
dedicated effort than a routine extraction pass, not something to fold
into an incremental phase.

**Update (2026-07-17): the dedicated effort happened, and this decision is
superseded.** The user explicitly requested it, and a 4-pass adversarial plan
review (checking for new bugs, duplication, and missed consolidation
opportunities before each execution pass) preceded implementation. All 6
deferred methods plus `_do_raw_command` are now out of `main_window.py`,
across a 6-commit sequence on `PrimaryWorkflowManager`/
`SecondaryWorkflowManager` (`dfd7628`, `1a14ded`, `338894c`, `ef6a05e`,
`76b2a4c`, characterization tests added first in `009a779`):
- `_do_raw_command`, `_do_push` → `PrimaryWorkflowManager` (mechanical
  moves; `_do_push` already touched no widgets, `_do_raw_command` was
  trivial).
- `_do_undo_roomfit`, `_do_undo_multi_source`, `_read_preset_to_copy`,
  `_do_copy_preset_to_device`, `_write_preset_copies_to_devices`,
  `_do_copy_presets_batch_multi`, `_do_copy_local_profile_to_devices` →
  `SecondaryWorkflowManager`. Each method's direct `self._status_banner`/
  `self._push_page` widget calls were converted to signal emissions
  (`undo_complete`, reused as-is, plus two new signals —
  `copy_batch_complete(int, int, int, int)` and
  `copy_local_profile_complete(str, int, int, int)`, kept separate rather
  than merged since the two summaries need genuinely different data
  shapes) — same widget→signal pattern Phase 5 established for
  `presets_delete_complete`. `configure()` gained
  `roomfit_safe_write_factory` plus three target-device connection
  factories (`wiim_http_client_factory`, `capability_prober_factory`,
  `target_adapter_factory` — pure pass-through of `MainWindow`'s existing
  `adapter_factories.py`-backed attributes, not new factory logic).
- The `_do_undo_multi_source` scheduling-vs-outcome race flagged in the
  post-Phase-5 audit was deliberately characterized with tests (`009a779`)
  and preserved as-is during the move, not fixed — moving code was not the
  moment to also change its behavior.
- This same effort also closed several smaller GUI-layer leaks found
  during a fresh sweep: `shared_helpers.py`'s model-construction functions
  moved to `models/peq.py`/`models/profile.py`/`models/channel_mode.py`
  (the file itself was deleted once empty), `MyPresetsView._count_bands()`
  moved to `Profile.band_counts()`, a hardcoded RoomFit-blocked-model
  substring check in `_on_capabilities_ready` was consolidated into
  `CapabilityProber.probe()` (which already made the same decision
  data-driven via `device_capabilities.json`), and a hardcoded diff-display
  tolerance in `filter_table.py` was replaced with the canonical
  `fp_compare.gain_matches()`.

`main_window.py` is now 3,732 lines (down from 4,169 pre-Phase-D). No
further extraction phases are planned for this item.

**Update (2026-07-17): branch-quality review and fixes.** After the Phase D extraction above landed,
an 8-angle code review (line-by-line, removed-behavior, cross-file, reuse, simplification,
efficiency, altitude, CLAUDE.md-conventions) was run against the full branch diff. 10 findings were
confirmed and independently verified against the actual code; all 10 were fixed, across 11 commits
(`b5415a9`, `17a6fe3`, `73ee1b0`, `6a7e011`, `0d58501`, `f086aca`, `a015432`, `649e92d`, `5cdad7c`,
`a44d39b`, `a7045b9`):

- **Two regressions from the Phase D move, fixed:** `_do_undo_multi_source` had lost its
  succeeded>0 → clear-pushed-snapshot behavior when it started sharing the binary `undo_complete`
  signal with the single-source undo paths — a partial multi-source undo no longer cleared stale
  dirty-tracking. Fixed with a dedicated `undo_multi_source_complete(int, int, str)` signal (`b5415a9`).
  Separately, `capability_prober.py`'s "mini"-model RoomFit fallback gated on the coarse
  `capability_file_override` flag, which `merge_into()` sets whenever *any* capability-file entry
  field matched — not specifically a RoomFit one — so a future/user-added entry that only set an
  unrelated field could silently bypass the smoke #36 correction. Narrowed the gate to the matched
  entry's own roomfit-specific fields (`17a6fe3`).
- **Documentation gaps closed:** the copy-to-device flow's dropped per-item success banner (batch
  summary + existing progress messages already cover it) was documented as an intentional
  consolidation, not a silent regression (`73ee1b0`). A stale test-file docstring claiming
  copy-preset-to-device methods were dead code was corrected — they're the same live methods this
  Phase D effort re-added (`6a7e011`).
- **Consolidation:** 5 separate hand-rolled copies of the str-or-ChannelMode coercion `coerce_channel_mode()`
  already centralizes (2 found by the original review, 3 more — including one in
  `wiim_adapter.py`'s `write_roomfit()` the original review missed — found during the plan's own
  adversarial re-review pass) now all call the one helper (`0d58501`). `MainWindow` no longer builds
  two byte-for-byte-identical `SafeWrite`/`RoomFitSafeWrite` factory-lambda pairs (`f086aca`).
- **Dead code removed:** `SecondaryWorkflowManager.is_configured` (zero callers anywhere) and its
  `wiim_adapter_factory`/`backup_manager` `configure()` params (never read by any workflow) were
  deleted; the removed lambda at the one production call site turned out to also be latently buggy —
  it captured the *source* device's capabilities and would have misapplied them to any different
  target device if it had ever been invoked (`649e92d`). `undo_last_push`'s `@Slot(str)` decorator,
  which understated its real 2-arg signature, was corrected to `@Slot(str, object)` (`5cdad7c`).
- **Efficiency:** the copy-to-device batch path connected to and re-probed capabilities on *every*
  (preset, device) pair instead of once per device — copying 3 presets to 3 devices made 9 probe
  cycles instead of 3. Restructured to connect once per device (`_write_preset_to_adapter` extracted
  from `_do_copy_preset_to_device` as a shared write-only primitive); an unreachable device now counts
  all its presets failed in one step instead of retrying the connection per preset (`a44d39b`).
  `wiim_adapter.py`'s `_write_peq_batch`/`_write_peq_sequential` no longer take a redundant
  `channel_mode` parameter that had to be kept in lockstep with `band_array_r`'s presence — it's
  derived internally now (`a7045b9`).

Two findings involved a genuine UX/scope trade-off rather than a single correct answer, resolved
in favor of the lower-risk option: the per-item copy banner stays consolidated into the batch
summary (not restored) to avoid banner-spam on larger batches, and the copy-to-device batch fix
above connects sequentially per device rather than also parallelizing writes across devices —
CLAUDE.md's "Safety before convenience" principle argued against adding concurrent-write complexity
to the safety-critical write path for uncertain benefit (most setups target 1-3 devices).

`main_window.py` is now 3,767 lines. No further passes are planned for this item.

---

## 3. Shared Base/Mixin for "Optional Embedded Warning" Dialogs (Tech Debt)

**Originally:** Surfaced via `/code-review ultra` during the 2026-07-12 dialog-consolidation session (`docs/smoke_test_issues.md` `#200`/`#201`).

**What:** `DevicePickerDialog` and `QuickSetupDialog` each independently gained an optional
`warning: tuple[str, str] | None` constructor param (folding a preceding standalone confirmation
into the dialog itself — see `docs/smoke_test_issues.md` for the workflow-consolidation this
enabled). The review found the two dialogs' `_setup_ui()` bodies had copy-pasted the same
"unpack tuple, build a warning box, add it to the layout" block; this was fixed in the same
session by extracting a shared `add_optional_warning_box(layout, warning, ...)` helper
(`src/gui/components/warning_box.py`). What's *not* fixed: the `warning` param, its docstring,
and the `setMinimumWidth(420 if warning else ...)` width-bump convention are still hand-duplicated
in each dialog's `__init__`/static factory method rather than coming from a shared base class or
mixin. **Correction (2026-07-17):** this entry originally cited `PushConfirmation` as a third,
differently-conventioned caller of the underlying `make_warning_box()` — that class was dead code
(zero production references) and has since been deleted; only the two dialogs below remain.

**Why deferred:** Only two dialogs currently need the optional-warning constructor pattern; a
third would justify extracting a shared base (`WarningDialogBase`/`OptionalWarningMixin`) with
real confidence about the right shape. Doing it now for two call sites risks guessing the wrong
abstraction (per `.kiro/steering` — don't design for hypothetical future requirements).

**Status:** Not started. Low priority, low risk if left alone (the duplication remaining after the
2026-07-12 partial fix is just `__init__`/docstring boilerplate, not behavior).

**To reactivate:** If a third dialog needs an embedded optional warning, extract a shared
`__init__`-level mixin/base class covering the `warning` param, docstring, and width-bump logic,
and migrate `DevicePickerDialog`/`QuickSetupDialog` onto it at the same time.

---

## 4. Multi-Source Push: No Automatic Rollback on Partial Failure (Known Limitation)

**Originally:** Surfaced during PR #1 review (2026-07-18) of item 2's `PrimaryWorkflowManager`
extraction — pre-existing behavior, not introduced by that PR, but previously undocumented as a
known limitation anywhere.

**What:** `PrimaryWorkflowManager._do_push()`'s PEQ flow writes to each of `state.selected_sources`
in sequence and aborts on the first failure (`src/gui/primary_workflows.py`, the "Abort on first
failure" comment). Each individual source's write still goes through the full `SafeWrite` 5-step
protocol (backup, write, read-back, verify, rollback-on-verify-failure) for *that* source — but if
source N fails after sources 1..N-1 already succeeded, there is no cross-source rollback: the
already-written sources are left in their new state rather than restored to their pre-push backups.
CLAUDE.md's design principle #1 ("Safety before convenience — never write to a device without
backup and verification") and #4 ("Recoverability — automatic rollback on verification failure")
read as applying at the whole-push level, not just per-source, so this is a real gap against the
stated design principles, not just a UX rough edge.

**Why deferred:** Backup paths for all sources written before the failure are still collected and
returned (`backup_paths` in `_do_push`), so the *user* can manually undo each succeeded source via
the existing undo flow — the data needed for a fix already exists, this is a missing automation, not
a missing capability. Most setups push to 1-2 sources, and a partial multi-source push failure is
uncommon (each source already passed its own read-back verification before the loop moves on; the
common failure mode is connection loss between sources, not a bad write). Fixing this properly means
either auto-invoking undo on sources 1..N-1 when source N fails (extra complexity in the safety-
critical write path, and a rollback-of-a-rollback risk if the auto-undo itself fails) or restructuring
the whole multi-source push to pre-stage backups for all sources before writing any of them.  Either
is a large enough decision to warrant its own design pass rather than folding into an unrelated PR.

**Status:** Not started.

**To reactivate:** Decide whether cross-source auto-rollback is wanted (and how it should behave if
the rollback itself fails), or whether documenting the manual-undo path in the GUI's push failure
message is sufficient. Implement in `PrimaryWorkflowManager._do_push()`'s PEQ branch.

---

## Completed / Closed Items (Archive)

### Adapters Instantiated Directly in `main_window.py` (Tech Debt)
**Completed:** 2026-07-17. Found during a code-quality audit alongside item 2 (MainWindow
God-Object) above, but a distinct violation: 4 sites in `main_window.py` called
`WiiMHttpClient(...)`/`CapabilityProber(...)`/`WiiMAdapter(...)`/`REWHttpApiClient()` directly,
against CLAUDE.md's "Adapters are injected via constructor... never instantiate an adapter inside
business logic." Fixed by adding a new `src/gui/adapter_factories.py` module (the sole place in
`src/gui/` allowed to call the real constructors) and threading 4 constructor-injected factory
parameters through `MainWindow.__init__` (`rew_client_factory`, `wiim_http_client_factory`,
`capability_prober_factory`, `wiim_adapter_factory`), each defaulting to the matching
`adapter_factories.py` function and reused at all 4 call sites. Also collapsed two duplicated
`# type: ignore[arg-type]` suppressions (masking `@Slot(object)`'s type erasure on the probed
capabilities) into a single `cast(DeviceCapabilities, caps)` at the top of
`_on_capabilities_ready()`. A grep-based guard test
(`test_gui_adapter_injection.py::TestNoDirectAdapterInstantiationInGui`, mirroring
`test_safe_write.py::TestNoDirectWriteBypass`'s pattern — its `iter_src_python_files()` helper was
promoted from a private copy in that file to `conftest.py` so both tests share it) now fails CI if
any file under `src/gui/` other than `adapter_factories.py` instantiates one of these classes
directly. Required updating 11 `unittest.mock.patch("src.gui.main_window.<Class>")` call sites
across `test_smoke_regression_operations.py` to patch `src.gui.adapter_factories.<Class>` instead
— the class names are still imported into `main_window.py` for type annotations, so the old patch
target silently stopped intercepting the call instead of raising an import error, and 3 of the 11
were live network-call regressions (real `httpx.ProxyError`s) until caught by actually running the
affected tests, not just by inspection.

### `ProfileRepository.list()` Shadows Builtin (Tech Debt)
**Completed:** 2026-07-14. Formerly backlog item "1. `ProfileRepository.list()` Shadows Builtin."
Renamed to `list_all()`, removing the `import builtins` + `builtins.list[Profile]` workaround.
Updated the one production call site (`_refresh_presets_view()`, `main_window.py`), the one
internal call site (`get_by_tag`), and 4 test locations in `test_profile_repository.py`. An
earlier version of this entry claimed the rename would "come along for free" while extracting
`_do_list_presets` for the MainWindow god-object item — that was stale/incorrect (`_do_list_presets`
never called `ProfileRepository.list()`); the two were done as fully independent commits.

### PEQ / RoomFit Enable/Disable Toggle in GUI
**Closed:** 2026-07-14. Formerly backlog item "1. PEQ / RoomFit Enable/Disable Toggle in GUI."
The GUI-toggle feature itself was an explicit, dated product decision not to build it (2026-07-02):
the WiiM Home app already provides this, and adding it to the sync tool would be UI clutter without
enabling a workflow that isn't already covered. Backend support remains available if reactivated —
`WiiMAdapter.enable_peq()`/`disable_peq()`/`get_peq_enabled()` and CLI `peq-toggle` are implemented;
the RoomFit DSP toggle mechanism (`EQChangeSourceFX`/`EQSourceOff` at `EQLevel:2`, empty
`source_name`) is hardware-confirmed but not wired into `WiiMAdapter`. **Correction (verified
current):** this entry previously flagged `docs/architecture.md`, a `# TODO: RoomFit toggle`
marker in `wiim_adapter.py`, and a GUI tooltip as stale artifacts describing RoomFit toggling as
unsupported. All three are already resolved as of this check: `docs/architecture.md`'s "Design
Notes" section already states the toggle "has a confirmed working API... but it is not wired into
`WiiMAdapter` or the GUI — this is an intentional product decision"; no `# TODO: RoomFit toggle`
marker exists anywhere in `wiim_adapter.py`; and no RoomFit-toggle tooltip exists anywhere under
`src/gui/`. No further doc-correction pass needed for this item.

### HP/LP Capability Detection and Write-Time Validation
**Closed:** 2026-07-14. Formerly backlog item "2. HP/LP Capability Detection and Write-Time
Validation." The functional problem — warning/skipping unsupported-filter-type bands at write
time — is already solved by the general `DeviceCapabilities.supported_filter_types` mechanism
(`src/models/capabilities.py:37`) and `validate_filters_for_device()`
(`src/gui/shared_helpers.py:234`), which already covers WiiM Mini's HP/LP exclusion. The only
remaining piece was *dynamic runtime probing* to auto-detect HP/LP support for a not-yet-catalogued
device — a real gap only if/when a new no-HP/LP device model shows up; none is known today. Revisit
if that happens.

### Profile Comparison & Diffing
**Closed:** 2026-07-14. Formerly backlog item "5. Profile Comparison & Diffing." Future-phase
feature (visually/textually compare two PEQ profiles), not MVP, no active plan or user demand.
Revisit if requested.

### Advanced Filter Types
**Closed:** 2026-07-14. Formerly backlog item "6. Advanced Filter Types." All-Pass filters and
specialized shelf variants are blocked on WiiM firmware support that doesn't exist yet — nothing
actionable on the app side. Revisit if WiiM ships new filter types in firmware.

### On-Device Preset/Profile Rename via `EQv2Rename`
**Closed:** 2026-07-14. Formerly backlog item "8. On-Device Preset/Profile Rename via
`EQv2Rename`." No user request for this; the existing save-as-new+delete-old workaround already
covers the functional need. `EQv2Rename` is hardware-confirmed working
(`docs/corrections.md`, 2026-07-10) for both PEQ presets and RoomFit profiles on two device models
— the investigation doesn't need to be redone if this is reactivated, only the `WiiMAdapter`
methods (`rename_peq_profile()`/`rename_roomfit_profile()`) and `PresetsDeviceView` menu wiring.

### Packaged `.exe` Shows a Brief Window Flash on Launch
**Closed:** 2026-07-14. Formerly backlog item "10. Packaged `.exe` Shows a Brief Window Flash on
Launch." Root cause understood (PyInstaller onefile build silently extracts the bundled runtime to
a temp folder on every launch); the only fix (switching to a onedir build) was explicitly declined
by the device owner (2026-07-11) in favor of keeping a single portable `.exe`. De facto won't-fix
under the current distribution constraint. Revisit only if the owner reconsiders the single-file
requirement.

### Rethink Source Discovery
**Completed:** 2026-07-03/04, shipped in commit `6bc189d` ("feat: UX & Capability
Improvements - Phase A"). Formerly backlog item "3. Rethink Source Discovery" —
the premise (no API enumerates real physical inputs) turned out to be
incomplete: `getAudioInputEnable` returns each input's `mode` (the exact
`source_name` PEQ/RoomFit commands use) plus an enabled/shown flag, correctly
excluding non-addressable entries like `udisk` (`docs/corrections.md`,
2026-07-03). `CapabilityProber._probe_source_names()`
(`src/adapters/capability_prober.py`) now calls this directly, replacing the
old dead `getStatusEx` `InputList` parsing; devices with no `getAudioInputEnable`
(WiiM Mini) fall back to the existing per-model capability-file/hardcoded table
as before, so nothing regressed for that case. Confirmed still wired in and
tested as of 2026-07-04.

### RoomFit DSP Toggle — API Investigation
**Completed:** 2026-07-02. Formerly backlog item "2. RoomFit Enable/Disable API
Investigation." Original 2026-06-15 hardware test concluded no API command
could toggle RoomFit; a 2026-07-02 retest found the same two commands
(`EQChangeSourceFX`/`EQSourceOff` at `EQLevel:2`) work when `source_name` is
the empty string rather than omitted or populated — the earlier test's
populated `source_name` silently targeted the wrong (per-source) scope
instead of failing. Confirmed round-trip against real hardware
(`docs/corrections.md`, 2026-07-02; `docs/wiim_api_notes.md` "RoomFit DSP
Toggle — CONFIRMED"). The investigation is closed; whether to wire this into
`WiiMAdapter`/the GUI was tracked under backlog item "PEQ / RoomFit
Enable/Disable Toggle in GUI" above, itself now closed as a product-scope
decision.

### Backward-Compat `ValidationError` Re-export in wiim_parser
**Completed:** 2026-06-28 (code quality audit follow-up). Confirmed zero real
importers of `ValidationError` from `src/translator/wiim_parser.py` anywhere
in the codebase (only this backlog's own description text matched a grep for
the import). Removed the dead `from src.models.errors import ValidationError`
re-export and its `# noqa: F401` comment from `wiim_parser.py`.

### Test coverage for hardware-testing findings
**Completed:** Task 51. Automated tests added for all API behaviors discovered during manual hardware validation.

### Channel Mode Enum
**Completed:** 2025-07-01. Introduced `ChannelMode` enum in `src/models/channel_mode.py` with `STEREO`/`LR` values and properties: `wire_value`, `profile_value`, `display_value`, `is_lr`. Used `Annotated[ChannelMode, BeforeValidator(...)]` (`ChannelModeField`) in Pydantic models for seamless string coercion. Replaced 38+ string comparison sites across 15 production files. `is_lr_mode()` retained as a backwards-compatible wrapper accepting both `str` and `ChannelMode`.

### Remove Redundant `state.current_filters` for L/R Mode
**Completed:** 2025-07-01. Added computed `WizardState.filters` property that returns `filters_l + filters_r` when in L/R mode, or `current_filters` for stereo. This eliminates the desync risk — the property always computes the correct combined list from the authoritative per-channel fields. Bundled with the Channel Mode Enum item.

### Dark/Light Style Consolidation
**Completed.** Refactored dark and light styles for consistency; reviewed and removed unnecessary in-line styles where it made sense.
