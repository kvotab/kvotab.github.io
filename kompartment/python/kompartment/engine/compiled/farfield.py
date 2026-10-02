"""A far-field path on cells whose settings move, refreshed in compiled code.

``FarfPath.refresh`` (:mod:`kompartment.engine.farfield`) works a path's
rates out again for every slot whose settings moved since it last saw them,
and lays the matched layers out once per run for each combination of its
other index lists. This module is that refresh and everything it calls --
``coefficients``, ``cell_values``, ``release_weights``, the reference layers
(``layer_depths``), the matched ones (``matched_grid``, ``auto_first_layer``,
``penetration_scale``) and Dekker's ``zeroin`` -- over flat arrays, with the
Python arithmetic in its order, so that a compiled refresh is the Python one
to the last bit.

A path keeps its state in ``W``, laid out by :func:`state_layout`: its release
weights, the settings each slot last saw, whether each combination has its
matched layers laid out, the layers, and its nuclides' decay constants. Its
rates are the derivative's matrix entries themselves. What a refresh reads
of the path -- its sizes, where its settings are in ``X``, where its rates
and its state are in ``W`` -- is its directory, an array of ``IW`` written by
:func:`directory`. :func:`take` and :func:`hand` move the state between ``W``
and the Python path's object.

Settings that describe no path make the Python refresh raise -- a
:class:`~kompartment.engine.farfield.FarfError`, and the odd ValueError or
ZeroDivisionError of its arithmetic. The compiled refresh answers
``ASK_PYTHON`` wherever one of them would be raised, and the path is handed
to the Python refresh, which raises it. It answers ``LAID_OUT`` when it has
laid matched layers out, so that the Python path holds them from then on and
never lays them out apart.
"""

from __future__ import annotations

import math
from typing import Any, Dict

import numpy as np
from numba import njit

from ..farfield import ATTENUATION, FARF_EQUATION_KEYS, RESOLVE, SURFACES
from . import guard_numba_cache

guard_numba_cache()

#: What a refresh answers.
DONE = 0          # the rates and release weights are up to date
ASK_PYTHON = 1    # a setting the Python refresh raises on: the path is handed to it, which raises
LAID_OUT = 2      # matched layers were laid out: the path is handed to the Python one, to hold them too

# --- a path's directory, in IW -----------------------------------------------------------------
FD_NNUC = 0       # nuclides
FD_WIDTH = 1      # combinations of the other index lists
FD_NKEYS = 2      # settings per slot
FD_NF = 3         # fracture cells up to the release point
FD_NM = 4         # matrix layers
FD_OB = 5         # the outflow condition, 0 to 3 (``effective_structure``)
FD_NB = 6         # fracture cells past the release point
FD_NNZ = 7        # matrix entries per slot
FD_NREL = 8       # release cells per slot
FD_MATCHED = 9    # 1 for the matched layers, 0 for the reference ones
FD_SURFACE = 10   # how the wetted surface is given: its place in SURFACES
FD_DATA = 11      # where in W the derivative's matrix data starts
FD_RELW = 12      # where in W the release weights are, slot by slot
FD_SEEN = 13      # ... the settings each slot last saw
FD_LAID = 14      # ... 1.0 for each combination with its matched layers laid out
FD_LAYERS = 15    # ... the layers of each combination: nm thicknesses, nm node spacings, q
FD_LAM = 16       # ... each nuclide's decay constant
FD_KEYS = 17      # where each of FARF_EQUATION_KEYS is among a slot's settings, -1 where it is not
FD_HEAD = FD_KEYS + len(FARF_EQUATION_KEYS)
# Then the slots in X of every slot's settings (``setting_idx``), slot by
# slot, and the positions in the matrix data of every slot's entries.

K_TW, K_F, K_AW, K_APERTURE, K_KD_F, K_KD_M, K_DE_M, K_EPS_M, K_RHO_M, K_PE, K_PEN_DEP, K_PEN_DEP_0 = (
    FARF_EQUATION_KEYS.index(key) for key in ('tw', 'f', 'aw', 'aperture', 'kd_f', 'kd_m', 'de_m', 'eps_m', 'rho_m',
                                              'pe', 'pen_dep', 'pen_dep_0'))
S_AW = SURFACES.index('aw')
S_APERTURE = SURFACES.index('aperture')
#: The functions zeroin searches.
GEO = 0           # layer_depths' geo(x): the series from a first layer x
POWERS = 1        # layer_depths' total(q): d0 * q**j added up
PRODUCTS = 2      # matched_grid's total(r): d0 multiplied by r layer after layer, added up


