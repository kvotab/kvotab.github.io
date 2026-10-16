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
to rounding, not to the bit. With numba installed, the recording and merging of
pieces, the sum over the history and the step being taken run as compiled
kernels instead (``_nb_*`` below), each a call for every source of the path at
once: twins of the Python and numpy path to the bit, whichever path the run
takes. A run of the far-field example worked out this way is eighteen times
quicker.
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


# --- the history sum, compiled ---------------------------------------------------------------
#
# What `Convolver.history` adds up for one target, with numba: the same arithmetic in the
# same order -- each block by its moments (`_from_moments`), those summed as numpy sums
# them (pairwise, `_nb_pairwise`), then the wide single pieces directly (`direct`), then
# the point impulses (`kernel_at`). numba does not fuse a multiply and an add, so every
# rounding is the numpy path's and the answer is the same to the bit. A model whose far
# field is most of its run spends it here, most of it, run as Python, in `direct`.

def _nb_block(v: Any, lo: int, n: int) -> float:
    """numpy's pairwise sum of ``v[lo:lo + n]`` for n <= 128: a plain loop below eight
    terms, eight accumulators from there."""
    if n < 8:
        res = 0.0
        for i in range(n):
            res += v[lo + i]
        return res
    r0 = v[lo]
    r1 = v[lo + 1]
    r2 = v[lo + 2]
    r3 = v[lo + 3]
    r4 = v[lo + 4]
    r5 = v[lo + 5]
    r6 = v[lo + 6]
    r7 = v[lo + 7]
    i = 8
    stop = n - (n % 8)
    while i < stop:
        r0 += v[lo + i]
        r1 += v[lo + i + 1]
        r2 += v[lo + i + 2]
        r3 += v[lo + i + 3]
        r4 += v[lo + i + 4]
        r5 += v[lo + i + 5]
        r6 += v[lo + i + 6]
        r7 += v[lo + i + 7]
        i += 8
    res = ((r0 + r1) + (r2 + r3)) + ((r4 + r5) + (r6 + r7))
    while i < n:
        res += v[lo + i]
        i += 1
    return res


def _nb_pairwise(v: Any, lo: int, n: int) -> float:
    """numpy's pairwise summation of ``v[lo:lo + n]`` (``pairwise_sum_DOUBLE``): blocks
    of up to 128 terms, and above that the two halves summed and added -- the same tree,
    walked with a stack rather than by recursion, which numba's cache does not keep."""
    if n <= 128:
        return _nb_block(v, lo, n)
    # A frame a node: 0 not yet split, 1 waiting for its left half, 2 for its right.
    s_lo = np.empty(64, dtype=np.int64)
    s_n = np.empty(64, dtype=np.int64)
    s_state = np.empty(64, dtype=np.int64)
    s_left = np.empty(64)
    top = 0
    s_lo[0] = lo
    s_n[0] = n
    s_state[0] = 0
    val = 0.0
    done = False
    while top >= 0:
        if done:
            if s_state[top] == 1:
                s_left[top] = val
                s_state[top] = 2
                half = s_n[top] // 2
                half -= half % 8
                done = False
                top += 1
                s_lo[top] = s_lo[top - 1] + half
                s_n[top] = s_n[top - 1] - half
                s_state[top] = 0
            else:
                val = s_left[top] + val
                top -= 1
            continue
        m = s_n[top]
        if m <= 128:
            val = _nb_block(v, s_lo[top], m)
            done = True
            top -= 1
            continue
        half = m // 2
        half -= half % 8
        s_state[top] = 1
        top += 1
        s_lo[top] = s_lo[top - 1]
        s_n[top] = half
        s_state[top] = 0
    return val


def _nb_count(t: Any, u: float) -> int:
    """``np.searchsorted(t, u, side='right')``: how many of t are <= u, NaN last."""
    n = t.shape[0]
    if u != u:
        return n
    lo = 0
    hi = n
    while lo < hi:
        mid = (lo + hi) >> 1
        if t[mid] <= u:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _nb_walk(t: Any, u: float, cnt: int) -> int:
    """``_nb_count`` for a lag no later than the one ``cnt`` counted for: walked down
    from there rather than searched for -- or searched for, the first time (``cnt <
    0``). A source's blocks are oldest first, so the lags they are read at only fall."""
    if cnt < 0 or u != u:
        return _nb_count(t, u)
    while cnt > 0 and t[cnt - 1] > u:
        cnt -= 1
    return cnt


def _nb_piece_at(t: Any, npc: int, u: float) -> int:
    """``piece_at``."""
    if u <= t[0]:
        return 0
    if u >= t[npc]:
        return npc - 1
    return _nb_count(t, u) - 1


def _nb_kernel_at(t: Any, a: Any, npc: int, t0: float, t_end: float, u: float) -> float:
    """``kernel_at``."""
    if not u >= t0 or not u <= t_end or npc < 1:
        return 0.0
    k = _nb_piece_at(t, npc, u)
    d = t[k + 1] - t[k]
    x = (u - t[k]) / d
    return a[k, 0] + x * (a[k, 1] + x * (a[k, 2] + x * (a[k, 3] + x * (a[k, 4] + x * a[k, 5]))))


