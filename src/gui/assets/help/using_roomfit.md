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

You can also load an existing RoomFit profile from the device via "Presets
on Device" in the sidebar.

### 3. Review

The filter table shows your RoomFit filters. Review the frequency, gain,
and Q values as you would for PEQ.

### 4. Name Your Profile

Before pushing, you must provide a profile name (up to 32 characters). This
is the name that appears in the WiiM Home app.

- If you enter the name of an existing profile, the app warns you that it
  will be overwritten.
- If the existing profile is currently active, an additional warning
  explains that overwriting may temporarily deactivate RoomFit (you can
  re-enable it from the WiiM Home app).

### 5. Push

The app pushes the RoomFit profile to your device using the same safe write
protocol: backup, write, verify, done.

After a successful push, Undo is available if you overwrote an existing
profile (the previous version is restored). For new profiles, Undo is not
shown since there was nothing to restore.

If the post-write verification fails, the same overwrite-vs-new distinction
applies to the automatic rollback: an overwritten profile's previous version
is restored, while a brand-new profile that failed verification is deleted
instead (there's no prior version to go back to). Either way you end up back
where you started, and the failure is reported clearly.

## RoomFit Activation

This app doesn't include a manual RoomFit on/off switch — use the WiiM Home
app for that. RoomFit does activate automatically as a side effect of some
actions here, though:

- **Pushing a profile** makes it the active one on your device.
- **Loading a profile** (via "Presets on Device" or the Filters page) briefly
  selects it on the device so its filters can be read, then restores whatever
  was previously active — this has no audible effect, since RoomFit's
  selected-but-not-applied state doesn't change what's playing.

The "Name Your Profile" step and "Presets on Device" both mark the
currently-active RoomFit profile (and PEQ preset) with a bold, colored
"(active)" label, so you can see what's live on your device before you name
or overwrite anything.

## Tips

- Use descriptive profile names that reference your measurement setup
  (e.g., "Main Seat REW 2024-12" or "Corner Position").
- RoomFit and PEQ coexist on the same device. They are independent systems.
- Pull an existing RoomFit profile before overwriting to keep a local
  backup via "Presets on Device" > "Save to My Presets."
