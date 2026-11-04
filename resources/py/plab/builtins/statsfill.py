"""Statistics fill-ins: tiedrank, ecdfhist; nearest-neighbour searchers
(createns, KDTreeSearcher, ExhaustiveSearcher, with knnsearch and
rangesearch); rocmetrics; multinomial regression (mnrfit, mnrval:
nominal, ordinal and hierarchical); linear mixed-effects models (fitlme,
LinearMixedModel with fixedEffects, randomEffects, covarianceParameters,
predict, fitted, residuals and response); D-optimal designs by
coordinate exchange (cordexch, daugment, dcovary); quasi-random streams
(qrandstream, qrand, reset)."""
import math
import re

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, darr, out, opt_str, is_str
from ..values import MError, Obj, Char, Cell, Struct, EMPTY, numel, py_str
from .. import runtime as R


def bi(*names, **kw):
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                raise err(f'stats:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0]) from None
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _st():
    import scipy.stats as st
    return st


def _outs(nargout, *vals):
    return vals[:max(nargout, 1)] if nargout > 1 else vals[0]


def _col(v):
    return out(np.asarray(v, float).reshape(-1, 1))


def _pairs(args, fn, names):
    """Name-value pairs (any case) as {lower name: value}."""
    if len(args) % 2:
        raise err(f'stats:{fn}:pairs', 'The options come as names and values.', fn)
    o = {}
    for i in range(0, len(args), 2):
        k = opt_str(args[i])
        if k is None or k.lower() not in names:
            raise err(f'stats:{fn}:option', f"'{py_str(args[i]) if is_str(args[i]) else '?'}' is not an option of {fn}.", fn)
        o[k.lower()] = args[i + 1]
    return o


def _int(v):
    return int(round(float(np.asarray(darr(v), float).reshape(-1)[0])))


def _rs():
    from .elmat import RNG
    return RNG.rs


def _wrap(name, test, handler):
    """name's builtin, with handler taking the call when test(first argument) holds."""
    info = REG.get(name)
    if info is None:
        return
    orig, ws, aw = info.fn, info.ws, info.aw
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


# ---- ranks, ecdf histograms ---------------------------------------------------------------------------------------------------

def _ranks(x, bidir):
    n = x.size
    order = np.argsort(x, kind='stable')
    xs = x[order]
    ranks = np.empty(n)
    ties = []
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1] == xs[i]:
            j += 1
        if bidir:
            pos = np.arange(i, j + 1)
            r = np.minimum(pos + 1, n - pos)
            ranks[order[i:j + 1]] = r.mean()
        else:
            ranks[order[i:j + 1]] = (i + j) / 2 + 1
        if j > i:
            ties.append(j - i + 1)
        i = j + 1
    t = np.array(ties, float)
    return ranks, float(np.sum(t ** 3 - t) / 2)


@bi('tiedrank', nout=2)
def tiedrank(nargout, *args):
    """[r, tieadj] = tiedrank(x), tiedrank(x, 0, bidir): the ranks of x, ties given their average rank (NaN stays NaN); tieadj = sum(t.^3 - t)/2 over the groups of t ties; bidir 1 ranks from both ends (the smallest and the largest 1, ...). Each column of a matrix."""
    nargchk(args, 1, 3, 'tiedrank')
    a = np.asarray(darr(args[0]), float)
    if len(args) > 1 and numel(args[1]) and float(np.asarray(darr(args[1])).reshape(-1)[0]) != 0:
        raise err('stats:tiedrank:tieflag', 'tieflag 1 (the Ansari-Bradley adjustment) is not made here; leave it 0.', 'tiedrank')
    bidir = len(args) > 2 and bool(np.asarray(darr(args[2])).reshape(-1)[0])
    row = a.ndim == 2 and a.shape[0] == 1
    A = a.reshape(-1, 1) if row or a.ndim < 2 else a
    R_ = np.full(A.shape, np.nan)
    adj = []
    for j in range(A.shape[1]):
        ok = ~np.isnan(A[:, j])
        r, t = _ranks(A[ok, j], bidir)
        R_[ok, j] = r
        adj.append(t)
    res = R_.reshape(a.shape)
    return _outs(nargout, out(res), adj[0] if len(adj) == 1 else out(np.array(adj).reshape(1, -1)))


@bi('ecdfhist', nout=2)
def ecdfhist(nargout, *args):
    """[n, c] = ecdfhist(f, x, m): a histogram of the density from the empirical cdf ecdf gives (f at x): the probability in each of m (10) equal bins (or bins centred at the values of m when it is a vector) over the bin width; drawn as bars when no output is asked for."""
    nargchk(args, 2, 3, 'ecdfhist')
    F = np.asarray(darr(args[0]), float).reshape(-1)
    x = np.asarray(darr(args[1]), float).reshape(-1)
    if F.size != x.size:
        raise err('stats:ecdfhist:size', 'f and x are the same size (as ecdf gives them).', 'ecdfhist')
    lo, hi = x[0] if x.size else 0.0, x[-1] if x.size else 1.0
    if len(args) > 2 and numel(args[2]) > 1:
        c = np.asarray(darr(args[2]), float).reshape(-1)
        mid = (c[:-1] + c[1:]) / 2
        edges = np.concatenate([[c[0] - (mid[0] - c[0])], mid, [c[-1] + (c[-1] - mid[-1])]])
    else:
        m = _int(args[2]) if len(args) > 2 and numel(args[2]) else 10
        edges = np.linspace(lo, hi, m + 1)
        c = (edges[:-1] + edges[1:]) / 2
    # the cdf at each edge: the step function's value just after it
    def cdf(t):
        k = np.searchsorted(x, t, side='right') - 1
        return np.where(k < 0, 0.0, F[np.clip(k, 0, F.size - 1)])
    Fe = cdf(edges)
    Fe[-1] = 1.0
    Fe[0] = 0.0
    n = np.diff(Fe) / np.diff(edges)
    if nargout == 0:
        R._builtin('bar', out(c.reshape(1, -1)), out(n.reshape(1, -1)), 1.0)
        return None
    return _outs(nargout, out(n.reshape(1, -1)), out(c.reshape(1, -1)))


# ---- nearest-neighbour searchers -------------------------------------------------------------------------------------------------

