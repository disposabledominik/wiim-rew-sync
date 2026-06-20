# Requirements Document

## Introduction

This feature wires the MainWindow signal handlers (currently containing TODO placeholders) to actual backend adapter methods via AsyncBridge, making the GUI functional end-to-end. The GUI redesign is complete — all widgets, pages, views, and dialogs are built and tested — but no real backend calls happen yet. This spec fills the integration gaps between the GUI layer and the existing backend adapters (WiiMAdapter, CapabilityProber, REWHttpApiClient, SafeWrite, DiscoveryModule, TranslationEngine, ProfileRepository).

## Glossary

- **AsyncBridge**: Thread-safe bridge between the Qt main thread and an asyncio worker thread; exposes `run_async(coroutine)` which schedules coroutines on a background event loop and emits Qt signals on completion.
- **MainWindow**: The application shell (`src/gui/main_window.py`) that owns all pages, the WizardController, and the AsyncBridge instance.
- **WizardController**: State machine managing wizard step sequencing and branching logic.
- **DiscoveryModule**: Backend module that discovers WiiM devices on the local network via mDNS and subnet scan fallback.
- **CapabilityProber**: Backend adapter that queries a WiiM device for its capabilities (PEQ band count, RoomFit level, source list, etc.).
- **WiiMAdapter**: Backend adapter for reading and writing PEQ/RoomFit settings on a WiiM device.
- **SafeWrite**: Five-step protocol (backup, write, read-back, verify, commit/rollback) for all device writes.
- **REWHttpApiClient**: Backend adapter for the REW localhost HTTP API (list measurements, get filters).
- **TranslationEngine**: Stateless facade providing parse/generate methods for REW files and WiiM band arrays.
- **ProfileRepository**: Local JSON storage for user preset profiles.
- **REWGenerator**: Component within TranslationEngine that generates REW-compatible EQ text files from CanonicalFilter lists.
- **StatusBanner**: Contextual message area at the bottom of the content area showing info, success, error, and progress messages.
- **OperationFeedbackManager**: Component that disables buttons and shows loading state during async operations.
- **SecondaryWorkflowManager**: Orchestrator for multi-source copy, multi-device push, profile recall, and undo operations.
- **BackupManager**: Repository component that creates and retrieves PEQ state backups for the SafeWrite protocol.
- **Safe_Write_Protocol**: The mandatory five-step sequence: backup current state, write new settings, read-back, verify, commit or rollback.

## Requirements

### Requirement 1: Device Discovery Integration

**User Story:** As a user, I want the Connect page to discover WiiM devices on my network when I open the app or press refresh, so that I can select a device to work with.

#### Acceptance Criteria

1. WHEN the ConnectPage emits refresh_requested, THE MainWindow SHALL call `self._bridge.run_async(discovery_module.discover())` to trigger network discovery on the background thread.
2. WHEN the AsyncBridge emits discovery_complete with a non-empty device list, THE MainWindow SHALL transform each DeviceInfo into a dict containing at minimum the keys "name" and "ip", and pass the resulting list to ConnectPage via `set_devices()`.
3. WHEN the AsyncBridge emits discovery_complete with an empty list, THE MainWindow SHALL call `set_devices([])` on the ConnectPage and display "No devices found" in the StatusBanner as an informational message.
4. IF a network error occurs during discovery, THEN THE AsyncBridge SHALL emit operation_error and THE MainWindow SHALL display the error in the StatusBanner using the error mapping defined in Requirement 12.
5. WHILE discovery is in progress, THE OperationFeedbackManager SHALL disable the Refresh and device-card buttons on the ConnectPage and THE ConnectPage SHALL display its scanning indicator via `set_scanning_active(True)`.
6. WHEN the ConnectPage becomes visible (showEvent fires), THE ConnectPage SHALL emit refresh_requested, which triggers the discovery flow defined in criterion 1.
7. WHEN the AsyncBridge emits operation_finished after a discovery operation, THE ConnectPage SHALL hide its scanning indicator via `set_scanning_active(False)`.

### Requirement 2: Capability Probing Integration

**User Story:** As a user, I want the app to automatically detect what my device supports after I select it, so that the wizard adapts to my device's capabilities.

