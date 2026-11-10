"""Generate a coil-placement library around a target and compute the ROI
E-fields, producing an ``e.hdf5`` consumable by the NeuroPilot pipeline
(offline "Precomputed E-Field" mode reads the ``E_mag`` dataset,
shape ``(n_placements, n_roi_elements)``).

The candidate placements are generated with SimNIBS's TMSoptimize machinery
(``_prepare()`` + ``_get_coil_positions()``): a grid of scalp positions
within ``--search-radius`` of the target, each with coil handle rotations
over ``--search-angle`` in ``--angle-resolution`` steps. If more placements
than ``--n-placements`` are generated, they are subsampled evenly.

The E-fields are computed with the fast OnlineFEM solver (one shared FEM
factorization, one right-hand side per placement) and saved per midlayer ROI
triangle: ``E`` (n, n_tri, 3), ``E_mag``/``E_norm``/``E_tan`` (n, n_tri).
No layer interpolation, theta or gradient quantities are computed.

Example:
    python scripts/roi_efield_library.py \
        --mesh-msh data/ernie/mesh/m2m_ernie/ernie.msh \
        --roi-hdf5 data/ernie/mesh/m2m_ernie/ernie.hdf5 \
        --roi-idx midlayer_m1s1pmd \
        --coil <MagVenture_MCF-B65_new.ccd> \
        --target -31.8389 5.40787 70.7634 \
        --out data/ernie/efield/e.hdf5
"""

import argparse
import os
import sys

parser = argparse.ArgumentParser(
    description="Compute ROI E-fields for a coil-placement library around a target"
)
parser.add_argument("--mesh-msh", required=True, help="SimNIBS FEM mesh (.msh)")
parser.add_argument("--roi-hdf5", required=True,
                    help="pynibs mesh HDF5 containing roi_surface/<roi-idx>")
parser.add_argument("--roi-idx", default="midlayer_m1s1pmd", help="ROI identifier")
parser.add_argument("--coil", required=True, help="TMS coil model (.ccd/.nii.gz)")
parser.add_argument("--target", nargs=3, required=True, type=float,
                    metavar="X Y Z", help="Target coordinates in mesh space (mm)")
parser.add_argument("--out", default="e.hdf5", help="Output e.hdf5 path")
parser.add_argument("--n-placements", type=int, default=500,
                    help="Number of placements to simulate (subsampled evenly "
                         "from the generated candidate grid)")
parser.add_argument("--search-radius", type=float, default=20.0,
                    help="Scalp search radius around the target (mm)")
parser.add_argument("--search-angle", type=float, default=180.0,
                    help="Coil rotation search range (deg)")
parser.add_argument("--angle-resolution", type=float, default=7.5,
                    help="Coil rotation step (deg)")
parser.add_argument("--spatial-resolution", type=float, default=3.0,
                    help="Scalp grid step (mm)")
parser.add_argument("--distance", type=float, default=1.0,
                    help="Skin-coil distance (mm)")
parser.add_argument("--target-radius", type=float, default=1.0,
                    help="Target size passed to TMSoptimize (mm)")
parser.add_argument("--anisotropy", default="scalar", choices=["scalar", "vn"],
                    help="Tissue conductivity model")
parser.add_argument("--solver", default="mumps",
                    help="SimNIBS solver options (empty: default direct solver; "
                         "'pardiso' requires the pardiso package)")
parser.add_argument("--didt", type=float, default=1e6,
                    help="Coil current rate of change (A/s); 1e6 A/s = 1 A/us")
args = parser.parse_args()

# Solver options must be set before SimNIBS is imported.
os.environ["SIMNIBS_SOLVER_OPTIONS"] = args.solver

import h5py  # noqa: E402
import numpy as np  # noqa: E402
import pynibs  # noqa: E402
from simnibs import mesh_io, opt_struct  # noqa: E402
from simnibs.simulation.onlinefem import FemTargetPointCloud, OnlineFEM  # noqa: E402

target = np.asarray(args.target, dtype=float)
out_dir = os.path.dirname(os.path.abspath(args.out))
os.makedirs(out_dir, exist_ok=True)

print("-" * 64)
print("NeuroPilot ROI E-field library")
print(f"  mesh:        {args.mesh_msh}")
print(f"  roi:         {args.roi_idx} ({args.roi_hdf5})")
print(f"  coil:        {args.coil}")
print(f"  target:      {target}")
print(f"  placements:  {args.n_placements}")
print(f"  out:         {args.out}")
print("-" * 64)

# Generate the candidate coil placements around the target
# ============================================================================
tms_opt = opt_struct.TMSoptimize()
tms_opt.fnamehead = os.path.abspath(args.mesh_msh)
tms_opt.pathfem = out_dir
tms_opt.fnamecoil = os.path.abspath(args.coil)
tms_opt.target = target
tms_opt.search_radius = args.search_radius
tms_opt.search_angle = args.search_angle
tms_opt.angle_resolution = args.angle_resolution
tms_opt.spatial_resolution = args.spatial_resolution
tms_opt.distance = args.distance
tms_opt.target_size = args.target_radius
tms_opt.anisotropy_type = args.anisotropy
if args.anisotropy == "vn":
    raise NotImplementedError("vn anisotropy needs conductivity tensors; "
                              "this Ernie dataset is isotropic.")
