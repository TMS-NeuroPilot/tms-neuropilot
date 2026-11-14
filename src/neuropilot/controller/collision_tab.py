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
from .collision_test import SELF_PENETRATION_M, CollisionTestSession
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
        self._caps: List[QtWidgets.QLabel] = []
        self._nudge_buttons: List[QtWidgets.QPushButton] = []
        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        for index, (label, unit) in enumerate(self.AXES):
            row, column = divmod(index, 3)
            cell = QtWidgets.QHBoxLayout()
            cell.setSpacing(4)
            cap = QtWidgets.QLabel(label)
            cap.setProperty("role", "cap")
            self._caps.append(cap)
            spin = QtWidgets.QDoubleSpinBox()
            spin.setDecimals(1)
            spin.setSingleStep(1.0)
            spin.setKeyboardTracking(False)
            spin.setMinimumWidth(110)
            spin.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                               QtWidgets.QSizePolicy.Fixed)
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
                button.setSizePolicy(QtWidgets.QSizePolicy.Fixed,
                                     QtWidgets.QSizePolicy.Fixed)
                button.setProperty("role", "nudge")
                self._nudge_buttons.append(button)
            minus.clicked.connect(
                lambda _=False, s=spin, u=unit: self._nudge(s, u, -1))
            plus.clicked.connect(
                lambda _=False, s=spin, u=unit: self._nudge(s, u, +1))
            cell.addWidget(cap)
            cell.addWidget(spin, 1)
            cell.addWidget(minus, 0, QtCore.Qt.AlignVCenter)
            cell.addWidget(plus, 0, QtCore.Qt.AlignVCenter)
            grid.addLayout(cell, row, column)
            grid.setColumnStretch(column, 1)
            self._spins.append(spin)
        self.set_values(position_m, orientation_deg)
        self.apply_ui_scale()

    def apply_ui_scale(self):
        """Keep the axis labels and nudge buttons aligned after a font rescale."""
        if self._caps:
            label_width = max(cap.sizeHint().width() for cap in self._caps)
            for cap in self._caps:
                cap.setFixedWidth(label_width)
        if self._nudge_buttons:
            button_width = max(button.sizeHint().width()
                               for button in self._nudge_buttons)
            for button in self._nudge_buttons:
                button.setFixedWidth(button_width)

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


