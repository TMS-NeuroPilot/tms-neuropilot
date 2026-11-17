# EMG channels and MEP windows

The controller does not record EMG itself in a real session; it reads what the
EMG acquisition wrote and extracts the MEP (CED/Signal in the reference setup). Two things must therefore
agree: the **names and count of the channels**, and the **window** in which the
response is searched.

## Channel names and count

`EMG_CHANNELS` in `.env`:

```bash
EMG_CHANNELS=FDI,APB,ADM
```

The list drives:

- the labels on the MEP plots,
- the columns of the results CSV (`mep_FDI_mV`, …),
- the number of channels the cortical map offers,
- the number of entries the channel-source YAML must have.

!!! warning "Restart applies"
    The channel list is read at import time. Changing it in **Config › Study**
    shows the new value, but the running controller keeps the old list until it
    is restarted. The status line says *needs restart* for this reason.

## The channel-source file

A small YAML referenced by the project's `emg_config_fn`, one entry per
channel, assigned **positionally** to `EMG_CHANNELS`:

```yaml
sources:
  - element_id: 5208        # FDI
  - element_id: 5165        # APB
  - xyz: [-16.2, 14.6, 61.9]  # ADM, nearest ROI triangle
```

| Field | Meaning |
|---|---|
| `element_id` | 0-based index into the ROI triangles, also the E-field column index |
| `xyz` | position in mm in SimNIBS space; the nearest ROI triangle centre is used |

The number of entries must equal the number of channels. A mismatch is rejected
and the previous channel assignment stays in use. Both cases are reported in the
log.

!!! note "What the source is used for"
    The source ties a muscle to a cortical site, which is what makes the map
    per-channel rather than a single global fit. It does **not** change where
    the coil goes; that is the placements file.

## The MEP window

All values live in `.env` and are read at import time:

| Key | Default | Unit | Meaning |
|---|---|---|---|
| `SAMPLING_RATE` | 4000 | Hz | acquisition sampling rate |
| `CUTOFF_FREQ` | 500 | Hz | low-pass filter before extraction |
| `TMS_PULSE_TIME` | 5 | tenths of a second | time of the pulse in the recording (5 → 0.5 s) |
| `START_MEP` | 10 | samples | window start, relative to the pulse |
| `END_MEP` | 100 | samples | window end, relative to the pulse |
| `MEASUREMENT_START_TIME` | 0 | samples | first sample kept from the file |

With the defaults the MEP window is `(100 − 10) / 4000 = 22.5 ms` long. A
cortical MEP typically starts 20–30 ms after the pulse; make sure the window
covers the response for the muscle and the latency you expect, not just the
default.

```text
file ──► [MEASUREMENT_START_TIME …] ──► pulse at TMS_PULSE_TIME
                                          │
                             START_MEP ───┼─── END_MEP
                                          ▼
                                   peak-to-peak amplitude
```

## What pynibs computes

The windowed signal is filtered at `CUTOFF_FREQ`, the peak-to-peak amplitude is
taken over the window, and the result is reported in mV. A window that contains
no response yields a small amplitude, not an error — that is a real result and
appears in the table like any other.

The pre-activation period (before the pulse) is displayed on the MEP page but is
not used by the regression.

## The virtual EMG (simulation and training)

In simulation and training the "EMG" is generated from the E-field and the
channel sources:
the virtual amplifier adds noise and a recruitment curve on top of the field at
the channel's source element. The source element is read for every pulse, from
the precomputed row or from the online per-pulse field.

Two response models are available:

- **DVS** (the default): a sigmoid in the E-field itself. `x0` and the slope
  are in V/m, and the input-side noise is also in V/m.
- **TVS**: the nine-coefficient population model. Its input is `E / upper limit`
  (a fraction of maximum stimulator output); `p3`–`p7` are the linear
  coefficients from the original model.

The settings are `.env` keys, read when the controller starts:

| Key | Default | Effect |
|---|---|---|
| `VIRTUAL_MEP_MODEL` | `dvs` | `dvs` or `tvs` |
| `VIRTUAL_MEP_NOISE_MV` | `0.001` | white-noise sigma added to the trace, mV |
| `VIRTUAL_MEP_TRIAL_VARIABILITY` | `true` | trial-to-trial variability of the MEP model |
| `VIRTUAL_MEP_MT` | `60` | field at or below which no MEP is produced, V/m |
| `VIRTUAL_MEP_UPPER_LIMIT` | `100` | TVS normalisation field, V/m |
| `VIRTUAL_MEP_EFIELD_SCALE` | `1.4` | scale applied to the precomputed E-field row |

DVS keys: `VIRTUAL_MEP_DVS_X0` (V/m), `VIRTUAL_MEP_DVS_R` (per V/m),
`VIRTUAL_MEP_DVS_SIGMA_X` (V/m), `VIRTUAL_MEP_DVS_AMP` (mV),
`VIRTUAL_MEP_DVS_Y0` (mV), and `VIRTUAL_MEP_DVS_SIGMA_Y` (log10 units).

TVS keys: `VIRTUAL_MEP_TVS_P1`…`P9`. `p1`/`p2` are log10 terms; `p3`–`p7` are
linear values, `p8` is V, and `p9` is dimensionless. `VIRTUAL_MEP_MT` remains
the no-response cutoff for both models. `VIRTUAL_MEP_TRIAL_VARIABILITY` turns
the model's trial-to-trial variability on or off; turning it off gives an ideal,
repeatable curve. All keys are in the
[`.env` reference](config/env.md). The same values are editable on
[Config › Simulation](gui/config.md).

Consequences for a simulated or training session:

- the MEP depends on the coil pose, so the map is not flat noise;
- `EMG_CHANNELS` still decides how many channels exist;
- the channel sources still decide which field drives which channel.

## Plots

| Key | Default | Where the files go |
|---|---|---|
| `EMG_PLOTS_FOLDER_PATH` | `emg_plots` | relative to `ROOT_FOLDER` |
| `P2P_PLOTS_FOLDER_PATH` | `p2p_plots` | relative to `ROOT_FOLDER` |

One plot per pulse in the first folder, one peak-to-peak trend plot in the
second. Both are diagnostic: the CSV is the data, the plots are for the
operator.

## Checks before a session

- [ ] `EMG_CHANNELS` matches the amplifier's channel count.
- [ ] the source YAML has one entry per channel and the indices resolve.
- [ ] the window covers the expected latency at the configured sampling rate.
- [ ] `TMS_PULSE_TIME` matches the acquisition's trigger position.
- [ ] the MEP page shows a live trace when you tap the electrode.

## Next

- [The project file](prepare/project.md)
- [MEP results page](gui/mep.md)
