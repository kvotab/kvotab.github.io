"""Curve fitting: fit, fittype and fitoptions; fits (cfit) evaluated as f(x)
or feval, plotted, and asked for their confidence bounds (confint), their
prediction bounds (predint), derivatives and integrals; and smooth.

Library models: poly1-poly9, exp1-exp2, power1-power2, gauss1-gauss8,
sin1-sin8, fourier1-fourier8, ratNM, weibull; the interpolants
linearinterp, nearestinterp, pchipinterp, cubicinterp and
smoothingspline; and models written as text ('a*exp(-b*x) + c') or as
anonymous functions of the coefficients and x. Polynomials are fitted by
linear least squares, the rest by scipy.optimize.least_squares
(trust-region reflective) from starting points worked out from the data.
"""
import math
import re

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, darr, out, opt_str, is_str
from ..values import MError, Obj, Char, Cell, Struct, FH, EMPTY, numel, py_str
from .. import runtime as R


def bi(*names, **kw):
    """Registered as builtins are, with what NumPy or SciPy refuses told as the function's own error."""
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _st():
    import scipy.stats as st
    return st


def _g(v):
    """A coefficient as the fits show it (4 significant digits)."""
    if not np.isfinite(v):
        return 'NaN' if np.isnan(v) else ('Inf' if v > 0 else '-Inf')
    return f'{v:.4g}'


# ---- models -------------------------------------------------------------------------------------------------------

_FUNCS = {'exp', 'log', 'log10', 'log2', 'sqrt', 'sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'atan2', 'sinh', 'cosh', 'tanh', 'abs',
          'pi', 'erf', 'erfc', 'gamma', 'besselj', 'power', 'sign', 'min', 'max', 'mod', 'floor', 'ceil', 'round', 'Inf', 'NaN', 'eps',
          'sum', 'prod', 'heaviside', 'sec', 'csc', 'cot', 'i', 'j'}


class Model:
    """A model's form: its name, how it is written, its coefficients, and how it is evaluated and started."""

    def __init__(self, name, kind, coeffs, text, fn, linear=None, start=None, indep='x', dep='y', fh=None):
        self.name, self.kind, self.coeffs, self.text = name, kind, coeffs, text
        self.fn = fn                    # (coefficient values, x) -> values
        self.linear = linear            # x -> the basis columns, for a linear model
        self.start = start              # (x, y) -> starting coefficients
        self.indep, self.dep = indep, dep
        self.fh = fh

    def label(self):
        lib = {'poly': 'Linear model', 'interp': None}
        if self.kind == 'interp':
            return {'linearinterp': 'Linear interpolant', 'nearestinterp': 'Nearest neighbor interpolant', 'pchipinterp': 'Shape-preserving (pchip) interpolant',
                    'cubicinterp': 'Cubic interpolant', 'smoothingspline': 'Smoothing spline'}[self.name] + ':'
        if self.kind == 'custom':
            return 'General model:' if self.linear is None else 'Linear model:'
        cap = self.name[0].upper() + self.name[1:]
        return ('Linear model ' if self.linear is not None else 'General model ') + cap + ':'


def _poly(n):
    names = [f'p{k + 1}' for k in range(n + 1)]
    pows = list(range(n, -1, -1))
    text = ' + '.join((f'p{k + 1}*x^{p}' if p > 1 else f'p{k + 1}*x' if p == 1 else f'p{k + 1}') for k, p in enumerate(pows))
    return Model(f'poly{n}', 'poly', names, text, lambda c, x: np.polyval(c, x), linear=lambda x: np.column_stack([x ** p for p in pows]))


def _loglin(x, y):
    ok = (y != 0) & np.isfinite(y)
    if ok.sum() < 2:
        return float(np.mean(y) or 1.0), 0.0
    s = np.sign(np.median(y[ok]))
    b, la = np.polyfit(x[ok & (np.sign(y) == s)], np.log(np.abs(y[ok & (np.sign(y) == s)])), 1)
    return s * math.exp(la), b


def _exp(n):
    if n == 1:
        return Model('exp1', 'exp', ['a', 'b'], 'a*exp(b*x)', lambda c, x: c[0] * np.exp(c[1] * x), start=lambda x, y: list(_loglin(x, y)))

    def st(x, y):
        a, b = _loglin(x, y)
        return [a / 2, b, a / 2, b / 2 if b else -0.1]
    return Model('exp2', 'exp', ['a', 'b', 'c', 'd'], 'a*exp(b*x) + c*exp(d*x)', lambda c, x: c[0] * np.exp(c[1] * x) + c[2] * np.exp(c[3] * x), start=st)


def _power(n):
    def st(x, y):
        ok = (x > 0) & (y > 0)
        if ok.sum() >= 2:
            b, la = np.polyfit(np.log(x[ok]), np.log(y[ok]), 1)
            return [math.exp(la), b] + ([0.0] if n == 2 else [])
        return [1.0, 1.0] + ([0.0] if n == 2 else [])
    if n == 1:
        return Model('power1', 'power', ['a', 'b'], 'a*x^b', lambda c, x: c[0] * np.power(x, c[1]), start=st)
    return Model('power2', 'power', ['a', 'b', 'c'], 'a*x^b+c', lambda c, x: c[0] * np.power(x, c[1]) + c[2], start=st)


def _gauss(n):
    names = [f'{l}{k + 1}' for k in range(n) for l in 'abc']
    text = ' + '.join(f'a{k + 1}*exp(-((x-b{k + 1})/c{k + 1})^2)' for k in range(n))

    def fn(c, x):
        return sum(c[3 * k] * np.exp(-((x - c[3 * k + 1]) / c[3 * k + 2]) ** 2) for k in range(n))

    def st(x, y):
        out_, r = [], y.astype(float).copy()
        span = (np.max(x) - np.min(x)) or 1.0
        for _ in range(n):
            i = int(np.argmax(r))
            a = r[i]
            half = np.abs(r - a / 2)
            w = span / (4 * n)
            above = np.nonzero(r > a / 2)[0]
            if above.size > 1:
                w = max((x[above].max() - x[above].min()) / 1.665, span / (20 * n))
            out_ += [a, x[i], w]
            r = r - a * np.exp(-((x - x[i]) / w) ** 2)
        return out_
    return Model(f'gauss{n}', 'gauss', names, text, fn, start=st)


