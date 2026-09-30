"""Reliability and Survival: Survival, Fit Proportional Hazards, Life
Distribution and Fit Parametric Survival.

Survival is statsmodels' SurvfuncRight (the Kaplan-Meier product-limit
estimate with Greenwood's standard errors) and survdiff (the log-rank test
and the weighted tests between groups); Fit Proportional Hazards is
statsmodels' PHReg. Every parametric fit -- the Exponential, Weibull and
Lognormal fits of Survival, the distributions of Life Distribution and the
regressions of Fit Parametric Survival -- is one location-scale model for
the time or its logarithm, with right censoring, fitted by maximum
likelihood as a statsmodels GenericLikelihoodModel:

    failure at t:   log f(t) = log phi(z) - log sigma - log t   (log-time families)
    censored at t:  log S(t) = log(1 - Phi(z))
    z = (g(t) - mu) / sigma,  g(t) = log t or t,  mu = x'beta

Phi is the smallest extreme value distribution for Weibull and SEV, the
largest for Frechet and LEV, the normal for Lognormal and Normal and the
logistic for Loglogistic and Logistic; Exponential is the Weibull with
sigma = 1. The likelihood is that of t itself (the log-time families carry
the Jacobian -log t), so -2 log L compares across families, as Life
Distribution's Model Comparisons do. The parameters are beta and log sigma;
their covariance is the inverse of the negative Hessian, and the intervals
of positive parameters are Wald intervals on the log scale.

A Freq column counts rows: Kaplan-Meier, the tests and PHReg see each row
as many times as its (whole-number) frequency; the parametric fits weight
the log-likelihood by it.
"""
import hashlib
import json
import math
import warnings

import numpy as np
import pandas as pd
from scipy import special, stats
from statsmodels.base.model import GenericLikelihoodModel
from statsmodels.duration.hazard_regression import PHReg
from statsmodels.duration.survfunc import SurvfuncRight, survdiff
from statsmodels.tools.numdiff import approx_fprime

from . import data, models
from .registry import api
from .util import code_head, col, one_line, table as rtable

EULER = 0.5772156649015329
LOG2PI = math.log(2 * math.pi)

# key: (label, standard distribution, log time, fixed sigma)
FAMILIES = {
    'weibull': ('Weibull', 'sev', True, None),
    'lognormal': ('Lognormal', 'normal', True, None),
    'loglogistic': ('Loglogistic', 'logistic', True, None),
    'frechet': ('Fréchet', 'lev', True, None),
    'exponential': ('Exponential', 'sev', True, 1.0),
    'normal': ('Normal', 'normal', False, None),
    'logistic': ('Logistic', 'logistic', False, None),
    'sev': ('SEV', 'sev', False, None),
    'lev': ('LEV', 'lev', False, None),
}
ORDER = ['weibull', 'lognormal', 'loglogistic', 'frechet', 'exponential', 'normal', 'logistic', 'sev', 'lev']
# mean and standard deviation of the standard distributions, for starting values
_MOMENTS = {'normal': (0.0, 1.0), 'logistic': (0.0, math.pi / math.sqrt(3)),
            'sev': (-EULER, math.pi / math.sqrt(6)), 'lev': (EULER, math.pi / math.sqrt(6))}


class NotApplicable(Exception):
    """A fit that the data do not allow (no failures, times not positive)."""


# ---- the standard distributions ------------------------------------------------

def _lpdf(base, z):
    if base == 'normal':
        return -0.5 * z * z - 0.5 * LOG2PI
    if base == 'logistic':
        a = np.abs(z)
        return -a - 2 * np.log1p(np.exp(-a))
    if base == 'sev':
        return z - np.exp(z)
    return -z - np.exp(-z)


def _lsf(base, z):
    """log S(z) = log(1 - Phi(z))."""
    if base == 'normal':
        return special.log_ndtr(-z)
    if base == 'logistic':
        return -(np.maximum(z, 0) + np.log1p(np.exp(-np.abs(z))))
    if base == 'sev':
        return -np.exp(z)
    return np.log(-np.expm1(-np.exp(-z)))


def _dlpdf(base, z):
    """d/dz log phi(z)."""
    if base == 'normal':
        return -z
    if base == 'logistic':
        return 1 - 2 * special.expit(z)
    if base == 'sev':
        return 1 - np.exp(z)
    return np.exp(-z) - 1


def _hazard(base, z):
    """phi(z) / S(z)."""
    if base == 'logistic':
        return special.expit(z)
    if base == 'sev':
        return np.exp(z)
    return np.exp(_lpdf(base, z) - _lsf(base, z))


def _cdf(base, z):
    if base == 'normal':
        return special.ndtr(z)
    if base == 'logistic':
        return special.expit(z)
    if base == 'sev':
        return -np.expm1(-np.exp(z))
    return np.exp(-np.exp(-z))


def _ppf(base, p):
    if base == 'normal':
        return special.ndtri(p)
    if base == 'logistic':
        return special.logit(p)
    if base == 'sev':
        return np.log(-np.log1p(-p))
    return -np.log(-np.log(p))


# ---- the censored location-scale model ------------------------------------------

class LocScale(GenericLikelihoodModel):
    """g(t) = x'beta + sigma * e with e standard `base`, right censored.
    Parameters: beta, then log sigma (unless sigma is fixed)."""

    def __init__(self, g, X, event, w, base, jac, sigma=None):
        self._ev = np.asarray(event, dtype=float) > 0
        self._w = np.asarray(w, dtype=float)
        self._base = base
        self._jac = np.asarray(jac, dtype=float)
        self._sigma = sigma
        super().__init__(np.asarray(g, dtype=float), np.asarray(X, dtype=float),
                         extra_params_names=None if sigma is not None else ['log sigma'])

    def _unpack(self, params):
        params = np.asarray(params, dtype=float)
        p = self.exog.shape[1]
        logs = math.log(self._sigma) if self._sigma is not None else float(params[p])
        return params[:p], logs

    def loglike(self, params):
        beta, logs = self._unpack(params)
        if not math.isfinite(logs) or abs(logs) > 40:
            return -1e300
        with np.errstate(all='ignore'):
            z = (self.endog - self.exog @ beta) * math.exp(-logs)
            ll = np.where(self._ev, _lpdf(self._base, z) - logs - self._jac, _lsf(self._base, z))
            v = float(np.dot(self._w, ll))
        return v if math.isfinite(v) else -1e300

    def score(self, params):
        beta, logs = self._unpack(params)
        with np.errstate(all='ignore'):
            inv = math.exp(-min(max(logs, -40.0), 40.0))
            z = (self.endog - self.exog @ beta) * inv
            a = np.where(self._ev, _dlpdf(self._base, z), -_hazard(self._base, z))
            wa = self._w * a
            g = -(wa @ self.exog) * inv
            if self._sigma is None:
                g = np.r_[g, -np.dot(wa, z) - np.dot(self._w, self._ev)]
        return np.asarray(g, dtype=float)

    def hessian(self, params):
        """The derivative of the analytic score, by central differences."""
        h = np.atleast_2d(approx_fprime(np.asarray(params, dtype=float), self.score, centered=True))
        return (h + h.T) / 2


def _start(g, X, w, base, fixed):
    m0, s0 = _MOMENTS[base]
    sw = np.sqrt(w)
    beta = np.linalg.lstsq(X * sw[:, None], g * sw, rcond=None)[0]
    r = g - X @ beta
    sd = math.sqrt(max(float(np.average(r * r, weights=w)), 0.0))
    if not math.isfinite(sd) or sd < 1e-8:
        sd = float(np.std(g)) or 1.0
    sigma = fixed if fixed is not None else max(sd / s0, 1e-6)
    beta = np.array(beta, dtype=float)
    beta[0] -= sigma * m0
    return beta if fixed is not None else np.r_[beta, math.log(sigma)]


def fit_ls(t, event, w, key, X=None, start=None):
    """Maximum likelihood fit of family `key` (FAMILIES) to times t with
    event (1 failure, 0 right censored) and weights w; X the design (its
    first column the constant). A dict: params, cov, llf, converged, ..."""
    label, base, logt, fixed = FAMILIES[key]
    t = np.asarray(t, dtype=float)
    event = np.asarray(event, dtype=float)
    w = np.asarray(w, dtype=float)
    if logt and np.any(t <= 0):
        raise NotApplicable('needs every time above zero')
    if not np.any(event > 0):
        raise NotApplicable('no failures: every time is censored')
    g = np.log(t) if logt else t
    jac = g if logt else np.zeros_like(t)
    X = np.ones((len(t), 1)) if X is None else np.asarray(X, dtype=float)
    mod = LocScale(g, X, event, w, base, jac, fixed)
    p0 = np.asarray(start, dtype=float) if start is not None else _start(g, X, w, base, fixed)
    nobs = len(t)

    def good(r):
        if r is None:
            return False
        p = np.asarray(r.params, dtype=float)
        if not np.all(np.isfinite(p)) or mod.loglike(p) <= -1e299:
            return False
        return float(np.max(np.abs(mod.score(p)))) / nobs < 1e-5

    res = None
    with warnings.catch_warnings():
        # the optimizers' own messages: convergence is checked here, and a
        # fit that does not converge says so in the result
        warnings.simplefilter('ignore')
        try:
            res = mod.fit(start_params=p0, method='bfgs', maxiter=3000, gtol=1e-9, disp=0)
        except Exception:
            res = None
        if not good(res):
            try:
                r0 = mod.fit(start_params=p0, method='nm', maxiter=40000, disp=0)
                res2 = mod.fit(start_params=r0.params, method='bfgs', maxiter=3000, gtol=1e-9, disp=0)
                if res is None or res2.llf > res.llf or not good(res):
                    res = res2
            except Exception:
                pass
    if res is None:
        raise NotApplicable('the fit failed')
    params = np.asarray(res.params, dtype=float)
    try:
        cov = np.asarray(res.cov_params(), dtype=float)
        if cov.shape != (len(params), len(params)) or not np.all(np.isfinite(cov)):
            cov = None
    except Exception:
        cov = None
    k = len(params)
    n = float(np.sum(w))
    llf = float(mod.loglike(params))
    return {'key': key, 'label': label, 'base': base, 'logt': logt, 'fixed': fixed, 'params': params, 'cov': cov,
            'llf': llf, 'k': k, 'n': n, 'converged': bool(good(res)), 'p': X.shape[1],
            'n_events': float(np.sum(w * (event > 0))), 'model': mod}


def _ic(llf, k, n):
    aic = -2 * llf + 2 * k
    aicc = aic + 2 * k * (k + 1) / (n - k - 1) if n - k - 1 > 0 else float('nan')
    return aicc, -2 * llf + k * math.log(n) if n > 0 else float('nan')


def _v2(f):
    """mu, log sigma, sigma and their 2x2 covariance of a one-sample fit."""
    p = f['params']
    V = f['cov'] if f['cov'] is not None else np.full((len(p), len(p)), np.nan)
    mu = float(p[0])
    if f['fixed'] is not None:
        return mu, math.log(f['fixed']), f['fixed'], np.array([[V[0, 0], 0.0], [0.0, 0.0]])
    return mu, float(p[1]), math.exp(float(p[1])), np.array([[V[0, 0], V[0, 1]], [V[1, 0], V[1, 1]]])


