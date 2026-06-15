# Requirements Document

## Introduction

The GUI Redesign replaces the current panel-based layout of the WiiM ↔ REW PEQ Sync Tool with a workflow-driven interface optimized for non-technical audiophile users. The primary use case — importing a REW room correction file and pushing it to a WiiM device — should be achievable in 3–4 clicks with clear guidance at every step. The redesign also supports browsing and exporting device presets/profiles, named preset targeting on push, and all secondary workflows (profile management, RoomFit, diagnostics). The visual style follows Windows 11 Fluent Design principles while adapting to macOS and Linux platform conventions. The entire backend (adapters, translator, safe-write protocol, models, async bridge) stays unchanged; only the `src/gui/` layer is replaced.

---

## Glossary

- **App**: The WiiM ↔ REW PEQ Sync Tool desktop application.
- **Wizard_Flow**: The guided, step-by-step workflow UI that walks the user from device selection through filter push.
- **Step_Indicator**: A visual breadcrumb bar showing the user's current position in the Wizard_Flow (e.g. Connect → Source → Filters → Review → Push).
- **Filter_Preview**: A read-only table or card view displaying imported or pulled filters before any write operation.
- **Status_Banner**: A contextual, color-coded message area that tells the user what just happened or what to do next.
- **Quick_Action_Card**: A prominent UI element on the home/landing view offering one-click access to the primary workflow.
- **Sidebar_Nav**: A collapsible navigation rail providing access to secondary features (Profiles, Settings, Diagnostics).
- **Device_Card**: A visual card representing a discovered WiiM device, showing name, model, IP, and connection state.
- **Push_Confirmation**: A modal dialog summarizing the filters about to be written and requesting explicit user confirmation before the Safe Write Protocol executes.
- **AsyncBridge**: The existing asyncio ↔ Qt signal/slot bridge (unchanged).
- **Safe_Write_Protocol**: The mandatory Backup → Write → Read-Back → Verify → Commit/Rollback sequence (unchanged).
- **CanonicalFilter**: The normalized internal representation of a single EQ band (unchanged).
- **Device_Library**: A sidebar view that lists PEQ presets and RoomFit profiles stored on the connected WiiM device, with export and load capabilities.
- **Fluent_Design**: Microsoft's design language for Windows 11, characterized by rounded corners, subtle shadows, layered surfaces, and the Segoe UI Variable typeface.

---

## Requirements

### Requirement 1: Guided Workflow Structure

**User Story:** As a non-technical audiophile, I want the application to guide me step-by-step through applying room correction, so that I never feel lost or unsure what to do next.

#### Acceptance Criteria

1. WHEN the App launches with no device connected, THE Wizard_Flow SHALL display a "Connect" step as the initial view with a clear call-to-action to discover devices.
2. THE Wizard_Flow SHALL present the workflow as a linear sequence of steps: Connect → Source → Filters → Review → Push.
3. THE Step_Indicator SHALL always be visible and SHALL highlight the current step, completed steps, and remaining steps using distinct visual treatments.
4. WHEN the user completes a step, THE Wizard_Flow SHALL automatically advance to the next step.
5. THE Wizard_Flow SHALL allow the user to navigate backward to any previously completed step by clicking the Step_Indicator.
6. WHEN the user navigates backward and changes a value (e.g. selects a different device), THE Wizard_Flow SHALL invalidate all subsequent steps and require the user to re-confirm them.
7. THE Wizard_Flow SHALL disable the "Next" or advance control when the current step's required selections are incomplete.

---

### Requirement 2: Device Connection Step

**User Story:** As a user, I want to discover and select my WiiM device in a visually clear way, so that I know exactly which device I am configuring.

#### Acceptance Criteria

