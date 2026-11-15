"""The sim robot's motion planner: the contract the pipeline gates on.

Drives the real MotionPlanner state machine on a headless MuJoCo world
(shipped robot and head): the IK-failure flags the placement scan reports,
the collision halt and its release on a new target, a target change
mid-motion, and the tracking state the pipeline collects data on.
"""

import os
import random

import pytest

from neuropilot.sim_robot import config as sim_config
from neuropilot.sim_robot.collision_checker import CollisionChecker
from neuropilot.sim_robot.contact_model import ContactModel
from neuropilot.sim_robot.ik_solver import IKPySolver
from neuropilot.sim_robot.motion_planner import MotionPlanner, MotionState
from neuropilot.sim_robot.mujoco_world import MuJoCoWorld
from neuropilot.sim_robot.robots import get as get_robot
from neuropilot.sim_robot.state import RobotState
from neuropilot.sim_robot.utils.transforms import m_to_mm


@pytest.fixture()
def planner(monkeypatch):
    """A real MotionPlanner on a headless world (shipped robot + head)."""
    spec = get_robot(sim_config.ROBOT)
    world = MuJoCoWorld(
        use_gui=False,
        end_effector_site_name=spec.ee_site,
        # A scene file per process: the parallel workers compose their own
        # world, and a shared file name would let one worker read another's
        # head or base pose (the file is rewritten at every connect()).
        scene_name=f"_collision_scene_{os.getpid()}.xml",
        head_pose=(list(sim_config.HEAD_POSITION),
                   list(sim_config.HEAD_ORIENTATION)),
        base_pose=(list(sim_config.ROBOT_BASE_POSITION),
                   list(sim_config.ROBOT_BASE_ORIENTATION)),
    )
    world.connect()
    ik = IKPySolver(spec.urdf,
                    active_links_mask=list(spec.ik_active_links),
                    base_elements=list(spec.ik_base_elements),
                    tip=spec.ik_tip)
    checker = CollisionChecker(world)
    contact = ContactModel(world, checker)
    state = RobotState()
    mp = MotionPlanner(state, world, ik, checker, contact)
    mp.sync_state()
    # The press step waits for contact force feedback the headless world
    # cannot produce deterministically; the press is the analogue of the
    # real robot's pressure PID and not what these tests gate on.
    monkeypatch.setattr(sim_config, "PRESS_ENABLED", False)
    try:
        yield mp, state, world, ik
    finally:
        world.disconnect()


def run_until_done(mp, state, limit=400):
    """Tick the planner until the motion completes (or the limit)."""
    for _ in range(limit):
        mp.step()
        if state.motion_done:
            return True
    return False


def _target_near(world, dx_mm=0.0, dy_mm=0.0):
    """A small-displacement target: the current TCP pose shifted a few mm."""
    pos_m, ori_deg = world.get_end_effector_pose()
    start_mm = m_to_mm(pos_m)
    return [start_mm[0] + dx_mm, start_mm[1] + dy_mm, start_mm[2]], list(ori_deg)


# ── path construction ──────────────────────────────────────────────────

def test_self_collision_uses_the_shared_mesh_overlap_tolerance():
    class FakeWorld:
        def __init__(self):
            self.contacts = []

        def get_self_collision_contacts(self):
            return self.contacts

    world = FakeWorld()
    checker = CollisionChecker(world)
    world.contacts = [{"dist": -0.001}]
    assert checker.check_self_collision() is False
    world.contacts = [{"dist": -0.010}]
    assert checker.check_self_collision() is True


def test_large_target_moves_retract_along_the_tool_normal(planner, monkeypatch):
    mp, _state, _world, ik = planner
    solution = [0.0] * len(ik.chain.links)
    calls = []

    def fake_solve(position, orientation, **kwargs):
        calls.append((list(position), list(orientation)))
        return True, solution

    monkeypatch.setattr(ik, "solve_with_config", fake_solve)
    retract, traverse, approach = mp._build_retract_path(
        [0.0] * 6, [0.0, 0.0, 0.0], [90.0, 0.0, 0.0],
        [0.1] * 6, [100.0, 0.0, 0.0], [0.0, 0.0, 0.0], None)

    assert len(retract) == sim_config.PATH_INTERPOLATION_STEPS
    assert len(traverse) == sim_config.PATH_INTERPOLATION_STEPS
    assert len(approach) == sim_config.PATH_INTERPOLATION_STEPS
    assert calls[0][0] == pytest.approx([0.0, 20.0, 0.0])
    assert calls[1][0] == pytest.approx([100.0, 0.0, -20.0])


