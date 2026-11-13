"""Lifecycle: worker threads, timers, teardown.

The mesh/coil summaries are produced in threads; their results must reach the
GUI thread through the ``file_info_ready`` signal (a widget touched from a
worker is undefined behaviour).  Closing the window must stop the timers and
the MuJoCo view.
"""


import sys
import threading
import time

import numpy as np
import pytest

QtCore = pytest.importorskip("PyQt5.QtCore")


def pump(qapp, seconds=2.0, until=None):
    """Process events until ``until()`` is true or the time is up."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        qapp.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.02)
    return False if until is not None else True


# ── the signal is the thread boundary ──────────────────────────────────

def test_file_info_signal_arrives_on_the_gui_thread(window, qapp):
    threads = []

    def worker():
        threads.append(threading.current_thread().name)
        window._emit_file_info("info_mesh", "123 tets · 45 tris")

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert pump(qapp, 2.0, lambda: window.info_mesh.text() != "")
    assert window.info_mesh.text() == "123 tets · 45 tris"


def test_emit_after_close_is_ignored(window, qapp):
    window._closing = True
    window._emit_file_info("info_mesh", "late")      # must not raise
    qapp.processEvents()
    assert window.info_mesh.text() != "late"


def test_mesh_summary_comes_back_from_the_worker(window, qapp, tmp_path,
                                                 monkeypatch):
    simnibs = pytest.importorskip("simnibs")
    mesh_io = simnibs.mesh_io

    class FakeMesh:
        class elm:
            elm_type = np.array([4, 4, 4, 2, 2])

    monkeypatch.setattr(mesh_io, "read_msh", lambda path: FakeMesh())
    mesh = tmp_path / "head.msh"
    mesh.write_text("not read: the reader is stubbed")
    window.loadmeshlabel.setText(str(mesh))
    window._update_file_infos()
    assert pump(qapp, 3.0, lambda: "tets" in window.info_mesh.text())
    assert window.info_mesh.text() == "3 tets · 2 tris"


def test_unreadable_mesh_is_reported(window, qapp, tmp_path, monkeypatch):
    simnibs = pytest.importorskip("simnibs")
    mesh_io = simnibs.mesh_io

    def boom(path):
        raise RuntimeError("bad mesh")

    monkeypatch.setattr(mesh_io, "read_msh", boom)
    mesh = tmp_path / "broken.msh"
    mesh.write_text("garbage")
    window.loadmeshlabel.setText(str(mesh))
    window._update_file_infos()
    assert pump(qapp, 3.0, lambda: "unreadable" in window.info_mesh.text())
    assert "RuntimeError" in window.info_mesh.text()


def test_mesh_reader_runs_once_per_file(window, qapp, tmp_path, monkeypatch):
    simnibs = pytest.importorskip("simnibs")
    mesh_io = simnibs.mesh_io
    calls = []

    class FakeMesh:
        class elm:
            elm_type = np.array([4])

    def slow_read(path):
        calls.append(path)
        time.sleep(0.2)
        return FakeMesh()

    monkeypatch.setattr(mesh_io, "read_msh", slow_read)
    mesh = tmp_path / "head.msh"
    mesh.write_text("x")
    window.loadmeshlabel.setText(str(mesh))
    for _ in range(3):
        window._update_file_infos()
    assert pump(qapp, 3.0, lambda: window.info_mesh.text() != "")
    assert len(calls) == 1


# ── cached summaries ───────────────────────────────────────────────────

def test_roi_summary_counts_triangles(window, roi_hdf5):
    window.loadroilabel.setText(str(roi_hdf5))
    window._update_file_infos()
    assert window.info_roi.text() == "4 triangles"


def test_roi_summary_refreshes_when_the_file_changes(window, tmp_path, h5file):
    nodes = np.zeros((6, 3))
    path = h5file({"mesh/nodes/node_coord": nodes,
                   "mesh/elm/triangle_number_list": np.array([[0, 1, 2], [1, 2, 3]])},
                  "roi.hdf5")
    window.loadroilabel.setText(str(path))
    window._update_file_infos()
    assert window.info_roi.text() == "2 triangles"

    h5file({"mesh/nodes/node_coord": nodes,
            "mesh/elm/triangle_number_list": np.array([[0, 1, 2], [1, 2, 3], [2, 3, 4]])},
           "roi.hdf5")
    os_utime(path)
    window._update_file_infos()
    assert window.info_roi.text() == "3 triangles"


def os_utime(path):
    """Bump the mtime so the cache signature changes (same-second rewrites)."""
    import os
    stat = os.stat(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000))


def test_broken_roi_summary_is_marked_unreadable(window, tmp_path):
    bad = tmp_path / "roi.hdf5"
    bad.write_text("garbage")
    window.loadroilabel.setText(str(bad))
    window._update_file_infos()
    assert window.info_roi.text().startswith("unreadable")


def test_efield_summary_shows_the_shape(window, e_matrix_hdf5):
    window.load_e_matrix_label.setText(str(e_matrix_hdf5(3, 40)))
    window._update_file_infos()
    assert "3" in window.info_efield.text() and "40" in window.info_efield.text()


def test_efield_summary_without_the_dataset(window, h5file):
    path = h5file({"other": np.zeros(2)}, "e.hdf5")
    window.load_e_matrix_label.setText(str(path))
    window._update_file_infos()
    assert window.info_efield.text() == "no E_mag dataset"


def test_summaries_are_blank_for_directories(window, tmp_path):
    for attr in ("loadmeshlabel", "loadroilabel", "load_e_matrix_label",
                 "loadplacementlabel", "coilspathlineedit", "emg_config_label"):
        getattr(window, attr).setText(str(tmp_path))
    window._update_file_infos()
    for label in ("info_mesh", "info_roi", "info_efield", "info_placements",
                  "info_coil", "info_emg"):
        assert getattr(window, label).text() == ""


def test_summaries_are_blank_when_the_paths_are_cleared(window, roi_hdf5):
    window.loadroilabel.setText(str(roi_hdf5))
    window._update_file_infos()
    assert window.info_roi.text()
    window.loadroilabel.setText("")
    window._update_file_infos()
    assert window.info_roi.text() == ""


def test_target_order_summary_counts_lines(window, tmp_path):
    order = tmp_path / "order.txt"
    order.write_text("0\n1\n\n2\n")
    window.target_order_LineEdit.setText(str(order))
    window._update_file_infos()
    assert window.info_target_order.text() == "3 placements"


def test_placements_summary_counts_matrices(window, placements_hdf5):
    window.loadplacementlabel.setText(str(placements_hdf5(7)))
    window._update_file_infos()
    assert "7" in window.info_placements.text()


def test_emg_summary_counts_sources(window, tmp_path):
    path = tmp_path / "emg.yaml"
    path.write_text("sources:\n  - element_id: 1\n  - element_id: 2\n")
    window.emg_config_label.setText(str(path))
    window._update_file_infos()
    assert window.info_emg.text() == "2 sources"


def test_results_status_is_in_the_overwrite_checkbox_tooltip(
        window, qapp, tmp_path):
    existing = tmp_path / "out.csv"
    existing.write_text("x" * 4096)
    window.savePathLineEdit.setText(str(existing))
    window._update_file_infos()
    assert "exists" in window.overwrite_results_chk.toolTip()

    window.savePathLineEdit.setText(str(tmp_path / "later.csv"))
    window._update_file_infos()
    assert "does not exist" in window.overwrite_results_chk.toolTip()


# ── close ──────────────────────────────────────────────────────────────

def test_close_stops_the_info_timer(window, qapp):
    window._info_timer.start()
    assert window._info_timer.isActive()
    window.close()
    qapp.processEvents()
    assert not window._info_timer.isActive()


def test_close_stops_the_robot_view(window, qapp):
    view = getattr(window, "_robot_scene_view", None)
    if view is None:
        pytest.skip("embedded robot view not available")
    window.close()
    qapp.processEvents()
    assert not view._timer.isActive()


def test_resize_scales_fonts_without_waiting_for_a_debounce(window, qapp):
    window.show()
    qapp.processEvents()
    window.resize(1244, 960)
    qapp.processEvents()
    window._rescale()
    before = window.cfg_mode_badge.fontInfo().pixelSize()
    window.resize(1800, 1200)
    qapp.processEvents()
    after = window.cfg_mode_badge.fontInfo().pixelSize()
    assert after > before


def test_resize_then_close_leaves_no_pending_style_timer(window, qapp, monkeypatch):
    captured = []
    monkeypatch.setattr(sys, "excepthook", lambda t, e, tb: captured.append(e))
    window.resize(1500, 1100)
    window.close()
    pump(qapp, 0.5)
    assert captured == []


def test_second_window_after_close_is_independent(window, qapp):
    from neuropilot.controller import control_panel as cp
    window.close()
    window.deleteLater()
    qapp.processEvents()
    second = cp.MainWindow(simulation=True)
    second.resize(1244, 960)
    qapp.processEvents()
    assert second.tabWidget.count() == 8   # 6 .ui pages + Collision test + About
    assert second is not window
    second.close()
    second.deleteLater()
    qapp.processEvents()


def test_online_fem_callback_runs_on_the_gui_thread(window, qapp, monkeypatch):
    """The manager finishes on a worker; the window must be updated via Qt."""
    from neuropilot.controller.OnlineFEMManager import OnlineFEMManager

    manager = OnlineFEMManager()
    manager.mesh_fn_msh = "mesh.msh"
    manager.roi_fn_hdf5 = "roi.hdf5"
    manager.coil_fn = "coil.hdf5"
    manager.initialize = lambda: None
    # The window connects this signal to its own slot at construction; add a
    # spy to observe which thread Qt delivers it on.
    seen = []
    window.online_fem_ready.connect(
        lambda: seen.append(threading.current_thread().name))
    manager.ensure_initialized(callback=window.online_fem_ready.emit)
    assert pump(qapp, 3.0, lambda: seen)
    assert seen and seen[0] == threading.main_thread().name


pytestmark = pytest.mark.gui


def test_style_pass_after_close_is_a_no_op(window, qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "_rescale_styles", lambda s: calls.append(s))
    window.resize(1500, 1100)          # arms the style timer
    window.close()
    pump(qapp, 0.5)
    assert calls == []


def test_rescale_skips_widgets_deleted_after_geometry_capture(window, qapp):
    from PyQt5 import QtWidgets, sip

    window.show()
    assert pump(qapp, 3.0, lambda: window._base_rects is not None)
    extra = QtWidgets.QCheckBox(window)
    window._base_rects["sheets"][extra] = "QCheckBox { color: red; }"
    window._base_rects["fonts"][extra] = 15
    window._base_rects["rects"][extra] = extra.geometry()
    sip.delete(extra)
    window._rescale()                 # must not touch the dead wrapper
    assert extra not in window._base_rects["sheets"]
    assert extra not in window._base_rects["fonts"]
    assert extra not in window._base_rects["rects"]
