import os

import magicpy as mp
from ..systems.system import SystemStatus, System
import asyncio
import serial
from concurrent.futures import ThreadPoolExecutor

class Stimulator(System):
    NAME = "Stimulator"
    DESCRIPTION = "Real (MagVenture via magicpy)"
    ERROR_RECOVERIES = {
        'No Connection' : None
    }

    def __init__(self, update_control_panel_func):
        super().__init__(update_control_panel_func=update_control_panel_func)
        self.avail = False
        # magicpy serial I/O is blocking; a single dedicated worker serializes
        # the commands and keeps the asyncio/Qt event loop responsive.
        self._serial_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stimulator")

    def _run_off_thread(self, fn, *args):
        """Run a blocking magicpy call on the serial worker thread."""
        def _worker():
            try:
                fn(*args)
            except Exception as e:
                print(f"Stimulator error in {getattr(fn, '__name__', fn)}: {e}")
        self._serial_executor.submit(_worker)

    # Serial + TTL ports of the stimulator (Aachen used /dev/ttyS0).
    # Overridable from .env (Config tab: Stimulator → serial / TTL port).
    PORT = os.getenv("STIMULATOR_PORT", "/dev/ttyS1")
    TTL_PORT = os.getenv("STIMULATOR_TTL_PORT", "/dev/parport0")

    def try_connect(self):
        try:
            self.stimulator = mp.MagVenture(self.PORT, ttl_port=self.TTL_PORT)  ## pavian
            self.stimulator.connect()
            self.avail = True
        except FileNotFoundError:
            print(f"Cannot connect to parallel port. ")
            self.stimulator = mp.MagVenture(self.PORT)  ## pavian
        except serial.serialutil.SerialException:
            print(f"Cannot connect to serial port.")
        self.set_details({"Port": self.PORT, "TTL port": self.TTL_PORT})
        asyncio.create_task(self.check_system())
    
    async def check_system(self):
        loop = asyncio.get_running_loop()
        # run blocking call in a thread
        try:
            info, error = await loop.run_in_executor(
                self._serial_executor, self.stimulator.get_status)
        except ValueError as e:
            print("Cannot get status from stimulator.")
            print(e)
            super().set_system_status(SystemStatus.ERROR, 'No Connection')
            return

        if error == 1:
            super().set_system_status(SystemStatus.ERROR, 'No Connection')
            return

        # get_status() reports the device's own identity: model, serial
        # number, coil type, waveform and the coil temperature.
        temperature = info.get('Temperature')
        self.set_details({
            "Model": info.get('Model'),
            "Serial no.": info.get('SerialNo'),
            "Coil": info.get('coilTypeNo'),
            "Waveform": info.get('Waveform'),
            "Temperature": None if temperature is None else f"{temperature} °C",
        })
        super().set_system_status(SystemStatus.OK)
    
    def recover(self, recovery):
        # No software recoveries implemented yet
        pass
    
    def arm(self):
        self._run_off_thread(self.stimulator.arm)

    def fire(self):
        try:
            resp, error = self.stimulator.fire(get_response=True)   # Send TMS pulse and get stimulator response
        except Exception as e:
            print("Couldn't fire stimulator.")
            print(e)

    def disarm(self):
        self._run_off_thread(self.stimulator.disarm)

    def set_amplitude(self, amplitude):
        assert 0 <= amplitude <= 100, f"Amplitude must be between 0 and 100"
        self._run_off_thread(self.stimulator.set_amplitude, amplitude)

    def set_waveform(self, waveform):
        assert waveform in ['Biphasic','Monophasic']
        self._run_off_thread(self.stimulator.set_waveform, waveform)
