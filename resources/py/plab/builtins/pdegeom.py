"""Geometry and meshes for the PDE functions: decsg (constructive solid
geometry of circles, polygons, rectangles and ellipses into minimal
regions, by an exact arrangement of segments and arcs), the geometry made
from it or from a geometry function, triangular meshes (a conforming
Delaunay triangulation of points on the edges and an equilateral lattice
inside, smoothed; quadratic elements with their midside nodes on the
curved edges), FEMesh with findNodes, findElements, area and meshToPet,
and pdegplot and pdemesh."""
import math

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, darr, out, opt_str, is_str
from ..values import MError, Obj, Char, Cell, FH, py_str
from .. import runtime as R

TWO_PI = 2 * math.pi


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                raise err(f'pde:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0]) from None
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _outs(nargout, *vals):
    return vals[:max(nargout, 1)] if nargout > 1 else vals[0]


# ---- curves -----------------------------------------------------------------------------------------------------------------------

class Curve:
    """An edge's curve, parameterized from 0 (start) to 1 (end)."""

    def pts(self, s):
        s = np.atleast_1d(np.asarray(s, float))
        return self._pts(s)

    def length(self):
        P = self.pts(np.linspace(0, 1, 257))
        return float(np.sum(np.hypot(*np.diff(P, axis=0).T)))

    def by_length(self, u):
        """The parameters at the fractions u of the curve's length."""
        s = np.linspace(0, 1, 513)
        P = self.pts(s)
        cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))])
        return np.interp(np.asarray(u, float) * cum[-1], cum, s)

    def start(self):
        return self.pts(0.0)[0]

    def end(self):
        return self.pts(1.0)[0]

    def resolution(self):
        """How many pieces a drawing or a polygon of it needs."""
        return 1

    def poly(self, extra=1):
        return self.pts(np.linspace(0, 1, self.resolution() * extra + 1))


class Seg(Curve):
    kind = 2

    def __init__(self, p0, p1):
        self.p0, self.p1 = np.asarray(p0, float), np.asarray(p1, float)

    def _pts(self, s):
        return self.p0[None, :] + s[:, None] * (self.p1 - self.p0)[None, :]

    def length(self):
        return float(np.hypot(*(self.p1 - self.p0)))

    def by_length(self, u):
        return np.asarray(u, float)

    def param(self, p):
        d = self.p1 - self.p0
        return float(np.dot(np.asarray(p) - self.p0, d) / max(np.dot(d, d), 1e-300))

    def sub(self, s0, s1):
        return Seg(self.pts(s0)[0], self.pts(s1)[0])

    def dl(self):
        return [2.0, self.p0[0], self.p1[0], self.p0[1], self.p1[1]]


class Arc(Curve):
    """A circular arc, counterclockwise from angle a0 to a1."""
    kind = 1

    def __init__(self, c, r, a0, a1):
        self.c, self.r, self.a0, self.a1 = np.asarray(c, float), float(r), float(a0), float(a1)

    def _pts(self, s):
        a = self.a0 + s * (self.a1 - self.a0)
        return self.c[None, :] + self.r * np.column_stack([np.cos(a), np.sin(a)])

    def length(self):
        return self.r * (self.a1 - self.a0)

    def by_length(self, u):
        return np.asarray(u, float)

    def param(self, p):
        q = np.asarray(p) - self.c
        t = (math.atan2(q[1], q[0]) - self.a0) % TWO_PI
        span = self.a1 - self.a0
        if t > span + 1e-9 and TWO_PI - t < 1e-9:
            t -= TWO_PI
        return t / span

    def sub(self, s0, s1):
        d = self.a1 - self.a0
        return Arc(self.c, self.r, self.a0 + s0 * d, self.a0 + s1 * d)

    def resolution(self):
        return max(2, int(math.ceil((self.a1 - self.a0) / TWO_PI * 128)))

    def dl(self):
        p, q = self.start(), self.end()
        return [1.0, p[0], q[0], p[1], q[1]]

    def extra(self):
        return [self.c[0], self.c[1], self.r]


class EArc(Curve):
    """An elliptic arc: centre c, semi-axes a and b, the first rotated by phi; counterclockwise from t0 to t1 (the eccentric angle)."""
    kind = 4

    def __init__(self, c, a, b, phi, t0, t1):
        self.c, self.a, self.b, self.phi, self.t0, self.t1 = np.asarray(c, float), float(a), float(b), float(phi), float(t0), float(t1)

    def _pts(self, s):
        t = self.t0 + s * (self.t1 - self.t0)
        x, y = self.a * np.cos(t), self.b * np.sin(t)
        cp, sp = math.cos(self.phi), math.sin(self.phi)
        return self.c[None, :] + np.column_stack([cp * x - sp * y, sp * x + cp * y])

    def param(self, p):
        q = np.asarray(p) - self.c
        cp, sp = math.cos(self.phi), math.sin(self.phi)
        x, y = cp * q[0] + sp * q[1], -sp * q[0] + cp * q[1]
        t = (math.atan2(y / self.b, x / self.a) - self.t0) % TWO_PI
        span = self.t1 - self.t0
        if t > span + 1e-9 and TWO_PI - t < 1e-9:
            t -= TWO_PI
        return t / span

    def sub(self, s0, s1):
        d = self.t1 - self.t0
        return EArc(self.c, self.a, self.b, self.phi, self.t0 + s0 * d, self.t0 + s1 * d)

    def resolution(self):
        return max(2, int(math.ceil((self.t1 - self.t0) / TWO_PI * 160)))

    def dl(self):
        p, q = self.start(), self.end()
        return [4.0, p[0], q[0], p[1], q[1]]

    def extra(self):
        return [self.c[0], self.c[1], self.a, self.b, self.phi]


class FCurve(Curve):
    """An edge of a geometry function: fun(bs, s) for s from s0 to s1."""
    kind = 0

    def __init__(self, fh, bs, s0, s1):
        self.fh, self.bs, self.s0, self.s1 = fh, bs, float(s0), float(s1)
        self._len = None

    def _pts(self, s):
        sv = self.s0 + s * (self.s1 - self.s0)
        r = self.fh.scall(2, float(self.bs), out(sv.reshape(1, -1)))
        x, y = (np.asarray(darr(v), float).reshape(-1) for v in r)
        return np.column_stack([x, y])

    def resolution(self):
        return 64

    def dl(self):
        p, q = self.start(), self.end()
        return [0.0, p[0], q[0], p[1], q[1]]


# ---- point-in-region tests -----------------------------------------------------------------------------------------------------------

