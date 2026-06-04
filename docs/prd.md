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
1. **Device Discovery**: Automatically locate WiiM devices on LAN using zeroconf. Refresh manually/automatically. Display IP, friendly name, model, firmware, and capabilities. Failure to discover must not crash the app.
2. **Capability Detection**: Probe for `supports_peq`, `supports_roomfit`, `supports_channel_peq`, etc. Adapt UI accordingly. All WiiM devices support 10-band per-input PEQ with stereo and individual L/R channel modes. All WiiM devices except WiiM Mini additionally support a dedicated RoomFit band set. WiiM Mini supports PEQ but not RoomFit.
3. **PEQ Read (Pull)**: Read active PEQ configuration, stereo PEQ, L/R channel PEQ, and active preset names from WiiM.
4. **PEQ Write (Push)**: Validate all values, backup existing state, write PEQ, read back to verify (using floating-point tolerances), and rollback on mismatch/failure.
5. **REW Import/Export**: Import REW EQ text files (validating frequency, gain, Q, type). Export WiiM PEQ filters to perfectly formatted REW-compatible text files.
6. **Local Profile Library**: Save, load, rename, delete, duplicate, and tag profiles locally.

## RoomFit Requirements (Experimental)
RoomFit capabilities are treated progressively:
- **Level 0**: No visibility.
- **Level 1**: Active state visible.
- **Level 2**: Readable.
- **Level 3**: Exportable.
- **Level 4**: Writable.
The application must dynamically determine this level and adapt the UI.

## Error Handling & Security
- Handle offline devices, API timeouts, malformed files, unsupported types, and network drops gracefully.
- Security: Strictly local network operation. No internet dependencies.

## Dry Run Mode (MVP Requirement)
Workflow: Import -> Translate -> Validate -> Preview -> Stop. No device writes occur during dry run.