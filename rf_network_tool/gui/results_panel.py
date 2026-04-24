"""Results Display Panel - embedded matplotlib plots for RF network analysis."""
import numpy as np
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
import matplotlib.patches as mpatches
import skrf as rf


class ResultsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.fig = Figure(figsize=(8, 7), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

        self._init_axes()
        self.clear()

    def _init_axes(self):
        self.fig.clear()
        self.ax_smith = self.fig.add_subplot(2, 2, 1)
        self.ax_vswr  = self.fig.add_subplot(2, 2, 2)
        self.ax_il    = self.fig.add_subplot(2, 2, 3)
        self.ax_text  = self.fig.add_subplot(2, 2, 4)
        self.ax_text.axis("off")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def clear(self):
        """Clear all plots and show placeholder message."""
        self._init_axes()
        for ax, title in [
            (self.ax_smith, "Smith Chart"),
            (self.ax_vswr,  "VSWR"),
            (self.ax_il,    "Insertion Loss (dB)"),
        ]:
            ax.set_title(title, fontsize=9)
            ax.text(0.5, 0.5, "No results yet", ha="center", va="center",
                    transform=ax.transAxes, color="gray", fontsize=9)

        self.ax_text.set_title("Summary", fontsize=9)
        self.ax_text.text(0.1, 0.5, "No results yet", va="center",
                          transform=self.ax_text.transAxes, fontsize=9, color="gray")
        self.canvas.draw_idle()

    def plot_network(self, net: rf.Network, freq_start: float, freq_stop: float):
        """Plot a 2-port rf.Network: Smith, VSWR, IL, and text summary."""
        self._init_axes()

        freqs_ghz = net.f / 1e9

        # ---- Smith chart ------------------------------------------------
        try:
            net.plot_s_smith(m=0, n=0, ax=self.ax_smith, color="blue",
                             label="S11", show_legend=False)
            net.plot_s_smith(m=1, n=1, ax=self.ax_smith, color="red",
                             label="S22", show_legend=False)
        except Exception:
            # Fallback: manual normalised plot on unit disk
            self._draw_smith_background(self.ax_smith)
            s11 = net.s[:, 0, 0]
            s22 = net.s[:, 1, 1]
            self.ax_smith.plot(s11.real, s11.imag, color="blue", label="S11", linewidth=1)
            self.ax_smith.plot(s22.real, s22.imag, color="red",  label="S22", linewidth=1)

        # VSWR=2 circle: |Γ| = (VSWR-1)/(VSWR+1) = 1/3
        vswr2_r = 1.0 / 3.0
        circle = mpatches.Circle((0, 0), vswr2_r, fill=False,
                                  linestyle="--", color="green",
                                  linewidth=1, label="VSWR=2")
        self.ax_smith.add_patch(circle)
        self.ax_smith.legend(fontsize=7, loc="upper right")
        self.ax_smith.set_title("Smith Chart (S11/S22)", fontsize=9)

        # ---- VSWR -------------------------------------------------------
        s11_mag = np.abs(net.s[:, 0, 0])
        s22_mag = np.abs(net.s[:, 1, 1])
        s11_mag = np.clip(s11_mag, 0, 0.9999)
        s22_mag = np.clip(s22_mag, 0, 0.9999)
        vswr11 = (1 + s11_mag) / (1 - s11_mag)
        vswr22 = (1 + s22_mag) / (1 - s22_mag)

        self.ax_vswr.plot(freqs_ghz, vswr11, color="blue", label="VSWR(S11)", linewidth=1)
        self.ax_vswr.plot(freqs_ghz, vswr22, color="red",  label="VSWR(S22)", linewidth=1)
        self.ax_vswr.axhline(2.0, color="green", linestyle="--", linewidth=0.8, label="VSWR=2")
        self.ax_vswr.set_xlabel("Frequency (GHz)", fontsize=8)
        self.ax_vswr.set_ylabel("VSWR", fontsize=8)
        self.ax_vswr.set_title("VSWR", fontsize=9)
        self.ax_vswr.legend(fontsize=7)
        self.ax_vswr.set_xlim(freq_start, freq_stop)
        self.ax_vswr.grid(True, linewidth=0.4)
        self.ax_vswr.tick_params(labelsize=7)

        # ---- Insertion Loss ---------------------------------------------
        s21_db = 20 * np.log10(np.clip(np.abs(net.s[:, 1, 0]), 1e-15, None))
        self.ax_il.plot(freqs_ghz, s21_db, color="purple", label="S21 (IL)", linewidth=1)
        self.ax_il.set_xlabel("Frequency (GHz)", fontsize=8)
        self.ax_il.set_ylabel("Magnitude (dB)", fontsize=8)
        self.ax_il.set_title("Insertion Loss (S21)", fontsize=9)
        self.ax_il.legend(fontsize=7)
        self.ax_il.set_xlim(freq_start, freq_stop)
        self.ax_il.grid(True, linewidth=0.4)
        self.ax_il.tick_params(labelsize=7)

        # ---- Text summary -----------------------------------------------
        worst_vswr11 = float(np.max(vswr11))
        worst_vswr22 = float(np.max(vswr22))
        min_il = float(np.min(s21_db))
        npts = len(freqs_ghz)
        summary = (
            f"Freq Range:  {freq_start:.3f} – {freq_stop:.3f} GHz\n"
            f"Points:      {npts}\n\n"
            f"Worst VSWR(S11): {worst_vswr11:.2f}\n"
            f"Worst VSWR(S22): {worst_vswr22:.2f}\n\n"
            f"Min S21 (IL):    {min_il:.2f} dB\n"
            f"Avg S21 (IL):    {float(np.mean(s21_db)):.2f} dB"
        )
        self.ax_text.set_title("Summary", fontsize=9)
        self.ax_text.text(0.05, 0.95, summary, va="top", transform=self.ax_text.transAxes,
                          fontsize=8, fontfamily="monospace",
                          bbox=dict(boxstyle="round", facecolor="lightyellow", alpha=0.6))

        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _draw_smith_background(self, ax):
        """Draw a minimal Smith chart background circle."""
        theta = np.linspace(0, 2 * np.pi, 360)
        ax.plot(np.cos(theta), np.sin(theta), "k", linewidth=0.8)
        ax.axhline(0, color="k", linewidth=0.5)
        ax.set_xlim(-1.1, 1.1)
        ax.set_ylim(-1.1, 1.1)
        ax.set_aspect("equal")
        ax.grid(True, linewidth=0.3)
