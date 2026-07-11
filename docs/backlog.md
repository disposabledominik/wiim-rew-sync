# Backlog — Deferred Features & Tech Debt

Items moved here from active specs, or noted during code quality audits. Not planned for the
current release but may be reconsidered in future versions. Backend support may already exist
(noted per item).

---

## 1. PEQ / RoomFit Enable/Disable Toggle in GUI

**Originally:** GUI Redesign Requirement 22, original spec Task 58

**What:** A visible on/off toggle in the UI allowing users to quickly enable or disable PEQ or RoomFit on the connected device for A/B listening tests.

**Why deferred:** The WiiM Home app already provides this functionality. Adding it to the sync tool adds UI clutter without enabling a workflow that isn't already covered. The tool's primary purpose is filter transfer, not device configuration. As of 2026-07-02 this is an explicit product decision, not a technical blocker (see backend status below) — reactivating this item is a scope call, not an investigation.

**Backend status:**
- ✅ `WiiMAdapter.enable_peq()` / `disable_peq()` / `get_peq_enabled()` — implemented (Task 57)
- ✅ CLI `peq-toggle --device --source --state on|off` — implemented and working
- ✅ RoomFit DSP toggle — **API mechanism confirmed** (`docs/corrections.md`, 2026-07-02): `EQChangeSourceFX`/`EQSourceOff` at `EQLevel:2` with `source_name:""` (empty, not omitted) reliably toggle RoomFit; status read via `EQGetLV2SourceBandEx` (same empty `source_name`) + `EQStat`. Round-tripped on real hardware. See `docs/wiim_api_notes.md` "RoomFit DSP Toggle — CONFIRMED".
- ⏳ Not implemented in `WiiMAdapter` — no `enable_roomfit()`/`disable_roomfit()`/status-read methods exist yet. Not a hardware-testing gap anymore, just unwritten code, deliberately not written per the product decision above.
- **Stale artifacts from before the mechanism was confirmed, not yet cleaned up:** `docs/architecture.md:208` still states "RoomFit toggle ... is not supported via API"; a `# TODO: RoomFit toggle` marker in `wiim_adapter.py` and a GUI tooltip referenced in `docs/corrections.md` (2026-06-15 row) predate the confirmation. If this item stays deferred, these should be corrected to say "confirmed possible, intentionally not implemented" rather than "not possible."

**To reactivate:** Restore Requirement 22 to the GUI redesign spec, add `PEQToggle` component back to design.md, and create implementation tasks for the toggle widget and its WizardController wiring. The RoomFit half no longer needs an investigation step — go straight to implementing `enable_roomfit()`/`disable_roomfit()` using the confirmed commands above.

---

## 2. HP/LP Capability Detection and Write-Time Validation

**Originally:** Pre-GUI phase backlog (root `BACKLOG.md`, flagged for review 2026-06-27 — confirmed still applicable, not implemented)

**What:** Add a `supports_hp_lp: bool` flag to `DeviceCapabilities`. During `_probe_peq()`, set it to `True` if mode 3 or 5 is seen in the EQBand response. In `dry-run-import`, warn if the import contains HP/LP filters targeting a device without support.

**Already substantially covered — the original problem this item describes is solved, just not by a dedicated flag** (confirmed 2026-07-04): `DeviceCapabilities.supported_filter_types` (`src/models/capabilities.py:37`) already exists as a general per-model allowed-filter-types list, populated from the static capability file (`src/models/assets/device_capabilities.json`) via `device_capability_file.py::merge_into()`. WiiM Mini's entry already lists `["PEAK", "LS", "HS"]` — HP/LP excluded. `validate_filters_for_device()` (`src/gui/shared_helpers.py:234`) consumes this list and does exactly the "warn (and skip) unsupported-type bands before write" behavior this item asks for, wired into the Review page via `main_window.py`. So the write-time-validation half of this item is done, just generalized to any filter type rather than HP/LP specifically.

**What's actually still missing:** the *dynamic runtime probing* half — nothing in `_probe_peq()` inspects the live `EQBand` response to auto-detect HP/LP support and populate the capability file entry automatically. Today, a newly-discovered device without HP/LP support needs a manual capability-file entry (like WiiM Mini's) added by hand; it isn't detected automatically the way the original item envisioned. Since WiiM Mini is the only currently-known no-HP/LP device and it's already hand-covered, this is now a "nice-to-have for future unknown devices" rather than a live gap.

**Why deferred:** The safe-write verify step already catches the mismatch at write time regardless, and the static per-model list already covers every currently-known device. Runtime auto-detection would only matter for a not-yet-catalogued device.

**Status:** ⏳ Runtime probing not implemented — no code path sets `supported_filter_types` (or a dedicated `supports_hp_lp`) from a live `EQBand` response; it's populated by the static JSON file only (re-confirmed 2026-07-04).

**To reactivate:** During `_probe_peq()`, inspect the live `EQBand`/`EQBandL`/`EQBandR` response for mode `3`/`5` and merge a detected HP/LP-support signal into `DeviceCapabilities.supported_filter_types` alongside (not replacing) the static capability-file entry, so newly-seen devices get correct behavior without waiting for a manual JSON update.