class Searcher(Obj):
    is_handle = False

    def __init__(self, kind, X, distance='euclidean', extra=None, bucket=50.0):
        self.kind, self.X, self.distance, self.extra, self.bucket = kind, X, distance, extra, bucket

    @property
    def cls(self):
        return 'KDTreeSearcher' if self.kind == 'kdtree' else 'ExhaustiveSearcher'

    def value_copy(self):
        return self

    def getprop(self, name):
        k = name.lower()
        if k == 'x':
            return out(self.X)
        if k == 'distance':
            return Char.of(self.distance) if isinstance(self.distance, str) else self.distance
        if k == 'distparameter':
            return self.extra if self.extra is not None else EMPTY()
        if k == 'bucketsize' and self.kind == 'kdtree':
            return self.bucket
        if k in ('knnsearch', 'rangesearch'):
            from .classdef import BoundBuiltin
            return BoundBuiltin(self, name)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class '{self.cls}'.")

    def setprop(self, name, value):
        k = name.lower()
        if k == 'distance':
            self.distance = py_str(value).lower() if is_str(value) else value
            return
        if k == 'distparameter':
            self.extra = value
            return
        raise MError('MATLAB:class:SetProhibited', f"You cannot set the '{name}' property of {self.cls}.")

    def propnames(self):
        return ['X', 'Distance', 'DistParameter'] + (['BucketSize'] if self.kind == 'kdtree' else [])

    def display_lines(self):
        lines = [f'  {self.cls} with properties:', '']
        if self.kind == 'kdtree':
            lines.append(f'       BucketSize: {self.bucket:g}')
        lines += [f"         Distance: '{self.distance if isinstance(self.distance, str) else 'function handle'}'",
                  '    DistParameter: ' + ('[]' if self.extra is None else '[' + ' '.join(f'{v:g}' for v in np.asarray(darr(self.extra)).reshape(-1)) + ']'),
                  f'                X: [{self.X.shape[0]}×{self.X.shape[1]} double]']
        return lines

    def options(self):
        """The searcher's distance as knnsearch's options."""
        if not isinstance(self.distance, str):
            return [Char.of('Distance'), self.distance]
        o = [Char.of('Distance'), Char.of(self.distance)]
        if self.extra is not None:
            key = {'minkowski': 'P', 'seuclidean': 'Scale', 'mahalanobis': 'Cov'}.get(self.distance)
            if key:
                o += [Char.of(key), self.extra]
        return o


_KD_DIST = ('euclidean', 'cityblock', 'minkowski', 'chebychev')


def _searcher(kind, args, fn):
    X = np.asarray(darr(args[0]), float)
    if X.ndim != 2:
        raise err(f'stats:{fn}:X', 'X is a matrix, one point in each row.', fn)
    o = _pairs(list(args[1:]), fn, ('distance', 'p', 'scale', 'cov', 'bucketsize', 'nsmethod'))
    if 'nsmethod' in o:
        kind = py_str(o['nsmethod']).lower()
        if kind not in ('kdtree', 'exhaustive'):
            raise err(f'stats:{fn}:NSMethod', "NSMethod is 'kdtree' or 'exhaustive'.", fn)
    dist = 'euclidean'
    if 'distance' in o:
        dist = py_str(o['distance']).lower() if is_str(o['distance']) else o['distance']
    if fn == 'createns' and 'nsmethod' not in o:
        kind = 'kdtree' if X.shape[1] <= 10 and isinstance(dist, str) and dist in _KD_DIST else 'exhaustive'
    if kind == 'kdtree' and not (isinstance(dist, str) and dist in _KD_DIST):
        raise err(f'stats:{fn}:distance', "A KDTreeSearcher takes the 'euclidean', 'cityblock', 'minkowski' or 'chebychev' distance.", fn)
    extra = o.get('p') if dist == 'minkowski' else o.get('scale') if dist == 'seuclidean' else o.get('cov') if dist == 'mahalanobis' else None
    if dist == 'minkowski' and extra is None:
        extra = 2.0
    bucket = float(np.asarray(darr(o['bucketsize'])).reshape(-1)[0]) if 'bucketsize' in o else 50.0
    return Searcher(kind, X, dist, extra, bucket)


@bi('createns', arr=False)
def createns(nargout, *args):
    """ns = createns(X, 'NSMethod', m, 'Distance', d, 'BucketSize', b): a nearest-neighbour searcher over the rows of X: a KDTreeSearcher (the default for up to 10 columns and the Euclidean, city block, Minkowski or Chebychev distance) or an ExhaustiveSearcher; knnsearch(ns, Y) and rangesearch(ns, Y, r) search it."""
    nargchk(args, 1, 9, 'createns')
    return _searcher('kdtree', args, 'createns')


@bi('KDTreeSearcher', arr=False)
def KDTreeSearcher(nargout, *args):
    """ns = KDTreeSearcher(X, 'Distance', d, 'P', p, 'BucketSize', b): a Kd-tree searcher over the rows of X."""
    nargchk(args, 1, 7, 'KDTreeSearcher')
    return _searcher('kdtree', args, 'KDTreeSearcher')


@bi('ExhaustiveSearcher', arr=False)
def ExhaustiveSearcher(nargout, *args):
    """ns = ExhaustiveSearcher(X, 'Distance', d, ...): a searcher that measures the distance to every row of X."""
    nargchk(args, 1, 7, 'ExhaustiveSearcher')
    return _searcher('exhaustive', args, 'ExhaustiveSearcher')


def _ns_search(name):
    def handler(nargout, ns, *rest):
        rest = list(rest)
        has_dist = any(is_str(a) and py_str(a).lower() == 'distance' for a in rest)
        extra = [] if has_dist else ns.options()
        return REG_ORIG[name](nargout, out(ns.X), *rest, *extra)
    return handler


REG_ORIG = {}
for _n in ('knnsearch', 'rangesearch'):
    if _n in REG:
        REG_ORIG[_n] = REG[_n].fn
        _wrap(_n, lambda v: isinstance(v, Searcher), _ns_search(_n))


# ---- rocmetrics --------------------------------------------------------------------------------------------------------------------

class ROC(Obj):
    cls = 'rocmetrics'
    is_handle = False

    def __init__(self, labels, scores, classes, curves, aucs, label_value):
        self.labels, self.scores, self.classes, self.curves, self.aucs, self.label_value = labels, scores, classes, curves, aucs, label_value

    def value_copy(self):
        return self

    def class_cell(self):
        return Cell.of_list([Char.of(c) for c in self.classes], (1, len(self.classes)))

    def metrics(self):
        from .tables import Table
        from .categoricals import Categorical
        names, thr, fpr, tpr = [], [], [], []
        for c, (x, y, t) in zip(self.classes, self.curves):
            names += [c] * x.size
            thr.append(t)
            fpr.append(x)
            tpr.append(y)
        cat = REG['categorical'].fn(1, Cell.of_list([Char.of(s) for s in names], (len(names), 1)))
        if not isinstance(cat, Categorical):
            cat = Cell.of_list([Char.of(s) for s in names], (len(names), 1))
        return Table([cat, _col(np.concatenate(thr)), _col(np.concatenate(fpr)), _col(np.concatenate(tpr))],
                     ['ClassName', 'Threshold', 'FalsePositiveRate', 'TruePositiveRate'])

    def getprop(self, name):
        k = name.lower()
        if k == 'auc':
            return out(np.array(self.aucs).reshape(1, -1))
        if k == 'classnames':
            return self.class_cell()
        if k == 'metrics':
            return self.metrics()
        if k == 'labels':
            return self.label_value
        if k == 'scores':
            return out(self.scores)
        if k == 'plot':
            from .classdef import BoundBuiltin
            return BoundBuiltin(self, name)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'rocmetrics'.")

    def propnames(self):
        return ['Metrics', 'AUC', 'ClassNames', 'Labels', 'Scores']

    def display_lines(self):
        k = len(self.classes)
        n = sum(x.size for x, _, _ in self.curves)
        return ['  rocmetrics with properties:', '', f'    Metrics: [{n}×4 table]', '        AUC: [' + '  '.join(f'{a:.4f}' for a in self.aucs) + ']',
                '', '  ' + f'{k} class{"es" if k != 1 else ""}: ' + ', '.join(self.classes)]


