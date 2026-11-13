"""Embedded 3D view of the simulated robot.

Simulation only: instead of the robot process streaming JPEG frames, the
controller renders the same MuJoCo scene locally and lets the operator orbit
around it. The view mirrors the simulated robot's full ``qpos`` (published
with the tracking state) and reloads the composed scene when the robot
rebuilds it (e.g. after a head-mesh change).

The scene file is the one the simulated robot writes
(``sim_robot/assets/mjcf/_generated_scene.xml``); the base robot MJCF is the
fallback while the robot process has not started yet.
"""

import os

import mujoco
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets


def _scene_dir():
    import neuropilot.sim_robot as sim_robot
    return os.path.join(os.path.dirname(sim_robot.__file__), "assets", "mjcf")


class RobotSceneView(QtCore.QObject):
    """Renders a MuJoCo scene into a QLabel with mouse orbit controls.

    Left drag orbits, right/middle drag pans, the wheel zooms, a double click
    restores the default view.
    """

    DEFAULT_AZIMUTH = 130.0
    DEFAULT_ELEVATION = -18.0
    DEFAULT_DISTANCE = 1.9
    DEFAULT_LOOKAT = (0.25, -0.15, 0.35)

    def __init__(self, label, fps=30, parent=None, auto_reload=True):
        super().__init__(parent)
        self.label = label
        self.auto_reload = auto_reload
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(max(10, int(1000 / max(1, fps))))
        self._timer.timeout.connect(self._render)

        self._model = None
        self._data = None
        self._renderer = None
        self._render_size = (0, 0)
        self._scene_path = None
        self._scene_stamp = None
        self._last_check = 0.0
        self._pending_qpos = None
        self._dirty = True
        self._started = False

        self._azimuth = self.DEFAULT_AZIMUTH
        self._elevation = self.DEFAULT_ELEVATION
        self._distance = self.DEFAULT_DISTANCE
        self._lookat = np.array(self.DEFAULT_LOOKAT, dtype=float)
        self._camera = mujoco.MjvCamera()

        self._drag_button = None
        self._last_mouse = QtCore.QPoint()

        label.setMouseTracking(True)
        label.setScaledContents(False)
        label.installEventFilter(self)

    # ── lifecycle ────────────────────────────────────────────────────
    def start(self):
        self._started = True
        self._load_scene()
        self._dirty = True
        self._timer.start()

    def stop(self):
        self._started = False
        self._suspend_render()

    def _suspend_render(self):
        """Drop the GL context while this page is hidden.

        Two embedded MuJoCo views (Control and Collision test) must not keep
        two live renderer contexts while the operator switches pages.
        """
        self._timer.stop()
        if self._renderer is not None:
            try:
                self._renderer.close()
            except Exception:
                pass
            self._renderer = None
            self._render_size = (0, 0)

    def _resume_render(self):
        if not self._started:
            return
        self._dirty = True
        if not self._timer.isActive():
            self._timer.start()

    def set_model(self, model, data):
        """Render an externally owned model/data pair (collision test).

        ``auto_reload`` must be false for this mode: the caller owns the
        scene and updates body poses in place.
        """
        if self._renderer is not None:
            try:
                self._renderer.close()
            except Exception:
                pass
            self._renderer = None
            self._render_size = (0, 0)
        model.vis.global_.offwidth = max(model.vis.global_.offwidth, 1920)
        model.vis.global_.offheight = max(model.vis.global_.offheight, 1200)
        self._model = model
        self._data = data
        self._scene_path = None
        self._scene_stamp = None
        self._pending_qpos = None
        mujoco.mj_forward(self._model, self._data)
        self._dirty = True

    def refresh(self):
        """Request a redraw after external model/data changes."""
        self._dirty = True

    def _fit_offscreen(self, width: int, height: int) -> None:
        """Grow MuJoCo's offscreen framebuffer to the widget size.

        MuJoCo refuses to render an image taller or wider than the model's
        ``vis.global_.offwidth/offheight``.  Those defaults are 1920x1200, so
        a maximized window on a scaled display used to disable the whole view
        with a misleading "no OpenGL" message.
        """
        if self._model is None:
            return
        self._model.vis.global_.offwidth = max(
            int(self._model.vis.global_.offwidth), int(width))
        self._model.vis.global_.offheight = max(
            int(self._model.vis.global_.offheight), int(height))

    # ── scene ────────────────────────────────────────────────────────
    def _candidates(self):
        base = _scene_dir()
        return (os.path.join(base, "_generated_scene.xml"),
                os.path.join(base, "robot_tm5x_700.xml"))

    def _load_scene(self):
        for path in self._candidates():
            if not os.path.isfile(path):
                continue
            try:
                model = mujoco.MjModel.from_xml_path(path)
            except Exception as e:
                print(f"[RobotSceneView] cannot load {os.path.basename(path)}: {e}")
                continue
            # The offscreen buffer must be at least as large as the widget.
            model.vis.global_.offwidth = max(model.vis.global_.offwidth, 1920)
            model.vis.global_.offheight = max(model.vis.global_.offheight, 1200)
            # The renderer is bound to the model it was built for: drop it so
            # the next frame rebuilds it against the reloaded scene.
            if self._renderer is not None:
                try:
                    self._renderer.close()
                except Exception:
                    pass
                self._renderer = None
                self._render_size = (0, 0)
            self._dirty = True
            self._model = model
            self._data = mujoco.MjData(model)
            # Without a forward pass the body/geom poses in MjData are not
            # computed and the renderer draws an empty scene.
            mujoco.mj_forward(self._model, self._data)
            self._scene_path = path
            try:
                stat = os.stat(path)
                self._scene_stamp = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                self._scene_stamp = None
            if self._pending_qpos is not None:
                self._apply_qpos(self._pending_qpos)
            return True
        return False

    def _maybe_reload(self):
        """Reload when the robot rewrote the composed scene (head change).

        The view may have started on the robot-only fallback before the
        simulated robot wrote ``_generated_scene.xml``.  Keep checking the
        candidate order, not only the mtime of the file loaded first, or the
        embedded view would never pick up the head.
        """
        if not self.auto_reload:
            return
        candidate = next((p for p in self._candidates() if os.path.isfile(p)),
                         None)
        if candidate is None:
            return
        if self._scene_path != candidate:
            self._load_scene()
            return
        try:
            stat = os.stat(self._scene_path)
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return
        if stamp != self._scene_stamp:
            self._scene_stamp = stamp
            self._load_scene()

    # ── state ────────────────────────────────────────────────────────
    def set_qpos(self, qpos):
        if not qpos:
            return
        self._pending_qpos = list(qpos)
        self._dirty = True
        if self._data is not None:
            self._apply_qpos(self._pending_qpos)

    def _apply_qpos(self, qpos):
        try:
            n = min(len(qpos), self._data.qpos.size)
            self._data.qpos[:n] = np.asarray(qpos[:n], dtype=float)
            mujoco.mj_forward(self._model, self._data)
        except Exception as e:
            print(f"[RobotSceneView] qpos apply failed: {e}")

    # ── rendering ────────────────────────────────────────────────────
    def _render(self):
        if not self.label.isVisible():
            return
        import time as _time
        now = _time.monotonic()
        if now - self._last_check > 1.0:
            self._last_check = now
            self._maybe_reload()
        if self._model is None and not self._load_scene():
            return

        width = max(32, self.label.width())
        height = max(24, self.label.height())
        self._fit_offscreen(width, height)
        resized = self._render_size != (width, height)
        if not self._dirty and not resized and self._renderer is not None:
            return
        self._dirty = False
        if self._renderer is None or resized:
            if self._renderer is not None:
                try:
                    self._renderer.close()
                except Exception:
                    pass
            try:
                self._renderer = mujoco.Renderer(self._model, height=height,
                                                 width=width)
            except Exception as e:
                # No usable OpenGL (headless session, remote display): stop
                # rendering instead of taking the whole window down.
                print(f"[RobotSceneView] OpenGL unavailable, view disabled: {e}")
                self._timer.stop()
                self.label.setText("3D robot view unavailable (no OpenGL)")
                return
            self._render_size = (width, height)

        camera = self._camera
        mujoco.mjv_defaultFreeCamera(self._model, camera)
        camera.azimuth = float(self._azimuth)
        camera.elevation = float(self._elevation)
        camera.distance = float(self._distance)
        camera.lookat[:] = self._lookat

        try:
            self._renderer.update_scene(self._data, camera=camera)
            frame = self._renderer.render()
        except Exception as e:
            print(f"[RobotSceneView] render failed: {e}")
            return
        image = QtGui.QImage(frame.data, frame.shape[1], frame.shape[0],
                             3 * frame.shape[1], QtGui.QImage.Format_RGB888).copy()
        self.label.setPixmap(QtGui.QPixmap.fromImage(image))

    # ── mouse interaction ────────────────────────────────────────────
    def eventFilter(self, obj, event):
        if obj is not self.label:
            return False
        etype = event.type()
        if etype == QtCore.QEvent.Hide:
            self._suspend_render()
            return False
        if etype == QtCore.QEvent.Show:
            self._resume_render()
            return False
        if etype == QtCore.QEvent.MouseButtonPress:
            self._drag_button = event.button()
            self._last_mouse = event.pos()
            return True
        if etype == QtCore.QEvent.MouseButtonDblClick:
            self.reset_view()
            return True
        if etype == QtCore.QEvent.MouseButtonRelease:
            self._drag_button = None
            return True
        if etype == QtCore.QEvent.MouseMove and self._drag_button is not None:
            delta = event.pos() - self._last_mouse
            self._last_mouse = event.pos()
            self._dirty = True
            if self._drag_button == QtCore.Qt.LeftButton:
                self._azimuth -= delta.x() * 0.4
                self._elevation = max(-89.0, min(89.0,
                                                 self._elevation - delta.y() * 0.3))
            else:
                # Pan in the camera plane: scale with distance/size.
                scale = self._distance * 0.0016
                self._lookat[0] -= delta.x() * scale
                self._lookat[2] += delta.y() * scale
            return True
        if etype == QtCore.QEvent.Wheel:
            steps = event.angleDelta().y() / 120.0
            self._distance = max(0.4, min(6.0,
                                          self._distance * (0.9 ** steps)))
            self._dirty = True
            return True
        return False

    def reset_view(self):
        self._dirty = True
        self._azimuth = self.DEFAULT_AZIMUTH
        self._elevation = self.DEFAULT_ELEVATION
        self._distance = self.DEFAULT_DISTANCE
        self._lookat = np.array(self.DEFAULT_LOOKAT, dtype=float)
