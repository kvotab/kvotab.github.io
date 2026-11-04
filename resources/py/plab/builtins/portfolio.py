"""Mean-variance portfolios: the Portfolio object (asset moments, bounds,
budget and linear constraints; the efficient frontier, its limits,
portfolios by return or by risk, the largest Sharpe ratio), portopt,
portstats, portvrisk, corr2cov and cov2corr.

Each portfolio on the frontier is the least variance for its return, found
by scipy.optimize.minimize (SLSQP, with the exact gradients) within the
constraints; the largest return by scipy.optimize.linprog.
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
            except (ValueError, TypeError, IndexError, KeyError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                raise err(f'finance:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _vec(v, n=None, what='The values', fn='Portfolio'):
    a = np.asarray(darr(v, fn), float).reshape(-1)
    if n is not None and a.size == 1 and n > 1:
        a = np.full(n, float(a[0]))
    if n is not None and a.size != n:
        raise err(f'finance:{fn}:Size', f'{what} has {n} values, one for each asset.', fn)
    return a


# ---- solving ------------------------------------------------------------------------------------------------------------------

class _Set:
    """The feasible weights: bounds, a budget range, A w <= b and Aeq w = beq."""

    def __init__(self, n, lb=None, ub=None, budget=(None, None), A=None, b=None, Aeq=None, beq=None):
        self.n = n
        self.lb = np.full(n, -np.inf) if lb is None else lb
        self.ub = np.full(n, np.inf) if ub is None else ub
        self.budget = budget
        self.A, self.b, self.Aeq, self.beq = A, b, Aeq, beq

    def scipy_constraints(self, extra=()):
        cons = list(extra)
        lo, hi = self.budget
        one = np.ones(self.n)
        if lo is not None and hi is not None and lo == hi:
            cons.append({'type': 'eq', 'fun': lambda w, v=lo: one @ w - v, 'jac': lambda w: one})
        else:
            if lo is not None:
                cons.append({'type': 'ineq', 'fun': lambda w, v=lo: one @ w - v, 'jac': lambda w: one})
            if hi is not None:
                cons.append({'type': 'ineq', 'fun': lambda w, v=hi: v - one @ w, 'jac': lambda w: -one})
        if self.A is not None and self.A.size:
            cons.append({'type': 'ineq', 'fun': lambda w: self.b - self.A @ w, 'jac': lambda w: -self.A})
        if self.Aeq is not None and self.Aeq.size:
            cons.append({'type': 'eq', 'fun': lambda w: self.Aeq @ w - self.beq, 'jac': lambda w: self.Aeq})
        return cons

    def bounds(self):
        return [(None if not np.isfinite(l) else l, None if not np.isfinite(u) else u) for l, u in zip(self.lb, self.ub)]

    def start(self):
        lo, hi = self.budget
        tot = lo if lo is not None else (hi if hi is not None else 1.0)
        w = np.full(self.n, tot / self.n)
        return np.clip(w, np.where(np.isfinite(self.lb), self.lb, -1e9), np.where(np.isfinite(self.ub), self.ub, 1e9))

    def linprog(self, c):
        """min c'w over the set (scipy.optimize.linprog, HiGHS)."""
        from scipy.optimize import linprog
        A_ub, b_ub, A_eq, b_eq = [], [], [], []
        lo, hi = self.budget
        one = np.ones((1, self.n))
        if lo is not None and hi is not None and lo == hi:
            A_eq.append(one)
            b_eq.append([lo])
        else:
            if lo is not None:
                A_ub.append(-one)
                b_ub.append([-lo])
            if hi is not None:
                A_ub.append(one)
                b_ub.append([hi])
        if self.A is not None and self.A.size:
            A_ub.append(self.A)
            b_ub.append(self.b)
        if self.Aeq is not None and self.Aeq.size:
            A_eq.append(self.Aeq)
            b_eq.append(self.beq)
        r = linprog(c, A_ub=np.vstack(A_ub) if A_ub else None, b_ub=np.concatenate([np.ravel(x) for x in b_ub]) if b_ub else None,
                    A_eq=np.vstack(A_eq) if A_eq else None, b_eq=np.concatenate([np.ravel(x) for x in b_eq]) if b_eq else None,
                    bounds=self.bounds(), method='highs')
        if r.status == 3:
            raise err('finance:Portfolio:Unbounded', 'The returns are unbounded within these constraints: give bounds or a budget.', 'Portfolio')
        if not r.success:
            raise err('finance:Portfolio:Infeasible', 'No portfolio satisfies the constraints.', 'Portfolio')
        return r.x


