import trimesh
import numpy as np

mesh = trimesh.load("../../tms-robot-sim/assets/meshes/head/")

print(f"Type:          {type(mesh)}")
print(f"Triangles:     {len(mesh.faces)}")
print(f"Vertices:      {len(mesh.vertices)}")
print(f"Watertight:    {mesh.is_watertight}")
print(f"Volume:        {mesh.volume:.6f}")
print(f"Bounding box:  {mesh.bounds}")   # ← check scale!
print(f"Empty:         {mesh.is_empty}")