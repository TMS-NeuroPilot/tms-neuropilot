import numpy as np
from .utils.transforms import (
    inverse_pipeline_axis_transform,
    simnibs_to_mujoco_world,
    m_to_mm,
)
from . import config
# Pipeline target (InVesalius convention)
pipeline_pos = [-68.30455078432443, -11.558878527014016, 61.462742309400625]
pipeline_ori = [-50.39255026296134, -42.365340047615895, 53.26226551359551]

print("=== Pipeline target (InVesalius) ===")
print(f"  position:    {pipeline_pos}")
print(f"  orientation: {pipeline_ori}")

# Step 1: inverse axis transform
simnibs_pos, simnibs_ori = inverse_pipeline_axis_transform(pipeline_pos, pipeline_ori)
print("\n=== After inverse axis transform (raw SimNIBS) ===")
print(f"  position:    {[round(v, 2) for v in simnibs_pos]}")
print(f"  orientation: {[round(v, 2) for v in simnibs_ori]}")

# Step 2: SimNIBS -> MuJoCo world
world_pos, world_ori = simnibs_to_mujoco_world(
    simnibs_pos_mm=simnibs_pos,
    simnibs_euler_deg=simnibs_ori,
    head_position_m=config.HEAD_POSITION,
    head_orientation_deg=config.HEAD_ORIENTATION,
)
world_pos_mm = m_to_mm(world_pos)

print("\n=== MuJoCo world ===")
print(f"  position (m):  {[round(v, 4) for v in world_pos]}")
print(f"  position (mm): {[round(v, 1) for v in world_pos_mm]}")
print(f"  orientation:   {[round(v, 2) for v in world_ori]}")

# Distance from robot base
robot_base = np.array(config.ROBOT_BASE_POSITION) * 1000  # to mm
dist = np.linalg.norm(np.array(world_pos_mm) - robot_base)
print(f"\n  Distance from robot base: {dist:.1f} mm")
print(f"  Robot reach: 700 mm → {'REACHABLE' if dist < 700 else 'OUT OF REACH'}")