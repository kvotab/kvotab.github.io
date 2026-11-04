"""Splines of the curve-fitting kind: the cubic smoothing spline (csaps,
by Reinsch's method), the smoothing spline within a tolerance (spaps),
interpolating splines of any order (spapi), the B-form (spmak), and what
works on either form (fnval, fnder, fnint, fnplt, fnbrk)."""
import math

import numpy as np

from . import bi as _register
from ._util import err, nargchk, darr, out, is_str
from ..values import MError, Obj, Char, numel, py_str
from .. import runtime as R
from .funfun import PP


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                raise err(f'SPLINES:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0]) from None
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _outs(nargout, *vals):
    return vals[:max(nargout, 1)] if nargout > 1 else vals[0]


class BForm(Obj):
    """A spline in B-form: knots, coefs (dim components by number), order."""
    __slots__ = ('knots', 'coefs', 'order', 'dim')
    cls = 'struct'

    def __init__(self, knots, coefs, order, dim=1):
        self.knots = np.asarray(knots, float).reshape(-1)
        self.coefs = np.atleast_2d(np.asarray(coefs, float))
        self.order = int(order)
        self.dim = int(dim)

    def number(self):
        return self.coefs.shape[1]

    def bspline(self):
        from scipy.interpolate import BSpline
        return BSpline(self.knots, self.coefs.T, self.order - 1, extrapolate=True)

    def getprop(self, name):
        if name == 'form':
            return Char.of('B-')
        if name == 'knots':
            return out(self.knots.reshape(1, -1))
        if name == 'coefs':
            return out(self.coefs)
        if name == 'number':
            return float(self.number())
        if name == 'order':
            return float(self.order)
        if name == 'dim':
            return float(self.dim)
        return super().getprop(name)

    def propnames(self):
        return ['form', 'knots', 'coefs', 'number', 'order', 'dim']

    def display_lines(self):
        return ['  struct with fields:', '', "     form: 'B-'", f'    knots: [1×{self.knots.size} double]',
                f'    coefs: [{self.coefs.shape[0]}×{self.coefs.shape[1]} double]', f'   number: {self.number()}',
                f'    order: {self.order}', f'      dim: {self.dim}']

    def eval(self, xq):
        xq = np.asarray(xq, float)
        v = self.bspline()(xq.reshape(-1, order='F'))
        v = np.asarray(v).reshape(xq.size, -1).T
        if self.dim == 1:
            return v.reshape(xq.shape, order='F')
        return v

    def interval(self):
        k = self.order
        return self.knots[k - 1], self.knots[-k]


def _form(v, fn):
    if isinstance(v, (PP, BForm)):
        return v
    raise err(f'SPLINES:{fn}:form', f'{fn} takes a spline (pp-form or B-form).', fn)


def _to_pp(f):
    """A B-form as a pp-form over its basic interval: each piece's coefficients the spline's derivatives at its left break (from the right) over m!."""
    if isinstance(f, PP):
        return f
    from scipy.interpolate import BSpline
    a, b = f.interval()
    br = np.unique(f.knots[(f.knots >= a) & (f.knots <= b)])
    k, D = f.order, f.dim
    coefs = np.zeros(((br.size - 1) * D, k))
    for d in range(D):
        bs = BSpline(f.knots, f.coefs[d], k - 1)
        for m in range(k):
            coefs[d::D, k - 1 - m] = (bs.derivative(m) if m else bs)(br[:-1]) / math.factorial(m)
    return PP(br, coefs, (D,))


# ---- smoothing splines ----------------------------------------------------------------------------------------------------------

def _merge(x, Y, w):
    """Sites sorted, equal ones merged: the weighted mean of their values, their weights summed."""
    order = np.argsort(x, kind='stable')
    x, Y, w = x[order], Y[:, order], w[order]
    keep = np.concatenate([[True], np.diff(x) > 0])
    if keep.all():
        return x, Y, w
    groups = np.cumsum(keep) - 1
    n = int(groups[-1]) + 1
    W = np.bincount(groups, w, n)
    Ym = np.vstack([np.bincount(groups, w * Y[d], n) / W for d in range(Y.shape[0])])
    return x[keep], Ym, W


def _reinsch(x, Y, w, lam):
    """The natural cubic smoothing spline minimizing sum(w*(y - g)^2) + lam*int(g''^2): its values g and second derivatives at x."""
    from scipy import sparse
    from scipy.sparse.linalg import spsolve
    n = x.size
    h = np.diff(x)
    if n == 2 or not np.isfinite(lam):
        # the weighted least-squares line
        A = np.column_stack([np.ones(n), x])
        G = np.zeros_like(Y)
        for d in range(Y.shape[0]):
            c = np.linalg.lstsq(A * np.sqrt(w)[:, None], Y[d] * np.sqrt(w), rcond=None)[0]
            G[d] = A @ c
        return G, np.zeros_like(Y)
    m = n - 2
    i = np.arange(m)
    Q = sparse.csc_matrix((np.concatenate([1 / h[:-1], -1 / h[:-1] - 1 / h[1:], 1 / h[1:]]),
                           (np.concatenate([i, i + 1, i + 2]), np.concatenate([i, i, i]))), shape=(n, m))
    Rm = sparse.diags([h[1:-1] / 6, (h[:-1] + h[1:]) / 3, h[1:-1] / 6], [-1, 0, 1], shape=(m, m), format='csc')
    Wi = sparse.diags(1 / w)
    A = (Rm + lam * (Q.T @ Wi @ Q)).tocsc()
    G = np.zeros_like(Y)
    Gam = np.zeros_like(Y)
    for d in range(Y.shape[0]):
        gamma = np.atleast_1d(spsolve(A, Q.T @ Y[d]))
        G[d] = Y[d] - lam * (Wi @ (Q @ gamma))
        Gam[d, 1:-1] = gamma
    return G, Gam


def _pp_of(x, G, Gam):
    """The pp form of the natural cubic spline with values G and second derivatives Gam at x."""
    D, n = G.shape
    h = np.diff(x)
    coefs = np.zeros(((n - 1) * D, 4))
    for d in range(D):
        g, c2 = G[d], Gam[d]
        a = g[:-1]
        b = (g[1:] - g[:-1]) / h - h * (2 * c2[:-1] + c2[1:]) / 6
        c = c2[:-1] / 2
        dd = (c2[1:] - c2[:-1]) / (6 * h)
        coefs[d::D] = np.column_stack([dd, c, b, a])
    return PP(x, coefs, (D,))


def _xy(args, fn):
    x = np.asarray(darr(args[0]), float).reshape(-1)
    y = np.asarray(darr(args[1]), float)
    isvec = y.ndim < 2 or 1 in y.shape
    Y = y.reshape(1, -1) if isvec else y
    if Y.shape[1] != x.size:
        raise err(f'SPLINES:{fn}:size', 'y must have a value (column) for each site x.', fn)
    if x.size < 2:
        raise err(f'SPLINES:{fn}:few', 'There must be at least two sites.', fn)
    return x, Y


@bi('csaps', nout=2)
def csaps(nargout, *args):
    """pp = csaps(x, y), csaps(x, y, p), values = csaps(x, y, p, xx), csaps(x, y, p, [], w), [pp, p] = csaps(...): the cubic smoothing spline minimizing p*sum(w.*(y - f(x)).^2) + (1-p)*int(f''^2): p 1 interpolates (the natural spline), p 0 is the least-squares line; p 1/(1 + h^3/6) unless given (h the average spacing of x). Equal sites are merged. Reinsch's method."""
    nargchk(args, 2, 5, 'csaps')
    x, Y = _xy(args, 'csaps')
    w = np.asarray(darr(args[4]), float).reshape(-1) if len(args) > 4 and numel(args[4]) else np.ones(x.size)
    xs, Ys, ws = _merge(x, Y, w)
    if len(args) > 2 and numel(args[2]):
        p = float(np.asarray(darr(args[2]), float).reshape(-1)[0])
    else:
        hbar = (xs[-1] - xs[0]) / max(xs.size - 1, 1)
        p = 1 / (1 + hbar ** 3 / 6)
    if not 0 <= p <= 1:
        raise err('SPLINES:csaps:p', 'The smoothing parameter p is from 0 to 1.', 'csaps')
    lam = math.inf if p == 0 else (1 - p) / p
    G, Gam = _reinsch(xs, Ys, ws, lam)
    pp = _pp_of(xs, G, Gam)
    if len(args) > 3 and numel(args[3]):
        vals = pp.eval(np.asarray(darr(args[3]), float))
        return _outs(nargout, out(np.asarray(vals)), p)
    return _outs(nargout, pp, p)


@bi('spaps', nout=3)
def spaps(nargout, *args):
    """[sp, values, rho] = spaps(x, y, tol, w): the roughest-penalty-smallest cubic spline (pp-form here) with sum(w.*(y - f(x)).^2) <= tol: the smoothing spline whose error is tol (the least-squares line when even that is within tol, the interpolant when tol is 0); rho the weight of the error (1/lambda); values f at x."""
    nargchk(args, 3, 5, 'spaps')
    x, Y = _xy(args, 'spaps')
    tol = float(np.asarray(darr(args[2]), float).reshape(-1)[0])
    w = np.asarray(darr(args[3]), float).reshape(-1) if len(args) > 3 and numel(args[3]) else np.ones(x.size)
    xs, Ys, ws = _merge(x, Y, w)

    def error(lam):
        G, _ = _reinsch(xs, Ys, ws, lam)
        return float(np.sum(ws * (Ys - G) ** 2))
    if tol <= 0:
        lam = 0.0
    elif error(math.inf) <= tol:
        lam = math.inf
    else:
        from scipy.optimize import brentq
        lo, hi = -30.0, 30.0
        while error(10 ** hi) < tol and hi < 60:
            hi += 10
        lam = 10 ** brentq(lambda t: error(10 ** t) - tol, lo, hi, xtol=1e-12)
    G, Gam = _reinsch(xs, Ys, ws, lam)
    pp = _pp_of(xs, G, Gam)
    vals = pp.eval(x if Y.shape[0] == 1 else x)
    rho = math.inf if lam == 0 else (0.0 if not math.isfinite(lam) else 1 / lam)
    return _outs(nargout, pp, out(np.atleast_2d(vals)), rho)


@bi('spapi')
def spapi(nargout, *args):
    """sp = spapi(k, x, y): the spline of order k (degree k-1) through the points (B-form; its knots SciPy's make_interp_spline chooses), or with the knot sequence k given (as many knots as points plus the order). Values = spapi(k, x, y, xx)."""
    nargchk(args, 3, 4, 'spapi')
    from scipy.interpolate import make_interp_spline
    kk = np.asarray(darr(args[0]), float).reshape(-1)
    x, Y = _xy(args[1:], 'spapi')
    order = np.argsort(x, kind='stable')
    x, Y = x[order], Y[:, order]
    if kk.size == 1:
        k = int(kk[0])
        if not 1 <= k <= x.size:
            raise err('SPLINES:spapi:order', f'The order is from 1 to the number of points ({x.size}).', 'spapi')
        s = make_interp_spline(x, Y.T, k=k - 1)
    else:
        knots = np.sort(kk)
        k = knots.size - x.size
        if k < 1:
            raise err('SPLINES:spapi:knots', 'The knot sequence has as many knots as points plus the order.', 'spapi')
        s = make_interp_spline(x, Y.T, k=k - 1, t=knots)
    b = BForm(s.t, np.asarray(s.c).reshape(s.c.shape[0], -1).T, k, Y.shape[0])
    if len(args) > 3:
        return out(np.asarray(b.eval(np.asarray(darr(args[3]), float))))
    return b


@bi('spmak')
def spmak(nargout, *args):
    """sp = spmak(knots, coefs): the spline in B-form with these knots and B-spline coefficients (a column for each B-spline; rows for vector values); its order is the number of knots less the number of coefficients."""
    nargchk(args, 2, 2, 'spmak')
    t = np.sort(np.asarray(darr(args[0]), float).reshape(-1))
    c = np.atleast_2d(np.asarray(darr(args[1]), float))
    k = t.size - c.shape[1]
    if k < 1:
        raise err('SPLINES:spmak:knots', 'There must be more knots than coefficients.', 'spmak')
    return BForm(t, c, k, c.shape[0])


# ---- what works on either form ----------------------------------------------------------------------------------------------------

@bi('fnval')
def fnval(nargout, *args):
    """v = fnval(f, x): the spline f (pp-form or B-form) at x."""
    nargchk(args, 2, 3, 'fnval')
    f, x = (args[0], args[1]) if isinstance(args[0], (PP, BForm)) else (args[1], args[0])
    f = _form(f, 'fnval')
    return out(np.asarray(f.eval(np.asarray(darr(x), float))))


@bi('fnder')
def fnder(nargout, *args):
    """fprime = fnder(f, dorder): the derivative of order dorder (1) of a spline, in the same form (a negative order integrates)."""
    nargchk(args, 1, 2, 'fnder')
    f = _form(args[0], 'fnder')
    d = int(np.asarray(darr(args[1]), float).reshape(-1)[0]) if len(args) > 1 else 1
    if d < 0:
        for _ in range(-d):
            f = _integral(f, 0.0)
        return f
    if isinstance(f, BForm):
        from scipy.interpolate import BSpline
        rows = []
        bs = None
        for c in f.coefs:
            bs = BSpline(f.knots, c, f.order - 1).derivative(d) if d < f.order else None
            rows.append(bs.c[:bs.t.size - bs.k - 1] if bs is not None else None)
        if bs is None:
            return BForm(f.knots[[0, -1]], np.zeros((f.dim, 1)), 1, f.dim)
        return BForm(bs.t, np.vstack(rows), f.order - d, f.dim)
    c = f.coefs.astype(float)
    k = f.order
    for _ in range(d):
        if k <= 1:
            c = np.zeros((c.shape[0], 1))
            break
        c = c[:, :-1] * np.arange(k - 1, 0, -1)[None, :]
        k -= 1
    return PP(f.breaks, c, f.dim)


def _integral(f, value):
    if isinstance(f, BForm):
        from scipy.interpolate import BSpline
        rows = []
        bs = None
        for c in f.coefs:
            bs = BSpline(f.knots, c, f.order - 1).antiderivative(1)
            a = f.interval()[0]
            rows.append(bs.c[:bs.t.size - bs.k - 1] - bs(a) + value)
        return BForm(bs.t, np.vstack(rows), f.order + 1, f.dim)
    D = f.ncomp()
    k = f.order
    b = f.breaks
    c = np.hstack([f.coefs / np.arange(k, 0, -1)[None, :], np.zeros((f.coefs.shape[0], 1))])
    # each piece's constant: the integral up to its start
    acc = np.full(D, float(value))
    for i in range(b.size - 1):
        rows = slice(i * D, (i + 1) * D)
        c[rows, -1] = acc
        h = b[i + 1] - b[i]
        acc = np.array([np.polyval(c[i * D + dd], h) for dd in range(D)])
    return PP(b, c, f.dim)


@bi('fnint')
def fnint(nargout, *args):
    """intgrf = fnint(f, value): the indefinite integral of a spline, value (0) at the left end of its basic interval, in the same form."""
    nargchk(args, 1, 2, 'fnint')
    f = _form(args[0], 'fnint')
    v = float(np.asarray(darr(args[1]), float).reshape(-1)[0]) if len(args) > 1 else 0.0
    return _integral(f, v)


def _interval(f):
    return (f.breaks[0], f.breaks[-1]) if isinstance(f, PP) else f.interval()


@bi('fnplt', nout=1)
def fnplt(nargout, *args):
    """fnplt(f), fnplt(f, symbol, interval, linewidth), points = fnplt(f, ...): the spline drawn over its basic interval (or interval); points the curve's points, a row of x and a row for each component."""
    nargchk(args, 1, 5, 'fnplt')
    f = _form(args[0], 'fnplt')
    sym, rng_, lw = None, None, None
    for a in args[1:]:
        if is_str(a):
            sym = py_str(a)
        elif numel(a) == 2:
            rng_ = np.asarray(darr(a), float).reshape(-1)
        elif numel(a) == 1:
            lw = float(np.asarray(darr(a), float).reshape(-1)[0])
    a, b = rng_ if rng_ is not None else _interval(f)
    xs = np.linspace(a, b, 301)
    brk = f.breaks if isinstance(f, PP) else np.unique(f.knots)
    xs = np.unique(np.concatenate([xs, brk[(brk >= a) & (brk <= b)]]))
    v = np.atleast_2d(np.asarray(f.eval(xs.reshape(1, -1))))
    pts = np.vstack([xs.reshape(1, -1), v.reshape(-1, xs.size)])
    if nargout:
        return out(pts)
    extra = [Char.of(sym)] if sym else []
    if lw:
        extra += [Char.of('LineWidth'), lw]
    if pts.shape[0] == 2:
        R._builtin('plot', out(pts[0:1].T), out(pts[1:2].T), *extra)
    elif pts.shape[0] == 3:
        R._builtin('plot', out(pts[1:2].T), out(pts[2:3].T), *extra)
    else:
        R._builtin('plot3', out(pts[1:2].T), out(pts[2:3].T), out(pts[3:4].T), *extra)
    return None


@bi('fnbrk', nout=5)
def fnbrk(nargout, *args):
    """fnbrk(f, part): a part of a spline: 'breaks', 'coefs', 'pieces', 'order', 'dim', 'interval', and for a B-form 'knots' and 'number'; [breaks, coefs, pieces, order, dim] = fnbrk(pp) (knots, coefs, number, order, dim of a B-form)."""
    nargchk(args, 1, 2, 'fnbrk')
    f = _form(args[0], 'fnbrk')
    if len(args) == 1:
        if isinstance(f, PP):
            return _outs(nargout, f.getprop('breaks'), f.getprop('coefs'), f.getprop('pieces'), f.getprop('order'), f.getprop('dim'))
        return _outs(nargout, f.getprop('knots'), f.getprop('coefs'), f.getprop('number'), f.getprop('order'), f.getprop('dim'))
    part = py_str(args[1]).lower()
    if part.startswith('int'):
        a, b = _interval(f)
        return out(np.array([[a, b]]))
    names = {'b': 'breaks', 'c': 'coefs', 'p': 'pieces', 'o': 'order', 'd': 'dim', 'k': 'knots', 'n': 'number'}
    key = names.get(part[:1])
    if key is None:
        raise err('SPLINES:fnbrk:part', "The part is 'breaks', 'coefs', 'pieces', 'order', 'dim', 'interval', 'knots' or 'number'.", 'fnbrk')
    if isinstance(f, BForm) and key in ('breaks', 'pieces'):
        f = _to_pp(f)
    if isinstance(f, PP) and key in ('knots', 'number'):
        raise err('SPLINES:fnbrk:part', f"A pp-form has no '{key}'.", 'fnbrk')
    return f.getprop(key)

