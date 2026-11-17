# Detailed B35 case v2.4 meshes

Source CAD: `B35 with Case v2.4.stl` (single-channel case, provided
2026-11-17). The detailed B65 case remains the default; these meshes are
prepared for setups using the smaller B35 case.

The source was rotated with the same CAD-to-robot rotation as the B65 case:

```text
R = [[ 0, 1,  0],
     [ 0, 0, -1],
     [-1, 0,  0]]
```

It was translated so that `x` is centred, the case/handle centre is at
`y = 70 mm`, and the coil-face side starts at `z = 0`:

```text
t = [-82.1777, 440.2253, 510.7684]  # mm
```

Two derivatives are kept:

- `coil_holder_b35_case_v2.4_fixed.stl` — transformed detailed mesh for
  visualisation.
- `coil_holder_b35_case_v2.4_collision.stl` — watertight, single-component
  collision derivative: 2 mm voxel remesh, marching cubes, 0.6 decimation
  (17,937 vertices, 35,910 triangles).

To select this case instead of the B65 default, set:

```ini
COIL_HOLDER=b35
```

The simulator rewrites only the coil mesh includes in the selected robot MJCF;
the arm model and `coil_tcp_site` remain unchanged.
