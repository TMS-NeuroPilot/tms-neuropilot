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
# Consecutive arm meshes overlap slightly at some wrist configurations even
# when the rendered links look clear. Ignore sub-2 mm self-mesh overlaps;
# deeper penetration still stops the scan.
SELF_PENETRATION_M = -0.002
SCAN_STEPS = 30


def _canonical_angle(value: float) -> float:
    """Represent a periodic joint angle in [-pi, pi]."""
    return (float(value) + np.pi) % (2.0 * np.pi) - np.pi


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
        self.branch = ("left", "up", "normal")

        self._scan_poses: List[Tuple[List[float], List[float]]] = []
        self._scan_results: List[dict] = []
        self._scan_index = 0
        self._scan_completed = 0
        self._scan_path: List[List[float]] = []
        self._scan_path_i = 0
        self._scan_active = False
        self._scan_message = ""
        self._scan_base_targets: List[Tuple[List[float], List[float]]] = []
        self._scan_target_ids: List[int] = []
        self._scan_order_indices: List[int] = []
        self._scan_reps: List[int] = []
        self._scan_total_targets = 0
        self._scan_repetitions = 1
        self._scan_branch_changes: List[dict] = []

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
        self._require_ready().reset_joint_positions(
            [_canonical_angle(value) for value in joints])

    # ── IK / jogging ─────────────────────────────────────────────────
    def _full_solution(self, active: Sequence[float]) -> List[float]:
        solution = [0.0] * len(self.ik.chain.links)
        for idx, value in zip(self.ik.active_indices, active):
            solution[idx] = float(value)
        return solution

    def branch_of_active(self, active: Sequence[float]) -> Tuple[str, str, str]:
        active = [_canonical_angle(value) for value in active]
        return ("left" if active[0] > 0 else "right",
                "up" if active[2] > 0 else "down",
                "normal" if active[4] >= 0 else "flipped")

    def set_start_from_current(self) -> Tuple[List[float], Tuple[str, str]]:
        self.start_joints = [_canonical_angle(value)
                             for value in self.current_joints()]
        self.branch = self.branch_of_active(self.start_joints)
        return list(self.start_joints), self.branch

    def reset_to_start(self) -> None:
        self._require_ready().reset_joint_positions(
            [_canonical_angle(value) for value in self.start_joints])

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
                elbow: Optional[str] = None,
                wrist: Optional[str] = None,
                fallback: bool = False) -> bool:
        """Solve IK for a world-frame coil pose and move the local model.

        ``fallback`` is for jogging: if the stored branch has no solution at
        a singular pose, the free simulation IK may still move the arm. The
        branch-selection presets leave it off so they remain strict.
        """
        if not self.ready:
            self.ensure_ready()
        shoulder = shoulder if shoulder is not None else self.branch[0]
        elbow = elbow if elbow is not None else self.branch[1]
        wrist = wrist if wrist is not None else self.branch[2]
        base_pos, base_ori = self.world_to_base_pose(
            position_mm, orientation_deg)
        active = self.current_joints()
        ok, solution = self.ik.solve_branch(
            base_pos, base_ori,
            shoulder=shoulder, elbow=elbow, wrist=wrist,
            initial_position=self._full_solution(active),
        )
        if (not ok or solution is None) and fallback:
            ok, solution = self.ik.solve_with_config(
                base_pos, base_ori,
                initial_position=self._full_solution(active),
                elbow_up=sim_config.IK_ELBOW_UP,
                max_retries=sim_config.IK_MAX_RETRIES,
            )
        if not ok or solution is None:
            return False
        target = [_canonical_angle(solution[i])
                  for i in self.ik.active_indices]
        self.world.reset_joint_positions(target)
        self.branch = self.branch_of_active(target)
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
        return self.move_to(new_pos, new_ori, fallback=True)

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
        all_self = world.get_self_collision_contacts()
        self_contacts = [contact for contact in all_self
                         if contact.get("dist", 0.0) <= SELF_PENETRATION_M]
        self_contact_mm = (min(float(contact["dist"]) for contact in all_self)
                           * 1000.0 if all_self else None)
        head_contacts = world.get_robot_head_contacts()
        collision = bool(self_contacts) or bool(head_contacts) or (
            distance is not None and distance <= PENETRATION_M)
        warning = (distance is not None and
                   distance <= NEAR_MISS_M and not collision)
        return {
            "collision": collision,
            "warning": warning,
            "self_collision": bool(self_contacts),
            "self_contact_mm": self_contact_mm,
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
                   elbow: Optional[str] = None,
                   wrist: Optional[str] = None,
                   target_ids: Optional[Sequence[int]] = None,
                   repetitions: int = 1) -> None:
        """Run through the experiment's target order, stopping at a collision.

        ``target_ids`` mirrors the Control page's target-order file.  Each
        target is repeated ``repetitions`` times, in the same order that the
        experiment performs its pulses.  Without an order file the placements
        are scanned in file order.
        """
        if not self.ready:
            self.ensure_ready()
        shoulder = shoulder if shoulder is not None else self.branch[0]
        elbow = elbow if elbow is not None else self.branch[1]
        wrist = wrist if wrist is not None else self.branch[2]
        self.branch = (shoulder, elbow, wrist)
        self._scan_total_targets = len(placements)
        self._scan_repetitions = max(1, int(repetitions))
        if target_ids is None:
            order = list(range(len(placements)))
        else:
            order = [int(value) for value in target_ids]
        self._scan_base_targets = []
        self._scan_target_ids = []
        self._scan_order_indices = []
        self._scan_reps = []
        for order_index, target_id in enumerate(order):
            if not 0 <= target_id < len(placements):
                raise ValueError(
                    f"target order references placement {target_id}, "
                    f"but only {len(placements)} placements exist")
            pos_mm, ori_deg = placements[target_id]
            world_pos, world_ori = pipeline_target_to_mujoco_world(
                list(pos_mm), list(ori_deg),
                self.head_pose[0], self.head_pose[1])
            base_pose = self.world_to_base_pose(
                m_to_mm(world_pos), world_ori)
            for rep in range(1, self._scan_repetitions + 1):
                self._scan_base_targets.append(base_pose)
                self._scan_target_ids.append(target_id)
                self._scan_order_indices.append(order_index)
                self._scan_reps.append(rep)

        self._scan_results = []
        self._scan_index = 0
        self._scan_completed = 0
        self._scan_path = []
        self._scan_path_i = 0
        self._scan_active = True
        self._scan_message = "starting"
        self._scan_branch_changes = []
        self.reset_to_start()
        self._prepare_next()

    def stop_scan(self, message: str = "stopped") -> None:
        self._scan_active = False
        self._scan_path = []
        self._scan_path_i = 0
        self._scan_message = message

    def _scan_entry(self, index: int) -> dict:
        """Metadata for one pulse in the scan sequence."""
        target_id = (self._scan_target_ids[index]
                     if index < len(self._scan_target_ids) else index)
        order_index = (self._scan_order_indices[index]
                       if index < len(self._scan_order_indices) else index)
        rep = (self._scan_reps[index]
               if index < len(self._scan_reps) else 1)
        return {
            "target_id": int(target_id),
            "order_index": int(order_index),
            "rep": int(rep),
        }

    def _prepare_next(self) -> None:
        if not self._scan_active:
            return
        total = len(self._scan_base_targets)
        if self._scan_index >= total:
            self._scan_active = False
            self._scan_completed = total
            self._scan_message = "complete"
            return
        idx = self._scan_index
        entry = self._scan_entry(idx)
        target_pos, target_ori = self._scan_base_targets[idx]
        active = self.current_joints()
        initial = self._full_solution(active)
        selected = (self.branch[0], self.branch[1], self.branch[2])
        ok, solution = self.ik.solve_branch(
            target_pos, target_ori,
            shoulder=selected[0], elbow=selected[1], wrist=selected[2],
            initial_position=initial,
        )
        used = selected
        if not ok or solution is None:
            # The production sim planner does not lock shoulder/wrist; it
            # asks for the configured elbow preference and accepts another
            # solution if needed.  Retry with that solver before calling the
            # target unreachable, so this scan does not stop where the real
            # simulation would still move.
            ok, solution = self.ik.solve_with_config(
                target_pos, target_ori,
                initial_position=initial,
                elbow_up=sim_config.IK_ELBOW_UP,
                max_retries=sim_config.IK_MAX_RETRIES,
            )
            if ok and solution is not None:
                used_active = [solution[i] for i in self.ik.active_indices]
                used = self.branch_of_active(used_active)
                if used != selected:
                    self._scan_branch_changes.append({
                        "index": idx,
                        "target_id": entry["target_id"],
                        "order_index": entry["order_index"],
                        "rep": entry["rep"],
                        "selected": list(selected),
                        "used": list(used),
                    })
        if not ok or solution is None:
            self._record_result(
                False, "IK failed", collision=False,
                detail={"selected_branch": list(selected),
                        "target_id": entry["target_id"],
                        "completed": self._scan_completed})
            self.stop_scan("no IK solution")
            return
        target = [_canonical_angle(solution[i])
                  for i in self.ik.active_indices]
        current = self.current_joints()
        self._scan_path = self._interpolate(current, target)
        self._scan_path_i = 0
        note = " (IK branch changed)" if used != selected else ""
        self._scan_message = (
            f"pulse {entry['order_index']} · {entry['rep']}/"
            f"{self._scan_repetitions} · target {entry['target_id']}{note}")

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
            self.stop_scan("collision")
            return self.scan_status()

        self._scan_path_i += 1
        if self._scan_path_i >= len(self._scan_path):
            self._record_result(True, "ok", collision=False, detail=state)
            self._scan_completed = self._scan_index + 1
            self._scan_index += 1
            self._scan_path = []
            self._scan_path_i = 0
            total = len(self._scan_base_targets)
            if self._scan_index >= total:
                self._scan_active = False
                self._scan_message = "complete"
            else:
                # Do not prepare the next target in the same tick: the last
                # waypoint of this pulse must reach the view before the
                # status names the next pulse.
                next_entry = self._scan_entry(self._scan_index)
                self._scan_message = (
                    f"reached pulse {self._scan_completed - 1}; preparing "
                    f"pulse {next_entry['order_index']} · "
                    f"{next_entry['rep']}/{self._scan_repetitions} · "
                    f"target {next_entry['target_id']}")
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
        total = len(self._scan_base_targets)
        current = (self._scan_entry(self._scan_index)
                   if 0 <= self._scan_index < total else None)
        last = (self._scan_entry(self._scan_completed - 1)
                if self._scan_completed > 0 else None)
        return {
            "active": self._scan_active,
            "index": self._scan_index,
            "completed": self._scan_completed,
            "total": total,
            "total_targets": (self._scan_total_targets or total),
            "repetitions": self._scan_repetitions,
            "target_id": current["target_id"] if current else None,
            "order_index": current["order_index"] if current else None,
            "rep": current["rep"] if current else None,
            "last_target_id": last["target_id"] if last else None,
            "last_order_index": last["order_index"] if last else None,
            "last_rep": last["rep"] if last else None,
            "path_step": self._scan_path_i,
            "path_total": len(self._scan_path),
            "preparing": self._scan_active and not self._scan_path,
            "message": self._scan_message,
            "branch_changes": list(self._scan_branch_changes),
            "results": list(self._scan_results),
            "collision": self.collision_state() if self.ready else None,
        }

    # ── helpers ──────────────────────────────────────────────────────
    def _require_ready(self) -> MuJoCoWorld:
        if not self.ready:
            raise RuntimeError("Collision test is not initialised")
        return self.world
