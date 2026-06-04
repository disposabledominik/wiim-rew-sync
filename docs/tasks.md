# Atomic Implementation Tasks

> Each task must be completed and its acceptance criteria verified before the next dependent task begins.
> Tasks marked with 🔒 are **phase gates** — do not proceed past them until all criteria pass.

---

## Phase 1: Foundation & Models

**Task 001** — Initialize project structure  
Goal: Set up the full project skeleton, tooling, and CI baseline.  
Actions: Create `src/` layout, `pyproject.toml`, virtual environment (Python 3.12+), configure `pytest`, `ruff`, and `mypy`.  
Acceptance Criteria:
- `pytest` runs and passes (empty suite is fine)
- `ruff check src/` passes with zero errors
- `mypy src/` passes with zero errors
- `logs/` directory is created on first run  
Dependencies: None

---

**Task 002** — Implement logging module  
Goal: Rotating log infrastructure for all three log channels.  
Actions: Create `src/logging/` module with handlers for `app.log`, `wiim_api.log`, `rew_api.log`. Use `RotatingFileHandler` (10 MB, 5 retained).  
Acceptance Criteria:
- Each log file is created on first write
- Files rotate when size exceeds 10 MB (verified by writing > 10 MB of log data in tests)
- No more than 5 backup archives exist after rotation
- All three log channels write independently  
Dependencies: Task 001

---

**Task 003** — Implement Pydantic models  
Goal: Define all core data models as Pydantic v2 models with validation.  
Actions: Create `CanonicalFilter`, `PEQBand`, `PEQSettings`, `DeviceCapabilities`, `Profile`, `BackupRecord` models in `src/models/`.  
Acceptance Criteria:
- `CanonicalFilter` rejects frequency < 10 Hz and > 22000 Hz
- `CanonicalFilter` rejects type values outside `{"PEAK","LS","HS","OFF"}`
- `PEQBand` rejects mode outside `{-1, 0, 1, 2}`, gain outside ±12 dB, Q outside 0.01–24
- `DeviceCapabilities` is constructable with all fields
- `mypy` reports no errors  
Dependencies: Task 001

---

**Task 004** — Implement floating-point tolerance utilities  
Goal: A dedicated module for all float comparisons used in verification.  
Actions: Create `src/utils/fp_compare.py` with `freq_matches`, `gain_matches`, `q_matches`, and `band_matches` functions. Tolerances: freq ±0.1 Hz, gain ±0.05 dB, Q ±0.01.  
Acceptance Criteria:
- `freq_matches(1000.0, 1000.09)` → True
- `freq_matches(1000.0, 1000.11)` → False
- `gain_matches(-3.0, -3.049)` → True
- `gain_matches(-3.0, -3.06)` → False
- `q_matches(1.41, 1.415)` → True
- All edge cases at exact tolerance boundary are covered by tests  
Dependencies: Task 003

---

## Phase 2: Translation Engine

**Task 005** — REW text file parser → Canonical model  
Goal: Parse REW EQ text export files into a list of `CanonicalFilter` objects.  
Actions: Implement `src/translator/rew_parser.py`. Handle `ON`/`OFF`, `PK`/`LS`/`HS`, multi-line format. Raise `ValidationError` for out-of-range or unknown values.  
Acceptance Criteria:
- Valid REW file parses without error
- `OFF` filter maps to `type="OFF"`
- `PK` → `PEAK`, `LS` → `LS`, `HS` → `HS`
- Frequency > 22000 Hz raises `ValidationError`
- Unknown filter type raises `ValidationError`
- Malformed line raises `ParseError` with descriptive message  
Dependencies: Tasks 003, 004

---

**Task 006** — Canonical model → REW text generator  
Goal: Generate a perfectly formatted REW-compatible EQ text file from Canonical filters.  
Actions: Implement `src/translator/rew_generator.py`. Output must match the exact REW format spec in `api_notes_rew.md`.  
Acceptance Criteria:
- First line is exactly `Equaliser: Parametric EQ`
- Filter lines are 1-indexed with two-digit zero-padding
- `OFF` filters are written with `OFF PK Fc ... Gain ... Q ...`
- Generated files load correctly into REW (verified manually with REW during Phase 5 validation)
- Round-trip: parse → generate → parse produces identical `CanonicalFilter` lists  
Dependencies: Task 005

