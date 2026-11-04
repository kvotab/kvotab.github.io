"""Surface fitting: fit([x y], z, type) gives an sfit, a surface z = f(x, y).

Library models: poly00 to poly55 (degree i in x and j in y, no term of a
total degree above the larger), lowess and loess (local linear and
quadratic regression), the interpolants linearinterp, nearestinterp,
cubicinterp, biharmonicinterp and thinplateinterp; and models written as
text in x and y or as anonymous functions of the coefficients, x and y.
Least squares, bounds, weights, exclusions and robust fitting go through
curvefit's own fitting. sfit and cfit also make a fit from a fittype and
coefficients; excludedata picks points to leave out of a fit.
"""
import math
import re

import numpy as np

from . import bi, REG
from ._util import err, nargchk, darr, out, opt_str, is_str, num
from ..values import MError, Obj, Char, Cell, Struct, FH, EMPTY, numel, py_str
from .. import runtime as R
from . import curvefit as CF


# ---- models of two variables -----------------------------------------------------------------------------------------------

class Model2:
    """A surface model: f(c, XY) with XY n-by-2, its coefficients and text."""

    def __init__(self, name, kind, coeffs, text, fn, linear=None, start=None, indep=('x', 'y'), dep='z', fh=None):
        self.name, self.kind, self.coeffs, self.text = name, kind, coeffs, text
        self.fn, self.linear, self.start = fn, linear, start
        self.indep, self.dep, self.fh = tuple(indep), dep, fh

    def label(self):
        if self.kind == 'poly':
            return f'Linear model {self.name[0].upper()}{self.name[1:]}:'
        if self.kind == 'interp':
            return {'linearinterp': 'Linear interpolant:', 'nearestinterp': 'Nearest neighbor interpolant:', 'cubicinterp': 'Cubic interpolant:',
                    'biharmonicinterp': 'Biharmonic interpolant:', 'thinplateinterp': 'Thin-plate spline interpolant:'}[self.name]
        if self.kind == 'local':
            return f'Locally weighted smoothing {"linear" if self.name == "lowess" else "quadratic"} regression:'
        return 'Linear model:' if self.linear is not None else 'General model:'

    def args(self):
        return ','.join(self.indep)


_INTERP2 = {'linearinterp': 'piecewise linear surface computed from p', 'nearestinterp': 'piecewise constant surface computed from p',
            'cubicinterp': 'piecewise cubic surface computed from p', 'biharmonicinterp': 'biharmonic surface computed from p',
            'thinplateinterp': 'thin-plate spline computed from p'}


def _poly2(i, j):
    """polyij: x^a y^b with a <= i, b <= j, a + b <= max(i, j), by total degree, x's power first."""
    top = max(i, j)
    terms = [(a, d - a) for d in range(top + 1) for a in range(d, -1, -1) if a <= i and d - a <= j]
    names = [f'p{a}{b}' for a, b in terms]

    def basis(XY):
        x, y = XY[:, 0], XY[:, 1]
        return np.column_stack([x ** a * y ** b for a, b in terms]) if terms else np.zeros((len(XY), 0))
    parts = []
    for nm, (a, b) in zip(names, terms):
        f = [('x' if a == 1 else f'x^{a}') if a else '', ('y' if b == 1 else f'y^{b}') if b else '']
        f = '*'.join(t for t in f if t)
        parts.append(nm + ('*' + f if f else ''))
    m = Model2(f'poly{i}{j}', 'poly', names, ' + '.join(parts), lambda c, XY: basis(XY) @ np.asarray(c, float), linear=basis)
    m.terms = terms
    return m


def library2(name):
    s = name.lower()
    m = re.fullmatch(r'poly([0-5])([0-5])', s)
    if m:
        return _poly2(int(m.group(1)), int(m.group(2)))
    if s in _INTERP2:
        return Model2(s, 'interp', ['p'], _INTERP2[s], None)
    if s in ('lowess', 'loess'):
        return Model2(s, 'local', ['p'], f'{s} ({"linear" if s == "lowess" else "quadratic"}) smoothing regression computed from p', None)
    return None


def custom2(expr, indep=('x', 'y'), dep='z', coeffs=None, problem=()):
    names = []
    for nm in re.findall(r'[A-Za-z_]\w*', expr):
        if nm not in CF._FUNCS and nm not in indep and nm not in names and nm not in problem:
            names.append(nm)
    if coeffs is not None:
        names = coeffs
    from .core import anon_from_text
    fh = anon_from_text(f'@({", ".join(names + list(problem) + list(indep))}) {CF._vectorized(expr)}')

    def fn(c, XY):
        col = lambda k: out(np.asarray(XY[:, k], float).reshape(-1, 1))
        r = fh.scall(1, *[float(v) for v in c], col(0), col(1))
        v = darr(r).reshape(-1).astype(float)
        return np.broadcast_to(v, (len(XY),)).copy() if v.size == 1 else v
    return Model2('custom', 'custom', names, expr, fn, indep=indep, dep=dep, fh=fh)


