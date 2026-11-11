"""Virtual EMG channels: names from .env, sources from the project."""

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
