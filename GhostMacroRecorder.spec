# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build for Ghost Macro Recorder.
# Produces a one-folder app in dist\GhostMacroRecorder\ which the Inno Setup
# installer (installer\GhostMacroRecorder.iss) copies into C:\Program Files.

from PyInstaller.utils.hooks import collect_all

ctk_datas, ctk_binaries, ctk_hiddenimports = collect_all("customtkinter")

hiddenimports = list(
    set(
        ctk_hiddenimports
        + [
            "pynput.keyboard._win32",
            "pynput.mouse._win32",
            "pystray._win32",
            "PIL._tkinter_finder",
        ]
    )
)

# Only ship the runtime assets (not the large source artwork)
app_assets = [
    ("assets/app.ico", "assets"),
    ("assets/icon.png", "assets"),
    ("assets/icon_small.png", "assets"),
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=ctk_binaries,
    datas=ctk_datas + app_assets,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "_pytest", "numpy"],
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
