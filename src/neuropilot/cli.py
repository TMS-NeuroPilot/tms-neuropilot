"""TMS NeuroPilot command line interface.

    neuropilot                  GUI mode selector (simulated vs real vs manual)
    neuropilot sim              full simulated stack
    neuropilot sim --components relay,robot    subset (debug)
    neuropilot controller [--sim|--robo|--manual]  controller only
    neuropilot relay            simulated relay only
    neuropilot robo [--launch-relay]           robotic mode (optionally + relay)
    neuropilot manual [--launch-relay]         manual mode: no robot
    neuropilot training [--launch-relay]       training: real TMS, virtual EMG
"""

import argparse
import asyncio
import sys

from . import config, startup, supervisor


def _run(components):
    try:
        asyncio.run(supervisor.run_stack(components))
    except KeyboardInterrupt:
        pass


def _resolve_invesalius(*, no_invesalius=False, override=None, gui=False):
    """Resolve the optional local InVesalius launcher.

    Discovery is deliberately non-fatal.  A broken conda metadata query or a
    missing installation must not prevent the controller from starting.
    """
    if no_invesalius:
        return None
    try:
        from .invesalius_launcher import resolve

        spec = resolve(
            config.RELAY_HOST,
            config.RELAY_PORT,
            interactive=gui or sys.stdin.isatty(),
            gui=gui,
            override=override,
        )
        if spec is not None and getattr(spec, "external", False):
            return None
        return spec
    except Exception as exc:                 # pragma: no cover - defensive
        print(f"[invesalius] discovery failed: {type(exc).__name__}: {exc}",
              file=sys.stderr, flush=True)
        return None


def _prepare_relay(*, gui=False):
    """Ensure the relay is running or can be started.

    Returns ``True`` when the controller should manage it, ``False`` when an
    existing relay is reused, and ``None`` after a GUI/terminal error.
    """
    try:
        manage = startup.prepare_relay(gui=gui)
    except Exception as exc:                 # pragma: no cover - defensive
        startup.show_error(
            "TMS NeuroPilot startup error",
            f"Relay startup failed: {type(exc).__name__}: {exc}",
            gui=gui,
        )
        return None
    if manage is None:
        startup.show_error(
            "TMS NeuroPilot startup error",
            startup.relay_unavailable_message(),
            gui=gui,
        )
        return None
    return manage


def _add_invesalius_options(parser):
    parser.add_argument(
        "--no-invesalius", action="store_true",
        help="do not start InVesalius automatically; use an existing instance",
    )
    parser.add_argument(
        "--invesalius", metavar="PATH",
        help="InVesalius conda env, inv launcher or checkout for this run",
    )


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
        description="TMS NeuroPilot — guided online TMS mapping with online field optimization",
    )
    sub = parser.add_subparsers(dest="command")

    sim = sub.add_parser("sim", help="start the full simulated stack")
    sim.add_argument("--components", type=str, default="relay,nav,robot,controller",
                     help="comma-separated subset: relay,nav,robot,controller")

    sub.add_parser("relay", help="start the simulated relay only")

    ctrl = sub.add_parser("controller", help="start the controller only")
    mode = ctrl.add_mutually_exclusive_group()
    mode.add_argument("--sim", action="store_true", help="simulation mode")
    mode.add_argument("--robo", action="store_true", help="robotic mode")
    mode.add_argument("--manual", action="store_true",
                      help="manual mode: real hardware, no robot")
    mode.add_argument("--training", action="store_true",
                      help="training mode: real TMS, virtual EMG, no robot")
    _add_invesalius_options(ctrl)

    robo = sub.add_parser("robo", help="robotic mode")
    robo.add_argument("--launch-relay", action="store_true",
                      help="compatibility flag; a configured relay is started automatically")
    _add_invesalius_options(robo)

    manual = sub.add_parser("manual", help="manual mode: real hardware, no robot")
    manual.add_argument("--launch-relay", action="store_true",
                        help="compatibility flag; a configured relay is started automatically")
    _add_invesalius_options(manual)

    training = sub.add_parser(
        "training", help="training mode: real TMS, virtual EMG, no robot")
    training.add_argument("--launch-relay", action="store_true",
                          help="compatibility flag; a configured relay is started automatically")
    _add_invesalius_options(training)

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
            return 0
        if not (args.robo or args.manual or args.training):
            _run(supervisor.controller_with_dialog())
            return 0
        manage = _prepare_relay(gui=startup.gui_available())
        if manage is None:
            return 1
        spec = _resolve_invesalius(
            no_invesalius=args.no_invesalius,
            override=args.invesalius,
        )
        if args.robo:
            _run(supervisor.robo_controller(with_relay=manage,
                                            invesalius=spec))
        elif args.manual:
            _run(supervisor.manual_stack(with_relay=manage,
                                         invesalius=spec))
        else:
            _run(supervisor.training_stack(with_relay=manage,
                                           invesalius=spec))
        return 0

    if args.command in ("manual", "training", "robo"):
        stack = {
            "manual": supervisor.manual_stack,
            "training": supervisor.training_stack,
            "robo": supervisor.robo_stack,
        }[args.command]
        manage = _prepare_relay(gui=startup.gui_available())
        if manage is None:
            return 1
        spec = _resolve_invesalius(
            no_invesalius=args.no_invesalius,
            override=args.invesalius,
        )
        _run(stack(with_relay=manage, invesalius=spec))
        return 0

    # No command: GUI mode selector.
    mode = _select_mode_gui()
    if mode is None:
        return 0
    print(f"[neuropilot] mode selected: {mode}")
    if mode == "simulation":
        _run(supervisor.sim_stack())
    else:
        manage = _prepare_relay(gui=True)
        if manage is None:
            return 1
        spec = _resolve_invesalius(gui=True)
        if mode == "manual":
            _run(supervisor.manual_stack(with_relay=manage,
                                         invesalius=spec))
        elif mode == "training":
            _run(supervisor.training_stack(with_relay=manage,
                                           invesalius=spec))
        else:
            _run(supervisor.robo_stack(with_relay=manage,
                                       invesalius=spec))
    return 0


if __name__ == "__main__":
    sys.exit(main())
