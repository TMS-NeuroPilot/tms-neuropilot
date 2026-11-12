"""The session-side manager: background load, ROI verification, NaN policy."""

import time

import h5py
import numpy as np
import pytest

from neuropilot.controller.EFieldSurrogate import roi_geometry_hash
from neuropilot.controller.SurrogateManager import SurrogateManager


def _pose(x, y, angle_deg):
    angle = np.deg2rad(angle_deg)
    c, s = np.cos(angle), np.sin(angle)
    matrix = np.eye(4)
    matrix[:3, :3] = [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]
    matrix[:3, 3] = [x, y, 0.0]
    return matrix


def _field(x, y, angle_deg):
    """Smooth six-element field for the synthetic grid."""
    theta = np.deg2rad(angle_deg)
    return np.array([
        1.00 + 0.05 * x + 0.03 * y + 0.02 * np.cos(theta),
        0.80 + 0.04 * y - 0.02 * x + 0.01 * np.sin(theta),
        0.60 + 0.03 * (x + y) + 0.02 * np.cos(2 * theta),
        0.40 + 0.02 * x * y + 0.01 * np.sin(2 * theta),
        0.20 + 0.01 * (x * x - y * y) + 0.02 * np.cos(theta),
        0.10 + 0.02 * x + 0.01 * np.sin(theta),
    ])


@pytest.fixture()
def session_files(tmp_path):
    """A small ROI (geo.hdf5 layout) and a matching dense library."""
    rng = np.random.default_rng(3)
    points = rng.normal(size=(8, 3)) * 20.0 + np.array([50.0, 40.0, 60.0])
    triangles = np.array([[0, 1, 2], [1, 2, 3], [2, 3, 4],
                          [3, 4, 5], [4, 5, 6], [5, 6, 7]])
    roi = tmp_path / "roi.hdf5"
    with h5py.File(roi, "w") as f:
        f.create_dataset("mesh/elm/triangle_number_list", data=triangles + 1)
        f.create_dataset("mesh/nodes/node_coord", data=points)

    positions = [(x, y) for x in (-4.0, 0.0, 4.0) for y in (-4.0, 0.0, 4.0)]
    angles = (0.0, 15.0, 30.0, 45.0)
    mats = np.array([_pose(x, y, a) for x, y in positions for a in angles])
    e_mag = np.array([_field(x, y, a) for x, y in positions for a in angles])
    library = tmp_path / "e_surrogate.hdf5"
    with h5py.File(library, "w") as f:
        f.create_dataset("E_mag", data=e_mag)
        f.create_dataset("matsimnibs", data=mats)
        f.attrs["roi_hash"] = roi_geometry_hash(points[triangles].mean(axis=1))
        f.attrs["n_elements"] = e_mag.shape[1]
    return library, roi, mats, e_mag


def make_manager(session_files):
    library, roi, mats, e_mag = session_files
    mgr = SurrogateManager()
    mgr.set_library_path(str(library))
    mgr.set_roi_fn_hdf5(str(roi))
    return mgr, mats, e_mag


def test_initialize_verifies_the_roi_and_becomes_ready(session_files):
    mgr, mats, e_mag = make_manager(session_files)
    mgr.initialize()
    assert mgr.surrogate is not None
    assert mgr.n_placements == len(e_mag)
    assert mgr.n_elements == e_mag.shape[1]
    assert mgr.surrogate.max_position_distance_mm == pytest.approx(4.0)


def test_initialize_requires_library_and_roi(session_files):
    library, roi, _, _ = session_files
    mgr = SurrogateManager()
    mgr.set_library_path(str(library))
    with pytest.raises(RuntimeError, match="ROI"):
        mgr.initialize()
    mgr.set_roi_fn_hdf5(str(roi))
    mgr.initialize()
    assert mgr.surrogate is not None


def test_roi_mismatch_fails_and_is_retriable(session_files, tmp_path):
    mgr, mats, e_mag = make_manager(session_files)
    # A second ROI with different node positions → different element order.
    rng = np.random.default_rng(7)
    points = rng.normal(size=(8, 3)) * 20.0
    triangles = np.array([[0, 1, 2], [1, 2, 3], [2, 3, 4],
                          [3, 4, 5], [4, 5, 6], [5, 6, 7]])
    other = tmp_path / "other_roi.hdf5"
    with h5py.File(other, "w") as f:
        f.create_dataset("mesh/elm/triangle_number_list", data=triangles + 1)
        f.create_dataset("mesh/nodes/node_coord", data=points)
    mgr.set_roi_fn_hdf5(str(other))
    with pytest.raises(ValueError, match="different ROI"):
        mgr.initialize()
    assert mgr.surrogate is None or mgr.ready is False

    mgr.set_roi_fn_hdf5(str(session_files[1]))
    mgr.initialize()
    assert mgr.surrogate is not None


def test_ensure_initialized_runs_in_the_background(session_files):
    mgr, _, _ = make_manager(session_files)
    mgr.ensure_initialized()
    deadline = time.time() + 5
    while not mgr.ready and time.time() < deadline:
        time.sleep(0.01)
    assert mgr.ready
    assert mgr.n_placements > 0


def test_compute_scales_the_library_field(session_files):
    mgr, mats, e_mag = make_manager(session_files)
    mgr.initialize()
    row = mgr.compute_e_field([list(mats[0][:3, 3]), [0.0, 0.0, 0.0]], 50)
    np.testing.assert_allclose(row, e_mag[0] * 50 * 1.4, rtol=1e-6)
    assert mgr.e_matrix.shape == (1, e_mag.shape[1])


def test_outside_pose_records_a_nan_row_and_stays_aligned(session_files):
    mgr, mats, e_mag = make_manager(session_files)
    mgr.initialize()
    inside = mgr.compute_e_field([list(mats[0][:3, 3]), [0.0, 0.0, 0.0]], 50)
    outside = mgr.compute_e_field([[100.0, 100.0, 0.0], [0.0, 0.0, 0.0]], 50)
    assert np.all(np.isnan(outside))
    assert mgr.last_check.inside is False
    assert mgr.e_matrix.shape == (2, e_mag.shape[1])
    assert np.all(np.isfinite(mgr.e_matrix[0]))
    assert np.all(np.isnan(mgr.e_matrix[1]))


def test_reset_clears_the_accumulated_matrix(session_files):
    mgr, mats, _ = make_manager(session_files)
    mgr.initialize()
    mgr.compute_e_field([list(mats[0][:3, 3]), [0.0, 0.0, 0.0]], 50)
    mgr.reset()
    assert mgr.e_matrix is None


def test_a_changed_library_invalidates_the_ready_state(session_files, tmp_path):
    library, roi, mats, e_mag = session_files
    mgr = SurrogateManager()
    mgr.set_library_path(str(library))
    mgr.set_roi_fn_hdf5(str(roi))
    mgr.initialize()
    assert mgr.surrogate is not None

    other = tmp_path / "other_library.hdf5"
    with h5py.File(other, "w") as f:
        f.create_dataset("E_mag", data=e_mag)
        f.create_dataset("matsimnibs", data=mats)
        # Deliberately wrong hash: loading it must fail, not silently pass.
        f.attrs["roi_hash"] = "0" * 64
        f.attrs["n_elements"] = e_mag.shape[1]
    mgr.set_library_path(str(other))
    assert mgr.ready is False
    assert mgr.surrogate is None
    with pytest.raises(ValueError, match="different ROI"):
        mgr.initialize()
