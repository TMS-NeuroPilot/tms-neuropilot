# Config page

**Config** collects the four configuration scopes in one place:

| Sub-tab | Scope | File it edits |
|---|---|---|
| **Lab (hardware)** | this machine | `~/.neuropilot/lab.yaml` (+ a few `.env` keys) |
| **Simulation** | this machine's simulated MEP | `.env` (`VIRTUAL_MEP_*`) |
| **Study (mapping)** | this protocol | a study YAML, applied to the session |
| **Subject (files)** | this subject | the project YAML, via the Project page |

The precedence between the files is on [Settings model](config/model.md); this
page documents the controls.

## Lab (hardware)

<figure>
  <img src="assets/screenshots/config-lab.png" alt="Config › Lab with the session, robot, stimulator, EMG computer and E-field solver cards.">
  <figcaption>Config › Lab. Fields pinned by `.env` carry a tooltip and are
  counted in the status line.</figcaption>
</figure>

### Session

| Field | Key | Applies |
|---|---|---|
| **Mode** | — | read-only badge: Simulated / Real / Manual / Training |
| **Relay host + port** | `RELAY_HOST`, `RELAY_PORT` | after restart |
| **Data folder** | `ROOT_FOLDER` | after restart |
| **UI scale** | `NEUROPILOT_UI_SCALE` | after restart |
| **Theme** | `UI_THEME` | **immediately** |

### Robot

| Field | Key | Notes |
|---|---|---|
| **Model** | `ROBOT` | the list comes from `sim_robot/robots.py`; an unknown value stays visible and is reported on save |
| **tms-robot-control** | `TMS_ROBOT_CONTROL_PATH` | used by `--launch-relay` and the Relay card to start the production relay |

### Stimulator

| Field | Key |
|---|---|
| **Serial port** | `STIMULATOR_PORT` |
| **TTL port** | `STIMULATOR_TTL_PORT` |

### EMG computer

| Field | Key |
|---|---|
| **Computer IP** | `EMG_COMPUTER_IP` |
| **SMB user** | `EMG_COMPUTER_USERNAME` |
| **Password** | `EMG_COMPUTER_PASSWORD` |

### E-field solver

| Field | Key | Values |
|---|---|---|
| **Solver** | `ONLINE_FEM_SOLVER` | `pardiso`, `amg` |
| **Anisotropy** | `ONLINE_FEM_ANISOTROPY` | `scalar`, `vector` |

These are used only when the online E-field mode is selected.

### Save and reload

- **Save lab profile** writes `lab.yaml` **and** the analysis keys shown on the
  Study tab (`EMG_CHANNELS`, `SAMPLING_RATE`, `CUTOFF_FREQ`, `TMS_PULSE_TIME`,
  `START_MEP`, `END_MEP`) to `.env`, preserving comments and unknown keys.
  That split is deliberate: hardware is portable between projects, the analysis
  windows are read at import and must live where the bootstrap reads them.
- **Reload** re-reads `lab.yaml` and `.env` and marks every field that `.env`
  overrides.
- The status line reports the file and the override count:
  `Loaded lab.yaml (~/.neuropilot/lab.yaml) · 2 key(s) overridden by .env`.
- Saving says: `Saved lab.yaml — restart NeuroPilot to apply.` The theme is the
  exception: it applies before you save.

!!! warning "`.env` wins"
    A key that `.env` defines cannot be changed from this page: the field is
    written to `lab.yaml`, but the next start still reads the `.env` value. The
    tooltip says so, and the status line counts them. Remove the line from
    `.env` (or change it there) if the GUI value should win.

## Simulation

The Simulation page tunes the virtual EMG. It is used in simulation and
training modes; the fields are disabled in real and manual modes. The controller reads the
values when it starts, and **Save simulation settings** writes `.env`, so
restart to apply.

