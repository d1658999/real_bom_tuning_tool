# USAGE — RF Network Tool (Development / Source Mode)

## 1. Overview

`rf_network_tool` is a PyQt5 GUI for composing and analyzing cascaded RF networks from measured S-parameter (Touchstone) files. It is designed for RF front-end engineers working on diplexers, triplexers, and multi-band matching networks — letting you wire up component/sub-network `.snp` files, assign port roles (open, short, lumped BOM component, or signal I/O), and immediately visualize Smith chart, VSWR, and Insertion Loss results. The built-in **Fleet optimizer** sweeps your full BOM library with 5 parallel AI agents to find the component combination that best satisfies your impedance-matching targets.

---

## 2. Prerequisites (running from source)

- **Python 3.10** (other 3.x versions may work but are untested)
- A virtual environment with all dependencies installed (see `BUILD.md` for a full environment setup guide)

**Quick setup recap:**

```cmd
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

> **Note:** On Linux/macOS replace `.venv\Scripts\` with `.venv/bin/`.

**BOM folders** must exist inside the project directory (next to `main.py` when running from source, or next to the packaged `.exe`):

```
real_bom_tuning_tool\
├── Capacitors_BOM\     ← Murata GJM0225 series .s2p files (107 components)
├── Inductors_BOM\      ← Murata LQP02TQ series .s2p files (63 components)
└── rf_network_tool\
```

If either folder is missing, the `capacitor` / `inductor` BOM dropdowns will be empty and Fleet cannot run.

---

## 3. Launching the Application

```cmd
cd C:\path\to\real_bom_tuning_tool
.venv\Scripts\python -m rf_network_tool.main
```

The main window opens with three panels:

| Panel | Location | Purpose |
|-------|----------|---------|
| **File Panel** | Left | Add / remove `.snp` files |
| **Port Config Panel** | Center | Configure port terminations for the selected file |
| **Results Panel** | Right | Smith chart, VSWR, Insertion Loss plots |

---

## 4. Step-by-Step Workflow

### 4.1 Load `.snp` Files

1. Click **"Add Files…"** in the left panel.
2. Select one or more Touchstone files (`.s2p`, `.s3p`, `.s4p`, `.s10p`, …).
3. Each file appears in the list showing its filename and port count.
4. Click a file in the list to select it and configure its ports in the center panel.

> **Tip:** You can load as many files as needed — a typical diplexer design might include one file for the antenna feed network and two files for the TX/RX filter paths.

---

### 4.2 Configure Ports

With a file selected, the center panel shows a row for each port. Use the **Termination** dropdown on each row to assign a role:

| Termination | When to use |
|-------------|-------------|
| `open` | Port is left unconnected (high impedance termination) |
| `short` | Port is shorted to ground |
| `capacitor` | Insert a series/shunt capacitor chosen from the BOM library |
| `inductor` | Insert a series/shunt inductor chosen from the BOM library |
| `connect` | Internally wire this port to another file's port |
| `signal` | Expose as a network signal I/O port (s1, s2, s3, …) |

**For `capacitor` / `inductor`:**
A second dropdown appears listing all components found in `Capacitors_BOM\` or `Inductors_BOM\`. Select the desired component value.

**For `connect`:**
Two additional dropdowns appear — select the **target file** and **target port**. You must also open the target file and configure the corresponding port back to this file/port. Both ends of a connection must be set, or the cascade will be incorrect.

**For `signal`:**
A signal index dropdown appears. Assign `s1`, `s2`, `s3`, … to each intended I/O port of the final cascaded network.

> **Signal index convention (recommended):**
> - `s1` → TX path port
> - `s2` → RX path port
> - `s3` (or the highest index) → Antenna port
>
> The **highest signal index is treated as the antenna port.** Its Smith/VSWR traces will span all signal frequency bands.

**Minimum requirements for a valid cascade:**
- At least **two** ports must be assigned `signal` (one `s1`, one `s2`).
- For a triplexer add `signal s3`; for a 4-port multiplexer add `signal s4`.
- All remaining ports must be `open`, `short`, a BOM component, or `connect`.

---

### 4.3 Set Signal Frequency Ranges *(optional but strongly recommended for Fleet)*

At the bottom of the Port Config panel, expand the **"Signal Frequency Ranges (Fleet)"** group box.

- Each detected signal port (s1, s2, …) has its own **Start GHz** and **Stop GHz** fields.
- Enter the evaluation frequency band for each signal independently (e.g., s1 = 1.7–2.2 GHz for TX, s2 = 2.3–2.7 GHz for RX).
- The **Antenna union** label updates automatically to show the combined span across all signal bands.

These ranges control:
- The frequency axis used on all result plots.
- The evaluation window used by Fleet to score VSWR and Insertion Loss.

> **Note:** The frequency ranges must overlap the simulation grid of your `.snp` files. If there is no overlap, the results panel will display an empty plot with a "no data in [x–y GHz]" summary message.

---

### 4.4 Run Cascade

Click the **"Run Cascade"** button.

The tool cascades all loaded files according to your port wiring into a single multi-port network, then populates the Results panel:

**Smith Chart**
- Each non-antenna signal port shows a single S-parameter trace over its own frequency band.
- The antenna port (highest signal index) shows one labeled trace **per band**, using distinct line styles (`—` solid, `--` dashed, `···` dotted, `-·` dash-dot) for easy visual comparison.

**VSWR**
- One trace per signal port, plotted over its own frequency band.
- The antenna port trace uses NaN breaks between bands to avoid spurious connecting lines across frequency gaps.
- A VSWR of **2.0 or below** (return loss ≥ 9.5 dB) is the typical acceptability threshold.

**Insertion Loss (IL)**
- S21 (or equivalent) in dB from each non-antenna signal port to the antenna port, evaluated across that signal's frequency band.
- A summary line below each trace shows the minimum IL value and the frequency range.

---

### 4.5 Save / Load Configuration

Use the **File** menu to persist your port wiring setup:

| Action | Menu item | Effect |
|--------|-----------|--------|
| Save | `File › Save Config` | Writes the full `AppState` (all file paths, port terminations, component assignments, connect wiring, signal freq ranges) to a `.json` file you choose |
| Load | `File › Load Config` | Restores a previously saved configuration and reloads all `.snp` files |

> **Caution:** `.snp` file paths are stored as **absolute paths**. If you move the project folder or share the config file with a colleague, update the paths in the JSON manually or re-add the files.

---

### 4.6 Run Fleet Optimization

Click **"Run Fleet"** to open the **Fleet Progress** dialog.

Fleet launches **5 independent agent threads** that each sweep a random subset of BOM component combinations and evaluate the resulting cascade:

1. Each agent assigns capacitor/inductor values from the BOM to every BOM-terminated port.
2. The cascade is computed and scored against your signal frequency ranges:
   - **VSWR < 2.0 bonus** across all signal bands
   - Minimize Insertion Loss
   - Maximize Return Loss
3. After all 5 agents report their best result, a **Principal agent** compares the scores and selects the overall winner.

**Output files** are written to a `fleet_results\` folder created next to the loaded `.snp` files:

| File | Contents |
|------|----------|
| `agent_1_result.json` … `agent_5_result.json` | Component assignments and score for each agent |
| `fleet_comparison.png` | Side-by-side bar chart comparing agent metrics |
| `final_decision.png` | Smith chart / VSWR / IL plots for the winning configuration |
| `fleet_report.md` | Written reasoning, score breakdown, and winner announcement |

> **Performance note:** Running Fleet over a large BOM with many component-terminated ports can take several minutes. The progress bar in the dialog shows each agent's status in real time.

---

## 5. Understanding the Plots

### Smith Chart
The Smith chart is normalized to **50 Ω**. Each trace represents the input reflection coefficient (S11 or equivalent) of a signal port swept across its frequency band. A well-matched port traces a tight cluster near the center of the chart.

### VSWR
Voltage Standing Wave Ratio computed from the reflection coefficient. Key reference values:

| VSWR | Return Loss | Match quality |
|------|-------------|---------------|
| 1.0 | ∞ dB | Perfect match |
| **2.0** | **9.5 dB** | **Typical pass/fail threshold** |
| 3.0 | 6.0 dB | Poor |

### Insertion Loss (IL)
IL in dB between each non-antenna signal port and the antenna port (S21 equivalent). Lower absolute values (closer to 0 dB) indicate a more efficient path. The summary line reports the **minimum IL** (worst-case point) across the signal band.

---

## 6. Tips and Caveats

- **Frequency range coverage:** Signal frequency ranges must overlap the frequency grid of the `.snp` files. If you set 1.7–2.2 GHz but your `.snp` files only cover 0.5–1.5 GHz, the results panel will be empty.

- **Connect port pairs must be symmetric:** If you wire file A port 2 → file B port 1, you **must also** wire file B port 1 → file A port 2. Asymmetric connections lead to incorrect cascade results.

- **Unique signal indices per file:** Assign each signal index (s1, s2, …) to at most one port across **all** files. Duplicate assignments will produce an incorrect cascaded network without a warning.

- **BOM folder location:** `Capacitors_BOM\` and `Inductors_BOM\` must be siblings of `main.py` (source mode) or the `.exe` (packaged mode). Placing them elsewhere will result in empty component dropdowns.

- **Fleet on large BOMs:** With many BOM-terminated ports, the combinatorial space is large. Fleet uses a random-subset sweep strategy rather than exhaustive search, so results may vary between runs. Re-running Fleet multiple times and comparing `fleet_report.md` files is recommended for critical designs.

- **Saving before Fleet:** Always save your configuration (`File › Save Config`) before running Fleet. Fleet modifies the active component assignments; loading the saved config lets you restore your starting point.

---

## 7. Example Configurations

Several ready-to-use example JSON configs are included in the project root:

| File | Description |
|------|-------------|
| `example2.json` | 2-signal (diplexer) example |
| `example3.json` | 3-signal (triplexer) example |
| `example3_2.json` | Alternative triplexer wiring |

Load any of them with **`File › Load Config`** to see a fully wired port configuration and explore the workflow before building your own design.

---

## 8. Architecture Reference

```
rf_network_tool/
├── main.py                   # Entry point: QApplication + MainWindow
├── gui/
│   ├── __init__.py           # AppState, FileConfig, PortConfig dataclasses
│   ├── main_window.py        # Cascade worker, Fleet worker, Save/Load
│   ├── file_panel.py         # Add/remove .snp files list
│   ├── port_config_panel.py  # Per-port termination + Signal Freq Ranges UI
│   └── results_panel.py      # Matplotlib Smith, VSWR, IL visualization
└── backend/
    ├── bom_parser.py         # Scan BOM folders, parse component filenames/values
    ├── network_builder.py    # Port config → cascaded rf.Network (scikit-rf)
    └── fleet_optimizer.py    # 5-agent BOM sweep optimizer with risk scoring
```

For a deeper dive into the implementation, see the inline docstrings in each module.