def _nb_direct(t: Any, a: Any, npc: int, t0k: float, t_endk: float, tt: float, c: float, w: float,
               e0: float, e1: float, e2: float, e3: float) -> float:
    """``direct``: Python's max and min kept as they choose."""
    lo_ = tt - (c + w)
    u_lo = t0k if t0k > lo_ else lo_
    hi_ = tt - (c - w)
    u_hi = t_endk if t_endk < hi_ else hi_
    if not u_hi > u_lo:
        return 0.0
    k = _nb_piece_at(t, npc, u_lo)
    u = u_lo
    total = 0.0
    while u < u_hi and k < npc:
        top = t[k + 1]
        nxt = top if top < u_hi else u_hi
        if nxt > u:
            t0 = t[k]
            d = t[k + 1] - t0
            a0 = a[k, 0]
            a1 = a[k, 1]
            a2 = a[k, 2]
            a3 = a[k, 3]
            a4 = a[k, 4]
            a5 = a[k, 5]
            mid = 0.5 * (u + nxt)
            hw = 0.5 * (nxt - u)
            for g in range(5):
                uu = mid + GL5_X[g] * hw
                x = (uu - t0) / d
                h = a0 + x * (a1 + x * (a2 + x * (a3 + x * (a4 + x * a5))))
                ss = (tt - uu - c) / w
                v = e0 + ss * (e1 + ss * (e2 + ss * e3))
                total += GL5_W[g] * hw * h * v
        u = nxt
        k += 1
    return total


def _nb_from_moment(t: Any, dk: Any, a: Any, k: int, uc: float, w: float, M: Any, b: int) -> float:
    """One block's term of ``_from_moments``, before the sum."""
    t0 = t[k]
    d = dk[k]
    x = (uc - t0) / d
    b0 = a[k, 0]
    b1 = a[k, 1]
    b2 = a[k, 2]
    b3 = a[k, 3]
    b4 = a[k, 4]
    b5 = a[k, 5]
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
    return t0c * M[b, 0] + r * (t1c * M[b, 1] + r * (t2c * M[b, 2] + r * (t3c * M[b, 3] + r * (
        t4c * M[b, 4] + r * t5c * M[b, 5]))))


def _nb_history(tt: float, C: Any, Wd: Any, M: Any, S: Any, E: Any, nb: int, t: Any, dk: Any, a: Any,
                ahead: Any, npc: int, t0k: float, t_endk: float, imp_t: Any, imp_a: Any, v: Any,
                wide: Any) -> float:
    """What the history releases at ``tt`` into one target, as ``Convolver.history`` adds it up."""
    total = 0.0
    if nb > 0:
        nv = 0
        nw = 0
        anykeep = False
        c_young = -1
        c_uc = -1
        for b in range(nb):
            uc = tt - C[b]
            w = Wd[b]
            if not ((uc + w > t0k) and (uc - w < t_endk)):
                continue
            anykeep = True
            if S[b]:
                young = uc - w
                c_young = _nb_walk(t, young, c_young)
                ka = c_young - 1
                ka = 0 if ka < 0 else (npc - 1 if ka > npc - 1 else ka)
                spacing = ahead[0] if young <= t0k else ahead[ka]
                if 2 * w > RHO * spacing:
                    wide[nw] = b
                    nw += 1
                    continue
            c_uc = _nb_walk(t, uc, c_uc)
            k = c_uc - 1
            k = 0 if k < 0 else (npc - 1 if k > npc - 1 else k)
            v[nv] = _nb_from_moment(t, dk, a, k, uc, w, M, b)
            nv += 1
        if anykeep:
            if nv > 0:
                total += 0.0 + _nb_pairwise(v, 0, nv)
            for j in range(nw):
                b = wide[j]
                total += _nb_direct(t, a, npc, t0k, t_endk, tt, C[b], Wd[b], E[b, 0], E[b, 1], E[b, 2], E[b, 3])
    for r in range(imp_t.shape[0]):
        total += imp_a[r] * _nb_kernel_at(t, a, npc, t0k, t_endk, tt - imp_t[r])
    return total


# --- a source's records and the step, compiled -----------------------------------------------
#
# What `Convolver.push` and `Convolver.compact` do to the records and the blocks, and the
# step being taken (`step_weights`, `point_parts`, `step_sum`), with numba, in the same
# order: twins of the Python below them, as the history's kernel is of `history`. A path's
# sources are rows of one `_Sources` -- last records, blocks, impulses -- so that one call
# records an instant for every source, sums every history, and works out the step.

#: ``BINOM`` as an array, for ``_nb_shift``.
_BINOM = np.array([[float(BINOM[m][k]) if k <= m else 0.0 for k in range(6)] for m in range(6)])
#: The exponents 0..5, handed to ``_nb_compact`` rather than written in it: a power
#: whose exponent is known when it is compiled can be turned into multiplications (x**2
#: into x*x), and Python takes every one from the C library's pow.
_POWERS = np.arange(6.0)


def _nb_piece(rt: Any, rv: Any, nr: int, t: float, v: float, C: Any, W: Any, M: Any, S: Any, E: Any,
              b: int) -> None:
    """``Convolver._piece``: the cubic through the last records (``nr`` of them in ``rt``,
    ``rv``) and ``v`` at ``t``, put in as block b."""
    ta = rt[nr - 1]
    c = 0.5 * (ta + t)
    w = 0.5 * (t - ta)
    count = nr + 1 if nr < 3 else 4
    ns = np.empty(4)
    nv = np.empty(4)
    for k in range(count - 1):
        ns[k] = (rt[nr - (count - 1) + k] - c) / w
        nv[k] = rv[nr - (count - 1) + k]
    ns[count - 1] = 1.0
    nv[count - 1] = v
    e = np.zeros(4)
    basis = np.empty(5)
    for k in range(count):
        for q in range(5):
            basis[q] = 0.0
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
    for m in range(6):
        s = 0.0
        for q in range(4):
            if (q + m) % 2 == 0:
                s += e[q] * 2 / (q + m + 1)
        M[b, m] = w * s
    C[b] = c
    W[b] = w
    S[b] = True
    for q in range(4):
        E[b, q] = e[q]


