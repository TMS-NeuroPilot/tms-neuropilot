"""Find and launch InVesalius for the real, manual and training modes.

InVesalius normally lives in its own conda environment.  The conda executable
is located through ``CONDA_EXE`` (or the active environment) and asked for the
environment list.  A candidate is valid when one of these works:

* ``<env>/bin/inv --help`` (the upstream entry point may be broken; this is
  only accepted when it really prints InVesalius' ``--remote-host`` flag)
* ``<env>/bin/python <checkout>/app.py --help``, where the checkout is found
  from the installer wrapper, an editable-install ``.pth`` file, or
  ``pip show InVesalius``.

The selected environment, checkout and launcher are stored in
``~/.neuropilot/lab.yaml`` unless the key is pinned in the repository
``.env``.  The picker also has an **Is started** option for an InVesalius
instance on another machine; it stores ``INVESALIUS_LAUNCH=external``.
Discovery failures are warnings, never startup errors: the controller can
still run while the user starts InVesalius manually.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

# How long one ``--help`` validation may take.  Importing InVesalius pulls in
# pandas/torch, so a few seconds is normal.
_HELP_TIMEOUT = 20.0
_CONDA_TIMEOUT = 15.0

_OFF_VALUES = {"off", "never", "external", "manual"}
_LOCAL_VALUES = {"auto", "local", "always"}


@dataclass(frozen=True)
class LaunchSpec:
    """The parts needed to start one local InVesalius installation."""

    env: Path | None = None
    checkout: Path | None = None
    launcher: Path | None = None
    python: Path | None = None
    source: str = ""
    external: bool = False

    @property
    def label(self) -> str:
        if self.env is not None:
            return str(self.env)
        if self.checkout is not None:
            return str(self.checkout)
        return str(self.launcher or "InVesalius")

    def argv(self, remote_host: str, remote_port: int) -> list[str]:
        """Return the smallest reliable launch command for this install."""
        if self.external:
            raise ValueError("external InVesalius has no local launch command")
        host = remote_host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        url = f"http://{host}:{remote_port}"
        if (self.python is not None and self.checkout is not None
                and (self.checkout / "app.py").is_file()):
            return [str(self.python), str(self.checkout / "app.py"),
                    "--remote-host", url]
        if self.launcher is not None and self.launcher.is_file():
            return [str(self.launcher), "--remote-host", url]
        raise ValueError(
            f"InVesalius launch target is incomplete: {self.label}")


def _env_prefixes() -> list[tuple[str, Path]]:
    """Return (display name, prefix) for conda environments.

    ``conda env list --json`` is the source of truth.  If conda cannot be
    called, fall back to the current environment and the ``envs`` directory
    next to it.  This keeps discovery useful in stripped-down test shells.
    """
    conda = os.environ.get("CONDA_EXE") or shutil.which("conda")
    if conda:
        try:
            result = subprocess.run(
                [conda, "env", "list", "--json"],
                capture_output=True, text=True, timeout=_CONDA_TIMEOUT,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if not isinstance(data, dict):
                    raise ValueError("conda env list returned a non-object")
                details = data.get("envs_details") or {}
                found = []
                for raw in data.get("envs") or []:
                    prefix = Path(raw).expanduser()
                    meta = details.get(raw, {}) if isinstance(details, dict) else {}
                    name = str(meta.get("name") or prefix.name or "base")
                    found.append((name, prefix))
                if found:
                    return found
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
            pass

    current = Path(sys.prefix).expanduser()
    prefixes = []
    if current.name in ("envs", ""):
        base = current.parent
    elif current.parent.name == "envs":
        base = current.parent.parent
    else:
        base = current
    if current.is_dir():
        prefixes.append(("current", current))
    envs_dir = base / "envs"
    if envs_dir.is_dir():
        for child in sorted(envs_dir.iterdir()):
            if child.is_dir() and child != current:
                prefixes.append((child.name, child))
    return prefixes


def _python_for(env: Path) -> Path | None:
    for name in ("python", "python3", "python.exe"):
        candidate = env / ("Scripts" if name.endswith(".exe") else "bin") / name
        if candidate.is_file():
            return candidate
    return None


def _launcher_for(env: Path) -> Path | None:
    for candidate in (env / "bin" / "inv", env / "Scripts" / "inv.exe"):
        if candidate.is_file():
            return candidate
    return None


def _app_script(checkout: Path | None) -> Path | None:
    if checkout is None:
        return None
    script = checkout / "app.py"
    return script if script.is_file() else None


def _checkout_from_wrapper(launcher: Path | None) -> Path | None:
    """Read the installer's ``inv`` wrapper without executing it."""
    if launcher is None:
        return None
    try:
        text = launcher.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for match in re.finditer(r'["\']([^"\']+\.py)["\']', text):
        candidate = Path(match.group(1)).expanduser()
        if not candidate.is_absolute():
            candidate = launcher.parent / candidate
        candidate = candidate.resolve()
        if candidate.name == "app.py" and candidate.is_file():
            return candidate.parent
    return None


