"""Choosing and applying a theme in the settings window."""

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from neuropilot.controller import theme


def test_all_themes_are_listed_in_the_config_tab(window):
    combo = window.cfg_theme
    assert [combo.itemText(i) for i in range(combo.count())] == theme.names()


def test_the_default_theme_is_selected_initially(window):
    assert window.cfg_theme.currentText() == window._theme_name


def test_the_shipped_sheet_is_the_default_theme(window):
    tokens = theme.tokens(window._theme_name)
    assert tokens["canvas"] in window.styleSheet()
    assert tokens["accent"] in window.styleSheet()


@pytest.mark.parametrize("name", ["Lab Paper", "Instrument Blue", "Graphite",
                                  "Midnight"])
def test_selecting_a_theme_applies_it_immediately(window, qapp, name):
    window.cfg_theme.setCurrentText(name)
    qapp.processEvents()
    tokens = theme.tokens(name)
    sheet = window.styleSheet()
    assert window._theme_name == name
    assert tokens["canvas"] in sheet and tokens["accent"] in sheet
    # the programmatic colours follow too
    assert window._theme["ink"] == tokens["ink"]
    import pyvista
    background = window.widget_3d_viewer.plotter.background_color
    background = background() if callable(background) else background
    assert pyvista.Color(background).hex_rgb.lower() == tokens["canvas"].lower()
    assert window.widget_mep_trend.figure.get_facecolor()[:3] == pytest.approx(
        tuple(int(tokens["card"][i:i + 2], 16) / 255 for i in (1, 3, 5)), abs=1e-3)


def test_switching_back_restores_the_light_sheet(window, qapp):
    window.cfg_theme.setCurrentText("Midnight")
    qapp.processEvents()
    window.cfg_theme.setCurrentText("Workstation Light")
    qapp.processEvents()
    assert window._theme_name == "Workstation Light"
    assert theme.tokens("Workstation Light")["card"] in window.styleSheet()
    assert "#0F1620" not in window.styleSheet()


def test_selecting_a_theme_persists_it(window, qapp):
    window.cfg_theme.setCurrentText("Graphite")
    qapp.processEvents()
    assert window._lab_profile.read()["UI_THEME"] == "Graphite"


def test_a_saved_theme_is_restored_on_the_next_start(window, qapp, tmp_path):
    # Simulate a previous session: the lab profile already carries the choice.
    window._lab_profile.write({"UI_THEME": "Midnight"})
    window.on_config_reload()
    qapp.processEvents()
    assert window._theme_name == "Midnight"
    assert window.cfg_theme.currentText() == "Midnight"


def test_reload_does_not_rewrite_the_profile(window, qapp):
    window._lab_profile.write({"UI_THEME": "Lab Paper"})
    before = window._lab_profile.path.read_text()
    window.on_config_reload()
    qapp.processEvents()
    assert window._theme_name == "Lab Paper"
    assert window._lab_profile.path.read_text() == before


def test_env_can_pin_the_theme(window, qapp, tmp_path):
    from neuropilot.controller.config_store import ConfigStore
    env = tmp_path / ".env"
    env.write_text("UI_THEME=Instrument Blue\n")
    window._config_store = ConfigStore(env)
    window._lab_profile.write({"UI_THEME": "Graphite"})
    window.on_config_reload()
    qapp.processEvents()
    assert window._theme_name == "Instrument Blue"


def test_saving_the_lab_page_keeps_the_theme(window, qapp):
    window.cfg_theme.setCurrentText("Graphite")
    qapp.processEvents()
    window.on_config_save()
    assert window._lab_profile.read()["UI_THEME"] == "Graphite"


def test_unknown_saved_theme_falls_back(window, qapp):
    window._lab_profile.write({"UI_THEME": "No Such Theme"})
    window.on_config_reload()
    qapp.processEvents()
    assert window._theme_name == theme.DEFAULT_THEME


def test_dark_theme_has_no_white_surfaces(window, qapp):
    window.cfg_theme.setCurrentText("Midnight")
    qapp.processEvents()
    sheet = window.styleSheet()
    assert "#FFFFFF" not in sheet.upper()
    # the widgets that used to stay white are styled by the sheet
    assert "QTableWidget" in sheet and "QPlainTextEdit" in sheet


def test_theme_switch_keeps_the_results_table_and_badge_usable(window, qapp):
    window.cfg_theme.setCurrentText("Graphite")
    qapp.processEvents()
    window.update_mesh_coloring({"ADC 0": [0.1, 0.5, 0.2]})
    window._apply_config_mode()
    qapp.processEvents()
    assert window.results_table.item(0, 2).text() == "1"
    assert window.cfg_mode_badge.text() in ("Simulated", "Real", "Manual")
    # the badge background is the theme's accent tint, not a hard-coded amber
    assert theme.tokens("Graphite")["accent_soft"] in window.cfg_mode_badge.styleSheet()


def test_theme_switch_recolours_the_status_labels(window, qapp):
    from neuropilot.controller.systems.system import SystemStatus

    class System:
        NAME = "EMG"
        DESCRIPTION = "test"
        ERROR_RECOVERIES = {}

        def __init__(self):
            self.status = SystemStatus.OK

        def is_error_state(self):
            return self.status != SystemStatus.OK

    system = System()
    window.initialize({system: system.ERROR_RECOVERIES})
    window.update_system_status(system, SystemStatus.OK)
    window.cfg_theme.setCurrentText("Midnight")
    qapp.processEvents()
    assert theme.tokens("Midnight")["ok"] in window.emgStatusLabel.styleSheet()


def test_charts_follow_the_theme(window, qapp):
    window.cfg_theme.setCurrentText("Lab Paper")
    qapp.processEvents()
    tokens = theme.tokens("Lab Paper")
    trend = window.widget_mep_trend
    axes = trend.figure.axes[0]
    assert axes.get_facecolor()[:3] == pytest.approx(
        tuple(int(tokens["card"][i:i + 2], 16) / 255 for i in (1, 3, 5)), abs=1e-3)
    assert trend.channel_colors["ADC 0"] == tokens["series"][0]


def test_theme_change_survives_a_resize(window, qapp):
    window.cfg_theme.setCurrentText("Instrument Blue")
    qapp.processEvents()
    window.resize(1600, 1100)
    qapp.processEvents()
    assert theme.tokens("Instrument Blue")["accent"] in window.styleSheet()


def test_theme_change_after_resize_keeps_the_scaling(window, qapp):
    window.resize(1500, 1050)
    qapp.processEvents()
    window.cfg_theme.setCurrentText("Graphite")
    qapp.processEvents()
    # the scaler re-applies the new sheet, including its px values
    assert "font-size" in window.styleSheet()
    assert theme.tokens("Graphite")["canvas"] in window.styleSheet()


pytestmark = pytest.mark.gui
