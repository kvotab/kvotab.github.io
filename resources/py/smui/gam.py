"""Analyze > Specialized Modeling > Generalized Additive Model.

statsmodels' GLMGam: a generalized linear model whose linear predictor is
the sum of smooth functions of some columns (penalized regression splines)
and an ordinary linear part (JMP's coding and names, from models.build).

    eta = linear part + s1(x1) + s2(x2) + ...,   mean = inverse link(eta)

Each smooth is a spline basis with a roughness penalty alpha * b'Sb, S the
integral of the squared second derivative:

  B-spline      statsmodels' UnivariateBSplines: `df` basis functions of
                `degree`, knots at quantiles of the column
  cyclic cubic  UnivariateCubicCyclicSplines (patsy's cc): the smallest and
                the largest value of the column are the same point of the
                cycle

Both are centred (constraints='center': the smooth sums to zero over the
rows, mgcv's identifiability constraint), so a term has df - 1 parameters
and its partial effect is the curve about the intercept.

The penalty weights are fixed, or chosen by statsmodels:

  aic, bic, gcv   GLMGam.select_penweight: Nelder-Mead on log(alpha) for
                  the smallest criterion, from the best common multiple of
                  each term's scale on a grid (a start that suits the units),
                  kept within 1e-6 to 1e7 times the scale. Far above that the
                  penalty leaks into the straight line a B-spline term keeps
                  unpenalized (rounding in S), its EDF falls below 1 and the
                  criterion "improves"; an unbounded search walks off there.
                  The bounded search is select_penweight's basinhopping with
                  niter=0: one bounded Nelder-Mead run, no random hops.
  kfold           GLMGam.select_penweight_kfold over a grid about the same
                  scales, with shuffled folds that are the same for every
                  alpha (statsmodels' KFold shuffles anew for each)

Two things statsmodels' GLMGam does not do by itself, done here: a Weight
(var_weights) reaches its penalized IRLS only through fit(weights=...), and
select_penweight refits without it; a Freq column is used as that many
copies of the row (GLMGam's residual degrees of freedom count rows, so
freq_weights would give a wrong scale).

The names the page calls:

  gam.fit       the report: smooth terms (partial effects with bands and
                partial residuals), model summary, tests, estimates, rows
  gam.term      one term refitted at trial penalties (the alpha slider)
  gam.profile   the Prediction Profiler, on the response scale
  gam.surface   the sum of the partial effects of two smooth terms
  gam.compare   the same model with the smooth columns as linear terms (GLM)

Fits are remembered (models.remember) under a key of everything that
defines them, so the slider, the profiler and the surface reuse them.
"""
import functools
import hashlib
import json
import math
import warnings

import numpy as np
import pandas as pd
from scipy import stats

from . import data, models
from .registry import api
from . import profile as profile_mod
from .util import code_head, col, table as rtable

_SM_FAMILY = {'normal': 'Gaussian', 'binomial': 'Binomial', 'poisson': 'Poisson', 'gamma': 'Gamma'}
_FAMILY_LABEL = {'normal': 'Normal', 'binomial': 'Binomial', 'poisson': 'Poisson', 'gamma': 'Gamma'}
_SM_LINK = {'identity': 'Identity', 'log': 'Log', 'logit': 'Logit', 'probit': 'Probit', 'cloglog': 'CLogLog',
            'reciprocal': 'InversePower', 'sqrt': 'Sqrt'}
_LINK_LABEL = {'identity': 'Identity', 'log': 'Log', 'logit': 'Logit', 'probit': 'Probit', 'cloglog': 'Comp LogLog',
               'reciprocal': 'Reciprocal', 'sqrt': 'Square Root'}
LINKS = {'normal': ['identity', 'log', 'reciprocal'], 'binomial': ['logit', 'probit', 'cloglog', 'log'],
         'poisson': ['log', 'identity', 'sqrt'], 'gamma': ['log', 'reciprocal', 'identity']}
_SMOOTHING = {'aic': 'AIC', 'bic': 'BIC', 'gcv': 'GCV', 'kfold': 'K-Fold Cross-Validation', 'fixed': 'Fixed penalty weights'}
_CRITERION = {'aic': 'aic', 'bic': 'bic_llf', 'gcv': 'gcv'}
_GRID = 10.0 ** np.arange(-3, 5)      # the common multiples of the scales tried for the start
_BOUNDS = (1e-6, 1e7)                 # the search's range, as multiples of each term's scale
_SIMPLEX = 0.5 * math.log(10)         # Nelder-Mead's first steps: half a decade of alpha
_MAXFUN = 400                         # at most this many fits in one search
_FREQ_MAX = 200_000                   # rows after a Freq column's copies
_SEED = 20260926                      # the folds of k-fold cross-validation


# ---------------------------------------------------------------------------
# the model: its spec (the cache key), its design, its fit
# ---------------------------------------------------------------------------

def _term_spec(t, i):
    t = dict(t or {})
    basis = 'cc' if t.get('basis') == 'cc' else 'bs'
    df = int(round(float(t.get('df') or 10)))
    degree = int(round(float(t.get('degree') or 3)))
    return {'basis': basis, 'df': df, 'degree': degree}


def _spec(y=None, smooth=(), linear=(), weight=None, freq=None, family='normal', link=None, smoothing='aic', penalty=None,
          terms=None, target=None, folds=5, **_ignored):
    """Everything that defines a fit, as a plain dict (the cache key)."""
    family = family if family in _SM_FAMILY else 'normal'
    link = link or LINKS[family][0]
    smooth = [str(s) for s in (smooth or [])]
    terms = list(terms or [])
    terms = [_term_spec(terms[i] if i < len(terms) else None, i) for i in range(len(smooth))]
    pen = None
    if penalty is not None:
        pen = [float(a) for a in penalty]
        if len(pen) != len(smooth) or not all(np.isfinite(pen)) or min(pen) < 0:
            raise ValueError('give one penalty weight, zero or above, for each smooth term')
    return {'y': str(y) if y is not None else None, 'smooth': smooth, 'linear': [str(s) for s in (linear or [])], 'weight': weight,
            'freq': freq, 'family': family, 'link': link, 'smoothing': smoothing if smoothing in _SMOOTHING else 'aic', 'penalty': pen,
            'terms': terms, 'target': target, 'folds': max(2, min(20, int(folds or 5)))}


def _rows_sig(rows):
    if rows is None:
        return 'all'
    a = np.asarray(rows, dtype=np.int64)
    return f'{len(a)}:{hashlib.blake2b(a.tobytes(), digest_size=10).hexdigest()}'


def _family(family, link):
    import statsmodels.api as sm
    return getattr(sm.families, _SM_FAMILY[family])(link=getattr(sm.families.links, _SM_LINK[link])())


def _lvl(v):
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return str(int(f)) if f.is_integer() else f'{f:.6g}'
    return str(v)


def _pylit(v):
    """A level as a Python literal for the code under the report."""
    if isinstance(v, (float, np.floating, int, np.integer)) and not isinstance(v, bool):
        return repr(float(v))
    return json.dumps(str(v))


