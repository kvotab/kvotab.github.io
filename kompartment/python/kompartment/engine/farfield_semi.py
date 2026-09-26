"""The runtime of a far-field path worked out semi-analytically.

A port of ``LaplaceFarfPath`` in ``src/sim/farfield-laplace.js``, beside
:class:`~kompartment.engine.farfield.FarfPath` for the paths on cells. The
application's module says what is solved and why; in short:

* no cells: one state per nuclide (per combination of the block's other
  dimensions) for what the path holds, d(held)/dt = in - out - Lambda held;
* ``out``, the release, is the inflow's recorded history convolved with the
  path's unit responses (:mod:`kompartment.engine.farfield_laplace`), worked
  out once per run from the settings at its first instant;
* the history is recorded at every accepted step, output time and segment
  start, a cubic through the last four records between them; two records at
  one instant are a step, a jump of what is held between them an amount
  delivered at once;
* each recorded piece is kept as six moments about its centre, and pieces
  merge while they are narrow beside every response spacing they will still
  meet, so the history stays about as long as the response's grid;
* the step being taken (from the last record to the time asked about) is
  integrated exactly against the response, the current inflow's weight being
  the release's derivative along it (the Jacobian's).

The arithmetic follows the application's operation for operation, except that
the sum over the history is taken with numpy (one pass per response rather
than one loop per block), which orders the additions differently: the two agree
to rounding, not to the bit.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .farfield import FarfError
from .farfield_laplace import LaplacePathError, prepare_path, transfer_at_zero, unit_response

#: A merged block may be at most this fraction of the narrowest response
#: spacing it will still meet (``RHO``).
RHO = 0.5
#: Pairs that pass less than this fraction of what their source lets through at
#: most are left out.
NEGLIGIBLE = 1e-15

GL5_X = (-0.906179845938664, -0.5384693101056831, 0.0, 0.5384693101056831, 0.906179845938664)
GL5_W = (0.23692688505618908, 0.47862867049936647, 0.5688888888888889, 0.47862867049936647, 0.23692688505618908)

#: Binomial coefficients to 5, for shifting moments.
BINOM = ((1,), (1, 1), (1, 2, 1), (1, 3, 3, 1), (1, 4, 6, 4, 1), (1, 5, 10, 10, 5, 1))

#: What each setting is called in a message: the application's labels as text.
FARF_TEXT = {
    'tw': 'Tw', 'f': 'F', 'aw': 'aw', 'aperture': 'δ', 'kd_f': 'Kd,f', 'kd_m': 'Kd,m', 'de_m': 'De,m',
    'eps_m': 'εm', 'rho_m': 'ρm', 'pe': 'Pe', 'pen_dep': 'PENDEP', 'pen_dep_0': 'PENDEP0',
}

#: Unit responses by settings, shared by every path and every run in this process.
_RESPONSES: 'OrderedDict[str, Dict[str, Any]]' = OrderedDict()
_RESPONSES_KEEP = 32


def _js_precision(x: float, digits: int) -> str:
    """``Number(x).toPrecision(digits)``, as the application writes it."""
    if x != x:
        return 'NaN'
    if x in (math.inf, -math.inf):
        return 'Infinity' if x > 0 else '-Infinity'
    if x == 0:
        return '0.' + '0' * (digits - 1) if digits > 1 else '0'
    e = math.floor(math.log10(abs(x)))
    text = f'{x:.{digits - 1}e}'
    mant, exp = text.split('e')
    e = int(exp)
    if e < -6 or e >= digits:
        return f"{mant}e{'+' if e >= 0 else '-'}{abs(e)}"
    return f'{x:.{max(0, digits - 1 - e)}f}'


def clear_responses() -> None:
    """Forgets every response kept (``clearResponses``)."""
    _RESPONSES.clear()


def _response_key(settings: Dict[str, Any], D: Optional[Dict[str, Any]], span: float, nnuc: int) -> str:
    parts = [repr(float(span)), str(nnuc)]
    for key in sorted(settings):
        v = settings[key]
        if isinstance(v, (list, tuple, np.ndarray)):
            parts.append(f"{key}={','.join(repr(float(x)) for x in v)}")
        else:
            parts.append(f'{key}={v!r}')
    if D is not None:
        for name in ('lam', 'ioff', 'icnt', 'ipar', 'icoef'):
            parts.append(f"{name}={','.join(repr(float(x)) for x in D[name])}")
    return ';'.join(parts)


# --- one response, ready to convolve ---------------------------------------------------------

class Kernel:
    """A unit response as quintic pieces in the power basis of each piece, with
    their running moments and the narrowest spacing ahead of every lag."""

    __slots__ = ('t', 'tl', 'n', 'np', 'a', 'ahead', 'P', 't0', 't_end', 'T0', 'd', 'm0', 'tm0')

    def __init__(self, r: Dict[str, Any]) -> None:
        t = np.asarray(r['t'], dtype=float)
        n = t.size
        npc = max(0, n - 1)
        h = np.asarray(r['h'], dtype=float)
        dh = np.asarray(r['dh'], dtype=float)
        d2h = np.asarray(r['d2h'], dtype=float)
        a = np.zeros((npc, 6))
        if npc:
            d = t[1:] - t[:-1]
            ya = h[:-1]
            da = d * dh[:-1]
            ea = d * d * d2h[:-1]
            yb = h[1:]
            db = d * dh[1:]
            eb = d * d * d2h[1:]
            a[:, 0] = ya
            a[:, 1] = da
            a[:, 2] = 0.5 * ea
            a[:, 3] = -10 * ya - 6 * da - 1.5 * ea + 10 * yb - 4 * db + 0.5 * eb
            a[:, 4] = 15 * ya + 8 * da + 1.5 * ea - 15 * yb + 7 * db - eb
            a[:, 5] = -6 * ya - 3 * da - 0.5 * ea + 6 * yb - 3 * db + 0.5 * eb
            self.d = d
        else:
            self.d = np.zeros(0)
        ahead = np.full(npc + 1, math.inf)
        for k in range(npc - 1, -1, -1):
            ahead[k] = min(ahead[k + 1], t[k + 1] - t[k])
        self.t = t
        self.tl = t.tolist()
        self.n = n
        self.np = npc
        self.a = a
        self.ahead = ahead
        self.t0 = float(t[0]) if n else math.inf
        self.t_end = float(t[-1]) if n else -math.inf
        self.T0 = r.get('T0')
        # under plug flow, what arrives within a hair of the delay, as a point
        # mass at the first time: m0 times the inflow at t - tm0
        m0 = r.get('m0') or 0.0
        self.m0 = float(m0) if m0 > 0 and n else 0.0
        self.tm0 = float(t[0]) if n else math.inf
        P = [[0.0] * n for _ in range(4)]
        for k in range(npc):
            part = piece_moments(self, k, self.tl[k], self.tl[k + 1])
            for q in range(4):
                P[q][k + 1] = P[q][k] + part[q]
        self.P = P


def piece_at(kern: Kernel, u: float) -> int:
    """The piece that holds lag u, clamped to the grid."""
    t = kern.tl
    if u <= t[0]:
        return 0
    if u >= t[kern.np]:
        return kern.np - 1
    return bisect_right(t, u) - 1


def _poly(kern: Kernel, k: int, x: float) -> float:
    a = kern.a[k]
    return float(a[0] + x * (a[1] + x * (a[2] + x * (a[3] + x * (a[4] + x * a[5])))))


def kernel_at(kern: Kernel, u: float) -> float:
    """h at lag u, zero outside the tabulated span."""
    if not u >= kern.t0 or not u <= kern.t_end or kern.np < 1:
        return 0.0
    k = piece_at(kern, u)
    d = kern.tl[k + 1] - kern.tl[k]
    return _poly(kern, k, (u - kern.tl[k]) / d)


def piece_moments(kern: Kernel, k: int, ua: float, ub: float) -> List[float]:
    """integral of h(u) u^q over [ua, ub] inside piece k, q = 0..3."""
    out = [0.0, 0.0, 0.0, 0.0]
    if not ub > ua:
        return out
    t0 = kern.tl[k]
    d = kern.tl[k + 1] - t0
    a = kern.a[k].tolist()
    c = 0.5 * (ua + ub)
    hw = 0.5 * (ub - ua)
    for g in range(5):
        u = c + GL5_X[g] * hw
        x = (u - t0) / d
        h = a[0] + x * (a[1] + x * (a[2] + x * (a[3] + x * (a[4] + x * a[5]))))
        w = GL5_W[g] * hw * h
        out[0] += w
        out[1] += w * u
        out[2] += w * u * u
        out[3] += w * u * u * u
    return out


def running_moments(kern: Kernel, D: float) -> List[float]:
    """integral of h(u) u^q over [0, D], q = 0..3."""
    out = [0.0, 0.0, 0.0, 0.0]
    if not D > kern.t0 or kern.np < 1:
        return out
    top = min(D, kern.t_end)
    k = piece_at(kern, top)
    for q in range(4):
        out[q] = kern.P[q][k]
    rest = piece_moments(kern, k, kern.tl[k], top)
    for q in range(4):
        out[q] += rest[q]
    return out


def lag_basis(s: Sequence[float], count: int, D: float) -> List[List[float]]:
    """The Lagrange basis of the nodes ``s`` (lags, the last zero) as
    polynomials in x = u/D over the step."""
    coef = []
    for k in range(count):
        row = [0.0] * 5
        row[0] = 1.0
        deg = 0
        den = 1.0
        sk = s[k] / D
        for m in range(count):
            if m == k:
                continue
            sm = s[m] / D
            for q in range(deg + 1, 0, -1):
                row[q] = row[q - 1] - sm * row[q]
            row[0] = -sm * row[0]
            deg += 1
            den *= sk - sm
        for q in range(deg + 1):
            row[q] /= den
        coef.append(row)
    return coef


def shift(mu: Sequence[float], c: float, w: float, nc: float, nw: float) -> List[float]:
    """Moments about c scaled by w as moments about nc scaled by nw."""
    alpha = w / nw
    beta = (c - nc) / nw
    out = [0.0] * 6
    for m in range(6):
        s = 0.0
        for k in range(m + 1):
            s += BINOM[m][k] * alpha ** k * beta ** (m - k) * mu[k]
        out[m] = s
    return out


def direct(kern: Kernel, t: float, c: float, w: float, e: Sequence[float]) -> float:
    """A recorded piece integrated against the response directly."""
    u_lo = max(t - (c + w), kern.t0)
    u_hi = min(t - (c - w), kern.t_end)
    if not u_hi > u_lo:
        return 0.0
    k = piece_at(kern, u_lo)
    u = u_lo
    total = 0.0
    tl = kern.tl
    while u < u_hi and k < kern.np:
        nxt = min(u_hi, tl[k + 1])
        if nxt > u:
            t0 = tl[k]
            d = tl[k + 1] - t0
            a = kern.a[k].tolist()
            mid = 0.5 * (u + nxt)
            hw = 0.5 * (nxt - u)
            for g in range(5):
                uu = mid + GL5_X[g] * hw
                x = (uu - t0) / d
                h = a[0] + x * (a[1] + x * (a[2] + x * (a[3] + x * (a[4] + x * a[5]))))
                s = (t - uu - c) / w
                v = e[0] + s * (e[1] + s * (e[2] + s * e[3]))
                total += GL5_W[g] * hw * h * v
        u = nxt
        k += 1
    return total


def _from_moments(kern: Kernel, k: np.ndarray, uc: np.ndarray, w: np.ndarray, mu: np.ndarray) -> float:
    """Blocks by their moments against pieces k of the response (``fromMoments``),
    summed."""
    t0 = kern.t[k]
    d = kern.d[k]
    x = (uc - t0) / d
    a = kern.a[k]
    b0, b1, b2, b3, b4, b5 = a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]
    c5 = b5
    c4 = b4 + x * c5
    c3 = b3 + x * c4
    c2 = b2 + x * c3
    c1 = b1 + x * c2
    t0c = b0 + x * c1
    c4 = c4 + x * c5
    c3 = c3 + x * c4
    c2 = c2 + x * c3
    t1c = c1 + x * c2
    c4 = c4 + x * c5
    c3 = c3 + x * c4
    t2c = c2 + x * c3
    c4 = c4 + x * c5
    t3c = c3 + x * c4
    t4c = c4 + x * c5
    t5c = c5
    r = -w / d
    v = t0c * mu[:, 0] + r * (t1c * mu[:, 1] + r * (t2c * mu[:, 2] + r * (t3c * mu[:, 3] + r * (
        t4c * mu[:, 4] + r * t5c * mu[:, 5]))))
    return float(np.sum(v))


# --- the recorded inflow of one source -------------------------------------------------------

class Convolver:
    """The inflow of one source, recorded, and what it has put into the path
    (``Convolver``): blocks oldest first -- centre, half-width, six moments
    scaled by the half-width, and for a block still one recorded piece its
    cubic in s = (tau - c)/w."""

    def __init__(self, targets: List[Dict[str, Any]]) -> None:
        self.targets = targets
        self.reset()

    def reset(self) -> None:
        self.bc: List[float] = []
        self.bw: List[float] = []
        self.bm: List[List[float]] = []
        self.bp: List[Optional[List[float]]] = []
        self.rt: List[float] = []
        self.rv: List[float] = []
        self.last_t = -math.inf
        self.imp_t: List[float] = []
        self.imp_a: List[float] = []
        self.compact_at = 64
        self.count = 0
        self._arrays: Optional[tuple] = None

    def ahead(self, u: float) -> float:
        m = math.inf
        for tg in self.targets:
            kern = tg['kern']
            if u >= kern.t_end:
                continue
            d = kern.ahead[0] if u <= kern.t0 else kern.ahead[piece_at(kern, u)]
            if d < m:
                m = d
        return m

    def reach(self) -> float:
        m = -math.inf
        for tg in self.targets:
            if tg['kern'].t_end > m:
                m = tg['kern'].t_end
        return m

    def impulse(self, t: float, amount: float) -> None:
        if amount == 0 or not math.isfinite(amount):
            return
        self.imp_t.append(t)
        self.imp_a.append(amount)

    def push(self, t: float, v: float) -> None:
        self.count += 1
        if t == self.last_t:
            if v == self.rv[-1]:
                return
            self.rt = [t]
            self.rv = [v]
            return
        if t < self.last_t:
            raise RuntimeError('a far-field path was told about an earlier instant after a later one')
        if self.rt:
            self._piece(t, v)
        self.rt.append(t)
        self.rv.append(v)
        if len(self.rt) > 4:
            self.rt.pop(0)
            self.rv.pop(0)
        self.last_t = t
        if len(self.bc) > self.compact_at:
            self.compact(t)

    def _piece(self, t: float, v: float) -> None:
        nr = len(self.rt)
        ta = self.rt[nr - 1]
        c = 0.5 * (ta + t)
        w = 0.5 * (t - ta)
        count = min(nr + 1, 4)
        ns = [0.0] * count
        nv = [0.0] * count
        for k in range(count - 1):
            ns[k] = (self.rt[nr - (count - 1) + k] - c) / w
            nv[k] = self.rv[nr - (count - 1) + k]
        ns[count - 1] = 1.0
        nv[count - 1] = v
        e = [0.0, 0.0, 0.0, 0.0]
        for k in range(count):
            basis = [0.0] * 5
            basis[0] = 1.0
            deg = 0
            den = 1.0
            for m in range(count):
                if m == k:
                    continue
                for q in range(deg + 1, 0, -1):
                    basis[q] = basis[q - 1] - ns[m] * basis[q]
                basis[0] = -ns[m] * basis[0]
                deg += 1
                den *= ns[k] - ns[m]
            for q in range(deg + 1):
                e[q] += nv[k] * basis[q] / den
        mu = [0.0] * 6
        for m in range(6):
            s = 0.0
            for q in range(4):
                if (q + m) % 2 == 0:
                    s += e[q] * 2 / (q + m + 1)
            mu[m] = w * s
        self.bc.append(c)
        self.bw.append(w)
        self.bm.append(mu)
        self.bp.append(e)
        self._arrays = None

    def compact(self, t_now: float) -> None:
        reach = self.reach()
        bc: List[float] = []
        bw: List[float] = []
        bm: List[List[float]] = []
        bp: List[Optional[List[float]]] = []
        for k in range(len(self.bc)):
            c = self.bc[k]
            w = self.bw[k]
            if t_now - (c + w) > reach:
                continue
            mu = self.bm[k]
            p = self.bp[k]
            if bc:
                last = len(bc) - 1
                lo = bc[last] - bw[last]
                hi = c + w
                width = hi - lo
                if width <= RHO * self.ahead(t_now - hi):
                    nc = 0.5 * (lo + hi)
                    nw = 0.5 * width
                    merged = shift(bm[last], bc[last], bw[last], nc, nw)
                    mine = shift(mu, c, w, nc, nw)
                    for m in range(6):
                        merged[m] += mine[m]
                    bc[last] = nc
                    bw[last] = nw
                    bm[last] = merged
                    bp[last] = None
                    continue
            bc.append(c)
            bw.append(w)
            bm.append(mu)
            bp.append(p)
        self.bc, self.bw, self.bm, self.bp = bc, bw, bm, bp
        self.compact_at = 2 * len(bc) + 64
        self._arrays = None

    def _snapshot(self) -> tuple:
        if self._arrays is None:
            nb = len(self.bc)
            C = np.array(self.bc, dtype=float)
            Wd = np.array(self.bw, dtype=float)
            M = np.array(self.bm, dtype=float).reshape(nb, 6)
            single = np.array([p is not None for p in self.bp], dtype=bool)
            self._arrays = (C, Wd, M, single)
        return self._arrays

    def history(self, t: float, out: np.ndarray) -> None:
        """What the recorded history releases at t, added into ``out[i]`` for
        each target."""
        if not self.targets:
            return
        nb = len(self.bc)
        C, Wd, M, single = self._snapshot() if nb else (None, None, None, None)
        for tg in self.targets:
            kern = tg['kern']
            npc = kern.np
            if npc < 1:
                continue
            total = 0.0
            if nb:
                uc = t - C
                keep = (uc + Wd > kern.t0) & (uc - Wd < kern.t_end)
                if keep.any():
                    young = uc - Wd
                    wide = np.zeros(nb, dtype=bool)
                    cand = keep & single
                    if cand.any():
                        ka = np.clip(np.searchsorted(kern.t, young[cand], side='right') - 1, 0, npc - 1)
                        spacing = np.where(young[cand] <= kern.t0, kern.ahead[0], kern.ahead[ka])
                        wide[cand] = 2 * Wd[cand] > RHO * spacing
                    moments = keep & ~wide
                    if moments.any():
                        u = uc[moments]
                        k = np.clip(np.searchsorted(kern.t, u, side='right') - 1, 0, npc - 1)
                        total += _from_moments(kern, k, u, Wd[moments], M[moments])
                    for b in np.nonzero(wide)[0].tolist():
                        total += direct(kern, t, self.bc[b], self.bw[b], self.bp[b])  # type: ignore[arg-type]
            for r in range(len(self.imp_t)):
                total += self.imp_a[r] * kernel_at(kern, t - self.imp_t[r])
            out[tg['i']] += total


def step_weights(cv: Convolver, t: float) -> List[Dict[str, Any]]:
    """The step from a source's last record to t, for each target: the weights
    of the cubic's nodes (``stepWeights``)."""
    out: List[Dict[str, Any]] = []
    nr = len(cv.rt)
    D = t - cv.last_t
    if not cv.targets or not nr or not D > 0:
        return out
    count = min(nr + 1, 4)
    s = [0.0] * count
    for k in range(count - 1):
        s[k] = t - cv.rt[nr - (count - 1) + k]
    s[count - 1] = 0.0
    coef = None
    for tg in cv.targets:
        kern = tg['kern']
        if not D > kern.t0:
            continue
        if coef is None:
            coef = lag_basis(s, count, D)
        mom = running_moments(kern, D)
        Dq = 1.0
        for q in range(1, 4):
            Dq *= D
            mom[q] /= Dq
        w = [0.0] * count
        for k in range(count):
            v = 0.0
            for q in range(count):
                v += coef[k][q] * mom[q]
            w[k] = v
        out.append({'i': tg['i'], 'w': w, 'count': count, 'nr': nr})
    return out


