"""Results Display Panel - embedded matplotlib plots for RF network analysis."""
import numpy as np
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
import matplotlib.patches as mpatches
import skrf as rf
from smith_chart_utils import draw_smith_chart_background

from rf_network_tool.backend.smith_targets import (
    coerce_special_smith_targets,
    format_impedance,
    impedance_to_gamma,
)


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
        self.ax_vswr = self.fig.add_subplot(2, 2, 2)
        self.ax_il = self.fig.add_subplot(2, 2, 3)
        self.ax_text = self.fig.add_subplot(2, 2, 4)
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

    def plot_network(self, net: rf.Network, freq_start: float, freq_stop: float,
                     signal_freq_ranges: dict = None, special_smith_targets: dict = None):
        """Plot an N-port rf.Network: Smith, VSWR, IL, and text summary.

        Convention: antenna port = last port (index N-1).
        Signal ports: 0..N-2. IL = antenna-to-each-signal transmission.

        signal_freq_ranges: {signal_index (1-based int): (start_ghz, stop_ghz)}.
        When provided, each signal port's traces are clipped to its own band;
        the antenna port uses the union of all non-antenna bands.
        Falls back to global (freq_start, freq_stop) for any missing entry.

        special_smith_targets: optional {signal_index: target config}. Values are
        non-normalized impedance targets in ohms and are drawn as Smith markers.
        """
        self._init_axes()
        freqs_ghz = net.f / 1e9
        n = net.nports
        ant = n - 1  # antenna port index

        COLORS = ["blue", "red", "green", "darkorange"]

        sfr = signal_freq_ranges or {}
        targets = coerce_special_smith_targets(special_smith_targets or {}, n)
        port_masks = self._build_port_masks(
            freqs_ghz, ant, freq_start, freq_stop, sfr)

        # Determine x-axis range for shared axes: use global simulation frequency range
        x_start, x_stop = freq_start, freq_stop

        # ---- Smith chart: each Sii plotted within its own freq mask -----
        # Antenna is split into per-band segments with distinct linestyles so
        # the user can tell which arc belongs to which signal's freq band.
        BAND_STYLES = ['-', '--', ':', '-.']  # one style per non-ant band
        self._draw_smith_background(self.ax_smith)
        for i in range(n):
            color = COLORS[i % len(COLORS)]
            if i == ant and ant > 1:
                # One separate trace per non-ant band — different linestyle, labelled
                for band_i in range(ant):
                    bm = port_masks[band_i]
                    if not np.any(bm):
                        continue
                    s_ant = net.s[bm, ant, ant]
                    s_i, e_i = sfr.get(band_i + 1, (freq_start, freq_stop))
                    lbl = f"S{ant+1}{ant+1}[s{band_i+1}:{s_i:.2f}\u2013{e_i:.2f}]"
                    self.ax_smith.plot(s_ant.real, s_ant.imag,
                                       color=color,
                                       linestyle=BAND_STYLES[band_i % len(
                                           BAND_STYLES)],
                                       label=lbl, linewidth=1.4)
            else:
                mask = port_masks[i]
                s_ii = net.s[mask, i, i]
                tag = " ANT" if i == ant else ""
                self.ax_smith.plot(s_ii.real, s_ii.imag, color=color,
                                   label=f"S{i+1}{i+1}{tag}", linewidth=1.2)

        vswr2_r = 1.0 / 3.0
        circle = mpatches.Circle((0, 0), vswr2_r, fill=False,
                                 linestyle="--", color="green",
                                 linewidth=1, label="VSWR=2")
        self.ax_smith.add_patch(circle)
        for sig_idx, (start, stop, resistance, reactance) in targets.items():
            gamma = impedance_to_gamma(resistance, reactance)
            color = COLORS[(sig_idx - 1) % len(COLORS)]
            self.ax_smith.plot(
                [gamma.real], [gamma.imag],
                marker="x", markersize=8, markeredgewidth=1.6,
                color=color, linestyle="None",
                label=(
                    f"S{sig_idx}{sig_idx} target "
                    f"{format_impedance(resistance, reactance)} "
                    f"[{start:.2f}-{stop:.2f}]"
                ),
            )
        self.ax_smith.legend(fontsize=7, loc="upper right")
        port_labels = "/".join(f"S{i+1}{i+1}" for i in range(n))
        self.ax_smith.set_title(f"Smith Chart ({port_labels})", fontsize=9)

        # ---- VSWR: each port within its own freq mask -------------------
        # Antenna uses NaN-separated per-band segments (same NaN trick as Smith).
        vswr_maxes = []
        for i in range(n):
            color = COLORS[i % len(COLORS)]
            if i == ant and ant > 1:
                # One segment per non-ant band; track overall max across all bands
                freq_parts, vswr_parts, band_maxes = [], [], []
                for band_i in range(ant):
                    bm = port_masks[band_i]
                    if np.any(bm):
                        fq = freqs_ghz[bm]
                        sm = np.clip(np.abs(net.s[bm, ant, ant]), 0, 0.9999)
                        vv = (1 + sm) / (1 - sm)
                        band_maxes.append(float(np.max(vv)))
                        if freq_parts:
                            freq_parts.append(np.nan)
                            vswr_parts.append(np.nan)
                        freq_parts.extend(fq.tolist())
                        vswr_parts.extend(vv.tolist())
                vswr_maxes.append(max(band_maxes) if band_maxes else 0.0)
                self.ax_vswr.plot(freq_parts, vswr_parts, color=color,
                                  label=f"VSWR(S{ant+1}{ant+1}) \u2190 ANT", linewidth=1)
            else:
                mask = port_masks[i]
                freq_i = freqs_ghz[mask]
                s_mag = np.clip(np.abs(net.s[mask, i, i]), 0, 0.9999)
                vswr_i = (1 + s_mag) / (1 - s_mag)
                vswr_maxes.append(float(np.max(vswr_i))
                                  if len(vswr_i) > 0 else 0.0)
                self.ax_vswr.plot(freq_i, vswr_i, color=color,
                                  label=f"VSWR(S{i+1}{i+1})", linewidth=1)

        self.ax_vswr.axhline(2.0, color="green", linestyle="--",
                             linewidth=0.8, label="VSWR=2")
        self.ax_vswr.set_xlabel("Frequency (GHz)", fontsize=8)
        self.ax_vswr.set_ylabel("VSWR", fontsize=8)
        self.ax_vswr.set_title("VSWR", fontsize=9)
        self.ax_vswr.legend(fontsize=7)
        self.ax_vswr.set_xlim(x_start, x_stop)
        self.ax_vswr.grid(True, linewidth=0.4)
        self.ax_vswr.tick_params(labelsize=7)

        # ---- IL: S_{ant,i} plotted within signal i's freq mask ----------
        il_values = []
        il_labels = []
        for i in range(ant):
            mask = port_masks[i]
            freq_i = freqs_ghz[mask]
            s_ant_i = np.clip(np.abs(net.s[mask, ant, i]), 1e-15, None)
            il_db = 20 * np.log10(s_ant_i)
            label = f"S{ant+1}{i+1} (IL)"
            self.ax_il.plot(freq_i, il_db,
                            color=COLORS[i % len(COLORS)],
                            label=label, linewidth=1)
            il_values.append(il_db)
            il_labels.append(label)

        ant_lbl = "/".join(f"S{ant+1}{i+1}" for i in range(ant))
        self.ax_il.set_xlabel("Frequency (GHz)", fontsize=8)
        self.ax_il.set_ylabel("Magnitude (dB)", fontsize=8)
        self.ax_il.set_title(f"Insertion Loss ({ant_lbl})", fontsize=9)
        self.ax_il.legend(fontsize=7)
        self.ax_il.set_xlim(x_start, x_stop)
        self.ax_il.grid(True, linewidth=0.4)
        self.ax_il.tick_params(labelsize=7)

        # ---- Text summary (per-port freq ranges) -----------------------
        npts = len(freqs_ghz)
        lines = [
            f"Freq Range:  {freq_start:.3f} \u2013 {freq_stop:.3f} GHz",
            f"Points:      {npts}",
            f"Ports:       {n}  (antenna = s{ant+1})",
            "",
        ]
        for i in range(n):
            tag = " (ANT)" if i == ant else ""
            if i < ant:
                s_i, e_i = sfr.get(i + 1, (freq_start, freq_stop))
            else:
                s_i, e_i = x_start, x_stop
            if vswr_maxes[i] > 0:
                lines.append(
                    f"VSWR(S{i+1}{i+1}){tag}: {vswr_maxes[i]:.2f}"
                    f"  [{s_i:.3f}\u2013{e_i:.3f} GHz]"
                )
            else:
                lines.append(
                    f"VSWR(S{i+1}{i+1}){tag}: no data in [{s_i:.3f}\u2013{e_i:.3f} GHz]")

        lines.append("")
        if targets:
            lines.append("Special Smith targets:")
            for sig_idx, (start, stop, resistance, reactance) in sorted(targets.items()):
                gamma = impedance_to_gamma(resistance, reactance)
                lines.append(
                    f"S{sig_idx}{sig_idx}: {format_impedance(resistance, reactance)}"
                    f" -> gamma={gamma.real:+.3f}{gamma.imag:+.3f}j"
                    f" [{start:.3f}-{stop:.3f} GHz]"
                )
            lines.append("")
        for i, (il_db, lbl) in enumerate(zip(il_values, il_labels)):
            s_i, e_i = sfr.get(i + 1, (freq_start, freq_stop))
            if len(il_db) > 0:
                lines.append(
                    f"Min {lbl}: {float(np.min(il_db)):.2f} dB  [{s_i:.3f}\u2013{e_i:.3f} GHz]"
                )
                lines.append(f"Avg {lbl}: {float(np.mean(il_db)):.2f} dB")
            else:
                lines.append(
                    f"{lbl}: no data in [{s_i:.3f}\u2013{e_i:.3f} GHz]")

        summary = "\n".join(lines)
        self.ax_text.set_title("Summary", fontsize=9)
        self.ax_text.text(0.05, 0.95, summary, va="top",
                          transform=self.ax_text.transAxes,
                          fontsize=8, fontfamily="monospace",
                          bbox=dict(boxstyle="round", facecolor="lightyellow", alpha=0.6))

        self.canvas.draw_idle()

    def build_insertion_loss_export_data(
        self,
        net: rf.Network,
        freq_start: float,
        freq_stop: float,
        signal_freq_ranges: dict = None,
    ):
        """Build CSV-ready insertion-loss data using MHz for the frequency column."""
        freqs_ghz = net.f / 1e9
        freqs_mhz = freqs_ghz * 1e3
        ant = net.nports - 1
        port_masks = self._build_port_masks(
            freqs_ghz,
            ant,
            freq_start,
            freq_stop,
            signal_freq_ranges or {},
        )

        union_mask = np.zeros(len(freqs_ghz), dtype=bool)
        il_columns = []
        for i in range(ant):
            mask = port_masks[i]
            union_mask |= mask
            il_db = np.full(len(freqs_ghz), np.nan)
            if np.any(mask):
                s_ant_i = np.clip(np.abs(net.s[mask, ant, i]), 1e-15, None)
                il_db[mask] = 20 * np.log10(s_ant_i)
            il_columns.append((f"S{ant+1}{i+1}_il_db", il_db))

        headers = ["frequency_mhz"] + [name for name, _ in il_columns]
        rows = []
        for idx in np.where(union_mask)[0]:
            row = [f"{freqs_mhz[idx]:.6f}"]
            for _, values in il_columns:
                row.append("" if np.isnan(
                    values[idx]) else f"{values[idx]:.6f}")
            rows.append(row)
        return headers, rows

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_port_masks(freqs_ghz, ant: int, freq_start: float, freq_stop: float, signal_freq_ranges: dict):
        """Build per-port frequency masks plus the antenna union mask."""
        port_masks = []
        for i in range(ant):
            start, stop = signal_freq_ranges.get(
                i + 1, (freq_start, freq_stop))
            port_masks.append((freqs_ghz >= start) & (freqs_ghz <= stop))

        ant_mask = np.zeros(len(freqs_ghz), dtype=bool)
        for mask in port_masks:
            ant_mask |= mask
        port_masks.append(ant_mask)
        return port_masks

    def _draw_smith_background(self, ax):
        """Draw a scikit-rf Smith chart background."""
        draw_smith_chart_background(ax)