def cdf_band(f, t, alpha=0.05):
    """F(t) of a one-sample fit with its pointwise Wald interval (on z)."""
    mu, logs, sig, V = _v2(f)
    t = np.asarray(t, dtype=float)
    zc = stats.norm.ppf(1 - alpha / 2)
    with np.errstate(all='ignore'):
        g = np.where(t > 0, np.log(np.where(t > 0, t, 1.0)), -np.inf) if f['logt'] else t
        u = (g - mu) / sig
        var = V[0, 0] / sig ** 2 + 2 * u * V[0, 1] / sig + u * u * V[1, 1]
        sd = np.sqrt(np.maximum(var, 0))
        F = _cdf(f['base'], u)
        lo = _cdf(f['base'], u - zc * sd)
        hi = _cdf(f['base'], u + zc * sd)
    if f['logt']:
        F, lo, hi = (np.where(t > 0, a, 0.0) for a in (F, lo, hi))
    return F, lo, hi


def quantile_band(f, p, alpha=0.05):
    """The time at which a fraction p has failed, with its Wald interval."""
    mu, logs, sig, V = _v2(f)
    p = np.asarray(p, dtype=float)
    zc = stats.norm.ppf(1 - alpha / 2)
    with np.errstate(all='ignore'):
        zp = _ppf(f['base'], p)
        q = mu + sig * zp
        var = V[0, 0] + 2 * sig * zp * V[0, 1] + (sig * zp) ** 2 * V[1, 1]
        sd = np.sqrt(np.maximum(var, 0))
        lo, hi = q - zc * sd, q + zc * sd
        if f['logt']:
            q, lo, hi = np.exp(q), np.exp(lo), np.exp(hi)
    return q, lo, hi


def param_rows(f, alpha=0.05):
    """The parameters of a one-sample fit, JMP's way: location and scale,
    then the alternative parameterization (Weibull alpha, beta; the
    exponential mean theta)."""
    mu, logs, sig, V = _v2(f)
    zc = stats.norm.ppf(1 - alpha / 2)
    se_mu = math.sqrt(V[0, 0]) if V[0, 0] >= 0 else float('nan')
    se_s = math.sqrt(V[1, 1]) if V[1, 1] >= 0 else float('nan')
    rows = [{'parameter': 'location μ', 'estimate': mu, 'se': se_mu, 'lower': mu - zc * se_mu, 'upper': mu + zc * se_mu}]
    if f['fixed'] is None:
        rows.append({'parameter': 'scale σ', 'estimate': sig, 'se': sig * se_s, 'lower': math.exp(logs - zc * se_s), 'upper': math.exp(logs + zc * se_s)})
    alt = []
    if f['key'] == 'weibull':
        a = math.exp(mu)
        alt.append({'parameter': 'α (scale)', 'estimate': a, 'se': a * se_mu, 'lower': math.exp(mu - zc * se_mu), 'upper': math.exp(mu + zc * se_mu)})
        b = 1 / sig
        alt.append({'parameter': 'β (shape)', 'estimate': b, 'se': b * se_s, 'lower': math.exp(-logs - zc * se_s), 'upper': math.exp(-logs + zc * se_s)})
    elif f['key'] == 'exponential':
        th = math.exp(mu)
        alt.append({'parameter': 'θ (mean)', 'estimate': th, 'se': th * se_mu, 'lower': math.exp(mu - zc * se_mu), 'upper': math.exp(mu + zc * se_mu)})
    return rows, alt


PARAM_COLS = lambda alpha: [col('parameter', 'Parameter', 'text'), col('estimate', 'Estimate'), col('se', 'Std Error'),  # noqa: E731
                            col('lower', f'Lower {100 * (1 - alpha):g}%'), col('upper', f'Upper {100 * (1 - alpha):g}%')]


# ---- the data -------------------------------------------------------------------

def censored_flags(table_id, censor, values, code):
    """True where the censor column holds the censor code."""
    if data.meta(table_id, censor).get('dataType') == 'numeric':
        try:
            c = float(str(code).strip())
        except ValueError:
            raise ValueError(f'the censor code {code!r} is not a number, and the censor column {censor} is numeric') from None
        return np.asarray(values, dtype=float) == c
    return np.array([str(v) == str(code).strip() for v in values], dtype=bool)


def _code_literal(table_id, censor, code):
    if data.meta(table_id, censor).get('dataType') == 'numeric':
        try:
            return repr(float(str(code).strip()))
        except ValueError:
            return repr(str(code))
    return json.dumps(str(code).strip())


def read(table_id, time, rows=None, censor=None, censor_code=1, group=None, freq=None):
    """The rows with a time (and censor, group and freq values when those
    are given): t, event (1 failure, 0 censored), whole-number frequencies,
    the page's row numbers, and the group codes and levels."""
    df = data.frame(table_id, [time, censor, group, freq], rows, dropna=True, as_category=False)
    t = df[time].to_numpy(float) if len(df) else np.zeros(0)
    ok = np.isfinite(t)
    f = np.ones(len(df))
    if freq:
        f = np.floor(df[freq].to_numpy(float) + 1e-9)
        ok &= np.isfinite(f) & (f >= 1)
    ev = np.ones(len(df))
    if censor and len(df):
        ev = (~censored_flags(table_id, censor, df[censor].to_numpy(), censor_code)).astype(float)
    df = df[ok]
    out = {'t': t[ok], 'event': ev[ok], 'freq': f[ok].astype(int), 'rows': df.index.to_numpy(), 'levels': [None], 'codes': np.zeros(int(ok.sum()), dtype=int)}
    if group:
        s = data.series(table_id, group, df.index, as_category=True)
        if isinstance(s.dtype, pd.CategoricalDtype):
            present = set(s.dropna().unique().tolist())
            levels = [lv for lv in s.cat.categories if lv in present]
            codes = np.asarray(pd.Categorical(s, categories=levels).codes)
        else:
            levels = sorted(pd.unique(s.dropna()).tolist())
            codes = np.searchsorted(np.asarray(levels, dtype=float), s.to_numpy(float))
        out['levels'] = levels
        out['codes'] = codes
    return out


def _expand(t, e, f):
    if np.all(f == 1):
        return t, e
    return np.repeat(t, f), np.repeat(e, f)


# ---- the code shown: the report's rows, and the graphs as matplotlib code ---------
# Every result's code reads the whole table as File > Export CSV writes it
# and keeps the report's rows: a By group's (its where lines), without the
# group's rows that the report leaves out (excluded, filtered out). Under
# each graph the report shows Python that draws it with matplotlib, with the
# light theme's colours and the graph's size at 100 pixels an inch.
J = json.dumps
PLT = 'import matplotlib.pyplot as plt'
BASE, TEXT, MUTED = '#2f6690', '#352921', '#786b5d'
PALETTE = ['#2f6690', '#d9822b', '#3a7d44', '#b0413e', '#6c5b7b', '#1f9e89', '#c0a000', '#8c564b', '#e377c2', '#7f7f7f', '#17becf', '#9467bd']
# smui-p-survival.js FIT_COLORS: a fitted distribution's colour, by its place in DISTS
FIT_COLORS = ['#b0413e', '#3a7d44', '#6c5b7b', '#c0a000', '#1f9e89', '#8c564b', '#e377c2', '#17becf', '#7f7f7f', '#2f6690']
DISTS = ['weibull', 'lognormal', 'exponential', 'frechet', 'loglogistic', 'normal', 'sev', 'logistic', 'lev']


def _lit(v):
    """A value as a Python literal: text quoted, a whole number without a point."""
    if isinstance(v, str):
        return J(v)
    if v is None:
        return 'None'
    v = float(v)
    if not math.isfinite(v):
        return 'np.nan' if v != v else ('np.inf' if v > 0 else '-np.inf')
    return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)


def _level_text(v):
    if isinstance(v, (float, np.floating)) and math.isfinite(v):
        return str(int(v)) if float(v).is_integer() and abs(v) < 1e15 else f'{float(v):.10g}'
    return str(v)


def _value_text(table, name, v):
    """A value as the table shows it, for a comment: a date as a date."""
    kind = ((data.meta(table, name).get('format') or {}).get('kind') or '') if table in data.TABLES else ''
    if kind.startswith('date') and isinstance(v, (int, float)) and math.isfinite(v):
        ts = pd.Timestamp(int(v), unit='ms')
        return ts.strftime('%Y-%m-%d' if kind == 'date' else '%Y-%m-%d %H:%M:%S')
    return _level_text(v)


def keep_lines(table, rows, where=None):
    """After the head: the By group's rows (its where lines), then the drop
    of the rows of the group that the report leaves out."""
    if table not in data.TABLES:
        return []
    n = data.TABLES[table]['n']
    match = np.ones(n, dtype=bool)
    out = []
    for w in where or []:
        c, v = w['column'], w['value']
        raw = data.raw(table, c)
        if data.meta(table, c).get('dataType') == 'numeric':
            match &= np.asarray(raw, dtype=float) == float(v)
        else:
            match &= np.array([x == v for x in raw], dtype=bool)
        out.append(f'df = df[df[{J(c)}] == {_lit(v)}]   # only the rows where {one_line(c)} is {one_line(_value_text(table, c, v))}')
    if rows is not None:
        keep = np.zeros(n, dtype=bool)
        keep[np.asarray(rows, dtype=int)] = True
        drop = np.flatnonzero(match & ~keep)
        if len(drop):
            out.append(f'df = df.drop(index=[{", ".join(str(int(r)) for r in drop)}])   # the rows the report leaves out')
    return out


def _inch(px):
    return f'{round(float(px)) / 100:g}'


def _read_code(table_id, table_name, time, censor, code, freq, cols, imports, keep=()):
    lines = [code_head(table_name, imports), *keep, f'd = df.dropna(subset={json.dumps([c for c in cols if c])})']
    if freq:
        lines.append(f'd = d[d[{J(freq)}] >= 1]   # a count of at least 1')
        lines.append(f'd = d.loc[d.index.repeat(np.floor(d[{json.dumps(freq)}] + 1e-9).astype(int))]   # Freq: each row as many times as its count')
    if censor:
        is_num = data.meta(table_id, censor).get('dataType') == 'numeric'
        lhs = f'd[{json.dumps(censor)}]' if is_num else f'd[{json.dumps(censor)}].astype(str)'
        lines.append(f'event = ({lhs} != {_code_literal(table_id, censor, code)}).astype(int).to_numpy()   # 1 = failure, 0 = censored')
    else:
        lines.append('event = np.ones(len(d), dtype=int)   # no censor column: every time is a failure')
    lines.append(f't = d[{json.dumps(time)}].to_numpy(float)')
    return lines


# ---- Kaplan-Meier ------------------------------------------------------------------

def _loglog(S, se, z):
    """The log(-log) transformed Greenwood interval, pointwise."""
    with np.errstate(all='ignore'):
        ok = (S > 0) & (S < 1) & np.isfinite(se) & (se > 0)
        v = np.where(ok, se / np.abs(S * np.log(np.where(ok, S, 0.5))), np.nan)
        lo = np.where(ok, S ** np.exp(z * v), np.nan)
        hi = np.where(ok, S ** np.exp(-z * v), np.nan)
    return lo, hi


