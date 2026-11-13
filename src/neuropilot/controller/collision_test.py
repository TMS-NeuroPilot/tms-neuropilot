"""Pre-flight collision test for a real cobot cell.

The experiment controller normally never moves a real robot.  This module
builds a *local* MuJoCo copy of the selected robot and the subject head so
the operator can find a subject position, robot base and start configuration
that survive the planned coil placements before touching the hardware.

It deliberately skips the mapping state machine: no stimulator, no EMG, no
MEPs, no analysis.  The scan only does IK, joint interpolation and collision
checks.  It is a planning aid, not a safety certification: the real robot's
controller still has the final say.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.spatial.transform import Rotation

from ..sim_robot import config as sim_config
from ..sim_robot.ik_solver import IKPySolver
from ..sim_robot.mujoco_world import MuJoCoWorld
from ..sim_robot.robots import get as get_robot
from ..sim_robot.utils.transforms import (
    matrix_to_pose,
    m_to_mm,
    pipeline_target_to_mujoco_world,
    pose_to_matrix,
)

# Collision thresholds mirror the simulator's safety defaults.  The scan
# stops on a true collision (penetration/contact) and reports proximity as a
# warning, so a near miss is visible before it becomes a hardware problem.
NEAR_MISS_M = 0.010
PENETRATION_M = -0.004
SCAN_STEPS = 30


class CollisionTestSession:
    """Local robot/head world used by the Collision test tab."""

    def __init__(self, head_stl: Optional[str] = None,
                 scene_name: str = "_collision_scene.xml"):
        self.spec = get_robot(sim_config.ROBOT)
        self.head_stl = head_stl
        self.scene_name = scene_name
        self.world: Optional[MuJoCoWorld] = None
        self.ik: Optional[IKPySolver] = None

        self.head_pose = (list(sim_config.HEAD_POSITION),
                          list(sim_config.HEAD_ORIENTATION))
        self.base_pose = (list(sim_config.ROBOT_BASE_POSITION),
                          list(sim_config.ROBOT_BASE_ORIENTATION))
        self.start_joints: List[float] = [0.0] * 6
        self.branch = ("left", "up")

        self._scan_poses: List[Tuple[List[float], List[float]]] = []
        self._scan_results: List[dict] = []
        self._scan_index = 0
        self._scan_path: List[List[float]] = []
        self._scan_path_i = 0
        self._scan_active = False
        self._scan_message = ""
        self._scan_base_targets: List[Tuple[List[float], List[float]]] = []

    # ── lifecycle ────────────────────────────────────────────────────
    @property
    def ready(self) -> bool:
        return self.world is not None and self.ik is not None

    def ensure_ready(self) -> None:
        if self.ready:
            return
        self.world = MuJoCoWorld(
            use_gui=False,
            end_effector_site_name=self.spec.ee_site,
            head_mesh_stl=self.head_stl,
            scene_name=self.scene_name,
            head_pose=self.head_pose,
            base_pose=self.base_pose,
        )
        self.world.connect()
        self.ik = IKPySolver(
            self.spec.urdf,
            active_links_mask=list(self.spec.ik_active_links),
            base_elements=list(self.spec.ik_base_elements),
        )
        self.reset_to_start()

    def dispose(self) -> None:
        self.stop_scan("closed")
        if self.world is not None:
            self.world.disconnect()
            self.world = None
        self.ik = None

    # ── poses ────────────────────────────────────────────────────────
    def set_head_pose(self, position_m: Sequence[float],
                      orientation_deg: Sequence[float]) -> None:
        self.head_pose = (list(position_m), list(orientation_deg))
        self._require_ready().set_scene_poses(head_pose=self.head_pose)

    def set_base_pose(self, position_m: Sequence[float],
                      orientation_deg: Sequence[float]) -> None:
        self.base_pose = (list(position_m), list(orientation_deg))
        self._require_ready().set_scene_poses(base_pose=self.base_pose)

    def current_end_effector(self) -> Tuple[List[float], List[float]]:
        """Current coil-site pose in ``(mm, deg)``."""
        pos_m, ori_deg = self._require_ready().get_end_effector_pose()
        return m_to_mm(pos_m), list(ori_deg)

    def home_pose(self) -> Tuple[List[float], List[float]]:
        """A safe-ish Cartesian start above the current head position."""
        head = np.asarray(self.head_pose[0], dtype=float)
        home_m = head + np.array([0.0, 0.0, 0.45])
        _, current_ori = self.current_end_effector()
        return m_to_mm(home_m.tolist()), current_ori

    def current_joints(self) -> List[float]:
        return list(self._require_ready().get_joint_positions())

    def set_current_joints(self, joints: Sequence[float]) -> None:
        self._require_ready().reset_joint_positions(list(joints))

    # ── IK / jogging ─────────────────────────────────────────────────
    def _full_solution(self, active: Sequence[float]) -> List[float]:
        solution = [0.0] * len(self.ik.chain.links)
        for idx, value in zip(self.ik.active_indices, active):
            solution[idx] = float(value)
        return solution

    def branch_of_active(self, active: Sequence[float]) -> Tuple[str, str]:
        return ("left" if active[0] > 0 else "right",
                "up" if active[2] > 0 else "down")

    def set_start_from_current(self) -> Tuple[List[float], Tuple[str, str]]:
        self.start_joints = self.current_joints()
        self.branch = self.branch_of_active(self.start_joints)
        return list(self.start_joints), self.branch

    def reset_to_start(self) -> None:
        self._require_ready().reset_joint_positions(self.start_joints)

    def world_to_base_pose(self, position_mm: Sequence[float],
                           orientation_deg: Sequence[float]
                           ) -> Tuple[List[float], List[float]]:
        """Express a world-frame coil pose in the robot base frame.

        The URDF/ikpy chain starts at the robot base, while the jog pad and
        the placement conversion work in the MuJoCo world frame.  Without this
        inverse base transform, moving the robot base would shift the real
        tool away from the requested world point.
        """
        base_mm = [v * 1000.0 for v in self.base_pose[0]]
        world = pose_to_matrix(list(position_mm), list(orientation_deg))
        body = pose_to_matrix(base_mm, list(self.base_pose[1]))
        xml_pose = getattr(self.world, "base_xml_pose", None)
        if xml_pose is not None:
            # The MJCF body may include a fixed frame offset that the URDF
            # chain carries as a fixed joint instead.  Divide it out so the
            # target is expressed in the chain root, not the body frame.
            xml_mm = [float(v) * 1000.0 for v in xml_pose[0]]
            xml = pose_to_matrix(xml_mm, list(xml_pose[1]))
            root = body @ np.linalg.inv(xml)
        else:
            root = body
        local = np.linalg.inv(root) @ world
        return matrix_to_pose(local)

    def move_to(self, position_mm: Sequence[float],
                orientation_deg: Sequence[float],
                shoulder: Optional[str] = None,
                elbow: Optional[str] = None) -> bool:
        """Solve IK for a world-frame coil pose and move the local model."""
        if not self.ready:
            self.ensure_ready()
        shoulder = shoulder if shoulder is not None else self.branch[0]
        elbow = elbow if elbow is not None else self.branch[1]
        base_pos, base_ori = self.world_to_base_pose(
            position_mm, orientation_deg)
        active = self.current_joints()
        ok, solution = self.ik.solve_branch(
            base_pos, base_ori,
            shoulder=shoulder, elbow=elbow,
            initial_position=self._full_solution(active),
        )
        if not ok or solution is None:
            return False
        target = [solution[i] for i in self.ik.active_indices]
        self.world.reset_joint_positions(target)
        self.branch = (shoulder, elbow)
        return True

    def jog(self, dx_mm: float = 0.0, dy_mm: float = 0.0,
            dz_mm: float = 0.0, drx_deg: float = 0.0,
            dry_deg: float = 0.0, drz_deg: float = 0.0) -> bool:
        """Move the coil site in world XYZ, rotate about the tool axes."""
        pos_mm, ori_deg = self.current_end_effector()
        new_pos = [pos_mm[0] + dx_mm, pos_mm[1] + dy_mm,
                   pos_mm[2] + dz_mm]
        current_r = Rotation.from_euler("xyz", ori_deg, degrees=True)
        delta_r = Rotation.from_euler(
            "xyz", [drx_deg, dry_deg, drz_deg], degrees=True)
        new_ori = (current_r * delta_r).as_euler(
            "xyz", degrees=True).tolist()
        return self.move_to(new_pos, new_ori)

    # ── collision state ─────────────────────────────────────────────
    def collision_state(self) -> Dict[str, object]:
        """Current robot/head and self-collision state.

        ``collision`` is true on contact or penetration; ``warning`` is true
        inside the 10 mm proximity band.  Distances are millimetres.
        """
        world = self._require_ready()
        distance = world.get_robot_head_closest_distance(
            distance_threshold=0.02)
        distance_mm = None if distance is None else distance * 1000.0
        self_contacts = world.get_self_collision_contacts()
        head_contacts = world.get_robot_head_contacts()
        collision = bool(self_contacts) or bool(head_contacts) or (
            distance is not None and distance <= PENETRATION_M)
        warning = (distance is not None and
                   distance <= NEAR_MISS_M and not collision)
        return {
            "collision": collision,
            "warning": warning,
            "self_collision": bool(self_contacts),
            "head_contact": bool(head_contacts),
            "distance_mm": distance_mm,
        }

    # ── placement scan ───────────────────────────────────────────────
    @property
    def scan_active(self) -> bool:
        return self._scan_active

    @property
    def scan_results(self) -> List[dict]:
        return list(self._scan_results)

    @property
    def scan_message(self) -> str:
        return self._scan_message

    def start_scan(self, placements: Sequence[Tuple[Sequence[float],
                                                    Sequence[float]]],
                   shoulder: Optional[str] = None,
                   elbow: Optional[str] = None) -> None:
        """Run through SimNIBS placements, stopping at the first collision."""
        if not self.ready:
            self.ensure_ready()
        shoulder = shoulder if shoulder is not None else self.branch[0]
        elbow = elbow if elbow is not None else self.branch[1]
        self.branch = (shoulder, elbow)
        self._scan_base_targets = []
        for pos_mm, ori_deg in placements:
            world_pos, world_ori = pipeline_target_to_mujoco_world(
                list(pos_mm), list(ori_deg),
                self.head_pose[0], self.head_pose[1])
            self._scan_base_targets.append(self.world_to_base_pose(
                m_to_mm(world_pos), world_ori))

        self._scan_results = []
        self._scan_index = 0
        self._scan_path = []
        self._scan_path_i = 0
        self._scan_active = True
        self._scan_message = "starting"
        self.reset_to_start()
        self._prepare_next()

    def stop_scan(self, message: str = "stopped") -> None:
        self._scan_active = False
        self._scan_path = []
        self._scan_path_i = 0
        self._scan_message = message

    def _prepare_next(self) -> None:
        if not self._scan_active:
            return
        if self._scan_index >= len(self._scan_base_targets):
            self._scan_active = False
            self._scan_message = "complete"
            return
        target_pos, target_ori = self._scan_base_targets[self._scan_index]
        active = self.current_joints()
        ok, solution = self.ik.solve_branch(
            target_pos, target_ori,
            shoulder=self.branch[0], elbow=self.branch[1],
            initial_position=self._full_solution(active),
        )
        if not ok or solution is None:
            self._record_result(False, "IK failed", collision=False)
            self.stop_scan(f"IK failed at placement {self._scan_index}")
            return
        target = [solution[i] for i in self.ik.active_indices]
        current = self.current_joints()
        self._scan_path = self._interpolate(current, target)
        self._scan_path_i = 0
        self._scan_message = f"placement {self._scan_index + 1}/" \
                             f"{len(self._scan_base_targets)}"

    @staticmethod
    def _interpolate(start: Sequence[float], end: Sequence[float],
                     steps: int = SCAN_STEPS) -> List[List[float]]:
        start = np.asarray(start, dtype=float)
        end = np.asarray(end, dtype=float)
        return [(start + (end - start) * i / max(1, steps)).tolist()
                for i in range(1, steps + 1)]

    def tick(self) -> Dict[str, object]:
        """Advance one visual waypoint.  Call from a GUI timer."""
        if not self._scan_active:
            return self.scan_status()
        if not self._scan_path:
            self._prepare_next()
            return self.scan_status()

        joints = self._scan_path[self._scan_path_i]
        self._require_ready().reset_joint_positions(joints)
        state = self.collision_state()
        if state["collision"]:
            self._record_result(False, "collision", collision=True,
                                detail=state)
            self.stop_scan(f"collision at placement {self._scan_index}")
            return self.scan_status()

        self._scan_path_i += 1
        if self._scan_path_i >= len(self._scan_path):
            self._record_result(True, "ok", collision=False, detail=state)
            self._scan_index += 1
            self._scan_path = []
            self._scan_path_i = 0
            self._prepare_next()
        return self.scan_status()

    def _record_result(self, ok: bool, message: str, collision: bool,
                       detail=None) -> None:
        self._scan_results.append({
            "index": self._scan_index,
            "ok": bool(ok),
            "collision": bool(collision),
            "message": message,
            "detail": detail or {},
        })

    def scan_status(self) -> Dict[str, object]:
        return {
            "active": self._scan_active,
            "index": self._scan_index,
            "total": len(self._scan_base_targets),
            "message": self._scan_message,
            "results": list(self._scan_results),
            "collision": self.collision_state() if self.ready else None,
        }

    # ── helpers ──────────────────────────────────────────────────────
    def _require_ready(self) -> MuJoCoWorld:
        if not self.ready:
            raise RuntimeError("Collision test is not initialised")
        return self.world
