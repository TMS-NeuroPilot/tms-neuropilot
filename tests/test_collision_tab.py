"""Collision-test tab: local world, saved setup and the placement scan."""

import json
import os

import numpy as np
import pytest
from PyQt5 import QtWidgets
from scipy.spatial.transform import Rotation

pytest.importorskip("PyQt5.QtWidgets")
pytest.importorskip("mujoco")
pytest.importorskip("ikpy")

from neuropilot.controller.collision_test import (
    SCAN_STEPS,
    CollisionTestSession,
    branch_of_active,
)
from neuropilot.controller.pipeline_controller import read_simnibs_targets_data
from neuropilot.lab_profile import LabProfile
from neuropilot.sim_robot import config as sim_config
from neuropilot.sim_robot.utils.transforms import orientation_distance_deg

# A scene file per process: the parallel workers compose their own world,
# and a shared file name would let one worker read another's head or base
# pose (the file is rewritten at every connect()).
SCENE_NAME = f"_collision_scene_{os.getpid()}.xml"

pytestmark = pytest.mark.gui


CUSTOM = {
    "head_position_m": [0.4, -0.4, 0.0],
    "head_orientation_deg": [0.0, 0.0, -90.0],
    "robot_base_position_m": [-0.2, 0.2, 0.0],
    "robot_base_orientation_deg": [0.0, 0.0, 0.0],
    "start_joints_rad": [-0.1, 0.2, 0.3, -0.4, 0.5, -0.6],
    "branch": ["right", "up", "normal"],
    "safe_height_mm": 400.0,
    "translation_threshold_mm": 10.0,
    "rotation_threshold_deg": 5.0,
}


def test_default_start_matches_the_simulator_start_pose():
    session = CollisionTestSession(scene_name=SCENE_NAME)
    assert session.start_joints == sim_config.START_JOINTS
    assert session.branch == branch_of_active(sim_config.START_JOINTS)
    assert session.branch == ("right", "up", "normal")


def test_enable_builds_the_local_world(window, qapp):
    tab = window.collision_tab
    tab._enable()
    qapp.processEvents()
    try:
        assert tab.session is not None
        assert tab.session.ready
        assert tab.base_editor.isEnabled()
        assert tab.enable_btn.text() == "Disable collision test"
    finally:
        tab._disable()
    assert tab.session is None
    assert tab.enable_btn.text() == "Enable collision test"


def test_project_and_lab_round_trip(window, qapp):
    tab = window.collision_tab
    tab.apply_config(CUSTOM)
    assert tab.project_config() == CUSTOM

    config = window.get_config_dict()
    assert config["collision_test"] == CUSTOM

    window.apply_config_dict({"collision_test": CUSTOM})
    assert window._collision_test_config == CUSTOM

    tab.save_to_project()
    assert window._collision_test_config == CUSTOM
    tab.save_to_lab()
    stored = LabProfile().read()["COLLISION_TEST"]
    assert json.loads(stored) == CUSTOM


def test_scan_stops_and_reports_a_collision(window, qapp, h5file):
    # A single reachable placement.  The zero start pose is not a valid
    # approach, so the scan must stop and report the collision instead of
    # pretending the placement is safe.
    matrix = np.eye(4)
    # SimNIBS coordinates: 50 mm above the head origin.  The controller
    # transforms this to the room frame with the current head pose.
    matrix[:3, 3] = [0.0, 0.0, 50.0]
    path = h5file({"matsimnibs": matrix[:, :, None]}, "placements.hdf5")
    window.loadplacementlabel.setText(str(path))

    tab = window.collision_tab
    tab._enable()
    qapp.processEvents()
    try:
        home_pos, home_ori = tab.session.home_pose()
        assert tab.session.move_to(home_pos, home_ori,
                                   shoulder="right", elbow="up",
                                   wrist="flipped")
        tab.session.set_start_from_current()
        tab._start_scan()
        for _ in range(500):
            tab._scan_tick()
            qapp.processEvents()
            if not tab.session.scan_active:
                break
        assert tab.session.scan_active
        assert tab._scan_paused
        assert tab._scan_collision_paused
        assert tab.session.scan_results
        assert any(r["collision"] or not r["ok"]
                   for r in tab.session.scan_results)
        assert "Collision detected; scan paused" in tab.status_label.text()
    finally:
        tab._disable()


def test_a_project_without_a_block_drops_the_previous_pose(
        window, controller, qapp):
    tab = window.collision_tab
    tab.apply_config(CUSTOM)
    window.set_controller(controller)
    assert controller.start_pose_joints == CUSTOM["start_joints_rad"]

    window.apply_config_dict({"project_name": "older-project"})
    assert controller.start_pose_joints is None
    assert tab.project_config() is None
    assert window.get_config_dict()["collision_test"] is None


def test_scan_completes_when_the_path_is_clear(h5file):
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        home_pos, home_ori = session.home_pose()
        assert session.move_to(home_pos, home_ori,
                               shoulder="right", elbow="up",
                               wrist="flipped")
        session.set_start_from_current()

        # Build the pipeline placement that maps back to this collision-free
        # home pose, so the scan checks a real but zero-length path.
        world_mm, world_ori = session.current_end_effector()
        head_pos = np.asarray(session.head_pose[0], dtype=float)
        head_rot = Rotation.from_euler(
            "xyz", session.head_pose[1], degrees=True)
        local_m = head_rot.inv().apply(
            np.asarray(world_mm, dtype=float) / 1000.0 - head_pos)
        raw_ori = (head_rot.inv() * Rotation.from_euler(
            "xyz", world_ori, degrees=True)).as_euler("xyz", degrees=True)
        matrix = np.eye(4)
        matrix[:3, :3] = Rotation.from_euler(
            "xyz", raw_ori, degrees=True).as_matrix()
        matrix[:3, 3] = local_m * 1000.0
        path = h5file({"matsimnibs": matrix[:, :, None]}, "clear.hdf5")
        placements, _ = read_simnibs_targets_data(str(path))

        session.start_scan(placements)
        for _ in range(500):
            state = session.tick()
            if not state["active"]:
                break

        assert state["message"] == "complete"
        assert state["results"][0]["ok"]
        assert not state["results"][0]["collision"]
    finally:
        session.dispose()


