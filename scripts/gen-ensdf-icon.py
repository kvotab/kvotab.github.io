#!/usr/bin/env python3
"""Emit ensdf.html's icon: resources/images/ensdf-icon.svg, and from it
ensdf-icon-32.png (the fallback) and ensdf-icon-180.png (the touch icon).

    python3 scripts/gen-ensdf-icon.py            # the SVG and both PNGs
    python3 scripts/gen-ensdf-icon.py --svg-only

The drawing is the radiation trefoil cut from the kvot cube; the SVG's own
comment says why it looks the way it does. Edit the inputs below, never the
numbers in the SVG: they are this arithmetic rounded.

World coordinates: x runs toward the viewer's right-front, u toward the
right-back (on screen, right and up at 30 degrees), z up; the viewer looks
along (-1, 1, -1). The trefoil is a cube of edge E whose near corner is the
origin, so its outline is the regular hexagon of radius E around that corner
and the three edges that meet there are the hexagon's radii at 30, 150 and
270 degrees; the face diagonals from the corner are the radii at 90, 210 and
330. Each blade is half a face, a plate of thickness T lying in it, cut short
of the corner: the left half of the top, the lower half of the left face and
the upper half of the right face. A plate shows its face and, as strips, the
two edges that face the viewer. The core is a small cube in the corner. Then
the whole drawing is scaled into the 64-unit square.

Nothing is written unless every edge is horizontal, vertical or at 30 degrees,
the drawing fits the square, and every gap is still at least a pixel at
sixteen pixels after scaling: below that a browser tab blurs the pieces into
one. Nor is it if a comment holds "--", which XML forbids: the browser would
drop the icon without a word. The PNGs are rasterised by headless Chrome
(CHROME overrides its path) and must show the drawing in all three tones.
"""
import math
import os
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'resources/images/ensdf-icon.svg'
PNG32 = ROOT / 'resources/images/ensdf-icon-32.png'
PNG180 = ROOT / 'resources/images/ensdf-icon-180.png'
CHROME = os.environ.get('CHROME', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')

# The inputs, in world units before scaling.
E = 30         # the cube the trefoil is cut from: the hexagon's radius on screen
CUT = 0.5      # the blades start this share of E out from the corner
T = 3.6        # the blades' thickness
CORE = 6.2     # the core cube's edge

SIZE = 64      # the viewBox
MARGIN = 0.5   # kept clear on the longer side
TOUCH_PLATE = '#352921'   # kompartment/icon-180.png's plate
TOUCH_DRAWN = 136         # the 64-unit square drawn this many pixels wide on 180

S = math.cos(math.pi / 6)
TOP, RIGHT, LEFT = '#f3b87b', '#bb6c5d', '#344126'


def proj(x, u, z):
    return ((x + u) * S, (x - u) / 2 - z)


def poly(*pts):
    return [proj(*p) for p in pts]


def box(x0, x1, u0, u1, z0, z1):
    return [
        (LEFT, poly((x0, u0, z1), (x1, u0, z1), (x1, u0, z0), (x0, u0, z0))),
        (RIGHT, poly((x1, u0, z1), (x1, u1, z1), (x1, u1, z0), (x1, u0, z0))),
        (TOP, poly((x0, u0, z1), (x0, u1, z1), (x1, u1, z1), (x1, u0, z1))),
    ]


def trefoil():
    """The blades, each its face and the two strips that face the viewer, and the core.
    Seen from the corner, a blade's face lies between a cube edge and a face diagonal;
    the plate's side along the diagonal is seen edge on, the side along the cube edge
    and the cut nearest the corner are not."""
    a, b, t = CUT * E, E, T
    top = [   # the left half of the top face: from the radius at 150 to the one at 90
        (TOP, poly((-a, 0, 0), (-b, 0, 0), (-b, b, 0), (-a, a, 0))),
        (LEFT, poly((-a, 0, 0), (-b, 0, 0), (-b, 0, -t), (-a, 0, -t))),
        (RIGHT, poly((-a, 0, 0), (-a, a, 0), (-a, a, -t), (-a, 0, -t))),
    ]
    right = [   # the upper half of the right face: from the radius at 30 to the one at 330
        (RIGHT, poly((0, a, 0), (0, b, 0), (0, b, -b), (0, a, -a))),
        (TOP, poly((0, a, 0), (0, b, 0), (-t, b, 0), (-t, a, 0))),
        (LEFT, poly((0, a, 0), (0, a, -a), (-t, a, -a), (-t, a, 0))),
    ]
    left = [   # the lower half of the left face: from the radius at 270 to the one at 210
        (LEFT, poly((0, 0, -a), (0, 0, -b), (-b, 0, -b), (-a, 0, -a))),
        (RIGHT, poly((0, 0, -a), (0, 0, -b), (0, t, -b), (0, t, -a))),
        (TOP, poly((0, 0, -a), (-a, 0, -a), (-a, t, -a), (0, t, -a))),
    ]
    core = box(-CORE, 0, 0, CORE, -CORE, 0)
    return [top, right, left, core]


def seg_dist(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    t = 0 if n == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / n))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def inside(p, polygon):
    x, y = p
    c = False
    for i in range(len(polygon)):
        (x1, y1), (x2, y2) = polygon[i], polygon[i - 1]
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


