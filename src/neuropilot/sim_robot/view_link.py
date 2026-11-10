#!/usr/bin/env python3
"""
View a single robot link's visual and collision meshes side by side.

Usage:
    python view_link.py <link_name>

Examples:
    python view_link.py link_6
    python view_link.py link_2
    python view_link.py flange
    python view_link.py all
"""

import os
import sys
import mujoco
import mujoco.viewer
import time

MESHES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "meshes")
#MESHES_DIR = "/data/u_yaseen_software/git/Omron_TM_robots-ROS/src/tmr_ros1/tm5_description/meshes"

LINK_MESHES = {
    "link_0": {
        "visual":    "robot/tm5-900/visual/tm5-base.obj",
        "collision": "robot/tm5-900/collision/tm5-base_c.stl",
    },
    "link_1": {
        "visual":    "robot/tm5-900/visual/tmr_400w_01_conv.stl",
        "collision": "robot/tm5-900/collision/tmr_400w_01_c.stl",
    },
    "link_2": {
        "visual":    "robot/tm5-700/visual/tm5-700_arm1_conv.stl",
        "collision": "robot/tm5-700/collision/tm5-700_arm1_c.stl",
    },
    "link_3": {
        "visual":    "robot/tm5-700/visual/tm5-700_arm2_conv.stl",
        "collision": "robot/tm5-700/collision/tm5-700_arm2_c.stl",
    },
    "link_4": {
        "visual":    "robot/tm5-900/visual/tmr_100w_01.stl",
        "collision": "robot/tm5-900/collision/tmr_100w_01_c.stl",
        #"visual":    "robot/tm5_900/visual/tmr_100w_01.obj",
        #"collision": "robot/tm5_900/collision/tm_100w_01_c.stl",

    },
    "link_5": {
        "visual":    "robot/tm5-900/visual/tmr_100w_02.obj",
        "collision": "robot/tm5-900/collision/tmr_100w_02_c.stl",
    },
    "link_6": {
        "visual":    "robot/tm5-900/visual/tmr_iox_conv.stl",
        "collision": "robot/tm5-900/collision/tmr_iox_c.stl",
    },
    "flange": {
        "visual":    "coil/coil_holder_fs_w_mcf_b65.stl",
        "collision": "coil/coil_holder_fs_w_mcf_b65.stl",
    },
}


def build_xml(link_name: str) -> str:
    meshes = LINK_MESHES[link_name]
    vis_file = meshes["visual"]
    col_file = meshes["collision"]

    scale_attr = ""
    if vis_file.endswith("coil_holder_fs_w_mcf_b65.stl"):
        scale_attr = ' scale="0.001 0.001 0.001"'

    return f'''
<mujoco model="view_{link_name}">
  <compiler meshdir="{MESHES_DIR}/" angle="radian"/>

  <asset>
    <mesh file="{vis_file}" name="vis_mesh"{scale_attr}/>
    <mesh file="{col_file}" name="col_mesh"{scale_attr}/>
    <texture type="skybox" builtin="gradient" rgb1="0.8 0.85 0.9" rgb2="0.4 0.45 0.5" width="512" height="512"/>
    <texture name="tex_grid" type="2d" builtin="checker" rgb1="0.8 0.8 0.8" rgb2="0.6 0.6 0.6" width="512" height="512"/>
    <material name="mat_grid" texture="tex_grid" texrepeat="10 10" texuniform="true"/>
    <material name="mat_vis" specular="0.5" shininess="0.3" rgba="0.5 0.5 0.5 1"/>
    <material name="mat_col" specular="0.3" shininess="0.2" rgba="0.8 0.4 0.1 1"/>
  </asset>

  <visual>
    <headlight ambient="0.4 0.4 0.4" diffuse="0.8 0.8 0.8" specular="0.2 0.2 0.2"/>
  </visual>

  <worldbody>
    <geom name="floor" type="plane" size="2 2 0.01" pos="0 0 -0.15" material="mat_grid"/>

    <body name="vis_body" pos="-0.15 0 0">
      <geom name="visual" type="mesh" mesh="vis_mesh" material="mat_vis"/>
    </body>

    <body name="col_body" pos="0.15 0 0">
      <geom name="collision" type="mesh" mesh="col_mesh" material="mat_col"/>
    </body>

    <camera name="front" pos="0 -0.6 0.3" xyaxes="1 0 0 0 0.7 0.7"/>
    <camera name="top" pos="0 0 0.6" xyaxes="1 0 0 0 1 0"/>
    <camera name="side" pos="0.6 0 0.3" xyaxes="0 -1 0 0 0 1"/>

    <light pos="0 0 1" dir="0 0 -1" diffuse="0.8 0.8 0.8"/>
    <light pos="0 -1 0.5" dir="0 1 -0.5" diffuse="0.4 0.4 0.4"/>
  </worldbody>
</mujoco>
'''


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    link_name = sys.argv[1]

    if link_name == "all":
        print("Available links:")
        for name, meshes in LINK_MESHES.items():
            print(f"  {name:8s}  vis={meshes['visual'].split('/')[-1]:30s}  col={meshes['collision'].split('/')[-1]}")
        return

    if link_name not in LINK_MESHES:
        print(f"Error: unknown link '{link_name}'")
        print(f"Available: {', '.join(LINK_MESHES.keys())}")
        sys.exit(1)

    meshes = LINK_MESHES[link_name]
    print(f"Link: {link_name}")
    print(f"  Visual:    {meshes['visual']}")
    print(f"  Collision: {meshes['collision']}")
    print()

    xml = build_xml(link_name)
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)

    print("Viewer controls:")
    print("  Left mouse:   rotate")
    print("  Right mouse:  pan")
    print("  Scroll:       zoom")
    print("  1/2/3:        switch camera (front/top/side)")
    print("  Space:        pause")
    print("  Esc:          quit")
    print()
    print("Left  = VISUAL mesh (grey)")
    print("Right = COLLISION mesh (orange)")

    with mujoco.viewer.launch_passive(model, data) as viewer:
        while viewer.is_running():
            viewer.sync()
            time.sleep(1.0 / 60.0)


if __name__ == "__main__":
    main()
