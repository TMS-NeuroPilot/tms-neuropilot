"""The project head mesh drives the simulated phantom.

The GUI must announce every path change (browse, paste, clear), and the
simulator must replace or reset the phantom and persist the override.
"""

import asyncio
import json
import os
import time
from types import SimpleNamespace

import pytest

from neuropilot.sim_robot import config as robot_config
from neuropilot.sim_robot.message_handlers import MessageHandlers
from neuropilot.sim_robot.state import RobotState


class _World:
    def __init__(self):
        self.head_mesh_stl = None
        self.calls = []

    def reload_head(self, stl):
        self.calls.append(stl)
        self.head_mesh_stl = stl
        return True


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _record_head_calls(window, controller, monkeypatch):
    calls = SimpleNamespace(head=[], mesh=[])

    monkeypatch.setattr(controller, "set_head_mesh",
                        lambda path: calls.head.append(path))
    monkeypatch.setattr(controller.online_fem_mgr, "set_mesh_fn_msh",
                        lambda path: calls.mesh.append(path))
    window.controller = controller
    return calls


@pytest.mark.gui
def test_browse_mesh_announces_the_subject_head(window, controller, tmp_path, monkeypatch):
    calls = _record_head_calls(window, controller, monkeypatch)
    mesh = tmp_path / "subject.msh"
    mesh.write_text("not read by this test")
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: str(mesh))
    monkeypatch.setattr(window, "_load_mesh_async", lambda *a, **k: None)

    window.pick_mesh()

    assert calls.head == [str(mesh)]
    assert calls.mesh == [str(mesh)]


@pytest.mark.gui
def test_clearing_the_mesh_resets_the_simulated_head(window, controller, monkeypatch):
    calls = _record_head_calls(window, controller, monkeypatch)
    window.loadmeshlabel.setText("")
    monkeypatch.setattr(window, "_clear_mesh", lambda *a, **k: None)

    window.paste_mesh_path()

    assert calls.head == [None]
    assert calls.mesh == [None]


@pytest.mark.gui
def test_missing_mesh_path_resets_the_simulated_head(window, controller, monkeypatch):
    calls = _record_head_calls(window, controller, monkeypatch)
    window.loadmeshlabel.setText("/definitely/not/a/mesh.msh")

    window.paste_mesh_path()

    assert window.loadmeshlabel.text() == ""
    assert calls.head == [None]


@pytest.mark.parametrize("path,expected", [
    ("subject.msh", "subject.msh"),
    ("", None),
    (None, None),
])
def test_controller_announces_every_head_state(controller, path, expected):
    from neuropilot.controller import pipeline_controller as pc

    async def run():
        controller.set_head_mesh(path)
        await asyncio.sleep(0)

    asyncio.run(run())
    topic, data = controller.remote.sent[-1]
    assert topic == pc.TOPIC_SET_HEAD_MESH
    assert data == {"mesh_path": expected}


def test_simulator_converts_persists_and_applies_the_subject_head(
        tmp_path, monkeypatch):
    mesh = tmp_path / "subject.msh"
    mesh.write_text("placeholder")
    stl = tmp_path / "subject_head_sim.stl"
    stl.write_text("placeholder")
    override_file = tmp_path / "sim_head_override.json"
    monkeypatch.setattr(robot_config, "HEAD_OVERRIDE_FILE", str(override_file))

    from neuropilot.sim_robot import mesh_converter
    monkeypatch.setattr(mesh_converter, "convert_head_mesh", lambda path: str(stl))

    state = RobotState()
    world = _World()
    handlers = MessageHandlers(state, world)

    handlers.handle(robot_config.TOPIC_SET_HEAD_MESH,
                    {"mesh_path": str(mesh)})

    assert _wait_until(lambda: state.head_mesh_source == str(mesh))
    assert world.calls == [str(stl)]
    payload = json.loads(override_file.read_text())
    assert payload == {"msh_path": str(mesh), "stl_path": str(stl)}


def test_clearing_the_head_removes_the_persisted_override(tmp_path, monkeypatch):
    override_file = tmp_path / "sim_head_override.json"
    override_file.write_text(json.dumps({"msh_path": "old.msh",
                                         "stl_path": "old.stl"}))
    monkeypatch.setattr(robot_config, "HEAD_OVERRIDE_FILE", str(override_file))

    state = RobotState(head_mesh_source="old.msh")
    world = _World()
    world.head_mesh_stl = "old.stl"
    handlers = MessageHandlers(state, world)

    handlers.handle(robot_config.TOPIC_SET_HEAD_MESH, {"mesh_path": None})

    assert _wait_until(lambda: state.head_mesh_source is None)
    assert world.calls == [None]
    assert not override_file.exists()


def test_an_invalid_announcement_does_not_leave_a_stale_override(
        tmp_path, monkeypatch):
    override_file = tmp_path / "sim_head_override.json"
    override_file.write_text(json.dumps({"msh_path": "old.msh",
                                         "stl_path": "old.stl"}))
    monkeypatch.setattr(robot_config, "HEAD_OVERRIDE_FILE", str(override_file))

    state = RobotState(head_mesh_source="old.msh")
    world = _World()
    world.head_mesh_stl = "old.stl"
    handlers = MessageHandlers(state, world)

    handlers.handle(robot_config.TOPIC_SET_HEAD_MESH,
                    {"mesh_path": str(tmp_path / "missing.msh")})

    assert _wait_until(lambda: state.head_mesh_source is None)
    assert world.calls == [None]
    assert not override_file.exists()

