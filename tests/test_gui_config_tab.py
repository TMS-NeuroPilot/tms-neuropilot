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

def test_reload_fills_the_widgets_from_the_lab_profile(window, env_file):
    # Keys the .env fixture does not define come from lab.yaml; RELAY_HOST it
    # does define, so .env wins there (see the override test).
    window._lab_profile.write({"STIMULATOR_PORT": "/dev/ttyUSB7",
                               "ONLINE_FEM_SOLVER": "amg",
                               "EMG_COMPUTER_IP": "10.0.0.7"})
    window.on_config_reload()
    assert window.cfg_stim_port.text() == "/dev/ttyUSB7"
    assert window.cfg_fem_solver.currentText() == "amg"
    assert window.cfg_emg_ip.text() == "10.0.0.7"
    # EMG_CHANNELS still comes from .env
    assert window.cfg_emg_channels.text() == "FDI,APB"
    assert "Loaded lab.yaml" in window.cfg_status_label.text()


def test_env_overrides_the_lab_profile(window, env_file):
    window._lab_profile.write({"RELAY_HOST": "lab-host"})
    window.on_config_reload()          # env_file has RELAY_HOST=localhost
    assert window.cfg_relay_host.text() == "localhost"
    assert ".env overrides" in window.cfg_relay_host.toolTip()
    assert "overridden by .env" in window.cfg_status_label.text()


def test_missing_lab_profile_falls_back_to_defaults(window):
    window._lab_profile.write({})
    window.on_config_reload()
    assert window.cfg_relay_host.text()  # a default, never empty
    assert window.cfg_relay_port.value() > 0


def test_unreadable_lab_profile_falls_back(window):
    window._lab_profile.path.parent.mkdir(parents=True, exist_ok=True)
    window._lab_profile.path.write_text("key: [unclosed\n")
    window.on_config_reload()          # must not raise
    assert window.cfg_relay_port.value() == 5000


def test_lab_profile_list_is_ignored(window):
    window._lab_profile.path.parent.mkdir(parents=True, exist_ok=True)
    window._lab_profile.path.write_text("- 1\n- 2\n")
    window.on_config_reload()
    assert window.cfg_relay_host.text() == "127.0.0.1"


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


# ── saving ────────────────────────────────────────────────────────────

def test_save_writes_the_hardware_values_to_lab_yaml(window, env_file):
    window.cfg_relay_port.setValue(6001)
    window.cfg_emg_ip.setText("192.168.1.9")
    window.on_config_save()
    lab = window._lab_profile.read()
    assert lab["RELAY_PORT"] == "6001"
    assert lab["EMG_COMPUTER_IP"] == "192.168.1.9"
    assert "Saved lab.yaml" in window.cfg_status_label.text()
    assert "restart" in window.cfg_status_label.text()


def test_save_keeps_env_and_writes_the_analysis_keys(window, tmp_path):
    env = tmp_path / ".env"
    env.write_text("# lab setup\nKEEP_ME=1\n")
    window._config_store = ConfigStore(env)
    window.cfg_emg_channels.setText("FDI,APB,ADM")
    window.cfg_sampling_rate.setValue(8000)
    window.on_config_save()
    text = env.read_text()
    assert "EMG_CHANNELS=FDI,APB,ADM" in text
    assert "SAMPLING_RATE=8000" in text
    assert "# lab setup" in text and "KEEP_ME=1" in text
    # ... and the hardware keys are no longer forced into .env
    assert "RELAY_PORT=" not in text
    assert "RELAY_PORT" not in window._config_store.read()


def test_save_reports_keys_pinned_by_env(window, env_file):
    # env_file defines RELAY_PORT=5000, so the lab value is overridden.
    window.cfg_relay_port.setValue(6002)
    window.on_config_save()
    assert "pinned by .env" in window.cfg_status_label.text()
    assert window._lab_profile.read()["RELAY_PORT"] == "6002"


def test_save_drops_empty_fields_but_keeps_the_ui_scale(window, env_file):
    window.cfg_relay_host.setText("")
    window.cfg_ui_scale.setText("")
    window.on_config_save()
    lab = window._lab_profile.read()
    assert "RELAY_HOST" not in lab          # empty means "use the default"
    assert lab["NEUROPILOT_UI_SCALE"] == ""


def test_save_recreates_a_deleted_folder(window, tmp_path):
    folder = tmp_path / "gone"
    folder.mkdir()
    path = folder / "lab.yaml"
    window._lab_profile = type(window._lab_profile)(path)
    folder.rmdir()
    window.cfg_relay_host.setText("host")
    window.on_config_save()
    assert path.is_file()
    assert "RELAY_HOST: host" in path.read_text()


