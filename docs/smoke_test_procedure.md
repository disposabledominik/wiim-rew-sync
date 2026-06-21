# GUI Smoke Test Procedure

Manual test procedure for validating the WiiM ↔ REW PEQ Sync Tool GUI.
Run after any significant GUI changes. Each test covers a complete user flow.

## Prerequisites

- At least one WiiM device powered on and reachable on the same network
- REW (Room EQ Wizard) running on the same machine (optional, for REW API tests)
- A valid REW EQ .txt export file available (for file import tests)
- A second REW .txt file for L/R testing (or use the same file for both channels)
- Launch: `python3 packaging/entry_gui.py`

## Test Legend

- [ ] = Not tested yet
- [P] = Passed
- [F] = Failed (note issue number)

---

## Test 1: First Launch & Onboarding

- [ ] App launches without crash
- [ ] Onboarding overlay appears on first run
- [ ] "Get Started" dismisses overlay and shows Connect page
- [ ] Step indicator shows wizard steps (Connect, EQ Type, Source, Filters, Review, Push)
- [ ] Sidebar shows "Home" as active navigation item

---

## Test 2: Device Discovery

- [ ] Connect page shows "Searching for WiiM devices..." spinner
- [ ] After ~3-5s, device cards appear with name, model, IP
- [ ] Clicking a device card shows "Processing..." in status banner
- [ ] After probe completes: step indicator advances, Connect step shows checkmark + "Connected"
- [ ] Sidebar shows device name (actual model, not "WiiM Device")

---

## Test 3: PEQ Flow — Source Selection & Filter Import (Stereo)

- [ ] EQ Type page shown (if device supports RoomFit); selecting PEQ advances
- [ ] Source page shows audio sources with checkboxes (wifi, bluetooth, line-in, etc.)
- [ ] Selecting one or more sources + clicking Continue advances to Filters page
- [ ] Filters page shows Stereo/L/R radio toggle and Browse button
- [ ] Stereo is selected by default
- [ ] Clicking Browse opens native file dialog
- [ ] Selecting a valid .txt file shows filename next to Browse
- [ ] "Next" button appears and is enabled after file is selected
- [ ] Clicking "Next" advances to Review page with filters loaded

---

## Test 4: PEQ Flow — Filter Import (L/R)

- [ ] On Filters page, switching to L/R mode shows Browse L and Browse R buttons
- [ ] Selecting a file for L shows its filename
- [ ] Selecting a file for R shows its filename
- [ ] "Import" button enabled only when both L and R files are selected
- [ ] Clicking "Import" advances to Review page
- [ ] Review page shows L/R tabs in filter table

---

## Test 5: Review Page (PEQ)

- [ ] Filter table shows ALL 5 columns (Band, Type, Freq, Gain, Q)
- [ ] Filter table uses full available width (not squished)
- [ ] Summary header shows "X bands → DeviceName / source / Stereo" (or L/R)
- [ ] "Push to Device" and "Export as REW File" and "Save to My Presets" buttons visible
- [ ] Dry Run checkbox is visible and toggleable
- [ ] Toggling Dry Run shows "DRY RUN" badge, button changes to "Preview Only"

---

## Test 6: Push to Device (PEQ)

- [ ] On Review page, clicking "Push to Device" advances to Push page
- [ ] Push page shows progress stepper (Backing up, Writing, Verifying)
- [ ] On success: green checkmark, success message, Undo + Export + Save buttons visible
- [ ] Push step shows checkmark in step indicator
- [ ] Clicking Undo restores previous settings, shows confirmation
- [ ] For multi-source push: all sources are written; Undo restores all

---

## Test 7: Dry Run (PEQ)

- [ ] With Dry Run enabled, clicking "Preview Only" shows push result without writing
- [ ] Status message indicates dry run (no device write occurred)
- [ ] No Undo button shown (nothing was written)

---

## Test 8: Export as REW File (Stereo)

- [ ] On Review page, clicking "Export as REW File" opens save dialog
- [ ] Selecting a path: status banner shows success
- [ ] Exported file has .txt extension (auto-appended if not typed)
- [ ] File content is valid REW format (verify header line)

---

## Test 9: Export as REW File (L/R)

- [ ] With L/R filters loaded, clicking "Export as REW File" shows ExportDialog
- [ ] ExportDialog allows setting L and R filenames
- [ ] Confirming creates two .txt files (_L.txt and _R.txt)
- [ ] Both files are valid REW format

---

## Test 10: RoomFit Flow

