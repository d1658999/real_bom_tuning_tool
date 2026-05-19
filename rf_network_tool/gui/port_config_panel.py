"""Port Configuration Panel - configure terminations for each port of each file."""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QScrollArea, QGroupBox,
    QTableWidget, QTableWidgetItem, QComboBox, QSpinBox, QLineEdit,
    QLabel, QDoubleSpinBox, QHeaderView, QSizePolicy, QCheckBox
)
from PyQt5.QtCore import pyqtSignal, Qt
from typing import Dict, Optional, Tuple

from rf_network_tool.gui import AppState, PortConfig, SmithTargetConfig
from rf_network_tool.backend import bom_parser


TERM_TYPES = [
    "open", "short",
    "capacitor", "inductor",
    "open/ind", "open/cap", "open/ind/cap",
    "short/ind", "short/cap", "short/ind/cap",
    "connect", "signal",
]
_CAP_LIST = None
_IND_LIST = None


def _capacitors():
    global _CAP_LIST
    if _CAP_LIST is None:
        try:
            _CAP_LIST = bom_parser.list_capacitors()
        except Exception:
            _CAP_LIST = []
    return _CAP_LIST


def _inductors():
    global _IND_LIST
    if _IND_LIST is None:
        try:
            _IND_LIST = bom_parser.list_inductors()
        except Exception:
            _IND_LIST = []
    return _IND_LIST


