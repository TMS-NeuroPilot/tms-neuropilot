# E-field library

The E-field library is the precomputed half of the mapping: for every coil
placement, the electric field it produces at every triangle of the ROI. The
controller reads one row per pulse, so a pulse is always associated with the
field of the pose that delivered it. The same file is the training data for
the surrogate E-field estimator — the interpolation method of
[Grosshagauer et al., 2025](https://doi.org/10.1016/j.brs.2025.102990) — and
the source for the ParaView field comparisons.

## What the file contains

`e.hdf5` from `scripts/02_create_roi_efield_library.py`:

| Dataset | Shape | Meaning |
|---|---|---|
| `E_mag` | `(n_placements, n_elements)` float | field magnitude per placement and ROI triangle, V/m at 100 % stimulator output |
| `E` | `(n_placements, n_elements, 3)` float | field vector, optionally |
| `E_norm` | `(n_placements, n_elements)` float | normal component, optionally |
| `E_tan` | `(n_placements, n_elements)` float | tangential component, optionally |
| `target` | `(3,)` float | the target position the search was centred on, mm |

The controller **requires** `E_mag` with shape `(placements, elements)`. Extra
datasets are ignored by the regression but useful for inspection.

!!! note "Large files"
    A 500-placement library with all four datasets is roughly 350 MB as
    float64; a dense surrogate library (some thousands of placements) is
    several GB. Keep one library per subject and ROI. The bundled example
    subject is stored through Git LFS; generated libraries for study subjects
    should not be committed.

## Building it

The script centres the search automatically: without `--target` it uses the
ROI centroid, and without `--search-radius` it derives the radius from the ROI
extent (the largest distance from the target to an ROI triangle centre) plus a
10 mm motion margin. Both can be set explicitly when a session needs something
else.

```bash
python scripts/02_create_roi_efield_library.py \
    --mesh-msh  data/<subj>/mesh/m2m_<subj>/<subj>.msh \
    --roi-hdf5  data/<subj>/mesh/m2m_<subj>/<subj>.hdf5 \
    --roi-idx   midlayer_m1s1pmd \
    --coil      /path/to/MagVenture_MCF-B65.ccd \
    --out       data/<subj>/efield/e.hdf5
```

| Flag | Default | Meaning |
|---|---|---|
| `--mesh-msh` | required | SimNIBS FEM mesh |
| `--roi-hdf5`, `--roi-idx` | required, `midlayer_m1s1pmd` | pynibs mesh HDF5 with `roi_surface/<idx>` |
| `--coil` | required | coil model `.ccd` |
| `--target` | ROI centroid | search centre, mm, SimNIBS space |
| `--search-radius` | ROI extent + `--margin` | mm around the target |
| `--margin` | 10.0 | extra radius for the automatic search radius, mm |
| `--n-placements` | 500 | placements to keep; `0` keeps the full grid |
| `--search-angle` | 180.0 | handle rotation range, degrees |
| `--angle-resolution` | 7.5 | step of the rotation search, degrees |
| `--spatial-resolution` | 3.0 | step of the position search, mm |
| `--distance` | 1.0 | coil-to-scalp distance, mm |
| `--target-radius` | 1.0 | target tolerance, mm |
| `--anisotropy` | `scalar` | `scalar` or `vn` (needs a DTI tensor) |
| `--solver` | `pardiso` | FEM solver |
| `--dadt-at` | `nodes` | `nodes` (fast) or `elements` (reference) |
| `--didt` | `1e6` | dI/dt used to scale the field, A/s |
| `--out` | `e.hdf5` | output path |

The script runs one FEM solve per placement. With the default node-based
dA/dt a solve takes ~2–3 s on the ernie mesh (the `elements` reference path
~4× longer). Expect minutes for a 500-placement library and hours for a dense
surrogate grid. Progress is printed per placement and flushed on purpose; run
with `PYTHONUNBUFFERED=1` when redirecting the output.

The output records how it was produced: `target_source`, `roi_radius_mm`,
`search_radius_mm`, `margin_mm`, the grid resolutions, plus the mesh, ROI,
coil and solver settings. A library can always be traced back to the run that
produced it.

### Recipes

**Precomputed library** (the default): a 3 mm / 7.5° grid subsampled to 500
placements. This is the file the *Precomputed* E-field mode loads.

**Surrogate library** (dense grid): no subsampling, 4 mm spacing and 15°
rotations, covering the ROI plus the motion margin. This is the training data
for the E-field surrogate — the interpolation method of
[Grosshagauer et al., 2025](https://doi.org/10.1016/j.brs.2025.102990)
([EfieldInterpolation](https://github.com/fMRIat/EfieldInterpolation)) — and
for the ParaView comparison; several GB and a few hours are normal. The
original a-priori step uses APSim (the auxiliary dipole method) and stores the
field at the target; this library is computed with the OnlineFEM solver and
keeps every ROI triangle, which is what the per-element interpolation and the
R² map need. It is loaded through the **Interpolated** E-field mode
(`surrogate_library_path` in the project):

```bash
python scripts/02_create_roi_efield_library.py \
    ... --spatial-resolution 4 --angle-resolution 15 --n-placements 0
```

Validate it on held-out placements (field error, target error, domain guard):

```bash
python scripts/03_validate_efield_surrogate.py \
    --library data/<subj>/efield/e_surrogate.hdf5 --target-element 13980
```

and export FEM-versus-surrogate time series for ParaView:

```bash
python scripts/04_export_efield_vtk_series.py \
    --library data/<subj>/efield/e_surrogate.hdf5 \
    --roi-hdf5 data/<subj>/mesh/m2m_<subj>/<subj>.hdf5 \
    --out-dir efield_vtk --n-steps 40
```

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
