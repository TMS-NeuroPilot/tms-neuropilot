"""Heavy project files load in the background.

The GUI must return from a file-path handler immediately, keep accepting
events while the read runs, and apply the result only on the GUI thread.
"""

import time

import pytest

pytest.importorskip("PyQt5.QtWidgets")


def test_head_hdf5_summary_is_shown(window, roi_hdf5):
    window.loadmeshlabel.setText(str(roi_hdf5))
    window._update_file_infos()
    assert window.info_mesh.text() == "4 triangles"


def test_e_field_load_does_not_block_the_window(window, controller, monkeypatch,
                                                e_matrix_hdf5):
    import neuropilot.controller.control_panel as cp

    path = e_matrix_hdf5(4, 12)
    real_reader = cp.read_e_matrix_file

    def slow_reader(fn):
        time.sleep(0.4)
        return real_reader(fn)

    monkeypatch.setattr(cp, "read_e_matrix_file", slow_reader)
    window.set_controller(controller)
    window.load_e_matrix_label.setText(str(path))

    started = time.monotonic()
    window.paste_e_field_path()
    elapsed = time.monotonic() - started

    assert elapsed < 0.25
    assert window.has_pending_loads()
    assert window.info_efield.text() == "loading..."
    assert controller.e_matrix is None

    # The rest of the window stays usable while the worker reads.
    window.n_repetitions_spinBox.setValue(7)
    assert window.n_repetitions_spinBox.value() == 7

    assert window.wait_for_loads(10.0)
    assert controller.e_matrix.shape == (4, 12)
    assert "4" in window.info_efield.text() and "12" in window.info_efield.text()


def test_mesh_load_does_not_block_the_window(window, monkeypatch, roi_hdf5):
    import neuropilot.controller.control_panel as cp

    real_reader = cp.read_mesh_file

    def slow_reader(fn, mesh_type="head", stop_event=None):
        time.sleep(0.4)
        return real_reader(fn, mesh_type, stop_event=stop_event)

    monkeypatch.setattr(cp, "read_mesh_file", slow_reader)
    window.loadroilabel.setText(str(roi_hdf5))

    started = time.monotonic()
    window.paste_roi_path()
    elapsed = time.monotonic() - started

    assert elapsed < 0.25
    assert window.has_pending_loads()
    assert window.widget_3d_viewer.mesh_roi is None

    assert window.wait_for_loads(10.0)
    assert window.widget_3d_viewer.mesh_roi is not None
    assert window.info_roi.text() == "4 triangles"


def test_a_new_path_supersedes_an_old_read(window, monkeypatch, roi_hdf5,
                                           h5file):
    import numpy as np
    import neuropilot.controller.control_panel as cp

    second = h5file({"mesh/nodes/node_coord": np.array(
                        [[0., 0., 0.], [2., 0., 0.], [0., 2., 0.]]),
                     "mesh/elm/triangle_number_list": np.array([[0, 1, 2]])},
                    "second_roi.hdf5")
    real_reader = cp.read_mesh_file

    def slow_reader(fn, mesh_type="head", stop_event=None):
        time.sleep(0.3)
        return real_reader(fn, mesh_type, stop_event=stop_event)

    monkeypatch.setattr(cp, "read_mesh_file", slow_reader)
    window.loadroilabel.setText(str(roi_hdf5))
    window.paste_roi_path()
    window.loadroilabel.setText(str(second))
    window.paste_roi_path()

    assert window.wait_for_loads(10.0)
    assert window.widget_3d_viewer.mesh_roi is not None
    assert window.widget_3d_viewer.mesh_roi.n_cells == 1
    assert window.info_roi.text() == "1 triangles"


def test_project_load_returns_before_the_mesh_is_read(window, monkeypatch,
                                                     roi_hdf5, tmp_path):
    import yaml
    import neuropilot.controller.control_panel as cp

    real_reader = cp.read_mesh_file

    def slow_reader(fn, mesh_type="head", stop_event=None):
        time.sleep(0.4)
        return real_reader(fn, mesh_type, stop_event=stop_event)

    monkeypatch.setattr(cp, "read_mesh_file", slow_reader)
    project = tmp_path / "project.yaml"
    project.write_text(yaml.safe_dump({"mesh_RIO_path": str(roi_hdf5),
                                       "fit_fun": "Sigmoid"}))

    started = time.monotonic()
    assert window.load_project_file(str(project)) is None
    elapsed = time.monotonic() - started

    assert elapsed < 0.25
    assert window.loadroilabel.text() == str(roi_hdf5)
    assert window.fitFunctionComboBox.currentText() == "Sigmoid"
    assert window.has_pending_loads()

    assert window.wait_for_loads(10.0)
    assert window.widget_3d_viewer.mesh_roi is not None
