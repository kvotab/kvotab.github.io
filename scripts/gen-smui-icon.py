#!/usr/bin/env python3
"""Emit smui.html's icon: resources/images/smui-icon.svg, and from it
smui-icon-32.png (the fallback) and smui-icon-180.png (the touch icon).

    python3 scripts/gen-smui-icon.py            # the SVG and both PNGs
    python3 scripts/gen-smui-icon.py --svg-only

The drawing is statsmodels' fitted curve with a point on each side and a dot
over the curve's upper end (JMP's dotted j), in the kvot mark's isometric
language; the SVG's own comment says why it looks the way it does. Edit the
inputs below, never the numbers in the SVG: they are this arithmetic rounded.

World coordinates: x runs toward the viewer's right-front, u toward the
right-back (on screen, right and up at 30 degrees), z up. The bar is a profile
in (u, z), extruded over x in [0, D], so its +x face is the profile itself and
its top and left faces are strips along the profile's edges. The cubes sit on
the slab's middle plane. Each data point is lowered (or raised) onto the bar
until it is GAP clear on screen, and the dot is lowered onto the stem the same
way, so the pieces are placed by that gap rather than by eye; then the whole
drawing is scaled into the 64-unit square.

Nothing is written unless every edge is horizontal, vertical or at 30 degrees,
the drawing fits the square, and every gap is still at least a pixel at
sixteen pixels after scaling: below that a browser tab blurs the pieces into
one. The PNGs are rasterised by headless Chrome (CHROME overrides its path).
"""
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'resources/images/smui-icon.svg'
PNG32 = ROOT / 'resources/images/smui-icon-32.png'
PNG180 = ROOT / 'resources/images/smui-icon-180.png'
CHROME = os.environ.get('CHROME', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')

# The inputs, in world units before scaling.
W = 6          # the bar's thickness in its own plane
D = 5          # its depth toward the viewer: thinner than a cube, like statsmodels' curve
LB = 30        # how far the bar runs across, along u
EA = 8         # how far the lower end drops below the run
EB = 8         # how far the upper end (the stem) rises above it
CUBE = 11      # the data points' edge
DOT = 10       # the dot's edge
GAP = 4.6      # the screen gap between pieces, before scaling
UPPER_X = -1   # screen x of the point above the curve, from the bar's left
LOWER_X = 33   # screen x of the point below it

SIZE = 64      # the viewBox
MARGIN = 0.5   # kept clear on the longer side
TOUCH_PLATE = '#352921'   # kompartment/icon-180.png's plate
TOUCH_DRAWN = 136         # the 64-unit square drawn this many pixels wide on 180

S = math.cos(math.pi / 6)
TOP, RIGHT, LEFT = '#f3b87b', '#bb6c5d', '#344126'


def proj(x, u, z):
    return ((x + u) * S, (x - u) / 2 - z)


def bar_faces(profile, d):
    """profile: counter-clockwise polygon in (u, z), u right and z up."""
    faces = [(RIGHT, [proj(d, u, z) for u, z in profile])]
    for i in range(len(profile)):
        (u1, z1), (u2, z2) = profile[i], profile[(i + 1) % len(profile)]
        strip = [proj(d, u1, z1), proj(d, u2, z2), proj(0, u2, z2), proj(0, u1, z1)]
        if z1 == z2 and u2 < u1:      # outward normal +z: the lit top
            faces.append((TOP, strip))
        elif u1 == u2 and z2 < z1:    # outward normal -u: the left face
            faces.append((LEFT, strip))
    return faces


def cube_faces(xc, uc, zc, c):
    h = c / 2
    x0, x1, u0, u1, z0, z1 = xc - h, xc + h, uc - h, uc + h, zc - h, zc + h
    return [
        (LEFT, [proj(x0, u0, z1), proj(x1, u0, z1), proj(x1, u0, z0), proj(x0, u0, z0)]),
        (RIGHT, [proj(x1, u0, z1), proj(x1, u1, z1), proj(x1, u1, z0), proj(x1, u0, z0)]),
        (TOP, [proj(x0, u0, z1), proj(x0, u1, z1), proj(x1, u1, z1), proj(x1, u0, z1)]),
    ]


def cube_on_screen(X, Y, c):
    """A cube on the slab's middle plane whose centre lands at screen (X, Y)."""
    xm = D / 2
    u = X / S - xm
    return cube_faces(xm, u, (xm - u) / 2 - Y, c)


def profile():
    """Up, across and up again: the lower end, the run, the stem."""
    zb, za = EA, EA + W
    zt = za + EB
    return [(0, 0), (W, 0), (W, zb), (LB, zb), (LB, zt), (LB - W, zt), (LB - W, za), (0, za)], zt


def seg_dist(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    t = 0 if n == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / n))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def inside(p, poly):
    x, y = p
    c = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def gap(a, b):
    """Screen distance between two pieces' faces; -1 if they overlap."""
    best = math.inf
    for _, p1 in a:
        for _, p2 in b:
            for p, q in ((p1, p2), (p2, p1)):
                for v in p:
                    if inside(v, q):
                        return -1
                    best = min(best, min(seg_dist(v, q[i], q[i - 1]) for i in range(len(q))))
    return best


