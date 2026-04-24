"""Port Configuration Panel - configure terminations for each port of each file."""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QGroupBox,
    QTableWidget, QTableWidgetItem, QComboBox, QSpinBox, QLineEdit,
    QLabel, QDoubleSpinBox, QHeaderView, QSizePolicy
)
from PyQt5.QtCore import pyqtSignal, Qt
from typing import Optional

from rf_network_tool.gui import AppState, PortConfig
from rf_network_tool.backend import bom_parser


TERM_TYPES = ["open", "short", "capacitor", "inductor", "connect", "signal"]
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
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
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

    def _build_component_widget(self, term: str, file_id: str, port_num: int, pc: PortConfig) -> QWidget:
        if term in ("open", "short"):
            return QLabel("")

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
            return combo

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
            return combo

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
            combo.addItems(["s1", "s2"])
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
        self.config_changed.emit()
