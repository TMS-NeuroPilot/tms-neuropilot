# Units and frames

Most "the robot went to the wrong place" reports are a units or frame mistake,
not a robot fault. This page states the conventions once, so the rest of the
site can refer to them.

## The two unit systems

| Context | Length | Rotation | Where |
|---|---|---|---|
| Relay messages | millimetres | degrees, intrinsic XYZ Euler (`sxyz`) | every `position` / `orientation` field |
| MuJoCo scene | metres | radians | `sim_robot` internals, MJCF assets |
| SimNIBS files | millimetres | degrees (matrix) | `m2m_*`, ROI HDF5, placements, E-field library |
| URDF | metres (file may differ; ikpy converts) | radians | `sim_robot/assets/urdf/` |
| Coil model `.ccd` | millimetres | its own frame | SimNIBS coil library |

The conversion points are few and deliberate:

- `controller/pipeline_controller.py` converts a `matsimnibs` 4×4 matrix to
  `(position_mm, euler_deg)` with `transformations.euler_from_matrix(m, "sxyz")`
  before anything is sent.
- `sim_robot` converts mm/degrees at its relay boundary and works in SI inside.
- The 3-D viewer converts nothing: it reads the same SimNIBS-space mesh the
  analysis uses, so mesh, placements and E-field columns share one frame.

## The frames

```text
SimNIBS head space  ── registration ──►  neuronavigation space
        │                                        │
        │ (targets, mesh, E-field columns)       │ (tracked coil, markers)
        ▼                                        ▼
   project files                          robot base frame
        │                                        │
        └────────────► analysis ◄────────────────┘
                        (realised poses, per pulse)
```

| Frame | Origin and axes | Used by |
|---|---|---|
| **SimNIBS head space** | the subject's T1, NIfTI convention (x right, y posterior, z superior), mm | mesh, ROI, placements, E-field, exported coordinates |
| **Neuronavigation space** | InVesalius' patient space after registration | markers, tracked coil, "coil at target" |
| **Robot base frame** | the robot's own base, metres | motion planning in `tms-robot-control` |
| **Coil local frame** | origin at the stimulation point, handle along **−y** | coil model, tool chain, IK target |

!!! danger "Safety: the tool point is the stimulation point"
    The robot's tool centre point (its end-effector site — `coil_tcp_site` in the
    shipped model) is the coil's stimulation point, not the flange and not the
    handle. If you change the coil
    mount, re-measure the tool point before the next real session. A tool-point
    error moves the focus by exactly that error.

## The coil-handle convention

The coil's local **−y** axis points along the handle, away from the head. The
robot's IK orients the coil with that convention; the 3-D viewer draws the
handle segment using the same axis. A coil whose handle is drawn in the wrong
direction is usually a transpose in an orientation matrix, not a modelling
error.

## Reading a target

A target is a 4×4 `matsimnibs` matrix:

```text
[ R  t ]      R = 3x3 rotation, columns = coil local axes in head space
[ 0  1 ]      t = coil stimulation point in head space, mm
```

The position is `t`. The orientation is `R`. When a file stores many targets
the layout is `(4, 4, n)` — one matrix per placement, **index-aligned with the
rows of the E-field library**. This is why sorting the placements reorders the
E-field rows and the target-order file together (see
[Coil placements](prepare/placements.md)).

## Checklist before trusting a target

- [ ] The mesh, the placements and the E-field library come from the **same**
      SimNIBS run of the **same** subject.
- [ ] The number of placements equals the first dimension of `E_mag`.
- [ ] The number of E-field columns equals the number of ROI triangles.
- [ ] The target-order file only contains indices in `0 … n_placements - 1`.
- [ ] In simulation, the coil visibly touches the head at the target.
- [ ] In a real session, the neuronavigation's registration was accepted and
      the coil is inside the tracking volume at the first target.

## Next

- [Coil placements and target order](prepare/placements.md) — the files these
  conventions apply to.
- [Add a robot](extend/robots.md) — where the base pose and tool site are
  declared.
