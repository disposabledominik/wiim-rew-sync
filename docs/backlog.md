# Backlog — Deferred Features & Tech Debt

Items moved here from active specs, or noted during code quality audits. Not planned for the
current release but may be reconsidered in future versions. Backend support may already exist
(noted per item).

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
automated suite is at 1181+ tests.

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

## 3. Multi-Source Push: No Automatic Rollback on Partial Failure (Known Limitation)

**What:** `PrimaryWorkflowManager._do_push()`'s PEQ flow writes to each of
`state.selected_sources` in sequence and aborts on the first failure. Each individual source's
write still goes through the full `SafeWrite` 5-step protocol — but if source N fails after
sources 1..N-1 already succeeded, there is no cross-source rollback: the already-written sources
are left in their new state. CLAUDE.md's design principles ("Safety before convenience" /
"automatic rollback on verification failure") read as applying at the whole-push level, not just
per-source, so this is a real gap, not just a UX rough edge.

**Why deferred:** Backup paths for all sources written before the failure are still collected and
returned, so the *user* can manually undo each succeeded source today — the data needed for a fix
already exists, this is a missing automation, not a missing capability. Fixing it properly means
either auto-invoking undo on sources 1..N-1 when source N fails (risk of a rollback-of-a-rollback
failure) or pre-staging backups for all sources before writing any of them — either is a large
enough decision to warrant its own design pass.

**Status:** Not started.

**To reactivate:** Decide whether cross-source auto-rollback is wanted (and how it should behave
if the rollback itself fails), or whether documenting the manual-undo path in the GUI's push
failure message is sufficient. Implement in `PrimaryWorkflowManager._do_push()`'s PEQ branch.

---

## 4. CI Release Pipeline (No Published Download Path)

**What:** There is no `.github/workflows/` (or equivalent CI) in this repo, and no published
GitHub Release with attached binaries. `packaging/README.md` documents how to *build* a standalone
executable per platform, but a non-technical user — this project's own stated target audience —
cannot currently download and run it without someone building it for them first.

**Why deferred:** Setting up automated cross-platform builds (Windows/macOS/Linux each require
building on that OS per `packaging/README.md`) and a release/signing process is new infrastructure,
not a bug fix, and the project is still in the hardware-QA-pending phase (see item 1) — shipping a
polished download experience ahead of that isn't the current priority.

**Status:** Not started.

**To reactivate:** Add a GitHub Actions workflow that builds the three PyInstaller targets (see
`packaging/README.md`'s per-platform build steps) on their respective OS runners and attaches the
artifacts to a GitHub Release, then update `README.md`'s Getting Started section to link the
release page directly instead of pointing at manual build instructions.

---

## Completed / Closed Items (Archive)

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
