"""Convert a project head mesh into the STL the MuJoCo phantom needs.

The simulator's head body is a closed triangle mesh loaded by MuJoCo as a
collision/render geometry. The project window's head mesh is a SimNIBS
``*.msh`` (volume mesh, 1M+ triangles), which MuJoCo cannot use directly —
so the skin surface is extracted, decimated to a manageable triangle count
and written as a binary STL next to the source mesh.

The skin is identified by its tissue number: SimNIBS labels skin
tetrahedra with tag 5 and their boundary triangles with tag 1005 (the
tag numbering runs from the inside out, WM=1...SCALP=5).

Conversion runs in the simulator process on demand (see message_handlers)
and is cached: the STL is regenerated only when the source mesh is newer or
the converter version changed.
"""

import json
import os

import numpy as np

from .utils.logging_utils import get_logger

log = get_logger(__name__)

# The default phantom (head.stl) has 200k triangles; keep the converted
# skin in the same range so physics/contact behaviour stays comparable.
MAX_TRIANGLES = 200_000
CONVERTER_VERSION = 3  # bump to invalidate cached STLs after logic changes
SKIN_TRIANGLE_TAG = 5  # SimNIBS: skin triangles carry tag 1005 (== 5 mod 1000)


def convert_head_mesh(fn_msh: str) -> str:
    """Extract the skin surface from ``fn_msh`` and write ``<stem>_head_sim.stl``.

    Returns the STL path. Raises on failure. Non-``.msh`` inputs (e.g. an
    ``*.stl`` entered directly) are returned unchanged — MuJoCo loads them
    as-is.
    """
    if not str(fn_msh).lower().endswith(".msh"):
        return fn_msh

    out_fn = os.path.splitext(fn_msh)[0] + "_head_sim.stl"
    version_fn = os.path.splitext(out_fn)[0] + "_sim_version.json"
    if (os.path.isfile(out_fn) and os.path.isfile(version_fn)
            and os.path.getmtime(out_fn) >= os.path.getmtime(fn_msh)):
        try:
            with open(version_fn) as f:
                if json.load(f).get("converter_version") == CONVERTER_VERSION:
                    log.info(f"Head mesh conversion cached: {out_fn}")
                    return out_fn
        except (OSError, ValueError):
            pass

    from simnibs import mesh_io  # lazy: slow import, only needed here
    import pyvista as pv

    log.info(f"Converting head mesh for the simulator: {fn_msh}")
    m = mesh_io.read_msh(fn_msh)
    tri_mask = m.elm.elm_type == 2
    nodes = m.nodes.node_coord[:, :3]
    tris = m.elm.node_number_list[tri_mask][:, :3].astype(int) - 1
    tags = m.elm.tag1[tri_mask]

    # Skin triangles carry tag 1005 (== 5 mod 1000) in SimNIBS meshes.
    skin = tris[(tags % 1000) == SKIN_TRIANGLE_TAG]
    if len(skin) == 0:
        raise ValueError(
            f"No skin surface (tag {SKIN_TRIANGLE_TAG}) found in {fn_msh} -- "
            "is this a SimNIBS head mesh?"
        )
    log.info(f"Skin surface: {len(skin)} triangles")

    faces = np.hstack((np.full((len(skin), 1), 3), skin)).flatten().astype(int)
    surf = pv.PolyData(nodes, faces).clean()

    if surf.n_cells > MAX_TRIANGLES:
        reduction = 1.0 - MAX_TRIANGLES / surf.n_cells
        surf = surf.decimate_pro(reduction)
        log.info(f"Skin decimated to {surf.n_cells} triangles")

    surf.save(out_fn, binary=True)
    with open(version_fn, "w") as f:
        json.dump({"converter_version": CONVERTER_VERSION,
                   "source": fn_msh}, f)
    log.info(f"Head mesh written: {out_fn} ({surf.n_cells} triangles)")
    return out_fn
