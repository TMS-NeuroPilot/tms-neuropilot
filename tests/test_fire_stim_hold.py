"""A pulse must never fire without the E-field it is supposed to use.

When the operator switches to the online solver mid-run, the solver may still
be loading.  ``fire_stim_step`` holds the pulse (the coil stays on target)
until the solver is ready, and releases it as soon as it is -- or as soon as
the operator switches back to the precomputed matrix.
"""

import time
from types import SimpleNamespace

from neuropilot.controller.pipeline_controller import PipelineController

fire_stim_step = PipelineController.fire_stim_step


class FakeStimulator:
    def __init__(self):
        self.armed = 0
        self.amplitudes = []

    def arm(self):
        self.armed += 1

    def set_amplitude(self, value):
        self.amplitudes.append(value)


class FakeLog:
    def __init__(self):
        self.lines = []

    def appendPlainText(self, text):
        self.lines.append(text)


class FakeManager:
    def __init__(self, online, ready):
        self.online_fem = online
        self.ready = ready

    @property
    def is_online(self):
        return self.online_fem is True

    @property
    def is_ready(self):
        return self.ready


def make_controller(online=True, ready=False, mode=None):
    ctrl = SimpleNamespace(
        online_fem_mgr=FakeManager(online, ready),
        efield_mode=(mode if mode is not None
                     else ("online" if online else "precomputed")),
        _online_hold_logged=False,
        _amplitude_hold_logged=False,
        control_panel=SimpleNamespace(finishedsteps=FakeLog()),
        stim_armed=False,
        stimulator=FakeStimulator(),
        stimulator_amplitude=55,
        stimulator_amplitude_at_stim=-1,
        current_step_start_time=time.time(),
    )
    ctrl._log_step = lambda text: ctrl.control_panel.finishedsteps.appendPlainText(text)
    # fire_stim_step is exercised on a bare namespace; bind the mode helper.
    ctrl._active_efield_manager = (
        lambda: PipelineController._active_efield_manager(ctrl))
    return ctrl


def test_pulse_is_held_while_the_solver_starts():
    ctrl = make_controller(online=True, ready=False)
    fire_stim_step(ctrl, target=None)
    assert ctrl.stimulator.armed == 0
    assert ctrl._online_hold_logged is True
    assert any("Holding stimulation" in line for line in ctrl.control_panel.finishedsteps.lines)


def test_hold_message_is_written_once():
    ctrl = make_controller(online=True, ready=False)
    for _ in range(5):
        fire_stim_step(ctrl, target=None)
    assert len(ctrl.control_panel.finishedsteps.lines) == 1


def test_pulse_resumes_when_the_solver_becomes_ready():
    ctrl = make_controller(online=True, ready=False)
    fire_stim_step(ctrl, target=None)
    ctrl.online_fem_mgr.ready = True
    fire_stim_step(ctrl, target=None)
    assert ctrl.stimulator.armed == 1
    assert ctrl._online_hold_logged is False
    assert ctrl.stimulator_amplitude_at_stim == 55


def test_switching_back_to_precomputed_releases_the_pulse():
    ctrl = make_controller(online=True, ready=False)
    fire_stim_step(ctrl, target=None)
    ctrl.online_fem_mgr.online_fem = False      # operator picked precomputed
    ctrl.efield_mode = "precomputed"
    fire_stim_step(ctrl, target=None)
    assert ctrl.stimulator.armed == 1


def test_pulse_is_held_while_the_interpolated_library_loads():
    ctrl = make_controller(online=False, mode="surrogate")
    ctrl.surrogate_mgr = FakeManager(online=False, ready=False)
    fire_stim_step(ctrl, target=None)
    assert ctrl.stimulator.armed == 0
    lines = ctrl.control_panel.finishedsteps.lines
    assert any("interpolated E-field library" in line for line in lines)


def test_pulse_resumes_when_the_interpolated_library_is_ready():
    ctrl = make_controller(online=False, mode="surrogate")
    ctrl.surrogate_mgr = FakeManager(online=False, ready=False)
    fire_stim_step(ctrl, target=None)
    ctrl.surrogate_mgr.ready = True
    fire_stim_step(ctrl, target=None)
    assert ctrl.stimulator.armed == 1
    assert ctrl._online_hold_logged is False


def test_precomputed_mode_never_waits():
    ctrl = make_controller(online=False, ready=False)
    fire_stim_step(ctrl, target=None)
    assert ctrl.stimulator.armed == 1
    assert ctrl.control_panel.finishedsteps.lines == []


def test_pulse_records_the_amplitude_at_fire_time():
    """The slider may change between pulses; each pulse keeps its own MSO."""
    ctrl = make_controller(online=False)
    ctrl.stimulator_amplitude = 70
    fire_stim_step(ctrl, target=None)
    assert ctrl.stimulator_amplitude_at_stim == 70

    ctrl.stimulator_amplitude = 30
    fire_stim_step(ctrl, target=None)
    assert ctrl.stimulator_amplitude_at_stim == 30


def test_changing_the_slider_after_a_pulse_does_not_change_its_intensity():
    ctrl = make_controller(online=False)
    ctrl.stimulator_amplitude = 70
    fire_stim_step(ctrl, target=None)          # this pulse is 70 %

    ctrl.stimulator_amplitude = 30             # operator moves the slider
    assert ctrl.stimulator_amplitude_at_stim == 70

    fire_stim_step(ctrl, target=None)          # the next pulse is 30 %
    assert ctrl.stimulator_amplitude_at_stim == 30


def test_pulse_is_held_without_a_stimulator_amplitude():
    ctrl = make_controller(online=False)
    ctrl.stimulator_amplitude = None
    fire_stim_step(ctrl, target=None)
    assert ctrl.stimulator.armed == 0
    assert ctrl._amplitude_hold_logged is True


def test_amplitude_hold_is_reported_once_and_released():
    ctrl = make_controller(online=False)
    ctrl.stimulator_amplitude = None
    for _ in range(3):
        fire_stim_step(ctrl, target=None)
    lines = [l for l in ctrl.control_panel.finishedsteps.lines if "amplitude" in l]
    assert len(lines) == 1

    ctrl.stimulator_amplitude = 55
    fire_stim_step(ctrl, target=None)
    assert ctrl.stimulator.armed == 1
    assert ctrl._amplitude_hold_logged is False
