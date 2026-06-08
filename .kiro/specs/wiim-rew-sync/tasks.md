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

- [ ] 4. Implement floating-point tolerance utilities
  - Create `src/utils/fp_compare.py` with constants: `FREQ_TOLERANCE_HZ = 0.1`, `GAIN_TOLERANCE_DB = 0.05`, `Q_TOLERANCE = 0.01`
  - Implement `freq_matches(a, b)`, `gain_matches(a, b)`, `q_matches(a, b)` predicates
  - Implement `band_matches(intended, read_back)` — OFF bands require only type match
  - Write unit tests in `src/tests/test_fp_compare.py` covering exact boundary values (pass at ε, fail at ε + 0.0001)
  - _Requirements: 5.6_

- [ ] 5. Write property test: floating-point tolerance predicate correctness (PBT)
  - In `src/tests/test_fp_compare.py`, add a Hypothesis `@given` test
  - Define a `st_float_near_boundary(center, tolerance)` strategy in `conftest.py`
  - Property: `band_matches()` returns True iff `|a - b| <= tolerance` for each parameter type; OFF bands always True
  - Use `@settings(max_examples=100)`
  - **Validates: Requirements 5.6, 16.7**

### Phase 2: Translation Engine

- [ ] 6. Implement REW text file parser
  - Create `src/translator/rew_parser.py` implementing `REWParser`
  - `parse_file(path)` requires first line exactly `Equaliser: Parametric EQ`; maps `PK`→`"PEAK"`, `LS`→`"LS"`, `HS`→`"HS"`, `OFF <type>`→`"OFF"`
  - Raise `ParseError` (with line number) for malformed lines; raise `ValidationError` for unknown type tokens or frequency outside 10–22000 Hz
  - Implement `parse_filter_settings(filter_settings)` for REW HTTP API `FilterSetting` objects
  - Write unit tests covering valid file, OFF filter, all type mappings, frequency error, unknown type error, malformed line error
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

- [ ] 7. Implement REW text file generator
  - Create `src/translator/rew_generator.py` implementing `REWGenerator`
  - `generate_file(filters, path, max_filters=10)`: first line exactly `Equaliser: Parametric EQ`; 1-based two-digit zero-padded numbering; gain and freq to 2 dp, Q to 3 dp; OFF bands as `OFF PK Fc <freq> Hz Gain <gain> dB Q <q>`
  - `generate_lr_files(filters_l, filters_r, base_path, max_filters=10)`: two files with `_L` / `_R` suffixes; return `(left_path, right_path)`
  - Write unit tests: first-line format, band numbering, decimal precision, OFF band format, L/R suffix naming
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [ ] 8. Write property test: REW parse-generate-parse round-trip (PBT)
  - In `src/tests/test_translator.py`, add a Hypothesis `@given` test
  - Define `st_canonical_filter()` and `st_canonical_filter_list(min_size=1, max_size=10)` strategies in `conftest.py`
  - Property: for any valid `CanonicalFilter` list, `generate_file` → `parse_file` must return a list identical to the original
  - Use `@settings(max_examples=100)`
  - **Validates: Requirements 16.6, 6.1, 6.3, 7.1, 7.2, 7.3, 7.4, 7.5**

- [ ] 9. Implement WiiM API response parser
  - Create `src/translator/wiim_parser.py`
  - `parse_wiim_band_array(band_array, channel="stereo")` maps `EQBand`/`EQBandL`/`EQBandR` arrays to `list[CanonicalFilter]`
  - Mode mapping: `−1`→`"OFF"`, `1`→`"PEAK"`, `0`→`"LS"`, `2`→`"HS"`
  - Write unit tests: 10-band array, L/R mode, all mode value mappings
  - _Requirements: 4.2, 4.3, 4.4, 4.5_

- [ ] 10. Implement WiiM API payload generator
  - Create `src/translator/wiim_generator.py`
  - `generate_wiim_band_array(filters)` produces 40-entry parameter list (4 params × 10 bands)
  - Clip gain to ±12 dB and Q to 0.01–24; log WARNING for each clip
  - Write unit tests: 10 filters → 40-entry output, OFF maps to mode −1, clipping triggers and logs warnings, round-trip within tolerance
  - _Requirements: 6.7, 6.8, 16.3, 16.4, 16.5_

