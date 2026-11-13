"""Controller file loaders under bad input.

No Qt here: these are the paths that used to raise inside GUI slots or die
mid-run (missing files, folders, corrupt HDF5, missing datasets, wrong
shapes, wrong dtypes, out-of-range orders, unusable ROI files).
"""

import os

import h5py
import numpy as np
import pytest
import yaml

from neuropilot.controller.OnlineFEMManager import OnlineFEMManager
from neuropilot.controller.pipeline_controller import (
    parse_target_order_file, read_simnibs_targets, read_target_order,
    stamped_results_filename, validate_simnibs_targets_file,
)


# ── E-field matrix ─────────────────────────────────────────────────────

def test_valid_matrix_loads(controller, e_matrix_hdf5):
    path = e_matrix_hdf5(4, 12)
    controller.set_e_matrix_file(str(path))
    assert controller.e_matrix.shape == (4, 12)
    assert controller.n_positions == 4 and controller.n_elms == 12
    assert controller.emg_computer.e_matrix is controller.e_matrix


@pytest.mark.parametrize("name", ["missing.hdf5", "folder", "text.hdf5",
                                  "empty.hdf5"])
def test_unusable_matrix_clears_the_state(controller, tmp_path, name):
    if name == "folder":
        path = tmp_path / "folder"
        path.mkdir()
    elif name == "text.hdf5":
        path = tmp_path / name
        path.write_text("not hdf5")
    elif name == "empty.hdf5":
        path = tmp_path / name
        path.write_bytes(b"")
    else:
        path = tmp_path / name
    controller.set_e_matrix_file(str(path))
    assert controller.e_matrix is None
    assert controller.n_elms is None


def test_matrix_without_the_dataset_is_rejected(controller, h5file):
    path = h5file({"other": np.zeros(3)}, "no_e.hdf5")
    controller.set_e_matrix_file(str(path))
    assert controller.e_matrix is None


@pytest.mark.parametrize("data", [
    np.zeros(10),                      # 1-D
    np.zeros((2, 3, 4)),              # 3-D
    np.zeros((0, 4)),                 # no placements
    np.array([[b"a", b"b"], [b"c", b"d"]]),   # byte strings
])
def test_matrix_with_a_bad_layout_is_rejected(controller, h5file, data):
    path = h5file({"E_mag": data}, "bad_e.hdf5")
    controller.set_e_matrix_file(str(path))
    assert controller.e_matrix is None
    assert controller.n_elms is None


def test_clearing_the_path_clears_the_matrix(controller, e_matrix_hdf5):
    controller.set_e_matrix_file(str(e_matrix_hdf5(2, 5)))
    assert controller.e_matrix is not None
    controller.set_e_matrix_file("")
    assert controller.e_matrix is None


def test_subsampling_survives_a_missing_matrix(controller):
    controller.set_map_elms(4)             # n_elms is -1: must not raise
    controller.n_elms = None
    controller.set_map_elms(2)             # ... nor with None
    assert controller.elm_idx_list in (None, [])


def test_subsampling_index_list_after_loading(controller, e_matrix_hdf5):
    controller.set_e_matrix_file(str(e_matrix_hdf5(2, 10)))
    controller.set_map_elms(3)
    np.testing.assert_array_equal(controller.elm_idx_list, np.arange(0, 10, 3))
    controller.set_map_elms(1)
    assert controller.elm_idx_list is None


# ── coil targets ───────────────────────────────────────────────────────

def test_validate_targets_accepts_a_good_file(placements_hdf5):
    assert validate_simnibs_targets_file(str(placements_hdf5(6))) == 6


@pytest.mark.parametrize("kind", ["missing", "folder", "text", "no_dataset",
                                  "flat", "empty", "strings"])
def test_validate_targets_rejects_bad_files(tmp_path, h5file, kind):
    if kind == "missing":
        path = tmp_path / "nope.hdf5"
    elif kind == "folder":
        path = tmp_path / "dir"
        path.mkdir()
    elif kind == "text":
        path = tmp_path / "text.hdf5"
        path.write_text("hello")
    elif kind == "no_dataset":
        path = h5file({"other": np.zeros(2)}, "no_mats.hdf5")
    elif kind == "flat":
        path = h5file({"matsimnibs": np.zeros((4, 4))}, "flat.hdf5")
    elif kind == "empty":
        path = h5file({"matsimnibs": np.zeros((4, 4, 0))}, "empty.hdf5")
    else:
        path = h5file({"matsimnibs": np.full((4, 4, 2), b"x")}, "str.hdf5")
    with pytest.raises(ValueError):
        validate_simnibs_targets_file(str(path))