def _inside_loops(P, loops):
    """Even-odd rule: whether each point of P (n, 2) is inside the closed polygons loops."""
    P = np.atleast_2d(P)
    inside = np.zeros(P.shape[0], bool)
    x, y = P[:, 0][:, None], P[:, 1][:, None]
    for L in loops:
        a = L
        b = np.roll(L, -1, axis=0)
        xa, ya, xb, yb = a[:, 0][None, :], a[:, 1][None, :], b[:, 0][None, :], b[:, 1][None, :]
        cond = (ya > y) != (yb > y)
        with np.errstate(divide='ignore', invalid='ignore'):
            xc = xa + (y - ya) * (xb - xa) / (yb - ya)
        cross = cond & (x < xc)
        inside ^= (np.sum(cross, axis=1) % 2).astype(bool)
    return inside


def _signed_area(L):
    x, y = L[:, 0], L[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


# ---- decsg ---------------------------------------------------------------------------------------------------------------------------

class Shape:
    def __init__(self, kind, curves, member):
        self.kind, self.curves, self.member = kind, curves, member


def _shapes(gd):
    shapes = []
    for j in range(gd.shape[1]):
        col = gd[:, j]
        k = int(round(col[0]))
        if k == 1:
            c, r = col[1:3], col[3]
            if not r > 0:
                raise err('pde:decsg:radius', 'A circle needs a positive radius.', 'decsg')
            curves = [Arc(c, r, q * math.pi / 2, (q + 1) * math.pi / 2) for q in range(4)]
            member = (lambda P, c=c.copy(), r=r: np.hypot(P[:, 0] - c[0], P[:, 1] - c[1]) < r)
        elif k in (2, 3):
            n = int(round(col[1]))
            if n < 3 or 2 + 2 * n > col.size:
                raise err('pde:decsg:polygon', 'A polygon column is [2; n; x1..xn; y1..yn] (a rectangle [3; 4; ...]).', 'decsg')
            V = np.column_stack([col[2:2 + n], col[2 + n:2 + 2 * n]])
            curves = [Seg(V[i], V[(i + 1) % n]) for i in range(n) if np.hypot(*(V[(i + 1) % n] - V[i])) > 0]
            member = (lambda P, V=V.copy(): _inside_loops(P, [V]))
        elif k == 4:
            c, a, b, phi = col[1:3], col[3], col[4], col[5]
            if not (a > 0 and b > 0):
                raise err('pde:decsg:axes', 'An ellipse needs positive semi-axes.', 'decsg')
            curves = [EArc(c, a, b, phi, q * math.pi / 2, (q + 1) * math.pi / 2) for q in range(4)]

            def member(P, c=c.copy(), a=a, b=b, phi=phi):
                q = P - c[None, :]
                cp, sp = math.cos(phi), math.sin(phi)
                x, y = cp * q[:, 0] + sp * q[:, 1], -sp * q[:, 0] + cp * q[:, 1]
                return (x / a) ** 2 + (y / b) ** 2 < 1
        else:
            raise err('pde:decsg:kind', 'Each column of gd is a circle (1), polygon (2), rectangle (3) or ellipse (4).', 'decsg')
        shapes.append(Shape(k, curves, member))
    return shapes


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


EPS = 1e-9


def _within(s):
    return -EPS <= s <= 1 + EPS


def _clip(s):
    return min(max(s, 0.0), 1.0)


def _inter(e1, e2, scale):
    """Points where two curves meet: [(s1, s2, point)]; overlapping pieces give the ends of each inside the other."""
    tol = 1e-10 * scale
    res = []
    if isinstance(e1, Seg) and isinstance(e2, Seg):
        d1, d2 = e1.p1 - e1.p0, e2.p1 - e2.p0
        den = _cross(d1, d2)
        l1, l2 = np.hypot(*d1), np.hypot(*d2)
        if abs(den) <= 1e-12 * l1 * l2:
            if abs(_cross(d1, e2.p0 - e1.p0)) / max(l1, 1e-300) > tol:
                return res
            for p in (e2.p0, e2.p1):
                s = e1.param(p)
                if _within(s):
                    res.append((_clip(s), e2.param(p), p))
            for p in (e1.p0, e1.p1):
                s = e2.param(p)
                if _within(s):
                    res.append((e1.param(p), _clip(s), p))
            return res
        w = e2.p0 - e1.p0
        t = _cross(w, d2) / den
        u = _cross(w, d1) / den
        if _within(t) and _within(u):
            res.append((_clip(t), _clip(u), e1.p0 + _clip(t) * d1))
        return res
    if isinstance(e1, Arc) and isinstance(e2, Seg):
        return [(b, a, p) for a, b, p in _inter(e2, e1, scale)]
    if isinstance(e1, Seg) and isinstance(e2, Arc):
        d = e1.p1 - e1.p0
        f = e1.p0 - e2.c
        A, B, Cc = np.dot(d, d), 2 * np.dot(f, d), np.dot(f, f) - e2.r ** 2
        disc = B * B - 4 * A * Cc
        if disc < -1e-12 * max(B * B, 1e-300):
            return res
        sq = math.sqrt(max(disc, 0.0))
        for t in sorted({(-B - sq) / (2 * A), (-B + sq) / (2 * A)}):
            if _within(t):
                p = e1.p0 + _clip(t) * d
                s2 = e2.param(p)
                if _within(s2):
                    res.append((_clip(t), _clip(s2), p))
        return res
    if isinstance(e1, Arc) and isinstance(e2, Arc):
        dc = e2.c - e1.c
        d = float(np.hypot(*dc))
        if d <= tol and abs(e1.r - e2.r) <= tol:
            for p in (e2.start(), e2.end()):
                s = e1.param(p)
                if _within(s):
                    res.append((_clip(s), e2.param(p), p))
            for p in (e1.start(), e1.end()):
                s = e2.param(p)
                if _within(s):
                    res.append((e1.param(p), _clip(s), p))
            return res
        if d <= tol or d > e1.r + e2.r + tol or d < abs(e1.r - e2.r) - tol:
            return res
        a = (e1.r ** 2 - e2.r ** 2 + d * d) / (2 * d)
        h = math.sqrt(max(e1.r ** 2 - a * a, 0.0))
        base = e1.c + a * dc / d
        perp = np.array([-dc[1], dc[0]]) / d
        for p in ([base] if h <= tol else [base + h * perp, base - h * perp]):
            s1, s2 = e1.param(p), e2.param(p)
            if _within(s1) and _within(s2):
                res.append((_clip(s1), _clip(s2), p))
        return res
    if isinstance(e1, EArc) and isinstance(e2, EArc) and np.allclose(e1.c, e2.c) and abs(e1.a - e2.a) <= tol and abs(e1.b - e2.b) <= tol and \
            abs((e1.phi - e2.phi) % math.pi) <= 1e-12:
        for p in (e2.start(), e2.end()):
            s = e1.param(p)
            if _within(s):
                res.append((_clip(s), e2.param(p), p))
        for p in (e1.start(), e1.end()):
            s = e2.param(p)
            if _within(s):
                res.append((e1.param(p), _clip(s), p))
        return res
    return _inter_numeric(e1, e2, scale)


def _inter_numeric(e1, e2, scale):
    """Crossings of polygons of the two curves, each refined by Newton's method on e1(s1) = e2(s2)."""
    n = 96
    s = np.linspace(0, 1, n + 1)
    P, Q = e1.pts(s), e2.pts(s)
    res = []
    for i in range(n):
        a0, a1 = P[i], P[i + 1]
        for j in range(n):
            b0, b1 = Q[j], Q[j + 1]
            d1, d2 = a1 - a0, b1 - b0
            den = _cross(d1, d2)
            if abs(den) < 1e-300:
                continue
            w = b0 - a0
            t, u = _cross(w, d2) / den, _cross(w, d1) / den
            if -1e-6 <= t <= 1 + 1e-6 and -1e-6 <= u <= 1 + 1e-6:
                x = np.array([s[i] + t / n, s[j] + u / n])
                for _ in range(30):
                    h = 1e-7
                    F = e1.pts(x[0])[0] - e2.pts(x[1])[0]
                    J = np.column_stack([(e1.pts(x[0] + h)[0] - e1.pts(x[0] - h)[0]) / (2 * h), -(e2.pts(x[1] + h)[0] - e2.pts(x[1] - h)[0]) / (2 * h)])
                    try:
                        dx = np.linalg.solve(J, -F)
                    except np.linalg.LinAlgError:
                        break
                    x = x + dx
                    if np.max(np.abs(dx)) < 1e-14:
                        break
                if _within(x[0]) and _within(x[1]):
                    p = e1.pts(_clip(x[0]))[0]
                    if not any(np.hypot(*(p - q)) < 1e-8 * scale for _, _, q in res):
                        res.append((_clip(x[0]), _clip(x[1]), p))
    return res


class _Verts:
    def __init__(self, tol):
        self.P = []
        self.tol = tol

    def id(self, p):
        for k, q in enumerate(self.P):
            if abs(q[0] - p[0]) <= self.tol and abs(q[1] - p[1]) <= self.tol:
                return k
        self.P.append(np.asarray(p, float))
        return len(self.P) - 1


def _parse_formula(sf, names):
    """A set formula (+ union, * intersection, - difference; * first) as a function of a membership dict."""
    toks = []
    i = 0
    sf = sf.replace(' ', '')
    while i < len(sf):
        ch = sf[i]
        if ch in '+-*()':
            toks.append(ch)
            i += 1
            continue
        j = i
        while j < len(sf) and (sf[j].isalnum() or sf[j] == '_'):
            j += 1
        if j == i:
            raise err('pde:decsg:formula', f"'{ch}' is not read in a set formula.", 'decsg')
        nm = sf[i:j]
        if nm not in names:
            raise err('pde:decsg:formula', f"'{nm}' is not a shape's name in ns.", 'decsg')
        toks.append(('n', nm))
        i = j
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take():
        pos[0] += 1
        return toks[pos[0] - 1]

    def factor():
        t = take() if peek() is not None else None
        if t == '(':
            v = expr()
            if take() != ')':
                raise err('pde:decsg:formula', 'The set formula has a parenthesis open.', 'decsg')
            return v
        if isinstance(t, tuple):
            return lambda m, nm=t[1]: m[nm]
        raise err('pde:decsg:formula', 'The set formula is not complete.', 'decsg')

    def term():
        v = factor()
        while peek() == '*':
            take()
            w = factor()
            v = (lambda m, v=v, w=w: v(m) and w(m))
        return v

    def expr():
        v = term()
        while peek() in ('+', '-'):
            op = take()
            w = term()
            v = (lambda m, v=v, w=w: v(m) or w(m)) if op == '+' else (lambda m, v=v, w=w: v(m) and not w(m))
        return v
    f = expr()
    if pos[0] != len(toks):
        raise err('pde:decsg:formula', 'The set formula has something after its end.', 'decsg')
    return f


def _arrange(shapes):
    """The curves of the shapes split where they meet, as edges between vertices; the faces the edges bound."""
    curves = [(k, c) for k, sh in enumerate(shapes) for c in sh.curves]
    allp = np.vstack([c.poly() for _, c in curves])
    scale = float(max(np.ptp(allp[:, 0]), np.ptp(allp[:, 1]), 1e-300))
    V = _Verts(1e-9 * scale)
    cuts = [[(0.0, None), (1.0, None)] for _ in curves]
    for i in range(len(curves)):
        for j in range(i + 1, len(curves)):
            for s1, s2, p in _inter(curves[i][1], curves[j][1], scale):
                cuts[i].append((s1, p))
                cuts[j].append((s2, p))
    edges = []                          # (va, vb, curve)
    seen = {}
    for (k, c), cs in zip(curves, cuts):
        cs.sort(key=lambda t: t[0])
        pts = []
        for s, p in cs:
            vid = V.id(p if p is not None else c.pts(s)[0])
            if pts and (abs(s - pts[-1][0]) < 1e-12 or vid == pts[-1][1]):
                continue
            pts.append((s, vid))
        for (s0, v0), (s1, v1) in zip(pts[:-1], pts[1:]):
            if v0 == v1:
                continue
            sub = c.sub(s0, s1)
            mid = sub.pts(0.5)[0]
            key = (min(v0, v1), max(v0, v1), round(mid[0] / scale, 7), round(mid[1] / scale, 7))
            if key in seen:
                continue
            seen[key] = len(edges)
            edges.append((v0, v1, sub))
    P = np.array(V.P)
    return P, edges, scale


def _faces(P, edges, scale):
    """Trace the faces of the planar graph: (cycles of half-edges (edge, +1/-1), their polygons, signed areas)."""
    out_ = {}
    for i, (va, vb, c) in enumerate(edges):
        for d, v in ((1, va), (-1, vb)):
            q = c.pts(1e-6 if d > 0 else 1 - 1e-6)[0] - P[v]
            out_.setdefault(v, []).append((math.atan2(q[1], q[0]), i, d))
    for v in out_:
        out_[v].sort()
    pos = {(i, d): (v, k) for v, lst in out_.items() for k, (_, i, d) in enumerate(lst)}
    used = set()
    cycles = []
    for i in range(len(edges)):
        for d in (1, -1):
            if (i, d) in used:
                continue
            cyc = []
            h = (i, d)
            while h not in used:
                used.add(h)
                cyc.append(h)
                ei, dd = h
                twin = (ei, -dd)
                v, k = pos[twin]
                lst = out_[v]
                _, ni, nd = lst[(k - 1) % len(lst)]
                h = (ni, nd)
            cycles.append(cyc)
    polys = []
    for cyc in cycles:
        pts = []
        for ei, d in cyc:
            c = edges[ei][2]
            pp = c.poly()
            if d < 0:
                pp = pp[::-1]
            pts.append(pp[:-1])
        polys.append(np.vstack(pts))
    areas = [_signed_area(L) for L in polys]
    return cycles, polys, areas


def _left_point(c, d, scale, frac=1e-4):
    """A point just to the left of a half-edge, at its middle."""
    p = c.pts(0.5)[0]
    q = c.pts(0.5 + 1e-4)[0] - c.pts(0.5 - 1e-4)[0]
    q = q / max(np.hypot(*q), 1e-300) * d
    return p + frac * scale * np.array([-q[1], q[0]])


def _regions(P, edges, scale):
    """The bounded faces: [(outer cycle index, [hole cycle indices], an interior point)] and each half-edge's face (-1 outside)."""
    cycles, polys, areas = _faces(P, edges, scale)
    atol = 1e-14 * scale * scale
    pos = [k for k, a in enumerate(areas) if a > atol]
    faces = {k: [] for k in pos}
    for k, a in enumerate(areas):
        if a > atol:
            continue
        ei, d = cycles[k][0]
        p = _left_point(edges[ei][2], d, scale)
        best = None
        for f in pos:
            if _inside_loops(p[None, :], [polys[f]])[0] and (best is None or areas[f] < areas[best]):
                best = f
        if best is not None:
            faces[best].append(k)
    result = []
    for f in pos:
        loops = [polys[f]] + [polys[h] for h in faces[f]]
        pt = None
        for frac in (1e-4, 1e-3, 1e-2, 1e-6):
            for ei, d in cycles[f]:
                q = _left_point(edges[ei][2], d, scale, frac)
                if _inside_loops(q[None, :], loops)[0]:
                    pt = q
                    break
            if pt is not None:
                break
        if pt is None:
            pt = polys[f].mean(axis=0)
        result.append((f, faces[f], pt))
    half_face = {}
    for idx, (f, holes, _) in enumerate(result):
        for k in [f] + holes:
            for h in cycles[k]:
                half_face[h] = idx
    return result, half_face, cycles, polys


@bi('decsg', nout=2)
def decsg(nargout, *args):
    """[dl, bt] = decsg(gd, sf, ns), decsg(gd): the geometry description matrix gd (a column each: circle [1; xc; yc; r], polygon [2; n; x; y], rectangle [3; 4; x; y], ellipse [4; xc; yc; a; b; phi]) decomposed into minimal regions: dl a column for each edge ([type; x1; x2; y1; y2; left face; right face; centre and radius or ellipse data], type 2 a segment, 1 a circular arc, 4 an elliptic arc, counterclockwise) of the regions the set formula sf keeps (+ union, * intersection, - difference, over the names in the columns of ns), bt which shapes each region lies in."""
    nargchk(args, 1, 3, 'decsg')
    gd = np.asarray(darr(args[0]), float)
    gd = gd.reshape(-1, 1) if gd.ndim == 1 else gd
    shapes = _shapes(gd)
    names = [f'S{k + 1}' for k in range(len(shapes))]
    if len(args) > 2:
        ns = args[2]
        rows = ns.row_strs() if isinstance(ns, Char) else [str(x) for x in np.asarray(darr(ns)).reshape(-1)]
        a = ns.a if isinstance(ns, Char) else None
        # a name in each column (ns'), or in each row when only that fits
        if a is not None and a.shape[1] == len(shapes):
            rows = [''.join(chr(int(ch)) for ch in a[:, j]).strip() for j in range(a.shape[1])]
        elif a is not None and a.shape[0] == len(shapes):
            rows = [r.strip() for r in ns.row_strs()]
        if len(rows) != len(shapes):
            raise err('pde:decsg:ns', 'ns has a name for each column of gd (a column each).', 'decsg')
        names = rows
    formula = py_str(args[1]) if len(args) > 1 else '+'.join(names)
    keep = _parse_formula(formula, names)
    P, edges, scale = _arrange(shapes)
    regions, half_face, _, _ = _regions(P, edges, scale)
    rows_bt, kept = [], []
    for f, holes, pt in regions:
        m = {nm: bool(sh.member(pt[None, :])[0]) for nm, sh in zip(names, shapes)}
        rows_bt.append([float(m[nm]) for nm in names])
        kept.append(keep(m))
    order = [k for k in range(len(regions)) if kept[k]]
    order.sort(key=lambda k: (round(regions[k][2][0], 9), round(regions[k][2][1], 9)))
    num = {k: n + 1 for n, k in enumerate(order)}
    cols = []
    for i, (va, vb, c) in enumerate(edges):
        lf = num.get(half_face.get((i, 1), -1), 0)
        rf = num.get(half_face.get((i, -1), -1), 0)
        if lf == 0 and rf == 0:
            continue
        col = c.dl() + [float(lf), float(rf)]
        if isinstance(c, (Arc, EArc)):
            col += c.extra()
        cols.append(col)
    if not cols:
        raise err('pde:decsg:empty', 'The set formula keeps no region.', 'decsg')
    nr = max(len(c) for c in cols)
    dl = np.zeros((nr, len(cols)))
    for j, c in enumerate(cols):
        dl[:len(c), j] = c
    bt = np.array([rows_bt[k] for k in order]) if order else np.zeros((0, len(shapes)))
    return _outs(nargout, out(dl), out(bt))


# ---- the geometry ---------------------------------------------------------------------------------------------------------------------

class Geometry(Obj):
    """A 2-D geometry: its edges (curves with the faces to their left and right, 0 outside), faces and vertices."""
    cls = 'pde.AnalyticGeometry'
    is_handle = True

    def __init__(self, curves, left, right):
        self.curves, self.left, self.right = curves, np.asarray(left, int), np.asarray(right, int)
        self.nfaces = int(max(self.left.max(initial=0), self.right.max(initial=0)))
        allp = np.vstack([c.poly() for c in curves])
        self.scale = float(max(np.ptp(allp[:, 0]), np.ptp(allp[:, 1]), 1e-300))
        V = _Verts(1e-8 * self.scale)
        self.ev = [(V.id(c.start()), V.id(c.end())) for c in curves]
        self.V = np.array(V.P)
        self._loops = None

    def face_loops(self):
        """For each face, its boundary as closed polygons (even-odd)."""
        if self._loops is None:
            loops = []
            for f in range(1, self.nfaces + 1):
                pieces = []
                for i, c in enumerate(self.curves):
                    if self.left[i] == f:
                        pieces.append(c.poly(4))
                    elif self.right[i] == f:
                        pieces.append(c.poly(4)[::-1])
                loops.append(_chain(pieces, 1e-7 * self.scale))
            self._loops = loops
        return self._loops

    def face_of(self, P):
        """The face each point lies in (0 outside)."""
        res = np.zeros(P.shape[0], int)
        for f, loops in enumerate(self.face_loops(), start=1):
            ins = _inside_loops(P, loops) & (res == 0)
            res[ins] = f
        return res

    def getprop(self, name):
        k = name.lower()
        if k == 'numfaces':
            return float(self.nfaces)
        if k == 'numedges':
            return float(len(self.curves))
        if k == 'numvertices':
            return float(self.V.shape[0])
        if k == 'numcells':
            return 0.0
        if k == 'vertices':
            return out(self.V)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'AnalyticGeometry'.")

    def propnames(self):
        return ['NumCells', 'NumFaces', 'NumEdges', 'NumVertices', 'Vertices']

    def display_lines(self):
        return ['  AnalyticGeometry with properties:', '', '       NumCells: 0', f'       NumFaces: {self.nfaces}',
                f'       NumEdges: {len(self.curves)}', f'    NumVertices: {self.V.shape[0]}', f'       Vertices: [{self.V.shape[0]}×2 double]']


def _chain(pieces, tol):
    """Pieces of boundary (point lists, the face on their left) joined end to end into closed loops."""
    loops = []
    left = list(pieces)
    while left:
        cur = list(left.pop(0))
        for _ in range(len(pieces) + 1):
            if np.hypot(*(np.asarray(cur[-1]) - cur[0])) <= tol:
                break
            k = next((i for i, p in enumerate(left) if np.hypot(*(p[0] - cur[-1])) <= tol), None)
            if k is None:
                break
            cur.extend(list(left.pop(k))[1:])
        loops.append(np.array(cur[:-1]) if len(cur) > 2 else np.array(cur))
    return loops


def geometry_from(g, fn='geometryFromEdges'):
    """A geometry from a decomposed geometry matrix dl or a geometry function."""
    if isinstance(g, FH) or (is_str(g) and not isinstance(g, Cell)):
        fh = R.NamedFH(py_str(g)) if is_str(g) else g
        ne = int(round(float(np.asarray(darr(fh.scall(1))).reshape(-1)[0])))
        d = np.asarray(darr(fh.scall(1, out(np.arange(1, ne + 1, dtype=float).reshape(1, -1)))), float)
        curves = [FCurve(fh, k + 1, d[0, k], d[1, k]) for k in range(ne)]
        return Geometry(curves, d[2], d[3])
    dl = np.asarray(darr(g), float)
    if dl.ndim != 2 or dl.shape[0] < 7:
        raise err(f'pde:{fn}:dl', 'The geometry is a decomposed geometry matrix (decsg) or a geometry function.', fn)
    curves = []
    for j in range(dl.shape[1]):
        col = dl[:, j]
        k = int(round(col[0]))
        p0, p1 = np.array([col[1], col[3]]), np.array([col[2], col[4]])
        if k == 2:
            curves.append(Seg(p0, p1))
        elif k == 1:
            c, r = col[7:9], col[9]
            a0 = math.atan2(p0[1] - c[1], p0[0] - c[0])
            a1 = math.atan2(p1[1] - c[1], p1[0] - c[0])
            while a1 <= a0 + 1e-12:
                a1 += TWO_PI
            curves.append(Arc(c, r, a0, a1))
        elif k == 4:
            c, a, b, phi = col[7:9], col[9], col[10], col[11]
            tmp = EArc(c, a, b, phi, 0.0, TWO_PI)
            t0 = tmp.param(p0) * TWO_PI
            t1 = tmp.param(p1) * TWO_PI
            while t1 <= t0 + 1e-12:
                t1 += TWO_PI
            curves.append(EArc(c, a, b, phi, t0, t1))
        else:
            raise err(f'pde:{fn}:type', 'Each column of dl is a segment (2), a circular arc (1) or an elliptic arc (4).', fn)
    return Geometry(curves, dl[5], dl[6])


# ---- meshes --------------------------------------------------------------------------------------------------------------------------

class Mesh:
    """Nodes (n, 2), elements (m, 3 or 6, corners counterclockwise then the midside nodes 1-2, 2-3, 3-1), each element's face,
    the boundary pieces (nodes along each geometric edge, with the edge) and each node's edges."""

    def __init__(self, p, t, tface, bsegs, hmax, hmin, order):
        self.p, self.t, self.tface, self.bsegs, self.hmax, self.hmin, self.order = p, t, tface, bsegs, hmax, hmin, order

    def edge_nodes(self, ids):
        ids = set(int(i) for i in ids)
        nodes = set()
        for seg in self.bsegs:
            if seg[-1] in ids:
                nodes.update(int(x) for x in seg[:-1] if x >= 0)
        return np.array(sorted(nodes), int)

    def face_nodes(self, ids):
        sel = np.isin(self.tface, list(ids))
        return np.unique(self.t[sel])

    def areas(self):
        p, t = self.p, self.t[:, :3]
        a, b, c = p[t[:, 0]], p[t[:, 1]], p[t[:, 2]]
        return 0.5 * ((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))


def _lattice(geom, h, bpts):
    lo = geom.V.min(axis=0) if geom.V.size else np.zeros(2)
    hi = geom.V.max(axis=0) if geom.V.size else np.ones(2)
    allp = np.vstack([c.poly(2) for c in geom.curves])
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    dy = h * math.sqrt(3) / 2
    ys = np.arange(lo[1] + dy / 2, hi[1], dy)
    pts = []
    for k, y in enumerate(ys):
        off = (h / 2) if k % 2 else 0.0
        xs = np.arange(lo[0] + h / 4 + off, hi[0], h)
        pts.append(np.column_stack([xs, np.full(xs.size, y)]))
    P = np.vstack(pts) if pts else np.zeros((0, 2))
    if not P.size:
        return P
    P = P[geom.face_of(P) > 0]
    if P.size and bpts.size:
        from scipy.spatial import cKDTree
        d, _ = cKDTree(bpts).query(P)
        P = P[d > 0.55 * h]
    return P


def _sample_edges(geom, h, hmin):
    """Nodes along every edge (shared at the vertices) and the boundary pieces: [a, b, edge, s_a, s_b]."""
    nodes = [v for v in geom.V]
    segs = []
    for i, c in enumerate(geom.curves):
        L = c.length()
        n = max(1, int(math.ceil(L / h - 1e-9)))
        if isinstance(c, Arc):
            n = max(n, int(math.ceil((c.a1 - c.a0) / (math.pi / 6) - 1e-9)))
        elif isinstance(c, (EArc, FCurve)):
            n = max(n, 4)
        if hmin > 0:
            n = min(n, max(1, int(L / hmin)))
        s = c.by_length(np.linspace(0, 1, n + 1))
        va, vb = geom.ev[i]
        ids = [va]
        if n > 1:
            P = c.pts(s[1:-1])
            for p in P:
                nodes.append(p)
                ids.append(len(nodes) - 1)
        ids.append(vb)
        for k in range(n):
            segs.append([ids[k], ids[k + 1], i, s[k], s[k + 1]])
    return nodes, segs


def _split_encroached(geom, nodes, segs):
    """Boundary pieces whose diametral circle holds another boundary node, halved until none does."""
    from scipy.spatial import cKDTree
    for _ in range(40):
        P = np.array(nodes)
        tree = cKDTree(P)
        new = []
        changed = False
        for a, b, e, sa, sb in segs:
            m = (P[a] + P[b]) / 2
            r = np.hypot(*(P[b] - P[a])) / 2
            hits = [k for k in tree.query_ball_point(m, r * (1 - 1e-9)) if k != a and k != b]
            if hits and r > 1e-9 * geom.scale:
                sm = (sa + sb) / 2
                nodes.append(geom.curves[e].pts(sm)[0])
                k = len(nodes) - 1
                new += [[a, k, e, sa, sm], [k, b, e, sm, sb]]
                changed = True
            else:
                new.append([a, b, e, sa, sb])
        segs = new
        if not changed:
            break
    return nodes, segs


def make_mesh(geom, hmax=None, hmin=None, order='quadratic'):
    from scipy.spatial import Delaunay, cKDTree
    h = float(hmax) if hmax else geom.scale / 10
    hm = float(hmin) if hmin else 0.0
    nodes, segs = _sample_edges(geom, h, hm)
    nodes, segs = _split_encroached(geom, nodes, segs)
    for _ in range(10):
        B = np.array(nodes)
        I = _lattice(geom, h, B)
        # interior points out of the boundary pieces' diametral circles
        if I.size:
            mids = np.array([(B[a] + B[b]) / 2 for a, b, *_ in segs])
            rads = np.array([np.hypot(*(B[b] - B[a])) / 2 for a, b, *_ in segs])
            tree = cKDTree(I)
            bad = set()
            for m, r in zip(mids, rads):
                bad.update(tree.query_ball_point(m, r * 1.02))
            I = np.delete(I, sorted(bad), axis=0)
        P = np.vstack([B, I])
        tri = Delaunay(P).simplices
        have = set()
        for s in tri:
            for x, y in ((s[0], s[1]), (s[1], s[2]), (s[2], s[0])):
                have.add((min(x, y), max(x, y)))
        missing = [k for k, (a, b, *_) in enumerate(segs) if (min(a, b), max(a, b)) not in have]
        if not missing:
            break
        new = []
        for k, (a, b, e, sa, sb) in enumerate(segs):
            if k in missing:
                sm = (sa + sb) / 2
                nodes.append(geom.curves[e].pts(sm)[0])
                m = len(nodes) - 1
                new += [[a, m, e, sa, sm], [m, b, e, sm, sb]]
            else:
                new.append([a, b, e, sa, sb])
        segs = new
    cen = P[tri].mean(axis=1)
    face = geom.face_of(cen)
    keep = face > 0
    tri, face = tri[keep], face[keep]
    # counterclockwise corners
    a, b, c = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    neg = ((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])) < 0
    tri[neg] = tri[neg][:, [0, 2, 1]]
    # nodes no element uses (lattice points in cut-off corners) dropped
    used = np.unique(tri)
    nb = len(nodes)
    remap = -np.ones(P.shape[0], int)
    remap[used] = np.arange(used.size)
    P = P[used]
    tri = remap[tri]
    segs = [[remap[a], remap[b], e, sa, sb] for a, b, e, sa, sb in segs]
    nbound = np.zeros(P.shape[0], bool)
    for a, b, *_ in segs:
        nbound[a] = nbound[b] = True
    del nb
    P = _smooth(P, tri, nbound)
    if order == 'quadratic':
        P, t6, segs6 = _quadratic(P, tri, segs, geom)
        bsegs = [(a, b, m, e) for a, b, m, e in segs6]
        return Mesh(P, t6, face, bsegs, h, hm, 'quadratic')
    bsegs = [(a, b, -1, e) for a, b, e, _, _ in segs]
    return Mesh(P, tri, face, bsegs, h, hm, 'linear')


