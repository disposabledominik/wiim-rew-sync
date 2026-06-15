# Project Structure

```
src/
├── adapters/        # WiiM HTTP adapter and REW HTTP adapter (network I/O)
├── cli/             # CLI entry point and proof-of-concept commands
├── discovery/       # mDNS device discovery (zeroconf)
│   ├── discovery_module.py # Orchestrator: mDNS then subnet fallback
│   ├── zeroconf_discover.py # mDNS probe (_wiim._tcp.local.)
│   └── subnet_scanner.py   # Fallback getStatusEx subnet scan
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
│   ├── __init__.py       # TranslationEngine facade (stateless, all @staticmethod)
│   ├── _warnings.py      # ValidationWarning dataclass
│   ├── rew_parser.py     # REW text/API → Canonical
│   ├── rew_generator.py  # Canonical → REW text
│   ├── wiim_parser.py    # WiiM API → Canonical
│   ├── wiim_generator.py # Canonical → WiiM API payload
│   └── schema_migrator.py # Profile schema version migration
└── utils/           # Shared utilities (fp_compare, app_dirs, etc.)
    ├── fp_compare.py    # Floating-point tolerance predicates
    └── app_dirs.py      # OS-appropriate data directory resolution

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
1. **Models & Translator** — domain models and stateless translation (COMPLETE)
2. **Network & Discovery** — HTTP clients, device discovery, capability probing (COMPLETE)
3. **Adapters & Repository** — safe write protocol, backup manager, profile storage (COMPLETE)
4. **CLI Proof of Concept** — full round-trip against real hardware (COMPLETE — all hardware tests passed 2026-06-14)
5. **GUI Layer** — PySide6 interface built on validated business logic (READY — Task 32 phase gate cleared)
6. **Packaging** — PyInstaller single-file distribution
7. **Integrity Fixes** — LP/HP in REW, dynamic max_filters, PBT strategy updates (Phase 10)
