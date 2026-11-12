"""NeuroPilot command line interface.

    neuropilot                  GUI mode selector (simulated vs real vs manual)
    neuropilot sim              full simulated stack
    neuropilot sim --components relay,robot    subset (debug)
    neuropilot controller [--sim|--real|--manual]  controller only
    neuropilot relay            simulated relay only
    neuropilot real [--launch-relay]           real mode (optionally + real relay)
    neuropilot manual [--launch-relay]         manual mode: no robot
    neuropilot training [--launch-relay]       training: real TMS, virtual EMG
"""

import argparse
import asyncio
import sys

from . import config, supervisor


def _run(components):
    try:
        asyncio.run(supervisor.run_stack(components))
    except KeyboardInterrupt:
        pass


def _select_mode_gui():
    """No-args launch: reuse the controller's mode-selection dialog."""
    from PyQt5 import QtWidgets

    from .controller import experiment_mode as windowmode

    app = QtWidgets.QApplication(sys.argv)
    dialog = windowmode.ModeSelectionDialog()
    if dialog.exec_() != QtWidgets.QDialog.Accepted:
        print("User closed the mode selector without choosing.")
        return None
    return dialog.mode


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="neuropilot",
        description="NeuroPilot — guided online TMS mapping with online field optimization",
    )
    sub = parser.add_subparsers(dest="command")

    sim = sub.add_parser("sim", help="start the full simulated stack")
    sim.add_argument("--components", type=str, default="relay,nav,robot,controller",
                     help="comma-separated subset: relay,nav,robot,controller")

    sub.add_parser("relay", help="start the simulated relay only")

    ctrl = sub.add_parser("controller", help="start the controller only")
    mode = ctrl.add_mutually_exclusive_group()
    mode.add_argument("--sim", action="store_true", help="simulation mode")
    mode.add_argument("--real", action="store_true", help="real-hardware mode")
    mode.add_argument("--manual", action="store_true",
                      help="manual mode: real hardware, no robot")

    real = sub.add_parser("real", help="real-hardware mode")
    real.add_argument("--launch-relay", action="store_true",
                      help="also start the production relay from "
                           "TMS_ROBOT_CONTROL_PATH (default: expect one running)")

    manual = sub.add_parser("manual", help="manual mode: real hardware, no robot")
    manual.add_argument("--launch-relay", action="store_true",
                        help="also start the production relay from "
                             "TMS_ROBOT_CONTROL_PATH (default: expect one running)")

    training = sub.add_parser(
        "training", help="training mode: real TMS, virtual EMG, no robot")
    training.add_argument("--launch-relay", action="store_true",
                          help="also start the production relay from "
                               "TMS_ROBOT_CONTROL_PATH (default: expect one running)")

    args = parser.parse_args(argv)

    # Importing components reads environment variables at import time; the
    # unified config must run first. It is already imported above.
    if args.command == "sim":
        selected = [c.strip() for c in args.components.split(",") if c.strip()]
        _run(supervisor.sim_stack(selected))
        return 0

    if args.command == "relay":
        _run(supervisor.sim_stack(["relay"]))
        return 0

    if args.command == "controller":
        if args.sim:
            _run(supervisor.sim_stack(["controller"]))
        elif args.real:
            _run(supervisor.real_controller())
        elif args.manual:
            _run(supervisor.manual_stack(with_relay=False))
        elif args.training:
            _run(supervisor.training_stack(with_relay=False))
        else:
            _run(supervisor.controller_with_dialog())
        return 0

    if args.command in ("manual", "training"):
        stack = (supervisor.manual_stack if args.command == "manual"
                 else supervisor.training_stack)
        if args.launch_relay:
            if not config.TMS_ROBOT_CONTROL_PATH:
                print("TMS_ROBOT_CONTROL_PATH is not set — cannot launch the "
                      "production relay. Set it in .env or pass it via the "
                      "environment.")
                return 1
            _run(stack(with_relay=True))
        else:
            print("[neuropilot] expecting a relay on "
                  f"{config.RELAY_HOST}:{config.RELAY_PORT} (start "
                  "tms-robot-control's relay_server.py manually or use "
                  "--launch-relay)")
            _run(stack(with_relay=False))
        return 0

    # No command: GUI mode selector.
    mode = _select_mode_gui()
    if mode is None:
        return 0
    print(f"[neuropilot] mode selected: {mode}")
    if mode == "simulation":
        _run(supervisor.sim_stack())
    elif mode == "manual":
        _run(supervisor.manual_stack(with_relay=False))
    elif mode == "training":
        _run(supervisor.training_stack(with_relay=False))
    else:
        _run(supervisor.real_stack(with_relay=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