def _endog(d, spec):
    """The response as numbers, and what it means: a continuous Y as it is;
    a two-level Y (or a numeric 0/1 one) for the binomial as the event
    indicator."""
    family = spec['family']
    s = d.df[d.y_alias]
    info = {'event': None}
    if isinstance(s.dtype, pd.CategoricalDtype):
        lv = [c for c in s.cat.categories if (s == c).any()]
        if family != 'binomial':
            raise ValueError(f'{spec["y"]} is {"ordinal" if s.cat.ordered else "nominal"}: the {_FAMILY_LABEL[family]} distribution needs a '
                             'continuous Y (a two-level Y takes the Binomial)')
        if len(lv) != 2:
            raise ValueError(f'{spec["y"]} has {len(lv)} levels: the Binomial takes a two-level or 0/1 Y')
        event = None
        if spec['target'] is not None:
            event = next((v for v in lv if _lvl(v) == _lvl(spec['target']) or v == spec['target']), None)
        if event is None:
            numeric01 = all(isinstance(v, (float, np.floating, int)) for v in lv) and sorted(float(v) for v in lv) == [0.0, 1.0]
            event = [v for v in lv if float(v) == 1.0][0] if numeric01 else lv[0]
        info['event'] = event
        info['levels'] = lv
        return (s == event).to_numpy(float), info
    y = s.to_numpy(float)
    if family == 'binomial':
        u = np.unique(y)
        if not np.all(np.isin(u, [0.0, 1.0])):
            raise ValueError(f'the Binomial needs a Y of 0s and 1s (or a two-level Y); {spec["y"]} has other values')
        info['event'] = 1.0
    elif family == 'poisson' and np.any(y < 0):
        raise ValueError(f'the Poisson needs a Y that is zero or above; {spec["y"]} has negative values')
    elif family == 'gamma' and np.any(y <= 0):
        raise ValueError(f'the Gamma needs a Y above zero; {spec["y"]} has values at or below zero')
    return y, info


def _design(tid, rows, spec):
    """The rows of the model and every array the fit needs, with a Freq
    column's copies made."""
    import patsy
    if not spec['y']:
        raise ValueError('choose a Y')
    if not spec['smooth']:
        raise ValueError('choose at least one Smooth Term')
    used = [spec['y']] + spec['smooth'] + spec['linear']
    if len(set(used)) != len(used):
        raise ValueError('a column is in two roles (Y, Smooth Terms, Linear Terms): each column once')
    for name in spec['smooth']:
        if data.is_categorical(tid, name):
            raise ValueError(f'{name} is not continuous: a smooth term needs a continuous column (put it in Linear Terms)')
    d = models.build(tid, spec['y'], [[n] for n in spec['linear']], rows, spec['weight'], spec['freq'], extra=spec['smooth'])
    if len(d.df) == 0:
        raise ValueError('no rows to fit: every row has a missing value in a column of the model, or is excluded')
    y, info = _endog(d, spec)
    index = d.df.index.to_numpy()
    vw = data.series(tid, spec['weight'], index, as_category=False).to_numpy(float) if spec['weight'] else None
    notes = []
    if spec['freq']:
        fq = data.series(tid, spec['freq'], index, as_category=False).to_numpy(float)
        rep = np.floor(fq + 1e-9).astype(np.intp)   # intp: np.repeat takes nothing wider (32 bits in Pyodide)
        if np.any(np.abs(fq - rep) > 1e-9):
            notes.append(f'{spec["freq"]} has values that are not whole numbers: each row counts its whole part (truncated).')
    else:
        rep = np.ones(len(index), dtype=np.intp)
    keep = rep > 0
    if int(rep[keep].sum()) > _FREQ_MAX:
        raise ValueError(f'{spec["freq"]} adds up to more than {_FREQ_MAX:,} rows, too many to fit here')
    X_all = patsy.dmatrix(d.rhs if spec['linear'] else '1', d.df, return_type='dataframe', NA_action='raise')
    di = X_all.design_info
    for e in d.effects:
        e['terms'] = []
    for term, sl in di.term_name_slices.items():
        for e in d.effects:
            if models._same_term(term, e['term']):
                e['terms'] = list(di.column_names[sl])
    take = np.repeat(np.nonzero(keep)[0], rep[keep])
    first = np.cumsum(rep[keep]) - rep[keep]      # each used row's first copy
    X = X_all.to_numpy(float)[take]
    if np.linalg.matrix_rank(X) < X.shape[1]:
        raise ValueError('the linear terms are collinear (a level with no rows, or a column that is a copy of another): take one out')
    xs = np.column_stack([d.df[d.alias[n]].to_numpy(float) for n in spec['smooth']])[take]
    terms = []
    for j, (name, t) in enumerate(zip(spec['smooth'], spec['terms'])):
        x = xs[:, j]
        u = np.unique(x)
        if len(u) < 4:
            raise ValueError(f'{name} has {len(u)} distinct values: a smooth term needs at least four')
        t = dict(t)
        lo = 3 if t['basis'] == 'cc' else t['degree'] + 1
        if t['basis'] == 'bs' and not 2 <= t['degree'] <= 5:
            raise ValueError(f'{name}: the degree of a B-spline is 2 to 5 (the penalty is on the second derivative)')
        want = t['df']
        t['df'] = max(lo, min(t['df'], 60, len(u)))
        if t['df'] != want:
            notes.append(f'{name}: the basis size is {t["df"]}, not {want} ({"at most the number of distinct values" if want > t["df"] else f"at least {lo}"}).')
        terms.append(t)
    return {'d': d, 'y': y[take], 'y_rows': y[keep], 'info': info, 'X': X, 'X_names': list(X_all.columns), 'di': di, 'xs': xs,
            'vw': vw[take] if vw is not None else None, 'rows': index[keep], 'first': first, 'n_rows': int(keep.sum()),
            'n': int(len(take)), 'terms': terms, 'notes': notes, 'rep': rep[keep]}


def _smoother(xs, names, terms):
    from statsmodels.gam.smooth_basis import GenericSmoothers, UnivariateBSplines, UnivariateCubicCyclicSplines
    sms = []
    for j, (name, t) in enumerate(zip(names, terms)):
        if t['basis'] == 'cc':
            sms.append(UnivariateCubicCyclicSplines(xs[:, j], df=t['df'], constraints='center', variable_name=name))
        else:
            sms.append(UnivariateBSplines(xs[:, j], df=t['df'], degree=t['degree'], include_intercept=True, constraints='center',
                                          variable_name=name))
    return GenericSmoothers(xs, sms)


def _gam(y, X, G, alpha, fam, vw):
    from statsmodels.gam.api import GLMGam
    kw = {'var_weights': vw} if vw is not None else {}
    return GLMGam(y, exog=X, smoother=G, alpha=[float(a) for a in alpha], family=fam, **kw)


def _fit(y, X, G, alpha, fam, vw):
    mod = _gam(y, X, G, alpha, fam, vw)
    # a Weight reaches the penalized IRLS only through fit(weights=...)
    return mod, mod.fit(weights=vw)


def _scales(G, fam, y, vw):
    """Each term's scale for alpha: tr(B'WB)/tr(S), where the penalty is as
    large as the data's part of the fit. Starts and grids are multiples of
    it, so they suit the units of the column."""
    w = np.asarray(fam.weights(fam.starting_mu(y)), dtype=float)
    if vw is not None:
        w = w * vw
    out = []
    for s in G.smoothers:
        B = np.asarray(s.basis, dtype=float)
        tr = float(np.trace(s.cov_der2))
        out.append(float(np.sum(w[:, None] * B * B)) / tr if tr > 0 else 1.0)
    return np.array(out)


class _SeededKFold:
    """K folds of a shuffled order that are the same every time split() is
    called: statsmodels' KFold(shuffle=True) shuffles anew for each alpha
    of the grid, so every alpha would be judged on other folds."""

    def __init__(self, k_folds, seed):
        self.k_folds = k_folds
        self.seed = seed

    def split(self, X, y=None, label=None):
        nobs = X.shape[0]
        order = np.random.default_rng(self.seed).permutation(nobs)
        for fold in np.array_split(order, self.k_folds):
            test = np.zeros(nobs, dtype=bool)
            test[fold] = True
            yield ~test, test


def _kfold_grid(k):
    m = max(2, min(15, int(math.floor(81 ** (1.0 / k) + 1e-9))))
    return np.linspace(-3, 4, m)