def _km(t, e, f, alpha=0.05, times=None, probs=None, simultaneous=False):
    te, ee = _expand(t, e, f)
    n = len(te)
    out = {'n': int(n), 'failed': int(ee.sum()), 'censored': int(n - ee.sum())}
    if n == 0:
        return out
    z = stats.norm.ppf(1 - alpha / 2)
    tau = float(te.max())
    t0 = min(0.0, float(te.min()))
    if not np.any(ee > 0):
        # no failures: the curve stays at 1
        et = np.zeros(0)
        sp = se = nr_e = d_e = np.zeros(0)
        sf = None
    else:
        sf = SurvfuncRight(te, ee)
        et = np.asarray(sf.surv_times, dtype=float)
        sp = np.asarray(sf.surv_prob, dtype=float)
        se = np.asarray(sf.surv_prob_se, dtype=float)
        nr_e = np.asarray(sf.n_risk, dtype=float)
        d_e = np.asarray(sf.n_events, dtype=float)
    lo, hi = _loglog(sp, se, z)

    # every distinct time: the counts, and the estimate carried from the last failure
    ut, pos = np.unique(te, return_inverse=True)
    m = np.bincount(pos, minlength=len(ut)).astype(float)
    d = np.bincount(pos, weights=ee, minlength=len(ut))
    at_risk = n - np.cumsum(m) + m
    k = np.searchsorted(et, ut, side='right') - 1
    has = k >= 0
    kk = np.maximum(k, 0)
    S = np.where(has, sp[kk] if len(sp) else 1.0, 1.0)
    SE = np.where(has, se[kk] if len(se) else 0.0, 0.0)
    L = np.where(has, lo[kk] if len(lo) else np.nan, np.nan)
    U = np.where(has, hi[kk] if len(hi) else np.nan, np.nan)
    out['table'] = {'time': ut, 'surv': S, 'fail': 1 - S, 'se': SE, 'lower': L, 'upper': U,
                    'failed': d, 'censored': m - d, 'at_risk': at_risk}

    # the step curve for the plot: from (t0, 1) through each failure to the largest time
    px = np.r_[t0, et, tau]
    py = np.r_[1.0, sp, sp[-1] if len(sp) else 1.0]
    pl = np.r_[1.0, np.where(np.isfinite(lo), lo, sp), (lo[-1] if np.isfinite(lo[-1]) else sp[-1]) if len(sp) else 1.0]
    pu = np.r_[1.0, np.where(np.isfinite(hi), hi, sp), (hi[-1] if np.isfinite(hi[-1]) else sp[-1]) if len(sp) else 1.0]
    out['plot'] = {'x': px, 'y': py, 'lower': pl, 'upper': pu}
    if simultaneous and sf is not None and abs(alpha - 0.05) < 1e-12:
        with np.errstate(all='ignore'):
            lcb, ucb = sf.simultaneous_cb(alpha=0.05, method='hw', transform='log')
            # Near the first failures, where the estimate is still close to 1,
            # the band spans nearly 0 to 1 by construction; it is left out
            # where it is more than three times as wide as the pointwise
            # interval on the log(-log) scale.
            g = np.log(-np.log(sp))
            wide = np.abs(np.log(-np.log(lcb)) - g)
            point = stats.norm.ppf(0.975) * se / np.abs(sp * np.log(sp))
            keep = np.isfinite(wide) & np.isfinite(point) & (wide <= 3 * point) & (sp > 0)
        lcb = np.where(keep, lcb, np.nan)
        ucb = np.where(keep, ucb, np.nan)
        out['plot']['lcb'] = np.r_[np.nan, lcb, lcb[-1]]
        out['plot']['ucb'] = np.r_[np.nan, ucb, ucb[-1]]

    # the restricted mean: the area under the curve up to the largest time,
    # with the variance sum A_i^2 d_i / (n_i (n_i - d_i))
    widths = np.diff(np.r_[t0, et, tau])
    out['mean'] = float(np.sum(np.r_[1.0, sp] * widths))
    if len(et):
        area_after = np.cumsum((sp * widths[1:])[::-1])[::-1]
        with np.errstate(all='ignore'):
            term = np.where(nr_e > d_e, area_after ** 2 * d_e / (nr_e * (nr_e - d_e)), 0.0)
        out['mean_se'] = float(math.sqrt(np.sum(term)))
    else:
        out['mean_se'] = float('nan')
    out['mean_biased'] = bool(len(sp) == 0 or sp[-1] > 0)
    # quantiles of the failure time
    if sf is not None:
        with np.errstate(all='ignore'):
            out['median'] = float(sf.quantile(0.5))
            ml, mu = sf.quantile_ci(0.5, alpha=alpha, method='cloglog')
            out['median_lower'], out['median_upper'] = float(ml), float(mu)
            out['q25'] = float(sf.quantile(0.25))
            out['q75'] = float(sf.quantile(0.75))
    else:
        out.update({'median': float('nan'), 'median_lower': float('nan'), 'median_upper': float('nan'), 'q25': float('nan'), 'q75': float('nan')})
    if times:
        est = []
        for tt in times:
            j = int(np.searchsorted(et, float(tt), side='right') - 1)
            s_ = float(sp[j]) if j >= 0 else 1.0
            est.append({'time': float(tt), 'surv': s_, 'fail': 1 - s_, 'se': float(se[j]) if j >= 0 else 0.0,
                        'lower': float(lo[j]) if j >= 0 else float('nan'), 'upper': float(hi[j]) if j >= 0 else float('nan')})
        out['est_times'] = est
    if probs:
        est = []
        for p in probs:
            if sf is None or not 0 < float(p) < 1:
                est.append({'p': float(p), 'time': float('nan'), 'lower': float('nan'), 'upper': float('nan')})
                continue
            with np.errstate(all='ignore'):
                q = float(sf.quantile(float(p)))
                a, b = sf.quantile_ci(float(p), alpha=alpha, method='cloglog')
            est.append({'p': float(p), 'time': q, 'lower': float(a), 'upper': float(b)})
        out['est_probs'] = est
    out['_steps'] = (et, sp)
    return out


def _row_points(t, e, rows, steps):
    """One point per row: its time, the estimate at that time (after the
    step), and whether it failed."""
    et, sp = steps
    k = np.searchsorted(et, t, side='right') - 1
    S = np.where(k >= 0, sp[np.maximum(k, 0)] if len(sp) else 1.0, 1.0)
    return {'rows': rows, 'time': t, 'surv': S, 'event': e}


@api('survival.km')
def km(table, time, rows=None, censor=None, censor_code=1, group=None, freq=None, alpha=0.05,
       times=None, probs=None, simultaneous=False, where=None, plot=None, table_name='data'):
    """Survival: the product-limit estimate per group (and combined), the
    summaries, and the tests between groups. where: the By group's; plot:
    the graphs' display options, for their code (plot_code)."""
    r = read(table, time, rows, censor, censor_code, group, freq)
    t, e, f, rws, codes = r['t'], r['event'], r['freq'], r['rows'], r['codes']
    if not len(t):
        return {'error': 'no rows with a time' + (', a censor value' if censor else '') + (' and a group' if group else '')}
    groups = []
    for i, lv in enumerate(r['levels']):
        m = codes == i
        g = _km(t[m], e[m], f[m], alpha, times, probs, simultaneous)
        g['level'] = lv
        g['points'] = _row_points(t[m], e[m], rws[m], g.pop('_steps'))
        groups.append(g)
    out = {'time': time, 'groups': groups, 'alpha': alpha, 'grouped': bool(group)}
    if group and len(groups) > 1:
        c = _km(t, e, f, alpha, times, probs, simultaneous)
        c.pop('_steps')
        c['level'] = None
        out['combined'] = c
        te, ee = _expand(t, e, f)
        ge = np.repeat(codes, f) if not np.all(f == 1) else codes
        tests = []
        for label, wt, kw in (('Log-Rank', None, {}), ('Wilcoxon', 'gb', {}), ('Tarone-Ware', 'tw', {}), ('Fleming-Harrington (ρ = 1)', 'fh', {'fh_p': 1.0})):
            try:
                with np.errstate(all='ignore'):
                    chi, p = survdiff(te, ee, ge, weight_type=wt, **kw)
                tests.append({'test': label, 'chisq': float(chi), 'df': len(groups) - 1, 'p': float(p)})
            except Exception as ex:  # a singular variance: no failures to compare
                tests.append({'test': label, 'chisq': None, 'df': len(groups) - 1, 'p': None, 'note': str(ex)})
        out['tests'] = rtable([col('test', 'Test', 'text'), col('chisq', 'ChiSquare'), col('df', 'DF', 'int'), col('p', 'Prob>ChiSq', 'p')], tests)
    else:
        out['combined'] = None
        out['tests'] = None
    lines = _read_code(table, table_name, time, censor, censor_code, freq, [time, censor, group, freq],
                       ['from statsmodels.duration.survfunc import SurvfuncRight, survdiff'], keep_lines(table, rows, where))
    if group:
        lines += [f'for level in [{", ".join(_lit(v) for v in r["levels"])}]:   # the levels of {group} with rows, in the table\'s order',
                  f'    sf = SurvfuncRight(t[d[{json.dumps(group)}] == level], event[d[{json.dumps(group)}] == level])',
                  '    print(level, sf.quantile(0.5), sf.quantile_ci(0.5, alpha=%g, method="cloglog"))' % alpha,
                  '    print(sf.summary())',
                  f'g = d[{json.dumps(group)}]',
                  "print(survdiff(t, event, g))                     # log-rank: chi-square, p",
                  "print(survdiff(t, event, g, weight_type='gb'))   # Wilcoxon (Gehan-Breslow)",
                  "print(survdiff(t, event, g, weight_type='tw'))   # Tarone-Ware",
                  "print(survdiff(t, event, g, weight_type='fh', fh_p=1))   # Fleming-Harrington"]
    else:
        lines += ['sf = SurvfuncRight(t, event)',
                  'print(sf.summary())   # time, survival, its standard error (Greenwood), at risk, failures',
                  'print(sf.quantile(0.5), sf.quantile_ci(0.5, alpha=%g, method="cloglog"))' % alpha]
    out['code'] = '\n'.join(lines)
    if plot is not None:
        ctx = dict(table=table, rows=rows, where=where, table_name=table_name, time=time, censor=censor, code=censor_code, group=group, freq=freq,
                   levels=r['levels'], alpha=alpha)
        out['plot_code'] = {'survival': _km_plot(ctx, plot, False), 'failure': _km_plot(ctx, plot, True),
                            'lin': {k: _lin_plot(ctx, plot, k, bool((plot.get('lin') or {}).get(k))) for k in ('exponential', 'weibull', 'lognormal')}}
    return out


def _plot_read(ctx):
    """The lines that read a survival graph's rows: a time and every value
    the report uses, a count of at least 1 (Freq), and each row's event."""
    T, C, G, F = ctx['time'], ctx['censor'], ctx.get('group'), ctx['freq']
    L = [f'T = {J(T)}', f'd = df.dropna(subset={J([c for c in (T, C, G, F) if c])}).copy()   # the rows with a time and every value the report uses']
    if F:
        L += [f'd = d[np.floor(d[{J(F)}] + 1e-9) >= 1]   # a count of at least 1 (Freq)', f'd["n"] = np.floor(d[{J(F)}] + 1e-9).astype(int)   # each row counts that many times']
    else:
        L.append('d["n"] = 1')
    if C:
        is_num = data.meta(ctx['table'], C).get('dataType') == 'numeric'
        lhs = f'd[{J(C)}]' if is_num else f'd[{J(C)}].astype(str)'
        L.append(f'd["event"] = ({lhs} != {_code_literal(ctx["table"], C, ctx["code"])}).astype(int)   # 1 a failure, 0 censored (the Censor Code marks a censored row)')
    else:
        L.append('d["event"] = 1   # no Censor column: every time is a failure')
    return L


