# Implementation Plan: GUI Redesign

## Overview

Replace the current splitter-based panel layout in `src/gui/` with a wizard-driven, single-pane interface using QStackedWidget. The backend remains unchanged — only the GUI layer (`src/gui/`) is replaced (except `async_bridge.py`). Implementation follows a bottom-up approach: constants/theme → shared components → pages → views → dialogs → main window → controller wiring.

## Tasks

- [x] 1. Set up project structure, constants, and theme system
  - [x] 1.1 Create `src/gui/constants.py` with colors, typography, spacing, and sizing constants
    - Define ACCENT_COLOR, SUCCESS_COLOR, ERROR_COLOR, WARNING_COLOR
    - Define FONT_FAMILY, FONT_SIZE_BODY, FONT_SIZE_HEADING, FONT_SIZE_CAPTION
    - Define SPACING_SM, SPACING_MD, SPACING_LG, CARD_RADIUS, BUTTON_RADIUS, MAX_CONTENT_WIDTH
    - Define SIDEBAR_EXPANDED, SIDEBAR_COLLAPSED, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT, LIST_ITEM_HEIGHT
    - _Requirements: 10.2, 10.4, 10.6, 10.8, 10.10, 25.1, 25.5_

  - [x] 1.2 Create `src/gui/theme.py` with ThemeManager class
    - Implement `apply_theme(mode)` to load and apply QSS stylesheets
    - Implement `detect_system_theme()` for Windows registry / macOS defaults detection
    - Support light, dark, and system modes with dynamic switching
    - _Requirements: 25.4, 25.9_

  - [x] 1.3 Create `src/gui/assets/styles/fluent_light.qss` stylesheet
    - Define widget-level selectors for all common Qt widgets (QPushButton, QLabel, QFrame, etc.)
    - Apply rounded corners, Fluent spacing, accent colors for light mode
    - Define property-based variants for primary/secondary/ghost button styles
    - _Requirements: 25.1, 25.2, 25.3, 25.5, 25.6, 25.7, 25.8_

  - [x] 1.4 Create `src/gui/assets/styles/fluent_dark.qss` stylesheet
    - Mirror light stylesheet structure with dark-mode color values
    - Maintain same layout/spacing, adjust backgrounds, text colors, and border colors
    - _Requirements: 25.4_

  - [x] 1.5 Create directory structure and `__init__.py` files
    - Create `src/gui/components/__init__.py`, `src/gui/pages/__init__.py`, `src/gui/views/__init__.py`, `src/gui/dialogs/__init__.py`, `src/gui/assets/icons/`, `src/gui/assets/help/`
    - _Requirements: 14.2_