def test_untouched_page_does_not_save_a_start_pose(window, controller):
    window.set_controller(controller)
    assert window.get_config_dict()["collision_test"] is None
    assert controller.start_pose_joints is None


def test_malformed_setup_is_ignored(window, controller):
    window.set_controller(controller)
    window.collision_tab.apply_config({"head_position_m": [1.0, 2.0]})
    assert controller.start_pose_joints is None
    assert window.collision_tab.project_config() is None


def test_moving_the_base_keeps_a_world_target_fixed():
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        target = ([388.0, -332.0, 61.5], [125.0, 34.0, 14.0])
        session.set_base_pose([0.2, 0.2, 0.1], [0.0, 0.0, 45.0])
        assert session.move_to(*target, shoulder="right", elbow="up")
        position, orientation = session.current_end_effector()
        assert np.linalg.norm(np.asarray(position) - target[0]) < 0.5
        assert orientation_distance_deg(orientation, target[1]) < 0.5
    finally:
        session.dispose()


def test_fixed_mjcf_base_rotation_is_divided_out():
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        target = ([388.0, -332.0, 61.5], [125.0, 34.0, 14.0])
        # Elfin-style MJCF: the base body already carries the same +90 deg
        # that the URDF chain has as a fixed joint.
        session.world.base_xml_pose = ([0.0, 0.0, 0.0], [0.0, 0.0, 90.0])
        session.set_base_pose([0.0, 0.0, 0.0], [0.0, 0.0, 90.0])
        local = session.world_to_base_pose(*target)
        assert np.linalg.norm(np.asarray(local[0]) - target[0]) < 0.5
        assert orientation_distance_deg(local[1], target[1]) < 0.5
    finally:
        session.dispose()


def test_controls_fit_before_the_3d_view_at_the_design_size(window, qapp):
    window.resize(1244, 960)
    window.show()
    for index in range(window.tabWidget.count()):
        if window.tabWidget.tabText(index) == "Collision test":
            window.tabWidget.setCurrentIndex(index)
            break
    qapp.processEvents()
    qapp.processEvents()

    tab = window.collision_tab
    scroll = next(s for s in tab.findChildren(QtWidgets.QScrollArea)
                  if s.widget() is not None
                  and tab.isAncestorOf(s.widget()))
    assert 500 <= scroll.width() <= 620
    assert tab.view_label.width() >= 300
    assert tab.view_label.minimumWidth() == 300
    assert scroll.maximumWidth() == 620
    assert scroll.verticalScrollBar().maximum() == 0
    assert not scroll.verticalScrollBar().isVisible()
    # The progress track must stay thick enough to read, with the speed
    # control on its own row underneath.
    assert tab.progress.height() >= 20
    assert (tab.progress.geometry().top()
            - tab.prev_btn.geometry().bottom() >= 12)
    assert (tab.scan_status.geometry().top()
            >= tab.progress.geometry().bottom())
    assert (tab.speed_slider.geometry().top()
            >= tab.scan_status.geometry().bottom())
    assert all(spin.width() >= 120 for spin in (
        tab.safe_height_spin, tab.translation_spin, tab.rotation_spin))


def test_failed_enable_keeps_the_button_label(window, qapp, monkeypatch):
    from neuropilot.controller import collision_tab as collision_tab_module

    def fail(self):
        raise RuntimeError("floor is lava")

    monkeypatch.setattr(collision_tab_module.CollisionTestSession,
                        "ensure_ready", fail)
    tab = window.collision_tab
    tab._enable()
    qapp.processEvents()

    assert tab.session is None
    assert not tab.enable_btn.isChecked()
    assert tab.enable_btn.text() == "Enable collision test"


def test_adding_a_placement_file_clears_the_stale_error(
        window, qapp, tmp_path):
    tab = window.collision_tab
    tab._placement_error = True
    tab._set_status("Load a coil placement file on the Project page first.",
                    True)
    path = tmp_path / "placements.hdf5"
    path.write_bytes(b"placeholder")

    window.loadplacementlabel.setText(str(path))
    qapp.processEvents()

    assert tab.status_label.text() == tab._ready_status
    assert tab.status_label.styleSheet() == ""
    assert tab._placement_error is False


def test_collision_groups_use_the_requested_order_and_caption(window):
    tab = window.collision_tab
    titles = [group.title() for group in tab.findChildren(QtWidgets.QGroupBox)]
    assert titles[:3] == [
        "Robot base", "Jog coil (world XYZ / tool rotations)",
        "Subject placement"]
    assert "Cobot pose setting" in titles
    step_labels = [label for label in tab.findChildren(QtWidgets.QLabel)
                   if label.text() == "Step"]
    assert step_labels
    assert step_labels[0].property("role") == "cap"


def test_disabling_clears_the_placement_scan_log(window, qapp):
    tab = window.collision_tab
    tab._enabled = True
    tab.collision_label.setText("COLLISION")
    tab.scan_status.setText("STOP: collision")
    tab._disable()
    qapp.processEvents()
    assert tab.collision_label.text() == ""
    assert tab.scan_status.text() == ""
    assert tab.progress.value() == 0