def _groups_lines(ctx, plot):
    """The groups (the Grouping's levels in the table's order), their names
    as the page writes them and their colours; and whether there are several."""
    levels = ctx['levels']
    if not ctx.get('group'):
        return [f'groups = [(d, {J(ctx["time"])}, "{BASE}")]   # one curve of every row'], False
    # the page's names of the levels ([[value, name], ...]); else as the page writes a value
    names = {(float(v) if isinstance(v, (int, float)) else str(v)): nm for v, nm in (plot.get('labels') or [])}
    labels = [names.get(float(v) if isinstance(v, (int, float, np.floating)) else str(v), _level_text(v)) for v in levels]
    multi = len(levels) > 1
    colors = [PALETTE[i % len(PALETTE)] if multi else BASE for i in range(len(levels))]
    G = J(ctx['group'])
    return [f'levels = [{", ".join(_lit(v) for v in levels)}]   # the levels of {ctx["group"]} with rows, in the table\'s order',
            f'names = {J(labels)}   # as the page writes them',
            f'colors = {J(colors)}   # the page\'s palette',
            f'groups = [(d[d[{G}] == v], name, color) for v, name, color in zip(levels, names, colors)]'], multi


_KM_FN = [
    'def km(s):',
    '    """The product-limit estimate of the rows s, each row as many times as its count (statsmodels SurvfuncRight): the failure times, the estimate, its standard error (Greenwood)."""',
    '    t, e = np.repeat(s[T].to_numpy(float), s["n"]), np.repeat(s["event"].to_numpy(), s["n"])',
    '    if e.sum() == 0:   # no failures: the curve stays at 1',
    '        return np.zeros(0), np.zeros(0), np.zeros(0), t, None',
    '    sf = SurvfuncRight(t, e)',
    '    return np.asarray(sf.surv_times, float), np.asarray(sf.surv_prob, float), np.asarray(sf.surv_prob_se, float), t, sf',
    '',
    'def at(s, et, sp):',
    '    """Each row\'s estimate at its own time (after the step there)."""',
    '    k = np.searchsorted(et, s[T].to_numpy(float), side="right") - 1',
    '    return np.where(k >= 0, sp[np.maximum(k, 0)] if len(sp) else 1.0, 1.0)']


def _km_plot(ctx, plot, failure):
    """The survival (or failure) plot as the page draws it (kmPlot): a step
    curve per group from (min(0, the first time), 1) to the largest time,
    the pointwise and simultaneous bands when shown, the combined curve, the
    censored rows as ticks and the failures as points when shown."""
    o = lambda k: bool(plot.get(k))  # noqa: E731
    ci, pts, comb, sim = o('showCI'), o('showPoints'), o('showCombined'), o('simCI') and abs(ctx['alpha'] - 0.05) < 1e-12
    tr = (lambda e: f'1 - {e}') if failure else (lambda e: e)
    L = _plot_read(ctx)
    G, multi = _groups_lines(ctx, plot)
    L += G
    if ci:
        L.append(f'z = stats.norm.ppf({1 - ctx["alpha"] / 2!r})   # for the pointwise limits')
    L += [''] + _KM_FN + ['']
    L += ['def curve(s):',
          '    """The steps as the page draws them' + (', with the pointwise limits (Greenwood, on the log(-log) scale)' if ci else '') +
          (' and the Hall-Wellner bands' if sim else '') + '."""',
          '    et, sp, se, t, sf = km(s)',
          '    x = np.r_[min(0.0, t.min()), et, t.max()]',
          '    y = np.r_[1.0, sp, sp[-1] if len(sp) else 1.0]']
    if ci:
        L += ['    with np.errstate(all="ignore"):',
              '        ok = (sp > 0) & (sp < 1) & np.isfinite(se) & (se > 0)',
              '        v = np.where(ok, se / np.abs(sp * np.log(np.where(ok, sp, 0.5))), np.nan)',
              '        lo, hi = np.where(ok, sp ** np.exp(z * v), np.nan), np.where(ok, sp ** np.exp(-z * v), np.nan)',
              '    end = lambda b: (b[-1] if np.isfinite(b[-1]) else sp[-1]) if len(sp) else 1.0',
              '    lower = np.r_[1.0, np.where(np.isfinite(lo), lo, sp), end(lo)]',
              '    upper = np.r_[1.0, np.where(np.isfinite(hi), hi, sp), end(hi)]']
    else:
        L.append('    lower = upper = None')
    if sim:
        L += ['    lcb = ucb = None',
              '    if sf is not None:   # Hall-Wellner 95% simultaneous bands (log transform), left out where more than three times as wide as the pointwise interval (log(-log) scale)',
              '        with np.errstate(all="ignore"):',
              '            lcb, ucb = sf.simultaneous_cb(alpha=0.05, method="hw", transform="log")',
              '            wide = np.abs(np.log(-np.log(lcb)) - np.log(-np.log(sp)))',
              '            point = stats.norm.ppf(0.975) * se / np.abs(sp * np.log(sp))',
              '            keep = np.isfinite(wide) & np.isfinite(point) & (wide <= 3 * point) & (sp > 0)',
              '        lcb, ucb = np.where(keep, lcb, np.nan), np.where(keep, ucb, np.nan)',
              '        lcb, ucb = np.r_[np.nan, lcb, lcb[-1]], np.r_[np.nan, ucb, ucb[-1]]',
              '    return x, y, lower, upper, et, sp, lcb, ucb']
    else:
        L.append('    return x, y, lower, upper, et, sp, None, None')
    W, H = plot.get('size') or [560, 350]
    L += ['', f'fig, ax = plt.subplots(figsize=({_inch(W)}, {_inch(H)}), layout="constrained")',
          'for s, name, color in groups:',
          '    x, y, lower, upper, et, sp, lcb, ucb = curve(s)']
    if ci:
        a, b = (tr('upper'), tr('lower')) if failure else ('lower', 'upper')
        L.append(f'    ax.fill_between(x, {a}, {b}, step="post", color=color, alpha=0.15, linewidth=0)   # Show Confid Interval')
    if sim:
        L += ['    if lcb is not None:   # Show Simultaneous CI',
              '        for band in (lcb, ucb):',
              f'            ax.plot(x, {tr("band")}, drawstyle="steps-post", color=color, linewidth=1, linestyle=":")']
    L.append(f'    ax.plot(x, {tr("y")}, drawstyle="steps-post", color=color, linewidth=1.8, label=name)')
    if comb and multi:
        L += ['x, y = curve(d)[:2]   # Show Combined: every row together',
              f'ax.plot(x, {tr("y")}, drawstyle="steps-post", color="{MUTED}", linewidth=1.5, linestyle="--", label="Combined")']
    L += ['for s, name, color in groups:',
          '    et, sp = curve(s)[4:6]',
          f'    S = {tr("at(s, et, sp)")}',
          '    cens = s["event"].to_numpy() == 0',
          '    ax.plot(s[T].to_numpy()[cens], S[cens], linestyle="none", marker="|", markersize=6.5, markeredgewidth=1.6, color=color)   # the censored rows']
    if pts:
        L.append('    ax.plot(s[T].to_numpy()[~cens], S[~cens], linestyle="none", marker="o", markersize=3.6, color=color)   # Show Points: the failures')
    L += ['ax.set_ylim(-0.02, 1.02)', 'ax.set_xlabel(T)', f'ax.set_ylabel("{"Failure" if failure else "Surviving"}")']
    if multi:
        L.append(f'ax.legend(loc="{"lower right" if failure else "upper right"}", frameon=False, fontsize=8)')
    L += [f'fig.suptitle(T + " {"failure" if failure else "survival"} plot", fontsize=10)', 'plt.show()']
    imports = [PLT, 'from statsmodels.duration.survfunc import SurvfuncRight'] + (['from scipy import stats'] if ci or sim else [])
    return '\n'.join([code_head(ctx['table_name'], imports)] + keep_lines(ctx['table'], ctx['rows'], ctx['where']) + L)


_LIN = {  # the linearizing plots (LINPLOTS): the title, a log time axis, the y of an estimate S, the y title
    'exponential': ('Exponential Plot', False, '-np.log(S)', '−Log(Surviving)'),
    'weibull': ('Weibull Plot', True, 'np.log(-np.log(S))', 'Log(−Log(Surviving))'),
    'lognormal': ('Lognormal Plot', True, 'stats.norm.ppf(1 - S)', 'Normal Quantile of Failure'),
}


def _lin_plot(ctx, plot, kind, with_fit):
    """An exponential, Weibull or lognormal plot as the page draws it
    (linPlot): a point per failed row on axes where the distribution is a
    straight line, and with the fit its line, fitted as the report's code
    fits it (censored maximum likelihood with scipy)."""
    title, logx, yexpr, ylab = _LIN[kind]
    L = _plot_read(ctx)
    G, multi = _groups_lines(ctx, plot)
    L += G + [''] + _KM_FN + ['']
    W, H = plot.get('lin_size') or [420, 300]
    L += [f'fig, ax = plt.subplots(figsize=({_inch(W)}, {_inch(H)}), layout="constrained")',
          'xs = []',
          'for s, name, color in groups:',
          '    et, sp, se, t, sf = km(s)',
          '    S = at(s, et, sp)',
          '    keep = (s["event"].to_numpy() == 1) & (S > 0) & (S < 1)' + (' & (s[T].to_numpy() > 0)' if logx else '') + '   # the failed rows',
          f'    x = {"np.log(s[T].to_numpy()[keep])" if logx else "s[T].to_numpy()[keep]"}',
          '    S = S[keep]',
          f'    ax.scatter(x, {yexpr}, s=18, color=color, label=name)',
          '    xs += list(x)']
    if with_fit:
        L += ['lo = ' + ('min(xs) - 0.1 * (max(xs) - min(xs))' if logx else '0.0'), 'hi = max(xs) + 0.1 * (max(xs) - min(xs))',
              'for s, name, color in groups:   # the fits: on these axes a straight line',
              '    t, e = np.repeat(s[T].to_numpy(float), s["n"]), np.repeat(s["event"].to_numpy(), s["n"])',
              '    if e.sum() == 0' + (' or (t <= 0).any()' if logx or kind == 'exponential' else '') + ':   # no fit: no failures, or a time not above zero',
              '        continue']
        if kind == 'exponential':
            L += ['    mu = np.log(t.sum() / e.sum())   # the exponential MLE: theta is the total time over the failures',
                  '    ax.plot([lo, hi], [lo / np.exp(mu), hi / np.exp(mu)], color=color, linewidth=1.3, linestyle="--")']
        else:
            L.append('    data = stats.CensoredData(uncensored=t[e == 1], right=t[e == 0])   # censored maximum likelihood, as the report\'s code fits it')
            if kind == 'weibull':
                L += ['    c, _, scale = stats.weibull_min.fit(data, floc=0)   # beta (the shape), 0, alpha (the scale)', '    mu, sigma = np.log(scale), 1 / c']
            else:
                L += ['    sigma, _, scale = stats.lognorm.fit(data, floc=0)   # sigma, 0, exp(mu)', '    mu = np.log(scale)']
            L.append('    ax.plot([lo, hi], [(lo - mu) / sigma, (hi - mu) / sigma], color=color, linewidth=1.3, linestyle="--")')
    L += ['ax.set_xlabel("Log(" + T + ")")' if logx else 'ax.set_xlabel(T)', f'ax.set_ylabel({J(ylab)})']
    if multi:
        L.append('ax.legend(loc="upper left", frameon=False, fontsize=8)')
    L += [f'fig.suptitle(T + " {title}", fontsize=10)', 'plt.show()']
    imports = [PLT, 'from scipy import stats', 'from statsmodels.duration.survfunc import SurvfuncRight']
    return '\n'.join([code_head(ctx['table_name'], imports)] + keep_lines(ctx['table'], ctx['rows'], ctx['where']) + L)


