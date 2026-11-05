"""Numerical methods on SciPy: roots and minima, integrals, ordinary
differential equations, interpolation, polynomials, filters and Fourier
transforms.

Functions passed in (handles or names) are called synchronously from SciPy's
loops, so they cannot wait for input there.
"""
import math

import numpy as np

from . import bi
from ._util import (err, nargchk, noout, maxout, arr, darr, out, opt_str, opt_lower, sval, ival, num, is_str, bool_out,
                    like_class, first_dim, dim_arg, expand_dims, strip_flags)
from ..ops import finish
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
    r = optimize.brentq(gg, min(a, b), max(a, b), xtol=max(tolx, 1e-300), rtol=4 * np.finfo(float).eps, maxiter=500, full_output=False)
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
    xatol = max(num(tolx), 1e-12) if tolx is not None else 1e-4
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


def _quad1(g, a, b, atol, rtol, pts=None):
    """The integral of g (which may give complex values) from a to b, both
    real: (value, error bound)."""
    from scipy import integrate
    imag = [False]

    def re_(t):
        v = g(float(t))
        if isinstance(v, complex):
            imag[0] = imag[0] or v.imag != 0
            return v.real
        return v
    kw = dict(epsabs=atol, epsrel=rtol, limit=650)
    if pts and math.isfinite(a) and math.isfinite(b):
        inner = [p for p in pts if min(a, b) < p < max(a, b)]
        if inner:
            kw['points'] = inner
    r, e = integrate.quad(re_, a, b, **kw)
    if imag[0]:
        ri, ei = integrate.quad(lambda t: complex(g(float(t))).imag, a, b, **kw)
        return complex(r, ri), e + ei
    return r, e


def _path_integral(f, a, b, waypoints, atol, rtol):
    """The integral of f from a to b through the waypoints: on the real line,
    or along the straight segments between them in the complex plane."""
    nodes = [a] + list(waypoints) + [b]
    if all(not isinstance(z, complex) or z.imag == 0 for z in nodes):
        nodes = [z.real if isinstance(z, complex) else z for z in nodes]
        return _quad1(lambda t: _scalar(_call1(f, t)), nodes[0], nodes[-1], atol, rtol, nodes[1:-1])
    total, err_ = 0j, 0.0
    for z0, z1 in zip(nodes[:-1], nodes[1:]):
        z0, z1 = complex(z0), complex(z1)
        dz = z1 - z0
        v, e = _quad1(lambda t, z0=z0, dz=dz: complex(_scalar(_call1(f, z0 + t * dz))) * dz, 0.0, 1.0, atol, rtol)
        total += v
        err_ += e
    return total, err_


def _num_or_complex(v):
    a = arr(v).reshape(-1)
    x = a[0]
    return complex(x) if np.iscomplexobj(a) and complex(x).imag != 0 else float(np.real(x))


def _integral_opts(args, first):
    opts = {}
    for i in range(first, len(args) - 1, 2):
        opts[py_str(args[i]).lower()] = args[i + 1]
    return opts


def _single_out(v, *limits):
    """The result as single when a limit is single."""
    if any(class_of(x) == 'single' for x in limits):
        return finish(np.array([[v]]), 'single')
    return v.real if isinstance(v, complex) and v.imag == 0 else v


def _waypoints(opts):
    if 'waypoints' not in opts:
        return []
    w = arr(opts['waypoints']).reshape(-1)
    return [complex(z) if np.iscomplexobj(w) else float(z) for z in w]


@bi('integral')
def integral(nargout, *args):
    nargchk(args, 3, None, 'integral')
    from scipy import integrate
    f = _fn(args[0])
    a, b = _num_or_complex(args[1]), _num_or_complex(args[2])
    opts = _integral_opts(args, 3)
    rtol = num(opts['reltol']) if 'reltol' in opts else 1e-6
    atol = num(opts['abstol']) if 'abstol' in opts else 1e-10
    if 'arrayvalued' in opts and bool(arr(opts['arrayvalued']).reshape(-1)[0]):
        v0 = darr(_call1(f, a))
        shape = v0.shape
        r, e = integrate.quad_vec(lambda t: darr(_call1(f, float(t))).reshape(-1), a, b, epsabs=atol, epsrel=rtol)
        return out(np.asarray(r).reshape(shape))
    try:
        r, e = _path_integral(f, a, b, _waypoints(opts), atol, rtol)
    except integrate.IntegrationWarning as w:
        R.warn('MATLAB:integral:MaxIntervalCountReached', str(w))
        r = float('nan')
    return _single_out(r, args[1], args[2], opts.get('waypoints', 0.0))


def _realpart(x):
    return x.real if isinstance(x, complex) else x


@bi('quadgk', nout=2)
def quadgk(nargout, *args):
    """quadgk(f, a, b, Name, Value): RelTol, AbsTol, Waypoints (complex ones
    make a path), ArrayValued; the error bound as the second output."""
    from scipy import integrate
    f = _fn(args[0])
    a, b = _num_or_complex(args[1]), _num_or_complex(args[2])
    opts = _integral_opts(args, 3)
    rtol = num(opts['reltol']) if 'reltol' in opts else 1e-6
    atol = num(opts['abstol']) if 'abstol' in opts else 1e-10
    if 'arrayvalued' in opts and bool(arr(opts['arrayvalued']).reshape(-1)[0]):
        shape = darr(_call1(f, float(np.real(a)))).shape
        r, e = integrate.quad_vec(lambda t: darr(_call1(f, float(t))).reshape(-1), a, b, epsabs=atol, epsrel=rtol)
        res = out(np.asarray(r).reshape(shape))
        return (res, float(e)) if nargout >= 2 else res
    r, e = _path_integral(f, a, b, _waypoints(opts), atol, rtol)
    r = _single_out(r, args[1], args[2], opts.get('waypoints', 0.0))
    return (r, float(e)) if nargout >= 2 else r