class BranchChoice(QtWidgets.QWidget):
    """Two exclusive radio buttons for one IK branch axis.

    The checks stay visible: unlike the former dropdowns, a popup cannot hide
    the second option, and the labels name the axis and value together.
    """

    def __init__(self, options, parent=None):
        super().__init__(parent)
        self._buttons: List[QtWidgets.QRadioButton] = []
        self._data: List[str] = []
        self._group = QtWidgets.QButtonGroup(self)
        self._group.setExclusive(True)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for index, (text, data) in enumerate(options):
            button = QtWidgets.QRadioButton(text)
            button.setProperty("role", "choice")
            self._group.addButton(button, index)
            layout.addWidget(button)
            self._buttons.append(button)
            self._data.append(data)
        layout.addStretch(1)
        self._buttons[0].setChecked(True)

    def currentIndex(self) -> int:
        return self._group.checkedId()

    def currentData(self) -> Optional[str]:
        index = self.currentIndex()
        return self._data[index] if 0 <= index < len(self._data) else None

    def setCurrentIndex(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)

    def findData(self, data: str) -> int:
        try:
            return self._data.index(data)
        except ValueError:
            return -1

    def count(self) -> int:
        return len(self._buttons)

    def buttons(self) -> List[QtWidgets.QRadioButton]:
        """The radio buttons, for accessibility and regression checks."""
        return list(self._buttons)


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
        self._ready_status = "Collision test is off."
        self._placement_error = False
        self._scan_placements: List = []
        self._last_ui_scale = None
        self._last_split_total = None
        self._last_scan_render_key = None

        self._scan_timer = QtCore.QTimer(self)
        self._scan_timer.setInterval(30)
        self._scan_timer.timeout.connect(self._scan_tick)

        self._build_ui()
        # A new project starts from the lab layout, not from a stale setup.
        self._pending_config = self._lab_config()
        self._has_setup = self._pending_config is not None
        self._set_controls_enabled(False)
        placement_label = getattr(self.window, "loadplacementlabel", None)
        if placement_label is not None:
            placement_label.textChanged.connect(self._placement_path_changed)

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
        self.save_project_btn = QtWidgets.QPushButton("Make project default")
        self.save_project_btn.setProperty("role", "transport")
        self.save_project_btn.setToolTip(
            "Store this layout in the project file.")
        self.save_project_btn.clicked.connect(self.save_to_project)
        top.addWidget(self.save_project_btn)
        self.save_lab_btn = QtWidgets.QPushButton("Make lab default")
        self.save_lab_btn.setProperty("role", "transport")
        self.save_lab_btn.setToolTip(
            "Store this layout as the lab default.")
        self.save_lab_btn.clicked.connect(self.save_to_lab)
        top.addWidget(self.save_lab_btn)
        self.use_btn = QtWidgets.QPushButton("Use at start pose")
        self.use_btn.setProperty("role", "transport")
        self.use_btn.setToolTip(
            "Use this six-joint pose when the experiment starts.")
        self.use_btn.clicked.connect(self._use_start_pose)
        top.addWidget(self.use_btn)
        root.addLayout(top)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        # The control stack gets the larger share; the 3D view yields width.
        # The handle stays draggable for an operator who wants more room.
        scroll.setMinimumWidth(760)
        scroll.setMaximumWidth(1000)
        self.scroll = scroll
        controls = QtWidgets.QWidget()
        left = QtWidgets.QVBoxLayout(controls)
        left.setContentsMargins(0, 0, 6, 0)
        left.setSpacing(4)

        self.base_editor = PoseEditor(
            "Robot base", sim_config.ROBOT_BASE_POSITION,
            sim_config.ROBOT_BASE_ORIENTATION)
        self.base_editor.changed.connect(self._base_changed)
        left.addWidget(self.base_editor)

        jog = QtWidgets.QGroupBox("Jog coil (world XYZ / tool rotations)")
        jog.setProperty("card", True)
        jog_layout = QtWidgets.QVBoxLayout(jog)
        jog_layout.setContentsMargins(6, 4, 6, 4)
        jog_layout.setSpacing(2)
        self._jog_nudges: List[QtWidgets.QPushButton] = []
        self._jog_caps: List[QtWidgets.QLabel] = []
        self._jog_value_labels: List[QtWidgets.QLabel] = []
        row = QtWidgets.QHBoxLayout()
        step_caption = QtWidgets.QLabel("Step")
        step_caption.setProperty("role", "cap")
        row.addWidget(step_caption)
        self.step_combo = QtWidgets.QComboBox()
        self.step_combo.setProperty("role", "step")
        for value in (1, 2, 5, 10, 20):
            self.step_combo.addItem(f"{value} mm / {value} deg", value)
        self.step_combo.setCurrentIndex(2)
        row.addWidget(self.step_combo)
        row.addStretch(1)
        jog_layout.addLayout(row)
        jog_grid = QtWidgets.QGridLayout()
        jog_grid.setHorizontalSpacing(8)
        jog_grid.setVerticalSpacing(4)
        for index, axis in enumerate(("X", "Y", "Z", "RX", "RY", "RZ")):
            row, column = divmod(index, 3)
            line = QtWidgets.QHBoxLayout()
            line.setSpacing(4)
            cap = QtWidgets.QLabel(axis)
            cap.setProperty("role", "cap")
            self._jog_caps.append(cap)
            line.addWidget(cap)
            value = QtWidgets.QLabel("—")
            value.setProperty("role", "value")
            value.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            value.setToolTip(
                "Current coil-site pose in world millimetres and tool degrees")
            self._jog_value_labels.append(value)
            line.addWidget(value)
            minus = QtWidgets.QPushButton("−")
            plus = QtWidgets.QPushButton("+")
            for button in (minus, plus):
                button.setProperty("role", "nudge")
                button.setSizePolicy(QtWidgets.QSizePolicy.Fixed,
                                     QtWidgets.QSizePolicy.Fixed)
                self._jog_nudges.append(button)
            minus.clicked.connect(
                lambda _=False, a=axis: self._jog(a, -1))
            plus.clicked.connect(
                lambda _=False, a=axis: self._jog(a, +1))
            line.addStretch(1)
            line.addWidget(minus, 0, QtCore.Qt.AlignVCenter)
            line.addWidget(plus, 0, QtCore.Qt.AlignVCenter)
            line.addStretch(1)
            jog_grid.addLayout(line, row, column)
            jog_grid.setColumnStretch(column, 1)
        jog_layout.addLayout(jog_grid)
        left.addWidget(jog)

        self.head_editor = PoseEditor(
            "Subject placement", sim_config.HEAD_POSITION,
            sim_config.HEAD_ORIENTATION)
        self.head_editor.changed.connect(self._head_changed)
        left.addWidget(self.head_editor)

        start = QtWidgets.QGroupBox("Start pose")
        start.setProperty("card", True)
        start_layout = QtWidgets.QVBoxLayout(start)
        start_layout.setContentsMargins(6, 4, 6, 4)
        start_layout.setSpacing(2)
        branch_row = QtWidgets.QVBoxLayout()
        branch_row.setSpacing(3)
        self.shoulder_choice = BranchChoice(
            (("Shoulder left", "left"), ("Shoulder right", "right")))
        self.arm_choice = BranchChoice(
            (("Arm up", "up"), ("Arm down", "down")))
        self.wrist_choice = BranchChoice(
            (("Wrist normal", "normal"), ("Wrist flipped", "flipped")))
        for choice in (self.shoulder_choice, self.arm_choice,
                       self.wrist_choice):
            choice.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                 QtWidgets.QSizePolicy.Fixed)
            branch_row.addWidget(choice)
        self.apply_branch_btn = QtWidgets.QPushButton(
            "Set start pose from selection")
        self.apply_branch_btn.setProperty("role", "branch")
        self.apply_branch_btn.setToolTip(
            "Solve the selected shoulder, arm and wrist branch.")
        self.apply_branch_btn.clicked.connect(self._apply_branch)
        start_layout.addLayout(branch_row)
        start_layout.addWidget(self.apply_branch_btn)
        self.set_start_btn = QtWidgets.QPushButton("Set start from current")
        self.set_start_btn.setToolTip(
            "Store the current six joint angles as the start pose.")
        self.set_start_btn.setProperty("role", "branch")
        self.set_start_btn.clicked.connect(self._capture_start)
        start_layout.addWidget(self.set_start_btn)
        self.start_label = QtWidgets.QLabel("")
        self.start_label.setProperty("role", "cap")
        self.start_label.setWordWrap(True)
        start_layout.addWidget(self.start_label)
        left.addWidget(start)

        scan = QtWidgets.QGroupBox("Placement scan")
        scan.setProperty("card", True)
        scan_layout = QtWidgets.QVBoxLayout(scan)
        scan_layout.setContentsMargins(6, 4, 6, 4)
        scan_layout.setSpacing(2)
        self.scan_btn = QtWidgets.QPushButton("Start collision scan")
        self.scan_btn.setProperty("role", "primary")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setProperty("role", "transport")
        self.reset_btn = QtWidgets.QPushButton("Reset to start")
        self.reset_btn.setProperty("role", "transport")
        self.scan_btn.clicked.connect(self._start_scan)
        self.stop_btn.clicked.connect(self._stop_scan)
        self.reset_btn.clicked.connect(self._go_start)
        scan_layout.addWidget(self.scan_btn)
        scan_actions = QtWidgets.QHBoxLayout()
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
        splitter.addWidget(scroll)

        self.view_label = QtWidgets.QLabel()
        self.view_label.setProperty("role", "bed")
        # The view is the flexible side: it shrinks before the controls do.
        self.view_label.setMinimumSize(300, 300)
        self.view_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.view_label.setAlignment(QtCore.Qt.AlignCenter)
        self.view_label.setStyleSheet(
            'QLabel[role="bed"] { background: #101317; border-radius: 8px; }')
        self.view_label.setText("Enable the collision test to load the 3D view.")
        splitter.addWidget(self.view_label)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([900, 320])
        self.splitter = splitter
        root.addWidget(splitter, 1)

        # The same counter layout as the Control page's robot view, but for
        # the local collision scan. It is deliberately a child of the label,
        # not a row in the page, so it cannot push the 3D view or the log.
        self.scan_total_value = QtWidgets.QLabel("—")
        self.scan_total_value.setProperty("role", "value")
        self.scan_current_value = QtWidgets.QLabel("idle")
        self.scan_current_value.setProperty("role", "value")
        overlay = QtWidgets.QWidget(self.view_label)
        overlay.setObjectName("scan_overlay")
        overlay.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        overlay.setStyleSheet(
            "QWidget#scan_overlay { background: rgba(15, 23, 42, 0.78);"
            " border-radius: 6px; }"
            "QWidget#scan_overlay QLabel { background: transparent;"
            " color: #F8FAFC; }"
            "QWidget#scan_overlay QLabel[role=\"cap\"] { color: #CBD5E1;"
            " font-size: 15px; }"
            "QWidget#scan_overlay QLabel[role=\"value\"] { color: #FFFFFF;"
            " font-weight: 600; }")
        overlay_layout = QtWidgets.QVBoxLayout(overlay)
        overlay_layout.setContentsMargins(10, 5, 10, 5)
        overlay_layout.setSpacing(2)
        total_cap = QtWidgets.QLabel("Total targets")
        total_cap.setProperty("role", "cap")
        current_cap = QtWidgets.QLabel("Current")
        current_cap.setProperty("role", "cap")
        total_row = QtWidgets.QHBoxLayout()
        total_row.setSpacing(6)
        total_row.addWidget(total_cap)
        total_row.addWidget(self.scan_total_value)
        total_row.addStretch(1)
        current_row = QtWidgets.QHBoxLayout()
        current_row.setSpacing(6)
        current_row.addWidget(current_cap)
        current_row.addWidget(self.scan_current_value)
        current_row.addStretch(1)
        overlay_layout.addLayout(total_row)
        overlay_layout.addLayout(current_row)
        overlay.adjustSize()
        overlay.hide()
        self._scan_overlay = overlay
        self.view_label.installEventFilter(self)

        self.model_label.setText(
            f"{sim_config.ROBOT_SPEC.label}  |  {sim_config.ROBOT_SPEC.ee_site}")
        self.apply_ui_scale(1.0)

    def apply_ui_scale(self, scale=1.0):
        """Scale the controls/view split with the rest of the window.

        The page is laid out at 1244 px, but the controller opens at up to
        2x on a large display. Without this, the control column kept its
        design width while the font doubled, so the axis labels and the
        millimetre suffixes were clipped. The radio rows and nudge buttons
        also re-measure their label widths here.
        """
        s = max(1.0, float(scale))
        self.base_editor.apply_ui_scale()
        self.head_editor.apply_ui_scale()
        if self._jog_caps:
            label_width = max(cap.sizeHint().width() for cap in self._jog_caps)
            for cap in self._jog_caps:
                cap.setFixedWidth(label_width)
        for value in self._jog_value_labels:
            value.setFixedWidth(round(100 * s))
        if self._jog_nudges:
            width = max(button.sizeHint().width()
                        for button in self._jog_nudges)
            for button in self._jog_nudges:
                button.setFixedWidth(width)
        if (self._last_ui_scale is not None
                and abs(s - self._last_ui_scale) < 0.01):
            self._apply_split(s)
            return
        self._last_ui_scale = s
        self.scroll.setMinimumWidth(round(700 * s))
        self.scroll.setMaximumWidth(round(900 * s))
        self.view_label.setMinimumSize(round(300 * s), round(300 * s))
        self._apply_split(s)

    def _apply_split(self, s):
        """Give the controls a narrower 60% share, once per real width."""
        total = self.splitter.width()
        if total < round(1100 * s):
            return
        if (self._last_split_total is not None
                and abs(total - self._last_split_total) < max(4, total * 0.02)):
            return
        view_min = round(300 * s)
        desired = max(round(700 * s),
                      min(round(total * 0.60), round(900 * s)))
        target = min(desired, max(1, total - view_min))
        self.splitter.setSizes([target, max(1, total - target)])
        self._last_split_total = total

    def showEvent(self, event):
        super().showEvent(event)
        scale = getattr(self.window, "_current_scale", lambda: 1.0)()
        # The splitter has no real width until this page has been laid out.
        QtCore.QTimer.singleShot(0, lambda: self.apply_ui_scale(scale))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        scale = getattr(self.window, "_current_scale", lambda: 1.0)()
        QtCore.QTimer.singleShot(0, lambda: self._apply_split(scale))

    def eventFilter(self, obj, event):
        if obj is self.view_label and event.type() in (
                QtCore.QEvent.Resize, QtCore.QEvent.Show):
            self._place_scan_overlay()
        return super().eventFilter(obj, event)

    def _place_scan_overlay(self):
        overlay = getattr(self, "_scan_overlay", None)
        label = getattr(self, "view_label", None)
        if overlay is None or label is None or not label.isVisible():
            return
        if label.width() <= 0 or label.height() <= 0:
            return
        overlay.resize(overlay.sizeHint())
        scale = getattr(self.window, "_current_scale", lambda: 1.0)()
        margin = max(8, round(10 * scale))
        overlay.move(max(0, label.width() - overlay.width() - margin),
                     margin)
        overlay.show()
        overlay.raise_()

    @staticmethod
    def _branch_text(branch) -> str:
        return "/".join(str(part) for part in branch)

    def _pulse_text(self, state, last=False) -> str:
        if last:
            order = state.get("last_order_index")
            rep = state.get("last_rep")
            target = state.get("last_target_id")
            fallback_order = int(state.get("completed") or 0) - 1
        else:
            order = state.get("order_index")
            rep = state.get("rep")
            target = state.get("target_id")
            fallback_order = int(state.get("index") or 0)
        if order is None:
            order = fallback_order
        if target is None:
            target = int(order) + 1
        if rep is None:
            rep = 1
        reps = int(state.get("repetitions") or 1)
        return f"pulse {order} · {rep}/{reps} · target {target}"

    def _scan_status_text(self, state, detailed=False) -> str:
        total = int(state.get("total") or 0)
        total_targets = int(state.get("total_targets") or total)
        completed = int(state.get("completed") or 0)
        message = str(state.get("message") or "")
        if state.get("active"):
            current_pulse = self._pulse_text(state)
            current_pulse = (current_pulse[:1].upper()
                             + current_pulse[1:])
            if state.get("preparing"):
                if completed:
                    last_pulse = self._pulse_text(state, last=True)
                    last_pulse = (last_pulse[:1].upper()
                                  + last_pulse[1:])
                    text = (f"{last_pulse} reached. Preparing "
                            f"{self._pulse_text(state)}.")
                else:
                    text = (f"{current_pulse}: solving IK and "
                            f"preparing the path.")
            else:
                text = (f"{current_pulse}: checking path "
                        f"{state.get('path_step', 0)}/"
                        f"{state.get('path_total', 0)}.")
            for change in reversed(state.get("branch_changes") or []):
                if change.get("index") == state.get("index"):
                    if detailed:
                        text += (f" Selected "
                                 f"{self._branch_text(change['selected'])} "
                                 f"was unreachable; using "
                                 f"{self._branch_text(change['used'])}.")
                    else:
                        text += " (IK branch changed)"
                    break
            return text
        if message.startswith("complete"):
            text = (f"Complete: {total_targets} targets checked in "
                    f"{completed} pulses, no collision.")
        elif message.startswith("no IK solution"):
            last = self._pulse_text(state, last=True) if completed else "start"
            text = (f"STOP: no IK solution for {self._pulse_text(state)}. "
                    f"This is not a collision. The arm remains at {last}.")
            if detailed:
                results = state.get("results") or []
                selected = ((results[-1].get("detail") or {})
                            .get("selected_branch") if results else None)
                if selected:
                    text += (f" Selected branch "
                             f"{self._branch_text(selected)} and the "
                             f"simulation IK both failed.")
        elif message.startswith("collision"):
            text = (f"STOP: collision at {self._pulse_text(state)}. "
                    f"The arm is at the first blocking waypoint.")
        elif message == "stopped":
            text = f"Stopped at {self._pulse_text(state)}."
        else:
            text = message or "Idle."
        changes = state.get("branch_changes") or []
        if changes:
            change = changes[-1]
            if detailed:
                text += (f" IK branch changed at pulse "
                         f"{change['order_index']}: "
                         f"{self._branch_text(change['selected'])} -> "
                         f"{self._branch_text(change['used'])}.")
            else:
                text += " IK branch changed."
        return text

    def _update_scan_ui(self, state):
        total = int(state.get("total") or 0)
        total_targets = int(state.get("total_targets") or total)
        if total <= 0:
            self.scan_total_value.setText("—")
            self.scan_current_value.setText("idle")
        else:
            self.scan_total_value.setText(str(total_targets))
            message = str(state.get("message") or "")
            if state.get("active"):
                if state.get("preparing") and state.get("completed"):
                    current = self._pulse_text(state, last=True)
                else:
                    current = self._pulse_text(state)
            elif message.startswith("complete"):
                current = f"{total_targets} targets · complete"
            else:
                current = self._pulse_text(state)
            self.scan_current_value.setText(current)
        self.scan_status.setText(self._scan_status_text(state))
        self.scan_status.setToolTip(
            self._scan_status_text(state, detailed=True))
        if self._enabled and self.view is not None:
            self._place_scan_overlay()
            # The label's size hint follows the scaled font after the layout
            # has settled; place it once more in the next event-loop turn.
            QtCore.QTimer.singleShot(0, self._place_scan_overlay)
        else:
            self._scan_overlay.hide()

    def _set_controls_enabled(self, enabled: bool):
        for widget in (self.base_editor, self.head_editor,
                       self.set_start_btn,
                       self.apply_branch_btn, self.shoulder_choice,
                       self.arm_choice, self.wrist_choice,
                       self.scan_btn, self.stop_btn, self.reset_btn,
                       self.step_combo):
            widget.setEnabled(enabled)
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
                      for v in data.get("branch", ("left", "up", "normal"))]
            if any(len(v) != 3 for v in (head_pos, head_ori,
                                         base_pos, base_ori)):
                raise ValueError("poses need three components")
            values = [*head_pos, *head_ori, *base_pos, *base_ori, *start]
            if not np.isfinite(values).all():
                raise ValueError("poses and joints must be finite")
            if len(start) != 6 or len(branch) not in (2, 3):
                raise ValueError("start pose needs six joints and branch signs")
            if branch[0] not in ("left", "right") \
                    or branch[1] not in ("up", "down"):
                raise ValueError("unknown IK branch")
            if len(branch) == 2:
                branch.append("normal")
            if branch[2] not in ("normal", "flipped"):
                raise ValueError("unknown wrist branch")
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
        self.session.branch = (branch[0], branch[1], branch[2])
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
            "branch": ["left", "up", "normal"],
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
            self._ready_status = "Ready without a 3D view."
            self._set_status(self._ready_status, True)
            self.status_label.setToolTip(view_error)
        else:
            phantom = "subject head" if head_stl else "default phantom"
            self._ready_status = (
                f"Ready: {sim_config.ROBOT_SPEC.label}, {phantom}.")
            self._set_status(self._ready_status)
            self.status_label.setToolTip(
                "Move the base/head, jog the coil, then run the placement scan.")
        if self.view is not None:
            self._update_scan_ui(self.session.scan_status())
        self._update_jog_values()

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
        self._ready_status = "Collision test is off."
        self._placement_error = False
        self.enable_btn.blockSignals(True)
        self.enable_btn.setChecked(False)
        self.enable_btn.blockSignals(False)
        self.enable_btn.setText("Enable collision test")
        self._set_controls_enabled(False)
        self.view_label.setText("Enable the collision test to load the 3D view.")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.collision_label.clear()
        self.scan_status.clear()
        self.scan_total_value.setText("—")
        self.scan_current_value.setText("idle")
        self._scan_overlay.hide()
        for label in self._jog_value_labels:
            label.setText("—")
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

    def _apply_branch(self):
        if self.session is None:
            return
        shoulder = self.shoulder_choice.currentData()
        elbow = self.arm_choice.currentData()
        wrist = self.wrist_choice.currentData()
        if self._scan_timer.isActive():
            self._stop_scan()
        previous_branch = tuple(self.session.branch)
        self._has_setup = True
        # The branch choice changes the arm configuration, never the coil
        # placement. Solve the selected branch for the exact pose the tool
        # currently occupies, so the coil stays put while the arm flips.
        original_joints = self.session.current_joints()
        target_pos, target_ori = self.session.current_end_effector()
        self.session.set_current_joints(original_joints)
        if not self.session.move_to(target_pos, target_ori,
                                    shoulder=shoulder, elbow=elbow,
                                    wrist=wrist):
            self.session.set_current_joints(original_joints)
            self.session.branch = previous_branch
            self._sync_start_label(sync_branch=False)
            self._sync_view()
            self._update_collision()
            self._set_status(
                "No IK solution for selected branch. Selection kept.", True)
            self.status_label.setToolTip(
                f"Selected {shoulder}/{elbow}/{wrist} cannot reach the current "
                "coil pose. Jog to another pose and try again.")
            return
        collides = self.session.collision_state()["collision"]
        self.session.set_start_from_current()
        self._sync_start_label()
        self._sync_view()
        self._update_collision()
        if collides:
            self._set_status(
                "Start pose set but it collides. Adjust base/head.", True)
            self.status_label.setToolTip(
                f"Selected {shoulder}/{elbow}/{wrist} reaches the current coil "
                "pose, but the arm/head pose collides.")
        else:
            self._set_status(
                "Start pose set to the selected branch; coil placement kept.")

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
        start = np.asarray(self.session.start_joints, dtype=float)
        current = np.asarray(self.session.current_joints(), dtype=float)
        already_there = (current.shape == start.shape
                         and np.allclose(current, start, atol=1e-6))
        if self.session.scan_active or self._scan_timer.isActive():
            self._stop_scan()
        self.session.reset_to_start()
        self._sync_view()
        self._update_collision()
        self._sync_start_label()
        self._set_status(
            "Already at the saved start pose." if already_there
            else "Moved to the saved start pose.")

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
    def _placement_path_changed(self, text: str):
        """Clear stale placement/enable errors once a file is now present."""
        path = (text or "").strip()
        if not path or not os.path.isfile(path):
            return
        if not (self._placement_error or self.status_label.styleSheet()):
            return
        self._placement_error = False
        self._set_status(self._ready_status)
        if self.scan_status.text().startswith("Load a coil placement"):
            self.scan_status.setText(
                "Placement file loaded." if self._enabled else "Idle.")

    def _start_scan(self):
        if self.session is None:
            return
        # Clear the previous run's terminal text before the new run can move.
        self.scan_status.setText("Preparing collision scan...")
        self.scan_status.setToolTip("")
        self.scan_total_value.setText("—")
        self.scan_current_value.setText("preparing")
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
            self.scan_current_value.setText("start pose collision")
            self._set_status("Start pose collides.", True)
            return
        path = self.window.loadplacementlabel.text().strip()
        if not path or not os.path.isfile(path):
            self._placement_error = True
            self.scan_current_value.setText("no placement file")
            self._set_status("Load a coil placement file on the Project page first.", True)
            return
        try:
            from .pipeline_controller import (read_simnibs_targets_data,
                                              read_target_order)
            placements, _ = read_simnibs_targets_data(path)
        except Exception as e:
            self._placement_error = True
            self._set_status("The placement file could not be read.", True)
            self.status_label.setToolTip(str(e))
            return
        if not placements:
            self._placement_error = True
            self._set_status("The placement file is empty.", True)
            return
        target_ids = None
        order_path = self.window.target_order_LineEdit.text().strip()
        if order_path:
            try:
                target_ids = read_target_order(order_path, len(placements))
            except Exception as e:
                self._placement_error = True
                self.scan_current_value.setText("target-order error")
                self._set_status("The target-order file could not be read.", True)
                self.status_label.setToolTip(str(e))
                return
        repetitions = max(1, int(self.window.n_repetitions_spinBox.value()))
        self._scan_placements = placements
        self._last_scan_render_key = None
        try:
            self.session.start_scan(
                placements, target_ids=target_ids, repetitions=repetitions)
        except Exception as e:
            self._set_status("The target order does not match the placements.", True)
            self.status_label.setToolTip(str(e))
            return
        state = self.session.scan_status()
        self.progress.setRange(0, max(1, int(state["total"])))
        self.progress.setValue(0)
        self._update_scan_ui(state)
        if state["active"]:
            self._scan_timer.start()
            self._set_status(
                f"Scanning {state['total_targets']} targets in "
                f"{state['total']} pulses from the saved start pose...")
        else:
            self._scan_timer.stop()
            self._report_scan_end(state)

    def _stop_scan(self):
        self._scan_timer.stop()
        if self.session is not None:
            self.session.stop_scan("stopped")
            self._update_scan_ui(self.session.scan_status())
        else:
            self.scan_status.setText("Stopped.")

    def _report_scan_end(self, state):
        """Set the top status and error styling for a finished/failed scan."""
        message = str(state.get("message") or "")
        if message.startswith("collision"):
            self._set_status("Collision detected. See the scan report.", True)
        elif message.startswith("no IK solution"):
            self._set_status("IK failure (not a collision). See the scan report.", True)
        elif message.startswith("complete"):
            self._set_status("Collision scan completed.")
        else:
            self._set_status("Collision scan stopped.")
        self.status_label.setToolTip(self.scan_status.toolTip())

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
        self.progress.setValue(int(state.get("completed") or 0))
        self._sync_view()
        self._update_collision()
        # One synchronous frame at every boundary (target reached, next
        # target being prepared, stop, failure) keeps the rendered arm from
        # lagging behind the status text.
        render_key = (state.get("index"), state.get("completed"),
                      state.get("active"), state.get("path_total") == 0)
        if render_key != self._last_scan_render_key:
            self._last_scan_render_key = render_key
            if self.view is not None:
                self.view.render_now()
        self._update_scan_ui(state)
        if not state["active"]:
            self._scan_timer.stop()
            self._report_scan_end(state)

    # ── view / status sync ─────────────────────────────────────────
    def _update_jog_values(self):
        labels = getattr(self, "_jog_value_labels", ())
        if not labels:
            return
        if self.session is None or not getattr(self.session, "ready", False):
            for label in labels:
                label.setText("—")
            return
        try:
            position_mm, orientation_deg = self.session.current_end_effector()
        except Exception:
            for label in labels:
                label.setText("—")
            return
        values = [*position_mm, *orientation_deg]
        for index, (label, value) in enumerate(zip(labels, values)):
            suffix = "°" if index >= 3 else " mm"
            label.setText(f"{value:.1f}{suffix}")

    def _sync_view(self):
        self._update_jog_values()
        if self.view is not None:
            self.view.refresh()

    def _sync_fields(self):
        if self.session is None:
            return
        self.base_editor.set_values(*self.session.base_pose)
        self.head_editor.set_values(*self.session.head_pose)
        self._sync_start_label()

    def _sync_start_label(self, sync_branch=True):
        if self.session is None:
            self.start_label.setText("")
            if sync_branch:
                self._sync_branch_controls()
            return
        joints = self.session.start_joints
        self.start_label.setText(
            f"{self.session.branch[0]} / {self.session.branch[1]} / "
            f"{self.session.branch[2]}  |  "
            + ", ".join(f"{np.degrees(v):.1f}°" for v in joints))
        if sync_branch:
            self._sync_branch_controls()

    def _sync_branch_controls(self):
        """Show the branch that is currently stored as the start pose."""
        if self.session is None:
            return
        for choice, value in (
                (self.shoulder_choice, self.session.branch[0]),
                (self.arm_choice, self.session.branch[1]),
                (self.wrist_choice, self.session.branch[2])):
            index = choice.findData(value)
            if index >= 0:
                choice.setCurrentIndex(index)

    def _update_collision(self):
        if self.session is None:
            return
        state = self.session.collision_state()
        distance = state["distance_mm"]
        self_contact = state.get("self_contact_mm")
        if self_contact is not None:
            tolerance_mm = abs(SELF_PENETRATION_M) * 1000.0
            self.collision_label.setToolTip(
                f"Smallest self-mesh overlap {abs(self_contact):.1f} mm; "
                f"overlaps shallower than {tolerance_mm:.1f} mm are tolerated.")
        else:
            self.collision_label.setToolTip("")
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
