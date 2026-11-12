# Lab profile reference

The lab profile is the hardware layer: settings that belong to *this machine*,
shared by every component and by every project. It is a small YAML at
`~/.neuropilot/lab.yaml`, edited on **Config › Lab**.

## The file

```yaml
# NeuroPilot lab profile -- hardware settings shared by every component.
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
| `TMS_ROBOT_CONTROL_PATH` | empty | `tms-robot-control` checkout |
| `STIMULATOR_PORT` | `/dev/ttyS1` | stimulator serial port |
| `STIMULATOR_TTL_PORT` | `/dev/parport0` | stimulator TTL port |
| `EMG_COMPUTER_IP` | `192.168.1.2` | EMG acquisition PC address |
| `EMG_COMPUTER_USERNAME` | `neuro` | SMB user |
| `EMG_COMPUTER_PASSWORD` | `<set in .env>` | SMB password |
| `ONLINE_FEM_SOLVER` | `pardiso` | FEM solver |
| `ONLINE_FEM_ANISOTROPY` | `scalar` | conductivity model |

## Precedence

```text
shell environment  >  .env  >  lab.yaml  >  defaults
```

Only keys that the shell and `.env` leave unset are exported from this file
(`os.environ.setdefault`). That is why the GUI marks `.env`-pinned fields and
why a value can "not stick": `.env` is still defining it.

## Who writes it

- **Config › Lab › Save lab profile** writes the 14 keys above.
- **Config › Lab › Theme** writes `UI_THEME` immediately when you change it.
- The controller itself never writes the file; a read-only home directory is
  fine until you press Save.

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