def settle(make, other, lo, hi):
    """Bisect t in [lo, hi], where a larger t moves make(t) toward `other`,
    to the last t at which it is still GAP clear."""
    for _ in range(60):
        mid = (lo + hi) / 2
        if gap(make(mid), other) >= GAP:
            lo = mid
        else:
            hi = mid
    return make(lo)


def drawing():
    prof, zt = profile()
    bar = bar_faces(prof, D)
    upper = settle(lambda Y: cube_on_screen(UPPER_X, Y, CUBE), bar, -200, 50)
    lower = settle(lambda Y: cube_on_screen(LOWER_X, -Y, CUBE), bar, -200, 50)
    dot = settle(lambda t: cube_faces(D / 2, LB - W / 2, zt + DOT / 2 + 200 - t, DOT), bar, 0, 200)
    pieces = [upper, lower, bar, dot]
    pts = [p for piece in pieces for _, poly in piece for p in poly]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    k = (SIZE - 2 * MARGIN) / max(w, h)
    ox, oy = (SIZE - w * k) / 2 - min(xs) * k, (SIZE - h * k) / 2 - min(ys) * k
    return [[(f, [(round(x * k + ox, 2), round(y * k + oy, 2)) for x, y in poly]) for f, poly in piece]
            for piece in pieces]


def check(pieces):
    """The three promises the comment in the SVG makes."""
    errors = []
    for piece in pieces:
        for _, poly in piece:
            for i in range(len(poly)):
                (x1, y1), (x2, y2) = poly[i - 1], poly[i]
                a = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
                if min(abs(a - t) for t in (0, 30, 90, 150, 180)) > 0.5:
                    errors.append(f'edge at {a:.1f} degrees: {poly[i - 1]} to {poly[i]}')
    pts = [p for piece in pieces for _, poly in piece for p in poly]
    if min(min(p) for p in pts) < 0 or max(max(p) for p in pts) > SIZE:
        errors.append('the drawing leaves the square')
    pixel = SIZE / 16
    for i in range(len(pieces)):
        for j in range(i + 1, len(pieces)):
            g = gap(pieces[i], pieces[j])
            if g < pixel:
                errors.append(f'pieces {i} and {j} are {g:.2f} apart, under a pixel at 16 px ({pixel})')
    return errors


