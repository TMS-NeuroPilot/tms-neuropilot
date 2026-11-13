import json
import os
import threading

from . import config
from .state import RobotState
from .utils.logging_utils import get_logger

log = get_logger(__name__)


class MessageHandlers:
    def __init__(self, state: RobotState, world=None):
        self.state = state
        # Optional MuJoCoWorld: needed for the head-mesh override, which
        # replaces the phantom geometry at runtime.
        self.world = world
        # Head requests are converted in worker threads; a later request
        # (another subject, or a cleared field) must win over an older one.
        self._head_request = 0
        self._head_request_lock = threading.Lock()
        self._head_apply_lock = threading.Lock()

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

        elif topic == config.TOPIC_SET_HEAD_MESH:
            self._handle_set_head_mesh(data)

        elif topic == config.TOPIC_SET_START_POSE:
            payload = self._unwrap(data)
            joints = payload.get("joints")
            if isinstance(joints, (list, tuple)) and len(joints) == 6:
                self.state.set_start_joints(joints)
                if self.world is not None:
                    self.world.reset_joint_positions(list(joints))
                log.info("Start pose set from the collision test.")

        elif topic == config.TOPIC_SET_FREE_DRIVE:
            payload = self._unwrap(data)
            enabled = payload.get("set")
            if enabled is not None:
                self.state.set_free_drive(bool(enabled))
                log.info(f"Free drive {'enabled' if enabled else 'disabled'}")

        elif topic == config.TOPIC_SET_DEFAULT_SPEED:
            payload = self._unwrap(data)
            ratio = payload.get("default_speed_ratio")
            if ratio is not None:
                self.state.set_default_speed_ratio(float(ratio))
                log.info(f"Default speed ratio set to {float(ratio):.2f}")

        elif topic == config.TOPIC_SET_TUNING_SPEED:
            payload = self._unwrap(data)
            ratio = payload.get("tuning_speed_ratio")
            if ratio is not None:
                self.state.set_tuning_speed_ratio(float(ratio))
                log.info(f"Tuning speed ratio set to {float(ratio):.2f}")

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

        # Pipeline coordinates -> raw SimNIBS orientation -> MuJoCo world.
        from .utils.transforms import pipeline_target_to_mujoco_world, m_to_mm
        world_pos, world_ori = pipeline_target_to_mujoco_world(
            position, orientation,
            config.HEAD_POSITION, config.HEAD_ORIENTATION)
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

        # Pipeline coordinates -> raw SimNIBS orientation -> MuJoCo world.
        from .utils.transforms import pipeline_target_to_mujoco_world, m_to_mm
        world_pos, world_ori = pipeline_target_to_mujoco_world(
            position, orientation,
            config.HEAD_POSITION, config.HEAD_ORIENTATION)
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

    # ── Head phantom override ──────────────────────────────────────────
    def _next_head_request(self) -> int:
        with self._head_request_lock:
            self._head_request += 1
            return self._head_request

    def _head_request_is_current(self, token: int) -> bool:
        with self._head_request_lock:
            return token == self._head_request

    def _handle_set_head_mesh(self, data: dict) -> None:
        """
        The pipeline announces the head mesh entered in the project window.
        The scalp surface is converted to an STL for MuJoCo (cached) and the
        phantom is replaced at runtime.  An empty path resets the default
        phantom, so a stale subject mesh never outlives its project.
        """
        payload = self._unwrap(data)
        fn_msh = payload.get("mesh_path") if isinstance(payload, dict) else None
        token = self._next_head_request()

        if not fn_msh:
            threading.Thread(target=self._reset_head_mesh,
                             args=(token,), daemon=True).start()
            return
        if not os.path.isfile(fn_msh):
            log.warning(f"Head mesh announcement with invalid path: {fn_msh}")
            threading.Thread(target=self._reset_head_mesh,
                             args=(token,), daemon=True).start()
            return
        if fn_msh == self.state.head_mesh_source:
            log.debug(f"Head mesh already active: {fn_msh}")
            return
        if self.world is None:
            log.warning("No MuJoCo world available -- head mesh ignored.")
            return

        log.info(f"Head mesh override requested: {fn_msh}")

        def _apply():
            from .mesh_converter import convert_head_mesh

            try:
                stl_path = convert_head_mesh(fn_msh)
            except Exception as e:
                log.error(f"Head mesh conversion failed: {e}")
                self._reset_head_mesh(token)
                return

            with self._head_apply_lock:
                if not self._head_request_is_current(token):
                    log.debug("Head mesh request superseded; discarding result.")
                    return

                applied = False
                if self.world is not None:
                    applied = self.world.reload_head(stl_path)
                if not applied:
                    # Do not leave a persisted mesh that the running model
                    # rejected; reset to the neutral phantom instead.
                    if self.world is not None:
                        self.world.reload_head(None)
                    try:
                        os.remove(config.HEAD_OVERRIDE_FILE)
                    except OSError:
                        pass
                    self.state.head_mesh_source = None
                    log.warning("Head mesh converted but not applied; "
                                "reset to the default phantom.")
                    return

                # Persist only after the running model accepted the mesh, so
                # a restart never picks up a phantom that failed here.
                try:
                    os.makedirs(os.path.dirname(config.HEAD_OVERRIDE_FILE),
                                exist_ok=True)
                    with open(config.HEAD_OVERRIDE_FILE, "w") as f:
                        json.dump({"msh_path": fn_msh, "stl_path": stl_path}, f)
                except OSError as e:
                    log.error(f"Could not persist the head override: {e}")

                self.state.head_mesh_source = fn_msh
                log.info("Head phantom updated from the project head mesh.")

        # Conversion takes seconds (simnibs import + decimation) -- off the
        # event loop.
        threading.Thread(target=_apply, daemon=True).start()

    def _reset_head_mesh(self, token: int) -> None:
        """Return to the default phantom and remove the persisted override."""
        with self._head_apply_lock:
            if not self._head_request_is_current(token):
                return
            world_override = getattr(self.world, "head_mesh_stl", None)
            if (self.state.head_mesh_source is None and world_override is None
                    and not os.path.isfile(config.HEAD_OVERRIDE_FILE)):
                log.debug("Default head phantom already active.")
                return

            try:
                os.remove(config.HEAD_OVERRIDE_FILE)
            except FileNotFoundError:
                pass
            except OSError as e:
                log.error(f"Could not remove the head override file: {e}")

            applied = False
            if self.world is not None:
                applied = self.world.reload_head(None)
            self.state.head_mesh_source = None
            if applied:
                log.info("Head phantom reset to the default head.stl.")
            elif self.world is not None:
                log.warning("Default head phantom could not be applied; "
                            "restart the simulator to reset it.")