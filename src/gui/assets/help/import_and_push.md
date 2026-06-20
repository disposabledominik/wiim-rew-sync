# Import & Push

This is the primary workflow: take a REW measurement and push its filters to
your WiiM device.

## Selecting a Source (PEQ Only)

PEQ filters are per-input. The Source step shows all audio inputs available
on your device (Wi-Fi, HDMI ARC, Optical, Line In, etc.). The currently
active source is pre-selected and labeled "(currently active)".

Choose the source you want to apply EQ filters to.

### Channel Modes

- **Stereo** - The same filters are applied to both left and right channels.
- **Left / Right** - Independent filter sets for each channel. Use this when
  your REW measurements differ significantly between channels.

## Loading Filters

You have three ways to get filters into the app:

### Import from REW File

Click "Import File" and browse for a REW-exported EQ text file (.txt). For
stereo mode, select one file. For L/R mode, select separate files for the
left and right channels.

You can also drag and drop a .txt file directly onto the import area.

### Pull from REW API

If REW is running on your computer with its HTTP API enabled, click "Pull
from REW" to fetch filters directly. This option only appears when the app
can reach REW on your network.

To enable the REW API: in REW, go to Preferences and enable the HTTP server.

### Pull from Device

Click "Pull from Device" to read the current PEQ configuration from your
WiiM device. This is useful for making adjustments to existing settings or
for backing up before changes.

## Reviewing Filters

After loading, the Review step shows a table of all filter bands:

| Column    | Description                           |
|-----------|---------------------------------------|
| Band      | Filter number (1-10)                  |
| Type      | Filter type (PK, LS, HS, etc.)        |
| Frequency | Center frequency in Hz                |
| Gain      | Boost or cut in dB                    |
| Q         | Bandwidth (higher Q = narrower band)  |

- Bands marked OFF are shown at reduced opacity.
- Clamped values (adjusted to fit device limits) are marked with an orange
  indicator. Hover to see the original vs. adjusted value.

## Dry Run Mode

Toggle "Dry Run" on the Review page to preview what would be sent to the
device without actually writing anything. The push button changes to
"Preview Only" and the app shows the translated payload.

This is useful for verifying your filter file translates correctly before
committing to a write.

## Pushing to Device

Click "Push to Device" to apply the filters. The app follows a safe
protocol:

1. **Backup** - Saves your current device settings
2. **Write** - Sends the new filters to the device
3. **Verify** - Reads back the settings to confirm they match
4. **Done** - Shows success or reports any issues

After a successful push, you can:

- Click **Undo** to instantly restore your previous settings
- Click **Export** to save the pushed filters as a REW file
- Click **Save Preset** to store the configuration locally

## Compare with Device

Toggle "Compare with Device" on the Review page to see a side-by-side diff
of your imported filters vs. what is currently on the device. Changed values
are highlighted in accent color with the gain difference shown.
