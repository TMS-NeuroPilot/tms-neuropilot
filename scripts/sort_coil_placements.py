"""Sort coil-placement sequences for minimal robot travel.

Reads a coil-placement library (``matsimnibs`` dataset in an HDF5 file, e.g.
the ``search_positions.hdf5`` written by ``roi_efield_library.py``) and a set
of coil sequences (``*.txt`` files with one placement index per line, as
produced by the offline sequence optimizers). Each sequence is reordered so
the robot travels the shortest possible path between consecutive
placements — trading off positional distance and coil rotation angle
(``--w-pos`` / ``--w-ang``) — via ``pynibs.coil.opt_coil_placement_order``.

For every input sequence ``<name>.txt`` two files are written into the
output directory: ``sorted_<name>.txt`` (the reordered placement indices)
and ``sorted_<name>.hdf5`` (the reordered matsimnibs stack, as stored by
pynibs).

Example:
    python scripts/sort_coil_placements.py \
        --matsimnibs data/ernie/efield/search_positions.hdf5 \
        --coil-seq data/ernie/efield/sequences \
        --out-dir data/ernie/efield/sequences_sorted
"""

import argparse
import glob
import os

import h5py
import numpy as np
import pynibs


def main():
    parser = argparse.ArgumentParser(
        description="Reorder coil-placement sequences for minimal robot travel"
    )
    parser.add_argument("--matsimnibs", required=True,
                        help="HDF5 file with a '/matsimnibs' (4, 4, N) dataset "
                             "of the coil-placement library")
    parser.add_argument("--coil-seq", required=True,
                        help="Directory with coil-sequence *.txt files "
                             "(one placement index per line), or a single "
                             "*.txt file")
    parser.add_argument("--out-dir", required=True,
                        help="Directory for the sorted sequences")
    parser.add_argument("--w-pos", type=float, default=2.0,
                        help="Weight of the positional travel cost (default: 2)")
    parser.add_argument("--w-ang", type=float, default=1.0,
                        help="Weight of the coil-rotation cost (default: 1)")
    parser.add_argument("--dataset", default="/matsimnibs",
                        help="HDF5 dataset path of the placement matrices")
    args = parser.parse_args()

    seq_files = (sorted(glob.glob(os.path.join(args.coil_seq, "*.txt")))
                 if os.path.isdir(args.coil_seq)
                 else [args.coil_seq])
    if not seq_files:
        parser.error(f"No *.txt coil sequences found in {args.coil_seq}")

    os.makedirs(args.out_dir, exist_ok=True)

    with h5py.File(args.matsimnibs, "r") as f:
        matsimnibs = f[args.dataset][:]
    if matsimnibs.ndim == 2:
        matsimnibs = matsimnibs[:, :, np.newaxis]
    n_placements = matsimnibs.shape[2]
    print(f"Placement library: {args.matsimnibs} ({n_placements} placements)")

    for seq_fn in seq_files:
        name = os.path.splitext(os.path.split(seq_fn)[1])[0]
        opt_indices = np.loadtxt(seq_fn).astype(int)
        print(f"\nSequence {seq_fn}: {len(opt_indices)} placements "
              f"(indices {opt_indices.min()}..{opt_indices.max()})")
        if opt_indices.max() >= n_placements:
            print(f"  WARNING: index out of range for a library of "
                  f"{n_placements} placements — skipping this sequence")
            continue

        fn_out_hdf5 = os.path.join(args.out_dir, f"sorted_{name}.hdf5")
        mats_opt, cost, route, cost_org = pynibs.coil.opt_coil_placement_order(
            matsimnibs, fn_out_hdf5,
            w_pos=args.w_pos, w_ang=args.w_ang,
            opt_indices=opt_indices)
        route = opt_indices[np.array(route)]

        print(f"  Cost original: {np.round(cost_org, 2)}, "
              f"cost sorted: {np.round(cost, 2)}")
        fn_out_txt = os.path.join(args.out_dir, f"sorted_{name}.txt")
        np.savetxt(fn_out_txt, np.array(route).astype(int), fmt="%i")
        print(f"  -> {fn_out_txt}")
        print(f"  -> {fn_out_hdf5}")

    print("\nDone.")


if __name__ == "__main__":
    main()