@api('survival.fit_groups')
def fit_groups(table, time, rows=None, censor=None, censor_code=1, group=None, freq=None, dists=('weibull',), alpha=0.05, where=None, table_name='data'):
    """Survival's Exponential, Weibull and Lognormal fits, per group."""
    r = read(table, time, rows, censor, censor_code, group, freq)
    t, e, f, codes = r['t'], r['event'], r['freq'], r['codes']
    out = {'fits': []}
    notes = []
    for key in dists:
        if key not in FAMILIES:
            continue
        label = FAMILIES[key][0]
        rows_p, rows_f, lines = [], [], []
        for i, lv in enumerate(r['levels']):
            m = codes == i
            try:
                fit = _remember(_key(table, rows, 'group', time, censor, censor_code, group, freq, key, i),
                                lambda m=m: fit_ls(t[m], e[m], f[m], key))
            except NotApplicable as ex:
                rows_f.append({'level': lv, 'error': str(ex)})
                continue
            if not fit['converged']:
                notes.append(f'{label} fit{"" if lv is None else f" for {lv}"} did not converge')
            main, alt = param_rows(fit, alpha)
            mu, logs, sig, _ = _v2(fit)
            if key == 'weibull':
                show = alt + [dict(main[0], parameter='λ (extreme value location)'), dict(main[1], parameter='δ (extreme value scale)')]
            elif key == 'exponential':
                show = alt
            else:
                show = main
            for p in show:
                rows_p.append({'level': lv, **p})
            aicc, bic = _ic(fit['llf'], fit['k'], fit['n'])
            rows_f.append({'level': lv, 'n': fit['n'], 'events': fit['n_events'], 'm2ll': -2 * fit['llf'], 'aicc': aicc, 'bic': bic,
                           'mu': mu, 'sigma': sig})
        out['fits'].append({'dist': key, 'label': label, 'params': rows_p, 'fit': rows_f})
    for n_ in notes:
        warnings.warn(n_)
    lines = _read_code(table, table_name, time, censor, censor_code, freq, [time, censor, group, freq], ['from scipy import stats'], keep_lines(table, rows, where))
    lines += ['# censored maximum likelihood with scipy: the failures as exact values, the censored as right-censored',
              'data = stats.CensoredData(uncensored=t[event == 1], right=t[event == 0])']
    for key in dists:
        if key == 'weibull':
            lines.append('print(stats.weibull_min.fit(data, floc=0))   # beta (shape), 0, alpha (scale)')
        elif key == 'lognormal':
            lines.append('print(stats.lognorm.fit(data, floc=0))       # sigma, 0, exp(mu)')
        elif key == 'exponential':
            lines.append('print(t.sum() / event.sum())                 # theta: the exponential MLE is total time / failures')
    lines.append('# the standard errors come from the Hessian of the log-likelihood (statsmodels GenericLikelihoodModel)')
    out['code'] = '\n'.join(lines)
    return out


# ---- a cache of fits, so that calculators and saved columns need no refit ----------

_FITS = {}
_FIT_ORDER = []


def _key(table_id, rows, *parts):
    h = 'all' if rows is None else hashlib.sha1(np.asarray(rows, dtype=np.int64).tobytes()).hexdigest()
    return json.dumps([table_id, data.version(table_id), h, parts], default=str)


def _remember(key, make):
    if key in _FITS:
        return _FITS[key]
    v = make()
    _FITS[key] = v
    _FIT_ORDER.append(key)
    while len(_FIT_ORDER) > 96:
        _FITS.pop(_FIT_ORDER.pop(0), None)
    return v


# ---- Life Distribution --------------------------------------------------------------

def _grids(t):
    tp = t[t > 0]
    out = {}
    if len(tp):
        lo, hi = float(tp.min()), float(tp.max())
        out['log'] = np.geomspace(lo / 5, hi * 5, 181)
    lo, hi = float(t.min()), float(t.max())
    pad = 0.6 * (hi - lo if hi > lo else abs(hi) + 1)
    out['lin'] = np.linspace(lo - pad, hi + pad, 181)
    return out


@api('lifedist.fit')
def lifedist_fit(table, time, rows=None, censor=None, censor_code=1, freq=None, dists=('weibull', 'lognormal'), alpha=0.05,
                 times=None, probs=None, where=None, plot=None, table_name='data'):
    """Life Distribution: the nonparametric estimate, the chosen
    distributions fitted with censoring, their comparison, and the
    probabilities and quantiles asked for."""
    r = read(table, time, rows, censor, censor_code, None, freq)
    t, e, f, rws = r['t'], r['event'], r['freq'], r['rows']
    if not len(t):
        return {'error': 'no rows with a time' + (' and a censor value' if censor else '')}
    km_ = _km(t, e, f, alpha)
    et, sp = km_.pop('_steps')
    # the probability plot's points: one per failed row, at the midpoint of
    # the jump of the estimate there (Meeker and Escobar's plotting position)
    j = np.searchsorted(et, t, side='left')
    fr = e > 0
    before = np.where(j > 0, sp[np.maximum(j - 1, 0)] if len(sp) else 1.0, 1.0)
    after = np.where(j < len(sp), sp[np.minimum(j, max(len(sp) - 1, 0))] if len(sp) else 1.0, 1.0)
    mid = 1 - (before + after) / 2
    out = {'time': time, 'n': km_['n'], 'failed': km_['failed'], 'censored': km_['censored'], 'alpha': alpha,
           'nonparametric': {'time': km_['table']['time'], 'fail': km_['table']['fail'], 'se': km_['table']['se'],
                             'lower': 1 - km_['table']['upper'], 'upper': 1 - km_['table']['lower'],
                             'failed': km_['table']['failed'], 'censored': km_['table']['censored'], 'at_risk': km_['table']['at_risk']},
           'points': {'rows': rws[fr], 'time': t[fr], 'prob': mid[fr]}, 'fits': []}
    grids = _grids(t)
    out['grids'] = grids
    comp = []
    for key in dists:
        if key not in FAMILIES:
            continue
        label = FAMILIES[key][0]
        try:
            fit = _remember(_key(table, rows, 'life', time, censor, censor_code, freq, key), lambda key=key: fit_ls(t, e, f, key))
        except NotApplicable as ex:
            out['fits'].append({'dist': key, 'label': label, 'error': str(ex)})
            continue
        if not fit['converged']:
            warnings.warn(f'the {label} fit did not converge; its estimates are the last iteration')
        main, alt = param_rows(fit, alpha)
        mu, logs, sig, V = _v2(fit)
        aicc, bic = _ic(fit['llf'], fit['k'], fit['n'])
        item = {'dist': key, 'label': label, 'params': rtable(PARAM_COLS(alpha), main), 'alt': rtable(PARAM_COLS(alpha), alt) if alt else None,
                'm2ll': -2 * fit['llf'], 'aicc': aicc, 'bic': bic, 'k': fit['k'], 'mu': mu, 'sigma': sig, 'logt': fit['logt'], 'base': fit['base'],
                'cov': rtable([col('name', 'Parameter', 'text'), col('mu', 'location μ'), col('logs', 'log σ')],
                             [{'name': 'location μ', 'mu': V[0, 0], 'logs': V[0, 1]}] + ([] if fit['fixed'] is not None else [{'name': 'log σ', 'mu': V[1, 0], 'logs': V[1, 1]}])),
                'curves': {}}
        for gk, grid in grids.items():
            F, lo, hi = cdf_band(fit, grid, alpha)
            item['curves'][gk] = {'F': F, 'lower': lo, 'upper': hi}
        if times:
            F, lo, hi = cdf_band(fit, np.asarray(times, dtype=float), alpha)
            item['at_times'] = [{'time': float(tt), 'F': float(a), 'lower': float(b), 'upper': float(c), 'S': 1 - float(a)} for tt, a, b, c in zip(times, F, lo, hi)]
        if probs:
            ok_p = [p for p in probs if 0 < float(p) < 1]
            q, lo, hi = quantile_band(fit, np.asarray(ok_p, dtype=float), alpha) if ok_p else ([], [], [])
            item['at_probs'] = [{'p': float(p), 'time': float(a), 'lower': float(b), 'upper': float(c)} for p, a, b, c in zip(ok_p, q, lo, hi)]
        out['fits'].append(item)
        comp.append({'dist': key, 'label': label, 'k': fit['k'], 'm2ll': -2 * fit['llf'], 'aicc': aicc, 'bic': bic})
    comp.sort(key=lambda x: x['aicc'] if x['aicc'] is not None and math.isfinite(x['aicc']) else math.inf)
    if comp:
        best = comp[0]['aicc']
        tot = sum(math.exp(-0.5 * (c['aicc'] - best)) for c in comp if math.isfinite(c['aicc']))
        for c in comp:
            c['weight'] = math.exp(-0.5 * (c['aicc'] - best)) / tot if math.isfinite(c['aicc']) and tot > 0 else None
    out['comparison'] = rtable([col('label', 'Distribution', 'text'), col('k', 'Nparm', 'int'), col('m2ll', '−2LogLikelihood'), col('aicc', 'AICc'),
                               col('weight', 'AICc Weight'), col('bic', 'BIC')], comp)
    lines = _read_code(table, table_name, time, censor, censor_code, freq, [time, censor, freq], ['from scipy import stats, optimize', 'from scipy.special import log_ndtr'],
                       keep_lines(table, rows, where))
    lines += ['# each distribution: log f for the failures, log S for the censored; the log-time families',
              '# (Weibull, Lognormal, Loglogistic, Frechet, Exponential) are location-scale models for log t',
              'X = np.ones((len(t), 1))   # the location only']
    for key in dists:
        if key in FAMILIES:
            lines.append(_nll_code(key, 'X'))
    out['code'] = '\n'.join(lines)
    if plot is not None:
        ctx = dict(table=table, rows=rows, where=where, table_name=table_name, time=time, censor=censor, code=censor_code, group=None, freq=freq, alpha=alpha)
        out['plot_code'] = {'prob': _life_prob_plot(ctx, out, plot), 'cdf': {f['dist']: _life_cdf_plot(ctx, out, f, plot) for f in out['fits'] if not f.get('error')}}
    return out


_Z = {  # (log f(z) , log S(z)) of the standard distributions, as code
    'sev': ('z - np.exp(z)', '-np.exp(z)'),
    'lev': ('-z - np.exp(-z)', 'np.log(-np.expm1(-np.exp(-z)))'),
    'normal': ('-z**2/2 - np.log(2*np.pi)/2', 'log_ndtr(-z)'),
    'logistic': ('-z - 2*np.log1p(np.exp(-z))', '-np.log1p(np.exp(z))'),
}


