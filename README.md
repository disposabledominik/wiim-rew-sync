# WiiM ↔ REW PEQ Sync Tool

## Master Project Specification for Kiro IDE

Version: 1.0

---

# 1. Project Overview

## Objective

Develop a cross-platform desktop application that allows users to transfer, synchronize, backup, analyze, and manage Parametric EQ (PEQ) configurations between Room EQ Wizard (REW) and WiiM devices.

The application must:

* Discover WiiM devices automatically on the local network.
* Read current PEQ settings from WiiM devices.
* Import REW-generated EQ filters.
* Export WiiM PEQ filters to REW-compatible format.
* Maintain a local profile library.
* Support stereo and per-channel PEQ.
* Provide safe write operations with verification and rollback.
* Remain usable by non-technical users.

The application must not require cloud services.

All operations must occur locally.

---

# 2. Design Principles

## Core Principles

1. Safety before convenience.
2. Local-first architecture.
3. Capability-driven behavior.
4. No undocumented assumptions.
5. Transparent operation.
6. Recoverability.
7. Non-destructive workflows.

---

# 3. Important Assumptions

## Assumption A

REW API functionality is documented and stable.

## Assumption B

WiiM APIs may differ by:

* model
* firmware
* generation

The application must dynamically detect capabilities.

## Assumption C

RoomFit behavior is partially undocumented.

The application must treat RoomFit support as experimental.

---

# 4. Project Structure

Create:

/docs

* prd.md
* architecture.md
* data_models.md
* api_notes_rew.md
* api_notes_wiim.md
* tasks.md
* qa.md
* corrections.md

/.kiro

* steering.md

/src

* adapters/
* discovery/
* translator/
* repository/
* gui/
* logging/
* tests/

---

# 5. Technology Stack

## Backend

Python 3.12+

## GUI

PySide6

## HTTP

httpx

## Discovery

zeroconf

## Testing

pytest

## Static Analysis

ruff
mypy

## Packaging

PyInstaller

---

# 6. Functional Requirements

## Device Discovery

The application shall:

* discover WiiM devices automatically
* refresh manually
* refresh automatically
* display friendly names
* display model information
* display firmware information
* display capabilities

Failure to discover devices must not crash the application.

---

## WiiM PEQ Read

The application shall:

* read active PEQ configuration
* read stereo PEQ
* read left channel PEQ
* read right channel PEQ
* read active preset information

---

## WiiM PEQ Write

The application shall:

* validate all values
* backup existing state
* write PEQ
* verify PEQ
* rollback on failure

---

## REW Import

Support:

* REW text export format
* future API integration

Import must validate:

* frequency
* gain
* Q
* filter type

before any device operation.

---

## REW Export

Support:

* REW-compatible EQ text files

Exported files must import directly into REW.

---

## Local Profile Library

Support:

* save
* load
* rename
* delete
* duplicate
* tag

Profiles shall be stored locally.

---

# 7. RoomFit Requirements

RoomFit must be treated as experimental.

Capability levels:

Level 0

No visibility.

Level 1

Active state visible.

Level 2

Readable.

Level 3

Exportable.

Level 4

Writable.

The application must determine capability level dynamically.

The UI must adapt automatically.

Never expose unsupported actions.

---

# 8. Capability Detection

Create:

DeviceCapabilities

Properties:

* supports_peq
* supports_roomfit
* supports_roomfit_read
* supports_roomfit_write
* supports_channel_peq
* supports_profile_enumeration
* supports_batch_write
* max_filters

All actions must consult capability information before execution.

---

# 9. Canonical Data Model

All formats must convert through a common model.

REW

↓

Canonical

↓

WiiM

WiiM

↓

Canonical

↓

REW

Never create direct REW→WiiM conversion logic.

---

# 10. Filter Model

Fields:

* type
* frequency_hz
* gain_db
* q

Supported filter types:

* PK
* LS
* HS

Future support:

* All-Pass
* Shelf variants

---

# 11. Translation Engine

Responsibilities:

* import conversion
* export conversion
* validation
* normalization
* rounding

The translation engine is the core business component.

---

# 12. Floating Point Verification

Never compare floats directly.

Use tolerances.

Frequency:

±0.1 Hz

Gain:

±0.05 dB

Q:

±0.01

Verification success must use tolerance-based comparisons.

---

# 13. Dry Run Mode

Required for MVP.

Workflow:

Import

↓

Translate

↓

Validate

↓

Preview

↓

Stop

No device writes occur.

---

# 14. Safety Requirements

Every write operation:

Backup

↓

Write

↓

Read Back

↓

Verify

↓

Success

or

Rollback

No exceptions.

---

# 15. Backup Requirements

Before any modification:

Create automatic backup.

Store:

* timestamp
* device
* firmware
* profile

Backups must be restorable.

---

# 16. Logging Requirements

Create:

logs/

app.log

