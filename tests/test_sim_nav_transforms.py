"""The navigation transforms: the round trips between coordinate frames.

``simnibs_to_nav_world`` and ``nav_world_to_simnibs`` are documented
inverses; the orientation conversions invert the pipeline's axis
convention.  Every expected value here is known by construction.
"""

import pytest
from scipy.spatial.transform import Rotation

from neuropilot.sim_nav.transforms import (
    inverse_pipeline_axis_transform,
    nav_world_to_simnibs,
    pipeline_orientation_to_simnibs,
    simnibs_orientation_to_external_controller,
    simnibs_to_nav_world,
)


def _rot_close(euler_a, euler_b):
    """Euler representations can differ; compare the rotations themselves."""
    Ra = Rotation.from_euler("xyz", euler_a, degrees=True)
    Rb = Rotation.from_euler("xyz", euler_b, degrees=True)
    return (Ra.inv() * Rb).magnitude() < 1e-9


# ── SimNIBS <-> navigation world (head pose applied) ───────────────────

def test_nav_round_trip_recovers_the_simnibs_target():
    pose = ([30.0, -45.0, 110.0], [10.0, -20.0, 30.0])
    head = ([0.4, -0.4, 0.0], [0.0, 0.0, -90.0])
    world_pos, world_euler = simnibs_to_nav_world(*pose, *head)
    back_pos, back_euler = nav_world_to_simnibs(world_pos, world_euler, *head)
    assert back_pos == pytest.approx(pose[0])
    assert _rot_close(back_euler, pose[1])


def test_nav_world_target_applies_the_head_frame():
    # With the head at the origin and unrotated, the world target is the
    # SimNIBS target in metres — by construction.
    pose = ([30.0, -45.0, 110.0], [10.0, -20.0, 30.0])
    head = ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
    world_pos, _ = simnibs_to_nav_world(*pose, *head)
    assert world_pos == pytest.approx([0.03, -0.045, 0.11])


# ── the pipeline's axis convention (flip z, swap x/y) ──────────────────

def test_the_axis_transform_inverse_is_an_involution_on_positions():
    pos = [12.0, -30.0, 45.0]
    once_pos, _ = inverse_pipeline_axis_transform(pos, [0.0, 0.0, 0.0])
    assert once_pos == [-30.0, 12.0, -45.0]
    twice_pos, _ = inverse_pipeline_axis_transform(once_pos, [0.0, 0.0, 0.0])
    assert twice_pos == pos


def test_orientation_convention_round_trips():
    ori = [15.0, -25.0, 40.0]
    external = simnibs_orientation_to_external_controller(ori)
    back = pipeline_orientation_to_simnibs(external)
    assert _rot_close(back, ori)
