#!/usr/bin/env python3
"""Regenerate the screenshots used by the documentation site.

    conda activate pipeline
    python docs/site/tools/make_screenshots.py [--keep-stack]

The script:

1. builds a neutral example project under /tmp/np_demo (symlinks to the
   bundled ``data/ernie`` subject — no personal paths appear in the images),
2. starts the simulated relay/nav/robot so the Connections page is live,
3. builds the real MainWindow in simulation mode, loads the project,
4. drives the pages to representative states (R² map, MEP history, Config
   sub-tabs, a dark theme) and writes PNGs to ``docs/site/assets/screenshots``.

The 3-D view is a VTK surface and is not part of a Qt ``grab()``; it is rendered
by ``MeshWidget.screenshot()`` and composited into the window image at the
viewport's geometry. That is the only non-Qt step.

Needs a display (``DISPLAY`` or ``WAYLAND_DISPLAY``) and the example dataset in
``data/ernie`` (stored through Git LFS).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CONTROLLER_DIR = REPO / "src" / "neuropilot" / "controller"
OUT = REPO / "docs" / "site" / "assets" / "screenshots"
DEMO = Path("/tmp/np_demo")
DATA = REPO / "data" / "ernie"

WIDTH, HEIGHT = 1244, 960


# ── demo project (neutral paths) ──────────────────────────────────────

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_demo_project import build_demo_project  # noqa: E402


# ── simulated stack ───────────────────────────────────────────────────

def start_stack(python: str):
    """Start relay/nav/robot through the supervisor and wait for readiness."""
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    log = DEMO / "stack.log"
    handle = log.open("w")
    process = subprocess.Popen(
        [python, "-m", "neuropilot.cli", "sim",
         "--components", "relay,nav,robot"],
        cwd=str(REPO), env=env, start_new_session=True,
        stdout=handle, stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + 90
    while time.time() < deadline:
        time.sleep(0.5)
        text = log.read_text(errors="replace") if log.is_file() else ""
        if "component died" in text:
            print(text[-2000:])
            raise SystemExit("the simulated stack died")
        if "robot ready" in text or "not ready after" in text:
            break
    print(f"[stack] running (pid {process.pid}, log {log})")
    return process


# ── screenshot helpers ────────────────────────────────────────────────

def pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.05)


def render_robot_scene(width: int, height: int):
    """Render the MuJoCo scene offscreen (same model the GUI view uses).

    The Qt widget's own renderer needs a GL context the Qt/xcb session does not
    provide here, so the docs composite an equivalent offscreen frame into the
    robot-view rectangle instead of shipping an empty black box.
    """
    import mujoco
    import numpy as np
    from neuropilot.controller.robot_scene_view import _scene_dir

    scene = Path(_scene_dir()) / "_generated_scene.xml"
    if not scene.is_file():
        return None
    model = mujoco.MjModel.from_xml_path(str(scene))
    data = mujoco.MjData(model)
    data.qpos[:] = model.qpos0
    mujoco.mj_forward(model, data)
    renderer = mujoco.Renderer(model, height=height, width=width)
    camera = mujoco.MjvCamera()
    mujoco.mjv_defaultFreeCamera(model, camera)
    camera.azimuth = 130.0
    camera.elevation = -18.0
    camera.distance = 1.9
    camera.lookat[:] = np.array([0.25, -0.15, 0.35])
    renderer.update_scene(data, camera=camera)
    frame = renderer.render().copy()
    renderer.close()
    return frame


def grab_window(app, win, path: Path, composite_mesh=False,
                robot_frame=None) -> None:
    from PyQt5 import QtCore, QtGui

    # No processEvents() here: the qasync loop is already running, and a
    # nested event loop raises "Cannot enter into task" from asyncio.
    image = win.grab().toImage()
    if robot_frame is not None:
        label = getattr(win, "robot_view_label", None)
        if label is not None and label.isVisible():
            height, width, _ = robot_frame.shape
            frame_image = QtGui.QImage(robot_frame.data, width, height,
                                       3 * width, QtGui.QImage.Format_RGB888).copy()
            top_left = label.mapTo(win, QtCore.QPoint(0, 0))
            painter = QtGui.QPainter(image)
            painter.drawImage(QtCore.QRect(top_left, label.size()), frame_image)
            painter.end()
            # The counters are child widgets of the label, so the robot
            # composite above covers them. Paint them back on top.
            overlay = getattr(win, "_target_overlay", None)
            if overlay is not None and overlay.isVisible():
                overlay_image = overlay.grab().toImage()
                top_left = overlay.mapTo(win, QtCore.QPoint(0, 0))
                painter = QtGui.QPainter(image)
                painter.drawImage(QtCore.QRect(top_left, overlay.size()),
                                  overlay_image)
                painter.end()
    if composite_mesh:
        view = win.widget_3d_viewer
        temp = path.with_suffix(".mesh.png")
        if view.screenshot(str(temp)):
            mesh = QtGui.QImage(str(temp))
            top_left = view.mapTo(win, QtCore.QPoint(0, 0))
            painter = QtGui.QPainter(image)
            painter.drawImage(QtCore.QRect(top_left, view.size()), mesh)
            painter.end()
        temp.unlink(missing_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path))
    print(f"wrote {path.relative_to(REPO)} ({image.width()}x{image.height()})")


def synthetic_map(view, n_elements: int, centre: int, peak: float):
    import numpy as np
    if view.mesh_roi is None:
        return np.zeros(n_elements)
    centres = view.mesh_roi.cell_centers().points
    hot = centres[min(centre, len(centres) - 1)]
    d = np.linalg.norm(centres - hot, axis=1)
    sigma = 14.0
    values = peak * np.exp(-(d ** 2) / (2 * sigma ** 2))
    return np.clip(values, 0.0, 0.95)


def emg_sweep(channels=3):
    import numpy as np
    t = np.linspace(0.0, 0.35, 1400)
    data = {}
    for i in range(channels):
        rng = np.random.default_rng(7 + i)
        noise = rng.normal(0, 0.02, t.size)
        base = 0.05 * np.sin(2 * np.pi * (3 + i) * t)
        latency = 0.045 + 0.006 * i
        width = 0.012
        mep = 0.9 * np.exp(-((t - latency - 0.03) ** 2) / (2 * width ** 2))
        mep -= 0.5 * np.exp(-((t - latency - 0.045) ** 2) / (2 * width ** 2))
        data[f"ADC {i}"] = base + noise + mep * (1.0 + 0.15 * i)
    return t, data


def fake_records(view, channel_keys, count=12):
    """Placement records from the real library, with plausible MEPs."""
    import h5py
    import numpy as np
    from neuropilot.controller import transformations as tr

    path = DEMO / "NP001" / "efield" / "search_positions.hdf5"
    with h5py.File(path) as f:
        mats = f["matsimnibs"][:]
    step = max(1, mats.shape[2] // count)
    records = []
    for trial, index in enumerate(range(0, mats.shape[2], step)[:count]):
        m = mats[:, :, index]
        pos = m[:3, 3]
        rot = np.degrees(tr.euler_from_matrix(m, "sxyz"))
        target = pos + np.array([0.4, -0.2, 0.3])
        mep = {key: float(0.4 + 0.05 * trial + 0.1 * i)
               for i, key in enumerate(channel_keys)}
        records.append({
            "trial": trial, "pulse_index": trial, "target_index": index,
            "position": pos.tolist(), "rotation": rot.tolist(),
            "target_position": target.tolist(), "target_rotation": rot.tolist(),
            "aim_error_mm": 1.2,
            "intensity": 42, "pressure": 2.1,
            "mep": mep, "e_field_mode": "precomputed",
        })
    return records


# ── main ──────────────────────────────────────────────────────────────

def port_open(port: int = 5000) -> bool:
    import socket
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def select_score(view, name: str) -> None:
    """Select the R² array for ``name`` in the scalar combo (FDI, APB, …)."""
    combo = view.scalar_selector
    for index in range(combo.count()):
        text = combo.itemText(index)
        data = combo.itemData(index)
        if name in text or (isinstance(data, str) and name in data):
            combo.setCurrentIndex(index)
            view.update_scalars(index)
            return


def run(args, project: Path) -> None:
    import asyncio

    import qasync
    from PyQt5 import QtWidgets
    from neuropilot.controller import main as controller_main

    robot_frame = None
    try:
        robot_frame = render_robot_scene(640, 480)
        print("robot view: offscreen frame rendered")
    except Exception as error:               # a screenshot must not fail on this
        print(f"robot view: {error}")

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    controller_main.app = app
    sys.argv = [sys.argv[0]]          # main() reads host/port from argv

    async def session():
        from neuropilot.controller.control_panel import MainWindow
        from neuropilot.controller.pipeline_controller import PipelineController
        from neuropilot.controller.sim_remote_connection import Remote

        remote = Remote("http://127.0.0.1:5000")
        win = MainWindow(simulation=True)
        win.resize(WIDTH, HEIGHT)
        win.showNormal()
        controller = PipelineController(remote=remote, control_panel=win,
                                        simulation=True, manual=False)
        controller.register_remote_handlers()
        win.set_controller(controller)

        # The relay is already up (start_stack waited for readiness); retry a
        # few times anyway so a slow accept queue cannot kill the session.
        for attempt in range(15):
            try:
                await remote.connect()
                if remote.sio.connected:
                    print(f"relay connected (attempt {attempt + 1})")
                    break
            except Exception as error:
                print(f"relay connect: {error}")
            await asyncio.sleep(1.0)
        error = win.load_project_file(str(project))
        print("project:", error or "loaded")
        if error:
            raise SystemExit(error)

        # Heavy project files are read in the window's background loaders;
        # start the pipeline only after those paths have been applied.
        deadline = time.time() + 240
        while win.has_pending_loads() and time.time() < deadline:
            await asyncio.sleep(0.1)

        # Start the pipeline only after the project is loaded: run() marks the
        # session as running, and loading is refused from then on.
        asyncio.create_task(controller.run())
        await asyncio.sleep(1.0)

        view = win.widget_3d_viewer
        deadline = time.time() + 240
        while time.time() < deadline:
            await asyncio.sleep(0.25)
            if view.mesh_head is not None and view.mesh_roi is not None:
                break
        await asyncio.sleep(4.0)

        # 1. Project --------------------------------------------------
        win.tabWidget.setCurrentIndex(0)
        await asyncio.sleep(0.6)
        grab_window(app, win, OUT / "project-demo.png")

        # 2. Connections (live simulated systems) ---------------------
        win.tabWidget.setCurrentIndex(1)
        await asyncio.sleep(4.0)
        grab_window(app, win, OUT / "connections-sim.png")

        # 3. Control, precomputed mode --------------------------------
        win.tabWidget.setCurrentIndex(2)
        win.offline_efield_btn.setChecked(True)
        win.totaltargets3.setText("500")
        win.currenttarget.setText("pulse 16 · 1/1 · target 483")
        win.finishedsteps.appendPlainText(
            "NeuroPilot 0.1.0 · simulation mode\n"
            "Project NP001_M1_left loaded\n"
            "Relay connected · 5000\n"
            "Stimulator, EMG and robot ready\n"
            "Precomputed library — ready immediately.\n"
            "Start to begin the mapping.")
        await asyncio.sleep(1.5)
        grab_window(app, win, OUT / "control-precomputed.png",
                    robot_frame=robot_frame)

        # 4. MEP results with a plausible history ---------------------
        channel_keys = ["ADC 0", "ADC 1", "ADC 2"]
        names = ["FDI", "APB", "ADM"]
        win.set_emg_channels(names)
        history = {key: [0.6 + 0.06 * i + 0.05 * j for i in range(14)]
                   for j, key in enumerate(channel_keys)}
        win.widget_mep_trend.update_as_trend(list(range(14)), history)
        t, data = emg_sweep(len(names))
        win.widget_emg_signal.update_as_signal(t, data)
        win.tabWidget.setCurrentIndex(3)
        await asyncio.sleep(1.2)
        grab_window(app, win, OUT / "mep-results.png")

        # 5. Cortical R² map (ROI) ------------------------------------
        n_elements = len(view.mesh_roi.cell_centers().points)
        scores = {
            "ADC 0": synthetic_map(view, n_elements, 5208, 0.86),
            "ADC 1": synthetic_map(view, n_elements, 5165, 0.78),
            "ADC 2": synthetic_map(view, n_elements, 4456, 0.71),
        }
        win.update_mesh_coloring(scores)
        view.set_mapping_results(fake_records(view, channel_keys), channel_keys)
        win.tabWidget.setCurrentIndex(4)
        view.radio_roi.setChecked(True)
        select_score(view, "FDI")
        view.plotter.reset_camera()
        view.plotter.render()
        win._mark_best_for("ADC 0")
        await asyncio.sleep(1.5)
        grab_window(app, win, OUT / "cortical-results.png", composite_mesh=True)

        # 6. Config sub-tabs ------------------------------------------
        win.tabWidget.setCurrentIndex(5)
        for index, name in enumerate(("config-lab", "config-simulation",
                                      "config-study", "config-subject")):
            win.cfg_tabs.setCurrentIndex(index)
            await asyncio.sleep(0.8)
            grab_window(app, win, OUT / f"{name}.png")

        # 7. A dark theme ---------------------------------------------
        win.tabWidget.setCurrentIndex(4)
        win.apply_theme("Graphite")
        select_score(view, "FDI")
        view.plotter.reset_camera()
        view.plotter.render()
        await asyncio.sleep(1.0)
        grab_window(app, win, OUT / "cortical-graphite.png", composite_mesh=True)
        win.tabWidget.setCurrentIndex(2)
        await asyncio.sleep(1.0)
        grab_window(app, win, OUT / "control-graphite.png",
                    robot_frame=robot_frame)
        win.apply_theme("Workstation Light")

        win.close()
        await asyncio.sleep(0.5)
        await remote.disconnect()

    try:
        loop.run_until_complete(session())
    except RuntimeError as error:
        # Closing the window lets qasync stop the loop before the coroutine
        # returns; every screenshot has been written by then.
        print(f"[done] {error}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-stack", action="store_true",
                        help="leave a stack started by this script running")
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)

    if not (DATA / "mesh" / "m2m_ernie" / "ernie.msh").is_file():
        raise SystemExit("example dataset missing: data/ernie (run git lfs pull, "
                         "or see data/create_ernie.py)")
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise SystemExit("no display: set DISPLAY (or WAYLAND_DISPLAY) first")

    DEMO.mkdir(parents=True, exist_ok=True)
    (DEMO / "data").mkdir(parents=True, exist_ok=True)
    os.environ["ROOT_FOLDER"] = str(DEMO / "data")
    os.environ["NEUROPILOT_LAB_FILE"] = str(DEMO / "lab.yaml")
    os.environ["NEUROPILOT_ENV_FILE"] = str(DEMO / ".env")
    os.environ["NEUROPILOT_SESSION_FILE"] = str(DEMO / "last_session.yaml")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    os.environ.setdefault("MUJOCO_GL", "glfw")

    project = build_demo_project(DEMO, DATA)

    stack = None if port_open(5000) else start_stack(args.python)
    if stack is None:
        print("[stack] reusing the relay on 127.0.0.1:5000")

    os.chdir(CONTROLLER_DIR)
    try:
        run(args, project)
    finally:
        if stack is not None and not args.keep_stack:
            # Signal the whole group: the supervisor starts the components as
            # children and a SIGTERM to it alone leaves them orphaned.
            import signal
            try:
                os.killpg(os.getpgid(stack.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                stack.wait(timeout=10)
            except subprocess.TimeoutExpired:
                stack.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
