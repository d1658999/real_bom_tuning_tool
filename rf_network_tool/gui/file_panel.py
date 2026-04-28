"""File Management Panel for loading .snp S-parameter files."""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QPushButton, QLabel, QFileDialog, QListWidgetItem, QMessageBox
)
from PyQt5.QtCore import pyqtSignal
from pathlib import Path
import skrf as rf

from rf_network_tool.gui import AppState, FileConfig, PortConfig


class FilePanel(QWidget):
    files_changed = pyqtSignal()

    def __init__(self, app_state: AppState, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Loaded S-Parameter Files")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.file_list.setMinimumHeight(200)
        layout.addWidget(self.file_list)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add Files...")
        self.remove_btn = QPushButton("Remove Selected")
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.remove_btn)
        layout.addLayout(btn_row)

        self.add_btn.clicked.connect(self._add_files)
        self.remove_btn.clicked.connect(self._remove_selected)

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open S-Parameter Files",
            "",
            "Touchstone Files (*.s1p *.s2p *.s3p *.s4p *.s5p *.s6p *.s7p "
            "*.s8p *.s9p *.s10p *.s11p *.s12p *.s*p);;All Files (*)"
        )
        added = 0
        for path in paths:
            try:
                net = rf.Network(path)
                nports = net.nports
            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Could not load {path}:\n{e}")
                continue

            stem = Path(path).stem
            file_id = self._unique_id(stem)

            ports = {
                p: PortConfig(label=f"Port {p}")
                for p in range(1, nports + 1)
            }

            self.app_state.files[file_id] = FileConfig(
                file_id=file_id,
                file_path=path,
                display_name=Path(path).name,
                nports=nports,
                ports=ports
            )
            added += 1

        if added:
            self.refresh_list()
            self.files_changed.emit()

    def _unique_id(self, stem: str) -> str:
        if stem not in self.app_state.files:
            return stem
        i = 2
        while f"{stem}_{i}" in self.app_state.files:
            i += 1
        return f"{stem}_{i}"

    def _remove_selected(self):
        selected = self.file_list.selectedItems()
        if not selected:
            return
        for item in selected:
            file_id = item.data(32)  # Qt.UserRole = 32
            if file_id and file_id in self.app_state.files:
                del self.app_state.files[file_id]
        self.refresh_list()
        self.files_changed.emit()

    def refresh_list(self):
        self.file_list.clear()
        for file_id, fc in self.app_state.files.items():
            item = QListWidgetItem(f"{fc.display_name}  ({fc.nports} ports)")
            item.setData(32, file_id)
            self.file_list.addItem(item)
