"""Single source of truth for cross-component configuration.

Component-internal constants (topic names, tolerances, physics parameters)
stay in each component's own ``config.py``; everything that must agree
between components lives here and is environment-overridable.

``.env`` is loaded from the repository root once, here, before any component
package is imported (some components read environment variables at import
time, e.g. the controller's ROOT_FOLDER).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from .lab_profile import apply_environment

REPO_ROOT = Path(__file__).resolve().parents[2]

# Load the suite-wide .env before any component reads os.environ.
# load_dotenv does not override variables already set in the environment, so
# explicit exports win over .env values.
load_dotenv(REPO_ROOT / ".env")

# Config > Lab edits ~/.neuropilot/lab.yaml.  It is the layer *below* .env:
# only keys the shell and .env left unset are exported here, so .env remains
# the override layer and existing installations behave exactly as before.
LAB_PROFILE_KEYS = apply_environment()


def _env(key: str, default: str) -> str:
    value = os.getenv(key, default)
    # Export it so child processes and import-time readers see the same value.
    os.environ.setdefault(key, value)
    return value


# ── Relay ────────────────────────────────────────────────────────────────────
RELAY_HOST = _env("RELAY_HOST", "127.0.0.1")
RELAY_PORT = int(_env("RELAY_PORT", "5000"))

# ── Data location (controller writes plots/results under this) ──────────────
# The controller does os.makedirs() under ROOT_FOLDER at import time; it must
# exist and be writable on every machine (the GitLab default pointed at an
# MPCDF cluster path).
ROOT_FOLDER = _env("ROOT_FOLDER", str(Path.home() / ".neuropilot"))
os.makedirs(ROOT_FOLDER, exist_ok=True)

# ── MuJoCo viewer on Wayland machines ────────────────────────────────────────
# GLFW ships an X11-only build in ~/.local/share/x11-glfw on this machine;
# the supervisor exports it for the sim_robot child when present.
PYGLFW_LIBRARY = os.getenv("PYGLFW_LIBRARY", "")
_X11_GLFW = Path.home() / ".local/share/x11-glfw/lib/libglfw.so.3"
if not PYGLFW_LIBRARY and _X11_GLFW.exists():
    PYGLFW_LIBRARY = str(_X11_GLFW)

# ── Real mode ────────────────────────────────────────────────────────────────
# Optional: path to a tms-robot-control checkout, used by
# `neuropilot real --launch-relay` to start the production relay.
TMS_ROBOT_CONTROL_PATH = _env("TMS_ROBOT_CONTROL_PATH", "")

READINESS_TIMEOUT_S = float(_env("READINESS_TIMEOUT_S", "60"))