def state_layout(F: Any, at: int) -> Dict[str, int]:
    """Where in W path F keeps its state, from ``at``: ``relw``, ``seen``,
    ``laid``, ``layers`` and ``lam``, and ``end``, past the last."""
    nm = F.structure['n_m']
    out = {'relw': at}
    at += F.rel_w.size
    out['seen'] = at
    at += F.seen.size
    out['laid'] = at
    at += F.other_width
    out['layers'] = at
    at += F.other_width * (2 * nm + 1) if F.grid == 'matched' else 0
    out['lam'] = at
    at += F.nnuc
    out['end'] = at
    return out


def directory(F: Any, data: int, at: Dict[str, int], pos: np.ndarray) -> np.ndarray:
    """Path F's directory (``FD_``): its rates at ``pos`` in the matrix data
    that starts at W[data], its state where ``at`` (:func:`state_layout`) says."""
    g = F.structure
    head = np.zeros(FD_HEAD, dtype=np.int64)
    head[FD_NNUC] = F.nnuc
    head[FD_WIDTH] = F.other_width
    head[FD_NKEYS] = len(F.keys)
    head[FD_NF] = g['n_f']
    head[FD_NM] = g['n_m']
    head[FD_OB] = g['o_b']
    head[FD_NB] = g['n_b']
    head[FD_NNZ] = F.nnz
    head[FD_NREL] = F.nrel
    head[FD_MATCHED] = 1 if F.grid == 'matched' else 0
    head[FD_SURFACE] = SURFACES.index(F.surface)
    head[FD_DATA] = data
    head[FD_RELW] = at['relw']
    head[FD_SEEN] = at['seen']
    head[FD_LAID] = at['laid']
    head[FD_LAYERS] = at['layers']
    head[FD_LAM] = at['lam']
    for i, key in enumerate(FARF_EQUATION_KEYS):
        head[FD_KEYS + i] = F.keys.index(key) if key in F.keys else -1
    return np.concatenate([head, np.asarray(F.setting_idx, dtype=np.int64).ravel(),
                           np.asarray(pos, dtype=np.int64)])


def take(F: Any, W: np.ndarray, data: int, at: Dict[str, int], pos: np.ndarray) -> None:
    """Path F's state, as the Python path's object holds it, into W."""
    W[data + pos] = F.vals.ravel()
    W[at['relw']:at['seen']] = F.rel_w.ravel()
    W[at['seen']:at['laid']] = F.seen.ravel()
    W[at['laid']:at['layers']] = F.laid_out
    if F.grid == 'matched':
        nm = F.structure['n_m']
        for o in np.flatnonzero(F.laid_out):
            lay = F.layers[o]
            a = at['layers'] + o * (2 * nm + 1)
            W[a:a + nm] = lay['d']
            W[a + nm:a + 2 * nm] = lay['h']
            W[a + 2 * nm] = lay['q']
    W[at['lam']:at['end']] = F.lam


def hand(F: Any, W: np.ndarray, data: int, at: Dict[str, int], pos: np.ndarray) -> None:
    """Path F's state, as a compiled run holds it in W, onto the Python path's object."""
    F.vals[:] = W[data + pos].reshape(F.vals.shape)
    F.rel_w[:] = W[at['relw']:at['seen']].reshape(F.rel_w.shape)
    F.seen[:] = W[at['seen']:at['laid']].reshape(F.seen.shape)
    F.laid_out[:] = W[at['laid']:at['layers']] != 0.0
    if F.grid == 'matched':
        nm = F.structure['n_m']
        for o in np.flatnonzero(F.laid_out):
            a = at['layers'] + o * (2 * nm + 1)
            F.layers[o] = {'kind': 'matched', 'd': W[a:a + nm].copy(), 'h': W[a + nm:a + 2 * nm].copy(),
                           'q': float(W[a + 2 * nm])}


# --- the arithmetic of engine/farfield.py --------------------------------------------------------


@njit(cache=True, inline='always', error_model='numpy')
def _x(X, fd, slot, key):
    """Setting ``key`` of ``slot``, as ``FarfPath._setting`` reads it from X."""
    return X[fd[FD_HEAD + slot * fd[FD_NKEYS] + fd[FD_KEYS + key]]]


