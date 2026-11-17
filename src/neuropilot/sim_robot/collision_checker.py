from typing import Optional

from . import config
from .mujoco_world import MuJoCoWorld
from .utils.logging_utils import get_logger

log = get_logger(__name__)


class CollisionChecker:
    def __init__(self, world: MuJoCoWorld):
        self.world = world
        self._distance_threshold_m = config.COLLISION_DISTANCE_THRESHOLD_M
        # The planner checks at 20 Hz. Log one line when an episode starts,
        # not on every tick or every distance change, and reset after the
        # robot is clear so a later episode can be reported again.
        self._proximity_active = False
        self._collision_active = False
        self._self_collision_logged = False

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
            self._proximity_active = False
            self._collision_active = False
            return False

        distance_mm = distance * 1000.0
        if distance <= config.PENTRATION_TOLERANCE:
            if not self._collision_active:
                log.warning(f"Collision detected: penetration depth "
                            f"{distance_mm:.2f} mm")
                self._collision_active = True
            self._proximity_active = False
            return True

        if distance <= self._distance_threshold_m:
            if not self._proximity_active:
                log.warning(f"Proximity warning: {distance_mm:.2f} mm to head")
                self._proximity_active = True
            self._collision_active = False
            return False

        self._proximity_active = False
        self._collision_active = False
        return False

    def check_self_collision(self) -> bool:
        contacts = self.world.get_self_collision_contacts()
        collision = any(
            contact.get("dist", 0.0) <= config.SELF_PENETRATION_TOLERANCE
            for contact in contacts)
        if collision and not self._self_collision_logged:
            log.warning("Self-collision detected")
        self._self_collision_logged = collision
        return collision

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