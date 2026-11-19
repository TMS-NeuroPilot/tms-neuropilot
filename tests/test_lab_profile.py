"""The lab profile (``~/.neuropilot/lab.yaml``) and its precedence rules.

shell environment  >  .env  >  lab.yaml  >  built-in defaults
"""

import os

import pytest
import yaml

from neuropilot import lab_profile
from neuropilot.lab_profile import LAB_KEYS, LabProfile


@pytest.fixture()
def profile(tmp_path, monkeypatch):
    monkeypatch.delenv("NEUROPILOT_LAB_FILE", raising=False)
    return LabProfile(tmp_path / "lab.yaml")


def test_default_path_can_be_overridden_by_env(monkeypatch, tmp_path):
    monkeypatch.setenv("NEUROPILOT_LAB_FILE", str(tmp_path / "custom.yaml"))
    assert lab_profile.default_path() == tmp_path / "custom.yaml"


def test_default_path_is_under_the_home_directory(monkeypatch):
    monkeypatch.delenv("NEUROPILOT_LAB_FILE", raising=False)
    assert lab_profile.default_path().parts[-2:] == (".neuropilot", "lab.yaml")


def test_missing_file_reads_empty(profile):
    assert profile.read() == {}


def test_roundtrip(profile):
    profile.write({"RELAY_HOST": "10.0.0.1", "RELAY_PORT": 6000})
    assert profile.read() == {"RELAY_HOST": "10.0.0.1", "RELAY_PORT": "6000"}


def test_write_merges_instead_of_replacing(profile):
    profile.write({"RELAY_HOST": "a"})
    profile.write({"RELAY_PORT": "7000"})
    assert profile.read() == {"RELAY_HOST": "a", "RELAY_PORT": "7000"}


def test_write_ignores_unknown_keys(profile):
    profile.write({"NOT_A_KEY": "x", "RELAY_HOST": "a"})
    assert profile.read() == {"RELAY_HOST": "a"}


def test_write_drops_none(profile):
    profile.write({"RELAY_HOST": None, "RELAY_PORT": "6000"})
    assert profile.read() == {"RELAY_PORT": "6000"}


def test_file_has_a_header_explaining_precedence(profile):
    profile.write({"RELAY_HOST": "a"})
    text = profile.path.read_text()
    assert text.startswith("# TMS NeuroPilot lab profile")
    assert "shell environment  >  .env" in text
    assert "RELAY_HOST: a" in text


def test_write_is_atomic(profile):
    profile.write({"RELAY_HOST": "a"})
    assert not list(profile.path.parent.glob("*.tmp"))


def test_write_creates_the_parent_directory(tmp_path):
    profile = LabProfile(tmp_path / "deep" / "nested" / "lab.yaml")
    profile.write({"RELAY_HOST": "a"})
    assert profile.path.is_file()


def test_write_to_a_directory_raises_oserror(tmp_path):
    folder = tmp_path / "dir"
    folder.mkdir()
    with pytest.raises(OSError):
        LabProfile(folder).write({"RELAY_HOST": "a"})


@pytest.mark.parametrize("content", ["key: [unclosed\n", "- 1\n- 2\n",
                                     "just text\n", "\x00\x01"])
def test_unreadable_or_non_mapping_files_are_ignored(profile, content):
    profile.path.parent.mkdir(parents=True, exist_ok=True)
    profile.path.write_bytes(content.encode("utf-8", "ignore"))
    assert profile.read() == {}


def test_read_keeps_only_known_keys(profile):
    profile.path.parent.mkdir(parents=True, exist_ok=True)
    profile.path.write_text(yaml.safe_dump({"RELAY_HOST": "a", "EXTRA": 1}))
    assert profile.read() == {"RELAY_HOST": "a"}


def test_read_stringifies_values(profile):
    profile.path.parent.mkdir(parents=True, exist_ok=True)
    profile.path.write_text(yaml.safe_dump({"RELAY_PORT": 6000,
                                            "NEUROPILOT_UI_SCALE": 1.5}))
    assert profile.read() == {"RELAY_PORT": "6000",
                              "NEUROPILOT_UI_SCALE": "1.5"}


