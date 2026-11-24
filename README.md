# TMS NeuroPilot

**TMS NeuroPilot — guided online TMS mapping with online field optimization.**

One suite for robot-assisted TMS mapping experiments: an experimenter-facing
controller (PyQt5 GUI) that drives the online mapping loop — coil targets,
online finite-element field computation, MEP regression, and stimulation
guidance through InVesalius — plus a complete virtual twin of the hardware
(relay, virtual robot, virtual neuronavigation) so the whole workflow runs
without any physical device.

## Where things live

| What | Where |
|---|---|
| Public code and issue tracker | [github.com/0nu/tms-neuropilot](https://github.com/0nu/tms-neuropilot) — `main` is the latest release, `dev` the development branch |
| Canonical development | the group's GitLab, [tms-localization/tms-neuropilot/tms-neuropilot](https://gitlab.gwdg.de/tms-localization/tms-neuropilot/tms-neuropilot) |
| Example subject data | separate repository, [tms-neuropilot-data](https://gitlab.gwdg.de/tms-localization/tms-neuropilot/tms-neuropilot-data) (clone into `data/ernie`) |

## Quick start

```bash
pip install -e . --no-deps      # in the `neuropilot` conda env (heavy deps come from conda)
neuropilot                      # GUI: choose simulated or real
neuropilot sim                  # simulated stack, one command
neuropilot sim --components relay,robot    # subset for debugging
neuropilot controller --sim     # controller alone in simulation mode
neuropilot robo [--launch-relay]           # robotic mode
```

`neuropilot sim` starts, in order: simulated relay → virtual neuronavigation
+ virtual robot (in parallel) → controller, each started only after the
previous one is ready, all logs prefixed by role in one terminal. Ctrl+C
shuts the whole stack down.

## Running on Windows

TMS NeuroPilot's four components and the whole simulated stack are
cross-platform. On Windows (Python 3.11+ in a conda env with the heavy deps
installed — same `neuropilot` environment as on Linux):

```bat
pip install -e . --no-deps
neuropilot sim
```

Notes:

- **Simulated stack (relay → robot + nav → controller) runs unchanged.** The
  supervisor launches each component with `sys.executable`, so it works
  regardless of interpreter path.
- **Real-hardware mode** is primarily a Linux/MPI-lab deployment. The code is
  import-safe, but the drivers themselves (`magicpy`, `pynibs`, InVesalius,
  `tms-robot-control`) must be installable on the target machine. Set the
  Windows serial port in `.env`, e.g. `STIMULATOR_PORT=COM3`; there is no
  default TTL (parallel) port on Windows.
- **Serial/TTL defaults are platform-aware**: `/dev/ttyS1` +
  `/dev/parport0` on Linux, `COM3` + no TTL on Windows (override in
  `Config › Lab` or `.env`).
- The virtual stimulator's pulse "alert" sound uses `winsound` on Windows
  instead of `paplay`.
- **Tests**: run `pytest -m "not gui"` directly. `scripts/run_tests.sh` is a
  bash helper for Linux CI. GUI tests run natively on Windows (no DISPLAY
  needed).
- `scripts/install_desktop_entry.sh` (a `.desktop` launcher) is
  Linux-only; on Windows start it from the installed console script
  (`neuropilot.exe` in the env's `Scripts/`).

## Documentation

The full documentation — installation, subject-data preparation, every GUI page
and configuration key, the workflows, the architecture, the relay protocol and
troubleshooting — is published with GitLab Pages:

<https://neuropilot-94ad2d.pages.gwdg.de/>

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
pytest                      # runs tests/ in parallel (8 workers at most)
pytest -n0                  # serial, when a run must be watched
pytest tests/test_gui_window.py -v
pytest -m "not gui"         # nothing that needs a display
scripts/run_tests.sh        # the same headless set the CI job runs
```

The suite runs in parallel by default (`pytest-xdist`, as many workers as
useful, 8 processes at most — see `addopts` in `pyproject.toml`); a full run
takes well under a minute instead of three.  Tests that build a MuJoCo world
write a scene file per process, so the workers cannot read each other's
head or base pose.

CI (`.gitlab-ci.yml`) runs a syntax gate and `pytest -m "not gui"` on every
push and merge request.  `scripts/ci-python.sh` finds the `neuropilot`
interpreter automatically (`PYTHON`, then the usual conda locations, then
`python3`), so the job needs no configuration when the runner has that
environment.  The GUI tests are a separate, manually started job for a runner
with a display.

The seven pages are snapshotted (`tests/test_gui_snapshots.py`): a coarse
32×24 pixel fingerprint plus the geometry of every named widget, compared
against `tests/baselines/gui_pages.json`.  A `.ui` or style-sheet regression
fails the test and leaves the current rendering in pytest's `tmp_path`.
After an intentional design change regenerate the baseline:

```bash
UPDATE_GUI_BASELINES=1 pytest tests/test_gui_snapshots.py
```

The suite covers the parts that do not need hardware: the fit-function
registry, the `.env` editor, the online solver lifecycle, the per-pulse
E-field rows that let the E-field mode switch mid-run, the collision-test
placement conversion and scan, the recording in `collect_data_step`, the
analysis assembly, the virtual EMG channels, robot health parsing, the
coil-target axis convention, the relay-topic contract and the placements CSV
export.

The GUI tests build a real `MainWindow` and drive it: all eight pages,
resizing, the results table and readout, project load/save with corrupt,
empty, missing and binary files, project files whose folder was deleted,
the Config tab against a temporary `.env`, the study profile, exports and
screenshots into deleted folders, manual mode, the status LEDs and
recovery buttons, every button on every page (with an exception hook that
turns a crashing slot into a failed test instead of an aborted run), the
mesh/coil summary threads and their Qt signals, and close/teardown.  On
Linux/macOS they need a display and are skipped automatically when `DISPLAY`
and `WAYLAND_DISPLAY` are both unset; on Windows Qt uses the native display
and they run normally.

Everything the tests write goes to `tmp_path`: the session cache and the
Config tab's `.env` are redirected in `tests/conftest.py`, and an autouse
fixture fails any test that rewrites `~/.neuropilot/last_session.yaml` or
the repository's `.env`.

## License

TMS NeuroPilot is licensed under the **Creative Commons Attribution-NonCommercial-ShareAlike 4.0
International (CC BY-NC-SA 4.0)** license — free to use, share, and adapt for
non-commercial purposes (research and clinical science), with attribution and
share-alike; commercial use requires prior permission from the authors.
See `LICENSE` for the full text.
