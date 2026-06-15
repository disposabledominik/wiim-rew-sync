# Packaging — WiiM <-> REW PEQ Sync

Build instructions for creating standalone executables using PyInstaller.

## Prerequisites

1. Python 3.12+
2. Install the project with packaging dependencies:

```bash
pip install -e ".[package]"
```

This installs `pyinstaller>=6.0.0` alongside the project's runtime dependencies.

## Build Commands

All commands should be run from the **project root** directory.

### Windows (.exe)

```bash
pyinstaller packaging/wiim_rew_sync_windows.spec
```

Output: `dist/WiiM-REW-Sync.exe`

### macOS (.app bundle)

```bash
pyinstaller packaging/wiim_rew_sync_macos.spec
```

Output: `dist/WiiM-REW-Sync.app/`

### Linux (single binary)

```bash
pyinstaller packaging/wiim_rew_sync_linux.spec
```

Output: `dist/WiiM-REW-Sync`

## Expected Output

| Platform | Output | Expected Size |
|----------|--------|--------------|
| Windows | `dist/WiiM-REW-Sync.exe` | 70-90 MB |
| macOS | `dist/WiiM-REW-Sync.app/` | 70-90 MB |
| Linux | `dist/WiiM-REW-Sync` | 70-90 MB |

## Design Decisions

- **No UPX compression**: UPX causes antivirus false positives on Windows for non-technical users. All spec files set `upx=False` explicitly.
- **Single-file distribution**: All platforms use `onefile` mode (or BUNDLE for macOS) for simplicity. No installer required.
- **Excluded Qt modules**: Heavy, unused PySide6 modules are excluded to reduce binary size by ~20-30 MB. Excluded modules include QtWebEngine, Qt3D, QtMultimedia, QtQuick, QtQml, QtDesigner, QtTest, QtBluetooth, QtNfc, QtPositioning, QtSensors, QtSerialPort, and QtWebSockets.
- **Hidden imports**: Core dependencies (pydantic, httpx, zeroconf, PySide6 widgets) and all `src.*` submodules are explicitly included to prevent PyInstaller from missing dynamic imports.

## Verifying the Build

1. Run the executable on a machine without Python installed.
2. Confirm the GUI opens with the main window layout (device panel, EQ panel, profiles).
3. Verify the `logs/` directory is created on first run in the appropriate location:
   - Windows: `%APPDATA%\wiim-rew-sync\logs\`
   - macOS/Linux: `~/.config/wiim-rew-sync/logs/`
4. Confirm profile storage directory is created at the same location under `profiles/`.

## Troubleshooting

- **Missing module errors**: If the binary fails with an import error, add the module to `hiddenimports` in the relevant `.spec` file and rebuild.
- **Large binary size**: If the binary exceeds 90 MB, check that the excluded Qt modules list hasn't been inadvertently reduced.
- **Antivirus false positives**: Ensure `upx=False` is set. If still flagged, consider code-signing the executable.
- **macOS Gatekeeper**: The `.app` bundle may need to be code-signed for distribution outside the App Store. For local testing, right-click and select "Open" to bypass Gatekeeper.