def _roc_curve(pos, s):
    """(FPR, TPR, thresholds) from the highest threshold down, starting at (0, 0); the area by trapezoids."""
    order = np.argsort(-s, kind='stable')
    s, pos = s[order], pos[order]
    P, N = pos.sum(), (~pos).sum()
    thr = np.unique(s)[::-1]
    tp = np.array([np.sum(pos & (s >= t)) for t in thr], float)
    fp = np.array([np.sum(~pos & (s >= t)) for t in thr], float)
    x = np.concatenate([[0.0], fp / max(N, 1)])
    y = np.concatenate([[0.0], tp / max(P, 1)])
    t = np.concatenate([[thr[0]] if thr.size else [0.0], thr])
    return x, y, t, float(np.trapezoid(y, x) if hasattr(np, 'trapezoid') else np.trapz(y, x))


@bi('rocmetrics', arr=False)
def rocmetrics(nargout, *args):
    """rocObj = rocmetrics(labels, scores, classNames): the ROC curve of each class against the rest: scores a column for each class (or a vector for the first), Metrics (ClassName, Threshold, FalsePositiveRate, TruePositiveRate) and AUC; plot(rocObj) draws them."""
    nargchk(args, 3, 3, 'rocmetrics')
    from .mlmodels import Labels
    L = Labels(args[0], 'rocmetrics')
    S = np.asarray(darr(args[1]), float)
    S = S.reshape(-1, 1) if S.ndim == 1 or (S.ndim == 2 and S.shape[0] == 1 and S.shape[1] == L.idx.size) else S
    if S.shape[0] != L.idx.size and S.shape[1] == L.idx.size:
        S = S.T
    cn = Labels(args[2], 'rocmetrics').classes
    if S.shape[1] != len(cn):
        raise err('stats:rocmetrics:scores', 'scores has a column for each of classNames.', 'rocmetrics')
    names = [str(c) if not isinstance(c, float) else f'{c:g}' for c in cn]
    labs = [L.classes[i] if i >= 0 else None for i in L.idx]
    curves, aucs = [], []
    for j, c in enumerate(cn):
        pos = np.array([v == c for v in labs])
        keep = np.array([v is not None for v in labs]) & np.isfinite(S[:, j])
        x, y, t, a = _roc_curve(pos[keep], S[keep, j])
        curves.append((x, y, t))
        aucs.append(a)
    return ROC(args[0], S, names, curves, aucs, args[0])


def _roc_plot(nargout, r, *rest):
    ax = R._builtin('gca')
    for c, (x, y, _) in zip(r.classes, r.curves):
        R._builtin('plot', ax, _col(x), _col(y), Char.of('DisplayName'), Char.of(f'{c} (AUC = {r.aucs[r.classes.index(c)]:.4g})'))
        R._builtin('hold', ax, Char.of('on'))
    R._builtin('plot', ax, out(np.array([[0.0], [1.0]])), out(np.array([[0.0], [1.0]])), Char.of('k:'), Char.of('HandleVisibility'), Char.of('off'))
    R._builtin('hold', ax, Char.of('off'))
    R._builtin('xlabel', ax, Char.of('False Positive Rate'))
    R._builtin('ylabel', ax, Char.of('True Positive Rate'))
    R._builtin('title', ax, Char.of('ROC Curve'))
    R._builtin('legend', ax, Char.of('Location'), Char.of('southeast'))
    return None


_wrap('plot', lambda v: isinstance(v, ROC), _roc_plot)


# ---- multinomial regression --------------------------------------------------------------------------------------------------------

def _cdf(link):
    st = _st()
    if link == 'logit':
        return lambda z: 1 / (1 + np.exp(-z)), lambda z: np.exp(-np.abs(z)) / (1 + np.exp(-np.abs(z))) ** 2
    if link == 'probit':
        return st.norm.cdf, st.norm.pdf
    if link == 'comploglog':
        return lambda z: 1 - np.exp(-np.exp(z)), lambda z: np.exp(z - np.exp(z))
    if link == 'loglog':
        return lambda z: np.exp(-np.exp(-z)), lambda z: np.exp(-z - np.exp(-z))
    raise err('stats:mnrfit:link', "The link is 'logit', 'probit', 'comploglog' or 'loglog'.", 'mnrfit')


def _mnr_counts(Y, n):
    Y = np.asarray(darr(Y), float)
    if Y.ndim == 2 and Y.shape[1] > 1 and Y.shape[0] == n:
        return Y
    y = Y.reshape(-1)
    if y.size != n or np.any(y != np.round(y)) or np.any(y < 1):
        raise err('stats:mnrfit:Y', 'Y is a column of category numbers 1 .. k, or a matrix of counts with a column for each category.', 'mnrfit')
    k = int(y.max())
    C = np.zeros((n, k))
    C[np.arange(n), y.astype(int) - 1] = 1
    return C


def _probs(B, X1, model, link, k, inter):
    """The category probabilities (n, k) for the parameters B."""
    n = X1.shape[0]
    if model == 'nominal':
        Bm = B.reshape(X1.shape[1], k - 1, order='F')
        eta = X1 @ Bm
        top = np.maximum(eta.max(axis=1, keepdims=True), 0)
        e = np.exp(eta - top)
        denom = e.sum(axis=1, keepdims=True) + np.exp(-top)
        return np.hstack([e / denom, np.exp(-top) / denom])
    F, _ = _cdf(link)
    p = X1.shape[1] - 1
    if model == 'ordinal':
        if inter:
            eta = X1 @ B.reshape(p + 1, k - 1, order='F')
        else:
            eta = B[:k - 1][None, :] + (X1[:, 1:] @ B[k - 1:])[:, None]
        G = F(eta)
        cum = np.hstack([np.zeros((n, 1)), G, np.ones((n, 1))])
        return np.diff(cum, axis=1)
    # hierarchical: P(y = j | y >= j) = F(alpha_j + x*beta_j)
    if inter:
        Bm = B.reshape(p + 1, k - 1, order='F')
        eta = X1 @ Bm
    else:
        eta = B[:k - 1][None, :] + (X1[:, 1:] @ B[k - 1:])[:, None]
    c = F(eta)
    P = np.zeros((n, k))
    rest = np.ones(n)
    for j in range(k - 1):
        P[:, j] = rest * c[:, j]
        rest = rest * (1 - c[:, j])
    P[:, k - 1] = rest
    return P


def _mnr_args(args, fn):
    o = _pairs(list(args), fn, ('model', 'interactions', 'link', 'estdisp', 'type', 'confidence'))
    model = py_str(o['model']).lower() if 'model' in o else 'nominal'
    if model not in ('nominal', 'ordinal', 'hierarchical'):
        raise err(f'stats:{fn}:model', "The model is 'nominal', 'ordinal' or 'hierarchical'.", fn)
    inter = (py_str(o['interactions']).lower() == 'on') if 'interactions' in o else model != 'ordinal'
    link = py_str(o['link']).lower() if 'link' in o else 'logit'
    if model == 'nominal' and link != 'logit':
        raise err(f'stats:{fn}:link', 'A nominal model has the logit link.', fn)
    return model, inter, link, o


def _matrix_layout(model, inter):
    """Whether B is (p+1)-by-(k-1), a column for each category's intercept and slopes (else the k-1 intercepts, then the shared slopes)."""
    return model == 'nominal' or inter


def _nparams(model, inter, k, p):
    return (p + 1) * (k - 1) if _matrix_layout(model, inter) else (k - 1) + p


