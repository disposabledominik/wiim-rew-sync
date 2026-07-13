# Managing Presets

Save, organize, and reuse your EQ configurations across devices and sources.

## What Are Presets?

Presets are locally saved filter configurations. Once you have a set of
filters you like, you can save them as a preset and reload them later
without needing the original REW file.

Presets are stored on your computer (not on the WiiM device). They are
portable between sessions and can be applied to any compatible device or
source.

## Saving a Preset

You can save a preset from two places:

- **Review page** — Click "Save to My Presets" to store the current filters.
- **Push result** — Click "Save to My Presets" on the success screen.

Give your preset a descriptive name (e.g., "Living Room Correction" or
"Headphone EQ v2"). The channel mode (Stereo or L/R) is saved automatically
and displayed as a badge in the preset list.

If you later push this preset to a device (directly, or via "Copy to
another device"), only letters, numbers, spaces, `-`, and `_` survive —
anything else is stripped from the name, since that's what the WiiM naming
API accepts.

## Loading a Preset

Open "My Saved Presets" from the sidebar. Select a preset and click "Load"
in the toolbar. The filters are loaded into the wizard Review step. From
there you can push to any connected device and source.

For L/R presets, both channels are loaded and the Review page shows separate
Left/Right tabs.

If the wizard isn't fully set up (no device connected or no source selected),
a Quick Setup dialog appears to help you choose a device, source, and channel
mode before loading.

## Organizing Your Library

### Rename

Select a preset in the list and click "Rename" in the toolbar. Enter a new
name and confirm. Alternatively, double-click the preset name to rename
inline.

### Duplicate

Select a preset and click "Duplicate" in the toolbar to create a copy.
Useful when you want to experiment with variations of an existing
configuration.

### Delete

Select a preset and click "Delete" in the toolbar to permanently remove it.
This action cannot be undone.

### Search and Filter

When your library grows beyond a few presets, use the search bar at the top
to filter by name.

## Presets on Device

The "Presets on Device" view in the sidebar shows PEQ presets and RoomFit
profiles stored directly on your WiiM device. From here you can:

- **Export** — Download as a REW-compatible .txt file (separate L/R files
  for per-channel presets)
- **Save locally** — Copy a device preset into your My Saved Presets library
- **Load** — Bring a device preset into the wizard Review step for
  modification or re-pushing
- **Copy to another device** — Push the preset to one or more other WiiM
  devices on your network

PEQ presets and RoomFit profiles appear in separate sections. Selecting an
item in one section deselects any selection in the other. If a PEQ preset or
RoomFit profile is currently active on the device, its entry is shown in
bold accent text with an "(active)" label, so you can see at a glance what's
actually playing before you export, load, or overwrite anything.

Reading a **PEQ** preset's filters (for any of the four actions above)
briefly switches your device's current input to that preset so its bands can
be read, then restores what was playing before you started — a confirmation
dialog appears first so you're not surprised by a brief change in what
you're hearing. **RoomFit** profiles have no such prompt: reading a RoomFit
profile's filters doesn't affect what's actually applied to your audio.

## Tips

- Save presets before pushing so you always have a local copy.
- Use meaningful names that remind you of the measurement conditions
  (room, mic position, date).
- PEQ presets can be loaded onto any source on any device. They are not
  tied to a specific input.
- L/R presets show a "L/R" badge and display per-channel band counts.
