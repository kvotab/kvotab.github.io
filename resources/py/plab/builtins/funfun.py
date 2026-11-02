"""Numerical methods on SciPy: roots and minima, integrals, ordinary
differential equations, interpolation, polynomials, filters and Fourier
transforms.

Functions passed in (handles or names) are called synchronously from SciPy's
loops, so they cannot wait for input there.
"""
import math

import numpy as np

from . import bi
from ._util import (err, nargchk, noout, maxout, arr, darr, out, opt_str, sval, ival, num, is_str, bool_out,
                    like_class, first_dim, dim_arg, expand_dims, strip_flags)
from ..values import (MError, NOVAL, Char, Cell, Struct, Str, FH, Obj, F64, C128, class_of, shape_of, numel,
                      _2d, EMPTY, py_str, share, share_all)
from .. import runtime as R


def _fn(f, what='function'):
    """A callable from a handle or a name."""
    if isinstance(f, FH):
        return f
    if is_str(f):
        return R.NamedFH(py_str(f))
    raise err('MATLAB:invalidFunction', f'The {what} must be a function handle or a function name.')


def _call1(f, *args):
    return f.scall(1, *args)


def _scalar(v):
    a = arr(v)
    if a.size != 1:
        raise err('MATLAB:fzero:ValueNotScalar', 'The function must return a scalar value.' if True else '')
    x = a.reshape(-1)[0]
    return complex(x) if a.dtype.kind == 'c' else float(x)


# ---- options -----------------------------------------------------------------------------

def _struct_opts(v):
    if type(v) is Struct and v.size == 1:
        return {k: v.get1(k) for k in v.f}
    if isinstance(v, Obj) and hasattr(v, 'opts'):
        return dict(v.opts)
    return {}


def _opt(opts, name, default=None):
    for k, v in opts.items():
        if k.lower() == name.lower():
            if type(v) is np.ndarray and v.size == 0:
                return default
            return v
    return default


@bi('optimset')
def optimset(nargout, *args):
    s = Struct((1, 1))
    names = ['Display', 'MaxFunEvals', 'MaxIter', 'TolFun', 'TolX', 'FunValCheck', 'OutputFcn', 'PlotFcns']
    base = {}
    i = 0
    if args and type(args[0]) is Struct:
        base = _struct_opts(args[0])
        i = 1
        if len(args) > 1 and type(args[1]) is Struct:
            base.update(_struct_opts(args[1]))
            i = 2
    for n in names:
        base.setdefault(n, EMPTY())
    while i + 1 < len(args):
        k = py_str(args[i])
        match = next((n for n in base if n.lower() == k.lower()), k)
        base[match] = args[i + 1]
        i += 2
    return Struct.scalar(base)


@bi('optimget')
def optimget(nargout, *args):
    opts = _struct_opts(args[0])
    v = _opt(opts, py_str(args[1]))
    if v is None:
        return args[2] if len(args) > 2 else EMPTY()
    return v


@bi('optimoptions')
def optimoptions(nargout, *args):
    rest = list(args[1:]) if args and (is_str(args[0]) or isinstance(args[0], FH)) else list(args)
    return optimset(1, *rest)


@bi('odeset')
def odeset(nargout, *args):
    base = {}
    i = 0
    if args and type(args[0]) is Struct:
        base = _struct_opts(args[0])
        i = 1
    for n in ('RelTol', 'AbsTol', 'MaxStep', 'InitialStep', 'Events', 'OutputFcn', 'OutputSel', 'Mass', 'MStateDependence', 'MassSingular', 'Jacobian', 'NonNegative', 'Refine',
              'Stats', 'Vectorized', 'MaxOrder', 'BDF', 'NormControl'):
        base.setdefault(n, EMPTY())
    while i + 1 < len(args):
        k = py_str(args[i])
        match = next((n for n in base if n.lower() == k.lower()), k)
        base[match] = args[i + 1]
        i += 2
    return Struct.scalar(base)


@bi('odeget')
def odeget(nargout, *args):
    opts = _struct_opts(args[0])
    v = _opt(opts, py_str(args[1]))
    if v is None:
        return args[2] if len(args) > 2 else EMPTY()
    return v


def _display(opts, fn):
    d = _opt(opts, 'Display')
    return py_str(d).lower() if d is not None and is_str(d) else 'notify'


# ---- roots and minima ----------------------------------------------------------------------

@bi('fzero', nout=4)
def fzero(nargout, *args):
    nargchk(args, 2, 3, 'fzero')
    from scipy import optimize
    f = _fn(args[0])
    x0 = darr(args[1]).reshape(-1)
    opts = _struct_opts(args[2]) if len(args) > 2 else {}
    tolx = _opt(opts, 'TolX')
    tolx = num(tolx) if tolx is not None else np.finfo(float).eps
    g = lambda x: _scalar(_call1(f, float(x)))
    nf = [0]

    def gg(x):
        nf[0] += 1
        v = g(x)
        if isinstance(v, complex) or not math.isfinite(v):
            raise err('MATLAB:fzero:ValueCheckFailed' if True else '', f'FZERO cannot continue because the function returned a non-finite or complex value at x = {x:g}.', 'fzero')
        return v
    if x0.size == 2:
        a, b = float(x0[0]), float(x0[1])
        fa, fb = gg(a), gg(b)
        if fa == 0:
            return _fz_out(nargout, a, 0.0, 1.0, nf[0])
        if fb == 0:
            return _fz_out(nargout, b, 0.0, 1.0, nf[0])
        if np.sign(fa) == np.sign(fb):
            raise err('MATLAB:fzero:ValuesAtEndPtsSameSign', 'The function values at the interval endpoints must differ in sign.', 'fzero')
    else:
        x = float(x0[0])
        fx = gg(x)
        if fx == 0:
            return _fz_out(nargout, x, 0.0, 1.0, nf[0])
        # search outward for a sign change, as the language's fzero does
        dx = abs(x) / 50 if x != 0 else 1 / 50
        a = b = x
        fa = fb = fx
        found = False
        for _ in range(200):
            dx *= math.sqrt(2)
            a = x - dx
            fa = gg(a)
            if np.sign(fa) != np.sign(fx):
                b, fb = x, fx
                found = True
                break
            b = x + dx
            fb = gg(b)
            if np.sign(fb) != np.sign(fx):
                a, fa = x, fx
                found = True
                break
        if not found:
            R.write('Exiting fzero: aborting search for an interval containing a sign change\n    because NaN or Inf function value encountered during search.\n' if False else '')
            raise err('MATLAB:fzero:NoSignChange', 'FZERO could not find an interval containing a sign change around the starting point.' if True else '', 'fzero')
    r = optimize.brentq(gg, min(a, b), max(a, b), xtol=max(tolx, 4 * np.finfo(float).eps * 0), rtol=4 * np.finfo(float).eps, maxiter=500, full_output=False)
    return _fz_out(nargout, float(r), g(r), 1.0, nf[0])


def _fz_out(nargout, x, fx, flag, nf):
    if nargout <= 1:
        return x
    outp = Struct.scalar({'intervaliterations': 0.0, 'iterations': float(nf), 'funcCount': float(nf),
                          'algorithm': Char.of('bisection, interpolation'), 'message': Char.of('Zero found in the interval.')})
    return (x, fx, flag, outp)[:nargout]


@bi('fminbnd', nout=4)
def fminbnd(nargout, *args):
    nargchk(args, 3, 4, 'fminbnd')
    from scipy import optimize
    f = _fn(args[0])
    a, b = num(args[1]), num(args[2])
    opts = _struct_opts(args[3]) if len(args) > 3 else {}
    tolx = _opt(opts, 'TolX')
    xatol = num(tolx) if tolx is not None else 1e-4
    res = optimize.minimize_scalar(lambda x: _scalar(_call1(f, float(x))), bounds=(a, b), method='bounded', options={'xatol': xatol})
    x = float(res.x)
    if nargout <= 1:
        return x
    outp = Struct.scalar({'iterations': float(res.nit), 'funcCount': float(res.nfev), 'algorithm': Char.of('golden section search, parabolic interpolation'), 'message': Char.of('Optimization terminated.')})
    return (x, float(res.fun), 1.0 if res.success else 0.0, outp)[:nargout]