def from_handle2(f):
    t = f.text() if hasattr(f, 'text') else ''
    m = re.match(r'@\(([^)]*)\)\s*(.*)$', t, re.S)
    if not m:
        raise err('curvefit:fittype:handle', 'A surface model given as a function is an anonymous function of its coefficients, x and y, as @(a, b, x, y) a*x + b*y.', 'fittype')
    args = [a.strip() for a in m.group(1).split(',') if a.strip()]
    if len(args) < 3:
        raise err('curvefit:fittype:handle', 'A surface model takes its coefficients, then x and y.', 'fittype')
    return custom2(m.group(2).strip(), indep=tuple(args[-2:]), coeffs=args[:-2])


def _indep(opts):
    v = opts.get('Independent')
    if v is None:
        return None
    if type(v) is Cell:
        return tuple(py_str(c) for c in v.a.reshape(-1))
    return (py_str(v),)


def model2_of(spec, opts):
    if isinstance(spec, FitType2):
        return spec.model
    if isinstance(spec, FH):
        return from_handle2(spec)
    s = py_str(spec)
    m = library2(s)
    if m is not None:
        return m
    if CF.library(s) is not None or s.lower() in ('pchipinterp', 'smoothingspline'):
        raise err('curvefit:fit:fittype', f"'{s}' is a curve model: a surface takes poly00 to poly55, lowess, loess, an interpolant or an expression in x and y.", 'fit')
    ind = _indep(opts) or ('x', 'y')
    if len(ind) != 2:
        raise err('curvefit:fit:fittype', 'A surface model has two independent variables.', 'fit')
    if not any(re.search(rf'\b{re.escape(v)}\b', s) for v in ind):
        raise err('curvefit:fit:fittype', f"'{s}' is no surface model: give poly00 to poly55, lowess, loess, an interpolant or an expression in {ind[0]} and {ind[1]}.", 'fit')
    coeffs = [py_str(c) for c in opts['Coefficients'].a.reshape(-1)] if 'Coefficients' in opts and type(opts['Coefficients']) is Cell else None
    dep = py_str(opts['Dependent']) if 'Dependent' in opts else 'z'
    return custom2(s, indep=ind, dep=dep, coeffs=coeffs)


def _is_surface_spec(spec, opts):
    """Whether a fittype call describes a surface: two independent variables
    named, a surface library name, or an anonymous function whose last two
    inputs are x and y."""
    ind = _indep(opts)
    if ind is not None:
        return len(ind) == 2
    if isinstance(spec, FH):
        return _surface_handle(spec)
    if is_str(spec):
        return library2(py_str(spec)) is not None
    return False


# ---- objects ---------------------------------------------------------------------------------------------------------------------

class FitType2(Obj):
    cls = 'fittype'
    is_handle = False

    def __init__(self, model):
        self.model = model

    def value_copy(self):
        return self

    def display_lines(self):
        m = self.model
        args = ','.join(m.coeffs + list(m.indep)) if m.kind not in ('interp', 'local') else m.args()
        return ['     ' + m.label(), f'     f({args}) = {m.text}']

    def index(self, args):
        m = self.model
        if m.kind in ('interp', 'local'):
            raise err('curvefit:fittype:evaluate', 'An interpolant or smoothing fittype is evaluated only once fitted.', 'fittype')
        c = [float(darr(a).flat[0]) for a in args[:-2]]
        x, y = (np.asarray(darr(a), float) for a in args[-2:])
        x, y = np.broadcast_arrays(x, y)
        return out(m.fn(np.asarray(c), np.column_stack([x.reshape(-1), y.reshape(-1)])).reshape(x.shape))