@njit(cache=True, inline='always', error_model='numpy')
def _div(a, b):
    """``farfield._div``: a / b as JavaScript has it."""
    if b != 0:
        return a / b
    if a == 0 or a != a:
        return np.nan
    return math.copysign(np.inf, a) * math.copysign(1.0, b)


@njit(cache=True, inline='always', error_model='numpy')
def _wetted_surface(X, fd, slot):
    """``farfield.wetted_surface`` of the slot's settings."""
    how = fd[FD_SURFACE]
    if how == S_AW:
        return _x(X, fd, slot, K_AW)
    if how == S_APERTURE:
        return _div(2.0, _x(X, fd, slot, K_APERTURE))
    return _div(_x(X, fd, slot, K_F), _x(X, fd, slot, K_TW))


@njit(cache=True, inline='always', error_model='numpy')
def _sign(x):
    """``np.sign``: 0.0 for either zero, NaN for NaN."""
    if x > 0:
        return 1.0
    if x < 0:
        return -1.0
    if x == 0:
        return 0.0
    return np.nan


@njit(cache=True, inline='always', error_model='numpy')
def _spacing(x):
    """``np.spacing``: the distance to the next double away from zero, signed
    like x -- and for either zero the least positive double, which numba's
    own np.spacing signs like the zero."""
    if x == 0:
        return 5e-324
    if x != x or math.isinf(x):
        return np.nan
    return np.nextafter(x, math.copysign(np.inf, x)) - x


@njit(cache=True, inline='always', error_model='numpy')
def _js_pow(q, j):
    """``farfield._js_pow``: Python's ``q ** j`` for a whole j >= 0 -- its
    special cases, then libm's pow of the magnitude with the sign put back,
    as CPython has it -- and Infinity where Python raises OverflowError."""
    if j == 0:
        return 1.0
    odd = j % 2 == 1
    if q != q:
        return q
    if q == 0 or math.isinf(q):
        return q if odd else abs(q)
    r = math.pow(abs(q), float(j))
    if math.isinf(r):
        return np.inf
    return -r if (odd and q < 0) else r


@njit(cache=True, error_model='numpy')
def _total(kind, x, d0, nm, pen_dep, ex):
    """The function zeroin searches (``GEO``, ``POWERS``, ``PRODUCTS``) at x;
    ``ex`` holds e**1 ... e**nm for ``GEO``."""
    s = 0.0
    if kind == GEO:
        for k in range(nm):
            s += x * ex[k]
    elif kind == POWERS:
        for j in range(nm):
            s += d0 * _js_pow(x, j)
    else:
        t = d0
        for _ in range(nm):
            s += t
            t *= x
    return s - pen_dep


@njit(cache=True, error_model='numpy')
def _zeroin(kind, a, b, d0, nm, pen_dep, ex):
    """``farfield.zeroin``, Dekker's, on ``_total``."""
    fa = _total(kind, a, d0, nm, pen_dep, ex)
    fc = fa
    c = a
    fb = 0.0
    for _ in range(1000):
        fb = _total(kind, b, d0, nm, pen_dep, ex)
        if _sign(fb) == _sign(fc):
            c = a
            fc = fa
        if abs(fc) < abs(fb):
            a, b, c = b, c, b
            fa, fb, fc = fb, fc, fb
        m = (b + c) / 2
        if abs(m - b) <= _spacing(abs(b)):
            return b
        p = (b - a) * fb
        q = fa - fb
        if p < 0:
            q = -q
            p = -p
        a = b
        fa = fb
        if p <= _spacing(q):
            b += _sign(c - b) * _spacing(b)
        elif p <= (m - b) * q:
            b += p / q
        else:
            b = m
    return b


@njit(cache=True, error_model='numpy')
def _layer_depths(pen_dep, nm, aw, first, d, ex):
    """``farfield.layer_depths`` into d; False where it raises."""
    if not (pen_dep > 0) or not math.isfinite(pen_dep):
        return False
    if not (aw > 0) or not math.isfinite(aw):
        return False
    d0 = first
    if not (d0 > 0) or not math.isfinite(d0):
        for k in range(nm):
            ex[k] = math.exp(k + 1.0)
        E = math.e
        d0 = _zeroin(GEO, 1e-12 / E, 2 / aw / E, 0.0, nm, pen_dep, ex) * E
    if d0 * nm > pen_dep * (1 + 1e-12):
        return False
    hi = 100.0
    while _total(POWERS, hi, d0, nm, pen_dep, ex) < 0 and hi < 1e300:
        hi *= 100
    q = _zeroin(POWERS, 1.0, hi, d0, nm, pen_dep, ex)
    for j in range(nm):
        d[j] = d0 * _js_pow(q, j)
    return True


