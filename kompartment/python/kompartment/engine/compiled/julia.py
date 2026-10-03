"""The Julia-derived solvers' loop compiled with numba: FBDF (factorising, or
by GMRES), QNDF (and QBDF), Rodas5P, RadauIIA5, KenCarp4, TRBDF2,
Rosenbrock23, Tsit5 and Vern7, and the default algorithm that switches
between them -- a port of ``engine/solvers/julia`` (the integrator's loop, the
Jacobian cache and W, the simplified Newton iteration, GMRES, the PI
controller, the method families and the composite's switch, with the
hand-off the application's ``auto`` stops at) with the same arithmetic in the
same order, so that a run takes the Python solver's steps, to the last bit.

As in :mod:`.solvers`, the loop is compiled once for every model: the model's
derivative, what its recorders keep at a step and its events' functions are
handed in as first-class functions. It returns to Python only for an analytic
Jacobian, for progress, and for what the Python solver hands to SuperLU: a
sparse W is formed here and factorised and solved with by the Python solver's
own ``SparseLU``, called back. A dense W, and Radau's complex one, is
factorised and solved with by the LAPACK routines SciPy calls for the Python
solver (``getrf``, ``getrs``), called from here at the addresses
``scipy.linalg.cython_lapack`` publishes: the same routines on the same
matrices, so the same bits.

The integrator keeps its own scalars as the loop's locals. What the pieces it
calls share lives in small arrays named by the constants below -- ``C_`` the
counts the adapter reports, ``WS_`` the factorisation's state, ``NS_`` and
``NI_`` the Newton iteration's, ``PC_`` the controller's, ``FB``/``FI``,
``QN``/``QI`` and ``RA``/``RI`` the multistep methods' and Radau's (and, in
:mod:`.krylov`, ``KF``/``KI`` the matrix-free W's) -- and the vectors in
tuples of arrays, unpacked where they are used. Where Python's scalar arithmetic would raise (a division
by zero), the loop ends with the status that says so. The driver is
:mod:`.julia_run`.

A composite run (the default algorithm) has two methods, one of each kind,
both fixed by the tolerance and the size of the system before it starts: the
non-stiff in slot 0, the stiff in slot 1, each with a controller of its own.
The loop switches between them as ``methods/default.py`` does, and stops
where it would switch to a slot it was told to hand off.

GMRES and the matrix-free W of the Krylov FBDF are compiled in
:mod:`.krylov`, apart, as ``solvers/julia/krylov.py`` is: a port of
Krylov.jl's ``gmres!``, under the Mozilla Public License 2.0 as that file is.
"""

from __future__ import annotations

import math

import llvmlite.binding as _llvm
import numpy as np
from numba import njit, types
from numba.extending import get_cython_function_address

from . import guard_numba_cache
from .krylov import C_NF as _KRYLOV_C_NF
from .krylov import (KF_GAMMA_DT, KF_T, KF_ZNORM, KI_MAX_BASIS, KI_MEMORY, KI_NITER, KI_NSOLVE, NKF, NKI,
                     _krylov_prepare, _krylov_solve, _seq_dot)
from .solvers import CB_T, RHS_T, STORE_T

guard_numba_cache()

# The Python solver's constants (``_js.py``, ``newton.py``), written out here:
# numba freezes a global into the code it caches, and checks this file only.
EPS = 2.0 ** -52
MIN_VALUE = 5e-324
SQRT_EPS = math.sqrt(EPS)
EPS_AROUND_ONE = 100 * math.sqrt(EPS)
MAX_SOLVER_POINTS = 4000      # ``runner.MAX_SOLVER_POINTS``, as in :mod:`.solvers`

# How a solve ended; ``fstat`` holds the numbers its message needs.
OK = 0                 # at the end of the span, or at an event (``evstat`` says)
R_MAX_ITERS = 1        # t: more steps than allowed
R_DT_FLOOR = 2         # t, dt: the step no longer moves the clock
R_STOPPED = 3          # the progress said stop
R_NOT_SOLVED = 4       # t, dt: the stages could not be solved at the smallest step
R_UNSTABLE = 5         # t, component: the state became infinite or not a number
R_EEST_NAN = 6         # t, dt: the error estimate not a number at the smallest step
R_ERROR_TEST = 7       # t, dt: the error test failed at the smallest step
E_INITIAL = 8          # component: the start or its derivative is not a number
E_HISTORY = 9          # a min/max history ran out of room
E_CALLBACK = 10        # a callback raised; the driver holds the exception
E_ZERO_DIVISION = 11   # where Python's arithmetic divides by zero
R_HANDED_OFF = 12      # t: a composite stopped where it would have switched to a slot it hands off

# The method families.
M_ROSENBROCK = 0
M_ESDIRK = 1
M_FBDF = 2
M_QNDF = 3
M_RADAU = 4
M_TSIT5 = 5
M_VERN7 = 6
M_ROS23 = 7            # Rosenbrock23, OrdinaryDiffEq's

# The counts the adapter reports (``ctr``).
C_NF = 0               # stats['nf']: every evaluation of the derivative
C_NJAC = 1             # jac_cache.njac
C_NFACTOR = 2          # W.nfactor
C_NSOLVE = 3           # W.nsolve, Radau's complex solves included
C_NSTEPS = 4           # stats['nsteps']: every step tried
C_NREJECT = 5          # stats['nreject']
NC = 6
assert C_NF == _KRYLOV_C_NF  # GMRES counts its evaluations of f into the same place

# What the matrix is (``fl``).
FL_CALLBACK = 0        # the Jacobian is the callback's, differenced where it declines
FL_SPARSE = 1          # W is sparse: the Python solver's SparseLU factorises it
FL_NORM_MAX = 2        # the 'max' norm, else the rms
NFL = 3

# ``WFactorization``'s state (``ws``).
WS_GAMMA_DT = 0
WS_TRANSFORM = 1
WS_STALE = 2           # jac_stale
WS_HAVE = 3            # have_factor
WS_AGE = 4
WS_MAX_AGE = 5
NWS = 6

# ``NewtonSolver``'s state: floats (``ns``) and integers (``ni``).
NS_GAMMA = 0
NS_C = 1
NS_ETA_OLD = 2
NS_PREV_THETA = 3
NS_ETA = 4
NS_ERRC = 5            # error_constant
NS_KAPPA = 6
NS_CUTOFF = 7          # fast_convergence_cutoff
NNS = 8
NI_METHOD = 0
NI_STATUS = 1
NI_NFAILS = 2
NI_MAX_ITERS = 3
NNI = 4
N_DIRK = 0
N_MULTISTEP = 1        # COEFFICIENT_MULTISTEP
N_CONVERGENCE = 0
N_DIVERGENCE = 1
N_MAX_ITERS = 2

# ``PIController``'s state (``pc``).
PC_BETA1 = 0
PC_BETA2 = 1
PC_GAMMA = 2
PC_QMIN = 3
PC_QMAX = 4
PC_QSTEADY_MIN = 5
PC_QSTEADY_MAX = 6
PC_QOLDINIT = 7
PC_ERROLD = 8
PC_QMAX_FIRST = 9      # qmax_first_step: the growth allowed after the run's first accepted step (0: none)
NPC = 10

# ``FBDFCache``'s state: floats (``fbv``) and integers (``fbi``).
FB_TERKM2 = 0
FB_TERKM1 = 1
FB_TERK = 2
FB_TERKP1 = 3
FB_TERKM3 = 4
FB_NEXT_TERK = 5
FB_GAMMA = 6           # gamma_ctrl
FB_QMAX = 7
FB_QMIN = 8
FB_QSTEADY_MIN = 9
FB_QSTEADY_MAX = 10
FB_MAX_ORDER = 11
NFB = 12
FI_ORDER = 0
FI_PREV_ORDER = 1
FI_N_HISTORY = 2
FI_QWAIT = 3
FI_NCONSTEPS = 4
FI_CONSFAIL = 5
FI_FROM_EVENT = 6      # iters_from_event
FI_PENDING = 7         # prev_order_pending
FI_NEXT_ORDER = 8
FI_MIN_ORDER = 9
FI_KRYLOV = 10         # the Newton iterations solved by GMRES (KrylovFBDF)
FI_KRYLOV_FRESH = 11   # krylov_fresh: no contraction rate to believe yet
NFI = 12
FB_K = 7               # MAX_ORDER_LIMIT + 2: the points of history kept
FB_STRIDE = 6          # coef[FB_STRIDE * k + j] is BDF_COEFFS[k][j]

# ``QNDFCache``'s state: floats (``qnv``) and integers (``qni``).
QN_DTPREV = 0
QN_EEST1 = 1
QN_EEST2 = 2
QN_GAMMA = 3           # gamma_ctrl
QN_QMAX = 4
QN_QMIN = 5
QN_QSTEADY_MIN = 6
QN_QSTEADY_MAX = 7
QN_MAX_ORDER = 8
NQN = 9
QI_ORDER = 0
QI_PREV_ORDER = 1
QI_NCONSTEPS = 2
QI_CONSFAIL = 3
QI_STARTED = 4
QI_MIN_ORDER = 5
NQI = 6
QN_ROWS = 8            # QNDF_MAX_ORDER + 3: the differences kept
QN_S = 5               # the stride of R, U and RU
QN_KAPPA = 0           # coef[QN_KAPPA:QN_KAPPA + 5]: kappa per order
QN_GAMMAS = 5          # coef[QN_GAMMAS:QN_GAMMAS + 6]: GAMMA

# ``RadauCache``'s state: floats (``rav``) and integers (``rai``).
RA_DTPREV = 0
RA_COMPLEX_DT = 1
RA_ETA_OLD = 2
RA_KAPPA = 3
RA_CUTOFF = 4          # fast_convergence_cutoff
NRA = 5
RI_COMPLEX_VALID = 0
RI_HAVE_HISTORY = 1
RI_STATUS = 2
RI_MAX_ITERS = 3
RI_SMOOTH = 4          # smooth_est
NRI = 5
RS_CONVERGENCE = 0
RS_FAST = 1            # 'FastConvergence'
RS_DIVERGENCE = 2
# RADAU_IIA5's numbers in ``coef``, in this order.
RADAU_COEFFICIENTS = ('T11', 'T12', 'T13', 'T21', 'T22', 'T23', 'T31', 'TI11', 'TI12', 'TI13', 'TI21', 'TI22',
                      'TI23', 'TI31', 'TI32', 'TI33', 'c1', 'c2', 'gamma', 'alpha', 'beta', 'e1', 'e2', 'e3')

_OPTS = dict(cache=True, error_model='numpy')
_F = types.float64
_A = types.float64[::1]
_I = types.int64[::1]
_M = types.float64[:, ::1]

# --- LAPACK, where SciPy's lu_factor and lu_solve reach it ----------------------------------------
# The symbols are registered in this process under names of this module's
# own, and the compiled code calls them by name: numba caches the code, and
# each process that loads it registers the addresses again first.

for _name in ('dgetrf', 'dgetrs', 'zgetrf', 'zgetrs'):
    _llvm.add_symbol(f'kompartment_{_name}', get_cython_function_address('scipy.linalg.cython_lapack', _name))
_P = types.voidptr
_dgetrf = types.ExternalFunction('kompartment_dgetrf', types.void(_P, _P, _P, _P, _P, _P))
_dgetrs = types.ExternalFunction('kompartment_dgetrs', types.void(_P, _P, _P, _P, _P, _P, _P, _P, _P))
_zgetrf_ = types.ExternalFunction('kompartment_zgetrf', types.void(_P, _P, _P, _P, _P, _P))
_zgetrs_ = types.ExternalFunction('kompartment_zgetrs', types.void(_P, _P, _P, _P, _P, _P, _P, _P, _P))


@njit(**_OPTS)
def _getrf(a, ipiv, lints):
    """``DenseLU.factor``: ``getrf`` of the matrix ``a`` holds by columns --
    ``a[j, i]`` is row i, column j, as LAPACK lays it out -- in place; False
    for a zero pivot, which the package calls singular. ``lints`` is
    LAPACK's integers: n, info and the right-hand sides (1)."""
    _dgetrf(lints.ctypes, lints.ctypes, a.ctypes, lints.ctypes, ipiv.ctypes, lints[1:].ctypes)
    for i in range(a.shape[0]):
        if a[i, i] == 0:
            return False
    return True


@njit(**_OPTS)
def _getrs(a, ipiv, lints, trans, x):
    """``DenseLU.solve``: ``getrs`` with the factors :func:`_getrf` left, x in place."""
    _dgetrs(trans.ctypes, lints.ctypes, lints[2:].ctypes, a.ctypes, lints.ctypes, ipiv.ctypes, x.ctypes, lints.ctypes,
            lints[1:].ctypes)


@njit(**_OPTS)
def _zgetrf(a, ipiv, lints):
    """:func:`_getrf` over the complex numbers (``ComplexDenseLU``)."""
    _zgetrf_(lints.ctypes, lints.ctypes, a.ctypes, lints.ctypes, ipiv.ctypes, lints[1:].ctypes)
    for i in range(a.shape[0]):
        if a[i, i] == 0:
            return False
    return True


@njit(**_OPTS)
def _zgetrs(a, ipiv, lints, trans, x):
    """:func:`_getrs` over the complex numbers."""
    _zgetrs_(trans.ctypes, lints.ctypes, lints[2:].ctypes, a.ctypes, lints.ctypes, ipiv.ctypes, x.ctypes,
             lints.ctypes, lints[1:].ctypes)


# --- JavaScript's arithmetic (``_js.py``) -------------------------------------------------------------


@njit(inline='always', **_OPTS)
def _jmax(a, b):
    """``Math.max``: NaN wins, and +0 is larger than -0."""
    if a != a or b != b:
        return np.nan
    if a > b:
        return a
    if b > a:
        return b
    if a == 0 and b == 0:
        return b if math.copysign(1.0, a) < 0 else a
    return a


@njit(inline='always', **_OPTS)
def _jmin(a, b):
    """``Math.min``: NaN wins, and -0 is smaller than +0."""
    if a != a or b != b:
        return np.nan
    if a < b:
        return a
    if b < a:
        return b
    if a == 0 and b == 0:
        return b if math.copysign(1.0, b) < 0 else a
    return a


@njit(inline='always', **_OPTS)
def _jpow(x, y):
    """``jpow``: fdlibm's exact cases, then the C library's ``pow``, whose
    infinities and NaNs are the ones ``jpow`` gives for Python's exceptions."""
    if y != y:
        return np.nan
    if y == 0:
        return 1.0
    if x != x:
        return np.nan
    if math.isinf(y) and abs(x) == 1:
        return np.nan
    if y == 0.5 and x > 0 and math.isfinite(x):
        return math.sqrt(x)
    if y == 1:
        return x
    if y == 2:
        return x * x
    return math.pow(x, y)


@njit(inline='always', **_OPTS)
def _jsign(x):
    """``Math.sign``."""
    if x != x:
        return np.nan
    if x > 0:
        return 1.0
    if x < 0:
        return -1.0
    return x


@njit(inline='always', **_OPTS)
def _ulp(x):
    """``ulp``: 2 ** (floor(log2 |x|) - 52), the smallest number at zero."""
    if x == 0:
        return MIN_VALUE
    a = abs(x)
    if a != a:
        return np.nan
    if math.isinf(a):
        return np.inf
    return math.ldexp(1.0, math.floor(math.log2(a)) - 52)


@njit(inline='always', **_OPTS)
def _npmax(a, b):
    """numpy's ``maximum``: NaN when either is."""
    if a != a or b != b:
        return np.nan
    return a if a >= b else b


# --- the norms -------------------------------------------------------------------------------------


@njit(**_OPTS)
def _error_norm(e, uprev, u, atol, rtol, norm_max):
    """``Integrator.error_norm``: |e / w| with w = atol + rtol*max(|uprev|, |u|),
    the largest (at least 0) or the rms of a sum taken left to right; a
    component that is not a number makes it NaN."""
    n = e.size
    if norm_max:
        m = 0.0
        for i in range(n):
            a = abs(e[i] / (atol[i] + rtol * _npmax(abs(uprev[i]), abs(u[i]))))
            if a != a:
                return np.nan
            if a > m:
                m = a
        return m
    s = 0.0
    for i in range(n):
        r = e[i] / (atol[i] + rtol * _npmax(abs(uprev[i]), abs(u[i])))
        s += r * r
    return math.sqrt(s / n)


@njit(**_OPTS)
def _residual_norm(dz, uprev, ustep, atol, rtol, norm_max):
    """``newton.residual_norm``: as :func:`_error_norm`, |dz| / w, against the
    stage value."""
    n = dz.size
    if norm_max:
        m = 0.0
        for i in range(n):
            a = abs(dz[i]) / (atol[i] + rtol * _npmax(abs(uprev[i]), abs(ustep[i])))
            if a != a:
                return np.nan
            if a > m:
                m = a
        return m
    s = 0.0
    for i in range(n):
        r = dz[i] / (atol[i] + rtol * _npmax(abs(uprev[i]), abs(ustep[i])))
        s += r * r
    return math.sqrt(s / n)