def _nb_ahead(u: float, KT: Any, KH: Any, KOT: Any, KN: Any, KT0: Any, KTE: Any, j0: int, j1: int) -> float:
    """``Convolver.ahead`` over targets j0 to j1 of ``_Sources``."""
    m = math.inf
    for j in range(j0, j1):
        if u >= KTE[j]:
            continue
        if u <= KT0[j]:
            d = KH[KOT[j]]
        else:
            npc = KN[j]
            d = KH[KOT[j] + _nb_piece_at(KT[KOT[j]:KOT[j] + npc + 1], npc, u)]
        if d < m:
            m = d
    return m


def _nb_shift(M: Any, b: int, c: float, w: float, nc: float, nw: float, K: Any, out: Any, at: int) -> None:
    """``shift`` of block b's moments, into ``out[at:at + 6]``."""
    alpha = w / nw
    beta = (c - nc) / nw
    for m in range(6):
        s = 0.0
        for k in range(m + 1):
            s += _BINOM[m, k] * math.pow(alpha, K[k]) * math.pow(beta, K[m - k]) * M[b, k]
        out[at + m] = s


def _nb_compact(t_now: float, reach: float, CC: Any, WW: Any, MM: Any, SS: Any, EE: Any, N: Any, s: int, KT: Any,
                KH: Any, KOT: Any, KN: Any, KT0: Any, KTE: Any, j0: int, j1: int, K: Any, out: Any) -> int:
    """``Convolver.compact`` on source s, its targets j0 to j1: how many blocks are left."""
    C = CC[s]
    W = WW[s]
    M = MM[s]
    S = SS[s]
    E = EE[s]
    nb = N[s]
    n = 0
    for k in range(nb):
        c = C[k]
        w = W[k]
        if t_now - (c + w) > reach:
            continue
        if n > 0:
            last = n - 1
            lc = C[last]
            lw = W[last]
            lo = lc - lw
            hi = c + w
            width = hi - lo
            if width <= RHO * _nb_ahead(t_now - hi, KT, KH, KOT, KN, KT0, KTE, j0, j1):
                nc = 0.5 * (lo + hi)
                nw = 0.5 * width
                _nb_shift(M, last, lc, lw, nc, nw, K, out, 0)
                _nb_shift(M, k, c, w, nc, nw, K, out, 6)
                for m in range(6):
                    M[last, m] = out[m] + out[6 + m]
                C[last] = nc
                W[last] = nw
                S[last] = False
                for q in range(4):
                    E[last, q] = 0.0
                continue
        if n != k:
            C[n] = c
            W[n] = w
            S[n] = S[k]
            for m in range(6):
                M[n, m] = M[k, m]
            for q in range(4):
                E[n, q] = E[k, q]
        n += 1
    N[s] = n
    return n


def _nb_push(t: float, v: float, RT: Any, RV: Any, NR: Any, LT: Any, CNT: Any, s: int, C: Any, W: Any, M: Any,
             S: Any, E: Any, N: Any) -> int:
    """``Convolver.push`` up to its compacting, on source s: 0, or -1 for an instant
    earlier than its last."""
    CNT[s] += 1
    nr = NR[s]
    if t == LT[s]:
        if v == RV[s, nr - 1]:
            return 0
        RT[s, 0] = t
        RV[s, 0] = v
        NR[s] = 1
        return 0
    if t < LT[s]:
        return -1
    if nr > 0:
        _nb_piece(RT[s], RV[s], nr, t, v, C[s], W[s], M[s], S[s], E[s], N[s])
        N[s] += 1
    if nr < 4:
        RT[s, nr] = t
        RV[s, nr] = v
        NR[s] = nr + 1
    else:
        for k in range(3):
            RT[s, k] = RT[s, k + 1]
            RV[s, k] = RV[s, k + 1]
        RT[s, 3] = t
        RV[s, 3] = v
    LT[s] = t
    return 0


def _nb_push_all(t: float, IN: Any, RT: Any, RV: Any, NR: Any, LT: Any, CNT: Any, C: Any, W: Any, M: Any, S: Any,
                 E: Any, N: Any) -> int:
    """``_nb_push`` of every source in turn, each with its current inflow: -1, or the first
    source told about an instant earlier than its last."""
    for s in range(NR.shape[0]):
        if _nb_push(t, IN[s], RT, RV, NR, LT, CNT, s, C, W, M, S, E, N) < 0:
            return s
    return -1


def _nb_histories(t: float, C: Any, W: Any, M: Any, S: Any, E: Any, N: Any, TS: Any, TI: Any, KT: Any, KOT: Any,
                  KD: Any, KA: Any, KOA: Any, KH: Any, KN: Any, KT0: Any, KTE: Any, IT: Any, IA: Any, IO: Any,
                  v: Any, wide: Any, out: Any) -> None:
    """``Convolver.history`` of every source at t, a source after another, added into
    ``out``."""
    for s in range(TS.shape[0] - 1):
        nb = N[s]
        for j in range(TS[s], TS[s + 1]):
            npc = KN[j]
            if npc < 1:
                continue
            o = KOT[j]
            oa = KOA[j]
            out[TI[j]] += _nb_history(t, C[s], W[s], M[s], S[s], E[s], nb, KT[o:o + npc + 1], KD[oa:oa + npc],
                                      KA[oa:oa + npc], KH[o:o + npc + 1], npc, KT0[j], KTE[j], IT[IO[s]:IO[s + 1]],
                                      IA[IO[s]:IO[s + 1]], v, wide)


def _nb_lag_basis(s: Any, count: int, D: float, coef: Any) -> None:
    """``lag_basis``, into the rows of ``coef``."""
    for k in range(count):
        for q in range(5):
            coef[k, q] = 0.0
        coef[k, 0] = 1.0
        deg = 0
        den = 1.0
        sk = s[k] / D
        for m in range(count):
            if m == k:
                continue
            sm = s[m] / D
            for q in range(deg + 1, 0, -1):
                coef[k, q] = coef[k, q - 1] - sm * coef[k, q]
            coef[k, 0] = -sm * coef[k, 0]
            deg += 1
            den *= sk - sm
        for q in range(deg + 1):
            coef[k, q] /= den