@bi('mnrfit', nout=3)
def mnrfit(nargout, *args):
    """[B, dev, stats] = mnrfit(X, Y, 'model', m, 'interactions', 'on'/'off', 'link', l): multinomial regression by maximum likelihood: 'nominal' (log odds of each category against the last, a column of B each), 'ordinal' (log(P(y <= j)/P(y > j)) = alpha_j + x*beta: B the k-1 intercepts then the slopes) or 'hierarchical' (P(y = j | y >= j)); Y the categories 1..k or counts; stats has beta, dfe, se, covb, coeffcorr, t and p."""
    nargchk(args, 2, 10, 'mnrfit')
    X = np.asarray(darr(args[0]), float)
    X = X.reshape(-1, 1) if X.ndim == 1 or (X.ndim == 2 and X.shape[0] == 1) else X
    n, p = X.shape
    Y = _mnr_counts(args[1], n)
    k = Y.shape[1]
    model, inter, link, _ = _mnr_args(args[2:], 'mnrfit')
    X1 = np.hstack([np.ones((n, 1)), X])
    m = Y.sum(axis=1)
    keep = m > 0
    X1, Y, m = X1[keep], Y[keep], m[keep]

    def nll(B):
        P = np.clip(_probs(B, X1, model, link, k, inter), 1e-300, 1)
        return -float(np.sum(Y * np.log(P)))
    npar = _nparams(model, inter, k, p)
    B0 = np.zeros(npar)
    if model == 'ordinal':
        cum = np.clip(np.cumsum(Y.sum(axis=0))[:-1] / Y.sum(), 1e-6, 1 - 1e-6)
        start = np.maximum.accumulate(np.log(cum / (1 - cum)))
        if _matrix_layout(model, inter):
            B0[0::p + 1] = start
        else:
            B0[:k - 1] = start
    from scipy.optimize import minimize
    res = minimize(nll, B0, method='BFGS', options={'gtol': 1e-10, 'maxiter': 2000})
    B = res.x
    for _ in range(2):
        res = minimize(nll, B, method='Nelder-Mead' if npar <= 3 else 'BFGS', options={'xatol': 1e-12, 'fatol': 1e-14, 'maxiter': 20000} if npar <= 3 else {'gtol': 1e-12, 'maxiter': 2000})
        B = res.x
    # the Hessian by central differences of the negative log-likelihood
    h = 1e-4 * np.maximum(1, np.abs(B))
    H = np.zeros((npar, npar))
    for i in range(npar):
        for j in range(i, npar):
            ei, ej = np.zeros(npar), np.zeros(npar)
            ei[i], ej[j] = h[i], h[j]
            H[i, j] = H[j, i] = (nll(B + ei + ej) - nll(B + ei - ej) - nll(B - ei + ej) + nll(B - ei - ej)) / (4 * h[i] * h[j])
    covb = np.linalg.pinv(H)
    se = np.sqrt(np.maximum(np.diag(covb), 0))
    P = _probs(B, X1, model, link, k, inter)
    with np.errstate(divide='ignore', invalid='ignore'):
        mu = m[:, None] * P
        dev = 2 * float(np.sum(np.where(Y > 0, Y * np.log(Y / mu), 0)))
    dfe = n * (k - 1) - npar
    with np.errstate(all='ignore'):
        t = B / se
        corr = covb / np.outer(se, se)
    pv = 2 * _st().norm.sf(np.abs(t))
    shape = (p + 1, k - 1) if _matrix_layout(model, inter) else (npar, 1)

    def sh(v):
        return out(np.asarray(v, float).reshape(shape, order='F'))
    stats = Struct.scalar({'beta': sh(B), 'dfe': float(dfe), 'sfit': math.nan, 's': 1.0, 'estdisp': 0.0, 'covb': out(covb), 'coeffcorr': out(corr),
                           'se': sh(se), 't': sh(t), 'p': sh(pv)})
    return _outs(nargout, sh(B), dev, stats)


@bi('mnrval')
def mnrval(nargout, *args):
    """pihat = mnrval(B, X, 'model', m, 'interactions', on/off, 'link', l), mnrval(B, X, ssize, ..., 'type', 'count'): the category probabilities (counts) for the rows of X from mnrfit's B."""
    nargchk(args, 2, 12, 'mnrval')
    B = np.asarray(darr(args[0]), float)
    X = np.asarray(darr(args[1]), float)
    X = X.reshape(-1, 1) if X.ndim < 2 else X
    rest = list(args[2:])
    ssize = None
    if rest and not is_str(rest[0]):
        ssize = np.asarray(darr(rest.pop(0)), float).reshape(-1)
    model, inter, link, o = _mnr_args(rest, 'mnrval')
    n, p = X.shape
    if _matrix_layout(model, inter):
        if B.ndim != 2 or B.shape[0] != p + 1:
            raise err('stats:mnrval:B', f'B has a row for the intercept and each of the {p} predictors.', 'mnrval')
        k = B.shape[1] + 1
        flat = B.reshape(-1, order='F')
    else:
        flat = B.reshape(-1)
        k = flat.size - p + 1
    P = _probs(flat, np.hstack([np.ones((n, 1)), X]), model, link, k, inter)
    if 'type' in o and py_str(o['type']).lower() == 'count':
        if ssize is None:
            raise err('stats:mnrval:ssize', "'type' 'count' needs the sample sizes ssize.", 'mnrval')
        P = P * ssize[:, None]
    return out(P)


# ---- linear mixed-effects models ----------------------------------------------------------------------------------------------------

class _RTerm:
    """A random-effects term: its design columns (n, q), names, grouping codes and level names."""

    def __init__(self, Z, names, codes, levels, gname):
        self.Z, self.names, self.codes, self.levels, self.gname = Z, names, codes, levels, gname
        self.q = Z.shape[1]
        self.L = len(levels)


def _group_codes(data, gtext, fn):
    parts = gtext.split(':')
    keys = []
    for v in parts:
        if v not in data.cols:
            raise err(f'stats:{fn}:formula', f"The grouping variable '{v}' is not a variable of the data.", fn)
        c = data.cols[v]
        if isinstance(c, tuple):
            codes, lv = c
            keys.append([lv[i] for i in codes])
        else:
            keys.append([f'{x:g}' for x in c])
    rows = list(zip(*keys))
    levels = sorted(set(rows), key=lambda r: tuple((0, float(x)) if re.fullmatch(r'-?\d+(\.\d+)?(e-?\d+)?', x) else (1, x) for x in r))
    pos = {r: i for i, r in enumerate(levels)}
    return np.array([pos[r] for r in rows]), [' '.join(r) for r in levels]


def _lme_parse(data, formula, fn):
    from .regression import _parse_rhs, Design
    if '~' not in formula:
        raise err(f'stats:{fn}:formula', "The formula is 'y ~ fixed + (random | group)'.", fn)
    lhs, rhs = formula.split('~', 1)
    lhs = lhs.strip()
    if lhs not in data.names:
        raise err(f'stats:{fn}:formula', f"The response '{lhs}' is not a variable of the data.", fn)
    data.response = lhs
    rand = re.findall(r'\(([^()|]*)\|([^()]*)\)', rhs)
    fixed = re.sub(r'[+]?\s*\([^()|]*\|[^()]*\)', '', rhs).strip()
    fixed = re.sub(r'^\s*\+', '', fixed).strip() or '1'
    others = [nm for nm in data.names if nm != lhs]
    terms, icpt = _parse_rhs(fixed, others, fn)
    fixed_design = Design(data, terms, icpt)
    rterms = []
    for expr, g in rand:
        rt, ri = _parse_rhs(expr.strip(), others, fn)
        d = Design(data, rt, ri)
        Z, names, _ = d.matrix(data.cols)
        codes, levels = _group_codes(data, g.strip(), fn)
        rterms.append(_RTerm(Z, names, codes, levels, g.strip()))
    if not rterms:
        raise err(f'stats:{fn}:formula', 'The formula has no random-effects term (expr | group).', fn)
    return fixed_design, rterms, lhs


