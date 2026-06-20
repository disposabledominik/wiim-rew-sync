# Import & Push Workflow

The most common workflow: take a REW measurement file and push its filters
to your WiiM device.

## Choosing a Source

The Source step lets you pick which audio input on your WiiM device will
receive the PEQ filters. The currently active source is pre-selected.

## Loading Filters

You have three options for loading filters:

- **Import File** — Browse for a REW-exported EQ text file (.txt)
- **Pull from REW** — Connect to REW's HTTP API and pull filters directly
- **Pull from Device** — Read the current PEQ configuration from your device

## Channel Modes

- **Stereo** — Same filters applied to both channels
- **L/R** — Independent filters for left and right channels

## Review and Push

After loading, review the filter table. Each band shows type, frequency,
gain, and Q factor. Clamped values are highlighted in orange.

Click "Push to Device" when ready. The app backs up your current settings
first, so you can always undo.
