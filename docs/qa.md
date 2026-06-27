# QA Scenarios (Given-When-Then)

## Core Translation & Validation

1. **Given** a valid REW text file, **When** imported, **Then** filters are accurately converted to Canonical form without data loss.
2. **Given** a REW text file with frequencies > 22000 Hz, **When** imported, **Then** a validation error is thrown before device interaction.
3. **Given** a WiiM device offline, **When** discovery runs, **Then** it gracefully times out and does not crash the app.

## Safe Write Protocol

4. **Given** a push operation is requested, **When** initiated, **Then** a JSON backup of the current state is saved locally per source.
5. **Given** a push operation, **When** read-back verification fails due to floating point variance > 0.05dB, **Then** rollback is triggered.
6. **Given** a successful push operation, **When** verification passes, **Then** the user receives a success notification and no rollback occurs.
7. **Given** a rollback is triggered, **When** completed, **Then** the device's PEQ is exactly as it was before the push.

## Device Capabilities

8. **Given** a WiiM Mini on the network, **When** capability detection runs, **Then** `supports_peq=True`, `supports_lr_filters=True`, `supports_roomfit=False`, and EQ Type step is skipped (auto-PEQ).
9. **Given** a WiiM device with batch-write firmware, **When** a push is executed, **Then** the Command Queue bypasses sequential writes for a single payload.
10. **Given** the user enables Dry Run, **When** they click "Preview Only", **Then** translation and validation occur, Push page shows results, but no network writes are dispatched and no Undo button is shown.

## Error Handling & Edge Cases

11. **Given** a device rebooting during write sequence, **When** the network connection drops, **Then** the Command Queue catches the timeout and attempts a safe abort.
12. **Given** a user exporting to REW, **When** the file is generated, **Then** the format matches `Equaliser: Parametric EQ` specification exactly.
13. **Given** the app is left open for 24 hours, **When** log files exceed 10MB, **Then** the files rotate and keep a maximum of 5 archives.
14. **Given** a profile is loaded from the Local Library, **When** the schema version is outdated, **Then** the translation engine migrates it to the current schema.
15. **Given** independent L/R channel mode, **When** filters are pulled, **Then** both Left and Right Canonical models are populated and displayed in separate tabs.
16. **Given** an invalid HTTP response (e.g. malformed JSON), **When** parsing fails, **Then** the error is logged and a generic communication error is shown.
17. **Given** a rollback fails due to a network drop, **When** the app recovers, **Then** an explicit critical error logs the failure and instructs the user on manual recovery with backup file path.

## REW API & RoomFit

18. **Given** the REW API is enabled locally, **When** queried, **Then** the user is presented with a measurement picker dialog and must explicitly select a measurement ID.
19. **Given** RoomFit capabilities on a non-Mini device, **When** the app connects, **Then** the user is offered a choice between PEQ and RoomFit EQ types.
20. **Given** RoomFit is selected, **When** the user pushes, **Then** a profile name must be provided before write; overwriting an active profile shows a warning.

## Multi-Device & Multi-Source

21. **Given** multiple WiiM devices in a multiroom group, **When** a push is executed on a slave device, **Then** the write targets that specific device (PEQ is per-device, not per-group).
22. **Given** two devices with identical friendly names, **When** discovered, **Then** they are distinctly identified by IP address in the UI device cards.
23. **Given** multiple sources selected on the Source page, **When** push is executed, **Then** the same filters are written to all selected sources with per-source backup.
24. **Given** a multi-source push, **When** Undo is clicked, **Then** all affected sources are restored from their individual backups.
25. **Given** a Presets on Device item, **When** "Copy to another device" is used with multiple target devices selected, **Then** the preset is pushed to all selected devices (not just the first).

## Filter Translation & Edge Cases

26. **Given** a push operation with a 0Hz / OFF filter, **When** translated, **Then** the WiiM API correctly disables that specific band.
27. **Given** a REW text file containing more than the device's max filter count, **When** imported, **Then** a validation warning is shown and only the supported number of enabled bands are used; the user is informed of the truncation.
28. **Given** L/R filters loaded on Review, **When** Export is clicked, **Then** an export dialog generates two separate .txt files (Left and Right).

## Presets & Profile Management

29. **Given** a preset saved from device via "Save to My Presets," **When** loaded from the local library, **Then** the channel mode (Stereo or L/R) is preserved and filters display correctly.
30. **Given** a profile with L/R channel mode, **When** loaded from My Saved Presets, **Then** the wizard state channel_mode is set correctly and Review shows L/R tabs.

## Developer & Diagnostic

31. **Given** a developer needs to debug, **When** Diagnostics Panel is opened, **Then** raw HTTP commands can be sent and capability JSON dumps are visible.
32. **Given** no local network connection, **When** the app boots, **Then** the app opens normally, shows "no devices found," and allows access to My Saved Presets.
33. **Given** a WiiM Mini is selected, **When** the EQ panel loads, **Then** the EQ Type step is skipped and the app proceeds directly with PEQ.
34. **Given** a WiiM Amp Pro, WiiM Amp Ultra, WiiM Sound, or WiiM Sound Lite is discovered, **When** capability detection runs, **Then** `supports_peq=True`, `supports_lr_filters=True`, and `supports_roomfit=True`.
35. **Given** Dry Run is enabled, **When** the user clicks "Preview Only," **Then** translation and validation occur, the Push page shows results, but no network write commands are dispatched and no Undo button is shown.