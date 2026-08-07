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

# Data files to bundle (help articles for in-app user guide)
import os
import sys
_SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
_PROJECT_ROOT = os.path.join(_SPEC_DIR, '..')

# Resolve the app version the same way the running app does (single source
# of truth: src/utils/version.py, backed by the setuptools_scm-generated
# src/_version.py written during `pip install -e ".[package]"`).
sys.path.insert(0, os.path.abspath(_PROJECT_ROOT))
from src.utils.version import get_app_version
_APP_VERSION = get_app_version()

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

# Bundle app icon (SVG/PNG) for runtime window icon, plus the QSS-referenced
# combo-box chevron icons (see src/gui/theme.py's %ICONS_DIR% substitution).
icons_src = os.path.join(_PROJECT_ROOT, "src", "gui", "assets", "icons")
for icon_file in (
    "app_icon.svg",
    "app_icon.png",
    "chevron_down_dark.svg",
    "chevron_down_light.svg",
):
    _icon_path = os.path.join(icons_src, icon_file)
    if os.path.isfile(_icon_path):
        datas_list.append(
            (_icon_path, os.path.join("src", "gui", "assets", "icons"))
        )

# Bundle the default device capability override file (seeded into the
# user's app data dir on first run -- see src/models/device_capability_file.py)
capabilities_src = os.path.join(
    _PROJECT_ROOT, "src", "models", "assets", "device_capabilities.json"
)
if os.path.isfile(capabilities_src):
    datas_list.append(
        (capabilities_src, os.path.join("src", "models", "assets"))
    )

# macOS icon: prefer .icns, fall back to .png
_MACOS_ICON = os.path.join(icons_src, 'app_icon.icns')
if not os.path.isfile(_MACOS_ICON):
    _MACOS_ICON = os.path.join(icons_src, 'app_icon.png')
if not os.path.isfile(_MACOS_ICON):
    _MACOS_ICON = None

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
    icon=_MACOS_ICON,
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
    icon=_MACOS_ICON,
    bundle_identifier="com.wiim-rew-sync.app",
    info_plist={
        "CFBundleDisplayName": "WiiM-REW-Sync",
        "CFBundleShortVersionString": _APP_VERSION,
        "NSHighResolutionCapable": True,
    },
)
