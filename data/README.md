# The small files in `data/`

The 1.9 GB example subject lives in its own repository
(`tms-localization/tms-neuropilot/tms-neuropilot-data`, cloned into
`data/ernie`). What stays here is what the code and the documentation need to
run out of the box.

| Path | What it is | Licence / provenance |
|---|---|---|
| `coil/MagVenture_MCF-B65_new.ccd` | coil model of the MagVenture MCF-B65 (new litz wire), used by the example pipeline and the simulator | taken unmodified from SimNIBS, `simnibs/resources/coil_models/Drakaki_BrainStim_2022/`; GPL-3.0 (SimNIBS). Cite Drakaki M, Mathiesen C, Siebner HR, Madsen KH, Thielscher A (2022), *Database of 25 validated coil models for electric field simulations for TMS*, Brain Stimulation 15(3):697-706, doi:10.1016/j.brs.2022.04.017 |
| `ernie.hdf5`, `create_ernie.py` | subject record and the script that wrote it, for the example subject | generated locally from the SimNIBS example dataset; see the data repository |
| `example_emg_channels.yaml`, `example_proj.txt.yaml` | example configuration files | part of this repository, GPL-3.0-or-later |

The `ernie` subject itself – `T1.inv3`, the MRI, the charm head model and the
surfaces – comes from the SimNIBS **example dataset** (subject "ernie",
<https://github.com/simnibs/example-dataset>, GPL-3.0) and keeps that licence;
the E-field library and the coil paths were computed locally with
`scripts/01_create_head_model.py` … `03_create_optimized_sequences.py`.
Details and the full attribution list are in the data repository's README.
