from typing import Optional

from . import config
from .mujoco_world import MuJoCoWorld
from .utils.logging_utils import get_logger

log = get_logger(__name__)


class CollisionChecker:
    def __init__(self, world: MuJoCoWorld):
        self.world = world
        self._distance_threshold_m = config.COLLISION_DISTANCE_THRESHOLD_M

    def check(self) -> bool:
        """
        Returns True if the robot is in collision with the head,
        False if it is safe.

        Collision is defined as the closest distance between any
        robot link and the head mesh being below the threshold.
        """
        distance = self.world.get_robot_head_closest_distance(
            distance_threshold=self._distance_threshold_m
        )

        if distance is None:
            # No points found within threshold — safe
            return False

        if distance <= config.PENTRATION_TOLERANCE:
            log.warning(f"Collision detected: penetration depth {distance * 1000:.2f} mm")
            return True

        if distance <= self._distance_threshold_m:
            log.warning(f"Proximity warning: {distance * 1000:.2f} mm to head")
            return False

        return False

    def check_self_collision(self) -> bool:
        contacts = self.world.get_self_collision_contacts()
        if contacts:
            log.warning("Self-collision detected")
            return True
        return False

    def get_closest_distance_mm(self) -> Optional[float]:
        """
        Returns the closest distance in mm between robot and head.
        Returns None if no objects are within the search threshold.
        Useful for contact_model.py to compute a force value from proximity.
        """
        distance_m = self.world.get_robot_head_closest_distance(
            distance_threshold=self._distance_threshold_m
        )

        if distance_m is None:
            return None

        return distance_m * 1000.0