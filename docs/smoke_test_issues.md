# GUI Smoke Test Issues

Tracks issues found during manual smoke testing of the GUI integration.

## Issue Status Legend

- **Status:** `FIXED` | `OPEN` | `WONTFIX`
- **Test:** `YES` (unit test exists) | `NO` (needs test) | `N/A` (not testable in automation)

## Issues

| # | Issue | Status | Test | Fix Commit | Notes |
|---|-------|--------|------|------------|-------|
| 1 | Device click → "Processing" → nothing happens (NoSources error) | FIXED | YES | `12e8b38` | getStatusEx doesn't report InputList; fallback to canonical source defaults |
| 2 | User Guide has no visible close button / way to exit | FIXED | YES | `d5ff9e9` | Wired `close_requested` signal to navigate back to wizard |
| 3 | All windows have transparent backgrounds (WSL rendering) | WONTFIX | N/A | — | WSLg/Wayland compositor artifact; resolves with native Windows build |
| 4 | Device cards in single narrow column, wasted screen space | FIXED | N/A | `fcb82c2` | Removed 800px max-width from QStackedWidget, increased MAX_CONTENT_WIDTH to 1200 |
| 5 | No step indicator shown at all | FIXED | YES | `559ce5f` | Step indicator never initialized at startup; added init with default flow |
| 6 | Sidebar device name shows "WiiM Device" instead of real name | FIXED | YES | `559ce5f` | Used caps.model fallback + discovered device name lookup |
| 7 | Pull from Device → "Processing" → nothing visible in GUI | FIXED | YES | `48bc9f9`, `d01bc84` | _on_peq_ready was a TODO stub; now populates ReviewPage + advances wizard |
| 8 | Success message after device pull wiped immediately | FIXED | YES | `48bc9f9` | OperationFeedbackManager.finish_operation() cleared banner; added 50ms delay |
| 9 | HelpView close button not wired | FIXED | YES | `d5ff9e9` | Same as #2 |
| 10 | Measurement picker cancel = silent dead end | FIXED | YES | `d5ff9e9` | Shows "Selection cancelled" info banner |
| 11 | FiltersPage retry button only hides error, doesn't reset page | FIXED | YES | `d5ff9e9` | Now re-shows option cards so user can try again |
| 12 | No immediate loading feedback for device/REW pull on FiltersPage | FIXED | YES | `d5ff9e9` | Added show_progress() before async calls |
| 13 | Empty filters from device — no guidance after banner auto-dismisses | FIXED | YES | `d5ff9e9` | Changed to persistent message with suggestion |
| 14 | ConnectPage auto-triggers discovery on every showEvent (back-nav) | FIXED | YES | `d5ff9e9` | Guard: only emit refresh_requested when no cards shown |
| 15 | RoomFit flow: Connect step missing checkmark after flow type switch | FIXED | YES | `791f04a` | _on_flow_type_changed now replays completed step summaries |
| 16 | RoomFit flow: "No source selected" when pulling from device | FIXED | YES | `791f04a` | Defaults to "wifi" when no source explicitly set (RoomFit is device-global) |
| 17 | Home button appears to do nothing | WONTFIX | N/A | — | Working as designed: "home" = return to current wizard step. If already there, no visible change. |
| 18 | App crashes on startup: `ProfileRepository` has no `storage_root` attribute | FIXED | YES | `ae787c2` | Added `storage_root` property to expose `_profiles_dir.parent` |
| 19 | Theme setting has no effect in compiled app (always dark) | FIXED | N/A | `ae787c2` | QSS stylesheets not bundled in PyInstaller spec; added to `datas_list` in all platform specs |
| 18 | Filter table too narrow (400px cap), only 3 columns visible | FIXED | N/A | `791f04a`, `5f355b5` | Removed max-width/centering, columns now stretch to fill available width |
| 19 | RoomFit mode: FiltersPage shows PEQ options instead of RoomFit UI | FIXED | YES | `5f355b5` | _on_eq_type_selected now calls set_roomfit_mode(True/False) |
| 20 | Presets on Device view shows nothing when navigated to | FIXED | YES | `5f355b5` | Added _load_device_presets() trigger on navigation + _do_list_presets async |
| 21 | Sidebar collapsed mode shows blank buttons (no icons) | FIXED | N/A | `b6bcc36` | Added emoji icons as placeholders for collapsed mode |
| 22 | Presets on Device shows PEQ presets but no RoomFit profiles | FIXED | YES | `b6bcc36` | _do_list_presets now fetches both PEQ + RoomFit and populates both sections |
| 23 | RoomFit FiltersPage profile dropdown is empty | FIXED | YES | `b6bcc36` | Added _do_list_roomfit_profiles async fetch when EQ type "roomfit" is selected |
| 24 | Presets on Device: Export/Save/Load buttons do nothing (no signal wired) | FIXED | YES | `69d09c2`, `c55918e` | Fully implemented: Export reads preset then writes REW file; Save creates local Profile; Load reads preset into Review |
| 25 | Presets on Device: Can select PEQ + RoomFit items simultaneously | FIXED | YES | `69d09c2` | Added mutual exclusion: selecting in one list clears the other |
| 26 | Presets on Device: Copy to Another Device doesn't actually write preset to target | FIXED | YES | `c55918e` | Reads filters, connects to target, writes via SafeWrite, saves as named preset; shows success/failure status |
| 27 | RoomFit FiltersPage: No way to progress after selecting profile from dropdown | FIXED | YES | `69d09c2` | Wired roomfit_profile_selected; reads profile with L/R mode handling; advances to Review |
| 28 | Review page shows single 24-row table for L/R instead of separate L/R tabs | FIXED | YES | `d0aa100` | _on_peq_ready now checks channel_mode and calls set_lr_filters() for L/R mode |
| 29 | Export as REW: L/R mode creates single file with 10 bands instead of two files | FIXED | YES | `d0aa100` | Export logic branches on channel_mode; uses ExportDialog for dual-file L/R export |
| 30 | Export as REW: file doesn't get .txt extension when not typed by user | FIXED | YES | `d0aa100` | Added if not path.lower().endswith('.txt'): path += '.txt' in stereo export path |
| 31 | Save to My Presets: no visible result after processing, nothing in My Presets | FIXED | YES | `d0aa100` | Added _profile_repository.list() → set_presets() refresh after save; also refresh on nav to My Presets |
| 32 | Copy to Another Device: status message not shown long enough to read | FIXED | YES | `d0aa100` | finish_operation() no longer clears banner unconditionally; only clears if still showing progress spinner |
| 33 | Copy to Another Device: only pushes to first device when multiple selected | FIXED | YES | `d0aa100` | Replaced per-item run_async loop with single _do_copy_presets_batch coroutine |
| 34 | Copy to Another Device: RoomFit profile saved as PEQ on target (wrong type) | FIXED | YES | `d0aa100` | _do_copy_preset_to_device now branches on preset_type; uses write_roomfit() for RoomFit |
| 35 | Source page shows all canonical sources regardless of device model | FIXED | YES | `d0aa100` | All common sources shown (PEQ accepts any source name; extra slots are harmless) |
| 36 | WiiM Mini shows RoomFit in EQ Type despite not supporting it | FIXED | YES | `d0aa100` | Added model-based roomfit blocklist; Mini forced to PEQ_ONLY flow even if roomfit_level >= 2 |
| 37 | ReviewPage "Save to My Presets" button does nothing | FIXED | YES | `d6983fb` | save_preset_requested signal was never connected; added _on_review_save_preset handler |
| 38 | My Saved Presets: no actions (delete/rename/duplicate) wired | FIXED | YES | `ddb2349`, `94272de` | Connected signals + added visible toolbar (Load/Rename/Duplicate/Delete) on selection |
| 39 | My Saved Presets: L/R presets shown as "stereo" with 24 bands | FIXED | YES | `ddb2349`, `94272de` | Badge shows "L/R", band count uses per-channel, channel_mode preserved on save |
| 40 | Export L/R preset from Presets on Device creates single file | FIXED | YES | `ddb2349`, `94272de` | Both Presets view and Review step now generate _L.txt + _R.txt; state.channel_mode updated from device |
| 41 | Back-nav to Connect → selecting new device keeps old flow type | FIXED | YES | `d6983fb` | _on_device_selected resets flow_type to PEQ before probing |
| 42 | WiiM Mini missing line-in source in Source page | FIXED | YES | `d6983fb` | Reverted to showing all common sources (PEQ accepts any name; no model filtering needed) |
| 43 | Sound/Sound Lite shows optical and HDMI sources (not applicable) | WONTFIX | N/A | — | PEQ engine accepts any source name; showing extra sources is harmless. No reliable way to probe physical inputs. |
| 44 | ReviewPage "Save to My Presets" crashes with FileNotFoundError for L/R names | FIXED | YES | `5c93394` | Name contained "/" from channel mode; added filesystem-safe name sanitization in shared helper |
| 45 | Export from Review vs Presets on Device shows different dialogs | FIXED | YES | `5c93394` | Consolidated into shared _export_filters_as_rew helper; both use ExportDialog for L/R |
| 46 | My Saved Presets: no visible action buttons (only right-click context menu) | FIXED | YES | `e921182` | Added visible toolbar (Load/Rename/Duplicate/Delete) that appears on item selection |
| 47 | Duplicate save/export logic across trigger points (architectural) | FIXED | YES | `5c93394` | Created shared helpers: _save_filters_to_presets, _export_filters_as_rew; all triggers converge |
| 48 | Presets on Device "Save to My Presets" creates popup windows | FIXED | YES | `e144ddb` | _do_preset_save was calling Qt widget methods from async thread; moved to thread-safe pattern |
| 49 | Loading L/R profile from My Saved Presets shows "no filters" | FIXED | YES | `e144ddb` | recall_profile now handles L/R profiles (filters_l + filters_r) not just stereo |
| 50 | "Copy to another source" shows "No sources available" | FIXED | YES | `e144ddb` | Was reading from capabilities.source_names (empty); now uses SourcePage's known source list |
| 51 | REW file import: no way to import L/R (two files) | FIXED | YES | `e144ddb` | Added Stereo/L/R choice dialog on import click; L/R shows dual file picker; wired file_import_lr_requested signal |
| 52 | FiltersPage shows "Pull from Device" and "Pull from REW API" options | FIXED | N/A | `e144ddb` | Hidden — these workflows are accessible via "Presets on Device" sidebar |
| 53 | PushPage "Export" and "Save to My Presets" buttons do nothing | FIXED | YES | `e144ddb` | Wired push_page.export_requested and save_preset_requested to shared handlers |
| 54 | Push step doesn't show checkmark on success | FIXED | YES | `e144ddb` | _on_write_complete now marks PUSH step completed in step indicator |
| 55 | Push sends L/R filters as stereo (channel_mode "L/R" != "lr") | FIXED | YES | `5761cef` | _do_push now checks both "lr" and "l/r" in channel_mode comparison |
| 56 | Drag-and-drop zone confusing for L/R (which file is L vs R?) | FIXED | N/A | `5761cef` | Drop zone hidden — import flow uses explicit Stereo/L/R choice dialog |
| 57 | Back-navigation from Push keeps all steps checked | FIXED | YES | `5761cef` | _on_step_changed now clears completion badges for invalidated steps via clear_completed() |
| 58 | Multi-device push always uses stereo PEQ regardless of context | FIXED | YES | `5761cef` | apply_to_devices now receives channel_mode from wizard state; builds L/R PEQSettings when appropriate |
| 59 | RoomFit: Filters page shows "Select RoomFit profile to pull" dropdown | FIXED | N/A | `7e6cc12` | Hidden — RoomFit profile pull is via "Presets on Device" sidebar only |
| 60 | RoomFit: NameProfilePage "Existing profiles" list is empty | FIXED | YES | `0a132e4` | Added _populate_name_profile_page() that fetches profiles when navigating to NAME_PROFILE step |
| 61 | RoomFit: Push ignores profile name from "Name Profile" step (uses "My RoomFit") | FIXED | YES | `b4f9037` | _on_push_requested defers push for RoomFit; push fires from _on_name_confirmed after name is stored |
| 62 | RoomFit: Undo button crashes with "Is a directory" error | FIXED | YES | `b83d65f` | Undo now works for RoomFit: backs up existing profile before overwrite; hidden for new profiles only |
| 63 | RoomFit/PEQ: L/R filters written as Stereo in all write paths | FIXED | YES | `306a1de` | write_roomfit now accepts channel_mode; all write paths (push, copy, multi-device) use shared helpers |
| 64 | Duplicated logic across 30+ locations (architectural) | FIXED | YES | `aaffc0f` | Created src/gui/shared_helpers.py with 5 shared functions; eliminated all duplication |
| 65 | Loading L/R profile from My Presets loses channel mode (shows as stereo) | FIXED | YES | `ec85fc5` | _on_profile_load_requested sets wizard state.channel_mode from profile before recall |
| 66 | FiltersPage: clicking "Import from REW File" after mode selection does nothing | FIXED | N/A | `32f0a44` | Redesigned: removed card+dialog; inline Stereo/L/R radio toggle + Browse buttons always visible |
| 67 | FiltersPage: re-navigating to page keeps stale file selections | FIXED | N/A | `32f0a44` | Page now uses simple toggle+browse pattern; clear_results resets state |
| 68 | Source page and other views too narrow (condensed, buttons clipped) | FIXED | N/A | `32f0a44` | Removed AlignHCenter from SourcePage outer layout; content expands to fill space |
| 69 | SecondaryWorkflowManager copy_preset_to_device hardcodes stereo | FIXED | YES | `32f0a44` | Added channel_mode parameter (default "stereo"); callers pass through |
| 70 | Duplicated backup JSON parsing in _do_undo and _do_undo_roomfit | FIXED | YES | `32f0a44` | Extracted parse_backup_filters() into shared_helpers; both undo paths use it |
| 71 | Dead code: _OptionCard, _DropZone, pull/REW card handlers in FiltersPage | FIXED | N/A | `32f0a44` | Removed entirely in FiltersPage rewrite |
| 72 | FiltersPage: No "Next" button in Stereo mode to proceed after returning to step | FIXED | YES | `edee68f` | Added unified "Next" button to both Stereo and L/R modes; enabled only when required files are selected |
| 73 | Stereo file import shown as L/R in Review due to stale channel_mode state | FIXED | YES | `edee68f` | _do_file_import now explicitly sets channel_mode="Stereo" before emitting peq_ready |
| 74 | Presets on Device "Copy to another device" only copies to first selected device (regression of #33) | FIXED | YES | `edee68f` | Replaced selected_devices[0] with iteration over all selected devices via _do_copy_presets_batch_multi |
| 75 | Review "Apply to multiple devices" always pushes to active PEQ (wrong for RoomFit) | FIXED | N/A | `edee68f` | Removed button entirely; "Copy to another device" in Presets on Device serves the same purpose correctly |
| 76 | Review "Copy to another source" replaced by multi-source selection in Source step | FIXED | N/A | `edee68f` | Source step now uses checkboxes (multi-select); push writes to all selected sources; removed Copy to another source button |
| 77 | Multi-source PEQ push: Undo doesn't restore all sources | FIXED | YES | `d6b9288` | _do_push now stores per-source backup paths; _do_undo_multi_source restores each source from its own backup |
| 78 | Copy to another device: status message says "N presets" when only 1 preset copied to N devices | FIXED | YES | `d6b9288` | Status now reads "1 preset(s) copied to 3 device(s)" reflecting actual items × devices |
| 79 | Copy to another device: L/R RoomFit profiles stored as Stereo on target | FIXED | YES | `d6b9288` | _do_copy_preset_to_device now passes channel_mode with filters_l/filters_r for L/R RoomFit |
| 80 | Dry Run mode: Push proceeds to device anyway, no dry-run acknowledgment in Push step | FIXED | YES | `d6b9288`, `bd5e86b` | Checks state.dry_run; for RoomFit advances twice (skips NAME_PROFILE) to reach PUSH page with dry-run result |
| 81 | "Compare with device" toggle does nothing (dead UI) | FIXED | N/A | `d6b9288` | Removed toggle, signal, and methods entirely; no functional comparison was implemented |
| 82 | My Saved Presets and Connect step still have narrow/condensed content layout | FIXED | N/A | `d6b9288` | Removed AlignHCenter from ConnectPage, ReviewPage, MyPresetsView outer layouts |
| 83 | File>Import/Export menu items do nothing; Help>About not wired | FIXED | N/A | `d6b9288` | Removed File>Import/Export (redundant with UI); wired Help>About with product description dialog |
| 84 | Help article needs update to reflect current UI after all bug fixes | FIXED | N/A | — | All 6 help articles rewritten: removed dead UI references (Compare toggle, FiltersPage cards, Pull from Device option), updated for multi-source, L/R export, toolbar actions, RoomFit flow |
| 85 | Diagnostics panel "Send" button does nothing (raw_command_requested not wired) | FIXED | YES | `9c6de2d`, `ff4597d`, `d1e2ce5`, `8499e83` | Thread-safe response; scrollable layout; caps auto-populated; log Refresh button widened |
| 86 | Connect step and My Saved Presets still narrow; row highlight misaligned in My Presets | FIXED | N/A | `9c6de2d`, `ff4597d` | Removed wrapper stretch centering; set explicit sizeHint height; set scanning widget minHeight |
| 87 | Sidebar preset/profile load doesn't work when wizard state is incomplete | FIXED | YES | `9c6de2d`, `ff4597d`, `d1e2ce5`, `8499e83`, `e386bfc` | QuickSetupDialog: checks completed_steps (not stale state); clears source on device re-select; marks all prior steps; navigates to Review |
| 88 | Initial device discovery times out (30s) in packaged app, then shows all 4 devices | FIXED | YES | — | Sequential mDNS→subnet scan + redundant enrichment took ~30s on cold start. Rewrote DiscoveryModule: parallel mDNS+subnet scan (1.5s grace), skip redundant getStatusEx for subnet results, progressive UI updates via on_found callback |
| 89 | Cancel button invisible in dark theme (UnsavedChangesDialog) | FIXED | NO | — | Removed hardcoded inline styles from Cancel button; uses ghost class from QSS theme |
| 90 | Settings screen paths not pre-populated; theme change + log buttons broken | FIXED | NO | — | _apply_settings now passes computed paths (get_log_dir, profile_repository.storage_root) when settings have empty defaults; theme wiring was already correct |
| 91 | Onboarding overlay uses hardcoded COLORS_LIGHT; text clipped in dark mode | FIXED | NO | — | Overlay now detects active theme and uses COLORS_DARK/COLORS_LIGHT dynamically; added minHeight to labels to prevent clipping |
| 92 | Pull from REW: L/R filters pushed to RoomFit profile result in empty/flat bands | OPEN | NO | — | Filters loaded correctly (11 after validation) but push may use PEQ path instead of RoomFit; diagnostic logging added — needs re-test to confirm flow_type at push time |
| 93 | Pull from REW: subsequent pull after preset load uses stale filters from preset | OPEN | NO | — | state.current_filters not updated correctly when switching between sidebar sources; diagnostic logging added for post-mortem |
| 94 | Connect step loses checkmark/context after RoomFit push via REW API | FIXED | NO | — | _mark_prior_steps_completed now explicitly marks CONNECT as completed when device is selected |
| 95 | Pull from REW: Quick Setup dialog shown unnecessarily when already at Filters step | FIXED | NO | — | _ensure_wizard_state_for_load now checks if user is at/past FILTERS step and skips dialog; PEQ_ONLY flow no longer asks for EQ_TYPE |
| 96 | Pull from REW: measurement picker not shown (REW returns dict-keyed response) | FIXED | NO | — | rew_http_client now handles dict-keyed measurement responses (keys "1", "2", ...) |
| 97 | Pull from REW: "Unknown filter type 'None'" error from REW API filters | FIXED | NO | — | Unified _TYPE_MAP handles all REW filter types; None/Modal/AllPass/L-T skipped; gain field reads "gaindB" |
| 98 | Push page shows stale DRY RUN content from previous dry run after real push | FIXED | NO | — | PushPage.reset() called on every PUSH step entry via _on_step_changed |
| 99 | Duplicated WiiM device identification logic in two modules | FIXED | YES | — | capability_prober and subnet_scanner had independent device lists with different entries and algorithms; unified into src/utils/device_identity.py |
| 100 | Hardware limit constants (gain/Q) duplicated in translator and GUI | FIXED | NO | — | Identical _GAIN_MIN/MAX, _Q_MIN/MAX defined independently in wiim_generator.py and shared_helpers.py; consolidated into src/models/constants.py (indirectly tested via clamping tests) |
| 101 | Band-param building logic repeated 4× in wiim_adapter.py | FIXED | NO | — | Manual loop building EQBand param dicts copy-pasted across _write_peq_batch, _write_peq_sequential, _write_peq_batch_lr, _write_peq_sequential_lr, and write_roomfit; extracted _flat_array_to_band_params() helper (indirectly tested via adapter write tests) |
| 102 | Two crash handlers overwriting each other (logging vs GUI) | FIXED | NO | — | install_crash_handler (logging/setup.py) and _crash_handler (main_window.py) both set sys.excepthook; GUI handler now flushes all log handlers for persistence (install_crash_handler never called in production; GUI handler not unit-testable without Qt) |
| 103 | Dead PEQBand model defined but never used in production code | FIXED | YES | — | PEQBand in models/peq.py had validators and was exported in __all__ but never instantiated anywhere; removed entirely |
| 104 | Lazy `import json` (3×) inside methods in capability_prober.py | FIXED | YES | — | stdlib module imported at function scope for no reason; moved to module-level import |
