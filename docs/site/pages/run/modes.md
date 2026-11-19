# Run modes

TMS NeuroPilot has four run modes. They share the controller, the state machine,
the relay protocol and the analysis; they differ only in who provides the
robot, the neuronavigation, the stimulator and the EMG.

Run `neuropilot` with no arguments to choose a mode in the selector, or start a
mode directly with `neuropilot sim`, `real`, `manual` or `training`.

<figure>
  <img src="assets/diagrams/run-modes.svg" alt="The four run modes and the processes each one starts.">
  <figcaption>Simulation replaces all peers with TMS NeuroPilot's virtual twin.
  Real mode uses the lab hardware. Manual mode keeps the hardware but removes
  the robot. Training keeps real stimulation and navigation but replaces the
  EMG with the virtual model and removes the robot.</figcaption>
</figure>

## Comparison

| | `sim` | `real` | `manual` | `training` |
|---|---|---|---|---|
| Command | `neuropilot sim` | `neuropilot real` | `neuropilot manual` | `neuropilot training` |
| Relay | `sim_relay` (started) | production `relay_server.py` | production `relay_server.py` | production `relay_server.py` |
| Neuronavigation | virtual (`sim_nav`) | InVesalius + your tracker | InVesalius + your tracker | InVesalius + your tracker |
| Robot | virtual MuJoCo (`sim_robot`) | your robot via `tms-robot-control` | **none**: operator moves the coil | **none**: operator moves the coil |
| Stimulator | virtual | your stimulator via `magicpy` | your stimulator via `magicpy` | your stimulator via `magicpy` |
| EMG | virtual | your EMG PC's share | your EMG PC's share | virtual, driven by the E-field |
| Hardware needed | none | all of it | stimulator, EMG, tracking | stimulator, tracking |
| E-field modes | both | both | both | both |
| Typical use | development, demos | the experiment | quick tests, coil-handling studies | operator training with real pulses |

The hardware entries name the integration point, not a required device: the
robot driver in `tms-robot-control`, the stimulator driver `magicpy`, and the
SMB share of your EMG acquisition. Any device that speaks those interfaces
works the same way.

`real`, `manual`, and `training` start a local InVesalius automatically when a
launcher is configured. `sim` uses the virtual neuronavigation and does not
start InVesalius. The launcher settings and discovery are described in the
[lab profile reference](config/lab.md).

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

The controller connects to the relay and expects the other roles to be
running. Start order on the lab PC:

```bash
python main_loop.py                          # 1. robot driver
neuropilot real                              # 2. controller + relay + InVesalius
```

`neuropilot real` starts the production relay automatically when
`TMS_ROBOT_CONTROL_PATH` is configured and no relay is already running. If the
path is missing, it asks for the `tms-robot-control` checkout and saves it. It
then starts a local InVesalius after the relay is reachable. InVesalius uses the
conda environment discovered from `CONDA_EXE`, or the values stored in
`~/.neuropilot/lab.yaml`.

If InVesalius is already running elsewhere, use the **Is started** button in
the picker. TMS NeuroPilot then skips the local launch and expects that instance to
connect to the same relay. `--no-invesalius` disables local startup as well.

`main_loop.py` is never started by TMS NeuroPilot. `--launch-relay` remains
accepted for compatibility; a configured relay is now automatic.

!!! danger "Safety: real stimulation"
    Real mode fires a stimulator at a person. Do not start it without ethics
    approval, a trained operator, the stimulator's own limits and a consented
    subject. The checklist is in [Real session checklist](run/real.md).

## Manual

```bash
neuropilot manual
```

Everything of real mode except the robot. The experimenter holds the coil;
InVesalius tracks it and starts automatically by default; the controller waits
for *Coil at target* exactly as it does with the robot. The robot card
disappears from the Connections page and the Start gate no longer waits for a
robot.

Use it when the robot is unavailable, when the coil must be handled by a person,
or to isolate a robot problem from the rest of the pipeline.

## Training

```bash
neuropilot training
```

Real stimulator and real InVesalius, but a virtual EMG. The operator holds the
coil, InVesalius tracks it, the controller waits for *Coil at target*, and the
stimulator fires. The MEP trace is generated from the E-field at the configured
channel sources instead of being recorded.

Start the controller; it starts the production relay when configured and then
InVesalius:

```bash
neuropilot training
```

Use `--no-invesalius` if you want to start InVesalius yourself, or choose
**Is started** when it runs on another machine. No robot driver and no EMG PC
are needed. `--launch-relay` remains accepted for compatibility, but a
configured relay is started automatically.

The channel sources are project data. The [Config › Simulation](gui/config.md)
page shows the configured channel names and the sources file; edit the mapping
in the Project tab. The precomputed E-field mode uses the library row for the
target. The online mode uses the field computed from the realised coil pose,
as in a real experiment.

Use training with the printable Ernie head or any other phantom. The
[Use cases](start/use-cases.md) page covers the phantom, registration and
stimulator caveats.

## Choosing without arguments

```bash
neuropilot
```

opens the mode selector. The chosen mode is what the controller starts in; it
is a launcher, not a setting. For real, manual and training, the selector also
checks the relay and prompts for the `tms-robot-control` path if needed. The
InVesalius picker offers **Select environment**, **Is started** for an external
instance, and **Cancel**.

<figure>
  <img src="assets/screenshots/mode-selector.png" alt="The TMS NeuroPilot mode selector with Simulation, Robotic TMS, Manual TMS and Training buttons.">
  <figcaption>Running <code>neuropilot</code> with no arguments opens the
  TMS NeuroPilot mode dialog. Robotic TMS, Manual TMS and Training modes start
  InVesalius automatically by default.</figcaption>
</figure>

## What is identical

- the six GUI pages and every control,
- the relay topics and payloads (byte-identical to the production components),
- the mapping loop,
- the E-field modes, the regression and the exports,
- the results CSV columns (robot-only fields are empty in manual and training).

## Next

- [Use cases](start/use-cases.md)
- [A simulated session](run/simulated.md)
- [Real session checklist](run/real.md)
- [Manual mode](run/manual.md)
