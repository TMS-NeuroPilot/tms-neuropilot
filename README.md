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

## Documentation

The full documentation — installation, subject-data preparation, every GUI page
and configuration key, the workflows, the architecture, the relay protocol and
troubleshooting — is published with GitLab Pages:

<https://tms-localization.pages.gwdg.de/papers/neuropilot/>

Its sources live in `docs/site/`: plain Markdown plus a dependency-free
generator (no MkDocs, no network). Build and preview locally:

```bash
python docs/site/build.py --serve 8000    # http://localhost:8000
python docs/site/build.py --check         # what the CI job verifies
```

`docs/site/README.md` is the authoring guide (Markdown subset, nav, figures).

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

## Robots

The pipeline is robot-agnostic: it sends and receives poses over the relay.
Everything robot-specific is one `RobotSpec` in
`src/neuropilot/sim_robot/robots.py` (MuJoCo model, URDF, IK chain, frames) —
adding a robot to the simulator is that entry plus the two assets.  Real
robots are drivers in `tms-robot-control` and need no change here.

```bash
python -m neuropilot.sim_robot.robots --list        # known robots
python -m neuropilot.sim_robot.robots --check omron # validate a spec
```

`docs/ROBOTS.md` has the full recipe (assets, conventions, relay contract,
pitfalls, verification checklist).

## Appearance

Five colour themes ship with the controller, selectable live in
**Config › Lab › Theme** (no restart):

| Theme | Character |
|---|---|
| Workstation Light | the default: cool neutral canvas, amber accent |
| Lab Paper | warm ivory canvas, terracotta accent — lower glare in a bright room |
| Instrument Blue | cool slate, deep instrumentation blue — keeps amber free for "warming up" |
| **Graphite** | dark, neutral two-level charcoal — long sessions in a dim room |
| **Midnight** | dark, blue-black with a cyan accent — sinks below the neuronavigation screen |

Every palette defines the same tokens (`src/neuropilot/controller/theme.py`):
text/border/surface colours, accent and its disabled/soft variants, status
colours, the instrument beds, chart grid and a six-colour series palette.  The
Qt style sheet is generated from those tokens, and the charts, 3D viewport,
status LEDs, mode badge and log bed are recoloured with the same table.  Text
contrast is enforced by tests (body text ≥ 7:1, captions and status colours
≥ 4.5:1).  The choice is stored in the lab profile (`UI_THEME`) and can be
pinned from `.env` like any other lab key.

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

CI (`.gitlab-ci.yml`) runs a syntax gate and `pytest -m "not gui"` on every
push and merge request.  `scripts/ci-python.sh` finds the `pipeline`
interpreter automatically (`PYTHON`, then the usual conda locations, then
`python3`), so the job needs no configuration when the runner has that
environment.  The GUI tests are a separate, manually started job for a runner
with a display.

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
