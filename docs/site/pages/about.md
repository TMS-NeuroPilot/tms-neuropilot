# About the project

TMS NeuroPilot is research software from the **Brain Networks** and **Neural Data
Science and Statistical Computing** groups at the
[Max Planck Institute for Human Cognitive and Brain Sciences](https://www.cbs.mpg.de/en)
(*MPI CBS*) and the
[Center for Scalable Data Analytics and Artificial Intelligence](https://scads.ai/)
(*ScaDS.AI*), Leipzig, Germany. It runs optimized TMS mapping experiments based
on per-pulse electric fields and integrates with InVesalius neuronavigation to
guide TMS placements across many pulses. It performs online mapping analyses,
supports robot integration, and ships a complete virtual twin to test and debug
workflows without hardware or subjects.

It is not a medical device. Real stimulation needs ethics approval, a trained
operator and the stimulator's own safety limits.

## What it is for

- Run E-field-optimized mapping experiments with online analysis
- Simulate mapping results for different optimization functions
- Switch between precomputed E-fields and online E-field calculation
- Put new optimization schemes to the test with a realistic virtual twin
- Switch mapping parameters live, such as the fit function
- Exclude single-trial responses during a run
- Train mapping experimenters in realistic settings with simulated MEPs
- Add new hardware setups, optimization schemes or fit functions thanks to the
  modular design

## Scientific scope and limits

TMS NeuroPilot implements per-pulse E-field mapping: each pulse is paired with the
field at its realised coil pose, and a regression is fitted separately for each
ROI element and EMG channel. This follows the element-wise mapping approach
described by
[Numssen et al. (2021)](https://doi.org/10.1016/j.neuroimage.2021.118654) and
the TMS mapping protocol of
[Weise et al. (2023)](https://doi.org/10.1038/s41596-022-00776-6). Coil
placement optimisation can use FPS ([Schultheiss et al., 2025](https://doi.org/10.1162/IMAG.a.1056))
or D-optimal design ([Qiu et al., 2026](https://doi.org/10.1162/IMAG.a.1446);
[Numssen, Qiu et al., 2026](https://doi.org/10.64898/2026.10.24.761539)).
The interpolated E-field mode uses the surrogate method of
[Grosshagauer et al. (2025)](https://doi.org/10.1016/j.brs.2025.102990).

The R² map is an explanatory localisation fitted to the collected pulses. It is
not a significance map, a causal source reconstruction, or a clinical
diagnosis. Report it with the pulse count, excluded pulses, fit function,
subsampling factor, E-field mode, coil model and registration quality. The
[cortical results page](gui/cortical.md) and
[analysis page](results/analysis.md) state the guards that limit
interpretation.

The virtual twin and the virtual EMG are models. They are useful for testing the
controller, the relay protocol, the mapping loop and operator training, but they
do not replace measurements of a participant's EMG or field. Real stimulation
still requires ethics approval and the stimulator's own safety limits.

## Contributors

| Contributor | Role                                                                                                                                         |
|---|----------------------------------------------------------------------------------------------------------------------------------------------|
| **[Ole Numssen](https://drOleNumssen.notion.site/)** | Maintainer and project lead (MPI CBS / ScaDS.AI)                                                                                             |
| **Abdullah Yaseen** | The controller and the simulators: virtual robot, virtual neuronavigation, simulated relay (Ernst Abbe University of Applied Sciences Jena) |
| **Samuel Berggren** | The cobot interface, movement and state machine                                                                                              |
| **Andrew Meng** | The cobot interface and movement state machine; the Ernie printable head (University of Michigan)                                                |
| **Benjamin Kalloch** | The first version; cobot movement and state machine                                                                                          |
| **Konstantin Weise** | A lot, including the coil holder and the force sensor (HTWK Leipzig / MPI CBS)                                                               |
| **Thomas R. Knösche** | Group leadership and supervision (MPI CBS / TU Ilmenau)                                                                                      |
| **Carla Martin** | InVesalius integration                                                                                                                       |
| **Renan H. Matsuda** | InVesalius integration help (Aalto University / Santos Dumont Institute, Brazil)                                                             |

Contacts and affiliations are kept in
[`CONTRIBUTORS.md`](https://github.com/TMS-NeuroPilot/tms-neuropilot/blob/main/CONTRIBUTORS.md)
rather than copied here, so there is one list to maintain.

## Components

| Component | Role |
|---|---|
| `neuropilot.controller` | GUI, state machine, analysis, online solver |
| `neuropilot.sim_relay` | simulated Socket.IO relay |
| `neuropilot.sim_robot` | MuJoCo robot twin |
| `neuropilot.sim_nav` | virtual neuronavigation |
| [InVesalius](https://invesalius.github.io/) | neuronavigation: tracking, registration, markers |
| `tms-robot-control` | production relay (`relay_server.py`) and robot driver (`main_loop.py`) |
| [`pynibs`](https://gitlab.gwdg.de/tms-localization/pynibs) | MEP extraction, the nine fit functions, regression |
| [SimNIBS](https://simnibs.github.io/simnibs/) | head meshes and the online E-field solver |

The four `neuropilot.*` packages are this repository. The `sim_*` packages are
not a separate pipeline: they speak the same relay topics as InVesalius and
`tms-robot-control`, so the controller does not know whether the peer on the
other end is real or virtual. `pynibs` and SimNIBS are libraries the controller
imports, not processes.

The suite has more than 800 pytest tests, including GUI tests, six-page visual
baselines and a relay-topic contract test. The documentation has its own
contract tests: every environment key, lab-profile key, relay topic and fit
function has to be documented, or CI fails. See
[Testing and CI](reference/testing.md).

## License

TMS NeuroPilot is licensed under the
**GNU General Public License v3.0 or later (GPL-3.0-or-later)**. You may use,
study, modify and redistribute it, including commercially; derived
distributions must stay under the GPL and make their source available. There
is no warranty. The full text is in
[`LICENSE`](https://github.com/TMS-NeuroPilot/tms-neuropilot/blob/main/LICENSE);
the bundled robot and coil assets keep their own permissive licences, listed in
[`THIRD_PARTY_LICENSES.md`](https://github.com/TMS-NeuroPilot/tms-neuropilot/blob/main/src/neuropilot/sim_robot/assets/THIRD_PARTY_LICENSES.md).

## Citing it

For the method and the virtual twin, cite the thesis:

```bibtex
@mastersthesis{yaseen2026neuropilot,
  author = {Yaseen, Abdullah},
  title  = {A Virtual Twin and Real-Time E-Field Approach for
            Robot-Assisted TMS Motor Cortex Mapping},
  school = {Ernst Abbe University of Applied Sciences Jena},
  year   = {2026}
}
```

For the software itself, cite the repository and the version or commit you
used:

```text
TMS NeuroPilot: guided online TMS mapping with online field optimization.
Brain Networks and Neural Data Science and Statistical Computing groups,
MPI CBS Leipzig / ScaDS.AI.
https://github.com/TMS-NeuroPilot/tms-neuropilot
```

## Contributing

Issues are welcome on the [public tracker](https://github.com/TMS-NeuroPilot/tms-neuropilot/issues).
Pull requests are welcome too: this repository is a read-only public mirror, so
they are ported upstream by hand rather than merged here. Before opening one:

```bash
pytest -m "not gui" -q          # or scripts/run_tests.sh
python docs/site/build.py --check
```

If you change a setting, a relay topic or a fit function, add the matching row
to the docs; the contract tests will tell you if you forgot. Changes to code
that also exists upstream (InVesalius, `tms-robot-control`) must stay additive
and unprefixed; see [Add a component](extend/components.md).

## Next

- [Changelog](reference/changelog.md): what changed, release by release.
- [Architecture](reference/architecture.md): how the processes fit together.
- [Quick start](start/quickstart.md): run it.
