# Control page

The **Control** page runs the session: stimulation settings, the E-field mode,
the transport buttons, the robot view and the log.

<figure>
  <img src="assets/screenshots/control-precomputed.png" alt="The Control page with the precomputed E-field mode selected and Start enabled.">
  <figcaption>Transport buttons at the top, stimulation and E-field cards on the
  left, robot speeds and the log on the right.</figcaption>
</figure>

## Transport row

| Button | Action | Notes |
|---|---|---|
| **Move Coil Up** | stop, pause, retract the robot | the safest way to interrupt |
| **Back** | repeat the previous target | ignored while a pulse is in flight |
| **Start / Pause** | start the mapping; while running, pause before the next pulse | the label toggles |
| **Next** | skip the current target | implemented as `skip` → `COMPLETE` |
| **Finish** | end the session after the current step | always enabled during a run |

In the top-right corner of the robot view: **Total targets** (the length of
the order list) and **Current** (the pulse counter and the active target).

## Stimulation card

| Control | Range | Effect |
|---|---|---|
| **Amplitude** slider + spin | 0–100 % MSO | sets the stimulator output; the slider and spin mirror each other |
| **Repetitions** | 1–100 | pulses per target |
| **Min. interval** | 1–60 s | minimum ISI, measured on the monotonic clock |
| **Pulse shape** | Biphasic / Monophasic | stimulator waveform |
| **Enable** | — | arms the stimulator for a single manual pulse |
| **Fire** | — | fires one pulse; only after **Enable** |

!!! danger "Safety: amplitude changes reach the stimulator"
    Moving the amplitude slider sends `set_amplitude_stim` immediately. Confirm
    the value on the stimulator itself before the first pulse, and never change
    it while a pulse is in flight.

The **Fire** button is for testing a single pulse outside the loop. It is gated
on **Enable** and is independent of the mapping; arming does not start a
session.

## E-Field card

| Control | Meaning |
|---|---|
| **Precomputed E-Field** | use the library loaded in the project |
| **Online E-Field** | solve the field per pulse with SimNIBS |
| **Interpolated** | interpolate the field from the dense library (`surrogate_library_path`), with a domain guard |
| hint line | what the mode is doing now (see [E-field modes](run/efield-modes.md)) |

Start is disabled until a mode is selected. The mode is switchable during a run;
pulses are held while the online solver warms up or the interpolated library
loads.

## Robot card

| Control | Meaning |
|---|---|
| **Enable free drive** | let the operator move the arm by hand (real mode) |
| **Default speed** | speed while travelling between targets, % |
| **Tuning speed** | speed near the head, % |

Both speeds are pushed to the robot when a session starts, so the robot runs
with the values shown in the GUI rather than its power-on defaults.

## Log card

A read-only log of the state machine:

```text
=== BEGIN TARGET 000 (1/1) ===
Sending target to InVesalius!
Tracking target with robot!
Stopping target tracking.
Firing Stimulator!
```

Health holds, skipped pulses, aim-error warnings and analysis messages appear
here too. The same lines are printed to the terminal.

## Robot view

In simulation the lower right shows the MuJoCo scene: the arm, the head model
and the coil. It is a rendering of the robot's joint state, not a measurement.

In real, manual and training modes there is no robot scene.

## Button gating

| Condition | Effect |
|---|---|
| no E-field mode | Start, Next, Back, Move Coil Up disabled |
| precomputed mode without a library | same |
| online mode while the solver warms up | Start disabled until ready |
| a system in error | Start disabled; during a run the loop holds |
| run in progress | Finish always enabled |

## Keyboard and accessibility

The window scales with `NEUROPILOT_UI_SCALE`; see
[Themes and display](gui/themes.md). The buttons expose their labels as
accessibility names, and the log is selectable text so it can be copied into a
bug report.

## Next

- [MEP results page](gui/mep.md)
- [The mapping loop](run/mapping-loop.md)
