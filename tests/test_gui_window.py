"""Smoke + structure tests for the real MainWindow.

These construct the actual window (Qt, pyvista, MuJoCo view) and drive it the
way the operator does: switch pages, resize, colour the mesh, update the
results table.  Anything that raises here would raise in front of the user.
"""


import numpy as np
import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

EXPECTED_TABS = ["Project", "Connections", "Control", "MEP results",
                 "Cortical results", "Collision test", "Config"]


def test_window_constructs_and_is_a_main_window(window):
    assert isinstance(window, QtWidgets.QMainWindow)


def test_pages_in_the_agreed_order(window):
    tabs = window.tabWidget
    names = [tabs.tabText(i) for i in range(tabs.count())]
    assert names == EXPECTED_TABS


def test_every_page_has_widgets(window):
    tabs = window.tabWidget
    for i in range(tabs.count()):
        page = tabs.widget(i)
        assert page is not None
        assert page.layout() is not None or page.findChildren(QtWidgets.QWidget)


def test_window_has_the_designed_minimum_size(window):
    assert window.minimumWidth() >= 1200
    assert window.minimumHeight() >= 900


def test_all_pages_can_be_shown(window, qapp):
    for i in range(window.tabWidget.count()):
        window.tabWidget.setCurrentIndex(i)
        qapp.processEvents()
        assert window.tabWidget.currentIndex() == i


def test_widgets_keep_their_object_names(window):
    # The .ui loader and the code both rely on these names.
    for name in ("start_btn", "finish_btn", "skiptarget", "back_btn",
                 "online_efield_btn", "offline_efield_btn",
                 "fitFunctionComboBox", "sampling_spinBox",
                 "widget_3d_viewer", "results_table", "results_summary",
                 "tabWidget", "cfg_save_btn", "cfg_reload_btn",
                 "project_name_edit", "loadmeshlabel", "loadroilabel",
                 "load_e_matrix_label", "loadplacementlabel",
                 "coilspathlineedit", "savePathLineEdit"):
        assert getattr(window, name, None) is not None, name


def test_project_name_starts_untitled(window):
    assert window.project_name_edit.placeholderText().lower().startswith("untitled")


def test_start_is_disabled_before_a_mode_is_chosen(window):
    assert not window.start_btn.isEnabled()
    assert not window.finish_btn.isEnabled()


def test_efield_radios_start_disabled_without_paths(window):
    assert not window.online_efield_btn.isEnabled()
    assert not window.offline_efield_btn.isEnabled()


def test_led_corner_shows_the_three_systems(window):
    corner = getattr(window, "_tab_corner", None)
    assert corner is not None
    texts = [lbl.text() for lbl in corner.findChildren(QtWidgets.QLabel)]
    joined = " ".join(texts).lower()
    for system in ("stimulator", "emg", "robot"):
        assert system in joined


def test_status_leds_exist(window):
    for name in ("stimStatusLabel", "emgStatusLabel", "robotStatusLabel"):
        assert getattr(window, name, None) is not None, name


def test_resize_does_not_raise(window, qapp):
    for size in ((1244, 960), (1600, 1000), (1244, 960), (2000, 1300)):
        window.resize(*size)
        qapp.processEvents()
    assert window.width() > 0


def test_results_panel_cards_scale_with_the_window(window, qapp):
    window.tabWidget.setCurrentIndex(4)
    window.resize(1244, 960)
    qapp.processEvents()
    narrow = window.groupBox_results.minimumWidth()
    window.resize(2000, 1200)
    qapp.processEvents()
    wide = window.groupBox_results.minimumWidth()
    assert wide >= narrow
    assert narrow >= 320


def test_control_action_buttons_are_compact(window, qapp):
    window.show()
    qapp.processEvents()
    window.tabWidget.setCurrentIndex(2)       # Control
    window.resize(1244, 960)
    qapp.processEvents()
    assert window.enableBtn.height() <= 30
    assert window.fireBtn.height() <= 30


def test_robot_view_ends_with_the_robot_card(window, qapp):
    window.show()
    qapp.processEvents()
    window.tabWidget.setCurrentIndex(2)       # Control
    window.resize(1244, 960)
    qapp.processEvents()
    view_bottom = window.robot_view_label.mapTo(
        window, window.robot_view_label.rect().bottomLeft()).y()
    card_bottom = window.groupBox_6.mapTo(
        window, window.groupBox_6.rect().bottomLeft()).y()
    assert view_bottom == card_bottom


def test_target_counters_sit_inside_the_robot_view(window):
    overlay = window._target_overlay
    assert overlay.parentWidget() is window.robot_view_label
    assert window.totaltargets3.parentWidget() is overlay
    assert window.currenttarget.parentWidget() is overlay
    assert window.totaltargets3.property("role") == "value"
    assert window.currenttarget.property("role") == "value"
    assert window.tab3.layout().count() == 3