1. WHEN the App starts, THE Wizard_Flow SHALL automatically trigger device discovery without requiring user interaction.
2. WHILE device discovery is in progress, THE App SHALL display a scanning animation with the text "Searching for WiiM devices on your network..."
3. WHEN discovery finds one or more devices, THE App SHALL display each device as a Device_Card showing: device name, model, IP address, firmware version, and multiroom role badge.
4. WHEN discovery finds exactly one device, THE App SHALL auto-select that device and advance to the Source step; THE App SHALL display a brief notification identifying the auto-selected device.
5. WHEN discovery finds multiple devices, THE App SHALL require the user to click a Device_Card to select a device.
6. WHEN discovery finds no devices, THE App SHALL display a helpful empty state with: a retry button, a brief explanation of common causes (device off, different subnet), and a link to manual troubleshooting guidance.
7. WHEN the user selects a device, THE App SHALL probe its capabilities via the AsyncBridge and display a brief "Connecting..." state on the Device_Card until probing completes.
8. WHEN capability probing completes, THE App SHALL advance to the Source step.
9. IF capability probing fails, THEN THE App SHALL display an error on the Device_Card with a "Retry" option and SHALL NOT advance to the next step.

---

### Requirement 3: Source Selection Step

**User Story:** As a user, I want to choose which audio input I am configuring EQ for, so that filters apply to the correct source.

#### Acceptance Criteria

1. WHEN the Source step is displayed, THE App SHALL show the device's available audio sources as selectable items populated from the probed capabilities.
2. THE App SHALL pre-select the device's currently active source and display a "(currently active)" label next to that source.
3. WHEN the user selects a source, THE Wizard_Flow SHALL advance to the Filters step.
4. THE App SHALL display a brief explanatory note: "EQ settings are per-source. Choose the input you want to apply room correction to."
5. WHEN the device supports L/R channel mode, THE App SHALL display a channel mode selector (Stereo / Left / Right) below the source list with "Stereo" as the default.
6. WHEN the device does not support L/R channel mode, THE App SHALL hide the channel mode selector and use Stereo mode implicitly.

---

### Requirement 4: Filter Loading Step

**User Story:** As a user, I want a clear choice between importing filters from a REW file or pulling the current state from my device, so that I always know where my filter data comes from.

#### Acceptance Criteria

1. WHEN the Filters step is displayed, THE App SHALL present two prominent options: "Import from REW File" and "Pull from Device".
2. WHEN the user selects "Import from REW File", THE App SHALL open a native file picker dialog filtered to `.txt` files.
3. WHEN the user selects a valid REW file, THE App SHALL parse the file, display the imported filters in the Filter_Preview, and advance to the Review step.
4. WHEN parsing encounters validation warnings (gain/Q out of WiiM range, too many bands), THE App SHALL display the warnings inline in the Filter_Preview with clear explanations and a "Continue with adjustments" button; THE App SHALL NOT advance until the user acknowledges.
5. WHEN parsing fails (invalid file format, malformed lines), THE App SHALL display an error message identifying the problem and offer the user a chance to select a different file.
6. WHEN the user selects "Pull from Device", THE App SHALL read the current PEQ state from the selected device and source via the AsyncBridge.
7. WHEN pulling completes, THE App SHALL populate the Filter_Preview and advance to the Review step.
8. IF the pull operation fails, THEN THE App SHALL display a connection error with a "Retry" option and SHALL NOT advance.
9. THE App SHALL also display a third, less prominent option: "Pull from REW API" (visible only when REW HTTP API is reachable).
10. WHEN "Pull from REW API" is selected, THE App SHALL retrieve measurements from REW, present a measurement picker, and after user selection SHALL parse filters and advance to the Review step.

---

### Requirement 5: Filter Review Step

**User Story:** As a user, I want to see exactly what filters will be written to my device before committing, so that I can verify the configuration and catch errors.

#### Acceptance Criteria

