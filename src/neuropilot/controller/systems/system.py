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
    # Human-readable description of the concrete hardware/backend shown in
    # the Connections page ("Stimulator — Simulated", ...). Subclasses that
    # implement a specific device set this; None falls back to NAME.
    DESCRIPTION = None

    def __init__(self, update_control_panel_func=None):
        self.status = SystemStatus.NAN
        self.update_control_panel_func = update_control_panel_func
        self.recovery_queue = deque()
        # Ordered label/value pairs describing the concrete connection
        # (device model, serial, host, channels ...), shown on the
        # Connections page next to the status card.
        self.details = {}

    def set_details(self, details):
        """Publish connection details; empty values are dropped and an
        unchanged dict is ignored so the 1 Hz health loop does not repaint."""
        details = {str(k): str(v) for k, v in (details or {}).items()
                   if v is not None and str(v).strip()}
        if details == self.details:
            return
        self.details = details
        if self.update_control_panel_func:
            # status=None tells the panel this is a details-only update.
            self.update_control_panel_func(self, None, None, details=details)
    
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