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

**Status:** ✅ Phase 1 complete (2026-07-14). `PrimaryWorkflowManager`
(`src/gui/primary_workflows.py`) now owns `_do_discovery`/`_do_probe`/
`_do_file_import`/`_do_file_import_lr`/`_do_list_presets` (the last as
`refresh_presets()`/`list_presets()`), plus the discovered-devices cache and
probe-generation counter that existed only to serve them. `main_window.py`
dropped from 4,739 to 4,569 lines across three commits (scaffold → wire →
extract `_do_list_presets`), with `test_gui_integration_primary.py` added
mirroring `test_gui_integration_secondary.py`'s structure. The PEQ/RoomFit
concurrent-fetch behavior (#174) is preserved via four separate signals
(`peq_presets_ready`/`peq_presets_unavailable`/`roomfit_profiles_ready`/
`roomfit_profiles_hidden`) rather than one combined result, since the two
fetches complete and update the view independently.

**To reactivate (next phase):** Continue with the remaining low-risk
candidates (`_do_device_pull`, `_do_roomfit_pull`, `_do_load_peq_preset`,
`_do_list_roomfit_profiles`, `_do_populate_name_profiles`,
`_do_rew_list_measurements`, `_do_rew_get_filters`, `_do_rew_get_filters_lr`,
`_do_export`, `_do_export_lr`, `_do_preset_export`, `_do_preset_save`,
`_do_raw_command`), following the same pattern: verbatim move, reuse
`_bridge_wrapper` via injection rather than reimplementing error handling,
and check for any state (like the discovered-devices cache) that only
existed to serve the method being moved.

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
mixin — `PushConfirmation` (a third dialog using the underlying `make_warning_box()` directly,
without the optional-param wrapper) makes it a third slightly-different convention already.

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

## Completed / Closed Items (Archive)

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
`source_name`) is hardware-confirmed but not wired into `WiiMAdapter`. **Known follow-up, not
actioned here:** `docs/architecture.md:208`, a `# TODO: RoomFit toggle` marker in
`wiim_adapter.py`, and a GUI tooltip referenced in `docs/corrections.md` (2026-06-15 row) still
describe RoomFit toggling as unsupported, which is now factually stale (it's supported, just
intentionally unbuilt) — worth a small standalone doc-correction pass.

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
