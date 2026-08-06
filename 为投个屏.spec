# -*- mode: python ; coding: utf-8 -*-

import os


_project_dir = os.path.abspath(SPECPATH)


a = Analysis(
    [os.path.join(_project_dir, 'main.py')],
    pathex=[],
    binaries=[],
    datas=[
        (os.path.join(_project_dir, 'resources'), 'resources'),
        (os.path.join(_project_dir, 'favicon.ico'), '.'),
        (os.path.join(_project_dir, 'ys', 'xys', 'images'), 'ys/xys/images'),
    ],
    hiddenimports=['cv2', 'numpy', 'websockets', 'core.hdc_client', 'core.cast_engine', 'core.input_manager', 'core.audio_manager', 'core.hdc_cast_service', 'core.web_cast_server', 'ui.styles', 'ui.main_window', 'ui.device_page', 'ui.cast_page', 'ui.extensions_page', 'ui.settings_page', 'ui.performance_page', 'ui.toolbox_page'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='为投个屏',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(_project_dir, 'favicon.ico')],
)
