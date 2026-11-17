"""Loading meshes into the 3D view (valid, corrupt and mismatched files)."""

import numpy as np
import pytest

pytest.importorskip("PyQt5.QtWidgets")
pytest.importorskip("pyvista")


@pytest.fixture()
def view(qapp, gui_env):
    from neuropilot.controller.meshwidget import MeshWidget
    widget = MeshWidget()
    widget.resize(500, 400)
    qapp.processEvents()
    return widget


def test_valid_roi_mesh_is_loaded(view, qapp, roi_hdf5):
    view.load_hdf5_mesh(str(roi_hdf5), mesh_type="roi")
    qapp.processEvents()
    assert view.mesh_roi is not None
    assert view.mesh_roi.n_cells == 4
    assert view.radio_roi.isChecked()


def test_tissue_types_are_attached_per_cell(view, qapp, h5file):
    nodes = np.zeros((6, 3))
    tris = np.array([[0, 1, 2], [1, 2, 3]])
    path = h5file({"mesh/nodes/node_coord": nodes,
                   "mesh/elm/triangle_number_list": tris,
                   "mesh/elm/tri_tissue_type": np.array([1, 2])}, "roi.hdf5")
    view.load_hdf5_mesh(str(path), mesh_type="roi")
    qapp.processEvents()
    assert "Tissue Type" in view.mesh_roi.cell_data


def test_mismatched_tissue_types_are_skipped(view, qapp, h5file):
    nodes = np.zeros((6, 3))
    tris = np.array([[0, 1, 2], [1, 2, 3]])
    path = h5file({"mesh/nodes/node_coord": nodes,
                   "mesh/elm/triangle_number_list": tris,
                   "mesh/elm/tri_tissue_type": np.array([1])}, "roi.hdf5")
    view.load_hdf5_mesh(str(path), mesh_type="roi")
    qapp.processEvents()
    assert view.mesh_roi is not None            # the geometry still loads
    assert "Tissue Type" not in view.mesh_roi.cell_data


def test_hdf5_without_the_mesh_datasets_keeps_the_old_view(view, qapp, h5file,
                                                           roi_hdf5):
    view.load_hdf5_mesh(str(roi_hdf5), mesh_type="roi")
    previous = view.mesh_roi
    bad = h5file({"something": np.zeros(2)}, "bad.hdf5")
    view.load_hdf5_mesh(str(bad), mesh_type="roi")   # prints, does not raise
    qapp.processEvents()
    assert view.mesh_roi is previous


def test_corrupt_hdf5_keeps_the_old_view(view, qapp, tmp_path):
    bad = tmp_path / "roi.hdf5"
    bad.write_text("not hdf5")
    view.load_hdf5_mesh(str(bad), mesh_type="roi")
    qapp.processEvents()
    assert view.mesh_roi is None


def test_empty_path_clears_the_mesh(view, qapp, roi_hdf5):
    view.load_hdf5_mesh(str(roi_hdf5), mesh_type="roi")
    view.load_hdf5_mesh("", mesh_type="roi")
    qapp.processEvents()
    assert view.mesh_roi is None


def test_unreadable_msh_keeps_the_previous_head(view, qapp, tmp_path, monkeypatch):
    from neuropilot.controller import meshwidget

    class FakeHead:
        n_cells = 4
        n_points = 6

    monkeypatch.setattr(meshwidget.pv, "PolyData",
                        lambda nodes, faces: _StubMesh())
    good = tmp_path / "head.msh"
    good.write_text("x")
    monkeypatch.setattr(view, "_load_simnibs_msh",
                        lambda path: (np.zeros((6, 3)), np.array([[0, 1, 2], [1, 2, 3]]),
                                      np.array([1, 2])))
    view.load_hdf5_mesh(str(good), mesh_type="head")
    qapp.processEvents()
    assert view.mesh_head is not None

    bad = tmp_path / "bad.msh"
    bad.write_text("x")
    monkeypatch.setattr(view, "_load_simnibs_msh", lambda path: None)
    view.load_hdf5_mesh(str(bad), mesh_type="head")
    qapp.processEvents()
    assert view.mesh_head is not None              # unchanged, not wiped


class _StubMesh:
    """Minimal stand-in for pyvista.PolyData (the test avoids the GL pipeline)."""

    n_points = 6
    n_cells = 2
    point_data = {}
    cell_data = {}

    def decimate(self, fraction):
        return self


def test_channel_display_names_are_remembered(view):
    view.set_channel_display_names(["FDI", "APB"])
    assert view.channel_display_names == {"ADC 0": "FDI", "ADC 1": "APB"}


def test_edges_are_shown_by_default(view):
    assert view.edge_checkbox.text() == "Show edges"
    assert view.edge_checkbox.isChecked()


