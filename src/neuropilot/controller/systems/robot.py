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
        self.remote.register_handlers({
            'Robot to Pipeline: Health status' : self.on_robot_health_update,
        })
        
    def try_connect(self):
        # Since were connected through the relay server (which is not exclusive to the robot) there is not much to check here.
        pass
    
    async def on_robot_health_update(self, data):
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
    
    