@njit(**_OPTS)
def _scaled_norm(v, uprev, u, atol_r, rtol_r):
    """``RadauCache.scaled_norm``: the rms against Radau's tolerances."""
    n = v.size
    s = 0.0
    for i in range(n):
        r = v[i] / (atol_r[i] + rtol_r * _npmax(abs(uprev[i]), abs(u[i])))
        s += r * r
    return math.sqrt(s / n)


# --- the Jacobian and W (``jacobian.py``) ----------------------------------------------------------------


@njit(**_OPTS)
def _jacobian(f, model, pycb, jac_cb, jac, fl, ctr, t, u, fu):
    """``JacobianCache.evaluate`` at (t, u), fu = f(t, u): the callback's
    values, or forward differences through the package's colouring of the
    pattern where there is no callback or it declines. 0, or -1 when the
    callback raised.

    ``jac``: the dense J or J's values on the pattern (``jd``, ``jv``), the
    colouring -- per group its columns (``gptr``, ``gcols``) and the entries
    it fills (``eptr``; each entry's row, its column's place in ``gcols`` and
    its place in ``jv``) -- and the buffers the callback and the differences use."""
    P, X, Wm, IW = model
    jd, jv, gptr, gcols, eptr, erow, ewhich, eent, ybuf, upert, fpert, dscale = jac
    ctr[C_NJAC] += 1
    if fl[FL_CALLBACK]:
        for i in range(u.size):
            ybuf[i] = u[i]
        r = jac_cb(t, 0.0)
        # Worked out in Python, into X: no longer the instant W[0] says.
        Wm[0] = np.nan
        if r < 0:
            return -1
        if r == 1:
            return 0
    n = u.size
    sparse = fl[FL_SPARSE] != 0
    if sparse:
        for p in range(jv.size):
            jv[p] = 0.0
    else:
        for i in range(n):
            for j in range(n):
                jd[i, j] = 0.0
    for g in range(gptr.size - 1):
        for q in range(n):
            upert[q] = u[q]
        for gg in range(gptr[g], gptr[g + 1]):
            j = gcols[gg]
            d = SQRT_EPS * _npmax(abs(u[j]), 1e-5)
            dscale[gg] = 1.0 / d
            upert[j] = u[j] + d
        f(t, upert, fpert, P, X, Wm, IW, pycb)
        ctr[C_NF] += 1
        for e in range(eptr[g], eptr[g + 1]):
            r = erow[e]
            v = (fpert[r] - fu[r]) * dscale[ewhich[e]]
            if sparse:
                jv[eent[e]] = v
            else:
                jd[r, gcols[ewhich[e]]] = v
    return 0


@njit(**_OPTS)
def _form_w(f, model, pycb, jac_cb, jac, factor_cb, mat, fl, ctr, t, uprev, fu, gamma_dt, transform, force_jac):
    """``Integrator.form_w`` (``WFactorization.form``): J renewed when asked,
    stale or too old, then W = I - gh*J, or I/(gh) - J with ``transform``,
    formed and factorised unless the factor is already W's. 1 formed, 0
    singular, -1 a callback raised.

    ``mat``: the state (``ws``), the dense W by columns and its pivots, W's
    values on its own pattern with where J's and the diagonal sit in them,
    and the buffers the sparse solve's callback reads and writes."""
    jd, jv = jac[0], jac[1]
    ws, wf, ipiv, lints, trans, wv, j_to_w, diag_w, rbuf, xbuf = mat
    if force_jac or ws[WS_STALE] != 0 or ws[WS_AGE] >= ws[WS_MAX_AGE]:
        if _jacobian(f, model, pycb, jac_cb, jac, fl, ctr, t, uprev, fu) < 0:
            return -1
        ws[WS_STALE] = 0.0
        ws[WS_AGE] = 0.0
        ws[WS_HAVE] = 0.0
    elif ws[WS_HAVE] != 0 and ws[WS_GAMMA_DT] == gamma_dt and ws[WS_TRANSFORM] == transform:
        return 1
    n = uprev.size
    if fl[FL_SPARSE]:
        for p in range(wv.size):
            wv[p] = 0.0
        if transform:
            d = 1 / gamma_dt
            for p in range(j_to_w.size):
                wv[j_to_w[p]] = -jv[p]
            for i in range(n):
                wv[diag_w[i]] += d
        else:
            mg = -gamma_dt
            for p in range(j_to_w.size):
                wv[j_to_w[p]] = mg * jv[p]
            for i in range(n):
                wv[diag_w[i]] += 1
        ctr[C_NFACTOR] += 1
        r = factor_cb(0.0, 0.0)
        if r < 0:
            return -1
        ok = r == 1
    else:
        if transform:
            d = 1 / gamma_dt
            for j in range(n):
                for i in range(n):
                    wf[j, i] = -jd[i, j]
            for i in range(n):
                wf[i, i] += d
        else:
            mg = -gamma_dt
            for j in range(n):
                for i in range(n):
                    wf[j, i] = jd[i, j] * mg
            for i in range(n):
                wf[i, i] += 1
        ctr[C_NFACTOR] += 1
        ok = _getrf(wf, ipiv, lints)
    ws[WS_HAVE] = 1.0 if ok else 0.0
    ws[WS_GAMMA_DT] = gamma_dt
    ws[WS_TRANSFORM] = transform
    return 1 if ok else 0


@njit(**_OPTS)
def _solve_w(solve_cb, mat, fl, ctr, b, x):
    """``WFactorization.solve``: x = W^-1 b (x may be b); False when the
    callback raised."""
    ws, wf, ipiv, lints, trans, wv, j_to_w, diag_w, rbuf, xbuf = mat
    ctr[C_NSOLVE] += 1
    if fl[FL_SPARSE]:
        for i in range(b.size):
            rbuf[i] = b[i]
        if solve_cb(0.0, 0.0) < 0:
            return False
        for i in range(x.size):
            x[i] = xbuf[i]
        return True
    for i in range(b.size):
        x[i] = b[i]
    _getrs(wf, ipiv, lints, trans, x)
    return True


@njit(inline='always', **_OPTS)
def _fast(ns, ni):
    """``NewtonSolver.fast_convergence``."""
    return ni[NI_STATUS] == N_CONVERGENCE and ns[NS_ETA] < ns[NS_CUTOFF]


# --- the simplified Newton iteration (``newton.py``) -------------------------------------------------------


@njit(**_OPTS)
def _newton(f, model, pycb, solve_cb, mat, fl, ctr, nwt, ns, ni, t, dt, uprev, atol_fixed, rtol, new_w,
            last_accepted, kry, krylov):
    """``NewtonSolver.solve``: z from its seed, against the W formed last --
    or, with ``krylov``, by GMRES at the iterate (``KrylovW``, told where the
    iteration is before every solve, as ``set_point`` tells it); the status,
    or -1 when a callback raised. ``nwt``: z, tmp, the stage value, f there
    and the increment."""
    P, X, Wm, IW = model
    z, tmp, ustep, k, dz = nwt
    n = z.size
    norm_max = fl[FL_NORM_MAX] != 0
    kappa = ns[NS_KAPPA]
    max_iters = ni[NI_MAX_ITERS]
    gamma = ns[NS_GAMMA]
    gamma_dt = gamma * dt
    tstep = t + ns[NS_C] * dt
    dirk = ni[NI_METHOD] == N_DIRK
    eta = _jpow(_jmax(ns[NS_ETA_OLD], EPS), 0.8) if new_w else ns[NS_ETA_OLD]
    ndz = 1.0
    prev_theta = ns[NS_PREV_THETA] if last_accepted else 1.0
    status = N_DIVERGENCE
    it = 1
    while it <= max_iters:
        ndz_prev = ndz
        if dirk:
            for i in range(n):
                ustep[i] = tmp[i] + gamma * z[i]
        else:
            for i in range(n):
                ustep[i] = z[i]
        f(tstep, ustep, k, P, X, Wm, IW, pycb)
        ctr[C_NF] += 1
        if dirk:
            for i in range(n):
                dz[i] = dt * k[i] - z[i]
        else:
            for i in range(n):
                dz[i] = tmp[i] + gamma_dt * k[i] - z[i]
        if krylov:
            kwf = kry[0]
            kwf[KF_T] = tstep
            kwf[KF_GAMMA_DT] = gamma_dt
            kwf[KF_ZNORM] = math.sqrt(_seq_dot(ustep, ustep))
            _krylov_solve(f, model, pycb, ctr, kry, dz, ustep, k, rtol)
        elif not _solve_w(solve_cb, mat, fl, ctr, dz, dz):
            return -1
        ndz = _residual_norm(dz, uprev, ustep, atol_fixed, rtol, norm_max)
        if ns[NS_ERRC] != 1:
            ndz *= ns[NS_ERRC]
        if not math.isfinite(ndz):
            status = N_DIVERGENCE
            ni[NI_NFAILS] += 1
            break
        if it > 1:
            theta = _jmax(0.3 * prev_theta, ndz / ndz_prev)
            prev_theta = theta
            if abs(theta - 1) <= EPS_AROUND_ONE:
                if ndz <= 1:
                    ni[NI_NFAILS] = 0
                    for i in range(n):
                        z[i] += dz[i]
                    ns[NS_ETA] = eta
                    ns[NS_ETA_OLD] = eta
                    ns[NS_PREV_THETA] = prev_theta
                    ni[NI_STATUS] = N_CONVERGENCE
                    return N_CONVERGENCE
                status = N_DIVERGENCE
                ni[NI_NFAILS] += 1
                break
            if theta > 2:
                status = N_DIVERGENCE
                ni[NI_NFAILS] += 1
                break
        else:
            theta = prev_theta
        for i in range(n):
            z[i] += dz[i]
        eta = theta / (1 - theta)
        if (it == 1 and ndz < 1e-5) or (it > 1 and eta >= 0 and eta * ndz < kappa):
            status = N_CONVERGENCE
            ni[NI_NFAILS] = 0
            break
        if it == max_iters:
            status = N_MAX_ITERS
            ni[NI_NFAILS] += 1
        it += 1
    ns[NS_ETA] = eta
    ns[NS_ETA_OLD] = eta
    ns[NS_PREV_THETA] = prev_theta
    ni[NI_STATUS] = status
    return status


# --- the step size (``controller.py``) --------------------------------------------------------------------


@njit(**_OPTS)
def _pi_accept(pc, eest, dt, first):
    """``PIController.accept``: the next step after one accepted; ``first``
    says it is the run's first accepted step, for ``qmax_first_step``."""
    qmax = pc[PC_QMAX_FIRST] if (first and pc[PC_QMAX_FIRST] > 0) else pc[PC_QMAX]
    if eest == 0:
        q = 1 / qmax
    else:
        q = _jpow(eest, pc[PC_BETA1]) / _jpow(pc[PC_ERROLD], pc[PC_BETA2])
        q /= pc[PC_GAMMA]
        q = _jmin(1 / pc[PC_QMIN], _jmax(1 / qmax, q))
    if q >= pc[PC_QSTEADY_MIN] and q <= pc[PC_QSTEADY_MAX]:
        q = 1.0
    pc[PC_ERROLD] = _jmax(eest, pc[PC_QOLDINIT])
    return dt / q


@njit(inline='always', **_OPTS)
def _pi_reject(pc, eest, dt):
    """``PIController.reject``: the step to retry one rejected with."""
    return dt / _jmin(1 / pc[PC_QMIN], _jpow(eest, pc[PC_BETA1]) / pc[PC_GAMMA])


@njit(**_OPTS)
def _initial_step(f, model, pycb, ctr, t0, u0, f0, tdir, order, rtol, atol, dtmax, u1, f1):
    """``initial_step``: Hairer's starting step, signed."""
    P, X, Wm, IW = model
    n = u0.size
    sa = 0.0
    sb = 0.0
    for i in range(n):
        w = atol[i] + rtol * abs(u0[i])
        a = u0[i] / w
        b = f0[i] / w
        sa += a * a
        sb += b * b
    d0 = math.sqrt(sa / n)
    d1 = math.sqrt(sb / n)
    h0 = 1e-6 if (d0 < 1e-5 or d1 < 1e-5) else 0.01 * (d0 / d1)
    h0 = _jmin(h0, abs(dtmax))
    step = tdir * h0
    for i in range(n):
        u1[i] = u0[i] + step * f0[i]
    f(t0 + tdir * h0, u1, f1, P, X, Wm, IW, pycb)
    ctr[C_NF] += 1
    sc = 0.0
    for i in range(n):
        c = (f1[i] - f0[i]) / (atol[i] + rtol * abs(u0[i]))
        sc += c * c
    d2 = math.sqrt(sc / n) / h0
    dmax = _jmax(d1, d2)
    h1 = _jmax(1e-6, h0 * 1e-3) if dmax <= 1e-15 else _jpow(0.01 / dmax, 1 / (order + 1))
    return tdir * _jmin(_jmin(100 * h0, h1), abs(dtmax))


# --- OrdinaryDiffEq's starting step (``controller.initial_step_sciml``) ---------------------------------
# Its p-th root goes through V8's ``Math.log10`` (``kompartment.jsmath``), as
# fdlibm writes it: here bit for bit, by the high and low words of a double.

_LN2_HI = 6.93147180369123816490e-01
_LN2_LO = 1.90821492927058770002e-10
_TWO54 = 1.80143985094819840000e+16
_LG1 = 6.666666666666735130e-01
_LG2 = 3.999999999940941908e-01
_LG3 = 2.857142874366239149e-01
_LG4 = 2.222219843214978396e-01
_LG5 = 1.818357216161805012e-01
_LG6 = 1.531383769920937332e-01
_LG7 = 1.479819860511658591e-01
_IVLN10 = 4.34294481903251816668e-01
_LOG10_2HI = 3.01029995663611771306e-01
_LOG10_2LO = 3.69423907715893078616e-13


@njit(inline='always', **_OPTS)
def _signed32(v):
    """A 32-bit word as fdlibm's signed int."""
    v = v & 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


@njit(**_OPTS)
def _v8_log(x):
    """``jsmath.log``: V8's ``Math.log``."""
    w = np.empty(1)
    u = w.view(np.uint32)
    w[0] = x
    hx = _signed32(np.int64(u[1]))
    lx = np.int64(u[0])
    k = 0
    if hx < 0x00100000:
        if ((hx & 0x7FFFFFFF) | lx) == 0:
            return -np.inf
        if hx < 0:
            return np.nan
        k -= 54
        x *= _TWO54
        w[0] = x
        hx = _signed32(np.int64(u[1]))
    if hx >= 0x7FF00000:
        return x + x
    k += (hx >> 20) - 1023
    hx &= 0x000FFFFF
    i = (hx + 0x95F64) & 0x100000
    w[0] = x
    u[1] = np.uint32(hx | (i ^ 0x3FF00000))
    x = w[0]
    k += i >> 20
    f = x - 1.0
    if (0x000FFFFF & (2 + hx)) < 3:
        if f == 0.0:
            if k == 0:
                return 0.0
            dk = float(k)
            return dk * _LN2_HI + dk * _LN2_LO
        r = f * f * (0.5 - 0.33333333333333333 * f)
        if k == 0:
            return f - r
        dk = float(k)
        return dk * _LN2_HI - ((r - dk * _LN2_LO) - f)
    s = f / (2.0 + f)
    dk = float(k)
    z = s * s
    i = hx - 0x6147A
    w2 = z * z
    j = 0x6B851 - hx
    t1 = w2 * (_LG2 + w2 * (_LG4 + w2 * _LG6))
    t2 = z * (_LG1 + w2 * (_LG3 + w2 * (_LG5 + w2 * _LG7)))
    i |= j
    r = t2 + t1
    if i > 0:
        hfsq = 0.5 * f * f
        if k == 0:
            return f - (hfsq - s * (hfsq + r))
        return dk * _LN2_HI - ((hfsq - (s * (hfsq + r) + dk * _LN2_LO)) - f)
    if k == 0:
        return f - s * (f - r)
    return dk * _LN2_HI - ((s * (f - r) - dk * _LN2_LO) - f)


@njit(**_OPTS)
def _v8_log10(x):
    """``jsmath.log10``: V8's ``Math.log10``."""
    w = np.empty(1)
    u = w.view(np.uint32)
    w[0] = x
    hx = _signed32(np.int64(u[1]))
    lx = np.int64(u[0])
    k = 0
    if hx < 0x00100000:
        if ((hx & 0x7FFFFFFF) | lx) == 0:
            return -np.inf
        if hx < 0:
            return np.nan
        k -= 54
        x *= _TWO54
        w[0] = x
        hx = _signed32(np.int64(u[1]))
        lx = np.int64(u[0])
    if hx >= 0x7FF00000:
        return x + x
    if hx == 0x3FF00000 and lx == 0:
        return 0.0
    k += (hx >> 20) - 1023
    i = 1 if k < 0 else 0
    hx = (hx & 0x000FFFFF) | ((0x3FF - i) << 20)
    y = float(k + i)
    u[1] = np.uint32(hx)
    u[0] = np.uint32(lx)
    z = y * _LOG10_2LO + _IVLN10 * _v8_log(w[0])
    return z + y * _LOG10_2HI


