# Project Structure

```
src/
├── adapters/        # WiiM HTTP adapter and REW HTTP adapter (network I/O)
├── cli/             # CLI entry point and proof-of-concept commands
├── discovery/       # mDNS device discovery (zeroconf)
├── gui/             # PySide6 GUI layer
│   ├── dialogs/     # Modal dialogs
│   └── panels/      # Main window panels
├── logging/         # Rotating log setup (app.log, wiim_api.log, rew_api.log)
├── models/          # Domain models (pydantic)
│   ├── canonical.py # CanonicalFilter — central data model
│   ├── capabilities.py # DeviceCapabilities
│   ├── errors.py    # Custom exception hierarchy
│   ├── peq.py       # PEQ band/config structures
│   └── profile.py   # User profile model
├── repository/      # Local JSON profile storage and backup management
├── tests/           # All tests (pytest + hypothesis)
├── translator/      # Translation engine (REW ↔ Canonical ↔ WiiM)
│   ├── rew_parser.py   # REW text/API → Canonical
│   └── wiim_parser.py  # WiiM API → Canonical and Canonical → WiiM payload
└── utils/           # Shared utilities (fp_compare, etc.)

docs/                # Project documentation (PRD, architecture, API notes, etc.)
```

## Architecture Rules

- **Canonical model is the hub**: All conversions go through `CanonicalFilter`. Direct REW→WiiM translation is forbidden.
- **Adapters are injected**: Adapters are passed via constructor for testability.
- **GUI is decoupled**: No network calls or business logic in GUI components.
- **Tests live with source**: `src/tests/` mirrors the module structure with `test_<module>.py` naming.
- **Translator is the core**: Must maintain ≥90% test coverage. Stateless, pure logic.
- **Logging is layered**: Three separate log files by concern (app, wiim_api, rew_api).

## Development Phases

The project follows a strict phased approach:
1. **Models & Translator** — domain models and stateless translation (current phase)
2. **CLI Proof of Concept** — full round-trip against real hardware (must pass before GUI)
3. **GUI Layer** — PySide6 interface built on validated business logic
4. **Packaging** — PyInstaller single-file distribution
