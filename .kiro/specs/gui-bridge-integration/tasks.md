# Implementation Plan: GUI Bridge Integration

## Overview

This plan wires the MainWindow signal handlers (currently containing TODO placeholders) to actual backend adapter methods via AsyncBridge, making the GUI functional end-to-end. The work is split into: dependency initialization, primary wizard signal handlers, secondary workflow execution, picker dialogs, error mapping, and comprehensive testing.

All adapter calls flow through `AsyncBridge.run_async()` and results return via Qt signals. No new domain models or adapters are introduced — this is purely integration glue.

## Tasks

- [x] 1. Dependency initialization and error mapping
  - [x] 1.1 Add backend adapter instance attributes to MainWindow.__init__
    - Create `_discovery_module`, `_rew_client`, `_profile_repository`, `_backup_manager` at startup
    - Add `_wiim_http_client`, `_capability_prober`, `_wiim_adapter`, `_safe_write` as `None`-initialized attributes (created lazily on device selection)
    - Import DiscoveryModule, REWHttpApiClient, ProfileRepository, BackupManager, WiiMHttpClient, CapabilityProber, WiiMAdapter, SafeWrite
    - Use AppSettings for discovery_timeout and presets_directory configuration
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6_

  - [x] 1.2 Implement `_map_error` method and `_bridge_wrapper` coroutine pattern
    - Add `_map_error(self, exc: Exception) -> str` with the mapping table from design (WiiMTimeoutError, WiiMConnectionError, REWNotConnectedError, ParseError, ValidationError, FileNotFoundError, PermissionError, OSError)
    - Add generic fallback for unmapped exception types
    - Add `_bridge_wrapper` async helper that catches exceptions, logs traceback, and emits `operation_error`
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

  - [x] 1.3 Add concurrent operation guard to MainWindow
    - Check `self._feedback_manager.is_active` before every `run_async` call
    - If active, log a warning and return early (ignore the trigger)
    - _Requirements: 13.4_

  - [x] 1.4 Write property test for error mapping completeness (Property 5)
    - **Property 5: Error mapping completeness**
    - **Validates: Requirements 12.2**
    - Generate exception instances from known mapping set and verify correct message returned
    - Generate arbitrary Exception subclasses and verify generic fallback returned (never None, never raises)

  - [x] 1.5 Write property test for concurrent operation prevention (Property 6)
    - **Property 6: Concurrent operation prevention**
    - **Validates: Requirements 13.4**
    - Generate pairs of operation trigger signals while is_active is True
    - Verify no second `run_async` call is made

- [ ] 2. Primary wizard signal handlers — discovery and capability probe
  - [x] 2.1 Wire `_on_refresh_requested` to discovery via AsyncBridge
    - Replace TODO with `self._bridge.run_async(self._do_discovery())` where `_do_discovery` is an async method calling `self._discovery_module.discover()`
    - On success, emit `discovery_complete` with transformed device dicts (keys: "name", "ip", "model")
    - On error, emit `operation_error` with mapped message
    - Guard with concurrent operation check
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [x] 2.2 Wire `_on_device_selected` to capability probing via AsyncBridge
    - Create `WiiMHttpClient(device_ip)` and `CapabilityProber(client)` on selection
    - Store as `self._wiim_http_client` and `self._capability_prober`
    - Call `self._bridge.run_async(self._do_probe())` where `_do_probe` calls `self._capability_prober.probe()`
    - On success emit `capabilities_ready`; on error emit `operation_error`
    - Guard with concurrent operation check
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 2.3 Update `_on_capabilities_ready` to create WiiMAdapter and SafeWrite
    - After storing capabilities, create `WiiMAdapter(self._wiim_http_client)` and `SafeWrite(self._wiim_adapter, self._backup_manager)`
    - Store as `self._wiim_adapter` and `self._safe_write`
    - Handle empty source_names (show error, stay on ConnectPage)
    - _Requirements: 14.2, 14.3, 2.7_

  - [x] 2.4 Write property test for DeviceInfo transformation (Property 1)
    - **Property 1: DeviceInfo transformation preserves required keys**
    - **Validates: Requirements 1.2**
    - Generate lists of DeviceInfo with arbitrary name/ip/model strings
    - Assert every resulting dict has "name" and "ip" keys matching original fields

  - [x] 2.5 Write property test for flow type determination (Property 2)
    - **Property 2: Flow type determination from roomfit_level**
    - **Validates: Requirements 2.2, 2.3**
    - Generate DeviceCapabilities with roomfit_level 0-4
    - Assert roomfit_level < 2 → PEQ_ONLY; roomfit_level >= 2 → NOT PEQ_ONLY

