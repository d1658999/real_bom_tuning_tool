# BUILD.md — Building `rf_network_tool` from Source

This guide walks through building the `rf_network_tool` Windows executable from a fresh Windows machine. The project combines a **Python (PyQt5)** front-end with a **Rust** acceleration module (`rf_sweep`) compiled via `maturin`.

---

## Prerequisites

Install all of the following before starting.

| Tool | Version | Notes |
|---|---|---|
| **Python** | **3.10.x** (exact) | The Rust extension `.pyd` filename encodes the CPython version (`cp310`). Using 3.11+ will break the build. |
| **Rust toolchain** | stable (latest) | Install via `rustup` |
| **MSVC C++ Build Tools** | VS 2019 or 2022 | Required by the Rust linker on Windows |
| **Git** | any recent | Optional, but recommended for cloning |

### Python 3.10

Download from [python.org/downloads](https://www.python.org/downloads/release/python-3100/) — choose the **Windows x86-64 installer**.  
During install, check **"Add Python to PATH"**.

Verify:
```cmd
python --version
```
Expected: `Python 3.10.x`

### Rust toolchain

```cmd
winget install Rustlang.Rustup
rustup install stable
rustup default stable
```

Verify:
```cmd
rustc --version
cargo --version
```

### Microsoft Visual Studio C++ Build Tools

Download the **Build Tools for Visual Studio** (not the full IDE) from  
[visualstudio.microsoft.com/visual-cpp-build-tools/](https://visualstudio.microsoft.com/visual-cpp-build-tools/)

During installation, select the **"Desktop development with C++"** workload. This provides the MSVC linker that Rust requires on Windows.

> **Note:** After installing Build Tools, restart your terminal so that `cl.exe` and `link.exe` are on the PATH.

---

## Step 1 — Clone / Obtain the Source

**Option A — Git clone:**
```cmd
git clone <repository-url> real_bom_tuning_tool
cd real_bom_tuning_tool
```

**Option B — Unzip archive:**  
Extract the provided zip to a folder such as `C:\Dev\real_bom_tuning_tool`, then open a terminal there:
```cmd
cd C:\Dev\real_bom_tuning_tool
```

---

## Step 2 — Create the Python Virtual Environment

All subsequent commands assume you are at the **project root** (`real_bom_tuning_tool\`).

```cmd
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install pyinstaller maturin
```

This installs:
- **PyQt5**, **numpy**, **scikit-rf**, **matplotlib** (from `requirements.txt`)
- **PyInstaller** — the exe packager
- **maturin** — the Rust/Python build bridge (>=1.13, <2.0)

> **Tip:** If `pip install` is slow, add `--no-deps` to skip dependency resolution for packages you know are compatible, or use `--index-url https://pypi.org/simple/` to force the standard index.

---

## Step 3 — Build the Rust Acceleration Module (`rf_sweep`)

Navigate into the Rust crate and compile with release optimisations:

```cmd
cd rf_network_tool\rf_sweep
maturin develop --release
cd ..\..
```

What this does:
- Compiles `lib.rs` with `opt-level = 3` and LTO (link-time optimisation) enabled
- Produces `rf_sweep.cp310-win_amd64.pyd` and installs it directly into `.venv\Lib\site-packages\`
- The `.pyd` is a native Windows DLL that Python imports as a regular module

**Verify the extension loaded correctly:**
```cmd
.venv\Scripts\python -c "import rf_sweep; print('rf_sweep OK')"
```

Expected output: `rf_sweep OK`

> **Warning:** If you see `ImportError: DLL load failed` or a wrong `.pyd` filename, make sure you created the venv with exactly Python 3.10 and that MSVC Build Tools are installed.

---

## Step 4 — (Optional) Run from Source to Verify

Before packaging, confirm the GUI launches cleanly:

```cmd
.venv\Scripts\python -m rf_network_tool.main
```

The RF Network Tool window should open. If it does, all dependencies are wired up correctly and you can proceed to packaging. Close the window when done.

> **Tip:** If imports fail at this stage, re-check Step 2 and Step 3. Fixing issues here is much faster than debugging a packaged exe.

---

## Step 5 — Build the Exe with `build_exe.bat`

**Option A — Double-click in File Explorer:**  
Double-click `build_exe.bat` at the project root.

**Option B — Run from a terminal:**
```cmd
cmd /c build_exe.bat
```

The script performs three phases:
1. Checks that `.venv\Scripts\pyinstaller.exe` exists
2. Runs `pyinstaller --clean rf_network_tool.spec`
3. Reports success and the output path

**Expected duration:** ~5 minutes on first run (PyInstaller collects files + UPX compression is applied).  
**Output:** `dist\rf_network_tool.exe` (~79 MB, single file, no console window)

> **Note:** The spec file bundles `rf_sweep.cp310-win_amd64.pyd` explicitly, along with `skrf` and `matplotlib` data files. Do **not** add common stdlib modules (`difflib`, `unittest`, `email`, `http`, `xml`, etc.) to the `excludes` list — they are pulled in transitively by `scipy` and removing them will cause runtime crashes.

---

## Step 6 — Deploy

Copy these three items to any folder on the target Windows machine:

```
<deployment folder>\
    rf_network_tool.exe      ← from dist\
    Inductors_BOM\           ← BOM data folder (Murata LQP02TQ inductors)
    Capacitors_BOM\          ← BOM data folder (Murata GJM0225 capacitors)
```

Launch `rf_network_tool.exe` directly — **no Python, Rust, or any other installation is required** on the target machine.

> **Note:** A `fleet_results\` folder is created automatically at runtime in the same directory as the exe.

---

## Troubleshooting

### `ModuleNotFoundError` at exe startup

**Symptom:** The exe crashes immediately or shows a missing-module error.  
**Cause:** A stdlib module was added to the `excludes` list in `rf_network_tool.spec`.  
**Fix:** Remove the offending module from `excludes` and rebuild. Do **not** exclude `difflib`, `unittest`, `email`, `http`, `xml`, or other stdlib modules — `scipy` and `scikit-rf` import them transitively.

---

### `rf_sweep.cp310-win_amd64.pyd` not found

**Symptom:** PyInstaller warns the `.pyd` file is missing, or the exe crashes with an import error for `rf_sweep`.  
**Cause:** The Rust extension was compiled against a different Python version, or `maturin develop` was not run.  
**Fix:**
1. Confirm the venv uses Python 3.10: `.venv\Scripts\python --version`
2. Re-run `maturin develop --release` from `rf_network_tool\rf_sweep\`
3. Re-run `build_exe.bat`

---

### PyInstaller DEPRECATION warning about `.venv\Lib\site-packages` in `pathex`

**Symptom:** Warning: *"DEPRECATION: ... site-packages path in pathex will not be supported in PyInstaller 7.0"*  
**Status:** Harmless in PyInstaller 6.x. `build_exe.bat` already invokes PyInstaller via `.venv\Scripts\pyinstaller.exe`, which is the recommended workaround.  
**Action needed when upgrading to PyInstaller 7.0:** Remove the site-packages path from `pathex` in `rf_network_tool.spec`.

---

### Debugging a crash in the packaged exe

The exe is built with `console=False`, so crash output is not visible. To see error messages:

1. Open `rf_network_tool.spec` and change:
   ```python
   console=False,
   ```
   to:
   ```python
   console=True,
   ```
2. Rebuild: `cmd /c build_exe.bat`
3. Run the new exe from a terminal (`cmd`): `dist\rf_network_tool.exe`
4. Read the traceback, fix the issue, then revert `console` to `False` before final packaging.

---

## Rebuilding After Code Changes

| What changed | Steps required |
|---|---|
| **Python only** (`.py` files) | Re-run `cmd /c build_exe.bat` |
| **Rust code** (`lib.rs`, `Cargo.toml`) | Run `maturin develop --release` (from `rf_network_tool\rf_sweep\`), then re-run `build_exe.bat` |
| **New Python dependency** | `.venv\Scripts\pip install <package>`, update `requirements.txt`, then re-run `build_exe.bat` |
| **PyInstaller spec changes** | Edit `rf_network_tool.spec`, then re-run `build_exe.bat` |
