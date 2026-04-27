# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for RF Network Tool.
Produces a single .exe that bundles Python, Qt, NumPy, scikit-rf,
matplotlib, and the compiled Rust rf_sweep extension.

Deployment layout expected by the user:
    <any folder>/
        rf_network_tool.exe   ← this output
        Inductors_BOM/        ← user-provided BOM folders
        Capacitors_BOM/
        fleet_results/        ← created automatically at runtime
"""

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ── Paths (relative to this spec file) ─────────────────────────────────────
SPEC_DIR   = os.path.dirname(os.path.abspath(SPEC))
VENV_SP    = os.path.join(SPEC_DIR, '.venv', 'Lib', 'site-packages')

RF_SWEEP_DIR = os.path.join(VENV_SP, 'rf_sweep')
RF_SWEEP_PYD = os.path.join(RF_SWEEP_DIR, 'rf_sweep.cp310-win_amd64.pyd')

# ── Data files bundled into the exe ─────────────────────────────────────────
datas = []

# scikit-rf ships JSON/yaml data files
datas += collect_data_files('skrf')

# matplotlib fonts, style sheets, etc.
datas += collect_data_files('matplotlib')

# rf_sweep package: __init__.py + .pyd binary
datas += [(os.path.join(RF_SWEEP_DIR, '__init__.py'), 'rf_sweep')]

# ── Hidden imports ───────────────────────────────────────────────────────────
hiddenimports = [
    # scikit-rf
    'skrf',
    'skrf.network',
    'skrf.frequency',
    'skrf.media',
    # numpy / scipy internals sometimes missed
    'numpy',
    'numpy.core._multiarray_umath',
    # matplotlib Qt5 backend
    'matplotlib.backends.backend_qt5agg',
    'matplotlib.backends.backend_agg',
    # PyQt5 modules used by matplotlib toolbar + our GUI
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PyQt5.QtPrintSupport',
    # our own packages
    'rf_network_tool',
    'rf_network_tool.gui',
    'rf_network_tool.gui.main_window',
    'rf_network_tool.gui.port_config_panel',
    'rf_network_tool.gui.file_panel',
    'rf_network_tool.gui.results_panel',
    'rf_network_tool.backend',
    'rf_network_tool.backend.fleet_optimizer',
    'rf_network_tool.backend.network_builder',
    'rf_network_tool.backend.bom_parser',
]
hiddenimports += collect_submodules('skrf')
hiddenimports += collect_submodules('matplotlib')

# ── Binaries: the Rust .pyd extension ───────────────────────────────────────
binaries = [
    (RF_SWEEP_PYD, 'rf_sweep'),
]

# ── Analysis ─────────────────────────────────────────────────────────────────
a = Analysis(
    [os.path.join(SPEC_DIR, 'rf_network_tool', 'main.py')],
    pathex=[SPEC_DIR, VENV_SP],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # trim unused but safe-to-remove packages
        'tkinter',
        'ftplib',
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
    name='rf_network_tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    # Single-file exe: everything merged in
    onefile=True,
    console=False,   # no console window; set True temporarily to see crash logs
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
