"""Process supervisor for the TMS NeuroPilot component stack.

Each component runs as its own child process (the controller hosts a
Qt/qasync event loop, the virtual robot a MuJoCo viewer — these cannot share
one process). The supervisor starts them in dependency order, waits for
readiness probes, multiplexes their output with role prefixes into one
terminal, and terminates everything on exit.
"""

import asyncio
import os
import re
import shutil
import signal
import sys
import time
from pathlib import Path

from . import config

# role -> (module to run as -m, extra argv)
COMPONENTS = {
    "relay": ("neuropilot.sim_relay", []),
    "nav": ("neuropilot.sim_nav", []),
    "robot": ("neuropilot.sim_robot", []),
    "controller": ("neuropilot.controller", []),
}

READY_LINE = "Connected"  # printed by sim_nav and sim_robot once registered

# Only the label inside the square brackets is coloured.  The rest of each log
# line is left in the terminal's normal colour so user output and tracebacks
# stay readable.
_LOG_COLORS = {
    "neuropilot": "1;36",   # bright cyan
    "controller": "32",     # green
    "invesalius": "35",     # magenta
    "relay": "36",          # cyan
    "nav": "33",            # yellow
    "robot": "34",          # blue
}


def _color_enabled():
    if "NO_COLOR" in os.environ:
        return False
    forced = os.environ.get("FORCE_COLOR")
    if forced is not None:
        return forced.lower() not in ("0", "false", "no")
    return sys.stdout.isatty()


def _label(name):
    if not _color_enabled():
        return f"[{name}]"
    color = _LOG_COLORS.get(name, "37")
    return f"[\033[{color}m{name}\033[0m]"


def _log(name, message):
    _LIVE.finish()
    print(f"{_label(name)} {message}", flush=True)


# GTK emits these cosmetic layout warnings when wxPython asks a control to be
# smaller than the active GTK theme's minimum. They originate inside the
# InVesalius GUI and are not actionable from the supervisor.
_GTK_LAYOUT_NOISE = re.compile(
    r"Gtk-(?:WARNING|CRITICAL).*?"
    r"(?:for_size smaller than min-size|"
    r"Negative content (?:width|height)|"
    r"gtk_widget_set_size_request)"
)
_PETSC_SHUTDOWN_NOISE = re.compile(
    r"(?:\[0\]PETSC ERROR: Caught signal number 15 Terminate|"
    r"PETSC ERROR: Try option -start_in_debugger|"
    r"PETSC ERROR: or see https://petsc\.org|"
    r"PETSC ERROR: configure using --with-debugging=yes|"
    r"PETSC ERROR: to get more information about the crash|"
    r"application called MPI_Abort\(MPI_WORLD, 59\)|"
    r"PMIU_write error|"
    r"system msg for write_line failure)"
)


def _drop_output_line(source, text):
    """Drop known GTK layout and PETSc shutdown noise."""
    if _GTK_LAYOUT_NOISE.search(text):
        return True
    if _PETSC_SHUTDOWN_NOISE.search(text):
        return True
    if source == "controller" and text.strip() == ":":
        return True
    if source == "invesalius" and not text.strip():
        return True
    return False


_FORWARD_RE = re.compile(
    r"^\[[^\]]+\]\[SIM RELAY\] "
    r"(?P<label>Forwarding .+?): (?P<payload>\{.*\})$"
)
_TOPIC_RE = re.compile(r"['\"]topic['\"]:\s*['\"]([^'\"]+)['\"]")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _relay_forward_key(text):
    match = _FORWARD_RE.match(text)
    if match is None:
        return None
    topic = _TOPIC_RE.search(match.group("payload"))
    if topic is None:
        return None
    return match.group("label"), topic.group(1)


def _with_count(text, count):
    if count <= 1:
        return text
    marker = ": {"
    index = text.find(marker)
    if index >= 0:
        return f"{text[:index]} x{count}{text[index:]}"
    return f"{text} x{count}"


