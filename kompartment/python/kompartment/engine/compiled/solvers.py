"""The solvers' loops compiled with numba: the NDF, Rosenbrock (2,3) and
Dormand-Prince, each a port of its Python version (``engine/solvers``) with
the same arithmetic in the same order -- the same steps, to the last bit, as
the Python solver running the same derivative.

Each is compiled once for every model and cached on disk: a model's
derivative is handed in as a first-class function of fixed signature (see
:mod:`.model`), so a new model costs the compilation of its derivative only.
The loop never returns to Python between steps, which is what makes a small
model slow in Python; it calls back into Python only for an analytic
Jacobian and for progress, through ``int64(float64, float64)`` callbacks
(:mod:`.run` makes them), and reports how it ended as a status code with the
numbers the Python error messages need.

The iteration matrix is factorised where the Python solver would factorise
it: by the application's dense LU, compiled here (what the Python solvers use
up to 200 states unless a sparse factorisation fills in less), or -- for a
larger or sparser matrix -- by the Python solver's own ``IterationMatrix``
(SuperLU or LAPACK), which the loop calls back to form and to solve with.
"""

from __future__ import annotations

import math

import numpy as np
from numba import cfunc, njit, types

EPS = 2.0 ** -52
SQRT_EPS = math.sqrt(EPS)
MAX_ORDER = 5
KAPPA = np.array([-0.185, -1 / 9, -0.0823, -0.0415, 0.0])
GAMMA = np.array([1.0, 3 / 2, 11 / 6, 25 / 12, 137 / 60])
NEWTON_MAX = 4
NEWTON_TOL = 0.3
RATE_LIMIT = 0.9
RATE_FLOOR = 0.02
CONVERGED_FLOOR = 1e-3
SAFETY = 0.8
SAFETY_LOWER = 0.75
SAFETY_HIGHER = 0.7
MAX_GROWTH = 10.0
NEWTON_CUT = 0.25
STALL_SPAN_FRACTION = 1e-10
MAX_BELOW_TOLERANCE = 20
PROGRESS_EVERY = 64

# How a compiled solve ended; ``fstat`` holds the numbers its message needs.
OK = 0
E_STEPS = 1            # t, max_steps
E_STALLED = 2          # t, window, distance
E_FLOOR = 3            # t, hmin, worst state (one-step methods)
E_FLOOR_NONFINITE = 4  # t, hmin, worst state
E_ERR_NONFINITE = 5    # t
E_SINGULAR = 6         # t, column, value, 1 when the entry was not a number
E_INITIAL = 7          # t, state
E_HISTORY = 8          # a min/max history ran out of room
E_ABORTED = 9          # t: the progress callback said stop
E_CALLBACK = 10        # a callback raised; the driver holds the exception
E_MATRIX = 11          # t: the Python matrix would not factorise; the driver holds why

# Where the iteration matrix is factorised.
MAT_KERNEL = 0         # here, by the application's dense LU
MAT_PYTHON = 1         # by the Python solver's own IterationMatrix (SuperLU, LAPACK), called back

# Jacobian modes.
JAC_DENSE = 0          # differenced, one column at a time (no pattern)
JAC_PATTERN = 1        # differenced through the pattern, one evaluation per colour
JAC_CALLBACK = 2       # the callback's values, differenced where it declines

_F = types.float64
_A = types.float64[::1]
_I = types.int64[::1]
_M = types.float64[:, ::1]
RHS_T = types.FunctionType(types.void(_F, _A, _A, _A, _A, _A, _I))
STORE_T = types.FunctionType(types.int64(_F, _A, _A, _A, _A, _I))
CB_SIG = types.int64(_F, _F)
CB_T = types.FunctionType(CB_SIG)
_OPTS = dict(cache=True, error_model='numpy')


@cfunc(CB_SIG, cache=True)
def no_callback(a, b):  # pragma: no cover - compiled
    """The callback slot when there is nothing to call."""
    return 1


# --- small arithmetic, as the Python solvers do it -----------------------------------------------


@njit(inline='always', **_OPTS)
def _ulp(x):
    a = abs(x)
    if not (a > 0):
        return 5e-324
    e = math.floor(math.log2(a)) - 52
    if e < -1074:
        e = -1074
    return math.ldexp(1.0, e)


@njit(inline='always', **_OPTS)
def _step_floor(t):
    return 16 * _ulp(t)


@njit(inline='always', **_OPTS)
def _pymax(a, b):
    """Python's ``max(a, b)``: ``b`` only when it is greater."""
    return b if b > a else a


@njit(inline='always', **_OPTS)
def _pymin(a, b):
    """Python's ``min(a, b)``: ``b`` only when it is less."""
    return b if b < a else a


@njit(inline='always', **_OPTS)
def _npmax(a, b):
    """numpy's ``maximum``: NaN when either is."""
    if a != a or b != b:
        return np.nan
    return a if a >= b else b


@njit(**_OPTS)
def _seq_ssq(v):
    s = 0.0
    for i in range(v.size):
        s += v[i] * v[i]
    return s


MAX_SOLVER_POINTS = 4000


@njit(**_OPTS)
def _collect(t, y, ct, cy, cint, cflt):
    """``runner.collect``: the accepted steps as output, every stride-th of
    them, the stride doubling (and every other kept) whenever they reach
    twice MAX_SOLVER_POINTS. cint: count, seen, stride; cflt: the last time."""
    if not (t > cflt[0]):
        return
    cflt[0] = t
    seen = cint[1]
    cint[1] = seen + 1
    if seen % cint[2]:
        return
    n = cint[0]
    ct[n] = t
    for i in range(y.size):
        cy[n, i] = y[i]
    n += 1
    if n >= 2 * MAX_SOLVER_POINTS:
        m = 0
        for k in range(0, n, 2):
            ct[m] = ct[k]
            for i in range(y.size):
                cy[m, i] = cy[k, i]
            m += 1
        n = m
        cint[2] *= 2
    cint[0] = n


# --- the NDF's norm (``Weighting``) ------------------------------------------------------------------


@njit(**_OPTS)
def _w_update(inv, y, ynew, threshold, norm_control):
    if norm_control:
        a = math.sqrt(_seq_ssq(y))
        b = math.sqrt(_seq_ssq(ynew))
        inv[0] = 1 / _pymax(_pymax(a, b), threshold[0])
        return
    for i in range(y.size):
        inv[i] = 1 / _npmax(_npmax(abs(y[i]), abs(ynew[i])), threshold[i])


@njit(**_OPTS)
def _w_of(v, inv, norm_control, rms):
    if norm_control:
        return math.sqrt(_seq_ssq(v)) * inv[0]
    if rms:
        if v.size == 0:
            return 0.0
        s = 0.0
        for i in range(v.size):
            a = v[i] * inv[i]
            s += a * a
        return math.sqrt(s / v.size)
    m = 0.0
    for i in range(v.size):
        a = abs(v[i]) * inv[i]
        if a != a:
            return np.nan
        if a > m:
            m = a
    return m


@njit(**_OPTS)
def _w_of_sum(a, b, inv, norm_control, rms, tmp):
    for i in range(a.size):
        tmp[i] = a[i] + b[i]
    return _w_of(tmp, inv, norm_control, rms)


# --- the difference table --------------------------------------------------------------------------


@njit(**_OPTS)
def _basis(s, k, out):
    out[0] = 1.0
    for j in range(1, k + 1):
        out[j] = out[j - 1] * ((s + j - 1) / j)


@njit(**_OPTS)
def _choose(n, r):
    v = 1.0
    for i in range(1, r + 1):
        v = (v * (n - r + i)) / i
    return v


