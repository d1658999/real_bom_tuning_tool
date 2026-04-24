"""RF Network Cascade Tool - Main entry point."""
import sys
from PyQt5.QtWidgets import QApplication
from rf_network_tool.gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
