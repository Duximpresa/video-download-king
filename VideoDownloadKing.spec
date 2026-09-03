# -*- mode: python ; coding: utf-8 -*-

datas = [('video_download_king/assets', 'video_download_king/assets')]
binaries = []
hiddenimports = [
    'gmssl.func',
    'gmssl.sm3',
]

excluded_modules = [
    'PySide6.QtBluetooth',
    'PySide6.QtCharts',
    'PySide6.QtDataVisualization',
    'PySide6.QtGraphs',
    'PySide6.QtHelp',
    'PySide6.QtLocation',
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    'PySide6.QtPositioning',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtQuick3D',
    'PySide6.QtQuickControls2',
    'PySide6.QtQuickWidgets',
    'PySide6.QtSensors',
    'PySide6.QtSerialPort',
    'PySide6.QtSql',
    'PySide6.QtSvg',
    'PySide6.QtTest',
    'PySide6.QtTextToSpeech',
    'PySide6.QtWebChannel',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineQuick',
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebSockets',
    'PySide6.Qt3DAnimation',
    'PySide6.Qt3DCore',
    'PySide6.Qt3DExtras',
    'PySide6.Qt3DInput',
    'PySide6.Qt3DLogic',
    'PySide6.Qt3DRender',
    'black',
    'IPython',
    'jupyter',
    'jupyter_client',
    'jupyter_core',
    'matplotlib',
    'mypy',
    'notebook',
    'numpy',
    'pandas',
    'PIL',
    'pytest',
    'setuptools',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)
# The Codex/Poppler toolchain can put a renamed ICU build on PATH. Qt 6.11
# imports the unversioned Windows system ICU ABI, while Poppler's DLL exports
# only version-suffixed symbols (for example, ucnv_open_78). Bundling that DLL
# makes Qt6Core fail before the main window is created. Windows 11 provides the
# compatible system ICU, so these environment-owned DLLs must stay excluded.
a.binaries = [
    item for item in a.binaries
    if item[0].lower() not in {'icuuc.dll', 'icudt78.dll'}
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VideoDownloadKing',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['video_download_king\\assets\\logo.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VideoDownloadKing',
)
