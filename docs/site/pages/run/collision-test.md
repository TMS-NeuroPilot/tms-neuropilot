# Collision test

Long coil handles and a subject who can only sit a few ways make robot-cell
layout a real constraint. The **Collision test** page lets you find a subject
position, robot base and start configuration before a real experiment, using
the selected robot model in a local MuJoCo scene. It does not stimulate, record
EMG, fit a map or talk to the real robot.

The page is available in every mode that has a robot. It is disabled in manual
and training modes, where there is no arm to test.

## What it checks

- the robot and coil holder against the subject head phantom;
- robot self-collision;
- every placement in the project's placement file, in file order;
- the direct joint-space path from the start pose and then from one placement
  to the next.

It stops at the first collision or IK failure and leaves the arm at that pose,
so you can see what hit. The head and robot base can then be moved, the start
pose changed, and the scan restarted. Placements are converted with the same
pipeline-to-robot axis convention as the simulated robot and then into the
robot base frame, so the planned world pose and an executed target agree even
after the base is moved.

## Method

The scene is compiled from the selected robot's MJCF model and the subject
skin surface. MuJoCo evaluates contacts and nearest distances; ikpy solves the
same URDF chain that the simulated robot uses. The scan follows the production
direct-or-upward rule. It compares the largest per-axis translation with
`TRANSLATION_THRESHOLD` (millimetres) and the largest per-axis rotation with
`ROTATION_THRESHOLD` (degrees). If either limit is exceeded, the arm climbs to
`SAFE_HEIGHT` (millimetres), traverses above the head and descends. Otherwise
it uses a direct joint-space line. There is no separate 20 mm retract
waypoint. Each segment is sampled at 30 waypoints and every waypoint is
checked. The same three values are also used by the manual move-away and
emergency paths, where the arm always climbs to `SAFE_HEIGHT`.

A head penetration of 4 mm or more and a self-penetration of 2 mm or more
count as collisions. The 4 mm head allowance matches the production
simulation, where the coil is pressed into the scalp. A head clearance of
10 mm or less is a near miss and is reported without stopping the scan.

Self-collision ignores overlaps shallower than 2 mm. The robot's collision
meshes overlap by about 1 mm at some wrist configurations even though the
rendered links look clear, so these shallow self-contacts are treated as mesh
overlap. A self-penetration of 2 mm or more still stops the scan. This
tolerance is a modelling limit, not a hardware safety margin.

MuJoCo is described in Todorov, Erez and Tassa (2012), *MuJoCo: A physics
engine for model-based control*, IEEE/RSJ International Conference on
Intelligent Robots and Systems. ikpy is a pure-Python inverse-kinematics
library built on the URDF joint chain.

!!! danger "Safety: planning aid, not a certificate"
    The scene contains the head phantom only. It does not model the subject's
    shoulders, torso, chair or the room. The path is a joint-space
    interpolation, not the production controller's exact trajectory. The real
    robot controller and its force/safety limits remain the final authority.

## Enable it

Press **Enable collision test**. The first enable builds the local world and
IK chain; later scans reuse it. The page also loads the project head mesh and
converts its skin surface to an STL, so the phantom matches the subject.

The 3D view uses the same embedded renderer as the simulated robot view. Drag
to orbit, right-drag to pan, wheel to zoom, double click to reset. Its
top-right overlay mirrors the Control page: **Total targets** and **Current**
show the same `pulse 0 · 1/1 · target 44` counters. The path waypoint is in
the status line below the scan controls. The collision test checks the target
geometry; it does not fire stimulation pulses.

## Position the subject and robot

| Control | Unit | Meaning |
|---|---|---|
| **Robot base** | mm, deg | Where the robot stands in the room and how it is rotated |
| **Subject placement** | mm, deg | Where the SimNIBS head origin sits relative to the robot base |

Each row has −/+ buttons for a small nudge. Changing either pose resets the arm
to the stored start configuration and updates the collision label.

The head and robot base are **relative descriptions** of the tested cell. They
do not move the real robot base; they record the arrangement you validated.

## Jog the coil

The jog pad moves the coil site in **world XYZ** and rotates about the **tool
axes**. The numbers beside the axis names show the current coil-site pose in
world millimetres and tool degrees. The IK solver converts each request to
joint angles and rejects a target it cannot reach; the status line says when a
jog failed.

Use a small step for final placement. A red `COLLISION` or amber `NEAR MISS`
label updates after every jog.

## Choose the start pose

Three radio groups choose the IK branch. Every option stays visible, so a
branch never depends on a dropdown popup:

- **Shoulder left** or **Shoulder right**, the sign of the first active joint;
- **Arm up** or **Arm down**, the sign of the third active joint;
- **Wrist normal** or **Wrist flipped**, the sign of the fifth active joint.

