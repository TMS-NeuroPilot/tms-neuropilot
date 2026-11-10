from enum import Enum, auto
from abc import ABC, abstractmethod
from collections import deque

class SystemStatus(Enum):
    NAN = auto()
    OK = auto()
    ERROR = auto()
    
    def str_to_enum(string):
        if string.lower() == "nan":
            return SystemStatus.NAN
        elif string.lower() == "ok":
            return SystemStatus.OK
        elif string.lower() == "error":
            return SystemStatus.ERROR
        else:
            print(f"Error: Could not match '{string}' to SystemStatus enum!")
        
class System(ABC):
    def __init__(self, update_control_panel_func=None):
        self.status = SystemStatus.NAN
        self.update_control_panel_func = update_control_panel_func
        self.recovery_queue = deque()
    
    def __init_subclass__(cls):
        super().__init_subclass__()
        if not hasattr(cls, 'NAME'):
            raise TypeError(f"{cls.__name__} must define an 'ERROR_RECOVERIES' class variable")
        if not hasattr(cls, 'ERROR_RECOVERIES'):
            raise TypeError(f"{cls.__name__} must define an 'ERROR_RECOVERIES' class variable")

    @abstractmethod
    def try_connect(self):
        pass

    @abstractmethod
    def recover(self, recovery: str):
        """
        This method attempts to recover the system according to the given recovery command sent. The method is called by the control
        panel, when the player presses the recovery button with the button text specifying the recovery command.
        
        The recovery command is specified by the value string in the ERROR_RECOVERIES of this class, given as response to the specified
        error key.

        Parameters
        ----------
        recovery : string
            The recovery command to act upon.

        Returns
        -------
        None
        """
        pass
    
    def set_system_status(self, status, error_message = None):
        """
        Sets the status of the system.

        Parameters
        ----------
        status : SystemStatus
            The new status of the system
        error_message : string
            Message to be applied informing the system what error it is.
            Expected to match a key in the ERROR_RECOVERIES dict.

        Returns
        -------
        None
        """
        self.status = status
        if self.update_control_panel_func:
            self.update_control_panel_func(self, status, error_message)
    
    @abstractmethod
    async def check_system(self):
        """
        Asynchronously does a health check of the system, and sets the system status accordingly.

        Returns
        -------
        None
        """
        pass
    
    def is_error_state(self):
        """
        Asynchronously does a health check of the system, and sets the system status accordingly.

        Returns
        -------
        bool
            True if the systemstatus is not OK, False otherwise. Called by the algorithm to see if system is OK.
        """
        return self.status != SystemStatus.OK