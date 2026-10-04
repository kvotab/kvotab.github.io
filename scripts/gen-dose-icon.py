#!/usr/bin/env python3
"""Emit dose_coefficients.html's icon: resources/images/dose-icon.svg, and from it
dose-icon-32.png (the fallback) and dose-icon-180.png (the touch icon).

    python3 scripts/gen-dose-icon.py            # the SVG and both PNGs
    python3 scripts/gen-dose-icon.py --svg-only

The drawing is the four letters of the ICRP's logotype standing in a row, in
the kvot mark's isometric language; the SVG's own comment says why it looks the
way it does. Edit the inputs below, never the numbers in the SVG: they are this
arithmetic rounded.

World coordinates as in gen-smui-icon.py: x runs toward the viewer's
right-front, u toward the right-back (on screen, right and up at 30 degrees),
z up. Each letter is an outline in (u, z), extruded over x in [0, DEPTH], so its
+x face is the letter and its top and left faces are strips along the outline's
edges. The letters stand in a row along u, so the word rises at 30 degrees, and
they are drawn from the farthest (the P) to the nearest (the I), each one's
strips before its face. Every gap between letters and every slit is CUT pixels
across at sixteen pixels; the scale that the drawing fills the square with
depends on them, so the two are solved for together.

Nothing is written unless every edge is horizontal, vertical or at 30 degrees,
the drawing fits the square, every gap and slit is still at least a pixel at
sixteen pixels after scaling, and each slit is floored, and each gap filled, by
a face of the letter behind it (the promises the comment in the SVG makes). The
PNGs are rasterised by headless Chrome (CHROME overrides its path) and checked
for being the drawing rather than a broken-image glyph.
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
OUT = ROOT / 'resources/images/dose-icon.svg'
PNG32 = ROOT / 'resources/images/dose-icon-32.png'
PNG180 = ROOT / 'resources/images/dose-icon-180.png'
CHROME = os.environ.get('CHROME', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')

# The logotype's letters, measured on the header image of icrp.org (the letters
# 99 pixels high), as shares of their height: the widths, and the slits.
WIDTH = {'I': 37 / 99, 'C': 90 / 99, 'R': 79 / 99, 'P': 78 / 99}
C_MOUTH = (0.515, 0.51)   # the C's slit from its right edge: its middle's height, its length as a share of the C's width
HIGH = 0.68               # the middle of the slit from the left edge of the R and of the P
R_HIGH = 0.42             # its length in the R, as a share of the R's width (in the P it runs across the stem)
R_LEG = (0.405, 0.283)    # the R's slit from below, between stem and leg: where it starts across the R, how high it reaches
P_STEM = 0.436            # the P's stem, as a share of its width
P_BOWL = 0.384            # the underside of the P's bowl, as a share of the height

# The inputs of the drawing, as shares of the letters' height.
NARROW = 0.62   # the letters' widths, so that the rising word fills the square
DEPTH = 0.40    # how far each letter stands out toward the viewer
CUT = 1.0       # every gap and slit, in pixels across at sixteen pixels

SIZE = 64      # the viewBox
MARGIN = 0.5   # kept clear on the longer side
PIXEL = SIZE / 16
TOUCH_PLATE = '#352921'   # kompartment/icon-180.png's plate, as smui's
TOUCH_DRAWN = 136         # the 64-unit square drawn this many pixels wide on 180

S = math.cos(math.pi / 6)
TOP, RIGHT, LEFT = '#f3b87b', '#bb6c5d', '#344126'


def proj(x, u, z):
    return ((x + u) * S, (x - u) / 2 - z)


def outlines(cut):
    """The four letters, counter-clockwise in (u, z) with u right and z up,
    standing in a row along u with `cut` between them; `cut` is also every
    slit's width."""
    w = {c: WIDTH[c] * NARROW for c in WIDTH}
    t = cut / 2
    m, ml = C_MOUTH[0], C_MOUTH[1] * w['C']
    rl, (ra, rh) = R_HIGH * w['R'], (R_LEG[0] * w['R'], R_LEG[1])
    ps = P_STEM * w['P']
    shapes = {
        'I': [(0, 0), (w['I'], 0), (w['I'], 1), (0, 1)],
        # a block whose mouth is a slit from its right edge
        'C': [(0, 0), (w['C'], 0), (w['C'], m - t), (w['C'] - ml, m - t), (w['C'] - ml, m + t), (w['C'], m + t),
              (w['C'], 1), (0, 1)],
        # a slit from the left edge, high up, and one from below between stem and leg
        'R': [(0, 0), (ra, 0), (ra, rh), (ra + cut, rh), (ra + cut, 0), (w['R'], 0), (w['R'], 1), (0, 1),
              (0, HIGH + t), (rl, HIGH + t), (rl, HIGH - t), (0, HIGH - t)],
        # the same high slit, across the stem, and open below the bowl
        'P': [(0, 0), (ps, 0), (ps, P_BOWL), (w['P'], P_BOWL), (w['P'], 1), (0, 1),
              (0, HIGH + t), (ps, HIGH + t), (ps, HIGH - t), (0, HIGH - t)],
    }
    out, u = [], 0.0
    for c in 'ICRP':
        out.append((c, [(u + a, z) for a, z in shapes[c]]))
        u += w[c] + cut
    return out


