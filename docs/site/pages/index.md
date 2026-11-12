<div class="hero" markdown="0">
<h1>NeuroPilot</h1>
<p class="lead">Guided, robot-assisted TMS mapping with a per-pulse electric field and a
cortical R² map that grows while the session runs.</p>
<div class="badges">
  <span class="badge accent">Python 3.11</span>
  <span class="badge">PyQt5 + asyncio</span>
  <span class="badge">SimNIBS 4.5</span>
  <span class="badge">CC BY-NC-SA 4.0</span>
  <span class="badge">730+ tests</span>
</div>
</div>

NeuroPilot runs one TMS mapping experiment from a single window. It tells the
neuronavigation where the next coil target is, waits until the robot has the
coil on that target, fires the stimulator, records the EMG response, computes
the E-field the pulse actually delivered, and folds the result into a
regression whose R² is painted over the subject's cortex.

The same window runs against the real lab or against a complete virtual twin —
relay, neuronavigation and a MuJoCo robot — so a new user can learn the
workflow, and a developer can change it, without touching hardware.

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
  <img src="assets/diagrams/architecture.svg" alt="The four NeuroPilot processes — controller, relay, neuronavigation and robot — and the hardware they replace or drive.">
  <figcaption>One controller process drives three peers over a Socket.IO relay.
  In simulation the peers are NeuroPilot's own virtual twin; in a real session
  they are InVesalius and the robot controller.</figcaption>
</figure>

The controller is the conductor. Every coil target is created as a marker in the
neuronavigation; the robot moves the coil to it; the stimulator fires; the EMG
is cut into a window around the pulse and reduced to a peak-to-peak amplitude;
and that amplitude is regressed against the E-field of the same pulse. Because
the E-field is known per pulse — from a precomputed library or from a SimNIBS
solve that runs while the coil moves — the map does not have to assume a
uniform field.

<div class="status-grid" markdown="0">
  <div class="status"><span class="k">Mapping loop</span><span class="v">7 steps</span></div>
  <div class="status"><span class="k">E-field modes</span><span class="v">2, switchable live</span></div>
  <div class="status"><span class="k">Fit functions</span><span class="v">9</span></div>
  <div class="status"><span class="k">Colour themes</span><span class="v">5 (3 light, 2 dark)</span></div>
</div>

## Run the simulator in three commands

```bash
conda activate pipeline
pip install -e . --no-deps          # once, from the repository root
neuropilot sim                      # relay → nav + robot → controller
```

The supervisor waits for each component's readiness probe before starting the
next, prefixes every log line with its role, and shuts the whole stack down on
Ctrl+C. When the window opens, load the bundled `ernie` example project and
press **Start mapping**.

!!! tip "No hardware, no risk"
    The simulated stack is the recommended way to learn the interface. It runs
    the same controller code, the same relay protocol and the same state
    machine as a real session — only the three peers are virtual.

## How to read this site

- **Start here** → [Key concepts](start/concepts.md) explains the vocabulary
  (target, pulse, E-field, MEP, R²) used everywhere else.
- **Install** covers the environment, SimNIBS, the `.env` bootstrap and the
  hardware wiring.
- **Prepare a session** is the data side: mesh, ROI, E-field library,
  placements, EMG channels and the project file.
- **Run a session** walks through the three run modes and the mapping loop.
- **GUI reference** documents every page, card and button.
- **Configuration** is the complete key reference for `.env`, the lab profile
  and study profiles.
- **Reference** holds the architecture, relay protocol, CLI, tests and
  troubleshooting.

!!! note "This documentation lives with the code"
    Every page is a Markdown file under `docs/site/pages/` in the repository
    and is published by CI on each push to `main`. The *Edit this page* link at
    the bottom of every page opens the source.
