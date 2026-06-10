# Technology & Build

## Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| GUI | PySide6 (Qt 6, LGPL) |
| HTTP | httpx (async) |
| Data validation | pydantic v2 |
| Device discovery | zeroconf |
| Testing | pytest, hypothesis (PBT), respx (HTTP mocking), pytest-asyncio |
| Linting | ruff |
| Type checking | mypy (strict on `src/translator/` and `src/models/`) |
| Packaging | PyInstaller (single-file executable) |

## Development Environment

- **Shell:** WSL2 Ubuntu (Linux). All commands must be Linux-compatible. Never use Windows cmd or PowerShell syntax.
- **Python:** Use `python3` (not `python`). Use `pip3` or `python3 -m pip` for package management.
- **Virtual environment:** Activate with `source .venv/bin/activate`.
- **Path separators:** Use forward slashes (`/`). The IDE may show Windows paths but execution is Linux.

## Hooks (Kiro Agent Hooks)

Hooks execute in the **Windows cmd shell** (not WSL). Each hook calls a `.bat` file in `scripts/` which delegates to `scripts/hook_runner.sh` via `wsl bash <path>`.

| Hook | Batch file |
|------|-----------|
| Type-check | `scripts/hook_mypy.bat` |
| Lint | `scripts/hook_lint.bat` |
| Tests | `scripts/hook_test.bat` |

Architecture: `.kiro/hooks/*.hook` → `scripts/hook_*.bat` → `wsl bash scripts/hook_runner.sh <cmd>`

**IMPORTANT: `hook_runner.sh` always exits 0.** Kiro discards stdout when a hook exits non-zero. The runner prints error output normally and appends `>>> FAILED (exit code N) <<<` but returns 0 so Kiro displays it. Do NOT "fix" this to return the real exit code — it will break output capture.

### CRITICAL — DO NOT MODIFY

- **Never put bash variables (`$HOME`, `$PATH`) inside `.bat` files** — Windows expands them before WSL sees them, causing parse failures on paths with parentheses.
- **Never inline `bash -c "..."` in hook JSON** — quoting breaks across Windows/Linux boundary.
- **Never modify hook `.hook` files, `.bat` files, or `hook_runner.sh`** unless explicitly asked by the user.
- **Never change line endings on `.sh` files** — `.gitattributes` enforces LF but tools can still corrupt them.
- If a new hook is needed, create a new `.bat` + add a hook JSON pointing to it. Follow the existing pattern exactly.

## Common Commands

```bash
# Install (editable with dev deps)
pip3 install -e ".[dev]"

# Run tests (coverage enforced ≥90% on translator)
python3 -m pytest

# Lint
python3 -m ruff check src/

# Format
python3 -m ruff format src/

# Type check
python3 -m mypy src/

# Run the app (CLI entry point)
python3 -m src.cli.main
```

## Key Configuration (pyproject.toml)

- **ruff**: line-length 100, target py312, rules: E/W/F/I/B/C4/UP/ANN/S/RUF
- **mypy**: strict mode on `src.translator.*` and `src.models.*`; ignore PySide6/zeroconf/respx imports
- **pytest**: testpaths = `src/tests`, asyncio_mode = auto, coverage on `src/translator`
- **coverage**: branch coverage, fail_under = 90

## Code Style Conventions

- Type annotations on all public functions (enforced via ruff ANN rules and mypy)
- Docstrings on all modules and public classes/functions
- Imports sorted by isort (via ruff I rule)
- No `assert` in production code (S101 ignored only in tests)
- `from __future__ import annotations` for deferred evaluation
- Pydantic `BaseModel` with `field_validator` for domain models
- Custom exception classes in `src/models/errors.py`
- Floating-point comparisons always use tolerances (see `src/utils/fp_compare.py`)

## Parallel Task Execution Rule

When executing multiple tasks from the same wave in parallel:

- **If two or more tasks write to the same file** (e.g., multiple PBT tests targeting `test_translator.py`, or multiple tasks extending `conftest.py`), they MUST be batched into a single subagent call. Never dispatch them as separate parallel subagents — the last one to finish will overwrite the others.
- **Tasks writing to completely separate files** can be safely dispatched as parallel subagent calls.
- **Always verify after parallel execution** by running `python3 -m pytest --no-header -q` to confirm no content was lost.

## Task Completion Quality Gate

Every task is only complete when ALL of the following pass:

1. `python3 -m pytest --no-header -q` — all tests pass
2. `python3 -m ruff check src/` — zero lint errors
3. `python3 -m mypy src/translator src/models` — zero type errors on strict modules

If any step fails, fix the issues before marking the task done. Do not accumulate lint/type debt across waves.

## Task Dispatch Efficiency Rules

- **Do not read files just to check existence** before dispatching. Let the subagent handle missing files.
- **Keep subagent prompts concise.** Include: task ID, acceptance criteria, and known gotchas. Do not paste full design docs — pass them as contextFiles instead.
- **Commit after each wave, not after each task.** Unless the user explicitly asks for per-task commits.
- **Dispatch aggressively within a wave.** If tasks write to separate files, run them all in parallel — don't wait for one to finish before starting the next.