def _dominant(x, y, k=1):
    """The k strongest angular frequencies of y (on x, evenly spaced or not)."""
    n = x.size
    xs = np.linspace(x.min(), x.max(), max(n, 16))
    ys = np.interp(xs, np.sort(x), y[np.argsort(x)]) - np.mean(y)
    F = np.abs(np.fft.rfft(ys))
    f = np.fft.rfftfreq(xs.size, xs[1] - xs[0]) * 2 * np.pi
    F[0] = 0
    idx = np.argsort(-F)[:k]
    return [float(f[i]) if f[i] > 0 else 2 * np.pi / ((x.max() - x.min()) or 1) for i in idx]


def _sin(n):
    names = [f'{l}{k + 1}' for k in range(n) for l in 'abc']
    text = ' + '.join(f'a{k + 1}*sin(b{k + 1}*x+c{k + 1})' for k in range(n))

    def fn(c, x):
        return sum(c[3 * k] * np.sin(c[3 * k + 1] * x + c[3 * k + 2]) for k in range(n))

    def st(x, y):
        ws = _dominant(x, y, n)
        amp = (np.max(y) - np.min(y)) / 2 or 1.0
        return [v for w in ws for v in (amp / max(n, 1), w, 0.0)]
    return Model(f'sin{n}', 'sin', names, text, fn, start=st)


def _fourier(n):
    names = ['a0'] + [f'{l}{k + 1}' for k in range(n) for l in 'ab'] + ['w']
    text = 'a0 + ' + ' + '.join(f'a{k + 1}*cos({k + 1 if k else ""}{"*" if k else ""}x*w) + b{k + 1}*sin({k + 1 if k else ""}{"*" if k else ""}x*w)'.replace('(*', '(') for k in range(n))

    def fn(c, x):
        w = c[-1]
        return c[0] + sum(c[1 + 2 * k] * np.cos((k + 1) * w * x) + c[2 + 2 * k] * np.sin((k + 1) * w * x) for k in range(n))

    def st(x, y):
        w = _dominant(x, y, 1)[0]
        B = np.column_stack([np.ones_like(x)] + [f((k + 1) * w * x) for k in range(n) for f in (np.cos, np.sin)])
        c = np.linalg.lstsq(B, y, rcond=None)[0]
        return list(c) + [w]
    return Model(f'fourier{n}', 'fourier', names, text, fn, start=st)


def _rat(nn, md):
    pn = [f'p{k + 1}' for k in range(nn + 1)]
    qn = [f'q{k + 1}' for k in range(md)]
    num = ' + '.join((f'p{k + 1}*x^{nn - k}' if nn - k > 1 else f'p{k + 1}*x' if nn - k == 1 else f'p{k + 1}') for k in range(nn + 1))
    den = ' + '.join([f'x^{md}' if md > 1 else 'x'] + [(f'q{k + 1}*x^{md - k - 1}' if md - k - 1 > 1 else f'q{k + 1}*x' if md - k - 1 == 1 else f'q{k + 1}') for k in range(md)])
    text = f'({num}) / ({den})'

    def fn(c, x):
        p, q = c[:nn + 1], c[nn + 1:]
        return np.polyval(p, x) / np.polyval(np.concatenate([[1.0], q]), x)

    def st(x, y):
        # y*(x^m + q1 x^(m-1) + ...) = p(x): linear in p and q
        A = np.column_stack([x ** (nn - k) for k in range(nn + 1)] + [-y * x ** (md - k - 1) for k in range(md)])
        c = np.linalg.lstsq(A, y * x ** md, rcond=None)[0]
        return list(c)
    return Model(f'rat{nn}{md}', 'rat', pn + qn, text, fn, start=st)


def _weibull():
    def st(x, y):
        return [1.0, 2.0]
    return Model('weibull', 'weibull', ['a', 'b'], 'a*b*x^(b-1)*exp(-a*x^b)', lambda c, x: c[0] * c[1] * np.power(x, c[1] - 1) * np.exp(-c[0] * np.power(x, c[1])), start=st)


_INTERP = ('linearinterp', 'nearestinterp', 'pchipinterp', 'cubicinterp', 'smoothingspline')


def library(name):
    s = name.lower()
    m = re.fullmatch(r'poly(\d)', s)
    if m and 1 <= int(m.group(1)) <= 9:
        return _poly(int(m.group(1)))
    m = re.fullmatch(r'(exp|power)([12])', s)
    if m:
        return (_exp if m.group(1) == 'exp' else _power)(int(m.group(2)))
    m = re.fullmatch(r'(gauss|sin|fourier)([1-8])', s)
    if m:
        return {'gauss': _gauss, 'sin': _sin, 'fourier': _fourier}[m.group(1)](int(m.group(2)))
    m = re.fullmatch(r'rat([0-5])([1-5])', s)
    if m:
        return _rat(int(m.group(1)), int(m.group(2)))
    if s == 'weibull':
        return _weibull()
    if s in _INTERP:
        return Model(s, 'interp', ['p'], 'piecewise polynomial computed from p', None)
    return None


def _vectorized(text):
    """A model written with * / ^ made elementwise (as .* ./ .^)."""
    return re.sub(r'(?<!\.)([*/^])', r'.\1', text)


def custom(expr, indep='x', dep='y', coeffs=None, problem=()):
    """A model written as text: its coefficients are the names in it other
    than the independent variable and the functions it calls."""
    names = []
    for nm in re.findall(r'[A-Za-z_]\w*', expr):
        if nm not in _FUNCS and nm != indep and nm not in names and nm not in problem:
            names.append(nm)
    if coeffs is not None:
        names = coeffs
    params = ', '.join(names + list(problem) + [indep])
    from .core import anon_from_text
    fh = anon_from_text(f'@({params}) {_vectorized(expr)}')

    def fn(c, x):
        r = fh.scall(1, *[float(v) for v in c], out(np.asarray(x, float).reshape(-1, 1)))
        return np.broadcast_to(darr(r).reshape(-1).astype(float), x.shape).copy() if numel(r) in (1, x.size) else darr(r).reshape(-1)
    return Model('custom', 'custom', names, expr, fn, indep=indep, dep=dep, fh=fh)


