"""Coil targets: SimNIBS matrices -> InVesalius position + Euler angles.

The conversion right-multiplies the rotation by the basis change

    T = [[0, 1, 0],
         [1, 0, 0],
         [0, 0, -1]]      (a 180 deg rotation about (1, 1, 0))

and leaves the translation untouched (InVesalius and SimNIBS agree on
positions, the coil *axes* are what differ).  These tests pin that down with
hand-checked matrices and with a round-trip through ``euler_matrix``.
"""

import h5py
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from neuropilot.controller import transformations as tr
from neuropilot.controller.pipeline_controller import PipelineController

get_initial_targets = PipelineController.get_initial_targets

BASIS_CHANGE = np.array([[0.0, 1.0, 0.0],
                         [1.0, 0.0, 0.0],
                         [0.0, 0.0, -1.0]])


def write_targets(path, matrices):
    with h5py.File(path, "w") as f:
        f.create_dataset("matsimnibs", data=np.stack(matrices, axis=2))


def make_controller(targets_file, order_file=None):
    from types import SimpleNamespace
    return SimpleNamespace(targets_file=str(targets_file),
                           target_order_fn=None if order_file is None else str(order_file),
                           target_order=None)


def target_matrix(translation=(0, 0, 0), euler_xyz_deg=(0, 0, 0)):
    m = np.eye(4)
    m[:3, :3] = Rotation.from_euler("xyz", euler_xyz_deg, degrees=True).as_matrix()
    m[:3, 3] = translation
    return m


def test_basis_change_is_a_proper_rotation():
    np.testing.assert_allclose(BASIS_CHANGE @ BASIS_CHANGE.T, np.eye(3), atol=1e-12)
    assert np.linalg.det(BASIS_CHANGE) == pytest.approx(1.0)


def test_positions_pass_through_unchanged(tmp_path):
    path = tmp_path / "targets.hdf5"
    write_targets(path, [target_matrix(translation=(10.0, 20.0, 30.0))])
    queue, _ = get_initial_targets(make_controller(path))
    np.testing.assert_allclose(queue[0][0], [10.0, 20.0, 30.0])


def test_each_axis_keeps_its_meaning(tmp_path):
    path = tmp_path / "targets.hdf5"
    write_targets(path, [target_matrix(translation=(1.0, 0.0, 0.0)),
                         target_matrix(translation=(0.0, 2.0, 0.0)),
                         target_matrix(translation=(0.0, 0.0, 3.0))])
    queue, _ = get_initial_targets(make_controller(path))
    np.testing.assert_allclose([t[0] for t in queue],
                               [[1, 0, 0], [0, 2, 0], [0, 0, 3]])


@pytest.mark.parametrize("euler", [(0, 0, 0), (10, 20, 30), (0, 0, 90),
                                   (90, 0, 0), (-30, 45, 10)])
def test_angles_reproduce_the_transformed_rotation(tmp_path, euler):
    path = tmp_path / "targets.hdf5"
    matrix = target_matrix(euler_xyz_deg=euler)
    write_targets(path, [matrix])

    queue, _ = get_initial_targets(make_controller(path))
    angles = queue[0][1]
    rebuilt = tr.euler_matrix(*np.radians(angles), axes="sxyz")[:3, :3]
    np.testing.assert_allclose(rebuilt, matrix[:3, :3] @ BASIS_CHANGE, atol=1e-9)


def test_angles_are_in_degrees(tmp_path):
    path = tmp_path / "targets.hdf5"
    write_targets(path, [target_matrix(euler_xyz_deg=(0, 0, 90))])
    queue, _ = get_initial_targets(make_controller(path))
    assert np.all(np.abs(queue[0][1]) <= 180.0)


def test_identity_rotation_becomes_the_basis_change(tmp_path):
    path = tmp_path / "targets.hdf5"
    write_targets(path, [target_matrix()])
    queue, _ = get_initial_targets(make_controller(path))
    # A 180 deg turn about (1, 1, 0): the canonical xyz solution is (180, 0, 90).
    np.testing.assert_allclose(np.abs(queue[0][1]), [180.0, 0.0, 90.0], atol=1e-9)


def test_all_matrices_are_returned_in_file_order(tmp_path):
    path = tmp_path / "targets.hdf5"
    write_targets(path, [target_matrix(translation=(float(i), 0.0, 0.0)) for i in range(4)])
    queue, order = get_initial_targets(make_controller(path))
    assert len(queue) == 4
    np.testing.assert_array_equal(order, np.arange(4))
    np.testing.assert_allclose([t[0][0] for t in queue], [0, 1, 2, 3])


def test_target_order_file_is_honoured(tmp_path):
    path = tmp_path / "targets.hdf5"
    write_targets(path, [target_matrix(translation=(float(i), 0.0, 0.0)) for i in range(3)])
    order_file = tmp_path / "order.txt"
    order_file.write_text("2\n0\n1\n")

    queue, order = get_initial_targets(make_controller(path, order_file))
    assert len(queue) == 3
    np.testing.assert_array_equal(order, [2, 0, 1])


def test_source_file_is_not_modified(tmp_path):
    path = tmp_path / "targets.hdf5"
    matrix = target_matrix(translation=(1.0, 2.0, 3.0), euler_xyz_deg=(5, 6, 7))
    write_targets(path, [matrix])

    get_initial_targets(make_controller(path))
    with h5py.File(path, "r") as f:
        stored = f["matsimnibs"][:, :, 0]
    np.testing.assert_allclose(stored, matrix)