1. WHEN the Review step is displayed, THE App SHALL show the full filter set in a readable table with columns: Band number, Type, Frequency (Hz), Gain (dB), Q factor.
2. THE App SHALL visually distinguish active filters from OFF/disabled filters using color or opacity.
3. THE App SHALL display a summary header showing: total active bands, source name, channel mode, and device name.
4. WHEN any gain or Q values were clipped to WiiM hardware limits, THE App SHALL display a "Clamped values" indicator next to the affected rows with tooltips explaining the original vs. clamped value.
5. THE App SHALL provide a prominent "Push to Device" button and a secondary "Save as Profile" button.
6. THE App SHALL provide a "Dry Run" toggle that, when active, changes the "Push to Device" button to "Preview Only" and prevents any device write.
7. WHEN Dry Run mode is active, THE App SHALL display a visible "DRY RUN" badge in the Status_Banner.

---

### Requirement 6: Push Execution and Feedback

**User Story:** As a user, I want clear, real-time feedback during the push operation, so that I know whether it succeeded or if something went wrong.

#### Acceptance Criteria

1. WHEN the user clicks "Push to Device", THE App SHALL display a Push_Confirmation dialog summarizing: device name, source, channel mode, number of bands, and whether Dry Run is active.
2. WHEN the user confirms the Push_Confirmation, THE App SHALL execute the Safe_Write_Protocol via the AsyncBridge.
3. WHILE the push operation is in progress, THE App SHALL display a progress indicator with stage labels (Backing up → Writing → Verifying → Done).
4. WHEN the push succeeds, THE App SHALL display a success state with a green checkmark and the message "Filters applied successfully" in the Status_Banner.
5. WHEN the push fails but rollback succeeds, THE App SHALL display a warning state explaining that the write failed and the original state has been restored.
6. WHEN the push fails and rollback also fails, THE App SHALL display a critical error state with the backup file path and step-by-step manual recovery instructions.
7. AFTER a successful push, THE App SHALL offer "Save as Profile" and "Start Over" actions.
8. WHEN the user is in Dry Run mode and clicks "Preview Only", THE App SHALL display the translation result and any clamping warnings without executing any network operation.

---

### Requirement 7: Status Banner and Contextual Feedback

**User Story:** As a user, I want the application to always tell me what is happening and what I should do next, so that I never feel stuck.

#### Acceptance Criteria

1. THE Status_Banner SHALL be persistently visible at the top or bottom of the main content area.
2. THE Status_Banner SHALL display contextual messages appropriate to the current workflow step (e.g. "Select your WiiM device to get started", "Choose the audio source to configure").
3. WHEN an operation is in progress, THE Status_Banner SHALL display an activity indicator and a descriptive message (e.g. "Scanning for devices...", "Reading filters from device...").
4. WHEN an operation completes successfully, THE Status_Banner SHALL display a success message with a green visual treatment that auto-dismisses after 5 seconds.
5. WHEN an error occurs, THE Status_Banner SHALL display an error message with a red visual treatment that persists until the user dismisses it or takes corrective action.
6. THE Status_Banner SHALL never display technical jargon (e.g. HTTP status codes, exception class names) to the user; error messages SHALL use plain language with actionable guidance.

---

### Requirement 8: Navigation and Secondary Features

**User Story:** As a user, I want to access profiles, settings, and advanced features without them cluttering my main workflow, so that the interface stays clean but full-featured.

#### Acceptance Criteria

1. THE App SHALL provide a Sidebar_Nav that gives access to: Home (Wizard_Flow), Profiles, and Settings.
2. THE Sidebar_Nav SHALL be collapsible to icon-only mode to maximize content space.
3. WHEN the user navigates to Profiles, THE App SHALL display the full profile management interface (save, load, rename, delete, duplicate, tag) as a dedicated view.
4. WHEN the user loads a profile from the Profiles view, THE App SHALL populate the Filter_Preview and navigate the Wizard_Flow to the Review step with the loaded filters.
5. THE Diagnostics_Panel SHALL remain accessible via a menu item (View → Diagnostics) and SHALL NOT appear in the Sidebar_Nav.
6. WHEN the user is on the Home view and has a device connected, THE App SHALL display the device name and connection status in the Sidebar_Nav header area.

---

### Requirement 9: Quick Start and Primary Use Case Optimization

**User Story:** As a user who just wants to apply a REW file to my WiiM, I want the fastest possible path from launch to applied filters, so that the tool feels effortless.