def linear_terms(terms, indep='x', coeffs=None):
    """A linear model of the terms given as text ({'x', 'sin(x)', '1'}): one coefficient for each, a, b, c ... unless named."""
    from .core import anon_from_text
    k = len(terms)
    names = coeffs or ([chr(ord('a') + i) for i in range(k)] if k <= 26 else [f'a{i + 1}' for i in range(k)])
    if len(names) != k:
        raise err('curvefit:fittype:coefficients', 'A linear model has a coefficient for each of its terms.', 'fittype')
    fhs = [anon_from_text(f'@({indep}) {_vectorized(t)}') for t in terms]

    def basis(x):
        cols = []
        for fh in fhs:
            v = darr(fh.scall(1, out(np.asarray(x, float).reshape(-1, 1)))).reshape(-1).astype(float)
            cols.append(np.broadcast_to(v, (x.size,)) if v.size == 1 else v)
        return np.column_stack(cols)
    parts = []
    for nm, t in zip(names, terms):
        t = t.strip()
        parts.append(nm if t == '1' else f'{nm}*({t})' if re.search(r'[-+]', t) else f'{nm}*{t}')
    text = ' + '.join(parts)
    return Model('custom', 'custom', names, text, lambda c, x: basis(x) @ np.asarray(c, float), linear=basis, indep=indep)


def from_handle(f):
    """A model given as an anonymous function @(a, b, x) ...: the last argument is x."""
    t = f.text() if hasattr(f, 'text') else ''
    m = re.match(r'@\(([^)]*)\)\s*(.*)$', t, re.S)
    if not m:
        raise err('curvefit:fittype:handle', 'A model given as a function is an anonymous function of its coefficients and x, as @(a, b, x) a*exp(-b*x).', 'fittype')
    args = [a.strip() for a in m.group(1).split(',') if a.strip()]
    body = m.group(2).strip()
    mdl = custom(body, indep=args[-1], coeffs=args[:-1])
    return mdl


# ---- fittype and cfit objects --------------------------------------------------------------------------------------

class FitType(Obj):
    cls = 'fittype'
    is_handle = False

    def __init__(self, model):
        self.model = model

    def display_lines(self):
        m = self.model
        args = ','.join(m.coeffs + [m.indep]) if m.kind != 'interp' else 'x'
        return ['     ' + m.label(), f'     f({args}) = {m.text}']

    def index(self, args):
        m = self.model
        c = [float(darr(a).flat[0]) for a in args[:-1]]
        x = darr(args[-1]).astype(float)
        return out(m.fn(np.asarray(c), x.reshape(-1)).reshape(x.shape))


class CFit(Obj):
    cls = 'cfit'
    is_handle = False

    def __init__(self, model, c, cov, dfe, sse, x, y, w, interp=None, smooth_p=None, spline=None):
        self.model, self.c, self.cov, self.dfe, self.sse = model, np.asarray(c, float), cov, dfe, sse
        self.x, self.y, self.w = x, y, w
        self.interp, self.smooth_p, self.spline = interp, smooth_p, spline

    def eval(self, x):
        x = np.asarray(x, float)
        if self.interp is not None:
            return self.interp(x)
        return self.model.fn(self.c, x)

    def bounds(self, level=0.95):
        if self.cov is None or self.dfe <= 0:
            return np.full((2, self.c.size), np.nan)
        se = np.sqrt(np.maximum(np.diag(self.cov), 0))
        t = _st().t.ppf((1 + level) / 2, self.dfe)
        return np.vstack([self.c - t * se, self.c + t * se])

    def display_lines(self):
        m = self.model
        lines = ['     ' + m.label(), f'     f({m.indep}) = {m.text}']
        if m.kind == 'interp':
            if self.smooth_p is not None:
                lines += ['     Smoothing parameter:', f'       p = {_g(self.smooth_p)}']
            return lines
        b = self.bounds()
        lines.append('     Coefficients (with 95% confidence bounds):' if np.all(np.isfinite(b)) else '     Coefficients:')
        w = max(len(n) for n in m.coeffs)
        for i, n in enumerate(m.coeffs):
            line = f'       {n.ljust(w)} = {_g(self.c[i]).rjust(10)}'
            if np.all(np.isfinite(b[:, i])):
                line += f'  ({_g(b[0, i])}, {_g(b[1, i])})'
            lines.append(line)
        return lines

    def index(self, args):
        x = darr(args[0]).astype(float)
        return out(self.eval(x.reshape(-1)).reshape(x.shape))

    def getprop(self, name):
        if name in self.model.coeffs:
            return float(self.c[self.model.coeffs.index(name)])
        if name == 'p' and self.model.kind == 'interp':
            return Struct.scalar({'form': Char.of('pp'), 'breaks': out(np.unique(self.x).reshape(1, -1))})
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class 'cfit'.")

    def propnames(self):
        return list(self.model.coeffs)


# ---- fitting ----------------------------------------------------------------------------------------------------------------

_FIT_OPTS = ('StartPoint', 'Lower', 'Upper', 'Weights', 'Exclude', 'Robust', 'SmoothingParam', 'Normalize', 'Method',
             'MaxIter', 'MaxFunEvals', 'TolFun', 'TolX', 'Display', 'Algorithm', 'DiffMinChange', 'DiffMaxChange', 'Independent',
             'Dependent', 'Coefficients', 'Problem', 'Span')


def _opts(args):
    low = {n.lower(): n for n in _FIT_OPTS}
    got, rest = {}, []
    i = 0
    while i < len(args):
        a = args[i]
        if isinstance(a, Struct):
            for k in a.f:
                if k.lower() in low:
                    v = a.get1(k)
                    if numel(v):
                        got[low[k.lower()]] = v
            i += 1
            continue
        s = opt_str(a)
        if s is not None and s.lower() in low and i + 1 < len(args):
            got[low[s.lower()]] = args[i + 1]
            i += 2
            continue
        rest.append(a)
        i += 1
    return got, rest


