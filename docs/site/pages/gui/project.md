# Project page

The **Project** page loads and saves the subject's YAML and shows every file the
session needs. It is the first page to fill in, and the one to re-check before
pressing Start.

<figure>
  <img src="assets/screenshots/project-demo.png" alt="The Project page with all file rows filled by the demo dataset.">
  <figcaption>The Project card (name, Load, Save) and the Project files card.
  Each row has a path field and a browse button.</figcaption>
</figure>

## Project card

| Control | Behaviour |
|---|---|
| **Project name** | label used in the title bar and as the default file name |
| **Load** | opens a YAML file; refuses non-mappings and corrupt files |
| **Save** | writes the current project; appends `.yaml` when the name has no extension |

An unsaved change marks the title with an asterisk. Loading is refused while a
mapping is running; saving is always allowed.

## Project files card

| Row | File | Required | What breaks without it |
|---|---|---|---|
| **Head mesh** | SimNIBS `.msh` or HDF5 | no | no 3-D anatomy; the online solver cannot run |
| **ROI surface** | HDF5 `geo.hdf5` | for a map | no R² map, no mesh to paint |
| **Target order** | text, one index per line | no | every placement is visited, in file order |
| **Coil placements** | HDF5 `matsimnibs` | yes | no target poses |
| **E-Field library** | HDF5 `E_mag` | precomputed mode | Start stays disabled |
| **Coil model** | SimNIBS `.ccd` | online mode | the online solver cannot run |
| **EMG channels** | YAML `sources` | no | channels have no cortical source |
| **Results file** | CSV path | yes | the session cannot be written |

Each row is validated when you leave the field: a missing or malformed file is
reported in the tooltip and in the log, and the path is kept so you can fix it
without retyping.

!!! tip "Browse buttons"
    Every row's browse button opens the dialog in the folder of the *current*
    value, or in your home folder. The head-mesh dialog filters for `.msh` and
    `.hdf5`; the coil dialog starts in the SimNIBS coil library.

## Reading the page at a glance

- A filled row is a file the controller has accepted.
- A red hint under a row means the file is missing or failed validation.
- The *Results file* row shows where the CSV will be written; its folder must
  exist.
- The **Config › Subject** tab mirrors this page read-only, with the same
  save/load shortcuts (see [Config page](gui/config.md)).

## Load semantics

- Only `*.yaml` / `*.yml` are offered.
- The loader accepts a partial file: keys that are absent keep their current
  value.
- Values of the wrong type are skipped with a warning; one bad key does not
  block the rest.
- After a successful load the path is restored on the next start.
- The E-field mode stored in the file is applied (if that mode is available).

## Save semantics

```yaml
project_name: NP001_M1_left
mesh_head_path: /data/NP001/mesh/m2m_NP001/NP001.msh
...
efield_mode: Precomputed
```

The full key list, with types and defaults, is in
[The project file](prepare/project.md).

## Common mistakes

| Symptom | Cause |
|---|---|
| *Load* shows "expected a mapping of settings" | the file is a list, a string or empty |
| the mesh row stays red | the path points at a folder or a non-HDF5/non-msh file |
| Start disabled after loading | no E-field library loaded in precomputed mode |
| paths work on your PC but not the lab PC | relative paths and a different working directory |
| the map is empty although pulses ran | ROI surface missing or element count mismatch |

## Next

- [Connections page](gui/connections.md)
- [The project file](prepare/project.md)
