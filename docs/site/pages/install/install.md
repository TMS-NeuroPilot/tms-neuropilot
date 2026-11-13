# Install the suite

This page installs NeuroPilot into a conda environment and configures it. It
assumes the machine already has conda (miniforge or miniconda). InVesalius, the
neuronavigation application for real sessions, has its own environment; its
installation is at the end of this page.

## 1. Get the code

```bash
git clone https://gitlab.gwdg.de/tms-localization/papers/neuropilot.git
cd neuropilot
```

The repository is self-contained: `src/` holds the four packages, `scripts/`
the data-preparation tools, `docs/` the documentation sources. The example
subject under `data/ernie` is stored through Git LFS; run `git lfs pull` after
cloning if you want to use it.

## 2. Create the environment

```bash
conda create -n pipeline python=3.11 -y
conda activate pipeline
conda install -c conda-forge -y \
    pyqt qasync pyvista vtk h5py scipy numpy pyyaml requests \
    python-socketio aiohttp python-dotenv
pip install mujoco pybullet ikpy smbprotocol
```

That is the minimum for the simulator and the GUI. The exact package set of an
existing lab machine is a superset; if you are migrating, `conda list` on the
old machine is the reference.

!!! note "Why conda for Qt and VTK"
    PyQt5 and VTK are binary packages with system-library expectations. Conda
    ships consistent builds; a mixed pip/conda environment is the most common
    source of "it starts on my machine but not on the lab PC".

## 3. Install the lab packages

```bash
pip install pynibs            # MEP extraction + fit functions
pip install magicpy           # only needed for a real stimulator
```

If the package index does not have them, install the wheels the group keeps on
GitLab or on the lab share. Check what is missing with:

```bash
python -c "import pynibs; print(pynibs.__file__)"
```

## 4. Install SimNIBS (for the online E-field mode and `.msh` meshes)

The precomputed E-field mode needs no SimNIBS. The online mode and reading
SimNIBS `.msh` head meshes do.

One known-good recipe, all inside `pipeline`:

```bash
# official SimNIBS 4.5.0 wheel from the GitHub release
pip install simnibs-4.5.0-*.whl
pip install petsc4py-*.whl          # SimNIBS' own wheel
pip install mkl tbb numba fmm3dpy samseg
conda install -c conda-forge python-mumps
```

!!! warning "MKL sonames"
    The `petsc4py` wheel links older MKL sonames (`libmkl*.so.2`). If the
    simulation import fails with a missing `libmkl_*.so.2`, copy those files
    from a working SimNIBS environment into `$CONDA_PREFIX/lib`; this is a
    packaging quirk, not a NeuroPilot problem. A separate `simnibs` conda
    environment (the official installer) also works; NeuroPilot only needs
    `simnibs` importable in `pipeline` for the online solver.

Check it:

```bash
python -c "import simnibs; print(simnibs.__version__)"
```

## 5. Install NeuroPilot in editable mode

```bash
pip install -e . --no-deps
```

`--no-deps` prevents pip from rebuilding PyQt5 or numpy from source; the heavy
dependencies are already in the environment. Editable mode means your edits in
`src/` take effect immediately.

Verify the entry point:

```bash
neuropilot --help
python -c "import neuropilot, neuropilot.controller; print('imports ok')"
```

## 6. Create `.env`

```bash
cp .env.example .env
```

Every key has a working default, so `.env` can stay as it is for a first run.
What you will eventually edit:

| Key | Change it when |
|---|---|
| `ROOT_FOLDER` | results should not live in `~/.neuropilot` |
| `RELAY_HOST`, `RELAY_PORT` | the relay runs on another machine or port 5000 is taken |
| `STIMULATOR_PORT`, `STIMULATOR_TTL_PORT` | the real stimulator is on different devices |
| `EMG_COMPUTER_IP`, `EMG_COMPUTER_USERNAME`, `EMG_COMPUTER_PASSWORD` | the EMG PC has a different address or share account |
| `ONLINE_FEM_SOLVER`, `ONLINE_FEM_ANISOTROPY` | the solver should use `amg` or anisotropic conductivity |
| `TMS_ROBOT_CONTROL_PATH` | `neuropilot real --launch-relay` should start the production relay |

`.env` is read **once, at import time**, by `neuropilot.config`; restart the
controller after editing it. See the [`.env` reference](config/env.md) for all
keys and the [settings model](config/model.md) for how `.env` interacts with
the lab profile.

## 6b. Windows

The controller, the four components and the whole simulated stack run on
Windows. The conda steps above work unchanged on win-64 (conda-forge ships
PyQt5, VTK, numpy, etc. for Windows; `mujoco`, `pybullet`, `ikpy` and
`smbprotocol` have Windows wheels):

