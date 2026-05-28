# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the RF KPI Compare Tool."""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
ROOT_DIR = os.path.dirname(SPEC_DIR)
VENV_SP = os.path.join(ROOT_DIR, '.venv', 'Lib', 'site-packages')
ICON_PATH = os.path.join(ROOT_DIR, 'rf_network_tool', 'assets', 'rf_network_tool_icon.ico')


datas = []
datas += collect_data_files('skrf')
datas += collect_data_files('matplotlib')


hiddenimports = [
    'numpy',
    'numpy.core._multiarray_umath',
    'skrf',
    'skrf.network',
    'skrf.frequency',
    'skrf.media',
    'xlsxwriter',
    'matplotlib.backends.backend_qt5agg',
    'matplotlib.backends.backend_agg',
    'matplotlib.backends.backend_pdf',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PyQt5.QtPrintSupport',
    'rf_kpi_compare_tool',
    'rf_kpi_compare_tool.app',
    'rf_kpi_compare_tool.comparison',
    'rf_kpi_compare_tool.main',
]
hiddenimports += collect_submodules('skrf')
hiddenimports += collect_submodules('matplotlib')
hiddenimports += collect_submodules('xlsxwriter')


a = Analysis(
    [os.path.join(ROOT_DIR, 'rf_kpi_compare_tool', 'main.py')],
    pathex=[ROOT_DIR, VENV_SP],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'test',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='rf_kpi_compare_tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    onefile=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH if os.path.exists(ICON_PATH) else None,
)
