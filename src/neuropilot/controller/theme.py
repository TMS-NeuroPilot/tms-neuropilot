"""Colour themes for the Workstation UI.

One Qt style sheet is generated from a token table, together with the few
colours the code sets directly (status text, LEDs, mode badge, chart and 3D
backgrounds).  Every palette defines the same keys, so adding a theme is one
dict; ``build_stylesheet`` substitutes the tokens without touching QSS braces
(``%(token)s`` placeholders).
"""

import re

# Human-readable order and meaning -- also what the tests walk.
TOKENS = (
    "ink", "muted", "soft", "mono",
    "canvas", "card", "line", "edge", "edge_hover", "hover",
    "accent", "accent_dark", "accent_soft", "accent_disabled", "on_accent",
    "disabled_bg", "disabled_edge", "disabled_ink",
    "ok", "ok_soft", "warn", "danger", "danger_soft", "danger_edge",
    "bed", "bed_ink", "bed_muted", "bed_sel",
    "scroll", "scroll_hover", "led_off", "grid",
    "series",
)

DEFAULT_THEME = "Workstation Light"

THEMES = {
    # The incumbent design, with two accessibility corrections: the accent is
    # deepened so white text on it reaches 4.5:1, and the "OK" green is the
    # darker shade that survives as *text* (the LED fill uses the same hue).
    "Workstation Light": {
        "ink": "#1B1F24", "muted": "#5A636E", "soft": "#3C444D", "mono": "#38434E",
        "canvas": "#F4F5F7", "card": "#FFFFFF", "line": "#E2E5E9",
        "edge": "#D9DDE3", "edge_hover": "#C6CCD4", "hover": "#EEF0F2",
        "accent": "#B45309", "accent_dark": "#92400E", "accent_soft": "#FDF3E7",
        "accent_disabled": "#E3C6A2", "on_accent": "#FFFFFF",
        "disabled_bg": "#F1F3F5", "disabled_edge": "#E7EAEE", "disabled_ink": "#A9B4BE",
        "ok": "#15803D", "ok_soft": "#E8F5EC", "warn": "#A16207",
        "danger": "#B91C1C", "danger_soft": "#FDF3F3", "danger_edge": "#EBC4C4",
        "bed": "#12151A", "bed_ink": "#C9D4DE", "bed_muted": "#7C8794",
        "bed_sel": "#2A333B",
        "scroll": "#C6CCD4", "scroll_hover": "#AEB6C0",
        "led_off": "#C9CFD6", "grid": "#E4E7EB",
        "series": ["#1D4ED8", "#C2410C", "#15803D", "#7E22CE", "#0F766E", "#BE185D"],
    },
    # Warm ivory paper, terracotta primary: lower glare in a bright room and
    # figures that read well when pasted into a manuscript.
    "Lab Paper": {
        "ink": "#221C14", "muted": "#6B6154", "soft": "#4A4238", "mono": "#3F382E",
        "canvas": "#F2EEE4", "card": "#FFFCF6", "line": "#E7E0D2",
        "edge": "#DCD4C4", "edge_hover": "#C8BFAE", "hover": "#F5F0E6",
        "accent": "#A64B08", "accent_dark": "#853B06", "accent_soft": "#FCF2E4",
        "accent_disabled": "#DFC0A3", "on_accent": "#FFFFFF",
        "disabled_bg": "#EFE9DC", "disabled_edge": "#E2DACA", "disabled_ink": "#A99F8D",
        "ok": "#146B33", "ok_soft": "#E6F1E6", "warn": "#8A5A06",
        "danger": "#A81F1C", "danger_soft": "#FBF0EC", "danger_edge": "#E3C0B4",
        "bed": "#14100C", "bed_ink": "#D6CBB8", "bed_muted": "#93876F",
        "bed_sel": "#332A20",
        "scroll": "#C8BFAE", "scroll_hover": "#B2A897",
        "led_off": "#CFC8BB", "grid": "#E9E2D4",
        "series": ["#1D4ED8", "#C2410C", "#15803D", "#7E22CE", "#0F766E", "#BE185D"],
    },
    # Cool slate with a deep instrumentation blue: amber stays free to mean
    # "warming up", so chrome and status never collide.
    "Instrument Blue": {
        "ink": "#14202C", "muted": "#5A6673", "soft": "#33404E", "mono": "#2F4354",
        "canvas": "#EDF1F6", "card": "#FFFFFF", "line": "#E1E7EF",
        "edge": "#D6DEE8", "edge_hover": "#C0CBD9", "hover": "#E7EDF4",
        "accent": "#0F6FA8", "accent_dark": "#0B547F", "accent_soft": "#EAF3F9",
        "accent_disabled": "#A7C7DA", "on_accent": "#FFFFFF",
        "disabled_bg": "#EFF2F6", "disabled_edge": "#E3E9F0", "disabled_ink": "#A5AFBA",
        "ok": "#15803D", "ok_soft": "#E7F3EA", "warn": "#A16207",
        "danger": "#B91C1C", "danger_soft": "#FDF2F2", "danger_edge": "#EDC3C3",
        "bed": "#0D1720", "bed_ink": "#C3D3E0", "bed_muted": "#7A8B9B",
        "bed_sel": "#26343F",
        "scroll": "#C0CBD9", "scroll_hover": "#A7B3C3",
        "led_off": "#C5CDD8", "grid": "#E1E7EF",
        "series": ["#1D4ED8", "#C2410C", "#15803D", "#7E22CE", "#0F766E", "#BE185D"],
    },
    # Neutral two-level charcoal for long sessions: no hue in the chrome, so
    # the log bed, the camera view and the six series colours keep their
    # signal.  Borders are lighter than the cards, as a dark theme needs.
    "Graphite": {
        "ink": "#DFE3E7", "muted": "#98A0A8", "soft": "#C2C8CE", "mono": "#9FB6C4",
        "canvas": "#17191C", "card": "#1F2226", "line": "#2E3237",
        "edge": "#3B4046", "edge_hover": "#51575E", "hover": "#282C31",
        "accent": "#F2A93F", "accent_dark": "#D98B2B", "accent_soft": "#2B2419",
        "accent_disabled": "#6E5A3C", "on_accent": "#17191C",
        "disabled_bg": "#23272B", "disabled_edge": "#343A41", "disabled_ink": "#6B7278",
        "ok": "#4ADE80", "ok_soft": "#1B2A20", "warn": "#EFC75E",
        "danger": "#F87171", "danger_soft": "#2A1A1A", "danger_edge": "#5A3232",
        "bed": "#0E1013", "bed_ink": "#C6CFD8", "bed_muted": "#8894A0",
        "bed_sel": "#2A3440",
        "scroll": "#3E444A", "scroll_hover": "#565D64",
        "led_off": "#3C4247", "grid": "#2A2F34",
        "series": ["#58A6FF", "#F5A65B", "#4ADE80", "#C58BFF", "#43D9C8", "#FF8FA3"],
    },
    # Blue-black for a dark room where the neuronavigation screen is the
    # reference: the canvas sits below that screen so the workstation recedes,
    # and the cool accent keeps amber/green/red unambiguous.
    "Midnight": {
        "ink": "#DFE6EE", "muted": "#93A3B5", "soft": "#BCC9D6", "mono": "#8FB4C9",
        "canvas": "#0F1620", "card": "#17202B", "line": "#26303C",
        "edge": "#303C4A", "edge_hover": "#445466", "hover": "#1E2834",
        "accent": "#35C5E3", "accent_dark": "#22A5C4", "accent_soft": "#122A33",
        "accent_disabled": "#35606E", "on_accent": "#0B131C",
        "disabled_bg": "#1B242E", "disabled_edge": "#2B3542", "disabled_ink": "#5F6E7C",
        "ok": "#4ADE80", "ok_soft": "#14251C", "warn": "#F5B335",
        "danger": "#FF7A70", "danger_soft": "#2B1A20", "danger_edge": "#5C3540",
        "bed": "#080E15", "bed_ink": "#CAD8E6", "bed_muted": "#8496A8",
        "bed_sel": "#22303E",
        "scroll": "#313C4A", "scroll_hover": "#48566A",
        "led_off": "#38475A", "grid": "#232E3A",
        "series": ["#58A6FF", "#F5A65B", "#4ADE80", "#C58BFF", "#43D9C8", "#FF8FA3"],
    },
}