- [x] 2. Implement shared components
  - [x] 2.1 Create `src/gui/components/status_banner.py`
    - Implement StatusBanner widget with show_info, show_success, show_error, show_progress, clear methods
    - Color-coded backgrounds (info=neutral, success=green, error=red, progress=spinner)
    - Auto-dismiss timer for success messages (5 seconds)
    - Dismissed signal, non-technical plain-language messages
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [x] 2.2 Create `src/gui/components/step_indicator.py`
    - Implement StepIndicator widget with horizontal breadcrumb bar
    - Support set_steps, set_current, set_completed (with summary text), invalidate_from
    - Emit step_clicked signal for backward navigation on completed steps
    - Visual states: completed (filled accent + checkmark + summary), active (accent ring + bold), upcoming (gray)
    - Adapt labels dynamically based on FlowType
    - _Requirements: 1.3, 1.4, 1.5, 11.8_

  - [x] 2.3 Create `src/gui/components/sidebar_nav.py`
    - Implement SidebarNav collapsible navigation rail
    - Items: Home, Presets on Device, My Saved Presets, Settings, Help
    - Emit navigation_requested signal with view key
    - Support collapse/expand toggle (48px collapsed, 200px expanded)
    - Device name display in header area (clickable to navigate to Connect step)
    - Hover tooltips in collapsed mode
    - _Requirements: 8.1, 8.2, 8.8, 2.10, 9.5_

  - [x] 2.4 Create `src/gui/components/filter_table.py`
    - Implement FilterTable widget with fixed column widths (Band 40px, Type 70px, Freq 100px, Gain 90px, Q 70px)
    - Support set_filters with optional clamping_map for indicators
    - Support set_lr_filters for L/R tabbed display
    - Support set_comparison for diff view (highlight changes, show gain diff)
    - OFF/disabled bands at 0.5 opacity; clamped values with orange dot + tooltip
    - Max table width ~400px, centered in available space
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 19.2, 19.3_

  - [x] 2.5 Create `src/gui/components/device_card.py`
    - Implement DeviceCard widget showing device name, model, IP, firmware, multiroom role badge
    - States: idle (neutral border), connecting (pulsing accent), connected (filled accent strip), error (red strip + error + retry)
    - Emit clicked signal for device selection
    - Rounded card (8px radius), 16px padding
    - _Requirements: 2.3, 2.7, 2.9_

  - [x] 2.7 Write unit tests for shared components
    - Test StatusBanner message display, auto-dismiss, state colors
    - Test StepIndicator step states, click signals, label adaptation
    - Test SidebarNav collapse/expand, navigation signals
    - Test FilterTable column rendering, clamping indicators, L/R tabs
    - Test DeviceCard states (idle/connecting/connected/error)
    - _Requirements: 7.1-7.6, 1.3-1.4, 8.1-8.2, 5.1-5.5, 2.3_

- [~] 3. Checkpoint - Ensure shared components build correctly
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Implement wizard pages
  - [x] 4.1 Create `src/gui/pages/connect_page.py`
    - Implement ConnectPage with scanning animation, device card display, empty state
    - Auto-trigger discovery on show
    - Auto-select single device (emit device_selected)
    - Display "Searching for WiiM devices on your network..." during scan
    - Empty state: retry button, common causes explanation, troubleshooting link
    - Support refresh_requested signal
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 4.2 Create `src/gui/pages/eq_type_page.py`
    - Implement EQTypePage with two large selectable cards
    - "Parametric EQ - per-input EQ filters" and "RoomFit - room correction (all inputs)"
    - Emit eq_type_selected signal ("peq" or "roomfit")
    - Only shown when device supports RoomFit (roomfit_level >= 2)
    - _Requirements: 1.9, 11.2_

  - [x] 4.3 Create `src/gui/pages/source_page.py`
    - Implement SourcePage showing device audio sources as selectable items
    - Pre-select active source with "(currently active)" label
    - Channel mode selector (Stereo / Left / Right) - hidden if not supported
    - Explanatory note: "PEQ settings are per-source..."
    - Emit source_selected signal (source_name, channel_mode)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 4.4 Create `src/gui/pages/filters_page.py`
    - Implement FiltersPage with three options: Import from REW File, Pull from Device, Pull from REW API
    - File picker: single file for Stereo, dual file for L/R with channel labels
    - Drag-and-drop target for .txt files
    - RoomFit profile dropdown for pull operations
    - Display validation warnings inline with "Continue with adjustments" button
    - Error display for parse failures with retry option
    - REW API option visible only when reachable
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 9.3_

  - [x] 4.5 Create `src/gui/pages/review_page.py`
    - Implement ReviewPage with FilterTable, summary header (bands, source, channel, device)
    - Primary button: "Push to Device"; secondary: "Export as REW File", "Save to My Presets"
    - Dry Run toggle (changes button to "Preview Only", shows "DRY RUN" badge)
    - Compare with device toggle (disabled when no device state available)
    - "Copy to another source" and "Apply to multiple devices" actions
    - Ctrl+Enter keyboard shortcut for push confirmation
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 9.7, 12.1, 19.1, 19.4, 20.1_

  - [x] 4.6 Create `src/gui/pages/name_profile_page.py`
    - Implement NameProfilePage with text input (32-char max)
    - Show existing profiles list for reference
    - Warning when overwriting active profile (deactivation warning)
    - Emit name_confirmed signal
    - _Requirements: 16.3, 16.4, 16.5_

  - [x] 4.7 Create `src/gui/pages/push_page.py`
    - Implement PushPage with progress stages: Backing up → Writing → Verifying → Done
    - Success state: green checkmark, "OK" (green) + "Undo" (red/orange) primary buttons
    - Secondary: "Export as REW File", "Save to My Presets" text links
    - Failure state: warning/critical with recovery instructions and backup path
    - Dry Run mode: show translation result without network operations
    - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 18.1_

  - [~] 4.8 Write unit tests for wizard pages
    - Test ConnectPage: discovery trigger, auto-select, empty state
    - Test EQTypePage: selection signals
    - Test SourcePage: source list population, channel mode visibility
    - Test FiltersPage: import/pull signals, drag-drop, validation warnings display
    - Test ReviewPage: button enable states, dry run toggle, compare toggle
    - Test PushPage: progress stages, success/failure display
    - _Requirements: 2.1-2.9, 1.9, 3.1-3.6, 4.1-4.12, 5.1-5.7, 6.2-6.8_

