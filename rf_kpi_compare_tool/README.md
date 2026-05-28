# RF KPI Compare Tool

This tool compares two or more 2-port Touchstone `.s2p` files over a shared frequency range and overlays the key RF traces in one GUI.

Features:
- Multi-file `.s2p` selection with validation for valid 2-port Touchstone data.
- Shared-range frequency selection so comparisons only run where every file has data.
- Overlaid Smith charts for `S11` and `S22`.
- Overlaid transmission plots for `S21` and `S12`.
- Return-loss and VSWR overlays for `S11` and `S22`.
- PDF export with the plots and summary pages.
- Excel export with summary tables, difference tables, trace data, and the plot image.

Run it from the repository root:

```powershell
python -m rf_kpi_compare_tool.main
```

Build a single Windows exe from the repository root or by double-clicking the batch file in this folder:

```cmd
cmd /c rf_kpi_compare_tool\build_exe.bat
```

Build output:
- `dist\rf_kpi_compare_tool.exe`

Build prerequisites:
- `.venv` exists in the repository root.
- `.venv\Scripts\pyinstaller.exe` is installed.
- Runtime dependencies are installed from `requirements.txt`.

Workflow:
1. Add two or more `.s2p` files.
2. Review the shared frequency range shown in the left panel.
3. Set the start and stop frequency in GHz.
4. Click `Compare`.
5. Export a PDF or Excel report if needed.

Notes:
- The tool uses the first loaded file as the baseline for pairwise delta reporting.
- If two files do not overlap in frequency, the comparison is blocked until the file set changes.
- Excel export requires the `xlsxwriter` dependency listed in `requirements.txt`.
