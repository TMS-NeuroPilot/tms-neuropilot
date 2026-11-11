#!/usr/bin/env python3
"""Generate the diagrams used by the documentation site.

The figures are plain SVG written by this script (no Graphviz, no Mermaid, no
network), so they can be regenerated on any machine and reviewed as text:

    python docs/site/tools/make_diagrams.py

Palette: light "paper" fills with dark ink, readable on both site themes.
"""

from __future__ import annotations

import html
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "diagrams"

INK = "#1B1F24"
MUTED = "#5A636E"
LINE = "#C6CCD4"
PAPER = "#FFFFFF"
FILL = "#F2F4F6"
ACCENT = "#B45309"
ACCENT_SOFT = "#FDF3E7"
OK = "#15803D"
OK_SOFT = "#E8F5EC"
BLUE = "#1D4ED8"
BLUE_SOFT = "#E8EEFC"
DANGER = "#B91C1C"
DANGER_SOFT = "#FDF3F3"

FONT = ("font-family=\"Inter, 'Segoe UI', 'DejaVu Sans', system-ui, sans-serif\"")


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def svg(width: int, height: int, body: str, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="{_esc(title)}">'
        f"<title>{_esc(title)}</title>"
        f"<rect width=\"{width}\" height=\"{height}\" rx=\"12\" fill=\"{PAPER}\"/>"
        f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{MUTED}"/></marker>'
        '</defs>'
        f"{body}</svg>\n")


def text(x, y, value, size=13, weight="400", fill=INK, anchor="middle"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}" {FONT}>{_esc(value)}</text>')


def multiline(x, y, lines, size=13, weight="400", fill=INK, anchor="middle",
              lh=None):
    lh = lh or size + 4
    return "".join(text(x, y + i * lh, line, size, weight, fill, anchor)
                   for i, line in enumerate(lines))


def box(x, y, w, h, lines, fill=FILL, stroke=LINE, size=13, weight="600",
        rx=10, ink=INK):
    body = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>')
    if isinstance(lines, str):
        lines = [lines]
    first = y + h / 2 - (len(lines) - 1) * (size + 4) / 2 + size / 3
    body += multiline(x + w / 2, first, lines, size, weight, ink)
    return body


def arrow(x1, y1, x2, y2, dashed=False, color=MUTED, width=1.6, curve=None):
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    if curve:
        path = f"M {x1} {y1} Q {curve[0]} {curve[1]} {x2} {y2}"
    else:
        path = f"M {x1} {y1} L {x2} {y2}"
    return (f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{width}"'
            f'{dash} marker-end="url(#arrow)"/>')


def label(x, y, value, size=11, fill=MUTED, anchor="middle"):
    return text(x, y, value, size, "500", fill, anchor)


def note(x, y, value, size=12, fill=MUTED, anchor="middle"):
    return text(x, y, value, size, "400", fill, anchor)


# ── figures ───────────────────────────────────────────────────────────

def architecture():
    b = []
    b.append(multiline(480, 30, ["Four processes, one relay"],
                       17, "700"))
    # relay hub
    b.append(box(380, 175, 200, 92, ["Relay", "Socket.IO :5000",
                                     "from_*  →  to_*"],
                 ACCENT_SOFT, ACCENT, 14))
    # controller
    b.append(box(40, 165, 210, 112, ["Controller", "PyQt5 + asyncio",
                                     "state machine · analysis",
                                     "online FEM"], BLUE_SOFT, BLUE, 14))
    # nav
    b.append(box(700, 70, 220, 84, ["Neuronavigation", "InVesalius  /  sim_nav"],
                 OK_SOFT, OK, 13))
    # robot
    b.append(box(700, 190, 220, 84, ["Robot", "tms-robot-control  /  sim_robot"],
                 OK_SOFT, OK, 13))
    # devices
    b.append(box(700, 310, 220, 62, ["Stimulator (serial · TTL)"],
                 FILL, LINE, 12, "500"))
    b.append(box(700, 386, 220, 62, ["EMG computer (SMB)"],
                 FILL, LINE, 12, "500"))

    b.append(arrow(250, 210, 378, 210))
    b.append(arrow(378, 236, 250, 236))
    b.append(arrow(580, 200, 698, 118))
    b.append(arrow(698, 138, 580, 220))
    b.append(arrow(580, 240, 698, 232))
    b.append(arrow(698, 252, 580, 252))
    b.append(arrow(810, 274, 810, 308))
    b.append(arrow(810, 372, 810, 384, dashed=True))
    b.append(label(330, 200, "topics"))
    b.append(label(330, 254, "health"))
    b.append(label(640, 130, "markers"))
    b.append(label(640, 222, "targets"))
    b.append(note(480, 440, "Dashed: direct device links on the control PC. "
                            "Everything else goes through the relay."))
    return svg(960, 470, "".join(b), "NeuroPilot architecture")


