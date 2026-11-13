"""Virtual TMS robot: a MuJoCo twin of the UR5 cobot used for simulated
pipeline runs, replacing the real robot controller towards the rest of the
stack.

Launched as ``python -m neuropilot.sim_robot`` (the ``neuropilot sim``
supervisor starts it in parallel with the virtual neuronavigation).

Component chain built in :func:`main`:

    1. ``RobotState``          shared state (pose, targets, tracking flags)
    2. ``MuJoCoWorld``         physics simulation and viewer (``--gui``)
    3. ``IKPySolver``          end-effector IK from the robot URDF
    4. ``CollisionChecker`` / ``ContactModel``
                               self/table collisions and contact forces
    5. ``MotionPlanner``       executes movement commands in the world
    6. ``SimRobotClient``      Socket.IO client speaking the robot role on
                               the relay (``from_robot`` / ``to_robot``)
    7. ``SimRobotController``  runs the movement and status-report loops

Housekeeping around the main loop: a thread stamps the MuJoCo viewer window
with the app icon once it appears (X11 only), and a watcher shuts the whole
simulator down when the viewer window is closed (Alt+F4) instead of
continuing headless.
"""

import asyncio
import argparse
import json
import math
import os

from . import config
from .state import RobotState
from .mujoco_world import MuJoCoWorld
from .ik_solver import IKPySolver
from .utils.logging_utils import get_logger
from .collision_checker import CollisionChecker
from .contact_model import ContactModel
from .motion_planner import MotionPlanner
from .controller import SimRobotController
from .sim_client import SimRobotClient

import threading

log = get_logger(__name__)


def set_viewer_icon_when_ready(window_title: str, icon_path: str) -> None:
    """Wait for the MuJoCo viewer window to appear on X11 and set its icon
    (_NET_WM_ICON). No-op when python-xlib is missing or the window is on
    Wayland (mujoco's viewer does not expose an icon API)."""
    try:
        import time as _time
        import os as _os

        _os.environ.setdefault("DISPLAY", ":0")
        from Xlib import X, display
        from PIL import Image

        d = display.Display()
        root = d.screen().root
        wm_name = d.intern_atom("_NET_WM_NAME")
        wm_icon = d.intern_atom("_NET_WM_ICON")

        # wait up to ~30 s for the window
        win = None
        for _ in range(60):
            children = root.query_tree().children
            for c in children:
                try:
                    name = c.get_wm_name()
                except Exception:
                    continue
                if isinstance(name, str) and window_title in name:
                    win = c
                    break
            if win is not None:
                break
            _time.sleep(0.5)
        if win is None:
            return

        data = []
        for size in [(128, 128), (32, 32)]:
            img = Image.open(icon_path).convert("RGBA").resize(size)
            data.extend([size[0], size[1]])
            for r, g, b, a in img.getdata():
                data.append((a << 24) | (r << 16) | (g << 8) | b)
        win.change_property(wm_icon, d.intern_atom("CARDINAL"), 32, data)
        d.sync()
        log.info("Viewer window icon set")
    except Exception as e:
        log.debug(f"Viewer icon not set: {e}")


def parse_args():
    """Command line arguments: relay host/port and viewer on/off."""
    parser = argparse.ArgumentParser(description="TMS Robot Simulator (MuJoCo)")
    parser.add_argument("--host", type=str,  default=config.RELAY_HOST)
    parser.add_argument("--port", type=int,  default=config.RELAY_PORT)
    parser.add_argument("--gui",  action="store_true", default=config.USE_GUI,
                        help="Launch MuJoCo viewer window")
    parser.add_argument("--no-gui", dest="gui", action="store_false",
                        help="Run MuJoCo headless")
    return parser.parse_args()


async def main():
    """Build the simulation chain, connect to the relay and run the
    controller loops until cancelled (Ctrl+C or closed viewer window)."""
    args = parse_args()
    url  = f"http://{args.host}:{args.port}"

    log.info(f"Starting TMS Robot Simulator (MuJoCo) → relay at {url}")

    # ── 1. Shared state ───────────────────────────────────────────────
    state = RobotState()

    # ── 2. MuJoCo world ───────────────────────────────────────────────
    # Head phantom override persisted from a previous session (the project
    # head mesh converted for MuJoCo): applied before the model is built.
    head_override = None
    state.head_mesh_source = None
    if os.path.isfile(config.HEAD_OVERRIDE_FILE):
        try:
            with open(config.HEAD_OVERRIDE_FILE) as f:
                override = json.load(f)
            head_override = override.get("stl_path")
            if head_override and os.path.isfile(head_override):
                state.head_mesh_source = override.get("msh_path")
                log.info(f"Head phantom override active: {state.head_mesh_source}")
            else:
                log.warning("Head override file missing -- using the default "
                            "phantom (head.stl).")
                head_override = None
                try:
                    os.remove(config.HEAD_OVERRIDE_FILE)
                except OSError:
                    pass
        except (OSError, ValueError) as e:
            log.warning(f"Head override unreadable ({e}) -- using the default "
                        "phantom (head.stl).")
            head_override = None

    world = MuJoCoWorld(
        use_gui=args.gui,
        end_effector_site_name=config.END_EFFECTOR_SITE_NAME,
        head_mesh_stl=head_override,
    )
    world.connect()
    log.info("MuJoCo world loaded")

    # ── 3. IK solver ──────────────────────────────────────────────────
    ik_solver = IKPySolver(
        urdf_path=config.ROBOT_URDF_PATH,
        active_links_mask=config.IK_ACTIVE_LINKS_MASK,
        base_elements=config.IK_BASE_ELEMENTS,
    )
    log.info("IK solver ready")


    # ── 4. Collision checker + contact model ──────────────────────────
    collision_checker = CollisionChecker(world)
    contact_model     = ContactModel(world, collision_checker)

    # ── 5. Motion planner ─────────────────────────────────────────────
    motion_planner = MotionPlanner(
        state=state,
        world=world,
        ik_solver=ik_solver,
        collision_checker=collision_checker,
        contact_model=contact_model,
    )

    # ── 6. Socket.IO client ───────────────────────────────────────────
    client = SimRobotClient(url=url, state=state, world=world)

    # ── 7. Controller ─────────────────────────────────────────────────
    controller = SimRobotController(
        state=state,
        client=client,
        motion_planner=motion_planner,
    )

    # ── 8. Connect then run ───────────────────────────────────────────
    await client.connect()
    log.info("Connected to relay — starting controller loops")

    # Set the viewer window icon once the window exists (X11 only; the icon
    # shows in the taskbar and alt-tab). No-op on Wayland windows. Only
    # relevant with the native viewer (--gui); the headless sim streams to
    # the pipeline GUI instead.
    if args.gui:
        icon_thread = threading.Thread(
            target=set_viewer_icon_when_ready,
            args=(f"MuJoCo : {config.MODEL_NAME}", "assets/icon.png"),
            daemon=True,
        )
        icon_thread.start()

        async def watch_viewer_window():
            """Alt+F4 on the viewer closes the window; shut the simulator down
            instead of continuing headless."""
            while True:
                await asyncio.sleep(0.5)
                if world.viewer_handle_closed():
                    log.info("Viewer window closed — shutting down")
                    for task in asyncio.all_tasks() - {asyncio.current_task()}:
                        task.cancel()
                    return

        window_watcher = asyncio.create_task(watch_viewer_window())

    try:
        await controller.run()
    except asyncio.CancelledError:
        log.info("Simulator shutting down")
    finally:
        world.disconnect()
        log.info("MuJoCo disconnected — bye")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[tms-robot-sim] Interrupted by user")