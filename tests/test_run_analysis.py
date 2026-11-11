"""run_analysis across an E-field mode switch.

Two things must hold no matter when the operator toggles precomputed/online:

* every retained pulse contributes exactly one E-field row, in pulse order;
* the MEP history is filtered with the *same* indices, so rows and MEPs stay
  paired.

The regression itself is replaced by a recorder, so the test runs in-process.
"""

from concurrent.futures import Future

import numpy as np
import pytest

import neuropilot.controller.pipeline_controller as pc
from neuropilot.controller.systems.emg import EMGComputer
from neuropilot.controller.systems.stimulator import Stimulator

N_ELMS = 3


class FakeSio:
    connected = True


class FakeRemote:
    url = "http://test"
    sio = FakeSio()

    def register_handlers(self, handlers):
        pass

    def register_handler(self, topic, handler):
        pass

    async def send_message(self, *args, **kwargs):
        return True


class InlineExecutor:
    """Stand-in for ProcessPoolExecutor that runs the work immediately."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, arg):
        future = Future()
        try:
            future.set_result(fn(arg))
        except Exception as exc:                      # pragma: no cover
            future.set_exception(exc)
        return future


@pytest.fixture()
def controller(monkeypatch):
    monkeypatch.setattr(Stimulator, "try_connect", lambda self: None)
    monkeypatch.setattr(EMGComputer, "try_connect", lambda self: None)
    monkeypatch.setattr(pc, "ProcessPoolExecutor", InlineExecutor)
    ctrl = pc.PipelineController(remote=FakeRemote(), simulation=True, control_panel=None)
    ctrl.elm_idx_list = np.arange(N_ELMS)
    ctrl.n_elms = N_ELMS
    return ctrl


def record_regression(monkeypatch):
    calls = []

    def fake_regress(args):
        channel, meps, matrix, fit_fun, elm_idx_list, n_elms = args
        calls.append({"channel": channel, "meps": list(meps),
                      "matrix": np.array(matrix), "fit_fun": fit_fun})
        return channel, np.zeros(n_elms)

    monkeypatch.setattr(pc, "_regress_single_channel", fake_regress)
    return calls


def pulse_row(value):
    return np.full(N_ELMS, float(value))


def feed(ctrl, rows, meps=None, placements=None):
    ctrl.used_coil_placements_idx = list(range(len(rows))) if placements is None else list(placements)
    ctrl.pulse_e_fields = list(rows)
    ctrl.pulse_modes = ["online" if r is not None else "precomputed" for r in rows]
    if meps is None:
        meps = list(range(1, len(rows) + 1))
    ctrl.mep_history = {"ADC 0": list(meps)}


def test_mixed_sources_produce_one_row_per_pulse(controller, monkeypatch):
    calls = record_regression(monkeypatch)
    # pulse 0: precomputed, pulse 1: online, pulse 2: back to precomputed
    feed(controller, [pulse_row(1), pulse_row(10), pulse_row(100)],
         meps=[1.0, 2.0, 3.0])
    controller.run_analysis()

    assert len(calls) == 1
    matrix = calls[0]["matrix"]
    assert matrix.shape == (3, N_ELMS)
    np.testing.assert_allclose(matrix[:, 0], [1.0, 10.0, 100.0])
    assert calls[0]["meps"] == [1.0, 2.0, 3.0]


def test_pulse_without_a_field_is_dropped_with_its_mep(controller, monkeypatch):
    calls = record_regression(monkeypatch)
    # pulse 1 happened while the online solver was still warming up
    feed(controller, [pulse_row(1), None, pulse_row(3), pulse_row(4)],
         meps=[10.0, 20.0, 30.0, 40.0])
    controller.run_analysis()

    matrix = calls[0]["matrix"]
    assert matrix.shape == (3, N_ELMS)
    np.testing.assert_allclose(matrix[:, 0], [1.0, 3.0, 4.0])
    assert calls[0]["meps"] == [10.0, 30.0, 40.0]


def test_excluded_pulses_do_not_reach_the_regression(controller, monkeypatch):
    calls = record_regression(monkeypatch)
    feed(controller, [pulse_row(i) for i in range(5)], meps=[1, 2, 3, 4, 5])
    controller.excluded_pulse_indices = {1, 3}
    controller.run_analysis()

    np.testing.assert_allclose(calls[0]["matrix"][:, 0], [0.0, 2.0, 4.0])
    assert calls[0]["meps"] == [1, 3, 5]


def test_fewer_than_three_usable_pulses_skips_the_regression(controller, monkeypatch):
    calls = record_regression(monkeypatch)
    feed(controller, [pulse_row(1), None, pulse_row(3)], meps=[1.0, 2.0, 3.0])
    controller.run_analysis()
    assert calls == []


def test_no_pulse_rows_at_all_skips_the_regression(controller, monkeypatch):
    calls = record_regression(monkeypatch)
    feed(controller, [], meps=[])
    controller.run_analysis()
    assert calls == []


def test_precomputed_only_run_works_without_a_loaded_matrix(controller, monkeypatch):
    # The per-pulse rows already carry the fields; the big precomputed matrix
    # is only the *source* for them and may legitimately be None here.
    calls = record_regression(monkeypatch)
    controller.e_matrix = None
    feed(controller, [pulse_row(i) for i in (7, 8, 9)])
    controller.run_analysis()
    assert len(calls) == 1


def test_scores_reach_the_control_panel(controller, monkeypatch):
    record_regression(monkeypatch)

    class Panel:
        def __init__(self):
            self.updates = []

        def update_mesh_coloring(self, scores):
            self.updates.append(scores)

    controller.control_panel = Panel()
    feed(controller, [pulse_row(i) for i in range(3)])
    controller.run_analysis()
    assert len(controller.control_panel.updates) == 1
    np.testing.assert_allclose(controller.control_panel.updates[0]["ADC 0"], np.zeros(N_ELMS))
    assert "ADC 0" in controller.final_scores


def test_every_channel_gets_the_same_matrix(controller, monkeypatch):
    calls = record_regression(monkeypatch)
    feed(controller, [pulse_row(i) for i in range(3)])
    controller.mep_history = {"ADC 0": [1.0, 2.0, 3.0], "ADC 1": [4.0, 5.0, 6.0]}
    controller.run_analysis()

    assert len(calls) == 2
    assert {c["channel"] for c in calls} == {"ADC 0", "ADC 1"}
    np.testing.assert_allclose(calls[0]["matrix"], calls[1]["matrix"])