def point_parts(cv: Convolver, t: float) -> List[Dict[str, Any]]:
    """The point masses whose lag puts them inside the step being taken
    (``pointParts``): node weights like the step's own."""
    out: List[Dict[str, Any]] = []
    nr = len(cv.rt)
    if not nr:
        return out
    for tg in cv.targets:
        kern = tg['kern']
        if not kern.m0 > 0:
            continue
        tau = t - kern.tm0
        if not tau > cv.last_t:
            continue
        count = min(nr + 1, 4)
        nodes = [cv.rt[nr - (count - 1) + k] for k in range(count - 1)] + [t]
        w = [0.0] * count
        for k in range(count):
            lk = 1.0
            for m in range(count):
                if m != k:
                    lk *= (tau - nodes[m]) / (nodes[k] - nodes[m])
            w[k] = kern.m0 * lk
        out.append({'i': tg['i'], 'w': w, 'count': count, 'nr': nr})
    return out


def step_sum(cv: Convolver, part: Dict[str, Any], v: float) -> float:
    """The step's contribution: its node weights against the records and the
    current inflow ``v``."""
    w, count, nr = part['w'], part['count'], part['nr']
    r = w[count - 1] * v
    for k in range(count - 1):
        r += w[k] * cv.rv[nr - (count - 1) + k]
    return r