<figure>
  <img src="assets/screenshots/config-simulation.png" alt="Config › Simulation with the MEP model fields and the project MEP source summary.">
  <figcaption>Config › Simulation. The MEP model is machine-local tuning; the
  channel sources remain project data.</figcaption>
</figure>

| Field | Key | Default | Unit |
|---|---|---|---|
| **Noise sigma** | `VIRTUAL_MEP_NOISE_MV` | `0.001` | mV |
| **Trial-to-trial variability** | `VIRTUAL_MEP_TRIAL_VARIABILITY` | `true` | on/off |
| **Motor threshold** | `VIRTUAL_MEP_MT` | `60` | V/m |
| **Upper limit** | `VIRTUAL_MEP_UPPER_LIMIT` | `100` | V/m |
| **E-field scale** | `VIRTUAL_MEP_EFIELD_SCALE` | `1.4` | factor |

The MEP source itself is project data: the cortical element per channel is
assigned in the project, not here. The page shows the configured channel names
and the EMG sources file. **Edit in Project** opens the Project tab; the source
elements stay with that subject. See [EMG channels and MEP windows](prepare/emg.md)
for the model and the key descriptions.

## Study (mapping)

<figure>
  <img src="assets/screenshots/config-study.png" alt="Config › Study with mapping, stimulation defaults, MEP analysis and EMG channel cards.">
  <figcaption>Config › Study. Save/Load work on a YAML; Apply pushes the values
  into the live session.</figcaption>
</figure>

### Mapping

| Field | Key |
|---|---|
| **Fit function** | `fit_fun` |
| **Subsampling** | `map_elms` |
| **E-field mode** | `efield_mode` |

### Stimulation defaults

| Field | Key |
|---|---|
| **Pulse shape** | `pulse_shape` |
| **Repetitions** | `n_repetitions` |
| **Min. interval (s)** | `min_isi` |
| **Amplitude (%MSO)** | `amplitude` |

### MEP analysis

| Field | Key | Unit |
|---|---|---|
| **Sampling rate** | `sampling_rate` | Hz |
| **Low-pass (Hz)** | `cutoff_freq` | Hz |
| **Pulse time (0.1 s)** | `tms_pulse_time` | tenths of a second |
| **MEP window** | `start_mep`, `end_mep` | samples after the pulse |

### EMG channels

| Field | Key |
|---|---|
| **Channels** | `emg_channels`, comma separated |

### The three buttons

| Button | Effect |
|---|---|
| **Save study…** | writes the values to a YAML (default `<data folder>/study.yaml`) |
| **Load study…** | reads a YAML into the widgets; changes nothing live |
| **Apply to session** | pushes the values into the live controls |

The status line after **Apply to session**:

```text
Applied: mapping/stimulation, precomputed E-field · needs restart: MEP windows and EMG channels (restart)
```

and while a mapping runs:

```text
Not applied: a mapping session is running (finish it first).
```

The full key list is in [Study profiles](prepare/study.md).

## Subject (files)

A read-only summary of the loaded project — head mesh, ROI, coil model,
placements, target order, E-field library, results file, EMG sources — with:

| Button | Effect |
|---|---|
| **Save project…** | same as Project › Save |
| **Load project…** | same as Project › Load |
| **Edit in Project tab** | jumps to the Project page |

The tab shows all four scopes in one window: Lab and Simulation first, Study
next, Subject here.

## What applies when

| Change | When it takes effect |
|---|---|
| theme | immediately, and is saved |
| relay, data folder, UI scale | after restart |
| stimulator ports, EMG credentials | after restart (they are read when the systems connect) |
| robot model | after restart of the simulator |
| solver and anisotropy | next time the online solver loads |
| study mapping/stimulation values | **Apply to session** |
| MEP windows and channel names | after restart |
| simulation MEP settings | after restart |
| project files | immediately on load |

## Next

- [Themes and display](gui/themes.md)
- [Settings model](config/model.md)
- [`.env` reference](config/env.md)
