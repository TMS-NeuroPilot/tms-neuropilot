# Quick start

From a fresh clone to a running simulated mapping session. No hardware and no
subject data are needed. The installation is one command; the manual recipe,
the Windows notes and the optional components are one link away.

!!! abstract "What you will have at the end"
    The simulated stack running in one terminal (relay, virtual
    neuronavigation, virtual robot and the controller) and one mapping session
    in which the controller has driven the robot, fired the stimulator,
    analysed the EMG and rendered an R² map on a cortical surface mesh.

    A real session uses InVesalius for the neuronavigation and
    `tms-robot-control` for the robot; this page stays with their virtual
    twins.

## 1. Get the code

```bash
git clone https://gitlab.gwdg.de/tms-localization/papers/neuropilot.git
cd neuropilot
```

The example subject under `data/ernie` is stored in Git LFS:

```bash
git lfs pull
```

## 2. Install with one command

```bash
scripts/install.sh
```

The only prerequisite is conda (miniforge or miniconda) on the PATH. The script

1. creates `.env` from `.env.example` if it is missing,
2. creates the conda environment `neuropilot` from `environment.yml`, or reuses
   it when it already exists,
3. installs TMS NeuroPilot in editable mode (`pip install -e . --no-deps`),
4. installs the MKL build that the SimNIBS solver wheel links against, and
   repairs the library search path where the wheel expects the older sonames,
5. verifies that every required module imports and stops with the failing
   import instead of leaving a half-working environment.

| Flag | Effect |
|---|---|
| `--env-name NAME` | use a different conda environment |
| `--with-invesalius` | also create the `invesalius` environment (real, manual and training sessions) |
| `--with-robot-control` | also clone the robot-control fork (real sessions) |

The virtual stack and the precomputed mapping mode run without SimNIBS; the
online E-field mode and the display of SimNIBS head meshes need it.
`--with-invesalius` is only needed when the neuronavigation is real.

!!! info "Manual installation"
    [Install the suite](install/install.md) has the step-by-step recipe: the
    exact conda and pip commands, Windows, SimNIBS and its solver, InVesalius,
    the desktop entry, updating and resetting.

## 3. Bootstrap configuration

`scripts/install.sh` already copied `.env.example` to `.env`. The file holds
what must exist before the GUI opens: the relay endpoint, the data folder, the
readiness timeout and the control-panel flag. Every value has a working
default, so a simulator session needs no edit. The full key list is in the
[`.env` reference](config/env.md).

!!! note "Where does session data go?"
    `ROOT_FOLDER` defaults to `~/.neuropilot` (Linux) or
    `C:\Users\<name>\.neuropilot` (Windows). Results, plots and the session
    cache are written there.

## 4. Start the simulated stack

```bash
conda activate neuropilot
neuropilot sim
```

The supervisor starts the components in dependency order and waits for each
readiness probe before starting the next:

```text
[neuropilot] started relay (pid 12345)
[relay] [SIM RELAY] Starting simulation relay on http://127.0.0.1:5000
[neuropilot] relay ready on 127.0.0.1:5000
[neuropilot] started nav (pid 12346)
[nav] [virtual_neuronavigation] Connected to http://127.0.0.1:5000
[neuropilot] nav ready
[neuropilot] started robot (pid 12347)
[robot] … sim_client — Connected to relay server at http://127.0.0.1:5000
[neuropilot] robot ready
[neuropilot] started controller (pid 12348)
```

A MuJoCo viewer window opens next to the controller window. Four components,
one terminal, one Ctrl+C to stop everything.

!!! tip "Cold start is slower"
    The first launch compiles the MuJoCo scene and imports SimNIBS/pyvista.
    Expect 20–40 s before the controller window appears; later starts are
    faster. The readiness budget is `READINESS_TIMEOUT_S` (default 60 s).

## 5. Prepare a subject with the three scripts

A project needs the subject's head model, the ROI surface, the E-field library
and the target order. Three scripts produce them in order, each reading the
output of the one before:

```bash
# 1. Head model: MRI to SimNIBS mesh (charm), ROI surface in the mesh HDF5
python scripts/01_create_head_model.py \
    -s data/<subj>/<subj>.hdf5 \
    -m mesh_<subj>_lincc \
    --charm_ini scripts/configs/charm_410.ini

# 2. Coil-placement library and ROI E-fields
python scripts/02_create_roi_efield_library.py \
    --mesh-msh data/<subj>/mesh/m2m_<subj>/<subj>.msh \
    --roi-hdf5 data/<subj>/mesh/m2m_<subj>/<subj>.hdf5 \
    --roi-idx midlayer_m1s1pmd \
    --coil data/<subj>/coil/MagVenture_MCF-B65_new.ccd \
    --out data/<subj>/efield/e.hdf5

# 3. Optimized target order from the library
python scripts/03_create_optimized_sequences.py \
    --e-hdf5 data/<subj>/efield/e.hdf5 \
    --n-stim 500
```