#### Acceptance Criteria

1. WHEN the App launches and exactly one device is found, THE App SHALL auto-connect to that device, auto-select the active source, and present the Filters step within 3 seconds of launch (network conditions permitting).
2. WHEN the App launches and has previously connected to a device (last-used device stored in settings), THE App SHALL attempt to reconnect to that device first before running full discovery.
3. THE App SHALL support a drag-and-drop target on the Filters step that accepts REW `.txt` files, triggering the same import flow as the file picker.
4. THE primary use case (import REW file → push to single device) SHALL require no more than 4 user interactions after launch: (1) confirm device if auto-selected or select device, (2) confirm source, (3) select REW file, (4) confirm push.
5. WHEN filters have been successfully imported, THE App SHALL enable a keyboard shortcut (Ctrl+Enter) to proceed to push confirmation from the Review step.

---

### Requirement 10: Visual Design and Layout

**User Story:** As a non-technical user, I want the interface to look clean and professional with clear visual hierarchy, so that I can focus on what matters without visual clutter.

#### Acceptance Criteria

1. THE App SHALL use a single-pane main content area (no splitters) with the Wizard_Flow step content filling the available space.
2. THE App SHALL use consistent spacing, typography, and color throughout all views.
3. THE App SHALL use a maximum of two primary action buttons visible at any time; secondary actions SHALL use text links or subdued button styles.
4. THE App SHALL use adequate font sizes (minimum 13px for body text) and sufficient contrast ratios for readability.
5. THE App SHALL use progressive disclosure: advanced options (channel mode, RoomFit, dry run) appear as expandable sections or secondary controls, not upfront.
6. THE App main window SHALL have a minimum size of 800×600 pixels and SHALL scale gracefully at larger sizes without wasted space.
7. THE App SHALL NOT use placeholder widgets or empty panels; every visible area SHALL display meaningful content or be hidden entirely.

---

### Requirement 11: RoomFit Integration

**User Story:** As a user with a RoomFit-capable device, I want to access RoomFit features within the same guided workflow, so that managing room correction is as easy as PEQ management.

#### Acceptance Criteria

1. WHEN the connected device has `roomfit_level` of 0, THE App SHALL hide all RoomFit UI elements entirely.
2. WHEN the connected device has `roomfit_level` of 1 or higher, THE App SHALL display a "RoomFit" section in the Source step indicating RoomFit is available on this device.
3. WHEN `roomfit_level` is 2 or higher, THE App SHALL allow the user to pull RoomFit filters as an option alongside PEQ pull in the Filters step.
4. WHEN `roomfit_level` is 4, THE App SHALL allow the user to push filters to a RoomFit slot, offering a RoomFit profile picker during the Review step.
5. THE App SHALL visually distinguish RoomFit operations from PEQ operations using a label or badge so the user always knows which filter type is being modified.

---

### Requirement 12: Error Prevention and Guidance

**User Story:** As a non-technical user, I want the application to prevent me from making mistakes before they happen, so that I never accidentally misconfigure my device.

#### Acceptance Criteria

1. THE App SHALL disable the "Push to Device" button until all prerequisites are met (device connected, source selected, filters loaded, not in Dry Run mode) and SHALL display a tooltip explaining each unmet prerequisite.
2. WHEN the user attempts to push filters that contain clipped values, THE App SHALL include a clamping summary in the Push_Confirmation dialog.
3. WHEN the user attempts to load a Stereo profile onto a device in L/R mode (or vice versa), THE App SHALL display a mode mismatch warning in the Push_Confirmation dialog and require explicit acknowledgement.
4. THE App SHALL auto-enable Dry Run mode for first-time users (until they explicitly disable it) and SHALL display a "Dry Run is ON — no changes will be made to your device" message.
5. WHEN the user has unsaved filter changes and attempts to navigate away or close the App, THE App SHALL prompt with an "Unsaved changes" confirmation dialog.
6. THE App SHALL never present more than one confirmation dialog simultaneously; sequential confirmations SHALL be consolidated into a single summary dialog where possible.

