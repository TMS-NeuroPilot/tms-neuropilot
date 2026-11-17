"""Cortical-results page: table, readout, marks, export, screenshot.

The 3D view is real (pyvista) where the test needs a mesh, but the heavy
loading is done from a tiny ROI file written into ``tmp_path``.
"""


import os

import numpy as np
import pytest


def score(n, base=0.0):
    return np.linspace(base, base + 0.4, n)


def placement(trial=0, mode="precomputed", mep=0.42):
    return {
        "trial": trial, "pulse_index": trial, "target_index": trial,
        "time": float(trial),
        "position": (1.0, 2.0, 3.0), "rotation": (0.0, 0.0, 0.0),
        "target_position": (1.5, 2.0, 3.0), "target_rotation": (0.0, 0.0, 0.0),
        "aim_error_mm": 0.5, "intensity": 55, "pressure": 1.0,
        "mep": {"ADC 0": mep}, "e_field_mode": mode,
    }


# ── table + summary ────────────────────────────────────────────────────

def test_table_shows_one_row_per_channel(window, qapp):
    window.set_emg_channels(["FDI", "APB"])
    window.update_mesh_coloring({"ADC 1": score(10, 0.1), "ADC 0": score(10)})
    qapp.processEvents()
    table = window.results_table
    assert table.rowCount() == 2
    assert [table.item(r, 0).text() for r in range(2)] == ["FDI", "APB"]


def test_table_marks_the_best_element(window, qapp):
    values = np.array([0.1, 0.9, 0.3])
    window.update_mesh_coloring({"ADC 0": values})
    qapp.processEvents()
    assert window.results_table.item(0, 2).text() == "1"
    assert "0.900" in window.results_table.item(0, 1).text()


def test_table_handles_empty_scores(window, qapp):
    window.update_mesh_coloring({"ADC 0": np.array([])})
    qapp.processEvents()
    assert window.results_table.item(0, 1).text() == "—"


def test_table_handles_nan_scores_without_raising(window, qapp):
    window.update_mesh_coloring({"ADC 0": np.array([np.nan, 0.3])})
    qapp.processEvents()
    assert window.results_table.rowCount() == 1


def test_summary_counts_a_mixed_session(window, qapp):
    window._mapping_placements = ([placement(i, "precomputed") for i in range(3)]
                                  + [placement(3, "online")])
    window.update_mesh_coloring({"ADC 0": score(5)})
    qapp.processEvents()
    assert window.results_summary.text().startswith("4 pulses (1 online) · ")


def test_update_mapping_results_bundle(window, qapp):
    window.update_mapping_results({
        "placements": [placement(0)],
        "channels": ["ADC 0"],
        "scores": {"ADC 0": score(4)},
    })
    qapp.processEvents()
    assert window._mapping_placements and len(window._mapping_placements) == 1
    assert window.results_table.rowCount() == 1


def test_update_mapping_results_ignores_an_empty_bundle(window):
    window.update_mapping_results(None)
    window.update_mapping_results({})
    assert window.results_table.rowCount() == 0


# ── radio-driven enable states ─────────────────────────────────────────

def test_results_controls_follow_the_view_radio(window, qapp):
    view = window.widget_3d_viewer
    view.radio_head.setChecked(True)
    window._update_results_controls()
    assert window.placement_metric_combo.isEnabled()
    assert not window.mark_best_btn.isEnabled()

    view.radio_roi.setChecked(True)
    window._update_results_controls()
    assert not window.placement_metric_combo.isEnabled()
    assert window.mark_best_btn.isEnabled()


# ── readout ────────────────────────────────────────────────────────────

def test_element_pick_shows_scores(window):
    window.set_emg_channels(["FDI"])
    window.update_mesh_coloring({"ADC 0": np.array([0.1, 0.44])})
    window.widget_3d_viewer.element_picked.emit(
        {"element": 42, "xyz": (1.0, 2.0, 3.0), "scores": {"ADC 0": 0.44}})
    text = window.selection_info.toPlainText()
    assert "ELEMENT 42" in text
    assert "1.0," in text and "2.0," in text and "3.0" in text
    assert "0.440" in text


def test_click_pins_the_readout(window):
    window.widget_3d_viewer.element_picked.emit(
        {"element": 7, "xyz": (0.0, 0.0, 0.0), "scores": {}, "click": True})
    window.widget_3d_viewer.element_picked.emit(
        {"element": 8, "xyz": (0.0, 0.0, 0.0), "scores": {}})
    assert window._selection_pinned is True
    assert "ELEMENT 7" in window.selection_info.toPlainText()


def test_clear_marks_unpins_and_resets_the_readout(window):
    window._selection_pinned = True
    window.on_clear_marks()
    assert window._selection_pinned is False
    assert "Hover the mesh" in window.selection_info.toPlainText()


def test_placement_pick_shows_the_full_record(window):
    window.set_emg_channels(["FDI"])
    window.widget_3d_viewer.placement_picked.emit({"record": placement(2, "online")})
    text = window.selection_info.toPlainText()
    for fragment in ("TRIAL 2", "aim error", "55", "E-field", "online", "MEP FDI"):
        assert fragment in text


def test_mark_best_without_scores_explains(window):
    window.on_mark_best()
    assert "No R² map yet" in window.selection_info.toPlainText()


def test_mark_best_marks_the_argmax(window, qapp, roi_hdf5):
    view = window.widget_3d_viewer
    view.load_hdf5_mesh(str(roi_hdf5), mesh_type="roi")
    qapp.processEvents()
    window.set_emg_channels(["FDI"])
    window.update_mesh_coloring({"ADC 0": np.array([0.1, 0.7, 0.2, 0.4])})
    window.on_mark_best()
    assert view._best_element == 1
    assert "BEST R²" in window.selection_info.toPlainText()