def drawing():
    pieces = trefoil()
    pts = [p for piece in pieces for _, polygon in piece for p in polygon]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    k = (SIZE - 2 * MARGIN) / max(w, h)
    ox, oy = (SIZE - w * k) / 2 - min(xs) * k, (SIZE - h * k) / 2 - min(ys) * k
    return [[(f, [(round(x * k + ox, 2), round(y * k + oy, 2)) for x, y in polygon]) for f, polygon in piece]
            for piece in pieces]


def check(pieces):
    """The three promises the comment in the SVG makes."""
    errors = []
    for piece in pieces:
        for _, polygon in piece:
            for i in range(len(polygon)):
                (x1, y1), (x2, y2) = polygon[i - 1], polygon[i]
                a = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
                if min(abs(a - t) for t in (0, 30, 90, 150, 180)) > 0.5:
                    errors.append(f'edge at {a:.1f} degrees: {polygon[i - 1]} to {polygon[i]}')
    pts = [p for piece in pieces for _, polygon in piece for p in polygon]
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
\t\tThe radiation trefoil, cut from a cube.

\t\tDRAWN IN THE KVOTAB MARK'S LANGUAGE, the same four rules as
\t\tkompartment/icon.svg: true 30-degree isometric (every edge
\t\thorizontal, at +/-30 degrees or vertical); one flat tone per face,
\t\t#f3b87b on top, #bb6c5d on the right, #344126 on the left; no
\t\tstrokes; no background plate.

\t\tThe first rule decides the trefoil. A cube seen corner on is a
\t\thexagon cut into six 60-degree triangles by the three edges and the
\t\tthree face diagonals that meet at the corner, and every one of those
\t\tlines is an allowed one; three alternate triangles are a trefoil,
\t\tone blade on each face, so each takes that face's tone. The usual
\t\tsign has its blades' sides at 0, 60 and 120 degrees, which the rule
\t\tdoes not allow, so this one is the sign turned by 30 degrees.

\t\tThe blades are plates rather than paper: each shows its two edges
\t\tthat face the viewer in the other two tones, which keeps every blade
\t\tin sight on a light tab and on a dark one. The core is a small cube
\t\tin the corner they were cut from. Every gap between the pieces is
\t\tmore than a pixel at sixteen pixels, which is what keeps the four
\t\tapart in a browser tab.

\t\tGenerated by scripts/gen-ensdf-icon.py, not typed: the cube, the
\t\tcut, the plates' thickness and the core, scaled into the square and
\t\trounded to two places. Change the inputs there and run it again
\t\trather than editing the numbers here.
\t-->
'''


def svg(pieces):
    top, right, left, core = pieces

    def polys(piece):
        return [f'\t<polygon fill="{f}" points="{" ".join(f"{x:g},{y:g}" for x, y in polygon)}"/>'
                for f, polygon in piece]

    return '\n'.join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" role="img">',
        '\t<title>Chart of Nuclides (ENSDF)</title>',
        COMMENT,
        '\t<!-- the blades: half the top, half the right face, half the left face -->',
        *polys(top), *polys(right), *polys(left),
        '\n\t<!-- the core, in the corner they were cut from -->', *polys(core),
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


def pixels(png):
    """(width, height, [(r, g, b, a)]) of an 8-bit RGBA or RGB PNG, by hand,
    so that the check below needs nothing beyond the standard library."""
    data = png.read_bytes()
    pos, chunks = 8, {}
    while pos < len(data):
        n = int.from_bytes(data[pos:pos + 4], 'big')
        kind = data[pos + 4:pos + 8]
        chunks.setdefault(kind, b'')
        chunks[kind] += data[pos + 8:pos + 8 + n]
        pos += 12 + n
    w, h = int.from_bytes(chunks[b'IHDR'][0:4], 'big'), int.from_bytes(chunks[b'IHDR'][4:8], 'big')
    depth, ctype = chunks[b'IHDR'][8], chunks[b'IHDR'][9]
    if depth != 8 or ctype not in (2, 6):
        return w, h, None
    bpp = 4 if ctype == 6 else 3
    raw, stride, out, prev = zlib.decompress(chunks[b'IDAT']), w * bpp, [], bytearray(w * bpp)
    for y in range(h):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += [tuple(line[i:i + bpp]) + ((255,) if bpp == 3 else ()) for i in range(0, stride, bpp)]
        prev = line
    return w, h, out


def looks_drawn(png, size):
    """The picture is the drawing: the right size, and each of the three tones
    is there, over the plate or the transparency, in a fair share of it."""
    w, h, px = pixels(png)
    if (w, h) != (size, size) or px is None:
        return f'{png.name} is {w}x{h}, not an {size}x{size} RGB(A) picture'
    for tone in (TOP, RIGHT, LEFT):
        rgb = tuple(int(tone[i:i + 2], 16) for i in (1, 3, 5))
        n = sum(1 for p in px if p[3] == 255 and all(abs(a - b) <= 6 for a, b in zip(p[:3], rgb)))
        if n < 0.02 * w * h:
            return f'{png.name} hardly holds {tone} ({n} pixels): not the drawing'
    return None


def main():
    pieces = drawing()
    errors = check(pieces)
    if errors:
        sys.exit('not written:\n  ' + '\n  '.join(errors))
    text = svg(pieces)
    for comment in text.split('<!--')[1:]:
        if '--' in comment.split('-->')[0]:
            sys.exit('not written: a comment holds "--", which XML forbids (the browser would not decode the icon)')
    OUT.write_text(text)
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
    for png, size in ((PNG32, 32), (PNG180, 180)):
        bad = looks_drawn(png, size)
        if bad:
            sys.exit(bad)
    print(f'wrote {PNG32.relative_to(ROOT)} and {PNG180.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