@njit(inline='always', **_OPTS)
def _next_up(x):
    """``next_up``: the next double above x >= 0."""
    if x == 0:
        return MIN_VALUE
    return np.nextafter(x, np.inf)


@njit(inline='always', **_OPTS)
def _eps_of(x):
    """``eps_of``: Julia's ``eps(x)``."""
    a = abs(x)
    if a == 0:
        return MIN_VALUE
    return _next_up(a) - a


@njit(**_OPTS)
def _measure(v, norm_max):
    """``initial_step_sciml``'s measure: the largest |v| (at least 0, NaN if
    any is), or the rms of a sum taken left to right."""
    n = v.size
    if norm_max:
        m = 0.0
        for i in range(n):
            a = abs(v[i])
            if a != a:
                return np.nan
            if a > m:
                m = a
        return m
    s = 0.0
    for i in range(n):
        s += v[i] * v[i]
    return math.sqrt(s / n)


@njit(inline='always', **_OPTS)
def _fallback(dt, tiny_first, tdir, smalldt, dtmin_):
    if tiny_first and (not math.isfinite(dt) or abs(dt) < 10 * EPS):
        return tdir * _jmax(smalldt, dtmin_)
    return dt


@njit(**_OPTS)
def _initial_step_sciml(f, model, pycb, ctr, t0, u0, f0, tdir, order, rtol, atol, dtmax, norm_max, u1, f1, w, v):
    """``initial_step_sciml``: the starting step as OrdinaryDiffEq's
    ``ode_determine_initdt`` takes it, signed (dtmin left at its default)."""
    P, X, Wm, IW = model
    n = u0.size
    dtmin_ = _next_up(_jmax(0.0, _eps_of(t0)))
    smalldt = _jmax(dtmin_, 1e-6)
    dtmax_abs = abs(dtmax)
    for i in range(n):
        w[i] = atol[i] + abs(u0[i]) * rtol
    for i in range(n):
        v[i] = u0[i] / w[i]
    d0 = _measure(v, norm_max)
    for i in range(n):
        v[i] = f0[i] / w[i]
    d1 = _measure(v, norm_max)
    if d1 != d1:
        return tdir * dtmin_
    dt0 = smalldt if (d0 < 1e-5 or d1 < 1e-5) else (d0 / d1) / 100
    dt0 = _jmin(dt0, dtmax_abs)
    tiny_first = dt0 < 10 * EPS
    step = tdir * dt0
    for i in range(n):
        u1[i] = u0[i] + step * f0[i]
    f(t0 + tdir * dt0, u1, f1, P, X, Wm, IW, pycb)
    ctr[C_NF] += 1
    same = n > 0
    for i in range(n):
        if not (f0[i] == f1[i]):
            same = False
            break
    if same:
        return _fallback(tdir * _jmax(dtmin_, 100 * dt0), tiny_first, tdir, smalldt, dtmin_)
    for i in range(n):
        v[i] = (f1[i] - f0[i]) / w[i]
    d2 = _measure(v, norm_max) / dt0
    m = _jmax(d1, d2)
    dt1 = _jmax(1e-6, dt0 * 1e-3) if m <= 1e-15 else _jpow(10.0, (-(2 + _v8_log10(m))) / order)
    return _fallback(tdir * _jmax(dtmin_, _jmin(_jmin(100 * dt0, dt1), dtmax_abs)), tiny_first, tdir, smalldt,
                     dtmin_)


# --- the explicit methods: Tsit5 and Vern7 (``methods/tsit5.py``, ``methods/vern7.py``) -------------------
# ``ex``: the stages (16 rows: Vern7's ten and its interpolant's six, Tsit5's
# seven), a stage's point and a sum, whether Vern7's interpolation stages are
# this step's, Tsit5's tableau (a by rows, c, btilde, the interpolant's
# polynomials by rows) and Vern7's (each row's nonzero terms -- stage, value --
# in the source's order, rows 0..9 the stages, 10 the solution, 11 the error,
# 12..17 the interpolation stages; c and the interpolation stages' c; the
# interpolant's stages and polynomials).


@njit(**_OPTS)
def _explicit_stiffness(ka, kb, ga, gb, still):
    """``explicit_stiffness``: the largest |(kb - ka)_i / (gb - ga)_i|, a
    component that has not moved at all passed over unless ``still``."""
    m = 0.0
    for i in range(ka.size):
        num = kb[i] - ka[i]
        den = gb[i] - ga[i]
        if not still and num == 0 and den == 0:
            continue
        r = abs(num / den)
        if r != r:
            return np.nan
        if r > m:
            m = r
    return m


@njit(**_OPTS)
def _tsit5_step(f, model, pycb, ctr, ex, t, dt, uprev, u, fsalfirst, fsallast, atol, rtol, norm_max):
    """``Tsit5Cache.step``: the error estimate; the stage-6 point stays in
    ``ex``'s point for the stiffness estimate."""
    P, X, Wm, IW = model
    ek, pt, acc = ex[0], ex[1], ex[2]
    ta, tc, tbt = ex[4], ex[5], ex[6]
    n = u.size
    k0 = ek[0]
    for i in range(n):
        k0[i] = fsalfirst[i]
    a2 = dt * ta[1, 0]
    for i in range(n):
        pt[i] = uprev[i] + a2 * k0[i]
    f(t + tc[1] * dt, pt, ek[1], P, X, Wm, IW, pycb)
    ctr[C_NF] += 1
    for s in range(2, 6):
        r0 = ta[s, 0]
        for i in range(n):
            acc[i] = r0 * k0[i]
        for j in range(1, s):
            rj = ta[s, j]
            kj = ek[j]
            for i in range(n):
                acc[i] = acc[i] + rj * kj[i]
        for i in range(n):
            pt[i] = uprev[i] + dt * acc[i]
        f(t + tc[s] * dt, pt, ek[s], P, X, Wm, IW, pycb)
        ctr[C_NF] += 1
    r0 = ta[6, 0]
    for i in range(n):
        acc[i] = r0 * k0[i]
    for j in range(1, 6):
        rj = ta[6, j]
        kj = ek[j]
        for i in range(n):
            acc[i] = acc[i] + rj * kj[i]
    for i in range(n):
        u[i] = uprev[i] + dt * acc[i]
    f(t + dt, u, ek[6], P, X, Wm, IW, pycb)
    ctr[C_NF] += 1
    for i in range(n):
        fsallast[i] = ek[6, i]
    b0 = tbt[0]
    for i in range(n):
        acc[i] = b0 * k0[i]
    for j in range(1, 7):
        bj = tbt[j]
        kj = ek[j]
        for i in range(n):
            acc[i] = acc[i] + bj * kj[i]
    for i in range(n):
        acc[i] = dt * acc[i]
    return _error_norm(acc, uprev, u, atol, rtol, norm_max)


@njit(**_OPTS)
def _tsit5_interpolate(ex, theta, dt, uprev, u, out):
    """``Tsit5Cache.interpolate``: Tsitouras's free interpolant, fourth order;
    the step's own solution at its end."""
    ek, acc, ti = ex[0], ex[2], ex[7]
    n = u.size
    if theta == 1:
        for i in range(n):
            out[i] = u[i]
        return
    th2 = theta * theta
    w0 = theta * (ti[0, 0] + theta * (ti[0, 1] + theta * (ti[0, 2] + theta * ti[0, 3])))
    for i in range(n):
        acc[i] = ek[0, i] * w0
    for j in range(1, 7):
        wj = th2 * (ti[j, 0] + theta * (ti[j, 1] + theta * ti[j, 2]))
        kj = ek[j]
        for i in range(n):
            acc[i] = acc[i] + kj[i] * wj
    for i in range(n):
        out[i] = uprev[i] + dt * acc[i]


@njit(**_OPTS)
def _vern7_combine(ex, row, uprev, dt, out):
    """``Vern7Cache.combine``: uprev + dt*sum coefficient*k over the row's terms."""
    ek, acc = ex[0], ex[2]
    vptr, vj, vv = ex[8], ex[9], ex[10]
    n = uprev.size
    p0 = vptr[row]
    j0 = vj[p0]
    v0 = vv[p0]
    for i in range(n):
        acc[i] = v0 * ek[j0, i]
    for p in range(p0 + 1, vptr[row + 1]):
        v = vv[p]
        kj = ek[vj[p]]
        for i in range(n):
            acc[i] = acc[i] + v * kj[i]
    for i in range(n):
        out[i] = uprev[i] + dt * acc[i]


@njit(**_OPTS)
def _vern7_step(f, model, pycb, ctr, ex, t, dt, uprev, u, fsalfirst, atol, rtol, norm_max):
    """``Vern7Cache.step``: the error estimate; the stage-10 point stays in
    ``ex``'s point for the stiffness estimate."""
    P, X, Wm, IW = model
    ek, pt, acc, valid = ex[0], ex[1], ex[2], ex[3]
    vptr, vj, vv, vc = ex[8], ex[9], ex[10], ex[11]
    n = u.size
    k0 = ek[0]
    for i in range(n):
        k0[i] = fsalfirst[i]
    for s in range(1, 10):
        _vern7_combine(ex, s, uprev, dt, pt)
        f(t + vc[s] * dt, pt, ek[s], P, X, Wm, IW, pycb)
        ctr[C_NF] += 1
    _vern7_combine(ex, 10, uprev, dt, u)
    valid[0] = 0
    p0 = vptr[11]
    j0 = vj[p0]
    v0 = vv[p0]
    for i in range(n):
        acc[i] = v0 * ek[j0, i]
    for p in range(p0 + 1, vptr[12]):
        v = vv[p]
        kj = ek[vj[p]]
        for i in range(n):
            acc[i] = acc[i] + v * kj[i]
    for i in range(n):
        acc[i] = dt * acc[i]
    return _error_norm(acc, uprev, u, atol, rtol, norm_max)


@njit(**_OPTS)
def _vern7_interpolate(f, model, pycb, ctr, ex, theta, t, dt, uprev, u, out):
    """``Vern7Cache.interpolate``: Verner's seventh-order interpolant, its six
    stages worked out once a step, when a point inside it is first asked
    for; the step's own solution at its end."""
    P, X, Wm, IW = model
    ek, pt, acc, valid = ex[0], ex[1], ex[2], ex[3]
    vc2, vst, vip, viv = ex[12], ex[13], ex[14], ex[15]
    n = u.size
    if theta == 1:
        for i in range(n):
            out[i] = u[i]
        return
    if valid[0] == 0:
        for m in range(6):
            _vern7_combine(ex, 12 + m, uprev, dt, pt)
            f(t + vc2[m] * dt, pt, ek[10 + m], P, X, Wm, IW, pycb)
            ctr[C_NF] += 1
        valid[0] = 1
    th2 = theta * theta
    for q in range(vst.size):
        lo = vip[q]
        hi = vip[q + 1]
        p = viv[hi - 1]
        for d in range(hi - 2, lo - 1, -1):
            p = viv[d] + theta * p
        wq = (theta if q == 0 else th2) * p
        kq = ek[vst[q] - 1]
        if q == 0:
            for i in range(n):
                acc[i] = kq[i] * wq
        else:
            for i in range(n):
                acc[i] = acc[i] + kq[i] * wq
    for i in range(n):
        out[i] = uprev[i] + dt * acc[i]


# --- Rosenbrock23 (``methods/rosenbrock23.py``) ---------------------------------------------------------------
# ``r23``: k1, k2, k3 (the stages; k1 and k2 are the interpolant's), dT, a
# stage's point, f there and a right-hand side.

ROS23_D = 1 / (2 + math.sqrt(2))
ROS23_C32 = 6 + math.sqrt(2)


@njit(**_OPTS)
def _ros23_step(f, model, pycb, jac_cb, jac, factor_cb, solve_cb, mat, fl, ctr, r23, t, dt, uprev, u, fsalfirst,
                fsallast, atol, rtol):
    """``Rosenbrock23Cache.step``: W = I/(h d) - J from a fresh J on every
    step. (1, the error estimate), (0, 0) when W is singular, (-1, 0) when a
    callback raised, (-2, 0) where Python divides by zero."""
    P, X, Wm, IW = model
    k1, k2, k3, dT, pt, f1, rhs = r23
    n = u.size
    dtgamma = dt * ROS23_D
    inv = 1.0 / dtgamma
    dto2 = dt / 2
    dto6 = dt / 6
    r = _form_w(f, model, pycb, jac_cb, jac, factor_cb, mat, fl, ctr, t, uprev, fsalfirst, dtgamma, 1.0, True)
    if r <= 0:
        return r, 0.0
    # df/dt, differenced with a step scaled by max(|t|, |h|) (``rosenbrock_time_derivative``).
    dtd = math.sqrt(EPS) * _jmax(abs(t), abs(dt))
    f(t + dtd, uprev, pt, P, X, Wm, IW, pycb)
    ctr[C_NF] += 1
    if dtd == 0:
        return -2, 0.0
    invd = 1 / dtd
    for i in range(n):
        dT[i] = (pt[i] - fsalfirst[i]) * invd
    for i in range(n):
        rhs[i] = fsalfirst[i] + dtgamma * dT[i]
    if not _solve_w(solve_cb, mat, fl, ctr, rhs, k1):
        return -1, 0.0
    for i in range(n):
        k1[i] = k1[i] * inv
    for i in range(n):
        pt[i] = uprev[i] + dto2 * k1[i]
    f(t + dto2, pt, f1, P, X, Wm, IW, pycb)
    ctr[C_NF] += 1
    for i in range(n):
        rhs[i] = f1[i] - k1[i]
    if not _solve_w(solve_cb, mat, fl, ctr, rhs, k2):
        return -1, 0.0
    for i in range(n):
        k2[i] = k2[i] * inv + k1[i]
    for i in range(n):
        u[i] = uprev[i] + dt * k2[i]
    f(t + dt, u, fsallast, P, X, Wm, IW, pycb)
    ctr[C_NF] += 1
    for i in range(n):
        rhs[i] = fsallast[i] - ROS23_C32 * (k2[i] - f1[i]) - 2 * (k1[i] - fsalfirst[i]) + dt * dT[i]
    if not _solve_w(solve_cb, mat, fl, ctr, rhs, k3):
        return -1, 0.0
    for i in range(n):
        k3[i] = k3[i] * inv
    for i in range(n):
        rhs[i] = dto6 * (k1[i] - 2 * k2[i] + k3[i])
    return 1, _error_norm(rhs, uprev, u, atol, rtol, fl[FL_NORM_MAX] != 0)


@njit(**_OPTS)
def _ros23_interpolate(r23, theta, dt, uprev, u, out):
    """``Rosenbrock23Cache.interpolate``: the method's own second-order
    interpolant; the step's own solution at its end."""
    k1, k2 = r23[0], r23[1]
    n = u.size
    if theta == 1:
        for i in range(n):
            out[i] = u[i]
        return
    c1 = theta * (1 - theta) / (1 - 2 * ROS23_D)
    c2 = theta * (theta - 2 * ROS23_D) / (1 - 2 * ROS23_D)
    for i in range(n):
        out[i] = uprev[i] + dt * (c1 * k1[i] + c2 * k2[i])


@njit(**_OPTS)
def _jac_inf_norm(jac, fl, jrow, rows):
    """``jacobian_inf_norm``: ||J||_inf, each row summed in column order; a
    NaN entry makes it NaN."""
    jd, jv = jac[0], jac[1]
    n = rows.size
    if n == 0:
        return 0.0
    for i in range(n):
        rows[i] = 0.0
    if fl[FL_SPARSE]:
        for p in range(jv.size):
            rows[jrow[p]] += abs(jv[p])
    else:
        for i in range(n):
            s = 0.0
            for j in range(n):
                s += abs(jd[i, j])
            rows[i] = s
    m = 0.0
    for i in range(n):
        a = rows[i]
        if a != a:
            return np.nan
        if a > m:
            m = a
    return m


# --- Rosenbrock: Rodas5P (``methods/rosenbrock.py``) ------------------------------------------------------
# coef: stages s, dense rows nh, gamma, then a, C (s x s each, by rows), c, d,
# b, btilde (s each) and H (nh x s).


@njit(inline='always', **_OPTS)
def _ros_layout(s):
    """Where a, C, c, d, b, btilde and H start in a Rosenbrock tableau's coef."""
    ka = 3
    kC = ka + s * s
    kc = kC + s * s
    kd = kc + s
    kb = kd + s
    kbt = kb + s
    return ka, kC, kc, kd, kb, kbt, kbt + s


