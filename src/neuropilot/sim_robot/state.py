from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class RobotTarget:
    position: Optional[List[float]] = None          # [x, y, z] in mm
    orientation: Optional[List[float]] = None       # [rota, rotb, rotc] in deg
    label: Optional[str] = None

    def clear(self):
        self.position = None
        self.orientation = None
        self.label = None

    def is_set(self) -> bool:
        return self.position is not None and self.orientation is not None


@dataclass
class RobotState:
    # Connection / mode
    connected: bool = False
    tracking_enabled: bool = False
    free_drive: bool = False
    objective: int = 0

    # Speed settings
    default_speed_ratio: float = 0.25
    tuning_speed_ratio: float = 0.10

    # Robot configuration
    joint_positions: List[float] = field(default_factory=list)
    target_joint_positions: List[float] = field(default_factory=list)

    # End-effector / coil pose
    current_position: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    current_orientation: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])

    # Commanded target from pipeline/neuronavigation
    target: RobotTarget = field(default_factory=RobotTarget)

    # IK / motion / collision / contact
    ik_success: bool = False
    collision: bool = False
    tracking_valid: bool = False
    motion_done: bool = False
    force_feedback: float = 0.0

    # Diagnostics
    last_status_text: str = "Idle"

    def set_connected(self, connected: bool):
        self.connected = bool(connected)
        self.last_status_text = "Connected to relay" if connected else "Disconnected from relay"

    def set_target(self, position, orientation, label=None):
        self.target.position = list(position)
        self.target.orientation = list(orientation)
        self.target.label = label

        self.ik_success = False
        self.collision = False
        self.tracking_valid = False
        self.motion_done = False
        self.last_status_text = f"Target set: {label or 'unnamed'}"

    def clear_target(self):
        self.target.clear()
        self.ik_success = False
        self.tracking_valid = False
        self.motion_done = False
        self.last_status_text = "Target cleared"

    def update_current_pose(self, position, orientation):
        self.current_position = list(position)
        self.current_orientation = list(orientation)

    def set_joint_positions(self, joints):
        self.joint_positions = list(joints)

    def set_target_joint_positions(self, joints):
        self.target_joint_positions = list(joints)

    def set_tracking_enabled(self, enabled: bool):
        self.tracking_enabled = bool(enabled)
        self.motion_done = False
        self.last_status_text = "Tracking enabled" if enabled else "Tracking disabled"

    def set_free_drive(self, enabled: bool):
        self.free_drive = bool(enabled)
        self.last_status_text = "Free drive enabled" if enabled else "Free drive disabled"

    def set_default_speed_ratio(self, ratio: float):
        self.default_speed_ratio = float(ratio)
        self.last_status_text = f"Default speed ratio set to {ratio:.3f}"

    def set_tuning_speed_ratio(self, ratio: float):
        self.tuning_speed_ratio = float(ratio)
        self.last_status_text = f"Tuning speed ratio set to {ratio:.3f}"

    def set_objective(self, objective: int):
        self.objective = int(objective)
        self.last_status_text = f"Objective set to {objective}"

    def set_ik_result(self, success: bool, target_joints=None):
        self.ik_success = bool(success)
        if target_joints is not None:
            self.target_joint_positions = list(target_joints)
        self.motion_done = False
        self.last_status_text = "IK solved" if success else "IK failed"

    def set_collision_state(self, collision: bool):
        self.collision = bool(collision)
        if collision:
            self.motion_done = False
            self.last_status_text = "Collision detected"

    def set_tracking_valid(self, valid: bool):
        self.tracking_valid = bool(valid)

    def set_motion_done(self, done: bool):
        self.motion_done = bool(done)
        if done:
            self.last_status_text = "Motion complete"

    def set_force_feedback(self, value: float):
        self.force_feedback = float(value)

    def build_tracking_state_message(self) -> dict:
        return {
            "topic": "SIM - Robot to Neuronavigation: Tracking State",
            "data": {
                "position": list(self.current_position),
                "orientation": list(self.current_orientation),
                "ik_success": self.ik_success,
                "collision": self.collision,
                "motion_done": self.motion_done,
                "tracking_valid": self.tracking_valid,
            },
        }

    def build_force_feedback_message(self) -> dict:
        return {
            "topic": "Robot to Neuronavigation: Send force sensor data",
            "data": {
                "force_feedback": self.force_feedback,
            },
        }