def test_start_pose_selectors_apply_one_branch(window, qapp):
    tab = window.collision_tab
    tab._enable()
    qapp.processEvents()
    try:
        tab.shoulder_choice.setCurrentIndex(
            tab.shoulder_choice.findData("right"))
        tab.arm_choice.setCurrentIndex(tab.arm_choice.findData("up"))
        tab.wrist_choice.setCurrentIndex(tab.wrist_choice.findData("normal"))
        tab._apply_branch()
        qapp.processEvents()
        assert tab.session.branch == ("right", "up", "normal")
        assert tab.shoulder_choice.currentData() == "right"
        assert tab.arm_choice.currentData() == "up"
        assert tab.wrist_choice.currentData() == "normal"
    finally:
        tab._disable()


def test_collision_action_labels_and_short_tooltips(window):
    tab = window.collision_tab
    assert tab.save_project_btn.text() == "Make project default"
    assert tab.save_lab_btn.text() == "Make lab default"
    assert tab.use_btn.text() == "Use at start pose"
    assert tab.apply_branch_btn.text() == "Set start pose from selection"
    assert tab.move_up_btn.text() == "Move coil up"
    assert tab.prev_btn.text() == "Prev target"
    assert tab.stop_btn.text() == "Stop"
    assert tab.next_btn.text() == "Next target"
    assert tab.scan_btn.text() == "Start collision scan"
    assert tab.wrist_choice.count() == 2
    for button in (tab.save_project_btn, tab.save_lab_btn, tab.use_btn):
        assert button.toolTip().strip()


def test_branch_defaults_to_arm_up(window):
    tab = window.collision_tab
    data = dict(CUSTOM)
    data.pop("branch")
    config = tab._validated_config(data)
    assert config is not None
    assert config["branch"] == ["right", "up", "normal"]
    assert tab._default_config()["branch"][1] == "up"


def test_start_pose_uses_visible_radio_buttons(window):
    tab = window.collision_tab
    for choice, labels in (
            (tab.shoulder_choice, ("left", "right")),
            (tab.arm_choice, ("up", "down")),
            (tab.wrist_choice, ("normal", "flipped"))):
        assert choice.count() == 2
        assert tuple(button.text() for button in choice.buttons()) == labels
        assert sum(button.isChecked() for button in choice.buttons()) == 1
    # The first radio of every row starts at the same x, so the three axes
    # read as one aligned column.
    assert len({choice.buttons()[0].x() for choice in (
        tab.shoulder_choice, tab.arm_choice, tab.wrist_choice)}) == 1
    assert all(button.width() >= 72 for choice in (
        tab.shoulder_choice, tab.arm_choice, tab.wrist_choice)
        for button in choice.buttons())
    assert tab.step_combo.sizeHint().height() < 48
    assert tab.step_combo.view().sizeHintForRow(0) >= 44


def test_collision_controls_scale_with_the_window(window, qapp):
    tab = window.collision_tab
    tab._last_ui_scale = None
    tab.apply_ui_scale(2.0)
    assert tab.scroll.minimumWidth() >= 1000
    assert tab.view_label.minimumWidth() >= 600
    assert all(button.width() < spin.width() for button, spin in zip(
        tab.base_editor._nudge_buttons[::2], tab.base_editor._spins))
    assert tab.prev_btn.maximumWidth() <= 360
    assert tab.next_btn.maximumWidth() <= 360


def test_collision_controls_are_compact_and_axes_are_coloured(window):
    tab = window.collision_tab
    tab._last_ui_scale = None
    tab.apply_ui_scale(1.0)
    assert tab.scan_btn.maximumWidth() <= 420
    assert tab.stop_btn.maximumWidth() <= 200
    caps = {cap.text(): cap for cap in tab._jog_caps}
    assert [caps[axis].property("axis") for axis in ("X", "Y", "Z")] == [
        "x", "y", "z"]
    assert all(caps[axis].property("axis") is None
               for axis in ("RX", "RY", "RZ"))
    for editor in (tab.base_editor, tab.head_editor):
        editor_caps = {cap.text(): cap for cap in editor._caps}
        assert [editor_caps[axis].property("axis")
                for axis in ("X", "Y", "Z")] == ["x", "y", "z"]
        assert all(editor_caps[axis].property("axis") is None
                   for axis in ("RX", "RY", "RZ"))
    assert all(label.property("role") == "jog-value"
               for label in tab._jog_value_labels)


def test_scan_enforces_the_selected_branch(monkeypatch):
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        solution = [0.0] * len(session.ik.chain.links)
        for index, value in zip(
                session.ik.active_indices,
                [-0.1, 0.1, 0.1, 0.1, 0.1, 0.1]):
            solution[index] = value
        branch_calls = []
        free_calls = []

        def fake_solve_branch(*args, **kwargs):
            branch_calls.append(kwargs)
            return True, solution

        monkeypatch.setattr(session.ik, "solve_branch", fake_solve_branch)
        monkeypatch.setattr(
            session.ik, "solve_with_config",
            lambda *args, **kwargs: free_calls.append(True) or (True, solution))
        session._scan_active = True
        session._scan_base_targets = [([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])]
        session._scan_index = 0
        session._scan_completed = 0
        session.branch = ("right", "up", "normal")

        session._prepare_next()
        state = session.scan_status()
        assert state["active"]
        assert state["message"].startswith("pulse 0 · 1/1 · target 0")
        assert "branch right/up/normal" in state["message"]
        assert state["branch_changes"] == []
        assert session.branch == ("right", "up", "normal")
        assert branch_calls[0]["shoulder"] == "right"
        assert branch_calls[0]["elbow"] == "up"
        assert branch_calls[0]["wrist"] == "normal"
        assert free_calls == []
    finally:
        session.dispose()