@njit(**_OPTS)
def _ros_step(f, model, pycb, jac_cb, jac, factor_cb, solve_cb, mat, fl, ctr, coef, ros, t, dt, uprev, u, fsalfirst,
              atol, rtol):
    """``RosenbrockCache.step``: (1, the error estimate), or (0, 0) when W is
    singular, (-1, 0) when a callback raised, (-2, 0) where Python divides by zero."""
    P, X, Wm, IW = model
    k, dense, valid, dT, du, ustage, rhs = ros
    n = u.size
    s = int(coef[0])
    gamma = coef[2]
    ka, kC, kc, kd, kb, kbt, _ = _ros_layout(s)
    r = _form_w(f, model, pycb, jac_cb, jac, factor_cb, mat, fl, ctr, t, uprev, fsalfirst, dt * gamma, 1.0, True)
    if r <= 0:
        return r, 0.0
    # df/dt, differenced with a step scaled by max(|t|, |h|) (``time_derivative``).
    dtd = math.sqrt(EPS) * _jmax(abs(t), abs(dt))
    f(t + dtd, uprev, du, P, X, Wm, IW, pycb)
    ctr[C_NF] += 1
    if dtd == 0:
        return -2, 0.0
    inv = 1 / dtd
    for i in range(n):
        dT[i] = (du[i] - fsalfirst[i]) * inv
    dd = dt * coef[kd]
    for i in range(n):
        rhs[i] = fsalfirst[i] + dd * dT[i]
    if not _solve_w(solve_cb, mat, fl, ctr, rhs, k[0]):
        return -1, 0.0
    for stage in range(1, s):
        for i in range(n):
            ustage[i] = uprev[i]
        for j in range(stage):
            a = coef[ka + s * stage + j]
            for i in range(n):
                ustage[i] += a * k[j, i]
        f(t + coef[kc + stage] * dt, ustage, du, P, X, Wm, IW, pycb)
        ctr[C_NF] += 1
        ds = dt * coef[kd + stage]
        invdt = 1 / dt
        for i in range(n):
            rhs[i] = 0.0
        for j in range(stage):
            cj = coef[kC + s * stage + j]
            for i in range(n):
                rhs[i] += cj * k[j, i]
        for i in range(n):
            rhs[i] = du[i] + ds * dT[i] + rhs[i] * invdt
        if not _solve_w(solve_cb, mat, fl, ctr, rhs, k[stage]):
            return -1, 0.0
    for i in range(n):
        u[i] = uprev[i]
    for j in range(s):
        bj = coef[kb + j]
        if bj != 0:
            for i in range(n):
                u[i] += bj * k[j, i]
    for i in range(n):
        rhs[i] = 0.0
    for j in range(s):
        bt = coef[kbt + j]
        if bt != 0:
            for i in range(n):
                rhs[i] += bt * k[j, i]
    valid[0] = 0
    return 1, _error_norm(rhs, uprev, u, atol, rtol, fl[FL_NORM_MAX] != 0)


@njit(**_OPTS)
def _ros_interpolate(coef, ros, theta, uprev, u, out):
    """``RosenbrockCache.interpolate``: (1-theta) u0 + theta (u1 + (1-theta)
    (k1 + theta (k2 + theta k3))), the dense rows built once a step."""
    k, dense, valid, dT, du, ustage, rhs = ros
    n = u.size
    s = int(coef[0])
    nh = int(coef[1])
    kH = _ros_layout(s)[6]
    if valid[0] == 0:
        for j in range(nh):
            for i in range(n):
                dense[j, i] = 0.0
            for m in range(s):
                h = coef[kH + s * j + m]
                if h != 0:
                    for i in range(n):
                        dense[j, i] += h * k[m, i]
        valid[0] = 1
    t1 = 1 - theta
    for i in range(n):
        acc = dense[nh - 1, i]
        for j in range(nh - 2, -1, -1):
            acc = dense[j, i] + theta * acc
        out[i] = t1 * uprev[i] + theta * (u[i] + t1 * acc)


# --- ESDIRK: KenCarp4 and TRBDF2 (``methods/esdirk.py``) ------------------------------------------------------
# coef: stages s, gamma, smooth_est, then a (s x s, by rows), b, btilde, c (s
# each) and alpha (s x s).


@njit(**_OPTS)
def _esdirk_step(f, model, pycb, jac_cb, jac, factor_cb, solve_cb, mat, fl, ctr, coef, ez, nwt, ns, ni, t, dt, uprev, u,
                 fsalfirst, fsallast, atol, atol_fixed, rtol, est, kry):
    """``ESDIRKCache.step``: each stage by the Newton iteration against one
    W = I - gamma h J. (1, the error estimate), (0, 0) when W is singular or a
    stage does not converge, (-1, 0) when a callback raised."""
    ws = mat[0]
    z, tmp = nwt[0], nwt[1]
    n = u.size
    s = int(coef[0])
    gamma = coef[1]
    smooth = coef[2] != 0
    a0 = 3
    b0 = a0 + s * s
    bt0 = b0 + s
    c0 = bt0 + s
    al0 = c0 + s
    gamma_dt = gamma * dt
    fresh_jac = ws[WS_STALE] != 0 or ws[WS_HAVE] == 0 or not _fast(ns, ni)
    gamma_moved = abs(ws[WS_GAMMA_DT] - gamma_dt) > 0.2 * abs(gamma_dt)
    r = _form_w(f, model, pycb, jac_cb, jac, factor_cb, mat, fl, ctr, t, uprev, fsalfirst, gamma_dt, 0.0, fresh_jac)
    if r <= 0:
        return r, 0.0
    new_w = fresh_jac or gamma_moved
    for i in range(n):
        ez[0, i] = dt * fsalfirst[i]
    for stage in range(1, s):
        for i in range(n):
            tmp[i] = uprev[i]
        for j in range(stage):
            a = coef[a0 + s * stage + j]
            for i in range(n):
                tmp[i] += a * ez[j, i]
        for i in range(n):
            z[i] = 0.0
        for j in range(stage):
            al = coef[al0 + s * stage + j]
            for i in range(n):
                z[i] += al * ez[j, i]
        ns[NS_C] = coef[c0 + stage]
        ns[NS_GAMMA] = gamma
        st = _newton(f, model, pycb, solve_cb, mat, fl, ctr, nwt, ns, ni, t, dt, uprev, atol_fixed, rtol,
                     new_w and stage == 1, True, kry, False)
        if st < 0:
            return -1, 0.0
        if st != N_CONVERGENCE:
            ws[WS_STALE] = 1.0
            return 0, 0.0
        for i in range(n):
            ez[stage, i] = z[i]
        new_w = False
    for i in range(n):
        u[i] = uprev[i]
    for j in range(s):
        bj = coef[b0 + j]
        for i in range(n):
            u[i] += bj * ez[j, i]
    invdt = 1 / dt
    for i in range(n):
        fsallast[i] = ez[s - 1, i] * invdt
    for i in range(n):
        est[i] = 0.0
    for j in range(s):
        bt = coef[bt0 + j]
        if bt != 0:
            for i in range(n):
                est[i] += bt * ez[j, i]
    if smooth and not _solve_w(solve_cb, mat, fl, ctr, est, est):
        return -1, 0.0
    return 1, _error_norm(est, uprev, u, atol, rtol, fl[FL_NORM_MAX] != 0)


@njit(**_OPTS)
def _hermite(theta, dt, uprev, u, f0, f1, out):
    """``hermite``: the cubic through (t, uprev, f0) and (t + dt, u, f1)."""
    t2 = theta * theta
    t3 = t2 * theta
    h00 = 2 * t3 - 3 * t2 + 1
    h10 = t3 - 2 * t2 + theta
    h01 = -2 * t3 + 3 * t2
    h11 = t3 - t2
    a = h10 * dt
    b = h11 * dt
    for i in range(u.size):
        out[i] = h00 * uprev[i] + a * f0[i] + h01 * u[i] + b * f1[i]


# --- FBDF (``methods/fbdf.py``) ----------------------------------------------------------------------------
# coef: BDF_COEFFS, row k at FB_STRIDE * k. ``fb``: the history (rows of uh,
# in the order uhi gives, newest first), the correctors, the predictor, the
# history's times from its newest point and as fractions of the step, the
# finite-difference work and buffers, then the state (fbv, fbi).


@njit(**_OPTS)
def _fornberg(xs, count, x0, m, c, w):
    """``fornberg_weights``: the weights for the m-th derivative at x0 from
    the first ``count`` nodes, the highest derivative only, into w."""
    stride = count
    for i in range(count * (m + 1)):
        c[i] = 0.0
    c[0] = 1.0
    c1 = 1.0
    c4 = xs[0] - x0
    for i in range(1, count):
        mn = min(i, m)
        c2 = 1.0
        c5 = c4
        c4 = xs[i] - x0
        for j in range(i):
            c3 = xs[i] - xs[j]
            c2 *= c3
            if j == i - 1:
                for k in range(mn, 0, -1):
                    c[i + k * stride] = c1 * (k * c[(i - 1) + (k - 1) * stride] - c5 * c[(i - 1) + k * stride]) / c2
                c[i] = -c1 * c5 * c[i - 1] / c2
            for k in range(mn, 0, -1):
                c[j + k * stride] = (c4 * c[j + k * stride] - k * c[j + (k - 1) * stride]) / c3
            c[j] = c4 * c[j] / c3
        c1 = c2
    for i in range(count):
        w[i] = c[i + m * stride]


@njit(**_OPTS)
def _estimate_terk(fb, m, dt, uprev, u, atol, rtol, norm_max):
    """``FBDFCache.estimate_terk``: ||h^(m-1) y^(m-1)(t+h)|| from the real
    history by an m-node formula."""
    uh, uhi, corr, upred, ts, thetas, fdw, xs, fw, tmp, v, fbv, fbi = fb
    count = min(m, fbi[FI_N_HISTORY] + 1)
    if count < 2:
        return np.inf
    xs[0] = dt
    for i in range(count - 1):
        xs[i + 1] = ts[i]
    _fornberg(xs, count, dt, count - 1, fdw, fw)
    n = u.size
    w0 = fw[0]
    for q in range(n):
        tmp[q] = w0 * u[q]
    for j in range(1, count):
        wj = fw[j]
        row = uhi[j - 1]
        for q in range(n):
            tmp[q] += wj * uh[row, q]
    scale = _jpow(abs(dt), float(count - 1))
    for q in range(n):
        tmp[q] *= scale
    return _error_norm(tmp, uprev, u, atol, rtol, norm_max)


@njit(**_OPTS)
def _lagrange(fb, xi, count, out):
    """``FBDFCache.lagrange``: the history's interpolant at theta = xi, the
    newest point plus weighted differences from it."""
    uh, uhi, corr, upred, ts, thetas, fdw, xs, fw, tmp, v, fbv, fbi = fb
    n = out.size
    r0 = uhi[0]
    for q in range(n):
        out[q] = uh[r0, q]
    for j in range(1, count):
        w = 1.0
        for m in range(count):
            if m == j:
                continue
            w *= (xi - thetas[m]) / (thetas[j] - thetas[m])
        if w == 0:
            continue
        rj = uhi[j]
        for q in range(n):
            out[q] += w * (uh[rj, q] - uh[r0, q])


@njit(**_OPTS)
def _fbdf_step(f, model, pycb, jac_cb, jac, factor_cb, solve_cb, mat, fl, ctr, coef, fb, nwt, ns, ni, t, dt, uprev, u,
               fsalfirst, atol, atol_fixed, rtol, kry):
    """``FBDFCache.step``: (1, the error estimate) with the order for the
    next step decided, (0, 0) when W is singular or Newton does not
    converge, (-1, 0) when a callback raised. A KrylovFBDF forms no W: its
    Newton iterations are solved by GMRES (``_krylov_solve``)."""
    uh, uhi, corr, upred, ts, thetas, fdw, xs, fw, tmp, v, fbv, fbi = fb
    ws = mat[0]
    z, ntmp = nwt[0], nwt[1]
    n = u.size
    norm_max = fl[FL_NORM_MAX] != 0
    k = min(fbi[FI_ORDER], max(1, fbi[FI_N_HISTORY]))
    fbi[FI_ORDER] = k
    row = FB_STRIDE * k
    gamma = 1 / coef[row]
    gamma_dt = gamma * dt
    tdt = dt  # t + dt on the history's own clock
    krylov = fbi[FI_KRYLOV] != 0
    if krylov:
        # Nothing to form, only this step's error weights to set; `need_new`
        # is what the Newton iteration makes of its last contraction rate,
        # not believed after a restart or a failure.
        need_new = fbi[FI_KRYLOV_FRESH] != 0 or not _fast(ns, ni)
        fbi[FI_KRYLOV_FRESH] = 0
        _krylov_prepare(kry, atol_fixed, rtol, uprev, u)
    else:
        need_new = ws[WS_STALE] != 0 or ws[WS_HAVE] == 0 or not _fast(ns, ni)
        r = _form_w(f, model, pycb, jac_cb, jac, factor_cb, mat, fl, ctr, t, uprev, fsalfirst, gamma_dt, 0.0,
                    need_new)
        if r <= 0:
            return r, 0.0
    nh = fbi[FI_N_HISTORY]
    count = min(k + 1, nh)
    for j in range(count):
        thetas[j] = ts[j] / dt
    if fbi[FI_FROM_EVENT] >= 1 and count >= 2:
        _lagrange(fb, 1.0, count, upred)
        for i in range(1, k):
            _lagrange(fb, float(-i), count, corr[i])
    else:
        # The first step from a start: an Euler predictor (fbdf.py explains).
        for q in range(n):
            upred[q] = uprev[q] + dt * fsalfirst[q]
        for i in range(1, k):
            for q in range(n):
                corr[i, q] = uprev[q]
    for q in range(n):
        v[q] = 0.0
    for m in range(1, k):
        am = coef[row + m + 1]
        for q in range(n):
            v[q] = v[q] + am * (corr[m, q] - uprev[q])
    for q in range(n):
        ntmp[q] = uprev[q] - v[q] * gamma
        z[q] = upred[q]
    ns[NS_GAMMA] = gamma
    ns[NS_C] = 1.0
    ni[NI_METHOD] = N_MULTISTEP
    ns[NS_ERRC] = 1 / (k + 1)
    st = _newton(f, model, pycb, solve_cb, mat, fl, ctr, nwt, ns, ni, t, dt, uprev, atol_fixed, rtol, need_new,
                 fbi[FI_CONSFAIL] == 0, kry, krylov)
    ns[NS_ERRC] = 1.0
    if st < 0:
        return -1, 0.0
    if st != N_CONVERGENCE:
        if krylov:
            fbi[FI_KRYLOV_FRESH] = 1
        else:
            ws[WS_STALE] = 1.0
        if fbi[FI_ORDER] > 1 and ni[NI_NFAILS] >= 3:
            fbi[FI_ORDER] -= 1
        fbi[FI_CONSFAIL] += 1
        fbi[FI_NCONSTEPS] = 0
        return 0, 0.0
    for q in range(n):
        u[q] = z[q]
    # The local error, from the predictor-corrector difference.
    for q in range(n):
        tmp[q] = u[q] - upred[q]
    for j in range(count):
        sj = (j + 1) * dt / (tdt - ts[j])
        for q in range(n):
            tmp[q] *= sj
    lte = -1 / (1 + k)
    for j in range(2, k + 1):
        rr = float(1 - j)
        for m in range(2, count + 1):
            rr *= ((tdt - j * dt) - ts[m - 1]) / (m * dt)
        lte -= coef[row + j - 1] * rr
    for q in range(n):
        tmp[q] = lte * tmp[q]
    eest = _error_norm(tmp, uprev, u, atol, rtol, norm_max)
    # What the order should be next.
    fbv[FB_TERK] = _estimate_terk(fb, k + 1, dt, uprev, u, atol, rtol, norm_max)
    fbv[FB_TERKM1] = _estimate_terk(fb, k, dt, uprev, u, atol, rtol, norm_max) if k > 1 else np.inf
    fbv[FB_TERKM2] = _estimate_terk(fb, k - 1, dt, uprev, u, atol, rtol, norm_max) if k > 2 else np.inf
    fbv[FB_TERKP1] = (_estimate_terk(fb, k + 2, dt, uprev, u, atol, rtol, norm_max)
                      if (fbi[FI_QWAIT] == 0 and k < fbv[FB_MAX_ORDER] and nh >= k + 2) else 0.0)
    fbv[FB_TERKM3] = _estimate_terk(fb, k - 2, dt, uprev, u, atol, rtol, norm_max) if k > 3 else np.inf
    _fbdf_decide(fbv, fbi)
    return 1, eest


@njit(**_OPTS)
def _fbdf_init(fb, ni, uprev):
    """``FBDFCache.init``: the history begins at the state."""
    uh, uhi, ts, fbi = fb[0], fb[1], fb[4], fb[12]
    ni[NI_METHOD] = N_MULTISTEP
    ts[0] = 0.0
    for q in range(uprev.size):
        uh[uhi[0], q] = uprev[q]
    fbi[FI_N_HISTORY] = 1
    fbi[FI_FROM_EVENT] = 0