def _nb_piece_moments(t: Any, a: Any, k: int, ua: float, ub: float, out: Any) -> None:
    """``piece_moments``, into ``out``."""
    for q in range(4):
        out[q] = 0.0
    if not ub > ua:
        return
    t0 = t[k]
    d = t[k + 1] - t0
    a0 = a[k, 0]
    a1 = a[k, 1]
    a2 = a[k, 2]
    a3 = a[k, 3]
    a4 = a[k, 4]
    a5 = a[k, 5]
    c = 0.5 * (ua + ub)
    hw = 0.5 * (ub - ua)
    for g in range(5):
        u = c + GL5_X[g] * hw
        x = (u - t0) / d
        h = a0 + x * (a1 + x * (a2 + x * (a3 + x * (a4 + x * a5))))
        w = GL5_W[g] * hw * h
        out[0] += w
        out[1] += w * u
        out[2] += w * u * u
        out[3] += w * u * u * u


def _nb_running_moments(t: Any, a: Any, P: Any, npc: int, t0k: float, t_endk: float, D: float, out: Any,
                        rest: Any) -> None:
    """``running_moments``, into ``out`` (``rest`` scratch)."""
    if not D > t0k or npc < 1:
        for q in range(4):
            out[q] = 0.0
        return
    top = t_endk if t_endk < D else D
    k = _nb_piece_at(t, npc, top)
    for q in range(4):
        out[q] = P[k, q]
    _nb_piece_moments(t, a, k, t[k], top, rest)
    for q in range(4):
        out[q] += rest[q]


def _nb_parts(t: float, RT: Any, RV: Any, NR: Any, LT: Any, TS: Any, TI: Any, KT: Any, KOT: Any, KA: Any, KOA: Any,
              KP: Any, KN: Any, KT0: Any, KTE: Any, KM0: Any, KTM0: Any, n: int, cur: Any, PS: Any, PI: Any,
              PC: Any, PN: Any, PW: Any) -> int:
    """``LaplaceFarfPath._parts``: for every source, a source after another, its
    ``step_weights`` and then its ``point_parts`` -- the source (PS), target (PI), nodes (PC),
    records (PN) and node weights (PW) of each part -- with each current inflow's weight added
    into ``cur``: how many parts."""
    sv = np.empty(4)
    coef = np.empty((4, 5))
    mom = np.empty(4)
    rest = np.empty(4)
    nodes = np.empty(4)
    p = 0
    for slot in range(TS.shape[0] - 1):
        j0 = TS[slot]
        j1 = TS[slot + 1]
        nr = NR[slot]
        last = LT[slot]
        count = nr + 1 if nr < 3 else 4
        D = t - last
        if j1 > j0 and nr > 0 and D > 0:
            for k in range(count - 1):
                sv[k] = t - RT[slot, nr - (count - 1) + k]
            sv[count - 1] = 0.0
            basis = False
            for j in range(j0, j1):
                if not D > KT0[j]:
                    continue
                if not basis:
                    _nb_lag_basis(sv, count, D, coef)
                    basis = True
                o = KOT[j]
                npc = KN[j]
                _nb_running_moments(KT[o:o + npc + 1], KA[KOA[j]:KOA[j] + npc], KP[o:o + npc + 1], npc, KT0[j],
                                    KTE[j], D, mom, rest)
                Dq = 1.0
                for q in range(1, 4):
                    Dq *= D
                    mom[q] /= Dq
                for k in range(count):
                    val = 0.0
                    for q in range(count):
                        val += coef[k, q] * mom[q]
                    PW[p, k] = val
                PS[p] = slot
                PI[p] = TI[j]
                PC[p] = count
                PN[p] = nr
                cur[TI[j] * n + slot % n] += PW[p, count - 1]
                p += 1
        if nr > 0:
            for j in range(j0, j1):
                if not KM0[j] > 0:
                    continue
                tau = t - KTM0[j]
                if not tau > last:
                    continue
                for k in range(count - 1):
                    nodes[k] = RT[slot, nr - (count - 1) + k]
                nodes[count - 1] = t
                for k in range(count):
                    lk = 1.0
                    for m in range(count):
                        if m != k:
                            lk *= (tau - nodes[m]) / (nodes[k] - nodes[m])
                    PW[p, k] = KM0[j] * lk
                PS[p] = slot
                PI[p] = TI[j]
                PC[p] = count
                PN[p] = nr
                cur[TI[j] * n + slot % n] += PW[p, count - 1]
                p += 1
    return p


def _nb_add_parts(res: Any, PS: Any, PI: Any, PC: Any, PN: Any, PW: Any, count: int, RV: Any, IN: Any) -> None:
    """``step_sum`` of each part, against its source's records and current inflow, added
    into ``res`` in turn."""
    for p in range(count):
        s = PS[p]
        c = PC[p]
        nr = PN[p]
        r = PW[p, c - 1] * IN[s]
        for k in range(c - 1):
            r += PW[p, k] * RV[s, nr - (c - 1) + k]
        res[PI[p]] += r


class _Compiled:
    """The kernels above, compiled."""

    __slots__ = ('history', 'histories', 'push', 'push_all', 'compact', 'parts', 'add_parts')

    def __init__(self, history: Any, histories: Any, push: Any, push_all: Any, compact: Any, parts: Any,
                 add_parts: Any) -> None:
        self.history = history
        self.histories = histories
        self.push = push
        self.push_all = push_all
        self.compact = compact
        self.parts = parts
        self.add_parts = add_parts


_COMPILED: Any = None


