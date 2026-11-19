# Glossary

Terms used across the code, the literature and this site. Internal spellings are
included so a code search lands here.

## Stimulation and physiology

**TMS**: transcranial magnetic stimulation. A coil over the scalp induces a
brief electric field in the cortex.

**MSO**: maximum stimulator output. Amplitudes in TMS NeuroPilot are % MSO.

**RMT**: resting motor threshold. The intensity at which a MEP appears in
about half of the trials; often the reference for the session amplitude.

**MEP**: motor evoked potential. The EMG response to a TMS pulse; its
peak-to-peak amplitude is the quantity the regression uses.

**Pre-activation**: EMG activity before the pulse. Displayed and recorded, not
used by the regression.

**ISI**: inter-stimulus interval. TMS NeuroPilot enforces a minimum
(`minium_isi`, seconds) between pulses.

**Motor hotspot**: the scalp site with the largest MEP for a muscle. Often the
target the coil search is centred on.

## Modelling

**E-field**: the electric field a pulse delivers to the cortex, V/m. Recorded
per pulse and per ROI element.

**FEM**: finite element method. SimNIBS solves the field on a tetrahedral head
mesh.

**ROI**: region of interest: the cortical surface patch the map is computed on.

**Midlayer**: a surface halfway between the grey/white boundary and the pial
surface, used as the ROI because it samples the field where pyramidal cells sit.

**Charm**: SimNIBS' head-model pipeline (segmentation + meshing).

**m2m**: the SimNIBS output folder `m2m_<subject>` with the mesh and the
intermediate segmentations.

**`.msh`**: SimNIBS mesh file, read by TMS NeuroPilot for display and the online
solver.

**`.ccd`**: SimNIBS coil model file (optionally `.ccd.nii.gz`).

**`matsimnibs`**: the 4×4 coil matrix format: rotation in the first three
columns, stimulation point in the translation. Stored as `(4, 4, n)` in
placement files, sometimes `(n, 4, 4)` in E-field libraries.

**`E_mag`**: dataset in the E-field library, shape
`(placements, roi_elements)`.

**R²**: coefficient of determination of the per-element fit
`MEP ~ f(E-field)`. The map's colour.

**Fit function**: the shape `f` (linear, sigmoid, exponential, step, and their
log variants); nine are available.

**Subsampling**: analysing every n-th ROI element (`map_elms`).

**Placement**: one coil pose in the search grid. A *target* is the placement
the loop is currently stimulating.

**Target order**: a text file of 0-based placement indices, one per line.

## Software

**Relay**: the Socket.IO hub that routes `{"topic", "data"}` envelopes.

**Topic**: the string that names a message, e.g.
`Robot to Pipeline: Health status`.

**Component**: one process: relay, neuronavigation, robot, controller.

**Supervisor**: `supervisor.py`; starts components, waits for readiness,
multiplexes logs.

**Simulated twin**: the virtual neuronavigation + robot + relay that replace
the hardware in `neuropilot sim`.

**Online solver**: `OnlineFEMManager`, a SimNIBS/PETSc solve for the realised
coil pose during the session.

**Lab profile**: `~/.neuropilot/lab.yaml`; hardware settings for this machine.

**Study profile**: a YAML with protocol defaults, applied to a session.

**Project file**: the per-subject YAML with file paths and session defaults.

**Session cache**: `~/.neuropilot/last_session.yaml`; remembers the last
project and settings. `NEUROPILOT_SESSION_FILE` moves it for tests and tools.

**Fit registry**: `controller/fit_functions.py`, the mapping from display names
to pynibs functions.

## Internal spellings you may search for

| Spelling | What it is |
|---|---|
| `minium_isi` | the project-file key for the minimum ISI (sic) |
| `mesh_RIO_path` | the project-file key for the ROI surface (sic) |
| `map_elms` | subsampling factor |
| `e_field_mode` | per-pulse E-field source (`precomputed` / `online` / `surrogate`) |
| `pulse_e_fields` | list of per-pulse E-field rows |
| `pulse_modes` | list of per-pulse modes |
| `collect_timeout_s` | `COLLECT_TIMEOUT_S`, wait for the realised pose |
| `emg_timeout_s` | `EMG_TIMEOUT_S`, wait for the EMG file |
| `max_aim_error_mm` | `MAX_AIM_ERROR_MM`, warning threshold |
| `Step.COMPLETE` | the terminal state of one pulse |
| `library_warning` | the placements/library consistency message |

## Acronyms

| Acronym | Expansion |
|---|---|
| TMS | transcranial magnetic stimulation |
| MEP | motor evoked potential |
| EMG | electromyography |
| MSO | maximum stimulator output |
| RMT | resting motor threshold |
| ISI | inter-stimulus interval |
| FEM | finite element method |
| ROI | region of interest |
| SMB | Server Message Block (the EMG share) |
| GLFW | Graphics Library Framework (MuJoCo's window) |
| VTK | Visualization Toolkit (the 3-D view) |

## Related pages

- [Key concepts](start/concepts.md)
- [Units and frames](start/units.md)
- [Relay protocol](reference/relay.md)