def _smooth(P, tri, fixed, iters=4):
    """Laplacian smoothing of the inner nodes, a move kept only while every element stays the right way round."""
    n = P.shape[0]
    nbr = [set() for _ in range(n)]
    for s in tri:
        for x, y in ((s[0], s[1]), (s[1], s[2]), (s[2], s[0])):
            nbr[x].add(y)
            nbr[y].add(x)
    elems = [[] for _ in range(n)]
    for k, s in enumerate(tri):
        for x in s:
            elems[x].append(k)

    def ok(k, Q):
        a, b, c = Q[tri[k, 0]], Q[tri[k, 1]], Q[tri[k, 2]]
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) > 0
    P = P.copy()
    for _ in range(iters):
        for i in range(n):
            if fixed[i] or not nbr[i]:
                continue
            old = P[i].copy()
            P[i] = P[list(nbr[i])].mean(axis=0)
            if not all(ok(k, P) for k in elems[i]):
                P[i] = old
    return P


def _quadratic(P, tri, segs, geom):
    """Midside nodes: on the curve for an edge on the boundary, halfway along the side elsewhere."""
    onb = {}
    for a, b, e, sa, sb in segs:
        onb[(min(a, b), max(a, b))] = (e, (sa + sb) / 2)
    mid = {}
    nodes = [p for p in P]
    t6 = np.zeros((tri.shape[0], 6), int)
    for k, (a, b, c) in enumerate(tri):
        t6[k, :3] = (a, b, c)
        for j, (x, y) in enumerate(((a, b), (b, c), (c, a))):
            key = (min(x, y), max(x, y))
            if key not in mid:
                if key in onb:
                    e, sm = onb[key]
                    nodes.append(geom.curves[e].pts(sm)[0])
                else:
                    nodes.append((P[x] + P[y]) / 2)
                mid[key] = len(nodes) - 1
            t6[k, 3 + j] = mid[key]
    segs6 = [(a, b, mid[(min(a, b), max(a, b))], e) for a, b, e, _, _ in segs]
    return np.array(nodes), t6, segs6


