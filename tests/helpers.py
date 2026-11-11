"""Helpers shared by the GUI tests."""

from __future__ import annotations


def build_window(qapp, gui_env, monkeypatch):
    """MainWindow in simulation mode, isolated from the user's files.

    The session cache, the Config tab's ``.env`` and the lab profile are all
    redirected into ``gui_env`` (a tmp dir): clicking Save in a test must never
    rewrite the repository's or the developer's configuration.
    """
    from neuropilot.controller import control_panel as cp
    from neuropilot.controller.config_store import ConfigStore
    from neuropilot.lab_profile import LabProfile

    cache = gui_env / "last_session.yaml"
    monkeypatch.setattr(cp, "_session_cache_path", lambda: str(cache))

    win = cp.MainWindow(simulation=True)
    win._config_store = ConfigStore(gui_env / ".env")
    win._lab_profile = LabProfile(gui_env / "lab.yaml")
    win.resize(1244, 960)
    qapp.processEvents()
    return win
