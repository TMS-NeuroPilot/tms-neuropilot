# Command line

```text
neuropilot {sim,relay,controller,real,manual,training}
```

Run `neuropilot` with no arguments to get a small mode-selection dialog.

## `neuropilot sim`

Starts the full simulated stack: relay → neuronavigation ∥ robot → controller.

```bash
neuropilot sim
neuropilot sim --components relay,robot      # a subset, for debugging
```

| Flag | Default | Meaning |
|---|---|---|
| `--components` | `relay,nav,robot,controller` | comma-separated subset |

The supervisor waits for each component's readiness probe, prefixes the logs by
role and stops everything on Ctrl+C. Exit code 0 on a normal shutdown.

## `neuropilot relay`

Starts only the simulated relay.

```bash
neuropilot relay
```

Useful when the other components run in separate terminals or on another
machine.

## `neuropilot controller`

Starts only the controller.

```bash
neuropilot controller --sim       # simulation (peers must already run)
neuropilot controller --real      # real hardware
neuropilot controller --manual    # real hardware, no robot
neuropilot controller --training  # real TMS, virtual EMG, no robot
neuropilot controller             # asks for the mode in a dialog
```

`--sim`, `--real`, `--manual` and `--training` are mutually exclusive.

For `--real`, `--manual`, and `--training`, the controller also starts a local
InVesalius by default and starts the relay when `TMS_ROBOT_CONTROL_PATH` is
configured. Use `--no-invesalius` to suppress InVesalius, or `--invesalius
PATH` to provide an environment, wrapper, or checkout for this run.

## `neuropilot real`

Real-hardware mode.

```bash
neuropilot real
neuropilot real --launch-relay
```

| Flag | Meaning |
|---|---|
| `--launch-relay` | compatibility flag; a configured relay is started automatically |
| `--no-invesalius` | do not start InVesalius automatically |
| `--invesalius PATH` | use this environment, wrapper, or checkout for this run |

If no relay is running, the controller starts one when
`TMS_ROBOT_CONTROL_PATH` points to a `tms-robot-control` checkout. If the path
is not configured, a dialog asks for it and the selection is saved. If the
relay cannot be started, the GUI and terminal show the reason and the stack
exits. An already-running relay is reused.

The same relay and InVesalius flags are available on `manual` and `training`.

## `neuropilot manual`

Real hardware, no robot.

```bash
neuropilot manual
neuropilot manual --launch-relay
```

Same relay behaviour as `real`.

## `neuropilot training`

Real stimulator and InVesalius, virtual EMG, no robot. The operator holds the
coil and the MEP trace is generated from the E-field.

```bash
neuropilot training
neuropilot training --launch-relay
```

Same relay behaviour as `real`. Start InVesalius before the controller; no
robot driver or EMG PC is needed. The channel sources come from the project.

## Robot registry

```bash
python -m neuropilot.sim_robot.robots --list
python -m neuropilot.sim_robot.robots --check omron   # or the key from --list
```

`--check` validates the MuJoCo model, the URDF, the base body, the tool site and
the IK mask. Exit code 1 on a problem.

## Documentation

```bash
python docs/site/build.py                 # build into public/
python docs/site/build.py --out /tmp/site # somewhere else
python docs/site/build.py --serve 8000    # build and preview
python docs/site/build.py --check         # verify links, then remove the output
```

`--check` is what CI runs; it fails on a broken internal link, an orphan page or
a missing nav entry.

## Tests

```bash
pytest                          # everything (GUI tests need a display)
pytest -m "not gui" -q          # the headless set
pytest tests/test_theme.py -v   # one file
scripts/run_tests.sh            # the headless set with the CI interpreter
UPDATE_GUI_BASELINES=1 pytest tests/test_gui_snapshots.py
```

## Data preparation

```bash
python scripts/01_create_head_model.py -s <subject.hdf5> -m <mesh_idx>
python scripts/02_create_roi_efield_library.py --mesh-msh … --roi-hdf5 … \
    --coil … --target x y z --out e.hdf5
python scripts/03_create_optimized_sequences.py --e-hdf5 e.hdf5 --n-stim 200
python scripts/sort_coil_placements.py --matsimnibs … --coil-seq … --out-dir …
```

Flags are documented in [Subject data](prepare/subject-data.md) and
[Coil placements](prepare/placements.md).

## Environment

Every command reads the same configuration chain:

```text
shell environment  >  .env  >  ~/.neuropilot/lab.yaml  >  defaults
```

One-off overrides work as expected:

```bash
ROOT_FOLDER=/tmp/np RELAY_PORT=5100 neuropilot sim
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | normal shutdown, or the dialog was closed |
| 1 | a required setting is missing (e.g. `--launch-relay` without a path), or `--check` found a problem |
| non-zero from a child | the supervisor stops the stack and exits |

## Cheat sheet

```bash
# install
conda activate neuropilot && pip install -e . --no-deps && cp .env.example .env

# run
neuropilot sim                     # everything, simulated
neuropilot real --launch-relay     # lab, with the production relay
neuropilot manual                  # lab, no robot

# check
python -m neuropilot.sim_robot.robots --check omron   # or the key from --list
pytest -m "not gui" -q
python docs/site/build.py --check

# data
python scripts/02_create_roi_efield_library.py --mesh-msh … --roi-hdf5 … \
       --coil … --target -37 -21 58 --out e.hdf5
```

## Next

- [Run modes](run/modes.md)
- [Testing and CI](reference/testing.md)
