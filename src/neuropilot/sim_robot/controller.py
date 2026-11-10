import asyncio
from typing import Optional

from .state import RobotState
from .sim_client import SimRobotClient
from .motion_planner import MotionPlanner
from .utils.logging_utils import get_logger

log = get_logger(__name__)


class SimRobotController:
    def __init__(self, state: RobotState, client: SimRobotClient, motion_planner: MotionPlanner):
        self.state          = state
        self.client         = client
        self.motion_planner = motion_planner

        self._publish_interval_sec = 0.05
        self._health_interval_sec  = 1.0
        self._control_interval_sec = 0.05

        self._last_force_feedback: Optional[float] = None
        self._running = False

    async def run(self):
        self._running = True
        await asyncio.gather(
            self.run_control_loop(),
            self.run_publish_loop(),
            self.run_health_loop(),
        )

    async def run_control_loop(self):
        while self._running:
            await self.step_control()
            await asyncio.sleep(self._control_interval_sec)

    async def run_publish_loop(self):
        while self._running:
            await self.client.publish_tracking_state()
            await self._publish_force_if_changed()
            await asyncio.sleep(self._publish_interval_sec)

    async def run_health_loop(self):
        while self._running:
            status  = "Connected" if self.state.connected else "Disconnected"
            message = self.state.last_status_text
            await self.client.publish_health_status(status=status, message=message)
            await asyncio.sleep(self._health_interval_sec)

    async def step_control(self):
        if self.state.objective == 2:
            if not self.motion_planner.is_move_away_active():
                self.motion_planner.start_move_away()
            else:
                self.motion_planner.step_move_away()
            return

        if not self.state.tracking_enabled:
            self.state.set_motion_done(False)
            self.state.set_tracking_valid(False)
            self.state.set_force_feedback(0.0)
            self.state.last_status_text = "Idle - tracking disabled"
            return

        if not self.state.target.is_set():
            self.state.set_motion_done(False)
            self.state.set_tracking_valid(False)
            self.state.set_force_feedback(0.0)
            self.state.last_status_text = "Waiting for target"
            return

        if self.state.free_drive:
            self.state.set_motion_done(False)
            self.state.set_tracking_valid(False)
            self.state.set_force_feedback(0.0)
            self.state.last_status_text = "Free drive active"
            return

        # All guards passed — let motion_planner do the real work
        self.motion_planner.step()

    async def _publish_force_if_changed(self):
        current_force = round(float(self.state.force_feedback), 4)
        if self._last_force_feedback is None or current_force != self._last_force_feedback:
            await self.client.publish_force_feedback()
            self._last_force_feedback = current_force

    def stop(self):
        self._running = False