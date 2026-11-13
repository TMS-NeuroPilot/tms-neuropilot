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

from neuropilot.controller.pipeline_controller import PipelineController, Step

collect_data_step = PipelineController.collect_data_step


class FakeEMG:
    """Stands in for the virtual EMG (the sweep content is not used)."""

    data_channel_names = ["ADC 0"]

    def __init__(self):
        self.calls = []

    def get_latest_emg_df(self, idx=None, e_field_for_mep=None, after=None):
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
        efield_mode="online" if online else "precomputed",
        surrogate_mgr=None,
        emg_computer=FakeEMG(),
        results_fn=None,
        control_panel=None,
        datetime_str="20260101_000000",
        steps=[],
        current_step=Step.COLLECT_DATA,
        emg_timeout_s=5.0,
        _emg_files_before=None,
        _fire_mono=0.0,
        _realized_mono=None,
        collect_timeout_s=20.0,
    )
    ctrl.compute_meps = lambda df: ({"ADC 0": 0.5}, {"ADC 0": 1.0}, {"ADC 0": 0.1})
    ctrl.push_mapping_results = lambda: None
    ctrl.switch_step = lambda step: ctrl.steps.append(step)
    ctrl._log_step = lambda text: ctrl.steps.append(text)
    ctrl._pulse_width = None
    ctrl._check_row_width = lambda row: PipelineController._check_row_width(ctrl, row)
    import types
    ctrl._read_emg = types.MethodType(PipelineController._read_emg, ctrl)
    ctrl._aim_error = PipelineController._aim_error
    ctrl.max_aim_error_mm = 5.0
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


def test_each_precomputed_pulse_uses_its_own_amplitude():
    # The operator can move the MSO slider between pulses, and may do so
    # again while the pulse is being collected.  The row must use the value
    # captured at fire time, not the current slider value.
    matrix = np.ones((3, 2))
    ctrl = make_controller(online=False, e_matrix=matrix, amplitude=70)
    ctrl.stimulator_amplitude = 30          # slider moved after this pulse
    run_step(ctrl)

    ctrl.stimulator_amplitude_at_stim = 30  # next pulse fires at 30 %
    run_step(ctrl)

    assert ctrl.realized_targets["intensity"] == [70, 30]
    np.testing.assert_allclose(ctrl.pulse_e_fields[0], 70 * 1.4 * np.ones(2))
    np.testing.assert_allclose(ctrl.pulse_e_fields[1], 30 * 1.4 * np.ones(2))


def test_online_pulse_passes_its_own_amplitude_to_the_solver():
    ctrl = make_controller(online=True, computed=np.ones(2), amplitude=70)
    run_step(ctrl)

    ctrl.stimulator_amplitude_at_stim = 30
    run_step(ctrl)

    assert [amp for _, amp in ctrl.online_fem_mgr.calls] == [70, 30]
    assert ctrl.realized_targets["intensity"] == [70, 30]


def test_surrogate_pulse_passes_its_own_amplitude_to_the_interpolator():
    ctrl = make_controller(online=False, e_matrix=np.ones((3, 2)), amplitude=70)
    calls = []

    def compute_e_field(marker, amplitude):
        calls.append(amplitude)
        return np.full(2, amplitude * 1.4)

    ctrl.efield_mode = "surrogate"
    ctrl.surrogate_mgr = SimpleNamespace(compute_e_field=compute_e_field)
    run_step(ctrl)

    ctrl.stimulator_amplitude_at_stim = 30
    run_step(ctrl)

    assert calls == [70, 30]
    assert ctrl.realized_targets["intensity"] == [70, 30]
    np.testing.assert_allclose(ctrl.pulse_e_fields[0], 70 * 1.4 * np.ones(2))
    np.testing.assert_allclose(ctrl.pulse_e_fields[1], 30 * 1.4 * np.ones(2))
    np.testing.assert_allclose(ctrl.emg_computer.calls[0], 70 * 1.4 * np.ones(2))
    np.testing.assert_allclose(ctrl.emg_computer.calls[1], 30 * 1.4 * np.ones(2))


def test_switching_modes_between_pulses_keeps_each_source():
    ctrl = make_controller(online=False, e_matrix=np.full((2, 2), 2.0), amplitude=10)
    run_step(ctrl)                                   # precomputed

    ctrl.efield_mode = "online"
    ctrl.online_fem_mgr.online_fem = True            # switch mid-run
    ctrl.online_fem_mgr.computed = np.array([9.0, 9.0])
    run_step(ctrl)                                   # online

    ctrl.efield_mode = "precomputed"
    ctrl.online_fem_mgr.online_fem = False           # and back
    run_step(ctrl)                                   # precomputed

    assert ctrl.pulse_modes == ["precomputed", "online", "precomputed"]
    expected = np.array([2.0, 2.0]) * 10 * 1.4
    np.testing.assert_allclose(ctrl.pulse_e_fields[0], expected)
    np.testing.assert_allclose(ctrl.pulse_e_fields[1], [9.0, 9.0])
    np.testing.assert_allclose(ctrl.pulse_e_fields[2], expected)


