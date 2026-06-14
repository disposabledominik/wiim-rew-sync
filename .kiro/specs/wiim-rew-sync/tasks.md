# Implementation Plan: WiiM ↔ REW PEQ Sync Tool

## Overview

This plan implements the WiiM ↔ REW PEQ Sync Tool in nine phases, progressing from the foundational data models and translation engine through network adapters, the safe-write protocol, CLI proof-of-concept, GUI, and final packaging. All data flows exclusively through the Canonical Filter Model. Property-based tests (Hypothesis) validate the core translation and repository invariants.

Tasks marked with a ⚠️ note are phase gates requiring manual hardware validation before proceeding.

## Tasks

### Phase 1: Foundation & Models

- [x] 1. Initialize project structure and tooling
  - Create the full `src/` directory layout as specified in `design.md` (models, translator, utils, discovery, adapters, repository, gui, logging, cli, tests)
  - Create `pyproject.toml` with Python 3.12+ requirement, PySide6, httpx, pydantic v2, hypothesis, pytest, ruff, mypy, and pytest-cov dependencies
  - Configure `ruff` linting and `mypy` type checking (strict mode for `src/translator/` and `src/models/`)
  - Configure `pytest` with coverage settings for `src/translator/`
  - Create `src/__init__.py` files for all packages
  - Create the `logs/` directory creation logic in application startup
  - _Requirements: 19.2_

- [x] 2. Implement logging module
  - Create `src/logging/setup.py` with `RotatingFileHandler` configuration for three channels: `logs/app.log`, `logs/wiim_api.log`, `logs/rew_api.log`
  - Each handler: max 10 MB per file, 5 backup archives retained
  - Every log entry must include: timestamp, log level, component name, message
  - The `logs/` directory must be created automatically on first run if absent
  - Write unit tests verifying creation, rotation, and independent channel writes
  - _Requirements: 15.1, 15.2, 15.3, 15.8, 19.2_

- [x] 3. Implement core Pydantic models
  - Implement `CanonicalFilter` in `src/models/canonical.py` with `type` (FilterType literal), `frequency_hz` (10–22000 Hz), `gain_db`, `q` fields and field validators
  - Implement `PEQBand` and `PEQSettings` in `src/models/peq.py`
  - Implement `DeviceCapabilities` and `DeviceInfo` in `src/models/capabilities.py`
  - Implement `Profile` and `BackupRecord` in `src/models/profile.py` with the `@model_validator` enforcing channel-mode/filter-key consistency
  - Implement the full exception hierarchy in `src/models/errors.py`
  - Implement `ValidationWarning` dataclass in `src/translator/__init__.py`
  - Write unit tests covering validation rejection cases and the `Profile` channel-mode validator
  - _Requirements: 4.4, 4.5, 6.4, 6.5, 9.2, 9.3, 9.4_

- [x] 4. Implement floating-point tolerance utilities
  - Create `src/utils/fp_compare.py` with constants: `FREQ_TOLERANCE_HZ = 0.1`, `GAIN_TOLERANCE_DB = 0.05`, `Q_TOLERANCE = 0.01`
  - Implement `freq_matches(a, b)`, `gain_matches(a, b)`, `q_matches(a, b)` predicates
  - Implement `band_matches(intended, read_back)` — OFF bands require only type match
  - Write unit tests in `src/tests/test_fp_compare.py` covering exact boundary values (pass at ε, fail at ε + 0.0001)
  - _Requirements: 5.6_

- [x] 5. Write property test: floating-point tolerance predicate correctness (PBT)
  - In `src/tests/test_fp_compare.py`, add a Hypothesis `@given` test
  - Define a `st_float_near_boundary(center, tolerance)` strategy in `conftest.py`
  - Property: `band_matches()` returns True iff `|a - b| <= tolerance` for each parameter type; OFF bands always True
  - Use `@settings(max_examples=100)`
  - **Validates: Requirements 5.6, 16.7**

### Phase 2: Translation Engine

- [x] 6. Implement REW text file parser
  - Create `src/translator/rew_parser.py` implementing `REWParser`
  - `parse_file(path)` requires first line exactly `Equaliser: Parametric EQ`; maps `PK`→`"PEAK"`, `LS`→`"LS"`, `HS`→`"HS"`, `OFF <type>`→`"OFF"`
  - Raise `ParseError` (with line number) for malformed lines; raise `ValidationError` for unknown type tokens or frequency outside 10–22000 Hz
  - Implement `parse_filter_settings(filter_settings)` for REW HTTP API `FilterSetting` objects
  - Write unit tests covering valid file, OFF filter, all type mappings, frequency error, unknown type error, malformed line error
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

- [x] 7. Implement REW text file generator
  - Create `src/translator/rew_generator.py` implementing `REWGenerator`
  - `generate_file(filters, path, max_filters=10)`: first line exactly `Equaliser: Parametric EQ`; 1-based two-digit zero-padded numbering; gain and freq to 2 dp, Q to 3 dp; OFF bands as `OFF PK Fc <freq> Hz Gain <gain> dB Q <q>`
  - `generate_lr_files(filters_l, filters_r, base_path, max_filters=10)`: two files with `_L` / `_R` suffixes; return `(left_path, right_path)`
  - Write unit tests: first-line format, band numbering, decimal precision, OFF band format, L/R suffix naming
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [x] 8. Write property test: REW parse-generate-parse round-trip (PBT)
  - In `src/tests/test_translator.py`, add a Hypothesis `@given` test
  - Define `st_canonical_filter()` and `st_canonical_filter_list(min_size=1, max_size=10)` strategies in `conftest.py`
  - Property: for any valid `CanonicalFilter` list, `generate_file` → `parse_file` must return a list identical to the original
  - Use `@settings(max_examples=100)`
  - **Validates: Requirements 16.6, 6.1, 6.3, 7.1, 7.2, 7.3, 7.4, 7.5**

- [x] 9. Implement WiiM API response parser
  - Create `src/translator/wiim_parser.py`
  - `parse_wiim_band_array(band_array, channel="stereo")` maps `EQBand`/`EQBandL`/`EQBandR` arrays to `list[CanonicalFilter]`
  - Mode mapping: `−1`→`"OFF"`, `1`→`"PEAK"`, `0`→`"LS"`, `2`→`"HS"`
  - Write unit tests: 10-band array, L/R mode, all mode value mappings
  - _Requirements: 4.2, 4.3, 4.4, 4.5_

