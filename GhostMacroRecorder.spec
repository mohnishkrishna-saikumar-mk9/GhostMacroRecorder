# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build for Ghost Macro Recorder.
# Produces a one-folder app in dist\GhostMacroRecorder\ which the Inno Setup
# installer (installer\GhostMacroRecorder.iss) copies into C:\Program Files.

hiddenimports = [
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
]

# Only ship the runtime assets (not the large source artwork)
app_assets = [
    ("assets/app.ico", "assets"),
    ("assets/icon.png", "assets"),
    ("assets/icon_small.png", "assets"),
    ("assets/icon_ui.png", "assets"),
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=app_assets,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "_pytest", "numpy", "tkinter", "customtkinter", "pystray"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GhostMacroRecorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/app.ico"],
    version="version_info.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GhostMacroRecorder",
)