def _nll_code(key, X='X'):
    label, base, logt, fixed = FAMILIES[key]
    lf, ls = _Z[base]
    y = 'np.log(t)' if logt else 't'
    jac = ' - np.log(t)' if logt else ''
    sig = '1.0' if fixed is not None else 'np.exp(p[-1])'
    nb = 'p' if fixed is not None else 'p[:-1]'
    k0 = f'np.r_[{y}.mean(), np.zeros({X}.shape[1] - 1){", 0.0" if fixed is None else ""}]'
    return '\n'.join([
        f'def nll_{key}(p, X={X}):   # {label}',
        f'    s = {sig}; z = ({y} - X @ {nb}) / s',
        f'    return -np.sum(np.where(event == 1, {lf} - np.log(s){jac}, {ls}))',
        f'fit = optimize.minimize(nll_{key}, {k0}, method="BFGS"); print("{label}", fit.x, 2 * fit.fun)   # -2 log L',
    ])


# ---- Life Distribution's graphs as code ------------------------------------------------
# The scales of the probability plot (smui-p-survival.js SCALES): the
# vertical axis is q(F), q the quantile function of the scale's standard
# distribution; the log-time families have a log time axis.
_SCALE_CODE = {
    'nonparametric': ('Nonparametric', False, 'p'), 'weibull': ('Weibull', True, 'np.log(-np.log(1 - p))'),
    'lognormal': ('Lognormal', True, 'stats.norm.ppf(p)'), 'exponential': ('Exponential', False, '-np.log(1 - p)'),
    'frechet': ('Fréchet', True, '-np.log(-np.log(p))'), 'loglogistic': ('Loglogistic', True, 'np.log(p / (1 - p))'),
    'normal': ('Normal', False, 'stats.norm.ppf(p)'), 'sev': ('SEV', False, 'np.log(-np.log(1 - p))'),
    'logistic': ('Logistic', False, 'np.log(p / (1 - p))'), 'lev': ('LEV', False, '-np.log(-np.log(p))'),
}
_BASE_CDF = {'normal': 'stats.norm.cdf(z)', 'logistic': '1 / (1 + np.exp(-z))', 'sev': '-np.expm1(-np.exp(z))', 'lev': 'np.exp(-np.exp(-z))'}
_PROB_TICKS = [0.0001, 0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99, 0.995, 0.999, 0.9999]


def _life_fit_lines(keys):
    """The lines that fit each distribution as the report's code does (its
    negative log-likelihood minimised by BFGS), with the covariance of
    (location, log scale) from the Hessian, and give its CDF with pointwise
    Wald limits on z."""
    L = ['X = np.ones((len(t), 1))   # the location only',
         'zc = stats.norm.ppf(1 - alpha / 2)', '',
         'def fitted(nll, x0):',
         '    """The maximum likelihood estimates and their covariance: the inverse Hessian of -log L."""',
         '    r = optimize.minimize(nll, x0, method="BFGS")',
         '    return r.x, np.linalg.inv(np.atleast_2d(approx_hess3(r.x, nll)))',
         '',
         'def cdf(p, V, base, logt, x):',
         '    """F(x) of a fit, with its pointwise limits by the delta method on z = (g(x) - mu)/sigma, g the log for the log-time families."""',
         '    mu, logs = p[0], (p[1] if len(p) > 1 else 0.0)',
         '    V = V if V.shape == (2, 2) else np.array([[V[0, 0], 0.0], [0.0, 0.0]])',
         '    sig = np.exp(logs)',
         '    x = np.asarray(x, float)',
         '    with np.errstate(all="ignore"):',
         '        g = np.where(x > 0, np.log(np.where(x > 0, x, 1.0)), -np.inf) if logt else x',
         '        u = (g - mu) / sig',
         '        sd = np.sqrt(np.maximum(V[0, 0] / sig ** 2 + 2 * u * V[0, 1] / sig + u * u * V[1, 1], 0))',
         '        F, lo, hi = (base(q) for q in (u, u - zc * sd, u + zc * sd))',
         '    return (tuple(np.where(x > 0, a, 0.0) for a in (F, lo, hi)) if logt else (F, lo, hi))',
         '']
    for key in keys:
        label, base, logt, fixed = FAMILIES[key]
        L += [_nll_code(key, 'X').split('\nfit = ')[0],
              f'fits[{J(key)}] = fitted(nll_{key}, np.r_[{"np.log(t)" if logt else "t"}.mean(){"" if fixed is not None else ", 0.0"}]) + (lambda z: {_BASE_CDF[base]}, {logt})   # {label}: (mu{"" if fixed is not None else ", log sigma"}), their covariance, the standard CDF, a log-time family']
    return L


def _life_head(ctx):
    imports = [PLT, 'from scipy import stats, optimize', 'from scipy.special import log_ndtr', 'from statsmodels.tools.numdiff import approx_hess3',
               'from statsmodels.duration.survfunc import SurvfuncRight']
    L = _plot_read(ctx)
    L += ['t, event = np.repeat(d[T].to_numpy(float), d["n"]), np.repeat(d["event"].to_numpy(), d["n"])   # each row as many times as its count',
          f'alpha = {ctx["alpha"]!r}']
    return [code_head(ctx['table_name'], imports)] + keep_lines(ctx['table'], ctx['rows'], ctx['where']), L


def _life_prob_plot(ctx, res, plot):
    """Compare Distributions' probability plot as the page draws it
    (probPlot): the nonparametric estimate at each failed row on the
    scale's probability paper, each fitted distribution's CDF, with the
    pointwise limits of the one whose scale is shown."""
    scale = plot.get('scale') or 'weibull'
    label, log_scale, qexpr = _SCALE_CODE.get(scale, _SCALE_CODE['weibull'])
    shown = [f for f in res['fits'] if not f.get('error')]
    bands = bool(plot.get('bands', True))
    show_np = bool(plot.get('showNP', True))
    W, H = plot.get('prob_size') or [640, 380]
    head, L = _life_head(ctx)
    L += ['# the nonparametric estimate: at each failed row, the Kaplan-Meier estimate of the failure probability at the middle of its jump (Meeker and Escobar)',
          'sf = SurvfuncRight(t, event)',
          'et, sp = np.asarray(sf.surv_times, float), np.asarray(sf.surv_prob, float)',
          'tr, er = d[T].to_numpy(float), d["event"].to_numpy()',
          'j = np.searchsorted(et, tr, side="left")',
          'before = np.where(j > 0, sp[np.maximum(j - 1, 0)], 1.0)',
          'after = np.where(j < len(sp), sp[np.minimum(j, len(sp) - 1)], 1.0)',
          'pt, pp = tr[er > 0], (1 - (before + after) / 2)[er > 0]',
          'fits = {}']
    L += _life_fit_lines([f['dist'] for f in shown])
    L += ['', f'def q(p):   # the {label} scale',
          '    with np.errstate(all="ignore"):',
          f'        return {qexpr}',
          '',
          'pq = q(pp)',
          'keep = np.isfinite(pq)' + (' & (pt > 0)' if log_scale else ''),
          'px, py = pt[keep], pq[keep]']
    if scale == 'nonparametric':
        L.append('ylo, yhi = -0.02, 1.02')
    else:
        L += ['ylo, yhi = (py.min(), py.max()) if len(py) else (q(0.05), q(0.95))',
              'pad = 0.15 * (yhi - ylo or 1) + 0.15',
              'ylo, yhi = max(q(0.0001), ylo - pad), min(q(0.9999), yhi + pad)   # the points, and some room']
    L += ['tp = px if len(px) else pt' + ('[pt > 0]' if log_scale else '') + '   # the failed rows\' times',
          'xlo, xhi = tp.min(), tp.max()']
    if log_scale:
        L += ['xr = (xlo / 1.6, xhi * 1.6)',
              'grid = np.geomspace(tr[tr > 0].min() / 5, tr[tr > 0].max() * 5, 181)   # the report\'s grid']
    else:
        L += ['xr = (xlo - 0.12 * (xhi - xlo or 1), xhi + 0.12 * (xhi - xlo or 1))',
              'grid = np.linspace(tr.min() - 0.6 * (tr.max() - tr.min() or abs(tr.max()) + 1), tr.max() + 0.6 * (tr.max() - tr.min() or abs(tr.max()) + 1), 181)   # the report\'s grid']
    L += ['inside = (grid > 0) & (grid >= xr[0]) & (grid <= xr[1])' if log_scale else 'inside = (grid >= xr[0]) & (grid <= xr[1])',
          f'colors = {{{", ".join(f"{J(k)}: {J(FIT_COLORS[DISTS.index(k) % len(FIT_COLORS)])}" for k in [f["dist"] for f in shown])}}}   # the page\'s colours for the distributions',
          f'names = {{{", ".join(f"{J(f["dist"])}: {J(f["label"])}" for f in shown)}}}',
          f'fig, ax = plt.subplots(figsize=({_inch(W)}, {_inch(H)}), layout="constrained")',
          'for key, (p, V, base, logt) in fits.items():',
          '    F, lo, hi = cdf(p, V, base, logt, grid)',
          '    y = q(F)',
          '    ok = inside & np.isfinite(y) & (y >= ylo - 1) & (y <= yhi + 1)',
          '    x = grid[ok]']
    if bands and scale in [f['dist'] for f in shown]:
        L += [f'    if key == {J(scale)}:   # Show Confidence Bands: the pointwise limits of the fit whose scale is shown',
              '        L_, U_ = q(lo[ok]), q(hi[ok])',
              '        L_, U_ = np.where(np.isfinite(L_), L_, np.nan), np.where(np.isfinite(U_), U_, np.nan)',
              '        ax.plot(x, L_, color=colors[key], linewidth=0.8, linestyle=":")',
              '        ax.plot(x, U_, color=colors[key], linewidth=0.8, linestyle=":")',
              '        ax.fill_between(x, L_, U_, color=colors[key], alpha=0.1, linewidth=0)']
    L.append('    ax.plot(x, y[ok], color=colors[key], linewidth=1.8, label=names[key])')
    if show_np:
        L.append(f'ax.scatter(px, py, s=18, color="{TEXT}", label="Nonparametric", zorder=3)')
    if scale == 'nonparametric':
        L.append('ticks = [0, 0.2, 0.4, 0.6, 0.8, 1]')
    else:
        L += [f'ticks, last = [], -np.inf   # the probabilities at least a twelfth of the axis apart',
              f'for p in {_PROB_TICKS!r}:',
              '    v = q(p)',
              '    if v < ylo or v > yhi or v - last < (yhi - ylo) / 12:',
              '        continue',
              '    ticks.append(p)',
              '    last = v']
    L += ['ax.set_yticks([q(p) for p in ticks], [str(p) for p in ticks])', 'ax.set_ylim(ylo, yhi)', 'ax.set_xlim(*xr)']
    if log_scale:
        L += ['ax.set_xscale("log")',
              'e0, e1 = int(np.floor(np.log10(xr[0]))), int(np.ceil(np.log10(xr[1])))   # ticks at 1, 2 and 5 times the powers of ten (the powers alone over many decades)',
              'xt = [float(f"{m * 10.0 ** e:.6g}") for e in range(e0, e1 + 1) for m in ((1,) if e1 - e0 > 5 else (1, 2, 5)) if xr[0] <= m * 10.0 ** e <= xr[1]]',
              'ax.set_xticks(xt, [f"{v:g}" for v in xt])',
              'ax.minorticks_off()',
              'ax.set_xlim(*xr)']
    L += ['ax.set_xlabel(T)', 'ax.set_ylabel("Probability")']
    L.append('ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1), frameon=False, fontsize=8)' if W >= 560 else 'ax.legend(loc="upper left", frameon=False, fontsize=8)')
    L += [f'fig.suptitle(T + " {label} probability plot", fontsize=10)', 'plt.show()']
    return '\n'.join(head + L)