wiim_api.log

rew_api.log

Use rotating logs.

10 MB

5 retained files

All failures must be logged.

---

# 17. Command Queue

Never perform concurrent writes.

Create:

WiiMCommandQueue

Requirements:

* FIFO
* single writer
* retries
* timeout support
* configurable delays

Default delay:

100 ms

The queue may be bypassed only when verified batch-write support exists.

---

# 18. Batch Write Support

Some WiiM firmware may support full-profile writes.

If supported:

Use batch writes.

Otherwise:

Write sequentially.

Capability detection must determine which mode is used.

---

# 19. REW API Requirements

Support:

* measurement enumeration
* measurement selection
* filter extraction

Never assume:

"latest measurement"

The user must explicitly select the measurement.

---

# 20. Error Handling

Handle:

* device offline
* device rebooting
* API timeout
* malformed REW files
* unsupported filter types
* unsupported firmware
* network disconnects

Graceful recovery is required.

---

# 21. Security Requirements

No cloud services.

No telemetry.

No account system.

No internet dependency.

Local network only.

---

# 22. Developer Diagnostics Mode

Include optional diagnostics panel.

Functions:

* raw API browser
* HTTP request tester
* capability dump
* protocol trace
* export diagnostics

This feature is intended to support future firmware changes.

---

# 23. CLI Proof of Concept Phase

Before GUI implementation:

Build CLI prototype.

Must successfully:

1. Discover WiiM devices.
2. Read PEQ.
3. Export REW.
4. Import REW.
5. Write PEQ.
6. Verify PEQ.

Do not begin GUI work until these tasks pass.

---

# 24. Testing Requirements

Unit Tests

Coverage targets:

Translation Engine

90%+

Adapters

80%+

Repository

80%+

Integration Tests

Required.

Mock WiiM devices.

Mock REW API.

---

# 25. QA Scenarios

Create at least 25 Given-When-Then scenarios.

Examples:

Given:

Valid REW file

When:

Imported

Then:

Filters appear correctly.

---

Given:

Device offline

When:

Push executed

Then:

Meaningful error displayed.

---

Given:

Verification mismatch

When:

Write completes

Then:

Rollback executed.

---

# 26. corrections.md Rules

Whenever an assumption fails:

Record:

* assumption
* failure
* root cause
* solution

Update architecture if needed.

This file acts as project memory.

---

# 27. Kiro Steering Rules

Create .kiro/steering.md

Rules:

1. Never invent undocumented WiiM endpoints.

2. Prefer official documentation.

3. Mark all assumptions.

4. Provide source references in comments.

5. Separate UI from business logic.

6. Use dependency injection.

7. Every business component requires tests.

8. Every API call requires timeout handling.

9. Every API call requires logging.

10. Every device write requires backup and verification.

11. Do not skip CLI phase.

12. If endpoint behavior is uncertain:

* stop
* document uncertainty
* create TODO
* continue with known functionality only

---

# 28. Atomic Task Generation Instructions

Kiro shall convert the implementation plan into 40–60 atomic tasks.

Each task must contain:

Goal

Actions

Acceptance Criteria

Dependencies

Example:

Task 001

Goal:

Initialize project.

Actions:

* create structure
* configure tooling

Acceptance Criteria:

* pytest passes
* ruff passes
* mypy passes

Dependencies:

none

---

# 29. Edge Cases

Handle:

* firmware upgrades during use
* firmware downgrades
* unsupported models
* RoomFit visibility changes
* partial profile writes
* duplicate device names
* IP address changes
* network packet loss
* Wi-Fi roaming
* floating point rounding differences
* invalid UTF-8 in responses
* malformed JSON
* stale cached capabilities

---

# 30. Future Phase Features

Not MVP.

Potential future features:

* live REW synchronization
* profile comparison
* profile diffing
* multi-device deployment
* profile cloud sync
* target curve management
* RoomFit visualization
* measurement import
* automatic PEQ optimization

---

# 31. How To Use This Specification In Kiro

Step 1

Create empty project.

Step 2

Create file structure exactly as defined.

Step 3

Paste this specification into the project.

Step 4

Generate:

* prd.md
* architecture.md
* data_models.md
* api_notes_rew.md
* api_notes_wiim.md
* tasks.md
* qa.md
* corrections.md
* steering.md

Step 5

Ask Kiro:

"Generate the document set from the master specification. Do not write application code."

Review output.

Step 6

Ask Kiro:

"Generate atomic tasks from tasks.md."

Review output.

Step 7

Ask Kiro:

"Implement CLI Proof of Concept only."

Complete all CLI validation.

Step 8

Validate against real WiiM hardware.

Step 9

Only after successful validation:

"Implement GUI layer."

Step 10

Run full QA scenarios.

Step 11

Package with PyInstaller.

Step 12

Perform acceptance testing with multiple WiiM models and firmware versions.

End of Specification.
