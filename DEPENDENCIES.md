# Dependencies

This document lists all packages required to build and run the WiiM ↔ REW PEQ Sync Tool.

The tool is designed to be **lightweight, portable, and usable by non-technical users**. End users receive a single-file executable (via PyInstaller) and do not need Python installed. This document is primarily for developers and contributors.

---

## Runtime Dependencies

These are bundled into the final executable:

| Package | Version | Purpose |
|---------|---------|---------|
| Python | ≥ 3.12 | Language runtime (embedded in PyInstaller bundle) |
| PySide6 | ≥ 6.7.0 | Cross-platform GUI framework (Qt 6 bindings) |
| httpx | ≥ 0.27.0 | Async HTTP client for WiiM and REW API communication |
| pydantic | ≥ 2.7.0 | Data validation and settings management (Canonical Filter Model) |
| zeroconf | ≥ 0.132.0 | mDNS/DNS-SD device discovery on local network |

### Why these choices

- **PySide6** — Qt-based, LGPL-licensed, runs on Windows/macOS/Linux without extra dependencies
- **httpx** — async-capable, lightweight alternative to requests; supports timeouts and TLS natively
- **pydantic v2** — Rust-backed validation; keeps the Canonical Filter Model type-safe with minimal overhead
- **zeroconf** — pure-Python mDNS, no system service dependencies; works across all platforms

### No internet required at runtime

The tool operates entirely on the local network. No cloud services, telemetry, accounts, or internet connectivity is needed.

---

## Development Dependencies

Only needed for building from source, running tests, and linting:

| Package | Version | Purpose |
|---------|---------|---------|
| hypothesis | ≥ 6.100.0 | Property-based testing framework |
| pytest | ≥ 8.2.0 | Test runner |
| pytest-cov | ≥ 5.0.0 | Coverage reporting |
| pytest-asyncio | ≥ 0.23.0 | Async test support |
| respx | ≥ 0.21.0 | Mock httpx requests in tests |
| ruff | ≥ 0.4.0 | Linter and formatter |
| mypy | ≥ 1.10.0 | Static type checker |

---

## Packaging Dependency

| Package | Version | Purpose |
|---------|---------|---------|
| PyInstaller | ≥ 6.0.0 | Bundles everything into a single portable executable |

The final artifact is:
- **Windows**: `wiim-rew-sync.exe` (single file, no installer needed)
- **macOS**: `wiim-rew-sync.app` (drag-and-drop bundle)
- **Linux**: `wiim-rew-sync` (single ELF binary)

---

## System Requirements (End Users)

| | Minimum |
|---|---|
| OS | Windows 10+, macOS 12+, or Linux (glibc 2.31+) |
| RAM | 256 MB available |
| Disk | ~70-90 MB for the executable |
| Network | Local network access (Wi-Fi or Ethernet on same subnet as WiiM devices) |
| Python | **NOT required** — the executable is self-contained |

---

## Installation for Developers

```bash
# Clone the repository
git clone https://github.com/<your-org>/wiim-rew-sync.git
cd wiim-rew-sync

# Create a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode with dev dependencies
pip3 install -e ".[dev]"

# Verify setup
python3 -m pytest src/tests/ -v
python3 -m ruff check src/
python3 -m mypy src/
```

---

## Building the Portable Executable

```bash
# Install PyInstaller
pip install pyinstaller>=6.0.0

# Build (platform-specific .spec files in packaging/)
pyinstaller packaging/wiim_rew_sync_windows.spec   # Windows
pyinstaller packaging/wiim_rew_sync_macos.spec     # macOS
pyinstaller packaging/wiim_rew_sync_linux.spec     # Linux
```

The output appears in `dist/`. Distribute the single file — no Python installation needed on the target machine.

**Size optimization:** The `.spec` files exclude unused Qt modules (QtWebEngine, Qt3D, QtMultimedia, etc.) to keep the binary at ~70-90 MB. UPX compression is intentionally NOT used — it triggers antivirus false positives on Windows, which is unacceptable for non-technical users.

---

## Dependency Philosophy

1. **Minimal footprint** — only 4 runtime packages, each chosen for cross-platform compatibility
2. **No native compilation** — all packages install from wheels; no C compiler needed
3. **No system services** — no Docker, no database, no background daemons
4. **Pinned minimums, no upper caps** — allows security patches while ensuring tested baselines
5. **Single-file distribution** — PyInstaller bundles Python + all deps into one portable artifact