- [x] 10. Implement WiiM API payload generator
  - Create `src/translator/wiim_generator.py`
  - `generate_wiim_band_array(filters)` produces 40-entry parameter list (4 params × 10 bands)
  - Clip gain to ±12 dB and Q to 0.01–24; log WARNING for each clip
  - Write unit tests: 10 filters → 40-entry output, OFF maps to mode −1, clipping triggers and logs warnings, round-trip within tolerance
  - _Requirements: 6.7, 6.8, 16.3, 16.4, 16.5_

- [x] 11. Write property test: WiiM generate-parse round-trip (PBT)
  - In `src/tests/test_translator.py`, add a Hypothesis `@given` test
  - Reuse `st_canonical_filter_list` strategy
  - Property: for any valid `CanonicalFilter` list, `generate_wiim_band_array` → `parse_wiim_band_array` must produce filters matching originals within tolerances (freq ±0.1 Hz, gain ±0.05 dB, Q ±0.01)
  - Use `@settings(max_examples=100)`
  - **Validates: Requirements 16.7, 4.2, 4.4, 4.5**

- [x] 12. Write property test: WiiM value clipping invariant (PBT)
  - In `src/tests/test_translator.py`, add a Hypothesis `@given` test
  - Strategy: generate `CanonicalFilter` objects with gain and Q values outside WiiM limits
  - Property: `generate_wiim_band_array()` must always produce entries with gain in [−12.0, +12.0] and Q in [0.01, 24.0], regardless of input values
  - Use `@settings(max_examples=100)`
  - **Validates: Requirements 6.7, 6.8, 16.3, 16.4**

- [x] 13. Implement schema migrator
  - Create `src/translator/schema_migrator.py`
  - `migrate_profile(raw: dict) -> dict`: upgrade from any older `schema_version` to current; raise `SchemaVersionError` if migration is impossible
  - Write unit tests: current-version is no-op, old version migrates, unknown version raises `SchemaVersionError`
  - _Requirements: 9.8_

- [x] 14. Assemble TranslationEngine facade and verify coverage
  - Create `src/translator/__init__.py` with the stateless `TranslationEngine` facade (all `@staticmethod` methods)
  - Run `pytest --cov=src/translator --cov-report=term-missing` and confirm ≥ 90% coverage
  - Ensure `mypy src/translator/` passes with zero errors
  - _Requirements: 16.1, 16.2_

### Phase 3: Network & Discovery

- [x] 15. Implement WiiM HTTP client
  - Create `src/adapters/wiim_http.py` implementing `WiiMHttpClient`
  - Use `httpx.AsyncClient` with `verify=False` and default 5 s timeout
  - `command(command)`: GET `https://<ip>/httpapi.asp?command=<command>`; return parsed JSON dict or raw string
  - Log every request/response pair to `wiim_api.log`
  - Raise `WiiMTimeoutError`, `WiiMConnectionError`, `WiiMResponseError` as appropriate
  - Write unit tests using `respx` or `unittest.mock.AsyncMock`
  - _Requirements: 4.6, 8.6, 14.7, 15.4_

- [x] 16. Implement device discovery module
  - Create `src/discovery/zeroconf_discover.py` for mDNS probing (`_wiim._tcp.local.` → `_linkplay._tcp.local.`)
  - Create `src/discovery/subnet_scanner.py` for fallback scan: `getStatusEx` probe; accept only recognisable `project` fields; exclude unrecognised hosts
  - Create `src/discovery/discovery_module.py` implementing `DiscoveryModule` with `discover()` and `refresh()` (configurable timeout, non-blocking, returns empty list on no results)
  - Write unit tests with fake `ServiceInfo` callbacks and mocked `WiiMHttpClient`
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

- [x] 17. Write property test: discovery result field completeness (PBT)
  - In `src/tests/test_discovery.py`, add a Hypothesis `@given` test
  - Strategy: generate `getStatusEx` response dicts with valid WiiM `project` fields and varying `DeviceName`, `Release`, `ip` values
  - Property: for any valid WiiM response, `DiscoveryModule` must produce a `DeviceInfo` with non-empty `ip`, `name`, `model`, and `firmware`
  - Use `@settings(max_examples=100)`
  - **Validates: Requirements 1.5, 1.8**

- [x] 18. Implement capability prober
  - Create `src/adapters/capability_prober.py` implementing `CapabilityProber`
  - `probe()` never raises; all failed probes default to the most conservative value
  - Probing sequence: `getStatusEx` → `EQGetLV2BandEx` → batch-write test → `EQGetLV2List` → RoomFit levels 0–4 sequential probe → `GetMultiroomInfo`
  - `max_filters`: 10 for WiiM, 0 for generic LinkPlay, 0 for unrecognised
  - Write unit tests with mocked `WiiMHttpClient` and canned fixture responses
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10_

### Phase 4: WiiM Adapter & Safe Write

- [x] 19. Implement WiiM adapter — PEQ read
  - Create `src/adapters/wiim_adapter.py` implementing `WiiMAdapter`
  - `read_peq(source_name)`: issue `EQGetLV2SourceBandEx`; convert via `wiim_parser`; return `PEQSettings`
  - Stereo: parse `EQBand`; L/R: parse `EQBandL` and `EQBandR` separately
  - Raise `WiiMResponseError` on missing fields; `WiiMConnectionError` on unreachable device
  - `get_multiroom_master_ip()`: return master IP from `GetMultiroomInfo` or None
  - Write unit tests with mocked HTTP client and fixture JSON responses
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

- [x] 20. Implement WiiM adapter — PEQ write and RoomFit
  - Add `write_peq(source_name, settings, queue)` to `WiiMAdapter`: batch path when `supports_batch_write=True`, queue path otherwise; raise `WiiMSlaveTargetError` if device role is slave
  - Add `read_roomfit()` and `write_roomfit(filters)` (gated by `roomfit_level`)
  - Write unit tests: batch path, sequential path, slave guard
  - _Requirements: 5.3, 5.4, 5.11, 17.1, 17.4_

- [x] 21. Implement WiiM command queue
  - Create `src/adapters/command_queue.py` implementing `WiiMCommandQueue`
  - Single asyncio FIFO consumer; 100 ms inter-command delay; max 3 retries per command
  - `start()`, `drain_and_stop()`, `cancel()` lifecycle
  - Read-only GET calls bypass the queue
  - Write unit tests: FIFO order, timing, retry on failure, clean drain
  - _Requirements: 5.4, 18.1_