def mapping_loop():
    steps = ["INIT", "SEND\nMARKER", "START\nTRACKING", "WAIT FOR\nTARGET",
             "FIRE\nSTIM", "COLLECT\nDATA", "ANALYSE", "COMPLETE"]
    b = [multiline(480, 30, ["One pulse = one pass through the loop"], 17, "700")]
    x, y, w, h, gap = 24, 70, 104, 70, 15
    centres = []
    for i, step in enumerate(steps):
        fill, stroke = (ACCENT_SOFT, ACCENT) if step == "COMPLETE" else (FILL, LINE)
        b.append(box(x + i * (w + gap), y, w, h, step.split("\n"), fill, stroke, 12))
        centres.append((x + i * (w + gap) + w / 2, y + h / 2))
        if i:
            b.append(arrow(centres[i - 1][0] + w / 2 + 2, y + h / 2,
                           centres[i][0] - w / 2 - 2, y + h / 2))
    last = centres[-1][0]
    b.append(arrow(last, y, last, y - 22))
    b.append(multiline(480, y - 36, ["next target / next repetition"], 11, "500", MUTED))
    # skip
    b.append(arrow(centres[2][0], y + h, centres[2][0], y + h + 34, dashed=True))
    b.append(arrow(centres[2][0], y + h + 38, last, y + h + 38, dashed=True))
    b.append(label(470, y + h + 58, "SKIP / Next  →  COMPLETE (abandon this target)"))
    # gates
    b.append(note(480, y + h + 92,
                  "WAIT FOR TARGET needs coil-at-target + force + minimum interval."))
    return svg(960, 250, "".join(b), "The mapping loop")


def subject_pipeline():
    b = [multiline(480, 30, ["From MRI to a session"], 17, "700")]
    # row 1
    b.append(box(30, 70, 170, 62, ["T1 / T2 MRI"], FILL, LINE, 13))
    b.append(box(240, 70, 190, 62, ["charm (SimNIBS)", "m2m_<subj>"], FILL, LINE, 12))
    b.append(box(470, 70, 180, 62, ["<subj>.msh", "head mesh"], OK_SOFT, OK, 12))
    b.append(box(690, 70, 240, 62, ["ROI surface", "geo.hdf5 (midlayer)"], OK_SOFT, OK, 12))
    b.append(arrow(200, 101, 238, 101))
    b.append(arrow(430, 101, 468, 101))
    b.append(arrow(650, 101, 688, 101))
    # row 2
    b.append(box(30, 180, 190, 62, ["TMSoptimize", "coil placements"], FILL, LINE, 12))
    b.append(box(260, 180, 200, 62, ["02_…efield_library", "FEM per placement"],
                 FILL, LINE, 11))
    b.append(box(500, 180, 180, 62, ["e.hdf5", "E_mag (n, elements)"], ACCENT_SOFT, ACCENT, 12))
    b.append(box(720, 180, 210, 62, ["03_…sequences", "target order .txt"], FILL, LINE, 11))
    b.append(arrow(220, 211, 258, 211))
    b.append(arrow(460, 211, 498, 211))
    b.append(arrow(680, 211, 718, 211))
    # row 3
    b.append(box(160, 300, 200, 62, ["coil model .ccd"], FILL, LINE, 12))
    b.append(box(400, 300, 200, 62, ["EMG channel sources", "sources.yaml"], FILL, LINE, 12))
    b.append(box(640, 300, 250, 70, ["Project file", "paths + defaults + efield_mode"],
                 BLUE_SOFT, BLUE, 12))
    b.append(arrow(260, 331, 398, 331))
    b.append(arrow(500, 331, 638, 331))
    b.append(arrow(590, 242, 700, 298))
    b.append(arrow(590, 132, 700, 298, dashed=True))
    b.append(note(480, 420, "The online E-field mode replaces e.hdf5: the same mesh, "
                            "ROI and coil model are enough."))
    return svg(960, 440, "".join(b), "Subject data pipeline")