def _vec(v):
    return darr(v).reshape(-1).astype(float)


def _model_of(spec, opts):
    if isinstance(spec, FitType):
        return spec.model
    if isinstance(spec, FH):
        return from_handle(spec)
    if type(spec) is Cell:
        coeffs = [py_str(c) for c in opts['Coefficients'].a.reshape(-1)] if 'Coefficients' in opts and type(opts['Coefficients']) is Cell else None
        indep = py_str(opts['Independent']) if 'Independent' in opts else 'x'
        return linear_terms([py_str(t) for t in spec.a.reshape(-1)], indep=indep, coeffs=coeffs)
    s = py_str(spec)
    m = library(s)
    if m is not None:
        return m
    indep = py_str(opts['Independent']) if 'Independent' in opts else 'x'
    if re.search(rf'\b{re.escape(indep)}\b', s):
        coeffs = [py_str(c) for c in opts['Coefficients'].a.reshape(-1)] if 'Coefficients' in opts and type(opts['Coefficients']) is Cell else None
        return custom(s, indep=indep, coeffs=coeffs)
    raise err('curvefit:fit:fittype', f"'{s}' is no model: give a library name (poly1, exp1, gauss2 ...) or an expression in {indep}.", 'fit')


def _fit(x, y, model, opts, w):
    from scipy.optimize import least_squares
    n = x.size
    p = len(model.coeffs)
    if model.kind == 'interp':
        return _fit_interp(x, y, model, opts, w)
    robust = py_str(opts['Robust']).lower() if 'Robust' in opts else 'off'
    robust = {'on': 'bisquare'}.get(robust, robust)
    if robust not in ('off', 'bisquare', 'lar'):
        raise err('curvefit:fit:Robust', "Robust is 'Off', 'On', 'Bisquare' or 'LAR'.", 'fit')
    linear = model.linear is not None and 'Lower' not in opts and 'Upper' not in opts
    if linear:
        B = model.linear(x)

        def solve(wt, c_prev):
            sw = np.sqrt(wt)
            c, *_ = np.linalg.lstsq(B * sw[:, None], y * sw, rcond=None)
            return c, B, {'algorithm': 'QR factorization and solve', 'iterations': 1, 'funcCount': 1, 'exitflag': 1, 'firstorderopt': 0.0, 'message': 'Success.'}
        c0 = None
    else:
        if 'StartPoint' in opts:
            c0 = _vec(opts['StartPoint'])
        elif model.start is not None:
            c0 = np.asarray(model.start(x, y), float)
        else:
            c0 = np.full(p, 1.0)
            R.write("Warning: Start point not provided: each coefficient starts at 1.\n", 'warn')
        if c0.size != p:
            raise err('curvefit:fit:StartPoint', f'StartPoint has a value for each of the {p} coefficients.', 'fit')
        lo = _vec(opts['Lower']) if 'Lower' in opts else np.full(p, -np.inf)
        hi = _vec(opts['Upper']) if 'Upper' in opts else np.full(p, np.inf)
        c0 = np.clip(c0, lo, hi)
        c0 = np.where(np.isfinite(c0), c0, np.clip(1.0, lo, hi))
        maxfev = int(darr(opts['MaxFunEvals']).flat[0]) if 'MaxFunEvals' in opts else 600
        tol = float(darr(opts['TolFun']).flat[0]) if 'TolFun' in opts else 1e-8

        def solve(wt, c_prev):
            sw = np.sqrt(wt)

            def res(c):
                with np.errstate(all='ignore'):
                    r = (model.fn(c, x) - y) * sw
                return np.where(np.isfinite(r), r, 1e100)
            r = least_squares(res, c_prev, bounds=(lo, hi), method='trf', x_scale='jac', max_nfev=maxfev, ftol=tol, xtol=tol, gtol=1e-12)
            ok = sw > 0
            J = np.zeros_like(r.jac)
            J[ok] = r.jac[ok] / sw[ok, None]
            if not np.all(ok):
                J[~ok] = _jac(model, r.x, x[~ok])
            return r.x, J, {'algorithm': 'trust-region-reflective', 'iterations': int(r.nfev), 'funcCount': int(r.nfev), 'exitflag': int(r.status > 0),
                            'firstorderopt': float(np.max(np.abs(r.grad))) if r.grad.size else 0.0, 'message': r.message}
    c, J, info = solve(w, c0)
    wv = w
    if robust != 'off':
        # iteratively reweighted: bisquare weights of the leverage-adjusted residuals over a robust scale (the median absolute
        # deviation, the p smallest left out), or 1/|r| for least absolute residuals
        Q = np.linalg.qr(J * np.sqrt(w)[:, None])[0]
        adj = 1 / np.sqrt(1 - np.minimum(0.9999, np.sum(Q ** 2, axis=1)))
        for it in range(50):
            r = (y - model.fn(c, x)) * adj
            rs = np.sort(np.abs(r))
            s = np.median(rs[max(p - 1, 0):]) / 0.6745 if rs.size else 0.0
            if s == 0:
                break
            if robust == 'bisquare':
                u = r / (4.685 * s)
                rw = (np.abs(u) < 1) * (1 - u ** 2) ** 2
            else:
                rw = 1 / np.maximum(np.abs(r), 1e-6 * s)
            wv = w * rw
            c_new, J, info2 = solve(wv, c)
            done = np.max(np.abs(c_new - c)) <= 1e-6 * max(np.max(np.abs(c_new)), 1e-12)
            c = c_new
            info = dict(info2, iterations=it + 2 if linear else info['iterations'] + info2['iterations'])
            if done:
                break
    fitted = model.fn(c, x)
    resid = y - fitted
    sse = float(np.sum(w * resid ** 2))
    dfe = n - p
    # the coefficients' variance from the final weights, with the weighted residual variance
    mse = float(np.sum(wv * resid ** 2)) / dfe if dfe > 0 else np.nan
    sw = np.sqrt(wv)
    try:
        cov = mse * np.linalg.pinv((J * sw[:, None]).T @ (J * sw[:, None]))
    except np.linalg.LinAlgError:
        cov = None
    return CFit(model, c, cov, dfe, sse, x, y, w), fitted, resid, J, info


