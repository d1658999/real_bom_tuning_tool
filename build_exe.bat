@echo off
REM ─────────────────────────────────────────────────────────────────────────
REM  build_exe.bat  –  Builds rf_network_tool.exe from source
REM  Double-click this file from the project root folder.
REM ─────────────────────────────────────────────────────────────────────────

setlocal
cd /d "%~dp0"

echo [1/3] Checking virtual environment ...
if not exist ".venv\Scripts\pyinstaller.exe" (
    echo ERROR: .venv\Scripts\pyinstaller.exe not found.
    echo Please run:  .venv\Scripts\pip install pyinstaller
    pause
    exit /b 1
)

echo [2/3] Running PyInstaller ...
.venv\Scripts\pyinstaller.exe --clean rf_network_tool.spec
if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller failed. See output above.
    pause
    exit /b 1
)

echo.
echo [3/3] Build complete!
echo Output: dist\rf_network_tool.exe
echo.
echo Deploy by placing these items in the same folder:
echo   dist\rf_network_tool.exe
echo   Inductors_BOM\
echo   Capacitors_BOM\
echo.
pause
