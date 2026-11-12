# About the project

NeuroPilot is research software from the **Brain Networks** and **Neural Data
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
[`CONTRIBUTORS.md`](https://gitlab.gwdg.de/tms-localization/papers/neuropilot/-/blob/main/CONTRIBUTORS.md)
rather than copied here, so there is one list to maintain.

## Components

| Component | Role |
|---|---|
| `neuropilot.controller` | GUI, state machine, analysis, online solver |
| `neuropilot.sim_relay` | simulated Socket.IO relay |
| `neuropilot.sim_robot` | MuJoCo robot twin |
| `neuropilot.sim_nav` | virtual neuronavigation |
| [InVesalius](https://invesalius.github.io/) | neuronavigation: tracking, registration, markers |
| [`tms-robot-control`](https://gitlab.gwdg.de/tms-localization/cobot/tms-robot-control) | production relay (`relay_server.py`) and robot driver (`main_loop.py`) |
| [`pynibs`](https://gitlab.gwdg.de/tms-localization/pynibs) | MEP extraction, the nine fit functions, regression |
| [SimNIBS](https://simnibs.github.io/simnibs/) | head meshes and the online E-field solver |

The four `neuropilot.*` packages are this repository. The `sim_*` packages are
not a separate pipeline: they speak the same relay topics as InVesalius and
`tms-robot-control`, so the controller does not know whether the peer on the
other end is real or virtual. `pynibs` and SimNIBS are libraries the controller
imports, not processes.

The suite has about 740 pytest tests, including GUI tests, six-page visual
baselines and a relay-topic contract test. The documentation has its own
contract tests: every environment key, lab-profile key, relay topic and fit
function has to be documented, or CI fails. See
[Testing and CI](reference/testing.md).

## License

NeuroPilot is licensed under
**CC BY-NC-SA 4.0** (Creative Commons Attribution-NonCommercial-ShareAlike
4.0 International). You may use, share and adapt it for non-commercial
purposes (research and clinical science) with attribution and share-alike.
Commercial use needs prior permission from the authors. The full text is in
[`LICENSE`](https://gitlab.gwdg.de/tms-localization/papers/neuropilot/-/blob/main/LICENSE).

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
NeuroPilot: guided online TMS mapping with online field optimization.
Brain Networks and Neural Data Science and Statistical Computing groups,
MPI CBS Leipzig / ScaDS.AI.
https://gitlab.gwdg.de/tms-localization/papers/neuropilot
```

## Contributing

Issues and merge requests are welcome on
[GitLab](https://gitlab.gwdg.de/tms-localization/papers/neuropilot/-/issues).
Before opening a merge request:

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