- [ ] 3. Primary wizard signal handlers — filter loading
  - [x] 3.1 Wire `_on_file_import_requested` to TranslationEngine via AsyncBridge
    - Call `self._bridge.run_async(self._do_file_import(path))` where `_do_file_import` calls `TranslationEngine.parse_rew_file(path)`
    - On success: store filters in WizardController state, populate FiltersPage
    - On success with skipped bands: also show info message with skip count
    - On error (FileNotFoundError, ParseError, ValidationError): emit `operation_error`
    - Guard with concurrent operation check
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 3.2 Wire `_on_device_pull_requested` to WiiMAdapter via AsyncBridge
    - Check selected source exists in state; if not, show error and return
    - Call `self._bridge.run_async(self._do_device_pull())` where `_do_device_pull` calls `self._wiim_adapter.read_peq(source_name)`
    - On success: convert PEQSettings to CanonicalFilter via `TranslationEngine.parse_wiim_band_array()`, store in state, populate FiltersPage
    - On error: emit `operation_error`
    - Guard with concurrent operation check
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 3.3 Wire `_on_rew_api_pull_requested` to REWHttpApiClient via AsyncBridge
    - Call `self._bridge.run_async(self._do_rew_list_measurements())` to list measurements
    - On success with items: present MeasurementPickerDialog for user selection
    - On user selection: call `self._bridge.run_async(self._do_rew_get_filters(uuid))`
    - On filters retrieved: store in state, populate FiltersPage
    - On REWNotConnectedError: show info banner "REW is not connected"
    - On empty list: show info "No measurements found in REW"
    - On dialog cancel: no action
    - Guard with concurrent operation check
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [~] 3.4 Write unit tests for file import, device pull, and REW pull handlers
    - Test happy paths with mocked adapters returning valid data
    - Test error paths (file not found, parse error, timeout, REW not connected)
    - Test precondition failures (no source selected for device pull)
    - _Requirements: 3.1-3.6, 4.1-4.5, 5.1-5.7_

- [ ] 4. Primary wizard signal handlers — push and export
  - [~] 4.1 Wire push step to SafeWrite via AsyncBridge
    - When WizardController advances to PUSH step, call `self._bridge.run_async(self._do_push())`
    - `_do_push` calls `self._safe_write.execute(source_name, peq_settings)`
    - Emit progress_update for each Safe_Write_Protocol stage (backing up, writing, verifying)
    - On success: emit `write_complete` with WriteResult
    - On error: emit `operation_error`
    - Guard with concurrent operation check
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [~] 4.2 Wire `_on_export_requested` to TranslationEngine via AsyncBridge
    - Open QFileDialog for save path (default .txt extension)
    - If user cancels dialog: return with no action
    - Call `self._bridge.run_async(self._do_export(filters, path))`
    - `_do_export` calls `TranslationEngine.generate_rew_file(filters, path)`
    - On success with no warnings: show "File exported" success banner
    - On success with warnings: show success + skipped band count
    - On I/O error: emit `operation_error`
    - Guard with concurrent operation check
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [~] 4.3 Write unit tests for push and export handlers
    - Test push success, rollback success, critical rollback failure, progress updates
    - Test export happy path, warnings, dialog cancel, I/O error
    - Use mocked SafeWrite/TranslationEngine
    - _Requirements: 6.1-6.7, 7.1-7.6_

