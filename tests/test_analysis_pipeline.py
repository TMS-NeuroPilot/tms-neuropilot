"""The analysis pipeline: stale results, NaN MEPs, width/source mismatches.

No Qt here; the regression is replaced by a recorder so the data reaching it
can be asserted directly.
"""

from concurrent.futures import Future
from types import SimpleNamespace

import numpy as np
import pytest

import neuropilot.controller.pipeline_controller as pc


class InlineExecutor:
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
        except Exception as exc:                  # pragma: no cover
            future.set_exception(exc)
        return future


@pytest.fixture()
def analysis(controller, monkeypatch):
    monkeypatch.setattr(pc, "ProcessPoolExecutor", InlineExecutor)
    calls = []

    def fake_regress(args):
        channel, meps, matrix, fit_fun, elm_idx_list, n_elms = args
        calls.append({"channel": channel, "meps": list(meps),
                      "matrix": np.array(matrix)})
        return channel, np.zeros(n_elms)

    monkeypatch.setattr(pc, "_regress_single_channel", fake_regress)
    controller.elm_idx_list = np.arange(3)
    controller.n_elms = 3
    controller.calls = calls
    controller.panel_updates = []
    controller.panel_lines = []
    controller.control_panel = SimpleNamespace(
        update_mesh_coloring=lambda scores: controller.panel_updates.append(scores),
        totaltargets3=SimpleNamespace(setText=lambda text: None),
        finishedsteps=SimpleNamespace(
            appendPlainText=controller.panel_lines.append,
            ensureCursorVisible=lambda: None),
    )
    return controller


def feed(ctrl, rows, meps, excluded=()):
    ctrl.used_coil_placements_idx = list(range(len(rows)))
    ctrl.pulse_e_fields = list(rows)
    ctrl.pulse_modes = ["precomputed"] * len(rows)
    ctrl.mep_history = dict(meps)
    ctrl.excluded_pulse_indices = set(excluded)


def rows(n):
    return [np.full(3, float(i)) for i in range(n)]


# ── stale results ──────────────────────────────────────────────────────

def test_superseded_analysis_is_discarded(analysis):
    feed(analysis, rows(4), {"ADC 0": [1.0, 2.0, 3.0, 4.0]})
    analysis._analysis_generation = 2

    analysis.run_analysis(generation=1)          # an older request
    assert analysis.calls == [] or analysis.panel_updates == []
    assert analysis.final_scores == {}

    analysis.run_analysis(generation=2)
    assert analysis.panel_updates
    assert "ADC 0" in analysis.final_scores


def test_current_generation_is_used_by_default(analysis):
    feed(analysis, rows(3), {"ADC 0": [1.0, 2.0, 3.0]})
    analysis._analysis_generation = 5
    analysis.run_analysis()
    assert analysis.panel_updates


def test_request_analysis_runs_without_an_event_loop(analysis):
    feed(analysis, rows(3), {"ADC 0": [1.0, 2.0, 3.0]})
    analysis.request_analysis()                  # no loop: synchronous
    assert analysis._analysis_generation == 1
    assert analysis.panel_updates


# ── non-finite MEPs ────────────────────────────────────────────────────

def test_channel_with_a_nan_mep_is_fitted_on_the_rest(analysis):
    feed(analysis, rows(4), {"ADC 0": [1.0, float("nan"), 3.0, 4.0]})
    analysis.run_analysis()
    assert len(analysis.calls) == 1
    assert analysis.calls[0]["meps"] == [1.0, 3.0, 4.0]
    assert analysis.calls[0]["matrix"].shape == (3, 3)


def test_channel_with_too_few_finite_meps_is_skipped(analysis):
    feed(analysis, rows(4), {"ADC 0": [1.0, float("nan"), float("nan"), 4.0]})
    analysis.run_analysis()
    assert analysis.calls == []
    assert any("no map for this channel" in line
               for line in analysis.panel_lines)


def test_one_bad_channel_does_not_block_the_other(analysis):
    feed(analysis, rows(4), {"ADC 0": [1.0, float("nan"), float("nan"), 4.0],
                             "ADC 1": [1.0, 2.0, 3.0, 4.0]})
    analysis.run_analysis()
    assert [call["channel"] for call in analysis.calls] == ["ADC 1"]


def test_short_channel_history_is_treated_as_missing(analysis):
    feed(analysis, rows(4), {"ADC 0": [1.0, 2.0]})   # only two samples
    analysis.run_analysis()
    assert analysis.calls == []


# ── dropped pulses / widths ────────────────────────────────────────────