@bi('fminsearch', nout=4)
def fminsearch(nargout, *args):
    nargchk(args, 2, None, 'fminsearch')
    from scipy import optimize
    f = _fn(args[0])
    x0 = darr(args[1])
    shape = x0.shape
    opts = _struct_opts(args[2]) if len(args) > 2 else {}
    extra = args[3:]
    tolx = _opt(opts, 'TolX')
    tolf = _opt(opts, 'TolFun')
    maxiter = _opt(opts, 'MaxIter')
    maxfev = _opt(opts, 'MaxFunEvals')
    n = x0.size
    o = {'xatol': num(tolx) if tolx is not None else 1e-4, 'fatol': num(tolf) if tolf is not None else 1e-4,
         'maxiter': int(num(maxiter)) if maxiter is not None and not is_str(maxiter) else 200 * n,
         'maxfev': int(num(maxfev)) if maxfev is not None and not is_str(maxfev) else 200 * n}
    # the initial simplex: 5% steps (0.00025 for zero components)
    sim = [x0.reshape(-1).astype(F64)]
    for i in range(n):
        y = x0.reshape(-1).astype(F64).copy()
        y[i] = y[i] * 1.05 if y[i] != 0 else 0.00025
        sim.append(y)
    o['initial_simplex'] = np.array(sim)
    fun = lambda x: _scalar(_call1(f, out(x.reshape(shape)), *extra))
    res = optimize.minimize(fun, x0.reshape(-1), method='Nelder-Mead', options=o)
    x = out(res.x.reshape(shape))
    if nargout <= 1:
        return x
    outp = Struct.scalar({'iterations': float(res.nit), 'funcCount': float(res.nfev), 'algorithm': Char.of('Nelder-Mead simplex direct search'), 'message': Char.of(str(res.message))})
    return (x, float(res.fun), 1.0 if res.success else 0.0, outp)[:nargout]


@bi('fminunc', nout=6)
def fminunc(nargout, *args):
    from scipy import optimize
    f = _fn(args[0])
    x0 = darr(args[1])
    shape = x0.shape
    fun = lambda x: _scalar(_call1(f, out(x.reshape(shape))))
    res = optimize.minimize(fun, x0.reshape(-1), method='BFGS')
    x = out(res.x.reshape(shape))
    if nargout <= 1:
        return x
    outp = Struct.scalar({'iterations': float(res.nit), 'funcCount': float(res.nfev), 'message': Char.of(str(res.message))})
    return (x, float(res.fun), 1.0 if res.success else 0.0, outp, out(res.jac.reshape(shape)), out(getattr(res, 'hess_inv', np.eye(x0.size))))[:nargout]


@bi('fmincon', nout=4)
def fmincon(nargout, *args):
    from scipy import optimize
    f = _fn(args[0])
    x0 = darr(args[1])
    shape = x0.shape
    n = x0.size
    A = darr(args[2]) if len(args) > 2 and numel(args[2]) else None
    b = darr(args[3]).reshape(-1) if len(args) > 3 and numel(args[3]) else None
    Aeq = darr(args[4]) if len(args) > 4 and numel(args[4]) else None
    beq = darr(args[5]).reshape(-1) if len(args) > 5 and numel(args[5]) else None
    lb = darr(args[6]).reshape(-1) if len(args) > 6 and numel(args[6]) else None
    ub = darr(args[7]).reshape(-1) if len(args) > 7 and numel(args[7]) else None
    nonlcon = args[8] if len(args) > 8 and isinstance(args[8], FH) else None
    cons = []
    if A is not None:
        cons.append({'type': 'ineq', 'fun': lambda x: b - A @ x})
    if Aeq is not None:
        cons.append({'type': 'eq', 'fun': lambda x: Aeq @ x - beq})
    if nonlcon is not None:
        def cin(x):
            c, ceq = nonlcon.scall(2, out(x.reshape(shape)))
            return -darr(c).reshape(-1) if numel(c) else np.zeros(0)

        def ceq(x):
            c, ce = nonlcon.scall(2, out(x.reshape(shape)))
            return darr(ce).reshape(-1) if numel(ce) else np.zeros(0)
        cons.append({'type': 'ineq', 'fun': cin})
        cons.append({'type': 'eq', 'fun': ceq})
    bounds = None
    if lb is not None or ub is not None:
        lo = lb if lb is not None else np.full(n, -np.inf)
        hi = ub if ub is not None else np.full(n, np.inf)
        bounds = list(zip(lo, hi))
    fun = lambda x: _scalar(_call1(f, out(x.reshape(shape))))
    res = optimize.minimize(fun, x0.reshape(-1), method='SLSQP', bounds=bounds, constraints=[c for c in cons if c])
    x = out(res.x.reshape(shape))
    if nargout <= 1:
        return x
    outp = Struct.scalar({'iterations': float(res.nit), 'funcCount': float(res.nfev), 'message': Char.of(str(res.message))})
    return (x, float(res.fun), 1.0 if res.success else 0.0, outp)[:nargout]


@bi('fsolve', nout=4)
def fsolve(nargout, *args):
    from scipy import optimize
    f = _fn(args[0])
    x0 = darr(args[1])
    shape = x0.shape
    fun = lambda x: darr(_call1(f, out(x.reshape(shape)))).reshape(-1)
    res = optimize.root(fun, x0.reshape(-1), method='hybr')
    x = out(res.x.reshape(shape))
    if nargout <= 1:
        return x
    return (x, out(np.asarray(res.fun).reshape(darr(_call1(f, x)).shape)), 1.0 if res.success else 0.0,
            Struct.scalar({'message': Char.of(str(res.message)), 'funcCount': float(res.nfev)}))[:nargout]


@bi('lsqcurvefit', nout=4)
def lsqcurvefit(nargout, *args):
    from scipy import optimize
    f = _fn(args[0])
    x0 = darr(args[1])
    xdata = args[2]
    ydata = darr(args[3]).reshape(-1)
    lb = darr(args[4]).reshape(-1) if len(args) > 4 and numel(args[4]) else -np.inf
    ub = darr(args[5]).reshape(-1) if len(args) > 5 and numel(args[5]) else np.inf
    shape = x0.shape
    fun = lambda p: darr(_call1(f, out(p.reshape(shape)), xdata)).reshape(-1) - ydata
    res = optimize.least_squares(fun, x0.reshape(-1), bounds=(lb, ub))
    x = out(res.x.reshape(shape))
    if nargout <= 1:
        return x
    return (x, float(np.sum(res.fun ** 2)), out(res.fun.reshape(-1, 1)), 1.0 if res.success else 0.0)[:nargout]


@bi('lsqnonlin', nout=3)
def lsqnonlin(nargout, *args):
    from scipy import optimize
    f = _fn(args[0])
    x0 = darr(args[1])
    lb = darr(args[2]).reshape(-1) if len(args) > 2 and numel(args[2]) else -np.inf
    ub = darr(args[3]).reshape(-1) if len(args) > 3 and numel(args[3]) else np.inf
    shape = x0.shape
    fun = lambda p: darr(_call1(f, out(p.reshape(shape)))).reshape(-1)
    res = optimize.least_squares(fun, x0.reshape(-1), bounds=(lb, ub))
    x = out(res.x.reshape(shape))
    if nargout <= 1:
        return x
    return (x, float(np.sum(res.fun ** 2)), out(res.fun.reshape(-1, 1)))[:nargout]


@bi('linprog', nout=4)
def linprog(nargout, *args):
    from scipy import optimize
    c = darr(args[0]).reshape(-1)
    A = darr(args[1]) if len(args) > 1 and numel(args[1]) else None
    b = darr(args[2]).reshape(-1) if len(args) > 2 and numel(args[2]) else None
    Aeq = darr(args[3]) if len(args) > 3 and numel(args[3]) else None
    beq = darr(args[4]).reshape(-1) if len(args) > 4 and numel(args[4]) else None
    lb = darr(args[5]).reshape(-1) if len(args) > 5 and numel(args[5]) else None
    ub = darr(args[6]).reshape(-1) if len(args) > 6 and numel(args[6]) else None
    n = c.size
    bounds = list(zip(lb if lb is not None else [None] * n, ub if ub is not None else [None] * n))
    res = optimize.linprog(c, A_ub=A, b_ub=b, A_eq=Aeq, b_eq=beq, bounds=bounds, method='highs')
    if res.x is None:
        return (EMPTY(), EMPTY(), -2.0, Struct.scalar({'message': Char.of(res.message)}))[:max(nargout, 1)] if nargout > 1 else EMPTY()
    x = out(res.x.reshape(-1, 1))
    if nargout <= 1:
        return x
    return (x, float(res.fun), 1.0 if res.success else 0.0, Struct.scalar({'message': Char.of(res.message)}))[:nargout]


# ---- integrals ------------------------------------------------------------------------------

def _vec_or_scalar_call(f, x):
    """f at a vector of points (the language's integral calls with
    vectors), falling back to one point at a time."""
    try:
        r = darr(_call1(f, out(np.asarray(x).reshape(1, -1))))
        if r.size == np.size(x):
            return r.reshape(-1)
    except MError:
        pass
    return np.array([_scalar(_call1(f, float(t))) for t in np.asarray(x).reshape(-1)])


