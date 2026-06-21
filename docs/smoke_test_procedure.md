# GUI Smoke Test Procedure

Manual test procedure for validating the WiiM ↔ REW PEQ Sync Tool GUI.
Run after any significant GUI changes. Each test covers a complete user flow.

## Prerequisites

- At least one WiiM device powered on and reachable on the same network
- REW (Room EQ Wizard) running on the same machine (optional, for REW API tests)
- A valid REW EQ .txt export file available (for file import tests)
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
- [ ] Step indicator shows wizard steps (Connect, Source, Filters, Review, Push)
- [ ] Sidebar shows "Home" as active navigation item

---

## Test 2: Device Discovery (PEQ-only device)

- [ ] Connect page shows "Searching for WiiM devices..." spinner
- [ ] After ~1-2s, device cards appear with name, model, IP
- [ ] Clicking a device card shows "Processing..." in status banner
- [ ] After probe completes: step indicator advances, Connect step shows checkmark + "Connected"
- [ ] Sidebar shows device name (not "WiiM Device")
- [ ] Source page is displayed with available sources (wifi, bluetooth, etc.)

---

## Test 3: Source Selection & Filter Loading (PEQ)

- [ ] Source page shows available sources with radio buttons / cards
- [ ] Selecting a source + clicking Continue advances to Filters page
- [ ] Filters page shows 3 option cards: "Import from REW File", "Pull from Device", "Pull from REW API"
- [ ] Drag-drop zone visible for .txt files

---

## Test 4: Pull from Device (PEQ)

- [ ] Clicking "Pull from Device" shows "Pulling filters from device..." progress
- [ ] After ~1s: advances to Review page
- [ ] Review page shows filter table with ALL 5 columns visible (Band, Type, Freq, Gain, Q)
- [ ] Filter table uses full available width (not squished to 400px)
- [ ] Summary header shows "X bands → DeviceName / source / Stereo"
- [ ] Status banner shows "X filters loaded — ready for review"
- [ ] "Push to Device" and "Export as REW File" buttons visible

---

## Test 5: Import from REW File

- [ ] Clicking "Import from REW File" opens a native file dialog
- [ ] Selecting a valid .txt file: advances to Review page with filters loaded
- [ ] Selecting an invalid file: error shown on FiltersPage with "Try Again" button
- [ ] Clicking "Try Again" resets page to initial state (option cards visible)
- [ ] Cancelling the file dialog: no change, stays on Filters page

---

## Test 6: Push to Device

- [ ] On Review page, clicking "Push to Device" advances to Push page
- [ ] Push page shows progress stepper (Backing up, Writing, Verifying)
- [ ] On success: green checkmark, "Filters pushed successfully", OK + Undo buttons
- [ ] Clicking OK returns to Filters page
- [ ] Status banner shows success message

---

## Test 7: Export as REW File

- [ ] On Review page, clicking "Export as REW File" opens save dialog
- [ ] Selecting a path: status banner shows "File exported successfully"
- [ ] Cancelling the dialog: no change, stays on Review page
- [ ] Exported file is valid REW format (open in text editor to verify header)

---

## Test 8: RoomFit Flow (requires device with roomfit_level >= 2)

- [ ] After device connect: EQ Type page shown with PEQ and RoomFit options
- [ ] Selecting "RoomFit" advances to Filters page with RoomFit UI (profile dropdown visible, not PEQ options)
- [ ] Step indicator shows "Connected" checkmark on Connect step
- [ ] Pull from Device works without "No source selected" error

---

## Test 9: Navigation

- [ ] Sidebar "Home" button returns to current wizard step from secondary views
- [ ] Sidebar "Presets on Device" navigates to presets view
- [ ] Sidebar "My Saved Presets" navigates to saved presets view
- [ ] Sidebar "Settings" navigates to settings view
- [ ] Help > User Guide opens help view
- [ ] Help view ✕ button returns to wizard
- [ ] Escape key returns from help view to wizard
- [ ] Step indicator: clicking a completed step navigates back to it

---

## Test 10: Presets on Device

- [ ] Navigating to "Presets on Device" while connected: shows preset list OR "not available" message
- [ ] If presets exist: list items show name + channel mode
- [ ] Action buttons (Export, Save, Load, Copy) enable/disable based on selection
- [ ] Without device connected: shows "Connect a device to browse..." empty state

---

## Test 11: Settings

- [ ] Settings view shows theme selector, log directory, presets directory, etc.
- [ ] Changing theme applies immediately (Light/Dark/System)
- [ ] Settings persist after app restart

---

## Test 12: Error Handling

- [ ] Disconnect device from network mid-operation: error shown in banner ("Device not responding" or "Could not reach device")
- [ ] Close REW while pulling from REW API: error shown ("REW is not connected")
- [ ] Try to push when device unreachable: error shown, not stuck in loading state
- [ ] 30-second operation timeout: after 30s of no response, shows "Operation timed out" and re-enables buttons

---

## Test 13: Concurrent Operation Guard

- [ ] While an operation is in progress (Processing... shown), clicking another action button does nothing (no double-submit)
- [ ] After operation completes, buttons work normally again

---

## Test 14: Window Close

- [ ] With filters loaded, closing the window shows "Unsaved Changes" dialog
- [ ] Clicking "Discard" closes the app
- [ ] Clicking "Cancel" keeps the app open
- [ ] With no filters loaded, closing the window exits directly (no dialog)

---

## Test 15: Keyboard Shortcuts

- [ ] Ctrl+R triggers device refresh/discovery
- [ ] Ctrl+Enter on Review page triggers push
- [ ] Escape dismisses help view
- [ ] Escape cancels active operation (when cancel button is shown)
- [ ] F1 opens User Guide

---

## Test 16: REW API Pull (requires REW running)

- [ ] Clicking "Pull from REW API" shows "Connecting to REW..." progress
- [ ] If REW is running: measurement picker dialog appears
- [ ] Selecting a measurement and clicking OK: filters loaded into Review
- [ ] Clicking Cancel on measurement picker: shows "Selection cancelled" briefly
- [ ] If REW not running: error shown "REW is not connected"
- [ ] If no measurements in REW: info "No measurements found in REW"
