from PyQt5 import QtCore, QtGui, QtWidgets, uic
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt
import math
import re
import sys
import os
import queue
import threading
import time
import traceback
from .systems.system import SystemStatus
from .theme import (DEFAULT_THEME, THEMES, build_stylesheet,
                    install_tall_combo_rows,
                    tokens as theme_tokens)
from .meshwidget import read_mesh_file
from .pipeline_controller import (
    read_e_matrix_file, read_emg_config_elements,
    read_simnibs_targets_data, validate_simnibs_targets_file,
)
import pynibs
import yaml
import numpy as np

def resource_path(relative_path: str) -> str:
    """
    Get the absolute path to a resource.
    Works in dev and when bundled with PyInstaller.
    """
    if hasattr(sys, "_MEIPASS"):  # PyInstaller temp folder
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))  # folder of this .py file

    return os.path.join(base_path, relative_path)


def _simnibs_coil_model(sub_dir: str, file_name: str):
    """
    Absolute path of a coil model shipped with SimNIBS, or None if SimNIBS is
    not installed in the running environment. SimNIBS is not imported here —
    the package location is resolved from its spec only.
    """
    import importlib.util
    spec = importlib.util.find_spec("simnibs")
    if spec is None or not spec.origin:
        return None
    fn = os.path.join(os.path.dirname(spec.origin), "resources", "coil_models",
                      sub_dir, file_name)
    return fn if os.path.isfile(fn) else None


class _TabCornerFrame(QtWidgets.QFrame):
    """Frame for the tab bar's top-right corner.

    QTabWidget places the corner widget bottom-aligned with its size hint
    height; reporting the tab bar's height makes the frame cover the whole
    strip, so the LEDs sit on the same white as the tabs."""

    def sizeHint(self):
        hint = super().sizeHint()
        parent = self.parentWidget()
        tab_bar = getattr(parent, "tabBar", None)
        height = tab_bar().height() if callable(tab_bar) else hint.height()
        return QtCore.QSize(hint.width(), max(hint.height(), height))