@bi('integral')
def integral(nargout, *args):
    nargchk(args, 3, None, 'integral')
    from scipy import integrate
    f = _fn(args[0])
    a, b = num(args[1]), num(args[2])
    opts = {}
    i = 3
    arrayvalued = False
    while i + 1 < len(args):
        k = py_str(args[i]).lower()
        opts[k] = args[i + 1]
        i += 2
    rtol = num(opts['reltol']) if 'reltol' in opts else 1e-6
    atol = num(opts['abstol']) if 'abstol' in opts else 1e-10
    if 'arrayvalued' in opts:
        arrayvalued = bool(arr(opts['arrayvalued']).reshape(-1)[0])
    if arrayvalued:
        v0 = darr(_call1(f, a))
        shape = v0.shape
        r, e = integrate.quad_vec(lambda t: darr(_call1(f, float(t))).reshape(-1), a, b, epsabs=atol, epsrel=rtol)
        return out(np.asarray(r).reshape(shape))
    cplx = [False]

    def g(t):
        v = _call1(f, float(t))
        x = _scalar(v)
        if isinstance(x, complex):
            cplx[0] = True
            return x
        return x
    waypoints = opts.get('waypoints')
    pts = list(darr(waypoints).reshape(-1)) if waypoints is not None else None
    try:
        if math.isinf(a) or math.isinf(b):
            r, e = integrate.quad(lambda t: _realpart(g(t)), a, b, epsabs=atol, epsrel=rtol, limit=650)
        else:
            r, e = integrate.quad(lambda t: _realpart(g(t)), a, b, epsabs=atol, epsrel=rtol, limit=650, points=pts)
        if cplx[0]:
            ri, ei = integrate.quad(lambda t: complex(g(t)).imag, a, b, epsabs=atol, epsrel=rtol, limit=650)
            return complex(r, ri) if ri != 0 else r
    except integrate.IntegrationWarning as w:
        R.warn('MATLAB:integral:MaxIntervalCountReached', str(w))
    return float(r)


def _realpart(x):
    return x.real if isinstance(x, complex) else x


@bi('quad', 'quadl', 'quadgk', nout=2)
def quad(nargout, *args):
    from scipy import integrate
    f = _fn(args[0])
    a, b = num(args[1]), num(args[2])
    tol = num(args[3]) if len(args) > 3 and numel(args[3]) and not is_str(args[3]) else 1e-6
    r, e = integrate.quad(lambda t: _realpart(_scalar(_call1(f, float(t)))), a, b, epsabs=tol, epsrel=1e-6 if tol >= 1e-6 else tol, limit=650)
    if nargout >= 2:
        return float(r), float(e)
    return float(r)


@bi('integral2', 'quad2d', 'dblquad')
def integral2(nargout, *args):
    from scipy import integrate
    f = _fn(args[0])
    xa, xb = num(args[1]), num(args[2])
    ya, yb = args[3], args[4]
    ylo = (lambda x: _scalar(_call1(ya, float(x)))) if isinstance(ya, FH) else (lambda x, v=num(ya): v)
    yhi = (lambda x: _scalar(_call1(yb, float(x)))) if isinstance(yb, FH) else (lambda x, v=num(yb): v)
    r, e = integrate.dblquad(lambda y, x: _realpart(_scalar(_call1(f, float(x), float(y)))), xa, xb, ylo, yhi, epsabs=1e-10, epsrel=1e-6)
    return float(r)


@bi('integral3', 'triplequad')
def integral3(nargout, *args):
    from scipy import integrate
    f = _fn(args[0])
    lims = [num(a) if not isinstance(a, FH) else a for a in args[1:7]]
    def lim(v):
        return v if not isinstance(v, FH) else v
    r, e = integrate.tplquad(lambda z, y, x: _realpart(_scalar(_call1(f, float(x), float(y), float(z)))),
                             lims[0], lims[1], lims[2], lims[3], lims[4], lims[5])
    return float(r)


# ---- ordinary differential equations -------------------------------------------------------------

_ODE_METHOD = {'ode45': 'RK45', 'ode23': 'RK23', 'ode113': 'Adams', 'ode78': 'Verner78', 'ode89': 'Verner89',
               'ode15s': 'NDF', 'ode23s': 'Rosenbrock23', 'ode23t': 'Trapezoid', 'ode23tb': 'TRBDF2'}
_REFINE = {'ode45': 4, 'ode78': 8, 'ode89': 4}
_EXPLICIT = ('ode45', 'ode23', 'ode113', 'ode78', 'ode89')


def _onoff(v):
    from ..ops import truth
    return py_str(v).lower() == 'on' if is_str(v) else bool(truth(v))