```bat
conda create -n pipeline python=3.11 -y
conda activate pipeline
conda install -c conda-forge -y ^
    pyqt qasync pyvista vtk h5py scipy numpy pyyaml requests ^
    python-socketio aiohttp python-dotenv
pip install mujoco pybullet ikpy smbprotocol
pip install -e . --no-deps
neuropilot sim
```

Platform-specific notes:

- **Serial ports.** There is no `/dev/` namespace on Windows: the built-in
  `STIMULATOR_PORT` default is `COM3` and there is no default TTL (parallel)
  port. For a real session set them explicitly in `.env`
  (`STIMULATOR_PORT=COM3`). The real-hardware drivers (`magicpy`, `pynibs`,
  InVesalius, `tms-robot-control`) must be installable on the machine too;
  the simulation stack has no such requirement.
- **SimNIBS.** Install it on Windows from the official installer/conda builds.
  The "MKL sonames" note above is Linux-specific (`libmkl*.so.2`); SimsNIBS'
  Windows wheels bundle their own runtimes.
- **Audio.** The virtual stimulator's pulse alert uses `winsound` on Windows
  instead of `paplay`.
- **Path handling.** MuJoCo scenes are generated with `/` separators inside
  the MJCF (`\` is an escape character in MuJoCo XML), and results folders
  are joined with `os.path.join`, so both work under Windows file APIs.
- **Tests:** run `pytest -m "not gui"` (or the full suite; the GUI tests run
  natively on Windows). `scripts/run_tests.sh` is a bash helper for Linux CI.
- `scripts/install_desktop_entry.sh` is Linux-only; on Windows launch the
  installed console script `neuropilot.exe` from the environment's
  `Scripts\` folder.

## 7. Optional: the GUI scale and the theme

On a HiDPI screen the GUI may open too small or too large. Set the scale
explicitly in `.env`:

```bash
NEUROPILOT_UI_SCALE=1.25
```

The colour theme is chosen in **Config › Lab › Theme** and stored in the lab
profile; see [Themes and display](gui/themes.md).

## 8. Optional: desktop entry and Alt+Tab icon

GNOME on Wayland takes the window icon from the desktop file named by
`QApplication.setDesktopFileName("neuropilot")`, not only from the icon set on
the window. An older copy of the icon can therefore survive a code update.
Install the current icon and desktop entry with:

```bash
scripts/install_desktop_entry.sh
```

Then restart NeuroPilot. The script installs the icon under a new theme name,
so GNOME does not reuse its cached placeholder.

## InVesalius (real, manual and training modes)

The simulator does not need InVesalius. Real, manual and training sessions use
it for neuronavigation, and it runs in its own conda environment. Use the group's fork:
stock upstream InVesalius does not publish the relay topics or the tracker
handling that NeuroPilot expects.

```bash
git clone https://gitlab.gwdg.de/tms-localization/cobot/invesalius-mpi.git
cd invesalius-mpi
conda create -n invesalius python=3.12 -y
conda activate invesalius
conda install -c conda-forge -y wxpython=4.2.2 numpy scipy pillow matplotlib \
    scikit-image nibabel pyserial psutil vtk==9.4.2 cython h5py imageio \
    pypubsub gdcm pyacvd
pip install "python-socketio[client]" pypolaris
pip install -e . --no-deps
```

Two details that cause most failed installs:

- **Python 3.12.** InVesalius declares `requires-python = "==3.12.*"`; 3.13 is
  not supported.
- **wxPython from conda.** wxPython is a large C++ extension. The conda package
  is already built; without it pip compiles wxPython from source and the
  install takes much longer.

`--no-deps` keeps pip from resolving the full dependency set, and from
rebuilding wxPython; the navigation runtime is already in the environment. The
two pip packages before it are runtime additions that the fork imports but does
not list in `requirements.txt`: the relay client (`python-socketio`) and the
NDI tracker binding (`pypolaris`).

`torch`, the backend for the deep-learning segmentation tools, is not needed
for navigation; install it separately if you use those tools.

Start it pointed at the relay:

```bash
python app.py --remote-host http://localhost:5000
```

Replace `localhost` with the relay host when the two programs run on different
machines.

## Updating

```bash
git pull
pip install -e . --no-deps       # only needed when the entry point or deps change
```

Then restart the controller. The lab profile and `.env` are not touched by an
update.

## Resetting

- **Configuration:** delete `~/.neuropilot/lab.yaml` (lab settings) and your
  `.env` (bootstrap overrides). Both regenerate from defaults on the next start.
- **Session data:** `~/.neuropilot/` holds the results and the last-session
  cache; move it aside rather than deleting it if you may need the data.
- **Environment:** `conda env remove -n pipeline` and start again.

## Next

- [Hardware setup](install/hardware.md): only needed for real hardware.
- [Verify the installation](install/verify.md): prove that everything works.
- [Quick start](start/quickstart.md): run the simulator.