#### Acceptance Criteria

1. WHEN the ConnectPage emits device_selected with a device IP, THE MainWindow SHALL store the device IP in WizardController state, create a WiiMHttpClient and CapabilityProber for that IP, and call `self._bridge.run_async(capability_prober.probe())` to query device capabilities on the background thread.
2. WHEN the AsyncBridge emits capabilities_ready with a DeviceCapabilities object, THE MainWindow SHALL store the DeviceCapabilities in WizardController state and determine the wizard flow type: if roomfit_level is less than 2 set flow type to PEQ_ONLY, otherwise set flow type to FULL.
3. WHEN capabilities_ready indicates roomfit_level less than 2, THE WizardController SHALL set flow type to PEQ_ONLY and skip the EQ_TYPE step, advancing directly from SOURCE to the next applicable step.
4. WHEN capabilities_ready includes a non-empty source_names list, THE MainWindow SHALL populate the SourcePage by calling `set_sources(source_names, active_source)` where active_source is the device's currently active input as reported by getStatusEx.
5. IF the capability probe fails due to a connection timeout (device not responding within 5 seconds) or network error (connection refused or unreachable), THEN THE MainWindow SHALL display an error message indicating the device could not be reached in the StatusBanner using the error style and remain on the ConnectPage without advancing the wizard.
6. WHILE capability probing is in progress, THE OperationFeedbackManager SHALL disable interactive buttons on the ConnectPage and show a loading indicator.
7. IF capabilities_ready indicates source_names is empty, THEN THE MainWindow SHALL display an error message indicating no audio sources were detected in the StatusBanner and remain on the ConnectPage.

### Requirement 3: REW File Import Integration

**User Story:** As a user, I want to import a REW EQ text file so that I can load filter settings from my room measurements.

#### Acceptance Criteria

1. WHEN the FiltersPage emits file_import_requested with a file path, THE MainWindow SHALL call `TranslationEngine.parse_rew_file(path)` to parse the file into CanonicalFilter objects.
2. WHEN parsing completes successfully with no skipped filters, THE MainWindow SHALL store the resulting filters in WizardController state and populate the FiltersPage with the parsed filters.
3. IF the file path does not exist or is unreadable, THEN THE MainWindow SHALL display an error message indicating the file could not be found or accessed in the StatusBanner without crashing.
4. IF the file content is malformed or contains out-of-range values, THEN THE MainWindow SHALL display an error message indicating the file could not be parsed, including the line number from the ParseError or ValidationError, in the StatusBanner without crashing.
5. WHEN the FiltersPage emits file_import_requested, THE MainWindow SHALL execute file parsing on the AsyncBridge background thread without blocking the GUI thread.
6. WHEN parsing completes with skipped filters due to unsupported filter types, THE MainWindow SHALL store the successfully parsed filters in WizardController state, populate the FiltersPage, and display an informational message in the StatusBanner indicating the number of skipped bands.

### Requirement 4: Device PEQ Pull Integration

**User Story:** As a user, I want to pull the current PEQ settings from my WiiM device so that I can review or export them.

#### Acceptance Criteria

1. WHEN the FiltersPage emits device_pull_requested, THE MainWindow SHALL call `self._bridge.run_async(wiim_adapter.read_peq(source_name))` using the currently selected source from WizardController state.
2. WHEN the AsyncBridge emits peq_ready with PEQSettings, THE MainWindow SHALL convert the PEQSettings bands to CanonicalFilter objects using `TranslationEngine.parse_wiim_band_array()`, store them in WizardController state, and populate the FiltersPage.
3. WHILE the device pull is in progress, THE OperationFeedbackManager SHALL show a progress indicator with the message "Reading from device...".
4. IF the device read fails due to connection timeout or network error, THEN THE MainWindow SHALL display a non-technical error message in the StatusBanner and leave the FiltersPage filters and selections in their prior state.
5. IF device_pull_requested is emitted and no source is selected in WizardController state, THEN THE MainWindow SHALL display an error message indicating that a source must be selected first and take no further action.

### Requirement 5: REW API Pull Integration

