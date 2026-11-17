"""InVesalius discovery, launch validation and optional-child lifecycle."""

import asyncio
import socket
import time
from pathlib import Path

import pytest

from neuropilot import invesalius_launcher as il
from neuropilot import supervisor


def _executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_env(tmp_path: Path, *, valid: bool = True) -> tuple[Path, Path]:
    env = tmp_path / "envs" / "invesalius"
    checkout = tmp_path / "invesalius-prs"
    checkout.mkdir()
    (checkout / "app.py").write_text("print('app')\n", encoding="utf-8")
    python = _executable(
        env / "bin" / "python",
        'echo "usage: app.py --remote-host HOST"; exit 0'
        if valid else 'echo "not invesalius"; exit 1',
    )
    launcher = _executable(
        env / "bin" / "inv",
        f'exec "{python}" "{checkout / "app.py"}" "$@"',
    )
    assert launcher.is_file()
    return env, checkout


def test_spec_for_env_reads_the_installer_wrapper(tmp_path):
    env, checkout = _fake_env(tmp_path)
    spec = il.spec_for_env(env)
    assert spec is not None
    assert spec.env == env
    assert spec.checkout == checkout
    assert spec.launcher == env / "bin" / "inv"
    assert spec.argv("127.0.0.1", 5000) == [
        str(env / "bin" / "python"),
        str(checkout / "app.py"),
        "--remote-host",
        "http://127.0.0.1:5000",
    ]


def test_spec_for_env_reads_the_editable_pth_without_inv(tmp_path):
    env = tmp_path / "envs" / "invesalius"
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "app.py").write_text("print('app')\n", encoding="utf-8")
    _executable(env / "bin" / "python",
                'echo "usage: app.py --remote-host HOST"; exit 0')
    site = env / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    (site / "invesalius.pth").write_text(str(checkout) + "\n", encoding="utf-8")

    spec = il.spec_for_env(env)
    assert spec is not None
    assert spec.checkout == checkout
    assert spec.launcher is None


def test_validate_rejects_a_generic_inv(tmp_path):
    launcher = _executable(tmp_path / "inv", 'echo "usage: invoke"; exit 0')
    ok, detail = il.validate(il.LaunchSpec(launcher=launcher))
    assert not ok
    assert "not InVesalius" in detail


def test_resolve_uses_an_explicit_environment(tmp_path, monkeypatch):
    env, checkout = _fake_env(tmp_path)
    monkeypatch.setenv("NEUROPILOT_LAB_FILE", str(tmp_path / "lab.yaml"))
    monkeypatch.setenv("INVESALIUS_LAUNCH", "auto")
    spec = il.resolve("127.0.0.1", 5000, interactive=False,
                      override=env, save=False)
    assert spec is not None
    assert spec.checkout == checkout


def test_resolve_off_never_runs_discovery(monkeypatch):
    monkeypatch.setenv("INVESALIUS_LAUNCH", "off")
    monkeypatch.setattr(il, "discover",
                        lambda: pytest.fail("discovery should not run"))
    assert il.resolve("127.0.0.1", 5000, interactive=False, save=False) is None


def test_resolve_does_not_start_a_local_app_for_a_remote_relay(
        tmp_path, monkeypatch):
    env, _checkout = _fake_env(tmp_path)
    monkeypatch.setenv("NEUROPILOT_LAB_FILE", str(tmp_path / "lab.yaml"))
    monkeypatch.setenv("INVESALIUS_LAUNCH", "auto")
    assert il.resolve("192.168.1.5", 5000, interactive=False,
                      override=env, save=False) is None


