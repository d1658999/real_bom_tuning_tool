from __future__ import annotations

import sys

from PyQt5.QtWidgets import QApplication

from rf_kpi_compare_tool.app import CompareMainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("RF KPI Compare Tool")
    app.setStyle("Fusion")
    window = CompareMainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