- [ ] After device connect (device with RoomFit): EQ Type page shown
- [ ] Selecting "RoomFit" skips Source step, advances to Filters page
- [ ] Filters page works the same (Stereo/L/R toggle + Browse)
- [ ] Review page shows filters normally
- [ ] Clicking "Push to Device" advances to Name Profile page
- [ ] Name Profile page shows text input for profile name
- [ ] Existing profiles shown in list (if any on device)
- [ ] Entering a name and confirming advances to Push page
- [ ] Push succeeds with profile saved on device

---

## Test 11: RoomFit — Overwrite Warning

- [ ] On Name Profile page, entering an existing profile name shows overwrite warning
- [ ] If profile is active, additional warning about deactivation shown
- [ ] Confirming proceeds with push anyway
- [ ] Undo available after overwriting existing profile; hidden for new profile

---

## Test 12: Presets on Device

- [ ] Sidebar "Presets on Device" navigates to presets view
- [ ] While connected: shows PEQ presets section and RoomFit profiles section
- [ ] Selecting a PEQ preset enables Export/Save/Load/Copy buttons
- [ ] Selecting in one section deselects the other section
- [ ] Export: saves as .txt (L/R generates dual files)
- [ ] Save to My Presets: creates local copy, refreshes list
- [ ] Load: brings filters into Review step (Quick Setup dialog if wizard incomplete)
- [ ] Copy to another device: shows device picker, copies preset to selected device(s)
- [ ] Without device connected: shows "Connect a device to browse..." empty state

---

## Test 13: My Saved Presets

- [ ] Sidebar "My Saved Presets" navigates to presets library
- [ ] Shows list of saved presets with name and channel mode badge
- [ ] Selecting a preset shows toolbar (Load, Rename, Duplicate, Delete)
- [ ] Load: Quick Setup dialog if needed, then filters appear in Review
- [ ] Rename: allows inline name edit, persists on confirm
- [ ] Duplicate: creates copy with " (copy)" suffix
- [ ] Delete: removes preset permanently
- [ ] L/R presets show "L/R" badge with per-channel band count

---

## Test 14: Navigation

- [ ] Sidebar "Home" returns to current wizard step from secondary views
- [ ] Help > User Guide opens help panel overlay
- [ ] Help panel ✕ button returns to previous view
- [ ] Escape key closes help panel
- [ ] Step indicator: clicking a completed step navigates back to it
- [ ] Back-navigation from Push clears completion badges for invalidated steps
- [ ] Selecting a new device (back to Connect) resets flow type

---

## Test 15: Settings

- [ ] Settings view shows theme selector, log directory, presets directory
- [ ] Changing theme applies immediately (Light/Dark/System)
- [ ] Support bundle generation works

---

## Test 16: Error Handling

- [ ] Disconnect device from network mid-operation: error shown in banner
- [ ] Close REW while pulling from REW API: error shown
- [ ] Try to push when device unreachable: error shown, not stuck in loading
- [ ] Invalid REW file import: error on Filters page with "Try Again" button
- [ ] "Try Again" resets Filters page to initial state

---

## Test 17: Concurrent Operation Guard

- [ ] While an operation is in progress ("Processing..." shown), other action buttons disabled
- [ ] After operation completes, buttons work normally again

---

## Test 18: Window Close

- [ ] With filters loaded, closing the window shows "Unsaved Changes" dialog
- [ ] Clicking "Discard" closes the app
- [ ] Clicking "Cancel" keeps the app open
- [ ] With no filters loaded, closing exits directly (no dialog)

---

## Test 19: Keyboard Shortcuts

- [ ] Ctrl+Enter on Review page triggers push
- [ ] Escape closes help panel
- [ ] F1 opens User Guide

---

## Test 20: REW API Pull (requires REW running)

- [ ] From Presets on Device or sidebar workflow: "Pull from REW API" connects to REW
- [ ] Measurement picker dialog appears with available measurements
- [ ] Selecting a measurement and clicking OK: filters loaded into Review
- [ ] Clicking Cancel on measurement picker: returns to previous state
- [ ] If REW not running: error shown "REW is not connected"

---

## Test 21: Diagnostics Panel

- [ ] Menu access opens Diagnostics panel
- [ ] "Send" button sends raw command to device and displays response
- [ ] Capabilities section shows device info
- [ ] Log viewer shows recent API log entries
- [ ] Refresh button works for logs

---

## Test 22: Multi-Source Push

- [ ] Select 2+ sources on Source page
- [ ] Import file and push: all selected sources are written
- [ ] Success message reflects all sources
- [ ] Undo restores all sources individually from their backups
