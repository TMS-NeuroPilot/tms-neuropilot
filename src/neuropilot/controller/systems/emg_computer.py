from smbprotocol.exceptions import SMBException
import smbclient
from ..systems.system import System, SystemStatus
import asyncio
import os
import pandas as pd

class EMGComputer(System):
    # Cluster defaults; override via .env (EMG_COMPUTER_IP / USERNAME / PASSWORD)
    # — read at instantiation, after load_dotenv().
    EMG_COMPUTER_IP_DEFAULT = "192.168.1.2"
    # EMG_OUTPUT_FOLDER_PATH = r"\\192.168.137.3\users\neuro\signal" # old config
    
    NAME = "EMG Computer"
    
    ERROR_RECOVERIES = {
        'Could not connect to IP' : 'Try to reconnect',
    }
    
    def __init__(self, update_control_panel_func):
        super().__init__(update_control_panel_func=update_control_panel_func)
        self.EMG_COMPUTER_IP = os.getenv("EMG_COMPUTER_IP", self.EMG_COMPUTER_IP_DEFAULT)
        self.EMG_COMPUTER_USERNAME = os.getenv("EMG_COMPUTER_USERNAME", "neuro")
        self.EMG_COMPUTER_PASSWORD = os.getenv("EMG_COMPUTER_PASSWORD", "")
        self.EMG_OUTPUT_FOLDER_PATH = f"\\{self.EMG_COMPUTER_IP}\\users\\neuro\\signal"
    
    def try_connect(self):
        try:
            smbclient.register_session(self.EMG_COMPUTER_IP, username=self.EMG_COMPUTER_USERNAME, password=self.EMG_COMPUTER_PASSWORD) # smbclient is a singleton, so no need for "self."
            super().set_system_status(SystemStatus.OK)
        except (ValueError, SMBException, ConnectionRefusedError, OSError, TimeoutError) as e:
            print(f"Could not connect to EMG computer at {self.EMG_COMPUTER_IP}: {e}")
            super().set_system_status(SystemStatus.ERROR, 'Could not connect to IP')
    
    def recover(self, recovery):
        self.try_connect()
    
    async def check_system(self):
        if self.recovery_queue:
            recovery = self.recovery_queue.popleft()
            if recovery == 'Try to connect':
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(lambda: list(smbclient.listdir(self.EMG_OUTPUT_FOLDER_PATH))),
                        timeout=5.0
                    )
                    super().set_system_status(SystemStatus.OK)
                except (ValueError, asyncio.TimeoutError, SMBException):
                    super().set_system_status(SystemStatus.ERROR, 'Could not connect to IP')
            else:
                print(f"Error: Recovery method '{recovery}' for system '{self.NAME}' not implemented!")
        
    
    def get_latest_emg_df(self, idx=None):
        if idx is None:
            idx = -1
        files = list(smbclient.listdir(self.EMG_OUTPUT_FOLDER_PATH))
        files.sort()
        last_file_path = os.path.join(self.EMG_OUTPUT_FOLDER_PATH, files[idx]).replace("/", "\\")
        #file_paths = []
        #for f in files:
        #    full_path = os.path.join(self.EMG_OUTPUT_FOLDER_PATH, f).replace("/", "\\")
        #    if smbclient.path.isfile(full_path):
        #        file_paths.append((f, full_path))
        #file_paths.sort(key=lambda x: x[0])
        #_, last_file_path = file_paths[-1]

        with smbclient.open_file(last_file_path, mode='r') as f:
            # The file is tab separated, not comma separated and the quotechar is "" not ''
            df = pd.read_csv(f, sep='\t', quotechar='"')

        # Give the time column a nicer name
        df = df.rename(columns={"s": "Time"})
        
        return df
