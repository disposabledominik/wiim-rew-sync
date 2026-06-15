# QA Sign-off Report

**Date:** 2026-06-15
**Version:** 0.1.0
**Environment:** WSL2 Ubuntu, Python 3.12.3

---

## 1. Test Suite Results

| Metric | Result |
|--------|--------|
| Total tests | 470 |
| Passed | 470 |
| Failed | 0 |
| `src/translator/` coverage | 96.52% (required: ≥ 90%) |
| Coverage gate | **PASSED** |

### Coverage Breakdown (src/translator/)

| Module | Stmts | Miss | Branch | Cover |
|--------|-------|------|--------|-------|
| `__init__.py` | 32 | 5 | 0 | 84% |
| `_warnings.py` | 9 | 0 | 0 | 100% |
| `rew_generator.py` | 35 | 0 | 6 | 100% |
| `rew_parser.py` | 194 | 3 | 72 | 98% |
| `schema_migrator.py` | 30 | 3 | 16 | 87% |
| `wiim_generator.py` | 52 | 0 | 18 | 100% |
| `wiim_parser.py` | 20 | 0 | 4 | 100% |
| **TOTAL** | **372** | **11** | **116** | **96.52%** |

---

## 2. Lint Results (ruff)

```
$ python3 -m ruff check src/
All checks passed!
```

**Result: PASSED** — Zero errors, zero warnings.

---

## 3. Type Check Results (mypy)

```
$ python3 -m mypy src/translator src/models
Success: no issues found in 13 source files

$ python3 -m mypy src/gui/dialogs/error_dialog.py
Success: no issues found in 1 source file
```

**Result: PASSED** — Zero errors on strict-mode modules (translator, models) and GUI error dialog.

---

## 4. Dependency Vulnerability Audit (pip-audit)

**Tool:** pip-audit 2.10.1

### Summary

Found 53 known vulnerabilities in 15 packages. **None are in project direct dependencies.**

### Project Direct Dependencies (all clean)

| Package | Version | Vulnerabilities |
|---------|---------|----------------|
| httpx | 0.28.1 | 0 |
| pydantic | 2.13.4 | 0 |
| PySide6 | 6.11.1 | 0 |
| zeroconf | 0.149.16 | 0 |
| hypothesis | 6.155.2 | 0 |
| pytest | 9.0.3 | 0 |
| ruff | 0.15.16 | 0 |
| mypy | 2.1.0 | 0 |
| respx | 0.23.1 | 0 |

### System-level Packages with Vulnerabilities (not project dependencies)

| Package | Version | CVE Count | Notes |
|---------|---------|-----------|-------|
| certifi | 2023.11.17 | 2 | System CA bundle |
| cryptography | 41.0.7 | 7 | System OpenSSL bindings |
| pip | 24.0 | 5 | Package installer |
| setuptools | 68.1.2 | 3 | Build tool |
| urllib3 | 2.0.7 | 6 | System HTTP lib |
| jinja2 | 3.1.2 | 5 | System template engine |
| pyjwt | 2.7.0 | 7 | System auth lib |
| requests | 2.31.0 | 3 | System HTTP lib |
| twisted | 24.3.0 | 3 | System networking |
| pyopenssl | 23.2.0 | 2 | System SSL |
| Others | Various | 10 | wheel, idna, pyasn1, pygments, configobj |

**Verdict:** No action required for distribution. All vulnerabilities are in system-level packages installed by the OS (Ubuntu 24.04), not bundled with the application. The PyInstaller single-file executable will include only project direct dependencies (httpx, pydantic, PySide6, zeroconf) which are all clean.

---

## 5. QA Scenarios Assessment

### Software-Testable Scenarios (Covered by Test Suite)