@njit(**_OPTS)
def _fbdf_restart(fb, uprev):
    """``FBDFCache.restart``: as a method switched back to starts again --
    its history from the state, at its lowest order."""
    uh, uhi, ts, fbv, fbi = fb[0], fb[1], fb[4], fb[11], fb[12]
    fbi[FI_KRYLOV_FRESH] = 1
    ts[0] = 0.0
    for q in range(uprev.size):
        uh[uhi[0], q] = uprev[q]
    fbi[FI_N_HISTORY] = 1
    fbi[FI_FROM_EVENT] = 0
    fbi[FI_ORDER] = fbi[FI_MIN_ORDER]
    fbi[FI_PREV_ORDER] = fbi[FI_ORDER]
    fbi[FI_QWAIT] = 3
    fbi[FI_NCONSTEPS] = 0
    fbi[FI_CONSFAIL] = 0
    fbv[FB_TERKM2] = np.inf
    fbv[FB_TERKM1] = np.inf
    fbv[FB_TERK] = np.inf
    fbv[FB_TERKP1] = 0.0


@njit(**_OPTS)
def _fbdf_decide(fbv, fbi):
    """``FBDFCache.decide``: the order and the estimate the next step takes."""
    fbi[FI_PENDING] = fbi[FI_ORDER]
    k = fbi[FI_ORDER]
    terk = fbv[FB_TERK]
    terkm1 = fbv[FB_TERKM1]
    terkm2 = fbv[FB_TERKM2]
    terkp1 = fbv[FB_TERKP1]
    decreasing = terkm2 > terkm1 and terkm1 > terk and terk > terkp1
    if (k < fbv[FB_MAX_ORDER] and fbi[FI_QWAIT] == 0
            and ((k == 1 and terk > terkp1) or (k == 2 and terkm1 > terk and terk > terkp1) or (k > 2 and decreasing))):
        k += 1
        terk = terkp1
    elif not decreasing and k > max(2, fbi[FI_MIN_ORDER]):
        terk = terkm1
        k -= 1
    fbi[FI_NEXT_ORDER] = k
    fbv[FB_NEXT_TERK] = terk


@njit(**_OPTS)
def _fbdf_accepted(coef, fb, u, dtjust):
    """``FBDFCache.accepted``: the order decided, the history moved on by the
    step just kept; the step it proposes next."""
    uh, uhi, corr, upred, ts, thetas, fdw, xs, fw, tmp, v, fbv, fbi = fb
    fbi[FI_PREV_ORDER] = fbi[FI_PENDING]
    k = fbi[FI_NEXT_ORDER]
    terk = fbv[FB_NEXT_TERK]
    if k != fbi[FI_ORDER]:
        fbi[FI_NCONSTEPS] = 0
        fbi[FI_ORDER] = k
    if not (terk > 0):
        q = 1 / fbv[FB_QMAX]
    else:
        q = _jpow(6 * terk / (coef[FB_STRIDE * k] * (k + 1)), 1 / (k + 1))
    q = _jmin(1 / fbv[FB_QMIN], _jmax(1 / fbv[FB_QMAX], q))
    if q <= fbv[FB_QSTEADY_MAX] and q >= fbv[FB_QSTEADY_MIN]:
        q = 1.0
    fbi[FI_CONSFAIL] = 0
    fbi[FI_NCONSTEPS] += 1
    fbi[FI_FROM_EVENT] += 1
    if fbi[FI_ORDER] != fbi[FI_PREV_ORDER]:
        fbi[FI_QWAIT] = fbi[FI_ORDER] + 2
    elif fbi[FI_QWAIT] > 0:
        fbi[FI_QWAIT] -= 1
    # The oldest row becomes the newest, holding u; the times move back by the step.
    last = uhi[FB_K - 1]
    for j in range(FB_K - 1, 0, -1):
        uhi[j] = uhi[j - 1]
        ts[j] = ts[j - 1] - dtjust
    uhi[0] = last
    for q_ in range(u.size):
        uh[last, q_] = u[q_]
    ts[0] = 0.0
    if fbi[FI_N_HISTORY] < FB_K:
        fbi[FI_N_HISTORY] += 1
    return dtjust / q


@njit(**_OPTS)
def _fbdf_rejected(fb, eest, dt):
    """``FBDFCache.rejected``: the order and step to try again with; the step."""
    uh, uhi, corr, upred, ts, thetas, fdw, xs, fw, tmp, v, fbv, fbi = fb
    k = fbi[FI_ORDER]
    h = abs(dt)
    fbi[FI_CONSFAIL] += 1
    fbi[FI_NCONSTEPS] = 0
    if fbi[FI_CONSFAIL] > 1:
        h /= 2
    z = fbv[FB_GAMMA] * _jpow(eest, 1 / (k + 1))
    hk = h / z if z <= 10 else 0.1 * h
    hn = hk
    kn = k
    terkm1 = fbv[FB_TERKM1]
    if k > 1 and math.isfinite(terkm1):
        zk1 = 1.3 * _jpow(terkm1, 1 / k)
        hk1 = h / zk1 if zk1 <= 10 else 0.1 * h
        if fbi[FI_CONSFAIL] > 2 or abs(hk1) > abs(hk):
            hn = _jmin(h, abs(hk1))
            kn = k - 1
    fbi[FI_ORDER] = max(fbi[FI_MIN_ORDER], kn)
    return _jsign(dt) * hn


@njit(**_OPTS)
def _fbdf_interpolate(fb, theta, u, out):
    """``FBDFCache.interpolate``: the Lagrange interpolant through the new
    point (theta = 1) and the points of history the step was taken from."""
    uh, uhi, corr, upred, ts, thetas, fdw, xs, fw, tmp, v, fbv, fbi = fb
    n = u.size
    m = min(fbi[FI_ORDER], fbi[FI_N_HISTORY])
    w = 1.0
    for j in range(m):
        w *= (theta - thetas[j]) / (1 - thetas[j])
    r0 = uhi[0]
    for q in range(n):
        out[q] = uh[r0, q] + w * (u[q] - uh[r0, q])
    for a in range(1, m):
        wa = (theta - 1) / (thetas[a] - 1)
        for b in range(m):
            if b == a:
                continue
            wa *= (theta - thetas[b]) / (thetas[a] - thetas[b])
        if wa == 0:
            continue
        ra = uhi[a]
        for q in range(n):
            out[q] += wa * (uh[ra, q] - uh[r0, q])


# --- QNDF and QBDF (``methods/qndf.py``) ----------------------------------------------------------------------
# coef: kappa per order (QN_KAPPA) and GAMMA (QN_GAMMAS). ``qn``: the
# backward differences D, the predictor u0, room for the rescaled
# differences and for the interpolant's sums, R, RU and U (QN_S x QN_S, by
# rows), then the state (qnv, qni).


@njit(inline='always', **_OPTS)
def _qndf_error_constant(coef, m):
    """``QNDFCache.error_constant_at``: kappa(m)*gamma(m) + 1/(m+1)."""
    return coef[QN_KAPPA + m - 1] * coef[QN_GAMMAS + m] + 1 / (m + 1)


@njit(**_OPTS)
def _qndf_step(f, model, pycb, jac_cb, jac, factor_cb, solve_cb, mat, fl, ctr, coef, qn, nwt, ns, ni, t, dt, uprev, u,
               fsalfirst, atol, atol_fixed, rtol, kry):
    """``QNDFCache.step``: (1, the error estimate) with the estimates one
    order either side, (0, 0) when W is singular or Newton does not converge,
    (-1, 0) when a callback raised."""
    D, u0, new, cols, R, RU, U, qnv, qni = qn
    ws = mat[0]
    z, ntmp, dd = nwt[0], nwt[1], nwt[4]
    n = u.size
    norm_max = fl[FL_NORM_MAX] != 0
    k = qni[QI_ORDER]
    if qnv[QN_MAX_ORDER] < k:
        k = int(qnv[QN_MAX_ORDER])
    qni[QI_ORDER] = k
    if qni[QI_STARTED] == 0:
        for q in range(n):
            D[1, q] = dt * fsalfirst[q]
        qnv[QN_DTPREV] = dt
        qni[QI_PREV_ORDER] = k
        qni[QI_STARTED] = 1
    elif qnv[QN_DTPREV] == 0:
        qnv[QN_DTPREV] = dt
        qni[QI_PREV_ORDER] = k
    elif dt != qnv[QN_DTPREV] or qni[QI_PREV_ORDER] != k:
        # D <- D*(R*U), onto the new step (``rescale_matrix``).
        rho = dt / qnv[QN_DTPREV]
        for rr in range(1, k + 1):
            v = -rr * rho
            R[rr - 1] = v
            for j in range(2, k + 1):
                v = v * ((j - 1) - rr * rho) / j
                R[(j - 1) * QN_S + (rr - 1)] = v
        for i in range(1, k + 1):
            for j in range(1, k + 1):
                acc = 0.0
                for m in range(1, k + 1):
                    acc += R[(i - 1) * QN_S + (m - 1)] * U[(m - 1) * QN_S + (j - 1)]
                RU[(i - 1) * QN_S + (j - 1)] = acc
        for j in range(1, k + 1):
            for q in range(n):
                new[j - 1, q] = 0.0
            for i in range(1, k + 1):
                w = RU[(i - 1) * QN_S + (j - 1)]
                if w == 0:
                    continue
                for q in range(n):
                    new[j - 1, q] += w * D[i, q]
        for j in range(1, k + 1):
            for q in range(n):
                D[j, q] = new[j - 1, q]
        qni[QI_NCONSTEPS] = 0
        qnv[QN_DTPREV] = dt
    qni[QI_PREV_ORDER] = k
    beta0 = 1 / ((1 - coef[QN_KAPPA + k - 1]) * coef[QN_GAMMAS + k])
    need_new = ws[WS_STALE] != 0 or ws[WS_HAVE] == 0 or not _fast(ns, ni)
    r = _form_w(f, model, pycb, jac_cb, jac, factor_cb, mat, fl, ctr, t, uprev, fsalfirst, beta0 * dt, 0.0, need_new)
    if r <= 0:
        return r, 0.0
    phi = dd
    for q in range(n):
        u0[q] = uprev[q]
        phi[q] = 0.0
    for j in range(1, k + 1):
        g = coef[QN_GAMMAS + j]
        for q in range(n):
            u0[q] += D[j, q]
            phi[q] += g * D[j, q]
    for q in range(n):
        ntmp[q] = u0[q] - beta0 * phi[q]
        z[q] = u0[q]
    ns[NS_GAMMA] = beta0
    ns[NS_C] = 1.0
    ni[NI_METHOD] = N_MULTISTEP
    ns[NS_ERRC] = abs(_qndf_error_constant(coef, k))
    st = _newton(f, model, pycb, solve_cb, mat, fl, ctr, nwt, ns, ni, t, dt, uprev, atol_fixed, rtol, need_new,
                 qni[QI_CONSFAIL] == 0, kry, False)
    ns[NS_ERRC] = 1.0
    if st < 0:
        return -1, 0.0
    if st != N_CONVERGENCE:
        ws[WS_STALE] = 1.0
        if qni[QI_ORDER] > qni[QI_MIN_ORDER] and ni[NI_NFAILS] >= 3:
            qni[QI_ORDER] -= 1
        qni[QI_CONSFAIL] += 1
        qni[QI_NCONSTEPS] = 0
        return 0, 0.0
    for q in range(n):
        u[q] = z[q]
    # dd = what the predictor missed by; the estimates read the differences
    # as they will be once the step is kept, and D waits for ``accepted``.
    for q in range(n):
        dd[q] = u[q] - u0[q]
    eest = abs(_qndf_error_constant(coef, k)) * _error_norm(dd, uprev, u, atol, rtol, norm_max)
    tmp = nwt[2]
    if k > 1:
        for q in range(n):
            tmp[q] = D[k, q] + dd[q]
        qnv[QN_EEST1] = abs(_qndf_error_constant(coef, k - 1)) * _error_norm(tmp, uprev, u, atol, rtol, norm_max)
    else:
        qnv[QN_EEST1] = np.inf
    if k < qnv[QN_MAX_ORDER]:
        for q in range(n):
            tmp[q] = dd[q] - D[k + 1, q]
        qnv[QN_EEST2] = abs(_qndf_error_constant(coef, k + 1)) * _error_norm(tmp, uprev, u, atol, rtol, norm_max)
    else:
        qnv[QN_EEST2] = np.inf
    return 1, eest


@njit(**_OPTS)
def _qndf_accepted(qn, u, eest, dtjust):
    """``QNDFCache.accepted``: the differences rolled past the step just kept
    (``commit``, from the state kept), the order and the step it proposes next."""
    D, u0, new, cols, R, RU, U, qnv, qni = qn
    n = u.size
    k = qni[QI_ORDER]
    for q in range(n):
        dd = u[q] - u0[q]
        D[k + 2, q] = dd - D[k + 1, q]
        D[k + 1, q] = dd
    for j in range(k, 0, -1):
        for q in range(n):
            D[j, q] += D[j + 1, q]
    qni[QI_CONSFAIL] = 0
    qni[QI_NCONSTEPS] += 1
    h = abs(dtjust)
    if not (eest > 0):
        return dtjust * qnv[QN_QMAX]
    prefer_const_step = qni[QI_NCONSTEPS] < k + 2
    z = qnv[QN_GAMMA] * _jpow(eest, 1 / (k + 1))
    hk = 10 * h if z <= 0.1 else h / z
    hn = hk
    kn = k
    eest1 = qnv[QN_EEST1]
    eest2 = qnv[QN_EEST2]
    if k > 1 and math.isfinite(eest1):
        zm = 1.3 * _jpow(eest1, 1 / k)
        hm = 0.0
        if zm <= 0.1:
            hm = 10 * h
        elif zm <= 1.3:
            hm = h / zm
        if hm > hk:
            hn = hm
            kn = k - 1
    if k < qnv[QN_MAX_ORDER] and math.isfinite(eest2):
        zp = 1.4 * _jpow(eest2, 1 / (k + 2))
        hp = 0.0
        if zp <= 0.1:
            hp = 10 * h
        elif zp <= 1.4:
            hp = h / zp
        if hp > hn:
            hn = hp
            kn = k + 1
    qni[QI_ORDER] = max(qni[QI_MIN_ORDER], kn)
    q = h / hn
    if prefer_const_step and q > 0.6 and q < 1.2:
        hnew = h
    elif q <= qnv[QN_QSTEADY_MAX] and q >= qnv[QN_QSTEADY_MIN]:
        hnew = h
    else:
        hnew = h / _jmin(1 / qnv[QN_QMIN], _jmax(1 / qnv[QN_QMAX], q))
    return _jsign(dtjust) * hnew


@njit(**_OPTS)
def _qndf_rejected(qn, eest, dt):
    """``QNDFCache.rejected``: the order and step to try again with; the step."""
    D, u0, new, cols, R, RU, U, qnv, qni = qn
    k = qni[QI_ORDER]
    h = abs(dt)
    qni[QI_CONSFAIL] += 1
    qni[QI_NCONSTEPS] = 0
    if qni[QI_CONSFAIL] > 1:
        h /= 2
    z = qnv[QN_GAMMA] * _jpow(eest, 1 / (k + 1))
    hk = h / z if z <= 10 else 0.1 * h
    hn = hk
    kn = k
    eest1 = qnv[QN_EEST1]
    if k > 1 and math.isfinite(eest1):
        zm = 1.3 * _jpow(eest1, 1 / k)
        hm = h / zm if zm <= 10 else 0.1 * h
        if qni[QI_CONSFAIL] > 2 or abs(hm) > abs(hk):
            hn = _jmin(h, abs(hm))
            kn = k - 1
    qni[QI_ORDER] = max(qni[QI_MIN_ORDER], kn)
    return _jsign(dt) * hn


@njit(**_OPTS)
def _qndf_interpolate(qn, theta, u, out):
    """``QNDFCache.interpolate``: u + sum_j phi_j(theta - 1) del^j u, with the
    differences as they stand once the step is kept."""
    D, u0, new, cols, R, RU, U, qnv, qni = qn
    n = u.size
    k = qni[QI_ORDER]
    s = theta - 1
    for q in range(n):
        acc = u[q] - u0[q]
        for j in range(k, 0, -1):
            acc = D[j, q] + acc
            cols[j, q] = acc
    for q in range(n):
        out[q] = u[q]
    # phi_1 = s, phi_j = phi_(j-1) (s + j - 1) / j.
    p = s
    for j in range(1, k + 1):
        if j > 1:
            p = p * (s + (j - 1)) / j
        for q in range(n):
            out[q] += p * cols[j, q]


