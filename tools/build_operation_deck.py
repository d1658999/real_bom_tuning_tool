"""Build a lightweight PPTX operation guide for RF Network Tool.

This intentionally avoids external presentation libraries so it can run on a
fresh checkout with only the Python standard library.
"""
from __future__ import annotations

import html
import os
import struct
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "RF_Network_Tool_GUI_Operation_Guide.pptx"

EMU_PER_IN = 914400
SLIDE_W = 13.333333 * EMU_PER_IN
SLIDE_H = 7.5 * EMU_PER_IN

NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def emu(inches: float) -> int:
    return int(round(inches * EMU_PER_IN))


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as f:
        sig = f.read(24)
    if sig[:8] != b"\x89PNG\r\n\x1a\n":
        return (1200, 800)
    return struct.unpack(">II", sig[16:24])


def fit_image(path: Path, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
    iw, ih = png_size(path)
    scale = min(w / iw, h / ih)
    nw = int(iw * scale)
    nh = int(ih * scale)
    return x + (w - nw) // 2, y + (h - nh) // 2, nw, nh


def text_box(
    shape_id: int,
    name: str,
    x: float,
    y: float,
    w: float,
    h: float,
    paragraphs: list[str],
    font_size: int = 20,
    color: str = "1F2937",
    bold: bool = False,
    fill: str | None = None,
    line: str | None = None,
) -> str:
    fill_xml = (
        f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>'
        if fill
        else "<a:noFill/>"
    )
    line_xml = (
        f'<a:ln w="9525"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>'
        if line
        else '<a:ln><a:noFill/></a:ln>'
    )
    runs = []
    bold_attr = ' b="1"' if bold else ""
    for i, para in enumerate(paragraphs):
        if para.startswith("- "):
            text = para
        else:
            text = para
        runs.append(
            f'<a:p><a:pPr marL="0" indent="0"/>'
            f'<a:r><a:rPr lang="en-US" sz="{font_size * 100}"'
            f'{bold_attr}>'
            f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
            f"</a:rPr><a:t>{esc(text)}</a:t></a:r>"
            f"</a:p>"
        )
        if i != len(paragraphs) - 1:
            pass
    return f"""
    <p:sp>
      <p:nvSpPr><p:cNvPr id="{shape_id}" name="{esc(name)}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
      <p:spPr>
        <a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>
        <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        {fill_xml}
        {line_xml}
      </p:spPr>
      <p:txBody><a:bodyPr wrap="square" anchor="t" lIns="91440" tIns="45720" rIns="91440" bIns="45720"/><a:lstStyle/>
        {''.join(runs)}
      </p:txBody>
    </p:sp>
    """


def rect(shape_id: int, name: str, x: float, y: float, w: float, h: float, fill: str, line: str = "D1D5DB") -> str:
    return f"""
    <p:sp>
      <p:nvSpPr><p:cNvPr id="{shape_id}" name="{esc(name)}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
      <p:spPr>
        <a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>
        <a:prstGeom prst="roundRect"><a:avLst/></a:prstGeom>
        <a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>
        <a:ln w="9525"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>
      </p:spPr>
    </p:sp>
    """


def picture(shape_id: int, rid: str, name: str, x: int, y: int, w: int, h: int) -> str:
    return f"""
    <p:pic>
      <p:nvPicPr><p:cNvPr id="{shape_id}" name="{esc(name)}"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>
      <p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>
      <p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>
    </p:pic>
    """


SLIDES = [
    {
        "title": "RF Network Cascade Tool",
        "subtitle": "GUI operation guide for S-parameter cascade, BOM tuning, and Fleet optimization",
        "bullets": [
            "- Audience: RF front-end engineers and tool users",
            "- Goal: operate the tool confidently from file load to final report",
            "- Visuals: local GUI/result images from the project workspace",
        ],
        "images": [ROOT / "Dual_tune.png"],
    },
    {
        "title": "1. Main GUI Layout",
        "bullets": [
            "- Left: Loaded S-Parameter Files",
            "- Center: Port Configuration and frequency controls",
            "- Right: Smith Chart, VSWR, Insertion Loss, and Summary",
            "- Toolbar: Run Cascade, Export SNP, Run Fleet, Save Config, Load Config",
        ],
        "diagram": "layout",
    },
    {
        "title": "2. Load Touchstone Files",
        "bullets": [
            "- Click Add Files... in the left panel",
            "- Select one or more .snp files: .s2p, .s3p, .s4p, .s10p, .s12p, and similar",
            "- Check that each file appears with the correct port count",
            "- Select a file to configure its port rows in the center panel",
        ],
        "callouts": ["Add Files...", "Remove Selected", "filename.sNp (N ports)"],
    },
    {
        "title": "3. Configure Port Roles",
        "bullets": [
            "- Edit Label if a port name helps the audience understand the topology",
            "- Use Termination for open, short, capacitor, inductor, connect, signal, or Fleet sweep modes",
            "- Keep unused ports as open or short based on the RF design",
            "- Assign external I/O ports as s1, s2, s3, or s4",
        ],
        "diagram": "table",
    },
    {
        "title": "4. Fixed Components vs Fleet Sweep",
        "bullets": [
            "- capacitor / inductor: pick one fixed BOM component; Fleet treats it as locked",
            "- open/ind, open/cap, open/ind/cap: sweep from an open baseline",
            "- short/ind, short/cap, short/ind/cap: sweep from a short baseline",
            "- Use nH and pF min/max fields to constrain the search space",
        ],
        "diagram": "matrix",
    },
    {
        "title": "5. Connect Ports Between Files",
        "bullets": [
            "- Choose connect when one port must be wired to another loaded network",
            "- Select target File and target Port in the dynamic control area",
            "- Configure the opposite port back to the original file and port",
            "- Symmetric connections are required for a trustworthy cascade result",
        ],
        "diagram": "connect",
    },
    {
        "title": "6. Signal Ranges and Antenna Rule",
        "bullets": [
            "- At least s1 and s2 are required before Run Cascade and Run Fleet are enabled",
            "- Signal indices must be consecutive: s1/s2, then s3, then s4",
            "- The highest signal index is treated as the antenna port",
            "- Set Start GHz and Stop GHz per non-antenna signal; antenna uses the union range",
        ],
        "diagram": "ranges",
    },
    {
        "title": "7. Run Cascade and Read Results",
        "bullets": [
            "- Click Run Cascade after files, connections, and signal ports are valid",
            "- Smith Chart shows reflection traces with a VSWR=2 reference circle",
            "- VSWR plot confirms match quality across each signal band",
            "- IL plot shows transmission from signal paths to the antenna port",
        ],
        "images": [ROOT / "fleet_results" / "final_decision.png"],
    },
    {
        "title": "8. Save, Load, and Export",
        "bullets": [
            "- Save Config writes the full setup to JSON",
            "- Load Config restores files, port roles, components, connections, and signal ranges",
            "- Export SNP is enabled only after a successful cascade",
            "- Saved .snp paths are absolute; update paths if the project is moved",
        ],
        "diagram": "files",
    },
    {
        "title": "9. Run Fleet Optimization",
        "bullets": [
            "- Click Run Fleet to open the Fleet Progress dialog",
            "- Fleet only sweeps ports configured as open/* or short/* sweep modes",
            "- Fixed capacitor and inductor selections stay locked during optimization",
            "- The dialog shows tunable ports, sweep progress, agent summaries, risk scores, and final output path",
            "- Close becomes available when the optimizer finishes or reports an error",
        ],
        "diagram": "fleet_dialog",
    },
    {
        "title": "10. Before Clicking Run Fleet",
        "bullets": [
            "- Save Config first so the original setup can be restored after tuning",
            "- Mark tunable ports with open/ind, open/cap, open/ind/cap, short/ind, short/cap, or short/ind/cap",
            "- Limit each tunable port with realistic nH and pF ranges to reduce search time",
            "- Confirm BOM folders are available and the live candidate counts are not zero",
            "- Confirm at least s1 and s2 are defined, consecutive, and frequency ranges overlap the .snp data",
        ],
        "diagram": "fleet_prepare",
    },
    {
        "title": "11. What Fleet Does Internally",
        "bullets": [
            "- Phase 1: build the base network and identify all tunable ports",
            "- Phase 1: create candidate lists from BOM files, including the baseline open or short option",
            "- Phase 1: sweep all component combinations and evaluate valid cascades",
            "- Phase 2: run five strategy agents against the shared sweep results",
            "- Phase 3: compute normalized production risk scores and choose the lowest-risk winner",
            "- Phase 4: save JSON, plots, comparison chart, final decision plot, and Markdown report",
        ],
        "diagram": "fleet_phases",
    },
    {
        "title": "12. Five Agent Strategies",
        "bullets": [
            "- Agent 1 - Min BOM: choose the fewest components within 10 percent of the best achievable VSWR",
            "- Agent 2 - Balance: trade off low VSWR and low insertion loss",
            "- Agent 3 - Min VSWR: strictly minimize peak VSWR across signal ports",
            "- Agent 4 - Smith Contour: prefer the tightest Smith-chart cluster near center",
            "- Agent 5 - Min IL: maximize transmission by minimizing insertion loss",
        ],
        "diagram": "fleet_strategies",
    },
    {
        "title": "13. How Risk Score Is Decided",
        "bullets": [
            "- Lower Risk Score is better; the Principal agent selects the lowest value",
            "- Score blends normalized metrics so no single raw unit dominates",
            "- 30 percent: worst VSWR under +/-5 percent tolerance",
            "- 25 percent: component count, because simpler BOMs are lower production risk",
            "- 20 percent: VSWR sensitivity under tolerance",
            "- 15 percent: insertion loss penalty, and 10 percent: VSWR spread between ports",
        ],
        "diagram": "risk_formula",
    },
    {
        "title": "14. Read fleet_comparison.png",
        "bullets": [
            "- Use this chart to compare all five agents side by side",
            "- VSWR S11 Max: worst match across non-antenna signal ports; lower is better",
            "- VSWR S22 Max: antenna/common-port VSWR across the union of signal bands; lower is better",
            "- Worst IL (dB): most negative transmission value; closer to 0 dB is better",
            "- Component Count: number of non-baseline assigned parts; lower is usually safer",
            "- Risk Score: final combined ranking metric; lowest bar is the production recommendation",
        ],
        "images": [ROOT / "fleet_results" / "fleet_comparison.png"],
    },
    {
        "title": "15. Read final_decision.png",
        "bullets": [
            "- The title names the winning agent, risk score, and strategy",
            "- Smith Chart shows the final reflection loci; traces closer to center indicate better match",
            "- Dashed reference circles/lines help identify VSWR targets such as 1.4 and 2.0",
            "- VSWR plot verifies pass/fail behavior across the selected frequency ranges",
            "- IL plot shows each signal-to-antenna path; flatter and closer to 0 dB is better",
        ],
        "images": [ROOT / "fleet_results" / "final_decision.png"],
    },
    {
        "title": "16. Read JSON and fleet_report.md",
        "bullets": [
            "- agent_N_result.json records each agent's selected assignments and metrics",
            "- assignments show network_id, port_index, final term_type, component_name, and component_path",
            "- fleet_report.md starts with the Winner, Strategy, Risk Score, and selection reason",
            "- The comparison table is the fastest way to explain tradeoffs in a design review",
            "- Final Component Assignments is the list to copy back into the GUI or BOM tuning record",
        ],
        "diagram": "fleet_artifacts",
    },
    {
        "title": "17. Run Fleet Troubleshooting",
        "bullets": [
            "- Run Fleet disabled: define consecutive signal ports starting at s1 and s2",
            "- No tunable ports: change at least one port to an open/* or short/* sweep mode",
            "- Empty or slow sweep: tighten nH/pF ranges and confirm BOM folders are populated",
            "- Empty plots or no valid configurations: check signal frequency ranges overlap all loaded .snp files",
            "- Unexpected winner: compare risk score, component count, VSWR tolerance, and IL rather than one metric alone",
        ],
        "diagram": "fleet_troubleshoot",
    },
    {
        "title": "18. Operator Checklist",
        "bullets": [
            "- BOM folders must sit beside the source/project or packaged executable",
            "- Signal indices must be unique and consecutive across all loaded files",
            "- Frequency ranges must overlap the .snp simulation grid",
            "- Save the starting config before Fleet because optimization can change active assignments",
            "- Re-run Fleet when more confidence is needed in the random subset sweep",
        ],
        "diagram": "checklist",
    },
]


def slide_xml(idx: int, slide: dict, image_rids: list[tuple[str, Path]]) -> str:
    shapes: list[str] = []
    sid = 2
    shapes.append(text_box(sid, "Title", 0.55, 0.28, 12.2, 0.55, [slide["title"]], font_size=28, color="111827", bold=True))
    sid += 1
    shapes.append(rect(sid, "Accent", 0.55, 0.9, 12.2, 0.035, "2563EB", "2563EB"))
    sid += 1

    if "subtitle" in slide:
        shapes.append(text_box(sid, "Subtitle", 0.65, 1.0, 5.8, 0.85, [slide["subtitle"]], font_size=17, color="374151"))
        sid += 1

    bullets = slide.get("bullets", [])
    if image_rids:
        shapes.append(text_box(sid, "Bullets", 0.65, 1.85 if "subtitle" in slide else 1.1, 5.25, 4.9, bullets, font_size=15, color="1F2937"))
        sid += 1
        if len(image_rids) == 1:
            path = image_rids[0][1]
            x, y, w, h = fit_image(path, emu(6.05), emu(1.15), emu(6.65), emu(5.55))
            shapes.append(picture(sid, image_rids[0][0], path.name, x, y, w, h))
            sid += 1
        else:
            for n, (rid, path) in enumerate(image_rids):
                x0 = 6.1
                y0 = 1.15 + n * 2.8
                x, y, w, h = fit_image(path, emu(x0), emu(y0), emu(6.55), emu(2.55))
                shapes.append(picture(sid, rid, path.name, x, y, w, h))
                sid += 1
    elif slide.get("diagram") or slide.get("callouts"):
        shapes.append(text_box(sid, "Bullets", 0.65, 1.1, 5.35, 5.55, bullets, font_size=15, color="1F2937"))
        sid += 1
        shapes.extend(diagram_shapes(slide, sid))
        sid += 20
    else:
        shapes.append(text_box(sid, "Bullets", 0.9, 1.25, 11.5, 5.4, bullets, font_size=18, color="1F2937"))
        sid += 1

    shapes.append(text_box(900, "Footer", 0.55, 7.05, 12.2, 0.25, [f"RF Network Cascade Tool operation guide  |  Slide {idx}"], font_size=8, color="6B7280"))
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}">
  <p:cSld>
    <p:bg><p:bgPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
      {''.join(shapes)}
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>
"""


def diagram_shapes(slide: dict, start_id: int) -> list[str]:
    kind = slide.get("diagram")
    callouts = slide.get("callouts")
    sid = start_id
    out: list[str] = []
    if callouts:
        y = 1.55
        for text in callouts:
            out.append(rect(sid, text, 6.4, y, 5.55, 0.7, "EFF6FF", "93C5FD")); sid += 1
            out.append(text_box(sid, text, 6.55, y + 0.13, 5.2, 0.36, [text], font_size=16, color="1E3A8A", bold=True)); sid += 1
            y += 1.0
    elif kind == "layout":
        boxes = [("Loaded files", "Add/remove Touchstone files"), ("Port configuration", "Frequency, port roles, BOM parts"), ("Results", "Smith, VSWR, IL, Summary")]
        for i, (a, b) in enumerate(boxes):
            x = 6.25 + i * 2.05
            out.append(rect(sid, a, x, 1.65, 1.8, 3.4, ["DBEAFE", "ECFDF5", "FEF3C7"][i], ["60A5FA", "34D399", "F59E0B"][i])); sid += 1
            out.append(text_box(sid, a, x + 0.1, 1.95, 1.6, 0.7, [a], font_size=14, color="111827", bold=True)); sid += 1
            out.append(text_box(sid, b, x + 0.1, 2.8, 1.6, 1.0, [b], font_size=10, color="374151")); sid += 1
    elif kind == "table":
        rows = ["Port # | Label | Termination | Component / Connect", "1 | TX | signal | s1", "2 | Match | open/ind | 0.2-4.7 nH", "3 | Link | connect | Filter_A port 1"]
        for i, row in enumerate(rows):
            fill = "E5E7EB" if i == 0 else "F9FAFB"
            out.append(rect(sid, f"row{i}", 6.25, 1.35 + i * 0.72, 5.95, 0.58, fill, "D1D5DB")); sid += 1
            out.append(text_box(sid, f"rowtext{i}", 6.4, 1.46 + i * 0.72, 5.6, 0.3, [row], font_size=10, color="111827", bold=(i == 0))); sid += 1
    elif kind == "matrix":
        rows = [("Fixed", "capacitor / inductor", "Single locked BOM part"), ("Open sweep", "open/ind/cap", "Try BOM values from open baseline"), ("Short sweep", "short/ind/cap", "Try BOM values from short baseline")]
        for i, (a, b, c) in enumerate(rows):
            out.append(rect(sid, a, 6.25, 1.35 + i * 1.05, 5.95, 0.8, ["F3F4F6", "EFF6FF", "FEF3C7"][i], "D1D5DB")); sid += 1
            out.append(text_box(sid, a, 6.45, 1.45 + i * 1.05, 1.45, 0.3, [a], font_size=12, color="111827", bold=True)); sid += 1
            out.append(text_box(sid, b, 8.0, 1.45 + i * 1.05, 1.55, 0.3, [b], font_size=10, color="2563EB", bold=True)); sid += 1
            out.append(text_box(sid, c, 9.65, 1.45 + i * 1.05, 2.25, 0.3, [c], font_size=10, color="374151")); sid += 1
    elif kind == "connect":
        out.append(rect(sid, "File A", 6.35, 2.0, 2.0, 1.0, "DBEAFE", "60A5FA")); sid += 1
        out.append(text_box(sid, "File A text", 6.65, 2.32, 1.4, 0.35, ["File A port 2"], font_size=13, bold=True)); sid += 1
        out.append(rect(sid, "File B", 10.0, 2.0, 2.0, 1.0, "ECFDF5", "34D399")); sid += 1
        out.append(text_box(sid, "File B text", 10.3, 2.32, 1.4, 0.35, ["File B port 1"], font_size=13, bold=True)); sid += 1
        out.append(text_box(sid, "Arrow", 8.58, 2.26, 1.2, 0.3, ["<---->"], font_size=20, color="111827", bold=True)); sid += 1
        out.append(text_box(sid, "Symmetric", 6.55, 3.45, 5.0, 0.8, ["Both ends must point to each other"], font_size=16, color="92400E", bold=True, fill="FFFBEB", line="F59E0B")); sid += 1
    elif kind == "ranges":
        rows = ["s1: 1.700 - 2.200 GHz", "s2: 2.300 - 2.700 GHz", "s3 (ant): 1.700 - 2.700 GHz union"]
        for i, row in enumerate(rows):
            out.append(rect(sid, row, 6.45, 1.55 + i * 0.85, 5.3, 0.58, "F9FAFB", "D1D5DB")); sid += 1
            out.append(text_box(sid, row, 6.65, 1.68 + i * 0.85, 4.8, 0.3, [row], font_size=14, color="111827", bold=(i == 2))); sid += 1
    elif kind == "files":
        labels = ["Save Config -> setup.json", "Load Config <- setup.json", "Export SNP -> cascade_result.sNp"]
        for i, label in enumerate(labels):
            out.append(rect(sid, label, 6.35, 1.55 + i * 1.0, 5.65, 0.72, "F3F4F6", "9CA3AF")); sid += 1
            out.append(text_box(sid, label, 6.55, 1.72 + i * 1.0, 5.1, 0.3, [label], font_size=15, color="111827", bold=True)); sid += 1
    elif kind == "checklist":
        labels = ["BOM folders found", "Signals unique", "Bands overlap data", "Config saved", "Fleet report reviewed"]
        for i, label in enumerate(labels):
            out.append(rect(sid, label, 6.4, 1.25 + i * 0.72, 5.5, 0.5, "F0FDF4", "86EFAC")); sid += 1
            out.append(text_box(sid, label, 6.58, 1.35 + i * 0.72, 5.0, 0.25, [f"[ ] {label}"], font_size=13, color="14532D", bold=True)); sid += 1
    elif kind == "fleet_dialog":
        rows = [
            ("Run Fleet", "Open progress dialog"),
            ("Tunable ports", "List open/* and short/* rows"),
            ("Progress log", "Sweep, agents, scores"),
            ("Close", "Enabled after finish/error"),
        ]
        for i, (a, b) in enumerate(rows):
            y = 1.35 + i * 0.82
            out.append(rect(sid, a, 6.25, y, 5.95, 0.62, "EFF6FF" if i == 0 else "F9FAFB", "93C5FD" if i == 0 else "D1D5DB")); sid += 1
            out.append(text_box(sid, a, 6.45, y + 0.13, 1.65, 0.25, [a], font_size=12, color="111827", bold=True)); sid += 1
            out.append(text_box(sid, b, 8.25, y + 0.13, 3.55, 0.25, [b], font_size=12, color="374151")); sid += 1
    elif kind == "fleet_prepare":
        labels = [
            "Save Config",
            "Set sweep modes",
            "Constrain ranges",
            "Check BOM counts",
            "Check signal bands",
        ]
        for i, label in enumerate(labels):
            y = 1.1 + i * 0.74
            out.append(rect(sid, label, 6.35, y, 5.75, 0.52, "F0FDF4", "86EFAC")); sid += 1
            out.append(text_box(sid, label, 6.55, y + 0.11, 5.25, 0.24, [f"{i+1}. {label}"], font_size=13, color="14532D", bold=True)); sid += 1
    elif kind == "fleet_phases":
        rows = [
            ("Phase 1", "Sweep BOM combinations"),
            ("Phase 2", "Run five strategy agents"),
            ("Phase 3", "Score production risk"),
            ("Phase 4", "Save plots and reports"),
        ]
        for i, (a, b) in enumerate(rows):
            x = 6.2 + (i % 2) * 3.05
            y = 1.45 + (i // 2) * 1.7
            out.append(rect(sid, a, x, y, 2.75, 1.05, ["DBEAFE", "ECFDF5", "FEF3C7", "FEE2E2"][i], ["60A5FA", "34D399", "F59E0B", "F87171"][i])); sid += 1
            out.append(text_box(sid, a, x + 0.15, y + 0.18, 2.3, 0.25, [a], font_size=13, color="111827", bold=True)); sid += 1
            out.append(text_box(sid, b, x + 0.15, y + 0.55, 2.35, 0.3, [b], font_size=11, color="374151")); sid += 1
    elif kind == "fleet_strategies":
        rows = [
            ("A1", "Min BOM", "fewest parts near best VSWR"),
            ("A2", "Balance", "VSWR plus IL"),
            ("A3", "Min VSWR", "lowest peak VSWR"),
            ("A4", "Smith", "tightest contour"),
            ("A5", "Min IL", "best transmission"),
        ]
        for i, (a, b, c) in enumerate(rows):
            y = 1.08 + i * 0.69
            out.append(rect(sid, a, 6.25, y, 5.95, 0.5, "F9FAFB", "D1D5DB")); sid += 1
            out.append(text_box(sid, a, 6.42, y + 0.09, 0.55, 0.23, [a], font_size=12, color="2563EB", bold=True)); sid += 1
            out.append(text_box(sid, b, 7.05, y + 0.09, 1.2, 0.23, [b], font_size=11, color="111827", bold=True)); sid += 1
            out.append(text_box(sid, c, 8.35, y + 0.09, 3.55, 0.23, [c], font_size=10, color="374151")); sid += 1
    elif kind == "risk_formula":
        rows = [
            ("0.30", "Worst VSWR under +/-5% tolerance"),
            ("0.25", "Component count"),
            ("0.20", "VSWR sensitivity"),
            ("0.15", "Insertion loss penalty"),
            ("0.10", "VSWR spread"),
        ]
        out.append(text_box(sid, "Risk formula", 6.25, 1.05, 5.95, 0.45, ["Risk Score = weighted normalized sum"], font_size=15, color="111827", bold=True, fill="EFF6FF", line="93C5FD")); sid += 1
        for i, (weight, label) in enumerate(rows):
            y = 1.75 + i * 0.58
            out.append(rect(sid, label, 6.35, y, 5.65, 0.4, "F9FAFB", "D1D5DB")); sid += 1
            out.append(text_box(sid, weight, 6.5, y + 0.07, 0.65, 0.2, [weight], font_size=11, color="DC2626", bold=True)); sid += 1
            out.append(text_box(sid, label, 7.25, y + 0.07, 4.45, 0.2, [label], font_size=10, color="374151")); sid += 1
    elif kind == "fleet_artifacts":
        labels = [
            "agent_N_result.json: exact chosen assignments",
            "agent_N_*.png: per-agent Smith/VSWR/IL",
            "fleet_comparison.png: compare strategies",
            "final_decision.png: winning plots",
            "fleet_report.md: design-review summary",
        ]
        for i, label in enumerate(labels):
            y = 1.1 + i * 0.72
            out.append(rect(sid, label, 6.25, y, 5.95, 0.5, "F3F4F6", "9CA3AF")); sid += 1
            out.append(text_box(sid, label, 6.45, y + 0.1, 5.45, 0.23, [label], font_size=11, color="111827", bold=True)); sid += 1
    elif kind == "fleet_troubleshoot":
        rows = [
            ("Disabled", "fix signal indices"),
            ("No tunables", "use open/* or short/*"),
            ("Slow", "tighten ranges"),
            ("No data", "check band overlap"),
            ("Winner surprise", "read risk tradeoff"),
        ]
        for i, (a, b) in enumerate(rows):
            y = 1.1 + i * 0.72
            out.append(rect(sid, a, 6.25, y, 5.95, 0.5, "FFFBEB", "F59E0B")); sid += 1
            out.append(text_box(sid, a, 6.45, y + 0.1, 1.45, 0.23, [a], font_size=11, color="92400E", bold=True)); sid += 1
            out.append(text_box(sid, b, 8.0, y + 0.1, 3.75, 0.23, [b], font_size=11, color="374151")); sid += 1
    return out


def rels(entries: list[tuple[str, str, str]]) -> str:
    body = "".join(f'<Relationship Id="{rid}" Type="{typ}" Target="{target}"/>' for rid, typ, target in entries)
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{NS_REL}">{body}</Relationships>'


def write_pptx() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    media_map: dict[Path, str] = {}
    media_files: list[Path] = []
    for slide in SLIDES:
        for img in slide.get("images", []):
            if img.exists() and img not in media_map:
                media_files.append(img)
                media_map[img] = f"image{len(media_files)}.png"

    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as z:
        overrides = [
            '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>',
            '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>',
            '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>',
            '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>',
        ]
        for i in range(1, len(SLIDES) + 1):
            overrides.append(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>')
        z.writestr("[Content_Types].xml", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
{''.join(overrides)}
</Types>""")
        z.writestr("_rels/.rels", rels([("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "ppt/presentation.xml")]))
        pres_rels = [("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster", "slideMasters/slideMaster1.xml")]
        for i in range(1, len(SLIDES) + 1):
            pres_rels.append((f"rId{i+1}", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide", f"slides/slide{i}.xml"))
        z.writestr("ppt/_rels/presentation.xml.rels", rels(pres_rels))
        sld_ids = "".join(f'<p:sldId id="{255+i}" r:id="rId{i+1}"/>' for i in range(1, len(SLIDES) + 1))
        z.writestr("ppt/presentation.xml", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}">
<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
<p:sldIdLst>{sld_ids}</p:sldIdLst>
<p:sldSz cx="{int(SLIDE_W)}" cy="{int(SLIDE_H)}" type="screen16x9"/>
<p:notesSz cx="6858000" cy="9144000"/>
<p:defaultTextStyle/>
</p:presentation>""")
        z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", rels([
            ("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout", "../slideLayouts/slideLayout1.xml"),
            ("rId2", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme", "../theme/theme1.xml"),
        ]))
        z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", rels([
            ("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster", "../slideMasters/slideMaster1.xml")
        ]))
        z.writestr("ppt/slideMasters/slideMaster1.xml", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}">
<p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
<p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles>
</p:sldMaster>""")
        z.writestr("ppt/slideLayouts/slideLayout1.xml", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}" type="blank" preserve="1"><p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>""")
        z.writestr("ppt/theme/theme1.xml", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="{NS_A}" name="RF Tool Theme"><a:themeElements><a:clrScheme name="RF"><a:dk1><a:srgbClr val="111827"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="374151"/></a:dk2><a:lt2><a:srgbClr val="F9FAFB"/></a:lt2><a:accent1><a:srgbClr val="2563EB"/></a:accent1><a:accent2><a:srgbClr val="059669"/></a:accent2><a:accent3><a:srgbClr val="D97706"/></a:accent3><a:accent4><a:srgbClr val="7C3AED"/></a:accent4><a:accent5><a:srgbClr val="DC2626"/></a:accent5><a:accent6><a:srgbClr val="0891B2"/></a:accent6><a:hlink><a:srgbClr val="2563EB"/></a:hlink><a:folHlink><a:srgbClr val="7C3AED"/></a:folHlink></a:clrScheme><a:fontScheme name="Arial"><a:majorFont><a:latin typeface="Arial"/></a:majorFont><a:minorFont><a:latin typeface="Arial"/></a:minorFont></a:fontScheme><a:fmtScheme name="Default"/></a:themeElements></a:theme>""")

        for img in media_files:
            z.write(img, f"ppt/media/{media_map[img]}")

        for i, slide in enumerate(SLIDES, start=1):
            image_rids = []
            rel_entries = [("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout", "../slideLayouts/slideLayout1.xml")]
            for n, img in enumerate(slide.get("images", []), start=2):
                if img.exists():
                    rid = f"rId{n}"
                    rel_entries.append((rid, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", f"../media/{media_map[img]}"))
                    image_rids.append((rid, img))
            z.writestr(f"ppt/slides/slide{i}.xml", slide_xml(i, slide, image_rids))
            z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", rels(rel_entries))

    print(OUT)
    print(f"{len(SLIDES)} slides written")
    print(f"Embedded images: {', '.join(p.name for p in media_files) if media_files else 'none'}")


if __name__ == "__main__":
    write_pptx()
