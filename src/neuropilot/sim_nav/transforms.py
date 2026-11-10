# transforms.py
# Coordinate transformation utilities for virtual neuronavigation.
# These functions match the transformations used in tms-robot-sim.

from typing import List, Tuple
import numpy as np
from scipy.spatial.transform import Rotation


def euler_deg_to_matrix(orientation_deg: List[float]) -> np.ndarray:
    """
    Convert Euler angles in degrees [rota, rotb, rotc] (XYZ convention)
    to a 3x3 rotation matrix.
    """
    return Rotation.from_euler("xyz", orientation_deg, degrees=True).as_matrix()


def inverse_pipeline_axis_transform(
    position: List[float],
    orientation_deg: List[float],
) -> Tuple[List[float], List[float]]:
    """
    Reverse the pipeline controller's axis convention transform
    (flip z, swap x/y) to recover raw SimNIBS coordinates.

    Pipeline forward:  m[:3,2] *= -1;  swap m[:3,0] <-> m[:3,1]
    Inverse:           swap pos[0] <-> pos[1];  pos[2] *= -1
                       swap+flip rotation matrix columns back
    """
    # Inverse position: swap x/y back, un-flip z
    pos_inv = [position[1], position[0], -position[2]]

    # Inverse rotation: rebuild matrix, swap cols back, un-flip col2
    R = euler_deg_to_matrix(orientation_deg)
    R_inv = R.copy()
    R_inv[:, 0], R_inv[:, 1] = R[:, 1].copy(), R[:, 0].copy()
    R_inv[:, 2] *= -1
    euler_inv = Rotation.from_matrix(R_inv).as_euler("xyz", degrees=True).tolist()

    return pos_inv, euler_inv


def simnibs_to_nav_world(
    simnibs_pos_mm: List[float],
    simnibs_euler_deg: List[float],
    head_position_m: List[float],
    head_orientation_deg: List[float],
) -> Tuple[List[float], List[float]]:
    """
    Convert a target from raw SimNIBS space (mm) to the navigation
    coordinates (meters, robot base frame).

    Steps:
      1. mm -> meters
      2. Build 4x4 target matrix in SimNIBS frame
      3. Apply head rotation: R_head @ M_target
      4. Translate by head world position
      5. Extract world-frame position (m) and Euler (deg)
    """
    # mm -> meters
    pos_m = [v / 1000.0 for v in simnibs_pos_mm]

    # Build target 4x4 in SimNIBS local frame (meters)
    M_target = np.eye(4)
    M_target[:3, :3] = euler_deg_to_matrix(simnibs_euler_deg)
    M_target[:3, 3] = np.array(pos_m)

    # Head rotation
    R_head = euler_deg_to_matrix(head_orientation_deg)

    # Apply: world_pos = R_head @ local_pos + head_offset
    world_pos = R_head @ M_target[:3, 3] + np.array(head_position_m)
    world_rot = R_head @ M_target[:3, :3]

    # Extract Euler
    world_euler = Rotation.from_matrix(world_rot).as_euler("xyz", degrees=True).tolist()

    return world_pos.tolist(), world_euler


def m_to_mm(position_m: List[float]) -> List[float]:
    return [v * 1000.0 for v in position_m]


def nav_world_to_simnibs(
    world_pos_m: List[float],
    world_euler_deg: List[float],
    head_position_m: List[float],
    head_orientation_deg: List[float],
) -> Tuple[List[float], List[float]]:
    """
    Convert a target from the navigation world frame (meters) back to raw SimNIBS space (mm).
    This is the inverse of simnibs_to_nav_world.

    Steps:
      1. Build head rotation matrix
      2. Compute inverse: local_pos = R_head_inv @ (world_pos - head_offset)
      3. meters -> mm
      4. Extract local-frame Euler (deg)
    """
    # Head rotation
    R_head = euler_deg_to_matrix(head_orientation_deg)
    R_head_inv = R_head.T  # Inverse of rotation matrix is its transpose

    # Inverse: local_pos = R_head_inv @ (world_pos - head_offset)
    local_pos = R_head_inv @ (np.array(world_pos_m) - np.array(head_position_m))
    local_rot = R_head_inv @ euler_deg_to_matrix(world_euler_deg)

    # meters -> mm
    local_pos_mm = [v * 1000.0 for v in local_pos.tolist()]

    # Extract Euler
    local_euler = Rotation.from_matrix(local_rot).as_euler("xyz", degrees=True).tolist()

    return local_pos_mm, local_euler


def simnibs_orientation_to_external_controller(orientation_deg: List[float]) -> List[float]:
    """
    Apply pipeline's axis convention to raw SimNIBS orientation.
    Pipeline forward: flip z, swap x/y columns of rotation matrix.
    """
    R = euler_deg_to_matrix(orientation_deg)
    R_pipe = R.copy()
    R_pipe[:, 2] *= -1  # flip z
    R_pipe[:, 0], R_pipe[:, 1] = R[:, 1].copy(), R[:, 0].copy()  # swap x/y
    return Rotation.from_matrix(R_pipe).as_euler("xyz", degrees=True).tolist()


def pipeline_orientation_to_simnibs(orientation_deg: List[float]) -> List[float]:
    """
    Reverse pipeline's axis convention to get raw SimNIBS orientation.
    Inverse: swap x/y columns back, un-flip z.
    """
    R = euler_deg_to_matrix(orientation_deg)
    R_simnibs = R.copy()
    R_simnibs[:, 0], R_simnibs[:, 1] = R[:, 1].copy(), R[:, 0].copy()  # swap x/y back
    R_simnibs[:, 2] *= -1  # un-flip z
    return Rotation.from_matrix(R_simnibs).as_euler("xyz", degrees=True).tolist()