_TOKEN_RE = re.compile(r"%\((\w+)\)s")

# Appended by the window: the generated checkbox/spin-box icons plus the
# E-field hint tones (the icon paths are filled in at runtime).
_ICONS_QSS = r"""
QCheckBox::indicator:checked { image: url(%(check)s); }
QSpinBox { padding-right: 20px; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right;
    width: 16px; border-left: 1px solid %(disabled_edge)s; border-bottom: 1px solid %(disabled_edge)s;
    border-top-right-radius: 4px; background: %(card)s; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right;
    width: 16px; border-left: 1px solid %(disabled_edge)s;
    border-bottom-right-radius: 4px; background: %(card)s; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: %(accent_soft)s; }
QSpinBox::up-arrow { image: url(%(up)s); width: 8px; height: 5px; }
QSpinBox::down-arrow { image: url(%(down)s); width: 8px; height: 5px; }
QLabel#efield_hint[tone="busy"] { color: %(warn)s; }
QLabel#efield_hint[tone="ok"] { color: %(ok)s; }
QLabel#efield_hint[tone="error"] { color: %(danger)s; }
"""

_QSS = r"""
/* ── Workstation theme ──────────────────────────────────────────────── */
QWidget { color: %(ink)s;
          font-family: 'Cantarell','Segoe UI','Noto Sans',sans-serif; }
QMainWindow, QWidget#centralwidget, QWidget[page="true"] { background: %(canvas)s; }
QLabel { background: transparent; }
QGroupBox { background: transparent; }

QTabWidget { background: %(card)s; }
QTabWidget::pane { border: 0; background: %(canvas)s; }
QTabBar { background: %(card)s; }
QTabBar::tab {
    background: transparent; color: %(muted)s;
    padding: 11px 18px; margin: 0; border: 0;
    border-bottom: 2px solid transparent;
    font-size: 12px; font-weight: 500;
}
QTabBar::tab:hover { color: %(ink)s; }
QTabBar::tab:selected { color: %(ink)s; font-weight: 600;
                        border-bottom: 2px solid %(accent)s; }

/* cards */
QGroupBox[card="true"] {
    background: %(card)s; border: 1px solid %(line)s; border-radius: 6px;
    margin-top: 14px; padding: 14px 14px 12px 14px;
    font-size: 11px; font-weight: 600; color: %(muted)s;
}
QGroupBox[card="true"]::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 12px; padding: 0 4px 0 4px; background: %(card)s;
}

/* text roles */
QLabel[role="cap"]     { font-size: 11px; color: %(muted)s; }
QLabel[role="value"]   { font-size: 15px; font-weight: 600; }
QLabel[role="value-xl"]{ font-size: 16px; font-weight: 600; }
QLabel[role="section"] { font-size: 11px; font-weight: 600; color: %(muted)s; }
QLabel[role="badge"]   { font-size: 11px; font-weight: 600; }
QRadioButton[role="choice"] { font-size: 12px; color: %(soft)s; spacing: 6px; }
QLabel[role="mono"]    { font-family: 'DejaVu Sans Mono','Consolas',monospace;
                         font-size: 12px; color: %(mono)s; }

/* LEDs: status on/off + color green/red (dynamic properties) */
QLabel[led="true"] { min-width: 10px; max-width: 10px; min-height: 10px;
                     max-height: 10px; border-radius: 3px; background: %(led_off)s; }
QLabel[led="true"][status="on"][color="green"] { background: %(ok)s; }
QLabel[led="true"][status="on"][color="red"]   { background: %(danger)s; }
QLabel[led="true"][status="off"]               { background: %(led_off)s; }

/* buttons */
QPushButton {
    background: %(card)s; color: %(ink)s;
    border: 1px solid %(edge)s; border-radius: 4px;
    padding: 6px 14px; min-height: 20px;
    font-size: 13px; font-weight: 500;
}
QPushButton:hover   { background: %(hover)s; border-color: %(scroll)s; }
QPushButton:pressed { background: %(line)s; }
QPushButton[role="primary"] { background: %(accent)s; color: %(on_accent)s;
                              border: 1px solid %(accent)s; font-weight: 600;
                              min-height: 28px; padding: 9px 26px; }
QPushButton[role="primary"]:hover { background: %(accent_dark)s; border-color: %(accent_dark)s; }
QPushButton[role="danger"]  { background: %(card)s; color: %(danger)s;
                              border: 1px solid %(danger_edge)s;
                              min-height: 24px; padding: 7px 18px; }
QPushButton[role="danger"]:hover { background: %(danger_soft)s; }
QPushButton[role="transport"] { min-height: 24px; padding: 7px 18px; }
QPushButton[role="compact"] { min-height: 10px; padding: 2px 14px; font-size: 13px; }
QPushButton[role="recover"] { min-height: 16px; padding: 3px 10px; font-size: 11px; }
QPushButton:disabled { background: %(disabled_bg)s; color: %(disabled_ink)s; border-color: %(disabled_edge)s; }
QPushButton[role="primary"]:disabled { background: %(accent_disabled)s; color: %(on_accent)s;
                                       border-color: %(accent_disabled)s; }

QToolButton[role="browse"] {
    background: %(card)s; border: 1px solid %(edge)s; border-radius: 4px;
    padding: 0; min-width: 28px; max-width: 28px; min-height: 28px;
    color: %(muted)s; font-size: 13px; font-weight: 600;
}
QToolButton[role="browse"]:hover { background: %(hover)s; color: %(ink)s; }

/* inputs */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: %(card)s; border: 1px solid %(edge)s; border-radius: 4px;
    padding: 4px 8px; min-height: 20px; font-size: 13px; color: %(ink)s;
    selection-background-color: %(accent)s; selection-color: %(on_accent)s;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 2px solid %(accent)s; padding: 3px 7px;
}
QLineEdit:disabled { background: %(disabled_bg)s; color: %(disabled_ink)s; }
QLineEdit[role="path"] { font-family: 'DejaVu Sans Mono','Consolas',monospace;
                         font-size: 12px; color: %(mono)s; }
QLineEdit[role="name"] { border: 1px solid %(edge)s; background: %(card)s;
                         border-radius: 4px; font-size: 15px; font-weight: 600;
                         color: %(ink)s; padding: 7px 8px; min-height: 24px; }
QLineEdit[role="name"]:focus { border: 2px solid %(accent)s; padding: 5px 7px; }
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 16px; border: 0; background: transparent; }
QComboBox::drop-down { border: 0; width: 22px; }
QComboBox:disabled { color: %(disabled_ink)s; background: %(canvas)s; border-color: %(disabled_edge)s; }
QComboBox QAbstractItemView { background: %(card)s; border: 1px solid %(edge)s;
    padding: 4px; selection-background-color: %(hover)s; selection-color: %(ink)s;
    outline: none; }
QComboBox QAbstractItemView::item { min-height: 24px; padding: 2px 6px; }

/* tables, info boxes and menus (the pages use them for results/readouts) */
QTableWidget, QTableView, QListWidget, QTreeWidget {
    background: %(card)s; color: %(ink)s; gridline-color: %(line)s;
    border: 1px solid %(line)s; border-radius: 6px;
    selection-background-color: %(accent_soft)s; selection-color: %(ink)s;
}
QTableWidget::item, QTableView::item { padding: 4px 6px; }
QHeaderView::section {
    background: %(hover)s; color: %(muted)s; border: 0;
    border-bottom: 1px solid %(line)s; padding: 4px 6px; font-size: 11px;
}
QTableCornerButton::section { background: %(hover)s; border: 0; }
QPlainTextEdit, QTextEdit {
    background: %(card)s; color: %(ink)s; border: 1px solid %(line)s;
    border-radius: 6px; padding: 6px;
    selection-background-color: %(accent)s; selection-color: %(on_accent)s;
}
QCheckBox, QRadioButton { color: %(ink)s; }
QToolTip { background: %(card)s; color: %(ink)s;
           border: 1px solid %(edge)s; padding: 4px; }
QMenu { background: %(card)s; color: %(ink)s; border: 1px solid %(edge)s; }
QMenu::item { padding: 5px 18px; }
QMenu::item:selected { background: %(hover)s; }
QDialog, QMessageBox { background: %(canvas)s; color: %(ink)s; }

/* sliders */
QSlider::groove:horizontal { height: 4px; background: %(line)s; border-radius: 2px; }
QSlider::sub-page:horizontal { background: %(accent)s; border-radius: 2px; }
QSlider::handle:horizontal { background: %(card)s; border: 2px solid %(accent)s;
                             border-radius: 7px; width: 14px; margin: -5px 0; }
QSlider::handle:horizontal:hover { background: %(accent_soft)s; }
QSlider::handle:horizontal:disabled { border-color: %(scroll)s; }

/* toggles */
QCheckBox::indicator, QRadioButton::indicator {
    width: 14px; height: 14px; border: 1px solid %(scroll)s; background: %(card)s; }
QCheckBox::indicator { border-radius: 3px; }
QRadioButton::indicator { border-radius: 7px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: %(accent)s; border-color: %(accent)s; }
QCheckBox:disabled, QRadioButton:disabled { color: %(disabled_ink)s; }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {
    background: %(disabled_bg)s; border-color: %(disabled_edge)s; }

/* instrument beds (log, robot view) */
QPlainTextEdit[role="log"] {
    background: %(bed)s; color: %(bed_ink)s; border: none; border-radius: 8px;
    font-family: 'DejaVu Sans Mono','Consolas',monospace; font-size: 12px;
    padding: 10px; selection-background-color: %(bed_sel)s;
}
QLabel[role="bed"] { background: %(bed)s; border-radius: 8px; color: %(bed_muted)s; }

/* scrollbars */
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: %(scroll)s; border-radius: 5px;
                              min-height: 28px; }
QScrollBar::handle:vertical:hover { background: %(scroll_hover)s; }
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page { height: 0; width: 0;
                                             background: none; border: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: %(scroll)s; border-radius: 5px;
                                min-width: 28px; }

QSplitter::handle { background: %(line)s; }
"""


