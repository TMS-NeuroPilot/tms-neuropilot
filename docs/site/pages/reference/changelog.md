# Changelog

The canonical changelog is
[`CHANGELOG.md`](https://gitlab.gwdg.de/tms-localization/papers/neuropilot/-/blob/main/CHANGELOG.md)
in the repository. This page summarises the milestones that change how the
suite is used.

## Unreleased

### Documentation

- This site: 44 pages covering installation, subject data, every GUI page,
  every configuration key, the workflows and the reference material. Built by a
  dependency-free generator (`docs/site/build.py`) and published by GitLab Pages
  on every push to `main`.
- Docs are checked in CI: the build fails on a broken link, an orphan page or a
  missing navigation entry.

### Robustness

- The MEP analysis keys (`SAMPLING_RATE`, `CUTOFF_FREQ`, `TMS_PULSE_TIME`,
  `START_MEP`, `END_MEP`, `MEASUREMENT_START_TIME`) now have defaults in code,
  so a checkout without `.env` starts instead of failing at import.
- The library/placement consistency check now compares matrices stored in
  either layout (`(4, 4, n)` or `(n, 4, 4)`) instead of skipping the comparison
  when the shapes differ.

### Earlier unreleased work

- **Training mode**: `neuropilot training` runs the real stimulator and
  InVesalius with a virtual EMG and no robot; the operator holds the coil.
- **Config › Simulation**: the five `VIRTUAL_MEP_*` keys, with the MEP source
  summary linked to the project.
- **Robot registry** — one `RobotSpec` per robot; `--list` / `--check`; the
  Config › Lab selector stores the key and reports unknown values.
- **Five colour themes** — Workstation Light, Lab Paper, Instrument Blue,
  Graphite, Midnight; switchable live from Config › Lab; contrast enforced by
  tests.
- **Lab profile** — hardware settings in `~/.neuropilot/lab.yaml`, edited in
  Config › Lab, with `.env` as the override layer.
- **E-field mode switching** — per-pulse E-field rows let the mode change
  mid-session; the pulse is held while the online solver warms up.
- **Config › Study** — a study profile with *Apply to session*, and a clear
  split between what applies immediately and what needs a restart.
- **Project file carries the E-field mode** (`efield_mode`).
- **Test suite** — about 700 tests, GUI tests behind a `gui` marker, six-page
  snapshot baselines, property/fuzz tests for the `.env` editor.

## 0.1.0 — 2026-11-10

The first release of the merged suite:

- `neuropilot sim` runs the whole simulated stack in one command.
- The controller drives the seven-step mapping loop against InVesalius, the
  robot controller and the stimulator.
- Precomputed and online E-fields, with the online solver in a separate worker.
- MEP extraction through `pynibs`, nine fit functions, R² maps on the cortical
  surface.
- Results CSV, placement log, plot folders, screenshots and CSV export.
- GitLab CI: syntax gate and headless tests.

## How versions are handled

The suite is pre-1.0. The changelog records behaviour changes that affect a
session or an existing configuration; internal refactors are not listed. When a
change requires action, the entry says so explicitly.

## Next

- [Architecture](reference/architecture.md)
- [Testing and CI](reference/testing.md)
