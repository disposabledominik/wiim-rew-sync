# Import & Push

This is the primary workflow: take a REW measurement and push its filters to
your WiiM device.

## Selecting Sources (PEQ Only)

PEQ filters are per-input. The Source step lists the inputs your device
actually reports as enabled (Wi-Fi, Bluetooth, HDMI, Optical, Line In, and
so on) as checkboxes, so the list differs between models. On a WiiM Mini,
which doesn't report its inputs, a standard list is shown instead.

You can select one or more sources — the same filter set will be pushed to
all selected sources in one operation.

### Channel Modes

When importing from **File Import** or **Pull from REW API** on the Filters
page, choose your channel mode:

- **Stereo** — The same filters are applied to both left and right channels.
  Import a single REW .txt file.
- **Left / Right (L/R)** — Independent filter sets for each channel. Import
  separate files for Left and Right. Use this when your REW measurements
  differ significantly between channels.

(**Device** and **Local Library** sources don't need this choice — the
channel mode is already part of the preset/profile you select.)

## Loading Filters

At the top of the Filters page, an "Import source" dropdown offers four
options — **File Import**, **Pull from REW API**, **Device**, and
**Local Library** — each showing its own panel below the dropdown.

### Import from REW File

With **File Import** selected, choose your channel mode (Stereo or L/R),
then click "Browse..." to open a file dialog.

- **Stereo mode** — Select one .txt file, then click "Continue" to proceed.
- **L/R mode** — Click "Browse..." next to each of "Left channel" and
  "Right channel" to select a file for each. Once both are selected, click
  "Continue" to proceed.

The files must be REW EQ text exports (.txt). If the file is invalid, an
error message appears with a "Try Again" button to reset and start over.

### Pull from REW API

Select **Pull from REW API** from the dropdown. If REW is running with its
HTTP API enabled, the panel connects automatically and lists available
measurements to choose from.

### Device

Select **Device** from the dropdown for two ways to get filters straight
from the connected device: click "Current configuration on device" to read
whatever PEQ bands are currently live on your selected source(s), or pick a
row from the list below it — a single merged list of PEQ presets and
RoomFit profiles saved on the device, regardless of whether you chose PEQ or
RoomFit on the EQ Type step (a saved RoomFit profile can be loaded into a
PEQ push and vice versa). Select a row and click "Load Preset." No separate
Stereo/L-R choice is needed here — the channel mode comes from the selected
configuration itself.

### Local Library

Select **Local Library** from the dropdown to browse presets saved locally
on this computer (the same presets shown in "My Saved Presets" in the
sidebar). Select one and click "Load Preset" — again, no separate channel
mode choice is needed.

## Reviewing Filters

After loading, the Review step shows a table of all filter bands:

| Column    | Description                           |
|-----------|---------------------------------------|
| Band      | Filter number (1 up to your device's band count) |
| Type      | Filter type (PK, LS, HS, LP, HP)      |
| Frequency | Center frequency in Hz                |
| Gain      | Boost or cut in dB                    |
| Q         | Bandwidth (higher Q = narrower band)  |

- Bands marked OFF are shown at reduced opacity.
- Clamped values (adjusted to fit device limits) are marked with an orange
  indicator. The cell shows the final value that will be written; hover to
  see the original value from your file.
- Filter types with no WiiM equivalent (e.g. Notch, Modal, All Pass, Linkwitz
  Transform, and REW's slope-based shelves) are dropped and shown as a
  crossed-out, unnumbered ("N/A") row — hover it to see why. Bands cut for
  exceeding the device's band limit are shown the same way.
- Bare LP/HP filters that had no Q specified in your file (filled in with
  REW's documented default of 0.7071) are flagged with a small indicator on
  the Q column — hover for details. These are not dropped, just filled in.
- For L/R mode, the table shows separate Left and Right tabs.

## Dry Run Mode

Toggle the "Dry Run" checkbox on the Review page to preview what would be
sent to the device without actually writing anything. The push button
changes to "Preview Only".

This is useful for verifying your filter file translates correctly before
committing to a write.

**Dry Run is on by default** the first time you use the app, so nothing is
sent to your device until you explicitly turn it off. If you push and don't
see any change on your device, check whether Dry Run is still checked.

The first time you uncheck it, the app will offer to turn off this default
for future sessions. You can also change it any time in
**Settings > Behavior > "Enable Dry Run by default for new sessions"**.

## Pushing to Device

Click "Push to Device" to apply the filters. The app follows a safe
protocol:

1. **Backup** — Saves your current device settings for each selected source
2. **Write** — Sends the new filters to the device
3. **Verify** — Reads back the settings to confirm they match
4. **Done** — Shows success with checkmark on the Push step

After a successful push, you can:

- Click **Show Pushed Filters** to see exactly what the device reported
  back after the write — useful for confirming the values landed as intended
- Click **Undo** to instantly restore your previous settings (works for all
  sources that were written to)
- Click **Export as REW File** to save the pushed filters as a REW file
- Click **Save to My Presets** to store the configuration in your local
  library

### Multi-Source Push

When multiple sources are selected in the Source step, they are written one
after another.

- **If every source succeeds**, the result screen shows the normal success
  state, and Undo restores all of them to their pre-push state, each from
  its own backup.
- **If a source fails**, the push stops there — sources after it in the list
  are never attempted. That source is rolled back to its previous settings
  automatically by its own write attempt. Sources already written before it
  keep their new filters and are **not** automatically rolled back; the
  result screen tells you how many, and its Undo button restores exactly
  those sources (not the one that failed, which is already back to normal).