@bi('quad', 'quadl', nout=2)
def quad(nargout, *args):
    """quad(f, a, b, tol, trace, p1, p2, ...): the parameters after trace go
    to f after x; the number of evaluations of f as the second output."""
    nargchk(args, 3, None, 'quad')
    f = _fn(args[0])
    a, b = num(args[1]), num(args[2])
    tol = num(args[3]) if len(args) > 3 and numel(args[3]) else 1e-6
    extra = list(args[5:])
    count = [0]

    def g(t):
        count[0] += 1
        return _scalar(_call1(f, t, *extra))
    r, e = _quad1(g, a, b, tol, 1e-6 if tol >= 1e-6 else tol)
    r = _single_out(r, args[1], args[2])
    return (r, float(count[0])) if nargout >= 2 else r


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
    xa, xb = num(args[1]), num(args[2])
    # limits of y may be functions of x, those of z functions of x and y
    ylo, yhi = [(lambda x, h=h: _scalar(_call1(h, float(x)))) if isinstance(h, FH) else num(h) for h in args[3:5]]
    zlo, zhi = [(lambda x, y, h=h: _scalar(_call1(h, float(x), float(y)))) if isinstance(h, FH) else num(h) for h in args[5:7]]
    r, e = integrate.tplquad(lambda z, y, x: _realpart(_scalar(_call1(f, float(x), float(y), float(z)))),
                             xa, xb, ylo, yhi, zlo, zhi, epsabs=1e-10, epsrel=1e-6)
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
    if type(sol) is not Struct or 'idata' not in sol.f:
        raise err('MATLAB:deval:SolNotFromDiffEqSolver', 'sol must be a solution structure from an ODE solver (sol = ode45(...)).', 'deval')
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
        if extrap == 'extrap':
            xq = np.clip(xq, x[0], x[-1])       # past the ends: the value at the end
        if m == 'nearest':
            # a half rounds up, as in the language
            pos = np.interp(xq, x, np.arange(x.size, dtype=F64))
            k = np.clip(np.floor(pos + 0.5).astype(np.intp), 0, x.size - 1)
            res = V[k].astype(np.result_type(V.dtype, F64))
            outside = (xq < x[0]) | (xq > x[-1])
            if outside.any():
                res[outside] = np.nan if extrap is None or isinstance(extrap, str) else extrap
            return res
        f = interpolate.interp1d(x, V, axis=0, kind=m, bounds_error=False,
                                 fill_value=(np.nan if extrap is None or isinstance(extrap, str) else extrap), assume_sorted=True)
        return f(xq)
    if m in ('pchip', 'cubic', 'makima') and np.iscomplexobj(V):
        # not linear in the values: the real and imaginary parts apart
        return _interp_cols(x, V.real, xq, method, extrap) + 1j * _interp_cols(x, V.imag, xq, method, extrap)
    if m in ('pchip', 'cubic'):
        f = interpolate.PchipInterpolator(x, V, axis=0, extrapolate=True)
    elif m == 'makima':
        f = interpolate.Akima1DInterpolator(x, V, axis=0, method='makima')
        f.extrapolate = True
    elif m == 'spline':
        f = interpolate.CubicSpline(x, V, axis=0, bc_type='not-a-knot', extrapolate=True)    # a parabola through 3 points, a line through 2
    else:
        raise err('MATLAB:interp1:InvalidMethod', f"Invalid interpolation method '{m}'.", 'interp1')
    res = f(xq)
    if extrap is not None and not isinstance(extrap, str):
        outside = (xq < x[0]) | (xq > x[-1])
        res[outside] = extrap
    return res


def _interp1_pp(x, V, method):
    """interp1(x, v, method, 'pp'): the interpolant as a piecewise polynomial."""
    if np.asarray(x).size < 2:
        raise err('MATLAB:interp1:NotEnoughPts', 'Interpolation needs at least two sample points.', 'interp1')
    from scipy import interpolate
    vec = V.ndim == 2 and 1 in V.shape
    Vc = V.reshape(-1, 1) if vec else V.reshape(V.shape[0], -1)
    order = np.argsort(x, kind='stable')
    x, Vc = x[order].astype(F64), Vc[order]
    dim = (1,) if vec else V.shape[1:]
    D = Vc.shape[1]
    n = x.size
    if method == 'linear':
        slope = np.diff(Vc, axis=0) / np.diff(x)[:, None]
        coefs = np.stack([slope, Vc[:-1]], axis=-1).reshape((n - 1) * D, 2)
        return PP(x, coefs, dim)
    if method in ('nearest', 'previous', 'next'):
        if method == 'nearest':
            br = np.concatenate([[x[0]], (x[:-1] + x[1:]) / 2, [x[-1]]])
            vals = Vc
        else:
            br = x
            vals = Vc[:-1] if method == 'previous' else Vc[1:]
        return PP(br, vals.reshape(-1, 1), dim)
    if method in ('pchip', 'cubic'):
        f = interpolate.PchipInterpolator(x, Vc, axis=0)
    elif method == 'makima':
        f = interpolate.Akima1DInterpolator(x, Vc, axis=0, method='makima')
    elif method == 'spline':
        f = interpolate.CubicSpline(x, Vc, axis=0, bc_type='not-a-knot')
    else:
        raise err('MATLAB:interp1:InvalidMethod', f"Invalid interpolation method '{method}'.", 'interp1')
    c = np.asarray(f.c)                    # (order, pieces, D)
    k = c.shape[0]
    return PP(np.asarray(f.x), c.transpose(1, 2, 0).reshape(-1, k), dim)


@bi('interp1')
def interp1(nargout, *args):
    nargchk(args, 2, 5, 'interp1')
    args = list(args)
    method = 'linear'
    extrap = None
    want_pp = False
    strs = [i for i, a in enumerate(args) if opt_str(a) is not None]
    # interp1(v, xq, method, ...): the method third means there is no x
    no_x = bool(strs) and strs[0] == 2 and opt_lower(args[2]) not in ('extrap', 'pp')
    for i in reversed(strs):
        s = opt_lower(args[i])
        if s == 'extrap':
            extrap = 'extrap'
        elif s in ('pp',):
            want_pp = True
        else:
            method = s.lstrip('*')          # '*linear' and the like: equally spaced points, the same result
            if method == 'v5cubic':
                method = 'cubic'
        args.pop(i)
    if want_pp:
        return _interp1_pp(darr(args[0]).reshape(-1), darr(args[1]), method)
    if no_x and len(args) == 3:
        extrap = num(args.pop(2)) if extrap is None else extrap
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
        raise err('MATLAB:interp1:YInvalidNumRows', 'The data sizes do not match.', 'interp1')
    if x.size < 2:
        raise err('MATLAB:interp1:NotEnoughPts', 'Interpolation needs at least two sample points.', 'interp1')
    if method in ('spline', 'pchip', 'cubic', 'makima') and extrap is None:
        extrap = 'extrap'
    q = xq.reshape(-1)
    res = _interp_cols(x.real, Vc, q.real, method, extrap)
    if vec:
        return out(np.asarray(res).reshape(xq.shape))
    if xq.ndim == 2 and (xq.shape[0] == 1 or xq.shape[1] == 1):
        return out(np.asarray(res).reshape(q.size, *V.shape[1:]))
    return out(np.asarray(res).reshape(xq.shape + V.shape[1:]))