- [x] 22. Implement backup manager
  - Create `src/repository/backup_manager.py` implementing `BackupManager`
  - `create_backup(settings, capabilities, trigger)`: write `BackupRecord` JSON; ISO 8601 timestamp required; `profile_type="backup"` and `trigger` field present
  - Retention: MAX 20 per device UUID; 21st triggers deletion of oldest; deletion failure → raise `BackupError` and abort
  - `list_backups(device_uuid)`: sorted oldest-first
  - Backups stored in `storage_root/backups/`, not visible in profile library
  - Write unit tests using `tmp_path`: creation, retention at 20, deletion trigger at 21, deletion-failure → `BackupError`
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

- [x] 23. Implement safe write protocol
  - Create `src/adapters/safe_write.py` implementing `SafeWrite` and `WriteResult`
  - `execute()` implements the five-step sequence in order: (1) Backup, (2) Write, (3) Read-Back (fresh call), (4) Verify via `band_matches()`, (5a) Commit / (5b) Rollback
  - On rollback: create `"pre_rollback"` backup; write backup state via queue; verify rollback
  - Rollback failure: log CRITICAL to `app.log` with backup path; return `WriteResult(success=False, rollback_success=False)`
  - Raise `WiiMSlaveTargetError` if target is slave
  - Write unit tests: success path, verify failure → rollback success, rollback failure → CRITICAL log, batch vs sequential branches
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11_

### Phase 5: REW Adapter & Repository

- [x] 24. Implement REW HTTP API client
  - Create `src/adapters/rew_http_client.py` implementing `REWHttpApiClient`
  - `list_measurements()`: GET `http://localhost:4735/measurements`; return `list[MeasurementSummary]`; raise `REWNotConnectedError` on connection refused
  - `get_filters(uuid)`: parse `FilterSetting` objects via `REWParser.parse_filter_settings()`; raise `REWMeasurementNotFoundError` on 404
  - Log all requests/responses to `rew_api.log`
  - Write unit tests with mocked httpx responses
  - _Requirements: 8.1, 8.3, 8.4, 8.5, 8.6_

- [x] 25. Implement profile repository
  - Create `src/repository/profile_repository.py` implementing `ProfileRepository`
  - OS-appropriate storage via `src/utils/app_dirs.py`
  - Implement all nine operations: `save`, `load`, `list`, `delete`, `rename`, `duplicate`, `add_tag`, `remove_tag`, `get_by_tag`
  - `save()`: Stereo → `filters` key only; L/R → `filters_l`/`filters_r` only
  - `load()`: validate channel-mode/filter-key consistency; apply schema migration; raise `ProfileNotFoundError` for missing names
  - `list()`: lexicographic, case-insensitive sort
  - Tags must persist across app restarts
  - Write unit tests using `tmp_path` pytest fixture
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10_

- [x] 26. Write property test: profile channel-mode key invariant (PBT)
  - In `src/tests/test_profile_repository.py`, add a Hypothesis `@given` test
  - Strategy: generate `Profile` objects in both Stereo and L/R modes with varying filter contents
  - Property: `save()` → `load()` round-trip preserves correct filter key structure for both channel modes
  - Use `@settings(max_examples=100)`
  - **Validates: Requirements 9.2, 9.3, 9.4**

- [x] 27. Write property test: profile list sort-order invariant (PBT)
  - In `src/tests/test_profile_repository.py`, add a Hypothesis `@given` test
  - Strategy: generate arbitrary sets of profile names with varying case, length, and leading characters
  - Property: for any set of profiles saved in any order, `list()` returns them in ascending lexicographic order by name (case-insensitive)
  - Use `@settings(max_examples=100)`
  - **Validates: Requirements 9.6**

### Phase 6: CLI Proof of Concept

- [x] 28. Implement CLI — `list-devices`
  - Create `src/cli/main.py` with argparse entry point; register as `wiim-rew-sync` console script in `pyproject.toml`
  - `list-devices`: run discovery; print tabular output (Name | IP | Model | Firmware | Role); print "No devices found." if empty; exit code 0 in both cases
  - Support global options: `--timeout FLOAT` and `--log-level LEVEL`
  - _Requirements: 1.1, 1.6_

- [x] 29. Implement CLI — `get-filters`
  - Add `get-filters --device <ip> [--source <name>] [--channel <stereo|left|right>]` command
  - Print 10-row table: Band | Type | Frequency (Hz) | Gain (dB) | Q
  - Exit code 0 on success, 1 on error
  - _Requirements: 4.1, 4.2, 4.3_

- [x] 30. Implement CLI — `dry-run-import`
  - Add `dry-run-import --file <path>` command
  - Parse REW file, translate to Canonical, print filter table with WiiM range warnings; no network calls
  - Exit code 0 on valid file, 1 on parse/validation error
  - _Requirements: 12.1, 12.2, 12.3, 6.7, 6.8_

- [x] 31. Implement CLI — `set-filters`
  - Add `set-filters --file <path> --device <ip> [--source <name>] [--channel <stereo|left|right>]` command
  - Run full safe-write with per-step progress output; print rollback or critical-error output as appropriate
  - Exit code 0 on verified success, 1 on any failure
  - _Requirements: 5.1-5.10, 12.1-12.3_

- [x] 32. CLI end-to-end hardware validation (phase gate)
  - Run all four CLI commands against physical WiiM hardware
  - Verify `get-filters` output matches WiiM app; verify `set-filters` filter change is visible in WiiM app
  - Document any API deviations in `docs/corrections.md`
  - Do not proceed to Phase 7 until all CLI commands pass on real hardware

### Phase 7: GUI Implementation

- [ ] 33. Implement async bridge and main window scaffold
  - Create `src/gui/async_bridge.py` implementing `AsyncBridge` with `start()`, `run_async()`, `shutdown()` and all signals from design
  - Wrap all async operations with `operation_started` / `operation_finished` / `progress_update` signals
  - Create `src/gui/main_window.py` with the layout from design (vertical splitter, device panel, EQ panel, action bar, profile tab widget, diagnostics dock widget)
  - Connect `closeEvent` to `AsyncBridge.shutdown()`
  - _Requirements: 18.1, 18.2, 18.3, 18.4_

