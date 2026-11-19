# Lab profile reference

The lab profile is the hardware layer: settings that belong to *this machine*,
shared by every component and by every project. It is a small YAML at
`~/.neuropilot/lab.yaml`, edited on **Config › Lab**.

## The file

```yaml
# TMS NeuroPilot lab profile -- hardware settings shared by every component.
# Edited in Config > Lab.  Precedence (highest first):
#   shell environment  >  .env  >  this file  >  built-in defaults
# so a key you keep in .env still wins over the value here.
RELAY_HOST: 127.0.0.1
RELAY_PORT: '5000'
ROOT_FOLDER: ~/.neuropilot
NEUROPILOT_UI_SCALE: ''
UI_THEME: Workstation Light
ROBOT: omron
TMS_ROBOT_CONTROL_PATH: ''
INVESALIUS_LAUNCH: auto
INVESALIUS_ENV: /opt/miniforge3/envs/invesalius
INVESALIUS_CHECKOUT: /opt/invesalius-prs
INVESALIUS_LAUNCHER: /opt/miniforge3/envs/invesalius/bin/inv
STIMULATOR_PORT: /dev/ttyS1
STIMULATOR_TTL_PORT: /dev/parport0
EMG_COMPUTER_IP: 192.168.1.2
EMG_COMPUTER_USERNAME: neuro
EMG_COMPUTER_PASSWORD: ""
ONLINE_FEM_SOLVER: pardiso
ONLINE_FEM_ANISOTROPY: scalar
```

Values are stored as strings; the GUI converts them when it reads them.

## Keys

| Key | Default | Meaning |
|---|---|---|
| `RELAY_HOST` | `127.0.0.1` | relay address |
| `RELAY_PORT` | `5000` | relay port |
| `ROOT_FOLDER` | `~/.neuropilot` | results and plots folder |
| `NEUROPILOT_UI_SCALE` | empty | forced GUI scale |
| `UI_THEME` | `Workstation Light` | colour theme |
| `ROBOT` | `omron` | simulated robot key |
| `TMS_ROBOT_CONTROL_PATH` | empty | `tms-robot-control` checkout; used to start the relay automatically |
| `INVESALIUS_LAUNCH` | `auto` | auto-start policy: `auto`, `local`, or `off`/`external` (case-insensitive) |
| `INVESALIUS_ENV` | empty | conda environment that contains InVesalius |
| `INVESALIUS_CHECKOUT` | empty | InVesalius source checkout containing `app.py` |
| `INVESALIUS_LAUNCHER` | empty | `inv` wrapper or other launcher path |
| `STIMULATOR_PORT` | `/dev/ttyS1` | stimulator serial port |
| `STIMULATOR_TTL_PORT` | `/dev/parport0` | stimulator TTL port |
| `EMG_COMPUTER_IP` | `192.168.1.2` | EMG acquisition PC address |
| `EMG_COMPUTER_USERNAME` | `neuro` | SMB user |
| `EMG_COMPUTER_PASSWORD` | `<set in .env>` | SMB password |
| `ONLINE_FEM_SOLVER` | `pardiso` | FEM solver |
| `ONLINE_FEM_ANISOTROPY` | `scalar` | conductivity model |
| `COLLISION_TEST` | empty | saved collision-test layout (JSON: head/base poses, start joints, IK branch, safe Z, translation and rotation limits) |

## InVesalius auto-start

In robo, manual and training mode TMS NeuroPilot starts a local InVesalius
before the controller. Simulation does not use InVesalius. With
`INVESALIUS_LAUNCH: auto`, this happens only when the relay is local; use
`local` to start a local InVesalius against a remote relay, or `off`/`external`
to manage it yourself.

The `INVESALIUS_ENV`, `INVESALIUS_CHECKOUT`, and `INVESALIUS_LAUNCHER` values
are filled automatically after the first successful discovery and can be
edited directly in this YAML file. Discovery asks conda for the environment
list; `CONDA_EXE` (or a `conda` executable on `PATH`) provides the conda
binary. The installer wrapper in the environment is preferred; when it is
missing or broken, TMS NeuroPilot uses the environment's Python together with
`INVESALIUS_CHECKOUT/app.py`. Closing InVesalius does not stop the controller.

