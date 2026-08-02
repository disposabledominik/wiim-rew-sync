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
4. Fill in the [sign-off](#7-sign-off) section and commit this file.

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
| `src/translator/` coverage ≥ 90% | ☑ Pass ☐ Fail | actual %: 96.89% |
| `ruff check src/` | ☑ Pass ☐ Fail | |
| `mypy src/` | ☑ Pass ☐ Fail | |
| `mypy src/translator src/models` (strict) | ☑ Pass ☐ Fail | |
| `pip-audit` — direct dependencies clean | ☑ Pass ☐ Fail | |

Do not carry forward numbers from a previous sign-off — re-run every gate fresh.

---

## 3. Prerequisites for manual testing

- At least one WiiM device powered on and reachable on the same network (a RoomFit-capable model —
  Amp Pro/Ultra, Sound, Sound Lite — and a WiiM Mini if you can get both, to cover the PEQ-only path).
- REW (Room EQ Wizard) running on the same machine, with its API enabled, for the REW-pull tests.
- A valid REW EQ `.txt` export file for file-import tests, and a second one (or reuse the first) for
  L/R testing.
- Launch: `python3 packaging/entry_gui.py` or use the latest released version.

**Legend:** `[ ]` not tested · `[P]` passed · `[F]` failed (log the issue number in
`docs/smoke_test_issues.md`) · `[N/A]` not applicable to this environment.

---

## 4. Manual test procedure (GUI)

### Test 1: First Launch & Onboarding
- [P] App launches without crash
- [P] Onboarding overlay appears on first run
- [P] "Get Started" dismisses overlay and shows Connect page
- [P] Step indicator shows wizard steps (Connect, EQ Type, Source, Filters, Review, Push)
- [P] Sidebar shows "Resume Setup" as the active navigation item

### Test 2: Device Discovery
- [P] Connect page shows "Searching for WiiM devices..." spinner
- [P] After ~3-5s, device cards appear with name, model, IP
- [P] Clicking a device card shows "Processing..." in status banner
- [P] After probe completes: step indicator advances, Connect step shows checkmark + device friendly name.
- [P] Sidebar shows device name (actual model, not "WiiM Device")
  NOTE: Two devices can't have identical friendly names (not allowed by WiiM Home app), so there's no manual test for that.

### Test 3: PEQ Flow — Source Selection & Filter Import (Stereo)
- [P] EQ Type page shown (if device supports RoomFit); selecting PEQ advances
- [P] Source page shows audio sources with checkboxes (wifi, bluetooth, line-in, etc.)
- [P] Selecting one or more sources + clicking Continue advances to Filters page
- [P] Filters page shows a File Import / "Pull from REW API" toggle, with a Stereo/L-R radio toggle
  and per-channel Browse button(s) inside File Import mode
- [P] Stereo is selected by default
- [P] Clicking Browse opens native file dialog
- [P] Selecting a valid `.txt` file shows filename next to Browse
- [P] "Continue" button appears and is enabled after file is selected
- [P] Clicking "Continue" advances to Review page with filters loaded

> Filters page no longer offers "Pull from Device" or a RoomFit-profile dropdown inline (removed
> per smoke issues #52/#59) — those flows live under the "Presets on Device" sidebar item only
> (Test 12). If you see either on the Filters page, that's a regression.

### Test 4: PEQ Flow — Filter Import (L/R)
- [P] On Filters page, switching to L/R mode shows Browse L and Browse R buttons
- [P] Selecting a file for L shows its filename
- [P] Selecting a file for R shows its filename
- [P] "Continue" button enabled only when both L and R files are selected
- [P] Clicking "Continue" advances to Review page
- [P] Review page shows L/R tabs in filter table

### Test 5: Review Page (PEQ)
- [P] Filter table shows all 5 columns (Band, Type, Freq, Gain, Q) and uses full available width
- [P] Breadcrumb steps show selected device name / EQ type / source(s) / total number of filters
- [P] "Preview Only", "Export as REW File", and "Save to My Presets" buttons visible
- [P] Dry Run checkbox is visible and toggleable
- [P] Toggling Dry Run the main button changes from "Preview Only" to "Push to Device"

### Test 6: Push to Device (PEQ)
- [P] On Review page, clicking "Push to Device" advances to Push page
- [P] Push page shows progress stepper (Backing up, Writing, Verifying)
- [P] On success: green checkmark, success message, Undo + Export + Save buttons visible
- [P] Push step shows checkmark in step indicator
- [P] Clicking Undo restores previous settings, shows confirmation
- [P] For multi-source push (2+ sources selected on Source page): all sources are written; success
  message reflects all sources; Undo restores every source individually from its own backup

### Test 7: Dry Run (PEQ)
- [P] With Dry Run enabled, clicking "Preview Only" shows push result without writing
- [P] Status message indicates dry run (no device write occurred)
- [P] No Undo button shown (nothing was written)

### Test 8: Export as REW File (Stereo)
- [P] On Review page, clicking "Export as REW File" opens save dialog
- [P] Selecting a path: status banner shows success
- [P] Exported file has `.txt` extension (auto-appended if not typed)
- [P] File content is valid REW format (verify header line)

### Test 9: Export as REW File (L/R)
- [P] With L/R filters loaded, clicking "Export as REW File" shows the export dialog
- [P] Dialog allows setting L and R filenames
- [P] Confirming creates two `.txt` files (`_L.txt` and `_R.txt`)
- [P] Both files are valid REW format

### Test 10: RoomFit Flow
- [P] After device connect (device with RoomFit): EQ Type page shown
- [P] Selecting "RoomFit" skips Source step, advances to Filters page
- [P] Filters page works the same (Stereo/L-R toggle + Browse; no separate RoomFit-pull UI here —
  see Test 12 for pulling an existing RoomFit profile from the device)
- [P] Review page shows filters normally
- [P] Clicking "Push to Device" advances to Name Profile page
- [P] Name Profile page shows text input for profile name, with existing profiles listed (if any)
- [P] Entering a name and confirming advances to Push page; push succeeds with profile saved on device

### Test 11: RoomFit — Overwrite Warning
- [P] On Name Profile page, entering an existing profile name shows an overwrite warning
- [P] If the profile is currently active, the warning states it will stay active with the new
  filters (it does **not** get deactivated — verify the wording doesn't claim otherwise)
- [P] Confirming proceeds with the push anyway
- [P] Undo behaviour: if overwriting an existing profile it will restore the previous filters; if saving a brand-new profile if will activate the previous one

### Test 12: Presets on Device
- [P] Sidebar "Presets on Device" navigates to presets view
- [P] While connected: shows PEQ presets section and RoomFit profiles section
- [P] Selecting a PEQ preset enables Export/Save/Load/Copy buttons; selecting in one section
  deselects the other
- [P] Export: saves as `.txt` (L/R generates dual files)
- [P] Save to My Presets: creates local copy
- [P] Load: brings filters into Review step (Quick Setup dialog if wizard incomplete)
- [P] Copy to another device: shows device picker; copies preset to **all** selected devices, not
  just the first
- [P] Without a device connected: shows "Connect a device to browse..." empty state

### Test 13: My Saved Presets
- [P] Sidebar "My Saved Presets" navigates to presets library
- [P] Shows list of saved presets with name and channel-mode badge
- [P] Selecting a preset shows a bottom-anchored toolbar, in this order: **Load, Copy to Another
  Device, Rename, Duplicate, Delete**
- [P] Load: Quick Setup dialog if needed, then filters appear in Review
- [P] Copy to Another Device: shows device picker, copies to selected device(s)
- [P] Rename: allows inline name edit, persists on confirm
- [P] Duplicate: creates copy with " (copy)" suffix
- [P] Delete: removes preset permanently
- [P] L/R presets show "L/R" badge with Left-channel band count (Right-channel band count is not shown)

### Test 14: Navigation
- [P] Sidebar "Resume Setup" returns to current wizard step from secondary views (no visible change if
  already there — this is by design, not a bug)
- [P] Help > User Guide opens help panel overlay; ✕ button and Escape both close it
- [P] Step indicator: clicking a completed step navigates back to it
- [P] Back-navigation from Push clears completion badges for invalidated steps
- [P] Selecting a new device (back to Connect) resets the flow steps (Connect, EQ Type, Source, Filters, Review, Push)

### Test 15: Settings
- [P] Settings view shows theme selector, log directory, presets directory
- [P] Changing theme applies immediately (Light/Dark/System)
- [P] Support bundle generation works

### Test 16: Error Handling
- [P] Disconnect device from network mid-operation: error shown in banner, app doesn't hang
- [N/A] Close REW while pulling from REW API: error shown
  NOTE: It is difficult to close REW fast enough for this test to be meaningfull.
- [P] Try to push when device unreachable: error shown, not stuck in loading
- [P] Invalid REW file import: error on Filters page status bar with "Dismiss" button.

### Test 17: Concurrent Operation Guard
- [F] While an operation is in progress ("Processing..." shown), other action buttons are disabled
- [F] After the operation completes, buttons work normally again
  NOTE: This doesn't seem to work - e.g. in "Presets on Device" and "My Saved Presets" view all button work during an active operation ("Processing..." shown). Smoke test issue `#243` logged.
  UPDATE (2026-08-02): `#243` was fixed and merged the day after this sign-off (PR #16,
  2026-07-27, per `docs/smoke_test_issues.md`). The `[F]` result above is left as the historical
  record of what this sign-off actually observed on 2026-07-26; re-run at the next sign-off to
  record a `[P]` result against the fix.

### Test 18: Window Close
- [P] With filters loaded, closing the window shows an "Unsaved Changes" dialog
- [P] "Discard and Quit" closes the app; "Continue Working" keeps it open
- [P] With no filters loaded, closing exits directly (no dialog)

### Test 19: Keyboard Shortcuts
- [P] Escape closes help panel
- [P] F1 opens User Guide

### Test 20: REW API Pull (requires REW running)
- [P] Entry points: the sidebar "Pull from REW" item, and the Filters page's "Pull from REW API"
  toggle — both open the same embedded measurement-list view (this is a page, not a modal dialog)
- [P] Available measurements are listed; double-clicking one (or selecting it and clicking Continue)
  loads it into Review
- [P] A Back button returns to the previous state without loading anything
- [P] If REW is not running: error shown, "REW is not connected" — app stays otherwise usable

### Test 21: Diagnostics Panel
- [P] "View" > "Diagnostics" Menu access opens Diagnostics panel
- [P] "Send" button sends a raw command to the device and displays the response
- [P] Capabilities section shows device info
- [P] Log viewer shows recent API log entries; Refresh button works

### Test 22: Multi-Source Push
- [P] Select 2+ sources on the Source page
- [P] Import a file and push: all selected sources are written; success message reflects all sources
- [P] Undo restores all sources individually from their own backups


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
| 21 | Multi-source push writes to all selected sources with per-source backup | Manual — Test 6/22 |
| 22 | Multi-source Undo restores every source from its own backup | Manual — Test 6/22 |
| 23 | "Copy to another device" with multiple targets pushes to all, not just the first | Automated — `test_smoke_regression_operations.py::test_issue74_copy_batch_multi_iterates_all_devices`; Manual — Test 12/13 |
| 24 | 0Hz/OFF filter correctly disables that band on the wire | Automated — `test_wiim_generator.py::TestModeMapping` |
| 25 | Import exceeding device's max filter count truncates with a warning | Automated — `test_rew_generator.py::TestMaxFilters`, `test_cli.py::test_dry_run_import_surfaces_range_warning` |
| 26 | L/R filters export as two separate `.txt` files | Automated — `test_smoke_regression_operations.py::test_issue29_export_lr_mode_uses_export_dialog`; Manual — Test 9 |
| 27 | Preset saved via "Save to My Presets" preserves channel mode on reload | Automated — `test_smoke_regression_operations.py` (issues #39/#65) |
| 28 | L/R profile loaded from My Saved Presets sets wizard channel_mode correctly | Automated — `test_smoke_regression_operations.py::test_issue49_recall_profile_lr` |
| 29 | Diagnostics Panel exposes raw HTTP commands and capability dumps | Manual — Test 21 |
| 30 | No network on boot: app opens, "no devices found," My Saved Presets still accessible | Automated — `test_profile_repository.py` (filesystem only) |
| 31 | WiiM Mini: EQ Type step skipped, PEQ-only | Automated — `test_smoke_regression_wizard.py::TestIssue36MiniRoomfitBlocklist::test_roomfit_read_false_forces_peq_only_regardless_of_model`; Manual — Test 10 |
| 32 | Amp Pro/Ultra/Sound/Sound Lite: `supports_peq/lr_filters/roomfit = True` | Automated — `test_capability_prober.py::TestAcousticCapabilityProbe` (model-agnostic RC-block detection; no per-SKU unit test exists for these exact models); Manual — Test 10 (this sign-off's hardware run confirmed on WiiM Sound and WiiM Amp Ultra, per §7) |

---

## 6. Known non-blocking items

These are deliberate `WONTFIX`es from `docs/smoke_test_issues.md` — do not re-log them as new bugs:

- **Transparent window backgrounds under WSL2/WSLg** (#3) — a Wayland compositor artifact, resolves
  on a native Windows build. Not reproducible outside WSL2.
- **Sidebar "Resume Setup" (nav key `home`) appears to do nothing** (#17) — working as designed: it returns to the current
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
| Date | 26.07.2026. |
| Tester | disposabledominik |
| App version (Help > About, or `wiim-rew-sync --version`) | v0.5.0 |
| Environment (OS, Python version) | Win11, Python 3.12.3 |
| Devices tested against (model, firmware) | WiiM Sound 5.2.820956, WiiM Amp Ultra 5.2.820839, WiiM Mini 4.6.819436 |
| REW available for testing? | ☑ Yes ☐ No |

**Verdict**

| Check | Status |
|-------|--------|
| All automated quality gates (§2) pass | ☑ |
| All applicable manual tests (§4) pass, or failures logged with issue numbers | ☑ |
| Every scenario in the traceability matrix (§5) resolves to a passing test or a documented, waived gap | ☑ |
| No open, unwaived scenario gaps | ☑ |

**Overall: ☐ PASS — ready to release ☑ PASS WITH WAIVED GAPS (list below) ☐ FAIL (list blockers below)**

Waived gaps / blockers:
- Issue `#243` was a waived gap as of this sign-off (2026-07-26); fixed and merged the following
  day (PR #16, 2026-07-27) -- no longer an open gap as of 2026-08-02. See Test 17 above.

---

Signed off by: disposabledominik

Date: 26.07.2026.