def _minvar(S, C, extra=(), w0=None):
    from scipy.optimize import minimize
    x0 = S.start() if w0 is None else w0
    r = minimize(lambda w: w @ C @ w, x0, jac=lambda w: 2 * C @ w, method='SLSQP', bounds=S.bounds(), constraints=S.scipy_constraints(extra),
                 options={'ftol': 1e-15, 'maxiter': 1000})
    if not r.success and r.status not in (8, 9):
        r2 = minimize(lambda w: w @ C @ w, S.linprog(np.zeros(S.n)), jac=lambda w: 2 * C @ w, method='SLSQP', bounds=S.bounds(),
                      constraints=S.scipy_constraints(extra), options={'ftol': 1e-15, 'maxiter': 2000})
        r = r2 if r2.fun <= r.fun or not r.success else r
    return r.x


def frontier_limits(S, mu, C):
    """The least-variance portfolio and the largest-return one (the least variance among those)."""
    wmin = _minvar(S, C)
    wmax = S.linprog(-mu)
    top = float(mu @ wmax)
    tol = 1e-10 * max(1.0, abs(top))
    wmax = _minvar(S, C, ({'type': 'ineq', 'fun': lambda w: mu @ w - (top - tol), 'jac': lambda w: mu},), w0=wmax)
    return wmin, wmax


def by_return(S, mu, C, target, w0=None):
    return _minvar(S, C, ({'type': 'eq', 'fun': lambda w: mu @ w - target, 'jac': lambda w: mu},), w0=w0)


def frontier(S, mu, C, k):
    wmin, wmax = frontier_limits(S, mu, C)
    if k == 1:
        return wmin.reshape(-1, 1)
    r0, r1 = float(mu @ wmin), float(mu @ wmax)
    W = [wmin]
    for t in np.linspace(r0, r1, k)[1:-1]:
        W.append(by_return(S, mu, C, t, w0=W[-1]))
    W.append(wmax)
    return np.column_stack(W)


def by_risk(S, mu, C, risk):
    """The largest return with a standard deviation of at most risk (the frontier's least-risk portfolio when risk is below it)."""
    from scipy.optimize import minimize, brentq
    wmin, wmax = frontier_limits(S, mu, C)
    lo, hi = math.sqrt(max(wmin @ C @ wmin, 0)), math.sqrt(max(wmax @ C @ wmax, 0))
    if risk <= lo:
        return wmin
    if risk >= hi:
        return wmax
    r0, r1 = float(mu @ wmin), float(mu @ wmax)
    def f(t):
        w = by_return(S, mu, C, t)
        return math.sqrt(max(w @ C @ w, 0)) - risk
    t = brentq(f, r0, r1, xtol=1e-12 * max(1.0, abs(r1)))
    return by_return(S, mu, C, t)


def max_sharpe(S, mu, C, rf):
    """The frontier portfolio with the largest (return - rf)/risk, found along the returns (golden-section search after a grid)."""
    from scipy.optimize import minimize_scalar
    wmin, wmax = frontier_limits(S, mu, C)
    r0, r1 = float(mu @ wmin), float(mu @ wmax)
    if r1 - r0 < 1e-14:
        return wmin

    def neg(t):
        w = by_return(S, mu, C, t)
        s = math.sqrt(max(w @ C @ w, 1e-300))
        return -(mu @ w - rf) / s
    grid = np.linspace(r0, r1, 21)
    vals = [neg(t) for t in grid]
    k = int(np.argmin(vals))
    a, b = grid[max(k - 1, 0)], grid[min(k + 1, grid.size - 1)]
    r = minimize_scalar(neg, bounds=(a, b), method='bounded', options={'xatol': 1e-12 * max(1.0, abs(r1))})
    t = r.x if r.fun <= vals[k] else grid[k]
    return by_return(S, mu, C, t)