async def _ode(name, nargout, args, label=None, implicit=None):
    """The solvers' common part. implicit is (F, yp0, jacobian) for ode15i,
    which solves F(t, y, y') = 0 (args[0] is then F)."""
    nargchk(args, 3, None, name)
    from scipy.integrate import solve_ivp
    from .. import odesolvers as S
    who = label or name
    f = args[0] if implicit else _fn(args[0])
    tspan = darr(args[1]).reshape(-1).real
    y0 = darr(args[2])
    yshape = y0.shape
    y0v = y0.reshape(-1)
    n = y0v.size
    opts = _struct_opts(args[3]) if len(args) > 3 else {}
    extra = args[4:]
    if tspan.size < 2:
        raise err('MATLAB:odearguments:TspanNotVector', 'The timespan must have at least two elements.', who)
    rtol = _opt(opts, 'RelTol')
    atol = _opt(opts, 'AbsTol')
    maxstep = _opt(opts, 'MaxStep')
    first = _opt(opts, 'InitialStep')
    refine = _opt(opts, 'Refine')
    events_fn = _opt(opts, 'Events')
    mass = _opt(opts, 'Mass')
    nonneg = _opt(opts, 'NonNegative')
    jac = _opt(opts, 'Jacobian')
    kw = {'rtol': num(rtol) if rtol is not None else 1e-3,
          'atol': darr(atol).reshape(-1) if atol is not None and numel(atol) > 1 else (num(atol) if atol is not None else 1e-6)}
    # the default largest step is a tenth of the time span
    kw['max_step'] = num(maxstep) if maxstep is not None else 0.1 * abs(float(tspan[-1] - tspan[0]))
    if first is not None:
        kw['first_step'] = num(first)
    method = 'NDF' if implicit else _ODE_METHOD[name]
    nn_idx = [int(i) - 1 for i in darr(nonneg).reshape(-1)] if nonneg is not None else []
    # a real y0 whose derivative is complex (y' = 1i*y from 1): the solution is complex
    cplx = np.iscomplexobj(y0v) or (not implicit and darr(f.scall(1, float(tspan[0]), out(y0v.reshape(-1, 1)), *extra)).dtype.kind == 'c')
    if cplx:
        y0v = y0v.astype(C128)

    def col(y):
        return out(np.asarray(y).reshape(-1, 1))

    def f_raw(t, y):
        yy = y.reshape(yshape) if len(yshape) == 2 and yshape[1] == 1 else y.reshape(-1, 1)
        if nn_idx:
            yy = yy.copy()
            yy.reshape(-1)[nn_idx] = np.maximum(yy.reshape(-1)[nn_idx], 0)
        r = darr(f.scall(1, float(t), out(yy.reshape(-1, 1)), *extra)).reshape(-1)
        if r.size != y.size:
            raise err('MATLAB:odearguments:SizeIC', f'{f.text() if hasattr(f, "text") else "The function"} returns a vector of length {r.size}, but the length of initial conditions vector is {y.size}. The vector returned by the function and the initial conditions vector must have the same number of elements.', who)
        if nn_idx:
            for i in nn_idx:
                if y[i] <= 0 and r[i] < 0:
                    r[i] = 0
        return r.astype(C128 if cplx else F64) if (cplx or r.dtype.kind == 'c') else r

    rhs = f_raw
    # the mass matrix: a matrix, or a function of t (MStateDependence 'none', or one input) or of t and y
    if mass is not None:
        if isinstance(mass, FH):
            dep = py_str(_opt(opts, 'MStateDependence', Char.of('weak'))).lower()
            of_t = dep == 'none' or (isinstance(mass, R.Anon) and mass.nparams == 1 and not mass.vararg)

            def M_of(t, y):
                M = darr(mass.scall(1, float(t), *extra) if of_t else mass.scall(1, float(t), col(y), *extra))
                if M.shape != (n, n):
                    raise err('MATLAB:odearguments:MassSize', f'The mass matrix must be {n}-by-{n}.', who)
                return M
            M0 = M_of(float(tspan[0]), y0v)
            mass_opt = M_of
        else:
            M0 = darr(mass)
            if M0.shape != (n, n):
                raise err('MATLAB:odearguments:MassSize', f'The mass matrix must be {n}-by-{n}.', who)
            mass_opt = M0
        ms = py_str(_opt(opts, 'MassSingular', Char.of('maybe'))).lower()
        singular = ms == 'yes' or (ms == 'maybe' and S.null_spaces(M0)[0] is not None)
        if singular and name not in ('ode15s', 'ode23t'):
            raise err('MATLAB:odearguments:MassSingular',
                      f'The mass matrix is singular: {who} cannot solve a differential-algebraic system; ode15s and ode23t can.', who)
        if name == 'ode23s' and isinstance(mass, FH):
            raise err('MATLAB:ode23s:MassMatrixNotConstant', 'ode23s takes a constant mass matrix only.', who)
        if name in _EXPLICIT:
            if isinstance(mass, FH):
                rhs = lambda t, y: np.linalg.solve(M_of(t, y), f_raw(t, y))     # noqa: E731
            else:
                from scipy.linalg import lu_factor, lu_solve
                Mlu = lu_factor(M0)
                rhs = lambda t, y: lu_solve(Mlu, f_raw(t, y))     # noqa: E731
        else:
            kw['mass'] = mass_opt
    # the Jacobian, for the solvers that use one
    if jac is not None and name not in _EXPLICIT and not implicit:
        if isinstance(jac, FH):
            kw['jac'] = lambda t, y: darr(jac.scall(1, float(t), col(y), *extra))
        else:
            kw['jac'] = darr(jac)
    if name == 'ode15s' or implicit:
        mo = _opt(opts, 'MaxOrder')
        if mo is not None:
            k = num(mo)
            if k not in (1, 2, 3, 4, 5):
                raise err('MATLAB:odeget:MaxOrder', 'MaxOrder must be 1, 2, 3, 4 or 5.', who)
            kw['max_order'] = int(k)
        bdf = _opt(opts, 'BDF')
        kw['bdf'] = bool(implicit) or (bdf is not None and _onoff(bdf))
    if implicit:
        kw['residual'], kw['yp0'], kw['jac'] = implicit
        rhs = lambda t, y: np.zeros_like(y)     # noqa: E731  (ode15i has no f(t, y))
    ev_list = []
    if events_fn is not None and isinstance(events_fn, FH):
        v0, term0, dir0 = events_fn.scall(3, float(tspan[0]), out(y0v.reshape(-1, 1)), *extra)
        nev = numel(v0)
        term0 = darr(term0).reshape(-1)
        dir0 = darr(dir0).reshape(-1)
        for k in range(nev):
            def ev(t, y, k=k):
                v = events_fn.scall(3, float(t), out(y.reshape(-1, 1)), *extra)[0]
                return float(darr(v).reshape(-1)[k])
            ev.terminal = bool(term0[k]) if term0.size > k else False
            ev.direction = float(dir0[k]) if dir0.size > k else 0.0
            ev_list.append(ev)
    t_eval = tspan if tspan.size > 2 else None
    rf = int(num(refine)) if refine is not None else _REFINE.get(name, 1)
    solver = method if method in ('RK45', 'RK23') else getattr(S, method)
    try:
        sol = solve_ivp(rhs, (float(tspan[0]), float(tspan[-1])), y0v, method=solver, t_eval=t_eval,
                        dense_output=nargout == 1 or (tspan.size == 2 and rf > 1), events=ev_list or None, **kw)
    except S.SolverError as e:
        raise err(f'MATLAB:{who}:Solver', str(e), who) from None
    if sol.status == -1:
        R.warn(f'MATLAB:{who}:IntegrationTolNotMet', f'Failure at t={sol.t[-1]:e}.  Unable to meet integration tolerances without reducing the step size below the smallest value allowed at time t.')
    if tspan.size == 2:
        ts = sol.t
        if rf > 1 and ts.size > 1 and sol.sol is not None:
            pts = [ts[0]]
            for i in range(ts.size - 1):
                for k in range(1, rf):
                    pts.append(ts[i] + (ts[i + 1] - ts[i]) * k / rf)
                pts.append(ts[i + 1])
            T = np.array(pts)
            Y = sol.sol(T).T
        else:
            T = ts
            Y = sol.y.T
    else:
        T = sol.t
        Y = sol.y.T
    # an output function (odeplot when nothing is asked for), as the solver goes
    outfcn = _opt(opts, 'OutputFcn')
    if outfcn is None and nargout == 0:
        outfcn = R.NamedFH('odeplot')
    if outfcn is not None:
        T, Y = await _outputs(_fn(outfcn, 'output function'), _opt(opts, 'OutputSel'), tspan, y0v, T, Y, sol.t, extra)
    if nargout == 0:
        return None
    if nargout == 1:
        s = Struct.scalar({'solver': Char.of(who), 'extdata': Struct.scalar({'odefun': f, 'options': Struct.scalar(opts), 'varargin': Cell.of_list(list(extra))}),
                           'x': out(sol.t.reshape(1, -1)), 'y': out(sol.y),
                           'stats': Struct.scalar({'nsteps': float(sol.t.size - 1), 'nfevals': float(sol.nfev),
                                                   'npds': float(sol.njev), 'ndecomps': float(sol.nlu)}),
                           'idata': _DenseHolder(sol.sol)})
        if ev_list:
            te = np.concatenate([np.asarray(x) for x in sol.t_events]) if sol.t_events else np.zeros(0)
            s.f['xe'] = np.empty((1, 1), object)
            s.f['xe'][0, 0] = out(te.reshape(1, -1))
        return s
    res = [out(T.reshape(-1, 1)), out(Y)]
    if nargout >= 3:
        te, ye, ie = [], [], []
        for k, (tk, yk) in enumerate(zip(sol.t_events or [], sol.y_events or [])):
            for t_, y_ in zip(tk, yk):
                te.append(t_)
                ye.append(y_)
                ie.append(k + 1)
        order = np.argsort(te, kind='stable') if te else []
        te = np.array(te)[order] if te else np.zeros(0)
        ye = np.array(ye)[order] if ye else np.zeros((0, y0v.size))
        ie = np.array(ie, F64)[order] if ie else np.zeros(0)
        res += [out(te.reshape(-1, 1)), out(ye.reshape(-1, y0v.size)), out(ie.reshape(-1, 1))]
    return tuple(res[:nargout])


class _DenseHolder(Obj):
    """A solution's interpolant, kept in sol.idata for deval."""
    __slots__ = ('fn',)
    cls = 'struct'
    shape = (1, 1)

    def __init__(self, fn):
        self.fn = fn

    def display_lines(self):
        return ['  [interpolation data]']


for _n in _ODE_METHOD:
    def _mk(n):
        async def f(nargout, *args):
            return await _ode(n, nargout, args)
        f.__name__ = n
        return f
    bi(_n, nout=5, aw=True, arr=False)(_mk(_n))


async def _outputs(fn, sel, tspan, y0, T, Y, steps, extra):
    """The output function called as the solvers call it: 'init' with the
    time span and the start, then after each step with its times (a row)
    and states (a column each, those OutputSel names), then 'done'. A true
    answer stops the solution there."""
    from ..ops import truth
    idx = [int(i) - 1 for i in darr(sel).reshape(-1)] if sel is not None and numel(sel) else list(range(Y.shape[1]))
    await fn.acall(0, out(tspan.reshape(1, -1)), out(y0[idx].reshape(-1, 1)), Char.of('init'), *extra)
    start = 1
    for end in np.searchsorted(T, steps[1:], side='right'):
        if end <= start:
            continue
        status = await fn.acall(1, out(T[start:end].reshape(1, -1)), out(Y[start:end][:, idx].T), Char.of(''), *extra)
        start = end
        if status is not None and truth(status):
            T, Y = T[:end], Y[:end]
            break
    await fn.acall(0, EMPTY(), EMPTY(), Char.of('done'), *extra)
    return T, Y


_ODEPLOT = {}