def test_ik_failure_is_reported_as_ik_not_collision(monkeypatch):
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        monkeypatch.setattr(session.ik, "solve_branch",
                            lambda *args, **kwargs: (False, None))
        session._scan_active = True
        session._scan_base_targets = [([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])]
        session._scan_index = 0
        session._scan_completed = 0
        session.branch = ("right", "up", "normal")

        session._prepare_next()
        state = session.scan_status()
        assert not state["active"]
        assert state["message"] == "no IK solution in selected branch"
        assert state["completed"] == 0
        assert state["results"][-1]["message"] == (
            "IK failed in selected branch")
        assert state["results"][-1]["collision"] is False
        assert state["results"][-1]["detail"]["selected_branch"] == [
            "right", "up", "normal"]
    finally:
        session.dispose()


def test_target_reached_is_rendered_before_preparing_the_next(monkeypatch):
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        monkeypatch.setattr(session, "collision_state",
                            lambda: {"collision": False})
        session._scan_active = True
        session._scan_base_targets = [([0.0, 0.0, 0.0], [0.0, 0.0, 0.0]),
                                      ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])]
        session._scan_index = 0
        session._scan_completed = 0
        session._scan_path = [[0.0] * 6]
        session._scan_path_i = 0

        state = session.tick()
        assert state["active"]
        assert state["completed"] == 1
        assert state["preparing"]
        assert "reached pulse 0" in state["message"]
        assert "preparing pulse 1" in state["message"]
        assert state["path_total"] == 0
    finally:
        session.dispose()


def test_scan_complete_reports_previous_near_misses(window):
    tab = window.collision_tab
    state = {
        "active": False,
        "message": "complete",
        "total": 2,
        "total_targets": 2,
        "completed": 2,
        "results": [
            {"detail": {"warning": True, "distance_mm": 6.2}},
            {"detail": {"warning": False, "distance_mm": 12.0}},
        ],
        "branch_changes": [],
    }
    text = tab._scan_status_text(state, detailed=True)
    assert "no collision" in text
    assert "1 near-miss waypoints" in text
    assert "6.2 mm" in text


def test_scan_overlay_shows_visible_target_and_ik_failure_state(window):
    tab = window.collision_tab
    tab._update_scan_ui({
        "active": True,
        "index": 3,
        "completed": 3,
        "total": 10,
        "path_step": 4,
        "path_total": 30,
        "preparing": False,
        "message": "pulse 3",
        "branch_changes": [],
        "total_targets": 10,
        "repetitions": 1,
        "target_id": 4,
        "order_index": 3,
        "rep": 1,
        "last_target_id": 3,
        "last_order_index": 2,
        "last_rep": 1,
    })
    assert tab.scan_total_value.text() == "10"
    assert tab.scan_current_value.text() == "pulse 3 · 1/1 · target 4"
    assert tab.scan_status.text().startswith("Pulse 3 · 1/1 · target 4:")

    tab._update_scan_ui({
        "active": False,
        "index": 3,
        "completed": 3,
        "total": 10,
        "path_step": 0,
        "path_total": 0,
        "preparing": False,
        "message": "no IK solution",
        "branch_changes": [],
        "total_targets": 10,
        "repetitions": 1,
        "target_id": 4,
        "order_index": 3,
        "rep": 1,
        "last_target_id": 3,
        "last_order_index": 2,
        "last_rep": 1,
    })
    assert tab.scan_current_value.text() == "pulse 3 · 1/1 · target 4"
    assert "not a collision" in tab.scan_status.text()
    assert "arm remains at pulse 2 · 1/1 · target 3" in tab.scan_status.text()


def test_scan_builds_the_target_order_and_repetition_sequence(monkeypatch):
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        monkeypatch.setattr(session, "_prepare_next", lambda: None)
        placements = [([0.0, 0.0, 0.0], [0.0, 0.0, 0.0]) for _ in range(3)]
        session.start_scan(placements, target_ids=[2, 0], repetitions=2)
        state = session.scan_status()
        assert state["total_targets"] == 3
        assert state["total"] == 4
        assert session._scan_order_indices == [0, 0, 1, 1]
        assert session._scan_target_ids == [2, 2, 0, 0]
        assert session._scan_reps == [1, 2, 1, 2]
    finally:
        session.dispose()


def test_start_scan_passes_the_project_order_and_repetitions(
        window, tmp_path, h5file):
    matrix = np.eye(4)[:, :, None]
    placements_path = h5file({"matsimnibs": matrix}, "ordered.hdf5")
    order_path = tmp_path / "order.txt"
    order_path.write_text("0\n")

    class _FakeSession:
        def __init__(self):
            self.calls = None

        def update_contact_colors(self):
            pass

        def reset_to_start(self):
            pass

        def collision_state(self):
            return {"collision": False, "warning": False,
                    "self_collision": False, "head_contact": False,
                    "distance_mm": None}

        def start_scan(self, placements, **kwargs):
            self.calls = (placements, kwargs)

        def scan_status(self):
            return {"active": False, "index": 0, "completed": 0,
                    "total": 2, "total_targets": 1, "repetitions": 2,
                    "target_id": 0, "order_index": 0, "rep": 1,
                    "last_target_id": None, "last_order_index": None,
                    "last_rep": None, "path_step": 0, "path_total": 0,
                    "preparing": False, "message": "complete",
                    "branch_changes": [], "results": []}

    tab = window.collision_tab
    fake = _FakeSession()
    tab.session = fake
    tab.view = None
    window.loadplacementlabel.setText(str(placements_path))
    window.target_order_LineEdit.setText(str(order_path))
    window.n_repetitions_spinBox.setValue(2)
    tab.scan_status.setText("STOP: stale error from the previous run")
    try:
        tab._start_scan()
        assert "stale error" not in tab.scan_status.text()
        assert fake.calls is not None
        placements, kwargs = fake.calls
        assert len(placements) == 1
        assert list(kwargs["target_ids"]) == [0]
        assert kwargs["repetitions"] == 2
    finally:
        tab.session = None
        window.target_order_LineEdit.clear()
        window.n_repetitions_spinBox.setValue(1)


