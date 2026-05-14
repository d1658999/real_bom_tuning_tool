"""Main application window for the RF Network Cascade Tool."""
import json
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QSplitter, QToolBar, QAction, QMessageBox,
    QFileDialog, QStatusBar, QWidget,
    QDialog, QVBoxLayout, QTextEdit, QPushButton, QLabel,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QTextCursor

import skrf as rf

from rf_network_tool.gui import AppState, FileConfig, PortConfig
from rf_network_tool.gui.file_panel import FilePanel
from rf_network_tool.gui.port_config_panel import PortConfigPanel
from rf_network_tool.gui.results_panel import ResultsPanel
from rf_network_tool.backend.network_builder import NetworkConfig, PortTermination, build_network_from_config
from rf_network_tool.backend.fleet_optimizer import FleetOptimizer


class _CascadeWorker(QObject):
    """Runs the network build in a background thread."""
    finished = pyqtSignal(object)   # rf.Network
    error    = pyqtSignal(str)

    def __init__(self, config: NetworkConfig):
        super().__init__()
        self._config = config

    def run(self):
        try:
            net = build_network_from_config(self._config)
            self.finished.emit(net)
        except Exception as e:
            self.error.emit(str(e))


class _FleetWorker(QObject):
    """Runs the fleet optimizer in a background thread."""
    progress = pyqtSignal(str)   # log line
    finished = pyqtSignal(str)   # output directory path
    error    = pyqtSignal(str)

    def __init__(self, app_state, output_dir: str):
        super().__init__()
        self._app_state = app_state
        self._output_dir = output_dir

    def run(self):
        try:
            optimizer = FleetOptimizer(
                self._app_state,
                progress_callback=self.progress.emit,
            )
            optimizer.run(output_dir=self._output_dir)
            self.finished.emit(self._output_dir)
        except Exception as e:
            import traceback
            self.progress.emit(f"\n[TRACEBACK]\n{traceback.format_exc()}")
            self.error.emit(str(e))


