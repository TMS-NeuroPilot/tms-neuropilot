# A simulated session

This is the full walkthrough of one mapping session in the simulator: what you
click, what appears in the log, and what the controller is doing on the wire.
It assumes the stack is running ([Quick start](start/quickstart.md)) and a
project is loaded.

## Before Start

1. **Connections**: all four cards green. In simulation they turn green a
   second after the controller connects; if one stays grey, press **Reconnect**.
2. **Control** — choose **Precomputed E-Field**. The hint under the radios says
   *"Precomputed library — ready immediately."* and **Start** becomes enabled.
3. Set **Amplitude** and **Repetitions**. For a first session the defaults are
   fine; `n_repetitions: 1` keeps it short.
4. **Cortical results** — the ROI mesh is displayed. No map is shown yet.

!!! note "Start is grey"
    Start is enabled only when the robot (or manual mode), the stimulator, the
    EMG and the E-field mode are all ready. A grey Start is a status, not a bug:
    the hint under the E-field radios says which condition is missing.

## Press Start

The first target appears in the status line:

```text
pulse 0 · 1/1 · target 44
```

and the log shows:

```text
=== BEGIN TARGET 000 (1/1) ===
```

The controller now runs the seven steps for this target:

| Step | What happens | What you see |
|---|---|---|
| `SEND_MARKER` | sends the coil pose to the neuronavigation as a marker | `Sending target to InVesalius!` |
| `START_TRACKING` | waits 3 s for the nav to be ready, then asks the robot to press | — |
| `WAIT_FOR_TARGET_REACHED` | waits for *Coil at target* | the robot arm moves in the MuJoCo view |
| `FIRE_STIM` | fires the stimulator | a pulse marker on the EMG trace |
| `COLLECT_DATA` | records the EMG, extracts the MEP, stores the field row | a new row on the MEP results page |
| `ANALYSE` | appends the pulse to the regression | R² appears after three pulses |
| `COMPLETE` | next repetition or next target | a new `=== BEGIN TARGET ===` block |

## While it runs

- The **Control** page shows the current target, the pulse count and the log.
- The **MEP results** page draws the live trace and the peak-to-peak trend.
- The **Cortical results** page redraws the map after each analysis task.

You can:

| Action | Effect |
|---|---|
| **Pause** | holds before the next pulse; the coil stays on target |
| **Start** | resumes from where it stopped |
| **Next** | skips the current target and moves to the next order entry |
| **Back** | repeats the previous target (ignored while a pulse is in flight) |
| **Move Coil Up** | stops, pauses and retracts the robot |
| **Finish** | ends the session after the current step, writes the results |

!!! tip "Pause works inside a target"
    Pause is checked before the pulse, not only between targets. The robot keeps
    the coil on the head while paused, so a subject can relax without losing the
    target.

## When something is unhealthy

If a system drops out mid-run, the loop holds instead of aborting:

```text
Held at WAIT_FOR_TARGET_REACHED: robot not ready. Finish ends the session.
```

The operator can fix the system (press **Reconnect**) and the loop continues:

```text
All systems ready again, continuing.
```

**Finish** is always available during a run, even when a system is dead — a
session must always be stoppable.

## Finishing

Press **Finish**. The controller stops after the current step, retracts the
robot, waits for the final analysis and writes the results CSV to the project's
`results_fn`:

```text
Finish pressed.
We are done.
```

The controller does not print a "written" line; check the file's modification
time or open it. In simulation, finish with a handful of pulses and open the
CSV — one row per pulse with the realised pose, the amplitude, the MEP per
channel and the E-field mode. See
[Export and data formats](results/export.md).

## What the log tells you

A healthy target looks like this (abridged):

```text
=== BEGIN TARGET 000 (1/1) ===
Sending target to InVesalius!
Tracking target with robot!
Stopping target tracking.
Firing Stimulator!
Analyses started, moving to next target
```

With fewer than three pulses the analysis step says so instead of fitting:

```text
Skipping analysis (N samples 1 < 3).
```

A pulse whose realised pose never arrives from the neuronavigation is dropped
rather than recorded with the wrong geometry:

```text
No realized target after 20 s -- pulse skipped.
```

The timeout is `COLLECT_TIMEOUT_S` (default 20 s). While the controller is
waiting for the robot, there is no timeout: use **Next** to skip the target or
**Finish** to end the session.

## Next

- [The mapping loop](run/mapping-loop.md) — the same loop, in detail.
- [E-field modes](run/efield-modes.md) — switch to online mid-session.