def _jac(model, c, x):
    J = np.zeros((x.size, c.size))
    f0 = model.fn(c, x)
    for k in range(c.size):
        h = 1e-7 * max(abs(c[k]), 1.0)
        cc = c.copy()
        cc[k] += h
        J[:, k] = (model.fn(cc, x) - f0) / h
    return J


def _reinsch(x, w):
    """The banded matrices of the smoothing spline (Green and Silverman): Q (n by n-2, three diagonals) as its columns'
    entries, R (n-2 square, tridiagonal) and B = Q' W^-1 Q (five diagonals), banded as for scipy.linalg."""
    h = np.diff(x)
    m = x.size - 2
    q0, q1, q2 = 1 / h[:-1], -1 / h[:-1] - 1 / h[1:], 1 / h[1:]
    R = np.zeros((3, m))
    R[1] = (h[:-1] + h[1:]) / 3
    R[0, 1:] = h[1:-1] / 6
    R[2, :-1] = h[1:-1] / 6
    iw = 1 / w
    B = np.zeros((5, m))
    B[2] = q0 ** 2 * iw[:-2] + q1 ** 2 * iw[1:-1] + q2 ** 2 * iw[2:]
    d1 = q1[:-1] * q0[1:] * iw[1:-2] + q2[:-1] * q1[1:] * iw[2:-1]
    d2 = q2[:-2] * q0[2:] * iw[2:-2]
    B[1, 1:], B[3, :-1] = d1, d1
    B[0, 2:], B[4, :-2] = d2, d2
    return (q0, q1, q2), R, B


def _qt(q, y):
    return q[0] * y[:-2] + q[1] * y[1:-1] + q[2] * y[2:]


def _qg(q, g):
    r = np.zeros(g.size + 2)
    r[:-2] += q[0] * g
    r[1:-1] += q[1] * g
    r[2:] += q[2] * g
    return r


def _ss_solve(x, y, w, lam, mats=None):
    """Fitted values of the smoothing spline minimizing sum(w r^2) + lam*integral(f''^2), and the trace of I - A (the
    hat matrix A), from the Cholesky factor of M = R + lam*B and the band of M^-1 (Hutchinson and de Hoog)."""
    from scipy.linalg import cholesky_banded, cho_solve_banded
    q, R, B = mats or _reinsch(x, w)
    m = x.size - 2
    M = lam * B
    M[1:4] += R
    U = cholesky_banded(M[:3], lower=False)
    g = cho_solve_banded((U, False), _qt(q, y))
    f = y - lam * _qg(q, g) / w
    # M = U'U = L D L' with L unit lower; the band of S = M^-1 from the bottom up
    d = U[2] ** 2
    l1 = np.zeros(m)
    l2 = np.zeros(m)
    l1[:-1] = U[1, 1:] / U[2, :-1]
    l2[:-2] = U[0, 2:] / U[2, :-2]
    s0 = np.zeros(m + 2)
    s1 = np.zeros(m + 2)
    s2 = np.zeros(m + 2)
    for i in range(m - 1, -1, -1):
        s2[i] = -(l1[i] * s1[i + 1] + l2[i] * s0[i + 2])
        s1[i] = -(l1[i] * s0[i + 1] + l2[i] * s1[i + 1])
        s0[i] = 1 / d[i] - (l1[i] * s1[i] + l2[i] * s2[i])
    tr = lam * (np.sum(s0[:m] * B[2]) + 2 * np.sum(s1[:m - 1] * B[3, :-1]) + 2 * np.sum(s2[:m - 2] * B[4, :-2]))
    return f, tr


def _gcv_p(x, y, w):
    """The smoothing parameter p (lambda = (1-p)/p) of least generalized cross-validation (Craven and Wahba):
    n*sum(w r^2)/trace(I - A)^2 over a grid of lambda, refined around the best. Fits with less than one residual
    degree of freedom are left out: as lambda goes to 0 the criterion tends to a limit that can undercut the true
    minimum when two x lie close together."""
    from scipy.optimize import minimize_scalar
    if x.size < 4:
        return 1.0
    mats = _reinsch(x, w)
    _, R, B = mats
    scale = np.sum(R[1]) / np.sum(B[2])

    def gcv(s):
        f, tr = _ss_solve(x, y, w, scale * 256.0 ** (3 * s - 1), mats)
        return x.size * float(np.sum(w * (y - f) ** 2)) / tr ** 2 if tr >= 1 else np.inf
    grid = np.linspace(-1.5, 1.5, 31)
    vals = [gcv(s) for s in grid]
    k = int(np.argmin(vals))
    if not np.isfinite(vals[k]):
        return 1.0
    lo, hi = grid[max(k - 1, 0)], grid[min(k + 1, grid.size - 1)]
    r = minimize_scalar(gcv, bounds=(lo, hi), method='bounded', options={'xatol': 1e-5})
    s = r.x if r.fun <= vals[k] else grid[k]
    return 1 / (1 + scale * 256.0 ** (3 * s - 1))


def _smoothing_spline(x, y, w, p):
    """The natural cubic spline through the smoothing spline's fitted values (its second derivatives are the solution's);
    p = 1 interpolates, p = 0 is the least-squares line."""
    from scipy.interpolate import CubicSpline
    if x.size < 3 or p >= 1:
        f = y
    elif p <= 0:
        c = np.polyfit(x, y, 1, w=np.sqrt(w))
        f = np.polyval(c, x)
    else:
        f, _ = _ss_solve(x, y, w, (1 - p) / p)
    if x.size == 1:
        return lambda t: np.full(np.shape(t), f[0])
    if x.size == 2:
        return lambda t: f[0] + (np.asarray(t, float) - x[0]) * (f[1] - f[0]) / (x[1] - x[0])
    return CubicSpline(x, f, bc_type='natural')