# --- RadauIIA5 (``methods/radau.py``) --------------------------------------------------------------------------
# coef: RADAU_COEFFICIENTS. ``ra``: the stages z (3 x n), their transforms w,
# the last accepted step's polynomial (cont), f at the stages, a state
# buffer, Radau's tolerances, the error estimate, the complex W by columns,
# its pivots and a complex right-hand side, then the state (rav, rai).


@njit(**_OPTS)
def _radau_form_complex(jac, fl, ra, alpha_dt, beta_dt, lints):
    """``RadauCache.form_complex_w``: ((alpha + i beta)/h) I - J, factorised."""
    jd, jv, gptr, gcols, eptr, erow, ewhich, eent = jac[0], jac[1], jac[2], jac[3], jac[4], jac[5], jac[6], jac[7]
    cw, cpiv = ra[7], ra[8]
    n = cw.shape[0]
    if fl[FL_SPARSE]:
        # J's values onto zeros, at the pattern's places (``re[row_idx, cols] = -values``).
        for j in range(n):
            for i in range(n):
                cw[j, i] = 0.0
        for g in range(gptr.size - 1):
            for e in range(eptr[g], eptr[g + 1]):
                cw[gcols[ewhich[e]], erow[e]] = complex(-jv[eent[e]], 0.0)
    else:
        for j in range(n):
            for i in range(n):
                cw[j, i] = complex(-jd[i, j], 0.0)
    for i in range(n):
        cw[i, i] = complex(cw[i, i].real + alpha_dt, beta_dt)
    return _zgetrf(cw, cpiv, lints)


@njit(**_OPTS)
def _radau_step(f, model, pycb, jac_cb, jac, factor_cb, solve_cb, mat, fl, ctr, coef, ra, t, dt, uprev, u, fsalfirst,
                fsallast, atol, nn, rtol):
    """``RadauCache.step``: the 3n x 3n Newton system as one real solve with
    (gamma/h) I - J and one complex with ((alpha + i beta)/h) I - J. (1, the
    error estimate), (0, 0) when a matrix is singular or Newton does not
    converge, (-1, 0) when a callback raised, (-2, 0) where Python divides by zero."""
    P, X, Wm, IW = model
    zs, wz, cont, ff, ust, atol_r, utilde, cw, cpiv, cb, rav, rai = ra
    ws, lints, trans = mat[0], mat[3], mat[4]
    n = u.size
    T11, T12, T13, T21, T22, T23, T31 = coef[0], coef[1], coef[2], coef[3], coef[4], coef[5], coef[6]
    TI11, TI12, TI13, TI21, TI22, TI23 = coef[7], coef[8], coef[9], coef[10], coef[11], coef[12]
    TI31, TI32, TI33 = coef[13], coef[14], coef[15]
    c1, c2, gamma, alpha, beta = coef[16], coef[17], coef[18], coef[19], coef[20]
    e1, e2, e3 = coef[21], coef[22], coef[23]
    z1, z2, z3 = zs[0], zs[1], zs[2]
    w1, w2, w3 = wz[0], wz[1], wz[2]
    ff1, ff2, ff3 = ff[0], ff[1], ff[2]
    rtol_r = _jpow(rtol, 2 / 3) / 10
    if rtol == 0:
        return -2, 0.0
    scale = rtol_r / rtol
    for i in range(n):
        atol_r[i] = atol[i] * scale
    gamma_dt = gamma / dt
    alpha_dt = alpha / dt
    beta_dt = beta / dt
    have_history = rai[RI_HAVE_HISTORY] != 0
    need_new = ws[WS_STALE] != 0 or ws[WS_HAVE] == 0 or rai[RI_STATUS] != RS_FAST
    # The complex half follows every renewal of J, including one for age.
    jacs_before = ctr[C_NJAC]
    r = _form_w(f, model, pycb, jac_cb, jac, factor_cb, mat, fl, ctr, t, uprev, fsalfirst, dt / gamma, 1.0, need_new)
    if r <= 0:
        return r, 0.0
    jac_renewed = ctr[C_NJAC] != jacs_before
    if need_new or jac_renewed or rai[RI_COMPLEX_VALID] == 0 or rav[RA_COMPLEX_DT] != dt:
        if not _radau_form_complex(jac, fl, ra, alpha_dt, beta_dt, lints):
            return 0, 0.0
        rai[RI_COMPLEX_VALID] = 1
        rav[RA_COMPLEX_DT] = dt
    # --- the starting guess
    if not have_history:
        for i in range(n):
            z1[i] = 0.0
            z2[i] = 0.0
            z3[i] = 0.0
            w1[i] = 0.0
            w2[i] = 0.0
            w3[i] = 0.0
    else:
        # Extrapolated from the last accepted step's polynomial.
        c1m1 = c1 - 1
        c2m1 = c2 - 1
        c3p = dt / rav[RA_DTPREV]
        c1p = c1 * c3p
        c2p = c2 * c3p
        for i in range(n):
            a1 = cont[0, i]
            a2 = cont[1, i]
            a3 = cont[2, i]
            z1[i] = c1p * (a1 + (c1p - c2m1) * (a2 + (c1p - c1m1) * a3))
            z2[i] = c2p * (a1 + (c2p - c2m1) * (a2 + (c2p - c1m1) * a3))
            z3[i] = c3p * (a1 + (c3p - c2m1) * (a2 + (c3p - c1m1) * a3))
        # Kept at or above zero where the caller asked for that (radau.js explains).
        if nn.size:
            for i in range(n):
                if nn[i] != 0:
                    floor = -uprev[i]
                    if z1[i] < floor:
                        z1[i] = floor
                    if z2[i] < floor:
                        z2[i] = floor
                    if z3[i] < floor:
                        z3[i] = floor
        for i in range(n):
            w1[i] = TI11 * z1[i] + TI12 * z2[i] + TI13 * z3[i]
            w2[i] = TI21 * z1[i] + TI22 * z2[i] + TI23 * z3[i]
            w3[i] = TI31 * z1[i] + TI32 * z2[i] + TI33 * z3[i]
    # --- Newton
    kappa = rav[RA_KAPPA]
    max_iters = rai[RI_MAX_ITERS]
    eta = _jpow(_jmax(rav[RA_ETA_OLD], EPS), 0.8)
    ndw = 1.0
    converged = False
    it = 0
    rhs1 = utilde
    while it < max_iters:
        it += 1
        for i in range(n):
            ust[i] = uprev[i] + z1[i]
        f(t + c1 * dt, ust, ff1, P, X, Wm, IW, pycb)
        for i in range(n):
            ust[i] = uprev[i] + z2[i]
        f(t + c2 * dt, ust, ff2, P, X, Wm, IW, pycb)
        for i in range(n):
            ust[i] = uprev[i] + z3[i]
        f(t + dt, ust, ff3, P, X, Wm, IW, pycb)
        ctr[C_NF] += 3
        for i in range(n):
            fw1 = TI11 * ff1[i] + TI12 * ff2[i] + TI13 * ff3[i]
            fw2 = TI21 * ff1[i] + TI22 * ff2[i] + TI23 * ff3[i]
            fw3 = TI31 * ff1[i] + TI32 * ff2[i] + TI33 * ff3[i]
            rhs1[i] = fw1 - gamma_dt * w1[i]
            cb[i] = complex(fw2 - alpha_dt * w2[i] + beta_dt * w3[i], fw3 - beta_dt * w2[i] - alpha_dt * w3[i])
        if not _solve_w(solve_cb, mat, fl, ctr, rhs1, rhs1):
            return -1, 0.0
        _zgetrs(cw, cpiv, lints, trans, cb)
        ctr[C_NSOLVE] += 1
        ndw_prev = ndw
        s1 = _scaled_norm(rhs1, uprev, u, atol_r, rtol_r)
        s2 = 0.0
        s3 = 0.0
        for i in range(n):
            wgt = atol_r[i] + rtol_r * _npmax(abs(uprev[i]), abs(u[i]))
            r2 = cb[i].real / wgt
            r3 = cb[i].imag / wgt
            s2 += r2 * r2
            s3 += r3 * r3
        ndw = s1 + math.sqrt(s2 / n) + math.sqrt(s3 / n)
        if not math.isfinite(ndw):
            break
        if it > 1:
            theta = ndw / ndw_prev
            diverging = theta > 1
            crawling = ndw * _jpow(theta, float(max_iters - it)) > kappa * (1 - theta)
            if diverging or crawling:
                rai[RI_STATUS] = RS_DIVERGENCE
                break
            eta = theta / (1 - theta)
        for i in range(n):
            w1[i] += rhs1[i]
            w2[i] += cb[i].real
            w3[i] += cb[i].imag
            z1[i] = T11 * w1[i] + T12 * w2[i] + T13 * w3[i]
            z2[i] = T21 * w1[i] + T22 * w2[i] + T23 * w3[i]
            z3[i] = T31 * w1[i] + w2[i]
        if eta * ndw < kappa and (it > 1 or ndw == 0 or have_history):
            converged = True
            rai[RI_STATUS] = RS_FAST if eta < rav[RA_CUTOFF] else RS_CONVERGENCE
            break
    if not converged:
        ws[WS_STALE] = 1.0
        return 0, 0.0
    rav[RA_ETA_OLD] = eta
    for i in range(n):
        u[i] = uprev[i] + z3[i]
    # --- the error estimate
    e1dt = e1 / dt
    e2dt = e2 / dt
    e3dt = e3 / dt
    smooth = rai[RI_SMOOTH] != 0
    for i in range(n):
        utilde[i] = fsalfirst[i] + e1dt * z1[i] + e2dt * z2[i] + e3dt * z3[i]
    if smooth and not _solve_w(solve_cb, mat, fl, ctr, utilde, utilde):
        return -1, 0.0
    eest = _scaled_norm(utilde, uprev, u, atol_r, rtol_r)
    if not (eest < 1) and not have_history:
        for i in range(n):
            ust[i] = uprev[i] + utilde[i]
        f(t, ust, ff1, P, X, Wm, IW, pycb)
        ctr[C_NF] += 1
        for i in range(n):
            utilde[i] = ff1[i] + e1dt * z1[i] + e2dt * z2[i] + e3dt * z3[i]
        if smooth and not _solve_w(solve_cb, mat, fl, ctr, utilde, utilde):
            return -1, 0.0
        eest = _scaled_norm(utilde, uprev, u, atol_r, rtol_r)
    f(t + dt, u, fsallast, P, X, Wm, IW, pycb)
    ctr[C_NF] += 1
    return 1, eest


@njit(**_OPTS)
def _radau_accepted(coef, ra, dtjust):
    """``RadauCache.accepted``: the step's collocation polynomial kept for the
    next starting guess."""
    zs, wz, cont, ff, ust, atol_r, utilde, cw, cpiv, cb, rav, rai = ra
    c1, c2 = coef[16], coef[17]
    rav[RA_DTPREV] = dtjust
    rai[RI_HAVE_HISTORY] = 1
    c1m1 = c1 - 1
    c2m1 = c2 - 1
    c1mc2 = c1 - c2
    for i in range(zs.shape[1]):
        a1 = (zs[1, i] - zs[2, i]) / c2m1
        tmp = (zs[0, i] - zs[1, i]) / c1mc2
        a2 = (tmp - a1) / c1m1
        cont[0, i] = a1
        cont[1, i] = a2
        cont[2, i] = a2 - (tmp - zs[0, i] / c1) / c2


@njit(**_OPTS)
def _radau_interpolate(coef, ra, theta, uprev, out):
    """``RadauCache.interpolate``: the collocation polynomial through the
    three stages, in Newton form about the nodes 1, c2, c1."""
    zs = ra[0]
    c1, c2 = coef[16], coef[17]
    c1m1 = c1 - 1
    c2m1 = c2 - 1
    c1mc2 = c1 - c2
    th1 = theta - 1
    for i in range(out.size):
        k1 = (zs[1, i] - zs[2, i]) / c2m1
        tmp = (zs[0, i] - zs[1, i]) / c1mc2
        k2 = (tmp - k1) / c1m1
        k3 = k2 - (tmp - zs[0, i] / c1) / c2
        out[i] = uprev[i] + zs[2, i] + th1 * (k1 + (theta - c2) * (k2 + (theta - c1) * k3))


# --- what the loop reads off a step -------------------------------------------------------------------------


@njit(**_OPTS)
def _eval_at(method, coef, ros, fb, qn, ra, ex, r23, f, model, pycb, ctr, theta, t, dt, uprev, u, fsalfirst, fsallast,
             out):
    """``eval_at``: the step's own interpolant at theta -- the method's, or the
    cubic Hermite for the ESDIRKs, which have none. Vern7's works out its six
    stages the first time a step is read inside, with the model's f."""
    if method == M_ROSENBROCK:
        _ros_interpolate(coef, ros, theta, uprev, u, out)
    elif method == M_ESDIRK:
        _hermite(theta, dt, uprev, u, fsalfirst, fsallast, out)
    elif method == M_FBDF:
        _fbdf_interpolate(fb, theta, u, out)
    elif method == M_QNDF:
        _qndf_interpolate(qn, theta, u, out)
    elif method == M_TSIT5:
        _tsit5_interpolate(ex, theta, dt, uprev, u, out)
    elif method == M_VERN7:
        _vern7_interpolate(f, model, pycb, ctr, ex, theta, t, dt, uprev, u, out)
    elif method == M_ROS23:
        _ros23_interpolate(r23, theta, dt, uprev, u, out)
    else:
        _radau_interpolate(coef, ra, theta, uprev, out)


@njit(**_OPTS)
def _locate_root(method, coef, ros, fb, qn, ra, ex, r23, f, ctr, evf, model, pycb, which, g_start, t, dt, uprev, u,
                 fsalfirst, fsallast, ub, gb):
    """``_locate_root``: where in the step, as theta, event function ``which``
    crosses zero -- bisection then Illinois on the step's interpolant; the
    bracket's far end."""
    P, X, Wm, IW = model
    lo = 0.0
    hi = 1.0
    flo = g_start
    _eval_at(method, coef, ros, fb, qn, ra, ex, r23, f, model, pycb, ctr, 1.0, t, dt, uprev, u, fsalfirst, fsallast, ub)
    evf(t + 1.0 * dt, ub, gb, P, X, Wm, IW, pycb)
    fhi = gb[which]
    it = 0
    while it < 60 and hi - lo > 1e-14:
        denom = fhi - flo
        mid = 0.5 * (lo + hi) if denom == 0 else lo - flo * (hi - lo) / denom
        if not (lo < mid < hi):
            mid = 0.5 * (lo + hi)
        _eval_at(method, coef, ros, fb, qn, ra, ex, r23, f, model, pycb, ctr, mid, t, dt, uprev, u, fsalfirst, fsallast,
                 ub)
        evf(t + mid * dt, ub, gb, P, X, Wm, IW, pycb)
        fmid = gb[which]
        if fmid == 0:
            hi = mid
            break
        if (fmid < 0) == (flo < 0):
            lo = mid
            flo = fmid
            fhi *= 0.5
        else:
            hi = mid
            fhi = fmid
            flo *= 0.5
        it += 1
    return hi


@njit(**_OPTS)
def _find_event(method, coef, ros, fb, qn, ra, ex, r23, f, ctr, evf, model, pycb, evdir, evbuf, evwhich, found, t, dt,
                t0, uprev, u, fsalfirst, fsallast, ub, u_event):
    """``_find_event``: the earliest crossing inside the step just taken, each
    function in its own direction (the functions at the step's start in
    evbuf[0]); functions crossing together are reported together. Whether
    one crossed, and the time where every one of them has: the state there in
    u_event, the events marked in evwhich."""
    P, X, Wm, IW = model
    g_prev = evbuf[0]
    g_now = evbuf[1]
    nev = evdir.size
    evf(t + dt, u, g_now, P, X, Wm, IW, pycb)
    nfound = 0
    for i in range(nev):
        a = g_prev[i]
        b = g_now[i]
        d = evdir[i]
        rising = a < 0 and b >= 0
        falling = a > 0 and b <= 0
        if (d >= 0 and rising) or (d <= 0 and falling):
            theta = _locate_root(method, coef, ros, fb, qn, ra, ex, r23, f, ctr, evf, model, pycb, i, a, t, dt, uprev,
                                 u, fsalfirst, fsallast, ub, evbuf[2])
            t_event = t + theta * dt
            # A root at the instant the solve began is not a crossing (``_root_at_start``).
            if abs(t_event - t0) <= 16 * EPS * _jmax(abs(t0), abs(dt)):
                continue
            found[0, nfound] = theta
            found[1, nfound] = t_event
            found[2, nfound] = i
            nfound += 1
    if nfound == 0:
        return False, 0.0
    first = 0
    for k in range(1, nfound):
        if found[0, k] < found[0, first]:
            first = k
    t_first = found[1, first]
    together = _jmax(2e-14 * abs(dt), 16 * EPS * _jmax(abs(t_first), abs(dt)))
    # Handed back where every one of them has crossed: the latest.
    last = first
    for i in range(nev):
        evwhich[i] = 0
    for k in range(nfound):
        if abs(found[1, k] - t_first) <= together:
            evwhich[int(found[2, k])] = 1
            if found[0, k] > found[0, last]:
                last = k
    _eval_at(method, coef, ros, fb, qn, ra, ex, r23, f, model, pycb, ctr, found[0, last], t, dt, uprev, u, fsalfirst,
             fsallast, u_event)
    return True, found[1, last]