# --- the path --------------------------------------------------------------------------------

class LaplaceFarfPath:
    """One far-field block worked out semi-analytically (``LaplaceFarfPath``)."""

    method = 'semi-analytical'

    def __init__(self, *, base: int, nnuc: int, other_width: int, dim_off: np.ndarray, single_off: np.ndarray,
                 setting_base: Dict[str, int], keys: Sequence[str], single: Sequence[str], surface: str,
                 release_base: int, span: float, names: Optional[Sequence[str]] = None,
                 block_name: str = '') -> None:
        self.base = base
        self.nnuc = nnuc
        self.other_width = other_width
        self.dim_off = np.asarray(dim_off, dtype=np.int64)
        self.single_off = np.asarray(single_off, dtype=np.int64)
        self.setting_base = dict(setting_base)
        self.keys = list(keys)
        self.is_single = set(single)
        self.surface = surface or 'f'
        self.release_base = release_base
        self.span = float(span)
        self.names = list(names) if names is not None else None
        self.block_name = block_name
        self.ncells = 1
        self.slots = other_width * nnuc
        self.release_slots = (release_base + self.dim_off).astype(np.int64)
        self.held_idx = base + np.arange(self.slots, dtype=np.int64)
        self.cell_starts = base + np.arange(other_width, dtype=np.int64) * nnuc
        self.D: Optional[Dict[str, Any]] = None
        self.in_tgt = np.zeros(0, dtype=np.int64)
        self.in_rate = np.zeros(0, dtype=np.int64)
        self.in_donor = np.zeros(0, dtype=np.int64)
        self._has_donor = np.zeros(0, dtype=bool)
        self._donor_at = np.zeros(0, dtype=np.int64)
        self.terms_into: List[List[tuple]] = [[] for _ in range(self.slots)]
        self.IN = np.zeros(self.slots)
        self.held = np.zeros(self.slots)
        self.last_held = np.zeros(self.slots)
        self.records: List[Dict[str, list]] = [{'t': [], 'v': []} for _ in range(self.slots)]
        self.impulses: List[Dict[str, list]] = [{'t': [], 'v': []} for _ in range(self.slots)]
        self.combos: List[Optional[Dict[str, Any]]] = [None] * other_width
        self.live: Optional[List[Convolver]] = None
        self.sweep: Optional[List[Convolver]] = None
        self.sweep_at = -math.inf
        self.sweep_next = 0
        self.sweep_imp = [0] * self.slots
        self.releases: Dict[float, np.ndarray] = {}
        self.last_t = -math.inf
        self.hist_t = math.nan
        self.hist_vals = np.zeros(self.slots)
        self.weight_t = math.nan
        self.weights: Optional[Dict[str, Any]] = None
        self.ready = False
        self.stats = {'evaluations': 0, 'blocks': 0, 'pairs': 0, 'response_ms': 0.0}

    # --- set up -------------------------------------------------------------------------

    def set_decay(self, lam: Any, table: Optional[Dict[str, Any]] = None) -> None:
        """The decay table the path's nuclides decay with, or None for none."""
        self.D = table
        self.restart()

    def set_inflow(self, tgt: np.ndarray, rate: np.ndarray, donor: np.ndarray) -> None:
        """What the model's fluxes deliver into each slot: ``IN[tgt] +=
        X[rate]`` times ``y[donor]`` where the donor is not -1."""
        self.in_tgt = np.asarray(tgt, dtype=np.int64)
        self.in_rate = np.asarray(rate, dtype=np.int64)
        self.in_donor = np.asarray(donor, dtype=np.int64)
        self._has_donor = self.in_donor >= 0
        self._donor_at = np.where(self._has_donor, self.in_donor, 0)
        self.terms_into: List[List[tuple]] = [[] for _ in range(self.slots)]
        for q, x, d in zip(self.in_tgt.tolist(), self.in_rate.tolist(), self.in_donor.tolist()):
            self.terms_into[q].append((x, d))

    def restart(self) -> None:
        """Starts a run: responses from the settings at its first instant, an
        empty history."""
        self.ready = False
        self.live = None
        self.sweep = None
        self.sweep_at = -math.inf
        self.releases = {}
        self.last_t = -math.inf
        self.hist_t = math.nan
        self.weight_t = math.nan
        for h in self.records + self.impulses:
            h['t'] = []
            h['v'] = []

    def _at(self, key: str, o: int, off: int) -> int:
        one = int(self.single_off[o]) if self.single_off.size else 0
        return self.setting_base[key] + (one if key in self.is_single else off)

    def settings_of(self, X: np.ndarray, o: int) -> Dict[str, Any]:
        s: Dict[str, Any] = {'surface': self.surface}
        n = self.nnuc
        for key in self.keys:
            if key in self.is_single:
                s[key] = float(X[self._at(key, o, int(self.dim_off[o * n]))])
            else:
                s[key] = [float(X[self._at(key, o, int(self.dim_off[o * n + m]))]) for m in range(n)]
        return s

    def prepare(self, X: np.ndarray) -> None:
        """The unit responses of every combination, from the settings in X;
        :class:`FarfError` with the reason for what the method cannot solve."""
        import time
        started = time.perf_counter()
        pairs = 0
        for o in range(self.other_width):
            settings = self.settings_of(X, o)
            key = _response_key(settings, self.D, self.span, self.nnuc)
            combo = _RESPONSES.get(key)
            if combo is not None:
                _RESPONSES.move_to_end(key)
            else:
                combo = self._responses(settings)
                _RESPONSES[key] = combo
                while len(_RESPONSES) > _RESPONSES_KEEP:
                    _RESPONSES.popitem(last=False)
            self.combos[o] = combo
            pairs += combo['pairs']
        self.stats['response_ms'] += (time.perf_counter() - started) * 1000
        self.stats['pairs'] = pairs
        self.ready = True
        self.live = self._convolvers()

    def _responses(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        try:
            path = prepare_path(settings, self.D, n=self.nnuc, names=self.names)
        except LaplacePathError as e:
            raise FarfError(str(e)) from None
        n = self.nnuc
        T0 = transfer_at_zero(path)
        kernels: List[Optional[Kernel]] = [None] * (n * n)
        misses: List[Dict[str, Any]] = []
        pairs = 0
        for j in range(n):
            most = 0.0
            for i in range(n):
                if T0[i * n + j] > most:
                    most = T0[i * n + j]
            for i in range(n):
                if not path.reach[j][i]:
                    continue
                T = T0[i * n + j]
                if not T > NEGLIGIBLE * most or not T > 1e-300:
                    continue
                r = unit_response(path, i, j, kind='release', t_max=self.span)
                if r.get('balanced') is False:
                    misses.append({'i': i, 'j': j, 'integral': r['integral'], 'expected': r['expected'],
                                   'T0': r['T0'], 'rel': r['rel'], 'until': r['t'][-1] if len(r['t']) else math.nan})
                if len(r['t']) < 2:
                    continue
                kernels[i * n + j] = Kernel(r)
                pairs += 1
        return {'kernels': kernels, 'pairs': pairs, 'misses': misses}

    def balance_warnings(self) -> List[Dict[str, str]]:
        """Every unit response that missed its mass balance, ``{block,
        message}`` (``balanceWarnings``): never a quiet shortfall."""
        out: List[Dict[str, str]] = []

        def p4(x: float) -> str:
            return _js_precision(x, 4)

        def name(k: int) -> str:
            return self.names[k] if self.names else f'#{k + 1}'

        for o, combo in enumerate(self.combos):
            for m in (combo or {}).get('misses', []):
                where = f' (index combination {o + 1} of {self.other_width})' if self.other_width > 1 else ''
                out.append({'block': self.block_name,
                            'message': f"the unit response of {name(m['i'])} to {name(m['j'])}{where} integrates to "
                                       f"{p4(m['integral'])}, but {p4(m['expected'])} of a pulse leaves the path by "
                                       f"{p4(m['until'])} (T(0) = {p4(m['T0'])}): the inversion failed there, and the "
                                       'release worked out from it is not reliable'})
        return out

    def _convolvers(self) -> List[Convolver]:
        n = self.nnuc
        out: List[Convolver] = []
        for o in range(self.other_width):
            kernels = self.combos[o]['kernels']  # type: ignore[index]
            for j in range(n):
                targets = [{'i': o * n + i, 'kern': kernels[i * n + j]} for i in range(n)
                           if kernels[i * n + j] is not None]
                out.append(Convolver(targets))
        return out

    # --- the release --------------------------------------------------------------------

    def inflow(self, y: np.ndarray, X: np.ndarray) -> np.ndarray:
        """What the model's fluxes deliver into every slot at (y, X)."""
        IN = self.IN
        IN.fill(0.0)
        if self.in_tgt.size:
            vals = np.where(self._has_donor, y[self._donor_at], 1.0) * X[self.in_rate]
            np.add.at(IN, self.in_tgt, vals)
        return IN

    def _weights(self, t: float) -> Dict[str, Any]:
        if t == self.weight_t and self.weights is not None:
            return self.weights
        n = self.nnuc
        W: Dict[str, Any] = {'cur': np.zeros(self.slots * n), 'parts': []}
        if self.live is not None and t > self.last_t:
            for slot in range(self.slots):
                for part in step_weights(self.live[slot], t) + point_parts(self.live[slot], t):
                    part['slot'] = slot
                    W['parts'].append(part)
                    W['cur'][part['i'] * n + (slot % n)] += part['w'][part['count'] - 1]
        self.weights = W
        self.weight_t = t
        return W

    def current_weights(self, t: float) -> np.ndarray:
        """The weight of each source's current inflow in each target's release
        at t: ``cur[slot * n + j]`` (the release's derivative along it)."""
        return self._weights(t)['cur']

    def release(self, y: np.ndarray, X: np.ndarray, t: float = math.nan) -> None:
        """The release of every slot at t, into its algebraic slots."""
        if not self.ready:
            self.prepare(X)
        self.stats['evaluations'] += 1
        t = float(t)
        kept = self.releases.get(t)
        if kept is not None:
            X[self.release_slots] = kept
            return
        recorded = self.records[0]['t'] if self.records else []
        last_recorded = recorded[-1] if recorded else -math.inf
        if t < last_recorded or (recorded and self.last_t == -math.inf):
            self._behind(y, X, t)
            return
        hist = self.hist_vals
        if t != self.hist_t:
            hist.fill(0.0)
            if self.live is not None:
                for slot in range(self.slots):
                    self.live[slot].history(t, hist)
                    self._points_behind(self.live[slot], slot, t, hist)
            self.hist_t = t
        IN = self.inflow(y, X)
        W = self._weights(t)
        res = hist.copy()
        for part in W['parts']:
            res[part['i']] += step_sum(self.live[part['slot']], part, float(IN[part['slot']]))  # type: ignore[index]
        X[self.release_slots] = res

    def _behind(self, y: np.ndarray, X: np.ndarray, t: float) -> None:
        """The release at an earlier instant than the last record: swept
        forward from the records again."""
        if self.sweep is None or t < self.sweep_at:
            self.sweep = self._convolvers()
            self.sweep_at = -math.inf
            self.sweep_next = 0
            self.sweep_imp = [0] * self.slots
        times = self.records[0]['t']
        while self.sweep_next < len(times) and times[self.sweep_next] <= t:
            q = self.sweep_next
            self.sweep_next += 1
            for slot in range(self.slots):
                rec = self.records[slot]
                self.sweep[slot].push(rec['t'][q], rec['v'][q])
        for slot in range(self.slots):
            imp = self.impulses[slot]
            cv = self.sweep[slot]
            while self.sweep_imp[slot] < len(imp['t']) and imp['t'][self.sweep_imp[slot]] <= t:
                q = self.sweep_imp[slot]
                self.sweep_imp[slot] += 1
                cv.impulse(imp['t'][q], imp['v'][q])
        self.sweep_at = t
        out = np.zeros(self.slots)
        for slot in range(self.slots):
            self.sweep[slot].history(t, out)
            self._points_behind(self.sweep[slot], slot, t, out)
        IN = self.inflow(y, X)
        for slot in range(self.slots):
            cv = self.sweep[slot]
            for part in step_weights(cv, t) + point_parts(cv, t):
                out[part['i']] += step_sum(cv, part, float(IN[slot]))
        X[self.release_slots] = out

    def _points_behind(self, cv: Convolver, slot: int, t: float, out: np.ndarray) -> None:
        """The point masses whose lag reaches back into the recorded history."""
        for tg in cv.targets:
            kern = tg['kern']
            if not kern.m0 > 0:
                continue
            tau = t - kern.tm0
            if tau > cv.last_t:
                continue
            out[tg['i']] += kern.m0 * self._recorded_inflow(slot, tau)

    def _recorded_inflow(self, slot: int, tau: float) -> float:
        """What flowed into ``slot`` at the earlier instant tau: the cubic the
        history holds there (``_recordedInflow``)."""
        T = self.records[0]['t']
        V = self.records[slot]['v']
        n = len(T)
        if not n or not tau >= T[0]:
            return 0.0
        if tau >= T[n - 1]:
            return V[n - 1]
        lo = 0
        hi = n - 1
        while hi - lo > 1:
            c = (lo + hi) >> 1
            if T[c] <= tau:
                lo = c
            else:
                hi = c
        b = lo + 1
        first = b
        while first > 0 and b - first < 3 and T[first - 1] < T[first]:
            first -= 1
        v = 0.0
        for k in range(first, b + 1):
            lk = 1.0
            for m in range(first, b + 1):
                if m != k:
                    lk *= (tau - T[m]) / (T[k] - T[m])
            v += lk * V[k]
        return v

    # --- the history ----------------------------------------------------------------------

    def prime(self, t0: float, y0: np.ndarray, X: np.ndarray) -> None:
        """Puts the history back to the start of a run and records its first instant."""
        if not self.ready:
            self.prepare(X)
        for h in self.records + self.impulses:
            h['t'] = []
            h['v'] = []
        self.live = self._convolvers()
        self.sweep = None
        self.releases = {}
        self.last_t = -math.inf
        self.hist_t = math.nan
        self.weight_t = math.nan
        self.store(t0, y0, X)

    def store(self, t: float, y: np.ndarray, X: np.ndarray) -> None:
        """Records an instant the solver has told the model about."""
        if not self.ready:
            self.prepare(X)
        if self.live is None:
            self.live = self._convolvers()
        t = float(t)
        if t < self.last_t:
            self._truncate(t)
        IN = self.inflow(y, X)
        held = self.held
        held[:] = y[self.held_idx]
        same = t == self.last_t
        record = not same
        if same:
            for slot in range(self.slots):
                amount = float(held[slot] - self.last_held[slot])
                if amount != 0:
                    self.live[slot].impulse(t, amount)
                    self.impulses[slot]['t'].append(t)
                    self.impulses[slot]['v'].append(amount)
                rec = self.records[slot]
                if float(IN[slot]) != rec['v'][-1]:
                    record = True
        if record:
            for slot in range(self.slots):
                rec = self.records[slot]
                v = float(IN[slot])
                rec['t'].append(t)
                rec['v'].append(v)
                self.live[slot].push(t, v)
        if t not in self.releases:
            self.releases[t] = X[self.release_slots].copy()
        self.last_held[:] = held
        self.last_t = t
        self.hist_t = math.nan
        self.weight_t = math.nan
        self.stats['blocks'] = sum(len(cv.bc) for cv in self.live)

    def _truncate(self, t: float) -> None:
        """Forgets everything recorded after t."""
        for h in self.records + self.impulses:
            k = len(h['t'])
            while k > 0 and h['t'][k - 1] > t:
                k -= 1
            del h['t'][k:]
            del h['v'][k:]
        for key in [k for k in self.releases if k > t]:
            del self.releases[key]
        self.live = self._convolvers()
        times = self.records[0]['t']
        for q in range(len(times)):
            for slot in range(self.slots):
                rec = self.records[slot]
                self.live[slot].push(rec['t'][q], rec['v'][q])
        for slot in range(self.slots):
            imp = self.impulses[slot]
            for q in range(len(imp['t'])):
                self.live[slot].impulse(imp['t'][q], imp['v'][q])
        self.last_t = times[-1] if times else -math.inf

    def run_state(self) -> Dict[str, Any]:
        """What a run leaves on the path that reading its results depends on."""
        return {'records': [{'t': list(h['t']), 'v': list(h['v'])} for h in self.records],
                'impulses': [{'t': list(h['t']), 'v': list(h['v'])} for h in self.impulses],
                'releases': {k: v.tolist() for k, v in self.releases.items()}}

    def restore_run_state(self, state: Dict[str, Any]) -> None:
        """A run's history (from :meth:`run_state`) back on the path: the
        results are read from it as from the run's own."""
        self.records = [{'t': list(h['t']), 'v': list(h['v'])} for h in state['records']]
        self.impulses = [{'t': list(h['t']), 'v': list(h['v'])} for h in state['impulses']]
        self.releases = {float(k): np.asarray(v, dtype=float) for k, v in state['releases'].items()}
        self.sweep = None
        self.sweep_at = -math.inf
        self.last_t = -math.inf
        self.live = None
        self.hist_t = math.nan
        self.weight_t = math.nan

    # --- the Jacobian ---------------------------------------------------------------------

    def release_dependencies(self, of_x: Any) -> List[np.ndarray]:
        """For each release slot, the states it depends on: what the inflow into
        the same combination reads, since the step being taken carries it
        with a weight (``releasePattern``)."""
        n = self.nnuc
        out: List[np.ndarray] = []
        empty = np.zeros(0, dtype=np.int64)
        per_o: List[np.ndarray] = []
        for o in range(self.other_width):
            parts: List[np.ndarray] = [empty]
            for j in range(n):
                for x, d in self.terms_into[o * n + j]:
                    if d >= 0:
                        parts.append(np.array([d], dtype=np.int64))
                    parts.append(of_x(int(x)))
            per_o.append(np.unique(np.concatenate(parts)))
        for slot in range(self.slots):
            out.append(per_o[slot // n])
        return out
