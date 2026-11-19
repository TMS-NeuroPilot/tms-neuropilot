#!/usr/bin/env python3
"""TMS NeuroPilot logo — concept 06 "Trajectory N x lock-on ring" build script.

Single source of geometric truth; emits
  * SVG masters (dark / light tile, mono marks, favicon variant)
  * PNG raster ramp rendered independently with the same geometry in Pillow
    (no cairosvg / rsvg available on this machine)

Design (viewBox units 512):
  rounded-square tile, bold monoline N built from two square-end stems and a
  shallow S-curve diagonal that ends in a focal dot wrapped by a broken lock-on
  ring; a small waypoint dot marks where the trajectory leaves the left stem.
"""
import math
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "assets", "img")
os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------- palette ---
TILE_DARK = "#1B2028"      # charcoal (logo tile, close to the draft renders)
TILE_LIGHT = "#FFFFFF"
INK_DARK = "#F2EEE3"       # cream glyph on the dark tile
INK_LIGHT = "#14181F"      # near-black glyph on light
AMBER_DARK = "#F2A93F"     # house accent on dark (docs --accent dark token)
AMBER_LIGHT = "#B45309"    # house accent on light (docs --accent light token)

# --------------------------------------------------------------- geometry ---
CANVAS = 512
TILE_RX = 112

STEM_W = 58          # monoline stroke width
STEM_TOP = 108
STEM_BOT = 404
XL = 169             # left stem centre x
XR = 336             # right stem centre x
STEM_RX = 4          # corner softening of stem rectangles

START_DOT = (XL - STEM_W / 2, STEM_TOP)          # waypoint sphere centred on the
                                                 # stem's top-LEFT corner point
CURVE_START = (XL, STEM_TOP + STEM_W / 2)        # ribbon top edge flush with stem top
FOCAL = (352, 398)
FOCAL_R = 32
START_R = 32
RING_R = 63
RING_W = 11
# broken ring: entry gap centred at 135 deg (upper left, facing the incoming
# diagonal), tiny exit gap at 305 deg (lower right).  SVG coords = PIL angles
# (deg, clockwise from east, y down).
# broken ring: two equal gaps ON THE TRAJECTORY AXIS - entry at 235 deg
# (upper left, where the diagonal approaches), exit at 55 deg (lower right).
# Equal 24 deg gaps -> the two ring halves are exactly symmetric (156 deg
# of arc each)
RING_GAPS = ((235, 24), (55, 24))

CP1 = (285, CURVE_START[1])     # CP1.y == CURVE_START.y keeps the join tangent
                                # horizontal where the straight run hands over
CP2 = (208, 312)
STRAIGHT_RUN_END = 195          # short exact horizontal run so the top edge is one
                                # continuous straight line out of the stem corner
                                # (no junction ledge); long enough to hide the
                                # curvature onset behind/beside the sphere but
                                # short enough that the glyph still reads as N

TILE_RA = 0.22       # tile corner radius as fraction of size for arbitrary sizes