@njit(**_OPTS)
def _regrid(cols, k, s_end, ratio, tmp):
    values = np.zeros((k + 1, k + 1))
    b = np.zeros(k + 1)
    for i in range(k + 1):
        _basis(s_end - i * ratio, k, b)
        for j in range(k + 1):
            values[i, j] = b[j]
    T = np.zeros((k + 1, k + 1))
    for m in range(k + 1):
        for j in range(m, k + 1):
            acc = 0.0
            for i in range(m + 1):
                acc += (-1.0 if i % 2 else 1.0) * _choose(m, i) * values[i, j]
            T[m, j] = acc
    neq = cols.shape[1]
    for m in range(k + 1):
        for q in range(neq):
            tmp[q] = 0.0
        for j in range(m, k + 1):
            w = T[m, j]
            if w == 0:
                continue
            for q in range(neq):
                tmp[q] += w * cols[j, q]
        for q in range(neq):
            cols[m, q] = tmp[q]


@njit(**_OPTS)
def _value_at(cols, k, s, clamp, out, b):
    _basis(s, k, b)
    neq = cols.shape[1]
    for q in range(neq):
        out[q] = cols[0, q]
    for j in range(1, k + 1):
        for q in range(neq):
            out[q] += b[j] * cols[j, q]
    for c in range(clamp.size):
        i = clamp[c]
        if out[i] < 0:
            out[i] = 0.0


@njit(**_OPTS)
def _forget(cols, i):
    for j in range(1, cols.shape[0]):
        cols[j, i] = 0.0


# --- the application's dense LU (``solvers/kernels.py``) ----------------------------------------------


@njit(**_OPTS)
def _factor(lu, piv, fail):
    n = lu.shape[0]
    for i in range(n):
        piv[i] = i
    for k in range(n):
        p = k
        max_abs = abs(lu[k, k])
        for i in range(k + 1, n):
            v = abs(lu[i, k])
            if v > max_abs:
                max_abs = v
                p = i
        if not (max_abs > 0) or not math.isfinite(max_abs):
            fail[0] = k
            fail[1] = max_abs
            return 2 if max_abs != 0 else 1
        if p != k:
            for j in range(n):
                tmp = lu[p, j]
                lu[p, j] = lu[k, j]
                lu[k, j] = tmp
            t = piv[p]
            piv[p] = piv[k]
            piv[k] = t
        pivot = lu[k, k]
        for i in range(k + 1, n):
            f = lu[i, k] / pivot
            if f == 0:
                continue
            lu[i, k] = f
            for j in range(k + 1, n):
                lu[i, j] -= f * lu[k, j]
    return 0


@njit(**_OPTS)
def _form(a, jac_mode, colptr, rowidx, jvals, jdense, held, any_held, lu, piv, fail):
    """I - a*J with the rows ``held`` marks as rows of the identity,
    factorised: 0, or -2 for an entry that is not a number, 1 for a singular
    matrix, 2 for a pivot that is not a number."""
    n = lu.shape[0]
    bad = -1
    bad_value = 0.0
    if jac_mode == JAC_DENSE:
        for j in range(n):
            for i in range(n):
                v = 0.0 if (any_held and held[i] != 0) else -a * jdense[i, j]
                if bad < 0 and not math.isfinite(v):
                    bad = j
                    bad_value = v
                lu[i, j] = v
    else:
        for i in range(n):
            for j in range(n):
                lu[i, j] = 0.0
        for j in range(n):
            for p in range(colptr[j], colptr[j + 1]):
                i = rowidx[p]
                if any_held and held[i] != 0:
                    continue
                v = -a * jvals[p]
                if bad < 0 and not math.isfinite(v):
                    bad = j
                    bad_value = v
                lu[i, j] = v
    if bad >= 0:
        fail[0] = bad
        fail[1] = bad_value
        return -2
    for i in range(n):
        lu[i, i] += 1.0
    return _factor(lu, piv, fail)


@njit(**_OPTS)
def _solve(lu, piv, b, x):
    n = lu.shape[0]
    for i in range(n):
        x[i] = b[piv[i]]
    for i in range(1, n):
        s = x[i]
        for j in range(i):
            s -= lu[i, j] * x[j]
        x[i] = s
    for i in range(n - 1, -1, -1):
        s = x[i]
        for j in range(i + 1, n):
            s -= lu[i, j] * x[j]
        x[i] = s / lu[i, i]


@njit(**_OPTS)
def _singular(fstat, t, fail, st):
    """The status a failed formation ends the solve with: ``st`` from
    :func:`_form_m`."""
    if st == -1:
        return E_CALLBACK
    fstat[0] = t
    if st == 3:
        return E_MATRIX
    fstat[1] = fail[0]
    fstat[2] = fail[1]
    fstat[3] = 1.0 if (st == -2 or st == 2) else 0.0
    return E_SINGULAR


@njit(**_OPTS)
def _form_m(mat_mode, form_cb, a, jac_mode, colptr, rowidx, jvals, jdense, held, any_held, lu, piv, fail):
    """I - a*J formed and factorised where the Python solver would: 0, a
    status of :func:`_form` here, or through the callback 3 (it would not
    factorise) and -1 (it raised)."""
    if mat_mode == MAT_KERNEL:
        return _form(a, jac_mode, colptr, rowidx, jvals, jdense, held, any_held, lu, piv, fail)
    r = form_cb(a, 1.0 if any_held else 0.0)
    if r < 0:
        return -1
    return 3 if r else 0


@njit(**_OPTS)
def _lsolve(mat_mode, solve_cb, lu, piv, b, x, rbuf, xbuf):
    """x = (I - a*J)^-1 b with the latest factorisation; False when the
    callback raised."""
    if mat_mode == MAT_KERNEL:
        _solve(lu, piv, b, x)
        return True
    for i in range(b.size):
        rbuf[i] = b[i]
    if solve_cb(0.0, 0.0) < 0:
        return False
    for i in range(x.size):
        x[i] = xbuf[i]
    return True


# --- the Jacobian (``difference_increment``, ``difference_jacobian``) ---------------------------------


@njit(**_OPTS)
def _increment(y, threshold, dl):
    for j in range(y.size):
        d = SQRT_EPS * _npmax(abs(y[j]), threshold[j])
        if d == 0:
            d = SQRT_EPS
        moved = (y[j] + d) - y[j]
        dl[j] = d if moved == 0 else moved


@njit(**_OPTS)
def _differenced(f, t, y, fy, jac_mode, colptr, rowidx, gptr, gcols, threshold, jvals, jdense,
                 P, X, W, IW, ytry, fd, dl, counts):
    n = y.size
    _increment(y, threshold, dl)
    if jac_mode == JAC_DENSE:
        for j in range(n):
            for q in range(n):
                ytry[q] = y[q]
            ytry[j] = y[j] + dl[j]
            f(t, ytry, fd, P, X, W, IW)
            counts[0] += 1
            for i in range(n):
                jdense[i, j] = (fd[i] - fy[i]) / dl[j]
        return
    for g in range(gptr.size - 1):
        for q in range(n):
            ytry[q] = y[q]
        for gg in range(gptr[g], gptr[g + 1]):
            j = gcols[gg]
            ytry[j] += dl[j]
        f(t, ytry, fd, P, X, W, IW)
        counts[0] += 1
        for gg in range(gptr[g], gptr[g + 1]):
            j = gcols[gg]
            for p in range(colptr[j], colptr[j + 1]):
                i = rowidx[p]
                jvals[p] = (fd[i] - fy[i]) / dl[j]


@njit(**_OPTS)
def _callback_jacobian(jac_cb, t, y, W, ybuf):
    """The callback's Jacobian at (t, y): 1 given, 0 declined, -1 it raised."""
    for i in range(y.size):
        ybuf[i] = y[i]
    r = jac_cb(t, 0.0)
    # The callback worked the algebraic slots out in Python, into X.
    W[0] = np.nan
    return r