class _FleetProgressDialog(QDialog):
    """Modal dialog that shows live fleet-optimizer progress."""

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self._app_state = app_state
        self._thread: QThread = None
        self._worker: _FleetWorker = None
        self._build_ui()
        self._start()

    def _build_ui(self):
        self.setWindowTitle("Fleet Optimizer – Running…")
        self.setMinimumSize(720, 480)
        layout = QVBoxLayout(self)

        self._status = QLabel("Fleet optimizer is running…  Please wait.")
        self._status.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._status)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFontFamily("Courier New")
        self._log.setFontPointSize(9)
        layout.addWidget(self._log, stretch=1)

        self._close_btn = QPushButton("Close")
        self._close_btn.setEnabled(False)
        self._close_btn.clicked.connect(self.accept)
        layout.addWidget(self._close_btn)

    def _start(self):
        from pathlib import Path
        first_fc = next(iter(self._app_state.files.values()))
        output_dir = str(Path(first_fc.file_path).parent / "fleet_results")

        self._worker = _FleetWorker(self._app_state, output_dir)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._append)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _append(self, msg: str):
        self._log.append(msg)
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.End)
        self._log.setTextCursor(cursor)

    def _on_done(self, output_dir: str):
        self._status.setText(f"✓  Done!   Results saved to:  {output_dir}")
        self._status.setStyleSheet("color: green; font-weight: bold;")
        self._close_btn.setEnabled(True)
        self.setWindowTitle("Fleet Optimizer – Complete")

    def _on_error(self, msg: str):
        self._status.setText(f"✗  Error: {msg}")
        self._status.setStyleSheet("color: red; font-weight: bold;")
        self._append(f"\n✗ ERROR: {msg}")
        self._close_btn.setEnabled(True)
        self.setWindowTitle("Fleet Optimizer – Failed")


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.app_state = AppState()
        self._cascade_thread: QThread = None
        self._cascade_worker: _CascadeWorker = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.setWindowTitle("RF Network Cascade Tool")
        self.resize(1400, 900)

        # Panels
        self.file_panel   = FilePanel(self.app_state)
        self.port_panel   = PortConfigPanel(self.app_state)
        self.result_panel = ResultsPanel()

        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.file_panel)
        splitter.addWidget(self.port_panel)
        splitter.addWidget(self.result_panel)
        splitter.setSizes([300, 500, 600])
        self.setCentralWidget(splitter)

        # Toolbar
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.run_cascade_action = QAction("▶  Run Cascade", self)
        self.run_cascade_action.setEnabled(False)
        toolbar.addAction(self.run_cascade_action)

        self.export_snp_action = QAction("Export SNP", self)
        self.export_snp_action.setEnabled(False)
        toolbar.addAction(self.export_snp_action)

        self.run_fleet_action = QAction("⚡  Run Fleet", self)
        self.run_fleet_action.setEnabled(False)
        toolbar.addAction(self.run_fleet_action)

        toolbar.addSeparator()

        save_action = QAction("💾  Save Config", self)
        toolbar.addAction(save_action)

        load_action = QAction("📂  Load Config", self)
        toolbar.addAction(load_action)

        # Status bar
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

        # Connections
        self.file_panel.files_changed.connect(self._on_files_changed)
        self.port_panel.config_changed.connect(self._on_config_changed)
        self.run_cascade_action.triggered.connect(self._run_cascade)
        self.export_snp_action.triggered.connect(self._export_result_snp)
        self.run_fleet_action.triggered.connect(self._run_fleet)
        save_action.triggered.connect(self._save_config)
        load_action.triggered.connect(self._load_config)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_files_changed(self):
        self._invalidate_result(clear_plot=True)
        self.port_panel.refresh()
        self._update_run_button()

    def _on_config_changed(self):
        self._invalidate_result(clear_plot=False)
        self.statusBar().showMessage(
            "Configuration changed. Previous plot is still shown until Run Cascade."
        )
        self._update_run_button()

    def _update_run_button(self):
        """Enable Run Cascade when files loaded AND at least s1+s2 are defined as consecutive signals."""
        has_files = bool(self.app_state.files)
        signal_indices = set()
        for fc in self.app_state.files.values():
            for pc in fc.ports.values():
                if pc.term_type == "signal":
                    signal_indices.add(pc.signal_index)
        # Need at minimum s1 and s2, and all present indices must be consecutive from 1
        n = len(signal_indices)
        consecutive = (n >= 2) and (signal_indices == set(range(1, n + 1)))
        ready = has_files and consecutive
        self.run_cascade_action.setEnabled(ready)
        self.run_fleet_action.setEnabled(ready)

    def _run_cascade(self):
        try:
            config = self._build_network_config()
        except Exception as e:
            QMessageBox.critical(self, "Config Error", str(e))
            return

        self._invalidate_result(clear_plot=False)
        self.statusBar().showMessage("Running cascade...")
        self.run_cascade_action.setEnabled(False)

        self._cascade_worker = _CascadeWorker(config)
        self._cascade_thread = QThread()
        self._cascade_worker.moveToThread(self._cascade_thread)
        self._cascade_thread.started.connect(self._cascade_worker.run)
        self._cascade_worker.finished.connect(self._on_cascade_done)
        self._cascade_worker.error.connect(self._on_cascade_error)
        self._cascade_worker.finished.connect(self._cascade_thread.quit)
        self._cascade_worker.error.connect(self._cascade_thread.quit)
        self._cascade_thread.start()

    def _on_cascade_done(self, net: rf.Network):
        self.app_state.result_network = net
        self.export_snp_action.setEnabled(True)
        self.result_panel.plot_network(
            net,
            self.app_state.freq_start_ghz,
            self.app_state.freq_stop_ghz,
            signal_freq_ranges=self.app_state.signal_freq_ranges,
        )
        npts = net.nports
        nf   = len(net.f)
        self.statusBar().showMessage(
            f"Done: {npts}-port network, {nf} points  "
            f"({self.app_state.freq_start_ghz:.3f}–{self.app_state.freq_stop_ghz:.3f} GHz)"
        )
        self._update_run_button()

    def _on_cascade_error(self, msg: str):
        QMessageBox.critical(self, "Cascade Error", msg)
        self.statusBar().showMessage("Error during cascade. Previous plot is still shown.")
        self._update_run_button()

    def _export_result_snp(self):
        net = self.app_state.result_network
        if net is None:
            QMessageBox.information(
                self,
                "No Cascade Result",
                "Run Cascade first, then export the resulting SNP file.",
            )
            return

        ext = f".s{net.nports}p"
        default_path = self._default_export_path(ext)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Cascade Result",
            str(default_path),
            f"Touchstone (*{ext});;All Files (*)",
        )
        if not path:
            return

        export_path = self._normalize_touchstone_path(Path(path), ext)
        try:
            net.write_touchstone(
                filename=export_path.with_suffix("").name,
                dir=str(export_path.parent),
                write_z0=True,
            )
            self.statusBar().showMessage(f"SNP exported to {export_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _run_fleet(self):
        dialog = _FleetProgressDialog(self.app_state, self)
        dialog.exec_()

    def _invalidate_result(self, clear_plot: bool = True):
        """Invalidate the exportable result, optionally clearing the visible plot."""
        self.app_state.result_network = None
        self.export_snp_action.setEnabled(False)
        if clear_plot:
            self.result_panel.clear()

    def _default_export_path(self, ext: str) -> Path:
        if self.app_state.files:
            first_fc = next(iter(self.app_state.files.values()))
            base_dir = Path(first_fc.file_path).parent
        else:
            base_dir = Path.cwd()
        return base_dir / f"cascade_result{ext}"

    @staticmethod
    def _normalize_touchstone_path(path: Path, ext: str) -> Path:
        if not path.suffix:
            return path.with_suffix(ext)
        if path.suffix.lower() == ext.lower():
            return path
        return path.with_name(f"{path.name}{ext}")

    # ------------------------------------------------------------------
    # Config build helper
    # ------------------------------------------------------------------

    def _build_network_config(self) -> NetworkConfig:
        cfg = NetworkConfig(
            freq_start_ghz=self.app_state.freq_start_ghz,
            freq_stop_ghz=self.app_state.freq_stop_ghz,
            freq_npoints=self.app_state.freq_npoints,
        )
        for file_id, fc in self.app_state.files.items():
            cfg.networks[file_id] = fc.file_path
            cfg.terminations[file_id] = {}
            for port_num, pc in fc.ports.items():
                t = PortTermination(type=pc.term_type)
                if pc.term_type in ("capacitor", "inductor"):
                    if not pc.component_path:
                        raise ValueError(
                            f"File '{fc.display_name}' port {port_num}: "
                            f"no component selected for {pc.term_type}"
                        )
                    t.component_path = pc.component_path
                elif pc.term_type == "connect":
                    if not pc.connect_to_file:
                        raise ValueError(
                            f"File '{fc.display_name}' port {port_num}: "
                            "no target file selected for 'connect'"
                        )
                    t.connect_to = (pc.connect_to_file, pc.connect_to_port)
                elif pc.term_type == "signal":
                    t.signal_port_index = pc.signal_index
                cfg.terminations[file_id][port_num] = t
        return cfg

    # ------------------------------------------------------------------
    # Save / Load config
    # ------------------------------------------------------------------

    def _save_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Configuration", "", "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        data = {
            "freq_start_ghz": self.app_state.freq_start_ghz,
            "freq_stop_ghz":  self.app_state.freq_stop_ghz,
            "freq_npoints":   self.app_state.freq_npoints,
            "signal_freq_ranges": {
                str(k): [v[0], v[1]]
                for k, v in self.app_state.signal_freq_ranges.items()
            },
            "files": {}
        }
        for file_id, fc in self.app_state.files.items():
            ports_data = {}
            for pnum, pc in fc.ports.items():
                ports_data[str(pnum)] = {
                    "label":          pc.label,
                    "term_type":      pc.term_type,
                    "component_path": pc.component_path,
                    "component_name": pc.component_name,
                    "connect_to_file": pc.connect_to_file,
                    "connect_to_port": pc.connect_to_port,
                    "signal_index":   pc.signal_index,
                    "ind_min_nh":     pc.ind_min_nh,
                    "ind_max_nh":     pc.ind_max_nh,
                    "cap_min_pf":     pc.cap_min_pf,
                    "cap_max_pf":     pc.cap_max_pf,
                }
            data["files"][file_id] = {
                "file_path":    fc.file_path,
                "display_name": fc.display_name,
                "nports":       fc.nports,
                "ports":        ports_data,
            }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self.statusBar().showMessage(f"Config saved to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def _load_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Configuration", "", "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e))
            return

        self.app_state.freq_start_ghz = data.get("freq_start_ghz", 3.3)
        self.app_state.freq_stop_ghz  = data.get("freq_stop_ghz",  5.0)
        self.app_state.freq_npoints   = data.get("freq_npoints",   201)
        raw_sfr = data.get("signal_freq_ranges", {})
        self.app_state.signal_freq_ranges = {
            int(k): (float(v[0]), float(v[1]))
            for k, v in raw_sfr.items()
        }
        self._invalidate_result(clear_plot=True)
        self.app_state.files.clear()

        for file_id, fd in data.get("files", {}).items():
            ports = {}
            for pnum_str, pd in fd.get("ports", {}).items():
                ports[int(pnum_str)] = PortConfig(
                    label          = pd.get("label", ""),
                    term_type      = pd.get("term_type", "open"),
                    component_path = pd.get("component_path", ""),
                    component_name = pd.get("component_name", ""),
                    connect_to_file= pd.get("connect_to_file", ""),
                    connect_to_port= pd.get("connect_to_port", 1),
                    signal_index   = pd.get("signal_index", 1),
                    ind_min_nh     = pd.get("ind_min_nh", 0.0),
                    ind_max_nh     = pd.get("ind_max_nh", 10000.0),
                    cap_min_pf     = pd.get("cap_min_pf", 0.0),
                    cap_max_pf     = pd.get("cap_max_pf", 10000.0),
                )
            self.app_state.files[file_id] = FileConfig(
                file_id      = file_id,
                file_path    = fd.get("file_path", ""),
                display_name = fd.get("display_name", file_id),
                nports       = fd.get("nports", len(ports)),
                ports        = ports,
            )

        self.file_panel.refresh_list()
        self.port_panel.refresh()
        # Sync frequency spinboxes
        self.port_panel.freq_start_spin.setValue(self.app_state.freq_start_ghz)
        self.port_panel.freq_stop_spin.setValue(self.app_state.freq_stop_ghz)
        self.port_panel.freq_pts_spin.setValue(self.app_state.freq_npoints)
        self._update_run_button()
        self.statusBar().showMessage(f"Config loaded from {path}")
