"""Analyze > Specialized Modeling > Count Regression: regression models for
counts, compared with each other, with rootograms.

The models, all statsmodels 0.14:

  poisson  Poisson                             discrete_model.Poisson
  nb2      Negative Binomial (NB2)             discrete_model.NegativeBinomial, loglike_method 'nb2':
                                               Var = mu + alpha mu^2 (JMP's negative binomial, alpha its sigma)
  nb1      Negative Binomial (NB1)             the same, 'nb1': Var = mu (1 + alpha)
  gp       Generalized Poisson                 discrete_model.GeneralizedPoisson, p = 1: Var = mu (1 + alpha)^2
  zip      Zero-Inflated Poisson               count_model.ZeroInflatedPoisson, inflation 'logit'
  zinb     Zero-Inflated Negative Binomial     count_model.ZeroInflatedNegativeBinomialP, p = 2
  zigp     Zero-Inflated Generalized Poisson   count_model.ZeroInflatedGeneralizedPoisson, p = 1
  hp, hnb  Hurdle Poisson, Negative Binomial   the two parts truncated_model.HurdleCountModel fits
                                               (a censored Poisson for P(Y > 0), which is a binomial GLM
                                               with the complementary log-log link, and TruncatedLFPoisson
                                               or TruncatedLFNegativeBinomialP for Y > 0), fitted here as
                                               two statsmodels models so that an exposure and zero
                                               effects of their own work (HurdleCountModel 0.14 takes
                                               neither); without them the numbers are HurdleCountModel's.

The names the page calls:

  counts.fit         one model: estimates by part, Wald effect tests, rate and odds ratios, the rows
                     (mean, P(Y = 0), Pearson and randomized quantile residuals), the expected count
                     frequencies, Poisson dispersion and zero-inflation tests
  counts.compare     the fitted models side by side: k, -2LL, AIC, AICc, BIC, zeros, dispersion;
                     likelihood-ratio tests of the nested pairs, Vuong tests of the others
  counts.lr_effects  likelihood-ratio effect tests, by refitting without each effect
  counts.margeff     statsmodels' get_margeff (Poisson, negative binomial, generalized Poisson)
  counts.profile     the Prediction Profiler: E[Y] and P(Y = 0) as each factor moves

The count probabilities, means and variances are computed here from the
fitted parameters (scipy's Poisson and negative binomial, the generalized
Poisson as statsmodels' log-likelihood writes it, mixed with the zero part),
because statsmodels 0.14's own predict(which='prob') of the zero-inflated
models needs a scipy function that scipy 1.15 removed. The tests check them
against statsmodels: the log-probabilities of the data sum to its llf, the
means and variances are its predict(which='mean' | 'var').

Designs are models.build's (JMP's effect coding and term names); a Freq
column repeats its rows for the fit (statsmodels' count models take no
weights). Fits are kept in a cache of this module's own, keyed by
everything that defines them, so comparisons, profilers and effect tests
reuse them; a forgotten fit is refitted.

Fitting. Each fit tries statsmodels' optimisers in turn (Newton, BFGS,
Nelder-Mead then BFGS) and keeps the first that converges, with a few Newton
steps after BFGS for the last digits; a fit that ends below where it started
is thrown away. The models with a dispersion alpha start from the model they
contain at alpha = 0 (the Poisson, the ZIP, the truncated Poisson), with
alpha from the sibling model (the NB2 for ZINB and the hurdle NB, the GP for
ZIGP) and with a constant, and keep the better: the ZINB likelihood of the
RAND data has a second maximum at pi -> 0 that a single start falls into.
When alpha goes below 1e-6, or the fit has no more log-likelihood than the
contained model, alpha is at its bound 0 and the report is that model's
(the negative binomial's log-likelihood is numerical noise so near 0). The
plan that won (steps and start) is kept, and the code under the report
repeats it.
"""
import hashlib
import json
import math
import warnings
from collections import OrderedDict

import numpy as np
import pandas as pd
from scipy import optimize, special, stats

from . import data, models
from .registry import api
from .util import code_head, col, table as rtable

ORDER = ['poisson', 'nb2', 'nb1', 'gp', 'zip', 'zinb', 'zigp', 'hp', 'hnb']
LABEL = {'poisson': 'Poisson', 'nb2': 'Negative Binomial (NB2)', 'nb1': 'Negative Binomial (NB1)', 'gp': 'Generalized Poisson',
         'zip': 'Zero-Inflated Poisson', 'zinb': 'Zero-Inflated Negative Binomial', 'zigp': 'Zero-Inflated Generalized Poisson',
         'hp': 'Hurdle Poisson', 'hnb': 'Hurdle Negative Binomial'}
SHORT = {'poisson': 'Poisson', 'nb2': 'NB2', 'nb1': 'NB1', 'gp': 'GP', 'zip': 'ZIP', 'zinb': 'ZINB', 'zigp': 'ZIGP', 'hp': 'Hurdle P', 'hnb': 'Hurdle NB'}
FAMILY = {'poisson': 'poisson', 'nb2': 'nb', 'nb1': 'nb', 'gp': 'gp', 'zip': 'poisson', 'zinb': 'nb', 'zigp': 'gp', 'hp': 'poisson', 'hnb': 'nb'}
P_OF = {'nb2': 2, 'nb1': 1, 'gp': 1, 'zinb': 2, 'zigp': 1, 'hnb': 2}
ZERO = {'zip': 'zi', 'zinb': 'zi', 'zigp': 'zi', 'hp': 'hurdle', 'hnb': 'hurdle'}
BASE = {'nb2': 'poisson', 'nb1': 'poisson', 'zinb': 'zip', 'hnb': 'hp'}   # the model at alpha = 0 (a boundary)
KMAX = 100          # the count distribution shows 0..KMAX, the last bin holding the rest
VARIANCE = {'poisson': 'Var(Y) = μ', 'nb2': 'Var(Y) = μ + αμ²', 'nb1': 'Var(Y) = μ(1 + α)', 'gp': 'Var(Y) = μ(1 + α)²',
            'zip': 'Var(Y) = (1 − π)λ(1 + πλ)', 'zinb': 'the count part: Var = λ + αλ²', 'zigp': 'the count part: Var = λ(1 + α)²',
            'hp': 'the count part: a zero-truncated Poisson', 'hnb': 'the count part: a zero-truncated NB2, Var = λ + αλ² before truncation'}


# ---------------------------------------------------------------------------
# the cache
# ---------------------------------------------------------------------------

_CACHE = OrderedDict()
_KEEP = 60


def _cache_get(key):
    v = _CACHE.get(key)
    if v is not None:
        _CACHE.move_to_end(key)
    return v


def _cache_put(key, value):
    _CACHE[key] = value
    _CACHE.move_to_end(key)
    while len(_CACHE) > _KEEP:
        _CACHE.popitem(last=False)
    return value


def _rows_sig(rows):
    if rows is None:
        return 'all'
    a = np.asarray(rows, dtype=np.int64)
    return f'{len(a)}:{hashlib.blake2b(a.tobytes(), digest_size=10).hexdigest()}'


def _spec(y=None, x=(), degree=1, zx=(), zero_same=True, exposure=None, offset=None, freq=None, **_ignored):
    """Everything that defines the data of a fit, as a plain dict."""
    return {'y': y, 'x': [str(c) for c in (x or [])], 'degree': int(degree or 1), 'zx': [str(c) for c in (zx or [])],
            'zero_same': bool(zero_same), 'exposure': exposure or None, 'offset': offset or None, 'freq': freq or None}


