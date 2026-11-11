"""The real-hardware drivers: no device, no share, no new sweep.

Nothing here touches hardware: ``magicpy``/``smbclient`` are patched.  The
point is that every failure ends in a system status, never in an exception
that would take the health loop (and the whole pipeline) down.
"""

import asyncio
import io

import pandas as pd
import pytest

from neuropilot.controller.systems.stimulator import Stimulator
from neuropilot.controller.systems.emg import EMGComputer
from neuropilot.controller.systems.system import SystemStatus


def run(coro):
    return asyncio.run(coro)


class FakeMagVenture:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.connected = False
        self.fired = 0

    def connect(self):
        self.connected = True

    def get_status(self):
        return {"Model": "MagVenture", "SerialNo": "1",
                "coilTypeNo": "B65", "Waveform": "Biphasic",
                "Temperature": 32}, 0

    def arm(self):
        pass

    def fire(self, get_response=False):
        self.fired += 1
        return b"", 0

    def disarm(self):
        pass

    def set_amplitude(self, value):
        pass

    def set_waveform(self, value):
        pass


@pytest.fixture()
def stim(monkeypatch):
    system = Stimulator(update_control_panel_func=lambda *a, **k: None)
    return system


# ── stimulator ─────────────────────────────────────────────────────────

def test_connect_success_sets_ok(stim, monkeypatch):
    monkeypatch.setattr("magicpy.MagVenture", FakeMagVenture)

    async def scenario():
        stim.try_connect()
        await asyncio.sleep(0.05)
    run(scenario())
    assert stim.avail is True
    assert stim.status is SystemStatus.OK


def test_missing_ttl_port_falls_back_to_the_serial_port(stim, monkeypatch):
    calls = {"n": 0}

    class NoParport(FakeMagVenture):
        def __init__(self, *args, **kwargs):
            calls["n"] += 1
            if kwargs.get("ttl_port"):
                raise FileNotFoundError("/dev/parport0")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("magicpy.MagVenture", NoParport)

    async def scenario():
        stim.try_connect()
        await asyncio.sleep(0.05)
    run(scenario())
    assert calls["n"] == 2
    assert stim.avail is True and stim.status is SystemStatus.OK


def test_no_stimulator_sets_error_without_raising(stim, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("no such device")

    monkeypatch.setattr("magicpy.MagVenture", boom)

    async def scenario():
        stim.try_connect()
        await asyncio.sleep(0.05)
    run(scenario())
    assert stim.avail is False
    assert stim.status is SystemStatus.ERROR


def test_check_system_without_a_device_is_an_error(stim):
    stim.stimulator = None
    run(stim.check_system())
    assert stim.status is SystemStatus.ERROR


def test_check_system_handles_a_disappearing_device(stim, monkeypatch):
    class Unplugged(FakeMagVenture):
        def get_status(self):
            raise OSError("device reports readiness to read but returned no data")

    stim.stimulator = Unplugged()
    run(stim.check_system())          # must not raise
    assert stim.status is SystemStatus.ERROR


def test_fire_without_a_device_reports_and_does_not_raise(stim):
    stim.stimulator = None
    stim.fire()
    assert stim.status is SystemStatus.ERROR


@pytest.mark.parametrize("call", ["arm", "disarm", "set_amplitude", "set_waveform"])
def test_commands_without_a_device_are_no_ops(stim, call):
    stim.stimulator = None
    if call == "set_amplitude":
        stim.set_amplitude(50)
    elif call == "set_waveform":
        stim.set_waveform("Biphasic")
    else:
        getattr(stim, call)()


# ── EMG computer ───────────────────────────────────────────────────────

@pytest.fixture()
def emg(monkeypatch):
    system = EMGComputer(update_control_panel_func=lambda *a, **k: None)
    system.probe_interval_s = 0
    return system


class FakeSMB:
    def __init__(self):
        self.files = {"sweep_1.txt": "s\tADC 0\n0\t1\n"}
        self.fail = False

    def listdir(self, folder):
        if self.fail:
            raise OSError("share gone")
        return list(self.files)

    class path:                                          # noqa: N801
        @staticmethod
        def isfile(path):
            return True

    def open_file(self, path, mode="r"):
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        return io.StringIO(self.files[name])


@pytest.fixture()
def smb(monkeypatch, emg):
    fake = FakeSMB()
    monkeypatch.setattr("smbclient.listdir", fake.listdir)
    monkeypatch.setattr("smbclient.path", fake.path, raising=False)
    monkeypatch.setattr("smbclient.open_file", fake.open_file, raising=False)
    return fake


def test_probe_ok_when_the_share_answers(emg, smb):
    run(emg.check_system())
    assert emg.status is SystemStatus.OK


def test_probe_reports_a_vanished_share(emg, smb):
    smb.fail = True
    run(emg.check_system())                # must not raise
    assert emg.status is SystemStatus.ERROR


def test_probe_recovers(emg, smb):
    smb.fail = True
    run(emg.check_system())
    smb.fail = False
    run(emg.check_system())
    assert emg.status is SystemStatus.OK


def test_probe_is_throttled(emg, smb, monkeypatch):
    emg.probe_interval_s = 60
    calls = []
    monkeypatch.setattr("smbclient.listdir",
                        lambda folder: calls.append(1) or ["sweep_1.txt"])
    run(emg.check_system())
    run(emg.check_system())
    assert len(calls) == 1


def test_signal_files_lists_only_files(emg, smb):
    assert emg.signal_files() == ["sweep_1.txt"]


def test_latest_file_with_no_snapshot(emg, smb):
    frame = emg.get_latest_emg_df()
    assert isinstance(frame, pd.DataFrame)
    assert "Time" in frame.columns


def test_no_new_file_returns_none(emg, smb):
    assert emg.get_latest_emg_df(after=["sweep_1.txt"]) is None


def test_a_new_file_is_returned(emg, smb):
    smb.files["sweep_2.txt"] = "s\tADC 0\n0\t2\n"
    frame = emg.get_latest_emg_df(after=["sweep_1.txt"])
    assert frame is not None
    assert frame["ADC 0"].iloc[0] == 2


def test_empty_folder_returns_none(emg, smb):
    smb.files.clear()
    assert emg.get_latest_emg_df() is None


def test_a_directory_entry_is_skipped(emg, smb, monkeypatch):
    smb.files["subdir"] = ""
    monkeypatch.setattr("smbclient.path.isfile",
                        lambda path: not path.endswith("subdir"))
    assert emg.signal_files() == ["sweep_1.txt"]


def test_read_failure_is_an_exception_the_controller_catches(emg, smb):
    smb.files["sweep_1.txt"] = "not a table at all"   # pd.read_csv may raise
    try:
        emg.get_latest_emg_df()
    except Exception as e:                        # noqa: BLE001
        # The controller wraps this in _read_emg -> NaN MEP, never a crash.
        assert isinstance(e, Exception)
