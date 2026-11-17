"""Process supervisor for the NeuroPilot component stack.

Each component runs as its own child process (the controller hosts a
Qt/qasync event loop, the virtual robot a MuJoCo viewer — these cannot share
one process). The supervisor starts them in dependency order, waits for
readiness probes, multiplexes their output with role prefixes into one
terminal, and terminates everything on exit.
"""

import asyncio
import os
import sys

from . import config

# role -> (module to run as -m, extra argv)
COMPONENTS = {
    "relay": ("neuropilot.sim_relay", []),
    "nav": ("neuropilot.sim_nav", []),
    "robot": ("neuropilot.sim_robot", []),
    "controller": ("neuropilot.controller", []),
}

READY_LINE = "Connected"  # printed by sim_nav and sim_robot once registered


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
    while True:
        line = await component.process.stdout.readline()
        if not line:
            break
        text = line.decode(errors="replace").rstrip("\n")
        print(f"{component.prefix} {text}", flush=True)
        if component.wait_ready == "line" and READY_LINE in text:
            component.ready.set()


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
    print(f"[neuropilot] started {component.name} (pid {component.process.pid})", flush=True)
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
                    print(f"[neuropilot] {component.name} not started: {reason}",
                          flush=True)
                    component.skipped = True
                    continue

            try:
                pumps.append(await _start(component))
                started.append(component)
            except OSError as exc:
                print(f"[neuropilot] could not start {component.name}: {exc}",
                      flush=True)
                component.skipped = True
                if component.shutdown_on_exit:
                    startup_failed = True
                    break
                continue

            if component.wait_ready == "port":
                ok = await _wait_port_open(config.RELAY_HOST, config.RELAY_PORT,
                                           config.READINESS_TIMEOUT_S)
                if ok:
                    print(f"[neuropilot] {component.name} ready on "
                          f"{config.RELAY_HOST}:{config.RELAY_PORT}", flush=True)
                else:
                    print(f"[neuropilot] WARNING: {component.name} port not open "
                          f"after {config.READINESS_TIMEOUT_S}s — continuing", flush=True)
            elif component.wait_ready == "line":
                # Non-blocking: the clients reconnect on their own, so start
                # the next component immediately; log readiness when seen.
                async def _announce(component=component):
                    try:
                        await asyncio.wait_for(component.ready.wait(),
                                               timeout=config.READINESS_TIMEOUT_S)
                        print(f"[neuropilot] {component.name} ready", flush=True)
                    except asyncio.TimeoutError:
                        print(f"[neuropilot] WARNING: {component.name} not ready "
                              f"after {config.READINESS_TIMEOUT_S}s", flush=True)
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
                    print(f"[neuropilot] component exited: {critical} — "
                          "shutting down stack", flush=True)
                    break

                for component in components:
                    if (not component.shutdown_on_exit
                            and component.process is not None
                            and component.process.returncode is not None
                            and component.name not in reported_optional):
                        print(f"[neuropilot] {component.name} exited with code "
                              f"{component.process.returncode}; keeping the "
                              "stack alive", flush=True)
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
        print("[neuropilot] all components stopped", flush=True)


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


def real_stack(with_relay=False, invesalius=None):
    args = ["--real"] + (["--manage-relay"] if with_relay else [])
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


def real_controller(with_relay=False, invesalius=None):
    return real_stack(with_relay=with_relay, invesalius=invesalius)
