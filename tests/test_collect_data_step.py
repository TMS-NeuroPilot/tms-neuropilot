"""collect_data_step: the E-field row a pulse actually contributes.

This is the recording end of the in-flight mode switch: whichever source is
active at stimulation time is stored *for that pulse*, next to its placement
index and MEPs, so a later switch cannot shift the matrix against the MEP
history.
"""

import asyncio
import time
from types import SimpleNamespace

import numpy as np
import pytest

from neuropilot.controller.pipeline_controller import PipelineController

collect_data_step = PipelineController.collect_data_step


class FakeEMG:
    def __init__(self):
        self.calls = []

    def get_latest_emg_df(self, idx=None, e_field_for_mep=None):
        self.calls.append(e_field_for_mep)
        return object()          # opaque: compute_meps is stubbed


class FakeOnlineManager:
    def __init__(self, e_matrix=None, computed=None):
        self.online_fem = True
        self.e_matrix = e_matrix
        self.computed = computed
        self.calls = []

    @property
    def is_online(self):
        return self.online_fem is True

    def compute_e_field(self, marker, amplitude):
        self.calls.append((marker, amplitude))
        if self.computed is not None:
            if self.e_matrix is None:
                self.e_matrix = np.asarray(self.computed).reshape(1, -1)
            else:
                self.e_matrix = np.vstack([self.e_matrix, self.computed])
        return self.computed


def make_controller(online=False, e_matrix=None, computed=None, amplitude=70):
    targets = {
        "idx": [], "idx_pulse": [], "time": [],
        "x_realized": [], "y_realized": [], "z_realized": [],
        "rota_realized": [], "rotb_realized": [], "rotc_realized": [],
        "x_target": [], "y_target": [], "z_target": [],
        "rota_target": [], "rotb_target": [], "rotc_target": [],
        "pressure": [], "intensity": [], "e_field_mode": [],
    }
    mgr = FakeOnlineManager(computed=computed)
    mgr.online_fem = online
    ctrl = SimpleNamespace(
        target_created=True,
        current_step_start_time=0.0,
        target_at_stim=[[0, 0, 0], [0, 0, 0]],
        realized_target={"markers": [[1.0, 2.0, 3.0], [0.0, 0.0, 0.0]]},
        current_target_order_idx=0,
        current_target_index=1,
        time_at_stim=time.time(),
        pressure_at_stim=1.0,
        cobotOnTarget=1.0,
        stimulator_amplitude_at_stim=amplitude,
        realized_targets=targets,
        mep_history={},
        emg_preac_amp_history={},
        emg_preac_var_history={},
        used_coil_placements_idx=[],
        pulse_e_fields=[],
        pulse_modes=[],
        excluded_pulse_indices=set(),
        e_matrix=e_matrix,
        online_fem_mgr=mgr,
        emg_computer=FakeEMG(),
        results_fn=None,
        control_panel=None,
        datetime_str="20260101_000000",
        steps=[],
    )
    ctrl.compute_meps = lambda df: ({"ADC 0": 0.5}, {"ADC 0": 1.0}, {"ADC 0": 0.1})
    ctrl.push_mapping_results = lambda: None
    ctrl.switch_step = lambda step: ctrl.steps.append(step)
    return ctrl


def run_step(ctrl):
    asyncio.run(collect_data_step(ctrl, target=None))


def test_precomputed_pulse_records_the_scaled_row():
    matrix = np.array([[1.0, 1.0], [2.0, 3.0]])
    ctrl = make_controller(online=False, e_matrix=matrix, amplitude=70)
    run_step(ctrl)

    assert len(ctrl.pulse_e_fields) == 1
    np.testing.assert_allclose(ctrl.pulse_e_fields[0], matrix[1] * 70 * 1.4)
    assert ctrl.pulse_modes == ["precomputed"]
    # The virtual EMG falls back to the precomputed matrix itself.
    assert ctrl.emg_computer.calls == [None]


def test_online_pulse_records_the_solver_row():
    field = np.array([5.0, 6.0, 7.0])
    ctrl = make_controller(online=True, computed=field)
    run_step(ctrl)

    np.testing.assert_allclose(ctrl.pulse_e_fields[0], field)
    assert ctrl.pulse_modes == ["online"]
    # ... and the same row drives the simulated MEP.
    np.testing.assert_allclose(ctrl.emg_computer.calls[0], field)


def test_online_pulse_without_a_field_is_marked_missing():
    ctrl = make_controller(online=True, computed=None)     # solver produced nothing
    run_step(ctrl)

    assert ctrl.pulse_e_fields == [None]
    assert ctrl.pulse_modes == ["online"]
    assert ctrl.emg_computer.calls == [None]


def test_precomputed_pulse_without_a_matrix_is_marked_missing():
    ctrl = make_controller(online=False, e_matrix=None)
    run_step(ctrl)
    assert ctrl.pulse_e_fields == [None]
    assert ctrl.pulse_modes == ["precomputed"]


def test_rows_stay_aligned_with_placements_and_meps():
    matrix = np.ones((3, 2))
    ctrl = make_controller(online=False, e_matrix=matrix, amplitude=50)
    for target in (0, 1, 2):
        ctrl.current_target_index = target
        run_step(ctrl)
    assert ctrl.used_coil_placements_idx == [0, 1, 2]
    assert len(ctrl.pulse_e_fields) == 3
    assert len(ctrl.mep_history["ADC 0"]) == 3
    assert ctrl.pulse_modes == ["precomputed"] * 3


def test_switching_modes_between_pulses_keeps_each_source():
    ctrl = make_controller(online=False, e_matrix=np.full((2, 2), 2.0), amplitude=10)
    run_step(ctrl)                                   # precomputed

    ctrl.online_fem_mgr.online_fem = True            # switch mid-run
    ctrl.online_fem_mgr.computed = np.array([9.0, 9.0])
    run_step(ctrl)                                   # online

    ctrl.online_fem_mgr.online_fem = False           # and back
    run_step(ctrl)                                   # precomputed

    assert ctrl.pulse_modes == ["precomputed", "online", "precomputed"]
    expected = np.array([2.0, 2.0]) * 10 * 1.4
    np.testing.assert_allclose(ctrl.pulse_e_fields[0], expected)
    np.testing.assert_allclose(ctrl.pulse_e_fields[1], [9.0, 9.0])
    np.testing.assert_allclose(ctrl.pulse_e_fields[2], expected)


def test_recorded_rows_are_copies():
    field = np.array([1.0, 2.0])
    ctrl = make_controller(online=True, computed=field)
    run_step(ctrl)
    field[:] = -1.0
    np.testing.assert_allclose(ctrl.pulse_e_fields[0], [1.0, 2.0])


def test_pulse_moves_on_to_the_analysis():
    from neuropilot.controller.pipeline_controller import Step
    ctrl = make_controller(online=False, e_matrix=np.ones((2, 2)))
    run_step(ctrl)
    assert ctrl.steps == [Step.ANALYSE]


def test_realized_geometry_and_mep_are_recorded():
    ctrl = make_controller(online=False, e_matrix=np.ones((2, 2)))
    run_step(ctrl)
    np.testing.assert_allclose(
        [ctrl.realized_targets["x_realized"][0],
         ctrl.realized_targets["y_realized"][0],
         ctrl.realized_targets["z_realized"][0]], [1.0, 2.0, 3.0])
    assert ctrl.realized_targets["intensity"] == [70]
    assert ctrl.realized_targets["e_field_mode"] == ["precomputed"]
    assert ctrl.mep_history == {"ADC 0": [0.5]}
