# Study profiles

A study profile is the protocol layer: the values that stay the same for every
subject of a study, as opposed to the project file, which is per subject. It is
a small YAML edited on **Config › Study**.

## What it holds

| Key | Default | Meaning |
|---|---|---|
| `fit_fun` | `Linear` | regression shape used for the R² map |
| `map_elms` | `1` | subsampling: analyse every n-th ROI element |
| `efield_mode` | `Precomputed` | default E-field mode for the session |
| `pulse_shape` | `Biphasic` | stimulator waveform |
| `n_repetitions` | `1` | pulses per target |
| `min_isi` | `4` | minimum inter-stimulus interval, seconds |
| `amplitude` | `20` | stimulator output, % MSO |
| `sampling_rate` | `4000` | EMG sampling rate, Hz |
| `cutoff_freq` | `500` | EMG low-pass, Hz |
| `tms_pulse_time` | `5` | pulse position in the recording, tenths of a second |
| `start_mep` | `10` | MEP window start, samples after the pulse |
| `end_mep` | `100` | MEP window end, samples after the pulse |
| `emg_channels` | `FDI,APB,ADM` | channel names, comma separated |

An example:

```yaml
fit_fun: Sigmoid
map_elms: 1
efield_mode: Precomputed
pulse_shape: Biphasic
n_repetitions: 3
min_isi: 5
amplitude: 42
sampling_rate: 4000
cutoff_freq: 500
tms_pulse_time: 5
start_mep: 10
end_mep: 100
emg_channels: FDI,APB,ADM
```

## Save, load, apply

The three buttons on **Config › Study** are deliberately separate:

| Button | What it does |
|---|---|
| **Save study…** | writes the current values to a YAML (default `<data folder>/study.yaml`) |
| **Load study…** | reads a YAML into the *widgets* — nothing changes in the session yet |
| **Apply to session** | pushes the widget values into the live controls |

This two-step flow lets you inspect a profile before it changes a running
session. The status line reports exactly what happened:

```text
Applied: mapping/stimulation, precomputed E-field · needs restart: MEP windows and EMG channels (restart)
```

### What applies immediately

- fit function and subsampling,
- pulse shape, repetitions, minimum interval, amplitude,
- the E-field mode (if that mode is available).

### What needs a restart

- **MEP windows** (`sampling_rate`, `cutoff_freq`, `tms_pulse_time`,
  `start_mep`, `end_mep`, `measurement_start_time`),
- **EMG channel names**.

The controller parses these at import time, so the running process keeps the old
values. The status line always lists them under *needs restart* — believe it
rather than the widgets.

### What is refused

**Apply to session** does nothing while a mapping is running:

```text
Not applied: a mapping session is running (finish it first).
```

Changing the fit function or subsampling mid-run would change the meaning of the
map that is being built; the controller refuses instead of producing a mixed
result.

## Where to keep it

- Default location: `<ROOT_FOLDER>/study.yaml`, which makes it available to
  everyone using that data folder.
- A study with several protocols can keep one file per protocol
  (`study_rest.yaml`, `study_online.yaml`) and load the right one per session.
- The study profile is **not** copied into the project file. Save both: the
  project says which subject, the study says which protocol.

## Relationship to `.env`

Some study values also exist as environment keys (`EMG_CHANNELS`,
`SAMPLING_RATE`, …). The precedence is:

```text
shell environment  >  .env  >  study profile applied to the session
```

Applying a profile writes into the live controls; it does not edit `.env`. If a
value in `.env` pins the same key, the next restart returns to the `.env` value.
That is intentional: a lab that pins a key in `.env` should not be overridden by
a colleague's study file.

## Next

- [Settings model](config/model.md) — the full precedence picture.
- [Config page](gui/config.md) — the four scopes in the GUI.
