"""Collision test tab: find a safe subject/robot/start-pose layout.

Simulation only, but available in every run mode that has a robot.  The tab
owns a local MuJoCo world and IK solver, so enabling it never touches the
real robot or the running experiment.  It is a planning aid; the production
robot controller remains the final authority.
"""

from __future__ import annotations

import json
import os
from typing import List, Optional

import numpy as np
from PyQt5 import QtCore, QtWidgets

from ..lab_profile import LabProfile
from ..sim_robot import config as sim_config
from .collision_test import CollisionTestSession
from .robot_scene_view import RobotSceneView


class PoseEditor(QtWidgets.QGroupBox):
    """Six numeric fields (mm / deg) with per-axis nudge buttons."""

    changed = QtCore.pyqtSignal(list, list)   # position_m, orientation_deg

    AXES = (("X", "mm"), ("Y", "mm"), ("Z", "mm"),
            ("RX", "deg"), ("RY", "deg"), ("RZ", "deg"))

    def __init__(self, title, position_m, orientation_deg, parent=None):
        super().__init__(title, parent)
        self.setProperty("card", True)
        self._step_mm = 5.0
        self._step_deg = 5.0
        self._spins: List[QtWidgets.QDoubleSpinBox] = []
        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        for row, (label, unit) in enumerate(self.AXES):
            cap = QtWidgets.QLabel(label)
            cap.setProperty("role", "cap")
            cap.setMinimumWidth(26)
            spin = QtWidgets.QDoubleSpinBox()
            spin.setDecimals(1)
            spin.setSingleStep(1.0)
            spin.setKeyboardTracking(False)
            if unit == "mm":
                spin.setRange(-5000.0, 5000.0)
                spin.setSuffix(" mm")
            else:
                spin.setRange(-360.0, 360.0)
                spin.setSuffix(" deg")
            spin.valueChanged.connect(self._emit)
            minus = QtWidgets.QPushButton("−")
            plus = QtWidgets.QPushButton("+")
            for button in (minus, plus):
                button.setFixedWidth(28)
                button.setProperty("role", "transport")
            minus.clicked.connect(
                lambda _=False, s=spin, u=unit: self._nudge(s, u, -1))
            plus.clicked.connect(
                lambda _=False, s=spin, u=unit: self._nudge(s, u, +1))
            grid.addWidget(cap, row, 0)
            grid.addWidget(spin, row, 1)
            grid.addWidget(minus, row, 2)
            grid.addWidget(plus, row, 3)
            self._spins.append(spin)
        self.set_values(position_m, orientation_deg)

    def _nudge(self, spin, unit, sign):
        step = self._step_mm if unit == "mm" else self._step_deg
        spin.setValue(spin.value() + sign * step)

    def set_step(self, mm: float, deg: float):
        self._step_mm = float(mm)
        self._step_deg = float(deg)

    def _emit(self, *_):
        self.changed.emit(*self.values_m())

    def values_m(self):
        values = [spin.value() for spin in self._spins]
        position_m = [v / 1000.0 for v in values[:3]]
        orientation_deg = list(values[3:])
        return position_m, orientation_deg

    def set_values(self, position_m, orientation_deg):
        values = [position_m[0] * 1000.0, position_m[1] * 1000.0,
                  position_m[2] * 1000.0, *orientation_deg]
        for spin, value in zip(self._spins, values):
            spin.blockSignals(True)
            spin.setValue(float(value))
            spin.blockSignals(False)