# ---- the Portfolio object -------------------------------------------------------------------------------------------------------

class Portfolio(Obj):
    cls = 'Portfolio'
    is_handle = False
    PROPS = ['Name', 'NumAssets', 'AssetList', 'AssetMean', 'AssetCovar', 'RiskFreeRate', 'LowerBound', 'UpperBound', 'LowerBudget', 'UpperBudget',
             'AInequality', 'bInequality', 'AEquality', 'bEquality']

    def __init__(self):
        self.name = ''
        self.n = None
        self.names = None
        self.mean = None
        self.cov = None
        self.rf = None
        self.lb = None
        self.ub = None
        self.lob = None
        self.upb = None
        self.A = self.b = self.Aeq = self.beq = None

    def value_copy(self):
        import copy
        return copy.copy(self)

    def nassets(self):
        return self.n

    def set_n(self, n, what):
        if self.n is None:
            self.n = n
        elif self.n != n:
            raise err('finance:Portfolio:NumAssets', f'{what} is for {n} assets; the portfolio has {self.n}.', 'Portfolio')

    def getprop(self, name):
        k = name.lower()
        e = lambda v: out(v) if v is not None else EMPTY()
        if k == 'name':
            return Char.of(self.name)
        if k == 'numassets':
            return float(self.n) if self.n is not None else EMPTY()
        if k == 'assetlist':
            names = self.names or ([f'Asset{i + 1}' for i in range(self.n)] if self.n else [])
            return Cell.of_list([Char.of(x) for x in names], (1, len(names)))
        if k == 'assetmean':
            return e(self.mean.reshape(-1, 1) if self.mean is not None else None)
        if k == 'assetcovar':
            return e(self.cov)
        if k == 'riskfreerate':
            return float(self.rf) if self.rf is not None else EMPTY()
        if k == 'lowerbound':
            return e(self.lb.reshape(-1, 1) if self.lb is not None else None)
        if k == 'upperbound':
            return e(self.ub.reshape(-1, 1) if self.ub is not None else None)
        if k == 'lowerbudget':
            return float(self.lob) if self.lob is not None else EMPTY()
        if k == 'upperbudget':
            return float(self.upb) if self.upb is not None else EMPTY()
        if k == 'ainequality':
            return e(self.A)
        if k == 'binequality':
            return e(self.b.reshape(-1, 1) if self.b is not None else None)
        if k == 'aequality':
            return e(self.Aeq)
        if k == 'bequality':
            return e(self.beq.reshape(-1, 1) if self.beq is not None else None)
        if name in _METHODS:
            from ..classdef import BoundBuiltin
            return BoundBuiltin(self, name)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class 'Portfolio'.")

    def setprop(self, name, value):
        _set(self, name, value)

    def propnames(self):
        return list(self.PROPS)

    def display_lines(self):
        def show(v, shape=None):
            if v is None:
                return '[]'
            a = np.asarray(v)
            if a.size <= 4:
                return '[' + ' '.join(f'{x:g}' for x in a.reshape(-1)) + ']'
            return f'[{"×".join(str(d) for d in (shape or a.shape))} double]'
        rows = [('Name', f"'{self.name}'" if self.name else '[]'), ('NumAssets', str(self.n) if self.n is not None else '[]'),
                ('AssetList', '{' + ' '.join(f"'{x}'" for x in self.names) + '}' if self.names else '[]'),
                ('AssetMean', show(self.mean, (self.n, 1) if self.n else None)), ('AssetCovar', show(self.cov)),
                ('RiskFreeRate', f'{self.rf:g}' if self.rf is not None else '[]'), ('LowerBound', show(self.lb, (self.n, 1) if self.n else None)),
                ('UpperBound', show(self.ub, (self.n, 1) if self.n else None)), ('LowerBudget', f'{self.lob:g}' if self.lob is not None else '[]'),
                ('UpperBudget', f'{self.upb:g}' if self.upb is not None else '[]'), ('AInequality', show(self.A)), ('bInequality', show(self.b)),
                ('AEquality', show(self.Aeq)), ('bEquality', show(self.beq))]
        w = max(len(r[0]) for r in rows)
        return ['  Portfolio with properties:', ''] + [f'    {k:>{w}}: {v}' for k, v in rows]

    def feasible_set(self, fn):
        if self.mean is None or self.cov is None:
            raise err(f'finance:{fn}:NoMoments', 'The portfolio has no asset moments: setAssetMoments or estimateAssetMoments.', fn)
        n = self.n
        if self.lb is None and self.ub is None and self.lob is None and self.upb is None and self.A is None and self.Aeq is None:
            raise err(f'finance:{fn}:NoConstraints', 'The portfolio has no constraints, so its returns are unbounded: setDefaultConstraints.', fn)
        return _Set(n, self.lb, self.ub, (self.lob, self.upb), self.A, self.b, self.Aeq, self.beq)