def names():
    """Theme names in menu order."""
    return list(THEMES)


def tokens(name=None):
    """Token table for a theme (falls back to the default)."""
    return THEMES.get(name) or THEMES[DEFAULT_THEME]


def build_stylesheet(name=None, icons=None):
    """The complete Qt style sheet for a theme.

    ``icons`` maps ``check``/``up``/``down`` to the generated PNG paths; the
    window passes them, tests and headless callers can omit them.
    """
    table = tokens(name)
    missing = [key for key in TOKENS if key not in table]
    if missing:
        raise KeyError(f"theme {name!r} is missing tokens: {missing}")

    def fill(template):
        def replace(match):
            key = match.group(1)
            if key in table:
                return str(table[key])
            if key in ("check", "up", "down"):
                return match.group(0)          # filled in by the icons pass
            raise KeyError(f"theme {name!r}: unknown token {key!r}")
        return _TOKEN_RE.sub(replace, template)

    sheet = fill(_QSS)
    if icons:
        sheet += fill(_ICONS_QSS) % icons
    return sheet


def luminance(colour):
    """Relative luminance (0..1) of a ``#RRGGBB`` colour."""
    rgb = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
              for c in rgb]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(foreground, background):
    """WCAG contrast ratio between two ``#RRGGBB`` colours (1..21)."""
    a, b = luminance(foreground), luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def is_dark(name=None):
    """True when the theme draws light text on a dark canvas."""
    return luminance(tokens(name)["canvas"]) < 0.4