# ---- interpolation on grids (interp2, interpn) ------------------------------------------------------

_GRID_METHODS = ('linear', 'nearest', 'cubic', 'spline', 'pchip', 'makima')


def _axis_weights(x, q, method):
    """The weights that give method's interpolant at the points q from the
    values at the grid points x (increasing): a len(q)-by-len(x) matrix, for
    the methods whose interpolant is linear in the values. Rows of points
    outside the grid are NaN."""
    n = x.size
    W = np.zeros((q.size, n))
    inside = (q >= x[0]) & (q <= x[-1])
    if n == 1:
        W[:, 0] = np.where(q == x[0], 1.0, np.nan)
        return W
    pos = np.interp(q, x, np.arange(n, dtype=F64))
    if method == 'nearest':
        k = np.clip(np.floor(pos + 0.5).astype(np.intp), 0, n - 1)        # a half rounds up
        W[np.arange(q.size), k] = 1.0
    elif method == 'linear' or n == 2:
        k = np.clip(np.floor(pos).astype(np.intp), 0, n - 2)
        t = pos - k
        W[np.arange(q.size), k] = 1 - t
        W[np.arange(q.size), k + 1] += t
    elif method == 'cubic' and np.allclose(np.diff(x), x[1] - x[0], rtol=1e-9, atol=0) and n >= 3:
        # Keys' cubic convolution (a = -1/2), the values past the ends extended by
        # f(-1) = 3 f(0) - 3 f(1) + f(2) (and alike at the other end)
        k = np.clip(np.floor(pos).astype(np.intp), 0, n - 2)
        t = pos - k

        def kern(s):
            s = np.abs(s)
            return np.where(s <= 1, 1.5 * s ** 3 - 2.5 * s ** 2 + 1, np.where(s < 2, -0.5 * s ** 3 + 2.5 * s ** 2 - 4 * s + 2, 0.0))
        rows = np.arange(q.size)
        for off in (-1, 0, 1, 2):
            w = kern(t - off)
            j = k + off
            for jj, ww in ((j, w),):
                lo, hi = jj < 0, jj > n - 1
                mid = ~(lo | hi)
                np.add.at(W, (rows[mid], jj[mid]), ww[mid])
                for c, idx in ((3, 0), (-3, 1), (1, 2)):
                    np.add.at(W, (rows[lo], np.full(lo.sum(), idx)), c * ww[lo])
                    np.add.at(W, (rows[hi], np.full(hi.sum(), n - 1 - idx)), c * ww[hi])
    else:
        # the cubic spline (not-a-knot), as the language's spline makes it
        from scipy import interpolate
        W = interpolate.CubicSpline(x, np.eye(n), axis=0, bc_type='not-a-knot')(q).reshape(q.size, n)
    W[~inside] = np.nan
    return W


def _grid_interp(axes, V, Q, method, extrapval, grid):
    """Values of V (on the grid of the vectors axes) at Q: a list of the query
    coordinates, one array per dimension; grid says Q is a list of grid
    vectors (the result is their grid) rather than points (all one size)."""
    from scipy import interpolate
    axes = [np.asarray(a, F64).reshape(-1) for a in axes]
    V = np.asarray(V)
    V = V.reshape(V.shape + (1,) * (len(axes) - V.ndim))
    for d, a in enumerate(axes):
        if a.size != V.shape[d]:
            raise err('MATLAB:interpn:gridMismatch', 'The grid vectors do not match the size of the values.', 'interp2')
        if a.size > 1 and a[0] > a[-1]:
            axes[d] = a[::-1]
            V = np.flip(V, d)
        if a.size > 1 and np.any(np.diff(axes[d]) <= 0):
            raise err('MATLAB:griddedInterpolant:NonMonotonicCompVecsErrId', 'The grid vectors must be strictly monotonic.', 'interp2')
    Q = [np.asarray(q, F64).reshape(-1) for q in Q]
    cplx = V.dtype.kind == 'c'
    Vf = V.astype(C128 if cplx else F64)
    if method in ('linear', 'nearest', 'cubic', 'spline'):
        Ws = [_axis_weights(a, q, method) for a, q in zip(axes, Q)]

        def apply(data, mats):
            """The weights applied dimension by dimension (to a grid, or to points)."""
            if grid:
                r_ = data
                for d, W in enumerate(mats):
                    r_ = np.moveaxis(np.tensordot(W, np.moveaxis(r_, d, 0), axes=(1, 0)), 0, d)
                return r_
            r_ = np.tensordot(mats[0], data, axes=(1, 0))            # (points, the rest)
            for W in mats[1:]:
                r_ = np.einsum('kj,kj...->k...', W, r_)
            return r_
        nan_v = np.isnan(Vf)
        r = apply(np.where(nan_v, 0, Vf), [np.nan_to_num(W, nan=0.0) for W in Ws])
        # NaN where a value used is NaN, or a point is outside the grid
        if nan_v.any():
            r = np.where(apply(nan_v.astype(F64), [np.abs(np.nan_to_num(W, nan=0.0)) for W in Ws]) > 0, np.nan, r)
        if grid:
            for d, W in enumerate(Ws):
                bad = np.isnan(W).any(axis=1)
                if bad.any():
                    idx = [slice(None)] * r.ndim
                    idx[d] = bad
                    r[tuple(idx)] = np.nan
        else:
            bad = np.zeros(Q[0].size, bool)
            for W in Ws:
                bad |= np.isnan(W).any(axis=1)
            r = np.where(bad.reshape((-1,) + (1,) * (r.ndim - 1)), np.nan, r)
        if cplx:
            r = np.where(np.isnan(r), complex(np.nan, np.nan), r)
    elif cplx:
        # pchip and makima: not linear in the values, so the real and imaginary parts apart
        r = (_grid_interp(axes, Vf.real, Q, method, np.nan, grid)
             + 1j * _grid_interp(axes, Vf.imag, Q, method, np.nan, grid))
        r = np.where(np.isnan(r), complex(np.nan, np.nan), r)
    else:
        # pchip and makima: not linear in the values; dimension by dimension on a grid
        def along(vals, a, q, d):
            vals = np.moveaxis(vals, d, 0)
            # a line with a NaN in it gives NaN (the interpolants take no NaN)
            nanline = np.isnan(vals).any(axis=0)
            vals = np.where(np.isnan(vals), 0.0, vals)
            if a.size < 2:
                res = np.repeat(vals[:1], q.size, axis=0)
            elif method == 'makima' and a.size >= 3:
                f = interpolate.Akima1DInterpolator(a, vals, axis=0, method='makima')
                res = f(q)
            else:
                res = interpolate.PchipInterpolator(a, vals, axis=0, extrapolate=False)(q)
            res = np.where(((q < a[0]) | (q > a[-1])).reshape((-1,) + (1,) * (res.ndim - 1)), np.nan, res)
            res = np.where(nanline[None, ...], np.nan, res)
            return np.moveaxis(res, 0, d)
        if grid:
            r = Vf
            for d, (a, q) in enumerate(zip(axes, Q)):
                r = along(r, a, q, d)
        else:
            if all(a.size >= 4 for a in axes):
                f = interpolate.RegularGridInterpolator(axes, Vf, method='pchip', bounds_error=False, fill_value=np.nan)
            else:
                f = interpolate.RegularGridInterpolator(axes, Vf, method='linear', bounds_error=False, fill_value=np.nan)
            r = f(np.column_stack(Q))
    if not (isinstance(extrapval, float) and math.isnan(extrapval)):
        r = np.where(np.isnan(r), extrapval, r) if not np.iscomplexobj(r) else r
    return r


