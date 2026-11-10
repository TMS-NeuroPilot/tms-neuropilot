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

## Contributing

- Abdullah Yaseen — `yaseen@cbs.mpg.de` (MPI CBS)
- Samuel Berggren — `berggren@cbs.mpg.de` (MPI CBS)
- Andrew Meng — `mengdrew@umich.edu` (University of Michigan)
- Benjamin Kalloch — `kalloch@cbs.mpg.de` (MPI CBS)
- Konstantin Weise — `konstantin.weise@htwk-leipzig.de` (HTWK Leipzig)
- Thomas R. Knösche — `knoesche@cbs.mpg.de` (MPI CBS)
- Renan H. Matsuda — `renan.matsuda@aalto.fi` (Aalto University)