def test_legend_values_follow_the_metric(view):
    from neuropilot.controller.meshwidget import MeshWidget

    assert MeshWidget._format_legend_value(0.00653, "MEP FDI (mV)") == "0.00653"
    assert MeshWidget._format_legend_value(0.0117, "MEP FDI (mV)") == "0.0117"
    assert MeshWidget._format_legend_value(0.0, "FDI (R²)") == "0.00"
    assert MeshWidget._format_legend_value(1.0, "FDI (R²)") == "1.00"


def test_scene_clear_restores_the_lightkit(view):
    view.plotter.clear()
    view._ensure_lightkit()
    assert len(view.plotter.renderer.GetLights()) >= 3


def test_pulse_count_reaches_the_corner_label(view, qapp):
    view.set_pulse_count(7)
    qapp.processEvents()
    assert "7" in view._label_pulses.text()


def test_marks_can_be_cleared_without_scores(view, qapp):
    view.clear_marks()
    assert view._best_element is None
    assert view._best_channel is None


def test_placement_metric_and_options_are_accepted(view, qapp):
    view.set_placement_metric("aim")
    view.set_placement_options(show=True, handles=True, path=True)
    qapp.processEvents()          # no exception is the assertion


def test_result_selector_shows_channel_names(view, qapp, roi_hdf5):
    view.load_hdf5_mesh(str(roi_hdf5), mesh_type="roi")
    view.set_channel_display_names(["FDI", "APB"])
    view.apply_scores({"ADC 0": np.array([0.1, 0.4, 0.2, 0.3]),
                       "ADC 1": np.array([0.2, 0.1, 0.5, 0.3])})
    qapp.processEvents()
    labels = [view.scalar_selector.itemText(i)
              for i in range(view.scalar_selector.count())]
    assert view._colour_caption.text() == "Show results:"
    assert labels == ["No results", "FDI", "APB"]


def _select_result(view, key):
    index = view.scalar_selector.findData(key)
    assert index >= 0
    view.scalar_selector.setCurrentIndex(index)


def test_emg_sources_are_drawn_on_the_selected_result(view, qapp, roi_hdf5):
    view.load_hdf5_mesh(str(roi_hdf5), mesh_type="roi")
    view.set_channel_display_names(["FDI", "APB"])
    view.set_emg_sources([0, 2])
    view.apply_scores({"ADC 0": np.array([0.1, 0.4, 0.2, 0.3]),
                       "ADC 1": np.array([0.2, 0.1, 0.5, 0.3])})
    _select_result(view, "Score ADC 1")
    qapp.processEvents()
    actors = view.plotter.actors
    assert "emg_source_0" not in actors
    assert "emg_source_1" in actors
    assert "emg_source_label_0-labels" not in actors
    assert "emg_source_label_1-labels" in actors

    centres = view.mesh_roi.cell_centers().points
    normals = view.mesh_roi.face_normals
    normal = normals[2] / np.linalg.norm(normals[2])
    expected = centres[2] + normal * 3.0
    point = actors["emg_source_1"].center
    np.testing.assert_allclose(point, expected, atol=1e-6)


def test_no_result_hides_the_source_spheres(view, qapp, roi_hdf5):
    view.load_hdf5_mesh(str(roi_hdf5), mesh_type="roi")
    view.set_channel_display_names(["FDI", "APB"])
    view.set_emg_sources([0, 2])
    view.apply_scores({"ADC 0": np.array([0.1, 0.4, 0.2, 0.3]),
                       "ADC 1": np.array([0.2, 0.1, 0.5, 0.3])})
    view.scalar_selector.setCurrentIndex(0)
    qapp.processEvents()
    assert not any(name.startswith("emg_source")
                   for name in view.plotter.actors)


def test_emg_sources_follow_the_roi_view(view, qapp, roi_hdf5):
    view.load_hdf5_mesh(str(roi_hdf5), mesh_type="roi")
    view.set_channel_display_names(["FDI"])
    view.set_emg_sources([0])
    view.apply_scores({"ADC 0": np.array([0.1, 0.4, 0.2, 0.3])})
    qapp.processEvents()
    assert "emg_source_0" in view.plotter.actors

    view.radio_head.setChecked(True)
    qapp.processEvents()
    assert "emg_source_0" not in view.plotter.actors

    view.radio_roi.setChecked(True)
    qapp.processEvents()
    assert "emg_source_0" in view.plotter.actors


def test_clearing_emg_sources_removes_the_spheres(view, qapp, roi_hdf5):
    view.load_hdf5_mesh(str(roi_hdf5), mesh_type="roi")
    view.set_channel_display_names(["FDI"])
    view.set_emg_sources([0, 1])
    view.apply_scores({"ADC 0": np.array([0.1, 0.4, 0.2, 0.3])})
    qapp.processEvents()
    assert "emg_source_0" in view.plotter.actors
    view.set_emg_sources([])
    qapp.processEvents()
    assert view.emg_sources == []
    assert not any(name.startswith("emg_source")
                   for name in view.plotter.actors)


pytestmark = pytest.mark.gui