def test_failed_branch_apply_keeps_the_radio_selection(window, monkeypatch):
    tab = window.collision_tab
    tab._enable()
    try:
        monkeypatch.setattr(tab.session, "move_to", lambda *args, **kwargs: False)
        tab.shoulder_choice.setCurrentIndex(
            tab.shoulder_choice.findData("right"))
        tab.arm_choice.setCurrentIndex(tab.arm_choice.findData("up"))
        tab.wrist_choice.setCurrentIndex(tab.wrist_choice.findData("flipped"))
        tab._apply_branch()
        assert tab.shoulder_choice.currentData() == "right"
        assert tab.arm_choice.currentData() == "up"
        assert tab.wrist_choice.currentData() == "flipped"
        assert "Selection kept" in tab.status_label.text()
    finally:
        tab._disable()


def _set_branch_demo_pose(session):
    session.set_head_pose([0.4, -0.4, 0.0], [0.0, 0.0, -90.0])
    session.set_base_pose([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
    session.start_joints = [
        -0.15631573099595975, 0.4073160988551985, 1.5014451367930322,
        -1.9087544049119525, 0.15631507765144684, 6.798270264983551e-06]
    session.branch = ("right", "up", "normal")
    session.reset_to_start()


def test_wrist_choice_changes_the_start_pose(window, qapp):
    import math

    tab = window.collision_tab
    tab._enable()
    qapp.processEvents()
    try:
        _set_branch_demo_pose(tab.session)
        starts = {}
        for wrist in ("normal", "flipped"):
            tab.shoulder_choice.setCurrentIndex(
                tab.shoulder_choice.findData("right"))
            tab.arm_choice.setCurrentIndex(tab.arm_choice.findData("up"))
            tab.wrist_choice.setCurrentIndex(tab.wrist_choice.findData(wrist))
            tab._apply_branch()
            qapp.processEvents()
            assert tab.session.branch[2] == wrist
            starts[wrist] = np.asarray(tab.session.start_joints)
        assert not np.allclose(starts["normal"], starts["flipped"])
        assert starts["normal"][4] >= 0.0
        assert starts["flipped"][4] < 0.0
        assert abs(abs(starts["normal"][5] - starts["flipped"][5])
                   - math.pi) < 0.2
    finally:
        tab._disable()


def test_shoulder_choice_keeps_the_coil_placement(window, qapp):
    tab = window.collision_tab
    tab._enable()
    qapp.processEvents()
    try:
        _set_branch_demo_pose(tab.session)
        poses = {}
        for shoulder in ("right", "left"):
            tab.shoulder_choice.setCurrentIndex(
                tab.shoulder_choice.findData(shoulder))
            tab.arm_choice.setCurrentIndex(tab.arm_choice.findData("up"))
            tab.wrist_choice.setCurrentIndex(tab.wrist_choice.findData("normal"))
            tab._apply_branch()
            qapp.processEvents()
            assert tab.session.branch[0] == shoulder
            poses[shoulder] = tab.session.current_end_effector()
        np.testing.assert_allclose(poses["right"][0], poses["left"][0],
                                   atol=0.5)
        assert orientation_distance_deg(
            poses["right"][1], poses["left"][1]) < 0.5
    finally:
        tab._disable()


def test_jog_values_show_the_current_tool_pose(window, qapp):
    tab = window.collision_tab
    tab._enable()
    qapp.processEvents()
    try:
        assert all(label.text() != "—" for label in tab._jog_value_labels)
        before = [label.text() for label in tab._jog_value_labels]
        tab._jog("X", 1)
        qapp.processEvents()
        after = [label.text() for label in tab._jog_value_labels]
        assert after != before
        assert all(label.text() != "—" for label in tab._jog_value_labels)
    finally:
        tab._disable()


def test_collision_preflight_shares_the_simulator_limits():
    from neuropilot.controller import collision_test
    from neuropilot.sim_robot import config as sim_config

    assert collision_test.NEAR_MISS_M == sim_config.COLLISION_DISTANCE_THRESHOLD_M
    assert collision_test.PENETRATION_M == sim_config.PENTRATION_TOLERANCE
    assert collision_test.SELF_PENETRATION_M == sim_config.SELF_PENETRATION_TOLERANCE
    assert collision_test.SCAN_STEPS == sim_config.PATH_INTERPOLATION_STEPS


def test_shallow_head_contact_is_tolerated_and_deep_contact_is_not(monkeypatch):
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        monkeypatch.setattr(session.world, "get_self_collision_contacts", lambda: [])
        monkeypatch.setattr(
            session.world, "get_robot_head_closest_distance",
            lambda **kw: -0.001)
        monkeypatch.setattr(
            session.world, "get_robot_head_contacts",
            lambda: [{"dist": -0.001}])
        shallow = session.collision_state()
        assert shallow["collision"] is False
        assert shallow["head_contact"] is False
        assert shallow["warning"] is False

        monkeypatch.setattr(
            session.world, "get_robot_head_closest_distance",
            lambda **kw: -0.010)
        monkeypatch.setattr(
            session.world, "get_robot_head_contacts",
            lambda: [{"dist": -0.010}])
        deep = session.collision_state()
        assert deep["collision"] is True
        assert deep["head_contact"] is True
    finally:
        session.dispose()


def test_head_proximity_is_not_a_warning(monkeypatch):
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        monkeypatch.setattr(
            session.world, "get_robot_head_closest_distance",
            lambda **kwargs: 0.006)
        monkeypatch.setattr(
            session.world, "get_self_collision_contacts", lambda: [])
        monkeypatch.setattr(session.world, "get_robot_head_contacts",
                            lambda: [])
        state = session.collision_state()
        assert state["collision"] is False
        assert state["warning"] is False
        assert state["distance_mm"] == pytest.approx(6.0)
    finally:
        session.dispose()


def test_contact_colours_tint_and_restore_the_robot(monkeypatch):
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        body_id = next(iter(session.world._robot_body_visual_geom_ids))
        geom_ids = session.world._robot_body_visual_geom_ids[body_id]
        collision_geoms = [
            gid for gid in range(session.world.model.ngeom)
            if int(session.world.model.geom_bodyid[gid]) == body_id
            and gid not in geom_ids]
        assert collision_geoms
        original = [session.world.model.geom_rgba[gid].copy()
                    for gid in geom_ids]
        original_collision = [session.world.model.geom_rgba[gid].copy()
                              for gid in collision_geoms]
        monkeypatch.setattr(
            session.world, "get_robot_head_body_distances",
            lambda *args, **kwargs: {body_id: 0.006})
        session.update_contact_colors()
        tinted = [session.world.model.geom_rgba[gid]
                  for gid in geom_ids]
        assert all(rgba[3] == pytest.approx(1.0) for rgba in tinted)
        assert any(not np.allclose(rgba, before)
                   for rgba, before in zip(tinted, original))
        assert all(np.allclose(session.world.model.geom_rgba[gid], before)
                   for gid, before in zip(collision_geoms,
                                          original_collision))

        monkeypatch.setattr(
            session.world, "get_robot_head_body_distances",
            lambda *args, **kwargs: {body_id: -0.001})
        session.update_contact_colors()
        assert all(np.allclose(session.world.model.geom_rgba[gid],
                               [0.45, 0.0, 0.0, 1.0])
                   for gid in geom_ids)

        session.clear_contact_colors()
        assert all(np.allclose(session.world.model.geom_rgba[gid], before)
                   for gid, before in zip(geom_ids, original))
    finally:
        session.dispose()


def test_far_bodies_are_not_tinted_by_the_distance_cap():
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        assert session.world.get_robot_head_body_distances(0.01) == {}
    finally:
        session.dispose()


def test_contact_colours_tint_both_sides_of_a_self_collision(monkeypatch):
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        bodies = list(session.world._robot_body_visual_geom_ids)
        body_a, body_b = bodies[0], bodies[1]
        geoms = {
            body_id: session.world._robot_body_visual_geom_ids[body_id]
            for body_id in (body_a, body_b)}

        def fake_contacts():
            return [{"dist": -0.002,
                     "geom1": geoms[body_a][0], "geom2": geoms[body_b][0]}]

        monkeypatch.setattr(
            session.world, "get_robot_head_body_distances",
            lambda *args, **kwargs: {})
        monkeypatch.setattr(
            session.world, "get_self_collision_contacts", fake_contacts)
        monkeypatch.setattr(session.world, "get_robot_head_contacts",
                            lambda: [])
        session.update_contact_colors()

        # Both involved bodies tint dark red.
        for body_id in (body_a, body_b):
            assert all(np.allclose(session.world.model.geom_rgba[gid],
                                   [0.45, 0.0, 0.0, 1.0])
                       for gid in geoms[body_id])
    finally:
        session.dispose()


def test_contact_colours_tint_the_head_on_a_head_contact(monkeypatch):
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        head_geoms = [gid for geoms in
                      session.world._head_body_visual_geom_ids.values()
                      for gid in geoms]
        assert head_geoms
        original = [session.world.model.geom_rgba[gid].copy()
                    for gid in head_geoms]

        def fake_head_contacts():
            # Beyond the 4 mm production tolerance: an actual contact.
            return [{"dist": -0.005, "geom1": 0, "geom2": 0,
                     "normal_force": 0.0}]

        monkeypatch.setattr(
            session.world, "get_robot_head_body_distances",
            lambda *args, **kwargs: {})
        monkeypatch.setattr(
            session.world, "get_self_collision_contacts", lambda: [])
        monkeypatch.setattr(session.world, "get_robot_head_contacts",
                            fake_head_contacts)
        session.update_contact_colors()
        assert all(np.allclose(session.world.model.geom_rgba[gid],
                               [0.45, 0.0, 0.0, 1.0])
                   for gid in head_geoms)

        # No head contact: the mesh gets its MJCF colour back.
        monkeypatch.setattr(session.world, "get_robot_head_contacts",
                            lambda: [])
        session.update_contact_colors()
        assert all(np.allclose(session.world.model.geom_rgba[gid], before)
                   for gid, before in zip(head_geoms, original))
    finally:
        session.dispose()


def test_movement_speed_links_to_control_default_speed(window):
    tab = window.collision_tab
    assert tab.speed_slider.value() == window.spinBox2.value()

    tab.speed_slider.setValue(80)
    assert window.spinBox2.value() == 80
    assert tab._scan_timer.interval() < 30

    window.spinBox2.setValue(20)
    assert tab.speed_slider.value() == 20
    assert tab._scan_timer.interval() > 30


def test_contact_colour_overlay_is_always_on(window):
    tab = window.collision_tab
    # The checkbox is gone: the overlay shows without a toggle to remember.
    assert not hasattr(tab, "contact_colors_chk")

    class FakeSession:
        def __init__(self):
            self.updates = 0

        def update_contact_colors(self):
            self.updates += 1

        def collision_state(self):
            return {"collision": False, "warning": False, "distance_mm": None,
                    "self_collision": False, "self_contact_mm": None,
                    "head_contact": False}

    original = tab.session
    fake = FakeSession()
    tab.session = fake
    tab._last_problem = None
    try:
        tab._update_collision()
        assert fake.updates == 1
    finally:
        tab.session = original


def test_move_coil_up_uses_the_configured_safe_height(monkeypatch):
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        session.set_motion_limits(400.0, 20.0, 15.0)
        solution = [0.0] * len(session.ik.chain.links)
        calls = []

        def fake_solve(position, orientation, initial):
            calls.append(list(position))
            return True, solution

        monkeypatch.setattr(
            session, "current_end_effector",
            lambda: ([0.0, 0.0, 100.0], [0.0, 0.0, 0.0]))
        monkeypatch.setattr(session, "_solve_selected_branch", fake_solve)
        assert session.move_coil_up() is True
        assert calls[0] == pytest.approx([0.0, 0.0, 400.0])

        monkeypatch.setattr(
            session, "current_end_effector",
            lambda: ([0.0, 0.0, 450.0], [0.0, 0.0, 0.0]))
        assert session.move_coil_up() is None
    finally:
        session.dispose()


def test_scan_button_pauses_and_resumes_without_stopping(window, monkeypatch):
    class FakeSession:
        scan_active = True

        def update_contact_colors(self):
            pass

        def scan_status(self):
            return {
                "active": True, "index": 1, "completed": 1, "total": 3,
                "total_targets": 3, "repetitions": 1, "target_id": 2,
                "order_index": 1, "rep": 1, "last_target_id": 1,
                "last_order_index": 0, "last_rep": 1, "path_step": 0,
                "path_total": 0, "preparing": False, "message": "pulse 1",
                "branch_changes": [], "results": [],
            }

        def can_jump_target(self, delta):
            return False

        def stop_scan(self, message="stopped"):
            pass

    tab = window.collision_tab
    original_session = tab.session
    original_enabled = tab._enabled
    fake = FakeSession()
    tab.session = fake
    tab._enabled = True
    tab._scan_paused = False
    tab.scan_btn.setText("Start collision scan")
    timer = tab._scan_timer
    monkeypatch.setattr(timer, "start", lambda: None)
    monkeypatch.setattr(timer, "stop", lambda: None)
    monkeypatch.setattr(timer, "isActive", lambda: False)
    try:
        tab._scan_button_clicked()
        assert tab._scan_paused is True
        assert tab.scan_btn.text() == "Resume collision scan"
        tab._scan_button_clicked()
        assert tab._scan_paused is False
        assert tab.scan_btn.text() == "Pause collision scan"
    finally:
        tab.session = original_session
        tab._enabled = original_enabled
        tab._scan_paused = False
        tab.scan_btn.setText("Start collision scan")


def test_layout_change_during_scan_continues_from_current_pulse(
        window, monkeypatch):
    class FakeSession:
        scan_active = True

        def __init__(self):
            self.reframes = 0
            self.resets = 0

        def update_contact_colors(self):
            pass

        def set_base_pose(self, position, orientation):
            pass

        def set_head_pose(self, position, orientation):
            pass

        def reframe_scan(self):
            self.reframes += 1
            return True

        def reset_to_start(self):
            self.resets += 1

        def scan_status(self):
            return {
                "active": True, "index": 2, "completed": 2, "total": 4,
                "total_targets": 4, "repetitions": 1, "target_id": 3,
                "order_index": 2, "rep": 1, "last_target_id": 2,
                "last_order_index": 1, "last_rep": 1, "path_step": 0,
                "path_total": 0, "preparing": False, "message": "pulse 2",
                "branch_changes": [], "results": [],
            }

        def collision_state(self):
            return {
                "collision": False, "warning": False, "distance_mm": 12.0,
                "self_collision": False, "self_contact_mm": None,
                "head_contact": False,
            }

    tab = window.collision_tab
    original = tab.session
    fake = FakeSession()
    tab.session = fake
    monkeypatch.setattr(tab._scan_timer, "isActive", lambda: True)
    try:
        tab._base_changed([0.1, 0.0, 0.0], [0.0, 0.0, 0.0])
        tab._head_changed([0.4, -0.4, 0.0], [0.0, 0.0, -90.0])
        assert fake.reframes == 2
        assert fake.resets == 0
    finally:
        tab.session = original


def test_clear_pose_keeps_the_last_near_miss_visible(window):
    class FakeSession:
        scan_active = False

        def __init__(self):
            self.state = {
                "collision": False,
                "warning": True,
                "distance_mm": 6.2,
                "self_collision": False,
                "self_contact_mm": None,
                "head_contact": False,
            }

        def update_contact_colors(self):
            pass

        def collision_state(self):
            return self.state

        def scan_status(self):
            return {"active": False}

    tab = window.collision_tab
    original = tab.session
    fake = FakeSession()
    tab.session = fake
    tab._last_problem = None
    try:
        tab._update_collision()
        assert "NEAR MISS" in tab.collision_label.text()

        fake.state = {
            "collision": False,
            "warning": False,
            "distance_mm": 12.0,
            "self_collision": False,
            "self_contact_mm": None,
            "head_contact": False,
        }
        tab._update_collision()
        text = tab.collision_label.text()
        assert "Last:" in text
        assert "NEAR MISS" in text
        assert "no collision" not in text.lower()
    finally:
        tab.session = original


def test_thresholds_choose_direct_or_safe_height(monkeypatch):
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        session.set_motion_limits(350.0, 20.0, 15.0)
        target = [0.0] * len(session.ik.active_indices)
        safe_calls = []

        def fake_safe_path(current, target, current_pos, current_ori,
                           target_pos, target_ori):
            safe_calls.append((current_pos, current_ori,
                               target_pos, target_ori))
            return [[0.0] * 6 for _ in range(3 * SCAN_STEPS)]

        monkeypatch.setattr(
            session, "current_end_effector",
            lambda: ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0]))
        monkeypatch.setattr(session, "_build_safe_height_path",
                            fake_safe_path)

        direct = session._build_motion_path(
            target, target, ([10.0, 0.0, 0.0], [0.0, 0.0, 0.0]))
        assert len(direct) == SCAN_STEPS
        assert safe_calls == []

        direct_rotation = session._build_motion_path(
            target, target, ([0.0, 0.0, 0.0], [10.0, 0.0, 0.0]))
        assert len(direct_rotation) == SCAN_STEPS
        assert safe_calls == []

        large_translation = session._build_motion_path(
            target, target, ([20.1, 0.0, 0.0], [0.0, 0.0, 0.0]))
        assert len(large_translation) == 3 * SCAN_STEPS
        assert len(safe_calls) == 1

        large_rotation = session._build_motion_path(
            target, target, ([0.0, 0.0, 0.0], [15.1, 0.0, 0.0]))
        assert len(large_rotation) == 3 * SCAN_STEPS
        assert len(safe_calls) == 2
    finally:
        session.dispose()


