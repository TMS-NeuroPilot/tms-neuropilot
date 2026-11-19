#!/usr/bin/env python3
"""Rasterize the generated diagram SVGs to PNG with QtSvg.

    python docs/site/tools/make_diagram_pngs.py
    python docs/site/tools/make_diagram_pngs.py --only mapping-loop mapping-loop-vertical

The SVG files remain the source of truth; the PNGs are convenience copies for
slides and chat clients.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtGui, QtSvg  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
DIAGRAMS = REPO / "docs" / "site" / "assets" / "diagrams"


def render(svg_path: Path) -> Path:
    renderer = QtSvg.QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise RuntimeError(f"invalid SVG: {svg_path}")
    size = renderer.defaultSize()
    image = QtGui.QImage(size, QtGui.QImage.Format_ARGB32)
    image.fill(QtGui.QColor("#FFFFFF"))
    painter = QtGui.QPainter(image)
    renderer.render(painter)
    painter.end()
    out = svg_path.with_suffix(".png")
    if not image.save(str(out), "PNG"):
        raise RuntimeError(f"could not write {out}")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only", nargs="*", default=None,
        help="diagram basenames without .svg; default: every SVG")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication([])
    wanted = set(args.only) if args.only else None
    paths = sorted(DIAGRAMS.glob("*.svg"))
    if wanted is not None:
        paths = [path for path in paths if path.stem in wanted]
    if not paths:
        raise SystemExit("no matching diagrams")
    for path in paths:
        out = render(path)
        print(f"wrote {out.relative_to(REPO)}")
    # Keep the application alive until QPainter has released its resources.
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