- [ ] 34. Implement device panel
  - Create `src/gui/panels/device_panel.py`
  - `QListWidget` showing: friendly name, IP, model, firmware, role badge, capability icons
  - Refresh button triggers non-blocking discovery; "No devices found" state shown when list is empty
  - On device selection: trigger `CapabilityProber.probe()` via `AsyncBridge`; emit `capabilities_ready`
  - _Requirements: 1.5, 2.1, 17.3, 18.4, 18.6_

- [ ] 35. Implement EQ panel and source selector
  - Create `src/gui/panels/eq_panel.py`
  - Source selector: populated from `capabilities.source_names`; no source pre-selected for write; currently active source pre-selected for display
  - Channel mode selector: disabled when `supports_channel_peq=False`
  - EQ type selector: PEQ tab always visible; RoomFit tab hidden when `roomfit_level == 0`
  - Filter table: 10-12 rows × 5 columns (dynamic based on `max_filters`); OFF bands shown in grey; UNKNOWN bands greyed with tooltip
  - **PEQ tab:**
    - Pull button → `WiiMAdapter.read_peq()` via `AsyncBridge`; table updates on `peq_ready`
  - **RoomFit tab (visible when `roomfit_level >= 1`):**
    - Profile selector dropdown: populated from `WiiMAdapter.list_roomfit_profiles()`; refresh button
    - When `roomfit_level == 1`: show "RoomFit Active" indicator, all controls disabled
    - When `roomfit_level >= 2`: Pull button enabled → `WiiMAdapter.read_roomfit(source, profile_name)` loads selected profile and displays bands
    - When `roomfit_level >= 4`: Push button enabled → `WiiMAdapter.write_roomfit(source, profile_name, filters)` writes to selected profile
    - **Deactivation warning**: if the user pushes to the currently-active RoomFit profile, show a confirmation dialog: "Saving to the active profile will deactivate Room Correction. You'll need to re-select it in the WiiM app. Save to a new name instead?" with options [Save as new name...] [Overwrite anyway] [Cancel]
    - New profile name input: text field appears when user chooses "Save as new name" or when no profile is selected
  - _Requirements: 3.1, 3.2, 3.3, 3.5, 4.1, 11.1, 11.2, 11.3, 11.4, 11.5, 11.7_

- [ ] 36. Implement import and export dialogs
  - Create `src/gui/dialogs/import_dialog.py`: `.txt` file dialog; synchronous parse; preview table with `ValidationWarning` items highlighted in orange; inline warning banner with acknowledgement checkbox if `len(filters) > max_filters`
  - Create `src/gui/dialogs/export_dialog.py`: save-mode file dialog; L/R mode shows two path fields with `_L.txt` / `_R.txt` pre-fills
  - **NOTE**: `REWGenerator.generate_file()` currently logs UNKNOWN-band skipping but does NOT return `ValidationWarning` objects to the caller. The export dialog needs to surface these warnings to the user. Refactor `generate_file()` to return `list[ValidationWarning]` (or accept a warnings accumulator) so the export dialog can display "N bands were omitted because their filter type is unknown."
  - _Requirements: 6.7, 6.8, 6.9, 6.10, 7.6, 14.2_

- [ ] 37. Implement profile panel
  - Create `src/gui/panels/profile_panel.py`
  - **Local profiles tab**: All nine CRUD+tag operations accessible from the panel
  - Loading a local profile populates the filter table in the EQ panel
  - Loading a Stereo profile onto an L/R device (or vice versa) shows a mode mismatch warning requiring explicit confirmation
  - **Device profiles tab** (when device is selected and `supports_profile_enumeration=True`):
    - Lists PEQ presets from device (`list_peq_profiles`)
    - Load button: loads a device preset into the live DSP (`load_peq_profile`) and refreshes the EQ panel
    - Delete button: removes a device preset (`delete_peq_profile`)
    - Device presets are read-only in the table (editing happens via the PEQ filter table + Push)
  - _Requirements: 9.5, 9.11_

- [ ] 38. Implement diagnostics panel
  - Create `src/gui/panels/diagnostics_panel.py` as hidden `QDockWidget`
  - Header: `"⚠ Developer Diagnostics — Not for production use"`
  - Raw command input with explicit Send button (no background polling); response display; capability dump; `wiim_api.log` tail (last 100 lines)
  - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

### Phase 8: Action Bar, Error Handling & Polish

- [ ] 39. Implement action bar and wire async operations
  - Create the `ActionBar` widget with Import REW, Export REW, Pull, Push, Dry Run buttons
  - Gate buttons by device/source selection and capabilities
  - Dry Run toggle: "DRY RUN" label visible when active (e.g. red background); suppress all device writes, backup creation, and queue calls; display translated filters with validation warnings
  - Push: blocked with error dialog if no source selected
  - **PEQ Push flow**: safe-write protocol (backup → write → verify → commit/rollback); optional "Save as device preset" checkbox + name field (calls `save_peq_profile()` after verified write)
  - **RoomFit Push flow**: no safe-write (RoomFit writes go to a named profile, not live DSP). Flow: parse → write to buffer → save to profile name. If overwriting active profile → show deactivation warning first.
  - **Export RoomFit**: when RoomFit tab is active, Export REW exports the currently-displayed RoomFit filters (not PEQ)
  - **Import to RoomFit**: when RoomFit tab is active, Import REW → parse file → display in RoomFit filter table → user can Push to save as a profile
  - Wire all buttons to `AsyncBridge.run_async()` with progress indicator and Cancel support
  - _Requirements: 3.2, 3.6, 5.11, 11.5, 12.1, 12.2, 12.3, 12.4, 12.5, 17.2, 18.4, 18.5, 18.6_

- [ ] 40. Implement error dialog and all error handling paths
  - Create `src/gui/dialogs/error_dialog.py` with severity-specific icons
  - Cover all failure modes: device offline, REW parse error, verify fail + rollback success, verify fail + rollback fail (copyable backup path + recovery steps), REW not connected, measurement not found, schema migration failure, malformed JSON, no-source write attempt, mode mismatch, slave redirect
  - All errors also written to `app.log` at ERROR or CRITICAL level
  - _Requirements: 14.1–14.8, 5.9, 5.10_

- [ ] 41. Implement multiroom write redirect
  - In `WiiMAdapter.write_peq()` and `SafeWrite.execute()`: if target role is `"slave"`, call `get_multiroom_master_ip()` and redirect to master IP
  - If master unreachable: raise `WiiMSlaveTargetError` and block operation
  - In GUI Push handler: display redirect warning to user; block with error dialog if master unreachable
  - _Requirements: 5.11, 17.1, 17.2, 17.4_

