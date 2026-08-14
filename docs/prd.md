# Product Requirements Document (PRD)

## Executive Summary
This project delivers a lightweight cross-platform desktop tool to transfer parametric EQ and RoomFit filter configurations between REW (Room EQ Wizard) and WiiM devices on a local network. It targets non-technical users with an intuitive GUI, ensuring data integrity via strict read-after-write verification, backup, and rollback on errors. 

## Design Principles
1. **Safety before convenience**: Never write without backing up and verifying.
2. **Local-first architecture**: No cloud services, telemetry, or account systems.
3. **Capability-driven behavior**: Dynamically detect device capabilities before exposing features.
4. **No undocumented assumptions**: Treat unknowns (like RoomFit) as experimental.
5. **Recoverability**: Non-destructive workflows with automatic rollback.

## Functional Requirements
1. **Device Discovery**: Automatically locate WiiM devices on LAN using zeroconf (mDNS primary, subnet scan fallback). Refresh manually/automatically. Display device name, model, and IP. Failure to discover must not crash the app.
2. **Capability Detection**: Probe for `supports_peq`, `supports_roomfit`, `supports_lr_filters`, `max_filters`, etc. Adapt UI accordingly. All WiiM devices support PEQ with stereo and L/R channel modes. All except WiiM Mini additionally support RoomFit. WiiM Mini is forced to PEQ-only flow.
3. **PEQ Read (Pull)**: Read active PEQ presets from WiiM device via "Presets on Device" sidebar view.
4. **PEQ Write (Push)**: Validate all values, backup existing state per source, write PEQ to one or more sources, read back to verify (using floating-point tolerances), and rollback on mismatch/failure. Multi-source push supported.
5. **REW Import/Export**: Import REW EQ text files (.txt) in Stereo or L/R mode. Export to REW-compatible text format (dual files for L/R).
6. **Local Profile Library ("My Saved Presets")**: Save, load, rename, delete, duplicate presets. Supports Stereo and L/R channel modes, shown as a bracketed summary after the preset name (e.g. "[Stereo: 7 bands]" or "[L: 5 bands / R: 11 bands]").
7. **Presets on Device**: Browse PEQ presets and RoomFit profiles stored on device. Export, save locally, load into wizard, copy to other devices.
8. **Multi-Source Push**: Source step allows multi-select. Same filter set pushed to all selected sources in one operation with per-source backup and undo.

## RoomFit Requirements (Experimental)
RoomFit capability is detected as three independent booleans on `DeviceCapabilities`
(see [data_models.md](data_models.md)), and the UI adapts to each:
- `supports_roomfit`: the RoomFit subsystem exists on this device at all.
- `supports_roomfit_read`: RoomFit bands can be read back from the device.
- `supports_roomfit_write`: RoomFit profiles can be saved to the device.

An earlier design used a graduated 0-4 `roomfit_level` ladder; it was removed because it encoded
probe *progress* rather than device reality (`corrections.md`, 2026-07-10). The field is still
accepted in the device capability file for backward compatibility, where it maps onto the three
booleans above.

## Error Handling & Security
- Handle offline devices, API timeouts, malformed files, unsupported types, and network drops gracefully.
- Security: Strictly local network operation. No internet dependencies.

## Dry Run Mode (MVP Requirement)
Workflow: Import -> Translate -> Validate -> Preview -> Stop. No device writes occur during dry run.