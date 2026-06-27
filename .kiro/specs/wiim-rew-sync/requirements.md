# Requirements Document

## Introduction

The WiiM ↔ REW PEQ Sync Tool is a cross-platform desktop application (Python + PySide6) that transfers parametric EQ and RoomFit filter configurations between REW (Room EQ Wizard) and WiiM audio streaming devices on a local network. It provides a safe, reversible workflow for applying room correction filters to WiiM hardware: every write operation is preceded by a backup and followed by read-back verification, with automatic rollback on failure. The application operates entirely on the local network with no cloud dependencies.

All data must flow through a Canonical Filter Model — direct REW-to-WiiM or WiiM-to-REW conversion without this intermediary is forbidden.

---

## Glossary

- **Canonical Filter**: The normalised internal representation of a single EQ band, containing `type`, `frequency_hz`, `gain_db`, and `q`. All import and export operations convert to/from this model.
- **CanonicalFilter**: The Pydantic model class implementing the Canonical Filter.
- **PEQBand**: The WiiM-level representation of a single EQ band using letter keys (`a`–`j`) and `_mode`/`_freq`/`_q`/`_gain` parameters.
- **PEQSettings**: The full PEQ state for one source on a device, including channel mode and all bands.
- **DeviceCapabilities**: The runtime-probed capability set of a discovered WiiM device.
- **Profile**: A named, locally-stored JSON snapshot of a PEQ filter set, created by the user.
- **BackupRecord**: An automatically-created JSON snapshot of a device's PEQ state, taken immediately before any write operation.
- **Translation Engine**: The stateless component that converts between REW text, Canonical, and WiiM API formats.
- **WiiM Command Queue**: The single-writer FIFO queue that serialises all WiiM PEQ write operations.
- **Safe Write Protocol**: The mandatory Backup → Write → Read-Back → Verify → Commit/Rollback sequence.
- **RoomFit**: WiiM's dedicated room-correction filter set, separate from per-input PEQ bands, supported on all WiiM devices except WiiM Mini.
- **REW**: Room EQ Wizard, a desktop acoustic measurement and equalisation application.
- **Dry Run**: An operational mode in which filters are translated and previewed but no write commands are dispatched to any device.
- **Diagnostics Panel**: A developer-facing UI panel (hidden by default) providing raw API access, log tailing, and capability inspection.
- **Source**: A named audio input on a WiiM device (e.g. `wifi`, `bluetooth`, `line-in`). PEQ is configured independently per source.
- **L/R Mode**: Independent left-channel and right-channel PEQ, supported on all WiiM devices.
- **Stereo Mode**: Shared left+right PEQ, the default channel mode.
- **pluginURI**: The LV2 plugin identifier for WiiM's parametric EQ: `http://moddevices.com/plugins/caps/EqNp`.
- **App**: The WiiM ↔ REW PEQ Sync Tool desktop application.

---

## Requirements

### Requirement 1: Device Discovery

**User Story:** As a user, I want the application to automatically find WiiM devices on my local network, so that I can select a device without manually entering IP addresses.

#### Acceptance Criteria

1. WHEN the App starts, THE Discovery_Module SHALL probe for WiiM devices using the `_wiim._tcp.local.` mDNS service type.
2. IF `_wiim._tcp.local.` yields no results, THEN THE Discovery_Module SHALL probe using `_linkplay._tcp.local.` as a secondary mDNS service type.
3. IF both mDNS probes yield no results, THEN THE Discovery_Module SHALL perform a subnet scan on ports 80 and 443, issuing a `getStatusEx` probe to each host and accepting only hosts whose response contains a recognisable `project` field.
4. WHEN discovery completes with no devices found (no devices were discovered at any point during the attempt), THE Discovery_Module SHALL return an empty list without raising an exception; devices that were found but lost or failed to process before completion SHALL NOT cause an empty list to be returned if at least one valid device was confirmed.
5. WHEN a device is discovered, THE Discovery_Module SHALL expose the device's IP address, friendly name (`DeviceName`), model (`project`), and firmware version (`Release`).
6. WHEN the user requests a manual refresh, THE Discovery_Module SHALL re-run the full discovery sequence and update the device list.
7. THE Discovery_Module SHALL complete each discovery attempt within a configurable timeout (default 5 seconds), SHALL NOT block the application event loop during discovery, and manual refresh SHALL also be non-blocking.
8. WHEN a discovered host responds to `getStatusEx` with a `project` field that does not indicate a WiiM device, THE Discovery_Module SHALL exclude that host from the device list.