- [ ] 11. Write property test: WiiM generate-parse round-trip (PBT)
  - In `src/tests/test_translator.py`, add a Hypothesis `@given` test
  - Reuse `st_canonical_filter_list` strategy
  - Property: for any valid `CanonicalFilter` list, `generate_wiim_band_array` → `parse_wiim_band_array` must produce filters matching originals within tolerances (freq ±0.1 Hz, gain ±0.05 dB, Q ±0.01)
  - Use `@settings(max_examples=100)`
  - **Validates: Requirements 16.7, 4.2, 4.4, 4.5**

- [ ] 12. Write property test: WiiM value clipping invariant (PBT)
  - In `src/tests/test_translator.py`, add a Hypothesis `@given` test
  - Strategy: generate `CanonicalFilter` objects with gain and Q values outside WiiM limits
  - Property: `generate_wiim_band_array()` must always produce entries with gain in [−12.0, +12.0] and Q in [0.01, 24.0], regardless of input values
  - Use `@settings(max_examples=100)`
  - **Validates: Requirements 6.7, 6.8, 16.3, 16.4**

- [ ] 13. Implement schema migrator
  - Create `src/translator/schema_migrator.py`
  - `migrate_profile(raw: dict) -> dict`: upgrade from any older `schema_version` to current; raise `SchemaVersionError` if migration is impossible
  - Write unit tests: current-version is no-op, old version migrates, unknown version raises `SchemaVersionError`
  - _Requirements: 9.8_

- [ ] 14. Assemble TranslationEngine facade and verify coverage
  - Create `src/translator/__init__.py` with the stateless `TranslationEngine` facade (all `@staticmethod` methods)
  - Run `pytest --cov=src/translator --cov-report=term-missing` and confirm ≥ 90% coverage
  - Ensure `mypy src/translator/` passes with zero errors
  - _Requirements: 16.1, 16.2_

### Phase 3: Network & Discovery

- [ ] 15. Implement WiiM HTTP client
  - Create `src/adapters/wiim_http.py` implementing `WiiMHttpClient`
  - Use `httpx.AsyncClient` with `verify=False` and default 5 s timeout
  - `command(command)`: GET `https://<ip>/httpapi.asp?command=<command>`; return parsed JSON dict or raw string
  - Log every request/response pair to `wiim_api.log`
  - Raise `WiiMTimeoutError`, `WiiMConnectionError`, `WiiMResponseError` as appropriate
  - Write unit tests using `respx` or `unittest.mock.AsyncMock`
  - _Requirements: 4.6, 8.6, 14.7, 15.4_

- [ ] 16. Implement device discovery module
  - Create `src/discovery/zeroconf_discover.py` for mDNS probing (`_wiim._tcp.local.` → `_linkplay._tcp.local.`)
  - Create `src/discovery/subnet_scanner.py` for fallback scan: `getStatusEx` probe; accept only recognisable `project` fields; exclude unrecognised hosts
  - Create `src/discovery/discovery_module.py` implementing `DiscoveryModule` with `discover()` and `refresh()` (configurable timeout, non-blocking, returns empty list on no results)
  - Write unit tests with fake `ServiceInfo` callbacks and mocked `WiiMHttpClient`
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

- [ ] 17. Write property test: discovery result field completeness (PBT)
  - In `src/tests/test_discovery.py`, add a Hypothesis `@given` test
  - Strategy: generate `getStatusEx` response dicts with valid WiiM `project` fields and varying `DeviceName`, `Release`, `ip` values
  - Property: for any valid WiiM response, `DiscoveryModule` must produce a `DeviceInfo` with non-empty `ip`, `name`, `model`, and `firmware`
  - Use `@settings(max_examples=100)`
  - **Validates: Requirements 1.5, 1.8**

- [ ] 18. Implement capability prober
  - Create `src/adapters/capability_prober.py` implementing `CapabilityProber`
  - `probe()` never raises; all failed probes default to the most conservative value
  - Probing sequence: `getStatusEx` → `EQGetLV2BandEx` → batch-write test → `EQGetLV2List` → RoomFit levels 0–4 sequential probe → `GetMultiroomInfo`
  - `max_filters`: 10 for WiiM, 0 for generic LinkPlay, 0 for unrecognised
  - Write unit tests with mocked `WiiMHttpClient` and canned fixture responses
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10_

### Phase 4: WiiM Adapter & Safe Write

- [ ] 19. Implement WiiM adapter — PEQ read
  - Create `src/adapters/wiim_adapter.py` implementing `WiiMAdapter`
  - `read_peq(source_name)`: issue `EQGetLV2SourceBandEx`; convert via `wiim_parser`; return `PEQSettings`
  - Stereo: parse `EQBand`; L/R: parse `EQBandL` and `EQBandR` separately
  - Raise `WiiMResponseError` on missing fields; `WiiMConnectionError` on unreachable device
  - `get_multiroom_master_ip()`: return master IP from `GetMultiroomInfo` or None
  - Write unit tests with mocked HTTP client and fixture JSON responses
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

