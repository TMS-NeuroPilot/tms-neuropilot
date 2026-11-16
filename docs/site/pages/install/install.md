# Install the suite

This page installs NeuroPilot into a conda environment and configures it. It
assumes the machine already has conda (miniforge or miniconda). InVesalius, the
neuronavigation application for real sessions, has its own environment; its
installation is at the end of this page.

## Quick install

The repository ships a one-file environment spec and an installer that does
everything below (optionally including InVesalius):

```bash
git clone https://gitlab.gwdg.de/tms-localization/papers/neuropilot.git
cd neuropilot
scripts/install.sh                     # conda env + NeuPilot
scripts/install.sh --with-invesalius   # also install InVesalius
scripts/install.sh --with-invesalius --with-robot-control
                                         # also clone the GitHub robot-control test stack
```

`--with-invesalius` uses the GitHub `installer-three-prs` branch. For a full
local test stack, add `--with-robot-control`, which clones the GitHub
`tms-robot-control` `installer-omron-relay` branch and installs its
requirements into the selected NeuroPilot environment. It does not create a
second robot-control environment.

or by hand:

```bash
conda env create -f environment.yml    # the whole suite in one spec
conda activate neuropilot
pip install -e . --no-deps
```

That is it — `neuropilot sim` starts the simulated stack. The numbered
sections after this one walk the same steps in detail and explain what each
package is for; they remain the reference when something in the quick path
fails on your machine.

## Manual installation

### 1. Get the code

```bash
git clone https://gitlab.gwdg.de/tms-localization/papers/neuropilot.git
cd neuropilot
```

The repository is self-contained: `src/` holds the four packages, `scripts/`
the data-preparation tools, `docs/` the documentation sources. The example
subject under `data/ernie` is stored through Git LFS; run `git lfs pull` after
cloning if you want to use it.

### 2. Create the environment

```bash
conda create -n neuropilot python=3.11 -y
conda activate neuropilot
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

### 3. Install the lab packages

```bash
pip install pynibs            # MEP extraction + fit functions
pip install magicpy           # only needed for a real stimulator
```

If the package index does not have them, install the wheels the group keeps on
GitLab or on the lab share. Check what is missing with:

```bash
python -c "import pynibs; print(pynibs.__file__)"
```

### 4. Install SimNIBS (for the online E-field mode and `.msh` meshes)

The precomputed E-field mode needs no SimNIBS. The online mode and reading
SimNIBS `.msh` head meshes do.

One known-good recipe, all inside `neuropilot`:

```bash
# SimNIBS' own petsc4py wheel, then the official SimNIBS 4.5.0 wheel
pip install "petsc4py @ https://github.com/simnibs/petsc4py/releases/download/v3.21.5/petsc4py-3.21.5-cp311-cp311-manylinux_2_28_x86_64.whl"
pip install --no-build-isolation "simnibs @ https://github.com/simnibs/simnibs/releases/download/v4.5.0/simnibs-4.5.0-cp311-cp311-linux_x86_64.whl"
pip install "mkl==2024.2.0" tbb numba fmm3dpy samseg
conda install -c conda-forge python-mumps
```

### 5. Install NeuroPilot in editable mode

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

### 6. Create `.env`

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

### 6b. Windows

The controller, the four components and the whole simulated stack run on
Windows. The conda steps above work unchanged on win-64 (conda-forge ships
PyQt5, VTK, numpy, etc. for Windows; `mujoco`, `pybullet`, `ikpy` and
`smbprotocol` have Windows wheels):

```bat
conda create -n neuropilot python=3.11 -y
conda activate neuropilot
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

### 7. Optional: the GUI scale and the theme

On a HiDPI screen the GUI may open too small or too large. Set the scale
explicitly in `.env`:

```bash
NEUROPILOT_UI_SCALE=1.25
```

The colour theme is chosen in **Config › Lab › Theme** and stored in the lab
profile; see [Themes and display](gui/themes.md).

### 8. Optional: desktop entry and Alt+Tab icon

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
it for neuronavigation, and it runs in its own conda environment. Use the main
InVesalius repository:

```text
https://github.com/invesalius/invesalius3
```

The relay and tracker changes are being proposed upstream; use the branch from
the relevant pull request until they are merged.

```bash
git clone https://github.com/invesalius/invesalius3.git
cd invesalius3
conda create -n invesalius python=3.12 -y
conda activate invesalius
conda install -c conda-forge -y wxpython=4.2.2 "numpy=1.26.4" \
    vtk==9.4.2 cython pyserial psutil pypubsub gdcm pyacvd
pip install "numpy==1.26.4" "scipy==1.14.0" "pandas==2.3.3" \
    "tifffile==2026.3.3" "ml_dtypes==0.5.4" "nibabel==5.2.1" \
    "scikit-image==0.24.0" "h5py==3.11.0" "imageio==2.34.2" \
    "matplotlib==3.9.0" "pillow==10.3.0" "pydicom==2.4.5" \
    "pynetdicom==2.0.2" "lib3mf==2.3.2" "onnx>=1.17,<2" onnxruntime \
    "python-socketio[client]" pypolaris
pip install --extra-index-url https://download.pytorch.org/whl/cpu \
    "torch==2.15.0+cpu"
pip install -e . --no-deps
```

Two details that cause most failed installs:

- **Python 3.12.** InVesalius declares `requires-python = "==3.12.*"`; 3.13 is
  not supported.
- **wxPython from conda.** wxPython is a large C++ extension. The conda package
  is already built; without it pip compiles wxPython from source and the
  install takes much longer.

`--no-deps` keeps pip from resolving the full dependency set, and from
rebuilding wxPython. The Python packages above are installed explicitly because
this branch imports its deep-learning module during startup: `pandas` and
`torch` are required even for a navigation-only session. The CPU torch wheel is
enough for normal use; install a CUDA build separately if you use GPU
segmentation.

Start it pointed at the relay:

```bash
python app.py --remote-host http://localhost:5000
```

After `scripts/install.sh --with-invesalius`, the equivalent `inv` command is
also available in the `invesalius` environment:

```bash
inv --remote-host http://localhost:5000
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
- **Environment:** `conda env remove -n neuropilot` and start again.

## Next

- [Hardware setup](install/hardware.md): only needed for real hardware.
- [Verify the installation](install/verify.md): prove that everything works.
- [Quick start](start/quickstart.md): run the simulator.
