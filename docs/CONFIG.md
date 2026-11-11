# Settings overview and the config model

Where every knob lives today, and how the Config tab should carry them.
Three scopes: **Lab** (hardware, per machine), **Study** (protocol, per
study) and **Subject** (files, per subject session).

## Where settings live today

### `.env` (suite root, loaded by `src/neuropilot/config.py`)

| Key | Meaning | Scope |
|---|---|---|
| `RELAY_HOST`, `RELAY_PORT` | Socket.IO relay all components connect to | Lab |
| `ROOT_FOLDER` | data folder (results, plots, caches) | Lab |
| `NEUROPILOT_UI_SCALE` | force the GUI scale (default: from the screen) | Lab |
| `ROBOT` | simulated robot model (`omron` …) | Lab |
| `TMS_ROBOT_CONTROL_PATH` | checkout used by `neuropilot real --launch-relay` | Lab |
| `STIMULATOR_PORT`, `STIMULATOR_TTL_PORT` | MagVenture serial + parallel port | Lab |
| `EMG_COMPUTER_IP`, `EMG_COMPUTER_USERNAME`, `EMG_COMPUTER_PASSWORD` | CED 1401 / Signal SMB share | Lab |
| `ONLINE_FEM_SOLVER`, `ONLINE_FEM_ANISOTROPY` | OnlineFEM solver + anisotropy | Lab |
| `READINESS_TIMEOUT_S`, `PYGLFW_LIBRARY` | supervisor / MuJoCo on Wayland | Lab (bootstrap) |
| `EMG_CHANNELS` | channel names/count (labels + results columns) | Study |
| `SAMPLING_RATE`, `CUTOFF_FREQ`, `TMS_PULSE_TIME`, `START_MEP`, `END_MEP`, `MEASUREMENT_START_TIME` | MEP extraction (pynibs) | Study |
| `EMG_PLOTS_FOLDER_PATH`, `P2P_PLOTS_FOLDER_PATH` | plot output sub-folders | Lab |
| `ENABLE_HEALTH_CHECK_AND_CONTROL_PANEL` | run the GUI + health checks | Lab (bootstrap) |

Read at **import time** — the controller parses the MEP windows and the
data folder when the module loads, so changes need a restart.

### Code constants (`config.py` of each component)

| Where | Examples | Scope |
|---|---|---|
| `sim_robot/config.py` | physics (`SIM_TIMESTEP`, `ACTUATOR_KP/KV`), IK (`IK_ELBOW_UP`, retries), collision tolerances, press thresholds, speed ratios, topic names, head/robot placement, camera | Lab (developer) |
| `controller/pipeline_controller.py` | `pressure_thresh`, amplitude→dI/dt factor (`1.4`), topic names | Developer |
| `controller/systems/virtual_emg.py` | MEP model constants (`mt=60`, upper limit) | Developer |

These are tuning constants, not operator settings; they stay in code.

### Project file (per session, saved from the GUI)

`project_name`, `mesh_head_path`, `mesh_RIO_path` (ROI), `e_field_path`,
`coil_path`, `targets_file` (placements), `target_order_fn`,
`results_fn`, `emg_config_fn`, `fit_fun`, `map_elms`, `stimulator_amplitude`,
`stimulator_waveform`, `n_repetitions`, `minium_isi`, `default_speed`,
`tuning_speed` — everything that belongs to one subject/session.

The EMG channel **sources** (element id / xyz per channel) live in a
separate small YAML referenced by `emg_config_fn`.

The fit function is one of the shapes pynibs provides
(`controller/fit_functions.py`): Linear, Linear (log), Sigmoid
(4-parameter — pynibs' default), Sigmoid (3-parameter), Sigmoid (log),
Exponential, Exponential (no offset), Exponential (log) and Step.  The
"(log)" variants model the logarithm of the MEP response; the plain ones
the raw peak-to-peak amplitude.

### GUI controls (live, in-memory)

Control page: amplitude (slider + spin), repetitions, min. interval, pulse
shape, default/tuning speed, E-field mode. Cortical results: mesh colour,
placement colour metric, display toggles, mapping parameters (fit
function, subsampling). Config page: everything listed above.

Values entered in the Control page are written into the project file on
save; the E-field mode is not persisted.

The E-field mode itself is switchable at any time, also while a mapping is
running: every pulse records the E-field it was stimulated with (from the
precomputed matrix or from the online solver), so a switch only affects the
following pulses and the regression stays index-aligned with the MEP
history.  Switching to online starts the solver load once (it takes about a
minute); until it is ready the coil stays on target and the pulse is held,
and switching back to precomputed releases it immediately.  The exported
placements CSV records which source each pulse used (`e_field_mode`).

## Proposed model

1. **`.env` stays the bootstrap file.** Only what must exist before the
   GUI starts (data folder, relay, UI scale, GLFW, health-check flag).
   Everything else moves out so `.env` stops being a junk drawer.
2. **Lab profile** — hardware settings (`~/.neuropilot/lab.yaml`), edited
   in Config › Lab, with the .env keys still honoured as overrides so
   existing installations keep working.
3. **Study profile** — protocol settings (`<project>/study.yaml` or any
   path): mapping parameters, MEP windows, stimulation defaults, EMG
   channel names, default E-field mode. Saved/loaded from Config › Study
   and applied to the live controls with one button.
4. **Subject/project file** — unchanged (`*.yaml` next to the project),
   edited on the Project page; Config › Subject shows a summary and the
   save/load shortcuts so all three scopes are visible in one place.

Rule of thumb: *would another lab need a different value?* → Lab.
*Would another study?* → Study. *Would another subject?* → Project.

## Status in this build

- Config › Lab: implemented, writes `.env` (comments and unknown keys are
  preserved; restart applies).
- Config › Study: implemented as a YAML profile (default
  `ROOT_FOLDER/study.yaml`) with *Apply to session* pushing the values
  into the live controls; the MEP windows still need a restart.
- Config › Subject: read-only summary of the project values plus
  save/load/jump-to-Project shortcuts.
- Moving the remaining `.env` entries into `lab.yaml` is the next step —
  deferred because every component reads `os.environ` today; the lab page
  already presents them as one group.