def _interp_opts(args, fn):
    """args without the method and extrapolation value at their end; the method and that value."""
    args = list(args)
    method, extrapval = 'linear', np.nan
    if len(args) >= 2 and opt_str(args[-2]) is not None and opt_str(args[-1]) is None:
        extrapval = num(args.pop())
    if args and opt_str(args[-1]) is not None:
        method = opt_lower(args.pop()).lstrip('*')
        if method == 'v5cubic':
            method = 'cubic'
        if method not in _GRID_METHODS:
            raise err(f'MATLAB:{fn}:InvalidMethod', f"Invalid interpolation method '{method}'.", fn)
    return args, method, extrapval


def _grid_vector(G, d):
    """A grid vector from a vector, or from an ndgrid/meshgrid array along dimension d."""
    G = np.asarray(G, F64)
    if G.ndim == 2 and 1 in G.shape:
        return G.reshape(-1)
    idx = [0] * G.ndim
    idx[d] = slice(None)
    return G[tuple(idx)].reshape(-1)


def _is_grid_query(Q):
    """Query arrays as grid vectors: all vectors, not all of one size and orientation."""
    if not all(q.ndim == 2 and 1 in q.shape for q in Q):
        return False
    return len(set(q.shape for q in Q)) > 1


@bi('interp2')
def interp2(nargout, *args):
    nargchk(args, 1, 7, 'interp2')
    args, method, extrapval = _interp_opts(args, 'interp2')
    if len(args) in (1, 2):
        # interp2(Z) and interp2(Z, k): the grid refined k times (once unless given)
        Z = darr(args[0])
        k = ival(args[1], 'k', 'interp2') if len(args) == 2 else 1
        m, n = Z.shape[:2]
        xq = np.linspace(1, n, (n - 1) * 2 ** k + 1)
        yq = np.linspace(1, m, (m - 1) * 2 ** k + 1)
        r = _grid_interp([np.arange(1, m + 1), np.arange(1, n + 1)], Z, [yq, xq], method, extrapval, True)
        return out(r)
    if len(args) == 3:
        Z, Xq, Yq = darr(args[0]), darr(args[1]), darr(args[2])
        x, y = np.arange(1, Z.shape[1] + 1, dtype=F64), np.arange(1, Z.shape[0] + 1, dtype=F64)
    elif len(args) == 5:
        X, Y, Z, Xq, Yq = [darr(a) for a in args]
        x, y = _grid_vector(X, 1), _grid_vector(Y, 0)
    else:
        raise err('MATLAB:interp2:nargin', 'Wrong number of input arguments.', 'interp2')
    # a row of x and a column of y (or vectors of different sizes) make a grid
    if Xq.ndim == 2 and Yq.ndim == 2 and 1 in Xq.shape and 1 in Yq.shape and (Xq.shape != Yq.shape or (Xq.shape[0] == 1 and Yq.shape[1] == 1 and Xq.size > 1 and Yq.size > 1 and Xq.shape != Yq.shape)):
        r = _grid_interp([y, x], Z, [Yq.reshape(-1), Xq.reshape(-1)], method, extrapval, True)
        return out(r)
    if Xq.shape != Yq.shape:
        if Xq.size == 1 or Yq.size == 1:
            Xq, Yq = np.broadcast_arrays(Xq, Yq)
        else:
            raise err('MATLAB:interp2:XqYqMismatch', 'Xq and Yq must be the same size or vectors.', 'interp2')
    r = _grid_interp([y, x], Z, [Yq, Xq], method, extrapval, False)
    return out(np.asarray(r).reshape(Xq.shape))


@bi('interpn')
def interpn(nargout, *args):
    nargchk(args, 1, None, 'interpn')
    args, method, extrapval = _interp_opts(args, 'interpn')
    if len(args) in (1, 2) and not (len(args) == 2 and numel(args[1]) > 1):
        V = darr(args[0])
        k = ival(args[1], 'k', 'interpn') if len(args) == 2 else 1
        axes = [np.arange(1, s + 1, dtype=F64) for s in V.shape]
        Q = [np.linspace(1, s, (s - 1) * 2 ** k + 1) for s in V.shape]
        return out(_grid_interp(axes, V, Q, method, extrapval, True))
    first = darr(args[0])
    if len(args) % 2 == 1 and not (first.ndim >= 2 and min(first.shape) > 1 and first.ndim == len(args) - 1):
        n = len(args) // 2
        V = darr(args[n])
        axes = [_grid_vector(darr(a), d) for d, a in enumerate(args[:n])]
        Q = [darr(a) for a in args[n + 1:]]
    else:
        V = darr(args[0])
        n = len(args) - 1
        axes = [np.arange(1, s + 1, dtype=F64) for s in (V.shape + (1,) * n)[:n]]
        Q = [darr(a) for a in args[1:]]
    if len(Q) != len(axes) or any(s > 1 for s in V.shape[len(axes):]):
        raise err('MATLAB:interpn:nargin', 'Wrong number of input arguments: give one grid and one query array per dimension of V.', 'interpn')
    if _is_grid_query(Q):
        return out(_grid_interp(axes, V, [q.reshape(-1) for q in Q], method, extrapval, True))
    shape = Q[0].shape
    if any(q.shape != shape for q in Q):
        Q = np.broadcast_arrays(*Q)
        shape = Q[0].shape
    return out(np.asarray(_grid_interp(axes, V, Q, method, extrapval, False)).reshape(shape))


