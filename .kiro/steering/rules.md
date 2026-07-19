# Domain Rules

These rules are mandatory for all work in this codebase. They encode hard-won lessons about WiiM API behavior, safety protocols, and project workflow gates.

---

## WiiM API Rules

1. **Never invent undocumented WiiM endpoints.** If it's not in `docs/wiim_api_notes.md` or confirmed by the capability prober, do not guess. Use the Uncertainty Protocol.

2. **Prefer official documentation.** For WiiM: the official HTTP API PDF and `pywiim` source. For REW: the official REW API and Equaliser help pages.

3. **WiiM PEQ uses the LV2 EqNp plugin.** Commands are `EQGetLV2BandEx`, `EQSetLV2Band`, `EQGetLV2SourceBandEx`, `EQSetLV2SourceBand`, etc. (not the older `GetPEQBandsEx`/`SetPEQBandEx` family). Do not mix the two families.

4. **Channel PEQ modes are `"Stereo"` and `"L/R"`.** Use these exact string values on the wire. The `EQBand` key is used for stereo; `EQBandL` and `EQBandR` for L/R mode.

5. **JSON payloads in WiiM commands must be URL-encoded** before being appended to the `httpapi.asp?command=...` query string.

---

## REW Rules

6. **Never auto-select a REW measurement.** The user must explicitly choose from the list returned by `GET /measurements`. Index numbers are unstable — always use UUID.

7. **REW API unavailability is non-fatal.** If REW is not running, connection refused is caught and a "REW not connected" status is shown. The app continues to function with file-based import/export.

---

## RoomFit Rules

8. **RoomFit filters are global — not per-input.** Unlike PEQ which applies per source (wifi, HDMI, etc.), RoomFit profiles apply to all audio inputs on the device. The UI must never show a source/input selector for RoomFit operations. The API uses a `source_name` parameter internally, but from the user's perspective RoomFit is device-wide.

## PEQ Preset Rules

9. **PEQ presets are global — loadable onto any source.** PEQ presets are stored device-wide (the same preset list is visible for all sources in the WiiM Home app). A preset saved while one source is active can be loaded onto any other source via `EQv2SourceLoad`. The UI should allow users to apply a named preset to one or more sources in a single action.

---

## Safety & Write Protocol

10. **Every device write requires backup and verification.** No exceptions. Follow the strict 5-step protocol in `docs/architecture.md`: Backup → Write → Read Back → Verify → Commit/Rollback.

11. **Every API call requires timeout handling.** Default: 5 seconds. Never allow a network call to block indefinitely.

12. **Every API call requires logging.** WiiM calls → `wiim_api.log`, REW calls → `rew_api.log`, app events → `app.log`.

---

## Code & Architecture Rules

13. **Mark all assumptions** in comments using the tag `# ASSUMPTION:`. Log them in `docs/corrections.md` if an assumption later fails.

14. **Provide source references** in comments when implementing specific API quirks (e.g. `# pywiim/api/peq.py: band params are letter-prefixed`).

15. **Separate UI from business logic** strictly. No network calls or data manipulation in GUI components.

16. **Use dependency injection** for all Adapters. Pass them via constructor. This enables clean mocking in tests.

17. **Every business component requires tests.** No module in `src/adapters/`, `src/translator/`, or `src/repository/` is considered done without tests.

---

## Workflow Gates

18. **Do not skip the CLI phase.** Task 32 is a hard gate. No GUI work begins until CLI validation passes against real hardware.

19. **Uncertainty Protocol**: If endpoint behaviour is uncertain — stop, document the uncertainty in `docs/corrections.md` as a new row, create a `# TODO:` comment, set the relevant capability flag to the most conservative (safe) value, and continue with confirmed functionality only.


---

## Smoke Test Issue Tracking

20. **Every GUI bug found during smoke testing MUST be logged to `docs/smoke_test_issues.md`.** Add a new row with issue number, description, status (`OPEN`), test status (`NO`), and notes. When a fix is applied, update the status to `FIXED` and record the commit hash. This is automatic — do not wait for the user to request it.

21. **When fixing a smoke test issue, update its status in `docs/smoke_test_issues.md` in the same commit.** Never fix an issue without updating the tracker.

22. **When creating unit-tests for smoke test issues, update their status in `docs/smoke_test_issues.md` in the same commit.** Never create unit-tests for smoke-test issues without updating the tracker.