### Phase 9: Packaging & Final QA

- [ ] 42. Implement OS-appropriate directory resolution and first-run setup
  - Create `src/utils/app_dirs.py` returning correct app data directory per OS
  - On startup: auto-create `logs/` and profile storage directories; abort with specific error if creation fails
  - _Requirements: 9.1, 19.2_

- [ ] 43. Create PyInstaller packaging configuration
  - Create `packaging/` with platform-specific `.spec` files for Windows (`.exe`), macOS (`.app`), Linux (single binary)
  - Exclude unused Qt modules (QtWebEngine, Qt3D, QtMultimedia, QtQuick, QtQml, QtDesigner, QtTest) to reduce binary size (~20-30 MB savings)
  - Do NOT use UPX compression (causes antivirus false positives for non-technical users)
  - Include all assets and logging configuration; verify each build runs without Python installed
  - Target size: 70-90 MB for Windows .exe (single file, no installer needed)
  - _Requirements: 19.1, 19.2, 19.3, 19.4_

- [ ] 44. Final QA sign-off (release gate)
  - Execute all QA scenarios from `docs/qa.md` against real hardware
  - Run full test suite: confirm ≥ 90% coverage for `src/translator/`, ≥ 80% overall
  - Run `ruff check src/` and `mypy src/` with zero errors; document any deviations in `docs/corrections.md`
  - Run `pip-audit` on dependencies to check for known vulnerabilities before distribution
  - Do not release until all QA scenarios pass

### Phase 10: Integrity Fixes (Tech Debt from Review)

- [x] 45. Add LP/HP support to REW parser and generator
  - Add `"LP"` and `"HP"` entries to `_TYPE_MAP` and `_API_TYPE_MAP` in `src/translator/rew_parser.py` (REW uses tokens `LP` and `HP` for low-pass and high-pass filters)
  - Add `"LP": "LP"` and `"HP": "HP"` entries to `_REVERSE_TYPE_MAP` in `src/translator/rew_generator.py`
  - Verify that `_format_filter_line()` handles LP/HP formatting correctly (same layout as PK/LS/HS)
  - Add unit tests: parse a REW file containing LP/HP filters; generate a REW file with LP/HP filters; round-trip LP/HP through parse→generate→parse
  - _Root cause: LP/HP modes (3, 5) were added to `wiim_parser.py` and `wiim_generator.py` after hardware testing, but the REW translator was not updated. Exporting LP/HP filters to REW format currently causes a `KeyError`._

- [x] 46. Add LP/HP to Hypothesis PBT strategy
  - Update `st_canonical_filter()` in `src/tests/conftest.py` to sample from `["PEAK", "LS", "HS", "LP", "HP", "OFF"]`
  - Verify that all existing PBT tests still pass (the REW round-trip PBT will need task 45 completed first)
  - Verify that the WiiM round-trip PBT (task 11) now exercises LP/HP code paths
  - _Root cause: The strategy was written before LP/HP support was added; it only generates PEAK/LS/HS/OFF._

- [x] 47. Implement dynamic `max_filters` probing in capability prober
  - In `src/adapters/capability_prober.py`, after `_probe_peq()` succeeds, count the number of distinct band letters present in the `EQGetLV2BandEx` response (e.g. bands a-l = 12)
  - Set `caps.max_filters` to the detected band count instead of hardcoding `10`
  - Update `src/translator/wiim_generator.py` to accept a `max_bands` parameter (default 10 for backward compatibility) and pad/truncate to that count
  - Update `WiiMAdapter._write_peq_batch()` and `_write_peq_sequential()` to iterate `max_filters` bands instead of hardcoded `range(10)`
  - Add unit test with a 12-band fixture response verifying `max_filters == 12`
  - _Root cause: WiiM Amp Ultra (firmware 20260409) has 12 bands. `_BAND_LETTERS` already includes `"abcdefghijkl"` for reads, but writes and exports are capped at 10._

- [x] 48. Fix BackupManager channel_mode mapping for L/R mode
  - In `src/repository/backup_manager.py`, when `settings.channel_mode == "lr"`, set `channel_mode = "left"` only if both `bands_l` and `bands_r` are populated; otherwise raise `BackupError` with a descriptive message
  - Consider using `channel_mode = "left"` as a sentinel meaning "this backup has L/R data" (since Profile model requires both `filters_l` and `filters_r` for non-stereo modes) — document this mapping in a code comment
  - Add a unit test: create a backup from a PEQSettings with `channel_mode="lr"` where both `bands_l` and `bands_r` are populated; verify the BackupRecord validates and round-trips correctly
  - Add a unit test: verify that attempting to backup a PEQSettings with `channel_mode="lr"` and an empty `bands_r` raises `BackupError`
  - _Root cause: The mapping from PEQSettings `"lr"` to Profile `"left"` is lossy and fragile. If `read_peq` ever returns only one channel populated, BackupRecord construction raises a Pydantic validation error._

- [x] 49. Update `structure.md` to reflect actual project layout
  - Add `_warnings.py` to the translator section in `.kiro/steering/structure.md`
  - Verify all other listed files match what's on disk; remove any phantom entries
  - _Root cause: `ValidationWarning` was extracted to `src/translator/_warnings.py` but the steering file still implies it lives in `__init__.py`._
  - _Resolution: Verified during integrity review (2026-06-13) — `_warnings.py` was already correctly listed in structure.md. Also added `app_dirs.py` to utils section and updated phase descriptions._