def _set(p, name, value):
    k = name.lower()
    if k == 'name':
        p.name = sval(value, 'Name', 'Portfolio')
    elif k == 'numassets':
        p.set_n(int(num(value)), 'NumAssets')
    elif k == 'assetlist':
        names = [py_str(x) for x in (value.a.reshape(-1, order='F') if type(value) in (Cell, Str) else [value])]
        p.set_n(len(names), 'AssetList')
        p.names = names
    elif k == 'assetmean':
        m = _vec(value)
        p.set_n(m.size, 'AssetMean')
        p.mean = m
    elif k == 'assetcovar':
        C = np.atleast_2d(np.asarray(darr(value), float))
        if C.shape[0] != C.shape[1] or not np.allclose(C, C.T, atol=1e-12 * max(1.0, np.abs(C).max())):
            raise err('finance:Portfolio:AssetCovar', 'AssetCovar is a symmetric matrix.', 'Portfolio')
        p.set_n(C.shape[0], 'AssetCovar')
        p.cov = (C + C.T) / 2
    elif k == 'riskfreerate':
        p.rf = float(num(value))
    elif k == 'lowerbound':
        p.lb = _vec(value, p.n, 'LowerBound') if p.n else _vec(value)
        p.set_n(p.lb.size, 'LowerBound')
    elif k == 'upperbound':
        p.ub = _vec(value, p.n, 'UpperBound') if p.n else _vec(value)
        p.set_n(p.ub.size, 'UpperBound')
    elif k in ('lowerbudget', 'upperbudget', 'budget'):
        v = float(num(value))
        if k in ('lowerbudget', 'budget'):
            p.lob = v
        if k in ('upperbudget', 'budget'):
            p.upb = v
    elif k in ('ainequality', 'aequality'):
        A = np.atleast_2d(np.asarray(darr(value), float))
        p.set_n(A.shape[1], name)
        if k == 'ainequality':
            p.A = A
        else:
            p.Aeq = A
    elif k == 'binequality':
        p.b = _vec(value)
    elif k == 'bequality':
        p.beq = _vec(value)
    else:
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'Portfolio'.")


def _port(v, fn):
    if not isinstance(v, Portfolio):
        raise err(f'finance:{fn}:NotPortfolio', f'{fn} takes a Portfolio object first.', fn)
    return v.value_copy()


def _named(p, args, fn):
    k = 0
    while k < len(args):
        o = opt_str(args[k])
        if o is None or k + 1 >= len(args):
            raise err(f'finance:{fn}:InvalidInput', 'Give Name, Value pairs.', fn)
        _set(p, o, args[k + 1])
        k += 2
    return p


@bi('Portfolio', arr=False)
def Portfolio_(nargout, *args):
    """p = Portfolio('Name', value, ...): a mean-variance portfolio problem
    (AssetMean, AssetCovar, LowerBound, UpperBound, Budget, RiskFreeRate,
    AssetList, AInequality, bInequality, AEquality, bEquality, Name)."""
    rest = list(args)
    p = Portfolio()
    if rest and isinstance(rest[0], Portfolio):
        p = rest.pop(0).value_copy()
    return _named(p, rest, 'Portfolio')


_METHODS = {}


def _method(name, nout=1):
    def deco(f):
        _METHODS[name] = f
        bi(name, nout=nout, arr=False)(f)
        return f
    return deco


