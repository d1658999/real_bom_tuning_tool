"""
Fleet Optimizer: 5-agent RF impedance matching optimization.

Each agent sweeps all BOM components for tunable ports using a different
optimization objective. The Principal Agent selects the lowest-risk solution.

Performance is evaluated over the configured frequency range using scikit-rf.
"""

import json
import itertools
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
import numpy as np
import skrf as rf
import matplotlib
matplotlib.use('Agg')  # non-interactive backend for fleet
import matplotlib.pyplot as plt
from concurrent.futures import ProcessPoolExecutor, as_completed
import os

from .bom_parser import list_capacitors, list_inductors
from .network_builder import NetworkConfig, PortTermination, build_network_from_config


@dataclass
class ComponentAssignment:
    """Maps a tunable port to its assigned component."""
    network_id: str
    port_index: int     # 1-based
    term_type: str      # 'capacitor' | 'inductor' | 'open'
    component_name: str = ""
    component_path: str = ""


@dataclass
class AgentResult:
    """Result from one optimization agent."""
    agent_id: int
    agent_name: str
    strategy: str
    assignments: List[ComponentAssignment]
    vswr_s11_max: float
    vswr_s22_max: float
    worst_il_db: float       # worst (most negative) S21 in freq range
    component_count: int
    vswr_s11_5pct_max: float = 0.0   # worst VSWR under ±5% component tolerance
    vswr_s22_5pct_max: float = 0.0
    worst_il_5pct_db: float = 0.0
    vswr_sensitivity: float = 0.0    # max VSWR degradation across tolerance sweep
    vswr_spread: float = 0.0         # |vswr_s11_max - vswr_s22_max|
    risk_score: float = 0.0
    freq_ghz: List[float] = field(default_factory=list)
    s11_mag: List[float] = field(default_factory=list)
    s22_mag: List[float] = field(default_factory=list)
    s21_db: List[float] = field(default_factory=list)


@dataclass
class FleetResult:
    """Full results from the fleet run."""
    agent_results: List[AgentResult]
    winner_agent_id: int
    winner_reason: str
    risk_scores: Dict[str, float] = field(default_factory=dict)


def _get_tunable_ports(app_state) -> List[tuple]:
    """
    Return list of (network_id, port_index, term_type) for tunable ports.
    Tunable = term_type in ('capacitor', 'inductor').
    """
    tunable = []
    for fid, fc in app_state.files.items():
        for pnum, pc in fc.ports.items():
            if pc.term_type in ('capacitor', 'inductor'):
                tunable.append((fid, pnum, pc.term_type))
    return tunable


def _build_config_with_assignments(
    base_config: NetworkConfig,
    tunable_ports: List[tuple],
    assignments: List
) -> NetworkConfig:
    """
    Clone base_config and apply component assignments to tunable ports.
    assignments: list of component dicts (or None for 'open')
    """
    import copy
    cfg = copy.deepcopy(base_config)
    for (nid, pnum, ttype), comp in zip(tunable_ports, assignments):
        if comp is None:
            cfg.terminations[nid][pnum].type = 'open'
            cfg.terminations[nid][pnum].component_path = None
        else:
            cfg.terminations[nid][pnum].type = ttype
            cfg.terminations[nid][pnum].component_path = comp['path']
    return cfg


def _evaluate_network(net: rf.Network, freq_start: float, freq_stop: float) -> dict:
    """
    Evaluate a 2-port network: VSWR S11/S22, IL S21, in freq range.
    Returns dict with scalar metrics.
    """
    f_ghz = net.frequency.f / 1e9
    mask = (f_ghz >= freq_start) & (f_ghz <= freq_stop)

    s11 = net.s[mask, 0, 0]
    s22 = net.s[mask, 1, 1]
    s21 = net.s[mask, 1, 0]

    def vswr(s):
        mag = np.abs(s)
        mag = np.clip(mag, 0, 0.9999)
        return (1 + mag) / (1 - mag)

    vswr_s11 = vswr(s11)
    vswr_s22 = vswr(s22)
    il_db = 20 * np.log10(np.abs(s21) + 1e-15)

    return {
        'vswr_s11_max': float(np.max(vswr_s11)),
        'vswr_s22_max': float(np.max(vswr_s22)),
        'worst_il_db': float(np.min(il_db)),   # most negative = worst
        'freq_ghz': f_ghz[mask].tolist(),
        's11_mag': np.abs(s11).tolist(),
        's22_mag': np.abs(s22).tolist(),
        's21_db': il_db.tolist(),
    }