def cubic(p0, p1, p2, p3, n=96):
    return [(
        (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t ** 2 * p2[0] + t ** 3 * p3[0],
        (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t ** 2 * p2[1] + t ** 3 * p3[1],
    ) for t in [i / n for i in range(n + 1)]]


# ------------------------------------------------------------------- SVG ----
def mark_path_points():
    """Centerline samples: straight horizontal run, then the S-curve."""
    pts = [(x, CURVE_START[1]) for x in
           [CURVE_START[0] + (STRAIGHT_RUN_END - CURVE_START[0]) * i / 16 for i in range(17)]]
    pts += cubic((STRAIGHT_RUN_END, CURVE_START[1]), CP1, CP2, FOCAL, n=512)
    return pts


def svg_mark_body(fill, accent, include_ring=True):
    """Glyph internals (no tile), coordinate strings only."""
    d = (f"M {CURVE_START[0]} {CURVE_START[1]} L {STRAIGHT_RUN_END} {CURVE_START[1]} "
         f"C {CP1[0]} {CP1[1]} {CP2[0]} {CP2[1]} {FOCAL[0]} {FOCAL[1]}")
    parts = [
        f'<rect x="{XL - STEM_W // 2}" y="{STEM_TOP}" width="{STEM_W}" height="{STEM_BOT - STEM_TOP}" rx="{STEM_RX}" fill="{fill}"/>',
        f'<rect x="{XR - STEM_W // 2}" y="{STEM_TOP}" width="{STEM_W}" height="{STEM_BOT - STEM_TOP}" rx="{STEM_RX}" fill="{fill}"/>',
        f'<path d="{d}" fill="none" stroke="{fill}" stroke-width="{STEM_W}"/>',
        f'<circle cx="{START_DOT[0]}" cy="{START_DOT[1]}" r="{START_R}" fill="{accent}"/>',
        f'<circle cx="{FOCAL[0]}" cy="{FOCAL[1]}" r="{FOCAL_R}" fill="{accent}"/>',
    ]
    if include_ring:
        for ang in ring_segments_deg():
            parts.append(
                f'<path d="{ring_arc_path(ang[0], ang[1])}" fill="none" stroke="{accent}" '
                f'stroke-width="{RING_W}" stroke-linecap="round"/>')
    return "\n  ".join(parts)


def ring_arc_path(start_deg, end_deg, radius=RING_R, cx=None, cy=None):
    cx = FOCAL[0] if cx is None else cx
    cy = FOCAL[1] if cy is None else cy
    # svgs and PIL both: angle degrees clockwise from +x, y grows downwards
    x1 = cx + radius * math.cos(math.radians(start_deg))
    y1 = cy + radius * math.sin(math.radians(start_deg))
    x2 = cx + radius * math.cos(math.radians(end_deg))
    y2 = cy + radius * math.sin(math.radians(end_deg))
    large = 1 if (end_deg - start_deg) % 360 > 180 else 0
    return f"M {x1:.2f} {y1:.2f} A {radius} {radius} 0 {large} 1 {x2:.2f} {y2:.2f}"


def ring_segments_deg():
    """[(start,end)] remaining arcs after carving the two gap wedges."""
    a, b = RING_GAPS
    a0, a1 = a[0] - a[1] / 2, a[0] + a[1] / 2     # entry gap span (268.75-314.25)
    b0, b1 = b[0] - b[1] / 2, b[0] + b[1] / 2     # exit gap span
    return [(a1, b0), (b1, a0 + 360)]


def svg_doc(body, cls=""):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" '
        f'role="img" aria-label="TMS NeuroPilot{cls}">\n  {body}\n</svg>\n'
    )


def write_svg(name, text):
    path = os.path.join(OUT, name)
    with open(path, "w") as f:
        f.write(text)
    print("svg  ", path)


def build_svgs():
    tile_dark = f'<rect width="512" height="512" rx="{TILE_RX}" fill="{TILE_DARK}"/>'
    tile_light = f'<rect width="512" height="512" rx="{TILE_RX}" fill="{TILE_LIGHT}"/>'
    write_svg("logo-dark.svg",
              svg_doc(tile_dark + "\n  " + svg_mark_body(INK_DARK, AMBER_DARK), " (dark)"))
    write_svg("logo-light.svg",
              svg_doc(tile_light + "\n  " + svg_mark_body(INK_LIGHT, AMBER_LIGHT), " (light)"))
    write_svg("logo-mono-on-light.svg",
              svg_doc(svg_mark_body(INK_LIGHT, INK_LIGHT)))
    write_svg("logo-mono-on-dark.svg",
              svg_doc(svg_mark_body(INK_DARK, INK_DARK)))
    write_svg("logo-mark-dark-bg.svg",
              svg_doc(svg_mark_body(INK_DARK, AMBER_DARK)))      # transparent bg


# favicon: 64-viewBox small variant (ringless, dots fat) ---------------------
def build_favicon():
    # scaled coordinates computed directly in 64 units
    k = 64 / 512
    # simplified marks tuned by hand rather than scaled script since no cairosvg
    body = (
        f'<rect width="64" height="64" rx="14" fill="{TILE_DARK}"/>\n'
        f'  <rect x="{21.1 - 5.5:.1f}" y="13" width="11" height="38" rx="1.5" fill="{INK_DARK}"/>\n'
        f'  <rect x="{42.0 - 5.5:.1f}" y="13" width="11" height="38" rx="1.5" fill="{INK_DARK}"/>\n'
        f'  <path d="M 21.1 18.5 L 28.1 18.5 C 39.4 18.5 26 39 44 49.8" '
        f'fill="none" stroke="{INK_DARK}" stroke-width="11"/>\n'
        f'  <circle cx="{21.1:.1f}" cy="{13 + 5.5:.1f}" r="4.5" fill="{AMBER_DARK}"/>\n'
        f'  <circle cx="{44.0:.1f}" cy="{49.8:.1f}" r="6.5" fill="{AMBER_DARK}"/>'
    )
    write_svg("favicon.svg",
              f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" '
              f'aria-label="TMS NeuroPilot">\n  {body}\n</svg>\n')


# ----------------------------------------------------------------- PIL ------
def pillow_mark(draw, s, ink, accent, include_ring=True, scale=1.0):
    """s = unit scale (render units -> pixels).  Same coordinates as SVG."""
    sw = max(1, round(STEM_W * s))
    st, sb = STEM_TOP * s, STEM_BOT * s
    for cx in (XL, XR):
        x0, x1 = (cx - STEM_W / 2) * s, (cx + STEM_W / 2) * s
        draw.rounded_rectangle([x0, st, x1, sb], radius=max(0, round(STEM_RX * s)), fill=ink)

    # diagonal: sampled cubic stroked as one closed ribbon (outer offsets
    # forward, inner offsets reversed), then joint disks for curvature
    # smoothing.  Avoids Pillow polyline artefacts (background slivers /
    # spike seams between quads).  Cap overlap artefacts stay invisible:
    # start is inside the cream left stem, end under the amber focal dot
    # (radius exceeds half the stroke width).
    hw = sw / 2
    pts = [(x * s, y * s) for x, y in mark_path_points()]
    outer = []
    for i in range(len(pts)):
        if i == 0:
            dx, dy = pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]
        else:
            dx, dy = pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]
        n_ = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / n_, dx / n_
        outer.append((pts[i][0] + nx * hw, pts[i][1] + ny * hw))
    inner = []
    for i in range(len(pts)):
        if i == 0:
            dx, dy = pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]
        else:
            dx, dy = pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]
        n_ = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / n_, dx / n_
        inner.append((pts[i][0] - nx * hw, pts[i][1] - ny * hw))
    draw.polygon(outer + inner[::-1], fill=ink)
    r = hw
    for x, y in pts[::16]:
        draw.ellipse([x - r, y - r, x + r, y + r], fill=ink)
    x, y = FOCAL[0] * s, FOCAL[1] * s
    r = FOCAL_R * s
    draw.ellipse([x - r, y - r, x + r, y + r], fill=accent)
    xs, ys = START_DOT[0] * s, START_DOT[1] * s
    rs = START_R * s
    draw.ellipse([xs - rs, ys - rs, xs + rs, ys + rs], fill=accent)
    if include_ring:
        rw = max(1, round(RING_W * s))
        rr = RING_R * s
        bbox = [x - rr, y - rr, x + rr, y + rr]
        for a0, a1 in ring_segments_deg():
            if a0 < a1:
                draw.arc(bbox, a0, a1, fill=accent, width=rw)
            else:  # wraps around 360 -> split
                draw.arc(bbox, a0, 360, fill=accent, width=rw)
                draw.arc(bbox, 0, a1, fill=accent, width=rw)


