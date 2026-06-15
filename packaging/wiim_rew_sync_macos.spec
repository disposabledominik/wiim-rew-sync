# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for WiiM <-> REW PEQ Sync — macOS .app bundle.

Build command:
    pyinstaller packaging/wiim_rew_sync_macos.spec

Output:
    dist/WiiM-REW-Sync.app (~70-90 MB)
"""

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Hidden imports that PyInstaller's analysis may miss
hidden_imports = [
    "pydantic",
    "pydantic.deprecated.decorator",
    "httpx",
    "httpx._transports.default",
    "zeroconf",
    "PySide6.QtWidgets",
    "PySide6.QtCore",
    "PySide6.QtGui",
    *collect_submodules("src.translator"),
    *collect_submodules("src.models"),
    *collect_submodules("src.adapters"),
    *collect_submodules("src.gui"),
    *collect_submodules("src.discovery"),
    *collect_submodules("src.repository"),
    *collect_submodules("src.logging"),
    *collect_submodules("src.utils"),
]

# Heavy Qt modules to exclude (~20-30 MB savings)
excluded_modules = [
    "PySide6.QtWebEngine",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DAnimation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.QtDesigner",
    "PySide6.QtTest",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtWebSockets",
]

a = Analysis(
    ["entry_gui.py"],
    pathex=["..", "."],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WiiM-REW-Sync",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="WiiM-REW-Sync",
)

app = BUNDLE(
    coll,
    name="WiiM-REW-Sync.app",
    icon=None,
    bundle_identifier="com.wiim-rew-sync.app",
    info_plist={
        "CFBundleDisplayName": "WiiM-REW-Sync",
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
    },
)