def _checkout_from_pth(env: Path) -> Path | None:
    patterns = (
        "lib/python*/site-packages/invesalius.pth",
        "Lib/site-packages/invesalius.pth",
    )
    for pattern in patterns:
        for pth in env.glob(pattern):
            try:
                lines = pth.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                value = line.strip()
                if not value or value.startswith("#"):
                    continue
                candidate = Path(value).expanduser()
                if not candidate.is_absolute():
                    candidate = pth.parent / candidate
                candidate = candidate.resolve()
                if _app_script(candidate) is not None:
                    return candidate
    return None


def _checkout_from_pip(env: Path, python: Path | None) -> Path | None:
    if python is None:
        return None
    try:
        result = subprocess.run(
            [str(python), "-m", "pip", "show", "InVesalius"],
            capture_output=True, text=True, timeout=_HELP_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    match = re.search(r"^Editable project location:\s*(.+)$",
                      result.stdout, re.MULTILINE)
    if not match:
        return None
    checkout = Path(match.group(1).strip()).expanduser().resolve()
    return checkout if _app_script(checkout) is not None else None


def spec_for_env(env: Path, source: str = "conda") -> LaunchSpec | None:
    """Build and validate a launch spec for one conda environment."""
    env = Path(env).expanduser().resolve()
    python = _python_for(env)
    launcher = _launcher_for(env)
    checkout = _checkout_from_wrapper(launcher) or _checkout_from_pth(env)
    if checkout is None:
        checkout = _checkout_from_pip(env, python)
    if python is None and launcher is None and checkout is None:
        return None
    spec = LaunchSpec(env=env, checkout=checkout, launcher=launcher,
                      python=python, source=source)
    return spec if validate(spec)[0] else None


def validate(spec: LaunchSpec) -> tuple[bool, str]:
    """Run ``--help`` and require the InVesalius ``--remote-host`` option."""
    if (spec.python is not None and spec.checkout is not None
            and _app_script(spec.checkout) is not None):
        argv = [str(spec.python), str(spec.checkout / "app.py"), "--help"]
        cwd = spec.checkout
    elif spec.launcher is not None:
        argv = [str(spec.launcher), "--help"]
        cwd = spec.checkout
    else:
        return False, "no Python, checkout or inv launcher"

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    try:
        result = subprocess.run(
            argv, cwd=str(cwd) if cwd is not None else None,
            capture_output=True, text=True, timeout=_HELP_TIMEOUT,
            env=env,
        )
    except FileNotFoundError as exc:
        return False, f"launcher not found: {exc}"
    except PermissionError as exc:
        return False, f"launcher not executable: {exc}"
    except subprocess.TimeoutExpired:
        return False, f"--help timed out after {_HELP_TIMEOUT:.0f}s"
    except OSError as exc:
        return False, f"could not run launcher: {exc}"

    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        detail = _last_line(output)
        return False, f"--help exited {result.returncode}" + (
            f": {detail}" if detail else "")
    if "--remote-host" not in output:
        return False, "the command is not InVesalius (no --remote-host in --help)"
    return True, ""


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1][:300] if lines else ""


def _from_path(raw: str | os.PathLike[str] | None) -> LaunchSpec | None:
    """Turn a selected env, inv wrapper or app.py path into a candidate."""
    if raw is None:
        return None
    path = Path(str(raw)).expanduser().resolve()
    if path.is_dir():
        if _launcher_for(path) is not None or _python_for(path) is not None:
            return spec_for_env(path, source="selected")
        if _app_script(path) is not None:
            return LaunchSpec(checkout=path, source="selected")
        return None
    if path.name == "app.py" and path.is_file():
        return LaunchSpec(checkout=path.parent, source="selected")
    if path.name in ("inv", "inv.exe") and path.is_file():
        env = path.parent.parent
        return spec_for_env(env, source="selected")
    return None


