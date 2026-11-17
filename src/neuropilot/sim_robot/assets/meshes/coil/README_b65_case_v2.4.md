# Detailed B65 case v2.4 meshes

Source CAD: `B65 with Case v2.4.stl` (single-channel case, provided 2026-11-17).

The source is not in the robot frame. It was rotated and translated to match the
old `coil_holder_fs_w_mcf_b65.stl` bounding-box centre and the existing
`coil_tcp_site` frame:

```text
R = [[ 0, 1,  0],
     [ 0, 0, -1],
     [-1, 0,  0]]
t = [55.8482, 452.3162, 674.3690]  # mm
```

Two derivatives are kept:

- `coil_holder_b65_case_v2.4_fixed.stl` — transformed detailed mesh, used for
  visualisation. It is the original multi-shell CAD output.
- `coil_holder_b65_case_v2.4_collision.stl` — watertight, single-component
  collision derivative: 2 mm voxel remesh, marching cubes, 0.6 decimation
  (20,224 vertices, 40,512 triangles).

The previous simplified holder `coil_holder_fs_w_mcf_b65.stl` is retained for
reference and rollback.