def _life_cdf_plot(ctx, res, f, plot):
    """A fit's Distribution Plot (cdfPlot): its CDF with the pointwise
    limits over the nonparametric estimate of the failure probability."""
    color = FIT_COLORS[DISTS.index(f['dist']) % len(FIT_COLORS)]
    W, H = plot.get('cdf_size') or [400, 250]
    head, L = _life_head(ctx)
    L += ['sf = SurvfuncRight(t, event)',
          'et, sp = np.asarray(sf.surv_times, float), np.asarray(sf.surv_prob, float)',
          'ut = np.unique(t)   # every distinct time',
          'k = np.searchsorted(et, ut, side="right") - 1',
          'Fn = 1 - np.where(k >= 0, sp[np.maximum(k, 0)], 1.0)   # the nonparametric estimate of the failure probability',
          'fits = {}']
    L += _life_fit_lines([f['dist']])
    lo = '0.0' if f['logt'] else 'ut.min() - 0.1 * (ut.max() - ut.min() or 1)'
    L += ['', f'lo, hi = {lo}, ut.max() + 0.1 * (ut.max() - ut.min() or 1)',
          'tr = d[T].to_numpy(float)',
          'pad = 0.6 * (tr.max() - tr.min() or abs(tr.max()) + 1)',
          'grid = np.linspace(tr.min() - pad, tr.max() + pad, 181)   # the report\'s grid',
          'grid = grid[(grid >= lo) & (grid <= hi)' + (' & (grid > 0)]' if f['logt'] else ']'),
          f'p, V, base, logt = fits[{J(f["dist"])}]',
          'F, L_, U_ = cdf(p, V, base, logt, grid)',
          f'fig, ax = plt.subplots(figsize=({_inch(W)}, {_inch(H)}), layout="constrained")',
          f'ax.fill_between(grid, L_, U_, color="{color}", alpha=0.15, linewidth=0)   # the pointwise limits',
          f'ax.plot(np.r_[min(0.0, ut.min()), ut], np.r_[0.0, Fn], drawstyle="steps-post", color="{TEXT}", linewidth=1.2, label="Nonparametric")',
          f'ax.plot(grid, F, color="{color}", linewidth=2, label={J(f["label"])})',
          'ax.set_xlim(lo, hi)', 'ax.set_ylim(-0.02, 1.02)', 'ax.set_xlabel(T)', 'ax.set_ylabel("Probability")',
          'ax.legend(loc="lower right", frameon=False, fontsize=8)',
          f'fig.suptitle(T + {J(" " + f["label"] + " distribution")}, fontsize=10)', 'plt.show()']
    return '\n'.join(head + L)


def _ph_plot(ctx, rhs, ties, plot):
    """Proportional hazards' Baseline Survival: the fit as the report's code
    makes it, then Breslow's estimate at the means of the design columns."""
    W, H = plot.get('size') or [460, 300]
    lines = _read_code(ctx['table'], ctx['table_name'], ctx['time'], ctx['censor'], ctx['code'], ctx['freq'], ctx['cols'],
                       [PLT, 'from statsmodels.duration.hazard_regression import PHReg'], keep_lines(ctx['table'], ctx['rows'], ctx['where']))
    lines[-1] = lines[-1].replace('t = ', 'd["_time"] = ')
    lines += [f'm = PHReg.from_formula({J("_time ~ " + rhs)}, d, status=event, ties={ties!r})',
              'r = m.fit()',
              'X, t, e = m.exog, m.endog, m.status   # the design columns (effect coded), a row for each count',
              'lp = (X - X.mean(axis=0)) @ r.params   # each row\'s linear predictor against a subject at the means of the design columns',
              'ut = np.unique(t[e > 0])   # the failure times',
              '# Breslow\'s estimate of the cumulative hazard (statsmodels\' baseline_cumulative_hazard holds the value just before each failure time)',
              'H = np.cumsum([((t == u) & (e > 0)).sum() / np.exp(lp[t >= u]).sum() for u in ut])',
              f'fig, ax = plt.subplots(figsize=({_inch(W)}, {_inch(H)}), layout="constrained")',
              f'ax.plot(np.r_[min(0.0, t.min()), ut, t.max()], np.r_[1.0, np.exp(-H), np.exp(-H[-1])], drawstyle="steps-post", color="{BASE}", linewidth=1.8)',
              'ax.set_ylim(-0.02, 1.02)', f'ax.set_xlabel({J(ctx["time"])})', 'ax.set_ylabel("Surviving")',
              'fig.suptitle("Baseline survival", fontsize=10)', 'plt.show()']
    return '\n'.join(lines)


# ---- Fit Parametric Survival ------------------------------------------------------------

def _design(table_id, time, effects, rows, censor, freq):
    import patsy
    d = models.build(table_id, time, [[e] for e in effects], rows, freq=freq, extra=[censor] if censor else ())
    if not len(d.df):
        return d, None, None
    dm = patsy.dmatrix(d.rhs, d.df, return_type='dataframe')
    di = dm.design_info
    names = [d.label(c) for c in dm.columns]
    groups = []
    for e in d.effects:
        cols = []
        for term, sl in di.term_name_slices.items():
            if models._same_term(term, e['term']):
                cols = list(range(sl.start, sl.stop))
        groups.append({'label': e['label'], 'cols': cols, 'alias': d.alias[e['names'][0]]})
    return d, dm, (names, groups)


def _events_of(table_id, d, censor, censor_code):
    if not censor:
        return np.ones(len(d.df))
    raw = data.series(table_id, censor, d.df.index, as_category=False).to_numpy()
    return (~censored_flags(table_id, censor, raw, censor_code)).astype(float)


@api('parametric.fit')
def parametric_fit(table, time, effects=(), rows=None, censor=None, censor_code=1, freq=None, dist='weibull', alpha=0.05,
                   corr=False, where=None, table_name='data'):
    """Fit Parametric Survival: an accelerated failure time regression, the
    location mu = x'beta of a censored location-scale model."""
    if dist not in FAMILIES:
        return {'error': f'no distribution {dist!r}'}
    label, base, logt, fixed = FAMILIES[dist]
    d, dm, meta = _design(table, time, list(effects), rows, censor, freq)
    if dm is None:
        return {'error': 'no rows with a time and every effect'}
    names, groups = meta
    t = d.df[d.y_alias].to_numpy(float)
    ev = _events_of(table, d, censor, censor_code)
    w = d.weights if d.weights is not None else np.ones(len(t))
    X = dm.to_numpy(float)
    if np.linalg.matrix_rank(X) < X.shape[1]:
        return {'error': 'the effects are collinear: some parameters cannot be estimated'}
    key = _key(table, rows, 'aft', time, list(effects), censor, censor_code, freq, dist)
    try:
        full = _remember(key, lambda: fit_ls(t, ev, w, dist, X))
        null = _remember(key + 'null', lambda: fit_ls(t, ev, w, dist, None))
    except NotApplicable as ex:
        return {'error': f'{label}: {ex}'}
    if not full['converged']:
        warnings.warn(f'the {label} regression did not converge; the estimates are the last iteration')
    zc = stats.norm.ppf(1 - alpha / 2)
    p = full['params']
    V = full['cov'] if full['cov'] is not None else np.full((len(p), len(p)), np.nan)
    se = np.sqrt(np.maximum(np.diag(V), 0)) if full['cov'] is not None else np.full(len(p), np.nan)
    est_rows = []
    for j, nm in enumerate(names):
        chi = (p[j] / se[j]) ** 2 if se[j] > 0 else float('nan')
        est_rows.append({'term': nm, 'estimate': p[j], 'se': se[j], 'lower': p[j] - zc * se[j], 'upper': p[j] + zc * se[j],
                         'chisq': chi, 'p': float(stats.chi2.sf(chi, 1)) if math.isfinite(chi) else None})
    if fixed is None:
        s = p[-1]
        sig = math.exp(s)
        est_rows.append({'term': 'σ (scale)', 'estimate': sig, 'se': sig * se[-1], 'lower': math.exp(s - zc * se[-1]), 'upper': math.exp(s + zc * se[-1]),
                         'chisq': None, 'p': None})
    lv = f'{100 * (1 - alpha):g}%'
    estimates = rtable([col('term', 'Term', 'text'), col('estimate', 'Estimate'), col('se', 'Std Error'), col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}'),
                       col('chisq', 'ChiSquare'), col('p', 'Prob>ChiSq', 'p')], est_rows)
    df_model = X.shape[1] - 1
    lr = 2 * (full['llf'] - null['llf'])
    whole = rtable([col('model', 'Model', 'text'), col('nll', '−LogLikelihood'), col('df', 'DF', 'int'), col('chisq', 'ChiSquare'), col('p', 'Prob>ChiSq', 'p')], [
        {'model': 'Difference', 'nll': null['llf'] * -1 - full['llf'] * -1, 'df': df_model, 'chisq': lr, 'p': float(stats.chi2.sf(lr, df_model)) if df_model > 0 else None},
        {'model': 'Full', 'nll': -full['llf'], 'df': None, 'chisq': None, 'p': None},
        {'model': 'Reduced', 'nll': -null['llf'], 'df': None, 'chisq': None, 'p': None}])
    lrt = []
    for gi, g in enumerate(groups):
        if not g['cols']:
            continue
        keep = [j for j in range(X.shape[1]) if j not in g['cols']]
        start = np.r_[p[keep], p[-1]] if fixed is None else p[keep]
        try:
            red = _remember(key + f'drop{gi}', lambda keep=keep, start=start: fit_ls(t, ev, w, dist, X[:, keep], start))
            chi = 2 * (full['llf'] - red['llf'])
            lrt.append({'source': g['label'], 'nparm': len(g['cols']), 'df': len(g['cols']), 'chisq': chi, 'p': float(stats.chi2.sf(max(chi, 0), len(g['cols'])))})
        except NotApplicable:
            pass
    aicc, bic = _ic(full['llf'], full['k'], full['n'])
    out = {'dist': dist, 'label': label, 'whole': whole, 'estimates': estimates,
           'lr': rtable([col('source', 'Source', 'text'), col('nparm', 'Nparm', 'int'), col('df', 'DF', 'int'), col('chisq', 'L-R ChiSquare'), col('p', 'Prob>ChiSq', 'p')], lrt),
           'summary': {'n': full['n'], 'events': full['n_events'], 'censored': full['n'] - full['n_events'], 'm2ll': -2 * full['llf'], 'aicc': aicc, 'bic': bic, 'k': full['k']},
           'logt': logt}
    if dist == 'weibull' and fixed is None:
        sig = math.exp(p[-1])
        out['shape'] = {'estimate': 1 / sig, 'lower': math.exp(-p[-1] - zc * se[-1]), 'upper': math.exp(-p[-1] + zc * se[-1])}
    if corr and full['cov'] is not None:
        sd = np.sqrt(np.maximum(np.diag(V), 1e-300))
        R = V / np.outer(sd, sd)
        labels = names + ([] if fixed is not None else ['log σ'])
        out['corr'] = rtable([col('term', 'Term', 'text')] + [col(f'c{j}', nm) for j, nm in enumerate(labels)],
                            [{'term': nm, **{f'c{j}': R[i, j] for j in range(len(labels))}} for i, nm in enumerate(labels)])
    lines = _read_code(table, table_name, time, censor, censor_code, freq, [time, censor, freq] + list(effects), ['import patsy', 'from scipy import stats, optimize', 'from scipy.special import log_ndtr'],
                       keep_lines(table, rows, where))
    rhs = models.code_formula(d).split('~', 1)[1].strip() if '~' in models.code_formula(d) else '1'
    lines.append(f'X = np.asarray(patsy.dmatrix({json.dumps(rhs)}, d))   # the design, with an intercept; effect coding for nominal effects')
    lines.append(_nll_code(dist, 'X'))
    out['code'] = '\n'.join(lines)
    return out


