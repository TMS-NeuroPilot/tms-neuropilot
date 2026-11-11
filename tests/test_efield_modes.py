"""Per-pulse E-field rows: the basis for switching the mode in flight.

The regression matrix is assembled from one row per pulse, so pulses
collected before and after a mode switch stay index-aligned with the MEP
history.  These tests pin that contract down.
"""

import numpy as np
import pytest

from neuropilot.controller.pipeline_controller import (
    assemble_analysis_matrix, precomputed_e_field_row,
)


class TestPrecomputedRow:
    def test_scales_with_the_stimulator_output(self):
        matrix = np.array([[1.0, 2.0], [3.0, 4.0]])
        row = precomputed_e_field_row(matrix, 1, 50)
        np.testing.assert_allclose(row, [3.0 * 50 * 1.4, 4.0 * 50 * 1.4])

    def test_zero_amplitude_gives_a_zero_row(self):
        row = precomputed_e_field_row(np.ones((2, 3)), 0, 0)
        np.testing.assert_allclose(row, np.zeros(3))

    def test_none_matrix_or_index_gives_none(self):
        assert precomputed_e_field_row(None, 0, 50) is None
        assert precomputed_e_field_row(np.ones((2, 3)), None, 50) is None

    def test_out_of_range_index_gives_none(self):
        assert precomputed_e_field_row(np.ones((2, 3)), 7, 50) is None

    def test_does_not_modify_the_source_matrix(self):
        matrix = np.ones((2, 3))
        precomputed_e_field_row(matrix, 0, 80)
        np.testing.assert_allclose(matrix, np.ones((2, 3)))


class TestAssembleAnalysisMatrix:
    def test_alignment_and_values(self):
        rows = [np.array([i, i, i], dtype=float) for i in range(5)]
        kept, matrix = assemble_analysis_matrix(rows, np.arange(5))
        np.testing.assert_array_equal(kept, np.arange(5))
        assert matrix.shape == (5, 3)
        np.testing.assert_allclose(matrix[:, 0], np.arange(5))

    def test_missing_rows_are_dropped_with_their_indices(self):
        rows = [np.ones(3), None, np.full(3, 2.0), None, np.full(3, 4.0)]
        kept, matrix = assemble_analysis_matrix(rows, np.arange(len(rows)))
        np.testing.assert_array_equal(kept, [0, 2, 4])
        np.testing.assert_allclose(matrix[:, 0], [1.0, 2.0, 4.0])

    def test_mixed_sources_are_kept_in_pulse_order(self):
        # One pulse from the precomputed matrix, one from the online solver,
        # one more from the precomputed matrix.
        rows = [np.full(2, 1.0), np.full(2, 10.0), np.full(2, 100.0)]
        kept, matrix = assemble_analysis_matrix(rows, [0, 1, 2])
        np.testing.assert_array_equal(kept, [0, 1, 2])
        np.testing.assert_allclose(matrix[:, 0], [1.0, 10.0, 100.0])

    def test_excluded_indices_are_respected(self):
        rows = [np.ones(2) for _ in range(4)]
        kept, matrix = assemble_analysis_matrix(rows, [0, 2, 3])
        np.testing.assert_array_equal(kept, [0, 2, 3])
        assert matrix.shape == (3, 2)

    def test_indices_beyond_the_recorded_rows_are_ignored(self):
        rows = [np.ones(2)]
        kept, matrix = assemble_analysis_matrix(rows, [0, 1, 2])
        np.testing.assert_array_equal(kept, [0])
        assert matrix.shape == (1, 2)

    def test_no_usable_pulse_gives_an_empty_result(self):
        kept, matrix = assemble_analysis_matrix([], [0, 1, 2])
        assert matrix is None and len(kept) == 0
        kept, matrix = assemble_analysis_matrix([None, None], [0, 1])
        assert matrix is None and len(kept) == 0

    def test_two_pulses_are_not_enough(self):
        # run_analysis requires three pulses for a regression; the helper
        # itself must still return what it has so the caller can say why.
        rows = [np.ones(2), np.ones(2)]
        kept, matrix = assemble_analysis_matrix(rows, [0, 1])
        assert len(kept) == 2 and matrix.shape == (2, 2)

    def test_rows_stack_into_a_matrix_of_the_right_width(self):
        rows = [np.arange(10, dtype=float), np.arange(10, dtype=float) * 2]
        _, matrix = assemble_analysis_matrix(rows, [0, 1])
        assert matrix.shape == (2, 10)

    def test_accepts_plain_lists_as_rows(self):
        kept, matrix = assemble_analysis_matrix([[1.0, 2.0], [3.0, 4.0]], [0, 1])
        np.testing.assert_allclose(matrix, [[1.0, 2.0], [3.0, 4.0]])


def test_amplitude_scaling_uses_the_realized_intensity():
    # 80 % output on a 100 %-normalised matrix equals 80*1.4 units.
    matrix = np.array([[1.0]])
    np.testing.assert_allclose(precomputed_e_field_row(matrix, 0, 80), [112.0])
    assert precomputed_e_field_row(matrix, 0, 80)[0] == pytest.approx(80 * 1.4)