---

## 3. `ProfileRepository.list()` Shadows Builtin (Tech Debt)

**Originally:** Code quality audit (2026-06-22)

**What:** The `list()` method on `ProfileRepository` shadows the Python builtin `list`, requiring `import builtins` + `builtins.list[Profile]` for type annotations within the class. Renaming to `list_all()` or `get_all()` would eliminate this workaround.

**Why deferred:** Renaming a public method on `ProfileRepository` would break the GUI layer, tests, and any code that calls `.list()`. Cosmetic improvement with non-trivial migration effort.

**Status:** Still present (confirmed 2026-07-04, `src/repository/profile_repository.py:5,98`). Production call sites: 1 internal (`get_by_tag`), 1 in `main_window.py:1994` inside `_do_list_presets`.

**To reactivate:** Rename method to `list_all()`, update all call sites (~2 production + 4 test locations). Bundle with the MainWindow extraction (backlog item below) — `_do_list_presets` is already a Phase-1 extraction candidate there, so the one production GUI call site gets touched anyway.

---

## 4. Hardware QA Sign-off

**Originally:** `docs/qa_signoff.md` final verdict (2026-06-15)

**What:** Full-flow validation against real WiiM device(s) covering the GUI-era scenarios that can't be automated (multiroom groups, RoomFit push with naming, device reboot mid-write, etc. — see `docs/qa.md` and `docs/qa_signoff.md` §5).

**Why deferred:** Requires physical hardware sessions.

**Status:** ✅ Largely superseded by events, not "pending" anymore. `docs/qa_signoff.md` itself is a frozen pre-GUI snapshot (2026-06-15, 470 tests, translator-only coverage) and hasn't been re-run/updated since, but extensive GUI-era hardware/manual QA has happened since via a different mechanism: `docs/smoke_test_issues.md` now tracks 168 logged issues, of which 162 are `FIXED`, 3 `WONTFIX`, 1 `REASSIGNED`, and only **one remains genuinely `OPEN`** (#119, an intermittent window-restore-from-maximized clipping bug — low severity, needs a consistent repro). The automated suite has grown to 1181 tests (confirmed 2026-07-04) from the 470 at the original sign-off. CLAUDE.md's own phase-status line still says GUI-era hardware QA is "ongoing," which is technically true (#119 open, and `docs/wiim_api_notes.md`/`docs/corrections.md` hardware investigations are still adding findings weekly as of 2026-07-04) but understates how much has actually been validated against real devices at this point.

**To reactivate:** Either (a) close out #119 and formally refresh `docs/qa_signoff.md` with current test counts/coverage to retire this item for good, or (b) decide the smoke-test log is the de facto ongoing sign-off mechanism going forward and archive this item as superseded.

---

## 5. Profile Comparison & Diffing

**Originally:** Master spec, Future Phase Features; root `BACKLOG.md`

**What:** Visually or textually compare two PEQ profiles to highlight changes.

**Status:** Not started — future-phase feature, not MVP.

---

## 6. Advanced Filter Types

**Originally:** Master spec, Future Phase Features; root `BACKLOG.md`

**What:** All-Pass filters and specialized shelf variants, if added to WiiM firmware.

**Status:** Not started — blocked on WiiM firmware support.

---

## 7. MainWindow God-Object — Extract Business Logic from GUI Layer (Tech Debt)

**Originally:** Code quality audit (2026-06-28)

**What:** `src/gui/main_window.py` is ~4,470 lines (grown from ~4,270 at the
last audit, confirmed 2026-07-11 during the RoomFit-capability-model/
prober-redesign pass). 25 of its `async def _do_*` methods call adapters/repository
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
`_do_copy_presets_batch`/`_do_copy_presets_batch_multi` (the live
"Copy to Another Device" feature — do not confuse with the deleted
`SecondaryWorkflowManager` methods of similar names, removed in the
2026-06-28 code quality audit as unreachable dead code).

**Mechanism to preserve:** all `_do_*` methods are invoked via
`self._bridge.run_async(self._bridge_wrapper(name, self._do_x(...)))`
from `_on_*` Qt slot handlers — this signal/bridge wiring pattern must be
preserved; only the method body + adapter calls move to the new class,
which then emits its own completion signal back to MainWindow's `_on_*`
handlers (same shape as `SecondaryWorkflowManager.undo_complete` etc.).

**Why deferred:** Not a correctness bug — current code works. Effort is
~Medium, best done incrementally (4-6 methods per pass) rather than
big-bang, to keep each step independently testable.

**Status:** Not started — the file keeps growing as new features land directly in
MainWindow (e.g. `_do_delete_presets`, and most recently the 2026-07-10/11
RoomFit-capability-model/prober-redesign pass, which touched 5 of the comma-source
bug's call sites — all already-flagged `_do_*` extraction candidates,
`_do_preset_export`/`_do_preset_save`/`_do_load_peq_preset` among them — and reduced
their per-method state re-derivation in the process, which should make eventual
extraction slightly easier). That same pass's new orchestration (the Phase 5
source-slot diagnostic, `EQGetSourceModes`) deliberately did **not** add a new
MainWindow `_do_*` method — it went into `SecondaryWorkflowManager` (a new
`fetch_source_slots()`/`source_slots_ready` signal pair) instead, demonstrating the
target pattern this item recommends. Priority: High — recommend tackling Phase 1
(discovery, probing, file imports — 4 methods, lowest risk) before or alongside the
*next* feature that would otherwise add more orchestration to MainWindow. Does not
need to block all feature work, but the rule is now being followed for new
orchestration (see Phase 5 above) even though the extraction itself hasn't started.

