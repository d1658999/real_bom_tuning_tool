"""
RF Network cascade builder.
Loads multiple .snp Touchstone files, connects ports between networks,
applies terminations (open/short/capacitor/inductor), and returns an N-port network.

Uses scikit-rf (skrf) for all S-parameter operations.

Algorithm:
1. Load all .snp files as rf.Network objects and interpolate to common freq grid
2. Build a block-diagonal super-network concatenating all networks
3. Track port mapping: (network_id, 1-based port) -> 0-based global port index
4. Apply inter-network connections using rf.innerconnect
5. Apply terminations (open/short/component) using rf.connect with 1-port networks
6. Result is an N-port network between the marked s1..sN signal ports (N >= 2)

Port termination models (all as SHUNT elements - component between port and ground):
  - open:      S11 = +1 (perfect open, no loading)
  - short:     S11 = -1 (short to ground, 0 ohm)
  - capacitor: load .s2p series model; port 0 to RF node, port 1 to short (ground)
  - inductor:  same as capacitor

For 0-ohm (short) termination, it's equivalent to a shunt short.
"""

import numpy as np
import skrf as rf
from skrf.network import connect, innerconnect
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict
from pathlib import Path


@dataclass
class PortTermination:
    """Describes termination for one port of a network."""
    # Type: 'open' | 'short' | 'capacitor' | 'inductor' | 'connect' | 'signal'
    type: str = 'open'
    # For 'capacitor' or 'inductor': absolute path to .s2p file
    component_path: Optional[str] = None
    # For 'connect': (network_id, 1-based port index)
    connect_to: Optional[Tuple[str, int]] = None
    # For 'signal': marks this as s1 or s2 (the output 2-port ports)
    signal_port_index: Optional[int] = None  # 1 or 2


@dataclass
class NetworkConfig:
    """Complete configuration for building the cascade network."""
    # Dict: network_id -> absolute file path
    networks: Dict[str, str] = field(default_factory=dict)
    # Dict: network_id -> {1-based port index -> PortTermination}
    terminations: Dict[str, Dict[int, PortTermination]] = field(default_factory=dict)
    freq_start_ghz: float = 3.3
    freq_stop_ghz: float = 5.0
    freq_npoints: int = 201


