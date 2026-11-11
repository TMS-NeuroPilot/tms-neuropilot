"""Online solver lifecycle: initialise once, never twice, never block the GUI."""

import threading

import numpy as np
import pytest

from neuropilot.controller.OnlineFEMManager import OnlineFEMManager


@pytest.fixture()
def manager():
    mgr = OnlineFEMManager()
    # Paths are all a background initialisation needs; the solver itself is
    # stubbed in the tests, so nothing touches SimNIBS or the filesystem.
    mgr.mesh_fn_msh = "mesh.msh"
    mgr.roi_fn_hdf5 = "roi.hdf5"
    mgr.coil_fn = "coil.hdf5"
    return mgr


def test_defaults():
    mgr = OnlineFEMManager()
    assert mgr.online_fem is None
    assert mgr.is_online is False
    assert mgr.is_offline is False
    assert mgr.is_ready is False
    assert mgr.initializing is False
    assert mgr.e_matrix is None


def test_mode_flags():
    mgr = OnlineFEMManager()
    mgr.online_fem = True
    assert mgr.is_online and not mgr.is_offline
    mgr.online_fem = False
    assert mgr.is_offline and not mgr.is_online


def test_ensure_initialized_starts_one_background_thread(manager):
    started, release = threading.Event(), threading.Event()
    calls, callbacks = [], []

    def fake_initialize():
        calls.append(1)
        started.set()
        release.wait(5)

    manager.initialize = fake_initialize
    manager.ensure_initialized(callback=lambda: callbacks.append("first"))
    manager.ensure_initialized(callback=lambda: callbacks.append("second"))
    assert started.wait(2)
    assert manager.initializing is True
    assert manager.is_ready is False

    release.set()
    for _ in range(200):
        if not manager.initializing:
            break
        threading.Event().wait(0.01)
    assert manager.initializing is False
    assert manager.is_ready is True
    assert len(calls) == 1                 # the second call reused the first
    assert callbacks == ["first"]          # only the running initialiser reports


def test_ensure_initialized_when_already_ready_only_calls_back(manager):
    manager.ready = True
    called = []
    manager.initialize = lambda: pytest.fail("must not initialise again")
    manager.ensure_initialized(callback=lambda: called.append(1))
    assert called == [1]
    assert manager.initializing is False


def test_ensure_initialized_refuses_without_paths():
    mgr = OnlineFEMManager()
    mgr.initialize = lambda: pytest.fail("must not initialise without paths")
    mgr.ensure_initialized()
    assert mgr.initializing is False
    assert mgr.is_ready is False


def test_failed_initialization_leaves_a_retryable_state(manager):
    def boom():
        raise RuntimeError("no solver")

    manager.initialize = boom
    called = []
    manager.ensure_initialized(callback=lambda: called.append(1))
    for _ in range(200):
        if not manager.initializing:
            break
        threading.Event().wait(0.01)
    assert manager.initializing is False
    assert manager.is_ready is False
    assert called == []                    # no "ready" callback on failure

    # A retry must be possible after a failure.
    manager.initialize = lambda: None
    manager.ensure_initialized()
    for _ in range(200):
        if not manager.initializing:
            break
        threading.Event().wait(0.01)
    assert manager.is_ready is True


def test_compute_e_field_is_a_no_op_offline(manager):
    manager.online_fem = False
    assert manager.compute_e_field([[0, 0, 0], [0, 0, 0]], 50) is None
    assert manager.e_matrix is None


def test_compute_e_field_appends_rows(manager):
    class FakeSolver:
        def update_field(self, matsimnibs, didt):
            scale = didt / 1e6
            return [[np.array([[scale, 0.0, 0.0], [0.0, scale, 0.0]])]]

    manager.computer = FakeSolver()
    manager.online_fem = True
    row1 = manager.compute_e_field([[0, 0, 0], [0, 0, 0]], 10)
    row2 = manager.compute_e_field([[0, 0, 0], [0, 0, 0]], 20)
    assert row1.shape == (2,)
    assert row1[0] == pytest.approx(10 * 1.4)
    assert row2[0] == pytest.approx(20 * 1.4)
    assert manager.e_matrix.shape == (2, 2)


def test_reset_clears_the_accumulated_matrix(manager):
    manager.e_matrix = np.zeros((3, 5))
    manager.reset()
    assert manager.e_matrix is None
