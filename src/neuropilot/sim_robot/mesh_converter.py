"""Convert a project head mesh into the STL the MuJoCo phantom needs.

The simulator's head body is a closed triangle mesh loaded by MuJoCo as a
collision/render geometry. The project window's head mesh is a SimNIBS
``*.msh`` (volume mesh, 1M+ triangles), which MuJoCo cannot use directly —
so the scalp surface (tissue 1) is extracted, decimated to a manageable
triangle count and written as a binary STL next to the source mesh.

Conversion runs in the simulator process on demand (see message_handlers)
and is cached: the STL is regenerated only when the source mesh is newer.
"""

import os

import numpy as np

from .utils.logging_utils import get_logger

log = get_logger(__name__)

# The default phantom (head88.stl) has 200k triangles; keep the converted
# scalp in the same range so physics/contact behaviour stays comparable.
MAX_TRIANGLES = 200_000


def convert_head_mesh(fn_msh: str) -> str:
    """Extract the scalp surface from ``fn_msh`` and write ``<stem>_head_sim.stl``.

    Returns the STL path. Raises on failure. Non-``.msh`` inputs (e.g. an
    ``*.stl`` entered directly) are returned unchanged — MuJoCo loads them
    as-is.
    """
    if not str(fn_msh).lower().endswith(".msh"):
        return fn_msh

    out_fn = os.path.splitext(fn_msh)[0] + "_head_sim.stl"
    if os.path.isfile(out_fn) and os.path.getmtime(out_fn) >= os.path.getmtime(fn_msh):
        log.info(f"Head mesh conversion cached: {out_fn}")
        return out_fn

    from simnibs import mesh_io  # lazy: slow import, only needed here
    import pyvista as pv

    log.info(f"Converting head mesh for the simulator: {fn_msh}")
    m = mesh_io.read_msh(fn_msh)
    tri_mask = m.elm.elm_type == 2
    nodes = m.nodes.node_coord[:, :3]
    tris = m.elm.node_number_list[tri_mask][:, :3].astype(int) - 1

    # Scalp = tissue 1 (SimNIBS tags 1001..1005); fall back to the full
    # outer surface if the mesh carries no tissue tags.
    tags = m.elm.tag1[tri_mask] % 1000
    scalp = tris[tags == 1]
    if len(scalp) == 0:
        log.warning("No scalp tissue (tag 1) found -- using all surface triangles.")
        scalp = tris

    faces = np.hstack((np.full((len(scalp), 1), 3), scalp)).flatten().astype(int)
    surf = pv.PolyData(nodes, faces).clean()

    if surf.n_cells > MAX_TRIANGLES:
        reduction = 1.0 - MAX_TRIANGLES / surf.n_cells
        surf = surf.decimate_pro(reduction)
        log.info(f"Scalp decimated to {surf.n_cells} triangles")

    surf.save(out_fn, binary=True)
    log.info(f"Head mesh written: {out_fn} ({surf.n_cells} triangles)")
    return out_fn
