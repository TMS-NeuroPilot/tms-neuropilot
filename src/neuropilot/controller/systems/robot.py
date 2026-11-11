import asyncio

from ..systems.system import SystemStatus, System

class Robot(System):
    NAME = "Robot"
    DESCRIPTION = "Real (via relay)"
    
    ERROR_RECOVERIES = {
        'Socket Broken' : 'Restart Robot Connection',
        'Emergency Stopped' : None,
    }
    
    def __init__(self, update_control_panel_func, remote):
        super().__init__(update_control_panel_func=update_control_panel_func)
        self.remote = remote
        self.robot_id = None
        self._robot_info = {}
        self.remote.register_handlers({
            'Robot to Pipeline: Health status' : self.on_robot_health_update,
        })
        self._publish_details()

    def _publish_details(self):
        """Relay address, robot identity and live link state.  The robot
        publishes its own fields in the health message (``info``); the relay
        part is known locally."""
        link = getattr(getattr(self.remote, "sio", None), "connected", False)
        details = {"Relay": getattr(self.remote, "url", "—")}
        if self.robot_id is not None:
            details["Robot ID"] = self.robot_id
        details.update(self._robot_info)
        details["Link"] = "connected" if link else "disconnected"
        self.set_details(details)
        
    def try_connect(self):
        # Since were connected through the relay server (which is not exclusive to the robot) there is not much to check here.
        pass
    
    async def on_robot_health_update(self, data):
        if not isinstance(data, dict):
            return
        if data.get("robot_id") is not None:
            self.robot_id = data.get("robot_id")
        info = data.get("info")
        if isinstance(info, dict):
            self._robot_info = {str(k): v for k, v in info.items()}
        self._publish_details()
        status = SystemStatus.str_to_enum(data.get("status"))
        message = data.get("message")
        super().set_system_status(status, message)
    
    # NOTE: in the middle of debugging, properly sends message but not received by invesalius
    # (need to run OnRobotConnect in the Tracker Tab class of preferences.py)
    def recover(self, recovery):
        if recovery == 'Restart Robot Connection':
            print("tried to recover")
            topic = 'Robot Recovery: Restart Robot Connection'
            asyncio.create_task(self.remote.send_message(topic, data={}))
        else:
            print(f"Error: Recovery method for '{recovery}' not implemented!")
    
    # This is done through the relay server, on_robot_health_update instead
    async def check_system(self):
        pass
    
    