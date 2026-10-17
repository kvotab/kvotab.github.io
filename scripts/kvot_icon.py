"""Shared by the page-icon generators that build their drawing from blocks:
gen-flashcards-icon.py, gen-winnetkakort-icon.py, gen-sl-icon.py and
gen-gitarr-icon.py (gen-kvot-touch-icon.py uses only its rasteriser).

The kvot mark's language, as kompartment/icon.svg sets it out: true 30-degree
isometric, every edge horizontal, at 30 degrees or upright; one flat tone per
face, #f3b87b on top, #bb6c5d on the right, #344126 on the left; no strokes;
no plate. A face can only take one of those tones if it faces one of the
three axes, so every shape here is rectilinear: boxes, and outlines whose
edges run along the axes, extruded.

World coordinates as in gen-rb-icon.py: x runs toward the viewer's
right-front, u toward the right-back (on screen, right and up at 30 degrees),
z up. A shape is a list of (tone, 3-D polygon) faces in the order it draws
them; order() puts several shapes in an order where the nearer face comes
later wherever two overlap, and problems() checks that it does.
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
CHROME = os.environ.get('CHROME', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')

SIZE = 64                  # the viewBox
FIT = 58                   # the drawing scaled to this, across or down, whichever is the longer
TOUCH_PLATE = '#352921'    # kompartment/icon-180.png's plate, as the other pages'
TOUCH_DRAWN = 136          # the 64-unit square drawn this many pixels wide on 180

S = math.cos(math.pi / 6)
TOP, RIGHT, LEFT = '#f3b87b', '#bb6c5d', '#344126'


def proj(x, u, z):
    return ((x + u) * S, (x - u) / 2 - z)


def box(x0, x1, u0, u1, z0, z1):
    """A box's three faces that show: the shaded -u face, the +x face and the lit top."""
    return [
        (LEFT, [(x0, u0, z0), (x1, u0, z0), (x1, u0, z1), (x0, u0, z1)]),
        (RIGHT, [(x1, u0, z0), (x1, u1, z0), (x1, u1, z1), (x1, u0, z1)]),
        (TOP, [(x0, u0, z1), (x1, u0, z1), (x1, u1, z1), (x0, u1, z1)]),
    ]


def _ccw(outline):
    a = sum(outline[i - 1][0] * outline[i][1] - outline[i][0] * outline[i - 1][1] for i in range(len(outline)))
    return outline if a > 0 else outline[::-1]


def upright(outline, x0, x1):
    """A rectilinear outline in (u, z), extruded over x in [x0, x1]: its +x face
    is the outline in the right-hand tone, with strips along its lit (+z) and
    shaded (-u) edges, the farthest first and the outline face last."""
    o = _ccw(outline)
    strips = []
    for i in range(len(o)):
        (u1, z1), (u2, z2) = o[i], o[(i + 1) % len(o)]
        if z1 == z2 and u2 < u1:
            tone = TOP
        elif u1 == u2 and z2 < z1:
            tone = LEFT
        else:
            continue
        strips.append(((x0 + x1) / 2 - (u1 + u2) / 2 + (z1 + z2) / 2, tone,
                       [(x1, u1, z1), (x1, u2, z2), (x0, u2, z2), (x0, u1, z1)]))
    strips.sort(key=lambda s: s[0])
    return [(t, q) for _, t, q in strips] + [(RIGHT, [(x1, u, z) for u, z in o])]


def flat(outline, z0, z1):
    """A rectilinear outline in (x, u), extruded over z in [z0, z1]: its top in
    the lit tone, with strips along its +x edges (right-hand tone) and -u edges
    (shaded), the farthest first and the top last."""
    o = _ccw(outline)
    strips = []
    for i in range(len(o)):
        (xa, ua), (xb, ub) = o[i], o[(i + 1) % len(o)]
        nx, nu = (ub - ua), -(xb - xa)     # the outward normal, counter-clockwise
        if nx > 0 and nu == 0:
            tone = RIGHT
        elif nu < 0 and nx == 0:
            tone = LEFT
        else:
            continue
        strips.append(((xa + xb) / 2 - (ua + ub) / 2 + (z0 + z1) / 2, tone,
                       [(xa, ua, z0), (xb, ub, z0), (xb, ub, z1), (xa, ua, z1)]))
    strips.sort(key=lambda s: s[0])
    return [(t, q) for _, t, q in strips] + [(TOP, [(x, u, z1) for x, u in o])]


def area(poly):
    return sum(poly[i - 1][0] * poly[i][1] - poly[i][0] * poly[i - 1][1] for i in range(len(poly))) / 2