---

### Requirement 2: Capability Detection

**User Story:** As a user, I want the application to adapt to my specific WiiM device's capabilities, so that unsupported features are hidden and supported features are always available.

#### Acceptance Criteria

1. WHEN a device is selected, THE Capability_Prober SHALL probe the device and populate a `DeviceCapabilities` object for it before any UI controls are enabled; `DeviceCapabilities` SHALL NOT exist for a device until that device has been explicitly selected.
2. THE Capability_Prober SHALL determine `supports_peq` by attempting `EQGetLV2BandEx`; if the command returns a valid response, `supports_peq` is True.
3. THE Capability_Prober SHALL determine `supports_lr_filters` by inspecting the `channelMode` field in the `EQGetLV2BandEx` response.
4. THE Capability_Prober SHALL determine `supports_batch_write` by attempting a write of all 10 bands in a single `EQSetLV2Band` payload and confirming the response indicates success.
5. THE Capability_Prober SHALL determine `supports_profile_enumeration` by attempting `EQGetLV2List`.
6. THE Capability_Prober SHALL determine `roomfit_level` using a sequential probe sequence (levels 0–4); the level is set to the highest confirmed level.
7. THE Capability_Prober SHALL determine the device's multiroom `role` by calling `GetMultiroomInfo`.
8. WHEN any capability probe fails or returns an unexpected response, THE Capability_Prober SHALL set that capability to its most conservative (safest) default value and SHALL NOT raise an exception.
9. THE Capability_Prober SHALL set `max_filters` to 10 for all WiiM devices, to 0 for generic LinkPlay devices, and to 0 (most conservative default) for any device that is neither WiiM nor generic LinkPlay.
10. THE App SHALL NOT hard-code capabilities by device model name; runtime probing determines all capabilities.

---

### Requirement 3: Source Input Selection

**User Story:** As a user, I want to select which audio input source I am configuring EQ for, so that my filter settings apply to the correct input.

#### Acceptance Criteria

1. WHEN a device is selected, THE App SHALL fetch the device's `InputList` from the `getStatusEx` response and populate the source selector with exactly those inputs.
2. THE App SHALL NOT auto-select any source for write operations; the user must explicitly choose a source before any PEQ write is initiated.
3. WHEN the user selects a device, THE App SHALL always pre-select the currently active source for display purposes only.
4. WHEN the device's `InputList` changes (detected on next device selection or manual refresh), THE App SHALL update the source selector to reflect the current list.
5. THE App SHALL pass the selected `source_name` to all subsequent PEQ read and write operations targeting that device.
6. IF the user attempts a PEQ write without having selected a source, THE App SHALL present an error and SHALL NOT proceed with the write.

---

### Requirement 4: PEQ Read (Pull)

**User Story:** As a user, I want to read the current parametric EQ settings from a WiiM device, so that I can inspect or export the active configuration.

#### Acceptance Criteria