def test_interpolated_outside_pulse_is_recorded_and_excluded():
    from neuropilot.controller.pipeline_controller import (
        assemble_analysis_matrix,
    )
    ctrl = make_controller(online=False, e_matrix=np.full((2, 2), 2.0))
    ctrl.efield_mode = "surrogate"
    ctrl.surrogate_mgr = SimpleNamespace(
        compute_e_field=lambda marker, amplitude: np.full(2, np.nan))
    run_step(ctrl)
    assert ctrl.pulse_modes == ["surrogate"]
    assert np.all(np.isnan(ctrl.pulse_e_fields[0]))
    assert ctrl.realized_targets["e_field_mode"] == ["surrogate"]
    # The regression drops the NaN row: the pulse is excluded from the map.
    kept, matrix = assemble_analysis_matrix(ctrl.pulse_e_fields, [0])
    assert len(kept) == 0 and matrix is None


def test_interpolated_inside_pulse_feeds_the_virtual_emg():
    ctrl = make_controller(online=False, e_matrix=np.full((2, 2), 2.0))
    ctrl.efield_mode = "surrogate"
    row = np.array([3.0, 4.0])
    ctrl.surrogate_mgr = SimpleNamespace(
        compute_e_field=lambda marker, amplitude: row.copy())
    run_step(ctrl)
    np.testing.assert_allclose(ctrl.pulse_e_fields[0], row)
    # e_field_for_mep reaches _read_emg; with the FakeEMG the pulse still
    # completes and the row is finite.
    assert np.all(np.isfinite(ctrl.pulse_e_fields[0]))


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


def test_results_file_in_a_deleted_folder_does_not_lose_the_pulse(tmp_path):
    # The folder may be removed while the mapping runs; the pulse is already
    # recorded, so a failed CSV write must not abort the step.
    ctrl = make_controller(online=False, e_matrix=np.ones((2, 2)))
    ctrl.results_fn = str(tmp_path / "gone" / "results.csv")
    run_step(ctrl)
    assert ctrl.pulse_e_fields != []
    assert ctrl.mep_history == {"ADC 0": [0.5]}


def test_results_file_is_written_next_to_the_configured_name(tmp_path):
    ctrl = make_controller(online=False, e_matrix=np.ones((2, 2)))
    ctrl.results_fn = str(tmp_path / "results.csv")
    run_step(ctrl)
    written = list(tmp_path.glob("results20260101_000000.csv"))
    assert len(written) == 1
    assert "intensity" in written[0].read_text().splitlines()[0]


def test_stale_realized_target_is_rejected():
    # The message arrived before this pulse fired: it belongs to the previous
    # pulse, so the geometry (and, online, the E-field position) must not be
    # recorded against this one.
    ctrl = make_controller(online=False, e_matrix=np.ones((2, 2)))
    ctrl.target_created = True
    ctrl._fire_mono = 100.0
    ctrl._realized_mono = 90.0
    run_step(ctrl)
    assert ctrl.pulse_e_fields == []
    assert ctrl.used_coil_placements_idx == []
    assert ctrl.target_created is False


def test_collect_gives_up_when_no_realized_target_arrives():
    ctrl = make_controller(online=False, e_matrix=np.ones((2, 2)))
    ctrl.target_created = False
    ctrl.current_step_start_time = time.time() - 30
    ctrl.collect_timeout_s = 20
    run_step(ctrl)
    assert ctrl.steps and ctrl.steps[-1] is Step.COMPLETE
    assert ctrl.pulse_e_fields == []


def test_pulse_is_discarded_when_the_step_is_aborted_during_the_read():
    ctrl = make_controller(online=False, e_matrix=np.ones((2, 2)))

    def aborting_read(idx=None, e_field_for_mep=None, after=None):
        ctrl.current_step = Step.SKIP
        return object()

    ctrl.emg_computer.get_latest_emg_df = aborting_read
    run_step(ctrl)
    assert ctrl.pulse_e_fields == []
    assert ctrl.mep_history == {}


def test_precomputed_pulse_with_a_large_aim_error_is_flagged():
    ctrl = make_controller(online=False, e_matrix=np.ones((2, 2)))
    ctrl.realized_target = {"markers": [[10.0, 0.0, 0.0], [0.0, 0.0, 0.0]]}
    ctrl.target_at_stim = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    run_step(ctrl)
    assert any("planned position" in str(step) for step in ctrl.steps)


def test_online_pulse_is_not_flagged_for_the_aim_error():
    # The online solver computes the field at the realized position, so a miss
    # is not a mismatch between the field and the anatomy.
    ctrl = make_controller(online=True, computed=np.ones(2))
    ctrl.realized_target = {"markers": [[10.0, 0.0, 0.0], [0.0, 0.0, 0.0]]}
    ctrl.target_at_stim = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    run_step(ctrl)
    assert not any("planned position" in str(step) for step in ctrl.steps)