def _fit_interp(x, y, model, opts, w):
    from scipy import interpolate as I
    o = np.argsort(x, kind='stable')
    xs, ys = x[o], y[o]
    xs, idx = np.unique(xs, return_index=True)
    ys = ys[idx]
    p = None
    if model.name == 'linearinterp':
        f = lambda t: np.interp(t, xs, ys, left=np.nan, right=np.nan)  # noqa: E731
    elif model.name == 'nearestinterp':
        g = I.interp1d(xs, ys, kind='nearest', bounds_error=False, fill_value=np.nan)
        f = lambda t: g(t)  # noqa: E731
    elif model.name == 'pchipinterp':
        f = I.PchipInterpolator(xs, ys, extrapolate=True)
    elif model.name == 'cubicinterp':
        f = I.CubicSpline(xs, ys, bc_type='not-a-knot' if xs.size > 3 else 'natural')
    else:
        ws = w[o][idx]
        if 'SmoothingParam' in opts:
            p = float(darr(opts['SmoothingParam']).flat[0])
            if not 0 <= p <= 1:
                raise err('MATLAB:fit:smoothingParam', 'SmoothingParam is from 0 to 1.', 'fit')
        else:
            p = _gcv_p(xs, ys, ws)
        f = _smoothing_spline(xs, ys, ws, p)
    fitted = f(x)
    resid = y - fitted
    sse = float(np.nansum(w * resid ** 2))
    cf = CFit(model, [], None, 0, sse, x, y, w, interp=lambda t: np.asarray(f(t), float), smooth_p=p if model.name == 'smoothingspline' else None,
              spline=f if hasattr(f, 'derivative') else None)
    return cf, fitted, resid, np.zeros((x.size, 0)), {'algorithm': model.name, 'iterations': 0, 'funcCount': 0, 'exitflag': 1, 'firstorderopt': 0.0, 'message': ''}


@bi('fit', nout=3)
def fit(nargout, *args):
    """[f, gof, output] = fit(x, y, fitType, Name, Value): a curve fitted to data."""
    nargchk(args, 3, 60, 'fit')
    opts, rest = _opts(list(args))
    xa = darr(rest[0], 'fit')
    if xa.ndim == 2 and min(xa.shape) > 1:
        raise err('curvefit:fit:xShape', 'x is a vector (a curve) or two columns [x y] (a surface).', 'fit')
    x, y = xa.reshape(-1).astype(float), _vec(rest[1])
    if x.size != y.size:
        raise err('curvefit:fit:xyLength', 'x and y must have the same number of values.', 'fit')
    model = _model_of(rest[2], opts)
    w = _vec(opts['Weights']) if 'Weights' in opts else np.ones(x.size)
    keep = np.isfinite(x) & np.isfinite(y) & np.isfinite(w)
    if 'Exclude' in opts:
        e = np.asarray(darr(opts['Exclude'])).reshape(-1)
        if e.dtype == bool or (e.size == x.size and set(np.unique(e)).issubset({0, 1})):
            keep &= ~e.astype(bool)
        else:
            keep[e.astype(int) - 1] = False
    xs, ys, ws = x[keep], y[keep], w[keep]
    if xs.size < (len(model.coeffs) if model.kind != 'interp' else 2):
        raise err('curvefit:fit:InsufficientData', f'There are fewer data points ({xs.size}) than coefficients to fit.', 'fit')
    cf, fitted, resid, J, info = _fit(xs, ys, model, opts, ws)
    if nargout < 2:
        return cf
    sst = float(np.sum(ws * (ys - np.average(ys, weights=ws)) ** 2))
    dfe = xs.size - (len(model.coeffs) if model.kind != 'interp' else 0)
    r2 = 1 - cf.sse / sst if sst > 0 else np.nan
    gof = Struct.scalar({'sse': cf.sse, 'rsquare': r2, 'dfe': float(dfe),
                         'adjrsquare': 1 - (1 - r2) * (xs.size - 1) / dfe if dfe > 0 else np.nan,
                         'rmse': math.sqrt(cf.sse / dfe) if dfe > 0 else np.nan})
    if nargout < 3:
        return cf, gof
    output = Struct.scalar({'numobs': float(xs.size), 'numparam': float(len(model.coeffs) if model.kind != 'interp' else 0),
                            'residuals': out(resid.reshape(-1, 1)), 'Jacobian': out(J), 'exitflag': float(info['exitflag']),
                            'firstorderopt': info['firstorderopt'], 'iterations': float(info['iterations']), 'funcCount': float(info['funcCount']),
                            'algorithm': Char.of(info['algorithm']), 'message': Char.of(str(info['message']))})
    return cf, gof, output


@bi('fittype')
def fittype(nargout, *args):
    """ft = fittype(libraryName), fittype(expression, 'independent', 'x', 'coefficients', {...}), fittype(@(a, b, x) ...): a model to fit."""
    nargchk(args, 1, 12, 'fittype')
    opts, rest = _opts(list(args))
    return FitType(_model_of(rest[0], opts))


@bi('fitoptions')
def fitoptions(nargout, *args):
    """opts = fitoptions(Name, Value, ...) or fitoptions(fitType, Name, Value): options for fit, as a struct."""
    opts, rest = _opts(list(args))
    d = {'Method': Char.of('NonlinearLeastSquares'), 'Robust': Char.of('Off'), 'StartPoint': EMPTY(), 'Lower': EMPTY(), 'Upper': EMPTY()}
    if rest and (is_str(rest[0]) or isinstance(rest[0], FitType)):
        m = _model_of(rest[0], opts)
        d['Method'] = Char.of('LinearLeastSquares' if m.linear is not None else ('SmoothingSpline' if m.name == 'smoothingspline' else 'Interpolant' if m.kind == 'interp' else 'NonlinearLeastSquares'))
    for k, v in opts.items():
        d[k] = v
    return Struct.scalar(d)


# ---- what a fit is asked -----------------------------------------------------------------------------------------------------

def _cfit(v, fn):
    if not isinstance(v, CFit):
        raise err(f'curvefit:{fn}:cfit', f'{fn} takes a fit (from fit).', fn)
    return v