COMMENT = '''\t<!--
\t\tA fitted curve with a data point on each side, and a dot over the top
\t\tof the curve: statsmodels' mark and JMP's, met halfway.

\t\tstatsmodels draws a curve that climbs, runs across and climbs again,
\t\twith its points on either side of it. JMP's wordmark is a lowercase
\t\tj whose dot is a figure. Here the curve's upper end is a stem, and a
\t\tcube set straight above it makes that end a dotted j, so the one bar
\t\tis both the fit and the letter. Neither mark is copied: no blue, no
\t\tfigure, no round dots, only the arrangement.

\t\tDRAWN IN THE KVOTAB MARK'S LANGUAGE, the same four rules as
\t\tkompartment/icon.svg: true 30-degree isometric (every edge
\t\thorizontal, at +/-30 degrees or vertical, so the curve is a bar with
\t\tcorners); one flat tone per face, #f3b87b on top, #bb6c5d on the
\t\tright, #344126 on the left; no strokes; no background plate.

\t\tThe bar is a profile in one vertical plane, extruded towards the
\t\tviewer, so its right face is the whole curve and the top and left
\t\tfaces are thin strips. It is thinner than the cubes, as statsmodels'
\t\tcurve is thinner than its dots. Every gap between pieces is just over
\t\ta pixel at sixteen pixels, which is what keeps the four apart in a
\t\tbrowser tab; the cubes are placed by that gap rather than by eye.

\t\tGenerated by scripts/gen-smui-icon.py, not typed: the bar's profile,
\t\tthree cubes and that one gap, scaled into the square and rounded to
\t\ttwo places. Change the inputs there and run it again rather than
\t\tediting the numbers here.
\t-->
'''


def svg(pieces):
    upper, lower, bar, dot = pieces

    def polys(piece):
        return [f'\t<polygon fill="{f}" points="{" ".join(f"{x:g},{y:g}" for x, y in poly)}"/>'
                for f, poly in piece]

    return '\n'.join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" role="img">',
        '\t<title>User Interface for statsmodels</title>',
        COMMENT,
        '\t<!-- the points, one on each side of the fit -->', *polys(upper), *polys(lower),
        '\n\t<!-- the fit: up, across and up again -->', *polys(bar),
        '\n\t<!-- the dot over its upper end -->', *polys(dot),
        '</svg>\n',
    ])


def rasterise(page, png, width, height):
    """Headless Chrome writes the screenshot and then never exits on its own,
    so wait for the file and stop that one process."""
    with tempfile.TemporaryDirectory() as tmp:
        html = Path(tmp) / 'icon.html'
        html.write_text(page)
        shot = Path(tmp) / 'shot.png'
        proc = subprocess.Popen([
            CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars',
            '--force-device-scale-factor=1', '--default-background-color=00000000',
            f'--user-data-dir={tmp}/profile', f'--window-size={width},{height}',
            f'--screenshot={shot}', html.as_uri(),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(300):
                time.sleep(0.1)
                if shot.exists() and shot.stat().st_size > 0:
                    time.sleep(0.3)
                    break
            else:
                sys.exit(f'Chrome wrote no screenshot for {png.name}')
        finally:
            proc.kill()
            proc.wait()
        png.write_bytes(shot.read_bytes())


def main():
    pieces = drawing()
    errors = check(pieces)
    if errors:
        sys.exit('not written:\n  ' + '\n  '.join(errors))
    OUT.write_text(svg(pieces))
    print(f'wrote {OUT.relative_to(ROOT)}')
    if '--svg-only' in sys.argv[1:]:
        return
    if not Path(CHROME).exists():
        sys.exit(f'no Chrome at {CHROME} (set CHROME, or pass --svg-only); the PNGs were not redrawn')
    src = OUT.as_uri()
    rasterise('<!doctype html><body style="margin:0;background:transparent">'
              f'<img src="{src}" width="32" height="32" style="display:block">', PNG32, 32, 32)
    pad = (180 - TOUCH_DRAWN) // 2
    rasterise(f'<!doctype html><body style="margin:0;background:{TOUCH_PLATE}">'
              f'<img src="{src}" width="{TOUCH_DRAWN}" height="{TOUCH_DRAWN}" '
              f'style="display:block;margin:{pad}px">', PNG180, 180, 180)
    print(f'wrote {PNG32.relative_to(ROOT)} and {PNG180.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
