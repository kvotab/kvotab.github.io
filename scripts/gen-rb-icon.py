#!/usr/bin/env python3
"""Emit rb.html's icon: resources/images/rb-icon.svg, and from it
rb-icon-32.png (the fallback) and rb-icon-180.png (the touch icon).

    python3 scripts/gen-rb-icon.py            # the SVG and both PNGs
    python3 scripts/gen-rb-icon.py --svg-only

The drawing is the H of the HDF Group's mark, its crossbar cut through the
middle as the mark's is, in the kvot mark's isometric language; the SVG's own
comment says why it looks the way it does. Edit the inputs below, never the
numbers in the SVG: they are this arithmetic rounded.

World coordinates as in gen-smui-icon.py: x runs toward the viewer's
right-front, u toward the right-back (on screen, right and up at 30 degrees),
z up. Each half of the H is its outline in (u, z), extruded over x in [0, d],
so its +x face is the letter and its top and left faces are strips along the
outline's edges: the lower half an upside-down U, the upper half a U above it,
the cut between them.

Nothing is scaled to fit. One world unit is one unit of the 64-unit square,
and the stems are sized and placed so that every upright edge falls on a pixel
boundary at 32 px and each stem's outer edges on one at 16 px as well; the
30-degree edges cannot be, and are left to antialiasing.

Nothing is written unless every edge is horizontal, vertical or at 30 degrees;
the drawing fits the square; the upright edges are on those pixel boundaries;
the cut and the notches are each at least a pixel at sixteen pixels; and every
face is drawn after the faces it hides. The PNGs are rasterised by headless
Chrome (CHROME overrides its path) and checked for being the drawing rather
than a broken-image glyph.
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
OUT = ROOT / 'resources/images/rb-icon.svg'
PNG32 = ROOT / 'resources/images/rb-icon-32.png'
PNG180 = ROOT / 'resources/images/rb-icon-180.png'
CHROME = os.environ.get('CHROME', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')

# The inputs, in units of the 64-unit square as they show on screen.
STEM = 6       # a stem across its right face: 1.5 px at 16 px, 3 px at 32
DEPTH = 6      # its left face across: as wide, so every bar is square in section, as the kvot mark's are
COUNTER = 3    # the space between the stems, in stems (the HDF mark's H has 3.5)
NOTCH = 1.5    # how far the stems run past the crossbar, in stems
CUT = 4.8      # the cut through the crossbar, measured up a stem; 4.16 across its 30-degree edges

SIZE = 64      # the viewBox
PIXEL = SIZE / 16
TOUCH_PLATE = '#352921'   # kompartment/icon-180.png's plate, as smui's and dose's
TOUCH_DRAWN = 136         # the 64-unit square drawn this many pixels wide on 180

S = math.cos(math.pi / 6)
TOP, RIGHT, LEFT = '#f3b87b', '#bb6c5d', '#344126'
D = DEPTH / S   # the extrusion, in world units


def proj(x, u, z):
    return ((x + u) * S, (x - u) / 2 - z)


def outlines():
    """The two halves, counter-clockwise in (u, z) with u right and z up."""
    s = STEM / S
    a1, b0, b1 = s, s * (1 + COUNTER), s * (2 + COUNTER)
    n, h = NOTCH * s, (NOTCH + 1) * s
    lower = [(0, 0), (a1, 0), (a1, n), (b0, n), (b0, 0), (b1, 0), (b1, h), (0, h)]
    z0 = h + CUT
    upper = [(0, z0), (b1, z0), (b1, z0 + h), (b0, z0 + h), (b0, z0 + s), (a1, z0 + s), (a1, z0 + h), (0, z0 + h)]
    return lower, upper


def faces(outline):
    """(tone, 3-D polygon) of one extruded half, the farthest first: the strips
    along its lit and shaded edges by depth, then the letter itself."""
    strips = []
    for i in range(len(outline)):
        (u1, z1), (u2, z2) = outline[i], outline[(i + 1) % len(outline)]
        if z1 == z2 and u2 < u1:      # outward normal +z: lit
            tone = TOP
        elif u1 == u2 and z2 < z1:    # outward normal -u: in shade
            tone = LEFT
        else:                         # facing away
            continue
        quad = [(D, u1, z1), (D, u2, z2), (0, u2, z2), (0, u1, z1)]
        # nearer to the viewer as x - u + z grows
        strips.append((D / 2 - (u1 + u2) / 2 + (z1 + z2) / 2, tone, quad))
    strips.sort(key=lambda s: s[0])
    return [(tone, quad) for _, tone, quad in strips] + [(RIGHT, [(D, u, z) for u, z in outline])]


def drawing():
    """The two halves, lower then upper, placed on the pixel grid: the left
    stem's shaded face starts on a whole pixel at 16 px, as near the middle of
    the square as that allows, and the drawing is centred top to bottom.
    Returns them with that left edge, as (tone, on screen, in the world)."""
    pieces = [faces(o) for o in outlines()]
    pts = [proj(*p) for piece in pieces for _, poly in piece for p in poly]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    ox = PIXEL * math.floor(((SIZE - w) / 2 - min(xs)) / PIXEL + 0.5)
    oy = (SIZE - h) / 2 - min(ys)

    def place(poly):
        return [(round(x + ox, 2), round(y + oy, 2)) for x, y in (proj(*p) for p in poly)]

    return [[(tone, place(poly), poly) for tone, poly in piece] for piece in pieces], ox


def area(poly):
    return sum(poly[i - 1][0] * poly[i][1] - poly[i][0] * poly[i - 1][1] for i in range(len(poly))) / 2


def clip(subject, clipper):
    """The part of `subject` inside `clipper`, which must be convex."""
    if area(clipper) < 0:
        clipper = clipper[::-1]
    out = subject
    for i in range(len(clipper)):
        (ax, ay), (bx, by) = clipper[i - 1], clipper[i]
        side = lambda p: (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)
        inp, out = out, []
        for j in range(len(inp)):
            p, q = inp[j - 1], inp[j]
            sp, sq = side(p), side(q)
            if (sp >= 0) != (sq >= 0):
                t = sp / (sp - sq)
                out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
            if sq >= 0:
                out.append(q)
        if not out:
            break
    return out


def nearness(quad, X, Y, screen):
    """x - u + z of the strip's plane where it shows at (X, Y) on screen."""
    (x0, y0), (x1, y1), (x3, y3) = screen[0], screen[1], screen[3]
    e1, e2 = (x1 - x0, y1 - y0), (x3 - x0, y3 - y0)
    det = e1[0] * e2[1] - e1[1] * e2[0]
    a = ((X - x0) * e2[1] - (Y - y0) * e2[0]) / det
    b = (e1[0] * (Y - y0) - e1[1] * (X - x0)) / det
    p = [quad[0][i] + a * (quad[1][i] - quad[0][i]) + b * (quad[3][i] - quad[0][i]) for i in range(3)]
    return p[0] - p[1] + p[2]


