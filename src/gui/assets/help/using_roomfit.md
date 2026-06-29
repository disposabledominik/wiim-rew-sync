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

## RoomFit Toggle

Enabling or disabling RoomFit on the device is not supported via the API.
Use the WiiM Home app to activate or deactivate RoomFit profiles for
playback.

## Tips

- Use descriptive profile names that reference your measurement setup
  (e.g., "Main Seat REW 2024-12" or "Corner Position").
- RoomFit and PEQ coexist on the same device. They are independent systems.
- Pull an existing RoomFit profile before overwriting to keep a local
  backup via "Presets on Device" > "Save to My Presets."