- [ ] 20. Implement WiiM adapter — PEQ write and RoomFit
  - Add `write_peq(source_name, settings, queue)` to `WiiMAdapter`: batch path when `supports_batch_write=True`, queue path otherwise; raise `WiiMSlaveTargetError` if device role is slave
  - Add `read_roomfit()` and `write_roomfit(filters)` (gated by `roomfit_level`)
  - Write unit tests: batch path, sequential path, slave guard
  - _Requirements: 5.3, 5.4, 5.11, 17.1, 17.4_

- [ ] 21. Implement WiiM command queue
  - Create `src/adapters/command_queue.py` implementing `WiiMCommandQueue`
  - Single asyncio FIFO consumer; 100 ms inter-command delay; max 3 retries per command
  - `start()`, `drain_and_stop()`, `cancel()` lifecycle
  - Read-only GET calls bypass the queue
  - Write unit tests: FIFO order, timing, retry on failure, clean drain
  - _Requirements: 5.4, 18.1_

- [ ] 22. Implement backup manager
  - Create `src/repository/backup_manager.py` implementing `BackupManager`
  - `create_backup(settings, capabilities, trigger)`: write `BackupRecord` JSON; ISO 8601 timestamp required; `profile_type="backup"` and `trigger` field present
  - Retention: MAX 20 per device UUID; 21st triggers deletion of oldest; deletion failure → raise `BackupError` and abort
  - `list_backups(device_uuid)`: sorted oldest-first
  - Backups stored in `storage_root/backups/`, not visible in profile library
  - Write unit tests using `tmp_path`: creation, retention at 20, deletion trigger at 21, deletion-failure → `BackupError`
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

- [ ] 23. Implement safe write protocol
  - Create `src/adapters/safe_write.py` implementing `SafeWrite` and `WriteResult`
  - `execute()` implements the five-step sequence in order: (1) Backup, (2) Write, (3) Read-Back (fresh call), (4) Verify via `band_matches()`, (5a) Commit / (5b) Rollback
  - On rollback: create `"pre_rollback"` backup; write backup state via queue; verify rollback
  - Rollback failure: log CRITICAL to `app.log` with backup path; return `WriteResult(success=False, rollback_success=False)`
  - Raise `WiiMSlaveTargetError` if target is slave
  - Write unit tests: success path, verify failure → rollback success, rollback failure → CRITICAL log, batch vs sequential branches
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11_

### Phase 5: REW Adapter & Repository

- [ ] 24. Implement REW HTTP API client
  - Create `src/adapters/rew_http_client.py` implementing `REWHttpApiClient`
  - `list_measurements()`: GET `http://localhost:4735/measurements`; return `list[MeasurementSummary]`; raise `REWNotConnectedError` on connection refused
  - `get_filters(uuid)`: parse `FilterSetting` objects via `REWParser.parse_filter_settings()`; raise `REWMeasurementNotFoundError` on 404
  - Log all requests/responses to `rew_api.log`
  - Write unit tests with mocked httpx responses
  - _Requirements: 8.1, 8.3, 8.4, 8.5, 8.6_

- [ ] 25. Implement profile repository
  - Create `src/repository/profile_repository.py` implementing `ProfileRepository`
  - OS-appropriate storage via `src/utils/app_dirs.py`
  - Implement all nine operations: `save`, `load`, `list`, `delete`, `rename`, `duplicate`, `add_tag`, `remove_tag`, `get_by_tag`
  - `save()`: Stereo → `filters` key only; L/R → `filters_l`/`filters_r` only
  - `load()`: validate channel-mode/filter-key consistency; apply schema migration; raise `ProfileNotFoundError` for missing names
  - `list()`: lexicographic, case-insensitive sort
  - Tags must persist across app restarts
  - Write unit tests using `tmp_path` pytest fixture
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10_

- [ ] 26. Write property test: profile channel-mode key invariant (PBT)
  - In `src/tests/test_profile_repository.py`, add a Hypothesis `@given` test
  - Strategy: generate `Profile` objects in both Stereo and L/R modes with varying filter contents
  - Property: `save()` → `load()` round-trip preserves correct filter key structure for both channel modes
  - Use `@settings(max_examples=100)`
  - **Validates: Requirements 9.2, 9.3, 9.4**