def test_save_to_a_lab_directory_reports_without_crashing(window, tmp_path):
    folder = tmp_path / "lab_dir"
    folder.mkdir()
    window._lab_profile = type(window._lab_profile)(folder)
    window.on_config_save()
    assert "Could not write" in window.cfg_status_label.text()


def test_save_to_an_env_directory_reports_without_crashing(window, tmp_path):
    folder = tmp_path / "env_dir"
    folder.mkdir()
    window._config_store = ConfigStore(folder)
    window.on_config_save()
    assert "could not write" in window.cfg_status_label.text().lower()


def test_reload_from_a_directory_is_harmless(window, tmp_path):
    folder = tmp_path / "env_dir"
    folder.mkdir()
    window._config_store = ConfigStore(folder)
    window.on_config_reload()          # must not raise
    assert "Loaded lab.yaml" in window.cfg_status_label.text()


def test_browse_root_uses_the_dialog(window, tmp_path, monkeypatch):
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: str(tmp_path))
    window.on_config_browse_root()
    assert window.cfg_root_folder.text() == str(tmp_path)


def test_browse_root_cancelled_keeps_the_value(window, monkeypatch):
    window.cfg_root_folder.setText("/somewhere")
    monkeypatch.setattr(window, "_file_dialog", lambda *a, **k: "")
    window.on_config_browse_root()
    assert window.cfg_root_folder.text() == "/somewhere"


def test_save_writes_every_lab_key(window, env_file):
    from neuropilot.lab_profile import LAB_KEYS
    window.on_config_save()
    written = set(window._lab_profile.read())
    assert {"RELAY_PORT", "ROBOT", "ONLINE_FEM_SOLVER",
            "EMG_COMPUTER_IP"} <= written
    assert written <= set(LAB_KEYS)


def test_save_button_writes_only_the_temporary_files(window, qapp, tmp_path):
    # The page sweep clicks "Save lab profile"; it must only touch tmp_path.
    assert str(tmp_path) in str(window._lab_profile.path)
    assert str(tmp_path) in str(window._config_store.path)
    window.cfg_relay_host.setText("sweep-host")
    window.cfg_save_btn.click()
    qapp.processEvents()
    assert window._lab_profile.path.is_file()
    assert "RELAY_HOST: sweep-host" in window._lab_profile.path.read_text()


# ── mode badge ─────────────────────────────────────────────────────────

def test_mode_badge_simulated(window):
    window._apply_config_mode()
    assert window.cfg_mode_badge.text() == "Simulated"
    assert window.cfg_mode_badge.property("role") == "badge"
    assert "font-size" not in window.cfg_mode_badge.styleSheet()
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


# ── robot selector ─────────────────────────────────────────────────────

def test_robot_selector_lists_the_registry(window):
    from neuropilot.sim_robot.robots import labels
    combo = window.cfg_robot_type
    shown = [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]
    assert shown == [(label, key) for key, label in labels()]


def test_robot_selector_saves_the_key(window):
    window.on_config_save()
    assert window._lab_profile.read()["ROBOT"] == "omron"


def test_robot_selector_restores_the_key(window):
    window._set_robot_key("omron")
    assert window._robot_key() == "omron"
    assert window.cfg_robot_type.currentText() == "Omron TM5X-700"


def test_unknown_robot_stays_visible(window):
    # A machine whose robot is not in this build must not be silently
    # replaced by another one.
    window._set_robot_key("kuka")
    assert window.cfg_robot_type.currentText().strip() == "kuka"
    assert window._robot_key() == "kuka"


# ── Simulation scope ───────────────────────────────────────────────────

def test_simulation_page_is_right_of_the_subject_page(window):
    titles = [window.cfg_tabs.tabText(i) for i in range(window.cfg_tabs.count())]
    assert titles == ["Lab (hardware)", "Study (mapping)",
                      "Subject (files)", "Simulation"]
    assert window.cfg_tabs.widget(3) is window.cfg_tab_simulation


