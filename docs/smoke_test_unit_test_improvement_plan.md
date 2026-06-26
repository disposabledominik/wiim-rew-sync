# Smoke Test Unit Test Improvement Plan

**Date:** 2026-06-26
**Scope:** Analysis of 90 smoke regression tests covering issues in `docs/smoke_test_issues.md`

---

## Executive Summary

- **Total smoke regression tests:** ~90 (covering 90 issues marked FIXED | YES)
- **Weak tests identified:** 21 (23%)
- **Robust tests:** ~69 (77%)
- **Overall quality rating:** 6.5/10

The smoke regression tests have a solid foundation with clear naming, appropriate mocking, and focus on specific fix behaviors. However, 21 tests are too shallow—checking only method signatures, signal existence, or using weak assertions. These provide minimal regression protection and should be strengthened.

---

## Weak Tests by Category

### 1. Signature-Only Tests (3 tests)

These tests only verify that a method signature accepts a parameter, but don't test that the parameter is actually used correctly. They won't catch regressions if the parameter exists but isn't used.

#### Test 1: `test_issue58_apply_to_devices_accepts_channel_mode`
- **Location:** `src/tests/test_smoke_regression_operations.py:155-162`
- **Issue:** #58 - Multi-device push passes channel_mode through
- **Current behavior:** Uses `inspect.signature()` to check parameter exists
- **Problem:** Doesn't verify channel_mode is actually passed to the write operations
- **Priority:** HIGH
- **Improvement:** Add a test that calls `apply_to_devices` with channel_mode and verifies it's passed to the underlying adapter write methods

#### Test 2: `test_issue34_copy_branches_on_preset_type`
- **Location:** `src/tests/test_smoke_regression_operations.py:699-706`
- **Issue:** #34 - _do_copy_preset_to_device branches on preset_type
- **Current behavior:** Uses `inspect.signature()` to check parameter exists
- **Problem:** Doesn't test the actual branching logic (PEQ vs RoomFit)
- **Priority:** HIGH
- **Improvement:** Add two test cases: one with `preset_type="PEQ"` and one with `preset_type="RoomFit"`, verify different code paths are taken (e.g., different adapter methods called)

#### Test 3: `test_issue69_copy_preset_to_device_has_channel_mode`
- **Location:** `src/tests/test_smoke_regression_operations.py:793-799`
- **Issue:** #69 - SecondaryWorkflowManager.copy_preset_to_device accepts channel_mode
- **Current behavior:** Uses `inspect.signature()` to check parameter exists
- **Problem:** Doesn't verify channel_mode is used in the copy operation
- **Priority:** HIGH
- **Improvement:** Call `copy_preset_to_device` with channel_mode and verify it's passed to the target device write operation

---

### 2. Existence-Only Tests (11 tests)

These tests only check that signals, methods, or attributes exist, but don't verify they're wired to handlers or that the wiring works correctly.

#### Test 4: `test_issue24_presets_device_export_connected`
- **Location:** `src/tests/test_smoke_regression_operations.py:450-452`
- **Issue:** #24 - PresetsDeviceView export_requested signal is connected
- **Current behavior:** `assert hasattr(view, "export_requested")`
- **Problem:** Doesn't verify signal is connected to a handler
- **Priority:** HIGH
- **Improvement:** Mock the handler, emit the signal, verify handler is called

#### Test 5: `test_issue24_presets_device_save_connected`
- **Location:** `src/tests/test_smoke_regression_operations.py:454-456`
- **Issue:** #24 - PresetsDeviceView save_to_my_presets signal is connected
- **Current behavior:** `assert hasattr(view, "save_to_my_presets")`
- **Problem:** Doesn't verify signal is connected to a handler
- **Priority:** HIGH
- **Improvement:** Mock the handler, emit the signal, verify handler is called

#### Test 6: `test_issue24_presets_device_load_connected`
- **Location:** `src/tests/test_smoke_regression_operations.py:458-460`
- **Issue:** #24 - PresetsDeviceView load_into_editor signal is connected
- **Current behavior:** `assert hasattr(view, "load_into_editor")`
- **Problem:** Doesn't verify signal is connected to a handler
- **Priority:** HIGH
- **Improvement:** Mock the handler, emit the signal, verify handler is called

#### Test 7: `test_issue37_review_save_preset_signal_connected`
- **Location:** `src/tests/test_smoke_regression_operations.py:500-505`
- **Issue:** #37 - ReviewPage save_preset_requested signal is connected
- **Current behavior:** Checks signal and handler exist separately
- **Problem:** Doesn't verify they're connected
- **Priority:** HIGH
- **Improvement:** Emit the signal and verify `_on_review_save_preset` is called

#### Test 8: `test_issue53_push_page_export_connected`
- **Location:** `src/tests/test_smoke_regression_operations.py:509-511`
- **Issue:** #53 - PushPage export_requested signal is connected
- **Current behavior:** `assert hasattr(window._push_page, "export_requested")`
- **Problem:** Doesn't verify signal is connected to a handler
- **Priority:** HIGH
- **Improvement:** Mock the handler, emit the signal, verify handler is called