def seg_dist(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    t = 0 if n == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / n))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def apart(p, q):
    """The least distance between two polygons that do not overlap."""
    return min(min(seg_dist(v, b[i - 1], b[i]) for i in range(len(b))) for a, b in ((p, q), (q, p)) for v in a)


def check(pieces, ox):
    """The promises the comment in the SVG makes."""
    errors = []
    flat = [f for piece in pieces for f in piece]
    for _, poly, _ in flat:
        for i in range(len(poly)):
            (x1, y1), (x2, y2) = poly[i - 1], poly[i]
            a = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
            if min(abs(a - t) for t in (0, 30, 90, 150, 180)) > 0.5:
                errors.append(f'edge at {a:.1f} degrees: {poly[i - 1]} to {poly[i]}')
            if x1 == x2 and x1 % (PIXEL / 2):
                errors.append(f'an upright edge at x = {x1:g}, between two pixels at 32 px')
    pts = [p for _, poly, _ in flat for p in poly]
    if min(min(p) for p in pts) < 0 or max(max(p) for p in pts) > SIZE:
        errors.append('the drawing leaves the square')
    # Each stem's outer edges: the left of its shaded face, the right of its own.
    s = STEM / S
    for u in (0, s * (1 + COUNTER)):
        for x in (proj(0, u, 0)[0] + ox, proj(D, u + s, 0)[0] + ox):
            if round(x, 2) % PIXEL:
                errors.append(f'a stem edge at x = {x:.2f}, between two pixels at 16 px')
    # The cut, between the two halves' own faces; the notches, between one
    # stem's face and the next stem's shaded face.
    cut = apart(pieces[0][-1][1], pieces[1][-1][1])
    if cut < PIXEL:
        errors.append(f'the cut is {cut:.2f} across, under a pixel at 16 px ({PIXEL})')
    if COUNTER * STEM - DEPTH < PIXEL:
        errors.append(f'the notches are {COUNTER * STEM - DEPTH:g} open, under a pixel at 16 px ({PIXEL})')
    # Every face drawn after the faces it hides: where two overlap on screen,
    # the later one must be the nearer. The letter's own faces, in the right
    # tone, all lie in the nearest plane, so nothing may be drawn over them.
    for i in range(len(flat)):
        for j in range(i + 1, len(flat)):
            (ti, pi, qi), (tj, pj, qj) = flat[i], flat[j]
            if RIGHT in (ti, tj):
                if ti == RIGHT and tj != RIGHT and abs(area(clip(pi, pj))) > 1e-6:
                    errors.append(f'a {tj} strip is drawn over the letter')
                continue
            both = clip(pi, pj)
            if len(both) < 3 or abs(area(both)) < 1e-6:
                continue
            cx, cy = sum(p[0] for p in both) / len(both), sum(p[1] for p in both) / len(both)
            if nearness(qj, cx, cy, pj) < nearness(qi, cx, cy, pi):
                errors.append(f'a {tj} strip is drawn over a nearer {ti} one')
    return errors, cut