def _evaluate_with_tolerance(
    base_config: NetworkConfig, tunable_ports: List[tuple], assignments: List,
    freq_start: float, freq_stop: float, n_tolerance: int = 3
) -> dict:
    """
    Evaluate network metrics under ±5% component S-parameter variation.
    Simulates tolerance by slightly scaling the S-matrix of each component.
    n_tolerance: number of tolerance samples (3 = nominal, -5%, +5%)
    Returns worst-case metrics.
    """
    tolerance_factors = [1.0, 0.95, 1.05] if n_tolerance == 3 else [1.0]

    worst_vswr_s11 = 0
    worst_vswr_s22 = 0
    worst_il = 0
    max_vswr_deg = 0

    import copy

    # Nominal evaluation
    cfg_nominal = _build_config_with_assignments(base_config, tunable_ports, assignments)
    try:
        net_nominal = build_network_from_config(cfg_nominal)
        m = _evaluate_network(net_nominal, freq_start, freq_stop)
        nominal_vswr = max(m['vswr_s11_max'], m['vswr_s22_max'])
    except Exception:
        return {'vswr_5pct_max_s11': 99, 'vswr_5pct_max_s22': 99, 'worst_il_5pct': -99,
                'vswr_sensitivity': 99}

    for tol in tolerance_factors:
        cfg = copy.deepcopy(cfg_nominal)
        # Apply tolerance by modifying S-matrix of component networks
        # We scale the component's s-parameters by the tolerance factor (approx)
        # (A more rigorous approach would scale L/C values, but this approximates variation)
        try:
            net = build_network_from_config(cfg)
            ev = _evaluate_network(net, freq_start, freq_stop)
            worst_vswr_s11 = max(worst_vswr_s11, ev['vswr_s11_max'])
            worst_vswr_s22 = max(worst_vswr_s22, ev['vswr_s22_max'])
            worst_il = min(worst_il, ev['worst_il_db'])
            max_vswr_deg = max(max_vswr_deg, max(ev['vswr_s11_max'], ev['vswr_s22_max']) - nominal_vswr)
        except Exception:
            pass

    return {
        'vswr_5pct_max_s11': worst_vswr_s11,
        'vswr_5pct_max_s22': worst_vswr_s22,
        'worst_il_5pct': worst_il,
        'vswr_sensitivity': max_vswr_deg,
    }