1. WHEN the user initiates a Pull for a selected device and source, THE WiiM_Adapter SHALL issue `EQGetLV2SourceBandEx` with the selected `source_name` and the `pluginURI`.
2. WHEN the device's `channelMode` is `"Stereo"`, THE WiiM_Adapter SHALL return a single list of 10 `CanonicalFilter` objects derived from the `EQBand` array; IF the expected format cannot be produced due to missing data or error, THE WiiM_Adapter SHALL raise an explicit `WiiMResponseError`.
3. WHEN the device's `channelMode` is `"L/R"`, THE WiiM_Adapter SHALL return separate left and right lists of 10 `CanonicalFilter` objects derived from `EQBandL` and `EQBandR` respectively; IF either list cannot be produced, THE WiiM_Adapter SHALL raise an explicit `WiiMResponseError`.
4. WHEN a band's `{letter}_mode` value is `-1`, THE WiiM_Adapter SHALL map it to `CanonicalFilter.type = "OFF"`.
5. WHEN a band's `{letter}_mode` value is `1`, `0`, or `2`, THE WiiM_Adapter SHALL map it to `CanonicalFilter.type` of `"PEAK"`, `"LS"`, or `"HS"` respectively.
6. THE WiiM_Adapter SHALL log all HTTP requests and responses to `wiim_api.log`.
7. IF the device is unreachable during a Pull, THE WiiM_Adapter SHALL raise a `WiiMConnectionError` and THE App SHALL display a connection error to the user without crashing.

---

### Requirement 5: PEQ Write (Push) — Safe Write Protocol

**User Story:** As a user, I want to write parametric EQ filters to a WiiM device safely, so that if anything goes wrong the device's original settings are restored automatically.

#### Acceptance Criteria

1. WHEN the user initiates a Push, THE Safe_Write component SHALL execute the following sequence in order with no steps omitted: (1) Backup, (2) Write, (3) Read-Back, (4) Verify, (5a) Commit on pass or (5b) Rollback on fail.
2. THE Safe_Write component SHALL create a `BackupRecord` of the current device PEQ state before issuing any write command.
3. WHEN `supports_batch_write` is True, THE Safe_Write component SHALL write all 10 bands in a single `EQSetLV2Band` payload.
4. WHEN `supports_batch_write` is False, THE Safe_Write component SHALL write bands sequentially via the `WiiM_Command_Queue` with a 100 ms inter-command delay.
5. AFTER writing, THE Safe_Write component SHALL fetch the live device state via a fresh `EQGetLV2SourceBandEx` call (not a cached value).
6. THE Safe_Write component SHALL compare each band's frequency, gain, and Q of the intended Canonical model against the read-back Canonical model using tolerances: frequency ±0.1 Hz, gain ±0.05 dB, Q ±0.01.
7. WHEN all bands pass verification, THE Safe_Write component SHALL return a success result and notify the user.
8. WHEN any band fails verification, THE Safe_Write component SHALL trigger rollback: write the backup state back to the device via the `WiiM_Command_Queue` and verify the rollback write.
9. WHEN rollback succeeds, THE Safe_Write component SHALL notify the user that the write failed but the original state has been restored.
10. WHEN rollback itself fails (e.g. due to network drop), THE Safe_Write component SHALL log a CRITICAL entry to `app.log` including the backup file path, and SHALL display an explicit user-facing message with the backup file path and manual recovery instructions.

---

### Requirement 6: REW Text File Import

**User Story:** As a user, I want to import an EQ filter file exported from REW, so that I can apply room correction results to my WiiM device.

#### Acceptance Criteria

1. WHEN the user selects a REW EQ text file for import, THE REW_Parser SHALL parse the file and produce a list of `CanonicalFilter` objects.
2. THE REW_Parser SHALL accept files whose first line is exactly `Equaliser: Parametric EQ`.
3. THE REW_Parser SHALL map filter type tokens: `PK` → `"PEAK"`, `LS` → `"LS"`, `HS` → `"HS"`, and `OFF <type>` → `"OFF"`.
4. WHEN a filter line contains a frequency outside 10–22000 Hz, THE REW_Parser SHALL raise a `ValidationError` before any device interaction occurs.
5. WHEN a filter line contains an unknown filter type token, THE REW_Parser SHALL raise a `ValidationError` with a descriptive message.
6. WHEN a filter line is malformed (missing fields or unparseable values), THE REW_Parser SHALL raise a `ParseError` with a descriptive message identifying the offending line.
7. WHEN imported gain values are within REW's valid range but outside WiiM's ±12 dB hardware limit, THE App SHALL display a validation warning and require the user to acknowledge before proceeding; THE Translation_Engine SHALL clip the values to WiiM limits before any write.
8. WHEN imported Q values are within REW's valid range but outside WiiM's 0.01–24 range, THE App SHALL display a validation warning and require acknowledgement; THE Translation_Engine SHALL clip the values before any write.
9. WHEN the imported file contains more filter bands than the selected device's `max_filters`, THE App SHALL display a warning stating how many bands will be used and how many discarded; only the first `max_filters` enabled bands in file order are used, and THE App SHALL require acknowledgement before proceeding.
10. THE App SHALL NOT make any network calls during REW file import, regardless of whether parsing succeeds or fails; import is a strictly local-only operation.