@_method('setAssetMoments')
def setAssetMoments(nargout, *args):
    """p = setAssetMoments(p, AssetMean, AssetCovar): the assets' expected returns and covariance."""
    nargchk(args, 3, 3, 'setAssetMoments')
    p = _port(args[0], 'setAssetMoments')
    p.n = None if p.mean is None and p.cov is None and p.lb is None and p.ub is None else p.n
    _set(p, 'AssetCovar', args[2])
    m = _vec(args[1])
    if m.size == 1 and p.n > 1:
        m = np.full(p.n, float(m[0]))
    _set(p, 'AssetMean', m)
    return p


@_method('estimateAssetMoments')
def estimateAssetMoments(nargout, *args):
    """p = estimateAssetMoments(p, AssetReturns): the mean and covariance of the returns (a row for each time, a column for each asset; NaN rows left out)."""
    nargchk(args, 2, 4, 'estimateAssetMoments')
    p = _port(args[0], 'estimateAssetMoments')
    X = np.asarray(darr(args[1]), float)
    X = X[np.all(np.isfinite(X), axis=1)]
    if X.shape[0] < 2:
        raise err('finance:estimateAssetMoments:TooFew', 'There are at least two rows of returns.', 'estimateAssetMoments')
    p.set_n(X.shape[1], 'AssetReturns')
    p.mean = X.mean(axis=0)
    p.cov = np.atleast_2d(np.cov(X, rowvar=False))
    return p


@_method('setDefaultConstraints')
def setDefaultConstraints(nargout, *args):
    """p = setDefaultConstraints(p): long only (LowerBound 0) and fully invested (budget 1)."""
    nargchk(args, 1, 2, 'setDefaultConstraints')
    p = _port(args[0], 'setDefaultConstraints')
    if len(args) > 1:
        p.set_n(int(num(args[1])), 'NumAssets')
    if p.n is None:
        raise err('finance:setDefaultConstraints:NumAssets', 'The number of assets is not known yet.', 'setDefaultConstraints')
    p.lb = np.zeros(p.n)
    p.ub = None
    p.lob = p.upb = 1.0
    return p


@_method('setBounds')
def setBounds(nargout, *args):
    """p = setBounds(p, LowerBound, UpperBound): bounds on each weight (a scalar for all)."""
    nargchk(args, 2, 3, 'setBounds')
    p = _port(args[0], 'setBounds')
    if numel(args[1]):
        _set(p, 'LowerBound', args[1])
    if len(args) > 2 and numel(args[2]):
        _set(p, 'UpperBound', args[2])
    return p


@_method('setBudget')
def setBudget(nargout, *args):
    """p = setBudget(p, LowerBudget, UpperBudget): bounds on the sum of the weights."""
    nargchk(args, 2, 3, 'setBudget')
    p = _port(args[0], 'setBudget')
    p.lob = float(num(args[1])) if numel(args[1]) else None
    p.upb = float(num(args[2])) if len(args) > 2 and numel(args[2]) else p.lob
    return p


@_method('setInequality')
def setInequality(nargout, *args):
    """p = setInequality(p, AInequality, bInequality): linear constraints A*w <= b."""
    nargchk(args, 3, 3, 'setInequality')
    p = _port(args[0], 'setInequality')
    _set(p, 'AInequality', args[1])
    _set(p, 'bInequality', args[2])
    return p


@_method('setEquality')
def setEquality(nargout, *args):
    """p = setEquality(p, AEquality, bEquality): linear constraints Aeq*w = beq."""
    nargchk(args, 3, 3, 'setEquality')
    p = _port(args[0], 'setEquality')
    _set(p, 'AEquality', args[1])
    _set(p, 'bEquality', args[2])
    return p


def _moments(p, fn):
    S = p.feasible_set(fn)
    return S, p.mean, p.cov


@_method('estimateFrontier')
def estimateFrontier(nargout, *args):
    """PortWts = estimateFrontier(p, NumPorts): NumPorts (10) portfolios on
    the efficient frontier, equally spaced in return from the least-risk one
    to the largest-return one, a column each."""
    nargchk(args, 1, 2, 'estimateFrontier')
    p = _port(args[0], 'estimateFrontier')
    k = int(num(args[1])) if len(args) > 1 else 10
    if k < 1:
        raise err('finance:estimateFrontier:NumPorts', 'NumPorts is a whole number from 1.', 'estimateFrontier')
    S, mu, C = _moments(p, 'estimateFrontier')
    return out(frontier(S, mu, C, k))


