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
    from neuropilot.controller.systems import virtual_emg as vemg

    seen = []
    monkeypatch.setattr(
        vemg, "scale_e_for_dvs",
        lambda e_field, mt, upper_limit: (seen.append(e_field), 0.0)[1])
    monkeypatch.setattr(
        vemg, "get_virtual_mep_tvs",
        lambda values, trial_variability: np.zeros(int(0.7 * 4000)))

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
    from neuropilot.controller.systems import virtual_emg as vemg

    seen = []
    monkeypatch.setattr(
        vemg, "scale_e_for_dvs",
        lambda e_field, mt, upper_limit: (seen.append(e_field), 0.0)[1])
    monkeypatch.setattr(
        vemg, "get_virtual_mep_tvs",
        lambda values, trial_variability: np.zeros(int(0.7 * 4000)))

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
        r"E=\d+\.\d{2} V/m, x=\d+\.\d{2}, MEP=\d+\.\d{2} mV", line)
        for line in lines)
