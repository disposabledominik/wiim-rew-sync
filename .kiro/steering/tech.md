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

- **Shell:** WSL2 Ubuntu (Linux). The execution shell is ALREADY Linux.
- **Do NOT** prefix commands with `wsl`, `wsl bash -c`, or `bash -c`. Run directly.
- **Python:** `python3` (not `python`). Package management: `pip3` or `python3 -m pip`.
- **Path separators:** Forward slashes (`/`). The IDE shows Windows paths but execution is Linux.

## Hooks (Kiro Agent Hooks)

Hooks execute in **Windows cmd shell** (not WSL) via batch files delegating to `scripts/hook_runner.sh`.

| Hook | Batch file |
|------|-----------|
| Type-check | `scripts/hook_mypy.bat` |
| Lint | `scripts/hook_lint.bat` |
| Tests | `scripts/hook_test.bat` |

**`hook_runner.sh` always exits 0** so Kiro displays output. Do NOT change this.

### DO NOT MODIFY hooks unless explicitly asked:
- Never put bash variables in `.bat` files
- Never inline `bash -c "..."` in hook JSON
- Never change line endings on `.sh` files

## Commands & Execution Rules

**Every `execute_pwsh` call for pytest, ruff, or mypy MUST include `timeout=60000`.**

```bash
# Full test suite (final verification)
python3 -m pytest --no-header -q

# Single test file (skip coverage gate)
python3 -m pytest src/tests/test_foo.py -v --no-cov

# Lint
python3 -m ruff check src/

# Type check
python3 -m mypy src/

# Install (ONLY if pyproject.toml deps changed)
pip3 install -e ".[dev]"
```

**Exit codes:** `-1` in WSL is normal (not a failure). `1` from pytest means tests failed (read output). Only retry on actual Python tracebacks — never retry because of exit codes.

**NEVER:**
- Check `python3 --version`
- Create temp shell scripts for single commands
- Pipe output to files then read them
- Run pytest/ruff/mypy as background processes
- Add `sleep` commands to wait for output
- Re-run a command that already produced valid output
- Run `pip install` unless deps changed

## Key Configuration (pyproject.toml)

- **ruff**: line-length 100, target py312, rules: E/W/F/I/B/C4/UP/ANN/S/RUF
- **mypy**: strict on `src.translator.*` and `src.models.*`; ignore PySide6/zeroconf/respx
- **pytest**: testpaths = `src/tests`, asyncio_mode = auto, coverage on `src/translator`
- **coverage**: branch coverage, fail_under = 90

## Code Style Conventions

- Type annotations on all public functions
- Docstrings on all modules and public classes/functions
- Imports sorted by isort (ruff I rule)
- No `assert` in production code (S101 ignored only in tests)
- `from __future__ import annotations` for deferred evaluation
- Custom exceptions in `src/models/errors.py`
- Floating-point comparisons use tolerances (`src/utils/fp_compare.py`)

## Common Pitfalls

1. **Never use en-dash or unicode minus in code.** ASCII hyphen `-` only. (RUF001/RUF002/RUF003)

2. **`caplog` requires `propagate=True`.** Our loggers have `propagate=False`. Use try/finally:
   ```python
   logger.propagate = True
   try:
       with caplog.at_level(logging.DEBUG, logger="wiim_rew_sync.wiim_api"):
           await operation()
       assert "expected" in caplog.text
   finally:
       logger.propagate = False
   ```

3. **No unused imports.** (F401) Only import what you use.

4. **Typed dicts in strict modules.** Use `dict[str, object]` not `dict`. (mypy disallow_any_generics)

5. **httpx exception names:** `httpx.TimeoutException` and `httpx.ConnectError` (not stdlib names).

6. **Hypothesis imports go at top of file** alongside other imports. Never mid-file. (E402)

## Parallel Task Execution

- **Same file → batch into one subagent call.** Last writer wins otherwise.
- **Separate files → dispatch in parallel.**
- **Shared interfaces:** When Task A creates a module that Task B calls, specify exact method names/signatures in both prompts.
- **Verify after:** Run full test suite to catch interface mismatches.

## Task Completion Quality Gate

1. `python3 -m pytest src/tests/test_<module>.py -v --no-cov` — task's own tests pass
2. `python3 -m ruff check src/` — zero lint errors
3. `python3 -m mypy src/translator src/models` — zero type errors
4. `python3 -m pytest --no-header -q` — full suite passes with coverage

Steps 1-3 for iteration; step 4 as final gate. Fix issues before marking done.

## Task Dispatch Efficiency

- **Only read files the subagent will EXTEND** (not create from scratch)
- **Pass spec files as contextFiles** — don't read them before dispatching
- **Don't read back files you just wrote**
- **Commit after each wave**, not each task
- **Dispatch all independent tasks in parallel**

## Implementation Patterns

**Async adapter** (DI, error mapping):
```python
class SomeAdapter:
    def __init__(self, client: WiiMHttpClient) -> None:
        self._client = client

    async def operation(self) -> Result:
        resp = await self._client.command("Cmd")
```

**Async adapter test** (AsyncMock):
```python
client = AsyncMock(spec=WiiMHttpClient)
client.command = AsyncMock(return_value={"key": "value"})
adapter = SomeAdapter(client)
result = await adapter.operation()
```

**PBT test**:
```python
@given(filters=st_canonical_filter_list(min_size=1, max_size=10))
@settings(max_examples=100)
def test_property(filters: list[CanonicalFilter]) -> None:
    ...
```
