"""Real-EMG system driver.

This is the production EMG computer client for hardware sessions. It expects
this hardware chain on the EMG signal PC (default IP 192.168.1.2):

    Digitimer D360 amplifier -> CED 1401 data acquisition unit (Signal software)
        -> signal PC writes one tab-separated signal file per pulse
        -> Windows share \\\\192.168.1.2\\users\\neuro\\signal

This class polls that SMB share (smbprotocol): health checks verify the
session and the shared folder, and :meth:`EMGComputer.get_latest_emg_df`
reads the newest signal file (time column renamed to ``Time``) for the
MEP analysis. The simulated counterpart is ``systems/virtual_emg_computer*.py``
(the pipeline selects between them by the Simulation/Real mode).
"""

from smbprotocol.exceptions import SMBException
import smbclient
from ..systems.system import System, SystemStatus
import asyncio
import os
import time
import pandas as pd

class EMGComputer(System):
    """Health-checked client for the real EMG signal PC (CED 1401 + Digitimer D360
    setup, see the module docstring). Connection is via SMB to the signal share;
    override the credentials through the .env keys below."""

    # Defaults match the MPI lab setup; override via .env
    # (EMG_COMPUTER_IP / EMG_COMPUTER_USERNAME / EMG_COMPUTER_PASSWORD)
    # — read at instantiation, after load_dotenv().
    EMG_COMPUTER_IP_DEFAULT = "192.168.1.2"
    # EMG_OUTPUT_FOLDER_PATH = r"\\192.168.137.3\users\neuro\signal" # old config
    
    NAME = "EMG Computer"
    DESCRIPTION = "Real (CED 1401 / Signal, SMB)"
    
    ERROR_RECOVERIES = {
        'Could not connect to IP' : 'Try to reconnect',
    }
    
    def __init__(self, update_control_panel_func):
        super().__init__(update_control_panel_func=update_control_panel_func)
        self.EMG_COMPUTER_IP = os.getenv("EMG_COMPUTER_IP", self.EMG_COMPUTER_IP_DEFAULT)
        self.EMG_COMPUTER_USERNAME = os.getenv("EMG_COMPUTER_USERNAME", "neuro")
        # No password default: the share credential belongs in .env.
        self.EMG_COMPUTER_PASSWORD = os.getenv("EMG_COMPUTER_PASSWORD", "")
        self.EMG_OUTPUT_FOLDER_PATH = f"\\{self.EMG_COMPUTER_IP}\\users\\neuro\\signal"
        # One SMB round trip every few seconds is enough to notice a share
        # that went away; the health loop runs at ~2 Hz.
        self.probe_interval_s = float(os.getenv("EMG_PROBE_INTERVAL_S", "5"))
        # smbclient defaults to a 60 s initial connection timeout. The
        # controller still constructs the systems before it shows the GUI, so
        # an offline EMG PC would otherwise freeze startup for a full minute.
        self.connect_timeout_s = max(
            0.5, float(os.getenv("EMG_CONNECT_TIMEOUT_S", "3")))
        self._last_probe = 0.0
    
    def _publish_details(self):
        channels = [c.strip() for c in
                    os.getenv("EMG_CHANNELS", "ADC 0,ADC 1,ADC 2").split(",")
                    if c.strip()]
        self.set_details({
            "Transport": "SMB2 (Signal share)",
            "Host": self.EMG_COMPUTER_IP,
            "Share": "\\users\\neuro\\signal",
            "User": self.EMG_COMPUTER_USERNAME,
            "Channels": f"{', '.join(channels)} ({len(channels)})",
        })

    def try_connect(self):
        self._publish_details()
        try:
            smbclient.register_session(
                self.EMG_COMPUTER_IP,
                username=self.EMG_COMPUTER_USERNAME,
                password=self.EMG_COMPUTER_PASSWORD,
                connection_timeout=self.connect_timeout_s,
            )
            super().set_system_status(SystemStatus.OK)
        except (ValueError, SMBException, ConnectionRefusedError, OSError, TimeoutError) as e:
            print(f"Could not connect to EMG computer at {self.EMG_COMPUTER_IP}: {e}")
            super().set_system_status(SystemStatus.ERROR, 'Could not connect to IP')
    
    def recover(self, recovery):
        self.try_connect()
    
    async def check_system(self):
        """Poll the share so a connection lost mid-session turns red.

        The probe is throttled (it costs a round trip) and runs in a thread so
        it can never block the event loop; failures always end in ERROR, never
        in an exception (the health loop would take the pipeline down).
        """
        now = time.monotonic()
        forced = bool(self.recovery_queue)
        while self.recovery_queue:
            self.recovery_queue.popleft()
        if not forced and now - getattr(self, "_last_probe", 0.0) < self.probe_interval_s:
            return
        self._last_probe = now
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: list(smbclient.listdir(self.EMG_OUTPUT_FOLDER_PATH))),
                timeout=5.0)
        except Exception as e:
            if self.status is not SystemStatus.ERROR:
                print(f"EMG share unavailable: {type(e).__name__}: {e}")
            super().set_system_status(SystemStatus.ERROR, 'Could not connect to IP')
            return
        if self.status is SystemStatus.ERROR:
            print("EMG share reachable again.")
        super().set_system_status(SystemStatus.OK)

    def signal_files(self):
        """Sorted list of the signal files (names only) on the share.

        Used as a snapshot before a pulse: the pulse's own file must not be
        one that was already there, otherwise the previous sweep would be
        paired with the new placement.
        """
        folder = self.EMG_OUTPUT_FOLDER_PATH
        names = []
        for name in smbclient.listdir(folder):
            path = os.path.join(folder, name).replace("/", "\\")
            try:
                if not smbclient.path.isfile(path):
                    continue
            except (OSError, SMBException):
                continue
            names.append(name)
        return sorted(names)

    def get_latest_emg_df(self, idx=None, e_field_for_mep=None, after=None):
        """Newest signal file as a DataFrame.

        ``e_field_for_mep`` is accepted for interface parity with the virtual
        EMG (the controller always passes it); the real acquisition does not
        need it — the field is only used to synthesise MEPs in simulation.

        ``after`` is the file list snapshotted *before* the pulse: only a file
        that appeared since then is a candidate, so a slow Signal PC cannot
        hand back the previous pulse's sweep (which would look plausible and
        silently corrupt the map).  Returns None when nothing new is there.
        """
        files = self.signal_files()
        if after is not None:
            known = set(after)
            files = [name for name in files if name not in known]
            if not files:
                return None
        if not files:
            return None
        if idx is None:
            idx = -1
        last_file_path = os.path.join(self.EMG_OUTPUT_FOLDER_PATH, files[idx]).replace("/", "\\")

        with smbclient.open_file(last_file_path, mode='r') as f:
            # The file is tab separated, not comma separated and the quotechar is "" not ''
            df = pd.read_csv(f, sep='\t', quotechar='"')

        # Give the time column a nicer name
        df = df.rename(columns={"s": "Time"})
        
        return df
