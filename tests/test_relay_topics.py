"""The relay wire protocol is a contract between independently built parts.

The controller, the simulated robot and the simulated neuronavigation each
spell the topic strings out.  If one of them drifts, the message is silently
dropped at runtime (the send path never raises), so the agreement is tested
here instead.
"""

import inspect

import pytest

from neuropilot.controller import pipeline_controller as pc
from neuropilot.sim_nav import config as nav_config
from neuropilot.sim_robot import config as robot_config


def test_head_mesh_topic_matches_the_simulator():
    assert pc.TOPIC_SET_HEAD_MESH == robot_config.TOPIC_SET_HEAD_MESH


@pytest.mark.parametrize("topic", [
    "Neuronavigation to Robot: Set objective",
    "Neuronavigation to Robot: Set free drive",
    "GUI to Robot: set default speed robot",
    "GUI to Robot: set tuning speed robot",
    "Press robot button",
    "STOP",
    "Pipeline to Robot: Set start pose",
    "Pipeline to Robot: Set motion limits",
])
def test_controller_topics_exist_in_the_robot_simulator(topic):
    known = {value for name, value in vars(robot_config).items()
             if name.startswith("TOPIC_") and isinstance(value, str)}
    assert topic in known


def test_create_marker_topic_matches_the_navigation_simulator():
    source = inspect.getsource(pc.PipelineController.send_marker_step)
    assert nav_config.TOPIC_CREATE_TARGET in source
    assert nav_config.TOPIC_CREATE_TARGET == robot_config.TOPIC_CREATE_MARKER


def test_navigation_reports_use_the_topics_the_controller_listens_to():
    assert nav_config.TOPIC_COIL_AT_TARGET == "From Neuronavigation: Coil at target"
    assert nav_config.TOPIC_REALIZED_TARGET == "From Neuronavigation: Coil target created"
    assert nav_config.TOPIC_SIM_TRACKING_STATE == robot_config.TOPIC_TRACKING_STATE


def test_robot_health_topic_matches_the_simulator():
    from neuropilot.controller.systems.robot import Robot
    source = inspect.getsource(Robot.__init__)
    assert robot_config.TOPIC_HEALTH_STATUS in source


def test_stim_marker_topic_matches_the_navigation_simulator():
    source = inspect.getsource(pc.PipelineController.fire_stim_step)
    assert nav_config.TOPIC_STIM_MARKER in source


def test_no_component_prefix_leaks_into_topic_names():
    # House rule: additions are unprefixed so they can flow upstream.
    topics = [value for module in (robot_config, nav_config)
              for name, value in vars(module).items()
              if name.startswith("TOPIC_") and isinstance(value, str)]
    for topic in topics:
        assert not topic.lower().startswith(("np ", "neuropilot ")), topic
