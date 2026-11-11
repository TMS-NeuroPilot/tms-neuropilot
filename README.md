# NeuroPilot

**NeuroPilot — guided online TMS mapping with online field optimization.**

One suite for robot-assisted TMS mapping experiments: an experimenter-facing
controller (PyQt5 GUI) that drives the online mapping loop — coil targets,
online finite-element field computation, MEP regression, and stimulation
guidance through InVesalius — plus a complete virtual twin of the hardware
(relay, virtual robot, virtual neuronavigation) so the whole workflow runs
without any physical device.

## Quick start

```bash
pip install -e . --no-deps      # in the `pipeline` conda env (heavy deps come from conda)
neuropilot                      # GUI: choose simulated or real
neuropilot sim                  # simulated stack, one command
neuropilot sim --components relay,robot    # subset for debugging
neuropilot controller --sim     # controller alone in simulation mode
neuropilot real [--launch-relay]           # real-hardware mode
```

`neuropilot sim` starts, in order: simulated relay → virtual neuronavigation
+ virtual robot (in parallel) → controller, each started only after the
previous one is ready, all logs prefixed by role in one terminal. Ctrl+C
shuts the whole stack down.

## Components

| Package | Origin | Role |
|---|---|---|
| `neuropilot.controller` | cobot-pipeline-controller | experiment orchestrator: PyQt5 GUI + qasync backend, health checks, online FEM (`onlineFEM.py`), MEP analysis |
| `neuropilot.sim_relay` | relay_server_sim | simulated Socket.IO relay hub |
| `neuropilot.sim_robot` | tms-robot-sim2 | virtual robot: MuJoCo scene + URDF IK, contact-model force feedback (`assets/` inside the package) |
| `neuropilot.sim_nav` | virtual_neuronavigation | virtual neuronavigation: head tracking, coil-target creation, tolerance evaluation |

Components communicate over Socket.IO relay topics
(`from_robot`, `from_neuronavigation`, `from_external_controller` →
`to_*`); the protocol is byte-identical to the production components in
`tms-robot-control` and InVesalius.

## Configuration

Copy `.env.example` to `.env`. Cross-component settings (relay endpoint,
data folder, readiness timeout, real-relay path) live in one place;
component-internal constants live in each component's `config.py`.

## Tests

```bash
pytest                      # runs tests/ (pytest is in the `pipeline` env)
pytest tests/test_gui_window.py -v
pytest -m "not gui"         # nothing that needs a display
scripts/run_tests.sh        # the same headless set the CI job runs
```

CI runs `pytest -m "not gui"` on every push and merge request
(`.gitlab-ci.yml`); it expects a runner with the `pipeline` environment (set
`PYTHON` in the CI/CD variables, or uncomment the runner tag in the file).

The six pages are snapshotted (`tests/test_gui_snapshots.py`): a coarse
32×24 pixel fingerprint plus the geometry of every named widget, compared
against `tests/baselines/gui_pages.json`.  A `.ui` or style-sheet regression
fails the test and leaves the current rendering in pytest's `tmp_path`.
After an intentional design change regenerate the baseline:

```bash
UPDATE_GUI_BASELINES=1 pytest tests/test_gui_snapshots.py
```

The suite covers the parts that do not need hardware: the fit-function
registry, the `.env` editor, the online solver lifecycle, the per-pulse
E-field rows that let the E-field mode switch mid-run, the recording in
`collect_data_step`, the analysis assembly, the virtual EMG channels,
robot health parsing, the coil-target axis convention, the relay-topic
contract and the placements CSV export.

The GUI tests build a real `MainWindow` and drive it: all six pages,
resizing, the results table and readout, project load/save with corrupt,
empty, missing and binary files, project files whose folder was deleted,
the Config tab against a temporary `.env`, the study profile, exports and
screenshots into deleted folders, manual mode, the status LEDs and
recovery buttons, every button on every page (with an exception hook that
turns a crashing slot into a failed test instead of an aborted run), the
mesh/coil summary threads and their Qt signals, and close/teardown.  They
need a display and are skipped automatically when `DISPLAY` and
`WAYLAND_DISPLAY` are both unset.

Everything the tests write goes to `tmp_path`: the session cache and the
Config tab's `.env` are redirected in `tests/conftest.py`, and an autouse
fixture fails any test that rewrites `~/.neuropilot/last_session.yaml` or
the repository's `.env`.

## License

NeuroPilot is licensed under the **Creative Commons Attribution-NonCommercial-ShareAlike 4.0
International (CC BY-NC-SA 4.0)** license — free to use, share, and adapt for
non-commercial purposes (research and clinical science), with attribution and
share-alike; commercial use requires prior permission from the authors.
See `LICENSE` for the full text.