@njit(**_OPTS)
def _collect(t, y, ct, cy, cint, cflt):
    """``runner.collect``, as :func:`.solvers._collect` does it: the accepted
    steps as output, every stride-th of them, the stride doubling (and every
    other kept) whenever they reach twice MAX_SOLVER_POINTS. cint: count,
    seen, stride; cflt: the last time."""
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


@njit(inline='always', **_OPTS)
def _clamp(nn, u):
    """``Integrator.clamp``: a non-negative state below zero put on zero; how many were."""
    hit = 0
    for i in range(nn.size):
        if nn[i] != 0 and u[i] < 0:
            u[i] = 0.0
            hit += 1
    return hit


@njit(inline='always', **_OPTS)
def _report(progress, pbuf, t, t0, span, nsteps):
    """The adapter's progress at t: 1 to go on, 0 when it says stop, -1 when it raised."""
    pbuf[0] = nsteps
    return progress(_jmin(1.0, abs(t - t0) / span), t)


# --- the loop (``integrator.solve``) --------------------------------------------------------------------------

FP_RTOL = 0
FP_T0 = 1
FP_TF = 2
FP_DTMAX = 3
FP_DT = 4              # the initial step asked for, or 0
FP_MAX_STEPS = 5
FP_MAX_AGE = 6         # max_jac_age
FP_KAPPA = 7           # the Newton iteration's
FP_CUTOFF = 8          # its fast_convergence_cutoff
FP_NONSTIFFTOL = 9     # a composite's switch (``SwitchState``): its thresholds,
FP_STIFFTOL = 10
FP_DTFAC = 11
FP_STABILITY = 12      # the non-stiff method's stability size,
FP_MAXSTIFFSTEP = 13   # and its counts
FP_MAXNONSTIFFSTEP = 14
FP_SWITCH_MAX = 15
NFP = 16
IP_METHOD = 0          # the method, or a composite's non-stiff one (slot 0)
IP_BELOW_TOL = 1       # below_tol_run, rounded
IP_STORE = 2           # the model's recorders keep the steps
IP_PROGRESS = 3
IP_SAVEAT_AT = 4       # the first time to save at
IP_ORDER = 5           # the order of the method it starts on, for the starting step
IP_AUTO_ABSTOL = 6
IP_NEWTON_MAX_ITERS = 7
IP_INITDT = 8          # OrdinaryDiffEq's starting step (``initdt='sciml'``), else Hairer's
IP_COMPOSITE = 9       # a composite of two methods
IP_STIFF = 10          # its stiff one (slot 1)
IP_FIRST = 11          # the slot it starts on
IP_HAND_OFF = 12       # the slots it hands off, as bits (1 << slot)
IP_STIFFALGFIRST = 13
IP_STILL = 14          # still_is_stiff: a state at rest read as Julia reads it
NIP = 15               # then the method's integers (fbi, qni or rai) as a step starts them
NCP = 2 * NPC          # cpar: the two slots' controllers, then the method's floats (fbv, qnv or rav)

# What the loop reports besides the counts: stats[NC + SO_...].
SO_ROWS = 0            # the rows written
SO_STEPS0 = 1          # the accepted steps of each slot
SO_STEPS1 = 2
SO_SWITCHES = 3
SO_SLOT = 4            # the slot in charge at the end
SO_BUILT = 5           # the slots that took charge at all, as bits
SO_W = 6               # whether W was ever formed
SO_KSOLVES = 7         # GMRES's solves and iterations
SO_KITERS = 8
SO_FROM = 9            # where it handed off: from this slot (-1, none) to that
SO_TO = 10
NSO = 11

JULIA_SIG = types.int64(
    RHS_T, STORE_T, RHS_T, CB_T, CB_T, CB_T, CB_T,   # f, store, evf, jac_cb, progress, factor_cb, solve_cb
    _A, _A, _A, _I, CB_T,                           # P, X, W, IW, pycb: the model's arrays and its callback
    _A, _A, _A, _A, _I,                             # saveat, y0, atol, atol0, nn
    _A, _A, _A, _I, _I,                             # coef, fpar, cpar, ipar, fl
    _M, _A, _I, _I, _I, _I, _I, _I, _A,              # jd, jv, gptr, gcols, eptr, erow, ewhich, eent, ybuf
    _M, _A, _I, _I, _A, _A,                         # wf, wv, j_to_w, diag_w, rbuf, xbuf
    _A, _M, _A, _I, _A,                             # evdir, evbuf, evy, evwhich, evstat
    _A, _M, _I, _A, _I,                             # tout, yout, stats, fstat, pbuf
    _A, _M, _I, _A,                                 # ct, cy, cint, cflt: the steps as output
    _A, _A, _I, _I, _A)                             # tstops, ecoef, eint, jrow, hand


@njit(inline='always', **_OPTS)
def _has_fsal_last(method):
    """Whether the step's last stage is f at its end: the ESDIRKs', Radau's,
    Tsit5's and Rosenbrock23's."""
    return method == M_ESDIRK or method == M_RADAU or method == M_TSIT5 or method == M_ROS23


@njit(**_OPTS)
def _explicit_tables(method, ecoef, eint):
    """The explicit method's tableau, out of ``ecoef`` and ``eint`` as
    :mod:`.julia_run` lays them out: Tsit5's a (7 x 7), c, btilde and
    interpolant (7 x 4); Vern7's terms (row pointers, stages, values), c, its
    interpolation stages' c, the interpolant's stages, polynomials' pointers
    and coefficients. A run without one has empty ones."""
    if method == M_TSIT5:
        ta = ecoef[0:49].reshape(7, 7)
        tc = ecoef[49:56]
        tbt = ecoef[56:63]
        ti = ecoef[63:91].reshape(7, 4)
    else:
        ta = np.zeros((1, 1))
        tc = np.zeros(1)
        tbt = np.zeros(1)
        ti = np.zeros((1, 1))
    if method == M_VERN7:
        nt = eint[0]
        nv = eint[1]
        ns = eint[2]
        vptr = eint[3:3 + 19]
        vj = eint[22:22 + nt]
        vst = eint[22 + nt:22 + nt + ns]
        vip = eint[22 + nt + ns:22 + nt + 2 * ns + 1]
        vv = ecoef[0:nt]
        vc = ecoef[nt:nt + 10]
        vc2 = ecoef[nt + 10:nt + 16]
        viv = ecoef[nt + 16:nt + 16 + nv]
    else:
        vptr = np.zeros(1, dtype=np.int64)
        vj = np.zeros(1, dtype=np.int64)
        vst = np.zeros(1, dtype=np.int64)
        vip = np.zeros(1, dtype=np.int64)
        vv = np.zeros(1)
        vc = np.zeros(1)
        vc2 = np.zeros(1)
        viv = np.zeros(1)
    return ta, tc, tbt, ti, vptr, vj, vv, vc, vc2, vst, vip, viv