@bi('griddata')
def griddata(nargout, *args):
    from scipy import interpolate
    x, y, v, xq, yq = [darr(a) for a in args[:5]]
    method = opt_lower(args[5]) if len(args) > 5 else 'linear'
    m = {'linear': 'linear', 'nearest': 'nearest', 'cubic': 'cubic', 'natural': 'linear', 'v4': 'cubic'}.get(method, 'linear')
    if xq.ndim == 2 and yq.ndim == 2 and xq.shape[0] == 1 and yq.shape[1] == 1 and xq.shape != yq.shape:
        xq, yq = np.meshgrid(xq.reshape(-1), yq.reshape(-1))
    r = interpolate.griddata(np.column_stack([x.reshape(-1), y.reshape(-1)]), v.reshape(-1), (xq, yq), method=m)
    return out(r)


class PP(Obj):
    """A piecewise polynomial (spline, pchip, mkpp), as the language's pp
    form: breaks; coefs with a row for each piece and value component (the
    components of a piece together); its order; dim, the size of a value."""
    __slots__ = ('breaks', 'coefs', 'order', 'dim')
    cls = 'struct'

    def __init__(self, breaks, coefs, dim=(1,)):
        self.breaks = np.asarray(breaks, F64).reshape(-1)
        self.coefs = np.asarray(coefs)
        self.order = self.coefs.shape[1]
        self.dim = tuple(int(d) for d in dim)

    def ncomp(self):
        return int(np.prod(self.dim))

    def dim_value(self):
        return float(self.dim[0]) if len(self.dim) == 1 else np.array([[float(d) for d in self.dim]])

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
            return self.dim_value()
        return super().getprop(name)

    def propnames(self):
        return ['form', 'breaks', 'coefs', 'pieces', 'order', 'dim']

    def display_lines(self):
        d = str(self.dim[0]) if len(self.dim) == 1 else '[' + ' '.join(str(x) for x in self.dim) + ']'
        return ['  struct with fields:', '', "     form: 'pp'", f'   breaks: [1×{self.breaks.size} double]',
                f'    coefs: [{self.coefs.shape[0]}×{self.coefs.shape[1]} double]', f'   pieces: {self.breaks.size - 1}',
                f'    order: {self.order}', f'      dim: {d}']

    def eval(self, xq):
        """The values at xq: xq's shape for scalar values, else dim by xq
        (dim by length(xq) for a vector xq)."""
        b = self.breaks
        D = self.ncomp()
        xv = np.asarray(xq).reshape(-1, order='F')
        k = np.clip(np.searchsorted(b, xv, side='right') - 1, 0, max(b.size - 2, 0))
        dx = xv - b[k]
        rows = k[None, :] * D + np.arange(D)[:, None]
        r = np.zeros((D, xv.size), self.coefs.dtype)
        for j in range(self.order):
            r = r * dx[None, :] + self.coefs[rows, j]
        r = np.where(np.isnan(xv)[None, :], np.nan, r)
        xq = np.asarray(xq)
        if self.dim == (1,):
            return r.reshape(xq.shape, order='F')
        isvec = xq.ndim == 2 and 1 in xq.shape
        return r.reshape(self.dim + ((xv.size,) if isvec else xq.shape), order='F')


def _pp_from_scipy(f, dim=(1,)):
    """A pp of scipy's piecewise polynomial (its c: order, pieces, components)."""
    c = np.asarray(f.c)
    k, n = c.shape[:2]
    D = int(np.prod(dim))
    coefs = c.reshape(k, n, D).transpose(1, 2, 0).reshape(n * D, k)
    return PP(np.asarray(f.x), coefs, dim)


def _interp_data(args, fn):
    """x (sorted, increasing) and the values y with x along their last dimension
    (as the rows of a D-by-n matrix), y's leading size, and whether y was a vector."""
    x = darr(args[0]).reshape(-1).astype(F64)
    y = darr(args[1])
    isvec = y.ndim == 2 and 1 in y.shape
    Y = y.reshape(1, -1) if isvec else y.reshape(-1, y.shape[-1], order='F')
    dim = (1,) if isvec else y.shape[:-1]
    if Y.shape[-1] not in (x.size, x.size + 2):
        raise err(f'MATLAB:{fn}:XYLengthMismatch', 'The values must be as many as the points x along their last dimension (or two more, for a spline with end slopes).', fn)
    if x.size < 2:
        raise err(f'MATLAB:{fn}:NotEnoughPts', 'There must be at least two points.', fn)
    return x, Y, dim, isvec


def _sorted(x, Y, ends=False):
    order = np.argsort(x, kind='stable')
    if ends:
        return x[order], np.concatenate([Y[:, :1], Y[:, 1:-1][:, order], Y[:, -1:]], axis=1)
    return x[order], Y[:, order]


@bi('spline')
def spline(nargout, *args):
    from scipy import interpolate
    nargchk(args, 2, 3, 'spline')
    x, Y, dim, isvec = _interp_data(args, 'spline')
    ends = Y.shape[-1] == x.size + 2
    x, Y = _sorted(x, Y, ends)
    if isvec and not ends and np.any(np.isnan(Y)):
        keep = ~np.isnan(Y[0])            # points with no value are left out
        x, Y = x[keep], Y[:, keep]
    if ends:
        f = interpolate.CubicSpline(x, Y[:, 1:-1], axis=1, bc_type=((1, Y[:, 0]), (1, Y[:, -1])))
    elif x.size == 2:
        f = interpolate.CubicSpline(x, Y, axis=1, bc_type='natural')
    elif x.size == 3:
        # not-a-knot through three points: the parabola through them
        f = interpolate.CubicSpline(x, Y, axis=1, bc_type='not-a-knot')
    else:
        f = interpolate.CubicSpline(x, Y, axis=1, bc_type='not-a-knot' if x.size > 3 else 'natural')
    pp = _pp_from_scipy(f, dim)
    if len(args) == 2:
        return pp
    return out(pp.eval(darr(args[2])))


