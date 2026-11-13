import math
import numpy as np
from .ik_solver import IKPySolver
from .utils.transforms import (
    inverse_pipeline_axis_transform,
    simnibs_to_mujoco_world,
    m_to_mm,
    orientation_distance_deg,
)
from . import config
solver = IKPySolver(
    urdf_path=config.ROBOT_URDF_PATH,
    active_links_mask=config.IK_ACTIVE_LINKS_MASK,
    base_elements=config.IK_BASE_ELEMENTS,
)

# ── Problematic target from pipeline ──
# Raw pipeline input (as received from virtual_neuronavigation)
pipeline_position = [-68.30455078432443, -11.558878527014016, 61.462742309400625]
pipeline_orientation = [-38.55619229320643, -52.960963392048235, 37.364085973181886]

print("=" * 60)
print("=== STEP 1: Raw pipeline input ===")
print(f"  position (mm):      {[round(v, 2) for v in pipeline_position]}")
print(f"  orientation (deg):  {[round(v, 2) for v in pipeline_orientation]}")

# ── Apply same transforms as message_handlers.py ──
# Step 1: inverse_pipeline_axis_transform (only orientation changes)
_, simnibs_ori = inverse_pipeline_axis_transform(pipeline_position, pipeline_orientation)

print()
print("=== STEP 2: After inverse_pipeline_axis_transform ===")
print(f"  position (mm):      {[round(v, 2) for v in pipeline_position]}  (unchanged)")
print(f"  simnibs_ori (deg):  {[round(v, 2) for v in simnibs_ori]}")

# Step 2: simnibs_to_mujoco_world
world_pos, world_ori = simnibs_to_mujoco_world(
    simnibs_pos_mm=pipeline_position,
    simnibs_euler_deg=simnibs_ori,
    head_position_m=config.HEAD_POSITION,
    head_orientation_deg=config.HEAD_ORIENTATION,
)

print()
print("=== STEP 3: After simnibs_to_mujoco_world ===")
print(f"  world_pos (m):      {[round(v, 4) for v in world_pos]}")
print(f"  world_ori (deg):    {[round(v, 2) for v in world_ori]}")

# Step 3: Convert to mm for state
state_pos_mm = m_to_mm(world_pos)

print()
print("=== STEP 4: Final state (what IK solver receives) ===")
print(f"  position (mm):      {[round(v, 2) for v in state_pos_mm]}")
print(f"  orientation (deg):  {[round(v, 2) for v in world_ori]}")

# ── Test 1: Regular solve (no configuration preference) ──
print()
print("=" * 60)
print("=== TEST 1: Regular solve (no configuration preference) ===")

success, joint_solution = solver.solve(
    position_mm=state_pos_mm,
    orientation_deg=world_ori,
)

print(f"  Success: {success}")
if success and joint_solution is not None:
    active_joints_rad = [joint_solution[i] for i in solver.active_indices]
    active_joints_deg = [round(math.degrees(j), 2) for j in active_joints_rad]
    print(f"  Joints (deg): {active_joints_deg}")
    print(f"  joint_3 (elbow): {'UP' if active_joints_rad[2] > 0 else 'DOWN'} ({active_joints_deg[2]:+.2f} deg)")

# ── Test 2: Solve with elbow up configuration ──
print()
print("=" * 60)
print("=== TEST 2: Solve with elbow up configuration ===")

success, joint_solution = solver.solve_with_config(
    position_mm=state_pos_mm,
    orientation_deg=world_ori,
    elbow_up=True,
    max_retries=config.IK_MAX_RETRIES,
)

print(f"  Success: {success}")
if success and joint_solution is not None:
    active_joints_rad = [joint_solution[i] for i in solver.active_indices]
    active_joints_deg = [round(math.degrees(j), 2) for j in active_joints_rad]
    print(f"  Joints (deg): {active_joints_deg}")
    print(f"  joint_3 (elbow): {'UP' if active_joints_rad[2] > 0 else 'DOWN'} ({active_joints_deg[2]:+.2f} deg)")

    # Verify with FK
    pos, ori = solver.forward(joint_solution)
    pos_err = np.linalg.norm(np.array(pos) - np.array(state_pos_mm))
    ori_err = orientation_distance_deg(ori, world_ori)

    print()
    print("=== FK Verification ===")
    print(f"  FK Position (mm):      {[round(v, 2) for v in pos]}")
    print(f"  FK Orientation (deg):  {[round(v, 2) for v in ori]}")
    print(f"  Position error (mm):    {pos_err:.2f}")
    print(f"  Orientation error (deg): {ori_err:.2f}")
    print(f"  motion_done would be:   {pos_err < 4.0 and ori_err < 1.0}")

    # Check joint limits
    joint_limits = [
        (-360, 360),   # joint_1
        (-360, 360),   # joint_2
        (-155, 155),   # joint_3
        (-360, 360),   # joint_4
        (-360, 360),   # joint_5
        (-360, 360),   # joint_6
    ]
    print()
    print("=== Joint limit check ===")
    for i, (j_rad, (lo, hi)) in enumerate(zip(active_joints_rad, joint_limits)):
        j_deg = math.degrees(j_rad)
        near_limit = abs(j_deg - hi) < 10 or abs(j_deg - lo) < 10
        status = " *** NEAR LIMIT ***" if near_limit else ""
        print(f"  joint_{i+1}: {j_deg:+8.2f} deg  (range: {lo} to {hi}){status}")

    # Compare with old working solution
    print()
    print("=== Comparison with old working solution ===")
    print("  Old (working):  [-3.16, +26.65, +120.67, -49.09, +28.42, +74.15]")
    print(f"  New (elbow up): {active_joints_deg}")
    print("  Note: Joint values may differ due to different TCP offset (0.1 vs 0.1108 m)")

else:
    print("  IK failed to find a solution")
