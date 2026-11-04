"""More statistics: lasso and elastic net, stepwise regression
(stepwiselm), n-way ANOVA (anovan), MANOVA (manova1), bootstrap
confidence intervals (bootci), the Ansari-Bradley test, copulas
(copularnd, copulapdf, copulacdf, copulastat, copulaparam, copulafit),
designs of experiments (fullfact, ff2n, fracfact, bbdesign, ccdesign,
candgen, candexch, rowexch), hidden Markov models (hmmgenerate,
hmmviterbi, hmmdecode, hmmtrain, hmmestimate), Cox regression (coxphfit),
feature selection (relieff, fscchi2, fscmrmr, sequentialfs) and two plots
of many variables (andrewsplot, parallelcoords) and probplot."""
import itertools
import math

import numpy as np

from . import bi as _register
from ._util import err, nargchk, num, is_str, darr, out
from ..values import MError, FH, Char, Cell, Struct, numel, py_str, text_list
from .. import runtime as R


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, np.linalg.LinAlgError) as e:
                raise err(f'stats:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _rs():
    from .elmat import RNG
    return RNG.rs


def _st():
    import scipy.stats as st
    return st


def _int(v):
    return int(round(float(num(v))))


_MAX_RUNS = 2 ** 20


def _count(v, fn, what='number of factors', lo=1):
    """A whole number of at least lo from a numeric argument (not text)."""
    if is_str(v):
        raise err(f'stats:{fn}:{what.split()[-1]}', f'The {what} must be a number, not text.', fn)
    k = _int(v)
    if k < lo or k != float(num(v)):
        raise err(f'stats:{fn}:{what.split()[-1]}', f'The {what} must be a whole number of at least {lo}.', fn)
    return k


def _runs_ok(nruns, fn):
    if nruns > _MAX_RUNS:
        raise err(f'stats:{fn}:size', f'The design would have {nruns:.4g} runs; at most {_MAX_RUNS} are made.', fn)


def _binary(n, signs=False):
    """Every row of n bits, counting in binary (the last column fastest); -1 and 1 when signs."""
    B = ((np.arange(2 ** n)[:, None] >> np.arange(n - 1, -1, -1)) & 1).astype(float)
    return 2 * B - 1 if signs else B


def _flag(v):
    if is_str(v):
        return py_str(v).lower() in ('on', 'true', 'yes')
    return bool(np.all(darr(v)))


def _pairs(args, fn, names):
    if len(args) % 2:
        raise err(f'stats:{fn}:pairs', f'The options of {fn} come as names and values.', fn)
    o = {}
    for i in range(0, len(args), 2):
        k = py_str(args[i]).lower()
        if names is not None and k not in names:
            raise err(f'stats:{fn}:option', f"'{py_str(args[i])}' is not an option of {fn}.", fn)
        o[k] = args[i + 1]
    return o


def _mat(v, fn, what='X'):
    a = np.asarray(darr(v), float)
    if a.ndim != 2:
        raise err(f'stats:{fn}:matrix', f'{what} is a matrix.', fn)
    return a


def _vec(v):
    return np.asarray(darr(v), float).reshape(-1)


def _statset(o, defaults):
    d = dict(defaults)
    s = o.get('options')
    if isinstance(s, Struct) and s.size == 1:
        for k, v in s.elem(0).items():
            if numel(v):
                d[k.lower()] = v
    return d


# ---- lasso and elastic net --------------------------------------------------------------------------------------------------------------

def _enet_path(Xs, yc, lambdas, alpha, maxit, tol, w=None):
    """Coordinate descent for 1/(2N) sum w (y - X b)^2 + lambda (alpha |b|_1 + (1 - alpha)/2 |b|^2), warm started along the
    path (lambda decreasing). Xs and yc are centred."""
    n, p = Xs.shape
    w = np.ones(n) / n if w is None else w / w.sum()
    xx = (w[:, None] * Xs ** 2).sum(0)
    b = np.zeros(p)
    r = yc.copy()
    B = np.zeros((p, len(lambdas)))
    for k, lam in enumerate(lambdas):
        for _ in range(maxit):
            maxd = 0.0
            for j in range(p):
                if xx[j] == 0:
                    continue
                old = b[j]
                rho = np.sum(w * Xs[:, j] * r) + xx[j] * old
                # (the threshold a hair wide, so that the largest lambda gives the empty model exactly)
                new = np.sign(rho) * max(abs(rho) - lam * alpha * (1 + 1e-12), 0) / (xx[j] + lam * (1 - alpha))
                if new != old:
                    r -= Xs[:, j] * (new - old)
                    b[j] = new
                    maxd = max(maxd, abs(new - old) * math.sqrt(xx[j]))
            if maxd < tol * max(1e-12, math.sqrt(np.sum(w * yc ** 2))):
                break
        B[:, k] = b
    return B


@bi('lasso', nout=2)
def lasso(nargout, *args):
    """[B, FitInfo] = lasso(X, y), lasso(..., 'Alpha', a, 'Lambda', l, 'NumLambda', n, 'LambdaRatio', r, 'CV', k, 'Standardize', tf, 'Weights', w, 'MaxIter', m, 'RelTol', t, 'DFmax', d): lasso (alpha 1) or elastic net regression for a path of penalties."""
    nargchk(args, 2, 30, 'lasso')
    X = _mat(args[0], 'lasso')
    y = _vec(args[1])
    if y.size != X.shape[0]:
        raise err('stats:lasso:size', 'X and y have as many rows.', 'lasso')
    o = _pairs(args[2:], 'lasso', ('alpha', 'lambda', 'numlambda', 'lambdaratio', 'cv', 'standardize', 'weights', 'maxiter', 'reltol', 'dfmax',
                                   'mcreps', 'predictornames', 'options', 'intercept', 'absTol'.lower(), 'b0', 'rho', 'u0'))
    keep = np.isfinite(y) & ~np.any(np.isnan(X), axis=1)
    X, y = X[keep], y[keep]
    n, p = X.shape
    alpha = float(num(o.get('alpha', 1.0)))
    if not 0 < alpha <= 1:
        raise err('stats:lasso:alpha', 'Alpha is in (0, 1].', 'lasso')
    w = _vec(o['weights'])[keep] if 'weights' in o else np.ones(n)
    wn = w / w.sum()
    std = _flag(o['standardize']) if 'standardize' in o else True
    mu = wn @ X
    yb = wn @ y
    Xc = X - mu
    sd = np.sqrt(wn @ Xc ** 2) if std else np.ones(p)
    sd = np.where(sd > 0, sd, 1)
    Xs = Xc / sd
    yc = y - yb
    if 'lambda' in o:
        lambdas = np.sort(_vec(o['lambda']))[::-1]
    else:
        lmax = np.max(np.abs(Xs.T @ (wn * yc))) / alpha
        nl = _int(o.get('numlambda', 100.0))
        ratio = float(num(o.get('lambdaratio', 1e-4)))
        lambdas = lmax * ratio ** (np.arange(nl) / max(nl - 1, 1)) if nl > 1 else np.array([lmax])
    maxit = _int(o.get('maxiter', 1e5))
    tol = float(num(o.get('reltol', 1e-4)))
    Bs = _enet_path(Xs, yc, lambdas, alpha, min(maxit, 100000), tol, w)
    B = Bs / sd[:, None]
    b0 = yb - mu @ B
    dfmax = o.get('dfmax')
    order = np.arange(len(lambdas))[::-1]           # lambda ascending, as the columns are given
    B, b0, lambdas = B[:, order], b0[order], lambdas[order]
    df = np.sum(B != 0, axis=0)
    if dfmax is not None:
        ok = df <= float(num(dfmax))
        B, b0, lambdas, df = B[:, ok], b0[ok], lambdas[ok], df[ok]
    mse = np.array([np.sum(wn * (y - b0[k] - X @ B[:, k]) ** 2) for k in range(len(lambdas))])
    info = {'Intercept': out(b0.reshape(1, -1)), 'Lambda': out(lambdas.reshape(1, -1)), 'Alpha': alpha, 'DF': out(df.reshape(1, -1).astype(float)),
            'MSE': out(mse.reshape(1, -1)), 'PredictorNames': Cell.empty((1, 0)), 'UseCovariance': False}
    if 'cv' in o:
        cv = o['cv']
        if is_str(cv) and py_str(cv).lower() == 'resubstitution':
            folds = None
        else:
            from .mlmodels import CVPartition
            c = cv if isinstance(cv, CVPartition) else CVPartition(n, 'kfold', k=_int(cv))
            folds = c
        if folds is not None:
            errs = np.zeros((folds.nsets, len(lambdas)))
            sizes = np.zeros(folds.nsets)
            for f in range(folds.nsets):
                tr, te = folds.train_mask(f), folds.test_mask(f)
                wt = w[tr] / w[tr].sum()
                mu_f = wt @ X[tr]
                yb_f = wt @ y[tr]
                sd_f = np.sqrt(wt @ (X[tr] - mu_f) ** 2) if std else np.ones(p)
                sd_f = np.where(sd_f > 0, sd_f, 1)
                Bf = _enet_path((X[tr] - mu_f) / sd_f, y[tr] - yb_f, lambdas[::-1], alpha, min(maxit, 100000), tol, w[tr])[:, ::-1] / sd_f[:, None]
                b0f = yb_f - mu_f @ Bf
                pred = b0f[None, :] + X[te] @ Bf
                errs[f] = np.average((y[te, None] - pred) ** 2, axis=0, weights=w[te])
                sizes[f] = te.sum()
            mse = errs.mean(0)
            se = errs.std(0, ddof=1) / math.sqrt(folds.nsets) if folds.nsets > 1 else np.zeros_like(mse)
            imin = int(np.argmin(mse))
            within = np.flatnonzero(mse <= mse[imin] + se[imin])
            i1 = int(within.max())
            info.update({'MSE': out(mse.reshape(1, -1)), 'SE': out(se.reshape(1, -1)), 'LambdaMinMSE': float(lambdas[imin]), 'Lambda1SE': float(lambdas[i1]),
                         'IndexMinMSE': float(imin + 1), 'Index1SE': float(i1 + 1)})
    res = (out(B), Struct.scalar(info))
    return res if nargout > 1 else res[0]


# ---- stepwise regression -------------------------------------------------------------------------------------------------------------------

def _term_text(t):
    return ':'.join(f'x{j + 1}' for j in t)


@bi('stepwiselm')
def stepwiselm(nargout, *args):
    """mdl = stepwiselm(X, y), stepwiselm(X, y, modelspec, 'Upper', spec, 'Lower', spec, 'PEnter', pe, 'PRemove', pr, 'Verbose', v): a linear model whose terms are added and removed one at a time by their F tests."""
    nargchk(args, 2, 20, 'stepwiselm')
    from .tables import Table
    if isinstance(args[0], Table):
        raise err('stats:stepwiselm:table', 'stepwiselm takes X and y here: table2array(T(:, predictors)) and the response.', 'stepwiselm')
    X = _mat(args[0], 'stepwiselm')
    y = _vec(args[1])
    rest = list(args[2:])
    start = 'constant'
    if rest and is_str(rest[0]) and len(rest) % 2 == 1:
        start = py_str(rest.pop(0)).lower()
    o = _pairs(rest, 'stepwiselm', ('upper', 'lower', 'penter', 'premove', 'verbose', 'criterion', 'nsteps', 'predictorvars', 'responsevar', 'varnames'))
    p = X.shape[1]
    singles = [(j,) for j in range(p)]
    pairs_ = [(i, j) for i in range(p) for j in range(i + 1, p)]

    def spec_terms(s):
        s = s.lower()
        if s == 'constant':
            return []
        if s == 'linear':
            return singles
        if s == 'interactions':
            return singles + pairs_
        raise err('stats:stepwiselm:modelspec', "The models named here are 'constant', 'linear' and 'interactions'.", 'stepwiselm')
    upper = spec_terms(py_str(o.get('upper', Char.of('interactions'))))
    lower = spec_terms(py_str(o.get('lower', Char.of('constant'))))
    current = list(dict.fromkeys(spec_terms(start) + lower))
    pe = float(num(o.get('penter', 0.05)))
    pr = float(num(o.get('premove', 0.10)))
    verbose = _int(o.get('verbose', 1.0))
    nsteps = _int(o['nsteps']) if 'nsteps' in o else 10 ** 6
    st = _st()

    def fit(terms):
        cols = [np.ones(X.shape[0])] + [np.prod(X[:, list(t)], axis=1) for t in terms]
        A = np.column_stack(cols)
        b, *_ = np.linalg.lstsq(A, y, rcond=None)
        r = y - A @ b
        return float(r @ r), A.shape[1]

    def ftest(small, big):
        s0, k0 = fit(small)
        s1, k1 = fit(big)
        dfe = X.shape[0] - k1
        if dfe <= 0 or s1 <= 0:
            return np.inf, 0.0
        F = (s0 - s1) / (k1 - k0) / (s1 / dfe)
        return F, float(st.f.sf(F, k1 - k0, dfe))

    def allowed(t, terms):
        return len(t) == 1 or all((j,) in terms for j in t)
    step = 0
    while step < nsteps:
        cands = [t for t in upper if t not in current and allowed(t, current)]
        best = None
        for t in cands:
            F, pv = ftest(current, current + [t])
            if pv < pe and (best is None or pv < best[2]):
                best = (t, F, pv)
        if best is not None:
            current.append(best[0])
            step += 1
            if verbose:
                R.write(f'{step}. Adding {_term_text(best[0])}, FStat = {best[1]:.5g}, pValue = {best[2]:.5g}\n')
            continue
        worst = None
        for t in current:
            if t in lower or any(len(u) > len(t) and set(t) <= set(u) for u in current):
                continue
            F, pv = ftest([u for u in current if u != t], current)
            if pv > pr and (worst is None or pv > worst[2]):
                worst = (t, F, pv)
        if worst is not None:
            current.remove(worst[0])
            step += 1
            if verbose:
                R.write(f'{step}. Removing {_term_text(worst[0])}, FStat = {worst[1]:.5g}, pValue = {worst[2]:.5g}\n')
            continue
        break
    terms = sorted(current, key=lambda t: (len(t), t))
    formula = 'y ~ ' + (' + '.join(['1'] + [_term_text(t) for t in terms]))
    return R._builtin('fitlm', out(X), out(y.reshape(-1, 1)), Char.of(formula))


# ---- n-way ANOVA and MANOVA ------------------------------------------------------------------------------------------------------------

def _factor(g, n, fn):
    from .statdesc import groups
    labels, idx = groups(g, n, fn)
    return labels, idx


def _effects(idx, L):
    """Sum-to-zero (effect) coding of a factor: L - 1 columns."""
    n = idx.size
    M = np.zeros((n, max(L - 1, 0)))
    for j in range(L - 1):
        M[idx == j, j] = 1
    M[idx == L - 1, :] = -1
    return M


@bi('anovan', nout=4)
def anovan(nargout, *args):
    """[p, tbl, stats, terms] = anovan(y, group), anovan(..., 'model', 'linear'|'interaction'|'full'|k|termsMatrix, 'sstype', 1|2|3, 'varnames', names, 'display', 'on'|'off'): n-way analysis of variance."""
    nargchk(args, 2, 14, 'anovan')
    from .stattests import _table, _show_table
    y = _vec(args[0])
    n = y.size
    g = args[1]
    factors = [g.a.reshape(-1, order='F')[i] for i in range(g.a.size)] if isinstance(g, Cell) and not all(isinstance(x, Char) for x in g.a.reshape(-1)) else None
    if factors is None:
        G = np.asarray(darr(g), float)
        factors = [out(G[:, j].reshape(-1, 1)) for j in range(G.shape[1])] if G.ndim == 2 and G.shape[0] == n else [g]
    o = _pairs(args[2:], 'anovan', ('model', 'sstype', 'varnames', 'display', 'alpha', 'random', 'continuous', 'nested'))
    k = len(factors)
    parts = [_factor(f, n, 'anovan') for f in factors]
    names = [str(s) for s in text_list(o['varnames'])] if 'varnames' in o else [f'X{i + 1}' for i in range(k)]
    model = o.get('model', Char.of('linear'))
    if is_str(model):
        mname = py_str(model).lower()
        order = {'linear': 1, 'interaction': 2, 'full': k}.get(mname)
        if order is None:
            raise err('stats:anovan:model', "model is 'linear', 'interaction', 'full', an order or a terms matrix.", 'anovan')
        terms = [t for r in range(1, order + 1) for t in itertools.combinations(range(k), r)]
    elif numel(model) == 1:
        terms = [t for r in range(1, _int(model) + 1) for t in itertools.combinations(range(k), r)]
    else:
        T = np.asarray(darr(model), float)
        terms = [tuple(int(j) for j in np.flatnonzero(row)) for row in T]
    sstype = _int(o.get('sstype', 3.0))
    keep = np.isfinite(y) & np.all([p_[1] >= 0 for p_ in parts], axis=0)
    y = y[keep]
    idxs = [p_[1][keep] for p_ in parts]
    Ls = [len(p_[0]) for p_ in parts]
    codes = [_effects(idxs[i], Ls[i]) for i in range(k)]

    def term_cols(t):
        cols = codes[t[0]]
        for j in t[1:]:
            cols = np.einsum('ni,nj->nij', cols, codes[j]).reshape(cols.shape[0], -1)
        return cols
    TC = {t: term_cols(t) for t in terms}
    ones = np.ones((y.size, 1))

    def sse(ts):
        A = np.column_stack([ones] + [TC[t] for t in ts])
        b, *_ = np.linalg.lstsq(A, y, rcond=None)
        r = y - A @ b
        return float(r @ r), int(np.linalg.matrix_rank(A))
    full_sse, full_rank = sse(terms)
    dfe = y.size - full_rank
    mse = full_sse / dfe if dfe > 0 else np.nan
    rows = [['Source', 'Sum Sq.', 'd.f.', 'Singular?', 'Mean Sq.', 'F', 'Prob>F']]
    pvals = []
    for i, t in enumerate(terms):
        if sstype == 1:
            s_with, r_with = sse(terms[:i + 1])
            s_wo, r_wo = sse(terms[:i])
        elif sstype == 2:
            others = [u for u in terms if u != t and not set(t) <= set(u)]
            s_with, r_with = sse(others + [t])
            s_wo, r_wo = sse(others)
        else:
            s_with, r_with = full_sse, full_rank
            s_wo, r_wo = sse([u for u in terms if u != t])
        ss = s_wo - s_with
        df = r_with - r_wo
        ms = ss / df if df > 0 else np.nan
        F = ms / mse if df > 0 and mse > 0 else np.nan
        pv = float(_st().f.sf(F, df, dfe)) if np.isfinite(F) else np.nan
        pvals.append(pv)
        rows.append(['*'.join(names[j] for j in t), ss, df, 0.0, ms, F, pv])
    sst = float(np.sum((y - y.mean()) ** 2))
    rows.append(['Error', full_sse, dfe, 0.0, mse, None, None])
    rows.append(['Total', sst, y.size - 1, 0.0, None, None, None])
    if 'display' not in o or _flag(o['display']):
        _show_table('Analysis of Variance', [r[:3] + r[4:] for r in rows])
    stats = Struct.scalar({'source': Char.of('anovan'), 'dfe': float(dfe), 'mse': float(mse), 'nlevels': out(np.array(Ls, float).reshape(-1, 1)),
                           'varnames': Cell.of_list([Char.of(s) for s in names], (k, 1)), 'sstype': float(sstype)})
    tm = np.zeros((len(terms), k))
    for i, t in enumerate(terms):
        tm[i, list(t)] = 1
    res = (out(np.array(pvals).reshape(-1, 1)), _table(rows), stats, out(tm))
    return res[:nargout] if nargout > 1 else res[0]


@bi('manova1', nout=3)
def manova1(nargout, *args):
    """[d, p, stats] = manova1(X, group), manova1(X, group, alpha): one-way multivariate analysis of variance: the dimension of the space the group means span (as far as the data show), and the tests behind it."""
    nargchk(args, 2, 3, 'manova1')
    X = _mat(args[0], 'manova1')
    labels, idx = _factor(args[1], X.shape[0], 'manova1')
    alpha = float(num(args[2])) if len(args) > 2 else 0.05
    keep = (idx >= 0) & ~np.any(np.isnan(X), axis=1)
    X, idx = X[keep], idx[keep]
    n, p = X.shape
    g = len(labels)
    mu = X.mean(0)
    T = (X - mu).T @ (X - mu)
    W = np.zeros((p, p))
    for c in range(g):
        Xc = X[idx == c]
        W += (Xc - Xc.mean(0)).T @ (Xc - Xc.mean(0))
    B = T - W
    from scipy.linalg import eigh
    vals, vecs = eigh(B, W)
    order = np.argsort(-vals)
    vals, vecs = np.maximum(vals[order], 0), vecs[:, order]
    dfW, dfB, dfT = n - g, g - 1, n - 1
    m = min(p, dfB)
    lam = np.array([np.prod(1 / (1 + vals[j:m])) for j in range(m)])
    chisq = -(dfT - (p + g) / 2) * np.log(lam)
    chisqdf = np.array([(p - j) * (dfB - j) for j in range(m)], float)
    pv = _st().chi2.sf(chisq, chisqdf)
    d = int(np.sum(np.cumprod(pv < alpha)))
    # canonical variables scaled to unit within-group variance
    vecs = vecs * np.sqrt(dfW / np.maximum(np.sum(vecs * (W @ vecs), 0), 1e-300))
    canon = (X - mu) @ vecs
    S = W / dfW
    Si = np.linalg.pinv(S)
    mdist = np.einsum('ij,jk,ik->i', X - mu, np.linalg.pinv(T / dfT), X - mu)
    gm = np.array([X[idx == c].mean(0) for c in range(g)])
    gmd = np.array([[float((gm[a] - gm[b]) @ Si @ (gm[a] - gm[b])) for b in range(g)] for a in range(g)])
    stats = Struct.scalar({'W': out(W), 'B': out(B), 'T': out(T), 'dfW': float(dfW), 'dfB': float(dfB), 'dfT': float(dfT),
                           'lambda': out(lam.reshape(-1, 1)), 'chisq': out(chisq.reshape(-1, 1)), 'chisqdf': out(chisqdf.reshape(-1, 1)),
                           'eigenval': out(vals.reshape(-1, 1)), 'eigenvec': out(vecs), 'canon': out(canon), 'mdist': out(mdist.reshape(-1, 1)),
                           'gmdist': out(gmd), 'gnames': Cell.of_list([Char.of(s) for s in labels], (g, 1))})
    res = (float(d), out(pv.reshape(-1, 1)), stats)
    return res[:nargout] if nargout > 1 else res[0]


# ---- bootstrap confidence intervals and the Ansari-Bradley test --------------------------------------------------------------------------

@bi('bootci', aw=True, nout=2)
async def bootci(nargout, *args):
    """ci = bootci(nboot, bootfun, d, ...), bootci(nboot, {bootfun, d, ...}, 'Type', t, 'Alpha', a, 'NBootStd', m): a bootstrap confidence interval of bootfun's value: 'bca' (unless given), 'per', 'cper', 'norm' or 'stud'."""
    nargchk(args, 2, 30, 'bootci')
    B = _int(args[0])
    a = list(args[1:])
    if isinstance(a[0], Cell):
        items = list(a[0].a.reshape(-1, order='F'))
        fun, datas = items[0], items[1:]
        rest = a[1:]
    else:
        fun = a[0]
        datas = []
        rest = a[1:]
        while rest and not (is_str(rest[0]) and py_str(rest[0]).lower() in ('type', 'alpha', 'nbootstd', 'stderr', 'weights', 'options')):
            datas.append(rest.pop(0))
    o = _pairs(rest, 'bootci', ('type', 'alpha', 'nbootstd', 'stderr', 'weights', 'options'))
    kind = py_str(o.get('type', Char.of('bca'))).lower()
    kind = {'percentile': 'per', 'corrected percentile': 'cper', 'normal': 'norm', 'student': 'stud'}.get(kind, kind)
    alpha = float(num(o.get('alpha', 0.05)))
    if not isinstance(fun, FH):
        raise err('stats:bootci:fun', 'bootci takes a function handle.', 'bootci')
    ns = {np.asarray(darr(d)).shape[0] if np.ndim(darr(d)) == 2 and np.asarray(darr(d)).shape[0] > 1 else numel(d) for d in datas}
    n = max(ns)

    def take(d, idx):
        arr_ = np.asarray(darr(d), float)
        if arr_.ndim == 2 and arr_.shape[0] == n and arr_.shape[0] > 1:
            return out(arr_[idx])
        if arr_.size == n:
            return out(arr_.reshape(-1)[idx].reshape(-1, 1) if arr_.shape[0] == n else arr_.reshape(-1)[idx].reshape(1, -1))
        return d

    async def stat(idx):
        return np.asarray(darr(await fun.acall(1, *[take(d, idx) for d in datas])), float).reshape(-1)
    rs = _rs()
    allidx = np.arange(n)
    t0 = await stat(allidx)
    boots = np.empty((B, t0.size))
    idxs = []
    for b in range(B):
        idx = rs.randint(0, n, n)
        idxs.append(idx)
        boots[b] = await stat(idx)
    st = _st()
    z = st.norm.ppf
    if kind == 'per':
        lo, hi = np.percentile(boots, [100 * alpha / 2, 100 * (1 - alpha / 2)], axis=0)
    elif kind == 'norm':
        bias = boots.mean(0) - t0
        se = boots.std(0, ddof=1)
        lo, hi = t0 - bias - z(1 - alpha / 2) * se, t0 - bias + z(1 - alpha / 2) * se
    elif kind in ('cper', 'bca'):
        prop = (np.sum(boots < t0, 0) + np.sum(boots == t0, 0) / 2) / B
        z0 = z(np.clip(prop, 1 / (2 * B), 1 - 1 / (2 * B)))
        acc = np.zeros_like(t0)
        if kind == 'bca':
            jack = np.array([await stat(np.delete(allidx, i)) for i in range(n)])
            d_ = jack.mean(0) - jack
            den = 6 * np.sum(d_ ** 2, 0) ** 1.5
            acc = np.where(den > 0, np.sum(d_ ** 3, 0) / np.where(den > 0, den, 1), 0)
        zl, zh = z(alpha / 2), z(1 - alpha / 2)
        pl = st.norm.cdf(z0 + (z0 + zl) / (1 - acc * (z0 + zl)))
        ph = st.norm.cdf(z0 + (z0 + zh) / (1 - acc * (z0 + zh)))
        lo = np.array([np.percentile(boots[:, j], 100 * pl[j]) for j in range(t0.size)])
        hi = np.array([np.percentile(boots[:, j], 100 * ph[j]) for j in range(t0.size)])
    elif kind == 'stud':
        m = _int(o.get('nbootstd', 100.0))

        async def se_of(idx):
            inner = np.array([await stat(idx[rs.randint(0, n, n)]) for _ in range(m)])
            return inner.std(0, ddof=1)
        se0 = await se_of(allidx)
        tstat = np.empty_like(boots)
        for b in range(B):
            tstat[b] = (boots[b] - t0) / np.maximum(await se_of(idxs[b]), 1e-300)
        ql, qh = np.percentile(tstat, [100 * (1 - alpha / 2), 100 * alpha / 2], axis=0)
        lo, hi = t0 - ql * se0, t0 - qh * se0
    else:
        raise err('stats:bootci:type', "Type is 'bca', 'per', 'cper', 'norm' or 'stud'.", 'bootci')
    ci = np.vstack([lo, hi])
    res = (out(ci), out(boots))
    return res if nargout > 1 else res[0]


@bi('ansaribradley', nout=3)
def ansaribradley(nargout, *args):
    """[h, p, stats] = ansaribradley(x, y), ansaribradley(..., 'Alpha', a, 'Tail', 'both'|'right'|'left'): the Ansari-Bradley test that two samples have the same dispersion."""
    nargchk(args, 2, 8, 'ansaribradley')
    x, y = _vec(args[0]), _vec(args[1])
    x, y = x[~np.isnan(x)], y[~np.isnan(y)]
    o = _pairs(args[2:], 'ansaribradley', ('alpha', 'tail', 'exact', 'method'))
    alpha = float(num(o.get('alpha', 0.05)))
    tail = py_str(o.get('tail', Char.of('both'))).lower()
    alt = {'both': 'two-sided', 'right': 'greater', 'left': 'less'}[tail]
    r = _st().ansari(x, y, alternative=alt)
    # the statistic and its normal approximation
    z_all = np.concatenate([x, y])
    N = z_all.size
    ranks = _st().rankdata(z_all)
    scores = np.minimum(ranks, N - ranks + 1)
    W = float(scores[:x.size].sum())
    m = x.size
    if N % 2 == 0:
        mean, var = m * (N + 2) / 4, m * y.size * (N + 2) * (N - 2) / (48 * (N - 1))
    else:
        mean, var = m * (N + 1) ** 2 / (4 * N), m * y.size * (N + 1) * (3 + N ** 2) / (48 * N ** 2)
    stats = Struct.scalar({'W': W, 'Wstar': (W - mean) / math.sqrt(var)})
    res = (float(r.pvalue <= alpha), float(r.pvalue), stats)
    return res[:nargout] if nargout > 1 else res[0]


# ---- copulas ----------------------------------------------------------------------------------------------------------------------------

_ARCH = ('clayton', 'frank', 'gumbel')


def _copula_args(fam, args, fn):
    fam = fam.lower()
    if fam == 'gaussian':
        P = np.asarray(darr(args[0]), float)
        rho = np.array([[1, P.item()], [P.item(), 1]]) if P.size == 1 else P
        return fam, rho, None
    if fam == 't':
        P = np.asarray(darr(args[0]), float)
        rho = np.array([[1, P.item()], [P.item(), 1]]) if P.size == 1 else P
        return fam, rho, float(num(args[1]))
    if fam in _ARCH:
        return fam, float(num(args[0])), None
    raise err(f'stats:{fn}:family', "The family is 'Gaussian', 't', 'Clayton', 'Frank' or 'Gumbel'.", fn)


def _frank_tau(a):
    from scipy.integrate import quad
    if a == 0:
        return 0.0
    D = quad(lambda t: t / np.expm1(t) if t != 0 else 1.0, 0, abs(a))[0] / abs(a)
    tau = 1 - 4 / abs(a) * (1 - D)
    return math.copysign(tau, a)


@bi('copularnd')
def copularnd(nargout, *args):
    """U = copularnd('Gaussian', rho, n), copularnd('t', rho, nu, n), copularnd('Clayton'|'Frank'|'Gumbel', alpha, n): random vectors with uniform marginals tied by a copula."""
    nargchk(args, 3, 4, 'copularnd')
    fam, P, nu = _copula_args(py_str(args[0]), args[1:], 'copularnd')
    n = _int(args[-1])
    rs = _rs()
    st = _st()
    if fam in ('gaussian', 't'):
        L = np.linalg.cholesky(P)
        Z = rs.standard_normal((n, P.shape[0])) @ L.T
        if fam == 'gaussian':
            return out(st.norm.cdf(Z))
        chi = rs.chisquare(nu, n) / nu
        return out(st.t.cdf(Z / np.sqrt(chi)[:, None], nu))
    a = P
    if fam == 'clayton':
        if a <= 0:
            raise err('stats:copularnd:alpha', 'The Clayton copula takes alpha > 0.', 'copularnd')
        V = rs.gamma(1 / a, 1, n)
        E = rs.exponential(1, (n, 2))
        return out((1 + E / V[:, None]) ** (-1 / a))
    if fam == 'gumbel':
        if a < 1:
            raise err('stats:copularnd:alpha', 'The Gumbel copula takes alpha >= 1.', 'copularnd')
        if a == 1:
            return out(rs.random_sample((n, 2)))
        # a positive stable variable (Chambers, Mallows and Stuck), then the Laplace transform
        b = 1 / a
        th = (rs.random_sample(n) - 0.5) * math.pi
        W = rs.exponential(1, n)
        S = np.sin(b * (th + math.pi / 2)) / np.cos(th) ** (1 / b) * (np.cos(th - b * (th + math.pi / 2)) / W) ** ((1 - b) / b)
        S = S * math.cos(math.pi * b / 2) ** (1 / b)
        E = rs.exponential(1, (n, 2))
        return out(np.exp(-(E / S[:, None]) ** b))
    # Frank: the second by inverting the conditional distribution
    u = rs.random_sample(n)
    w = rs.random_sample(n)
    if a == 0:
        return out(np.column_stack([u, w]))
    v = -np.log1p(w * np.expm1(-a) / (w + (1 - w) * np.exp(-a * u))) / a
    return out(np.column_stack([u, v]))


def _copula_pdf(fam, P, nu, U):
    st = _st()
    U = np.clip(U, 1e-12, 1 - 1e-12)
    if fam == 'gaussian':
        Z = st.norm.ppf(U)
        Pi = np.linalg.inv(P)
        return np.exp(-0.5 * np.einsum('ij,jk,ik->i', Z, Pi - np.eye(P.shape[0]), Z)) / math.sqrt(np.linalg.det(P))
    if fam == 't':
        Z = st.t.ppf(U, nu)
        mv = st.multivariate_t(np.zeros(P.shape[0]), P, df=nu).pdf(Z)
        return mv / np.prod(st.t.pdf(Z, nu), axis=1)
    u, v = U[:, 0], U[:, 1]
    a = P
    if fam == 'clayton':
        return (1 + a) * (u * v) ** (-1 - a) * (u ** -a + v ** -a - 1) ** (-2 - 1 / a)
    if fam == 'frank':
        if a == 0:
            return np.ones_like(u)
        e = np.exp(-a)
        num_ = a * (1 - e) * np.exp(-a * (u + v))
        den = ((1 - e) - (1 - np.exp(-a * u)) * (1 - np.exp(-a * v))) ** 2
        return num_ / den
    lu, lv = -np.log(u), -np.log(v)
    A = (lu ** a + lv ** a) ** (1 / a)
    C = np.exp(-A)
    return C / (u * v) * (lu * lv) ** (a - 1) * (lu ** a + lv ** a) ** (2 / a - 2) * (1 + (a - 1) / A)


def _copula_cdf(fam, P, nu, U):
    st = _st()
    u, v = U[:, 0], U[:, 1] if U.shape[1] > 1 else U[:, 0]
    if fam == 'gaussian':
        return st.multivariate_normal(np.zeros(P.shape[0]), P).cdf(st.norm.ppf(np.clip(U, 1e-15, 1 - 1e-15)))
    if fam == 't':
        return st.multivariate_t(np.zeros(P.shape[0]), P, df=nu).cdf(st.t.ppf(np.clip(U, 1e-15, 1 - 1e-15), nu))
    a = P
    if fam == 'clayton':
        return np.maximum(u ** -a + v ** -a - 1, 0) ** (-1 / a)
    if fam == 'frank':
        return -np.log1p(np.expm1(-a * u) * np.expm1(-a * v) / np.expm1(-a)) / a if a != 0 else u * v
    return np.exp(-((-np.log(u)) ** a + (-np.log(v)) ** a) ** (1 / a))


@bi('copulapdf')
def copulapdf(nargout, *args):
    """y = copulapdf(family, U, rho), copulapdf('t', U, rho, nu), copulapdf(family, U, alpha): a copula's density at the rows of U."""
    nargchk(args, 3, 4, 'copulapdf')
    U = _mat(args[1], 'copulapdf', 'U')
    fam, P, nu = _copula_args(py_str(args[0]), args[2:], 'copulapdf')
    return out(np.asarray(_copula_pdf(fam, P, nu, U)).reshape(-1, 1))


@bi('copulacdf')
def copulacdf(nargout, *args):
    """y = copulacdf(family, U, rho), copulacdf('t', U, rho, nu), copulacdf(family, U, alpha): a copula's distribution function at the rows of U."""
    nargchk(args, 3, 4, 'copulacdf')
    U = _mat(args[1], 'copulacdf', 'U')
    fam, P, nu = _copula_args(py_str(args[0]), args[2:], 'copulacdf')
    return out(np.asarray(_copula_cdf(fam, P, nu, U)).reshape(-1, 1))


@bi('copulastat', nout=2)
def copulastat(nargout, *args):
    """r = copulastat(family, param), copulastat(..., 'Type', 'kendall'|'spearman'): the rank correlation a copula's parameter gives."""
    nargchk(args, 2, 5, 'copulastat')
    fam = py_str(args[0]).lower()
    rest = list(args[1:])
    kind = 'kendall'
    if len(rest) >= 2 and is_str(rest[-2]) and py_str(rest[-2]).lower() == 'type':
        kind = py_str(rest[-1]).lower()
        rest = rest[:-2]
    if fam in ('gaussian', 't'):
        rho = np.asarray(darr(rest[0]), float)
        r = 2 / math.pi * np.arcsin(rho) if kind == 'kendall' else (6 / math.pi * np.arcsin(rho / 2) if fam == 'gaussian' else None)
        if r is None:
            raise err('stats:copulastat:t', "The t copula's Spearman correlation has no closed form here.", 'copulastat')
        return out(r) if np.ndim(r) else float(r)
    a = float(num(rest[0]))
    if kind != 'kendall':
        from scipy.integrate import dblquad
        val = dblquad(lambda v, u: _copula_cdf(fam, a, None, np.array([[u, v]]))[0], 0, 1, 0, 1)[0]
        return 12 * val - 3
    if fam == 'clayton':
        return a / (a + 2)
    if fam == 'gumbel':
        return 1 - 1 / a
    return _frank_tau(a)


@bi('copulaparam')
def copulaparam(nargout, *args):
    """param = copulaparam(family, r): the parameter that gives a Kendall rank correlation r."""
    nargchk(args, 2, 4, 'copulaparam')
    fam = py_str(args[0]).lower()
    r = float(num(args[1]))
    if fam in ('gaussian', 't'):
        return math.sin(math.pi * r / 2)
    if fam == 'clayton':
        return 2 * r / (1 - r)
    if fam == 'gumbel':
        return 1 / (1 - r)
    from scipy.optimize import brentq
    return brentq(lambda a: _frank_tau(a) - r, -100 if r < 0 else 1e-6, -1e-6 if r < 0 else 100)


@bi('copulafit', nout=2)
def copulafit(nargout, *args):
    """rho = copulafit('Gaussian', U), [rho, nu] = copulafit('t', U), alpha = copulafit('Clayton'|'Frank'|'Gumbel', U): a copula fitted to data in the unit square (cube) by maximum likelihood."""
    nargchk(args, 2, 6, 'copulafit')
    from scipy.optimize import minimize_scalar
    fam = py_str(args[0]).lower()
    U = _mat(args[1], 'copulafit', 'U')
    st = _st()
    if fam == 'gaussian':
        Z = st.norm.ppf(np.clip(U, 1e-12, 1 - 1e-12))
        return out(np.corrcoef(Z, rowvar=False))
    if fam == 't':
        def rho_for(nu):
            T = st.t.ppf(np.clip(U, 1e-12, 1 - 1e-12), nu)
            Rm = np.corrcoef(T, rowvar=False)
            return Rm, -np.sum(np.log(_copula_pdf('t', Rm, nu, U)))
        r = minimize_scalar(lambda lnu: rho_for(math.exp(lnu))[1], bounds=(math.log(1.0), math.log(200.0)), method='bounded')
        nu = math.exp(r.x)
        res = (out(rho_for(nu)[0]), float(nu))
        return res if nargout > 1 else res[0]
    if fam not in _ARCH:
        raise err('stats:copulafit:family', "The family is 'Gaussian', 't', 'Clayton', 'Frank' or 'Gumbel'.", 'copulafit')
    tau = st.kendalltau(U[:, 0], U[:, 1])[0]
    a0 = copulaparam(1, Char.of(fam), float(np.clip(tau, -0.95 if fam == 'frank' else 0.01, 0.95)))
    lo, hi = {'clayton': (1e-4, max(50.0, 3 * a0)), 'gumbel': (1.0, max(50.0, 3 * a0)), 'frank': (min(-50.0, 3 * a0), max(50.0, 3 * a0))}[fam]
    r = minimize_scalar(lambda a: -np.sum(np.log(np.maximum(_copula_pdf(fam, a, None, U), 1e-300))), bounds=(lo, hi), method='bounded')
    return float(r.x)


# ---- designs of experiments -----------------------------------------------------------------------------------------------------------

@bi('fullfact')
def fullfact(nargout, *args):
    """d = fullfact(levels): every combination of the factors' levels (numbered from 1), the first factor changing fastest."""
    nargchk(args, 1, 1, 'fullfact')
    if is_str(args[0]):
        raise err('stats:fullfact:levels', 'The levels must be numbers, not text.', 'fullfact')
    L = [int(v) for v in _vec(args[0])]
    if any(l < 1 for l in L):
        raise err('stats:fullfact:levels', 'Each factor needs at least one level.', 'fullfact')
    _runs_ok(float(np.prod([float(l) for l in L])), 'fullfact')
    rows = list(itertools.product(*[range(1, l + 1) for l in reversed(L)]))
    return out(np.array([r[::-1] for r in rows], float).reshape(-1, len(L)))


@bi('ff2n')
def ff2n(nargout, *args):
    """d = ff2n(n): the two-level full factorial of n factors, 0 and 1, counting in binary (the last factor fastest)."""
    nargchk(args, 1, 1, 'ff2n')
    n = _count(args[0], 'ff2n')
    _runs_ok(2.0 ** n, 'ff2n')
    return out(_binary(n))


@bi('fracfact')
def fracfact(nargout, *args):
    """d = fracfact(gen): a two-level fractional factorial (-1 and 1) from its generators, as 'a b c abc' (each a product of base factors)."""
    nargchk(args, 1, 5, 'fracfact')
    words = py_str(args[0]).split() if is_str(args[0]) else [str(s) for s in text_list(args[0])]
    base = sorted(set(ch for w in words if len(w.lstrip('+-')) == 1 for ch in w.lstrip('+-')))
    letters = sorted(set(ch for w in words for ch in w.lstrip('+-')))
    if set(letters) - set(base):
        raise err('stats:fracfact:generators', 'Every letter of a generator is a base factor of its own.', 'fracfact')
    _runs_ok(2.0 ** len(base), 'fracfact')
    full = _binary(len(base), True)
    col = {b: full[:, i] for i, b in enumerate(base)}
    D = np.column_stack([(-1 if w.startswith('-') else 1) * np.prod([col[ch] for ch in w.lstrip('+-')], axis=0) for w in words])
    return out(D)


@bi('bbdesign')
def bbdesign(nargout, *args):
    """D = bbdesign(n), bbdesign(n, 'center', nc): a Box-Behnken design of n factors (3 to 7) at -1, 0 and 1: each pair of factors at their four corners, the rest at 0, and nc centre points (one unless given)."""
    nargchk(args, 1, 3, 'bbdesign')
    n = _count(args[0], 'bbdesign')
    if n < 3:
        raise err('stats:bbdesign:n', 'bbdesign takes 3 factors or more.', 'bbdesign')
    _runs_ok(2.0 * n * (n - 1), 'bbdesign')
    nc = _int(args[2]) if len(args) > 2 else 1
    rows = []
    for i, j in itertools.combinations(range(n), 2):
        for a_, b_ in itertools.product([-1.0, 1.0], repeat=2):
            r = np.zeros(n)
            r[i], r[j] = a_, b_
            rows.append(r)
    rows += [np.zeros(n)] * nc
    return out(np.array(rows))


@bi('ccdesign', nout=2)
def ccdesign(nargout, *args):
    """[dCC, blocks] = ccdesign(n), ccdesign(n, 'type', 'circumscribed'|'inscribed'|'faced', 'center', nc): a central composite design: the factorial corners, the axial points at +-alpha (the fourth root of the corners' number, rotatable), and nc centre points (n unless given)."""
    nargchk(args, 1, 9, 'ccdesign')
    n = _count(args[0], 'ccdesign', lo=2)
    _runs_ok(2.0 ** n + 2 * n, 'ccdesign')
    o = _pairs(args[1:], 'ccdesign', ('type', 'center', 'fraction', 'blocksize'))
    kind = py_str(o.get('type', Char.of('circumscribed'))).lower()
    nc = _int(o['center']) if 'center' in o and not is_str(o['center']) else n
    corners = _binary(n, True)
    alpha = len(corners) ** 0.25
    axial = np.vstack([v * alpha * np.eye(n)[i] for i in range(n) for v in (-1, 1)]) + 0.0     # no -0
    if kind == 'inscribed':
        corners = corners / alpha
        axial = axial / alpha
    elif kind == 'faced':
        axial = axial / alpha
    elif kind != 'circumscribed':
        raise err('stats:ccdesign:type', "type is 'circumscribed', 'inscribed' or 'faced'.", 'ccdesign')
    D = np.vstack([corners, axial, np.zeros((nc, n))])
    return (out(D), out(np.ones((D.shape[0], 1)))) if nargout > 1 else out(D)


def _model_matrix(D, model):
    """The columns of a model's terms: a constant, the factors, and their products or squares as the model has them."""
    n, p = D.shape
    m = model.lower()
    cols = [np.ones(n)]
    cols += [D[:, j] for j in range(p)]
    if m in ('interaction', 'quadratic'):
        cols += [D[:, i] * D[:, j] for i, j in itertools.combinations(range(p), 2)]
    if m in ('purequadratic', 'quadratic'):
        cols += [D[:, j] ** 2 for j in range(p)]
    if m not in ('linear', 'interaction', 'quadratic', 'purequadratic'):
        raise err('stats:rowexch:model', "The model is 'linear', 'interaction', 'quadratic', 'purequadratic' or a terms matrix.", 'rowexch')
    return np.column_stack(cols)


@bi('candgen')
def candgen(nargout, *args):
    """C = candgen(nfactors, model): a candidate set for D-optimal designs: the grid of -1 and 1 (and 0 for a quadratic model)."""
    nargchk(args, 2, 4, 'candgen')
    p = _count(args[0], 'candgen')
    model = py_str(args[1]).lower() if is_str(args[1]) else 'linear'
    lv = [-1.0, 0.0, 1.0] if model in ('quadratic', 'purequadratic') else [-1.0, 1.0]
    _runs_ok(float(len(lv)) ** p, 'candgen')
    return out(np.array(list(itertools.product(lv, repeat=p))))


def _exchange(C, nruns, model, tries, rs, maxit=10):
    """Rows of C (by their model columns: C itself when model is None) for nruns runs maximizing det(X'X)."""
    F = C if model is None else _model_matrix(C, model)
    best = None
    for _ in range(tries):
        rows = list(rs.choice(C.shape[0], nruns, replace=nruns > C.shape[0]))
        for _it in range(maxit):
            improved = False
            for i in range(nruns):
                X = F[rows]
                M = X.T @ X + 1e-9 * np.eye(F.shape[1])
                Mi = np.linalg.inv(M)
                d_old = F[rows[i]] @ Mi @ F[rows[i]]
                dv = np.einsum('ij,jk,ik->i', F, Mi, F)
                cross = F @ Mi @ F[rows[i]]
                gain = (1 + dv) * (1 - d_old) + cross ** 2 - 1
                j = int(np.argmax(gain))
                if gain[j] > 1e-9:
                    rows[i] = j
                    improved = True
            if not improved:
                break
        X = F[rows]
        det = np.linalg.slogdet(X.T @ X)
        val = det[1] if det[0] > 0 else -np.inf
        if best is None or val > best[1]:
            best = (list(rows), val)
    return best[0], F


@bi('candexch')
def candexch(nargout, *args):
    """rlist = candexch(C, nruns), candexch(..., 'tries', k): the rows of a matrix of candidate model terms that make a D-optimal design of nruns runs, by exchanges (Fedorov's)."""
    nargchk(args, 2, 10, 'candexch')
    C = _mat(args[0], 'candexch', 'C')
    nruns = _int(args[1])
    o = _pairs(args[2:], 'candexch', ('tries', 'maxiter', 'display', 'init', 'start', 'options', 'bounds'))
    rows, _ = _exchange(C, nruns, None, _int(o.get('tries', 1.0)), _rs(), _int(o.get('maxiter', 10.0)))
    return out(np.array(rows, float).reshape(-1, 1) + 1)


@bi('rowexch', nout=2)
def rowexch(nargout, *args):
    """[dRE, X] = rowexch(nfactors, nruns), rowexch(nfactors, nruns, model, 'tries', k): a D-optimal design by exchanges among the candidate grid (candgen), and its model matrix."""
    nargchk(args, 2, 10, 'rowexch')
    p, nruns = _int(args[0]), _int(args[1])
    model = py_str(args[2]).lower() if len(args) > 2 and is_str(args[2]) and py_str(args[2]).lower() not in ('tries', 'maxiter', 'display') else 'linear'
    rest = list(args[3:]) if len(args) > 2 and is_str(args[2]) and model == py_str(args[2]).lower() else list(args[2:])
    o = _pairs(rest, 'rowexch', ('tries', 'maxiter', 'display', 'init', 'bounds', 'categorical', 'levels', 'options'))
    C = np.asarray(darr(candgen(1, float(p), Char.of(model))), float)
    rows, F = _exchange(C, nruns, model, _int(o.get('tries', 1.0)), _rs(), _int(o.get('maxiter', 10.0)))
    D = C[rows]
    res = (out(D), out(F[rows]))
    return res if nargout > 1 else res[0]


# ---- hidden Markov models ------------------------------------------------------------------------------------------------------------

def _hmm_args(args, fn):
    seq = np.asarray(darr(args[0]), float).reshape(-1).astype(int) - 1
    T = _mat(args[1], fn, 'TRANS')
    E = _mat(args[2], fn, 'EMIS')
    if T.shape[0] != T.shape[1] or E.shape[0] != T.shape[0]:
        raise err(f'stats:{fn}:size', 'TRANS is square, EMIS has a row for each state.', fn)
    if np.any(seq < 0) or np.any(seq >= E.shape[1]):
        raise err(f'stats:{fn}:symbols', f'The symbols are numbered 1 to {E.shape[1]}.', fn)
    return seq, T, E


def _forward_backward(seq, T, E):
    """Scaled forward and backward variables, the process in state 1 before the first symbol."""
    L, K = seq.size, T.shape[0]
    f = np.zeros((K, L + 1))
    f[0, 0] = 1
    s = np.ones(L + 1)
    for t in range(1, L + 1):
        f[:, t] = E[:, seq[t - 1]] * (T.T @ f[:, t - 1])
        s[t] = f[:, t].sum()
        f[:, t] /= s[t] if s[t] > 0 else 1
    b = np.ones((K, L + 1))
    for t in range(L - 1, -1, -1):
        b[:, t] = T @ (E[:, seq[t]] * b[:, t + 1]) / (s[t + 1] if s[t + 1] > 0 else 1)
    return f, b, s


@bi('hmmgenerate', nout=2)
def hmmgenerate(nargout, *args):
    """[seq, states] = hmmgenerate(len, TRANS, EMIS): a sequence of symbols (and of the states that gave them) from a hidden Markov model that starts in state 1 before its first step."""
    nargchk(args, 3, 7, 'hmmgenerate')
    L = _int(args[0])
    T = _mat(args[1], 'hmmgenerate', 'TRANS')
    E = _mat(args[2], 'hmmgenerate', 'EMIS')
    rs = _rs()
    st, seq = np.zeros(L, int), np.zeros(L, int)
    cur = 0
    cT, cE = np.cumsum(T, 1), np.cumsum(E, 1)
    for t in range(L):
        cur = min(int(np.searchsorted(cT[cur], rs.random_sample() * cT[cur, -1], side='right')), T.shape[0] - 1)
        st[t] = cur
        seq[t] = min(int(np.searchsorted(cE[cur], rs.random_sample() * cE[cur, -1], side='right')), E.shape[1] - 1)
    res = (out(seq.reshape(1, -1) + 1.0), out(st.reshape(1, -1) + 1.0))
    return res if nargout > 1 else res[0]


@bi('hmmviterbi')
def hmmviterbi(nargout, *args):
    """states = hmmviterbi(seq, TRANS, EMIS): the most likely path of states for a sequence (Viterbi), from state 1 before the first symbol."""
    nargchk(args, 3, 7, 'hmmviterbi')
    seq, T, E = _hmm_args(args, 'hmmviterbi')
    L, K = seq.size, T.shape[0]
    with np.errstate(divide='ignore'):
        lT, lE = np.log(T), np.log(E)
    v = np.full(K, -np.inf)
    v[0] = 0.0
    back = np.zeros((L, K), int)
    for t in range(L):
        cand = v[:, None] + lT
        back[t] = np.argmax(cand, axis=0)
        v = cand[back[t], np.arange(K)] + lE[:, seq[t]]
    path = np.zeros(L, int)
    path[-1] = int(np.argmax(v))
    for t in range(L - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    return out(path.reshape(1, -1) + 1.0)


@bi('hmmdecode', nout=5)
def hmmdecode(nargout, *args):
    """[PSTATES, logpseq, FORWARD, BACKWARD, S] = hmmdecode(seq, TRANS, EMIS): the posterior probability of each state at each step, the log-probability of the sequence, and the scaled forward and backward variables."""
    nargchk(args, 3, 7, 'hmmdecode')
    seq, T, E = _hmm_args(args, 'hmmdecode')
    f, b, s = _forward_backward(seq, T, E)
    P = f * b
    logp = float(np.sum(np.log(s[1:])))
    res = (out(P[:, 1:]), logp, out(f), out(b), out(s.reshape(1, -1)))
    return res[:nargout] if nargout > 1 else res[0]


@bi('hmmestimate', nout=2)
def hmmestimate(nargout, *args):
    """[TRANS, EMIS] = hmmestimate(seq, states), hmmestimate(..., 'Pseudoemissions', P, 'Pseudotransitions', T): the transition and emission probabilities counted from a sequence whose states are known."""
    nargchk(args, 2, 10, 'hmmestimate')
    seq = np.asarray(darr(args[0]), float).reshape(-1).astype(int) - 1
    states = np.asarray(darr(args[1]), float).reshape(-1).astype(int) - 1
    o = _pairs(args[2:], 'hmmestimate', ('pseudoemissions', 'pseudotransitions', 'symbols', 'statenames'))
    K = int(states.max()) + 1
    M = int(seq.max()) + 1
    Tc = np.asarray(darr(o['pseudotransitions']), float) if 'pseudotransitions' in o else np.zeros((K, K))
    Ec = np.asarray(darr(o['pseudoemissions']), float) if 'pseudoemissions' in o else np.zeros((K, M))
    K, M = max(K, Tc.shape[0]), max(M, Ec.shape[1])
    Tc = np.pad(Tc, ((0, K - Tc.shape[0]), (0, K - Tc.shape[1])))
    Ec = np.pad(Ec, ((0, K - Ec.shape[0]), (0, M - Ec.shape[1])))
    prev = 0
    for s_, e_ in zip(states, seq):
        Tc[prev, s_] += 1
        Ec[s_, e_] += 1
        prev = s_
    with np.errstate(invalid='ignore'):
        T = Tc / Tc.sum(1, keepdims=True)
        E = Ec / Ec.sum(1, keepdims=True)
    res = (out(np.nan_to_num(T)), out(np.nan_to_num(E)))
    return res if nargout > 1 else res[0]


@bi('hmmtrain', nout=3)
def hmmtrain(nargout, *args):
    """[ESTTR, ESTEMIT, logliks] = hmmtrain(seq, TRGUESS, EMITGUESS), hmmtrain(..., 'Algorithm', 'BaumWelch'|'Viterbi', 'Tolerance', t, 'Maxiterations', n, 'Pseudoemissions', P, 'Pseudotransitions', T): a hidden Markov model's probabilities estimated from sequences (a cell of them, or one)."""
    nargchk(args, 3, 15, 'hmmtrain')
    seqs = [np.asarray(darr(s), float).reshape(-1).astype(int) - 1 for s in args[0].a.reshape(-1)] if isinstance(args[0], Cell) else \
        [np.asarray(darr(args[0]), float).reshape(-1).astype(int) - 1]
    T = _mat(args[1], 'hmmtrain', 'TRANS').copy()
    E = _mat(args[2], 'hmmtrain', 'EMIS').copy()
    o = _pairs(args[3:], 'hmmtrain', ('algorithm', 'tolerance', 'maxiterations', 'pseudoemissions', 'pseudotransitions', 'symbols', 'verbose'))
    alg = py_str(o.get('algorithm', Char.of('baumwelch'))).lower()
    tol = float(num(o.get('tolerance', 1e-6)))
    maxit = _int(o.get('maxiterations', 500.0))
    pT = np.asarray(darr(o['pseudotransitions']), float) if 'pseudotransitions' in o else 0.0
    pE = np.asarray(darr(o['pseudoemissions']), float) if 'pseudoemissions' in o else 0.0
    K, M = E.shape
    logliks = []
    for it in range(maxit):
        Tc = np.zeros((K, K)) + pT
        Ec = np.zeros((K, M)) + pE
        ll = 0.0
        for seq in seqs:
            if alg == 'viterbi':
                path = np.asarray(darr(hmmviterbi(1, out(seq + 1.0), out(T), out(E))), float).reshape(-1).astype(int) - 1
                prev = 0
                for s_, e_ in zip(path, seq):
                    Tc[prev, s_] += 1
                    Ec[s_, e_] += 1
                    prev = s_
                f, b, sc = _forward_backward(seq, T, E)
                ll += float(np.sum(np.log(sc[1:])))
                continue
            f, b, sc = _forward_backward(seq, T, E)
            ll += float(np.sum(np.log(sc[1:])))
            for t in range(seq.size):
                xi = f[:, t, None] * T * (E[:, seq[t]] * b[:, t + 1])[None, :] / sc[t + 1]
                Tc += xi
            g = f * b
            for t in range(seq.size):
                Ec[:, seq[t]] += g[:, t + 1]
        logliks.append(ll)
        with np.errstate(invalid='ignore'):
            Tn = np.nan_to_num(Tc / Tc.sum(1, keepdims=True))
            En = np.nan_to_num(Ec / Ec.sum(1, keepdims=True))
        change = max(np.max(np.abs(Tn - T)), np.max(np.abs(En - E)))
        T, E = Tn, En
        if len(logliks) > 1 and abs(logliks[-1] - logliks[-2]) / (1 + abs(logliks[-2])) < tol and change < tol:
            break
    else:
        R.warn('stats:hmmtrain:NoConvergence', f'Algorithm did not converge with tolerance {tol:g} in {maxit} iterations.')
    res = (out(T), out(E), out(np.array(logliks).reshape(1, -1)))
    return res[:nargout] if nargout > 1 else res[0]


# ---- Cox proportional hazards -----------------------------------------------------------------------------------------------------------

@bi('coxphfit', nout=4)
def coxphfit(nargout, *args):
    """[b, logl, H, stats] = coxphfit(X, T), coxphfit(..., 'Censoring', c, 'Ties', 'breslow'|'efron', 'Frequency', f, 'Baseline', x0): a Cox proportional hazards regression by Newton's method on the partial likelihood."""
    nargchk(args, 2, 14, 'coxphfit')
    X = _mat(args[0], 'coxphfit')
    t = _vec(args[1])
    o = _pairs(args[2:], 'coxphfit', ('censoring', 'ties', 'frequency', 'baseline', 'init', 'options', 'strata'))
    cens = _vec(o['censoring']).astype(bool) if 'censoring' in o else np.zeros(t.size, bool)
    freq = _vec(o['frequency']) if 'frequency' in o else np.ones(t.size)
    ties = py_str(o.get('ties', Char.of('breslow'))).lower()
    n, p = X.shape
    x0 = _vec(o['baseline']) if 'baseline' in o else X.mean(0)
    Xc = X - x0
    order = np.argsort(t, kind='stable')
    Xc, t, cens, freq = Xc[order], t[order], cens[order], freq[order]
    times = np.unique(t[~cens])

    def ll_grad_hess(b):
        eta = Xc @ b
        r = freq * np.exp(eta)
        L, g, H = 0.0, np.zeros(p), np.zeros((p, p))
        for tt in times:
            atrisk = t >= tt
            dead = (t == tt) & ~cens
            d = freq[dead].sum()
            S0 = r[atrisk].sum()
            S1 = (r[atrisk, None] * Xc[atrisk]).sum(0)
            S2 = (r[atrisk, None, None] * Xc[atrisk, :, None] * Xc[atrisk, None, :]).sum(0)
            L += np.sum(freq[dead] * eta[dead])
            g += (freq[dead, None] * Xc[dead]).sum(0)
            if ties == 'efron' and d > 1:
                D0 = r[dead].sum()
                D1 = (r[dead, None] * Xc[dead]).sum(0)
                D2 = (r[dead, None, None] * Xc[dead, :, None] * Xc[dead, None, :]).sum(0)
                m = int(round(d))
                for k in range(m):
                    f = k / m
                    s0 = S0 - f * D0
                    s1 = S1 - f * D1
                    s2 = S2 - f * D2
                    L -= math.log(s0)
                    g -= s1 / s0
                    H -= s2 / s0 - np.outer(s1, s1) / s0 ** 2
            else:
                L -= d * math.log(S0)
                g -= d * S1 / S0
                H -= d * (S2 / S0 - np.outer(S1, S1) / S0 ** 2)
        return L, g, H
    b = _vec(o['init']) if 'init' in o else np.zeros(p)
    L, g, H = ll_grad_hess(b)
    for _ in range(100):
        step = np.linalg.solve(-H, g)
        lam = 1.0
        for _ in range(30):
            Ln, gn, Hn = ll_grad_hess(b + lam * step)
            if Ln >= L - 1e-12:
                break
            lam /= 2
        b = b + lam * step
        conv = abs(Ln - L) < 1e-10 * (1 + abs(L))
        L, g, H = Ln, gn, Hn
        if conv:
            break
    cov = np.linalg.inv(-H)
    se = np.sqrt(np.diag(cov))
    z = b / se
    pv = 2 * _st().norm.sf(np.abs(z))
    # Breslow's cumulative baseline hazard at x0
    r = freq * np.exp(Xc @ b)
    Hc, cum = [], 0.0
    for tt in times:
        dead = (t == tt) & ~cens
        cum += freq[dead].sum() / r[t >= tt].sum()
        Hc.append((tt, cum))
    Hm = np.array(Hc) if Hc else np.zeros((0, 2))
    stats = Struct.scalar({'beta': out(b.reshape(-1, 1)), 'se': out(se.reshape(-1, 1)), 'z': out(z.reshape(-1, 1)), 'p': out(pv.reshape(-1, 1)), 'covb': out(cov)})
    res = (out(b.reshape(-1, 1)), float(L), out(Hm), stats)
    return res[:nargout] if nargout > 1 else res[0]


# ---- feature selection --------------------------------------------------------------------------------------------------------------------

def _labels_idx(y, fn):
    from .mlmodels import Labels
    return Labels(y, fn)


@bi('relieff', nout=2)
def relieff(nargout, *args):
    """[idx, weights] = relieff(X, y, k), relieff(..., 'method', 'classification'|'regression'): the predictors ranked by ReliefF: by how they differ between each point and its k nearest neighbours of other classes (or values) against its own."""
    nargchk(args, 3, 9, 'relieff')
    X = _mat(args[0], 'relieff')
    k = _int(args[2])
    o = _pairs(args[3:], 'relieff', ('method', 'prior', 'updates', 'categoricalx', 'sigma'))
    method = py_str(o.get('method', Char.of('classification'))).lower()
    n, p = X.shape
    rng_ = X.max(0) - X.min(0)
    rng_ = np.where(rng_ > 0, rng_, 1)
    Z = X / rng_
    from scipy.spatial.distance import cdist
    D = cdist(Z, Z, 'cityblock')
    np.fill_diagonal(D, np.inf)
    W = np.zeros(p)
    if method == 'classification':
        L = _labels_idx(args[1], 'relieff')
        y = L.idx
        K = L.K
        prior = np.bincount(y[y >= 0], minlength=K) / np.sum(y >= 0)
        for i in range(n):
            if y[i] < 0:
                continue
            for c in range(K):
                members = np.flatnonzero((y == c) & (np.arange(n) != i))
                if members.size == 0:
                    continue
                near = members[np.argsort(D[i, members], kind='stable')[:k]]
                diff = np.abs(Z[near] - Z[i]).mean(0)
                if c == y[i]:
                    W -= diff
                else:
                    W += prior[c] / (1 - prior[y[i]]) * diff
        W /= n
    else:
        y = _vec(args[1])
        yr = (y - y.min()) / max(np.ptp(y), 1e-300)
        sigma = float(num(o.get('sigma', 50.0)))
        Ndc, Nda, Ndadc = 0.0, np.zeros(p), np.zeros(p)
        for i in range(n):
            near = np.argsort(D[i], kind='stable')[:k]
            rank_w = np.exp(-(np.arange(1, near.size + 1) / sigma) ** 2)
            rank_w /= rank_w.sum()
            dy = np.abs(yr[near] - yr[i])
            dx = np.abs(Z[near] - Z[i])
            Ndc += np.sum(dy * rank_w)
            Nda += np.sum(dx * rank_w[:, None], 0)
            Ndadc += np.sum(dx * (dy * rank_w)[:, None], 0)
        W = Ndadc / Ndc - (Nda - Ndadc) / (n - Ndc)
    idx = np.argsort(-W, kind='stable')
    res = (out(idx.reshape(1, -1) + 1.0), out(W.reshape(1, -1)))
    return res if nargout > 1 else res[0]


def _discretize(x, bins=10):
    """A numeric predictor in up to 10 groups of about equal counts (its distinct values when fewer)."""
    u = np.unique(x[~np.isnan(x)])
    if u.size <= bins:
        return np.searchsorted(u, x)
    edges = np.unique(np.quantile(x[~np.isnan(x)], np.linspace(0, 1, bins + 1)[1:-1]))
    return np.searchsorted(edges, x, side='right')


@bi('fscchi2', nout=2)
def fscchi2(nargout, *args):
    """[idx, scores] = fscchi2(X, Y): the predictors ranked by chi-square tests of their independence from the response (numeric ones in groups of equal counts); scores = -log(p)."""
    nargchk(args, 2, 6, 'fscchi2')
    X = _mat(args[0], 'fscchi2')
    L = _labels_idx(args[1], 'fscchi2')
    y = L.idx
    scores = np.zeros(X.shape[1])
    for j in range(X.shape[1]):
        g = _discretize(X[:, j])
        ok = y >= 0
        tab = np.zeros((g.max() + 1, L.K))
        np.add.at(tab, (g[ok], y[ok]), 1)
        tab = tab[tab.sum(1) > 0][:, tab.sum(0) > 0]
        if tab.shape[0] < 2 or tab.shape[1] < 2:
            continue
        p = _st().chi2_contingency(tab, correction=False)[1]
        scores[j] = -math.log(max(p, 1e-300))
    idx = np.argsort(-scores, kind='stable')
    res = (out(idx.reshape(1, -1) + 1.0), out(scores.reshape(1, -1)))
    return res if nargout > 1 else res[0]


def _mutual_info(a, b):
    ka, kb = a.max() + 1, b.max() + 1
    tab = np.zeros((ka, kb))
    np.add.at(tab, (a, b), 1)
    P = tab / tab.sum()
    pa, pb = P.sum(1, keepdims=True), P.sum(0, keepdims=True)
    with np.errstate(divide='ignore', invalid='ignore'):
        v = np.where(P > 0, P * np.log(P / (pa * pb)), 0)
    return float(v.sum())


@bi('fscmrmr', nout=2)
def fscmrmr(nargout, *args):
    """[idx, scores] = fscmrmr(X, Y): the predictors ranked by minimum redundancy maximum relevance: each next the one whose mutual information with the response, less its mean with those chosen, is largest (numeric predictors in groups of equal counts)."""
    nargchk(args, 2, 6, 'fscmrmr')
    X = _mat(args[0], 'fscmrmr')
    L = _labels_idx(args[1], 'fscmrmr')
    ok = L.idx >= 0
    y = L.idx[ok]
    G = [_discretize(X[ok, j]) for j in range(X.shape[1])]
    rel = np.array([_mutual_info(g, y) for g in G])
    p = X.shape[1]
    chosen, scores = [], np.zeros(p)
    left = list(range(p))
    while left:
        if not chosen:
            j = int(max(left, key=lambda q: rel[q]))
            val = rel[j]
        else:
            vals = {q: rel[q] - np.mean([_mutual_info(G[q], G[c]) for c in chosen]) for q in left}
            j = max(left, key=lambda q: vals[q])
            val = vals[j]
        scores[j] = max(val, 0.0) if chosen else val
        chosen.append(j)
        left.remove(j)
    res = (out(np.array(chosen, float).reshape(1, -1) + 1), out(scores.reshape(1, -1)))
    return res if nargout > 1 else res[0]


@bi('sequentialfs', aw=True, nout=2)
async def sequentialfs(nargout, *args):
    """[inmodel, history] = sequentialfs(fun, X, y), sequentialfs(..., 'cv', k|c|'none', 'direction', 'forward'|'backward', 'nfeatures', n, 'keepin', idx, 'keepout', idx): predictors chosen one at a time while the cross-validated criterion fun(XTRAIN, ytrain, XTEST, ytest) falls."""
    nargchk(args, 3, 30, 'sequentialfs')
    fun = args[0]
    if not isinstance(fun, FH):
        raise err('stats:sequentialfs:fun', 'sequentialfs takes a function handle first.', 'sequentialfs')
    X = _mat(args[1], 'sequentialfs')
    datas = [args[2]]
    rest = list(args[3:])
    while rest and not is_str(rest[0]):
        datas.append(rest.pop(0))
    o = _pairs(rest, 'sequentialfs', ('cv', 'direction', 'nfeatures', 'keepin', 'keepout', 'options', 'mcreps', 'nullmodel'))
    n, p = X.shape
    from .mlmodels import CVPartition
    cv = o.get('cv', 10.0)
    if is_str(cv) and py_str(cv).lower() == 'none':
        part = CVPartition(n, 'resubstitution')
    elif isinstance(cv, CVPartition):
        part = cv
    else:
        part = CVPartition(n, 'kfold', k=_int(cv))
    direction = py_str(o.get('direction', Char.of('forward'))).lower()
    nf = _int(o['nfeatures']) if 'nfeatures' in o else None
    keepin = set(int(v) - 1 for v in _vec(o['keepin'])) if 'keepin' in o else set()
    keepout = set(int(v) - 1 for v in _vec(o['keepout'])) if 'keepout' in o else set()
    from ..index import idx as take

    def rows(d, mask):
        a_ = np.asarray(darr(d))
        if a_.ndim == 2 and a_.shape[0] == n:
            return take(d, (out(mask.reshape(-1, 1)), Char.of(':')))
        return take(d, (out(mask.reshape(-1, 1)),))

    async def crit(cols):
        if not cols:
            return np.inf
        tot = 0.0
        cnt = 0
        for i in range(part.nsets):
            tr, te = part.train_mask(i), part.test_mask(i)
            Xs = out(X[:, sorted(cols)])
            args_ = [rows(Xs, tr)] + [rows(d, tr) for d in datas] + [rows(Xs, te)] + [rows(d, te) for d in datas]
            v = await fun.acall(1, *args_)
            tot += float(np.sum(darr(v)))
            cnt += int(te.sum())
        return tot / cnt
    inmodel = set(range(p)) - keepout if direction == 'backward' else set(keepin)
    hist_in, hist_crit = [], []
    current = await crit(inmodel) if direction == 'backward' else np.inf
    while True:
        if nf is not None and len(inmodel) == nf:
            break
        cands = [j for j in range(p) if (j not in inmodel and j not in keepout) if direction == 'forward'] if direction == 'forward' else \
            [j for j in inmodel if j not in keepin]
        if not cands:
            break
        vals = {}
        for j in cands:
            vals[j] = await crit(inmodel | {j} if direction == 'forward' else inmodel - {j})
        j = min(cands, key=lambda q: vals[q])
        if nf is None and vals[j] >= current:
            break
        inmodel = inmodel | {j} if direction == 'forward' else inmodel - {j}
        current = vals[j]
        hist_in.append(sorted(inmodel))
        hist_crit.append(current)
    mask = np.zeros((1, p), bool)
    mask[0, list(inmodel)] = True
    In = np.zeros((len(hist_in), p), bool)
    for r, cols in enumerate(hist_in):
        In[r, cols] = True
    history = Struct.scalar({'In': out(In), 'Crit': out(np.array(hist_crit).reshape(1, -1))})
    res = (out(mask), history)
    return res if nargout > 1 else res[0]


# ---- plots of many variables -------------------------------------------------------------------------------------------------------------

def _group_lines(ax, curves, groups, labels):
    from ..graphics_base import Line
    handles = []
    for gi, lab in enumerate(labels):
        col = ax.next_color()
        sel = [i for i in range(len(curves)) if groups[i] == gi]
        if not sel:
            continue
        xs, ys = [], []
        for i in sel:
            xs += list(curves[i][0]) + [np.nan]
            ys += list(curves[i][1]) + [np.nan]
        L = Line(ax)
        L.props['XData'], L.props['YData'] = np.array([xs]), np.array([ys])
        L.props['Color'] = col
        L.props['DisplayName'] = lab
        handles.append(L)
    return handles


def _grouping(o, n, fn):
    if 'group' in o:
        from .statdesc import groups
        labels, idx = groups(o['group'], n, fn)
        return labels, idx
    return [''], np.zeros(n, int)


def _standardize(X, how):
    how = how.lower()
    if how == 'on':
        sd = X.std(0, ddof=1)
        return (X - X.mean(0)) / np.where(sd > 0, sd, 1)
    if how in ('pca', 'pcastd'):
        Xc = X - X.mean(0)
        if how == 'pcastd':
            sd = Xc.std(0, ddof=1)
            Xc = Xc / np.where(sd > 0, sd, 1)
        U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
        return Xc @ Vt.T
    return X


@bi('andrewsplot')
def andrewsplot(nargout, *args):
    """h = andrewsplot(X), andrewsplot(..., 'Group', g, 'Standardize', 'on'|'PCA'|'PCAStd'): each row drawn as the curve x1/sqrt(2) + x2 sin(2 pi t) + x3 cos(2 pi t) + x4 sin(4 pi t) + ... for t in [0, 1]."""
    nargchk(args, 1, 9, 'andrewsplot')
    from .graphics import newplot
    X = _mat(args[0], 'andrewsplot')
    o = _pairs(args[1:], 'andrewsplot', ('group', 'standardize', 'quantile'))
    X = _standardize(X, py_str(o.get('standardize', Char.of('off'))))
    t = np.linspace(0, 1, 101)
    p = X.shape[1]
    basis = [np.full_like(t, 1 / math.sqrt(2))]
    for k in range(1, p):
        m = (k + 1) // 2
        basis.append(np.sin(2 * math.pi * m * t) if k % 2 == 1 else np.cos(2 * math.pi * m * t))
    Bm = np.array(basis)
    labels, idx = _grouping(o, X.shape[0], 'andrewsplot')
    ax = newplot(None)
    curves = [(t, X[i] @ Bm) for i in range(X.shape[0])]
    hs = _group_lines(ax, curves, idx, labels)
    ax.touch()
    from ..graphics_base import HArr
    return HArr.of(hs, col=True) if nargout else None


@bi('parallelcoords')
def parallelcoords(nargout, *args):
    """h = parallelcoords(X), parallelcoords(..., 'Group', g, 'Labels', names, 'Standardize', 'on'|'PCA'|'PCAStd'): each row drawn as a line across its variables, side by side."""
    nargchk(args, 1, 11, 'parallelcoords')
    from .graphics import newplot
    X = _mat(args[0], 'parallelcoords')
    o = _pairs(args[1:], 'parallelcoords', ('group', 'labels', 'standardize', 'quantile'))
    X = _standardize(X, py_str(o.get('standardize', Char.of('off'))))
    labels, idx = _grouping(o, X.shape[0], 'parallelcoords')
    ax = newplot(None)
    xs = np.arange(1, X.shape[1] + 1, dtype=float)
    hs = _group_lines(ax, [(xs, X[i]) for i in range(X.shape[0])], idx, labels)
    ax.set_value('XTick', xs.reshape(1, -1))
    if 'labels' in o:
        ax.set_value('XTickLabel', Cell.of_list([Char.of(str(s)) for s in text_list(o['labels'])]))
    ax.set_value('XLim', np.array([[0.5, X.shape[1] + 0.5]]))
    ax.touch()
    from ..graphics_base import HArr
    return HArr.of(hs, col=True) if nargout else None


@bi('probplot')
def probplot(nargout, *args):
    """h = probplot(y), probplot(dist, y), probplot(ax, ...): the data's order statistics against a distribution's quantiles (normal unless named: 'exponential', 'extreme value', 'lognormal', 'rayleigh', 'weibull', 'half normal'), with the line through their quartiles."""
    nargchk(args, 1, 4, 'probplot')
    from .graphics import newplot
    from ..graphics_base import Line
    a = list(args)
    dist = 'normal'
    if is_str(a[0]):
        dist = py_str(a.pop(0)).lower()
    y = np.sort(_vec(a[0]))
    y = y[~np.isnan(y)]
    n = y.size
    pp = (np.arange(1, n + 1) - 0.5) / n
    st = _st()
    table = {'normal': (st.norm.ppf, lambda v: v), 'exponential': (lambda q: -np.log1p(-q), lambda v: v),
             'extreme value': (lambda q: np.log(-np.log1p(-q)), lambda v: v), 'ev': (lambda q: np.log(-np.log1p(-q)), lambda v: v),
             'lognormal': (st.norm.ppf, np.log), 'rayleigh': (lambda q: np.sqrt(-2 * np.log1p(-q)), lambda v: v),
             'weibull': (lambda q: np.log(-np.log1p(-q)), np.log), 'half normal': (lambda q: st.norm.ppf((1 + q) / 2), lambda v: v)}
    if dist not in table:
        raise err('stats:probplot:dist', "The distribution is 'normal', 'exponential', 'extreme value', 'lognormal', 'rayleigh', 'weibull' or 'half normal'.", 'probplot')
    qf, tr = table[dist]
    q = qf(pp)
    v = tr(y)
    ax = newplot(None)
    L = Line(ax)
    L.props['XData'], L.props['YData'] = v.reshape(1, -1), q.reshape(1, -1)
    L.props['LineStyle'] = 'none'
    L.props['Marker'] = '+'
    L.props['Color'] = (0.0, 0.447, 0.741)
    i1, i3 = int(round(0.25 * (n - 1))), int(round(0.75 * (n - 1)))
    if v[i3] != v[i1]:
        slope = (q[i3] - q[i1]) / (v[i3] - v[i1])
        xs = np.array([v.min(), v.max()])
        Lr = Line(ax)
        Lr.props['XData'], Lr.props['YData'] = xs.reshape(1, -1), (q[i1] + slope * (xs - v[i1])).reshape(1, -1)
        Lr.props['LineStyle'] = '--'
        Lr.props['Color'] = (0.85, 0.325, 0.098)
    R._builtin('xlabel', ax, Char.of('Data' if tr is not np.log else 'log(Data)'))
    R._builtin('ylabel', ax, Char.of('Quantile'))
    R._builtin('title', ax, Char.of('Probability plot for ' + dist.title() + ' distribution'))
    ax.touch()
    return L if nargout else None