def convex(poly):
    sign = 0
    for i in range(len(poly)):
        (ax, ay), (bx, by), (cx, cy) = poly[i - 2], poly[i - 1], poly[i]
        cr = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(cr) > 1e-9:
            if sign == 0:
                sign = 1 if cr > 0 else -1
            elif (cr > 0) != (sign > 0):
                return False
    return True


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


def nearness(face, X, Y):
    """x - u + z of a planar face where it shows at (X, Y) on screen: the
    larger, the nearer the viewer."""
    p0 = face[0]
    s0 = proj(*p0)
    for k in range(1, len(face) - 1):
        p1, p2 = face[k], face[k + 1]
        s1, s2 = proj(*p1), proj(*p2)
        e1, e2 = (s1[0] - s0[0], s1[1] - s0[1]), (s2[0] - s0[0], s2[1] - s0[1])
        det = e1[0] * e2[1] - e1[1] * e2[0]
        if abs(det) > 1e-9:
            a = ((X - s0[0]) * e2[1] - (Y - s0[1]) * e2[0]) / det
            b = (e1[0] * (Y - s0[1]) - e1[1] * (X - s0[0])) / det
            p = [p0[i] + a * (p1[i] - p0[i]) + b * (p2[i] - p0[i]) for i in range(3)]
            return p[0] - p[1] + p[2]
    raise ValueError('a face with no area')


def overlap(fi, fj):
    """Where two faces overlap on screen, as a point (X, Y), or None."""
    pi, pj = [proj(*p) for p in fi], [proj(*p) for p in fj]
    if convex(pj):
        both = clip(pi, pj)
    elif convex(pi):
        both = clip(pj, pi)
    else:
        return None
    if len(both) < 3 or abs(area(both)) < 1e-6:
        return None
    return sum(p[0] for p in both) / len(both), sum(p[1] for p in both) / len(both)


def order(shapes):
    """The faces of several shapes, in an order where, wherever two shapes
    overlap on screen, the nearer one comes later; each shape keeps its own
    order. Returns the faces, and the shapes' indices in the order drawn."""
    seq = arrange(shapes)
    return [f for i in seq for f in shapes[i]], seq


def arrange(shapes):
    """The shapes' indices, by a topological sort over the overlaps of their
    faces: where two overlap, the nearer is drawn later."""
    n = len(shapes)
    after = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            votes = 0
            for _, fi in shapes[i]:
                for _, fj in shapes[j]:
                    at = overlap(fi, fj)
                    if at is None:
                        continue
                    d = nearness(fi, *at) - nearness(fj, *at)
                    if abs(d) > 1e-6:
                        votes += 1 if d > 0 else -1
            if votes > 0:
                after[i].add(j)
            elif votes < 0:
                after[j].add(i)
    done, seq = set(), []
    while len(done) < n:
        ready = [i for i in range(n) if i not in done and after[i] <= done] or \
                [min((i for i in range(n) if i not in done), key=lambda i: len(after[i] - done))]
        for i in sorted(ready):
            done.add(i)
            seq.append(i)
    return seq


def place(faces, fit=FIT):
    """The faces on screen, scaled so the drawing is `fit` units across or down
    and centred in the square: (tone, on screen, in the world)."""
    pts = [proj(*p) for _, poly in faces for p in poly]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    k = min(fit / (max(xs) - min(xs)), fit / (max(ys) - min(ys)))
    ox = (SIZE - k * (max(xs) - min(xs))) / 2 - k * min(xs)
    oy = (SIZE - k * (max(ys) - min(ys))) / 2 - k * min(ys)
    return [(t, [(round(k * proj(*p)[0] + ox, 2), round(k * proj(*p)[1] + oy, 2)) for p in poly], poly)
            for t, poly in faces], k


def problems(placed):
    """The promises every icon's comment makes: the edges at the four
    isometric angles, the drawing inside the square, and every face drawn
    after the faces it hides."""
    errors = []
    for _, poly, _ in placed:
        for i in range(len(poly)):
            (x1, y1), (x2, y2) = poly[i - 1], poly[i]
            if (x1, y1) == (x2, y2):
                continue
            a = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
            if min(abs(a - t) for t in (0, 30, 90, 150, 180)) > 0.5:
                errors.append(f'an edge at {a:.1f} degrees: {poly[i - 1]} to {poly[i]}')
    pts = [p for _, poly, _ in placed for p in poly]
    if min(min(p) for p in pts) < 0 or max(max(p) for p in pts) > SIZE:
        errors.append('the drawing leaves the square')
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            (ti, _, fi), (tj, _, fj) = placed[i], placed[j]
            at = overlap(fi, fj)
            if at is not None and nearness(fj, *at) < nearness(fi, *at) - 1e-6:
                errors.append(f'a {tj} face is drawn over a nearer {ti} one')
    return errors


