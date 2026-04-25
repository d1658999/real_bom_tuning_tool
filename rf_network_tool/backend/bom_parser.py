"""
BOM parser for Murata capacitor and inductor component libraries.
Scans Capacitors_BOM/ and Inductors_BOM/ folders (relative to project root).
"""
from pathlib import Path
import re

def get_project_root() -> Path:
    """Return project root: parent of rf_network_tool/."""
    return Path(__file__).parent.parent.parent

def _parse_cap_value(code: str) -> str:
    """
    Parse capacitor value from EIA code portion of filename.
    Examples: 'R20' -> '0.2pF', '1R0' -> '1.0pF', '100' -> '10.0pF', '220' -> '22.0pF'
    Rules:
      - If contains 'R': R is decimal separator ('R20' -> '0.20', '1R0' -> '1.0', '4R7' -> '4.7')
      - Else (3 digits XYZ): value = int(XY) * 10**int(Z) (e.g. '100' -> 10*1 = 10pF, '220' -> 22pF)
    """
    code = code.upper()
    if 'R' in code:
        parts = code.split('R')
        left = parts[0] if parts[0] else '0'
        right = parts[1] if len(parts) > 1 else '0'
        val = float(f"{left}.{right}")
        return f"{val:.2g}pF"
    elif len(code) == 3 and code.isdigit():
        mantissa = int(code[:2])
        exp = int(code[2])
        val = mantissa * (10 ** exp)
        return f"{val:.4g}pF"
    return code + "pF"


def _parse_cap_value_pf(code: str) -> float:
    """Return capacitor value as a float in pF; returns 0.0 if unparseable."""
    code = code.upper()
    try:
        if 'R' in code:
            parts = code.split('R')
            left = parts[0] if parts[0] else '0'
            right = parts[1] if len(parts) > 1 else '0'
            return float(f"{left}.{right}")
        elif len(code) == 3 and code.isdigit():
            return float(int(code[:2]) * (10 ** int(code[2])))
    except (ValueError, IndexError):
        pass
    return 0.0


def _parse_ind_value(code: str) -> str:
    """
    Parse inductor value from code portion (between TQ and H02/B02).
    Examples: '0N2' -> '0.2nH', '1N0' -> '1.0nH', '10N' -> '10nH', '10' -> '10nH', '22' -> '22nH'
    N acts as decimal separator or trailing unit indicator.
    """
    code = code.upper()
    if 'N' in code:
        parts = code.split('N')
        left = parts[0] if parts[0] else '0'
        right = parts[1] if (len(parts) > 1 and parts[1]) else ''
        if right:
            val = float(f"{left}.{right}")
        else:
            val = float(left)
        return f"{val:.4g}nH"
    elif code.isdigit():
        return f"{int(code)}nH"
    return code + "nH"


def _parse_ind_value_nh(code: str) -> float:
    """Return inductor value as a float in nH; returns 0.0 if unparseable."""
    code = code.upper()
    try:
        if 'N' in code:
            parts = code.split('N')
            left = parts[0] if parts[0] else '0'
            right = parts[1] if (len(parts) > 1 and parts[1]) else ''
            return float(f"{left}.{right}") if right else float(left)
        elif code.isdigit():
            return float(int(code))
    except (ValueError, IndexError):
        pass
    return 0.0

def list_capacitors() -> list:
    """Return list of dicts: {name, path, display_name, value_pF}"""
    bom_dir = get_project_root() / "Capacitors_BOM"
    results = []
    for f in sorted(bom_dir.glob("*.s2p")):
        name = f.stem
        m = re.search(r'C1E([0-9R]+)[A-Z]+01', name, re.IGNORECASE)
        if m:
            code = m.group(1).upper()
            display = f"{_parse_cap_value(code)} - {name}"
            value_pf = _parse_cap_value_pf(code)
        else:
            display = name
            value_pf = 0.0
        results.append({"name": name, "path": str(f), "display_name": display, "value_pF": value_pf})
    return results

def list_inductors() -> list:
    """Return list of dicts: {name, path, display_name, value_nH}"""
    bom_dir = get_project_root() / "Inductors_BOM"
    results = []
    for f in sorted(bom_dir.glob("*.s2p")):
        name = f.stem
        m = re.search(r'TQ([0-9N]+)[A-Z]\d+', name, re.IGNORECASE)
        if m:
            code = m.group(1).upper()
            display = f"{_parse_ind_value(code)} - {name}"
            value_nh = _parse_ind_value_nh(code)
        else:
            display = name
            value_nh = 0.0
        results.append({"name": name, "path": str(f), "display_name": display, "value_nH": value_nh})
    return results

def get_capacitor_path(name: str) -> str:
    """Get absolute path of capacitor .s2p by stem name."""
    bom_dir = get_project_root() / "Capacitors_BOM"
    p = bom_dir / (name + ".s2p")
    if p.exists():
        return str(p)
    for f in bom_dir.glob(f"{name}*"):
        return str(f)
    raise FileNotFoundError(f"Capacitor not found: {name}")

def get_inductor_path(name: str) -> str:
    """Get absolute path of inductor .s2p by stem name."""
    bom_dir = get_project_root() / "Inductors_BOM"
    p = bom_dir / (name + ".s2p")
    if p.exists():
        return str(p)
    for f in bom_dir.glob(f"{name}*"):
        return str(f)
    raise FileNotFoundError(f"Inductor not found: {name}")