def _compiled() -> Optional[_Compiled]:
    """The kernels above compiled with numba, or None where numba is not installed or will
    not compile them -- and then the convolvers and the path do it all in Python and numpy,
    as they always did. Compiled once a process, and kept on disk (see
    kompartment.engine.compiled)."""
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = False
        from ._numba import jit, numba_module
        if numba_module() is not None:
            try:
                from .compiled import guard_numba_cache
                guard_numba_cache()
                # Each helper as compiled code under its own name, so that the kernels,
                # compiled after them, call compiled code.
                for name in ('_nb_block', '_nb_pairwise', '_nb_count', '_nb_walk', '_nb_piece_at', '_nb_kernel_at',
                             '_nb_direct', '_nb_from_moment', '_nb_history', '_nb_piece', '_nb_push', '_nb_ahead',
                             '_nb_shift', '_nb_lag_basis', '_nb_piece_moments', '_nb_running_moments'):
                    fn = jit(globals()[name])
                    if fn is None:
                        raise RuntimeError(name)
                    globals()[name] = fn
                kernels = [jit(fn) for fn in (_nb_histories, _nb_push_all, _nb_compact, _nb_parts, _nb_add_parts)]
                if any(k is None for k in kernels):
                    raise RuntimeError('a kernel')
                histories, push_all, compact, parts, add_parts = kernels
                # Each called once, on a source without targets, with the types a run hands
                # it, so that a run finds them compiled.
                src = _Sources([[]])
                IT, IA, IO = src.impulses()
                _nb_history(0.0, src.C[0], src.W[0], src.M[0], src.S[0], src.E[0], 0, np.zeros(2), np.ones(1),
                            np.zeros((1, 6)), np.full(2, math.inf), 1, 0.0, 1.0, IT, IA, src.v, src.wide)
                histories(0.0, src.C, src.W, src.M, src.S, src.E, src.N, src.TS, src.TI, src.KT, src.KOT, src.KD,
                          src.KA, src.KOA, src.KH, src.KN, src.KT0, src.KTE, IT, IA, IO, src.v, src.wide, np.zeros(1))
                _nb_push(0.0, 0.0, src.RT, src.RV, src.NR, src.LT, src.CNT, 0, src.C, src.W, src.M, src.S, src.E,
                         src.N)
                push_all(1.0, np.zeros(1), src.RT, src.RV, src.NR, src.LT, src.CNT, src.C, src.W, src.M, src.S,
                         src.E, src.N)
                compact(1.0, src.reach[0], src.C, src.W, src.M, src.S, src.E, src.N, 0, src.KT, src.KH, src.KOT,
                        src.KN, src.KT0, src.KTE, src.TS[0], src.TS[1], _POWERS, src.out)
                P = _Parts(1)
                count = parts(2.0, src.RT, src.RV, src.NR, src.LT, src.TS, src.TI, src.KT, src.KOT, src.KA, src.KOA,
                              src.KP, src.KN, src.KT0, src.KTE, src.KM0, src.KTM0, 1, np.zeros(1), P.S, P.I, P.C, P.N,
                              P.W)
                add_parts(np.zeros(1), P.S, P.I, P.C, P.N, P.W, count, src.RV, np.zeros(1))
                _COMPILED = _Compiled(_nb_history, histories, _nb_push, push_all, compact, parts, add_parts)
            except Exception:  # noqa: BLE001 - numba present but refusing: Python and numpy, as before
                _COMPILED = False
    return _COMPILED or None


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
        self.rt: List[float] = []
        self.rv: List[float] = []
        self.last_t = -math.inf
        self._reset_blocks()

    def _reset_blocks(self) -> None:
        self.imp_t: List[float] = []
        self.imp_a: List[float] = []
        self.compact_at = 64
        self.count = 0
        # The blocks, n of them: centres, half-widths, moments, whether each is still one
        # recorded piece, and that piece's cubic (zeros once it is not). Arrays a block
        # long would be rebuilt every step; these grow by doubling.
        self.n = 0
        self._C = np.zeros(64)
        self._W = np.zeros(64)
        self._M = np.zeros((64, 6))
        self._S = np.zeros(64, dtype=bool)
        self._E = np.zeros((64, 4))
        self._v = np.zeros(64)
        self._wide = np.zeros(64, dtype=np.int64)
        self._arrays: Optional[tuple] = None
        self._imp: Optional[tuple] = None

    def _room(self, n: int) -> None:
        """Arrays for at least n blocks, what is in them kept."""
        if n <= self._C.shape[0]:
            return
        size = max(n, 2 * self._C.shape[0])
        for name in ('_C', '_W', '_M', '_S', '_E'):
            old = getattr(self, name)
            new = np.zeros((size,) + old.shape[1:], dtype=old.dtype)
            new[:self.n] = old[:self.n]
            setattr(self, name, new)
        self._v = np.zeros(size)
        self._wide = np.zeros(size, dtype=np.int64)

    def _set_block(self, b: int, c: float, w: float, mu: Sequence[float], e: Optional[Sequence[float]]) -> None:
        self._C[b] = c
        self._W[b] = w
        self._M[b] = mu
        self._S[b] = e is not None
        self._E[b] = e if e is not None else (0.0, 0.0, 0.0, 0.0)

    def _impulse_arrays(self) -> tuple:
        if self._imp is None:
            self._imp = (np.array(self.imp_t, dtype=float), np.array(self.imp_a, dtype=float))
        return self._imp

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
        self._imp = None

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
        if self.n > self.compact_at:
            self.compact(t)

    def _piece(self, t: float, v: float) -> None:
        rt = self.rt
        rv = self.rv
        nr = len(rt)
        ta = rt[nr - 1]
        c = 0.5 * (ta + t)
        w = 0.5 * (t - ta)
        count = min(nr + 1, 4)
        ns = [0.0] * count
        nv = [0.0] * count
        for k in range(count - 1):
            ns[k] = (rt[nr - (count - 1) + k] - c) / w
            nv[k] = rv[nr - (count - 1) + k]
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
        self._room(self.n + 1)
        self._set_block(self.n, c, w, mu, e)
        self.n += 1
        self._arrays = None

    def compact(self, t_now: float) -> None:
        reach = self.reach()
        C, W, M, S, E = self._C, self._W, self._M, self._S, self._E
        n = 0
        for k in range(self.n):
            c = float(C[k])
            w = float(W[k])
            if t_now - (c + w) > reach:
                continue
            if n:
                last = n - 1
                lc = float(C[last])
                lw = float(W[last])
                lo = lc - lw
                hi = c + w
                width = hi - lo
                if width <= RHO * self.ahead(t_now - hi):
                    nc = 0.5 * (lo + hi)
                    nw = 0.5 * width
                    merged = shift(M[last].tolist(), lc, lw, nc, nw)
                    mine = shift(M[k].tolist(), c, w, nc, nw)
                    for m in range(6):
                        merged[m] += mine[m]
                    self._set_block(last, nc, nw, merged, None)
                    continue
            if n != k:
                C[n], W[n], M[n], S[n], E[n] = C[k], W[k], M[k], S[k], E[k]
            n += 1
        self.n = n
        self.compact_at = 2 * n + 64
        self._arrays = None

    def _snapshot(self) -> tuple:
        if self._arrays is None:
            n = self.n
            self._arrays = (self._C[:n], self._W[:n], self._M[:n], self._S[:n])
        return self._arrays

    def history(self, t: float, out: np.ndarray) -> None:
        """What the recorded history releases at t, added into ``out[i]`` for
        each target."""
        if not self.targets:
            return
        nb = self.n
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
                        total += direct(kern, t, float(C[b]), float(Wd[b]), self._E[b].tolist())
            for r in range(len(self.imp_t)):
                total += self.imp_a[r] * kernel_at(kern, t - self.imp_t[r])
            out[tg['i']] += total


