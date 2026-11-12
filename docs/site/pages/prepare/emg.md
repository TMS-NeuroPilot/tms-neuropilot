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
| `element_id` | 0-based index into the ROI triangles (the E-field columns) |
| `xyz` | position in mm in SimNIBS space; the nearest ROI vertex is used |

If the file has fewer entries than channels, the remaining channels have no
source; the map for them stays empty. If it has more, the extra entries are
ignored. Both cases are reported in the log.

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

## The virtual EMG (simulation)

In simulation the "EMG" is generated from the E-field and the channel sources:
the virtual amplifier adds noise and a recruitment curve on top of the field at
the channel's source element. Constants live in
`controller/systems/virtual_emg.py` (a tuning constant, not an operator
setting).

Consequences for a simulated session:

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
