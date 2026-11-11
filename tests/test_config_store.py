"""The .env editor behind the Config › Lab page."""

import pytest

from neuropilot.controller.config_store import MANAGED_KEYS, ConfigStore, _clean

ORIGINAL = """\
# suite configuration
RELAY_HOST=localhost
RELAY_PORT=5000            # relay listens here

ROOT_FOLDER=/tmp/neuropilot_test
UNMANAGED_KEY=keep me
"""


@pytest.fixture()
def store(tmp_path):
    path = tmp_path / ".env"
    path.write_text(ORIGINAL)
    return ConfigStore(path)


def test_read_returns_only_managed_keys(store):
    values = store.read()
    assert values["RELAY_HOST"] == "localhost"
    assert values["RELAY_PORT"] == "5000"      # inline comment stripped
    assert values["ROOT_FOLDER"] == "/tmp/neuropilot_test"
    assert "UNMANAGED_KEY" not in values


def test_read_missing_file_returns_empty(tmp_path):
    assert ConfigStore(tmp_path / "nope.env").read() == {}


def test_write_updates_in_place(store):
    store.write({"RELAY_PORT": "6000"})
    text = store.path.read_text()
    assert "RELAY_PORT=6000" in text
    assert text.count("RELAY_PORT=") == 1


def test_write_keeps_comments_and_unknown_keys(store):
    store.write({"RELAY_PORT": "6000"})
    text = store.path.read_text()
    assert "# suite configuration" in text
    assert "UNMANAGED_KEY=keep me" in text
    assert "ROOT_FOLDER=/tmp/neuropilot_test" in text


def test_write_appends_new_keys_in_managed_order(tmp_path):
    store = ConfigStore(tmp_path / ".env")
    store.write({"EMG_CHANNELS": "FDI,APB", "RELAY_HOST": "host"})
    lines = [l for l in store.path.read_text().splitlines() if l and not l.startswith("#")]
    keys = [l.split("=", 1)[0] for l in lines]
    assert keys == ["RELAY_HOST", "EMG_CHANNELS"]   # order of MANAGED_KEYS
    assert store.read() == {"RELAY_HOST": "host", "EMG_CHANNELS": "FDI,APB"}


def test_write_ignores_unmanaged_and_none_values(store):
    store.write({"NOT_A_KEY": "x", "RELAY_HOST": None})
    text = store.path.read_text()
    assert "NOT_A_KEY" not in text
    assert "RELAY_HOST=localhost" in text


def test_write_is_atomic_and_leaves_no_temp_file(store):
    store.write({"RELAY_PORT": "6001"})
    assert not list(store.path.parent.glob("*.tmp"))


def test_round_trip_of_every_managed_key(tmp_path):
    store = ConfigStore(tmp_path / ".env")
    payload = {key: f"value-{i}" for i, key in enumerate(MANAGED_KEYS)}
    store.write(payload)
    assert store.read() == payload


@pytest.mark.parametrize("raw,expected", [
    ("plain", "plain"),
    ("  spaced  ", "spaced"),
    ('"quoted"', "quoted"),
    ("'single'", "single"),
    ("value # comment", "value"),
    ("", ""),
    ("#value-not-a-comment", "#value-not-a-comment"),
    ("value # trailing comment", "value"),
])
def test_clean_matches_dotenv_semantics(raw, expected):
    assert _clean(raw) == expected


def test_repeated_writes_do_not_grow_the_file(store):
    for port in range(5000, 5010):
        store.write({"RELAY_PORT": str(port)})
    text = store.path.read_text()
    assert text.count("RELAY_PORT=") == 1
    assert "RELAY_PORT=5009" in text