# ---- FEMesh --------------------------------------------------------------------------------------------------------------------------

class FEMesh(Obj):
    cls = 'pde.FEMesh'
    is_handle = True

    def __init__(self, mesh):
        self.m = mesh

    def getprop(self, name):
        k = name.lower()
        m = self.m
        if k == 'nodes':
            return out(m.p.T)
        if k == 'elements':
            return out(m.t.T + 1.0)
        if k == 'maxelementsize':
            return float(m.hmax)
        if k == 'minelementsize':
            return float(m.hmin)
        if k == 'meshgradation':
            return 1.5
        if k == 'geometricorder':
            return Char.of(m.order)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'FEMesh'.")

    def propnames(self):
        return ['Nodes', 'Elements', 'MaxElementSize', 'MinElementSize', 'MeshGradation', 'GeometricOrder']

    def display_lines(self):
        m = self.m
        return ['  FEMesh with properties:', '', f'             Nodes: [2×{m.p.shape[0]} double]', f'          Elements: [{m.t.shape[1]}×{m.t.shape[0]} double]',
                f'    MaxElementSize: {m.hmax:.4g}', f'    MinElementSize: {m.hmin:.4g}', '     MeshGradation: 1.5', f"    GeometricOrder: '{m.order}'"]


def _femesh(v, fn):
    from .pdefem import PDEModel, _Results
    if isinstance(v, FEMesh):
        return v.m
    if isinstance(v, PDEModel):
        if v.mesh is None:
            raise err(f'pde:{fn}:noMesh', 'The model has no mesh: generateMesh first.', fn)
        return v.mesh
    if isinstance(v, _Results):
        return v.mesh
    raise err(f'pde:{fn}:mesh', f'{fn} takes a mesh (FEMesh) or a model with one.', fn)