- [x] 50. Graceful handling of unknown filter types and extra bands (forward compatibility)
  - **Problem**: If WiiM firmware adds a new filter mode (e.g. mode 6 = "NOTCH") or new bands (e.g. a-n for 14 bands), the tool currently crashes on read with a `ValidationError`. The user can't even view their device state.
  - **Design goal**: Reads never crash on unknown data. Unknown bands are preserved for backup/display with a warning. Writes only touch bands the tool understands.
  - **Changes required**:
    1. In `src/models/canonical.py`: Change `FilterType` from a closed `Literal` to a type that accepts unknown values gracefully. Options: (a) add a catch-all `"UNKNOWN"` variant to the Literal and store the raw mode value in an optional `raw_mode: int | None` field, or (b) use `str` for `type` with runtime validation that warns on unrecognised values instead of rejecting them.
    2. In `src/translator/wiim_parser.py`: Replace the `raise ValidationError` on unknown mode with a `logging.warning()` and return a `CanonicalFilter(type="UNKNOWN", ...)` (or equivalent). Log the raw mode value for diagnostics.
    3. In `src/translator/wiim_generator.py`: If a filter has `type="UNKNOWN"` and a `raw_mode` is available, pass the raw mode value through unchanged. If no raw mode is available, skip the band and log a warning.
    4. In `src/translator/rew_generator.py`: Skip `UNKNOWN`-type bands during REW export with a `ValidationWarning` noting which bands were omitted. Do not crash.
    5. In `src/translator/rew_parser.py`: No change needed (REW files won't contain unknown types — they're generated by REW itself).
    6. In `src/adapters/wiim_adapter.py` read path: No changes needed — it already reads all band letters dynamically.
    7. In GUI (future): Display UNKNOWN bands as read-only/greyed-out rows with a tooltip like "Unsupported filter type (mode X) — upgrade the tool for full support".
    8. In CLI `get-filters`: Display UNKNOWN bands with the type shown as `?<mode>` (e.g. `?6`) so the user sees them.
  - **Tests**:
    - Unit test: `parse_wiim_band_array` with an unknown mode value (e.g. 99) returns a filter with `type="UNKNOWN"` and logs a warning (no exception).
    - Unit test: `generate_wiim_band_array` with an UNKNOWN filter that has `raw_mode=99` produces mode 99 in the output array.
    - Unit test: `generate_wiim_band_array` with an UNKNOWN filter without `raw_mode` skips that band and emits a `ValidationWarning`.
    - Unit test: REW generator skips UNKNOWN bands and returns a warning.
    - Integration test: A device with 14 bands (hypothetical) can be read without error; bands beyond the tool's write limit are displayed but not overwritten.
  - _Rationale: WiiM has already added LP (mode 3) and HP (mode 5) in recent firmware. Future firmware could add NOTCH, BANDPASS, ALL-PASS, or additional bands. The tool must degrade gracefully rather than crash on read._

- [x] 51. Fix and test hardware-validation findings
  - Update unit tests for LP (mode 3) and HP (mode 5) filter type parsing and generation in `test_wiim_parser.py` and `test_wiim_generator.py`
  - Update unit tests for 12-band devices (letters a-l, 48-entry arrays) in `test_wiim_generator.py`
  - Add `Muzo_Mini` test case in `test_capability_prober.py`
  - Add mDNS enrichment test (discovery calls `getStatusEx`) in `test_discovery.py`
  - Add CLI L/R auto-detection test and `list-sources` test in `test_cli.py`
  - Investigate source discovery limitation and document findings
  - Ensure all existing tests still pass with LP/HP and 12-band changes
  - _Requirements: 2.10, 4.4, 4.5_

- [x] 52. Rewrite REW parser for real export format
  - Rewrite `src/translator/rew_parser.py` to handle the actual REW "Filter Settings file" format (see `docs/rew_export_examples/`)
  - Header handling: skip preamble lines until `Equaliser:` line is found; accept any equaliser type (Generic, Configurable PEQ, Parametric EQ, etc.)
  - Filter line formats to support:
    - `PK Fc <freq> Hz Gain <gain> dB Q <q>` — map to PEAK
    - `HP Q Fc <freq> Hz Q <q>` — map to HP (no gain; set gain=0)
    - `LP Q Fc <freq> Hz Q <q>` — map to LP (no gain; set gain=0)
    - `LS Q Fc <freq> Hz Gain <gain> dB Q <q>` — map to LS
    - `HS Q Fc <freq> Hz Gain <gain> dB Q <q>` — map to HS
    - `HP Fc <freq> Hz` — map to HP (Butterworth, Q=0.707, gain=0)
    - `LP Fc <freq> Hz` — map to LP (Butterworth, Q=0.707, gain=0)
    - `LS Fc <freq> Hz Gain <gain> dB` — map to LS (fixed slope, Q=0.707)
    - `HS Fc <freq> Hz Gain <gain> dB` — map to HS (fixed slope, Q=0.707)
    - `LS 12dB Fc <freq> Hz Gain <gain> dB` — map to LS (Q=0.707)
    - `HS 12dB Fc <freq> Hz Gain <gain> dB` — map to HS (Q=0.707)
    - `None` — map to OFF
  - Unsupported filter types (Modal, LP1, HP1, LS 6dB, HS 6dB, Notch, Notch Q, All-pass, L-T): emit a `ValidationWarning` and skip the band (do not crash)
  - Handle `OFF` state prefix (same as before)
  - Ignore duplicate filter sections at end of file (REW appends extra measurement filters)
  - Frequency may be integer (`50 Hz`) or decimal (`50.00 Hz`) — handle both
  - Flexible whitespace matching throughout
  - Update unit tests with the three real export examples in `docs/rew_export_examples/`
  - Preserve backward compatibility with the simple `Equaliser: Parametric EQ` format
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