def _choose(D, G, fam, spec):
    """The penalty weights: fixed, or chosen by statsmodels."""
    y, X, vw = D['y'], D['X'], D['vw']
    k = len(G.smoothers)
    mode = spec['smoothing']
    a0 = _scales(G, fam, y, vw)
    out = {'mode': mode, 'a0': a0, 'fits': 0, 'notes': [], 'start': None, 'grid': None}
    if spec['penalty'] is not None:
        out['mode'] = 'fixed'
        out['alpha'] = np.array(spec['penalty'], dtype=float)
        return out
    if mode == 'fixed':
        out['alpha'] = a0.copy()
        return out
    if mode == 'kfold':
        why = None
        if spec['family'] != 'normal' or spec['link'] != 'identity':
            why = 'statsmodels\' k-fold search refits with the normal distribution and the identity link only'
        elif vw is not None:
            why = 'statsmodels\' k-fold search refits without the weights'
        elif spec['freq']:
            why = f'the copies of a row that {spec["freq"]} makes would fall into different folds'
        elif any(t['basis'] == 'cc' for t in D['terms']):
            why = 'statsmodels\' k-fold search needs the basis derivatives, which the cyclic cubic basis does not have'
        elif k > 6:
            why = 'a grid for more than six smooth terms is too large'
        if why:
            out['notes'].append(f'K-fold cross-validation is not available here ({why}): the penalties were chosen by AIC.')
            mode = out['mode'] = 'aic'
        else:
            g = _kfold_grid(k)
            alphas = [a0[j] * 10.0 ** g for j in range(k)]
            mod = _gam(y, X, G, a0, fam, None)
            acv, cvres = mod.select_penweight_kfold(alphas=alphas, cv_iterator=_SeededKFold(spec['folds'], _SEED))
            out['alpha'] = np.asarray(acv, dtype=float)
            out['fits'] = len(cvres.alphas_grid) * spec['folds']
            out['grid'] = g
            out['cv_error'] = float(np.min(cvres.cv_error))
            edge = [t for t, a, b in zip(spec['smooth'], out['alpha'], a0) if min(abs(math.log10(a / b) - g[0]), abs(math.log10(a / b) - g[-1])) < 1e-6]
            if edge:
                out['notes'].append('The cross-validation error is smallest at an end of the grid for ' + ', '.join(edge) +
                                    ': the best penalty may lie beyond it.')
            return out
    if mode == 'gcv' and spec['family'] in ('binomial', 'poisson'):
        out['notes'].append('GCV with the scale fixed at 1 (binomial, Poisson) always prefers the smoothest fit: the penalties were chosen by AIC.')
        mode = out['mode'] = 'aic'
    crit = _CRITERION[mode]
    vals = []
    for c in _GRID:
        _m, r = _fit(y, X, G, c * a0, fam, vw)
        vals.append(float(getattr(r, crit)))
    start = a0 * _GRID[int(np.nanargmin(vals))]
    mod, r0 = _fit(y, X, G, start, fam, vw)     # select_penweight needs a fitted model
    if vw is not None:
        # select_penweight refits with _fit_pirls(alpha, start_params): give those refits the weights
        mod._fit_pirls = functools.partial(mod._fit_pirls, weights=vw)
    f0 = float(getattr(r0, crit))
    ftol = 1e-7 * max(1.0, abs(f0))
    s0 = np.log(start)
    simplex = np.vstack([s0] + [s0 + _SIMPLEX * np.eye(k)[j] for j in range(k)])
    bounds = [(math.log(a * _BOUNDS[0]), math.log(a * _BOUNDS[1])) for a in a0]
    alpha, fres, hist = mod.select_penweight(criterion=crit, start_params=start, method='basinhopping', niter=0, minimizer_kwargs={
        'method': 'Nelder-Mead', 'bounds': bounds, 'options': {'xatol': 0.01, 'fatol': ftol, 'maxfev': _MAXFUN, 'initial_simplex': simplex}})
    out['alpha'] = np.asarray(alpha, dtype=float)
    out['fits'] = len(_GRID) + 1 + len(hist['alpha'])
    out['start'] = start
    out['ftol'] = ftol
    low = getattr(fres, 'lowest_optimization_result', None)
    if low is not None and getattr(low, 'status', 0) in (1, 2):
        out['notes'].append(f'The search for the penalties stopped at its limit of {_MAXFUN} fits: the criterion may be lower elsewhere.')
    top = [t for t, a, b in zip(spec['smooth'], out['alpha'], a0) if math.log10(a / b) > math.log10(_BOUNDS[1]) - 0.02]
    if top:
        out['notes'].append('The search reached its largest penalty for ' + ', '.join(top) + ': the smoothest fit (a straight line for a B-spline, '
                            'nothing for a cyclic term).')
    return out


def _model(tid, rows, spec):
    key = models.model_key('gam', tid, data.version(tid), _rows_sig(rows), spec)
    m = models.recall(key)
    if m is not None:
        return m
    D = _design(tid, rows, spec)
    fam = _family(spec['family'], spec['link'])
    G = _smoother(D['xs'], spec['smooth'], D['terms'])
    ch = _choose(D, G, fam, spec)
    mod, res = _fit(D['y'], D['X'], G, ch['alpha'], fam, D['vw'])
    m = {'key': key, 'spec': spec, 'tid': tid, 'D': D, 'd': D['d'], 'G': G, 'fam': fam, 'choice': ch, 'model': mod, 'res': res,
         'k_lin': int(mod.k_exog_linear)}
    models.remember(key, m)
    return m


# ---------------------------------------------------------------------------
# the parts of a fit
# ---------------------------------------------------------------------------

def _idx(m, j):
    return m['k_lin'] + np.nonzero(m['G'].mask[j])[0]


def _const(m):
    return m['D']['X_names'].index('Intercept') if 'Intercept' in m['D']['X_names'] else None


def _curve(m, j, x):
    """The partial effect s_j(x) and its standard error, without and with
    the intercept (statsmodels' partial_values(include_constant=...), at
    any x)."""
    res = m['res']
    b = np.asarray(res.params, dtype=float)
    V = np.asarray(res.cov_params(), dtype=float)
    idx = _idx(m, j)
    B = np.asarray(m['G'].smoothers[j].transform(np.asarray(x, dtype=float)), dtype=float)
    f = B @ b[idx]
    se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', B, V[np.ix_(idx, idx)], B), 0))
    c = _const(m)
    if c is None:
        return f, se, se
    Bc = np.column_stack([np.ones(len(B)), B])
    ic = np.concatenate([[c], idx])
    sec = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', Bc, V[np.ix_(ic, ic)], Bc), 0))
    return f, se, sec


def _edf(m, j):
    return float(np.sum(np.asarray(m['res'].edf, dtype=float)[_idx(m, j)]))


def _grid(x, n):
    lo, hi = float(np.min(x)), float(np.max(x))
    return np.linspace(lo, hi, n) if hi > lo else np.array([lo])


def _term_out(m, j, n_grid=101):
    D, res = m['D'], m['res']
    t = D['terms'][j]
    x = D['xs'][:, j]
    g = _grid(x, n_grid)
    f, se, sec = _curve(m, j, g)
    # partial residuals: the term at each row plus the working residual (statsmodels' plot_partial with cpr)
    first = D['first']
    fx, _, _ = _curve(m, j, x[first])
    wres = np.asarray(res.resid_working, dtype=float)[first]
    return {'name': m['spec']['smooth'][j], 'index': j, 'basis': t['basis'], 'df': t['df'], 'degree': t['degree'] if t['basis'] == 'bs' else None,
            'nparm': int(len(_idx(m, j))), 'alpha': float(m['choice']['alpha'][j]), 'a0': float(m['choice']['a0'][j]), 'edf': _edf(m, j),
            'curve': {'x': g, 'f': f, 'se': se, 'se_c': sec},
            'points': {'x': x[first], 'f': fx, 'partial': fx + wres, 'rows': [int(r) for r in D['rows']]},
            'min': float(np.min(x)), 'max': float(np.max(x)), 'mean': float(np.mean(x))}


