"""The collision-tested start pose crosses the relay as joint angles."""

import asyncio

from neuropilot.sim_robot import config as robot_config
from neuropilot.sim_robot.message_handlers import MessageHandlers
from neuropilot.sim_robot.state import RobotState


class _World:
    def __init__(self):
        self.calls = []

    def reset_joint_positions(self, joints):
        self.calls.append(list(joints))


def test_topics_agree():
    from neuropilot.controller import pipeline_controller as pc

    assert pc.TOPIC_SET_START_POSE == robot_config.TOPIC_SET_START_POSE


def test_controller_announces_the_pose(controller):
    from neuropilot.controller import pipeline_controller as pc

    joints = [0.1, 0.2, 0.3, -0.4, 0.5, -0.6]

    async def run():
        controller.set_start_pose(joints)
        await asyncio.sleep(0)

    asyncio.run(run())
    topic, data = controller.remote.sent[-1]
    assert topic == pc.TOPIC_SET_START_POSE
    assert data == {"joints": joints}
    assert controller.start_pose_joints == joints


def test_controller_announces_the_branch(controller):
    from neuropilot.controller import pipeline_controller as pc

    joints = [0.1, 0.2, 0.3, -0.4, 0.5, -0.6]
    branch = ["right", "up", "normal"]

    async def run():
        controller.set_start_pose(joints, branch)
        await asyncio.sleep(0)

    asyncio.run(run())
    topic, data = controller.remote.sent[-1]
    assert topic == pc.TOPIC_SET_START_POSE
    assert data == {"joints": joints, "branch": branch}
    assert controller.start_pose_branch == branch


def test_simulator_applies_the_pose():
    state = RobotState()
    world = _World()
    handlers = MessageHandlers(state, world)
    joints = [0.1, 0.2, 0.3, -0.4, 0.5, -0.6]

    handlers.handle(robot_config.TOPIC_SET_START_POSE, {"joints": joints})

    assert state.start_joints == joints
    assert state.start_branch is None
    assert world.calls == [joints]


def test_simulator_applies_the_branch():
    state = RobotState()
    world = _World()
    handlers = MessageHandlers(state, world)
    joints = [0.1, 0.2, 0.3, -0.4, 0.5, -0.6]
    branch = ["right", "up", "normal"]

    handlers.handle(robot_config.TOPIC_SET_START_POSE,
                    {"joints": joints, "branch": branch})

    assert state.start_branch == branch


def test_controller_announces_motion_limits(controller):
    from neuropilot.controller import pipeline_controller as pc

    limits = {
        "safe_height_mm": 420.0,
        "translation_threshold_mm": 12.0,
        "rotation_threshold_deg": 7.0,
    }

    async def run():
        controller.set_motion_limits(limits, announce=True)
        await asyncio.sleep(0)

    asyncio.run(run())
    topic, data = controller.remote.sent[-1]
    assert topic == pc.TOPIC_SET_MOTION_LIMITS
    assert data == limits
    assert controller.motion_limits == limits


def test_simulator_applies_motion_limits():
    state = RobotState()
    handlers = MessageHandlers(state, _World())
    limits = {
        "safe_height_mm": 420.0,
        "translation_threshold_mm": 12.0,
        "rotation_threshold_deg": 7.0,
    }

    handlers.handle(robot_config.TOPIC_SET_MOTION_LIMITS, limits)

    assert state.motion_limits.safe_height_mm == 420.0
    assert state.motion_limits.translation_threshold_mm == 12.0
    assert state.motion_limits.rotation_threshold_deg == 7.0


def test_simulator_ignores_incomplete_motion_limits():
    state = RobotState()
    handlers = MessageHandlers(state, _World())

    handlers.handle(robot_config.TOPIC_SET_MOTION_LIMITS,
                    {"safe_height_mm": 420.0})

    assert state.motion_limits.safe_height_mm == (
        robot_config.SAFE_HEIGHT_MM)
    assert state.motion_limits.translation_threshold_mm == (
        robot_config.TRANSLATION_THRESHOLD_MM)


def test_simulator_ignores_a_pose_of_the_wrong_length():
    state = RobotState()
    world = _World()
    handlers = MessageHandlers(state, world)

    handlers.handle(robot_config.TOPIC_SET_START_POSE,
                    {"joints": [0.1, 0.2]})

    assert state.start_joints == []
    assert world.calls == []
