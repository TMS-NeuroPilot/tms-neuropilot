#!/usr/bin/env python3
"""Export FEM and surrogate E-fields as two ParaView time series.

Writes two ``.pvd`` collections with the same placement order:

    <out>/fem.pvd          FEM fields (from the library's ``E`` dataset)
    <out>/estimated.pvd    surrogate fields (same placements)

The individual ``.vtp`` files live next to each collection; open the two
``.pvd`` files in ParaView and use the time controls to step through the
placements. Both collections have the same number of steps, so they update
together.

The surrogate is trained on 80% of the library; the exported placements are
test poses that the domain guard accepts. The magnitude is the scalar
surrogate's estimate (the accepted method); the direction comes from a
separate PCA/IDW surrogate of the three vector components, scaled to that
magnitude. ``estimated.vtp`` also carries the FEM magnitude and the error
arrays for comparison.

The library is at ``didt = 1e6 A/s`` (1 A/us), so both files show the field
for that current rate; multiply by ``amplitude_percent * 1.4`` for V/m at a
given stimulator amplitude.

Requires the ``neuropilot`` environment (pyvista/h5py).
"""
import argparse
from pathlib import Path
import sys
import time
import warnings

import h5py
import numpy as np
import pyvista as pv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from neuropilot.controller.EFieldSurrogate import EFieldSurrogate, read_library  # noqa: E402


def _roi_geometry(path, roi_idx):
    with h5py.File(path, "r") as handle:
        group = handle[f"roi_surface/{roi_idx}"]
        points = np.asarray(group["node_coord_mid"][:], dtype=np.float64)
        raw = np.asarray(group["node_number_list"][:, :3], dtype=np.int64)
    triangles = raw - raw.min()
    if triangles.max() >= len(points):
        raise ValueError("ROI triangles reference nodes outside node_coord_mid")
    faces = np.hstack([np.full((len(triangles), 1), 3, dtype=np.int64),
                       triangles]).ravel()
    return points, triangles, faces


def _normals(points, triangles):
    p1 = points[triangles[:, 0]]
    p2 = points[triangles[:, 1]]
    p3 = points[triangles[:, 2]]
    normals = np.cross(p2 - p1, p3 - p1)
    lengths = np.linalg.norm(normals, axis=1)
    return normals / np.where(lengths > 0, lengths, 1.0)[:, None]


def _cell_mesh(points, faces):
    return pv.PolyData(points, faces)


def _write_pvd(path, files):
    lines = ['<?xml version="1.0"?>',
             '<VTKFile type="Collection" version="0.1" byte_order="LittleEndian">',
             '  <Collection>']
    for step, filename in enumerate(files):
        lines.append(f'    <DataSet timestep="{step}" group="" part="0" '
                     f'file="{filename}"/>')
    lines += ['  </Collection>', '</VTKFile>']
    Path(path).write_text("\n".join(lines) + "\n")


def _select_steps(estimator, mats, test, n_steps):
    accepted = [int(i) for i in test if estimator.check_pose(mats[i]).inside]
    if not accepted:
        raise RuntimeError("no test placement passed the domain guard")
    count = min(int(n_steps), len(accepted))
    picks = np.linspace(0, len(accepted) - 1, count).round().astype(int)
    return [accepted[int(i)] for i in picks]


