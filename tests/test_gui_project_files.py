"""Project files: load, save, and every wrong file the dialog can hand over.

All files live under ``tmp_path``; nothing touches the user's projects.
"""


import os

import numpy as np
import pytest
import yaml

PROJECT_KEYS = {
    "project_name", "fit_fun", "map_elms", "results_fn",
    "stimulator_amplitude", "target_order_fn", "stimulator_waveform",
    "minium_isi", "n_repetitions", "targets_file", "default_speed",
    "tuning_speed", "mesh_head_path", "mesh_RIO_path", "e_field_path",
    "surrogate_library_path",
    "coil_path", "emg_config_fn", "efield_mode",
}


def write(path, data):
    path.write_text(yaml.safe_dump(data))
    return path


# ── saving ──────────────────────────────────────────────────────────────

def test_save_writes_every_project_key(window, tmp_path):
    target = tmp_path / "proj.yaml"
    assert window.save_project_file(str(target)) is None
    assert target.is_file()
    data = yaml.safe_load(target.read_text())
    assert set(data) == PROJECT_KEYS


def test_save_appends_the_extension(window, tmp_path):
    target = tmp_path / "noext"
    assert window.save_project_file(str(target)) is None
    assert (tmp_path / "noext.yaml").is_file()


def test_save_remembers_the_project_file_and_clears_dirty(window, tmp_path):
    window._project_dirty = True
    target = tmp_path / "proj.yaml"
    window.save_project_file(str(target))
    assert window._project_file == str(target)
    assert window._project_dirty is False
    assert "Unsaved" not in window.project_name_edit.toolTip()


def test_save_adopts_the_file_name_when_unnamed(window, tmp_path):
    target = tmp_path / "subject_01.yaml"
    window.save_project_file(str(target))
    assert window.project_name_edit.text() == "subject_01.yaml"


def test_save_keeps_an_existing_project_name(window, tmp_path):
    window.project_name_edit.setText("S01 M1")
    target = tmp_path / "other.yaml"
    window.save_project_file(str(target))
    assert window.project_name_edit.text() == "S01 M1"


def test_save_into_a_deleted_folder_reports_and_keeps_state(window, tmp_path):
    folder = tmp_path / "gone"
    folder.mkdir()
    target = folder / "proj.yaml"
    folder.rmdir()

    error = window.save_project_file(str(target))
    assert error
    assert window._project_file is None          # not claimed as saved


