---
name: rf-bom-tuning-tool
description: "Use when working on the real_bom_tuning_tool repository, the RF Network Tool GUI, Touchstone .snp files, cascade wiring, port terminations, fleet optimization, BOM sweeps, the rf_sweep Rust extension, Windows packaging, or example JSON configs."
---

# RF BOM Tuning Tool

Use this skill when the task is specific to this repository. It packages the repo's main code paths, constraints, and the narrowest useful validation paths.

## Start From A Concrete Anchor

Route the task to one owned surface before exploring broadly:

- Python GUI: `rf_network_tool/gui/`
- Cascade assembly and port ordering: `rf_network_tool/backend/network_builder.py`
- Fleet optimization and result ranking: `rf_network_tool/backend/fleet_optimizer.py`
- BOM parsing and component discovery: `rf_network_tool/backend/bom_parser.py`
- Rust acceleration: `rf_network_tool/rf_sweep/src/lib.rs`
- App startup and Windows shell behavior: `rf_network_tool/main.py`
- Packaging: `rf_network_tool.spec`, `build_exe.bat`
- Repro fixtures: `example2.json`, `example3.json`, `example3_2.json`, `example3_5.json`

## Repository Facts

- The main application is a PyQt5 GUI launched with `python -m rf_network_tool.main`.
- The app builds cascaded RF networks from Touchstone `.sNp` files using `scikit-rf`.
- BOM libraries live in `Capacitors_BOM/` and `Inductors_BOM/`; if either folder is missing, BOM dropdowns and Fleet runs will not behave correctly.
- The Rust extension lives in `rf_network_tool/rf_sweep/` and is built with `maturin develop --release`.
- The Python extension output is tied to CPython 3.10 (`cp310`). Treat Python 3.10 as a hard build constraint unless the task is explicitly a version migration.
- Saved JSON configs use absolute paths, so portability issues are expected unless paths are rewritten.
- A valid final cascade needs at least two signal ports.
- `connect` wiring must be symmetric on both ends of a port pair.
- The highest signal index is treated as the antenna port in plotting and evaluation behavior.

## Working Strategy

1. Prefer the smallest existing repro before inventing new inputs.
2. Step to the owning abstraction instead of staying in UI wiring or glue code.
3. Preserve domain rules unless the user asks to change them.
4. Validate with the narrowest useful command immediately after the first edit.

Use these routing rules:

- UI behavior, widget state, save/load interactions: work in `rf_network_tool/gui/`.
- Network math, termination semantics, connection order, signal ordering: work in `network_builder.py`.
- Sweep ranking, agent outputs, report content, combination search behavior: work in `fleet_optimizer.py`.
- Missing components, wrong displayed values, BOM range issues: work in `bom_parser.py`.
- Per-port sweep performance or termination update math: work in `rf_network_tool/rf_sweep/src/lib.rs`.

## Common Commands

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\pip install pyinstaller maturin
.\.venv\Scripts\python -m rf_network_tool.main
Push-Location rf_network_tool\rf_sweep
maturin develop --release
Pop-Location
cmd /c build_exe.bat
```

## Validation Guidance

- Python GUI or backend change: prefer `.\.venv\Scripts\python -m rf_network_tool.main` if the virtual environment exists.
- Rust extension change: rebuild the extension before validating any Python path that imports `rf_sweep`.
- Packaging change: use `cmd /c build_exe.bat`.
- Config or documentation change: verify the touched file and review the diff if no runnable check exists.
- Do not rebuild the packaged executable for a pure Python logic change unless the user asks for packaging validation.

## Domain Guardrails

- Treat terminations as shunt-style unless the code and task clearly indicate a different model.
- Keep BOM directories and example configs intact unless the request is explicitly about changing repo data.
- Reuse existing Touchstone fixtures before adding synthetic RF data.
- Report environment blockers clearly, especially missing `.venv`, missing BOM folders, or Python version mismatches.

## Completion Standard

When using this skill, finish with:

- What changed
- What was validated
- Any remaining hard constraints, especially Python 3.10, BOM directory requirements, or absolute-path config behavior