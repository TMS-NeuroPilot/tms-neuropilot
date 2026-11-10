import trimesh

mesh = trimesh.load(r"/data/u_yaseen_software/git/tms-robot-sim/assets/meshes/head/head2.stl")
print(f"Original: {len(mesh.faces)} triangles, {len(mesh.vertices)} vertices")

simplified = mesh.simplify_quadric_decimation(face_count=800000)
print(f"Simplified: {len(simplified.faces)} triangles, {len(simplified.vertices)} vertices")

simplified.export(r"/data/u_yaseen_software/git/tms-robot-sim/assets/meshes/head/head_visual_8k.stl")
print("Saved head_visual.stl")