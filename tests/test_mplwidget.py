"""The MEP trend plot: excluded pulses and short channel histories."""


import numpy as np
import pytest

pytest.importorskip("PyQt5.QtWidgets")


@pytest.fixture()
def trend(qapp, gui_env):
    from neuropilot.controller.mplwidget import MplGraphWidget
    widget = MplGraphWidget()
    widget.resize(600, 300)
    qapp.processEvents()
    return widget


def test_plot_draws_one_line_per_channel(trend, qapp):
    trend.update_as_trend([0, 1, 2], {"ADC 0": [0.1, 0.2, 0.3]})
    qapp.processEvents()
    assert "ADC 0" in trend.lines


def test_excluded_pulses_are_dropped(trend, qapp):
    trend.update_as_trend([0, 1, 2, 3], {"ADC 0": [0.1, 0.2, 0.3, 0.4]},
                          exclusion={1, 3})
    qapp.processEvents()
    xdata = list(trend.lines["ADC 0"].get_xdata())
    assert xdata == [1, 3]


def test_exclusion_beyond_a_short_history_is_ignored(trend, qapp):
    # Pulse 5 was excluded, but this channel only has three samples.
    trend.update_as_trend([0, 1, 2], {"ADC 0": [0.1, 0.2, 0.3]},
                          exclusion={5})
    qapp.processEvents()
    assert len(trend.lines["ADC 0"].get_xdata()) == 3


def test_exclusion_mixing_valid_and_invalid_indices(trend, qapp):
    trend.update_as_trend([0, 1], {"ADC 0": [0.1, 0.2]},
                          exclusion={1, 9})
    qapp.processEvents()
    assert list(trend.lines["ADC 0"].get_xdata()) == [1]


def test_more_indices_than_values_is_truncated(trend, qapp):
    trend.update_as_trend([0, 1, 2, 3, 4], {"ADC 0": [0.1, 0.2]})
    qapp.processEvents()
    assert len(trend.lines["ADC 0"].get_ydata()) == 2


def test_empty_history_is_harmless(trend, qapp):
    trend.update_as_trend([], {})
    qapp.processEvents()
    assert trend.lines == {}


def test_unknown_channel_is_not_plotted(trend, qapp):
    trend.update_as_trend([0, 1], {"NOT A CHANNEL": [1.0, 2.0]})
    qapp.processEvents()
    assert "NOT A CHANNEL" not in trend.lines


def test_channel_names_can_be_reset(trend, qapp):
    trend.set_channels(["FDI", "APB"])
    qapp.processEvents()          # must not raise


pytestmark = pytest.mark.gui