def test_read_targets_returns_positions_and_angles(placements_hdf5):
    queue = read_simnibs_targets(str(placements_hdf5(3)))
    assert len(queue) == 3
    assert all(pos.shape == (3,) and ang.shape == (3,) for pos, ang in queue)


def test_read_targets_rejects_a_nan_matrix(h5file):
    mats = np.repeat(np.eye(4)[:, :, None], 2, axis=2)
    mats[0, 0, 0] = np.nan
    path = h5file({"matsimnibs": mats}, "nan.hdf5")
    with pytest.raises(ValueError):
        read_simnibs_targets(str(path))


def test_read_targets_is_repeatable(placements_hdf5):
    path = str(placements_hdf5(3))
    first = read_simnibs_targets(path)
    second = read_simnibs_targets(path)
    np.testing.assert_allclose(first[1][0], second[1][0])


def test_target_order_accepts_a_plain_list(tmp_path):
    path = tmp_path / "order.txt"
    path.write_text("2\n0\n1\n")
    np.testing.assert_array_equal(parse_target_order_file(str(path)), [2, 0, 1])


@pytest.mark.parametrize("text", ["", "a\nb\n", "1.5\n2\n", "-1\n2\n"])
def test_target_order_rejects_garbage(tmp_path, text):
    path = tmp_path / "order.txt"
    path.write_text(text)
    with pytest.raises(ValueError):
        parse_target_order_file(str(path))


def test_target_order_range_is_checked(tmp_path):
    path = tmp_path / "order.txt"
    path.write_text("0\n9\n")
    with pytest.raises(ValueError):
        read_target_order(str(path), 3)


def test_target_order_in_range_passes(tmp_path):
    path = tmp_path / "order.txt"
    path.write_text("2\n0\n")
    np.testing.assert_array_equal(read_target_order(str(path), 3), [2, 0])


def test_set_targets_file_clears_an_unusable_file(controller, tmp_path):
    bad = tmp_path / "bad.hdf5"
    bad.write_text("x")
    controller.set_targets_file(str(bad))
    assert controller.targets_file is None


def test_set_targets_file_reports_the_count(controller, placements_hdf5):
    controller.set_targets_file(str(placements_hdf5(4)))
    assert controller.targets_file is not None
    assert controller.target_order.shape == (4,)


def test_set_targets_file_with_none_clears(controller, placements_hdf5):
    controller.set_targets_file(str(placements_hdf5(2)))
    controller.set_targets_file(None)
    assert controller.targets_file is None


# ── EMG channel sources ────────────────────────────────────────────────

def write_emg(path, data):
    path.write_text(yaml.safe_dump(data))
    return path


def test_emg_config_assigns_element_ids(controller, tmp_path):
    n = len(controller.emg_computer.display_names)
    path = write_emg(tmp_path / "emg.yaml",
                     {"sources": [{"element_id": i} for i in range(n)]})
    controller.set_emg_config(str(path))
    assert controller.emg_computer.channel_elements == list(range(n))


def test_emg_config_accepts_a_bare_list(controller, tmp_path):
    n = len(controller.emg_computer.display_names)
    path = write_emg(tmp_path / "emg.yaml", [{"element_id": i} for i in range(n)])
    controller.set_emg_config(str(path))
    assert controller.emg_computer.channel_elements == list(range(n))


@pytest.mark.parametrize("content", [
    {"sources": []},
    {"sources": [{"nonsense": 1}]},
    {"sources": "not a list"},
    "just a string",
])
def test_emg_config_rejects_bad_structure(controller, tmp_path, content):
    before = list(controller.emg_computer.channel_elements)
    path = write_emg(tmp_path / "emg.yaml", content)
    controller.set_emg_config(str(path))
    assert controller.emg_computer.channel_elements == before


def test_emg_config_rejects_a_count_mismatch(controller, tmp_path):
    before = list(controller.emg_computer.channel_elements)
    path = write_emg(tmp_path / "emg.yaml",
                     {"sources": [{"element_id": 1}] * 99})
    controller.set_emg_config(str(path))
    assert controller.emg_computer.channel_elements == before


def test_emg_config_corrupt_yaml_is_ignored(controller, tmp_path):
    path = tmp_path / "emg.yaml"
    path.write_text("sources: [unclosed\n")
    controller.set_emg_config(str(path))            # no exception


def test_emg_config_missing_file_is_ignored(controller, tmp_path):
    controller.set_emg_config(str(tmp_path / "nope.yaml"))


def test_emg_config_xyz_without_a_roi_is_refused(controller, tmp_path):
    before = list(controller.emg_computer.channel_elements)
    path = write_emg(tmp_path / "emg.yaml",
                     {"sources": [{"xyz": [0, 0, 0]}] * len(before)})
    controller.set_emg_config(str(path))
    assert controller.emg_computer.channel_elements == before


