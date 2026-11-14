"""Collision-test tab: local world, saved setup and the placement scan."""

import json

import numpy as np
import pytest
from PyQt5 import QtWidgets
from scipy.spatial.transform import Rotation

pytest.importorskip("PyQt5.QtWidgets")
pytest.importorskip("mujoco")
pytest.importorskip("ikpy")

from neuropilot.controller.collision_test import CollisionTestSession
from neuropilot.controller.pipeline_controller import read_simnibs_targets_data
from neuropilot.lab_profile import LabProfile
from neuropilot.sim_robot.utils.transforms import orientation_distance_deg

pytestmark = pytest.mark.gui


CUSTOM = {
    "head_position_m": [0.4, -0.4, 0.0],
    "head_orientation_deg": [0.0, 0.0, -90.0],
    "robot_base_position_m": [-0.2, 0.2, 0.0],
    "robot_base_orientation_deg": [0.0, 0.0, 0.0],
    "start_joints_rad": [0.1, 0.2, 0.3, -0.4, 0.5, -0.6],
    "branch": ["right", "up", "normal"],
}


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
        assert not tab.session.scan_active
        assert tab.session.scan_results
        assert any(r["collision"] or not r["ok"]
                   for r in tab.session.scan_results)
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
    session = CollisionTestSession()
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
    session = CollisionTestSession()
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
    session = CollisionTestSession()
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
    assert scroll.width() >= 850
    assert tab.view_label.width() >= 300
    assert tab.view_label.minimumWidth() == 300
    assert scroll.maximumWidth() == 1000
    assert scroll.verticalScrollBar().maximum() == 0
    assert not scroll.verticalScrollBar().isVisible()


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
    assert tab.set_start_btn.text() == "Set start from current"
    assert tab.apply_branch_btn.text() == "Set start pose from selection"
    assert tab.wrist_choice.count() == 2
    for button in (tab.save_project_btn, tab.save_lab_btn, tab.use_btn):
        assert button.toolTip().strip()


def test_start_pose_uses_visible_radio_buttons(window):
    tab = window.collision_tab
    for choice, labels in (
            (tab.shoulder_choice, ("Shoulder left", "Shoulder right")),
            (tab.arm_choice, ("Arm up", "Arm down")),
            (tab.wrist_choice, ("Wrist normal", "Wrist flipped"))):
        assert choice.count() == 2
        assert tuple(button.text() for button in choice.buttons()) == labels
        assert sum(button.isChecked() for button in choice.buttons()) == 1
    assert tab.step_combo.sizeHint().height() >= 48
    assert tab.step_combo.view().sizeHintForRow(0) >= 44


def test_go_start_returns_to_the_saved_pose_and_reports_it(window, qapp):
    tab = window.collision_tab
    tab._enable()
    qapp.processEvents()
    try:
        start = list(tab.session.start_joints)
        before = list(tab.session.current_joints())
        tab._jog("X", 1)
        qapp.processEvents()
        assert not np.allclose(tab.session.current_joints(), before)
        assert not np.allclose(tab.session.current_joints(), start)

        tab.reset_btn.click()
        qapp.processEvents()
        assert np.allclose(tab.session.current_joints(), start)
        assert tab.status_label.text() == "Moved to the saved start pose."
        assert tab.scan_status.text() == "Idle."

        tab.reset_btn.click()
        qapp.processEvents()
        assert tab.status_label.text() == "Already at the saved start pose."
        assert tab.scan_status.text() == "Idle."
    finally:
        tab._disable()


def test_collision_controls_scale_with_the_window(window, qapp):
    tab = window.collision_tab
    tab._last_ui_scale = None
    tab.apply_ui_scale(2.0)
    assert tab.scroll.minimumWidth() >= 1520
    assert tab.view_label.minimumWidth() >= 600
    assert all(button.width() < spin.width() for button, spin in zip(
        tab.base_editor._nudge_buttons[::2], tab.base_editor._spins))


def test_selected_branch_retries_with_the_simulation_solver(monkeypatch):
    session = CollisionTestSession()
    session.ensure_ready()
    try:
        solution = [0.0] * len(session.ik.chain.links)
        for index in session.ik.active_indices:
            solution[index] = 0.1
        monkeypatch.setattr(session.ik, "solve_branch",
                            lambda *args, **kwargs: (False, None))
        monkeypatch.setattr(session.ik, "solve_with_config",
                            lambda *args, **kwargs: (True, solution))
        session._scan_active = True
        session._scan_base_targets = [([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])]
        session._scan_index = 0
        session._scan_completed = 0
        session.branch = ("right", "down", "flipped")

        session._prepare_next()
        state = session.scan_status()
        assert state["active"]
        assert state["message"].startswith("pulse 0 · 1/1 · target 0")
        assert "IK branch changed" in state["message"]
        assert state["branch_changes"] == [{
            "index": 0,
            "target_id": 0,
            "order_index": 0,
            "rep": 1,
            "selected": ["right", "down", "flipped"],
            "used": ["left", "up", "normal"],
        }]
        assert session.branch == ("right", "down", "flipped")
    finally:
        session.dispose()


def test_both_solvers_failing_is_reported_as_ik_not_collision(monkeypatch):
    session = CollisionTestSession()
    session.ensure_ready()
    try:
        monkeypatch.setattr(session.ik, "solve_branch",
                            lambda *args, **kwargs: (False, None))
        monkeypatch.setattr(session.ik, "solve_with_config",
                            lambda *args, **kwargs: (False, None))
        session._scan_active = True
        session._scan_base_targets = [([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])]
        session._scan_index = 0
        session._scan_completed = 0

        session._prepare_next()
        state = session.scan_status()
        assert not state["active"]
        assert state["message"] == "no IK solution"
        assert state["completed"] == 0
        assert state["results"][-1]["message"] == "IK failed"
        assert state["results"][-1]["collision"] is False
    finally:
        session.dispose()


def test_target_reached_is_rendered_before_preparing_the_next(monkeypatch):
    session = CollisionTestSession()
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
    session = CollisionTestSession()
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


def test_wrist_choice_changes_the_start_pose(window, qapp):
    import math

    tab = window.collision_tab
    tab._enable()
    qapp.processEvents()
    try:
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