**User Story:** As a user, I want to pull filters directly from REW's running API so that I can transfer measurements without exporting files manually.

#### Acceptance Criteria

1. WHEN the FiltersPage emits rew_api_pull_requested, THE MainWindow SHALL call `self._bridge.run_async(rew_client.list_measurements())` to retrieve available measurements.
2. WHEN measurements are retrieved successfully and the list contains one or more items, THE MainWindow SHALL present the measurement list in a selection dialog for explicit user selection.
3. WHEN the user selects a measurement from the dialog, THE MainWindow SHALL call `self._bridge.run_async(rew_client.get_filters(uuid))` using the selected measurement's UUID.
4. WHEN filters are retrieved successfully, THE MainWindow SHALL store the resulting CanonicalFilter list in WizardController state and populate the FiltersPage.
5. IF REW is not running or the API is unreachable (REWNotConnectedError), THEN THE MainWindow SHALL display "REW is not connected" in the StatusBanner as a non-fatal informational message and leave all other workflow options (file import, device pull) available.
6. IF the measurement list is retrieved successfully but contains zero items, THEN THE MainWindow SHALL display "No measurements found in REW" in the StatusBanner as an informational message.
7. IF the user dismisses the measurement selection dialog without selecting, THEN THE MainWindow SHALL take no further action and remain on the FiltersPage.

### Requirement 6: Device Push Integration (SafeWrite)

**User Story:** As a user, I want to push my reviewed filters to the WiiM device with automatic backup and verification, so that I can safely apply room corrections.

#### Acceptance Criteria

1. WHEN the WizardController advances to the PUSH step, THE MainWindow SHALL call `self._bridge.run_async(safe_write.execute(source_name, peq_settings))` to execute the Safe_Write_Protocol.
2. THE Safe_Write_Protocol execution SHALL follow all five steps: backup current state, write new settings, read-back, verify, commit or rollback.
3. WHEN the AsyncBridge emits write_complete with a successful WriteResult, THE MainWindow SHALL display the PushPage in success state with the backup path stored in WizardController state.
4. WHEN the AsyncBridge emits write_complete with a failed WriteResult where rollback_success is True, THE MainWindow SHALL display the PushPage in failure state with the message "Write verification failed; original state restored."
5. WHEN the AsyncBridge emits write_complete with a failed WriteResult where rollback_success is False, THE MainWindow SHALL display the PushPage in critical failure state with recovery instructions including the backup file path.
6. WHILE the push operation is in progress, THE MainWindow SHALL show progress stage updates on the PushPage reflecting the current Safe_Write_Protocol step (backing up, writing, verifying).
7. WHILE the push operation is in progress, THE OperationFeedbackManager SHALL disable all navigation and action buttons.

### Requirement 7: REW File Export Integration

**User Story:** As a user, I want to export my current filters as a REW-compatible text file so that I can share or reimport them in REW.

#### Acceptance Criteria

1. WHEN the ReviewPage emits export_rew_requested, THE MainWindow SHALL open a file save dialog defaulting to `.txt` extension and then call `TranslationEngine.generate_rew_file(filters, path)` with the user-chosen path.
2. WHEN the export completes successfully with zero validation warnings, THE MainWindow SHALL display "File exported" in the StatusBanner as a success message.
3. IF the export produces one or more validation warnings (skipped UNKNOWN-type bands), THEN THE MainWindow SHALL display a success message in the StatusBanner that includes the count of skipped bands.
4. IF the user cancels the file save dialog, THEN THE MainWindow SHALL take no further action and remain on the ReviewPage.
5. THE MainWindow SHALL execute file generation on the AsyncBridge background thread without blocking the GUI thread.
6. IF a file I/O error occurs during generation (permission denied, disk full), THEN THE MainWindow SHALL display an error message in the StatusBanner indicating the file could not be written.

### Requirement 8: Undo Last Push Integration

**User Story:** As a user, I want to undo my last push and restore the device to its previous state, so that I can recover from an unwanted change.

#### Acceptance Criteria