@bi('pchip')
def pchip(nargout, *args):
    from scipy import interpolate
    nargchk(args, 2, 3, 'pchip')
    x, Y, dim, isvec = _interp_data(args, 'pchip')
    x, Y = _sorted(x, Y)
    f = interpolate.PchipInterpolator(x, Y, axis=1)
    pp = _pp_from_scipy(f, dim)
    if len(args) == 2:
        return pp
    return out(pp.eval(darr(args[2])))


@bi('makima')
def makima(nargout, *args):
    from scipy import interpolate
    nargchk(args, 2, 3, 'makima')
    x = darr(args[0]).reshape(-1)
    y = darr(args[1]).reshape(-1)
    if x.size < 2 or y.size != x.size:
        raise err('MATLAB:makima:XYLengthMismatch', 'x and y must be vectors of the same length, at least 2.', 'makima')
    if np.any(np.diff(np.sort(x)) == 0):
        raise err('MATLAB:makima:RepeatedX', 'The points x must be distinct.', 'makima')
    order = np.argsort(x, kind='stable')
    x, y = x[order], y[order]
    f = interpolate.Akima1DInterpolator(x, y, method='makima')
    f.extrapolate = True
    if len(args) == 2:
        return _pp_from_scipy(f, (1,))          # makima(x, y): the piecewise polynomial (Akima's is one of SciPy's)
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
    nargchk(args, 2, 3, 'mkpp')
    b = darr(args[0]).reshape(-1)
    c = darr(args[1])
    dim = tuple(int(d) for d in darr(args[2]).reshape(-1)) if len(args) > 2 else (1,)
    n = b.size - 1
    D = int(np.prod(dim))
    if n < 1 or c.size % (n * D):
        raise err('MATLAB:mkpp:PPNumberMismatchCoeffs', 'The coefficients must fit the pieces and the size of a value.', 'mkpp')
    return PP(b, c.reshape(n * D, -1, order='F'), dim)


@bi('unmkpp', nout=5)
def unmkpp(nargout, *args):
    pp = args[0]
    if not hasattr(pp, 'breaks'):
        raise err('MATLAB:unmkpp:InvalidPP', 'The input must be a piecewise polynomial (from mkpp, spline or pchip).', 'unmkpp')
    return (out(pp.breaks.reshape(1, -1)), out(pp.coefs), float(pp.breaks.size - 1), float(pp.order), pp.dim_value())[:max(nargout, 1)]


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
    if np.linalg.matrix_rank(V) < n + 1:
        p = np.linalg.lstsq(V, y, rcond=None)[0]
        R.warn('MATLAB:polyfit:RepeatedPointsOrRescale', 'Polynomial is badly conditioned. Add points with distinct X values, reduce the degree of the polynomial, or try centering and scaling as described in HELP POLYFIT.')
    else:
        # least squares through the QR factors of the Vandermonde matrix
        from scipy.linalg import solve_triangular
        p = solve_triangular(Rm, Q.conj().T @ y)
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
    """[y, delta] = polyval(p, x, S, mu): the polynomial by Horner's rule
    at x (centred and scaled by mu), and from polyfit's S the standard error
    estimate delta = normr/sqrt(df)*sqrt(1 + |A/R|^2) of each prediction."""
    nargchk(args, 2, 4, 'polyval')
    p = darr(args[0]).reshape(-1)
    x = darr(args[1])
    if len(args) > 3 and numel(args[3]):
        mu = darr(args[3]).reshape(-1)
        x = (x - mu[0]) / mu[1]
    y = np.zeros(x.shape, dtype=np.result_type(p, x, F64))
    for c in p:
        y = y * x + c
    if p.size == 0:
        y = np.zeros(x.shape)
    single = any(class_of(v) == 'single' for v in args[:2])

    def back(v):
        return finish(np.asarray(v).astype(np.complex64 if np.iscomplexobj(v) else np.float32), 'single') if single else out(v)
    if nargout < 2:
        return back(y)
    if len(args) < 3 or type(args[2]) is not Struct:
        raise err('MATLAB:polyval:RequiresS', 'The structure S from polyfit is needed for delta.', 'polyval')
    S = args[2]
    if not all(k in S.f for k in ('R', 'df', 'normr')):
        raise err('MATLAB:polyval:RequiresS', 'S must be the structure from polyfit (fields R, df and normr).', 'polyval')
    Rm = darr(S.get1('R'))
    df, normr = num(S.get1('df')), num(S.get1('normr'))
    A = np.vander(x.reshape(-1, order='F'), p.size)
    from scipy.linalg import solve_triangular
    E = solve_triangular(Rm, A.T, trans='T').T            # A / R
    e = np.sqrt(1 + np.sum(np.abs(E) ** 2, axis=1))
    delta = (np.full(e.shape, np.inf) if df == 0 else normr / math.sqrt(df) * e).reshape(x.shape, order='F')
    return back(y), back(delta)


@bi('polyvalm')
def polyvalm(nargout, *args):
    p = darr(args[0]).reshape(-1)
    X = darr(args[1])
    if X.ndim != 2 or X.shape[0] != X.shape[1]:
        raise err('MATLAB:polyvalm:NonSquareMatrix', 'The matrix must be square.', 'polyvalm')
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


def _shape_arg(args, k, default, fn):
    """The shape of a convolution's result: 'full', 'same' or 'valid'."""
    if len(args) <= k:
        return default
    s = opt_str(args[k])
    if s is None or s.lower() not in ('full', 'same', 'valid'):
        raise err(f'MATLAB:{fn}:unknownShapeParameter', "The shape is 'full', 'same' or 'valid'.", fn)
    return s.lower()


@bi('conv')
def conv(nargout, *args):
    nargchk(args, 2, 3, 'conv')
    u = darr(args[0])
    v = darr(args[1])
    shape = _shape_arg(args, 2, 'full', 'conv')
    if (u.ndim > 2 or min(u.shape) > 1) or (v.ndim > 2 or min(v.shape) > 1):
        raise err('MATLAB:conv:AorBNotVector', 'A and B must be vectors.', 'conv')
    uu, vv = u.reshape(-1), v.reshape(-1)
    if uu.size == 0 or vv.size == 0:
        return np.zeros((1, 0)) if shape != 'same' else out(np.zeros(u.shape))
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
    # the orientation of the longer vector ('same': of the first), the second's when they are as long
    lead = u if shape == 'same' or uu.size > vv.size else v
    col = lead.ndim == 2 and lead.shape[1] == 1 and lead.shape[0] > 1
    return out(r.reshape(-1, 1) if col else r.reshape(1, -1))


