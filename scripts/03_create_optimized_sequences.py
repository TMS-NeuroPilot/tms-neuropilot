"""Create optimized coil-placement sequences from a precomputed E-field library.

Reads an ``e.hdf5`` (as written by ``02_create_roi_efield_library.py``) and produces one
coil sequence per selection algorithm, written as ``*.txt`` files with one
placement index per line (the format consumed by
``scripts/sort_coil_placements.py``). The selection schemes and their
reference publications:

- ``RANDOM``            uniformly random ordering (seeded)
                        — Numssen et al. 2021, "Efficient high-resolution TMS
                        mapping of the human motor cortex by nonlinear
                        regression", NeuroImage 245:118654 (random sampling
                        baseline for nonlinear-regression mapping)
- ``FPS``               farthest-point sampling in E-field space
                        — Schultheiss et al. 2025, "Efficient prospective
                        electric field-informed localization of motor cortical
                        targets of transcranial magnetic stimulation",
                        Imaging Neuroscience 3 (introduced FPS for TMS motor
                        mapping)
- ``D-Optimal``         greedy D-optimal selection, linear kernel
- ``D-Optimal(RBF)``    greedy D-optimal selection, RBF kernel (auto bandwidth)
                        — Qiu et al. 2026, "Optimal Pre-Experimental Coil
                        Sequence Selection for TMS Motor Mapping",
                        Imaging Neuroscience, DOI 10.1162/IMAG.a.1446 (casts
                        the sequence design as a subset-selection problem and
                        compares FPS against linear and RBF-kernelized
                        D-optimal objectives)

The FPS and D-optimal implementations come from
``pynibs.optimization.coil_sampling`` (pynibs dev branch).

Example:
    python scripts/03_create_optimized_sequences.py \
        --e-hdf5 data/ernie/efield/e.hdf5 \
        --n-stim 500 \
        --out-dir data/ernie/efield
"""

import argparse
import os

import h5py
import numpy as np
from pynibs.optimization.coil_sampling import doptimal_select, fps_select


def main():
    parser = argparse.ArgumentParser(
        description="Select coil-placement sequences (RANDOM / FPS / D-Optimal / "
                    "D-Optimal(RBF)) from a precomputed E-field library"
    )
    parser.add_argument("--e-hdf5", required=True,
                        help="E-field library HDF5 with an 'E_mag' dataset "
                             "(n_placements, n_roi_elements)")
    parser.add_argument("--n-stim", type=int, default=500,
                        help="Number of placements per sequence")
    parser.add_argument("--out-dir", default=None,
                        help="Directory for the *.txt sequences "
                             "(default: next to the e.hdf5)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (random ordering, FPS/D-optimal "
                             "tie-breaking)")
    parser.add_argument("--dataset", default="E_mag",
                        help="HDF5 dataset to select from (default: E_mag)")
    parser.add_argument("--normalize", default="none",
                        choices=["none", "row", "both"],
                        help="E-field normalization before D-optimal selection "
                             "(passed to pynibs doptimal_select)")
    parser.add_argument("--rbf-tau", default="auto",
                        help="RBF bandwidth: 'auto' (2 x median pairwise squared "
                             "distance) or a float")
    parser.add_argument("--rbf-ridge", type=float, default=0.0,
                        help="Ridge jitter for the RBF kernel path")
    parser.add_argument("--no-auto-sort", dest="auto_sort", action="store_false",
                        help="Skip the automatic travel-distance sorting of the "
                             "constructed sequences")
    parser.add_argument("--w-pos", type=float, default=2.0,
                        help="Travel-sort weight of the positional cost "
                             "(default: 2)")
    parser.add_argument("--w-ang", type=float, default=1.0,
                        help="Travel-sort weight of the coil-rotation cost "
                             "(default: 1)")
    args = parser.parse_args()

    out_dir = args.out_dir or os.path.dirname(os.path.abspath(args.e_hdf5))
    os.makedirs(out_dir, exist_ok=True)

    with h5py.File(args.e_hdf5, "r") as f:
        e_matrix = f[args.dataset][:]
    n_coil = e_matrix.shape[0]
    n_stim = min(args.n_stim, n_coil)
    if args.n_stim > n_coil:
        print(f"NOTE: library has only {n_coil} placements — "
              f"producing full-order sequences of length {n_stim}.")
    print(f"E-field library: {args.e_hdf5} ({e_matrix.shape}), "
          f"selecting/ordering {n_stim} placements")

    sequences = {}

    # RANDOM — seeded uniform ordering
    rng = np.random.default_rng(args.seed)
    sequences["RANDOM"] = rng.permutation(n_coil)[:n_stim]
    print("RANDOM done")

    # FPS — farthest-point sampling in E-field space
    idx, score = fps_select(e_matrix, n_stim, seed=args.seed)
    sequences["FPS"] = np.asarray(idx)
    print(f"FPS done (score trace {score.shape if score.size else 'empty'})")

    # D-Optimal — greedy max-volume, linear kernel
    idx, score = doptimal_select(e_matrix, n_stim, normalize=args.normalize,
                                 kernel="linear", seed=args.seed)
    sequences["D-Optimal"] = np.asarray(idx)
    print(f"D-Optimal (linear) done (log-det trace {score.shape})")

    # D-Optimal(RBF) — greedy max-volume in RBF-kernel space
    tau = None if args.rbf_tau == "auto" else float(args.rbf_tau)
    idx, score = doptimal_select(e_matrix, n_stim, normalize=args.normalize,
                                 kernel="rbf", tau=tau, ridge=args.rbf_ridge,
                                 seed=args.seed)
    sequences["D-Optimal(RBF)"] = np.asarray(idx)
    print(f"D-Optimal (RBF) done (log-det trace {score.shape})")

    for name, seq in sequences.items():
        fn = os.path.join(out_dir, f"ernie_coil_algo_{name}.txt")
        np.savetxt(fn, np.asarray(seq, dtype=int), fmt="%i")
        print(f"  {fn} ({len(seq)} placements, "
              f"{len(np.unique(seq))} unique)")

    # Auto-sort: reorder each constructed sequence for minimal robot travel
    # (position + rotation cost) with pynibs' opt_coil_placement_order, using
    # the matsimnibs stack stored in the e.hdf5.
    if args.auto_sort:
        import pynibs

        with h5py.File(args.e_hdf5, "r") as f:
            matsimnibs = f["matsimnibs"][:]
        matsimnibs = np.transpose(matsimnibs, (1, 2, 0))  # (n,4,4) -> (4,4,n)

        for name, seq in sequences.items():
            seq = np.asarray(seq, dtype=int)
            fn_hdf5 = os.path.join(out_dir, f"ernie_coil_algo_{name}_travel_sorted.hdf5")
            mats_opt, cost, route, cost_org = pynibs.coil.opt_coil_placement_order(
                matsimnibs, fn_hdf5,
                w_pos=args.w_pos, w_ang=args.w_ang,
                opt_indices=seq)
            route = seq[np.array(route)]
            fn_txt = os.path.join(out_dir, f"ernie_coil_algo_{name}_travel_sorted.txt")
            np.savetxt(fn_txt, route.astype(int), fmt="%i")
            print(f"  {name}: travel cost {np.round(cost_org, 2)} -> "
                  f"{np.round(cost, 2)}")
            print(f"  {fn_txt}")
            print(f"  {fn_hdf5}")

    print("Done.")


if __name__ == "__main__":
    main()
