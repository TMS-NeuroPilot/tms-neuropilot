import math
from enum import Enum
from typing import List, Optional, Tuple

import numpy as np

from . import config
from .state import RobotState
from .mujoco_world import MuJoCoWorld
from .ik_solver import IKPySolver
from .collision_checker import CollisionChecker
from .contact_model import ContactModel
from .utils.logging_utils import get_logger

log = get_logger(__name__)


class MotionState(Enum):
    IDLE              = 0
    PRE_VERIFY        = 1
    ASCENDING         = 2
    TRAVERSING        = 3
    DESCENDING        = 4
    PRE_VERIFY_DIRECT = 5
    DIRECT_MOVING     = 6
    CONVERGING        = 7
    COLLISION_HALT    = 8
    PRESS             = 9


class MotionPlanner:
    """
    State-machine motion planner with target retract-and-approach support.

    The first target from the start pose uses the absolute safe height.
    Later large target-to-target moves retract 20 mm along the negative tool
    normal, traverse, then approach. If the retract path is blocked, the
    safe-height path is the fallback.

    For small displacements / orientation-only changes:
      DIRECT_MOVING

    The manual move-away path is separate: it uses the absolute
    ``SAFE_HEIGHT_M`` so the coil leaves the head for end/emergency actions.

    Every path is pre-verified for head and self-collision before
    the first visual move.  If the target changes mid-motion the
    current path is aborted and a new one is computed from the
    current robot pose.
    """

    def __init__(
        self,
        state: RobotState,
        world: MuJoCoWorld,
        ik_solver: IKPySolver,
        collision_checker: CollisionChecker,
        contact_model: ContactModel,
    ):
        self.state             = state
        self.world             = world
        self.ik_solver         = ik_solver
        self.collision_checker = collision_checker
        self.contact_model     = contact_model

        self._motion_state = MotionState.IDLE
        self._path: List[List[float]] = []
        self._path_idx: int = 0
        self._retract_ascend: List[List[float]] = []
        self._retract_traverse: List[List[float]] = []
        self._retract_descend: List[List[float]] = []
        self._target_key: Optional[Tuple] = None
        self._target_active: List[float] = []
        self._press_depth: float = 0.0
        self._press_dir = None
        self._path_pos: float = 0.0
        self._last_applied_pos: Optional[float] = None

        self._move_away_active: bool = False
        self._move_away_path: List[List[float]] = []
        self._move_away_idx: int = 0
        # The first target from the start pose uses the absolute safe height.
        # Target-to-target moves use the shorter tool-normal retract.
        self._has_reached_target: bool = False

    # ────────────────────────────────────────────────────────────────
    # Public entry point  (called at 20 Hz from the controller)
    # ────────────────────────────────────────────────────────────────

    def step(self) -> None:
        """
        Called every control loop tick.  Dispatches to the current
        motion-state handler.
        """
        if not self.state.target.is_set():
            self._reset_motion()
            self._has_reached_target = False
            return

        new_key = self._build_target_key()
        if self._motion_state not in (MotionState.IDLE, MotionState.COLLISION_HALT):
            if new_key != self._target_key:
                log.info("Target changed mid-motion — recomputing path")
                self._reset_motion()

        if self._motion_state == MotionState.COLLISION_HALT:
            if new_key != self._target_key:
                self.state.set_collision_state(False)
                self.state.set_motion_done(False)
                self.state.set_tracking_valid(False)
                self._motion_state = MotionState.IDLE
                self._target_key = new_key

        if self._motion_state == MotionState.IDLE:
            self._start_new_motion()

        elif self._motion_state == MotionState.PRE_VERIFY:
            self._motion_state = MotionState.ASCENDING
            self._path = self._retract_ascend
            self._path_idx = 0
            self._first_path_pose()

        elif self._motion_state == MotionState.ASCENDING:
            self._advance_path()

        elif self._motion_state == MotionState.TRAVERSING:
            self._advance_path()

        elif self._motion_state == MotionState.DESCENDING:
            self._advance_path()

        elif self._motion_state == MotionState.PRE_VERIFY_DIRECT:
            self._motion_state = MotionState.DIRECT_MOVING
            self._path_idx = 0
            self._first_path_pose()

        elif self._motion_state == MotionState.DIRECT_MOVING:
            self._advance_path()

        elif self._motion_state == MotionState.CONVERGING:
            self._converge()

        elif self._motion_state == MotionState.PRESS:
            self._press_step()

    # ────────────────────────────────────────────────────────────────
    # Internal helpers
    # ────────────────────────────────────────────────────────────────

    def _build_target_key(self) -> Tuple:
        return (
            tuple(self.state.target.position),
            tuple(self.state.target.orientation),
        )

    def _reset_motion(self):
        self._motion_state = MotionState.IDLE
        self._path = []
        self._path_idx = 0
        self._retract_ascend = []
        self._retract_traverse = []
        self._retract_descend = []
        self._target_key = None
        self._target_active = []
        self._press_depth = 0.0
        self._press_dir = None
        self._path_pos = 0.0
        self._last_applied_pos = None
        self.state.set_motion_done(False)
        self.state.set_tracking_valid(False)

    def _build_padded_initial(self) -> Optional[List[float]]:
        """Place the current active joints at their ikpy chain indices."""
        if not self.state.joint_positions:
            return None
        padded = [0.0] * len(self.ik_solver.chain.links)
        for idx, value in zip(self.ik_solver.active_indices,
                              self.state.joint_positions):
            padded[idx] = value
        return padded

    def _active_joints(self, solution: List[float]) -> List[float]:
        """Extract the movable joints from a full ikpy solution."""
        return [float(solution[i]) for i in self.ik_solver.active_indices]

    # ────────────────────────────────────────────────────────────────
    # Path construction  (runs once per new target)
    # ────────────────────────────────────────────────────────────────

    def _start_new_motion(self):
        padded_initial = self._build_padded_initial()

        success, joint_solution = self.ik_solver.solve_with_config(
            position_mm=self.state.target.position,
            orientation_deg=self.state.target.orientation,
            initial_position=padded_initial,
            elbow_up=config.IK_ELBOW_UP,
            max_retries=config.IK_MAX_RETRIES,
        )
        if not success or joint_solution is None:
            self.state.set_ik_result(False)
            self.state.set_motion_done(False)
            self.state.set_tracking_valid(False)
            log.warning(f"IK solve failed for target: {self.state.target.label or 'unnamed'}")
            return

        target_active = self._active_joints(joint_solution)
        self._target_active = target_active
        current_active = list(self.state.joint_positions)

        from .utils.transforms import m_to_mm
        current_pos_m, current_ori_deg = self.world.get_end_effector_pose()
        current_pos_mm = m_to_mm(current_pos_m)
        target_pos_mm = self.state.target.position
        target_ori_deg = self.state.target.orientation

        path_ok = False

        if not current_active:
            self.state.set_ik_result(True, target_joints=joint_solution)
            self.world.reset_joint_positions(target_active)
            self.world.step(n_steps=4)
            self._sync_state()
            self._motion_state = MotionState.CONVERGING
            return

        displacement = math.sqrt(
            (current_pos_mm[0] - target_pos_mm[0])**2 +
            (current_pos_mm[1] - target_pos_mm[1])**2 +
            (current_pos_mm[2] - target_pos_mm[2])**2
        )

        if displacement > config.CRANE_DISPLACEMENT_THRESHOLD_MM:
            chosen = None
            label = ""
            if not self._has_reached_target:
                # First approach from the saved start pose keeps the old
                # absolute safe-height path; the tool normal is meaningless
                # while the coil is still high above the head.
                chosen = self._build_safe_height_path(
                    current_active, current_pos_mm, current_ori_deg,
                    target_active, target_pos_mm, target_ori_deg,
                    padded_initial,
                )
                label = "First-target safe-height path"
            else:
                # Retract away from the head using the negative tool normal,
                # then try the same safe-height path if that route is blocked.
                chosen = self._build_retract_path(
                    current_active, current_pos_mm, current_ori_deg,
                    target_active, target_pos_mm, target_ori_deg,
                    padded_initial,
                )
                label = "Retract path"
                if (chosen[0] is None
                        or not self._verify_path(chosen[0] + chosen[1] + chosen[2])):
                    fallback = self._build_safe_height_path(
                        current_active, current_pos_mm, current_ori_deg,
                        target_active, target_pos_mm, target_ori_deg,
                        padded_initial,
                    )
                    if (fallback[0] is not None
                            and self._verify_path(
                                fallback[0] + fallback[1] + fallback[2])):
                        chosen = fallback
                        label = "Safe-height fallback"
                    else:
                        chosen = (None, None, None)
            ascend, traverse, descend = chosen
            if ascend is not None and self._verify_path(ascend + traverse + descend):
                self._retract_ascend   = ascend
                self._retract_traverse = traverse
                self._retract_descend  = descend
                self._motion_state = MotionState.PRE_VERIFY
                path_ok = True
                n = len(ascend)
                log.info(f"{label} built ({3*n} poses) — pre-verified OK")
        else:
            path = self._interpolate_joints(current_active, target_active)
            if self._verify_path(path):
                self._path = path
                self._motion_state = MotionState.PRE_VERIFY_DIRECT
                path_ok = True
                log.info(f"Direct path built ({len(path)} poses) — pre-verified OK")

        if path_ok:
            self.state.set_collision_state(False)
            self.state.set_ik_result(True, target_joints=joint_solution)
            self._path_idx = 0
            self._target_key = self._build_target_key()
            return

        log.warning("Path rejected — all poses blocked by collision")
        self.state.set_collision_state(True)
        self.state.set_motion_done(False)
        self.state.set_tracking_valid(False)
        self._motion_state = MotionState.COLLISION_HALT

    def _build_safe_height_path(
        self,
        current_active: List[float],
        current_pos_mm: List[float],
        current_ori_deg: List[float],
        target_active: List[float],
        target_pos_mm: List[float],
        target_ori_deg: List[float],
        padded_initial: Optional[List[float]],
    ) -> Tuple[Optional[List[List[float]]], Optional[List[List[float]]], Optional[List[List[float]]]]:
        """Build the absolute safe-height crane path.

        Used for the first target from the start pose and as the fallback
        when the short tool-normal retract is blocked.
        """
        safe_z_mm = config.SAFE_HEIGHT_M * 1000.0
        above_curr_p = [current_pos_mm[0], current_pos_mm[1], safe_z_mm]
        above_tgt_p = [target_pos_mm[0], target_pos_mm[1], safe_z_mm]

        _, sol_curr = self.ik_solver.solve_with_config(
            above_curr_p, current_ori_deg,
            initial_position=padded_initial,
            elbow_up=config.IK_ELBOW_UP,
            max_retries=config.IK_MAX_RETRIES,
        )
        if sol_curr is None:
            return None, None, None

        _, sol_tgt = self.ik_solver.solve_with_config(
            above_tgt_p, target_ori_deg,
            initial_position=padded_initial,
            elbow_up=config.IK_ELBOW_UP,
            max_retries=config.IK_MAX_RETRIES,
        )
        if sol_tgt is None:
            return None, None, None

        above_curr_active = self._active_joints(sol_curr)
        above_tgt_active = self._active_joints(sol_tgt)
        ascend = self._interpolate_joints(current_active, above_curr_active)
        traverse = self._interpolate_joints(above_curr_active, above_tgt_active)
        descend = self._interpolate_joints(above_tgt_active, target_active)
        return ascend, traverse, descend

    def _build_retract_path(
        self,
        current_active: List[float],
        current_pos_mm: List[float],
        current_ori_deg: List[float],
        target_active: List[float],
        target_pos_mm: List[float],
        target_ori_deg: List[float],
        padded_initial: Optional[List[float]],
    ) -> Tuple[Optional[List[List[float]]], Optional[List[List[float]]], Optional[List[List[float]]]]:
        """
        Build three joint-space segments for a target transition:
          1.  RETRACT:  current → current - 20 mm along current tool +Z
          2.  TRAVERSE: retracted_current → retracted_target
          3.  APPROACH: retracted_target → target along target +Z
        Returns (retract, traverse, approach) or (None, None, None) if
        IK fails for an intermediate waypoint.

        The tool +Z axis points toward the head at the coil targets, so the
        away direction is the negative tool normal.  The retract is
        ``TARGET_RETRACT_M``, not the absolute ``SAFE_HEIGHT_M`` used by the
        manual move-away action.
        """
        from .utils.transforms import euler_deg_to_matrix

        retract_mm = config.TARGET_RETRACT_M * 1000.0
        current_z = euler_deg_to_matrix(current_ori_deg)[:, 2]
        target_z = euler_deg_to_matrix(target_ori_deg)[:, 2]
        retracted_curr_p = [
            current_pos_mm[i] - float(current_z[i]) * retract_mm
            for i in range(3)
        ]
        retracted_tgt_p = [
            target_pos_mm[i] - float(target_z[i]) * retract_mm
            for i in range(3)
        ]

        _, sol_curr = self.ik_solver.solve_with_config(
            retracted_curr_p, current_ori_deg,
            initial_position=padded_initial,
            elbow_up=config.IK_ELBOW_UP,
            max_retries=config.IK_MAX_RETRIES,
        )
        if sol_curr is None:
            return None, None, None

        _, sol_tgt = self.ik_solver.solve_with_config(
            retracted_tgt_p, target_ori_deg,
            initial_position=padded_initial,
            elbow_up=config.IK_ELBOW_UP,
            max_retries=config.IK_MAX_RETRIES,
        )
        if sol_tgt is None:
            return None, None, None

        retracted_curr_active = self._active_joints(sol_curr)
        retracted_tgt_active  = self._active_joints(sol_tgt)

        ascend   = self._interpolate_joints(current_active, retracted_curr_active)
        traverse = self._interpolate_joints(retracted_curr_active, retracted_tgt_active)
        descend  = self._interpolate_joints(retracted_tgt_active, target_active)
        return ascend, traverse, descend

    # ────────────────────────────────────────────────────────────────
    # Interpolation
    # ────────────────────────────────────────────────────────────────

    @staticmethod
    def _interpolate_joints(start: List[float], end: List[float]) -> List[List[float]]:
        """
        Linearly interpolate between two active-joint configurations.

        Returns N intermediate poses (one per PATH_INTERPOLATION_STEPS),
        excluding the start pose.
        """
        n = config.PATH_INTERPOLATION_STEPS
        return [
            [s + (e - s) * t / n for s, e in zip(start, end)]
            for t in range(1, n + 1)
        ]

    # ────────────────────────────────────────────────────────────────
    # Pre-verification  (dry-run all poses for collision)
    # ────────────────────────────────────────────────────────────────

    def _verify_path(self, path: List[List[float]]) -> bool:
        """
        Snap the MuJoCo model to each pose in *path* and check for
        head and self-collision.  Restores the original joints when
        done.
        Returns True if every pose is collision-free.
        """
        saved = list(self.world.get_joint_positions())
        for joints in path:
            self.world.reset_joint_positions(joints)
            if self.collision_checker.check():
                self.world.reset_joint_positions(saved)
                log.warning("Head collision at an intermediate pose — aborting")
                return False
            if self.collision_checker.check_self_collision():
                self.world.reset_joint_positions(saved)
                log.warning("Self-collision at an intermediate pose — aborting")
                return False
        self.world.reset_joint_positions(saved)
        return True

    # ────────────────────────────────────────────────────────────────
    # Execution helpers  (run every tick during motion)
    # ────────────────────────────────────────────────────────────────

    def _first_path_pose(self):
        """
        Snap to and step the first pose of the current segment.
        Called when entering a new segment (including the first).
        """
        if not self._path:
            return
        self._path_pos = 0.0
        self._last_applied_pos = 0.0
        joints = self._path[0]
        self.world.reset_joint_positions(joints)
        self.world.step(n_steps=2)
        self._sync_state()

    def _active_ratio(self) -> float:
        """The speed ratio for the current segment: the default speed drives
        the transfer (ascend/traverse), the tuning speed the final approach
        (descend/direct move) — mirroring the real robot."""
        if self._motion_state in (MotionState.ASCENDING, MotionState.TRAVERSING):
            return self.state.default_speed_ratio
        return self.state.tuning_speed_ratio

    def _advance_path(self):
        """
        Advance along the current segment's path with a fractional index —
        joint poses are interpolated between the path points, so the speed
        sliders scale the pace continuously instead of in whole-point jumps.
        Transitions to the next state when the segment is exhausted.
        """
        last = len(self._path) - 1
        if self._path_pos >= last:
            self._on_segment_done()
            return

        # Speed scaling: the baseline pace corresponds to SPEED_BASE_RATIO
        # on the GUI slider; lower ratios slow down, higher speed up.
        step = max(self._active_ratio() / config.SPEED_BASE_RATIO, 0.05)
        self._path_pos = min(self._path_pos + step, float(last))

        if self._last_applied_pos is not None and \
                abs(self._path_pos - self._last_applied_pos) < 1e-9:
            return  # no visible change this tick
        self._last_applied_pos = self._path_pos

        idx = int(self._path_pos)
        frac = self._path_pos - idx
        if idx >= last or frac <= 0.0:
            joints = self._path[idx]
        else:
            a = np.asarray(self._path[idx], dtype=float)
            b = np.asarray(self._path[idx + 1], dtype=float)
            joints = (a + (b - a) * frac).tolist()
        self.world.reset_joint_positions(joints)
        self.world.step(n_steps=2)
        self._sync_state()

    def _on_segment_done(self):
        """
        Called when one segment finishes.  Advances to the next
        segment or transitions to CONVERGING.
        """
        if self._motion_state == MotionState.ASCENDING:
            self._motion_state = MotionState.TRAVERSING
            self._path = self._retract_traverse
            self._path_idx = 0
            log.debug("ASCENDING done → TRAVERSING")
            self._first_path_pose()

        elif self._motion_state == MotionState.TRAVERSING:
            self._motion_state = MotionState.DESCENDING
            self._path = self._retract_descend
            self._path_idx = 0
            log.debug("TRAVERSING done → DESCENDING")
            self._first_path_pose()

        elif self._motion_state == MotionState.DESCENDING:
            log.debug("DESCENDING done → CONVERGING")
            self._motion_state = MotionState.CONVERGING
            self._converge()

        elif self._motion_state == MotionState.DIRECT_MOVING:
            log.debug("DIRECT_MOVING done → CONVERGING")
            self._motion_state = MotionState.CONVERGING
            self._converge()

    def _converge(self):
        """
        Settle at the target pose.  Snaps to target joints, zeros
        velocities to prevent oscillation, then steps physics.
        Once the pose error falls below threshold, signals motion_done
        and returns to IDLE.
        """
        self.world.reset_joint_positions(self._target_active)
        with self.world._data_lock:
            self.world.data.qvel[:] = 0.0
        self.world.step(n_steps=4)
        self._sync_state()
        pos_err, ori_err = self._compute_pose_error(
            self.state.current_position,
            self.state.current_orientation,
        )
        motion_done = pos_err < 4.0 and ori_err < 1.0
        self.state.set_motion_done(motion_done)
        self.state.set_tracking_valid(motion_done)
        if motion_done:
            self._has_reached_target = True
            # The coil origin (TCP) sits above the skin contact point (the
            # SimNIBS coil casing height), so reaching the target alone does
            # not produce contact. Press toward the head until the simulated
            # force feedback crosses the pipeline's threshold — the analogue
            # of the real robot's pressure PID.
            if config.PRESS_ENABLED and \
                    self.contact_model.compute_force_feedback() < config.PRESS_FORCE_THRESHOLD:
                self._motion_state = MotionState.PRESS
                self._press_depth = 0.0
                self._press_dir = None
                log.info(f"Target '{self.state.target.label}' reached — "
                         f"pressing toward the head for contact "
                         f"(pos_err={pos_err:.2f} mm, ori_err={ori_err:.2f} deg)")
            else:
                self._motion_state = MotionState.IDLE
                log.info(f"Target '{self.state.target.label}' reached — "
                         f"pos_err={pos_err:.2f} mm, ori_err={ori_err:.2f} deg, "
                         f"force={self.state.force_feedback:.3f}")
        else:
            log.debug(f"Converging — pos_err={pos_err:.2f} mm, ori_err={ori_err:.2f} deg")

    def _press_step(self):
        """Move the coil along its axis toward the head in small increments
        until the contact force exceeds the pipeline threshold."""
        import numpy as np
        from .utils.transforms import euler_deg_to_matrix

        self._press_depth += config.PRESS_STEP_MM
        if self._press_depth > config.PRESS_MAX_DEPTH_MM:
            log.warning("Press depth limit reached without contact -- "
                        "continuing without force feedback.")
            self._motion_state = MotionState.IDLE
            return

        # Press along the coil axis: -z of the target orientation points
        # from the coil origin toward the head.
        if self._press_dir is None:
            R = euler_deg_to_matrix(self.state.target.orientation)
            self._press_dir = [-c for c in R[:, 2]]
        position = [self.state.target.position[i] + self._press_dir[i] * self._press_depth
                    for i in range(3)]

        padded_initial = self._build_padded_initial()
        success, joint_solution = self.ik_solver.solve_with_config(
            position_mm=position,
            orientation_deg=self.state.target.orientation,
            initial_position=padded_initial,
            elbow_up=config.IK_ELBOW_UP,
            max_retries=config.IK_MAX_RETRIES,
        )
        if not success:
            log.debug(f"Press: IK failed at depth {self._press_depth:.1f} mm")
            return

        self.world.reset_joint_positions(self._active_joints(joint_solution))
        self.world.step(n_steps=4)
        self._sync_state()

        force = self.state.force_feedback
        if force >= config.PRESS_FORCE_THRESHOLD:
            log.info(f"Coil pressed onto the head at {self._press_depth:.1f} mm "
                     f"depth -- force {force:.2f}")
            self._motion_state = MotionState.IDLE

    # ────────────────────────────────────────────────────────────────
    # State synchronisation
    # ────────────────────────────────────────────────────────────────

    def _sync_state(self):
        """
        Read the current MuJoCo simulation state back into the shared
        state object.
        """
        self.state.set_joint_positions(self.world.get_joint_positions())
        try:
            achieved_pos_m, achieved_ori_deg = self.world.get_end_effector_pose()
        except RuntimeError:
            return
        from .utils.transforms import m_to_mm
        achieved_pos_mm = m_to_mm(achieved_pos_m)
        self.state.update_current_pose(achieved_pos_mm, achieved_ori_deg)
        force = self.contact_model.compute_force_feedback()
        self.state.set_force_feedback(force)

    def sync_state(self):
        """Public wrapper: sync the shared state from the world (used at
        startup so the first motion starts from the true initial pose)."""
        self._sync_state()

    # ────────────────────────────────────────────────────────────────
    # Pose-error computation
    # ────────────────────────────────────────────────────────────────

    def _compute_pose_error(
        self,
        achieved_pos_mm: list,
        achieved_ori_deg: list,
    ) -> Tuple[float, float]:
        from .utils.transforms import position_distance_mm, orientation_distance_deg
        pos_err = position_distance_mm(
            achieved_pos_mm,
            self.state.target.position,
        )
        ori_err = orientation_distance_deg(
            achieved_ori_deg,
            self.state.target.orientation,
        )
        return pos_err, ori_err

    def is_move_away_active(self) -> bool:
        return self._move_away_active

    def start_move_away(self) -> None:
        safe_z_mm = config.SAFE_HEIGHT_M * 1000
        current_pos_m, current_ori_deg = self.world.get_end_effector_pose()
        from .utils.transforms import m_to_mm
        current_pos_mm = m_to_mm(current_pos_m)

        if current_pos_mm[2] >= safe_z_mm:
            self.state.set_objective(0)
            self.state.set_tracking_enabled(False)
            self.state.set_motion_done(True)
            self.state.set_tracking_valid(False)
            self.state.set_force_feedback(0.0)
            self.state.last_status_text = "Already above safe height"
            return

        ascend_target_mm = [current_pos_mm[0], current_pos_mm[1], safe_z_mm]

        padded = self._build_padded_initial()
        success, sol = self.ik_solver.solve_with_config(
            ascend_target_mm, current_ori_deg,
            initial_position=padded,
            elbow_up=config.IK_ELBOW_UP,
            max_retries=config.IK_MAX_RETRIES,
        )
        if not success or sol is None:
            log.warning("Move-away IK failed")
            self.state.set_objective(0)
            return

        ascend_active = self._active_joints(sol)
        current_active = list(self.state.joint_positions)
        if not current_active:
            log.warning("Move-away skipped — no current joint positions")
            self.state.set_objective(0)
            return
        self._move_away_path = self._interpolate_joints(current_active, ascend_active)
        self._move_away_idx = 0
        self._move_away_active = True
        log.info("Move-away started — ascending to safe height")

    def step_move_away(self) -> None:
        if self._move_away_idx >= len(self._move_away_path):
            self.state.set_objective(0)
            self.state.set_tracking_enabled(False)
            self.state.set_motion_done(True)
            self.state.set_tracking_valid(False)
            self.state.set_force_feedback(0.0)
            self.state.last_status_text = "Moved away from head"
            self._move_away_active = False
            self._move_away_path = []
            log.info("Move-away complete")
            return

        joints = self._move_away_path[self._move_away_idx]
        self.world.reset_joint_positions(joints)
        self.world.step(n_steps=2)
        self._sync_state()
        self._move_away_idx += 1
