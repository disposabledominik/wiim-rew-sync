# Manual QA & Sign-off Guide

This document is the single reference for running final manual QA and signing off a release of the
WiiM ↔ REW PEQ Sync Tool. It supersedes `docs/qa.md`, the previous `docs/qa_signoff.md` (dated
2026-06-15), and `docs/smoke_test_procedure.md`, which were three separate, increasingly stale
documents covering the same release-gate activity. Use this one going forward; update it in place
each time you sign off a release rather than creating a new doc.

`docs/smoke_test_issues.md` remains the separate, ongoing bug tracker for issues found during
testing — keep logging new GUI bugs there (per CLAUDE.md, fix + status update in the same commit).
This document is about the release-gate *process*, not day-to-day bug tracking.

---

## 1. How to use this document

1. Run the [automated quality gates](#2-automated-quality-gates) and fill in the results table.
2. Work through the [manual test procedure](#4-manual-test-procedure-gui) against real WiiM hardware
   (and REW where noted), marking each checkbox `[P]`/`[F]`/`[N/A]`.
3. Cross-check the [scenario traceability matrix](#5-scenario-traceability-matrix) — every QA
   scenario must resolve to either a passing automated test or a passing manual test step above.
   Any scenario with neither is a gap; log it and don't sign off until it's closed or explicitly
   waived.
4. Fill in the [sign-off](#6-sign-off) section and commit this file.

---

## 2. Automated quality gates

Run from WSL2 Ubuntu bash (`python3`/`pip3`), per CLAUDE.md. Never pipe these through `tail`/`grep` —
the full suite can take 10-20 minutes and will look like it hung; absence of `FAILED` lines in the
final summary means it passed.

```bash
python3 -m pytest --no-header -q                    # full suite; coverage gate: src/translator ≥ 90%
python3 -m ruff check src/                           # lint — zero errors required
python3 -m mypy src/                                 # type check — zero errors required (repo-wide)
python3 -m mypy src/translator src/models            # strict-mode subset, run separately per pyproject.toml
pip-audit                                            # dependency vulnerability scan (direct deps only matter for packaging)
```

**Results (fill in at sign-off time):**

| Gate | Result | Notes |
|------|--------|-------|
| Full test suite (`pytest --no-header -q`) | ☐ Pass ☐ Fail | total / passed / failed: |
| `src/translator/` coverage ≥ 90% | ☐ Pass ☐ Fail | actual %: |
| `ruff check src/` | ☐ Pass ☐ Fail | |
| `mypy src/` | ☐ Pass ☐ Fail | |
| `mypy src/translator src/models` (strict) | ☐ Pass ☐ Fail | |
| `pip-audit` — direct dependencies clean | ☐ Pass ☐ Fail | |

Do not carry forward numbers from a previous sign-off — re-run every gate fresh; the codebase moves
fast enough (60+ GUI fixes landed between the last two sign-off attempts) that a stale count is
worse than no count.

---

## 3. Prerequisites for manual testing

- At least one WiiM device powered on and reachable on the same network (a RoomFit-capable model —
  Amp Pro/Ultra, Sound, Sound Lite — and a WiiM Mini if you can get both, to cover the PEQ-only path).
- REW (Room EQ Wizard) running on the same machine, with its API enabled, for the REW-pull tests.
- A valid REW EQ `.txt` export file for file-import tests, and a second one (or reuse the first) for
  L/R testing.
- Launch: `python3 packaging/entry_gui.py`

**Legend:** `[ ]` not tested · `[P]` passed · `[F]` failed (log the issue number in
`docs/smoke_test_issues.md`) · `[N/A]` not applicable to this environment.

---

## 4. Manual test procedure (GUI)

### Test 1: First Launch & Onboarding
- [ ] App launches without crash
- [ ] Onboarding overlay appears on first run
- [ ] "Get Started" dismisses overlay and shows Connect page
- [ ] Step indicator shows wizard steps (Connect, EQ Type, Source, Filters, Review, Push)
- [ ] Sidebar shows "Home" as active navigation item

### Test 2: Device Discovery
- [ ] Connect page shows "Searching for WiiM devices..." spinner
- [ ] After ~3-5s, device cards appear with name, model, IP
- [ ] Clicking a device card shows "Processing..." in status banner
- [ ] After probe completes: step indicator advances, Connect step shows checkmark + "Connected"
- [ ] Sidebar shows device name (actual model, not "WiiM Device")
- [ ] Two devices with identical friendly names are still distinctly identified by IP in the device
  cards (requires 2+ physical devices — see scenario 22 in the traceability matrix if unavailable)

### Test 3: PEQ Flow — Source Selection & Filter Import (Stereo)
- [ ] EQ Type page shown (if device supports RoomFit); selecting PEQ advances
- [ ] Source page shows audio sources with checkboxes (wifi, bluetooth, line-in, etc.)
- [ ] Selecting one or more sources + clicking Continue advances to Filters page
- [ ] Filters page shows a File Import / "Pull from REW API" toggle, with a Stereo/L-R radio toggle
  and per-channel Browse button(s) inside File Import mode
- [ ] Stereo is selected by default
- [ ] Clicking Browse opens native file dialog
- [ ] Selecting a valid `.txt` file shows filename next to Browse
- [ ] "Next" button appears and is enabled after file is selected
- [ ] Clicking "Next" advances to Review page with filters loaded

> Filters page no longer offers "Pull from Device" or a RoomFit-profile dropdown inline (removed
> per smoke issues #52/#59) — those flows live under the "Presets on Device" sidebar item only
> (Test 12). If you see either on the Filters page, that's a regression.

### Test 4: PEQ Flow — Filter Import (L/R)
- [ ] On Filters page, switching to L/R mode shows Browse L and Browse R buttons
- [ ] Selecting a file for L shows its filename
- [ ] Selecting a file for R shows its filename
- [ ] "Import" button enabled only when both L and R files are selected
- [ ] Clicking "Import" advances to Review page
- [ ] Review page shows L/R tabs in filter table

### Test 5: Review Page (PEQ)
- [ ] Filter table shows all 5 columns (Band, Type, Freq, Gain, Q) and uses full available width
- [ ] Summary header shows "X bands → DeviceName / source / Stereo" (or L/R)
- [ ] "Push to Device", "Export as REW File", and "Save to My Presets" buttons visible
- [ ] Dry Run checkbox is visible and toggleable
- [ ] Toggling Dry Run shows "DRY RUN" badge, button changes to "Preview Only"

### Test 6: Push to Device (PEQ)
- [ ] On Review page, clicking "Push to Device" advances to Push page
- [ ] Push page shows progress stepper (Backing up, Writing, Verifying)
- [ ] On success: green checkmark, success message, Undo + Export + Save buttons visible
- [ ] Push step shows checkmark in step indicator
- [ ] Clicking Undo restores previous settings, shows confirmation
- [ ] For multi-source push (2+ sources selected on Source page): all sources are written; success
  message reflects all sources; Undo restores every source individually from its own backup

### Test 7: Dry Run (PEQ)
- [ ] With Dry Run enabled, clicking "Preview Only" shows push result without writing
- [ ] Status message indicates dry run (no device write occurred)
- [ ] No Undo button shown (nothing was written)

### Test 8: Export as REW File (Stereo)
- [ ] On Review page, clicking "Export as REW File" opens save dialog
- [ ] Selecting a path: status banner shows success
- [ ] Exported file has `.txt` extension (auto-appended if not typed)
- [ ] File content is valid REW format (verify header line)

### Test 9: Export as REW File (L/R)
- [ ] With L/R filters loaded, clicking "Export as REW File" shows the export dialog
- [ ] Dialog allows setting L and R filenames
- [ ] Confirming creates two `.txt` files (`_L.txt` and `_R.txt`)
- [ ] Both files are valid REW format

### Test 10: RoomFit Flow
- [ ] After device connect (device with RoomFit): EQ Type page shown
- [ ] Selecting "RoomFit" skips Source step, advances to Filters page
- [ ] Filters page works the same (Stereo/L-R toggle + Browse; no separate RoomFit-pull UI here —
  see Test 12 for pulling an existing RoomFit profile from the device)
- [ ] Review page shows filters normally
- [ ] Clicking "Push to Device" advances to Name Profile page
- [ ] Name Profile page shows text input for profile name, with existing profiles listed (if any)
- [ ] Entering a name and confirming advances to Push page; push succeeds with profile saved on device

### Test 11: RoomFit — Overwrite Warning
- [ ] On Name Profile page, entering an existing profile name shows an overwrite warning
- [ ] If the profile is currently active, the warning states it will stay active with the new
  filters (it does **not** get deactivated — verify the wording doesn't claim otherwise)
- [ ] Confirming proceeds with the push anyway
- [ ] Undo is available after overwriting an existing profile; hidden when saving as a brand-new profile

### Test 12: Presets on Device
- [ ] Sidebar "Presets on Device" navigates to presets view
- [ ] While connected: shows PEQ presets section and RoomFit profiles section
- [ ] Selecting a PEQ preset enables Export/Save/Load/Copy buttons; selecting in one section
  deselects the other
- [ ] Export: saves as `.txt` (L/R generates dual files)
- [ ] Save to My Presets: creates local copy, refreshes list
- [ ] Load: brings filters into Review step (Quick Setup dialog if wizard incomplete)
- [ ] Copy to another device: shows device picker; copies preset to **all** selected devices, not
  just the first
- [ ] Without a device connected: shows "Connect a device to browse..." empty state

### Test 13: My Saved Presets
- [ ] Sidebar "My Saved Presets" navigates to presets library
- [ ] Shows list of saved presets with name and channel-mode badge
- [ ] Selecting a preset shows a bottom-anchored toolbar, in this order: **Load, Copy to Another
  Device, Rename, Duplicate, Delete**
- [ ] Load: Quick Setup dialog if needed, then filters appear in Review
- [ ] Copy to Another Device: shows device picker, copies to selected device(s)
- [ ] Rename: allows inline name edit, persists on confirm
- [ ] Duplicate: creates copy with " (copy)" suffix
- [ ] Delete: removes preset permanently
- [ ] L/R presets show "L/R" badge with per-channel band count

### Test 14: Navigation
- [ ] Sidebar "Home" returns to current wizard step from secondary views (no visible change if
  already there — this is by design, not a bug)
- [ ] Help > User Guide opens help panel overlay; ✕ button and Escape both close it
- [ ] Step indicator: clicking a completed step navigates back to it
- [ ] Back-navigation from Push clears completion badges for invalidated steps
- [ ] Selecting a new device (back to Connect) resets flow type to PEQ

### Test 15: Settings
- [ ] Settings view shows theme selector, log directory, presets directory
- [ ] Changing theme applies immediately (Light/Dark/System)
- [ ] Support bundle generation works

### Test 16: Error Handling
- [ ] Disconnect device from network mid-operation: error shown in banner, app doesn't hang
- [ ] Close REW while pulling from REW API: error shown
- [ ] Try to push when device unreachable: error shown, not stuck in loading
- [ ] Invalid REW file import: error on Filters page with "Try Again" button; "Try Again" resets the
  page to its initial state

### Test 17: Concurrent Operation Guard
- [ ] While an operation is in progress ("Processing..." shown), other action buttons are disabled
- [ ] After the operation completes, buttons work normally again

### Test 18: Window Close
- [ ] With filters loaded, closing the window shows an "Unsaved Changes" dialog
- [ ] "Discard" closes the app; "Cancel" keeps it open
- [ ] With no filters loaded, closing exits directly (no dialog)

### Test 19: Keyboard Shortcuts
- [ ] Ctrl+Enter on Review page triggers push
- [ ] Escape closes help panel
- [ ] F1 opens User Guide

### Test 20: REW API Pull (requires REW running)
- [ ] Entry points: the sidebar "Pull from REW" item, and the Filters page's "Pull from REW API"
  toggle — both open the same embedded measurement-list view (this is a page, not a modal dialog)
- [ ] Available measurements are listed; double-clicking one (or selecting it and clicking Continue)
  loads it into Review
- [ ] A Back button returns to the previous state without loading anything
- [ ] If REW is not running: error shown, "REW is not connected" — app stays otherwise usable

### Test 21: Diagnostics Panel
- [ ] Menu access opens Diagnostics panel
- [ ] "Send" button sends a raw command to the device and displays the response
- [ ] Capabilities section shows device info
- [ ] Log viewer shows recent API log entries; Refresh button works

### Test 22: Multi-Source Push
- [ ] Select 2+ sources on the Source page
- [ ] Import a file and push: all selected sources are written; success message reflects all sources
- [ ] Undo restores all sources individually from their own backups

### Test 23: Multiroom Group (requires 2+ physical devices in a group)
- [ ] Pushing PEQ to a slave device in a multiroom group targets that specific device only — PEQ is
  per-device, never applied group-wide

---

## 5. Scenario traceability matrix

Every scenario must map to at least one automated test **or** one manual test step above. Automated
test names below are reference pointers from the last time they were checked — re-verify they still
exist and pass rather than trusting the name; the suite has changed significantly since these were
first written. `test_smoke_regression_operations.py` and `test_smoke_regression_wizard.py` carry
most of the GUI-behavior regression coverage that grew out of `docs/smoke_test_issues.md`.

| # | Scenario | Coverage |
|---|----------|----------|
| 1 | REW import → Canonical, no data loss | Automated — `test_rew_parser.py`, `test_translator.py` (PBT round-trip) |
| 2 | Frequency > 22000 Hz → validation error | Automated — `test_rew_parser.py::TestParseFileFrequencyError` |
| 3 | WiiM device offline → discovery times out gracefully | Automated — `test_capability_prober.py::TestConnectionFailure`, `test_wiim_http.py` |
| 4 | Push → per-source JSON backup saved locally | Automated — `test_safe_write.py::TestSuccessPath` |
| 5 | Read-back variance > 0.05dB → rollback triggered | Automated — `test_safe_write.py::TestVerifyFailureRollbackSuccess` |
| 6 | Verification passes → success, no rollback | Automated — `test_safe_write.py::TestSuccessPath` |
| 7 | Rollback restores device to pre-push state | Automated — `test_safe_write.py::TestVerifyFailureRollbackSuccess` |
| 8 | WiiM Mini capabilities: PEQ only, RoomFit unsupported, EQ Type step skipped | Automated — `test_capability_prober.py::TestWiiMDeviceDetection`; Manual — Test 10 |
| 9 | Batch-write firmware bypasses sequential writes | Automated — `test_wiim_adapter.py::TestWritePeqBatch` |
| 10 | Dry Run: translate/validate only, no network write, no Undo | Automated — `test_cli.py::test_dry_run_import_valid`; Manual — Test 7 |
| 11 | Device reboots mid-write → safe abort on dropped connection | Manual — Test 16 (hardware, power-cycle required) |
| 12 | REW export matches `Equaliser: Parametric EQ` format | Automated — `test_rew_generator.py`; Manual — Test 8/9 |
| 13 | Logs rotate at 10MB, max 5 archives | Automated — `test_logging.py::TestHandlerConfiguration` |
| 14 | Outdated profile schema migrated on load | Automated — `test_schema_migrator.py`, `test_profile_repository.py::TestSchemaMigration` |
| 15 | Independent L/R pull populates both channel tabs | Automated — `test_wiim_adapter.py::TestReadPeqLR`; Manual — Test 4/5 |
| 16 | Malformed HTTP response → logged, generic error shown | Automated — `test_wiim_http.py` |
| 17 | Rollback itself fails → critical error with manual-recovery instructions | Automated — `test_safe_write.py::TestRollbackFailure` |
| 18 | REW API measurement selection requires explicit pick | Manual — Test 20 (requires running REW) |
| 19 | RoomFit-capable, non-Mini device offers PEQ/RoomFit choice | Manual — Test 10 |
| 20 | RoomFit push requires profile name; overwrite of active profile warns | Manual — Test 10/11 |
| 21 | Multiroom slave write targets that specific device only | Manual — Test 23 (requires multiroom group) |
| 22 | Identical device names distinguished by IP in device cards | Manual — Test 2 (requires 2+ physical devices) |
| 23 | Multi-source push writes to all selected sources with per-source backup | Manual — Test 6/22 |
| 24 | Multi-source Undo restores every source from its own backup | Manual — Test 6/22 |
| 25 | "Copy to another device" with multiple targets pushes to all, not just the first | Automated — `test_smoke_regression_operations.py::test_issue74_copy_batch_multi_iterates_all_devices`; Manual — Test 12/13 |
| 26 | 0Hz/OFF filter correctly disables that band on the wire | Automated — `test_wiim_generator.py::TestModeMapping` |
| 27 | Import exceeding device's max filter count truncates with a warning | Automated — `test_rew_generator.py::TestMaxFilters`, `test_cli.py::test_dry_run_import_surfaces_range_warning` |
| 28 | L/R filters export as two separate `.txt` files | Automated — `test_smoke_regression_operations.py::test_issue29_export_lr_mode_uses_export_dialog`; Manual — Test 9 |
| 29 | Preset saved via "Save to My Presets" preserves channel mode on reload | Automated — `test_smoke_regression_operations.py` (issues #39/#65) |
| 30 | L/R profile loaded from My Saved Presets sets wizard channel_mode correctly | Automated — `test_smoke_regression_operations.py::test_issue49_recall_profile_lr` |
| 31 | Diagnostics Panel exposes raw HTTP commands and capability dumps | Manual — Test 21 |
| 32 | No network on boot: app opens, "no devices found," My Saved Presets still accessible | Automated — `test_profile_repository.py` (filesystem only) |
| 33 | WiiM Mini: EQ Type step skipped, PEQ-only | Automated — `test_smoke_regression_wizard.py::test_wiim_mini_roomfit_level_2_forced_peq_only`; Manual — Test 10 |
| 34 | Amp Pro/Ultra/Sound/Sound Lite: `supports_peq/lr_filters/roomfit = True` | Automated — `test_capability_prober.py::TestWiiMDeviceDetection` |
| 35 | *(duplicate of scenario 10 in the pre-merge docs — removed)* | — |

**Gaps to close before signing off:** scenarios 21 and 22 have no automated coverage and depend on
hardware most single-device test setups won't have (a multiroom group, or two devices sharing a
name). If you can't reproduce that hardware configuration, note it explicitly as a waived scenario
in the sign-off section below rather than silently skipping it.

---

## 6. Known non-blocking items

These are deliberate `WONTFIX`es from `docs/smoke_test_issues.md` — do not re-log them as new bugs:

- **Transparent window backgrounds under WSL2/WSLg** (#3) — a Wayland compositor artifact, resolves
  on a native Windows build. Not reproducible outside WSL2.
- **Sidebar "Home" appears to do nothing** (#17) — working as designed: it returns to the current
  wizard step, so there's no visible change if you're already there.
- **Extra/inapplicable audio sources shown for some models** (#43) — the PEQ engine accepts any
  source name and there's no reliable way to probe which inputs are physically present, so showing
  a superset is harmless.

For anything else found during this pass, log it in `docs/smoke_test_issues.md` with a status and
test reference, per CLAUDE.md's issue-tracking rule (fix + status update land in the same commit).

---

## 7. Sign-off

| Field | Value |
|-------|-------|
| Date | |
| Tester | |
| App version (`pyproject.toml`) | |
| Environment (OS, Python version) | |
| Devices tested against (model, firmware) | |
| REW available for testing? | ☐ Yes ☐ No |

**Verdict**

| Check | Status |
|-------|--------|
| All automated quality gates (§2) pass | ☐ |
| All applicable manual tests (§4) pass, or failures logged with issue numbers | ☐ |
| Every scenario in the traceability matrix (§5) resolves to a passing test or a documented, waived gap | ☐ |
| No open, unwaived scenario gaps | ☐ |

**Overall: ☐ PASS — ready to release ☐ PASS WITH WAIVED GAPS (list below) ☐ FAIL (list blockers below)**

Waived gaps / blockers:

-

Signed off by: ________________________ Date: ________________