def _configured_spec() -> LaunchSpec | None:
    for key in ("INVESALIUS_ENV", "INVESALIUS_CHECKOUT",
                "INVESALIUS_LAUNCHER"):
        raw = os.getenv(key, "").strip()
        if not raw:
            continue
        spec = _from_path(raw)
        if spec is not None and validate(spec)[0]:
            return spec
    return None


def _dedupe(specs: Iterable[LaunchSpec]) -> list[LaunchSpec]:
    seen = set()
    result = []
    for spec in specs:
        key = (str(spec.env or ""), str(spec.checkout or ""),
               str(spec.launcher or ""), str(spec.python or ""))
        if key not in seen:
            seen.add(key)
            result.append(spec)
    return result


def discover() -> tuple[list[LaunchSpec], list[str]]:
    """Return valid candidates and human-readable rejection reasons."""
    candidates = []
    errors = []
    for name, prefix in _env_prefixes():
        if not prefix.is_dir():
            continue
        looks_relevant = (
            "invesalius" in name.lower()
            or "invesalius" in prefix.name.lower()
            or _launcher_for(prefix) is not None
        )
        if not looks_relevant:
            continue
        spec = spec_for_env(prefix, source=name)
        if spec is not None:
            candidates.append(spec)
        else:
            errors.append(f"{name}: no working InVesalius launcher at {prefix}")
    return _dedupe(candidates), errors


def _external_spec() -> LaunchSpec:
    """Persist external mode and return a non-launchable sentinel."""
    try:
        from .startup import save_settings
        save_settings((("INVESALIUS_LAUNCH", "external"),))
    except Exception as exc:                 # pragma: no cover - defensive
        print(f"[invesalius] could not save external mode: {exc}",
              flush=True)
    os.environ["INVESALIUS_LAUNCH"] = "external"
    print("[invesalius] using an externally started InVesalius",
          flush=True)
    return LaunchSpec(source="external", external=True)


def _choice(labels: Sequence[str], gui: bool) -> int | None:
    choices = list(labels) + ["Is started (external)"]
    if gui:
        try:
            from PyQt5 import QtWidgets
            if QtWidgets.QApplication.instance() is not None:
                item, ok = QtWidgets.QInputDialog.getItem(
                    None, "Select InVesalius",
                    "Multiple InVesalius environments were found:",
                    choices, 0, False)
                if not ok:
                    return None
                return choices.index(item)
        except Exception:
            pass
    if not sys.stdin.isatty():
        return None
    print("[invesalius] multiple environments found:")
    for index, label in enumerate(choices, 1):
        print(f"  {index}. {label}")
    try:
        answer = input("Select InVesalius [1-%d, blank to skip]: "
                       % len(choices))
    except EOFError:
        return None
    answer = answer.strip()
    if not answer:
        return None
    try:
        index = int(answer) - 1
    except ValueError:
        return None
    return index if 0 <= index < len(choices) else None


def _ask_path(gui: bool) -> LaunchSpec | None:
    if gui:
        try:
            from PyQt5 import QtWidgets
            if QtWidgets.QApplication.instance() is None:
                if not (os.environ.get("DISPLAY")
                        or os.environ.get("WAYLAND_DISPLAY")
                        or sys.platform.startswith("win")
                        or sys.platform == "darwin"):
                    raise RuntimeError("no display")
                QtWidgets.QApplication([])
            app = QtWidgets.QApplication.instance()
            if app is not None:
                box = QtWidgets.QMessageBox()
                box.setWindowTitle("InVesalius")
                box.setIcon(QtWidgets.QMessageBox.Question)
                box.setText("InVesalius was not found.")
                box.setInformativeText(
                    "Select a local environment or launcher, or choose "
                    "'Is started' when InVesalius is already running on "
                    "another machine.")
                box.setMinimumSize(760, 300)
                box.layout().setSizeConstraint(
                    QtWidgets.QLayout.SetMinimumSize)
                select_button = box.addButton(
                    "Select environment…", QtWidgets.QMessageBox.ActionRole)
                external_button = box.addButton(
                    "Is started", QtWidgets.QMessageBox.AcceptRole)
                box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
                box.exec_()
                if box.clickedButton() is external_button:
                    return _external_spec()
                if box.clickedButton() is not select_button:
                    return None

                from .startup import choose_directory, choose_file

                folder = choose_directory(
                    "Select InVesalius conda environment",
                    Path.home(), gui=True)
                if folder:
                    spec = _from_path(folder)
                    if spec is not None and validate(spec)[0]:
                        return spec
                file_name = choose_file(
                    "Select InVesalius inv launcher",
                    "inv (inv inv.exe);;All files (*)",
                    Path.home(), gui=True)
                if file_name:
                    spec = _from_path(file_name)
                    if spec is not None and validate(spec)[0]:
                        return spec
                return None
        except Exception:
            pass
    if not sys.stdin.isatty():
        return None
    try:
        value = input(
            "InVesalius conda env or inv launcher path "
            "(blank to cancel, 'external' if already started): ").strip()
    except EOFError:
        return None
    if value.lower() in ("external", "started", "is started"):
        return _external_spec()
    return _from_path(value) if value else None


