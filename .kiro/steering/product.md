# Product Summary

WiiM ↔ REW PEQ Sync Tool — a cross-platform desktop application that transfers parametric EQ (PEQ) and RoomFit filter configurations between Room EQ Wizard (REW) and WiiM devices on a local network.

## Key Capabilities

- Discover WiiM devices on LAN via mDNS (zeroconf)
- Read/write 10-band PEQ configurations (stereo and per-channel L/R)
- Import REW EQ text files and REW HTTP API filter data
- Export WiiM PEQ to REW-compatible text format
- Local profile library (save, load, rename, delete, duplicate, tag)
- RoomFit support (experimental, capability-level gated 0–4)
- Dry Run mode (translate and preview without writing to device)

## Design Principles

1. Safety before convenience — never write without backup and verification
2. Local-first — no cloud, no telemetry, no accounts, no internet dependency
3. Capability-driven — dynamically detect what each device supports
4. All data flows through the Canonical Filter Model (never REW→WiiM direct)
5. Recoverability — automatic rollback on verification failure

## Target Users

Non-technical audiophile users who want to apply REW room correction measurements to their WiiM devices without manual configuration.