- [~] 5. Checkpoint - Ensure wizard pages build correctly
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Implement WizardController state machine
  - [x] 6.1 Create `src/gui/wizard_controller.py`
    - Implement WizardStep enum and FlowType enum
    - Implement WizardState dataclass with all state fields
    - Implement WizardController(QObject) with step sequencing logic
    - Implement steps_for_flow() returning correct step sequence per FlowType
    - Implement advance() with validation and step_changed signal
    - Implement go_to_step() with invalidation of subsequent steps
    - Implement reset() to return to Connect step
    - Implement set_flow_type() to adapt step sequence at runtime
    - Wire to AsyncBridge signals for capability/discovery/write results
    - _Requirements: 1.2, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 14.1_

  - [~] 6.2 Write property test: Flow step sequence correctness (Property 1)
    - **Property 1: Flow step sequence correctness**
    - For any valid FlowType and device capabilities, steps_for_flow() returns the exact documented sequence
    - PEQ → [CONNECT, EQ_TYPE, SOURCE, FILTERS, REVIEW, PUSH]
    - RoomFit → [CONNECT, EQ_TYPE, FILTERS, REVIEW, NAME_PROFILE, PUSH]
    - PEQ-only → [CONNECT, SOURCE, FILTERS, REVIEW, PUSH]
    - No SOURCE for RoomFit, no EQ_TYPE for PEQ-only, NAME_PROFILE only for RoomFit
    - **Validates: Requirements 1.2, 1.9, 1.10, 1.11**

  - [~] 6.3 Write property test: Step classification invariant (Property 2)
    - **Property 2: Step classification invariant**
    - For any valid wizard state, every step is classified as exactly one of: completed, active, or upcoming
    - No step in two categories simultaneously; active step is always exactly one
    - **Validates: Requirements 1.3**

  - [~] 6.4 Write property test: Forward advancement preserves sequence order (Property 3)
    - **Property 3: Forward advancement preserves sequence order**
    - For any non-final step, advance() moves to next step in sequence
    - Previous step added to completed set; new step not in completed set
    - **Validates: Requirements 1.5**

  - [~] 6.5 Write property test: Back-navigation invalidates subsequent steps (Property 4)
    - **Property 4: Back-navigation invalidates all subsequent steps**
    - Navigating backward removes all steps after target from completed set
    - Preserves steps before target (inclusive); current step becomes target
    - **Validates: Requirements 1.6**

  - [~] 6.6 Write property test: Push prerequisites predicate (Property 5)
    - **Property 5: Push prerequisites predicate**
    - Push enabled iff: device connected, source selected (or RoomFit), filters non-empty, dry_run is False
    - If any condition not met, push is disabled
    - **Validates: Requirements 12.1**

  - [~] 6.7 Write unit tests for WizardController
    - Test flow branching based on roomfit_level (0 → PEQ-only, >=2 → EQ_TYPE shown)
    - Test advance/back-navigation/reset behavior
    - Test signal emission (step_changed, flow_type_changed, wizard_reset)
    - Test step summary updates via step_summary_updated signal
    - _Requirements: 1.2-1.12, 11.1-11.8_

