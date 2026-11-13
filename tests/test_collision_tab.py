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
    "branch": ["right", "up"],
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
                                   shoulder="right", elbow="up")
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
                               shoulder="right", elbow="up")
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
    assert scroll.width() >= 750
    assert tab.view_label.width() >= 360
    assert tab.view_label.minimumWidth() == 360
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