def _lme_Z(rterms, n):
    """The random-effects design (n, sum of L*q), each term's effects by level, then by effect within a level."""
    blocks = []
    for t in rterms:
        Zt = np.zeros((n, t.L * t.q))
        for j in range(t.q):
            Zt[np.arange(n), t.codes * t.q + j] = t.Z[:, j]
        blocks.append(Zt)
    return np.hstack(blocks)


def _theta_to_T(theta, rterms):
    Ts, k = [], 0
    for t in rterms:
        T = np.zeros((t.q, t.q))
        idx = np.tril_indices(t.q)
        m = idx[0].size
        T[idx] = theta[k:k + m]
        k += m
        Ts.append(T)
    return Ts


def _Lambda(Ts, rterms):
    from scipy.linalg import block_diag
    return block_diag(*[np.kron(np.eye(t.L), T) for t, T in zip(rterms, Ts)])


def _lme_solve(theta, X, y, Z, rterms, reml):
    n, p = X.shape
    Lam = _Lambda(_theta_to_T(theta, rterms), rterms)
    ZL = Z @ Lam
    q = ZL.shape[1]
    A11 = ZL.T @ ZL + np.eye(q)
    L1 = np.linalg.cholesky(A11)
    from scipy.linalg import solve_triangular
    R12 = solve_triangular(L1, ZL.T @ X, lower=True)
    cu = solve_triangular(L1, ZL.T @ y, lower=True)
    S = X.T @ X - R12.T @ R12
    RX = np.linalg.cholesky(S)
    rhs = X.T @ y - R12.T @ cu
    beta = solve_triangular(RX.T, solve_triangular(RX, rhs, lower=True), lower=False)
    u = solve_triangular(L1.T, cu - R12 @ beta, lower=False)
    res = y - X @ beta - ZL @ u
    r2 = float(res @ res + u @ u)
    ld = 2 * float(np.sum(np.log(np.diag(L1))))
    if reml:
        ldx = 2 * float(np.sum(np.log(np.diag(RX))))
        dev = ld + ldx + (n - p) * (1 + math.log(2 * math.pi * r2 / (n - p)))
    else:
        dev = ld + n * (1 + math.log(2 * math.pi * r2 / n))
    return dev, beta, u, Lam, S, r2


