"""Supervisor cleanup for a relay left behind by a crashed controller."""

import subprocess
import sys
from pathlib import Path

from neuropilot import supervisor


def _relay_script(tmp_path: Path) -> Path:
    script = tmp_path / "relay_server.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    return script


def test_supervisor_stops_an_owned_relay(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor.config, "ROOT_FOLDER", str(tmp_path))
    pid_path = tmp_path / "relay.pid"
    process = subprocess.Popen([sys.executable, str(_relay_script(tmp_path))])
    pid_path.write_text(str(process.pid), encoding="utf-8")
    try:
        assert supervisor._stop_owned_relay() == process.pid
        assert process.wait(timeout=5) is not None
        assert not pid_path.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)


def test_supervisor_does_not_kill_an_unrelated_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor.config, "ROOT_FOLDER", str(tmp_path))
    pid_path = tmp_path / "relay.pid"
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    pid_path.write_text(str(process.pid), encoding="utf-8")
    try:
        assert supervisor._stop_owned_relay() is None
        assert process.poll() is None
        assert not pid_path.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)


def test_external_relay_does_not_remove_another_owners_pid(tmp_path, monkeypatch):
    from neuropilot.controller.systems.relay import RelaySystem

    monkeypatch.setattr(supervisor.config, "ROOT_FOLDER", str(tmp_path))
    pid_path = tmp_path / "relay.pid"
    pid_path.write_text("12345", encoding="utf-8")
    relay = RelaySystem(manage=False)
    relay.stop()
    assert pid_path.exists()
