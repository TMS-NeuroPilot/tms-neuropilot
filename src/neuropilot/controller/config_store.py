"""Read and write the suite's ``.env`` from the GUI.

Only the keys the Config tab manages are rewritten; comments, ordering and
unknown entries in the file are preserved. Values are plain strings — the
tab decides how to parse them.
"""

import os
import re
from pathlib import Path

# Order used when new keys are appended to the file.
MANAGED_KEYS = (
    "RELAY_HOST", "RELAY_PORT",
    "ROOT_FOLDER", "NEUROPILOT_UI_SCALE",
    "ROBOT",
    "STIMULATOR_PORT", "STIMULATOR_TTL_PORT",
    "EMG_CHANNELS", "EMG_COMPUTER_IP", "EMG_COMPUTER_USERNAME",
    "EMG_COMPUTER_PASSWORD",
    "SAMPLING_RATE", "CUTOFF_FREQ", "TMS_PULSE_TIME",
    "START_MEP", "END_MEP",
    "ONLINE_FEM_SOLVER", "ONLINE_FEM_ANISOTROPY",
    "TMS_ROBOT_CONTROL_PATH",
)

_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def _clean(value: str) -> str:
    """Strip surrounding quotes and inline comments the way dotenv does."""
    value = value.strip()
    if not value:
        return ""
    if value[0] in "\"'":
        quote = value[0]
        end = value.find(quote, 1)
        if end != -1:
            return value[1:end]
    return value.split("#", 1)[0].strip()


class ConfigStore:
    """Editor for the suite ``.env`` file."""

    def __init__(self, path=None):
        if path is None:
            repo_root = Path(__file__).resolve().parents[3]
            path = repo_root / ".env"
        self.path = Path(path)

    # ── reading ─────────────────────────────────────────────────────
    def read(self):
        """Current values of the managed keys (empty dict if no file)."""
        values = {}
        if not self.path.is_file():
            return values
        try:
            text = self.path.read_text()
        except OSError:
            return values
        for line in text.splitlines():
            match = _LINE.match(line)
            if not match:
                continue
            key, raw = match.group(1), match.group(2)
            if key in MANAGED_KEYS:
                values[key] = _clean(raw)
        return values

    # ── writing ─────────────────────────────────────────────────────
    def write(self, values):
        """Update ``values`` in place, keeping every other line untouched."""
        values = {k: v for k, v in values.items()
                  if k in MANAGED_KEYS and v is not None}
        lines = []
        if self.path.is_file():
            try:
                lines = self.path.read_text().splitlines()
            except OSError:
                lines = []

        seen = set()
        for i, line in enumerate(lines):
            match = _LINE.match(line)
            if not match or match.group(1) not in values:
                continue
            key = match.group(1)
            seen.add(key)
            lines[i] = f"{key}={values[key]}"

        missing = [k for k in MANAGED_KEYS if k in values and k not in seen]
        if missing:
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend(f"{key}={values[key]}" for key in missing)

        text = "\n".join(lines).rstrip() + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(text)
        os.replace(tmp, self.path)
        return values