def _key(kind, tid, rows, spec, *more):
    return json.dumps([kind, tid, data.version(tid), _rows_sig(rows), spec, *more], sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# the data of an analysis: designs, response, offset, frequencies
# ---------------------------------------------------------------------------

def _attach(d, di):
    """Which design columns belong to which effect."""
    for e in d.effects:
        e['terms'] = []
    for term, sl in di.term_name_slices.items():
        cols = di.column_names[sl]
        for e in d.effects:
            if models._same_term(term, e['term']):
                e['terms'] = list(cols)
    return d


def _design(d):
    import patsy
    X = patsy.dmatrix(d.rhs, d.df, return_type='dataframe', NA_action='raise')
    _attach(d, X.design_info)
    return X


def _effects_of(names, degree):
    if not names:
        return []
    return models.full_factorial(list(names), None if degree >= len(names) else max(1, degree))


def _prep(tid, rows, spec):
    key = _key('prep', tid, rows, spec)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    y = spec['y']
    if not y:
        raise ValueError('choose a Y, Count column')
    if spec['exposure'] and spec['offset']:
        raise ValueError('give an Exposure or an Offset, not both')
    effects = _effects_of(spec['x'], spec['degree'])
    if spec['zx']:
        zeffects = [[c] for c in spec['zx']]
    elif spec['zero_same']:
        zeffects = effects
    else:
        zeffects = []
    if y in spec['x'] or y in spec['zx']:
        raise ValueError(f'{y} is the Y and an effect: take it out of the effects')
    extra = list(dict.fromkeys([c for c in [*spec['x'], *spec['zx'], spec['exposure'], spec['offset']] if c]))
    d = models.build(tid, y, effects, rows, None, spec['freq'], extra=extra)
    if len(d.df) == 0:
        raise ValueError('no rows to fit: every row has a missing value in a column of the model, or is excluded')
    same = zeffects == effects
    dz = d if same else models.build(tid, y, zeffects, rows, None, spec['freq'], extra=extra)
    if list(dz.df.index) != list(d.df.index):
        raise ValueError('the zero part and the count part do not have the same rows')
    idx = d.df.index.to_numpy()
    yv = data.series(tid, y, idx, as_category=False).to_numpy(float)
    bad = ~np.isfinite(yv) | (yv < 0) | (np.abs(yv - np.round(yv)) > 1e-9)
    if bad.any():
        r = int(idx[np.argmax(bad)]) + 1
        raise ValueError(f'{y} must hold counts, whole numbers of zero or more: row {r} has {data.series(tid, y, [idx[np.argmax(bad)]], as_category=False).iloc[0]:g}')
    yv = np.round(yv)
    expo = off = None
    if spec['exposure']:
        expo = data.series(tid, spec['exposure'], idx, as_category=False).to_numpy(float)
        if np.any(~np.isfinite(expo) | (expo <= 0)):
            raise ValueError(f'the exposure {spec["exposure"]} must be above zero in every row (it is logged)')
    if spec['offset']:
        off = data.series(tid, spec['offset'], idx, as_category=False).to_numpy(float)
        if np.any(~np.isfinite(off)):
            raise ValueError(f'the offset {spec["offset"]} has a value that is not a number')
    f = None
    if spec['freq']:
        f = np.asarray(d.weights, dtype=float)
        if np.any(np.abs(f - np.round(f)) > 1e-9):
            raise ValueError(f'Freq ({spec["freq"]}) must hold whole numbers: each row counts that many times')
        f = np.round(f).astype(int)
    X = _design(d)
    Z = X if same else _design(dz)
    for M, part in ((X, 'count'), (Z, 'zero')):
        if M.shape[1] and np.linalg.matrix_rank(M.to_numpy(float)) < M.shape[1]:
            raise ValueError(f'the {part} part of the model is singular: its effects are collinear (or a factor has a level with no rows); remove an effect')
    rep = np.repeat(np.arange(len(idx)), f) if f is not None else None
    P = {'tid': tid, 'rows': rows, 'spec': spec, 'd': d, 'dz': dz, 'same': same, 'X': X, 'Z': Z, 'idx': idx, 'y': yv,
         'expo': expo, 'off': off, 'f': f, 'rep': rep, 'n': float(np.sum(f)) if f is not None else float(len(yv)),
         'effects': effects, 'zeffects': zeffects, 'key': key}
    return _cache_put(key, P)


def _logoff(P):
    """The offset on the linear predictor's scale, per row (log exposure or the offset)."""
    if P['expo'] is not None:
        return np.log(P['expo'])
    if P['off'] is not None:
        return P['off']
    return np.zeros(len(P['y']))


def _expanded(P):
    """The arrays of the fit: the rows repeated by Freq."""
    r = P['rep']
    X, Z = P['X'].to_numpy(float), P['Z'].to_numpy(float)
    y, expo, off = P['y'], P['expo'], P['off']
    if r is not None:
        X, Z, y = X[r], Z[r], y[r]
        expo = expo[r] if expo is not None else None
        off = off[r] if off is not None else None
    kw = {}
    if expo is not None:
        kw['exposure'] = expo
    if off is not None:
        kw['offset'] = off
    return y, X, Z, kw


# ---------------------------------------------------------------------------
# the fitted distributions
# ---------------------------------------------------------------------------

def _base_logpmf(fam, p, alpha, lam, k):
    if fam == 'poisson' or (fam == 'nb' and not alpha > 0):
        return stats.poisson.logpmf(k, lam)
    if fam == 'nb':
        size = lam ** (2 - p) / alpha
        return stats.nbinom.logpmf(k, size, size / (size + lam))
    # the generalized Poisson as statsmodels' GeneralizedPoisson.loglikeobs writes it
    a1 = 1 + alpha * lam ** (p - 1)
    a2 = lam + (a1 - 1) * k
    a1 = np.maximum(1e-20, a1)
    a2 = np.maximum(1e-20, a2)
    return np.log(lam) + (k - 1) * np.log(a2) - k * np.log(a1) - special.gammaln(k + 1) - a2 / a1


def _base_cdf(fam, p, alpha, lam, k):
    """P(Y <= k) of the base distribution, per row (k an array like lam)."""
    k = np.asarray(k, dtype=float)
    out = np.zeros(np.broadcast(lam, k).shape)
    ok = k >= 0
    if fam == 'poisson' or (fam == 'nb' and not alpha > 0):
        out[ok] = stats.poisson.cdf(np.broadcast_to(k, out.shape)[ok], np.broadcast_to(lam, out.shape)[ok])
        return out
    if fam == 'nb':
        lamb = np.broadcast_to(lam, out.shape)[ok]
        size = lamb ** (2 - p) / alpha
        out[ok] = stats.nbinom.cdf(np.broadcast_to(k, out.shape)[ok], size, size / (size + lamb))
        return out
    lamb = np.broadcast_to(lam, out.shape).ravel()
    kk = np.broadcast_to(k, out.shape).ravel()
    res = np.zeros(len(kk))
    top = int(np.max(kk)) if len(kk) else -1
    if top >= 0:
        j = np.arange(top + 1, dtype=float)
        for s in range(0, len(kk), 4000):
            sl = slice(s, s + 4000)
            pm = np.exp(_base_logpmf('gp', p, alpha, lamb[sl, None], j[None, :]))
            cs = np.cumsum(pm, axis=1)
            kc = kk[sl]
            good = kc >= 0
            r = np.zeros(len(kc))
            r[good] = cs[np.nonzero(good)[0], kc[good].astype(int)]
            res[sl] = r
    return res.reshape(out.shape)


def _base_var(fam, p, alpha, lam):
    if fam == 'poisson' or (fam == 'nb' and not alpha > 0):
        return lam
    if fam == 'nb':
        return lam + alpha * lam ** p
    return lam * (1 + alpha * lam ** (p - 1)) ** 2


class Dist:
    """The fitted distribution of Y in each row: a base count distribution
    (Poisson, NB-P, GP-P with mean lam) and, for zero-inflated models, a
    structural zero with probability w; for hurdle models, P(Y > 0) = w and
    the base distribution truncated at zero above it."""

    def __init__(self, fam, p, alpha, lam, zero=None, w=None):
        self.fam, self.p, self.alpha, self.lam, self.zero, self.w = fam, p, alpha, np.asarray(lam, float), zero, w

    def _col(self, v, k):
        v = np.asarray(v, float)
        return v[:, None] if np.ndim(k) == 2 and v.ndim == 1 else v

    def logpmf(self, k):
        """log P(Y = k): k per row (shape of lam) or a row of counts (1, K)."""
        lam = self._col(self.lam, k)
        lb = _base_logpmf(self.fam, self.p, self.alpha, lam, k)
        if self.zero is None:
            return lb
        w = self._col(self.w, k)
        if self.zero == 'zi':
            with np.errstate(divide='ignore'):
                return np.where(np.asarray(k) == 0, np.log(w + (1 - w) * np.exp(lb)), np.log1p(-w) + lb)
        f0 = np.exp(_base_logpmf(self.fam, self.p, self.alpha, lam, 0.0))
        with np.errstate(divide='ignore', invalid='ignore'):
            return np.where(np.asarray(k) == 0, np.log1p(-w), np.log(w) + lb - np.log1p(-f0))

    def pmf(self, k):
        return np.exp(self.logpmf(k))

    def cdf(self, k):
        """P(Y <= k), k per row."""
        k = np.asarray(k, float)
        Fb = _base_cdf(self.fam, self.p, self.alpha, self.lam, k)
        if self.zero is None:
            return Fb
        w = self.w
        if self.zero == 'zi':
            return np.where(k < 0, 0.0, w + (1 - w) * Fb)
        f0 = np.exp(_base_logpmf(self.fam, self.p, self.alpha, self.lam, 0.0))
        return np.where(k < 0, 0.0, np.where(k < 1, 1 - w, 1 - w + w * (Fb - f0) / (1 - f0)))

    def mean(self):
        lam = self.lam
        if self.zero is None:
            return lam
        if self.zero == 'zi':
            return (1 - self.w) * lam
        f0 = np.exp(_base_logpmf(self.fam, self.p, self.alpha, lam, 0.0))
        return self.w * lam / (1 - f0)

    def var(self):
        lam, V = self.lam, _base_var(self.fam, self.p, self.alpha, self.lam)
        if self.zero is None:
            return V
        m = self.mean()
        if self.zero == 'zi':
            return (1 - self.w) * (V + lam * lam) - m * m
        f0 = np.exp(_base_logpmf(self.fam, self.p, self.alpha, lam, 0.0))
        return self.w * (V + lam * lam) / (1 - f0) - m * m

    def p0(self):
        return np.exp(self.logpmf(np.zeros(len(self.lam))))


def _parts(key, kx, kz, has_alpha):
    """The slices of the parameter vector: statsmodels' order, the zero part
    first for zero-inflated and hurdle models."""
    if key not in ZERO:
        out = {'count': slice(0, kx)}
        if has_alpha:
            out['alpha'] = slice(kx, kx + 1)
        return out
    out = {'zero': slice(0, kz), 'count': slice(kz, kz + kx)}
    if has_alpha:
        out['alpha'] = slice(kz + kx, kz + kx + 1)
    return out


def _dist(m, X, Z, logoff, params=None):
    """The fitted distribution at design rows X (count part), Z (zero part)
    and offsets logoff (the log exposure or the offset)."""
    b = m['params'] if params is None else params
    parts = m['parts']
    lam = np.exp(np.clip(X @ b[parts['count']] + logoff, -700, 700))
    alpha = float(b[parts['alpha']][0]) if 'alpha' in parts else 0.0
    fam = FAMILY[m['model']] if 'alpha' in parts or FAMILY[m['model']] == 'poisson' else 'poisson'
    zero = ZERO.get(m['model'])
    w = None
    if zero == 'zi':
        w = special.expit(Z @ b[parts['zero']])
    elif zero == 'hurdle':
        w = -np.expm1(-np.exp(np.clip(Z @ b[parts['zero']] + logoff, -700, 700)))
    return Dist(fam, P_OF.get(m['model'], 2), alpha, lam, zero, w)


# ---------------------------------------------------------------------------
# fitting
# ---------------------------------------------------------------------------

def _attempt(fn):
    """Run a fit, keeping its warnings: only the warnings of the fit that is
    kept are passed on to the report (_replay); the trial steps of an
    optimiser that were thrown away are not the reader's concern, and
    numpy's overflow warnings inside a line search are not either."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        try:
            r, err = fn(), None
        except Exception as e:  # noqa: BLE001 - reported to the page
            r, err = None, e
    return r, [w for w in caught if issubclass(w.category, UserWarning)], err


def _replay(caught):
    seen = set()
    for w in caught:
        t = (w.category, str(w.message))
        if t not in seen:
            seen.add(t)
            warnings.warn(str(w.message), w.category, stacklevel=2)


def _finite_fit(r, alpha_pos=False):
    if r is None:
        return False
    try:
        llf = float(r.llf)
        p = np.asarray(r.params, dtype=float)
    except Exception:  # noqa: BLE001
        return False
    if not (np.isfinite(llf) and np.all(np.isfinite(p))):
        return False
    return not alpha_pos or p[-1] > 0


def _converged(r):
    return bool((getattr(r, 'mle_retvals', None) or {}).get('converged', True))


# The optimiser steps of a fit, as statsmodels' fit() takes them.
STEPS = {'newton': {'method': 'newton', 'maxiter': 100}, 'bfgs': {'method': 'bfgs', 'maxiter': 1000, 'gtol': 1e-8},
         'nm': {'method': 'nm', 'maxiter': 20000}, 'polish': {'method': 'newton', 'maxiter': 50}}


def _run(mod, start, plan):
    """The steps of a plan, each from where the last one ended; the warnings
    of the last step."""
    p, r, caught = start, None, []
    for s in plan:
        r, caught, e = _attempt(lambda: mod.fit(start_params=p, disp=0, **STEPS[s]))
        if e is not None:
            return None, caught, e
        p = np.asarray(r.params, dtype=float)
    return r, caught, None


def _fit_plans(mod, start, plans, alpha_pos=False):
    """Try the plans in order and keep the first that converges (a Newton
    polish after BFGS when it is no worse and stays near), else the best
    finite one. A fit that ends below its start is thrown away: an optimiser
    that went astray. Returns (results, warnings, plan) or (None, [], None)."""
    l0 = -np.inf
    if start is not None:
        with np.errstate(all='ignore'):
            try:
                l0 = float(mod.loglike(np.asarray(start, float)))
            except Exception:  # noqa: BLE001
                l0 = -np.inf
        l0 = l0 if np.isfinite(l0) else -np.inf
    fallback = None
    for plan in plans:
        r, w, e = _run(mod, start, plan)
        if e is not None or not _finite_fit(r, alpha_pos) or float(r.llf) < l0 - 1e-7 * max(1.0, abs(l0)):
            continue
        if _converged(r):
            if plan[-1] in ('bfgs', 'nm'):
                r2, w2, e2 = _run(mod, np.asarray(r.params, float), ['polish'])
                if e2 is None and _finite_fit(r2, alpha_pos) and _converged(r2) and float(r2.llf) >= float(r.llf) - 1e-9:
                    p1, p2 = np.asarray(r.params, float), np.asarray(r2.params, float)
                    if np.all(np.abs(p2 - p1) <= 1e-3 * np.maximum(1, np.abs(p1))):
                        return r2, w2, list(plan) + ['polish']
            return r, w, list(plan)
        if fallback is None or float(r.llf) > float(fallback[0].llf):
            fallback = (r, w, list(plan))
    return fallback if fallback else (None, [], None)


PLANS = [['newton'], ['bfgs'], ['nm', 'bfgs']]
PLANS_BFGS = [['bfgs'], ['newton'], ['nm', 'bfgs']]
ALPHA_MIN = 1e-6    # below it alpha is at its bound 0: the model is the one it contains (the NB's log-likelihood is noise there)


def _log_alpha_mle(mod, start):
    """Maximise the model's log-likelihood over log(alpha) instead of alpha
    (the last parameter), where statsmodels' own fits step into alpha < 0
    and fail: to tell an interior optimum from alpha at its bound 0."""
    def unpack(u):
        v = np.array(u, dtype=float)
        v[-1] = math.exp(min(u[-1], 50))
        return v

    def f(u):
        with np.errstate(all='ignore'):
            v = mod.loglike(unpack(u))
        return -v if np.isfinite(v) else 1e300

    def g(u):
        p = unpack(u)
        with np.errstate(all='ignore'):
            s = np.array(mod.score(p), dtype=float)
        s[-1] *= p[-1]
        return -s if np.all(np.isfinite(s)) else np.zeros(len(s))

    u0 = np.array(start, dtype=float)
    u0[-1] = math.log(max(float(start[-1]), 1e-3))
    r = optimize.minimize(f, u0, jac=g, method='BFGS', options={'maxiter': 3000, 'gtol': 1e-7})
    return unpack(r.x)


def _alpha_fit(mod, starts, plans, base_llf=None, positive=True):
    """A model with a dispersion alpha (the last parameter) that contains a
    simpler model at alpha = 0: from each start in turn, keep the best fit
    that converged. With positive (the negative binomials, alpha > 0): when
    none reaches an interior alpha with more log-likelihood than the simpler
    model, the maximum over log(alpha) decides, and failing that alpha is at
    its bound 0. Returns (results, warnings, plan, start index, restart, boundary)."""
    best = None
    for i, (_label, s) in enumerate(starts):
        r, w, plan = _fit_plans(mod, s, plans, alpha_pos=positive)
        if r is None:
            continue
        ok = _converged(r) and (not positive or float(np.asarray(r.params)[-1]) > ALPHA_MIN)
        cand = (ok, float(r.llf), i, r, w, plan)
        if best is None or (cand[0], cand[1]) > (best[0], best[1]):
            best = cand
    tol = 1e-8 * max(1.0, abs(base_llf)) if base_llf is not None else 0.0
    if best is not None and best[0] and (base_llf is None or best[1] > base_llf + tol):
        return best[3], best[4], best[5], best[2], None, False
    if not positive:
        return (best[3], best[4], best[5], best[2], None, False) if best is not None else (None, [], None, None, None, False)
    p_ = _log_alpha_mle(mod, starts[0][1])
    if p_[-1] > ALPHA_MIN:
        r2, w2, plan2 = _fit_plans(mod, p_, [['bfgs'], ['newton']], alpha_pos=True)
        if r2 is not None and _converged(r2) and (base_llf is None or float(r2.llf) > base_llf + tol):
            return r2, w2, plan2, None, p_, False
    return None, [], None, None, None, True


def _starts(base_params, alpha_hint, const):
    """Starting values: the contained model's estimates with alpha from the
    sibling model (NB2 or GP) and with a constant alpha."""
    out = []
    if alpha_hint is not None and np.isfinite(alpha_hint):
        out.append(('hint', np.append(base_params, alpha_hint)))
    if not out or abs(out[0][1][-1] - const) > 1e-6:
        out.append(('const', np.append(base_params, const)))
    return out


def _fit_core(key, y, X, Z, kw, start=None, hints=None):
    """Fit one model to arrays; the result as a plain dict. start: starting
    values from the full model (the reduced fits of the effect tests).
    hints (from _get): 'base', the fit of the model this one contains at
    alpha = 0 (the Poisson for NB and GP, the ZIP for ZINB and ZIGP); 'alpha',
    alpha of the sibling model (the NB2's for ZINB and the hurdle NB, the
    GP's for ZIGP), a start. The plan of each fit (the optimiser steps and
    where they started) is kept for the code under the report."""
    import statsmodels.api as sm
    from statsmodels.discrete.count_model import ZeroInflatedGeneralizedPoisson, ZeroInflatedNegativeBinomialP, ZeroInflatedPoisson
    from statsmodels.discrete.discrete_model import GeneralizedPoisson, NegativeBinomial, Poisson
    from statsmodels.discrete.truncated_model import TruncatedLFNegativeBinomialP, TruncatedLFPoisson
    hints = hints or {}
    base = hints.get('base')
    fam, zero = FAMILY[key], ZERO.get(key)
    out = {'model': key, 'boundary': None, 'notes': [], 'warnings': [], 'plan': None, 'start': None}
    kx, kz = X.shape[1], Z.shape[1]
    restart_note = 'statsmodels\' fit stepped to α ≤ 0; it was restarted from the maximum of the likelihood over log α.'

    def need(r, what='the fit'):
        if r is None:
            raise ValueError(f'{what} did not reach a finite log-likelihood')
        return r

    if zero is None:
        if key == 'poisson':
            r, w, plan = _fit_plans(Poisson(y, X, **kw), start, PLANS)
            out.update(res=need(r), plan=plan)
        elif key in ('nb2', 'nb1'):
            # statsmodels' NegativeBinomial searches over log(alpha) with BFGS: it goes to alpha -> 0 without failing
            mod = NegativeBinomial(y, X, loglike_method=key, **kw)
            r, w, plan = _fit_plans(mod, start, [['bfgs'], ['nm', 'bfgs']])
            need(r)
            a = float(np.asarray(r.params)[-1])
            if not a > ALPHA_MIN or (base is not None and float(r.llf) <= base['llf'] + 1e-8 * max(1.0, abs(base['llf']))):
                out['boundary'] = 'alpha'
                out['model_fitted'] = 'poisson'
                out['alpha_plan'] = plan
                if base is not None:
                    r, w, plan = base['res'], base['warnings'], base['plan']
                else:
                    w = [x for x in w if 'Inverting hessian' not in str(x.message)]
            out.update(res=r, plan=plan)
        else:
            mod = GeneralizedPoisson(y, X, p=1, **kw)
            r, w, plan = _fit_plans(mod, start, PLANS)
            if base is not None and (r is None or float(r.llf) < base['llf'] - 1e-8 * max(1.0, abs(base['llf']))):
                # the GP contains the Poisson at alpha = 0: from there
                s0 = np.append(base['params'], 0.0)
                r, w, plan = _fit_plans(mod, s0, PLANS_BFGS)
                out['start'] = {'kind': 'poisson', 'alpha': 0.0}
            out.update(res=need(r), plan=plan)
        out['warnings'] += w
    elif zero == 'zi':
        zmod = ZeroInflatedPoisson(y, X, exog_infl=Z, inflation='logit', **kw)
        if key == 'zip':
            r, w, plan = _fit_plans(zmod, start, PLANS_BFGS)
            out.update(res=need(r), plan=plan)
            out['warnings'] += w
        else:
            if base is None and start is None:
                z0, zw, zplan = _fit_plans(zmod, None, PLANS_BFGS)
                if z0 is None:
                    raise ValueError('the zero-inflated Poisson that gives the starting values did not converge')
                base = {'res': z0, 'params': np.asarray(z0.params, float), 'llf': float(z0.llf), 'plan': zplan, 'warnings': zw}
                out['zip_plan'] = zplan
            const = 0.5 if fam == 'nb' else 0.1
            if start is not None:
                starts = [('given', np.asarray(start, float))]
            else:
                starts = _starts(base['params'], hints.get('alpha'), const)
                if fam == 'gp':
                    starts.append(('zero', np.append(base['params'], 0.0)))   # the ZIP itself: alpha = 0 is inside the GP
            cls = (lambda: ZeroInflatedNegativeBinomialP(y, X, exog_infl=Z, p=2, **kw)) if fam == 'nb' else (lambda: ZeroInflatedGeneralizedPoisson(y, X, exog_infl=Z, p=1, **kw))
            mod = cls()
            r, w, plan, si, restart, boundary = _alpha_fit(mod, starts, PLANS_BFGS, None if base is None else base['llf'], positive=fam == 'nb')
            if restart is not None:
                out['restart'] = restart
                out['notes'].append(restart_note)
            if boundary or r is None:
                if fam != 'nb':
                    need(r)
                if base is None:
                    z0, zw, zplan = _fit_plans(zmod, starts[0][1][:-1], PLANS_BFGS)
                    base = {'res': need(z0), 'params': np.asarray(z0.params, float), 'llf': float(z0.llf), 'plan': zplan, 'warnings': zw}
                out['boundary'] = 'alpha'
                out['model_fitted'] = 'zip'
                r, w, plan = base['res'], base['warnings'], base['plan']
            else:
                out['start'] = {'kind': 'zip', 'from': None if si is None else starts[si][0], 'alpha': None if si is None else float(starts[si][1][-1])}
            out.update(res=need(r), plan=plan)
            out['warnings'] += w
    else:
        # the hurdle: P(Y > 0) = 1 - exp(-exp(Z g + offset)), a binomial GLM with the complementary log-log link
        # (statsmodels' censored Poisson zero model), and a zero-truncated count model for Y > 0
        yb = (y > 0).astype(float)
        if yb.min() == yb.max():
            raise ValueError('a hurdle model needs zeros and counts above zero')
        off = np.log(kw['exposure']) if 'exposure' in kw else kw.get('offset')
        gmod = sm.GLM(yb, Z, family=sm.families.Binomial(link=sm.families.links.CLogLog()), offset=off)
        sz = None if start is None else start[:kz]
        g0, wg, eg = _attempt(lambda: gmod.fit(start_params=sz, maxiter=100))
        if eg is not None:
            raise eg
        g1, wg1, eg1 = _attempt(lambda: gmod.fit(start_params=np.asarray(g0.params, float), method='newton', maxiter=100))
        if not (eg1 is None and _finite_fit(g1) and float(g1.llf) >= float(g0.llf) - 1e-9):
            raise ValueError('the zero part (P(Y > 0)) did not converge')
        out['warnings'] += wg + wg1
        # statsmodels 0.14's truncated models log an exposure twice (the Poisson inside gets the logged one):
        # they are given the log exposure as an offset, the same model
        kwo = {} if off is None else {'offset': off}
        sc = None if start is None else start[kz:]
        tp = TruncatedLFPoisson(y, X, **kwo)
        if fam == 'poisson':
            cr, wc, plan = _fit_plans(tp, sc, PLANS)
            need(cr, 'the count part (Y > 0)')
        else:
            t0, tw, tplan = _fit_plans(tp, None if sc is None else sc[:-1], PLANS)
            if t0 is None:
                raise ValueError('the truncated Poisson that gives the starting values did not converge')
            out['tpois_plan'] = tplan
            cmod = TruncatedLFNegativeBinomialP(y, X, p=2, **kwo)
            starts = [('given', np.asarray(sc, float))] if sc is not None else _starts(np.asarray(t0.params, float), hints.get('alpha'), 0.5)
            cr, wc, plan, si, restart, boundary = _alpha_fit(cmod, starts, PLANS, float(t0.llf))
            if restart is not None:
                out['restart'] = restart
                out['notes'].append(restart_note)
            if boundary or cr is None:
                out['boundary'] = 'alpha'
                out['model_fitted'] = 'hp'
                cr, wc, plan = t0, tw, tplan
            else:
                out['start'] = {'kind': 'tpois', 'from': None if si is None else starts[si][0], 'alpha': None if si is None else float(starts[si][1][-1])}
            need(cr, 'the count part (Y > 0)')
        out['warnings'] += wc
        out.update(res=None, zero_res=g1, count_res=cr, plan=plan)
    return _finish(out, key, kx, kz)


def _finish(out, key, kx, kz):
    """params, cov, llf and the part slices of a fit."""
    from scipy.linalg import block_diag
    if ZERO.get(key) == 'hurdle':
        gz, cr = out['zero_res'], out['count_res']
        pz, pc = np.asarray(gz.params, float), np.asarray(cr.params, float)
        params = np.concatenate([pz, pc])
        try:
            cov = block_diag(np.asarray(gz.cov_params(), float), np.asarray(cr.cov_params(), float))
        except Exception:
            cov = np.full((len(params), len(params)), np.nan)
        llf = float(gz.llf) + float(cr.llf)
        gconv = getattr(gz, 'converged', None)
        if gconv is None:
            gconv = (getattr(gz, 'mle_retvals', None) or {}).get('converged', True)
        conv = [bool(gconv), bool(cr.mle_retvals.get('converged', True))]
        converged = all(conv)
    else:
        r = out['res']
        params = np.asarray(r.params, float)
        try:
            cov = np.asarray(r.cov_params(), float)
        except Exception:
            cov = np.full((len(params), len(params)), np.nan)
        llf = float(r.llf)
        converged = bool(r.mle_retvals.get('converged', True)) if hasattr(r, 'mle_retvals') else True
    has_alpha = FAMILY[key] != 'poisson' and out['boundary'] != 'alpha'
    if out['boundary'] == 'alpha' and ZERO.get(key) is None and len(params) == kx + 1:
        # NegativeBinomial with alpha -> 0 (no Poisson fit at hand): its estimates without alpha
        params, cov = params[:-1], cov[:-1, :-1]
    out.update(params=params, cov=cov, llf=llf, converged=converged, parts=_parts(key, kx, kz, has_alpha), k=len(params),
               has_alpha=has_alpha)
    return out


def _get(tid, rows, spec, key):
    """The fit of one model, from the cache or fitted now."""
    ck = _key('fit', tid, rows, spec, key)
    hit = _cache_get(ck)
    if hit is not None:
        return hit
    P = _prep(tid, rows, spec)
    if ZERO.get(key) and not np.any(P['y'] == 0):
        raise ValueError(f'{P["spec"]["y"]} has no zeros: a zero-inflated or hurdle model has no zeros to fit')
    if ZERO.get(key) and np.all(P['y'] == 0):
        raise ValueError(f'every value of {P["spec"]["y"]} is zero')
    y, X, Z, kw = _expanded(P)
    hints = {}
    base = {'nb2': 'poisson', 'nb1': 'poisson', 'gp': 'poisson', 'zinb': 'zip', 'zigp': 'zip'}.get(key)
    sibling = {'zinb': 'nb2', 'hnb': 'nb2', 'zigp': 'gp'}.get(key)
    for role, other in (('base', base), ('sibling', sibling)):
        if other is None:
            continue
        try:
            o = _get(tid, rows, spec, other)
        except Exception:  # noqa: BLE001 - only a start
            continue
        if role == 'base':
            hints['base'] = {'res': o['res'], 'params': np.asarray(o['res'].params, float), 'llf': o['llf'], 'plan': o['plan'], 'warnings': o['warnings']}
        elif o['boundary'] is None and 'alpha' in o['parts']:
            hints['alpha'] = float(o['params'][o['parts']['alpha']][0])
    m = _fit_core(key, y, X, Z, kw, None, hints)
    m['key'] = ck
    m['P'] = P
    _rows_part(m, P)
    return _cache_put(ck, m)


def _rows_part(m, P):
    """Per row of the table (not repeated by Freq): the distribution and what
    comes from it."""
    X, Z = P['X'].to_numpy(float), P['Z'].to_numpy(float)
    D = _dist(m, X, Z, _logoff(P))
    y = P['y']
    ll = D.logpmf(y)
    m['D'] = D
    m['llobs'] = ll
    m['mean'] = D.mean()
    m['var'] = D.var()
    m['p0'] = D.p0()
    with np.errstate(divide='ignore', invalid='ignore'):
        m['pearson'] = (y - m['mean']) / np.sqrt(m['var'])
    w = P['f'] if P['f'] is not None else np.ones(len(y))
    m['llf_rows'] = float(np.sum(w * ll))


# ---------------------------------------------------------------------------
# report tables
# ---------------------------------------------------------------------------

def _uncentre(d, names):
    cm = getattr(d, 'centered_main', None)
    if not cm or 'Intercept' not in names:
        return None
    T = np.eye(len(names))
    i0 = names.index('Intercept')
    for t, mn in cm.items():
        if t in names:
            T[i0, names.index(t)] = -mn
    return T


def _part_estimates(d, names, b, V, alpha, with_tests=True):
    """One part's estimates in JMP's order, the intercept at x = 0."""
    T = _uncentre(d, names)
    if T is not None:
        b, V = T @ b, T @ V @ T.T
    se = np.sqrt(np.maximum(np.diag(V), 0)) if np.all(np.isfinite(V)) else np.sqrt(np.abs(np.diag(V)))
    z = float(stats.norm.ppf(1 - alpha / 2))
    rows = []
    for j, nm in enumerate(names):
        s = float(se[j]) if np.isfinite(se[j]) and se[j] > 0 else None
        zr = float(b[j] / s) if s else None
        rows.append({'term': d.label(nm), 'name': nm, 'estimate': float(b[j]), 'se': s, 'z': zr if with_tests else None,
                     'p': float(2 * stats.norm.sf(abs(zr))) if (zr is not None and with_tests) else None,
                     'lower': float(b[j] - z * s) if s else None, 'upper': float(b[j] + z * s) if s else None})
    rank = {'Intercept': -1}
    for i, e in enumerate(d.effects):
        for c in e.get('terms', []):
            rank.setdefault(c, i)
    rows.sort(key=lambda r: rank.get(r['name'], len(d.effects)))
    return rows


def _est_table(rows, alpha):
    lv = f'{100 * (1 - alpha):g}%'
    return rtable([col('term', 'Term', 'text'), col('estimate', 'Estimate'), col('se', 'Std Error'), col('z', 'z Ratio'),
                   col('p', 'Prob>|z|', 'p'), col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}')], rows)


def _wald_effects(d, names, b, V):
    rows = []
    for e in d.effects:
        cols = [names.index(t) for t in e.get('terms', []) if t in names]
        if not cols:
            continue
        bb = b[cols]
        VV = V[np.ix_(cols, cols)]
        if not np.all(np.isfinite(VV)):
            rows.append({'source': e['label'], 'nparm': len(cols), 'df': len(cols), 'stat': None, 'p': None})
            continue
        stat = float(bb @ np.linalg.pinv(VV) @ bb)
        dfr = int(np.linalg.matrix_rank(VV))
        rows.append({'source': e['label'], 'nparm': len(cols), 'df': dfr, 'stat': stat, 'p': float(stats.chi2.sf(stat, dfr)) if dfr else None})
    return rows


def _effects_table(rows, lr=False):
    return rtable([col('source', 'Source', 'text'), col('nparm', 'Nparm', 'int'), col('df', 'DF', 'int'),
                   col('stat', 'L-R ChiSquare' if lr else 'Wald ChiSquare'), col('p', 'Prob>ChiSq', 'p')], rows)


def _crossed(d, name):
    return any(len(e['names']) > 1 and name in e['names'] for e in d.effects)


def _design_rows(d, di, settings):
    """Design rows for points given as {column name: value}; an unset
    continuous column sits at its mean, a categorical one at its first level."""
    import patsy
    n = len(settings)
    cols = {}
    for name, a in d.alias.items():
        if a == d.y_alias or a not in d.df:
            continue
        vals = [s.get(name) for s in settings]
        if a in d.categorical:
            lv = d.levels[a]
            cols[a] = pd.Categorical([lv[_level_index(lv, v)] if v is not None else lv[0] for v in vals], categories=lv)
        elif pd.api.types.is_numeric_dtype(d.df[a]):
            mn = float(d.df[a].mean())
            cols[a] = np.array([mn if v is None else float(v) for v in vals], dtype=float)
    frame = pd.DataFrame(cols, index=range(n))
    return np.asarray(patsy.build_design_matrices([di], frame, return_type='dataframe')[0], dtype=float)


def _level_index(levels, v):
    for i, lv in enumerate(levels):
        if lv == v:
            return i
    s = str(v)
    for i, lv in enumerate(levels):
        if _lvl(lv) == s or str(lv) == s:
            return i
        try:
            if isinstance(lv, (float, int, np.floating)) and float(lv) == float(v):
                return i
        except (TypeError, ValueError):
            pass
    return 0


def _lvl(v):
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return str(int(f)) if f.is_integer() else f'{f:.6g}'
    return str(v)


def _ratios(d, M, names, b, V, alpha, kind):
    """exp of the estimates as JMP's Odds Ratios report has them: per unit
    and over the range of a continuous main effect, between each pair of
    levels of a nominal one (for effects in no crossing)."""
    z = float(stats.norm.ppf(1 - alpha / 2))
    di = M.design_info
    unit, levels, skipped = [], [], []
    ok = np.all(np.isfinite(V))
    for e in d.effects:
        if len(e['names']) != 1:
            continue
        nm = e['names'][0]
        a = d.alias[nm]
        if _crossed(d, nm):
            skipped.append(nm)
            continue
        cols = [names.index(t) for t in e.get('terms', []) if t in names]
        if not cols:
            continue
        if a not in d.categorical:
            j = cols[0]
            bj = float(b[j])
            sj = math.sqrt(max(V[j, j], 0)) if ok else float('nan')
            x = d.df[a].to_numpy(float)
            span = float(np.max(x) - np.min(x))
            unit.append({'term': nm, 'ratio': _exp(bj), 'lower': _exp(bj - z * sj), 'upper': _exp(bj + z * sj),
                         'p': float(stats.chi2.sf((bj / sj) ** 2, 1)) if sj > 0 else None,
                         'range': _exp(bj * span), 'range_lower': _exp((bj - z * sj) * span), 'range_upper': _exp((bj + z * sj) * span), 'span': span})
        else:
            lv = d.levels[a]
            L = _design_rows(d, di, [{nm: v} for v in lv])
            for i1 in range(len(lv)):
                for i2 in range(len(lv)):
                    if i1 == i2:
                        continue
                    dl = L[i1] - L[i2]
                    est = float(dl @ b)
                    se = math.sqrt(max(float(dl @ V @ dl), 0)) if ok else float('nan')
                    levels.append({'term': nm, 'level1': _lvl(lv[i1]), 'level2': _lvl(lv[i2]), 'ratio': _exp(est),
                                   'lower': _exp(est - z * se), 'upper': _exp(est + z * se),
                                   'p': float(stats.chi2.sf((est / se) ** 2, 1)) if se > 0 else None})
    return {'kind': kind, 'unit': unit, 'levels': levels, 'skipped': skipped}


def _exp(x):
    try:
        return math.exp(x) if np.isfinite(x) else None
    except OverflowError:
        return float('inf')


# ---------------------------------------------------------------------------
# counts.fit
# ---------------------------------------------------------------------------

def _dist_table(P, D_list, K=None):
    """Observed and expected frequencies of 0..K (the last bin holds the rest
    when the counts go above KMAX)."""
    y = P['y']
    w = P['f'] if P['f'] is not None else np.ones(len(y))
    ymax = int(np.max(y))
    K = min(ymax, KMAX) if K is None else K
    tail = ymax > K
    obs = np.array([np.sum(w[y == k]) for k in range(K)] + [np.sum(w[y >= K]) if tail else np.sum(w[y == K])], dtype=float)
    ks = np.arange(K + 1, dtype=float)
    exps = []
    for D in D_list:
        e = np.zeros(K + 1)
        n = len(y)
        for s in range(0, n, 20000):
            sl = slice(s, s + 20000)
            Ds = Dist(D.fam, D.p, D.alpha, D.lam[sl], D.zero, None if D.w is None else D.w[sl])
            pm = Ds.pmf(ks[None, :])
            if tail:
                pm[:, K] = 1 - Ds.cdf(np.full(len(Ds.lam), K - 1.0))
            e += w[sl] @ pm
        exps.append(e)
    return {'k': list(range(K + 1)), 'observed': obs, 'expected': exps, 'tail': bool(tail), 'K': K, 'n': float(np.sum(w))}


def _quantile_resid(m, P, seed):
    """Randomized quantile residuals (Dunn and Smyth 1996): u uniform between
    F(y - 1) and F(y), then the normal quantile of u; numpy's generator with
    this seed, one draw per row in the order of the rows."""
    D = m['D']
    y = P['y']
    lo, hi = D.cdf(y - 1), D.cdf(y)
    u = np.random.default_rng(int(seed)).uniform(lo, hi)
    u = np.clip(u, 1e-15, 1 - 1e-15)
    return stats.norm.ppf(u)


@api('counts.fit')
def fit(table, y, rows=None, model='poisson', x=(), degree=1, zx=(), zero_same=True, exposure=None, offset=None, freq=None,
        alpha=0.05, seed=1, table_name='data'):
    if model not in LABEL:
        raise KeyError(f'no count model {model!r}')
    spec = _spec(y, x, degree, zx, zero_same, exposure, offset, freq)
    head = {'model': model, 'label': LABEL[model], 'short': SHORT[model]}
    try:
        m = _get(table, rows, spec, model)
    except Exception as e:  # noqa: BLE001 - a model that cannot be fitted is a message in its outline
        return {**head, 'error': str(e) or type(e).__name__}
    _replay(m['warnings'])
    P = m['P']
    d, dz = P['d'], P['dz']
    X, Z = P['X'], P['Z']
    names_x, names_z = list(X.columns), list(Z.columns)
    b, V = m['params'], m['cov']
    parts = m['parts']
    out = dict(head)
    n, k = P['n'], m['k']
    llf = m['llf']
    aic = -2 * llf + 2 * k
    out.update(n=n, nrows=len(P['y']), k=k, llf=llf, m2ll=-2 * llf, aic=aic, aicc=aic + (2 * k * (k + 1) / (n - k - 1) if n - k - 1 > 0 else float('nan')),
               bic=-2 * llf + k * math.log(n), converged=m['converged'], boundary=m['boundary'], alpha=alpha)
    wts = P['f'] if P['f'] is not None else np.ones(len(P['y']))
    out['zeros'] = {'observed': float(np.sum(wts * (P['y'] == 0))), 'predicted': float(np.sum(wts * m['p0']))}
    chi2 = float(np.sum(wts * m['pearson'] ** 2))
    out['pearson'] = {'chi2': chi2, 'df': n - k, 'ratio': chi2 / (n - k) if n - k > 0 else None}
    # estimates, effect tests and ratios by part
    est, eff, rat = {}, {}, {}
    sc = parts['count']
    est['count'] = _est_table(_part_estimates(d, names_x, b[sc], V[sc, sc], alpha), alpha)
    eff['count'] = _effects_table(_wald_effects(d, names_x, b[sc], V[sc, sc]))
    rat['count'] = _ratios(d, X, names_x, b[sc], V[sc, sc], alpha, 'rate')
    if 'zero' in parts:
        sz = parts['zero']
        est['zero'] = _est_table(_part_estimates(dz, names_z, b[sz], V[sz, sz], alpha), alpha)
        eff['zero'] = _effects_table(_wald_effects(dz, names_z, b[sz], V[sz, sz]))
        rat['zero'] = _ratios(dz, Z, names_z, b[sz], V[sz, sz], alpha, 'odds' if ZERO[model] == 'zi' else 'rate')
    if 'alpha' in parts:
        sa = parts['alpha']
        a = float(b[sa][0])
        s = math.sqrt(V[sa, sa][0, 0]) if np.isfinite(V[sa, sa][0, 0]) and V[sa, sa][0, 0] > 0 else None
        zc = float(stats.norm.ppf(1 - alpha / 2))
        interior = FAMILY[model] == 'gp'
        est['alpha'] = _est_table([{'term': 'α (dispersion)', 'estimate': a, 'se': s, 'z': a / s if (s and interior) else None,
                                    'p': float(2 * stats.norm.sf(abs(a / s))) if (s and interior) else None,
                                    'lower': a - zc * s if s else None, 'upper': a + zc * s if s else None}], alpha)
    elif FAMILY[model] == 'nb':
        est['alpha'] = _est_table([{'term': 'α (dispersion)', 'estimate': 0.0, 'se': None, 'z': None, 'p': None, 'lower': None, 'upper': None}], alpha)
    out['estimates'] = est
    out['effects'] = eff
    out['ratios'] = rat
    out['caption'] = _captions(model)
    # the rows
    out['rows'] = [int(i) for i in P['idx']]
    out['y'] = P['y']
    out['mean'] = m['mean']
    out['p0'] = m['p0']
    out['resid_pearson'] = m['pearson']
    out['resid_quantile'] = _quantile_resid(m, P, seed)
    out['seed'] = int(seed)
    out['freq'] = P['f']
    dt = _dist_table(P, [m['D']])
    out['dist'] = {'k': dt['k'], 'observed': dt['observed'], 'expected': dt['expected'][0], 'tail': dt['tail'], 'n': dt['n']}
    out['factors'] = _factors(P)
    out['notes'], out['warn'] = _notes(m, P, model, out)
    if model == 'poisson':
        out['poisson_tests'] = _poisson_tests(m)
    out['margeff'] = model in ('poisson', 'nb2', 'nb1', 'gp')
    out['code'] = _code_model(P, model, m, table_name, seed)
    return out


def _captions(model):
    z = ZERO.get(model)
    c = {'count': 'Count part: log of the mean' + (' of the count distribution' if z else '')}
    if z == 'zi':
        c['zero'] = 'Zero inflation: logit of P(structural zero)'
    elif z == 'hurdle':
        c['zero'] = 'Zero hurdle: P(Y > 0) = 1 − exp(−exp(xb)), complementary log-log'
    if FAMILY[model] != 'poisson':
        c['alpha'] = 'Dispersion'
    return c


def _factors(P):
    """The profiler's factors: the model's columns, then the exposure or offset."""
    d, dz = P['d'], P['dz']
    out, seen = [], set()
    for des in (d, dz):
        for e in des.effects:
            for nm in e['names']:
                if nm in seen:
                    continue
                seen.add(nm)
                a = des.alias[nm]
                if a in des.categorical:
                    out.append({'name': nm, 'type': 'categorical', 'levels': list(des.levels[a]), 'labels': [_lvl(v) for v in des.levels[a]]})
                else:
                    xv = des.df[a].to_numpy(float)
                    out.append({'name': nm, 'type': 'continuous', 'min': float(np.min(xv)), 'max': float(np.max(xv)), 'mean': float(np.mean(xv))})
    for role in ('exposure', 'offset'):
        c = P['spec'][role]
        if c:
            v = P['expo'] if role == 'exposure' else P['off']
            out.append({'name': c, 'type': 'continuous', 'role': role, 'min': float(np.min(v)), 'max': float(np.max(v)), 'mean': float(np.mean(v))})
    return out


def _notes(m, P, model, out):
    notes, warn = [], []
    fam = FAMILY[model]
    if not m['converged']:
        warn.append(f'{LABEL[model]}: the optimiser did not report convergence; the estimates may not be the maximum of the likelihood.')
    if m['boundary'] == 'alpha':
        base = LABEL[BASE[model]]
        warn.append(f'α went to its lower bound 0: there is no overdispersion for this model to take up, and the {LABEL[model]} is the {base} '
                    f'(its estimates and log-likelihood are the {base}\'s; α = 0 has no standard error).')
    V = m['cov']
    if not np.all(np.isfinite(V)) or np.any(np.diag(V) <= 0):
        warn.append('The Hessian could not be inverted at the estimates: some standard errors are missing. A parameter may be at a bound '
                    '(an inflation probability near 0 or 1, α near 0) or not identified by these data.')
    b = m['params']
    if 'zero' in m['parts']:
        g = b[m['parts']['zero']]
        big = np.abs(g) > 12
        if big.any():
            warn.append('The zero part has estimates beyond ±12 on its link scale: a level or a range where every count is zero (or none is), '
                        'or no excess zeros at all. Its standard errors and tests are not reliable.')
        if ZERO[model] == 'zi' and np.max(m['D'].w) < 1e-4:
            warn.append('The zero-inflation probability is below 0.0001 in every row: the data have no excess zeros for this model.')
    if fam == 'gp' and 'alpha' in m['parts']:
        a = float(b[m['parts']['alpha']][0])
        if a < 0:
            notes.append(f'α = {a:.4g} < 0: the generalized Poisson is underdispersed here (its variance below the mean).')
    if model == 'poisson' and out['pearson']['ratio'] is not None and out['pearson']['ratio'] > 1.5:
        notes.append(f'Pearson χ²/DF is {out["pearson"]["ratio"]:.3g}: the counts vary more than a Poisson allows (overdispersion); '
                     'the Poisson\'s standard errors are then too small. A negative binomial or generalized Poisson takes it up, a zero-inflated '
                     'or hurdle model the part that comes from excess zeros.')
    if abs(m['llf_rows'] - m['llf']) > 1e-6 * max(1.0, abs(m['llf'])):
        warn.append(f'The probabilities computed for the report give a log-likelihood of {m["llf_rows"]:.6f}, statsmodels\' is {m["llf"]:.6f}.')
    notes += m['notes']
    return notes, warn


def _poisson_tests(m):
    """statsmodels' dispersion tests (Dean, Cameron-Trivedi) and the score test
    for excess zeros of a Poisson fit."""
    out = {}
    r = m['res']
    try:
        dg = r.get_diagnostic()
        dt = dg.test_dispersion()
        sf = dt.summary_frame()
        out['dispersion'] = rtable([col('method', 'Test', 'text'), col('alternative', 'Alternative variance', 'text'), col('stat', 'Statistic'), col('p', 'Prob>|z|', 'p')],
                                   [{'method': str(rw['method']), 'alternative': str(rw['alternative']).replace('mu', 'μ').replace(' a ', ' α ').replace('(1 + a)', '(1 + α)'),
                                     'stat': float(rw['statistic']), 'p': float(rw['pvalue'])} for _, rw in sf.iterrows()])
        rows = []
        for meth, label in (('prob', 'Score test of P(Y = 0) (statsmodels, method "prob")'), ('broek', 'van den Broek score test')):
            try:
                zt = dg.test_poisson_zeroinflation(method=meth)
                rows.append({'test': label, 'stat': float(zt.statistic), 'p': float(zt.pvalue)})
            except Exception as e:  # noqa: BLE001
                rows.append({'test': f'{label}: {e}', 'stat': None, 'p': None})
        out['zero'] = rtable([col('test', 'Test', 'text'), col('stat', 'z'), col('p', 'Prob>|z|', 'p')], rows)
    except Exception as e:  # noqa: BLE001
        out['error'] = str(e)
    return out


# ---------------------------------------------------------------------------
# counts.compare
# ---------------------------------------------------------------------------

def _nested(P, a, b):
    """(restricted, full, df, boundary) when model a is nested in model b."""
    pairs = {('poisson', 'nb2'): (1, True), ('poisson', 'nb1'): (1, True), ('poisson', 'gp'): (1, False),
             ('zip', 'zinb'): (1, True), ('zip', 'zigp'): (1, False), ('hp', 'hnb'): (1, True)}
    if (a, b) in pairs:
        return pairs[(a, b)]
    if (a, b) == ('poisson', 'hp'):
        # the Poisson is the hurdle Poisson whose zero part has the count part's parameters
        if set(P['X'].columns) <= set(P['Z'].columns):
            return (P['Z'].shape[1], False)
    return None


def _vuong(ll1, ll2, w, k1, k2):
    m = ll1 - ll2
    n = float(np.sum(w))
    mean = float(np.sum(w * m) / n)
    sd = math.sqrt(float(np.sum(w * (m - mean) ** 2)) / (n - 1)) if n > 1 else 0.0
    if not sd > 1e-12 * max(1.0, abs(mean)):
        return None
    s = float(np.sum(w * m))
    out = {}
    for tag, corr in (('', 0.0), ('_aic', float(k1 - k2)), ('_bic', (k1 - k2) * math.log(n) / 2)):
        z = (s - corr) / (sd * math.sqrt(n))
        out['z' + tag] = z
        out['p' + tag] = float(stats.norm.sf(abs(z)))
    return out


@api('counts.compare')
def compare(table, y, rows=None, which=(), x=(), degree=1, zx=(), zero_same=True, exposure=None, offset=None, freq=None,
            alpha=0.05, table_name='data'):
    keys = [k for k in (which or []) if k in LABEL]
    keys = sorted(dict.fromkeys(keys), key=ORDER.index)
    spec = _spec(y, x, degree, zx, zero_same, exposure, offset, freq)
    try:
        P = _prep(table, rows, spec)
    except Exception as e:  # noqa: BLE001 - the data cannot be fitted: a message in the report
        return {'error': str(e) or type(e).__name__}
    fits, failed = {}, []
    for k in keys:
        try:
            fits[k] = _get(table, rows, spec, k)
        except Exception as e:  # noqa: BLE001
            failed.append({'model': k, 'label': LABEL[k], 'error': str(e)})
    n = P['n']
    w = P['f'] if P['f'] is not None else np.ones(len(P['y']))
    rows_out = []
    for k, m in fits.items():
        kk = m['k']
        aic = -2 * m['llf'] + 2 * kk
        ratio = float(np.sum(w * m['pearson'] ** 2)) / (n - kk) if n - kk > 0 else None
        rows_out.append({'model': k, 'label': LABEL[k], 'short': SHORT[k], 'k': kk, 'm2ll': -2 * m['llf'], 'aic': aic,
                         'aicc': aic + (2 * kk * (kk + 1) / (n - kk - 1) if n - kk - 1 > 0 else float('nan')),
                         'bic': -2 * m['llf'] + kk * math.log(n), 'zeros_obs': float(np.sum(w * (P['y'] == 0))),
                         'zeros_pred': float(np.sum(w * m['p0'])), 'dispersion': ratio, 'converged': m['converged'], 'boundary': m['boundary']})
    fin = [r['aicc'] for r in rows_out if r['aicc'] is not None and np.isfinite(r['aicc'])]
    if fin:
        best = min(fin)
        tot = sum(math.exp(-0.5 * (a - best)) for a in fin)
        for r in rows_out:
            r['weight'] = math.exp(-0.5 * (r['aicc'] - best)) / tot if np.isfinite(r['aicc']) else None
    lr, vu = [], []
    ks = list(fits)
    for i, a in enumerate(ks):
        for b_ in ks[i + 1:]:
            nest = _nested(P, a, b_)
            ma, mb = fits[a], fits[b_]
            if nest is not None:
                dfn, boundary = nest
                stat = max(0.0, 2 * (mb['llf'] - ma['llf']))
                p = float(stats.chi2.sf(stat, dfn))
                if boundary:
                    # P(T >= t) under the mixture: 1 at t = 0, half the chi2(1) tail above
                    p = 1.0 if stat < 1e-9 else 0.5 * p
                lr.append({'test': f'{SHORT[a]} vs {SHORT[b_]}', 'restricted': LABEL[a], 'full': LABEL[b_], 'lr': stat, 'df': dfn, 'p': p,
                           'boundary': boundary, 'mixture': '½χ²₀ + ½χ²₁' if boundary else f'χ²({dfn})'})
            else:
                v = _vuong(mb['llobs'], ma['llobs'], w, mb['k'], ma['k'])
                row = {'m1': LABEL[b_], 'm2': LABEL[a], 's1': SHORT[b_], 's2': SHORT[a]}
                if v is None:
                    row.update({'note': 'the two models give the same probabilities'})
                else:
                    row.update(v)
                    row['favours'] = SHORT[b_] if v['z_aic'] > 0 else SHORT[a]
                vu.append(row)
    dt = _dist_table(P, [fits[k]['D'] for k in fits])
    notes = []
    if any(r['boundary'] for r in lr):
        notes.append('α = 0 is on the boundary of the negative binomial\'s parameter space: the likelihood ratio statistic is then a 50:50 mixture of '
                     'χ²₀ and χ²₁ (Self and Liang 1987), and its p-value half the χ²₁ one.')
    if vu:
        notes.append('Vuong\'s test for non-nested models, computed here from the log-probability of each row under each model (statsmodels has no '
                     'Vuong test): z = √n·mean(m)/sd(m), m the difference of the two log-probabilities per row; the corrected statistics subtract '
                     '(k₁ − k₂) (AIC) or (k₁ − k₂)·log(n)/2 (BIC) from Σm, as R\'s pscl::vuong does. A positive z favours Model 1; the p-values are '
                     'one-sided, towards the model it favours. A zero-inflated model and its count model are nested at the boundary (π → 0); '
                     'Wilson (2015) shows that the Vuong test is not valid for that comparison: read it with the AICc and BIC.')
    notes.append('k counts every estimated parameter: the count part, the zero part and α, as statsmodels\' aic and bic do and as JMP counts its '
                 'AICc = AIC + 2k(k + 1)/(n − k − 1). Dispersion is Pearson χ²/(n − k), the Pearson residuals from each model\'s own mean and variance.')
    return {'models': rows_out, 'failed': failed, 'lr': lr, 'vuong': vu,
            'dist': {'k': dt['k'], 'observed': dt['observed'], 'expected': {k: e for k, e in zip(fits, dt['expected'])}, 'tail': dt['tail'], 'n': dt['n']},
            'notes': notes, 'code': _code_compare(P, fits, table_name)}


# ---------------------------------------------------------------------------
# likelihood-ratio effect tests, marginal effects, the profiler
# ---------------------------------------------------------------------------

@api('counts.lr_effects')
def lr_effects(table, y, rows=None, model='poisson', x=(), degree=1, zx=(), zero_same=True, exposure=None, offset=None, freq=None):
    spec = _spec(y, x, degree, zx, zero_same, exposure, offset, freq)
    try:
        m = _get(table, rows, spec, model)
    except Exception as e:  # noqa: BLE001
        return {'error': str(e)}
    P = m['P']
    fitted = m.get('model_fitted', model)
    yy, X, Z, kw = _expanded(P)
    b = m['params']
    out, failed = {}, []
    for part, des, M in (('count', P['d'], P['X']), ('zero', P['dz'], P['Z'])):
        if part not in m['parts']:
            continue
        names = list(M.columns)
        rows_out = []
        for e in des.effects:
            cols = [names.index(t) for t in e.get('terms', []) if t in names]
            if not cols:
                continue
            keep = [j for j in range(len(names)) if j not in cols]
            sl = m['parts'][part]
            full_idx = np.arange(len(b))
            drop = set(full_idx[sl][cols])
            start = np.array([b[j] for j in range(len(b)) if j not in drop])
            Xr, Zr = (X[:, keep], Z) if part == 'count' else (X, Z[:, keep])
            r, _w, err = _attempt(lambda: _fit_core(fitted, yy, Xr, Zr, kw, start))
            if err is not None or r is None:
                rows_out.append({'source': e['label'], 'nparm': len(cols), 'df': len(cols), 'stat': None, 'p': None})
                failed.append(e['label'])
                continue
            stat = max(0.0, 2 * (m['llf'] - r['llf']))
            rows_out.append({'source': e['label'], 'nparm': len(cols), 'df': len(cols), 'stat': stat, 'p': float(stats.chi2.sf(stat, len(cols)))})
        out[part] = _effects_table(rows_out, lr=True)
    notes = ['Each effect\'s L-R ChiSquare is twice the log-likelihood the model loses when it is refitted without the effect\'s terms '
             '(in that part of the model; the other parts keep theirs).']
    if failed:
        notes.append('The refit without ' + ', '.join(dict.fromkeys(failed)) + ' did not converge: no test.')
    return {'effects': out, 'notes': notes}


@api('counts.margeff')
def margeff(table, y, rows=None, model='poisson', at='overall', method='dydx', x=(), degree=1, zx=(), zero_same=True, exposure=None,
            offset=None, freq=None, alpha=0.05, table_name='data'):
    spec = _spec(y, x, degree, zx, zero_same, exposure, offset, freq)
    if model not in ('poisson', 'nb2', 'nb1', 'gp'):
        return {'error': f'statsmodels 0.14 has no marginal effects for the {LABEL[model]} (get_margeff: "not yet implemented for zero inflation"; '
                         'the hurdle model\'s fails): use the Prediction Profiler'}
    try:
        m = _get(table, rows, spec, model)
    except Exception as e:  # noqa: BLE001
        return {'error': str(e)}
    r = m['res']   # at alpha = 0 the negative binomial's fit is the Poisson's, and so are its effects
    me = r.get_margeff(at=at, method=method)
    sf = me.summary_frame(alpha=alpha)
    P = m['P']
    d = P['d']
    names = list(P['X'].columns)
    exog_names = list(r.model.exog_names)
    rows_out = []
    lv = f'{100 * (1 - alpha):g}%'
    for i, (nm, rw) in enumerate(sf.iterrows()):
        j = exog_names.index(nm) if nm in exog_names else None
        label = d.label(names[j]) if j is not None and j < len(names) else str(nm)
        vals = rw.to_numpy(float)
        rows_out.append({'term': label, 'name': names[j] if j is not None and j < len(names) else str(nm), 'effect': vals[0], 'se': vals[1],
                         'z': vals[2], 'p': vals[3], 'lower': vals[4], 'upper': vals[5]})
    rank = {}
    for i, e in enumerate(d.effects):
        for c in e.get('terms', []):
            rank.setdefault(c, i)
    rows_out.sort(key=lambda r: rank.get(r['name'], len(d.effects)))
    head = {'dydx': 'dy/dx', 'eyex': 'ey/ex', 'dyex': 'dy/ex', 'eydx': 'ey/dx'}.get(method, method)
    notes = [f'statsmodels\' get_margeff(at="{at}", method="{method}") of the mean count: '
             + ('the average of the effects over the rows.' if at == 'overall' else f'the effects at the {at} of the design columns.'),
             'It differentiates by the columns of the design: for a continuous column that is a main effect only, dE[Y]/dx; for the effect-coded '
             'columns of a nominal factor, or a crossing or power term, the derivative by that coded column (not a change of level).']
    if P['expo'] is not None or P['off'] is not None:
        notes.append('get_margeff predicts with the exposure at 1 (the offset at 0): these are effects on the rate per unit of exposure.')
    lines = _code_frame(P, table_name) + _code_designs(P) + _code_fit_lines(P, model, m, 'fit')
    lines.append(f'print(fit.get_margeff(at={at!r}, method={method!r}).summary_frame(alpha={alpha!r}))')
    return {'table': rtable([col('term', 'Term', 'text'), col('effect', head), col('se', 'Std Error'), col('z', 'z Ratio'), col('p', 'Prob>|z|', 'p'),
                             col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}')], rows_out),
            'notes': notes, 'code': '\n'.join(lines)}


def _gradient(fn, theta, h=1e-6):
    base = fn(theta)
    G = np.zeros((len(base), len(theta)))
    for j in range(len(theta)):
        s = h * max(1.0, abs(theta[j]))
        tp, tm = theta.copy(), theta.copy()
        tp[j] += s
        tm[j] -= s
        G[:, j] = (fn(tp) - fn(tm)) / (2 * s)
    return base, G


@api('counts.profile')
def profile(table, y, rows=None, model='poisson', current=None, grid=41, alpha=0.05, x=(), degree=1, zx=(), zero_same=True,
            exposure=None, offset=None, freq=None):
    """The Prediction Profiler: for each factor, E[Y] and P(Y = 0) (with
    delta-method confidence intervals on the log and logit scales) as the
    factor varies and the others stay at their current values."""
    spec = _spec(y, x, degree, zx, zero_same, exposure, offset, freq)
    try:
        m = _get(table, rows, spec, model)
    except Exception as e:  # noqa: BLE001
        return {'error': str(e)}
    P = m['P']
    facs = _factors(P)
    cur = {}
    for f in facs:
        v = (current or {}).get(f['name'])
        if f['type'] == 'categorical':
            cur[f['name']] = f['levels'][_level_index(f['levels'], v)] if v is not None else f['levels'][0]
        else:
            try:
                cur[f['name']] = float(v) if v is not None else f['mean']
            except (TypeError, ValueError):
                cur[f['name']] = f['mean']
    settings = [dict(cur)]
    spans = []
    for f in facs:
        g = list(range(len(f['levels']))) if f['type'] == 'categorical' else list(np.linspace(f['min'], f['max'], int(grid))) if f['max'] > f['min'] else [f['min']]
        spans.append((len(settings), len(g)))
        for v in g:
            s = dict(cur)
            s[f['name']] = f['levels'][v] if f['type'] == 'categorical' else float(v)
            settings.append(s)
    Xn = _design_rows(P['d'], P['X'].design_info, settings)
    Zn = _design_rows(P['dz'], P['Z'].design_info, settings) if not P['same'] else Xn
    if P['spec']['exposure']:
        lo = np.log(np.array([s[P['spec']['exposure']] for s in settings], dtype=float))
    elif P['spec']['offset']:
        lo = np.array([s[P['spec']['offset']] for s in settings], dtype=float)
    else:
        lo = np.zeros(len(settings))

    def g(theta):
        D = _dist(m, Xn, Zn, lo, theta)
        with np.errstate(divide='ignore'):
            return np.concatenate([np.log(D.mean()), special.logit(np.clip(D.p0(), 1e-300, 1 - 1e-16))])

    theta = np.asarray(m['params'], float)
    val, G = _gradient(g, theta)
    V = m['cov']
    ns = len(settings)
    zc = float(stats.norm.ppf(1 - alpha / 2))
    if np.all(np.isfinite(V)):
        se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', G, V, G), 0))
    else:
        se = np.full(len(val), np.nan)
    lm, lp = val[:ns], val[ns:]
    sm_, sp = se[:ns], se[ns:]
    resp = [
        {'name': f'Mean {spec["y"]}', 'pred': np.exp(lm), 'lower': np.exp(lm - zc * sm_), 'upper': np.exp(lm + zc * sm_), 'bounded': False},
        {'name': f'P({spec["y"]} = 0)', 'pred': special.expit(lp), 'lower': special.expit(lp - zc * sp), 'upper': special.expit(lp + zc * sp), 'bounded': True},
    ]
    for f in facs:
        f['current'] = cur[f['name']]
    out = {'factors': facs, 'responses': [], 'alpha': alpha}
    for r in resp:
        ok = np.all(np.isfinite(r['lower']))
        item = {'name': r['name'], 'bounded': r['bounded'],
                'current': {'pred': float(r['pred'][0]), 'lower': float(r['lower'][0]) if ok else None, 'upper': float(r['upper'][0]) if ok else None},
                'traces': []}
        for f, (at, k) in zip(facs, spans):
            sl = slice(at, at + k)
            item['traces'].append({'factor': f['name'], 'x': f['labels'] if f['type'] == 'categorical' else [s[f['name']] for s in settings[sl]],
                                   'pred': r['pred'][sl], 'lower': r['lower'][sl] if ok else None, 'upper': r['upper'][sl] if ok else None})
        out['responses'].append(item)
    return out


# ---------------------------------------------------------------------------
# the Python code under the reports
# ---------------------------------------------------------------------------

def _code_frame(P, table_name):
    """Read the exported table, keep the report's rows and the model's
    columns, the page's level order; Freq repeats rows."""
    lines = [code_head(table_name, ['import patsy', 'from scipy import stats'])]
    rows = P['rows']
    tid = P['tid']
    if rows is not None:
        n = data.TABLES[tid]['n'] if tid in data.TABLES else None
        keep = [int(r) for r in rows]
        if n is not None and len(keep) > n / 2:
            drop = sorted(set(range(n)) - set(keep))
            if drop:
                lines.append(f'df = df.drop(index={drop})   # the rows the report leaves out')
        else:
            lines.append(f'df = df.loc[{keep}]   # the rows of the report')
    spec = P['spec']
    cols = list(dict.fromkeys([spec['y'], *spec['x'], *spec['zx'], *(c for c in (spec['exposure'], spec['offset'], spec['freq']) if c)]))
    lines.append(f'd = df[{json.dumps(cols)}].dropna()')
    for des in (P['d'], P['dz']):
        for nm in cols:
            a = des.alias.get(nm)
            if a is None or a not in des.categorical:
                continue
            lv = des.levels[a]
            numeric = all(isinstance(v, (float, int, np.floating, np.integer)) for v in lv)
            cats = json.dumps([float(v) for v in lv] if numeric else [str(v) for v in lv])
            src = f'd[{json.dumps(nm)}].astype(float)' if numeric else f'd[{json.dumps(nm)}]'
            line = f'd[{json.dumps(nm)}] = pd.Categorical({src}, categories={cats})   # the level order of the table'
            if line not in lines:
                lines.append(line)
    if spec['freq']:
        fq = json.dumps(spec['freq'])
        lines.append(f'd = d[d[{fq}] > 0]')
        lines.append(f'd = d.loc[d.index.repeat(d[{fq}].astype(int))]   # Freq: each row counts that many times (the models take no weights)')
    return lines


def _code_designs(P):
    lines = [f'X = patsy.dmatrix({json.dumps(models.code_formula(P["d"], lhs=False))}, d, return_type="dataframe")   # the count part, JMP\'s effect coding']
    if not P['same']:
        lines.append(f'Z = patsy.dmatrix({json.dumps(models.code_formula(P["dz"], lhs=False))}, d, return_type="dataframe")   # the zero part')
    else:
        lines.append('Z = X   # the zero part has the same effects')
    return lines


def _kw_code(P):
    spec = P['spec']
    if spec['exposure']:
        return f', exposure=d[{json.dumps(spec["exposure"])}]'
    if spec['offset']:
        return f', offset=d[{json.dumps(spec["offset"])}]'
    return ''


def _logoff_code(P):
    spec = P['spec']
    if spec['exposure']:
        return f'np.log(d[{json.dumps(spec["exposure"])}])'
    if spec['offset']:
        return f'd[{json.dumps(spec["offset"])}]'
    return 'None'


def _pyarr(a):
    return '[' + ', '.join(repr(float(v)) for v in a) + ']'


def _plan_lines(var, ctor, plan, start_expr=None):
    """A model and the optimiser steps of its fit, each from where the last ended."""
    L = [f'{var}_model = {ctor}']
    s = start_expr
    for step in plan or ['bfgs']:
        o = STEPS[step]
        opts = ', '.join(f'{k}={v!r}' for k, v in o.items() if k != 'method')
        sp = f'start_params={s}, ' if s else ''
        L.append(f'{var} = {var}_model.fit({sp}method="{o["method"]}", {opts}, disp=0)')
        s = f'{var}.params'
    return L


def _cached(P, key):
    """The cached fit of another model of the same data, or None."""
    return _CACHE.get(_key('fit', P['tid'], P['rows'], P['spec'], key))


def _zip_plan(P, m):
    """The plan of the ZIP whose estimates start a ZINB or ZIGP."""
    if m.get('zip_plan'):
        return m['zip_plan']
    return (_cached(P, 'zip') or {}).get('plan') or PLANS_BFGS[0]


def _code_fit_lines(P, key, m, var):
    """The statsmodels calls of one fit, as the backend made them."""
    yv = f'd[{json.dumps(P["spec"]["y"])}]'
    kw = _kw_code(P)
    fitted = m.get('model_fitted', key)
    plan = m.get('plan')
    st = m.get('start') or {}
    ctor = {'poisson': f'sm.Poisson({yv}, X{kw})', 'nb2': f'sm.NegativeBinomial({yv}, X, loglike_method="nb2"{kw})',
            'nb1': f'sm.NegativeBinomial({yv}, X, loglike_method="nb1"{kw})', 'gp': f'sm.GeneralizedPoisson({yv}, X, p=1{kw})',
            'zip': f'sm.ZeroInflatedPoisson({yv}, X, exog_infl=Z, inflation="logit"{kw})',
            'zinb': f'sm.ZeroInflatedNegativeBinomialP({yv}, X, exog_infl=Z, p=2{kw})',
            'zigp': f'sm.ZeroInflatedGeneralizedPoisson({yv}, X, exog_infl=Z, p=1{kw})'}

    def sibling_lines(sib, name):
        c = _cached(P, sib) or {}
        return _plan_lines(name, ctor[sib], c.get('plan') or PLANS_BFGS[0])

    def alpha_start(prefix, params_expr, sib, sib_name):
        """The start of an alpha model: its contained model's estimates and alpha."""
        if st.get('from') == 'hint':
            return sibling_lines(sib, sib_name), f'np.append({params_expr}, {sib_name}.params.iloc[-1])'
        return [], f'np.append({params_expr}, {st.get("alpha", 0.5)!r})'

    L = []
    if key in ('nb2', 'nb1') and fitted == 'poisson':
        L += _plan_lines('nb', ctor[key], m.get('alpha_plan') or ['bfgs'])
        L.append('# alpha went to its bound 0 (below 1e-6): the negative binomial is the Poisson, whose estimates the report shows')
        L += _plan_lines(var, ctor['poisson'], plan)
    elif key == 'gp' and st.get('kind') == 'poisson':
        L += _plan_lines('pois', ctor['poisson'], (_cached(P, 'poisson') or {}).get('plan') or PLANS[0])
        L.append('# the generalized Poisson from the Poisson (alpha = 0 inside it): its default start ended below the Poisson')
        L += _plan_lines(var, ctor['gp'], plan, 'np.append(pois.params, 0.0)')
    elif key in ('poisson', 'nb2', 'nb1', 'gp', 'zip'):
        L += _plan_lines(var, ctor[key], plan)
        if key in ('nb2', 'nb1'):
            L[-1] += '   # BFGS searches over log(alpha) in statsmodels\' NegativeBinomial'
    elif key in ('zinb', 'zigp'):
        L += _plan_lines('zip_fit', ctor['zip'], _zip_plan(P, m))
        if fitted == 'zip':
            L.append(f'# the {LABEL[key]} went to alpha = 0 (below 1e-6): it is the zero-inflated Poisson, whose estimates the report shows')
            L.append(f'{var} = zip_fit')
        elif 'restart' in m:
            L.append('# statsmodels\' fits from the ZIP\'s estimates stepped to alpha <= 0; the maximum over log(alpha) was this start:')
            L += _plan_lines(var, ctor[key], plan, _pyarr(m['restart']))
        else:
            sib = 'nb2' if key == 'zinb' else 'gp'
            pre, sexpr = alpha_start('zip', 'zip_fit.params', sib, f'{sib}_fit')
            L += pre
            L += _plan_lines(var, ctor[key], plan, sexpr)
            L[-1] += '   # from the ZIP\'s estimates (the best of the starts tried)'
    else:
        # the hurdle in its two parts
        off = _logoff_code(P)
        offc = '' if off == 'None' else f', offset={off}'
        L.append('from statsmodels.discrete.truncated_model import TruncatedLFPoisson, TruncatedLFNegativeBinomialP')
        L.append(f'zero = sm.GLM(({yv} > 0).astype(float), Z, family=sm.families.Binomial(link=sm.families.links.CLogLog()), offset={off}).fit(maxiter=100)')
        L.append('zero = zero.model.fit(start_params=zero.params, method="newton", maxiter=100)   # Newton: standard errors from the observed information')
        tctor = f'TruncatedLFPoisson({yv}, X{offc})'
        if key == 'hp':
            L += _plan_lines('count', tctor, plan)
        else:
            L += _plan_lines('tpois', tctor, m.get('tpois_plan') or PLANS[0])
            nbctor = f'TruncatedLFNegativeBinomialP({yv}, X, p=2{offc})'
            if fitted == 'hp':
                L.append('# the negative binomial count part went to alpha = 0: it is the truncated Poisson')
                L.append('count = tpois')
            elif 'restart' in m:
                L += _plan_lines('count', nbctor, plan, _pyarr(m['restart']))
            else:
                pre, sexpr = alpha_start('tpois', 'tpois.params', 'nb2', 'nb2_fit')
                L += pre
                L += _plan_lines('count', nbctor, plan, sexpr)
        L.append('# the log exposure goes in as an offset: statsmodels 0.14\'s truncated models log an exposure twice. Without an exposure and')
        L.append('# with the same effects in both parts this is HurdleCountModel(y, X, dist=...).fit()')
    return L


def _code_params_lines(P, key, m, var):
    """params, llf and k of a fit in the code, as the report counts them."""
    if ZERO.get(key) == 'hurdle':
        return [f'{var}_params = np.concatenate([zero.params, count.params])   # the zero part first, as HurdleCountModel orders them',
                f'{var}_llf = zero.llf + count.llf']
    return [f'{var}_params = np.asarray({var}.params)', f'{var}_llf = {var}.llf']


def _code_dist_lines(P, key, m, var):
    """The fitted distribution per row in the code: lam, the zero part, pmf and cdf."""
    fam = FAMILY[key]
    fitted = m.get('model_fitted', key)
    if m['boundary'] == 'alpha':
        fam = 'poisson'
    L = []
    zero = ZERO.get(key)
    if zero == 'hurdle':
        L.append('lam = np.exp(np.asarray(X) @ np.asarray(count.params)[:X.shape[1]]' + (f' + {_logoff_code(P)}' if _logoff_code(P) != 'None' else '') + ')')
        L.append('w = np.asarray(zero.predict())   # P(Y > 0)')
        alpha = 'np.asarray(count.params)[-1]'
    elif zero == 'zi':
        L.append(f'lam = np.asarray({var}.predict(which="mean-main"))   # the count distribution\'s mean')
        L.append(f'w = 1 - np.asarray({var}.predict(which="prob-main"))   # P(structural zero)')
        alpha = f'np.asarray({var}.params)[-1]'
    else:
        L.append(f'lam = np.asarray({var}.predict())')
        alpha = f'np.asarray({var}.params)[-1]'
    if fam == 'poisson':
        L += ['pmf0 = lambda k: stats.poisson.pmf(k, lam)', 'cdf0 = lambda k: stats.poisson.cdf(k, lam)']
    elif fam == 'nb':
        pp = P_OF[key]
        size = '1 / a' if pp == 2 else 'lam / a'
        L += [f'a = {alpha}; size = {size}   # NB{pp}: Var = lam + a lam^{pp}',
              'pmf0 = lambda k: stats.nbinom.pmf(k, size, size / (size + lam))', 'cdf0 = lambda k: stats.nbinom.cdf(k, size, size / (size + lam))']
    else:
        L += [f'a = {alpha}',
              'from statsmodels.distributions.discrete import genpoisson_p',
              'pmf0 = lambda k: genpoisson_p.pmf(k, lam, a, 1)   # statsmodels\' generalized Poisson, p = 1',
              'cdf0 = lambda k: np.array([genpoisson_p.pmf(np.arange(int(kk) + 1), m_, a, 1).sum() if kk >= 0 else 0.0 for kk, m_ in zip(np.broadcast_to(k, lam.shape), lam)])']
    if zero == 'zi':
        L += ['pmf = lambda k: (1 - w) * pmf0(k) + w * (np.asarray(k) == 0)', 'cdf = lambda k: np.where(np.asarray(k) < 0, 0, w + (1 - w) * cdf0(k))',
              'mean = (1 - w) * lam']
    elif zero == 'hurdle':
        L += ['f0 = pmf0(0)', 'pmf = lambda k: np.where(np.asarray(k) == 0, 1 - w, w * pmf0(k) / (1 - f0))',
              'cdf = lambda k: np.where(np.asarray(k) < 0, 0, np.where(np.asarray(k) == 0, 1 - w, 1 - w + w * (cdf0(k) - f0) / (1 - f0)))',
              'mean = w * lam / (1 - f0)']
    else:
        L += ['pmf, cdf, mean = pmf0, cdf0, lam']
    _ = fitted
    return L


def _code_model(P, key, m, table_name, seed):
    lines = _code_frame(P, table_name) + _code_designs(P) + _code_fit_lines(P, key, m, 'fit') + _code_params_lines(P, key, m, 'fit')
    if ZERO.get(key) != 'hurdle':
        lines.append('print(fit.summary())')
    else:
        lines += ['print(zero.summary())', 'print(count.summary())']
    k = m['k']
    lines.append(f'k = {k}; n = len(d); print(fit_llf, -2 * fit_llf + 2 * k, -2 * fit_llf + k * np.log(n))   # log-likelihood, AIC, BIC')
    lines += _code_dist_lines(P, key, m, 'fit')
    y = json.dumps(P['spec']['y'])
    K = min(int(np.max(P['y'])), KMAX)
    tail = int(np.max(P['y'])) > KMAX
    lines.append(f'y = d[{y}].to_numpy()')
    lines.append('p0 = pmf(np.zeros(len(y)))   # P(Y = 0) per row')
    if tail:
        lines.append(f'expected = [pmf(np.full(len(y), j)).sum() for j in range({K})] + [(1 - cdf(np.full(len(y), {K - 1}))).sum()]   # the rootogram: {K} and above in the last bin')
    else:
        lines.append(f'expected = [pmf(np.full(len(y), j)).sum() for j in range({K + 1})]   # the rootogram\'s expected frequencies: sums of the predicted probabilities')
    first = '' if P['spec']['freq'] is None else '[~d.index.duplicated()]'
    if first:
        lines.append('one = ~d.index.duplicated()   # one row of each repeated (Freq) row, for the residuals')
        lines.append('u = np.random.default_rng(%d).uniform(cdf(y - 1)[one], cdf(y)[one])   # randomized quantile residuals (Dunn and Smyth 1996)' % int(seed))
    else:
        lines.append('u = np.random.default_rng(%d).uniform(cdf(y - 1), cdf(y))   # randomized quantile residuals (Dunn and Smyth 1996)' % int(seed))
    lines.append('quantile_resid = stats.norm.ppf(np.clip(u, 1e-15, 1 - 1e-15))')
    lines.append('print(p0.sum(), np.round(expected, 3))   # predicted zeros; expected frequencies of 0, 1, ...')
    lines += _centred_code(P)
    return '\n'.join(lines)


def _centred_code(P):
    """The comment the code carries when a main effect was centred like its crossings."""
    names = []
    for des in (P['d'], P['dz']):
        for t in getattr(des, 'centered_main', {}) or {}:
            a = t[2:t.index(' ')] if t.startswith('I(') else None
            nm = des.name.get(a) if a else None
            if nm and nm not in names:
                names.append(nm)
    if not names:
        return []
    return [f'# {", ".join(names)}: the main effect is centred like its crossings, so patsy codes them as JMP does; the report\'s',
            '# Intercept is at 0 instead of the mean: Intercept - sum(mean * slope)']


def _code_compare(P, fits, table_name):
    lines = _code_frame(P, table_name) + _code_designs(P)
    lines.append('ll, k = {}, {}   # the log-probability of each row under each model, the number of parameters')
    for key, m in fits.items():
        var = f'fit_{key}'
        lines.append(f'# {LABEL[key]}')
        lines += _code_fit_lines(P, key, m, var)
        if ZERO.get(key) == 'hurdle':
            lines += [f'll[{key!r}] = np.log(np.where(d[{json.dumps(P["spec"]["y"])}] > 0, zero.predict(), 1 - zero.predict()))',
                      f'll[{key!r}][d[{json.dumps(P["spec"]["y"])}].to_numpy() > 0] += count.model.loglikeobs(np.asarray(count.params))',
                      f'k[{key!r}] = len(zero.params) + len(count.params)']
        else:
            lines += [f'll[{key!r}] = {var}.model.loglikeobs(np.asarray({var}.params))   # pandas params: positional [-1] inside statsmodels needs an array', f'k[{key!r}] = len({var}.params)']
    lines += ['n = len(d)',
              'for a in k: print(a, k[a], -2 * ll[a].sum(), -2 * ll[a].sum() + 2 * k[a], -2 * ll[a].sum() + k[a] * np.log(n))   # k, -2LL, AIC, BIC',
              'def vuong(m1, m2):   # R pscl::vuong: raw, AIC- and BIC-corrected z; positive favours m1',
              '    m = ll[m1] - ll[m2]; s = m.std(ddof=1) * np.sqrt(n)',
              '    return [(m.sum() - c) / s for c in (0, k[m1] - k[m2], (k[m1] - k[m2]) * np.log(n) / 2)]',
              'def lr(small, big, df=1, boundary=True):   # boundary: alpha = 0, a 50:50 mixture of chi2(0) and chi2(1)',
              '    s = max(0, 2 * (ll[big].sum() - ll[small].sum())); return s, (0.5 if boundary else 1) * stats.chi2.sf(s, df)']
    ks = list(fits)
    for i, a in enumerate(ks):
        for b in ks[i + 1:]:
            nest = _nested(P, a, b)
            if nest is not None:
                lines.append(f'print("{SHORT[a]} vs {SHORT[b]}", lr({a!r}, {b!r}, {nest[0]}, {nest[1]}))')
            else:
                lines.append(f'print("{SHORT[b]} vs {SHORT[a]}", vuong({b!r}, {a!r}))')
    return '\n'.join(lines)