@api('parametric.save')
def parametric_save(table, time, effects=(), rows=None, censor=None, censor_code=1, freq=None, dist='weibull', what='quantile', value=0.5):
    """Per row: the time quantile at a failure probability, or the survival
    probability at a time, from the fitted regression."""
    label, base, logt, fixed = FAMILIES[dist]
    d, dm, meta = _design(table, time, list(effects), rows, censor, freq)
    if dm is None:
        return {'error': 'no rows'}
    t = d.df[d.y_alias].to_numpy(float)
    ev = _events_of(table, d, censor, censor_code)
    w = d.weights if d.weights is not None else np.ones(len(t))
    X = dm.to_numpy(float)
    key = _key(table, rows, 'aft', time, list(effects), censor, censor_code, freq, dist)
    full = _remember(key, lambda: fit_ls(t, ev, w, dist, X))
    p = full['params']
    sig = full['fixed'] if full['fixed'] is not None else math.exp(p[-1])
    mu = X @ p[:X.shape[1]]
    with np.errstate(all='ignore'):
        if what == 'quantile':
            q = mu + sig * _ppf(base, float(value))
            vals = np.exp(q) if logt else q
        else:
            tt = float(value)
            g = (math.log(tt) if tt > 0 else -np.inf) if logt else tt
            vals = 1 - _cdf(base, (g - mu) / sig)
    return {'rows': d.df.index.to_numpy(), 'values': vals}


# ---- Fit Proportional Hazards ------------------------------------------------------------

def _breslow(t, ev, lp):
    """Breslow's estimate of the cumulative hazard at the failure times, for
    linear predictors lp: H(u) = sum over failures at or before u of
    d / sum over the risk set of exp(lp)."""
    ut = np.unique(t[ev > 0])
    order = np.argsort(t)
    ts, es = t[order], np.exp(lp[order])
    # the risk set at u: every time >= u
    tail = np.cumsum(es[::-1])[::-1]
    first = np.searchsorted(ts, ut, side='left')
    d = np.array([np.sum((t == u) & (ev > 0)) for u in ut], dtype=float)
    h = d / tail[first]
    return ut, np.cumsum(h), h


@api('phreg.fit')
def phreg_fit(table, time, effects=(), rows=None, censor=None, censor_code=1, freq=None, ties='breslow', alpha=0.05, where=None, plot=None, table_name='data'):
    """Fit Proportional Hazards: Cox regression with statsmodels' PHReg."""
    effects = list(effects)
    if not effects:
        return {'error': 'add at least one effect'}
    if ties not in ('breslow', 'efron'):
        ties = 'breslow'
    d, dm, meta = _design(table, time, effects, rows, censor, freq)
    if dm is None:
        return {'error': 'no rows with a time and every effect'}
    names, groups = meta
    t0 = d.df[d.y_alias].to_numpy(float)
    ev0 = _events_of(table, d, censor, censor_code)
    f = np.floor(d.weights + 1e-9).astype(int) if d.weights is not None else np.ones(len(t0), dtype=int)
    keep = f >= 1
    X0 = dm.to_numpy(float)[:, 1:]            # no intercept in a proportional hazards model
    names = names[1:]
    for g in groups:
        g['cols'] = [c - 1 for c in g['cols']]
    t0, ev0, X0, f = t0[keep], ev0[keep], X0[keep], f[keep]
    idx0 = d.df.index.to_numpy()[keep]
    if not np.any(ev0 > 0):
        return {'error': 'no failures: every time is censored'}
    if X0.shape[1] == 0 or np.linalg.matrix_rank(X0) < X0.shape[1]:
        return {'error': 'the effects are collinear or constant: some parameters cannot be estimated'}
    rep = np.repeat(np.arange(len(t0)), f)
    t, ev, X = t0[rep], ev0[rep], X0[rep]
    mod = PHReg(t, X, status=ev, ties=ties)
    res = mod.fit(disp=0)
    b = np.asarray(res.params, dtype=float)
    V = np.asarray(res.cov_params(), dtype=float)
    se = np.sqrt(np.maximum(np.diag(V), 0))
    llf = float(res.llf)
    llf0 = float(mod.loglike(np.zeros(len(b))))
    zc = stats.norm.ppf(1 - alpha / 2)
    lv = f'{100 * (1 - alpha):g}%'
    lr = 2 * (llf - llf0)
    whole = rtable([col('model', 'Model', 'text'), col('nll', '−LogLikelihood'), col('chisq', 'ChiSquare'), col('df', 'DF', 'int'), col('p', 'Prob>ChiSq', 'p')], [
        {'model': 'Difference', 'nll': llf - llf0, 'chisq': lr, 'df': len(b), 'p': float(stats.chi2.sf(lr, len(b)))},
        {'model': 'Full', 'nll': -llf, 'chisq': None, 'df': None, 'p': None},
        {'model': 'Reduced', 'nll': -llf0, 'chisq': None, 'df': None, 'p': None}])
    est = []
    for j, nm in enumerate(names):
        chi = (b[j] / se[j]) ** 2 if se[j] > 0 else float('nan')
        est.append({'term': nm, 'estimate': b[j], 'se': se[j], 'lower': b[j] - zc * se[j], 'upper': b[j] + zc * se[j],
                    'chisq': chi, 'p': float(stats.chi2.sf(chi, 1)) if math.isfinite(chi) else None})
    estimates = rtable([col('term', 'Term', 'text'), col('estimate', 'Estimate'), col('se', 'Std Error'), col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}'),
                       col('chisq', 'ChiSquare'), col('p', 'Prob>ChiSq', 'p')], est)
    lrt = []
    for g in groups:
        if not g['cols']:
            continue
        rest = [j for j in range(X.shape[1]) if j not in g['cols']]
        if rest:
            llr = float(PHReg(t, X[:, rest], status=ev, ties=ties).fit(disp=0, start_params=b[rest]).llf)
        else:
            llr = llf0
        chi = 2 * (llf - llr)
        lrt.append({'source': g['label'], 'nparm': len(g['cols']), 'df': len(g['cols']), 'chisq': chi, 'p': float(stats.chi2.sf(max(chi, 0), len(g['cols'])))})
    # risk ratios: per unit and per range of each continuous effect, and
    # between the levels of each nominal effect
    unit, rng, nominal = [], [], []
    for g in groups:
        if not g['cols']:
            continue
        a = g['alias']
        if a in d.categorical:
            levels = d.levels[a]
            k = len(levels)
            C = np.zeros((k, X.shape[1]))
            for i in range(k - 1):
                C[i, g['cols'][i]] = 1.0
            C[k - 1, g['cols']] = -1.0
            rows_n = []
            for i in range(k):
                for j in range(k):
                    if i == j:
                        continue
                    c = C[i] - C[j]
                    lrr = float(c @ b)
                    s = math.sqrt(max(float(c @ V @ c), 0))
                    chi = (lrr / s) ** 2 if s > 0 else float('nan')
                    rows_n.append({'level1': models._level_text(str(levels[i])), 'level2': models._level_text(str(levels[j])), 'rr': math.exp(lrr),
                                   'p': float(stats.chi2.sf(chi, 1)) if math.isfinite(chi) else None,
                                   'lower': math.exp(lrr - zc * s), 'upper': math.exp(lrr + zc * s), 'recip': math.exp(-lrr)})
            nominal.append({'effect': g['label'], 'table': rtable([col('level1', 'Level1', 'text'), col('level2', '/Level2', 'text'), col('rr', 'Risk Ratio'),
                                                                  col('p', 'Prob>ChiSq', 'p'), col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}'), col('recip', 'Reciprocal')], rows_n)})
        else:
            j = g['cols'][0]
            chi = (b[j] / se[j]) ** 2 if se[j] > 0 else float('nan')
            pv = float(stats.chi2.sf(chi, 1)) if math.isfinite(chi) else None
            unit.append({'term': g['label'], 'rr': math.exp(b[j]), 'p': pv, 'lower': math.exp(b[j] - zc * se[j]), 'upper': math.exp(b[j] + zc * se[j]), 'recip': math.exp(-b[j])})
            span = float(np.max(X0[:, j]) - np.min(X0[:, j]))
            rng.append({'term': g['label'], 'range': span, 'rr': math.exp(b[j] * span), 'p': pv, 'lower': math.exp((b[j] - zc * se[j]) * span),
                        'upper': math.exp((b[j] + zc * se[j]) * span), 'recip': math.exp(-b[j] * span)})
    rr_cols = [col('term', 'Term', 'text'), col('rr', 'Risk Ratio'), col('p', 'Prob>ChiSq', 'p'), col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}'), col('recip', 'Reciprocal')]
    # baseline survival at the means of the design columns
    xbar = X.mean(axis=0)
    lp = (X - xbar) @ b
    ut, H, _h = _breslow(t, ev, lp)
    risk0 = np.exp((X0 - xbar) @ b)
    out = {'whole': whole, 'estimates': estimates,
           'lr': rtable([col('source', 'Source', 'text'), col('nparm', 'Nparm', 'int'), col('df', 'DF', 'int'), col('chisq', 'L-R ChiSquare'), col('p', 'Prob>ChiSq', 'p')], lrt),
           'unit': rtable(rr_cols, unit) if unit else None,
           'range': rtable(rr_cols[:1] + [col('range', 'Range')] + rr_cols[1:], rng) if rng else None,
           'nominal': nominal, 'ties': ties,
           'summary': {'n': int(len(t)), 'events': int(ev.sum()), 'censored': int(len(t) - ev.sum())},
           'baseline': {'time': np.r_[min(0.0, float(t.min())), ut, float(t.max())], 'surv': np.r_[1.0, np.exp(-H), np.exp(-H[-1])]},
           'scores': {'rows': idx0, 'risk': risk0, 'lp': X0 @ b}}
    lines = _read_code(table, table_name, time, censor, censor_code, freq, [time, censor] + effects, ['from statsmodels.duration.hazard_regression import PHReg'],
                       keep_lines(table, rows, where))
    lines[-1] = lines[-1].replace('t = ', 'd["_time"] = ')
    rhs = models.code_formula(d).split('~', 1)[1].strip()
    if plot is not None:
        ctx = dict(table=table, rows=rows, where=where, table_name=table_name, time=time, censor=censor, code=censor_code, freq=freq, cols=[time, censor] + effects)
        out['plot_code'] = _ph_plot(ctx, rhs, ties, plot)
    lines += [f'm = PHReg.from_formula({json.dumps("_time ~ " + rhs)}, d, status=event, ties={ties!r})',
              'r = m.fit()',
              'print(r.summary())   # coefficients, standard errors, hazard ratios exp(coef)',
              'print(2 * (r.llf - m.loglike(np.zeros(len(r.params)))))   # the whole-model likelihood ratio chi-square']
    out['code'] = '\n'.join(lines)
    return out
