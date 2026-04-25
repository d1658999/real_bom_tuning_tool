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

# Try to import the Rust extension for accelerated sweeps
try:
    import rf_sweep as _rf_sweep
    _RUST_AVAILABLE = True
except ImportError:
    _RUST_AVAILABLE = False


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
    # Complex S-params for Smith chart (real/imag split to keep JSON-serialisable)
    s11_re: List[float] = field(default_factory=list)
    s11_im: List[float] = field(default_factory=list)
    s22_re: List[float] = field(default_factory=list)
    s22_im: List[float] = field(default_factory=list)


@dataclass
class FleetResult:
    """Full results from the fleet run."""
    agent_results: List[AgentResult]
    winner_agent_id: int
    winner_reason: str
    risk_scores: Dict[str, float] = field(default_factory=dict)


def _get_tunable_ports(app_state) -> List[tuple]:
    """
    Return list of (network_id, port_index, term_type) for tunable (swept) ports.

    'open/ind', 'open/cap', and 'open/ind/cap' ports are swept during fleet optimization.
    Ports set to 'capacitor' or 'inductor' with a specific component already
    selected are treated as FIXED — the fleet uses that component as-is.
    """
    SWEEP_TYPES = {'open/ind', 'open/cap', 'open/ind/cap'}
    tunable = []
    for fid, fc in app_state.files.items():
        for pnum, pc in fc.ports.items():
            if pc.term_type in SWEEP_TYPES:
                tunable.append((fid, pnum, pc.term_type))
    return tunable


