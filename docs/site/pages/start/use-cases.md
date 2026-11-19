# Use cases

TMS NeuroPilot is one controller with four run modes. The GUI, relay protocol and
analysis are the same in all of them; only the hardware behind the roles
changes. This page maps the modes to the ways teams use the suite.

| Use case | Coil | Neuronavigation | Stimulator | MEP | Command |
|---|---|---|---|---|---|
| [Real experiment, robot](#real-experiment) | robot | InVesalius | real | real EMG | `neuropilot real` |
| [Real experiment, manual](#real-experiment) | operator | InVesalius | real | real EMG | `neuropilot manual` |
| [Virtual experiment](#virtual-experiment) | virtual robot | `sim_nav` | virtual | virtual EMG | `neuropilot sim` |
| [Training, real TMS](#training-real-tms-simulated-meps) | operator | InVesalius | real | virtual EMG | `neuropilot training` |

## Real experiment

The production path. The subject is prepared as described in
[Subject data](prepare/subject-data.md); InVesalius tracks the coil and the head,
the robot driver moves the coil, the stimulator fires, and the EMG computer
records the response. TMS NeuroPilot runs the mapping loop and analyses each pulse.

Use the robot when the coil must be held precisely for many placements:

```bash
neuropilot real
```

Use manual mode when the operator holds the coil, when the robot is unavailable,
or when you want to isolate a robot problem from the rest of the pipeline:

```bash
neuropilot manual
```

The operational checklist is in [Real session checklist](run/real.md); the
manual workflow is in [Manual mode](run/manual.md).

## Virtual experiment

No hardware and no subject. The simulated stack starts the relay, the virtual
neuronavigation, the virtual robot and the controller in one terminal:

```bash
neuropilot sim
```

The controller runs the same state machine and the same analysis as a real
session. The E-field comes from the project library (or the online solver), and
the virtual EMG turns that field into a synthetic MEP at the configured channel
sources.

Use it to:

- learn the GUI and the mapping loop without a subject;
- develop and debug the controller, relay, robot or analysis;
- reproduce a real-session problem with the same code paths;
- demonstrate the system and train new operators.

Start with [Quick start](start/quickstart.md), then follow
[A simulated session](run/simulated.md) for the wire-level walkthrough.

## Training: real TMS, simulated MEPs

The in-between case: a real stimulator and coil on a printable phantom, real
InVesalius tracking, the operator holding the coil, and no real EMG. The MEP
trace is synthesized from the E-field, so the trainee sees and hears real pulses
and works through the real positioning, navigation and safety loop while the
response and the R² map are simulated.

```bash
neuropilot training
```

Start the production relay and InVesalius, then the controller:

```bash
python relay_server.py 5000
python app.py --remote-host http://localhost:5000
neuropilot training
```

No robot driver and no EMG PC are needed. `--launch-relay` starts the production
relay from `TMS_ROBOT_CONTROL_PATH` as in real mode.

### E-field and sources

The channel sources are project data, exactly as in the virtual twin: the
project defines which cortical element drives which channel. The
[Config › Simulation](gui/config.md) page shows the configured channels and the
sources file; edit the mapping in the Project tab.

- **Precomputed mode** uses the library row for the target, like a simulated
  session.
- **Online mode** uses the field computed from the realised coil pose, like a
  real experiment.

The stimulator amplitude is the real amplitude set in the session, so the
synthetic MEP scales with it.

### Physical setup

- The example dataset includes `ernie_skin_printable.stl` for printing the skin
  surface. Any other phantom works too.
- Mount the printed skin rigidly and attach a tracked head reference. Register
  the phantom to the Ernie mesh in InVesalius with landmarks or fiducials before
  tracking the coil.
- The printable file is a skin surface, not a complete head. The coil needs a
  stable surface and the head reference must stay fixed relative to it.
- A real stimulator firing into a coil over plastic sees an air load. Check the
  coil temperature, duty cycle and the stimulator's own limits; the sound and
  the coil movement are real, the MEP is not.
- The operator follows the same *Coil at target* gate as in manual mode. The
  robot is not used in training; use real mode with a real EMG for robot
  positioning.

!!! note "Training is manual"
    The operator holds the coil. The mode exists to train the stimulation,
    navigation and decision loop with real pulses, not to test robot control.

## Choosing a use case

| If you want to... | Start with |
|---|---|
| learn the interface | [Quick start](start/quickstart.md) |
| run a real experiment with the robot | [Real session checklist](run/real.md) |
| run a real experiment by hand | [Manual mode](run/manual.md) |
| test or debug without hardware | [A simulated session](run/simulated.md) |
| train operators with real pulses | [Run modes](run/modes.md), then `neuropilot training` |

## Next

- [Quick start](start/quickstart.md): run the simulator.
- [Run modes](run/modes.md): the full mode comparison.
- [EMG channels and MEP windows](prepare/emg.md): the virtual EMG and its settings.
