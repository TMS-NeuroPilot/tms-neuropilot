"""Config tab: the ``.env`` editor, the mode badge and the study profile.

The store is pointed at ``tmp_path`` in every test; the repository's real
``.env`` is never written.
"""


import os

import pytest
import yaml

from neuropilot.controller.config_store import MANAGED_KEYS, ConfigStore


@pytest.fixture()
def env_file(tmp_path, window):
    """Seed the window's throw-away .env (the store already lives in tmp_path)."""
    path = window._config_store.path
    path.write_text("# lab setup\nRELAY_HOST=localhost\nRELAY_PORT=5000\n"
                    "EMG_CHANNELS=FDI,APB\nKEEP_ME=1\n")
    window._config_store = ConfigStore(path)
    window.on_config_reload()
    return path


# ── Lab scope ──────────────────────────────────────────────────────────

def test_reload_fills_the_widgets_from_env(window, env_file):
    assert window.cfg_relay_host.text() == "localhost"
    assert window.cfg_relay_port.value() == 5000
    assert window.cfg_emg_channels.text() == "FDI,APB"
    assert "Loaded from" in window.cfg_status_label.text()


def test_reload_uses_fallbacks_for_garbage_numbers(window, tmp_path):
    path = tmp_path / ".env"
    path.write_text("RELAY_PORT=abc\nSAMPLING_RATE=\nSTART_MEP=12.9\n")
    window._config_store = ConfigStore(path)
    window.on_config_reload()
    assert window.cfg_relay_port.value() == 5000       # fallback
    assert window.cfg_sampling_rate.value() == 4000     # fallback
    assert window.cfg_mep_start.value() == 12           # truncated


@pytest.mark.parametrize("text,fallback", [("abc", 4000), ("", 4000),
                                           ("12.9", 12), ("-5", -5)])
def test_set_int_parsing(window, text, fallback):
    window._set_int(window.cfg_sampling_rate, text, 4000)
    assert window.cfg_sampling_rate.value() == max(
        window.cfg_sampling_rate.minimum(), min(fallback,
                                                window.cfg_sampling_rate.maximum()))


def test_save_writes_managed_values_and_keeps_the_rest(window, env_file):
    window.cfg_relay_port.setValue(6001)
    window.cfg_emg_channels.setText("FDI,APB,ADM")
    window.on_config_save()

    text = env_file.read_text()
    assert "RELAY_PORT=6001" in text
    assert "EMG_CHANNELS=FDI,APB,ADM" in text
    assert "# lab setup" in text and "KEEP_ME=1" in text
    assert "Saved to" in window.cfg_status_label.text()
    assert "restart" in window.cfg_status_label.text()


def test_save_drops_empty_fields_but_keeps_the_ui_scale(window, env_file):
    # An emptied field must not be written as "KEY=" (that would defeat the
    # .env fallback), so the file keeps its current value for it; the two
    # keys whose empty value is meaningful are written even when blank.
    window.cfg_relay_host.setText("")
    window.cfg_ui_scale.setText("")
    window.on_config_save()
    text = env_file.read_text()
    assert "RELAY_HOST=localhost" in text          # untouched
    assert "NEUROPILOT_UI_SCALE=" in text          # written empty


def test_save_button_writes_only_the_temporary_store(window, qapp, tmp_path):
    # The window fixture points the Config tab at tmp_path; the "Save to .env"
    # button (clicked by the page sweep) must never touch the repo's .env.
    assert str(tmp_path) in str(window._config_store.path)
    window.cfg_relay_host.setText("sweep-host")
    window.cfg_save_btn.click()
    qapp.processEvents()
    assert window._config_store.path.is_file()
    assert "RELAY_HOST=sweep-host" in window._config_store.path.read_text()


def test_save_recreates_a_deleted_folder(window, tmp_path):
    folder = tmp_path / "gone"
    folder.mkdir()
    path = folder / ".env"
    window._config_store = ConfigStore(path)
    folder.rmdir()
    window.cfg_relay_host.setText("host")
    window.on_config_save()
    assert path.is_file()
    assert "RELAY_HOST=host" in path.read_text()


def test_save_to_a_directory_reports_without_crashing(window, tmp_path):
    folder = tmp_path / "env_dir"
    folder.mkdir()
    window._config_store = ConfigStore(folder)
    window.on_config_save()
    assert "Could not write" in window.cfg_status_label.text()


def test_reload_from_a_directory_is_harmless(window, tmp_path):
    folder = tmp_path / "env_dir"
    folder.mkdir()
    window._config_store = ConfigStore(folder)
    window.on_config_reload()          # must not raise
    assert "Loaded from" in window.cfg_status_label.text()


def test_browse_root_uses_the_dialog(window, tmp_path, monkeypatch):
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: str(tmp_path))
    window.on_config_browse_root()
    assert window.cfg_root_folder.text() == str(tmp_path)


def test_browse_root_cancelled_keeps_the_value(window, monkeypatch):
    window.cfg_root_folder.setText("/somewhere")
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: "")
    window.on_config_browse_root()
    assert window.cfg_root_folder.text() == "/somewhere"


def test_managed_key_list_covers_every_widget(window, env_file):
    # Saving must write every managed key (except the deliberately droppable
    # ones), otherwise a field would silently never persist.
    window.on_config_save()
    written = set(ConfigStore(env_file).read())
    assert {"RELAY_HOST", "RELAY_PORT", "EMG_CHANNELS", "ONLINE_FEM_SOLVER"} <= written
    assert written <= set(MANAGED_KEYS)


# ── mode badge ─────────────────────────────────────────────────────────