class LinearMixedModel(Obj):
    cls = 'LinearMixedModel'
    is_handle = False

    def __init__(self, data, fixed, rterms, X, xnames, y, reml, formula):
        self.data, self.fixed, self.rterms, self.X, self.xnames, self.y, self.reml, self.formula = data, fixed, rterms, X, xnames, y, reml, formula
        n, p = X.shape
        self.n, self.p = n, p
        self.Z = _lme_Z(rterms, n)
        ntheta = sum(t.q * (t.q + 1) // 2 for t in rterms)
        theta0 = np.concatenate([np.eye(t.q)[np.tril_indices(t.q)] for t in rterms])
        lower = np.concatenate([np.where(np.tril_indices(t.q)[0] == np.tril_indices(t.q)[1], 0.0, -np.inf) for t in rterms])
        from scipy.optimize import minimize
        f = lambda th: _lme_solve(th, X, y, self.Z, rterms, reml)[0]  # noqa: E731
        best = None
        for start in (theta0, theta0 * 0.3):
            r = minimize(f, start, method='L-BFGS-B', bounds=list(zip(lower, [np.inf] * ntheta)), options={'ftol': 1e-14, 'gtol': 1e-10, 'maxiter': 5000})
            r2 = minimize(f, r.x, method='Nelder-Mead', options={'xatol': 1e-10, 'fatol': 1e-12, 'maxiter': 20000})
            th = r2.x if r2.fun <= r.fun else r.x
            th = np.where(lower == 0, np.abs(th), th)
            val = f(th)
            if best is None or val < best[1]:
                best = (th, val)
        self.theta = best[0]
        dev, beta, u, Lam, S, r2 = _lme_solve(self.theta, X, y, self.Z, rterms, reml)
        self.dev = dev
        self.beta = beta
        self.sigma2 = r2 / (n - p if reml else n)
        self.b = Lam @ u
        self.covb = self.sigma2 * np.linalg.inv(S)
        self.se = np.sqrt(np.maximum(np.diag(self.covb), 0))
        self.dfe = n - p
        self.Ts = _theta_to_T(self.theta, rterms)
        self.loglik = -dev / 2
        self.ncov = ntheta
        k = p + ntheta + 1
        self.aic = dev + 2 * k
        self.bic = dev + k * math.log(n - p if reml else n)
        self.fitted_c = X @ beta + self.Z @ self.b
        self.fitted_m = X @ beta

    def value_copy(self):
        return self

    def coef_rows(self, alpha=0.05):
        st = _st()
        with np.errstate(all='ignore'):
            t = self.beta / self.se
        pv = 2 * st.t.sf(np.abs(t), self.dfe)
        h = st.t.ppf(1 - alpha / 2, self.dfe) * self.se
        return t, pv, self.beta - h, self.beta + h

    def coef_table(self):
        from .tables import Table
        t, pv, lo, hi = self.coef_rows()
        names = Cell.of_list([Char.of(s) for s in self.xnames], (len(self.xnames), 1))
        return Table([names, _col(self.beta), _col(self.se), _col(t), _col(np.full(self.p, float(self.dfe))), _col(pv), _col(lo), _col(hi)],
                     ['Name', 'Estimate', 'SE', 'tStat', 'DF', 'pValue', 'Lower', 'Upper'])

    def cov_rows(self, k):
        """(name1, name2, type, estimate) rows of term k's covariance: standard deviations and correlations."""
        t, T = self.rterms[k], self.Ts[k]
        C = self.sigma2 * T @ T.T
        sd = np.sqrt(np.maximum(np.diag(C), 0))
        rows = []
        for i in range(t.q):
            for j in range(i, t.q):
                if i == j:
                    rows.append((t.names[i], t.names[i], 'std', float(sd[i])))
        for i in range(t.q):
            for j in range(i + 1, t.q):
                rows.append((t.names[j], t.names[i], 'corr', float(C[i, j] / (sd[i] * sd[j])) if sd[i] * sd[j] > 0 else math.nan))
        return rows

    def getprop(self, name):
        k = name.lower()
        resid = self.y - self.fitted_c
        sse = float(resid @ resid)
        sst = float(np.sum((self.y - self.y.mean()) ** 2))
        vals = {
            'coefficients': lambda: self.coef_table(),
            'coefficientnames': lambda: Cell.of_list([Char.of(s) for s in self.xnames], (1, len(self.xnames))),
            'coefficientcovariance': lambda: out(self.covb),
            'loglikelihood': lambda: self.loglik,
            'modelcriterion': lambda: Struct.scalar({'AIC': self.aic, 'BIC': self.bic, 'LogLikelihood': self.loglik, 'Deviance': self.dev}),
            'numobservations': lambda: float(self.n),
            'numpredictors': lambda: float(len(self.data.predictors)),
            'numestimatedcoefficients': lambda: float(self.p),
            'numcoefficients': lambda: float(self.p),
            'dfe': lambda: float(self.dfe),
            'mse': lambda: self.sigma2,
            'sse': lambda: sse,
            'sst': lambda: sst,
            'ssr': lambda: sst - sse,
            'rsquared': lambda: Struct.scalar({'Ordinary': 1 - sse / sst if sst > 0 else math.nan,
                                               'Adjusted': 1 - (sse / self.dfe) / (sst / (self.n - 1)) if sst > 0 and self.dfe > 0 else math.nan}),
            'fitmethod': lambda: Char.of('REML' if self.reml else 'ML'),
            'formula': lambda: Char.of(self.formula),
            'responsename': lambda: Char.of(self.data.response),
            'predictornames': lambda: Cell.of_list([Char.of(s) for s in self.data.predictors], (1, len(self.data.predictors))),
        }
        if k in vals:
            return vals[k]()
        if k in ('fixedeffects', 'randomeffects', 'covarianceparameters', 'predict', 'fitted', 'residuals', 'response'):
            from .classdef import BoundBuiltin
            return BoundBuiltin(self, name)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'LinearMixedModel'.")

    def propnames(self):
        return ['Coefficients', 'CoefficientNames', 'CoefficientCovariance', 'DFE', 'FitMethod', 'Formula', 'LogLikelihood', 'MSE', 'ModelCriterion',
                'NumCoefficients', 'NumEstimatedCoefficients', 'NumObservations', 'NumPredictors', 'PredictorNames', 'ResponseName', 'Rsquared', 'SSE', 'SSR', 'SST']

    def display_lines(self):
        from .regression import _fmt
        q = sum(t.L * t.q for t in self.rterms)
        lines = [f'Linear mixed-effects model fit by {"REML" if self.reml else "ML"}', '', 'Model information:',
                 f'    Number of observations          {self.n:>8d}', f'    Fixed effects coefficients      {self.p:>8d}',
                 f'    Random effects coefficients     {q:>8d}', f'    Covariance parameters           {self.ncov + 1:>8d}', '',
                 'Formula:', f'    {self.formula}', '', 'Model fit statistics:',
                 f'    {"AIC":>10}    {"BIC":>10}    {"LogLikelihood":>14}    {"Deviance":>10}',
                 f'    {_fmt(self.aic):>10}    {_fmt(self.bic):>10}    {_fmt(self.loglik):>14}    {_fmt(self.dev):>10}', '',
                 'Fixed effects coefficients (95% CIs):']
        t, pv, lo, hi = self.coef_rows()
        w = max(12, max(len(s) for s in self.xnames) + 4)
        lines.append(f'    {"Name":<{w}}{"Estimate":>12}{"SE":>12}{"tStat":>12}{"DF":>8}{"pValue":>14}{"Lower":>12}{"Upper":>12}')
        for i, nm in enumerate(self.xnames):
            lines.append(f"    {repr(nm):<{w}}{_fmt(self.beta[i]):>12}{_fmt(self.se[i]):>12}{_fmt(t[i]):>12}{self.dfe:>8d}{_fmt(pv[i]):>14}{_fmt(lo[i]):>12}{_fmt(hi[i]):>12}")
        lines += ['', 'Random effects covariance parameters:']
        for k, rt in enumerate(self.rterms):
            lines.append(f'Group: {rt.gname} ({rt.L} Levels)')
            lines.append(f'    {"Name1":<18}{"Name2":<18}{"Type":<10}{"Estimate":>12}')
            for a, b2, ty, est in self.cov_rows(k):
                lines.append(f"    {repr(a):<18}{repr(b2):<18}{repr(ty):<10}{_fmt(est):>12}")
            lines.append('')
        lines += ['Group: Error', f'    {"Name":<18}{"Estimate":>12}', f"    {repr('Res Std'):<18}{_fmt(math.sqrt(self.sigma2)):>12}"]
        return lines


@bi('fitlme', arr=False)
def fitlme(nargout, *args):
    """lme = fitlme(tbl, formula, 'FitMethod', 'ML'): a linear mixed-effects model: 'y ~ x1 + x2 + (1 | g)', '(1 + x | g)' (correlated random intercept and slope), '(1 | g1:g2)' (nested groups), each random term's covariance full; by maximum likelihood ('ML', the default) or restricted maximum likelihood ('REML'), the likelihood profiled over the fixed effects and the residual variance and maximized over the relative covariance factors."""
    nargchk(args, 2, 6, 'fitlme')
    from .tables import Table
    from .regression import _data_from
    if not isinstance(args[0], Table):
        raise err('stats:fitlme:table', 'fitlme takes a table and a formula.', 'fitlme')
    o = _pairs(list(args[2:]), 'fitlme', ('fitmethod', 'dfmethod', 'covariancepattern', 'optimizer', 'checkhessian'))
    method = py_str(o['fitmethod']).upper() if 'fitmethod' in o else 'ML'
    if method not in ('ML', 'REML'):
        raise err('stats:fitlme:FitMethod', "FitMethod is 'ML' or 'REML'.", 'fitlme')
    data, _ = _data_from([args[0]], 'fitlme', {})
    formula = py_str(args[1])
    fixed, rterms, resp = _lme_parse(data, formula, 'fitlme')
    X, xnames, _ = fixed.matrix(data.cols)
    y = np.asarray(data.cols[resp], float)
    ok = np.isfinite(y) & np.all(np.isfinite(X), axis=1) & np.all([np.all(np.isfinite(t.Z), axis=1) for t in rterms], axis=0)
    if not ok.all():
        X, y = X[ok], y[ok]
        for t in rterms:
            t.Z, t.codes = t.Z[ok], t.codes[ok]
    text = f"{resp} ~ " + ' + '.join([('1' if fixed.intercept else '-1')] + [n for n in xnames if n != '(Intercept)']) + ''.join(
        f" + ({' + '.join(t.names).replace('(Intercept)', '1')} | {t.gname})" for t in rterms)
    return LinearMixedModel(data, fixed, rterms, X, xnames, y, method == 'REML', text)


def _lme(v, fn):
    if not isinstance(v, LinearMixedModel):
        raise err(f'stats:{fn}:model', f'{fn} takes a linear mixed-effects model (fitlme).', fn)
    return v


@bi('fixedEffects', nout=3, arr=False)
def fixedEffects(nargout, *args):
    """[beta, betanames, stats] = fixedEffects(lme): the fixed-effects estimates, their names (a table) and the coefficient table."""
    nargchk(args, 1, 5, 'fixedEffects')
    m = _lme(args[0], 'fixedEffects')
    from .tables import Table
    names = Table([Cell.of_list([Char.of(s) for s in m.xnames], (m.p, 1))], ['Name'])
    return _outs(nargout, _col(m.beta), names, m.coef_table())


@bi('randomEffects', nout=3, arr=False)
def randomEffects(nargout, *args):
    """[B, Bnames, stats] = randomEffects(lme): the predicted random effects (conditional modes), each grouping term's levels in turn, each level's effects in turn; Bnames a table of Group, Level and Name."""
    nargchk(args, 1, 5, 'randomEffects')
    m = _lme(args[0], 'randomEffects')
    from .tables import Table
    G, Lv, Nm = [], [], []
    for t in m.rterms:
        for lev in t.levels:
            for nm in t.names:
                G.append(t.gname)
                Lv.append(lev)
                Nm.append(nm)
    cell = lambda xs: Cell.of_list([Char.of(s) for s in xs], (len(xs), 1))  # noqa: E731
    names = Table([cell(G), cell(Lv), cell(Nm)], ['Group', 'Level', 'Name'])
    if nargout > 2:
        # the conditional variances of the effects: sigma^2 * Lambda (Lambda' Z' Z Lambda + I)^-1 Lambda', the fixed effects held at their estimates
        Lam = _Lambda(m.Ts, m.rterms)
        ZL = m.Z @ Lam
        V = m.sigma2 * Lam @ np.linalg.inv(ZL.T @ ZL + np.eye(ZL.shape[1])) @ Lam.T
        se = np.sqrt(np.maximum(np.diag(V), 0))
        st = _st()
        with np.errstate(all='ignore'):
            t = m.b / se
        pv = 2 * st.t.sf(np.abs(t), m.dfe)
        h = st.t.ppf(0.975, m.dfe) * se
        stats = Table([cell(G), cell(Lv), cell(Nm), _col(m.b), _col(se), _col(t), _col(np.full(m.b.size, float(m.dfe))), _col(pv), _col(m.b - h), _col(m.b + h)],
                      ['Group', 'Level', 'Name', 'Estimate', 'SEPred', 'tStat', 'DF', 'pValue', 'Lower', 'Upper'])
        return _col(m.b), names, stats
    return _outs(nargout, _col(m.b), names)


@bi('covarianceParameters', nout=3, arr=False)
def covarianceParameters(nargout, *args):
    """[psi, mse, stats] = covarianceParameters(lme): each random term's covariance matrix (a cell), the residual variance, and for each term a struct of its rows (Name1, Name2, Type, Estimate: standard deviations and correlations)."""
    nargchk(args, 1, 3, 'covarianceParameters')
    m = _lme(args[0], 'covarianceParameters')
    psi = Cell.of_list([out(m.sigma2 * T @ T.T) for T in m.Ts], (len(m.Ts), 1))
    stats = []
    for k, t in enumerate(m.rterms):
        rows = m.cov_rows(k)
        stats.append(Struct.scalar({'Group': Char.of(t.gname), 'Name1': Cell.of_list([Char.of(r[0]) for r in rows], (len(rows), 1)),
                                    'Name2': Cell.of_list([Char.of(r[1]) for r in rows], (len(rows), 1)),
                                    'Type': Cell.of_list([Char.of(r[2]) for r in rows], (len(rows), 1)), 'Estimate': _col([r[3] for r in rows])}))
    stats.append(Struct.scalar({'Group': Char.of('Error'), 'Name': Char.of('Res Std'), 'Estimate': math.sqrt(m.sigma2)}))
    return _outs(nargout, psi, m.sigma2, Cell.of_list(stats, (len(stats), 1)))


def _conditional(rest):
    o = {py_str(rest[i]).lower(): rest[i + 1] for i in range(0, len(rest) - 1, 2) if is_str(rest[i])}
    c = o.get('conditional')
    return True if c is None else bool(np.asarray(darr(c)).reshape(-1)[0]), o


def _lme_predict(nargout, m, *rest):
    from .tables import Table
    rest = list(rest)
    new = rest.pop(0) if rest and isinstance(rest[0], Table) else None
    cond, _ = _conditional(rest)
    if new is None:
        return _col(m.fitted_c if cond else m.fitted_m)
    from .regression import _data_from
    d2, _ = _data_from([new], 'predict', {})
    cols = dict(d2.cols)
    for nm, c in m.data.cols.items():
        if isinstance(c, tuple) and nm in cols and isinstance(cols[nm], tuple):
            # categories of the new data mapped onto the fit's
            codes, lv = cols[nm]
            cols[nm] = (np.array([c[1].index(lv[i]) if lv[i] in c[1] else 0 for i in codes]), c[1])
    X, _, _ = m.fixed.matrix(cols)
    yhat = X @ m.beta
    if cond:
        off = 0
        for t in m.rterms:
            Zt_cols = _term_columns(m, t, cols, X.shape[0])
            keys = _new_codes(d2, t)
            for i, key in enumerate(keys):
                if key in t.levels:
                    li = t.levels.index(key)
                    yhat[i] += Zt_cols[i] @ m.b[off + li * t.q: off + (li + 1) * t.q]
            off += t.L * t.q
    return _col(yhat)


def _term_columns(m, t, cols, n):
    """A random term's columns for new data: its effects' names read as the fixed design reads them."""
    out_ = np.zeros((n, t.q))
    for j, nm in enumerate(t.names):
        if nm == '(Intercept)':
            out_[:, j] = 1.0
            continue
        v = np.ones(n)
        for part in nm.split(':'):
            mm = re.fullmatch(r'([A-Za-z]\w*)(?:\^(\d+))?', part)
            if mm and mm.group(1) in cols and not isinstance(cols[mm.group(1)], tuple):
                v = v * np.asarray(cols[mm.group(1)], float) ** int(mm.group(2) or 1)
            elif '_' in part and part.split('_', 1)[0] in cols and isinstance(cols[part.split('_', 1)[0]], tuple):
                var, lev = part.split('_', 1)
                codes, lv = cols[var]
                v = v * np.array([lv[c] == lev for c in codes], float)
        out_[:, j] = v
    return out_


def _new_codes(d2, t):
    parts = t.gname.split(':')
    keys = []
    for v in parts:
        c = d2.cols[v]
        keys.append([c[1][i] for i in c[0]] if isinstance(c, tuple) else [f'{x:g}' for x in c])
    return [' '.join(r) for r in zip(*keys)]


_wrap('predict', lambda v: isinstance(v, LinearMixedModel), _lme_predict)


@bi('fitted', arr=False)
def fitted(nargout, *args):
    """yfit = fitted(lme, 'Conditional', true): the fitted values, with the predicted random effects (conditional) or without them (marginal)."""
    nargchk(args, 1, 3, 'fitted')
    m = _lme(args[0], 'fitted')
    cond, _ = _conditional(list(args[1:]))
    return _col(m.fitted_c if cond else m.fitted_m)


@bi('residuals', arr=False)
def residuals(nargout, *args):
    """r = residuals(lme, 'Conditional', true, 'ResidualType', 'Raw'): the response less the fitted values ('Pearson': divided by the residual standard deviation)."""
    nargchk(args, 1, 5, 'residuals')
    m = _lme(args[0], 'residuals')
    cond, o = _conditional(list(args[1:]))
    r = m.y - (m.fitted_c if cond else m.fitted_m)
    kind = py_str(o['residualtype']).lower() if 'residualtype' in o else 'raw'
    if kind == 'pearson':
        r = r / math.sqrt(m.sigma2)
    elif kind != 'raw':
        raise err('stats:residuals:type', "ResidualType is 'Raw' or 'Pearson' here.", 'residuals')
    return _col(r)


@bi('response', arr=False)
def response(nargout, *args):
    """y = response(lme): the response the model was fitted to."""
    nargchk(args, 1, 1, 'response')
    return _col(_lme(args[0], 'response').y)


# ---- D-optimal designs by coordinate exchange ------------------------------------------------------------------------------------------

def _model_cols(D, model, fixed=None):
    from .statsmore import _model_matrix
    full = D if fixed is None else np.hstack([D, fixed])
    return _model_matrix(full, model)


def _logdet(F):
    s, v = np.linalg.slogdet(F.T @ F)
    return v if s > 0 else -np.inf


def _coord_exchange(n, nf, model, tries, maxiter, fixed_rows=None, cov=None, levels=None):
    """nf-factor runs (n of them, after fixed_rows) on the levels, each coordinate in turn set to the level giving the largest det(X'X)."""
    rs = _rs()
    lv = levels if levels is not None else np.array([-1.0, 0.0, 1.0] if model in ('quadratic', 'purequadratic') else [-1.0, 1.0])
    best = None
    grid = None
    if lv.size ** nf <= 4096:
        import itertools
        grid = np.array(list(itertools.product(lv, repeat=nf)))
    for _ in range(tries):
        # the start: distinct points of the level grid when it is small enough to list, else random levels
        if grid is not None:
            D = grid[rs.choice(grid.shape[0], n, replace=n > grid.shape[0])].copy()
        else:
            D = lv[rs.randint(0, lv.size, (n, nf))]
        for _it in range(maxiter):
            changed = False
            for i in range(n):
                for j in range(nf):
                    cur = D[i, j]
                    vals = []
                    for v in lv:
                        D[i, j] = v
                        full = D if fixed_rows is None else np.vstack([fixed_rows, D])
                        vals.append(_logdet(_model_cols(full, model, cov)))
                    k = int(np.argmax(vals))
                    D[i, j] = lv[k]
                    if lv[k] != cur and vals[k] > vals[list(lv).index(cur)] + 1e-10:
                        changed = True
            if not changed:
                break
        full = D if fixed_rows is None else np.vstack([fixed_rows, D])
        val = _logdet(_model_cols(full, model, cov))
        if best is None or val > best[1]:
            best = (D.copy(), val)
    return best[0]


def _de_opts(rest, fn):
    model = 'linear'
    if rest and is_str(rest[0]) and py_str(rest[0]).lower() in ('linear', 'interaction', 'quadratic', 'purequadratic'):
        model = py_str(rest.pop(0)).lower()
    o = _pairs(rest, fn, ('tries', 'maxiter', 'display', 'bounds', 'levels', 'categorical', 'excludefun', 'init', 'options'))
    return model, _int(o.get('tries', 1.0)), _int(o.get('maxiter', 10.0)), o


@bi('cordexch', nout=2)
def cordexch(nargout, *args):
    """[dCE, X] = cordexch(nfactors, nruns, model, 'tries', k, 'maxiter', m): a D-optimal design by coordinate exchange: from random runs on the levels -1 and 1 (and 0 for a quadratic model), each coordinate in turn set to the level that makes det(X'X) largest, until nothing changes; X its model matrix."""
    nargchk(args, 2, 9, 'cordexch')
    nf, n = _int(args[0]), _int(args[1])
    model, tries, maxit, _ = _de_opts(list(args[2:]), 'cordexch')
    D = _coord_exchange(n, nf, model, tries, maxit)
    return _outs(nargout, out(D), out(_model_cols(D, model)))


@bi('daugment', nout=2)
def daugment(nargout, *args):
    """[dCE2, X] = daugment(startdes, nruns, model, ...): startdes with nruns more runs chosen by coordinate exchange to make the whole design D-optimal."""
    nargchk(args, 2, 9, 'daugment')
    S = np.asarray(darr(args[0]), float)
    n = _int(args[1])
    model, tries, maxit, _ = _de_opts(list(args[2:]), 'daugment')
    D = _coord_exchange(n, S.shape[1], model, tries, maxit, fixed_rows=S)
    full = np.vstack([S, D])
    return _outs(nargout, out(full), out(_model_cols(full, model)))


@bi('dcovary', nout=2)
def dcovary(nargout, *args):
    """[dCV, X] = dcovary(nfactors, covariates, model, ...): a D-optimal design for the factors with the covariates fixed (a run for each row of covariates), by coordinate exchange; dCV holds the factors then the covariates."""
    nargchk(args, 2, 9, 'dcovary')
    nf = _int(args[0])
    Cv = np.asarray(darr(args[1]), float)
    Cv = Cv.reshape(-1, 1) if Cv.ndim == 1 else Cv
    model, tries, maxit, _ = _de_opts(list(args[2:]), 'dcovary')
    D = _coord_exchange(Cv.shape[0], nf, model, tries, maxit, cov=Cv)
    full = np.hstack([D, Cv])
    return _outs(nargout, out(full), out(_model_cols(D, model, Cv)))


# ---- quasi-random streams ----------------------------------------------------------------------------------------------------------------

class QRandStream(Obj):
    cls = 'qrandstream'
    is_handle = True

    def __init__(self, pset):
        self.pset = pset
        self.state = 0

    def getprop(self, name):
        k = name.lower()
        if k == 'pointset':
            return self.pset
        if k == 'state':
            return float(self.state + 1)
        if k in ('qrand', 'reset'):
            from .classdef import BoundBuiltin
            return BoundBuiltin(self, name)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'qrandstream'.")

    def setprop(self, name, value):
        if name.lower() == 'state':
            self.state = _int(value) - 1
            return
        raise MError('MATLAB:class:SetProhibited', f"You cannot set the '{name}' property of qrandstream.")

    def propnames(self):
        return ['PointSet', 'State']

    def display_lines(self):
        return ['  Quasi-random stream in ' + str(self.pset.d) + ' dimensions', '  Sequence: ' + self.pset.cls, f'  State: {self.state + 1}']


@bi('qrandstream', arr=False)
def qrandstream(nargout, *args):
    """q = qrandstream(type, d, prop, val, ...), qrandstream(p): a stream of points from a quasi-random set ('sobol' or 'halton', d dimensions, the set's properties), read in order by qrand(q, n) and started over by reset(q)."""
    nargchk(args, 1, 12, 'qrandstream')
    from .gsa import PointSet
    if isinstance(args[0], PointSet):
        return QRandStream(args[0])
    kind = py_str(args[0]).lower()
    if kind not in ('sobol', 'halton'):
        raise err('stats:qrandstream:type', "The type is 'sobol' or 'halton'.", 'qrandstream')
    p = REG['sobolset' if kind == 'sobol' else 'haltonset'].fn(1, *args[1:])
    return QRandStream(p)


@bi('qrand')
def qrand(nargout, *args):
    """x = qrand(q), qrand(q, n): the next n (1) points of a quasi-random stream, a row each."""
    nargchk(args, 1, 2, 'qrand')
    q = args[0]
    if not isinstance(q, QRandStream):
        raise err('stats:qrand:stream', 'qrand takes a qrandstream.', 'qrand')
    n = _int(args[1]) if len(args) > 1 else 1
    P = q.pset.points(np.arange(q.state, q.state + n))
    q.state += n
    return out(P)


def _reset(nargout, *args):
    args[0].state = 0
    return None


if 'reset' in REG:
    _wrap('reset', lambda v: isinstance(v, QRandStream), _reset)
else:
    @bi('reset', arr=False)
    def reset(nargout, *args):
        """reset(q): a quasi-random stream started over from its first point."""
        nargchk(args, 1, 1, 'reset')
        if not isinstance(args[0], QRandStream):
            raise err('MATLAB:reset:input', 'reset takes a qrandstream here.', 'reset')
        return _reset(nargout, *args)