@bi('odeplot', arr=False)
def odeplot(nargout, *args):
    """The output function that plots each component against time as the
    solver goes; the solvers use it when no output is asked for."""
    from .graphics import newplot
    from ..graphics_base import Line
    flag = py_str(args[2]).lower() if len(args) > 2 and is_str(args[2]) else ''
    if flag == 'init':
        t = darr(args[0]).reshape(-1)
        y = darr(args[1]).reshape(-1)
        ax = newplot(None)
        lines = []
        for v in y:
            h = Line(ax)
            h.props['XData'] = np.array([[float(t[0])]])
            h.props['YData'] = np.array([[float(v.real)]])
            h.props['Color'] = ax.next_color()
            lines.append(h)
        if t.size > 1 and t[-1] != t[0]:
            ax.set_value('XLim', np.array([[min(t[0], t[-1]), max(t[0], t[-1])]]))
        ax.touch()
        _ODEPLOT['state'] = (ax, lines)
        return None
    if flag == 'done':
        _ODEPLOT.pop('state', None)
        return None
    st = _ODEPLOT.get('state')
    if st is None or not args or not numel(args[0]):
        return False
    ax, lines = st
    t = darr(args[0]).reshape(1, -1)
    y = darr(args[1]).reshape(len(lines), -1) if len(lines) else np.zeros((0, t.size))
    for h, row in zip(lines, y):
        if h.valid:
            h.props['XData'] = np.hstack([h.props['XData'].reshape(1, -1), t])
            h.props['YData'] = np.hstack([h.props['YData'].reshape(1, -1), row.real.reshape(1, -1)])
    ax.touch()
    return False


@bi('deval', nout=2)
def deval(nargout, *args):
    if type(args[0]) is Struct:
        sol, x = args[0], darr(args[1]).reshape(-1)
        idx = [int(i) - 1 for i in darr(args[2]).reshape(-1)] if len(args) > 2 else None
    else:
        x, sol = darr(args[0]).reshape(-1), args[1]
        idx = [int(i) - 1 for i in darr(args[2]).reshape(-1)] if len(args) > 2 else None
    holder = sol.get1('idata')
    Y = holder.fn(x)
    if idx is not None:
        Y = Y[idx]
    return out(Y)


def _implicit_parts(F, opts, extra, n, who):
    """F(t, y, yp) and its Jacobian [dF/dy, dF/dyp] (None: by differences) as
    the solvers call them."""
    def res(t, y, yp):
        r = darr(F.scall(1, float(t), out(y.reshape(-1, 1)), out(yp.reshape(-1, 1)), *extra)).reshape(-1)
        if r.size != n:
            raise err('MATLAB:odearguments:SizeIC', f'The function returns a vector of length {r.size}, but the length of the initial conditions vector is {n}.', who)
        return r
    jac = _opt(opts, 'Jacobian')
    if jac is None:
        jpy = None
    elif isinstance(jac, FH):
        def jpy(t, y, yp):
            a, b = jac.scall(2, float(t), out(y.reshape(-1, 1)), out(yp.reshape(-1, 1)), *extra)
            return darr(a), darr(b)
    elif type(jac) is Cell and jac.a.size == 2:
        a, b = jac.a.reshape(-1, order='F')
        jpy = (darr(a), darr(b))
    else:
        raise err(f'MATLAB:{who}:JacobianForm', 'The Jacobian is a function returning [dfdy, dfdyp], or a cell {dfdy, dfdyp}.', who)
    return res, jpy


def _implicit_jac(res, jpy, t, y, yp, atol):
    from ..odesolvers import _fd
    if jpy is None:
        r = res(t, y, yp)
        return (_fd(lambda z: res(t, z, yp), y, r, atol * np.ones(y.size)),
                _fd(lambda z: res(t, y, z), yp, r, np.maximum(np.abs(yp), 1.0) * 1e-8))
    if callable(jpy):
        return jpy(t, y, yp)
    return jpy


@bi('ode15i', nout=5, aw=True, arr=False)
async def ode15i(nargout, *args):
    """F(t, y, y') = 0 by the BDFs of order 1 to 5: an implicit ODE, or a
    DAE of index 1 whose initial conditions are consistent (decic finds
    such)."""
    from ..odesolvers import EPS, _norm
    nargchk(args, 4, None, 'ode15i')
    F = _fn(args[0])
    t0 = float(darr(args[1]).reshape(-1)[0].real)
    y0 = darr(args[2]).reshape(-1).astype(float) if not np.iscomplexobj(darr(args[2])) else darr(args[2]).reshape(-1)
    yp0 = darr(args[3]).reshape(-1).astype(y0.dtype)
    if yp0.size != y0.size:
        raise err('MATLAB:ode15i:YP0Size', 'The initial conditions y0 and yp0 must have the same number of elements.', 'ode15i')
    opts = args[4] if len(args) > 4 else Struct.scalar()
    o = _struct_opts(opts) if type(opts) is Struct else {}
    extra = args[5:]
    rtol = num(_opt(o, 'RelTol')) if _opt(o, 'RelTol') is not None else 1e-3
    atol = darr(_opt(o, 'AbsTol')).reshape(-1) if _opt(o, 'AbsTol') is not None else np.array(1e-6)
    res, jpy = _implicit_parts(F, o, extra, y0.size, 'ode15i')
    r0 = res(t0, y0, yp0)
    Fy, Fyp = _implicit_jac(res, jpy, t0, y0, yp0, atol)
    sy, syp = atol + rtol * np.abs(y0), atol + rtol * np.abs(yp0)
    if np.linalg.cond(Fyp) < 1 / (1000 * EPS):
        # an implicit ODE: y' follows from y, so yp0 is made to fit y0
        yp = yp0.copy()
        for _ in range(50):
            step = np.linalg.solve(_implicit_jac(res, jpy, t0, y0, yp, atol)[1], -res(t0, y0, yp))
            yp = yp + step
            if _norm(step / syp) < 1e-6:
                break
        if _norm((yp - yp0) / syp) > 1:
            R.warn('MATLAB:ode15i:InconsistentIC', 'The initial conditions are not consistent: F(t0, y0, yp0) is not zero, so yp0 is corrected to fit y0.')
        yp0 = yp
    else:
        delta = np.linalg.lstsq(np.hstack([Fy, Fyp]), -r0, rcond=None)[0]
        if _norm(np.concatenate([delta[:y0.size] / sy, delta[y0.size:] / syp])) > 1:
            raise err('MATLAB:ode15i:NeedConsistentIC', 'The initial conditions are not consistent: F(t0, y0, yp0) is not zero. decic finds consistent ones.', 'ode15i')
    return await _ode('ode15i', nargout, [F, args[1], args[2], opts, *extra], label='ode15i', implicit=(res, yp0, jpy))


@bi('decic', nout=3)
def decic(nargout, *args):
    """Initial conditions for F(t, y, y') = 0 that satisfy it, changing the
    components not held as little as least squares can."""
    from ..odesolvers import _norm
    nargchk(args, 6, None, 'decic')
    F = _fn(args[0])
    t0 = float(num(args[1]))
    y = darr(args[2]).reshape(-1).astype(float)
    hold_y = darr(args[3]).reshape(-1) != 0
    yp = darr(args[4]).reshape(-1).astype(float)
    hold_yp = darr(args[5]).reshape(-1) != 0
    n = y.size
    if yp.size != n or hold_y.size != n or hold_yp.size != n:
        raise err('MATLAB:decic:Sizes', 'y0, yp0 and the vectors saying which of them are fixed must have the same length.', 'decic')
    if int(hold_y.sum() + hold_yp.sum()) > n:
        raise err('MATLAB:decic:TooManyFixed', f'More than {n} of the 2*{n} initial values are fixed: the conditions cannot all be met.', 'decic')
    o = _struct_opts(args[6]) if len(args) > 6 else {}
    extra = args[7:]
    atol = darr(_opt(o, 'AbsTol')).reshape(-1) if _opt(o, 'AbsTol') is not None else np.array(1e-6)
    res, jpy = _implicit_parts(F, o, extra, n, 'decic')
    free_y, free_yp = ~hold_y, ~hold_yp
    k = int(free_y.sum())
    for _ in range(100):
        r = res(t0, y, yp)
        Fy, Fyp = _implicit_jac(res, jpy, t0, y, yp, atol)
        A = np.hstack([Fy[:, free_y], Fyp[:, free_yp]])
        delta = np.linalg.lstsq(A, -r, rcond=None)[0]
        y[free_y] += delta[:k]
        yp[free_yp] += delta[k:]
        if _norm(delta) <= 1e-13 * (1 + _norm(np.concatenate([y, yp]))):
            break
    resnrm = float(np.linalg.norm(res(t0, y, yp)))
    return out(y.reshape(-1, 1)), out(yp.reshape(-1, 1)), resnrm


