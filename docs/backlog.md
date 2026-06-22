# Backlog — Deferred Features

Items moved here from active specs. They are not planned for the current release but may be reconsidered in future versions. Backend support may already exist (noted per item).

---

## 1. PEQ / RoomFit Enable/Disable Toggle in GUI

**Originally:** GUI Redesign Requirement 22, original spec Task 58

**What:** A visible on/off toggle in the UI allowing users to quickly enable or disable PEQ or RoomFit on the connected device for A/B listening tests.

**Why deferred:** The WiiM Home app already provides this functionality. Adding it to the sync tool adds UI clutter without enabling a workflow that isn't already covered. The tool's primary purpose is filter transfer, not device configuration.

**Backend status:**
- ✅ `WiiMAdapter.enable_peq()` / `disable_peq()` / `get_peq_enabled()` — implemented (Task 57)
- ✅ CLI `peq-toggle --device --source --state on|off` — implemented and working
- ⏳ RoomFit toggle — API mechanism unconfirmed (Task 58 not started, requires hardware testing)

**To reactivate:** Restore Requirement 22 to the GUI redesign spec, add `PEQToggle` component back to design.md, and create implementation tasks for the toggle widget and its WizardController wiring.

---

## 2. RoomFit Enable/Disable API Investigation

**Originally:** Original spec Task 58

**What:** Determine whether RoomFit can be toggled on/off independently via the WiiM HTTP API.

**Why deferred:** Requires physical hardware testing. The PEQ toggle already works via CLI for users who want it. RoomFit toggle has no confirmed API command.

**Backend status:**
- ⏳ Not started — API commands still not found. Investigation steps documented in Task 58 didn't surface the required API calls.
- Uncertainty Protocol applies: if confirmed, implement adapter methods; if not, document as unsupported

**To reactivate:** Reverse-engineer the API call against real hardware. If successful, implement adapter methods and optionally restore the GUI toggle.
