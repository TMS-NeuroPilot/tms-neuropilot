# Adding another robot

The pipeline itself does not know which robot moves the coil: it sends poses
and reads poses over the relay.  Everything robot-specific is concentrated in
two places:

| Where | What | Needed for |
|---|---|---|
| `src/neuropilot/sim_robot/robots.py` | one `RobotSpec` per robot: geometry, URDF, IK chain, frames | the **simulator** |
| `tms-robot-control` (separate repository) | a driver class + `ROBOT_CONFIG` entry + `ROBOT` in its `.env` | the **real** robot |

```text
pipeline_controller ──relay topics──► tms-robot-control ──vendor SDK──► robot   (real mode)
        │                                   ▲
        └──relay topics──► sim_robot ───────┘                                   (sim mode)
```

The simulated robot speaks the same topics as the production controller, so a
new robot only has to satisfy that contract in either place.

## TL;DR

| Mode | Effort | You need |
|---|---|---|
| Simulated | one dataclass entry + two assets | a MuJoCo model (with meshes) and a URDF of the same kinematic chain, then `--check` |
| Real | one driver class in `tms-robot-control` | the vendor SDK wrapper, a `ROBOT_CONFIG` tuning block, `ROBOT=<name>` in its `.env` |

A robot that exists in `tms-robot-control` but not in `robots.py` cannot be
*simulated* (the pipeline still runs it in real mode — the simulator is only
used by `neuropilot sim`).

## Bundled robots

The simulator ships four models.  The `tms-robot-control` driver names are
accepted directly in `ROBOT`, so the same value can be used on both sides.

| `ROBOT` / driver | Simulator key | Model | Notes |
|---|---|---|---|
| `omron` | `omron` | Omron TM5X-700 | MPI CBS deployment; TCP 5890 + Modbus 502 |
| `ur` | `ur5` | Universal Robots UR5 | 6 joints, 5 kg, 850 mm, ±0.1 mm |
| `elfin`, `elfin_new_api` | `elfin5` | Han's Robot Elfin E5 | Aalto / BioMag Helsinki mTMS platform, deployed at Tübingen; 6 joints, 5 kg, 800 mm, ±0.05 mm |
| `dobot` | `cr5` | Dobot CR5 | CR-series TCP-IP model; 6 joints, 5 kg, 900 mm, ±0.03 mm |