def test_emg_config_with_a_corrupt_roi_keeps_the_defaults(controller, tmp_path,
                                                          monkeypatch):
    from types import SimpleNamespace
    n = len(controller.emg_computer.display_names)
    before = list(controller.emg_computer.channel_elements)
    bad_roi = tmp_path / "roi.hdf5"
    bad_roi.write_text("garbage")
    controller.control_panel = SimpleNamespace(loadroilabel=SimpleNamespace(
        text=lambda: str(bad_roi)))
    path = write_emg(tmp_path / "emg.yaml",
                     {"sources": [{"xyz": [0, 0, 0]}] * n})
    controller.set_emg_config(str(path))            # must not raise
    assert controller.emg_computer.channel_elements == before


def test_emg_config_projects_xyz_to_the_nearest_element(controller, tmp_path,
                                                        h5file, monkeypatch):
    from types import SimpleNamespace
    n = len(controller.emg_computer.display_names)
    nodes = np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [0.0, 10.0, 0.0],
                      [0.0, 0.0, 10.0], [10.0, 10.0, 0.0], [20.0, 0.0, 0.0]])
    tris = np.array([[0, 1, 2], [1, 2, 3], [2, 3, 4], [3, 4, 5]])
    roi = h5file({"mesh/nodes/node_coord": nodes,
                  "mesh/elm/triangle_number_list": tris}, "roi.hdf5")
    controller.control_panel = SimpleNamespace(loadroilabel=SimpleNamespace(
        text=lambda: str(roi)))
    centres = nodes[tris].mean(axis=1)
    path = write_emg(tmp_path / "emg.yaml",
                     {"sources": [{"xyz": centres[2].tolist()}] * n})
    controller.set_emg_config(str(path))
    assert controller.emg_computer.channel_elements == [2] * n


# ── results file naming ────────────────────────────────────────────────

@pytest.mark.parametrize("path,stamp,expected", [
    ("results.csv", "S", "resultsS.csv"),
    ("/tmp/a/results.csv", "S", "/tmp/a/resultsS.csv"),
    ("/tmp/my.csv.dir/results.csv", "S", "/tmp/my.csv.dir/resultsS.csv"),
    ("noext", "S", "noextS.csv"),
])
def test_stamped_results_filename_only_touches_the_extension(path, stamp, expected):
    assert stamped_results_filename(path, stamp) == expected


# ── online solver paths ────────────────────────────────────────────────

@pytest.mark.parametrize("given,expected", [
    ("/a/b/mesh.hdf5", "/a/b/mesh.msh"),
    ("/a/b/mesh.h5", "/a/b/mesh.msh"),
    ("/a/b/mesh.msh", "/a/b/mesh.msh"),
    ("/a/b/mesh.hdf5.hdf5", "/a/b/mesh.hdf5.msh"),
    ("/a/b/mesh", "/a/b/mesh.msh"),
])
def test_mesh_extension_derivation(given, expected):
    mgr = OnlineFEMManager()
    mgr.set_mesh_fn_msh(given)
    assert mgr.mesh_fn_msh == expected


def test_mesh_path_can_be_cleared():
    mgr = OnlineFEMManager()
    mgr.set_mesh_fn_msh("/a/b/mesh.hdf5")
    mgr.set_mesh_fn_msh("")
    assert mgr.mesh_fn_msh is None


# ── ConfigStore on a hostile filesystem ────────────────────────────────

def test_config_store_with_a_directory_path(tmp_path):
    from neuropilot.controller.config_store import ConfigStore
    store = ConfigStore(tmp_path)
    assert store.read() == {}
    with pytest.raises(OSError):
        store.write({"RELAY_HOST": "x"})


def test_config_store_with_a_readonly_parent(tmp_path):
    from neuropilot.controller.config_store import ConfigStore
    folder = tmp_path / "ro"
    folder.mkdir()
    os.chmod(folder, 0o500)
    try:
        store = ConfigStore(folder / ".env")
        with pytest.raises(OSError):
            store.write({"RELAY_HOST": "x"})
    finally:
        os.chmod(folder, 0o700)


def test_config_store_ignores_a_truncated_file(tmp_path):
    from neuropilot.controller.config_store import ConfigStore
    path = tmp_path / ".env"
    path.write_text("RELAY_HOST=\x00bad\n")
    values = ConfigStore(path).read()
    assert isinstance(values, dict)


# ── session cache shapes ───────────────────────────────────────────────

def test_apply_config_dict_survives_every_yaml_shape(window, qapp):
    """Whatever a truncated cache holds, the window must stay usable."""
    for bad in (None, [], [1, 2], "text", 42, {}, {"map_elms": None}):
        window.apply_config_dict(bad)
    assert window.tabWidget.count() == 7
