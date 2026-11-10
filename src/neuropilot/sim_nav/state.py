# state.py
#Stores:

    #latest target from pipeline,

    #latest robot pose,

    #collision flag,

    #whether “target reached” has already been sent for the current target,

    #latest pose at stim time.

# state.py

from dataclasses import dataclass
from typing import Optional, List, Dict


@dataclass
class VirtualNeuronavigationState:
    target_position: Optional[List[float]] = None
    target_orientation: Optional[List[float]] = None
    target_label: Optional[str] = None

    current_position: Optional[List[float]] = None
    current_orientation: Optional[List[float]] = None

    latest_valid_pose: Optional[Dict[str, List[float]]] = None
    stim_pose: Optional[Dict[str, List[float]]] = None

    ik_success: bool = False
    collision: bool = False
    motion_done: bool = False
    tracking_valid: bool = False

    target_reached_sent: bool = False

    def set_target(self, position, orientation, label=None):
        self.target_position = list(position)
        self.target_orientation = list(orientation)
        self.target_label = label
        self.target_reached_sent = False
        self.latest_valid_pose = None
        self.stim_pose = None

    def update_tracking_state(
        self,
        position,
        orientation,
        ik_success=False,
        collision=False,
        motion_done=False,
        tracking_valid=False,
    ):
        self.current_position = list(position)
        self.current_orientation = list(orientation)
        self.ik_success = bool(ik_success)
        self.collision = bool(collision)
        self.motion_done = bool(motion_done)
        self.tracking_valid = bool(tracking_valid)

    def has_target(self) -> bool:
        return self.target_position is not None and self.target_orientation is not None

    def has_current_pose(self) -> bool:
        return self.current_position is not None and self.current_orientation is not None

    def snapshot_current_pose(self):
        if not self.has_current_pose():
            return None
        return {
            "position": list(self.current_position),
            "orientation": list(self.current_orientation),
        }

    def current_pose_as_markers(self):
        pose = self.snapshot_current_pose()
        if pose is None:
            return None
        return [pose["position"], pose["orientation"]]

    def latest_valid_pose_as_markers(self):
        if self.latest_valid_pose is None:
            return None
        return [
            list(self.latest_valid_pose["position"]),
            list(self.latest_valid_pose["orientation"]),
        ]

    def stim_pose_as_markers(self):
        if self.stim_pose is None:
            return None
        return [
            list(self.stim_pose["position"]),
            list(self.stim_pose["orientation"]),
        ]