class _Sources:
    """A path's sources as the compiled kernels keep them, a row a source: its last records
    (a convolver's ``rt``, ``rv`` and ``last_t``, oldest first, ``NR`` of them), its blocks
    (``N`` of them, as a convolver keeps them) and its point impulses; and its targets'
    responses end to end. Source s's targets are ``TS[s]`` to ``TS[s + 1]``: each one's slot
    ``TI``, grid ``KT`` with its spacings ahead ``KH`` and running moments ``KP`` beside it
    (from ``KOT``), pieces' widths ``KD`` and coefficients ``KA`` (from ``KOA``), and its
    pieces, first and last times and point mass."""

    def __init__(self, targets: List[List[Dict[str, Any]]]) -> None:
        slots = len(targets)
        self.RT = np.zeros((slots, 4))
        self.RV = np.zeros((slots, 4))
        self.NR = np.zeros(slots, dtype=np.int64)
        self.LT = np.full(slots, -math.inf)
        self.CNT = np.zeros(slots, dtype=np.int64)
        self.N = np.zeros(slots, dtype=np.int64)
        self.CA = np.full(slots, 64, dtype=np.int64)
        self.C = np.zeros((slots, 64))
        self.W = np.zeros((slots, 64))
        self.M = np.zeros((slots, 64, 6))
        self.S = np.zeros((slots, 64), dtype=bool)
        self.E = np.zeros((slots, 64, 4))
        self.v = np.zeros(64)
        self.wide = np.zeros(64, dtype=np.int64)
        self.out = np.zeros(12)
        self.imp_t: List[List[float]] = [[] for _ in range(slots)]
        self.imp_a: List[List[float]] = [[] for _ in range(slots)]
        self._imp: Optional[tuple] = None
        flat = [tg for row in targets for tg in row]
        kerns = [tg['kern'] for tg in flat]
        self.TS = np.zeros(slots + 1, dtype=np.int64)
        for q, row in enumerate(targets):
            self.TS[q + 1] = self.TS[q] + len(row)
        self.TI = np.array([tg['i'] for tg in flat], dtype=np.int64)
        self.KOT = np.zeros(len(kerns), dtype=np.int64)
        self.KOA = np.zeros(len(kerns), dtype=np.int64)
        for j in range(1, len(kerns)):
            self.KOT[j] = self.KOT[j - 1] + kerns[j - 1].t.size
            self.KOA[j] = self.KOA[j - 1] + kerns[j - 1].np
        if any(k.ahead.size != k.t.size for k in kerns):
            raise ValueError('a response without a spacing ahead of each of its times')
        self.KT = np.concatenate([k.t for k in kerns]) if kerns else np.zeros(0)
        self.KH = np.concatenate([k.ahead for k in kerns]) if kerns else np.zeros(0)
        self.KP = np.concatenate([np.array(k.P, dtype=float).T for k in kerns]) if kerns else np.zeros((0, 4))
        self.KD = np.concatenate([k.d for k in kerns]) if kerns else np.zeros(0)
        self.KA = np.concatenate([k.a for k in kerns]) if kerns else np.zeros((0, 6))
        self.KN = np.array([k.np for k in kerns], dtype=np.int64)
        self.KT0 = np.array([k.t0 for k in kerns], dtype=float)
        self.KTE = np.array([k.t_end for k in kerns], dtype=float)
        self.KM0 = np.array([k.m0 for k in kerns], dtype=float)
        self.KTM0 = np.array([k.tm0 for k in kerns], dtype=float)
        # How far back each source's responses reach (``Convolver.reach``).
        self.reach = np.full(slots, -math.inf)
        for q, row in enumerate(targets):
            for tg in row:
                if tg['kern'].t_end > self.reach[q]:
                    self.reach[q] = tg['kern'].t_end
        # Point masses whose lag reaches back into the records are released by the path,
        # a source at a time, after the source's history.
        self.points = bool(np.any(self.KM0 > 0))
        # A part for each target's step, and one for its point mass.
        self.most = 2 * len(flat)

    def room(self, n: int) -> None:
        """Rows for at least n blocks, what is in them kept."""
        cap = self.C.shape[1]
        if n <= cap:
            return
        size = max(n, 2 * cap)
        for name in ('C', 'W', 'M', 'S', 'E'):
            old = getattr(self, name)
            new = np.zeros((old.shape[0], size) + old.shape[2:], dtype=old.dtype)
            new[:, :cap] = old
            setattr(self, name, new)
        self.v = np.zeros(size)
        self.wide = np.zeros(size, dtype=np.int64)

    def impulses(self) -> tuple:
        """Every source's point impulses end to end -- times, amounts -- and where each
        source's begin."""
        if self._imp is None:
            IO = np.zeros(len(self.imp_t) + 1, dtype=np.int64)
            for q, ts in enumerate(self.imp_t):
                IO[q + 1] = IO[q] + len(ts)
            self._imp = (np.array([x for ts in self.imp_t for x in ts], dtype=float),
                         np.array([x for xs in self.imp_a for x in xs], dtype=float), IO)
        return self._imp