class SFit(Obj):
    cls = 'sfit'
    is_handle = False

    def __init__(self, model, c, cov=None, dfe=0, sse=np.nan, XY=None, z=None, w=None, interp=None, norm=None, span=None):
        self.model, self.c, self.cov, self.dfe, self.sse = model, np.asarray(c, float), cov, dfe, sse
        self.XY, self.z, self.w = XY, z, w
        self.interp = interp
        self.norm = norm            # (means, stds) when Normalize was on
        self.span = span

    def value_copy(self):
        return self

    def eval_xy(self, XY):
        XY = np.asarray(XY, float).reshape(-1, 2)
        if self.interp is not None:
            return np.asarray(self.interp(XY), float).reshape(-1)
        if self.norm is not None:
            XY = (XY - self.norm[0]) / self.norm[1]
        return self.model.fn(self.c, XY)

    def eval(self, x, y):
        x, y = np.broadcast_arrays(np.asarray(x, float), np.asarray(y, float))
        return self.eval_xy(np.column_stack([x.reshape(-1), y.reshape(-1)])).reshape(x.shape)

    def bounds(self, level=0.95):
        if self.cov is None or self.dfe <= 0:
            return np.full((2, self.c.size), np.nan)
        se = np.sqrt(np.maximum(np.diag(self.cov), 0))
        t = CF._st().t.ppf((1 + level) / 2, self.dfe)
        return np.vstack([self.c - t * se, self.c + t * se])

    def display_lines(self):
        m = self.model
        lines = ['     ' + m.label(), f'     f({m.args()}) = {m.text}']
        if self.norm is not None:
            (mx, my), (sx, sy) = self.norm
            lines += [f'       where x is normalized by mean {CF._g(mx)} and std {CF._g(sx)}',
                      f'       and where y is normalized by mean {CF._g(my)} and std {CF._g(sy)}']
        if m.kind in ('interp', 'local'):
            if m.kind == 'local' and self.span is not None:
                lines += ['     Span:', f'       {CF._g(self.span)}']
            return lines
        b = self.bounds()
        lines.append('     Coefficients (with 95% confidence bounds):' if b.size and np.all(np.isfinite(b)) else '     Coefficients:')
        w = max((len(n) for n in m.coeffs), default=1)
        for i, n in enumerate(m.coeffs):
            line = f'       {n.ljust(w)} = {CF._g(self.c[i]).rjust(10)}'
            if np.all(np.isfinite(b[:, i])):
                line += f'  ({CF._g(b[0, i])}, {CF._g(b[1, i])})'
            lines.append(line)
        return lines

    def index(self, args):
        if len(args) == 1:
            XY = np.asarray(darr(args[0]), float)
            if XY.ndim != 2 or XY.shape[1] != 2:
                raise err('curvefit:sfit:evaluate', 'A surface fit is evaluated as sf(x, y) or sf([x y]).', 'sfit')
            return out(self.eval_xy(XY).reshape(-1, 1))
        if len(args) != 2:
            raise err('curvefit:sfit:evaluate', 'A surface fit is evaluated as sf(x, y) or sf([x y]).', 'sfit')
        return out(self.eval(darr(args[0]), darr(args[1])))

    def getprop(self, name):
        if name in self.model.coeffs and self.model.kind not in ('interp', 'local'):
            return float(self.c[self.model.coeffs.index(name)])
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class 'sfit'.")

    def propnames(self):
        return list(self.model.coeffs) if self.model.kind not in ('interp', 'local') else []


# ---- fitting --------------------------------------------------------------------------------------------------------------------

def _indexed(model, XY):
    """The surface model as curvefit's fitting sees it: a model of the points' numbers."""
    pick = lambda i: XY[np.asarray(i, float).astype(int)]
    lin = (lambda i: model.linear(pick(i))) if model.linear is not None else None
    start = (lambda i, z: model.start(pick(i), z)) if model.start is not None else None
    return CF.Model(model.name, model.kind, model.coeffs, model.text, lambda c, i: model.fn(c, pick(i)), linear=lin, start=start)


def _local_fit(XY, z, w, degree, span, robust, at):
    """Local regression of the given degree at the points at: tricube weights on the span nearest points (as a fraction of
    them), distances measured in each variable's range; bisquare robustness weights from the fit at the data."""
    n = len(XY)
    k = max(int(math.ceil(span * n)), {1: 3, 2: 6}[degree] + 1)
    k = min(k, n)
    scale = np.ptp(XY, axis=0)
    scale = np.where(scale > 0, scale, 1.0)
    U = XY / scale

    def basis(D):
        cols = [np.ones(len(D)), D[:, 0], D[:, 1]]
        if degree == 2:
            cols += [D[:, 0] ** 2, D[:, 0] * D[:, 1], D[:, 1] ** 2]
        return np.column_stack(cols)

    def at_points(P, rw):
        Pu = P / scale
        res = np.empty(len(P))
        for i, p in enumerate(Pu):
            d = np.sqrt(np.sum((U - p) ** 2, axis=1))
            idx = np.argsort(d, kind='stable')[:k]
            dmax = d[idx].max()
            uu = d[idx] / (dmax * 1.0000001 if dmax > 0 else 1.0)
            wt = (1 - uu ** 3) ** 3 * rw[idx] * w[idx]
            A = basis(XY[idx] - P[i])
            sw = np.sqrt(wt)
            if np.sum(wt > 0) < A.shape[1]:
                res[i] = np.average(z[idx], weights=np.where(wt > 0, wt, 1e-300)) if np.any(wt > 0) else np.nan
                continue
            c = np.linalg.lstsq(A * sw[:, None], z[idx] * sw, rcond=None)[0]
            res[i] = c[0]
        return res
    rw = np.ones(n)
    if robust:
        for _ in range(5):
            r = z - at_points(XY, rw)
            s = np.median(np.abs(r))
            if s == 0:
                break
            u = r / (6 * s)
            rw = (np.abs(u) < 1) * (1 - u ** 2) ** 2
    return at_points(at, rw), (lambda P: at_points(np.asarray(P, float), rw))


