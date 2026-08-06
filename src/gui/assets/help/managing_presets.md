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

Loading a saved preset into the wizard happens from the **Filters** step, not
from the "My Saved Presets" sidebar page. On the Filters step, choose
**Local Library** from the "Import source" dropdown, select your preset from
the list, and click "Load Preset." The filters are loaded and you're
advanced to the Review step, ready to push to whichever device and source
you already picked earlier in the wizard.

For L/R presets, both channels are loaded and the Review page shows separate
Left/Right tabs — you don't need to choose Stereo or L/R yourself, since the
preset already carries its own channel mode.

## Organizing Your Library

### Rename

Select a preset in the list and click "Rename" in the toolbar. Enter a new
name and confirm. Alternatively, double-click the preset name to rename
inline.

### Duplicate

Select a preset and click "Duplicate" in the toolbar to create a copy, named
after the original with "copy" appended. Useful when you want to experiment
with variations of an existing configuration.

### Copy to Another Device

Select a preset and click "Copy to Another Device" to push it straight to
one or more other WiiM devices on your network, without going through the
wizard. You pick the target devices from a list.

### Delete

Select a preset and click "Delete" in the toolbar to permanently remove it.
This action cannot be undone.

### Search and Filter

Once you have more than 10 presets, a search box appears above the list.
Type in it to filter by name.

## Presets on Device

The "Presets on Device" view in the sidebar shows PEQ presets and RoomFit
profiles stored directly on your WiiM device. From here you can:

- **Export** — Download as a REW-compatible .txt file (separate L/R files
  for per-channel presets)
- **Save locally** — Copy a device preset into your My Saved Presets library
- **Copy to another device** — Push the preset to one or more other WiiM
  devices on your network

To bring a device preset into the wizard instead, use the Filters step's
**Device** dropdown option — see "Loading a Preset" above; the same merged
PEQ/RoomFit list appears there, selectable from within the wizard itself.

PEQ presets and RoomFit profiles appear in separate sections. Selecting an
item in one section deselects any selection in the other. If a PEQ preset or
RoomFit profile is currently active on the device, its entry is shown in
bold accent text with an "(active)" label, so you can see at a glance what's
actually playing before you export or overwrite anything.

If the live PEQ config on the device doesn't match any saved preset — for
example, after adjusting bands directly rather than loading a saved preset —
a **Custom** row (the same term the WiiM Home app uses) appears at the top
of the PEQ Presets list, marked "(active)." Since it's already live, reading
it for Export or Save to My Presets skips the usual "this will briefly
activate on your device" confirmation entirely — there's nothing to
temporarily switch to. Copy to Another Device also works, but since
"Custom" isn't a name the device actually assigned, you'll be asked to
enter a real name before it's saved on the target device. The one exception
is **Delete** — it stays disabled whenever the Custom row is selected
(alone or alongside other presets), since there's no saved preset on this
device to delete. To bring that live config into the wizard instead, use
the Filters step's "Current configuration on device" button, or select the
equivalent "Custom" row shown there.

Reading a **PEQ** preset's filters (for any of the three actions above, or
when loading one via the Filters step's Device option) briefly switches your
device's current input to that preset so its bands can be read, then
restores what was playing before you started — a confirmation dialog
appears first so you're not surprised by a brief change in what you're
hearing. **RoomFit** profiles have no such prompt, because reading one is
not expected to disturb what's currently applied to your audio.

## Tips

- Save presets before pushing so you always have a local copy.
- Use meaningful names that remind you of the measurement conditions
  (room, mic position, date).
- PEQ presets can be loaded onto any source on any device. They are not
  tied to a specific input.
- L/R presets show a "L/R" badge and display per-channel band counts.
