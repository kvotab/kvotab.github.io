"""Econometric models: arima (with seasonal parts, predictors, t innovations
and a conditional variance model), the conditional variance models garch,
egarch and gjr, and varm (vector autoregressions); with estimate, forecast,
simulate, infer, summarize, impulse, irf and fevd.

A coefficient that is NaN is estimated; a number is held fixed. Estimates
maximize the likelihood conditional on presample values: the first P
observations (or Y0) for the mean, zero presample innovations unless E0 is
given, and for a variance model the mean square of the innovations as its
presample. Standard errors come from the inverse of the numerical Hessian of
the log-likelihood.
"""
import math

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, darr, out, opt_str, is_str, sval, num
from ..values import MError, Obj, Char, Cell, Struct, Str, EMPTY, numel, py_str, class_of
from .. import runtime as R


def bi(*names, **kw):
    """Registered as builtins are, with what NumPy or SciPy refuses told as the function's own error."""
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, KeyError, ZeroDivisionError, np.linalg.LinAlgError, OverflowError) as e:
                raise err(f'econ:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _st():
    import scipy.stats as st
    return st


def _rs():
    from .elmat import RNG
    return RNG.rs


def _g(v):
    if isinstance(v, (float, int, np.floating)) and not np.isfinite(v):
        return 'NaN' if np.isnan(v) else ('Inf' if v > 0 else '-Inf')
    return f'{float(v):.5g}'


def _pairs(args, fn, names):
    pos, opts = [], {}
    k = 0
    args = list(args)
    while k < len(args):
        o = opt_str(args[k])
        if o is not None and o.lower() in names and k + 1 < len(args):
            opts[o.lower()] = args[k + 1]
            k += 2
            continue
        if opts or o is not None:
            raise err(f'econ:{fn}:InvalidOption', f"'{o if o is not None else class_of(args[k])}' is not an option of {fn}.", fn)
        pos.append(args[k])
        k += 1
    return pos, opts


def _col(v, fn, what):
    a = np.asarray(darr(v, fn), float)
    if a.ndim == 2 and a.shape[0] == 1:
        a = a.T
    return a


def _num1(v, fn, what):
    a = np.asarray(darr(v, fn), float).reshape(-1)
    if a.size != 1:
        raise err(f'econ:{fn}:InvalidValue', f'{what} is one number.', fn)
    return float(a[0])


def _cell_values(v, fn, what):
    """Coefficients given as a cell (or a vector) of numbers."""
    if type(v) is Cell:
        vals = []
        for c in v.a.reshape(-1, order='F'):
            a = np.asarray(darr(c), float).reshape(-1)
            if a.size != 1:
                raise err(f'econ:{fn}:InvalidCoefficients', f'{what} is a cell of numbers (NaN to estimate).', fn)
            vals.append(float(a[0]))
        return vals
    return [float(x) for x in np.asarray(darr(v, fn), float).reshape(-1)]


def _lags_of(values, lags, fn, what):
    """A dict lag -> coefficient from values and lags (either may be left out)."""
    if lags is not None:
        L = [int(x) for x in np.asarray(darr(lags), float).reshape(-1)]
        if any(x < 1 for x in L) or len(set(L)) != len(L):
            raise err(f'econ:{fn}:InvalidLags', f'{what} lags are distinct whole numbers from 1.', fn)
        if values is None:
            return {x: np.nan for x in L}
        if len(values) != len(L):
            raise err(f'econ:{fn}:LagsMismatch', f'{what} has a coefficient for each of its lags.', fn)
        return {x: v for x, v in zip(L, values) if v != 0}
    if values is None:
        return {}
    return {k + 1: v for k, v in enumerate(values) if v != 0}


def _lag_cell(d):
    """The coefficients as the property shows them: a cell from lag 1 to the largest, 0 at the lags not in the model."""
    m = max(d) if d else 0
    return Cell.of_list([float(d.get(k, 0.0)) for k in range(1, m + 1)], (1, m))


def _lag_text(d):
    if not d:
        return '{}'
    lags = sorted(d)
    vals = ' '.join(_g(d[k]) for k in lags)
    return f"{{{vals}}} at lag{'s' if len(lags) > 1 else ''} [{' '.join(str(k) for k in lags)}]"


def _dist_of(v, fn):
    if v is None:
        return {'Name': 'Gaussian'}
    if is_str(v):
        n = py_str(v).lower()
        if n == 'gaussian':
            return {'Name': 'Gaussian'}
        if n == 't':
            return {'Name': 't', 'DoF': np.nan}
    if type(v) is Struct and 'Name' in v.f:
        n = py_str(v.get1('Name')).lower()
        if n == 'gaussian':
            return {'Name': 'Gaussian'}
        if n == 't':
            dof = float(num(v.get1('DoF'))) if 'DoF' in v.f else np.nan
            if not (np.isnan(dof) or dof > 2):
                raise err(f'econ:{fn}:InvalidDoF', 'The t distribution\'s DoF is above 2 (or NaN to estimate).', fn)
            return {'Name': 't', 'DoF': dof}
    raise err(f'econ:{fn}:InvalidDistribution', "Distribution is 'Gaussian', 't' or struct('Name', 't', 'DoF', v).", fn)


def _dist_value(d):
    if d['Name'] == 'Gaussian':
        return Struct.scalar({'Name': Str(np.array([['Gaussian']], object))})
    return Struct.scalar({'Name': Str(np.array([['t']], object)), 'DoF': float(d['DoF'])})


def _dist_text(d):
    return 'Name = "Gaussian"' if d['Name'] == 'Gaussian' else f'Name = "t", DoF = {_g(d["DoF"])}'


def _loglik(e, v, dist, dof=None):
    """The log-likelihood of innovations e with variances v (Gaussian, or t standardized to variance v)."""
    if dist == 'Gaussian':
        return float(-0.5 * np.sum(np.log(2 * np.pi * v) + e ** 2 / v))
    from scipy.special import gammaln
    nu = dof
    c = gammaln((nu + 1) / 2) - gammaln(nu / 2) - 0.5 * np.log(np.pi * (nu - 2))
    return float(np.sum(c - 0.5 * np.log(v) - (nu + 1) / 2 * np.log1p(e ** 2 / ((nu - 2) * v))))


def _draw(dist, size, dof=None):
    rs = _rs()
    if dist == 'Gaussian':
        return rs.standard_normal(size)
    return rs.standard_t(dof, size) * math.sqrt((dof - 2) / dof)


def _hessian(f, x):
    """The Hessian of f at x by central differences."""
    n = x.size
    H = np.zeros((n, n))
    h = 1e-4 * np.maximum(np.abs(x), 1e-2)
    f0 = f(x)
    for i in range(n):
        ei = np.zeros(n)
        ei[i] = h[i]
        H[i, i] = (f(x + ei) - 2 * f0 + f(x - ei)) / h[i] ** 2
        for j in range(i):
            ej = np.zeros(n)
            ej[j] = h[j]
            H[i, j] = H[j, i] = (f(x + ei + ej) - f(x + ei - ej) - f(x - ei + ej) + f(x - ei - ej)) / (4 * h[i] * h[j])
    return H


def _cov_from(negll, x):
    if x.size == 0:
        return np.zeros((0, 0))
    H = _hessian(negll, x)
    try:
        C = np.linalg.inv(H)
    except np.linalg.LinAlgError:
        C = np.linalg.pinv(H)
    return (C + C.T) / 2


def _num_text(v, width, fmt):
    if not np.isfinite(v):
        t = 'NaN' if np.isnan(v) else ('Inf' if v > 0 else '-Inf')
        return f'{t:>{width}}'
    return f'{v:{width}{fmt}}'


def _tstats(vals, se):
    """t statistics and p-values; a parameter held fixed (standard error 0) has t Inf and p 0."""
    vals, se = np.asarray(vals, float), np.asarray(se, float)
    with np.errstate(divide='ignore', invalid='ignore'):
        t = np.where(se > 0, vals / np.where(se > 0, se, 1), np.where(vals == 0, np.nan, np.inf * np.sign(vals)))
    p = np.where(np.isnan(t), np.nan, 2 * _st().norm.sf(np.abs(np.nan_to_num(t, nan=0.0, posinf=1e300, neginf=-1e300))))
    return t, p


def _table_lines(title, names, vals, se):
    lines = ['', f'    {title}', '']
    w = max([len(n) for n in names] + [8])
    t, p = _tstats(vals, se)
    lines.append(' ' * (w + 4) + f'{"Value":>12}  {"StandardError":>14}  {"TStatistic":>11}  {"PValue":>11}')
    lines.append(' ' * (w + 4) + f'{"_" * 12:>12}  {"_" * 14:>14}  {"_" * 11:>11}  {"_" * 11:>11}')
    lines.append('')
    for n, v, s, ti, pi in zip(names, vals, se, t, p):
        lines.append(f'    {n:<{w}}{_num_text(v, 12, ".6g")}  {_num_text(s, 14, ".6g")}  {_num_text(ti, 11, ".5g")}  {_num_text(pi, 11, ".5g")}')
    return lines


def _results_table(names, vals, se):
    from .tables import Table
    vals, se = np.asarray(vals, float), np.asarray(se, float)
    t, p = _tstats(vals, se)
    return Table([vals.reshape(-1, 1), se.reshape(-1, 1), t.reshape(-1, 1), p.reshape(-1, 1)], ['Value', 'StandardError', 'TStatistic', 'PValue'],
                 rownames=list(names))


def _show(display, lines):
    if display != 'off':
        R.write('\n'.join(lines) + '\n')


# ---- conditional variance models -------------------------------------------------------------------------------------------

class CondVar(Obj):
    """garch, egarch and gjr: the variance of the innovations at each time from past variances and innovations."""
    is_handle = False

    def __init__(self, kind):
        self.kind = kind
        self.garch, self.arch, self.lev = {}, {}, {}
        self.const = np.nan
        self.offset = 0.0
        self.dist = {'Name': 'Gaussian'}
        self.desc = None
        self.name = 'Y'
        self.fit = None

    @property
    def cls(self):
        return self.kind

    def value_copy(self):
        import copy
        o = copy.copy(self)
        o.garch, o.arch, o.lev, o.dist = dict(self.garch), dict(self.arch), dict(self.lev), dict(self.dist)
        return o

    @property
    def P(self):
        return max(self.garch) if self.garch else 0

    @property
    def Q(self):
        return max([0] + list(self.arch) + list(self.lev))

    def label(self):
        return {'garch': 'GARCH', 'egarch': 'EGARCH', 'gjr': 'GJR'}[self.kind] + f'({self.P},{self.Q})'

    def description(self):
        if self.desc is not None:
            return self.desc
        d = 'Gaussian' if self.dist['Name'] == 'Gaussian' else 't'
        return f'{self.label()} Conditional Variance Model' + (' with Offset' if self.offset != 0 or np.isnan(self.offset) else '') + f' ({d} Distribution)'

    def uncond(self):
        if any(np.isnan(v) for v in list(self.garch.values()) + list(self.arch.values()) + list(self.lev.values()) + [self.const]):
            return np.nan
        g = sum(self.garch.values())
        if self.kind == 'egarch':
            return math.exp(self.const / (1 - g)) if g < 1 else np.nan
        s = g + sum(self.arch.values()) + (0.5 * sum(self.lev.values()) if self.kind == 'gjr' else 0)
        return self.const / (1 - s) if s < 1 else np.nan

    def props(self):
        p = ['Description', 'SeriesName', 'Distribution', 'P', 'Q', 'Constant', 'GARCH', 'ARCH']
        if self.kind != 'garch':
            p.append('Leverage')
        p.append('UnconditionalVariance')
        p.append('Offset')
        return p

    def getprop(self, name):
        k = name.lower()
        if k == 'description':
            return Str(np.array([[self.description()]], object))
        if k == 'seriesname':
            return Str(np.array([[self.name]], object))
        if k == 'distribution':
            return _dist_value(self.dist)
        if k == 'p':
            return float(self.P)
        if k == 'q':
            return float(self.Q)
        if k == 'constant':
            return float(self.const)
        if k == 'garch':
            return _lag_cell(self.garch)
        if k == 'arch':
            return _lag_cell(self.arch)
        if k == 'leverage' and self.kind != 'garch':
            return _lag_cell(self.lev)
        if k == 'unconditionalvariance':
            return float(self.uncond())
        if k == 'offset':
            return float(self.offset)
        return _method_or_fail(self, name)

    def setprop(self, name, value):
        k = name.lower()
        if k == 'constant':
            self.const = _num1(value, self.kind, 'Constant')
        elif k == 'garch':
            self.garch = _lags_of(_cell_values(value, self.kind, 'GARCH'), None, self.kind, 'GARCH')
        elif k == 'arch':
            self.arch = _lags_of(_cell_values(value, self.kind, 'ARCH'), None, self.kind, 'ARCH')
        elif k == 'leverage' and self.kind != 'garch':
            self.lev = _lags_of(_cell_values(value, self.kind, 'Leverage'), None, self.kind, 'Leverage')
        elif k == 'offset':
            self.offset = _num1(value, self.kind, 'Offset')
        elif k == 'distribution':
            self.dist = _dist_of(value, self.kind)
        elif k == 'description':
            self.desc = sval(value, 'Description', self.kind)
        elif k == 'seriesname':
            self.name = sval(value, 'SeriesName', self.kind)
        else:
            raise MError('MATLAB:class:SetProhibited', f"You cannot set the '{name}' property of {self.kind}.")
        self.fit = None

    def propnames(self):
        return self.props()

    def display_lines(self):
        rows = [('Description', f'"{self.description()}"'), ('SeriesName', f'"{self.name}"'), ('Distribution', _dist_text(self.dist)),
                ('P', str(self.P)), ('Q', str(self.Q)), ('Constant', _g(self.const)), ('GARCH', _lag_text(self.garch)), ('ARCH', _lag_text(self.arch))]
        if self.kind != 'garch':
            rows.append(('Leverage', _lag_text(self.lev)))
        rows += [('UnconditionalVariance', _g(self.uncond())), ('Offset', _g(self.offset))]
        w = max(len(r[0]) for r in rows)
        return [f'  {self.kind} with properties:', ''] + [f'    {k:>{w}}: {v}' for k, v in rows]

    # the parameters: (name, getter key) in a fixed order
    def param_slots(self):
        slots = [('Constant', ('const', None))]
        slots += [(f'GARCH{{{k}}}', ('garch', k)) for k in sorted(self.garch)]
        slots += [(f'ARCH{{{k}}}', ('arch', k)) for k in sorted(self.arch)]
        slots += [(f'Leverage{{{k}}}', ('lev', k)) for k in sorted(self.lev)]
        slots.append(('Offset', ('offset', None)))
        if self.dist['Name'] == 't':
            slots.append(('DoF', ('dof', None)))
        return slots

    def get_slot(self, key):
        what, k = key
        if what == 'const':
            return self.const
        if what == 'offset':
            return self.offset
        if what == 'dof':
            return self.dist['DoF']
        return getattr(self, what)[k]

    def set_slot(self, key, v):
        what, k = key
        if what == 'const':
            self.const = v
        elif what == 'offset':
            self.offset = v
        elif what == 'dof':
            self.dist['DoF'] = v
        else:
            getattr(self, what)[k] = v

    def variances(self, e, v0=None, e0=None):
        """The conditional variances of innovations e (after the offset is taken off), from presample variances v0 and
        innovations e0 (the mean square of e when not given)."""
        from scipy.signal import lfilter
        e = np.asarray(e, float)
        T = e.size
        P, Q = self.P, self.Q
        ms = float(np.mean(e ** 2)) if T else 1.0
        V0 = np.full(P, ms) if v0 is None else np.asarray(v0, float)[-P:] if P else np.zeros(0)
        if v0 is not None and P and V0.size < P:
            V0 = np.concatenate([np.full(P - V0.size, ms), V0])
        if self.kind == 'egarch':
            ez = math.sqrt(2 / math.pi) if self.dist['Name'] == 'Gaussian' else _abs_t_mean(self.dist['DoF'])
            logv = np.empty(T)
            past_lv = list(np.log(V0)) if P else []
            if e0 is None:
                past_z = [0.0] * Q
                past_az = [ez] * Q
            else:
                E0 = np.asarray(e0, float)[-Q:] if Q else np.zeros(0)
                sd = math.sqrt(ms)
                past_z = list(E0 / sd)
                past_az = [abs(z) for z in past_z]
                while len(past_z) < Q:
                    past_z.insert(0, 0.0)
                    past_az.insert(0, ez)
            G = [(k, v) for k, v in self.garch.items()]
            A = [(k, v) for k, v in self.arch.items()]
            L = [(k, v) for k, v in self.lev.items()]
            for t in range(T):
                lv = self.const
                for k, g in G:
                    lv += g * past_lv[-k]
                for k, a in A:
                    lv += a * (past_az[-k] - ez)
                for k, l in L:
                    lv += l * past_z[-k]
                lv = min(max(lv, -700.0), 700.0)
                logv[t] = lv
                z = e[t] / math.exp(lv / 2)
                past_lv.append(lv)
                past_z.append(z)
                past_az.append(abs(z))
            return np.exp(logv)
        E0sq = np.full(Q, ms) if e0 is None else (np.asarray(e0, float)[-Q:] ** 2 if Q else np.zeros(0))
        neg0 = np.full(Q, 0.5) if e0 is None else ((np.asarray(e0, float)[-Q:] < 0).astype(float) if Q else np.zeros(0))
        if e0 is not None and Q and E0sq.size < Q:
            E0sq = np.concatenate([np.full(Q - E0sq.size, ms), E0sq])
            neg0 = np.concatenate([np.full(Q - neg0.size, 0.5), neg0])
        e2 = np.concatenate([E0sq, e ** 2])
        neg = np.concatenate([neg0, (e < 0).astype(float)])
        u = np.full(T, self.const)
        for k, a in self.arch.items():
            u += a * e2[Q - k:Q - k + T]
        for k, l in self.lev.items():
            u += l * (neg * e2)[Q - k:Q - k + T]
        if not P:
            return u
        a = np.zeros(P + 1)
        a[0] = 1
        for k, g in self.garch.items():
            a[k] = -g
        # the recursion v(t) = u(t) + sum g_k v(t-k), started from V0
        from scipy.signal import lfiltic
        return lfilter([1.0], a, u, zi=lfiltic([1.0], a, y=V0[::-1]))[0]

    def check(self):
        """Whether the coefficients give positive, stationary variances."""
        g = sum(self.garch.values())
        if self.kind == 'egarch':
            return abs(g) < 1
        if self.const <= 0 or any(v < 0 for v in self.garch.values()):
            return False
        if self.kind == 'garch':
            return all(v >= 0 for v in self.arch.values()) and g + sum(self.arch.values()) < 1
        return all(self.arch.get(k, 0) >= 0 and self.arch.get(k, 0) + self.lev.get(k, 0) >= 0 for k in set(self.arch) | set(self.lev)) \
            and g + sum(self.arch.values()) + 0.5 * sum(self.lev.values()) < 1


def _abs_t_mean(nu):
    """E|z| for a t variable of nu degrees of freedom scaled to variance 1."""
    from scipy.special import gammaln
    return float(math.sqrt(nu - 2) * math.exp(gammaln((nu - 1) / 2) - gammaln(nu / 2)) / math.sqrt(math.pi))


def _make_condvar(kind, args):
    M = CondVar(kind)
    if args and not is_str(args[0]):
        if len(args) != 2:
            raise err(f'econ:{kind}:InvalidInput', f'{kind}(P, Q) takes the numbers of GARCH and ARCH lags.', kind)
        P, Q = int(_num1(args[0], kind, 'P')), int(_num1(args[1], kind, 'Q'))
        if P < 0 or Q < 0 or (P > 0 and Q == 0):
            raise err(f'econ:{kind}:InvalidDegrees', 'P and Q are whole numbers from 0; a model with GARCH lags has ARCH lags too.', kind)
        M.garch = {k: np.nan for k in range(1, P + 1)}
        M.arch = {k: np.nan for k in range(1, Q + 1)}
        if kind != 'garch':
            M.lev = {k: np.nan for k in range(1, Q + 1)}
        return M
    names = ('constant', 'garch', 'garchlags', 'arch', 'archlags', 'leverage', 'leveragelags', 'offset', 'distribution', 'description', 'seriesname')
    pos, o = _pairs(args, kind, names)
    M.garch = _lags_of(_cell_values(o['garch'], kind, 'GARCH') if 'garch' in o else None, o.get('garchlags'), kind, 'GARCH')
    M.arch = _lags_of(_cell_values(o['arch'], kind, 'ARCH') if 'arch' in o else None, o.get('archlags'), kind, 'ARCH')
    if kind != 'garch':
        M.lev = _lags_of(_cell_values(o['leverage'], kind, 'Leverage') if 'leverage' in o else None, o.get('leveragelags'), kind, 'Leverage')
    elif 'leverage' in o or 'leveragelags' in o:
        raise err('econ:garch:InvalidOption', 'A garch model has no Leverage terms: use gjr or egarch.', 'garch')
    if 'constant' in o:
        M.const = _num1(o['constant'], kind, 'Constant')
    if 'offset' in o:
        M.offset = _num1(o['offset'], kind, 'Offset')
    if 'distribution' in o:
        M.dist = _dist_of(o['distribution'], kind)
    if 'description' in o:
        M.desc = sval(o['description'], 'Description', kind)
    if 'seriesname' in o:
        M.name = sval(o['seriesname'], 'SeriesName', kind)
    return M


@bi('garch', arr=False)
def garch(nargout, *args):
    """Mdl = garch(P, Q) or garch('Name', value, ...): a GARCH conditional variance model."""
    return _make_condvar('garch', args)


@bi('egarch', arr=False)
def egarch(nargout, *args):
    """Mdl = egarch(P, Q) or egarch('Name', value, ...): an EGARCH conditional variance model (of the log variance)."""
    return _make_condvar('egarch', args)


@bi('gjr', arr=False)
def gjr(nargout, *args):
    """Mdl = gjr(P, Q) or gjr('Name', value, ...): a GJR conditional variance model (negative innovations weigh more)."""
    return _make_condvar('gjr', args)


# ---- ARIMA ------------------------------------------------------------------------------------------------------------------

def _polymul(a, b):
    return np.convolve(a, b)


def _lagpoly(d, sign):
    """1 + sign*sum(c_k L^k) as coefficients in L^0, L^1, ..."""
    m = max(d) if d else 0
    p = np.zeros(m + 1)
    p[0] = 1
    for k, v in d.items():
        p[k] = sign * v
    return p


class Arima(Obj):
    cls = 'arima'
    is_handle = False

    def __init__(self):
        self.ar, self.ma, self.sar, self.sma = {}, {}, {}, {}
        self.d, self.s = 0, 0
        self.const = np.nan
        self.var = np.nan               # a number, or a CondVar
        self.dist = {'Name': 'Gaussian'}
        self.beta = np.zeros(0)
        self.desc = None
        self.name = 'Y'
        self.fit = None

    def value_copy(self):
        import copy
        o = copy.copy(self)
        o.ar, o.ma, o.sar, o.sma, o.dist = dict(self.ar), dict(self.ma), dict(self.sar), dict(self.sma), dict(self.dist)
        o.beta = self.beta.copy()
        o.var = self.var.value_copy() if isinstance(self.var, CondVar) else self.var
        return o

    def a_poly(self):
        """The whole autoregressive operator: AR times SAR times the differences."""
        p = _polymul(_lagpoly(self.ar, -1), _lagpoly(self.sar, -1))
        for _ in range(self.d):
            p = _polymul(p, [1.0, -1.0])
        if self.s:
            sd = np.zeros(self.s + 1)
            sd[0], sd[-1] = 1, -1
            p = _polymul(p, sd)
        return p

    def b_poly(self):
        return _polymul(_lagpoly(self.ma, 1), _lagpoly(self.sma, 1))

    @property
    def P(self):
        return len(self.a_poly()) - 1

    @property
    def Q(self):
        return len(self.b_poly()) - 1

    def label(self):
        p, q = (max(self.ar) if self.ar else 0), (max(self.ma) if self.ma else 0)
        name = 'ARIMAX' if self.beta.size else 'ARIMA'
        t = f'{name}({p},{self.d},{q}) Model'
        if self.s:
            t += ' Seasonally Integrated'
        parts = [f'{nm}({max(d)})' for nm, d in (('AR', self.sar), ('MA', self.sma)) if d]
        if parts:
            t += ' with Seasonal ' + ' and '.join(parts)
        return t

    def description(self):
        if self.desc is not None:
            return self.desc
        d = 'Gaussian' if self.dist['Name'] == 'Gaussian' else 't'
        return f'{self.label()} ({d} Distribution)'

    PROPS = ['Description', 'SeriesName', 'Distribution', 'P', 'D', 'Q', 'Constant', 'AR', 'SAR', 'MA', 'SMA', 'Seasonality', 'Beta', 'Variance']

    def getprop(self, name):
        k = name.lower()
        if k == 'description':
            return Str(np.array([[self.description()]], object))
        if k == 'seriesname':
            return Str(np.array([[self.name]], object))
        if k == 'distribution':
            return _dist_value(self.dist)
        if k == 'p':
            return float(self.P)
        if k == 'd':
            return float(self.d)
        if k == 'q':
            return float(self.Q)
        if k == 'constant':
            return float(self.const)
        if k in ('ar', 'sar', 'ma', 'sma'):
            return _lag_cell(getattr(self, k))
        if k == 'seasonality':
            return float(self.s)
        if k == 'beta':
            return out(self.beta.reshape(1, -1)) if self.beta.size else out(np.zeros((1, 0)))
        if k == 'variance':
            return self.var if isinstance(self.var, CondVar) else float(self.var)
        return _method_or_fail(self, name)

    def setprop(self, name, value):
        k = name.lower()
        if k == 'constant':
            self.const = _num1(value, 'arima', 'Constant')
        elif k in ('ar', 'sar', 'ma', 'sma'):
            setattr(self, k, _lags_of(_cell_values(value, 'arima', k.upper()), None, 'arima', k.upper()))
        elif k == 'd':
            d = _num1(value, 'arima', 'D')
            if d < 0 or d != int(d):
                raise err('econ:arima:InvalidD', 'D is a whole number from 0.', 'arima')
            self.d = int(d)
        elif k == 'seasonality':
            s = _num1(value, 'arima', 'Seasonality')
            if s < 0 or s != int(s):
                raise err('econ:arima:InvalidSeasonality', 'Seasonality is a whole number from 0.', 'arima')
            self.s = int(s)
        elif k == 'variance':
            self.var = value.value_copy() if isinstance(value, CondVar) else _num1(value, 'arima', 'Variance')
            if not isinstance(self.var, CondVar) and not (np.isnan(self.var) or self.var > 0):
                raise err('econ:arima:InvalidVariance', 'Variance is positive (NaN to estimate), or a garch, egarch or gjr model.', 'arima')
        elif k == 'beta':
            self.beta = np.asarray(darr(value), float).reshape(-1)
        elif k == 'distribution':
            self.dist = _dist_of(value, 'arima')
        elif k == 'description':
            self.desc = sval(value, 'Description', 'arima')
        elif k == 'seriesname':
            self.name = sval(value, 'SeriesName', 'arima')
        else:
            raise MError('MATLAB:class:SetProhibited', f"You cannot set the '{name}' property of arima.")
        self.fit = None

    def propnames(self):
        return list(self.PROPS)

    def display_lines(self):
        var = (f'[{self.var.label()} Model]' if isinstance(self.var, CondVar) else _g(self.var))
        rows = [('Description', f'"{self.description()}"'), ('SeriesName', f'"{self.name}"'), ('Distribution', _dist_text(self.dist)),
                ('P', str(self.P)), ('D', str(self.d)), ('Q', str(self.Q)), ('Constant', _g(self.const)), ('AR', _lag_text(self.ar)),
                ('SAR', _lag_text(self.sar)), ('MA', _lag_text(self.ma)), ('SMA', _lag_text(self.sma)), ('Seasonality', str(self.s)),
                ('Beta', '[' + ' '.join(_g(b) for b in self.beta) + ']' if self.beta.size else '[1×0]'), ('Variance', var)]
        w = max(len(r[0]) for r in rows)
        return ['  arima with properties:', ''] + [f'    {k:>{w}}: {v}' for k, v in rows]

    def param_slots(self):
        slots = [('Constant', ('const', None))]
        for nm, attr in (('AR', 'ar'), ('SAR', 'sar'), ('MA', 'ma'), ('SMA', 'sma')):
            slots += [(f'{nm}{{{k}}}', (attr, k)) for k in sorted(getattr(self, attr))]
        slots += [(f'Beta({k + 1})', ('beta', k)) for k in range(self.beta.size)]
        if not isinstance(self.var, CondVar):
            slots.append(('Variance', ('var', None)))
        if self.dist['Name'] == 't':
            slots.append(('DoF', ('dof', None)))
        return slots

    def get_slot(self, key):
        what, k = key
        if what == 'const':
            return self.const
        if what == 'var':
            return self.var
        if what == 'dof':
            return self.dist['DoF']
        if what == 'beta':
            return self.beta[k]
        return getattr(self, what)[k]

    def set_slot(self, key, v):
        what, k = key
        if what == 'const':
            self.const = v
        elif what == 'var':
            self.var = v
        elif what == 'dof':
            self.dist['DoF'] = v
        elif what == 'beta':
            self.beta[k] = v
        else:
            getattr(self, what)[k] = v

    def stationary(self):
        p = _polymul(_lagpoly(self.ar, -1), _lagpoly(self.sar, -1))
        return _roots_outside(p)

    def invertible(self):
        return _roots_outside(self.b_poly())

    def innovations(self, y, y0, e0, X):
        """The innovations of the observations y (after the presample y0), e0 the presample innovations (zeros unless
        given), X the predictors' rows for y."""
        from scipy.signal import lfilter
        a, b = self.a_poly(), self.b_poly()
        P, Q = a.size - 1, b.size - 1
        full = np.concatenate([y0, y])
        n = y.size
        # w(t) = a(L) y(t) - c - x(t) beta
        w = np.convolve(full, a)[P:P + n] if P else y.copy()
        w = w - self.const
        if self.beta.size:
            w = w - X @ self.beta
        if not Q:
            return w
        if e0 is None or not np.any(e0):
            return lfilter([1.0], b, w)
        from scipy.signal import lfiltic
        E0 = np.zeros(Q)
        e0 = np.asarray(e0, float)[-Q:]
        E0[Q - e0.size:] = e0
        zi = lfiltic([1.0], b, y=E0[::-1])
        return lfilter([1.0], b, w, zi=zi)[0]

    def psi(self, n):
        """The first n weights of b(L)/a(L)."""
        from scipy.signal import lfilter
        imp = np.zeros(n)
        imp[0] = 1
        return lfilter(self.b_poly(), self.a_poly(), imp)


def _roots_outside(p):
    p = np.trim_zeros(np.asarray(p, float), 'b')
    if p.size <= 1:
        return True
    if not np.all(np.isfinite(p)):
        return False
    r = np.roots(p[::-1])
    return bool(np.all(np.abs(r) > 1 + 1e-8))


def _method_or_fail(obj, name):
    meths = {'estimate', 'forecast', 'simulate', 'infer', 'summarize', 'impulse', 'irf', 'fevd'}
    if name in meths:
        from ..classdef import BoundBuiltin
        return BoundBuiltin(obj, name)
    raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{obj.cls}'.")


@bi('arima', arr=False)
def arima(nargout, *args):
    """Mdl = arima, arima(p, D, q) or arima('Name', value, ...): an ARIMA model of a series."""
    M = Arima()
    if args and not is_str(args[0]):
        if len(args) != 3:
            raise err('econ:arima:InvalidInput', 'arima(p, D, q) takes the AR degree, the integration and the MA degree.', 'arima')
        p, d, q = (int(_num1(a, 'arima', 'p, D and q')) for a in args)
        if min(p, d, q) < 0:
            raise err('econ:arima:InvalidDegrees', 'p, D and q are whole numbers from 0.', 'arima')
        M.ar = {k: np.nan for k in range(1, p + 1)}
        M.ma = {k: np.nan for k in range(1, q + 1)}
        M.d = d
        return M
    names = ('ar', 'arlags', 'ma', 'malags', 'sar', 'sarlags', 'sma', 'smalags', 'd', 'seasonality', 'constant', 'variance', 'distribution', 'beta',
             'description', 'seriesname')
    pos, o = _pairs(args, 'arima', names)
    for attr in ('ar', 'ma', 'sar', 'sma'):
        vals = _cell_values(o[attr], 'arima', attr.upper()) if attr in o else None
        setattr(M, attr, _lags_of(vals, o.get(attr + 'lags'), 'arima', attr.upper()))
    for key, prop in (('d', 'D'), ('seasonality', 'Seasonality'), ('constant', 'Constant'), ('variance', 'Variance'), ('distribution', 'Distribution'),
                      ('beta', 'Beta'), ('description', 'Description'), ('seriesname', 'SeriesName')):
        if key in o:
            M.setprop(prop, o[key])
    return M


# ---- estimation ---------------------------------------------------------------------------------------------------------------

def _free_slots(M):
    """The model's parameters to estimate (NaN) and to hold (numbers), the variance model's after the mean's."""
    slots = [(nm, M, key) for nm, key in M.param_slots()]
    if isinstance(M, Arima) and isinstance(M.var, CondVar):
        slots += [(nm, M.var, key) for nm, key in M.var.param_slots() if key[0] != 'offset']
    return slots


def _arima_parts(M, y, opts, fn):
    """Presample, sample and predictors for an ARIMA fit or inference."""
    P = M.P
    y = np.asarray(y, float).reshape(-1)
    if 'y0' in opts:
        y0 = _col(opts['y0'], fn, 'Y0').reshape(-1)
        if y0.size < P:
            raise err(f'econ:{fn}:Y0', f'Y0 has at least P = {P} values.', fn)
        y0 = y0[y0.size - P:] if P else np.zeros(0)
        ys = y
    else:
        if y.size <= P:
            raise err(f'econ:{fn}:TooFew', f'The series is longer than P = {P}, the presample it needs.', fn)
        y0, ys = y[:P], y[P:]
    e0 = _col(opts['e0'], fn, 'E0').reshape(-1) if 'e0' in opts else None
    X = None
    if M.beta.size or 'x' in opts:
        if 'x' not in opts:
            raise err(f'econ:{fn}:NoPredictors', 'The model has Beta: give the predictors X.', fn)
        X = np.asarray(darr(opts['x']), float)
        if X.ndim == 1 or X.shape[0] == 1 and X.shape[1] != M.beta.size:
            X = X.reshape(-1, 1)
        if X.shape[0] < ys.size:
            raise err(f'econ:{fn}:XRows', f'X has at least as many rows as the sample ({ys.size}).', fn)
        X = X[X.shape[0] - ys.size:]
    return y0, ys, e0, X


def _starts(M, y0, ys, X, opts):
    """Starting values: AR, constant and Beta from least squares on the lags (the MA parts at 0)."""
    full = np.concatenate([y0, ys])
    lags = sorted(M.ar)
    n = ys.size
    P0 = y0.size
    # differences first
    z = full.copy()
    for _ in range(M.d):
        z = np.diff(z)
    if M.s:
        z = z[M.s:] - z[:-M.s]
    m = max(lags) if lags else 0
    cols = [np.ones(z.size - m)] + [z[m - k:z.size - k] for k in lags]
    if X is not None and M.beta.size:
        cols += [X[-(z.size - m):, j] for j in range(X.shape[1])] if z.size - m <= X.shape[0] else []
    st = {}
    if z.size - m > len(cols) + 1:
        A = np.column_stack(cols)
        c, *_ = np.linalg.lstsq(A, z[m:], rcond=None)
        st['const'] = c[0]
        for i, k in enumerate(lags):
            st[('ar', k)] = float(np.clip(c[1 + i], -0.9, 0.9)) if len(lags) == 1 else float(c[1 + i])
        res = z[m:] - A @ c
        st['var'] = float(np.var(res)) if res.size else float(np.var(z))
        if len(cols) > 1 + len(lags):
            for j in range(len(cols) - 1 - len(lags)):
                st[('beta', j)] = float(c[1 + len(lags) + j])
    else:
        st['const'] = float(np.mean(z)) if z.size else 0.0
        st['var'] = float(np.var(z)) if z.size > 1 else 1.0
    return st


def _fit(M, y, opts, fn='estimate'):
    """M with its NaN parameters estimated: (EstMdl, the parameters' covariance, logL, info, names, values)."""
    from scipy.optimize import minimize
    M = M.value_copy()
    slots = _free_slots(M)
    free = [(nm, obj, key) for nm, obj, key in slots if np.isnan(obj.get_slot(key))]
    if isinstance(M, Arima):
        y0, ys, e0, X = _arima_parts(M, y, opts, fn)
        st = _starts(M, y0, ys, X, opts)
        x0 = []
        for nm, obj, key in free:
            what = key[0]
            if obj is M:
                if what == 'const':
                    v = st.get('const', 0.0)
                elif what in ('ar', 'sar'):
                    v = st.get(key, 0.1) if what == 'ar' else 0.1
                elif what in ('ma', 'sma'):
                    v = 0.1
                elif what == 'beta':
                    v = st.get(key, 0.0)
                elif what == 'var':
                    v = max(st.get('var', 1.0), 1e-8)
                else:
                    v = 10.0
            else:
                v = _var_start(obj, key, st.get('var', 1.0))
            x0.append(v)
    else:
        e = np.asarray(y, float).reshape(-1)
        x0 = []
        for nm, obj, key in free:
            x0.append(_var_start(obj, key, float(np.var(e)) if e.size > 1 else 1.0, float(np.mean(e))))
    x0 = np.asarray(x0, float)
    for k, v in opts.get('initial', {}).items():
        for i, (nm, obj, key) in enumerate(free):
            if nm == k:
                x0[i] = v
    concentrate = isinstance(M, Arima) and not isinstance(M.var, CondVar) and M.dist['Name'] == 'Gaussian' and np.isnan(M.var)
    idx_var = [i for i, (nm, obj, key) in enumerate(free) if key == ('var', None) and obj is M]

    def load(x):
        for (nm, obj, key), v in zip(free, x):
            obj.set_slot(key, float(v))

    def negll(x, conc=False):
        load(x)
        try:
            if isinstance(M, Arima):
                if not (M.stationary() and M.invertible()):
                    return 1e12
                e = M.innovations(ys, y0, e0, X)
                if not np.all(np.isfinite(e)):
                    return 1e12
                if isinstance(M.var, CondVar):
                    if not M.var.check():
                        return 1e12
                    v = M.var.variances(e)
                elif conc:
                    v = np.full(e.size, max(float(np.mean(e ** 2)), 1e-300))
                else:
                    if not M.var > 0:
                        return 1e12
                    v = np.full(e.size, M.var)
                dist = M.dist
            else:
                if not M.check():
                    return 1e12
                e = np.asarray(y, float).reshape(-1) - M.offset
                v = M.variances(e, opts.get('v0'), opts.get('e0'))
                dist = M.dist
            if dist['Name'] == 't' and not dist['DoF'] > 2.0001:
                return 1e12
            if not np.all(np.isfinite(v)) or np.any(v <= 0):
                return 1e12
            r = -_loglik(e, v, dist['Name'], dist.get('DoF'))
            return r if np.isfinite(r) else 1e12
        except (np.linalg.LinAlgError, ValueError, OverflowError, FloatingPointError):
            return 1e12

    if free:
        keep = [i for i in range(len(free)) if not (concentrate and i in idx_var)]
        xk0 = x0[keep]

        def obj_k(xk):
            x = x0.copy()
            x[keep] = xk
            return negll(x, conc=concentrate)
        best = None
        if xk0.size:
            with np.errstate(all='ignore'):
                r1 = minimize(obj_k, xk0, method='BFGS', options={'gtol': 1e-8, 'maxiter': 2000})
                cand = [r1]
                r2 = minimize(obj_k, r1.x, method='Nelder-Mead', options={'xatol': 1e-10, 'fatol': 1e-12, 'maxiter': 20000, 'maxfev': 40000})
                cand.append(r2)
                if r2.fun < r1.fun - 1e-9:
                    cand.append(minimize(obj_k, r2.x, method='BFGS', options={'gtol': 1e-9, 'maxiter': 2000}))
            best = min(cand, key=lambda r: r.fun)
            xbest = x0.copy()
            xbest[keep] = best.x
        else:
            xbest = x0.copy()
        if concentrate:
            load(xbest)
            e = M.innovations(ys, y0, e0, X)
            for i in idx_var:
                xbest[i] = float(np.mean(e ** 2))
        load(xbest)
        nll = negll(xbest)
        if nll >= 1e12:
            raise err(f'econ:{fn}:NoFit', 'No coefficients make the model stationary, invertible and its variances positive from these starting values.', fn)
        cov = _cov_from(lambda x: negll(x), xbest)
        exitflag = 1.0 if best is None or best.success or best.fun <= nll + 1e-6 else 0.0
    else:
        xbest = x0
        nll = negll(xbest)
        if nll >= 1e12:
            raise err(f'econ:{fn}:NoFit', 'The model given is not stationary, not invertible or has variances that are not positive.', fn)
        cov = np.zeros((0, 0))
        exitflag = 1.0
    load(xbest)
    logL = -nll
    names = [nm for nm, obj, key in slots]
    values = np.array([float(obj.get_slot(key)) for nm, obj, key in slots])
    se = np.zeros(len(slots))
    full_cov = np.zeros((len(slots), len(slots)))
    fi = [i for i, (nm, obj, key) in enumerate(slots) if any(o is obj and k == key for _, o, k in free)]
    for a, i in enumerate(fi):
        for b, j in enumerate(fi):
            full_cov[i, j] = cov[a, b]
    se[fi] = np.sqrt(np.maximum(np.diag(cov), 0))
    nobs = (ys.size if isinstance(M, Arima) else np.asarray(y).size)
    M.fit = {'names': names, 'values': values, 'se': se, 'logL': logL, 'n': nobs, 'k': len(free), 'cov': full_cov,
             'mean': sum(1 for nm, obj, key in slots if obj is M)}
    info = Struct.scalar({'exitflag': exitflag, 'X': out(values.reshape(-1, 1)), 'X0': out(np.array([float(v) for v in x0]).reshape(-1, 1)) if x0.size else EMPTY()})
    return M, full_cov, logL, info


def _var_start(obj, key, var, mean=0.0):
    what, k = key
    P = max(obj.P, 1)
    Q = max(obj.Q, 1)
    if obj.kind == 'egarch':
        if what == 'const':
            return math.log(max(var, 1e-12)) * (1 - 0.7)
        if what == 'garch':
            return 0.7 / P
        if what == 'arch':
            return 0.1 / Q
        if what == 'lev':
            return 0.0
    else:
        if what == 'const':
            return max(var, 1e-12) * 0.1
        if what == 'garch':
            return 0.7 / P
        if what == 'arch':
            return 0.15 / Q
        if what == 'lev':
            return 0.05 / Q
    if what == 'offset':
        return mean
    if what == 'dof':
        return 10.0
    return 0.1


def _fit_lines(M):
    f = M.fit
    if isinstance(M, Arima) and isinstance(M.var, CondVar):
        k = f['mean']
        return (_table_lines(M.description() + ':', f['names'][:k], f['values'][:k], f['se'][:k])
                + _table_lines(M.var.description() + ':', f['names'][k:], f['values'][k:], f['se'][k:]))
    return _table_lines(M.description() + ':', f['names'], f['values'], f['se'])


# ---- the methods -------------------------------------------------------------------------------------------------------------

def _model(v, fn, kinds=None):
    ok = (Arima, CondVar, Varm) if kinds is None else kinds
    if not isinstance(v, ok):
        raise err(f'econ:{fn}:InvalidModel', f'{fn} takes an arima, garch, egarch, gjr or varm model.', fn)
    return v


def _display_opt(opts, default='params'):
    d = (opt_str(opts['display']) or default).lower() if 'display' in opts else default
    if d not in ('off', 'params', 'full', 'iter', 'table', 'diagnostics'):
        raise err('econ:estimate:InvalidDisplay', "Display is 'off', 'params', 'full' or 'iter'.", 'estimate')
    return d


_EST_OPTS = ('y0', 'e0', 'v0', 'x', 'display', 'constant0', 'ar0', 'ma0', 'sar0', 'sma0', 'beta0', 'variance0', 'dof0', 'garch0', 'arch0', 'leverage0', 'offset0', 'options')


@bi('estimate', nout=4, arr=False)
def estimate(nargout, *args):
    """[EstMdl, EstParamCov, logL, info] = estimate(Mdl, y, Name, Value):
    the model's NaN parameters estimated by maximum likelihood (for varm:
    [EstMdl, EstSE, logL, E])."""
    nargchk(args, 2, 40, 'estimate')
    M = _model(args[0], 'estimate')
    pos, opts = _pairs(args[2:], 'estimate', _EST_OPTS)
    if isinstance(M, Varm):
        return _varm_estimate(nargout, M, args[1], opts)
    y = _col(args[1], 'estimate', 'y')
    if y.ndim != 2 or y.shape[1] != 1:
        raise err('econ:estimate:InvalidData', 'y is a vector.', 'estimate')
    y = y.reshape(-1)
    if not np.all(np.isfinite(y)):
        y = y[np.isfinite(y)]
    if isinstance(M, CondVar):
        if 'v0' in opts:
            opts['v0'] = _col(opts['v0'], 'estimate', 'V0').reshape(-1)
        if 'e0' in opts:
            opts['e0'] = _col(opts['e0'], 'estimate', 'E0').reshape(-1)
    initial = {}
    for key, nm in (('constant0', 'Constant'), ('variance0', 'Variance'), ('dof0', 'DoF'), ('offset0', 'Offset')):
        if key in opts:
            initial[nm] = float(num(opts[key]))
    opts['initial'] = initial
    Est, cov, logL, info = _fit(M, y, opts)
    _show(_display_opt(opts), _fit_lines(Est))
    vals = (Est, out(cov), logL, info)
    return vals[:max(nargout, 1)] if nargout > 1 else Est


def _cond_innov(M, Y0, X0, E0):
    """Presample responses (the last P), with innovations inferred from Y0 when it is longer than P (else E0, or zeros)."""
    P, Q = M.P, M.Q
    y0 = Y0[Y0.size - P:] if P else np.zeros(0)
    if E0 is not None:
        return y0, E0
    if Y0.size > P and Q:
        e = M.innovations(Y0[P:], Y0[:P], None, X0[-(Y0.size - P):] if X0 is not None else None)
        return y0, e
    return y0, np.zeros(Q)


@bi('forecast', nout=3, arr=False)
def forecast(nargout, *args):
    """[Y, YMSE] = forecast(Mdl, numperiods, Y0, Name, Value): minimum mean
    square error forecasts and their mean square errors (for garch, egarch
    and gjr the forecast conditional variances)."""
    nargchk(args, 2, 20, 'forecast')
    M = _model(args[0], 'forecast')
    h = int(_num1(args[1], 'forecast', 'numperiods'))
    if h < 1:
        raise err('econ:forecast:InvalidHorizon', 'numperiods is a whole number from 1.', 'forecast')
    rest = list(args[2:])
    Y0 = None
    if rest and not is_str(rest[0]):
        Y0 = rest.pop(0)
    pos, opts = _pairs(rest, 'forecast', ('y0', 'e0', 'v0', 'x0', 'xf'))
    if Y0 is None and 'y0' in opts:
        Y0 = opts['y0']
    _complete(M, 'forecast')
    if isinstance(M, Varm):
        return _varm_forecast(nargout, M, h, Y0, opts)
    if isinstance(M, CondVar):
        Y0a = _col(Y0, 'forecast', 'Y0') if Y0 is not None else np.zeros((0, 1))
        paths = []
        for j in range(max(Y0a.shape[1] if Y0a.ndim == 2 else 1, 1)):
            e = (Y0a[:, j] if Y0a.size else np.zeros(0)) - M.offset
            V = _condvar_forecast(M, e, h, opts)
            paths.append(V)
        return out(np.column_stack(paths))
    Y0a = _col(Y0, 'forecast', 'Y0') if Y0 is not None else np.zeros((0, 1))
    if Y0a.shape[0] < M.P:
        raise err('econ:forecast:Y0', f'Y0 holds at least P = {M.P} presample responses.', 'forecast')
    X0 = np.asarray(darr(opts['x0']), float) if 'x0' in opts else None
    XF = np.asarray(darr(opts['xf']), float) if 'xf' in opts else None
    if M.beta.size and XF is None:
        raise err('econ:forecast:NoXF', 'The model has Beta: give the predictors over the forecast period, XF.', 'forecast')
    if XF is not None and XF.ndim == 2 and XF.shape[0] == 1 and M.beta.size != 1:
        XF = XF.reshape(1, -1)
    E0 = _col(opts['e0'], 'forecast', 'E0') if 'e0' in opts else None
    a, b = M.a_poly(), M.b_poly()
    P, Q = a.size - 1, b.size - 1
    outs, mses = [], []
    psi = M.psi(h)
    for j in range(Y0a.shape[1]):
        y0, e0 = _cond_innov(M, Y0a[:, j], X0, None if E0 is None else E0[:, min(j, E0.shape[1] - 1)])
        ys = list(y0)
        es = list(np.asarray(e0, float)[-Q:]) if Q else []
        es = [0.0] * (Q - len(es)) + es
        f = []
        for t in range(h):
            v = M.const + sum(-a[k] * ys[-k] for k in range(1, P + 1)) + sum(b[k] * es[-k] for k in range(1, Q + 1))
            if M.beta.size:
                v += float(XF[t] @ M.beta)
            f.append(v)
            ys.append(v)
            es.append(0.0)
        outs.append(f)
        if isinstance(M.var, CondVar):
            e_hist = M.innovations(Y0a[P:, j], Y0a[:P, j], None, None) if Y0a.shape[0] > P else np.zeros(0)
            V = _condvar_forecast(M.var, e_hist, h, {})
        else:
            V = np.full(h, M.var)
        mses.append([float(np.sum(psi[:t + 1][::-1] ** 2 * V[:t + 1])) for t in range(h)])
    Y = out(np.array(outs).T)
    MSE = out(np.array(mses).T)
    return (Y, MSE) if nargout > 1 else Y


def _condvar_forecast(M, e, h, opts):
    """The variances forecast after the innovations e: the next from the data, later ones with E[e^2] = v (E[I(e<0)e^2] =
    v/2, and the log-variance terms of egarch at 0)."""
    P, Q = M.P, M.Q
    if e.size:
        V = M.variances(e)
        hist_v = list(V)
        hist_e2 = list(e ** 2)
        hist_neg = list((e < 0).astype(float) * e ** 2)
        hist_z = list(e / np.sqrt(V))
    else:
        u = M.uncond()
        hist_v, hist_e2, hist_neg, hist_z = [u] * max(P, 1), [u] * max(Q, 1), [u / 2] * max(Q, 1), [0.0] * max(Q, 1)
    f = []
    for t in range(h):
        if M.kind == 'egarch':
            ez = math.sqrt(2 / math.pi) if M.dist['Name'] == 'Gaussian' else _abs_t_mean(M.dist['DoF'])
            lv = M.const + sum(g * math.log(hist_v[-k]) for k, g in M.garch.items())
            if t == 0 and e.size:
                lv += sum(a * (abs(hist_z[-k]) - ez) for k, a in M.arch.items()) + sum(l * hist_z[-k] for k, l in M.lev.items())
            else:
                lv += sum(a * (abs(hist_z[-k]) - ez) for k, a in M.arch.items() if k > t) + sum(l * hist_z[-k] for k, l in M.lev.items() if k > t)
            v = math.exp(lv)
            hist_z.append(0.0)
        else:
            v = M.const + sum(g * hist_v[-k] for k, g in M.garch.items()) + sum(a * hist_e2[-k] for k, a in M.arch.items()) \
                + sum(l * hist_neg[-k] for k, l in M.lev.items())
            hist_e2.append(v)
            hist_neg.append(v / 2)
        f.append(v)
        hist_v.append(v)
    return np.array(f)


def _complete(M, fn):
    vals = [obj.get_slot(key) for nm, obj, key in _free_slots(M)] if not isinstance(M, Varm) else [M.const, M.cov] + list(M.ar)
    if any(np.any(np.isnan(np.asarray(v, float))) for v in vals):
        raise err(f'econ:{fn}:NotFullySpecified', f'{fn} needs every parameter known: estimate the model first (its NaN values).', fn)


@bi('simulate', nout=3, arr=False)
def simulate(nargout, *args):
    """[Y, E, V] = simulate(Mdl, numobs, 'NumPaths', m, 'Y0', y0, 'E0', e0,
    'X', X): sample paths of the model (for garch, egarch and gjr: [V, Y])."""
    nargchk(args, 2, 20, 'simulate')
    M = _model(args[0], 'simulate')
    n = int(_num1(args[1], 'simulate', 'numobs'))
    if n < 1:
        raise err('econ:simulate:InvalidNumObs', 'numobs is a whole number from 1.', 'simulate')
    pos, opts = _pairs(args[2:], 'simulate', ('numpaths', 'y0', 'e0', 'v0', 'x'))
    m = int(_num1(opts['numpaths'], 'simulate', 'NumPaths')) if 'numpaths' in opts else 1
    _complete(M, 'simulate')
    if isinstance(M, Varm):
        return _varm_simulate(nargout, M, n, m, opts)
    if isinstance(M, CondVar):
        V, E = _simulate_condvar(M, n, m, opts)
        Y = E + M.offset
        return (out(V), out(Y)) if nargout > 1 else out(V)
    a, b = M.a_poly(), M.b_poly()
    P, Q = a.size - 1, b.size - 1
    X = np.asarray(darr(opts['x']), float) if 'x' in opts else None
    if M.beta.size and X is None:
        raise err('econ:simulate:NoX', 'The model has Beta: give the predictors X.', 'simulate')
    if X is not None and X.ndim == 1:
        X = X.reshape(-1, 1)
    if 'y0' in opts:
        Y0 = _col(opts['y0'], 'simulate', 'Y0')
    else:
        mu = M.const / float(np.sum(a)) if M.stationary() and M.d == 0 and M.s == 0 and abs(np.sum(a)) > 1e-12 else 0.0
        Y0 = np.full((P, 1), mu)
    E0 = _col(opts['e0'], 'simulate', 'E0') if 'e0' in opts else np.zeros((Q, 1))
    if isinstance(M.var, CondVar):
        V, E = _simulate_condvar(M.var, n, m, {})
    else:
        V = np.full((n, m), M.var)
        E = _draw(M.dist['Name'], (n, m), M.dist.get('DoF')) * math.sqrt(M.var)
    Y = np.zeros((n, m))
    for j in range(m):
        ys = list(Y0[-P:, min(j, Y0.shape[1] - 1)]) if P else []
        es = list(E0[-Q:, min(j, E0.shape[1] - 1)]) if Q else []
        ys = [0.0] * (P - len(ys)) + ys
        es = [0.0] * (Q - len(es)) + es
        for t in range(n):
            v = M.const + sum(-a[k] * ys[-k] for k in range(1, P + 1)) + sum(b[k] * es[-k] for k in range(1, Q + 1)) + E[t, j]
            if M.beta.size:
                v += float(X[X.shape[0] - n + t] @ M.beta)
            Y[t, j] = v
            ys.append(v)
            es.append(E[t, j])
    vals = (out(Y), out(E), out(V))
    return vals[:nargout] if nargout > 1 else vals[0]


def _simulate_condvar(M, n, m, opts):
    V = np.zeros((n, m))
    E = np.zeros((n, m))
    u = M.uncond()
    if not np.isfinite(u):
        u = M.const if M.kind != 'egarch' else math.exp(M.const)
    ez = math.sqrt(2 / math.pi) if M.dist['Name'] == 'Gaussian' else (_abs_t_mean(M.dist['DoF']) if M.dist['Name'] == 't' else 0)
    for j in range(m):
        hv = [u] * max(M.P, 1)
        he = [math.sqrt(u)] * max(M.Q, 1)
        hz = [0.0] * max(M.Q, 1)
        z = _draw(M.dist['Name'], n, M.dist.get('DoF'))
        for t in range(n):
            if M.kind == 'egarch':
                lv = M.const + sum(g * math.log(hv[-k]) for k, g in M.garch.items()) + sum(a * (abs(hz[-k]) - ez) for k, a in M.arch.items()) \
                    + sum(l * hz[-k] for k, l in M.lev.items())
                v = math.exp(min(lv, 700))
            else:
                v = M.const + sum(g * hv[-k] for k, g in M.garch.items()) + sum(a * he[-k] ** 2 for k, a in M.arch.items()) \
                    + sum(l * (he[-k] < 0) * he[-k] ** 2 for k, l in M.lev.items())
            e = z[t] * math.sqrt(v)
            V[t, j], E[t, j] = v, e
            hv.append(v)
            he.append(e)
            hz.append(z[t])
    return V, E


@bi('infer', nout=3, arr=False)
def infer(nargout, *args):
    """[E, V, logL] = infer(Mdl, Y, 'Y0', y0, 'E0', e0, 'X', X): the
    innovations (residuals), their variances and the log-likelihood (for
    garch, egarch and gjr: [V, logL]; for varm: [E, logL])."""
    nargchk(args, 2, 20, 'infer')
    M = _model(args[0], 'infer')
    pos, opts = _pairs(args[2:], 'infer', ('y0', 'e0', 'v0', 'x'))
    _complete(M, 'infer')
    if isinstance(M, Varm):
        return _varm_infer(nargout, M, args[1], opts)
    y = _col(args[1], 'infer', 'Y')
    if isinstance(M, CondVar):
        Vs, Ls = [], []
        for j in range(y.shape[1]):
            e = y[:, j] - M.offset
            V = M.variances(e, _col(opts['v0'], 'infer', 'V0').reshape(-1) if 'v0' in opts else None, _col(opts['e0'], 'infer', 'E0').reshape(-1) if 'e0' in opts else None)
            Vs.append(V)
            Ls.append(_loglik(e, V, M.dist['Name'], M.dist.get('DoF')))
        vals = (out(np.column_stack(Vs)), out(np.array([Ls])) if len(Ls) > 1 else Ls[0])
        return vals[:nargout] if nargout > 1 else vals[0]
    Es, Vs, Ls = [], [], []
    for j in range(y.shape[1]):
        y0, ys, e0, X = _arima_parts(M, y[:, j], opts, 'infer')
        e = M.innovations(ys, y0, e0, X)
        v = M.var.variances(e) if isinstance(M.var, CondVar) else np.full(e.size, M.var)
        pad = y.shape[0] - e.size
        Es.append(np.concatenate([np.full(pad, np.nan), e]))
        Vs.append(np.concatenate([np.full(pad, np.nan), v]))
        Ls.append(_loglik(e, v, M.dist['Name'], M.dist.get('DoF')))
    vals = (out(np.column_stack(Es)), out(np.column_stack(Vs)), out(np.array([Ls])) if len(Ls) > 1 else Ls[0])
    return vals[:nargout] if nargout > 1 else vals[0]


@bi('summarize', arr=False)
def summarize(nargout, *args):
    """summarize(EstMdl) or results = summarize(EstMdl): an estimated model's
    parameters with their standard errors, t statistics and p-values, the
    log-likelihood and information criteria."""
    nargchk(args, 1, 1, 'summarize')
    M = _model(args[0], 'summarize')
    if M.fit is None:
        if nargout:
            return Struct.scalar({'Description': Str(np.array([[M.description()]], object))})
        R.write('\n'.join(M.display_lines()) + '\n')
        return None
    f = M.fit
    k, n, L = f['k'], f['n'], f['logL']
    aic, bic = -2 * L + 2 * k, -2 * L + k * math.log(n)
    if nargout:
        d = {'Description': Str(np.array([[M.description()]], object)), 'SampleSize': float(n), 'NumEstimatedParameters': float(k),
             'LogLikelihood': L, 'AIC': aic, 'BIC': bic, 'Table': _results_table(f['names'], f['values'], f['se'])}
        if isinstance(M, Varm):
            d['Covariance'] = out(M.cov)
        return Struct.scalar(d)
    lines = [f'\n    {M.description()}', '', f'    Effective Sample Size: {n}', f'    Number of Estimated Parameters: {k}',
             f'    LogLikelihood: {L:.6g}', f'    AIC: {aic:.6g}', f'    BIC: {bic:.6g}']
    lines += _table_lines('', f['names'], f['values'], f['se'])[2:]
    if isinstance(M, Varm):
        lines += ['', '    Innovations Covariance Matrix:'] + ['    ' + '  '.join(f'{v:12.5g}' for v in row) for row in M.cov]
    R.write('\n'.join(lines) + '\n')
    return None


_CONTROL_IMPULSE = REG.get('impulse')       # control.py's, for LTI models: impulse hands it anything but an arima model


@bi('impulse', nout=3, arr=False)
def impulse(nargout, *args):
    """y = impulse(Mdl, numObs): an ARIMA model's impulse response (the
    weights of its infinite MA form, 1 first); without outputs, a stem plot."""
    if _CONTROL_IMPULSE is not None and not (args and isinstance(args[0], Arima)):
        info = _CONTROL_IMPULSE
        return info.fn(R.BASE, nargout, *args) if info.ws else info.fn(nargout, *args)
    nargchk(args, 1, 2, 'impulse')
    M = _model(args[0], 'impulse', (Arima,))
    if any(np.isnan(v) for v in list(M.ar.values()) + list(M.ma.values()) + list(M.sar.values()) + list(M.sma.values())):
        raise err('econ:impulse:NotFullySpecified', 'The AR and MA coefficients are known (no NaN).', 'impulse')
    n = int(_num1(args[1], 'impulse', 'numObs')) if len(args) > 1 else None
    if n is None:
        n = 10
        psi = M.psi(1000)
        big = np.flatnonzero(np.abs(psi) > 0.01 * max(np.abs(psi).max(), 1e-300))
        n = int(min(max(big[-1] + 2 if big.size else 10, 10), 1000))
    psi = M.psi(n)
    if nargout == 0:
        b = lambda name, *a: R._builtin(name, *a)
        b('stem', out(np.arange(n, dtype=float).reshape(-1, 1)), out(psi.reshape(-1, 1)), Char.of('filled'))
        b('title', Char.of('Impulse Response'))
        b('xlabel', Char.of('Observation Time'))
        b('ylabel', Char.of('Response'))
        return None
    return out(psi.reshape(-1, 1))


# ---- vector autoregressions ---------------------------------------------------------------------------------------------------

class Varm(Obj):
    cls = 'varm'
    is_handle = False

    def __init__(self, n, p):
        self.n, self.p = n, p
        self.const = np.full(n, np.nan)
        self.ar = [np.full((n, n), np.nan) for _ in range(p)]
        self.trend = np.zeros(n)
        self.beta = np.zeros((n, 0))
        self.cov = np.full((n, n), np.nan)
        self.names = [f'Y{k + 1}' for k in range(n)]
        self.desc = None
        self.fit = None

    def value_copy(self):
        import copy
        o = copy.copy(self)
        o.const, o.trend, o.beta, o.cov = self.const.copy(), self.trend.copy(), self.beta.copy(), self.cov.copy()
        o.ar = [A.copy() for A in self.ar]
        o.names = list(self.names)
        return o

    def description(self):
        if self.desc is not None:
            return self.desc
        return f'{self.n}-Dimensional VAR{"X" if self.beta.shape[1] else ""}({self.p}) Model' + (' with Linear Time Trend' if np.any(self.trend != 0) else '')

    PROPS = ['Description', 'SeriesNames', 'NumSeries', 'P', 'Constant', 'AR', 'Trend', 'Beta', 'Covariance']

    def getprop(self, name):
        k = name.lower()
        if k == 'description':
            return Str(np.array([[self.description()]], object))
        if k == 'seriesnames':
            return Str(np.array([self.names], object))
        if k == 'numseries':
            return float(self.n)
        if k == 'p':
            return float(self.p)
        if k == 'constant':
            return out(self.const.reshape(-1, 1))
        if k == 'ar':
            return Cell.of_list([out(A) for A in self.ar], (1, self.p))
        if k == 'trend':
            return out(self.trend.reshape(-1, 1))
        if k == 'beta':
            return out(self.beta)
        if k == 'covariance':
            return out(self.cov)
        return _method_or_fail(self, name)

    def setprop(self, name, value):
        k = name.lower()
        n = self.n
        if k == 'constant':
            self.const = _vecn(value, n, 'Constant')
        elif k == 'ar':
            mats = [np.asarray(darr(c), float) for c in (value.a.reshape(-1, order='F') if type(value) is Cell else [value])]
            if any(A.shape != (n, n) for A in mats):
                raise err('econ:varm:InvalidAR', f'AR is a cell of {n}-by-{n} matrices.', 'varm')
            self.ar, self.p = mats, len(mats)
        elif k == 'trend':
            self.trend = _vecn(value, n, 'Trend')
        elif k == 'beta':
            B = np.asarray(darr(value), float)
            if B.ndim != 2 or (B.size and B.shape[0] != n):
                raise err('econ:varm:InvalidBeta', f'Beta has {n} rows, one for each series.', 'varm')
            self.beta = B.reshape(n, -1)
        elif k == 'covariance':
            C = np.asarray(darr(value), float)
            if C.shape != (n, n):
                raise err('econ:varm:InvalidCovariance', f'Covariance is {n}-by-{n}.', 'varm')
            self.cov = C
        elif k == 'seriesnames':
            names = [py_str(x) for x in (value.a.reshape(-1, order='F') if type(value) in (Cell, Str) else [value])]
            if len(names) != n:
                raise err('econ:varm:InvalidNames', f'Give {n} series names.', 'varm')
            self.names = names
        elif k == 'description':
            self.desc = sval(value, 'Description', 'varm')
        else:
            raise MError('MATLAB:class:SetProhibited', f"You cannot set the '{name}' property of varm.")
        self.fit = None

    def propnames(self):
        return list(self.PROPS)

    def display_lines(self):
        n = self.n

        def mat_text(A, shape):
            if np.all(np.isnan(A)):
                return f'{shape} of NaNs'
            if np.all(A == 0):
                return f'{shape} of zeros'
            return f'{shape}'
        lags = [k + 1 for k, A in enumerate(self.ar) if not np.all(A == 0)]
        ar = '{' + ' '.join(f'{n}×{n} matrix' + (' of NaNs' if np.all(np.isnan(self.ar[k - 1])) else '') for k in lags) + '}' + \
            (f" at lag{'s' if len(lags) > 1 else ''} [{' '.join(str(k) for k in lags)}]" if lags else '')
        rows = [('Description', f'"{self.description()}"'), ('SeriesNames', '  '.join(f'"{x}"' for x in self.names)), ('NumSeries', str(n)), ('P', str(self.p)),
                ('Constant', '[' + (' '.join(_g(v) for v in self.const) + ']' if not np.all(np.isnan(self.const)) else f'{n}×1 vector of NaNs]')),
                ('AR', ar), ('Trend', '[' + mat_text(self.trend, f'{n}×1 vector') + ']'), ('Beta', f'[{n}×{self.beta.shape[1]} matrix]'),
                ('Covariance', '[' + mat_text(self.cov, f'{n}×{n} matrix') + ']')]
        w = max(len(r[0]) for r in rows)
        return ['  varm with properties:', ''] + [f'    {k:>{w}}: {v}' for k, v in rows]

    def phi(self, h):
        """The moving-average matrices Psi_0 = I, Psi_1, ... Psi_{h-1}."""
        n = self.n
        Ps = [np.eye(n)]
        for j in range(1, h):
            S = np.zeros((n, n))
            for k in range(1, min(j, self.p) + 1):
                S += self.ar[k - 1] @ Ps[j - k]
            Ps.append(S)
        return Ps


def _vecn(v, n, what):
    a = np.asarray(darr(v), float).reshape(-1)
    if a.size != n:
        raise err('econ:varm:InvalidValue', f'{what} has {n} values, one for each series.', 'varm')
    return a


@bi('varm', arr=False)
def varm(nargout, *args):
    """Mdl = varm(numSeries, numLags) or varm('Constant', c, 'AR', {A1 ...},
    'Trend', t, 'Beta', B, 'Covariance', S): a vector autoregression."""
    if args and not is_str(args[0]):
        if len(args) != 2:
            raise err('econ:varm:InvalidInput', 'varm(numSeries, numLags) takes the number of series and of lags.', 'varm')
        n, p = int(_num1(args[0], 'varm', 'numSeries')), int(_num1(args[1], 'varm', 'numLags'))
        if n < 1 or p < 0:
            raise err('econ:varm:InvalidInput', 'numSeries is a whole number from 1, numLags from 0.', 'varm')
        return Varm(n, p)
    pos, o = _pairs(args, 'varm', ('constant', 'ar', 'lags', 'trend', 'beta', 'covariance', 'seriesnames', 'description'))
    if 'ar' in o:
        mats = [np.asarray(darr(c), float) for c in (o['ar'].a.reshape(-1, order='F') if type(o['ar']) is Cell else [o['ar']])]
        n = mats[0].shape[0]
    elif 'constant' in o:
        n = numel(o['constant'])
        mats = []
    elif 'covariance' in o:
        n = np.asarray(darr(o['covariance'])).shape[0]
        mats = []
    else:
        raise err('econ:varm:InvalidInput', "varm needs the number of series: give 'AR', 'Constant' or 'Covariance'.", 'varm')
    if 'lags' in o and mats:
        lags = [int(x) for x in np.asarray(darr(o['lags']), float).reshape(-1)]
        if len(lags) != len(mats):
            raise err('econ:varm:LagsMismatch', 'Lags has a lag for each AR matrix.', 'varm')
        full = [np.zeros((n, n)) for _ in range(max(lags))]
        for L, A in zip(lags, mats):
            full[L - 1] = A
        mats = full
    M = Varm(n, len(mats))
    M.ar = mats
    M.const = np.zeros(n) if 'constant' not in o else M.const
    for key, prop in (('constant', 'Constant'), ('trend', 'Trend'), ('beta', 'Beta'), ('covariance', 'Covariance'), ('seriesnames', 'SeriesNames'),
                      ('description', 'Description')):
        if key in o:
            M.setprop(prop, o[key])
    if 'constant' not in o:
        M.const = np.zeros(n)
    return M


def _varm_data(M, Y, opts, fn):
    Y = np.asarray(darr(Y, fn), float)
    if Y.ndim != 2 or Y.shape[1] != M.n:
        raise err(f'econ:{fn}:InvalidData', f'Y has a column for each of the {M.n} series.', fn)
    if 'y0' in opts:
        Y0 = np.asarray(darr(opts['y0']), float)
        if Y0.shape[0] < M.p or Y0.shape[1] != M.n:
            raise err(f'econ:{fn}:Y0', f'Y0 has at least {M.p} rows and {M.n} columns.', fn)
        full = np.vstack([Y0[Y0.shape[0] - M.p:], Y])
        T = Y.shape[0]
    else:
        if Y.shape[0] <= M.p:
            raise err(f'econ:{fn}:TooFew', f'Y has more than {M.p} rows (the presample).', fn)
        full = Y
        T = Y.shape[0] - M.p
    X = None
    if M.beta.shape[1] or 'x' in opts:
        if 'x' not in opts:
            raise err(f'econ:{fn}:NoX', 'The model has Beta: give the predictors X.', fn)
        X = np.asarray(darr(opts['x']), float)
        if X.ndim == 1:
            X = X.reshape(-1, 1)
        X = X[X.shape[0] - T:]
    return full, T, X


def _varm_estimate(nargout, M, Y, opts):
    M = M.value_copy()
    k_x = 0
    if 'x' in opts and not M.beta.shape[1]:
        Xa = np.asarray(darr(opts['x']), float)
        k_x = Xa.reshape(Xa.shape[0], -1).shape[1]
        M.beta = np.full((M.n, k_x), np.nan)
    full, T, X = _varm_data(M, Y, opts, 'estimate')
    n, p = M.n, M.p
    Yt = full[p:p + T] if full.shape[0] >= p + T else full[p:]
    T = Yt.shape[0]
    # regressors: constant, trend, the lags, predictors; the known parts moved to the left
    blocks = [('const', np.ones((T, 1)), M.const.reshape(-1, 1)), ('trend', np.arange(1, T + 1, dtype=float).reshape(-1, 1), M.trend.reshape(-1, 1))]
    for k in range(p):
        blocks.append((f'ar{k}', full[p - k - 1:p - k - 1 + T], M.ar[k]))
    if X is not None:
        blocks.append(('beta', X, M.beta))
    Z, cols = [], []
    known = np.zeros((T, n))
    for name, R_, C in blocks:
        for j in range(R_.shape[1]):
            c = C[:, j]
            if np.all(np.isnan(c)):
                Z.append(R_[:, j])
                cols.append((name, j))
            elif np.any(np.isnan(c)):
                raise err('econ:estimate:PartlyKnown', 'Each column of a coefficient matrix is known or NaN (estimated) as a whole here.', 'estimate')
            else:
                known += np.outer(R_[:, j], c)
    Z = np.column_stack(Z) if Z else np.zeros((T, 0))
    Yw = Yt - known
    B, *_ = np.linalg.lstsq(Z, Yw, rcond=None) if Z.shape[1] else (np.zeros((0, n)),)
    E = Yw - Z @ B
    Sigma = E.T @ E / T
    if np.all(np.isnan(M.cov)):
        M.cov = Sigma
    covB = np.kron(Sigma, np.linalg.inv(Z.T @ Z)) if Z.shape[1] else np.zeros((0, 0))
    se_all = np.sqrt(np.maximum(np.diag(covB), 0)).reshape(n, -1).T if Z.shape[1] else np.zeros((0, n))
    SE = {'const': np.zeros(n), 'trend': np.zeros(n), 'beta': np.zeros_like(M.beta)}
    SE.update({f'ar{k}': np.zeros((n, n)) for k in range(p)})
    for i, (name, j) in enumerate(cols):
        if name == 'const':
            M.const = B[i].copy()
            SE['const'] = se_all[i].copy()
        elif name == 'trend':
            M.trend = B[i].copy()
            SE['trend'] = se_all[i].copy()
        elif name == 'beta':
            M.beta[:, j] = B[i]
            SE['beta'][:, j] = se_all[i]
        else:
            k = int(name[2:])
            M.ar[k][:, j] = B[i]
            SE[name][:, j] = se_all[i]
    C = M.cov
    sign, logdet = np.linalg.slogdet(C)
    Ci = np.linalg.inv(C)
    logL = float(-0.5 * (T * n * math.log(2 * math.pi) + T * logdet + np.einsum('ti,ij,tj->', E, Ci, E)))
    names, values, ses = [], [], []
    for i in range(n):
        if ('const', 0) in cols:
            names.append(f'Constant({i + 1})')
            values.append(M.const[i])
            ses.append(SE['const'][i])
    for k in range(p):
        for j in range(n):
            if (f'ar{k}', j) in cols:
                for i in range(n):
                    names.append(f'AR{{{k + 1}}}({i + 1},{j + 1})')
                    values.append(M.ar[k][i, j])
                    ses.append(SE[f'ar{k}'][i, j])
    if ('trend', 0) in cols:
        for i in range(n):
            names.append(f'Trend({i + 1})')
            values.append(M.trend[i])
            ses.append(SE['trend'][i])
    for j in range(M.beta.shape[1]):
        if ('beta', j) in cols:
            for i in range(n):
                names.append(f'Beta({i + 1},{j + 1})')
                values.append(M.beta[i, j])
                ses.append(SE['beta'][i, j])
    M.fit = {'names': names, 'values': np.array(values), 'se': np.array(ses), 'logL': logL, 'n': T, 'k': len(cols) * n + n * (n + 1) // 2, 'cov': covB}
    _show(_display_opt(opts, 'off'), _table_lines(M.description() + ':', names, np.array(values), np.array(ses)))
    EstSE = Struct.scalar({'Constant': out(SE['const'].reshape(-1, 1)), 'AR': Cell.of_list([out(SE[f'ar{k}']) for k in range(p)], (1, p)),
                           'Trend': out(SE['trend'].reshape(-1, 1)), 'Beta': out(SE['beta'])})
    vals = (M, EstSE, logL, out(E))
    return vals[:max(nargout, 1)] if nargout > 1 else M


def _varm_mean(M, hist, t, X=None):
    v = M.const + M.trend * t
    for k in range(M.p):
        v = v + M.ar[k] @ hist[-k - 1]
    if X is not None and M.beta.shape[1]:
        v = v + M.beta @ X
    return v


def _varm_forecast(nargout, M, h, Y0, opts):
    if Y0 is None:
        if M.p:
            raise err('econ:forecast:Y0', f'Give at least {M.p} rows of presample responses Y0.', 'forecast')
        Y0a = np.zeros((0, M.n))
    else:
        Y0a = np.asarray(darr(Y0), float)
        if Y0a.ndim != 2 or Y0a.shape[1] != M.n or Y0a.shape[0] < M.p:
            raise err('econ:forecast:Y0', f'Y0 has at least {M.p} rows and {M.n} columns.', 'forecast')
    XF = np.asarray(darr(opts['xf']), float) if 'xf' in opts else None
    if M.beta.shape[1] and XF is None:
        raise err('econ:forecast:NoXF', 'The model has Beta: give XF.', 'forecast')
    hist = [Y0a[i] for i in range(Y0a.shape[0])]
    t0 = Y0a.shape[0]
    F = []
    for t in range(h):
        v = _varm_mean(M, hist, t0 + t + 1, XF[t] if XF is not None else None)
        F.append(v)
        hist.append(v)
    Ps = M.phi(h)
    mse = []
    acc = np.zeros((M.n, M.n))
    for t in range(h):
        acc = acc + Ps[t] @ M.cov @ Ps[t].T
        mse.append(out(acc.copy()))
    Y = out(np.array(F))
    return (Y, Cell.of_list(mse, (h, 1))) if nargout > 1 else Y


def _varm_simulate(nargout, M, n, m, opts):
    Y0 = np.asarray(darr(opts['y0']), float) if 'y0' in opts else None
    X = np.asarray(darr(opts['x']), float) if 'x' in opts else None
    if M.beta.shape[1] and X is None:
        raise err('econ:simulate:NoX', 'The model has Beta: give X.', 'simulate')
    L = np.linalg.cholesky(M.cov + 1e-15 * np.eye(M.n))
    Ys = np.zeros((n, M.n, m))
    Es = np.zeros((n, M.n, m))
    rs = _rs()
    mu = None
    try:
        A = np.eye(M.n) - sum(M.ar)
        mu = np.linalg.solve(A, M.const)
    except np.linalg.LinAlgError:
        mu = np.zeros(M.n)
    for j in range(m):
        hist = [Y0[i] for i in range(Y0.shape[0])] if Y0 is not None else [mu.copy() for _ in range(M.p)]
        for t in range(n):
            e = L @ rs.standard_normal(M.n)
            v = _varm_mean(M, hist, t + 1, X[X.shape[0] - n + t] if X is not None else None) + e
            Ys[t, :, j] = v
            Es[t, :, j] = e
            hist.append(v)
    Y = out(Ys[:, :, 0] if m == 1 else Ys)
    E = out(Es[:, :, 0] if m == 1 else Es)
    return (Y, E) if nargout > 1 else Y


def _varm_infer(nargout, M, Y, opts):
    full, T, X = _varm_data(M, Y, opts, 'infer')
    p = M.p
    E = np.zeros((T, M.n))
    for t in range(T):
        hist = [full[i] for i in range(t, t + p)]
        E[t] = full[p + t] - _varm_mean(M, hist, t + 1, X[t] if X is not None else None)
    sign, logdet = np.linalg.slogdet(M.cov)
    Ci = np.linalg.inv(M.cov)
    logL = float(-0.5 * (T * M.n * math.log(2 * math.pi) + T * logdet + np.einsum('ti,ij,tj->', E, Ci, E)))
    return (out(E), logL) if nargout > 1 else out(E)


def _irf_opts(args, fn):
    pos, opts = _pairs(args, fn, ('numobs', 'method'))
    h = int(_num1(opts['numobs'], fn, 'NumObs')) if 'numobs' in opts else 20
    method = (opt_str(opts['method']) or 'orthogonalized').lower() if 'method' in opts else 'orthogonalized'
    if method not in ('orthogonalized', 'generalized'):
        raise err(f'econ:{fn}:InvalidMethod', "Method is 'orthogonalized' or 'generalized'.", fn)
    return h, method


@bi('irf', arr=False)
def irf(nargout, *args):
    """Response = irf(Mdl, 'NumObs', h, 'Method', m): a VAR model's impulse
    responses: Response(t, j, k) is variable k's response at time t-1 to a
    shock to variable j of one standard deviation (orthogonalized by the
    Cholesky factor of the covariance, or generalized); without outputs,
    plotted."""
    nargchk(args, 1, 5, 'irf')
    M = args[0]
    if isinstance(M, Arima):
        h, _ = _irf_opts(args[1:], 'irf')
        return impulse(nargout, M, float(h))
    M = _model(M, 'irf', (Varm,))
    _complete(M, 'irf')
    h, method = _irf_opts(args[1:], 'irf')
    Ps = M.phi(h)
    n = M.n
    if method == 'orthogonalized':
        S = np.linalg.cholesky(M.cov)
    else:
        S = M.cov / np.sqrt(np.diag(M.cov))[None, :]
    Rsp = np.zeros((h, n, n))
    for t in range(h):
        Rsp[t] = (Ps[t] @ S).T          # shock j (row) -> variable k (column)
    if nargout == 0:
        b = lambda name, *a: R._builtin(name, *a)
        b('figure')
        for j in range(n):
            for k in range(n):
                b('subplot', float(n), float(n), float(j * n + k + 1))
                b('plot', out(np.arange(h, dtype=float).reshape(-1, 1)), out(Rsp[:, j, k].reshape(-1, 1)))
                b('title', Char.of(f'{M.names[j]} → {M.names[k]}'))
        return None
    return out(Rsp)


@bi('fevd', arr=False)
def fevd(nargout, *args):
    """Decomposition = fevd(Mdl, 'NumObs', h, 'Method', m): the forecast
    error variance decomposition: Decomposition(t, j, k) is the share of
    variable k's forecast error variance at horizon t due to shocks to
    variable j."""
    nargchk(args, 1, 5, 'fevd')
    M = _model(args[0], 'fevd', (Varm,))
    _complete(M, 'fevd')
    h, method = _irf_opts(args[1:], 'fevd')
    Ps = M.phi(h)
    n = M.n
    S = np.linalg.cholesky(M.cov) if method == 'orthogonalized' else M.cov / np.sqrt(np.diag(M.cov))[None, :]
    contrib = np.zeros((h, n, n))
    acc = np.zeros((n, n))
    for t in range(h):
        acc = acc + (Ps[t] @ S) ** 2          # (variable, shock)
        tot = acc.sum(axis=1, keepdims=True)
        contrib[t] = (acc / tot).T
    return out(contrib)


def classes():
    return (Arima, CondVar, Varm)