class _CompiledConvolver(Convolver):
    """A convolver whose records, blocks and impulses are row ``slot`` of its path's
    ``_Sources``, which the compiled kernels keep; read here as the Python convolver's are."""

    def __init__(self, targets: List[Dict[str, Any]], kernels: _Compiled, src: _Sources, slot: int) -> None:
        self._kernels = kernels
        self._src = src
        self._slot = slot
        super().__init__(targets)

    @property
    def rt(self) -> List[float]:  # type: ignore[override]
        return self._src.RT[self._slot, :self._src.NR[self._slot]].tolist()

    @property
    def rv(self) -> List[float]:  # type: ignore[override]
        return self._src.RV[self._slot, :self._src.NR[self._slot]].tolist()

    @property
    def last_t(self) -> float:  # type: ignore[override]
        return float(self._src.LT[self._slot])

    @property
    def n(self) -> int:  # type: ignore[override]
        return int(self._src.N[self._slot])

    @property
    def count(self) -> int:  # type: ignore[override]
        return int(self._src.CNT[self._slot])

    @property
    def compact_at(self) -> int:  # type: ignore[override]
        return int(self._src.CA[self._slot])

    def reset(self) -> None:
        src, s = self._src, self._slot
        src.NR[s] = 0
        src.LT[s] = -math.inf
        src.CNT[s] = 0
        src.N[s] = 0
        src.CA[s] = 64
        self.imp_t = src.imp_t[s]
        self.imp_a = src.imp_a[s]
        del self.imp_t[:]
        del self.imp_a[:]
        src._imp = None
        self._imp = None

    def impulse(self, t: float, amount: float) -> None:
        super().impulse(t, amount)
        self._src._imp = None

    def push(self, t: float, v: float) -> None:
        src, s = self._src, self._slot
        src.room(int(src.N[s]) + 1)
        if self._kernels.push(t, v, src.RT, src.RV, src.NR, src.LT, src.CNT, s, src.C, src.W, src.M, src.S, src.E,
                              src.N) < 0:
            raise RuntimeError('a far-field path was told about an earlier instant after a later one')
        if src.N[s] > src.CA[s]:
            self.compact(t)

    def compact(self, t_now: float) -> None:
        src, s = self._src, self._slot
        n = self._kernels.compact(t_now, src.reach[s], src.C, src.W, src.M, src.S, src.E, src.N, s, src.KT, src.KH,
                                  src.KOT, src.KN, src.KT0, src.KTE, src.TS[s], src.TS[s + 1], _POWERS, src.out)
        src.CA[s] = 2 * n + 64

    def history(self, t: float, out: np.ndarray) -> None:
        if not self.targets:
            return
        src, s = self._src, self._slot
        kernel = self._kernels.history
        nb = int(src.N[s])
        imp_t, imp_a = self._impulse_arrays()
        C, W, M, S, E = src.C[s], src.W[s], src.M[s], src.S[s], src.E[s]
        for tg in self.targets:
            kern = tg['kern']
            if kern.np < 1:
                continue
            out[tg['i']] += kernel(t, C, W, M, S, E, nb, kern.t, kern.d, kern.a, kern.ahead, kern.np, kern.t0,
                                   kern.t_end, imp_t, imp_a, src.v, src.wide)


def _sources_of(cvs: Optional[List[Convolver]]) -> Optional[_Sources]:
    """The compiled sources behind a set of convolvers, or None for Python ones."""
    if cvs and isinstance(cvs[0], _CompiledConvolver):
        return cvs[0]._src
    return None


