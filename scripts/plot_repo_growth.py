"""Plot repository growth: lines of code per commit over time.

Two series: all code (tests included) and code without tests.
Counts lines in tracked source files only; binary assets, data files and
documentation are ignored. The line counts come from the committed blobs
(the working tree may hold LFS-smudged data files).

Large jumps of the no-tests curve are labelled, always with the text to the
right of the jump, using a short version of the commit subject so the curve
can be read without consulting git log.
"""

import math
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parents[1]

# Source extensions counted as "code".
CODE_EXT = {
    ".py", ".sh", ".toml", ".yml", ".yaml", ".ini", ".cfg",
    ".ui", ".js", ".css", ".html", ".cpp", ".h", ".hpp", ".c",
}

# Jumps of the no-tests curve at least this large get a label.
JUMP_THRESHOLD = 600

# Short labels for the commits worth pointing at, keyed by a prefix of the
# original subject. Anything unlisted falls back to a truncated subject.
SHORT_LABELS = [
    ("Merge the pipeline controller", "four component repos merged"),
    ("Add head-model creation script", "head-model creation script"),
    ("Mapping results: overlay", "mapping-results overlay"),
    ("Consolidate the GUI definitions", "GUI definitions consolidated"),
    ("Rebuild the controller GUI", "GUI rebuilt (Workstation design)"),
    ("Allow switching the E-field mode", "runtime E-field mode switch"),
    ("Harden the GUI against bad files", "GUI hardening (files, threads)"),
    ("Keep the experiment loop controllable", "controllable experiment loop"),
    ("Harden the hardware drivers", "hardware/relay hardening"),
    ("Add five colour themes", "five colour themes"),
    ("Publish the full documentation", "docs site generator"),
    ("Add the Interpolated E-field mode", "Interpolated E-field mode"),
    ("Load project files without blocking", "non-blocking project load"),
    ("Add collision-test planner", "collision-test planner"),
    ("Add the collision", "collision controls polish"),
    ("Align collision controls", "collision controls polish"),
    ("Auto-start InVesalius", "auto-start InVesalius"),
]


def is_test(path: str) -> bool:
    parts = path.split("/")
    if "tests" in parts[:-1]:
        return True
    name = parts[-1]
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(REPO), *args], text=True)


