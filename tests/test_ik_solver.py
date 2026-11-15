"""IK results must reach the requested pose and repeat between scans."""

import pytest

from neuropilot.sim_robot import config as sim_config
from neuropilot.sim_robot.ik_solver import IKPySolver
from neuropilot.sim_robot.robots import get as get_robot

TARGET = [100.0, -300.0, 800.0]
ORIENTATION = [0.0, 0.0, 0.0]


@pytest.fixture(scope="module")
def solver():
    spec = get_robot(sim_config.ROBOT)
    return IKPySolver(
        spec.urdf,
        active_links_mask=list(spec.ik_active_links),
        base_elements=list(spec.ik_base_elements),
        tip=spec.ik_tip,
    )


def _fake_solution(solver):
    return [0.0] * len(solver.chain.links)


def test_straight_arm_is_the_arm_up_branch(solver):
    zero = [0.0] * len(solver.chain.links)
    assert solver.branch_of(zero) == ("right", "up", "normal")


def test_solve_rejects_a_local_minimum_that_does_not_reach_the_pose(
        solver, monkeypatch):
    monkeypatch.setattr(
        solver.chain, "inverse_kinematics_frame",
        lambda **kwargs: _fake_solution(solver))
    monkeypatch.setattr(
        solver, "forward", lambda joints: ([999.0, 0.0, 0.0], [0.0, 0.0, 0.0]))

    ok, solution = solver.solve(TARGET, ORIENTATION)

    assert ok is False
    assert solution is None


def test_solve_with_config_rejects_an_unreached_pose(solver, monkeypatch):
    monkeypatch.setattr(
        solver, "solve", lambda *args, **kwargs: (True, _fake_solution(solver)))
    monkeypatch.setattr(
        solver.chain, "inverse_kinematics_frame",
        lambda **kwargs: _fake_solution(solver))
    monkeypatch.setattr(
        solver, "forward", lambda joints: ([999.0, 0.0, 0.0], [0.0, 0.0, 0.0]))

    ok, solution = solver.solve_with_config(TARGET, ORIENTATION, max_retries=2)

    assert ok is False
    assert solution is None


def test_solve_with_config_retries_are_deterministic_per_seed(
        solver, monkeypatch):
    calls = []

    def fake_ik(target, initial_position, orientation_mode):
        calls.append(list(initial_position))
        return _fake_solution(solver)

    monkeypatch.setattr(solver, "solve", lambda *args, **kwargs: (False, None))
    monkeypatch.setattr(solver, "forward", lambda joints: (TARGET, ORIENTATION))
    monkeypatch.setattr(solver, "_solution_matches",
                        lambda *args, **kwargs: False)
    monkeypatch.setattr(solver.chain, "inverse_kinematics_frame", fake_ik)

    assert solver.solve_with_config(
        TARGET, ORIENTATION, max_retries=3, seed=123) == (False, None)
    first = list(calls)
    calls.clear()
    assert solver.solve_with_config(
        TARGET, ORIENTATION, max_retries=3, seed=123) == (False, None)
    second = list(calls)
    calls.clear()
    assert solver.solve_with_config(
        TARGET, ORIENTATION, max_retries=3, seed=456) == (False, None)
    third = list(calls)

    assert first == second
    assert first != third
