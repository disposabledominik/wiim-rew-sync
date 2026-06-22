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

## 3. Channel Mode Enum (Tech Debt)

**Originally:** Code quality audit (2026-06-22)

**What:** The codebase uses multiple string conventions for the same channel concept: `"stereo"` / `"lr"` (PEQSettings), `"stereo"` / `"left"` / `"right"` (Profile), `"Stereo"` / `"L/R"` (wire format). A `ChannelMode` enum with `.wire_value`, `.profile_value`, and `.settings_value` properties would eliminate ad-hoc normalization scattered across `shared_helpers.is_lr_mode()` and multiple comparison sites.

**Why deferred:** Large surface area refactor touching models, adapters, GUI, repository, and persisted JSON profiles (requires migration). High regression risk for cosmetic improvement. Current ad-hoc normalization is tested and working.

**Backend status:**
- `is_lr_mode()` in `shared_helpers.py` handles all known variants
- At least 6 modules compare channel mode strings directly

**To reactivate:** Define a `ChannelMode` enum in `src/models/`, add `.wire_value` / `.profile_value` computed properties, migrate all comparison sites, add schema migration for persisted profiles. Target for a major version bump.

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