class PortConfigPanel(QWidget):
    config_changed = pyqtSignal()

    def __init__(self, app_state: AppState, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._signal_freq_spinboxes: Dict[int, Tuple[QDoubleSpinBox, QDoubleSpinBox]] = {}
        self._smith_target_widgets: Dict[int, Tuple[
            QCheckBox, QDoubleSpinBox, QDoubleSpinBox, QDoubleSpinBox, QDoubleSpinBox
        ]] = {}
        self._refreshing_signal_freq = False
        self._refreshing_smith_targets = False
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        title = QLabel("Port Configuration")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        outer.addWidget(title)

        # Frequency row
        freq_row = QHBoxLayout()
        freq_row.addWidget(QLabel("Freq Start (GHz):"))
        self.freq_start_spin = QDoubleSpinBox()
        self.freq_start_spin.setRange(0.001, 100.0)
        self.freq_start_spin.setDecimals(3)
        self.freq_start_spin.setSingleStep(0.1)
        self.freq_start_spin.setValue(self.app_state.freq_start_ghz)
        freq_row.addWidget(self.freq_start_spin)

        freq_row.addWidget(QLabel("Freq Stop (GHz):"))
        self.freq_stop_spin = QDoubleSpinBox()
        self.freq_stop_spin.setRange(0.001, 100.0)
        self.freq_stop_spin.setDecimals(3)
        self.freq_stop_spin.setSingleStep(0.1)
        self.freq_stop_spin.setValue(self.app_state.freq_stop_ghz)
        freq_row.addWidget(self.freq_stop_spin)

        freq_row.addWidget(QLabel("Points:"))
        self.freq_pts_spin = QSpinBox()
        self.freq_pts_spin.setRange(2, 10001)
        self.freq_pts_spin.setValue(self.app_state.freq_npoints)
        freq_row.addWidget(self.freq_pts_spin)

        freq_row.addStretch()
        outer.addLayout(freq_row)

        self.freq_start_spin.valueChanged.connect(self._on_freq_changed)
        self.freq_stop_spin.valueChanged.connect(self._on_freq_changed)
        self.freq_pts_spin.valueChanged.connect(self._on_freq_changed)

        # Per-signal frequency range group
        outer.addWidget(self._create_signal_freq_group())
        outer.addWidget(self._create_smith_target_group())

        # Scrollable area for per-file groups
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_contents = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_contents)
        self.scroll_layout.setContentsMargins(4, 4, 4, 4)
        self.scroll_layout.setSpacing(8)
        self.scroll_layout.addStretch()
        self.scroll.setWidget(self.scroll_contents)
        outer.addWidget(self.scroll, stretch=1)

        self._refresh_signal_freq_group()
        self._refresh_smith_target_group()

    # ------------------------------------------------------------------
    # Signal frequency range group
    # ------------------------------------------------------------------

    def _create_signal_freq_group(self) -> QGroupBox:
        """Create collapsible group for per-signal frequency ranges."""
        group = QGroupBox("Signal Frequency Ranges (Fleet)")
        group.setVisible(False)
        self._signal_freq_group = group
        self._signal_freq_layout = QFormLayout()
        group.setLayout(self._signal_freq_layout)
        return group

    def _create_smith_target_group(self) -> QGroupBox:
        """Create optional per-signal special Smith target rows."""
        group = QGroupBox("Special Smith Targets (optional, ohms)")
        group.setVisible(False)
        self._smith_target_group = group
        self._smith_target_layout = QFormLayout()
        group.setLayout(self._smith_target_layout)
        return group

    def _current_signal_indices(self) -> set:
        signal_indices: set = set()
        for fc in self.app_state.files.values():
            for pc in fc.ports.values():
                if pc.term_type == "signal":
                    signal_indices.add(pc.signal_index)
        return signal_indices

    def _refresh_signal_freq_group(self):
        """Rebuild per-signal freq range rows based on current signal assignments."""
        if self._refreshing_signal_freq:
            return
        self._refreshing_signal_freq = True
        try:
            signal_indices = self._current_signal_indices()

            if len(signal_indices) < 2:
                self._signal_freq_group.setVisible(False)
                self._smith_target_group.setVisible(False)
                return

            ant_idx = max(signal_indices)
            non_ant = sorted(signal_indices - {ant_idx})

            # Clear existing rows
            while self._signal_freq_layout.rowCount() > 0:
                self._signal_freq_layout.removeRow(0)
            self._signal_freq_spinboxes.clear()

            for sig_idx in non_ant:
                start_val, stop_val = self.app_state.signal_freq_ranges.get(
                    sig_idx, (self.app_state.freq_start_ghz, self.app_state.freq_stop_ghz)
                )

                start_spin = QDoubleSpinBox()
                start_spin.setRange(0.001, 100.0)
                start_spin.setDecimals(3)
                start_spin.setSuffix(" GHz")
                start_spin.setValue(start_val)
                start_spin.setFixedWidth(100)

                stop_spin = QDoubleSpinBox()
                stop_spin.setRange(0.001, 100.0)
                stop_spin.setDecimals(3)
                stop_spin.setSuffix(" GHz")
                stop_spin.setValue(stop_val)
                stop_spin.setFixedWidth(100)

                self._signal_freq_spinboxes[sig_idx] = (start_spin, stop_spin)

                # Persist the displayed value immediately so plots always see correct range
                # even if the user never explicitly edits this spinbox.
                self.app_state.signal_freq_ranges[sig_idx] = (start_val, stop_val)

                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.addWidget(start_spin)
                row_layout.addWidget(QLabel("–"))
                row_layout.addWidget(stop_spin)
                row_layout.addStretch()
                self._signal_freq_layout.addRow(f"s{sig_idx}:", row_widget)

                start_spin.valueChanged.connect(
                    lambda _, si=sig_idx: self._on_signal_freq_changed(si)
                )
                stop_spin.valueChanged.connect(
                    lambda _, si=sig_idx: self._on_signal_freq_changed(si)
                )

            # Read-only antenna union row
            if self.app_state.signal_freq_ranges:
                all_starts = [self.app_state.signal_freq_ranges.get(
                    i, (self.app_state.freq_start_ghz, self.app_state.freq_stop_ghz))[0]
                    for i in non_ant]
                all_stops = [self.app_state.signal_freq_ranges.get(
                    i, (self.app_state.freq_start_ghz, self.app_state.freq_stop_ghz))[1]
                    for i in non_ant]
                union_txt = f"{min(all_starts):.3f} – {max(all_stops):.3f} GHz (union)"
            else:
                union_txt = (f"{self.app_state.freq_start_ghz:.3f} – "
                             f"{self.app_state.freq_stop_ghz:.3f} GHz (union)")
            ant_label = QLabel(union_txt)
            ant_label.setStyleSheet("color: gray; font-style: italic;")
            self._signal_freq_layout.addRow(f"s{ant_idx} (ant):", ant_label)
            self._ant_union_label = ant_label

            self._signal_freq_group.setVisible(True)
        finally:
            self._refreshing_signal_freq = False
        self._refresh_smith_target_group()

    def _refresh_smith_target_group(self):
        """Rebuild special Smith target rows for all signal ports."""
        if self._refreshing_smith_targets:
            return
        self._refreshing_smith_targets = True
        try:
            signal_indices = self._current_signal_indices()
            if len(signal_indices) < 2:
                self._smith_target_group.setVisible(False)
                return

            while self._smith_target_layout.rowCount() > 0:
                self._smith_target_layout.removeRow(0)
            self._smith_target_widgets.clear()

            ant_idx = max(signal_indices)
            for sig_idx in sorted(signal_indices):
                target = self.app_state.special_smith_targets.get(sig_idx)
                start_val, stop_val = self._default_target_range(sig_idx, ant_idx)
                enabled = False
                resistance = 50.0
                reactance = 0.0
                if target is not None:
                    enabled = target.enabled
                    start_val = target.start_ghz
                    stop_val = target.stop_ghz
                    resistance = target.resistance_ohm
                    reactance = target.reactance_ohm

                enable_check = QCheckBox("Use")
                enable_check.setChecked(enabled)

                start_spin = self._target_spin(start_val, " GHz", 0.001, 100.0, 3, 0.1, 92)
                stop_spin = self._target_spin(stop_val, " GHz", 0.001, 100.0, 3, 0.1, 92)
                r_spin = self._target_spin(resistance, " ohm", 0.0, 100000.0, 2, 1.0, 95)
                x_spin = self._target_spin(reactance, " ohm", -100000.0, 100000.0, 2, 1.0, 95)

                self._smith_target_widgets[sig_idx] = (
                    enable_check, start_spin, stop_spin, r_spin, x_spin
                )

                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(4)
                row_layout.addWidget(enable_check)
                row_layout.addWidget(QLabel("Range:"))
                row_layout.addWidget(start_spin)
                row_layout.addWidget(QLabel("-"))
                row_layout.addWidget(stop_spin)
                row_layout.addWidget(QLabel("R:"))
                row_layout.addWidget(r_spin)
                row_layout.addWidget(QLabel("X:"))
                row_layout.addWidget(x_spin)
                row_layout.addStretch()

                tag = " (ant)" if sig_idx == ant_idx else ""
                self._smith_target_layout.addRow(f"s{sig_idx}{tag}:", row_widget)

                enable_check.toggled.connect(
                    lambda _, si=sig_idx: self._on_smith_target_changed(si)
                )
                start_spin.valueChanged.connect(
                    lambda _, si=sig_idx: self._on_smith_target_changed(si)
                )
                stop_spin.valueChanged.connect(
                    lambda _, si=sig_idx: self._on_smith_target_changed(si)
                )
                r_spin.valueChanged.connect(
                    lambda _, si=sig_idx: self._on_smith_target_changed(si)
                )
                x_spin.valueChanged.connect(
                    lambda _, si=sig_idx: self._on_smith_target_changed(si)
                )

            hint = QLabel("Outside an enabled range, the optimizer still targets 50+0j ohm.")
            hint.setStyleSheet("color: gray; font-style: italic;")
            self._smith_target_layout.addRow("", hint)
            self._smith_target_group.setVisible(True)
        finally:
            self._refreshing_smith_targets = False

    def _target_spin(self, value: float, suffix: str, minimum: float, maximum: float,
                     decimals: int, step: float, width: int) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        spin.setValue(value)
        spin.setFixedWidth(width)
        return spin

    def _default_target_range(self, signal_idx: int, ant_idx: int) -> Tuple[float, float]:
        if signal_idx != ant_idx:
            return self.app_state.signal_freq_ranges.get(
                signal_idx,
                (self.app_state.freq_start_ghz, self.app_state.freq_stop_ghz),
            )
        if self.app_state.signal_freq_ranges:
            starts = [v[0] for v in self.app_state.signal_freq_ranges.values()]
            stops = [v[1] for v in self.app_state.signal_freq_ranges.values()]
            return min(starts), max(stops)
        return self.app_state.freq_start_ghz, self.app_state.freq_stop_ghz

    def _on_signal_freq_changed(self, signal_idx: int):
        start_spin, stop_spin = self._signal_freq_spinboxes[signal_idx]
        self.app_state.signal_freq_ranges[signal_idx] = (
            start_spin.value(), stop_spin.value()
        )
        self._refresh_ant_union_label()
        self.config_changed.emit()
        self._refresh_smith_target_group()

    def _on_smith_target_changed(self, signal_idx: int):
        if self._refreshing_smith_targets:
            return
        widgets = self._smith_target_widgets.get(signal_idx)
        if not widgets:
            return
        enable_check, start_spin, stop_spin, r_spin, x_spin = widgets
        if start_spin.value() > stop_spin.value():
            stop_spin.setValue(start_spin.value())
        self.app_state.special_smith_targets[signal_idx] = SmithTargetConfig(
            enabled=enable_check.isChecked(),
            start_ghz=start_spin.value(),
            stop_ghz=stop_spin.value(),
            resistance_ohm=r_spin.value(),
            reactance_ohm=x_spin.value(),
        )
        self.config_changed.emit()

    def _refresh_ant_union_label(self):
        """Update the read-only antenna union label."""
        if not hasattr(self, '_ant_union_label') or not self._signal_freq_spinboxes:
            return
        all_starts = [v[0].value() for v in self._signal_freq_spinboxes.values()]
        all_stops = [v[1].value() for v in self._signal_freq_spinboxes.values()]
        self._ant_union_label.setText(
            f"{min(all_starts):.3f} – {max(all_stops):.3f} GHz (union)"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self):
        """Rebuild entire scroll area from current app_state."""
        # Remove all existing group boxes (leave the trailing stretch)
        while self.scroll_layout.count() > 1:
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for file_id, fc in self.app_state.files.items():
            group = self._make_file_group(file_id, fc)
            self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, group)

        self._refresh_signal_freq_group()
        self._refresh_smith_target_group()

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _make_file_group(self, file_id: str, fc) -> QGroupBox:
        group = QGroupBox(fc.display_name)
        group.setStyleSheet("QGroupBox { font-weight: bold; }")
        vbox = QVBoxLayout(group)

        table = QTableWidget(fc.nports, 4)
        table.setHorizontalHeaderLabels(["Port #", "Label", "Termination", "Component / Connect"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        table.setColumnWidth(1, 90)   # just wider than "Port 10"; user can still resize
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QTableWidget.NoSelection)

        for row, port_num in enumerate(range(1, fc.nports + 1)):
            pc = fc.ports.get(port_num, PortConfig(label=f"Port {port_num}"))
            fc.ports[port_num] = pc

            # Col 0: port number (read-only)
            num_item = QTableWidgetItem(str(port_num))
            num_item.setFlags(Qt.ItemIsEnabled)
            table.setItem(row, 0, num_item)

            # Col 1: label
            label_edit = QLineEdit(pc.label)
            label_edit.textChanged.connect(
                lambda text, fid=file_id, pn=port_num: self._on_label_changed(fid, pn, text)
            )
            table.setCellWidget(row, 1, label_edit)

            # Col 2: termination type combobox
            term_combo = QComboBox()
            term_combo.addItems(TERM_TYPES)
            if pc.term_type in TERM_TYPES:
                term_combo.setCurrentIndex(TERM_TYPES.index(pc.term_type))
            table.setCellWidget(row, 2, term_combo)

            # Col 3: dynamic component widget (placeholder, set after connecting signal)
            placeholder = QLabel("")
            table.setCellWidget(row, 3, placeholder)

            # Connect after setting initial widget so we can build it properly
            term_combo.currentIndexChanged.connect(
                lambda idx, fid=file_id, pn=port_num, t=table, r=row, tc=term_combo:
                    self._on_term_changed(fid, pn, t, r, tc)
            )

            # Build initial component widget
            self._set_component_widget(table, row, file_id, port_num, pc)

        vbox.addWidget(table)
        return group

    def _set_component_widget(self, table: QTableWidget, row: int,
                               file_id: str, port_num: int, pc: PortConfig):
        term = pc.term_type
        widget = self._build_component_widget(term, file_id, port_num, pc)
        table.setCellWidget(row, 3, widget)

    # ------------------------------------------------------------------
    # Range-limit widget for fleet sweep ports
    # ------------------------------------------------------------------

    def _build_range_widget(self, file_id: str, port_num: int, pc: PortConfig,
                             show_ind: bool, show_cap: bool,
                             baseline: str = 'open') -> QWidget:
        """
        Compact widget with QDoubleSpinBox min/max limits and a live count label.
        Shown for open/* and short/* (series) termination types.
        baseline: 'open' for shunt-to-ground types, 'short' for series types.
        """
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(2, 0, 2, 0)
        h.setSpacing(4)

        count_label = QLabel()
        count_label.setStyleSheet("color: #0066cc; font-style: italic; font-size: 10px;")

        def _spin(value: float, suffix: str, decimals: int = 2, step: float = 0.1) -> QDoubleSpinBox:
            sb = QDoubleSpinBox()
            sb.setRange(0.0, 99999.0)
            sb.setDecimals(decimals)
            sb.setSingleStep(step)
            sb.setSuffix(suffix)
            sb.setValue(value)
            sb.setFixedWidth(90)
            return sb

        def _update_count():
            n_ind = n_cap = 0
            if show_ind:
                # Round to 2 dp to match setDecimals(2); Qt can return e.g. 0.5999 for 0.60
                lo = round(sb_ind_min.value(), 2)
                hi = round(sb_ind_max.value(), 2)
                n_ind = sum(1 for i in _inductors()
                            if lo <= round(i.get('value_nH', 0.0), 2) <= hi)
            if show_cap:
                lo = round(sb_cap_min.value(), 2)
                hi = round(sb_cap_max.value(), 2)
                n_cap = sum(1 for c in _capacitors()
                            if lo <= round(c.get('value_pF', 0.0), 2) <= hi)
            parts = []
            if show_ind:
                parts.append(f"{n_ind} ind")
            if show_cap:
                parts.append(f"{n_cap} cap")
            count_label.setText(f"🔍 {baseline} + {' + '.join(parts)}")

        def _on_ind_changed():
            # clamp: min ≤ max
            if sb_ind_min.value() > sb_ind_max.value():
                sb_ind_max.setValue(sb_ind_min.value())
            # Round to 2 dp so stored limits are clean and consistent with display
            pc.ind_min_nh = round(sb_ind_min.value(), 2)
            pc.ind_max_nh = round(sb_ind_max.value(), 2)
            _update_count()
            self.config_changed.emit()

        def _on_cap_changed():
            if sb_cap_min.value() > sb_cap_max.value():
                sb_cap_max.setValue(sb_cap_min.value())
            pc.cap_min_pf = round(sb_cap_min.value(), 2)
            pc.cap_max_pf = round(sb_cap_max.value(), 2)
            _update_count()
            self.config_changed.emit()

        if show_ind:
            h.addWidget(QLabel("ind:"))
            sb_ind_min = _spin(pc.ind_min_nh, " nH")
            sb_ind_max = _spin(pc.ind_max_nh, " nH")
            h.addWidget(sb_ind_min)
            h.addWidget(QLabel("–"))
            h.addWidget(sb_ind_max)
            sb_ind_min.valueChanged.connect(lambda _: _on_ind_changed())
            sb_ind_max.valueChanged.connect(lambda _: _on_ind_changed())
        else:
            sb_ind_min = sb_ind_max = None  # type: ignore[assignment]

        if show_cap:
            if show_ind:
                sep = QLabel("|")
                sep.setStyleSheet("color: #aaa;")
                h.addWidget(sep)
            h.addWidget(QLabel("cap:"))
            sb_cap_min = _spin(pc.cap_min_pf, " pF")
            sb_cap_max = _spin(pc.cap_max_pf, " pF")
            h.addWidget(sb_cap_min)
            h.addWidget(QLabel("–"))
            h.addWidget(sb_cap_max)
            sb_cap_min.valueChanged.connect(lambda _: _on_cap_changed())
            sb_cap_max.valueChanged.connect(lambda _: _on_cap_changed())
        else:
            sb_cap_min = sb_cap_max = None  # type: ignore[assignment]

        h.addWidget(count_label, stretch=1)
        _update_count()
        return container

    def _build_component_widget(self, term: str, file_id: str, port_num: int, pc: PortConfig) -> QWidget:
        if term in ("open", "short"):
            return QLabel("")

        elif term == "open/ind":
            return self._build_range_widget(file_id, port_num, pc,
                                            show_ind=True, show_cap=False,
                                            baseline='open')

        elif term == "open/cap":
            return self._build_range_widget(file_id, port_num, pc,
                                            show_ind=False, show_cap=True,
                                            baseline='open')

        elif term == "open/ind/cap":
            return self._build_range_widget(file_id, port_num, pc,
                                            show_ind=True, show_cap=True,
                                            baseline='open')

        elif term == "short/ind":
            return self._build_range_widget(file_id, port_num, pc,
                                            show_ind=True, show_cap=False,
                                            baseline='short')

        elif term == "short/cap":
            return self._build_range_widget(file_id, port_num, pc,
                                            show_ind=False, show_cap=True,
                                            baseline='short')

        elif term == "short/ind/cap":
            return self._build_range_widget(file_id, port_num, pc,
                                            show_ind=True, show_cap=True,
                                            baseline='short')

        elif term == "capacitor":
            caps = _capacitors()
            combo = QComboBox()
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            for c in caps:
                combo.addItem(c["display_name"], c["path"])
            # Restore previous selection
            if pc.component_path:
                for i in range(combo.count()):
                    if combo.itemData(i) == pc.component_path:
                        combo.setCurrentIndex(i)
                        break
            elif combo.count() > 0:
                pc.component_path = combo.itemData(0)
                pc.component_name = combo.itemText(0)

            combo.currentIndexChanged.connect(
                lambda idx, fid=file_id, pn=port_num, cb=combo:
                    self._on_component_changed(fid, pn, cb)
            )
            container = QWidget()
            h = QHBoxLayout(container)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(combo, stretch=1)
            lock = QLabel("🔒 Fixed in Fleet")
            lock.setStyleSheet("color: #888; font-size: 10px; font-style: italic;")
            h.addWidget(lock)
            return container

        elif term == "inductor":
            inds = _inductors()
            combo = QComboBox()
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            for ind in inds:
                combo.addItem(ind["display_name"], ind["path"])
            if pc.component_path:
                for i in range(combo.count()):
                    if combo.itemData(i) == pc.component_path:
                        combo.setCurrentIndex(i)
                        break
            elif combo.count() > 0:
                pc.component_path = combo.itemData(0)
                pc.component_name = combo.itemText(0)

            combo.currentIndexChanged.connect(
                lambda idx, fid=file_id, pn=port_num, cb=combo:
                    self._on_component_changed(fid, pn, cb)
            )
            container = QWidget()
            h = QHBoxLayout(container)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(combo, stretch=1)
            lock = QLabel("🔒 Fixed in Fleet")
            lock.setStyleSheet("color: #888; font-size: 10px; font-style: italic;")
            h.addWidget(lock)
            return container

        elif term == "connect":
            container = QWidget()
            h = QHBoxLayout(container)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(QLabel("File:"))

            file_combo = QComboBox()
            other_files = [(fid, fc.display_name)
                           for fid, fc in self.app_state.files.items()
                           if fid != file_id]
            for fid, dname in other_files:
                file_combo.addItem(dname, fid)

            if pc.connect_to_file:
                for i in range(file_combo.count()):
                    if file_combo.itemData(i) == pc.connect_to_file:
                        file_combo.setCurrentIndex(i)
                        break

            h.addWidget(file_combo)
            h.addWidget(QLabel("Port:"))

            port_spin = QSpinBox()
            port_spin.setRange(1, 99)
            port_spin.setValue(pc.connect_to_port or 1)
            h.addWidget(port_spin)

            def on_connect_changed(_, fid=file_id, pn=port_num, fc_cb=file_combo, ps=port_spin):
                self._on_connect_changed(fid, pn, fc_cb, ps)

            file_combo.currentIndexChanged.connect(on_connect_changed)
            port_spin.valueChanged.connect(on_connect_changed)
            return container

        elif term == "signal":
            combo = QComboBox()
            combo.addItems(["s1", "s2", "s3", "s4"])
            combo.setCurrentIndex(max(0, (pc.signal_index or 1) - 1))
            combo.currentIndexChanged.connect(
                lambda idx, fid=file_id, pn=port_num:
                    self._on_signal_changed(fid, pn, idx + 1)
            )
            return combo

        return QLabel("")

    # ------------------------------------------------------------------
    # Slot handlers
    # ------------------------------------------------------------------

    def _on_freq_changed(self):
        self.app_state.freq_start_ghz = self.freq_start_spin.value()
        self.app_state.freq_stop_ghz = self.freq_stop_spin.value()
        self.app_state.freq_npoints = self.freq_pts_spin.value()
        self.config_changed.emit()

    def _on_label_changed(self, file_id: str, port_num: int, text: str):
        if file_id in self.app_state.files:
            self.app_state.files[file_id].ports[port_num].label = text
        self.config_changed.emit()

    def _on_term_changed(self, file_id: str, port_num: int,
                          table: QTableWidget, row: int, term_combo: QComboBox):
        term = term_combo.currentText()
        if file_id not in self.app_state.files:
            return
        pc = self.app_state.files[file_id].ports[port_num]
        pc.term_type = term
        # Reset component fields
        pc.component_path = ""
        pc.component_name = ""

        # Rebuild component widget
        widget = self._build_component_widget(term, file_id, port_num, pc)
        table.setCellWidget(row, 3, widget)
        self._refresh_signal_freq_group()
        self.config_changed.emit()

    def _on_component_changed(self, file_id: str, port_num: int, combo: QComboBox):
        if file_id not in self.app_state.files:
            return
        pc = self.app_state.files[file_id].ports[port_num]
        pc.component_path = combo.currentData() or ""
        pc.component_name = combo.currentText()
        self.config_changed.emit()

    def _on_connect_changed(self, file_id: str, port_num: int,
                             file_combo: QComboBox, port_spin: QSpinBox):
        if file_id not in self.app_state.files:
            return
        pc = self.app_state.files[file_id].ports[port_num]
        pc.connect_to_file = file_combo.currentData() or ""
        pc.connect_to_port = port_spin.value()
        self.config_changed.emit()

    def _on_signal_changed(self, file_id: str, port_num: int, signal_idx: int):
        if file_id not in self.app_state.files:
            return
        self.app_state.files[file_id].ports[port_num].signal_index = signal_idx
        self._refresh_signal_freq_group()
        self._refresh_smith_target_group()
        self.config_changed.emit()
