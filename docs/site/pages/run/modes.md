# Run modes

NeuroPilot has three run modes. They share the controller, the state machine,
the relay protocol and the analysis; they differ only in who plays the other
three roles — robot, neuronavigation and stimulator.

<figure>
  <img src="assets/diagrams/run-modes.svg" alt="The three run modes and the processes each one starts.">
  <figcaption>Simulation replaces all peers with NeuroPilot's virtual twin.
  Real mode uses the lab hardware. Manual mode keeps the hardware but removes
  the robot.</figcaption>
</figure>

## Comparison

| | `sim` | `real` | `manual` |
|---|---|---|---|
| Command | `neuropilot sim` | `neuropilot real` | `neuropilot manual` |
| Relay | `sim_relay` (started) | production `relay_server.py` | production `relay_server.py` |
| Neuronavigation | virtual (`sim_nav`) | InVesalius + your tracker | InVesalius + your tracker |
| Robot | virtual MuJoCo (`sim_robot`) | your robot via `tms-robot-control` | **none** — operator moves the coil |
| Stimulator | virtual | your stimulator via `magicpy` | your stimulator via `magicpy` |
| EMG | virtual | your EMG PC's share | your EMG PC's share |
| Hardware needed | none | all of it | stimulator, EMG, tracking |
| E-field modes | both | both | both |
| Typical use | training, development, demos | the experiment | quick tests, coil-handling studies |

The hardware entries name the integration point, not a required device: the
robot driver in `tms-robot-control`, the stimulator driver `magicpy`, and the
SMB share of your EMG acquisition. Any device that speaks those interfaces
works the same way.

## Simulation

```bash
neuropilot sim
```

Starts relay → (nav ∥ robot) → controller, in that order, each after its
readiness probe passes. Logs are prefixed by role in one terminal.

```bash
neuropilot sim --components relay,robot       # a subset, for debugging
neuropilot controller --sim                   # controller only (peers already running)
neuropilot relay                              # the simulated relay alone
```

In this mode the controller also shows a live MuJoCo view of the robot in the
Control page, and the virtual EMG is generated from the E-field.

Use it to:

- learn the GUI and the workflow without a subject,
- develop and test changes to the controller, the relay or the analysis,
- reproduce a bug from a real session (the same code paths run),
- demonstrate the system.

## Real

```bash
neuropilot real
```

The controller connects to the relay and expects the other three roles to be
running. Start order on the lab PC:

```bash
python relay_server.py 5000                  # 1. production relay
python app.py --remote-host http://localhost:5000   # 2. InVesalius
python main_loop.py                          # 3. robot driver
neuropilot real                              # 4. controller
```

Or let the controller start the production relay for you:

```bash
neuropilot real --launch-relay
```

which requires `TMS_ROBOT_CONTROL_PATH` to point at a `tms-robot-control`
checkout. InVesalius and `main_loop.py` are never started by NeuroPilot.

!!! danger "Safety — real stimulation"
    Real mode fires a stimulator at a person. Do not start it without ethics
    approval, a trained operator, the stimulator's own limits and a consented
    subject. The checklist is in [Real session checklist](run/real.md).

## Manual

```bash
neuropilot manual
```

Everything of real mode except the robot. The experimenter holds the coil;
InVesalius tracks it; the controller waits for *Coil at target* exactly as it
does with the robot. The robot card disappears from the Connections page and the
Start gate no longer waits for a robot.

Use it when the robot is unavailable, when the coil must be handled by a person,
or to isolate a robot problem from the rest of the pipeline.

## Choosing without arguments

```bash
neuropilot
```

opens a small dialog with the three modes. The chosen mode is what the
controller starts in; it is a launcher, not a setting.

## What is identical

- the six GUI pages and every control,
- the relay topics and payloads (byte-identical to the production components),
- the seven-step mapping loop,
- the E-field modes, the regression and the exports,
- the results CSV columns (robot-only fields are empty in manual mode).

That is deliberate: a session rehearsed in the simulator exercises the same
controller code that runs on the day.

## Next

- [A simulated session](run/simulated.md)
- [Real session checklist](run/real.md)
- [Manual mode](run/manual.md)