def _tests(m):
    """Is the smooth zero? statsmodels' test_significance: the Wald
    statistic of all the term's coefficients, referred to chi-square with
    the term's EDF; beside it the same statistic on as many degrees of
    freedom as the term has parameters."""
    res = m['res']
    out = []
    for j, name in enumerate(m['spec']['smooth']):
        nparm = int(len(_idx(m, j)))
        with warnings.catch_warnings():
            # "the behavior of wald_test will change after 0.14": about statsmodels' API, not this test
            warnings.filterwarnings('ignore', message='The behavior of wald_test', category=FutureWarning)
            try:
                t = res.test_significance(j)
                stat = float(np.squeeze(t.statistic))
                df = float(t.df_denom)
                p = float(np.squeeze(t.pvalue))
                how = 'test_significance'
            except AttributeError:   # an older statsmodels: the Wald test on the term's coefficients
                idx = _idx(m, j)
                b = np.asarray(res.params, dtype=float)[idx]
                V = np.asarray(res.cov_params(), dtype=float)[np.ix_(idx, idx)]
                stat = float(b @ np.linalg.pinv(V) @ b)
                df = _edf(m, j)
                p = float(stats.chi2.sf(stat, df))
                how = 'wald'
        out.append({'term': f's({name})', 'name': name, 'edf': df, 'nparm': nparm, 'chisq': stat, 'p': p,
                    'p_nparm': float(stats.chi2.sf(stat, nparm)), 'how': how})
    return out


