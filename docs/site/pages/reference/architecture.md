# Architecture

TMS NeuroPilot is four processes that talk over one Socket.IO relay. This page is
the map: what each process owns, how they start, and where the code lives.

<figure>
  <img src="assets/diagrams/architecture.svg" alt="The four TMS NeuroPilot processes and the relay that connects them, with the real hardware behind the simulated peers.">
  <figcaption>Simulation replaces the three peers; the controller and the relay
  protocol stay the same.</figcaption>
</figure>

This page is the software side only. The hardware side, meaning what runs on
which PC, how the stimulator and the EMG are wired, and which links go over IP,
is drawn in [Hardware setup](../install/hardware.html) (one example wiring, not
the only possible one).

## The four processes

| Role | Package | Entry point | Owns |
|---|---|---|---|
| **controller** | `neuropilot.controller` | `neuropilot controller` | PyQt5 window, asyncio backend, state machine, analysis, online FEM |
| **relay** | `neuropilot.sim_relay` | `neuropilot relay` | the Socket.IO hub and its routing rules |
| **neuronavigation** | `neuropilot.sim_nav` | `python -m neuropilot.sim_nav` | virtual InVesalius: markers, tracking, tolerance |
| **robot** | `neuropilot.sim_robot` | `python -m neuropilot.sim_robot` | MuJoCo scene, IK, collision, force feedback, camera |

In robo mode the last two (and the relay) are replaced by InVesalius, the robot
controller and the production relay; the controller does not change.

## Startup and readiness

`neuropilot sim` runs `supervisor.run_stack()`:

```text
relay      → wait until RELAY_PORT accepts a TCP connection
nav        → start, wait (non-blocking) for "Connected" in its output
robot      → start, wait (non-blocking) for "Connected"
controller → start; no probe
```

Each child runs with:

- its working directory set to the package directory (Qt's `.ui` loader imports
  `mplwidget` relative to the cwd),
- `PYTHONUNBUFFERED=1` (readiness and logs depend on prompt output),
- the merged environment (`ROOT_FOLDER`, `PYGLFW_LIBRARY`, lab profile).

Logs are multiplexed into one terminal with role prefixes. If a child exits with
a non-zero, non-signal code, the supervisor stops the stack.

## The controller's loop

The controller is a single-threaded `qasync` event loop: Qt events and asyncio
tasks share one thread. Consequences:

- a blocking call freezes the GUI **and** the health checks;
- `magicpy` (stimulator) and SMB reads run in executors;
- project files with large meshes, E-field libraries or placements are read by
  background loader threads, and the GUI applies their results through a timer;
- the FEM and the regression run in worker processes/executors;
- results are delivered to the GUI through Qt signals or the loader queue, not
  by touching widgets from a worker.

[The mapping loop](run/mapping-loop.md) covers the state machine.

## Data flow

```text
project YAML ──► controller ──► targets, E-field library
                    │
                    ├─ marker ──────► neuronavigation ──► realised pose
                    ├─ target pose ─► robot ───────────► coil at target
                    ├─ fire ────────► stimulator
                    ├─ collect ─────► EMG files ──► MEP
                    └─ E-field row ─► regression ──► R² ──► mesh + export
```

Nothing large travels over the relay: meshes, EMG files and libraries are read
from disk by the process that needs them. The relay carries topic strings,
poses, status and small payloads.

## Repository layout

```text
neuropilot/
├── src/neuropilot/
│   ├── cli.py                 # subcommands: sim, relay, controller, real, manual, training
│   ├── supervisor.py          # component order, readiness, log multiplexing
│   ├── config.py              # .env + lab profile merge, cross-component values
│   ├── lab_profile.py         # ~/.neuropilot/lab.yaml reader/writer
│   ├── controller/
│   │   ├── main.py            # QApplication + backend wiring
│   │   ├── control_panel.py   # MainWindow: pages, widgets, handlers
│   │   ├── pipeline_controller.py  # Step machine, analysis, relay I/O
│   │   ├── OnlineFEMManager.py     # SimNIBS online solver lifecycle
│   │   ├── meshwidget.py      # pyvista 3-D view + picking
│   │   ├── theme.py           # token tables + style sheet
│   │   ├── fit_functions.py   # the nine pynibs shapes
│   │   ├── config_store.py    # .env editor (comments preserved)
│   │   ├── systems/           # stimulator, EMG, robot backends
│   │   └── gui/               # pipeline_control.ui + icons
│   ├── sim_relay/             # aiohttp + socketio hub
│   ├── sim_robot/             # MuJoCo twin; assets/ live inside the package
│   └── sim_nav/               # virtual neuronavigation
├── scripts/                   # data preparation + CI helpers
├── tests/                     # pytest suite, baselines/
├── docs/                      # CONFIG.md, ROBOTS.md, DESIGN.md, site/
└── pyproject.toml             # entry point, package-data globs
```

!!! warning "Two layout constraints"
    - `sim_robot/assets/` must stay **inside the package**: the MJCF resolves
      mesh paths relative to the XML.
    - `controller/gui/*.ui` and `*.png` are package data. If the globs in
      `pyproject.toml` miss them, the checkout works and the installed package
      does not.

## Files and ports

| Thing | Default | Set by |
|---|---|---|
| relay port | 5000 | `RELAY_PORT` |
| controller ↔ relay | Socket.IO over HTTP | `RELAY_HOST`, `RELAY_PORT` |
| results and plots | `~/.neuropilot` | `ROOT_FOLDER` |
| project | anywhere | Project page |
| lab profile | `~/.neuropilot/lab.yaml` | `NEUROPILOT_LAB_FILE` |
| session cache | `~/.neuropilot/last_session.yaml` | `NEUROPILOT_SESSION_FILE` |

## Why the relay exists

It decouples three vendors that would otherwise need point-to-point
integrations: InVesalius publishes PubSub messages, the robot controller speaks
its own protocol, and the stimulator is a serial device. The relay gives them
one envelope and one routing table — which is also what makes the virtual twin
possible.

## Next

- [Relay protocol](reference/relay.md)
- [Command line](reference/cli.md)
- [Testing and CI](reference/testing.md)
