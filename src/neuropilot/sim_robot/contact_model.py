# tms-robot-sim/contact_model.py

from typing import Optional

from . import config
from .mujoco_world import MuJoCoWorld
from .collision_checker import CollisionChecker
from .utils.logging_utils import get_logger

log = get_logger(__name__)


class ContactModel:
    def __init__(self, world: MuJoCoWorld, collision_checker: CollisionChecker):
        self.world = world
        self.collision_checker = collision_checker
        self._force_scale = config.CONTACT_FORCE_SCALE

    def compute_force_feedback(self) -> float:
        """
        Returns a simulated force feedback value based on contact
        between the coil and the head.

        Logic:
          1. If there are actual contact points → compute force from
             PyBullet's normal force values.
          2. If no contact points but within proximity → estimate force
             from distance (soft approach zone).
          3. If no contact and not in proximity → return 0.0.

        The pipeline's CobotOnTarget handler reads this value and
        uses it to decide whether the coil is pressing on the head.
        """
        # --- Case 1: real contact points from MuJoCo ---
        contacts = self.world.get_robot_head_contacts()

        if contacts:
            total_normal_force = sum(c["normal_force"] for c in contacts)
            force_value = total_normal_force * self._force_scale
            log.debug(f"Contact force from {len(contacts)} contact point(s): {force_value:.3f}")
            return float(force_value)

        # --- Case 2: no contact yet, but within proximity ---
        distance_mm = self.collision_checker.get_closest_distance_mm()

        if distance_mm is not None and distance_mm > 0.0:
            threshold_mm = config.COLLISION_DISTANCE_THRESHOLD_M * 1000.0
            # Linear ramp: at threshold → 0.0, at 0 mm → CONTACT_FORCE_SCALE
            proximity_ratio = 1.0 - (distance_mm / threshold_mm)
            proximity_ratio = max(0.0, min(1.0, proximity_ratio))
            force_value = proximity_ratio * self._force_scale
            log.debug(f"Proximity-based force: {force_value:.3f} (distance {distance_mm:.2f} mm)")
            return float(force_value)

        # --- Case 3: far from head ---
        return 0.0

    def is_coil_on_head(self, threshold: float = 0.5) -> bool:
        """
        Returns True if the computed force feedback is above the given
        threshold — meaning the coil is considered to be pressing on the head.

        This mirrors the pressure_thresh logic in PipelineController.
        """
        return self.compute_force_feedback() >= threshold