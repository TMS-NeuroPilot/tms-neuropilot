# evaluator.py

#Contains the logic for:

    #comparing current robot pose to target pose,

    #deciding if pose is within tolerance,

    #suppressing success if collision is true.


# evaluator.py

import math
from typing import Sequence, Tuple


def wrap_angle_deg(angle: float) -> float:
    return ((angle + 180.0) % 360.0) - 180.0


def angle_diff_deg(a: float, b: float) -> float:
    return abs(wrap_angle_deg(a - b))


def position_error_mm(p1: Sequence[float], p2: Sequence[float]) -> float:
    return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(p1, p2)))


def orientation_error_deg(o1: Sequence[float], o2: Sequence[float]) -> Tuple[float, float, float]:
    return tuple(angle_diff_deg(a, b) for a, b in zip(o1, o2))


def is_pose_within_tolerance(
    current_position,
    current_orientation,
    target_position,
    target_orientation,
    position_tol_mm,
    orientation_tol_deg,
):
    pos_err = position_error_mm(current_position, target_position)
    rot_err = orientation_error_deg(current_orientation, target_orientation)

    within = (
        pos_err <= position_tol_mm
        and all(err <= orientation_tol_deg for err in rot_err)
    )

    return within, pos_err, rot_err