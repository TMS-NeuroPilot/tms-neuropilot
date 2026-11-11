"""Placement records and the CSV export of the Cortical-results page."""

import csv
from types import SimpleNamespace

import numpy as np
import pytest

from neuropilot.controller.control_panel import MainWindow
from neuropilot.controller.pipeline_controller import PipelineController

placement_records = PipelineController.placement_records
write_csv = MainWindow._write_placements_csv
channel_keys = MainWindow._channel_keys
display_name = MainWindow._display_name


def realized_targets(n=2):
    return {
        "idx": list(range(n)),
        "idx_pulse": list(range(n)),
        "time": [0.0 + i for i in range(n)],
        "x_realized": [1.0 + i for i in range(n)],
        "y_realized": [2.0 + i for i in range(n)],
        "z_realized": [3.0 + i for i in range(n)],
        "rota_realized": [0.0] * n,
        "rotb_realized": [0.0] * n,
        "rotc_realized": [0.0] * n,
        "x_target": [1.5 + i for i in range(n)],
        "y_target": [2.0 + i for i in range(n)],
        "z_target": [3.0 + i for i in range(n)],
        "rota_target": [0.0] * n,
        "rotb_target": [0.0] * n,
        "rotc_target": [0.0] * n,
        "pressure": [1.2] * n,
        "intensity": [55, 60],
    }


def make_controller(modes=("precomputed", "online")):
    return SimpleNamespace(
        realized_targets=realized_targets(),
        mep_history={"ADC 0": [0.5, 0.7], "ADC 1": [0.1]},
        pulse_modes=list(modes),
    )


@pytest.fixture()
def controller():
    return make_controller()


def make_panel(records, keys=("ADC 0", "ADC 1"), names=("FDI", "APB")):
    panel = SimpleNamespace(
        _mapping_scores={k: None for k in keys},
        _mapping_placements=records,
        _emg_display_names=list(names),
    )
    panel._channel_keys = lambda: channel_keys(panel)
    panel._display_name = lambda key: display_name(panel, key)
    return panel


def test_one_record_per_pulse(controller):
    records = placement_records(make_controller())
    assert len(records) == 2
    assert [r["trial"] for r in records] == [0, 1]


def test_aim_error_is_the_distance_to_the_planned_point(controller):
    records = placement_records(make_controller())
    np.testing.assert_allclose([r["aim_error_mm"] for r in records], [0.5, 0.5])


def test_missing_meps_become_none(controller):
    records = placement_records(make_controller())
    assert records[0]["mep"] == {"ADC 0": 0.5, "ADC 1": 0.1}
    assert records[1]["mep"] == {"ADC 0": 0.7, "ADC 1": None}


def test_each_record_names_the_e_field_source(controller):
    records = placement_records(make_controller(modes=("precomputed", "online")))
    assert [r["e_field_mode"] for r in records] == ["precomputed", "online"]


def test_missing_modes_do_not_break_records(controller):
    ctrl = make_controller(modes=())
    records = placement_records(ctrl)
    assert [r["e_field_mode"] for r in records] == [None, None]


def test_repeated_record_generation_is_stable(controller):
    ctrl = make_controller()
    first = placement_records(ctrl)
    second = placement_records(ctrl)
    assert first[0]["position"] == second[0]["position"]
    assert first[0]["mep"] == second[0]["mep"]


def test_csv_header_and_rows(tmp_path, controller):
    records = placement_records(make_controller())
    panel = make_panel(records)
    path = tmp_path / "placements.csv"
    write_csv(panel, path)

    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    assert header[:3] == ["trial", "pulse_index", "target_index"]
    assert header[-3:] == ["e_field_mode", "mep_FDI_mV", "mep_APB_mV"]
    assert len(rows) == 3

    first = dict(zip(header, rows[1]))
    assert first["trial"] == "0"
    assert first["e_field_mode"] == "precomputed"
    assert float(first["aim_error_mm"]) == 0.5
    assert float(first["mep_FDI_mV"]) == 0.5
    assert float(first["mep_APB_mV"]) == 0.1

    second = dict(zip(header, rows[2]))
    assert second["e_field_mode"] == "online"
    assert second["mep_APB_mV"] == ""          # missing MEP stays empty


def test_csv_handles_records_without_geometry(tmp_path):
    record = {"trial": 0, "pulse_index": 0, "target_index": 0,
              "aim_error_mm": 0.0, "intensity": 50, "pressure": 1.0,
              "mep": {"ADC 0": 0.2}, "e_field_mode": None}
    panel = make_panel([record], keys=("ADC 0",), names=("FDI",))
    path = tmp_path / "p.csv"
    write_csv(panel, path)
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2
    assert rows[1][3:12] == [""] * 9           # x/y/z realized + rotation + target


class TestResultsSummaryPrefix:
    def test_empty_session(self):
        assert MainWindow._results_prefix([]) == ""
        assert MainWindow._results_prefix(None) == ""

    def test_single_mode_session(self):
        records = [{"e_field_mode": "precomputed"}] * 4
        assert MainWindow._results_prefix(records) == "4 pulses · "

    def test_mixed_session_names_the_online_share(self):
        records = ([{"e_field_mode": "precomputed"}] * 3
                   + [{"e_field_mode": "online"}] * 2)
        assert MainWindow._results_prefix(records) == "5 pulses (2 online) · "

    def test_online_only_session(self):
        records = [{"e_field_mode": "online"}] * 3
        assert MainWindow._results_prefix(records) == "3 pulses · "

    def test_records_without_a_mode_are_still_counted(self):
        records = [{"e_field_mode": None}, {"e_field_mode": "online"}]
        assert MainWindow._results_prefix(records) == "2 pulses (1 online) · "


def test_channel_keys_are_sorted_numerically():
    panel = make_panel([], keys=("ADC 10", "ADC 2", "ADC 1"))
    assert panel._channel_keys() == ["ADC 1", "ADC 2", "ADC 10"]


def test_display_names_map_positionally():
    panel = make_panel([], keys=("ADC 0", "ADC 1"), names=("FDI", "APB"))
    assert panel._display_name("ADC 0") == "FDI"
    assert panel._display_name("ADC 1") == "APB"


def test_display_name_falls_back_to_the_key():
    panel = make_panel([], keys=("ADC 9",), names=("FDI",))
    assert panel._display_name("ADC 9") == "ADC 9"
    assert panel._display_name("odd") == "odd"