class _Parts:
    """The step's parts as the compiled kernels write them, ``count`` of them: each one's
    source, target, nodes, records and node weights."""

    __slots__ = ('count', 'S', 'I', 'C', 'N', 'W')

    def __init__(self, most: int) -> None:
        self.count = 0
        self.S = np.empty(most, dtype=np.int64)
        self.I = np.empty(most, dtype=np.int64)
        self.C = np.empty(most, dtype=np.int64)
        self.N = np.empty(most, dtype=np.int64)
        self.W = np.empty((most, 4))


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
        """A convolver for every source -- compiled ones, rows of one ``_Sources``, when the
        kernels compiled."""
        n = self.nnuc
        rows: List[List[Dict[str, Any]]] = []
        for o in range(self.other_width):
            kernels = self.combos[o]['kernels']  # type: ignore[index]
            for j in range(n):
                rows.append([{'i': o * n + i, 'kern': kernels[i * n + j]} for i in range(n)
                             if kernels[i * n + j] is not None])
        compiled = _compiled()
        if compiled is None:
            return [Convolver(targets) for targets in rows]
        src = _Sources(rows)
        return [_CompiledConvolver(targets, compiled, src, slot) for slot, targets in enumerate(rows)]

    # --- the release --------------------------------------------------------------------

    def inflow(self, y: np.ndarray, X: np.ndarray) -> np.ndarray:
        """What the model's fluxes deliver into every slot at (y, X)."""
        IN = self.IN
        IN.fill(0.0)
        if self.in_tgt.size:
            vals = np.where(self._has_donor, y[self._donor_at], 1.0) * X[self.in_rate]
            np.add.at(IN, self.in_tgt, vals)
        return IN

    def _parts(self, cvs: List[Convolver], t: float, cur: np.ndarray) -> Any:
        """The step from the last records to t, for every source of ``cvs`` in turn: its
        ``step_weights`` and then its ``point_parts``, each part's current-inflow weight
        added into ``cur`` -- a list of parts, or the compiled kernels' ``_Parts``."""
        src = _sources_of(cvs)
        if src is not None:
            P = _Parts(src.most)
            P.count = cvs[0]._kernels.parts(t, src.RT, src.RV, src.NR, src.LT, src.TS, src.TI, src.KT, src.KOT,  # type: ignore[attr-defined]
                                            src.KA, src.KOA, src.KP, src.KN, src.KT0, src.KTE, src.KM0, src.KTM0,
                                            self.nnuc, cur, P.S, P.I, P.C, P.N, P.W)
            return P
        n = self.nnuc
        parts: List[Dict[str, Any]] = []
        for slot in range(self.slots):
            for part in step_weights(cvs[slot], t) + point_parts(cvs[slot], t):
                part['slot'] = slot
                parts.append(part)
                cur[part['i'] * n + (slot % n)] += part['w'][part['count'] - 1]
        return parts

    def _add_parts(self, res: np.ndarray, parts: Any, cvs: Optional[List[Convolver]], IN: np.ndarray) -> None:
        """Each part's ``step_sum`` against its source's records and current inflow, added
        into ``res`` in turn."""
        src = _sources_of(cvs)
        if src is not None and isinstance(parts, _Parts):
            cvs[0]._kernels.add_parts(res, parts.S, parts.I, parts.C, parts.N, parts.W, parts.count, src.RV,  # type: ignore[index, attr-defined]
                                      IN)
            return
        for part in parts:
            res[part['i']] += step_sum(cvs[part['slot']], part, float(IN[part['slot']]))  # type: ignore[index]

    def _histories(self, cvs: List[Convolver], t: float, out: np.ndarray) -> None:
        """What every source's history releases at t, added into ``out``, a source after
        another: its blocks and impulses (``Convolver.history``), then the point masses whose
        lag reaches back into its records (``_points_behind``)."""
        src = _sources_of(cvs)
        if src is not None and not src.points:
            IT, IA, IO = src.impulses()
            cvs[0]._kernels.histories(t, src.C, src.W, src.M, src.S, src.E, src.N, src.TS, src.TI, src.KT, src.KOT,  # type: ignore[attr-defined]
                                      src.KD, src.KA, src.KOA, src.KH, src.KN, src.KT0, src.KTE, IT, IA, IO, src.v,
                                      src.wide, out)
            return
        for slot in range(self.slots):
            cvs[slot].history(t, out)
            self._points_behind(cvs[slot], slot, t, out)

    def _weights(self, t: float) -> Dict[str, Any]:
        if t == self.weight_t and self.weights is not None:
            return self.weights
        W: Dict[str, Any] = {'cur': np.zeros(self.slots * self.nnuc), 'parts': []}
        if self.live is not None and t > self.last_t:
            W['parts'] = self._parts(self.live, t, W['cur'])
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
                self._histories(self.live, t, hist)
            self.hist_t = t
        IN = self.inflow(y, X)
        W = self._weights(t)
        res = hist.copy()
        self._add_parts(res, W['parts'], self.live, IN)
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
        self._histories(self.sweep, t, out)
        IN = self.inflow(y, X)
        parts = self._parts(self.sweep, t, np.zeros(self.slots * self.nnuc))
        self._add_parts(out, parts, self.sweep, IN)
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
            src = _sources_of(self.live)
            for slot in range(self.slots):
                rec = self.records[slot]
                v = float(IN[slot])
                rec['t'].append(t)
                rec['v'].append(v)
                if src is None:
                    self.live[slot].push(t, v)
            if src is not None:
                self._push_all(src, t, IN)
        if t not in self.releases:
            self.releases[t] = X[self.release_slots].copy()
        self.last_held[:] = held
        self.last_t = t
        self.hist_t = math.nan
        self.weight_t = math.nan
        src = _sources_of(self.live)
        self.stats['blocks'] = int(src.N.sum()) if src is not None else sum(cv.n for cv in self.live)

    def _push_all(self, src: _Sources, t: float, IN: np.ndarray) -> None:
        """Every live source told of t and its current inflow at once, as each
        ``Convolver.push`` would be, compacting where it is due."""
        src.room(int(src.N.max()) + 1)
        cvs = self.live
        if cvs[0]._kernels.push_all(t, IN, src.RT, src.RV, src.NR, src.LT, src.CNT, src.C, src.W, src.M, src.S,  # type: ignore[index, attr-defined]
                                    src.E, src.N) >= 0:
            raise RuntimeError('a far-field path was told about an earlier instant after a later one')
        for slot in np.nonzero(src.N > src.CA)[0].tolist():
            cvs[slot].compact(t)  # type: ignore[index]

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