def faces(outline):
    """(tone, polygon) of one extruded letter, the farthest first: the strips
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
        poly = [proj(DEPTH, u1, z1), proj(DEPTH, u2, z2), proj(0, u2, z2), proj(0, u1, z1)]
        # nearer to the viewer as x - u + z grows
        strips.append((DEPTH / 2 - (u1 + u2) / 2 + (z1 + z2) / 2, tone, poly))
    strips.sort(key=lambda s: s[0])
    return [(tone, poly) for _, tone, poly in strips] + [(RIGHT, [proj(DEPTH, u, z) for u, z in outline])]


def layout(cut):
    letters = outlines(cut)
    pieces = [(c, faces(o)) for c, o in reversed(letters)]
    pts = [p for _, piece in pieces for _, poly in piece for p in poly]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    k = (SIZE - 2 * MARGIN) / max(w, h)
    return pieces, k, (min(xs), min(ys), w, h)


def drawing():
    """Solve for the cut that is CUT pixels across once the drawing is scaled
    into the square: the gaps show as their width times cos 30, and so do the
    slits, which run at 30 degrees."""
    cut = 0.1
    for _ in range(60):
        _, k, _ = layout(cut)
        cut = CUT * PIXEL / (k * S)
    pieces, k, (x0, y0, w, h) = layout(cut)
    ox, oy = (SIZE - w * k) / 2 - x0 * k, (SIZE - h * k) / 2 - y0 * k
    scaled = [(c, [(f, [(round(x * k + ox, 2), round(y * k + oy, 2)) for x, y in poly]) for f, poly in piece])
              for c, piece in pieces]
    return scaled, k, cut


def check(pieces, k, cut):
    """The promises the comment in the SVG makes."""
    errors = []
    for _, piece in pieces:
        for _, poly in piece:
            for i in range(len(poly)):
                (x1, y1), (x2, y2) = poly[i - 1], poly[i]
                a = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
                if min(abs(a - t) for t in (0, 30, 90, 150, 180)) > 0.5:
                    errors.append(f'edge at {a:.1f} degrees: {poly[i - 1]} to {poly[i]}')
    pts = [p for _, piece in pieces for _, poly in piece for p in poly]
    if min(min(p) for p in pts) < 0 or max(max(p) for p in pts) > SIZE:
        errors.append('the drawing leaves the square')
    # Each gap, measured on the rounded faces: the space between one letter's
    # face and the next one's, across.
    front = {c: piece[-1][1] for c, piece in pieces}   # each letter's own face is drawn last
    for a, b in zip('ICR', 'CRP'):
        g = min(x for x, _ in front[b]) - max(x for x, _ in front[a])
        if g < PIXEL - 0.05:
            errors.append(f'the gap between {a} and {b} is {g:.2f} across, under a pixel at 16 px ({PIXEL})')
    if cut * k * S < PIXEL - 0.05:
        errors.append(f'the slits are {cut * k * S:.2f} across, under a pixel at 16 px')
    # A slit cut from the side shows its floor, in the lit tone, only if the
    # floor reaches across the opening; a gap shows the next letter's shaded
    # side only if that side is at least as deep as the gap is wide.
    if DEPTH / 2 < cut:
        errors.append('the slits are wider than their floors can fill: the background would show through')
    if DEPTH < cut:
        errors.append('the gaps are wider than the letters are deep')
    return errors


COMMENT = '''\t<!--
\t\tThe four letters of the ICRP's logotype, standing in a row: the
\t\tcommission whose models this page calculates with.

\t\tThe logotype is four heavy letters whose counters are cut down to
\t\thairline slits: a plain bar for the I, a C whose mouth is one slit from
\t\tits right edge, and an R and a P each cut by a slit from the left, high
\t\tup; a slit from below parts the R's leg from its stem, and the P is
\t\topen under its bowl. Here the letters keep those widths and those cuts,
\t\tmeasured on the logotype, and nothing else of it: no blue, no round
\t\tbowls, and every cut as wide as a browser tab needs. It is redrawn,
\t\tnot copied.

\t\tDRAWN IN THE KVOTAB MARK'S LANGUAGE, the same four rules as
\t\tkompartment/icon.svg and smui-icon.svg: true 30-degree isometric
\t\t(every edge horizontal, at +/-30 degrees or vertical, so the bowls are
\t\tsquare); one flat tone per face, #f3b87b on top, #bb6c5d on the right,
\t\t#344126 on the left; no strokes; no background plate.

\t\tEach letter is its outline in one vertical plane, extruded towards the
\t\tviewer, so the right faces spell the word and the tops are lit. A slit
\t\tcut from the side shows its floor in the lit tone, as the logotype's
\t\tslits are white; each gap between letters, and the R's slit from
\t\tbelow, shows the shaded side of the letter behind it. The letters are
\t\tnarrowed to %(narrow)d per cent so that the word, rising at 30 degrees,
\t\tfills the square, and every gap and slit is a pixel wide at sixteen
\t\tpixels, which is what keeps the four letters apart in a browser tab.

\t\tGenerated by scripts/gen-dose-icon.py, not typed: the letters'
\t\tmeasured widths and cuts, the narrowing, the depth and that one pixel,
\t\tscaled into the square and rounded to two places. Change the inputs
\t\tthere and run it again rather than editing the numbers here.
\t-->
'''


def svg(pieces):
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" role="img">',
             '\t<title>Dose Coefficients</title>', COMMENT % {'narrow': round(NARROW * 100)}]
    say = {'P': 'the P, farthest', 'R': 'the R', 'C': 'the C', 'I': 'the I, nearest'}
    for c, piece in pieces:
        lines.append(f'\t<!-- {say[c]} -->')
        lines += [f'\t<polygon fill="{f}" points="{" ".join(f"{x:g},{y:g}" for x, y in poly)}"/>' for f, poly in piece]
    lines.append('</svg>\n')
    return '\n'.join(lines)


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


def looks_drawn(png, size, plate=None):
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
    pieces, k, cut = drawing()
    errors = check(pieces, k, cut)
    if errors:
        sys.exit('not written:\n  ' + '\n  '.join(errors))
    text = svg(pieces)
    for comment in text.split('<!--')[1:]:
        if '--' in comment.split('-->')[0]:
            sys.exit('not written: a comment holds "--", which XML forbids (the browser would not decode the icon)')
    OUT.write_text(text)
    print(f'wrote {OUT.relative_to(ROOT)}: the letters {k:.2f} units high ({k * 16 / SIZE:.2f} px at 16 px), '
          f'gaps and slits {cut * k * S * 16 / SIZE:.2f} px across at 16 px')
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
