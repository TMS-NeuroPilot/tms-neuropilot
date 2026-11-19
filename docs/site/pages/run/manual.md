# Manual mode

Manual mode runs the real pipeline without the robot: a person holds the coil,
the neuronavigation tracks it, and the controller waits for *Coil at target*
exactly as it does with the robot.

```bash
neuropilot manual
```

or `neuropilot controller --manual` when the relay, InVesalius and the stimulator
are already running.

## What changes

| | Real mode | Manual mode |
|---|---|---|
| Robot process | required | not started |
| Robot card on Connections | present | **absent** |
| Start gate | waits for the robot | ignores the robot |
| Coil positioning | robot | the operator |
| Pressure signal | force sensor | not used |
| Coil pose | robot forward kinematics | tracked coil from the neuronavigation |
| Everything else | identical | identical |

The controller sets `manual = True`, which:

- skips `Press robot button` messages,
- skips the force-threshold check in `WAIT_FOR_TARGET_REACHED`,
- keeps the minimum-interval and coil-at-target gates,
- takes the realised pose and the aim error from the **tracked coil** instead of
  the robot's forward kinematics; the pose columns are filled as usual, the
  pressure column is not.

## The workflow

1. Make the relay and InVesalius available as in robo mode; `neuropilot manual`
   starts them automatically when configured.
2. Start the controller: `neuropilot manual`.
3. Load the project.
4. On **Control**, choose an E-field mode. Both work; precomputed still needs
   the library and the placements.
5. Press **Start**. The controller creates the first marker.
6. Move the coil until the neuronavigation reports *Coil at target*.
7. The controller fires when the interval has elapsed.

The sequence then repeats for the next target. With a precomputed library the
coil must be at the planned pose, because the field row belongs to that
placement; the operator's job is to reach it within tolerance.

!!! tip "Manual mode is the fastest way to test the pipeline"
    It removes the robot from the loop while keeping the real stimulator, EMG,
    tracking and analysis. If a problem disappears in manual mode, it is in the
    robot or its driver — not in the controller.

## Caveats

- **Target tolerance matters more.** A hand-held coil drifts; a pulse whose
  realised pose is far from the planned one is flagged
  (`coil was N mm from the planned placement`) and, with a precomputed library,
  the field used is the planned one, not the delivered one. Check the aim-error
  column in the export.
- **No force feedback.** The pressure column is empty and the operator decides
  the contact.
- **No free-drive / objective messages.** The `Enable free drive` button on the
  Control page has no effect in manual mode.
- **The robot view is empty.** There is no simulated robot in robo modes; the
  Control page shows no 3-D arm.

## When to use it

- Commissioning the stimulator, EMG or tracking without the robot.
- A protocol that requires hand-held stimulation.
- Isolating a fault: if the session runs in manual mode, the controller, relay,
  InVesalius and stimulator are fine.

!!! note "Training"
    Training mode is manual positioning with a real stimulator and a virtual
    EMG. See [Run modes](run/modes.md) and [Use cases](start/use-cases.md).

## Next

- [E-field modes](run/efield-modes.md)
- [The mapping loop](run/mapping-loop.md)