def test_log_card_has_no_inner_caption_and_a_usable_console(window):
    assert window.groupBox_stats.title() == "Log"
    assert getattr(window, "label_5", None) is None
    assert window.finishedsteps.minimumHeight() >= 100
    assert (window.robot_view_label.sizePolicy().verticalPolicy()
            == QtWidgets.QSizePolicy.Ignored)


def test_width_only_resize_keeps_connections_card_widths(window, qapp):
    window.show()
    qapp.processEvents()
    window.tabWidget.setCurrentIndex(1)       # Connections
    window.resize(1244, 960)
    qapp.processEvents()
    window.resize(1900, 960)
    qapp.processEvents()
    assert window.groupBox_relay.width() > 800
    assert window.groupBox_relay.width() == window.groupBox_2.width()
    assert window.groupBox_relay_info.width() == window.groupBox_stim_info.width()


def test_choice_popups_can_be_sized_twice(window):
    window._size_choice_popups()
    window._size_choice_popups()          # idempotent, must not raise


def test_mesh_colouring_fills_the_results_table(window, qapp):
    window.set_emg_channels(["FDI", "APB"])
    window.update_mesh_coloring({"ADC 0": np.linspace(0.0, 0.5, 25),
                                 "ADC 1": np.linspace(0.0, 0.2, 25)})
    qapp.processEvents()
    table = window.results_table
    assert table.rowCount() == 2
    assert table.item(0, 0).text() == "FDI"          # display name of ADC 0
    assert table.item(0, 2).text() == "24"            # argmax element
    assert "R² 0.500" in window.results_summary.text()


def test_results_summary_without_data(window):
    window._refresh_results_table()
    assert "No R² map yet" in window.results_summary.text()


def test_mesh_colouring_accepts_shorter_arrays_after_longer_ones(window, qapp):
    window.update_mesh_coloring({"ADC 0": np.ones(30)})
    window.update_mesh_coloring({"ADC 0": np.ones(3)})
    qapp.processEvents()
    assert window.results_table.rowCount() == 1


def test_emg_display_names_reach_the_metric_selector(window, qapp):
    window.set_emg_channels(["FDI", "APB"])
    qapp.processEvents()
    combo = window.placement_metric_combo
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert any("FDI" in text for text in labels)
    assert labels[-2:] == ["Trial id", "Aim error"]


def test_project_config_dict_has_the_expected_shape(window):
    cfg = window.get_config_dict()
    for key in ("project_name", "fit_fun", "map_elms", "results_fn",
                "targets_file", "mesh_head_path", "mesh_RIO_path",
                "e_field_path", "coil_path", "emg_config_fn",
                "stimulator_amplitude", "n_repetitions"):
        assert key in cfg


def test_apply_config_dict_ignores_unknown_keys(window):
    before = window.get_config_dict()
    assert window.apply_config_dict({"no_such_setting": 1}) is True
    assert window.get_config_dict() == before


def test_apply_config_dict_sets_values(window):
    assert window.apply_config_dict({"fit_fun": "Sigmoid",
                                     "n_repetitions": 4}) is True
    assert window.fitFunctionComboBox.currentText() == "Sigmoid"
    assert window.n_repetitions_spinBox.value() == 4


@pytest.mark.parametrize("bad", [None, [], "text", 42, ["fit_fun", "Sigmoid"]])
def test_apply_config_dict_rejects_non_mappings(window, bad):
    before = window.get_config_dict()
    assert window.apply_config_dict(bad) is False
    assert window.get_config_dict() == before


def test_flipping_every_page_with_data_does_not_raise(window, qapp):
    window.update_mesh_coloring({"ADC 0": np.linspace(0.0, 0.3, 10)})
    window._mapping_placements = [
        {"trial": 0, "pulse_index": 0, "position": (1.0, 2.0, 3.0),
         "aim_error_mm": 0.2, "intensity": 50, "e_field_mode": "precomputed",
         "mep": {"ADC 0": 0.1}},
    ]
    for i in range(window.tabWidget.count()):
        window.tabWidget.setCurrentIndex(i)
        qapp.processEvents()


def test_screenshot_without_a_file_dialog_path_is_a_no_op(window, monkeypatch):
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: "")
    window.on_screenshot()          # must simply return


def test_export_without_a_path_writes_nothing(window, monkeypatch, tmp_path):
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: "")
    window.on_export_results()
    assert list(tmp_path.glob("*.csv")) == []


def test_close_and_reopen(window, qapp):
    """Closing must not leave Qt objects in a state that breaks a new window."""
    window.close()
    window.deleteLater()
    qapp.processEvents()
    second = type(window)(simulation=True)
    second.resize(1244, 960)
    qapp.processEvents()
    assert second.tabWidget.count() == len(EXPECTED_TABS)
    second.close()
    second.deleteLater()
    qapp.processEvents()


pytestmark = pytest.mark.gui
