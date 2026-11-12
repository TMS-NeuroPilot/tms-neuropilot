#!/usr/bin/env python3
"""Validate a precomputed E-field library with the surrogate estimator.

Uses the same protocol as the offline assessment: a random 80/20 pose split
and a leave-positions-out split. Reports field error over all ROI elements,
the target-element error (optional), and how the domain guard classifies the
test poses. No SimNIBS or EfieldInterpolation dependency.

Example:
    python scripts/03_validate_efield_surrogate.py \
        --library /tmp/opencode/dense20/e.hdf5 --target-element 13980
"""
import argparse
from pathlib import Path
import sys
import time
import warnings

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from neuropilot.controller.EFieldSurrogate import EFieldSurrogate, read_library  # noqa: E402


def _percentile(values, q=50):
    return float(np.percentile(values, q)) if values else float("nan")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True,
                        help="e.hdf5 written by 02_create_roi_efield_library.py")
    parser.add_argument("--components", type=int, default=20)
    parser.add_argument("--holdout", type=float, default=0.15,
                        help="fraction of positions held out spatially")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--target-element", type=int, default=-1,
                        help="ROI element index for the target-scalar error")
    parser.add_argument("--max-position-mm", type=float, default=None)
    parser.add_argument("--max-rotation-deg", type=float, default=None)
    parser.add_argument("--position-search-mm", type=float, default=None)
    parser.add_argument("--rotation-search-deg", type=float, default=None)
    args = parser.parse_args()

    e_mag, mats = read_library(args.library)
    translations = np.round(mats[:, :3, 3], 4)
    positions, inverse = np.unique(translations, axis=0, return_inverse=True)
    print(f"{args.library}: {len(e_mag)} poses, {e_mag.shape[1]} elements, "
          f"{len(positions)} positions")

    overrides = dict(
        n_components=args.components,
        max_position_distance_mm=args.max_position_mm,
        max_rotation_distance_deg=args.max_rotation_deg,
        position_search_mm=args.position_search_mm,
        rotation_search_deg=args.rotation_search_deg,
    )
    full = EFieldSurrogate.from_arrays(e_mag, mats, **overrides)
    print(f"  k={full.n_components}  guard {full.max_position_distance_mm:.2f} mm / "
          f"{full.max_rotation_distance_deg:.1f} deg  search "
          f"{full.position_search_mm:.2f} mm / {full.rotation_search_deg:.1f} deg")

    rng = np.random.default_rng(args.seed)
    order = rng.permutation(len(e_mag))
    n_test = max(1, int(round(0.2 * len(e_mag))))
    splits = {"random 80/20": (order[n_test:], order[:n_test])}

    n_hold = max(1, int(round(args.holdout * len(positions))))
    held_positions = rng.choice(len(positions), n_hold, replace=False)
    held = np.isin(inverse, held_positions)
    splits[f"leave-{n_hold}-positions-out"] = (np.flatnonzero(~held),
                                               np.flatnonzero(held))

    for label, (train, test) in splits.items():
        estimator = EFieldSurrogate.from_arrays(
            e_mag[train], mats[train], **overrides)
        errors, target_errors, inside, outside, timings = [], [], [], [], []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for i in test:
                started = time.perf_counter()
                field, check = estimator.compute_e_field(mats[i])
                timings.append(time.perf_counter() - started)
                errors.append(100.0 * np.linalg.norm(field - e_mag[i])
                              / np.linalg.norm(e_mag[i]))
                if args.target_element >= 0:
                    target_errors.append(
                        100.0 * abs(field[args.target_element]
                                    - e_mag[i, args.target_element])
                        / abs(e_mag[i, args.target_element]))
                (inside if check.inside else outside).append(errors[-1])

        print(f"\n== {label}: train {len(train)}, test {len(test)}")
        print(f"  field median {np.median(errors):5.2f}%  "
              f"mean {np.mean(errors):5.2f}%")
        if target_errors:
            print(f"  target median {np.median(target_errors):5.2f}%  "
                  f"mean {np.mean(target_errors):5.2f}%")
        print(f"  guard inside n={len(inside)} median {_percentile(inside):5.2f}%"
              f"  outside n={len(outside)} median {_percentile(outside):5.2f}%")
        print(f"  {1000 * np.mean(timings):5.2f} ms/pose")


if __name__ == "__main__":
    main()