@njit(cache=True, error_model='numpy')
def _penetration_scale(de, rm, lam, rf, aw, tw, pe):
    """``farfield.penetration_scale``; -1.0, which it never answers, where it
    raises (the square root of a negative number, a division by zero)."""
    if not (de > 0) or not (rm > 0) or not (aw > 0) or not math.isfinite(aw):
        return np.inf
    if not (tw > 0) or not (pe > 0):
        return np.inf
    G = (ATTENUATION * (1 + ATTENUATION / pe)) / tw
    A = aw * math.sqrt(de * rm)
    under = A * A + 4 * rf * G
    if under < 0:
        return -1.0
    below = A + math.sqrt(under)
    if below == 0:
        return -1.0
    u = (2 * G) / below
    uu = u * u
    floor = lam if (math.isfinite(lam) and lam > 0) else 0.0
    u2 = floor if floor > uu else uu
    if not (u2 > 0) or not math.isfinite(u2):
        return np.inf
    return math.sqrt(de / rm / u2)


@njit(cache=True, error_model='numpy')
def _auto_first_layer(X, W, fd, o, pen_dep, nm, aw, tw, pe):
    """``farfield.auto_first_layer`` over combination o's nuclides, as
    ``FarfPath._lay_out`` lists them; -1.0 where it raises."""
    nnuc = fd[FD_NNUC]
    L = np.inf
    for m in range(nnuc):
        slot = o * nnuc + m
        rm = _x(X, fd, slot, K_EPS_M) + _x(X, fd, slot, K_RHO_M) * _x(X, fd, slot, K_KD_M)
        rf = 1 + _x(X, fd, slot, K_KD_F) * aw
        v = _penetration_scale(_x(X, fd, slot, K_DE_M), rm, W[fd[FD_LAM] + m], rf, aw, tw, pe)
        if v < 0:
            return -1.0
        if v < L:
            L = v
    even = pen_dep / nm
    if not (L < np.inf):
        return even
    d0 = L / RESOLVE
    return d0 if d0 < even else even


@njit(cache=True, error_model='numpy')
def _lay_out(X, W, fd, o, ex):
    """``FarfPath._lay_out``: the matched layers of combination o, from every
    nuclide on it (``matched_grid``), into their place in W; False where the
    Python one raises."""
    first = o * fd[FD_NNUC]
    for slot in range(first, first + fd[FD_NNUC]):
        if not _rock_ok(X, fd, slot):
            return False
    nm = fd[FD_NM]
    aw = _wetted_surface(X, fd, first)
    pen_dep = _x(X, fd, first, K_PEN_DEP)
    if not (pen_dep > 0) or not math.isfinite(pen_dep):
        return False
    d0 = _x(X, fd, first, K_PEN_DEP_0)
    if not (d0 > 0) or not math.isfinite(d0):
        d0 = _auto_first_layer(X, W, fd, o, pen_dep, nm, aw, _x(X, fd, first, K_TW), _x(X, fd, first, K_PE))
        if d0 < 0:
            return False
    if d0 * nm > pen_dep * (1 + 1e-12):
        return False
    d = fd[FD_LAYERS] + o * (2 * nm + 1)
    h = d + nm
    q = 1.0
    if nm == 1 or d0 * nm >= pen_dep * (1 - 1e-12):
        for j in range(nm):
            W[d + j] = pen_dep / nm
    else:
        hi = 2.0
        while _total(PRODUCTS, hi, d0, nm, pen_dep, ex) < 0 and hi < 1e300:
            hi *= 2
        q = _zeroin(PRODUCTS, 1.0, hi, d0, nm, pen_dep, ex)
        W[d] = d0
        for j in range(1, nm):
            W[d + j] = W[d + j - 1] * q
    if q < 0:
        # math.sqrt raises -- which the search, held above 1, never comes to.
        return False
    W[h] = W[d] / (1 + math.sqrt(q))
    for j in range(1, nm):
        W[h + j] = math.sqrt(W[d + j - 1] * W[d + j])
    W[h + nm] = q
    return True