def test_resolve_missing_install_is_a_warning_not_an_exception(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NEUROPILOT_LAB_FILE", str(tmp_path / "lab.yaml"))
    monkeypatch.setenv("INVESALIUS_LAUNCH", "auto")
    monkeypatch.delenv("INVESALIUS_ENV", raising=False)
    monkeypatch.delenv("INVESALIUS_CHECKOUT", raising=False)
    monkeypatch.delenv("INVESALIUS_LAUNCHER", raising=False)
    monkeypatch.setattr(il, "_env_prefixes", lambda: [])
    assert il.resolve("127.0.0.1", 5000, interactive=False,
                      save=False) is None
    assert "continuing without auto-start" in capsys.readouterr().out


def test_resolve_asks_when_multiple_environments_are_valid(
        tmp_path, monkeypatch):
    good_a, checkout_a = _fake_env(tmp_path)
    good_b = tmp_path / "envs" / "invesalius-test"
    checkout_b = tmp_path / "checkout-b"
    checkout_b.mkdir()
    (checkout_b / "app.py").write_text("print('app')\n", encoding="utf-8")
    _executable(good_b / "bin" / "python",
                'echo "usage: app.py --remote-host HOST"; exit 0')
    _executable(good_b / "bin" / "inv",
                f'exec "{good_b / "bin" / "python"}" "{checkout_b / "app.py"}" "$@"')
    monkeypatch.setenv("NEUROPILOT_LAB_FILE", str(tmp_path / "lab.yaml"))
    monkeypatch.setenv("INVESALIUS_LAUNCH", "auto")
    monkeypatch.delenv("INVESALIUS_ENV", raising=False)
    monkeypatch.delenv("INVESALIUS_CHECKOUT", raising=False)
    monkeypatch.delenv("INVESALIUS_LAUNCHER", raising=False)

    first = il.spec_for_env(good_a)
    second = il.spec_for_env(good_b)
    assert first is not None and second is not None
    monkeypatch.setattr(il, "discover", lambda: ([first, second], []))
    monkeypatch.setattr(il, "_choice", lambda labels, gui: 1)
    selected = il.resolve("127.0.0.1", 5000, interactive=True, save=False)
    assert selected is not None
    assert selected.checkout == checkout_b


def test_saving_the_selection_writes_lab_keys(tmp_path, monkeypatch):
    env, checkout = _fake_env(tmp_path)
    lab = tmp_path / "lab.yaml"
    monkeypatch.setenv("NEUROPILOT_LAB_FILE", str(lab))
    monkeypatch.setenv("INVESALIUS_LAUNCH", "auto")
    spec = il.resolve("127.0.0.1", 5000, interactive=False,
                      override=env, save=True)
    assert spec is not None
    text = lab.read_text(encoding="utf-8")
    assert f"INVESALIUS_ENV: {env}" in text
    assert f"INVESALIUS_CHECKOUT: {checkout}" in text
    assert "INVESALIUS_LAUNCH: auto" in text


def test_real_stack_adds_invesalius_before_the_controller_starts(
        tmp_path, monkeypatch):
    env, checkout = _fake_env(tmp_path)
    spec = il.spec_for_env(env)
    assert spec is not None
    components = supervisor.real_stack(invesalius=spec)
    assert [c.name for c in components] == ["controller", "invesalius"]
    launch = components[1]
    assert launch.wait_for_port is True
    assert launch.shutdown_on_exit is False
    assert launch.cwd == str(checkout)


def test_invesalius_waits_for_the_relay_port(tmp_path, monkeypatch):
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    monkeypatch.setattr(supervisor.config, "RELAY_HOST", "127.0.0.1")
    monkeypatch.setattr(supervisor.config, "RELAY_PORT", port)
    monkeypatch.setattr(supervisor.config, "READINESS_TIMEOUT_S", 2.0)

    marker = tmp_path / "invesalius-started"
    invesalius = _executable(
        tmp_path / "invesalius", f'touch "{marker}"; exit 0')
    controller = _executable(tmp_path / "controller", "sleep 0.3; exit 0")
    components = [
        supervisor.Component("controller", None, [], wait_ready=None,
                              executable=str(controller)),
        supervisor.Component("invesalius", None, [], wait_ready=None,
                              executable=str(invesalius), wait_for_port=True,
                              shutdown_on_exit=False),
    ]
    try:
        asyncio.run(supervisor.run_stack(components))
    finally:
        server.close()
    assert marker.is_file()


def test_optional_child_exit_keeps_the_critical_child_alive(tmp_path):
    optional = _executable(tmp_path / "optional", "exit 0")
    critical = _executable(tmp_path / "critical", "sleep 0.5; exit 0")
    components = [
        supervisor.Component("invesalius", None, [], wait_ready=None,
                              executable=str(optional),
                              shutdown_on_exit=False),
        supervisor.Component("controller", None, [], wait_ready=None,
                              executable=str(critical)),
    ]
    started = time.monotonic()
    asyncio.run(supervisor.run_stack(components))
    assert time.monotonic() - started >= 0.4


def test_optional_child_start_failure_does_not_abort_the_stack(
        tmp_path, capsys):
    critical = _executable(tmp_path / "critical", "sleep 0.2; exit 0")
    components = [
        supervisor.Component("invesalius", None, [], wait_ready=None,
                              executable=str(tmp_path / "missing"),
                              shutdown_on_exit=False),
        supervisor.Component("controller", None, [], wait_ready=None,
                              executable=str(critical)),
    ]
    asyncio.run(supervisor.run_stack(components))
    out = capsys.readouterr().out
    assert "could not start invesalius" in out
    assert "all components stopped" in out


def test_cli_real_no_invesalius_skips_discovery(monkeypatch):
    from neuropilot import cli

    seen = {}
    monkeypatch.setattr(cli, "_prepare_relay", lambda **kwargs: False)
    monkeypatch.setattr(
        cli, "_resolve_invesalius",
        lambda **kwargs: seen.update(kwargs) or None)
    monkeypatch.setattr(cli, "_run", lambda components: seen.update(
        components=[c.name for c in components]))
    assert cli.main(["real", "--no-invesalius"]) == 0
    assert seen["no_invesalius"] is True
    assert seen["components"] == ["controller"]


def test_cli_real_passes_an_invesalius_override(monkeypatch, tmp_path):
    from neuropilot import cli

    seen = {}
    monkeypatch.setattr(cli, "_prepare_relay", lambda **kwargs: False)
    monkeypatch.setattr(
        cli, "_resolve_invesalius",
        lambda **kwargs: seen.update(kwargs) or None)
    monkeypatch.setattr(cli, "_run", lambda components: seen.update(
        components=[c.name for c in components]))
    path = str(tmp_path / "invesalius")
    assert cli.main(["real", "--invesalius", path]) == 0
    assert seen["override"] == path


def test_cli_real_manages_a_configured_relay(monkeypatch):
    from neuropilot import cli

    seen = {}
    monkeypatch.setattr(cli, "_prepare_relay", lambda **kwargs: True)
    monkeypatch.setattr(cli, "_resolve_invesalius", lambda **kwargs: None)
    monkeypatch.setattr(cli, "_run", lambda components: seen.update(
        components=components))
    assert cli.main(["real", "--no-invesalius"]) == 0
    assert seen["components"][0].args == ["--real", "--manage-relay"]


def test_cli_real_aborts_when_relay_setup_fails(monkeypatch):
    from neuropilot import cli

    monkeypatch.setattr(cli, "_prepare_relay", lambda **kwargs: None)
    monkeypatch.setattr(cli, "_run",
                        lambda components: pytest.fail("must not start"))
    assert cli.main(["real", "--no-invesalius"]) == 1


def test_cli_sim_never_resolves_invesalius(monkeypatch):
    from neuropilot import cli

    monkeypatch.setattr(cli, "_resolve_invesalius",
                        lambda **kwargs: pytest.fail("sim resolved InVesalius"))
    monkeypatch.setattr(cli, "_run", lambda components: None)
    assert cli.main(["sim"]) == 0


def test_supervisor_colors_only_the_bracket_label(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert supervisor._label("controller") == "[\033[32mcontroller\033[0m]"
    assert supervisor._label("invesalius") == "[\033[35minvesalius\033[0m]"


def test_supervisor_honours_no_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert supervisor._label("controller") == "[controller]"


def test_invesalius_start_line_shows_the_checkout(tmp_path, capsys):
    invesalius = _executable(tmp_path / "invesalius", "exit 0")
    controller = _executable(tmp_path / "controller", "sleep 0.2; exit 0")
    components = [
        supervisor.Component("controller", None, [], wait_ready=None,
                              executable=str(controller)),
        supervisor.Component("invesalius", None, [], wait_ready=None,
                              executable=str(invesalius),
                              cwd=str(tmp_path), shutdown_on_exit=False),
    ]
    asyncio.run(supervisor.run_stack(components))
    out = capsys.readouterr().out
    assert f"[invesalius] start InVesalius from {tmp_path}" in out


def test_supervisor_drops_gtk_layout_noise():
    noise = [
        "(app.py:123): Gtk-WARNING **: 09:05:10.815: for_size smaller than min-size (21 < 32) while measuring gadget (node entry, owner GtkSpinButton)",
        "(app.py:123): Gtk-WARNING **: 09:05:10.815: Negative content width -14 (allocation 20, extents 17x17) while allocating gadget (node button, owner GtkButton)",
        "(app.py:123): Gtk-CRITICAL **: 09:05:10.760: gtk_widget_set_size_request: assertion 'height >= -1' failed",
    ]
    for text in noise:
        assert supervisor._drop_output_line("invesalius", text)
    assert supervisor._drop_output_line("invesalius", "")
    assert not supervisor._drop_output_line("controller", "")
    assert not supervisor._drop_output_line(
        "invesalius", "real InVesalius error: could not load project")
    assert not supervisor._drop_output_line(
        "relay", "Gtk-WARNING **: unrelated non-layout warning")
