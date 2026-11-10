"""Extract skin/GM/WM surfaces from a SimNIBS m2m HDF5 into STL files.

Reads the surface triangles of the volume mesh together with their tissue
tags (SimNIBS convention: 1 = WM, 2 = GM, 3 = CSF, 4 = skull, 5 = skin) and
writes one binary STL per tissue, coordinates in millimeters (same
convention as Yaseen's OUT_STL script in the controller's `code store`).

Usage:
    python scripts/make_tissue_stls.py \
        --hdf5 data/ernie/mesh/m2m_ernie/ernie.hdf5 \
        --out-dir data/ernie/surfaces
"""

import argparse
import os

import h5py
import numpy as np
import trimesh

# SimNIBS tissue tags for the surface triangles. SimNIBS 4 m2m meshes mark
# the outer surface of each tissue with tag 1000 + tissue (older meshes use
# the bare tissue number); the script accepts both.
TISSUES = {5: "skin", 2: "gm", 1: "wm"}


def select_tag(tags, tissue):
    for candidate in (1000 + tissue, tissue):
        if candidate in tags:
            return candidate
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hdf5", default="data/ernie/mesh/m2m_ernie/ernie.hdf5",
                        help="SimNIBS m2m HDF5 with the tagged volume mesh")
    parser.add_argument("--out-dir", default="data/ernie/surfaces",
                        help="directory for the STL files")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    with h5py.File(args.hdf5, "r") as f:
        nodes = f["mesh/nodes/node_coord"][:]
        tris = f["mesh/elm/triangle_number_list"][:]
        tags = f["mesh/elm/tri_tissue_type"][:]

    print(f"nodes: {nodes.shape}, surface triangles: {tris.shape}")
    print("tag counts:", {int(t): int(c) for t, c in zip(*np.unique(tags, return_counts=True))})

    for tissue, name in TISSUES.items():
        tag = select_tag(tags, tissue)
        if tag is None:
            print(f"WARNING: no surface triangles for tissue {tissue} ({name}) — skipped")
            continue
        sel = tris[tags == tag]
        if len(sel) == 0:
            print(f"WARNING: no triangles with tag {tag} ({name}) — skipped")
            continue
        mesh = trimesh.Trimesh(vertices=nodes, faces=sel, process=False)
        out = os.path.join(args.out_dir, f"ernie_{name}.stl")
        mesh.export(out)
        print(f"{name} (tag {tag}): {len(sel)} triangles, watertight={mesh.is_watertight} -> {out}")


if __name__ == "__main__":
    main()