---

**Task 007** — WiiM API response → Canonical model  
Goal: Parse the WiiM LV2 PEQ band array into Canonical filters.  
Actions: Implement `src/translator/wiim_parser.py`. Handle `EQBand`, `EQBandL`, `EQBandR` arrays. Map `_mode` values to Canonical types using the table in `data_models.md`.  
Acceptance Criteria:
- 10-band `EQBand` array parses into 10 `CanonicalFilter` objects
- `L/R` mode response produces separate left and right `CanonicalFilter` lists
- Band letter `a_mode: -1` → Canonical `type="OFF"`
- Band letter `a_mode: 1` → Canonical `type="PEAK"`
- `a_mode: 0` → `LS`, `a_mode: 2` → `HS`  
Dependencies: Task 003

---

**Task 008** — Canonical model → WiiM API payload  
Goal: Convert Canonical filters into the WiiM LV2 PEQ band parameter list.  
Actions: Implement `src/translator/wiim_generator.py`. Apply WiiM range clipping (gain ±12 dB, Q 0.01–24, freq 10–22000). Log any clipping that occurs.  
Acceptance Criteria:
- 10 `CanonicalFilter` objects produce a valid 40-entry `EQBand` array
- `type="OFF"` maps to `{letter}_mode: -1`
- Gain values outside ±12 dB are clipped and a warning is logged
- Q values outside 0.01–24 are clipped and a warning is logged
- Round-trip: convert to WiiM payload → parse back → matches original within tolerance  
Dependencies: Tasks 004, 007

---

**Task 009** — Translation Engine unit tests  
Goal: Full test coverage for the Translation Engine (>90%).  
Actions: Write `src/tests/test_translator.py`. Cover all valid inputs, boundary conditions, error cases, and round-trips.  
Acceptance Criteria:
- `pytest --cov=src/translator` reports ≥ 90% coverage
- All tests pass
- Includes tests for: valid REW parse, invalid REW parse, valid WiiM parse, round-trip, clipping behaviour, OFF filter handling  
Dependencies: Tasks 005–008

---

## Phase 3: Network & Discovery

**Task 010** — Zeroconf discovery module  
Goal: Discover WiiM devices on the LAN.  
Actions: Implement `src/discovery/zeroconf_discover.py`. Probe `_wiim._tcp.local.` first, then `_linkplay._tcp.local.`, then subnet scan fallback with `getStatusEx`. Return a list of candidate IPs.  
Acceptance Criteria:
- At least one WiiM device is discovered on the LAN when one is present
- Discovery timeout (default 5 s) does not crash if no devices are found
- Returns empty list gracefully when no devices are available  
Dependencies: Task 001

---

**Task 011** — Async HTTP client wrapper  
Goal: A thin, testable async HTTP client for WiiM device communication.  
Actions: Implement `src/adapters/wiim_http.py` using `httpx.AsyncClient`. All requests use `verify=False`. Default timeout: 5 seconds. All requests/responses logged to `wiim_api.log`.  
Acceptance Criteria:
- `get_status_ex(ip)` returns a parsed dict on success
- `WiiMTimeoutError` is raised on timeout
- `WiiMConnectionError` is raised when device is offline
- `WiiMResponseError` is raised on malformed JSON
- All exceptions carry endpoint and attempt context  
Dependencies: Tasks 002, 003

---

**Task 012** — DeviceCapabilities prober  
Goal: Determine the full capability set of a WiiM device.  
Actions: Implement `src/adapters/capability_prober.py`. Probe for: `supports_peq` (attempt `EQGetLV2BandEx`), `supports_channel_peq` (check `channelMode` in response), `supports_batch_write` (attempt a write of all 10 bands at once and verify), `supports_profile_enumeration` (`EQGetLV2List`), RoomFit level (sequential probe per `wiim_api_notes.md`), `max_filters`, multiroom `role`.  
Acceptance Criteria:
- All WiiM devices except generic LinkPlay report `supports_peq=True` and `max_filters=10`
- All WiiM devices report `supports_channel_peq=True`
- WiiM Mini reports `supports_roomfit=False` and `roomfit_level=0`
- All WiiM devices except WiiM Mini report `supports_roomfit=True` with level determined by probe
- Slave device correctly reports `role="slave"`
- RoomFit level is set to the highest confirmed level (0–4)
- All unknown/failed probes default to the most conservative (safe) capability value  
Dependencies: Task 011