def _fit_line(line, width=None):
    if width is None:
        width = shutil.get_terminal_size((120, 24)).columns
    prefix, separator, message = line.partition(" ")
    visible_prefix = len(_ANSI_RE.sub("", prefix))
    available = max(20, width - visible_prefix - 1)
    if len(_ANSI_RE.sub("", message)) <= available:
        return line
    return f"{prefix}{separator}{message[:available - 1]}…"


class _LiveOutput:
    """Coalesce repeated relay-forwarding lines.

    On a TTY the first line is written in place and later repeats overwrite it.
    Redirected output is held and emitted once when the burst ends.
    """

    def __init__(self, stream=None, is_tty=None):
        self._stream = stream
        self._is_tty = is_tty
        self.key = None
        self.name = "relay"
        self.text = ""
        self.count = 0
        self.visible = False

    @property
    def stream(self):
        return self._stream if self._stream is not None else sys.stdout

    def _tty(self):
        if self._is_tty is not None:
            return self._is_tty
        try:
            return self.stream.isatty()
        except Exception:
            return False

    def _write(self, text):
        self.stream.write(text)
        self.stream.flush()

    def _line(self, name):
        return _fit_line(f"{_label(name)} "
                         f"{_with_count(self.text, self.count)}")

    def feed(self, name, key, text):
        if self.key == key:
            self.count += 1
            self.text = text
            if self._tty():
                self._write("\r\033[2K" + self._line(name))
            return
        self.finish()
        self.name = name
        self.key = key
        self.text = text
        self.count = 1
        if self._tty():
            self._write(self._line(name))
            self.visible = True

    def finish(self):
        if self.key is None:
            return
        if self._tty():
            if self.visible:
                self._write("\n")
        else:
            self._write(self._line(self.name) + "\n")
        self.key = None
        self.text = ""
        self.count = 0
        self.visible = False


# The relay's current burst is shared by every pump and supervisor log call.
_LIVE = _LiveOutput()


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _is_relay_process(pid):
    """Check /proc so a recycled PID is never killed by mistake."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return True  # no /proc (non-Linux): trust the owned PID file
    return any("relay_server.py" in part for part in
               raw.decode(errors="replace").split("\0"))


def _stop_owned_relay():
    """Stop a relay recorded by RelaySystem if its controller crashed."""
    pid_path = Path(config.ROOT_FOLDER) / "relay.pid"
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if not _pid_alive(pid):
        try:
            pid_path.unlink()
        except OSError:
            pass
        return None
    if not _is_relay_process(pid):
        try:
            pid_path.unlink()
        except OSError:
            pass
        return None
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError:
        return None
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and _pid_alive(pid):
        time.sleep(0.1)
    if _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        pid_path.unlink()
    except OSError:
        pass
    return pid


class Component:
    def __init__(self, name, module, args, wait_ready, log_prefix=None, cwd=None,
                 executable=None, wait_for_port=False, shutdown_on_exit=True):
        self.name = name
        self.module = module
        self.args = args
        self.wait_ready = wait_ready  # None | 'port' | 'line'
        self.prefix = log_prefix or f"[{name}]"
        self.cwd = cwd  # None -> the component's own package directory
        self.executable = executable
        self.wait_for_port = wait_for_port
        # Optional children (InVesalius) may exit without taking the controller
        # and relay down with them.
        self.shutdown_on_exit = shutdown_on_exit
        self.process = None
        self.skipped = False
        self.ready = asyncio.Event()

    def argv(self):
        executable = self.executable or sys.executable
        if self.module:
            return [executable, "-m", self.module, *self.args]
        return [executable, *self.args]


def _child_env():
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"  # readiness probes depend on seeing lines promptly
    env.setdefault("ROOT_FOLDER", config.ROOT_FOLDER)
    if config.PYGLFW_LIBRARY:
        env.setdefault("PYGLFW_LIBRARY", config.PYGLFW_LIBRARY)
    return env


async def _wait_port_open(host, port, timeout, abort=None):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if abort is not None and abort():
            return False
        try:
            _, writer = await asyncio.open_connection(host, port)
            writer.close()
            return True
        except OSError:
            await asyncio.sleep(0.25)
    return False


async def _pump(component):
    """Read the child's stdout line by line, prefix and forward it."""
    assert component.process.stdout is not None
    try:
        while True:
            line = await component.process.stdout.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip("\n")
            if _drop_output_line(component.name, text):
                continue
            key = _relay_forward_key(text)
            if key is not None:
                _LIVE.feed(component.name, key, text)
            else:
                _LIVE.finish()
                print(f"{_label(component.name)} {text}", flush=True)
            if component.wait_ready == "line" and READY_LINE in text:
                component.ready.set()
    finally:
        _LIVE.finish()