def test_safe_height_uses_the_configured_limit(monkeypatch):
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        session.set_motion_limits(420.0, 20.0, 15.0)
        solution = [0.0] * len(session.ik.chain.links)
        calls = []

        def fake_solve(position, orientation, initial):
            calls.append(list(position))
            return True, solution

        monkeypatch.setattr(
            session, "current_end_effector",
            lambda: ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0]))
        monkeypatch.setattr(session, "_solve_selected_branch", fake_solve)
        target = [0.0] * len(session.ik.active_indices)
        path = session._build_motion_path(
            target, target, ([100.0, 0.0, 0.0], [0.0, 0.0, 0.0]))
        assert len(path) == 3 * SCAN_STEPS
        assert calls[0][2] == pytest.approx(420.0)
        assert calls[1][2] == pytest.approx(420.0)
    finally:
        session.dispose()


def test_movement_limits_are_saved_and_edited(window, qapp):
    tab = window.collision_tab
    tab._enable()
    qapp.processEvents()
    try:
        tab.safe_height_spin.setValue(410.0)
        tab.translation_spin.setValue(12.0)
        tab.rotation_spin.setValue(7.0)
        qapp.processEvents()
        limits = tab.session.motion_limits
        assert limits.safe_height_mm == pytest.approx(410.0)
        assert limits.translation_threshold_mm == pytest.approx(12.0)
        assert limits.rotation_threshold_deg == pytest.approx(7.0)
        assert tab.project_config()["safe_height_mm"] == pytest.approx(410.0)
    finally:
        tab._disable()


