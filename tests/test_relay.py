"""Relay lifecycle used by the Connections page."""

import socket

import pytest

from neuropilot import config
from neuropilot.controller.systems.relay import RelaySystem
from neuropilot.controller.systems.system import SystemStatus


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def fake_relay(tmp_path, monkeypatch):
    script = tmp_path / "relay_server.py"
    script.write_text(
        "import socket, sys, time\n"
        "sock = socket.socket()\n"
        "sock.bind(('127.0.0.1', int(sys.argv[1])))\n"
        "sock.listen()\n"
        "time.sleep(30)\n"
    )
    port = _free_port()
    monkeypatch.setattr(config, "TMS_ROBOT_CONTROL_PATH", str(tmp_path))
    monkeypatch.setattr(config, "RELAY_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "RELAY_PORT", str(port))
    monkeypatch.setattr(config, "READINESS_TIMEOUT_S", 5.0)
    # Keep relay.pid/relay.log inside the test, never in the shared ROOT_FOLDER:
    # a concurrent supervisor cleanup would otherwise stop this relay.
    monkeypatch.setattr(config, "ROOT_FOLDER", str(tmp_path))
    return port


def test_simulation_relay_is_status_only(fake_relay):
    relay = RelaySystem(simulation=True)
    relay.try_connect()
    assert relay.status == SystemStatus.ERROR
    assert "supervisor" in relay._last_message
    relay.recover("Start relay")          # must not spawn a process
    assert relay.process is None


def test_relay_starts_and_stops(fake_relay):
    relay = RelaySystem(manage=True)
    try:
        relay.try_connect()
        assert relay.status == SystemStatus.OK
        assert relay.owned is True
        assert relay.process is not None
        assert "relay.log" in relay.details["Log"]
    finally:
        relay.stop()
    assert relay.process is None


def test_relay_pid_file_lives_in_the_test_root(fake_relay, tmp_path):
    """The pid file must not sit in a ROOT_FOLDER shared with other workers."""
    relay = RelaySystem(manage=True)
    try:
        relay.try_connect()
        assert relay.status == SystemStatus.OK
        assert relay.pid_path == tmp_path / "relay.pid"
    finally:
        relay.stop()


def test_unmanaged_relay_reports_not_running(fake_relay):
    relay = RelaySystem(manage=False)
    relay.try_connect()
    assert relay.status == SystemStatus.ERROR
    assert relay._last_message == "Relay not running"
    assert relay.ERROR_RECOVERIES["Relay not running"] == "Start relay"
