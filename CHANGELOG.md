# Changelog

All notable changes to NeuroPilot are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- A Config tab for the settings that previously only lived in `.env`:
  relay host/port, data folder, UI scale, simulated robot model, the
  tms-robot-control checkout, stimulator serial/TTL ports, EMG channels
  and SMB credentials, the MEP analysis windows and the online E-field
  solver/anisotropy.  The active mode (Simulated / Real / Manual) is
  shown as a badge and settings the mode does not use are disabled.  Save
  rewrites only the managed keys in `.env`, keeping comments and unknown
  entries; a restart applies the values.

## [Unreleased]

### Changed

- The E-field mode selector moved from the status strip into its own
  card on the Control page (where the mapping parameters were), and the
  mapping parameters (fit function, subsampling) moved to the results
  page, which is now called "Cortical results".

## [Unreleased]

### Changed

- The simulated robot no longer streams JPEG frames to the pipeline.  The
  controller renders the same MuJoCo scene in the robot-view panel, so the
  operator can orbit (drag), pan (right drag), zoom (wheel) and reset
  (double click); the simulated robot publishes its full `qpos` with the
  tracking state and the view only redraws when the pose or camera
  changes.  Simulation only — real mode leaves the panel empty.

## [Unreleased]

### Added

- Mapping results page split into the 3D view and a results panel.  The
  panel shows the per-channel best R² and element, a session summary, the
  placement display controls (colour by MEP / trial / aim error, coil
  handles, path) and a selection readout.
- Realized coil placements are drawn on the head as spheres coloured by
  MEP size, trial id or aim error, with optional coil-direction sticks and
  path lines; hovering a marker shows the trial, pose, aim error and MEPs.
- On the ROI surface, hovering reports the element, its coordinates and
  the R² of every channel; clicking pins the readout.  "Mark best R²"
  outlines the highest-R² triangle in pink (shortcut B), H toggles
  head/ROI and F restores the home view.
- Export from the results page: a PNG screenshot and CSV tables of the R²
  per ROI triangle (with coordinates) plus the placement log (poses, aim
  errors, intensities, MEPs), with a README describing every column.

## [0.1.0] — 2026-11-10

First release of the merged suite.

### Added

- One repository formed from four GitLab projects: the controller
  (`cobot-pipeline-controller`), the sim relay (`relay_server_sim`), the
  virtual robot (`tms-robot-sim2`) and the virtual neuronavigation
  (`virtual_neuronavigation`).
- Process supervisor and CLI: `neuropilot sim` starts the whole simulated
  stack (relay → nav + robot in parallel → controller) with readiness
  probes, role-prefixed logs and a Ctrl+C cascade; `neuropilot` without
  arguments opens a GUI mode selector; `neuropilot real [--launch-relay]`
  for hardware sessions.
- `--sim` / `--real` flags on the controller, replacing the always-on mode
  selection dialog.
- Unified suite configuration: one `.env` + `src/neuropilot/config.py` with
  a local-safe `ROOT_FOLDER` default (the cluster-path import crash is gone
  suite-side).
- Proportional UI scaling in the control panel: widgets and fonts scale
  with the window; Start/Back/Next buttons are centered under the status
  LEDs; consistent pixel-based font sizes (labels 16px, widgets 15px).
- `scripts/make_tissue_stls.py`: extracts skin/GM/WM surface STLs from a
  SimNIBS m2m HDF5 by tissue tag.
- `CONTRIBUTORS.md`, README with quick start, CC BY-NC-SA 4.0 license.

### Changed

- Relay channels renamed to the external-controller convention
  (`from_external_controller` / `to_external_controller`); the marker topic
  is now `External Controller to Neuronavigation: Create Marker`.
- The simulated end-effector is the coil holder
  (`coil_holder_fs_w_mcf_b65.stl`) instead of the bare B65 coil case, with
  the matching TCP height.
- Renamed for clarity: `onlineFEM.py` → `OnlineFEMManager.py`,
  `control_panel_window2.py` → `control_panel.py`.

### Fixed

- All relay clients (controller, sim robot, sim relay era clients) drop
  messages and reconnect automatically during relay outages instead of
  crashing with `BadNamespaceError`.
- Windows-mode bugs found by the end-to-end gate: controller positional
  argument parsing vs flags, PyQt `.ui` custom-widget imports needing the
  component cwd, unbuffered child output for readiness probes.

### Removed

- The unused legacy control panel (`control_panel_window.py`) and Yaseen's
  scratch `code store` folder (the STL recipe lives on in
  `scripts/make_tissue_stls.py`).