# --- the NDF's projected derivative (``_Projected``) --------------------------------------------------


@njit(**_OPTS)
def _proj(f, t, y, out, P, X, W, IW, constrained, push, held_rows, flags, counts):
    """f(t, y) into ``out``, a constrained state at zero whose derivative is
    negative held there; flags[0] says whether anything is held."""
    counts[0] += 1
    f(t, y, out, P, X, W, IW)
    if constrained.size == 0:
        return
    above = True
    for c in range(constrained.size):
        if not (y[constrained[c]] > 0):
            above = False
            break
    if above:
        if flags[0]:
            for c in range(constrained.size):
                held_rows[constrained[c]] = 0
            flags[0] = 0
        return
    anyh = 0
    for c in range(constrained.size):
        i = constrained[c]
        hold = (y[i] <= 0) and (out[i] < 0)
        push[c] = _npmax(push[c], -out[i] if hold else 0.0)
        if hold:
            out[i] = 0.0
            held_rows[i] = 1
            anyh = 1
        else:
            held_rows[i] = 0
    flags[0] = anyh


@njit(**_OPTS)
def _form_w(mat_mode, form_cb, a, jac_mode, colptr, rowidx, jvals, jdense, held_now, held_in_w, constrained,
            lu, piv, fail):
    any_held = False
    if constrained.size:
        for i in range(held_now.size):
            held_in_w[i] = held_now[i]
        for c in range(constrained.size):
            if held_in_w[constrained[c]] != 0:
                any_held = True
                break
    return _form_m(mat_mode, form_cb, a, jac_mode, colptr, rowidx, jvals, jdense, held_in_w, any_held, lu, piv,
                   fail)


@njit(**_OPTS)
def _snap(cols, constrained, atol, mark, below):
    """``snap_onto_bound``: the constrained states above zero but within
    their tolerance that ``mark`` picks -- held (1) or, with ``below``,
    below zero -- put on zero; how many."""
    snapped = 0
    for c in range(constrained.size):
        i = constrained[c]
        sel = mark[i] < 0 if below else mark[i] == 1
        if cols[0, i] > 0 and cols[0, i] <= atol[i] and sel:
            snapped += 1
    if snapped == 0:
        return 0
    for c in range(constrained.size):
        i = constrained[c]
        sel = mark[i] < 0 if below else mark[i] == 1
        if cols[0, i] > 0 and cols[0, i] <= atol[i] and sel:
            cols[0, i] = 0.0
            _forget(cols, i)
    return snapped


# --- the NDF --------------------------------------------------------------------------------------------

NDF_SIG = types.int64(
    RHS_T, STORE_T, CB_T, CB_T, _A, _A, _A, _I,         # f, store, jac_cb, progress, P, X, W, IW
    _A, _A, _A, _I,                                     # tspan, y0, atol, constrained
    types.int64, _I, _I, _A, _I, _I, _A,                # jac_mode, colptr, rowidx, jvals, gptr, gcols, ybuf
    _A, _I, _M, _I, _I, _A,                             # fpar, ipar, yout, held, stats, fstat
    _A, _M, _I, _A,                                     # ct, cy, cint, cflt: the steps as output
    CB_T, CB_T, _M, _I, _A, _A)                         # form_cb, solve_cb, jdense, held_in_w, rbuf, xbuf