@_method('estimateFrontierLimits')
def estimateFrontierLimits(nargout, *args):
    """PortWts = estimateFrontierLimits(p, 'min' or 'max'): the frontier's ends (both, as two columns, unless one is asked for)."""
    nargchk(args, 1, 2, 'estimateFrontierLimits')
    p = _port(args[0], 'estimateFrontierLimits')
    S, mu, C = _moments(p, 'estimateFrontierLimits')
    wmin, wmax = frontier_limits(S, mu, C)
    which = (opt_str(args[1]) or '').lower() if len(args) > 1 else 'both'
    if which == 'min':
        return out(wmin.reshape(-1, 1))
    if which == 'max':
        return out(wmax.reshape(-1, 1))
    if which != 'both':
        raise err('finance:estimateFrontierLimits:Choice', "Choose 'min' or 'max'.", 'estimateFrontierLimits')
    return out(np.column_stack([wmin, wmax]))


@_method('estimateFrontierByReturn')
def estimateFrontierByReturn(nargout, *args):
    """PortWts = estimateFrontierByReturn(p, TargetReturn): the least-risk portfolio of each target return (within the frontier's range)."""
    nargchk(args, 2, 2, 'estimateFrontierByReturn')
    p = _port(args[0], 'estimateFrontierByReturn')
    S, mu, C = _moments(p, 'estimateFrontierByReturn')
    wmin, wmax = frontier_limits(S, mu, C)
    r0, r1 = float(mu @ wmin), float(mu @ wmax)
    W = []
    for t in np.asarray(darr(args[1]), float).reshape(-1):
        if t < r0 - 1e-12 * max(1, abs(r0)) or t > r1 + 1e-12 * max(1, abs(r1)):
            raise err('finance:estimateFrontierByReturn:OutOfRange', f'The target return {t:g} is outside the frontier ({r0:g} to {r1:g}).', 'estimateFrontierByReturn')
        W.append(wmin if t <= r0 else wmax if t >= r1 else by_return(S, mu, C, t))
    return out(np.column_stack(W))


@_method('estimateFrontierByRisk')
def estimateFrontierByRisk(nargout, *args):
    """PortWts = estimateFrontierByRisk(p, TargetRisk): the largest-return portfolio of each risk (standard deviation)."""
    nargchk(args, 2, 2, 'estimateFrontierByRisk')
    p = _port(args[0], 'estimateFrontierByRisk')
    S, mu, C = _moments(p, 'estimateFrontierByRisk')
    return out(np.column_stack([by_risk(S, mu, C, float(t)) for t in np.asarray(darr(args[1]), float).reshape(-1)]))


@_method('estimateMaxSharpeRatio')
def estimateMaxSharpeRatio(nargout, *args):
    """PortWts = estimateMaxSharpeRatio(p): the frontier portfolio with the largest Sharpe ratio, (return - RiskFreeRate)/risk."""
    nargchk(args, 1, 3, 'estimateMaxSharpeRatio')
    p = _port(args[0], 'estimateMaxSharpeRatio')
    S, mu, C = _moments(p, 'estimateMaxSharpeRatio')
    rf = p.rf if p.rf is not None else 0.0
    return out(max_sharpe(S, mu, C, rf).reshape(-1, 1))


def _weights(p, v, fn):
    W = np.asarray(darr(v, fn), float)
    if W.ndim == 2 and W.shape[0] != p.n and W.shape[1] == p.n:
        W = W.T
    if W.shape[0] != p.n:
        raise err(f'finance:{fn}:Size', f'The weights have a row for each of the {p.n} assets.', fn)
    return W


@_method('estimatePortReturn')
def estimatePortReturn(nargout, *args):
    """pret = estimatePortReturn(p, PortWts): each portfolio's expected return."""
    nargchk(args, 2, 2, 'estimatePortReturn')
    p = _port(args[0], 'estimatePortReturn')
    W = _weights(p, args[1], 'estimatePortReturn')
    return out((p.mean @ W).reshape(-1, 1))