| Script | Input | Output | What it does |
|---|---|---|---|
| `01_create_head_model.py` | T1 (and T2, DWI if available) | `m2m_<subj>/<subj>.msh`, subject HDF5 | `charm` segmentation and meshing, anisotropic conductivity from the DWI, ROI surface in the mesh file |
| `02_create_roi_efield_library.py` | head mesh, ROI, coil | `e.hdf5` | placement grid of scalp positions and handle rotations, one FEM solve per placement, design matrix with a hash over the ROI element order |
| `03_create_optimized_sequences.py` | `e.hdf5` | one `*.txt` per algorithm | farthest-point, D-optimal and RBF-kernel D-optimal sequences |

Two helpers complete the set: `03_validate_efield_surrogate.py` scores a library
against the interpolation (random 80/20 and leave-positions-out split), and
`04_export_efield_vtk_series.py` exports it as ParaView time series.
`sort_coil_placements.py` reorders a sequence for minimal robot travel.

The artefacts, their formats and what TMS NeuroPilot validates when it loads
them are described in [Subject data](prepare/subject-data.md).

## 6. Load a mapping project

The controller needs a project: the subject mesh, the coil placements, the
E-field library, the EMG sources and the output paths. Two ways to get one:

=== "Example subject (if you have it)"

    The repository carries the SimNIBS example subject under `data/ernie`.
    Build a project file whose paths are relative to the project:

    ```bash
    python docs/site/tools/make_demo_project.py
    ```

    It prints the project path (default `/tmp/np_demo/NP001/NP001.yaml`). In
    the controller, open the **Project** page, click **Load**, and select it.

    This is the real example head, so the geometry is meaningful, but it is
    still a tutorial dataset, not a study subject.

=== "Your own subject"

    Prepare the files with the three scripts above, add the EMG channel sources
    and the coil model, and save the project file. This is the path for a real
    session; the simulator does not need hardware, but it does need a project.

Once loaded, the **Project** page shows every path and the **Cortical
results** page has a mesh to draw on.

<figure>
  <img src="assets/screenshots/project-demo.png" alt="The Project page with every file slot filled by the demo dataset.">
  <figcaption>The Project page after loading a project. Each row is one file;
  the folder buttons on the right open the file dialog in a sensible
  directory.</figcaption>
</figure>

## 7. Connect, choose the E-field mode, run

1. Open the **Connections** page and press **Reconnect** if a card is still
   grey. In simulation all four systems turn green within a second or two.
2. Open the **Control** page and choose **Precomputed E-Field**. Start is
   disabled until a mode is chosen; that is the intended gate, not a bug.
3. Set the amplitude and repetitions for the demo (the defaults are fine).
4. Press **Start**. The controller creates a marker in the neuronavigation, the
   robot moves the coil to it, the stimulator fires, and the MEP appears on
   the **MEP results** page.
5. Watch the **Cortical results** page: the first R² map appears after three
   pulses.

<figure>
  <img src="assets/screenshots/control-precomputed.png" alt="The Control page with the precomputed E-field mode selected and Start enabled.">
  <figcaption>The Control page. Left: stimulation and speed settings. Middle:
  E-field mode and transport. Right: the robot view and the session log.</figcaption>
</figure>

## 8. Finish and stop

- **Finish** ends the mapping and writes the results CSV.
- Ctrl+C in the terminal where `neuropilot sim` runs stops all four components.

```text
[controller] shutting down
[robot]      stopped
[nav]        stopped
[relay]      stopped
```

## If it does not start

| Symptom | First thing to try |
|---|---|
| `neuropilot: command not found` | `conda activate neuropilot`, then rerun `scripts/install.sh` |
| `scripts/install.sh` fails on an import | The script prints the failing module; rerun it after fixing the environment, it is idempotent |
| Controller window never appears | Check the last 30 lines of the terminal for a traceback; a missing `DISPLAY` is the usual cause on a remote machine |
| `ROOT_FOLDER` permission error | `ROOT_FOLDER=/tmp/neuropilot_test neuropilot sim` |
| MuJoCo window fails to open on Wayland | See `PYGLFW_LIBRARY` in [Troubleshooting](reference/troubleshooting.md) |
| Port 5000 already in use | Something else is bound to it; stop it or set `RELAY_PORT` in `.env` |

The full symptom, cause and fix table is in
[Troubleshooting](reference/troubleshooting.md).

## Next

- [Key concepts](start/concepts.md): the vocabulary used by every other page.
- [A simulated session](run/simulated.md): the same walkthrough with more
  detail, including what each step does on the wire.
- [Real session checklist](run/real.md): when you are ready for hardware.
