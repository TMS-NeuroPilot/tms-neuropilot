"""Startup dependency checks and machine-local path persistence.

The controller needs two local tools in real/manual/training mode:

* the production relay checkout (``TMS_ROBOT_CONTROL_PATH``)
* InVesalius (environment, checkout, or ``inv`` launcher)

The persisted path belongs in ``~/.neuropilot/lab.yaml`` because it is
machine-specific.  A key that is already pinned in the repository ``.env`` is
updated there instead: ``.env`` has higher precedence, so writing the lab
profile would otherwise have no effect.

All GUI helpers are best-effort.  Headless startup falls back to terminal
input/output.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
from pathlib import Path
from typing import Iterable

from . import config
from .controller.config_store import ConfigStore
from .lab_profile import LabProfile

_GUI_DISPLAY_VARS = ("DISPLAY", "WAYLAND_DISPLAY")


def _print_error(message: str) -> None:
    print(f"[neuropilot] ERROR: {message}", file=sys.stderr, flush=True)


def gui_available() -> bool:
    """Return True when a Qt dialog can probably be shown."""
    try:
        from PyQt5 import QtWidgets
        if QtWidgets.QApplication.instance() is not None:
            return True
    except Exception:
        return False
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return True
    return any(os.environ.get(name) for name in _GUI_DISPLAY_VARS)


def _qt_app():
    """Return a QApplication, creating one when a display is available."""
    try:
        from PyQt5 import QtWidgets
    except Exception:
        return None
    app = QtWidgets.QApplication.instance()
    if app is not None:
        return app
    if not gui_available():
        return None
    try:
        return QtWidgets.QApplication([])
    except Exception:
        return None


def _make_message_dialog(title: str, message: str, kind: str):
    """Build the wide message dialog, or return None."""
    try:
        from PyQt5 import QtCore, QtWidgets

        dialog = QtWidgets.QDialog()
        dialog.setWindowTitle(title)
        dialog.setWindowModality(QtCore.Qt.ApplicationModal)
        dialog.setMinimumSize(760, 260)
        dialog.setSizeGripEnabled(True)
        layout = QtWidgets.QVBoxLayout(dialog)
        row = QtWidgets.QHBoxLayout()
        icon_label = QtWidgets.QLabel()
        standard = (QtWidgets.QStyle.SP_MessageBoxCritical
                    if kind == "critical"
                    else QtWidgets.QStyle.SP_MessageBoxWarning)
        icon_label.setPixmap(
            dialog.style().standardIcon(standard).pixmap(32, 32))
        icon_label.setAlignment(QtCore.Qt.AlignTop)
        row.addWidget(icon_label)
        text = QtWidgets.QLabel(message)
        text.setWordWrap(True)
        text.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        text.setMinimumWidth(680)
        row.addWidget(text, 1)
        layout.addLayout(row)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.resize(800, 300)
        return dialog
    except Exception:
        return None


def _message_box(title: str, message: str, kind: str, *, gui: bool) -> bool:
    """Show a wide modal message dialog; return True when it was displayed."""
    if not gui or _qt_app() is None:
        return False
    dialog = _make_message_dialog(title, message, kind)
    if dialog is None:
        return False
    dialog.exec_()
    return True


def show_error(title: str, message: str, *, gui: bool = True) -> None:
    """Show a modal error and always write the same message to the terminal."""
    _message_box(title, message, "critical", gui=gui)
    _print_error(message)


async def show_error_async(title: str, message: str, *,
                           gui: bool = True) -> None:
    """Show the error without blocking the qasync event loop."""
    _print_error(message)
    if not gui or _qt_app() is None:
        return
    dialog = _make_message_dialog(title, message, "critical")
    if dialog is None:
        return
    done = asyncio.Event()
    dialog.finished.connect(lambda _result: done.set())
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    await done.wait()
    dialog.deleteLater()


def _show_warning(title: str, message: str, *, gui: bool) -> None:
    if _message_box(title, message, "warning", gui=gui):
        return
    print(f"[neuropilot] {message}", file=sys.stderr, flush=True)


def relay_is_running(host: str | None = None, port: int | None = None,
                     timeout: float = 0.4) -> bool:
    """Return whether the relay port accepts a TCP connection."""
    host = config.RELAY_HOST if host is None else host
    port = int(config.RELAY_PORT if port is None else port)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def configured_relay_path() -> Path | None:
    """Return a valid tms-robot-control checkout, or None."""
    raw = (config.TMS_ROBOT_CONTROL_PATH or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if (path / "relay_server.py").is_file() else None


def choose_directory(title: str, initial: str | Path | None = None,
                     *, gui: bool = True) -> Path | None:
    """Open a resizable directory picker, or ask in the terminal."""
    app = _qt_app() if gui else None
    if app is not None:
        from PyQt5 import QtWidgets
        start = str(Path(initial).expanduser()) if initial else str(Path.home())
        dialog = QtWidgets.QFileDialog(None, title, start)
        dialog.setFileMode(QtWidgets.QFileDialog.Directory)
        dialog.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
        dialog.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        dialog.setMinimumSize(820, 520)
        dialog.resize(900, 600)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return None
        selected = dialog.selectedFiles()
        return Path(selected[0]) if selected else None
    if not sys.stdin.isatty():
        return None
    try:
        raw = input(f"{title} (blank to cancel): ").strip()
    except EOFError:
        return None
    return Path(raw).expanduser() if raw else None


def choose_file(title: str, name_filter: str,
                initial: str | Path | None = None, *,
                gui: bool = True) -> Path | None:
    """Open a resizable file picker, or ask in the terminal."""
    app = _qt_app() if gui else None
    if app is not None:
        from PyQt5 import QtWidgets
        start = str(Path(initial).expanduser()) if initial else str(Path.home())
        dialog = QtWidgets.QFileDialog(None, title, start, name_filter)
        dialog.setFileMode(QtWidgets.QFileDialog.ExistingFile)
        dialog.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        dialog.setMinimumSize(820, 520)
        dialog.resize(900, 600)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return None
        selected = dialog.selectedFiles()
        return Path(selected[0]) if selected else None
    if not sys.stdin.isatty():
        return None
    try:
        raw = input(f"{title} (blank to cancel): ").strip()
    except EOFError:
        return None
    return Path(raw).expanduser() if raw else None


def _ask_relay_path(gui: bool) -> Path | None:
    initial = (Path(config.TMS_ROBOT_CONTROL_PATH).expanduser()
               if config.TMS_ROBOT_CONTROL_PATH else Path.home())
    return choose_directory("Select tms-robot-control checkout", initial,
                            gui=gui)


def ask_relay_path(gui: bool = True) -> Path | None:
    """Prompt until a directory containing relay_server.py is selected."""
    while True:
        path = _ask_relay_path(gui)
        if path is None:
            return None
        if (path / "relay_server.py").is_file():
            return path
        _show_warning(
            "Invalid relay checkout",
            f"{path} does not contain relay_server.py.\n\n"
            "Select the tms-robot-control checkout directory.",
            gui=gui,
        )


def relay_unavailable_message() -> str:
    address = f"{config.RELAY_HOST}:{config.RELAY_PORT}"
    raw = (config.TMS_ROBOT_CONTROL_PATH or "").strip()
    if raw:
        return (
            f"The relay at {address} is not running and could not be started "
            f"from {raw}.\n\n"
            "Check that TMS_ROBOT_CONTROL_PATH points to a tms-robot-control "
            "checkout containing relay_server.py, or start relay_server.py "
            f"{config.RELAY_PORT} manually."
        )
    return (
        f"The relay at {address} is not running and TMS_ROBOT_CONTROL_PATH "
        "is not configured.\n\n"
        "Set the tms-robot-control checkout in Config > Lab, or start "
        f"relay_server.py {config.RELAY_PORT} manually."
    )


def save_settings(values: Iterable[tuple[str, object]]) -> bool:
    """Persist settings with the suite precedence and update this process.

    Any key already present in the repository ``.env`` is written there;
    everything else goes to ``~/.neuropilot/lab.yaml``.  Empty values are
    removed from the process environment when possible.
    """
    incoming = {str(key): str(value) for key, value in values
                if value is not None}
    if not incoming:
        return True
    try:
        env_store = ConfigStore()
        env_keys = set(env_store.read())
        env_values = {key: value for key, value in incoming.items()
                      if key in env_keys}
        lab_values = {key: value for key, value in incoming.items()
                      if key not in env_keys}
        if env_values:
            env_store.write(env_values)
        if lab_values:
            LabProfile().write(lab_values)
    except (OSError, ValueError) as exc:
        _print_error(f"could not save startup settings: {exc}")
        return False

    for key, value in incoming.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)
        if hasattr(config, key):
            setattr(config, key, value)
    return True


def prepare_relay(*, gui: bool = True) -> bool | None:
    """Ensure a relay will be available.

    Returns:
        False  -- an external relay is already running
        True   -- a configured relay checkout is available and the controller
                  should manage the relay
        None   -- no usable relay and the user did not provide a path
    """
    if relay_is_running():
        return False
    if configured_relay_path() is not None:
        return True

    path = ask_relay_path(gui)
    if path is None:
        return None
    if not save_settings((("TMS_ROBOT_CONTROL_PATH", path),)):
        return None
    return True
