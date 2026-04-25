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
        """Plot an N-port rf.Network: Smith, VSWR, IL, and text summary.

        Convention: antenna port = last port (index N-1).
        Signal ports: 0 .. N-2. IL = antenna-to-each-signal transmission.
        """
        self._init_axes()
        freqs_ghz = net.f / 1e9
        n = net.nports
        ant = n - 1  # antenna port index

        # Colour palette: s1=blue, s2=red, s3=green, s4=orange (up to 4 ports)
        COLORS = ["blue", "red", "green", "darkorange"]

        # ---- Smith chart (all Sii reflections) --------------------------
        smith_ok = False
        try:
            for i in range(n):
                label = f"S{i+1}{i+1}"
                net.plot_s_smith(m=i, n=i, ax=self.ax_smith,
                                 color=COLORS[i % len(COLORS)],
                                 label=label, show_legend=False)
            smith_ok = True
        except Exception:
            pass

        if not smith_ok:
            self._draw_smith_background(self.ax_smith)
            for i in range(n):
                s_ii = net.s[:, i, i]
                self.ax_smith.plot(s_ii.real, s_ii.imag,
                                   color=COLORS[i % len(COLORS)],
                                   label=f"S{i+1}{i+1}", linewidth=1)

        # VSWR=2 reference circle
        vswr2_r = 1.0 / 3.0
        circle = mpatches.Circle((0, 0), vswr2_r, fill=False,
                                  linestyle="--", color="green",
                                  linewidth=1, label="VSWR=2")
        self.ax_smith.add_patch(circle)
        self.ax_smith.legend(fontsize=7, loc="upper right")
        port_labels = "/".join(f"S{i+1}{i+1}" for i in range(n))
        self.ax_smith.set_title(f"Smith Chart ({port_labels})", fontsize=9)

        # ---- VSWR (all ports) ------------------------------------------
        vswr_values = []
        for i in range(n):
            s_ii_mag = np.clip(np.abs(net.s[:, i, i]), 0, 0.9999)
            vswr_i = (1 + s_ii_mag) / (1 - s_ii_mag)
            vswr_values.append(vswr_i)
            lbl = f"VSWR(S{i+1}{i+1})" + (" ← ANT" if i == ant else "")
            self.ax_vswr.plot(freqs_ghz, vswr_i,
                              color=COLORS[i % len(COLORS)],
                              label=lbl, linewidth=1)

        self.ax_vswr.axhline(2.0, color="green", linestyle="--",
                             linewidth=0.8, label="VSWR=2")
        self.ax_vswr.set_xlabel("Frequency (GHz)", fontsize=8)
        self.ax_vswr.set_ylabel("VSWR", fontsize=8)
        self.ax_vswr.set_title("VSWR", fontsize=9)
        self.ax_vswr.legend(fontsize=7)
        self.ax_vswr.set_xlim(freq_start, freq_stop)
        self.ax_vswr.grid(True, linewidth=0.4)
        self.ax_vswr.tick_params(labelsize=7)

        # ---- Insertion Loss (antenna → each signal port) ---------------
        il_values = []
        il_labels = []
        for i in range(ant):  # signal ports 0..ant-1
            s_ant_i = np.clip(np.abs(net.s[:, ant, i]), 1e-15, None)
            il_db = 20 * np.log10(s_ant_i)
            label = f"S{ant+1}{i+1} (IL)"
            self.ax_il.plot(freqs_ghz, il_db,
                            color=COLORS[i % len(COLORS)],
                            label=label, linewidth=1)
            il_values.append(il_db)
            il_labels.append(label)

        ant_lbl = "/".join(f"S{ant+1}{i+1}" for i in range(ant))
        self.ax_il.set_xlabel("Frequency (GHz)", fontsize=8)
        self.ax_il.set_ylabel("Magnitude (dB)", fontsize=8)
        self.ax_il.set_title(f"Insertion Loss ({ant_lbl})", fontsize=9)
        self.ax_il.legend(fontsize=7)
        self.ax_il.set_xlim(freq_start, freq_stop)
        self.ax_il.grid(True, linewidth=0.4)
        self.ax_il.tick_params(labelsize=7)

        # ---- Text summary ----------------------------------------------
        npts = len(freqs_ghz)
        lines = [
            f"Freq Range:  {freq_start:.3f} – {freq_stop:.3f} GHz",
            f"Points:      {npts}",
            f"Ports:       {n}  (antenna = s{ant+1})",
            "",
        ]
        for i in range(n):
            worst_v = float(np.max(vswr_values[i]))
            tag = " (ANT)" if i == ant else ""
            lines.append(f"VSWR(S{i+1}{i+1}){tag}: {worst_v:.2f}")

        lines.append("")
        for i, (il_db, lbl) in enumerate(zip(il_values, il_labels)):
            lines.append(f"Min {lbl}: {float(np.min(il_db)):.2f} dB")
            lines.append(f"Avg {lbl}: {float(np.mean(il_db)):.2f} dB")

        summary = "\n".join(lines)
        self.ax_text.set_title("Summary", fontsize=9)
        self.ax_text.text(0.05, 0.95, summary, va="top",
                          transform=self.ax_text.transAxes,
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