The elbow boundary is inclusive: a straight arm has zero on the third joint
and is the Omron arm-up pose. The simulator's power-on configuration is the
same zero joint pose, and the collision test starts from that pose as well.
The wrist sign is evaluated on the canonical joint angle in
[-180°, 180°], not on an arbitrary 360° representation. This keeps normal and
flipped physically distinct instead of showing the same pose twice.

A 6R arm can have up to eight IK solutions. Some are unreachable because of
joint limits or collisions. Press **Set start pose from selection** to solve
the chosen branch for the coil pose the robot currently holds. The coil
placement stays fixed; only the arm configuration changes. If only a colliding
solution exists, it still stores that pose and warns you to adjust the
base/head before scanning. If no solution exists, it leaves the current pose
untouched, keeps your radio selection, and asks you to jog to another pose.
The resulting six joints become the start configuration.

Use **Set start from current** to store the six joint angles of the pose you
reached by jogging. **Reset to start** in the placement-scan row returns the
arm to that saved configuration. The status line reports whether the arm moved
or was already at the saved pose.

## Movement limits

The compact row under **Start pose** exposes the three values that decide
between a direct move and the safe-height path:

| Field | `.env` key | Unit | Meaning |
|---|---|---|---|
| Safe Z | `SAFE_HEIGHT` | mm | Z above the robot base that the arm climbs to before traversing |
| Trans. | `TRANSLATION_THRESHOLD` | mm | Largest per-axis translation that still allows a direct move |
| Rot. | `ROTATION_THRESHOLD` | deg | Largest per-axis rotation that still allows a direct move |

The fields start from the `.env` values in `neuropilot/.env` and can be
changed before a scan. A change stops the current scan, so the next scan
starts with the new limits. The values are stored in the project and lab
collision blocks and are sent to the simulated robot on
`Pipeline to Robot: Set motion limits` at the next experiment start. The
names and units match `tms-robot-control/.env`; the production controller
must handle the topic before it can apply project values without an `.env`
restart.

## Run the scan

1. Load the project's placement file on the **Project** page.
2. Choose a start pose and, if needed, adjust the movement limits.
3. Press **Start collision scan**.

The scan follows the project's target-order file and repetition count, so its
pulse numbers and target IDs match the Control page. Without an order file it
uses every placement in file order. The progress bar counts reached pulses. On
a collision the scan stops, the message names the pulse and target, and the
arm stays at the colliding waypoint.

The robot base and subject placement can be changed while a scan is running.
The scan continues from the current pulse, regenerates the remaining target
poses from the new layout and replans the current target from the arm's
present pose. It does not restart at pulse zero. The progress bar keeps the
pulses already completed.

The collision line keeps the last near miss or collision visible after the
current pose becomes clear, and the completed-scan summary reports the number
of near-miss waypoints and the closest distance. A green "current pose clear"
line therefore does not hide an earlier problem.

An **IK failure is not a collision**. It means the selected shoulder, arm and
wrist branch cannot reach that target from the previous pose. The scan keeps
the chosen branch for every target and every safe-height or retract waypoint;
it never substitutes another arm shape. If a waypoint or target has no
solution in that branch, the scan stops, leaves the arm at the last reached
target, and says that the selected branch has no IK solution. This is the
behaviour the simulated experiment uses when the start pose carries the same
branch.

## Save and use the result

| Button | Effect |
|---|---|
| **Make project default** | Stores head pose, robot base, start joints and branch in the project YAML |
| **Make lab default** | Stores the same block in `~/.neuropilot/lab.yaml` for projects that do not override it |
| **Use at start pose** | Queues the six-joint start pose and its branch for the next experiment start |

The project value wins over the lab default. The start pose and branch are sent
on `Pipeline to Robot: Set start pose`; the simulated planner then solves every
target and path waypoint in the same branch. The production
`tms-robot-control` driver must handle that topic before a real run can use it.
The head and base values are the validated cell description and remain part of
the project record.

## What is not modelled yet

- subject shoulders, torso, chair and table;
- the production controller's exact blend, force-control and press trajectory;
- cable routing and the robot's real joint limits beyond the URDF model;
- link 3 against link 5 self-contact, because MuJoCo convexifies mesh geoms and
  the convex hull of the forearm fills the wrist fork; the visual meshes have
  about 15 mm clearance in the folded pose that used to report a collision.

Use the page to eliminate obvious bad layouts, then confirm the final cell on
the real robot at low speed.

## Next

- [Real session checklist](run/real.md): the ordered hardware procedure.
- [Relay reference](reference/relay.md): the full message contract, including
  `Pipeline to Robot: Set start pose`.