@njit(cache=True, error_model='numpy')
def _cell_values(fd, adv_f, d_f, diff_fm1, diff_m1f, mmf, mmb, out):
    """``farfield.cell_values``: the transport matrix's values, in the order
    ``cell_structure`` lists them."""
    nm = fd[FD_NM]
    ob = fd[FD_OB]
    NF = fd[FD_NF] + fd[FD_NB]
    frac_loss = -(adv_f + 2 * d_f + diff_fm1)
    for i in range(NF):
        out[i] = frac_loss
    out[0] += d_f
    if ob == 1:
        out[NF - 1] += d_f
    elif ob == 2:
        out[NF - 1] += 2 * d_f
    elif ob == 3:
        out[NF - 1] += 3 * d_f
    i = NF
    for k in range(NF):
        for j in range(1, nm + 1):
            if j == 1:
                out[i] = -(diff_m1f + mmf[0])
            elif j == nm:
                out[i] = -mmb[nm - 2]
            else:
                out[i] = -(mmf[j - 1] + mmb[j - 2])
            i += 1
    for k in range(1, NF):
        out[i] = d_f + adv_f
        if k == NF - 1:
            if ob == 2:
                out[i] -= d_f
            elif ob == 3:
                out[i] -= 3 * d_f
        i += 1
        out[i] = d_f
        i += 1
    if ob == 3:
        out[i] = d_f
        i += 1
    for k in range(NF):
        out[i] = diff_fm1
        out[i + 1] = diff_m1f
        i += 2
    for j in range(nm - 1):
        for k in range(NF):
            out[i] = mmf[j]
            out[i + 1] = mmb[j]
            i += 2


@njit(cache=True, inline='always', error_model='numpy')
def _release_weights(fd, adv_f, d_f, W, at):
    """``farfield.release_weights``, into W[at:]."""
    ob = fd[FD_OB]
    if fd[FD_NB] > 0:
        W[at] = adv_f + d_f
        W[at + 1] = -d_f
    elif ob == 0:
        W[at] = adv_f + d_f
    elif ob == 1:
        W[at] = adv_f
    elif ob == 2:
        W[at] = adv_f - d_f
        W[at + 1] = d_f
    else:
        W[at] = adv_f - 2 * d_f
        W[at + 1] = 3 * d_f
        W[at + 2] = -d_f


@njit(cache=True, inline='always', error_model='numpy')
def _rock_ok(X, fd, slot):
    """``farfield.rock_setting_problem`` of a slot is None: each of the
    rock's settings a number of zero or more."""
    for k in (K_KD_F, K_KD_M, K_DE_M, K_EPS_M, K_RHO_M):
        v = _x(X, fd, slot, k)
        if not (v >= 0) or not math.isfinite(v):
            return False
    return True


@njit(cache=True, error_model='numpy')
def _rates(X, W, fd, slot, layers, depths, diffs, vals):
    """``coefficients`` of one slot -- on the matched layers at W[layers:],
    or the reference ones in ``depths`` -- then ``cell_values`` into the
    derivative's matrix data and ``release_weights`` into the slot's
    weights; False, before anything is written, where the Python ones raise."""
    nf = fd[FD_NF]
    nm = fd[FD_NM]
    pe = _x(X, fd, slot, K_PE)
    if not (pe > 0) or not math.isfinite(pe):
        return False
    aw = _wetted_surface(X, fd, slot)
    if not (aw > 0) or not math.isfinite(aw):
        return False
    tw = _x(X, fd, slot, K_TW)
    if not (tw > 0) or not math.isfinite(tw):
        return False
    if not _rock_ok(X, fd, slot):
        return False
    r_m = _x(X, fd, slot, K_EPS_M) + _x(X, fd, slot, K_RHO_M) * _x(X, fd, slot, K_KD_M)
    if not (r_m > 0) or not math.isfinite(r_m):
        return False
    f_df = 1 / (1 + _x(X, fd, slot, K_KD_F) * aw)
    adv_f = (f_df * nf) / tw
    spread = adv_f * (nf / pe - 0.5)
    d_f = spread if spread > 0.0 else 0.0
    de = _x(X, fd, slot, K_DE_M)
    mmf = diffs[:nm]
    mmb = diffs[nm:]
    if fd[FD_MATCHED] != 0:
        d = layers
        h = layers + nm
        diff_fm1 = (f_df * aw * de) / W[h]
        diff_m1f = de / (r_m * W[d] * W[h])
        for j in range(nm - 1):
            mmf[j] = de / (r_m * W[d + j] * W[h + j + 1])
            mmb[j] = de / (r_m * W[d + j + 1] * W[h + j + 1])
    else:
        diff_fm1 = (f_df * 2 * aw * de) / depths[0]
        diff_m1f = (2 * de) / (r_m * depths[0] * depths[0])
        for j in range(nm - 1):
            mmf[j] = (2 * de) / (r_m * depths[j] * (depths[j] + depths[j + 1]))
            mmb[j] = (2 * de) / (r_m * depths[j + 1] * (depths[j + 1] + depths[j]))
    _cell_values(fd, adv_f, d_f, diff_fm1, diff_m1f, mmf, mmb, vals)
    nnz = fd[FD_NNZ]
    data = fd[FD_DATA]
    pos = FD_HEAD + fd[FD_NNUC] * fd[FD_WIDTH] * fd[FD_NKEYS] + slot * nnz
    for e in range(nnz):
        W[data + fd[pos + e]] = vals[e]
    _release_weights(fd, adv_f, d_f, W, fd[FD_RELW] + slot * fd[FD_NREL])
    return True