@njit(NDF_SIG, **_OPTS)
def ndf(f, store, jac_cb, progress, P, X, W, IW, tspan, y0, atol, constrained,
        jac_mode, colptr, rowidx, jvals, gptr, gcols, ybuf, fpar, ipar, yout, held, stats, fstat,
        ct, cy, cint, cflt, form_cb, solve_cb, jdense, held_in_w, rbuf, xbuf):
    """``engine/solvers/ndf.py``'s ``ndf``, compiled.

    fpar: rtol, hmax, h0, max_steps, stagnation_tol
    ipar: max_order, bdf, norm_control, rms, auto_abstol, below_tol_run
          (-1 for the default), min_newton, stall_window, constant,
          has_store, has_progress, mat_mode
    stats (out): nsteps, nfailed, npds, ndecomps, nsolves, nbelowtol,
          negative, nfevals, rows written
    ``atol`` is raised in place when auto_abstol is on; the accepted steps
    are collected (``_collect``) when cint[3] is set. ``jdense`` (the
    Jacobian without a pattern), ``held_in_w`` (the rows held in the
    matrix), ``rbuf`` and ``xbuf`` (a solve's right-hand side and answer) are
    the caller's, for the matrix callbacks to read and write.
    """
    neq = y0.size
    npts = tspan.size
    t0 = tspan[0]
    t_end = tspan[npts - 1]
    direction = math.copysign(1.0, t_end - t0)
    span = abs(t_end - t0)
    rtol = fpar[0]
    hmax_opt = fpar[1]
    h0 = fpar[2]
    max_steps = fpar[3]
    stagnation_tol = fpar[4]
    max_order = ipar[0]
    bdf = ipar[1] != 0
    norm_control = ipar[2] != 0
    rms = ipar[3] != 0 and not norm_control
    auto_abstol = ipar[4] != 0
    below_tol_run = ipar[5]
    min_newton = ipar[6]
    stall_window = ipar[7]
    constant = ipar[8] != 0
    has_store = ipar[9] != 0
    has_progress = ipar[10] != 0
    mat_mode = ipar[11]
    for q in range(stats.size):
        stats[q] = 0
    counts = np.zeros(1, dtype=np.int64)

    leading = np.zeros(MAX_ORDER + 2)
    error_const = np.zeros(MAX_ORDER + 2)
    for k in range(1, MAX_ORDER + 1):
        kappa = 0.0 if bdf else KAPPA[k - 1]
        leading[k] = (1 - kappa) * GAMMA[k - 1]
        error_const[k] = kappa * GAMMA[k - 1] + 1 / (k + 1)
    threshold = np.empty(neq)
    for i in range(neq):
        threshold[i] = atol[i] / rtol
    newton_threshold = threshold.copy() if auto_abstol else threshold
    einv = np.zeros(1 if norm_control else neq)
    ninv = np.zeros(1 if norm_control else neq) if auto_abstol else einv
    floor_run = MAX_BELOW_TOLERANCE if below_tol_run < 0 else below_tol_run
    floor_newton_run = 0 if below_tol_run < 0 else floor_run
    hmax = _pymin(hmax_opt, span) if hmax_opt > 0 else 0.1 * span

    projected = constrained.size > 0
    push = np.zeros(constrained.size)
    held_rows = np.zeros(neq, dtype=np.int64)
    pflags = np.zeros(1, dtype=np.int64)
    for i in range(neq):
        held[i] = 0

    cols = np.zeros((max_order + 3, neq))
    for i in range(neq):
        cols[0, i] = y0[i]
        yout[0, i] = y0[i]
    row = 1
    next_out = 1
    t = t0
    next_report = PROGRESS_EVERY

    f0 = np.empty(neq)
    _proj(f, t0, cols[0], f0, P, X, W, IW, constrained, push, held_rows, pflags, counts)
    for i in range(neq):
        if not math.isfinite(cols[0, i]) or not math.isfinite(f0[i]):
            fstat[0] = t0
            fstat[1] = i
            stats[7] = counts[0]
            return E_INITIAL

    # --- the Jacobian and the matrix
    ytry = np.empty(neq)
    fd = np.empty(neq)
    dl = np.empty(neq)
    raw = np.empty(neq)
    stats[2] += 1
    got = 0
    if jac_mode == JAC_CALLBACK:
        got = _callback_jacobian(jac_cb, t, cols[0], W, ybuf)
        if got < 0:
            stats[7] = counts[0]
            return E_CALLBACK
    if got == 0:
        _differenced(f, t, cols[0], f0, jac_mode, colptr, rowidx, gptr, gcols, threshold, jvals, jdense,
                     P, X, W, IW, ytry, fd, dl, counts)
    fresh = True
    lu = np.zeros((neq, neq)) if mat_mode == MAT_KERNEL else np.zeros((1, 1))
    piv = np.zeros(neq, dtype=np.int64)
    fail = np.zeros(2)
    held_now = np.zeros(neq, dtype=np.int64)
    for i in range(neq):
        held_in_w[i] = 0

    # --- the first step
    yp = f0.copy()
    tmpv = np.empty(neq)
    y = cols[0]
    if h0 > 0:
        step_size = h0
    else:
        _w_update(einv, y, y, threshold, norm_control)
        d0 = _w_of(y, einv, norm_control, rms) / rtol
        d1 = _w_of(yp, einv, norm_control, rms) / rtol
        guess = 1e-6 if (d0 < 1e-5 or d1 < 1e-5) else 0.01 * (d0 / d1)
        guess = _pymin(guess, hmax)
        trial = np.empty(neq)
        for i in range(neq):
            trial[i] = y[i] + direction * guess * yp[i]
        f1 = np.empty(neq)
        _proj(f, t0 + direction * guess, trial, f1, P, X, W, IW, constrained, push, held_rows, pflags, counts)
        for i in range(neq):
            tmpv[i] = f1[i] - f0[i]
        d2 = _w_of(tmpv, einv, norm_control, rms) / rtol / guess
        if not math.isfinite(d2):
            d2 = 100 * d1
        m = _pymax(d1, d2)
        h1 = _pymax(1e-6, guess * 1e-3) if m <= 1e-15 else math.sqrt(0.01 / m)
        step_size = _pymin(100 * guess, h1)
    step_size = _pymin(hmax, _pymax(_step_floor(t0), step_size))
    h = direction * step_size
    for i in range(neq):
        cols[1, i] = h * yp[i]
    k = 1
    hTable = h
    if projected:
        for i in range(neq):
            held_now[i] = held_rows[i]
    st = _form_w(mat_mode, form_cb, h / leading[k], jac_mode, colptr, rowidx, jvals, jdense, held_now, held_in_w,
                 constrained, lu, piv, fail)
    if st != 0:
        stats[7] = counts[0]
        return _singular(fstat, t, fail, st)
    stats[3] += 1
    hW = h
    kW = k
    rate = -1.0

    consecutive = 0
    mask_reforms = 0
    below_run = 0
    tnew = t0
    stall_step = 0
    stall_t = t0
    stall_h = 0.0
    d = np.zeros(neq)
    delta = xbuf
    resid = rbuf
    pred = np.zeros(neq)
    hist = np.zeros(neq)
    ynew = np.zeros(neq)
    fv = np.zeros(neq)
    b = np.zeros(max_order + 3)
    dense = np.zeros(neq)
    err = 0.0

    while True:
        hmin = _step_floor(t)
        step_size = _pymin(hmax, _pymax(hmin, abs(h)))
        last = False
        h_try = direction * step_size
        if 1.1 * step_size >= abs(t_end - t):
            h_try = t_end - t
            last = True
        if h_try != hTable:
            _regrid(cols, k, 0.0, h_try / hTable, tmpv)
            hTable = h_try
            consecutive = 0
        h = h_try
        mask_reforms = 0
        y = cols[0]
        if projected:
            anyle = False
            for c in range(constrained.size):
                if y[constrained[c]] <= 0:
                    anyle = True
                    break
            if anyle:
                _proj(f, t, y, raw, P, X, W, IW, constrained, push, held_rows, pflags, counts)
            for i in range(neq):
                held_now[i] = held_rows[i]
        moved = False
        if projected:
            for c in range(constrained.size):
                if held_now[constrained[c]] != held_in_w[constrained[c]]:
                    moved = True
                    break
        if h != hW or k != kW or moved:
            st = _form_w(mat_mode, form_cb, h / leading[k], jac_mode, colptr, rowidx, jvals, jdense, held_now,
                         held_in_w, constrained, lu, piv, fail)
            if st != 0:
                stats[7] = counts[0]
                return _singular(fstat, t, fail, st)
            stats[3] += 1
            hW = h
            kW = k
            rate = -1.0

        err = 0.0
        first_failure = True
        while True:
            tnew = t_end if last else t + h
            for i in range(neq):
                pred[i] = cols[0, i]
            for j in range(1, k + 1):
                for i in range(neq):
                    pred[i] += cols[j, i]
            for i in range(neq):
                hist[i] = 0.0
            for j in range(1, k + 1):
                g = GAMMA[j - 1]
                for i in range(neq):
                    hist[i] += g * cols[j, i]
            for i in range(neq):
                ynew[i] = pred[i]
                d[i] = 0.0
            for c in range(constrained.size):
                push[c] = 0.0
            _w_update(einv, y, ynew, threshold, norm_control)
            if auto_abstol:
                _w_update(ninv, y, ynew, newton_threshold, norm_control)
            roundoff = 100 * EPS * _w_of(ynew, ninv, norm_control, rms)
            outcome = 0                      # 0 converged, 1 not a number, 2 too slow
            prev = 0.0
            rho = rate
            scale = 1 / leading[k]
            for it in range(1, NEWTON_MAX + 1):
                _proj(f, tnew, ynew, fv, P, X, W, IW, constrained, push, held_rows, pflags, counts)
                for i in range(neq):
                    resid[i] = (h * fv[i] - hist[i]) * scale - d[i]
                if mat_mode == MAT_KERNEL:
                    _solve(lu, piv, resid, delta)
                elif solve_cb(0.0, 0.0) < 0:
                    stats[7] = counts[0]
                    return E_CALLBACK
                stats[4] += 1
                size = _w_of(delta, ninv, norm_control, rms)
                if not math.isfinite(size):
                    outcome = 1
                    break
                for i in range(neq):
                    d[i] = d[i] + delta[i]
                    ynew[i] = pred[i] + d[i]
                if size <= roundoff or size <= CONVERGED_FLOOR * rtol:
                    break
                if it == 1:
                    if min_newton <= 1 and rate >= 0 and (rate / (1 - rate)) * size <= NEWTON_TOL * rtol:
                        break
                    prev = size
                    continue
                ratio = size / prev
                if ratio >= RATE_LIMIT:
                    if stagnation_tol > 0 and fresh and size <= stagnation_tol * rtol:
                        break
                    outcome = 2
                    break
                rho = _pymax(ratio, RATE_FLOOR)
                remaining = (rho / (1 - rho)) * size
                if remaining <= NEWTON_TOL * rtol and it >= min_newton:
                    break
                if it == NEWTON_MAX or remaining * rho ** float(NEWTON_MAX - it) > NEWTON_TOL * rtol:
                    outcome = 2
                    break
                prev = size

            if outcome != 0:
                stats[1] += 1
                if projected:
                    snapped = _snap(cols, constrained, atol, held_rows, False)
                    if snapped:
                        stats[6] += snapped
                        _proj(f, t, cols[0], raw, P, X, W, IW, constrained, push, held_rows, pflags, counts)
                        for i in range(neq):
                            held_now[i] = held_rows[i]
                        st = _form_w(mat_mode, form_cb, h / leading[k], jac_mode, colptr, rowidx, jvals, jdense,
                                     held_now, held_in_w, constrained, lu, piv, fail)
                        if st != 0:
                            stats[7] = counts[0]
                            return _singular(fstat, t, fail, st)
                        stats[3] += 1
                        hW = h
                        kW = k
                        rate = -1.0
                        continue
                if not fresh:
                    stats[2] += 1
                    got = 0
                    if jac_mode == JAC_CALLBACK:
                        got = _callback_jacobian(jac_cb, t, cols[0], W, ybuf)
                        if got < 0:
                            stats[7] = counts[0]
                            return E_CALLBACK
                    if got == 0:
                        f(t, cols[0], raw, P, X, W, IW)
                        counts[0] += 1
                        _differenced(f, t, cols[0], raw, jac_mode, colptr, rowidx, gptr, gcols, threshold, jvals,
                                     jdense, P, X, W, IW, ytry, fd, dl, counts)
                    fresh = True
                    if projected:
                        for i in range(neq):
                            held_now[i] = held_rows[i]
                    st = _form_w(mat_mode, form_cb, h / leading[k], jac_mode, colptr, rowidx, jvals, jdense, held_now,
                                 held_in_w, constrained, lu, piv, fail)
                    if st != 0:
                        stats[7] = counts[0]
                        return _singular(fstat, t, fail, st)
                    stats[3] += 1
                    hW = h
                    kW = k
                    rate = -1.0
                    continue
                if abs(h) <= hmin:
                    if outcome == 1 or below_run >= floor_newton_run:
                        fstat[0] = t
                        fstat[1] = hmin
                        stats[7] = counts[0]
                        return E_FLOOR_NONFINITE if outcome == 1 else E_FLOOR
                    below_run += 1
                    stats[5] += 1
                    err = rtol
                    break
                h_new = direction * _pymax(_step_floor(t), abs(h) * NEWTON_CUT)
                if h_new != hTable:
                    _regrid(cols, k, 0.0, h_new / hTable, tmpv)
                    hTable = h_new
                h = h_new
                consecutive = 0
                mask_reforms = 0
                last = False
                st = _form_w(mat_mode, form_cb, h / leading[k], jac_mode, colptr, rowidx, jvals, jdense, held_now,
                             held_in_w, constrained, lu, piv, fail)
                if st != 0:
                    stats[7] = counts[0]
                    return _singular(fstat, t, fail, st)
                stats[3] += 1
                hW = h
                kW = k
                rate = -1.0
                continue
            if mask_reforms < 1 and projected:
                released = False
                for c in range(constrained.size):
                    i = constrained[c]
                    if held_in_w[i] == 1 and held_rows[i] == 0:
                        held_now[i] = 0
                        released = True
                if released:
                    mask_reforms += 1
                    stats[1] += 1
                    st = _form_w(mat_mode, form_cb, h / leading[k], jac_mode, colptr, rowidx, jvals, jdense, held_now,
                                 held_in_w, constrained, lu, piv, fail)
                    if st != 0:
                        stats[7] = counts[0]
                        return _singular(fstat, t, fail, st)
                    stats[3] += 1
                    hW = h
                    kW = k
                    rate = -1.0
                    continue
            rate = rho

            err = error_const[k] * _w_of(d, einv, norm_control, rms)
            if not math.isfinite(err):
                fstat[0] = t
                stats[7] = counts[0]
                return E_ERR_NONFINITE
            for_constraint = False
            if projected:
                worst = 0.0
                for c in range(constrained.size):
                    i = constrained[c]
                    v = -ynew[i] / threshold[i] if ynew[i] < 0 else 0.0
                    if v != v:
                        worst = np.nan
                        break
                    if c == 0 or v > worst:
                        worst = v
                if worst > rtol and worst > err:
                    err = worst
                    for_constraint = True
            if err <= rtol:
                below_run = 0
                break
            stats[1] += 1
            if for_constraint:
                snapped = _snap(cols, constrained, atol, ynew, True)
                if snapped:
                    stats[6] += snapped
                    _proj(f, t, cols[0], raw, P, X, W, IW, constrained, push, held_rows, pflags, counts)
                    for i in range(neq):
                        held_now[i] = held_rows[i]
                    st = _form_w(mat_mode, form_cb, h / leading[k], jac_mode, colptr, rowidx, jvals, jdense, held_now,
                                 held_in_w, constrained, lu, piv, fail)
                    if st != 0:
                        stats[7] = counts[0]
                        return _singular(fstat, t, fail, st)
                    stats[3] += 1
                    hW = h
                    kW = k
                    rate = -1.0
                    continue
            if abs(h) <= hmin:
                if below_run >= floor_run:
                    fstat[0] = t
                    fstat[1] = hmin
                    stats[7] = counts[0]
                    return E_FLOOR
                below_run += 1
                stats[5] += 1
                break
            if first_failure:
                first_failure = False
                factor = _pymax(0.1, SAFETY * (rtol / err) ** (1 / (k + 1)))
                if k > 1:
                    err_lower = error_const[k - 1] * _w_of_sum(cols[k], d, einv, norm_control, rms, tmpv)
                    lower = _pymax(0.1, SAFETY_LOWER * (rtol / err_lower) ** (1 / k)) if err_lower > 0 else np.inf
                    if lower > factor:
                        k = k - 1
                        factor = _pymin(1.0, lower)
            else:
                factor = 0.5
            h_new = direction * _pymax(_step_floor(t), abs(h) * factor)
            if h_new != hTable:
                _regrid(cols, k, 0.0, h_new / hTable, tmpv)
                hTable = h_new
            h = h_new
            consecutive = 0
            mask_reforms = 0
            last = False
            st = _form_w(mat_mode, form_cb, h / leading[k], jac_mode, colptr, rowidx, jvals, jdense, held_now,
                         held_in_w, constrained, lu, piv, fail)
            if st != 0:
                stats[7] = counts[0]
                return _singular(fstat, t, fail, st)
            stats[3] += 1
            hW = h
            kW = k
            rate = -1.0

        # --- accepted
        stats[0] += 1
        if stats[0] > max_steps:
            fstat[0] = t
            fstat[1] = max_steps
            stats[7] = counts[0]
            return E_STEPS
        if stats[0] - stall_step >= stall_window:
            crawling = abs(tnew - stall_t) < span * STALL_SPAN_FRACTION
            not_growing = abs(h) <= 2 * stall_h
            if crawling and not_growing:
                fstat[0] = tnew
                fstat[1] = stall_window
                fstat[2] = span * STALL_SPAN_FRACTION
                stats[7] = counts[0]
                return E_STALLED
            stall_step = stats[0]
            stall_t = tnew
            stall_h = abs(h)

        for i in range(neq):
            cols[k + 2, i] = d[i] - cols[k + 1, i]
            cols[k + 1, i] = d[i]
        for j in range(k, -1, -1):
            for i in range(neq):
                cols[j, i] += cols[j + 1, i]
        y = cols[0]
        if projected:
            for c in range(constrained.size):
                i = constrained[c]
                if y[i] < 0:
                    y[i] = 0.0
                    stats[6] += 1
                    _forget(cols, i)
            for c in range(constrained.size):
                i = constrained[c]
                if push[c] * abs(h) > atol[i]:
                    held[i] += 1

        while next_out < npts:
            tq = tspan[next_out]
            if direction * (tnew - tq) < 0:
                break
            if tq == tnew:
                for i in range(neq):
                    dense[i] = cols[0, i]
            else:
                _value_at(cols, k, (tq - tnew) / h, constrained, dense, b)
            for i in range(neq):
                yout[row, i] = dense[i]
            row += 1
            if has_store and store(tq, dense, P, X, W, IW) != 0:
                stats[7] = counts[0]
                stats[8] = row
                return E_HISTORY
            next_out += 1
        if has_store and store(tnew, cols[0], P, X, W, IW) != 0:
            stats[7] = counts[0]
            stats[8] = row
            return E_HISTORY
        if cint[3]:
            _collect(tnew, cols[0], ct, cy, cint, cflt)
        if has_progress and counts[0] >= next_report:
            next_report = counts[0] + PROGRESS_EVERY
            r = progress(_pymin(1.0, abs(tnew - t0) / span), tnew)
            if r <= 0:
                fstat[0] = tnew
                stats[7] = counts[0]
                stats[8] = row
                return E_ABORTED if r == 0 else E_CALLBACK

        t = tnew
        if auto_abstol:
            for i in range(neq):
                fl = rtol * abs(cols[0, i])
                if fl > atol[i]:
                    atol[i] = fl
                    threshold[i] = fl / rtol
        if last:
            break

        consecutive += 1
        if consecutive >= k + 1:
            best = _pymin(MAX_GROWTH, SAFETY * (rtol / err) ** (1 / (k + 1))) if err > 0 else MAX_GROWTH
            best_k = k
            if k > 1:
                e_lower = error_const[k - 1] * _w_of(cols[k], einv, norm_control, rms)
                g = _pymin(MAX_GROWTH, SAFETY_LOWER * (rtol / e_lower) ** (1 / k)) if e_lower > 0 else MAX_GROWTH
                if g > best:
                    best = g
                    best_k = k - 1
            if k < max_order:
                e_higher = error_const[k + 1] * _w_of(cols[k + 2], einv, norm_control, rms)
                g = _pymin(MAX_GROWTH, SAFETY_HIGHER * (rtol / e_higher) ** (1 / (k + 2))) if e_higher > 0 \
                    else MAX_GROWTH
                if g > best:
                    best = g
                    best_k = k + 1
            if best > 1:
                k = best_k
                h *= best
                consecutive = 0
        if not constant:
            fresh = False

    stats[7] = counts[0]
    stats[8] = row
    return OK