@bi('deconv', nout=2)
def deconv(nargout, *args):
    from scipy import signal
    y = darr(args[0])
    b = y.reshape(-1)
    a = darr(args[1]).reshape(-1)
    if a.size == 0 or a[0] == 0:
        raise err('MATLAB:deconv:ZeroCoef1', 'First coefficient of A must be non-zero.', 'deconv')
    col = y.ndim == 2 and y.shape[1] == 1 and y.shape[0] > 1
    shape = (lambda v: v.reshape(-1, 1)) if col else (lambda v: v.reshape(1, -1))
    if b.size < a.size:
        q, r = np.zeros(1), b.astype(F64)          # nothing divides: the quotient is 0, the rest is all of y
    else:
        q, r = signal.deconvolve(b, a)
    qq = out(shape(np.asarray(q, F64)))
    if nargout >= 2:
        return qq, out(shape(np.asarray(r)))
    return qq


def _pder(p):
    return np.polyder(p) if p.size > 1 else np.zeros(1)


@bi('polyder', nout=2)
def polyder(nargout, *args):
    """polyder(p); polyder(a, b) of the product a*b; [q, d] = polyder(a, b) of the quotient a/b,
    q = a'*b - a*b' (leading zeros dropped) over d = b*b."""
    nargchk(args, 1, 2, 'polyder')
    if len(args) == 2:
        a, b = darr(args[0]).reshape(-1), darr(args[1]).reshape(-1)
        if nargout < 2:
            return out(_pder(np.convolve(a, b)).reshape(1, -1))
        q = np.polysub(np.convolve(_pder(a), b), np.convolve(a, _pder(b)))
        q = np.trim_zeros(np.atleast_1d(q), 'f')
        q = q if q.size else np.zeros(1)
        return out(q.reshape(1, -1)), out(np.convolve(b, b).reshape(1, -1))
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
    """[r, p, k] = residue(b, a): the partial fractions of b(s)/a(s), a
    repeated pole's residues in increasing powers, the poles in groups by
    decreasing magnitude (SciPy's signal.residue, regrouped); [b, a] =
    residue(r, p, k) puts them back together (signal.invres)."""
    nargchk(args, 2, 3, 'residue')
    from scipy import signal
    if len(args) == 3:
        r = darr(args[0]).reshape(-1)
        p = darr(args[1]).reshape(-1)
        k = darr(args[2]).reshape(-1)
        if r.size != p.size:
            raise err('MATLAB:residue:InputSizeMismatch', 'There must be one residue per pole.', 'residue')
        b, a = signal.invres(r, p, k, tol=1e-3, rtype='avg')
        b, a = (np.real_if_close(np.asarray(v), tol=1e6) for v in (b, a))
        return (out(b.reshape(1, -1)), out(a.reshape(1, -1)))[:max(nargout, 1)] if nargout > 1 else out(b.reshape(1, -1))
    b = darr(args[0]).reshape(-1)
    a = darr(args[1]).reshape(-1)
    r, p, k = signal.residue(b, a, tol=1e-3, rtype='avg')
    # groups of equal poles (adjacent in SciPy's result), by decreasing |p|
    groups, i = [], 0
    while i < p.size:
        j = i + 1
        while j < p.size and abs(p[j] - p[i]) <= 1e-3 * max(abs(p[i]), 1):
            j += 1
        groups.append((i, j))
        i = j
    groups.sort(key=lambda g: -abs(p[g[0]]))
    order = [t for g0, g1 in groups for t in range(g0, g1)]
    r, p = r[order], p[order]
    kk = out(k.reshape(1, -1)) if k.size else np.zeros((0, 0))
    return (out(r.reshape(-1, 1)), out(p.reshape(-1, 1)), kk)[:max(nargout, 1)] if nargout > 1 else out(r.reshape(-1, 1))


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
    single = any(class_of(v) == 'single' for v in args[:3])
    if single:
        r = filter_(nargout, *[darr(v) for v in args[:3]], *args[3:])
        return tuple(finish(np.asarray(v), 'single') for v in r) if isinstance(r, tuple) else finish(np.asarray(r), 'single')
    X = expand_dims(x, dim)
    if X.size == 0:
        n = max(a.size, b.size) - 1
        y = out(np.zeros(X.shape, np.result_type(X.dtype, b.dtype, a.dtype, F64)))
        return (y, out(np.zeros((n, 0)))) if nargout >= 2 else y
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
    nargchk(args, 2, 3, 'filter2')
    h = darr(args[0])
    x = darr(args[1])
    shape = _shape_arg(args, 2, 'same', 'filter2')
    if h.ndim != 2 or x.ndim != 2:
        raise err('MATLAB:filter2:NotMatrix', 'The filter and the data must be matrices.', 'filter2')
    return out(signal.correlate2d(x, h, mode=shape))


