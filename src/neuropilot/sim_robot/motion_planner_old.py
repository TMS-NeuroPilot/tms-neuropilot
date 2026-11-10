# tms-robot-sim/motion_planner.py

import math
from typing import Optional, Tuple

from . import config
from .state import RobotState
from .mujoco_world import MuJoCoWorld
from .ik_solver import IKPySolver
from .collision_checker import CollisionChecker
from .contact_model import ContactModel
from .utils.logging_utils import get_logger

log = get_logger(__name__)


class MotionPlanner:
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

    def step(self) -> None:
        """
        One motion planning step. Called every control loop tick.

        Flow:
          1. Solve IK for the current target
          2. Check collision before moving
          3. Apply joint positions to PyBullet
          4. Step the simulation
          5. Read back the achieved end-effector pose
          6. Update state with pose, force, and status flags
        """

        # ── 1. Solve IK ───────────────────────────────────────────────
        # Reconstruct padded initial position: [0, j1..j6, 0]
        if self.state.joint_positions:
            #initial_position = [0.0] + list(self.state.joint_positions) + [0.0]   # if the coil is not in the robot urdf file
            initial_position = [0.0] + list(self.state.joint_positions) + [0.0, 0.0] # if the coil is in the urdf file of the robot
        else:
            initial_position = None

        #success, joint_solution = self.ik_solver.solve(
        #    position_mm=self.state.target.position,
        #    orientation_deg=self.state.target.orientation,
        #    initial_position=initial_position,
        #)

        success, joint_solution = self.ik_solver.solve_with_config(
            position_mm=self.state.target.position,
            orientation_deg=self.state.target.orientation,
            initial_position=initial_position,
            elbow_up=config.IK_ELBOW_UP,
            max_retries=config.IK_MAX_RETRIES,
        )

        if not success or joint_solution is None:
            self.state.set_ik_result(False)
            self.state.set_motion_done(False)
            self.state.set_tracking_valid(False)
            log.warning("IK solve failed for target: "
                        f"{self.state.target.label or 'unnamed'}")
            return

        self.state.set_ik_result(True, target_joints=joint_solution)
        log.debug(f"IK solved for target '{self.state.target.label}'")

        # Strip padding: IK returns [0, j1, j2, j3, j4, j5, j6, 0]
        # PyBullet needs only [j1, j2, j3, j4, j5, j6]
        #active_joints = joint_solution[1:-1]  # if the coil is not in the robot urdf file
        active_joints = joint_solution[1:7]  # if the coil is in the urdf file of the robot

        # ── 2. Apply joints tentatively and check collision ───────────
        self.world.reset_joint_positions(active_joints)
        self.world.step(n_steps=1)

        collision = self.collision_checker.check()
        self_collision = self.collision_checker.check_self_collision()
        #self.state.set_collision_state(collision)
        self.state.set_collision_state(collision or self_collision)

        if collision or self_collision:
            log.warning("Collision detected — halting motion this step")
            self.state.set_motion_done(False)
            self.state.set_tracking_valid(False)
            return

        # ── 3. Drive joints with motor control ────────────────────────
        self.world.set_joint_motor_targets(active_joints)
        self.world.step(n_steps=4)   # a few more steps to settle. changed from 4 steps= (8ms) to 10 steps= (20ms) is a bad idea cuz it increase jittering

        # ── 4. Read back achieved pose ────────────────────────────────
        try:
            achieved_pos_m, achieved_ori_deg = self.world.get_end_effector_pose()
        except RuntimeError as exc:
            log.error(f"Could not read end-effector pose: {exc}")
            return

        # Convert m → mm to stay consistent with state and pipeline units
        from .utils.transforms import m_to_mm
        achieved_pos_mm = m_to_mm(achieved_pos_m)

        self.state.update_current_pose(achieved_pos_mm, achieved_ori_deg)
        self.state.set_joint_positions(self.world.get_joint_positions())

        # ── 5. Compute force feedback ─────────────────────────────────
        force = self.contact_model.compute_force_feedback()
        self.state.set_force_feedback(force)

        # ── 6. Evaluate pose error → decide if motion is done ─────────
        pos_err, ori_err = self._compute_pose_error(achieved_pos_mm, achieved_ori_deg)

        motion_done    = pos_err < 4.0 and ori_err < 1.0   # 2 mm, 1 deg tolerance
        tracking_valid = motion_done

        self.state.set_motion_done(motion_done)
        self.state.set_tracking_valid(tracking_valid)

        if motion_done:
            log.info(f"Target '{self.state.target.label}' reached — "
                     f"pos_err={pos_err:.2f} mm, ori_err={ori_err:.2f} deg, "
                     f"force={force:.3f}")
        else:
            log.debug(f"Converging — pos_err={pos_err:.2f} mm, ori_err={ori_err:.2f} deg")

    def _compute_pose_error(
        self,
        achieved_pos_mm: list,
        achieved_ori_deg: list,
    ) -> Tuple[float, float]:
        """
        Returns (position_error_mm, orientation_error_deg) between
        the achieved pose and the current target.
        """
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