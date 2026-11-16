import os

import magicpy as mp
from ..systems.system import SystemStatus, System
from ...lab_profile import STIMULATOR_PORT_DEFAULT, STIMULATOR_TTL_PORT_DEFAULT
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

    # Serial + TTL ports of the stimulator (Aachen used /dev/ttyS0 on Linux;
    # Windows defaults to COM3 / no TTL line, see lab_profile._serial_defaults).
    # Overridable from .env (Config tab: Stimulator → serial / TTL port).
    PORT = os.getenv("STIMULATOR_PORT", STIMULATOR_PORT_DEFAULT)
    TTL_PORT = os.getenv("STIMULATOR_TTL_PORT", STIMULATOR_TTL_PORT_DEFAULT)

    @staticmethod
    def _print_permission_help(error, port):
        """Explain the usual Linux serial-port permission failure once."""
        text = str(error).lower()
        if not (isinstance(error, PermissionError)
                or "permission denied" in text
                or "access is denied" in text):
            return
        print(f"Permission denied opening the stimulator port {port}.")
        print("Add your user to the dialout group, then log out and back in:")
        print("  sudo usermod -aG dialout $USER")
        print("For the current terminal only, run:")
        print("  newgrp dialout")
        print(f"Check access with: ls -l {port}")

    def try_connect(self):
        """Open the serial port (and the TTL port if the PC has one).

        Any failure leaves the system in ERROR with a message -- never in a
        state where the health loop later raises out of an unconnected
        device (that used to take the whole pipeline down).
        """
        self.stimulator = None
        self.avail = False
        try:
            self.stimulator = mp.MagVenture(self.PORT, ttl_port=self.TTL_PORT)
            self.stimulator.connect()
            self.avail = True
        except FileNotFoundError:
            print("Cannot open the TTL/parallel port; trying the serial port only.")
            print("The TTL port is optional. If you use it, check that the")
            print("parallel device exists and is accessible:")
            print(f"  sudo modprobe ppdev && ls -l {self.TTL_PORT}")
            try:
                self.stimulator = mp.MagVenture(self.PORT)
                self.stimulator.connect()
                self.avail = True
            except Exception as e:
                print(f"Cannot connect to the stimulator on {self.PORT}: {e}")
                self._print_permission_help(e, self.PORT)
                self.stimulator = None
        except serial.serialutil.SerialException as e:
            print(f"Cannot connect to serial port {self.PORT}: {e}")
            self._print_permission_help(e, self.PORT)
            self.stimulator = None
        except Exception as e:                  # magicpy raises a mixed bag
            print(f"Stimulator initialisation failed: {e}")
            self._print_permission_help(e, self.PORT)
            self.stimulator = None

        self.set_details({"Port": self.PORT, "TTL port": self.TTL_PORT,
                          "Connected": "yes" if self.avail else "no"})
        if not self.avail:
            super().set_system_status(SystemStatus.ERROR, 'No Connection')
        try:
            asyncio.create_task(self.check_system())
        except RuntimeError:
            pass                                # no loop yet (GUI-only code)
    
    async def check_system(self):
        loop = asyncio.get_running_loop()
        if self.stimulator is None:
            super().set_system_status(SystemStatus.ERROR, 'No Connection')
            return
        # run blocking call in a thread; an unplugged device raises a mix of
        # pyserial exceptions (PortNotOpenError is not a ValueError).
        try:
            info, error = await loop.run_in_executor(
                self._serial_executor, self.stimulator.get_status)
        except Exception as e:
            print(f"Cannot get status from stimulator: {e}")
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
        if self.stimulator is None:
            print("Stimulator not connected -- cannot arm.")
            return
        self._run_off_thread(self.stimulator.arm)

    def fire(self):
        if self.stimulator is None:
            print("Stimulator not connected -- pulse not delivered.")
            super().set_system_status(SystemStatus.ERROR, 'No Connection')
            return
        try:
            resp, error = self.stimulator.fire(get_response=True)   # Send TMS pulse and get stimulator response
        except Exception as e:
            print(f"Couldn't fire stimulator: {e}")
            super().set_system_status(SystemStatus.ERROR, 'No Connection')

    def disarm(self):
        if self.stimulator is None:
            return
        self._run_off_thread(self.stimulator.disarm)

    def set_amplitude(self, amplitude):
        if not 0 <= amplitude <= 100:
            raise ValueError(f"Amplitude must be between 0 and 100, got {amplitude}")
        if self.stimulator is None:
            return
        self._run_off_thread(self.stimulator.set_amplitude, amplitude)

    def set_waveform(self, waveform):
        if waveform not in ("Biphasic", "Monophasic"):
            raise ValueError(f"Unsupported pulse shape: {waveform}")
        if self.stimulator is None:
            return
        self._run_off_thread(self.stimulator.set_waveform, waveform)
