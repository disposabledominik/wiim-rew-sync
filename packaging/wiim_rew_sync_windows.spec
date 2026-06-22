# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for WiiM <-> REW PEQ Sync — Windows single-file .exe.

Build command:
    pyinstaller packaging/wiim_rew_sync_windows.spec

Output:
    dist/WiiM-REW-Sync.exe (~70-90 MB)
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

# Data files to bundle (help articles for in-app user guide)
import os
_SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
_PROJECT_ROOT = os.path.join(_SPEC_DIR, '..')

help_src = os.path.join(_PROJECT_ROOT, "src", "gui", "assets", "help")
datas_list = []
if os.path.isdir(help_src):
    for f in os.listdir(help_src):
        if f.endswith(".md"):
            datas_list.append(
                (os.path.join(help_src, f), os.path.join("src", "gui", "assets", "help"))
            )

# Bundle QSS stylesheets for theme support
styles_src = os.path.join(_PROJECT_ROOT, "src", "gui", "assets", "styles")
if os.path.isdir(styles_src):
    for f in os.listdir(styles_src):
        if f.endswith(".qss"):
            datas_list.append(
                (os.path.join(styles_src, f), os.path.join("src", "gui", "assets", "styles"))
            )

# Bundle app icon (SVG) for runtime window icon
icons_src = os.path.join(_PROJECT_ROOT, "src", "gui", "assets", "icons")
for icon_file in ("app_icon.svg", "app_icon.ico", "app_icon.png"):
    icon_path = os.path.join(icons_src, icon_file)
    if os.path.isfile(icon_path):
        datas_list.append(
            (icon_path, os.path.join("src", "gui", "assets", "icons"))
        )

# Resolve icon path for the exe embedded icon
_ICON_PATH = os.path.join(_PROJECT_ROOT, 'src', 'gui', 'assets', 'icons', 'app_icon.ico')

a = Analysis(
    ["entry_gui.py"],
    pathex=["..", "."],
    binaries=[],
    datas=datas_list,
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
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
    icon=_ICON_PATH,
)