@bi('odextend', aw=True, arr=False)
async def odextend(nargout, *args):
    """Carry a solution structure on to a later time with the solver that
    made it: the solution from its last point joined to it."""
    nargchk(args, 3, 5, 'odextend')
    sol = args[0]
    if type(sol) is not Struct or 'idata' not in sol.f:
        raise err('MATLAB:odextend:InvalidSol', 'The first input must be a solution structure from an ODE solver.', 'odextend')
    ext = sol.get1('extdata')
    name = sol.get1('solver').str()
    f = args[1] if numel(args[1]) else ext.get1('odefun')
    tfinal = num(args[2])
    x, y = darr(sol.get1('x')), darr(sol.get1('y'))
    y0 = darr(args[3]).reshape(-1, 1) if len(args) > 3 and numel(args[3]) else y[:, -1:]
    opts = args[4] if len(args) > 4 else ext.get1('options')
    extra = list(ext.get1('varargin').a.reshape(-1, order='F'))
    if name == 'ode15i':
        raise err('MATLAB:odextend:ode15i', 'odextend does not carry on ode15i solutions here: call ode15i again from the last point.', 'odextend')
    new = await _ode(name, 1, [f, np.array([[x[0, -1], tfinal]]), out(y0), opts, *extra])
    x2, y2 = darr(new.get1('x')), darr(new.get1('y'))
    t1 = x[0, -1]
    f1, f2 = sol.get1('idata').fn, new.get1('idata').fn
    up = tfinal >= t1

    def joined(t):
        t = np.asarray(t, float).reshape(-1)
        first = (t <= t1) if up else (t >= t1)
        res = np.empty((y.shape[0], t.size))
        if np.any(first):
            res[:, first] = f1(t[first])
        if np.any(~first):
            res[:, ~first] = f2(t[~first])
        return res

    for k, v in (('x', out(np.concatenate([x, x2[:, 1:]], axis=1))), ('y', out(np.concatenate([y, y2[:, 1:]], axis=1))),
                 ('idata', _DenseHolder(joined))):
        new.f[k][0, 0] = v
    return new


# ---- interpolation ----------------------------------------------------------------------------

def _interp_cols(x, V, xq, method, extrap):
    """Interpolate the columns of V at xq."""
    from scipy import interpolate
    order = np.argsort(x, kind='stable')
    x = x[order]
    V = V[order]
    if np.any(np.diff(x) == 0):
        raise err('MATLAB:interp1:NonUniqueX', 'The grid vectors must contain unique points.', 'interp1')
    m = method
    if m in ('linear',):
        fn = lambda col: np.interp(xq, x, col, left=np.nan, right=np.nan)
        res = np.column_stack([fn(V[:, j]) if np.isrealobj(V) else fn(V[:, j].real) + 1j * fn(V[:, j].imag) for j in range(V.shape[1])])
        if extrap is not None or m != 'linear':
            pass
        if isinstance(extrap, str) and extrap == 'extrap':
            f = interpolate.interp1d(x, V, axis=0, kind='linear', fill_value='extrapolate', assume_sorted=True)
            res = f(xq)
        elif extrap is not None and not isinstance(extrap, str):
            res = np.where(np.isnan(res) & ((xq < x[0]) | (xq > x[-1]))[:, None], extrap, res)
        return res
    if m in ('nearest', 'next', 'previous'):
        f = interpolate.interp1d(x, V, axis=0, kind=m, bounds_error=False,
                                 fill_value=('extrapolate' if extrap == 'extrap' else (np.nan if extrap is None else extrap)), assume_sorted=True)
        return f(xq)
    if m in ('pchip', 'cubic'):
        f = interpolate.PchipInterpolator(x, V, axis=0, extrapolate=True)
    elif m == 'makima':
        f = interpolate.Akima1DInterpolator(x, V, axis=0, method='makima')
        f.extrapolate = True
    elif m == 'spline':
        f = interpolate.CubicSpline(x, V, axis=0, bc_type='not-a-knot' if x.size > 3 else 'natural', extrapolate=True)
    else:
        raise err('MATLAB:interp1:InvalidMethod', f"Invalid interpolation method '{m}'.", 'interp1')
    res = f(xq)
    if extrap is not None and not isinstance(extrap, str):
        outside = (xq < x[0]) | (xq > x[-1])
        res[outside] = extrap
    return res


@bi('interp1')
def interp1(nargout, *args):
    nargchk(args, 2, 5, 'interp1')
    args = list(args)
    method = 'linear'
    extrap = None
    strs = [i for i, a in enumerate(args) if opt_str(a) is not None]
    for i in reversed(strs):
        s = opt_str(args[i]).lower()
        if s == 'extrap':
            extrap = 'extrap'
        elif s in ('pp',):
            pass
        else:
            method = s if s != '*linear' else 'linear'
        args.pop(i)
    if len(args) >= 4:
        extrap = num(args.pop(3)) if extrap is None else extrap
    if len(args) == 2:
        V = darr(args[0])
        xq = darr(args[1])
        n = V.shape[0] if not (V.ndim == 2 and V.shape[0] == 1) else V.shape[1]
        x = np.arange(1, n + 1, dtype=F64)
    else:
        x = darr(args[0]).reshape(-1)
        V = darr(args[1])
        xq = darr(args[2])
    vec = V.ndim == 2 and (V.shape[0] == 1 or V.shape[1] == 1)
    if vec:
        Vc = V.reshape(-1, 1)
    else:
        Vc = V.reshape(V.shape[0], -1)
    if Vc.shape[0] != x.size:
        raise err('MATLAB:interp1:YInvalidNumRows', 'The data sizes do not match.' if True else '', 'interp1')
    if method in ('spline', 'pchip', 'cubic', 'makima') and extrap is None:
        extrap = 'extrap'
    q = xq.reshape(-1)
    res = _interp_cols(x.real, Vc, q.real, method, extrap)
    if vec:
        return out(np.asarray(res).reshape(xq.shape))
    if xq.ndim == 2 and (xq.shape[0] == 1 or xq.shape[1] == 1):
        return out(np.asarray(res).reshape(q.size, *V.shape[1:]))
    return out(np.asarray(res).reshape(xq.shape + V.shape[1:]))


@bi('interp2')
def interp2(nargout, *args):
    from scipy import interpolate
    args = list(args)
    method = 'linear'
    extrapval = np.nan
    if args and opt_str(args[-1]) is not None:
        method = opt_str(args.pop()).lower()
    elif len(args) >= 2 and opt_str(args[-2]) is not None:
        extrapval = num(args.pop())
        method = opt_str(args.pop()).lower()
    if len(args) == 5:
        X, Y, Z, Xq, Yq = [darr(a) for a in args]
        x = X[0, :] if X.ndim == 2 and X.shape[0] > 1 else X.reshape(-1)
        y = Y[:, 0] if Y.ndim == 2 and Y.shape[1] > 1 else Y.reshape(-1)
    elif len(args) == 3:
        Z, Xq, Yq = [darr(a) for a in args]
        x = np.arange(1, Z.shape[1] + 1, dtype=F64)
        y = np.arange(1, Z.shape[0] + 1, dtype=F64)
    else:
        raise err('MATLAB:interp2:nargin', 'Wrong number of input arguments.', 'interp2')
    if Xq.ndim == 2 and Yq.ndim == 2 and (Xq.shape[0] == 1 and Yq.shape[1] == 1) and Xq.shape != Yq.shape:
        Xq, Yq = np.meshgrid(Xq.reshape(-1), Yq.reshape(-1))
    m = {'linear': 'linear', 'nearest': 'nearest', 'cubic': 'cubic', 'spline': 'cubic', 'makima': 'cubic'}.get(method, 'linear')
    f = interpolate.RegularGridInterpolator((y, x), Z, method=m, bounds_error=False, fill_value=extrapval)
    pts = np.column_stack([Yq.reshape(-1), Xq.reshape(-1)])
    return out(f(pts).reshape(Xq.shape))


@bi('interpn')
def interpn(nargout, *args):
    from scipy import interpolate
    args = list(args)
    method = 'linear'
    if args and opt_str(args[-1]) is not None:
        method = opt_str(args.pop()).lower()
    n = (len(args) - 1) // 2
    grids = [darr(a) for a in args[:n]]
    V = darr(args[n])
    q = [darr(a) for a in args[n + 1:]]
    axes = []
    for k, g in enumerate(grids):
        idx = [0] * g.ndim
        idx[k] = slice(None)
        axes.append(g[tuple(idx)].reshape(-1) if g.ndim > 1 else g.reshape(-1))
    f = interpolate.RegularGridInterpolator(axes, V, method='linear' if method == 'linear' else 'nearest' if method == 'nearest' else 'cubic', bounds_error=False, fill_value=np.nan)
    pts = np.column_stack([a.reshape(-1) for a in q])
    return out(f(pts).reshape(q[0].shape))


@bi('griddata')
def griddata(nargout, *args):
    from scipy import interpolate
    x, y, v, xq, yq = [darr(a) for a in args[:5]]
    method = opt_str(args[5]).lower() if len(args) > 5 else 'linear'
    m = {'linear': 'linear', 'nearest': 'nearest', 'cubic': 'cubic', 'natural': 'linear', 'v4': 'cubic'}.get(method, 'linear')
    if xq.ndim == 2 and yq.ndim == 2 and xq.shape[0] == 1 and yq.shape[1] == 1 and xq.shape != yq.shape:
        xq, yq = np.meshgrid(xq.reshape(-1), yq.reshape(-1))
    r = interpolate.griddata(np.column_stack([x.reshape(-1), y.reshape(-1)]), v.reshape(-1), (xq, yq), method=m)
    return out(r)