tms_opt.open_in_gmsh = False
tms_opt.solver_options = args.solver

print("Generating candidate coil placements (TMSoptimize grid) ...")
tms_opt._prepare()
pos_matrices = tms_opt._get_coil_positions()
n_generated = len(pos_matrices)
print(f"Generated {n_generated} candidate placements.")

# Subsample evenly to the requested number of placements.
if n_generated > args.n_placements:
    idx = np.unique(np.round(np.linspace(0, n_generated - 1, args.n_placements)).astype(int))
    pos_matrices = [pos_matrices[i] for i in idx]
    print(f"Subsampled to {len(pos_matrices)} placements.")
n_pos = len(pos_matrices)

# Store the placement library next to the results (provenance).
fn_search = os.path.join(out_dir, "search_positions.hdf5")
pynibs.coil.write_coil_pos_hdf5(
    fn_hdf=fn_search,
    centers=np.vstack([p[0:3, 3] for p in pos_matrices]),
    m0=np.vstack([p[0:3, 0] for p in pos_matrices]),
    m1=np.vstack([p[0:3, 1] for p in pos_matrices]),
    m2=np.vstack([p[0:3, 2] for p in pos_matrices]),
    datanames=None, data=None, overwrite=True)
print(f"Placement library written to {fn_search}")

# Build the midlayer ROI (no layer interpolation)
# ============================================================================
print(f"Reading ROI {args.roi_idx} ...")
with h5py.File(args.roi_hdf5, "r") as f:
    roi_group = f[f"roi_surface/{args.roi_idx}"]
    node_coord_mid = roi_group["node_coord_mid"][:]
    node_number_list = roi_group["node_number_list"][:]
    tri_center_coord_mid = roi_group["tri_center_coord_mid"][:]

offset = np.min(node_number_list[:, :3])
p1 = node_coord_mid[node_number_list[:, 0] - offset]
p2 = node_coord_mid[node_number_list[:, 1] - offset]
p3 = node_coord_mid[node_number_list[:, 2] - offset]
triangles_normals = np.cross(p2 - p1, p3 - p1).T
triangles_normals /= np.linalg.norm(triangles_normals, axis=0)
triangles_normals = triangles_normals.T
n_tri = tri_center_coord_mid.shape[0]
print(f"ROI midlayer: {n_tri} triangles")

mesh_simn = mesh_io.read_msh(os.path.abspath(args.mesh_msh))
roi_simnibs = [FemTargetPointCloud(center=tri_center_coord_mid, mesh=mesh_simn)]
roi_simnibs[-1].triangles_normals = triangles_normals

# Prepare the OnlineFEM solver (one factorization, one RHS per placement)
# ============================================================================
print("Preparing OnlineFEM ...")
ofem = OnlineFEM(
    mesh=mesh_simn,
    method="TMS",
    fn_coil=os.path.abspath(args.coil),
    roi=roi_simnibs,
    anisotropy_type=args.anisotropy,
    solver_options=args.solver,
    fn_logger=None,
    useElements=True,
    dataType=[1],
)

E = np.zeros((n_pos, n_tri, 3))
E_mag = np.zeros((n_pos, n_tri))
E_norm = np.zeros((n_pos, n_tri))
E_tan = np.zeros((n_pos, n_tri))

import time  # noqa: E402

print(f"Running {n_pos} FEM solves ...")
t_start = time.time()
for i_pos in range(n_pos):
    t_run = time.time()
    e = ofem.update_field(matsimnibs=pos_matrices[i_pos], didt=args.didt)
    E[i_pos] = e[0][0]
    E_mag[i_pos] = np.linalg.norm(e[0][0], axis=1)
    E_norm[i_pos] = -np.sum(e[0][0] * triangles_normals, axis=1)
    E_tan[i_pos] = np.sqrt(E_mag[i_pos] ** 2 - E_norm[i_pos] ** 2)
    print(f"  {i_pos + 1}/{n_pos} ({time.time() - t_run:.2f}s)")
print(f"FEM solving took {time.time() - t_start:.1f}s")

# Save results
# ============================================================================
with h5py.File(args.out, "w") as h5:
    h5.create_dataset("/E", data=E)
    h5.create_dataset("/E_mag", data=E_mag)
    h5.create_dataset("/E_norm", data=E_norm)
    h5.create_dataset("/E_tan", data=E_tan)
    h5.create_dataset("/matsimnibs", data=np.array(pos_matrices))
    h5.create_dataset("/target", data=target)
print(f"Saved {args.out} (E_mag shape {E_mag.shape})")
print("Done.")
