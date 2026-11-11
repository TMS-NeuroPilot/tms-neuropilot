import time
import asyncio
from ..systems.system import System, SystemStatus
import subprocess


class VirtualStimulator(System):
    NAME = "Virtual Stimulator"
    DESCRIPTION = "Simulated"

    # Matched with real Stimulator for UI safety
    ERROR_RECOVERIES = {
        'No Connection': None
    }

    def __init__(self, update_control_panel_func=None, fire_delay_s=0.02):
        super().__init__(update_control_panel_func=update_control_panel_func)
        self.avail = False  # Start false until try_connect is called
        self.armed = False
        self.amplitude = 0  # 0..100 (%MSO)
        self.waveform = "Biphasic"
        self.fire_delay_s = fire_delay_s

    def try_connect(self):
        print("[VirtualStimulator] Hardware mocked successfully. Connected.")
        self.avail = True
        self._publish_details()
        super().set_system_status(SystemStatus.OK)

    def _publish_details(self):
        """Mirror the real stimulator's details rows with simulation values."""
        self.set_details({
            "Model": "Simulated MagVenture",
            "Port": "none (virtual)",
            "Waveform": self.waveform,
            "Amplitude": f"{self.amplitude} % MSO",
            "Fire latency": f"{self.fire_delay_s * 1000:.0f} ms",
        })

    async def check_system(self):
        # Always healthy in simulation
        super().set_system_status(SystemStatus.OK)

    def recover(self, recovery: str):
        self.try_connect()

    def arm(self):
        if not self.avail:
            return
        self.armed = True
        print("[VirtualStimulator] Armed.")

    def disarm(self):
        self.armed = False
        print("[VirtualStimulator] Disarmed.")

    def set_amplitude(self, amplitude: int):
        assert 0 <= amplitude <= 100, "Amplitude must be between 0 and 100"
        self.amplitude = int(amplitude)
        self._publish_details()
        print(f"[VirtualStimulator] Amplitude set to {self.amplitude}%")

    def set_waveform(self, waveform: str):
        assert waveform in ["Biphasic", "Monophasic"]
        self.waveform = waveform
        self._publish_details()
        print(f"[VirtualStimulator] Waveform set to {self.waveform}")

    def fire(self):
        if not self.avail:
            return
        if not self.armed:
            self.armed = True

        time.sleep(self.fire_delay_s)  # emulate IO latency
        # --- SOUND LOGIC ---
        try:
            # Spawns a background process to play the sound without freezing the GUI
            subprocess.Popen(
                ['paplay', '/usr/share/sounds/freedesktop/stereo/dialog-warning.oga'],
                stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            # Fails silently if 'paplay' is missing on a different Linux machine
            pass
        # -------------------------------
        print(f"[VirtualStimulator] *** FIRED *** | Amp: {self.amplitude}%, Wave: {self.waveform}")