"""The Socket.IO relay as a managed system.

In real/manual/training mode the relay is the hub every peer connects to. This
class exposes it on the Connections page: it checks the port, can start the
production ``relay_server.py`` from ``TMS_ROBOT_CONTROL_PATH``, and can restart
a relay that NeuroPilot started. A relay that was already running is treated as
external and is never stopped by NeuroPilot.
"""

import asyncio
import atexit
import socket
import subprocess
import sys
import time
from pathlib import Path

from ... import config
from .system import System, SystemStatus


class RelaySystem(System):
    NAME = "Relay"
    DESCRIPTION = "Production Socket.IO relay"
    ERROR_RECOVERIES = {
        "Relay not running": "Start relay",
        "Relay stopped": "Restart relay",
        "Relay did not start": "Restart relay",
    }

    def __init__(self, update_control_panel_func=None, manage=False,
                 simulation=False):
        super().__init__(update_control_panel_func)
        self.host = config.RELAY_HOST
        self.port = int(config.RELAY_PORT)
        self.manage = bool(manage)
        self.simulation = simulation
        self.DESCRIPTION = "Simulated" if simulation else "Production"
        self.process = None
        self.owned = False
        self.failure_reason = ""
        self.log_handle = None
        self.log_path = Path(config.ROOT_FOLDER) / "relay.log"
        self._remote = self.host not in ("127.0.0.1", "localhost", "::1")
        if self.simulation:
            self.manage = False
        atexit.register(self.stop)

    # ── status ─────────────────────────────────────────────────────
    def _port_open(self):
        try:
            with socket.create_connection((self.host, self.port), timeout=0.4):
                return True
        except OSError:
            return False

    def _relay_script(self):
        path = (config.TMS_ROBOT_CONTROL_PATH or "").strip()
        if not path:
            return None
        script = Path(path) / "relay_server.py"
        return script if script.is_file() else None

    def _publish_details(self):
        self.set_details({
            "URL": f"http://{self.host}:{self.port}",
            "Mode": "Simulated" if self.simulation else "Production",
            "Managed": ("NeuroPilot" if self.owned else
                        ("Supervisor" if self.simulation else "External")),
            "PID": str(self.process.pid) if self.owned and self.process else "",
            "Log": str(self.log_path) if self.owned else "",
        })

    def _set_status(self, status, message=None):
        self._last_message = message
        self.set_system_status(status, message)

    def try_connect(self):
        """Check the port; start the relay only when NeuroPilot manages it."""
        self.failure_reason = ""
        self._publish_details()
        if self._port_open():
            self._set_status(SystemStatus.OK)
            return
        if self.simulation:
            self.failure_reason = "Simulated relay is not running"
            self._set_status(SystemStatus.ERROR, "Relay not running (supervisor)")
            return
        if self.manage and not self._remote:
            if self._start():
                self._set_status(SystemStatus.OK)
                return
            if not self.failure_reason:
                self.failure_reason = (
                    f"Relay did not start; see {self.log_path}")
            self._set_status(SystemStatus.ERROR, "Relay did not start")
            return
        path = (config.TMS_ROBOT_CONTROL_PATH or "").strip()
        if self._remote:
            self.failure_reason = (
                f"Relay {self.host}:{self.port} is not reachable")
            message = "Relay not running (remote host)"
        elif not path:
            self.failure_reason = (
                f"Relay {self.host}:{self.port} is not running and "
                "TMS_ROBOT_CONTROL_PATH is not configured")
            message = "Relay not running"
        else:
            self.failure_reason = (
                f"Relay {self.host}:{self.port} is not running; "
                f"start it or use --launch-relay")
            message = "Relay not running"
        self._set_status(SystemStatus.ERROR, message)

    async def check_system(self):
        if self._port_open():
            self._publish_details()
            self._set_status(SystemStatus.OK)
            return
        self._publish_details()
        if self.simulation:
            self._set_status(SystemStatus.ERROR, "Relay not running (supervisor)")
        elif self.owned:
            self._set_status(SystemStatus.ERROR, "Relay stopped")
        elif self._remote:
            self._set_status(SystemStatus.ERROR, "Relay not running (remote host)")
        else:
            self._set_status(SystemStatus.ERROR, "Relay not running")

    # ── process control ────────────────────────────────────────────
    def _start(self):
        """Start the production relay; return True once its port is open."""
        self.failure_reason = ""
        if self.simulation:
            return False
        if self._port_open():
            self.owned = False
            self._publish_details()
            return True
        if self._remote:
            self.failure_reason = (
                f"Relay {self.host}:{self.port} is configured as a remote "
                "host and is not reachable")
            return False
        script = self._relay_script()
        if script is None:
            raw = (config.TMS_ROBOT_CONTROL_PATH or "").strip()
            if raw:
                self.failure_reason = (
                    f"relay_server.py was not found under {raw}")
            else:
                self.failure_reason = "TMS_ROBOT_CONTROL_PATH is not configured"
            return False
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.log_handle is None:
                self.log_handle = self.log_path.open("a", encoding="utf-8")
            self.process = subprocess.Popen(
                [sys.executable, str(script), str(self.port)],
                cwd=str(script.parent),
                stdout=self.log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                # Detach the relay from the controller's process group so a
                # Ctrl+C in the terminal does not take the relay down with it.
                # POSIX-only: Python ignores this kwarg on Windows.
                start_new_session=True,
            )
            self.owned = True
            self._publish_details()
        except OSError as e:
            print(f"[RELAY] could not start {script}: {e}")
            self.failure_reason = (
                f"Could not start {script}: {e}; see {self.log_path}")
            self._close_log()
            return False

        deadline = time.monotonic() + min(15.0, max(5.0, config.READINESS_TIMEOUT_S))
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                print(f"[RELAY] relay_server.py exited with {self.process.returncode}")
                self.failure_reason = (
                    f"relay_server.py exited with code {self.process.returncode}; "
                    f"see {self.log_path}")
                self._close_log()
                return False
            if self._port_open():
                return True
            time.sleep(0.1)
        print("[RELAY] relay did not open its port in time")
        self.failure_reason = (
            f"relay_server.py did not open port {self.port}; see {self.log_path}")
        self._stop()
        return False

    def _stop(self):
        process = self.process
        self.process = None
        self.owned = False
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            except OSError:
                pass
        self._close_log()

    def _close_log(self):
        if self.log_handle is not None:
            try:
                self.log_handle.close()
            except OSError:
                pass
            self.log_handle = None

    def stop(self):
        """Terminate a relay started by this process, if any."""
        self._stop()

    def recover(self, recovery):
        """Start or restart the relay without blocking the Qt event loop."""
        if self.simulation:
            return

        async def restart():
            await asyncio.to_thread(self._stop)
            await asyncio.to_thread(self._start)
            await self.check_system()

        try:
            asyncio.get_running_loop().create_task(restart())
        except RuntimeError:
            self._stop()
            self._start()
            self.try_connect()
