"""Create optimized coil-placement sequences from a precomputed E-field library.

Reads an ``e.hdf5`` (as written by ``roi_efield_library.py``) and produces one
coil sequence per selection algorithm, written as ``*.txt`` files with one
placement index per line (the format consumed by
``scripts/sort_coil_placements.py``):

- ``RANDOM``            uniformly random ordering (seeded)
- ``FPS``               farthest-point sampling in E-field space
- ``D-Optimal``         greedy D-optimal selection, linear kernel
- ``D-Optimal(RBF)``    greedy D-optimal selection, RBF kernel (auto bandwidth)

The FPS and D-optimal implementations come from
``pynibs.optimization.coil_sampling`` (pynibs dev branch).

Example:
    python scripts/create_optimized_sequences.py \
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

    print("Done.")


if __name__ == "__main__":
    main()