@bi('findNodes')
def findNodes(nargout, *args):
    """nodes = findNodes(mesh, 'region', 'Edge'|'Face', ids), findNodes(mesh, 'box', xlim, ylim), findNodes(mesh, 'radius', center, r), findNodes(mesh, 'nearest', points): node numbers (a row)."""
    nargchk(args, 3, 4, 'findNodes')
    m = _femesh(args[0], 'findNodes')
    how = py_str(args[1]).lower()
    P = m.p
    if how == 'region':
        kind = py_str(args[2]).lower()
        ids = np.asarray(darr(args[3]), float).reshape(-1).astype(int)
        nodes = m.edge_nodes(ids) if kind == 'edge' else m.face_nodes(ids) if kind == 'face' else None
        if nodes is None:
            raise err('pde:findNodes:region', "The region is 'Edge' or 'Face'.", 'findNodes')
    elif how == 'box':
        xl = np.asarray(darr(args[2]), float).reshape(-1)
        yl = np.asarray(darr(args[3]), float).reshape(-1)
        nodes = np.flatnonzero((P[:, 0] >= xl[0]) & (P[:, 0] <= xl[1]) & (P[:, 1] >= yl[0]) & (P[:, 1] <= yl[1]))
    elif how == 'radius':
        c = np.asarray(darr(args[2]), float).reshape(-1)
        r = float(np.asarray(darr(args[3]), float).reshape(-1)[0])
        nodes = np.flatnonzero(np.hypot(P[:, 0] - c[0], P[:, 1] - c[1]) <= r)
    elif how == 'nearest':
        Q = np.asarray(darr(args[2]), float)
        Q = Q.reshape(2, -1) if Q.ndim == 1 or Q.shape[0] == 2 else Q.T
        d = np.hypot(P[:, 0][:, None] - Q[0][None, :], P[:, 1][:, None] - Q[1][None, :])
        nodes = np.argmin(d, axis=0)
    else:
        raise err('pde:findNodes:how', "findNodes looks by 'region', 'box', 'radius' or 'nearest'.", 'findNodes')
    return out(np.asarray(nodes, float).reshape(1, -1) + 1)


