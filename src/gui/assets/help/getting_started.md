# Getting Started

Welcome to WiiM REW Sync! This app bridges the gap between Room EQ Wizard
(REW) and your WiiM device, letting you apply room correction filters
without touching the WiiM Home app.

## What This App Does

WiiM REW Sync reads your REW room correction measurements and pushes them
to your WiiM device as parametric EQ (PEQ) or RoomFit filters. It also
lets you pull existing filters from the device, save presets locally, and
manage multiple configurations.

## What You Need

- A WiiM device connected to your local network (Wi-Fi or Ethernet)
- Your computer on the same network/subnet as the WiiM device
- One of the following:
  - A REW EQ text file (exported from Room EQ Wizard)
  - REW running with its HTTP API enabled (for live filter pulls)

## First Steps

### 1. Connect to Your Device

When you open the app, it automatically searches for WiiM devices on your
network. Device cards appear after a few seconds showing the device name,
model, and IP address. Click a device card to connect.

If no devices appear, check the Troubleshooting section for common causes.

### 2. Choose Your EQ Type

If your device supports RoomFit (all models except WiiM Mini), you will
be asked to choose:

- **Parametric EQ** — Applies filters to specific audio input(s). Different
  sources can have different EQ settings.
- **RoomFit** — Applies room correction across all audio inputs at once.

If your device only supports PEQ (WiiM Mini), this step is skipped
automatically.

### 3. Select Sources (PEQ Only)

For PEQ, choose one or more audio sources to apply your filters to. You can
select multiple sources (e.g., Wi-Fi and Bluetooth) and the same filters
will be pushed to all of them in one operation.

### 4. Import Filters

On the Filters page, choose between Stereo or L/R (per-channel) mode, then
browse for your REW EQ text file:

- **Stereo** — Select one .txt file. The same filters apply to both channels.
- **L/R** — Select separate files for Left and Right channels.

Click "Continue" to load the filters into the review step.

### 5. Review and Push

The Review page shows a table of all filter bands with frequency, gain, Q,
and type. Check that everything looks right, then click "Push to Device."

The app always backs up your current device settings first, so you can undo
the change if needed.

## Tips for New Users

- **Dry Run mode** — Toggle the Dry Run checkbox on the Review page to
  preview the translation without writing to your device. The push button
  changes to "Preview Only."
- **Undo** is available after a successful push. Your previous settings are
  backed up automatically, every time.
- Use the sidebar to access Presets on Device, My Saved Presets, Settings,
  and the User Guide at any time during the workflow.
- **Presets on Device** in the sidebar lets you browse, export, and copy
  existing PEQ presets and RoomFit profiles directly from your WiiM device.
- **Pull from REW** in the sidebar imports filters directly from REW's HTTP
  API if REW is running with the API enabled (no file export needed).

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `F1` | Open this User Guide |
| `Escape` | Close the User Guide, or cancel the operation in progress |
| `Ctrl+R` | Search for devices again |
| `Ctrl+Enter` | Push to device (on the Review page) |
| `Ctrl+Q` | Quit the app |
