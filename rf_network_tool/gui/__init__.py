"""GUI package for RF Network Tool."""
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class PortConfig:
    """Configuration for one port."""
    label: str = ""
    term_type: str = "open"    # open|short|capacitor|inductor|connect|signal
    component_path: str = ""   # abs path for cap/ind
    component_name: str = ""   # display name
    connect_to_file: str = ""  # file id for 'connect' type
    connect_to_port: int = 1   # 1-based port number
    signal_index: int = 1      # 1 or 2 for 'signal' type


@dataclass
class FileConfig:
    """Configuration for one loaded .snp file."""
    file_id: str       # unique id (file stem)
    file_path: str     # absolute path
    display_name: str  # filename
    nports: int        # number of ports
    ports: Dict[int, PortConfig] = field(default_factory=dict)  # 1-based


@dataclass
class AppState:
    """Global application state."""
    files: Dict[str, FileConfig] = field(default_factory=dict)
    freq_start_ghz: float = 3.3
    freq_stop_ghz: float = 5.0
    freq_npoints: int = 201
    result_network: object = None  # rf.Network or None
