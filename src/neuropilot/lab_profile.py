"""Lab profile: the hardware settings shared by every component.

Stored in ``~/.neuropilot/lab.yaml`` (override the location with
``NEUROPILOT_LAB_FILE``).  Precedence, highest first:

    shell environment  >  .env  >  lab.yaml  >  built-in defaults

``.env`` therefore stays the bootstrap/override layer: any key it still
defines wins over the lab profile, so existing installations keep working
unchanged and a site can pin a value without touching the GUI.  The Config ›
Lab page edits this file; see ``docs/CONFIG.md``.

The module only depends on ``yaml`` and is imported by ``neuropilot.config``
before any component package, so it must stay free of GUI/heavy imports.
"""

import os
from pathlib import Path

import yaml

# Order used in the GUI and in the written file.
LAB_KEYS = (
    "RELAY_HOST", "RELAY_PORT",
    "ROOT_FOLDER", "NEUROPILOT_UI_SCALE", "UI_THEME",
    "ROBOT", "TMS_ROBOT_CONTROL_PATH",
    "STIMULATOR_PORT", "STIMULATOR_TTL_PORT",
    "EMG_COMPUTER_IP", "EMG_COMPUTER_USERNAME", "EMG_COMPUTER_PASSWORD",
    "ONLINE_FEM_SOLVER", "ONLINE_FEM_ANISOTROPY",
    "COLLISION_TEST",
)

def _serial_defaults():
    """Platform-aware serial/TTL port defaults for the stimulator.

    Linux uses the classic ``/dev/ttyS*`` serial and ``/dev/parport*``
    parallel (TTL) devices. Windows has no ``/dev`` namespace: serial ports
    are ``COM*`` (there is no universal default, ``COM3`` is the common
    first external port), and a TTL line is only available through vendor
    parallel hardware, so it defaults to empty there. Either is overridden
    by ``.env`` / the lab profile.
    """
    if os.name == "nt":
        return "COM3", ""
    return "/dev/ttyS1", "/dev/parport0"


STIMULATOR_PORT_DEFAULT, STIMULATOR_TTL_PORT_DEFAULT = _serial_defaults()

# Same values as the Config tab has always shown; kept here so a missing
# lab.yaml (and a missing .env) still yields the documented defaults.
DEFAULTS = {
    "RELAY_HOST": "127.0.0.1",
    "RELAY_PORT": "5000",
    "ROOT_FOLDER": str(Path.home() / ".neuropilot"),
    "NEUROPILOT_UI_SCALE": "",
    "UI_THEME": "Workstation Light",
    "ROBOT": "omron",
    "TMS_ROBOT_CONTROL_PATH": "",
    "STIMULATOR_PORT": STIMULATOR_PORT_DEFAULT,
    "STIMULATOR_TTL_PORT": STIMULATOR_TTL_PORT_DEFAULT,
    "EMG_COMPUTER_IP": "192.168.1.2",
    "EMG_COMPUTER_USERNAME": "neuro",
    "EMG_COMPUTER_PASSWORD": "",
    "ONLINE_FEM_SOLVER": "pardiso",
    "ONLINE_FEM_ANISOTROPY": "scalar",
    "COLLISION_TEST": "",
}

_HEADER = """\
# NeuroPilot lab profile -- hardware settings shared by every component.
# Edited in Config > Lab.  Precedence (highest first):
#   shell environment  >  .env  >  this file  >  built-in defaults
# so a key you keep in .env still wins over the value here.
"""


def default_path():
    """``NEUROPILOT_LAB_FILE`` or ``~/.neuropilot/lab.yaml``."""
    explicit = os.getenv("NEUROPILOT_LAB_FILE")
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".neuropilot" / "lab.yaml"


def read(path=None):
    """Known lab keys from the profile (empty dict when missing/unreadable)."""
    path = Path(path) if path is not None else default_path()
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        print(f"[WARN] lab profile unreadable ({path}): {e}")
        return {}
    if not isinstance(data, dict):
        print(f"[WARN] lab profile ignored ({path}): expected a mapping")
        return {}
    values = {}
    for key in LAB_KEYS:
        if data.get(key) is not None:
            values[key] = str(data[key])
    return values


def write(values, path=None):
    """Merge ``values`` into the profile and write it atomically."""
    path = Path(path) if path is not None else default_path()
    incoming = {k: str(v) for k, v in (values or {}).items()
                if k in LAB_KEYS and v is not None}
    merged = read(path)
    merged.update(incoming)
    body = {k: merged[k] for k in LAB_KEYS if k in merged}
    text = _HEADER + yaml.safe_dump(body, sort_keys=False,
                                    default_flow_style=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return incoming


def apply_environment(values=None, environ=None):
    """Export lab values for keys the shell or ``.env`` did not define.

    Returns the keys that were applied (useful for diagnostics and tests).
    An empty value means "unset" and is skipped, so a blank field in the GUI
    falls back to the built-in default instead of exporting "".
    """
    environ = os.environ if environ is None else environ
    applied = []
    for key, value in (read() if values is None else values).items():
        if key not in LAB_KEYS or key == "COLLISION_TEST" \
                or not str(value).strip():
            continue
        if key not in environ:
            environ[key] = str(value)
            applied.append(key)
    return applied


class LabProfile:
    """One lab profile file, with the reader/writer the Config tab needs."""

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_path()

    def read(self):
        return read(self.path)

    def write(self, values):
        return write(values, self.path)

    def env_keys(self, env_store):
        """Keys the profile defines that ``.env`` also pins (i.e. overridden)."""
        env = env_store.read() if env_store is not None else {}
        return [k for k in self.read() if k in env]