- [x] 53. Rewrite RoomFit probing and adapter to use real API commands
  - **Problem**: The capability prober's `_probe_roomfit()` and `WiiMAdapter.read_roomfit()`/`write_roomfit()` use fictitious commands (`getRoomFitStatus`, `getRoomFitBands`, `setRoomFitBands`) that do not exist on WiiM devices. Hardware testing (2026-06-14) confirmed that RoomFit uses the standard LV2 PEQ commands with `EQLevel: 2` added to the JSON payload.
  - **RoomFit is NOT experimental**: All WiiM devices except Mini support RoomFit reads and profile CRUD. Only direct band writes (level 4) remain unconfirmed. The default `roomfit_level` for recognised WiiM devices (excluding Mini) should be probed dynamically, not defaulted to 0.
  - **Changes required**:
    1. In `src/adapters/capability_prober.py` — rewrite `_probe_roomfit()`:
       - Level 1: `EQv2GetNewList` with `{"pluginURI": "...", "EQLevel": 2}` — returns valid JSON (not "unknown command")
       - Level 2: `EQGetLV2SourceBandEx` with `{"pluginURI": "...", "source_name": "wifi", "EQLevel": 2}` — returns band data
       - Level 3: implicit from level 2 (band data is parseable)
       - Level 4: `EQSetLV2SourceBand` with `{"pluginURI": "...", "source_name": "wifi", "EQLevel": 2, ...}` + `EQSourceSave` — buffer write + profile save both succeed (CONFIRMED 2026-06-14). Saving to active profile deactivates RoomFit; saving to new name does not. Probe: attempt `EQSourceSave` + `EQLevel: 2` to a temporary profile name, then delete it.
    2. In `src/adapters/wiim_adapter.py` — rewrite `read_roomfit()`:
       - Use `EQv2SourceLoad` first to load the target profile into the API buffer
       - Then `EQGetLV2SourceBandEx` with `EQLevel: 2` to read the buffer
       - Accept `source_name` and `profile_name` parameters (RoomFit is per-source and profile-based)
       - Parse response identically to PEQ (same `EQBand`/`EQBandL`/`EQBandR` format)
       - Important: bare reads without a prior load return stale buffer data (persistent, device-global). Always load first.
    3. In `src/adapters/wiim_adapter.py` — rewrite `write_roomfit()`:
       - Use `EQSetLV2SourceBand` with `EQLevel: 2` to write to the API buffer
       - Then `EQSourceSave` with `EQLevel: 2` to persist the buffer to a named profile
       - Accept `source_name` and `profile_name` parameters
       - Same payload format as PEQ write but with `"EQLevel": 2` added
       - **Deactivation rule:** Saving to the currently-active profile name deactivates RoomFit (user must re-select). Saving to a new/different profile name does NOT deactivate — active profile remains applied.
       - **Recommended UX:** Default to saving as a new profile name to avoid disruption. If user chooses to overwrite the active profile, warn about deactivation.
       - Buffer is NOT cleared after save — retains the saved data with the new profile name.
    4. Update `src/tests/test_capability_prober.py`:
       - Replace mock fixtures using old commands with ones using the real LV2 commands + EQLevel
       - Test: device with RoomFit returns level 2+ (band data readable)
       - Test: WiiM Mini (no RoomFit) returns level 0 (empty profile list or "unknown command")
       - Test: profile save succeeds → level 4
    5. Update `src/tests/test_wiim_adapter.py`:
       - Replace `getRoomFitBands`/`setRoomFitBands` mock commands with `EQGetLV2SourceBandEx`/`EQSetLV2SourceBand` + `EQLevel: 2`
       - Test: `read_roomfit("wifi", "ProfileName")` issues EQv2SourceLoad then EQGetLV2SourceBandEx with EQLevel 2
       - Test: `write_roomfit("wifi", "NewProfile", filters)` issues EQSetLV2SourceBand then EQSourceSave with EQLevel 2
       - Test: `list_roomfit_profiles()` issues EQv2GetNewList with EQLevel 2 and returns profile metadata
    6. Add `list_roomfit_profiles()` to `WiiMAdapter`:
       - Wraps `EQv2GetNewList` + `EQLevel: 2`
       - Returns list of profile metadata (name, channelMode, type, updateAt)
       - Used by GUI profile selector and CLI `list-roomfit-profiles` command
    7. Add CLI command `list-roomfit-profiles --device <IP>`:
       - Displays RoomFit profiles on the device (Name | Channel Mode | Type)
       - Exit code 0 on success (even if empty list), 1 on error
       - Gated by `roomfit_level >= 1`
  - **Do NOT change**: The `roomfit_level` field semantics (0-4), `DeviceCapabilities` model, or `SafeWrite` integration — those remain the same.
  - _Root cause: Original implementation was based on assumed/speculative command names. Hardware testing confirmed RoomFit is just another EQ level within the existing LV2 plugin architecture._
  - _Requirements: 2.6, 11.1, 11.2, 11.3, 11.7_

- [x] 54. Add unit tests for `src/utils/app_dirs.py`
  - Create `src/tests/test_app_dirs.py`
  - Test `get_app_data_dir()` returns correct paths for each platform by mocking `platform.system()`:
    - Windows mock → path contains `APPDATA` or `.wiim-rew-sync`
    - macOS mock → path contains `Library/Application Support/wiim-rew-sync`
    - Linux mock (default) → path contains `.local/share/wiim-rew-sync`
  - Test that `XDG_DATA_HOME` override is respected on Linux
  - Test that missing `APPDATA` env var on Windows falls back to `~/.wiim-rew-sync`
  - _Rationale: Only utility module without dedicated tests. Simple platform-branching logic that should be verified before packaging phase._

- [x] 55. Add PEQ device profile management to WiiMAdapter and CLI
  - **Problem**: The tool currently writes directly to the live PEQ bands but has no way to list, save, or load named PEQ presets on the device. Users want to see what's on their device, save REW corrections as a device preset (persists across reboots/source switches), and load previous presets.
  - **PEQ profile workflow** (simpler than RoomFit — no buffer indirection):
    - PEQ reads/writes go directly to the live DSP state (no load-before-read needed)
    - `EQSourceSave` saves the currently-active bands as a named preset
    - `EQv2SourceLoad` loads a saved preset into the live DSP (immediate effect)
    - No deactivation side effects (unlike RoomFit)
  - **Changes required**:
    1. Add `list_peq_profiles(source_name: str)` to `WiiMAdapter`:
       - Wraps `EQv2GetNewList` + `{"pluginURI": "...", "EQLevel": 1}` (or omit EQLevel)
       - Returns list of profile metadata (name, channelMode, type)
    2. Add `save_peq_profile(source_name: str, profile_name: str)` to `WiiMAdapter`:
       - Wraps `EQSourceSave` — saves the currently-active live bands as a named preset
       - If profile_name already exists, it is overwritten
    3. Add `load_peq_profile(source_name: str, profile_name: str)` to `WiiMAdapter`:
       - Wraps `EQv2SourceLoad` — loads a saved preset into the live DSP
       - Immediate effect on audio output (unlike RoomFit)
    4. Add `delete_peq_profile(profile_name: str)` to `WiiMAdapter`:
       - Wraps `EQv2Delete` — removes a saved preset
    5. Add CLI commands:
       - `list-peq-profiles --device <IP>` — displays PEQ presets on device (Name | Channel Mode)
       - Update `set-filters` to accept optional `--save-as <PROFILE_NAME>` — after writing to live DSP, also saves as a device preset
    6. Add unit tests with mocked HTTP client for all four adapter methods
    7. Add CLI tests for `list-peq-profiles` and `--save-as` flag
  - **Integration with existing safe-write workflow**: The `set-filters` command currently writes to live DSP via SafeWrite (backup → write → verify). Adding `--save-as` simply calls `save_peq_profile()` AFTER the SafeWrite succeeds — it's a post-commit step, not part of the verification loop.
  - _Requirements: 2.5 (supports_profile_enumeration), 9.5 (profile library UX)_

