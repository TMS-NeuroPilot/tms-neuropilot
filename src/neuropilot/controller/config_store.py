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
    # Lab profile keys that may also be pinned from .env (see lab_profile.py).
    "UI_THEME",
)

_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "'": "'", "\\": "\\"}


def _clean(value: str) -> str:
    """Read a value the way python-dotenv does.

    * a quoted value keeps everything up to its closing quote (``\\"`` escapes
      a double quote), so ``#`` and spaces survive;
    * an unquoted value is cut at a ``#`` that follows whitespace -- a ``#``
      inside a password or path (``p#ss``) is *not* a comment, which the old
      ``split('#')`` got wrong and silently truncated the value;
    * surrounding whitespace is dropped.
    """
    value = value.strip()
    if not value:
        return ""
    if value[0] in "\"'":
        quote = value[0]
        out = []
        i = 1
        while i < len(value):
            char = value[i]
            if quote == '"' and char == "\\" and i + 1 < len(value):
                # Decode the escapes python-dotenv knows; an unknown sequence
                # keeps its backslash (a Windows path must survive).
                decoded = _ESCAPES.get(value[i + 1])
                if decoded is not None:
                    out.append(decoded)
                    i += 2
                    continue
                out.append(char)
                i += 1
                continue
            if char == quote:
                break
            out.append(char)
            i += 1
        return "".join(out)
    comment = re.search(r"\s#", value)
    if comment is not None:
        value = value[:comment.start()]
    return value.strip()


def _format(value: str) -> str:
    """Write a value so python-dotenv reads it back unchanged.

    Anything that could be re-interpreted -- a comment ``#``, whitespace,
    quotes, a backslash, an empty string -- is double-quoted with ``\\`` and
    ``"`` escaped (the only escapes dotenv decodes).  Plain values are left
    alone so the file keeps its familiar look.
    """
    value = str(value)
    if value == "":
        return ""
    if value == value.strip() and not re.search(r'[\s#"\'\\]', value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class ConfigStore:
    """Editor for the suite ``.env`` file."""

    def __init__(self, path=None):
        if path is None:
            override = os.getenv("NEUROPILOT_ENV_FILE")
            if override:
                path = Path(override).expanduser()
            else:
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
            lines[i] = f"{key}={_format(values[key])}"

        missing = [k for k in MANAGED_KEYS if k in values and k not in seen]
        if missing:
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend(f"{key}={_format(values[key])}" for key in missing)

        text = "\n".join(lines).rstrip() + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(text)
        os.replace(tmp, self.path)
        return values
