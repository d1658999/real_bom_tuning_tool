"""Render the RF Network Tool icon assets from the SVG source."""
import os
from pathlib import Path

from PIL import Image
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QGuiApplication, QImage, QPainter
from PyQt5.QtSvg import QSvgRenderer


SIZES = (16, 32, 48, 64, 128, 256)

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "rf_network_tool" / "assets"
SVG_PATH = ASSET_DIR / "rf_network_tool_icon.svg"
ICO_PATH = ASSET_DIR / "rf_network_tool_icon.ico"


def render_pngs() -> list[Path]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        raise RuntimeError(f"Unable to load SVG icon: {SVG_PATH}")

    png_paths = []
    for size in SIZES:
        image = QImage(size, size, QImage.Format_ARGB32)
        image.fill(Qt.transparent)

        painter = QPainter(image)
        renderer.render(painter)
        painter.end()

        png_path = ASSET_DIR / f"rf_network_tool_icon_{size}.png"
        if not image.save(str(png_path)):
            raise RuntimeError(f"Unable to write PNG icon: {png_path}")
        png_paths.append(png_path)

    app.quit()
    return png_paths


def build_ico() -> None:
    source = ASSET_DIR / "rf_network_tool_icon_256.png"
    image = Image.open(source).convert("RGBA")
    image.save(ICO_PATH, sizes=[(size, size) for size in SIZES])


def main() -> None:
    render_pngs()
    build_ico()
    print(f"Wrote {ICO_PATH}")


if __name__ == "__main__":
    main()
