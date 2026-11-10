"""
Create .vtk and .vtp files from headmesh
"""
import os
import sys
import h5py
import meshio
import pyvista
import simnibs
import numpy as np
import vtk
import pynibs

print(f"SimNIBS: {simnibs.__version__}")
print(f"pyNIBS: {pynibs.__version__}")
print(f"pyvista: {pyvista.__version__}")
print(f"numpy: {np.__version__}")
print(f"meshio: {meshio.__version__}")
print(f"vtk: {vtk.vtkVersion.GetVTKVersion()}")

# fn_msh = sys.argv[1]
fn_msh = "a_msh_or_an_hdf5_filename.msh"

assert os.path.exists(fn_msh), f"Mesh file {fn_msh} does not exist"
assert fn_msh.endswith(".hdf5") or fn_msh.endswith(".msh"), f"Mesh file {fn_msh} is not in .hdf5 or .msh format."
mesh_type = os.path.splitext(fn_msh)[1].lower()

# create filenames for the different tissue types and file types
fn_vtk = f"{fn_msh.replace(mesh_type, '.vtk')}"
# fn_skin_vtp = f"{fn_msh.replace(mesh_type, '_skin.vtp')}"
# fn_gm_vtk = f"{fn_msh.replace(mesh_type, '_gm.vtk')}"
# fn_gm_vtp = f"{fn_msh.replace(mesh_type, '_gm.vtp')}"

print(f"Reading {fn_msh}")
if mesh_type == ".hdf5":
    with h5py.File(fn_msh, 'r') as f:
        nodes = f['mesh/nodes/node_coord'][:]
        tri_tissue_type = f['/mesh/elm/tri_tissue_type'][:]
        tr_con = f['/mesh/elm/triangle_number_list'][:]
        # some meshes have E-field data in it, some not
        try:
            e = f['/data/tris/E'][:]
            e_gm = e[tri_tissue_type == 1002]
            e_skin = e[tri_tissue_type == 1005]
            cell_data_skin = {"e": [e_skin]}
            cell_data_gm = {"e": [e_gm]}
        except KeyError:
            print("Could not find E field in mesh file")
            cell_data_skin = None
            cell_data_gm = None
    # tr_con_gm = tr_con[tri_tissue_type == 1002]
    # tr_con_skin = tr_con[tri_tissue_type == 1005]

    print(f"Writing {fn_vtk}")
    meshio.Mesh(points=nodes,
                cells={"triangle": tr_con},
                cell_data=cell_data_skin).write(fn_vtk)
    quit()

    print(f"Writing {fn_gm_vtk}")
    meshio.Mesh(points=nodes,
                cells={"triangle": tr_con_gm},
                cell_data=cell_data_gm).write(fn_gm_vtk)

    print(f"Writing {fn_gm_vtp}")
    poly = pyvista.PolyData(nodes, np.column_stack((np.full(len(tr_con_gm), 3), tr_con_gm)))
    if cell_data_gm is not None:
        poly.cells["e_gm"] = cell_data_gm
    poly.save(fn_gm_vtp)
    del poly

    print(f"Writing {fn_skin_vtp}")
    poly = pyvista.PolyData(nodes, np.column_stack((np.full(len(tr_con_skin), 3), tr_con_skin)))
    if cell_data_skin is not None:
        poly.cells["e_skin"] = cell_data_skin
    poly.save(fn_skin_vtp)
    del poly

else:
    # .msh
    # I'm ignoring reading/writing data arrays (such as E-fields) for now
    mesh = simnibs.read_msh(fn_msh)
    mesh_gm = mesh.crop_mesh(tags=1002)
    mesh_skin = mesh.crop_mesh(tags=1005)

    # get indices of nodes for each triangle.
    # we only take the first three columns here because simnibs also has a forth column for tetrahedra
    # also, .msh is 1-based, so indexing would go sideways if not taken care of
    tr_con_gm = mesh_gm.elm.node_number_list[:, :3] - 1  # convert to zero-based indexing
    tr_con_skin = mesh_skin.elm.node_number_list[:, :3] - 1  # convert to zero-based indexing

    nodes_gm = mesh_gm.nodes.node_coord
    nodes_skin = mesh_skin.nodes.node_coord

    print(f"Writing {fn_skin_vtk}")
    meshio.Mesh(points=nodes_skin,
                cells={"triangle": tr_con_skin}).write(fn_skin_vtk)

    print(f"Writing {fn_gm_vtk}")
    meshio.Mesh(points=nodes_gm,
                cells={"triangle": tr_con_gm}).write(fn_gm_vtk)

    print(f"Writing {fn_gm_vtp}")
    poly = pyvista.PolyData(nodes_gm, np.column_stack((np.full(len(tr_con_gm), 3), tr_con_gm)))
    if cell_data_gm is not None:
        poly.cells["e_gm"] = cell_data_gm
    poly.save(fn_gm_vtp)
    del poly

    print(f"Writing {fn_skin_vtp}")
    poly = pyvista.PolyData(nodes_skin, np.column_stack((np.full(len(tr_con_skin), 3), tr_con_skin)))
    if cell_data_skin is not None:
        poly.cells["e_skin"] = cell_data_skin
    poly.save(fn_skin_vtp)
    del poly
