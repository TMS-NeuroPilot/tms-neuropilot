from PyQt5 import QtCore, QtGui, QtWidgets, uic
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt
import re
import sys
import os
from .systems.system import SystemStatus
import pynibs
import time
import yaml

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


def _control_ui_icons():
    """Write the small PNG assets the style sheet needs (a check tick and the
    spin-box chevrons) and return their paths. Qt style sheets cannot draw
    these glyphs, and shipping binary resources for two 14 px icons is
    overkill — they are rendered once into the user's temp folder."""
    import tempfile
    folder = os.path.join(tempfile.gettempdir(), "neuropilot_ui")
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

    return {
        "check": _stroke(os.path.join(folder, "check.png"), (14, 14),
                         [(3.5, 7.5), (6.0, 10.0), (10.5, 4.0)], "#FFFFFF", 2.2),
        "up": _stroke(os.path.join(folder, "up.png"), (8, 5),
                      [(1.0, 4.0), (4.0, 1.0), (7.0, 4.0)], "#B45309", 1.6),
        "down": _stroke(os.path.join(folder, "down.png"), (8, 5),
                        [(1.0, 1.0), (4.0, 4.0), (7.0, 1.0)], "#B45309", 1.6),
    }


def _session_cache_path():
    """Per-user cache file holding the project fields between runs.

    Lives in ``~/.neuropilot`` — ``os.path.expanduser`` resolves to the
    user's profile directory on Windows as well, so the same code works on
    the lab PCs without adjustment.
    """
    return os.path.join(os.path.expanduser("~"), ".neuropilot", "last_session.yaml")


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, simulation):
        super().__init__()

        # ui is inside the "gui" folder
        ui_path = resource_path(os.path.join("gui", "pipeline_control.ui"))
        uic.loadUi(ui_path, self)

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
        if scale_env:
            scale = float(scale_env)
        else:
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
        #self.emg_results = []
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
        #history_meps = {
        #    'ADC 0': [0.05, 0.06, 0.04, 0.08],  # A clean list of Y-values for plotting
        #    'ADC 1': [0.12, 0.11, 0.13, 0.12],
        #    'ADC 2': [0.02, 0.01, 0.02, 0.02]
        #}
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
        self.online_efield_btn.setEnabled(False)
        self.offline_efield_btn.setEnabled(False)

        self.online_efield_btn.toggled.connect(self.on_efield_mode_changed)
        self.offline_efield_btn.toggled.connect(self.on_efield_mode_changed)

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
                              ("led_robot", "Robot")):
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


        self.led_labels = {}  # map LED labels to systems

        # 1. Initialize Explicit Hardware Flags for Disabling and enabling the start and skip button
        self.robot_ready = False
        self.stim_ready = False
        self.emg_ready = False

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
        self._update_file_infos()

        # Restore the last session's project fields. The values are only
        # stashed here — they are applied in set_controller(), once the
        # controller (and its setters) exist.
        self._pending_session = None
        cache_fn = _session_cache_path()
        if os.path.isfile(cache_fn):
            try:
                with open(cache_fn, "r") as f:
                    self._pending_session = yaml.safe_load(f) or {}
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

    def _place_tab_corner(self):
        """Size the LED corner to its (scaled) contents.  QTabWidget only
        re-runs its corner placement on resize, so after a font/style pass
        the captions would clip at the right edge."""
        corner = getattr(self, "_tab_corner", None)
        if corner is None:
            return
        lay = corner.layout()
        if lay is not None:
            lay.activate()
        hint = corner.sizeHint()
        bar = self.tabWidget.tabBar()
        corner.setGeometry(self.tabWidget.width() - hint.width(), 0,
                           hint.width(), max(hint.height(), bar.height()))
        corner.raise_()

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

    def _install_ui_assets(self):
        icons = _control_ui_icons()
        extra = """
QCheckBox::indicator:checked { image: url(%(check)s); }
QSpinBox { padding-right: 20px; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right;
    width: 16px; border-left: 1px solid #E7EAEE; border-bottom: 1px solid #E7EAEE;
    border-top-right-radius: 4px; background: #FAFBFC; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right;
    width: 16px; border-left: 1px solid #E7EAEE;
    border-bottom-right-radius: 4px; background: #FAFBFC; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #FEF3E2; }
QSpinBox::up-arrow { image: url(%(up)s); width: 8px; height: 5px; }
QSpinBox::down-arrow { image: url(%(down)s); width: 8px; height: 5px; }
""" % icons
        self.setStyleSheet(self.styleSheet() + extra)

    # ── Project file summaries ─────────────────────────────────────────────
    def _update_file_infos(self):
        """Show a short summary next to each configured project file."""
        def set_info(name, text):
            lbl = getattr(self, name, None)
            if lbl is not None:
                lbl.setText(text or "")

        def cached(path, key, computer):
            entry = self._info_cache.get((path, key))
            if entry is not None:
                return entry
            try:
                entry = computer(path)
            except Exception as e:
                entry = f"unreadable ({type(e).__name__})"
            self._info_cache[(path, key)] = entry
            return entry

        def h5_shape(fn, dataset, fmt):
            import h5py
            with h5py.File(fn, "r") as f:
                ids = dataset(f)
                return fmt(ids)

        # head mesh: a SimNIBS .msh read is slow -> worker thread
        mesh_fn = self.loadmeshlabel.text().strip()
        if mesh_fn.lower().endswith(".msh") and os.path.isfile(mesh_fn):
            pending = self._info_cache.get((mesh_fn, "mesh_pending"))
            done = self._info_cache.get((mesh_fn, "mesh"))
            if done is not None:
                set_info("info_mesh", done)
            elif pending is None:
                self._info_cache[(mesh_fn, "mesh_pending")] = True
                def _mesh_worker():
                    try:
                        from simnibs import mesh_io
                        m = mesh_io.read_msh(mesh_fn)
                        n_tet = int((m.elm.elm_type == 4).sum())
                        n_tri = int((m.elm.elm_type == 2).sum())
                        text = f"{n_tet:,} tets · {n_tri:,} tris"
                    except Exception as e:
                        text = f"unreadable ({type(e).__name__})"
                    self._info_cache[(mesh_fn, "mesh")] = text
                    QtCore.QTimer.singleShot(0, lambda: set_info("info_mesh", text))
                import threading
                threading.Thread(target=_mesh_worker, daemon=True).start()
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
            done = self._info_cache.get((coil_fn, "coil"))
            pending = self._info_cache.get((coil_fn, "coil_pending"))
            if done is not None:
                set_info("info_coil", done)
            elif pending is None:
                self._info_cache[(coil_fn, "coil_pending")] = True
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
                    self._info_cache[(coil_fn, "coil")] = text
                    QtCore.QTimer.singleShot(0, lambda: set_info("info_coil", text))
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
            set_info("info_results", f"exists · {kb} KB")
        elif res_fn:
            set_info("info_results", "will be created")

    # ── Project file state ─────────────────────────────────────────────────
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
            # strip previously appended scaling rules (both forms)
            ss = re.sub(r"\s*/\* neuropilot font scaling \*/\s*\n?\w[\w:]* \{ font-size: \d+px; \}", "", ss)
            ss = re.sub(r"\s*/\* neuropilot font scaling \*/ font-size: \d+px;", "", ss)
            selector = widget.metaObject().className()
            widget.setStyleSheet(
                ss.rstrip()
                + f"\n/* neuropilot font scaling */\n{selector} {{ font-size: {px}px; }}\n")

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
        super().showEvent(event)

    def _capture_base_rects_now(self):
        self._base_rects = self._capture_base_rects()
        # Apply the current scale immediately so a window resized before the
        # capture is consistent from the first paint after it.
        self._rescale()

    def resizeEvent(self, event):
        if getattr(self, "_base_rects", None) is None:
            return
        # Cheap pass on every resize event: geometry only.
        self._rescale_geometry()
        # The tab bar itself is resized by the layout after this event, so
        # place the LED corner once that has settled (otherwise it keeps the
        # old x position and the last LED is clipped).
        QtCore.QTimer.singleShot(0, self._place_tab_corner)
        # Expensive pass (full stylesheet repolish + setFont on every widget):
        # deferred so dragging stays smooth, and skipped entirely when the
        # rounded pixel sizes did not change.
        if not getattr(self, "_styles_timer_pending", False):
            self._styles_timer_pending = True
            QtCore.QTimer.singleShot(150, self._apply_styles_if_needed)
        super().resizeEvent(event)

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
        s = self._current_scale()
        last = getattr(self, "_last_style_scale", None)
        if last is not None and abs(s - last) < 0.04:
            return  # rounded pixel sizes unchanged — skip the expensive pass
        self._last_style_scale = s
        self._rescale_styles(s)

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
        for w, base in self._base_rects["rects"].items():
            x, y, ww, hh = base.x(), base.y(), base.width(), base.height()
            if w.parentWidget() is central:
                w.setGeometry(round(x * s + ox), round(y * s + oy),
                              round(ww * s), round(hh * s))
            else:
                w.setGeometry(round(x * s), round(y * s), round(ww * s), round(hh * s))

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
        for w, base_sheet in self._base_rects["sheets"].items():
            w.setStyleSheet(scale_px(base_sheet) if base_sheet else "")

        # Fonts scale with the window for every descendant.
        for w, base_px in self._base_rects["fonts"].items():
            self._apply_font_px(w, max(9, round(base_px * s)))

        # Font and style changes alter size hints; re-activate the layout tree
        # so rows sized from label/font metrics stop clipping at larger scales.
        for widget in self.centralwidget.findChildren(QtWidgets.QWidget):
            lay = QtWidgets.QWidget.layout(widget)
            if lay is not None:
                lay.activate()
        self.centralwidget.updateGeometry()
        self._place_tab_corner()
        self._sync_project_gap()

    def on_efield_mode_changed(self):
        if not (self.online_efield_btn.isChecked() or self.offline_efield_btn.isChecked()):
            return
        if self.controller:
            self.controller.online_fem_mgr.online_fem = self.online_efield_btn.isChecked()
            if self.controller.online_fem_mgr.is_online:
                import threading
                # self.controller.online_fem_mgr.ready = False #redundent
                #threading.Thread(target=self.controller.online_fem_mgr.init_background, daemon=True).start()
                self.controller.online_fem_mgr.init_background(callback=self.update_button_states)

        #self.online_efield_btn.setEnabled(False)
        #self.offline_efield_btn.setEnabled(False)
        if self.online_efield_btn.isChecked():
            self.offline_efield_btn.setEnabled(False)  # grey out the other
        else:
            self.online_efield_btn.setEnabled(False)  # grey out the other
        self.efield_mode_selected = True
        self.update_button_states()

    def _check_paths_ready(self):
        all_set = (
                self.controller
                and self.controller.online_fem_mgr.mesh_fn_msh
                and self.controller.online_fem_mgr.roi_fn_hdf5
                and self.controller.online_fem_mgr.coil_fn
        )
        if not self.efield_mode_selected:
            self.online_efield_btn.setEnabled(bool(all_set))
            self.offline_efield_btn.setEnabled(bool(all_set))

    def update_button_states(self):
        if not self.efield_mode_selected:
            self.start_btn.setEnabled(False)
            self.skiptarget.setEnabled(False)
            self.back_btn.setEnabled(False)
            return

        fem_ok = True
        if self.controller and self.controller.online_fem_mgr.is_online:
            fem_ok = self.controller.online_fem_mgr.is_ready

        # Manual mode runs without a robot system: the operator is the robot.
        robot_ok = ((self.controller is not None and getattr(self.controller, "manual", False))
                    or self.robot_ready)

        if robot_ok and self.stim_ready and self.emg_ready and fem_ok:
            self.start_btn.setEnabled(True)
            self.skiptarget.setEnabled(True)
            self.back_btn.setEnabled(True)
        else:
            self.start_btn.setEnabled(False)
            self.skiptarget.setEnabled(False)
            self.back_btn.setEnabled(False)

    def update_mesh_coloring(self, scores_dict):
        """
        Called by Controller.
        scores_dict: {'ADC 0': array, 'ADC 1': array, ...}
        """
        if hasattr(self, 'widget_3d_viewer'):
            self.widget_3d_viewer.apply_scores(scores_dict)

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
            #print(f"time vals len/max: {len(time_vals)} / {max(time_vals)}")
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
                    exclusion=self.controller.excluded_pulse_indices
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

            if "robot" in name:
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

    def update_robot_view(self, jpeg_bytes: bytes):
        """Show one frame of the simulated robot's overview camera in the
        panel below the logger. Real-hardware mode never receives frames,
        so the panel stays clean there."""
        if getattr(self, "_robot_view_disabled", False):
            return
        label = self.robot_view_label
        now = time.monotonic()
        # Throttle the GUI updates (the stream is 10 Hz; painting every
        # frame is wasted work when frames arrive faster than repaints).
        if now - getattr(self, "_last_robot_view_update", 0.0) < 0.08:
            return
        self._last_robot_view_update = now
        pixmap = QPixmap()
        if not pixmap.loadFromData(jpeg_bytes, "JPEG"):
            return
        # Fill the panel completely (crop the overflow) so no dark bands
        # appear above/below the frame.
        scaled = pixmap.scaled(label.width(), label.height(),
                               Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        label.setPixmap(scaled)

    # Maps a system name fragment to its details card widget prefix.
    INFO_PREFIXES = (("stim", "stim_info"), ("emg", "emg_info"),
                     ("robot", "robot_info"))

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

        # By default: disable Recover
        if recover_button is not None:
            recover_button.setEnabled(False)
            self.pending_recovery[system] = None

        if status == SystemStatus.OK:
            status_label.setStyleSheet("color: #0D9E42")
            status_label.setText("OK")
            self.set_led_status(led_widget, "on", "green")
            if message_label:
                message_label.setText("")

        elif status == SystemStatus.ERROR:
            status_label.setStyleSheet("color: #B50E0E")
            status_label.setText("ERROR")
            self.set_led_status(led_widget, "on", "red")

            msg_text = message

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
            status_label.setStyleSheet("color: #595959")
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

        if "robot" in name:
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
        if self.controller:
            self.slider1_spinbox1(20)
            # Push the restored session values to the controller (the cache
            # was loaded before the controller existed) — this also lets the
            # user's last amplitude override the default 20 above.
            self._apply_pending_session()

    # functions for the elements in the second Tap
    # === BEGIN: Handlers for loading the Mesh ===
    def pick_mesh(self):
        """Opens file dialog and loads mesh into the 3D widget."""
        file_path = self._file_dialog(
                "Select Mesh File",
                os.getcwd(),
                "HDF5 Files (*.hdf5 *.h5);;VTK Files (*.vtk)",
                save=False
        )
        if file_path:
            # just show path in QLineEdit
            self.loadmeshlabel.setText(file_path)
            print(f"Loading mesh: {file_path}")
            if hasattr(self, 'widget_3d_viewer'):
                self.widget_3d_viewer.load_hdf5_mesh(file_path, mesh_type="head")
            if self.controller:
                self.controller.online_fem_mgr.set_mesh_fn_msh(file_path)
            self._check_paths_ready()

    def paste_mesh_path(self):
        file_path = self.loadmeshlabel.text().strip()
        if not file_path:
            print("No file path given.")
            if hasattr(self, 'widget_3d_viewer'):
                self.widget_3d_viewer.load_hdf5_mesh(file_path, mesh_type="head")
            if self.controller:
                self.controller.online_fem_mgr.set_mesh_fn_msh(None)
            self._check_paths_ready()

        # Check if the file actually exists on the drive
        elif os.path.isfile(file_path):
            print(f"Loading mesh: {file_path}")
            if hasattr(self, 'widget_3d_viewer'):
                self.widget_3d_viewer.load_hdf5_mesh(file_path, mesh_type="head")
            if self.controller:
                self.controller.online_fem_mgr.set_mesh_fn_msh(file_path)
                self.controller.set_head_mesh(file_path)
            self._check_paths_ready()
        else:
            # The file is missing or the user typed a directory instead of a file
            print(f"Wrong path: The file '{file_path}' does not exist.")
            self.loadmeshlabel.setText("")
            if self.controller:
                self.controller.online_fem_mgr.set_mesh_fn_msh(None)
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
        if file_path and os.path.isfile(file_path) and self.controller:
            self.controller.set_emg_config(file_path)

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
            if hasattr(self, 'widget_3d_viewer'):
                # Call the new HDF5 loader
                self.widget_3d_viewer.load_hdf5_mesh(file_path, mesh_type="roi")
            if self.controller:
                self.controller.online_fem_mgr.set_roi_fn_hdf5(file_path)
            self._check_paths_ready()

    def paste_roi_path(self):
        file_path = self.loadroilabel.text().strip()
        if not file_path:
            print("No file path given.")
            if hasattr(self, 'widget_3d_viewer'):
                self.widget_3d_viewer.load_hdf5_mesh(file_path, mesh_type="roi")
            if self.controller:
                self.controller.online_fem_mgr.set_roi_fn_hdf5(None)
            self._check_paths_ready()

        # Check if the file actually exists on the drive
        elif os.path.isfile(file_path):
            print(f"Loading ROI: {file_path}")
            if hasattr(self, 'widget_3d_viewer'):
                self.widget_3d_viewer.load_hdf5_mesh(file_path, mesh_type="roi")
            if self.controller:
                self.controller.online_fem_mgr.set_roi_fn_hdf5(file_path)
                # The EMG source projection runs against this ROI: re-apply
                # the channel config so xyz sources re-project.
                if self.emg_config_label.text().strip():
                    self.controller.set_emg_config(self.emg_config_label.text().strip())
            self._check_paths_ready()
        else:
            # The file is missing or the user typed a directory instead of a file
            print(f"Wrong path: The file '{file_path}' does not exist.")
            self.loadroilabel.setText("")
            if self.controller:
                self.controller.online_fem_mgr.set_roi_fn_hdf5(None)
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
            if self.controller:
                self.controller.set_targets_file(file_path_coil_placement)

    def paste_coil_placements_path(self):
        file_path = self.loadplacementlabel.text().strip()
        if not file_path:
            print("No file path given.")
            if self.controller:
                self.controller.set_targets_file(None)

        # Check if the file actually exists on the drive
        elif os.path.isfile(file_path):
            if self.controller:
                self.controller.set_targets_file(file_path)
        else:
            # The file is missing or the user typed a directory instead of a file
            print(f"Wrong path: The file '{file_path}' does not exist.")
            self.loadplacementlabel.setText("")
            # Optional: UI popup here to warn the user visually
    # === END: Handlers for loading the coil placements ===

    # === BEGIN: Handlers for loading the E-Field ===
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
            if self.controller:
                self.controller.set_e_matrix_file(file_path)

    def paste_e_field_path(self):
        file_path = self.load_e_matrix_label.text().strip()
        if not file_path:
            print("No file path given.")
            if self.controller:
                self.controller.set_e_matrix_file(file_path)

        # Check if the file actually exists on the drive
        elif os.path.isfile(file_path):
            if self.controller:
                print(f"Loading E Field: {file_path}")
                self.controller.set_e_matrix_file(file_path)
        else:
            # The file is missing or the user typed a directory instead of a file
            print(f"Wrong path: The file '{file_path}' does not exist.")
            self.load_e_matrix_label.setText("")
            # Optional: UI popup here to warn the user visually
    # === END: Handlers for loading the E-Field ===

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
            try:
                with open(file_path, "r") as f:
                    data = yaml.safe_load(f)
            except (OSError, yaml.YAMLError) as e:
                QtWidgets.QMessageBox.warning(
                    self, "Invalid YAML",
                    f"Could not load config file:\n{e}"
                )
                return
            self._project_loading = True
            try:
                self.apply_config_dict(data)
            finally:
                self._project_loading = False
            self._project_file = file_path
            self._project_dirty = False
            # The stored name wins; fall back to the file name.
            if not self.project_name_edit.text().strip():
                self.project_name_edit.setText(os.path.basename(file_path))
            self._update_project_label()
            self._save_session_cache()

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
            # 1. Ensure the file has the correct extension
            if not file_path.lower().endswith(('.yaml', '.yml')):
                file_path += '.yaml'

            # 2. An empty name field adopts the file name (stored in the
            #    project file via get_config_dict below).
            if not self.project_name_edit.text().strip():
                self.project_name_edit.setText(os.path.basename(file_path))

            # 3. Get the state and save
            data = self.get_config_dict()
            with open(file_path, "w") as f:
                yaml.dump(data, f, default_flow_style=False)

            # 4. The saved file becomes the project file, changes are saved
            self._project_file = file_path
            self._project_dirty = False
            self._update_project_label()
            self._save_session_cache()

            print(f"Configuration successfully saved to: {file_path}")


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
    def get_config_dict(self):
        """Return controller and GUI parameters as a plain dict."""
        return {
            "project_name": self.project_name_edit.text().strip() or None,
            "fit_fun": self.fitFunctionComboBox.currentText(),
            "map_elms": self.sampling_spinBox.value(),
            "results_fn": self.savePathLineEdit.text() or None,
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
            "coil_path": self.coilspathlineedit.text() or None,
            "emg_config_fn": self.emg_config_label.text() or None,

        }

    def apply_config_dict(self, d):
        """Apply only the keys present in d to controller state and UI."""
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
            "target_order_fn": lambda v: (self.target_order_LineEdit.setText(v or ""),self.paste_target_order_path()),
            "targets_file": lambda v: (self.loadplacementlabel.setText(v or ""), self.paste_coil_placements_path()),
            "mesh_head_path": lambda v: (self.loadmeshlabel.setText(v or ""),self.paste_mesh_path()),
            "mesh_RIO_path": lambda v: (self.loadroilabel.setText(v or ""),self.paste_roi_path()),
            "e_field_path": lambda v: (self.load_e_matrix_label.setText(v or ""),self.paste_e_field_path()),
            "coil_path": lambda v: (self.coilspathlineedit.setText(v or ""), self.paste_coil_path()),
            "emg_config_fn": lambda v: (self.emg_config_label.setText(v or ""), self.paste_emg_config()),
        }

        # Iterate through the config and apply the values using the matched setter function
        for key, setter in setters.items():
            if key in d:
                val = d[key]
                # For SpinBoxes, we must ensure we don't pass a None value
                if val is None and key not in ["project_name", "results_fn", "target_order_fn", "targets_file",
                                               "mesh_head_path", "mesh_RIO_path", "e_field_path", "coil_path",
                                               "emg_config_fn"]:
                    continue

                    # Execute the matched function
                setter(val)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