- [~] 7. Checkpoint - Ensure WizardController logic is correct
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Implement secondary views
  - [~] 8.1 Create `src/gui/views/presets_device_view.py`
    - Implement PresetsDeviceView with two sections: PEQ Presets and RoomFit Profiles
    - Fetch via list_peq_profiles() and list_roomfit_profiles()
    - Each item: name, channel mode badge, PEQ/RoomFit badge
    - Multi-select for batch operations
    - Actions: Export as REW File, Save to My Presets, Load into Editor, Copy to Another Device
    - Empty state when no device connected
    - Search/filter field when > 10 items
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 15.8, 15.9, 15.10, 15.11, 15.12, 8.5, 8.6, 10.9_

  - [~] 8.2 Create `src/gui/views/my_presets_view.py`
    - Implement MyPresetsView with local preset library CRUD
    - List items: name, channel mode badge (Stereo/L/R), active band count
    - Inline rename (double-click), context menu (Load, Rename, Duplicate, Delete)
    - Search/filter when > 10 items
    - Emit load_requested signal to populate wizard Review step
    - _Requirements: 8.3, 8.4, 10.9_

  - [~] 8.3 Create `src/gui/views/settings_view.py`
    - Implement SettingsView with sections: Appearance, Paths, Behavior, Logs, Support
    - Appearance: Light/Dark/System theme toggle
    - Paths: Log dir, Presets dir, Default REW export folder (with browse + validation)
    - Behavior: Discovery timeout, Dry Run default, last-used device
    - Logs: Log file list with sizes, "Open Log Folder", "Copy Log Path"
    - Support: "Generate Support Bundle", "Show onboarding again"
    - All settings persist via settings.json
    - _Requirements: 24.1, 24.2, 24.5, 24.9, 24.10, 24.11, 24.12, 24.14, 24.15, 25.4_

  - [~] 8.4 Create `src/gui/views/help_view.py`
    - Implement HelpView as side panel overlay (does not replace current view)
    - Render bundled Markdown from assets/help/
    - Searchable table of contents sidebar
    - Contextual navigation: auto-navigate to relevant section based on current step
    - Navigate to section via help icon "?" on wizard steps
    - _Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 27.6, 27.7, 27.8, 27.9, 27.10_

  - [~] 8.5 Write unit tests for secondary views
    - Test PresetsDeviceView: section display, multi-select, empty state
    - Test MyPresetsView: CRUD signals, search filtering, load signal
    - Test SettingsView: theme toggle, path validation, settings persistence
    - Test HelpView: contextual navigation, section rendering
    - _Requirements: 15.1-15.12, 8.3-8.6, 24.1-24.15, 27.1-27.10_

- [ ] 9. Implement dialogs
  - [~] 9.1 Create `src/gui/dialogs/push_confirmation.py`
    - Implement PushConfirmation modal dialog with static confirm() method
    - Display: device name, source, channel mode, band count, dry run state
    - Include clamping summary when applicable
    - Include mode mismatch warning when applicable
    - Consolidate sequential confirmations into single summary
    - _Requirements: 6.1, 12.2, 12.3, 12.6_

  - [~] 9.2 Create `src/gui/dialogs/onboarding_overlay.py`
    - Implement OnboardingOverlay for first-run welcome
    - 3 capability cards: Import filters, Push safely, Save presets
    - "Get Started" button (dismiss + start wizard) and "Skip" link
    - Only shown when first_run_complete is False in settings
    - _Requirements: 23.1, 23.2, 23.3, 23.4, 23.5, 23.7_

  - [~] 9.3 Create `src/gui/dialogs/crash_dialog.py`
    - Implement CrashDialog with static show_crash() method
    - Display "The app encountered an unexpected error" + log file path
    - Include "View Logs" link and "Generate Support Bundle" button
    - _Requirements: 24.6, 24.7, 24.13_

  - [~] 9.4 Create `src/gui/dialogs/unsaved_changes_dialog.py`
    - Implement unsaved changes confirmation dialog
    - Triggered on close or navigate-away when filter changes exist
    - _Requirements: 12.5_