def _conv_cut(full, sa, sb, shape, fn):
    """The part of a full convolution that 'same' (the size of A, from
    floor(size(B)/2)) or 'valid' (the size of A less that of B, plus 1,
    perhaps empty) keeps."""
    if shape == 'full':
        return full
    idx = []
    for d in range(full.ndim):
        a_, b_ = sa[d] if d < len(sa) else 1, sb[d] if d < len(sb) else 1
        if shape == 'same':
            idx.append(slice(b_ // 2, b_ // 2 + a_))
        elif shape == 'valid':
            n = max(a_ - b_ + 1, 0) if b_ > 0 else 0
            idx.append(slice(b_ - 1, b_ - 1 + n))
        else:
            raise err(f'MATLAB:{fn}:unknownShapeParameter', "The shape is 'full', 'same' or 'valid'.", fn)
    return full[tuple(idx)]


def _conv_full(A, B):
    from scipy import signal
    if A.size == 0 or B.size == 0:
        return np.zeros(tuple(max(a + b - 1, 0) for a, b in zip(A.shape, B.shape)), np.result_type(A.dtype, B.dtype, F64))
    return signal.convolve(A, B, mode='full', method='direct')


def _conv_class(r, *vals):
    return finish(r, 'single') if any(class_of(v) == 'single' for v in vals) else out(r)


@bi('conv2')
def conv2(nargout, *args):
    nargchk(args, 2, 4, 'conv2')
    if len(args) >= 3 and opt_str(args[2]) is None:
        # conv2(u, v, A): down the columns with u, then along the rows with v
        u = darr(args[0]).reshape(-1, 1)
        v = darr(args[1]).reshape(1, -1)
        A = darr(args[2])
        shape = opt_lower(args[3]) if len(args) > 3 else 'full'
        full = _conv_full(_conv_full(A, u), v)
        return _conv_class(_conv_cut(full, A.shape, (u.size, v.size), shape, 'conv2'), *args[:3])
    A, B = darr(args[0]), darr(args[1])
    if A.ndim > 2 or B.ndim > 2:
        raise err('MATLAB:conv2:InputMustBe2D', 'conv2 takes 2-D arrays (convn takes more dimensions).', 'conv2')
    shape = opt_lower(args[2]) if len(args) > 2 else 'full'
    return _conv_class(_conv_cut(_conv_full(A, B), A.shape, B.shape, shape, 'conv2'), args[0], args[1])


@bi('convn')
def convn(nargout, *args):
    nargchk(args, 2, 3, 'convn')
    A, B = darr(args[0]), darr(args[1])
    nd = max(A.ndim, B.ndim)
    A2 = A.reshape(A.shape + (1,) * (nd - A.ndim))
    B2 = B.reshape(B.shape + (1,) * (nd - B.ndim))
    shape = _shape_arg(args, 2, 'full', 'convn')
    return _conv_class(_conv_cut(_conv_full(A2, B2), A2.shape, B2.shape, shape, 'convn'), args[0], args[1])


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


def _grad_along(f, h, axis):
    """The differences of f along axis: one-sided at the ends, central inside,
    (f(i+1) - f(i-1))/(x(i+1) - x(i-1)), with h a spacing or the coordinates."""
    f = np.moveaxis(f, axis, 0)
    n = f.shape[0]
    g = np.zeros(f.shape, np.result_type(f.dtype, F64))
    if n > 1:
        x = h * np.arange(n, dtype=F64) if np.ndim(h) == 0 else np.asarray(h, F64).reshape(-1)
        if x.size != n:
            raise err('MATLAB:gradient:InvalidGridSpacing', 'The coordinates must be as many as the points along their dimension.', 'gradient')
        sh = (-1,) + (1,) * (f.ndim - 1)
        g[0] = (f[1] - f[0]) / (x[1] - x[0])
        g[-1] = (f[-1] - f[-2]) / (x[-1] - x[-2])
        if n > 2:
            g[1:-1] = (f[2:] - f[:-2]) / (x[2:] - x[:-2]).reshape(sh)
    return np.moveaxis(g, 0, axis)


@bi('gradient', nout=99)
def gradient(nargout, *args):
    """[FX, FY, FZ, ...] = gradient(F, h) or gradient(F, hx, hy, ...): x is
    the second dimension, y the first, then the third and on; a vector has
    one gradient, along itself."""
    nargchk(args, 1, None, 'gradient')
    f = darr(args[0])
    f = f.astype(F64) if f.dtype.kind not in 'fc' else f
    hs = [num(a) if numel(a) == 1 else darr(a).reshape(-1) for a in args[1:]]
    if f.ndim == 2 and (f.shape[0] == 1 or f.shape[1] == 1):
        h = hs[0] if hs else 1.0
        axis = 1 if f.shape[0] == 1 else 0
        return out(_grad_along(f, h, axis))
    nd = f.ndim
    order = [1, 0] + list(range(2, nd))          # x, y, then the rest
    if len(hs) == 1:
        hs = hs * nd
    elif not hs:
        hs = [1.0] * nd
    elif len(hs) != nd:
        raise err('MATLAB:gradient:InvalidInputs', 'Give one spacing, or one for each dimension.', 'gradient')
    k = max(1, nargout)
    if k > nd:
        raise err('MATLAB:maxlhs', 'Too many output arguments.', 'gradient')
    res = [out(_grad_along(f, hs[i], order[i])) for i in range(k)]
    return res[0] if k == 1 else tuple(res)


def _second_diff(f, h, axis):
    """Second differences of f along axis, extended past the inner points
    linearly (constantly when there is only one inner point)."""
    f = np.moveaxis(f, axis, 0)
    n = f.shape[0]
    D = np.zeros(f.shape, np.result_type(f.dtype, F64))
    if n >= 3:
        x = h * np.arange(n, dtype=F64) if np.ndim(h) == 0 else np.asarray(h, F64).reshape(-1)
        if x.size != n:
            raise err('MATLAB:del2:InvalidGridSpacing', 'The coordinates must be as many as the points along their dimension.', 'del2')
        sh = (-1,) + (1,) * (f.ndim - 1)
        dl, dr = (x[1:-1] - x[:-2]).reshape(sh), (x[2:] - x[1:-1]).reshape(sh)
        D[1:-1] = 2 * ((f[2:] - f[1:-1]) / dr - (f[1:-1] - f[:-2]) / dl) / (dl + dr)
        if n == 3:
            D[0], D[-1] = D[1], D[1]
        else:
            D[0] = 2 * D[1] - D[2]
            D[-1] = 2 * D[-2] - D[-3]
    return np.moveaxis(D, 0, axis)


@bi('del2')
def del2(nargout, *args):
    """The discrete Laplacian over 2N in N dimensions (over 4 for a vector):
    the second differences along each dimension, summed; spacings as for
    gradient (x the second dimension, y the first)."""
    nargchk(args, 1, None, 'del2')
    f = darr(args[0])
    f = f.astype(F64) if f.dtype.kind not in 'fc' else f
    hs = [num(a) if numel(a) == 1 else darr(a).reshape(-1) for a in args[1:]]
    if f.ndim == 2 and (f.shape[0] == 1 or f.shape[1] == 1):
        h = hs[0] if hs else 1.0
        return out(_second_diff(f, h, 1 if f.shape[0] == 1 else 0) / 4)
    nd = f.ndim
    order = [1, 0] + list(range(2, nd))
    if not hs:
        hs = [1.0] * nd
    elif len(hs) == 1:
        hs = hs * nd
    elif len(hs) != nd:
        raise err('MATLAB:del2:InvalidInputs', 'Give one spacing, or one for each dimension.', 'del2')
    L = sum(_second_diff(f, hs[k], order[k]) for k in range(nd))
    return out(L / (2 * nd))