def test_scan_target_jump_moves_one_pulse(monkeypatch):
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        session._scan_active = True
        session._scan_base_targets = [
            ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0]) for _ in range(4)]
        session._scan_index = 1
        session._scan_completed = 1
        prepared = []
        monkeypatch.setattr(
            session, "_prepare_next", lambda: prepared.append(True))

        assert session.can_jump_target(-1)
        assert session.can_jump_target(1)
        assert session.jump_target(1) is True
        assert session._scan_index == 2
        assert session.jump_target(-1) is True
        assert session._scan_index == 1
        assert prepared == [True, True]

        session._scan_index = 0
        assert not session.can_jump_target(-1)
        assert not session.jump_target(-1)
        session._scan_index = 3
        assert not session.can_jump_target(1)
    finally:
        session.dispose()


def test_reframe_scan_keeps_progress_and_recomputes_targets(monkeypatch):
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        session._scan_active = True
        session._scan_placements = [
            ([0.0, 0.0, 50.0], [0.0, 0.0, 0.0]),
            ([10.0, 0.0, 50.0], [0.0, 0.0, 0.0]),
        ]
        session._scan_target_order = [0, 1]
        session._scan_repetitions = 1
        session._scan_total_targets = 2
        session._scan_index = 1
        session._scan_completed = 1
        session._scan_results = [{"index": 0, "ok": True}]
        old_world = session._scan_world_targets
        prepared = []
        monkeypatch.setattr(
            session, "_prepare_next", lambda: prepared.append(True))

        session.set_head_pose([0.5, -0.4, 0.0], [0.0, 0.0, -90.0])
        assert session.reframe_scan() is True
        assert len(session._scan_base_targets) == 2
        assert len(session._scan_world_targets) == 2
        assert session._scan_index == 1
        assert session._scan_completed == 1
        assert session._scan_results == [{"index": 0, "ok": True}]
        assert prepared == [True]
        assert session._scan_world_targets != old_world
    finally:
        session.dispose()


