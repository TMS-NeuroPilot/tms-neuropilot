# MEP results page

Two plots and one job: show whether the stimulation is producing motor-evoked
potentials, and let you inspect and exclude individual pulses.

<figure>
  <img src="assets/screenshots/mep-results.png" alt="The MEP results page after several pulses: the MEP trend on top and the last EMG sweep below.">
  <figcaption>Top: peak-to-peak MEP per pulse and channel. Bottom: the filtered
  EMG sweep of one pulse, with navigation and the inclusion checkbox.</figcaption>
</figure>

## The MEP trend (top)

- **x-axis**: target index / pulse number, in acquisition order.
- **y-axis**: peak-to-peak amplitude, mV.
- **one line per EMG channel**, in the channel order of `EMG_CHANNELS`.
- Pulses excluded from the mapping are marked, so you can see whether an
  exclusion changed the trend.

The plot is redrawn after every pulse. A flat line at a small amplitude usually
means no response (or no contact); a line that collapses mid-session is worth
investigating before the next target.

## The EMG signal (bottom)

The last pulse's filtered sweep:

- **x-axis**: time, seconds, relative to the recording.
- **y-axis**: amplitude, per channel.
- The low-pass filter uses `CUTOFF_FREQ` and `SAMPLING_RATE`.
- The title shows the pulse (`3. EMG`), and the window is the one used for the
  MEP extraction.

### Navigating and excluding

| Control | Effect |
|---|---|
| **< Previous EMG** | show the previous pulse's sweep |
| **Next EMG >** | show the next pulse's sweep |
| **Include MEP in Mapping** | include/exclude this pulse from the regression |

Excluding a pulse is not cosmetic: the controller drops it from the analysis
matrix and from the R² computation, and marks it in the export. Use it for a
pulse that is visibly an artefact (movement, electrical noise, a double
discharge) — and record why in the session notes.

!!! tip "Exclusion is reversible"
    Re-check the box and the pulse returns to the mapping; the next analysis
    uses it again. Nothing is deleted from the results CSV.

## What "no MEP" looks like

| Pattern | Likely cause |
|---|---|
| flat, low-amplitude noise on every channel | stimulator not firing, or coil not on the head |
| large stimulus artefact, no response after it | the MEP window starts too early or too late |
| response only on one channel | the other electrodes lost contact |
| response that decays over the session | coil heating, fatigue, or a real physiological effect |

See [EMG channels and MEP windows](prepare/emg.md) for the window parameters.

## What is stored

Every pulse is appended to the results CSV with its amplitude per channel and
its pre-activation values. Excluded pulses carry the exclusion flag.

Each plot has a **Save to .png** button in its left pane. It saves the currently
visible plot with a timestamped filename under `ROOT_FOLDER`:

- MEP trend → `P2P_PLOTS_FOLDER_PATH` (`p2p_plots` by default)
- EMG signal → `EMG_PLOTS_FOLDER_PATH` (`emg_plots` by default)

The folders are created only when the corresponding button is clicked.

## A note on pynibs

The extraction, filtering and peak-to-peak computation come from `pynibs`, the
group's analysis package. The controller calls it with the environment values
above; it does not re-implement the signal processing. If you need a different
filter or a different amplitude definition, change the study parameters, not
the GUI.

## Next

- [Cortical results page](gui/cortical.md)
- [Analysis and fits](results/analysis.md)