def _estimates(m, alpha):
    """The linear part: JMP's names (models.build), Wald chi-square tests."""
    res, d = m['res'], m['d']
    names = m['D']['X_names']
    b = np.asarray(res.params, dtype=float)
    se = np.asarray(res.bse, dtype=float)
    z = float(stats.norm.ppf(1 - alpha / 2))
    rows = []
    for i, nm in enumerate(names):
        w = (b[i] / se[i]) ** 2 if se[i] > 0 else float('nan')
        rows.append({'term': d.label(nm), 'estimate': b[i], 'se': se[i], 'chisq': w, 'p': float(stats.chi2.sf(w, 1)) if np.isfinite(w) else None,
                     'lower': b[i] - z * se[i], 'upper': b[i] + z * se[i], 'name': nm})
    lv = f'{100 * (1 - alpha):g}%'
    est = rtable([col('term', 'Term', 'text'), col('estimate', 'Estimate'), col('se', 'Std Error'), col('chisq', 'Wald ChiSquare'),
                  col('p', 'Prob>ChiSq', 'p'), col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}')], rows)
    V = np.asarray(res.cov_params(), dtype=float)
    eff = []
    for e in d.effects:
        cols = [names.index(t) for t in e.get('terms', []) if t in names]
        if not cols:
            continue
        bb = b[cols]
        vv = V[np.ix_(cols, cols)]
        w = float(bb @ np.linalg.pinv(vv) @ bb)
        eff.append({'source': e['label'], 'nparm': len(cols), 'df': len(cols), 'chisq': w, 'p': float(stats.chi2.sf(w, len(cols)))})
    return est, eff


def _diag(m, alpha):
    D, res = m['D'], m['res']
    first = D['first']
    X = np.asarray(m['model'].exog, dtype=float)
    b = np.asarray(res.params, dtype=float)
    V = np.asarray(res.cov_params(), dtype=float)
    eta = (X @ b)[first]
    Xf = X[first]
    se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', Xf, V, Xf), 0))
    z = float(stats.norm.ppf(1 - alpha / 2))
    inv = m['fam'].link.inverse
    mu = np.asarray(res.fittedvalues, dtype=float)[first]
    lo, hi = inv(eta - z * se), inv(eta + z * se)
    y = D['y'][first]
    return {'rows': [int(r) for r in D['rows']], 'actual': y, 'predicted': mu, 'residual': y - mu,
            'resid_dev': np.asarray(res.resid_deviance, dtype=float)[first], 'resid_pearson': np.asarray(res.resid_pearson, dtype=float)[first],
            'linpred': eta, 'lower_mean': np.minimum(lo, hi), 'upper_mean': np.maximum(lo, hi)}


def _factors(m):
    """The profiler's factors: the smooth terms, then the linear terms."""
    D, d = m['D'], m['d']
    out = []
    for j, name in enumerate(m['spec']['smooth']):
        x = D['xs'][:, j]
        out.append({'name': name, 'type': 'continuous', 'kind': 'smooth', 'min': float(np.min(x)), 'max': float(np.max(x)), 'mean': float(np.mean(x))})
    for name in m['spec']['linear']:
        a = d.alias[name]
        if a in d.categorical:
            out.append({'name': name, 'type': 'categorical', 'kind': 'linear', 'levels': list(d.levels[a]), 'labels': [_lvl(v) for v in d.levels[a]]})
        else:
            x = d.df[a].to_numpy(float)
            out.append({'name': name, 'type': 'continuous', 'kind': 'linear', 'min': float(np.min(x)), 'max': float(np.max(x)), 'mean': float(np.mean(x))})
    return out


def _summary(m):
    res, D, ch = m['res'], m['D'], m['choice']
    dev, null = float(res.deviance), float(res.null_deviance)
    return {'n': D['n'], 'n_rows': D['n_rows'], 'sum_weights': float(np.sum(D['vw'])) if D['vw'] is not None else None,
            'deviance': dev, 'null_deviance': null, 'dev_explained': (null - dev) / null if null > 0 else None,
            'pearson': float(res.pearson_chi2), 'scale': float(res.scale), 'llf': float(res.llf), 'aic': float(res.aic),
            'bic': float(res.bic_llf), 'gcv': float(res.gcv), 'edf': float(np.sum(res.edf)), 'df_resid': float(res.df_resid),
            'converged': bool(getattr(res, 'converged', True)), 'iterations': int(res.fit_history.get('iteration', 0)) if hasattr(res, 'fit_history') else None,
            'fits': int(ch['fits']), 'smoothing': ch['mode'], 'smoothing_label': _SMOOTHING[ch['mode']]}


def _notes(m):
    spec, ch = m['spec'], m['choice']
    notes = list(m['D']['notes']) + list(ch['notes'])
    if ch['mode'] in _CRITERION:
        notes.append(f'The penalty weights minimise {_SMOOTHING[ch["mode"]]}: statsmodels\' select_penweight, a Nelder-Mead search over log α '
                     f'from the best common multiple of each term\'s scale, within 10⁻⁶ to 10⁷ times it ({ch["fits"]} fits). It is a local search; '
                     'mgcv optimises GCV, UBRE or REML by Newton\'s method, and REML, mgcv\'s recommended choice, is not in statsmodels.')
    elif ch['mode'] == 'kfold':
        notes.append(f'The penalty weights have the smallest {spec["folds"]}-fold cross-validation error, statsmodels\' select_penweight_kfold '
                     f'on a grid of {len(ch["grid"])} values about each term\'s scale ({ch["fits"]} fits), the folds shuffled once (seed {_SEED}).')
    if ch['mode'] == 'gcv':
        notes.append('statsmodels\' GCV is scale / (1 − EDF/n)², with the scale already divided by n − EDF: it asks more of each degree of freedom '
                     'than mgcv\'s n·D/(n − EDF)², and gives smoother fits.')
    notes.append('The penalty is α·bᵀSb, S = ∫s″(x)²dx on the column\'s own scale, so α depends on the units of x and Y (mgcv\'s λ on the same '
                 'basis is 2α). The EDF are diag((XᵀWX + 2αS)⁻¹XᵀWX) summed over a term, as mgcv\'s edf; AIC and BIC count the total EDF as '
                 'the number of parameters, the scale not included.')
    if spec['weight']:
        notes.append(f'{spec["weight"]} enters as statsmodels\' var_weights, given to the penalized IRLS as fit(weights=...), and to every refit of '
                     'the penalty search (GLMGam leaves them out otherwise).')
    if spec['freq']:
        notes.append(f'{spec["freq"]}: each row counts as that many copies (GLMGam\'s freq_weights would count rows in the residual degrees of freedom).')
    if spec['family'] == 'poisson' and not np.allclose(m['D']['y'], np.round(m['D']['y'])):
        notes.append('The Poisson Y has values that are not whole numbers: the likelihood is a quasi-likelihood there.')
    return notes


# ---------------------------------------------------------------------------
# the code under the report
# ---------------------------------------------------------------------------

def _code(m, table_name, rows):
    k = len(m['spec']['smooth'])
    return '\n'.join(_fit_lines(m, table_name, rows) + [
        'print(res.summary())',
        'print("EDF by term:", [res.edf[model.k_exog_linear:][m].sum() for m in smoother.mask], "total:", res.edf.sum())',
        'print("deviance", res.deviance, "AIC", res.aic, "BIC", res.bic_llf, "GCV", res.gcv)',
        f'for i in range({k}):',
        '    print(smoother.smoothers[i].variable_name, res.test_significance(i))   # Wald χ² on the term\'s EDF',
        'fit, se = res.partial_values(0, include_constant=False)   # the first term\'s partial effect at the rows'])


def _fit_lines(m, table_name, rows, extra_imports=()):
    """The code that reads the table and fits the model as the report does
    (the penalty search included), up to res = model.fit()."""
    spec, D, d, ch = m['spec'], m['D'], m['d'], m['choice']
    tid = m['tid']
    cyc = [t['basis'] == 'cc' for t in D['terms']]
    if all(cyc):
        imp = 'from statsmodels.gam.api import GLMGam, CyclicCubicSplines'
    elif not any(cyc):
        imp = 'from statsmodels.gam.api import GLMGam, BSplines'
    else:
        imp = 'from statsmodels.gam.api import GLMGam\nfrom statsmodels.gam.smooth_basis import GenericSmoothers, UnivariateBSplines, UnivariateCubicCyclicSplines'
    extra = [*extra_imports, 'import patsy', imp]
    if ch['mode'] == 'kfold':
        extra.append('from statsmodels.gam.gam_cross_validation.cross_validators import KFold')
    lines = [code_head(table_name, extra)]
    if rows is not None:
        n_all = data.TABLES[tid]['n'] if tid in data.TABLES else None
        keep = [int(r) for r in rows]
        if n_all is not None and len(keep) > n_all / 2:
            drop = sorted(set(range(n_all)) - set(keep))
            if drop:
                lines.append(f'df = df.drop(index={drop})   # the rows the report leaves out')
        else:
            lines.append(f'df = df.loc[{keep}]   # the rows of the report')
    cols = list(dict.fromkeys([spec['y']] + spec['smooth'] + spec['linear'] + [c for c in (spec['weight'], spec['freq']) if c]))
    lines.append(f'd = df[{json.dumps(cols)}].dropna()')
    for n in spec['linear'] + [spec['y']]:
        a = d.alias.get(n)
        if a is None or a not in d.levels:
            continue
        lv = d.levels[a]
        numeric = all(isinstance(v, (float, int, np.floating, np.integer)) for v in lv)
        cats = json.dumps([float(v) for v in lv] if numeric else [str(v) for v in lv])
        src = f'd[{json.dumps(n)}].astype(float)' if numeric else f'd[{json.dumps(n)}]'
        lines.append(f'd[{json.dumps(n)}] = pd.Categorical({src}, categories={cats})   # the level order of the table')
    wf = [c for c in (spec['weight'], spec['freq']) if c]
    if wf:
        lines.append('d = d[' + ' & '.join(f'(d[{json.dumps(c)}] > 0)' for c in wf) + ']   # rows with a positive weight and frequency')
    if spec['freq']:
        lines.append(f'd = d.loc[d.index.repeat(np.floor(d[{json.dumps(spec["freq"])}] + 1e-9).astype(int))]   # {spec["freq"]}: that many copies of each row')
    if D['info']['event'] is not None and D['info'].get('levels') is not None:
        lines.append(f'y = (d[{json.dumps(spec["y"])}] == {_pylit(D["info"]["event"])}).to_numpy(float)   # the event: {_lvl(D["info"]["event"])}')
    else:
        lines.append(f'y = d[{json.dumps(spec["y"])}].to_numpy(float)')
    lines.append(f'xs = d[{json.dumps(spec["smooth"])}].to_numpy(float)')
    names = json.dumps(spec['smooth'])
    if not any(cyc):
        lines.append(f'smoother = BSplines(xs, df={[t["df"] for t in D["terms"]]}, degree={[t["degree"] for t in D["terms"]]}, constraints="center", variable_names={names})')
    elif all(cyc):
        lines.append(f'smoother = CyclicCubicSplines(xs, df={[t["df"] for t in D["terms"]]}, constraints="center", variable_names={names})')
    else:
        parts = []
        for j, (n, t) in enumerate(zip(spec['smooth'], D['terms'])):
            if t['basis'] == 'cc':
                parts.append(f'    UnivariateCubicCyclicSplines(xs[:, {j}], df={t["df"]}, constraints="center", variable_name={json.dumps(n)}),')
            else:
                parts.append(f'    UnivariateBSplines(xs[:, {j}], df={t["df"]}, degree={t["degree"]}, include_intercept=True, constraints="center", variable_name={json.dumps(n)}),')
        lines.append('smoother = GenericSmoothers(xs, [\n' + '\n'.join(parts) + '\n])')
    rhs = models.code_formula(d, lhs=False) if spec['linear'] else '1'
    lines.append(f'X = patsy.dmatrix({json.dumps(rhs)}, d, return_type="dataframe")   # the linear part{", effect coded" if d.categorical else ""}')
    lines.append(f'fam = sm.families.{_SM_FAMILY[spec["family"]]}(link=sm.families.links.{_SM_LINK[spec["link"]]}())')
    wkw = f', var_weights=d[{json.dumps(spec["weight"])}].to_numpy(float)' if spec['weight'] else ''
    fkw = f'weights=d[{json.dumps(spec["weight"])}].to_numpy(float)' if spec['weight'] else ''
    if ch['mode'] in _CRITERION:
        crit = _CRITERION[ch['mode']]
        lines += ['# each term\'s scale for α, tr(BᵀWB)/tr(S); the search starts at the best common multiple of it on a grid',
                  'w = fam.weights(fam.starting_mu(y))' + (f' * d[{json.dumps(spec["weight"])}].to_numpy(float)' if spec['weight'] else ''),
                  'a0 = np.array([np.sum(w[:, None] * s.basis ** 2) / np.trace(s.cov_der2) for s in smoother.smoothers])',
                  'grid = 10.0 ** np.arange(-3, 5)',
                  f'crit = [GLMGam(y, exog=X, smoother=smoother, alpha=list(c * a0), family=fam{wkw}).fit({fkw}).{crit} for c in grid]',
                  'start = a0 * grid[int(np.argmin(crit))]',
                  f'model = GLMGam(y, exog=X, smoother=smoother, alpha=list(start), family=fam{wkw})',
                  f'first = model.fit({fkw})   # select_penweight needs a fitted model']
        if spec['weight']:
            lines += ['import functools',
                      f'model._fit_pirls = functools.partial(model._fit_pirls, weights=d[{json.dumps(spec["weight"])}].to_numpy(float))   # its refits, with the weights']
        lines += ['# Nelder-Mead in log α, kept within 1e-6 to 1e7 times the scale (far above, rounding in S lets the penalty',
                  '# reach a B-spline\'s straight line and the criterion falls for nothing); basinhopping with niter=0 is one bounded run',
                  'simplex = np.log(start) + np.vstack([np.zeros(len(start)), 0.5 * np.log(10) * np.eye(len(start))])',
                  f'bounds = [(np.log(a * {_BOUNDS[0]!r}), np.log(a * {_BOUNDS[1]!r})) for a in a0]',
                  f'alpha, _, _ = model.select_penweight(criterion={json.dumps(crit)}, start_params=start, method="basinhopping", niter=0, minimizer_kwargs={{',
                  f'    "method": "Nelder-Mead", "bounds": bounds, "options": {{"xatol": 0.01, "fatol": {ch["ftol"]!r}, "maxfev": {_MAXFUN}, "initial_simplex": simplex}}}})',
                  f'# alpha = {[float(a) for a in ch["alpha"]]!r}   # what the report found']
    elif ch['mode'] == 'kfold':
        lines += ['class SeededKFold(KFold):   # the same shuffled folds for every α (KFold(shuffle=True) shuffles anew for each)',
                  '    def split(self, X, y=None, label=None):',
                  '        order = np.random.default_rng(self.seed).permutation(X.shape[0])',
                  '        for fold in np.array_split(order, self.k_folds):',
                  '            test = np.zeros(X.shape[0], dtype=bool); test[fold] = True',
                  '            yield ~test, test',
                  'w = fam.weights(fam.starting_mu(y))',
                  'a0 = np.array([np.sum(w[:, None] * s.basis ** 2) / np.trace(s.cov_der2) for s in smoother.smoothers])',
                  f'cv = SeededKFold({spec["folds"]}); cv.seed = {_SEED}',
                  f'alpha, cvres = GLMGam(y, exog=X.to_numpy(), smoother=smoother, alpha=list(a0), family=fam).select_penweight_kfold('
                  f'alphas=[a * 10.0 ** np.linspace(-3, 4, {len(ch["grid"])}) for a in a0], cv_iterator=cv)',
                  f'# alpha = {[float(a) for a in ch["alpha"]]!r}   # what the report found']
    else:
        lines.append(f'alpha = {[float(a) for a in ch["alpha"]]!r}   # the penalty weights, fixed')
    lines += [f'model = GLMGam(y, exog=X, smoother=smoother, alpha=list(alpha), family=fam{wkw})',
              f'res = model.fit({fkw})']
    return lines


# ---------------------------------------------------------------------------
# the entry points
# ---------------------------------------------------------------------------

@api('gam.fit')
def fit(table, rows=None, alpha=0.05, table_name='data', **model):
    spec = _spec(**model)
    m = _model(table, rows, spec)
    res, D = m['res'], m['D']
    terms = [_term_out(m, j) for j in range(len(spec['smooth']))]
    est, eff = _estimates(m, alpha)
    c = _const(m)
    info = D['info']
    return {'model': {'response': spec['y'], 'event': _lvl(info['event']) if info.get('levels') is not None else None,
                      'levels': [_lvl(v) for v in info['levels']] if info.get('levels') is not None else None,
                      'distribution': _FAMILY_LABEL[spec['family']], 'family': spec['family'], 'link': _LINK_LABEL[spec['link']],
                      'link_key': spec['link']},
            'summary': _summary(m), 'terms': terms, 'intercept': float(np.asarray(res.params)[c]) if c is not None else 0.0,
            'tests': _tests(m), 'estimates': est, 'effect_tests': eff, 'diag': _diag(m, alpha), 'factors': _factors(m),
            'alpha': alpha, 'key': m['key'], 'notes': _notes(m), 'code': _code(m, table_name, rows)}


@api('gam.term')
def term(table, index=0, rows=None, n_grid=101, **model):
    """One smooth term at trial penalties (the alpha slider): its curve,
    partial residuals and EDF, and the criteria of the whole fit."""
    spec = _spec(**model)
    m = _model(table, rows, spec)
    j = int(index)
    res = m['res']
    c = _const(m)
    return {'term': _term_out(m, j, n_grid), 'intercept': float(np.asarray(res.params)[c]) if c is not None else 0.0,
            'edf': float(np.sum(res.edf)), 'aic': float(res.aic), 'bic': float(res.bic_llf), 'gcv': float(res.gcv),
            'deviance': float(res.deviance), 'alpha': [float(a) for a in m['choice']['alpha']]}


def _settings_frame(m, settings):
    """The design rows (linear part, smooth columns) of points given as
    {column name: value}; an unset column sits at its mean or first level,
    and a smooth column is kept inside the range of its data (the basis
    ends there)."""
    import patsy
    d, D = m['d'], m['D']
    n = len(settings)
    vals = {}
    for name in m['spec']['linear']:
        a = d.alias[name]
        if a in d.categorical:
            lv = d.levels[a]
            vals[name] = [lv[_level_index(lv, s.get(name))] if s.get(name) is not None else lv[0] for s in settings]
        else:
            mean = float(d.df[a].mean())
            vals[name] = [float(s[name]) if s.get(name) is not None else mean for s in settings]
    frame = d.frame_for(vals) if vals else pd.DataFrame(index=range(n))
    Xl = np.asarray(patsy.build_design_matrices([D['di']], frame, return_type='dataframe')[0], dtype=float) if m['spec']['linear'] else np.ones((n, 1))
    xs = np.empty((n, len(m['spec']['smooth'])))
    for j, name in enumerate(m['spec']['smooth']):
        x = D['xs'][:, j]
        lo, hi, mean = float(np.min(x)), float(np.max(x)), float(np.mean(x))
        for i, s in enumerate(settings):
            v = s.get(name)
            v = mean if v is None else float(v)
            xs[i, j] = min(max(v, lo), hi)
    return Xl, xs


def _level_index(levels, v):
    for i, lv in enumerate(levels):
        if lv == v or _lvl(lv) == _lvl(v) or str(lv) == str(v):
            return i
    return 0


def _predict(m, settings, alpha):
    """The mean with its confidence interval, statsmodels' get_prediction
    (the interval of the linear predictor through the inverse link)."""
    Xl, xs = _settings_frame(m, settings)
    pr = m['res'].get_prediction(exog=Xl, exog_smooth=xs)
    sf = pr.summary_frame(alpha=alpha)
    return sf['mean'].to_numpy(float), sf['mean_ci_lower'].to_numpy(float), sf['mean_ci_upper'].to_numpy(float)


def _predictor(table, rows=None, alpha=0.05, **model):
    """The profiler's view of the fitted GAM (see profile.py): the mean on
    the response scale with its confidence limits (get_prediction)."""
    spec = _spec(**model)
    m = _model(table, rows, spec)
    facs = _factors(m)
    info = m['D']['info']
    if spec['family'] != 'binomial':
        name = spec['y']
    elif info.get('levels') is not None:
        name = f'Prob[{_lvl(info["event"])}]'
    else:
        name = f'Prob[{spec["y"]} = 1]'

    def run(settings):
        mu, lo, hi = _predict(m, settings, alpha)
        return [{'name': name, 'pred': mu, 'lower': lo, 'upper': hi, 'bounded': spec['family'] == 'binomial'}]
    D, d = m['D'], m['d']
    observed = {n: D['xs'][:, j].tolist() for j, n in enumerate(spec['smooth'])}
    for n in spec['linear']:
        observed[n] = [None if v is None or (isinstance(v, float) and math.isnan(v)) else (v.item() if hasattr(v, 'item') else v) for v in d.df[d.alias[n]].astype(object)]
    return profile_mod.Predictor(facs, run, observed)


# gam.profile (the traces), gam.maximize and gam.importance, as every profiled model
profile_mod.expose('gam', _predictor, alpha=True)


@api('gam.surface')
def surface(table, first=0, second=1, rows=None, n=40, **model):
    """The sum of two smooth terms' partial effects on a grid (link scale)."""
    spec = _spec(**model)
    m = _model(table, rows, spec)
    k = len(spec['smooth'])
    a, b = int(first), int(second)
    if not (0 <= a < k and 0 <= b < k) or a == b:
        raise ValueError('choose two different smooth terms')
    D = m['D']
    ga, gb = _grid(D['xs'][:, a], int(n)), _grid(D['xs'][:, b], int(n))
    fa, _, _ = _curve(m, a, ga)
    fb, _, _ = _curve(m, b, gb)
    z = fb[:, None] + fa[None, :]
    first_rows = D['first']
    return {'x': ga, 'y': gb, 'z': z, 'xname': spec['smooth'][a], 'yname': spec['smooth'][b],
            'points': {'x': D['xs'][first_rows, a], 'y': D['xs'][first_rows, b], 'rows': [int(r) for r in D['rows']]}}


@api('gam.compare')
def compare(table, rows=None, alpha=0.05, table_name='data', **model):
    """The same model with every smooth column as a linear term: a GLM of
    the same family and link, fitted to the same rows."""
    import statsmodels.api as sm
    spec = _spec(**model)
    m = _model(table, rows, spec)
    D, res = m['D'], m['res']
    Xg = np.column_stack([D['X'], D['xs']])
    kw = {'var_weights': D['vw']} if D['vw'] is not None else {}
    g = sm.GLM(D['y'], Xg, family=_family(spec['family'], spec['link']), **kw).fit()
    p = int(np.linalg.matrix_rank(Xg))
    edf = float(np.sum(res.edf))
    dd = float(g.deviance - res.deviance)
    ddf = edf - p
    known = spec['family'] in ('binomial', 'poisson')
    phi = float(res.scale)
    test = {'ddev': dd, 'ddf': ddf}
    if ddf > 1e-6:
        if known:
            test.update({'stat': dd, 'label': 'L-R ChiSquare', 'p': float(stats.chi2.sf(max(dd, 0.0), ddf))})
        else:
            fr = (dd / ddf) / phi
            test.update({'stat': fr, 'label': 'F Ratio', 'p': float(stats.f.sf(max(fr, 0.0), ddf, float(res.df_resid)))})
    models_rows = [{'model': 'Linear (GLM)', 'df': float(p), 'deviance': float(g.deviance), 'aic': float(g.aic), 'bic': float(g.bic_llf)},
                   {'model': 'Additive (GAM)', 'df': edf, 'deviance': float(res.deviance), 'aic': float(res.aic), 'bic': float(res.bic_llf)}]
    names = m['D']['X_names'] + spec['smooth']
    lin = [{'term': m['d'].label(nm) if i < len(m['D']['X_names']) else nm, 'estimate': float(np.asarray(g.params)[i]), 'se': float(np.asarray(g.bse)[i])}
           for i, nm in enumerate(names)]
    wkw = f', var_weights=d[{json.dumps(spec["weight"])}].to_numpy(float)' if spec['weight'] else ''
    code = _code(m, table_name, rows).split('\nmodel = GLMGam(y, exog=X, smoother=smoother, alpha=list(alpha)')[0]
    code += ('\nres = GLMGam(y, exog=X, smoother=smoother, alpha=list(alpha), family=fam' + wkw + ').fit(' +
             (f'weights=d[{json.dumps(spec["weight"])}].to_numpy(float)' if spec['weight'] else '') + ')' +
             f'\nglm = sm.GLM(y, np.column_stack([X, xs]), family=fam{wkw}).fit()   # the smooth columns as linear terms' +
             '\nprint(glm.deviance, res.deviance, glm.aic, res.aic)' +
             '\nddev, ddf = glm.deviance - res.deviance, res.edf.sum() - np.linalg.matrix_rank(np.column_stack([X, xs]))' +
             ('\nprint(ddev, ddf, stats.chi2.sf(ddev, ddf))' if known else '\nprint((ddev / ddf) / res.scale, stats.f.sf((ddev / ddf) / res.scale, ddf, res.df_resid))'))
    code = code.replace('import patsy\n', 'import patsy\nfrom scipy import stats\n', 1)
    return {'models': models_rows, 'test': test, 'known_scale': known, 'linear': lin, 'code': code,
            'notes': ['Both models are fitted to the same rows. The test is approximate: the additive model is penalized, so the two are not '
                      'nested in the usual sense, and its degrees of freedom (the EDF) are not whole numbers (as mgcv\'s anova.gam).']}


# ---------------------------------------------------------------------------
# the graphs as matplotlib code
# ---------------------------------------------------------------------------
# Under each graph the report shows Python that draws it with matplotlib from
# a CSV export of the table (the notebook runs it): the report's rows, the
# model fitted as the report fits it (its penalty search included), the light
# theme's colours, the graph's size at 100 pixels an inch. The page sends
# what it chose (a term's band, residuals, rug and intercept; the surface's
# two terms); gam.plot_code writes the code of one graph. The Prediction
# Profiler is interactive and has none.
FIT, BAND, POINT, MUTED, GRID = '#c0392b', '#c0392b', '#2f6690', '#786b5d', '#e0d7ce'
PX = 0.72   # points per pixel: a figure at 100 pixels an inch


def _pt(px):
    return f'{px * PX:.3g}'


def _area(px):
    return f'{(px * PX) ** 2:.3g}'


def _first_line(spec):
    if spec['freq']:
        return 'first = ~d.index.duplicated()   # each row once (the fit repeats a row Freq times)'
    return 'first = np.ones(len(d), dtype=bool)'


def _term_code(m, table_name, rows, plot, alpha):
    spec = m['spec']
    j = int(plot.get('index') or 0)
    name = spec['smooth'][j]
    band = plot.get('band', True) is not False
    resid = bool(plot.get('resid', spec['family'] != 'binomial'))
    rug = bool(plot.get('rug', m['D']['n_rows'] <= 4000))
    const = bool(plot.get('constant')) and _const(m) is not None
    n = m['D']['n_rows']
    c = _fit_lines(m, table_name, rows, ['import matplotlib.pyplot as plt', 'from scipy import stats'])
    c += [_first_line(spec),
          f'j = {j}   # the term s({name})',
          'idx = model.k_exog_linear + np.nonzero(smoother.mask[j])[0]   # its coefficients',
          'b, V = np.asarray(res.params), np.asarray(res.cov_params())   # the penalized (Bayesian) covariance',
          'x = xs[:, j]',
          'g = np.linspace(x.min(), x.max(), 101)',
          'B = smoother.smoothers[j].transform(g)',
          'f = B @ b[idx]   # the partial effect, centred',
          'se = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", B, V[np.ix_(idx, idx)], B), 0))']
    if const:
        c += ['ic = np.r_[list(X.columns).index("Intercept"), idx]   # Include Intercept: the curve about the intercept, its standard error with it',
              'Bc = np.column_stack([np.ones(len(g)), B])',
              'se = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", Bc, V[np.ix_(ic, ic)], Bc), 0))',
              'c = b[ic[0]]']
    else:
        c.append('c = 0.0')
    c += [f'z = stats.norm.ppf({1 - alpha / 2!r})',
          'fig, ax = plt.subplots(figsize=(3.8, 2.8), layout="constrained")']
    if band:
        c.append(f'ax.fill_between(g, c + f - z * se, c + f + z * se, color="{BAND}", alpha=0.13, linewidth=0)   # the pointwise {100 * (1 - alpha):g}% band')
    if resid:
        c += ['B1 = smoother.smoothers[j].transform(x[first])',
              f'ax.scatter(x[first], c + B1 @ b[idx] + np.asarray(res.resid_working)[first], s={_area(4 if n > 500 else 5)}, color="{POINT}", alpha=0.75, label="Partial residuals")   # the term plus the working residual']
    c.append(f'ax.plot(g, c + f, color="{FIT}", linewidth={_pt(2)})   # s({name})')
    if rug:
        c.append(f'ax.plot(x[first], np.full(first.sum(), 0.035), linestyle="none", marker="|", markersize={_pt(9)}, color="{MUTED}", transform=ax.get_xaxis_transform())   # the rug')
    c += [f'ax.axhline(0, color="{GRID}", linewidth={_pt(1)})',
          f'ax.set_xlabel({json.dumps(name)})', f'ax.set_ylabel({json.dumps(f"Intercept + s({name})" if const else f"s({name})")})',
          f'ax.set_title({json.dumps(f"{name} partial effect")})', 'plt.show()']
    return '\n'.join(c)


def _diag_head(m, table_name, rows, imports=()):
    spec = m['spec']
    c = _fit_lines(m, table_name, rows, ['import matplotlib.pyplot as plt', *imports])
    c += [_first_line(spec), 'mu = np.asarray(res.fittedvalues)[first]   # the predicted mean']
    return c


def _diag_code(m, table_name, rows, kind):
    spec = m['spec']
    yname = spec['y']
    info = m['D']['info']
    n = m['D']['n_rows']
    s = _area(4 if n > 500 else 6)
    if kind == 'actual':
        c = _diag_head(m, table_name, rows) + ['yy = y[first]']
        ylab = f'{yname} ({_lvl(info["event"])} = 1)' if info.get('levels') is not None else f'{yname} Actual'
        c += ['lo, hi = min(mu.min(), yy.min()), max(mu.max(), yy.max())',
              'fig, ax = plt.subplots(figsize=(3.8, 3.0), layout="constrained")',
              f'ax.scatter(mu, yy, s={s}, color="{POINT}")',
              f'ax.plot([lo, hi], [lo, hi], color="{FIT}", linewidth={_pt(1.4)})   # actual = predicted',
              f'ax.set_xlabel({json.dumps(f"{yname} Predicted")})', f'ax.set_ylabel({json.dumps(ylab)})', f'ax.set_title({json.dumps(f"{yname} actual by predicted")})']
    elif kind == 'residual':
        c = _diag_head(m, table_name, rows)
        c += ['fig, ax = plt.subplots(figsize=(3.8, 3.0), layout="constrained")',
              f'ax.scatter(mu, y[first] - mu, s={s}, color="{POINT}")',
              f'ax.axhline(0, color="{POINT}", linewidth={_pt(1)})',
              f'ax.set_xlabel({json.dumps(f"{yname} Predicted")})', f'ax.set_ylabel({json.dumps(f"{yname} Residual")})', f'ax.set_title({json.dumps(f"{yname} residual by predicted")})']
    else:
        c = _diag_head(m, table_name, rows, ['from scipy import stats'])
        c += ['r = np.asarray(res.resid_deviance)[first]',
              'z = stats.norm.ppf(stats.rankdata(r) / (len(r) + 1))   # Φ⁻¹(rank/(n+1)), ties by their average rank',
              'o = np.argsort(r, kind="stable")',
              'mr, sr = r.mean(), r.std(ddof=1)',
              'fig, ax = plt.subplots(figsize=(3.6, 2.9), layout="constrained")',
              f'ax.scatter(z[o], r[o], s={s}, color="{POINT}")',
              f'ax.plot([z.min(), z.max()], [mr + sr * z.min(), mr + sr * z.max()], color="{FIT}", linewidth={_pt(1.3)})   # the residuals\' mean and standard deviation',
              'ax.set_xlabel("Normal Quantile")', 'ax.set_ylabel("Deviance Residual")', f'ax.set_title({json.dumps(f"{yname} deviance residual normal quantile plot")})']
    return '\n'.join(c + ['plt.show()'])


LEVELS_LINES = ['def plotly_levels(z, n=15):   # the contour levels the page shows: Plotly\'s own, a round step (2, 5 or 10 times a power of ten) of about (max − min)/15',
                '    lo, hi = np.nanmin(z), np.nanmax(z)',
                '    rough = (hi - lo) / n',
                '    base = 10.0 ** np.floor(np.log10(rough))',
                '    step = base * min(v for v in (2, 5, 10) if v >= rough / base)',
                '    start, end = np.ceil(lo / step) * step, np.floor(hi / step) * step',
                '    start, end = (start + step if start == lo else start), (end - step if end == hi else end)',
                '    return np.arange(start, end + step / 2, step)']


def _surface_code(m, table_name, rows, plot):
    spec = m['spec']
    a, b = int(plot.get('first') or 0), int(plot.get('second') or 1)
    na, nb = spec['smooth'][a], spec['smooth'][b]
    ng = int(plot.get('n') or 40)
    c = _fit_lines(m, table_name, rows, ['import matplotlib.pyplot as plt'])
    c += [_first_line(spec), ''] + LEVELS_LINES + ['',
          'def partial(j, v):   # the partial effect of term j at the values v, centred',
          '    return smoother.smoothers[j].transform(v) @ np.asarray(res.params)[model.k_exog_linear + np.nonzero(smoother.mask[j])[0]]',
          f'a, b = {a}, {b}   # s({na}) across, s({nb}) up',
          f'ga, gb = np.linspace(xs[:, a].min(), xs[:, a].max(), {ng}), np.linspace(xs[:, b].min(), xs[:, b].max(), {ng})',
          'z = partial(b, gb)[:, None] + partial(a, ga)[None, :]   # an additive model: the two curves added',
          'fig, ax = plt.subplots(figsize=(4.7, 3.8), layout="constrained")',
          'mesh = ax.pcolormesh(ga, gb, z, cmap="viridis", shading="gouraud")',
          f'lines = ax.contour(ga, gb, z, levels=plotly_levels(z), colors="#444444", linewidths={_pt(0.5)})',
          f'ax.clabel(lines, fontsize={_pt(9)}, colors="white")',
          f'ax.scatter(xs[first, a], xs[first, b], s={_area(5)}, color=(1, 1, 1, 0.85), edgecolors="#222222", linewidths={_pt(1)})   # the rows',
          f'fig.colorbar(mesh, ax=ax, label={json.dumps(f"s({na}) + s({nb})")})',
          f'ax.set_xlabel({json.dumps(na)})', f'ax.set_ylabel({json.dumps(nb)})', f'ax.set_title({json.dumps(f"{na} and {nb} surface")})', 'plt.show()']
    return '\n'.join(c)


@api('gam.plot_code')
def plot_code(table, kind='term', plot=None, rows=None, alpha=0.05, table_name='data', **model):
    """The Python that draws one of the report's graphs with matplotlib (kind:
    term, actual, residual, devqq, surface), the model fitted as the report
    fits it, from what the page chose (plot)."""
    spec = _spec(**model)
    m = _model(table, rows, spec)
    plot = plot or {}
    if kind == 'term':
        code = _term_code(m, table_name, rows, plot, alpha)
    elif kind in ('actual', 'residual', 'devqq'):
        code = _diag_code(m, table_name, rows, kind)
    elif kind == 'surface':
        code = _surface_code(m, table_name, rows, plot)
    else:
        raise ValueError(f'no graph {kind!r}')
    return {'plot_code': code}