def test_mark_best_clears_before_remarking(window, qapp, roi_hdf5):
    view = window.widget_3d_viewer
    view.load_hdf5_mesh(str(roi_hdf5), mesh_type="roi")
    window.update_mesh_coloring({"ADC 0": np.array([0.1, 0.2, 0.7, 0.4])})
    window.on_mark_best()
    window.on_clear_marks()
    assert view._best_element is None


def test_results_row_click_marks_that_channel(window, qapp, roi_hdf5):
    view = window.widget_3d_viewer
    view.load_hdf5_mesh(str(roi_hdf5), mesh_type="roi")
    window.set_emg_channels(["FDI", "APB"])
    window.update_mesh_coloring({"ADC 0": np.array([0.9, 0.1, 0.2, 0.3]),
                                 "ADC 1": np.array([0.1, 0.2, 0.8, 0.3])})
    window.on_results_row_clicked(1, 0)
    assert view._best_channel == "ADC 1"
    assert view._best_element == 2


@pytest.mark.parametrize("row", [-1, 99])
def test_results_row_click_out_of_range_is_harmless(window, qapp, row):
    window.update_mesh_coloring({"ADC 0": np.array([0.1, 0.2])})
    window.on_results_row_clicked(row, 0)          # must not raise


# ── exports ────────────────────────────────────────────────────────────

def test_export_writes_tables_and_readme(window, qapp, tmp_path, roi_hdf5,
                                         monkeypatch):
    view = window.widget_3d_viewer
    view.load_hdf5_mesh(str(roi_hdf5), mesh_type="roi")
    window.set_emg_channels(["FDI"])
    window.update_mesh_coloring({"ADC 0": np.array([0.1, 0.5, 0.2, 0.3])})
    window._mapping_placements = [placement(0), placement(1, "online")]
    base = tmp_path / "export"
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: str(base))

    window.on_export_results()

    assert (tmp_path / "export_roi_r2.csv").is_file()
    assert (tmp_path / "export_placements.csv").is_file()
    readme = (tmp_path / "export_README.txt").read_text()
    assert "export_roi_r2.csv" in readme and "export_placements.csv" in readme
    assert "Exported" in window.selection_info.toPlainText()


def test_export_into_a_deleted_folder_reports(window, qapp, tmp_path, monkeypatch):
    window.update_mesh_coloring({"ADC 0": np.array([0.1, 0.2])})
    window._mapping_placements = [placement(0)]
    folder = tmp_path / "gone"
    folder.mkdir()
    target = folder / "export"
    folder.rmdir()
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: str(target))
    window.on_export_results()
    assert "Export failed" in window.selection_info.toPlainText()


def test_export_with_nothing_collected_writes_the_readme(window, tmp_path,
                                                        monkeypatch):
    base = tmp_path / "empty"
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: str(base))
    window.on_export_results()
    assert (tmp_path / "empty_README.txt").is_file()
    assert not (tmp_path / "empty_roi_r2.csv").exists()


def test_roi_csv_pads_short_channel_scores(window, qapp, tmp_path, roi_hdf5,
                                           monkeypatch):
    view = window.widget_3d_viewer
    view.load_hdf5_mesh(str(roi_hdf5), mesh_type="roi")
    window.update_mesh_coloring({"ADC 0": np.array([0.1, 0.2, 0.3, 0.4]),
                                 "ADC 1": np.array([0.5])})
    path = tmp_path / "roi.csv"
    window._write_roi_csv(path)
    lines = path.read_text().splitlines()
    assert len(lines) == 5                        # header + 4 elements
    assert lines[2].endswith(",")                  # ADC 1 has no value there


def test_screenshot_writes_a_png(window, qapp, tmp_path, monkeypatch):
    target = tmp_path / "shot"
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: str(target))
    window.on_screenshot()
    written = tmp_path / "shot.png"
    assert written.is_file() and written.stat().st_size > 0
    assert "Screenshot saved" in window.selection_info.toPlainText()


def test_screenshot_into_a_deleted_folder_reports(window, tmp_path, monkeypatch):
    folder = tmp_path / "gone"
    folder.mkdir()
    target = folder / "shot"
    folder.rmdir()
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: str(target))
    window.on_screenshot()
    assert "Screenshot failed" in window.selection_info.toPlainText()


def test_screenshot_cancelled_changes_nothing(window, monkeypatch):
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: "")
    before = window.selection_info.toPlainText()
    window.on_screenshot()
    assert window.selection_info.toPlainText() == before


def test_emg_sources_reach_the_cortical_view(window, qapp, roi_hdf5):
    view = window.widget_3d_viewer
    view.load_hdf5_mesh(str(roi_hdf5), mesh_type="roi")
    window.set_emg_channels(["FDI", "APB"])
    window.set_emg_sources([0, 2])
    qapp.processEvents()
    assert view.emg_sources == [0, 2]
    assert "emg_source_0" in view.plotter.actors
    assert "emg_source_1" in view.plotter.actors


def test_removing_the_emg_config_clears_the_sources(window, qapp, roi_hdf5):
    view = window.widget_3d_viewer
    view.load_hdf5_mesh(str(roi_hdf5), mesh_type="roi")
    window.set_emg_sources([0])
    qapp.processEvents()
    window.emg_config_label.setText("")
    window.paste_emg_config()
    qapp.processEvents()
    assert view.emg_sources == []
    assert "emg_source_0" not in view.plotter.actors


pytestmark = pytest.mark.gui
