# E-field library

The E-field library is the precomputed half of the mapping: for every coil
placement, the electric field it produces at every triangle of the ROI. The
controller reads one row per pulse, so a pulse is always associated with the
field of the pose that delivered it.

## What the file contains

`e.hdf5` from `scripts/02_create_roi_efield_library.py`:

| Dataset | Shape | Meaning |
|---|---|---|
| `E_mag` | `(n_placements, n_elements)` float | field magnitude per placement and ROI triangle, V/m |
| `E` | `(n_placements, n_elements, 3)` float | field vector, optionally |
| `E_norm` | `(n_placements, n_elements)` float | normal component, optionally |
| `E_tan` | `(n_placements, n_elements)` float | tangential component, optionally |
| `target` | `(3,)` float | the target position the search was centred on, mm |

The controller **requires** `E_mag` with shape `(placements, elements)`. Extra
datasets are ignored by the regression but useful for inspection.

!!! note "Large files"
    A 500-placement search on 15 000 ROI triangles is about 350 MB as float64
    (`500 × 15 000 × 8` bytes for `E_mag` alone). Keep one library per subject
    and ROI; do not commit them to the repository.

## Building it

```bash
python scripts/02_create_roi_efield_library.py \
    --mesh-msh  data/<subj>/mesh/m2m_<subj>/<subj>.msh \
    --roi-hdf5  data/<subj>/mesh/roi/midlayer_m1s1pmd/geo.hdf5 \
    --roi-idx   midlayer_m1s1pmd \
    --coil      /path/to/MagVenture_MCF-B65.ccd \
    --target    -37.0 -21.0 58.0 \
    --out       data/<subj>/efield/e.hdf5
```

| Flag | Default | Meaning |
|---|---|---|
| `--mesh-msh` | required | SimNIBS FEM mesh |
| `--roi-hdf5`, `--roi-idx` | required, `midlayer_m1s1pmd` | ROI surface and its display name |
| `--coil` | required | coil model `.ccd` |
| `--target` | required | search centre, mm, SimNIBS space |
| `--n-placements` | 500 | how many placements to keep |
| `--search-radius` | 20.0 | mm around the target |
| `--search-angle` | 180.0 | handle rotation range, degrees |
| `--angle-resolution` | 7.5 | step of the rotation search, degrees |
| `--spatial-resolution` | 3.0 | step of the position search, mm |
| `--distance` | 1.0 | coil-to-scalp distance, mm |
| `--target-radius` | 1.0 | target tolerance, mm |
| `--anisotropy` | `scalar` | `scalar` or `vn` (needs a DTI tensor) |
| `--solver` | `pardiso` | FEM solver |
| `--didt` | `1e6` | dI/dt used to scale the field, A/s |
| `--out` | `e.hdf5` | output path |

The script runs one FEM solve per placement. On a workstation expect **minutes
to hours** depending on mesh size, placement count and solver. It prints
progress per placement and flushes on purpose; run it with `PYTHONUNBUFFERED=1`
if you redirect the output.

!!! tip "Reduce before you solve"
    The field patterns of neighbouring placements are highly correlated. A
    D-optimal or FPS subset of 100–200 placements often constrains the
    regression as well as 500 and takes a fraction of the time. See
    [Coil placements](prepare/placements.md).

## What the controller checks

When you select the library on the Project page:

- the file is HDF5 and has an `E_mag` dataset;
- `E_mag` is two-dimensional with at least one row and one column;
- the dtype is numeric;
- the shape is reported in the log: `E-Matrix loaded. Shape: (500, 15168)`;
- if the same file has a `matsimnibs` dataset, it is kept for the
  placements/library consistency check.

When both the E-field library and the placements file are loaded, the
controller compares the coil matrices and warns when the library was computed
for different placements:

```text
[WARN] The E-field library was computed for different coil placements
       than the loaded placement file.
```

This is the most common silent error: a sorted or subsampled placement file
paired with an unsorted full library makes every pulse use the wrong field.

## Online instead of precomputed

The online mode replaces this file: the field is solved for the realised coil
pose at pulse time by `OnlineFEMManager` (SimNIBS + PETSc). It needs:

- the `.msh` head mesh,
- the ROI surface,
- the coil model,
- the solver settings (`ONLINE_FEM_SOLVER`, `ONLINE_FEM_ANISOTROPY`).

No `e.hdf5`, no placements library. The trade-off is time: the solver needs
about a minute to warm up, then a solve per pulse. See
[E-field modes](run/efield-modes.md).

## Validating a library by eye

Load the project in the simulator and open **Cortical results**. The placement
overlay colours each pulse by its MEP; the map colours each triangle by R². A
library whose rows are misaligned with the placements usually produces a
plausible-looking but spatially scrambled map — check the warning line in the
log first, not the picture.

## Next

- [Coil placements and target order](prepare/placements.md)
- [E-field modes](run/efield-modes.md)
