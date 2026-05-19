"""Helpers for optional non-50-ohm Smith-chart optimization targets."""
from typing import Dict, Optional, Tuple
import numpy as np


Z0_OHMS = 50.0

SmithTargetTuple = Tuple[float, float, float, float]  # start GHz, stop GHz, R ohm, X ohm


def impedance_to_gamma(
    resistance_ohm: float,
    reactance_ohm: float,
    z0_ohms: float = Z0_OHMS,
) -> complex:
    """Convert a non-normalized impedance target to reflection coefficient."""
    z = complex(float(resistance_ohm), float(reactance_ohm))
    z0 = float(z0_ohms)
    denom = z + z0
    if abs(denom) < 1e-15:
        return complex(0.999999, 0.0)
    return (z - z0) / denom


def _read_target_value(target, name: str, default):
    if isinstance(target, dict):
        return target.get(name, default)
    return getattr(target, name, default)


def coerce_special_smith_targets(
    targets,
    n_ports: Optional[int] = None,
) -> Dict[int, SmithTargetTuple]:
    """
    Return enabled targets as {signal_index: (start, stop, R, X)}.

    Accepts the GUI dataclass instances, dictionaries from JSON-like data, or
    direct tuples/lists in the same order for test and backward-compatible use.
    """
    result: Dict[int, SmithTargetTuple] = {}
    if not targets:
        return result

    for raw_key, target in targets.items():
        try:
            sig_idx = int(raw_key)
        except (TypeError, ValueError):
            continue
        if sig_idx < 1 or (n_ports is not None and sig_idx > n_ports):
            continue

        if isinstance(target, (list, tuple)):
            if len(target) < 4:
                continue
            enabled = True
            start_ghz, stop_ghz, resistance_ohm, reactance_ohm = target[:4]
        else:
            enabled = bool(_read_target_value(target, "enabled", True))
            start_ghz = _read_target_value(target, "start_ghz", 0.0)
            stop_ghz = _read_target_value(target, "stop_ghz", 0.0)
            resistance_ohm = _read_target_value(target, "resistance_ohm", Z0_OHMS)
            reactance_ohm = _read_target_value(target, "reactance_ohm", 0.0)

        if not enabled:
            continue
        start = float(start_ghz)
        stop = float(stop_ghz)
        if stop < start:
            start, stop = stop, start
        result[sig_idx] = (
            start,
            stop,
            float(resistance_ohm),
            float(reactance_ohm),
        )

    return result


def build_target_gamma_matrix(
    freqs_ghz: np.ndarray,
    n_ports: int,
    targets,
) -> np.ndarray:
    """
    Build per-port, per-frequency target gamma values.

    Default target is 50+0j, represented by gamma=0. Enabled special ranges
    override that default only inside their configured frequency interval.
    """
    freqs = np.asarray(freqs_ghz, dtype=float)
    target_gamma = np.zeros((int(n_ports), len(freqs)), dtype=complex)
    for sig_idx, (start, stop, resistance, reactance) in coerce_special_smith_targets(
        targets, n_ports
    ).items():
        mask = (freqs >= start) & (freqs <= stop)
        if np.any(mask):
            target_gamma[sig_idx - 1, mask] = impedance_to_gamma(resistance, reactance)
    return target_gamma


def format_impedance(resistance_ohm: float, reactance_ohm: float) -> str:
    sign = "+" if reactance_ohm >= 0 else "-"
    return f"{resistance_ohm:.2f}{sign}{abs(reactance_ohm):.2f}j ohm"
