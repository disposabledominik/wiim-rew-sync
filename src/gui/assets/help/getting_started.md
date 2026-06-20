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
network. If only one device is found, it connects automatically. Otherwise,
select your device from the list.

If no devices appear, check the Troubleshooting section for common causes.

### 2. Choose Your EQ Type

If your device supports RoomFit, you will be asked to choose:

- **Parametric EQ** - Applies filters to a specific audio input (source).
  Different sources can have different EQ settings.
- **RoomFit** - Applies room correction across all audio inputs at once.

If your device only supports PEQ, this step is skipped automatically.

### 3. Import Filters

Load your REW measurements by importing a text file, pulling from the REW
API, or reading the current configuration from your device.

### 4. Review and Push

Preview the filter table to confirm everything looks right, then push to
your device. The app always backs up your current settings first, so you
can undo the change if needed.

## Tips for New Users

- **Dry Run mode** is enabled by default for first-time users. It previews
  the translation without writing anything to your device.
- **Undo** is always available after a push. Your previous settings are
  backed up automatically.
- Use the sidebar to access Presets, Settings, and this Help guide at any
  time during the workflow.