- [~] 10. Checkpoint - Ensure views and dialogs build correctly
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Implement MainWindow and wire everything together
  - [~] 11.1 Create `src/gui/main_window.py`
    - Implement MainWindow(QMainWindow) shell with sidebar + QStackedWidget + StatusBanner
    - Layout: MenuBar → Central Widget (QHBoxLayout: SidebarNav + QVBoxLayout: StepIndicator + QStackedWidget + StatusBanner)
    - QDockWidget for Diagnostics (hidden, View → Diagnostics toggle)
    - Create and own WizardController, pass AsyncBridge
    - Register all pages and views in QStackedWidget with PAGE_INDICES
    - Set minimum window size 800x600
    - Install global exception handler (crash_handler)
    - Handle closeEvent (unsaved changes check, bridge shutdown)
    - _Requirements: 14.1, 14.2, 14.4, 14.5, 10.1, 10.6, 24.6_

  - [~] 11.2 Wire WizardController to page signals and AsyncBridge
    - Connect page signals (device_selected, eq_type_selected, source_selected, etc.) to WizardController
    - Connect AsyncBridge signals (discovery_complete, capabilities_ready, peq_ready, write_complete, operation_error, progress_update) to controller handlers
    - Connect StepIndicator.step_clicked to WizardController.go_to_step
    - Connect SidebarNav.navigation_requested to QStackedWidget page switching
    - Implement auto-advance logic (single device auto-select, PEQ-only device skip)
    - _Requirements: 14.1, 14.3, 14.6, 1.5, 2.4, 2.8, 9.1, 9.2_

  - [~] 11.3 Implement responsive operation feedback and button state management
    - Disable action buttons immediately on click (prevent double-submit)
    - Show loading state within 100ms of user action
    - Display "This may take a moment..." for operations > 3 seconds
    - Provide Cancel button for operations > 2 seconds
    - Ensure main thread never blocks (all I/O via AsyncBridge)
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

  - [~] 11.4 Implement layout stability and progressive disclosure
    - Anchor action buttons, navigation, step indicators, and status banner positions
    - Reserve content area space with skeleton placeholders during loading
    - MAX_CONTENT_WIDTH constraint with centered alignment on large screens
    - Progressive disclosure: channel mode, RoomFit, dry run as secondary/expandable controls
    - _Requirements: 10.11, 10.12, 10.13, 10.5_

  - [~] 11.5 Implement keyboard navigation and accessibility
    - Full Tab/Shift+Tab/Enter/Escape navigation through all steps
    - Logical tab order following visual reading order
    - Visible focus indicators (3:1 contrast ratio)
    - Accessible names on all interactive elements
    - Keyboard shortcuts: Ctrl+O (import), Ctrl+R (refresh devices), Ctrl+Enter (confirm/push)
    - StatusBanner messages announced to screen readers
    - State communication via icon + text (not color alone)
    - _Requirements: 26.1, 26.2, 26.3, 26.4, 26.5, 26.6, 26.7_

  - [~] 11.6 Implement secondary workflow integrations
    - "Copy to another source" flow: source picker (multi-select) → Safe_Write_Protocol per source
    - "Apply to multiple devices" flow: device picker → source picker per device → sequential push
    - "Copy to Another Device" from Presets on Device view
    - Profile Recall from My Saved Presets → load into Review step
    - Undo last push: restore from most recent backup via Safe_Write_Protocol
    - _Requirements: 17.1, 17.2, 17.3, 18.1, 18.2, 18.3, 18.4, 18.6, 20.1, 20.2, 20.3, 20.4, 20.5, 21.1, 21.2, 21.3, 21.4, 21.5, 21.6_

  - [~] 11.7 Write integration tests for full wizard flows
    - Test happy path: single device → import → push (mock AsyncBridge signals)
    - Test RoomFit flow: EQ_TYPE shown, SOURCE skipped, NAME_PROFILE before push
    - Test back-navigation: step invalidation, page state reset
    - Test error recovery: StatusBanner shows error, page shows retry
    - Test undo after push: backup restore triggered
    - Test sidebar navigation preserves wizard state
    - _Requirements: 1.2-1.12, 11.1-11.8, 14.1-14.6_