---

### Requirement 7: REW Text File Export

**User Story:** As a user, I want to export the current WiiM PEQ filters to a REW-compatible text file, so that I can load them back into REW for further analysis.

#### Acceptance Criteria

1. WHEN the user requests an export, THE REW_Generator SHALL produce a text file whose first line is exactly `Equaliser: Parametric EQ`.
2. THE REW_Generator SHALL write filter lines with 1-based, two-digit zero-padded numbering (e.g. `Filter  1:`, `Filter  2:`).
3. THE REW_Generator SHALL write gain and frequency values to 2 decimal places and Q values to 3 decimal places.
4. WHEN a band's Canonical `type` is `"OFF"`, THE REW_Generator SHALL write `OFF PK Fc <freq> Hz Gain <gain> dB Q <q>`, preserving the last known frequency, gain, and Q values (defaulting to 1000.00 Hz, 0.00 dB, 1.000 Q if none).
5. THE REW_Generator SHALL write all bands up to the device's `max_filters` count; no bands SHALL be omitted.
6. WHEN exporting a profile in L/R channel mode, THE REW_Generator SHALL produce two separate files — one for the left channel and one for the right channel — with filenames that clearly indicate the channel; THE REW_Generator SHALL NOT produce channel-specific separate files when the device is in Stereo mode.
7. THE generated file SHALL load into REW without error (verified during hardware QA).

---

### Requirement 8: REW HTTP API Integration

**User Story:** As a user, I want to pull filter data directly from a running REW instance over its local HTTP API, so that I do not need to manually export text files.

#### Acceptance Criteria

1. WHEN the user requests a list of REW measurements, THE REW_Adapter SHALL call `GET http://localhost:4735/measurements` and return the list of measurement summaries including title, UUID, date, and frequency range.
2. THE App SHALL require the user to explicitly select a measurement by UUID before any filter extraction proceeds; THE App SHALL NOT auto-select the latest or first measurement.
3. WHEN the user selects a measurement UUID, THE REW_Adapter SHALL call `GET http://localhost:4735/measurements/<uuid>/filters` and parse the returned `FilterSetting` objects into `CanonicalFilter` objects.
4. WHEN REW is not running or the API is not reachable, THE REW_Adapter SHALL handle the connection refused error gracefully, display a "REW not connected" status, and SHALL NOT crash the App.
5. WHEN a measurement UUID is not found, THE REW_Adapter SHALL handle the HTTP 404 response and display an appropriate error to the user.
6. THE REW_Adapter SHALL log all HTTP requests and responses to `rew_api.log`.
7. WHEN the REW API is unreachable, THE App SHALL still function normally for all non-REW-API operations.

---

### Requirement 9: Local Profile Library

**User Story:** As a user, I want to save, load, rename, delete, duplicate, and tag my EQ filter configurations locally, so that I can reuse and organise my filter presets.

#### Acceptance Criteria