def short_subject(subject: str, limit: int = 34) -> str:
    for prefix, short in SHORT_LABELS:
        if subject.startswith(prefix):
            return short
    if len(subject) <= limit:
        return subject
    cut = subject[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def annotate_jumps(ax, fig, jumps, occupied, lines):
    """Label the jumps of the red (no-tests) curve.

    The text always sits to the right of the jump corner. A position is
    accepted only if it stays inside the axes, does not overlap an already
    placed label (or the legend), and does not sit on either curve.
    """
    from matplotlib.text import Text

    renderer = fig.canvas.get_renderer()
    ax_bb = ax.get_window_extent(renderer)

    # Dense samples of the drawn lines in display coordinates, used to keep
    # the labels off the curve itself.
    chunks = []
    for line in lines:
        disp = line.get_transform().transform(line.get_path().vertices)
        for (x0, y0), (x1, y1) in zip(disp[:-1], disp[1:]):
            n = max(1, int(math.hypot(x1 - x0, y1 - y0) / 6))
            chunks.append(np.column_stack([
                np.linspace(x0, x1, n + 1), np.linspace(y0, y1, n + 1)]))
    curve = np.vstack(chunks)

    # Candidate offsets in points; dx is always positive so the text stays to
    # the right of the jump.
    candidates = []
    for dx in (16, 30, 48, 70, 96, 128, 164):
        for dy in (10, -8, 22, -20, 0, 34, -32, 48, -46):
            candidates.append((dx, dy))

    def free(bb: "Bbox") -> bool:
        margin = 2
        if not (bb.x0 >= ax_bb.x0 + margin and bb.x1 <= ax_bb.x1 - margin
                and bb.y0 >= ax_bb.y0 + margin and bb.y1 <= ax_bb.y1 - margin):
            return False
        if any(not (bb.x1 + margin < o.x0 or bb.x0 - margin > o.x1
                    or bb.y1 + margin < o.y0 or bb.y0 - margin > o.y1)
               for o in occupied):
            return False
        hit = ((curve[:, 0] >= bb.x0 - 3) & (curve[:, 0] <= bb.x1 + 3)
               & (curve[:, 1] >= bb.y0 - 3) & (curve[:, 1] <= bb.y1 + 3))
        return not hit.any()

    for t, y, label, _delta in sorted(jumps, key=lambda j: -abs(j[3])):
        for dx, dy in candidates:
            ann = ax.annotate(
                label, xy=(t, y), xytext=(dx, dy), textcoords="offset points",
                fontsize=8, color="#333333", ha="left", va="center",
                bbox=dict(boxstyle="round,pad=0.28", fc="white", ec="0.75",
                          lw=0.4, alpha=0.92),
                arrowprops=dict(arrowstyle="-", color="0.55", lw=0.6,
                                shrinkA=3, shrinkB=2),
                zorder=6,
            )
            # Text-only bbox: Annotation.get_window_extent would include the
            # leader line and so always touch the curve at the anchor. The
            # positions must be refreshed first, otherwise the bbox is still
            # in offset points (the annotation was never drawn yet).
            ann.update_positions(renderer)
            bb = Text.get_window_extent(ann, renderer).expanded(1.06, 1.35)
            if free(bb):
                occupied.append(bb)
                break
            ann.remove()
        else:
            print(f"  warning: no room for label {label!r}", flush=True)


def main() -> None:
    commits = []
    for line in git("log", "--reverse", "--format=%H|%ct|%ad|%s",
                    "--date=format:%Y-%m-%d %H:%M:%S", "HEAD").strip().splitlines():
        sha, ct, ad, subject = line.split("|", 3)
        commits.append((sha, int(ct), ad, subject))
    print(f"{len(commits)} commits", flush=True)

    # Cache line counts per blob so unchanged files are counted once.
    blob_cache: dict[str, int] = {}

    def blob_lines(sha: str) -> int:
        if sha not in blob_cache:
            data = subprocess.check_output(
                ["git", "-C", str(REPO), "cat-file", "blob", sha]
            )
            blob_cache[sha] = data.count(b"\n")  # same convention as `wc -l`
        return blob_cache[sha]

    rows = []
    for i, (sha, ct, _ad, subject) in enumerate(commits, 1):
        total = no_tests = 0
        for entry in git("ls-tree", "-r", sha).splitlines():
            meta, path = entry.split("\t", 1)
            if Path(path).suffix.lower() not in CODE_EXT:
                continue
            if path.startswith("data/"):  # simulation data, not code
                continue
            n = blob_lines(meta.split()[2])
            total += n
            if not is_test(path):
                no_tests += n
        rows.append((datetime.fromtimestamp(ct), total, no_tests, subject))
        if i % 50 == 0 or i == len(commits):
            print(
                f"  {i}/{len(commits)}  {rows[-1][0]:%Y-%m-%d %H:%M}  "
                f"all={total}  no-tests={no_tests}",
                flush=True,
            )

    dates = [r[0] for r in rows]
    total_loc = [r[1] for r in rows]
    code_loc = [r[2] for r in rows]

    fig, ax = plt.subplots(figsize=(13.5, 7), dpi=150)
    ax.fill_between(dates, code_loc, total_loc, step="post", color="#1f77b4", alpha=0.12)
    totals_line, = ax.step(dates, total_loc, where="post", color="#1f77b4", lw=1.8,
                           label="all code (tests included)")
    code_line, = ax.step(dates, code_loc, where="post", color="#d62728", lw=1.8,
                         label="code without tests")

    ax.set_xlabel("commit date (local time)")
    ax.set_ylabel("lines of code")
    ax.set_title("neuropilot: repository growth per commit")
    ax.grid(alpha=0.3)
    ax.set_ylim(0, max(total_loc) * 1.10)
    span = dates[-1] - dates[0]
    ax.set_xlim(dates[0] - span * 0.02, dates[-1] + span * 0.08)
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b"))
    ax.xaxis.set_minor_locator(mdates.HourLocator(byhour=[6, 12, 18]))
    fig.autofmt_xdate(rotation=30, ha="right")

    # Collect the no-tests jumps to label (gain: top of the step, drop: the
    # value before the drop).
    jumps = []
    prev = None
    for d, _t, c, subject in rows:
        if prev is not None and abs(c - prev) >= JUMP_THRESHOLD:
            jumps.append((d, c if c > prev else prev, short_subject(subject), c - prev))
        prev = c
    print(f"labelling {len(jumps)} jumps", flush=True)

    legend = ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    fig.canvas.draw()
    occupied = [legend.get_window_extent(fig.canvas.get_renderer()).expanded(1.02, 1.1)]
    annotate_jumps(ax, fig, jumps, occupied, [totals_line, code_line])

    out = REPO / "docs" / "repo_growth.png"
    fig.savefig(out)

    csv = REPO / "docs" / "repo_growth.csv"
    with open(csv, "w") as fh:
        fh.write("commit_time,loc_all,loc_without_tests\n")
        for d, t, c, _ in rows:
            fh.write(f"{d.isoformat(sep=' ')},{t},{c}\n")

    print(f"wrote {out} and {csv}")
    print(f"tip: all={total_loc[-1]}, without tests={code_loc[-1]}, "
          f"tests={total_loc[-1] - code_loc[-1]}")


if __name__ == "__main__":
    sys.exit(main())
