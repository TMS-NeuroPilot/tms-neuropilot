"""Startup relay checks and path persistence."""

from pathlib import Path

import pytest

from neuropilot import startup


def _paths(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    lab_file = tmp_path / "lab.yaml"
    monkeypatch.setenv("NEUROPILOT_ENV_FILE", str(env_file))
    monkeypatch.setenv("NEUROPILOT_LAB_FILE", str(lab_file))
    return env_file, lab_file


def test_save_settings_updates_pinned_env(tmp_path, monkeypatch):
    env_file, lab_file = _paths(tmp_path, monkeypatch)
    env_file.write_text("TMS_ROBOT_CONTROL_PATH=/old\n", encoding="utf-8")
    assert startup.save_settings(
        (("TMS_ROBOT_CONTROL_PATH", "/new"),))
    assert "TMS_ROBOT_CONTROL_PATH=/new" in env_file.read_text()
    assert not lab_file.exists()
    assert startup.config.TMS_ROBOT_CONTROL_PATH == "/new"


def test_save_settings_uses_lab_when_not_pinned(tmp_path, monkeypatch):
    env_file, lab_file = _paths(tmp_path, monkeypatch)
    env_file.write_text("RELAY_HOST=127.0.0.1\n", encoding="utf-8")
    assert startup.save_settings(
        (("TMS_ROBOT_CONTROL_PATH", "/new"),))
    assert "TMS_ROBOT_CONTROL_PATH: /new" in lab_file.read_text()
    assert "TMS_ROBOT_CONTROL_PATH" not in env_file.read_text()


def test_prepare_relay_reuses_an_existing_relay(monkeypatch):
    monkeypatch.setattr(startup, "relay_is_running", lambda: True)
    monkeypatch.setattr(startup, "ask_relay_path",
                        lambda gui: pytest.fail("must not prompt"))
    assert startup.prepare_relay(gui=False) is False


def test_prepare_relay_uses_a_configured_path(monkeypatch):
    monkeypatch.setattr(startup, "relay_is_running", lambda: False)
    monkeypatch.setattr(startup, "configured_relay_path",
                        lambda: Path("/tmp/relay"))
    monkeypatch.setattr(startup, "ask_relay_path",
                        lambda gui: pytest.fail("must not prompt"))
    assert startup.prepare_relay(gui=False) is True


def test_prepare_relay_prompts_and_saves(monkeypatch, tmp_path):
    path = tmp_path / "relay"
    monkeypatch.setattr(startup, "relay_is_running", lambda: False)
    monkeypatch.setattr(startup, "configured_relay_path", lambda: None)
    monkeypatch.setattr(startup, "ask_relay_path", lambda gui: path)
    saved = []
    monkeypatch.setattr(startup, "save_settings",
                        lambda values: saved.append(list(values)) or True)
    assert startup.prepare_relay(gui=False) is True
    assert saved == [[("TMS_ROBOT_CONTROL_PATH", path)]]


def test_prepare_relay_cancel_returns_none(monkeypatch):
    monkeypatch.setattr(startup, "relay_is_running", lambda: False)
    monkeypatch.setattr(startup, "configured_relay_path", lambda: None)
    monkeypatch.setattr(startup, "ask_relay_path", lambda gui: None)
    assert startup.prepare_relay(gui=False) is None


def test_external_invesalius_is_saved(tmp_path, monkeypatch):
    from neuropilot import invesalius_launcher as il

    env_file, lab_file = _paths(tmp_path, monkeypatch)
    spec = il._external_spec()
    assert spec.external is True
    assert "INVESALIUS_LAUNCH: external" in lab_file.read_text()
    assert not env_file.exists() or "INVESALIUS_LAUNCH" not in env_file.read_text()


def test_external_invesalius_updates_a_pinned_env(tmp_path, monkeypatch):
    from neuropilot import invesalius_launcher as il

    env_file, lab_file = _paths(tmp_path, monkeypatch)
    env_file.write_text("INVESALIUS_LAUNCH=auto\n", encoding="utf-8")
    spec = il._external_spec()
    assert spec.external is True
    assert "INVESALIUS_LAUNCH=external" in env_file.read_text()
    assert not lab_file.exists()


def test_relay_failure_reason_mentions_missing_configuration(
        monkeypatch, tmp_path):
    from neuropilot import config
    from neuropilot.controller.systems.relay import RelaySystem
    from neuropilot.controller.systems.system import SystemStatus

    monkeypatch.setattr(config, "RELAY_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "RELAY_PORT", 1)
    monkeypatch.setattr(config, "TMS_ROBOT_CONTROL_PATH", "")
    relay = RelaySystem(manage=False)
    relay.try_connect()
    assert relay.status is SystemStatus.ERROR
    assert "not configured" in relay.failure_reason


def test_relay_failure_reason_mentions_a_missing_script(
        monkeypatch, tmp_path):
    from neuropilot import config
    from neuropilot.controller.systems.relay import RelaySystem

    monkeypatch.setattr(config, "RELAY_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "RELAY_PORT", 1)
    monkeypatch.setattr(config, "TMS_ROBOT_CONTROL_PATH", str(tmp_path))
    relay = RelaySystem(manage=True)
    relay.try_connect()
    assert "relay_server.py" in relay.failure_reason
