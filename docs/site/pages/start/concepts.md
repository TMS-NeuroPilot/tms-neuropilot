# Key concepts

Every other page assumes the vocabulary on this one. It is short on purpose:
five quantities, one loop.

## The five quantities

| Quantity | What it is | Where you meet it |
|---|---|---|
| **Target** | A coil pose the protocol wants stimulated: a position and an orientation, in SimNIBS head space. | `search_positions.hdf5` (the placements library), the target-order file |
| **Pulse** | One stimulation at one target. A target is usually repeated `n_repetitions` times. | the Control page, the results CSV |
| **E-field** | The electric field that pulse delivered to each element of the cortical region of interest, in V/m. | `e.hdf5` (precomputed) or the online solver |
| **MEP** | The peak-to-peak amplitude of the EMG response that pulse evoked, per channel, in mV. | the MEP results page, the results CSV |
| **R²** | How well the MEP amplitudes are explained by the E-field, per cortical element and per channel. | the Cortical results page, the exported `_roi_r2.csv` |

The point of the software is the last row: a map of R² over the cortex says
*where* the stimulation effect is best explained by the field the coil
delivered — a data-driven localisation of the stimulated site.

## The loop

<figure>
  <img src="assets/diagrams/mapping-loop.svg" alt="The seven-step mapping loop: INIT, SEND_MARKER, START_TRACKING, WAIT_FOR_TARGET_REACHED, FIRE_STIM, COLLECT_DATA, ANALYSE, COMPLETE.">
  <figcaption>One pulse is one pass through the loop. The E-field row for the
  pulse is chosen or computed while the robot is still moving, so the analysis
  has everything it needs when the EMG arrives.</figcaption>
</figure>

1. **Choose the next target** — the next entry of the target-order file, or a
   new marker requested from the neuronavigation.
2. **Move the coil** — the robot receives the target pose, plans, moves and
   presses the coil against the head.
3. **Wait for the target** — the neuronavigation reports the realised coil pose
   and whether it is within tolerance (`Coil at target`).
4. **Fire** — the stimulator delivers one pulse at the configured amplitude.
5. **Collect** — the EMG is recorded and the MEP is extracted from the window
   around the pulse.
6. **Associate the field** — the E-field of *that* coil pose is taken from the
   precomputed library or solved online.
7. **Analyse** — the pulse is appended to the regression; R² is recomputed and
   the cortical map is redrawn.

The loop repeats until the target list is exhausted or the operator presses
**Finish**. [The mapping loop](run/mapping-loop.md) documents the state machine
in detail; [E-field modes](run/efield-modes.md) covers step 6.

## Why the E-field is per pulse

A naive mapping assumes every pulse delivers the same field to the same spot.
In practice the coil sits a few millimetres away from the planned pose, the
head moves, and the handle angle changes. The field therefore differs between
pulses, and a regression against a nominal field blurs the map.

NeuroPilot records the field of the realised pose for every pulse. Each row of
the regression is `(E-field vector, MEP amplitude)` for one pulse, so a pulse
that landed 3 mm off contributes the field it actually delivered. This is also
why the E-field mode can be switched mid-run without corrupting anything: the
mode decides how the row is produced, not what the row means.

## The regression

After at least **three pulses**, the analysis fits, for each EMG channel and
each ROI element:

```text
MEP_amplitude  ~  f(E_field at that element)
```

The coefficient of determination of that fit is the R² you see on the mesh. One
fit per element is what makes the map: elements where the field varies with the
response in a consistent way get a high R²; elements where it does not get a
low one.

The shape of `f` is selectable per study (nine options, see
[Analysis and fits](results/analysis.md)). The default is a linear fit; a
sigmoid is closer to the physiological recruitment curve but needs more pulses
to constrain four parameters.

!!! note "R² is not a significance test"
    A high R² says the field explains the variance in this sample. It does not
    say the effect is significant, nor that the element is the source of the
    MEP. Treat the map as a localisation aid and report it with the pulse count,
    the fit function and the E-field mode.

## What the three modes change

The quantities above are identical in all three run modes. Only who provides
the peers changes:

| Mode | Neuronavigation | Robot | Stimulator | EMG |
|---|---|---|---|---|
| `sim` | virtual (`sim_nav`) | virtual MuJoCo (`sim_robot`) | virtual | virtual |
| `real` | InVesalius | `tms-robot-control` | MagVenture via `magicpy` | CED 1401 share |
| `manual` | InVesalius | none — the operator moves the coil | MagVenture | CED 1401 |

[Run modes](run/modes.md) compares them in full.

## What NeuroPilot is not

- It is **not a medical device**. It is research software; every real session
  needs ethics approval and local MR-safety rules.
- It is **not a neuronavigation system**. It asks InVesalius to create markers
  and reports realised coil poses; it does not track the head itself.
- It is **not a stimulator driver**. It sends fire commands over a serial line
  and TTL pulse; the stimulator's own safety limits still apply.
- It is **not a robot controller**. It sends poses; the robot controller owns
  the motion, the force limits and the collision checking.

## Next

- [Units and frames](start/units.md) — the coordinate conventions that make the
  targets make sense.
- [Architecture](reference/architecture.md) — the processes behind the loop.
- [The mapping loop](run/mapping-loop.md) — the state machine, step by step.