class PP(Obj):
    """A piecewise polynomial (spline, pchip, mkpp)."""
    __slots__ = ('breaks', 'coefs', 'order', 'dim')
    cls = 'struct'

    def __init__(self, breaks, coefs, dim=1):
        self.breaks = breaks
        self.coefs = coefs
        self.order = coefs.shape[1]
        self.dim = dim

    def getprop(self, name):
        if name == 'form':
            return Char.of('pp')
        if name == 'breaks':
            return out(self.breaks.reshape(1, -1))
        if name == 'coefs':
            return out(self.coefs)
        if name == 'pieces':
            return float(self.breaks.size - 1)
        if name == 'order':
            return float(self.order)
        if name == 'dim':
            return float(self.dim)
        return super().getprop(name)

    def propnames(self):
        return ['form', 'breaks', 'coefs', 'pieces', 'order', 'dim']

    def display_lines(self):
        return ['  struct with fields:', '', "     form: 'pp'", f'   breaks: [1×{self.breaks.size} double]',
                f'    coefs: [{self.coefs.shape[0]}×{self.coefs.shape[1]} double]', f'   pieces: {self.breaks.size - 1}',
                f'    order: {self.order}', f'      dim: {self.dim}']

    def eval(self, xq):
        b = self.breaks
        k = np.clip(np.searchsorted(b, xq, side='right') - 1, 0, b.size - 2)
        dx = xq - b[k]
        r = np.zeros(xq.shape)
        for j in range(self.order):
            r = r * dx + self.coefs[k, j]
        return r


def _pp_from_scipy(f):
    c = f.c          # (order, pieces)
    return PP(np.asarray(f.x), np.asarray(c).T.copy())


@bi('spline')
def spline(nargout, *args):
    from scipy import interpolate
    x = darr(args[0]).reshape(-1)
    y = darr(args[1])
    yv = y.reshape(-1)
    if yv.size == x.size + 2:
        f = interpolate.CubicSpline(x, yv[1:-1], bc_type=((1, yv[0]), (1, yv[-1])))
    else:
        f = interpolate.CubicSpline(x, yv, bc_type='not-a-knot' if x.size > 3 else 'natural')
    if len(args) == 2:
        return _pp_from_scipy(f)
    xq = darr(args[2])
    return out(f(xq))


@bi('pchip')
def pchip(nargout, *args):
    from scipy import interpolate
    x = darr(args[0]).reshape(-1)
    y = darr(args[1]).reshape(-1)
    f = interpolate.PchipInterpolator(x, y)
    if len(args) == 2:
        return _pp_from_scipy(f)
    return out(f(darr(args[2])))


@bi('makima')
def makima(nargout, *args):
    from scipy import interpolate
    x = darr(args[0]).reshape(-1)
    y = darr(args[1]).reshape(-1)
    f = interpolate.Akima1DInterpolator(x, y, method='makima')
    f.extrapolate = True
    return out(f(darr(args[2])))


@bi('ppval')
def ppval(nargout, *args):
    pp = args[0]
    xq = darr(args[1])
    if not isinstance(pp, PP):
        raise err('MATLAB:ppval:invalidPP', 'The first input must be a piecewise polynomial.', 'ppval')
    return out(pp.eval(xq))


@bi('mkpp')
def mkpp(nargout, *args):
    b = darr(args[0]).reshape(-1)
    c = darr(args[1])
    n = b.size - 1
    c = c.reshape(n, -1)
    return PP(b, c)


@bi('unmkpp', nout=5)
def unmkpp(nargout, *args):
    pp = args[0]
    return (out(pp.breaks.reshape(1, -1)), out(pp.coefs), float(pp.breaks.size - 1), float(pp.order), float(pp.dim))[:max(nargout, 1)]


# ---- polynomials --------------------------------------------------------------------------------

@bi('polyfit', nout=3)
def polyfit(nargout, *args):
    nargchk(args, 3, 3, 'polyfit')
    x = darr(args[0]).reshape(-1)
    y = darr(args[1]).reshape(-1)
    n = ival(args[2], 'degree', 'polyfit')
    if x.size != y.size:
        raise err('MATLAB:polyfit:XYSizeMismatch', 'The first two inputs must have the same number of elements.', 'polyfit')
    mu = None
    if nargout >= 3:
        mu = np.array([np.mean(x), np.std(x, ddof=1)])
        x = (x - mu[0]) / mu[1]
    V = np.vander(x, n + 1)
    Q, Rm = np.linalg.qr(V)
    p = np.linalg.lstsq(V, y, rcond=None)[0]
    if np.linalg.matrix_rank(V) < n + 1:
        R.warn('MATLAB:polyfit:RepeatedPointsOrRescale', 'Polynomial is badly conditioned. Add points with distinct X values, reduce the degree of the polynomial, or try centering and scaling as described in HELP POLYFIT.')
    res = out(p.reshape(1, -1))
    if nargout <= 1:
        return res
    r = y - V @ p
    S = Struct.scalar({'R': out(Rm), 'df': float(max(0, y.size - (n + 1))), 'normr': float(np.linalg.norm(r)),
                       'rsquared': float(1 - np.sum(r ** 2) / np.sum((y - y.mean()) ** 2)) if y.size > 1 else 1.0})
    if nargout == 2:
        return res, S
    return res, S, out(mu.reshape(-1, 1))


@bi('polyval', nout=2)
def polyval(nargout, *args):
    nargchk(args, 2, 4, 'polyval')
    p = darr(args[0]).reshape(-1)
    x = darr(args[1])
    if len(args) > 3:
        mu = darr(args[3]).reshape(-1)
        x = (x - mu[0]) / mu[1]
    y = np.zeros(x.shape, dtype=np.result_type(p, x, F64))
    for c in p:
        y = y * x + c
    if p.size == 0:
        y = np.zeros(x.shape)
    return out(y)


@bi('polyvalm')
def polyvalm(nargout, *args):
    p = darr(args[0]).reshape(-1)
    X = darr(args[1])
    n = X.shape[0]
    Y = np.zeros_like(X)
    for c in p:
        Y = Y @ X + c * np.eye(n)
    return out(Y)


@bi('roots')
def roots(nargout, *args):
    c = darr(args[0]).reshape(-1)
    if not np.all(np.isfinite(c)):
        raise err('MATLAB:roots:NonFiniteInput', 'Input to ROOTS must not contain NaN or Inf.', 'roots')
    nz = np.flatnonzero(c)
    if nz.size == 0:
        return np.zeros((0, 1))
    trailing = c.size - 1 - nz[-1]
    c = c[nz[0]:nz[-1] + 1]
    n = c.size - 1
    if n < 1:
        r = np.zeros(trailing)
    else:
        A = np.diag(np.ones(n - 1, dtype=c.dtype), -1)
        A[0, :] = -c[1:] / c[0]
        r = np.concatenate([np.linalg.eigvals(A), np.zeros(trailing)])
    return out(r.reshape(-1, 1)) if r.size else np.zeros((0, 1))


@bi('poly')
def poly(nargout, *args):
    a = darr(args[0])
    if a.ndim == 2 and a.shape[0] == a.shape[1] and a.shape[0] > 1:
        e = np.linalg.eigvals(a)
    else:
        e = a.reshape(-1)
    c = np.array([1.0 + 0j])
    for z in e:
        c = np.convolve(c, np.array([1.0, -z]))
    if np.all(np.abs(c.imag) <= 0) or np.allclose(np.sort_complex(e), np.sort_complex(np.conj(e))):
        c = c.real
    return out(c.reshape(1, -1))


@bi('conv')
def conv(nargout, *args):
    nargchk(args, 2, 3, 'conv')
    u = darr(args[0])
    v = darr(args[1])
    shape = opt_str(args[2]).lower() if len(args) > 2 else 'full'
    uu, vv = u.reshape(-1), v.reshape(-1)
    full = np.convolve(uu, vv)
    if shape == 'same':
        start = (vv.size - 1) // 2 if True else 0
        start = int(math.ceil((vv.size - 1) / 2))
        r = full[start:start + uu.size]
    elif shape == 'valid':
        n = max(uu.size - vv.size + 1, 0)
        r = full[vv.size - 1:vv.size - 1 + n] if n else np.zeros(0)
    else:
        r = full
    col = (u.ndim == 2 and u.shape[1] == 1 and u.shape[0] > 1) or (u.size == 1 and v.ndim == 2 and v.shape[1] == 1 and v.shape[0] > 1)
    return out(r.reshape(-1, 1) if col else r.reshape(1, -1))


