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
        tip: str = "coil_tcp",
        end_effector_link_name: Optional[str] = None,
    ):
        self.urdf_path = urdf_path
        self.active_links_mask = active_links_mask
        # ikpy >= 4.4 deprecates base_elements (removed in 5.0).  The new
        # API takes the base link name; our specs always pass exactly one.
        self.base_elements = base_elements
        # The URDF link where the chain ends (the tool point); the new ikpy
        # API needs it explicitly when several branches leave the base link.
        self.tip = tip
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
            kwargs["base"] = self.base_elements[0]

        kwargs["tip"] = self.tip

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
        verify: bool = True,
    ) -> Tuple[bool, Optional[List[float]]]:
        """Solve IK and, by default, verify the achieved Cartesian pose.

        ikpy returns a best-effort local minimum for many unreachable or
        orientation-infeasible targets.  Without the verification gate a
        caller would drive to that local minimum and never signal
        ``motion_done``.  ``verify=False`` is only for callers that
        deliberately want the raw numerical result.
        """
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

            solution = [float(v) for v in joint_solution]
            if verify and not self._solution_matches(
                    solution, position_mm, orientation_deg):
                return False, None
            return True, solution

        except Exception as exc:
            print(f"[tms-robot-sim] IK solve failed: {exc}")
            return False, None

    @staticmethod
    def _branch_signs(shoulder: str, elbow: str, wrist: str = "normal"):
        shoulder = str(shoulder).strip().lower()
        elbow = str(elbow).strip().lower()
        if shoulder in ("left", "l", "+", "plus", "positive"):
            s = 1
        elif shoulder in ("right", "r", "-", "minus", "negative"):
            s = -1
        else:
            raise ValueError(f"Unknown shoulder branch: {shoulder!r}")
        if elbow in ("up", "u", "+", "plus", "positive"):
            e = 1
        elif elbow in ("down", "d", "-", "minus", "negative"):
            e = -1
        else:
            raise ValueError(f"Unknown elbow branch: {elbow!r}")
        wrist = str(wrist).strip().lower()
        if wrist in ("normal", "n", "+", "plus", "positive"):
            w = 1
        elif wrist in ("flipped", "flip", "f", "-", "minus", "negative"):
            w = -1
        else:
            raise ValueError(f"Unknown wrist branch: {wrist!r}")
        return s, e, w

    @staticmethod
    def _canonical_angle(angle: float) -> float:
        """Represent a periodic joint angle in [-pi, pi]."""
        return (float(angle) + math.pi) % (2.0 * math.pi) - math.pi

    def canonical_solution(self, solution: List[float]) -> List[float]:
        """Normalise the active periodic joints without changing the pose.

        The URDF allows some joints to turn through +/-2*pi.  ikpy then
        returns the same physical solution as, for example, +6.20 rad or
        -0.08 rad.  The branch buttons must compare the physical sign, not
        the arbitrary 2*pi representation.
        """
        result = [float(value) for value in solution]
        for index in self.active_indices:
            result[index] = self._canonical_angle(result[index])
        return result

    def _solution_matches(
        self,
        solution: List[float],
        position_mm: List[float],
        orientation_deg: List[float],
        position_tolerance_mm: float = 0.5,
        orientation_tolerance_deg: float = 0.5,
    ) -> bool:
        """Whether a joint solution reaches the requested Cartesian pose.

        The tolerances match the branch presets: a solution that is only a
        local minimum must not be reported as reaching the target.
        """
        candidate = self.canonical_solution(solution)
        achieved_pos, achieved_ori = self.forward(candidate)
        pos_err = np.linalg.norm(
            np.asarray(achieved_pos, dtype=float)
            - np.asarray(position_mm, dtype=float))
        ori_err = Rotation.from_euler(
            "xyz", achieved_ori, degrees=True).inv() * Rotation.from_euler(
                "xyz", orientation_deg, degrees=True)
        return (pos_err <= position_tolerance_mm
                and np.degrees(ori_err.magnitude()) <= orientation_tolerance_deg)

    def branch_of(self, solution: List[float]):
        """``('left'/'right', 'up'/'down')`` for a full ikpy solution."""
        solution = self.canonical_solution(solution)
        sh = solution[self.active_indices[0]]
        el = solution[self.active_indices[2]]
        wr = solution[self.active_indices[4]] if len(self.active_indices) > 4 else 0.0
        return ("left" if sh > 0 else "right",
                "up" if el > 0 else "down",
                "normal" if wr >= 0 else "flipped")

    def solve_branch(
        self,
        position_mm: List[float],
        orientation_deg: List[float],
        shoulder: str = "left",
        elbow: str = "up",
        wrist: str = "normal",
        attempts: int = 30,
        initial_position: Optional[List[float]] = None,
        seed: Optional[int] = None,
    ) -> Tuple[bool, Optional[List[float]]]:
        """Solve the IK for a requested shoulder/elbow branch.

        The base-pan sign selects ``left`` (+J1) or ``right`` (-J1); the
        elbow sign selects ``up`` (+J3) or ``down`` (-J3).  The solver seeds
        the chain in the requested quadrant and rejects solutions that land
        in another branch.  This is the branch selector used by the
        collision-test start-pose presets.
        """
        if len(self.active_indices) < 3:
            return False, None
        sh_sign, el_sign, wr_sign = self._branch_signs(shoulder, elbow, wrist)
        sh_idx, el_idx = self.active_indices[0], self.active_indices[2]
        wr_idx = self.active_indices[4] if len(self.active_indices) > 4 else None
        rng = random.Random(0 if seed is None else seed)

        def _matches(solution):
            candidate = self.canonical_solution(solution)
            if not ((candidate[sh_idx] > 0) == (sh_sign > 0)
                    and (candidate[el_idx] > 0) == (el_sign > 0)):
                return False
            if (wr_idx is not None
                    and (candidate[wr_idx] >= 0) != (wr_sign > 0)):
                return False
            # ikpy can return a local minimum without raising.  A branch
            # preset must actually reach the requested Cartesian pose.
            return self._solution_matches(
                candidate, position_mm, orientation_deg)

        if initial_position is not None:
            # Holding the current pose must not send the arm through a
            # different IK solution just because one exists.
            initial = self.canonical_solution(initial_position)
            if _matches(initial):
                return True, initial
            ok, solution = self.solve(
                position_mm, orientation_deg, initial, verify=False)
            if ok and solution is not None and _matches(solution):
                return True, self.canonical_solution(solution)

        base = ([0.0] * len(self.chain.links)
                if initial_position is None else list(initial_position))
        for _ in range(max(1, attempts)):
            seed_position = list(base)
            seed_position[sh_idx] = sh_sign * rng.uniform(0.8, 2.8)
            seed_position[el_idx] = el_sign * rng.uniform(1.0, 2.6)
            if wr_idx is not None:
                seed_position[wr_idx] = wr_sign * rng.uniform(0.8, 2.6)
            for idx in self.active_indices:
                if idx not in (sh_idx, el_idx, wr_idx):
                    seed_position[idx] += rng.uniform(-0.5, 0.5)
            ok, solution = self.solve(position_mm, orientation_deg,
                                      seed_position, verify=False)
            if ok and solution is not None and _matches(solution):
                return True, self.canonical_solution(solution)
        return False, None

    def solve_with_config(
        self,
        position_mm: List[float],
        orientation_deg: List[float],
        initial_position: Optional[List[float]] = None,
        elbow_up: bool = True,
        max_retries: int = 10,
        seed: Optional[int] = None,
    ) -> Tuple[bool, Optional[List[float]]]:
        """
        Solve IK with configuration preference (elbow up/down).

        Args:
            position_mm: Target position in mm
            orientation_deg: Target orientation in degrees
            initial_position: Initial joint positions (padded with inactive links)
            elbow_up: True for elbow up (joint_3 positive), False for elbow down
            max_retries: Maximum number of retries with different initial positions
            seed: Retry seed.  Defaults to 0 so repeated scans are deterministic.

        Returns:
            (success, joint_solution) - same as solve()
        """
        # The elbow is the third movable joint; its index in the full ikpy
        # solution depends on the fixed links in the robot's URDF.
        if len(self.active_indices) < 3:
            return False, None
        elbow_idx = self.active_indices[2]
        # Never draw retries from the process-global random state: the same
        # target and initial pose must produce the same path every scan.
        rng = random.Random(0 if seed is None else seed)
        fallback = None

        # First try with the provided initial position.  Verify below, so the
        # raw solver call does not duplicate the forward-kinematics check.
        success, solution = self.solve(
            position_mm, orientation_deg, initial_position, verify=False)

        if success and solution is not None:
            candidate = self.canonical_solution(solution)
            if self._solution_matches(candidate, position_mm, orientation_deg):
                fallback = candidate
                if (candidate[elbow_idx] > 0) == elbow_up:
                    return True, candidate

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
                new_initial[elbow_idx] = rng.uniform(1.0, 2.5)
            else:
                new_initial[elbow_idx] = rng.uniform(-2.5, -1.0)

            # Also add some randomness to other active joints to explore
            # different configurations.
            for i in self.active_indices:
                if i != elbow_idx:
                    new_initial[i] += rng.uniform(-0.5, 0.5)

            try:
                joint_solution = self.chain.inverse_kinematics_frame(
                    target=target_frame,
                    initial_position=new_initial,
                    orientation_mode="all",
                )
                if joint_solution is None:
                    continue
                candidate = self.canonical_solution(
                    [float(v) for v in joint_solution])
                if not self._solution_matches(
                        candidate, position_mm, orientation_deg):
                    continue
                if fallback is None:
                    fallback = candidate
                if (candidate[elbow_idx] > 0) == elbow_up:
                    print(f"[IK] Found elbow {'up' if elbow_up else 'down'} solution on retry {retry + 1}")
                    return True, candidate

            except Exception:
                continue

        # If we found a verified pose but not the requested elbow, prefer it.
        if fallback is not None:
            print(f"[IK] Warning: Could not find elbow {'up' if elbow_up else 'down'} solution after {max_retries} retries, using best available")
            return True, fallback

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