def _save(spec: LaunchSpec) -> None:
    try:
        from .lab_profile import LabProfile
        from .startup import save_settings

        current = LabProfile().read()
        values = {
            "INVESALIUS_ENV": str(spec.env) if spec.env is not None else "",
            "INVESALIUS_CHECKOUT": (str(spec.checkout)
                                    if spec.checkout is not None else ""),
            "INVESALIUS_LAUNCHER": (str(spec.launcher)
                                    if spec.launcher is not None else ""),
        }
        if not current.get("INVESALIUS_LAUNCH"):
            values["INVESALIUS_LAUNCH"] = "auto"
        if save_settings(values.items()):
            print("[invesalius] saved launcher configuration", flush=True)
    except Exception as exc:                 # pragma: no cover - defensive
        print(f"[invesalius] could not save launcher configuration: "
              f"{type(exc).__name__}: {exc}", flush=True)


def _relay_is_local(host: str) -> bool:
    host = (host or "").strip().strip("[]")
    if host in ("", "0.0.0.0", "::", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def resolve(remote_host: str, remote_port: int, *, interactive: bool = True,
            gui: bool = False, override: str | os.PathLike[str] | None = None,
            save: bool = True) -> LaunchSpec | None:
    """Find a local InVesalius installation, or return ``None``.

    ``None`` is a normal result, not an error: real/manual/training sessions can
    still use an externally started InVesalius.
    """
    mode = os.getenv("INVESALIUS_LAUNCH", "auto").strip().lower() or "auto"
    if mode in _OFF_VALUES:
        print("[invesalius] auto-start disabled by INVESALIUS_LAUNCH", flush=True)
        return None
    if mode not in _LOCAL_VALUES:
        print(f"[invesalius] unknown INVESALIUS_LAUNCH={mode!r}; using auto",
              flush=True)
        mode = "auto"
    if mode == "auto" and not _relay_is_local(remote_host):
        print(f"[invesalius] relay {remote_host}:{remote_port} is remote; "
              "expecting an external InVesalius", flush=True)
        return None

    try:
        selected = _from_path(override) if override else _configured_spec()
    except Exception as exc:                 # pragma: no cover - defensive
        print(f"[invesalius] could not read the configured launcher: "
              f"{type(exc).__name__}: {exc}", flush=True)
        selected = None
    if selected is not None:
        ok, detail = validate(selected)
        if ok:
            if save and override:
                _save(selected)
            return selected
        print(f"[invesalius] configured launcher is invalid ({detail}); "
              "searching again", flush=True)
    elif override:
        print(f"[invesalius] selected path is not a usable InVesalius "
              f"launcher: {override}", flush=True)

    try:
        candidates, errors = discover()
    except Exception as exc:                 # pragma: no cover - defensive
        print(f"[invesalius] discovery failed: {type(exc).__name__}: {exc}",
              flush=True)
        candidates, errors = [], []
    if len(candidates) > 1:
        labels = [f"{spec.env or spec.checkout or spec.launcher}" for spec in candidates]
        index = _choice(labels, gui) if interactive or gui else None
        if index is None:
            print("[invesalius] no environment selected; continuing without "
                  "auto-start", flush=True)
            return None
        if index == -1:
            return _external_spec()
        selected = candidates[index]
    elif len(candidates) == 1:
        selected = candidates[0]
    else:
        for error in errors[:4]:
            print(f"[invesalius] {error}", flush=True)
        selected = _ask_path(gui) if interactive or gui else None
        if selected is None:
            print("[invesalius] no launchable InVesalius found; continuing "
                  "without auto-start. Set INVESALIUS_LAUNCHER or start it "
                  "manually with --remote-host.", flush=True)
            return None

    if selected.external:
        return selected
    ok, detail = validate(selected)
    if not ok:
        print(f"[invesalius] selected launcher is invalid: {detail}", flush=True)
        return None
    if save:
        _save(selected)
    return selected
