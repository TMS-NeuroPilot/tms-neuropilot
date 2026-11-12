# Analysis and fits

This page explains what happens between "the MEP arrived" and "the map is on
screen": the regression matrix, the fit, how R² is computed and the guards
around them.

## From pulses to a matrix

For each pulse the controller stores:

```python
pulse_e_fields[i] = array(n_elements)   # or None if no field was available
pulse_modes[i]    = "precomputed" | "online" | "surrogate"
mep_history[ch][i] = amplitude_mV       # or NaN
```

The analysis (`assemble_analysis_matrix`) then:

1. drops the pulses the operator excluded,
2. drops the pulses whose E-field is `None`,
3. returns the kept indices **and** the matching matrix rows.

Dropping is never silent:

```text
[WARN] 2 pulse(s) without an E-field were left out of the map (12 used).
```

and the MEP history is filtered with the same indices, so row *k* of the matrix
always belongs to MEP *k*.

## The three-pulse floor

The regression needs at least **three** pulses. Below that the analysis returns
without fitting and the GUI keeps saying *"No R² map yet — needs at least three
pulses."*

The analysis runs after every third pulse (the `ANALYSE` step triggers it), and
once more at the end of the session.

## Per channel

Each EMG channel is fitted independently:

```text
for channel in EMG_CHANNELS:
    meps = [finite MEP values for the kept pulses]
    scores = regress_data(E_subset, meps, fun=fit_fun)   # one R² per element
```

Guards:

- fewer than three finite MEPs → no map for that channel,
  `[WARN] channel FDI: only 2 finite MEP(s) -- no map for this channel.`
- some non-finite MEPs → those pulses are dropped for that channel only,
  `[WARN] channel FDI: 1 MEP(s) were not measurable and are left out.`
- a length mismatch between matrix and MEP vector → the channel is skipped.

## The fit functions

The nine shapes come from `pynibs.expio.fit_funs`; the display name is what the
project file stores:

| Display name | Shape |
|---|---|
| `Linear` | straight line |
| `Linear (log)` | line against log(response) |
| `Sigmoid` | 4-parameter sigmoid (pynibs' default) |
| `Sigmoid (3-parameter)` | sigmoid with fixed lower asymptote |
| `Sigmoid (log)` | 4-parameter sigmoid against log(response) |
| `Exponential` | exponential with offset |
| `Exponential (no offset)` | exponential through the origin |
| `Exponential (log)` | exponential against log(response) |
| `Step` | step function |

The "(log)" variants model the logarithm of the MEP; the others the raw
peak-to-peak amplitude. `Linear` is the default because it needs the fewest
pulses to be stable; a sigmoid is closer to the physiological recruitment curve
but four parameters need more data.

## Subsampling

`map_elms` (GUI: **Subsampling**) analyses every n-th ROI element:

- `1` — every element, the full map;
- `2`, `3`, … — faster, coarser, fewer multiple-comparison opportunities.

The value is stored in the project file and refuses to change during a run
(`map_elms` is set when the analysis starts).

## What R² means here

For each element *e* and channel *c*:

```text
R²(e, c) = 1 - SS_res / SS_tot
```

of the fit `MEP ~ f(E(e))` across the collected pulses. It measures how much of
the MEP variance the field at that element explains. It is **not** a
significance test, and it is not corrected for multiple comparisons across
elements; treat it as a localisation aid.

Practical reading:

| Pattern | Interpretation |
|---|---|
| one focal hot spot | the response is consistent with a source there |
| broad high-R² band | the field varies smoothly; many elements co-vary |
| high R² on few pulses | unstable — collect more before interpreting |
| map changes completely after 3 pulses | too few samples; wait for 10+ |

## Reporting a map

The map is only interpretable together with its acquisition and analysis
choices. Record at least:

- the number of pulses used and the number excluded, with the reason;
- the fit function and the subsampling factor (`map_elms`);
- the E-field mode per pulse, especially for a mixed session;
- the E-field library provenance (`target_source`, `search_radius_mm`,
  `roi_hash`) or the online solver settings;
- the coil model, neuronavigation registration quality and aim-error summary;
- the ROI definition and the element count.

Do not report R² as a significance value or as a causal source estimate. A
useful figure states the pulse count and the scalar range next to the map.

## How the analysis runs

- It runs in a `ProcessPoolExecutor`, one task per channel, so the GUI and the
  mapping loop stay responsive.
- A generation counter invalidates superseded runs: if you exclude a pulse or
  load another library while a fit is running, the older result is discarded
  (`discarding a superseded analysis result`).
- Results are delivered to the GUI through a Qt signal, not by touching widgets
  from the worker.

## Warnings you may see

| Message | Meaning |
|---|---|
| `Skipping analysis (N samples 3 < 3).` | not enough pulses yet |
| `Skipping analysis (Only N valid pulses).` | too few usable pulses |
| `Skipping analysis: N pulse(s) with an E-field (need 3).` | too many dropped rows |
| `channel X: only N finite MEP(s)` | the EMG had no usable response |
| `channel X: N MEP(s) were not measurable` | partial sweeps |
| `Analysis failed for X: …` | the fit raised; the other channels continue |
| `discarding a superseded analysis result` | a newer analysis is running |

## Next

- [Export and data formats](results/export.md)
- [Cortical results page](gui/cortical.md)
- [E-field modes](run/efield-modes.md)
