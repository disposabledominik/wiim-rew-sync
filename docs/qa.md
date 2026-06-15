# QA Scenarios (Given-When-Then)

1. **Given** a valid REW text file, **When** imported, **Then** filters are accurately converted to Canonical form without data loss.
2. **Given** a REW text file with frequencies > 22000 Hz, **When** imported, **Then** a validation error is thrown before device interaction.
3. **Given** a WiiM device offline, **When** discovery runs, **Then** it gracefully times out and does not crash the app.
4. **Given** a push operation is requested, **When** initiated, **Then** a JSON backup of the current state is saved locally.
5. **Given** a push operation, **When** read-back verification fails due to floating point variance > 0.05dB, **Then** rollback is triggered.
6. **Given** a successful push operation, **When** verification passes, **Then** the user receives a success notification and no rollback occurs.
7. **Given** a rollback is triggered, **When** completed, **Then** the device's PEQ is exactly as it was before the push.
8. **Given** a WiiM Mini on the network, **When** capability detection runs, **Then** `supports_peq=True`, `supports_channel_peq=True`, `supports_roomfit=False`, and all RoomFit controls are hidden in the UI.
9. **Given** a WiiM device with batch-write firmware, **When** a push is executed, **Then** the Command Queue bypasses sequential writes for a single payload.
10. **Given** the user selects "Dry Run", **When** they apply an imported file, **Then** translation and validation occur, but no network write commands are dispatched.
11. **Given** a device rebooting during a write sequence, **When** the network connection drops, **Then** the Command Queue catches the timeout and attempts a safe abort.
12. **Given** a user exporting to REW, **When** the file is generated, **Then** the format matches `Equaliser: Parametric EQ` specification exactly.
13. **Given** the app is left open for 24 hours, **When** log files exceed 10MB, **Then** the files rotate and keep a maximum of 5 archives.
14. **Given** a profile is loaded from the Local Library, **When** the schema version is outdated, **Then** the translation engine migrates it to the current schema.
15. **Given** independent L/R channel mode, **When** filters are pulled, **Then** both Left and Right Canonical models are populated and displayed.
16. **Given** an invalid HTTP response (e.g. malformed JSON), **When** parsing fails, **Then** the error is logged and a generic communication error is shown.
17. **Given** the REW API is enabled locally, **When** queried, **Then** the user is forced to select a specific measurement ID rather than defaulting.
18. **Given** RoomFit capabilities are Level 1, **When** the app connects, **Then** the UI shows "RoomFit Active" but disables export/write buttons.
19. **Given** RoomFit capabilities are Level 4, **When** the app connects, **Then** the user can read, export, and overwrite the RoomFit slots.
20. **Given** multiple WiiM devices in a multiroom group, **When** a push is executed on a slave device, **Then** the write targets that specific device (PEQ is per-device, not per-group).
21. **Given** two devices with identical friendly names, **When** discovered, **Then** they are distinctly identified by IP/MAC address in the UI.
22. **Given** a push operation with a 0Hz / OFF filter, **When** translated, **Then** the WiiM API correctly disables that specific band.
23. **Given** a developer needs to debug, **When** Diagnostics Mode is opened, **Then** raw HTTP requests and capability JSON dumps are visible.
24. **Given** no local network connection, **When** the app boots, **Then** the app opens normally and displays the Local Profile Library gracefully.
25. **Given** a rollback fails due to a network drop, **When** the app recovers, **Then** an explicit critical error logs the failure and instructs the user on manual recovery.
26. **Given** a WiiM Mini is selected, **When** the EQ panel loads, **Then** all 10 PEQ bands are accessible in both Stereo and L/R channel modes, but the RoomFit tab is absent from the UI.
27. **Given** a WiiM Amp Pro, WiiM Amp Ultra, WiiM Sound, or WiiM Sound Lite is discovered, **When** capability detection runs, **Then** `supports_peq=True`, `supports_channel_peq=True`, and `supports_roomfit=True`, identical behaviour to a WiiM Ultra.
28. **Given** a REW text file containing more than 10 filter bands, **When** imported, **Then** a validation warning is shown and only the first 10 enabled bands are used; the user is informed of the truncation before any device write.
29. **Given** a user selects a device and it has multiple inputs, **When** the source selector populates, **Then** only inputs reported in the device's `InputList` are shown, and no source is auto-selected for write operations.
30. **Given** a profile saved in L/R channel mode, **When** loaded onto a device in Stereo mode, **Then** the app warns the user of the mode mismatch and requires explicit confirmation before proceeding.