The picker also has an **Is started** option. It sets
`INVESALIUS_LAUNCH: external`, skips local startup, and expects an InVesalius
instance on another machine to connect to the same relay.

When a real/manual/training session starts without a relay, TMS NeuroPilot starts
one from `TMS_ROBOT_CONTROL_PATH`. If that path is missing, a directory picker
asks for the `tms-robot-control` checkout. A value already pinned in `.env` is
updated there; otherwise it is written to this lab profile.

## Cobot pose and movement limits

**Config › Lab › Cobot pose** shows the same shoulder, arm and wrist choices and
the safe Z, translation and rotation limits as the collision test. The values
come from the loaded project first, then the `COLLISION_TEST` lab block, then
the built-in collision defaults.

**Make project default** and **Make lab default** in the collision test write
the complete block. The Config page can also update the lab block with **Save
lab profile**. A loaded project keeps its own values until another project or
lab default is applied.

## Precedence

```text
shell environment  >  .env  >  lab.yaml  >  defaults
```

Only keys that the shell and `.env` leave unset are exported from this file
(`os.environ.setdefault`). That is why the GUI marks `.env`-pinned fields and
why a value can "not stick": `.env` is still defining it.

## Who writes it

- **Config › Lab › Save lab profile** writes the hardware keys and merges the
  Config-page cobot pose and movement limits into `COLLISION_TEST`.
- **Config › Lab › Theme** writes `UI_THEME` immediately when you change it.
- The first real/manual/training launch writes the discovered
  `INVESALIUS_ENV`, `INVESALIUS_CHECKOUT`, and `INVESALIUS_LAUNCHER` values.
- The controller itself does not write hardware settings; a read-only home
  directory is fine until you press Save.

The GUI writes atomically (temp file + rename) and preserves unknown keys and
comments in the existing file where the writer can.

## Who reads it

`neuropilot.lab_profile.apply_environment()` is called by
`neuropilot.config` before any component package is imported. That single call
is what makes every child process (`neuropilot.controller`, `sim_robot`,
`sim_relay`, `sim_nav`) see the same merged values.

The Config tab also reads it directly, to fill the fields and to compute the
override list.

## What is *not* in it

| Setting | Where it lives | Why |
|---|---|---|
| MEP windows, sampling rate, channel names | `.env` | read at import by the controller; the GUI writes them there from the Study tab |
| fit function, amplitude, ISI | study profile / project file | protocol, not hardware |
| mesh, ROI, library, placements | project file | subject |
| readiness timeout, GLFW library | `.env` | needed before the GUI starts |

## Moving the file

```bash
NEUROPILOT_LAB_FILE=/etc/neuropilot/lab.yaml neuropilot controller --sim
```

Useful for a shared lab account or for tests. The GUI shows the path it loaded
in the status line, so there is no ambiguity about which file is active.

## Hand-editing

Safe:

- change a value, keep the key spelling;
- add a comment;
- reorder keys.

Not safe:

- rename a key (it is ignored; the default applies);
- add a key that is not in `LAB_KEYS` and expect it to reach the components
  (use `.env` for that);
- write a YAML list or a nested mapping (the reader expects flat key/value and
  ignores the file with a warning).

## Troubleshooting

| Symptom | Cause |
|---|---|
| a saved value is ignored | the same key is defined in `.env` or the shell |
| `lab profile ignored (expected a mapping)` | the file is a list or malformed |
| theme resets after restart | `UI_THEME` is pinned in `.env` to another value |
| robot model change does nothing | the simulator was not restarted |
| file not found on a new machine | `NEUROPILOT_LAB_FILE` points elsewhere |

## Next

- [Settings model](config/model.md)
- [`.env` reference](config/env.md)
- [Themes and display](gui/themes.md)
