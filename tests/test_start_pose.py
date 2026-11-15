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


def test_simulator_ignores_a_pose_of_the_wrong_length():
    state = RobotState()
    world = _World()
    handlers = MessageHandlers(state, world)

    handlers.handle(robot_config.TOPIC_SET_START_POSE,
                    {"joints": [0.1, 0.2]})

    assert state.start_joints == []
    assert world.calls == []