---

## Phase 4: WiiM Adapter & Safety

**Task 013** — WiiM PEQ Read  
Goal: Read the current PEQ state from a device and return Canonical filters.  
Actions: Implement `src/adapters/wiim_adapter.py` `read_peq()` method. Fetch for a given source and channel mode. Convert via `wiim_parser.py`. Support stereo and L/R modes.  
Acceptance Criteria:
- Stereo mode returns a single list of 10 `CanonicalFilter` objects
- L/R mode returns separate left and right lists
- Disabled bands return `type="OFF"`
- Correct source name is used in the request  
Dependencies: Tasks 007, 011, 012

---

**Task 014** — WiiMCommandQueue  
Goal: A FIFO single-writer queue for all PEQ write operations.  
Actions: Implement `src/adapters/command_queue.py` as an `asyncio.Queue`-based single-consumer. Default inter-command delay: 100 ms. Supports: retries (max 3), per-command timeout, cancellation on shutdown.  
Acceptance Criteria:
- Commands are executed sequentially in FIFO order
- Inter-command delay is enforced (verified via timing test)
- A failed command retries up to 3 times before raising
- Queue drain completes cleanly on shutdown  
Dependencies: Task 011

---

**Task 015** — Backup generator  
Goal: Save the current device PEQ state to a local JSON backup before any write.  
Actions: Implement `src/repository/backup.py`. Call `read_peq()` and write the result as a `BackupRecord` JSON file with timestamp and device metadata.  
Acceptance Criteria:
- Backup file is created with correct timestamp in filename
- Backup contains device model, firmware, UUID, and all 10 filter bands
- Backup is stored in a `backups/` subdirectory, not in the user-facing profile library
- Backup file is valid JSON and conforms to `BackupRecord` schema  
Dependencies: Tasks 003, 013

---

**Task 016** — Safe Write operation  
Goal: Implement the full Backup → Write → Read Back → Verify sequence.  
Actions: Implement `src/adapters/safe_write.py`. Orchestrate: backup, write via queue (or batch if supported), read back, verify using `fp_compare.py` tolerances.  
Acceptance Criteria:
- Backup is always created before any write
- Write uses batch path when `supports_batch_write=True`, queue path otherwise
- Read-back fetches the live state from the device (not cached)
- Verify compares all 10 bands using tolerance rules
- Returns `WriteResult(success=True)` on pass
- Returns `WriteResult(success=False, failed_bands=[...])` on verify failure  
Dependencies: Tasks 004, 013, 014, 015

---

**Task 017** — Rollback trigger  
Goal: Restore backup state when a write verification fails.  
Actions: Implement rollback in `src/adapters/safe_write.py`. On `WriteResult.success=False`, write the backup state back using the same queue. Verify the rollback write. If rollback write also fails, log CRITICAL and surface to user.  
Acceptance Criteria:
- Rollback correctly restores the previously backed-up filter state
- Rollback is verified with the same tolerance rules as the original write
- If rollback fails: CRITICAL log entry is written with backup file path
- User receives a clear error message with manual recovery instructions  
Dependencies: Task 016

---

## Phase 5: CLI Proof of Concept

**Task 018** — CLI: `--list-devices`  
Goal: Discover and list all WiiM devices on the LAN.  
Actions: Implement CLI entry point (`src/cli/main.py`). `--list-devices` runs discovery and prints device name, IP, model, firmware.  
Acceptance Criteria:
- Runs without error when no devices are present (outputs "No devices found")
- Lists all discovered devices with correct metadata  
Dependencies: Tasks 010, 011, 012

---

**Task 019** — CLI: `--get-filters`  
Goal: Read and display the current PEQ filters from a target device.  
Actions: `--get-filters --device <ip>` reads the PEQ and prints the Canonical filter list in a human-readable table.  
Acceptance Criteria:
- Outputs all 10 bands with type, frequency, gain, Q
- Handles `--source <name>` parameter to target a specific source
- Handles `--channel <stereo|left|right>` parameter  
Dependencies: Task 013

---

