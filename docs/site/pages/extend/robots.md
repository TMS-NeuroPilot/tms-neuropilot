# Add a robot

The pipeline is robot-agnostic: it sends poses over the relay and reads poses
back. Everything robot-specific lives in one `RobotSpec` plus two assets, so
adding a robot to the **simulator** is a table entry.

!!! info "Two places, two goals"
    - The **simulator** needs `sim_robot/robots.py` + a MuJoCo model + a URDF.
    - A **real** robot needs a driver in `tms-robot-control`, which is a
      separate repository with its own configuration.

    This page covers the simulator; the full recipe, including the real-driver
    side and the relay contract, is in
    [`docs/ROBOTS.md`](https://gitlab.gwdg.de/tms-localization/papers/neuropilot/-/blob/main/docs/ROBOTS.md).

## The spec

```python
# src/neuropilot/sim_robot/robots.py
ROBOTS = {
    "omron": RobotSpec(...),

    "ur5": RobotSpec(
        key="ur5",
        label="Universal Robots UR5e",
        mjcf="assets/mjcf/ur5e.xml",          # with its meshes
        urdf="assets/urdf/ur5e.urdf",
        base_body="base_link",
        ee_site="coil_tcp_site",
        ik_active_links=(False, True, True, True, True, True, True, False, False),
        ik_base_elements=("base_link",),
        ik_elbow_up=True,
        base_position=(0.0, 0.0, 0.0),        # metres, room coordinates
        base_orientation=(0.0, 0.0, 0.0),     # degrees, XYZ "sxyz"
        camera_target=(0.2, -0.2, 0.15),
        camera_offset=(0.35, -1.05, 0.20),
        max_reach_m=0.85,
        notes="6 joints; flange + B65 holder at the TCP.",
    ),
}
```

`sim_robot/config.py` derives every robot constant from the spec
(`ROBOT_URDF_PATH`, `ROBOT_BASE_BODY_NAME`, `END_EFFECTOR_SITE_NAME`,
`IK_ACTIVE_LINKS_MASK`, `IK_BASE_ELEMENTS`, `IK_ELBOW_UP`, the base pose, the
camera framing and `MODEL_NAME`), so no other file needs editing.

## The assets

| Asset | Must provide |
|---|---|
| MuJoCo XML | the kinematic tree, one hinge joint per actuated axis, actuators named after the joints, a base body, a site at the coil's **stimulation point**, collision geometry |
| URDF | the same chain including the flange and coil holder, so ikpy's tip is the same physical point as the MuJoCo site |

MuJoCo works in metres and radians; the URDF may use millimetres (ikpy handles
its own file). The tool point is the **stimulation point**, not the flange — a
tool-point error moves the focus by exactly that error.

## Validate before starting

```bash
python -m neuropilot.sim_robot.robots --list
python -m neuropilot.sim_robot.robots --check ur5
```

`--check` verifies that:

- the files exist and parse,
- the base body and the end-effector site are declared,
- the URDF contains the base element,
- the IK mask length equals the chain ikpy builds from the URDF.

It exits non-zero on a problem and prints a summary of the spec.

## Select it

- **Config › Lab › Robot** — the list comes from the registry; the label is
  shown and the key is stored.
- `ROBOT=ur5` in `.env` or `~/.neuropilot/lab.yaml`.
- `ROBOT=ur5 neuropilot sim` for one run.

An unknown key is reported with the list of known robots instead of silently
building the wrong machine.

## Verify in the simulator

1. `neuropilot sim` — the view shows the new robot and the head.
2. The arm homes and moves without self-collision warnings.
3. A target moves the coil to the head with the handle in the expected
   direction.
4. The **Control** log shows `Coil at target` for a target inside the reach.

## Real robots

`tms-robot-control` needs:

- a driver class that speaks the relay topics
  (`Neuronavigation to Robot: Set target`, `… Set objective`,
  `… Set free drive`, `Press robot button`, `STOP`),
- a `ROBOT_CONFIG` tuning block,
- `ROBOT=<name>` in its own `.env`.

NeuroPilot does not change for a real robot: it already sends the same topics
the simulator answers.

## Checklist

- [ ] `--check` returns 0
- [ ] `--list` shows the new key and label
- [ ] the coil site is the stimulation point
- [ ] the handle direction matches the physical coil
- [ ] `ROBOT=<key> neuropilot sim` starts without a traceback
- [ ] `pytest tests/test_robot_registry.py -q` passes

## Next

- [Themes](extend/themes.md)
- [Add a component](extend/components.md)
- [Relay protocol](reference/relay.md)