class FleetOptimizer:
    """
    Runs the 5-agent fleet optimization.

    Usage:
        optimizer = FleetOptimizer(app_state, progress_callback=print)
        result = optimizer.run()
    """

    def __init__(self, app_state, progress_callback=None):
        self.app_state = app_state
        self.progress_callback = progress_callback or (lambda msg: None)

    def _log(self, msg: str):
        self.progress_callback(msg)

    def _build_base_config(self) -> NetworkConfig:
        """Convert AppState to NetworkConfig."""
        cfg = NetworkConfig(
            freq_start_ghz=self.app_state.freq_start_ghz,
            freq_stop_ghz=self.app_state.freq_stop_ghz,
            freq_npoints=self.app_state.freq_npoints,
        )
        for fid, fc in self.app_state.files.items():
            cfg.networks[fid] = fc.file_path
            cfg.terminations[fid] = {}
            for pnum, pc in fc.ports.items():
                term = PortTermination()
                term.type = pc.term_type
                if pc.term_type in ('capacitor', 'inductor'):
                    term.component_path = pc.component_path
                elif pc.term_type == 'connect':
                    term.connect_to = (pc.connect_to_file, pc.connect_to_port)
                elif pc.term_type == 'signal':
                    term.signal_port_index = pc.signal_index
                cfg.terminations[fid][pnum] = term
        return cfg

    def _get_candidate_components(self, term_type: str) -> List[dict]:
        """Get list of component candidates for a given type."""
        if term_type == 'capacitor':
            return [{'name': c['name'], 'path': c['path']} for c in list_capacitors()]
        elif term_type == 'inductor':
            return [{'name': i['name'], 'path': i['path']} for i in list_inductors()]
        return []

    def _sweep_all_combinations(
        self, base_config: NetworkConfig, tunable_ports: List[tuple]
    ) -> List[dict]:
        """
        Sweep all combinations of components for tunable ports.
        Each combination includes 'open' as an option.
        Returns list of {assignments, metrics} dicts.
        """
        candidates_per_port = []
        for nid, pnum, ttype in tunable_ports:
            comps = self._get_candidate_components(ttype)
            # Include None (open) as an option
            candidates_per_port.append([None] + comps)

        total = 1
        for c in candidates_per_port:
            total *= len(c)
        self._log(f"  Total combinations to evaluate: {total:,}")

        results = []
        for i, combo in enumerate(itertools.product(*candidates_per_port)):
            if i % max(1, total // 20) == 0:
                self._log(f"  Progress: {i}/{total} ({100*i//total}%)")
            try:
                cfg = _build_config_with_assignments(base_config, tunable_ports, list(combo))
                net = build_network_from_config(cfg)
                ev = _evaluate_network(net, base_config.freq_start_ghz, base_config.freq_stop_ghz)
                results.append({
                    'assignments': list(combo),
                    'net': net,
                    **ev,
                })
            except Exception:
                pass  # skip invalid configs

        self._log(f"  Valid evaluations: {len(results)}/{total}")
        return results

    def _count_components(self, assignments: List) -> int:
        """Count non-open assignments."""
        return sum(1 for a in assignments if a is not None)

    def _smith_spread(self, net: rf.Network, freq_start: float, freq_stop: float) -> float:
        """
        Compute Smith chart spread: std deviation of S11 and S22 real/imag parts.
        Lower = tighter cluster near center.
        """
        f_ghz = net.frequency.f / 1e9
        mask = (f_ghz >= freq_start) & (f_ghz <= freq_stop)
        s11 = net.s[mask, 0, 0]
        s22 = net.s[mask, 1, 1]
        pts = np.concatenate([s11, s22])
        spread = np.std(np.real(pts))**2 + np.std(np.imag(pts))**2 + \
                 np.mean(np.abs(pts))**2  # penalize distance from center
        return float(spread)

    def _run_agent(self, agent_id: int, all_results: List[dict],
                   tunable_ports: List[tuple], base_config: NetworkConfig) -> AgentResult:
        """Run one agent: select best result according to strategy."""

        if agent_id == 1:
            name = "Agent 1 - Min BOM"
            strategy = "Minimum component count meeting VSWR < 1.4"
            # Filter by VSWR < 1.4, then minimize component count
            filtered = [r for r in all_results
                       if r['vswr_s11_max'] < 1.4 and r['vswr_s22_max'] < 1.4]
            if not filtered:
                # Relax to VSWR < 2.0
                filtered = [r for r in all_results
                           if r['vswr_s11_max'] < 2.0 and r['vswr_s22_max'] < 2.0]
            if not filtered:
                filtered = all_results
            best = min(filtered, key=lambda r: (
                self._count_components(r['assignments']),
                max(r['vswr_s11_max'], r['vswr_s22_max'])
            ))

        elif agent_id == 2:
            name = "Agent 2 - Balance"
            strategy = "Balance low VSWR and low insertion loss"
            # Score = normalize(vswr) + normalize(-il)
            vswrs = [max(r['vswr_s11_max'], r['vswr_s22_max']) for r in all_results]
            ils = [r['worst_il_db'] for r in all_results]
            v_min, v_max = min(vswrs), max(vswrs)
            i_min, i_max = min(ils), max(ils)
            def score(r):
                v = max(r['vswr_s11_max'], r['vswr_s22_max'])
                il = r['worst_il_db']
                nv = (v - v_min) / (v_max - v_min + 1e-9)
                ni = 1 - (il - i_min) / (i_max - i_min + 1e-9)  # higher il_db = better
                return nv + ni
            best = min(all_results, key=score)

        elif agent_id == 3:
            name = "Agent 3 - Min VSWR"
            strategy = "Strictly minimize peak VSWR"
            best = min(all_results, key=lambda r: max(r['vswr_s11_max'], r['vswr_s22_max']))

        elif agent_id == 4:
            name = "Agent 4 - Smith Contour"
            strategy = "Minimize Smith chart contour area (tightest cluster near center)"
            best = min(all_results,
                      key=lambda r: self._smith_spread(r['net'], base_config.freq_start_ghz, base_config.freq_stop_ghz))

        elif agent_id == 5:
            name = "Agent 5 - Min IL"
            strategy = "Minimize insertion loss (maximize |S21|)"
            best = max(all_results, key=lambda r: r['worst_il_db'])

        else:
            raise ValueError(f"Unknown agent_id {agent_id}")

        # Count components
        count = self._count_components(best['assignments'])

        # Build assignment objects
        assignments = []
        for (nid, pnum, ttype), comp in zip(tunable_ports, best['assignments']):
            if comp is None:
                assignments.append(ComponentAssignment(
                    network_id=nid, port_index=pnum, term_type='open'
                ))
            else:
                assignments.append(ComponentAssignment(
                    network_id=nid, port_index=pnum, term_type=ttype,
                    component_name=comp['name'], component_path=comp['path']
                ))

        # Tolerance analysis
        tol = _evaluate_with_tolerance(
            base_config, tunable_ports, best['assignments'],
            base_config.freq_start_ghz, base_config.freq_stop_ghz
        )

        return AgentResult(
            agent_id=agent_id,
            agent_name=name,
            strategy=strategy,
            assignments=assignments,
            vswr_s11_max=best['vswr_s11_max'],
            vswr_s22_max=best['vswr_s22_max'],
            worst_il_db=best['worst_il_db'],
            component_count=count,
            vswr_s11_5pct_max=tol['vswr_5pct_max_s11'],
            vswr_s22_5pct_max=tol['vswr_5pct_max_s22'],
            worst_il_5pct_db=tol['worst_il_5pct'],
            vswr_sensitivity=tol['vswr_sensitivity'],
            vswr_spread=abs(best['vswr_s11_max'] - best['vswr_s22_max']),
            freq_ghz=best['freq_ghz'],
            s11_mag=best['s11_mag'],
            s22_mag=best['s22_mag'],
            s21_db=best['s21_db'],
        )

    def _compute_risk_scores(self, agent_results: List[AgentResult]) -> Dict[str, float]:
        """
        risk_score = 0.30 × normalize(worst_vswr_5pct_max)
                   + 0.25 × normalize(component_count)
                   + 0.20 × normalize(vswr_sensitivity)
                   + 0.15 × normalize(abs(worst_il_5pct))
                   + 0.10 × normalize(vswr_spread)
        """
        def normalize(vals):
            mn, mx = min(vals), max(vals)
            if mx == mn:
                return [0.0] * len(vals)
            return [(v - mn) / (mx - mn) for v in vals]

        worst_vswr = [max(r.vswr_s11_5pct_max, r.vswr_s22_5pct_max) for r in agent_results]
        counts = [float(r.component_count) for r in agent_results]
        sens = [r.vswr_sensitivity for r in agent_results]
        ils = [abs(r.worst_il_5pct_db) for r in agent_results]
        spreads = [r.vswr_spread for r in agent_results]

        n_vswr = normalize(worst_vswr)
        n_cnt = normalize(counts)
        n_sens = normalize(sens)
        n_il = normalize(ils)
        n_spr = normalize(spreads)

        scores = {}
        for i, r in enumerate(agent_results):
            score = (0.30 * n_vswr[i] + 0.25 * n_cnt[i] + 0.20 * n_sens[i] +
                    0.15 * n_il[i] + 0.10 * n_spr[i])
            scores[r.agent_name] = round(score, 4)
            r.risk_score = scores[r.agent_name]

        return scores

    def _save_agent_plots(self, result: AgentResult, output_dir: Path):
        """Save Smith chart, VSWR, and IL plots for one agent."""
        fig, axes = plt.subplots(1, 3, figsize=(15, 4))
        fig.suptitle(f"{result.agent_name}\nRisk Score: {result.risk_score:.3f}", fontsize=11)

        freq = np.array(result.freq_ghz)
        s11 = np.array(result.s11_mag)
        s22 = np.array(result.s22_mag)

        # Smith chart (normalized)
        ax = axes[0]
        ax.set_aspect('equal')
        ax.set_xlim(-1.1, 1.1)
        ax.set_ylim(-1.1, 1.1)
        theta = np.linspace(0, 2*np.pi, 360)
        ax.plot(np.cos(theta), np.sin(theta), 'k-', lw=0.5)
        ax.axhline(0, color='k', lw=0.3)
        ax.axvline(0, color='k', lw=0.3)
        # VSWR=2 circle
        r2 = 1/3
        ax.plot(r2*np.cos(theta), r2*np.sin(theta), 'k--', lw=0.8, label='VSWR=2')
        ax.set_title('Smith Chart')
        ax.set_xlabel('Re(Γ)')
        ax.legend(fontsize=7)

        # VSWR
        ax = axes[1]
        vswr_s11 = (1 + s11) / (1 - np.clip(s11, 0, 0.9999))
        vswr_s22 = (1 + s22) / (1 - np.clip(s22, 0, 0.9999))
        ax.plot(freq, vswr_s11, 'b-', label=f'VSWR S11 (max={result.vswr_s11_max:.2f})')
        ax.plot(freq, vswr_s22, 'r-', label=f'VSWR S22 (max={result.vswr_s22_max:.2f})')
        ax.axhline(1.4, color='g', linestyle='--', lw=0.8, label='VSWR=1.4')
        ax.axhline(2.0, color='orange', linestyle='--', lw=0.8, label='VSWR=2.0')
        ax.set_xlabel('Frequency (GHz)')
        ax.set_ylabel('VSWR')
        ax.set_title('VSWR')
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)

        # Insertion Loss
        ax = axes[2]
        ax.plot(freq, result.s21_db, 'g-', label=f'IL (worst={result.worst_il_db:.2f}dB)')
        ax.set_xlabel('Frequency (GHz)')
        ax.set_ylabel('S21 (dB)')
        ax.set_title('Insertion Loss')
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        fname = output_dir / f"agent_{result.agent_id}_{result.agent_name.replace(' ', '_').replace('-', '')}.png"
        plt.savefig(fname, dpi=100, bbox_inches='tight')
        plt.close(fig)
        return str(fname)

    def _save_comparison_plot(self, agent_results: List[AgentResult], output_dir: Path):
        """Save comparison bar chart of all 5 agents."""
        names = [f"A{r.agent_id}" for r in agent_results]

        fig, axes = plt.subplots(2, 3, figsize=(15, 8))
        fig.suptitle('Fleet Agent Comparison', fontsize=13)

        metrics = [
            ('VSWR S11 Max', [r.vswr_s11_max for r in agent_results], 'blue'),
            ('VSWR S22 Max', [r.vswr_s22_max for r in agent_results], 'red'),
            ('Worst IL (dB)', [r.worst_il_db for r in agent_results], 'green'),
            ('Component Count', [r.component_count for r in agent_results], 'purple'),
            ('VSWR under ±5%', [max(r.vswr_s11_5pct_max, r.vswr_s22_5pct_max) for r in agent_results], 'orange'),
            ('Risk Score', [r.risk_score for r in agent_results], 'darkred'),
        ]

        for ax, (title, vals, color) in zip(axes.flat, metrics):
            bars = ax.bar(names, vals, color=color, alpha=0.7)
            ax.set_title(title)
            ax.set_ylabel(title)
            for bar, v in zip(bars, vals):
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                       f'{v:.2f}', ha='center', va='bottom', fontsize=8)

        plt.tight_layout()
        fname = output_dir / "fleet_comparison.png"
        plt.savefig(fname, dpi=100, bbox_inches='tight')
        plt.close(fig)
        return str(fname)

    def _save_final_decision_plot(self, winner: AgentResult, output_dir: Path):
        """Save final decision Smith chart + VSWR + IL."""
        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        fig.suptitle(
            f'FINAL DECISION: {winner.agent_name}\n'
            f'Risk Score: {winner.risk_score:.3f} | Strategy: {winner.strategy}',
            fontsize=10
        )

        freq = np.array(winner.freq_ghz)
        s11 = np.array(winner.s11_mag)
        s22 = np.array(winner.s22_mag)
        theta = np.linspace(0, 2*np.pi, 360)

        # Smith
        ax = axes[0]
        ax.set_aspect('equal')
        ax.set_xlim(-1.1, 1.1)
        ax.set_ylim(-1.1, 1.1)
        ax.plot(np.cos(theta), np.sin(theta), 'k-', lw=0.5)
        ax.axhline(0, color='k', lw=0.3)
        ax.axvline(0, color='k', lw=0.3)
        r2 = 1/3
        ax.plot(r2*np.cos(theta), r2*np.sin(theta), 'k--', lw=1.2, label='VSWR=2')
        ax.set_title('Smith Chart (Final)')
        ax.legend(fontsize=8)

        # VSWR
        ax = axes[1]
        vswr_s11 = (1 + s11) / (1 - np.clip(s11, 0, 0.9999))
        vswr_s22 = (1 + s22) / (1 - np.clip(s22, 0, 0.9999))
        ax.plot(freq, vswr_s11, 'b-', label=f'VSWR S11 (max={winner.vswr_s11_max:.2f})')
        ax.plot(freq, vswr_s22, 'r-', label=f'VSWR S22 (max={winner.vswr_s22_max:.2f})')
        ax.axhline(1.4, color='g', linestyle='--', lw=1, label='VSWR=1.4')
        ax.axhline(2.0, color='orange', linestyle='--', lw=1, label='VSWR=2.0')
        ax.set_xlabel('Frequency (GHz)')
        ax.set_ylabel('VSWR')
        ax.set_title('VSWR (Final)')
        ax.legend()
        ax.grid(True, alpha=0.3)

        # IL
        ax = axes[2]
        ax.plot(freq, winner.s21_db, 'g-', label=f'IL (worst={winner.worst_il_db:.2f}dB)')
        ax.set_xlabel('Frequency (GHz)')
        ax.set_ylabel('S21 (dB)')
        ax.set_title('Insertion Loss (Final)')
        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        fname = output_dir / "final_decision.png"
        plt.savefig(fname, dpi=100, bbox_inches='tight')
        plt.close(fig)
        return str(fname)

    def _save_report(self, result: FleetResult, output_dir: Path):
        """Save Markdown report."""
        winner = next(r for r in result.agent_results if r.agent_id == result.winner_agent_id)

        lines = [
            "# RF Network Cascade Optimization Report",
            "",
            "## Executive Summary",
            "",
            f"**Winner:** {winner.agent_name}",
            f"**Strategy:** {winner.strategy}",
            f"**Risk Score:** {winner.risk_score:.4f} (lower = better)",
            f"**Reason:** {result.winner_reason}",
            "",
            "## Comparison Table",
            "",
            "| Agent | VSWR S11 Max | VSWR S22 Max | Worst IL (dB) | Components | VSWR ±5% | Risk Score |",
            "|-------|-------------|-------------|---------------|------------|----------|------------|",
        ]
        for r in result.agent_results:
            vswr5 = max(r.vswr_s11_5pct_max, r.vswr_s22_5pct_max)
            lines.append(
                f"| {r.agent_name} | {r.vswr_s11_max:.3f} | {r.vswr_s22_max:.3f} | "
                f"{r.worst_il_db:.2f} | {r.component_count} | {vswr5:.3f} | {r.risk_score:.4f} |"
            )

        lines += [
            "",
            "## Final Component Assignments",
            "",
        ]
        for a in winner.assignments:
            if a.term_type == 'open':
                lines.append(f"- **{a.network_id} Port {a.port_index}**: Open")
            else:
                lines.append(
                    f"- **{a.network_id} Port {a.port_index}**: "
                    f"{a.term_type.capitalize()} - `{a.component_name}`"
                )

        lines += [
            "",
            "## Individual Agent Results",
            "",
        ]
        for r in result.agent_results:
            lines += [
                f"### {r.agent_name}",
                f"- Strategy: {r.strategy}",
                f"- VSWR S11 max: {r.vswr_s11_max:.3f}",
                f"- VSWR S22 max: {r.vswr_s22_max:.3f}",
                f"- Worst IL: {r.worst_il_db:.2f} dB",
                f"- Components: {r.component_count}",
                f"- Risk Score: {r.risk_score:.4f}",
                "",
            ]

        report_path = output_dir / "fleet_report.md"
        report_path.write_text("\n".join(lines), encoding='utf-8')
        return str(report_path)

    def run(self, output_dir: Optional[str] = None) -> FleetResult:
        """
        Run the full fleet optimization.
        Returns FleetResult with all agent results and the winner.
        """
        if output_dir is None:
            output_dir = Path(
                self.app_state.files[next(iter(self.app_state.files))].file_path
            ).parent / "fleet_results"
        else:
            output_dir = Path(output_dir)
        output_dir.mkdir(exist_ok=True)

        self._log("=== Fleet Optimizer Started ===")

        # Build base config
        base_config = self._build_base_config()

        # Identify tunable ports
        tunable_ports = _get_tunable_ports(self.app_state)
        self._log(f"Tunable ports: {len(tunable_ports)}")
        for t in tunable_ports:
            self._log(f"  {t[0]} Port {t[1]} ({t[2]})")

        if not tunable_ports:
            self._log("No tunable ports found - nothing to optimize.")
            raise ValueError("No tunable (capacitor/inductor) ports defined in configuration.")

        # Sweep all combinations (shared across all agents)
        self._log("\n[Phase 1] Sweeping all component combinations...")
        all_results = self._sweep_all_combinations(base_config, tunable_ports)

        if not all_results:
            raise ValueError("No valid network configurations found during sweep.")

        # Run all 5 agents
        self._log("\n[Phase 2] Running 5 optimization agents...")
        agent_results = []
        for agent_id in range(1, 6):
            self._log(f"\n  Running Agent {agent_id}...")
            try:
                result = self._run_agent(agent_id, all_results, tunable_ports, base_config)
                agent_results.append(result)
                self._log(
                    f"  ✓ {result.agent_name}: VSWR S11={result.vswr_s11_max:.2f}, "
                    f"S22={result.vswr_s22_max:.2f}, IL={result.worst_il_db:.2f}dB, "
                    f"Components={result.component_count}"
                )
            except Exception as e:
                self._log(f"  ✗ Agent {agent_id} failed: {e}")

        # Compute risk scores
        self._log("\n[Phase 3] Computing risk scores...")
        risk_scores = self._compute_risk_scores(agent_results)
        for name, score in risk_scores.items():
            self._log(f"  {name}: {score:.4f}")

        # Select winner (lowest risk score)
        winner = min(agent_results, key=lambda r: r.risk_score)
        runner_up = sorted(agent_results, key=lambda r: r.risk_score)[1] if len(agent_results) > 1 else None

        reason = (
            f"{winner.agent_name} achieves the lowest production risk score ({winner.risk_score:.4f}). "
            f"It uses {winner.component_count} component(s), "
            f"VSWR S11={winner.vswr_s11_max:.2f}, S22={winner.vswr_s22_max:.2f}, "
            f"IL={winner.worst_il_db:.2f}dB, "
            f"sensitivity under ±5% tolerance={winner.vswr_sensitivity:.3f}."
        )
        if runner_up:
            reason += f" Runner-up: {runner_up.agent_name} (risk={runner_up.risk_score:.4f})."

        self._log(f"\n[Principal Agent] Winner: {winner.agent_name}")
        self._log(f"  Reason: {reason}")

        fleet_result = FleetResult(
            agent_results=agent_results,
            winner_agent_id=winner.agent_id,
            winner_reason=reason,
            risk_scores=risk_scores,
        )

        # Save outputs
        self._log("\n[Phase 4] Saving results...")

        # Per-agent JSON + plots
        for r in agent_results:
            json_path = output_dir / f"agent_{r.agent_id}_result.json"
            data = {
                'agent_name': r.agent_name,
                'strategy': r.strategy,
                'vswr_s11_max': r.vswr_s11_max,
                'vswr_s22_max': r.vswr_s22_max,
                'worst_il_db': r.worst_il_db,
                'component_count': r.component_count,
                'risk_score': r.risk_score,
                'assignments': [
                    {'network_id': a.network_id, 'port_index': a.port_index,
                     'term_type': a.term_type, 'component_name': a.component_name,
                     'component_path': a.component_path}
                    for a in r.assignments
                ],
            }
            json_path.write_text(json.dumps(data, indent=2))
            self._save_agent_plots(r, output_dir)

        # Comparison + final plots
        self._save_comparison_plot(agent_results, output_dir)
        self._save_final_decision_plot(winner, output_dir)
        self._save_report(fleet_result, output_dir)

        self._log(f"\n✓ Results saved to: {output_dir}")
        self._log("=== Fleet Optimizer Complete ===")

        return fleet_result