1. THE Profile_Repository SHALL store profiles as JSON files in the OS-appropriate application data directory (`%APPDATA%\wiim-rew-sync\` on Windows, `~/.config/wiim-rew-sync/` on Linux/macOS).
2. WHEN saving a profile in Stereo channel mode, THE Profile_Repository SHALL write the profile with a `filters` key; `filters_l` and `filters_r` MUST NOT be present.
3. WHEN saving a profile in L/R channel mode, THE Profile_Repository SHALL write the profile with `filters_l` and `filters_r` keys; the `filters` key MUST NOT be present.
4. WHEN loading a profile, THE Profile_Repository SHALL validate that the filter key(s) match the `channel_mode` field; a mismatch SHALL be treated as an invalid profile and SHALL NOT be loaded silently.
5. THE Profile_Repository SHALL support `save`, `load`, `list`, `delete`, `rename`, `duplicate`, `add_tag`, `remove_tag`, and `get_by_tag` operations.
6. WHEN `list()` is called, THE Profile_Repository SHALL return all profiles sorted by name.
7. WHEN `load()` is called with a profile name that does not exist, THE Profile_Repository SHALL raise a `ProfileNotFoundError`.
8. WHEN a profile's `schema_version` is lower than the current version, THE Profile_Repository SHALL attempt automatic schema migration via the Translation_Engine before loading; if migration fails, THE App SHALL display a clear error and SHALL NOT load the profile.
9. WHEN `duplicate()` is called, THE Profile_Repository SHALL create a copy of the profile with a new name and the same filter data.
10. THE Profile_Repository SHALL persist tags across application restarts.
11. WHEN loading a Stereo profile onto a device in L/R mode (or vice versa), THE App SHALL display a mode mismatch warning and require explicit user confirmation before proceeding.

---

### Requirement 10: Backup Management

**User Story:** As a developer/power user, I want automatic backups of device state to be retained locally, so that I can manually recover if automated rollback fails.

#### Acceptance Criteria

1. THE Backup_Manager SHALL store backups in a `backups/` subdirectory, separate from user-facing profiles; backups SHALL NOT appear in the profile library UI.
2. WHEN a backup is created, THE Backup_Manager SHALL include: timestamp (ISO 8601, required — backup creation SHALL fail if a timestamp cannot be generated), device model, firmware version, UUID, MAC address, source name, channel mode, and all filter band data.
3. WHEN the channel mode is `"Stereo"`, THE Backup_Manager SHALL write the `filters` key; when `"L/R"`, it SHALL write `filters_l` and `filters_r`.
4. WHEN the 21st backup for a given device UUID is created, THE Backup_Manager SHALL delete the oldest backup for that device UUID; IF the deletion fails due to file system errors or permissions, THE Backup_Manager SHALL fail the entire backup operation and NOT proceed with creating the new backup.
5. THE Backup_Manager SHALL use `profile_type: "backup"` in the JSON and SHALL include a `trigger` field (`"pre_write"` or `"pre_rollback"`).
6. WHEN a rollback is initiated, THE Backup_Manager SHALL create a new `"pre_rollback"` backup of the current (post-failed-write) state before writing the original backup back to the device.

---

### Requirement 11: RoomFit Support (Experimental)

**User Story:** As a user with a RoomFit-capable WiiM device, I want to view and manage my RoomFit configuration in the same tool, so that I can incorporate room correction into my workflow.

#### Acceptance Criteria

1. WHEN `roomfit_level` is 0 (including WiiM Mini), THE App SHALL hide all RoomFit UI controls entirely.
2. WHEN `roomfit_level` is 1, THE App SHALL display a "RoomFit Active" indicator but SHALL disable all RoomFit read, export, and write controls.
3. WHEN `roomfit_level` is 2 or higher, THE App SHALL enable RoomFit read functionality and display the RoomFit filter data.
4. WHEN `roomfit_level` is 3 or higher, THE App SHALL enable RoomFit export to REW text format.
5. WHEN `roomfit_level` is 4, THE App SHALL enable RoomFit write functionality and allow the user to overwrite RoomFit slots.
6. WHEN a RoomFit capability probe command returns an unexpected response, THE Capability_Prober SHALL log the behaviour in `corrections.md`, set the capability to the last confirmed level, and SHALL NOT raise an exception.
7. THE App SHALL treat RoomFit read data as a Canonical filter set using the same band parameter format as PEQ.

---

### Requirement 12: Dry Run Mode

**User Story:** As a user, I want to preview what would be written to my device before committing any changes, so that I can verify the translation result without risk.

#### Acceptance Criteria

1. WHEN the user enables Dry Run mode and initiates an import-and-apply operation, THE App SHALL execute: Import → Translate → Validate → Preview filters in UI → Stop.
2. WHEN in Dry Run mode, THE App SHALL NOT dispatch any write commands to any device or invoke the `WiiM_Command_Queue`.
3. WHEN in Dry Run mode, THE App SHALL NOT create a `BackupRecord`.
4. WHEN in Dry Run mode, THE App SHALL display the translated filter set in the EQ filter table; IF out-of-range gain or Q values are detected, THE App SHALL display validation warnings alongside the preview, and the preview SHALL only be shown after warnings have been properly surfaced to the user.
5. THE App SHALL make Dry Run mode clearly distinguishable from live mode in the UI (e.g. a visible "DRY RUN" indicator).

---

### Requirement 13: Developer Diagnostics Panel

**User Story:** As a developer, I want a raw API access panel, so that I can debug device communication and inspect capability data without an external tool.

#### Acceptance Criteria

1. THE Diagnostics_Panel SHALL NOT be visible on normal application startup.
2. THE Diagnostics_Panel SHALL be accessible via an application menu item.
3. WHEN the user submits a raw command string, THE Diagnostics_Panel SHALL send `https://<selected_device_ip>/httpapi.asp?command=<input>` to the currently selected device only when explicitly submitted by the user (no automated sending or background polling); THE Diagnostics_Panel SHALL display the raw response on success, or an error message, connection status, or timeout indicator on failure.
4. THE Diagnostics_Panel SHALL display the full `DeviceCapabilities` object for the currently selected device as formatted JSON.
5. THE Diagnostics_Panel SHALL display a tail of the most recent entries from `wiim_api.log`.
6. THE Diagnostics_Panel SHALL be clearly labelled as a developer/diagnostic tool in its UI header.

---

### Requirement 14: Error Handling and Notifications

**User Story:** As a user, I want clear, actionable error messages for every failure mode, so that I know what went wrong and how to recover.

#### Acceptance Criteria

1. WHEN a device is offline or unreachable, THE App SHALL display a "Device offline" message and SHALL NOT crash.
2. WHEN a REW text file fails to parse, THE App SHALL display a clear error identifying the problem (e.g. line number, offending value) and SHALL NOT proceed with any device operation.
3. WHEN a write verification fails and rollback succeeds, THE App SHALL display a notification stating that the write failed and the original state has been restored.
4. WHEN a write verification fails and rollback also fails, THE App SHALL display a critical error message containing the backup file path and step-by-step manual recovery instructions.
5. WHEN a REW API call fails, THE App SHALL display an error specific to the failure (e.g. "REW not connected", "Measurement not found") without crashing.
6. WHEN a schema migration fails, THE App SHALL display a clear error and refuse to load the outdated profile.
7. WHEN a malformed JSON response is received from a WiiM device, THE App SHALL log the error to `wiim_api.log` and display a generic communication error to the user.
8. ALL errors SHALL also be written to `app.log` at the appropriate severity level (ERROR or CRITICAL).
9. WHEN the App starts with no network connection, THE App SHALL open normally, display the profile library, and show a "No devices found" state without crashing.

---

### Requirement 15: Logging

**User Story:** As a developer or power user, I want the application to maintain detailed logs of all operations, so that I can diagnose issues after the fact.

#### Acceptance Criteria

1. THE App SHALL maintain three rotating log files: `logs/app.log`, `logs/wiim_api.log`, and `logs/rew_api.log`.
2. EACH log file SHALL rotate when it exceeds 10 MB and SHALL retain a maximum of 5 backup archives.
3. EVERY log entry SHALL include a timestamp, log level, component name, and message.
4. THE `wiim_api.log` SHALL record all HTTP requests and responses to WiiM devices.
5. THE `rew_api.log` SHALL record all HTTP requests and responses to the REW local API.
6. THE `app.log` SHALL record application lifecycle events, UI events, errors, and all rollback events.
7. CRITICAL events (rollback failures, unexpected API responses) SHALL be logged at CRITICAL or ERROR level in `app.log`.
8. THE `logs/` directory SHALL be created automatically on first application run if it does not exist.

---

### Requirement 16: Translation Engine Integrity

**User Story:** As a developer, I want the Translation Engine to be fully unit-tested and stateless, so that data conversion is reliable and regressions are caught immediately.

#### Acceptance Criteria

1. THE Translation_Engine SHALL be stateless; it SHALL NOT maintain internal state between conversion calls.
2. THE Translation_Engine SHALL achieve greater than 90% unit test coverage as measured by `pytest --cov=src/translator`.
3. THE Translation_Engine SHALL clip gain values that exceed WiiM's ±12 dB limit and log a warning when clipping occurs.
4. THE Translation_Engine SHALL clip Q values that exceed WiiM's 0.01–24 range and log a warning when clipping occurs.
5. WHEN converting a REW text parse result to a WiiM payload, THE Translation_Engine SHALL produce a valid 40-entry parameter list (4 parameters × 10 bands).
6. THE Translation_Engine SHALL support round-trip conversion: parse a REW file → generate a REW file → parse again, producing identical `CanonicalFilter` lists.
7. THE Translation_Engine SHALL support round-trip conversion: convert Canonical filters to a WiiM payload → parse the payload back → produce Canonical filters matching the originals within the floating-point tolerances.

---

### Requirement 17: Multiroom Device Display

**User Story:** As a user with a WiiM multiroom group, I want to see each device's group role, so that I understand my network topology.

#### Acceptance Criteria

1. WHEN displaying discovered devices, THE App SHALL indicate each device's multiroom role (solo, master, slave) as an informational badge.
2. THE App SHALL allow PEQ and RoomFit read/write operations on any device regardless of its multiroom role (PEQ filters are per-device, not per-group).
3. THE Capability_Prober SHALL determine the device's multiroom `role` by calling `GetMultiroomInfo` for display purposes only.

---

### Requirement 18: GUI Responsiveness and Threading

**User Story:** As a user, I want the application UI to remain responsive during all network and file operations, so that I can interact with the interface while operations run in the background.

#### Acceptance Criteria

1. THE App SHALL run all network I/O (WiiM Adapter, REW Adapter, Discovery) on a dedicated background `asyncio` event loop thread.
2. THE App's main thread SHALL run the PySide6 Qt event loop exclusively; no blocking calls SHALL occur on the main thread.
3. ALL communication between the GUI and the async core SHALL use Qt signals/slots or thread-safe queues.
4. WHEN an async operation is in progress, THE App SHALL display a progress indicator (spinner or progress bar).
5. WHEN an in-progress operation supports cancellation, THE App SHALL provide a cancel control that stops the operation cleanly.
6. THE App SHALL remain interactive and accept user input while background operations are running.

---

### Requirement 19: Packaging and Distribution

**User Story:** As a non-technical user, I want to run the application without installing Python or any dependencies, so that setup is straightforward.

#### Acceptance Criteria

1. THE App SHALL be distributed as a single-file executable for Windows (`.exe`), macOS (`.app` bundle), and Linux (single binary) using PyInstaller.
2. WHEN launched for the first time, THE App SHALL automatically create the `logs/` directory and profile storage directory if they do not exist; IF either directory cannot be created, THE App SHALL NOT start and SHALL display an error explaining which directory could not be created.
3. THE packaged App SHALL include all required assets and logging configuration.
4. THE packaged App SHALL run without requiring a Python installation on the host system.
