"""Controller entry point: wires the GUI, the pipeline controller and the
relay connection together and runs the asyncio/Qt event loop.

Launched as ``python -m neuropilot.controller`` (or via the ``neuropilot``
launcher: ``neuropilot controller --sim|--real``; the supervisor starts it
the same way for simulated stacks).

Flow:
    1. ``run()`` parses ``--sim``/``--real`` (or shows the mode selection
       dialog) and builds the QApplication.
    2. ``main()`` creates the relay ``Remote`` (simulated or real) from the
       optional positional ``[host] [port]`` arguments (default
       ``127.0.0.1 5000``), optionally shows the control panel
       (``ENABLE_HEALTH_CHECK_AND_CONTROL_PANEL=true`` in ``.env``), builds
       the :class:`~neuropilot.controller.pipeline_controller.PipelineController`
       and connects to the relay server.
    3. The pipeline (algorithm + health checks) runs as a background task
       while the Qt/asyncio loop keeps the GUI alive.

Everything runs in a single-threaded event loop. qasync bridges Qt and
asyncio when the GUI is enabled; without the GUI, plain asyncio is used.
No callback may block — see the asyncio notes in the repository docs.
"""

import asyncio
import logging
import numpy as np
from .pipeline_controller import PipelineController
import sys
from .control_panel import MainWindow
from qasync import QEventLoop, asyncSlot
from PyQt5.QtWidgets import QApplication, QDialog
from PyQt5.QtGui import QIcon
from . import experiment_mode as windowmode
import qasync
from dotenv import load_dotenv
import os

# Global QApplication; created in run(), used by main() to attach the
# control panel window.
app = None


def get_command_line_arguments():
    """Extract the relay host/port from positional command line arguments.

    Accepts ``[host] [port]``, ``[port]`` or nothing (defaults
    ``127.0.0.1:5000``). Option flags such as ``--sim``/``--real`` are
    ignored here — they are consumed by :func:`run`.
    """
    default_host = '127.0.0.1'
    default_port = 5000

    # Ignore option flags (--sim/--real); only positional host/port remain.
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(positional) == 2:
        host = positional[0]
        port = int(positional[1])
    elif len(positional) == 1:
        host = default_host
        port = int(positional[0])
    else:
        host = default_host
        port = default_port

    return host, port

async def main(enable_health_check_and_control_panel, simulation):
    """Build all components and keep the event loop alive.

    Creates the relay ``Remote`` (simulated or real variant, depending on
    ``simulation``), the control panel window (if enabled) and the
    ``PipelineController``, connects to the relay server and finally starts
    the pipeline as a background task. The trailing sleep loop keeps the
    coroutine alive; Qt event processing continues in parallel through the
    qasync integration.
    """
    # Configure logging.
    np.set_printoptions(formatter={'float': '{:0.1f}'.format})

    if simulation:
        from .sim_remote_connection import Remote
    else:
        from .remote_connection import Remote

    # Create the relay connection from the optional positional host/port.
    host, port = get_command_line_arguments()
    url = f'http://{host}:{port}'
    remote = Remote(url)

    # Control panel (only when ENABLE_HEALTH_CHECK_AND_CONTROL_PANEL=true).
    if enable_health_check_and_control_panel:
        # The control panel is shown by the PipelineController once it is
        # ready, not here.
        app.window2 = MainWindow(simulation=simulation)
        # Otherwise the window becomes transparent frozen while the controller initializes
        await asyncio.sleep(0.1)

    # The controller tracks whether health checks and the control panel are
    # active via `control_panel is not None`.
    controller = PipelineController(remote=remote,
                                    control_panel=app.window2 if enable_health_check_and_control_panel else None,simulation=simulation)
    controller.register_remote_handlers()
    if enable_health_check_and_control_panel:
        app.window2.set_controller(controller)

    # With everything prepped we connect to the relay server.
    await remote.connect()

    # Run the algorithm and health checks (if enabled). create_task runs it
    # in parallel to this coroutine instead of in sequence.
    asyncio.create_task(run_pipeline(controller))

    while True:
        await asyncio.sleep(1)



async def run_pipeline(controller):
    """Run the pipeline (algorithm steps and health checks) to completion."""
    print("Running Pipeline!")
    await controller.run()

def cleanup():
    """Called when the event loop is cancelled (Ctrl+C / stack shutdown)."""
    print("Closing Pipeline!")

def run(argv=None):
    """Parse arguments, select the mode and run the event loop.

    ``--sim``/``--real`` select the mode directly; without them the mode
    selection dialog is shown. With the control panel enabled (``.env``),
    the loop is ``qasync.run`` (Qt + asyncio in one thread); otherwise a
    plain ``asyncio.run`` is sufficient. Returns a process exit code.
    """
    global app
    import argparse
    parser = argparse.ArgumentParser(description="NeuroPilot controller")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--sim', action='store_true',
                       help='start in simulation mode (skip the mode dialog)')
    group.add_argument('--real', action='store_true',
                       help='start in real-hardware mode (skip the mode dialog)')
    args = parser.parse_args(argv)

    app = QApplication(sys.argv)
    # Window identity: without this, Qt derives the X11 WM_CLASS from the
    # script filename ("__main__.py") and the Wayland app_id is unset, so
    # GNOME shows a default icon in Alt+Tab. The matching desktop file is
    # ~/.local/share/applications/neuropilot.desktop.
    app.setApplicationName("neuropilot")
    app.setDesktopFileName("neuropilot")

    # App-wide icon (dialog, control panel, taskbar)
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui", "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    if args.sim or args.real:
        is_simulation = args.sim
        print(f"Is Simulation: {is_simulation}")
    else:
        # Create and show our custom dialog
        dialog = windowmode.ModeSelectionDialog()

        # exec_() blocks until the user clicks a button
        if dialog.exec_() == QDialog.Accepted:
            is_simulation = dialog.is_simulation
            print(f"Is Simulation: {is_simulation}")
        else:
            print("User closed the dialog without selecting.")
            return 0

    # If we do not use PyQt then we cannot run using qasync as qasync is used to bridge PyQt with our async algorithm.
    # So in that case we just run with ordinary asyncio.
    load_dotenv()
    enable_health_check_and_control_panel = os.getenv('ENABLE_HEALTH_CHECK_AND_CONTROL_PANEL', 'false').lower() == 'true'
    try:
        if enable_health_check_and_control_panel:
            qasync.run(main(enable_health_check_and_control_panel,is_simulation))
        else:
            asyncio.run(main(enable_health_check_and_control_panel,is_simulation))
    except asyncio.exceptions.CancelledError:
        print("KeyboardInterrupt: application exiting")
        cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(run())