def rounded_tile_mask(size, rx):
    from PIL import Image, ImageDraw
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=round(rx), fill=255)
    return m


def render(size, mode="dark-tile", sup=4, optimize_small=False):
    """Raster one logo tile at `size` px. mode: dark-tile|light-tile|mono-light|mono-dark|transparent-dark"""
    from PIL import Image, ImageDraw
    S = size * sup
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    palettes = {
        "dark-tile": (TILE_DARK, INK_DARK, AMBER_DARK),
        "light-tile": (TILE_LIGHT, INK_LIGHT, AMBER_LIGHT),
        "mono-light": (None, INK_LIGHT, INK_LIGHT),
        "mono-dark": (None, INK_DARK, INK_DARK),
        "transparent-dark": (None, INK_DARK, AMBER_DARK),
        "dark-square": (TILE_DARK, INK_DARK, AMBER_DARK),   # full-bleed, no alpha
    }
    bg, ink, accent = palettes[mode]
    if bg:
        radius = 0 if mode == "dark-square" else round(TILE_RA * S)
        draw.rounded_rectangle([0, 0, S - 1, S - 1], radius=radius, fill=bg)
    s = S / CANVAS
    pillow_mark(draw, s, ink, accent, include_ring=not optimize_small)
    img = img.resize((size, size), Image.LANCZOS)
    if bg and mode != "dark-square":    # baked rounded-corner alpha for normal tiles
        mask = rounded_tile_mask(size, TILE_RA * size)
        r, g, b, _ = img.split()
        img = Image.merge("RGBA", (r, g, b, mask))
    return img