---

### Requirement 13: Responsive Operation Feedback

**User Story:** As a user, I want every button press to feel responsive even when operations take time, so that I trust the application is working correctly.

#### Acceptance Criteria

1. WHEN the user triggers any operation that involves network I/O, THE App SHALL display a loading state within 100 milliseconds of the user action.
2. THE App SHALL disable action buttons immediately upon click to prevent double-submission, re-enabling them only after the operation completes or fails.
3. WHEN an operation takes longer than 3 seconds, THE App SHALL display a supplementary message (e.g. "This may take a moment...") to reassure the user.
4. ALL background operations SHALL remain cancellable; THE App SHALL provide a "Cancel" button for operations lasting longer than 2 seconds.
5. THE App SHALL remain interactive (scrolling, navigating to other views) while background operations execute; the main thread SHALL NOT block.
6. WHEN an operation completes, THE App SHALL provide clear completion feedback (visual state change, message, or animation) distinct from the in-progress state.

---

### Requirement 14: Window Layout and Architecture

**User Story:** As a developer, I want the new GUI to maintain clean separation of concerns and integrate with the existing AsyncBridge, so that the redesign does not require backend changes.

#### Acceptance Criteria

1. THE App SHALL use the existing AsyncBridge signal/slot mechanism for all communication between the GUI layer and the async backend.
2. THE App SHALL replace all files in `src/gui/` except `async_bridge.py`, which SHALL remain unchanged.
3. THE App SHALL NOT introduce any new network I/O or business logic into GUI components; all operations SHALL be dispatched through the AsyncBridge to the existing adapters.
4. THE App main window SHALL use a QStackedWidget or equivalent mechanism to manage step transitions rather than splitters with fixed panels.
5. THE App SHALL maintain the existing menu bar with View → Diagnostics toggle for the developer diagnostics dock.
6. THE App SHALL emit the same signals for profile operations, PEQ read/write, and discovery that the current panels emit, preserving backend compatibility.

---

### Requirement 15: Device Preset and Profile Browsing and Export

**User Story:** As a user, I want to browse the PEQ presets and RoomFit profiles stored on my WiiM device and export them to REW-compatible files, so that I can back them up or edit them in REW.

#### Acceptance Criteria

1. THE Sidebar_Nav SHALL include a "Device Library" view (accessible when a device is connected) that lists both PEQ presets and RoomFit profiles stored on the connected device.
2. WHEN the user navigates to the Device Library view, THE App SHALL fetch the list of PEQ presets via `list_peq_profiles()` and RoomFit profiles via `list_roomfit_profiles()` and display them in separate labelled sections.
3. EACH listed preset/profile SHALL display its name, channel mode, and a visual indicator distinguishing PEQ from RoomFit items.
4. THE App SHALL allow the user to select one or more presets/profiles and click "Export to REW File" to save them as individual `.txt` files in REW-compatible format.
5. WHEN exporting multiple items, THE App SHALL prompt the user for a destination folder and generate one REW `.txt` file per selected item, named after the preset/profile name.
6. WHEN exporting a single item, THE App SHALL open a "Save As" dialog pre-filled with the preset/profile name.
7. WHEN exporting an L/R preset/profile, THE App SHALL generate two files (`_L.txt` and `_R.txt`) as per the existing REW generator convention.
8. THE App SHALL allow the user to select a preset/profile and click "Load into Editor" to populate the Filter_Preview and navigate to the Review step (enabling push to a different source or re-push after edits).
9. WHEN the device does not support profile enumeration (`supports_profile_enumeration=False`), THE App SHALL display "Device presets not available on this model" in the PEQ presets section.
10. WHEN `roomfit_level` is 0, THE App SHALL hide the RoomFit profiles section entirely.

---

### Requirement 16: Named Preset and Profile Targeting on Push

**User Story:** As a user, I want to choose a name for the PEQ preset or RoomFit profile when pushing filters to my device, so that I can organize multiple configurations on the device.

