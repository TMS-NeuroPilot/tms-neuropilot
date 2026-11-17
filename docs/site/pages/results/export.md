# Export and data formats

A session leaves three kinds of files: the results CSV written by the
controller, the plots, and whatever you export from the cortical page. This page
lists the columns and the formats so an analysis script can be written against
them.

## The results CSV

Path: the project's `results_fn`. The final file is written when the session
finishes (`Finish`). During the session, the analysis also writes timestamped
snapshots next to it (`<name><stamp>.csv`), so an interrupted session still
leaves the pulses collected so far.

**Overwrite existing file** is on by default, so the final table replaces an
existing `results_fn`. If it is off and the path already exists, the existing
file is left untouched and the final table is written to `<name><stamp>.csv`
instead.

| Column | Unit | Meaning |
|---|---|---|
| `idx` | — | position in the target-order list (0-based) |
| `idx_pulse` | — | placement index that was stimulated |
| `time` | — | wall-clock time of the pulse |
| `x_realized`, `y_realized`, `z_realized` | mm | coil stimulation point actually used |
| `rota_realized`, `rotb_realized`, `rotc_realized` | deg | realised coil orientation (XYZ Euler) |
| `x_target`, `y_target`, `z_target` | mm | planned coil position |
| `rota_target`, `rotb_target`, `rotc_target` | deg | planned orientation |
| `pressure` | — | force-sensor reading at stimulation (empty in manual mode) |
| `intensity` | % MSO | stimulator output at the pulse |
| `e_field_mode` | — | `precomputed`, `online` or `surrogate` |
| `mep_<channel>_mV` | mV | peak-to-peak MEP per channel |
| `mep_<channel>_preact_p2p` | mV | pre-activation peak-to-peak |
| `mep_<channel>_preact_var` | mV² | pre-activation variance |

The MEP columns use the **display names** from `EMG_CHANNELS`
(`mep_FDI_mV`, …). Excluded pulses are not removed from the CSV; the exclusion
is an analysis property, so the raw record stays complete.

!!! note "One row per pulse, not per target"
    `n_repetitions = 3` produces three rows with the same `idx_pulse` and
    different `idx`. The aim error and the E-field are per pulse.

## Plots

| Folder | Content |
|---|---|
| `<ROOT_FOLDER>/emg_plots` | saved EMG-signal plots (Save to .png) |
| `<ROOT_FOLDER>/p2p_plots` | saved MEP-trend plots (Save to .png) |

Folder names come from `EMG_PLOTS_FOLDER_PATH` and `P2P_PLOTS_FOLDER_PATH`.
The folders are created when their first plot is saved, not when the controller
starts.

## The cortical export

**Cortical results › Export CSV…** writes three files with one base name:

### `<base>_roi_r2.csv`

| Column | Unit | Meaning |
|---|---|---|
| `element` | — | ROI triangle index, 0-based, same order as the E-field columns |
| `x_mm`, `y_mm`, `z_mm` | mm | triangle centroid, SimNIBS head space |
| `r2_<channel>` | — | R² per triangle, empty when not fitted |

### `<base>_placements.csv`

| Column | Unit | Meaning |
|---|---|---|
| `trial` | — | acquisition order |
| `pulse_index` | — | pulse number in the session |
| `target_index` | — | planned target index |
| `x_realized`, `y_realized`, `z_realized` | mm | realised coil centre |
| `rota_realized`, `rotb_realized`, `rotc_realized` | deg | realised orientation |
| `x_target`, `y_target`, `z_target` | mm | planned coil centre |
| `aim_error_mm` | mm | distance between realised and planned |
| `intensity_pctMSO` | % MSO | stimulator output |
| `pressure` | — | force reading (empty in manual mode) |
| `e_field_mode` | — | per-pulse E-field source |
| `mep_<channel>_mV` | mV | MEP per channel |

### `<base>_README.txt`

The column dictionary, generated with the data:

```text
NeuroPilot mapping export
=========================

Channels: FDI, APB, ADM
Coordinates are in mm, SimNIBS head space.
...
```

Keep this file with the CSVs. It is the only place that states the frame and the
units next to the numbers.

## Screenshots

**Screenshot…** saves the 3-D view as a PNG, including the corner overlays
(pulse count, channel, scalar bar). The image is rendered by VTK at the current
window size.

## What is not in the export

- the E-field vectors themselves (they stay in `e.hdf5` / the online cache),
- the raw EMG sweeps (they stay in the plots and the acquisition's own files),
- the regression parameters per element (only R² is exported),
- the fit residuals.

If an analysis needs the field vectors or the fit parameters, add a dataset to
the E-field library or extend the export — see
[Add a component](extend/components.md) for the code conventions.

## Reproducing a map

To recompute an R² map from an archive you need:

1. the project YAML (which names the files),
2. the E-field library (`e.hdf5`) or the mesh + ROI + coil for an online solve,
3. the results CSV (the MEPs and the pulse order),
4. the same `fit_fun` and `map_elms`.

The code path is `assemble_analysis_matrix()` +
`pynibs.regression.regress_data()`; the same inputs give the same map.

## Next

- [Analysis and fits](results/analysis.md)
- [Cortical results page](gui/cortical.md)