- [~] 5. Checkpoint — primary handlers complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Picker dialogs for secondary workflows
  - [x] 6.1 Create `SourcePickerDialog` in `src/gui/dialogs/source_picker.py`
    - Modal dialog with checkable source list (excludes current source)
    - Accept/Cancel buttons
    - Returns `list[str]` of selected sources or `None` on cancel
    - Static method `get_sources(parent, available_sources, exclude)` for convenience
    - _Requirements: 9.1, 9.2_

  - [x] 6.2 Create `DevicePickerDialog` in `src/gui/dialogs/device_picker.py`
    - Modal dialog with checkable device list (excludes current device)
    - Accept/Cancel buttons
    - Returns `list[DeviceInfo]` of selected devices or `None` on cancel
    - Static method `get_devices(parent, discovered_devices, exclude_ip)` for convenience
    - _Requirements: 10.1, 10.2, 15.1, 15.2_

  - [x] 6.3 Create `MeasurementPickerDialog` in `src/gui/dialogs/measurement_picker.py`
    - Modal dialog with single-select measurement list
    - Accept/Cancel buttons
    - Returns `MeasurementSummary` or `None` on cancel
    - Static method `get_measurement(parent, measurements)` for convenience
    - _Requirements: 5.2, 5.7_

  - [x] 6.4 Write unit tests for picker dialogs
    - Test dialog creation, selection, accept/cancel return values
    - Use qtbot fixtures
    - _Requirements: 9.1, 9.2, 10.1, 10.2, 5.2, 5.7_

- [ ] 7. SecondaryWorkflowManager async execution
  - [x] 7.1 Add `configure()` method to SecondaryWorkflowManager for adapter injection
    - Accept `bridge`, `wiim_adapter_factory`, `safe_write_factory`, `backup_manager` parameters
    - Store references for use in workflow methods
    - Call `configure()` from MainWindow after adapters are created (in `_on_capabilities_ready`)
    - _Requirements: 8.1, 9.3, 10.3, 15.3_

  - [~] 7.2 Implement async `copy_to_sources` via AsyncBridge
    - Replace placeholder with `bridge.run_async(self._do_copy_to_sources(filters, targets))`
    - For each source: execute SafeWrite independently, emit progress per source
    - On per-source failure: record failure, continue to next source (fault isolation)
    - Emit `copy_to_sources_complete` with full results list
    - _Requirements: 9.3, 9.4, 9.5, 9.6, 9.7_

  - [~] 7.3 Implement async `apply_to_devices` via AsyncBridge
    - Replace placeholder with `bridge.run_async(self._do_apply_to_devices(filters, request))`
    - For each device: connect → probe → SafeWrite; emit progress per device
    - On per-device failure: record failure, continue (fault isolation)
    - Emit `multi_device_complete` with full results list
    - _Requirements: 10.3, 10.4, 10.5, 10.6, 10.7_

  - [~] 7.4 Implement async `undo_last_push` via AsyncBridge
    - Read backup file from `backup_path` to get previous PEQ state
    - Execute SafeWrite with backup data (backup current → write → verify)
    - On success: emit `undo_complete(True, "Previous filters restored")`
    - On failure: emit `undo_complete(False, error_message)`
    - On missing backup file: emit `undo_complete(False, "No backup available")`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [~] 7.5 Implement async `copy_preset_to_device` via AsyncBridge
    - Connect to target device, probe capabilities, execute SafeWrite
    - On success: emit `copy_to_device_complete(True, message)`
    - On failure: emit `copy_to_device_complete(False, error_message)`
    - _Requirements: 15.3, 15.4, 15.5, 15.6_

  - [~] 7.6 Write property test for copy-to-sources fault isolation (Property 3)
    - **Property 3: Copy-to-sources fault isolation**
    - **Validates: Requirements 9.3, 9.6, 9.7**
    - Generate non-empty source lists + failure bitmaps
    - Assert: every source attempted, exactly one SourceCopyResult per source, success field accurate

  - [~] 7.7 Write property test for multi-device push fault isolation (Property 4)
    - **Property 4: Multi-device push fault isolation**
    - **Validates: Requirements 10.3, 10.6, 10.7**
    - Generate non-empty device lists + failure bitmaps
    - Assert: every device attempted, exactly one DevicePushResult per device, success field accurate