#### Acceptance Criteria

1. WHEN the user reaches the Review step and the connected device supports profile enumeration, THE App SHALL display a "Save as device preset" checkbox with a text field for the preset name.
2. WHEN "Save as device preset" is checked and the user confirms the push, THE App SHALL first execute the Safe_Write_Protocol for the live PEQ state, THEN save the written state as a named device preset using `save_peq_profile()`.
3. WHEN the user is pushing to a RoomFit profile (`roomfit_level >= 4`), THE App SHALL display a "Profile name" field that the user MUST fill before pushing; THE App SHALL pre-populate this with the name of the profile being overwritten (if any) or leave it blank for a new profile.
4. WHEN the user enters a RoomFit profile name that matches the currently-active profile, THE App SHALL display a deactivation warning: "Saving to the active profile will temporarily deactivate Room Correction. You'll need to re-select it in the WiiM app." with options [Save as new name...] [Overwrite anyway] [Cancel].
5. THE preset/profile name field SHALL validate that the name is non-empty and does not exceed 32 characters.
6. WHEN push completes successfully and a preset/profile name was specified, THE App SHALL display the success message including the saved name (e.g. "Filters applied and saved as 'Living Room EQ'").

---

### Requirement 17: Supported Use Cases — All Task-Based and Guided

**User Story:** As a user, I want every operation in the application to follow a clear, guided sequence of steps, so that I always know what to do next regardless of which workflow I am in.

#### Acceptance Criteria

1. EVERY user-facing workflow in the App SHALL follow a task-based, step-by-step guided structure with the same UX principles as the primary wizard: clear step labels, visual progress, contextual help text, automatic advancement on completion, and back-navigation.
2. THE App SHALL support the following primary use cases, EACH presented as a guided flow with step indicators:
   - **Import & Push** (Connect → Source → Import File → Review → Push): Import a REW `.txt` file → preview → push to device. The primary 4-click path.
   - **Pull & Export** (Connect → Source → Pull → Review → Export): Pull current device PEQ state → preview → export to REW `.txt` file. The Export step SHALL offer a "Save As" file dialog with the source name pre-filled.
   - **Pull & Re-Push** (Connect → Source → Pull → Review → Change Target → Push): Pull from device → user views filters → select a different source or channel → push back. The "Change Target" step lets the user pick a new destination without restarting.
   - **Profile Recall & Push** (Select Profile → Review → Connect → Source → Push): Load a saved local profile → preview → connect to device → push. This flow starts from the Profiles sidebar and merges into the wizard at the Review step.
   - **REW API Import & Push** (Connect → Source → Select Measurement → Review → Push): Pull filters from a running REW instance → preview → push.
3. THE App SHALL support the following secondary use cases, EACH also presented with guided step flows:
   - **Device Preset Export** (Connect → Browse Presets → Select → Export): List device PEQ presets → select one or more → export to REW `.txt` files. The App SHALL show a progress indicator during export and confirm completion with file paths.
   - **RoomFit Profile Export** (Connect → Browse RoomFit → Select → Export): List device RoomFit profiles → select one or more → export to REW `.txt` files.
   - **Batch Export** (Connect → Select All / Choose Items → Pick Folder → Export All): Export all device presets, all RoomFit profiles, or all local profiles to a folder. The App SHALL show per-item progress.
   - **RoomFit Push** (Connect → Source → Import/Pull → Review → Name Profile → Push): Same as Import & Push but targets a named RoomFit profile slot. The "Name Profile" step SHALL appear before push and require a profile name.
4. THE App SHALL support the following utility use cases:
   - **Dry Run**: Available as a toggle within any push flow; changes "Push" button to "Preview Only" and prevents all device writes.
   - **Local Profile Management**: Accessible from the Sidebar_Nav as a dedicated view; CRUD operations (save, load, rename, delete, duplicate, tag) use inline editing patterns (no separate wizard needed since these are single-action operations).
   - **Diagnostics**: Raw API access for developers (View → Diagnostics, hidden by default). This is the ONLY feature that does not require a guided flow.
