@echo off
REM ─────────────────────────────────────────────────────────────────────────
REM  build_exe.bat  –  Builds rf_network_tool.exe from source
REM
REM  Requirements:
REM    • Run from the project root (same folder as this script)
REM    • .venv must exist with all dependencies installed
REM      (run:  .venv\Scripts\pip install -r requirements.txt)
REM ─────────────────────────────────────────────────────────────────────────

setlocal
cd /d "%~dp0"

echo [1/3] Activating virtual environment ...
call .venv\Scripts\activate.bat

echo [2/3] Running PyInstaller ...
pyinstaller --clean rf_network_tool.spec

echo [3/3] Done.
echo.
echo Output: dist\rf_network_tool.exe
echo.
echo Deploy by copying these items to the same folder:
echo   dist\rf_network_tool.exe
echo   Inductors_BOM\
echo   Capacitors_BOM\
echo.
pause
