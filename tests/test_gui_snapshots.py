"""Screenshot/structure snapshots of the main pages.

The About page is intentionally not fingerprinted here: it is static
text/labels, and regenerating a baseline needs a display on a workstation.

A coarse pixel fingerprint (32x24 grayscale) plus the geometry of the named
widgets catches a broken ``.ui`` file or a style-sheet regression without being
sensitive to font hinting between machines.

Regenerate the baselines after an intentional design change::

    UPDATE_GUI_BASELINES=1 pytest tests/test_gui_snapshots.py

The current rendering is written to ``tmp_path`` when a page drifts, so the
failure can be compared with the baseline by eye.
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest

QtCore = pytest.importorskip("PyQt5.QtCore")
QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

PAGES = ["Project", "Connections", "Control", "MEP results",
         "Cortical results", "Collision test", "Config"]
SIZE = (1244, 960)
COLS, ROWS = 32, 24
BASELINE = Path(__file__).parent / "baselines" / "gui_pages.json"

# Coarse fingerprint tolerance.  Two captures of the same build are identical
# (mean 0.00), so the budget is only for font hinting between machines; a
# 2 px border or a hidden card already costs ~1.5 grey levels of mean.
# Layout/visibility changes are caught by the structure check as well.
MEAN_TOLERANCE = 1.0
MAX_TOLERANCE = 24
CHANGED_FRACTION = 0.04       # cells allowed to jump by more than CHANGED_BY
CHANGED_BY = 20
# Geometry tolerance (px): layouts follow font metrics.
GEOMETRY_TOLERANCE = 8


class _DummyRobotView:
    """Keep the MuJoCo view static so the Control page is reproducible."""

    def __init__(self, label, parent=None):
        self.label = label
        self.stopped = False

    def start(self):
        self.label.setText("")

    def stop(self):
        self.stopped = True

    def set_qpos(self, qpos):
        pass


@pytest.fixture()
def snap_window(qapp, gui_env, monkeypatch):
    """A window whose robot view cannot repaint itself between grabs."""
    from neuropilot.controller import robot_scene_view
    from helpers import build_window

    monkeypatch.setattr(robot_scene_view, "RobotSceneView", _DummyRobotView)
    win = build_window(qapp, gui_env, monkeypatch)
    win.showNormal()
    qapp.processEvents()
    try:
        yield win
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()


@pytest.fixture()
def snapshots(snap_window):
    return capture(snap_window)


def fingerprint(image):
    """32x24 grayscale of the whole window."""
    scaled = image.scaled(COLS, ROWS, QtCore.Qt.IgnoreAspectRatio,
                          QtCore.Qt.SmoothTransformation)
    values = []
    for y in range(ROWS):
        for x in range(COLS):
            colour = scaled.pixelColor(x, y)
            values.append(int(round((colour.red() + colour.green()
                                     + colour.blue()) / 3)))
    return values


def structure(page):
    """Visible named widgets of a page as (name, x, y, w, h)."""
    entries = []
    for child in page.findChildren(QtWidgets.QWidget):
        name = child.objectName()
        if not name or not child.isVisible() or child.width() < 40:
            continue
        top_left = child.mapTo(page, QtCore.QPoint(0, 0))
        entries.append([name, top_left.x(), top_left.y(),
                        child.width(), child.height()])
    return sorted(entries)


def capture(window):
    pages = {}
    for index, name in enumerate(PAGES):
        window.tabWidget.setCurrentIndex(index)
        QtWidgets.QApplication.processEvents()
        image = window.grab().toImage()
        page = window.tabWidget.widget(index)
        pages[name] = {"fingerprint": fingerprint(image),
                       "structure": structure(page)}
    return {"size": list(SIZE), "pages": pages}


def load_baseline():
    if not BASELINE.is_file():
        return None
    return json.loads(BASELINE.read_text())


def update_baseline(data):
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def test_baseline_exists():
    if os.getenv("UPDATE_GUI_BASELINES"):
        pytest.skip("baselines are being regenerated")
    assert BASELINE.is_file(), (
        "no GUI baseline; create it with UPDATE_GUI_BASELINES=1")


def test_generate_baseline_when_requested(snapshots):
    """``UPDATE_GUI_BASELINES=1`` rewrites the committed baseline."""
    if not os.getenv("UPDATE_GUI_BASELINES"):
        pytest.skip("set UPDATE_GUI_BASELINES=1 to regenerate the baseline")
    update_baseline(snapshots)
    assert BASELINE.is_file()


@pytest.mark.parametrize("page", PAGES)
def test_page_fingerprint_matches_baseline(snap_window, snapshots, page, tmp_path):
    if os.getenv("UPDATE_GUI_BASELINES"):
        pytest.skip("baselines are being regenerated")
    baseline = load_baseline()
    assert baseline is not None, (
        "no GUI baseline; create it with UPDATE_GUI_BASELINES=1")

    current = np.array(snapshots["pages"][page]["fingerprint"], dtype=int)
    reference = np.array(baseline["pages"][page]["fingerprint"], dtype=int)
    diff = np.abs(current - reference)

    changed = float((diff > CHANGED_BY).mean())
    if (diff.mean() > MEAN_TOLERANCE or diff.max() > MAX_TOLERANCE
            or changed > CHANGED_FRACTION):
        snap_window.tabWidget.setCurrentIndex(PAGES.index(page))
        QtWidgets.QApplication.processEvents()
        target = tmp_path / f"{page.replace(' ', '_')}.png"
        snap_window.grab().save(str(target))
        pytest.fail(
            f"{page}: layout/style drift (mean {diff.mean():.2f}, "
            f"max {diff.max()}, changed {changed:.0%}); "
            f"current rendering: {target}. "
            "If the change is intended run "
            "UPDATE_GUI_BASELINES=1 pytest tests/test_gui_snapshots.py")


@pytest.mark.parametrize("page", PAGES)
def test_page_structure_matches_baseline(snapshots, page):
    if os.getenv("UPDATE_GUI_BASELINES"):
        pytest.skip("baselines are being regenerated")
    baseline = load_baseline()
    assert baseline is not None

    current = {row[0]: row[1:] for row in snapshots["pages"][page]["structure"]}
    reference = {row[0]: row[1:] for row in baseline["pages"][page]["structure"]}

    missing = sorted(set(reference) - set(current))
    added = sorted(set(current) - set(reference))
    assert not missing, f"{page}: widgets disappeared: {missing}"
    assert not added, f"{page}: new visible widgets: {added}"

    for name, ref in reference.items():
        cur = current[name]
        drift = [abs(a - b) for a, b in zip(cur, ref)]
        assert max(drift) <= GEOMETRY_TOLERANCE, (
            f"{page}: {name} moved/resized by {drift} px "
            f"(was {ref}, now {cur})")


def test_window_size_is_the_design_size(snap_window):
    assert (snap_window.width(), snap_window.height()) == SIZE


def test_every_page_renders_something(snapshots):
    for page in PAGES:
        values = snapshots["pages"][page]["fingerprint"]
        assert len(values) == COLS * ROWS
        assert min(values) >= 0 and max(values) <= 255
        assert max(values) - min(values) > 10, f"{page} looks blank"


pytestmark = pytest.mark.gui