- [ ] 56. Add unit tests for hardware-testing fixes (channel mode, L/R write, RoomFit CLI)
  - **Problem**: Several bugs were fixed during manual hardware testing (Task 32) but lack dedicated unit tests. The fixes work correctly but are only validated by the hardware tests, not by the automated suite.
  - **Tests to add**:
    1. In `src/tests/test_safe_write.py` — **channel mode adaptation**:
       - Test: writing stereo settings to an L/R device calls `_set_channel_mode("Stereo")` before writing
       - Test: writing L/R settings to a stereo device calls `_set_channel_mode("L/R")` before writing
       - Test: matching modes (stereo→stereo) does not call `_set_channel_mode`
    2. In `src/tests/test_safe_write.py` — **band count tolerance in verification**:
       - Test: verification passes when device returns 12 bands but only 10 were written (extra bands ignored)
       - Test: verification still fails if one of the first 10 bands doesn't match
    3. In `src/tests/test_wiim_adapter.py` — **L/R write paths**:
       - Test: `_write_peq_batch_lr` sends payload with `EQBandL` and `EQBandR` keys
       - Test: `_write_peq_sequential_lr` enqueues 10 commands, each with `EQBandL` and `EQBandR`
       - Test: `write_peq` with `channel_mode="lr"` and both `bands_l`/`bands_r` populated calls the L/R path
    4. In `src/tests/test_cli.py` — **RoomFit CLI commands**:
       - Test: `get-roomfit-filters` displays stereo table for stereo profile
       - Test: `get-roomfit-filters` displays both L/R tables for L/R profile
       - Test: `set-roomfit-filters` calls `write_roomfit` with correct args
       - Test: `set-roomfit-filters` on unsupported device prints appropriate error
    5. In `src/tests/test_wiim_adapter.py` — **EQSetLV2ChannelMode call**:
       - Test: `_set_channel_mode("Stereo")` issues `EQSetLV2ChannelMode` with correct payload
       - Test: `_set_channel_mode("L/R")` issues correct command
  - _Rationale: All fixes confirmed working on real hardware (Task 32 passed) but need automated regression tests to prevent future breakage._
    6. In `src/tests/test_cli.py` — **`--file-right` L/R write via CLI**:
       - Test: `set-filters --file left.txt --file-right right.txt` parses both files and writes L/R mode
       - Test: `--file-right` without `--file` still requires `--file` (argparse enforces)
    7. In `src/tests/test_safe_write.py` — **rollback with L/R data**:
       - Test: rollback restores original L/R bands (not just stereo)
    8. In `src/tests/test_capability_prober.py` — **RoomFit probe doesn't hit HTTP 431**:
       - Test: probe with L/R 12-band response does NOT attempt `EQSetLV2SourceBand` (only `EQSourceSave`)
       - Verify the probe payload stays small regardless of device band count/channel mode

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": [1] },
    { "wave": 2, "tasks": [2, 3] },
    { "wave": 3, "tasks": [4] },
    { "wave": 4, "tasks": [5, 6, 9] },
    { "wave": 5, "tasks": [7, 10, 13] },
    { "wave": 6, "tasks": [8, 11, 12, 14] },
    { "wave": 7, "tasks": [15] },
    { "wave": 8, "tasks": [16, 18] },
    { "wave": 9, "tasks": [17, 19] },
    { "wave": 10, "tasks": [20, 21] },
    { "wave": 11, "tasks": [22, 24, 25] },
    { "wave": 12, "tasks": [23, 26, 27] },
    { "wave": 13, "tasks": [28, 29, 30] },
    { "wave": 14, "tasks": [31] },
    { "wave": 14.5, "tasks": [45, 48] },
    { "wave": 14.6, "tasks": [46, 47] },
    { "wave": 14.7, "tasks": [51] },
    { "wave": 14.8, "tasks": [50] },
    { "wave": 14.9, "tasks": [52, 53, 54, 55] },
    { "wave": 15, "tasks": [32] },
    { "wave": 15.5, "tasks": [49, 56] },
    { "wave": 16, "tasks": [33, 42] },
    { "wave": 17, "tasks": [34] },
    { "wave": 18, "tasks": [35] },
    { "wave": 19, "tasks": [36, 37, 38] },
    { "wave": 20, "tasks": [39] },
    { "wave": 21, "tasks": [40, 41] },
    { "wave": 22, "tasks": [43] },
    { "wave": 23, "tasks": [44] }
  ]
}
```

## Notes

- All PBT tasks use Hypothesis with `@settings(max_examples=100)` minimum
- Strategies `st_canonical_filter()`, `st_canonical_filter_list()`, and `st_float_near_boundary()` are defined in `src/tests/conftest.py` and shared across all PBT tasks
- The `TranslationEngine` is strictly stateless — all methods are `@staticmethod`; any attempt to add instance state is a design violation
- All WiiM device writes must go through the `WiiMCommandQueue`; direct writes bypassing the queue are forbidden
- The Safe Write Protocol (Backup → Write → Read-Back → Verify → Commit/Rollback) must not be abbreviated under any circumstances
- Coverage target: ≥ 90% for `src/translator/`, ≥ 80% overall (`pytest --cov=src --cov-report=term-missing`)
- `mypy` strict mode is enforced for `src/translator/` and `src/models/`; all other modules require at minimum zero mypy errors in default mode
- The `docs/corrections.md` file should be updated whenever real-hardware testing reveals API behaviour that diverges from the documented spec

## Integrity Review Log (2026-06-13)

Findings from full codebase integrity review. Decisions documented here for future reference.

### Resolved

1. **SafeWrite accessing private `_capabilities`** — FIXED. Added a public `capabilities` property to `WiiMAdapter`. `SafeWrite` now uses `adapter.capabilities` instead of `adapter._capabilities`. Tests updated to match.

2. **Task 49 (`structure.md` accuracy)** — CLOSED. Verified that `_warnings.py` was already correctly listed. Also added `app_dirs.py` to the utils section and updated phase descriptions during the review.

### Intentionally Deferred (no action needed)

3. **`src/utils/app_dirs.py` has no dedicated test file** — RESOLVED. Added as Task 54 in wave 14.9 (pre-packaging). Will be implemented alongside Tasks 52/53.

4. **mypy "unused section" warning for PySide6/respx/zeroconf overrides** — RESOLVED. Set `warn_unused_configs = false` in pyproject.toml. These overrides exist for GUI-phase imports. The note was harmless but noisy.
