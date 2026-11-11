"""Shared pytest setup.

``src/`` is put on the path here; the GUI fixtures redirect every writable
location (session cache, data folder, project files) into ``tmp_path`` so the
suite never touches the user's data.
"""

import os
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

CONTROLLER_DIR = SRC / "neuropilot" / "controller"

from helpers import build_window  # noqa: E402  (tests/ is on sys.path)

# The suite writes results/study files under ROOT_FOLDER in a few code paths;
# keep those out of the user's home.  `.env` does not override an existing
# variable (load_dotenv(override=False)), so this wins.
os.environ.setdefault("ROOT_FOLDER", "/tmp/opencode/neuropilot_tests")


# ── Guard rails: the suite must never write the user's configuration ───

REPO_ENV = Path(__file__).resolve().parents[1] / ".env"
USER_CACHE = Path.home() / ".neuropilot" / "last_session.yaml"
USER_LAB = Path.home() / ".neuropilot" / "lab.yaml"


def _stamp(path):
    try:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


@pytest.fixture(autouse=True)
def protect_user_files():
    """Fail the test that rewrites the user's configuration files."""
    before = (_stamp(REPO_ENV), _stamp(USER_CACHE), _stamp(USER_LAB))
    yield
    after = (_stamp(REPO_ENV), _stamp(USER_CACHE), _stamp(USER_LAB))
    assert after == before, ("a test wrote the repository .env or a file "
                             "under ~/.neuropilot")


# ── Qt ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session (Qt allows only one)."""
    from PyQt5 import QtWidgets

    app = QtWidgets.QApplication.instance()
    if app is not None:
        return app
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("GUI tests need a display (DISPLAY/WAYLAND_DISPLAY unset)")
    try:
        app = QtWidgets.QApplication([])
    except Exception as e:                       # pragma: no cover - env dependent
        pytest.skip(f"Qt could not start: {e}")
    return app


@pytest.fixture()
def gui_env(monkeypatch, tmp_path):
    """Environment for GUI code: cwd for the .ui loader, temp data folder."""
    # uic.loadUi imports the custom widgets (mplwidget) relative to the cwd,
    # which is what the supervisor sets for the real components.
    monkeypatch.chdir(CONTROLLER_DIR)
    monkeypatch.setenv("ROOT_FOLDER", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture()
def window(qapp, gui_env, monkeypatch):
    """A real MainWindow in simulation mode, isolated from the user's files."""
    win = build_window(qapp, gui_env, monkeypatch)
    try:
        yield win
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()


# ── File factories (everything under tmp_path) ─────────────────────────

@pytest.fixture()
def h5file(tmp_path):
    """Create an HDF5 file from a dict of datasets; returns its path."""
    h5py = pytest.importorskip("h5py")

    def _make(datasets, name="data.hdf5"):
        path = tmp_path / name
        with h5py.File(path, "w") as f:
            for key, value in datasets.items():
                f.create_dataset(key, data=value)
        return path
    return _make


@pytest.fixture()
def roi_hdf5(h5file):
    """A tiny ROI surface: 6 nodes, 4 triangles."""
    import numpy as np
    nodes = np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [0.0, 10.0, 0.0],
                      [0.0, 0.0, 10.0], [10.0, 10.0, 0.0], [10.0, 0.0, 10.0]])
    tris = np.array([[0, 1, 2], [1, 2, 3], [2, 3, 4], [3, 4, 5]])
    return h5file({"mesh/nodes/node_coord": nodes,
                   "mesh/elm/triangle_number_list": tris}, "roi.hdf5")


@pytest.fixture()
def placements_hdf5(h5file):
    """Factory for a SimNIBS placements file with n identity matrices."""
    import numpy as np

    def _make(n=3, name="placements.hdf5"):
        mats = np.repeat(np.eye(4)[:, :, None], n, axis=2)
        for i in range(n):
            mats[0, 3, i] = float(i)
        return h5file({"matsimnibs": mats}, name)
    return _make


@pytest.fixture()
def e_matrix_hdf5(h5file):
    """Factory for an E-field library with a given (placements, elements)."""
    import numpy as np

    def _make(n_positions=3, n_elements=8, name="e_field.hdf5"):
        data = np.arange(n_positions * n_elements, dtype=float).reshape(
            n_positions, n_elements)
        return h5file({"E_mag": data}, name)
    return _make


# ── Controller (no hardware, no event loop) ────────────────────────────

class _FakeSio:
    connected = True


class FakeRemote:
    """Minimal stand-in for the relay client used by the controller."""

    url = "http://test"
    sio = _FakeSio()

    def __init__(self):
        self.handlers = {}
        self.sent = []

    def register_handlers(self, handlers):
        self.handlers.update(handlers)

    def register_handler(self, topic, handler):
        self.handlers[topic] = handler

    async def send_message(self, topic, data=None):
        self.sent.append((topic, data))
        return True


@pytest.fixture()
def controller(monkeypatch):
    """A simulated PipelineController without hardware or a running loop."""
    from neuropilot.controller.pipeline_controller import PipelineController
    from neuropilot.controller.systems.emg import EMGComputer
    from neuropilot.controller.systems.stimulator import Stimulator

    # The real systems would schedule relay work on a loop that is not running.
    monkeypatch.setattr(Stimulator, "try_connect", lambda self: None)
    monkeypatch.setattr(EMGComputer, "try_connect", lambda self: None)
    return PipelineController(remote=FakeRemote(), simulation=True,
                              control_panel=None)


@pytest.fixture()
def gui(window, controller):
    """Window with a controller attached, as the real entry point does."""
    window.set_controller(controller)
    return window
