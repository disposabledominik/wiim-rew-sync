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
