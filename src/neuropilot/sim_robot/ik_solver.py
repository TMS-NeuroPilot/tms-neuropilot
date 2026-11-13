import math
import os
import random
from typing import List, Optional, Tuple

import numpy as np
from ikpy.chain import Chain
from scipy.spatial.transform import Rotation

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


class IKPySolver:
    def __init__(
        self,
        urdf_path: str,
        active_links_mask: Optional[List[bool]] = None,
        base_elements: Optional[List[str]] = None,
        end_effector_link_name: Optional[str] = None,
    ):
        self.urdf_path = urdf_path
        self.active_links_mask = active_links_mask
        self.base_elements = base_elements
        self.end_effector_link_name = end_effector_link_name

        self.chain = self._build_chain()
        # The chain length differs per robot (fixed base/tool frames are
        # included).  Active *movable* joints are the mask entries that are
        # true and whose ikpy link is not fixed.
        self.active_indices = [
            i for i, link in enumerate(self.chain.links)
            if link.joint_type != "fixed"
            and (self.active_links_mask is None or self.active_links_mask[i])
        ]

    def _build_chain(self) -> Chain:
        urdf_abs = os.path.join(PROJECT_ROOT, self.urdf_path)
        kwargs = {
            "urdf_file": urdf_abs,
        }

        if self.active_links_mask is not None:
            kwargs["active_links_mask"] = self.active_links_mask

        if self.base_elements is not None:
            kwargs["base_elements"] = self.base_elements

        if self.end_effector_link_name is not None:
            kwargs["last_link_vector"] = None

        return Chain.from_urdf_file(**kwargs)

    @staticmethod
    def mm_to_m(position_mm: List[float]) -> List[float]:
        return [float(v) / 1000.0 for v in position_mm]

    @staticmethod
    def m_to_mm(position_m: List[float]) -> List[float]:
        return [float(v) * 1000.0 for v in position_m]

    @staticmethod
    def euler_deg_to_rotation_matrix(orientation_deg: List[float]) -> np.ndarray:
        return Rotation.from_euler("xyz", orientation_deg, degrees=True).as_matrix()

    @staticmethod
    def build_target_frame(position_mm: List[float], orientation_deg: List[float]) -> np.ndarray:
        target_frame = np.eye(4)
        target_frame[:3, :3] = IKPySolver.euler_deg_to_rotation_matrix(orientation_deg)
        target_frame[:3, 3] = np.array(IKPySolver.mm_to_m(position_mm))
        return target_frame

    def solve(
        self,
        position_mm: List[float],
        orientation_deg: List[float],
        initial_position: Optional[List[float]] = None,
    ) -> Tuple[bool, Optional[List[float]]]:
        try:
            target_frame = self.build_target_frame(position_mm, orientation_deg)

            if initial_position is None:
                initial_position = [0.0] * len(self.chain.links)

            joint_solution = self.chain.inverse_kinematics_frame(
                target=target_frame,
                initial_position=initial_position,
                orientation_mode="all",
            )

            if joint_solution is None:
                return False, None

            return True, [float(v) for v in joint_solution]

        except Exception as exc:
            print(f"[tms-robot-sim] IK solve failed: {exc}")
            return False, None

    def solve_with_config(
        self,
        position_mm: List[float],
        orientation_deg: List[float],
        initial_position: Optional[List[float]] = None,
        elbow_up: bool = True,
        max_retries: int = 10,
    ) -> Tuple[bool, Optional[List[float]]]:
        """
        Solve IK with configuration preference (elbow up/down).

        Args:
            position_mm: Target position in mm
            orientation_deg: Target orientation in degrees
            initial_position: Initial joint positions (padded with inactive links)
            elbow_up: True for elbow up (joint_3 positive), False for elbow down
            max_retries: Maximum number of retries with different initial positions

        Returns:
            (success, joint_solution) - same as solve()
        """
        # The elbow is the third movable joint; its index in the full ikpy
        # solution depends on the fixed links in the robot's URDF.
        if len(self.active_indices) < 3:
            return False, None
        elbow_idx = self.active_indices[2]

        # First try with the provided initial position
        success, solution = self.solve(position_mm, orientation_deg, initial_position)

        if success and solution is not None:
            joint_3_val = solution[elbow_idx]
            is_elbow_up = joint_3_val > 0

            if is_elbow_up == elbow_up:
                # Solution matches desired configuration
                return True, solution

        # Solution doesn't match desired configuration, retry with different initial positions
        target_frame = self.build_target_frame(position_mm, orientation_deg)

        for retry in range(max_retries):
            # Create a random initial position with joint_3 biased toward desired configuration
            if initial_position is not None:
                new_initial = list(initial_position)
            else:
                new_initial = [0.0] * len(self.chain.links)

            # Bias joint_3 toward desired configuration
            # For elbow up: positive angle (e.g., +2.0 rad ≈ 115°)
            # For elbow down: negative angle (e.g., -2.0 rad ≈ -115°)
            if elbow_up:
                new_initial[elbow_idx] = random.uniform(1.0, 2.5)  # positive = elbow up
            else:
                new_initial[elbow_idx] = random.uniform(-2.5, -1.0)  # negative = elbow down

            # Also add some randomness to other active joints to explore
            # different configurations.
            for i in self.active_indices:
                if i != elbow_idx:
                    new_initial[i] += random.uniform(-0.5, 0.5)

            try:
                joint_solution = self.chain.inverse_kinematics_frame(
                    target=target_frame,
                    initial_position=new_initial,
                    orientation_mode="all",
                )

                if joint_solution is not None:
                    joint_3_val = joint_solution[elbow_idx]
                    is_elbow_up = joint_3_val > 0

                    if is_elbow_up == elbow_up:
                        print(f"[IK] Found elbow {'up' if elbow_up else 'down'} solution on retry {retry + 1}")
                        return True, [float(v) for v in joint_solution]

            except Exception:
                continue

        # If we couldn't find a matching configuration, return the original solution
        if success and solution is not None:
            print(f"[IK] Warning: Could not find elbow {'up' if elbow_up else 'down'} solution after {max_retries} retries, using best available")
            return True, solution

        return False, None

    def forward(
        self,
        joint_positions: List[float],
    ) -> Tuple[List[float], List[float]]:
        frame = self.chain.forward_kinematics(joint_positions)

        position_m = frame[:3, 3]
        rotation_matrix = frame[:3, :3]
        orientation_deg = Rotation.from_matrix(rotation_matrix).as_euler("xyz", degrees=True)

        return self.m_to_mm(position_m.tolist()), orientation_deg.tolist()

    def compute_pose_error(
        self,
        target_position_mm: List[float],
        target_orientation_deg: List[float],
        achieved_position_mm: List[float],
        achieved_orientation_deg: List[float],
    ) -> dict:
        pos_error = np.array(achieved_position_mm) - np.array(target_position_mm)
        rot_error = np.array(achieved_orientation_deg) - np.array(target_orientation_deg)

        return {
            "position_error_mm": pos_error.tolist(),
            "position_error_norm_mm": float(np.linalg.norm(pos_error)),
            "orientation_error_deg": rot_error.tolist(),
            "orientation_error_norm_deg": float(np.linalg.norm(rot_error)),
        }