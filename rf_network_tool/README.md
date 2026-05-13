# RF Network Cascade Tool

A PyQt5 GUI for cascading multiple S-parameter (.snp) Touchstone files,
configuring port terminations, and running fleet optimization.

## Launch

```bash
cd C:\Users\pricewu\Documents\SideProject\real_bom_tuning_tool
python -m rf_network_tool.main
```

## Workflow

1. **Add Files** — load .snp files (Add Files... button)
2. **Configure Ports** — for each port, set:
   - `open` / `short` / `capacitor` / `inductor` / `connect` / `signal`
   - For capacitor/inductor: pick from BOM dropdown
   - For connect: select target file and port
   - Mark exactly one port as **signal s1** and one as **signal s2**
3. **Run Cascade** - cascades networks and shows Smith chart, VSWR, IL
4. **Export SNP** - after reviewing the cascade result, save it as a Touchstone `.sNp` file
5. **Run Fleet** - sweeps all BOM combinations, 5 agents optimize, Principal selects winner

## Output (fleet_results/)

- `agent_N_result.json` — component assignments per agent
- `fleet_comparison.png` — side-by-side metrics
- `final_decision.png` — winner's plots
- `fleet_report.md` — written report with reasoning

## BOM Directories

| Directory | Contents |
|-----------|----------|
| `Capacitors_BOM/` | 107 Murata GJM0225 series capacitor `.s2p` files |
| `Inductors_BOM/`  | 63 Murata LQP02TQ series inductor `.s2p` files  |

## Architecture

```
rf_network_tool/
├── main.py                  # Entry point
├── gui/
│   ├── __init__.py          # AppState, FileConfig, PortConfig dataclasses
│   ├── main_window.py       # MainWindow + CascadeWorker + FleetWorker + FleetProgressDialog
│   ├── file_panel.py        # Load/remove .snp files
│   ├── port_config_panel.py # Per-port termination configuration
│   └── results_panel.py     # Matplotlib: Smith, VSWR, IL plots
└── backend/
    ├── bom_parser.py        # Scan BOM folders, parse component values
    ├── network_builder.py   # NetworkConfig → 2-port rf.Network (scikit-rf)
    └── fleet_optimizer.py   # 5-agent sweep optimizer with risk scoring
```