@bi('findElements')
def findElements(nargout, *args):
    """elems = findElements(mesh, 'region', 'Face', ids), findElements(mesh, 'box', xlim, ylim), findElements(mesh, 'radius', center, r), findElements(mesh, 'attached', nodes): element numbers (a row); 'box' and 'radius' take the elements with all their nodes inside."""
    nargchk(args, 3, 4, 'findElements')
    m = _femesh(args[0], 'findElements')
    how = py_str(args[1]).lower()
    P = m.p
    if how == 'region':
        ids = np.asarray(darr(args[3]), float).reshape(-1).astype(int)
        el = np.flatnonzero(np.isin(m.tface, ids))
    elif how == 'attached':
        nodes = np.asarray(darr(args[2]), float).reshape(-1).astype(int) - 1
        el = np.flatnonzero(np.any(np.isin(m.t, nodes), axis=1))
    else:
        if how == 'box':
            xl = np.asarray(darr(args[2]), float).reshape(-1)
            yl = np.asarray(darr(args[3]), float).reshape(-1)
            ins = (P[:, 0] >= xl[0]) & (P[:, 0] <= xl[1]) & (P[:, 1] >= yl[0]) & (P[:, 1] <= yl[1])
        elif how == 'radius':
            c = np.asarray(darr(args[2]), float).reshape(-1)
            r = float(np.asarray(darr(args[3]), float).reshape(-1)[0])
            ins = np.hypot(P[:, 0] - c[0], P[:, 1] - c[1]) <= r
        else:
            raise err('pde:findElements:how', "findElements looks by 'region', 'box', 'radius' or 'attached'.", 'findElements')
        el = np.flatnonzero(np.all(ins[m.t], axis=1))
    return out(np.asarray(el, float).reshape(1, -1) + 1)


