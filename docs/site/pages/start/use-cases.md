# Use cases

NeuroPilot is one controller with three supported run modes. The GUI, relay
protocol and analysis are the same in all of them; only the hardware behind the
roles changes. This page maps the modes to the ways teams use the suite.

| Use case | Coil | Neuronavigation | Stimulator | MEP | Command |
|---|---|---|---|---|---|
| Real experiment, robot | robot | InVesalius | real | real EMG | `neuropilot real` |
| Real experiment, manual | operator | InVesalius | real | real EMG | `neuropilot manual` |
| Virtual experiment | virtual robot | `sim_nav` | virtual | virtual EMG | `neuropilot sim` |
| Hybrid training | robot or operator | InVesalius | real | virtual EMG | not a run mode yet |

## Real experiment

The production path. The subject is prepared as described in
[Subject data](prepare/subject-data.md); InVesalius tracks the coil and the head,
the robot driver moves the coil, the stimulator fires, and the EMG computer
records the response. NeuroPilot runs the mapping loop and analyses each pulse.

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

## Hybrid training: real TMS, simulated MEPs

This is the in-between case: a real stimulator and coil on a printable Ernie
head, real InVesalius tracking, and a robot or an operator moving the coil, but
no real EMG. The MEP trace is synthesized from the E-field, so the trainee sees
and hears real pulses and works through the real positioning, navigation and
safety loop while the response and the R² map are simulated.

### What already exists

- The example dataset includes `ernie_skin_printable.stl` for printing the
  skin surface.
- `VirtualEMG` generates a trace from the E-field at the configured channel
  source elements; see [EMG channels and MEP windows](prepare/emg.md).
- The controller already feeds the virtual EMG the coil placement and the
  stimulator amplitude, and reads its trace through the same analysis path it
  uses for a real EMG.
- Real mode already drives InVesalius, the robot driver and the real
  stimulator; manual mode replaces the robot with the operator.
- A precomputed E-field library and channel sources for Ernie are part of the
  example project.

### What is missing

The run-mode flag currently selects the stimulator and the EMG together:

- `neuropilot sim` creates a virtual stimulator and a virtual EMG;
- `neuropilot real` and `neuropilot manual` create a real stimulator and the
  real SMB EMG computer.

There is no per-device choice such as "real stimulator, virtual EMG". The
controller branches on the EMG object (`isinstance(..., VirtualEMG)`) and is
ready for that combination, but the launcher, the mode dialog and the mode badge
need a mixed backend selection before this use case becomes a supported run
mode.

### Physical setup

- Print the Ernie skin surface, mount it rigidly, and attach a tracked head
  reference. Register the printed phantom to the Ernie mesh in InVesalius with
  landmarks or fiducials before tracking the coil.
- The printable file is a skin surface, not a complete head. The coil needs a
  stable surface and the head reference must stay fixed relative to it.
- With the robot, a rigid plastic phantom reaches the force limit faster than a
  scalp. Validate the target tolerance and force limit, or start with manual
  mode. A thin compliant layer can make the contact more realistic.
- A real stimulator firing into a coil over plastic sees an air load. Check the
  coil temperature, duty cycle and the stimulator's own limits; the sound and
  the coil movement are real, the MEP is not.
- Use the precomputed library for predictable timing, or the online solver if
  the tracked coil pose should drive the field. The simulated MEP follows the
  planned target, not a physiological response.

!!! warning "Not a supported run mode yet"
    Do not plan a training session around real TMS with simulated MEPs until
    the mixed backend selection is added and tested. The pieces exist, but the
    mode does not.

## Choosing a use case

| If you want to... | Start with |
|---|---|
| learn the interface | [Quick start](start/quickstart.md) |
| run a real experiment with the robot | [Real session checklist](run/real.md) |
| run a real experiment by hand | [Manual mode](run/manual.md) |
| test or debug without hardware | [A simulated session](run/simulated.md) |
| train operators with real pulses | hybrid training, after the backend selection is added |

## Next

- [Quick start](start/quickstart.md): run the simulator.
- [Run modes](run/modes.md): the full mode comparison.
- [EMG channels and MEP windows](prepare/emg.md): the virtual EMG and its settings.