- [ ] 27. Write property test: profile list sort-order invariant (PBT)
  - In `src/tests/test_profile_repository.py`, add a Hypothesis `@given` test
  - Strategy: generate arbitrary sets of profile names with varying case, length, and leading characters
  - Property: for any set of profiles saved in any order, `list()` returns them in ascending lexicographic order by name (case-insensitive)
  - Use `@settings(max_examples=100)`
  - **Validates: Requirements 9.6**

### Phase 6: CLI Proof of Concept

- [ ] 28. Implement CLI — `list-devices`
  - Create `src/cli/main.py` with argparse entry point; register as `wiim-rew-sync` console script in `pyproject.toml`
  - `list-devices`: run discovery; print tabular output (Name | IP | Model | Firmware | Role); print "No devices found." if empty; exit code 0 in both cases
  - Support global options: `--timeout FLOAT` and `--log-level LEVEL`
  - _Requirements: 1.1, 1.6_

- [ ] 29. Implement CLI — `get-filters`
  - Add `get-filters --device <ip> [--source <name>] [--channel <stereo|left|right>]` command
  - Print 10-row table: Band | Type | Frequency (Hz) | Gain (dB) | Q
  - Exit code 0 on success, 1 on error
  - _Requirements: 4.1, 4.2, 4.3_

- [ ] 30. Implement CLI — `dry-run-import`
  - Add `dry-run-import --file <path>` command
  - Parse REW file, translate to Canonical, print filter table with WiiM range warnings; no network calls
  - Exit code 0 on valid file, 1 on parse/validation error
  - _Requirements: 12.1, 12.2, 12.3, 6.7, 6.8_

- [ ] 31. Implement CLI — `set-filters`
  - Add `set-filters --file <path> --device <ip> [--source <name>] [--channel <stereo|left|right>]` command
  - Run full safe-write with per-step progress output; print rollback or critical-error output as appropriate
  - Exit code 0 on verified success, 1 on any failure
  - _Requirements: 5.1–5.10, 12.1–12.3_

- [ ] 32. CLI end-to-end hardware validation (phase gate)
  - Run all four CLI commands against physical WiiM hardware
  - Verify `get-filters` output matches WiiM app; verify `set-filters` filter change is visible in WiiM app
  - Document any API deviations in `docs/corrections.md`
  - ⚠️ Do not proceed to Phase 7 until all CLI commands pass on real hardware

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
  - Filter table: 10 rows × 5 columns; OFF bands shown in grey
  - Pull button → `WiiMAdapter.read_peq()` via `AsyncBridge`; table updates on `peq_ready`
  - _Requirements: 3.1, 3.2, 3.3, 3.5, 4.1, 11.1, 11.2, 11.3_

- [ ] 36. Implement import and export dialogs
  - Create `src/gui/dialogs/import_dialog.py`: `.txt` file dialog; synchronous parse; preview table with `ValidationWarning` items highlighted in orange; inline warning banner with acknowledgement checkbox if `len(filters) > max_filters`
  - Create `src/gui/dialogs/export_dialog.py`: save-mode file dialog; L/R mode shows two path fields with `_L.txt` / `_R.txt` pre-fills
  - _Requirements: 6.7, 6.8, 6.9, 6.10, 7.6, 14.2_

- [ ] 37. Implement profile panel
  - Create `src/gui/panels/profile_panel.py`
  - All nine CRUD+tag operations accessible from the panel
  - Loading a profile populates the filter table in the EQ panel
  - Loading a Stereo profile onto an L/R device (or vice versa) shows a mode mismatch warning requiring explicit confirmation
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
  - Wire all buttons to `AsyncBridge.run_async()` with progress indicator and Cancel support
  - _Requirements: 3.2, 3.6, 5.11, 12.1, 12.2, 12.3, 12.4, 12.5, 17.2, 18.4, 18.5, 18.6_

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
  - Include all assets and logging configuration; verify each build runs without Python installed
  - _Requirements: 19.1, 19.2, 19.3, 19.4_

- [ ] 44. Final QA sign-off (release gate)
  - Execute all QA scenarios from `docs/qa.md` against real hardware
  - Run full test suite: confirm ≥ 90% coverage for `src/translator/`, ≥ 80% overall
  - Run `ruff check src/` and `mypy src/` with zero errors; document any deviations in `docs/corrections.md`
  - ⚠️ Do not release until all QA scenarios pass

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
    { "wave": 15, "tasks": [32] },
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