def test_save_into_a_path_whose_parent_is_a_file(window, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    error = window.save_project_file(str(blocker / "proj.yaml"))
    assert error


def test_save_roundtrip_restores_the_fields(window, qapp, tmp_path):
    window.set_emg_channels(["FDI", "APB"])
    window.project_name_edit.setText("roundtrip")
    window.apply_config_dict({"fit_fun": "Sigmoid", "n_repetitions": 3,
                              "stimulator_amplitude": 42})
    target = tmp_path / "roundtrip.yaml"
    window.save_project_file(str(target))

    window.apply_config_dict({"fit_fun": "Linear", "n_repetitions": 1,
                              "stimulator_amplitude": 20})
    assert window.load_project_file(str(target)) is None
    assert window.project_name_edit.text() == "roundtrip"
    assert window.fitFunctionComboBox.currentText() == "Sigmoid"
    assert window.n_repetitions_spinBox.value() == 3
    assert window.spinBox.value() == 42


# ── loading wrong files ────────────────────────────────────────────────

def test_load_missing_file_returns_an_error(window):
    before = window.get_config_dict()
    error = window.load_project_file("/definitely/not/here/proj.yaml")
    assert error
    assert window.get_config_dict() == before


def test_load_a_directory_returns_an_error(window, tmp_path):
    error = window.load_project_file(str(tmp_path))
    assert error
    assert window._project_file is None


def test_load_an_empty_file_returns_an_error(window, tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("")
    error = window.load_project_file(str(path))
    assert error and "mapping" in error
    assert window._project_file is None


def test_load_a_corrupt_yaml_returns_an_error(window, tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("key: [unclosed\n")
    error = window.load_project_file(str(path))
    assert error
    assert window._project_file is None


def test_load_a_yaml_list_returns_an_error(window, tmp_path):
    path = tmp_path / "list.yaml"
    path.write_text("- 1\n- 2\n")
    before = window.get_config_dict()
    error = window.load_project_file(str(path))
    assert error and "mapping" in error
    assert window.get_config_dict() == before


def test_load_a_yaml_scalar_returns_an_error(window, tmp_path):
    path = tmp_path / "scalar.yaml"
    path.write_text("just text\n")
    error = window.load_project_file(str(path))
    assert error
    assert window._project_file is None


def test_load_binary_garbage_returns_an_error(window, tmp_path):
    path = tmp_path / "binary.yaml"
    path.write_bytes(b"\xff\xfe\x00\x01binary")
    error = window.load_project_file(str(path))
    assert error


@pytest.mark.parametrize("bad", [3.7, "many", float("nan"), float("inf"), None])
def test_load_bad_numbers_are_skipped_not_fatal(window, tmp_path, bad):
    path = tmp_path / "bad_number.yaml"
    path.write_text(yaml.safe_dump({"map_elms": bad,
                                    "n_repetitions": 5,
                                    "fit_fun": "Sigmoid"}))
    assert window.load_project_file(str(path)) is None
    assert window.n_repetitions_spinBox.value() == 5     # the good keys applied
    assert window.fitFunctionComboBox.currentText() == "Sigmoid"
    assert window.sampling_spinBox.value() >= 1          # untouched/clamped


def test_load_float_rounds_to_the_nearest_step(window, tmp_path):
    path = write(tmp_path / "float.yaml", {"map_elms": 3.6})
    assert window.load_project_file(str(path)) is None
    assert window.sampling_spinBox.value() == 4


def test_load_string_number_is_accepted(window, tmp_path):
    path = write(tmp_path / "string_number.yaml", {"n_repetitions": "4"})
    assert window.load_project_file(str(path)) is None
    assert window.n_repetitions_spinBox.value() == 4


def test_load_unknown_keys_are_ignored(window, tmp_path):
    path = write(tmp_path / "future.yaml",
                 {"some_future_setting": True, "fit_fun": "Exponential"})
    assert window.load_project_file(str(path)) is None
    assert window.fitFunctionComboBox.currentText() == "Exponential"


def test_load_missing_keys_keep_current_values(window, tmp_path):
    window.apply_config_dict({"n_repetitions": 6})
    path = write(tmp_path / "partial.yaml", {"fit_fun": "Step"})
    assert window.load_project_file(str(path)) is None
    assert window.n_repetitions_spinBox.value() == 6


def test_load_sets_the_project_file_and_clears_dirty(window, tmp_path):
    path = write(tmp_path / "proj.yaml", {"fit_fun": "Linear"})
    window._project_dirty = True
    assert window.load_project_file(str(path)) is None
    assert window._project_file == str(path)
    assert window._project_dirty is False


def test_load_counts_the_targets_in_the_file(window, controller, tmp_path, placements_hdf5):
    window.set_controller(controller)
    path = write(tmp_path / "proj.yaml",
                 {"targets_file": str(placements_hdf5(5))})
    window.load_project_file(str(path))
    assert window.totaltargets3.text() == "5"


# ── project files pointing at deleted / wrong data ─────────────────────

def test_load_project_with_files_deleted_after_saving(window, qapp, tmp_path,
                                                      roi_hdf5, e_matrix_hdf5):
    folder = tmp_path / "study"
    folder.mkdir()
    mesh = folder / "head.msh"
    mesh.write_text("fake")
    roi = folder / "roi.hdf5"
    roi.write_bytes(roi_hdf5.read_bytes())
    emat = folder / "e.hdf5"
    emat.write_bytes(e_matrix_hdf5(2, 6).read_bytes())
    proj = folder / "proj.yaml"
    proj.write_text(yaml.safe_dump({
        "mesh_RIO_path": str(roi), "e_field_path": str(emat),
        "mesh_head_path": str(mesh), "fit_fun": "Sigmoid",
    }))

    for name in ("head.msh", "roi.hdf5", "e.hdf5"):
        (folder / name).unlink()

    assert window.load_project_file(str(proj)) is None
    assert window.fitFunctionComboBox.currentText() == "Sigmoid"
    # Every missing path was rejected instead of being restored as a phantom.
    assert window.loadroilabel.text() == ""
    assert window.load_e_matrix_label.text() == ""
    assert window.loadmeshlabel.text() == ""


def test_load_project_with_unreadable_roi_keeps_going(window, qapp, tmp_path):
    bad = tmp_path / "roi.hdf5"
    bad.write_text("not hdf5 at all")
    proj = write(tmp_path / "proj.yaml",
                 {"mesh_RIO_path": str(bad), "fit_fun": "Sigmoid"})
    assert window.load_project_file(str(proj)) is None
    assert window.fitFunctionComboBox.currentText() == "Sigmoid"


def test_load_project_with_corrupt_e_matrix_keeps_going(window, qapp, tmp_path):
    bad = tmp_path / "e.hdf5"
    bad.write_text("nope")
    proj = write(tmp_path / "proj.yaml",
                 {"e_field_path": str(bad), "fit_fun": "Linear"})
    assert window.load_project_file(str(proj)) is None


def test_load_project_with_wrong_placements_is_rejected(window, qapp, tmp_path):
    bad = tmp_path / "targets.hdf5"
    bad.write_text("nope")
    proj = write(tmp_path / "proj.yaml", {"targets_file": str(bad)})
    assert window.load_project_file(str(proj)) is None
    assert window.loadplacementlabel.text() == ""


# ── the paste_* path handlers ──────────────────────────────────────────

def test_paste_mesh_rejects_a_deleted_path(window):
    window.loadmeshlabel.setText("/gone/head.msh")
    window.paste_mesh_path()
    assert window.loadmeshlabel.text() == ""


def test_paste_mesh_accepts_a_real_file(window, tmp_path):
    mesh = tmp_path / "head.msh"
    mesh.write_text("not really a mesh")
    window.loadmeshlabel.setText(str(mesh))
    window.paste_mesh_path()             # reader fails, but the path is kept
    assert window.loadmeshlabel.text() == str(mesh)


def test_paste_roi_rejects_garbage_without_crashing(window, tmp_path):
    roi = tmp_path / "roi.hdf5"
    roi.write_text("garbage")
    window.loadroilabel.setText(str(roi))
    window.paste_roi_path()
    assert window.widget_3d_viewer.mesh_roi is None


def test_paste_e_field_rejects_a_text_file(window, controller):
    window.set_controller(controller)
    window.load_e_matrix_label.setText(__file__)   # this Python file is not HDF5
    window.paste_e_field_path()
    assert controller.e_matrix is None


def test_paste_e_field_loads_a_valid_matrix(window, controller, e_matrix_hdf5):
    window.set_controller(controller)
    path = e_matrix_hdf5(4, 12)
    window.load_e_matrix_label.setText(str(path))
    window.paste_e_field_path()
    assert controller.e_matrix.shape == (4, 12)
    assert controller.n_elms == 12


def test_paste_placements_rejects_a_corrupt_file(window, controller, tmp_path):
    window.set_controller(controller)
    bad = tmp_path / "targets.hdf5"
    bad.write_text("garbage")
    window.loadplacementlabel.setText(str(bad))
    window.paste_coil_placements_path()
    assert window.loadplacementlabel.text() == ""
    assert controller.targets_file is None
    assert window.loadplacementlabel.toolTip()


def test_paste_placements_rejects_a_missing_dataset(window, controller, h5file):
    window.set_controller(controller)
    bad = h5file({"other": np.zeros(3)}, "no_mats.hdf5")
    window.loadplacementlabel.setText(str(bad))
    window.paste_coil_placements_path()
    assert window.loadplacementlabel.text() == ""


def test_paste_placements_rejects_the_wrong_shape(window, controller, h5file):
    window.set_controller(controller)
    bad = h5file({"matsimnibs": np.zeros((4, 4))}, "flat.hdf5")
    window.loadplacementlabel.setText(str(bad))
    window.paste_coil_placements_path()
    assert window.loadplacementlabel.text() == ""


def test_paste_placements_accepts_a_valid_file(window, controller, placements_hdf5):
    window.set_controller(controller)
    good = placements_hdf5(6)
    window.loadplacementlabel.setText(str(good))
    window.paste_coil_placements_path()
    assert window.loadplacementlabel.text() == str(good)
    assert controller.targets_file == str(good)
    assert "6" in window.loadplacementlabel.toolTip()


def test_paste_target_order_rejects_text(window, controller, tmp_path):
    window.set_controller(controller)
    bad = tmp_path / "order.txt"
    bad.write_text("first\nsecond\n")
    window.target_order_LineEdit.setText(str(bad))
    window.paste_target_order_path()
    assert window.target_order_LineEdit.text() == ""
    assert controller.target_order_fn is None


def test_paste_target_order_rejects_negative_entries(window, controller, tmp_path):
    window.set_controller(controller)
    bad = tmp_path / "order.txt"
    bad.write_text("-1\n2\n")
    window.target_order_LineEdit.setText(str(bad))
    window.paste_target_order_path()
    assert window.target_order_LineEdit.text() == ""


def test_paste_target_order_accepts_valid_indices(window, controller, tmp_path):
    window.set_controller(controller)
    good = tmp_path / "order.txt"
    good.write_text("2\n0\n1\n")
    window.target_order_LineEdit.setText(str(good))
    window.paste_target_order_path()
    assert window.target_order_LineEdit.text() == str(good)


def test_paste_coil_rejects_a_directory(window, tmp_path):
    window.coilspathlineedit.setText(str(tmp_path))
    window.paste_coil_path()
    assert window.coilspathlineedit.text() == ""


def test_paste_save_path_adds_the_csv_extension(window, controller, tmp_path):
    window.set_controller(controller)
    window.savePathLineEdit.setText(str(tmp_path / "results"))
    window.paste_save_path()
    assert window.savePathLineEdit.text().endswith(".csv")
    assert controller.results_fn == window.savePathLineEdit.text()


def test_paste_save_path_recreates_a_deleted_folder(window, controller, tmp_path):
    window.set_controller(controller)
    folder = tmp_path / "deleted" / "nested"
    window.savePathLineEdit.setText(str(folder / "out.csv"))
    window.paste_save_path()
    assert folder.is_dir()
    assert controller.results_fn.endswith("out.csv")


def test_paste_save_path_with_a_file_as_parent_is_reported(window, controller, tmp_path):
    window.set_controller(controller)
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    window.savePathLineEdit.setText(str(blocker / "out.csv"))
    window.paste_save_path()
    # No crash; the controller must not be told to write into an impossible path.
    assert controller.results_fn in (None, "")


pytestmark = pytest.mark.gui


def test_project_paths_are_saved_relative_to_the_project_file(window, tmp_path):
    folder = tmp_path / "subject"
    folder.mkdir()
    mesh = folder / "head.msh"
    mesh.write_text("fake")
    window.apply_config_dict({"mesh_head_path": str(mesh)})
    project = folder / "project.yaml"
    assert window.save_project_file(str(project)) is None
    data = yaml.safe_load(project.read_text())
    assert data["mesh_head_path"] == "head.msh"

    # Loading from a different working directory resolves against the YAML.
    window.apply_config_dict({"mesh_head_path": ""})
    assert window.load_project_file(str(project)) is None
    assert window.loadmeshlabel.text() == str(mesh)
