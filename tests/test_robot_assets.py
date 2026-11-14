"""Shipped robot models: the MJCF and the IK URDF describe the same arm.

The simulator uses two independent descriptions of every robot.  If their
tool frames drift apart, the arm reaches the target but the coil site does
not, so the check belongs in the test suite, not only in a manual run.
"""

from pathlib import Path

import numpy as np
import pytest

from neuropilot.sim_robot import robots

mujoco = pytest.importorskip("mujoco")
ikpy_chain = pytest.importorskip("ikpy.chain")

ASSETS = Path(__file__).resolve().parents[1] / "src" / "neuropilot" / "sim_robot"
KEYS = robots.keys()


def _chain(spec):
    return ikpy_chain.Chain.from_urdf_file(
        str(ASSETS / spec.urdf),
        base=list(spec.ik_base_elements)[0],
        tip=spec.ik_tip,
        active_links_mask=list(spec.ik_active_links),
    )


@pytest.mark.parametrize("key", KEYS)
def test_mjcf_has_joints_actuators_and_the_tool_site(key):
    spec = robots.get(key)
    model = mujoco.MjModel.from_xml_path(str(ASSETS / spec.mjcf))
    assert model.njnt == 6
    assert model.nu == 6
    assert model.site(spec.ee_site).id >= 0
    assert model.body(spec.base_body).id >= 0


@pytest.mark.parametrize("key", KEYS)
def test_urdf_chain_has_six_active_joints_and_ends_at_the_tool(key):
    spec = robots.get(key)
    chain = _chain(spec)
    assert len(chain.links) == len(spec.ik_active_links)
    active = [i for i, link in enumerate(chain.links)
              if link.joint_type != "fixed"
              and spec.ik_active_links[i]]
    assert len(active) == 6
    assert chain.links[-1].name == "coil_tcp_fixed_joint"


@pytest.mark.parametrize("key", KEYS)
def test_urdf_and_mjcf_tool_frames_agree_at_zero(key):
    spec = robots.get(key)
    chain = _chain(spec)
    frame = chain.forward_kinematics([0.0] * len(chain.links))

    model = mujoco.MjModel.from_xml_path(str(ASSETS / spec.mjcf))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    site_id = model.site(spec.ee_site).id
    site_pos = data.site_xpos[site_id]
    site_rot = data.site_xmat[site_id].reshape(3, 3)

    assert np.linalg.norm(frame[:3, 3] - site_pos) < 1e-5
    assert np.linalg.norm(frame[:3, :3] - site_rot) < 1e-5


@pytest.mark.parametrize("driver,key", [
    ("ur", "ur5"),
    ("elfin", "elfin5"),
    ("elfin_new_api", "elfin5"),
    ("dobot", "cr5"),
    ("omron", "omron"),
])
def test_driver_names_from_tms_robot_control_resolve(driver, key):
    assert robots.get(driver).key == key
    assert robots.normalize(driver) == key