def _biharmonic(XY, z):
    """Sandwell's biharmonic spline: the sum of w_k |r - r_k|^2 (ln|r - r_k| - 1) through the points."""
    scale = np.ptp(XY, axis=0).max() or 1.0
    P = XY / scale
    D = np.sqrt(((P[:, None, :] - P[None, :, :]) ** 2).sum(-1))
    with np.errstate(divide='ignore', invalid='ignore'):
        G = np.where(D > 0, D ** 2 * (np.log(D) - 1), 0.0)
    wts = np.linalg.lstsq(G, z, rcond=None)[0] if np.linalg.matrix_rank(G) < len(z) else np.linalg.solve(G, z)

    def f(Q):
        Q = np.asarray(Q, float) / scale
        d = np.sqrt(((Q[:, None, :] - P[None, :, :]) ** 2).sum(-1))
        with np.errstate(divide='ignore', invalid='ignore'):
            g = np.where(d > 0, d ** 2 * (np.log(d) - 1), 0.0)
        return g @ wts
    return f


def _interp2(XY, z, name):
    from scipy import interpolate as I
    # repeated points: their mean
    U, inv = np.unique(XY, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    zz = np.bincount(inv, weights=z) / np.bincount(inv)
    if name == 'linearinterp':
        g = I.LinearNDInterpolator(U, zz)
        return lambda P: g(np.asarray(P, float))
    if name == 'nearestinterp':
        # MATLAB-style: nearest within the data's convex hull, NaN outside it
        g = I.NearestNDInterpolator(U, zz)
        h = I.LinearNDInterpolator(U, np.zeros(len(U)))
        return lambda P: np.where(np.isnan(h(np.asarray(P, float))), np.nan, g(np.asarray(P, float)))
    if name == 'cubicinterp':
        g = I.CloughTocher2DInterpolator(U, zz)
        return lambda P: g(np.asarray(P, float))
    if name == 'biharmonicinterp':
        return _biharmonic(U, zz)
    g = I.RBFInterpolator(U, zz, kernel='thin_plate_spline', degree=1)
    return lambda P: g(np.asarray(P, float))


def fit_surface(nargout, XY, z, spec, opts):
    model = model2_of(spec, opts)
    n = len(z)
    w = CF._vec(opts['Weights']) if 'Weights' in opts else np.ones(n)
    if w.size != n:
        raise err('curvefit:fit:Weights', 'There is a weight for each point.', 'fit')
    keep = np.all(np.isfinite(XY), axis=1) & np.isfinite(z) & np.isfinite(w)
    if 'Exclude' in opts:
        e = np.asarray(darr(opts['Exclude'])).reshape(-1)
        if e.dtype == bool or (e.size == n and set(np.unique(e)).issubset({0, 1})):
            keep &= ~e.astype(bool)
        else:
            keep[e.astype(int) - 1] = False
    X, zs, ws = XY[keep], z[keep], w[keep]
    norm = None
    if 'Normalize' in opts and (opt_str(opts['Normalize']) or '').lower() == 'on' and model.kind not in ('interp',):
        mu, sd = X.mean(axis=0), X.std(axis=0, ddof=1)
        sd = np.where(sd > 0, sd, 1.0)
        norm = (mu, sd)
        X = (X - mu) / sd
    info = {'algorithm': model.name, 'iterations': 0, 'funcCount': 0, 'exitflag': 1, 'firstorderopt': 0.0, 'message': ''}
    if model.kind == 'interp':
        if len(zs) < 3:
            raise err('curvefit:fit:InsufficientData', 'An interpolant needs at least 3 points.', 'fit')
        f = _interp2(X, zs, model.name)
        sf = SFit(model, [], None, 0, 0.0, XY[keep], zs, ws, interp=f)
        fitted = np.asarray(f(X), float)
        J = np.zeros((len(zs), 0))
        p = 0
    elif model.kind == 'local':
        span = float(num(opts['Span'])) if 'Span' in opts else 0.25
        if not 0 < span <= 1:
            raise err('curvefit:fit:Span', 'Span is a fraction of the points, above 0 and at most 1.', 'fit')
        robust = (opt_str(opts['Robust']) or 'off').lower() if 'Robust' in opts else 'off'
        deg = 1 if model.name == 'lowess' else 2
        if len(zs) < 3 * deg + 1:
            raise err('curvefit:fit:InsufficientData', f'{model.name} needs at least {3 * deg + 1} points.', 'fit')
        fitted, g = _local_fit(X, zs, ws, deg, span, robust in ('on', 'bisquare', 'lar'), X)
        if norm is not None:
            mu, sd = norm
            sf = SFit(model, [], None, 0, 0.0, XY[keep], zs, ws, interp=lambda P: g((np.asarray(P, float) - mu) / sd), span=span)
        else:
            sf = SFit(model, [], None, 0, 0.0, XY[keep], zs, ws, interp=g, span=span)
        J = np.zeros((len(zs), 0))
        p = 0
    else:
        p = len(model.coeffs)
        if len(zs) < p:
            raise err('curvefit:fit:InsufficientData', f'There are fewer data points ({len(zs)}) than coefficients to fit.', 'fit')
        idx = np.arange(len(zs), dtype=float)
        cf, fitted, resid, J, info = CF._fit(idx, zs, _indexed(model, X), opts, ws)
        sf = SFit(model, cf.c, cf.cov, cf.dfe, cf.sse, XY[keep], zs, ws, norm=norm)
    resid = zs - fitted
    sse = float(np.nansum(ws * resid ** 2))
    sf.sse = sse
    if nargout < 2:
        return sf
    sst = float(np.sum(ws * (zs - np.average(zs, weights=ws)) ** 2))
    dfe = len(zs) - p
    r2 = 1 - sse / sst if sst > 0 else np.nan
    gof = Struct.scalar({'sse': sse, 'rsquare': r2, 'dfe': float(dfe),
                         'adjrsquare': 1 - (1 - r2) * (len(zs) - 1) / dfe if dfe > 0 else np.nan,
                         'rmse': math.sqrt(sse / dfe) if dfe > 0 else np.nan})
    if nargout < 3:
        return sf, gof
    output = Struct.scalar({'numobs': float(len(zs)), 'numparam': float(p), 'residuals': out(resid.reshape(-1, 1)), 'Jacobian': out(J),
                            'exitflag': float(info['exitflag']), 'firstorderopt': info['firstorderopt'], 'iterations': float(info['iterations']),
                            'funcCount': float(info['funcCount']), 'algorithm': Char.of(info['algorithm']), 'message': Char.of(str(info['message']))})
    return sf, gof, output


# ---- the builtins, through curvefit's -----------------------------------------------------------------------------------------

def _fit_wrapper(orig):
    def f(nargout, *args):
        if len(args) >= 3:
            opts, rest = CF._opts(list(args))
            if len(rest) >= 3:
                if len(rest) >= 4 and not is_str(rest[2]) and not isinstance(rest[2], (CF.FitType, FitType2, FH, Cell)):
                    # fit(x, y, z, type): the two variables apart
                    x, y = CF._vec(rest[0]), CF._vec(rest[1])
                    if x.size != y.size:
                        raise err('curvefit:fit:xyLength', 'x and y have the same number of values.', 'fit')
                    return fit_surface(nargout, np.column_stack([x, y]), CF._vec(rest[2]), rest[3], opts)
                xa = darr(rest[0], 'fit')
                if (xa.ndim == 2 and xa.shape[1] == 2 and xa.shape[0] != 1) or isinstance(rest[2], FitType2):
                    if xa.ndim != 2 or xa.shape[1] != 2:
                        raise err('curvefit:fit:surface', 'A surface is fitted to points [x y], two columns.', 'fit')
                    z = CF._vec(rest[1])
                    if z.size != xa.shape[0]:
                        raise err('curvefit:fit:xyLength', '[x y] has a row for each value of z.', 'fit')
                    return fit_surface(nargout, xa.astype(float), z, rest[2], opts)
        return orig(nargout, *args)
    f.__doc__ = orig.__doc__
    return f


REG['fit'].fn = _fit_wrapper(REG['fit'].fn)


def _fittype_wrapper(orig):
    def f(nargout, *args):
        opts, rest = CF._opts(list(args))
        if rest and _is_surface_spec(rest[0], opts):
            return FitType2(model2_of(rest[0], opts))
        return orig(nargout, *args)
    f.__doc__ = orig.__doc__
    return f


def _surface_handle(fh):
    """An anonymous model whose last two inputs are x and y (any names: whose body uses both)."""
    m = re.match(r'@\(([^)]*)\)\s*(.*)$', fh.text() if hasattr(fh, 'text') else '', re.S)
    if not m:
        return False
    args = [a.strip() for a in m.group(1).split(',') if a.strip()]
    return len(args) >= 3 and args[-2] == 'x' and args[-1] == 'y'


REG['fittype'].fn = _fittype_wrapper(REG['fittype'].fn)


def _over(name, handler):
    """name's builtin, with handler taking a surface fit or fittype first (curvefit's wrapper keeps the builtin's flags)."""
    CF._wrap(name, lambda v: isinstance(v, (SFit, FitType2)), handler)


def _confint(nargout, f, *rest):
    if not isinstance(f, SFit):
        raise err('curvefit:confint:fit', 'confint takes a fit.', 'confint')
    level = float(darr(rest[0]).flat[0]) if rest else 0.95
    return out(f.bounds(level))


def _jac(f, XY):
    p = f.c.size
    m = f.model
    P = (XY - f.norm[0]) / f.norm[1] if f.norm is not None else XY
    if m.linear is not None:
        return m.linear(P)
    y0 = m.fn(f.c, P)
    J = np.empty((len(XY), p))
    for j in range(p):
        h = math.sqrt(np.finfo(float).eps) * max(abs(f.c[j]), 1.0)
        cc = f.c.copy()
        cc[j] += h
        J[:, j] = (m.fn(cc, P) - y0) / h
    return J


def _predint(nargout, f, *rest):
    if not isinstance(f, SFit):
        raise err('curvefit:predint:fit', 'predint takes a fit.', 'predint')
    if not rest:
        raise err('MATLAB:minrhs', 'Give the points, [x y].', 'predint')
    XY = np.asarray(darr(rest[0]), float).reshape(-1, 2) if numel(rest[0]) % 2 == 0 else None
    if XY is None:
        raise err('curvefit:predint:points', 'The points are [x y], two columns.', 'predint')
    level = float(darr(rest[1]).flat[0]) if len(rest) > 1 else 0.95
    obs = not (len(rest) > 2 and py_str(rest[2]).lower() == 'functional')
    sim = len(rest) > 3 and py_str(rest[3]).lower() == 'on'
    y = f.eval_xy(XY)
    if f.cov is None or f.dfe <= 0:
        ci = np.full((len(XY), 2), np.nan)
        return (out(ci), out(y.reshape(-1, 1))) if nargout > 1 else out(ci)
    J = _jac(f, XY)
    p = f.c.size
    var = np.einsum('ij,jk,ik->i', J, f.cov, J) + (f.sse / f.dfe if obs else 0)
    k = p + (1 if obs else 0)
    crit = math.sqrt(k * CF._st().f.ppf(level, k, f.dfe)) if sim else CF._st().t.ppf((1 + level) / 2, f.dfe)
    d = crit * np.sqrt(np.maximum(var, 0))
    ci = np.column_stack([y - d, y + d])
    return (out(ci), out(y.reshape(-1, 1))) if nargout > 1 else out(ci)


def _differentiate(nargout, f, *rest):
    if not isinstance(f, SFit):
        raise err('curvefit:differentiate:fit', 'differentiate takes a fit.', 'differentiate')
    if len(rest) == 1:
        XY = np.asarray(darr(rest[0]), float)
        x, y = XY[:, 0], XY[:, 1]
        shape = (len(XY), 1)
    elif len(rest) == 2:
        x, y = np.broadcast_arrays(np.asarray(darr(rest[0]), float), np.asarray(darr(rest[1]), float))
        shape = x.shape
    else:
        raise err('MATLAB:minrhs', 'Give the points: differentiate(sf, x, y) or differentiate(sf, [x y]).', 'differentiate')
    x, y = x.reshape(-1), y.reshape(-1)
    m = f.model
    if m.kind == 'poly':
        sx, sy = (f.norm[1] if f.norm is not None else (1.0, 1.0))
        u, v = ((x - f.norm[0][0]) / sx, (y - f.norm[0][1]) / sy) if f.norm is not None else (x, y)
        d = {key: np.zeros_like(u) for key in ('x', 'y', 'xx', 'xy', 'yy')}
        for c, (a, b) in zip(f.c, m.terms):
            pw = lambda t, k: t ** k if k >= 0 else np.zeros_like(t)
            d['x'] += c * a * pw(u, a - 1) * pw(v, b) / sx
            d['y'] += c * b * pw(u, a) * pw(v, b - 1) / sy
            d['xx'] += c * a * (a - 1) * pw(u, a - 2) * pw(v, b) / sx ** 2
            d['xy'] += c * a * b * pw(u, a - 1) * pw(v, b - 1) / (sx * sy)
            d['yy'] += c * b * (b - 1) * pw(u, a) * pw(v, b - 2) / sy ** 2
        res = [d[k] for k in ('x', 'y', 'xx', 'xy', 'yy')]
    else:
        hx = 1e-3 * np.maximum(np.abs(x), 1.0) * (np.ptp(f.XY[:, 0]) if f.XY is not None and np.ptp(f.XY[:, 0]) > 0 else 1.0) / max(np.max(np.abs(x)), 1.0)
        hy = 1e-3 * np.maximum(np.abs(y), 1.0) * (np.ptp(f.XY[:, 1]) if f.XY is not None and np.ptp(f.XY[:, 1]) > 0 else 1.0) / max(np.max(np.abs(y)), 1.0)
        F = lambda a, b: f.eval(a, b)
        f0 = F(x, y)
        fxp, fxm, fyp, fym = F(x + hx, y), F(x - hx, y), F(x, y + hy), F(x, y - hy)
        fpp, fpm, fmp, fmm = F(x + hx, y + hy), F(x + hx, y - hy), F(x - hx, y + hy), F(x - hx, y - hy)
        res = [(fxp - fxm) / (2 * hx), (fyp - fym) / (2 * hy), (fxp - 2 * f0 + fxm) / hx ** 2, (fpp - fpm - fmp + fmm) / (4 * hx * hy),
               (fyp - 2 * f0 + fym) / hy ** 2]
    outs = [out(r.reshape(shape)) for r in res]
    n = max(nargout, 1)
    return tuple(outs[:n]) if n > 1 else outs[0]


def _coeffvalues(nargout, f, *rest):
    if not isinstance(f, SFit):
        raise err('curvefit:coeffvalues:fit', 'coeffvalues takes a fit.', 'coeffvalues')
    return out(f.c.reshape(1, -1))


def _coeffnames(nargout, f, *rest):
    names = f.model.coeffs if f.model.kind not in ('interp', 'local') else []
    return Cell.of_list([Char.of(n) for n in names], (len(names), 1))


def _numcoeffs(nargout, f, *rest):
    return float(len(f.model.coeffs)) if f.model.kind not in ('interp', 'local') else 0.0


def _feval(nargout, f, *rest):
    return f.index(list(rest))


def _formula(nargout, f, *rest):
    return Char.of(f.model.text)


def _indepnames(nargout, f, *rest):
    return Cell.of_list([Char.of(n) for n in f.model.indep], (len(f.model.indep), 1))


def _depnames(nargout, f, *rest):
    return Cell.of_list([Char.of(f.model.dep)], (1, 1))


def _plot_sfit(nargout, f, *rest):
    """plot(sf), plot(sf, [x y], z), with 'Style' 'Surface' (the default), 'PredFunc', 'PredObs', 'Residuals' or 'Contour', and 'Level'."""
    words, nums = [], []
    k = 0
    style, level = 'surface', 0.95
    while k < len(rest):
        a = rest[k]
        if is_str(a) and py_str(a).lower() == 'style' and k + 1 < len(rest):
            style = py_str(rest[k + 1]).lower()
            k += 2
            continue
        if is_str(a) and py_str(a).lower() == 'level' and k + 1 < len(rest):
            level = float(num(rest[k + 1]))
            k += 2
            continue
        if is_str(a):
            words.append(py_str(a).lower())
        else:
            nums.append(a)
        k += 1
    if style not in ('surface', 'predfunc', 'predobs', 'residuals', 'contour'):
        raise err('curvefit:plot:Style', "Style is 'Surface', 'PredFunc', 'PredObs', 'Residuals' or 'Contour'.", 'plot')
    data = None
    if len(nums) >= 2:
        XY = np.asarray(darr(nums[0]), float).reshape(-1, 2)
        data = (XY, CF._vec(nums[1]))
    src = data[0] if data is not None else f.XY
    if src is not None and len(src):
        (x0, y0), (x1, y1) = src.min(axis=0), src.max(axis=0)
    else:
        x0, y0, x1, y1 = -1.0, -1.0, 1.0, 1.0
    gx, gy = np.meshgrid(np.linspace(x0, x1, 49), np.linspace(y0, y1, 49))
    Z = f.eval(gx, gy)
    hs = []
    b = lambda name, *a: R._builtin(name, *a)
    if style == 'residuals':
        if data is None:
            raise err('curvefit:plot:Residuals', 'Residuals need the data: plot(sf, [x y], z, ''Style'', ''Residuals'').', 'plot')
        r = data[1] - f.eval_xy(data[0])
        h = b('stem3', data[0][:, 0].reshape(-1, 1), data[0][:, 1].reshape(-1, 1), r.reshape(-1, 1))
        b('hold', Char.of('on'))
        b('surf', np.array([[x0, x1], [x0, x1]]), np.array([[y0, y0], [y1, y1]]), np.zeros((2, 2)), Char.of('FaceAlpha'), 0.3, Char.of('EdgeColor'), Char.of('none'))
        b('hold', Char.of('off'))
        b('xlabel', Char.of('x'))
        b('ylabel', Char.of('y'))
        b('zlabel', Char.of('residuals'))
        return h if nargout else None
    if style == 'contour':
        h = b('contour', out(gx), out(gy), out(Z))
    else:
        h = b('surf', out(gx), out(gy), out(Z))
        if style in ('predfunc', 'predobs'):
            ci = darr(_predint(1, f, out(np.column_stack([gx.reshape(-1), gy.reshape(-1)])), level, Char.of('observation' if style == 'predobs' else 'functional')))
            b('hold', Char.of('on'))
            for j in range(2):
                b('surf', out(gx), out(gy), out(ci[:, j].reshape(gx.shape)), Char.of('FaceAlpha'), 0.25, Char.of('EdgeColor'), Char.of('none'))
            b('hold', Char.of('off'))
    if data is not None:
        b('hold', Char.of('on'))
        if style == 'contour':
            b('plot', data[0][:, 0].reshape(-1, 1), data[0][:, 1].reshape(-1, 1), Char.of('ko'), Char.of('MarkerFaceColor'), Char.of('k'))
        else:
            b('plot3', data[0][:, 0].reshape(-1, 1), data[0][:, 1].reshape(-1, 1), data[1].reshape(-1, 1), Char.of('ko'), Char.of('MarkerFaceColor'), Char.of('k'))
        b('hold', Char.of('off'))
    b('xlabel', Char.of('x'))
    b('ylabel', Char.of('y'))
    if style != 'contour':
        b('zlabel', Char.of('z'))
    return h if nargout else None


for _name, _h in (('confint', _confint), ('predint', _predint), ('differentiate', _differentiate), ('coeffvalues', _coeffvalues),
                  ('coeffnames', _coeffnames), ('numcoeffs', _numcoeffs), ('feval', _feval), ('formula', _formula), ('plot', _plot_sfit)):
    _over(_name, _h)
REG['differentiate'].nout = max(REG['differentiate'].nout, 5)
for _name, _h in (('indepnames', _indepnames), ('dependnames', _depnames)):
    if _name in REG:
        _over(_name, _h)


# ---- fits from coefficients ---------------------------------------------------------------------------------------------------

def _from_coefficients(nargout, args, fn, surface):
    if not args:
        raise err('MATLAB:minrhs', f'{fn} takes a fittype and its coefficients.', fn)
    ft = args[0]
    if is_str(ft):
        ft = REG['fittype'].fn(1, ft)
    want = FitType2 if surface else CF.FitType
    if not isinstance(ft, want):
        raise err(f'curvefit:{fn}:fittype', f'{fn} takes a fittype of {"two variables" if surface else "one variable"}, then its coefficients.', fn)
    m = ft.model
    if m.kind in ('interp', 'local'):
        raise err(f'curvefit:{fn}:fittype', f'An interpolant or smoothing fit is made by fit, from data.', fn)
    c = [float(num(a)) for a in args[1:]]
    if len(c) != len(m.coeffs):
        raise err(f'curvefit:{fn}:coefficients', f'Give a value for each of the {len(m.coeffs)} coefficients ({", ".join(m.coeffs)}).', fn)
    if surface:
        return SFit(m, c)
    return CF.CFit(m, c, None, 0, np.nan, None, None, None)


@bi('sfit')
def sfit(nargout, *args):
    """sf = sfit(fittype, coef1, coef2, ...): a surface with the coefficients given."""
    return _from_coefficients(nargout, args, 'sfit', True)


@bi('cfit')
def cfit(nargout, *args):
    """cf = cfit(fittype, coef1, coef2, ...): a curve with the coefficients given."""
    return _from_coefficients(nargout, args, 'cfit', False)


# ---- excludedata --------------------------------------------------------------------------------------------------------------

@bi('excludedata')
def excludedata(nargout, *args):
    """tf = excludedata(x, y, 'box', [xmin xmax ymin ymax]), ('domain', [xmin
    xmax]), ('range', [ymin ymax]) or ('indices', idx): true for the points to
    leave out of a fit (outside the box, domain or range; at the indices)."""
    nargchk(args, 4, 4, 'excludedata')
    x, y = CF._vec(args[0]), CF._vec(args[1])
    if x.size != y.size:
        raise err('curvefit:excludedata:xyLength', 'x and y have the same number of values.', 'excludedata')
    how = (opt_str(args[2]) or '').lower()
    v = np.asarray(darr(args[3]), float).reshape(-1)
    shape = np.asarray(darr(args[1])).shape if numel(args[1]) == y.size else (y.size, 1)
    if how == 'box':
        if v.size != 4:
            raise err('curvefit:excludedata:box', "'box' takes [xmin xmax ymin ymax].", 'excludedata')
        tf = (x < v[0]) | (x > v[1]) | (y < v[2]) | (y > v[3])
    elif how == 'domain':
        if v.size != 2:
            raise err('curvefit:excludedata:domain', "'domain' takes [xmin xmax].", 'excludedata')
        tf = (x < v[0]) | (x > v[1])
    elif how == 'range':
        if v.size != 2:
            raise err('curvefit:excludedata:range', "'range' takes [ymin ymax].", 'excludedata')
        tf = (y < v[0]) | (y > v[1])
    elif how == 'indices':
        if np.any(v < 1) or np.any(v > x.size) or np.any(v != np.round(v)):
            raise err('curvefit:excludedata:indices', f'The indices are whole numbers from 1 to {x.size}.', 'excludedata')
        tf = np.zeros(x.size, bool)
        tf[v.astype(int) - 1] = True
    else:
        raise err('curvefit:excludedata:method', "The method is 'box', 'domain', 'range' or 'indices'.", 'excludedata')
    return out(tf.reshape(shape))
