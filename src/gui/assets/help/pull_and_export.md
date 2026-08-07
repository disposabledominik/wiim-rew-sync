# Pull & Export

Read the current EQ settings from your WiiM device and export them as
REW-compatible files for analysis or backup.

## Pulling Filters from REW (API)

On the Filters step of the wizard, choose **Pull from REW API** from the
"Import source" dropdown to import filters directly from Room EQ Wizard
without exporting a text file.

### Prerequisites

- REW must be running on the same computer
- REW's HTTP API must be enabled (in REW: Preferences → enable HTTP server)
- The API runs on localhost:4735 by default

### Workflow

1. On the Filters step, select **Pull from REW API** from the "Import
   source" dropdown
2. A measurement picker appears showing all available measurements in REW,
   with a **Stereo / L-R** toggle at the top
3. Leave **Stereo** selected to pick one measurement, or switch to **L/R**
   to pick separate Left and Right measurements side by side
4. Select your measurement(s) and click "Continue" (or double-click a
   measurement in Stereo mode). "Back" returns to File Import without
   loading anything.
5. Filters are loaded and you're advanced to the Review step

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

There are two places to work with configurations already on your WiiM
device, depending on what you want to do:

- To **load** a device configuration into the wizard, use the Filters step's
  **Device** option (see below).
- To **export, save locally, or copy** a device preset **without** going
  through the wizard, use "Presets on Device" in the sidebar.

### Loading from the Filters Step

On the Filters step, choose **Device** from the "Import source" dropdown.
It shows one merged list combining every PEQ preset and RoomFit profile
saved on the device, regardless of whether you chose PEQ or RoomFit on the
EQ Type step (a RoomFit-saved profile can be loaded into a PEQ push and
vice versa). Select a row and click "Load Preset."

If the live PEQ config on your selected source doesn't match any saved
preset, a **Custom** row appears at the top of the list, marked active —
select it the same way to pull whatever PEQ bands are currently live
instead of a saved preset. On a device that can't list saved presets at
all, "Custom" is the only PEQ row shown, so it's still how you reach the
live config there too. Note that a source that's never had a preset loaded
onto it reports this same "no match" signal, so "Custom" can just as easily
mean flat, default filters as genuinely hand-adjusted ones — pull it and
check the Review step if you need to know which.

A row marked "(active, PEQ off)" or "(active, RoomFit off)" instead of
plain "(active)" means PEQ/RoomFit is currently switched off for that
scope — you can still pull and push it the same way, it just isn't audible
right now.

Either way, filters are loaded and you're advanced straight to the Review
step — no separate Stereo/L-R choice is needed for a saved preset/profile,
since the channel mode comes from the preset itself.

### Presets on Device (Sidebar) — Export, Save, Copy

The "Presets on Device" sidebar view lists PEQ presets and (if your device
supports it) RoomFit profiles in separate sections. From here you can:

- **Export** — Save as a REW-compatible .txt file.
- **Save locally** — Copy the preset into your local My Saved Presets
  library.
- **Copy to another device** — Push the preset directly to one or more
  other WiiM devices on your network.

This page is for managing presets on the device itself, not for loading them
into the wizard — use the Filters step's Device option for that instead.

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
  restore your previous settings. For a multi-source push where every
  source succeeded, Undo restores all of them; if one source failed partway
  through, Undo restores only the sources that were written before the
  failure (see "Multi-Source Push" in the Import & Push section).
- **Manual restore via CLI** — Backups are saved as JSON files in the app
  data folder (path shown in Settings under "Paths"). Neither the GUI nor
  REW can load a backup file directly, but the command-line tool can write
  it straight back to the device:
  `wiim-rew-sync restore-backup --device <ip> --source <source> --file <backup path>`.
  This is also the recovery path if a push fails so badly that even the
  automatic rollback can't reach the device — see "Backup Files" in the
  Troubleshooting section.

### Backup Lifecycle

Backups are created automatically on each push and retained until the limit
is reached (20 most recent per device). Each backup is timestamped and
tagged with the device name, source, and channel mode.
