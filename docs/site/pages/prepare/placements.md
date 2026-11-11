# Coil placements and target order

The placements file says *where the coil can go*. The target-order file says
*where it goes next*. Both are index-aligned with the E-field library, which is
what keeps the regression consistent.

## The placements file

`search_positions.hdf5` from SimNIBS `TMSoptimize` (or the group's wrapper):

| Dataset | Shape | Meaning |
|---|---|---|
| `matsimnibs` | `(4, 4, n)` float | one coil matrix per placement, mm, SimNIBS space |
| `centers` | `(n, 3)` float, optional | coil centre per placement |
| `m0`, `m1`, `m2` | `(n, 3)` float, optional | coil axes, for inspection |

The controller reads **only** `matsimnibs`. Each matrix follows the convention
in [Units and frames](start/units.md): translation is the stimulation point,
rotation columns are the coil axes.

!!! warning "Order is meaning"
    Row *i* of `matsimnibs` is column *i* of `E_mag`. If you sort, subsample or
    filter the placements, you must apply the same reordering to the E-field
    library. `sort_coil_placements.py` exists for exactly this reason — see
    below.

## The target-order file

A plain text file with one integer per line:

```text
44
477
391
156
22
```

Rules:

- indices into the placements file, **0-based** (the first placement is `0`);
- one target per line; whitespace and blank lines are fine;
- values must be integers and `0 <= index < n_placements`;
- the file is validated when you load it, not when you press Start.

An invalid file is rejected with a message naming the offending index:

```text
Target order ernie.txt references target 500, but only 500 placements exist.
```

If you do not load an order file, the controller stimulates **all placements in
file order** — useful for a first test, slow for a real session.

!!! tip "Repeats are allowed"
    The order file may repeat an index. A protocol that alternates between two
    hot spots, or returns to the best target at the end, is just a longer list.

## Choosing an order

`scripts/03_create_optimized_sequences.py` selects a subset of placements that
constrains the regression well and writes an order file:

```bash
python scripts/03_create_optimized_sequences.py \
    --e-hdf5 data/<subj>/efield/e.hdf5 \
    --n-stim 200 \
    --out-dir data/<subj>/coil_path
```

| Flag | Default | Meaning |
|---|---|---|
| `--e-hdf5` | required | the E-field library to select from |
| `--n-stim` | 500 | number of pulses to plan |
| `--out-dir` | next to the library | where the order files are written |
| `--seed` | 42 | RNG seed for the random baseline |
| `--dataset` | `E_mag` | which field dataset to use |
| `--normalize` | `none` | feature normalisation before selection |
| `--rbf-tau`, `--rbf-ridge` | `auto`, `0.0` | RBF kernel width / ridge for D-optimal |
| `--w-pos`, `--w-ang` | 2.0, 1.0 | travel cost weights (position mm, angle deg) |
| `--no-auto-sort` | off | keep the selection order instead of travel-sorting |

It writes one file per strategy (`RANDOM`, `FPS`, `D-Optimal`, …) plus a
`*_travel_sorted.txt` variant. **Use the travel-sorted file**: the robot spends
most of its time moving between targets, and a spatially coherent order roughly
halves the session duration.

## Sorting placements for travel

If you already have a placement file and an order, reorder both together:

```bash
python scripts/sort_coil_placements.py \
    --matsimnibs data/<subj>/efield/search_positions.hdf5 \
    --coil-seq   data/<subj>/coil_path/selected.txt \
    --out-dir    data/<subj>/coil_path
```

The script writes a new `matsimnibs` file, the matching order file and an XDMF
for visual inspection. Use the outputs as the project's `targets_file` and
`target_order_fn`; do not mix the sorted order with the unsorted library.

## Common mistakes

| Symptom | Cause |
|---|---|
| `references target N, but only M placements exist` | order file is 1-based or from another subject |
| `contains non-integer entries` | a header line, a comma-separated list or a float |
| every pulse uses the same field | order file lists one index repeatedly |
| map looks spatially scrambled | sorted placements paired with an unsorted library |
| robot takes a long path between targets | raw algorithm order instead of `*_travel_sorted.txt` |
| `Coil at target` never arrives | placement is outside the robot's reach or collides |

## Next

- [EMG channels and MEP windows](prepare/emg.md)
- [The project file](prepare/project.md)
