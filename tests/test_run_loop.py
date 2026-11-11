"""The experiment loop: health gating, Finish, aborts and timing.

Drives ``run_algorithm`` for real (simulated systems, fake relay, fake panel)
with the steps stubbed where the hardware would be involved.
"""

import asyncio
import time
from types import SimpleNamespace

import pytest

from neuropilot.controller.pipeline_controller import PipelineController, Step
from neuropilot.controller.systems.system import SystemStatus


class FakeLog:
    def __init__(self):
        self.lines = []

    def appendPlainText(self, text):
        self.lines.append(text)

    def ensureCursorVisible(self):
        pass


class FakePanel:
    """The bits of MainWindow the algorithm writes to."""

    def __init__(self):
        self.log = FakeLog()
        self.lines = self.log.lines
        self.finishedsteps = self.log
        self.totaltargets3 = SimpleNamespace(setText=lambda text: None)
        self.currenttarget = SimpleNamespace(setText=lambda text: None)
        self.spinBox2 = SimpleNamespace(value=lambda: 40)
        self.spinBox3 = SimpleNamespace(value=lambda: 10)
        self.updates = []

    def on_new_emg_result(self, **kwargs):
        pass

    def update_mapping_results(self, bundle):
        self.updates.append(bundle)


class FakeSystem:
    NAME = "EMG"

    def __init__(self, status=SystemStatus.OK):
        self.status = status

    def is_error_state(self):
        return self.status != SystemStatus.OK

    async def check_system(self):
        pass


def run(coro, timeout=8.0):
    async def wrapper():
        return await asyncio.wait_for(coro, timeout=timeout)
    return asyncio.run(wrapper())


@pytest.fixture()
def loop_controller(controller, placements_hdf5, tmp_path):
    """Controller with two targets, a fake panel and one healthy system."""
    ctrl = controller
    ctrl.targets_file = str(placements_hdf5(2))
    ctrl.control_panel = FakePanel()
    ctrl.systems = [FakeSystem()]
    ctrl.results_fn = str(tmp_path / "results.csv")
    # The algorithm waits for "Start" before the first target; the GUI's Start
    # button clears this.
    ctrl.is_paused = False
    return ctrl


def test_finish_ends_the_run_even_when_a_system_is_down(loop_controller):
    ctrl = loop_controller
    ctrl.systems = [FakeSystem(SystemStatus.ERROR)]

    async def scenario():
        task = asyncio.create_task(ctrl.run_algorithm())
        await asyncio.sleep(0.3)             # the loop is held at SEND_MARKER
        ctrl.finish_experiment()
        await task
    run(scenario())

    assert ctrl.is_finished is True
    assert ctrl.current_step is Step.COMPLETE
    assert any("Held at" in line for line in ctrl.control_panel.lines)


def test_the_hold_message_is_written_once(loop_controller):
    ctrl = loop_controller
    ctrl.systems = [FakeSystem(SystemStatus.ERROR)]

    async def scenario():
        task = asyncio.create_task(ctrl.run_algorithm())
        await asyncio.sleep(0.5)             # many loop iterations
        ctrl.finish_experiment()
        await task
    run(scenario())

    held = [line for line in ctrl.control_panel.lines if "Held at" in line]
    assert len(held) == 1


def test_a_failing_step_aborts_and_still_writes_the_results(loop_controller,
                                                           tmp_path):
    ctrl = loop_controller
    for key in ctrl.realized_targets:               # one complete pulse row
        ctrl.realized_targets[key].append(0)

    def boom(target):
        raise RuntimeError("marker send failed")

    ctrl.send_marker_step = boom
    run(ctrl.run_algorithm())

    assert ctrl.is_finished is True
    assert ctrl.aborted_by and "marker send failed" in ctrl.aborted_by
    assert any("[ERROR]" in line for line in ctrl.control_panel.lines)
    assert (tmp_path / "results.csv").is_file()      # finalisation still ran


def test_pause_holds_the_pulse_inside_a_target(loop_controller):
    ctrl = loop_controller
    fired = []

    def tracking(target):                 # start_tracking_step is synchronous
        ctrl.switch_step(Step.WAIT_FOR_TARGET_REACHED)

    async def reached(target):
        ctrl.switch_step(Step.FIRE_STIM)

    ctrl.start_tracking_step = tracking
    ctrl.wait_for_target_reached_step = reached
    ctrl.fire_stim_step = lambda target: fired.append(target)
    ctrl.is_paused = True

    async def scenario():
        task = asyncio.create_task(ctrl.run_algorithm())
        await asyncio.sleep(0.3)
        assert fired == []                    # held at FIRE_STIM
        ctrl.is_paused = False
        await asyncio.sleep(0.2)
        ctrl.finish_experiment()
        await task
    run(scenario())

    assert fired, "the pulse must fire once the pause is released"


