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
- **CRITICAL: The execution shell is ALREADY Linux (WSL).** Do NOT prefix commands with `wsl`, `wsl bash -c`, or `bash -c`. Just run commands directly (e.g. `python3 -m pytest`, not `wsl bash -c "python3 -m pytest"`).
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

**NOTE on exit codes:** `pytest` exits with code 1 when tests fail — this is NORMAL, not a broken command. Read the output to identify which tests failed, fix them, and re-run. Do NOT pipe output to files, wrap in try/catch scripts, or use other workarounds. Just run the command directly and read the result.

**NOTE on coverage gate:** When running a SINGLE test file (e.g., `python3 -m pytest src/tests/test_wiim_adapter.py -v`), always add `--no-cov` to skip the coverage check. The 90% gate is only meaningful for the full test suite. Pattern:
- Single file: `python3 -m pytest src/tests/test_foo.py -v --no-cov`
- Full suite (final verification): `python3 -m pytest --no-header -q`

**NEVER do any of the following:**
- Do NOT check `python3 --version` — it's Python 3.12+, this is confirmed and will never change.
- Do NOT create temporary shell scripts to run single commands.
- Do NOT pipe test output to files and then read the files. Just run the command directly.
- Do NOT re-run `pip install -e ".[dev]"` unless a new dependency was added to pyproject.toml. The environment is already set up.
- Do NOT run `pytest`, `ruff`, or `mypy` as background processes. These complete in under 30 seconds — run them directly with `timeout=60000`.
- Do NOT add `sleep` commands to wait for output. If a command needs more time, increase the timeout parameter instead.

**Command timeout guidance:** Always use `timeout=60000` (60 seconds) for `pytest`, `ruff check`, and `mypy` calls. These commands always finish within 30s on this machine.

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

## Common Pitfalls (avoid these)

1. **Never use en-dash `–` or minus sign `−` in code.** Always use ASCII hyphen `-`. Ruff RUF001/RUF002/RUF003 will reject unicode dashes in strings, comments, and docstrings.

2. **Logger `propagate=False` breaks `caplog`.** Our logging setup disables propagation on `wiim_rew_sync.app`, `wiim_rew_sync.wiim_api`, and `wiim_rew_sync.rew_api`. To test logging with `caplog`, temporarily set `propagate=True` in a try/finally block:
   ```python
   logger = logging.getLogger("wiim_rew_sync.wiim_api")
   logger.propagate = True
   try:
       with caplog.at_level(logging.DEBUG, logger="wiim_rew_sync.wiim_api"):
           await some_operation()
       assert "expected message" in caplog.text
   finally:
       logger.propagate = False
   ```

3. **Do not leave unused imports.** Ruff F401 will catch them. Only import what you use. Run `python3 -m ruff check <file>` after writing to confirm.

4. **Dict type annotations require type args in strict modules.** Use `dict[str, object]` not `dict` in `src/translator/` and `src/models/` (mypy disallow_any_generics is enabled).

5. **`httpx` exceptions mapping:** `httpx.TimeoutException` (not `httpx.TimeoutError`), `httpx.ConnectError` (not `httpx.ConnectionError`). These differ from stdlib names.

## Parallel Task Execution Rule

When executing multiple tasks from the same wave in parallel:

- **If two or more tasks write to the same file** (e.g., multiple PBT tests targeting `test_translator.py`, or multiple tasks extending `conftest.py`), they MUST be batched into a single subagent call. Never dispatch them as separate parallel subagents — the last one to finish will overwrite the others.
- **Tasks writing to completely separate files** can be safely dispatched as parallel subagent calls.
- **If Task A creates a module that Task B calls**, specify the exact public API (method names, signatures) in BOTH dispatch prompts to prevent interface mismatches. Example: when the adapter calls the queue, both subagents must agree on `enqueue(command)` as the method name.
- **Always verify after parallel execution** by running `python3 -m pytest --no-header -q` to confirm no content was lost and no interface mismatches exist.

## Task Completion Quality Gate

Every task is only complete when ALL of the following pass:

1. `python3 -m pytest src/tests/test_<module>.py -v --no-cov` — the task's own tests pass
2. `python3 -m ruff check src/` — zero lint errors
3. `python3 -m mypy src/translator src/models` — zero type errors on strict modules
4. `python3 -m pytest --no-header -q` — full suite passes (coverage gate active)

Steps 1-3 are for fast iteration. Step 4 is the final verification before marking done.
If any step fails, fix the issues before marking the task done. Do not accumulate lint/type debt across waves.

## Task Dispatch Efficiency Rules

- **Only read files that ALREADY EXIST and whose content you need to pass context about.** Before dispatching:
  - DO read: source files the subagent will EXTEND (e.g., adding methods to an existing adapter)
  - DO NOT read: files the subagent will CREATE from scratch (they don't exist yet — reading returns nothing)
  - DO NOT read: spec files (design.md, requirements.md) — pass them as contextFiles instead
  - DO NOT read: test files that the subagent will create
- **Keep subagent prompts concise.** Include: task ID, acceptance criteria, and known gotchas. Do not paste full design docs — pass them as contextFiles instead.
- **Commit after each wave, not after each task.** Unless the user explicitly asks for per-task commits.
- **Dispatch aggressively within a wave.** If tasks write to separate files, run them all in parallel — don't wait for one to finish before starting the next.
- **Do not re-read files already passed as contextFiles.** If a file is in the contextFiles array, it's already in context — reading it again wastes tokens.
- **Do not read back files you just wrote.** The write tool confirms success. Only re-read if you need to verify complex content or check for conflicts.
- **Do not re-read design.md or requirements.md from disk** if they are already in contextFiles. Trust the content provided.
- **Do not run `pip install` at the start of every task.** Only run it if a new dependency was added to `pyproject.toml` in the current wave.

## Implementation Patterns (follow these for consistency)

**Async adapter pattern** (see `src/adapters/wiim_http.py`):
```python
class SomeAdapter:
    def __init__(self, client: WiiMHttpClient) -> None:  # DI
        self._client = client

    async def some_operation(self) -> Result:
        try:
            resp = await self._client.command("SomeCommand")
        except WiiMTimeoutError:
            ...  # re-raise or handle
```

**Test pattern for async adapters** (see `src/tests/test_wiim_http.py`):
```python
from unittest.mock import AsyncMock

client = AsyncMock(spec=WiiMHttpClient)
client.command = AsyncMock(return_value={"key": "value"})
adapter = SomeAdapter(client)
result = await adapter.some_operation()
assert result == expected
```

**PBT test pattern** (see `src/tests/test_translator.py`):
```python
@given(filters=st_canonical_filter_list(min_size=1, max_size=10))
@settings(max_examples=100)
def test_some_property(filters: list[CanonicalFilter]) -> None:
    # property assertion here
```