# --- the one-step methods (``solvers/onestep.py``, ``rosenbrock23.py``, ``dormand_prince.py``) ----------

ONESTEP_STALL_FRACTION = 1e-9
MAX_AT_FLOOR = 20
ONESTEP_SAFETY = 0.9
SHRINK_LEAST = 0.1
GROW_MOST = 5.0
ROS_D = 1 / (2 + math.sqrt(2))
ROS_E32 = 6 + math.sqrt(2)
DP_NODES = np.array([1 / 5, 3 / 10, 4 / 5, 8 / 9, 1.0, 1.0])
DP_STAGE = np.array([
    [1 / 5, 0.0, 0.0, 0.0, 0.0, 0.0],
    [3 / 40, 9 / 40, 0.0, 0.0, 0.0, 0.0],
    [44 / 45, -56 / 15, 32 / 9, 0.0, 0.0, 0.0],
    [19372 / 6561, -25360 / 2187, 64448 / 6561, -212 / 729, 0.0, 0.0],
    [9017 / 3168, -355 / 33, 46732 / 5247, 49 / 176, -5103 / 18656, 0.0],
    [35 / 384, 0.0, 500 / 1113, 125 / 192, -2187 / 6784, 11 / 84],
])
DP_ERROR = np.array([71 / 57600, 0.0, -71 / 16695, 71 / 1920, -17253 / 339200, 22 / 525, -1 / 40])
DP_DENSE = np.array([
    [1.0, -183 / 64, 37 / 12, -145 / 128],
    [0.0, 0.0, 0.0, 0.0],
    [0.0, 1500 / 371, -1000 / 159, 1000 / 371],
    [0.0, -125 / 32, 125 / 12, -375 / 64],
    [0.0, 9477 / 3392, -729 / 106, 25515 / 6784],
    [0.0, -11 / 7, 11 / 3, -55 / 28],
    [0.0, 3 / 2, -4.0, 5 / 2],
])


