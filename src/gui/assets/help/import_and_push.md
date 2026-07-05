# Import & Push

This is the primary workflow: take a REW measurement and push its filters to
your WiiM device.

## Selecting Sources (PEQ Only)

PEQ filters are per-input. The Source step shows common audio inputs
(Wi-Fi, Bluetooth, HDMI, Optical, Line In, etc.) as checkboxes. You can
select one or more sources — the same filter set will be pushed to all
selected sources in one operation.

### Channel Modes

On the Filters page, choose your channel mode before importing:

- **Stereo** — The same filters are applied to both left and right channels.
  Import a single REW .txt file.
- **Left / Right (L/R)** — Independent filter sets for each channel. Import
  separate files for Left and Right. Use this when your REW measurements
  differ significantly between channels.

## Loading Filters

### Import from REW File

On the Filters page, select your channel mode (Stereo or L/R) then click
"Browse" to open a file dialog.

- **Stereo mode** — Select one .txt file, then click "Next" to proceed.
- **L/R mode** — Click "Browse L" and "Browse R" to select files for each
  channel. Once both are selected, click "Import" to proceed.

The files must be REW EQ text exports (.txt). If the file is invalid, an
error message appears with a "Try Again" button to reset and start over.

### Pull from Device

Access existing device configurations via "Presets on Device" in the
sidebar. From there you can load a PEQ preset or RoomFit profile into the
review step for editing or re-pushing.

### Pull from REW API

If REW is running with its HTTP API enabled, access the "Pull from REW API"
option through the sidebar workflow. A measurement picker dialog lets you
choose which REW measurement to import.

## Reviewing Filters

After loading, the Review step shows a table of all filter bands:

| Column    | Description                           |
|-----------|---------------------------------------|
| Band      | Filter number (1–10)                  |
| Type      | Filter type (PK, LS, HS, LP, HP)      |
| Frequency | Center frequency in Hz                |
| Gain      | Boost or cut in dB                    |
| Q         | Bandwidth (higher Q = narrower band)  |

- Bands marked OFF are shown at reduced opacity.
- Clamped values (adjusted to fit device limits) are marked with an orange
  indicator. The cell shows the final value that will be written; hover to
  see the original value from your file.
- Filter types with no WiiM equivalent (e.g. Notch, Modal, All Pass, Linkwitz
  Transform) are dropped and shown as a crossed-out, unnumbered ("N/A") row —
  hover it to see why. Bands cut for exceeding the device's band limit are
  shown the same way.
- Filter types auto-converted to a different WiiM-supported type, and bare
  LP/HP filters that had no Q specified in your file (filled in with REW's
  documented default of 0.7071), are flagged with a small indicator on the
  Type or Q column — hover for details. These are not dropped, just adjusted.
- For L/R mode, the table shows separate Left and Right tabs.

## Dry Run Mode

Toggle the "Dry Run" checkbox on the Review page to preview what would be
sent to the device without actually writing anything. The push button
changes to "Preview Only" and a "DRY RUN" badge appears.

This is useful for verifying your filter file translates correctly before
committing to a write.

**Dry Run is on by default** the first time you use the app, so nothing is
sent to your device until you explicitly turn it off. If you push and don't
see any change on your device, check whether Dry Run is still checked.

The first time you uncheck it, the app will offer to turn off this default
for future sessions. You can also change it any time in
**Settings > General > "Enable Dry Run by default for new sessions"**.

## Pushing to Device

Click "Push to Device" to apply the filters. The app follows a safe
protocol:

1. **Backup** — Saves your current device settings for each selected source
2. **Write** — Sends the new filters to the device
3. **Verify** — Reads back the settings to confirm they match
4. **Done** — Shows success with checkmark on the Push step

After a successful push, you can:

- Click **Undo** to instantly restore your previous settings (works for all
  sources that were written to)
- Click **Export** to save the pushed filters as a REW file
- Click **Save Preset** to store the configuration in your local library

### Multi-Source Push

When multiple sources are selected in the Source step, all are written in
sequence. If any source fails verification, only that source is rolled back.
Undo restores all sources to their pre-push state.
