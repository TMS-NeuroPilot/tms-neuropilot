# Quick start

This page takes you from a fresh clone to a running simulated mapping session.
It needs no hardware and no subject data. With the `pipeline` environment
already in place it takes about ten minutes; creating that environment the first
time takes longer.

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

## 2. Create the environment

```bash
conda create -n pipeline python=3.11 -y
conda activate pipeline
python --version          # must be 3.11.x
conda install -c conda-forge -y pyqt qasync pyvista vtk h5py scipy numpy \
    pyyaml requests python-socketio aiohttp python-dotenv
pip install mujoco pybullet ikpy smbprotocol pynibs
```

These are the packages the GUI, the 3-D view, the relay, the analysis and the
virtual robot need. If the `pipeline` environment already exists, activate it
and skip the create/install lines.

SimNIBS is not needed for this walkthrough, which uses the precomputed E-field
mode. It is needed for the online solver and for displaying a SimNIBS `.msh`
head mesh; [Install the suite](install/install.md) has the recipe.

InVesalius is not part of this environment: it is a separate application for
real and manual sessions, covered in [Install the suite](install/install.md)
under *InVesalius*.

## 3. Install NeuroPilot

```bash
pip install -e . --no-deps
```

`--no-deps` is deliberate: the heavy dependencies (PyQt5, pyvista, pynibs,
MuJoCo) are already installed in the environment. The package itself installs
the `neuropilot` command and the package under `src/`.

Check that the command is on the path:

```bash
neuropilot --help
```

```text
usage: neuropilot [-h] {sim,relay,controller,real,manual} ...
```

## 4. Create the bootstrap configuration

```bash
cp .env.example .env
```

`.env` holds what must exist *before* the GUI opens: the relay endpoint, the
data folder, the readiness timeout and the flag that enables the control panel.
Every value in it has a working default, so for a simulator session you can
leave it untouched. The full key list is in the
[`.env` reference](config/env.md).

!!! note "Where does session data go?"
    `ROOT_FOLDER` defaults to `~/.neuropilot`. Results, plots and the session
    cache are written there. The path is built from the platform's home
    directory, so on Windows it resolves to `C:\Users\<name>\.neuropilot`
    without a manual path edit. For a throw-away test you can point it
    elsewhere:

    ```bash
    ROOT_FOLDER=/tmp/neuropilot_test neuropilot sim
    ```

## 5. Start the simulated stack

```bash
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

## 6. Load a mapping project

The controller needs a project: the subject mesh, the coil placements, the
E-field library, the EMG sources and the output paths. Two ways to get one:

=== "Example subject (if you have it)"

    The repository can carry the SimNIBS example subject under `data/ernie`
    (several GB; not tracked). If you have it, build a project file whose
    paths contain no home directory:

    ```bash
    python docs/site/tools/make_demo_project.py
    ```

    It prints the project path (default `/tmp/np_demo/NP001/NP001.yaml`). In
    the controller, open the **Project** page, click **Load**, and select it.

    This is the real example head, so the geometry is meaningful, but it is
    still a tutorial dataset, not a study subject.

=== "Your own subject"

    Prepare the head mesh, ROI surface, E-field library, placements and EMG
    channels as described in [Prepare a session](prepare/subject-data.md), then
    load the project file you saved. This is the path for a real session; the
    simulator does not need hardware, but it does need a project.

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
| `neuropilot: command not found` | `pip install -e . --no-deps` in the active `pipeline` env |
| Controller window never appears | Check the last 30 lines of the terminal for a traceback; a missing `DISPLAY` is the usual cause on a remote machine |
| `ROOT_FOLDER` permission error | `ROOT_FOLDER=/tmp/neuropilot_test neuropilot sim` |
| MuJoCo window fails to open on Wayland | See `PYGLFW_LIBRARY` in [Troubleshooting](reference/troubleshooting.md) |
| Port 5000 already in use | Something else is bound to it; stop it or set `RELAY_PORT` in `.env` |

The full symptom → cause → fix table is in
[Troubleshooting](reference/troubleshooting.md).

## Next

- [Key concepts](start/concepts.md): the vocabulary used by every other page.
- [A simulated session](run/simulated.md): the same walkthrough with more
  detail, including what each step does on the wire.
- [Real session checklist](run/real.md): when you are ready for hardware.
