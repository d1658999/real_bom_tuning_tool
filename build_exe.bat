@echo off
REM ─────────────────────────────────────────────────────────────────────────
REM  build_exe.bat  –  Builds rf_network_tool.exe from source
REM  Double-click this file from the project root folder.
REM ─────────────────────────────────────────────────────────────────────────

setlocal
cd /d "%~dp0"

set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"

echo [1/4] Checking virtual environment ...
if not exist "%VENV_PYTHON%" (
    echo ERROR: %VENV_PYTHON% not found.
    echo Please create the virtual environment with Python 3.10 first.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\pyinstaller.exe" (
    echo ERROR: .venv\Scripts\pyinstaller.exe not found.
    echo Please run:  .venv\Scripts\pip install pyinstaller
    pause
    exit /b 1
)

"%VENV_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 10) else 1)"
if errorlevel 1 (
    echo ERROR: .venv must use Python 3.10.x for rf_sweep and PyInstaller.
    echo Current version:
    "%VENV_PYTHON%" -V
    echo Recreate the virtual environment with Python 3.10, then reinstall requirements.
    pause
    exit /b 1
)

echo [2/4] Building Rust acceleration module ...
pushd "rf_network_tool\rf_sweep"
set "PYO3_PYTHON=%VENV_PYTHON%"
cargo build --release
if errorlevel 1 (
    popd
    echo.
    echo ERROR: Rust rf_sweep build failed. See output above.
    pause
    exit /b 1
)
popd

set "RF_SWEEP_PYD="
for %%F in (".venv\Lib\site-packages\rf_sweep\rf_sweep.cp*-win_amd64.pyd") do set "RF_SWEEP_PYD=%%~fF"
if not defined RF_SWEEP_PYD (
    echo ERROR: rf_sweep .pyd not found in .venv\Lib\site-packages\rf_sweep.
    echo Please install the rf_sweep package into the virtual environment first.
    pause
    exit /b 1
)

copy /Y "rf_network_tool\rf_sweep\target\release\rf_sweep.dll" "%RF_SWEEP_PYD%" >nul
if errorlevel 1 (
    echo.
    echo ERROR: Could not update %RF_SWEEP_PYD%.
    echo Close any running rf_network_tool or Python process, then run this build again.
    pause
    exit /b 1
)

echo [3/4] Running PyInstaller ...
.venv\Scripts\pyinstaller.exe --clean rf_network_tool.spec
if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller failed. See output above.
    pause
    exit /b 1
)

echo.
echo [4/4] Build complete!
echo Output: dist\rf_network_tool.exe
echo.
echo Deploy by placing these items in the same folder:
echo   dist\rf_network_tool.exe
echo   Inductors_BOM\
echo   Capacitors_BOM\
echo.
pause
