# sim_client.py

#Socket.IO client for the sim relay. It should listen on to_neuronavigation and send on from_neuronavigation


# sim_client.py

import asyncio
import socketio

from .config import (
    URL,
    FROM_EVENT,
    TO_EVENT,
    POSITION_TOL_MM,
    ORIENTATION_TOL_DEG,
    TOPIC_CREATE_TARGET,
    TOPIC_COIL_AT_TARGET,
    TOPIC_REALIZED_TARGET,
    TOPIC_STIM_MARKER,
    TOPIC_SIM_TRACKING_STATE,
    HEAD_POSITION,
    HEAD_ORIENTATION,
)
from .evaluator import is_pose_within_tolerance
from .state import VirtualNeuronavigationState
from .transforms import (
    nav_world_to_simnibs,
    simnibs_orientation_to_external_controller,
    pipeline_orientation_to_simnibs,
)


class SimNeuronavigationClient:
    def __init__(self, state: VirtualNeuronavigationState, url: str = URL):
        self.url = url
        self.state = state
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=0,
            reconnection_delay=1,
            reconnection_delay_max=5,
            logger=False,
            engineio_logger=False,
        )

        self.sio.on("connect", self.on_connect)
        self.sio.on("disconnect", self.on_disconnect)
        self.sio.on(TO_EVENT, self.on_message_received)

    async def connect(self):
        # The initial connect must succeed; reconnection=True only helps
        # afterwards. Retry with a clear log instead of a raw traceback.
        while True:
            try:
                await self.sio.connect(self.url)
                break
            except socketio.exceptions.ConnectionError as e:
                print(f"[virtual_neuronavigation] Relay not reachable at {self.url} ({e}). Retrying in 2 s...")
                await asyncio.sleep(2)
        self._wait_task = asyncio.create_task(self.sio.wait())

    async def on_connect(self):
        print(f"[virtual_neuronavigation] Connected to {self.url}")

    async def on_disconnect(self):
        print("[virtual_neuronavigation] Disconnected")

    async def send_message(self, topic, data=None):
        if data is None:
            data = {}
        await self.sio.emit(FROM_EVENT, {"topic": topic, "data": data})

    async def on_message_received(self, msg):
        topic = msg.get("topic")
        data = msg.get("data", {})

        if topic == TOPIC_CREATE_TARGET:
            await self.handle_create_target(data)
        elif topic == TOPIC_SIM_TRACKING_STATE:
            await self.handle_tracking_state(data)
        elif topic == TOPIC_STIM_MARKER:
            await self.handle_stim_marker(data)

    def _unwrap_pipeline_marker_payload(self, data):
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
            return data["data"]
        return data

    async def handle_create_target(self, data):
        payload = self._unwrap_pipeline_marker_payload(data)

        position = payload.get("position")
        orientation = payload.get("orientation")
        label = payload.get("label")

        if position is None or orientation is None:
            print("[virtual_neuronavigation] Invalid target payload")
            return

        # Store target in pipeline coords (as received from pipeline)
        # Position is raw SimNIBS, orientation is InVesalius convention
        self.state.set_target(position, orientation, label=label)
        print(
            f"[virtual_neuronavigation] New target: label={label}, "
            f"pipeline_pos={[round(v, 2) for v in position]}, "
            f"pipeline_ori={[round(v, 2) for v in orientation]}"
        )

        # Forward to tms-robot-sim via "Neuronavigation to Robot: Set target"
        # the navigation sim will transform pipeline coords → navigation world
        await self.send_message("Neuronavigation to Robot: Set target", {
            "position": position,
            "orientation": orientation,
            "label": label,
        })
        print("[virtual_neuronavigation] Forwarded target to robot sim")

    async def handle_tracking_state(self, data):
        position = data.get("position")
        orientation = data.get("orientation")

        if position is None or orientation is None:
            print("[virtual_neuronavigation] Tracking state missing pose")
            return

        self.state.update_tracking_state(
            position=position,
            orientation=orientation,
            ik_success=data.get("ik_success", False),
            collision=data.get("collision", False),
            motion_done=data.get("motion_done", False),
            tracking_valid=data.get("tracking_valid", False),
        )

        if not self.state.has_target():
            return

        if not self.state.ik_success:
            return

        if self.state.collision:
            print("[virtual_neuronavigation] Collision=True, not sending target reached")
            return

        if not self.state.motion_done:
            return

        if not self.state.tracking_valid:
            return

        # Transform current pose from the navigation world frame → raw SimNIBS
        # position is in mm, nav_world_to_simnibs expects meters
        raw_simnibs_pos, raw_simnibs_ori = nav_world_to_simnibs(
            world_pos_m=[v / 1000.0 for v in position],  # mm → meters
            world_euler_deg=orientation,
            head_position_m=HEAD_POSITION,
            head_orientation_deg=HEAD_ORIENTATION,
        )

        # Transform raw SimNIBS orientation → pipeline orientation
        pipeline_ori = simnibs_orientation_to_external_controller(raw_simnibs_ori)

        # Compare in pipeline coordinates
        # Position is raw SimNIBS (same as pipeline), orientation is pipeline convention
        within, pos_err, rot_err = is_pose_within_tolerance(
            current_position=raw_simnibs_pos,
            current_orientation=pipeline_ori,
            target_position=self.state.target_position,  # pipeline coords (raw SimNIBS pos)
            target_orientation=self.state.target_orientation,  # pipeline coords (InVesalius ori)
            position_tol_mm=POSITION_TOL_MM,
            orientation_tol_deg=ORIENTATION_TOL_DEG,
        )

        print(
            "[virtual_neuronavigation] Tracking check | "
            f"within={within}, pos_err={pos_err:.2f} mm, "
            f"rot_err=({rot_err[0]:.2f}, {rot_err[1]:.2f}, {rot_err[2]:.2f}) deg, "
            f"ik_success={self.state.ik_success}, collision={self.state.collision}, "
            f"motion_done={self.state.motion_done}, tracking_valid={self.state.tracking_valid}"
        )

        if within:
            self.state.latest_valid_pose = self.state.snapshot_current_pose()

            if not self.state.target_reached_sent:
                await self.send_message(TOPIC_COIL_AT_TARGET, {"state": True})
                self.state.target_reached_sent = True
                print("[virtual_neuronavigation] Sent: Coil at target")

    async def handle_stim_marker(self, data):
        label = data.get("label") if isinstance(data, dict) else None
        if label != "stim_mark":
            return

        # Freeze the pose at stim time.
        if self.state.latest_valid_pose is not None:
            pose = self.state.latest_valid_pose
        else:
            pose = self.state.snapshot_current_pose()

        if pose is None:
            print("[virtual_neuronavigation] No stim pose available")
            return

        # Transform the navigation world frame → raw SimNIBS
        # pose["position"] is in mm, nav_world_to_simnibs expects meters
        raw_simnibs_pos, raw_simnibs_ori = nav_world_to_simnibs(
            world_pos_m=[v / 1000.0 for v in pose["position"]],  # mm → meters
            world_euler_deg=pose["orientation"],
            head_position_m=HEAD_POSITION,
            head_orientation_deg=HEAD_ORIENTATION,
        )

        # Send realized target in raw SimNIBS/world coordinates
        # This matches what InVesalius does in real hardware (marker.to_world())
        await self.send_message(TOPIC_REALIZED_TARGET, {
            "markers": [raw_simnibs_pos, raw_simnibs_ori]
        })
        print(
            f"[virtual_neuronavigation] Sent realized target: "
            f"pos={[round(v, 2) for v in raw_simnibs_pos]}, "
            f"ori={[round(v, 2) for v in raw_simnibs_ori]}"
        )