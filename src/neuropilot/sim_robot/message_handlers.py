from . import config
from .state import RobotState
from .utils.logging_utils import get_logger

log = get_logger(__name__)


class MessageHandlers:
    def __init__(self, state: RobotState):
        self.state = state

    def handle(self, topic: str, data: dict) -> None:
        if topic == config.TOPIC_CREATE_MARKER:
            self._handle_create_marker(data)

        elif topic == config.TOPIC_SET_TARGET:
            self._handle_set_target(data)

        elif topic == config.TOPIC_PRESS_BUTTON:
            self._handle_press_robot_button(data)

        elif topic == config.TOPIC_SET_OBJECTIVE:
            self._handle_set_objective(data)

        elif topic == config.TOPIC_STOP:
            self._handle_stop(data)

        else:
            log.debug(f"No handler for topic: {topic}")

    # ── Handlers ──────────────────────────────────────────────────────

    def _handle_create_marker(self, data: dict) -> None:
        """
        The state now stores targets in MuJoCo world coordinates (mm) instead of InVesalius convention.
        The motion_planner.py and ik_solver.py need no changes — they already expect mm position and deg orientation,
        and the IK solver divides by 1000 internally.
        """
        payload = self._unwrap(data)

        position = payload.get("position")
        orientation = payload.get("orientation")
        label = payload.get("label")

        if position is None or orientation is None:
            log.warning("Create Marker received with missing position or orientation")
            self.state.last_status_text = "Invalid marker payload"
            return

        # ── NEW: Convert InVesalius convention → raw SimNIBS → PyBullet world ──
        from .utils.transforms import inverse_pipeline_axis_transform, simnibs_to_mujoco_world

        # Step 1: Position is raw SimNIBS (pipeline doesn't transform it)
        # Only orientation needs inverse of pipeline's axis transform
        _, simnibs_ori = inverse_pipeline_axis_transform(position, orientation)

        # Step 2: Convert raw SimNIBS → MuJoCo world (meters)
        world_pos, world_ori = simnibs_to_mujoco_world(
            simnibs_pos_mm=position,
            simnibs_euler_deg=simnibs_ori,
            head_position_m=config.HEAD_POSITION,
            head_orientation_deg=config.HEAD_ORIENTATION,
        )

        # Store world-frame coordinates (meters → mm for state consistency)
        from .utils.transforms import m_to_mm
        state_pos_mm = m_to_mm(world_pos)

        self.state.set_target(position=state_pos_mm, orientation=world_ori, label=label)
        log.info(f"Target set: label='{label}', "
                 f"world_pos_mm={state_pos_mm}, world_ori={world_ori}")

    def _handle_set_target(self, data: dict) -> None:
        """
        Receive target from Virtual Neuronavigation in pipeline coords.
        Same logic as _handle_create_marker - transforms pipeline coords to PyBullet world.
        """
        payload = self._unwrap(data)

        position = payload.get("position")
        orientation = payload.get("orientation")
        label = payload.get("label")

        if position is None or orientation is None:
            log.warning("Set target received with missing position or orientation")
            self.state.last_status_text = "Invalid target payload"
            return

        # Convert pipeline coords → raw SimNIBS → MuJoCo world
        from .utils.transforms import inverse_pipeline_axis_transform, simnibs_to_mujoco_world, m_to_mm

        # Step 1: Position is raw SimNIBS (pipeline doesn't transform it)
        # Only orientation needs inverse of pipeline's axis transform
        _, simnibs_ori = inverse_pipeline_axis_transform(position, orientation)

        # Step 2: Convert raw SimNIBS → MuJoCo world (meters)
        world_pos, world_ori = simnibs_to_mujoco_world(
            simnibs_pos_mm=position,
            simnibs_euler_deg=simnibs_ori,
            head_position_m=config.HEAD_POSITION,
            head_orientation_deg=config.HEAD_ORIENTATION,
        )

        # Store world-frame coordinates (meters → mm for state consistency)
        state_pos_mm = m_to_mm(world_pos)

        self.state.set_target(position=state_pos_mm, orientation=world_ori, label=label)
        log.info(f"Target set from neuronavigation: label='{label}', "
                 f"world_pos_mm={state_pos_mm}, world_ori={world_ori}")

    def _handle_press_robot_button(self, data: dict) -> None:
        pressed = bool((data or {}).get("pressed", False))
        self.state.set_tracking_enabled(pressed)
        log.info(f"Tracking enabled → {pressed}")

    def _handle_set_objective(self, data: dict) -> None:
        objective = int((data or {}).get("objective", 0))
        self.state.set_objective(objective)
        log.info(f"Objective → {objective}")

    def _handle_stop(self, data: dict) -> None:
        self.state.set_tracking_enabled(False)
        self.state.set_motion_done(False)
        self.state.set_tracking_valid(False)
        self.state.set_force_feedback(0.0)
        self.state.last_status_text = "Stopped by command"
        log.info("STOP received — all motion halted")

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _unwrap(data: dict) -> dict:
        """
        Some messages from the relay arrive double-wrapped:
        { "data": { "position": ..., "orientation": ... } }
        This unwraps that one extra layer if present.
        """
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
            return data["data"]
        return data or {}