**Task 020** — CLI: `--dry-run-import`  
Goal: Import a REW file, translate it, and display the result without writing to device.  
Actions: `--dry-run-import --file <path>` parses the REW file, translates to Canonical, prints the result and any validation warnings.  
Acceptance Criteria:
- Valid REW file: prints all filters with any WiiM range warnings
- Invalid REW file: prints a clear error message and exits non-zero
- No network calls are made  
Dependencies: Tasks 005, 008

---

**Task 021** — CLI: `--set-filters`  
Goal: Import a REW file and write it to a device using the full safety protocol.  
Actions: `--set-filters --file <path> --device <ip>` runs the full Import → Translate → Validate → Backup → Write → Verify → Commit/Rollback sequence.  
Acceptance Criteria:
- Prints confirmation at each step (backup path, write progress, verify result)
- Prints success message on verify pass
- Prints rollback notification and outcome on verify fail
- Prints critical error and manual recovery path if rollback also fails  
Dependencies: Tasks 016, 017, 020

---

**Task 022** 🔒 — End-to-end CLI hardware validation  
Goal: Validate the full CLI flow against real WiiM hardware.  
Actions: Run Tasks 018–021 against a physical WiiM device. Document results. Update `corrections.md` with any deviations from expected behaviour.  
Acceptance Criteria:
- `--list-devices` discovers the test device
- `--get-filters` retrieves correct filter data (compare with WiiM app)
- `--dry-run-import` processes a sample REW file without error
- `--set-filters` writes filters to the device, verifies, and the device EQ reflects the change
- All deviations from expected API behaviour are logged in `corrections.md`
- **Do not proceed to Phase 6 until all criteria pass.**  
Dependencies: Tasks 018–021

---

## Phase 6: Data Persistence

**Task 023** — Local Profile Library  
Goal: Save, load, list, and delete user profiles, with L/R mode schema support.  
Actions: Implement `src/repository/profile_repository.py`. JSON file storage in OS app data directory. Support: `save`, `load`, `list`, `delete`, `rename`. Enforce schema rules: `filters` for Stereo, `filters_l`/`filters_r` for L/R. Implement backup retention: keep the 20 most recent backups per device UUID, pruning oldest on creation of the 21st.  
Acceptance Criteria:
- Stereo profile saves with `filters` key; L/R profile saves with `filters_l` and `filters_r` keys (never both layouts in the same file)
- Profile survives app restart
- `list()` returns all profiles sorted by name
- `load()` on missing profile raises `ProfileNotFoundError`
- Outdated schema version triggers migration before load
- 21st backup for a device deletes the oldest backup for that device  
Dependencies: Tasks 003, 004

---

**Task 024** — Profile tagging and duplication  
Goal: Add metadata operations to the Profile Library.  
Actions: Extend `src/repository/profile_repository.py` with `add_tag`, `remove_tag`, `get_by_tag`, `duplicate` operations.  
Acceptance Criteria:
- Tags persist across restarts
- `duplicate()` creates a copy with a new name and same filter data
- `get_by_tag("bass")` returns only profiles tagged with "bass"  
Dependencies: Task 023

---

## Phase 7: GUI Implementation (PySide6)

**Task 025** — PySide6 main window scaffold  
Goal: Create the main application window with the layout defined in `architecture.md`.  
Actions: Implement `src/gui/main_window.py`. Wire up the async event loop bridge (background thread + Qt signals).  
Acceptance Criteria:
- Application launches without error
- Window is resizable and panels are proportionally laid out
- Closing the window cleanly shuts down the async event loop  
Dependencies: Tasks 001, 014

---

**Task 026** — Device Discovery panel  
Goal: Show discovered devices and their capability indicators.  
Actions: Implement `src/gui/panels/device_panel.py`. Device list with IP, name, model, firmware. Capability icons (PEQ, L/R, RoomFit level). Manual and auto-refresh.  
Acceptance Criteria:
- Clicking a device selects it for subsequent operations
- Capabilities are visually indicated and greyed out when not supported
- "Refresh" button re-runs discovery without freezing the UI
- "No devices found" state is shown clearly  
Dependencies: Tasks 010, 012, 025

---

