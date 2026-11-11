"""The robot registry: what a new robot needs, and that the current one works.

The simulator is robot-agnostic; everything robot-specific is one RobotSpec in
``sim_robot/robots.py``.  These tests pin the contract so a new robot is added
by data (assets + one spec), not by editing code in several places.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from neuropilot.sim_robot import robots
from neuropilot.sim_robot.robots import RobotSpec

SRC = Path(__file__).resolve().parents[1] / "src"


def run(*args):
    return subprocess.run([sys.executable, "-m", "neuropilot.sim_robot.robots",
                           *args], capture_output=True, text=True, timeout=120,
                          cwd=str(SRC.parent),
                          env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"})


# ── the registry ───────────────────────────────────────────────────────

def test_every_spec_is_complete():
    for key, spec in robots.ROBOTS.items():
        assert spec.key == key
        assert spec.label
        assert spec.mjcf.endswith(".xml")
        assert spec.urdf.endswith(".urdf")
        assert spec.base_body and spec.ee_site
        assert len(spec.ik_active_links) >= 3
        assert len(spec.base_position) == 3
        assert len(spec.base_orientation) == 3
        assert len(spec.camera_offset) == 3


def test_the_default_robot_is_registered():
    assert robots.DEFAULT_ROBOT in robots.ROBOTS


def test_lookup_is_case_insensitive_and_strips():
    assert robots.get("  OMRON ").key == "omron"


def test_unknown_lookup_lists_the_known_robots():
    with pytest.raises(KeyError) as excinfo:
        robots.get("kuka")
    assert "kuka" in str(excinfo.value)
    assert "omron" in str(excinfo.value)
    assert "docs/ROBOTS.md" in str(excinfo.value)


def test_resolve_falls_back_with_a_warning(capsys):
    spec = robots.resolve("kuka")
    assert spec.key == robots.DEFAULT_ROBOT
    assert "not a known robot" in capsys.readouterr().out


def test_labels_pair_keys_with_human_names():
    pairs = robots.labels()
    assert ("omron", "Omron TM5X-700") in pairs


# ── the shipped assets ─────────────────────────────────────────────────

@pytest.mark.parametrize("key", robots.keys())
def test_shipped_robot_passes_its_check(key):
    problems = robots.check(robots.get(key))
    assert problems == []


def test_check_reports_a_missing_mjcf(tmp_path):
    spec = RobotSpec(key="x", label="X", mjcf="nope.xml", urdf="nope.urdf",
                     base_body="base", ee_site="tcp",
                     ik_active_links=(False, True, True, True))
    problems = robots.check(spec, root=tmp_path)
    assert any("MuJoCo model missing" in p for p in problems)
    assert any("IK URDF missing" in p for p in problems)


def test_check_reports_a_missing_site(tmp_path):
    mjcf = tmp_path / "robot.xml"
    mjcf.write_text('<mujoco><worldbody><body name="base">'
                    '<site name="other"/></body></worldbody></mujoco>')
    urdf = tmp_path / "robot.urdf"
    urdf.write_text('<robot name="r"><link name="base"/><link name="tip"/>'
                    '<joint name="j" type="revolute"/></robot>')
    spec = RobotSpec(key="x", label="X", mjcf="robot.xml", urdf="robot.urdf",
                     base_body="base", ee_site="tcp",
                     ik_active_links=(False, True, True))
    problems = robots.check(spec, root=tmp_path)
    assert any("no <site name='tcp'>" in p for p in problems)


def test_check_reports_a_missing_base_body(tmp_path):
    mjcf = tmp_path / "robot.xml"
    mjcf.write_text('<mujoco><worldbody><body name="other">'
                    '<site name="tcp"/></body></worldbody></mujoco>')
    urdf = tmp_path / "robot.urdf"
    urdf.write_text('<robot name="r"><link name="base"/><link name="tip"/>'
                    '<joint name="j" type="revolute"/></robot>')
    spec = RobotSpec(key="x", label="X", mjcf="robot.xml", urdf="robot.urdf",
                     base_body="base", ee_site="tcp",
                     ik_active_links=(False, True, True))
    problems = robots.check(spec, root=tmp_path)
    assert any("no <body name='base'>" in p for p in problems)


def test_check_reports_a_broken_xml(tmp_path):
    (tmp_path / "robot.xml").write_text("<mujoco><worldbody>")
    (tmp_path / "robot.urdf").write_text("<robot><link")
    spec = RobotSpec(key="x", label="X", mjcf="robot.xml", urdf="robot.urdf",
                     base_body="base", ee_site="tcp",
                     ik_active_links=(False, True, True))
    problems = robots.check(spec, root=tmp_path)
    assert any("does not parse" in p for p in problems)


def test_check_reports_a_mismatched_ik_mask():
    spec = robots.ROBOTS["omron"]
    broken = RobotSpec(**{**spec.__dict__,
                          "ik_active_links": (False, True, True)})
    problems = robots.check(broken)
    # ikpy either builds a shorter chain (mismatch reported) or refuses the
    # mask outright; both are caught.
    assert any("one entry per link" in p or "ikpy cannot build" in p
               for p in problems)


def test_check_requires_a_plausible_mask():
    spec = robots.ROBOTS["omron"]
    broken = RobotSpec(**{**spec.__dict__, "ik_active_links": (True,)})
    problems = robots.check(broken)
    assert any("at least three" in p for p in problems)


# ── config wiring ──────────────────────────────────────────────────────

def test_config_derives_its_constants_from_the_spec():
    from neuropilot.sim_robot import config
    spec = config.ROBOT_SPEC
    assert config.ROBOT == spec.key
    assert config.ROBOT_KNOWN is True
    assert config.ROBOT_MJCF[spec.key] == spec.mjcf
    assert config.ROBOT_URDF_PATH == spec.urdf
    assert config.ROBOT_BASE_BODY_NAME == spec.base_body
    assert config.END_EFFECTOR_SITE_NAME == spec.ee_site
    assert list(spec.ik_active_links) == config.IK_ACTIVE_LINKS_MASK
    assert list(spec.ik_base_elements) == config.IK_BASE_ELEMENTS
    assert list(spec.base_position) == config.ROBOT_BASE_POSITION
    assert spec.label in config.MODEL_NAME


def test_config_lists_every_geometry_for_the_gui():
    from neuropilot.sim_robot import config
    assert set(config.ROBOT_MJCF) == set(robots.keys())


# ── the CLI ────────────────────────────────────────────────────────────

def test_cli_lists_the_robots():
    result = run("--list")
    assert result.returncode == 0, result.stderr
    assert "omron" in result.stdout
    assert "Omron TM5X-700" in result.stdout


def test_cli_checks_a_robot():
    result = run("--check", "omron")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[OK]" in result.stdout


def test_cli_reports_an_unknown_robot():
    result = run("--check", "kuka")
    assert result.returncode == 2
    assert "not a known robot" in result.stdout
