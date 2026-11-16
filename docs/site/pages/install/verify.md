# Verify the installation

Run these checks in order. Each one isolates a layer, so a failure tells you
where to look instead of "the app does not start".

## 1. Imports

```bash
conda activate neuropilot
```

Paste this into a Python session, or save it as `check_imports.py` and run it:

```python
import neuropilot, neuropilot.config
print("suite   ", neuropilot.__name__, neuropilot.config.REPO_ROOT)
import PyQt5.QtWidgets, qasync, pyvista      # GUI + 3-D
import h5py, numpy, scipy, yaml, socketio    # data + relay
import pynibs                                # MEP analysis
import mujoco, ikpy                          # virtual robot
print("imports ok")
```

A missing module names the layer to fix. `magicpy` is optional (real
stimulator only); `simnibs` is optional unless you want the online E-field.

## 2. Command line

```bash
neuropilot --help
neuropilot sim --help
neuropilot controller --help
```

The first line should read `usage: neuropilot [-h] {sim,relay,controller,real,manual,training}`.
If the command is missing, the editable install did not run in this environment:

```bash
pip install -e . --no-deps
```

## 3. Robot registry

```bash
python -m neuropilot.sim_robot.robots --list
python -m neuropilot.sim_robot.robots --check omron   # or the key from --list
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

The non-GUI set runs in well under a minute. The GUI tests are separate:

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

The controller window opens with the seven tabs. A MuJoCo viewer window opens for
the virtual robot. Ctrl+C stops everything.

## Next

- [Quick start](start/quickstart.md) — run a session in the simulator.
- [Troubleshooting](reference/troubleshooting.md) — if a check failed.
