"""Small fill-ins: the sine and cosine integrals, Dawson's integral and the
Fresnel integrals (SciPy's special functions, SymPy's for symbolic
input); the characteristic and minimal polynomials and the Jordan form
(exact, by SymPy); quadv."""
import numpy as np

from . import bi as _register
from ._util import err, nargchk, darr, out, is_str
from ..values import MError, FH, numel, py_str
from .. import runtime as R


def bi(*names, **kw):
    def deco(f):
        if kw.get('aw'):
            async def g(*a):
                try:
                    return await f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0]) from None
        else:
            def g(*a):
                try:
                    return f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0]) from None
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _is_sym(v):
    from ..symbolic import Sym
    return isinstance(v, Sym)


def _special(name, fn, symname):
    """An elementwise special function: SciPy's on numbers, SymPy's on symbolic input."""
    def f(nargout, *args):
        nargchk(args, 1, 1, name)
        v = args[0]
        if _is_sym(v):
            from ..symbolic import Sym, sp
            s = sp()
            g = symname(s)
            return Sym(np.vectorize(lambda e: g(e), otypes=[object])(v.a))
        a = darr(v, name)
        if a.dtype.kind not in 'fciub':
            raise err(f'MATLAB:{name}:input', f'{name} takes numbers.', name)
        r = fn(a.astype(complex) if np.iscomplexobj(a) else a.astype(float))
        return out(np.real_if_close(r, tol=0) if np.iscomplexobj(r) and not np.any(np.imag(r)) else r)
    f.__name__ = name
    f.__doc__ = f'{name}(x): elementwise.'
    return f


def _sinint(x):
    from scipy.special import sici
    return sici(x)[0]


def _cosint(x):
    from scipy.special import sici
    if not np.iscomplexobj(x) and np.any(x < 0):
        r = sici(x.astype(complex))[1]
        return np.where(x == 0, -np.inf, r)
    return sici(x)[1]


def _dawson(x):
    from scipy.special import dawsn
    return dawsn(x)


def _fresnels(x):
    from scipy.special import fresnel
    return fresnel(x)[0]


def _fresnelc(x):
    from scipy.special import fresnel
    return fresnel(x)[1]


for _n, _f, _s in (('sinint', _sinint, lambda s: s.Si), ('cosint', _cosint, lambda s: s.Ci), ('dawson', _dawson, None),
                   ('fresnels', _fresnels, lambda s: s.fresnels), ('fresnelc', _fresnelc, lambda s: s.fresnelc)):
    if _s is None:
        def _s(s):
            return lambda e: s.sqrt(s.pi) / 2 * s.exp(-e ** 2) * s.erfi(e)
    bi(_n, arr=True)(_special(_n, _f, _s))


# ---- polynomials of matrices, the Jordan form ----------------------------------------------------------------------------------

async def _matrix(v, fn):
    """A square matrix as a SymPy Matrix (numbers as sym() makes them), and whether the input was symbolic."""
    from .. import symbolic as Y
    s = await Y.ensure()
    sym = _is_sym(v)
    if not sym:
        # logical and text become numbers, as sym makes them from double
        d = darr(v, fn)
        v = out(d.astype(complex) if np.iscomplexobj(d) else d.astype(float))
    a = Y.arr_of(v)
    if a.ndim != 2 or a.shape[0] != a.shape[1]:
        raise err(f'symbolic:{fn}:square', f'{fn} takes a square matrix.', fn)
    return s.Matrix(a.tolist()), sym, s


def _result(M, sym):
    from .. import symbolic as Y
    from ..symbolic import Sym
    arr = Y._np(M) if hasattr(M, 'shape') else np.array([[M]], object)
    if sym:
        return Sym(arr)
    vals = np.array([[complex(e.evalf(20)) for e in row] for row in arr], complex) if arr.size else np.zeros(arr.shape)
    return out(np.real_if_close(vals, tol=1e3) if not np.any(np.abs(vals.imag) > 1e-12 * max(1.0, float(np.max(np.abs(vals))) if vals.size else 1.0)) else vals)


def _poly_args(args, fn):
    var = None
    if len(args) > 1:
        from ..symbolic import Sym
        if not isinstance(args[1], Sym):
            raise err(f'symbolic:{fn}:var', 'The variable must be symbolic.', fn)
        var = args[1].a.reshape(-1)[0]
    return var


@bi('charpoly', aw=True, arr=False)
async def charpoly(nargout, *args):
    """p = charpoly(A): the coefficients of det(x*I - A), highest power first (exact); charpoly(A, x): the polynomial in x."""
    nargchk(args, 1, 2, 'charpoly')
    M, sym, s = await _matrix(args[0], 'charpoly')
    var = _poly_args(args, 'charpoly')
    P = M.charpoly()
    if var is not None:
        from ..symbolic import Sym
        return Sym(np.array([[P.as_expr().subs(P.gen, var)]], object))
    c = s.Matrix([P.all_coeffs()])
    return _result(c, sym or False)


