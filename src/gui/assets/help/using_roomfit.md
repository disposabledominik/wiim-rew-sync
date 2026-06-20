# Using RoomFit

RoomFit is WiiM's room correction feature. Unlike parametric EQ, RoomFit
applies across all audio inputs on your device simultaneously.

## What is RoomFit?

RoomFit uses a set of correction filters to compensate for your room's
acoustic characteristics. It works similarly to PEQ but with two key
differences:

- **Global** - RoomFit applies to all audio sources (Wi-Fi, HDMI, Optical,
  etc.) at once. You do not choose a source for RoomFit.
- **Profile-based** - Filters are saved as named profiles on the device.
  You can have multiple profiles (e.g., "Listening Position A" and
  "Near Field") and switch between them.

## How It Differs from PEQ

| Feature         | Parametric EQ            | RoomFit                  |
|-----------------|--------------------------|--------------------------|
| Scope           | Per audio source         | All sources              |
| Storage         | Per-source bands         | Named profiles           |
| Source selector  | Yes                      | No (not applicable)      |
| Wizard step     | Choose source first      | Name profile before push |

## Device Compatibility

Not all WiiM devices support RoomFit. The app detects your device's
capability level automatically:

- **Level 0** - PEQ only (RoomFit not available)
- **Level 2+** - Full RoomFit support

If your device does not support RoomFit, the EQ Type selection step is
skipped and the app proceeds directly with PEQ.

## RoomFit Workflow

### 1. Choose RoomFit

On the EQ Type page, select "RoomFit" to enter the RoomFit flow. The
source selection step is skipped (since RoomFit is global).

### 2. Load Filters

Import your REW measurements using any of the standard methods: file
import, REW API pull, or pull an existing RoomFit profile from the device.

When pulling from the device, a profile dropdown lets you choose which
existing profile to load.

### 3. Review

The filter table shows your RoomFit filters. Review the frequency, gain,
and Q values as you would for PEQ.

### 4. Name Your Profile

Before pushing, you must provide a profile name (up to 32 characters). This
is the name that appears in the WiiM Home app and on the device itself.

- If you enter the name of an existing profile, the app warns you that it
  will be overwritten.
- If the name matches the currently active profile, an additional warning
  explains that overwriting will immediately affect playback.

### 5. Push

The app pushes the RoomFit profile to your device. The same safe write
protocol applies: backup, write, verify, done.

## Tips

- Use descriptive profile names that reference your measurement setup
  (e.g., "Main Seat REW 2024-12" or "Corner Position").
- RoomFit and PEQ can coexist on the same device. They are independent
  systems.
- Pull an existing RoomFit profile before overwriting to keep a local
  backup.