**Task 027** — Current Settings view  
Goal: Display the current PEQ state for the selected device, source, and channel mode.  
Actions: Implement `src/gui/panels/eq_panel.py`. Source selector (populated from device `InputList`). Channel mode selector (Stereo / L/R). EQ type selector (PEQ / RoomFit — hidden if `supports_roomfit=False`). Filter table showing type, frequency, gain, Q for all 10 bands.  
Acceptance Criteria:
- Source selector shows only inputs from the device's live `InputList`; no input is auto-selected for write operations
- Selecting a device auto-selects the currently active source for display purposes only
- Selecting a source and clicking "Pull" reads and displays the live PEQ state for that source
- L/R channel mode selector is disabled when `supports_channel_peq=False`
- RoomFit tab is hidden when `supports_roomfit=False` (WiiM Mini)
- Disabled bands (OFF) are visually distinct
- Loading a Stereo profile while the device is in L/R mode (or vice versa) shows a mode mismatch warning requiring confirmation  
Dependencies: Tasks 013, 026

---

**Task 028** — REW Import/Export dialogs  
Goal: File dialogs for REW text file import and export with validation feedback.  
Actions: Implement `src/gui/dialogs/import_dialog.py` and `src/gui/dialogs/export_dialog.py`. Show validation warnings inline before any write operation.  
Acceptance Criteria:
- Import dialog filters for `.txt` files
- After import, the filter table shows the translated result with any WiiM range warnings highlighted
- If the REW file contains more than `max_filters` bands, a warning states how many bands were discarded and requires acknowledgement before proceeding
- Export dialog saves a REW-compatible file that opens in REW without error
- Exported L/R mode profiles generate two separate REW files (left and right channels), clearly labelled  
Dependencies: Tasks 005, 006, 027

---

**Task 029** — Profile Library management tab  
Goal: UI for saving, loading, renaming, tagging, deleting, and duplicating profiles.  
Actions: Implement `src/gui/panels/profile_panel.py`.  
Acceptance Criteria:
- All CRUD operations are accessible from the panel
- Loading a profile populates the filter table
- Tags are filterable in the profile list  
Dependencies: Tasks 023, 024, 027

---

**Task 030** — Developer Diagnostics Panel  
Goal: Hidden panel for raw API debugging.  
Actions: Implement `src/gui/panels/diagnostics_panel.py`. Accessible via a menu item (not visible by default). Raw command input, response viewer, capability dump, request log tail.  
Acceptance Criteria:
- Panel is not visible on normal startup
- Raw command input sends a `httpapi.asp?command=...` request to the selected device and displays the raw response
- Capability dump shows the full `DeviceCapabilities` object as formatted JSON  
Dependencies: Tasks 011, 012, 025

---

## Phase 8: Polish & Packaging

**Task 031** — Wire GUI to async core  
Goal: Connect all action buttons to their underlying async operations.  
Actions: Wire Pull, Push, Import, Export, Dry Run buttons. Show progress indicators during async operations.  
Acceptance Criteria:
- All operations run without blocking the UI
- Progress is indicated (spinner or progress bar) during device communication
- Operations can be cancelled mid-flight  
Dependencies: Tasks 025–030

---

**Task 032** — Error dialogs and rollback notifications  
Goal: User-facing error handling for all failure modes.  
Actions: Implement `src/gui/dialogs/error_dialog.py`. Cover: offline device, verify fail + rollback success, verify fail + rollback fail (with backup path shown), REW file parse error, schema migration failure.  
Acceptance Criteria:
- Every known failure mode has a distinct, user-friendly message
- Rollback failures show the backup file path in the dialog
- Errors are also written to `app.log`  
Dependencies: Tasks 017, 031

---

**Task 033** — PyInstaller packaging  
Goal: Create single-file executables for Windows, macOS, and Linux.  
Actions: Create `packaging/` directory with platform-specific `.spec` files. Include all assets and log config.  
Acceptance Criteria:
- Windows: single `.exe` runs without installing Python
- macOS: `.app` bundle runs without installing Python
- Linux: single binary runs without installing Python
- First launch creates the `logs/` and profile storage directories automatically  
Dependencies: Tasks 031, 032

---

**Task 034** 🔒 — Final QA sign-off  
Goal: Verify all 25 QA scenarios in `qa.md` pass.  
Actions: Execute each scenario against real WiiM hardware. Document results.  
Acceptance Criteria:
- All 25 QA scenarios pass
- Any deviations are documented in `corrections.md`
- **Do not release until all scenarios pass.**  
Dependencies: Tasks 033
