# Backlog — Deferred Features

Items moved here from active specs. They are not planned for the current release but may be reconsidered in future versions. Backend support may already exist (noted per item).

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

## 3. ~~Channel Mode Enum~~ (DONE)

**Completed:** 2025-07-01

**What was done:** Introduced `ChannelMode` enum in `src/models/channel_mode.py` with `STEREO`/`LR` values and properties: `wire_value`, `profile_value`, `display_value`, `is_lr`. Used `Annotated[ChannelMode, BeforeValidator(...)]` (`ChannelModeField`) in Pydantic models for seamless string coercion. Replaced 38+ string comparison sites across 15 production files. `is_lr_mode()` retained as a backwards-compatible wrapper accepting both `str` and `ChannelMode`.

---

## ~~6. Remove Redundant `state.current_filters` for L/R Mode~~ (DONE)

**Completed:** 2025-07-01

**What was done:** Added computed `WizardState.filters` property that returns `filters_l + filters_r` when in L/R mode, or `current_filters` for stereo. This eliminates the desync risk — the property always computes the correct combined list from the authoritative per-channel fields. Bundled with item #3 as planned.

---

## 4. Backward-Compat `ValidationError` Re-export in wiim_parser (Tech Debt)

**Originally:** Code quality audit (2026-06-22)

**What:** `src/translator/wiim_parser.py` imports and re-exports `ValidationError` with `# noqa: F401 — kept for backward compat` even though the module never raises it. This exists solely so external code that does `from src.translator.wiim_parser import ValidationError` still works.

**Why deferred:** Removing it risks breaking any consumer that imports from this location. The cost of keeping it is one import line. Zero functional impact.

**To reactivate:** Audit all consumers (internal and potential external), remove the import, update any broken references. Low priority.

---

## 5. `ProfileRepository.list()` Shadows Builtin (Tech Debt)

**Originally:** Code quality audit (2026-06-22)

**What:** The `list()` method on `ProfileRepository` shadows the Python builtin `list`, requiring `import builtins` + `builtins.list[Profile]` for type annotations within the class. Renaming to `list_all()` or `get_all()` would eliminate this workaround.

**Why deferred:** Renaming a public method on `ProfileRepository` would break the GUI layer, tests, and any code that calls `.list()`. Cosmetic improvement with non-trivial migration effort.

**To reactivate:** Rename method to `list_all()`, update all call sites (~8 locations in GUI + tests). Bundle with other repository refactoring if it arises.

## 6. Perform manual QA.

## 7. Refactor Dark and Light styles to make them consistent - see if there is any chance to consolidate for easier maintenance. Review in-line styles in code, and remove where it makes sense.