@njit(cache=True, inline='always', error_model='numpy')
def _changed(X, W, fd, slot):
    """Whether a setting of ``slot`` is not what it last saw (NaN never is)."""
    n = fd[FD_NKEYS]
    at = FD_HEAD + slot * n
    seen = fd[FD_SEEN] + slot * n
    for i in range(n):
        if X[fd[at + i]] != W[seen + i]:
            return True
    return False


@njit(cache=True, inline='always', error_model='numpy')
def _see(X, W, fd, slot):
    """The slot's settings, as it has now seen them."""
    n = fd[FD_NKEYS]
    at = FD_HEAD + slot * n
    seen = fd[FD_SEEN] + slot * n
    for i in range(n):
        W[seen + i] = X[fd[at + i]]


@njit(cache=True, error_model='numpy')
def refresh(X, W, fd):
    """``FarfPath.refresh`` of the path whose directory is ``fd``: the rates
    and release weights of every slot whose settings moved, on layers laid
    out the first time round. Answers ``DONE``; ``LAID_OUT`` when it laid
    matched layers out; ``ASK_PYTHON`` where the Python refresh raises,
    with what came before that worked out, as the Python one leaves it."""
    nnuc = fd[FD_NNUC]
    width = fd[FD_WIDTH]
    matched = fd[FD_MATCHED] != 0
    laid = fd[FD_LAID]
    work = False
    for o in range(width):
        if matched and W[laid + o] == 0.0:
            work = True
    for slot in range(nnuc * width):
        if work:
            break
        work = _changed(X, W, fd, slot)
    if not work:
        return DONE
    nm = fd[FD_NM]
    nnz = fd[FD_NNZ]
    scratch = np.empty(nnz + 4 * nm)
    vals = scratch[:nnz]
    diffs = scratch[nnz:nnz + 2 * nm]
    depths = scratch[nnz + 2 * nm:nnz + 3 * nm]
    ex = scratch[nnz + 3 * nm:]
    answer = DONE
    for o in range(width):
        lo = o * nnuc
        fresh = matched and W[laid + o] == 0.0
        if not fresh:
            moved = False
            for slot in range(lo, lo + nnuc):
                if _changed(X, W, fd, slot):
                    moved = True
                    break
            if not moved:
                continue
        if fresh:
            if not _lay_out(X, W, fd, o, ex):
                return ASK_PYTHON
        elif not matched:
            # The reference layers follow from settings the combination's
            # nuclides share: worked out once for them all, as the Python
            # refresh works them out with its first slot's rates.
            if not _layer_depths(_x(X, fd, lo, K_PEN_DEP), nm, _wetted_surface(X, fd, lo),
                                 _x(X, fd, lo, K_PEN_DEP_0), depths, ex):
                return ASK_PYTHON
        layers = fd[FD_LAYERS] + o * (2 * nm + 1)
        for slot in range(lo, lo + nnuc):
            if not fresh and not _changed(X, W, fd, slot):
                continue
            if not _rates(X, W, fd, slot, layers, depths, diffs, vals):
                return ASK_PYTHON
            _see(X, W, fd, slot)
        if fresh:
            W[laid + o] = 1.0
            answer = LAID_OUT
    return answer
