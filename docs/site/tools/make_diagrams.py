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
TRAIN = "#7E22CE"
TRAIN_SOFT = "#F3E8FF"

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


def arrow(x1, y1, x2, y2, dashed=False, color=MUTED, width=1.6, curve=None,
          head=True):
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    marker = ' marker-end="url(#arrow)"' if head else ""
    if curve:
        path = f"M {x1} {y1} Q {curve[0]} {curve[1]} {x2} {y2}"
    else:
        path = f"M {x1} {y1} L {x2} {y2}"
    return (f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{width}"'
            f'{dash}{marker}/>')


def label(x, y, value, size=11, fill=MUTED, anchor="middle"):
    return text(x, y, value, size, "500", fill, anchor)


def note(x, y, value, size=12, fill=MUTED, anchor="middle"):
    return text(x, y, value, size, "400", fill, anchor)


# ── figures ───────────────────────────────────────────────────────────

def architecture():
    b = []
    b.append(multiline(480, 30, ["Four processes, one relay"], 17, "700"))
    # relay hub
    b.append(box(370, 175, 210, 92, ["Relay", "Socket.IO :5000",
                                     "from_*  →  to_*"],
                 ACCENT_SOFT, ACCENT, 14))
    # controller
    b.append(box(40, 150, 220, 120, ["Controller GUI", "PyQt5 + asyncio",
                                     "state machine · analysis",
                                     "online FEM"], BLUE_SOFT, BLUE, 14))
    # nav
    b.append(box(700, 75, 220, 80, ["Neuronavigation",
                                   "InVesalius  /  sim_nav"], OK_SOFT, OK, 13))
    # robot
    b.append(box(700, 195, 220, 80, ["Robot",
                                    "tms-robot-control  /  sim_robot"], OK_SOFT, OK, 13))
    # devices (direct links, no relay)
    b.append(box(40, 330, 220, 66, ["Stimulator", "serial + TTL"],
                 FILL, LINE, 12, "500"))
    b.append(box(320, 330, 220, 66, ["EMG computer", "e.g. CED 1401 · SMB"],
                 FILL, LINE, 12, "500"))

    # relay links (solid)
    b.append(arrow(262, 195, 368, 195))
    b.append(arrow(368, 235, 262, 235))
    b.append(label(315, 185, "topics"))
    b.append(label(315, 252, "health / poses"))
    b.append(arrow(582, 190, 698, 120))
    b.append(arrow(698, 145, 582, 215))
    b.append(label(645, 120, "markers"))
    b.append(arrow(582, 235, 698, 228))
    b.append(arrow(698, 250, 582, 250))
    b.append(label(645, 215, "targets"))

    # device links (dashed): both devices sit on the control PC
    b.append(arrow(120, 272, 120, 326, dashed=True))
    b.append(label(196, 303, "serial / TTL", 11, MUTED, "start"))
    b.append(arrow(410, 328, 258, 276, dashed=True))
    b.append(label(438, 305, "SMB", 11, MUTED, "start"))

    b.append(note(480, 428, "Solid: relay topics.  Dashed: direct device links "
                            "on the control PC."))
    b.append(note(480, 448, "In simulation the relay, neuronavigation and robot "
                            "are NeuroPilot's virtual twin."))
    return svg(960, 470, "".join(b), "NeuroPilot architecture")