def test_pulses_without_a_field_are_counted(analysis):
    feed(analysis, [np.ones(3), None, np.ones(3), np.ones(3)],
         {"ADC 0": [1.0, 2.0, 3.0, 4.0]})
    analysis.run_analysis()
    assert analysis.calls[0]["meps"] == [1.0, 3.0, 4.0]
    assert any("without an E-field" in line for line in analysis.panel_lines)


def test_mixed_row_widths_use_the_majority_width(analysis):
    narrow = [np.ones(3) for _ in range(3)]
    wide = [np.ones(5)]
    feed(analysis, narrow + wide, {"ADC 0": [1.0, 2.0, 3.0, 4.0]})
    analysis.run_analysis()
    assert analysis.calls[0]["matrix"].shape == (3, 3)


# ── library / placements consistency ───────────────────────────────────

def test_matching_library_and_placements_do_not_warn(analysis, e_matrix_hdf5,
                                                     placements_hdf5):
    analysis.set_e_matrix_file(str(e_matrix_hdf5(3, 6)))
    analysis.set_targets_file(str(placements_hdf5(3)))
    assert analysis.library_warning is None


def test_different_placement_counts_warn(analysis, e_matrix_hdf5, placements_hdf5):
    analysis.set_e_matrix_file(str(e_matrix_hdf5(2, 6)))
    analysis.set_targets_file(str(placements_hdf5(5)))
    assert analysis.library_warning
    assert "5" in analysis.library_warning and "2" in analysis.library_warning


def test_different_placements_with_the_same_count_warn(analysis, h5file):
    mats = np.repeat(np.eye(4)[:, :, None], 3, axis=2)
    library = h5file({"E_mag": np.ones((3, 4)),
                      "matsimnibs": mats}, "e.hdf5")
    shifted = mats.copy()
    shifted[0, 3, :] = 9.0
    targets = h5file({"matsimnibs": shifted}, "t.hdf5")

    analysis.set_e_matrix_file(str(library))
    analysis.set_targets_file(str(targets))
    assert analysis.library_warning
    assert "different coil placements" in analysis.library_warning


def test_transposed_library_layout_is_compared_not_skipped(analysis, h5file):
    """(n, 4, 4) in the library and (4, 4, n) in the placements agree."""
    mats = np.repeat(np.eye(4)[:, :, None], 3, axis=2)
    library = h5file({"E_mag": np.ones((3, 4)),
                      "matsimnibs": mats.transpose(2, 0, 1)}, "e.hdf5")
    targets = h5file({"matsimnibs": mats}, "t.hdf5")

    analysis.set_e_matrix_file(str(library))
    analysis.set_targets_file(str(targets))
    assert analysis.library_warning is None


def test_transposed_layout_with_different_matrices_warns(analysis, h5file):
    mats = np.repeat(np.eye(4)[:, :, None], 3, axis=2)
    shifted = mats.copy()
    shifted[0, 3, :] = 9.0
    library = h5file({"E_mag": np.ones((3, 4)),
                      "matsimnibs": shifted.transpose(2, 0, 1)}, "e.hdf5")
    targets = h5file({"matsimnibs": mats}, "t.hdf5")

    analysis.set_e_matrix_file(str(library))
    analysis.set_targets_file(str(targets))
    assert analysis.library_warning
    assert "different coil placements" in analysis.library_warning


def test_the_warning_clears_when_the_files_agree_again(analysis, e_matrix_hdf5,
                                                       placements_hdf5):
    analysis.set_e_matrix_file(str(e_matrix_hdf5(2, 6)))
    analysis.set_targets_file(str(placements_hdf5(5)))
    assert analysis.library_warning
    analysis.set_targets_file(str(placements_hdf5(2)))
    assert analysis.library_warning is None


# ── score delivery ─────────────────────────────────────────────────────

def test_scores_can_be_delivered_through_a_signal():
    emitted = []
    signal = SimpleNamespace(emit=lambda scores: emitted.append(scores))
    panel = SimpleNamespace(scores_ready=signal,
                            update_mesh_coloring=lambda scores: None)
    ctrl = SimpleNamespace(control_panel=panel)
    pc.PipelineController._deliver_scores(ctrl, {"ADC 0": np.zeros(3)})
    assert emitted and "ADC 0" in emitted[0]


def test_plain_panels_are_called_directly():
    calls = []
    panel = SimpleNamespace(update_mesh_coloring=lambda scores: calls.append(scores))
    ctrl = SimpleNamespace(control_panel=panel)
    pc.PipelineController._deliver_scores(ctrl, {"ADC 0": np.zeros(2)})
    assert len(calls) == 1
    np.testing.assert_allclose(calls[0]["ADC 0"], np.zeros(2))


def test_delivery_without_a_panel_is_a_no_op():
    pc.PipelineController._deliver_scores(SimpleNamespace(control_panel=None),
                                          {"ADC 0": np.zeros(2)})
