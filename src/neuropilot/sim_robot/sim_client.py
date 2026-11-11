import asyncio
import socketio

from . import config
from .state import RobotState
from .message_handlers import MessageHandlers
from .utils.logging_utils import get_logger

log = get_logger(__name__)


class SimRobotClient:
    def __init__(self, url: str, state: RobotState, world=None):
        self.url      = url
        self.state    = state
        self.handlers = MessageHandlers(state, world=world)
        self.loop = None  # running event loop, captured in connect()

        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=0,
            reconnection_delay=1,
            reconnection_delay_max=5,
            logger=False,
            engineio_logger=False,
        )

        self.sio.on("connect",    self._on_connect)
        self.sio.on("disconnect", self._on_disconnect)
        self.sio.on("to_robot",   self._on_message_received)

    # ── Connection ────────────────────────────────────────────────────

    async def connect(self) -> None:
        # The initial connect must succeed; reconnection=True only helps
        # afterwards. Retry with a clear log instead of a raw traceback.
        self.loop = asyncio.get_running_loop()
        while True:
            try:
                await self.sio.connect(self.url)
                break
            except socketio.exceptions.ConnectionError as e:
                log.warning(f"Relay not reachable at {self.url} ({e}). Retrying in 2 s...")
                await asyncio.sleep(2)
        self._wait_task = asyncio.create_task(self.sio.wait())

    async def _on_connect(self) -> None:
        self.state.set_connected(True)
        log.info(f"Connected to relay server at {self.url}")

    async def _on_disconnect(self) -> None:
        self.state.set_connected(False)
        log.warning("Disconnected from relay server")

    # ── Send ──────────────────────────────────────────────────────────

    async def send_message(self, topic: str, data: dict = None) -> None:
        if data is None:
            data = {}
        message = {"topic": topic, "data": data}
        # Callers run in fire-and-forget loops; raising while disconnected
        # only produces lost messages and unhandled-task noise. Drop instead;
        # the client reconnects automatically.
        if not self.sio.connected:
            return
        try:
            await self.sio.emit("from_robot", message)
        except socketio.exceptions.BadNamespaceError:
            # Disconnected between the check and the emit.
            return

    # ── Publish helpers ───────────────────────────────────────────────

    async def publish_tracking_state(self) -> None:
        await self.send_message(
            topic=config.TOPIC_TRACKING_STATE,
            data={
                "position":      list(self.state.current_position),
                "orientation":   list(self.state.current_orientation),
                "ik_success":    self.state.ik_success,
                "collision":     self.state.collision,
                "motion_done":   self.state.motion_done,
                "tracking_valid": self.state.tracking_valid,
            },
        )

    async def publish_force_feedback(self) -> None:
        await self.send_message(
            topic=config.TOPIC_FORCE_FEEDBACK,
            data={
                "force_feedback": self.state.force_feedback,
            },
        )

    async def publish_health_status(self, status: str, message: str) -> None:
        # Map the controller's connection state to the pipeline's SystemStatus
        # vocabulary ("OK"/"ERROR") — cobot-pipeline-controller/systems/robot.py
        # parses this via SystemStatus.str_to_enum on the other end.
        pipeline_status = "OK" if status.lower() == "connected" else "ERROR"
        await self.send_message(
            topic=config.TOPIC_HEALTH_STATUS,
            data={
                "status":  pipeline_status,
                "message": message,
                # The pipeline shows these next to the robot's status card.
                "robot_id": "virtual-twin",
                "info": {
                    "Robot": config.MODEL_NAME,
                    "Mode": "Headless MuJoCo",
                    "Camera": f"{config.CAMERA_STREAM_WIDTH}x{config.CAMERA_STREAM_HEIGHT}"
                              f" @ {config.CAMERA_STREAM_FPS:g} fps",
                },
            },
        )

    # ── Receive ───────────────────────────────────────────────────────

    async def _on_message_received(self, msg: dict) -> None:
        topic = msg.get("topic")
        data  = msg.get("data", {})

        if topic is None:
            log.warning("Received malformed message without topic")
            return

        self.handlers.handle(topic, data)