def mapping_loop():
    steps = ["INIT", "SEND\nMARKER", "START\nTRACKING", "WAIT FOR\nTARGET",
             "FIRE\nSTIM", "COLLECT\nDATA", "ANALYSE", "COMPLETE"]
    width, height = 1000, 250
    b = [multiline(width // 2, 24, ["One pulse = one pass through the loop"],
                   17, "700")]
    x, y, w, h, gap = 24, 70, 104, 70, 17
    centres = []
    for i, step in enumerate(steps):
        fill, stroke = (ACCENT_SOFT, ACCENT) if step == "COMPLETE" else (FILL, LINE)
        b.append(box(x + i * (w + gap), y, w, h, step.split("\n"), fill, stroke, 12))
        centres.append((x + i * (w + gap) + w / 2, y + h / 2))
        if i:
            b.append(arrow(centres[i - 1][0] + w / 2 + 2, y + h / 2,
                           centres[i][0] - w / 2 - 2, y + h / 2))
    first, last = centres[0][0], centres[-1][0]
    # loop back from COMPLETE to INIT, above the row
    loop_y = y - 18
    b.append(arrow(last, y, last, loop_y, head=False))
    b.append(arrow(last, loop_y, first, loop_y, head=False))
    b.append(arrow(first, loop_y, first, y))
    b.append(label(width / 2, loop_y - 6, "next target / next repetition"))
    # skip from START TRACKING to COMPLETE, below the row
    skip_y = y + h + 38
    b.append(arrow(centres[2][0], y + h, centres[2][0], skip_y,
                   dashed=True, head=False))
    b.append(arrow(centres[2][0], skip_y, last, skip_y, dashed=True, head=False))
    b.append(arrow(last, skip_y, last, y + h + 2, dashed=True))
    b.append(label(width / 2, skip_y + 20,
                   "SKIP / Next  →  COMPLETE (abandon this target)"))
    # gates
    b.append(note(width / 2, skip_y + 54,
                  "WAIT FOR TARGET needs coil-at-target + force + minimum interval."))
    return svg(width, height, "".join(b), "The mapping loop")


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
            "robot        your robot", "stimulator   your stimulator",
            "EMG          your EMG PC"], BLUE_SOFT, BLUE),
        ("Manual", "neuropilot manual", [
            "relay        production", "navigation   InVesalius",
            "robot        operator moves coil", "stimulator   your stimulator",
            "EMG          your EMG PC"], ACCENT_SOFT, ACCENT),
        ("Training", "neuropilot training", [
            "relay        production", "navigation   InVesalius",
            "robot        operator moves coil", "stimulator   your stimulator",
            "EMG          virtual (E-field)"], TRAIN_SOFT, TRAIN),
    ]
    b = [multiline(480, 30, ["Four run modes, one controller"], 17, "700")]
    for i, (title, command, lines, fill, stroke) in enumerate(cols):
        x = 30 + (i % 2) * 460
        y = 60 + (i // 2) * 240
        b.append(box(x, y, 440, 40, [title], fill, stroke, 15))
        b.append(note(x + 220, y + 60, command, 12))
        b.append(box(x, y + 72, 440, 150, [], PAPER, stroke, 12))
        for j, line in enumerate(lines):
            b.append(text(x + 18, y + 100 + j * 24, line, 12, "400", INK, "start"))
    b.append(note(480, 550, "The controller, the relay topics, the loop and the "
                            "analysis are identical in all four."))
    return svg(960, 580, "".join(b), "Run modes")


def efield_modes():
    b = [multiline(480, 30, ["Three sources, one per-pulse row"], 17, "700")]
    # lane 1: precomputed
    b.append(box(30, 60, 170, 60, ["E-field library", "E_mag row"], ACCENT_SOFT, ACCENT, 12))
    b.append(arrow(200, 90, 268, 90))
    b.append(box(270, 60, 190, 60, ["row of planned", "placement"], FILL, LINE, 12))
    b.append(label(150, 138, "precomputed mode"))
    # lane 2: online
    b.append(box(30, 170, 170, 60, ["realised pose", "from tracking"], FILL, LINE, 12))
    b.append(arrow(200, 200, 268, 200))
    b.append(box(270, 170, 190, 60, ["OnlineFEMManager", "solve (≈ 1 min warm-up)"],
                 BLUE_SOFT, BLUE, 11))
    b.append(label(150, 248, "online mode"))
    # lane 3: interpolated
    b.append(box(30, 280, 170, 60, ["dense library", "E_mag + roi_hash"], OK_SOFT, OK, 12))
    b.append(arrow(200, 310, 268, 310))
    b.append(box(270, 280, 190, 60, ["EFieldSurrogate", "pose interpolation"],
                 ACCENT_SOFT, ACCENT, 11))
    b.append(label(150, 358, "interpolated mode"))
    # merge
    b.append(arrow(460, 90, 560, 190))
    b.append(arrow(460, 200, 560, 200))
    b.append(arrow(460, 310, 560, 210))
    b.append(box(562, 165, 160, 70, ["pulse row", "(n_elements,)"], OK_SOFT, OK, 12))
    b.append(arrow(722, 200, 790, 200))
    b.append(box(792, 165, 140, 70, ["regression", "MEP ~ f(E)"], ACCENT_SOFT, ACCENT, 12))
    b.append(note(480, 410, "Each pulse stores the field it was stimulated with, so "
                            "the mode can change mid-run."))
    b.append(note(480, 430, "Rows without a field are dropped and the MEP history "
                            "is re-indexed with them."))
    return svg(960, 470, "".join(b), "E-field modes")


def state_machine():
    b = [multiline(520, 28, ["The controller state machine"], 17, "700")]
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
    # Escape hatch: leave WAIT_FOR_TARGET from its *bottom* edge and complete
    # the target, instead of cutting across the box from the top.
    b.append(arrow(710, 126, 520, 218, dashed=True, color=DANGER))
    b.append(text(660, 150, "SKIP / Next", 11, "600", DANGER))
    b.append(note(520, 330, "Finish, Skip and Next work even when a system is in "
                            "error; the health gate only blocks the work steps."))
    return svg(1040, 360, "".join(b), "Controller state machine")


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
        b.append(box(100, y, 370, 56, [title, sub], fill, stroke, 13))

    # The precedence arrow sits clear of the boxes, not on their edge.
    b.append(arrow(44, 330, 44, 66))
    b.append(text(44, 350, "highest priority", 11, "600", MUTED, "start"))
    b.append(text(24, 200, "precedence", 11, "600", MUTED, "middle")
             .replace('text-anchor="middle"',
                      'text-anchor="middle" transform="rotate(-90 24 200)"'))

    # Session data: study and project feed the live controls.  A bus on the
    # right merges both into one arrow, instead of two arrows to nowhere.
    b.append(box(560, 78, 330, 56, ["Study profile", "protocol defaults"], PAPER, LINE, 13))
    b.append(box(560, 154, 330, 56, ["Project file", "one subject"], PAPER, LINE, 13))
    b.append(box(560, 250, 330, 62, ["Live session controls"], OK_SOFT, OK, 13))
    b.append(arrow(890, 106, 920, 106, head=False))
    b.append(arrow(890, 182, 920, 182, head=False))
    b.append(arrow(920, 106, 920, 281, head=False))
    b.append(arrow(920, 281, 892, 281))
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