5. ALL use cases that produce or consume filters SHALL share the same Filter_Preview and Review step UI component — the workflow adapts its step sequence based on the filter source and destination, but the review/preview experience is always identical.
6. WHEN the user initiates any workflow, THE App SHALL display the full step sequence for that workflow in the Step_Indicator, so the user can see how many steps remain and where they are.
7. THE App SHALL NOT present any workflow as a collection of independent buttons on a single screen; every multi-step operation SHALL have explicit step transitions with visual feedback.

---

### Requirement 18: Log File Accessibility

**User Story:** As a user experiencing issues, I want to easily find and share log files, so that I or a support contact can diagnose problems.

#### Acceptance Criteria

1. THE Settings view SHALL display the log file directory path and provide a "Open Log Folder" button that opens the OS file explorer at that location.
2. THE Settings view SHALL list the three log files (app.log, wiim_api.log, rew_api.log) with their current size and last-modified timestamp.
3. THE App SHALL continue to generate rotating log files as per the existing logging configuration (10 MB rotation, 5 archives retained) regardless of the GUI redesign.
4. WHEN a critical error occurs (e.g. rollback failure), THE error dialog SHALL include a "View Logs" link that opens the app.log file in the system's default text viewer.
5. THE Settings view SHALL provide a "Copy Log Path" button for easy sharing in support requests.

---

### Requirement 19: Windows 11 Fluent Design Alignment

**User Story:** As a Windows 11 user, I want the application to look and feel like a modern Windows app, so that it integrates visually with my desktop environment.

#### Acceptance Criteria

1. THE App SHALL use a visual style aligned with Windows 11 Fluent Design principles: rounded corners (8px radius on cards, buttons, and inputs), subtle drop shadows, and semi-transparent layering where appropriate.
2. THE App SHALL use the Segoe UI Variable font family (the Windows 11 system font) as the primary typeface, falling back to the platform default on macOS/Linux.
3. THE App SHALL use a neutral color palette with a single accent color (default: WiiM brand teal `#00B4D8`) for primary actions, links, and the Step_Indicator active state.
4. THE App SHALL support light mode and dark mode, following the OS system preference by default with a manual override in Settings.
5. THE App SHALL use card-based layouts with consistent 16px/24px spacing grid for content sections (Device_Cards, filter tables, profile items).
6. THE App buttons SHALL use Fluent-style pill shapes for primary actions and ghost/outline styles for secondary actions.
7. THE App SHALL apply subtle hover and press animations (opacity shifts, slight scale) on interactive elements to provide tactile feedback.
8. THE App SHALL use Fluent-style iconography (line-based, consistent stroke weight) for navigation and action icons; icons SHALL be sourced from the Fluent UI System Icons set or equivalent open-source alternatives.
9. ON macOS AND Linux, THE App SHALL adapt the visual style to feel native to each platform (e.g. macOS uses SF Pro font, Linux uses system GTK/Qt theme) while maintaining the same layout and color system.

---

### Requirement 20: Accessibility and Usability

**User Story:** As a user who may have vision or motor impairments, I want the application to be usable with keyboard navigation and screen readers, so that the tool is accessible to all audiophiles.

#### Acceptance Criteria

1. THE App SHALL support full keyboard navigation through all workflow steps using Tab, Shift+Tab, Enter, and Escape.
2. THE App SHALL maintain a logical tab order that follows the visual reading order within each step.
3. ALL interactive elements SHALL have visible focus indicators that meet a minimum 3:1 contrast ratio against their background.
4. ALL buttons and controls SHALL have accessible names that convey their purpose to assistive technology.
5. THE App SHALL provide keyboard shortcuts for primary actions: Ctrl+O for import file, Ctrl+R for refresh devices, Ctrl+Enter for confirm/push.
6. THE Status_Banner messages SHALL be announced to screen readers when they change (using Qt accessibility roles).
7. THE App SHALL NOT rely solely on color to communicate state (e.g. success/error indicators SHALL include an icon or text label in addition to color).
