# Contributing

Thanks for looking at the code. This covers running the project from source, the CLI, the
test/lint/type-check workflow, and the conventions the codebase follows.

## Setup

Requires Python 3.12+.

```bash
git clone https://github.com/disposabledominik/wiim-rew-sync.git
cd wiim-rew-sync
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Running from source

```bash
python packaging/entry_gui.py         # GUI
```

The CLI was the original proof-of-concept and remains useful for scripting and headless use:

```bash
wiim-rew-sync list-devices
wiim-rew-sync list-sources --device <ip>
wiim-rew-sync get-filters --device <ip> --source wifi
wiim-rew-sync dry-run-import --file my_measurement.txt
wiim-rew-sync set-filters --file my_measurement.txt --device <ip> --source wifi
wiim-rew-sync peq-toggle --device <ip> --source wifi --state on
```

Run `wiim-rew-sync <command> --help` for the full option list, or `wiim-rew-sync --help` for all
commands (sources, RoomFit profiles, presets, etc.).

To build a standalone executable instead of running from source, see
[packaging/README.md](packaging/README.md).

## Tests, lint, type checks

```bash
python3 -m pytest src/tests/test_<module>.py -v --no-cov   # targeted tests (fast, ~5s)
python3 -m ruff check src/                                  # lint
python3 -m mypy src/                                        # type check
```

The full test suite (`python3 -m pytest --no-header -q`) takes 10-20 minutes on WSL and will time
out most agent/CI shells — run targeted test files during development, and treat the full suite as
an optional final gate. Don't pipe pytest/ruff/mypy output through `| tail`, `| grep`, etc.; it
makes timeouts worse and drops output you need. See [CLAUDE.md](CLAUDE.md)'s Commands section for
the full nuance (including a WSL/coverage artifact you can safely ignore in Qt-based test output).

Task completion gate before calling any change done:
1. `pytest` for the touched module(s) passes
2. `ruff check src/` — zero errors
3. `mypy src/` — zero errors (`src/translator/` and `src/models/` run under strict-mode overrides)

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the same three gates plus
`pip-audit` and the full suite with its coverage threshold on every PR, so a change that skips the
local gate will be caught there rather than merged.

## Code style

- Type annotations on all public functions; docstrings on all public modules/classes/functions.
- `from __future__ import annotations` for deferred evaluation.
- Imports sorted by isort (ruff `I` rule); no unused imports.
- No `assert` in production code — use the custom exceptions in `src/models/errors.py`.
- Floating-point comparisons use the tolerances in `src/utils/fp_compare.py`, not raw `==`.
- ASCII hyphen `-` only — no en-dash or unicode minus (ruff RUF001-3).

## Testing philosophy

- Every module in `src/adapters/`, `src/translator/`, and `src/repository/` needs a matching
  `test_<module>.py` covering its public API, edge cases, and error paths.
- Every bug fix ships with a regression test (fails before the fix, passes after).
- Every new feature ships with tests — never functionality without coverage.
- State machines, translation logic, and data pipelines get property-based tests (Hypothesis) in
  addition to unit tests.
- GUI components use `pytest-qt` (`qtbot`); mock `AsyncBridge` rather than making real network
  calls in GUI tests.

## Architecture and domain rules

Read [CLAUDE.md](CLAUDE.md) before making non-trivial changes — it covers the Canonical Filter
Model, the safe-write protocol, and the non-negotiable domain rules (WiiM API quirks, REW rules,
etc.). Deeper reference material lives in [docs/](docs/README.md), notably
[docs/architecture.md](docs/architecture.md) and [docs/wiim_api_notes.md](docs/wiim_api_notes.md).

## Tech stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| GUI | PySide6 (Qt 6, LGPL) |
| HTTP | httpx (async) |
| Data validation | pydantic v2 |
| Device discovery | zeroconf |
| Testing | pytest, hypothesis (PBT), respx (HTTP mocking), pytest-asyncio, pytest-qt |
| Linting | ruff |
| Type checking | mypy (strict on `src/translator/` and `src/models/`) |
| Packaging | PyInstaller (single-file executable) |
