# Verify the installation

Run these checks in order. Each one isolates a layer, so a failure tells you
where to look instead of "the app does not start".

## 1. Imports

```bash
conda activate pipeline
python - <<'PY'
import neuropilot, neuropilot.config
print("suite   ", neuropilot.__name__, neuropilot.config.REPO_ROOT)
import PyQt5.QtWidgets, qasync, pyvista      # GUI + 3-D
import h5py, numpy, scipy, yaml, socketio    # data + relay
import pynibs                                # MEP analysis
import mujoco, ikpy                          # virtual robot
print("imports ok")
PY
```

A missing module names the layer to fix. `magicpy` is optional (real
stimulator only); `simnibs` is optional unless you want the online E-field.

## 2. Command line

```bash
neuropilot --help
neuropilot sim --help
neuropilot controller --help
```

The first line should read `usage: neuropilot [-h] {sim,relay,controller,real,manual}`.
If the command is missing, the editable install did not run in this environment:

```bash
pip install -e . --no-deps
```

## 3. Robot registry

```bash
python -m neuropilot.sim_robot.robots --list
python -m neuropilot.sim_robot.robots --check omron
```

`--check` validates that the MuJoCo model, the URDF and the IK chain exist and
that the joint masks have the right length. It prints a short report and exits
non-zero on a broken entry.

## 4. Test suite

The headless part of the suite needs no display and no hardware:

```bash
pytest -m "not gui" -q
```

or, identically:

```bash
scripts/run_tests.sh
```

Expect roughly 700 tests passing in a few minutes. The GUI tests are separate:

```bash
pytest -m gui -q           # needs DISPLAY or WAYLAND_DISPLAY
```

!!! note "What a failure means"
    The non-GUI suite covers the fit registry, the `.env` editor, the online
    solver lifecycle, the per-pulse E-field rows, the analysis assembly, the
    relay-topic contract and the export writers. A failure there is a real
    regression, not a missing device.

## 5. Simulated stack

```bash
neuropilot sim
```

In the terminal you should see four components connect, and no traceback:

```text
[neuropilot] relay ready on 127.0.0.1:5000
[neuropilot] nav ready
[neuropilot] robot ready
[neuropilot] started controller
```

The controller window opens with the six tabs. A MuJoCo viewer window opens for
the virtual robot. Ctrl+C stops everything.

## 6. GUI smoke test

Open each tab once. Every page must render without a traceback in the terminal:

| Page | What proves it works |
|---|---|
| Project | the file rows are editable, **Load** opens a dialog |
| Connections | three cards, each with a status LED |
| Control | the E-field radios, the transport buttons (Start disabled until a mode is chosen) |
| MEP results | two empty plots with axes |
| Cortical results | the empty 3-D viewport and the Results / Mapping / Display / Selection cards |
| Config | three sub-tabs: Lab, Study, Subject |

## 7. Online solver (optional)

With the simulator running and a project loaded:

1. Open **Control** and click **Online E-Field**.
2. The hint under the radios changes to *"Warming up the online solver (about a
   minute) — pulses wait until it is ready."*
3. After the solver load, it changes to *"Online solver ready."*

If it says *"Online solver unavailable — switch to Precomputed"*, SimNIBS or
`petsc4py` is not importable in `pipeline`. Check step 1 and the MKL note in
[Install the suite](install/install.md).

## 8. Data files (optional)

If you already have a subject:

```bash
python - <<'PY'
import h5py
for path in ["/path/to/roi.hdf5", "/path/to/e.hdf5", "/path/to/placements.hdf5"]:
    with h5py.File(path) as f:
        print(path, list(f.keys()))
PY
```

A valid ROI has `mesh/nodes/node_coord` and `mesh/elm/triangle_number_list`; a
valid E-field library has `E_mag` with shape `(placements, roi_elements)`. See
[Subject data](prepare/subject-data.md).

## 9. Documentation build

```bash
python docs/site/build.py --check
```

This builds the site, verifies every internal link and anchor and removes the
output again. It needs nothing but the standard library, so it also works on a
machine without the GUI stack.

## What "verified" means

- [ ] imports ok
- [ ] `neuropilot` on the PATH
- [ ] `robots --check omron` ok
- [ ] `pytest -m "not gui"` green
- [ ] `neuropilot sim` shows four components and no traceback
- [ ] all six GUI pages render
- [ ] (optional) online solver reaches *ready*
- [ ] (optional) `docs/site/build.py --check` returns 0

Only the first four are needed before you start preparing subject data; the rest
confirm the environment is complete.

## Next

- [Quick start](start/quickstart.md) — run a session in the simulator.
- [Troubleshooting](reference/troubleshooting.md) — if a check failed.