def _jordan(M, s):
    P, J = M.jordan_form()
    return P, J


@bi('minpoly', aw=True, arr=False)
async def minpoly(nargout, *args):
    """p = minpoly(A): the coefficients of the minimal polynomial of A, highest power first: the product over the eigenvalues of (x - lambda)^k, k the largest Jordan block of each (exact); minpoly(A, x): the polynomial in x."""
    nargchk(args, 1, 2, 'minpoly')
    M, sym, s = await _matrix(args[0], 'minpoly')
    var = _poly_args(args, 'minpoly')
    _, J = _jordan(M, s)
    n = J.shape[0]
    blocks = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and J[j, j + 1] == 1 and s.simplify(J[j + 1, j + 1] - J[i, i]) == 0:
            j += 1
        ev = J[i, i]
        key = next((k for k in blocks if s.simplify(k - ev) == 0), ev)
        blocks[key] = max(blocks.get(key, 0), j - i + 1)
        i = j + 1
    x = s.Dummy('x')
    expr = s.Integer(1)
    for ev, k in blocks.items():
        expr *= (x - ev) ** k
    P = s.Poly(s.expand(expr), x)
    if var is not None:
        from ..symbolic import Sym
        return Sym(np.array([[s.simplify(P.as_expr().subs(x, var))]], object))
    c = s.Matrix([[s.nsimplify(s.simplify(cf)) for cf in P.all_coeffs()]])
    return _result(c, sym)


@bi('jordan', nout=2, aw=True, arr=False)
async def jordan(nargout, *args):
    """J = jordan(A), [V, J] = jordan(A): the Jordan form, A*V = V*J (exact, by SymPy; numbers come back as numbers)."""
    nargchk(args, 1, 1, 'jordan')
    M, sym, s = await _matrix(args[0], 'jordan')
    P, J = _jordan(M, s)
    if nargout <= 1:
        return _result(J, sym)
    return _result(P, sym), _result(J, sym)


# ---- quadv ---------------------------------------------------------------------------------------------------------------------------

@bi('quadv', nout=2, aw=True, arr=False)
async def quadv(nargout, *args):
    """[Q, fcnt] = quadv(fun, a, b, tol): the integral of an array-valued function by adaptive Simpson quadrature, every element to within tol (1e-6) in the largest error."""
    nargchk(args, 3, 5, 'quadv')
    f = args[0]
    if is_str(f):
        f = R.NamedFH(py_str(f))
    if not isinstance(f, FH):
        raise err('MATLAB:quadv:fun', 'The integrand must be a function handle.', 'quadv')
    a, b = float(np.asarray(darr(args[1])).reshape(-1)[0]), float(np.asarray(darr(args[2])).reshape(-1)[0])
    tol = float(np.asarray(darr(args[3])).reshape(-1)[0]) if len(args) > 3 and numel(args[3]) else 1e-6
    extra = args[5:]
    count = [0]
    shape = [None]

    async def F(x):
        count[0] += 1
        v = np.asarray(darr(await f.acall(1, float(x), *extra)), float)
        if shape[0] is None:
            shape[0] = v.shape
        elif v.shape != shape[0]:
            raise err('MATLAB:quadv:size', 'The integrand must return arrays of one size.', 'quadv')
        if R.tk():
            await R.H(None, 0, '')
        return v
    if a == b:
        v = await F(a)
        return (out(np.zeros_like(v)), float(count[0])) if nargout > 1 else out(np.zeros_like(v))
    # Simpson on the interval, then halves until each panel's two halves agree to within its share of tol
    fa, fm, fb = await F(a), await F((a + b) / 2), await F(b)

    async def step(lo, hi, flo, fmid, fhi, whole, depth, tl):
        mid = (lo + hi) / 2
        f1, f2 = await F((lo + mid) / 2), await F((mid + hi) / 2)
        h = (hi - lo) / 12
        left = h * (flo + 4 * f1 + fmid)
        right = h * (fmid + 4 * f2 + fhi)
        both = left + right
        if depth > 50 or count[0] > 10000:
            return both
        if np.max(np.abs(both - whole), initial=0.0) <= 15 * tl:
            return both + (both - whole) / 15
        return (await step(lo, mid, flo, f1, fmid, left, depth + 1, tl / 2)) + (await step(mid, hi, fmid, f2, fhi, right, depth + 1, tl / 2))
    whole = (b - a) / 6 * (fa + 4 * fm + fb)
    Q = await step(a, b, fa, fm, fb, whole, 0, tol)
    Q = np.asarray(Q, float)
    if count[0] > 10000:
        R.warn('MATLAB:quadv:MaxFcnCount', 'Maximum function count exceeded; singularity likely.')
    res = out(Q if Q.ndim else np.array([[float(Q)]]))
    return (res, float(count[0])) if nargout > 1 else res