class CollisionTestTab(QtWidgets.QWidget):
    """The Collision test page."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.controller = None
        self.session: Optional[CollisionTestSession] = None
        self.view: Optional[RobotSceneView] = None
        self._enabled = False
        self._pending_config: Optional[dict] = None
        self._head_error: Optional[str] = None
        self._scan_placements: List = []

        self._scan_timer = QtCore.QTimer(self)
        self._scan_timer.setInterval(30)
        self._scan_timer.timeout.connect(self._scan_tick)

        self._build_ui()
        # A new project starts from the lab layout, not from a stale setup.
        self._pending_config = self._lab_config()
        self._has_setup = self._pending_config is not None
        self._set_controls_enabled(False)

    # ── UI ──────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(10)
        self.enable_btn = QtWidgets.QPushButton("Enable collision test")
        self.enable_btn.setCheckable(True)
        self.enable_btn.setProperty("role", "primary")
        self.enable_btn.toggled.connect(self._toggle_enabled)
        top.addWidget(self.enable_btn)
        self.model_label = QtWidgets.QLabel("")
        self.model_label.setProperty("role", "cap")
        top.addWidget(self.model_label)
        self.status_label = QtWidgets.QLabel("Collision test is off.")
        self.status_label.setProperty("role", "cap")
        top.addWidget(self.status_label, 1)
        self.save_project_btn = QtWidgets.QPushButton("Save setup to project")
        self.save_project_btn.setProperty("role", "transport")
        self.save_project_btn.clicked.connect(self.save_to_project)
        top.addWidget(self.save_project_btn)
        self.use_btn = QtWidgets.QPushButton("Use start pose")
        self.use_btn.setProperty("role", "transport")
        self.use_btn.setToolTip(
            "Queue the current start joints for the next experiment start.")
        self.use_btn.clicked.connect(self._use_start_pose)
        top.addWidget(self.use_btn)
        self.save_lab_btn = QtWidgets.QPushButton("Save as lab default")
        self.save_lab_btn.setProperty("role", "transport")
        self.save_lab_btn.clicked.connect(self.save_to_lab)
        top.addWidget(self.save_lab_btn)
        root.addLayout(top)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(10)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(430)
        scroll.setMaximumWidth(490)
        controls = QtWidgets.QWidget()
        left = QtWidgets.QVBoxLayout(controls)
        left.setContentsMargins(0, 0, 6, 0)
        left.setSpacing(8)

        self.base_editor = PoseEditor(
            "Robot base", sim_config.ROBOT_BASE_POSITION,
            sim_config.ROBOT_BASE_ORIENTATION)
        self.head_editor = PoseEditor(
            "Subject head", sim_config.HEAD_POSITION,
            sim_config.HEAD_ORIENTATION)
        self.base_editor.changed.connect(self._base_changed)
        self.head_editor.changed.connect(self._head_changed)
        left.addWidget(self.base_editor)
        left.addWidget(self.head_editor)

        jog = QtWidgets.QGroupBox("Jog coil (world XYZ / tool rotations)")
        jog.setProperty("card", True)
        jog_layout = QtWidgets.QVBoxLayout(jog)
        jog_layout.setContentsMargins(8, 8, 8, 8)
        jog_layout.setSpacing(5)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Step"))
        self.step_combo = QtWidgets.QComboBox()
        for value in (1, 2, 5, 10, 20):
            self.step_combo.addItem(f"{value} mm / {value} deg", value)
        self.step_combo.setCurrentIndex(2)
        row.addWidget(self.step_combo)
        row.addStretch(1)
        jog_layout.addLayout(row)
        for axis in ("X", "Y", "Z", "RX", "RY", "RZ"):
            line = QtWidgets.QHBoxLayout()
            cap = QtWidgets.QLabel(axis)
            cap.setProperty("role", "cap")
            cap.setMinimumWidth(26)
            line.addWidget(cap)
            minus = QtWidgets.QPushButton("−")
            plus = QtWidgets.QPushButton("+")
            for button in (minus, plus):
                button.setProperty("role", "transport")
            minus.clicked.connect(
                lambda _=False, a=axis: self._jog(a, -1))
            plus.clicked.connect(
                lambda _=False, a=axis: self._jog(a, +1))
            line.addWidget(minus, 1)
            line.addWidget(plus, 1)
            jog_layout.addLayout(line)
        left.addWidget(jog)

        start = QtWidgets.QGroupBox("Start pose")
        start.setProperty("card", True)
        start_layout = QtWidgets.QVBoxLayout(start)
        start_layout.setContentsMargins(8, 8, 8, 8)
        start_layout.setSpacing(5)
        branch_row = QtWidgets.QGridLayout()
        self.branch_buttons = []
        for i, (label, shoulder, elbow) in enumerate((
                ("Shoulder left / elbow up", "left", "up"),
                ("Shoulder right / elbow up", "right", "up"),
                ("Shoulder left / elbow down", "left", "down"),
                ("Shoulder right / elbow down", "right", "down"))):
            button = QtWidgets.QPushButton(label)
            button.setProperty("role", "transport")
            button.clicked.connect(
                lambda _=False, s=shoulder, e=elbow:
                self._apply_branch(s, e))
            branch_row.addWidget(button, i // 2, i % 2)
            self.branch_buttons.append(button)
        start_layout.addLayout(branch_row)
        actions = QtWidgets.QHBoxLayout()
        self.set_start_btn = QtWidgets.QPushButton("Set from current")
        self.go_start_btn = QtWidgets.QPushButton("Go to start")
        for button in (self.set_start_btn, self.go_start_btn):
            button.setProperty("role", "transport")
        self.set_start_btn.clicked.connect(self._capture_start)
        self.go_start_btn.clicked.connect(self._go_start)
        actions.addWidget(self.set_start_btn)
        actions.addWidget(self.go_start_btn)
        start_layout.addLayout(actions)
        self.start_label = QtWidgets.QLabel("")
        self.start_label.setProperty("role", "cap")
        self.start_label.setWordWrap(True)
        start_layout.addWidget(self.start_label)
        left.addWidget(start)

        scan = QtWidgets.QGroupBox("Placement scan")
        scan.setProperty("card", True)
        scan_layout = QtWidgets.QVBoxLayout(scan)
        scan_layout.setContentsMargins(8, 8, 8, 8)
        scan_layout.setSpacing(5)
        scan_actions = QtWidgets.QHBoxLayout()
        self.scan_btn = QtWidgets.QPushButton("Start collision scan")
        self.scan_btn.setProperty("role", "primary")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setProperty("role", "transport")
        self.reset_btn = QtWidgets.QPushButton("Reset to start")
        self.reset_btn.setProperty("role", "transport")
        self.scan_btn.clicked.connect(self._start_scan)
        self.stop_btn.clicked.connect(self._stop_scan)
        self.reset_btn.clicked.connect(self._go_start)
        scan_actions.addWidget(self.scan_btn)
        scan_actions.addWidget(self.stop_btn)
        scan_actions.addWidget(self.reset_btn)
        scan_layout.addLayout(scan_actions)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        scan_layout.addWidget(self.progress)
        self.collision_label = QtWidgets.QLabel("Current pose: no collision.")
        self.collision_label.setProperty("role", "cap")
        self.collision_label.setWordWrap(True)
        scan_layout.addWidget(self.collision_label)
        self.scan_status = QtWidgets.QLabel("Idle.")
        self.scan_status.setProperty("role", "cap")
        self.scan_status.setWordWrap(True)
        scan_layout.addWidget(self.scan_status)
        left.addWidget(scan)
        left.addStretch(1)
        scroll.setWidget(controls)
        body.addWidget(scroll)

        self.view_label = QtWidgets.QLabel()
        self.view_label.setProperty("role", "bed")
        self.view_label.setMinimumSize(640, 480)
        self.view_label.setAlignment(QtCore.Qt.AlignCenter)
        self.view_label.setStyleSheet(
            'QLabel[role="bed"] { background: #101317; border-radius: 8px; }')
        self.view_label.setText("Enable the collision test to load the 3D view.")
        body.addWidget(self.view_label, 1)
        root.addLayout(body, 1)

        self.model_label.setText(
            f"{sim_config.ROBOT_SPEC.label}  |  {sim_config.ROBOT_SPEC.ee_site}")

    def _set_controls_enabled(self, enabled: bool):
        for widget in (self.base_editor, self.head_editor,
                       self.set_start_btn, self.go_start_btn,
                       self.scan_btn, self.stop_btn, self.reset_btn,
                       self.step_combo):
            widget.setEnabled(enabled)
        for button in self.branch_buttons:
            button.setEnabled(enabled)
        self.save_project_btn.setEnabled(enabled)
        self.save_lab_btn.setEnabled(enabled)
        self.use_btn.setEnabled(enabled)

    def _set_status(self, text: str, error=False):
        self.status_label.setText(text)
        self.status_label.setToolTip("")
        self.status_label.setStyleSheet(
            "color: #B42318;" if error else "")

    # ── controller / persistence ────────────────────────────────────
    def set_controller(self, controller):
        self.controller = controller
        if controller is not None and getattr(controller, "manual", False):
            self.enable_btn.setEnabled(False)
            mode = ("training" if getattr(controller, "training", False)
                    else "manual")
            self._set_status(
                f"Collision test is unavailable in {mode} mode (no robot).")
        else:
            self.enable_btn.setEnabled(True)
        if controller is not None and self._has_setup and self._pending_config:
            joints = self._pending_config.get("start_joints_rad")
            if joints:
                controller.start_pose_joints = [float(v) for v in joints]

    def project_config(self) -> Optional[dict]:
        # An untouched page must not save (or later command) the zero pose.
        if not self._has_setup:
            return None
        if self.session is None:
            return self._pending_config or self._default_config()
        return {
            "head_position_m": list(self.session.head_pose[0]),
            "head_orientation_deg": list(self.session.head_pose[1]),
            "robot_base_position_m": list(self.session.base_pose[0]),
            "robot_base_orientation_deg": list(self.session.base_pose[1]),
            "start_joints_rad": list(self.session.start_joints),
            "branch": list(self.session.branch),
        }

    @staticmethod
    def _validated_config(data) -> Optional[dict]:
        """Return a normalised setup dict, or ``None`` for bad input."""
        if not isinstance(data, dict):
            return None
        try:
            head_pos = [float(v) for v in data["head_position_m"]]
            head_ori = [float(v) for v in data["head_orientation_deg"]]
            base_pos = [float(v) for v in data["robot_base_position_m"]]
            base_ori = [float(v) for v in data["robot_base_orientation_deg"]]
            start = [float(v) for v in data["start_joints_rad"]]
            branch = [str(v).strip().lower()
                      for v in data.get("branch", ("left", "up"))]
            if any(len(v) != 3 for v in (head_pos, head_ori,
                                         base_pos, base_ori)):
                raise ValueError("poses need three components")
            values = [*head_pos, *head_ori, *base_pos, *base_ori, *start]
            if not np.isfinite(values).all():
                raise ValueError("poses and joints must be finite")
            if len(start) != 6 or len(branch) != 2:
                raise ValueError("start pose needs six joints and two branch signs")
            if branch[0] not in ("left", "right") \
                    or branch[1] not in ("up", "down"):
                raise ValueError("unknown IK branch")
        except (KeyError, TypeError, ValueError):
            return None
        return {
            "head_position_m": head_pos,
            "head_orientation_deg": head_ori,
            "robot_base_position_m": base_pos,
            "robot_base_orientation_deg": base_ori,
            "start_joints_rad": start,
            "branch": branch,
        }

    def apply_config(self, data: Optional[dict]) -> None:
        config = self._validated_config(data)
        if config is None:
            self._pending_config = None
            self._has_setup = False
            self.window._collision_test_config = None
            if self.controller is not None:
                self.controller.start_pose_joints = None
            if self.session is not None:
                self._apply_config_now(self._default_config(),
                                       update_controller=False)
            return
        self._pending_config = config
        self._has_setup = True
        if self.session is not None:
            self._apply_config_now(config)

    def reset_config(self) -> None:
        """Drop a project override and fall back to the lab layout."""
        lab = self._validated_config(self._lab_config())
        self._pending_config = lab
        self._has_setup = bool(lab)
        self.window._collision_test_config = None
        if self.controller is not None:
            # Do not let a previous project's queued pose leak into this one.
            self.controller.start_pose_joints = (
                list(lab["start_joints_rad"]) if lab else None)
        if self.session is not None:
            if lab:
                self._apply_config_now(lab)
            else:
                self._apply_config_now(self._default_config(),
                                       update_controller=False)

    def _apply_config_now(self, data: dict, update_controller=True):
        config = self._validated_config(data)
        if config is None:
            return
        head_pos = config["head_position_m"]
        head_ori = config["head_orientation_deg"]
        base_pos = config["robot_base_position_m"]
        base_ori = config["robot_base_orientation_deg"]
        start = config["start_joints_rad"]
        branch = config["branch"]
        self.session.set_head_pose(head_pos, head_ori)
        self.session.set_base_pose(base_pos, base_ori)
        self.session.start_joints = start
        self.session.branch = (branch[0], branch[1])
        if update_controller and self.controller is not None:
            self.controller.start_pose_joints = list(start)
        self.session.reset_to_start()
        self._sync_fields()
        self._sync_view()
        self._update_collision()

    def _default_config(self) -> dict:
        return {
            "head_position_m": list(sim_config.HEAD_POSITION),
            "head_orientation_deg": list(sim_config.HEAD_ORIENTATION),
            "robot_base_position_m": list(sim_config.ROBOT_BASE_POSITION),
            "robot_base_orientation_deg": list(sim_config.ROBOT_BASE_ORIENTATION),
            "start_joints_rad": [0.0] * 6,
            "branch": ["left", "up"],
        }

    def _lab_config(self):
        try:
            raw = LabProfile().read().get("COLLISION_TEST")
            if raw:
                return json.loads(raw)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        return None

    def save_to_project(self):
        self._has_setup = True
        config = self.project_config()
        self.window._collision_test_config = config
        if self.controller is not None:
            self.controller.start_pose_joints = list(
                config.get("start_joints_rad", []))
        self.window._mark_project_dirty()
        self._set_status("Setup saved into the project. Save the project file to keep it.")

    def _use_start_pose(self):
        if self.session is None:
            return
        if self.controller is None:
            self._set_status("No controller is attached.", True)
            return
        self._has_setup = True
        joints = list(self.session.start_joints)
        self.controller.set_start_pose(joints)
        self._set_status("Start pose queued for the next experiment start.")

    def save_to_lab(self):
        self._has_setup = True
        config = self.project_config()
        try:
            LabProfile().write({"COLLISION_TEST": json.dumps(config)})
        except OSError as e:
            self._set_status(f"Could not write the lab default: {e}", True)
            return
        self._set_status("Setup saved as the lab default.")

    # ── enable / disable ────────────────────────────────────────────
    def _toggle_enabled(self, enabled: bool):
        if enabled:
            self._enable()
        else:
            self._disable()

    def _head_stl(self) -> Optional[str]:
        path = ""
        if self.window is not None:
            path = self.window.loadmeshlabel.text().strip()
        if not path:
            return None
        if not os.path.isfile(path):
            self._head_error = f"head mesh not found: {path}"
            return None
        if path.lower().endswith(".msh"):
            try:
                from ..sim_robot.mesh_converter import convert_head_mesh
                stl = convert_head_mesh(path)
            except Exception as e:
                self._head_error = f"could not convert the head mesh: {e}"
                return None
            if not stl or not os.path.isfile(stl):
                self._head_error = "head conversion produced no STL"
                return None
            return stl
        if path.lower().endswith(".stl"):
            return path
        self._head_error = "head mesh must be SimNIBS .msh or .stl"
        return None

    def _enable(self):
        if self._enabled:
            return
        self.enable_btn.blockSignals(True)
        self.enable_btn.setChecked(True)
        self.enable_btn.blockSignals(False)
        self.enable_btn.setText("Disable collision test")
        self._set_status("Building the collision-test world...")
        self._head_error = None
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            head_stl = self._head_stl()
            if self._head_error:
                self.enable_btn.blockSignals(True)
                self.enable_btn.setChecked(False)
                self.enable_btn.blockSignals(False)
                self.enable_btn.setText("Enable collision test")
                self._set_status(
                    "Collision test not started: head mesh error.", True)
                self.status_label.setToolTip(self._head_error)
                return
            session = CollisionTestSession(head_stl=head_stl)
            session.ensure_ready()
        except Exception as e:
            self.enable_btn.blockSignals(True)
            self.enable_btn.setChecked(False)
            self.enable_btn.blockSignals(False)
            self.enable_btn.setText("Enable collision test")
            self._set_status("Collision test could not start.", True)
            self.status_label.setToolTip(str(e))
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self.session = session
        config = self._pending_config if self._has_setup else None
        if not config:
            config = (getattr(self.window, "_collision_test_config", None)
                      or self._lab_config())
        config = self._validated_config(config)
        if config:
            self._pending_config = config
            self._has_setup = True
            self._apply_config_now(config)
        else:
            self._sync_fields()
            self._update_collision()

        view_error = None
        try:
            self.view = RobotSceneView(
                self.view_label, parent=self, auto_reload=False)
            self.view.start()
            # start() loads the shared sim scene if present; replace it with
            # the session's own model/data pair afterwards.
            self.view.set_model(session.world.model, session.world.data)
        except Exception as e:
            self.view = None
            view_error = str(e)
        self._enabled = True
        self.enable_btn.setText("Disable collision test")
        self._set_controls_enabled(True)
        if view_error:
            self._set_status("Ready without a 3D view.", True)
            self.status_label.setToolTip(view_error)
        else:
            phantom = "subject head" if head_stl else "default phantom"
            self._set_status(
                f"Ready: {sim_config.ROBOT_SPEC.label}, {phantom}.")
            self.status_label.setToolTip(
                "Move the base/head, jog the coil, then run the placement scan.")

    def shutdown(self):
        """Release the local world before the main window is destroyed."""
        if self._enabled:
            self._disable()

    def _disable(self):
        if not self._enabled:
            return
        self._stop_scan()
        if self.view is not None:
            self.view.stop()
            self.view = None
        if self.session is not None:
            # Keep an unsaved layout for a later re-enable in this project.
            self._pending_config = self.project_config()
            self.session.dispose()
            self.session = None
        self._enabled = False
        self.enable_btn.blockSignals(True)
        self.enable_btn.setChecked(False)
        self.enable_btn.blockSignals(False)
        self.enable_btn.setText("Enable collision test")
        self._set_controls_enabled(False)
        self.view_label.setText("Enable the collision test to load the 3D view.")
        self._set_status("Collision test is off.")

    # ── pose / start / jog ──────────────────────────────────────────
    def _base_changed(self, position_m, orientation_deg):
        if self.session is None:
            return
        if self._scan_timer.isActive():
            self._stop_scan()
        self._has_setup = True
        self.session.set_base_pose(position_m, orientation_deg)
        self.session.reset_to_start()
        self._sync_view()
        self._update_collision()

    def _head_changed(self, position_m, orientation_deg):
        if self.session is None:
            return
        if self._scan_timer.isActive():
            self._stop_scan()
        self._has_setup = True
        self.session.set_head_pose(position_m, orientation_deg)
        self.session.reset_to_start()
        self._sync_view()
        self._update_collision()

    def _apply_branch(self, shoulder, elbow):
        if self.session is None:
            return
        if self._scan_timer.isActive():
            self._stop_scan()
        self._has_setup = True
        # Prefer a home point above the subject, but never accept a start
        # that is already in collision.  Fall back to the pose the operator
        # is currently holding.
        original_joints = self.session.current_joints()
        original_pos, original_ori = self.session.current_end_effector()
        home_pos, home_ori = self.session.home_pose()
        for pos, ori, note in (
                (home_pos, home_ori, ""),
                (original_pos, original_ori, "Home pose was not usable; ")):
            self.session.set_current_joints(original_joints)
            if not self.session.move_to(pos, ori, shoulder=shoulder,
                                        elbow=elbow):
                continue
            if self.session.collision_state()["collision"]:
                continue
            self.session.set_start_from_current()
            self._sync_start_label()
            self._sync_view()
            self._update_collision()
            if note:
                self._set_status(note + "the current pose is now the start.")
            return
        self.session.set_current_joints(original_joints)
        self._sync_view()
        self._update_collision()
        self._set_status("No collision-free start found.", True)
        self.status_label.setToolTip(
            f"No collision-free {shoulder}/{elbow} start found. "
            "Jog to a clear pose and use Set from current.")

    def _capture_start(self):
        if self.session is None:
            return
        if self._scan_timer.isActive():
            self._stop_scan()
        self._has_setup = True
        self.session.set_start_from_current()
        self._sync_start_label()
        self._set_status("Current joints stored as the start pose.")

    def _go_start(self):
        if self.session is None:
            return
        self._stop_scan()
        self.session.reset_to_start()
        self._sync_view()
        self._update_collision()

    def _jog(self, axis, sign):
        if self.session is None:
            return
        if self._scan_timer.isActive():
            self._stop_scan()
        self._has_setup = True
        step = float(self.step_combo.currentData())
        delta = {"X": (step, 0, 0, 0, 0, 0),
                 "Y": (0, step, 0, 0, 0, 0),
                 "Z": (0, 0, step, 0, 0, 0),
                 "RX": (0, 0, 0, step, 0, 0),
                 "RY": (0, 0, 0, 0, step, 0),
                 "RZ": (0, 0, 0, 0, 0, step)}[axis]
        args = [sign * v for v in delta]
        if not self.session.jog(*args):
            self._set_status(
                f"Jog {axis}{'+' if sign > 0 else '-'} failed: IK unreachable.", True)
            return
        self._sync_view()
        self._update_collision()

    # ── scan ────────────────────────────────────────────────────────
    def _start_scan(self):
        if self.session is None:
            return
        # The scan always starts from the stored pose, so validate that pose,
        # not whichever pose the operator happens to hold after jogging.
        self.session.reset_to_start()
        self._sync_view()
        self._update_collision()
        start_state = self.session.collision_state()
        if start_state["collision"]:
            self.scan_status.setText(
                "Start pose is already in collision. Choose another branch or "
                "move the base/head first.")
            self._set_status("Start pose collides.", True)
            return
        path = self.window.loadplacementlabel.text().strip()
        if not path or not os.path.isfile(path):
            self._set_status("Load a coil placement file on the Project page first.", True)
            return
        try:
            from .pipeline_controller import read_simnibs_targets_data
            placements, _ = read_simnibs_targets_data(path)
        except Exception as e:
            self._set_status(f"Could not read the placements: {e}", True)
            return
        if not placements:
            self._set_status("The placement file is empty.", True)
            return
        self._scan_placements = placements
        self.progress.setRange(0, len(placements))
        self.progress.setValue(0)
        self.session.start_scan(placements)
        self._scan_timer.start()
        self._set_status(
            f"Scanning {len(placements)} placements from the saved start pose...")

    def _stop_scan(self):
        self._scan_timer.stop()
        if self.session is not None:
            self.session.stop_scan("stopped")
        self.scan_status.setText("Stopped.")

    def _scan_tick(self):
        if self.session is None:
            self._scan_timer.stop()
            return
        try:
            state = self.session.tick()
        except Exception as e:
            self._scan_timer.stop()
            self.scan_status.setText(f"Scan stopped by an error: {e}")
            self._set_status("Collision scan failed.", True)
            return
        self.progress.setValue(int(state["index"]))
        self._sync_view()
        self._update_collision()
        if state["active"]:
            self.scan_status.setText(f"{state['message']}: checking path...")
        if not state["active"]:
            self._scan_timer.stop()
            if state["message"].startswith("collision"):
                self.scan_status.setText(
                    f"STOP: collision at placement {state['index'] + 1}. "
                    "Adjust the base/head/start pose, then reset and restart.")
                self._set_status("Collision detected. See the scan report.", True)
            elif state["message"].startswith("IK failed"):
                self.scan_status.setText(
                    f"STOP: IK failed at placement {state['index'] + 1}.")
                self._set_status("IK failure. Change the start pose or base.", True)
            else:
                self.scan_status.setText(
                    f"Complete: {state['index']} placements checked, no collision.")
                self._set_status("Collision scan completed.")

    # ── view / status sync ─────────────────────────────────────────
    def _sync_view(self):
        if self.view is not None:
            self.view.refresh()

    def _sync_fields(self):
        if self.session is None:
            return
        self.base_editor.set_values(*self.session.base_pose)
        self.head_editor.set_values(*self.session.head_pose)
        self._sync_start_label()

    def _sync_start_label(self):
        if self.session is None:
            self.start_label.setText("")
            return
        joints = self.session.start_joints
        self.start_label.setText(
            f"{self.session.branch[0]} / {self.session.branch[1]}  |  "
            + ", ".join(f"{np.degrees(v):.1f}°" for v in joints))

    def _update_collision(self):
        if self.session is None:
            return
        state = self.session.collision_state()
        distance = state["distance_mm"]
        if state["collision"]:
            text = "COLLISION"
            if state["self_collision"]:
                text += " (self)"
            if state["head_contact"]:
                text += " (head)"
            if distance is not None:
                text += f"  {distance:.1f} mm"
            self.collision_label.setText(text)
            self.collision_label.setStyleSheet("color: #B42318;")
        elif state["warning"]:
            self.collision_label.setText(f"NEAR MISS  {distance:.1f} mm")
            self.collision_label.setStyleSheet("color: #B45309;")
        else:
            self.collision_label.setText("Current pose: no collision.")
            self.collision_label.setStyleSheet("")