@njit(**_OPTS)
def _weighted(v, ya, yb, threshold):
    """``kernels._weighted``: the largest |v| / max(|ya|, |yb|, threshold)
    and where; NaN and the first index where it is not a number."""
    worst = 0.0
    at = 0
    for i in range(v.size):
        s = _pymax(_pymax(abs(ya[i]), abs(yb[i])), threshold[i])
        e = abs(v[i]) / s
        if not (e >= 0) or not math.isfinite(yb[i]):
            return np.nan, i
        if i == 0 or e > worst:
            worst = e
            at = i
    if worst > 0:
        return worst, at
    return 0.0, 0


@njit(**_OPTS)
def _held(f, t, y, out, P, X, W, IW, nn_idx, push, hold_on):
    """f(t, y) into ``out``, held at zero as ``HeldDerivative`` holds it
    when ``hold_on``."""
    f(t, y, out, P, X, W, IW)
    if not hold_on:
        return
    above = True
    for c in range(nn_idx.size):
        if not (y[nn_idx[c]] > 0):
            above = False
            break
    if above:
        return
    for c in range(nn_idx.size):
        i = nn_idx[c]
        if y[i] <= 0 and out[i] < 0:
            push[i] = _npmax(push[i], -out[i])
            out[i] = 0.0


@njit(**_OPTS)
def _any_below(v, nn_idx):
    for c in range(nn_idx.size):
        if v[nn_idx[c]] < 0:
            return True
    return False


@njit(**_OPTS)
def _ros_jacobian(f, jac_cb, t, y, f0, jac_mode, colptr, rowidx, gptr, gcols, threshold, jvals, jdense,
                  P, X, W, IW, ytry, fd, dl, ybuf, nn_idx, push, hold_on):
    """``_Stepper._jacobian``: the callback's values, else differenced with
    the held derivative. The evaluations spent (the callback's count
    none), or -1 when the callback raised."""
    if jac_mode == JAC_CALLBACK:
        r = _callback_jacobian(jac_cb, t, y, W, ybuf)
        if r < 0:
            return -1
        if r == 1:
            return 0
    n = y.size
    _increment(y, threshold, dl)
    if jac_mode == JAC_DENSE:
        for j in range(n):
            for q in range(n):
                ytry[q] = y[q]
            ytry[j] = y[j] + dl[j]
            _held(f, t, ytry, fd, P, X, W, IW, nn_idx, push, hold_on)
            for i in range(n):
                jdense[i, j] = (fd[i] - f0[i]) / dl[j]
        return n
    ngroups = gptr.size - 1
    for g in range(ngroups):
        for q in range(n):
            ytry[q] = y[q]
        for gg in range(gptr[g], gptr[g + 1]):
            j = gcols[gg]
            ytry[j] += dl[j]
        _held(f, t, ytry, fd, P, X, W, IW, nn_idx, push, hold_on)
        for gg in range(gptr[g], gptr[g + 1]):
            j = gcols[gg]
            for p in range(colptr[j], colptr[j + 1]):
                i = rowidx[p]
                jvals[p] = (fd[i] - f0[i]) / dl[j]
    return ngroups


ONESTEP_SIG = types.int64(
    RHS_T, STORE_T, CB_T, CB_T, _A, _A, _A, _I,         # f, store, jac_cb, progress, P, X, W, IW
    _A, _A, _A, _I,                                     # tspan, y0, atol, nn_idx
    types.int64, _I, _I, _A, _I, _I, _A,                # jac_mode, colptr, rowidx, jvals, gptr, gcols, ybuf
    _A, _I, _M, _I, _I, _A,                             # fpar, ipar, yout, held, stats, fstat
    _A, _M, _I, _A,                                     # ct, cy, cint, cflt: the steps as output
    CB_T, CB_T, _M, _A, _A)                             # form_cb, solve_cb, jdense, rbuf, xbuf