| # | Scenario | Test Coverage |
|---|----------|---------------|
| 1 | REW import → Canonical (no data loss) | `test_rew_parser.py`, `test_translator.py` (PBT round-trip) |
| 2 | Frequency > 22000 Hz → validation error | `test_rew_parser.py::TestParseFileFrequencyError` |
| 3 | Device offline → graceful timeout | `test_capability_prober.py::TestConnectionFailure`, `test_wiim_http.py` |
| 4 | Push → backup saved | `test_safe_write.py::TestSuccessPath::test_success_calls_backup` |
| 5 | Read-back variance > 0.05dB → rollback | `test_safe_write.py::TestVerifyFailureRollbackSuccess` |
| 6 | Verification passes → success, no rollback | `test_safe_write.py::TestSuccessPath` |
| 7 | Rollback restores original PEQ | `test_safe_write.py::TestVerifyFailureRollbackSuccess::test_rollback_writes_original_back` |
| 8 | WiiM Mini capabilities | `test_capability_prober.py::TestWiiMDeviceDetection::test_wiim_mini_detected_correctly` |
| 9 | Batch-write bypass | `test_wiim_adapter.py::TestWritePeqBatch` |
| 10 | Dry Run (no network writes) | `test_cli.py::test_dry_run_import_valid` |
| 12 | REW export format correctness | `test_rew_generator.py` (full format validation) |
| 13 | Log rotation (10MB, 5 archives) | `test_logging.py::TestHandlerConfiguration` |
| 14 | Schema migration on profile load | `test_schema_migrator.py`, `test_profile_repository.py::TestSchemaMigration` |
| 15 | L/R channel pull → both models | `test_wiim_adapter.py::TestReadPeqLR` |
| 16 | Invalid HTTP response → error logged | `test_wiim_http.py::test_http_500_raises_wiim_response_error` |
| 22 | 0Hz/OFF filter → band disabled | `test_wiim_generator.py::TestModeMapping::test_off_maps_to_mode_negative_1` |
| 24 | No network → app opens, profile library works | `test_profile_repository.py` (filesystem only) |
| 25 | Rollback failure → critical error | `test_safe_write.py::TestRollbackFailure` |
| 28 | >10 bands → truncation warning | `test_rew_generator.py::TestMaxFilters`, `test_cli.py::test_dry_run_import_surfaces_range_warning` |
| 30 | L/R profile on Stereo device → mode adaptation | `test_safe_write.py::TestChannelModeAdaptation` |

### Hardware-Required Scenarios (Cannot Be Automated)

| # | Scenario | Reason |
|---|----------|--------|
| 11 | Device rebooting during write → safe abort | Requires physical device power cycle |
| 17 | REW API measurement selection | Requires running REW instance |
| 18 | RoomFit Level 1 → UI shows "Active", buttons disabled | Requires specific firmware + GUI |
| 19 | RoomFit Level 4 → full read/export/write | Requires compatible device |
| 20 | Multiroom slave write targets specific device | Requires multiroom group |
| 21 | Identical device names → distinct by IP/MAC | Requires 2+ physical devices |
| 23 | Diagnostics mode → raw HTTP visible | Requires live network traffic |
| 26 | WiiM Mini → 10 bands, no RoomFit tab | Requires Mini + GUI |
| 27 | Amp Pro/Ultra/Sound capabilities match Ultra | Requires specific hardware |
| 29 | Source selector from InputList | Requires device with multiple inputs |

**Note:** CLI hardware validation was completed 2026-06-14 (Task 32 phase gate). Scenarios 4, 5, 6, 7, 9 were confirmed against real WiiM devices during that session.

---

## 6. Overall Verdict

| Check | Status |
|-------|--------|
| Test suite (470 tests) | ✅ PASSED |
| Translator coverage ≥ 90% | ✅ 96.52% |
| Lint (ruff) | ✅ Zero errors |
| Type check (mypy) | ✅ Zero errors |
| pip-audit (direct deps) | ✅ No vulnerabilities |
| Hardware QA | ⏳ Pending manual execution |

### Final Verdict

**Software QA: PASSED.**
**Hardware QA: Pending — requires real WiiM device(s) for scenarios 11, 17-21, 23, 26-27, 29.**

All automated quality gates are green. The application is ready for hardware validation and subsequent distribution packaging.