def test_mode_badge_simulated(window):
    window._apply_config_mode()
    assert window.cfg_mode_badge.text() == "Simulated"
    assert window.cfg_robot_type.isEnabled()
    assert not window.cfg_stim_port.isEnabled()


def test_mode_badge_real(window, controller, monkeypatch):
    # Real mode is a property of the entry point, not of the controller.
    monkeypatch.setattr(window, "simulation", False)
    window.set_controller(controller)
    window._apply_config_mode()
    assert window.cfg_mode_badge.text() == "Real"
    assert not window.cfg_robot_type.isEnabled()
    assert window.cfg_stim_port.isEnabled()


def test_mode_badge_manual(window, controller):
    controller.manual = True
    window.set_controller(controller)
    window._apply_config_mode()
    assert window.cfg_mode_badge.text() == "Manual"
    assert "no robot" in window.cfg_robot_hint.text().lower()


# ── Study scope ────────────────────────────────────────────────────────

STUDY_KEYS = {"fit_fun", "map_elms", "efield_mode", "pulse_shape",
              "n_repetitions", "min_isi", "amplitude", "sampling_rate",
              "cutoff_freq", "tms_pulse_time", "start_mep", "end_mep",
              "emg_channels"}


def test_study_dict_has_every_protocol_key(window):
    assert set(window._study_dict()) == STUDY_KEYS


def test_study_fill_ignores_garbage_values(window):
    window._fill_study_widgets({"map_elms": "many", "n_repetitions": None,
                                "fit_fun": "Exponential", "unknown": 1})
    assert window.cfg_fit_function.currentText() == "Exponential"
    assert window.cfg_subsampling.value() >= 1


def test_study_save_and_load_roundtrip(window, tmp_path, monkeypatch):
    window.cfg_fit_function.setCurrentText("Sigmoid")
    window.cfg_reps.setValue(4)
    window.cfg_emg_channels.setText("FDI,APB")
    target = tmp_path / "study.yaml"
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: str(target))
    window.on_study_save()
    assert target.is_file()
    assert "Saved" in window.cfg_study_status.text()

    window.cfg_fit_function.setCurrentText("Linear")
    window.cfg_reps.setValue(1)
    window.on_study_load()
    assert window.cfg_fit_function.currentText() == "Sigmoid"
    assert window.cfg_reps.value() == 4
    assert "Loaded" in window.cfg_study_status.text()


def test_study_save_into_a_deleted_folder_reports(window, tmp_path, monkeypatch):
    folder = tmp_path / "gone"
    folder.mkdir()
    target = folder / "study.yaml"
    folder.rmdir()
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: str(target))
    window.on_study_save()
    assert "Could not write" in window.cfg_study_status.text()


def test_study_load_of_a_list_is_rejected(window, tmp_path, monkeypatch):
    path = tmp_path / "study.yaml"
    path.write_text("- 1\n- 2\n")
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: str(path))
    window.cfg_fit_function.setCurrentText("Linear")
    window.on_study_load()
    assert "Not a study profile" in window.cfg_study_status.text()
    assert window.cfg_fit_function.currentText() == "Linear"


def test_study_load_of_a_corrupt_file_reports(window, tmp_path, monkeypatch):
    path = tmp_path / "study.yaml"
    path.write_text("key: [unclosed\n")
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: str(path))
    window.on_study_load()
    assert "Could not read" in window.cfg_study_status.text()


def test_study_load_of_a_missing_file_reports(window, tmp_path, monkeypatch):
    monkeypatch.setattr(window, "_file_dialog",
                        lambda *a, **k: str(tmp_path / "nope.yaml"))
    window.on_study_load()
    assert "Could not read" in window.cfg_study_status.text()


def test_study_apply_pushes_into_the_session(window):
    window.cfg_fit_function.setCurrentText("Sigmoid")
    window.cfg_subsampling.setValue(3)
    window.cfg_reps.setValue(2)
    window.cfg_isi.setValue(5)
    window.cfg_amplitude.setValue(44)
    window.on_study_apply()
    assert window.fitFunctionComboBox.currentText() == "Sigmoid"
    assert window.sampling_spinBox.value() == 3
    assert window.n_repetitions_spinBox.value() == 2
    assert window.min_interval_spinBox.value() == 5
    assert window.spinBox.value() == 44
    assert "Applied" in window.cfg_study_status.text()
    assert "needs restart" in window.cfg_study_status.text()


def test_study_apply_sets_the_efield_mode_only_when_enabled(window, monkeypatch):
    monkeypatch.setattr(window.online_efield_btn, "isEnabled", lambda: True)
    window.cfg_efield_mode.setCurrentText("Online")
    window.on_study_apply()
    assert window.online_efield_btn.isChecked()


def test_study_apply_skips_the_efield_mode_when_paths_are_missing(window):
    window.online_efield_btn.setChecked(False)
    window.offline_efield_btn.setChecked(False)
    assert not window.online_efield_btn.isEnabled()      # no paths yet
    window.cfg_efield_mode.setCurrentText("Online")
    window.on_study_apply()
    assert not window.online_efield_btn.isChecked()
    assert "online E-field" not in window.cfg_study_status.text()


def test_study_apply_with_an_unknown_mode_does_not_touch_the_radios(window):
    window.online_efield_btn.setChecked(False)
    window.offline_efield_btn.setChecked(False)
    window.cfg_efield_mode.setCurrentText("something else")
    window.on_study_apply()
    assert not window.online_efield_btn.isChecked()
    assert not window.offline_efield_btn.isChecked()


def test_default_study_path_follows_the_data_folder(window, tmp_path):
    window.cfg_root_folder.setText(str(tmp_path))
    assert window._default_study_path() == str(tmp_path / "study.yaml")


pytestmark = pytest.mark.gui