async def _start(component):
    if component.cwd is not None:
        cwd = component.cwd
    elif component.module:
        cwd = os.path.join(config.REPO_ROOT, "src", *component.module.split("."))
    else:
        cwd = str(config.REPO_ROOT)
    component.process = await asyncio.create_subprocess_exec(
        *component.argv(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=_child_env(),
        cwd=cwd,
    )
    _log("neuropilot", f"started {component.name} "
                        f"(pid {component.process.pid})")
    pump = asyncio.create_task(_pump(component))
    return pump


async def _stop(component):
    if component.process and component.process.returncode is None:
        try:
            component.process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(component.process.wait(), timeout=5)
        except asyncio.TimeoutError:
            component.process.kill()


async def run_stack(components, timeout=None):
    """Start components in order, wait until all exit or one dies.

    `components` is an ordered list of Component objects. Readiness handling:
    - 'port': relay — wait until RELAY_PORT accepts connections
    - 'line': nav/robot — wait until READY_LINE appears in their output
    - None:   controller — no probe, just keep it alive

    A component with ``shutdown_on_exit=False`` is optional.  InVesalius uses
    that: if it fails to start or closes during a session, the controller and
    relay stay alive and the reason is printed.
    """
    pumps = []
    started = []
    startup_failed = False
    reported_optional = set()
    try:
        for component in components:
            if component.wait_for_port:
                def _previous_died():
                    return any(c.process is not None
                               and c.process.returncode is not None
                               for c in started)

                ok = await _wait_port_open(
                    config.RELAY_HOST, config.RELAY_PORT,
                    config.READINESS_TIMEOUT_S, abort=_previous_died)
                if not ok:
                    if _previous_died():
                        reason = ("the controller exited before the relay "
                                  "became reachable")
                    else:
                        reason = (f"relay {config.RELAY_HOST}:"
                                  f"{config.RELAY_PORT} is not reachable "
                                  f"after {config.READINESS_TIMEOUT_S:.0f}s")
                    _log("neuropilot",
                         f"{component.name} not started: {reason}")
                    component.skipped = True
                    continue

            if component.name == "invesalius":
                source = (component.cwd or component.executable
                          or "configured launcher")
                _log("invesalius", f"start InVesalius from {source}")

            try:
                pumps.append(await _start(component))
                started.append(component)
            except OSError as exc:
                _log("neuropilot",
                     f"could not start {component.name}: {exc}")
                component.skipped = True
                if component.shutdown_on_exit:
                    startup_failed = True
                    break
                continue

            if component.wait_ready == "port":
                ok = await _wait_port_open(config.RELAY_HOST, config.RELAY_PORT,
                                           config.READINESS_TIMEOUT_S)
                if ok:
                    _log("neuropilot",
                         f"{component.name} ready on "
                         f"{config.RELAY_HOST}:{config.RELAY_PORT}")
                else:
                    _log("neuropilot",
                         f"WARNING: {component.name} port not open after "
                         f"{config.READINESS_TIMEOUT_S}s — continuing")
            elif component.wait_ready == "line":
                # Non-blocking: the clients reconnect on their own, so start
                # the next component immediately; log readiness when seen.
                async def _announce(component=component):
                    try:
                        await asyncio.wait_for(component.ready.wait(),
                                               timeout=config.READINESS_TIMEOUT_S)
                        _log("neuropilot", f"{component.name} ready")
                    except asyncio.TimeoutError:
                        _log("neuropilot",
                             f"WARNING: {component.name} not ready after "
                             f"{config.READINESS_TIMEOUT_S}s")
                asyncio.create_task(_announce())

        # Wait until every child has exited, or a critical child exits.  The
        # controller is the user-facing component: closing its window must
        # stop the relay and the virtual components, even with exit code 0.
        if not startup_failed:
            while True:
                critical = [
                    (c.name, c.process.returncode)
                    for c in components
                    if c.shutdown_on_exit and c.process is not None
                    and c.process.returncode is not None
                ]
                if critical:
                    _log("neuropilot",
                         f"component exited: {critical} — shutting down stack")
                    break

                for component in components:
                    if (not component.shutdown_on_exit
                            and component.process is not None
                            and component.process.returncode is not None
                            and component.name not in reported_optional):
                        _log("neuropilot",
                             f"{component.name} exited with code "
                             f"{component.process.returncode}; keeping the "
                             "stack alive")
                        reported_optional.add(component.name)

                if all(
                    component.skipped
                    or (component.process is not None
                        and component.process.returncode is not None)
                    for component in components
                ):
                    break
                await asyncio.sleep(0.5)
    finally:
        for component in components:
            await _stop(component)
        stopped_relay = _stop_owned_relay()
        if stopped_relay is not None:
            _log("neuropilot", f"stopped owned relay (pid {stopped_relay})")
        _log("neuropilot", "all components stopped")


def sim_stack(selected=None):
    """Ordered Component list for the simulated stack."""
    wanted = set(selected or COMPONENTS)
    order = ["relay", "nav", "robot", "controller"]
    specs = {
        "relay": Component("relay", *COMPONENTS["relay"], wait_ready="port"),
        "nav": Component("nav", *COMPONENTS["nav"], wait_ready="line"),
        "robot": Component("robot", *COMPONENTS["robot"], wait_ready="line"),
        "controller": Component("controller", "neuropilot.controller",
                                ["--sim"], wait_ready=None),
    }
    return [specs[name] for name in order if name in wanted]


def controller_with_dialog():
    """Controller only; its own mode-selection dialog appears."""
    return [Component("controller", "neuropilot.controller", [], wait_ready=None)]


def invesalius_component(spec):
    """Build the optional InVesalius child from a launcher spec."""
    if getattr(spec, "external", False):
        raise ValueError("external InVesalius must not be launched")
    host = config.RELAY_HOST
    if host in ("", "0.0.0.0", "::"):
        host = "127.0.0.1"
    argv = spec.argv(host, config.RELAY_PORT)
    return Component(
        "invesalius",
        None,
        argv[1:],
        wait_ready=None,
        executable=argv[0],
        cwd=str(spec.checkout) if spec.checkout is not None else None,
        wait_for_port=True,
        shutdown_on_exit=False,
    )


def _with_invesalius(components, invesalius):
    if invesalius is not None:
        components.append(invesalius_component(invesalius))
    return components


def robo_stack(with_relay=False, invesalius=None):
    args = ["--robo"] + (["--manage-relay"] if with_relay else [])
    return _with_invesalius([
        Component("controller", "neuropilot.controller", args,
                  wait_ready=None)
    ], invesalius)


def manual_stack(with_relay=False, invesalius=None):
    """Manual mode: real hardware, no robot (the operator moves the coil)."""
    args = ["--manual"] + (["--manage-relay"] if with_relay else [])
    return _with_invesalius([
        Component("controller", "neuropilot.controller", args,
                  wait_ready=None)
    ], invesalius)


def training_stack(with_relay=False, invesalius=None):
    """Training: real stimulator and navigation, virtual EMG, no robot."""
    args = ["--training"] + (["--manage-relay"] if with_relay else [])
    return _with_invesalius([
        Component("controller", "neuropilot.controller", args,
                  wait_ready=None)
    ], invesalius)


def robo_controller(with_relay=False, invesalius=None):
    return robo_stack(with_relay=with_relay, invesalius=invesalius)