def _area_mesh(nargout, *args):
    m = _femesh(args[0], 'area')
    a = _element_areas(m)
    if len(args) > 1:
        idx = np.asarray(darr(args[1]), float).reshape(-1).astype(int) - 1
        a = a[idx]
    return _outs(nargout, float(a.sum()), out(a.reshape(1, -1)))


def _element_areas(m):
    """Element areas, a quadratic element's by its curved sides (the 6-point rule on its isoparametric map)."""
    if m.order == 'linear':
        return m.areas()
    from .pdefem import _ref
    G = _ref('quadratic')
    X = m.p[m.t]                                    # (ne, 6, 2)
    J = np.einsum('qbd,ebx->eqxd', G['dN'], X)      # (ne, nq, 2(x), 2(d))
    det = J[..., 0, 0] * J[..., 1, 1] - J[..., 0, 1] * J[..., 1, 0]
    return np.sum(det * G['w'][None, :], axis=1)


def _wrap_area():
    info = REG.get('area')
    if info is None:
        return
    orig, ws, aw = info.fn, info.ws, info.aw

    def test(v):
        from .pdefem import PDEModel
        return isinstance(v, (FEMesh, PDEModel))
    if aw:
        async def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                return _area_mesh(a[1] if ws else a[0], *args)
            return await orig(*a)
    else:
        def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                return _area_mesh(a[1] if ws else a[0], *args)
            return orig(*a)
    info.fn = f
    info.nout = max(info.nout, 2)


_wrap_area()


@bi('meshToPet', nout=3)
def meshToPet(nargout, *args):
    """[p, e, t] = meshToPet(mesh): the mesh in the older form: p the nodes (2-by-n), e the boundary pieces (a column each: start and end node, parameters, edge, faces to the left and right), t the elements (corners, or all six nodes, then the face)."""
    nargchk(args, 1, 1, 'meshToPet')
    m = _femesh(args[0], 'meshToPet')
    p = m.p.T
    e = np.zeros((7, len(m.bsegs)))
    for k, (a, b, _, ed) in enumerate(m.bsegs):
        e[:, k] = [a + 1, b + 1, 0, 1, ed + 1, 0, 0]
    t = np.vstack([m.t.T + 1.0, m.tface.reshape(1, -1).astype(float)])
    return _outs(nargout, out(p), out(e), out(t))


# ---- drawing ----------------------------------------------------------------------------------------------------------------------------

def _geom_of(v, fn):
    from .pdefem import PDEModel
    if isinstance(v, Geometry):
        return v
    if isinstance(v, PDEModel):
        if v.geometry is None:
            raise err(f'pde:{fn}:noGeometry', 'The model has no geometry: geometryFromEdges first.', fn)
        return v.geometry
    return geometry_from(v, fn)


