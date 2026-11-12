"""Synthetic tests for the precomputed E-field surrogate.

The library is small enough to check the interpolation and the domain guard
without SimNIBS, a head mesh, or an FEM solve.
"""
import numpy as np
import pytest

from neuropilot.controller.EFieldSurrogate import (
    EFieldSurrogate,
    OutsideDomainError,
)


def _pose(x, y, angle_deg):
    angle = np.deg2rad(angle_deg)
    c, s = np.cos(angle), np.sin(angle)
    matrix = np.eye(4)
    matrix[:3, :3] = [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]
    matrix[:3, 3] = [x, y, 0.0]
    return matrix


def _field(x, y, angle_deg):
    """Smooth, strictly positive five-element field for the synthetic grid."""
    theta = np.deg2rad(angle_deg)
    return np.array([
        1.00 + 0.05 * x + 0.03 * y + 0.02 * np.cos(theta),
        0.80 + 0.04 * y - 0.02 * x + 0.01 * np.sin(theta),
        0.60 + 0.03 * (x + y) + 0.02 * np.cos(2 * theta),
        0.40 + 0.02 * x * y + 0.01 * np.sin(2 * theta),
        0.20 + 0.01 * (x * x - y * y) + 0.02 * np.cos(theta),
    ])


@pytest.fixture()
def library():
    """3 x 3 positions at 4 mm spacing, four rotations at 15 deg steps."""
    positions = [(x, y) for x in (-4.0, 0.0, 4.0) for y in (-4.0, 0.0, 4.0)]
    angles = (0.0, 15.0, 30.0, 45.0)
    mats = np.array([_pose(x, y, a) for x, y in positions for a in angles])
    e_mag = np.array([_field(x, y, a) for x, y in positions for a in angles])
    return e_mag, mats


@pytest.fixture()
def surrogate(library):
    e_mag, mats = library
    return EFieldSurrogate.from_arrays(e_mag, mats, n_components=5)


def test_training_poses_reconstruct_exactly(library, surrogate):
    e_mag, mats = library
    for expected, matrix in zip(e_mag, mats):
        field, check = surrogate.compute_e_field(matrix)
        assert check.inside
        assert check.position_distance_mm == pytest.approx(0.0, abs=1e-9)
        assert check.rotation_distance_deg == pytest.approx(0.0, abs=1e-9)
        np.testing.assert_allclose(field, expected, rtol=1e-6, atol=1e-9)


def test_guard_defaults_match_the_sampling(surrogate):
    assert surrogate.max_position_distance_mm == pytest.approx(4.0)
    assert surrogate.max_rotation_distance_deg == pytest.approx(15.0)
    assert surrogate.position_search_mm == pytest.approx(6.0)
    assert surrogate.rotation_search_deg == pytest.approx(22.5)


def test_signed_features_are_not_clipped(library):
    """A vector-component surrogate must keep negative values."""
    e_mag, mats = library
    signed = e_mag.copy()
    signed[:, 3] -= 1.0
    surrogate = EFieldSurrogate.from_arrays(signed, mats, n_components=5)
    field, _ = surrogate.compute_e_field(mats[0])
    assert field[3] < 0.0
    np.testing.assert_allclose(field, signed[0], rtol=1e-6, atol=1e-9)


def test_between_samples_is_inside_and_accurate(surrogate):
    # Cell centre (2, 2) and half a rotation step: both are inside.
    expected = _field(2.0, 2.0, 7.5)
    field, check = surrogate.compute_e_field(_pose(2.0, 2.0, 7.5))
    assert check.inside
    error = np.linalg.norm(field - expected) / np.linalg.norm(expected)
    assert error < 0.05


def test_outside_position_and_rotation_are_detected(surrogate):
    far_position = surrogate.check_pose(_pose(20.0, 0.0, 0.0))
    assert not far_position.inside
    assert "position" in far_position.reasons[0]

    far_rotation = surrogate.check_pose(_pose(0.0, 0.0, 75.0))
    assert not far_rotation.inside
    assert "rotation" in far_rotation.reasons[0]


def test_outside_policies(library):
    e_mag, mats = library
    outside = _pose(20.0, 0.0, 0.0)

    nan_surrogate = EFieldSurrogate.from_arrays(
        e_mag, mats, n_components=5, on_outside="nan")
    with pytest.warns(RuntimeWarning):
        field, check = nan_surrogate.compute_e_field(outside)
    assert not check.inside
    assert np.isnan(field).all()

    raise_surrogate = EFieldSurrogate.from_arrays(
        e_mag, mats, n_components=5, on_outside="raise")
    with pytest.raises(OutsideDomainError):
        raise_surrogate.compute_e_field(outside)

    warn_surrogate = EFieldSurrogate.from_arrays(
        e_mag, mats, n_components=5, on_outside="warn")
    with pytest.warns(RuntimeWarning):
        warn_field, warn_check = warn_surrogate.compute_e_field(outside)
    assert not warn_check.inside
    assert np.isfinite(warn_field).all()


def test_explicit_domain_limit(library):
    e_mag, mats = library
    loose = EFieldSurrogate.from_arrays(
        e_mag, mats, n_components=5, max_position_distance_mm=25.0,
        on_outside="nan")
    _, check = loose.compute_e_field(_pose(20.0, 0.0, 0.0))
    assert check.inside


def test_refit_recomputes_the_sampling_defaults(library):
    e_mag, mats = library
    surrogate = EFieldSurrogate(n_components=3)
    surrogate.fit(e_mag, mats)
    assert surrogate.max_rotation_distance_deg == pytest.approx(15.0)

    positions = [(x, y) for x in (-4.0, 0.0, 4.0) for y in (-4.0, 0.0, 4.0)]
    angles = np.arange(0.0, 45.0 + 7.5, 7.5)
    finer = np.array([_pose(x, y, a) for x, y in positions for a in angles])
    finer_e = np.array([_field(x, y, a) for x, y in positions for a in angles])
    surrogate.fit(finer_e, finer)
    assert surrogate.max_rotation_distance_deg == pytest.approx(7.5)
    assert surrogate.n_components == 3


def test_rejects_a_non_4x4_pose(surrogate):
    with pytest.raises(ValueError):
        surrogate.compute_e_field(np.eye(3))


def test_hdf5_round_trip(library, tmp_path):
    h5py = pytest.importorskip("h5py")
    e_mag, mats = library
    path = tmp_path / "e.hdf5"
    with h5py.File(path, "w") as handle:
        handle.create_dataset("E_mag", data=e_mag)
        handle.create_dataset("matsimnibs", data=mats)

    surrogate = EFieldSurrogate.from_file(path, n_components=5)
    field, check = surrogate.compute_e_field(mats[17])
    assert check.inside
    np.testing.assert_allclose(field, e_mag[17], rtol=1e-6, atol=1e-9)
