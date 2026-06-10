# Kiro IDE Steering Rules

## Development Environment

- **Shell:** WSL2 Ubuntu (Linux). All shell commands must be Linux-compatible. Never use Windows cmd or PowerShell syntax.
- **Python:** Use `python3` (not `python`). Use `pip3` or `python3 -m pip` for package management.
- **Virtual environment:** Activate with `source .venv/bin/activate`, not `.venv\Scripts\activate`.
- **Path separators:** Use forward slashes (`/`) in shell commands. The IDE may show Windows paths (`C:\...`) but the execution shell is Linux.
- **Install command:** `pip install -e ".[dev]"` (editable install with dev deps).
- **Test command:** `python3 -m pytest` (preferred over bare `pytest` to avoid PATH issues).
- **Lint:** `python3 -m ruff check src/`
- **Type check:** `python3 -m mypy src/`

---

1. **Never invent undocumented WiiM endpoints.** If it's not in `wiim_api_notes.md` or confirmed by the capability prober, do not guess. Use the Uncertainty Protocol.

2. **Prefer official documentation.** For WiiM: the official HTTP API PDF and `pywiim` source. For REW: the official REW API and Equaliser help pages.

3. **Mark all assumptions** in comments using the tag `# ASSUMPTION:`. Log them in `corrections.md` if an assumption later fails.

4. **Provide source references** in comments when implementing specific API quirks (e.g. `# pywiim/api/peq.py: band params are letter-prefixed`).

5. **Separate UI from business logic** strictly. No network calls or data manipulation in GUI components.

6. **Use dependency injection** for all Adapters. Pass them via constructor. This enables clean mocking in tests.

7. **Every business component requires tests.** No module in `src/adapters/`, `src/translator/`, or `src/repository/` is considered done without tests.

8. **Every API call requires timeout handling.** Default: 5 seconds. Never allow a network call to block indefinitely.

9. **Every API call requires logging.** WiiM calls → `wiim_api.log`, REW calls → `rew_api.log`, app events → `app.log`.

10. **Every device write requires backup and verification.** (No exceptions.) See the strict 5-step protocol in `architecture.md`.

11. **Do not skip the CLI phase.** Task 022 is a hard gate. No GUI work begins until CLI validation passes against real hardware.

12. **Uncertainty Protocol**: If endpoint behaviour is uncertain — stop, document the uncertainty in `corrections.md` as a new row, create a `# TODO:` comment, set the relevant capability flag to the most conservative (safe) value, and continue with confirmed functionality only.

13. **WiiM PEQ uses the LV2 EqNp plugin.** Commands are `EQGetLV2BandEx`, `EQSetLV2Band`, `EQGetLV2SourceBandEx`, `EQSetLV2SourceBand`, etc. (not the older `GetPEQBandsEx`/`SetPEQBandEx` family). Do not mix the two families.

14. **Channel PEQ modes are `"Stereo"` and `"L/R"`.** Use these exact string values. The `EQBand` key is used for stereo; `EQBandL` and `EQBandR` for L/R mode.

15. **JSON payloads in WiiM commands must be URL-encoded** before being appended to the `httpapi.asp?command=...` query string.

16. **Always target the master node for EQ writes.** Check `role` from `GetMultiroomInfo` before writing. If the selected device is a slave, resolve the master's IP and target that instead.

17. **Never auto-select a REW measurement.** The user must explicitly choose from the list returned by `GET /measurements`. Index numbers are unstable — always use UUID.

18. **REW API unavailability is non-fatal.** If REW is not running, connection refused is caught and a "REW not connected" status is shown. The app continues to function with file-based import/export.