@_method('estimatePortRisk')
def estimatePortRisk(nargout, *args):
    """prsk = estimatePortRisk(p, PortWts): each portfolio's standard deviation."""
    nargchk(args, 2, 2, 'estimatePortRisk')
    p = _port(args[0], 'estimatePortRisk')
    W = _weights(p, args[1], 'estimatePortRisk')
    return out(np.sqrt(np.maximum(np.einsum('ik,ij,jk->k', W, p.cov, W), 0)).reshape(-1, 1))


@_method('estimatePortMoments', nout=2)
def estimatePortMoments(nargout, *args):
    """[prsk, pret] = estimatePortMoments(p, PortWts): each portfolio's risk and return."""
    r = estimatePortRisk(1, *args)
    m = estimatePortReturn(1, *args)
    return (r, m) if nargout > 1 else r


@_method('plotFrontier', nout=2)
def plotFrontier(nargout, *args):
    """[prsk, pret] = plotFrontier(p, NumPorts): the efficient frontier (10 portfolios) drawn, risk against return."""
    nargchk(args, 1, 2, 'plotFrontier')
    p = _port(args[0], 'plotFrontier')
    W = np.asarray(estimateFrontier(1, p, *args[1:]), float)
    risk = np.sqrt(np.maximum(np.einsum('ik,ij,jk->k', W, p.cov, W), 0))
    ret = p.mean @ W
    if nargout == 0:
        b = lambda name, *a: R._builtin(name, *a)
        b('plot', out(risk.reshape(-1, 1)), out(ret.reshape(-1, 1)), Char.of('-o'), Char.of('MarkerSize'), 4.0)
        b('title', Char.of('Efficient Frontier' + (f' of {p.name}' if p.name else '')))
        b('xlabel', Char.of('Standard Deviation of Portfolio Returns'))
        b('ylabel', Char.of('Mean of Portfolio Returns'))
        return None
    return (out(risk.reshape(-1, 1)), out(ret.reshape(-1, 1))) if nargout > 1 else out(risk.reshape(-1, 1))


# ---- the older functions ----------------------------------------------------------------------------------------------------------

def _mu_cov(m, c, fn):
    mu = np.asarray(darr(m, fn), float).reshape(-1)
    C = np.atleast_2d(np.asarray(darr(c, fn), float))
    if C.shape != (mu.size, mu.size):
        raise err(f'finance:{fn}:Size', 'The covariance is square, with a row for each asset.', fn)
    return mu, (C + C.T) / 2


@bi('portopt', nout=3, arr=False)
def portopt(nargout, *args):
    """[PortRisk, PortReturn, PortWts] = portopt(ExpReturn, ExpCovariance,
    NumPorts, PortReturn, ConSet): portfolios on the efficient frontier,
    long only and fully invested unless ConSet ([A b]: A*w <= b) says
    more; without outputs the frontier drawn."""
    nargchk(args, 2, 5, 'portopt')
    mu, C = _mu_cov(args[0], args[1], 'portopt')
    n = mu.size
    A = b = None
    if len(args) > 4 and numel(args[4]):
        M = np.atleast_2d(np.asarray(darr(args[4]), float))
        if M.shape[1] != n + 1:
            raise err('finance:portopt:ConSet', f'ConSet is [A b], {n + 1} columns: A*w <= b.', 'portopt')
        A, b = M[:, :n], M[:, n]
    S = _Set(n, np.zeros(n), None, (1.0, 1.0), A, b)
    if len(args) > 3 and numel(args[3]):
        targets = np.asarray(darr(args[3]), float).reshape(-1)
        W = np.column_stack([by_return(S, mu, C, t) for t in targets])
    else:
        k = int(num(args[2])) if len(args) > 2 and numel(args[2]) else 10
        W = frontier(S, mu, C, k)
    risk = np.sqrt(np.maximum(np.einsum('ik,ij,jk->k', W, C, W), 0))
    ret = mu @ W
    if nargout == 0:
        b_ = lambda name, *a: R._builtin(name, *a)
        b_('plot', out(risk.reshape(-1, 1)), out(ret.reshape(-1, 1)), Char.of('-o'), Char.of('MarkerSize'), 4.0)
        b_('title', Char.of('Mean-Variance-Efficient Frontier'))
        b_('xlabel', Char.of('Risk (Standard Deviation)'))
        b_('ylabel', Char.of('Expected Return'))
        return None
    vals = (out(risk.reshape(-1, 1)), out(ret.reshape(-1, 1)), out(W.T))
    return vals[:nargout] if nargout > 1 else vals[0]


