# Cortical results page

The 3-D view shows the regression result as a colour map on the ROI surface
mesh — the R² value of each triangle is mapped to a colour, not painted onto
the anatomy. This page
documents the viewport, the four cards next to it and the export.

<figure>
  <img src="assets/screenshots/cortical-results.png" alt="The Cortical results page with an R² map on the ROI surface, placements and the coil handles.">
  <figcaption>The ROI surface coloured by R² for the FDI channel, with the
  best element marked and its values pinned in the Selection card.</figcaption>
</figure>

## The viewport

| Interaction | Effect |
|---|---|
| drag | rotate |
| scroll | zoom |
| middle-drag / shift-drag | pan |
| hover | show element R² and coordinates in **Selection** |
| click | pin the readout (hover no longer overwrites it) |
| **B** | mark the best R² element of the selected channel |
| **H** | toggle head mesh / ROI surface |
| **F** | reset the camera to the home view |

The surface selector above the viewport switches between the head mesh and the
ROI. **Show results** offers **No results** and one entry per EMG channel
(**FDI**, **APB**, …) for the computed R² maps on the ROI. Tissue labels are
not offered as a result; the head is shown in plain colour. **Show edges**
overlays the triangle wireframe; it is on by default.

In simulation and training, a loaded EMG source config also marks each channel's
source as a labelled sphere on the ROI surface. The sphere colour matches the
channel label; it is independent of the R² colour map.

!!! note "No map is drawn before three pulses"
    The readout says *"No R² map yet — needs at least three pulses."* until the
    regression has enough samples. That is a threshold, not a bug.

!!! note "Localisation, not significance"
    R² measures how much of the MEP variance the field at an element explains.
    It is not corrected for multiple comparisons and is not a significance
    test. Report the pulse count, exclusions, fit function and E-field mode
    with the map (see [Analysis and fits](results/analysis.md)).

## Results card

| Column | Meaning |
|---|---|
| **Channel** | EMG channel display name |
| **max R²** | the best R² over all ROI elements for that channel |
| **element** | the ROI triangle index where it occurs |

Clicking a row marks that channel's best element on the mesh. The summary line
below restates the pulse count and the fit function in use.

## Mapping card

| Control | Meaning |
|---|---|
| **Fit function** | one of the nine shapes (`Linear`, `Sigmoid`, …); see [Analysis and fits](results/analysis.md) |
| **Subsampling** | analyse every n-th element (`map_elms`); 1 = every element |

Changing either during a run is refused: it would change the meaning of the map
being built. Change them before Start, or finish the session first.

## Display card

| Control | Meaning |
|---|---|
| **Colour by** | what the placement spheres show: trial number, aim error, or a channel's MEP |
| **Show coil placements** | draw the realised coil positions |
| **Coil handles** | draw the handle direction of each placement |
| **Path between placements** | connect the placements in acquisition order |
| **Mark best R²** | mark the best element of the selected channel |
| **Clear** | remove the marks |

The placement colours are independent of the surface colours: the surface is the
regression, the placements are the pulses.

## Selection card

Two kinds of readout, both pinned by a click:

```text
ELEMENT 5208   ·   pinned
xyz      -25.1, 15.5, 55.8  mm
FDI      R²   0.421
APB      R²   0.187
```

```text
TRIAL 4  ·  pulse 4
xyz      -26.0, 15.1, 56.2  mm
aim error   1.3  mm
intensity     42  %MSO
E-field   precomputed
MEP FDI     1.84  mV
```

If the pulse used the online solver, the readout says `online`. If a pulse was
excluded from the mapping, the MEP is still shown but the element R² does not
include it.

## Export

**Export CSV…** writes three files sharing one base name:

| File | Contents |
|---|---|
| `<base>_roi_r2.csv` | element, x/y/z (mm), one `r2_<channel>` column per channel |
| `<base>_placements.csv` | one row per pulse: realised pose, target pose, aim error, intensity, pressure, E-field mode, MEP per channel |
| `<base>_README.txt` | the column dictionary, units and frames |

The README is generated next to the data on purpose: an exported table without
its units is ambiguous. The full column list is in
[Export and data formats](results/export.md).

**Screenshot…** saves the current view (including the corner overlays) as a PNG.
The export and the screenshot both fail gracefully if the target folder was
deleted — the message appears in the Selection card.

## What the colours mean

- **R²** is per element and per channel, computed from the pulses collected so
  far. A dark blue element is not "unstimulated"; it is an element whose field
  did not co-vary with the MEP.
- The scale is fixed to **0 to 1** for R², so the colour of a value means the
  same thing in every session and every screenshot.
- Tissue colours on the head mesh are anatomy, not results.

## Keyboard summary

| Key | Action |
|---|---|
| `B` | mark best R² |
| `H` | head / ROI |
| `F` | home camera |

## Next

- [Config page](gui/config.md)
- [Export and data formats](results/export.md)