def _onoff(o, k):
    v = o.get(k)
    return v is not None and (py_str(v).lower() == 'on' if is_str(v) else bool(np.asarray(darr(v)).reshape(-1)[0]))


def _opts(args, names, fn):
    o = {}
    for i in range(0, len(args) - 1, 2):
        k = opt_str(args[i])
        if k is None or k.lower() not in names:
            raise err(f'pde:{fn}:option', f"'{py_str(args[i]) if is_str(args[i]) else '?'}' is not an option of {fn}.", fn)
        o[k.lower()] = args[i + 1]
    if len(args) % 2:
        raise err(f'pde:{fn}:pairs', 'The options come as names and values.', fn)
    return o


def _b(name, *a):
    return R._builtin(name, *a)


@bi('pdegplot')
def pdegplot(nargout, *args):
    """pdegplot(model), pdegplot(dl), pdegplot(geometry function), with 'EdgeLabels', 'FaceLabels', 'VertexLabels' 'on': the geometry's edges drawn, labelled E1, F1, V1."""
    nargchk(args, 1, 9, 'pdegplot')
    g = _geom_of(args[0], 'pdegplot')
    o = _opts(list(args[1:]), ('edgelabels', 'facelabels', 'vertexlabels', 'facealpha', 'celllabels'), 'pdegplot')
    ax = _b('gca')
    hold = ax.props.get('NextPlot') == 'add' if hasattr(ax, 'props') else False
    for i, c in enumerate(g.curves):
        Pp = c.poly(2)
        _b('plot', ax, out(Pp[:, 0].reshape(-1, 1)), out(Pp[:, 1].reshape(-1, 1)), Char.of('Color'), out(np.array([[0.0, 0.0, 0.0]])))
        if i == 0:
            _b('hold', ax, Char.of('on'))
        if _onoff(o, 'edgelabels'):
            m = c.pts(0.5)[0]
            _b('text', ax, float(m[0]), float(m[1]), Char.of(f'E{i + 1}'), Char.of('Color'), out(np.array([[0.0, 0.0, 1.0]])), Char.of('FontWeight'), Char.of('bold'))
    if _onoff(o, 'vertexlabels'):
        for k, v in enumerate(g.V):
            _b('text', ax, float(v[0]), float(v[1]), Char.of(f'V{k + 1}'), Char.of('Color'), out(np.array([[0.0, 0.5, 0.0]])))
    if _onoff(o, 'facelabels'):
        for f in range(1, g.nfaces + 1):
            pt = _face_point(g, f)
            if pt is not None:
                _b('text', ax, float(pt[0]), float(pt[1]), Char.of(f'F{f}'), Char.of('Color'), out(np.array([[1.0, 0.0, 0.0]])), Char.of('FontWeight'), Char.of('bold'))
    if not hold:
        _b('hold', ax, Char.of('off'))
    _b('axis', ax, Char.of('equal'))
    # a margin round the geometry, so that edges on its bounding box are not hidden by the axes' box
    allp = np.vstack([c.poly() for c in g.curves])
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    mg = 0.05 * float(max(hi - lo))
    _b('axis', ax, out(np.array([[lo[0] - mg, hi[0] + mg, lo[1] - mg, hi[1] + mg]])))
    return None


def _face_point(g, f):
    """A point well inside face f: the lattice point of a fine grid deepest inside it."""
    loops = g.face_loops()[f - 1]
    allp = np.vstack(loops)
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    xs, ys = np.linspace(lo[0], hi[0], 41)[1:-1], np.linspace(lo[1], hi[1], 41)[1:-1]
    X, Y = np.meshgrid(xs, ys)
    Q = np.column_stack([X.ravel(), Y.ravel()])
    ins = _inside_loops(Q, loops)
    if not ins.any():
        return None
    Q = Q[ins]
    bd = np.vstack([np.vstack([L, L[:1]]) for L in loops])
    d = np.min(np.hypot(Q[:, 0][:, None] - bd[:, 0][None, :], Q[:, 1][:, None] - bd[:, 1][None, :]), axis=1)
    return Q[int(np.argmax(d))]


def draw_mesh(m, ax, color=(0.0, 0.447, 0.741), node_labels=False, elem_labels=False):
    """The mesh's element sides (curved sides by their midside nodes) as one line object."""
    t = m.t
    if m.order == 'quadratic':
        sides = [(0, 3, 1), (1, 4, 2), (2, 5, 0)]
    else:
        sides = [(0, 1), (1, 2), (2, 0)]
    seen = set()
    xs, ys = [], []
    for row in t:
        for sd in sides:
            key = (min(row[sd[0]], row[sd[-1]]), max(row[sd[0]], row[sd[-1]]))
            if key in seen:
                continue
            seen.add(key)
            idx = [row[s] for s in sd]
            xs += [m.p[i, 0] for i in idx] + [np.nan]
            ys += [m.p[i, 1] for i in idx] + [np.nan]
    _b('plot', ax, out(np.array(xs).reshape(-1, 1)), out(np.array(ys).reshape(-1, 1)), Char.of('Color'), out(np.array([color])))
    if node_labels:
        for k, (x, y) in enumerate(m.p):
            _b('text', ax, float(x), float(y), Char.of(f'n{k + 1}'), Char.of('FontSize'), 8.0)
    if elem_labels:
        for k, row in enumerate(t):
            c = m.p[row[:3]].mean(axis=0)
            _b('text', ax, float(c[0]), float(c[1]), Char.of(f'e{k + 1}'), Char.of('FontSize'), 8.0, Char.of('Color'), out(np.array([[0.6, 0.0, 0.0]])))


@bi('pdemesh')
def pdemesh(nargout, *args):
    """pdemesh(model), pdemesh(mesh), pdemesh(p, e, t), with 'NodeLabels', 'ElementLabels' 'on': the mesh drawn."""
    nargchk(args, 1, 7, 'pdemesh')
    rest = list(args[1:])
    if not isinstance(args[0], Obj) and len(args) >= 3 and not is_str(args[1]):
        p = np.asarray(darr(args[0]), float).T
        t = np.asarray(darr(args[2]), float)
        nt = 6 if t.shape[0] >= 6 and t.shape[0] != 4 else 3
        tt = t[:nt].T.astype(int) - 1
        m = Mesh(p, tt, t[-1].astype(int) if t.shape[0] in (4, 7) else np.ones(tt.shape[0], int), [], 0, 0, 'quadratic' if nt == 6 else 'linear')
        rest = list(args[3:])
    else:
        m = _femesh(args[0], 'pdemesh')
    o = _opts(rest, ('nodelabels', 'elementlabels'), 'pdemesh')
    ax = _b('gca')
    draw_mesh(m, ax, node_labels=_onoff(o, 'nodelabels'), elem_labels=_onoff(o, 'elementlabels'))
    _b('axis', ax, Char.of('equal'))
    return None