# ── the environment layer ──────────────────────────────────────────────

def test_apply_environment_exports_unset_keys():
    environ = {}
    applied = lab_profile.apply_environment({"RELAY_HOST": "lab"}, environ)
    assert applied == ["RELAY_HOST"]
    assert environ["RELAY_HOST"] == "lab"


def test_env_already_set_wins():
    environ = {"RELAY_HOST": "from-env-file"}
    applied = lab_profile.apply_environment({"RELAY_HOST": "lab"}, environ)
    assert applied == []
    assert environ["RELAY_HOST"] == "from-env-file"


def test_empty_values_are_not_exported():
    environ = {}
    lab_profile.apply_environment({"TMS_ROBOT_CONTROL_PATH": "",
                                   "NEUROPILOT_UI_SCALE": "   "}, environ)
    assert environ == {}


def test_unknown_keys_are_not_exported():
    environ = {}
    lab_profile.apply_environment({"EVIL": "x"}, environ)
    assert environ == {}


def test_apply_environment_reads_the_file_when_given_nothing(tmp_path):
    profile = LabProfile(tmp_path / "lab.yaml")
    profile.write({"RELAY_HOST": "lab-host"})
    environ = {}
    applied = lab_profile.apply_environment(profile.read(), environ)
    assert "RELAY_HOST" in applied and environ["RELAY_HOST"] == "lab-host"


def test_every_lab_key_has_a_default():
    assert set(LAB_KEYS) == set(lab_profile.DEFAULTS)


def test_ui_scale_and_tms_path_default_to_empty():
    assert lab_profile.DEFAULTS["NEUROPILOT_UI_SCALE"] == ""
    assert lab_profile.DEFAULTS["TMS_ROBOT_CONTROL_PATH"] == ""


def test_env_keys_lists_what_env_pins(profile, tmp_path):
    from neuropilot.controller.config_store import ConfigStore
    profile.write({"RELAY_HOST": "lab", "RELAY_PORT": "6000"})
    env = tmp_path / ".env"
    env.write_text("RELAY_PORT=5000\n")
    store = ConfigStore(env)
    assert profile.env_keys(store) == ["RELAY_PORT"]


def test_env_keys_without_a_store(profile):
    profile.write({"RELAY_HOST": "lab"})
    assert profile.env_keys(None) == []


def test_config_module_applies_the_profile_below_env(tmp_path):
    """`neuropilot.config` exports lab values only when the shell/.env is silent."""
    script = f"""
import os, sys
os.environ.pop("RELAY_HOST", None)
os.environ["NEUROPILOT_LAB_FILE"] = {str(tmp_path / 'lab.yaml')!r}
sys.path.insert(0, {str(lab_profile.__file__).rsplit('/src/', 1)[0] + '/src'!r})
from neuropilot import lab_profile, config
print(config.RELAY_HOST)
print(",".join(config.LAB_PROFILE_KEYS))
"""
    import subprocess
    import sys
    lab_profile.write({"RELAY_HOST": "lab-host"}, tmp_path / "lab.yaml")
    out = subprocess.run([sys.executable, "-c", script], capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    host, applied = out.stdout.strip().splitlines()
    assert host == "lab-host"
    assert "RELAY_HOST" in applied


def test_config_module_lets_env_win(tmp_path):
    script = f"""
import os, sys
os.environ["RELAY_HOST"] = "shell-host"
os.environ["NEUROPILOT_LAB_FILE"] = {str(tmp_path / 'lab.yaml')!r}
sys.path.insert(0, {str(lab_profile.__file__).rsplit('/src/', 1)[0] + '/src'!r})
from neuropilot import config
print(config.RELAY_HOST)
"""
    import subprocess
    import sys
    lab_profile.write({"RELAY_HOST": "lab-host"}, tmp_path / "lab.yaml")
    out = subprocess.run([sys.executable, "-c", script], capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "shell-host"
