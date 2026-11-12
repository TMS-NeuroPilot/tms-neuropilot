from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QFrame, QCheckBox, QRadioButton, \
    QButtonGroup, QSizePolicy
from PyQt5 import QtGui
from PyQt5.QtCore import QPoint, QRectF, Qt, pyqtSignal
import pyvista as pv
from pyvistaqt import QtInteractor
import h5py
import numpy as np

# Initial camera direction for the 3D view (unit-norm on use): from the
# subject's upper left, slightly posterior — nose pointing left, vertex up.
# Same home view for head and ROI meshes.
HOME_VIEW_DIRECTION = np.array([-0.75, -0.30, 0.58])


class LoadCancelled(Exception):
    """Raised when a worker is stopped before it builds a VTK object."""


def _read_simnibs_msh_file(file_path):
    """Read a SimNIBS .msh without touching Qt (safe in a worker thread).

    Returns ``(nodes, triangles, tissue_tags, n_tets)`` or ``None`` when the
    file cannot be read.  The caller gets the readable error message from the
    log; the worker path turns ``None`` into an exception instead.
    """
    try:
        from simnibs import mesh_io
        m = mesh_io.read_msh(file_path)
        tri_mask = m.elm.elm_type == 2  # surface triangles (tets are 4)
        n_tet = int((m.elm.elm_type == 4).sum())
        nodes = m.nodes.node_coord[:, :3]
        tr_con = m.elm.node_number_list[tri_mask][:, :3].astype(int) - 1
        tri_tissue_type = m.elm.tag1[tri_mask].astype(int) % 1000  # 1001..1005 -> 1..5
        return nodes, tr_con, tri_tissue_type, n_tet
    except Exception as e:
        print(f"Error reading SimNIBS mesh {file_path}: {e}")
        import traceback
        traceback.print_exc()
        return None


def _read_hdf5_mesh_arrays(file_path):
    """Read the arrays of a pynibs/ROI geo HDF5 (no Qt, worker-safe)."""
    with h5py.File(file_path, 'r') as f:
        nodes = f['mesh/nodes/node_coord'][:]
        tr_con = f['/mesh/elm/triangle_number_list'][:]
        tri_tissue_type = (f['/mesh/elm/tri_tissue_type'][:]
                           if '/mesh/elm/tri_tissue_type' in f else None)
    return nodes, tr_con, tri_tissue_type


def _mesh_from_arrays(nodes, tr_con, tri_tissue_type, mesh_type,
                      stop_event=None):
    """Build the display PolyData from mesh arrays.

    No Qt and no renderer access: the caller may run this in a worker thread
    and hand the finished object to the GUI thread.  The optional 90 %
    decimation of a large head surface is part of the read rather than the
    first paint, because it is the expensive part of opening a head mesh.
    ``stop_event`` is checked before any VTK object is created so closing the
    window during a long read does not leave a worker using VTK after the
    Qt application has gone away.
    """
    if stop_event is not None and stop_event.is_set():
        raise LoadCancelled()
    n_faces = tr_con.shape[0]
    padding = np.full((n_faces, 1), 3)
    faces_flat = np.hstack((padding, tr_con)).flatten().astype(int)
    loaded_mesh = pv.PolyData(nodes, faces_flat)

    if tri_tissue_type is not None:
        n_data = len(tri_tissue_type)
        n_points = loaded_mesh.n_points
        n_cells = loaded_mesh.n_cells
        print(f"Data mapping: {n_data} values -> {n_points} Points / {n_cells} Cells")
        if n_data == n_points:
            loaded_mesh.point_data["Tissue Type"] = tri_tissue_type
        elif n_data == n_cells:
            loaded_mesh.cell_data["Tissue Type"] = tri_tissue_type
        else:
            print(f"[WARNING] Data length ({n_data}) matches neither Points nor Cells.")

    if mesh_type == "head" and loaded_mesh.n_cells > 200000:
        if stop_event is not None and stop_event.is_set():
            raise LoadCancelled()
        try:
            loaded_mesh = loaded_mesh.decimate(0.9)
            print(f"Head mesh decimated for display: {loaded_mesh.n_cells} triangles")
        except Exception as e:
            print(f"[WARN] head decimation skipped: {e}")
    if stop_event is not None and stop_event.is_set():
        raise LoadCancelled()
    return loaded_mesh, n_faces


def read_mesh_file(file_path, mesh_type="head", stop_event=None):
    """Read a display mesh and return ``(PolyData, summary)``.

    This is the worker-thread entry point used by the GUI.  It handles both
    SimNIBS ``*.msh`` files and pynibs/ROI HDF5 files and never touches a
    widget, so the window stays responsive while a large mesh is read and
    decimated.
    """
    if str(file_path).lower().endswith(".msh"):
        loaded = _read_simnibs_msh_file(file_path)
        if loaded is None:
            raise ValueError(f"could not read SimNIBS mesh: {file_path}")
        if stop_event is not None and stop_event.is_set():
            raise LoadCancelled()
        nodes, tr_con, tri_tissue_type, n_tet = loaded
        mesh, n_faces = _mesh_from_arrays(nodes, tr_con, tri_tissue_type,
                                          mesh_type, stop_event=stop_event)
        summary = f"{n_tet:,} tets · {n_faces:,} tris"
    else:
        nodes, tr_con, tri_tissue_type = _read_hdf5_mesh_arrays(file_path)
        if stop_event is not None and stop_event.is_set():
            raise LoadCancelled()
        mesh, n_faces = _mesh_from_arrays(nodes, tr_con, tri_tissue_type,
                                          mesh_type, stop_event=stop_event)
        summary = f"{n_faces:,} triangles"
    return mesh, summary


