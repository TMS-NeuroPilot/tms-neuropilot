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
same URDF chain that the simulated robot uses. The direct path between two
placements is sampled at 30 joint-space waypoints, and every waypoint is
checked. A contact or penetration is a collision; a clearance of 10 mm or less
is a near miss and is reported without stopping the scan.

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
axes**. The IK solver converts each request to joint angles and rejects a
target it cannot reach; the status line says when a jog failed.

Use a small step for final placement. A red `COLLISION` or amber `NEAR MISS`
label updates after every jog.

## Choose the start pose

Three radio groups choose the IK branch. Every option stays visible, so a
branch never depends on a dropdown popup:

- **Shoulder left** or **Shoulder right**, the sign of the first active joint;
- **Arm up** or **Arm down**, the sign of the third active joint;
- **Wrist normal** or **Wrist flipped**, the sign of the fifth active joint.

A 6R arm can have up to eight IK solutions. Some are unreachable because of
joint limits or collisions. Press **Set start pose from selection** to solve the
chosen branch. It first tries a Cartesian home point above the subject. If that
point is unreachable or in collision, it tries the pose you are currently
holding. If neither gives a collision-free branch, it restores the current pose
and asks you to jog to a clear one. The resulting six joints become the start
configuration.

Use **Set start from current** to store the six joint angles of the pose you
reached by jogging. **Move to current start pose** returns the arm to that
saved configuration. The status line reports whether the arm moved or was
already at the saved pose.

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
joint configuration for that target from the previous pose. The scan first
tries the shoulder/arm/wrist branch selected for the start pose, then retries
with the same free IK solver that the simulated experiment uses. A successful
retry is reported as an IK branch change, and the scan continues. If both
solvers fail, the arm remains at the last reached target and the status says
so. The simulated experiment may still reach such a target because it does not
lock the start-pose shoulder/wrist branch and may choose another approach.

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
- the production controller's crane, blend and force-control trajectory;
- cable routing and the robot's real joint limits beyond the URDF model.

Use the page to eliminate obvious bad layouts, then confirm the final cell on
the real robot at low speed.

## Next

- [Real session checklist](run/real.md): the ordered hardware procedure.
- [Relay reference](reference/relay.md): the full message contract, including
  `Pipeline to Robot: Set start pose`.