def run_modes():
    cols = [
        ("Simulation", "neuropilot sim", [
            "relay        sim_relay", "navigation   sim_nav",
            "robot        sim_robot", "stimulator   virtual",
            "EMG          virtual"], OK_SOFT, OK),
        ("Real", "neuropilot real", [
            "relay        production", "navigation   InVesalius",
            "robot        Omron", "stimulator   MagVenture",
            "EMG          CED 1401"], BLUE_SOFT, BLUE),
        ("Manual", "neuropilot manual", [
            "relay        production", "navigation   InVesalius",
            "robot        — operator —", "stimulator   MagVenture",
            "EMG          CED 1401"], ACCENT_SOFT, ACCENT),
    ]
    b = [multiline(480, 30, ["Three run modes, one controller"], 17, "700")]
    for i, (title, command, lines, fill, stroke) in enumerate(cols):
        x = 30 + i * 305
        b.append(box(x, 62, 280, 44, [title], fill, stroke, 15))
        b.append(note(x + 140, 126, command, 12))
        b.append(box(x, 140, 280, 150, [], PAPER, stroke, 12))
        for j, line in enumerate(lines):
            b.append(text(x + 18, 168 + j * 24, line, 12, "400", INK, "start"))
    b.append(note(480, 330, "The controller, the relay topics, the loop and the "
                            "analysis are identical in all three."))
    return svg(960, 360, "".join(b), "Run modes")


def efield_modes():
    b = [multiline(480, 30, ["Two sources, one per-pulse row"], 17, "700")]
    # lane 1
    b.append(box(30, 70, 170, 60, ["E-field library", "E_mag row"], ACCENT_SOFT, ACCENT, 12))
    b.append(arrow(200, 100, 268, 100))
    b.append(box(270, 70, 190, 60, ["row of planned", "placement"], FILL, LINE, 12))
    b.append(label(150, 148, "precomputed mode"))
    # lane 2
    b.append(box(30, 200, 170, 60, ["realised pose", "from tracking"], FILL, LINE, 12))
    b.append(arrow(200, 230, 268, 230))
    b.append(box(270, 200, 190, 60, ["OnlineFEMManager", "solve (≈ 1 min warm-up)"],
                 BLUE_SOFT, BLUE, 11))
    b.append(label(150, 278, "online mode"))
    # merge
    b.append(arrow(460, 100, 560, 160))
    b.append(arrow(460, 230, 560, 170))
    b.append(box(562, 130, 160, 70, ["pulse row", "(n_elements,)"], OK_SOFT, OK, 12))
    b.append(arrow(722, 165, 790, 165))
    b.append(box(792, 130, 140, 70, ["regression", "MEP ~ f(E)"], ACCENT_SOFT, ACCENT, 12))
    b.append(note(480, 340, "Each pulse stores the field it was stimulated with, so "
                            "the mode can change mid-run."))
    b.append(note(480, 360, "Rows without a field are dropped and the MEP history "
                            "is re-indexed with them."))
    return svg(960, 390, "".join(b), "E-field modes")


