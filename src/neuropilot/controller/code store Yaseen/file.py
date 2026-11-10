
import h5py
import numpy as np
from stl import mesh as stl_mesh
import os

HDF5_PATH = '/data/pt_01756/probands/30298.bb/mesh/charm_beta/m2m_30298.bb/30298.bb.hdf5'   # ← change this
OUT_STL   = '/data/u_yaseen_software/git/tms-robot-sim/assets/meshes/head/head.stl'
OUT_URDF  = '/data/u_yaseen_software/git/tms-robot-sim/assets/urdf/head.urdf'

os.makedirs(os.path.dirname(OUT_STL),  exist_ok=True)
os.makedirs(os.path.dirname(OUT_URDF), exist_ok=True)

# --- 1. Read HDF5 ---
with h5py.File(HDF5_PATH, 'r') as f:
    nodes  = f['mesh/nodes/node_coord'][:]         # (N, 3)
    tris   = f['/mesh/elm/triangle_number_list'][:] # (M, 3)

print(f'Nodes: {nodes.shape}, Triangles: {tris.shape}')

# --- 2. Build STL ---
head_mesh = stl_mesh.Mesh(np.zeros(tris.shape[0], dtype=stl_mesh.Mesh.dtype))
for i, tri in enumerate(tris):
    for j in range(3):
        head_mesh.vectors[i][j] = nodes[tri[j]]

head_mesh.save(OUT_STL)
print(f'STL saved → {OUT_STL}')

# --- 3. Write URDF ---
# Check if coordinates are in mm (values > 10) or meters
max_coord = np.abs(nodes).max()
scale = '0.001 0.001 0.001' if max_coord > 10 else '1 1 1'
print(f'Max coordinate value: {max_coord:.1f} → using scale={scale}')

urdf = f'''<?xml version=\"1.0\"?>
<robot name=\"head\">
  <link name=\"world\"/>
  <joint name=\"fixed\" type=\"fixed\">
    <parent link=\"world\"/>
    <child link=\"head_link\"/>
    <origin xyz=\"0 0 0\" rpy=\"0 0 0\"/>
  </joint>
  <link name=\"head_link\">
    <visual>
      <geometry>
        <mesh filename=\"assets/meshes/head/head.stl\" scale=\"{scale}\"/>
      </geometry>
      <material name=\"skin\">
        <color rgba=\"1.0 0.8 0.7 0.9\"/>
      </material>
    </visual>
    <collision>
      <geometry>
        <mesh filename=\"assets/meshes/head/head.stl\" scale=\"{scale}\"/>
      </geometry>
    </collision>
    <inertial>
      <mass value=\"4.5\"/>
      <inertia ixx=\"0.016\" ixy=\"0\" ixz=\"0\" iyy=\"0.016\" iyz=\"0\" izz=\"0.016\"/>
    </inertial>
  </link>
</robot>'''

with open(OUT_URDF, 'w') as f:
    f.write(urdf)
print(f'URDF saved → {OUT_URDF}')