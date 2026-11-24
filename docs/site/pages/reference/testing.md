# Testing and CI

The suite has more than 800 tests. Most of them need no display and no
hardware; the GUI tests are marked and run on a workstation or in a manual CI
job.

## Running

```bash
pytest                          # everything (needs a display for `gui`)
pytest -m "not gui" -q          # headless, what CI runs
pytest tests/test_theme.py -v   # one file
scripts/run_tests.sh            # headless, with the CI interpreter
```

`scripts/run_tests.sh` and `.gitlab-ci.yml` both use
`scripts/ci-python.sh`, which finds the interpreter in this order:

1. `$PYTHON`, if it is executable or on the PATH;
2. the `neuropilot` conda environment in the usual locations;
3. `python3`.

## Markers

| Marker | Meaning |
|---|---|
| `gui` | builds a real `MainWindow`; skipped without `DISPLAY`/`WAYLAND_DISPLAY` |

The GUI tests cover all eight pages, resizing, the results table, project
load/save with corrupt/empty/missing/binary files, the Config tab against a
temporary `.env`, the study profile, exports and screenshots into deleted
folders, manual mode, the status LEDs and recovery buttons, every button on
every page, the mesh/coil summary threads and close/teardown.

## Isolation

Tests never touch your data:

- `ROOT_FOLDER` and the lab/env files are redirected into `tmp_path`;
- an autouse fixture **fails** a test that writes the repository `.env`,
  `~/.neuropilot/last_session.yaml` or `lab.yaml`;
- GUI tests monkeypatch the session-cache path.

## GUI snapshots

`tests/test_gui_snapshots.py` captures a 32×24 grey fingerprint and the geometry
of every named widget on the seven main pages, and compares them against
`tests/baselines/gui_pages.json`. A `.ui` or style-sheet regression fails; the
current rendering is left in pytest's `tmp_path` for comparison.

After an intentional design change:

```bash
UPDATE_GUI_BASELINES=1 pytest tests/test_gui_snapshots.py
```

## What the suite proves

| Area | Examples |
|---|---|
| configuration | `.env` round-trip with comments, quotes, `#`, backslashes; lab-profile precedence; the Config tab's Save split |
| state machine | step transitions, skip/back/pause, health holds, step exceptions, monotonic ISI |
| E-field | per-pulse rows, mid-run mode switch, solver lifecycle, pulse holds |
| analysis | matrix assembly, dropped pulses, per-channel NaNs, superseded results |
| data | placements validation, library/placement consistency, ROI/mesh loaders |
| GUI | pages, buttons, dialogs, exports, screenshots, teardown |
| hardware | stimulator/EMG/robot status parsing, relay topics, recovery |
| docs | the site builds, every link resolves, every page is in the nav |

## CI pipeline

`.gitlab-ci.yml` has two stages:

| Job | Stage | What it does |
|---|---|---|
| `check:syntax` | check | `compileall` on `src/` and a `pyproject.toml` parse — catches a syntax error even without the heavy imports |
| `test` | test | `pytest -m "not gui"` with a JUnit report; runs on pushes and merge requests |
| `test:gui` | test | manual; `pytest -m gui` on a runner with a display |
| `pages` (GitHub Actions) | deploy | builds this site twice from one source: `dev` → the repository's `gh-pages` branch (<https://tms-neuropilot.github.io/tms-neuropilot/>, development docs), `main` → `TMS-NeuroPilot/tms-neuropilot.github.io` (<https://tms-neuropilot.github.io/>, release docs) |

The CI variables keep everything isolated:

```yaml
ROOT_FOLDER: "$CI_PROJECT_DIR/.ci-data"
NEUROPILOT_LAB_FILE: "$CI_PROJECT_DIR/.ci-data/lab.yaml"
NEUROPILOT_ENV_FILE: "$CI_PROJECT_DIR/.ci-data/.env"
```

`ci-python.sh` means the runner needs no configuration beyond the `neuropilot`
environment (or a `PYTHON` variable pointing at it).

## The documentation build

```bash
python docs/site/build.py --check
```

The builder is dependency-free (standard library only), so it runs on the same
interpreter as the tests and needs no network. It fails on:

- a page listed in `nav.toml` that does not exist,
- a page that exists but is not in `nav.toml` (an orphan),
- a broken internal link or asset reference.

It also writes `search-index.json`, `sitemap.xml`, `robots.txt` and a 404 page.

## Adding a test

- Put unit tests next to the existing file for the module.
- Use the fixtures in `tests/conftest.py` (`h5file`, `roi_hdf5`,
  `placements_hdf5`, `e_matrix_hdf5`, `window`), not your own temp files.
- Mark a test `gui` as soon as it constructs a widget.
- Never write outside `tmp_path`; the guard fixture will fail the test.

## Coverage gaps

- Robot motion quality and force control are not tested — they need the
  physical arm.
- The real stimulator and the EMG share are mocked; the protocols are tested,
  the devices are not.
- The online FEM is tested around the solver, not for numerical accuracy.
- Screenshot *content* is fingerprinted, not compared pixel by pixel across
  machines.

## Next

- [Architecture](reference/architecture.md)
- [Troubleshooting](reference/troubleshooting.md)
