"""Placement conversion must agree between the collision test and robot."""

import numpy as np
from scipy.spatial.transform import Rotation

from neuropilot.controller.pipeline_controller import read_simnibs_targets_data
from neuropilot.sim_robot import config as sim_config
from neuropilot.sim_robot.message_handlers import MessageHandlers
from neuropilot.sim_robot.state import RobotState
from neuropilot.sim_robot.utils.transforms import (
    m_to_mm,
    orientation_distance_deg,
    pipeline_target_to_mujoco_world,
    simnibs_to_mujoco_world,
)


def _placement_matrix(raw_ori_deg, raw_pos_mm):
    matrix = np.eye(4)
    matrix[:3, :3] = Rotation.from_euler(
        "xyz", raw_ori_deg, degrees=True).as_matrix()
    matrix[:3, 3] = raw_pos_mm
    return matrix[:, :, None]


def test_pipeline_orientation_undoes_the_axis_convention(h5file):
    raw_ori = [12.0, -34.0, 56.0]
    raw_pos = [0.0, 0.0, 50.0]
    path = h5file({"matsimnibs": _placement_matrix(raw_ori, raw_pos)},
                  "placements.hdf5")
    pipeline_targets, _ = read_simnibs_targets_data(str(path))
    pipeline_pos, pipeline_ori = pipeline_targets[0]

    expected_pos, expected_ori = simnibs_to_mujoco_world(
        raw_pos, raw_ori, sim_config.HEAD_POSITION,
        sim_config.HEAD_ORIENTATION)
    got_pos, got_ori = pipeline_target_to_mujoco_world(
        pipeline_pos, pipeline_ori, sim_config.HEAD_POSITION,
        sim_config.HEAD_ORIENTATION)

    assert np.allclose(got_pos, expected_pos, atol=1e-9)
    assert orientation_distance_deg(got_ori, expected_ori) < 1e-6


def test_the_robot_handler_uses_the_same_conversion(h5file):
    raw_ori = [12.0, -34.0, 56.0]
    raw_pos = [0.0, 0.0, 50.0]
    path = h5file({"matsimnibs": _placement_matrix(raw_ori, raw_pos)},
                  "placements.hdf5")
    pipeline_targets, _ = read_simnibs_targets_data(str(path))
    pipeline_pos, pipeline_ori = pipeline_targets[0]

    state = RobotState()
    handlers = MessageHandlers(state, world=None)
    handlers.handle("Neuronavigation to Robot: Set target", {
        "position": pipeline_pos,
        "orientation": pipeline_ori,
    })

    expected_pos, expected_ori = pipeline_target_to_mujoco_world(
        pipeline_pos, pipeline_ori, sim_config.HEAD_POSITION,
        sim_config.HEAD_ORIENTATION)
    assert np.allclose(state.target.position, m_to_mm(expected_pos), atol=1e-6)
    assert orientation_distance_deg(state.target.orientation,
                                    expected_ori) < 1e-6
