"""Robot system: health messages become status + connection details."""

import asyncio

import pytest

from neuropilot.controller.systems.robot import Robot
from neuropilot.controller.systems.system import SystemStatus


class FakeSocket:
    connected = True


class FakeRemote:
    url = "http://localhost:5000"
    sio = FakeSocket()

    def __init__(self):
        self.handlers = {}
        self.sent = []

    def register_handlers(self, handlers):
        self.handlers.update(handlers)

    async def send_message(self, topic, data=None):
        self.sent.append((topic, data))
        return True


@pytest.fixture()
def robot():
    published = []
    remote = FakeRemote()
    robot = Robot(update_control_panel_func=lambda *a, **k: published.append((a, k)),
                  remote=remote)
    robot.published = published
    return robot


def test_health_topic_is_registered(robot):
    assert "Robot to Pipeline: Health status" in robot.remote.handlers


def test_initial_details_show_relay_and_link(robot):
    assert robot.details["Relay"] == "http://localhost:5000"
    assert robot.details["Link"] == "connected"


def test_health_update_sets_status_and_details(robot):
    asyncio.run(robot.on_robot_health_update({
        "robot_id": "omron-1",
        "status": "ok",
        "info": {"Model": "Omron TM5", "Firmware": "1.2.3"},
    }))
    assert robot.robot_id == "omron-1"
    assert robot.status is SystemStatus.OK
    assert robot.details["Robot ID"] == "omron-1"
    assert robot.details["Model"] == "Omron TM5"
    assert robot.details["Firmware"] == "1.2.3"


def test_health_update_keeps_previous_info_when_omitted(robot):
    asyncio.run(robot.on_robot_health_update({
        "robot_id": "omron-1", "status": "ok", "info": {"Model": "Omron TM5"},
    }))
    asyncio.run(robot.on_robot_health_update({"status": "ok"}))
    assert robot.details["Model"] == "Omron TM5"
    assert robot.robot_id == "omron-1"


def test_health_update_with_a_non_mapping_is_ignored(robot):
    asyncio.run(robot.on_robot_health_update(None))
    asyncio.run(robot.on_robot_health_update("ok"))
    assert robot.status is SystemStatus.NAN


def test_unknown_status_text_becomes_nan(robot):
    asyncio.run(robot.on_robot_health_update({"status": "banana"}))
    assert robot.status is SystemStatus.NAN
    assert robot.is_error_state() is True        # not a green light


def test_health_update_without_status_keeps_nan(robot):
    asyncio.run(robot.on_robot_health_update({"robot_id": "x"}))
    assert robot.status is SystemStatus.NAN


def test_error_health_carries_the_message(robot):
    asyncio.run(robot.on_robot_health_update({
        "robot_id": "omron-1", "status": "error", "message": "Socket Broken",
    }))
    assert robot.status is SystemStatus.ERROR
    # The panel receives (system, status, message) and renders the recovery.
    system, status, message = robot.published[-1][0][:3]
    assert system is robot
    assert status is SystemStatus.ERROR
    assert message == "Socket Broken"
    assert "Socket Broken" in robot.ERROR_RECOVERIES
