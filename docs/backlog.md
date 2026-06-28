# Backlog — Deferred Features & Tech Debt

Items moved here from active specs, or noted during code quality audits. Not planned for the
current release but may be reconsidered in future versions. Backend support may already exist
(noted per item).

---

## 1. PEQ / RoomFit Enable/Disable Toggle in GUI

**Originally:** GUI Redesign Requirement 22, original spec Task 58

**What:** A visible on/off toggle in the UI allowing users to quickly enable or disable PEQ or RoomFit on the connected device for A/B listening tests.

**Why deferred:** The WiiM Home app already provides this functionality. Adding it to the sync tool adds UI clutter without enabling a workflow that isn't already covered. The tool's primary purpose is filter transfer, not device configuration.

**Backend status:**
- ✅ `WiiMAdapter.enable_peq()` / `disable_peq()` / `get_peq_enabled()` — implemented (Task 57)
- ✅ CLI `peq-toggle --device --source --state on|off` — implemented and working
- ⏳ RoomFit toggle — API mechanism unconfirmed (Task 58 not started, requires hardware testing)

**To reactivate:** Restore Requirement 22 to the GUI redesign spec, add `PEQToggle` component back to design.md, and create implementation tasks for the toggle widget and its WizardController wiring.

---

## 2. RoomFit Enable/Disable API Investigation

**Originally:** Original spec Task 58

**What:** Determine whether RoomFit can be toggled on/off independently via the WiiM HTTP API.

**Why deferred:** Requires physical hardware testing. The PEQ toggle already works via CLI for users who want it. RoomFit toggle has no confirmed API command.

**Backend status:**
- ⏳ Not started — API commands still not found. Investigation steps documented in Task 58 didn't surface the required API calls.
- Uncertainty Protocol applies: if confirmed, implement adapter methods; if not, document as unsupported

**To reactivate:** Reverse-engineer the API call against real hardware. If successful, implement adapter methods and optionally restore the GUI toggle.

---

## 3. Rethink Source Discovery

**Originally:** Pre-GUI phase backlog (root `BACKLOG.md`)

**What:** The WiiM API accepts any source name and returns valid PEQ data regardless of whether the physical input exists. Need a reliable mechanism to show only real inputs.

**Why deferred:** No confirmed API call enumerates real inputs per device/model. `src/cli/main.py` currently falls back to a hardcoded default (`"wifi"`) when no input list is available — see the `# ASSUMPTION` comment there.

**Options to investigate:**
- A per-model list of inputs (and other model-specific attributes), managed via a config file (no app rebuild required)
- `GetAudioInputList` or similar undocumented endpoints on newer firmware
- Maintain a model-to-inputs mapping table (fragile but functional)
- Accept the limitation and let users configure which sources to show (per-device preference)

**To reactivate:** Hardware-test candidate endpoints across WiiM models/firmware; if none work, build the config-file-based mapping approach.

---

## 4. HP/LP Capability Detection and Write-Time Validation

**Originally:** Pre-GUI phase backlog (root `BACKLOG.md`, flagged for review 2026-06-27 — confirmed still applicable, not implemented)

**What:** Add a `supports_hp_lp: bool` flag to `DeviceCapabilities`. During `_probe_peq()`, set it to `True` if mode 3 or 5 is seen in the EQBand response. In `dry-run-import`, warn if the import contains HP/LP filters targeting a device without support.

**Why deferred:** The safe-write verify step already catches the mismatch at write time, so this is a UX improvement (earlier warning) rather than a correctness gap. WiiM Mini currently doesn't support HP/LP; newer firmware may add it.

**Status:** ⏳ Not implemented — `supports_hp_lp` does not yet exist on `DeviceCapabilities` (confirmed 2026-06-27).

**Options to investigate:**
- A per-model list of capabilities managed via a config file (no app rebuild required)

**To reactivate:** Add the capability flag, wire up probing, and add the pre-write warning in dry-run-import.

---

## 5. `ProfileRepository.list()` Shadows Builtin (Tech Debt)

**Originally:** Code quality audit (2026-06-22)

**What:** The `list()` method on `ProfileRepository` shadows the Python builtin `list`, requiring `import builtins` + `builtins.list[Profile]` for type annotations within the class. Renaming to `list_all()` or `get_all()` would eliminate this workaround.

**Why deferred:** Renaming a public method on `ProfileRepository` would break the GUI layer, tests, and any code that calls `.list()`. Cosmetic improvement with non-trivial migration effort.

**Status:** Still present (confirmed 2026-06-28, `src/repository/profile_repository.py:5,166`). Production call sites: 1 internal (`filter_by_tag`), 1 in `main_window.py:1798` inside `_do_list_presets`.

**To reactivate:** Rename method to `list_all()`, update all call sites (~2 production + 4 test locations). Bundle with the MainWindow extraction (backlog item below) — `_do_list_presets` is already a Phase-1 extraction candidate there, so the one production GUI call site gets touched anyway.

---

## 6. Hardware QA Sign-off

**Originally:** `docs/qa_signoff.md` final verdict (2026-06-15)

**What:** Full-flow validation against real WiiM device(s) covering the GUI-era scenarios that can't be automated (multiroom groups, RoomFit push with naming, device reboot mid-write, etc. — see `docs/qa.md` and `docs/qa_signoff.md` §5).

**Why deferred:** Requires physical hardware sessions; software QA (470 tests, 96.52% translator coverage, lint/type-check clean) already passed pre-GUI.

**Status:** ⏳ Pending — not yet executed against the post-GUI build.

**To reactivate:** Run the hardware-required scenarios listed in `docs/qa_signoff.md` §5 against the current build, update the sign-off doc with results.

---

## 7. Profile Comparison & Diffing

**Originally:** Master spec, Future Phase Features; root `BACKLOG.md`

**What:** Visually or textually compare two PEQ profiles to highlight changes.

**Status:** Not started — future-phase feature, not MVP.

---

## 8. Advanced Filter Types

**Originally:** Master spec, Future Phase Features; root `BACKLOG.md`

**What:** All-Pass filters and specialized shelf variants, if added to WiiM firmware.

**Status:** Not started — blocked on WiiM firmware support.

---

## 9. MainWindow God-Object — Extract Business Logic from GUI Layer (Tech Debt)

**Originally:** Code quality audit (2026-06-28)

**What:** `src/gui/main_window.py` is ~159KB / 137 methods / ~3,800 lines.
~18 of its `async def _do_*` methods call adapters/repository directly
(network I/O + data manipulation in a GUI class), violating
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

**Status:** Not started. Priority: High — recommend tackling Phase 1
(discovery, probing, file imports — 4 methods, lowest risk) before or
alongside the *next* feature that would otherwise add more orchestration
to MainWindow, to stop the file from growing further. Does not need to
block all feature work, but adopt the rule now: new orchestration logic
goes into a controller/manager class, never directly into MainWindow.

**To reactivate:** Start with the 4 Phase-1 methods, write
`test_primary_workflows.py` mirroring `test_secondary_workflows.py`'s
structure, wire signals in a `_setup_secondary_workflows()`-style method,
verify smoke tests still pass, then proceed to the next phase. **Bundle
opportunity:** while moving `_do_list_presets`, also resolve item #5
above (`ProfileRepository.list()` shadows builtin) — rename to
`list_all()` at the same time, since that line is already being touched.

---

## Completed Items (Archive)

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
