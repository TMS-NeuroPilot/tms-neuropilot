"""Virtual EMG channels: names from .env, sources from the project."""

import re

import numpy as np
import pandas as pd
import pytest

from neuropilot.controller.systems.virtual_emg import VirtualEMG


@pytest.fixture()
def emg(monkeypatch):
    monkeypatch.setenv("EMG_CHANNELS", "FDI,APB,ADM")
    return VirtualEMG()


def test_display_names_come_from_env(emg):
    assert emg.display_names == ["FDI", "APB", "ADM"]
    assert emg.data_channel_names == ["ADC 0", "ADC 1", "ADC 2"]
    assert emg.channel_count == 3


def test_single_channel_configuration(monkeypatch):
    monkeypatch.setenv("EMG_CHANNELS", "FDI")
    emg = VirtualEMG()
    assert emg.channel_count == 1
    assert emg.data_channel_names == ["ADC 0"]


def test_display_name_map_matches_positional_order(emg):
    assert emg.display_name_map() == {"ADC 0": "FDI", "ADC 1": "APB", "ADC 2": "ADM"}


def test_default_mep_model_is_dvs(emg):
    assert emg.model == "dvs"


def test_model_can_be_selected_from_env(monkeypatch):
    monkeypatch.setenv("EMG_CHANNELS", "FDI")
    monkeypatch.setenv("VIRTUAL_MEP_MODEL", "TVS")
    assert VirtualEMG().model == "tvs"


def test_unknown_model_falls_back_to_dvs(monkeypatch):
    monkeypatch.setenv("EMG_CHANNELS", "FDI")
    monkeypatch.setenv("VIRTUAL_MEP_MODEL", "nonsense")
    assert VirtualEMG().model == "dvs"


def test_set_channel_elements_accepts_one_source_per_channel(emg):
    emg.set_channel_elements([11, 22, 33])
    assert emg.channel_elements == [11, 22, 33]


@pytest.mark.parametrize("elements", [[1, 2], [1, 2, 3, 4], []])
def test_set_channel_elements_rejects_a_count_mismatch(emg, elements):
    with pytest.raises(ValueError):
        emg.set_channel_elements(elements)


def test_set_channel_elements_keeps_the_old_sources_on_error(emg):
    before = list(emg.channel_elements)
    with pytest.raises(ValueError):
        emg.set_channel_elements([1])
    assert emg.channel_elements == before


def test_get_latest_emg_df_needs_an_e_matrix(emg):
    with pytest.raises(ValueError):
        emg.get_latest_emg_df()


def test_get_latest_emg_df_needs_all_sources(emg):
    emg.set_e_matrix(np.ones((4, 6000)))
    emg.channel_elements = [1, None, 3]
    with pytest.raises(ValueError):
        emg.get_latest_emg_df()


def test_online_field_overrides_the_precomputed_matrix(emg):
    emg.set_e_matrix(np.zeros((4, 6000)))      # precomputed says "no field"
    emg.set_channel_elements([5, 6, 7])
    field = np.zeros(6000)
    field[[5, 6, 7]] = 90.0                    # online says "strong field"
    df = emg.get_latest_emg_df(e_field_for_mep=field)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["Time", "ADC 0", "ADC 1", "ADC 2"]
    # The online field must actually drive the simulated MEP.
    assert df[["ADC 0", "ADC 1", "ADC 2"]].abs().to_numpy().max() > 0


def test_fallback_uses_the_precomputed_matrix(emg):
    matrix = np.zeros((4, 6000))
    matrix[2, [5, 6, 7]] = 90.0
    emg.set_e_matrix(matrix)
    emg.set_channel_elements([5, 6, 7])
    emg.set_current_state(coil_placement_idx=2, stimuator_amplitude=80)
    df = emg.get_latest_emg_df()
    assert df[["ADC 0", "ADC 1", "ADC 2"]].abs().to_numpy().max() > 0


def test_precomputed_fallback_uses_the_pulse_amplitude(emg, monkeypatch):
    seen = []
    monkeypatch.setattr(
        emg, "_mep_for_field",
        lambda e_field: (seen.append(e_field), (0.0, 0.0))[1])

    matrix = np.zeros((2, 10))
    matrix[1, 3:6] = 10.0
    emg.set_e_matrix(matrix)
    emg.set_channel_elements([3, 4, 5])

    emg.set_current_state(coil_placement_idx=1, stimuator_amplitude=80)
    emg.get_latest_emg_df()
    assert seen[-1] == pytest.approx(10.0 * 1.4 * 80)

    # The next pulse fires at 40 %; the first pulse's MEP must not change.
    emg.set_current_state(coil_placement_idx=1, stimuator_amplitude=40)
    emg.get_latest_emg_df()
    assert seen[-1] == pytest.approx(10.0 * 1.4 * 40)


def test_solver_field_is_already_scaled_and_is_not_scaled_again(emg, monkeypatch):
    seen = []
    monkeypatch.setattr(
        emg, "_mep_for_field",
        lambda e_field: (seen.append(e_field), (0.0, 0.0))[1])

    emg.set_e_matrix(np.zeros((2, 10)))
    emg.set_channel_elements([3, 4, 5])
    emg.set_current_state(coil_placement_idx=1, stimuator_amplitude=80)

    field = np.zeros(10)
    field[3:6] = 5.0
    emg.get_latest_emg_df(e_field_for_mep=field)
    assert seen[-1] == pytest.approx(5.0)


def test_waveform_length_matches_the_configured_segment(emg):
    emg.set_e_matrix(np.ones((1, 6000)))
    emg.set_channel_elements([1, 2, 3])
    df = emg.get_latest_emg_df(e_field_for_mep=np.full(6000, 90.0))
    assert len(df) == int(0.7 * 4000)
    assert df["Time"].iloc[0] == 0.0