@bi('deconv', nout=2)
def deconv(nargout, *args):
    from scipy import signal
    b = darr(args[0]).reshape(-1)
    a = darr(args[1]).reshape(-1)
    if a[0] == 0:
        raise err('MATLAB:deconv:ZeroCoef1', 'First coefficient of A must be non-zero.', 'deconv')
    q, r = signal.deconvolve(b, a)
    qq = out(q.reshape(1, -1)) if q.size else np.zeros((1, 0))
    if nargout >= 2:
        return qq, out(r.reshape(1, -1))
    return qq


@bi('polyder', nout=2)
def polyder(nargout, *args):
    if len(args) == 2 and nargout < 2:
        p = np.convolve(darr(args[0]).reshape(-1), darr(args[1]).reshape(-1))
        return out(np.polyder(p).reshape(1, -1))
    p = darr(args[0]).reshape(-1)
    if p.size <= 1:
        return 0.0
    d = np.polyder(p)
    return out(d.reshape(1, -1))


@bi('polyint')
def polyint(nargout, *args):
    p = darr(args[0]).reshape(-1)
    k = num(args[1]) if len(args) > 1 else 0.0
    n = p.size
    r = np.concatenate([p / np.arange(n, 0, -1), [k]])
    return out(r.reshape(1, -1))


@bi('residue', nout=3)
def residue(nargout, *args):
    from scipy import signal
    b = darr(args[0]).reshape(-1)
    a = darr(args[1]).reshape(-1)
    r, p, k = signal.residue(b, a)
    return (out(r.reshape(-1, 1)), out(p.reshape(-1, 1)), out(k.reshape(1, -1)) if k.size else np.zeros((0, 0)))[:max(nargout, 1)]


# ---- filters and transforms ---------------------------------------------------------------------

@bi('filter', nout=2)
def filter_(nargout, *args):
    nargchk(args, 3, 5, 'filter')
    from scipy import signal
    b = darr(args[0]).reshape(-1)
    a = darr(args[1]).reshape(-1)
    x = darr(args[2])
    zi = darr(args[3]) if len(args) > 3 and numel(args[3]) else None
    dim = dim_arg(args[4], 'filter') if len(args) > 4 else first_dim(x.shape)
    if a[0] == 0:
        raise err('MATLAB:filter:firstElementOfDenominatorFilterCoefficientsMustBeNonzero', 'First denominator filter coefficient must be non-zero.', 'filter')
    X = expand_dims(x, dim)
    if zi is not None:
        n = max(a.size, b.size) - 1
        ziv = zi.reshape(n, -1) if zi.size else None
        zz = np.moveaxis(ziv.reshape((n,) + tuple(s for i, s in enumerate(X.shape) if i != dim)), 0, dim) if ziv is not None else None
        y, zf = signal.lfilter(b, a, X, axis=dim, zi=zz)
        if nargout >= 2:
            return out(y), out(np.moveaxis(zf, dim, 0).reshape(n, -1))
        return out(y)
    if nargout >= 2:
        n = max(a.size, b.size) - 1
        zz = np.zeros(tuple(n if i == dim else s for i, s in enumerate(X.shape)))
        y, zf = signal.lfilter(b, a, X, axis=dim, zi=zz)
        return out(y), out(np.moveaxis(zf, dim, 0).reshape(n, -1))
    return out(signal.lfilter(b, a, X, axis=dim))


@bi('filter2')
def filter2(nargout, *args):
    from scipy import signal
    h = darr(args[0])
    x = darr(args[1])
    shape = opt_str(args[2]).lower() if len(args) > 2 else 'same'
    return out(signal.correlate2d(x, h, mode=shape))


@bi('conv2')
def conv2(nargout, *args):
    from scipy import signal
    if len(args) >= 3 and opt_str(args[2]) is None:
        u = darr(args[0]).reshape(-1)
        v = darr(args[1]).reshape(-1)
        A = darr(args[2])
        shape = opt_str(args[3]).lower() if len(args) > 3 else 'full'
        r = signal.convolve2d(signal.convolve2d(A, u.reshape(-1, 1), mode='full'), v.reshape(1, -1), mode='full')
        if shape == 'full':
            return out(r)
        ker = np.outer(u, v)
        return out(signal.convolve2d(A, ker, mode=shape))
    A = darr(args[0])
    B = darr(args[1])
    shape = opt_str(args[2]).lower() if len(args) > 2 else 'full'
    return out(signal.convolve2d(A, B, mode=shape))


@bi('convn')
def convn(nargout, *args):
    from scipy import signal
    A = darr(args[0])
    B = darr(args[1])
    shape = opt_str(args[2]).lower() if len(args) > 2 else 'full'
    return out(signal.convolve(A, B, mode=shape, method='direct'))


def _fft_like(name, fn):
    def f(nargout, *args):
        nargchk(args, 1, 3, name)
        x = darr(args[0])
        n = None
        if len(args) > 1 and numel(args[1]):
            n = ival(args[1], 'n', name)
        dim = dim_arg(args[2], name) if len(args) > 2 else first_dim(x.shape)
        X = expand_dims(x, dim)
        r = fn(X, n=n, axis=dim)
        if name == 'ifft' and len(args) > 1 and opt_str(args[-1]) == 'symmetric':
            r = r.real
        return out(r)
    f.__name__ = name
    bi(name)(f)


_fft_like('fft', np.fft.fft)
_fft_like('ifft', np.fft.ifft)


@bi('fft2')
def fft2(nargout, *args):
    x = darr(args[0])
    s = (ival(args[1]), ival(args[2])) if len(args) > 2 else None
    return out(np.fft.fft2(x, s=s))


@bi('ifft2')
def ifft2(nargout, *args):
    x = darr(args[0])
    s = (ival(args[1]), ival(args[2])) if len(args) > 2 and opt_str(args[1]) is None else None
    r = np.fft.ifft2(x, s=s)
    if args and opt_str(args[-1]) == 'symmetric':
        r = r.real
    return out(r)


@bi('fftn')
def fftn(nargout, *args):
    return out(np.fft.fftn(darr(args[0])))


@bi('ifftn')
def ifftn(nargout, *args):
    return out(np.fft.ifftn(darr(args[0])))


@bi('fftshift')
def fftshift(nargout, *args):
    x = arr(args[0])
    if len(args) > 1:
        return like_class(np.fft.fftshift(x, axes=ival(args[1]) - 1), args[0])
    if x.ndim == 2 and (x.shape[0] == 1 or x.shape[1] == 1):
        return like_class(np.fft.fftshift(x), args[0])
    return like_class(np.fft.fftshift(x), args[0])


@bi('ifftshift')
def ifftshift(nargout, *args):
    x = arr(args[0])
    if len(args) > 1:
        return like_class(np.fft.ifftshift(x, axes=ival(args[1]) - 1), args[0])
    return like_class(np.fft.ifftshift(x), args[0])


@bi('detrend')
def detrend(nargout, *args):
    from scipy import signal
    x = darr(args[0])
    order = num(args[1]) if len(args) > 1 and opt_str(args[1]) is None else 1
    kind = 'constant' if order == 0 or (len(args) > 1 and opt_str(args[1]) == 'constant') else 'linear'
    dim = first_dim(x.shape)
    return out(signal.detrend(x, axis=dim, type=kind))


@bi('gradient', nout=3)
def gradient(nargout, *args):
    f = darr(args[0])
    spacing = [darr(a).reshape(-1) for a in args[1:]]
    if f.ndim == 2 and (f.shape[0] == 1 or f.shape[1] == 1):
        h = spacing[0] if spacing else np.array([1.0])
        h = h[0] if h.size == 1 else h
        g = np.gradient(f.reshape(-1), h)
        return out(g.reshape(f.shape))
    hx = spacing[0] if spacing else np.array([1.0])
    hy = spacing[1] if len(spacing) > 1 else hx
    hx = hx[0] if hx.size == 1 else hx
    hy = hy[0] if hy.size == 1 else hy
    gy, gx = np.gradient(f, hy, hx)
    if nargout <= 1:
        return out(gx)
    return out(gx), out(gy)


@bi('del2')
def del2(nargout, *args):
    f = darr(args[0])
    h = num(args[1]) if len(args) > 1 else 1.0
    if f.ndim == 2 and (f.shape[0] == 1 or f.shape[1] == 1):
        v = f.reshape(-1)
        g = np.gradient(np.gradient(v, h), h) / 4
        return out(g.reshape(f.shape))
    gy = np.gradient(np.gradient(f, h, axis=0), h, axis=0)
    gx = np.gradient(np.gradient(f, h, axis=1), h, axis=1)
    return out((gx + gy) / 4)