#### Test 9: `test_issue53_push_page_save_preset_connected`
- **Location:** `src/tests/test_smoke_regression_operations.py:513-515`
- **Issue:** #53 - PushPage save_preset_requested signal is connected
- **Current behavior:** `assert hasattr(window._push_page, "save_preset_requested")`
- **Problem:** Doesn't verify signal is connected to a handler
- **Priority:** HIGH
- **Improvement:** Mock the handler, emit the signal, verify handler is called

#### Test 10: `test_issue38_my_presets_view_has_toolbar`
- **Location:** `src/tests/test_smoke_regression_operations.py:710-716`
- **Issue:** #38 - My Saved Presets view has toolbar buttons
- **Current behavior:** Checks attributes exist with `hasattr()` or checks
- **Problem:** Doesn't verify toolbar is visible or buttons work
- **Priority:** MEDIUM
- **Improvement:** Verify toolbar widget exists, is visible, and buttons are clickable/enabled

#### Test 11: `test_issue42_source_page_has_set_sources`
- **Location:** `src/tests/test_smoke_regression_operations.py:734-737`
- **Issue:** #42 - Source page receives all common sources including line-in
- **Current behavior:** `assert hasattr(page, "set_sources")`
- **Problem:** Doesn't test that set_sources actually populates the UI
- **Priority:** MEDIUM
- **Improvement:** Call `set_sources` with a list, verify checkboxes are created and have correct labels

#### Test 12: `test_issue48_save_filters_to_presets_callable`
- **Location:** `src/tests/test_smoke_regression_operations.py:741-743`
- **Issue:** #48 - Preset save uses thread-safe pattern
- **Current behavior:** `assert callable(window._save_filters_to_presets)`
- **Problem:** Doesn't test the thread-safety or that it actually saves
- **Priority:** MEDIUM
- **Improvement:** Call the method with test data, verify profile is saved to repository

#### Test 13: `test_issue50_source_page_provides_sources`
- **Location:** `src/tests/test_smoke_regression_operations.py:784-789`
- **Issue:** #50 - Copy to another source reads from SourcePage source list
- **Current behavior:** Checks `set_sources` and `_source_checkboxes` exist
- **Problem:** Doesn't test that copy operation actually reads from these
- **Priority:** MEDIUM
- **Improvement:** Set up source checkboxes with selections, call copy operation, verify it uses the selected sources

#### Test 14: `test_issue85_diagnostics_raw_command_connected`
- **Location:** `src/tests/test_smoke_regression_operations.py:937-939`
- **Issue:** #85 - Diagnostics panel raw_command_requested signal is connected
- **Current behavior:** `assert hasattr(window._diagnostics_panel, "raw_command_requested")`
- **Problem:** Doesn't verify signal is connected to handler
- **Priority:** MEDIUM
- **Improvement:** Emit the signal, verify `_on_raw_command_requested` is called

---

### 3. Weak/No Assertions (5 tests)

These tests have minimal or no assertions, providing little regression protection.

#### Test 15: `test_issue10_picker_cancel_shows_info`
- **Location:** `src/tests/test_smoke_regression_operations.py:615-620`
- **Issue:** #10 - Measurement picker cancel shows info banner
- **Current behavior:** Only checks `show_info` is callable
- **Problem:** Doesn't test cancel behavior or that banner actually shows
- **Priority:** HIGH
- **Improvement:** Simulate picker cancel, verify banner shows "Selection cancelled" message

#### Test 16: `test_issue11_filters_page_has_retry_mechanism`
- **Location:** `src/tests/test_smoke_regression_operations.py:624-628`
- **Issue:** #11 - FiltersPage retry shows option cards
- **Current behavior:** Checks for `show_error` or `clear_results` methods
- **Problem:** Doesn't test the retry mechanism actually works
- **Priority:** HIGH
- **Improvement:** Simulate error state, call retry method, verify option cards are shown

#### Test 17: `test_issue12_device_pull_shows_progress`
- **Location:** `src/tests/test_smoke_regression_operations.py:632-639`
- **Issue:** #12 - Progress shown immediately before async call
- **Current behavior:** `assert mock_prog.called or window._bridge.run_async.called`
- **Problem:** Weak "or" assertion - doesn't verify progress is shown first
- **Priority:** MEDIUM
- **Improvement:** Verify progress is shown before run_async is called (use call order verification)

#### Test 18: `test_issue13_empty_filters_shows_persistent_message`
- **Location:** `src/tests/test_smoke_regression_operations.py:643-654`
- **Issue:** #13 - Empty filters shows persistent guidance
- **Current behavior:** No assertion, just checks no crash
- **Problem:** No verification that message is shown
- **Priority:** MEDIUM
- **Improvement:** Add assertion that guidance message is displayed (may need to handle QTimer-based display)

