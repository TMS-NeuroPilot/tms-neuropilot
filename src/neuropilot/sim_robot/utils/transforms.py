from typing import List, Tuple
import numpy as np
from scipy.spatial.transform import Rotation

#import sys
#from pathlib import Path
#sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
#import transformations as tr



def euler_deg_to_quat(orientation_deg: List[float]) -> List[float]:
    """
    Convert Euler angles in degrees [rota, rotb, rotc] (XYZ convention)
    to quaternion [x, y, z, w].
    """
    r = Rotation.from_euler("xyz", orientation_deg, degrees=True)
    q = r.as_quat()  # returns [x, y, z, w]
    return q.tolist()


def quat_to_euler_deg(quat_xyzw: List[float]) -> List[float]:
    """
    Convert quaternion [x, y, z, w] to Euler angles in degrees [rota, rotb, rotc]
    (XYZ convention).
    """
    r = Rotation.from_quat(quat_xyzw)
    return r.as_euler("xyz", degrees=True).tolist()


def euler_deg_to_matrix(orientation_deg: List[float]) -> np.ndarray:
    """
    Convert Euler angles in degrees [rota, rotb, rotc] (XYZ convention)
    to a 3x3 rotation matrix.
    """
    return Rotation.from_euler("xyz", orientation_deg, degrees=True).as_matrix()


def pose_to_matrix(
    position: List[float],
    orientation_deg: List[float],
) -> np.ndarray:
    """
    Build a 4x4 homogeneous transform matrix from:
      - position [x, y, z] in mm
      - orientation [rota, rotb, rotc] in degrees (XYZ Euler)
    """
    mat = np.eye(4)
    mat[:3, :3] = euler_deg_to_matrix(orientation_deg)
    mat[:3, 3]  = np.array(position, dtype=float)
    return mat


def matrix_to_pose(mat: np.ndarray) -> Tuple[List[float], List[float]]:
    """
    Decompose a 4x4 homogeneous transform matrix back into:
      - position [x, y, z] in mm
      - orientation [rota, rotb, rotc] in degrees (XYZ Euler)
    """
    position        = mat[:3, 3].tolist()
    orientation_deg = Rotation.from_matrix(mat[:3, :3]).as_euler("xyz", degrees=True).tolist()
    return position, orientation_deg


def position_distance_mm(pos_a: List[float], pos_b: List[float]) -> float:
    """
    Euclidean distance between two positions in mm.
    """
    return float(np.linalg.norm(np.array(pos_a) - np.array(pos_b)))


def orientation_distance_deg(ori_a: List[float], ori_b: List[float]) -> float:
    """
    Angular distance between two orientations given as XYZ Euler degrees.
    Returns the geodesic angle in degrees between the two rotations.
    """
    r_a = Rotation.from_euler("xyz", ori_a, degrees=True)
    r_b = Rotation.from_euler("xyz", ori_b, degrees=True)
    r_diff = r_a.inv() * r_b
    return float(np.degrees(r_diff.magnitude()))


def mm_to_m(position_mm: List[float]) -> List[float]:
    return [v / 1000.0 for v in position_mm]


def m_to_mm(position_m: List[float]) -> List[float]:
    return [v * 1000.0 for v in position_m]


def inverse_pipeline_axis_transform(
    position: List[float],
    orientation_deg: List[float],
) -> Tuple[List[float], List[float]]:
    """
    Reverse the pipeline controller's axis convention transform
    (flip z, swap x/y) to recover raw SimNIBS coordinates.

    Pipeline forward:  m[:3,2] *= -1;  swap m[:3,0] <-> m[:3,1]

    """

    # TODO: this variant leaves the position untouched, while the same
    # function in sim_nav/transforms.py also inverts the position
    # (swap x/y, flip z) to undo the documented forward transform. Either
    # the callers here compensate separately or this is a latent bug --
    # check the robot message handling (message_handlers.py) before
    # changing this.
    pos = [position[0], position[1], position[2]]

    # Inverse rotation: rebuild matrix, swap cols back, un-flip col2
    R = euler_deg_to_matrix(orientation_deg)
    R_inv = R.copy()
    R_inv[:, 0], R_inv[:, 1] = R[:, 1].copy(), R[:, 0].copy()
    R_inv[:, 2] *= -1
    #print("HERE IS THE TRANSFORMED TARGET MATRIX", R_inv)
    euler_inv = Rotation.from_matrix(R_inv).as_euler("xyz", degrees=True).tolist()
    #print("HERE IS THE TRANSFORMED TARGET degrees", euler_inv)
    #R_inv_4x4 = np.eye(4)
    #R_inv_4x4[:3, :3] = R
    #euler_inv2 = np.degrees(tr.euler_from_matrix(R_inv_4x4, "sxyz"))
    #print("HERE IS THE TRANSFORMED TARGET degrees 2nd version", euler_inv2)
    #print("HERE IS THE TRANSFORMED TARGET pose", pos)

    return pos, euler_inv


def pipeline_target_to_mujoco_world(
    pipeline_pos_mm: List[float],
    pipeline_euler_deg: List[float],
    head_position_m: List[float],
    head_orientation_deg: List[float],
) -> Tuple[List[float], List[float]]:
    """Convert a pipeline/InVesalius target to the MuJoCo world frame.

    ``read_simnibs_targets_data`` leaves the position in raw SimNIBS space but
    changes the orientation to the InVesalius coil convention.  Undo only that
    orientation transform, then place the target with the subject-head pose.
    This is the single conversion used by the simulated robot and by the
    collision-test scan, so a planned placement and an executed placement agree.
    """
    _, simnibs_ori = inverse_pipeline_axis_transform(
        pipeline_pos_mm, pipeline_euler_deg)
    return simnibs_to_mujoco_world(
        pipeline_pos_mm, simnibs_ori, head_position_m, head_orientation_deg)


def simnibs_to_mujoco_world(
    simnibs_pos_mm: List[float],
    simnibs_euler_deg: List[float],
    head_position_m: List[float],
    head_orientation_deg: List[float],
) -> Tuple[List[float], List[float]]:
    """
    Convert a target from raw SimNIBS space (mm) to MuJoCo world
    coordinates (meters, robot base frame).

    Steps:
      1. mm → meters
      2. Build 4x4 target matrix in SimNIBS frame
      3. Apply head rotation: R_head @ M_target
      4. Translate by head world position
      5. Extract world-frame position (m) and Euler (deg)
    """
    # mm → meters
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