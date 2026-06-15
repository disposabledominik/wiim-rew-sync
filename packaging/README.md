# Packaging — WiiM ↔ REW PEQ Sync

Build instructions for creating standalone executables using PyInstaller.

> **Important:** PyInstaller is NOT a cross-compiler. You must build on the target OS.
> A Windows `.exe` must be built on Windows, a macOS `.app` on macOS, etc.

---

## Windows (.exe)

### Prerequisites

1. **Install Python 3.12+** from https://www.python.org/downloads/
   - During installation, **check "Add python.exe to PATH"** (critical!)
   - Finish the installer
2. Open a **new** CMD or PowerShell window (so PATH picks up the new Python)
3. Verify: `python --version` → should show `Python 3.12.x`

### Build Steps

```cmd
cd C:\Users\domin\Desktop\Misc\_dev\wiim-rew-sync

:: Create a Windows-native virtual environment
python -m venv .venv-win

:: Activate it
.venv-win\Scripts\activate

:: Install the project + PyInstaller
pip install -e ".[package]"

:: Build the executable
pyinstaller packaging/wiim_rew_sync_windows.spec
```

### Output

```
dist\WiiM-REW-Sync.exe   (~70-90 MB)
```

### Verify

1. Double-click `dist\WiiM-REW-Sync.exe` — the GUI should open.
2. Check that `%APPDATA%\wiim-rew-sync\logs\` was created on first launch.
3. Check that `%APPDATA%\wiim-rew-sync\profiles\` was created.

### Notes

- Do NOT use the WSL `.venv/` directory — it contains Linux binaries.
- Add `.venv-win/` to `.gitignore` so it isn't committed.
- If you get "python is not recognized", close and reopen CMD after installing Python.

---

## macOS (.app bundle)

### Prerequisites

1. **Install Python 3.12+** via Homebrew (recommended):
   ```bash
   brew install python@3.12
   ```
   Or download from https://www.python.org/downloads/macos/

2. Verify: `python3 --version` → should show `Python 3.12.x`

### Build Steps

```bash
cd /path/to/wiim-rew-sync

# Create virtual environment
python3 -m venv .venv-mac

# Activate it
source .venv-mac/bin/activate

# Install the project + PyInstaller
pip install -e ".[package]"

# Build the .app bundle
pyinstaller packaging/wiim_rew_sync_macos.spec
```

### Output

```
dist/WiiM-REW-Sync.app/   (~70-90 MB)
```

### Verify

1. Double-click `dist/WiiM-REW-Sync.app` — or from terminal: `open dist/WiiM-REW-Sync.app`
2. Check that `~/.config/wiim-rew-sync/logs/` was created on first launch.
3. Check that `~/.config/wiim-rew-sync/profiles/` was created.

### Notes

- **Gatekeeper:** Since the app is unsigned, macOS will block it on first open.
  Right-click → "Open" → "Open" to bypass, or: `xattr -dr com.apple.quarantine dist/WiiM-REW-Sync.app`
- For distribution, consider code-signing with an Apple Developer certificate.
- If building on Apple Silicon (M1/M2/M3), the binary will be arm64. For universal binary,
  build on Intel or use `--target-arch universal2` (requires both architectures of dependencies).

---

## Linux (single binary)

### Prerequisites

1. **Install Python 3.12+** via your package manager:

   Ubuntu/Debian:
   ```bash
   sudo apt update
   sudo apt install python3 python3-venv python3-pip
   ```

   Fedora:
   ```bash
   sudo dnf install python3 python3-pip
   ```

   Arch:
   ```bash
   sudo pacman -S python python-pip
   ```

2. Verify: `python3 --version` → should show `Python 3.12.x`

### Build Steps

```bash
cd /path/to/wiim-rew-sync

# Create virtual environment
python3 -m venv .venv-linux

# Activate it
source .venv-linux/bin/activate

# Install the project + PyInstaller
pip install -e ".[package]"

# Build the single binary
pyinstaller packaging/wiim_rew_sync_linux.spec
```

### Output

```
dist/WiiM-REW-Sync   (~70-90 MB)
```

### Verify

1. Run: `./dist/WiiM-REW-Sync`
2. Check that `~/.config/wiim-rew-sync/logs/` was created on first launch.
3. Check that `~/.config/wiim-rew-sync/profiles/` was created.

### Notes

- The binary links against system libraries (glibc, Qt platform plugins).
  Build on the oldest distro version you intend to support for maximum compatibility
  (e.g., Ubuntu 22.04 for broad glibc coverage).
- If the app fails with a Qt platform plugin error, install: `sudo apt install libxcb-xinerama0 libxkbcommon-x11-0`
- For WSL2 users: you can build the Linux binary from WSL, but you'll need an X server
  (e.g., WSLg on Windows 11) to run the GUI.

---

## Expected Output Summary

| Platform | Command | Output | Expected Size |
|----------|---------|--------|--------------|
| Windows | `pyinstaller packaging/wiim_rew_sync_windows.spec` | `dist\WiiM-REW-Sync.exe` | 70-90 MB |
| macOS | `pyinstaller packaging/wiim_rew_sync_macos.spec` | `dist/WiiM-REW-Sync.app/` | 70-90 MB |
| Linux | `pyinstaller packaging/wiim_rew_sync_linux.spec` | `dist/WiiM-REW-Sync` | 70-90 MB |

---

## Design Decisions

- **No UPX compression**: UPX causes antivirus false positives on Windows for non-technical users. All spec files set `upx=False` explicitly.
- **Single-file distribution**: All platforms use `onefile` mode (or BUNDLE for macOS) for simplicity. No installer required — just copy the file and run.
- **Excluded Qt modules**: Heavy, unused PySide6 modules are excluded to reduce binary size by ~20-30 MB:
  QtWebEngine, Qt3D, QtMultimedia, QtQuick, QtQml, QtDesigner, QtTest, QtBluetooth, QtNfc, QtPositioning, QtSensors, QtSerialPort, QtWebSockets.
- **Hidden imports**: Core dependencies (pydantic, httpx, zeroconf, PySide6 widgets) and all `src.*` submodules are explicitly included to prevent PyInstaller from missing dynamic imports.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `python is not recognized` (Windows) | Reinstall Python with "Add to PATH" checked, then open a new terminal |
| `ModuleNotFoundError` at runtime | Add the missing module to `hiddenimports` in the `.spec` file and rebuild |
| Binary exceeds 90 MB | Check that the excluded Qt modules list hasn't been reduced in the `.spec` |
| Antivirus false positive (Windows) | Ensure `upx=False` is set. Consider code-signing the `.exe` |
| macOS Gatekeeper blocks app | `xattr -dr com.apple.quarantine dist/WiiM-REW-Sync.app` |
| Qt platform plugin error (Linux) | `sudo apt install libxcb-xinerama0 libxkbcommon-x11-0` |
| WSL `.venv` has `bin/` not `Scripts/` | That's a Linux venv — create a new one on native Windows Python |
| PyInstaller not found after pip install | Make sure the venv is activated (prompt shows `(.venv-win)` etc.) |