#### Test 19: `test_issue32_finish_clears_only_progress`
- **Location:** `src/tests/test_smoke_regression_operations.py:658-671`
- **Issue:** #32 - finish_operation only clears if still showing progress
- **Current behavior:** Conditional assertion that might not execute
- **Problem:** Complex conditional logic makes test fragile
- **Priority:** MEDIUM
- **Improvement:** Simplify to two explicit test cases: one with progress (should clear), one without (should not clear)

---

### 4. Test-Description Mismatch (1 test)

#### Test 20: `test_issue92_lr_filter_splitting`
- **Location:** `src/tests/test_smoke_regression_operations.py:985-1000`
- **Issue:** #92 - Pull from REW: L/R filters pushed to RoomFit profile result in empty/flat bands
- **Current behavior:** Tests `split_lr_filters` helper function
- **Problem:** Issue description states fix was storing explicit `filters_l/filters_r` in `WizardState`, but test only tests the helper
- **Priority:** HIGH
- **Improvement:** Add test that verifies WizardState stores explicit filters_l/filters_r when L/R filters are loaded, not just the split logic

---

### 5. Test Name Mismatch (1 test)

#### Test 21: `test_issue60_name_profile_populated_on_navigation`
- **Location:** `src/tests/test_smoke_regression_operations.py:531-536`
- **Issue:** #60 - NAME_PROFILE step populates existing profile list
- **Current behavior:** Test name is `test_issue60_name_profile_populated_on_navigation`
- **Problem:** Referenced as `test_issue60_name_profile_populated` in smoke_test_issues.md
- **Priority:** LOW
- **Improvement:** Update smoke_test_issues.md to match actual test name

---

## Additional Observations

### Implementation Detail Coupling

Several tests access private/internal attributes:
- `connect_page._device_cards` (line 148)
- `connect_page._source_checkboxes` (line 788)
- `filters_page._next_btn` (line 390)
- `filters_page._stereo_path` (line 397)

**Impact:** Fragile to refactoring; tests may break on implementation changes.
**Priority:** LOW
**Improvement:** Use public APIs where possible, or document that these are intentional white-box tests.

### Async Test Patterns

Some tests use `asyncio.run()` directly instead of `@pytest.mark.asyncio`:
- Lines: 215, 238, 271, 433, 571, 691, 856, 884, 922

**Impact:** Less idiomatic pytest-asyncio usage; may not integrate well with async fixtures.
**Priority:** LOW
**Improvement:** Replace `asyncio.run()` with `@pytest.mark.asyncio` decorator for consistency.

---

## Improvement Plan by Priority

### Priority 1 (HIGH) - Critical Regression Protection

**Estimated effort:** 4-6 hours

1. **Fix signature-only tests (3 tests)**
   - Add behavioral assertions to verify parameters are actually used
   - Tests: #58, #34, #69

2. **Fix signal connection tests (6 tests)**
   - Verify signals are wired to handlers by emitting and checking handler calls
   - Tests: #24 (3 tests), #37, #53 (2 tests)

3. **Fix weak assertion tests (2 tests)**
   - Add actual behavior verification for picker cancel and retry mechanism
   - Tests: #10, #11

4. **Fix test-description mismatch**
   - Add test for WizardState explicit filters_l/filters_r storage
   - Test: #92

### Priority 2 (MEDIUM) - Strengthen Existing Tests

**Estimated effort:** 3-4 hours

1. **Improve existence-only tests (5 tests)**
   - Add behavioral verification for toolbar, set_sources, copy operation
   - Tests: #38, #42, #48, #50, #85

2. **Fix weak/no assertion tests (3 tests)**
   - Add proper assertions for progress display, empty filters message, finish_operation
   - Tests: #12, #13, #32

### Priority 3 (LOW) - Code Quality and Consistency

**Estimated effort:** 1-2 hours

1. **Fix test name mismatch**
   - Update smoke_test_issues.md reference
   - Test: #60

2. **Reduce private attribute access**
   - Refactor tests to use public APIs where feasible
   - Multiple tests

3. **Standardize async test patterns**
   - Replace asyncio.run() with @pytest.mark.asyncio
   - Multiple tests

---

## Test Quality Rating by Category

| Category | Rating | Notes |
|----------|--------|-------|
| Wizard Flow Tests | 7/10 | Good coverage, some shallow tests |
| Push/Write Tests | 6/10 | Several signature-only tests |
| Import/Export Tests | 8/10 | Strong behavioral tests |
| Presets Tests | 6/10 | Many existence-only checks |
| Settings/UI Tests | 5/10 | Weakest - mostly existence checks |
| Shared Helpers Tests | 9/10 | Excellent - pure unit tests |

---

## Conclusion

The smoke regression test suite provides good coverage with clear test naming and appropriate mocking. The 21 weak tests identified should be strengthened to provide better regression protection. The HIGH priority improvements (11 tests) should be addressed first as they represent the most significant gaps in test coverage.

After implementing these improvements, the overall test quality rating should increase from **6.5/10** to approximately **8.5/10**.