@bi('portstats', nout=2)
def portstats(nargout, *args):
    """[PortRisk, PortReturn] = portstats(ExpReturn, ExpCovariance, PortWts): each portfolio's (a row of weights) standard deviation and expected return."""
    nargchk(args, 2, 3, 'portstats')
    mu, C = _mu_cov(args[0], args[1], 'portstats')
    W = np.atleast_2d(np.asarray(darr(args[2]), float)) if len(args) > 2 else np.full((1, mu.size), 1 / mu.size)
    if W.shape[1] != mu.size:
        raise err('finance:portstats:Size', 'PortWts has a column for each asset.', 'portstats')
    risk = np.sqrt(np.maximum(np.einsum('ki,ij,kj->k', W, C, W), 0)).reshape(-1, 1)
    ret = (W @ mu).reshape(-1, 1)
    return (out(risk), out(ret)) if nargout > 1 else out(risk)


@bi('portvrisk')
def portvrisk(nargout, *args):
    """ValueAtRisk = portvrisk(PortReturn, PortRisk, RiskThreshold, PortValue):
    the loss that normal returns exceed with probability RiskThreshold
    (0.05), -(PortReturn + norminv(RiskThreshold)*PortRisk)*PortValue
    (PortValue 1); negative when even that case gains."""
    nargchk(args, 2, 4, 'portvrisk')
    from scipy.stats import norm
    ret = np.asarray(darr(args[0]), float)
    risk = np.asarray(darr(args[1]), float)
    th = np.asarray(darr(args[2]), float) if len(args) > 2 and numel(args[2]) else np.array(0.05)
    val = np.asarray(darr(args[3]), float) if len(args) > 3 and numel(args[3]) else np.array(1.0)
    if np.any((th <= 0) | (th >= 1)):
        raise err('finance:portvrisk:Threshold', 'RiskThreshold is a probability between 0 and 1.', 'portvrisk')
    ret, risk, th, val = np.broadcast_arrays(ret, risk, th, val)
    return out(-(ret + norm.ppf(th) * risk) * val)


@bi('corr2cov')
def corr2cov(nargout, *args):
    """ExpCovariance = corr2cov(ExpSigma, ExpCorrC): the covariance of standard deviations and correlations (the identity unless given)."""
    nargchk(args, 1, 2, 'corr2cov')
    s = np.asarray(darr(args[0]), float).reshape(-1)
    Cr = np.atleast_2d(np.asarray(darr(args[1]), float)) if len(args) > 1 and numel(args[1]) else np.eye(s.size)
    if Cr.shape != (s.size, s.size):
        raise err('finance:corr2cov:Size', 'ExpCorrC is square, with a row for each standard deviation.', 'corr2cov')
    return out(Cr * np.outer(s, s))


@bi('cov2corr', nout=2)
def cov2corr(nargout, *args):
    """[ExpSigma, ExpCorrC] = cov2corr(ExpCovariance): the standard deviations (a row) and correlations of a covariance."""
    nargchk(args, 1, 1, 'cov2corr')
    C = np.atleast_2d(np.asarray(darr(args[0]), float))
    if C.shape[0] != C.shape[1]:
        raise err('finance:cov2corr:NotSquare', 'ExpCovariance is square.', 'cov2corr')
    s = np.sqrt(np.diag(C))
    with np.errstate(divide='ignore', invalid='ignore'):
        Cr = C / np.outer(s, s)
    return (out(s.reshape(1, -1)), out(Cr)) if nargout > 1 else out(s.reshape(1, -1))


def classes():
    return (Portfolio,)
