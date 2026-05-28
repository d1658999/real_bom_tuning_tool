@echo off
REM Build a single-file rf_kpi_compare_tool.exe using the repository virtualenv.

setlocal
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "ROOT_DIR=%%~fI"

cd /d "%ROOT_DIR%"

echo [1/3] Checking virtual environment ...
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv\Scripts\python.exe not found.
    echo Create the project virtual environment first.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\pyinstaller.exe" (
    echo ERROR: .venv\Scripts\pyinstaller.exe not found.
    echo Please run: .venv\Scripts\pip install pyinstaller
    pause
    exit /b 1
)

echo [2/3] Verifying compare tool sources ...
.venv\Scripts\python.exe -m py_compile ^
    rf_kpi_compare_tool\__init__.py ^
    rf_kpi_compare_tool\__main__.py ^
    rf_kpi_compare_tool\comparison.py ^
    rf_kpi_compare_tool\app.py ^
    rf_kpi_compare_tool\main.py
if errorlevel 1 (
    echo.
    echo ERROR: Python validation failed. See output above.
    pause
    exit /b 1
)

echo [3/3] Running PyInstaller ...
.venv\Scripts\pyinstaller.exe --clean --noconfirm ^
    --distpath "%ROOT_DIR%\dist" ^
    --workpath "%ROOT_DIR%\build\rf_kpi_compare_tool" ^
    "%ROOT_DIR%\rf_kpi_compare_tool\rf_kpi_compare_tool.spec"
if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller failed. See output above.
    pause
    exit /b 1
)

echo.
echo Build complete.
echo Output: dist\rf_kpi_compare_tool.exe
echo.
pause