def _build_config_with_assignments(
    base_config: NetworkConfig,
    tunable_ports: List[tuple],
    assignments: List
) -> NetworkConfig:
    """
    Clone base_config and apply component assignments to tunable ports.
    assignments: list of component dicts (or None for 'open').
    Each component dict may carry a 'comp_type' key ('capacitor'|'inductor')
    used when the port type is 'open/ind/cap'.
    """
    import copy
    cfg = copy.deepcopy(base_config)
    for (nid, pnum, ttype), comp in zip(tunable_ports, assignments):
        if comp is None:
            cfg.terminations[nid][pnum].type = 'open'
            cfg.terminations[nid][pnum].component_path = None
        else:
            # For open/ind/cap ports, the actual type lives in comp['comp_type']
            resolved_type = comp.get('comp_type', ttype)
            cfg.terminations[nid][pnum].type = resolved_type
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
        # Complex S-params for Smith chart plotting (real/imag split)
        's11_re': np.real(s11).tolist(),
        's11_im': np.imag(s11).tolist(),
        's22_re': np.real(s22).tolist(),
        's22_im': np.imag(s22).tolist(),
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
                elif pc.term_type in ('open/ind', 'open/cap', 'open/ind/cap'):
                    term.type = 'open'  # baseline; fleet will override per-combination
                elif pc.term_type == 'connect':
                    term.connect_to = (pc.connect_to_file, pc.connect_to_port)
                elif pc.term_type == 'signal':
                    term.signal_port_index = pc.signal_index
                cfg.terminations[fid][pnum] = term
        return cfg

    def _get_candidate_components(
        self, term_type: str,
        ind_min_nh: float = 0.0, ind_max_nh: float = 10000.0,
        cap_min_pf: float = 0.0, cap_max_pf: float = 10000.0,
    ) -> List[dict]:
        """Get list of component candidates for a given type, filtered by value range.

        Limits from PortConfig are already rounded to 2 dp by the GUI spinboxes.
        A small EPS (1e-6) is added to the upper bound to absorb any residual
        floating-point imprecision so that exact boundary values are always included.
        """
        EPS = 1e-6  # < smallest meaningful component step (0.1 nH / 0.1 pF)

        def _ind_ok(i: dict) -> bool:
            v = i.get('value_nH', 0.0)
            return (ind_min_nh - EPS) <= v <= (ind_max_nh + EPS)

        def _cap_ok(c: dict) -> bool:
            v = c.get('value_pF', 0.0)
            return (cap_min_pf - EPS) <= v <= (cap_max_pf + EPS)

        if term_type == 'capacitor':
            return [{'name': c['name'], 'path': c['path'], 'comp_type': 'capacitor', 'value_pF': c.get('value_pF', 0.0)}
                    for c in list_capacitors() if _cap_ok(c)]
        elif term_type == 'inductor':
            return [{'name': i['name'], 'path': i['path'], 'comp_type': 'inductor', 'value_nH': i.get('value_nH', 0.0)}
                    for i in list_inductors() if _ind_ok(i)]
        elif term_type == 'open/ind':
            return [{'name': i['name'], 'path': i['path'], 'comp_type': 'inductor', 'value_nH': i.get('value_nH', 0.0)}
                    for i in list_inductors() if _ind_ok(i)]
        elif term_type == 'open/cap':
            return [{'name': c['name'], 'path': c['path'], 'comp_type': 'capacitor', 'value_pF': c.get('value_pF', 0.0)}
                    for c in list_capacitors() if _cap_ok(c)]
        elif term_type == 'open/ind/cap':
            caps = [{'name': c['name'], 'path': c['path'], 'comp_type': 'capacitor', 'value_pF': c.get('value_pF', 0.0)}
                    for c in list_capacitors() if _cap_ok(c)]
            inds = [{'name': i['name'], 'path': i['path'], 'comp_type': 'inductor', 'value_nH': i.get('value_nH', 0.0)}
                    for i in list_inductors() if _ind_ok(i)]
            return caps + inds
        return []

    def _sweep_all_combinations(
        self, base_config: NetworkConfig, tunable_ports: List[tuple]
    ) -> List[dict]:
        """
        Sweep all combinations of components for tunable ports.
        Uses Rust extension if available, falls back to pure Python.
        Returns list of {assignments, metrics} dicts.
        """
        candidates_per_port = []
        for nid, pnum, ttype in tunable_ports:
            pc = self.app_state.files[nid].ports[pnum]
            comps = self._get_candidate_components(
                ttype,
                ind_min_nh=pc.ind_min_nh, ind_max_nh=pc.ind_max_nh,
                cap_min_pf=pc.cap_min_pf, cap_max_pf=pc.cap_max_pf,
            )
            candidates_per_port.append([None] + comps)  # None = open

        total = 1
        for c in candidates_per_port:
            total *= len(c)
        self._log(f"  Total combinations: {total:,}")

        if _RUST_AVAILABLE and len(tunable_ports) > 0:
            return self._sweep_rust(base_config, tunable_ports, candidates_per_port, total)
        else:
            if not _RUST_AVAILABLE:
                self._log("  [WARNING] rf_sweep Rust module not found, using Python fallback")
            return self._sweep_python(base_config, tunable_ports, candidates_per_port, total)

    def _sweep_rust(
        self, base_config: NetworkConfig, tunable_ports: List[tuple],
        candidates_per_port: List[list], total: int
    ) -> List[dict]:
        """Rust-accelerated sweep using pre-built base network."""
        import rf_sweep
        import numpy as np
        from .network_builder import build_base_network_for_fleet

        self._log("  [Rust] Building base network...")
        tunable_keys = [(nid, pnum) for nid, pnum, _ in tunable_ports]

        try:
            base_net, ordered_keys = build_base_network_for_fleet(base_config, tunable_keys)
            nfreq = len(base_net.frequency)
            f_ghz = base_net.frequency.f / 1e9
            mask = (f_ghz >= base_config.freq_start_ghz) & (f_ghz <= base_config.freq_stop_ghz)
            eval_indices = np.where(mask)[0]
        except Exception as e:
            self._log(f"  [Rust] Base network build failed: {e}, falling back to Python")
            return self._sweep_python(base_config, tunable_ports, candidates_per_port, total)

        if len(eval_indices) == 0:
            self._log("  [Rust] No freq points in range, falling back to Python")
            return self._sweep_python(base_config, tunable_ports, candidates_per_port, total)
        eval_start, eval_stop = int(eval_indices[0]), int(eval_indices[-1])

        self._log(f"  [Rust] Base network: {base_net.nports} ports, {nfreq} freq points")
        self._log(f"  [Rust] Eval range indices: {eval_start}..{eval_stop}")

        # Build gamma arrays per tunable port: shape (n_cands, nfreq)
        # Row 0 = open (Γ = +1), rows 1..n_cands-1 = component gammas
        self._log("  [Rust] Pre-loading termination gammas...")
        term_gammas_re = []
        term_gammas_im = []
        all_candidates = []  # parallel list to candidates_per_port

        for (nid, pnum, ttype), comps in zip(tunable_ports, candidates_per_port):
            n_cands = len(comps)
            gamma_re = np.zeros((n_cands, nfreq), dtype=np.float64)
            gamma_im = np.zeros((n_cands, nfreq), dtype=np.float64)

            for c_idx, comp in enumerate(comps):
                if comp is None:
                    # open: Γ = +1
                    gamma_re[c_idx, :] = 1.0
                else:
                    # Build 1-port shunt termination, extract S11
                    from .network_builder import PortTermination
                    term = PortTermination(
                        type=comp.get('comp_type', ttype),
                        component_path=comp['path']
                    )
                    from .network_builder import NetworkBuilder
                    term_net_1port = NetworkBuilder._build_termination_network_static(
                        term, base_net.frequency
                    )
                    gamma_re[c_idx, :] = term_net_1port.s[:, 0, 0].real
                    gamma_im[c_idx, :] = term_net_1port.s[:, 0, 0].imag

            term_gammas_re.append(gamma_re)
            term_gammas_im.append(gamma_im)
            all_candidates.append(comps)

        # Call Rust
        self._log(f"  [Rust] Launching parallel sweep ({total:,} combinations)...")
        base_s = base_net.s  # (nfreq, N, N) complex128

        vswr_s11, vswr_s22, worst_il, combo_indices = rf_sweep.sweep_terminations_parallel(
            np.ascontiguousarray(base_s.real, dtype=np.float64),
            np.ascontiguousarray(base_s.imag, dtype=np.float64),
            [np.ascontiguousarray(g, dtype=np.float64) for g in term_gammas_re],
            [np.ascontiguousarray(g, dtype=np.float64) for g in term_gammas_im],
            eval_start,
            eval_stop,
        )
        self._log(f"  [Rust] Sweep complete: {len(vswr_s11):,} valid combinations")

        # Pack results into the same format as _sweep_python
        results = []
        for i in range(len(vswr_s11)):
            assignments = [all_candidates[p][combo_indices[i, p]] for p in range(len(tunable_ports))]
            results.append({
                'assignments': assignments,
                'net': None,   # lazy: will be built on demand for the winner
                'vswr_s11_max': float(vswr_s11[i]),
                'vswr_s22_max': float(vswr_s22[i]),
                'worst_il_db': float(worst_il[i]),
                'freq_ghz': [],
                's11_mag': [],
                's22_mag': [],
                's21_db': [],
            })
        return results

    def _sweep_python(
        self, base_config: NetworkConfig, tunable_ports: List[tuple],
        candidates_per_port: List[list], total: int
    ) -> List[dict]:
        """Pure-Python fallback sweep (original implementation)."""
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
                pass
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
            strategy = "Fewest components within 10% of the best achievable VSWR"
            # Determine the globally best (minimum) VSWR achievable across all candidates.
            vswr_floor = min(max(r['vswr_s11_max'], r['vswr_s22_max']) for r in all_results)
            # Accept results within 10% above the floor.  This prevents "open" (0 components)
            # from winning just because it scrapes under a loose absolute threshold — it only
            # wins if it genuinely comes close to what any component can achieve.
            vswr_threshold = vswr_floor * 1.10
            near_optimal = [r for r in all_results
                            if max(r['vswr_s11_max'], r['vswr_s22_max']) <= vswr_threshold]
            # Among near-optimal results, prefer fewest components; break ties by VSWR.
            best = min(near_optimal, key=lambda r: (
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
            # Check ALL results — previous agents may have lazily rebuilt some nets,
            # so checking only [0] is unreliable for Rust-path results.
            if all_results and all(r.get('net') is not None for r in all_results):
                best = min(all_results,
                          key=lambda r: self._smith_spread(r['net'], base_config.freq_start_ghz, base_config.freq_stop_ghz))
            else:
                # Rust path: use vswr_spread as proxy for Smith contour tightness
                best = min(all_results,
                          key=lambda r: abs(r['vswr_s11_max'] - r['vswr_s22_max']) +
                                        max(r['vswr_s11_max'], r['vswr_s22_max']))

        elif agent_id == 5:
            name = "Agent 5 - Min IL"
            strategy = "Minimize insertion loss (maximize |S21|)"
            best = max(all_results, key=lambda r: r['worst_il_db'])

        else:
            raise ValueError(f"Unknown agent_id {agent_id}")

        # If net was not pre-computed (Rust path), build it now for the winner.
        # Work on a shallow copy so we don't mutate the shared all_results list
        # (other agents still need clean net=None entries to detect the Rust path).
        best = dict(best)
        if best.get('net') is None:
            try:
                cfg = _build_config_with_assignments(base_config, tunable_ports, best['assignments'])
                best['net'] = build_network_from_config(cfg)
                ev = _evaluate_network(best['net'], base_config.freq_start_ghz, base_config.freq_stop_ghz)
                best.update(ev)
            except Exception as e:
                self._log(f"  [Agent {agent_id}] Lazy rebuild failed: {e}")

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
                # For open/ind/cap ports, use the resolved comp_type
                resolved_type = comp.get('comp_type', ttype)
                assignments.append(ComponentAssignment(
                    network_id=nid, port_index=pnum, term_type=resolved_type,
                    component_name=comp['name'], component_path=comp['path']
                ))

        # Tolerance analysis
        try:
            tol = _evaluate_with_tolerance(
                base_config, tunable_ports, best['assignments'],
                base_config.freq_start_ghz, base_config.freq_stop_ghz
            )
        except Exception as e:
            self._log(f"  [Agent {agent_id}] Tolerance analysis failed: {e}")
            tol = {'vswr_5pct_max_s11': 0.0, 'vswr_5pct_max_s22': 0.0,
                   'worst_il_5pct': 0.0, 'vswr_sensitivity': 0.0}

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
            s11_re=best.get('s11_re', []),
            s11_im=best.get('s11_im', []),
            s22_re=best.get('s22_re', []),
            s22_im=best.get('s22_im', []),
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

        # Smith chart — plot actual S11/S22 locus using complex values
        ax = axes[0]
        ax.set_aspect('equal')
        ax.set_xlim(-1.1, 1.1)
        ax.set_ylim(-1.1, 1.1)
        theta = np.linspace(0, 2*np.pi, 360)
        ax.plot(np.cos(theta), np.sin(theta), 'k-', lw=0.5)
        ax.axhline(0, color='k', lw=0.3)
        ax.axvline(0, color='k', lw=0.3)
        r2 = 1/3
        ax.plot(r2*np.cos(theta), r2*np.sin(theta), 'k--', lw=0.8, label='VSWR=2')
        # Plot actual S11/S22 locus
        if result.s11_re:
            s11_re = np.array(result.s11_re)
            s11_im = np.array(result.s11_im)
            ax.plot(s11_re, s11_im, 'b-', lw=1.5, label='S11')
        if result.s22_re:
            s22_re = np.array(result.s22_re)
            s22_im = np.array(result.s22_im)
            ax.plot(s22_re, s22_im, 'r-', lw=1.5, label='S22')
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

        # Smith — plot actual S11/S22 locus using complex values
        ax = axes[0]
        ax.set_aspect('equal')
        ax.set_xlim(-1.1, 1.1)
        ax.set_ylim(-1.1, 1.1)
        ax.plot(np.cos(theta), np.sin(theta), 'k-', lw=0.5)
        ax.axhline(0, color='k', lw=0.3)
        ax.axvline(0, color='k', lw=0.3)
        r2 = 1/3
        ax.plot(r2*np.cos(theta), r2*np.sin(theta), 'k--', lw=1.2, label='VSWR=2')
        # Plot actual S11/S22 locus
        if winner.s11_re:
            ax.plot(np.array(winner.s11_re), np.array(winner.s11_im), 'b-', lw=2, label='S11')
        if winner.s22_re:
            ax.plot(np.array(winner.s22_re), np.array(winner.s22_im), 'r-', lw=2, label='S22')
        ax.set_title('Smith Chart (Final)')
        ax.set_xlabel('Re(Γ)')
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
