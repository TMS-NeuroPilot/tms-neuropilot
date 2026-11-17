"""Coil-holder selection for the simulated robot tool."""

from pathlib import Path

import pytest

pytest.importorskip("mujoco")

from neuropilot.sim_robot import config as sim_config
from neuropilot.sim_robot.mujoco_world import MuJoCoWorld


@pytest.fixture()
def world(qapp, tmp_path):
    spec = sim_config.ROBOT_SPEC
    widget = MuJoCoWorld(
        use_gui=False,
        scene_name=f"_coil_holder_test_{tmp_path.name}.xml",
        head_pose=(list(sim_config.HEAD_POSITION),
                   list(sim_config.HEAD_ORIENTATION)),
        base_pose=(list(spec.base_position), list(spec.base_orientation)),
    )
    try:
        yield widget
    finally:
        widget.disconnect()


def _scene_path(world):
    return Path(world._compose_scene())


def test_default_scene_uses_b65_and_removes_stale_overrides(world):
    scene = _scene_path(world)
    text = scene.read_text()
    assert 'include file="robot_tm5x_700.xml"' in text
    assert "coil_holder_b35_case" not in text
    override = scene.with_name(scene.stem + "_coil_override.xml")
    assert not override.exists()


def test_b35_scene_uses_a_coil_override(world, monkeypatch):
    monkeypatch.setattr(sim_config, "COIL_HOLDER", "b35")
    scene = _scene_path(world)
    override = scene.with_name(scene.stem + "_coil_override.xml")
    try:
        assert override.is_file()
        override_text = override.read_text()
        assert "coil_holder_b35_case_v2.4_fixed.stl" in override_text
        assert "coil_holder_b35_case_v2.4_collision.stl" in override_text
        assert "coil_holder_b65_case" not in override_text
        assert override.name in scene.read_text()
    finally:
        override.unlink(missing_ok=True)
