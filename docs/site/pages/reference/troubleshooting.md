# Troubleshooting

Symptom-first. Each row names the most likely cause and the fix, and links the
page that explains it.

## Install and start

| Symptom | Cause | Fix |
|---|---|---|
| `neuropilot: command not found` | editable install missing in the active env | `pip install -e . --no-deps` |
| `ModuleNotFoundError: PyQt5` / `pynibs` / `mujoco` | wrong interpreter | `conda activate neuropilot`; check `which python` |
| `TypeError` on a missing MEP key at import | `.env` missing and an old checkout | `cp .env.example .env` (current code has defaults; update if needed) |
| import crashes on `ROOT_FOLDER` | `.env` points at the cluster path | `ROOT_FOLDER=/tmp/neuropilot_test neuropilot sim` |
| `Address already in use` on 5000 | another relay or service | stop it, or set `RELAY_PORT` |
| `Cannot connect to the stimulator ... Permission denied` | user not in `dialout` | `sudo usermod -aG dialout $USER`; log out/in, or `newgrp dialout` |
| `Cannot open the TTL/parallel port` | no `/dev/parport0`, or no permission | serial-only fallback is normal; for TTL run `sudo modprobe ppdev` and check the `lp` group |
| window never appears | no `DISPLAY`/`WAYLAND_DISPLAY` | run on a graphical session, or use `pytest -m "not gui"` |
| MuJoCo viewer fails on Wayland | GLFW is X11-only | set `PYGLFW_LIBRARY` to the X11 `libglfw.so.3` |

## Simulator

| Symptom | Cause | Fix |
|---|---|---|
| one component dies at start | traceback in its prefixed log | read the last lines; the supervisor stops the stack |
| `component died: [('robot', 1)]` | robot model/asset problem | `python -m neuropilot.sim_robot.robots --check <robot-key>` |
| controller starts but nothing connects | relay not up or wrong port | check `[relay]` line and `RELAY_PORT` |
| `WARNING: nav not ready after 60s` | slow import or crash | check the `[nav]` log; raise `READINESS_TIMEOUT_S` |
| simulated robot does not move | target outside reach or IK failed | watch the log; check the placement |

## Connections

| Symptom | Cause | Fix |
|---|---|---|
| a card stays grey | no health packet yet | wait 1 s, press **Reconnect** |
| stimulator red, `No Connection` | wrong serial port or unplugged | check `STIMULATOR_PORT`, permissions (`dialout`) |
| EMG red, `Could not connect to IP` | share or credentials | test with `smbclient`, check `EMG_COMPUTER_*` |
| robot red | `main_loop.py` not running, or Modbus/listen disabled | start the robot driver; enable both services |
| robot spams `Awaiting valid pressure data` | force sensor has no reading | touch the sensor once |
| **Reconnect** disabled | no software recovery for this error | fix the hardware; the message names the failure |

## Session

| Symptom | Cause | Fix |
|---|---|---|
| **Start** grey | no E-field mode, missing library, or a system not ready | read the hint under the E-field radios |
| **Start** grey while a file row says `loading...` | a large project file is still being read | wait for the row to show its summary; the window remains usable |
| `Online solver unavailable` | SimNIBS/petsc4py not importable | check `import simnibs`, then the MKL note in install |
| pulses are held in online mode | solver warming up | wait for `Online solver ready.` |
| `Held at …: … not ready` | a system dropped mid-run | fix it, **Reconnect**; the loop continues |
| `Previous ignored: a pulse is in flight.` | **Back** pressed during fire/collect | expected; wait for the next target |
| `No realized target after 20 s -- pulse skipped.` | neuronavigation did not report the pose | check tracking; raise `COLLECT_TIMEOUT_S` if the system is slow |
| coil never reaches the target | out of reach, collision, tracking | **Next**, check the placement and the robot state |
| pulses fire but no MEP | amplifier, window, or stimulator | check the EMG trace and the MEP page |
| map empty after many pulses | no ROI, no library, or < 3 finite MEPs | check the ROI row and the log warnings |

## Data and files

| Symptom | Cause | Fix |
|---|---|---|
| `references target N, but only M placements exist` | order file from another subject or 1-based | regenerate with the matching placements |
| `E_mag must be (placements, elements)` | transposed or wrong dataset | check the shape with `h5py` |
| `different coil placements` warning | sorted placements + unsorted library | re-sort the library or reload the matching pair |
| `expected a mapping of settings` | project is a list/empty/binary | fix the YAML |
| export fails "folder deleted" | target folder removed | choose an existing folder |
| results CSV missing | folder not writable, or `Finish` never reached | check `results_fn` and the log |

## Values that do not stick

| Symptom | Cause | Fix |
|---|---|---|
| a Lab value reverts after restart | the same key is in `.env` | the status line counts them; edit `.env` |
| MEP windows changed in the GUI do nothing | they are read at import | restart the controller |
| theme changes but reverts next start | `UI_THEME` pinned in `.env` | edit `.env` or remove the line |
| study **Apply to session** refuses | a mapping is running | finish it first |
| `lab profile ignored (expected a mapping)` | malformed YAML | fix or delete the file |

## Log colors

The supervisor colors only the role label inside square brackets, for example
`[controller]`, `[invesalius]` and `[relay]`. Set `NO_COLOR` to disable this,
or `FORCE_COLOR=1` to keep the colors when output is redirected to a file.

## Tests and CI

| Symptom | Cause | Fix |
|---|---|---|
| `pytest: command not found` | pytest not in the env | `conda activate neuropilot` / `pip install pytest` |
| GUI tests skipped | no display | run with `DISPLAY`/`WAYLAND_DISPLAY`, or use `-m "not gui"` |
| snapshot drift after a design change | baselines outdated | `UPDATE_GUI_BASELINES=1 pytest tests/test_gui_snapshots.py` |
| CI: `pytest is not installed in …` | runner lacks the env | set `PYTHON` to the neuropilot interpreter |
| CI: `pages` fails on a link | a page references a missing asset | run `python docs/site/build.py --check` locally |
| CI: `pages` fails on an orphan | a page is not in `nav.toml` | add it or delete it |

## What to collect before asking

1. The terminal log with role prefixes (`[relay]`, `[nav]`, `[robot]`,
   `[controller]`), from the start of the run.
2. The step where it failed and the last 20 lines of the Control log.
3. `python -m neuropilot.sim_robot.robots --check <key>` output.
4. `pytest -m "not gui" -q` tail, if the problem is reproducible without
   hardware.
5. The project YAML (redact paths if needed) and the E-field shapes:
   `E_mag.shape`, ROI triangles, placements.

## Next

- [Architecture](reference/architecture.md) — when the symptom needs a mental
  model.
- [Relay protocol](reference/relay.md) — when messages are not arriving.
