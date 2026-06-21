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
| 18 | Filter table too narrow (400px cap), only 3 columns visible | FIXED | N/A | `791f04a`, current | Removed max-width/centering, columns now stretch to fill available width |
| 19 | RoomFit mode: FiltersPage shows PEQ options instead of RoomFit UI | FIXED | NO | current | _on_eq_type_selected now calls set_roomfit_mode(True/False) |
| 20 | Presets on Device view shows nothing when navigated to | FIXED | NO | current | Added _load_device_presets() trigger on navigation + _do_list_presets async |
| 21 | Sidebar collapsed mode shows blank buttons (no icons) | FIXED | N/A | current | Added emoji icons as placeholders for collapsed mode |
| 22 | Presets on Device shows PEQ presets but no RoomFit profiles | FIXED | NO | current | _do_list_presets now fetches both PEQ + RoomFit and populates both sections |
| 23 | RoomFit FiltersPage profile dropdown is empty | FIXED | NO | current | Added _do_list_roomfit_profiles async fetch when EQ type "roomfit" is selected |
| 24 | Presets on Device: Export/Save/Load buttons do nothing (no signal wired) | FIXED | NO | current | Fully implemented: Export reads preset then writes REW file; Save creates local Profile; Load reads preset into Review |
| 25 | Presets on Device: Can select PEQ + RoomFit items simultaneously | FIXED | NO | current | Added mutual exclusion: selecting in one list clears the other |
| 26 | Presets on Device: Copy to Another Device doesn't actually write preset to target | FIXED | NO | current | Reads filters, connects to target, writes via SafeWrite, saves as named preset; shows success/failure status |
| 27 | RoomFit FiltersPage: No way to progress after selecting profile from dropdown | FIXED | NO | current | Wired roomfit_profile_selected; reads profile with L/R mode handling; advances to Review |
| 28 | Review page shows single 24-row table for L/R instead of separate L/R tabs | OPEN | NO | — | _on_peq_ready uses set_filters() for all modes; should use set_lr_filters() for L/R |
| 29 | Export as REW: L/R mode creates single file with 10 bands instead of two files | OPEN | NO | — | Export logic doesn't branch on channel_mode; needs to generate two files for L/R |
| 30 | Export as REW: file doesn't get .txt extension when not typed by user | OPEN | NO | — | QFileDialog doesn't auto-append extension on some platforms |
| 31 | Save to My Presets: no visible result after processing, nothing in My Presets | OPEN | NO | — | Save may succeed but no UI refresh of MyPresetsView; also check if save actually writes |
| 32 | Copy to Another Device: status message not shown long enough to read | OPEN | NO | — | Success banner auto-dismisses too quickly or gets cleared by finish_operation |
| 33 | Copy to Another Device: only pushes to first device when multiple selected | OPEN | NO | — | Loop only processes first item or sequential calls clobber each other |
| 34 | Copy to Another Device: RoomFit profile saved as PEQ on target (wrong type) | OPEN | NO | — | Copy logic doesn't branch on preset_type for target save method |
| 35 | Source page shows all canonical sources regardless of device model | OPEN | NO | — | Should filter based on device model + discovered sources with custom EQ |
| 36 | WiiM Mini shows RoomFit in EQ Type despite not supporting it | OPEN | NO | — | Should check roomfit_level and hide RoomFit option when level < 2 |