COMMENT = '''\t<!--
\t\tThe H of the HDF Group's mark, cut through its crossbar: the first
\t\tletter of the format whose files this page opens.

\t\tThe HDF Group draws H, D and F as one ligature of heavy strokes, with
\t\ta crossbar on the H as thick as two of them, and cuts the whole of it
\t\tthrough the middle, the upper half blue and the lower green. Here the
\t\tH alone keeps that cut: its upper half is a U over its lower half,
\t\tan upside-down U, and the cut runs between them through the middle
\t\tof the crossbar. It is redrawn, not copied: no blue or green, no D
\t\tor F, only the letter and the cut.

\t\tDRAWN IN THE KVOTAB MARK'S LANGUAGE, the same four rules as
\t\tkompartment/icon.svg and smui-icon.svg: true 30-degree isometric
\t\t(every edge horizontal, at +/-30 degrees or vertical); one flat tone
\t\tper face, #f3b87b on top, #bb6c5d on the right, #344126 on the left;
\t\tno strokes; no background plate.

\t\tEach half is its outline in one vertical plane, extruded towards the
\t\tviewer as far as a stem is wide, so every bar is square in section,
\t\tas the kvot mark's are. Through the cut the lower half's top shows in
\t\tthe lit tone, where the HDF mark shows white. The cut is just over a
\t\tpixel across at sixteen pixels, which keeps the halves apart in a
\t\tbrowser tab, and the stems stand on whole pixels: their outer edges at
\t\tsixteen pixels, every upright edge at thirty-two.

\t\tGenerated by scripts/gen-rb-icon.py, not typed: the stem, the depth,
\t\tthe counter, the notch and the cut, laid on the pixel grid and rounded
\t\tto two places. Change the inputs there and run it again rather than
\t\tediting the numbers here.
\t-->
'''


def svg(pieces):
    def polys(piece):
        return [f'\t<polygon fill="{f}" points="{" ".join(f"{x:g},{y:g}" for x, y in poly)}"/>' for f, poly, _ in piece]

    lower, upper = pieces
    return '\n'.join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" role="img">',
        '\t<title>HDF5 Browser</title>',
        COMMENT,
        '\t<!-- the lower half, an upside-down U -->', *polys(lower),
        '\n\t<!-- the upper half, a U above the cut -->', *polys(upper),
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
            if f == 1: line[i] = (line[i] + a) & 255
            elif f == 2: line[i] = (line[i] + b) & 255
            elif f == 3: line[i] = (line[i] + (a + b) // 2) & 255
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
    hexes = {TOP: (243, 184, 123), RIGHT: (187, 108, 93), LEFT: (52, 65, 38)}
    near = lambda p, q: all(abs(a - b) <= 6 for a, b in zip(p, q))
    for name, rgb in hexes.items():
        n = sum(1 for p in px if p[3] == 255 and near(p[:3], rgb))
        if n < 0.02 * w * h:
            return f'{png.name} hardly holds {name} ({n} pixels): not the drawing'
    return None


def main():
    pieces, ox = drawing()
    errors, cut = check(pieces, ox)
    if errors:
        sys.exit('not written:\n  ' + '\n  '.join(errors))
    text = svg(pieces)
    for comment in text.split('<!--')[1:]:
        if '--' in comment.split('-->')[0]:
            sys.exit('not written: a comment holds "--", which XML forbids (the browser would not decode the icon)')
    OUT.write_text(text)
    print(f'wrote {OUT.relative_to(ROOT)}: stems {STEM * 16 / SIZE:g} px across at 16 px, '
          f'the cut {cut * 16 / SIZE:.2f} px')
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
