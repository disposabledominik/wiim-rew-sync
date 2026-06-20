# Pull & Export

Read the current EQ settings from your WiiM device and export them as
REW-compatible files for analysis or backup.

## Pulling Filters from Your Device

From the Filters step in the wizard, choose "Pull from Device" to read the
active PEQ or RoomFit configuration directly from your WiiM device.

### PEQ Pull

For PEQ, the app reads the filter configuration for the source and channel
mode you selected in the previous step. You will see the full 10-band set
including any bands that are set to OFF.

### RoomFit Pull

For RoomFit, the app shows a dropdown of available profiles on your device.
Select the profile you want to view, and its filters will be loaded into the
review table.

## Exporting as REW File

After loading filters (whether imported or pulled), click "Export as REW
File" on the Review page. The app saves a standard REW-compatible text file
that you can open in Room EQ Wizard for further analysis or modification.

Choose a location using the file dialog. The default export folder can be
set in Settings.

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

- **Undo** - Click the Undo button on the push result screen to immediately
  restore your previous settings.
- **Manual restore** - Backups are saved as JSON files in the app data
  folder. You can find the backup path in Settings under "Paths".

### Backup Lifecycle

Backups are created automatically on each push and retained until you
manually remove them. Each backup is timestamped and tagged with the device
name and source.
