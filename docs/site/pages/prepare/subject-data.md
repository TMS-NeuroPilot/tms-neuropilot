# Subject data

A session needs five artefacts for one subject. This page says what each one is,
which script produces it, and what NeuroPilot checks when it loads it.

<figure>
  <img src="assets/diagrams/subject-pipeline.svg" alt="The subject-data pipeline: MRI to head model, mesh to ROI surface, placements to E-field library, and the order and EMG files that complete a project.">
  <figcaption>Four artefacts and two small configuration files. The head model
  is shared by every step; the E-field library is the only artefact the online
  mode can replace.</figcaption>
</figure>

## The artefacts

| Artefact | File | Produced by | Used for |
|---|---|---|---|
| Head mesh | `m2m_<subj>/<subj>.msh` (or an HDF5 mesh) | SimNIBS `charm` | the 3-D view, the robot's head model |
| ROI surface | `geo.hdf5` | ROI extraction from the midlayer surface | the map: one R² per triangle |
| Coil placements | `search_positions.hdf5` | SimNIBS `TMSoptimize` | the targets the loop visits |
| E-field library | `e.hdf5` | `scripts/02_create_roi_efield_library.py` | per-pulse E-field rows |
| Target order | `*.txt` | `scripts/03_create_optimized_sequences.py` | which placement to stimulate, in which order |

Two more small files complete a project: the **EMG channel sources**
(`*.yaml`) and the **coil model** (`*.ccd`).

## 1. Head model

NeuroPilot reads the SimNIBS head mesh directly:

```text
m2m_<subj>/<subj>.msh
```

Create it with SimNIBS `charm` (the group's `scripts/01_create_head_model.py`
wraps this for a subject HDF5):

```bash
python scripts/01_create_head_model.py \
    -s data/<subj>/<subj>.hdf5 \
    -m mesh_<subj>_lincc \
    --charm_ini scripts/configs/charm_410.ini
```

The script runs `charm` (segmentation + meshing) and writes the `m2m_<subj>`
folder next to the subject's MRI. See the SimNIBS documentation for `charm`
options; `--charm_cmd_params` forwards extra flags, `--mesh` skips segmentation
when you already have one.

!!! warning "Size"
    A full head mesh has 1–2 million triangles and is 150–350 MB. The 3-D view
    decimates it for display, but the file must stay complete for the FEM.

An HDF5 mesh with `mesh/nodes/node_coord` and
`mesh/elm/triangle_number_list` is also accepted; the demo dataset uses that
form.

## 2. ROI surface

The **region of interest** is the cortical surface patch the map is computed on.
It is a triangle mesh in an HDF5 file:

| Dataset | Shape | Meaning |
|---|---|---|
| `mesh/nodes/node_coord` | `(N, 3)` float | vertex positions, mm, SimNIBS space |
| `mesh/elm/triangle_number_list` | `(M, 3)` int, 0-based | triangle vertex indices |
| `mesh/elm/tri_tissue_type` | `(M, 1)` int, optional | per-triangle label, used for colouring |

The example subject uses a *midlayer* surface (`midlayer_m1s1pmd`): a surface
halfway between the grey/white boundary and the pial surface, which samples the
field where the pyramidal cells sit.

!!! note "Element count is a contract"
    The number of E-field columns must equal `M`. If you change the ROI, every
    E-field library computed for the old ROI is invalid. NeuroPilot reports the
    mismatch instead of silently using the first columns.

## 3. Coil model

A SimNIBS `.ccd` file (optionally `.ccd.nii.gz`). The file defines the coil
geometry used by the FEM; it does not affect where the robot moves. Use the
model that matches the physical coil — a B65 model for a B65 coil.

The file dialog starts in the SimNIBS coil library
(`simnibs/resources/coil_models/`).

## 4. EMG channel sources

The channel **names and count** come from `EMG_CHANNELS` in `.env`. The
**cortical source** of each channel comes from a small YAML, one entry per
channel, assigned positionally:

```yaml
sources:
  - element_id: 5208        # FDI: index into the ROI triangles
  - element_id: 5165        # APB
  - xyz: [-16.2, 14.6, 61.9]  # ADM: position in mm; nearest triangle is used
```

`element_id` is the row index of the E-field column, so it must be
`< n_elements`. `xyz` is projected onto the nearest ROI vertex and the
projection distance is printed, which makes it a safe alternative when you know
the anatomy but not the index.

See [EMG channels and MEP windows](prepare/emg.md) for the full format.

## 5. Results file

A path to a CSV the controller appends to during the session. It is created if
missing; the folder must exist and be writable. The columns are documented in
[Export and data formats](results/export.md).

## Sanity checks before the session

```bash
python - <<'PY'
import h5py, numpy as np
roi = "roi/geo.hdf5"; ef = "efield/e.hdf5"; pl = "placements.hdf5"
with h5py.File(roi) as f:
    n_el = f["mesh/elm/triangle_number_list"].shape[0]
with h5py.File(ef) as f:
    E = f["E_mag"]
    print("E_mag", E.shape, "elements", E.shape[1])
with h5py.File(pl) as f:
    print("placements", f["matsimnibs"].shape[2])
print("ROI triangles", n_el)
PY
```

- [ ] `E_mag.shape[1] == ROI triangles`
- [ ] `E_mag.shape[0] == matsimnibs.shape[2]`
- [ ] every target-order index is `0 <= i < n_placements`
- [ ] `EMG_CHANNELS` has as many names as the source YAML has entries
- [ ] the mesh opens in the Cortical results page

## Where the scripts live

| Script | Purpose |
|---|---|
| `scripts/01_create_head_model.py` | run `charm`, produce `m2m_<subj>/<subj>.msh` |
| `scripts/02_create_roi_efield_library.py` | place the coil over the target, solve the FEM for every placement, write `e.hdf5` |
| `scripts/03_create_optimized_sequences.py` | choose a subset/order of placements (random, FPS, D-optimal) |
| `scripts/sort_coil_placements.py` | reorder placements for minimal robot travel |
| `scripts/make_tissue_stls.py`, `msh2vtk_surf.py` | surface extraction, for inspection |

The next two pages cover the last four in detail.

## Next

- [E-field library](prepare/efield-library.md)
- [Coil placements and target order](prepare/placements.md)
- [EMG channels and MEP windows](prepare/emg.md)
