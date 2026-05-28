from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QDoubleSpinBox,
)
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
import numpy as np

from rf_kpi_compare_tool.comparison import (
    DIFFERENCE_HEADERS,
    SUMMARY_HEADERS,
    ComparisonResult,
    PARAMETER_INDEXES,
    LoadedNetwork,
    build_summary_lines,
    common_frequency_range,
    compare_networks,
    export_excel_report,
)


COLORS = [
    "#1f77b4",
    "#d62728",
    "#2ca02c",
    "#ff7f0e",
    "#9467bd",
    "#17becf",
    "#8c564b",
    "#e377c2",
]


class CompareMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.loaded_networks: list[LoadedNetwork] = []
        self.latest_result: ComparisonResult | None = None

        self.setWindowTitle("RF KPI Compare Tool")
        self.resize(1520, 920)
        self._build_ui()
        self._clear_results("Add at least two .s2p files to start comparing.")
        self._refresh_state()

    def _build_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Horizontal, self)
        root_layout.addWidget(splitter)

        controls = QWidget(self)
        controls.setMinimumWidth(360)
        control_layout = QVBoxLayout(controls)
        control_layout.setContentsMargins(8, 8, 8, 8)
        control_layout.setSpacing(8)

        title = QLabel("2-Port S-Parameter Comparison")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        title.setWordWrap(True)
        control_layout.addWidget(title)

        intro = QLabel(
            "Load two or more .s2p files, choose a frequency window within the shared range, "
            "then compare Smith charts, transmission, return loss, and VSWR in one view."
        )
        intro.setWordWrap(True)
        control_layout.addWidget(intro)

        self.file_list = QListWidget(self)
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.setMinimumHeight(220)
        control_layout.addWidget(self.file_list)

        file_button_row = QHBoxLayout()
        self.add_files_button = QPushButton("Add .s2p Files...", self)
        self.remove_files_button = QPushButton("Remove Selected", self)
        self.clear_files_button = QPushButton("Clear All", self)
        file_button_row.addWidget(self.add_files_button)
        file_button_row.addWidget(self.remove_files_button)
        file_button_row.addWidget(self.clear_files_button)
        control_layout.addLayout(file_button_row)

        range_group = QGroupBox("Frequency Range (GHz)", self)
        range_layout = QVBoxLayout(range_group)
        form_layout = QFormLayout()
        self.common_range_label = QLabel("No files loaded")
        self.start_freq_spin = QDoubleSpinBox(self)
        self.stop_freq_spin = QDoubleSpinBox(self)
        for spin_box in (self.start_freq_spin, self.stop_freq_spin):
            spin_box.setDecimals(6)
            spin_box.setRange(0.0, 1_000_000.0)
            spin_box.setSingleStep(0.1)
            spin_box.setKeyboardTracking(False)
        form_layout.addRow("Shared range", self.common_range_label)
        form_layout.addRow("Start", self.start_freq_spin)
        form_layout.addRow("Stop", self.stop_freq_spin)
        range_layout.addLayout(form_layout)
        self.use_common_range_button = QPushButton("Use Shared Range", self)
        range_layout.addWidget(self.use_common_range_button)
        control_layout.addWidget(range_group)

        action_row = QHBoxLayout()
        self.compare_button = QPushButton("Compare", self)
        self.export_pdf_button = QPushButton("Export PDF", self)
        self.export_excel_button = QPushButton("Export Excel", self)
        action_row.addWidget(self.compare_button)
        action_row.addWidget(self.export_pdf_button)
        action_row.addWidget(self.export_excel_button)
        control_layout.addLayout(action_row)

        self.hint_label = QLabel("Only valid 2-port .s2p files are accepted.")
        self.hint_label.setWordWrap(True)
        control_layout.addWidget(self.hint_label)
        control_layout.addStretch(1)

        right_panel = QTabWidget(self)

        plot_tab = QWidget(self)
        plot_layout = QVBoxLayout(plot_tab)
        plot_layout.setContentsMargins(4, 4, 4, 4)
        plot_layout.setSpacing(4)
        self.figure = Figure(figsize=(12, 9), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        plot_layout.addWidget(self.toolbar)
        plot_layout.addWidget(self.canvas)
        right_panel.addTab(plot_tab, "Plots")

        self.metrics_table = self._create_table(SUMMARY_HEADERS)
        metrics_tab = QWidget(self)
        metrics_layout = QVBoxLayout(metrics_tab)
        metrics_layout.setContentsMargins(4, 4, 4, 4)
        metrics_layout.addWidget(self.metrics_table)
        right_panel.addTab(metrics_tab, "Metrics")

        self.differences_table = self._create_table(DIFFERENCE_HEADERS)
        differences_tab = QWidget(self)
        differences_layout = QVBoxLayout(differences_tab)
        differences_layout.setContentsMargins(4, 4, 4, 4)
        differences_layout.addWidget(self.differences_table)
        right_panel.addTab(differences_tab, "Differences")

        splitter.addWidget(controls)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 1140])

        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)

        self.add_files_button.clicked.connect(self._add_files)
        self.remove_files_button.clicked.connect(self._remove_selected_files)
        self.clear_files_button.clicked.connect(self._clear_loaded_files)
        self.use_common_range_button.clicked.connect(self._apply_shared_range)
        self.compare_button.clicked.connect(self._run_comparison)
        self.export_pdf_button.clicked.connect(self._export_pdf)
        self.export_excel_button.clicked.connect(self._export_excel)

    def _create_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers), self)
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select 2-Port Touchstone Files",
            "",
            "Touchstone 2-Port Files (*.s2p *.S2P);;All Files (*)",
        )
        if not paths:
            return

        known_paths = {loaded.path for loaded in self.loaded_networks}
        load_errors: list[str] = []
        added = 0
        for path_str in paths:
            path = Path(path_str).expanduser().resolve()
            if path in known_paths:
                continue

            try:
                loaded = LoadedNetwork.from_path(
                    path, self._make_unique_display_name(path))
            except ValueError as exc:
                load_errors.append(f"{path.name}: {exc}")
                continue

            self.loaded_networks.append(loaded)
            known_paths.add(path)
            added += 1

        if added:
            self._refresh_file_list()
            self._refresh_state()
            self.statusBar().showMessage(f"Loaded {added} file(s).", 4000)

        if load_errors:
            QMessageBox.warning(self, "Load Error", "\n\n".join(load_errors))

    def _remove_selected_files(self) -> None:
        selected_paths = {
            Path(item.data(Qt.UserRole))
            for item in self.file_list.selectedItems()
            if item.data(Qt.UserRole)
        }
        if not selected_paths:
            return

        self.loaded_networks = [
            loaded for loaded in self.loaded_networks if loaded.path not in selected_paths
        ]
        self._refresh_file_list()
        self._refresh_state()
        self.statusBar().showMessage("Selected files removed.", 3000)

    def _clear_loaded_files(self) -> None:
        if not self.loaded_networks:
            return
        self.loaded_networks.clear()
        self._refresh_file_list()
        self._refresh_state()
        self.statusBar().showMessage("All files cleared.", 3000)

    def _refresh_file_list(self) -> None:
        self.file_list.clear()
        for loaded in self.loaded_networks:
            item = QListWidgetItem(
                f"{loaded.display_name}  [{loaded.min_freq_ghz:.6f} - {loaded.max_freq_ghz:.6f} GHz]"
            )
            item.setToolTip(str(loaded.path))
            item.setData(Qt.UserRole, str(loaded.path))
            self.file_list.addItem(item)

    def _refresh_state(self) -> None:
        self.latest_result = None
        shared_range = self._shared_range_for_ui()
        if shared_range is None:
            self.common_range_label.setText("Need at least one file")
            self.start_freq_spin.setEnabled(False)
            self.stop_freq_spin.setEnabled(False)
            self.use_common_range_button.setEnabled(False)
            self.compare_button.setEnabled(False)
            self.export_pdf_button.setEnabled(False)
            self.export_excel_button.setEnabled(False)
            self._clear_results(
                "Add at least two .s2p files to start comparing.")
            return

        range_start, range_stop = shared_range
        self.common_range_label.setText(
            f"{range_start:.6f} - {range_stop:.6f}")
        for spin_box in (self.start_freq_spin, self.stop_freq_spin):
            spin_box.setEnabled(True)
            spin_box.setRange(range_start, range_stop)

        self.use_common_range_button.setEnabled(True)

        start_value = self.start_freq_spin.value()
        stop_value = self.stop_freq_spin.value()
        if start_value < range_start or start_value >= range_stop:
            self.start_freq_spin.setValue(range_start)
        if stop_value > range_stop or stop_value <= range_start:
            self.stop_freq_spin.setValue(range_stop)
        if self.start_freq_spin.value() >= self.stop_freq_spin.value():
            self.start_freq_spin.setValue(range_start)
            self.stop_freq_spin.setValue(range_stop)

        can_compare = len(self.loaded_networks) >= 2
        self.compare_button.setEnabled(can_compare)
        self.export_pdf_button.setEnabled(False)
        self.export_excel_button.setEnabled(False)
        self._clear_results(
            "Choose a valid frequency window inside the shared range, then click Compare."
        )

    def _shared_range_for_ui(self) -> tuple[float, float] | None:
        if not self.loaded_networks:
            return None
        if len(self.loaded_networks) == 1:
            only_item = self.loaded_networks[0]
            return only_item.min_freq_ghz, only_item.max_freq_ghz
        return common_frequency_range(self.loaded_networks)

    def _apply_shared_range(self) -> None:
        shared_range = self._shared_range_for_ui()
        if shared_range is None:
            return
        self.start_freq_spin.setValue(shared_range[0])
        self.stop_freq_spin.setValue(shared_range[1])

    def _run_comparison(self) -> None:
        try:
            result = compare_networks(
                self.loaded_networks,
                self.start_freq_spin.value(),
                self.stop_freq_spin.value(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Comparison Error", str(exc))
            return

        self.latest_result = result
        self._plot_result(result)
        self._populate_metrics_table(result)
        self._populate_differences_table(result)
        self.export_pdf_button.setEnabled(True)
        self.export_excel_button.setEnabled(True)
        self.statusBar().showMessage(
            (
                f"Compared {len(result.file_order)} files across "
                f"{result.selected_start_ghz:.6f} - {result.selected_stop_ghz:.6f} GHz."
            ),
            5000,
        )

    def _plot_result(self, result: ComparisonResult) -> None:
        self.figure.clear()
        axes = self.figure.subplots(3, 2)
        self.figure.subplots_adjust(hspace=0.28, wspace=0.20)

        ax_s11_smith = axes[0][0]
        ax_s22_smith = axes[0][1]
        ax_s21 = axes[1][0]
        ax_s12 = axes[1][1]
        ax_return_loss = axes[2][0]
        ax_vswr = axes[2][1]

        self._draw_smith_background(ax_s11_smith, "Smith Chart - S11")
        self._draw_smith_background(ax_s22_smith, "Smith Chart - S22")

        freq = result.frequency_ghz
        for index, file_name in enumerate(result.file_order):
            color = COLORS[index % len(COLORS)]
            traces = result.traces[file_name]
            magnitude_db = result.magnitude_db[file_name]
            return_loss_db = result.return_loss_db[file_name]
            vswr = result.vswr[file_name]

            ax_s11_smith.plot(
                traces["S11"].real,
                traces["S11"].imag,
                color=color,
                linewidth=1.2,
                label=file_name,
            )
            ax_s22_smith.plot(
                traces["S22"].real,
                traces["S22"].imag,
                color=color,
                linewidth=1.2,
                label=file_name,
            )
            ax_s21.plot(
                freq, magnitude_db["S21"], color=color, linewidth=1.4, label=file_name)
            ax_s12.plot(
                freq, magnitude_db["S12"], color=color, linewidth=1.4, label=file_name)
            ax_return_loss.plot(
                freq,
                return_loss_db["S11"],
                color=color,
                linewidth=1.4,
                linestyle="-",
                label=f"{file_name} S11",
            )
            ax_return_loss.plot(
                freq,
                return_loss_db["S22"],
                color=color,
                linewidth=1.2,
                linestyle="--",
                label=f"{file_name} S22",
            )
            ax_vswr.plot(
                freq,
                vswr["S11"],
                color=color,
                linewidth=1.4,
                linestyle="-",
                label=f"{file_name} S11",
            )
            ax_vswr.plot(
                freq,
                vswr["S22"],
                color=color,
                linewidth=1.2,
                linestyle="--",
                label=f"{file_name} S22",
            )

        self._format_frequency_axis(
            ax_s21, "Insertion Loss - S21", "Magnitude (dB)", result)
        self._format_frequency_axis(
            ax_s12, "Reverse Transmission - S12", "Magnitude (dB)", result)
        self._format_frequency_axis(
            ax_return_loss, "Return Loss - S11 / S22", "Return Loss (dB)", result)
        self._format_frequency_axis(
            ax_vswr, "VSWR - S11 / S22", "VSWR", result)
        ax_vswr.axhline(2.0, color="#2ca02c", linestyle=":",
                        linewidth=1.0, label="VSWR=2")

        for smith_axis in (ax_s11_smith, ax_s22_smith):
            smith_axis.legend(fontsize=7, loc="upper right")
        for axis in (ax_s21, ax_s12, ax_return_loss, ax_vswr):
            axis.legend(fontsize=7, loc="best")

        self.canvas.draw_idle()

    def _format_frequency_axis(
        self,
        axis,
        title: str,
        y_label: str,
        result: ComparisonResult,
    ) -> None:
        axis.set_title(title, fontsize=10)
        axis.set_xlabel("Frequency (GHz)", fontsize=9)
        axis.set_ylabel(y_label, fontsize=9)
        axis.set_xlim(result.selected_start_ghz, result.selected_stop_ghz)
        axis.grid(True, linewidth=0.4)
        axis.tick_params(labelsize=8)

    def _draw_smith_background(self, axis, title: str) -> None:
        theta = np.linspace(0.0, 2.0 * np.pi, 360)
        axis.plot(np.cos(theta), np.sin(theta), color="black", linewidth=0.8)
        axis.axhline(0.0, color="black", linewidth=0.4)
        axis.axvline(0.0, color="black", linewidth=0.4)
        axis.set_xlim(-1.1, 1.1)
        axis.set_ylim(-1.1, 1.1)
        axis.set_aspect("equal", adjustable="box")
        axis.grid(True, linewidth=0.3)
        axis.set_title(title, fontsize=10)
        axis.set_xlabel("Real", fontsize=8)
        axis.set_ylabel("Imag", fontsize=8)
        axis.tick_params(labelsize=7)

    def _populate_metrics_table(self, result: ComparisonResult) -> None:
        self.metrics_table.setRowCount(len(result.summary_rows))
        for row_index, row in enumerate(result.summary_rows):
            values = [
                row.file_name,
                row.parameter,
                self._format_value(row.min_db),
                self._format_value(row.max_db),
                self._format_optional_value(row.min_return_loss_db),
                self._format_optional_value(row.max_return_loss_db),
                self._format_optional_value(row.min_vswr),
                self._format_optional_value(row.max_vswr),
            ]
            for column_index, value in enumerate(values):
                self.metrics_table.setItem(
                    row_index, column_index, QTableWidgetItem(value))
        self.metrics_table.resizeColumnsToContents()

    def _populate_differences_table(self, result: ComparisonResult) -> None:
        self.differences_table.setRowCount(len(result.delta_rows))
        for row_index, row in enumerate(result.delta_rows):
            values = [
                row.baseline_file,
                row.compared_file,
                row.parameter,
                self._format_value(row.max_abs_delta_db),
                self._format_value(row.mean_abs_delta_db),
                self._format_value(row.frequency_at_max_ghz),
            ]
            for column_index, value in enumerate(values):
                self.differences_table.setItem(
                    row_index, column_index, QTableWidgetItem(value))
        self.differences_table.resizeColumnsToContents()

    def _export_pdf(self) -> None:
        if self.latest_result is None:
            return

        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Export Comparison Report (PDF)",
            "rf_kpi_comparison_report.pdf",
            "PDF Files (*.pdf)",
        )
        if not destination:
            return

        try:
            with PdfPages(destination) as pdf:
                pdf.savefig(self.figure, dpi=180, bbox_inches="tight")
                self._append_summary_pages(pdf, self.latest_result)
        except Exception as exc:  # pragma: no cover - UI path only
            QMessageBox.critical(self, "Export Error",
                                 f"Could not write PDF report:\n{exc}")
            return

        self.statusBar().showMessage(
            f"PDF report exported to {destination}", 5000)

    def _append_summary_pages(self, pdf: PdfPages, result: ComparisonResult) -> None:
        lines = build_summary_lines(result)
        chunk_size = 42
        for start_index in range(0, len(lines), chunk_size):
            summary_figure = Figure(figsize=(8.27, 11.69), tight_layout=True)
            axis = summary_figure.add_subplot(1, 1, 1)
            axis.axis("off")
            axis.text(
                0.02,
                0.98,
                "\n".join(lines[start_index: start_index + chunk_size]),
                va="top",
                ha="left",
                fontsize=9,
                fontfamily="monospace",
            )
            pdf.savefig(summary_figure, dpi=180, bbox_inches="tight")

    def _export_excel(self) -> None:
        if self.latest_result is None:
            return

        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Export Comparison Report (Excel)",
            "rf_kpi_comparison_report.xlsx",
            "Excel Files (*.xlsx)",
        )
        if not destination:
            return

        plot_image = BytesIO()
        self.figure.savefig(plot_image, format="png",
                            dpi=180, bbox_inches="tight")
        plot_image.seek(0)

        try:
            export_excel_report(self.latest_result, destination, plot_image)
        except Exception as exc:  # pragma: no cover - UI path only
            QMessageBox.critical(self, "Export Error",
                                 f"Could not write Excel report:\n{exc}")
            return

        self.statusBar().showMessage(
            f"Excel report exported to {destination}", 5000)

    def _clear_results(self, message: str) -> None:
        self.figure.clear()
        axis = self.figure.add_subplot(1, 1, 1)
        axis.axis("off")
        axis.text(0.5, 0.5, message, ha="center",
                  va="center", fontsize=12, color="#666666")
        self.canvas.draw_idle()
        self.metrics_table.setRowCount(0)
        self.differences_table.setRowCount(0)

    def _make_unique_display_name(self, path: Path) -> str:
        existing_names = {
            loaded.display_name for loaded in self.loaded_networks}
        candidate = path.name
        if candidate not in existing_names:
            return candidate

        counter = 2
        while True:
            candidate = f"{path.stem} ({counter}){path.suffix}"
            if candidate not in existing_names:
                return candidate
            counter += 1

    @staticmethod
    def _format_value(value: float) -> str:
        return f"{value:.6f}"

    @staticmethod
    def _format_optional_value(value: float | None) -> str:
        if value is None:
            return "N/A"
        return f"{value:.6f}"
