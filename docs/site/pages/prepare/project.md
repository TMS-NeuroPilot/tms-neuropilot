# The project file

A project is one YAML file per subject and session. It points at the subject's
files and carries the stimulation and mapping defaults. **Load** and **Save** on
the Project page read and write it; everything in it can also be edited by hand.

## An annotated project

```yaml
# One subject, one session.
project_name: NP001_M1_left

# Subject files (absolute paths; ~ is not expanded).
mesh_head_path: /data/NP001/mesh/m2m_NP001/NP001.msh
mesh_RIO_path: /data/NP001/mesh/roi/midlayer_m1s1pmd/geo.hdf5
coil_path: /opt/simnibs/resources/coil_models/Drakaki_BrainStim_2022/MagVenture_MCF-B65_new.ccd

# Target library and the order in which to visit it.
targets_file: /data/NP001/efield/search_positions.hdf5
target_order_fn: /data/NP001/coil_path/selected_travel_sorted.txt

# Precomputed E-field library. Not needed for the online mode.
e_field_path: /data/NP001/efield/e.hdf5

# EMG channel sources and the results table.
emg_config_fn: /data/NP001/emg_channels.yaml
results_fn: /data/NP001/results/NP001_M1_left.csv

# Mapping and stimulation defaults.
fit_fun: Linear
map_elms: 1
stimulator_amplitude: 20
stimulator_waveform: Biphasic
n_repetitions: 1
minium_isi: 4
default_speed: 40
tuning_speed: 10

# Travels with the subject: Precomputed or Online.
efield_mode: Precomputed
```

## Every key

| Key | Type | Default | Meaning |
|---|---|---|---|
| `project_name` | string | file name | label shown in the title bar and used as the default save name |
| `mesh_head_path` | path | none | SimNIBS `.msh` or HDF5 head mesh |
| `mesh_RIO_path` | path | none | ROI surface HDF5 (`geo.hdf5`) |
| `coil_path` | path | none | SimNIBS `.ccd` coil model |
| `targets_file` | path | none | placements HDF5 with `matsimnibs` |
| `target_order_fn` | path | none | target-order text file; all placements when absent |
| `e_field_path` | path | none | precomputed E-field library (`E_mag`); unused online |
| `emg_config_fn` | path | none | channel-source YAML |
| `results_fn` | path | none | CSV written when the session finishes |
| `fit_fun` | string | `Linear` | one of the nine fit shapes; see [Analysis and fits](results/analysis.md) |
| `map_elms` | int | `1` | analyse every n-th ROI element (subsampling) |
| `stimulator_amplitude` | int | `20` | % MSO |
| `stimulator_waveform` | string | `Biphasic` | `Biphasic` or `Monophasic` |
| `n_repetitions` | int | `1` | pulses per target |
| `minium_isi` | int | `4` | minimum inter-stimulus interval, seconds |
| `default_speed` | int | `40` | robot speed while travelling, % |
| `tuning_speed` | int | `10` | robot speed near the head, % |
| `efield_mode` | string | absent | `Precomputed` or `Online`; carried with the subject |

!!! warning "Two spellings are historical"
    `mesh_RIO_path` (capital RIO) and `minium_isi` (missing "m") are the keys
    the code has used since the first version. They are what existing project
    files contain, so they are what the GUI reads and writes. Renaming them
    would invalidate every saved project; treat them as the format, not as
    typos to fix.

## Loading

- **Project › Load** accepts `*.yaml` and `*.yml`.
- A file that is not a mapping (empty, a list, a binary file, a corrupt YAML) is
  refused with a message; the current project stays loaded and usable.
- Keys that cannot be coerced to the widget type are skipped with a warning;
  the rest of the file still applies.
- Loading is refused while a mapping is running — swapping the library or the
  subsampling under a live analysis would change what the map means.
- After a successful load the path is remembered and restored on the next start
  (`~/.neuropilot/last_session.yaml`).

## Saving

- **Project › Save** writes plain YAML, in the order shown above.
- An empty `project_name` adopts the file name.
- `.yaml` is appended when the dialog returns a name without an extension.
- A failed write (folder deleted, permission denied) leaves the project marked
  as unsaved; pick another location.

## Paths

Use **absolute paths**. The four components run with different working
directories (the controller runs from its package directory so that Qt can
import the custom widgets), so a relative path resolves differently depending on
who opens it. `~` is not expanded in project files.

For a portable project, keep the whole subject folder together and generate the
YAML with a small script that prefixes the folder — the demo-data generator does
exactly that.

## The file is the session record

The project file plus the results CSV are the record of a session. The CSV holds
what happened (poses, amplitudes, MEPs, E-field mode per pulse); the YAML holds
what was planned. Keep both, and keep the E-field library they refer to: without
it the map cannot be recomputed.

## Next

- [Study profiles](prepare/study.md) — the protocol layer above the project.
- [Project page](gui/project.md) — the GUI view of these keys.