class _ScalarLegend(QWidget):
    """Compact legend: large title, thin bar, values at the bar ends."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setStyleSheet("background: transparent;")
        self._title = ""
        self._minimum = ""
        self._maximum = ""
        self._colours = []
        self._ink = QtGui.QColor("#1B1F24")
        self.setFixedHeight(52)
        self.hide()

    def set_legend(self, title, minimum, maximum, colours, ink=None):
        self._title = str(title or "")
        self._minimum = str(minimum)
        self._maximum = str(maximum)
        self._colours = list(colours or [])
        if ink is not None:
            self._ink = QtGui.QColor(ink)
        self.show()
        self.raise_()
        self.update()

    def clear_legend(self):
        self._title = ""
        self._minimum = ""
        self._maximum = ""
        self._colours = []
        self.hide()

    def set_ink(self, ink):
        self._ink = QtGui.QColor(ink)
        self.update()

    def paintEvent(self, event):
        if not self._colours or not self._title:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        base_px = self.font().pixelSize()
        if base_px <= 0:
            base_px = 16
        title_font = QtGui.QFont(self.font())
        title_font.setPixelSize(max(13, round(base_px * 1.2)))
        label_font = QtGui.QFont(self.font())
        label_font.setPixelSize(max(9, round(base_px * 0.8)))
        title_metrics = QtGui.QFontMetrics(title_font)
        label_metrics = QtGui.QFontMetrics(label_font)

        title_h = title_metrics.height()
        bar_h = max(6, round(base_px * 0.667))
        label_w = max(label_metrics.horizontalAdvance(self._minimum),
                      label_metrics.horizontalAdvance(self._maximum)) + 8
        bar_x = label_w
        bar_w = max(20, self.width() - 2 * label_w)
        bar_y = title_h + 4

        painter.setFont(title_font)
        painter.setPen(self._ink)
        painter.drawText(QRectF(0, 0, self.width(), title_h),
                         Qt.AlignHCenter | Qt.AlignVCenter, self._title)

        gradient = QtGui.QLinearGradient(bar_x, 0, bar_x + bar_w, 0)
        for index, colour in enumerate(self._colours):
            position = index / max(1, len(self._colours) - 1)
            gradient.setColorAt(position, colour)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QtGui.QBrush(gradient))
        painter.drawRect(QRectF(bar_x, bar_y, bar_w, bar_h))

        painter.setFont(label_font)
        painter.setPen(self._ink)
        label_y = bar_y + (bar_h - label_metrics.height()) / 2
        painter.drawText(QRectF(0, label_y, label_w - 8,
                                      label_metrics.height()),
                         Qt.AlignRight | Qt.AlignVCenter, self._minimum)
        painter.drawText(QRectF(bar_x + bar_w + 8, label_y,
                                      label_w - 8, label_metrics.height()),
                         Qt.AlignLeft | Qt.AlignVCenter, self._maximum)
        painter.end()


class MeshWidget(QWidget):
    # Emitted while hovering/clicking: {"element", "xyz", "scores"} for the
    # ROI surface, {"index", "record"} for a realized coil placement.
    element_picked = pyqtSignal(dict)
    placement_picked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        # --- 1. Main Layout ---
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # --- 2. Top Control Bar ---
        self.controls_frame = QFrame()
        # Minimum height; the layout grows the bar with the (scaled) fonts.
        self.controls_frame.setMinimumHeight(40)
        # Scope the rule to this frame only: a bare QFrame selector also
        # matches every QLabel inside it and draws a line under their text.
        # The bar carries no bottom rule at all — it read as an underline
        # below the checkbox and the mesh radios.
        self.controls_frame.setObjectName("mesh_controls")
        self.controls_frame.setStyleSheet(
            "QFrame#mesh_controls { background-color: #FFFFFF; border: none; }")
        self.controls_layout = QHBoxLayout(self.controls_frame)
        self.controls_layout.setContentsMargins(10, 5, 10, 5)

        lbl = QLabel("Mesh colour:")
        lbl.setStyleSheet("font-weight: 600; color: #6B7280; font-size: 12px;")
        self._colour_caption = lbl
        self.controls_layout.addWidget(lbl)

        self.scalar_selector = QComboBox()
        # Wide enough for the longest entry; grows with the available space.
        self.scalar_selector.setMinimumWidth(280)
        from PyQt5.QtWidgets import QSizePolicy
        self.scalar_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.scalar_selector.setStyleSheet("""
                    /* 1. Main Box Styling */
                    QComboBox {
                        border: 1px solid #D9DDE3;
                        border-radius: 8px;
                        padding: 4px 10px;
                        background-color: #ffffff;
                        color: #333333;
                        font-size: 14px;
                    }

                    /* Hover state for the main box */
                    QComboBox:hover {
                        border: 1px solid #D97706; 
                    }

                    /* 2. The Drop-down Button area */
                    QComboBox::drop-down {
                        subcontrol-origin: padding;
                        subcontrol-position: top right;
                        width: 28px;
                        border-left: 1px solid #e0e0e0; /* Subtle divider */
                        border-top-right-radius: 4px;
                        border-bottom-right-radius: 4px;
                        background-color: #F4F5F7;
                    }

                    /* The Arrow itself */
                    QComboBox::down-arrow {
                        image: url(:/qt-project.org/styles/commonstyle/images/arrowdown.png);
                        width: 10px; 
                        height: 10px;
                    }

                    /* Disabled arrow (optional but good practice) */
                    QComboBox::down-arrow:disabled {
                        image: url(:/qt-project.org/styles/commonstyle/images/arrowdown_disabled.png);
                    }

                    /* 3. The Pop-up List (Menu) */
                    QComboBox QAbstractItemView {
                        border: 1px solid #D9DDE3;
                        border-radius: 4px;
                        background-color: #ffffff;
                        color: #333333;
                        selection-background-color: #D97706;
                        selection-color: #ffffff;
                        outline: none;     /* Completely removes the thin black focus line */
                        padding: 0px;      /* Removes the gap inside the box */
                        margin: 0px;       /* Removes the gap outside the box */
                    }

                    /* Add some spacing to the items inside the list */
                    QComboBox QAbstractItemView::item {
                        min-height: 28px;
                        padding-left: 8px; /* Restores the text padding nicely */
                        border: none;
                    }
                """)
        self.scalar_selector.addItem("No color")
        self.scalar_selector.currentIndexChanged.connect(self.update_scalars)
        self.controls_layout.addWidget(self.scalar_selector)

        # Checkbox to toggle edges
        self.edge_checkbox = QCheckBox("Show edges")
        self.edge_checkbox.setChecked(True)  # Mesh edges are visible by default
        # Pixel-based font: the app default font scales with the X screen DPI
        # and renders ~2x on high-DPI screens, larger than the rest of the panel.
        self.edge_checkbox.setStyleSheet("margin-left: 15px; color: #1B1F24; font-size: 13px;")
        self.edge_checkbox.stateChanged.connect(self.refresh_current_view)
        self.controls_layout.addWidget(self.edge_checkbox)

        # Radio Buttons for Mesh Type
        self.radio_group = QButtonGroup(self)
        self.radio_head = QRadioButton("Show Head")
        self.radio_roi = QRadioButton("Show ROI")
        self.radio_head.setChecked(True)
        # Pixel-based fonts (see edge_checkbox above)
        self.radio_head.setStyleSheet("margin-left: 15px; color: #1B1F24; font-size: 13px;")
        self.radio_roi.setStyleSheet("margin-left: 10px; color: #1B1F24; font-size: 13px;")

        self.radio_group.addButton(self.radio_head)
        self.radio_group.addButton(self.radio_roi)

        self.controls_layout.addWidget(self.radio_head)
        self.controls_layout.addWidget(self.radio_roi)

        self.radio_head.toggled.connect(self.toggle_mesh_view)
        self.radio_roi.toggled.connect(self.toggle_mesh_view)

        self.controls_layout.addStretch()
        self.layout.addWidget(self.controls_frame)

        # --- 3. The 3D Plotter ---
        self.plotter = QtInteractor(self)
        self.layout.addWidget(self.plotter)
        # Three-point kit lighting keeps folds and coil-like curvature
        # readable when the surface is a single colour with edge lines.
        self._ensure_lightkit()

        # <--- ADD THIS: PERFORMANCE SETTINGS --->
        # <--- start --->
        # This allows the resolution to drop slightly ONLY while you rotate
        # self.plotter.ren_win.SetDesiredUpdateRate(5.0)

        # This uses a faster lighting system
        # self.plotter.enable_lightkit()
        # <--- END --->

        self.plotter.set_background("#FFFFFF")     # apply_theme() overrides
        self.plotter.add_axes()
        self.plotter.view_isometric()

        self.current_mesh = None
        self.mesh_head = None
        self.mesh_roi = None
        self._cell_markers_info = []  # list of (cell_idx, color, label) tuples
        self._camera_mesh = None      # mesh the home camera was set for
        self._bar_title = ""
        # Data-layer channel key ('ADC 0') -> display name from EMG_CHANNELS.
        self.channel_display_names = {}

        # ── mapping-results overlays ─────────────────────────────────────
        self.placements = []            # realized coil placements (dicts)
        self.channel_keys = []          # data keys in display order
        self._scores = {}               # channel key -> R2 per ROI element
        self._placement_metric = ("mep", None)   # ("mep"|"trial"|"aim", key)
        self._show_placements = True
        self._show_coil_handles = True
        self._show_path = False
        self._best_element = None
        self._best_channel = None
        self._pulse_count = 0
        self._label_map = self._make_corner_label()
        self._label_pulses = self._make_corner_label(align_right=True)
        self._legend = _ScalarLegend(self)
        self._legend_ink = "#1B1F24"
        self._init_picking()
        self._install_shortcuts()

    # ── picking ──────────────────────────────────────────────────────────
    def _init_picking(self):
        from vtkmodules.vtkRenderingCore import vtkCellPicker
        self._picker = vtkCellPicker()
        self._picker.SetTolerance(0.01)
        self._last_pick_at = 0.0
        self._mouse_down = False
        self.plotter.setMouseTracking(True)
        self.plotter.iren.add_observer("MouseMoveEvent", self._on_mouse_move)
        self.plotter.iren.add_observer("LeftButtonPressEvent", self._on_left_press)
        self.plotter.iren.add_observer("LeftButtonReleaseEvent", self._on_left_release)

    def _on_left_press(self, obj, event):
        self._mouse_down = True
        self._emit_pick(obj, click=True)

    def _on_left_release(self, obj, event):
        self._mouse_down = False

    def _on_mouse_move(self, obj, event):
        # Hover picking while dragging the camera is pointless and costly.
        if self._mouse_down:
            return
        self._emit_pick(obj, click=False)

    def _emit_pick(self, iren, click):
        import time as _time
        now = _time.monotonic()
        if not click and now - self._last_pick_at < 0.06:
            return
        self._last_pick_at = now
        x, y = iren.GetEventPosition()
        name, picker = self._pick_at(x, y)
        if name == "placements":
            idx = picker.GetPointId()
            if 0 <= idx < len(self.placements):
                self.placement_picked.emit({"index": idx,
                                            "record": self.placements[idx],
                                            "click": click})
        elif name == "main_mesh" and self.current_mesh is self.mesh_roi:
            cid = picker.GetCellId()
            if cid is not None and cid >= 0:
                xyz = tuple(float(v) for v in picker.GetPickPosition())
                scores = {k: (float(v[cid]) if cid < len(v) else None)
                          for k, v in self._scores.items()}
                self.element_picked.emit({"element": int(cid), "xyz": xyz,
                                          "scores": scores, "click": click})

    def _pick_at(self, x, y):
        """Pick at window coords; returns (actor name, picker) or (None, None)."""
        self._picker.Pick(x, y, 0, self.plotter.renderer)
        actor = self._picker.GetActor()
        if actor is None:
            return None, None
        for name, candidate in self.plotter.actors.items():
            if candidate is actor:
                return name, self._picker
        return None, None

    # ── corner overlays ──────────────────────────────────────────────────
    def _make_corner_label(self, align_right=False):
        label = QLabel(self)
        label.setTextFormat(Qt.RichText)
        label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        label.setStyleSheet(
            "QLabel { background: rgba(255,255,255,0.88); color: #1B1F24;"
            " border: 1px solid #E2E5E9; border-radius: 6px;"
            " padding: 4px 10px; font-size: 14px; font-weight: 600; }")
        label.setAlignment((Qt.AlignRight if align_right else Qt.AlignLeft) | Qt.AlignVCenter)
        label.hide()
        return label

    def _position_corner_labels(self):
        margin = 14
        top = self.controls_frame.height() + margin
        for label, right in ((self._label_map, False), (self._label_pulses, True)):
            if label is None:
                continue
            label.adjustSize()
            x = (self.width() - margin - label.width()) if right else margin
            label.move(max(margin, x), top)
            label.raise_()
        self._position_legend()

    def _position_legend(self):
        legend = getattr(self, "_legend", None)
        if legend is None or not legend.isVisible():
            return
        base_px = self.font().pixelSize() or 16
        legend.setFixedHeight(max(36, round(52 * base_px / 16)))
        width = min(max(320, int(self.width() * 0.6)), max(200, self.width() - 40))
        legend.setFixedWidth(width)
        x = (self.width() - width) // 2
        y = self.height() - legend.height() - 16
        legend.move(max(0, x), max(0, y))
        legend.raise_()

    def set_pulse_count(self, count):
        self._pulse_count = int(count or 0)
        self._update_overlay_labels()

    def _update_overlay_labels(self):
        """Top-left: what the colours mean (muscle + metric); top-right:
        how many pulses are behind the picture."""
        mesh_label = ""
        if self.current_mesh is self.mesh_head:
            if self.placements and self._show_placements:
                kind, channel = self._placement_metric
                if kind == "trial":
                    mesh_label = "Trial id"
                elif kind == "aim":
                    mesh_label = "Aim error [mm]"
                else:
                    name = self.channel_display_names.get(channel, channel or "MEP")
                    mesh_label = f"{name}<br><span style='font-size:11px; color:#6B7280'>MEP size [mV]</span>"
        else:
            text = self.scalar_selector.currentText() if self.scalar_selector.count() else ""
            if text and text != "No color":
                if " mapping result" in text:
                    name, rest = text.split(" mapping result", 1)
                    mesh_label = (f"{name}<br><span style='font-size:11px; color:#6B7280'>"
                                  f"mapping result{rest}</span>")
                else:
                    mesh_label = text
        self._label_map.setText(mesh_label)
        self._label_map.setVisible(bool(mesh_label))
        count = self._pulse_count
        self._label_pulses.setText(
            f"{count}<span style='font-size:11px; color:#6B7280'> pulses</span>")
        self._label_pulses.setVisible(count > 0)
        self._position_corner_labels()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_corner_labels()

    def _install_shortcuts(self):
        """B mark best R², H toggle head/ROI, F home view (view has focus)."""
        from PyQt5.QtGui import QKeySequence
        from PyQt5.QtWidgets import QShortcut
        self.setFocusPolicy(Qt.StrongFocus)
        for keys, slot in (("B", self._shortcut_mark_best),
                           ("H", self._shortcut_toggle_mesh),
                           ("F", self._shortcut_home)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

    def _score_key(self):
        if self._best_channel in self._scores:
            return self._best_channel
        return next(iter(self._scores), None)

    def _shortcut_mark_best(self):
        self.mark_best_element(self._score_key())

    def _shortcut_toggle_mesh(self):
        if self.radio_head.isChecked():
            self.radio_roi.setChecked(True)
        else:
            self.radio_head.setChecked(True)

    def _shortcut_home(self):
        self._set_home_camera()
        self.plotter.render()

    # ── mapping results ──────────────────────────────────────────────────
    def set_mapping_results(self, placements, channel_keys):
        self.placements = list(placements or [])
        self.channel_keys = list(channel_keys or [])
        self._pulse_count = len(self.placements)
        self._refresh_overlays()

    def set_placement_options(self, show=None, handles=None, path=None):
        if show is not None:
            self._show_placements = bool(show)
        if handles is not None:
            self._show_coil_handles = bool(handles)
        if path is not None:
            self._show_path = bool(path)
        self._refresh_overlays()

    def set_placement_metric(self, kind, channel=None):
        self._placement_metric = (kind, channel)
        self._refresh_overlays()

    def _placement_values(self, records=None):
        """(values, title) for the current placement colour metric."""
        kind, channel = self._placement_metric
        values = []
        for rec in (records if records is not None else self.placements):
            if kind == "trial":
                values.append(float(rec.get("trial", 0)))
            elif kind == "aim":
                values.append(float(rec.get("aim_error_mm") or 0.0))
            else:
                mep = (rec.get("mep") or {}).get(channel)
                values.append(float(mep) if mep is not None else 0.0)
        if kind == "trial":
            title = "Trial"
        elif kind == "aim":
            title = "Aim error [mm]"
        else:
            name = self.channel_display_names.get(channel, channel)
            title = f"MEP {name} [mV]"
        return values, title

    def _refresh_overlays(self):
        """Redraw placement spheres/handles/path and the best-element mark."""
        for name in ("placements", "coil_handles", "placement_path",
                     "best_element", "best_element_pt"):
            self.plotter.remove_actor(name)

        on_head = self.current_mesh is self.mesh_head
        if on_head and self.placements and self._show_placements:
            self._draw_placements()
        if self.current_mesh is self.mesh_roi and self._best_element is not None:
            self._draw_best_element()
        self._update_overlay_labels()
        self.plotter.render()

    def _draw_placements(self):
        import numpy as np
        records = [rec for rec in self.placements if rec.get("position")]
        if not records:
            return
        points = np.array([rec["position"] for rec in records], dtype=float)
        # Lift the markers a few mm off the scalp (radial from the head
        # centre): the recorded coil points sit on the skin and would
        # otherwise be half-buried in the (opaque) head surface.
        if self.mesh_head is not None:
            centre = np.asarray(self.mesh_head.center)
            radial = points - centre
            norm = np.linalg.norm(radial, axis=1, keepdims=True) + 1e-9
            points = points + radial / norm * 6.0

        values, title = self._placement_values(records)
        values = np.asarray(values, dtype=float)
        finite = values[np.isfinite(values)]
        if finite.size:
            kind = self._placement_metric[0]
            # Robust upper clip for continuous metrics: a single MEP outlier
            # would otherwise flatten every other marker into one colour.
            upper = (float(np.percentile(finite, 95))
                     if kind in ("mep", "aim") else float(finite.max()))
            clim = (float(finite.min()), max(upper, float(finite.min()) + 1e-6))
        else:
            clim = (0.0, 1.0)
        self.plotter.add_points(points, scalars=values, cmap="turbo", clim=clim,
                                render_points_as_spheres=True, point_size=22,
                                name="placements", show_scalar_bar=False)
        self._add_scalar_bar(title, clim)

        if self._show_coil_handles:
            segments = [self._coil_handle_segment(rec, point)
                        for rec, point in zip(records, points)]
            segments = [s for s in segments if s is not None]
            if segments:
                vertices, lines = [], []
                for k, (start, end) in enumerate(segments):
                    vertices.extend([start, end])
                    lines.extend([2, 2 * k, 2 * k + 1])
                poly = pv.PolyData(np.asarray(vertices), lines=np.asarray(lines))
                # Sticks along the coil handle; dark slate reads on the light
                # scalp where a pale grey disappeared.
                self.plotter.add_mesh(poly, color="#3C4A56", line_width=5,
                                      opacity=0.9, name="coil_handles")

        if self._show_path and len(points) > 1:
            path = pv.lines_from_points(points)
            # Colour the path by acquisition order so the sequence stays
            # readable even when the coil jumps between targets.
            trials = np.array([float(rec.get("trial", i))
                               for i, rec in enumerate(records)])
            if trials.size == path.n_points:
                path["trial"] = trials
                self.plotter.add_mesh(path, scalars="trial", cmap="turbo",
                                      line_width=4, name="placement_path",
                                      show_scalar_bar=False)
            else:
                self.plotter.add_mesh(path, color="#D97706", line_width=4,
                                      name="placement_path")

    def _coil_handle_segment(self, record, origin=None):
        """(start, end) of the coil handle, in world space.

        SimNIBS coil frame: +z is the coil normal (pointing into the head),
        the figure-8 lobes lie along +/-x and the handle runs along **-y**
        (the casing of the B65 extends ~160 mm in that direction).  Using
        the normal here drew a spike out of the scalp instead of a handle.
        """
        import numpy as np
        from scipy.spatial.transform import Rotation
        try:
            pos = np.asarray(origin if origin is not None else record["position"])
            rot = record.get("rotation") or [0.0, 0.0, 0.0]
            rotation = Rotation.from_euler("xyz", rot, degrees=True)
            handle = rotation.apply([0.0, -1.0, 0.0])
            return pos + handle * 6.0, pos + handle * 70.0
        except Exception:
            return None

    # ── theme ───────────────────────────────────────────────────────────
    def apply_theme(self, theme):
        """Recolour the viewport, the picker and the corner labels."""
        self._theme = dict(theme)
        self.plotter.set_background(theme["canvas"])
        # The GL surface is a native window; the widget behind it (and every
        # grab/screenshot) shows the palette colour.
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(theme["canvas"]))
        self.setPalette(palette)
        self.controls_frame.setStyleSheet(
            f"QFrame#mesh_controls {{ background-color: {theme['canvas']};"
            " border: none; }")
        self._colour_caption.setStyleSheet(
            f"font-weight: 600; color: {theme['muted']}; font-size: 12px;")
        self._style_controls(theme)
        for widget in (self.edge_checkbox, self.radio_head, self.radio_roi):
            margin = "15px" if widget is not self.radio_roi else "10px"
            widget.setStyleSheet(
                f"margin-left: {margin}; color: {theme['ink']}; font-size: 13px;")
        for label in (getattr(self, "_label_map", None),
                      getattr(self, "_label_pulses", None)):
            if label is not None:
                label.setStyleSheet(
                    f"QLabel {{ background: {theme['card']};"
                    f" color: {theme['ink']}; border: 1px solid {theme['line']};"
                    " border-radius: 6px; padding: 6px 10px; font-size: 12px; }")
        self._style_scalar_bar()
        self._position_legend()
        self.plotter.render()

    def _style_controls(self, theme):
        self.scalar_selector.setStyleSheet(f"""
            QComboBox {{
                border: 1px solid {theme['edge']};
                border-radius: 8px;
                padding: 4px 10px;
                background-color: {theme['card']};
                color: {theme['ink']};
                font-size: 14px;
            }}
            QComboBox:hover {{ border: 1px solid {theme['accent']}; }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 28px;
                border-left: 1px solid {theme['line']};
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
                background-color: {theme['canvas']};
            }}
            QComboBox QAbstractItemView {{
                border: 1px solid {theme['edge']};
                border-radius: 4px;
                background-color: {theme['card']};
                color: {theme['ink']};
                selection-background-color: {theme['accent']};
                selection-color: {theme['on_accent']};
                outline: none;
                padding: 0px;
                margin: 0px;
            }}
        """)

    def _ensure_lightkit(self):
        """Recreate the renderer lights after plotter.clear().

        ``clear()`` removes every light, and without an explicit light the
        plain-colour surface renders as a flat silhouette.
        """
        try:
            self.plotter.enable_lightkit()
        except (AttributeError, RuntimeError):
            pass

    def _style_scalar_bar(self):
        theme = getattr(self, "_theme", None)
        if not theme:
            return
        rgb = [int(theme["ink"][i:i + 2], 16) / 255 for i in (1, 3, 5)]
        self._legend_ink = theme["ink"]
        legend = getattr(self, "_legend", None)
        if legend is not None:
            legend.set_ink(self._legend_ink)
        bars = getattr(self.plotter, "scalar_bars", None)
        if not bars:
            return
        try:
            items = bars.items()
        except AttributeError:
            return
        for _, bar in items:
            for prop in (bar.GetTitleTextProperty(), bar.GetLabelTextProperty()):
                prop.SetColor(*rgb)

    @staticmethod
    def _format_legend_value(value, title):
        """Match the scalar-bar label style: R² maps use two decimals."""
        try:
            value = float(value)
        except (TypeError, ValueError):
            return str(value)
        text = str(title or "").lower()
        if "mapping result" in text or "r2" in text or "r²" in text:
            return f"{value:.2f}"
        return f"{value:.3g}"

    def _legend_colours(self, bar):
        """Sample the scalar-bar lookup table for the Qt gradient."""
        colours = []
        try:
            lut = bar.GetLookupTable()
            count = int(lut.GetNumberOfTableValues()) if lut is not None else 0
            for index in range(max(0, count)):
                value = lut.GetTableValue(index)
                if value is not None and len(value) >= 3:
                    colours.append(QtGui.QColor.fromRgbF(*value[:3]))
        except (AttributeError, TypeError, ValueError):
            colours = []
        if not colours:
            # Keep the legend usable if VTK did not expose its lookup table.
            colours = [QtGui.QColor("#30123b"), QtGui.QColor("#4145ab"),
                       QtGui.QColor("#4675ed"), QtGui.QColor("#39a2fc"),
                       QtGui.QColor("#1bcfd4"), QtGui.QColor("#24eca6"),
                       QtGui.QColor("#61fc6c"), QtGui.QColor("#a4fc3b"),
                       QtGui.QColor("#d1e834"), QtGui.QColor("#f3c63a"),
                       QtGui.QColor("#fe9b2d"), QtGui.QColor("#f36315"),
                       QtGui.QColor("#d93806"), QtGui.QColor("#b11901"),
                       QtGui.QColor("#7a0402")]
        return colours

    def _add_scalar_bar(self, title, clim=None):
        """Draw a thin Qt legend with end labels instead of VTK tick labels.

        VTK puts horizontal scalar-bar labels above the colour strip; the Qt
        overlay places the minimum and maximum beside the bar and gives the
        title its own, larger type size. The VTK actor is kept only as the
        lookup-table source and is hidden.
        """
        self._bar_title = title or ""
        bar = self.plotter.add_scalar_bar(title="", n_labels=2,
                                          vertical=False, height=0.06,
                                          width=0.5, position_x=0.25,
                                          position_y=0.02)
        if bar is None:
            self._legend.clear_legend()
            return
        try:
            bar.SetDrawTickLabels(False)
            bar.SetTitle("")
            bar.SetDrawAnnotations(False)
        except AttributeError:
            pass
        if clim is None:
            try:
                clim = bar.GetLookupTable().GetRange()
            except (AttributeError, TypeError):
                clim = (0.0, 1.0)
        colours = self._legend_colours(bar)
        self._legend.set_legend(
            title,
            self._format_legend_value(clim[0], title),
            self._format_legend_value(clim[1], title),
            colours, getattr(self, "_legend_ink", "#1B1F24"))
        self._position_legend()
        try:
            bar.VisibilityOff()
        except AttributeError:
            pass
        self._style_scalar_bar()

    def _draw_best_element(self):
        import numpy as np
        cell = self.current_mesh.extract_cells(int(self._best_element))
        # Tube the triangle outline: a hairline disappears at normal zoom.
        outline = cell.extract_feature_edges()
        try:
            outline = outline.tube(radius=1.0, n_sides=8)
        except Exception:
            pass
        self.plotter.add_mesh(outline, color="#FF2D95", name="best_element")
        centre = np.asarray(cell.cell_centers().points[0]).reshape(1, 3)
        self.plotter.add_points(centre, color="#FF2D95", point_size=14,
                                render_points_as_spheres=True,
                                name="best_element_pt")

    def mark_best_element(self, channel_key=None):
        """Outline the highest-R2 element of ``channel_key`` (default: the
        first channel with scores).  Returns the element index or None."""
        import numpy as np
        key = channel_key if channel_key in self._scores else next(iter(self._scores), None)
        if key is None:
            return None
        scores = np.asarray(self._scores[key])
        if scores.size == 0:
            return None
        self._best_element = int(np.argmax(scores))
        self._best_channel = key
        self._refresh_overlays()
        return self._best_element

    def clear_marks(self):
        self._best_element = None
        self._best_channel = None
        self._refresh_overlays()

    def screenshot(self, path):
        """Render the view to a PNG, including the corner overlays (the VTK
        screenshot alone would drop the Qt labels)."""
        from PyQt5 import QtGui
        frame = self.plotter.screenshot(return_img=True)
        if frame is None:
            return False
        height, width = frame.shape[:2]
        image = QtGui.QImage(frame.data, width, height, 3 * width,
                             QtGui.QImage.Format_RGB888).copy()
        painter = QtGui.QPainter(image)
        scale_x = width / max(1, self.width())
        scale_y = height / max(1, self.height())
        for label in (self._label_map, self._label_pulses, self._legend):
            if not label.isVisible():
                continue
            pos = label.mapTo(self, QPoint(0, 0))
            pixmap = label.grab()
            painter.drawPixmap(int(pos.x() * scale_x), int(pos.y() * scale_y),
                               int(pixmap.width() * scale_x),
                               int(pixmap.height() * scale_y), pixmap)
        painter.end()
        return bool(image.save(path))

    def set_channel_display_names(self, names):
        """Map the ADC data keys to the configured EMG channel names so the
        results dropdown reads 'FDI mapping result [R2]' instead of 'Score
        ADC 0'."""
        names = list(names or [])
        self.channel_display_names = {f"ADC {i}": name
                                      for i, name in enumerate(names)}
        self.refresh_dropdown()

    def _display_name(self, data_key):
        """Human label for a mesh data array (results use the channel name)."""
        if data_key.startswith("Score "):
            channel = data_key[len("Score "):]
            return f"{self.channel_display_names.get(channel, channel)} mapping result [R2]"
        return data_key

    def mark_cells(self, cell_indices, colors, labels=None):
        """Add callout arrows pointing at cells + connecting line between first two."""
        self._cell_markers_info = list(zip(cell_indices, colors, labels or [''] * len(cell_indices)))
        self._render_cell_markers()

    def _render_cell_markers(self):
        """Render stored cell markers on the plotter."""
        # Remove old markers by name
        for name in ["cell_arrow_true", "cell_arrow_best", "cell_connect_line"]:
            self.plotter.remove_actor(name)

        if self.current_mesh is None or not self._cell_markers_info:
            self.plotter.render()
            return

        centers = self.current_mesh.cell_centers().points
        normals = self.current_mesh.face_normals
        bounds = self.current_mesh.bounds
        span = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4])
        offset = span * 0.055

        arrow_names = ["cell_arrow_true", "cell_arrow_best"]
        for i, (cell_idx, color, label) in enumerate(self._cell_markers_info):
            center = centers[cell_idx]
            normal = normals[cell_idx]
            arrow_start = center + normal * offset
            direction = -normal

            arrow = pv.Arrow(start=arrow_start, direction=direction, scale=3,
                             tip_length=0.43, tip_radius=0.23, shaft_radius=0.08)
            name = arrow_names[i] if i < len(arrow_names) else f"cell_arrow_{i}"
            self.plotter.add_mesh(arrow, color=color, name=name)

        # Draw geodesic path between first two cells (follows mesh surface)
        if len(self._cell_markers_info) >= 2:
            c1 = centers[self._cell_markers_info[0][0]]
            c2 = centers[self._cell_markers_info[1][0]]
            v1 = self.current_mesh.find_closest_point(c1)
            v2 = self.current_mesh.find_closest_point(c2)
            path = self.current_mesh.geodesic(v1, v2)
            self.plotter.add_mesh(path, color='yellow', line_width=7, name="cell_connect_line")

        self.plotter.render()

    def toggle_mesh_view(self):
        """Switches the current mesh between Head and ROI based on radio button selection."""
        # 1. Save the current selection state before switching
        previous_data_key = self.scalar_selector.currentData()
        previous_text = self.scalar_selector.currentText()

        # 2. Switch the active mesh
        if self.radio_head.isChecked():
            self.current_mesh = self.mesh_head
        elif self.radio_roi.isChecked():
            self.current_mesh = self.mesh_roi

        # 3. Refresh dropdown contents for the new mesh
        self.refresh_dropdown()

        # 4. Attempt to restore the previous selection
        if previous_text:
            index_by_text = self.scalar_selector.findText(previous_text)
            if index_by_text >= 0:
                self.scalar_selector.setCurrentIndex(index_by_text)
            else:
                # If the exact array isn't found, check if "Solid Color" exists as fallback
                fallback_index = self.scalar_selector.findText("No color")
                if fallback_index >= 0:
                    self.scalar_selector.setCurrentIndex(fallback_index)

        # If the new mesh offers results but the restored item is the plain
        # colour, show the first result instead.
        if self.scalar_selector.currentIndex() == 0 and self.scalar_selector.count() > 1:
            self.scalar_selector.blockSignals(True)
            self.scalar_selector.setCurrentIndex(1)
            self.scalar_selector.blockSignals(False)

        # 5. Redraw the scene based on the (restored) selection
        self.update_scalars(self.scalar_selector.currentIndex())

    # A helper function to toggle the visibility of the edges
    def refresh_current_view(self):
        """Forces the plotter to redraw with the new edge settings."""
        if self.current_mesh is not None:
            # Simply re-trigger the current scalar selection to redraw
            self.update_scalars(self.scalar_selector.currentIndex())

    def apply_scores(self, scores_dict):
        """
        Adds regression scores to the mesh and updates the dropdown.
        scores_dict: {'ADC 0': np.array, 'ADC 1': np.array}
        """
        if self.current_mesh is None:
            return

        try:

            # 1. Memorize exactly what the user is looking at right now
            #    (If "Solid Color", this will likely be None)
            previous_data_key = self.scalar_selector.currentData()
            previous_text = self.scalar_selector.currentText()

            # 2. Add every channel's score to the mesh data
            for channel_name, scores in scores_dict.items():

                # Check dimensions (Cell Data vs Point Data)
                self._scores[channel_name] = np.asarray(scores)
                if len(scores) == self.current_mesh.n_cells:
                    # Naming convention: "Score ADC 0"
                    data_name = f"Score {channel_name}"
                    #--- BEGIN NORMALIZATION SCORE BLOCK
                    # NEW: Normalize scores to [0, 1]
                   # scores_min = scores.min()
                   # scores_max = scores.max()
                   # if scores_max > scores_min:
                    #    scores = (scores - scores_min) / (scores_max - scores_min)
                    #else:
                    #    scores = np.zeros_like(scores)  # All same → map to 0
                    # --- END NORMALIZATION SCORE BLOCK

                    self.current_mesh.cell_data[data_name] = scores

                elif len(scores) == self.current_mesh.n_points:
                    data_name = f"Score {channel_name}"
                    # --- BEGIN NORMALIZATION SCORE BLOCK
                    # NEW: Normalize scores to [0, 1]
                   # scores_min = scores.min()
                   # scores_max = scores.max()
                   # if scores_max > scores_min:
                     #   scores = (scores - scores_min) / (scores_max - scores_min)
                    #else:
                     #   scores = np.zeros_like(scores)  # All same → map to 0
                    # --- END NORMALIZATION SCORE BLOCK
                    self.current_mesh.point_data[data_name] = scores

                else:
                    print(f"Skipping {channel_name}: Data length {len(scores)} matches neither Cells nor Points.")

            # 3. Refresh the dropdown
            # (This scans the mesh again and will find the new 'Score ADC X' arrays)
            self.refresh_dropdown()

            # 4. RESTORE SELECTION
            # We look for the item that has the same data key as before.
            index = self.scalar_selector.findData(previous_data_key)

            if index > 0:
                # Found it! Switch back to it immediately.
                self.scalar_selector.setCurrentIndex(index)
            elif previous_data_key is None and self.scalar_selector.count() > 1:
                # Nothing was selected before (findData(None) matches the
                # placeholder): show the first R² map instead of leaving the
                # surface uncoloured.
                self.scalar_selector.setCurrentIndex(1)
            else:
                # If we couldn't match the data key (maybe it was Solid Color with no data),
                # try to match the text label (e.g. "Solid Color (No Data)")
                index_by_text = self.scalar_selector.findText(previous_text)
                if index_by_text >= 0:
                    self.scalar_selector.setCurrentIndex(index_by_text)

            # Note: We do NOT force an update to a new channel here.
            # If the user was watching "Score ADC 1", they stay on "Score ADC 1".
            # If they were watching "Solid Color", they stay on "Solid Color".

            # Force the 3D window to redraw just in case the numbers changed
            # for the *current* view (e.g. Analysis updated the heatmap you are currently watching)
            self.plotter.render()

        except Exception as e:
            print(f"Error applying scores: {e}")

    def load_hdf5_mesh(self, file_path, mesh_type="head"):
        """
        Loads mesh data and creates a PyVista PolyData object.
        mesh_type can be "head" or "roi".

        Supported formats:
        - SimNIBS ``*.msh`` (read via simnibs mesh_io; the head mesh in the
          m2m folder) — triangles and their tissue tags
        - ``*.hdf5`` meshes with ``/mesh/nodes/node_coord`` and
          ``/mesh/elm/triangle_number_list`` (ROI geo files)

        The GUI uses :func:`read_mesh_file` in a worker and then
        :meth:`set_loaded_mesh`; this synchronous entry point remains for
        tests, tools and scripts that already run off the GUI thread.
        """
        # 1. Guard Clause: Handle the empty state
        if not file_path:
            print(f"3D Viewer: Empty path received for {mesh_type}. Wiping corresponding mesh.")
            if mesh_type == "head":
                self.mesh_head = None
            elif mesh_type == "roi":
                self.mesh_roi = None

            self.toggle_mesh_view()
            return

        # 2. Proceed with loading the actual file
        try:
            if str(file_path).lower().endswith(".msh"):
                loaded_mesh = self._load_simnibs_msh(file_path)
                if loaded_mesh is None:
                    return
                nodes, tr_con, tri_tissue_type = loaded_mesh
            else:
                nodes, tr_con, tri_tissue_type = _read_hdf5_mesh_arrays(file_path)

            loaded_mesh, n_faces = _mesh_from_arrays(
                nodes, tr_con, tri_tissue_type, mesh_type)
            self.set_loaded_mesh(loaded_mesh, mesh_type)

            print(f"Successfully loaded HDF5 {mesh_type} Mesh: {n_faces} triangles.")

        except Exception as e:
            print(f"Error loading HDF5 mesh: {e}")
            import traceback
            traceback.print_exc()

    def set_loaded_mesh(self, loaded_mesh, mesh_type="head", select=True):
        """Install a mesh prepared by :func:`read_mesh_file`.

        ``select=False`` stores the surface without switching the radio: when
        a project loads the head and ROI concurrently the completion order is
        not the request order, and the last requested surface must stay the
        visible one.
        """
        if mesh_type == "head":
            self.mesh_head = loaded_mesh
            if select:
                self.radio_head.setChecked(True)
        elif mesh_type == "roi":
            self.mesh_roi = loaded_mesh
            if select:
                self.radio_roi.setChecked(True)
        if select:
            self.toggle_mesh_view()

    def _load_simnibs_msh(self, file_path):
        """Read a SimNIBS ``*.msh`` mesh: returns ``(nodes, triangles,
        tissue_tags)`` or ``None`` on failure. The tags (1001..1005 for the
        five SimNIBS tissues) are remapped to 1..5 so both mesh sources
        color consistently, and the 1-based node numbers are converted to
        0-based for VTK."""
        loaded = _read_simnibs_msh_file(file_path)
        return loaded[:3] if loaded is not None else None

    def refresh_dropdown(self):
        """Populates the dropdown with the available mapping results.

        Tissue tags are deliberately not offered: the viewer shows the
        anatomy in plain colour and only overlays computed results (the
        'Score <channel>' arrays) or nothing ('No color')."""
        self.scalar_selector.blockSignals(True)
        self.scalar_selector.clear()
        self.scalar_selector.addItem("No color")

        if self.current_mesh:
            keys = []
            for data in (self.current_mesh.point_data, self.current_mesh.cell_data):
                for name in data.keys():
                    if name == "Tissue Type":
                        continue
                    keys.append(name)
            for raw_name in sorted(set(keys), key=lambda n: self._display_name(n).lower()):
                self.scalar_selector.addItem(self._display_name(raw_name), raw_name)

        self.scalar_selector.blockSignals(False)

    def _set_home_camera(self):
        """Initial perspective: camera on the subject's upper left, slightly
        posterior — the nose points left and the vertex is up. Distance is
        set relative to the mesh diagonal so both the head and the (much
        smaller) ROI frame nicely."""
        if self.current_mesh is None:
            return
        center = np.array(self.current_mesh.center)
        bounds = np.array(self.current_mesh.bounds)
        length = np.linalg.norm(bounds[1::2] - bounds[::2])
        direction = HOME_VIEW_DIRECTION / np.linalg.norm(HOME_VIEW_DIRECTION)
        self.plotter.camera_position = [center + direction * length * 1.9,
                                        center, (0, 0, 1)]

    def update_scene_default(self):
        """Renders the mesh for the first time after loading."""
        self.plotter.clear()
        self.plotter.scalar_bars.clear()
        self._legend.clear_legend()
        self._ensure_lightkit()
        self.plotter.add_axes()

        # Check if we have data to show automatically
        if not self.current_mesh:
            self.plotter.reset_camera()
            return

        show_lines = self.edge_checkbox.isChecked()  # a variable to toggle the visibility of the edges

        score_index = self.scalar_selector.findData(
            next((k for k in self.current_mesh.cell_data.keys()
                  if k.startswith("Score ")), None))
        if score_index > 0:
            self.scalar_selector.setCurrentIndex(score_index)
            self.update_scalars(score_index)
            return
        self.plotter.add_mesh(self.current_mesh, color='#d9e6f2',
                              show_edges=show_lines,
                              edge_color='#4B5563', edge_opacity=0.75,
                              smooth_shading=True, specular=0.55,
                              specular_power=25, ambient=0.2, diffuse=0.9,
                              name="main_mesh")

        self._set_home_camera()
        self._refresh_overlays()

    def update_scalars(self, index):
        """Called when user changes dropdown."""
        self.plotter.clear()
        self.plotter.scalar_bars.clear()
        self._legend.clear_legend()
        self._ensure_lightkit()
        self.plotter.add_axes()
        if self.current_mesh is None:
            self._render_cell_markers()
            self.plotter.render()
            return

        array_name = self.scalar_selector.currentData()
        #self.plotter.clear()
        #self.plotter.add_axes()

        if array_name is None:
            self._bar_title = ""
            # Plain colour: the edge toggle stays available but is not forced
            # on (1.1M head triangles would render as a black mass).
            self.edge_checkbox.setEnabled(True)
            show_lines = self.edge_checkbox.isChecked()
            self.plotter.add_mesh(self.current_mesh, color='#d9e6f2',
                                  show_edges=show_lines,
                                  edge_color='#4B5563', edge_opacity=0.75,
                                  smooth_shading=True, specular=0.55,
                                  specular_power=25, ambient=0.2,
                                  diffuse=0.9, name="main_mesh")
        else:
            # Data mode: allow user to toggle edges freely
            self.edge_checkbox.setEnabled(True)
            show_lines = self.edge_checkbox.isChecked()  # a variable to toggle the visibility of the edges
            # show_scalar_bar=False: the bar is added below with the human
            # label; add_mesh would otherwise add a second one named after
            # the internal array key.
            self.plotter.add_mesh(self.current_mesh, scalars=array_name, cmap="turbo",
                                  show_edges=show_lines, edge_color="black",
                                  clim=[0.0, 1.0], show_scalar_bar=False,
                                  name="main_mesh")
            self._add_scalar_bar(self.scalar_selector.currentText(),
                                 clim=(0.0, 1.0))

        # Only re-home the camera when the *mesh* changed: a colour switch or
        # a fresh R² map must not rotate the view under the user.
        if self._camera_mesh is not self.current_mesh:
            self._set_home_camera()
            self._camera_mesh = self.current_mesh
        self._render_cell_markers()
        # Re-add the mapping overlays (placements on the head, best-element
        # mark on the ROI) that plotter.clear() removed.
        self._refresh_overlays()