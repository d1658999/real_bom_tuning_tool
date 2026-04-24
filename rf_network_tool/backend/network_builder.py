"""
RF Network cascade builder.
Loads multiple .snp Touchstone files, connects ports between networks,
applies terminations (open/short/capacitor/inductor), and returns a 2-port network.

Uses scikit-rf (skrf) for all S-parameter operations.

Algorithm:
1. Load all .snp files as rf.Network objects and interpolate to common freq grid
2. Build a block-diagonal super-network concatenating all networks
3. Track port mapping: (network_id, 1-based port) -> 0-based global port index
4. Apply inter-network connections using rf.innerconnect
5. Apply terminations (open/short/component) using rf.connect with 1-port networks
6. Result is a 2-port network between the marked s1 and s2 ports

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
    """Builds a final 2-port S-parameter network from a NetworkConfig."""

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

        # 7. Reorder to [s1, s2] and return
        if not signal_ports.get(1) or not signal_ports.get(2):
            raise ValueError("Must define exactly one s1 and one s2 signal port")

        k1 = port_map[signal_ports[1]]
        k2 = port_map[signal_ports[2]]

        if super_net.nports != 2:
            raise ValueError(
                f"After all terminations, expected 2 ports but got {super_net.nports}. "
                "Ensure all non-signal ports are terminated."
            )

        # Reorder ports if needed so port 0 = s1, port 1 = s2
        if k1 != 0 or k2 != 1:
            super_net = super_net.renumber([k1, k2], [0, 1])

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

        - open:       S11 = +1 everywhere (total reflection, no current)
        - short:      S11 = -1 everywhere (short to ground)
        - capacitor/inductor (shunt): load .s2p series model, connect port 1 to short
          (ground) → returns 1-port shunt element seen from port 0.
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
            # Shunt model: connect comp port 1 (index 1) to short → 1-port remains
            short_s = -np.ones((nf, 1, 1), dtype=complex)
            short = rf.Network(frequency=freq, s=short_s)
            shunt_1port = connect(comp, 1, short, 0)
            return shunt_1port

        else:
            # Unknown: treat as open
            s = np.ones((nf, 1, 1), dtype=complex)
            return rf.Network(frequency=freq, s=s)


def build_network_from_config(config: NetworkConfig) -> rf.Network:
    """Convenience function: build and return 2-port network from config."""
    builder = NetworkBuilder(config)
    return builder.build()