def test_field_normalisation_is_a_fraction_of_the_mso_field(emg):
    assert emg._normalise_field(emg.mt) == 0.0
    assert emg._normalise_field(80.0) == pytest.approx(0.8)
    assert emg._normalise_field(120.0) == 1.0


def test_dvs_uses_the_field_in_v_per_m(emg):
    emg.trial_variability = False
    emg.noise_mv = 0.0
    emg.set_e_matrix(np.zeros((1, 3)))
    emg.set_channel_elements([0, 1, 2])

    below = emg.get_latest_emg_df(e_field_for_mep=np.array([40.0] * 3))
    assert below["ADC 0"].abs().max() == pytest.approx(0.0)

    inside = emg.get_latest_emg_df(e_field_for_mep=np.array([80.0] * 3))
    assert inside["ADC 0"].abs().max() > 0.1


def test_tvs_uses_the_mso_normalised_field(emg):
    emg.model = "tvs"
    emg.trial_variability = False
    emg.noise_mv = 0.0
    emg.set_e_matrix(np.zeros((1, 3)))
    emg.set_channel_elements([0, 1, 2])

    low = emg.get_latest_emg_df(e_field_for_mep=np.array([70.0] * 3))
    high = emg.get_latest_emg_df(e_field_for_mep=np.array([100.0] * 3))
    assert high["ADC 0"].abs().max() > low["ADC 0"].abs().max()


def test_details_describe_the_configured_channels(emg):
    published = []
    emg.update_control_panel_func = lambda system, status, message, details=None: published.append(details)
    emg._publish_details()
    details = published[-1]
    assert "FDI, APB, ADM" in details["Channels"]
    assert details["Backend"].startswith("Simulated")


def test_mep_tuning_comes_from_env(monkeypatch):
    monkeypatch.setenv("EMG_CHANNELS", "FDI")
    monkeypatch.setenv("VIRTUAL_MEP_NOISE_MV", "0.02")
    monkeypatch.setenv("VIRTUAL_MEP_TRIAL_VARIABILITY", "off")
    monkeypatch.setenv("VIRTUAL_MEP_MT", "45")
    monkeypatch.setenv("VIRTUAL_MEP_UPPER_LIMIT", "90")
    monkeypatch.setenv("VIRTUAL_MEP_EFIELD_SCALE", "1.2")
    emg = VirtualEMG()
    assert emg.noise_mv == pytest.approx(0.02)
    assert emg.trial_variability is False
    assert emg.mt == pytest.approx(45)
    assert emg.upper_limit == pytest.approx(90)
    assert emg.efield_scale == pytest.approx(1.2)


def test_tvs_coefficients_come_from_env(monkeypatch):
    monkeypatch.setenv("EMG_CHANNELS", "FDI")
    monkeypatch.setenv("VIRTUAL_MEP_MODEL", "tvs")
    values = {f"VIRTUAL_MEP_TVS_P{i}": str(i + 0.5) for i in range(1, 10)}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    emg = VirtualEMG()
    assert [getattr(emg, f"tvs_p{i}") for i in range(1, 10)] == pytest.approx(
        [float(values[f"VIRTUAL_MEP_TVS_P{i}"]) for i in range(1, 10)])


def test_dvs_coefficients_come_from_env(monkeypatch):
    monkeypatch.setenv("EMG_CHANNELS", "FDI")
    monkeypatch.setenv("VIRTUAL_MEP_MODEL", "dvs")
    for key, value in {
            "VIRTUAL_MEP_DVS_X0": "82",
            "VIRTUAL_MEP_DVS_R": "0.2",
            "VIRTUAL_MEP_DVS_SIGMA_X": "6",
            "VIRTUAL_MEP_DVS_AMP": "2",
            "VIRTUAL_MEP_DVS_Y0": "0.02",
            "VIRTUAL_MEP_DVS_SIGMA_Y": "0.3"}.items():
        monkeypatch.setenv(key, value)
    emg = VirtualEMG()
    assert (emg.dvs_x0, emg.dvs_r, emg.dvs_sigma_x, emg.dvs_amp,
            emg.dvs_y0, emg.dvs_sigma_y) == pytest.approx(
        (82, 0.2, 6, 2, 0.02, 0.3))


def test_disabling_noise_and_trial_variability_is_deterministic(monkeypatch):
    monkeypatch.setenv("EMG_CHANNELS", "FDI")
    monkeypatch.setenv("VIRTUAL_MEP_NOISE_MV", "0")
    monkeypatch.setenv("VIRTUAL_MEP_TRIAL_VARIABILITY", "false")
    emg = VirtualEMG()
    emg.set_e_matrix(np.ones((1, 6000)))
    emg.set_channel_elements([1])
    field = np.full(6000, 90.0)
    first = emg.get_latest_emg_df(e_field_for_mep=field)["ADC 0"].to_numpy()
    second = emg.get_latest_emg_df(e_field_for_mep=field)["ADC 0"].to_numpy()
    np.testing.assert_allclose(first, second)


def test_emg_generation_logs_one_rounded_line_per_channel(emg, capsys):
    emg.set_e_matrix(np.zeros((1, 3)))
    emg.set_channel_elements([0, 1, 2])
    emg.get_latest_emg_df(e_field_for_mep=np.full(3, 90.0))
    output = capsys.readouterr().out
    assert "HEREEEEEEEEEE" not in output
    assert "this is the " not in output
    lines = [line for line in output.splitlines()
             if line.startswith("Virtual EMG ")]
    assert len(lines) == emg.channel_count
    assert all(re.search(
        r"\[DVS\]: E=\d+\.\d{2} V/m, MEP=\d+\.\d{2} mV", line)
        for line in lines)
