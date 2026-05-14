"""RF Network Cascade Tool - Main entry point."""
import sys
from pathlib import Path

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication

from rf_network_tool.gui.main_window import MainWindow


def _resource_path(relative_path: str) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base_path / relative_path


def _set_windows_app_id():
    if sys.platform != "win32":
        return

    try:
        import ctypes

        app_id = "pricewu.rf_network_tool.cascade.1"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        # Non-fatal: the Qt window icon still works if Windows app-id setup fails.
        pass


def _apply_windows_taskbar_icon(window, icon_path: Path):
    if sys.platform != "win32" or not icon_path.exists():
        return

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd = wintypes.HWND(int(window.winId()))

        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        GCLP_HICON = -14
        GCLP_HICONSM = -34
        SM_CXICON = 11
        SM_CYICON = 12
        SM_CXSMICON = 49
        SM_CYSMICON = 50

        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SendMessageW.restype = wintypes.LPARAM
        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]

        def load_icon(cx_metric: int, cy_metric: int):
            return user32.LoadImageW(
                None,
                str(icon_path),
                IMAGE_ICON,
                user32.GetSystemMetrics(cx_metric),
                user32.GetSystemMetrics(cy_metric),
                LR_LOADFROMFILE,
            )

        small_icon = load_icon(SM_CXSMICON, SM_CYSMICON)
        big_icon = load_icon(SM_CXICON, SM_CYICON)
        if not small_icon or not big_icon:
            return

        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small_icon)
        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big_icon)

        set_class_long = (
            user32.SetClassLongPtrW
            if ctypes.sizeof(ctypes.c_void_p) == 8
            else user32.SetClassLongW
        )
        set_class_long.restype = ctypes.c_void_p
        set_class_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        set_class_long(hwnd, GCLP_HICONSM, small_icon)
        set_class_long(hwnd, GCLP_HICON, big_icon)

        window._native_icon_handles = (small_icon, big_icon)
    except Exception:
        pass


def main():
    _set_windows_app_id()
    app = QApplication(sys.argv)
    icon_path = _resource_path("rf_network_tool/assets/rf_network_tool_icon.ico")
    icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
    if icon_path.exists():
        app.setWindowIcon(icon)
    app.setStyle("Fusion")
    window = MainWindow()
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.show()
    QTimer.singleShot(0, lambda: _apply_windows_taskbar_icon(window, icon_path))
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