1. WHEN the PushPage emits undo_requested, THE SecondaryWorkflowManager SHALL read the backup file at the stored backup_path from WizardController state to retrieve the previous PEQ state.
2. WHEN the backup file is read successfully, THE SecondaryWorkflowManager SHALL execute undo via the Safe_Write_Protocol: backup current state, write backup data, read-back, verify, commit or rollback.
3. WHEN undo completes successfully, THE SecondaryWorkflowManager SHALL emit undo_complete(True, "Previous filters restored") and THE MainWindow SHALL display the message in the StatusBanner.
4. IF undo fails (WriteResult with success=False), THEN THE SecondaryWorkflowManager SHALL emit undo_complete(False, error_message) and THE MainWindow SHALL display the error in the StatusBanner.
5. IF the backup file at backup_path does not exist or cannot be read, THEN THE SecondaryWorkflowManager SHALL emit undo_complete(False, message) indicating the backup is unavailable and THE MainWindow SHALL display the error in the StatusBanner without attempting the write.
6. WHILE undo is in progress, THE OperationFeedbackManager SHALL disable all action buttons and show a progress indicator.

### Requirement 9: Copy to Another Source Integration

**User Story:** As a user, I want to copy my current filters to additional audio sources on the same device, so that I can apply the same EQ across multiple inputs.

#### Acceptance Criteria

1. WHEN the ReviewPage emits copy_to_source_requested, THE MainWindow SHALL present a source picker dialog showing all available sources except the currently selected one.
2. IF the user cancels the source picker dialog, THEN THE MainWindow SHALL take no further action and remain on the ReviewPage.
3. WHEN the user confirms target sources, THE SecondaryWorkflowManager SHALL execute the Safe_Write_Protocol independently for each selected target source in sequence.
4. WHILE writing to each source, THE SecondaryWorkflowManager SHALL emit copy_to_sources_progress with the target source name and its current write stage (backing up, writing, verifying).
5. WHILE a copy-to-sources operation is in progress, THE OperationFeedbackManager SHALL disable all interactive buttons and show a loading indicator.
6. WHEN all source writes complete, THE SecondaryWorkflowManager SHALL emit copy_to_sources_complete with a list of per-source results indicating success or failure with an error description for each failed source.
7. IF a write fails for one source, THEN THE SecondaryWorkflowManager SHALL continue processing remaining sources and include the failure reason in the final per-source results.

### Requirement 10: Multi-Device Push Integration

**User Story:** As a user, I want to push my filters to multiple WiiM devices on my network, so that I can apply consistent EQ across my whole system.

#### Acceptance Criteria

1. WHEN the ReviewPage emits multi_device_requested, THE MainWindow SHALL present a device picker dialog showing all discovered devices except the currently connected device.
2. IF the user cancels the device picker dialog, THEN THE MainWindow SHALL take no further action and remain on the ReviewPage.
3. WHEN the user selects target devices and sources, THE SecondaryWorkflowManager SHALL execute the push sequence for each device sequentially: connect, probe capabilities, execute Safe_Write_Protocol.
4. WHILE pushing to each device, THE SecondaryWorkflowManager SHALL emit multi_device_progress with the target device name and its current stage (connecting, probing, writing, verifying).
5. WHILE a multi-device push operation is in progress, THE OperationFeedbackManager SHALL disable all interactive buttons and show a loading indicator.
6. WHEN all device pushes complete, THE SecondaryWorkflowManager SHALL emit multi_device_complete with a list of per-device results indicating success or failure with an error description for each failed device.
7. IF a push fails for one device, THEN THE SecondaryWorkflowManager SHALL continue processing remaining devices and include the failure reason in the final per-device results.

### Requirement 11: Profile Recall Integration

**User Story:** As a user, I want to load a previously saved preset from My Presets and push it to my device, so that I can quickly recall a known-good EQ configuration.

#### Acceptance Criteria

1. WHEN the MyPresetsView emits load_requested with a Profile object, THE SecondaryWorkflowManager SHALL extract the CanonicalFilter list from the profile.
2. WHEN filters are extracted successfully, THE SecondaryWorkflowManager SHALL emit profile_recalled with the filter list.
3. WHEN profile_recalled is received, THE MainWindow SHALL store the filters in WizardController state, populate the ReviewPage, and navigate to the Review step.
4. IF the profile contains no filters, THEN THE MainWindow SHALL display "Profile contains no filters" in the StatusBanner and remain on the current view.
5. IF the profile data is corrupted or cannot be deserialized, THEN THE MainWindow SHALL display an error message indicating the profile could not be read in the StatusBanner and remain on the current view.