@njit(JULIA_SIG, **_OPTS)
def julia(f, store, evf, jac_cb, progress, factor_cb, solve_cb, P, X, Wm, IW, pycb, saveat, y0, atol, atol0, nn,
          coef, fpar, cpar, ipar, fl, jd, jv, gptr, gcols, eptr, erow, ewhich, eent, ybuf, wf, wv, j_to_w, diag_w,
          rbuf, xbuf, evdir, evbuf, evy, evwhich, evstat, tout, yout, stats, fstat, pbuf, ct, cy, cint, cflt,
          tstops, ecoef, eint, jrow, hand):
    """``integrator.solve`` with the method ``ipar[IP_METHOD]`` -- or, for a
    composite, with the two of ``ipar[IP_METHOD]`` and ``ipar[IP_STIFF]`` and
    the switch between them -- compiled.

    fpar, ipar: see ``FP_`` and ``IP_``; cpar: the two slots' controllers'
    numbers (``PC_``), then the method's floats (fbv, qnv or rav) as a run
    starts them; coef: the stiff (or only) method's tableau or coefficients,
    ecoef and eint the explicit one's; fl: ``FL_``. ``atol`` is the
    integrator's own tolerance (raised in place under auto_abstol),
    ``atol0`` the one asked for, which the Newton iteration and the starting
    step read; ``nn`` marks the non-negative states (empty when none is). The
    Jacobian (``jd`` dense, ``jv`` on the pattern, whose rows are ``jrow``),
    the colouring that differences it, W by columns (``wf``) or its values
    (``wv``) and the callbacks' buffers are the Python solver's own objects'
    arrays. Rows are saved at ``saveat`` from ``ipar[IP_SAVEAT_AT]`` into
    tout/yout, steps land on ``tstops``, and the model's recorders are told
    of each row and each step (``store``), the steps collected when cint[3]
    is set; an event stops the solve, which says so in evstat (1, the time),
    with the state there in evy and the events that fired in evwhich; a
    hand-off stops it too, with the state there in ``hand``.
    stats (out): the ``C_`` counts, then the ``SO_`` numbers; fstat (out): t,
    dt and the component a message needs.
    """
    n = y0.size
    comp = ipar[IP_COMPOSITE] != 0
    mcode0 = ipar[IP_METHOD]
    mcode1 = ipar[IP_STIFF] if comp else mcode0
    slot = ipar[IP_FIRST] if comp else 0
    method = mcode1 if slot == 1 else mcode0
    rtol = fpar[FP_RTOL]
    t0 = fpar[FP_T0]
    tf = fpar[FP_TF]
    dtmax = fpar[FP_DTMAX]
    max_steps = fpar[FP_MAX_STEPS]
    below_tol_max = ipar[IP_BELOW_TOL]
    has_store = ipar[IP_STORE] != 0
    has_progress = ipar[IP_PROGRESS] != 0
    auto_abstol = ipar[IP_AUTO_ABSTOL] != 0
    norm_max = fl[FL_NORM_MAX] != 0
    has_nn = nn.size > 0
    nev = evdir.size
    model = (P, X, Wm, IW)
    ctr = np.zeros(NC, dtype=np.int64)
    diff = tf - t0
    tdir = 1.0 if diff > 0 else (-1.0 if diff < 0 else 1.0)
    span = abs(tf - t0)
    t_eps = 16 * _jmax(_ulp(t0), _ulp(tf))

    # --- what the methods share: J, W, the Newton iteration, the controllers
    jac = (jd, jv, gptr, gcols, eptr, erow, ewhich, eent, ybuf, np.zeros(n), np.zeros(n), np.zeros(max(gcols.size, 1)))
    ws = np.zeros(NWS)
    ws[WS_GAMMA_DT] = np.nan
    ws[WS_STALE] = 1.0
    ws[WS_MAX_AGE] = fpar[FP_MAX_AGE]
    lints = np.zeros(3, dtype=np.int32)
    lints[0] = n
    lints[2] = 1
    trans = np.zeros(1, dtype=np.uint8)
    trans[0] = 78  # 'N'
    mat = (ws, wf, np.zeros(n, dtype=np.int32), lints, trans, wv, j_to_w, diag_w, rbuf, xbuf)
    nwt = (np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n))
    ns = np.zeros(NNS)
    ns[NS_GAMMA] = 1.0
    ns[NS_ETA_OLD] = 1.0
    ns[NS_PREV_THETA] = 1.0
    ns[NS_ETA] = 1.0
    ns[NS_ERRC] = 1.0
    ns[NS_KAPPA] = fpar[FP_KAPPA]
    ns[NS_CUTOFF] = fpar[FP_CUTOFF]
    ni = np.zeros(NNI, dtype=np.int64)
    ni[NI_STATUS] = N_CONVERGENCE
    ni[NI_MAX_ITERS] = ipar[IP_NEWTON_MAX_ITERS]
    pcs = np.zeros((2, NPC))
    pcs[0, :] = cpar[:NPC]
    pcs[1, :] = cpar[NPC:NCP]
    pc = pcs[slot]

    # --- each method's own: full size for the ones that run
    use_ros = mcode0 == M_ROSENBROCK or mcode1 == M_ROSENBROCK
    m_ros = n if use_ros else 1
    s_ros = int(coef[0]) if use_ros else 1
    h_ros = int(coef[1]) if use_ros else 1
    ros = (np.zeros((s_ros, m_ros)), np.zeros((h_ros, m_ros)), np.zeros(1, dtype=np.int64), np.zeros(m_ros),
           np.zeros(m_ros), np.zeros(m_ros), np.zeros(m_ros))
    use_esd = mcode0 == M_ESDIRK
    m_esd = n if use_esd else 1
    ez = np.zeros((int(coef[0]) if use_esd else 1, m_esd))
    est = np.zeros(m_esd)
    use_fb = mcode0 == M_FBDF or mcode1 == M_FBDF
    m_fb = n if use_fb else 1
    fbv = np.zeros(NFB)
    fbi = np.zeros(NFI, dtype=np.int64)
    if use_fb:
        fbv[:] = cpar[NCP:NCP + NFB]
        fbi[:] = ipar[NIP:NIP + NFI]
    fb = (np.zeros((FB_K, m_fb)), np.arange(FB_K), np.zeros((FB_K, m_fb)), np.zeros(m_fb), np.zeros(FB_K),
          np.zeros(FB_K), np.zeros((FB_K + 1) * (FB_K + 2)), np.zeros(FB_K + 1), np.zeros(FB_K + 1), np.zeros(m_fb),
          np.zeros(m_fb), fbv, fbi)
    use_qn = mcode0 == M_QNDF
    m_qn = n if use_qn else 1
    qnv = np.zeros(NQN)
    qni = np.zeros(NQI, dtype=np.int64)
    qcoef = np.zeros(QN_S * QN_S)
    if use_qn:
        qnv[:] = cpar[NCP:NCP + NQN]
        qni[:] = ipar[NIP:NIP + NQI]
        qcoef[:] = coef[QN_GAMMAS + 6:QN_GAMMAS + 6 + QN_S * QN_S]
    qn = (np.zeros((QN_ROWS, m_qn)), np.zeros(m_qn), np.zeros((QN_S, m_qn)), np.zeros((QN_S + 1, m_qn)),
          np.zeros(QN_S * QN_S), np.zeros(QN_S * QN_S), qcoef, qnv, qni)
    use_ra = mcode0 == M_RADAU
    m_ra = n if use_ra else 1
    rav = np.zeros(NRA)
    rai = np.zeros(NRI, dtype=np.int64)
    if use_ra:
        rav[:] = cpar[NCP:NCP + NRA]
        rai[:] = ipar[NIP:NIP + NRI]
    ra = (np.zeros((3, m_ra)), np.zeros((3, m_ra)), np.zeros((3, m_ra)), np.zeros((3, m_ra)), np.zeros(m_ra),
          np.zeros(m_ra), np.zeros(m_ra), np.zeros((m_ra, m_ra), dtype=np.complex128),
          np.zeros(m_ra, dtype=np.int32), np.zeros(m_ra, dtype=np.complex128), rav, rai)
    use_ex = mcode0 == M_TSIT5 or mcode0 == M_VERN7
    m_ex = n if use_ex else 1
    ta, tc, tbt, ti, vptr, vj, vv, vc, vc2, vst, vip, viv = _explicit_tables(mcode0, ecoef, eint)
    ex = (np.zeros((16, m_ex)), np.zeros(m_ex), np.zeros(m_ex), np.zeros(1, dtype=np.int64), ta, tc, tbt, ti, vptr, vj,
          vv, vc, vc2, vst, vip, viv)
    use_23 = mcode0 == M_ROS23 or mcode1 == M_ROS23
    m_23 = n if use_23 else 1
    r23 = (np.zeros(m_23), np.zeros(m_23), np.zeros(m_23), np.zeros(m_23), np.zeros(m_23), np.zeros(m_23),
           np.zeros(m_23))
    use_kr = use_fb and fbi[FI_KRYLOV] != 0
    m_kr = n if use_kr else 1
    kwf = np.zeros(NKF)
    kwi = np.zeros(NKI, dtype=np.int64)
    if use_kr:
        # GMRES's basis: ``memory`` vectors to start with, up to 256 MB of them.
        kwi[KI_MEMORY] = min(20, n)
        kwi[KI_MAX_BASIS] = max(kwi[KI_MEMORY], (256 * 1024 * 1024) // (8 * max(1, n)))
    Vh = [np.zeros((max(1, kwi[KI_MEMORY]), m_kr))]
    kry = (kwf, kwi, np.zeros(m_kr), np.zeros(m_kr), Vh, np.zeros(m_kr), np.zeros(m_kr), np.zeros(m_kr),
           np.zeros(m_kr), np.zeros(m_kr), np.zeros(m_kr), np.zeros(m_kr), np.zeros(m_kr), np.zeros(m_kr))
    rowsum = np.zeros(n if comp else 1)

    # --- the composite's switch (``SwitchState``, ``CompositeCache``)
    nonstifftol = fpar[FP_NONSTIFFTOL]
    stifftol = fpar[FP_STIFFTOL]
    dtfac = fpar[FP_DTFAC]
    stability = fpar[FP_STABILITY]
    maxstiffstep = fpar[FP_MAXSTIFFSTEP]
    maxnonstiffstep = fpar[FP_MAXNONSTIFFSTEP]
    switch_max = fpar[FP_SWITCH_MAX]
    still = ipar[IP_STILL] != 0
    hand_mask = ipar[IP_HAND_OFF]
    as_count = 0
    as_succ = 0
    as_stiff = ipar[IP_STIFFALGFIRST] != 0
    built = 1 << slot if comp else 1
    steps0 = 0
    steps1 = 0
    nswitches = 0
    skip_next = False
    handed = False
    hand_from = -1
    hand_to = -1
    eigen_est = 1.0
    dec = True            # do_error_check
    naccept = 0
    w_formed = False

    uprev = y0.copy()
    u = y0.copy()
    fsalfirst = np.zeros(n)
    fsallast = np.zeros(n)
    utmp = np.zeros(n)
    ub = np.zeros(n)
    u_event = np.zeros(n)
    found = np.zeros((3, max(nev, 1)))
    rows = 0
    t = t0
    dt = 0.0
    eest = 1.0
    status = OK
    evstat[0] = 0.0
    ntstops = tstops.size
    tstop_at = 0

    # --- the start
    f(t0, uprev, fsalfirst, P, X, Wm, IW, pycb)
    ctr[C_NF] += 1
    bad = -1
    for i in range(n):
        if not math.isfinite(uprev[i]) or not math.isfinite(fsalfirst[i]):
            bad = i
            break
    if bad >= 0:
        fstat[2] = bad
        status = E_INITIAL
    else:
        if method == M_ESDIRK:
            ni[NI_METHOD] = N_DIRK
            ns[NS_GAMMA] = coef[1]
        elif method == M_FBDF:
            _fbdf_init(fb, ni, uprev)
        elif method == M_QNDF:
            ni[NI_METHOD] = N_MULTISTEP
        if fpar[FP_DT] != 0:
            dt = abs(fpar[FP_DT]) * tdir
        elif ipar[IP_INITDT] != 0:
            dt = _initial_step_sciml(f, model, pycb, ctr, t0, uprev, fsalfirst, tdir, ipar[IP_ORDER], rtol, atol0,
                                     _jmin(abs(dtmax), span), norm_max, utmp, ub, u_event, fsallast)
            for q in range(n):
                fsallast[q] = 0.0
        else:
            dt = _initial_step(f, model, pycb, ctr, t0, uprev, fsalfirst, tdir, ipar[IP_ORDER], rtol, atol0, dtmax,
                               utmp, ub)
        if not math.isfinite(dt) or dt == 0:
            dt = tdir * _jmin(1e-6 * span, dtmax)
        dt = tdir * _jmin(_jmin(abs(dt), abs(dtmax)), span)
    sa = ipar[IP_SAVEAT_AT]
    if status == OK:
        if sa < saveat.size and saveat[sa] == t0:
            tout[0] = t0
            for q in range(n):
                yout[0, q] = uprev[q]
            rows = 1
            sa += 1
        if nev:
            evf(t0, uprev, evbuf[0], P, X, Wm, IW, pycb)
    below_run = 0

    # --- the loop: choose the method, propose a step, judge it, save what it
    # passed, look for an event, choose the next
    while status == OK and tdir * (tf - t) > t_eps:
        if comp:
            # ``choose_algorithm!``: a verdict on the last attempt, after it
            # was judged and its successor's dt chosen (``CompositeCache.choose``).
            # No verdict on an FBDF attempt the error test turned down.
            if not handed:
                if skip_next:
                    skip_next = False
                else:
                    dt_was = dt
                    stiffness = abs(eigen_est * dt / stability)
                    tol = stifftol if as_stiff else nonstifftol
                    stiff = not (stiffness <= tol)
                    if not stiff:
                        as_succ += 1
                    else:
                        as_succ = 0
                    dec = (as_succ > switch_max or not stiff) or as_stiff
                    if stiff:
                        as_count = 1 if as_count < 0 else as_count + 1
                    else:
                        as_count = -1 if as_count > 0 else as_count - 1
                    nxt = 1 if as_stiff else 0
                    if not as_stiff and as_count > maxstiffstep:
                        dt = dt_was * dtfac
                        as_stiff = True
                        nxt = 1
                    elif as_stiff and as_count < -maxnonstiffstep:
                        dt = dt_was / dtfac
                        as_stiff = False
                        nxt = 0
                    if nxt != slot:
                        if hand_mask & (1 << nxt):
                            handed = True
                            hand_from = slot
                            hand_to = nxt
                        else:
                            # ``activate``: its controller in charge, and FBDF
                            # started as a method switched to starts.
                            fresh = (built & (1 << nxt)) == 0
                            built |= 1 << nxt
                            slot = nxt
                            method = mcode1 if slot == 1 else mcode0
                            pc = pcs[slot]
                            if method == M_FBDF:
                                if fresh:
                                    _fbdf_init(fb, ni, uprev)
                                    if t != t0:
                                        _fbdf_restart(fb, uprev)
                                else:
                                    _fbdf_restart(fb, uprev)
                            nswitches += 1
            if handed:
                status = R_HANDED_OFF
                break
        if ctr[C_NSTEPS] >= max_steps and dec:
            status = R_MAX_ITERS
            break
        limit = tf
        if tstop_at < ntstops and tdir * (tstops[tstop_at] - limit) < 0:
            limit = tstops[tstop_at]
        if tdir * (t + dt - limit) > 0:
            dt = limit - t
        elif tdir * (limit - (t + dt)) <= t_eps:
            dt = limit - t
        dtmin = _jmax(MIN_VALUE, 16 * _ulp(t))
        at_floor = abs(dt) <= dtmin
        if at_floor:
            dt = tdir * dtmin
        if t + dt == t:
            status = R_DT_FLOOR
            break

        njac_before = ctr[C_NJAC]
        if method == M_ROSENBROCK:
            st, e = _ros_step(f, model, pycb, jac_cb, jac, factor_cb, solve_cb, mat, fl, ctr, coef, ros, t, dt, uprev,
                              u, fsalfirst, atol, rtol)
            w_formed = True
        elif method == M_ESDIRK:
            st, e = _esdirk_step(f, model, pycb, jac_cb, jac, factor_cb, solve_cb, mat, fl, ctr, coef, ez, nwt, ns, ni,
                                 t, dt, uprev, u, fsalfirst, fsallast, atol, atol0, rtol, est, kry)
            w_formed = True
        elif method == M_FBDF:
            st, e = _fbdf_step(f, model, pycb, jac_cb, jac, factor_cb, solve_cb, mat, fl, ctr, coef, fb, nwt, ns, ni,
                               t, dt, uprev, u, fsalfirst, atol, atol0, rtol, kry)
            if not use_kr:
                w_formed = True
        elif method == M_QNDF:
            st, e = _qndf_step(f, model, pycb, jac_cb, jac, factor_cb, solve_cb, mat, fl, ctr, coef, qn, nwt, ns, ni,
                               t, dt, uprev, u, fsalfirst, atol, atol0, rtol, kry)
            w_formed = True
        elif method == M_TSIT5:
            st = 1
            e = _tsit5_step(f, model, pycb, ctr, ex, t, dt, uprev, u, fsalfirst, fsallast, atol, rtol, norm_max)
        elif method == M_VERN7:
            st = 1
            e = _vern7_step(f, model, pycb, ctr, ex, t, dt, uprev, u, fsalfirst, atol, rtol, norm_max)
        elif method == M_ROS23:
            st, e = _ros23_step(f, model, pycb, jac_cb, jac, factor_cb, solve_cb, mat, fl, ctr, r23, t, dt, uprev, u,
                                fsalfirst, fsallast, atol, rtol)
            w_formed = True
        else:
            st, e = _radau_step(f, model, pycb, jac_cb, jac, factor_cb, solve_cb, mat, fl, ctr, coef, ra, t, dt,
                                uprev, u, fsalfirst, fsallast, atol, nn, rtol)
            w_formed = True
        if st < 0:
            status = E_CALLBACK if st == -1 else E_ZERO_DIVISION
            break
        # The composite's estimate of the spectral radius: the explicit
        # method's from its last two stages, the stiff one's ||J||_inf
        # whenever it formed J (``Integrator.form_w``).
        if comp:
            if method == M_TSIT5:
                eigen_est = _explicit_stiffness(ex[0][5], ex[0][6], ex[1], u, still)
            elif method == M_VERN7:
                eigen_est = _explicit_stiffness(ex[0][8], ex[0][9], ex[1], u, still)
            elif ctr[C_NJAC] != njac_before:
                eigen_est = _jac_inf_norm(jac, fl, jrow, rowsum)
        ctr[C_NSTEPS] += 1

        if st == 0:
            ctr[C_NREJECT] += 1
            if has_progress:
                r = _report(progress, pbuf, t, t0, span, ctr[C_NSTEPS])
                if r <= 0:
                    status = R_STOPPED if r == 0 else E_CALLBACK
                    break
            # At the smallest step the clock can represent there is nowhere
            # left to go (unless a composite has waived the checks while it switches).
            if at_floor and dec:
                status = R_NOT_SOLVED
                break
            dt *= 0.5
            ws[WS_STALE] = 1.0
            pc[PC_ERROLD] = pc[PC_QOLDINIT]
            continue
        eest = e

        bad = -1
        for i in range(n):
            if not math.isfinite(u[i]):
                bad = i
                break
        if bad >= 0:
            ctr[C_NREJECT] += 1
            # The candidate is no state; the last accepted one is.
            for i in range(n):
                u[i] = uprev[i]
            dt *= 0.5
            ws[WS_STALE] = 1.0
            if abs(dt) < _jmax(MIN_VALUE, 16 * _ulp(t)):
                fstat[2] = bad
                status = R_UNSTABLE
                break
            continue

        # An error estimate that is not a number is a step that failed outright.
        if eest != eest:
            ctr[C_NREJECT] += 1
            for i in range(n):
                u[i] = uprev[i]
            if has_progress:
                r = _report(progress, pbuf, t, t0, span, ctr[C_NSTEPS])
                if r <= 0:
                    status = R_STOPPED if r == 0 else E_CALLBACK
                    break
            if at_floor:
                status = R_EEST_NAN
                break
            dt *= 0.5
            ws[WS_STALE] = 1.0
            pc[PC_ERROLD] = pc[PC_QOLDINIT]
            continue

        accepted = eest <= 1
        if not accepted and at_floor and dec:
            if below_run < below_tol_max:
                below_run += 1
                accepted = True
            else:
                status = R_ERROR_TEST
                break
        if accepted:
            below_run = 0
        if not accepted:
            ctr[C_NREJECT] += 1
            if method == M_FBDF:
                if comp:
                    skip_next = True
                dt = _fbdf_rejected(fb, eest, dt)
            elif method == M_QNDF:
                dt = _qndf_rejected(qn, eest, dt)
            else:
                dt = _pi_reject(pc, eest, dt)
            if has_progress:
                r = _report(progress, pbuf, t, t0, span, ctr[C_NSTEPS])
                if r <= 0:
                    status = R_STOPPED if r == 0 else E_CALLBACK
                    break
            continue

        # --- the step is good: the event functions and the saved rows are
        # read off its own interpolant, before an event cuts it short
        tnew = t + dt
        hit = False
        t_e = 0.0
        if nev:
            hit, t_e = _find_event(method, coef, ros, fb, qn, ra, ex, r23, f, ctr, evf, model, pycb, evdir, evbuf,
                                   evwhich, found, t, dt, t0, uprev, u, fsalfirst, fsallast, ub, u_event)
        naccept += 1
        clamped = _clamp(nn, u) if has_nn else 0
        t_end = t_e if hit else tnew
        while sa < saveat.size and tdir * (saveat[sa] - t_end) <= 0:
            ts = saveat[sa]
            if tdir * (ts - t) >= 0:
                theta = 1.0 if dt == 0 else (ts - t) / dt
                _eval_at(method, coef, ros, fb, qn, ra, ex, r23, f, model, pycb, ctr, theta, t, dt, uprev, u,
                         fsalfirst, fsallast, utmp)
                if has_nn:
                    _clamp(nn, utmp)
                tout[rows] = ts
                for q in range(n):
                    yout[rows, q] = utmp[q]
                rows += 1
                if has_store and store(ts, utmp, P, X, Wm, IW, pycb) != 0:
                    status = E_HISTORY
                    break
            sa += 1
        if status != OK:
            break
        if hit:
            dt = t_e - t
            for q in range(n):
                u[q] = u_event[q]
            if has_nn:
                _clamp(nn, u)
        ta_ = t + dt
        if has_store and store(ta_, u, P, X, Wm, IW, pycb) != 0:
            status = E_HISTORY
            break
        if cint[3]:
            _collect(ta_, u, ct, cy, cint, cflt)
        if auto_abstol:
            for i in range(n):
                want = rtol * abs(u[i])
                if want > atol[i]:
                    atol[i] = want

        dtjust = dt
        t += dt
        if abs(tf - t) <= t_eps:
            t = tf
        elif tstop_at < ntstops and abs(tstops[tstop_at] - t) <= 16 * _jmax(_ulp(t), MIN_VALUE):
            t = tstops[tstop_at]
        for q in range(n):
            uprev[q] = u[q]
        # f at the new point is the step's own last stage where the method has
        # one -- unless clamping moved the point off it, which Tsit5 and
        # Rosenbrock23 answer by evaluating f again.
        if _has_fsal_last(method) and not (clamped > 0 and (method == M_TSIT5 or method == M_ROS23)):
            for q in range(n):
                fsalfirst[q] = fsallast[q]
        else:
            f(t, uprev, fsalfirst, P, X, Wm, IW, pycb)
            ctr[C_NF] += 1
        # The Jacobian ages by the steps taken with it: an explicit method's do not count.
        if not (method == M_TSIT5 or method == M_VERN7):
            ws[WS_AGE] += 1
        dtp = 0.0
        if method == M_ROSENBROCK:
            ros[2][0] = 0
        elif method == M_FBDF:
            dtp = _fbdf_accepted(coef, fb, u, dtjust)
        elif method == M_QNDF:
            dtp = _qndf_accepted(qn, u, eest, dtjust)
        elif method == M_RADAU:
            _radau_accepted(coef, ra, dtjust)
        if comp:
            if slot == 0:
                steps0 += 1
            else:
                steps1 += 1
        if tstop_at < ntstops and tdir * (t - tstops[tstop_at]) >= 0:
            tstop_at += 1

        if nev:
            if hit:
                # The adapter makes every event terminal: the solve ends
                # here, the state taken afresh as the integrator takes it.
                for q in range(n):
                    evy[q] = u[q]
                evstat[0] = 1.0
                evstat[1] = t
                f(t, uprev, fsalfirst, P, X, Wm, IW, pycb)
                ctr[C_NF] += 1
                tout[rows] = t
                for q in range(n):
                    yout[rows, q] = u[q]
                rows += 1
                break
            evf(t, uprev, evbuf[0], P, X, Wm, IW, pycb)

        # --- the next step
        if method == M_FBDF or method == M_QNDF:
            dtnext = dtp
        else:
            dtnext = _pi_accept(pc, eest, dtjust, naccept == 1)
        if not math.isfinite(dtnext) or dtnext == 0:
            dtnext = dtjust
        dt = tdir * _jmin(abs(dtnext), abs(dtmax))
        if has_progress:
            r = _report(progress, pbuf, t, t0, span, ctr[C_NSTEPS])
            if r <= 0:
                status = R_STOPPED if r == 0 else E_CALLBACK
                break

    if status == R_HANDED_OFF:
        for q in range(n):
            hand[q] = uprev[q]
    for q in range(NC):
        stats[q] = ctr[q]
    stats[NC + SO_ROWS] = rows
    stats[NC + SO_STEPS0] = steps0
    stats[NC + SO_STEPS1] = steps1
    stats[NC + SO_SWITCHES] = nswitches
    stats[NC + SO_SLOT] = slot
    stats[NC + SO_BUILT] = built
    stats[NC + SO_W] = 1 if w_formed else 0
    stats[NC + SO_KSOLVES] = kwi[KI_NSOLVE]
    stats[NC + SO_KITERS] = kwi[KI_NITER]
    stats[NC + SO_FROM] = hand_from
    stats[NC + SO_TO] = hand_to
    fstat[0] = t
    fstat[1] = dt
    return status