@njit(ONESTEP_SIG, **_OPTS)
def onestep(f, store, jac_cb, progress, P, X, W, IW, tspan, y0, atol, nn_idx,
            jac_mode, colptr, rowidx, jvals, gptr, gcols, ybuf, fpar, ipar, yout, held, stats, fstat,
            ct, cy, cint, cflt, form_cb, solve_cb, jdense, rbuf, xbuf):
    """``engine/solvers/onestep.py``'s ``integrate`` with the Rosenbrock
    (2,3) or the Dormand-Prince stepper, compiled.

    fpar: rtol, hmax, h0, max_steps, hmin
    ipar: method (0 Rosenbrock, 1 Dormand-Prince), constant, has_store,
          has_progress, stall_window, mat_mode
    stats (out): nsteps, nfailed, nfevals, nbelowtol, negative, npds,
          ndecomps, rows written
    """
    neq = y0.size
    npts = tspan.size
    t0 = tspan[0]
    t_end = tspan[npts - 1]
    direction = 1.0 if t_end > t0 else -1.0
    span = abs(t_end - t0)
    rtol = fpar[0]
    hmax_opt = fpar[1]
    h0 = fpar[2]
    max_steps = fpar[3]
    hmin_opt = fpar[4]
    ros = ipar[0] == 0
    constant = ipar[1] != 0
    has_store = ipar[2] != 0
    has_progress = ipar[3] != 0
    stall_window = ipar[4]
    mat_mode = ipar[5]
    has_nn = nn_idx.size > 0
    hold_on = has_nn and ros
    exponent = 1 / ((2 if ros else 4) + 1)
    stall_span = ONESTEP_STALL_FRACTION * span
    hmax = _pymin(hmax_opt, span) if hmax_opt > 0 else 0.1 * span
    threshold = np.empty(neq)
    for i in range(neq):
        threshold[i] = atol[i] / rtol
    is_nn = np.zeros(neq, dtype=np.int64)
    for c in range(nn_idx.size):
        is_nn[nn_idx[c]] = 1
    for q in range(stats.size):
        stats[q] = 0
    for i in range(neq):
        held[i] = 0
    push = np.zeros(neq)
    nsteps = 0
    nfailed = 0
    nfevals = 0
    nbelowtol = 0
    negative = 0
    npds = 0
    ndecomps = 0

    y = y0.copy()
    for i in range(neq):
        yout[0, i] = y[i]
    row = 1
    next_out = 1
    t = t0
    ynew = np.zeros(neq)
    err_vec = np.zeros(neq)
    dense = np.zeros(neq)
    ftmp = np.zeros(neq)

    # --- the stepper
    f0 = np.zeros(neq)
    ft = np.zeros(neq)
    f1 = np.zeros(neq)
    f2 = np.zeros(neq)
    k1 = np.zeros(neq)
    k2 = np.zeros(neq)
    k3 = np.zeros(neq)
    ymid = np.zeros(neq)
    tmp = np.zeros(neq)
    kk = np.zeros((7, neq)) if not ros else np.zeros((1, 1))
    y_from = np.zeros(neq)
    t_from = t0
    h_from = 1.0
    lu = np.zeros((neq, neq)) if (ros and mat_mode == MAT_KERNEL) else np.zeros((1, 1))
    piv = np.zeros(neq, dtype=np.int64)
    fail = np.zeros(2)
    ytry = np.zeros(neq)
    fd = np.zeros(neq)
    dl = np.zeros(neq)
    need_jacobian = True
    dfdt_at = np.nan
    spent = 0

    if ros:
        _held(f, t, y, f0, P, X, W, IW, nn_idx, push, hold_on)
        if _ros_jacobian(f, jac_cb, t, y, f0, jac_mode, colptr, rowidx, gptr, gcols, threshold, jvals, jdense,
                         P, X, W, IW, ytry, fd, dl, ybuf, nn_idx, push, hold_on) < 0:
            return E_CALLBACK
        npds += 1
        need_jacobian = False
        nfevals += 1
        fstart = f0
    else:
        f(t, y, kk[0], P, X, W, IW)
        nfevals += 1
        fstart = kk[0]

    if h0 > 0:
        step_size = h0
    else:
        d0 = _weighted(y, y, y, threshold)[0] / rtol
        d1 = _weighted(fstart, y, y, threshold)[0] / rtol
        guess = 1e-6 if (d0 < 1e-5 or d1 < 1e-5) else 0.01 * (d0 / d1)
        guess = _pymin(guess, hmax)
        trial = np.empty(neq)
        for i in range(neq):
            trial[i] = y[i] + direction * guess * fstart[i]
        _held(f, t0 + direction * guess, trial, ftmp, P, X, W, IW, nn_idx, push, hold_on)
        nfevals += 1
        for i in range(neq):
            ftmp[i] = ftmp[i] - fstart[i]
        d2 = _weighted(ftmp, y, y, threshold)[0] / rtol / guess
        if not math.isfinite(d2):
            d2 = 100 * d1
        m = _pymax(d1, d2)
        h1 = _pymax(1e-6, guess * 1e-3) if m <= 1e-15 else (0.01 / m) ** exponent
        step_size = _pymin(100 * guess, h1)
    step_size = _pymin(hmax, _pymax(_pymax(16 * EPS * abs(t0), hmin_opt), step_size))
    at_floor = 0
    stall_step = 0
    stall_t = t0
    err = 0.0
    while True:
        if nsteps > max_steps:
            fstat[0] = t
            fstat[1] = max_steps
            stats[2] = nfevals
            return E_STEPS
        hmin = _pymax(16 * EPS * abs(t), hmin_opt)
        step_size = _pymin(hmax, _pymax(hmin, step_size))
        h = direction * step_size
        last = False
        if 1.1 * step_size >= abs(t_end - t):
            h = t_end - t
            step_size = abs(h)
            last = True
        err = 0.0
        worst_at = 0
        failed_once = False
        restart = False
        tnew = t
        while True:
            tnew = t_end if last else t + h
            h = tnew - t
            # --- attempt
            if ros:
                before = spent
                if need_jacobian and not (constant and npds > 0):
                    used = _ros_jacobian(f, jac_cb, t, y, f0, jac_mode, colptr, rowidx, gptr, gcols, threshold,
                                         jvals, jdense, P, X, W, IW, ytry, fd, dl, ybuf, nn_idx, push, hold_on)
                    if used < 0:
                        stats[2] = nfevals
                        return E_CALLBACK
                    spent += used
                    npds += 1
                need_jacobian = False
                if dfdt_at != t:
                    dt = math.copysign(_pymin(SQRT_EPS * _pymax(abs(t), abs(t + h)), abs(h)), h)
                    _held(f, t + dt, y, ftmp, P, X, W, IW, nn_idx, push, hold_on)
                    spent += 1
                    for i in range(neq):
                        ft[i] = (ftmp[i] - f0[i]) / dt
                    dfdt_at = t
                st = _form_m(mat_mode, form_cb, h * ROS_D, jac_mode, colptr, rowidx, jvals, jdense, held, False,
                             lu, piv, fail)
                if st != 0:
                    stats[2] = nfevals
                    return _singular(fstat, t, fail, st)
                ndecomps += 1
                hD = h * ROS_D
                half_h = 0.5 * h
                for i in range(neq):
                    tmp[i] = f0[i] + hD * ft[i]
                if not _lsolve(mat_mode, solve_cb, lu, piv, tmp, k1, rbuf, xbuf):
                    stats[2] = nfevals
                    return E_CALLBACK
                for i in range(neq):
                    ymid[i] = y[i] + half_h * k1[i]
                _held(f, t + 0.5 * h, ymid, f1, P, X, W, IW, nn_idx, push, hold_on)
                for i in range(neq):
                    tmp[i] = f1[i] - k1[i]
                if not _lsolve(mat_mode, solve_cb, lu, piv, tmp, k2, rbuf, xbuf):
                    stats[2] = nfevals
                    return E_CALLBACK
                for i in range(neq):
                    k2[i] += k1[i]
                for i in range(neq):
                    ynew[i] = y[i] + h * k2[i]
                _held(f, tnew, ynew, f2, P, X, W, IW, nn_idx, push, hold_on)
                for i in range(neq):
                    tmp[i] = f2[i] - ROS_E32 * (k2[i] - f1[i]) - 2 * (k1[i] - f0[i]) + hD * ft[i]
                if not _lsolve(mat_mode, solve_cb, lu, piv, tmp, k3, rbuf, xbuf):
                    stats[2] = nfevals
                    return E_CALLBACK
                for i in range(neq):
                    err_vec[i] = k1[i] - 2 * k2[i] + k3[i]
                spent += 2
                t_from = t
                h_from = h
                for i in range(neq):
                    y_from[i] = y[i]
                nfevals += spent - before
                scale = 1 / 6
            else:
                for s in range(5):
                    for i in range(neq):
                        tmp[i] = 0.0
                    for j in range(s + 1):
                        c = DP_STAGE[s, j]
                        if c != 0:
                            for i in range(neq):
                                tmp[i] = tmp[i] + c * kk[j, i]
                    for i in range(neq):
                        ymid[i] = y[i] + h * tmp[i]
                    f(t + h * DP_NODES[s], ymid, kk[s + 1], P, X, W, IW)
                for i in range(neq):
                    tmp[i] = 0.0
                for j in range(6):
                    c = DP_STAGE[5, j]
                    if c != 0:
                        for i in range(neq):
                            tmp[i] = tmp[i] + c * kk[j, i]
                for i in range(neq):
                    ynew[i] = y[i] + h * tmp[i]
                f(tnew, ynew, kk[6], P, X, W, IW)
                for i in range(neq):
                    err_vec[i] = 0.0
                for j in range(7):
                    c = DP_ERROR[j]
                    if c != 0:
                        for i in range(neq):
                            err_vec[i] = err_vec[i] + c * kk[j, i]
                t_from = t
                h_from = h
                for i in range(neq):
                    y_from[i] = y[i]
                nfevals += 6
                scale = 1.0
            worst, worst_at = _weighted(err_vec, y, ynew, threshold)
            err = worst * step_size * scale
            if not math.isfinite(err):
                nfailed += 1
                if step_size <= hmin:
                    fstat[0] = t
                    fstat[1] = hmin
                    fstat[2] = worst_at
                    stats[2] = nfevals
                    return E_FLOOR_NONFINITE
                failed_once = True
                step_size = _pymax(hmin, 0.1 * step_size)
                h = direction * step_size
                last = False
                continue
            for_constraint = False
            if has_nn and err <= rtol and _any_below(ynew, nn_idx):
                at = 0
                vat = 0.0
                for i in range(neq):
                    v = -ynew[i] / threshold[i] if (is_nn[i] != 0 and ynew[i] < 0) else 0.0
                    if v != v:
                        if vat == vat:
                            at = i
                            vat = v
                        break
                    if i == 0 or v > vat:
                        at = i
                        vat = v
                if vat > 0 and vat > rtol:
                    err = vat
                    worst_at = at
                    for_constraint = True
            if err <= rtol:
                at_floor = 0
                break
            nfailed += 1
            if for_constraint and ros:
                snapped = False
                for i in range(neq):
                    if is_nn[i] != 0 and ynew[i] < 0 and y[i] > 0 and y[i] <= atol[i]:
                        snapped = True
                        break
                if snapped:
                    for i in range(neq):
                        if is_nn[i] != 0 and ynew[i] < 0 and y[i] > 0 and y[i] <= atol[i]:
                            y[i] = 0.0
                    _held(f, t, y, f0, P, X, W, IW, nn_idx, push, hold_on)
                    need_jacobian = True
                    dfdt_at = np.nan
                    nfevals += 1
                    restart = True
                    break
            before_size = step_size
            if for_constraint or failed_once:
                step_size = _pymax(hmin, 0.5 * step_size)
            else:
                step_size = _pymax(hmin, step_size * _pymax(SHRINK_LEAST,
                                                            ONESTEP_SAFETY * (rtol / err) ** exponent))
            failed_once = True
            if step_size <= hmin:
                at_floor += 1
                if at_floor >= MAX_AT_FLOOR:
                    fstat[0] = t
                    fstat[1] = hmin
                    fstat[2] = worst_at
                    stats[2] = nfevals
                    return E_FLOOR
                step_size = before_size
                nbelowtol += 1
                break
            h = direction * step_size
            last = False
        if restart:
            continue
        nsteps += 1
        reprojected = False
        if has_nn:
            if _any_below(ynew, nn_idx):
                for i in range(neq):
                    if is_nn[i] != 0 and ynew[i] < 0:
                        ynew[i] = 0.0
                        negative += 1
                reprojected = True
            if hold_on:
                for i in range(neq):
                    if push[i] * step_size > atol[i]:
                        held[i] += 1
                    push[i] = 0.0
        if nsteps - stall_step >= stall_window:
            if abs(tnew - stall_t) < stall_span:
                fstat[0] = tnew
                fstat[1] = stall_window
                fstat[2] = stall_span
                stats[2] = nfevals
                return E_STALLED
            stall_step = nsteps
            stall_t = tnew
        while next_out < npts:
            tq = tspan[next_out]
            if direction * (tnew - tq) < 0:
                break
            if tq == tnew:
                for i in range(neq):
                    dense[i] = ynew[i]
            else:
                s = (tq - t_from) / h_from
                if ros:
                    a1 = s * h_from
                    a2 = s * s * h_from
                    for i in range(neq):
                        dense[i] = y_from[i] + a1 * f0[i] + a2 * (k2[i] - f0[i])
                else:
                    s2 = s * s
                    s3 = s2 * s
                    s4 = s3 * s
                    for i in range(neq):
                        tmp[i] = 0.0
                    for j in range(7):
                        w = DP_DENSE[j, 0] * s + DP_DENSE[j, 1] * s2 + DP_DENSE[j, 2] * s3 + DP_DENSE[j, 3] * s4
                        if w != 0:
                            for i in range(neq):
                                tmp[i] = tmp[i] + w * kk[j, i]
                    for i in range(neq):
                        dense[i] = y_from[i] + h_from * tmp[i]
                if has_nn:
                    for i in range(neq):
                        if is_nn[i] != 0 and dense[i] < 0:
                            dense[i] = 0.0
            for i in range(neq):
                yout[row, i] = dense[i]
            row += 1
            if has_store and store(tq, dense, P, X, W, IW) != 0:
                stats[2] = nfevals
                stats[7] = row
                return E_HISTORY
            next_out += 1
        if has_store and store(tnew, ynew, P, X, W, IW) != 0:
            stats[2] = nfevals
            stats[7] = row
            return E_HISTORY
        if cint[3]:
            _collect(tnew, ynew, ct, cy, cint, cflt)
        if has_progress and (nsteps & 31) == 0:
            r = progress(abs(tnew - t0) / span, tnew)
            if r <= 0:
                fstat[0] = tnew
                stats[2] = nfevals
                stats[7] = row
                return E_ABORTED if r == 0 else E_CALLBACK
        if last:
            break
        # --- accept
        if ros:
            if reprojected:
                _held(f, tnew, ynew, f2, P, X, W, IW, nn_idx, push, hold_on)
                nfevals += 1
            for i in range(neq):
                f0[i] = f2[i]
            need_jacobian = True
            dfdt_at = np.nan
        else:
            if reprojected:
                f(tnew, ynew, kk[6], P, X, W, IW)
                nfevals += 1
            for i in range(neq):
                kk[0, i] = kk[6, i]
        if not failed_once:
            grow = ONESTEP_SAFETY * (rtol / err) ** exponent if err > 0 else GROW_MOST
            step_size *= _pymin(GROW_MOST, _pymax(SHRINK_LEAST, grow))
        t = tnew
        for i in range(neq):
            y[i] = ynew[i]
    stats[0] = nsteps
    stats[1] = nfailed
    stats[2] = nfevals
    stats[3] = nbelowtol
    stats[4] = negative
    stats[5] = npds
    stats[6] = ndecomps
    stats[7] = row
    return OK