def test_simulation_reload_fills_from_env(window, tmp_path):
    env = tmp_path / ".env"
    env.write_text("VIRTUAL_MEP_NOISE_MV=0.02\n"
                   "VIRTUAL_MEP_TRIAL_VARIABILITY=false\n"
                   "VIRTUAL_MEP_MT=45\n"
                   "VIRTUAL_MEP_UPPER_LIMIT=90\n"
                   "VIRTUAL_MEP_EFIELD_SCALE=1.2\n")
    window._config_store = ConfigStore(env)
    window.on_config_reload()
    assert window.cfg_sim_noise.value() == pytest.approx(0.02)
    assert not window.cfg_sim_trial.isChecked()
    assert window.cfg_sim_mt.value() == pytest.approx(45)
    assert window.cfg_sim_upper.value() == pytest.approx(90)
    assert window.cfg_sim_scale.value() == pytest.approx(1.2)


def test_simulation_save_writes_the_env_keys(window, tmp_path):
    env = tmp_path / ".env"
    env.write_text("# keep me\nKEEP_ME=1\n")
    window._config_store = ConfigStore(env)
    window.cfg_sim_noise.setValue(0.01)
    window.cfg_sim_trial.setChecked(False)
    window.cfg_sim_mt.setValue(50)
    window.cfg_sim_upper.setValue(90)
    window.cfg_sim_scale.setValue(1.3)
    window.on_sim_save()
    text = env.read_text()
    assert "VIRTUAL_MEP_NOISE_MV=0.01" in text
    assert "VIRTUAL_MEP_TRIAL_VARIABILITY=false" in text
    assert "VIRTUAL_MEP_MT=50" in text
    assert "VIRTUAL_MEP_UPPER_LIMIT=90" in text
    assert "VIRTUAL_MEP_EFIELD_SCALE=1.3" in text
    assert "KEEP_ME=1" in text
    assert "restart" in window.cfg_sim_status.text()


def test_simulation_save_rejects_an_upper_limit_at_the_threshold(window, tmp_path):
    env = tmp_path / ".env"
    window._config_store = ConfigStore(env)
    window.cfg_sim_mt.setValue(60)
    window.cfg_sim_upper.setValue(60)
    window.on_sim_save()
    assert "above the motor threshold" in window.cfg_sim_status.text()
    assert not env.exists() or "VIRTUAL_MEP" not in env.read_text()


def test_simulation_page_disabled_in_real_mode(window, controller, monkeypatch):
    monkeypatch.setattr(window, "simulation", False)
    window.set_controller(controller)
    window._apply_config_mode()
    assert not window.cfg_sim_noise.isEnabled()
    assert not window.cfg_sim_save_btn.isEnabled()
    assert "ignored" in window.cfg_sim_hint.text()


def test_simulation_source_summary_points_to_the_project(window):
    window.cfg_emg_channels.setText("FDI,APB")
    window.emg_config_label.setText("/tmp/sources.yaml")
    window._refresh_simulation_summary()
    text = window.cfg_sim_sources.toPlainText()
    assert "FDI,APB" in text
    assert "sources.yaml" in text
    assert window.cfg_sim_sources.toolTip() == "/tmp/sources.yaml"
    assert window.cfg_sim_project_btn.text() == "Edit in Project"


def test_mode_badge_training(window, controller, monkeypatch):
    monkeypatch.setattr(window, "training", True)
    monkeypatch.setattr(window, "simulation", False)
    controller.manual = True
    window.set_controller(controller)
    window._apply_config_mode()
    assert window.cfg_mode_badge.text() == "Training"
    assert window.cfg_sim_noise.isEnabled()
    assert window.cfg_stim_port.isEnabled()
    assert not window.cfg_emg_ip.isEnabled()
    assert "Training" in window.cfg_emg_hint.text()


def test_simulation_save_is_allowed_in_training(window, tmp_path, monkeypatch):
    monkeypatch.setattr(window, "training", True)
    monkeypatch.setattr(window, "simulation", False)
    env = tmp_path / ".env"
    window._config_store = ConfigStore(env)
    window.cfg_sim_noise.setValue(0.02)
    window.on_sim_save()
    assert "VIRTUAL_MEP_NOISE_MV=0.02" in env.read_text()


def test_every_config_dropdown_gets_the_tall_input_style(window, qapp):
    from PyQt5 import QtWidgets
    window.tabWidget.setCurrentWidget(window.tab6)
    qapp.processEvents()
    combos = window.cfg_tabs.findChildren(QtWidgets.QComboBox)
    assert combos
    for combo in combos:
        assert combo.sizeHint().height() >= 48, combo.objectName()
        assert combo.view().sizeHintForRow(0) >= 44, combo.objectName()
        expected = combo.view().sizeHintForRow(0) * min(combo.count(), 8)
        assert combo.view().minimumHeight() >= expected, combo.objectName()