- [ ] 8. Wire picker dialogs into MainWindow handlers
  - [~] 8.1 Wire `_on_copy_to_source_requested` with SourcePickerDialog
    - Replace TODO: open SourcePickerDialog with available sources (exclude current)
    - On cancel: return with no action
    - On confirm: call `self._secondary_workflows.copy_to_sources(filters, targets)`
    - _Requirements: 9.1, 9.2_

  - [~] 8.2 Wire `_on_multi_device_requested` with DevicePickerDialog
    - Replace TODO: open DevicePickerDialog with discovered devices (exclude current)
    - On cancel: return with no action
    - On confirm: build MultiDeviceRequest and call `self._secondary_workflows.apply_to_devices(filters, request)`
    - _Requirements: 10.1, 10.2_

  - [~] 8.3 Wire `_on_copy_to_device_requested` with DevicePickerDialog
    - Replace TODO: open DevicePickerDialog for single target device selection
    - On cancel: return with no action
    - On confirm: call `self._secondary_workflows.copy_preset_to_device(preset_filters, target_ip, source)`
    - _Requirements: 15.1, 15.2_

  - [~] 8.4 Wire `_on_rew_api_pull_requested` result handler with MeasurementPickerDialog
    - After measurements are listed, open MeasurementPickerDialog
    - On cancel: no action
    - On selection: trigger `_do_rew_get_filters(uuid)` via bridge
    - _Requirements: 5.2, 5.7_

- [~] 9. Checkpoint — all integration wiring complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Operation feedback timeout integration
  - [~] 10.1 Add 30-second hard timeout to OperationFeedbackManager
    - Add a QTimer(`_timeout_timer`) with 30-second interval started on `start_operation()`
    - On timeout: show error "Operation timed out" in StatusBanner, re-enable buttons, set `is_active = False`
    - Stop timeout timer on `finish_operation()`
    - _Requirements: 13.5_

  - [~] 10.2 Write unit tests for operation feedback timeout
    - Test timeout fires after 30s (use QTimer simulation via qtbot.waitSignal)
    - Test timeout does not fire if operation finishes before 30s
    - Test buttons re-enabled on timeout
    - _Requirements: 13.1, 13.2, 13.3, 13.5_

- [ ] 11. Integration tests
  - [~] 11.1 Write integration test for discovery → device selection → probe → push flow
    - End-to-end signal chain with mocked adapters
    - Verify wizard state transitions
    - Verify page population at each step
    - _Requirements: 1.1-1.7, 2.1-2.7, 6.1-6.7_

  - [~] 11.2 Write integration test for SecondaryWorkflowManager with mocked adapters
    - Test copy-to-sources with mixed success/failure results
    - Test multi-device push with connection failures
    - Test undo with missing backup file
    - _Requirements: 8.1-8.6, 9.3-9.7, 10.3-10.7_

  - [~] 11.3 Write integration test for profile recall flow
    - Test profile with filters → navigates to Review
    - Test empty profile → error shown
    - Test corrupted profile → error shown
    - _Requirements: 11.1-11.5_

- [~] 12. Final checkpoint — full test suite passes
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks including tests are mandatory per project policy
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All tests use pytest-qt (qtbot) for signal/slot testing and AsyncMock for adapter mocking
- The existing MainWindow already has bridge signal connections wired (`_wire_signals`); these tasks fill in the handler bodies
- SecondaryWorkflowManager already has the signal infrastructure; these tasks add real async execution

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "1.5"] },
    { "id": 2, "tasks": ["2.1", "2.2", "6.1", "6.2", "6.3"] },
    { "id": 3, "tasks": ["2.3", "2.4", "2.5", "6.4"] },
    { "id": 4, "tasks": ["3.1", "3.2", "3.3", "7.1"] },
    { "id": 5, "tasks": ["3.4", "4.1", "4.2", "7.2", "7.3", "7.4", "7.5"] },
    { "id": 6, "tasks": ["4.3", "7.6", "7.7", "8.1", "8.2", "8.3", "8.4"] },
    { "id": 7, "tasks": ["10.1"] },
    { "id": 8, "tasks": ["10.2", "11.1", "11.2", "11.3"] }
  ]
}
```