@bi('confint')
def confint(nargout, *args):
    """ci = confint(f, level): the coefficients' confidence bounds (95 %), one column each."""
    nargchk(args, 1, 2, 'confint')
    f = _cfit(args[0], 'confint')
    level = float(darr(args[1]).flat[0]) if len(args) > 1 else 0.95
    return out(f.bounds(level))


@bi('predint', nout=2)
def predint(nargout, *args):
    """[ci, y] = predint(f, x, level, intopt, simopt): prediction bounds of a fit, for new observations ('observation') or the curve ('functional')."""
    nargchk(args, 2, 5, 'predint')
    f = _cfit(args[0], 'predint')
    x = _vec(args[1])
    level = float(darr(args[2]).flat[0]) if len(args) > 2 else 0.95
    obs = not (len(args) > 3 and py_str(args[3]).lower() == 'functional')
    sim = len(args) > 4 and py_str(args[4]).lower() == 'on'
    y = f.eval(x)
    if f.cov is None or f.dfe <= 0:
        return (out(np.full((x.size, 2), np.nan)), out(y.reshape(-1, 1))) if nargout > 1 else out(np.full((x.size, 2), np.nan))
    p = f.c.size
    if f.model.linear is not None:
        J = f.model.linear(x)
    else:
        J = np.empty((x.size, p))
        for j in range(p):
            h = math.sqrt(np.finfo(float).eps) * max(abs(f.c[j]), 1.0)
            cc = f.c.copy()
            cc[j] += h
            J[:, j] = (f.model.fn(cc, x) - y) / h
    var = np.einsum('ij,jk,ik->i', J, f.cov, J) + (f.sse / f.dfe if obs else 0)
    k = p + (1 if obs else 0)
    crit = math.sqrt(k * _st().f.ppf(level, k, f.dfe)) if sim else _st().t.ppf((1 + level) / 2, f.dfe)
    d = crit * np.sqrt(np.maximum(var, 0))
    ci = np.column_stack([y - d, y + d])
    return (out(ci), out(y.reshape(-1, 1))) if nargout > 1 else out(ci)


@bi('coeffvalues')
def coeffvalues(nargout, *args):
    """c = coeffvalues(f): a fit's coefficients, as a row."""
    nargchk(args, 1, 1, 'coeffvalues')
    return out(_cfit(args[0], 'coeffvalues').c.reshape(1, -1))


@bi('coeffnames')
def coeffnames(nargout, *args):
    """names = coeffnames(f): the names of a fit's (or a fittype's) coefficients, as a column."""
    nargchk(args, 1, 1, 'coeffnames')
    v = args[0]
    m = v.model if isinstance(v, (CFit, FitType)) else None
    if m is None:
        raise err('curvefit:coeffnames:fit', 'coeffnames takes a fit or a fittype.', 'coeffnames')
    return Cell.of_list([Char.of(n) for n in m.coeffs], (len(m.coeffs), 1))


@bi('numcoeffs')
def numcoeffs(nargout, *args):
    """n = numcoeffs(f): how many coefficients a fit or fittype has."""
    nargchk(args, 1, 1, 'numcoeffs')
    v = args[0]
    if not isinstance(v, (CFit, FitType)):
        raise err('curvefit:numcoeffs:fit', 'numcoeffs takes a fit or a fittype.', 'numcoeffs')
    return float(len(v.model.coeffs)) if v.model.kind != 'interp' else 0.0


@bi('differentiate', nout=2)
def differentiate(nargout, *args):
    """[fx, fxx] = differentiate(f, x): a fit's first (and second) derivatives at x."""
    nargchk(args, 2, 2, 'differentiate')
    f = _cfit(args[0], 'differentiate')
    xa = darr(args[1])
    x = xa.reshape(-1).astype(float)
    if f.model.kind == 'poly':
        d1, d2 = np.polyval(np.polyder(f.c), x), np.polyval(np.polyder(f.c, 2), x)
    elif hasattr(f.spline, 'derivative'):
        d1, d2 = f.spline.derivative()(x), f.spline.derivative(2)(x)
    else:
        # central differences, extrapolated (Richardson) from steps h and h/2
        h = 1e-3 * np.maximum(np.abs(x), 1.0)

        def diffs(h):
            y0, yp, ym = f.eval(x), f.eval(x + h), f.eval(x - h)
            return (yp - ym) / (2 * h), (yp - 2 * y0 + ym) / h ** 2
        a1, a2 = diffs(h)
        b1, b2 = diffs(h / 2)
        d1, d2 = (4 * b1 - a1) / 3, (4 * b2 - a2) / 3
    return (out(d1.reshape(xa.shape)), out(d2.reshape(xa.shape))) if nargout > 1 else out(d1.reshape(xa.shape))


@bi('integrate')
def integrate(nargout, *args):
    """y = integrate(f, x, x0): the integral of a fit from x0 to each x."""
    nargchk(args, 3, 3, 'integrate')
    f = _cfit(args[0], 'integrate')
    from scipy.integrate import quad
    xa = darr(args[1])
    x0 = float(darr(args[2]).flat[0])
    xs = xa.reshape(-1).astype(float)
    if f.model.kind == 'poly':
        P = np.polyint(f.c)
        r = np.polyval(P, xs) - np.polyval(P, x0)
    elif hasattr(f.spline, 'integrate'):
        r = np.array([f.spline.integrate(x0, v) for v in xs])
    else:
        r = np.array([quad(lambda t: float(f.eval(np.array([t]))[0]), x0, float(v), limit=200)[0] for v in xs])
    return out(r.reshape(xa.shape))


