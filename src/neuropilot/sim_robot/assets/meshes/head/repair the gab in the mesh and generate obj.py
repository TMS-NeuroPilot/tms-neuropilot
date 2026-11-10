import trimesh

# Load original full-res mesh
mesh = trimesh.load(r"D:\Max Planck work\tms-robot-sim\assets\meshes\head\head2.stl")
print(f"Original: {len(mesh.faces)} tris, watertight={mesh.is_watertight}")

# Fix normals (make all face normals point outward)
mesh.fix_normals()
print("Normals fixed")

# Fill holes to make it watertight
trimesh.repair.fill_holes(mesh)
print(f"After fill_holes: watertight={mesh.is_watertight}")

# If still not watertight, try the more aggressive repair
if not mesh.is_watertight:
    # Convert to volume and back — forces watertight
    pitch = mesh.extents.min() / 200  # voxel size
    voxel = mesh.voxelized(pitch)
    mesh = voxel.marching_cubes
    print(f"After voxel repair: {len(mesh.faces)} tris, watertight={mesh.is_watertight}")

# Decimate to ~200K for visual
if len(mesh.faces) > 200000:
    mesh = mesh.simplify_quadric_decimation(face_count=500000)
    print(f"After decimation: {len(mesh.faces)} tris")

# Fix normals again after decimation
mesh.fix_normals()

# Export as OBJ (stores vertex normals for smooth shading)
mesh.export(r"D:\Max Planck work\tms-robot-sim\assets\meshes\head\head_visual_5k.obj")
print(f"Saved head_visual.obj: {len(mesh.faces)} tris, watertight={mesh.is_watertight}")

# Also export as STL backup
#mesh.export(r"D:\Max Planck work\tms-robot-sim\assets\meshes\head\head_visual.stl")
#print("Saved head_visual.stl")