### Requirement 12: Error Presentation

**User Story:** As a user, I want all errors displayed in plain language so that I understand what went wrong without needing technical knowledge.

#### Acceptance Criteria

1. WHEN the AsyncBridge emits operation_error, THE MainWindow SHALL display the human_readable_message parameter in the StatusBanner using the error style.
2. THE MainWindow SHALL map technical exception types to user-friendly messages: connection timeout to "Device not responding", REWNotConnectedError to "REW is not connected", file parse errors to "Could not read file".
3. THE MainWindow SHALL persist error messages in the StatusBanner until the user dismisses them via the banner's close control or a new operation completes successfully.
4. THE MainWindow SHALL log the full technical error details (including traceback) to the app log file without displaying them to the user.

### Requirement 13: Operation Feedback During Async Calls

**User Story:** As a user, I want visual feedback when the app is working in the background, so that I know the app is not frozen.

#### Acceptance Criteria

1. WHEN the AsyncBridge emits operation_started, THE OperationFeedbackManager SHALL disable all interactive buttons within the current page and show a loading indicator.
2. WHEN the AsyncBridge emits operation_finished, THE OperationFeedbackManager SHALL re-enable all interactive buttons and hide the loading indicator.
3. WHILE an operation has been running for more than 3 seconds, THE OperationFeedbackManager SHALL display a "This is taking longer than expected" message.
4. THE MainWindow SHALL prevent duplicate concurrent operations by ignoring user actions while an operation is already in progress.
5. IF neither operation_finished nor operation_error is received within 30 seconds of operation_started, THEN THE OperationFeedbackManager SHALL display a timeout error message in the StatusBanner and re-enable interactive buttons.

### Requirement 14: Dependency Initialization

**User Story:** As a developer, I want the MainWindow to create and configure all backend adapter instances at startup, so that they are available for bridge calls.

#### Acceptance Criteria

1. WHEN the MainWindow initializes, THE MainWindow SHALL create a DiscoveryModule instance with the configured discovery timeout from AppSettings.
2. WHEN a device is selected and capabilities are probed, THE MainWindow SHALL create a WiiMAdapter instance configured with the device IP and a WiiMHttpClient.
3. WHEN a WiiMAdapter is created, THE MainWindow SHALL create a SafeWrite instance using the adapter and a BackupManager.
4. THE MainWindow SHALL create a REWHttpApiClient instance at startup (connection failures are handled lazily on first use).
5. THE MainWindow SHALL create a ProfileRepository instance at startup using the configured presets directory from AppSettings.
6. THE MainWindow SHALL store all adapter instances as instance attributes accessible to signal handlers.

### Requirement 15: Copy Preset to Another Device Integration

**User Story:** As a user, I want to copy a device preset to a different WiiM device on my network, so that I can share EQ settings between rooms.

#### Acceptance Criteria

1. WHEN the PresetsDeviceView emits copy_to_device_requested with preset items, THE MainWindow SHALL present a device picker dialog showing all discovered devices except the currently connected device.
2. IF the user cancels the device picker dialog, THEN THE MainWindow SHALL take no further action and remain on the current view.
3. WHEN the user selects a target device, THE SecondaryWorkflowManager SHALL connect to the target device, probe its capabilities, and execute the Safe_Write_Protocol to write the preset filters.
4. WHILE a copy-to-device operation is in progress, THE OperationFeedbackManager SHALL disable all interactive buttons and show a loading indicator.
5. WHEN the copy completes successfully, THE SecondaryWorkflowManager SHALL emit copy_to_device_complete(True, message) and THE MainWindow SHALL display a success message in the StatusBanner.
6. IF the copy fails, THEN THE SecondaryWorkflowManager SHALL emit copy_to_device_complete(False, error_message) and THE MainWindow SHALL display the error in the StatusBanner.