def build_rasters():
    jobs = [
        # (name, size, mode)
        ("neuropilot-logo-512-dark.png", 512, "dark-tile"),
        ("neuropilot-logo-256-dark.png", 256, "dark-tile"),
        ("neuropilot-logo-128-dark.png", 128, "dark-tile"),
        ("neuropilot-logo-64-dark.png", 64, "dark-tile"),
        ("neuropilot-logo-32-dark.png", 32, "dark-tile"),
        ("neuropilot-logo-24-dark.png", 24, "dark-tile"),
        ("neuropilot-logo-16-dark.png", 16, "dark-tile"),
        ("neuropilot-logo-256-light.png", 256, "light-tile"),
        ("neuropilot-mark-256-transparent-dark.png", 256, "transparent-dark"),
        ("neuropilot-mark-256-mono-light.png", 256, "mono-light"),
        ("neuropilot-mark-256-mono-dark.png", 256, "mono-dark"),
        ("gitlab-avatar-192.png", 192, "dark-square"),
        ("ICON16-unused.png", 16, "dark-tile"),
        ("ICON32-unused.png", 32, "dark-tile"),
    ]
    for name, size, mode in jobs:
        opt = size <= 24     # ringless simplified glyph for the tiny ramp
        img = render(size, mode, optimize_small=opt)
        path = os.path.join(OUT, name)
        img.save(path)
        print("png  ", path)

    # Windows .ico with the full ring at >=32, simplified below (PyQt will use PNG,
    # the .ico is spare for shortcuts/installers)
    from PIL import Image
    base = os.path.join(OUT, "icon256x.png")
    frames = [(s, render(s, "dark-tile", optimize_small=(s <= 24))) for s in (256, 128, 64, 48, 32, 24, 16)]
    frames[-1][1].save(
        os.path.join(OUT, "neuropilot.ico"),
        format="ICO", sizes=[(s, s) for s, _ in frames], append_images=[f for _, f in frames[1:]])
    print("ico  ", os.path.join(OUT, "neuropilot.ico"))


# ------------------------------------------------------------ spinner -------
def build_spinner(dark=True, frames=36, size=192):
    """Ring with entry gap rotating around the focal point; dot at centre;
    'locks' on the last frame (gap closes). Output GIF on the tile colour."""
    import math
    from PIL import Image, ImageDraw
    bg = TILE_DARK if dark else TILE_LIGHT
    ink = INK_DARK if dark else INK_LIGHT
    accent = AMBER_DARK if dark else AMBER_LIGHT
    out_name = f"spinner-dark.gif" if dark else f"spinner-light.gif"
    imgs = []
    sup = 4
    S = size * sup
    pad = 0.13
    s = S / CANVAS / 1.0
    rr = RING_R * 1.9 * s
    cx = cy = S / 2
    for i in range(frames):
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, S - 1, S - 1], radius=round(TILE_RA * S), fill=bg)
        # static faint inner cross ticks + waypoint dot hint
        t = (i + 1) / frames
        locked = t > 0.88
        gap = 6 if not locked else 30          # degrees: nearly closed at end
        a0 = 360 * t                            # rotating gap start
        if locked:
            # full ring on lock
            d.arc([cx - rr, cy - rr, cx + rr, cy + rr], 0, 360, fill=accent,
                  width=max(2, round(9 * sup / 2)))
        else:
            d.arc([cx - rr, cy - rr, cx + rr, cy + rr], a0 + gap / 2, a0 + 360 - gap / 2,
                  fill=accent, width=max(2, round(9 * sup / 2)))
        # center dot grows while locked
        dr = (16 + 10 * (t if locked else 0.0)) * sup / 2
        d.ellipse([cx - dr, cy - dr, cx + dr, cy + dr], fill=accent)
        r8, g8, b8 = _hex2rgb(bg)
        comp = Image.new("RGB", (S, S), (r8, g8, b8))
        comp.paste(img, (0, 0), img)
        frames_img = comp.resize((size, size), Image.LANCZOS)
        imgs.append(frames_img)
    out_path = os.path.join(OUT, out_name)
    imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=60, loop=0, optimize=True)
    print("gif  ", out_path)


def _hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def build_smil_spinner():
    """SVG spinner (SMIL) for docs — breaking ring rotates + gap closes at end not
    feasible purely in SMIL rotation; ships a simple rotating open ring + pulsing dot."""
    rx = 86
    dur = "1.2s"
    body = (
        f'<rect width="192" height="192" rx="42" fill="{TILE_DARK}"/>\n'
        f'  <g transform="translate(96 96)">\n'
        f'    <circle r="{rx}" fill="none" stroke="{AMBER_DARK}" stroke-width="9"'
        f'      stroke-dasharray="{2 * math.pi * rx * 0.86:.1f} {2 * math.pi * rx * 0.14:.1f}"'
        f'      stroke-linecap="round">\n'
        f'      <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="{dur}" repeatCount="indefinite"/>\n'
        f'    </circle>\n'
        f'    <circle r="13" fill="{AMBER_DARK}">\n'
        f'      <animate attributeName="r" values="10;14;10" dur="{dur}" repeatCount="indefinite"/>\n'
        f'    </circle>\n'
        f'  </g>'
    )
    write_svg("spinner-smil.svg",
              f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192" '
              f'role="img" aria-label="TMS NeuroPilot loading">\n  {body}\n</svg>\n')


if __name__ == "__main__":
    build_svgs()
    build_favicon()
    build_rasters()
    build_spinner(dark=True)
    build_spinner(dark=False)
    build_smil_spinner()
    print("done ->", OUT)
