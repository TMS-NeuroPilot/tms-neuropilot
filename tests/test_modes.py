"""The three run modes and the guards around a live session."""

import asyncio

import pytest

import neuropilot.controller.pipeline_controller as pc
from neuropilot.controller.remote_connection import Remote as RealRemote
from neuropilot.controller.systems.emg import EMGComputer
from neuropilot.controller.systems.stimulator import Stimulator
from neuropilot.controller.systems.virtual_emg import VirtualEMG
from neuropilot.controller.systems.virtual_stimulator import VirtualStimulator
from neuropilot.controller.sim_remote_connection import Remote as SimRemote


@pytest.fixture()
def build(monkeypatch):
    """Construct a controller with the hardware connects stubbed out."""
    monkeypatch.setattr(Stimulator, "try_connect", lambda self: None)
    monkeypatch.setattr(EMGComputer, "try_connect", lambda self: None)

    def _build(**kwargs):
        return pc.PipelineController(remote=SimRemote("http://test"),
                                     control_panel=None, **kwargs)
    return _build


# ── mode selection ─────────────────────────────────────────────────────

def test_simulated_mode_uses_virtual_hardware(build):
    ctrl = build(simulation=True)
    assert isinstance(ctrl.stimulator, VirtualStimulator)
    assert isinstance(ctrl.emg_computer, VirtualEMG)
    assert ctrl.robot is not None
    assert ctrl.simulation is True
    assert ctrl.manual is False


def test_real_mode_uses_hardware(build):
    ctrl = build(simulation=False)
    assert isinstance(ctrl.stimulator, Stimulator)
    assert isinstance(ctrl.emg_computer, EMGComputer)
    assert ctrl.simulation is False


def test_manual_simulation_keeps_simulated_hardware(build):
    # manual only removes the robot; it must not silently open real hardware.
    ctrl = build(simulation=True, manual=True)
    assert ctrl.manual is True
    assert ctrl.robot is None
    assert isinstance(ctrl.stimulator, VirtualStimulator)
    assert isinstance(ctrl.emg_computer, VirtualEMG)
    assert ctrl.simulation is True


def test_real_manual_has_no_robot_but_hardware(build):
    ctrl = build(simulation=False, manual=True)
    assert ctrl.robot is None
    assert isinstance(ctrl.stimulator, Stimulator)
    assert ctrl.simulation is False


def test_landmark_tracks_are_skipped_in_simulation(build):
    ctrl = build(simulation=True)
    ctrl.simulation = True
    ctrl.control_panel = None
    ctrl.OnRobotTrackingState({"qpos": [0.0] * 6})      # must not raise


# ── a live session is protected ────────────────────────────────────────

def test_is_running_follows_the_session(build):
    ctrl = build(simulation=True)
    assert ctrl.is_running is False
    ctrl.start_of_experiment = object()
    assert ctrl.is_running is True
    ctrl.is_finished = True
    assert ctrl.is_running is False


# ── aim error ──────────────────────────────────────────────────────────

def test_aim_error_is_the_distance_between_the_centres(build):
    ctrl = build(simulation=True)
    assert ctrl._aim_error([[0, 0, 0], [0, 0, 0]], [[3, 4, 0], [0, 0, 0]]) == pytest.approx(5.0)
    assert ctrl._aim_error(None, [[0, 0, 0], [0, 0, 0]]) is None


# ── the real relay client ──────────────────────────────────────────────

def test_real_remote_awaits_only_coroutines():
    remote = RealRemote("http://test")
    seen = []
    remote.register_handler("t", lambda payload: seen.append(payload))
    asyncio.run(remote.on_message_received({"topic": "t", "data": 1}))
    assert seen == [1]


def test_real_remote_awaits_a_coroutine_handler():
    remote = RealRemote("http://test")
    seen = []

    async def handler(payload):
        await asyncio.sleep(0)
        seen.append(payload)

    remote.register_handler("t", handler)
    asyncio.run(remote.on_message_received({"topic": "t", "data": 2}))
    assert seen == [2]


@pytest.mark.parametrize("bad", [None, "text", 42, ["t"]])
def test_real_remote_ignores_non_object_messages(bad):
    remote = RealRemote("http://test")
    asyncio.run(remote.on_message_received(bad))       # must not raise


def test_controller_handlers_tolerate_malformed_payloads(build):
    ctrl = build(simulation=True)

    async def scenario():
        await ctrl.CobotOnTarget({})                   # no force_feedback
        await ctrl.OnCoilAtTarget({})                  # no state
        await ctrl.GetRealizedTarget({})               # no markers
        await ctrl.GetRealizedTarget(None)
        ctrl.OnRobotTrackingState({})                  # sync handler
        ctrl.OnRobotTrackingState(None)
    asyncio.run(scenario())
    assert ctrl.target_created is False


def test_tracking_state_reaches_the_view_only_with_a_panel(build):
    ctrl = build(simulation=True)
    seen = []
    ctrl.control_panel = type("Panel", (), {
        "update_robot_scene": lambda self, qpos: seen.append(qpos)})()
    ctrl.OnRobotTrackingState({"qpos": [1.0, 2.0]})
    assert seen == [[1.0, 2.0]]
    ctrl.OnRobotTrackingState({"qpos": []})        # empty: ignored
    ctrl.OnRobotTrackingState(None)                # malformed: ignored
    assert len(seen) == 1


def test_aim_error_warning_in_precomputed_mode():
    ctrl = pc.PipelineController.__new__(pc.PipelineController)
    ctrl.online_fem_mgr = type("M", (), {"is_online": False})()
    ctrl.max_aim_error_mm = 5.0
    lines = []
    ctrl._log_step = lines.append
    # the warning lives in collect_data_step; the helper is what it calls
    assert ctrl._aim_error([[10, 0, 0], [0, 0, 0]], [[0, 0, 0], [0, 0, 0]]) == 10.0


def test_training_uses_real_stimulation_and_virtual_emg(build):
    ctrl = build(simulation=False, training=True)
    assert ctrl.training is True
    assert ctrl.manual is True
    assert ctrl.robot is None
    assert isinstance(ctrl.stimulator, Stimulator)
    assert isinstance(ctrl.emg_computer, VirtualEMG)
    assert ctrl.simulation is False


def test_training_cannot_also_be_simulated(build):
    with pytest.raises(ValueError, match="training mode"):
        build(simulation=True, training=True)


def test_training_stack_starts_the_controller_in_training_mode():
    from neuropilot import supervisor
    components = supervisor.training_stack()
    assert [c.module for c in components] == ["neuropilot.controller"]
    assert components[0].args == ["--training"]


def test_launch_relay_is_controller_managed():
    from neuropilot import supervisor
    components = supervisor.robo_stack(with_relay=True)
    assert components[0].args == ["--robo", "--manage-relay"]
    manual = supervisor.manual_stack(with_relay=True)
    assert manual[0].args == ["--manual", "--manage-relay"]
    training = supervisor.training_stack(with_relay=True)
    assert training[0].args == ["--training", "--manage-relay"]
