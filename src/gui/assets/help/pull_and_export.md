# Pull & Export

Read the current EQ settings from your WiiM device and export them as
REW-compatible files for analysis or backup.

## Pulling Filters from REW (API)

Use "Pull from REW" in the sidebar to import filters directly from Room EQ
Wizard without exporting a text file.

### Prerequisites

- REW must be running on the same computer
- REW's HTTP API must be enabled (in REW: Preferences → enable HTTP server)
- The API runs on localhost:4735 by default

### Workflow

1. Click "Pull from REW" in the sidebar
2. A measurement picker screen shows all available measurements in REW,
   with a **Stereo / L-R** toggle at the top
3. Leave **Stereo** selected to pick one measurement, or switch to **L/R**
   to pick separate Left and Right measurements side by side
4. Select your measurement(s) and click "Continue" (or double-click a
   measurement in Stereo mode). "Back" leaves without loading anything.
5. Filters are loaded into the Review step

If REW has many measurements loaded, start typing a measurement's name
while its list has focus to jump straight to it.

### Supported Filter Types

The app imports the REW filter types that WiiM can actually reproduce:
- PK (Peak), and the explicit-Q variants LS Q, HS Q, LP Q, HP Q — imported
  exactly as REW specifies them.
- A bare LP/HP (no Q) is also imported, using REW's documented default Q —
  see the note below.
- Unsupported types have no WiiM equivalent and are skipped:
  - Notch / Notch Q — skipped rather than approximated as Peak, because REW
    notches imply attenuation deeper than WiiM's -12 dB floor can reproduce.
  - Modal, All Pass, Linkwitz Transform (L-T) — no WiiM equivalent.
  - Bare LS/HS, LS 6dB/HS 6dB, LS 12dB/HS 12dB — REW describes these with a
    shelf *slope* (S) value, and WiiM's EQ has only a Q parameter, with no
    validated way to convert one into the other.
  - LP1 / HP1 — 1st-order filters, which have no Q at all.
- Skipped bands still show up in the Review step as a crossed-out, unnumbered
  ("N/A") row — hover it to see why it was skipped. Bands cut for exceeding
  the device's band limit are shown the same way.
- A bare LP/HP (no Q specified in REW) is imported using REW's own documented
  default Q (0.7071) rather than being skipped. Since this fills in a value
  REW didn't specify, the Review step flags it with a small indicator on the
  Q column — hover it to see the note. LP Q/HP Q/LS Q/HS Q (which carry an
  explicit Q already) are a direct match and never show this note.

If REW is not running or the API is not enabled, you'll see:
"REW is not connected. Please ensure REW is running and its HTTP API is
enabled (localhost:4735)."

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

This is the same human-readable format REW itself produces via
**EQ window &rarr; Filter Tasks &rarr; Export filter settings as text**,
so it's useful for reference, sharing, or re-importing back into *this
app*. Note that REW's own **Import Filters** feature only accepts REW's
own `.req` filter-settings format &mdash; this text export cannot be
loaded back into REW.

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