class NetworkBuilder:
    """Builds a final N-port S-parameter network from a NetworkConfig (N >= 2)."""

    def __init__(self, config: NetworkConfig):
        self.config = config

    def build(self) -> rf.Network:
        """Build and return the final 2-port network."""
        # 1. Load and interpolate
        nets = self._load_networks()

        # 2. Build port mapping (network_id, 1-based) -> 0-based global index
        port_map: Dict[Tuple[str, int], int] = {}
        offset = 0
        for nid in nets:
            for p in range(nets[nid].nports):
                port_map[(nid, p + 1)] = offset + p
            offset += nets[nid].nports

        # 3. Build block-diagonal super-network
        super_net = self._block_diagonal(list(nets.values()))

        # 4. Apply inter-network connections (innerconnect)
        seen_pairs = set()
        for nid, terms in self.config.terminations.items():
            for port, term in terms.items():
                if term.type != 'connect':
                    continue
                cid, cport = term.connect_to
                pair = tuple(sorted([(nid, port), (cid, cport)]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                k = port_map[(nid, port)]
                l = port_map[(cid, cport)]
                super_net = innerconnect(super_net, k, l)
                port_map = self._update_port_map_innerconnect(port_map, k, l, (nid, port), (cid, cport))

        # 5. Identify signal ports (s1, s2) - don't terminate these
        signal_ports = {}  # signal_port_index -> (nid, port)
        for nid, terms in self.config.terminations.items():
            for port, term in terms.items():
                if term.type == 'signal':
                    signal_ports[term.signal_port_index] = (nid, port)

        # 6. Apply non-connect, non-signal terminations
        for nid, terms in self.config.terminations.items():
            for port, term in terms.items():
                if term.type in ('connect', 'signal'):
                    continue
                if (nid, port) not in port_map:
                    continue
                k = port_map[(nid, port)]
                term_net = self._build_termination_network(term, super_net.frequency)
                super_net = connect(super_net, k, term_net, 0)
                port_map = self._update_port_map_connect(port_map, k, (nid, port))

        # 7. Validate signal ports are consecutive 1..N and reorder to [s1, s2, ..., sN]
        if not signal_ports:
            raise ValueError("No signal ports defined. At least s1 and s2 are required.")
        n_signals = max(signal_ports.keys())
        expected = set(range(1, n_signals + 1))
        if set(signal_ports.keys()) != expected:
            raise ValueError(
                f"Signal port indices must be consecutive starting from 1. "
                f"Got indices: {sorted(signal_ports.keys())}"
            )
        if n_signals < 2:
            raise ValueError("At least two signal ports (s1, s2) are required.")

        # Build ordered port indices: [s1_idx, s2_idx, ..., sN_idx]
        ordered_ks = [port_map[signal_ports[i]] for i in range(1, n_signals + 1)]

        if super_net.nports != n_signals:
            raise ValueError(
                f"After all terminations, expected {n_signals} ports but got {super_net.nports}. "
                "Ensure all non-signal ports are terminated."
            )

        # Reorder ports if needed so port 0=s1, port 1=s2, ..., port N-1=sN
        # NOTE: skrf renumber() is in-place and returns None — do NOT reassign
        target = list(range(n_signals))
        if ordered_ks != target:
            super_net.renumber(ordered_ks, target)

        return super_net

    def _load_networks(self) -> Dict[str, rf.Network]:
        """Load all .snp files and interpolate to common frequency grid."""
        freq = rf.Frequency(
            self.config.freq_start_ghz,
            self.config.freq_stop_ghz,
            self.config.freq_npoints,
            'ghz'
        )
        nets = {}
        for nid, path in self.config.networks.items():
            net = rf.Network(path)
            nets[nid] = net.interpolate(freq)
        return nets

    def _block_diagonal(self, nets: list) -> rf.Network:
        """Combine networks into a single block-diagonal super-network."""
        total_ports = sum(n.nports for n in nets)
        freq = nets[0].frequency
        nf = len(freq)
        s = np.zeros((nf, total_ports, total_ports), dtype=complex)
        z0 = np.zeros((nf, total_ports), dtype=complex)
        offset = 0
        for n in nets:
            p = n.nports
            s[:, offset:offset+p, offset:offset+p] = n.s
            z0[:, offset:offset+p] = n.z0
            offset += p
        return rf.Network(frequency=freq, s=s, z0=z0)

    def _update_port_map_innerconnect(
        self, port_map: dict, k: int, l: int, key1: tuple, key2: tuple
    ) -> dict:
        """Update port_map after innerconnect(ntwk, k, l) removes ports k and l."""
        lo, hi = min(k, l), max(k, l)
        new_map = {}
        for key, idx in port_map.items():
            if key == key1 or key == key2:
                continue  # removed
            if idx > hi:
                new_map[key] = idx - 2
            elif idx > lo:
                new_map[key] = idx - 1
            else:
                new_map[key] = idx
        return new_map

    def _update_port_map_connect(self, port_map: dict, k: int, removed_key: tuple) -> dict:
        """Update port_map after connect(super_net, k, term_1port, 0) removes port k."""
        new_map = {}
        for key, idx in port_map.items():
            if key == removed_key:
                continue  # removed
            if idx > k:
                new_map[key] = idx - 1
            else:
                new_map[key] = idx
        return new_map

    def _build_termination_network(self, term: PortTermination, freq: rf.Frequency) -> rf.Network:
        """
        Build a 1-port termination network.

        - open:                    S11 = +1 (total reflection, no current)
        - short:                   S11 = -1 (short to ground)
        - capacitor/inductor:      .s2p shunt element — port 1 connected to SHORT (ground)
        - capacitor_series/        .s2p series element — port 1 connected to OPEN (floating),
          inductor_series:         giving series-mode (not shunt-to-ground) behaviour.
        """
        nf = len(freq)

        if term.type == 'open':
            s = np.ones((nf, 1, 1), dtype=complex)
            return rf.Network(frequency=freq, s=s)

        elif term.type == 'short':
            s = -np.ones((nf, 1, 1), dtype=complex)
            return rf.Network(frequency=freq, s=s)

        elif term.type in ('capacitor', 'inductor'):
            if not term.component_path:
                raise ValueError(f"No component path for {term.type} termination")
            comp = rf.Network(term.component_path)
            comp = comp.interpolate(freq)
            # Shunt model: connect port 1 to short (ground) → 1-port shunt element
            short_s = -np.ones((nf, 1, 1), dtype=complex)
            short = rf.Network(frequency=freq, s=short_s)
            return connect(comp, 1, short, 0)

        elif term.type in ('capacitor_series', 'inductor_series'):
            if not term.component_path:
                raise ValueError(f"No component path for {term.type} termination")
            comp = rf.Network(term.component_path)
            comp = comp.interpolate(freq)
            # Series model: connect port 1 to open (floating) → 1-port series element
            open_s = np.ones((nf, 1, 1), dtype=complex)
            open_net = rf.Network(frequency=freq, s=open_s)
            return connect(comp, 1, open_net, 0)

        else:
            # Unknown: treat as open
            s = np.ones((nf, 1, 1), dtype=complex)
            return rf.Network(frequency=freq, s=s)

    @staticmethod
    def _build_termination_network_static(term: PortTermination, freq: rf.Frequency) -> rf.Network:
        """Static wrapper for _build_termination_network (used by Rust-accelerated sweep)."""
        dummy = NetworkBuilder.__new__(NetworkBuilder)
        return dummy._build_termination_network(term, freq)


def build_network_from_config(config: NetworkConfig) -> rf.Network:
    """Convenience function: build and return N-port network from config."""
    builder = NetworkBuilder(config)
    return builder.build()


def build_base_network_for_fleet(
    config: NetworkConfig,
    tunable_port_keys: list  # list of (network_id, 1-based port_num)
) -> tuple:
    """
    Build the base network for Rust-accelerated fleet sweep.

    Like build() but:
    - Does NOT terminate tunable ports (leaves them as open ports in the network)
    - Reorders remaining ports to: [s1=0, s2=1, ..., sN=N-1, t0=N, t1=N+1, ..., tk=N+k]

    Returns:
        (net, ordered_port_keys)
        net: rf.Network with ports [s1, s2, ..., sN, t0, t1, ..., tk]
        ordered_port_keys: [(nid, pnum), ...] matching net port indices
    """
    builder = NetworkBuilder(config)
    nets = builder._load_networks()

    # Build port map: (nid, 1-based) -> 0-based global index
    port_map: dict = {}
    offset = 0
    for nid in nets:
        for p in range(nets[nid].nports):
            port_map[(nid, p + 1)] = offset + p
        offset += nets[nid].nports

    # Block-diagonal super-network
    super_net = builder._block_diagonal(list(nets.values()))

    tunable_set = set(tuple(k) for k in tunable_port_keys)

    # Apply inter-network connections (innerconnect)
    seen_pairs = set()
    for nid, terms in config.terminations.items():
        for port, term in terms.items():
            if term.type != 'connect':
                continue
            cid, cport = term.connect_to
            pair = tuple(sorted([(nid, port), (cid, cport)]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            k = port_map[(nid, port)]
            l = port_map[(cid, cport)]
            super_net = innerconnect(super_net, k, l)
            port_map = builder._update_port_map_innerconnect(
                port_map, k, l, (nid, port), (cid, cport)
            )

    # Find signal port indices BEFORE terminating
    signal_ports = {}
    for nid, terms in config.terminations.items():
        for port, term in terms.items():
            if term.type == 'signal':
                signal_ports[term.signal_port_index] = (nid, port)

    # Apply FIXED terminations only (skip tunable and signal and connect)
    for nid, terms in config.terminations.items():
        for port, term in terms.items():
            if term.type in ('connect', 'signal'):
                continue
            if (nid, port) in tunable_set:
                continue  # leave tunable ports open in the network
            if (nid, port) not in port_map:
                continue
            k = port_map[(nid, port)]
            term_net = builder._build_termination_network(term, super_net.frequency)
            super_net = connect(super_net, k, term_net, 0)
            port_map = builder._update_port_map_connect(port_map, k, (nid, port))

    # Reorder: [s1, s2, ..., sN, t0, t1, ..., tk]
    if not signal_ports:
        raise ValueError("No signal ports defined. At least s1 and s2 are required.")
    n_signals = max(signal_ports.keys())
    expected = set(range(1, n_signals + 1))
    if set(signal_ports.keys()) != expected:
        raise ValueError(
            f"Signal port indices must be consecutive starting from 1. "
            f"Got indices: {sorted(signal_ports.keys())}"
        )
    if n_signals < 2:
        raise ValueError("At least two signal ports (s1, s2) are required.")

    signal_indices = [port_map[signal_ports[i]] for i in range(1, n_signals + 1)]
    tunable_indices = [port_map[tuple(k)] for k in tunable_port_keys
                       if tuple(k) in port_map]

    desired_order = signal_indices + tunable_indices
    to_ports = list(range(len(desired_order)))

    if len(desired_order) != super_net.nports:
        raise ValueError(
            f"Port count mismatch: {super_net.nports} ports in network but "
            f"{len(desired_order)} in desired order. "
            "Check that all non-signal, non-tunable ports are terminated."
        )

    # NOTE: skrf renumber() is in-place and returns None — do NOT reassign
    super_net.renumber(desired_order, to_ports)

    # Build ordered_port_keys: [s1_key, s2_key, ..., sN_key, t0_key, ...]
    ordered_port_keys = [signal_ports[i] for i in range(1, n_signals + 1)] + [
        tuple(k) for k in tunable_port_keys if tuple(k) in port_map
    ]

    return super_net, ordered_port_keys
