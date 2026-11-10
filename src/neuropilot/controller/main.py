import asyncio
import logging
import numpy as np
from .pipeline_controller import PipelineController
import sys
from .control_panel_window import ControlPanelWindow
from .control_panel_window2 import MainWindow
from qasync import QEventLoop, asyncSlot
from PyQt5.QtWidgets import QApplication, QDialog
from PyQt5.QtGui import QIcon
from . import experiment_mode as windowmode
import qasync
from dotenv import load_dotenv
import os

def get_command_line_arguments():
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
    # Configure logging.
    np.set_printoptions(formatter={'float': '{:0.1f}'.format})

    if simulation:
        from .sim_remote_connection import Remote
    else:
        from .remote_connection import Remote

    ## Create remote
    host, port = get_command_line_arguments()
    url = f'http://{host}:{port}'
    remote = Remote(url)
    ## Control panel (if enabled in .env)
    
    if enable_health_check_and_control_panel:
        # Control Panel. The control panel is called to show by PipelineController.
        app.window = ControlPanelWindow()
        app.window2 = MainWindow(simulation=simulation)
        # Otherwise the window becomes transparent frozen while the controller initializes
        await asyncio.sleep(0.1)
    
    ## Controller
    # The control panel keeps track of whether we do health checks and run the control panel
    # by checking the attribute self.control_panel != None
    controller = PipelineController(remote=remote,
                                    control_panel=app.window2 if enable_health_check_and_control_panel else None,simulation=simulation)
    controller.register_remote_handlers()
    if enable_health_check_and_control_panel:
        app.window2.set_controller(controller)
    
    # With everything prepped we connect to the relay server.
    await remote.connect()
    
    # Run the algorithm and health checks (if enabled). Create_task means it runs in parallel, instead of in sequence.
    asyncio.create_task(run_pipeline(controller))

    while True:
        await asyncio.sleep(1)



async def run_pipeline(controller):
    # Run the pipeline
    print("Running Pipeline!")
    await controller.run()

def cleanup():
    print("Closing Pipeline!")
    # asyncio.create_task(cleanup())

def run(argv=None):
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
        if enable_health_check_and_control_panel == True:
            qasync.run(main(enable_health_check_and_control_panel,is_simulation))
        else:
            asyncio.run(main(enable_health_check_and_control_panel,is_simulation))
    except asyncio.exceptions.CancelledError:
        print("KeyboardInterrupt: application exiting")
        cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(run())