def test_shallow_self_mesh_overlap_is_not_a_collision(monkeypatch):
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        monkeypatch.setattr(session.world, "get_robot_head_contacts", lambda: [])
        monkeypatch.setattr(
            session.world, "get_robot_head_closest_distance", lambda **kw: None)
        monkeypatch.setattr(
            session.world, "get_self_collision_contacts",
            lambda: [{"dist": -0.0010}])
        shallow = session.collision_state()
        assert shallow["collision"] is False
        assert shallow["self_collision"] is False
        assert shallow["self_contact_mm"] == pytest.approx(-1.0)

        monkeypatch.setattr(
            session.world, "get_self_collision_contacts",
            lambda: [{"dist": -0.010}])
        deep = session.collision_state()
        assert deep["collision"] is True
        assert deep["self_collision"] is True
    finally:
        session.dispose()


def test_known_link3_link5_false_contact_is_excluded():
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        session.world.reset_joint_positions(np.radians(
            [-9.0, 28.97, 91.86, -120.93, 9.0, 0.0]).tolist())
        state = session.collision_state()
        assert state["collision"] is False
        assert state["self_collision"] is False
        assert state["self_contact_mm"] is None
    finally:
        session.dispose()


def test_self_collision_still_detects_a_real_fold():
    session = CollisionTestSession(scene_name=SCENE_NAME)
    session.ensure_ready()
    try:
        session.world.reset_joint_positions(np.radians(
            [131.3, -321.2, -86.7, -227.3, -233.3, 224.7]).tolist())
        state = session.collision_state()
        assert state["collision"] is True
        assert state["self_collision"] is True
        assert state["self_contact_mm"] < -2.0
    finally:
        session.dispose()
