# GUI Smoke Test Issues

Tracks issues found during manual smoke testing of the GUI integration.

## Issue Status Legend

- **Status:** `FIXED` | `OPEN` | `WONTFIX`
- **Test:** `YES` (unit test exists) | `NO` (needs test) | `N/A` (not testable in automation)

## Issues

| # | Issue | Status | Test | Fix Commit | Notes |
|---|-------|--------|------|------------|-------|
| 1 | Device click → "Processing" → nothing happens (NoSources error) | FIXED | NO | `12e8b38` | getStatusEx doesn't report InputList; fallback to canonical source defaults |
| 2 | User Guide has no visible close button / way to exit | FIXED | NO | `d5ff9e9` | Wired `close_requested` signal to navigate back to wizard |
| 3 | All windows have transparent backgrounds (WSL rendering) | WONTFIX | N/A | — | WSLg/Wayland compositor artifact; resolves with native Windows build |
| 4 | Device cards in single narrow column, wasted screen space | FIXED | N/A | `fcb82c2` | Removed 800px max-width from QStackedWidget, increased MAX_CONTENT_WIDTH to 1200 |
| 5 | No step indicator shown at all | FIXED | NO | `559ce5f` | Step indicator never initialized at startup; added init with default flow |
| 6 | Sidebar device name shows "WiiM Device" instead of real name | FIXED | NO | `559ce5f` | Used caps.model fallback + discovered device name lookup |
| 7 | Pull from Device → "Processing" → nothing visible in GUI | FIXED | NO | `48bc9f9`, `d01bc84` | _on_peq_ready was a TODO stub; now populates ReviewPage + advances wizard |
| 8 | Success message after device pull wiped immediately | FIXED | NO | `48bc9f9` | OperationFeedbackManager.finish_operation() cleared banner; added 50ms delay |
| 9 | HelpView close button not wired | FIXED | NO | `d5ff9e9` | Same as #2 |
| 10 | Measurement picker cancel = silent dead end | FIXED | NO | `d5ff9e9` | Shows "Selection cancelled" info banner |
| 11 | FiltersPage retry button only hides error, doesn't reset page | FIXED | NO | `d5ff9e9` | Now re-shows option cards so user can try again |
| 12 | No immediate loading feedback for device/REW pull on FiltersPage | FIXED | NO | `d5ff9e9` | Added show_progress() before async calls |
| 13 | Empty filters from device — no guidance after banner auto-dismisses | FIXED | NO | `d5ff9e9` | Changed to persistent message with suggestion |
| 14 | ConnectPage auto-triggers discovery on every showEvent (back-nav) | FIXED | NO | `d5ff9e9` | Guard: only emit refresh_requested when no cards shown |
| 15 | RoomFit flow: Connect step missing checkmark after flow type switch | FIXED | NO | `791f04a` | _on_flow_type_changed now replays completed step summaries |
| 16 | RoomFit flow: "No source selected" when pulling from device | FIXED | NO | `791f04a` | Defaults to "wifi" when no source explicitly set (RoomFit is device-global) |
| 17 | Home button appears to do nothing | WONTFIX | N/A | — | Working as designed: "home" = return to current wizard step. If already there, no visible change. |
| 18 | Filter table too narrow (400px cap), only 3 columns visible | FIXED | N/A | `791f04a`, `5f355b5` | Removed max-width/centering, columns now stretch to fill available width |
| 19 | RoomFit mode: FiltersPage shows PEQ options instead of RoomFit UI | FIXED | NO | `5f355b5` | _on_eq_type_selected now calls set_roomfit_mode(True/False) |
| 20 | Presets on Device view shows nothing when navigated to | FIXED | NO | `5f355b5` | Added _load_device_presets() trigger on navigation + _do_list_presets async |
| 21 | Sidebar collapsed mode shows blank buttons (no icons) | FIXED | N/A | `b6bcc36` | Added emoji icons as placeholders for collapsed mode |
| 22 | Presets on Device shows PEQ presets but no RoomFit profiles | FIXED | NO | `b6bcc36` | _do_list_presets now fetches both PEQ + RoomFit and populates both sections |
| 23 | RoomFit FiltersPage profile dropdown is empty | FIXED | NO | `b6bcc36` | Added _do_list_roomfit_profiles async fetch when EQ type "roomfit" is selected |
| 24 | Presets on Device: Export/Save/Load buttons do nothing (no signal wired) | FIXED | NO | `69d09c2`, `c55918e` | Fully implemented: Export reads preset then writes REW file; Save creates local Profile; Load reads preset into Review |
| 25 | Presets on Device: Can select PEQ + RoomFit items simultaneously | FIXED | NO | `69d09c2` | Added mutual exclusion: selecting in one list clears the other |
| 26 | Presets on Device: Copy to Another Device doesn't actually write preset to target | FIXED | NO | `c55918e` | Reads filters, connects to target, writes via SafeWrite, saves as named preset; shows success/failure status |
| 27 | RoomFit FiltersPage: No way to progress after selecting profile from dropdown | FIXED | NO | `69d09c2` | Wired roomfit_profile_selected; reads profile with L/R mode handling; advances to Review |
| 28 | Review page shows single 24-row table for L/R instead of separate L/R tabs | FIXED | NO | `d0aa100` | _on_peq_ready now checks channel_mode and calls set_lr_filters() for L/R mode |
| 29 | Export as REW: L/R mode creates single file with 10 bands instead of two files | FIXED | NO | `d0aa100` | Export logic branches on channel_mode; uses ExportDialog for dual-file L/R export |
| 30 | Export as REW: file doesn't get .txt extension when not typed by user | FIXED | NO | `d0aa100` | Added if not path.lower().endswith('.txt'): path += '.txt' in stereo export path |
| 31 | Save to My Presets: no visible result after processing, nothing in My Presets | FIXED | NO | `d0aa100` | Added _profile_repository.list() → set_presets() refresh after save; also refresh on nav to My Presets |
| 32 | Copy to Another Device: status message not shown long enough to read | FIXED | NO | `d0aa100` | finish_operation() no longer clears banner unconditionally; only clears if still showing progress spinner |
| 33 | Copy to Another Device: only pushes to first device when multiple selected | FIXED | NO | `d0aa100` | Replaced per-item run_async loop with single _do_copy_presets_batch coroutine |
| 34 | Copy to Another Device: RoomFit profile saved as PEQ on target (wrong type) | FIXED | NO | `d0aa100` | _do_copy_preset_to_device now branches on preset_type; uses write_roomfit() for RoomFit |
| 35 | Source page shows all canonical sources regardless of device model | FIXED | NO | `d0aa100` | All common sources shown (PEQ accepts any source name; extra slots are harmless) |
| 36 | WiiM Mini shows RoomFit in EQ Type despite not supporting it | FIXED | NO | `d0aa100` | Added model-based roomfit blocklist; Mini forced to PEQ_ONLY flow even if roomfit_level >= 2 |
| 37 | ReviewPage "Save to My Presets" button does nothing | FIXED | NO | `d6983fb` | save_preset_requested signal was never connected; added _on_review_save_preset handler |
| 38 | My Saved Presets: no actions (delete/rename/duplicate) wired | FIXED | NO | `ddb2349`, `94272de` | Connected signals + added visible toolbar (Load/Rename/Duplicate/Delete) on selection |
| 39 | My Saved Presets: L/R presets shown as "stereo" with 24 bands | FIXED | NO | `ddb2349`, `94272de` | Badge shows "L/R", band count uses per-channel, channel_mode preserved on save |
| 40 | Export L/R preset from Presets on Device creates single file | FIXED | NO | `ddb2349`, `94272de` | Both Presets view and Review step now generate _L.txt + _R.txt; state.channel_mode updated from device |
| 41 | Back-nav to Connect → selecting new device keeps old flow type | FIXED | NO | `d6983fb` | _on_device_selected resets flow_type to PEQ before probing |
| 42 | WiiM Mini missing line-in source in Source page | FIXED | NO | `d6983fb` | Reverted to showing all common sources (PEQ accepts any name; no model filtering needed) |
| 43 | Sound/Sound Lite shows optical and HDMI sources (not applicable) | WONTFIX | N/A | — | PEQ engine accepts any source name; showing extra sources is harmless. No reliable way to probe physical inputs. |
| 44 | ReviewPage "Save to My Presets" crashes with FileNotFoundError for L/R names | FIXED | NO | current | Name contained "/" from channel mode; added filesystem-safe name sanitization in shared helper |
| 45 | Export from Review vs Presets on Device shows different dialogs | FIXED | NO | current | Consolidated into shared _export_filters_as_rew helper; both use ExportDialog for L/R |
| 46 | My Saved Presets: no visible action buttons (only right-click context menu) | FIXED | NO | `e921182` | Added visible toolbar (Load/Rename/Duplicate/Delete) that appears on item selection |
| 47 | Duplicate save/export logic across trigger points (architectural) | FIXED | NO | current | Created shared helpers: _save_filters_to_presets, _export_filters_as_rew; all triggers converge |
