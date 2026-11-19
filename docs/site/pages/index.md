<div class="hero" markdown="0">
<h1>NeuroPilot</h1>
<p class="lead">Running optimized TMS mapping experiments with per-pulse electric fields,
online analysis, InVesalius neuronavigation and a complete virtual twin.</p>
<div class="badges">
  <span class="badge accent">Python 3.11</span>
  <span class="badge">PyQt5 + asyncio</span>
  <span class="badge">SimNIBS 4.5</span>
  <span class="badge">InVesalius 3.1</span>
  <span class="badge">CC BY-NC-SA 4.0</span>
</div>
</div>

NeuroPilot guides the experimenter through a mapping experiment: the coil is
held by hand (manual mode) or by a TMS robot (real mode, via
[tms-robot-control](https://gitlab.gwdg.de/tms-localization/cobot/tms-robot-control)),
while the software collects the EMG responses and runs element-wise mapping
analyses online.
That enables high-resolution structure-function mapping
([Numssen et al., 2021](https://doi.org/10.1016/j.neuroimage.2021.118654);
[Weise et al., 2023](https://doi.org/10.1038/s41596-022-00776-6)).

It integrates with [InVesalius](https://invesalius.github.io/) neuronavigation to
guide the coil across many placements, controls the stimulator, and uses
[SimNIBS](https://simnibs.github.io/simnibs/) for online E-field calculations.
Experiments can use different optimization schemes, for example
FPS ([Schultheiss et al., 2025](https://doi.org/10.1162/IMAG.a.1056)) or
D-optimal ([Numssen, Qiu et al., 2026](https://doi.org/10.64898/2026.10.24.761539)),
and the analysis
runs online; single trials can be excluded by hand and the full data set
exported. The software is open source and can be adapted to local hardware,
outcome metrics and new optimization schemes.

A full virtual-twin mode allows extensive testing of new optimization schemes
under realistic conditions (noise, individual morphology, experimental demands
and session duration) to dry-run robotic experiments or to train experimenters
on simulated MEPs and realistic tracking.

<figure>
  <img src="assets/screenshots/neuropilot-sim-session.gif" alt="A simulated session: the Control page with the robot twin, the MEP page, the cortical R² map and the Connections page.">
  <figcaption>A simulated session, sped up. The twin moves the coil from target
  to target, the MEP page shows the responses as pulses arrive, the cortical map
  is computed online, and the Connections page reports the health of all
  subsystems.</figcaption>
</figure>

<div class="cards" markdown="0">
  <a class="card" href="start/quickstart.html">
    <span class="card-kicker">New here</span>
    <span class="card-title">Run the simulator <span class="arrow">→</span></span>
    <p>Install once, then run a full mapping session in ten minutes with no
    hardware at all.</p>
  </a>
  <a class="card" href="run/real.html">
    <span class="card-kicker">Operator</span>
    <span class="card-title">Prepare a real session <span class="arrow">→</span></span>
    <p>Subject data, E-field library, lab profile and the ordered checklist for
    the day of the experiment.</p>
  </a>
  <a class="card" href="reference/architecture.html">
    <span class="card-kicker">Developer</span>
    <span class="card-title">Understand the suite <span class="arrow">→</span></span>
    <p>Components, relay topics, the state machine, the configuration layers
    and the test suite.</p>
  </a>
</div>

<figure class="screenshot-wide">
  <img src="assets/screenshots/control-precomputed.png" alt="The NeuroPilot Control page: transport buttons and stimulation settings on the left, the E-field mode and the virtual robot in the middle, robot speeds and the session log on the right.">
  <figcaption>The Control page during a simulated session: transport and
  stimulation on the left, the E-field mode and the virtual robot in the
  middle, the session log underneath. The other five pages cover the project,
  the connections, the MEPs, the cortical map and the configuration.</figcaption>
</figure>

## What it does

<figure>
  <img src="assets/diagrams/architecture.svg" alt="The four NeuroPilot processes (controller, relay, neuronavigation and robot) and the hardware they replace or drive.">
  <figcaption>One controller process drives three peers over a Socket.IO relay.
  In simulation the peers are NeuroPilot's own virtual twin; in a real session
  they are InVesalius, the robot driver and the production relay.</figcaption>
</figure>

A mapping session is a loop over pulses:

1. The controller takes the next target from the target order.
2. It creates that target as a marker in the neuronavigation.
3. The robot, or the operator in manual mode, moves the coil there.
4. The stimulator fires.
5. The EMG is cut into a window around the pulse and reduced to a peak-to-peak MEP.
6. The pulse's E-field is read from the precomputed library or solved
   online for the realised coil pose.
7. For each ROI element, the MEPs are regressed against |E| at that cortical
   location across all trials, and the R² map is updated. The map supports
   localisation of the cortical source; it is not a significance test.

This 'voxel-wise' mapping approach can also be applied to map other responses,
such as phosphene production, reaction time, or heart-brain coupling in other
functions and brain regions.

## Run the simulator in three commands

```bash
conda activate neuropilot
pip install -e . --no-deps          # once, from the repository root
neuropilot sim                      # relay → nav + robot → controller
```

When the NeuroPilot GUI has loaded, load the `ernie` example project and press
**Start**.

!!! tip "No hardware required"
    The simulated stack is the recommended way to learn the interface. It runs
    the same controller code, the same relay protocol and the same state
    machine as a real session; only the relay, neuronavigation and robot are
    virtual twins.

## How to read this site

- **Start here** → [Key concepts](start/concepts.md) explains the vocabulary
  (target, pulse, E-field, MEP, R²) used everywhere else.
- **Install** covers the environment, SimNIBS, the `.env` bootstrap and the
  hardware wiring.
- **Prepare a session** is the data side: mesh, ROI, E-field library,
  placements, EMG channels and the project file.
- **Run a session** walks through the four run modes and the mapping loop.
- **GUI reference** documents every page, card and button.
- **Configuration** is the complete key reference for `.env`, the lab profile
  and study profiles.
- **Reference** holds the architecture, relay protocol, CLI, tests and
  troubleshooting.
- **About** covers who builds it, the components, the license and how to cite it.