class _TopLineOverlay(QtWidgets.QWidget):
    """One-device-pixel white line over the LED corner.

    The tab bar paints a one-pixel top separator itself, but its width stops
    where the QTabWidget corner starts.  QTabWidget also keeps resetting the
    corner's y to 1 logical pixel, so a border or paint inside the corner
    lands on a different row (and is twice as thick at 200 % scaling).  This
    overlay starts at y=0 and uses a cosmetic pen, matching the tab bar's
    line exactly at every device-pixel ratio.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        pen = QtGui.QPen(QtGui.QColor("#FFFFFF"))
        pen.setWidthF(1.0)               # one logical pixel, like the tab bar
        painter.setPen(pen)
        painter.drawLine(QtCore.QPointF(0, 1.0),
                         QtCore.QPointF(self.width(), 1.0))
        painter.end()


_ICON_CACHE = {}

# The About page's copy-citation glyph: rendered once per colour into the
# user's temp folder, like _control_ui_icons below.
_COPY_ICON_CACHE = {}


def _copy_icon(check_colour="#6B7280"):
    """Render a small copy glyph (two overlapping sheets) as a PNG path."""
    cached = _COPY_ICON_CACHE.get(check_colour)
    if cached:
        return cached
    import tempfile
    folder = os.path.join(tempfile.gettempdir(), "neuropilot_ui", "copy")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"copy_{check_colour.lstrip('#').lower()}.png")
    pm = QPixmap(14, 14)
    pm.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pm)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(QtGui.QPen(QtGui.QColor(check_colour), 1.5))
    painter.setBrush(QtCore.Qt.NoBrush)
    # Back sheet (offset) and front sheet; at 14 px this reads as "copy".
    painter.drawRoundedRect(QtCore.QRectF(4.5, 1.0, 7.5, 8.5), 1.5, 1.5)
    painter.drawRoundedRect(QtCore.QRectF(2.0, 4.5, 7.5, 8.5), 1.5, 1.5)
    painter.end()
    pm.save(path, "PNG")
    _COPY_ICON_CACHE[check_colour] = path
    return path


def _control_ui_icons(check_colour="#FFFFFF"):
    """Write the small PNG assets the style sheet needs (a check tick and the
    spin-box chevrons) and return their paths. Qt style sheets cannot draw
    these glyphs, and shipping binary resources for two 14 px icons is
    overkill — they are rendered once per colour into the user's temp folder.

    ``check_colour`` is the theme's ``on_accent``: a dark theme has a bright
    accent, so a white tick would disappear on it.
    """
    import tempfile
    cached = _ICON_CACHE.get(check_colour)
    if cached:
        return cached
    tag = check_colour.lstrip("#").lower()
    folder = os.path.join(tempfile.gettempdir(), "neuropilot_ui", tag)
    os.makedirs(folder, exist_ok=True)

    def _stroke(path, size, points, color, width=2):
        pm = QPixmap(*size)
        pm.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pm)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        pen = QtGui.QPen(QtGui.QColor(color), width)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in points]))
        painter.end()
        pm.save(path, "PNG")
        return path

    icons = {
        "check": _stroke(os.path.join(folder, "check.png"), (14, 14),
                         [(3.5, 7.5), (6.0, 10.0), (10.5, 4.0)], check_colour, 2.2),
        "up": _stroke(os.path.join(folder, "up.png"), (8, 5),
                      [(1.0, 4.0), (4.0, 1.0), (7.0, 4.0)], "#B45309", 1.6),
        "down": _stroke(os.path.join(folder, "down.png"), (8, 5),
                        [(1.0, 1.0), (4.0, 4.0), (7.0, 1.0)], "#B45309", 1.6),
    }
    _ICON_CACHE[check_colour] = icons
    return icons


def _fmt_number(value, spec):
    """Format a number for a CSV cell; None/blank/unparsable becomes "".

    Placement records come from the live session *and* from loaded bundles, so
    a missing aim error or intensity must leave an empty cell instead of
    raising (or writing the string "None").
    """
    if value is None or value == "":
        return ""
    try:
        return format(float(value), spec) if spec else str(value)
    except (TypeError, ValueError):
        return ""


def _session_cache_path():
    """Per-user cache file holding the project fields between runs.

    Lives in ``~/.neuropilot`` — ``os.path.expanduser`` resolves to the
    user's profile directory on Windows as well, so the same code works on
    the lab PCs without adjustment. ``NEUROPILOT_SESSION_FILE`` lets tools
    and tests redirect it without touching the real profile.
    """
    override = os.getenv("NEUROPILOT_SESSION_FILE")
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), ".neuropilot", "last_session.yaml")


# Path-valued fields in a project YAML.  They are stored relative to the
# project file when the asset lives below it, so a cloned example project
# keeps working on another machine.
_PROJECT_PATH_KEYS = (
    "results_fn", "target_order_fn", "targets_file", "mesh_head_path",
    "mesh_RIO_path", "e_field_path", "surrogate_library_path",
    "coil_path", "emg_config_fn",
)


def _resolve_project_paths(data, base_dir):
    """Return a copy of *data* with relative project paths made absolute."""
    if not isinstance(data, dict) or not base_dir:
        return data
    result = dict(data)
    base = os.path.abspath(os.path.expanduser(str(base_dir)))
    for key in _PROJECT_PATH_KEYS:
        value = result.get(key)
        if value is None or str(value).strip() == "":
            continue
        text = os.path.expanduser(str(value))
        if not os.path.isabs(text):
            text = os.path.join(base, text)
        result[key] = os.path.normpath(os.path.abspath(text))
    return result


def _relative_project_paths(data, base_dir):
    """Return a copy of *data* with paths below *base_dir* made relative."""
    if not isinstance(data, dict) or not base_dir:
        return data
    result = dict(data)
    base = os.path.abspath(os.path.expanduser(str(base_dir)))
    for key in _PROJECT_PATH_KEYS:
        value = result.get(key)
        if value is None or str(value).strip() == "":
            continue
        path = os.path.abspath(os.path.expanduser(str(value)))
        try:
            if os.path.commonpath((path, base)) != base:
                continue
        except ValueError:
            continue
        result[key] = os.path.relpath(path, base)
    return result


def _path_signature(path):
    """Cheap change detector for a file that may be rewritten in place."""
    try:
        stat = os.stat(path)
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


class _FileLoader:
    """One daemon worker that keeps only the newest submitted job.

    Heavy file reads run here, never on the GUI thread.  The worker pushes
    finished jobs onto a queue; the window drains that queue from a QTimer
    (see ``_drain_load_results``), so no widget is touched off the GUI thread.
    If the operator changes a path while the old file is still being read,
    the pending job is replaced and the old result is ignored by its token.
    """

    def __init__(self, name, load_fn):
        self.name = name
        self._load_fn = load_fn
        self._condition = threading.Condition()
        self._job = None
        self._active_event = None
        self._stopping = False
        self._results = queue.Queue()
        self._thread = threading.Thread(
            target=self._run, name=f"neuropilot-load-{name}", daemon=True)
        self._thread.start()

    def submit(self, token, path, **meta):
        """Queue a job, replacing any job that has not started yet."""
        job = None
        if path:
            job = dict(meta)
            job.update(token=token, path=path)
        with self._condition:
            if self._active_event is not None:
                self._active_event.set()
            self._job = job
            self._condition.notify()

    def cancel(self):
        """Drop the pending job; a read already in progress still finishes."""
        with self._condition:
            self._job = None
            if self._active_event is not None:
                self._active_event.set()
            self._condition.notify()

    def stop(self):
        with self._condition:
            self._stopping = True
            self._job = None
            if self._active_event is not None:
                self._active_event.set()
            self._condition.notify()

    def poll(self):
        results = []
        while True:
            try:
                results.append(self._results.get_nowait())
            except queue.Empty:
                break
        return results

    def is_busy(self):
        with self._condition:
            return self._active_event is not None or self._job is not None

    def _run(self):
        while True:
            with self._condition:
                while self._job is None and not self._stopping:
                    self._condition.wait()
                if self._stopping:
                    return
                job = self._job
                self._job = None
                stop_event = threading.Event()
                self._active_event = stop_event
                job["stop_event"] = stop_event
            try:
                payload = self._load_fn(job["path"], job)
                result = dict(job, payload=payload, error=None, detail="")
            except Exception as e:             # noqa: BLE001 - reported in GUI
                result = dict(job, payload=None, error=str(e),
                              detail=traceback.format_exc(),
                              error_type=type(e).__name__)
            finally:
                with self._condition:
                    if self._active_event is stop_event:
                        self._active_event = None
            self._results.put(result)


class _TargetValueLabel(QtWidgets.QLabel):
    """A value label that reports text changes to the target overlay."""

    text_changed = QtCore.pyqtSignal()

    def setText(self, text):
        super().setText(text)
        self.text_changed.emit()


class MainWindow(QtWidgets.QMainWindow):
    # Background readers (mesh / coil summaries) must not touch widgets from
    # their thread; they emit this and Qt delivers it on the GUI thread.
    file_info_ready = QtCore.pyqtSignal(str, str)
    # Same for the online solver finishing its (background) initialisation.
    online_fem_ready = QtCore.pyqtSignal()
    # Same for the interpolated library finishing its (background) load.
    surrogate_library_ready = QtCore.pyqtSignal()
    # Finished R² maps from the analysis worker thread.
    scores_ready = QtCore.pyqtSignal(dict)

    def __init__(self, simulation, training=False):
        super().__init__()
        self.simulation = simulation
        self.training = training
        self._closing = False

        # ui is inside the "gui" folder
        ui_path = resource_path(os.path.join("gui", "pipeline_control.ui"))
        uic.loadUi(ui_path, self)

        self.file_info_ready.connect(self._on_file_info_ready)
        self.online_fem_ready.connect(self.update_button_states)
        self.scores_ready.connect(self.update_mesh_coloring)

        # The robot view is a QLabel that receives a pixmap every frame. Its
        # pixmap size hint would otherwise feed the label's own current height
        # back into the layout and pin the 3D view to the largest possible
        # size. Ignore that vertical hint so the layout can give the log card
        # the space below it.
        self.robot_view_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Ignored)

        # The console needs no separate caption inside its card.
        self.groupBox_stats.setTitle("Log")
        log_caption = getattr(self, "label_5", None)
        if log_caption is not None:
            self.groupBox_stats.layout().removeWidget(log_caption)
            log_caption.setParent(None)
            log_caption.deleteLater()
            self.label_5 = None

        # Enable/Fire are single-action buttons; use a compact height so the
        # 3D view ends higher and the log console gets the space.
        for button in (self.enableBtn, self.fireBtn):
            button.setProperty("role", "compact")

        # The Control page's three cards were taller than their content and
        # squeezed the log console at the bottom. Tighten their padding and
        # spacing; the extra height now goes to the console. The card padding
        # is inline so it scales with the rest of the page styles.
        for name in ("groupBox_5", "groupBox_efield", "groupBox_6"):
            card = getattr(self, name, None)
            if card is not None:
                card.setStyleSheet(
                    "QGroupBox { padding: 8px 14px 8px 14px; }")
        for name in ("stim_v", "efield_v", "robot_v", "stats_v"):
            card_layout = getattr(self, name, None)
            if card_layout is not None:
                card_layout.setSpacing(6)
        if hasattr(self, "control_left"):
            self.control_left.setSpacing(8)
            # The old spacer at the bottom of the card column would absorb
            # the height difference and leave the 3D view hanging below the
            # Robot card. Remove it so the view ends with the cards.
            for index in range(self.control_left.count() - 1, -1, -1):
                item = self.control_left.itemAt(index)
                if item is not None and item.spacerItem() is not None:
                    self.control_left.takeAt(index)
        self.finishedsteps.setMinimumHeight(120)
        self._setup_target_overlay()

        self._theme_name = DEFAULT_THEME
        self._theme = theme_tokens(DEFAULT_THEME)
        self._system_status = {}

        # Default window size: open at a comfortable fraction of the screen so
        # the pixel-based UI (fonts scale with the window in _rescale) is
        # readable on high-DPI displays. Override with NEUROPILOT_UI_SCALE.
        self._design_size = (self.width(), self.height())
        # The pages are laid out for this size and the font scaler bottoms
        # out at 1.0, so shrinking further only breaks the layout.
        # The control page's card stack needs a little more height than the
        # .ui's design box; below that the cards clip their last row.
        self.setMinimumSize(QtCore.QSize(self._design_size[0],
                                         max(self._design_size[1], 960)))
        scale_env = os.getenv("NEUROPILOT_UI_SCALE")
        scale = None
        if scale_env:
            try:
                scale = float(scale_env)
            except ValueError:
                # The Config tab invites free text here; a typo must not
                # prevent the application from starting.
                print(f"[WARN] NEUROPILOT_UI_SCALE={scale_env!r} is not a number, using auto")
        if scale is None:
            screen = QtWidgets.QApplication.primaryScreen()
            avail = screen.availableGeometry() if screen else None
            if avail is not None and avail.width() and avail.height():
                scale = min(avail.width() / self._design_size[0],
                            avail.height() / self._design_size[1], 2.0)
            else:
                scale = 1.0
        scale = max(1.0, scale)
        if abs(scale - 1.0) > 0.01:
            self.resize(round(self._design_size[0] * scale),
                        round(self._design_size[1] * scale))

        # Project tab: explain what each path field expects.
        # The third E-field source (interpolated library) is created here in
        # code: the .ui carries the two original radios and path rows, and the
        # new widgets slot into the existing layouts with the same roles.
        self.surrogate_efield_btn = QtWidgets.QRadioButton("Interpolated")
        self.surrogate_efield_btn.setObjectName("surrogate_efield_btn")
        self.surrogate_efield_btn.setProperty("role", "choice")
        self.surrogate_efield_btn.setToolTip(
            "Interpolated E-field: PCA + pose interpolation of the dense "
            "library (Grosshagauer et al. 2025), with a domain guard. Needs "
            "the library file and the ROI surface.")
        efield_layout = self.offline_efield_btn.parent().layout()
        if efield_layout is not None:
            efield_layout.insertWidget(
                efield_layout.indexOf(self.efield_hint),
                self.surrogate_efield_btn)
        self.surrogate_library_row = QtWidgets.QWidget()
        self.surrogate_library_row.setObjectName("surrogate_library_row")
        row_layout = QtWidgets.QHBoxLayout(self.surrogate_library_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        surrogate_cap = QtWidgets.QLabel("Interpolated library:")
        surrogate_cap.setProperty("role", "cap")
        self.surrogate_library_label = QtWidgets.QLineEdit()
        self.surrogate_library_label.setObjectName("surrogate_library_label")
        self.surrogate_library_label.setPlaceholderText(
            "data/<subject>/efield/e_surrogate.hdf5")
        self.surrogate_library_label.setToolTip(
            "Dense E-field library for the Interpolated mode "
            "(E_mag plus roi_hash). Checked against the ROI surface on load.")
        self.surrogate_libraryBtn = QtWidgets.QToolButton()
        self.surrogate_libraryBtn.setObjectName("surrogate_libraryBtn")
        self.surrogate_libraryBtn.setText("...")
        self.surrogate_libraryBtn.setProperty("role", "browse")
        self.surrogate_libraryBtn.setToolTip(
            "Browse for the interpolated E-field library")
        for widget in (surrogate_cap, self.surrogate_library_label,
                       self.surrogate_libraryBtn):
            row_layout.addWidget(widget)
        if efield_layout is not None:
            efield_layout.insertWidget(
                efield_layout.indexOf(self.efield_hint),
                self.surrogate_library_row)

        path_tooltips = {
            "loadmeshlabel": "Head mesh for the 3D view and the online FEM.\n"
                             "Accepts a pynibs mesh HDF5 (.hdf5 — the matching SimNIBS .msh\n"
                             "next to it is used automatically) or a SimNIBS .msh file.",
            "loadroilabel": "ROI surface: HDF5 with the ROI triangles\n"
                            "(e.g. data/<subject>/mesh/roi/<roi>/geo.hdf5).\n"
                            "Its element count must match the loaded E-field library.",
            "target_order_LineEdit": "Optional text file with the stimulation target order\n"
                                     "(one target per line).",
            "loadplacementlabel": "Coil placement library: HDF5 with the candidate placements,\n"
                                  "e.g. search_positions.hdf5 from scripts/02_create_roi_efield_library.py.",
            "load_e_matrix_label": "Precomputed E-field library: e.hdf5 with the E_mag dataset\n"
                                   "(n_placements x n_roi_elements), written by\n"
                                   "scripts/02_create_roi_efield_library.py. Used by the Precomputed E-Field mode.",
            "savePathLineEdit": "Results CSV file: MEP/regression results are written here\n"
                                "(a .csv ending is added automatically).",
            "coilspathlineedit": "TMS coil model: SimNIBS coil file (.ccd or .ccd.nii.gz),\n"
                                 "e.g. MagVenture_MCF-B65_new.ccd.",
            "emg_config_label": "EMG channel sources: YAML with one source per channel\n"
                                "('element_id' into the ROI or 'xyz' in mm, SimNIBS\n"
                                "coordinates -- xyz is projected to the closest ROI\n"
                                "element). Channel names and count come from\n"
                                "EMG_CHANNELS in .env.",
        }
        for widget_name, tooltip in path_tooltips.items():
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setToolTip(tooltip)
        for btn_name, tooltip in {
            "loadmeshBtn": "Browse for the head mesh file",
            "loadROIBtn": "Browse for the ROI surface file",
            "target_order_PathBtn": "Browse for the target-order file",
            "loadplacementsBtn": "Browse for the coil placement library",
            "load_e_matrixBtn": "Browse for the precomputed E-field library",
            "savePathBtn": "Choose where the results CSV is written",
            "coilPathBtn": "Browse for the TMS coil model file",
        }.items():
            btn = getattr(self, btn_name, None)
            if btn is not None:
                btn.setToolTip(tooltip)

        # Fonts are set programmatically (pixel-based, per widget class) and
        # scaled together with the geometry in _rescale — the .ui's scattered
        # 9pt fonts made sizes inconsistent, and fixed pixel fonts read badly
        # on high-DPI screens.
        # The Start/Back/Next buttons are flattened out of their layout in
        # _flatten_button_row (called right before the base-geometry capture)
        # so they can be centered under the status LEDs exactly and scaled
        # with everything else.

        # Absolute-positioned form: capture the design geometry (1244x894) so
        # resizeEvent can scale every child proportionally (see _rescale).
        # Capture must wait for the first layout pass — before it, the
        # centralwidget still has its 100x30 placeholder size.
        self._base_rects = None

        # create a pipeline controller instance
        self.controller = None

        self.toggle_free_drive_set = True

        # list to store the emg data
        # New History Management
        self.emg_history = []  # List of dictionaries
        self.current_history_idx = -1

        # Connect the signals from EmgNavGraphWidget
        self.widget_emg_signal.prev_clicked.connect(self.show_previous_emg)
        self.widget_emg_signal.next_clicked.connect(self.show_next_emg)
        self.widget_emg_signal.inclusion_toggled.connect(self.handle_inclusion_change)

        # for plotting
        self.history_targets = []

        # Storage (Over Time)
        self.history_meps = {}

        # 2nd. Tap (Connections)
        # the following components are dicts
        # they will be used to mapp through them to fill the UI elements
        # Will be filled in initialize()
        self.all_error_recoveries = {}  # {system_obj: {error_msg: recovery_name}}
        self.status_labels = {}  # {system_obj: QLabel}
        self.message_labels = {}  # {system_obj: QLabel}
        self.recover_buttons = {}  # {system_obj: QPushButton}
        self.pending_recovery = {}  # {system_obj: str}  # which recovery to call next
        self.last_update_labels={} # {system_obj: QLabel}

        #1. Tab (Project)
        self.loadmeshBtn.clicked.connect(self.pick_mesh)
        self.loadmeshlabel.editingFinished.connect(self.paste_mesh_path)

        self.loadROIBtn.clicked.connect(self.pick_ROI)
        self.loadroilabel.editingFinished.connect(self.paste_roi_path)

        self.target_order_PathBtn.clicked.connect(self.pick_target_order_path)
        self.target_order_LineEdit.editingFinished.connect(self.paste_target_order_path)

        self.loadplacementsBtn.clicked.connect(self.pick_coilplacement)
        self.loadplacementlabel.editingFinished.connect(self.paste_coil_placements_path)

        self.load_e_matrixBtn.clicked.connect(self.pick_e_field)
        self.load_e_matrix_label.editingFinished.connect(self.paste_e_field_path)

        self.surrogate_libraryBtn.clicked.connect(self.pick_surrogate_library)
        self.surrogate_library_label.editingFinished.connect(
            self.paste_surrogate_library_path)

        self.savePathBtn.clicked.connect(self.pick_save_path)
        self.savePathLineEdit.editingFinished.connect(self.paste_save_path)

        self.coilPathBtn.clicked.connect(self.pick_coil_path)
        self.coilspathlineedit.editingFinished.connect(self.paste_coil_path)

        self.emgConfigBtn.clicked.connect(self.pick_emg_config)
        self.emg_config_label.editingFinished.connect(self.paste_emg_config)

        self.load_yaml.clicked.connect(self.on_load_yaml)
        self.save_yaml.clicked.connect(self.on_save_yaml)


        #3rd. Tab (control)
        self.efield_mode_selected = False
        self._pending_efield_mode = None
        self.online_efield_btn.setEnabled(False)
        self.offline_efield_btn.setEnabled(False)
        self.surrogate_efield_btn.setEnabled(False)

        self.online_efield_btn.toggled.connect(self.on_efield_mode_changed)
        self.offline_efield_btn.toggled.connect(self.on_efield_mode_changed)
        self.surrogate_efield_btn.toggled.connect(self.on_efield_mode_changed)
        self.surrogate_library_ready.connect(self._on_surrogate_library_ready)

        # Nothing may run before a mode and a ready stack exist: start with the
        # whole transport row (and Finish) disabled.
        self.update_button_states()

        # Status LEDs live in the tab bar's top-right corner (right of the
        # tab strip) instead of on the Control page.
        # The empty part of the tab strip is painted by QTabBar itself from
        # the palette, not from the style sheet — fill it white so the strip
        # reads as one bar from the tabs to the LEDs.
        bar = self.tabWidget.tabBar()
        bar.setAutoFillBackground(True)
        bar_palette = bar.palette()
        bar_palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#FFFFFF"))
        bar.setPalette(bar_palette)

        corner = _TabCornerFrame(self.tabWidget)
        self._tab_corner = corner
        self._top_line = _TopLineOverlay(self.tabWidget)
        corner.setObjectName("tab_corner")
        # Same white as the tab strip — a transparent corner showed the
        # window grey behind the LEDs.
        corner.setStyleSheet(
            "QFrame#tab_corner { background: #FFFFFF; border: none; }")
        corner_layout = QtWidgets.QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 12, 0)
        corner_layout.setSpacing(14)
        self._corner_pairs = {}
        for attr, caption in (("led_stim", "Stimulator"),
                              ("led_emg", "EMG"),
                              ("led_robot", "Robot"),
                              ("led_relay", "Relay")):
            pair = QtWidgets.QHBoxLayout()
            pair.setSpacing(6)
            led = QtWidgets.QLabel(corner)
            led.setProperty("led", True)
            led.setFixedSize(10, 10)
            setattr(self, attr, led)
            cap = QtWidgets.QLabel(caption, corner)
            cap.setProperty("role", "cap")
            pair.addWidget(led)
            pair.addWidget(cap)
            corner_layout.addLayout(pair)
            self._corner_pairs[attr] = (led, cap)
        self.tabWidget.setCornerWidget(corner, QtCore.Qt.TopRightCorner)

        self._populate_fit_functions()
        self._setup_robot_scene_view(self.simulation)
        self._setup_config_tab()
        self._collision_test_config = None
        self._setup_collision_tab()
        self._setup_about_tab()

        # Mapping-results panel: state, table and wiring.
        self._mapping_scores = {}        # channel key -> R2 per ROI element
        self._mapping_placements = []    # realized coil placements
        self._emg_display_names = []
        self._selection_pinned = False
        self._setup_mapping_panel()

        # Check tick + spin-box chevrons come from generated PNGs; the rules
        # are appended here so they take part in the normal px scaling.
        self._install_ui_assets()

        # Default coil model: the MCF-B65 CCD shipped with SimNIBS (the same
        # model the precomputed E-field library was computed with). Goes
        # through paste_coil_path so validation and the FEM manager update
        # exactly like a hand-entered path.
        default_coil = _simnibs_coil_model("Drakaki_BrainStim_2022",
                                           "MagVenture_MCF-B65_new.ccd")
        if default_coil:
            self.coilspathlineedit.setText(default_coil)
            self.paste_coil_path()

        # One-line status under the E-field radios ("choose a mode", "warming
        # up", "ready"), refreshed by update_button_states.
        self._update_efield_hint()

        # Paint the window with the default theme; the Config tab re-applies
        # the saved one when it loads the lab profile.
        self.apply_theme(self._theme_name)


        self.led_labels = {}  # map LED labels to systems

        # 1. Initialize Explicit Hardware Flags for Disabling and enabling the start and skip button
        self.robot_ready = False
        self.stim_ready = False
        self.emg_ready = False
        self.relay_ready = False
        self._setup_relay_card()

        # 2. Disable execution buttons by default on startup
        self.start_btn.setEnabled(False)
        self.skiptarget.setEnabled(False)
        self.back_btn.setEnabled(False)
        self.enableBtn.setEnabled(False)
        self.fireBtn.setEnabled(False)

        self.skiptarget.clicked.connect(self.on_skip_step_clicked)
        self.back_btn.clicked.connect(self.on_back_clicked)
        self.start_btn.clicked.connect(self.on_start_pause_clicked)
        self.finish_btn.clicked.connect(self.on_finish_clicked)
        self.move_coil_up.clicked.connect(self.on_move_coil_up)
        self.freedrive.clicked.connect(self.toggle_free_drive_func)
        self.enableBtn.clicked.connect(self.on_enable_clicked)
        self.fireBtn.clicked.connect(self.on_fire_stim_clicked)

        self.slider.valueChanged.connect(self.slider1_spinbox1)
        self.spinBox.valueChanged.connect(self.slider1_spinbox1)

        self.slider2.valueChanged.connect(self.slider2_spinbox2)
        self.spinBox2.valueChanged.connect(self.slider2_spinbox2)

        self.slider3.valueChanged.connect(self.slider3_spinbox3)
        self.spinBox3.valueChanged.connect(self.slider3_spinbox3)

        self.sampling_spinBox.valueChanged.connect(self.on_subsampling_changed)
        self.n_repetitions_spinBox.valueChanged.connect(self.on_n_repetitions_changed)
        self.min_interval_spinBox.valueChanged.connect(self.on_min_interval_changed)

        self.pulseShapeComboBox.currentTextChanged.connect(self.on_pulse_shape_changed)
        self.fitFunctionComboBox.currentTextChanged.connect(self.on_fit_function_changed)
        for combo in (self.pulseShapeComboBox, self.fitFunctionComboBox):
            combo.setMaxVisibleItems(12)


        #4th Tab
        # --- set the title for each widget ---
        if hasattr(self, 'widget_mep_trend'):
            self.widget_mep_trend.set_title("MEPs")

        if hasattr(self, 'widget_emg_signal'):
            self.widget_emg_signal.set_title("Last EMG")
            self.refresh_emg_nav_display()

        # ── Project file tracking (Project group, Project tab) ─────────────
        # The label under Load/Save shows the loaded project file and turns
        # bold as soon as any project field is changed.
        self._project_file = None
        self._project_dirty = False
        self._project_loading = False
        self._project_ready = True
        for _le in (self.savePathLineEdit, self.target_order_LineEdit,
                    self.loadplacementlabel, self.loadmeshlabel,
                    self.loadroilabel, self.load_e_matrix_label,
                    self.coilspathlineedit, self.project_name_edit,
                    self.emg_config_label):
            _le.textChanged.connect(self._mark_project_dirty)
        for _cb in (self.fitFunctionComboBox, self.pulseShapeComboBox):
            _cb.currentTextChanged.connect(self._mark_project_dirty)
        self.overwrite_results_chk.toggled.connect(
            self._on_overwrite_results_changed)
        self.overwrite_results_chk.toggled.connect(self._mark_project_dirty)
        for _sb in (self.sampling_spinBox, self.spinBox, self.min_interval_spinBox,
                    self.n_repetitions_spinBox, self.spinBox2, self.spinBox3):
            _sb.valueChanged.connect(self._mark_project_dirty)
        self._update_project_label()

        # File summaries next to the project paths (updated on change, with
        # a short debounce; heavy mesh reads happen in a worker thread).
        self._info_cache = {}
        self._info_timer = QtCore.QTimer(self)
        self._info_timer.setSingleShot(True)
        self._info_timer.setInterval(250)
        self._info_timer.timeout.connect(self._update_file_infos)
        for _le in (self.loadmeshlabel, self.loadroilabel, self.target_order_LineEdit,
                    self.loadplacementlabel, self.load_e_matrix_label,
                    self.savePathLineEdit, self.coilspathlineedit,
                    self.emg_config_label):
            _le.textChanged.connect(lambda *_: self._info_timer.start())
        # Heavy files are read in daemon workers; their results arrive on the
        # GUI thread through this poll timer.  The window (and every other
        # tab) stays interactive while a head mesh or E-field library loads.
        self._loaders = {}
        self._pending_loads = {}
        self._load_tokens = {}
        self._load_current = {}
        self._load_serial = 0
        self._mesh_view_request = None
        self._load_timer = QtCore.QTimer(self)
        self._load_timer.setInterval(40)
        self._load_timer.timeout.connect(self._drain_load_results)
        self._load_timer.start()
        # Closing while a worker is inside VTK (head decimation) must keep
        # the Qt application alive until that thread is done; destroying it
        # under a running VTK call segfaults.
        self._close_requested = False
        self._close_prepared = False
        self._close_force = False
        self._close_deadline = None
        self._close_timer = QtCore.QTimer(self)
        self._close_timer.setInterval(100)
        self._close_timer.timeout.connect(self._retry_close)
        self._update_file_infos()

        # QSS cannot raise the popup row height with Fusion; install the
        # delegate once every page has built its combo boxes, then size the
        # popups from those row heights.
        install_tall_combo_rows(self)
        self._size_choice_popups()

        # Restore the last session's project fields. The values are only
        # stashed here — they are applied in set_controller(), once the
        # controller (and its setters) exist.
        self._pending_session = None
        cache_fn = _session_cache_path()
        if os.path.isfile(cache_fn):
            try:
                with open(cache_fn, "r") as f:
                    data = yaml.safe_load(f) or {}
                # A truncated or hand-edited cache can hold anything; only a
                # mapping is a usable session.
                self._pending_session = data if isinstance(data, dict) else {}
            except (OSError, yaml.YAMLError) as e:
                print(f"Session cache unreadable, ignoring: {e}")

    # ── Session cache (per-user, ~/.neuropilot/last_session.yaml) ──────────
    def _save_session_cache(self):
        """Persist the current project fields for the next startup."""
        fn = _session_cache_path()
        try:
            os.makedirs(os.path.dirname(fn), exist_ok=True)
            with open(fn, "w") as f:
                yaml.dump(self.get_config_dict(), f, default_flow_style=False)
        except OSError as e:
            print(f"Could not write session cache: {e}")

    def _apply_pending_session(self):
        """Apply the stashed session cache, if any (called on controller
        attach so the values also reach the controller's setters)."""
        if not self._pending_session:
            return
        self._project_loading = True
        try:
            self.apply_config_dict(self._pending_session)
        finally:
            self._project_loading = False
        self._pending_session = None

    # ── Appearance ────────────────────────────────────────────────────────
    def apply_theme(self, name, persist=False):
        """Repaint the whole window with a colour theme.

        The style sheet is regenerated from the token table and every colour
        the code sets directly (status labels, LEDs, mode badge, chart and 3D
        backgrounds, the instrument beds) is refreshed.  The choice can be
        written to the lab profile so it survives a restart.
        """
        self._theme_name = name if name in THEMES else DEFAULT_THEME
        self._theme = theme_tokens(self._theme_name)
        # The tick must contrast with the accent fill of the active theme.
        self._ui_icons = _control_ui_icons(self._theme["on_accent"])
        sheet = build_stylesheet(self._theme_name, icons=self._ui_icons)
        self.setStyleSheet(sheet)
        self._restyle_parts()
        base = getattr(self, "_base_rects", None)
        if base is not None:
            base["win_sheet"] = sheet          # the scaler re-applies this one
            # The fresh sheet is built at the design size. Re-apply the
            # current window scale immediately, otherwise a theme change
            # makes the whole window snap back to small fonts until the
            # next resize.
            self._rescale()
            self._match_relay_card_height()
        if persist:
            try:
                self._lab_profile.write({"UI_THEME": self._theme_name})
            except OSError as e:
                print(f"[WARN] could not save the theme: {e}")
        return self._theme_name

    def _restyle_parts(self):
        """Re-apply the colours that live outside the style sheet."""
        theme = self._theme

        # Tab strip and its LED corner share the card colour.
        bar = self.tabWidget.tabBar()
        palette = bar.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(theme["card"]))
        bar.setPalette(palette)
        bar.setAutoFillBackground(True)
        corner = getattr(self, "_tab_corner", None)
        if corner is not None:
            corner.setStyleSheet(
                f"QFrame#tab_corner {{ background: {theme['card']};"
                " border: none; }")

        # Instrument beds (log + robot view).
        log = getattr(self, "finishedsteps", None)
        if log is not None:
            log.setStyleSheet(
                f"QPlainTextEdit {{ background: {theme['bed']};"
                f" color: {theme['bed_ink']}; border: none;"
                " border-radius: 8px; padding: 10px; }")
        bed = getattr(self, "robot_view_label", None)
        if bed is not None:
            bed.setStyleSheet(
                f"QLabel {{ background: {theme['bed']}; border-radius: 8px;"
                f" color: {theme['bed_muted']}; }}")

        # Charts and the 3D view.
        for attr in ("widget_mep_trend", "widget_emg_signal"):
            widget = getattr(self, attr, None)
            apply = getattr(widget, "apply_theme", None)
            if callable(apply):
                apply(theme)
        view = getattr(self, "widget_3d_viewer", None)
        apply = getattr(view, "apply_theme", None)
        if callable(apply):
            apply(theme)

        # Re-render the colours the handlers write inline.
        self._apply_config_mode()
        for system, status in list(getattr(self, "_system_status", {}).items()):
            self.update_system_status(system, status)
        self._update_efield_hint()
        self._recolour_about_links()

    @QtCore.pyqtSlot(str, str)
    def _on_file_info_ready(self, name, text):
        """Deliver a worker-produced file summary to its caption label."""
        label = getattr(self, name, None)
        if label is not None:
            label.setText(text)

    def _emit_file_info(self, name, text):
        """Thread-safe: called from the mesh/coil reader threads."""
        if getattr(self, "_closing", False):
            return
        try:
            self.file_info_ready.emit(name, text)
        except RuntimeError:                 # window already destroyed
            pass

    # ── Asynchronous file loading ─────────────────────────────────────────
    _LOAD_INFO_LABELS = {
        "head": "info_mesh",
        "roi": "info_roi",
        "efield": "info_efield",
        "targets": "info_placements",
        "emg": "info_emg",
    }

    def _loader_for(self, kind):
        loader = self._loaders.get(kind)
        if loader is not None:
            return loader
        if kind in ("head", "roi"):
            load_fn = lambda path, job: read_mesh_file(
                path, job.get("mesh_type", kind),
                stop_event=job.get("stop_event"))
        elif kind == "efield":
            load_fn = lambda path, job: read_e_matrix_file(path)
        elif kind == "targets":
            load_fn = lambda path, job: read_simnibs_targets_data(path)
        elif kind == "emg":
            load_fn = lambda path, job: read_emg_config_elements(
                path, job.get("roi_path"))
        else:
            raise ValueError(f"unknown loader kind: {kind}")
        loader = _FileLoader(kind, load_fn)
        self._loaders[kind] = loader
        return loader

    def _set_load_info(self, kind, text):
        label = getattr(self, self._LOAD_INFO_LABELS.get(kind, ""), None)
        if label is not None:
            label.setText(text or "")

    def _start_load(self, kind, path, force=False, **meta):
        """Start a background read, replacing an older one of the same kind.

        Returns the token, or ``None`` when the exact same file is already
        loaded or in flight.  The caller has already put the path in the
        line edit; this method only schedules the read and updates the
        summary label.
        """
        if not path:
            self._cancel_load(kind)
            return None
        signature = _path_signature(path)
        current = self._load_current.get(kind)
        if (not force and current and current.get("path") == path
                and current.get("signature") == signature
                and (current.get("loaded") or current.get("pending"))):
            if current.get("pending"):
                self._set_load_info(kind, "loading...")
            return None

        # Tokens are compared per kind, but the pending map is global; keep
        # the serial unique so a fast E-field read cannot clear a mesh job.
        self._load_serial += 1
        token = self._load_serial
        self._load_tokens[kind] = token
        for old_token, old_job in list(self._pending_loads.items()):
            if old_job.get("kind") == kind:
                self._pending_loads.pop(old_token, None)
        self._load_current[kind] = {
            "token": token, "path": path, "signature": signature,
            "loaded": False, "pending": True,
        }
        self._pending_loads[token] = {"kind": kind, "path": path}
        self._loader_for(kind).submit(token, path, **meta)
        self._set_load_info(kind, "loading...")
        self.update_button_states()
        return token

    def _cancel_load(self, kind):
        """Forget the current request and drop whatever has not started."""
        self._load_tokens[kind] = self._load_tokens.get(kind, 0) + 1
        self._load_current.pop(kind, None)
        for old_token, old_job in list(self._pending_loads.items()):
            if old_job.get("kind") == kind:
                self._pending_loads.pop(old_token, None)
        loader = self._loaders.get(kind)
        if loader is not None:
            loader.cancel()
        self._set_load_info(kind, "")
        self.update_button_states()

    def _drain_load_results(self):
        """Deliver finished background reads to the GUI thread."""
        if getattr(self, "_closing", False):
            return
        changed = False
        for kind, loader in list(self._loaders.items()):
            for result in loader.poll():
                token = result.get("token")
                self._pending_loads.pop(token, None)
                current = self._load_current.get(kind)
                if not current or current.get("token") != token:
                    continue       # the operator changed the path meanwhile
                current["pending"] = False
                if result.get("error"):
                    current["loaded"] = False
                    self._handle_load_error(kind, result)
                else:
                    current["loaded"] = True
                    self._handle_load_success(kind, result)
                changed = True
        if changed:
            self._check_paths_ready()

    def _handle_load_success(self, kind, result):
        path = result.get("path", "")
        signature = _path_signature(path)
        if kind in ("head", "roi"):
            field = self.loadmeshlabel if kind == "head" else self.loadroilabel
            if field.text().strip() != path:
                return
            payload = result.get("payload")
            if not payload:
                return
            loaded_mesh, summary = payload
            select = self._mesh_view_request in (None, kind)
            self.widget_3d_viewer.set_loaded_mesh(
                loaded_mesh, mesh_type=kind, select=select)
            self._set_load_info(kind, summary)
            cache_key = "mesh" if kind == "head" else "roi"
            self._info_cache[(path, cache_key, signature)] = summary
            if kind == "roi" and self.emg_config_label.text().strip():
                # The xyz sources project onto the ROI element order; a new
                # ROI can change the nearest element.  Reload off the GUI.
                self._start_load("emg", self.emg_config_label.text().strip(),
                                 force=True,
                                 roi_path=self.loadroilabel.text().strip())
        elif kind == "efield":
            if self.load_e_matrix_label.text().strip() != path:
                return
            data, mats = result.get("payload")
            if self.controller:
                self.controller.apply_e_matrix_file(path, data, mats)
            summary = (f"{data.shape[0]:,} × {data.shape[1]:,} "
                       "placements × elements")
            self._set_load_info(kind, summary)
            self._info_cache[(path, "e", signature)] = summary
        elif kind == "targets":
            if self.loadplacementlabel.text().strip() != path:
                return
            target_queue, target_mats = result.get("payload")
            if self.controller:
                self.controller.set_targets_file(
                    path, target_queue=target_queue, target_mats=target_mats)
            summary = f"{len(target_queue):,} placements"
            self._set_load_info(kind, summary)
            self.loadplacementlabel.setToolTip(summary)
            self._info_cache[(path, "pl", signature)] = summary
        elif kind == "emg":
            if self.emg_config_label.text().strip() != path:
                return
            elements = result.get("payload") or []
            applied = True
            if self.controller:
                applied = self.controller.apply_emg_config_elements(elements)
                if applied is None:      # non-Qt test doubles
                    applied = True
            summary = f"{len(elements)} sources" if applied else "ignored"
            self._set_load_info(kind, summary)
            self._info_cache[(path, "emg", signature)] = summary
        self._refresh_subject_summary()

    def _handle_load_error(self, kind, result):
        path = result.get("path", "")
        error = result.get("error") or "unreadable file"
        detail = result.get("detail") or ""
        error_type = result.get("error_type") or type(error).__name__
        print(f"[WARN] could not load {kind} file {path}: {error}")
        if detail:
            print(detail)
        if kind == "targets":
            if self.loadplacementlabel.text().strip() == path:
                self._reject_path(self.loadplacementlabel, error)
            if self.controller:
                self.controller.set_targets_file(None)
            return
        if kind == "emg":
            label = getattr(self, "info_emg", None)
            if label is not None:
                label.setText(f"unreadable ({error_type})")
                label.setToolTip(error)
            if self.emg_config_label.text().strip() == path:
                self.emg_config_label.setToolTip(error)
            return
        if kind == "efield":
            if self.controller:
                self.controller.clear_e_matrix()
            field = self.load_e_matrix_label
        elif kind == "head":
            field = self.loadmeshlabel
        else:
            field = self.loadroilabel
        if field.text().strip() == path:
            field.setToolTip(error)
        label = getattr(self, self._LOAD_INFO_LABELS.get(kind, ""), None)
        if label is not None:
            label.setText(f"unreadable ({error_type})")
            label.setToolTip(error)

    def has_pending_loads(self):
        return bool(self._pending_loads)

    def wait_for_loads(self, timeout=30.0):
        """Process events until all background reads finish (tests/tools)."""
        app = QtWidgets.QApplication.instance()
        deadline = time.monotonic() + max(0.0, float(timeout))
        while self._pending_loads and time.monotonic() < deadline:
            if app is not None:
                app.processEvents()
            self._drain_load_results()
            time.sleep(0.01)
        if app is not None:
            app.processEvents()
        self._drain_load_results()
        return not self._pending_loads

    def closeEvent(self, event):
        """Stop timers/threads that would otherwise outlive the window."""
        busy = [loader for kind, loader in getattr(self, "_loaders", {}).items()
                if kind in ("head", "roi") and loader.is_busy()]
        if busy and not self._close_force:
            if not self._close_requested:
                self._close_requested = True
                self._close_deadline = time.monotonic() + 30.0
                self._closing = True
                self._prepare_close()
                self.setEnabled(False)
                self.setWindowTitle(f"{self.windowTitle()}  (stopping loads...)")
                self._close_timer.start()
            event.ignore()
            return
        self._prepare_close()
        super().closeEvent(event)

    def _prepare_close(self):
        """One-time teardown; safe to call again after a deferred close."""
        if getattr(self, "_close_prepared", False):
            return
        self._close_prepared = True
        self._closing = True
        controller = getattr(self, "controller", None)
        if controller is not None and getattr(controller, "is_running", False):
            # The loop dies with the window: finish the session explicitly so
            # the robot is released and the results file is written.
            print("[WARN] window closed during a mapping session -- finishing it.")
            try:
                controller.finish_experiment()
                controller.move_robot_away_from_head()
            except Exception as e:            # pragma: no cover - teardown
                print(f"[WARN] could not finish the session: {e}")
        stimulator = getattr(controller, "stimulator", None) if controller else None
        if stimulator is not None:
            try:
                stimulator.disarm()
            except Exception:                 # pragma: no cover - hardware
                pass
        for attr in ("_info_timer", "_styles_timer", "_load_timer",
                     "_close_timer"):
            timer = getattr(self, attr, None)
            if timer is not None:
                try:
                    timer.stop()
                except RuntimeError:
                    pass
        for loader in list(getattr(self, "_loaders", {}).values()):
            try:
                loader.stop()
            except Exception:
                pass
        self._pending_loads.clear()
        view = getattr(self, "_robot_scene_view", None)
        if view is not None:
            try:
                view.stop()
            except Exception as e:           # pragma: no cover - GL teardown
                print(f"[WARN] robot view stop: {e}")
        collision_tab = getattr(self, "collision_tab", None)
        if collision_tab is not None:
            try:
                collision_tab.shutdown()
            except Exception as e:           # pragma: no cover - GL teardown
                print(f"[WARN] collision view stop: {e}")

    def _retry_close(self):
        """Finish a close that waited for a background VTK read."""
        if any(loader.is_busy() for kind, loader in self._loaders.items()
               if kind in ("head", "roi")):
            if (self._close_deadline is not None
                    and time.monotonic() < self._close_deadline):
                return
            print("[WARN] background file read did not stop; closing anyway.")
            self._close_force = True
        self._close_timer.stop()
        self._close_requested = False
        self.close()

    def _place_tab_corner(self):
        """Size the LED corner to its (scaled) contents.  QTabWidget only
        re-runs its corner placement on resize, so after a font/style pass
        the captions would clip at the right edge."""
        corner = getattr(self, "_tab_corner", None)
        if corner is None:
            return
        lay = corner.layout()
        if lay is not None:
            # Breathing room between the last caption ("Robot") and the
            # window edge; scales with the UI so it stays visible at 2x.
            margin = max(14, round(14 * self._current_scale()))
            lay.setContentsMargins(0, 0, margin, 0)
            lay.activate()
        hint = corner.sizeHint()
        bar = self.tabWidget.tabBar()
        corner.setGeometry(self.tabWidget.width() - hint.width(), 0,
                           hint.width(), max(hint.height(), bar.height()))
        corner.raise_()
        line = getattr(self, "_top_line", None)
        if line is not None:
            line.setGeometry(bar.width(), 0,
                             max(1, self.tabWidget.width() - bar.width()),
                             max(1, bar.height()))
            line.raise_()

    def _resize_results_panel(self, scale):
        """The results panel's width comes from the style sheet's design
        values, but layout widths do not scale with the window: compute
        them from the current scale so the text always fits."""
        width = max(320, round(330 * scale))
        for attr in ("groupBox_results", "groupBox_display", "groupBox_selection",
                     "groupBox_7"):
            card = getattr(self, attr, None)
            if card is None:
                continue
            card.setMinimumWidth(width)
            card.setMaximumWidth(width + round(40 * scale))

    def _size_choice_popups(self):
        """Give every dropdown a popup tall enough for its visible items.

        Qt sizes the popup from the delegate's row hint, which the scaled
        style sheet can leave smaller than the rendered text, so a two-item
        branch menu used to show one item and a scroll arrow.  The view's
        minimum height is set from the real row heights after every font
        rescale, so all choices are visible without scrolling.
        """
        for combo in self.findChildren(QtWidgets.QComboBox):
            if combo.count() == 0:
                continue
            view = combo.view()
            row = max(view.sizeHintForRow(i) for i in range(combo.count()))
            visible = min(combo.count(), 8)
            combo.setMaxVisibleItems(visible)
            view.setMinimumHeight(visible * row + 2 * view.frameWidth() + 10)

    def _sync_project_gap(self):
        """Keep the gap above the results row at about one input row."""
        grid = self.groupBox_files.layout()
        if grid is None:
            return
        item = grid.itemAtPosition(7, 0)
        if item is None or item.spacerItem() is None:
            return
        row_h = self.loadmeshlabel.height() or self.loadmeshlabel.sizeHint().height()
        item.spacerItem().changeSize(
            10, max(10, row_h),
            QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        grid.invalidate()

    def _populate_fit_functions(self):
        """Fill the mapping-function menus from pynibs (one source of truth)."""
        try:
            from .fit_functions import fit_names
            names = fit_names()
        except Exception as e:
            print(f"[WARN] fit functions unavailable: {e}")
            return
        for attr in ("fitFunctionComboBox", "cfg_fit_function"):
            combo = getattr(self, attr, None)
            if combo is None:
                continue
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            if current in names:
                combo.setCurrentText(current)
            combo.blockSignals(False)

    # ── Config tab ─────────────────────────────────────────────────────
    def _setup_relay_card(self):
        """Add the relay card to the Connections page."""
        tab = getattr(self, "tab1", None)
        layout = tab.layout() if tab is not None else None
        if layout is None or hasattr(self, "relayStatusLabel"):
            return

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(12)

        card = QtWidgets.QGroupBox("Relay")
        card.setObjectName("groupBox_relay")
        card.setProperty("card", True)
        self.groupBox_relay = card
        card_v = QtWidgets.QVBoxLayout(card)
        card_v.setContentsMargins(0, 6, 0, 0)
        card_v.setSpacing(8)

        def add_pair(caption, attr, right=False, role="detail"):
            line = QtWidgets.QHBoxLayout()
            line.setSpacing(8)
            cap = QtWidgets.QLabel(caption)
            cap.setProperty("role", "cap")
            cap.setMinimumWidth(90)
            cap.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                              QtWidgets.QSizePolicy.Fixed)
            val = QtWidgets.QLabel("")
            val.setObjectName(attr)
            # Same roles as the .ui cards: value for Status, mono for the
            # timestamp, detail for the value column.
            val.setProperty("role", role)
            val.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                              QtWidgets.QSizePolicy.Fixed)
            if right:
                val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            line.addWidget(cap)
            line.addWidget(val, 1)
            card_v.addLayout(line)
            setattr(self, attr, val)

        add_pair("Status", "relayStatusLabel", right=True, role="value")
        add_pair("Message", "relayMessageLabel", role="cap")
        add_pair("Last update", "relayLastUpdateLabel", right=True,
                 role="mono")

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        button = QtWidgets.QPushButton("Reconnect")
        button.setObjectName("relayRecoverButton")
        button.setProperty("role", "transport")
        button.setEnabled(False)
        button_row.addWidget(button)
        card_v.addLayout(button_row)
        self.relayRecoverButton = button

        details = QtWidgets.QGroupBox("Details")
        details.setObjectName("groupBox_relay_info")
        details.setProperty("card", True)
        self.groupBox_relay_info = details
        details_v = QtWidgets.QVBoxLayout(details)
        details_v.setContentsMargins(0, 6, 0, 0)
        details_v.setSpacing(8)
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        for index in range(1, 6):
            cap = QtWidgets.QLabel("")
            cap.setObjectName(f"relay_info_cap_{index}")
            cap.setProperty("role", "cap")
            cap.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                              QtWidgets.QSizePolicy.Fixed)
            val = QtWidgets.QLabel("")
            val.setObjectName(f"relay_info_val_{index}")
            val.setProperty("role", "detail")
            val.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                              QtWidgets.QSizePolicy.Fixed)
            setattr(self, f"relay_info_cap_{index}", cap)
            setattr(self, f"relay_info_val_{index}", val)
            grid.addWidget(cap, index - 1, 0)
            grid.addWidget(val, index - 1, 1)
        grid.setColumnStretch(1, 1)
        details_v.addLayout(grid)

        row.addWidget(card, 3)
        row.addWidget(details, 2)
        layout.insertLayout(0, row)

        # The relay row must not collapse to its own (shorter) content: keep
        # both relay cards the same height as the stimulator/EMG/robot cards.
        tabs = getattr(self, "tabWidget", None)
        if tabs is not None:
            tabs.currentChanged.connect(
                lambda _index: QtCore.QTimer.singleShot(
                    0, self._match_relay_card_height))
        QtCore.QTimer.singleShot(0, self._match_relay_card_height)

    def _match_relay_card_height(self, *_):
        """Match the relay row to the height of the other Connections cards."""
        refs = (getattr(self, "groupBox_2", None),
                getattr(self, "groupBox_4", None),
                getattr(self, "groupBox_3", None))
        cards = (getattr(self, "groupBox_relay", None),
                 getattr(self, "groupBox_relay_info", None))
        if any(card is None for card in cards):
            return

        visible = [w.height() for w in refs
                   if w is not None and w.isVisible() and w.height() > 0]
        if not visible:
            # The Connections tab has not been shown yet; use the design
            # height until it is.
            visible = [w.sizeHint().height() for w in refs if w is not None]
        if not visible:
            return
        target = max(visible)
        for card in cards:
            if card.minimumHeight() != target:
                card.setMinimumHeight(target)

    def _setup_target_overlay(self):
        """Put the session counters on top of the robot view.

        The old full-width status strip cost a whole row above the transport
        buttons. Moving the same labels into the 3D view frees that row and
        keeps the counters visible next to the robot.
        """
        root = getattr(self, "tab3", None)
        if root is None:
            return
        root = root.layout()
        if root is None:
            return

        # Remove the old status strip from the page layout; keep its child
        # labels and move them into the overlay.
        for attr in ("totaltargets3", "currenttarget"):
            old = getattr(self, attr)
            self.totals_row.removeWidget(old)
            replacement = _TargetValueLabel(old.text(), self.robot_view_label)
            replacement.setObjectName(attr)
            replacement.setProperty("role", "value")
            replacement.setSizePolicy(old.sizePolicy())
            replacement.setAlignment(old.alignment())
            setattr(self, attr, replacement)
            old.setParent(None)
            old.deleteLater()
        for widget in (self.label_7, self.label_6):
            self.totals_row.removeWidget(widget)
        for index in range(root.count()):
            if root.itemAt(index).layout() is self.status_strip:
                root.takeAt(index)
                break
        # Remove the status strip's row and give the freed height to the log
        # rather than to the 3D view: body (1) then log (2).
        root.setStretch(0, 0)
        root.setStretch(1, 1)
        root.setStretch(2, 2)

        overlay = QtWidgets.QWidget(self.robot_view_label)
        overlay.setObjectName("target_overlay")
        overlay.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        overlay.setStyleSheet(
            "QWidget#target_overlay { background: rgba(15, 23, 42, 0.78);"
            " border-radius: 6px; }"
            "QWidget#target_overlay QLabel { background: transparent;"
            " color: #F8FAFC; }"
            # Captions share the value size: the small cap next to a long
            # bold value ("pulse 0 · 1/1 · target 44") read like a different
            # font. Same size; the muted colour keeps the hierarchy.
            "QWidget#target_overlay QLabel[role=\"cap\"] { color: #CBD5E1;"
            " font-size: 15px; }"
            "QWidget#target_overlay QLabel[role=\"value\"] { color: #FFFFFF;"
            " font-weight: 600; }")

        overlay_layout = QtWidgets.QHBoxLayout(overlay)
        overlay_layout.setContentsMargins(10, 5, 10, 5)
        overlay_layout.setSpacing(6)
        overlay_layout.addWidget(self.label_7)
        overlay_layout.addWidget(self.totaltargets3)
        overlay_layout.addSpacing(12)
        overlay_layout.addWidget(self.label_6)
        overlay_layout.addWidget(self.currenttarget)
        overlay.adjustSize()
        overlay.hide()
        self._target_overlay = overlay
        self.robot_view_label.installEventFilter(self)

        self.totaltargets3.text_changed.connect(self._place_target_overlay)
        self.currenttarget.text_changed.connect(self._place_target_overlay)
        self._place_target_overlay()

    def _place_target_overlay(self, *_):
        """Anchor the counters to the top-right corner of the robot view."""
        overlay = getattr(self, "_target_overlay", None)
        label = getattr(self, "robot_view_label", None)
        if overlay is None or label is None or not label.isVisible():
            return
        if label.width() <= 0 or label.height() <= 0:
            return
        overlay.adjustSize()
        margin = max(8, round(10 * self._current_scale()))
        overlay.move(max(0, label.width() - overlay.width() - margin),
                     margin)
        overlay.show()
        overlay.raise_()

    # ── Config tab ─────────────────────────────────────────────────────
    def _setup_config_tab(self):
        if not hasattr(self, "cfg_save_btn"):
            return
        from .config_store import ConfigStore
        from .. import config as suite_config
        from ..lab_profile import (LabProfile, STIMULATOR_PORT_DEFAULT,
                                   STIMULATOR_TTL_PORT_DEFAULT)
        # Hardware settings live in ~/.neuropilot/lab.yaml; .env stays the
        # bootstrap/override layer (see docs/CONFIG.md).
        self._config_store = ConfigStore()
        self._lab_profile = LabProfile()
        self._config_defaults = {
            "RELAY_HOST": suite_config.RELAY_HOST,
            "RELAY_PORT": str(suite_config.RELAY_PORT),
            "ROOT_FOLDER": suite_config.ROOT_FOLDER,
            "NEUROPILOT_UI_SCALE": os.getenv("NEUROPILOT_UI_SCALE", ""),
            "ROBOT": os.getenv("ROBOT", "omron"),
            "TMS_ROBOT_CONTROL_PATH": os.getenv("TMS_ROBOT_CONTROL_PATH", ""),
            "STIMULATOR_PORT": os.getenv("STIMULATOR_PORT", STIMULATOR_PORT_DEFAULT),
            "STIMULATOR_TTL_PORT": os.getenv("STIMULATOR_TTL_PORT", STIMULATOR_TTL_PORT_DEFAULT),
            "EMG_CHANNELS": os.getenv("EMG_CHANNELS", "FDI,APB,ADM"),
            "EMG_COMPUTER_IP": os.getenv("EMG_COMPUTER_IP", "192.168.1.2"),
            "EMG_COMPUTER_USERNAME": os.getenv("EMG_COMPUTER_USERNAME", "neuro"),
            "EMG_COMPUTER_PASSWORD": os.getenv("EMG_COMPUTER_PASSWORD", ""),
            "SAMPLING_RATE": os.getenv("SAMPLING_RATE", "4000"),
            "CUTOFF_FREQ": os.getenv("CUTOFF_FREQ", "500"),
            "TMS_PULSE_TIME": os.getenv("TMS_PULSE_TIME", "5"),
            "START_MEP": os.getenv("START_MEP", "10"),
            "END_MEP": os.getenv("END_MEP", "100"),
            "VIRTUAL_MEP_NOISE_MV": os.getenv("VIRTUAL_MEP_NOISE_MV", "0.001"),
            "VIRTUAL_MEP_TRIAL_VARIABILITY": os.getenv(
                "VIRTUAL_MEP_TRIAL_VARIABILITY", "true"),
            "VIRTUAL_MEP_MT": os.getenv("VIRTUAL_MEP_MT", "60"),
            "VIRTUAL_MEP_UPPER_LIMIT": os.getenv("VIRTUAL_MEP_UPPER_LIMIT", "100"),
            "VIRTUAL_MEP_EFIELD_SCALE": os.getenv("VIRTUAL_MEP_EFIELD_SCALE", "1.4"),
            "ONLINE_FEM_SOLVER": os.getenv("ONLINE_FEM_SOLVER", "pardiso"),
            "ONLINE_FEM_ANISOTROPY": os.getenv("ONLINE_FEM_ANISOTROPY", "scalar"),
        }

        # Robot models the simulator knows about: the label is shown, the key
        # (what ROBOT/lab.yaml stores) is the item data.
        try:
            from ..sim_robot.robots import labels as robot_labels
            from ..sim_robot.robots import keys as robot_keys
            for key, label in robot_labels():
                self.cfg_robot_type.addItem(label, key)
        except Exception as e:                       # pragma: no cover
            print(f"[WARN] robot registry unavailable: {e}")
            self.cfg_robot_type.addItem("Omron TM5X-700", "omron")
        self.cfg_robot_type.setEditable(True)

        self._theme_loading = True
        self.cfg_theme.addItems(list(THEMES))     # populate without writing
        # The .ui carries Precomputed/Online; the interpolated library is the
        # third E-field source (created in code, like its radio).
        if self.cfg_efield_mode.findText("Interpolated") < 0:
            self.cfg_efield_mode.addItem("Interpolated")
        self._theme_loading = False
        self.cfg_theme.currentTextChanged.connect(self.on_theme_changed)

        self.cfg_save_btn.clicked.connect(self.on_config_save)
        self.cfg_reload_btn.clicked.connect(self.on_config_reload)
        self.cfg_root_browse.clicked.connect(self.on_config_browse_root)

        # Study profile: protocol values that travel between sessions.
        self.cfg_study_save_btn.clicked.connect(self.on_study_save)
        self.cfg_study_load_btn.clicked.connect(self.on_study_load)
        self.cfg_study_apply_btn.clicked.connect(self.on_study_apply)
        self.cfg_subject_save_btn.clicked.connect(self.on_save_yaml)
        self.cfg_subject_load_btn.clicked.connect(self.on_load_yaml)
        self.cfg_subject_goto_btn.clicked.connect(
            lambda: self.tabWidget.setCurrentIndex(0))
        self.cfg_tabs.currentChanged.connect(self._on_config_page_changed)
        self._setup_simulation_page()

        self.on_config_reload()
        self._apply_config_mode()
        self._refresh_subject_summary()

    def _setup_collision_tab(self):
        """Add the pre-flight collision-test page before Config."""
        try:
            from .collision_tab import CollisionTestTab
        except Exception as e:                       # pragma: no cover
            print(f"[WARN] collision-test tab unavailable: {e}")
            return
        page = CollisionTestTab(self, parent=self)
        index = self.tabWidget.count()
        for i in range(self.tabWidget.count()):
            if self.tabWidget.tabText(i) == "Config":
                index = i
                break
        self.tabWidget.insertTab(index, page, "Collision test")
        self.collision_tab = page

    def _setup_about_tab(self):
        """Build the About page as the last tab.

        The text condenses ``docs/site/pages/about.md`` (that page is the
        source of truth; keep the two in step). External links are QLabel
        anchors, never buttons: the generic "click every button" interaction
        test sweeps every page and must not launch a browser.
        """
        self._about_links = []
        page = QtWidgets.QWidget()
        page_layout = QtWidgets.QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        # A scroll area keeps every card readable on smaller windows instead
        # of clipping the last row of the tallest column.
        content = QtWidgets.QWidget()
        content.setMinimumWidth(1040)
        root = QtWidgets.QVBoxLayout(content)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)

        def link(text, url):
            label = QtWidgets.QLabel()
            label.setTextFormat(QtCore.Qt.RichText)
            label.setOpenExternalLinks(True)
            label.setText(f'<a href="{url}">{text}</a>')
            # Same body size as every card (role="cap"); the anchor colour
            # comes from the theme recolour below.
            label.setProperty("role", "cap")
            self._about_links.append(label)
            return label

        def card(title, children):
            box = QtWidgets.QGroupBox(title)
            box.setProperty("card", True)
            col = QtWidgets.QVBoxLayout(box)
            col.setContentsMargins(14, 4, 14, 8)
            col.setSpacing(5)
            for child in children:
                if isinstance(child, QtWidgets.QLayout):
                    col.addLayout(child)
                else:
                    col.addWidget(child)
            return box

        def wrap(text, role=None):
            label = QtWidgets.QLabel(text)
            label.setWordWrap(True)
            if role:
                label.setProperty("role", role)
            return label

        # ── two columns: header + cards on the left, the right-hand
        #    cards starting at the very top ────────────────────────────
        columns = QtWidgets.QHBoxLayout()
        columns.setSpacing(14)
        root.addLayout(columns, 1)
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(12)
        right = QtWidgets.QVBoxLayout()
        right.setSpacing(12)
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)

        # ── header: logo + title + version, top of the left column ──
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(16)
        icon_path = resource_path(os.path.join("gui", "icon.png"))
        if os.path.exists(icon_path):
            pix = QPixmap(icon_path).scaled(
                96, 96, QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation)
            logo = QtWidgets.QLabel()
            logo.setPixmap(pix)
            logo.setAlignment(QtCore.Qt.AlignTop)
            header.addWidget(logo)
        title_col = QtWidgets.QVBoxLayout()
        title_col.setSpacing(2)
        title = QtWidgets.QLabel("NeuroPilot")
        font = title.font()
        font.setPointSize(20)
        font.setBold(True)
        title.setFont(font)
        subtitle = wrap("Guided online TMS mapping with online field "
                        "optimization.", role="cap")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        try:
            from .. import __version__ as _np_version
        except Exception:                            # pragma: no cover
            _np_version = "?"
        version = wrap(f"Version {_np_version}  ·  MPI CBS Leipzig / ScaDS.AI",
                       role="cap")
        title_col.addWidget(version)
        # Without a trailing stretch the layout spreads the logo's extra
        # height between the title lines; the stretch keeps them together.
        title_col.addStretch(1)
        header.addLayout(title_col, 1)
        left.addLayout(header)

        warn = wrap(
            "<b>Research software — not a medical device.</b> NeuroPilot is "
            "intended for research use only and is not approved or cleared "
            "for clinical or therapeutic use. It must not be used for "
            "clinical decisions or to stimulate patients. Real TMS requires "
            "ethics approval, a trained operator and the stimulator "
            "manufacturer's safety limits.", role="cap")
        left.addWidget(card("Research use only", [warn]))

        about = wrap(
            "NeuroPilot runs E-field-optimized TMS mapping experiments: each "
            "pulse is paired with the electric field at its realized coil "
            "pose, a regression is fitted per ROI element and EMG channel, "
            "and the results guide the next placement. It integrates with "
            "InVesalius neuronavigation, supports robot assistance and ships "
            "a complete virtual twin (relay, virtual robot, virtual "
            "navigation) to develop and train the workflow without hardware "
            "or subjects.", role="cap")
        left.addWidget(card("About", [about]))

        sci = wrap(
            "Per-pulse E-field mapping follows Numssen et al. (2021); the "
            "mapping protocol follows Weise et al. (2023). Coil placement "
            "optimization can use FPS (Schultheiss et al., 2025) or D-optimal "
            "design (Numssen, Qiu et al., 2026). The interpolated E-field "
            "mode uses the surrogate method of Grosshagauer et al. (2025). "
            "The R² map is an explanatory localization fitted to the "
            "collected pulses — not a significance map, a causal source "
            "reconstruction or a clinical diagnosis.", role="cap")
        papers_note = wrap(
            "A loose collection of papers from our groups and from others — "
            "not a complete review of the field.", role="cap")
        papers = [
            ("Weise & Numssen (2020) — a novel approach to localize cortical TMS",
             "https://doi.org/10.1016/j.neuroimage.2019.116486"),
            ("Numssen et al. (2021) — element-wise E-field mapping",
             "https://doi.org/10.1016/j.neuroimage.2021.118654"),
            ("Weise et al. (2023) — TMS mapping protocol",
             "https://doi.org/10.1038/s41596-022-00776-6"),
            ("Jing et al. (2023) — TMS effects on spatial attention",
             "https://doi.org/10.1088/1361-6560/acff34"),
            ("Jing et al. (2026) — effects of E-field direction on TMS-based motor cortex mapping",
             "https://doi.org/10.1162/IMAG.a.1211"),
            ("Feng et al. (2026) — target-specificity in neuro-cardiac-guided TMS",
             "https://doi.org/10.1038/s41398-026-03879-w"),
            ("Feng et al. (2026) — cortical stimulation strength in sgACC (preprint)",
             "https://doi.org/10.64898/2026.05.10.724073"),
            ("Qiu et al. (2026) — optimal pre-experimental coil sequences",
             "https://doi.org/10.1162/IMAG.a.1446"),
            ("Qiu et al. (2026) — real-time posterior probabilistic TMS",
             "https://doi.org/10.64898/2026.10.06.757035"),
            ("Schultheiss et al. (2025) — FPS coil placement",
             "https://doi.org/10.1162/IMAG.a.1056"),
            ("Numssen, Qiu et al. (2026) — D-optimal coil placement",
             "https://doi.org/10.64898/2026.10.24.761539"),
            ("Grosshagauer et al. (2025) — surrogate E-field mode",
             "https://doi.org/10.1016/j.brs.2025.102990"),
            ("Yaseen (2026) — virtual twin and real-time E-field approach (master's thesis)",
             "https://neuropilot-94ad2d.pages.gwdg.de/"),
        ]
        resources = [
            ("Documentation", "https://neuropilot-94ad2d.pages.gwdg.de/"),
            ("Source code",
             "https://gitlab.gwdg.de/tms-localization/papers/neuropilot"),
            ("InVesalius", "https://invesalius.github.io/"),
            ("tms-robot-control",
             "https://gitlab.gwdg.de/tms-localization/cobot/tms-robot-control"),
            ("pynibs", "https://gitlab.gwdg.de/tms-localization/pynibs"),
            ("SimNIBS", "https://simnibs.github.io/simnibs/"),
        ]
        right.addWidget(card("Resources", [link(t, u) for t, u in resources]))

        lic = wrap(
            "Released under <b>CC BY-NC-SA 4.0</b>: free for non-commercial "
            "use (research and clinical science) with attribution and "
            "share-alike; commercial use needs permission from the authors.",
            role="cap")
        right.addWidget(card("License", [
            lic,
            link("Creative Commons BY-NC-SA 4.0",
                 "https://creativecommons.org/licenses/by-nc-sa/4.0/"),
            link("Full license text",
                 "https://gitlab.gwdg.de/tms-localization/papers/"
                 "neuropilot/-/blob/main/LICENSE"),
        ]))
        # The longest box goes to the right half, so the left column stays
        # short enough for How to cite and Credits to fit under About.
        right.addWidget(
            card("Scientific background",
                 [sci, papers_note, *[link(t, u) for t, u in papers]]))
        right.addStretch(1)

        thesis_text = ("Yaseen, A. (2026). A Virtual Twin and Real-Time "
                       "E-Field Approach for Robot-Assisted TMS Motor Cortex "
                       "Mapping. Master's thesis, Ernst Abbe University of "
                       "Applied Sciences Jena.")
        software_text = ("NeuroPilot: guided online TMS mapping with online "
                         "field optimization. MPI CBS Leipzig / ScaDS.AI.")

        def cite_row(text):
            """Selectable citation text with a small copy-to-clipboard icon.

            A plain QLabel is not selectable, so the text needed interaction
            flags; the button copies the full citation in one click. A copy
            is harmless in the generic click-every-button sweep.
            """
            label = QtWidgets.QLabel(text)
            label.setWordWrap(True)
            label.setProperty("role", "mono")
            label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse |
                                          QtCore.Qt.TextSelectableByKeyboard)
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(label, 1)
            btn = QtWidgets.QToolButton()
            btn.setProperty("role", "browse")
            btn.setIcon(QtGui.QIcon(_copy_icon()))
            btn.setIconSize(QtCore.QSize(12, 12))
            btn.setToolTip("Copy citation")
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(
                lambda: QtWidgets.QApplication.clipboard().setText(text))
            row.addWidget(btn, 0, QtCore.Qt.AlignTop)
            return row

        left.addWidget(card("How to cite", [
            cite_row(thesis_text),
            cite_row(software_text),
        ]))

        credits = wrap(
            "Maintained by Ole Numssen (MPI CBS / ScaDS.AI) with the group "
            "and external collaborators.", role="cap")
        left.addWidget(card("Credits", [
            credits,
            link("Contact: numssen@cbs.mpg.de",
                 "mailto:numssen@cbs.mpg.de"),
            link("Full contributor list: CONTRIBUTORS.md",
                 "https://gitlab.gwdg.de/tms-localization/papers/"
                 "neuropilot/-/blob/main/CONTRIBUTORS.md"),
        ]))
        # Without a trailing stretch the layout inflates every card to fill
        # the column height; the stretch lets cards keep their natural size.
        left.addStretch(1)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        # Vertical scrolling only: the two-column layout is designed for the
        # window width, so a horizontal scrollbar would never help.
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        self.tabWidget.addTab(page, "About")
        self._recolour_about_links()

    def _recolour_about_links(self):
        """Colour the About page anchors with the active theme's accent."""
        theme = getattr(self, "_theme", None)
        if not theme:
            return
        for label in list(getattr(self, "_about_links", [])):
            try:
                label.setStyleSheet(f"a {{ color: {theme['accent']}; }}")
            except Exception:                       # pragma: no cover
                pass

    def _setup_simulation_page(self):
        """Build Config › Simulation (the .ui has no page for it)."""
        if not hasattr(self, "cfg_tabs") or hasattr(self, "cfg_tab_simulation"):
            return
        page = QtWidgets.QWidget()
        page.setObjectName("cfg_tab_simulation")
        root = QtWidgets.QVBoxLayout(page)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        intro = QtWidgets.QLabel(
            "Tune the MEP model used by the virtual EMG in simulation mode. "
            "The channel source elements come from the project.")
        intro.setProperty("role", "cap")
        intro.setWordWrap(True)
        root.addWidget(intro)

        columns = QtWidgets.QHBoxLayout()
        columns.setSpacing(10)
        root.addLayout(columns, 1)

        model = QtWidgets.QGroupBox("MEP model")
        model.setProperty("card", True)
        model.setMinimumWidth(420)
        model_v = QtWidgets.QVBoxLayout(model)
        model_v.setContentsMargins(0, 6, 0, 0)
        model_v.setSpacing(8)

        def add_row(text, widget):
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(8)
            cap = QtWidgets.QLabel(text)
            cap.setProperty("role", "cap")
            cap.setFixedWidth(160)
            row.addWidget(cap)
            row.addWidget(widget, 1)
            model_v.addLayout(row)

        self.cfg_sim_noise = QtWidgets.QDoubleSpinBox()
        self.cfg_sim_noise.setRange(0.0, 10.0)
        self.cfg_sim_noise.setDecimals(4)
        self.cfg_sim_noise.setSingleStep(0.001)
        add_row("Noise sigma (mV)", self.cfg_sim_noise)

        self.cfg_sim_mt = QtWidgets.QDoubleSpinBox()
        self.cfg_sim_mt.setRange(0.0, 300.0)
        self.cfg_sim_mt.setDecimals(1)
        self.cfg_sim_mt.setSingleStep(1.0)
        add_row("Motor threshold (V/m)", self.cfg_sim_mt)

        self.cfg_sim_upper = QtWidgets.QDoubleSpinBox()
        self.cfg_sim_upper.setRange(1.0, 300.0)
        self.cfg_sim_upper.setDecimals(1)
        self.cfg_sim_upper.setSingleStep(1.0)
        add_row("Upper limit (V/m)", self.cfg_sim_upper)

        self.cfg_sim_scale = QtWidgets.QDoubleSpinBox()
        self.cfg_sim_scale.setRange(0.1, 10.0)
        self.cfg_sim_scale.setDecimals(2)
        self.cfg_sim_scale.setSingleStep(0.1)
        add_row("E-field scale (dI/dt)", self.cfg_sim_scale)

        self.cfg_sim_trial = QtWidgets.QCheckBox("Trial-to-trial variability")
        self.cfg_sim_trial.setProperty("role", "cap")
        model_v.addWidget(self.cfg_sim_trial)
        variability_hint = QtWidgets.QLabel(
            "Off gives an ideal, repeatable curve; noise still applies.")
        variability_hint.setProperty("role", "cap")
        variability_hint.setWordWrap(True)
        model_v.addWidget(variability_hint)
        model_v.addStretch(1)

        left = QtWidgets.QVBoxLayout()
        left.setSpacing(10)
        left.addWidget(model)
        left.addStretch(1)

        source = QtWidgets.QGroupBox("MEP source")
        source.setProperty("card", True)
        source.setMinimumWidth(420)
        source_v = QtWidgets.QVBoxLayout(source)
        source_v.setContentsMargins(0, 6, 0, 0)
        source_v.setSpacing(8)
        self.cfg_sim_sources = QtWidgets.QPlainTextEdit()
        self.cfg_sim_sources.setReadOnly(True)
        self.cfg_sim_sources.setProperty("role", "info")
        self.cfg_sim_sources.setMinimumHeight(150)
        self.cfg_sim_sources.setMaximumHeight(220)
        source_v.addWidget(self.cfg_sim_sources)
        self.cfg_sim_project_btn = QtWidgets.QPushButton("Edit in Project")
        self.cfg_sim_project_btn.setProperty("role", "transport")
        self.cfg_sim_project_btn.clicked.connect(
            lambda: self.tabWidget.setCurrentIndex(0))
        source_v.addWidget(self.cfg_sim_project_btn)
        source_hint = QtWidgets.QLabel(
            "The cortical element per channel is project data. This page only "
            "tunes the simulated signal.")
        source_hint.setProperty("role", "cap")
        source_hint.setWordWrap(True)
        source_v.addWidget(source_hint)
        source_v.addStretch(1)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(source)
        right.addStretch(1)

        columns.addLayout(left, 1)
        columns.addLayout(right, 1)

        self.cfg_sim_hint = QtWidgets.QLabel("")
        self.cfg_sim_hint.setProperty("role", "cap")
        self.cfg_sim_hint.setWordWrap(True)
        self.cfg_sim_hint.setText(
            "Read when the controller starts; restart to apply.")
        root.addWidget(self.cfg_sim_hint)

        bottom = QtWidgets.QHBoxLayout()
        bottom.setSpacing(10)
        self.cfg_sim_save_btn = QtWidgets.QPushButton("Save simulation settings")
        self.cfg_sim_save_btn.setProperty("role", "primary")
        self.cfg_sim_save_btn.clicked.connect(self.on_sim_save)
        self.cfg_sim_reload_btn = QtWidgets.QPushButton("Reload")
        self.cfg_sim_reload_btn.setProperty("role", "transport")
        self.cfg_sim_reload_btn.clicked.connect(self.on_sim_reload)
        self.cfg_sim_status = QtWidgets.QLabel("")
        self.cfg_sim_status.setProperty("role", "cap")
        bottom.addWidget(self.cfg_sim_save_btn)
        bottom.addWidget(self.cfg_sim_reload_btn)
        bottom.addWidget(self.cfg_sim_status, 1)
        root.addLayout(bottom)

        self.cfg_tabs.addTab(page, "Simulation")
        self.cfg_tab_simulation = page

    def _lab_fields(self):
        """(key, widget, kind) for every hardware setting on the Lab page."""
        return (
            ("RELAY_HOST", self.cfg_relay_host, "text"),
            ("RELAY_PORT", self.cfg_relay_port, "int"),
            ("ROOT_FOLDER", self.cfg_root_folder, "text"),
            ("NEUROPILOT_UI_SCALE", self.cfg_ui_scale, "text"),
            ("UI_THEME", self.cfg_theme, "combo"),
            ("ROBOT", self.cfg_robot_type, "robot"),
            ("TMS_ROBOT_CONTROL_PATH", self.cfg_tms_path, "text"),
            ("STIMULATOR_PORT", self.cfg_stim_port, "text"),
            ("STIMULATOR_TTL_PORT", self.cfg_stim_ttl, "text"),
            ("EMG_COMPUTER_IP", self.cfg_emg_ip, "text"),
            ("EMG_COMPUTER_USERNAME", self.cfg_emg_user, "text"),
            ("EMG_COMPUTER_PASSWORD", self.cfg_emg_password, "text"),
            ("ONLINE_FEM_SOLVER", self.cfg_fem_solver, "combo"),
            ("ONLINE_FEM_ANISOTROPY", self.cfg_fem_anisotropy, "combo"),
        )

    def lab_values(self):
        """Current Lab-page values, as they would be written to lab.yaml."""
        values = {}
        for key, widget, kind in self._lab_fields():
            if kind == "int":
                values[key] = str(widget.value())
            elif kind == "robot":
                values[key] = self._robot_key()
            elif kind == "combo":
                values[key] = widget.currentText().strip()
            else:
                values[key] = widget.text().strip()
        # Empty text fields fall back to the defaults, so drop them instead of
        # writing "KEY=" (which would defeat the fallback).
        return {k: v for k, v in values.items()
                if v != "" or k in ("NEUROPILOT_UI_SCALE",
                                    "TMS_ROBOT_CONTROL_PATH")}

    def _robot_key(self):
        """The ROBOT key currently selected (label shown, key stored).

        An editable combo keeps ``currentData()`` from the last selected item
        even after the user types something else, so the data only counts when
        the shown text is that item's label.
        """
        combo = self.cfg_robot_type
        text = combo.currentText().strip()
        index = combo.currentIndex()
        data = combo.currentData()
        if data and 0 <= index < combo.count() and combo.itemText(index) == text:
            return str(data)
        try:
            from ..sim_robot.robots import ROBOTS
            by_label = {spec.label: key for key, spec in ROBOTS.items()}
        except Exception:                            # pragma: no cover
            by_label = {}
        return by_label.get(text, text).lower()

    def _set_robot_key(self, key):
        combo = self.cfg_robot_type
        index = combo.findData(key)
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            # An unknown robot stays visible (and is reported on save) instead
            # of silently switching the lab to a different machine.
            combo.setEditText(str(key))

    def on_config_reload(self):
        """Fill the Lab page from lab.yaml, with .env overriding it.

        The study/analysis values (MEP windows, rates, channel names) still
        come from .env; they are the ones that need a restart.
        """
        lab = self._lab_profile.read()
        env = self._config_store.read()
        source = {}

        def get(key):
            if env.get(key) not in (None, ""):
                source[key] = "env"
                return env[key]
            if lab.get(key) not in (None, ""):
                source[key] = "lab"
                return lab[key]
            source[key] = "default"
            return self._config_defaults.get(key, "")

        for key, widget, kind in self._lab_fields():
            value = get(key)
            if kind == "int":
                self._set_int(widget, value, int(self._config_defaults.get(key, 0) or 0))
            elif kind == "robot":
                self._set_robot_key(str(value))
            elif kind == "combo":
                widget.setCurrentText(str(value) or self._config_defaults.get(key, ""))
            else:
                widget.setText(str(value))
            if source[key] == "env":
                widget.setToolTip(".env overrides the lab profile for this key")
            else:
                widget.setToolTip("")

        self.cfg_emg_channels.setText(
            env.get("EMG_CHANNELS", self._config_defaults.get("EMG_CHANNELS", "")))
        self._set_int(self.cfg_sampling_rate,
                      env.get("SAMPLING_RATE", self._config_defaults["SAMPLING_RATE"]), 4000)
        self._set_int(self.cfg_cutoff,
                      env.get("CUTOFF_FREQ", self._config_defaults["CUTOFF_FREQ"]), 500)
        self._set_int(self.cfg_pulse_time,
                      env.get("TMS_PULSE_TIME", self._config_defaults["TMS_PULSE_TIME"]), 5)
        self._set_int(self.cfg_mep_start,
                      env.get("START_MEP", self._config_defaults["START_MEP"]), 10)
        self._set_int(self.cfg_mep_end,
                      env.get("END_MEP", self._config_defaults["END_MEP"]), 100)

        for key, widget, fallback in (
            ("VIRTUAL_MEP_NOISE_MV", self.cfg_sim_noise, 0.001),
            ("VIRTUAL_MEP_MT", self.cfg_sim_mt, 60.0),
            ("VIRTUAL_MEP_UPPER_LIMIT", self.cfg_sim_upper, 100.0),
            ("VIRTUAL_MEP_EFIELD_SCALE", self.cfg_sim_scale, 1.4),
        ):
            self._set_float(widget, env.get(
                key, self._config_defaults.get(key, fallback)), fallback)
        self.cfg_sim_trial.setChecked(self._as_bool(
            env.get("VIRTUAL_MEP_TRIAL_VARIABILITY"),
            self._as_bool(self._config_defaults.get("VIRTUAL_MEP_TRIAL_VARIABILITY"), True)))
        self._refresh_simulation_summary()

        saved_theme = env.get("UI_THEME") or lab.get("UI_THEME")
        if saved_theme:
            self._theme_loading = True
            try:
                if saved_theme in THEMES:
                    self.cfg_theme.setCurrentText(saved_theme)
                self.apply_theme(saved_theme)
            finally:
                self._theme_loading = False

        overrides = [k for k, src in source.items() if src == "env"]
        detail = (f" · {len(overrides)} key(s) overridden by .env"
                  if overrides else "")
        self._set_config_status(
            f"Loaded {self._lab_profile.path.name} ({self._lab_profile.path}){detail}")

    def on_theme_changed(self, name):
        """Apply a theme immediately and remember it in the lab profile.

        Only a real change is written: populating the combo or reloading the
        page must not create or touch the lab profile.
        """
        if getattr(self, "_theme_loading", False) or not name:
            return
        changed = name != self._theme_name
        self.apply_theme(name, persist=changed)
        if hasattr(self, "cfg_status_label"):
            self._set_config_status(f"Theme: {name} (applied)")

    @staticmethod
    def _set_int(widget, text, fallback):
        try:
            value = int(float(str(text).strip()))
        except (TypeError, ValueError):
            value = fallback
        widget.setValue(value)

    @staticmethod
    def _set_float(widget, text, fallback):
        try:
            value = float(str(text).strip())
        except (TypeError, ValueError):
            value = fallback
        widget.setValue(value)

    @staticmethod
    def _as_bool(text, fallback):
        if text is None or str(text).strip() == "":
            return fallback
        return str(text).strip().lower() in {"1", "true", "yes", "on"}

    def _set_config_status(self, text):
        label = getattr(self, "cfg_status_label", None)
        if label is not None:
            label.setText(text)

    def on_config_browse_root(self):
        folder = self._file_dialog("Select data folder",
                                   self.cfg_root_folder.text() or os.path.expanduser("~"),
                                   "", save=False)
        if folder:
            self.cfg_root_folder.setText(folder)

    def on_config_save(self):
        """Write the hardware settings to lab.yaml and the rest to .env.

        Splitting them keeps the lab profile portable between projects while
        .env stays the bootstrap/override layer; a key kept in .env still
        wins after the restart.
        """
        lab_values = self.lab_values()
        env_values = {
            "EMG_CHANNELS": self.cfg_emg_channels.text().strip(),
            "SAMPLING_RATE": str(self.cfg_sampling_rate.value()),
            "CUTOFF_FREQ": str(self.cfg_cutoff.value()),
            "TMS_PULSE_TIME": str(self.cfg_pulse_time.value()),
            "START_MEP": str(self.cfg_mep_start.value()),
            "END_MEP": str(self.cfg_mep_end.value()),
        }
        env_values = {k: v for k, v in env_values.items() if v != ""}
        try:
            self._lab_profile.write(lab_values)
        except OSError as e:
            self._set_config_status(
                f"Could not write {self._lab_profile.path}: {e}")
            return
        try:
            self._config_store.write(env_values)
        except OSError as e:
            self._set_config_status(
                f"Saved lab profile · could not write {self._config_store.path}: {e}")
            return
        overrides = sorted(set(lab_values) & set(self._config_store.read()))
        detail = (f" · {len(overrides)} key(s) pinned by .env" if overrides else "")
        self._set_config_status(
            f"Saved {self._lab_profile.path.name}{detail}"
            " — restart NeuroPilot to apply.")

    def on_sim_save(self):
        """Write the simulated-MEP knobs to .env."""
        if not (self.simulation or self.training):
            self.cfg_sim_status.setText(
                "Simulation settings are only used in simulation and training modes.")
            return
        if self.cfg_sim_upper.value() <= self.cfg_sim_mt.value():
            self.cfg_sim_status.setText(
                "Upper limit must be above the motor threshold.")
            return
        values = {
            "VIRTUAL_MEP_NOISE_MV": f"{self.cfg_sim_noise.value():g}",
            "VIRTUAL_MEP_TRIAL_VARIABILITY":
                "true" if self.cfg_sim_trial.isChecked() else "false",
            "VIRTUAL_MEP_MT": f"{self.cfg_sim_mt.value():g}",
            "VIRTUAL_MEP_UPPER_LIMIT": f"{self.cfg_sim_upper.value():g}",
            "VIRTUAL_MEP_EFIELD_SCALE": f"{self.cfg_sim_scale.value():g}",
        }
        try:
            self._config_store.write(values)
        except OSError as e:
            self.cfg_sim_status.setText(
                f"Could not write {self._config_store.path}: {e}")
            return
        self.cfg_sim_status.setText(
            "Saved simulation settings; restart NeuroPilot to apply.")

    def on_sim_reload(self):
        self.on_config_reload()
        self.cfg_sim_status.setText("Reloaded from .env.")

    # ── Config › Study ─────────────────────────────────────────────────
    def _study_dict(self):
        """Protocol values carried by a study profile."""
        return {
            "fit_fun": self.cfg_fit_function.currentText(),
            "map_elms": self.cfg_subsampling.value(),
            "efield_mode": self.cfg_efield_mode.currentText(),
            "pulse_shape": self.cfg_pulse_shape.currentText(),
            "n_repetitions": self.cfg_reps.value(),
            "min_isi": self.cfg_isi.value(),
            "amplitude": self.cfg_amplitude.value(),
            "sampling_rate": self.cfg_sampling_rate.value(),
            "cutoff_freq": self.cfg_cutoff.value(),
            "tms_pulse_time": self.cfg_pulse_time.value(),
            "start_mep": self.cfg_mep_start.value(),
            "end_mep": self.cfg_mep_end.value(),
            "emg_channels": self.cfg_emg_channels.text().strip(),
        }

    def _fill_study_widgets(self, values):
        def text(combo, key):
            if key in values:
                combo.setCurrentText(str(values[key]))

        def number(spin, key):
            try:
                spin.setValue(int(values[key]))
            except (KeyError, TypeError, ValueError):
                pass

        text(self.cfg_fit_function, "fit_fun")
        number(self.cfg_subsampling, "map_elms")
        text(self.cfg_efield_mode, "efield_mode")
        text(self.cfg_pulse_shape, "pulse_shape")
        number(self.cfg_reps, "n_repetitions")
        number(self.cfg_isi, "min_isi")
        number(self.cfg_amplitude, "amplitude")
        number(self.cfg_sampling_rate, "sampling_rate")
        number(self.cfg_cutoff, "cutoff_freq")
        number(self.cfg_pulse_time, "tms_pulse_time")
        number(self.cfg_mep_start, "start_mep")
        number(self.cfg_mep_end, "end_mep")
        if "emg_channels" in values:
            self.cfg_emg_channels.setText(str(values["emg_channels"]))

    def _default_study_path(self):
        root = self.cfg_root_folder.text().strip() or os.path.expanduser("~")
        return os.path.join(root, "study.yaml")

    def on_study_save(self):
        path = self._file_dialog("Save study profile",
                                 self._default_study_path(),
                                 "YAML files (*.yaml *.yml)", save=True)
        if not path:
            return
        if not path.lower().endswith((".yaml", ".yml")):
            path += ".yaml"
        try:
            with open(path, "w") as f:
                yaml.safe_dump(self._study_dict(), f, sort_keys=False,
                               default_flow_style=False)
        except OSError as e:
            self.cfg_study_status.setText(f"Could not write {path}: {e}")
            return
        self.cfg_study_status.setText(f"Saved {os.path.basename(path)}")

    def on_study_load(self):
        path = self._file_dialog("Load study profile",
                                 self._default_study_path(),
                                 "YAML files (*.yaml *.yml)", save=False)
        if not path:
            return
        try:
            with open(path) as f:
                values = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as e:
            self.cfg_study_status.setText(f"Could not read {path}: {e}")
            return
        if not isinstance(values, dict):
            self.cfg_study_status.setText("Not a study profile (expected a mapping).")
            return
        self._fill_study_widgets(values)
        self.cfg_study_status.setText(
            f"Loaded {os.path.basename(path)} — 'Apply to session' uses it now.")

    def on_study_apply(self):
        """Push the study values into the live controls."""
        if self._run_in_progress():
            self.cfg_study_status.setText(
                "Not applied: a mapping session is running (finish it first).")
            return
        values = self._study_dict()
        applied, deferred = [], []
        try:
            self.fitFunctionComboBox.setCurrentText(values["fit_fun"])
            self.sampling_spinBox.setValue(int(values["map_elms"]))
            self.pulseShapeComboBox.setCurrentText(values["pulse_shape"])
            self.n_repetitions_spinBox.setValue(int(values["n_repetitions"]))
            self.min_interval_spinBox.setValue(int(values["min_isi"]))
            self.slider1_spinbox1(int(values["amplitude"]))
            applied.append("mapping/stimulation")
        except (AttributeError, ValueError) as e:
            print(f"[WARN] study apply: {e}")

        mode = values["efield_mode"].lower()
        if mode.startswith("online") and self.online_efield_btn.isEnabled():
            self.online_efield_btn.setChecked(True)
            applied.append("online E-field")
        elif ((mode.startswith("interp") or mode.startswith("surrogate"))
                and self.surrogate_efield_btn.isEnabled()):
            self.surrogate_efield_btn.setChecked(True)
            applied.append("interpolated E-field")
        elif mode.startswith("pre") and self.offline_efield_btn.isEnabled():
            self.offline_efield_btn.setChecked(True)
            applied.append("precomputed E-field")

        deferred.append("MEP windows and EMG channels (restart)")
        self.cfg_study_status.setText(
            "Applied: " + ", ".join(applied or ["nothing"]) +
            " · needs restart: " + ", ".join(deferred))

    # ── Config › Subject ───────────────────────────────────────────────
    def _on_config_page_changed(self, index):
        if self.cfg_tabs.widget(index) is getattr(self, "cfg_tab_subject", None):
            self._refresh_subject_summary()
        elif self.cfg_tabs.widget(index) is getattr(self, "cfg_tab_simulation", None):
            self._refresh_simulation_summary()

    def _refresh_simulation_summary(self):
        box = getattr(self, "cfg_sim_sources", None)
        if box is None:
            return
        channels = self.cfg_emg_channels.text().strip() or "not set"
        sources_path = self.emg_config_label.text().strip()
        sources = os.path.basename(sources_path) if sources_path else "not set"
        box.setToolTip(sources_path)
        box.setPlainText(
            f"Channels:    {channels}\n"
            f"EMG sources: {sources}")

    def _refresh_subject_summary(self):
        box = getattr(self, "cfg_subject_summary", None)
        if box is None:
            return
        rows = [
            ("Project", self.project_name_edit.text().strip() or "(untitled)"),
            ("Head mesh", self.loadmeshlabel.text().strip() or "—"),
            ("ROI surface", self.loadroilabel.text().strip() or "—"),
            ("Coil model", os.path.basename(self.coilspathlineedit.text().strip()) or "—"),
            ("Placements", self.loadplacementlabel.text().strip() or "—"),
            ("Target order", self.target_order_LineEdit.text().strip() or "—"),
            ("E-field library", self.load_e_matrix_label.text().strip() or "—"),
            ("Interpolated library", self.surrogate_library_label.text().strip() or "—"),
            ("Results file", self.savePathLineEdit.text().strip() or "—"),
            ("EMG sources", self.emg_config_label.text().strip() or "—"),
        ]
        box.setPlainText("\n".join(f"{name:<16}{value}" for name, value in rows))
        self._refresh_simulation_summary()

    def _apply_config_mode(self):
        """Show the active mode and grey out the settings it does not use."""
        manual = bool(self.controller is not None and getattr(self.controller, "manual", False))
        simulated = bool(self.simulation) and not manual
        training = bool(getattr(self, "training", False))
        virtual_emg = simulated or training
        mode = ("Training" if training else
                ("Manual" if manual else ("Simulated" if simulated else "Real")))
        badge = getattr(self, "cfg_mode_badge", None)
        if badge is None:
            return
        theme = getattr(self, "_theme", {})
        palette = {
            "Simulated": (theme.get("accent_soft", "#FEF3E2"),
                          theme.get("accent_dark", "#B45309")),
            "Real": (theme.get("ok_soft", "#E8F5EC"),
                     theme.get("ok", "#1B7F3B")),
            "Manual": (theme.get("hover", "#EEF0F2"),
                       theme.get("soft", "#3C444D")),
            "Training": (theme.get("accent_soft", "#FEF3E2"),
                         theme.get("accent_dark", "#B45309")),
        }[mode]
        badge.setText(mode)
        badge.setStyleSheet(
            f"QLabel[role=\"badge\"] {{ background: {palette[0]};"
            f" color: {palette[1]}; border-radius: 9px;"
            " padding: 2px 10px; }")

        # Robot: only the simulator uses the model selector.
        self.cfg_robot_type.setEnabled(simulated)
        self.cfg_tms_path.setEnabled(not simulated)
        if simulated:
            self.cfg_robot_hint.setText("Virtual twin model used by `neuropilot sim`.")
        elif training:
            self.cfg_robot_hint.setText(
                "Training mode: the operator moves the coil; no robot is used.")
        elif manual:
            self.cfg_robot_hint.setText("Manual mode: no robot is used.")
        else:
            self.cfg_robot_hint.setText("Real robot: configured in tms-robot-control;"
                                        " the pipeline reaches it through the relay above.")

        # Stimulator serial ports: hardware only.
        for widget in (self.cfg_stim_port, self.cfg_stim_ttl):
            widget.setEnabled(not simulated)
        self.cfg_stim_hint.setText(
            "Simulation uses the virtual stimulator."
            if simulated else
            ("Training fires the real stimulator." if training else
             "Serial + TTL ports of the MagVenture."))

        # EMG computer credentials: hardware only.
        for widget in (self.cfg_emg_ip, self.cfg_emg_user, self.cfg_emg_password):
            widget.setEnabled(not virtual_emg)
        self.cfg_emg_hint.setText(
            "Training EMG: a synthetic trace driven by the E-field."
            if training else
            ("Simulated EMG: the channel names label the plots and the results."
             if simulated else
             "SMB share on the EMG computer (Digitimer D360 -> CED 1401)."))

        # Simulation page: used by both the virtual twin and training mode.
        for attr in ("cfg_sim_noise", "cfg_sim_trial", "cfg_sim_mt",
                     "cfg_sim_upper", "cfg_sim_scale", "cfg_sim_save_btn"):
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.setEnabled(virtual_emg)
        hint = getattr(self, "cfg_sim_hint", None)
        if hint is not None:
            hint.setText(
                "Used by the virtual EMG in simulation and training modes; "
                "restart to apply."
                if virtual_emg else
                "Simulation and training only; these values are ignored in "
                "real and manual modes.")

    # ── Mapping results panel ───────────────────────────────────────────
    def _setup_mapping_panel(self):
        table = getattr(self, "results_table", None)
        if table is not None:
            table.cellClicked.connect(self.on_results_row_clicked)
            table.verticalHeader().setVisible(False)
            header = table.horizontalHeader()
            header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
            header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
            table.setMinimumHeight(90)
            table.setMaximumHeight(260)
        self._rebuild_placement_metric_combo()

        view = getattr(self, "widget_3d_viewer", None)
        if view is not None:
            view.element_picked.connect(self.on_element_picked)
            view.placement_picked.connect(self.on_placement_picked)
            view.radio_head.toggled.connect(self._update_results_controls)
            view.radio_roi.toggled.connect(self._update_results_controls)

        for attr, slot in (("placement_metric_combo", self.on_placement_metric_changed),
                           ("show_placements_chk", self.on_placement_options_changed),
                           ("show_coil_chk", self.on_placement_options_changed),
                           ("show_path_chk", self.on_placement_options_changed),
                           ("mark_best_btn", self.on_mark_best),
                           ("clear_marks_btn", self.on_clear_marks),
                           ("screenshot_btn", self.on_screenshot),
                           ("export_btn", self.on_export_results)):
            widget = getattr(self, attr, None)
            if widget is None:
                continue
            if isinstance(widget, QtWidgets.QComboBox):
                widget.currentIndexChanged.connect(slot)
            elif isinstance(widget, QtWidgets.QCheckBox):
                widget.toggled.connect(slot)
            else:
                widget.clicked.connect(slot)

        # Sync the viewer with the checkbox defaults in the .ui.
        self.on_placement_options_changed()
        self._size_choice_popups()
        self._update_results_controls()
        self._set_selection_info("Hover the mesh for R² values; click to pin.\n"
                                 "On the head view, hover a coil placement for trial data.")

    def _update_results_controls(self, *_):
        """Placement controls only apply to the head view, the best-R² mark
        only to the ROI view."""
        view = getattr(self, "widget_3d_viewer", None)
        if view is None:
            return
        head = view.radio_head.isChecked()
        for attr in ("placement_metric_combo", "show_placements_chk",
                     "show_coil_chk", "show_path_chk"):
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.setEnabled(head)
        mark = getattr(self, "mark_best_btn", None)
        if mark is not None:
            mark.setEnabled(not head)

    def _rebuild_placement_metric_combo(self):
        combo = getattr(self, "placement_metric_combo", None)
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        for i, name in enumerate(self._emg_display_names):
            combo.addItem(f"MEP size — {name}", ("mep", f"ADC {i}"))
        combo.addItem("Trial id", ("trial", None))
        combo.addItem("Aim error", ("aim", None))
        combo.blockSignals(False)
        self.on_placement_metric_changed()

    def on_placement_metric_changed(self, *_):
        combo = getattr(self, "placement_metric_combo", None)
        view = getattr(self, "widget_3d_viewer", None)
        if combo is None or view is None:
            return
        data = combo.currentData()
        if isinstance(data, (tuple, list)) and len(data) == 2:
            view.set_placement_metric(data[0], data[1])

    def on_placement_options_changed(self, *_):
        view = getattr(self, "widget_3d_viewer", None)
        if view is None:
            return
        view.set_placement_options(
            show=self.show_placements_chk.isChecked(),
            handles=self.show_coil_chk.isChecked(),
            path=self.show_path_chk.isChecked())

    def update_mapping_results(self, bundle):
        """Called by the controller after every collected pulse."""
        if not bundle:
            return
        self._mapping_placements = bundle.get("placements", [])
        channels = bundle.get("channels") or []
        view = getattr(self, "widget_3d_viewer", None)
        if view is not None:
            view.set_mapping_results(self._mapping_placements, channels)
        scores = bundle.get("scores")
        if scores:
            self.update_mesh_coloring(scores)

    def _channel_keys(self):
        keys = list(self._mapping_scores.keys())
        keys.sort(key=lambda k: int(k.split()[-1]) if k.split()[-1].isdigit() else 99)
        return keys

    def _display_name(self, key):
        try:
            idx = int(key.split()[-1])
        except (ValueError, IndexError):
            return key
        if 0 <= idx < len(self._emg_display_names):
            return self._emg_display_names[idx]
        return key

    def _refresh_results_table(self):
        table = getattr(self, "results_table", None)
        if table is None:
            return
        keys = self._channel_keys()
        self._table_keys = keys
        table.setRowCount(len(keys))
        for row, key in enumerate(keys):
            scores = self._mapping_scores.get(key)
            best, element = (0.0, None) if scores is None or len(scores) == 0 else \
                (float(np.max(scores)), int(np.argmax(scores)))
            values = [self._display_name(key),
                      "—" if element is None else f"{best:.3f}",
                      "—" if element is None else str(element)]
            for col, text in enumerate(values):
                item = table.item(row, col)
                if item is None:
                    item = QtWidgets.QTableWidgetItem()
                    table.setItem(row, col, item)
                item.setText(text)
        summary = getattr(self, "results_summary", None)
        if summary is not None:
            if not keys:
                summary.setText("No R² map yet — needs at least three pulses.")
            elif not any(len(np.asarray(self._mapping_scores[k])) for k in keys):
                summary.setText("No R² map yet — needs at least three pulses.")
            else:
                best_key = max(keys, key=lambda k: float(np.max(self._mapping_scores[k]))
                               if len(self._mapping_scores[k]) else 0.0)
                scores = self._mapping_scores[best_key]
                prefix = self._results_prefix(self._mapping_placements)
                summary.setText(
                    f"{prefix}best {self._display_name(best_key)} "
                    f"R² {float(np.max(scores)):.3f} "
                    f"(element {int(np.argmax(scores))})")
        # Size the table to its rows (the design height does not scale with
        # the fonts, so a fixed height would scroll with only three rows).
        table.resizeRowsToContents()
        header_h = table.horizontalHeader().height()
        rows_h = sum(table.rowHeight(r) for r in range(len(keys))) if keys else 0
        table.setFixedHeight(min(340, header_h + rows_h
                                 + 2 * table.frameWidth() + 8))

    @staticmethod
    def _results_prefix(placements):
        """Pulse count for the results summary, noting a mixed-mode session."""
        count = len(placements or [])
        if not count:
            return ""
        online = sum(1 for rec in placements if rec.get("e_field_mode") == "online")
        text = f"{count} pulses"
        if 0 < online < count:
            text += f" ({online} online)"
        return text + " · "

    def _set_selection_info(self, text):
        box = getattr(self, "selection_info", None)
        if box is not None:
            box.setPlainText(text)

    @staticmethod
    def _kv(label, value, width=10):
        return f"{label:<{width}}{value}"

    def _format_scores(self, scores):
        lines = []
        for key in self._channel_keys():
            value = (scores or {}).get(key)
            if value is None:
                continue
            lines.append(self._kv(self._display_name(key), f"R²   {value:.3f}", width=8))
        return lines

    def on_element_picked(self, info):
        if info.get("click"):
            self._selection_pinned = True
        elif self._selection_pinned:
            return
        x, y, z = info.get("xyz", (0.0, 0.0, 0.0))
        head = f"ELEMENT {info.get('element')}"
        if self._selection_pinned:
            head += "   ·   pinned"
        lines = [head,
                 self._kv("xyz", f"{x:7.1f}, {y:7.1f}, {z:7.1f}  mm", width=8)]
        lines += self._format_scores(info.get("scores")) or [self._kv("R²", "not computed yet")]
        self._set_selection_info("\n".join(lines))

    def on_placement_picked(self, info):
        if info.get("click"):
            self._selection_pinned = True
        elif self._selection_pinned:
            return
        rec = info.get("record") or {}
        pos = rec.get("position") or (0.0, 0.0, 0.0)
        head = f"TRIAL {rec.get('trial')}  ·  pulse {rec.get('pulse_index')}"
        if self._selection_pinned:
            head += "   ·   pinned"
        lines = [head,
                 self._kv("xyz", f"{pos[0]:7.1f}, {pos[1]:7.1f}, {pos[2]:7.1f}  mm"),
                 self._kv("aim error", f"{rec.get('aim_error_mm', 0.0):6.1f}  mm"),
                 self._kv("intensity", f"{rec.get('intensity', 0):6.0f}  %MSO")]
        if rec.get("e_field_mode"):
            # Which E-field source this pulse used (it can change mid-run).
            lines.append(self._kv("E-field", rec["e_field_mode"]))
        for key, value in (rec.get("mep") or {}).items():
            if value is not None:
                lines.append(self._kv(f"MEP {self._display_name(key)}", f"{value:6.2f}  mV"))
        self._set_selection_info("\n".join(lines))

    def on_mark_best(self, *_):
        self._mark_best_for(self._selected_score_key())

    def on_results_row_clicked(self, row, column):
        """Clicking a row marks that channel's best element."""
        keys = getattr(self, "_table_keys", [])
        if 0 <= row < len(keys):
            self._mark_best_for(keys[row])

    def _mark_best_for(self, key):
        view = getattr(self, "widget_3d_viewer", None)
        if view is None:
            return
        element = view.mark_best_element(key)
        if element is None:
            self._set_selection_info("No R² map yet — collect at least three pulses.")
            return
        scores = self._mapping_scores.get(key)
        best = float(np.max(scores)) if scores is not None else float("nan")
        mesh = view.current_mesh
        centre = None
        if mesh is not None and element < mesh.n_cells:
            centre = mesh.cell_centers().points[element]
        lines = [f"BEST R²   ·   {self._display_name(key)}   ·   pinned",
                 self._kv("element", str(element), width=8),
                 self._kv("R²", f"{best:.3f}", width=8)]
        if centre is not None:
            lines.append(self._kv("xyz", f"{centre[0]:7.1f}, {centre[1]:7.1f}, "
                                         f"{centre[2]:7.1f}  mm", width=8))
        self._selection_pinned = True
        self._set_selection_info("\n".join(lines))

    def _selected_score_key(self):
        combo = getattr(self, "placement_metric_combo", None)
        data = combo.currentData() if combo is not None else None
        if isinstance(data, (tuple, list)) and len(data) == 2 and data[0] == "mep":
            return data[1]
        keys = self._channel_keys()
        return keys[0] if keys else None

    def on_clear_marks(self, *_):
        view = getattr(self, "widget_3d_viewer", None)
        if view is not None:
            view.clear_marks()
        self._selection_pinned = False
        self._set_selection_info("Hover the mesh for R² values; click to pin.")

    def on_screenshot(self, *_):
        view = getattr(self, "widget_3d_viewer", None)
        if view is None:
            return
        start = os.path.expanduser("~")
        if self.savePathLineEdit.text().strip():
            start = os.path.dirname(self.savePathLineEdit.text().strip()) or start
        path = self._file_dialog("Save 3D view screenshot", start,
                                 "PNG image (*.png)", save=True)
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            written = view.screenshot(path)
        except Exception as e:
            self._set_selection_info(f"Screenshot failed: {e}")
            return
        if written is False:
            # QImage.save() only returns False on a bad path; without this the
            # GUI happily reports a screenshot that does not exist.
            self._set_selection_info(f"Screenshot failed: could not write\n  {path}")
        else:
            self._set_selection_info(f"Screenshot saved\n  {path}")

    def on_export_results(self, *_):
        """Write the R² table (element coordinates + scores) and the placement
        log (coil poses, MEPs, aim errors) next to a chosen base file name."""
        start = os.path.expanduser("~")
        if self.savePathLineEdit.text().strip():
            start = os.path.dirname(self.savePathLineEdit.text().strip()) or start
        base = self._file_dialog("Export mapping results (CSV)", start,
                                 "CSV files (*.csv)", save=True)
        if not base:
            return
        base = re.sub(r"\.csv$", "", base, flags=re.IGNORECASE)
        written = []
        try:
            if self._mapping_scores:
                path = base + "_roi_r2.csv"
                self._write_roi_csv(path)
                written.append(path)
            if self._mapping_placements:
                path = base + "_placements.csv"
                self._write_placements_csv(path)
                written.append(path)
            readme = base + "_README.txt"
            self._write_export_readme(readme, base)
            written.append(readme)
            self._set_selection_info("Exported\n" + "\n".join(f"  {p}" for p in written))
        except Exception as e:
            self._set_selection_info(f"Export failed: {e}")

    def _write_roi_csv(self, path):
        import csv
        view = getattr(self, "widget_3d_viewer", None)
        mesh = getattr(view, "mesh_roi", None) if view is not None else None
        centres = mesh.cell_centers().points if mesh is not None else None
        keys = self._channel_keys()
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["element", "x_mm", "y_mm", "z_mm"]
                            + [f"r2_{self._display_name(k)}" for k in keys])
            n = max((len(self._mapping_scores.get(k, [])) for k in keys), default=0)
            for element in range(n):
                xyz = centres[element] if centres is not None and element < len(centres) \
                    else (float("nan"),) * 3
                row = [element, f"{xyz[0]:.3f}", f"{xyz[1]:.3f}", f"{xyz[2]:.3f}"]
                row += [f"{float(self._mapping_scores[k][element]):.5f}"
                        if element < len(self._mapping_scores.get(k, [])) else ""
                        for k in keys]
                writer.writerow(row)

    def _write_export_readme(self, path, base=None):
        """Column dictionary next to the exported tables (units + frames)."""
        base_name = os.path.basename(base if base is not None else path)
        names = ", ".join(self._display_name(k) for k in self._channel_keys()) or "—"
        with open(path, "w") as f:
            f.write(
                "NeuroPilot mapping export\n"
                "========================\n\n"
                f"Channels: {names}\n"
                "Coordinates are in mm, SimNIBS head space.\n\n"
                f"{base_name}_roi_r2.csv\n"
                "  element        ROI triangle index (0-based, same order as the E-field columns)\n"
                "  x_mm/y_mm/z_mm triangle centroid\n"
                "  r2_<channel>   regression R^2 per triangle (NaN/empty if not fitted)\n\n"
                f"{base_name}_placements.csv\n"
                "  trial, pulse_index, target_index  acquisition order / pulse / planned target\n"
                "  x/y/z_realized  coil centre actually used (mm)\n"
                "  rota/rotb/rotc_realized  coil orientation, Euler xyz degrees\n"
                "  x/y/z_target    planned coil centre (mm)\n"
                "  aim_error_mm    |realized - target| (mm)\n"
                "  intensity_pctMSO  stimulator output\n"
                "  pressure        force sensor reading at stimulation\n"
                "  mep_<channel>_mV peak-to-peak MEP amplitude\n")

    def _write_placements_csv(self, path):
        import csv
        keys = self._channel_keys()
        header = ["trial", "pulse_index", "target_index",
                  "x_realized", "y_realized", "z_realized",
                  "rota_realized", "rotb_realized", "rotc_realized",
                  "x_target", "y_target", "z_target",
                  "aim_error_mm", "intensity_pctMSO", "pressure",
                  "e_field_mode"]
        header += [f"mep_{self._display_name(k)}_mV" for k in keys]
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for rec in self._mapping_placements:
                pos, rot = rec.get("position"), rec.get("rotation")
                tpos, trot = rec.get("target_position"), rec.get("target_rotation")
                row = [rec.get("trial"), rec.get("pulse_index"), rec.get("target_index")]
                row += [f"{v:.3f}" for v in pos] if pos else ["", "", ""]
                row += [f"{v:.2f}" for v in rot] if rot else ["", "", ""]
                row += [f"{v:.3f}" for v in tpos] if tpos else ["", "", ""]
                row += [_fmt_number(rec.get("aim_error_mm"), ".2f"),
                        _fmt_number(rec.get("intensity"), ""),
                        _fmt_number(rec.get("pressure"), ""),
                        rec.get("e_field_mode") or ""]
                mep = rec.get("mep") or {}
                row += ["" if mep.get(k) is None else f"{mep[k]:.4f}" for k in keys]
                writer.writerow(row)

    def _install_ui_assets(self):
        # The generated PNGs are referenced by the theme's style sheet, which
        # apply_theme() installs once the window is complete.
        self._ui_icons = _control_ui_icons()

    def _update_file_infos(self):
        """Show a short summary next to each configured project file."""
        def set_info(name, text):
            lbl = getattr(self, name, None)
            if lbl is not None:
                lbl.setText(text or "")

        def signature(path):
            """Cheap change detector: a rewritten file must not keep its old
            summary after the user re-runs a preprocessing script."""
            try:
                stat = os.stat(path)
                return (stat.st_mtime_ns, stat.st_size)
            except OSError:
                return None

        def cached(path, key, computer):
            cache_key = (path, key, signature(path))
            entry = self._info_cache.get(cache_key)
            if entry is not None:
                return entry
            try:
                entry = computer(path)
            except Exception as e:
                entry = f"unreadable ({type(e).__name__})"
            self._info_cache[cache_key] = entry
            return entry

        def h5_shape(fn, dataset, fmt):
            import h5py
            with h5py.File(fn, "r") as f:
                ids = dataset(f)
                return fmt(ids)

        # head mesh: a SimNIBS .msh read is slow -> worker thread
        mesh_fn = self.loadmeshlabel.text().strip()
        if mesh_fn.lower().endswith(".msh") and os.path.isfile(mesh_fn):
            sig = signature(mesh_fn)
            active = self._load_current.get("head")
            if (active and active.get("path") == mesh_fn
                    and active.get("signature") == sig):
                if active.get("pending"):
                    set_info("info_mesh", "loading...")
                else:
                    set_info("info_mesh",
                             self._info_cache.get((mesh_fn, "mesh", sig), ""))
            else:
                pending = self._info_cache.get((mesh_fn, "mesh_pending", sig))
                done = self._info_cache.get((mesh_fn, "mesh", sig))
                if done is not None:
                    set_info("info_mesh", done)
                elif pending is None:
                    self._info_cache[(mesh_fn, "mesh_pending", sig)] = True
                    def _mesh_worker():
                        try:
                            from simnibs import mesh_io
                            m = mesh_io.read_msh(mesh_fn)
                            n_tet = int((m.elm.elm_type == 4).sum())
                            n_tri = int((m.elm.elm_type == 2).sum())
                            text = f"{n_tet:,} tets · {n_tri:,} tris"
                        except Exception as e:
                            text = f"unreadable ({type(e).__name__})"
                        self._info_cache[(mesh_fn, "mesh", sig)] = text
                        self._emit_file_info("info_mesh", text)
                    import threading
                    threading.Thread(target=_mesh_worker, daemon=True).start()
        else:
            active = self._load_current.get("head")
            sig = signature(mesh_fn) if mesh_fn else None
            if (mesh_fn and active and active.get("path") == mesh_fn
                    and active.get("signature") == sig):
                if active.get("pending"):
                    set_info("info_mesh", "loading...")
                else:
                    set_info("info_mesh",
                             self._info_cache.get((mesh_fn, "mesh", sig), ""))
            elif (mesh_fn.lower().endswith((".hdf5", ".h5"))
                    and os.path.isfile(mesh_fn)):
                # Light HDF5 header read: show the triangle count while the
                # full mesh (and its display decimation) is still loading.
                done = self._info_cache.get((mesh_fn, "mesh", sig))
                if done is not None:
                    set_info("info_mesh", done)
                else:
                    try:
                        import h5py
                        with h5py.File(mesh_fn, "r") as f:
                            n_tri = f["mesh/elm/triangle_number_list"].shape[0]
                        text = f"{n_tri:,} triangles"
                    except Exception as e:
                        text = f"unreadable ({type(e).__name__})"
                    self._info_cache[(mesh_fn, "mesh", sig)] = text
                    set_info("info_mesh", text)
            else:
                set_info("info_mesh", "")

        roi_fn = self.loadroilabel.text().strip()
        set_info("info_roi", cached(roi_fn, "roi", lambda fn: h5_shape(
            fn, lambda f: f["mesh/elm/triangle_number_list"].shape[0],
            lambda n: f"{n:,} triangles")) if roi_fn and os.path.isfile(roi_fn) else "")

        to_fn = self.target_order_LineEdit.text().strip()
        set_info("info_target_order", cached(to_fn, "to", lambda fn: (
            lambda lines: f"{len([l for l in lines if l.strip()]):,} placements")(
            open(fn).read().splitlines())) if to_fn and os.path.isfile(to_fn) else "")

        pl_fn = self.loadplacementlabel.text().strip()
        def placements_info(fn):
            import h5py
            with h5py.File(fn, "r") as f:
                if "centers" in f:
                    n = f["centers"].shape[0]
                elif "matsimnibs" in f:
                    n = f["matsimnibs"].shape[-1]
                else:
                    n = len(f.keys())
            return f"{n:,} placements"
        set_info("info_placements", cached(pl_fn, "pl", placements_info)
                 if pl_fn and os.path.isfile(pl_fn) else "")

        e_fn = self.load_e_matrix_label.text().strip()
        def efield_info(fn):
            import h5py
            with h5py.File(fn, "r") as f:
                if "E_mag" in f:
                    a, b = f["E_mag"].shape
                    return f"{a:,} × {b:,} placements × elements"
                return "no E_mag dataset"
        set_info("info_efield", cached(e_fn, "e", efield_info)
                 if e_fn and os.path.isfile(e_fn) else "")

        coil_fn = self.coilspathlineedit.text().strip()
        if coil_fn and os.path.isfile(coil_fn):
            sig = signature(coil_fn)
            done = self._info_cache.get((coil_fn, "coil", sig))
            pending = self._info_cache.get((coil_fn, "coil_pending", sig))
            if done is not None:
                set_info("info_coil", done)
            elif pending is None:
                self._info_cache[(coil_fn, "coil_pending", sig)] = True
                def _coil_worker():
                    # SimNIBS knows the model's own brand/name (a .ccd header
                    # carries them); the import is slow, hence the thread.
                    try:
                        from simnibs.simulation.tms_coil.tms_coil import TmsCoil
                        coil = TmsCoil.from_file(coil_fn)
                        text = " ".join(x for x in (coil.brand, coil.name) if x)
                        text = text or os.path.basename(coil_fn)
                    except Exception:
                        text = os.path.basename(coil_fn)
                    self._info_cache[(coil_fn, "coil", sig)] = text
                    self._emit_file_info("info_coil", text)
                import threading
                threading.Thread(target=_coil_worker, daemon=True).start()
        else:
            set_info("info_coil", "")

        emg_fn = self.emg_config_label.text().strip()
        def emg_info(fn):
            with open(fn) as f:
                data = yaml.safe_load(f) or {}
            sources = data.get("sources", data) if isinstance(data, dict) else data
            return f"{len(sources)} sources" if isinstance(sources, list) else ""
        set_info("info_emg", cached(emg_fn, "emg", emg_info)
                 if emg_fn and os.path.isfile(emg_fn) else "")

        res_fn = self.savePathLineEdit.text().strip()
        if res_fn and os.path.isfile(res_fn):
            kb = max(1, os.path.getsize(res_fn) // 1024)
            self.overwrite_results_chk.setToolTip(
                f"The results file exists ({kb} KB). Uncheck to keep it and "
                "write a timestamped copy instead.")
        elif res_fn:
            self.overwrite_results_chk.setToolTip(
                "The configured results file does not exist yet.")
        else:
            self.overwrite_results_chk.setToolTip("")

    # ── Project file state ─────────────────────────────────────────────────
    def _on_overwrite_results_changed(self, checked):
        if self.controller is not None:
            self.controller.set_overwrite_results(bool(checked))

    def _mark_project_dirty(self, *_):
        if not getattr(self, "_project_ready", False) or self._project_loading:
            return
        self._save_session_cache()
        if not self._project_dirty:
            self._project_dirty = True
            self._update_project_label()

    def _update_project_label(self):
        """Render the project name field: 'untitled project' placeholder when
        no file is associated, the stored name (or file name) otherwise, bold
        while there are unsaved changes."""
        edit = self.project_name_edit
        font = edit.font()
        if self._project_file:
            name = edit.text().strip() or os.path.basename(self._project_file)
            if edit.text().strip() != name:
                edit.setText(name)
            font.setBold(self._project_dirty)
            font.setItalic(False)
            if self._project_dirty:
                edit.setToolTip(f"Unsaved changes — Save updates\n{self._project_file}")
            else:
                edit.setToolTip(self._project_file)
        else:
            font.setBold(False)
            font.setItalic(True)
            edit.setToolTip("Project name (stored in the project file on Save)")
        edit.setFont(font)

    # ── Proportional resizing ──────────────────────────────────────────────
    @staticmethod
    def _is_layout_managed(w):
        """True when a QLayout positions this widget (scaling its geometry
        would fight the layout). Tab/stack pages are excluded: the stacked
        container positions them, but their geometry still must scale."""
        p = w.parentWidget()
        if p is None:
            return False
        # Tab/stack pages (and the tab bar's corner widget) are positioned
        # by the stacked container itself.  Rescaling their geometry on top
        # of that double-applied the window scale: the pages grew past the
        # window during a resize and pushed the page content out of view.
        if isinstance(p, (QtWidgets.QTabWidget, QtWidgets.QStackedWidget)):
            return True
        # Unbound call: MeshWidget shadows .layout with a QVBoxLayout attribute.
        lay = QtWidgets.QWidget.layout(p)
        if lay is None:
            return False
        try:
            return lay.indexOf(w) != -1
        except RuntimeError:
            return False

    # Base font sizes in pixels per widget class (checked in order). These
    # scale with the window in _rescale, so the UI stays readable at any
    # window size, including high-DPI screens.
    FONT_BASE_PX = (
        (QtWidgets.QLabel, 16),
        (QtWidgets.QGroupBox, 16),
        (QtWidgets.QTabBar, 16),
        (QtWidgets.QAbstractButton, 15),
        (QtWidgets.QComboBox, 15),
        (QtWidgets.QSpinBox, 15),
        (QtWidgets.QDoubleSpinBox, 15),
        (QtWidgets.QLineEdit, 15),
        (QtWidgets.QWidget, 15),
    )

    @classmethod
    def _base_font_px(cls, widget):
        for klass, px in cls.FONT_BASE_PX:
            if isinstance(widget, klass):
                return px
        return 15

    @classmethod
    def _apply_font_px(cls, widget, px):
        """Set a widget's font size in pixels. Widgets with an inline
        stylesheet ignore setFont (the stylesheet style overrides the widget
        font), so for those a properly selected rule is appended to their
        stylesheet instead — a bare declaration outside a rule block would
        be invalid CSS and silently ignored."""
        import re
        px = max(9, px)
        f = widget.font()
        f.setPixelSize(px)
        widget.setFont(f)
        ss = widget.styleSheet()
        if ss:
            if "font-size" in ss:
                # the stylesheet governs this widget's font size — scale it
                ss = re.sub(r"font-size:\s*\d+px", f"font-size: {max(9, px)}px", ss)
                widget.setStyleSheet(ss)
                return
            # A colour-only stylesheet leaves the size to setFont. Do not
            # append a selector after bare declarations: that is invalid CSS,
            # so Qt drops the declarations (this used to make the relay
            # status fall back to the default colour and font size).
            ss = re.sub(r"\s*/\* neuropilot font scaling \*/\s*\n?\w[\w:]* \{ font-size: \d+px; \}", "", ss)
            ss = re.sub(r"\s*/\* neuropilot font scaling \*/ font-size: \d+px;", "", ss)
            if ss != widget.styleSheet():
                widget.setStyleSheet(ss)

    def _capture_base_rects(self):
        """Record the design-geometry of every absolutely-positioned
        descendant of the central widget; layout-managed widgets reflow
        inside the containers we scale. Font sizes are handled for all
        descendants (geometry management does not affect fonts)."""
        central = self.centralwidget
        fonts = {}
        sheets = {}
        # Pass 1: apply the base fonts everywhere, then let every layout
        # settle — geometry read too early reflects the old (smaller) fonts.
        for w in central.findChildren(QtWidgets.QWidget):
            base_px = self._base_font_px(w)
            fonts[w] = base_px
            sheets[w] = w.styleSheet()  # raw design stylesheet, unscaled
            self._apply_font_px(w, base_px)
        for w in central.findChildren(QtWidgets.QWidget):
            lay = QtWidgets.QWidget.layout(w)
            if lay is not None:
                lay.activate()
        # Pass 2: read the design geometry (the new UI is layout-driven, so
        # this covers only the few absolutely placed widgets).
        rects = {}
        for w in central.findChildren(QtWidgets.QWidget):
            if self._is_layout_managed(w):
                continue
            rects[w] = w.geometry()
        return {"central": central, "size": self._design_size,
                "rects": rects, "fonts": fonts, "sheets": sheets,
                "win_sheet": self.styleSheet()}

    def showEvent(self, event):
        # Capture base geometry once, after the first layout pass has run
        # (a zero-timer fires when the event loop next processes events).
        if self._base_rects is None:
            QtCore.QTimer.singleShot(0, self._capture_base_rects_now)
        QtCore.QTimer.singleShot(0, self._place_target_overlay)
        super().showEvent(event)

    def eventFilter(self, obj, event):
        if (obj is getattr(self, "robot_view_label", None)
                and event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show)):
            QtCore.QTimer.singleShot(0, self._place_target_overlay)
        return super().eventFilter(obj, event)

    def _capture_base_rects_now(self):
        self._base_rects = self._capture_base_rects()
        # Apply the current scale immediately so a window resized before the
        # capture is consistent from the first paint after it.
        self._rescale()
        self._match_relay_card_height()

    def resizeEvent(self, event):
        if getattr(self, "_base_rects", None) is None:
            return
        # Cheap pass on every resize event: geometry only.
        self._rescale_geometry()
        # Re-run the visible page's layout tree immediately: the deferred
        # style pass otherwise lets nested columns (Config in particular)
        # float in stale positions while the drag is in progress.
        page = self.tabWidget.currentWidget()
        if page is not None:
            self._activate_layout_tree(page)
            page.updateGeometry()
        self._place_target_overlay()
        # The tab bar itself is resized by the layout after this event, so
        # place the LED corner once that has settled (otherwise it keeps the
        # old x position and the last LED is clipped).
        QtCore.QTimer.singleShot(0, self._place_tab_corner)
        # Expensive pass (full stylesheet repolish + setFont on every widget):
        # deferred to the next event-loop turn so dragging stays smooth, and
        # skipped entirely when the rounded pixel sizes did not change. A
        # long delay makes the page visibly snap after the drag ends.
        if not getattr(self, "_styles_timer_pending", False):
            self._styles_timer_pending = True
            QtCore.QTimer.singleShot(0, self._apply_styles_if_needed)
        super().resizeEvent(event)

    def _activate_layout_tree(self, widget):
        """Recompute the layouts of one page, including nested cards/tabs.

        A resize changes the page geometry without necessarily invalidating
        the cached item rectangles. Activating a stale layout leaves cards at
        their old width (visible on Connections after a width-only resize), so
        invalidate the whole page first and then activate from the top down.
        """
        layouts = []
        layout = QtWidgets.QWidget.layout(widget)
        if layout is not None:
            layouts.append(layout)
        for child in widget.findChildren(QtWidgets.QWidget):
            child_layout = QtWidgets.QWidget.layout(child)
            if child_layout is not None:
                layouts.append(child_layout)
        for layout in layouts:
            layout.invalidate()
        for layout in layouts:
            layout.activate()

    def _current_scale(self):
        rects = getattr(self, "_base_rects", None)
        if not rects:
            return 1.0
        base_w, base_h = rects["size"]
        if not base_w or not base_h:
            return 1.0
        return min(self.width() / base_w, self.height() / base_h)

    def _file_dialog(self, title, start_folder, name_filter, save=False):
        """Non-native file dialog with a size scaled to the window.

        The static convenience dialogs open with a small default size that
        does not follow the window scaling; a real dialog instance can be
        resized to match. Returns the selected path or "" on cancel.
        """
        dlg = QtWidgets.QFileDialog(self, title, start_folder, name_filter)
        dlg.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        s = self._current_scale()
        dlg.resize(int(1000 * s), int(650 * s))
        if save:
            dlg.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            return dlg.selectedFiles()[0]
        return ""

    def _apply_styles_if_needed(self):
        self._styles_timer_pending = False
        if getattr(self, "_closing", False):
            # A resize one-shot can still fire while the window is closing.
            return
        s = self._current_scale()
        last = getattr(self, "_last_style_scale", None)
        if last is not None and abs(s - last) < 0.04:
            return  # rounded pixel sizes unchanged — skip the expensive pass
        self._last_style_scale = s
        self._rescale_styles(s)
        self._match_relay_card_height()

    def _rescale(self):
        self._rescale_geometry()
        self._rescale_styles(self._current_scale())
        self._last_style_scale = self._current_scale()

    def _rescale_geometry(self):
        s = self._current_scale()
        # Center the scaled content inside the window (letterbox offset).
        ox = (self.width() - self._base_rects["size"][0] * s) / 2
        oy = (self.height() - self._base_rects["size"][1] * s) / 2
        central = self._base_rects["central"]
        stale = []
        for w, base in list(self._base_rects["rects"].items()):
            x, y, ww, hh = base.x(), base.y(), base.width(), base.height()
            try:
                parent = w.parentWidget()
                if parent is central:
                    w.setGeometry(round(x * s + ox), round(y * s + oy),
                                  round(ww * s), round(hh * s))
                else:
                    w.setGeometry(round(x * s), round(y * s),
                                  round(ww * s), round(hh * s))
            except RuntimeError:
                stale.append(w)
        for w in stale:
            self._base_rects["rects"].pop(w, None)

    def _rescale_styles(self, s):
        # Stylesheets scale with the window: every px value in the design
        # stylesheets (font sizes, indicators, grooves, handles, paddings)
        # is multiplied by s. This covers the window-level rules (radio
        # buttons...) and the per-widget rules (sliders, line edits...).
        def scale_px(sheet):
            return re.sub(r"(\d+(?:\.\d+)?)px",
                          lambda m: f"{max(1, round(float(m.group(1)) * s))}px",
                          sheet)

        self.setStyleSheet(scale_px(self._base_rects["win_sheet"]))
        last_scaled = getattr(self, "_last_scaled_sheets", {})
        stale = []
        for w, base_sheet in list(self._base_rects["sheets"].items()):
            try:
                current = w.styleSheet()
            except RuntimeError:
                # A page may have deleted a widget after the base geometry
                # was captured (the About/Config rebuilds do this).  A stale
                # Python wrapper must not crash a resize.
                stale.append(w)
                continue
            previous = last_scaled.get(w)
            if previous is not None and current != previous:
                # A handler replaced this widget's inline style since the
                # last scaling pass (status colour, theme badge, log bed).
                # Take the fresh declaration as the new unscaled base so a
                # later resize or theme change does not restore stale colours.
                base_sheet = current
                self._base_rects["sheets"][w] = base_sheet
            scaled = scale_px(base_sheet) if base_sheet else ""
            try:
                w.setStyleSheet(scaled)
            except RuntimeError:
                stale.append(w)
                continue
            last_scaled[w] = scaled

        for w in stale:
            self._base_rects["sheets"].pop(w, None)
            self._base_rects["fonts"].pop(w, None)
            last_scaled.pop(w, None)

        # Fonts scale with the window for every descendant.
        stale = []
        for w, base_px in list(self._base_rects["fonts"].items()):
            try:
                self._apply_font_px(w, max(9, round(base_px * s)))
            except RuntimeError:
                stale.append(w)
        for w in stale:
            self._base_rects["fonts"].pop(w, None)
            last_scaled.pop(w, None)
        # Remember the post-font sheets: a font-size rewrite is not a new
        # declaration from a handler, so it must not replace the base sheet.
        for w in list(self._base_rects["sheets"]):
            try:
                last_scaled[w] = w.styleSheet()
            except RuntimeError:
                self._base_rects["sheets"].pop(w, None)
                self._base_rects["fonts"].pop(w, None)
                last_scaled.pop(w, None)
        self._last_scaled_sheets = last_scaled

        # Keep the log console readable at every scale. This also caps the
        # robot view above it, so the log card starts higher and grows with
        # the window instead of staying at its minimum height.
        self.finishedsteps.setMinimumHeight(max(80, round(120 * s)))

        # Font and style changes alter size hints; re-activate the layout tree
        # so rows sized from label/font metrics stop clipping at larger scales.
        for widget in self.centralwidget.findChildren(QtWidgets.QWidget):
            lay = QtWidgets.QWidget.layout(widget)
            if lay is not None:
                lay.activate()
        self.centralwidget.updateGeometry()
        self._place_tab_corner()
        self._sync_project_gap()
        self._size_choice_popups()
        self._resize_results_panel(s)
        self._place_target_overlay()
        collision_tab = getattr(self, "collision_tab", None)
        if collision_tab is not None:
            collision_tab.apply_ui_scale(s)

    def efield_mode_name(self):
        """``"Online"`` / ``"Interpolated"`` / ``"Precomputed"`` / None."""
        if self.online_efield_btn.isChecked():
            return "Online"
        if self.surrogate_efield_btn.isChecked():
            return "Interpolated"
        if self.offline_efield_btn.isChecked():
            return "Precomputed"
        return None

    def _apply_efield_mode(self, mode):
        """Select a mode by name; returns True when it was applied now.

        A project can be loaded before its E-field paths are usable (the
        radios stay disabled then).  The name is remembered in
        ``_pending_efield_mode`` and retried as soon as the paths are ready.
        """
        text = str(mode or "").strip().lower()
        if text.startswith("online"):
            button, wanted = self.online_efield_btn, "efield_online"
        elif text.startswith("interp") or text.startswith("surrogate"):
            button, wanted = self.surrogate_efield_btn, "efield_surrogate"
        elif text.startswith("pre"):
            button, wanted = self.offline_efield_btn, "efield_precomputed"
        else:
            return False
        if not button.isEnabled():
            self._pending_efield_mode = text
            return False
        self._pending_efield_mode = None
        if not button.isChecked():
            button.setChecked(True)      # triggers on_efield_mode_changed
        return True

    def on_efield_mode_changed(self):
        """Switch between the E-field sources, also mid-run.

        The pipeline records one E-field row per pulse, so a switch only
        changes which source the *next* pulse uses; the analysis keeps the
        pulses it already has.  The radios stay enabled so the operator can
        always switch back, and each source is initialised once instead of
        once per toggle.
        """
        if not (self.online_efield_btn.isChecked()
                or self.surrogate_efield_btn.isChecked()
                or self.offline_efield_btn.isChecked()):
            return
        if self.surrogate_efield_btn.isChecked():
            mode = "surrogate"
        elif self.online_efield_btn.isChecked():
            mode = "online"
        else:
            mode = "precomputed"
        self._mark_project_dirty()       # the mode is saved with the project
        if self.controller:
            self.controller.efield_mode = mode
            self.controller.online_fem_mgr.online_fem = (mode == "online")
            if mode == "online":
                # The manager finishes on its worker thread; the signal hops
                # the callback back to the GUI thread.
                self.controller.online_fem_mgr.ensure_initialized(
                    callback=self.online_fem_ready.emit)
            elif mode == "surrogate":
                self.controller.surrogate_mgr.ensure_initialized(
                    callback=self.surrogate_library_ready.emit)
        self.efield_mode_selected = True
        self.update_button_states()

    def _reject_path(self, field, error):
        """Clear a path field that points at an unusable file and say why.

        The message goes to the log and to the field's tooltip; nothing
        modal, because this can fire while a project is being restored.
        """
        print(f"[WARN] {error}")
        field.setText("")
        field.setToolTip(str(error))
        self._set_selection_info(f"Ignored file:\n  {error}")

    def _check_paths_ready(self):
        mgr = self.controller.online_fem_mgr if self.controller else None
        s_mgr = self.controller.surrogate_mgr if self.controller else None
        all_set = bool(
                mgr
                and mgr.mesh_fn_msh and os.path.isfile(mgr.mesh_fn_msh)
                and mgr.roi_fn_hdf5
                and mgr.coil_fn
        )
        # The interpolated mode needs the dense library plus the ROI surface
        # the library is verified against (element order / count).
        surrogate_set = bool(
                s_mgr
                and s_mgr.library_fn and os.path.isfile(s_mgr.library_fn)
                and s_mgr.roi_fn_hdf5
        )
        # Both modes stay selectable for the whole session; an in-flight
        # switch is allowed and only affects the following pulses.
        self.online_efield_btn.setEnabled(all_set)
        self.offline_efield_btn.setEnabled(all_set)
        self.surrogate_efield_btn.setEnabled(surrogate_set)
        # Paths may arrive *after* the operator picked a mode (project load,
        # path edit); make sure the source then starts after all.
        pending = getattr(self, "_pending_efield_mode", None)
        if pending:
            self._apply_efield_mode(pending)
        if all_set and self.online_efield_btn.isChecked() and self.controller:
            self.controller.online_fem_mgr.ensure_initialized(
                callback=self.online_fem_ready.emit)
        if (surrogate_set and self.surrogate_efield_btn.isChecked()
                and self.controller):
            self.controller.surrogate_mgr.ensure_initialized(
                callback=self.surrogate_library_ready.emit)
        self.update_button_states()

    def update_button_states(self):
        """Gate the transport buttons: nothing runs before the E-field mode is
        chosen, and only a ready stack may start a mapping."""
        # Finish stays available while an experiment is running so it can
        # always be stopped, even if a system drops out mid-session.
        running = bool(self.controller
                       and getattr(self.controller, "start_of_experiment", None)
                       and not getattr(self.controller, "is_finished", False))
        loads_pending = bool(getattr(self, "_pending_loads", None)) and not running

        if not self.efield_mode_selected:
            for button in (self.start_btn, self.skiptarget, self.back_btn,
                           self.move_coil_up):
                button.setEnabled(False)
            self.finish_btn.setEnabled(running)
            return

        fem_ok = True
        if self.controller:
            mode = getattr(self.controller, "efield_mode", None)
            if mode == "online":
                mgr = self.controller.online_fem_mgr
                # Online mode waits for the solver, but a running experiment
                # stays usable: pulses collected so far keep their fields.
                fem_ok = mgr.is_ready or running
            elif mode == "surrogate":
                s_mgr = self.controller.surrogate_mgr
                fem_ok = s_mgr.is_ready or running
            else:
                # Precomputed mode without a matrix loaded has no E-field.
                fem_ok = self.controller.e_matrix is not None or running

        # Manual mode runs without a robot system: the operator is the robot.
        robot_ok = ((self.controller is not None and getattr(self.controller, "manual", False))
                    or self.robot_ready)

        ready = (not loads_pending and self.relay_ready and robot_ok
                 and self.stim_ready and self.emg_ready and fem_ok)
        for button in (self.start_btn, self.skiptarget, self.back_btn,
                       self.move_coil_up):
            button.setEnabled(ready)
        self.finish_btn.setEnabled(ready or running)
        self._update_efield_hint()

    def _update_efield_hint(self):
        """One line under the E-field radios: what the mode is doing now."""
        label = getattr(self, "efield_hint", None)
        if label is None:
            return
        mgr = getattr(self.controller, "online_fem_mgr", None) if self.controller else None
        s_mgr = getattr(self.controller, "surrogate_mgr", None) if self.controller else None
        online = bool(mgr is not None and mgr.is_online)
        surrogate = bool(getattr(self.controller, "efield_mode", None) == "surrogate"
                         and s_mgr is not None)
        if getattr(self, "_pending_loads", None):
            count = len(self._pending_loads)
            text = ("Loading file..." if count == 1
                    else f"Loading {count} files...")
            role = "busy"
            if label.text() != text:
                label.setText(text)
            if label.property("tone") != role:
                label.setProperty("tone", role)
                label.style().unpolish(label)
                label.style().polish(label)
            return
        if mgr is not None and online:
            if mgr.is_ready:
                text, role = "Online solver ready.", "ok"
            elif getattr(mgr, "initializing", False):
                text = ("Warming up the online solver; "
                        "pulses wait until it is ready.")
                role = "busy"
            else:
                text = "Online solver unavailable — switch to Precomputed."
                role = "error"
        elif surrogate:
            if s_mgr.is_ready:
                text, role = (f"Interpolated library ready "
                              f"({s_mgr.n_placements} placements, guard "
                              f"{s_mgr.surrogate.max_position_distance_mm:.1f} mm / "
                              f"{s_mgr.surrogate.max_rotation_distance_deg:.0f}°).",
                              "ok")
            elif getattr(s_mgr, "initializing", False):
                text = ("Loading the interpolated E-field library (a few "
                        "seconds) — pulses wait until it is ready.")
                role = "busy"
            else:
                text = ("Interpolated library unavailable — check the library "
                        "and ROI paths / the log.")
                role = "error"
        elif self.offline_efield_btn.isChecked():
            text, role = "Precomputed library — ready immediately.", "ok"
        elif self.efield_mode_selected:
            text, role = "", "ok"
        else:
            text, role = "Choose a mode to enable Start.", ""
        if label.text() != text:
            label.setText(text)
        if label.property("tone") != role:
            label.setProperty("tone", role)
            label.style().unpolish(label)
            label.style().polish(label)

    def update_mesh_coloring(self, scores_dict):
        """R² maps from the regression (per channel, one value per ROI element).

        Called by the controller; also feeds the results table, the hover
        readout and the best-element marker."""
        self._mapping_scores.update({k: np.asarray(v) for k, v in (scores_dict or {}).items()})
        if hasattr(self, 'widget_3d_viewer'):
            self.widget_3d_viewer.apply_scores(scores_dict)
        self._refresh_results_table()

    # set the status of self.robot_led, self.stim_led, self.emg_led
    def set_led_status(self, led_widget, status_val: str, color_val: str):
        """Architectural helper to safely update LED states and force CSS re-evaluation."""
        if led_widget is None:
            return

        # 1. Update the dynamic properties
        led_widget.setProperty("status", status_val)
        led_widget.setProperty("color", color_val)

        # 2. Force the Qt Style Engine to re-evaluate the CSS
        led_widget.style().unpolish(led_widget)
        led_widget.style().polish(led_widget)
        led_widget.update()


    def on_new_emg_result(self, target_index, emg_data, meps):
        """
        target_index: int
        emg_data: DataFrame with 's', 'ADC 0', 'ADC 1', 'ADC 2'
        meps: Dict {'ADC 0': 0.05, ...}
        """
        # 1. Update History (For the Trend Plot)
        self.history_targets.append(target_index)
        for ch, val in meps.items():
            # 1. If we haven't seen "ADC 0" before, create a new list for it
            if ch not in self.history_meps:
                self.history_meps[ch] = []
            # 2. Add the new value to the end of that specific channel's list
            self.history_meps[ch].append(float(val))

        # 2. Update Widget 1: MEP Trend
        # "widget_mep_trend" is the objectName you set in Qt Designer
        if self.controller:
            exclusion = self.controller.excluded_pulse_indices
        else:
            exclusion = None

        if hasattr(self, 'widget_mep_trend'):
            self.widget_mep_trend.update_as_trend(
                    target_indices=self.history_targets,
                    history_dict=self.history_meps,
                    exclusion=exclusion
            )

        order = 6
        # 3. Update Widget 2: Raw Signal
        # "widget_emg_signal" is the objectName you set in Qt Designer
        if hasattr(self, 'widget_emg_signal'):
            time_vals = emg_data["Time"]
            # Filter columns to only get the EMG channels (everything but Time)

            signal_dict = {col: pynibs.expio.butter_lowpass_filter(emg_data[col],
                                                                   int(os.getenv("CUTOFF_FREQ")),
                                                                   int(os.getenv("SAMPLING_RATE")),
                                                                   order) for col in emg_data.columns if col != "Time"}

            # Create A dictionary for each received emg
            new_record = {
                "target_index": target_index,
                "time_array": time_vals,
                "data_dict": signal_dict,
                "meps": meps,
                "included": True
            }
            # Append to history and update index to the latest
            self.emg_history.append(new_record)
            self.current_history_idx = len(self.emg_history) - 1

            # Update the UI to show this latest pulse
            self.refresh_emg_nav_display()

            self.widget_emg_signal.update_as_signal(
                    time_array=time_vals,
                    data_dict=signal_dict
            )

    def refresh_emg_nav_display(self):
        if not self.emg_history or self.current_history_idx == -1:
            self.widget_emg_signal.btn_prev.setEnabled(False)
            self.widget_emg_signal.btn_next.setEnabled(False)
            self.widget_emg_signal.chk_include.setChecked(False)
            self.widget_emg_signal.chk_include.setEnabled(False)
            return

        # Get the record at the current index
        record = self.emg_history[self.current_history_idx]

        # Update the graph visually
        self.widget_emg_signal.update_as_signal(record["time_array"], record["data_dict"])

        # Update labels
        self.widget_emg_signal.set_title(f"{record['target_index']+1}. EMG")

        # Logic for buttons: Disable 'Prev' if at start, 'Next' if at end
        self.widget_emg_signal.btn_prev.setEnabled(self.current_history_idx > 0)
        self.widget_emg_signal.btn_next.setEnabled(self.current_history_idx < len(self.emg_history) - 1)

        # Update checkbox without triggering its signal
        self.widget_emg_signal.chk_include.blockSignals(True)
        self.widget_emg_signal.chk_include.setEnabled(True)
        self.widget_emg_signal.chk_include.setChecked(record["included"])
        self.widget_emg_signal.chk_include.blockSignals(False)

    def show_previous_emg(self):
        if self.current_history_idx > 0:
            self.current_history_idx -= 1
            self.refresh_emg_nav_display()

    def show_next_emg(self):
        if self.current_history_idx < len(self.emg_history) - 1:
            self.current_history_idx += 1
            self.refresh_emg_nav_display()

    def handle_inclusion_change(self, is_included):
        if self.current_history_idx == -1:
            return

        record = self.emg_history[self.current_history_idx]
        record["included"] = is_included

        # Tell the controller to update the map
        if self.controller:
            self.controller.set_pulse_inclusion(record['target_index'], is_included)
        if hasattr(self, 'widget_mep_trend'):
            self.widget_mep_trend.update_as_trend(
                    target_indices=self.history_targets,
                    history_dict=self.history_meps,
                    exclusion=getattr(self.controller, "excluded_pulse_indices", set())
            )


    def toggle_free_drive_func(self):
        if self.controller:
            if self.toggle_free_drive_set:
                print("test_func")
                self.controller.toggle_free_drive(self.toggle_free_drive_set)
                self.freedrive.setText("Disable free Drive")
                self.toggle_free_drive_set = not self.toggle_free_drive_set

            elif not self.toggle_free_drive_set:
                print("test_func")
                self.controller.toggle_free_drive(self.toggle_free_drive_set)
                self.freedrive.setText("Enable free Drive")
                self.toggle_free_drive_set = not self.toggle_free_drive_set

    def on_pulse_shape_changed(self, shape_text: str):
        """
        Triggered when the user selects a new pulse shape from the dropdown.
        """
        print(f"UI: Pulse shape selected -> {shape_text}")
        if self.controller:
            try:
                self.controller.set_waveform(shape_text)
            except ValueError:
                print("Couldn't set waveform.")
                if shape_text == "Biphasic":
                    self.pulseShapeComboBox.setCurrentIndex(1)
                elif shape_text == "Monophasic":
                    self.pulseShapeComboBox.setCurrentIndex(0)


    def on_fit_function_changed(self, fit_func: str):
        """
        Triggered when the user selects a new Fit Function from the dropdown.
        """
        print(f"UI: Fit Function shape selected -> {fit_func}")
        if self.controller:
            self.controller.set_fit_function(fit_func)

    def set_robot_manual(self):
        """Manual mode: the operator moves the coil.  Remove every robot
        control (transport button, robot card, camera view, LED) and give
        the freed space on the Control page to the log."""
        self._robot_view_disabled = True
        for attr in ("groupBox_3", "groupBox_robot_info",   # Connections
                     "move_coil_up", "groupBox_6",          # Control
                     "robot_view_label"):
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.hide()
        for widget in self._corner_pairs.get("led_robot", ()):
            widget.hide()

        # Reflow: move the log card from the bottom row into the camera's
        # place so the body row is two full columns.
        try:
            root = self.tab3.layout()
            body = bottom = None
            body_index = bottom_index = -1
            for i in range(root.count()):
                lay = root.itemAt(i).layout()
                if lay is None:
                    continue
                if lay.indexOf(self.robot_view_label) != -1:
                    body, body_index = lay, i
                if lay.indexOf(self.groupBox_stats) != -1:
                    bottom, bottom_index = lay, i
            if body is not None and bottom is not None:
                bottom.removeWidget(self.groupBox_stats)
                root.removeItem(root.itemAt(bottom_index))
                body.insertWidget(1, self.groupBox_stats)
                body.setStretch(0, 1)
                body.setStretch(1, 1)
                body.setStretch(2, 0)
        except (AttributeError, RuntimeError) as e:
            print(f"[WARN] manual layout reflow skipped: {e}")

    def initialize(self, all_error_recoveries):
        self.all_error_recoveries = all_error_recoveries

        # Wire each system to its labels & Recover button in the .ui
        for system, err_map in all_error_recoveries.items():
            name = getattr(system, "NAME", "").lower()
            description = getattr(system, "DESCRIPTION", None) or getattr(system, "NAME", "")
            # Show the concrete hardware/backend on the Connections page
            # group ("Stimulator — Simulated", ...) so the mode is always
            # visible; new hardware variants only set DESCRIPTION.
            def _set_group_title(group_attr, base):
                group = getattr(self, group_attr, None)
                if group is not None:
                    group.setTitle(f"{base} — {description}")

            if "relay" in name:
                self._bind_system(
                        system=system,
                        status_label=getattr(self, "relayStatusLabel", None),
                        message_label=getattr(self, "relayMessageLabel", None),
                        recover_button=getattr(self, "relayRecoverButton", None),
                        last_update_label=getattr(self, "relayLastUpdateLabel", None),
                        led_label=getattr(self, "led_relay", None)
                )
                _set_group_title("groupBox_relay", "Relay")

            elif "robot" in name:
                self._bind_system(
                        system=system,
                        status_label=getattr(self, "robotStatusLabel", None),
                        message_label=getattr(self, "robotMessageLabel", None),
                        recover_button=getattr(self, "robotRecoverButton", None),
                        last_update_label=getattr(self, "robotLastUpdateLabel", None),
                        led_label=getattr(self, "led_robot", None) # the status of the led in the connection tap
                )
                _set_group_title("groupBox_3", "Robot")

            elif "stimulator" in name:  # stimulator
                self._bind_system(
                        system=system,
                        status_label=getattr(self, "stimStatusLabel", None),
                        message_label=getattr(self, "stimMessageLabel", None),
                        recover_button=getattr(self, "stimRecoverButton", None),
                        last_update_label=getattr(self, "stimLastUpdateLabel", None),
                        led_label=getattr(self, "led_stim", None)  # the status of the led in the connection tap
                )
                _set_group_title("groupBox_2", "Stimulator")

            elif "emg" in name:
                self._bind_system(
                        system=system,
                        status_label=getattr(self, "emgStatusLabel", None),
                        message_label=getattr(self, "emgMessageLabel", None),
                        recover_button=getattr(self, "emgRecoverButton", None),
                        last_update_label=getattr(self, "emgLastUpdateLabel", None),
                        led_label=getattr(self, "led_emg", None)  # the status of the led in the connection tap
                )
                _set_group_title("groupBox_4", "EMG")

        # Initialize display
        for sys_obj in self.status_labels:
            self._update_details_view(sys_obj, getattr(sys_obj, "details", {}))
        for sys_obj, lbl in self.status_labels.items():
            if lbl is not None:
                lbl.setText("Not Initialized")
            #   lbl.setStyleSheet("color: #595959")
        for sys_obj, lbl in self.message_labels.items():
            if lbl is not None:
                lbl.setText("")

    def _bind_system(self, system, status_label, message_label, recover_button, last_update_label=None,led_label=None):
        """Connects one system to its status/message labels and its Recover button."""
        if status_label is None:
            print(f"[WARN] No status label for system {getattr(system, 'NAME', '?')}")
            return

        self.status_labels[system] = status_label
        self.message_labels[system] = message_label
        if last_update_label is not None:
            self.last_update_labels[system] = last_update_label
        self.led_labels[system] = led_label

        if recover_button is not None:
            self.recover_buttons[system] = recover_button
            recover_button.setEnabled(False)
            # capture system object in default arg
            recover_button.clicked.connect(lambda _, s=system: self.on_recover_clicked(s))

    def _setup_robot_scene_view(self, simulation):
        """Simulation only: render the robot scene locally instead of
        receiving JPEG frames, so the operator can orbit around it."""
        self._robot_scene_view = None
        if not simulation:
            return
        label = getattr(self, "robot_view_label", None)
        if label is None:
            return
        try:
            from .robot_scene_view import RobotSceneView
            label.setStyleSheet("QLabel[role=\"bed\"] { background: #101317;"
                                " border-radius: 8px; }")
            label.setToolTip("Drag to orbit, right-drag to pan, wheel to zoom,"
                             " double click to reset")
            self._robot_scene_view = RobotSceneView(label, parent=self)
            self._robot_scene_view.start()
        except Exception as e:
            print(f"[WARN] embedded robot view unavailable: {e}")
            self._robot_scene_view = None

    def update_robot_scene(self, qpos):
        """Joint configuration published by the simulated robot."""
        view = getattr(self, "_robot_scene_view", None)
        if view is not None:
            view.set_qpos(qpos)

    # Maps a system name fragment to its details card widget prefix.
    INFO_PREFIXES = (("stim", "stim_info"), ("emg", "emg_info"),
                     ("robot", "robot_info"), ("relay", "relay_info"))

    def _update_details_view(self, system, details):
        """Fill one system's details card: label/value rows in order, unused
        rows hidden so shorter lists do not leave empty lines."""
        name = getattr(system, "NAME", "").lower()
        prefix = next((p for key, p in self.INFO_PREFIXES if key in name), None)
        if prefix is None:
            return
        rows = list((details or {}).items())
        for i in range(1, 6):
            cap = getattr(self, f"{prefix}_cap_{i}", None)
            val = getattr(self, f"{prefix}_val_{i}", None)
            if cap is None or val is None:
                continue
            if i <= len(rows):
                key, value = rows[i - 1]
                cap.setText(str(key))
                val.setText(str(value))
                cap.show()
                val.show()
            else:
                cap.setText("")
                val.setText("")
                cap.hide()
                val.hide()

    def update_system_status(self, system=None, status=None, message=None,
                             details=None):
        if system is None:
            return
        if details is not None:
            self._update_details_view(system, details)
            if status is None:
                return

        status_label = self.status_labels.get(system)
        message_label = self.message_labels.get(system)
        recover_button = self.recover_buttons.get(system)
        led_widget = self.led_labels.get(system)

        if status_label is None:
            # No UI mapped for this system (shouldn't happen if everything wired)
            return

        # Remember the status so a theme change can re-render it.
        self._system_status[system] = status
        theme = getattr(self, "_theme", {})

        # By default: disable Recover
        if recover_button is not None:
            recover_button.setEnabled(False)
            self.pending_recovery[system] = None

        if status == SystemStatus.OK:
            status_label.setStyleSheet(
                f"QLabel {{ color: {theme.get('ok', '#0D9E42')}; }}")
            status_label.setText("OK")
            self.set_led_status(led_widget, "on", "green")
            if message_label:
                message_label.setText("")
            # A relay that NeuroPilot owns can be restarted even while healthy.
            if ("relay" in getattr(system, "NAME", "").lower()
                    and recover_button is not None
                    and getattr(system, "owned", False)):
                recover_button.setText("Restart relay")
                recover_button.setEnabled(True)
                self.pending_recovery[system] = "Restart relay"

        elif status == SystemStatus.ERROR:
            status_label.setStyleSheet(
                f"QLabel {{ color: {theme.get('danger', '#B50E0E')}; }}")
            status_label.setText("ERROR")
            self.set_led_status(led_widget, "on", "red")

            msg_text = message or ""

            # Use ERROR_RECOVERIES to see if there is a defined recovery
            err_map = self.all_error_recoveries.get(system, {})
            if message in err_map:
                recovery_name = err_map[message]
                self.pending_recovery[system] = recovery_name
                if recover_button is not None and recovery_name is not None:
                    # change button text to recovery_name
                    recover_button.setText(recovery_name)
                    recover_button.setEnabled(True)
                else:
                    msg_text += "\nNo Recovery Implemented"

            else:
                msg_text += "\nNo Recovery Implemented"

            if message_label:
                message_label.setText(msg_text)

        elif status == SystemStatus.NAN:
            status_label.setStyleSheet(
                f"QLabel {{ color: {theme.get('muted', '#595959')}; }}")
            status_label.setText("Status: Not Initialized")
            self.set_led_status(led_widget, "off", "")
            if message_label:
                message_label.setText("")

        # add a "last update" label in the UI and set it here

        last_lbl = self.last_update_labels.get(system)
        if last_lbl is not None:
            last_lbl.setText(time.strftime("%H:%M:%S", time.localtime(time.time())))

        # 1. Identify which system is updating and set its specific flag
        name = getattr(system, "NAME", "").lower()
        is_system_ok = (status == SystemStatus.OK)

        if "relay" in name:
            self.relay_ready = is_system_ok
        elif "robot" in name:
            self.robot_ready = is_system_ok
        elif "stimulator" in name:
            self.stim_ready = is_system_ok
        elif "emg" in name:
            self.emg_ready = is_system_ok

        # 2. Evaluate if ALL three systems are True (The AND Gate)
        self.update_button_states()

        if self.stim_ready:
            self.enableBtn.setEnabled(True)
            self.fireBtn.setEnabled(True)
        else:
            self.enableBtn.setEnabled(False)
            self.fireBtn.setEnabled(False)

    def on_recover_clicked(self, system):
        """Called when user clicks the Recover button for a system."""
        recovery_name = self.pending_recovery.get(system)
        if recovery_name:
            print(f"Recovering {getattr(system, 'NAME', '?')} with {recovery_name}")
            system.recover(recovery_name)
        else:
            print("No recovery action stored for this system.")

    def set_controller(self, controller):
        self.controller = controller
        if hasattr(self, "collision_tab"):
            self.collision_tab.set_controller(controller)
        if controller is not None:
            # Keep the back-reference in sync: the entry point passes the
            # panel at construction, alternate launchers attach it here.
            controller.control_panel = self
        self._apply_config_mode()
        if self.controller:
            self.slider1_spinbox1(20)
            # Push the restored session values to the controller (the cache
            # was loaded before the controller existed) — this also lets the
            # user's last amplitude override the default 20 above.
            self._apply_pending_session()
            # The restored slider values do not emit valueChanged when they
            # already match the .ui defaults, so the robot would keep its own
            # defaults until a slider is touched.
            if hasattr(self.controller, "push_robot_settings"):
                self.controller.push_robot_settings()

    # functions for the elements in the second Tap
    # === BEGIN: Handlers for loading the Mesh ===
    def _load_mesh_async(self, file_path, mesh_type):
        """Schedule a display mesh read; the window stays interactive."""
        self._mesh_view_request = mesh_type
        token = self._start_load(mesh_type, file_path, mesh_type=mesh_type)
        if token is None:
            # The same file is already in memory.  Still honour the request
            # to show it (project reloads and re-entering the same path).
            current = self._load_current.get(mesh_type)
            if current and current.get("loaded"):
                view = getattr(self, "widget_3d_viewer", None)
                mesh = (view.mesh_head if mesh_type == "head"
                        else view.mesh_roi) if view is not None else None
                if mesh is not None:
                    view.set_loaded_mesh(mesh, mesh_type=mesh_type, select=True)
        return token

    def _clear_mesh(self, mesh_type):
        self._cancel_load(mesh_type)
        if hasattr(self, 'widget_3d_viewer'):
            self.widget_3d_viewer.load_hdf5_mesh("", mesh_type=mesh_type)

    def pick_mesh(self):
        """Opens file dialog and loads mesh into the 3D widget."""
        file_path = self._file_dialog(
                "Select Mesh File",
                os.getcwd(),
                "SimNIBS Mesh (*.msh);;HDF5 Files (*.hdf5 *.h5);;VTK Files (*.vtk)",
                save=False
        )
        if file_path:
            # just show path in QLineEdit
            self.loadmeshlabel.setText(file_path)
            print(f"Loading mesh: {file_path}")
            self._load_mesh_async(file_path, "head")
            if self.controller:
                self.controller.online_fem_mgr.set_mesh_fn_msh(file_path)
                self.controller.set_head_mesh(file_path)
            self._check_paths_ready()

    def paste_mesh_path(self):
        file_path = self.loadmeshlabel.text().strip()
        if not file_path:
            print("No file path given.")
            self._clear_mesh("head")
            if self.controller:
                self.controller.online_fem_mgr.set_mesh_fn_msh(None)
                self.controller.set_head_mesh(None)
            self._check_paths_ready()

        # Check if the file actually exists on the drive
        elif os.path.isfile(file_path):
            print(f"Loading mesh: {file_path}")
            self._load_mesh_async(file_path, "head")
            if self.controller:
                self.controller.online_fem_mgr.set_mesh_fn_msh(file_path)
                self.controller.set_head_mesh(file_path)
            self._check_paths_ready()
        else:
            # The file is missing or the user typed a directory instead of a file
            print(f"Wrong path: The file '{file_path}' does not exist.")
            self.loadmeshlabel.setText("")
            self._clear_mesh("head")
            if self.controller:
                self.controller.online_fem_mgr.set_mesh_fn_msh(None)
                self.controller.set_head_mesh(None)
            self._check_paths_ready()

    # === END: Handlers for loading the Mesh ===

    # === BEGIN: Handlers for loading the coil path ===
    def pick_coil_path(self):
        """Opens file dialog for TMS coil model (.ccd) file."""
        # Start in the SimNIBS coil-model folder: that is where the
        # shipped .ccd files (e.g. the default MCF-B65) live. Fall back
        # to the current selection's folder, then to the home directory.
        coil_models_dir = _simnibs_coil_model("Drakaki_BrainStim_2022",
                                              "MagVenture_MCF-B65_new.ccd")
        if coil_models_dir:
            start_folder = os.path.dirname(coil_models_dir)
        else:
            current = self.coilspathlineedit.text().strip()
            start_folder = (os.path.dirname(current) if os.path.isdir(os.path.dirname(current))
                            else os.path.expanduser("~"))
        file_path = self._file_dialog(
                "Select Coil Model File",
                start_folder,
                "CCD Files (*.ccd *.ccd.nii.gz)",
                save=False
        )
        if file_path:
            self.coilspathlineedit.setText(file_path)
            print(f"GUI: Coil model set: {file_path}")
            if self.controller:
                self.controller.online_fem_mgr.set_coil_fn(file_path)
            self._check_paths_ready()

    def pick_emg_config(self):
        """Opens file dialog for the EMG channel source config (.yaml)."""
        file_path = self._file_dialog(
            "Select EMG Channel Config",
            os.path.dirname(self.emg_config_label.text().strip())
            if self.emg_config_label.text().strip() else os.path.expanduser("~"),
            "YAML Files (*.yaml *.yml)",
        )
        if file_path:
            self.emg_config_label.setText(file_path)
            self.paste_emg_config()

    def paste_emg_config(self):
        file_path = self.emg_config_label.text().strip()
        if not file_path:
            self._cancel_load("emg")
            return
        if not os.path.isfile(file_path):
            # Same behaviour as the mesh/ROI/coil fields: do not keep a path
            # that cannot be used.
            self._reject_path(self.emg_config_label,
                              f"EMG config not found: {file_path}")
            self._cancel_load("emg")
            return
        # Reading the YAML is cheap, but xyz sources are projected onto the
        # ROI; keep that file read off the GUI thread as well.
        self._start_load("emg", file_path, force=True,
                         roi_path=self.loadroilabel.text().strip())

    def set_emg_channels(self, names):
        """Propagate the configured EMG channel display names to the MEP
        plots and the mapping viewer (the data layer keeps its ADC keys)."""
        for attr in ("widget_mep_trend", "widget_emg_signal"):
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.set_channels(names)
        widget = getattr(self, "widget_3d_viewer", None)
        if widget is not None:
            widget.set_channel_display_names(names)
        self._emg_display_names = list(names)
        self._rebuild_placement_metric_combo()

    def paste_coil_path(self):
        file_path = self.coilspathlineedit.text().strip()
        if not file_path:
            print("GUI: No coil path given.")
            if self.controller:
                self.controller.online_fem_mgr.set_coil_fn(None)
            self._check_paths_ready()
        elif os.path.isfile(file_path):
            print(f"GUI: Coil model set: {file_path}")
            if self.controller:
                self.controller.online_fem_mgr.set_coil_fn(file_path)
            self._check_paths_ready()
        else:
            print(f"GUI: Wrong path: The file '{file_path}' does not exist.")
            self.coilspathlineedit.setText("")
            if self.controller:
                self.controller.online_fem_mgr.set_coil_fn(None)
            self._check_paths_ready()

    # === END: Handlers for loading the coil path ===


    # === BEGIN: Handlers for loading the ROI ===
    def pick_ROI(self):
        """Opens file dialog and loads HDF5 mesh."""
        file_path = self._file_dialog(
                "Select Mesh File",
                os.getcwd(),
                "HDF5 Files (*.hdf5 *.h5);;VTK Files (*.vtk)",
                save=False
        )
        if file_path:
            # just show path in QLineEdit
            self.loadroilabel.setText(file_path)
            print(f"Loading ROI: {file_path}")
            self._load_mesh_async(file_path, "roi")
            if self.controller:
                self.controller.online_fem_mgr.set_roi_fn_hdf5(file_path)
                self.controller.surrogate_mgr.set_roi_fn_hdf5(file_path)
            self._check_paths_ready()

    def paste_roi_path(self):
        file_path = self.loadroilabel.text().strip()
        if not file_path:
            print("No file path given.")
            self._clear_mesh("roi")
            if self.controller:
                self.controller.online_fem_mgr.set_roi_fn_hdf5(None)
                self.controller.surrogate_mgr.set_roi_fn_hdf5(None)
            self._check_paths_ready()

        # Check if the file actually exists on the drive
        elif os.path.isfile(file_path):
            print(f"Loading ROI: {file_path}")
            self._load_mesh_async(file_path, "roi")
            if self.controller:
                self.controller.online_fem_mgr.set_roi_fn_hdf5(file_path)
                self.controller.surrogate_mgr.set_roi_fn_hdf5(file_path)
                # The EMG source projection runs against this ROI: re-apply
                # the channel config so xyz sources re-project.  Do it after
                # the ROI read finishes, not on the GUI thread in this slot.
            self._check_paths_ready()
        else:
            # The file is missing or the user typed a directory instead of a file
            print(f"Wrong path: The file '{file_path}' does not exist.")
            self.loadroilabel.setText("")
            self._clear_mesh("roi")
            if self.controller:
                self.controller.online_fem_mgr.set_roi_fn_hdf5(None)
                self.controller.surrogate_mgr.set_roi_fn_hdf5(None)
            self._check_paths_ready()

    # === END: Handlers for loading the ROI ===

    # === BEGIN: Handlers for loading the Target Path  ===
    def pick_target_order_path(self):
        """Opens file dialog and loads Target Order txt file."""
        file_path = self._file_dialog(
                "Select Target Order File",
                os.getcwd(),
                "Text Files (*.txt)",
                save=False
        )
        if file_path:
            # just show path in QLineEdit
            self.target_order_LineEdit.setText(file_path)
            if self.controller:
                self.controller.set_target_order_fn(file_path)

    def paste_target_order_path(self):
        file_path = self.target_order_LineEdit.text().strip()
        if not file_path:
            print("No file path given.")
            if self.controller:
                self.controller.set_target_order_fn(None) # passing None instead of empty string because this line (if self.target_order_fn is not None:) in the pipeline controller

        # Check if the file actually exists on the drive
        elif os.path.isfile(file_path):
            if self.controller:
                # Reject a corrupt order now rather than at Start.
                from .pipeline_controller import parse_target_order_file
                try:
                    order = parse_target_order_file(file_path)
                except ValueError as e:
                    self._reject_path(self.target_order_LineEdit, e)
                    self.controller.set_target_order_fn(None)
                    return
                self.target_order_LineEdit.setToolTip(f"{len(order):,} placements")
                self.controller.set_target_order_fn(file_path)
        else:
            # The file is missing or the user typed a directory instead of a file
            print(f"Wrong path: The file '{file_path}' does not exist.")
            self.target_order_LineEdit.setText("")
            # Optional: UI popup here to warn the user visually
    # === END: Handlers for loading the Target Path  ===

    # === BEGIN: Handlers for loading the coil placements  ===
    def pick_coilplacement(self):
        file_path_coil_placement = self._file_dialog(
                "Select a file",
                os.getcwd(),
                "HDF5 Files (*.hdf5)",
                save=False
        )
        if file_path_coil_placement:
            # just show path in QLineEdit
            self.loadplacementlabel.setText(file_path_coil_placement)
            self.paste_coil_placements_path()

    def paste_coil_placements_path(self):
        file_path = self.loadplacementlabel.text().strip()
        if not file_path:
            print("No file path given.")
            self._cancel_load("targets")
            if self.controller:
                self.controller.set_targets_file(None)

        # Check if the file actually exists on the drive
        elif os.path.isfile(file_path):
            # Vet the HDF5 layout before the run depends on it.  This reads
            # only the header and is fast; the matrices are read in a worker.
            try:
                n = validate_simnibs_targets_file(file_path)
            except ValueError as e:
                self._reject_path(self.loadplacementlabel, e)
                self._cancel_load("targets")
                if self.controller:
                    self.controller.set_targets_file(None)
                return
            self.loadplacementlabel.setToolTip(f"{n:,} coil placements")
            if self.controller:
                if hasattr(self.controller, "set_targets_file_header"):
                    self.controller.set_targets_file_header(file_path, n)
                else:
                    self.controller.set_targets_file(file_path)
            self._start_load("targets", file_path)
        else:
            # The file is missing or the user typed a directory instead of a file
            print(f"Wrong path: The file '{file_path}' does not exist.")
            self.loadplacementlabel.setText("")
            self._cancel_load("targets")
            if self.controller:
                self.controller.set_targets_file(None)
    # === END: Handlers for loading the coil placements ===

    # === BEGIN: Handlers for loading the E-Field ===
    def _begin_e_field_load(self, file_path):
        """Schedule the precomputed matrix read and clear stale state now."""
        if self.controller:
            if hasattr(self.controller, "clear_e_matrix"):
                self.controller.clear_e_matrix()
            else:
                self.controller.e_matrix = None
                self.controller.n_elms = None
                self.controller.n_positions = None
        self._start_load("efield", file_path)
        self._check_paths_ready()

    def pick_e_field(self):
        """Opens file dialog and loads HDF5 E Field."""
        file_path = self._file_dialog(
                "Select Mesh File",
                os.getcwd(),
                "HDF5 Files (*.hdf5)",
                save=False
        )
        if file_path:
            # just show path in QLineEdit
            self.load_e_matrix_label.setText(file_path)
            print(f"Loading E Field: {file_path}")
            self._begin_e_field_load(file_path)

    def paste_e_field_path(self):
        file_path = self.load_e_matrix_label.text().strip()
        if not file_path:
            print("No file path given.")
            self._cancel_load("efield")
            if self.controller:
                if hasattr(self.controller, "clear_e_matrix"):
                    self.controller.clear_e_matrix()
                else:
                    self.controller.e_matrix = None
            self._check_paths_ready()

        # Check if the file actually exists on the drive
        elif os.path.isfile(file_path):
            print(f"Loading E Field: {file_path}")
            self._begin_e_field_load(file_path)
        else:
            # The file is missing or the user typed a directory instead of a file
            print(f"Wrong path: The file '{file_path}' does not exist.")
            self.load_e_matrix_label.setText("")
            self._cancel_load("efield")
            if self.controller:
                if hasattr(self.controller, "clear_e_matrix"):
                    self.controller.clear_e_matrix()
                else:
                    self.controller.e_matrix = None
            self._check_paths_ready()
    # === END: Handlers for loading the E-Field ===

    # === BEGIN: Handlers for the interpolated (surrogate) library ===
    def pick_surrogate_library(self):
        """File dialog for the dense library of the Interpolated mode."""
        file_path = self._file_dialog(
                "Select Interpolated E-field Library",
                os.getcwd(),
                "HDF5 Files (*.hdf5)",
                save=False
        )
        if file_path:
            self.surrogate_library_label.setText(file_path)
            self.paste_surrogate_library_path()

    def paste_surrogate_library_path(self):
        file_path = self.surrogate_library_label.text().strip()
        if not file_path:
            if self.controller:
                self.controller.surrogate_mgr.set_library_path(None)
        elif os.path.isfile(file_path):
            if self.controller:
                self.controller.surrogate_mgr.set_library_path(file_path)
                # A changed library invalidates the loaded one; (re-)start
                # the background load when the Interpolated mode is selected.
                if (self.controller.efield_mode == "surrogate"
                        and self.controller.surrogate_mgr.library_fn
                        and not self.controller.surrogate_mgr.ready
                        and not self.controller.surrogate_mgr.initializing):
                    self.controller.surrogate_mgr.ensure_initialized(
                        callback=self.surrogate_library_ready.emit)
        else:
            print(f"Wrong path: The file '{file_path}' does not exist.")
            self.surrogate_library_label.setText("")
        self._check_paths_ready()

    def _on_surrogate_library_ready(self):
        """The library finished loading: element count for the map + status."""
        mgr = self.controller.surrogate_mgr if self.controller else None
        if (mgr and mgr.is_ready
                and getattr(self.controller, "n_elms", None) in (None, -1)):
            # Same role as the precomputed matrix load: the map needs the
            # element count for the subsampled index list.
            self.controller.n_elms = mgr.n_elements
            self.controller.set_map_elms(self.controller.map_elms)
        self.update_button_states()
    # === END: Handlers for the interpolated library ===

    # === BEGIN: Handlers for loading the saving path ===
    def pick_save_path(self):
        # 1. Look at the target order text box to see where they loaded from
        target_path = self.target_order_LineEdit.text().strip()

        # 2. Default to the user's home directory just in case the box is empty
        start_folder = os.path.expanduser("~")

        # 3. If there is a target path, extract ONLY the folder part
        if target_path:
            extracted_folder = os.path.dirname(target_path)
            # Verify the folder actually exists before telling the dialog to open it
            if os.path.isdir(extracted_folder):
                start_folder = extracted_folder

        # 4. Open the Save dialog explicitly in that 'start_folder'
        file_path = self._file_dialog(
                "Select Save Location",
                start_folder,  # <--- This tells the window exactly where to open!
                "CSV Files (*.csv);;All Files (*)",
                save=True
        )
        if file_path:
            if not file_path.lower().endswith('.csv'):
                file_path= file_path + ".csv"
            self.savePathLineEdit.setText(file_path)
            #notify the controller immediately
            if self.controller:
                self.controller.set_results_filename(file_path)

    def paste_save_path(self):
        file_path = self.savePathLineEdit.text().strip()
        if not file_path:
            print("No file path given.")
            if self.controller:
                self.controller.set_results_filename(None)
            return

        if not file_path.lower().endswith('.csv'):
            file_path += '.csv'
            self.savePathLineEdit.setText(file_path)  # Update UI to show the fix

        # 2. Extract just the folder path
        folder_path = os.path.dirname(file_path)

        # 3. Create the folder(s) if they do not exist
        if folder_path:  # Ensures it's not empty
            try:
                os.makedirs(folder_path, exist_ok=True)
                print(f"Verified or created directory: {folder_path}")
            except OSError as e:
                print(f"Error: Could not create directory. {e}")
                return

        if self.controller:
            print(f"the Path for saving the results has been set: {file_path}")
            self.controller.set_results_filename(file_path)
    # === END: Handlers for loading the saving path ===

    # ===
    def on_load_yaml(self):
        """Opens file dialog and loads YAML file."""
        file_path = self._file_dialog(
                "Load Config",
                os.path.dirname(self._project_file) if self._project_file
                else os.path.expanduser("~"),
                "YAML Files (*.yaml *.yml)"
        )
        if file_path:
            error = self.load_project_file(file_path)
            if error:
                QtWidgets.QMessageBox.warning(
                    self, "Invalid YAML",
                    f"Could not load config file:\n{error}"
                )

    def _run_in_progress(self):
        controller = getattr(self, "controller", None)
        running = getattr(controller, "is_running", False)
        return running is True

    def load_project_file(self, file_path):
        """Load a project YAML without a dialog.

        Returns ``None`` on success and a short error message otherwise; the
        caller decides whether to show a dialog.  Nothing is applied when the
        file cannot be read or does not hold a mapping, so a wrong file can
        never leave the GUI half-configured.
        """
        if self._run_in_progress():
            return ("a mapping session is running -- finish it before loading "
                    "another project")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
            return str(e)
        if not isinstance(data, dict):
            return (f"expected a mapping of settings, found "
                    f"{type(data).__name__}")
        data = _resolve_project_paths(
            data, os.path.dirname(os.path.abspath(file_path)))
        self._project_loading = True
        try:
            self.apply_config_dict(data)
        finally:
            self._project_loading = False
        self._project_file = file_path
        # The stored name wins; fall back to the file name.  Do this *before*
        # clearing the dirty flag: setText fires textChanged -> _mark_project_dirty.
        if not self.project_name_edit.text().strip():
            self.project_name_edit.setText(os.path.basename(file_path))
        self._project_dirty = False
        self._update_project_label()
        self._save_session_cache()
        return None

    def on_save_yaml(self):
        # Default the save dialog to the current project folder and, if the
        # user already typed a project name, to that name.
        default_name = self.project_name_edit.text().strip()
        start_dir = os.path.dirname(self._project_file) if self._project_file \
            else os.path.expanduser("~")
        start = os.path.join(start_dir, default_name + ".yaml") if default_name else start_dir
        file_path = self._file_dialog(
                "Select Save Location",
                start,
                "YAML Files (*.yaml *.yml)",
                save=True
        )
        if file_path:
            error = self.save_project_file(file_path)
            if error:
                QtWidgets.QMessageBox.warning(
                    self, "Could not save", f"Could not save config file:\n{error}"
                )

    def save_project_file(self, file_path):
        """Write the project YAML without a dialog.

        Returns ``None`` on success and a short error message otherwise (the
        folder may have been removed while the dialog was open).  The project
        stays marked unsaved on failure so the user can pick another place.
        """
        if not file_path.lower().endswith(('.yaml', '.yml')):
            file_path += '.yaml'
        # An empty name field adopts the file name (stored in the project file
        # via get_config_dict below).
        if not self.project_name_edit.text().strip():
            self.project_name_edit.setText(os.path.basename(file_path))
        data = self.get_config_dict(
            base_dir=os.path.dirname(os.path.abspath(file_path)))
        try:
            with open(file_path, "w") as f:
                yaml.dump(data, f, default_flow_style=False)
        except OSError as e:
            print(f"Could not save the project to {file_path}: {e}")
            self.project_name_edit.setToolTip(f"Could not save:\n{e}")
            return str(e)
        self._project_file = file_path
        self._project_dirty = False
        self._update_project_label()
        self._save_session_cache()
        print(f"Configuration successfully saved to: {file_path}")
        return None


    def on_skip_step_clicked(self):
        if self.controller:
            print("Skip Step")
            self.controller.switch_step("skip")

    def on_back_clicked(self):
        if self.controller:
            print("Previous Step")
            self.controller.switch_step("previous")

    def on_start_pause_clicked(self):
        if self.controller:

            self.controller.toggle_start_pause()

            if self.controller.is_paused:
                self.start_btn.setText("Start")
            else:
                self.start_btn.setText("Pause")

    def on_enable_clicked(self):
        if self.controller:
            self.controller.enable_stimulator()

    def on_fire_stim_clicked(self):
        if self.controller:
            self.controller.trigger_stim()

    def on_finish_clicked(self):
        if self.controller:
            self.controller.finish_experiment()

    def on_move_coil_up(self):
        if self.controller:
            self.controller.set_stopped_true()
            self.controller.set_pause_true()
            self.controller.move_robot_away_from_head()
            self.start_btn.setText("Start")

    def slider1_spinbox1(self,value):
        print(f"Slider1 and spinbox1 value changed to {value}")
        self.slider.blockSignals(True)
        self.spinBox.blockSignals(True)

        self.slider.setValue(value)
        self.spinBox.setValue(value)

        self.slider.blockSignals(False)
        self.spinBox.blockSignals(False)

        if self.controller:
            self.controller.set_amplitude_stim(value)

    def slider2_spinbox2(self,value):
        print(f"Slider2 and spinbox2 value changed to {value}")
        self.slider2.blockSignals(True)
        self.spinBox2.blockSignals(True)

        self.slider2.setValue(value)
        self.spinBox2.setValue(value)

        self.slider2.blockSignals(False)
        self.spinBox2.blockSignals(False)
        if self.controller:
            self.controller.set_default_speed(value)

    def slider3_spinbox3(self,value):
        print(f"Slider3 and spinbox3 value changed to {value}")
        self.slider3.blockSignals(True)
        self.spinBox3.blockSignals(True)

        self.slider3.setValue(value)
        self.spinBox3.setValue(value)

        self.slider3.blockSignals(False)
        self.spinBox3.blockSignals(False)
        if self.controller:
            self.controller.set_tuning_speed(value)

    def on_subsampling_changed(self,value):
        if self.controller:
            self.controller.set_map_elms(value)
            print(f"Subsampling set to {value}")

    def on_n_repetitions_changed(self, value):
        if self.controller:
            self.controller.set_n_repetitions(value)

    def on_min_interval_changed(self,value):
        if self.controller:
            self.controller.set_minium_isi(value)

    ##################################################
    def get_config_dict(self, base_dir=None):
        """Return controller and GUI parameters as a plain dict.

        ``base_dir`` is set when writing a project YAML; paths below it are
        stored relative to the project file.  The session cache uses the
        default ``None`` and therefore keeps absolute paths.
        """
        data = {
            "project_name": self.project_name_edit.text().strip() or None,
            "fit_fun": self.fitFunctionComboBox.currentText(),
            "map_elms": self.sampling_spinBox.value(),
            "results_fn": self.savePathLineEdit.text() or None,
            "overwrite_results": self.overwrite_results_chk.isChecked(),
            "stimulator_amplitude": self.spinBox.value(),
            "target_order_fn": self.target_order_LineEdit.text() or None,
            "stimulator_waveform": self.pulseShapeComboBox.currentText(),
            "minium_isi": self.min_interval_spinBox.value(),
            "n_repetitions": self.n_repetitions_spinBox.value(),
            "targets_file": self.loadplacementlabel.text() or None,
            "default_speed": self.spinBox2.value(),
            "tuning_speed": self.spinBox3.value(),
            "mesh_head_path": self.loadmeshlabel.text() or None,
            "mesh_RIO_path": self.loadroilabel.text() or None,
            "e_field_path": self.load_e_matrix_label.text() or None,
            "surrogate_library_path": self.surrogate_library_label.text() or None,
            "coil_path": self.coilspathlineedit.text() or None,
            "emg_config_fn": self.emg_config_label.text() or None,
            # Travels with the subject so a session resumes in the same mode.
            "efield_mode": self.efield_mode_name(),
            "collision_test": (self.collision_tab.project_config()
                               if hasattr(self, "collision_tab") else None),
        }
        return _relative_project_paths(data, base_dir)

    def apply_config_dict(self, d):
        """Apply only the keys present in d to controller state and UI.

        Anything that is not a mapping (an empty file, a list, a stray
        string in a hand-edited YAML) is ignored: loading a wrong file must
        never take the GUI down.
        """
        if not isinstance(d, dict):
            print(f"[WARN] project config ignored: expected a mapping, got {type(d).__name__}")
            return False
        if self._run_in_progress():
            # Swapping the library/placements/subsampling under a live run
            # changes what the map means (or crashes the analysis).
            print("[WARN] project config ignored: a mapping session is running.")
            return False
        if hasattr(self, "collision_tab"):
            value = d.get("collision_test")
            if isinstance(value, dict):
                self._collision_test_config = dict(value)
                self.collision_tab.apply_config(value)
            else:
                # An older project has no collision block: do not carry the
                # previous project's cell layout into it.
                self.collision_tab.reset_config()
        # YAML gives whatever the user typed: 3.7, "many", .nan.  Each widget
        # kind is coerced here, and a value that cannot be coerced is skipped
        # with a warning, so one bad key never blocks the rest of the file.
        spin_keys = {"map_elms", "stimulator_amplitude", "minium_isi",
                     "n_repetitions", "default_speed", "tuning_speed"}
        combo_keys = {"fit_fun", "stimulator_waveform"}
        setters = {
            # The project name is plain GUI state (no backend call behind it).
            "project_name": lambda v: self.project_name_edit.setText(v or ""),
            # ComboBoxes use setCurrentText
            "fit_fun": self.fitFunctionComboBox.setCurrentText,
            "stimulator_waveform": self.pulseShapeComboBox.setCurrentText,

            # SpinBoxes use setValue
            "map_elms": self.sampling_spinBox.setValue,
            "stimulator_amplitude": self.spinBox.setValue,
            "minium_isi": self.min_interval_spinBox.setValue,
            "n_repetitions": self.n_repetitions_spinBox.setValue,
            "default_speed": self.spinBox2.setValue,
            "tuning_speed": self.spinBox3.setValue,

            # LineEdits use setText, but we wrap them in lambdas for two reasons:
            # 1. To prevent crashes if 'v' is None (using 'v or ""')
            # 2. To trigger manual backend functions since LineEdits don't have automatic valueChanged signals here
            "results_fn": lambda v: (self.savePathLineEdit.setText(v or ""),self.paste_save_path()),
            "overwrite_results": self.overwrite_results_chk.setChecked,
            "target_order_fn": lambda v: (self.target_order_LineEdit.setText(v or ""),self.paste_target_order_path()),
            "targets_file": lambda v: (self.loadplacementlabel.setText(v or ""), self.paste_coil_placements_path()),
            "mesh_head_path": lambda v: (self.loadmeshlabel.setText(v or ""),self.paste_mesh_path()),
            "mesh_RIO_path": lambda v: (self.loadroilabel.setText(v or ""),self.paste_roi_path()),
            "e_field_path": lambda v: (self.load_e_matrix_label.setText(v or ""),self.paste_e_field_path()),
            "surrogate_library_path": lambda v: (self.surrogate_library_label.setText(v or ""), self.paste_surrogate_library_path()),
            "coil_path": lambda v: (self.coilspathlineedit.setText(v or ""), self.paste_coil_path()),
            "emg_config_fn": lambda v: (self.emg_config_label.setText(v or ""), self.paste_emg_config()),
        }

        # Iterate through the config and apply the values using the matched setter function
        for key, setter in setters.items():
            if key not in d or key == "efield_mode":
                continue
            val = d[key]
            if key in spin_keys:
                try:
                    number = float(val)
                    if not math.isfinite(number):
                        raise ValueError("not finite")
                    val = int(round(number))
                except (TypeError, ValueError):
                    print(f"[WARN] project config: ignoring {key}={val!r}")
                    continue
            elif key in combo_keys:
                if val is None:
                    continue
                val = str(val)
            elif key == "overwrite_results":
                val = self._as_bool(val, True)
            elif val is None:
                val = ""
            setter(val)

        # The mode needs the E-field paths to be in place first (the radios are
        # disabled without them), so it is applied after the loop.  A mode that
        # cannot be selected yet is remembered and retried by _check_paths_ready.
        if "efield_mode" in d:
            self._apply_efield_mode(d["efield_mode"])
        self._refresh_subject_summary()
        return True

    # ── Config › Study ─────────────────────────────────────────────────


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
