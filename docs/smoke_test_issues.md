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