**To reactivate:** Start with the 4 Phase-1 methods, write
`test_primary_workflows.py` mirroring `test_secondary_workflows.py`'s
structure, wire signals in a `_setup_secondary_workflows()`-style method,
verify smoke tests still pass, then proceed to the next phase. **Bundle
opportunity:** while moving `_do_list_presets`, also resolve item #3
above (`ProfileRepository.list()` shadows builtin) — rename to
`list_all()` at the same time, since that line is already being touched.

---

## 8. On-Device Preset/Profile Rename via `EQv2Rename`

**Originally:** Surfaced during 2026-07-10 hardware API research (`docs/corrections.md`).

**What:** A rename action in `PresetsDeviceView` (and/or `MyPresetsView` for the on-device side)
that renames a saved PEQ preset or RoomFit profile in place on the device, instead of the current
save-as-new + delete-old workaround.

**Backend status:** `EQv2Rename:{"pluginURI":"...","Name":"<old>","newName":"<new>","EQLevel":<1|2>}`
is hardware-confirmed working (`docs/corrections.md`, 2026-07-10) — clean round-trip verified for
both ordinary PEQ presets and RoomFit profiles, including RoomFit's own calibration profile, on two
device models (WiiM Amp Ultra, WiiM Mini). Not yet wired into `WiiMAdapter` — no
`rename_peq_profile()`/`rename_roomfit_profile()` methods exist. `MyPresetsView`'s existing rename
action is local-repo-only (renames the JSON profile file, not anything on the device).

**Why deferred:** No user request yet; the save-as-new+delete-old workaround already covers the
functional need (it just loses `UpdateAt` and requires two device round-trips instead of one).

**To reactivate:** Add `rename_peq_profile(old_name, new_name)`/`rename_roomfit_profile(old_name,
new_name)` to `WiiMAdapter`, issuing `EQv2Rename` via `encode_wiim_command` (classify it into
`_ROOMFIT_REQUIRES_OMITTED_SOURCE_NAME` in `wiim_commands.py`, matching every other RoomFit command
that takes no `source_name`). Wire a rename action into `PresetsDeviceView`'s per-preset menu.

---

## 9. Shared Base/Mixin for "Optional Embedded Warning" Dialogs (Tech Debt)

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

## 10. Packaged `.exe` Shows a Brief Window Flash on Launch (Known Issue)

**Originally:** Reported by the device owner, 2026-07-11.

**What:** Launching the packaged Windows `.exe` briefly shows a small window that closes
automatically before the main GUI window appears.

**Investigated (2026-07-11), no code change made:** `packaging/wiim_rew_sync_windows.spec:138`
already sets `console=False` (a PE-subsystem-level setting — Windows creates no console for the
process at all when this is set), every documented build path invokes this exact spec, and no
subprocess/`QProcess`/`os.system` call exists anywhere in the startup path
(`packaging/entry_gui.py`, `src/gui/` init). A clean rebuild (removing `build/`/`dist/` and
re-running `pyinstaller packaging/wiim_rew_sync_windows.spec`) was confirmed by the device owner to
not fix it, ruling out a stale-artifact explanation.

**Suspected root cause:** the app is built as a PyInstaller **onefile** exe (confirmed via
`entry_gui.py`'s `sys._MEIPASS` check) — every launch first silently extracts the bundled Python
runtime and Qt libraries to a temp folder before any app code runs. This is a documented source of
a brief window flash on some Windows/AV configurations, independent of the `console=False` setting.

**Why deferred:** The only known fix is switching the spec from a onefile `EXE(...)` build to a
onedir build (`EXE(..., exclude_binaries=True)` + `COLLECT(...)`), which removes the
temp-extraction-at-launch step entirely. This changes distribution from a single `.exe` to an
`.exe` + adjacent folder of files. The device owner declined this tradeoff (2026-07-11) — a single
portable `.exe` is preferred over the flash-free folder distribution.

**To reactivate:** Switch `packaging/wiim_rew_sync_windows.spec` to a onedir build as described
above, update `packaging/README.md`'s build/distribution instructions accordingly, and re-verify
the flash is gone on real hardware before closing this item.

---

## Completed Items (Archive)

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
`WiiMAdapter`/the GUI is now a product-scope question, tracked under
backlog item "1. PEQ / RoomFit Enable/Disable Toggle in GUI" above rather
than as its own open investigation.

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
