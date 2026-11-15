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
same URDF chain that the simulated robot uses. The scan follows the simulated
planner's motion strategy. The first target from the saved start pose uses the
350 mm safe height. Later moves above 20 mm retract the coil 20 mm along the
negative tool normal, away from the head, traverse, then approach the target
along its normal. If that short path is blocked, the safe-height path is used
as a fallback. Shorter moves use a direct joint-space line. The 350 mm safe
height is also reserved for the manual move-away, end and emergency actions.
Each segment is sampled at 30 waypoints and every waypoint is checked.

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

## Run the scan

1. Load the project's placement file on the **Project** page.
2. Choose a start pose.
3. Press **Start collision scan**.

The scan follows the project's target-order file and repetition count, so its
pulse numbers and target IDs match the Control page. Without an order file it
uses every placement in file order. The progress bar counts reached pulses. On
a collision the scan stops, the message names the pulse and target, and the
arm stays at the colliding waypoint. Move the base, head or start pose, press
**Reset to start**, and run it again.

An **IK failure is not a collision**. It means the solver could not find a
joint configuration for that target from the previous pose. The scan uses the
same free IK solver and elbow preference as the simulated experiment. The
shoulder/arm/wrist selection shapes the start pose and the initial joint
configuration; it is not a per-target lock, because the simulated planner can
choose another branch. If the solver lands in a different branch, the scan
reports an IK branch change and continues. If the solver fails, the arm remains
at the last reached target and the status says so.

## Save and use the result

| Button | Effect |
|---|---|
| **Make project default** | Stores head pose, robot base, start joints and branch in the project YAML |
| **Make lab default** | Stores the same block in `~/.neuropilot/lab.yaml` for projects that do not override it |
| **Use at start pose** | Queues the six-joint start pose for the next experiment start |

The project value wins over the lab default. The start pose is sent on
`Pipeline to Robot: Set start pose`; the production `tms-robot-control` driver
must handle that topic before a real run can use it. The head and base values
are the validated cell description and remain part of the project record.

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