def _add_common(mesh, vectors, magnitude, normals, pose, index, check):
    norm = -np.sum(vectors * normals, axis=1)
    tangent = np.sqrt(np.clip(magnitude ** 2 - norm ** 2, 0.0, None))
    mesh.cell_data["E"] = vectors.astype(np.float32)
    mesh.cell_data["E_mag"] = magnitude.astype(np.float32)
    mesh.cell_data["E_norm"] = norm.astype(np.float32)
    mesh.cell_data["E_tan"] = tangent.astype(np.float32)
    mesh.cell_data.active_vectors_name = "E"
    mesh.cell_data.active_scalars_name = "E_mag"
    mesh.field_data["pose_matrix"] = np.asarray(pose, dtype=np.float64).ravel()
    mesh.field_data["translation"] = np.asarray(pose)[:3, 3]
    mesh.field_data["library_index"] = np.array([index], dtype=np.int32)
    mesh.field_data["guard_position_mm"] = np.array(
        [check.position_distance_mm], dtype=np.float64)
    mesh.field_data["guard_rotation_deg"] = np.array(
        [check.rotation_distance_deg], dtype=np.float64)
    mesh.field_data["didt_A_per_s"] = np.array([1e6], dtype=np.float64)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True,
                        help="e.hdf5 from 02_create_roi_efield_library.py")
    parser.add_argument("--roi-hdf5", required=True,
                        help="m2m subject HDF5 with roi_surface/<roi-idx>")
    parser.add_argument("--roi-idx", default="midlayer_m1s1pmd")
    parser.add_argument("--out-dir", default="efield_vtk")
    parser.add_argument("--n-steps", type=int, default=40)
    parser.add_argument("--components", type=int, default=20,
                        help="PCA components for E_mag (accepted method)")
    parser.add_argument("--vec-components", type=int, default=60,
                        help="PCA components for the vector direction")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    out = Path(args.out_dir)
    fem_dir = out / "fem"
    est_dir = out / "estimated"
    for directory in (fem_dir, est_dir):
        directory.mkdir(parents=True, exist_ok=True)
        for old in directory.glob("e_*.vtp"):
            old.unlink()

    e_mag, mats = read_library(args.library)
    with h5py.File(args.library, "r") as handle:
        if "E" not in handle:
            raise KeyError(f"{args.library} has no 'E' vector dataset")
        e_vec = np.asarray(handle["E"][:], dtype=np.float64)
    if e_vec.shape[:2] != e_mag.shape:
        raise ValueError("E and E_mag disagree on the ROI shape")

    points, triangles, faces = _roi_geometry(args.roi_hdf5, args.roi_idx)
    if len(triangles) != e_mag.shape[1]:
        raise ValueError("ROI triangles and E-field elements disagree")
    normals = _normals(points, triangles)

    rng = np.random.default_rng(args.seed)
    order = rng.permutation(len(e_mag))
    n_test = max(1, int(round(0.2 * len(e_mag))))
    train, test = order[n_test:], order[:n_test]

    started = time.time()
    mag_surrogate = EFieldSurrogate.from_arrays(
        e_mag[train], mats[train], n_components=args.components,
        on_outside="warn", clip_nonnegative=True)
    vec_surrogate = EFieldSurrogate.from_arrays(
        e_vec[train].reshape(len(train), -1), mats[train],
        n_components=args.vec_components, on_outside="warn",
        clip_nonnegative=False)
    print(f"fitted surrogates on {len(train)} placements in "
          f"{time.time() - started:.1f} s "
          f"(mag k={mag_surrogate.n_components}, "
          f"vec k={vec_surrogate.n_components})")

    steps = _select_steps(mag_surrogate, mats, test, args.n_steps)
    fem_files, est_files = [], []
    field_errors, magnitude_errors, direction_angles = [], [], []
    full_magnitude_errors = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for step, index in enumerate(steps):
            check = mag_surrogate.check_pose(mats[index])
            fem = e_vec[index]
            fem_mag = e_mag[index]

            est_mag, _ = mag_surrogate.compute_e_field(mats[index])
            est_vec, _ = vec_surrogate.compute_e_field(mats[index])
            est_vec = est_vec.reshape(-1, 3)
            lengths = np.linalg.norm(est_vec, axis=1)
            direction = np.divide(est_vec, lengths[:, None],
                                  out=np.zeros_like(est_vec),
                                  where=lengths[:, None] > 0)
            est_vec = direction * est_mag[:, None]

            error = est_vec - fem
            error_mag = np.linalg.norm(error, axis=1)
            relative = np.divide(error_mag, np.linalg.norm(fem, axis=1),
                                 out=np.full_like(error_mag, np.nan),
                                 where=np.linalg.norm(fem, axis=1) > 0)
            field_errors.append(100.0 * np.linalg.norm(error)
                                / np.linalg.norm(fem))
            magnitude_errors.append(100.0 * np.median(np.abs(est_mag - fem_mag)
                                                      / np.abs(fem_mag)))
            full_magnitude_errors.append(
                100.0 * np.linalg.norm(est_mag - fem_mag)
                / np.linalg.norm(fem_mag))
            fem_lengths = np.linalg.norm(fem, axis=1)
            est_lengths = np.linalg.norm(est_vec, axis=1)
            cosine = np.sum(est_vec * fem, axis=1) / np.maximum(
                fem_lengths * est_lengths, 1e-12)
            direction_angles.append(np.degrees(
                np.arccos(np.clip(cosine, -1.0, 1.0))))

            fem_mesh = _cell_mesh(points, faces)
            _add_common(fem_mesh, fem, fem_mag, normals, mats[index], index,
                        check)
            fem_name = f"fem/e_{step:03d}.vtp"
            fem_mesh.save(out / fem_name, binary=True)
            fem_files.append(fem_name)

            est_mesh = _cell_mesh(points, faces)
            _add_common(est_mesh, est_vec, est_mag, normals, mats[index],
                        index, check)
            est_mesh.cell_data["E_fem_mag"] = fem_mag.astype(np.float32)
            est_mesh.cell_data["E_error"] = error.astype(np.float32)
            est_mesh.cell_data["E_error_mag"] = error_mag.astype(np.float32)
            est_mesh.cell_data["E_rel_error"] = relative.astype(np.float32)
            est_name = f"estimated/e_{step:03d}.vtp"
            est_mesh.save(out / est_name, binary=True)
            est_files.append(est_name)

    _write_pvd(out / "fem.pvd", fem_files)
    _write_pvd(out / "estimated.pvd", est_files)

    print(f"selected {len(steps)} accepted test placements")
    print(f"vector field error median {np.median(field_errors):.2f}%  "
          f"magnitude error median {np.median(full_magnitude_errors):.2f}%")
    print(f"direction angle median "
          f"{np.median(np.concatenate(direction_angles)):.1f} deg  "
          f"element |E| error median {np.median(magnitude_errors):.2f}%")
    print(f"open: {out / 'fem.pvd'}")
    print(f"      {out / 'estimated.pvd'}")


if __name__ == "__main__":
    main()