def test_previous_is_ignored_while_a_pulse_is_in_flight(loop_controller):
    ctrl = loop_controller
    ctrl.current_target_order_idx = 1
    ctrl.current_step = Step.COLLECT_DATA
    ctrl.switch_step("previous")
    assert ctrl.current_target_order_idx == 1
    assert ctrl.current_step is Step.COLLECT_DATA


def test_previous_works_between_targets(loop_controller):
    ctrl = loop_controller
    ctrl.current_target_order_idx = 1
    ctrl.current_step = Step.COMPLETE

    async def scenario():
        ctrl.switch_step("previous")
        await asyncio.sleep(0.05)            # the stop messages are tasks
    run(scenario())

    assert ctrl.current_target_order_idx == 0
    assert ctrl._go_back is True


def test_finish_sends_stop_and_releases_the_robot(loop_controller):
    ctrl = loop_controller
    ctrl.is_finished = False

    sent = []

    async def send(topic, data=None):
        sent.append((topic, data))
        return True

    ctrl.remote.send_message = send

    async def scenario():
        ctrl.finish_experiment()
        await asyncio.sleep(0.05)             # let the created tasks run
    run(scenario())

    topics = [topic for topic, _ in sent]
    assert "STOP" in topics
    press = [data for topic, data in sent if topic == "Press robot button"]
    assert press and press[0] == {"pressed": False}
    assert ctrl.current_step is Step.SKIP


def test_finish_is_idempotent(loop_controller):
    ctrl = loop_controller
    sent = []

    async def send(topic, data=None):
        sent.append(topic)
        return True

    ctrl.remote.send_message = send

    async def scenario():
        ctrl.finish_experiment()
        await asyncio.sleep(0.05)
        first = len(sent)
        ctrl.finish_experiment()
        await asyncio.sleep(0.05)
        assert len(sent) == first
    run(scenario())


def test_manual_mode_does_not_send_robot_messages(loop_controller):
    ctrl = loop_controller
    ctrl.manual = True
    sent = []

    async def send(topic, data=None):
        sent.append(topic)
        return True

    ctrl.remote.send_message = send

    async def scenario():
        ctrl.finish_experiment()
        await asyncio.sleep(0.05)
    run(scenario())

    assert sent == []


# ── ISI on the monotonic clock ─────────────────────────────────────────

def test_isi_is_measured_on_the_monotonic_clock(controller):
    ctrl = controller
    ctrl.manual = True
    ctrl.target_reached = True
    ctrl.minium_isi = 4

    async def scenario():
        ctrl._last_pulse_mono = ctrl.mono_now() - 1     # 1 s ago
        ctrl.switch_step(Step.WAIT_FOR_TARGET_REACHED)
        await ctrl.wait_for_target_reached_step(target=None)
        assert ctrl.current_step is Step.WAIT_FOR_TARGET_REACHED

        ctrl._last_pulse_mono = ctrl.mono_now() - 5     # 5 s ago
        await ctrl.wait_for_target_reached_step(target=None)
        assert ctrl.current_step is Step.FIRE_STIM
    run(scenario())


def test_a_forward_clock_jump_cannot_shorten_the_isi(controller):
    ctrl = controller
    ctrl.manual = True
    ctrl.target_reached = True
    ctrl.minium_isi = 4
    # A wall clock that jumped forward would have made the old gate pass; the
    # monotonic clock still says the last pulse was one second ago.
    ctrl.time_at_stim = time.time() + 3600

    async def scenario():
        ctrl._last_pulse_mono = ctrl.mono_now() - 1
        ctrl.switch_step(Step.WAIT_FOR_TARGET_REACHED)
        await ctrl.wait_for_target_reached_step(target=None)
        assert ctrl.current_step is Step.WAIT_FOR_TARGET_REACHED
    run(scenario())


def test_first_pulse_has_no_isi_wait(controller):
    ctrl = controller
    ctrl.manual = True
    ctrl.target_reached = True
    ctrl._last_pulse_mono = None

    async def scenario():
        ctrl.switch_step(Step.WAIT_FOR_TARGET_REACHED)
        await ctrl.wait_for_target_reached_step(target=None)
        assert ctrl.current_step is Step.FIRE_STIM
    run(scenario())