def svg(placed, title, comment, sections=()):
    """The SVG: its title, the comment that says what it is, and its faces;
    `sections` as ((label, count), ...) puts a comment before each run of faces."""
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" role="img">',
             f'\t<title>{title}</title>', comment.rstrip('\n')]
    at = 0
    for label, count in (sections or (('the drawing', len(placed)),)):
        lines.append(f'\n\t<!-- {label} -->')
        for t, poly, _ in placed[at:at + count]:
            lines.append(f'\t<polygon fill="{t}" points="{" ".join(f"{x:g},{y:g}" for x, y in poly)}"/>')
        at += count
    lines.append('</svg>\n')
    text = '\n'.join(lines)
    for c in text.split('<!--')[1:]:
        if '--' in c.split('-->')[0]:
            sys.exit('not written: a comment holds "--", which XML forbids (the browser would not decode the icon)')
    return text


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
    so that the checks need nothing beyond the standard library."""
    data = Path(png).read_bytes()
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


def tones(png):
    """The share of the picture in each of the three tones, exactly or nearly."""
    w, h, px = pixels(png)
    if px is None:
        return w, h, None
    near = lambda p, q: all(abs(a - b) <= 6 for a, b in zip(p, q))
    rgb = {TOP: (243, 184, 123), RIGHT: (187, 108, 93), LEFT: (52, 65, 38)}
    return w, h, {t: sum(1 for p in px if p[3] == 255 and near(p[:3], c)) / (w * h) for t, c in rgb.items()}


def looks_drawn(png, size, least):
    """The picture is the drawing, not a broken-image glyph: the right size,
    and each tone in `least` ({tone: share}) in at least that share."""
    w, h, share = tones(png)
    if (w, h) != (size, size) or share is None:
        return f'{Path(png).name} is {w}x{h}, not an {size}x{size} RGB(A) picture'
    for t, least_share in least.items():
        if share[t] < least_share:
            return f'{Path(png).name} hardly holds {t} ({share[t]:.3f} of it): not the drawing'
    return None


# Thin edges blend with what is beside them at 32 px, so only the lit tone,
# and the right-hand one, are asked of the small picture.
LEAST_32 = {TOP: 0.04, RIGHT: 0.008}
LEAST_180 = {TOP: 0.04, RIGHT: 0.008, LEFT: 0.004}


def write(svg_path, png32, png180, text, least32=LEAST_32, least180=LEAST_180):
    """Write the SVG and, from it, the 32 px PNG (on nothing) and the 180 px
    touch icon (on the plate), and check both."""
    Path(svg_path).write_text(text)
    print(f'wrote {Path(svg_path).relative_to(ROOT)}')
    if '--svg-only' in sys.argv[1:]:
        return
    if not Path(CHROME).exists():
        sys.exit(f'no Chrome at {CHROME} (set CHROME, or pass --svg-only); the PNGs were not redrawn')
    src = Path(svg_path).as_uri()
    rasterise('<!doctype html><body style="margin:0;background:transparent">'
              f'<img src="{src}" width="32" height="32" style="display:block">', png32, 32, 32)
    pad = (180 - TOUCH_DRAWN) // 2
    rasterise(f'<!doctype html><body style="margin:0;background:{TOUCH_PLATE}">'
              f'<img src="{src}" width="{TOUCH_DRAWN}" height="{TOUCH_DRAWN}" '
              f'style="display:block;margin:{pad}px">', png180, 180, 180)
    for png, size, least in ((png32, 32, least32), (png180, 180, least180)):
        if '--shares' in sys.argv[1:]:
            print(f'  {Path(png).name}:', {t: round(v, 3) for t, v in tones(png)[2].items()})
            continue
        bad = looks_drawn(png, size, least)
        if bad:
            sys.exit(bad)
    print(f'wrote {Path(png32).relative_to(ROOT)} and {Path(png180).relative_to(ROOT)}')


RULES = '''\t\tDRAWN IN THE KVOTAB MARK'S LANGUAGE, the same four rules as
\t\tkompartment/icon.svg and the other pages' icons: true 30-degree
\t\tisometric (every edge horizontal, at +/-30 degrees or vertical); one
\t\tflat tone per face, #f3b87b on top, #bb6c5d on the right, #344126 on
\t\tthe left; no strokes; no background plate.'''
