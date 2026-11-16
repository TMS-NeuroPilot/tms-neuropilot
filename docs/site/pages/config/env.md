# `.env` reference

`.env` lives in the repository root and is read once, at import, before any
component starts. It is the bootstrap and override layer: a key here wins over
the lab profile and over the built-in defaults.

Create it once:

```bash
cp .env.example .env
```

## Keys

### Relay

| Key | Default | Meaning | Restart |
|---|---|---|---|
| `RELAY_HOST` | `127.0.0.1` | Socket.IO relay address | yes |
| `RELAY_PORT` | `5000` | relay port | yes |

### Data and plots

| Key | Default | Meaning | Restart |
|---|---|---|---|
| `ROOT_FOLDER` | `~/.neuropilot` | results, plots, caches; created at import | yes |
| `EMG_PLOTS_FOLDER_PATH` | `emg_plots` | per-pulse EMG plots, relative to `ROOT_FOLDER` | yes |
| `P2P_PLOTS_FOLDER_PATH` | `p2p_plots` | peak-to-peak trend plots, relative to `ROOT_FOLDER` | yes |

### Interface

| Key | Default | Meaning | Restart |
|---|---|---|---|
| `NEUROPILOT_UI_SCALE` | empty (from the screen) | force the GUI scale | yes |
| `UI_THEME` | `Workstation Light` | colour theme; also editable in Config › Lab | no |
| `NEUROPILOT_SESSION_FILE` | `~/.neuropilot/last_session.yaml` | session cache; tests and screenshot tools redirect it | no |

### Virtual EMG (simulation)

| Key | Default | Meaning | Restart |
|---|---|---|---|
| `VIRTUAL_MEP_NOISE_MV` | `0.001` | white-noise sigma added to the trace, mV | yes |
| `VIRTUAL_MEP_TRIAL_VARIABILITY` | `true` | trial-to-trial variability of the MEP model | yes |
| `VIRTUAL_MEP_MT` | `60` | motor threshold used to normalise the field, V/m | yes |
| `VIRTUAL_MEP_UPPER_LIMIT` | `100` | saturation field of the recruitment curve, V/m | yes |
| `VIRTUAL_MEP_EFIELD_SCALE` | `1.4` | scale applied to the precomputed E-field row | yes |

### Robot

| Key | Default | Meaning | Restart |
|---|---|---|---|
| `ROBOT` | `omron` | simulated robot model (key from `sim_robot/robots.py`) | yes |
| `TMS_ROBOT_CONTROL_PATH` | empty | `tms-robot-control` checkout for starting the relay (`--launch-relay` or the Relay card) | yes |
| `INVESALIUS_LAUNCH` | `auto` | auto-start InVesalius in real/manual/training mode (`auto`, `local`, `off`) | yes |
| `INVESALIUS_ENV` | empty | conda environment containing InVesalius | yes |
| `INVESALIUS_CHECKOUT` | empty | InVesalius checkout containing `app.py` | yes |
| `INVESALIUS_LAUNCHER` | empty | `inv` wrapper or equivalent launcher | yes |

### Stimulator

| Key | Default | Meaning | Restart |
|---|---|---|---|
| `STIMULATOR_PORT` | `/dev/ttyS1` | serial port of the stimulator | yes |
| `STIMULATOR_TTL_PORT` | `/dev/parport0` | parallel port for the TTL trigger | yes |

### EMG computer

| Key | Default | Meaning | Restart |
|---|---|---|---|
| `EMG_COMPUTER_IP` | `192.168.1.2` | EMG acquisition PC address | yes |
| `EMG_COMPUTER_USERNAME` | `neuro` | SMB user | yes |
| `EMG_COMPUTER_PASSWORD` | `<set in .env>` | SMB password | yes |

### MEP extraction

| Key | Default | Meaning | Restart |
|---|---|---|---|
| `EMG_CHANNELS` | `FDI,APB,ADM` | channel names and count | yes |
| `SAMPLING_RATE` | `4000` | Hz | yes |
| `CUTOFF_FREQ` | `500` | low-pass, Hz | yes |
| `TMS_PULSE_TIME` | `5` | pulse position in the recording, **tenths of a second** | yes |
| `START_MEP` | `10` | window start, samples after the pulse | yes |
| `END_MEP` | `100` | window end, samples after the pulse | yes |
| `MEASUREMENT_START_TIME` | `0` | first sample kept from the file | yes |

### Online solver

| Key | Default | Meaning | Restart |
|---|---|---|---|
| `ONLINE_FEM_SOLVER` | `pardiso` | `pardiso` or `amg` | no (next solver load) |
| `ONLINE_FEM_ANISOTROPY` | `scalar` | `scalar` or `vector` | no (next solver load) |

### Supervisor and bootstrap

| Key | Default | Meaning | Restart |
|---|---|---|---|
| `READINESS_TIMEOUT_S` | `60` | seconds to wait for a component's readiness probe | yes |
| `ENABLE_HEALTH_CHECK_AND_CONTROL_PANEL` | `true` in `.env.example` | run the GUI and health checks (`false` is for partial tests only) | yes |
| `PYGLFW_LIBRARY` | auto-detected | X11 GLFW library for the MuJoCo viewer on Wayland | yes |

### Controller timeouts

| Key | Default | Meaning | Restart |
|---|---|---|---|
| `COLLECT_TIMEOUT_S` | `20` | wait for the realised coil pose before skipping a pulse | yes |
| `EMG_TIMEOUT_S` | `5` | wait for the EMG file of a pulse | yes |
| `MAX_AIM_ERROR_MM` | `5` | aim error above which a pulse is flagged | yes |
| `EMG_PROBE_INTERVAL_S` | `5` | SMB health probe interval | yes |

### Test and CI hooks

| Key | Default | Meaning |
|---|---|---|
| `NEUROPILOT_LAB_FILE` | `~/.neuropilot/lab.yaml` | move the lab profile |
| `NEUROPILOT_ENV_FILE` | `<repo>/.env` | the file the Config tab edits (tests/CI redirect it) |
| `NEUROPILOT_DEBUG_GEODESIC` | unset | simulate the geodesic debug export |
| `DISPLAY`, `WAYLAND_DISPLAY` | from the session | Qt needs one of them for the GUI |

## Syntax

`.env` follows python-dotenv:

```bash
RELAY_HOST=127.0.0.1
ROOT_FOLDER=/data/neuropilot        # comments after a value
EMG_COMPUTER_PASSWORD="p a s s # 1" # quotes protect spaces and '#'
```

Rules the Config tab's writer follows so a round-trip is lossless:

- a value containing spaces, `#`, quotes or backslashes is written **quoted**;
- inside double quotes, backslashes and quotes are escaped;
- unquoted values are trimmed;
- comments and unknown keys are preserved when the GUI writes the file.

!!! warning "Values are read at import"
    Editing `.env` while the controller runs changes nothing until restart.
    This is the most common "my change did nothing" report.

## Required vs optional

Every key has a default in the code, so a missing `.env` starts the suite with
the documented values. A checkout without any `.env` at all is still a bad idea:
the analysis keys are read at import, and the defaults are the *example*
protocol, not yours.

## Precedence reminder

```text
shell environment  >  .env  >  lab.yaml  >  defaults
```

A key exported in the shell beats `.env`; a key in `.env` beats the GUI's Lab
page. See [Settings model](config/model.md).

## Next

- [Lab profile reference](config/lab.md)
- [Study profiles](prepare/study.md)
