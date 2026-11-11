# The mapping loop

The controller is a state machine. Each target runs `INIT → … → COMPLETE`; the
loop then moves to the next repetition or the next target. This page documents
the steps, the gates and the escape hatches.

<figure>
  <img src="assets/diagrams/state-machine.svg" alt="The controller state machine: INIT, SEND_MARKER, START_TRACKING, WAIT_FOR_TARGET_REACHED, FIRE_STIM, COLLECT_DATA, ANALYSE, COMPLETE, with SKIP as an escape.">
  <figcaption>Seven steps per pulse. `SKIP` completes the current target from
  any step; `Finish` ends the whole session.</figcaption>
</figure>

## The steps

| Step | What it does | Leaves when |
|---|---|---|
| `INIT` | the state before the first target; per-target flags are reset by `reset_algorithm()` | immediately |
| `SEND_MARKER` | sends `External Controller to Neuronavigation: Create Marker` with the target pose and a label | after the message is queued |
| `START_TRACKING` | waits **3 s** for the neuronavigation to accept the marker, then sends `Press robot button` (skipped in manual mode) | after 3 s |
| `WAIT_FOR_TARGET_REACHED` | waits for *Coil at target*, force above threshold (robot mode) and the minimum interval | all three hold |
| `FIRE_STIM` | fires the stimulator; records the fire time on the monotonic clock | the stimulator accepted the command |
| `COLLECT_DATA` | waits for the realised pose, reads the EMG, extracts the MEP, stores the E-field row | the pulse is recorded (or skipped) |
| `ANALYSE` | appends the pulse and triggers a background fit every third pulse | immediately |
| `COMPLETE` | next repetition, next target, or the end | — |

The per-frame loop calls the matching `<name>_step` function and sleeps 50 ms
between iterations. Every step must return quickly; the slow work (FEM, EMG
reads, fits) runs in executors or background tasks.

## The gates in `WAIT_FOR_TARGET_REACHED`

A pulse is fired only when **all** of these are true:

1. **Coil at target** — the neuronavigation confirmed the realised pose
   (`From Neuronavigation: Coil at target`).
2. **Force** — the robot's force reading exceeds `pressure_thresh` (1). Manual
   mode skips this gate.
3. **ISI** — at least `minium_isi` seconds have passed since the previous pulse,
   measured on the **monotonic** clock so a system-time jump cannot shorten it.

The step keeps the robot's press button active while it waits and releases it
when it advances (`Stopping target tracking.`).

## Escape hatches

| Action | Implementation | Result |
|---|---|---|
| **Next** (skip) | `switch_step("skip")` → `COMPLETE` | the current target is abandoned; the next order entry starts |
| **Back** | `switch_step("previous")` → decrement the order index, reset repetitions | the previous target is repeated |
| **Pause** | checked before the pulse and between targets | the coil stays on target |
| **Finish** | `is_finished = True` | the loop ends after the current step; results are written |
| **Move Coil Up** | stop + pause + `Set objective: 2` | the robot retracts |
| step raises | `_abort_run()` | the run stops, the error is logged, collected data is kept |

**Back** is ignored while the pulse is in flight:

```text
Previous ignored: a pulse is in flight.
```

**Finish** and **Next** work even when a system is unhealthy. The health gate
only blocks the work steps, never the operator's ability to stop.

## Health holds

Before each work step the controller checks all systems. If one is in an error
state the loop holds:

```text
Held at WAIT_FOR_TARGET_REACHED: robot not ready. Finish ends the session.
```

When the system recovers:

```text
All systems ready again, continuing.
```

This is deliberate: a dropped EMG or robot should not silently abandon a
session, and it should not keep stimulating either.

## Repetitions and ordering

- The target order is a list of **0-based** placement indices.
- `n_repetitions` repeats the same target before advancing.
- Without an order file the controller visits every placement in file order.
- `current_target_order_idx` is the position in the order list; it is what the
  status line shows as `pulse N`.

## Timing constants

| Constant | Default | Where |
|---|---|---|
| navigation settle time | 3 s | `start_tracking_step` |
| collect timeout | 20 s (`COLLECT_TIMEOUT_S`) | `collect_data_step` |
| EMG file timeout | 5 s (`EMG_TIMEOUT_S`) | `_read_emg` |
| aim-error warning | 5 mm (`MAX_AIM_ERROR_MM`) | `collect_data_step` |
| minimum ISI | `minium_isi` (project file) | `wait_for_target_reached_step` |
| frame sleep | 50 ms | the run loop |

## What is reset per target

`reset_algorithm()` clears the flags that belong to one pulse: target reached,
target created, realised target, the previous pulse's fire time, the "go back"
flag and the per-step log state. A new flag added to the loop must be reset
there, or it leaks into the next target.

## Failure semantics

- One failing step aborts the **run**, not the process: the error is logged with
  a traceback, `aborted_by` is set, and the results collected so far are kept.
- A failed analysis is logged but does not abort the run.
- A missing realised pose after `COLLECT_TIMEOUT_S` skips the pulse:
  `No realized target after 20 s -- pulse skipped.`
- A missing EMG file is recorded without a MEP:
  `[WARN] no new EMG file for this pulse …`

## Where to look in the code

| Function | File |
|---|---|
| `run_experiment` | `controller/pipeline_controller.py` |
| `send_marker_step`, `start_tracking_step`, `wait_for_target_reached_step` | same |
| `fire_stim_step`, `collect_data_step`, `analyse_step` | same |
| `switch_step`, `reset_algorithm` | same |
| `Step` enum | same file, near the top |

## Next

- [E-field modes](run/efield-modes.md)
- [Analysis and fits](results/analysis.md)
- [Add a component](extend/components.md) — if the loop needs a new peer.