The Elfin entry records the model used by the Aalto / BioMag Helsinki mTMS
platform and deployed at the University of Tübingen.  The source is Matsuda
et al. 2025, *Phys. Med. Biol.* 70:165015,
[doi:10.1088/1361-6560/adf36e](https://doi.org/10.1088/1361-6560/adf36e)
(Methods: "Elfin E5 collaborative robot (Han's Robot Co Ltd, China). This
robot has 6 joints, a 5 kg payload capacity, an operational range of up to
80 cm, and a repeatability accuracy of ±0.05 mm.").

All four models use the same B65 coil holder mesh and place
`coil_tcp_site` 0.1 m along the tool Z axis.  The URDF carries a matching
fixed `coil_tcp` link, so the ikpy tip and the MuJoCo site are the same
physical point.  The UR5 and Dobot meshes/URDFs are third-party assets; see
`src/neuropilot/sim_robot/assets/THIRD_PARTY_LICENSES.md`.

---

## 1. Simulated mode: one spec, two assets

### 1.1 What the simulator expects from the MuJoCo model

`<robot>.xml` (+ `meshdir` meshes) included into the composed scene by
`sim_robot/mujoco_world.py`:

* the kinematic tree with **one hinge joint per actuated axis**, actuators
  named after them (the sim discovers joints/actuators from the model — no
  joint list is hard-coded);
* a `<body name="…">` that carries the robot base — named in the spec as
  `base_body` (e.g. `link_0`);
* a `<site name="…">` at the **tool point** (the coil's stimulation point) —
  named in the spec as `ee_site` (e.g. `coil_tcp_site`);
* collision geometry for self-collision and head contact, with
  `<contact><exclude …>` pairs for the links that are meant to touch
  (the coil pressed on the head);
* metres and radians (MuJoCo's convention).  The URDF may use millimetres —
  ikpy handles the units of its own file.

### 1.2 What the IK solver expects from the URDF

`ikpy` reads the URDF directly (independent of MuJoCo).  It must describe the
same chain, including the tool flange and the coil holder, so that the IK tip
is the same physical point as `ee_site`.

### 1.3 Add the spec

```python
# src/neuropilot/sim_robot/robots.py
ROBOTS = {
    "omron": RobotSpec(...),

    "ur5": RobotSpec(
        key="ur5",
        label="Universal Robots UR5",
        mjcf="assets/mjcf/ur5.xml",             # with its meshes
        urdf="assets/urdf/ur5.urdf",
        base_body="base_link",
        ee_site="coil_tcp_site",
        ik_active_links=(False, False, True, True, True, True, True, True, False, False, False),
        ik_base_elements=("base_link",),
        ik_elbow_up=True,
        base_position=(0.0, 0.0, 0.0),          # metres, room coordinates
        base_orientation=(0.0, 0.0, 0.0),       # degrees, XYZ "sxyz"
        camera_target=(0.2, -0.2, 0.15),        # overview camera look-at
        camera_offset=(0.35, -1.05, 0.20),      # … and offset from it
        max_reach_m=0.85,
        notes="6 joints; flange + B65 holder at the TCP.",
    ),
}
```

`config.py` derives **every** robot constant from the spec (`ROBOT_URDF_PATH`,
`ROBOT_BASE_BODY_NAME`, `END_EFFECTOR_SITE_NAME`, `IK_ACTIVE_LINKS_MASK`,
`IK_BASE_ELEMENTS`, `IK_ELBOW_UP`, `ROBOT_BASE_POSITION/ORIENTATION`, camera
framing, `MODEL_NAME`), so no other file needs editing.

### 1.4 Validate before starting anything

```bash
python -m neuropilot.sim_robot.robots --list          # all robots
python -m neuropilot.sim_robot.robots --check ur5     # exit 1 on problems
```

The check verifies the files exist and parse, the site and base body are
declared, the URDF contains the base element and — when `ikpy` is installed —
that the IK mask length equals the chain ikpy actually builds from the URDF.
It prints a one-screen summary of the spec.

### 1.5 Select it

* GUI: **Config › Lab › Robot** (the list comes from the registry; the label is
  shown, the key is stored), then *Save lab profile*.
* or `ROBOT=ur5` in `~/.neuropilot/lab.yaml` / `.env` (see `docs/CONFIG.md`),
  or `ROBOT=ur5 neuropilot sim` for one run.

`neuropilot.config` exports the value, the supervisor passes its environment to
the child processes, and `sim_robot` builds the scene for that robot.  An
unknown key is reported by the simulator with the list of known robots instead
of silently building the wrong machine.

### 1.6 Verify

1. `neuropilot sim` → the embedded view shows the new robot and the head.
2. Homing / free drive: the robot moves without self-collision warnings.
3. A target from InVesalius: the coil arrives with the handle pointing where
   the planner expects (compare a known point with `test_transform.py`).
4. Press: the coil touches the phantom and `force_feedback` rises above
   `PRESS_FORCE_THRESHOLD`.
5. Run 3 pulses and check the realized positions in the Cortical-results
   placement log (aim error in the expected range).

---

## 2. Real mode: a driver in `tms-robot-control`

The production controller is a separate repository (`0nu/tms-robot-control`,
`tms-robot-control-official/` in this workspace; the Omron lives on the
`mpi-cbs2026` branch).  A new robot is a subclass of
`robot/robots/robot.py::Robot` implementing:

```text
__init__(ip, config)     connect() / disconnect() / is_connected()
initialize()             home pose, modes, units
get_pose()               [x, y, z (mm), rx, ry, rz (deg, XYZ "sxyz")] or None
is_moving()              is_error_state()   read_force_sensor()
move_linear(target, speed_ratio)
move_circular(start, waypoint, target, speed_ratio)
dynamic_motion(target, speed_ratio)         # tracking mode
stop_robot()             enable_free_drive() / disable_free_drive()
close()                  clean_errors()
```

…plus a tuning block in `robot/constants.py::ROBOT_CONFIG` (`working_space_radius`,
tuning/arc thresholds, speed and force thresholds) and `ROBOT=<name>` in the
controller's `.env`.  `main_loop.py` looks the name up and constructs the
driver; nothing in NeuroPilot changes — the pipeline still speaks the relay.

Relay contract (verified against `sim_robot/message_handlers.py`):

| Topic | Direction | Payload |
|---|---|---|
| `Neuronavigation to Robot: Set target` | in | `position` mm, `orientation` deg (sxyz) |
| `Press robot button` | in | `pressed: bool` |
| `Neuronavigation to Robot: Set objective` | in | `objective: 2` = move away from head |
| `STOP` | in | `{}` |
| `Neuronavigation to Robot: Set free drive` | in | `set: bool` |
| `GUI to Robot: set default speed robot` | in | `default_speed_ratio: 0..1` |
| `GUI to Robot: set tuning speed robot` | in | `tuning_speed_ratio: 0..1` |
| `Pipeline to Robot: Set head mesh` | in | `mesh_path` (sim only; informational for hardware). `null` resets the default phantom |
| `Pipeline to Robot: Set start pose` | in | `joints` (six radians); queued before the next run |
| `SIM - Robot to Neuronavigation: Tracking State` | out | `position` mm, `orientation` deg, `ik_success`, `collision`, `motion_done`, `tracking_valid`, `qpos` |
| `Robot to Neuronavigation: Send force sensor data` | out | `force_feedback` |
| `Robot to Pipeline: Health status` | out | `robot_id`, `status` (`ok`/`error`/`nan`), `message`, `info{}` |

The `info` dict is what the Connections page shows for the robot (model,
firmware, …).  `status` drives the LED and the Start gate: an unknown or
missing status is displayed as "Not Initialized" and blocks starting.

`Pipeline to Robot: Set start pose` is implemented by the simulated robot.
The production `tms-robot-control` driver does not handle it yet, so a real
run still starts from the pose the controller already uses. Add the handler
for the installed robot model before relying on the queued pose.

---

## 3. Conventions that bite

* **Units.** Relay poses are **millimetres and degrees** (XYZ Euler, static
  frame `sxyz`); MuJoCo assets are **metres and radians**.  `sim_robot`
  converts at the boundary (`state.py` stores mm).
* **The tool point is the coil's stimulation point**, not the flange.  If the
  flange/coil-holder chain is missing from the URDF or the site is placed on
  the flange, every target is off by the tool length.
* **Coil handle.** The pipeline assumes the handle is the coil's local **−y**
  axis; the coil model (`assets/mjcf/coil/…`) and the site frame must agree.
* **Base frame.** `base_position`/`base_orientation` describe where the robot
  stands in the room; the head phantom is placed independently
  (`HEAD_POSITION`).  Both are per-lab values, not per-robot — re-measure them
  when you move the setup.
* **Joint zero/direction.** The IK (URDF) and the MuJoCo model must agree; a
  flipped joint sign gives a robot that mirrors its target.
* **Self-collision.** Add `<exclude>` pairs for links that may touch (coil ↔
  head) but not for links that must never meet; the collision checker uses
  the MJCF contact geometry.
* **Speed mapping.** The GUI slider sends `ratio = value/100`; the sim scales
  its baseline path pace by `SPEED_BASE_RATIO`.  A much faster or slower
  robot may need that constant adjusted, otherwise the tuning motion is too
  abrupt (or too slow) for the operator.
* **Pressing.** `PRESS_STEP_MM`, `PRESS_MAX_DEPTH_MM` and
  `PRESS_FORCE_THRESHOLD` model the real controller's pressure PID; a robot
  without a force sensor should report `force_feedback` from a modelled
  contact instead of a constant.
* **Reach.** Keep the head inside `max_reach_m` with some margin; the IK has
  no workspace check of its own and will fail with `ik_success: false`.

---

## 4. Tests and review checklist

* `pytest tests/test_robot_registry.py` — every spec's assets exist, the site
  and base body are declared, the IK mask matches the chain, `config`
  constants follow the spec, the CLI works.
* `python -m neuropilot.sim_robot.robots --check <key>` — same checks by hand.
* `pytest tests/test_relay_topics.py` — the topic strings still agree between
  the controller, the sim robot and the sim navigation.
* For a real robot: `neuropilot real --launch-relay`, connect from InVesalius,
  press *Connect to robot*, then move the coil a few centimetres with the
  hand-held/free-drive mode before running a mapping.  Run three pulses and
  compare the realized positions with the planned ones.

---

## 5. What was made easier (and what is still manual)

Done in this repository:

* one `RobotSpec` table instead of six scattered constants;
* `config.py` derives every constant, so nothing else needs editing;
* a validation CLI with actionable messages (`--check`, `--list`);
* the GUI lists all registered robots with human labels and stores the key;
* an unknown `ROBOT` is reported (with the known keys) instead of silently
  falling back;
* the registry is covered by tests, so adding a robot that is missing an asset
  or has a wrong IK mask fails the suite before the simulator starts.

Still manual, by nature:

* producing the MuJoCo model and the URDF (meshes, collision geometry, joint
  limits, tool chain) — CAD work, not code;
* measuring the room layout (`base_position`, head position/orientation) and
  the tool transform for a new coil;
* the real controller's driver class, which lives in `tms-robot-control`;
* validating motion quality (smoothness, collision behaviour, pressing) on the
  physical robot — no test can replace that.