def _plot_fit(nargout, f, *rest):
    """plot(f), plot(f, x, y), plot(f, x, y, 'residuals'): the fit (and its data)."""
    words = [py_str(a).lower() for a in rest if is_str(a)]
    nums = [a for a in rest if not is_str(a)]
    if len(nums) >= 2:
        x, y = _vec(nums[0]), _vec(nums[1])
        lo, hi = float(np.min(x)), float(np.max(x))
    else:
        x = y = None
        lo, hi = (float(np.min(f.x)), float(np.max(f.x))) if f.x is not None and f.x.size else (0.0, 1.0)
    if 'residuals' in words and x is not None:
        r = y - f.eval(x)
        _b('plot', x.reshape(-1, 1), r.reshape(-1, 1), Char.of('.'))
        _b('hold', Char.of('on'))
        _b('plot', np.array([[lo], [hi]]), np.zeros((2, 1)), Char.of('-'))
        _b('hold', Char.of('off'))
        _b('legend', Char.of('data'), Char.of('zero line'))
        return None
    xx = np.linspace(lo, hi, 400)
    if x is not None:
        _b('plot', x.reshape(-1, 1), y.reshape(-1, 1), Char.of('.'))
        _b('hold', Char.of('on'))
    _b('plot', xx.reshape(-1, 1), f.eval(xx).reshape(-1, 1), Char.of('-'))
    if 'predobs' in words or 'predfunc' in words:
        ci = darr(predint(1, f, out(xx), 0.95, Char.of('observation' if 'predobs' in words else 'functional')))
        _b('plot', xx.reshape(-1, 1), ci, Char.of(':'))
    if x is not None:
        _b('hold', Char.of('off'))
        _b('legend', Char.of('data'), Char.of('fitted curve'))
    _b('xlabel', Char.of('x'))
    _b('ylabel', Char.of('y'))
    return None


def _b(name, *args):
    return R._builtin(name, *args)


# ---- smooth -------------------------------------------------------------------------------------------------------------------

def _moving(y, span):
    n = y.size
    out_ = np.empty(n)
    h = (span - 1) // 2
    for i in range(n):
        k = min(h, i, n - 1 - i)
        out_[i] = np.mean(y[i - k:i + k + 1])
    return out_


def _local(x, y, span, degree, robust):
    """Locally weighted regression (tricube weights over the span nearest points), with bisquare robustness weights."""
    n = y.size
    k = max(int(span), degree + 1)
    rw = np.ones(n)
    yy = np.empty(n)
    for it in range(6 if robust else 1):
        prev = yy.copy()
        for i in range(n):
            d = np.abs(x - x[i])
            idx = np.argsort(d, kind='stable')[:k]
            dmax = d[idx].max()
            u = d[idx] / (dmax if dmax > 0 else 1.0)
            w = (1 - u ** 3) ** 3 * rw[idx]
            if np.sum(w > 0) <= degree:
                # too few points keep weight: the previous pass stands (the data in the first)
                yy[i] = y[i] if it == 0 else prev[i]
                continue
            A = np.vander(x[idx] - x[i], degree + 1, increasing=True)
            sw = np.sqrt(w)
            c = np.linalg.lstsq(A * sw[:, None], y[idx] * sw, rcond=None)[0]
            yy[i] = c[0]
        if robust:
            r = y - yy
            s = np.median(np.abs(r))
            if s == 0:
                break
            u = r / (6 * s)
            rw = (np.abs(u) < 1) * (1 - u ** 2) ** 2
    return yy


@bi('smooth')
def smooth(nargout, *args):
    """yy = smooth(y), smooth(y, span), smooth(y, method), smooth(y, span, method), smooth(x, y, ...): smoothed data, as a column."""
    nargchk(args, 1, 5, 'smooth')
    words = [py_str(a).lower() for a in args if is_str(a)]
    method = words[0] if words else 'moving'
    if method not in ('moving', 'lowess', 'loess', 'sgolay', 'rlowess', 'rloess'):
        raise err('curvefit:smooth:method', "The method is 'moving', 'lowess', 'loess', 'sgolay', 'rlowess' or 'rloess'.", 'smooth')
    k = next((i for i, a in enumerate(args) if is_str(a)), len(args))
    # the numbers before the method: (x,) y and the span; after it, the degree of 'sgolay'
    nums, after = list(args[:k]), [a for a in args[k + 1:] if not is_str(a)]
    if len(nums) >= 2 and numel(nums[1]) == numel(nums[0]) and numel(nums[0]) > 1:
        x, y = _vec(nums[0]), _vec(nums[1])
        rest = nums[2:]
    else:
        y = _vec(nums[0])
        x = np.arange(1, y.size + 1, dtype=float)
        rest = nums[1:]
    n = y.size
    span = float(darr(rest[0]).flat[0]) if rest and numel(rest[0]) else 5.0
    degree = int(darr(after[0]).flat[0]) if after else 2
    if span < 1:
        span = math.ceil(span * n)
    span = int(span)
    if method in ('moving', 'sgolay') and span % 2 == 0:
        span -= 1
    span = max(1, min(span, n if n % 2 or method not in ('moving', 'sgolay') else n - 1))
    if method == 'moving':
        yy = _moving(y, span)
    elif method == 'sgolay':
        from scipy.signal import savgol_filter
        if span <= degree:
            raise err('curvefit:smooth:span', 'The span must be larger than the degree.', 'smooth')
        yy = savgol_filter(y, span, degree, mode='interp') if n >= span else y.copy()
    else:
        yy = _local(x, y, span, 1 if method in ('lowess', 'rlowess') else 2, method.startswith('r'))
    return out(yy.reshape(-1, 1))


# ---- fits through the builtins: feval(f, x), plot(f, ...), formula(f) ------------------------------------------------------------

def _wrap(name, test, handler):
    info = REG[name]
    orig = info.fn
    ws, aw = info.ws, info.aw
    if aw:
        async def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                return handler(a[1] if ws else a[0], *args)
            return await orig(*a)
    else:
        def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                return handler(a[1] if ws else a[0], *args)
            return orig(*a)
    info.fn = f


def _feval_fit(nargout, f, *rest):
    if isinstance(f, FitType):
        return f.index(list(rest))
    x = darr(rest[0]).astype(float)
    return out(f.eval(x.reshape(-1)).reshape(x.shape))


_wrap('feval', lambda v: isinstance(v, (CFit, FitType)), _feval_fit)
_wrap('plot', lambda v: isinstance(v, CFit), _plot_fit)
_wrap('formula', lambda v: isinstance(v, (CFit, FitType)), lambda nargout, f, *rest: Char.of(f.model.text))
