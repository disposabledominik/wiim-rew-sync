# AGENTS.md

Compact instructions for the WiiM-REW-Sync repository.

## Environment & Tooling
- **Language:** Python 3.12+
- **Environment:** WSL2 Ubuntu (Linux). Run commands directly (no `wsl` prefix).
- **GUI Framework:** PySide6
- **Test Runner:** `pytest` (with `pytest-qt` for GUI, `pytest-asyncio`, `respx` for HTTP, `hypothesis` for PBT)
- **Lint/Format:** `ruff`
- **Type Checking:** `mypy` (strict for `src/translator/` and `src/models/`, but ideally all files in `src/` should be clean)

## Verification Commands
Run these from the project root (use `timeout=60000` for task execution):
- **Targeted Test:** `python3 -m pytest src/tests/test_<module>.py -v --no-cov`
- **Lint:** `python3 -m ruff check .`
- **Type Check:** `python3 -m mypy .`
- **Full Suite (Gate):** `python3 -m pytest --no-header -q` (Expect ~25min; timeouts are frequent but acceptable if targeted tests pass)

## Testing Quirks
- **Execution Strategy:** Only run tests relevant to your changes. Full suite runs are very slow; `pytest-cov` parallel database combination causes `ERROR` artifacts in WSL — ignore these, verify only the pass/fail summary.
- **GUI Tests:** Use `qtbot` and `unittest.mock.AsyncMock`. Mock `AsyncBridge`; do not perform real network calls.
- **Warnings:** Mocked async coroutines trigger `RuntimeWarning`; explicitly ignored in `pyproject.toml`.
- **Caplog:** Our loggers have `propagate=False`. For tests, wrap in `try/finally` setting `propagate=True`.
- **Regression:** `src/tests/test_smoke_regression_wizard.py` is the primary reference.

## Architecture Quirks
- **Async GUI:** Heavy reliance on `PySide6` signals/slots. Logic uses `asyncio`.
- **Core Packages:** `src/translator/` and `src/models/` are strict-typed, high coverage (>90%).
- **Hooks:** Do NOT modify `scripts/*.bat` or `.sh` files.
- **Floating Point:** Use `src/utils/fp_compare.py` for comparisons.

## Implementation Rules
- **No `assert` in prod:** (S101) Use custom exceptions in `src/models/errors.py`.
- **Async Adapters:** Inject `WiiMHttpClient`. Use `AsyncMock` for testing.
- **Hypothesis:** Imports must be at the top level.
- **Parallelism:** Collision-check before parallel tasks. If modifying the same file or shared test module, run sequentially.
- **Common Pitfalls:** No unused imports (F401), use `dict[str, object]` for untyped dicts, `httpx` exception names (`TimeoutException`, `ConnectError`).
- **Unit tests for every new feature or bugfix** Refer to and update `docs/smoke_test_issues.md` with every detected issue, and after every fix/update.

## External File Loading
 
CRITICAL: When you encounter a file reference (e.g., @rules/general.md), use your Read tool to load it on a need-to-know basis. They're relevant to the SPECIFIC task at hand.
 
Instructions:
 
- Do NOT preemptively load all references - use lazy loading based on actual need
- When loaded, treat content as mandatory instructions that override defaults
- Follow references recursively when needed

## Development Guidelines
For information about the project: @.kiro/product.md
For project structure: @.kiro/structure.md

## General Guidelines
 
Read the following file immediately as it's relevant to all workflows: @.kiro/rules.md