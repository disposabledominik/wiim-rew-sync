# Pull & Export

Read the current EQ settings from your WiiM device and export them as
REW-compatible files for analysis or backup.

## Pulling Filters from Your Device

Use "Presets on Device" in the sidebar to browse and pull configurations
from your WiiM device.

### PEQ Presets

The Presets on Device view lists all PEQ presets saved on your device. From
here you can:

- **Load** — Bring the preset's filters into the Review step for editing
  or re-pushing to a different source.
- **Export** — Save as a REW-compatible .txt file.
- **Save locally** — Copy the preset into your local My Saved Presets
  library.
- **Copy to another device** — Push the preset directly to one or more
  other WiiM devices on your network.

### RoomFit Profiles

If your device supports RoomFit, the Presets on Device view also lists
RoomFit profiles in a separate section. The same actions (Load, Export,
Save, Copy) are available.

## Exporting as REW File

After loading filters (whether imported or pulled), click "Export as REW
File" on the Review page or from the Presets on Device view.

### Stereo Export

A standard file dialog appears. Choose a location and filename. The file
gets a .txt extension automatically if you don't type one.

### L/R Export

For L/R (per-channel) configurations, an export dialog appears asking you
to specify filenames for the Left and Right channels. Two separate .txt
files are created (e.g., `MyEQ_L.txt` and `MyEQ_R.txt`).

### Export Format

The exported file uses REW's standard filter text format:

```
Filter  1: ON  PK  Fc   100 Hz  Gain  -3.0 dB  Q  1.41
Filter  2: ON  PK  Fc   250 Hz  Gain   2.5 dB  Q  2.00
...
```

This is the same format that REW produces when you export from its EQ
window, so you can re-import it into REW at any time.

## Backup and Restore

Every time you push filters to your device, the app automatically saves a
backup of the previous configuration. Backups are stored locally in the
app's data directory.

### Restoring a Backup

If something goes wrong after a push, you have two options:

- **Undo** — Click the Undo button on the push result screen to immediately
  restore your previous settings. For multi-source pushes, Undo restores
  all affected sources.
- **Manual restore** — Backups are saved as JSON files in the app data
  folder. You can find the backup path in Settings under "Paths."

### Backup Lifecycle

Backups are created automatically on each push and retained until the limit
is reached (20 most recent per device). Each backup is timestamped and
tagged with the device name, source, and channel mode.
