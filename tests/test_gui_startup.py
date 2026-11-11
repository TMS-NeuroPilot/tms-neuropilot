"""Startup and settings edge cases that used to prevent the app from running."""


import os

import numpy as np
import pytest
import yaml


def make_window(qapp, gui_env, monkeypatch, tmp_path, resize=True):
    """Construct a window with its session cache in tmp_path."""
    from neuropilot.controller import control_panel as cp
    monkeypatch.setattr(cp, "_session_cache_path",
                        lambda: str(tmp_path / "last_session.yaml"))
    win = cp.MainWindow(simulation=True)
    if resize:
        win.resize(1244, 960)
    qapp.processEvents()
    return win


@pytest.mark.parametrize("value", ["abc", "", " ", "1,5", "auto"])
def test_invalid_ui_scale_does_not_stop_startup(qapp, gui_env, monkeypatch,
                                                tmp_path, value):
    monkeypatch.setenv("NEUROPILOT_UI_SCALE", value)
    win = make_window(qapp, gui_env, monkeypatch, tmp_path)
    try:
        assert win.tabWidget.count() == 6
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("value", ["0", "-3", "0.2"])
def test_tiny_ui_scale_is_clamped(qapp, gui_env, monkeypatch, tmp_path, value):
    monkeypatch.setenv("NEUROPILOT_UI_SCALE", value)
    win = make_window(qapp, gui_env, monkeypatch, tmp_path)
    try:
        assert win.minimumWidth() >= 1200
        assert win._current_scale() >= 1.0
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()


def test_large_ui_scale_opens_a_larger_window(qapp, gui_env, monkeypatch, tmp_path):
    monkeypatch.setenv("NEUROPILOT_UI_SCALE", "1.5")
    win = make_window(qapp, gui_env, monkeypatch, tmp_path, resize=False)
    try:
        assert win.width() >= 1.4 * win._design_size[0]
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()


# ── session cache shapes ───────────────────────────────────────────────

def test_list_session_cache_is_ignored(qapp, gui_env, monkeypatch, tmp_path):
    cache = tmp_path / "last_session.yaml"
    cache.write_text("- 1\n- 2\n")
    win = make_window(qapp, gui_env, monkeypatch, tmp_path)
    try:
        assert win._pending_session in ({}, None)
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()


def test_scalar_session_cache_is_ignored(qapp, gui_env, monkeypatch, tmp_path):
    cache = tmp_path / "last_session.yaml"
    cache.write_text("just a string\n")
    win = make_window(qapp, gui_env, monkeypatch, tmp_path)
    try:
        assert win._pending_session in ({}, None)
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()


def test_corrupt_session_cache_is_ignored(qapp, gui_env, monkeypatch, tmp_path):
    cache = tmp_path / "last_session.yaml"
    cache.write_text("key: [unclosed\n")
    win = make_window(qapp, gui_env, monkeypatch, tmp_path)
    try:
        assert win.tabWidget.count() == 6
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()


def test_session_cache_with_dead_paths_is_applied_safely(qapp, gui_env,
                                                         monkeypatch, tmp_path,
                                                         controller):
    cache = tmp_path / "last_session.yaml"
    cache.write_text(yaml.safe_dump({
        "mesh_head_path": str(tmp_path / "gone.msh"),
        "e_field_path": str(tmp_path / "gone.hdf5"),
        "fit_fun": "Sigmoid",
        "stimulator_amplitude": 42,
    }))
    win = make_window(qapp, gui_env, monkeypatch, tmp_path)
    win.set_controller(controller)          # the cache is applied on attach
    try:
        assert win.fitFunctionComboBox.currentText() == "Sigmoid"
        assert win.loadmeshlabel.text() == ""
        assert win.load_e_matrix_label.text() == ""
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()


def test_session_cache_directory_replaced_by_a_file(qapp, gui_env, monkeypatch,
                                                    tmp_path):
    folder = tmp_path / "cache_dir"
    folder.write_text("not a directory")
    monkeypatch.setattr(
        "neuropilot.controller.control_panel._session_cache_path",
        lambda: str(folder / "last_session.yaml"))
    win = make_window(qapp, gui_env, monkeypatch, tmp_path)
    try:
        win.cfg_relay_host.setText("x")          # triggers a cache write attempt
        qapp.processEvents()
        assert win.tabWidget.count() == 6
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()


# ── the online solver needs its derived .msh ───────────────────────────

def test_radios_need_the_derived_msh(window, controller, tmp_path, monkeypatch):
    window.set_controller(controller)
    hdf5 = tmp_path / "mesh.hdf5"
    hdf5.write_text("x")                        # the sibling .msh does not exist
    window.loadmeshlabel.setText(str(hdf5))
    window.paste_mesh_path()
    assert controller.online_fem_mgr.mesh_fn_msh.endswith(".msh")
    assert not window.online_efield_btn.isEnabled()

    (tmp_path / "mesh.msh").write_text("x")
    window.paste_mesh_path()
    window.coilspathlineedit.setText(__file__)
    window.paste_coil_path()
    window.loadroilabel.setText(__file__)
    window.paste_roi_path()
    assert window.online_efield_btn.isEnabled()


def test_emg_config_field_clears_a_missing_file(window):
    window.emg_config_label.setText("/gone/channels.yaml")
    window.paste_emg_config()
    assert window.emg_config_label.text() == ""
    assert "not found" in window.emg_config_label.toolTip().lower()


def test_emg_config_field_keeps_a_real_file(window, controller, tmp_path):
    path = tmp_path / "channels.yaml"
    path.write_text("sources:\n  - element_id: 1\n")
    window.set_controller(controller)
    window.emg_config_label.setText(str(path))
    window.paste_emg_config()
    assert window.emg_config_label.text() == str(path)


# ── project name / dirty state ─────────────────────────────────────────

def test_editing_a_field_marks_the_project_dirty(window, qapp):
    window._project_file = "/tmp/project.yaml"
    window._project_dirty = False
    window.n_repetitions_spinBox.setValue(5)
    qapp.processEvents()
    assert window._project_dirty is True
    assert "Unsaved" in window.project_name_edit.toolTip()


def test_loading_suppresses_the_dirty_flag(window, tmp_path):
    window._project_loading = True
    window.n_repetitions_spinBox.setValue(7)
    window._project_loading = False
    assert window._project_dirty is False


def test_untitled_project_tooltip(window):
    window._project_file = None
    window._update_project_label()
    assert "project name" in window.project_name_edit.toolTip().lower()
    assert window.project_name_edit.placeholderText()


pytestmark = pytest.mark.gui