def state_machine():
    b = [multiline(480, 28, ["The controller state machine"], 17, "700")]
    nodes = {
        "INIT": (60, 70), "SEND_MARKER": (250, 70), "START_TRACKING": (440, 70),
        "WAIT": (630, 70), "FIRE": (820, 70),
        "COLLECT": (820, 220), "ANALYSE": (630, 220), "COMPLETE": (440, 220),
    }
    w, h = 160, 56
    fills = {"COMPLETE": (OK_SOFT, OK), "WAIT": (ACCENT_SOFT, ACCENT)}
    for name, (x, y) in nodes.items():
        fill, stroke = fills.get(name, (FILL, LINE))
        label_text = {"WAIT": "WAIT_FOR_TARGET"}.get(name, name)
        b.append(box(x, y, w, h, [label_text], fill, stroke, 12))
    b.append(arrow(220, 98, 248, 98))
    b.append(arrow(410, 98, 438, 98))
    b.append(arrow(600, 98, 628, 98))
    b.append(arrow(790, 98, 818, 98))
    b.append(arrow(900, 126, 900, 218))
    b.append(arrow(818, 248, 792, 248))
    b.append(arrow(628, 248, 602, 248))
    b.append(arrow(438, 248, 330, 130, dashed=True))
    b.append(label(360, 190, "next target"))
    b.append(label(905, 175, "fire", 11))
    # escape
    b.append(arrow(710, 70, 520, 216, dashed=True, color=DANGER))
    b.append(text(640, 175, "SKIP / Next", 11, "600", DANGER))
    b.append(note(480, 330, "Finish, Skip and Next work even when a system is in "
                            "error; the health gate only blocks the work steps."))
    return svg(960, 360, "".join(b), "Controller state machine")


def config_precedence():
    layers = [
        ("Shell environment", "one-off overrides", DANGER_SOFT, DANGER),
        (".env  (repository root)", "bootstrap + pins any key", ACCENT_SOFT, ACCENT),
        ("~/.neuropilot/lab.yaml", "hardware, edited in Config › Lab", BLUE_SOFT, BLUE),
        ("Built-in defaults", "lab_profile.DEFAULTS", FILL, LINE),
    ]
    b = [multiline(480, 30, ["Which value wins"], 17, "700")]
    for i, (title, sub, fill, stroke) in enumerate(layers):
        y = 62 + i * 70
        b.append(box(90, y, 380, 56, [title, sub], fill, stroke, 13))
        if i:
            b.append(arrow(280, y - 12, 280, y - 2))
    b.append(text(90, 350, "highest priority", 11, "600", MUTED, "start"))
    b.append(arrow(90, 330, 90, 66))
    b.append(text(82, 200, "precedence", 11, "600", MUTED, "middle")
             .replace('text-anchor="middle"', 'text-anchor="middle" transform="rotate(-90 82 200)"'))
    # session data
    b.append(box(560, 78, 330, 56, ["Study profile", "protocol defaults"], PAPER, LINE, 13))
    b.append(box(560, 154, 330, 56, ["Project file", "one subject"], PAPER, LINE, 13))
    b.append(arrow(892, 106, 940, 106))
    b.append(arrow(892, 182, 940, 182))
    b.append(box(560, 250, 330, 62, ["Live session controls"], OK_SOFT, OK, 13))
    b.append(arrow(725, 210, 725, 248))
    b.append(note(725, 336, "Applied by the GUI, not an override layer."))
    return svg(960, 360, "".join(b), "Configuration precedence")


FIGURES = {
    "architecture": architecture,
    "mapping-loop": mapping_loop,
    "subject-pipeline": subject_pipeline,
    "run-modes": run_modes,
    "efield-modes": efield_modes,
    "state-machine": state_machine,
    "config-precedence": config_precedence,
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in FIGURES.items():
        path = OUT / f"{name}.svg"
        path.write_text(build(), encoding="utf-8")
        print(f"wrote {path.relative_to(OUT.parents[2])}")


if __name__ == "__main__":
    main()
