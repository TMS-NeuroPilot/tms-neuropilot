"""The embedded MuJoCo robot view (simulation only)."""

import os

import numpy as np
import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
QtCore = pytest.importorskip("PyQt5.QtCore")
pytest.importorskip("mujoco")


@pytest.fixture()
def view(qapp, gui_env, monkeypatch):
    from neuropilot.controller import robot_scene_view as rsv

    # The real assets are large; a tiny MJCF is enough for the plumbing.
    tmp = gui_env / "mjcf"
    tmp.mkdir(exist_ok=True)
    (tmp / "robot_tm5x_700.xml").write_text(
        '<mujoco><worldbody><body name="b"><joint name="j" type="hinge"/>'
        '<geom size="0.05"/></body></worldbody></mujoco>')
    monkeypatch.setattr(rsv, "_scene_dir", lambda: str(tmp))

    label = QtWidgets.QLabel()
    label.resize(320, 240)
    label.show()
    qapp.processEvents()
    widget = rsv.RobotSceneView(label, parent=label)
    try:
        yield widget
    finally:
        widget.stop()
        label.close()


def test_scene_loads(view):
    assert view._load_scene() is True
    assert view._model is not None
    assert view._data is not None


def test_missing_scene_is_reported_not_raised(view, monkeypatch):
    from neuropilot.controller import robot_scene_view as rsv
    monkeypatch.setattr(rsv, "_scene_dir", lambda: "/definitely/not/here")
    assert view._load_scene() is False
    view._render()                      # no model: a no-op, no exception


def test_broken_scene_xml_is_skipped(view, gui_env, monkeypatch):
    from neuropilot.controller import robot_scene_view as rsv
    tmp = gui_env / "broken"
    tmp.mkdir(exist_ok=True)
    (tmp / "robot_tm5x_700.xml").write_text("<mujoco><worldbody>")
    monkeypatch.setattr(rsv, "_scene_dir", lambda: str(tmp))
    assert view._load_scene() is False


def test_qpos_longer_than_the_model_is_truncated(view):
    view._load_scene()
    view.set_qpos([1.0] * (view._data.qpos.size + 10))
    assert np.isfinite(view._data.qpos).all()


def test_qpos_shorter_than_the_model_is_applied_partially(view):
    view._load_scene()
    view.set_qpos([0.5])
    assert view._data.qpos[0] == pytest.approx(0.5)


def test_empty_qpos_is_ignored(view):
    view._load_scene()
    before = np.array(view._data.qpos)
    view.set_qpos([])
    view.set_qpos(None)
    np.testing.assert_allclose(view._data.qpos, before)


def test_textual_qpos_does_not_raise(view):
    view._load_scene()
    view.set_qpos(["a", "b"])           # conversion fails inside _apply_qpos
    assert view._data is not None


def test_start_and_stop_the_timer(view):
    view.start()
    assert view._timer.isActive()
    view.stop()
    assert not view._timer.isActive()


def test_view_switches_from_the_fallback_to_the_generated_scene(view):
    """The robot writes _generated_scene.xml after the window starts.

    The view initially loads the robot-only fallback.  It must pick up the
    higher-priority scene later, otherwise the subject head never appears.
    """
    from neuropilot.controller import robot_scene_view as rsv

    tmp = rsv._scene_dir()
    generated = os.path.join(tmp, "_generated_scene.xml")
    if os.path.exists(generated):
        os.remove(generated)
    assert view._load_scene() is True
    assert view._scene_path.endswith("robot_tm5x_700.xml")

    with open(generated, "w") as f:
        f.write('<mujoco><worldbody><body name="generated_body">'
                '<geom size="0.05"/></body></worldbody></mujoco>')
    view._maybe_reload()
    assert view._scene_path == generated
    assert view._model.body("generated_body").id >= 0


def test_stop_without_a_renderer_is_safe(view):
    view._renderer = None
    view.stop()                          # must not raise


def test_render_without_opengl_disables_the_view(view, monkeypatch):
    import mujoco
    view._load_scene()
    view.label.show()

    def no_gl(*args, **kwargs):
        raise RuntimeError("no OpenGL")

    monkeypatch.setattr(mujoco, "Renderer", no_gl)
    view._dirty = True
    view._render()
    assert not view._timer.isActive()
    assert "unavailable" in view.label.text()


def test_render_when_hidden_does_nothing(view, monkeypatch):
    calls = []
    monkeypatch.setattr(view, "_maybe_reload", lambda: calls.append(1))
    view.label.hide()
    view._render()
    assert calls == []


class _Event:
    """Minimal stand-in for the Qt mouse/wheel events the view filters."""

    def __init__(self, kind, button=None, pos=None, angle=0):
        self._kind = kind
        self._button = button
        self._pos = pos or QtCore.QPoint(0, 0)
        self._angle = angle

    def type(self):
        return self._kind

    def button(self):
        return self._button

    def pos(self):
        return self._pos

    def angleDelta(self):
        return QtCore.QPoint(0, self._angle)


def test_mouse_events_orbit_pan_and_zoom(view):
    label = view.label

    start = view._azimuth
    view.eventFilter(label, _Event(QtCore.QEvent.MouseButtonPress,
                                  button=QtCore.Qt.LeftButton,
                                  pos=QtCore.QPoint(10, 10)))
    view.eventFilter(label, _Event(QtCore.QEvent.MouseMove,
                                  pos=QtCore.QPoint(30, 20)))
    view.eventFilter(label, _Event(QtCore.QEvent.MouseButtonRelease,
                                  button=QtCore.Qt.LeftButton))
    assert view._azimuth != start

    distance = view._distance
    view.eventFilter(label, _Event(QtCore.QEvent.Wheel, angle=120))
    assert view._distance != distance

    view.reset_view()
    assert view._distance == view.DEFAULT_DISTANCE


pytestmark = pytest.mark.gui


def test_offscreen_buffer_grows_to_the_label_size(view):
    view._load_scene()
    view._model.vis.global_.offwidth = 1920
    view._model.vis.global_.offheight = 1200
    view._fit_offscreen(2488, 1571)
    assert view._model.vis.global_.offwidth >= 2488
    assert view._model.vis.global_.offheight >= 1571