def test_first_target_uses_safe_height(planner, monkeypatch):
    mp, _state, _world, ik = planner
    solution = [0.0] * len(ik.chain.links)
    calls = []

    def fake_solve(position, orientation, **kwargs):
        calls.append(list(position))
        return True, solution

    monkeypatch.setattr(ik, "solve_with_config", fake_solve)
    mp._build_safe_height_path(
        [0.0] * 6, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0],
        [0.1] * 6, [100.0, 0.0, 0.0], [0.0, 0.0, 0.0], None)
    assert calls[0][2] == pytest.approx(350.0)
    assert calls[1][2] == pytest.approx(350.0)


def test_interpolation_is_linear_and_excludes_the_start():
    n = sim_config.PATH_INTERPOLATION_STEPS
    path = MotionPlanner._interpolate_joints([0.0, 0.0], [1.0, 2.0])
    assert len(path) == n
    assert path[0] == pytest.approx([1 / n, 2 / n])
    assert path[-1] == [1.0, 2.0]
    # every pose sits on the straight line between start and end
    assert path[0][1] / path[0][0] == pytest.approx(2.0)


# ── the states the pipeline reads ──────────────────────────────────────

def test_no_target_keeps_the_planner_idle(planner):
    mp, state, _, _ = planner
    mp.step()
    assert mp._motion_state == MotionState.IDLE
    assert not state.motion_done
    assert not state.tracking_valid


def test_an_ik_failure_reports_the_flags_without_a_path(planner, monkeypatch):
    # ikpy's numerical IK returns a best-effort solution for almost any
    # target, so the failure path is driven through the solver itself.
    mp, state, _, _ = planner
    monkeypatch.setattr(mp.ik_solver, "solve_with_config",
                        lambda *a, **k: (False, None))
    state.set_target([100.0, -300.0, 800.0], [0.0, 0.0, 0.0], "far")
    mp.step()
    assert not state.ik_success
    assert not state.motion_done
    assert not state.tracking_valid
    # no path was built: the planner stays idle and retries on later ticks
    assert mp._motion_state == MotionState.IDLE


def test_small_displacement_reaches_the_target_and_signals_tracking(planner):
    mp, state, world, _ = planner
    target_mm, ori_deg = _target_near(world, dx_mm=5.0)
    state.set_target(target_mm, ori_deg, "near")
    assert run_until_done(mp, state)
    assert state.ik_success
    assert state.tracking_valid
    err = sum((a - b) ** 2
              for a, b in zip(state.current_position, target_mm)) ** 0.5
    assert err < 5.0


def test_a_target_change_mid_motion_recomputes_and_reaches_the_new_target(planner):
    mp, state, world, ik = planner
    first_mm, ori_deg = _target_near(world, dx_mm=5.0)
    state.set_target(first_mm, ori_deg, "first")
    for _ in range(10):                    # into the path, motion not done
        mp.step()
        if state.motion_done:
            break
    # A reachable second target, known by construction: perturb the stored
    # solution's wrist joint slightly and take its forward kinematics.  The
    # pose is reachable by definition, so the test does not depend on the
    # numerical solver finding a valid orientation for an arbitrary shift.
    solution = list(state.target_joint_positions)
    solution[mp.ik_solver.active_indices[-1]] += 0.1
    padded = [0.0] * len(ik.chain.links)
    for idx, value in zip(ik.active_indices, solution):
        padded[idx] = value
    second_mm, second_ori = ik.forward(padded)
    state.set_target(second_mm, second_ori, "second")
    assert run_until_done(mp, state)
    assert state.ik_success
    err = sum((a - b) ** 2
              for a, b in zip(state.current_position, second_mm)) ** 0.5
    assert err < 5.0


def test_a_blocked_path_halts_in_collision_until_the_target_changes(planner,
                                                                    monkeypatch):
    mp, state, world, _ = planner
    target_mm, ori_deg = _target_near(world, dx_mm=5.0)
    state.set_target(target_mm, ori_deg, "blocked")
    # Every pose collides: the planner must halt instead of moving.
    monkeypatch.setattr(mp.collision_checker, "check", lambda: True)
    monkeypatch.setattr(mp.collision_checker, "check_self_collision",
                        lambda: False)
    mp.step()
    assert state.collision
    assert not state.motion_done
    assert not state.tracking_valid
    assert mp._motion_state == MotionState.COLLISION_HALT

    # A new target releases the halt; with the checker quiet the path passes.
    monkeypatch.setattr(mp.collision_checker, "check", lambda: False)
    clear_mm = [target_mm[0] + 10.0, target_mm[1], target_mm[2]]
    state.set_target(clear_mm, ori_deg, "clear")
    mp.step()
    assert not state.collision
    assert mp._motion_state == MotionState.PRE_VERIFY_DIRECT
    assert run_until_done(mp, state)
