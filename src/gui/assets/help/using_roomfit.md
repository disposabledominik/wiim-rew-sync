# Using RoomFit

RoomFit is WiiM's room correction feature. Unlike parametric EQ, RoomFit
applies across all audio inputs on your device simultaneously.

## What is RoomFit?

RoomFit uses a set of correction filters to compensate for your room's
acoustic characteristics. It works similarly to PEQ but with two key
differences:

- **Global** — RoomFit applies to all audio sources (Wi-Fi, HDMI, Optical,
  etc.) at once. You do not choose a source for RoomFit.
- **Profile-based** — Filters are saved as named profiles on the device.
  You can have multiple profiles (e.g., "Listening Position A" and
  "Near Field") and switch between them in the WiiM Home app.

## How It Differs from PEQ

| Feature         | Parametric EQ            | RoomFit                  |
|-----------------|--------------------------|--------------------------|
| Scope           | Per audio source         | All sources              |
| Storage         | Per-source bands         | Named profiles           |
| Source selector | Yes (multi-select)       | No (not applicable)      |
| Wizard step     | Choose source(s) first   | Name profile before push |

## Device Compatibility

Not all WiiM devices support RoomFit. The app detects your device's
capability automatically:

- **WiiM Mini** — PEQ only (RoomFit not available)
- **All other WiiM models** — Full RoomFit support (PEQ + RoomFit)

If your device does not support RoomFit, the EQ Type selection step is
skipped and the app proceeds directly with PEQ.

## RoomFit Workflow

### 1. Choose RoomFit

On the EQ Type page, select "RoomFit" to enter the RoomFit flow. The
source selection step is skipped (since RoomFit is global).

### 2. Import Filters

On the Filters page, choose Stereo or L/R mode and browse for your REW
measurement file(s), just like the PEQ workflow.

You can also load an existing RoomFit profile from the device: choose
**Device** from the "Import source" dropdown on the Filters step. It shows
one merged list of PEQ presets and RoomFit profiles saved on the device — a
profile saved under RoomFit shows up there too — so you can select it and
click "Load Preset."

### 3. Review

The filter table shows your RoomFit filters. Review the frequency, gain,
and Q values as you would for PEQ.

### 4. Name Your Profile

Before pushing, you must provide a profile name (up to 32 characters). This
is the name that appears in the WiiM Home app.

- Only letters (any language), numbers, spaces, `-`, and `_` are accepted by
  the device. If you type any other character, a warning appears and it's
  automatically stripped from the name before saving.
- Whatever name you choose, saving will make that profile active on your
  device and turn RoomFit on if it's currently off.
- If you enter the name of an existing profile, the app additionally warns
  you that its stored filters will be overwritten.

### 5. Push

The app pushes the RoomFit profile to your device using the same safe write
protocol: backup, write, verify, done. On success, the pushed profile
becomes active and RoomFit turns on if it was off.

Undo is always available after a successful push. It restores whatever
profile was active, and RoomFit's on/off state, to what they were
beforehand. If the push overwrote an existing profile, Undo also restores
that profile's previous filters. If the push created a brand-new profile,
Undo leaves that profile saved on the device (delete it via "Presets on
Device" if you don't want to keep it) and only restores the previous
selection and on/off state.

If the post-write verification fails, the same overwrite-vs-new distinction
applies to the automatic rollback: an overwritten profile's previous version
is restored, while a brand-new profile that failed verification is deleted
instead (there's no prior version to go back to). Either way, RoomFit's
selection and on/off state are also restored to what they were before the
push, so a failed push has no lasting effect on your device.

"Copy to Another Device" (from "Presets on Device") behaves the same way on
each target device you copy to.

## RoomFit Activation

This app doesn't include a manual RoomFit on/off switch — use the WiiM Home
app for that. RoomFit does activate automatically as a side effect of some
actions here, though:

- **Pushing a profile** (or copying one to another device) makes it the
  active one there and turns RoomFit on if it was off.
- **Loading a profile** (via the Filters step's **Device** option) briefly
  selects it on the device so its filters can be read, then restores whatever
  was previously active.

The "Name Your Profile" step and "Presets on Device" both mark the
currently-active RoomFit profile (and PEQ preset) with a bold, colored
"(active)" label, so you can see what's live on your device before you name
or overwrite anything. If RoomFit is currently switched off, that label
reads "(active, RoomFit off)" instead — the profile is still selected, it
just isn't being applied to your audio right now. Turn RoomFit back on via
the WiiM Home app (see above) if you want it audible again.

## Tips

- Use descriptive profile names that reference your measurement setup
  (e.g., "Main Seat REW 2024-12" or "Corner Position").
- RoomFit and PEQ coexist on the same device. They are independent systems.
- Pull an existing RoomFit profile before overwriting to keep a local
  backup via "Presets on Device" > "Save to My Presets."