- [ ] 12. Implement settings persistence and first-run logic
  - [~] 12.1 Create AppSettings dataclass and settings file I/O
    - Implement AppSettings dataclass (theme, log_directory, presets_directory, etc.)
    - Load/save from settings.json in app data directory
    - Auto-reconnect to last-used device on launch
    - Auto-enable Dry Run for first-time users
    - _Requirements: 9.2, 12.4, 23.6, 24.15_

  - [~] 12.2 Wire settings to MainWindow and components
    - Apply theme on startup based on saved preference
    - Set sidebar collapsed state from settings
    - Set Dry Run default from settings
    - Show onboarding overlay when first_run_complete is False
    - _Requirements: 23.1, 23.5, 24.15, 25.4_

- [ ] 13. Create help content assets
  - [~] 13.1 Create bundled help Markdown files in `src/gui/assets/help/`
    - getting-started.md (mirrors onboarding content)
    - import-and-push.md (primary workflow guide)
    - pull-and-export.md
    - managing-presets.md
    - using-roomfit.md
    - troubleshooting.md (device not found, parse errors, push failures, rollback)
    - _Requirements: 27.2, 27.3, 27.7, 27.8, 27.10_

- [ ] 14. Remove old GUI files and update entry point
  - [~] 14.1 Remove deprecated files from `src/gui/` (panels/, old main_window, etc.)
    - Delete all files in src/gui/ except async_bridge.py
    - Update src/gui/__init__.py to export new MainWindow
    - Ensure entry point (if any) creates new MainWindow
    - _Requirements: 14.2_

- [~] 15. Final checkpoint - Full integration verification
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate the WizardController state machine logic (5 properties from design)
- Unit tests validate individual widget behavior and signal emission
- Integration tests validate full flow traversal with mocked AsyncBridge
- `async_bridge.py` is the ONLY file preserved from the old GUI — all other files are replaced
- All GUI tests use `pytest-qt` (qtbot fixture) for event simulation
- AsyncBridge is mocked via `unittest.mock.AsyncMock` — no real network in tests
- The design uses Python/PySide6 throughout — no language selection needed

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.5"] },
    { "id": 1, "tasks": ["1.3", "1.4"] },
    { "id": 2, "tasks": ["2.1", "2.2", "2.3", "2.4", "2.5"] },
    { "id": 3, "tasks": ["2.7"] },
    { "id": 4, "tasks": ["4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "6.1"] },
    { "id": 5, "tasks": ["4.8", "6.2", "6.3", "6.4", "6.5", "6.6", "6.7"] },
    { "id": 6, "tasks": ["8.1", "8.2", "8.3", "8.4", "9.1", "9.2", "9.3", "9.4"] },
    { "id": 7, "tasks": ["8.5", "12.1", "13.1"] },
    { "id": 8, "tasks": ["11.1", "12.2"] },
    { "id": 9, "tasks": ["11.2", "11.3", "11.4", "11.5"] },
    { "id": 10, "tasks": ["11.6"] },
    { "id": 11, "tasks": ["11.7", "14.1"] }
  ]
}
```
