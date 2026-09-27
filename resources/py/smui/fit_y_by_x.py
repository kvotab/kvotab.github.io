"""Fit Y by X and Matched Pairs.

Fit Y by X studies one response against one factor; their modeling types
choose the analysis, as JMP does:

    Y continuous,  X continuous   Bivariate     line, polynomial, special,
                                                spline, local smoother, each
                                                value, robust, orthogonal,
                                                quantile, ellipses, contours
    Y continuous,  X categorical  Oneway        ANOVA, t tests, comparisons,
                                                rank tests, Brunner-Munzel,
                                                variances, equivalence,
                                                power, ANOM, Poisson rates
    Y categorical, X continuous   Logistic      Logit (GLM with weights),
                                                MNLogit, OrderedModel
    Y categorical, X categorical  Contingency   the crosstab, chi-square and
                                                exact tests, measures,
                                                kappa, relative risk, two
                                                proportions, CMH and
                                                Breslow-Day

Matched Pairs compares paired responses (their difference against their
mean); binary responses get Cochran's Q and McNemar's tests.

Weight and Freq. Freq counts a row that many times; Weight weights it. The
least-squares fits use both: weighted least squares on weight x freq, with
the residual degrees of freedom counted from Freq (statsmodels counts rows,
so the model's df_resid is set before fitting). Where the statsmodels or
scipy function takes no weights (rank tests, robust and quantile fits, the
local smoother, MNLogit, OrderedModel), whole-number frequencies are
counted by repeating rows and Weight is not used; the result says so in
'notes'.

Every result carries 'code', Python that computes it from a CSV export of
the table, and results about rows carry 'rows', the page's row numbers.
"""
import json
import math

import numpy as np
import pandas as pd
from scipy import stats

from . import data, models
from .registry import api
from .util import code_head, col
from .util import table as rtable

J = json.dumps
MAX_EXPANDED = 3_000_000     # rows after repeating Freq, at most
SEED = 20260926              # quasi-Monte Carlo integrals and subsamples: the same numbers every time


# ---- shared pieces -----------------------------------------------------------

def _q(name):
    """A column name in a patsy formula."""
    return name if str(name).isidentifier() else f'Q({J(str(name))})'


def _lvtext(v):
    """A level as text: 12.0 as 12."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _head(table_name, where=None, imports=()):
    """The top of a code snippet: read the table, keep the group's rows."""
    lines = [code_head(table_name, list(imports))]
    for w in where or []:
        lines.append(f'df = df[df[{J(w["column"])}] == {J(w["value"])}]   # only the rows where {w["column"]} is {_lvtext(w["value"])}')
    return lines


def _wf(df, table, weight, freq):
    """The Weight and Freq of the rows of df; rows with a missing, zero or
    negative weight or frequency are dropped."""
    n = len(df)
    w = data.series(table, weight, df.index, as_category=False).to_numpy(float) if weight else np.ones(n)
    f = data.series(table, freq, df.index, as_category=False).to_numpy(float) if freq else np.ones(n)
    ok = np.isfinite(w) & np.isfinite(f) & (w > 0) & (f > 0)
    return df[ok], w[ok], f[ok]


def _reps(f):
    """Freq as whole repeat counts, for functions that take no weights."""
    if f is None:
        return None
    r = np.rint(f)
    if np.any(np.abs(f - r) > 1e-9):
        raise ValueError('Freq must hold whole numbers for this analysis (it is counted by repeating rows)')
    if r.sum() > MAX_EXPANDED:
        raise ValueError(f'Freq adds up to {int(r.sum())} rows, more than {MAX_EXPANDED} for this analysis')
    return r.astype(int)


def _wexpr(weight, freq, frame='d'):
    parts = [f'{frame}[{J(c)}]' for c in (weight, freq) if c]
    return ' * '.join(parts) if parts else None


def _unexpand(values, reps):
    """Values of repeated rows back to one per row (the first copy)."""
    if reps is None:
        return values
    starts = np.concatenate([[0], np.cumsum(reps)[:-1]])
    return np.asarray(values)[starts]


def _tab(cols, rows, **extra):
    return rtable(cols, rows, **extra)


class _XY:
    """Continuous Y and X with the rows' weights and frequencies."""

    def __init__(self, y, x, w, f, rows, weight, freq):
        self.y, self.x, self.w, self.f, self.rows = y, x, w, f, rows
        self.weight, self.freq = weight, freq
        self.wf = w * f
        self.n = len(y)
        self.N = float(np.sum(f))
        self.weighted = bool(weight or freq)

    def expand(self):
        """(y, x, reps) with Freq counted by repeating rows."""
        if not self.freq:
            return self.y, self.x, None
        r = _reps(self.f)
        return np.repeat(self.y, r), np.repeat(self.x, r), r


def _xy(table, y, x, rows=None, weight=None, freq=None):
    if y == x:
        raise ValueError('Y and X are the same column')
    df = data.frame(table, [y, x, weight, freq], rows, as_category=False)
    df, w, f = _wf(df, table, weight, freq)
    yv = df[y].to_numpy(float)
    xv = df[x].to_numpy(float)
    ok = np.isfinite(yv) & np.isfinite(xv)
    return _XY(yv[ok], xv[ok], w[ok], f[ok], df.index.to_numpy()[ok], weight, freq)


def _fit_wls(X, yv, xy):
    """Least squares with the page's weights, the residual df from Freq."""
    import statsmodels.api as sm
    mod = sm.WLS(yv, X, weights=xy.wf) if xy.weighted else sm.OLS(yv, X)
    if xy.freq:
        mod.df_resid = float(xy.N - np.linalg.matrix_rank(np.asarray(X, float)))
    return mod.fit()


def _fit_design(d, f):
    """models.build's design, fitted with the residual df from Freq."""
    import statsmodels.formula.api as smf
    if d.weights is not None:
        mod = smf.wls(d.formula, data=d.df, weights=d.weights)
    else:
        mod = smf.ols(d.formula, data=d.df)
    if f is not None:
        mod.df_resid = float(np.sum(f) - np.linalg.matrix_rank(mod.exog))
    res = mod.fit()
    models.attach_terms(d, res)
    return res


def _freq_of(table, freq, index):
    return data.series(table, freq, index, as_category=False).to_numpy(float) if freq else None


def _summary_of_fit(res, yv, wf, count):
    """JMP's Summary of Fit. count: the observations (Freq summed)."""
    df_total = float(res.df_resid + res.df_model)
    r2 = float(res.rsquared)
    r2a = 1 - (1 - r2) * df_total / res.df_resid if res.df_resid > 0 else None
    rows = [
        {'stat': 'RSquare', 'value': r2},
        {'stat': 'RSquare Adj', 'value': r2a},
        {'stat': 'Root Mean Square Error', 'value': float(np.sqrt(res.mse_resid)) if res.df_resid > 0 else None},
        {'stat': 'Mean of Response', 'value': float(np.average(yv, weights=wf))},
        {'stat': 'Observations (or Sum Wgts)', 'value': float(count)},
    ]
    return _tab([col('stat', '', 'text'), col('value', '')], rows)


def _estimates(res, names, alpha, stat='t'):
    """Parameter Estimates from any statsmodels result with params, bse."""
    ci = np.asarray(res.conf_int(alpha))
    lv = f'{100 * (1 - alpha):g}%'
    rows = []
    for j, nm in enumerate(names):
        rows.append({'term': nm, 'estimate': float(np.asarray(res.params)[j]), 'se': float(np.asarray(res.bse)[j]),
                     't': float(np.asarray(res.tvalues)[j]), 'p': float(np.asarray(res.pvalues)[j]),
                     'lower': float(ci[j, 0]), 'upper': float(ci[j, 1])})
    lab = 'z Ratio' if stat == 'z' else 't Ratio'
    pl = 'Prob>|z|' if stat == 'z' else 'Prob>|t|'
    return _tab([col('term', 'Term', 'text'), col('estimate', 'Estimate'), col('se', 'Std Error'), col('t', lab), col('p', pl, 'p'),
                 col('lower', f'Lower {lv}', hidden=True), col('upper', f'Upper {lv}', hidden=True)], rows)


def _lack_of_fit(res, xv, yv, wf, f):
    """Pure error from rows with the same X; the rest of the error is lack
    of fit. None when no X value repeats."""
    ux, inv = np.unique(xv, return_inverse=True)
    g = len(ux)
    sw = np.bincount(inv, weights=wf)
    m = np.bincount(inv, weights=wf * yv) / sw
    pe_ss = float(np.sum(wf * (yv - m[inv]) ** 2))
    pe_df = float(np.sum(f)) - g
    lof_df = float(res.df_resid) - pe_df
    if pe_df <= 0 or lof_df <= 0:
        return None
    lof_ss = float(res.ssr) - pe_ss
    fr = (lof_ss / lof_df) / (pe_ss / pe_df) if pe_ss > 0 else None
    p = float(stats.f.sf(fr, lof_df, pe_df)) if fr is not None else None
    tss = float(res.centered_tss)
    rows = [
        {'source': 'Lack Of Fit', 'df': lof_df, 'ss': lof_ss, 'ms': lof_ss / lof_df, 'f': fr, 'p': p},
        {'source': 'Pure Error', 'df': pe_df, 'ss': pe_ss, 'ms': pe_ss / pe_df, 'f': None, 'p': None},
        {'source': 'Total Error', 'df': float(res.df_resid), 'ss': float(res.ssr), 'ms': None, 'f': None, 'p': None},
    ]
    return _tab([col('source', 'Source', 'text'), col('df', 'DF'), col('ss', 'Sum of Squares'), col('ms', 'Mean Square'),
                 col('f', 'F Ratio'), col('p', 'Prob > F', 'p')], rows, max_rsq=1 - pe_ss / tss if tss > 0 else None)


def _anova(res, source='Model'):
    t = models.anova(None, res)
    t['rows'][0]['source'] = source
    return t


def _thin(n, most=400):
    """Indices of at most `most` points spread over n, first and last kept."""
    if n <= most:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, most).round().astype(int))


def _grid(lo, hi, n=160):
    if not hi > lo:
        return np.array([lo, hi], float)
    return np.linspace(lo, hi, n)


def _lvcode(v):
    """A level as a Python literal for the code under a result: 12.0 as 12,
    text quoted."""
    if isinstance(v, (bool, np.bool_)):
        return repr(bool(v))
    if isinstance(v, (int, float, np.integer, np.floating)):
        f = float(v)
        return str(int(f)) if f.is_integer() else repr(f)
    return J(str(v))


def _fin(v):
    """A float, or None for a missing or undefined value (NaN)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _invert_test(pfun, alpha, center, log=False, lo_lim=-np.inf, hi_lim=np.inf, span=None):
    """A two-sided confidence interval by inverting a test: where the
    p-value pfun(v) falls to alpha on either side of its largest value. The
    p-value is scanned on a grid (log scale for ratios, v > 0) and each
    crossing refined by brentq; a side where it stays above alpha up to its
    limit gets the limit (0 or infinity for a ratio). Used when statsmodels'
    own inversion fails (a zero count)."""
    from scipy.optimize import brentq

    def p(u):
        v = math.exp(u) if log else u
        with np.errstate(all='ignore'):
            try:
                pv = float(pfun(v))
            except (ValueError, ZeroDivisionError, FloatingPointError):
                pv = float('nan')
        return pv if math.isfinite(pv) else 0.0
    if log:
        c = math.log(center) if center and center > 0 and math.isfinite(center) else 0.0
        us = c + np.linspace(-(span or 25.0), span or 25.0, 1001)
        lo_u, hi_u = -np.inf, np.inf
    else:
        s = span or 1.0
        lo_u = lo_lim if math.isfinite(lo_lim) else center - 40 * s
        hi_u = hi_lim if math.isfinite(hi_lim) else center + 40 * s
        us = np.linspace(lo_u, hi_u, 2001)
    ps = np.array([p(u) for u in us])
    if not np.any(ps >= alpha):
        return None, None
    top = int(np.argmax(ps))
    f = lambda u: p(u) - alpha
    below = np.where(ps[:top] < alpha)[0]
    above = np.where(ps[top:] < alpha)[0]
    if len(below):
        i = below[-1]
        lo = brentq(f, us[i], us[i + 1], xtol=1e-13)
        lo = math.exp(lo) if log else lo
    else:
        lo = 0.0 if log else lo_lim
    if len(above):
        i = top + above[0]
        hi = brentq(f, us[i - 1], us[i], xtol=1e-13)
        hi = math.exp(hi) if log else hi
    else:
        hi = np.inf if log else hi_lim
    return float(lo), float(hi)


def _ci_checked(ci, pfun, alpha, est, tol=1e-4):
    """True when a confidence interval from statsmodels' test inversion is
    one: it holds the estimate, its finite limits give the p-value alpha,
    and inside it the p-value is above alpha. (With a zero count
    statsmodels can return one root twice.)"""
    try:
        lo, hi = float(ci[0]), float(ci[1])
    except (TypeError, ValueError):
        return False
    if math.isnan(lo) or math.isnan(hi) or not lo < hi:
        return False
    if est is not None and not (lo - 1e-9 * (1 + abs(lo)) <= est <= hi + 1e-9 * (1 + abs(hi))):
        return False
    with np.errstate(all='ignore'):
        for v in (lo, hi):
            if math.isfinite(v) and v != 0:
                pv = float(pfun(v))
                if not (math.isfinite(pv) and abs(pv - alpha) <= tol * max(alpha, 1e-3) * 10):
                    return False
        if math.isfinite(lo) and math.isfinite(hi):
            mid = math.sqrt(lo * hi) if lo > 0 and hi > 0 else (lo + hi) / 2
            pm = float(pfun(mid))
            if not (math.isfinite(pm) and pm > alpha):
                return False
    return True


# ---- Effect sizes and Bayes factors (Distribution's Test Mean uses them too) ----
#
# Exact intervals invert the noncentral t and F distributions: the
# noncentralities at which the observed statistic is the upper and the lower
# alpha/2 point (Steiger and Fouladi 1997, Cumming and Finch 2001, Smithson
# 2003, Steiger 2004). The Bayes factors are Rouder et al.'s (2009) JZS t
# tests and Ly, Verhagen and Wagenmakers' (2016) test of a correlation.

JZS_R = math.sqrt(2) / 2     # the default scale of the Cauchy prior on δ ("medium")


def hedges_j(df):
    """Hedges' (1981) exact correction J = Γ(ν/2)/(√(ν/2) Γ((ν−1)/2)): J·d
    is unbiased for δ under normality (about 1 − 3/(4ν − 1))."""
    if not df > 1:
        return float('nan')
    return math.exp(math.lgamma(df / 2) - 0.5 * math.log(df / 2) - math.lgamma((df - 1) / 2))


def _falls_to(fun, target, start, scale, low=-math.inf):
    """The x at which fun, decreasing in x, equals target: a bracket grown
    outward from start, then brentq. None when fun stays below target down
    to low (the root would be below the limit)."""
    from scipy.optimize import brentq
    g = lambda v: fun(v) - target
    a, b = max(low, start - scale), start + scale
    for _ in range(80):
        ga = g(a)
        if ga < 0:
            if a <= low:
                return None
            a = max(low, a - 2 * (b - a))
            continue
        if g(b) > 0:
            b = b + 2 * (b - a)
            continue
        return float(brentq(g, a, b, xtol=1e-12, rtol=1e-13, maxiter=500))
    return float('nan')


def nct_interval(t, df, alpha):
    """The 1 − alpha interval of the noncentrality λ of a t statistic on df
    degrees of freedom: stats.nct.cdf(t, df, λ) is 1 − alpha/2 at the lower
    limit and alpha/2 at the upper."""
    cdf = lambda lam: float(stats.nct.cdf(t, df, lam))
    s = 2 * math.sqrt(1 + t * t / (2 * df))
    return _falls_to(cdf, 1 - alpha / 2, t, s), _falls_to(cdf, alpha / 2, t, s)


def ncf_interval(F, d1, d2, alpha):
    """The 1 − alpha interval of the noncentrality λ ≥ 0 of an F statistic:
    stats.ncf.cdf(F, d1, d2, λ) is 1 − alpha/2 at the lower limit and
    alpha/2 at the upper; a limit is 0 when even λ = 0 puts F below that
    point."""
    cdf = lambda lam: float(stats.ncf.cdf(F, d1, d2, lam)) if lam > 0 else float(stats.f.cdf(F, d1, d2))
    start = max(1.0, (F - 1) * d1)
    s = 2 + 2 * math.sqrt(max(start, 1.0))
    lo = _falls_to(cdf, 1 - alpha / 2, start, s, low=0.0)
    hi = _falls_to(cdf, alpha / 2, start, s, low=0.0)
    return (0.0 if lo is None else lo), (0.0 if hi is None else hi)


def smd_rows(d, t, df, k, alpha, names=("Cohen's d", "Hedges' g")):
    """The rows of an Effect Size table for a standardized mean difference d
    whose t statistic is t = d/k on df degrees of freedom: the exact
    interval of δ from the noncentral t (λ = δ/k), and Hedges' g = J·d with
    the interval multiplied by J."""
    lo, hi = nct_interval(t, df, alpha)
    lo, hi = (lo * k if lo is not None else None), (hi * k if hi is not None else None)
    j = hedges_j(df)
    return [{'effect': names[0], 'estimate': d, 'lower': lo, 'upper': hi, 'method': 'noncentral t'},
            {'effect': names[1], 'estimate': j * d, 'lower': j * lo if lo is not None else None, 'upper': j * hi if hi is not None else None,
             'method': 'noncentral t × J', 'j': j}]


def bonett_se(d, v1, v2, n1, n2, r=None):
    """Bonett's (2008) standard error of a mean difference standardized by
    √((s₁² + s₂²)/2): two independent groups, or (r given) two paired
    measurements of n units."""
    s2 = (v1 + v2) / 2
    if r is None:
        df1, df2 = n1 - 1, n2 - 1
        return math.sqrt(d * d * (v1 * v1 / df1 + v2 * v2 / df2) / (8 * s2 * s2) + (v1 / df1 + v2 / df2) / s2)
    df = n1 - 1
    vd = v1 + v2 - 2 * r * math.sqrt(v1 * v2)
    return math.sqrt(d * d * (v1 * v1 + v2 * v2 + 2 * r * r * v1 * v2) / (8 * df * s2 * s2) + vd / (df * s2))


def _peaked_integral(f, a, b, peak, width):
    """∫ f over (a, b) (either may be infinite) for a positive f with most of
    its mass within a few widths of peak: quad on pieces cut there."""
    from scipy.integrate import quad
    cuts = sorted({min(max(peak + k * width, a), b) for k in (-60, -20, -6, -2, 0, 2, 6, 20, 60)} | {a, b})
    # f falls away from the peak: its value at the interval's point nearest
    # the peak, times the width, bounds the integral's scale, and an absolute
    # tolerance from it keeps about 1e-12 of the whole without chasing the
    # relative accuracy of pieces that add nothing
    near = min(max(peak, a), b)
    top = f(near) if math.isfinite(near) else 0.0
    eps = 1e-13 * top * width if top > 0 else 0.0
    total = 0.0
    for lo, hi in zip(cuts[:-1], cuts[1:]):
        if hi > lo:
            v, _ = quad(f, lo, hi, limit=200, epsabs=eps, epsrel=1e-11)
            total += v
    return total


def jzs(t, n, df, r=JZS_R):
    """Rouder et al.'s (2009, eq. 1) JZS t test: δ ~ Cauchy(0, r) as δ | g ~
    N(0, g r²), g ~ inverse gamma(½, ½), Jeffreys' prior on σ. n is the
    sample size (one sample, paired) or n₁n₂/(n₁ + n₂), df the t's degrees
    of freedom. Returns log BF10 and the posterior probabilities P(δ > 0 | t)
    and P(δ < 0 | t) under the alternative, for the one-sided Bayes factors
    BF±0 = 2·BF10·P(δ ≷ 0 | t) (Morey and Wagenmakers 2014). Given g, σ
    integrates out in closed form: P(δ > 0 | t, g) is the central t cdf (df
    + 1 DF) at t·√(c(df + 1)/(df + t²(1 − c))), c = n g r²/(1 + n g r²); so
    all three are integrals over g of Rouder's integrand, taken on log g
    and scaled by its largest value."""
    from scipy.integrate import quad
    from scipy.optimize import minimize_scalar
    t = float(t)
    t2 = t * t
    lnr = math.log(n * r * r)

    def l1a(u):   # log(1 + n g r²) at g = e^u, without overflow
        la = lnr + u
        return la + math.log1p(math.exp(-la)) if la > 0 else math.log1p(math.exp(la))

    def L(u):   # log of the integrand at g = e^u, times dg/du
        if u < -700:
            return -math.inf
        lg = l1a(u)
        return (-0.5 * lg - (df + 1) / 2 * math.log1p(t2 / df * math.exp(-lg))
                - 0.5 * math.log(2 * math.pi) - 0.5 * u - 0.5 * math.exp(-u))

    def q(u):
        inv = math.exp(-l1a(u))          # 1/(1 + n g r²)
        return t * math.sqrt((1 - inv) * (df + 1) / (df + t2 * inv))
    grid = np.arange(-20.0, 60.0, 0.5)
    vals = [L(u) for u in grid]
    i = int(np.argmax(vals))
    m = minimize_scalar(lambda u: -L(u), bounds=(grid[max(i - 1, 0)], grid[min(i + 1, len(grid) - 1)]), method='bounded', options={'xatol': 1e-10})
    top = float(m.x) if -m.fun >= vals[i] else float(grid[i])
    Lmax = L(top)

    def integral(h):   # ∫ exp(L − Lmax) h du, split at the top; the integrand is at most 1 and about as wide
        f = lambda u: math.exp(L(u) - Lmax) * h(u)
        return (quad(f, -np.inf, top, limit=200, epsabs=1e-15, epsrel=1e-11)[0]
                + quad(f, top, np.inf, limit=200, epsabs=1e-15, epsrel=1e-11)[0])
    whole = integral(lambda u: 1.0)
    pos = integral(lambda u: float(stats.t.cdf(q(u), df + 1)))
    neg = integral(lambda u: float(stats.t.sf(q(u), df + 1)))
    log_bf = Lmax + math.log(whole) + (df + 1) / 2 * math.log1p(t2 / df)
    return log_bf, pos / whole, neg / whole


def _bf_row(label, log_bf10):
    """A row of a Bayes Factor table from log BF10 (BF01 its inverse)."""
    lb = float(log_bf10)
    big = 700.0   # exp overflows beyond about 709
    bf10 = math.exp(lb) if lb < big else float('inf')
    bf01 = math.exp(-lb) if -lb < big else float('inf')
    return {'alternative': label, 'bf10': bf10, 'bf01': bf01, 'log10': lb / math.log(10)}


def jzs_rows(t, n, df, r, labels):
    """The Bayes Factor table of a t statistic: two-sided, then δ > 0, δ < 0
    (labels in that order)."""
    lb, pp, pn = jzs(t, n, df, r)
    lpos = lb + math.log(2 * pp) if pp > 0 else -math.inf
    lneg = lb + math.log(2 * pn) if pn > 0 else -math.inf
    return [_bf_row(labels[0], lb), _bf_row(labels[1], lpos), _bf_row(labels[2], lneg)]


JZS_CODE = '''def jzs(t, n, df, r):   # Rouder et al. (2009): BF10 of a t statistic for δ ~ Cauchy(0, r), and P(δ > 0 | t)
    w = lambda g: (1 + n*g*r**2)**-0.5 * (1 + t**2/((1 + n*g*r**2)*df))**(-(df + 1)/2) * (2*np.pi)**-0.5 * g**-1.5 * np.exp(-1/(2*g))
    q = lambda g: t * np.sqrt(n*g*r**2/(1 + n*g*r**2) * (df + 1)/(df + t**2/(1 + n*g*r**2)))   # P(δ > 0 | t, g) is the t cdf (df + 1 DF) at q
    I = integrate.quad(w, 0, np.inf, limit=200)[0]
    return I / (1 + t**2/df)**(-(df + 1)/2), integrate.quad(lambda g: w(g) * stats.t.cdf(q(g), df + 1), 0, np.inf, limit=200)[0] / I'''


def pearson_log_bf(r, n, kappa=1.0):
    """Ly, Verhagen and Wagenmakers' (2016) Bayes factors for a Pearson
    correlation r of n pairs, a stretched beta(1/κ, 1/κ) prior on ρ over
    (−1, 1) (κ = 1: uniform): the exact likelihood of ρ given r (Hotelling's
    form of the density of r, relative to ρ = 0) integrated against the
    prior over (−1, 1), (0, 1) and (−1, 0) (the one-sided priors doubled).
    Returns log BF10, log BF+0, log BF−0. The integrals are taken on
    z = atanh ρ, where the likelihood is about normal, scaled by its top."""
    from scipy.special import betaln, hyp2f1
    r = float(r)
    c = n - 0.5
    base = math.log(hyp2f1(0.5, 0.5, c, 0.5))
    lprior0 = (1 - 2 / kappa) * math.log(2) - betaln(1 / kappa, 1 / kappa)

    def logf(z):   # log of likelihood × prior × dρ/dz at ρ = tanh z
        rho = math.tanh(z)
        lone = math.log(4) - 2 * abs(z) - 2 * math.log1p(math.exp(-2 * abs(z)))   # log(1 − ρ²), exact for any z
        return ((n - 1) / 2 * lone - (n - 1.5) * math.log1p(-rho * r) + math.log(hyp2f1(0.5, 0.5, c, (1 + rho * r) / 2)) - base
                + lprior0 + (1 / kappa - 1) * lone + lone)
    z0 = math.atanh(max(-0.999999, min(0.999999, r)))
    w = 1 / math.sqrt(max(n - 3, 1))
    zs = np.concatenate([z0 + w * np.linspace(-12, 12, 241), np.linspace(-15, 15, 301)])
    top = max(logf(float(z)) for z in zs)
    f = lambda z: math.exp(logf(z) - top)
    pos = _peaked_integral(f, 0.0, np.inf, z0, w)
    neg = _peaked_integral(f, -np.inf, 0.0, z0, w)
    lt = lambda v: top + math.log(v) if v > 0 else -math.inf
    return lt(pos + neg), lt(2 * pos), lt(2 * neg)


PEARSON_CODE = '''def bf_rho(r, n, kappa, lo=-1, hi=1):   # Ly et al. (2016): the exact likelihood of ρ given r against a stretched beta prior
    lik = lambda p: (1 - p*p)**((n - 1)/2) * (1 - p*r)**(1.5 - n) * special.hyp2f1(0.5, 0.5, n - 0.5, (1 + p*r)/2) / special.hyp2f1(0.5, 0.5, n - 0.5, 0.5)
    prior = lambda p: 2**(1 - 2/kappa) * (1 - p*p)**(1/kappa - 1) / special.beta(1/kappa, 1/kappa)
    return integrate.quad(lambda p: lik(p) * prior(p), lo, hi, points=[r] if lo < r < hi else None, limit=200)[0] * (2 if hi - lo < 2 else 1)'''


def _es_table(rows, alpha):
    lv = f'{100 * (1 - alpha):g}%'
    return _tab([col('effect', 'Effect Size', 'text'), col('estimate', 'Estimate'), col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}'),
                 col('method', 'Interval', 'text')], rows)


def _bf_table(rows):
    return _tab([col('alternative', 'Alternative', 'text'), col('bf10', 'BF10'), col('bf01', 'BF01'), col('log10', 'log10 BF10', hidden=True)], rows)


# ---- Bivariate ----------------------------------------------------------------

@api('fitybyx.bivariate')
def bivariate(table, y, x, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Summary Statistics of a scatterplot: the means, standard deviations,
    correlation and covariance of X and Y."""
    from statsmodels.stats.weightstats import DescrStatsW
    xy = _xy(table, y, x, rows, weight, freq)
    if xy.n < 2:
        return {'error': 'fewer than two rows with both values', 'n': xy.n}
    d = DescrStatsW(np.column_stack([xy.x, xy.y]), weights=xy.wf, ddof=1)
    cov = np.asarray(d.cov)
    sd = np.sqrt(np.diag(cov))
    r = float(cov[0, 1] / (sd[0] * sd[1])) if sd[0] > 0 and sd[1] > 0 else None
    out = {'n': xy.N, 'n_rows': xy.n, 'mean_x': float(d.mean[0]), 'mean_y': float(d.mean[1]), 'sd_x': float(sd[0]), 'sd_y': float(sd[1]),
           'r': r, 'cov': float(cov[0, 1])}
    c = _head(table_name, where, ['from statsmodels.stats.weightstats import DescrStatsW'])
    c.append(f'd = df[[{J(x)}, {J(y)}]].dropna()')
    we = _wexpr(weight, freq)
    if we:
        c[-1] = f'd = df[[{", ".join(J(v) for v in (x, y, weight, freq) if v)}]].dropna()'
        c.append(f'print(DescrStatsW(d[[{J(x)}, {J(y)}]], weights={we}, ddof=1).cov)')
    else:
        c.append('print(d.mean(), d.std(), d.corr(), d.cov())')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.bivariate_bf')
def bivariate_bf(table, y, x, kappa=1.0, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Bayes Factor of the Pearson correlation (Ly, Verhagen and Wagenmakers
    2016): ρ ~ stretched beta(1/κ, 1/κ) on (−1, 1) under the alternative
    (κ = 1, uniform, by default), the exact likelihood of ρ given r;
    two-sided and one-sided (ρ > 0, ρ < 0). Freq counts rows; Weight is
    not used."""
    xy = _xy(table, y, x, rows, weight, freq)
    if not (kappa and kappa > 0):
        return {'error': 'the width κ of the prior must be positive'}
    try:
        yv, xv, _ = xy.expand()
    except ValueError as e:
        return {'error': str(e)}
    n = len(yv)
    if n < 3:
        return {'error': 'fewer than three rows with both values'}
    if np.std(xv) == 0 or np.std(yv) == 0:
        return {'error': 'a column is constant: no correlation'}
    r = float(stats.pearsonr(xv, yv).statistic)
    if abs(r) >= 1 - 1e-12:
        return {'error': 'the points lie on a line (r = ±1): the Bayes factor is infinite'}
    l2, lp, ln = pearson_log_bf(r, n, kappa)
    rows_out = [_bf_row('ρ ≠ 0', l2), _bf_row('ρ > 0', lp), _bf_row('ρ < 0', ln)]
    out = {'table': _bf_table(rows_out), 'r': r, 'n': n, 'kappa': kappa, 'notes': ['Weight is not used by the Bayes factor; Freq is.'] if weight else []}
    c = _head(table_name, where, ['from scipy import stats, integrate, special'])
    c.append(f'd = df[[{", ".join(J(v) for v in (x, y, freq) if v)}]].dropna()')
    if freq:
        c.append(_repeat_code(freq))
    c.append(f'r, n = stats.pearsonr(d[{J(x)}], d[{J(y)}]).statistic, len(d)')
    c.append(PEARSON_CODE)
    c.append(f'print(bf_rho(r, n, {kappa!r}), bf_rho(r, n, {kappa!r}, 0, 1), bf_rho(r, n, {kappa!r}, -1, 0))   # BF10: ρ ≠ 0, ρ > 0, ρ < 0; BF01 = 1/BF10')
    out['code'] = '\n'.join(c)
    return out


def _poly_labels(d, x):
    lab = {}
    a = d.alias[x]
    m = d.means.get(a)
    for i, e in enumerate(d.effects):
        for c in e.get('terms', []):
            lab[c] = x if i == 0 else f'({x}-{m:.6g})^{i + 1}'
    return lab


@api('fitybyx.fit_poly')
def fit_poly(table, y, x, degree=1, rows=None, weight=None, freq=None, alpha=0.05, want_rows=False, where=None, table_name='data'):
    """Fit Line (degree 1) and Fit Polynomial (2 to 6): least squares on X
    and centred powers of X, JMP's Summary of Fit, Lack Of Fit, Analysis of
    Variance and Parameter Estimates, and the fitted curve with confidence
    curves for the mean and for individuals."""
    if y == x:
        return {'error': 'Y and X are the same column'}
    degree = int(max(1, min(6, int(degree))))
    d = models.build(table, y, [[x] * k for k in range(1, degree + 1)], rows, weight, freq, center=True)
    n = len(d.df)
    if n < degree + 2:
        return {'error': f'{n} rows with both values: too few for degree {degree}'}
    f = _freq_of(table, freq, d.df.index)
    wf = np.asarray(d.weights, float) if d.weights is not None else np.ones(n)
    count = float(np.sum(f)) if f is not None else float(n)
    res = _fit_design(d, f)
    yv = d.df[d.y_alias].to_numpy(float)
    xv = d.df[d.alias[x]].to_numpy(float)
    est = models.estimates(d, res, alpha)
    lab = _poly_labels(d, x)
    for r in est['rows']:
        r['term'] = lab.get(r['name'], r['term'])
    for c in est['columns']:
        if c['key'] in ('lower', 'upper'):
            c['hidden'] = True
    g = _grid(float(xv.min()), float(xv.max()))
    sf = res.get_prediction(d.frame_for({x: g})).summary_frame(alpha=alpha)
    out = {'kind': 'poly', 'degree': degree, 'n': count, 'alpha': alpha,
           'terms': [{'term': r['term'], 'estimate': r['estimate']} for r in est['rows']],
           'summary': _summary_of_fit(res, yv, wf, count if d.weights is None or not weight else float(np.sum(wf))),
           'lack_of_fit': _lack_of_fit(res, xv, yv, wf, f if f is not None else np.ones(n)),
           'anova': _anova(res), 'estimates': est,
           'rmse': float(np.sqrt(res.mse_resid)), 'rsquare': float(res.rsquared),
           'curve': {'x': g, 'fit': sf['mean'].to_numpy(), 'lo_fit': sf['mean_ci_lower'].to_numpy(), 'hi_fit': sf['mean_ci_upper'].to_numpy(),
                     'lo_ind': sf['obs_ci_lower'].to_numpy(), 'hi_ind': sf['obs_ci_upper'].to_numpy()}}
    if want_rows:
        out['row_values'] = _row_values(res, d.df.index.to_numpy(), yv, np.asarray(res.model.exog), wf, alpha)
    formula = models.code_formula(d)
    c = _head(table_name, where)
    c.append(f'd = df[[{J(x)}, {J(y)}{", " + J(weight) if weight else ""}{", " + J(freq) if freq else ""}]].dropna()')
    we = _wexpr(weight, freq)
    if we:
        c.append(f'mod = smf.wls({J(formula)}, d, weights={we})')
    else:
        c.append(f'mod = smf.ols({J(formula)}, d)')
    if freq:
        c.append(f'mod.df_resid = d[{J(freq)}].sum() - {degree + 1}   # Freq counts rows; statsmodels counts rows once')
    c += ['res = mod.fit()', 'print(res.summary())',
          f'print(res.get_prediction(pd.DataFrame({{{J(x)}: np.linspace(d[{J(x)}].min(), d[{J(x)}].max(), 5)}})).summary_frame(alpha={alpha}))   # confidence curves']
    out['code'] = '\n'.join(c)
    return out


def _row_values(res, rows, yv, exog, wf, alpha):
    """Per row: predicted, residual, studentized residual and the
    confidence limits of the mean and of an individual."""
    out = {'rows': rows, 'predicted': np.asarray(res.fittedvalues, float), 'residual': yv - np.asarray(res.fittedvalues, float)}
    try:
        inf = res.get_influence()
        out['studentized'] = np.asarray(inf.resid_studentized_internal, float)
    except Exception:
        pass
    try:
        sf = res.get_prediction(exog, weights=wf).summary_frame(alpha=alpha)
        out['lo_mean'] = sf['mean_ci_lower'].to_numpy()
        out['hi_mean'] = sf['mean_ci_upper'].to_numpy()
        out['lo_indiv'] = sf['obs_ci_lower'].to_numpy()
        out['hi_indiv'] = sf['obs_ci_upper'].to_numpy()
    except Exception:
        pass
    return out


@api('fitybyx.fit_mean')
def fit_mean(table, y, x, rows=None, weight=None, freq=None, alpha=0.05, want_rows=False, where=None, table_name='data'):
    """Fit Mean: the mean of Y as a horizontal line."""
    xy = _xy(table, y, x, rows, weight, freq)
    if xy.n < 2:
        return {'error': 'fewer than two rows with both values'}
    X = np.ones((xy.n, 1))
    res = _fit_wls(X, xy.y, xy)
    mean = float(res.params[0])
    out = {'kind': 'mean', 'n': xy.N, 'mean': mean, 'sd': float(np.sqrt(res.mse_resid)), 'se': float(res.bse[0]), 'sse': float(res.ssr),
           'curve': {'x': [float(xy.x.min()), float(xy.x.max())], 'fit': [mean, mean]}}
    if want_rows:
        out['row_values'] = {'rows': xy.rows, 'predicted': np.full(xy.n, mean), 'residual': xy.y - mean}
    c = _head(table_name, where, ['from statsmodels.stats.weightstats import DescrStatsW'])
    c.append(f'd = df[[{J(x)}, {J(y)}{", " + J(weight) if weight else ""}{", " + J(freq) if freq else ""}]].dropna()')
    we = _wexpr(weight, freq)
    c.append(f'res = sm.WLS(d[{J(y)}], np.ones(len(d)), weights={we}).fit()' if we else f'res = sm.OLS(d[{J(y)}], np.ones(len(d))).fit()')
    c.append('print(res.params, np.sqrt(res.mse_resid), res.bse, res.ssr)   # mean, Std Dev [RMSE], Std Error, SSE')
    out['code'] = '\n'.join(c)
    return out


# Fit Special: name, forward, inverse, domain, text in the report
_TRANSFORMS = {
    'none': ('{}', lambda v: v, lambda v: v, lambda v: np.isfinite(v)),
    'log': ('Log({})', np.log, np.exp, lambda v: v > 0),
    'sqrt': ('Sqrt({})', np.sqrt, lambda v: np.where(v >= 0, v * v, np.nan), lambda v: v >= 0),
    'square': ('{}^2', np.square, lambda v: np.sqrt(np.where(v >= 0, v, np.nan)), lambda v: v >= 0),
    'reciprocal': ('1/{}', lambda v: 1 / v, lambda v: 1 / v, lambda v: v != 0),
    'exp': ('Exp({})', np.exp, lambda v: np.log(np.where(v > 0, v, np.nan)), lambda v: np.isfinite(np.exp(np.clip(v, -700, 700)))),
}
# X is only transformed forward: a square takes any X (the domain above is
# Y's, whose fit is taken back by the square root)
_X_DOMAIN = {'square': lambda v: np.isfinite(v)}
_TR_TITLE = {'log': 'Log', 'sqrt': 'Sqrt', 'square': 'Square', 'reciprocal': 'Recip', 'exp': 'Exp'}
_TR_CODE = {'none': '{}', 'log': 'np.log({})', 'sqrt': 'np.sqrt({})', 'square': '{}**2', 'reciprocal': '1/{}', 'exp': 'np.exp({})'}


@api('fitybyx.fit_special')
def fit_special(table, y, x, ytr='none', xtr='none', degree=1, intercept=None, slope=None, rows=None, weight=None, freq=None, alpha=0.05,
                want_rows=False, where=None, table_name='data'):
    """Fit Special: transform Y and X (log, square root, square,
    reciprocal, exponential), a polynomial of degree 1 to 5 in the
    transformed X, and optionally the intercept or the slope held at a
    value. The curve is drawn on the original scale; with Y transformed,
    the fit is also measured on the original scale."""
    import statsmodels.api as sm
    if ytr not in _TRANSFORMS or xtr not in _TRANSFORMS:
        return {'error': 'unknown transformation'}
    xy = _xy(table, y, x, rows, weight, freq)
    ok = _TRANSFORMS[ytr][3](xy.y) & _X_DOMAIN.get(xtr, _TRANSFORMS[xtr][3])(xy.x)
    dropped = int(np.sum(~ok))
    yv, xv, wf, f, rws = xy.y[ok], xy.x[ok], xy.wf[ok], xy.f[ok], xy.rows[ok]
    sub = _XY(yv, xv, xy.w[ok], f, rws, weight, freq)
    yt = _TRANSFORMS[ytr][1](yv)
    xt = _TRANSFORMS[xtr][1](xv)
    degree = int(max(1, min(5, int(degree))))
    if intercept is not None or slope is not None:
        degree = 1
    n = len(yv)
    if n < degree + 2:
        return {'error': 'too few rows in the domain of the transformations'}
    ylab = _TRANSFORMS[ytr][0].format(y)
    xlab = _TRANSFORMS[xtr][0].format(x)
    mx = float(np.average(xt, weights=wf))
    cols = [xt] + [(xt - mx) ** k for k in range(2, degree + 1)]
    names = [xlab] + [f'({xlab}-{mx:.6g})^{k}' for k in range(2, degree + 1)]
    notes = []
    if dropped:
        notes.append(f'{dropped} rows outside the domain of the transformations are left out.')
    fixed = {}
    target = yt.copy()
    if intercept is not None and slope is not None:
        fixed = {'Intercept': float(intercept), xlab: float(slope)}
        pred_t = intercept + slope * xt
        res = None
        terms = [{'term': 'Intercept', 'estimate': float(intercept)}, {'term': xlab, 'estimate': float(slope)}]
    elif intercept is not None:
        fixed = {'Intercept': float(intercept)}
        res = _fit_wls(xt[:, None], yt - intercept, sub)
        pred_t = intercept + res.params[0] * xt
        terms = [{'term': 'Intercept', 'estimate': float(intercept)}, {'term': xlab, 'estimate': float(res.params[0])}]
    elif slope is not None:
        fixed = {xlab: float(slope)}
        res = _fit_wls(np.ones((n, 1)), yt - slope * xt, sub)
        pred_t = res.params[0] + slope * xt
        terms = [{'term': 'Intercept', 'estimate': float(res.params[0])}, {'term': xlab, 'estimate': float(slope)}]
    else:
        X = sm.add_constant(np.column_stack(cols), has_constant='add')
        res = _fit_wls(X, yt, sub)
        pred_t = np.asarray(res.fittedvalues)
        terms = [{'term': nm, 'estimate': float(b)} for nm, b in zip(['Intercept'] + names, res.params)]
    count = float(np.sum(f))
    sst_t = float(np.sum(wf * (yt - np.average(yt, weights=wf)) ** 2))
    sse_t = float(np.sum(wf * (yt - pred_t) ** 2))
    out = {'kind': 'special', 'ytr': ytr, 'xtr': xtr, 'degree': degree, 'fixed': fixed, 'n': count, 'ylab': ylab, 'xlab': xlab, 'terms': terms, 'notes': notes}
    title = 'Transformed Fit' + (f' {_TR_TITLE[ytr]}' if ytr != 'none' else '') + (f' to {_TR_TITLE[xtr]}' if xtr != 'none' else '')
    if ytr == 'none' and xtr == 'none':
        title = 'Constrained Fit' if fixed else ('Linear Fit' if degree == 1 else f'Polynomial Fit Degree={degree}')
    out['title'] = title
    if res is not None and not fixed:
        out['summary'] = _summary_of_fit(res, yt, wf, count if not weight else float(np.sum(wf)))
        out['anova'] = _anova(res)
        out['estimates'] = _estimates(res, ['Intercept'] + names, alpha)
    elif res is not None:
        df_r = float(res.df_resid)
        out['summary'] = _tab([col('stat', '', 'text'), col('value', '')], [
            {'stat': 'RSquare', 'value': 1 - sse_t / sst_t if sst_t > 0 else None},
            {'stat': 'Root Mean Square Error', 'value': math.sqrt(sse_t / df_r) if df_r > 0 else None},
            {'stat': 'Mean of Response', 'value': float(np.average(yt, weights=wf))},
            {'stat': 'Observations (or Sum Wgts)', 'value': count if not weight else float(np.sum(wf))}])
        free = ['Intercept'] if slope is not None else [xlab]
        out['estimates'] = _estimates(res, free, alpha)
        notes.append('With a parameter held fixed, RSquare is 1 − SSE/SST about the mean of the (transformed) response.')
    else:
        out['summary'] = _tab([col('stat', '', 'text'), col('value', '')], [
            {'stat': 'Sum of Squared Error', 'value': sse_t}, {'stat': 'RSquare', 'value': 1 - sse_t / sst_t if sst_t > 0 else None},
            {'stat': 'Observations (or Sum Wgts)', 'value': count}])
    inv = _TRANSFORMS[ytr][2]
    if ytr != 'none':
        pred = inv(pred_t)
        sse = float(np.nansum(wf * (yv - pred) ** 2))
        sst = float(np.sum(wf * (yv - np.average(yv, weights=wf)) ** 2))
        dfr = float(res.df_resid) if res is not None else count
        out['original'] = _tab([col('stat', '', 'text'), col('value', '')], [
            {'stat': 'Sum of Squared Error', 'value': sse}, {'stat': 'Root Mean Square Error', 'value': math.sqrt(sse / dfr) if dfr > 0 else None},
            {'stat': 'RSquare', 'value': 1 - sse / sst if sst > 0 else None}, {'stat': 'Sum of Residuals', 'value': float(np.nansum(wf * (yv - pred)))}])
    else:
        pred = pred_t
    # the curve on the original scale
    g = _grid(float(xv.min()), float(xv.max()), 200)
    gt = _TRANSFORMS[xtr][1](g)
    curve = {'x': g}
    if res is not None and not fixed:
        Xg = sm.add_constant(np.column_stack([gt] + [(gt - mx) ** k for k in range(2, degree + 1)]), has_constant='add')
        sf = res.get_prediction(Xg).summary_frame(alpha=alpha)
        a, b = sf['mean_ci_lower'].to_numpy(), sf['mean_ci_upper'].to_numpy()
        c_, d_ = sf['obs_ci_lower'].to_numpy(), sf['obs_ci_upper'].to_numpy()
        lo_f, hi_f, lo_i, hi_i = inv(a), inv(b), inv(c_), inv(d_)
        if ytr == 'reciprocal':
            lo_f, hi_f, lo_i, hi_i = hi_f, lo_f, hi_i, lo_i
        curve.update({'fit': inv(sf['mean'].to_numpy()), 'lo_fit': lo_f, 'hi_fit': hi_f, 'lo_ind': lo_i, 'hi_ind': hi_i})
    else:
        a0 = terms[0]['estimate']
        b0 = terms[1]['estimate']
        curve['fit'] = inv(a0 + b0 * gt)
    out['curve'] = curve
    if want_rows:
        out['row_values'] = {'rows': rws, 'predicted': pred, 'residual': yv - pred}
    c = _head(table_name, where)
    c.append(f'd = df[[{J(x)}, {J(y)}{", " + J(weight) if weight else ""}{", " + J(freq) if freq else ""}]].dropna()')
    c.append(f'yt = {_TR_CODE[ytr].format("d[" + J(y) + "]")}; xt = {_TR_CODE[xtr].format("d[" + J(x) + "]")}')
    we = _wexpr(weight, freq)
    if intercept is not None and slope is None:
        c.append(f'res = sm.{"WLS" if we else "OLS"}(yt - {intercept!r}, xt{", weights=" + we if we else ""}).fit()   # the intercept held at {intercept!r}')
    elif slope is not None and intercept is None:
        c.append(f'res = sm.{"WLS" if we else "OLS"}(yt - {slope!r} * xt, np.ones(len(d)){", weights=" + we if we else ""}).fit()   # the slope held at {slope!r}')
    elif intercept is None:
        powers = ''.join(f', (xt - {mx:.10g})**{k}' for k in range(2, degree + 1))
        c.append(f'X = sm.add_constant(np.column_stack([xt{powers}]))')
        c.append(f'res = sm.{"WLS" if we else "OLS"}(yt, X{", weights=" + we if we else ""}).fit()')
    if freq and res is not None:
        c.insert(len(c) - 1, f'# Freq: set mod.df_resid = d[{J(freq)}].sum() - (number of parameters) before .fit() to count rows as JMP does')
    c.append('print(res.summary())' if res is not None else f'print(({_TR_CODE[ytr].format("d[" + J(y) + "]")} - ({intercept!r} + {slope!r} * xt))**2).sum())')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.fit_spline')
def fit_spline(table, y, x, lam=None, standardize=False, rows=None, weight=None, freq=None, want_rows=False, alpha=0.05, where=None, table_name='data'):
    """Fit Spline: the cubic smoothing spline that minimises
    sum w (y - f(x))^2 + lambda * integral f''(x)^2 dx
    (scipy.interpolate.make_smoothing_spline). Rows with the same X are
    combined (their weighted mean, their weights summed), which leaves the
    criterion unchanged. lam None chooses lambda by generalised
    cross-validation."""
    from scipy.interpolate import make_smoothing_spline
    xy = _xy(table, y, x, rows, weight, freq)
    ux, inv = np.unique(xy.x, return_inverse=True)
    if len(ux) < 5:
        return {'error': 'a smoothing spline needs at least five distinct X values'}
    W = np.bincount(inv, weights=xy.wf)
    yb = np.bincount(inv, weights=xy.wf * xy.y) / W
    mx, sx = 0.0, 1.0
    if standardize:
        mx = float(np.average(xy.x, weights=xy.wf))
        sx = float(np.sqrt(np.sum(xy.wf * (xy.x - mx) ** 2) / (np.sum(xy.wf) - 1)))
        if not sx > 0:
            sx = 1.0
    xs = (ux - mx) / sx
    spl = make_smoothing_spline(xs, yb, w=W, lam=None if lam is None else float(lam))
    pred = spl(xs[inv])
    sse = float(np.sum(xy.wf * (xy.y - pred) ** 2))
    sst = float(np.sum(xy.wf * (xy.y - np.average(xy.y, weights=xy.wf)) ** 2))
    g = _grid(float(ux[0]), float(ux[-1]), int(min(600, max(200, len(ux)))))
    out = {'kind': 'spline', 'lam': lam, 'standardize': bool(standardize), 'n': xy.N, 'rsquare': 1 - sse / sst if sst > 0 else None, 'sse': sse,
           'curve': {'x': g, 'fit': spl((g - mx) / sx)}}
    if want_rows:
        out['row_values'] = {'rows': xy.rows, 'predicted': pred, 'residual': xy.y - pred}
    c = _head(table_name, where, ['from scipy.interpolate import make_smoothing_spline'])
    c.append(f'd = df[[{J(x)}, {J(y)}{", " + J(weight) if weight else ""}{", " + J(freq) if freq else ""}]].dropna()')
    we = _wexpr(weight, freq)
    c.append(f'd = d.assign(_w={we if we else "1.0"})')
    c.append(f'g = d.groupby({J(x)}).apply(lambda s: pd.Series({{"y": np.average(s[{J(y)}], weights=s["_w"]), "w": s["_w"].sum()}}))   # rows with the same X combined')
    xs = f'(g.index - {mx!r}) / {sx!r}' if standardize else 'g.index'
    c.append(f'spl = make_smoothing_spline({xs}, g["y"], w=g["w"], lam={lam!r})')
    c.append(f'print(spl(({xs})[:5]))')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.fit_lowess')
def fit_lowess(table, y, x, frac=2 / 3, it=0, rows=None, weight=None, freq=None, want_rows=False, alpha=0.05, where=None, table_name='data'):
    """Kernel Smoother as statsmodels' LOWESS: at each point a line fitted
    by tricube weights to the nearest fraction `frac` of the points, `it`
    robustifying iterations."""
    from statsmodels.nonparametric.smoothers_lowess import lowess
    xy = _xy(table, y, x, rows, weight, freq)
    if xy.n < 4:
        return {'error': 'too few rows for a local smoother'}
    notes = []
    yv, xv, reps = xy.expand()
    if weight:
        notes.append('statsmodels\' lowess takes no weights: Weight is not used here.')
    n = len(yv)
    frac = float(min(1.0, max(0.02, frac)))
    it = int(max(0, min(6, int(it))))
    rng_x = float(xv.max() - xv.min())
    delta = 0.005 * rng_x if n > 3000 else 0.0
    fitted = lowess(yv, xv, frac=frac, it=it, delta=delta, return_sorted=False)
    sse = float(np.sum((yv - fitted) ** 2))
    sst = float(np.sum((yv - yv.mean()) ** 2))
    order = np.argsort(xv, kind='stable')
    xs, fs = xv[order], fitted[order]
    ux, first = np.unique(xs, return_index=True)
    fu = fs[first]
    keep = _thin(len(ux), 500)
    out = {'kind': 'lowess', 'frac': frac, 'it': it, 'n': float(n), 'rsquare': 1 - sse / sst if sst > 0 else None, 'sse': sse, 'notes': notes,
           'delta': delta, 'curve': {'x': ux[keep], 'fit': fu[keep]}}
    if want_rows:
        pr = _unexpand(fitted, reps)
        out['row_values'] = {'rows': xy.rows, 'predicted': pr, 'residual': xy.y - pr}
    c = _head(table_name, where, ['from statsmodels.nonparametric.smoothers_lowess import lowess'])
    c.append(f'd = df[[{J(x)}, {J(y)}{", " + J(freq) if freq else ""}]].dropna()')
    if freq:
        c.append(f'd = d.loc[d.index.repeat(d[{J(freq)}].astype(int))]   # Freq: each row counted that many times')
    c.append(f'fit = lowess(d[{J(y)}], d[{J(x)}], frac={frac!r}, it={it}, delta={delta!r})   # sorted (x, fitted) pairs')
    c.append('print(fit[:5])')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.fit_each')
def fit_each(table, y, x, rows=None, weight=None, freq=None, want_rows=False, alpha=0.05, where=None, table_name='data'):
    """Fit Each Value: the mean of Y at each distinct X, whose error is the
    pure error of the lack-of-fit test."""
    xy = _xy(table, y, x, rows, weight, freq)
    if xy.n < 2:
        return {'error': 'fewer than two rows'}
    ux, inv = np.unique(xy.x, return_inverse=True)
    W = np.bincount(inv, weights=xy.wf)
    m = np.bincount(inv, weights=xy.wf * xy.y) / W
    sse = float(np.sum(xy.wf * (xy.y - m[inv]) ** 2))
    dfe = xy.N - len(ux)
    sst = float(np.sum(xy.wf * (xy.y - np.average(xy.y, weights=xy.wf)) ** 2))
    out = {'kind': 'each', 'n': xy.N, 'n_unique': len(ux), 'df': dfe, 'sse': sse, 'ms': sse / dfe if dfe > 0 else None,
           'rsquare': 1 - sse / sst if sst > 0 else None, 'curve': {'x': ux, 'fit': m}}
    if want_rows:
        out['row_values'] = {'rows': xy.rows, 'predicted': m[inv], 'residual': xy.y - m[inv]}
    c = _head(table_name, where)
    c.append(f'd = df[[{J(x)}, {J(y)}]].dropna()')
    c.append(f'means = d.groupby({J(x)})[{J(y)}].transform("mean"); sse = ((d[{J(y)}] - means)**2).sum()')
    c.append(f'print(d[{J(x)}].nunique(), sse, sse / (len(d) - d[{J(x)}].nunique()))   # unique values, SS, mean square')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.fit_robust')
def fit_robust(table, y, x, method='huber', rows=None, weight=None, freq=None, alpha=0.05, want_rows=False, where=None, table_name='data'):
    """Robust ▸ Fit Robust: an M-estimated line (statsmodels RLM) with
    Huber's or Tukey's bisquare norm; the scale is the MAD, re-estimated
    as the fit iterates."""
    import statsmodels.api as sm
    xy = _xy(table, y, x, rows, weight, freq)
    if xy.n < 3:
        return {'error': 'too few rows'}
    yv, xv, reps = xy.expand()
    notes = []
    if weight:
        notes.append('statsmodels\' RLM takes no weights: Weight is not used here.')
    norm = sm.robust.norms.TukeyBiweight() if method == 'bisquare' else sm.robust.norms.HuberT()
    X = sm.add_constant(xv, has_constant='add')
    res = sm.RLM(yv, X, M=norm).fit()
    b = np.asarray(res.params, float)
    g = np.array([float(xv.min()), float(xv.max())])
    out = {'kind': 'robust', 'method': method, 'n': float(len(yv)), 'estimates': _estimates(res, ['Intercept', x], alpha, stat='z'),
           'terms': [{'term': 'Intercept', 'estimate': float(b[0])}, {'term': x, 'estimate': float(b[1])}],
           'scale': float(res.scale), 'iterations': int(res.fit_history['iteration']) if hasattr(res, 'fit_history') else None,
           'norm': 'Huber (t = 1.345)' if method != 'bisquare' else 'Tukey bisquare (c = 4.685)',
           'notes': notes, 'curve': {'x': g, 'fit': b[0] + b[1] * g}}
    if want_rows:
        pr = b[0] + b[1] * xy.x
        out['row_values'] = {'rows': xy.rows, 'predicted': pr, 'residual': xy.y - pr, 'weights': _unexpand(np.asarray(res.weights, float), reps)}
    c = _head(table_name, where)
    c.append(f'd = df[[{J(x)}, {J(y)}]].dropna()')
    c.append(f'res = sm.RLM(d[{J(y)}], sm.add_constant(d[{J(x)}]), M=sm.robust.norms.{"TukeyBiweight" if method == "bisquare" else "HuberT"}()).fit()')
    c.append('print(res.summary())')
    out['code'] = '\n'.join(c)
    return out


def _deming(sxx, syy, sxy, delta):
    """The orthogonal (Deming) slope for error variance ratio delta =
    var(error in Y) / var(error in X); delta 0 fits X to Y."""
    sxx, syy, sxy = np.asarray(sxx, float), np.asarray(syy, float), np.asarray(sxy, float)
    delta = np.asarray(delta, float)
    with np.errstate(divide='ignore', invalid='ignore'):
        dm = syy - delta * sxx
        b = (dm + np.sqrt(dm * dm + 4 * delta * sxy * sxy)) / (2 * sxy)
        b = np.where(delta == 0, syy / sxy, b)
    return b


@api('fitybyx.fit_orthogonal')
def fit_orthogonal(table, y, x, mode='univariate', ratio=None, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Fit Orthogonal: the line that minimises the distances to the points
    measured with the error variance ratio delta = var(Y error)/var(X
    error): Univariate Variances (delta = s_y²/s_x², the standardised
    principal component), Equal Variances (delta = 1), Fit X to Y (delta =
    0) or a given ratio. Standard errors by the jackknife over the
    observations (the delta of Univariate Variances re-estimated each
    time)."""
    xy = _xy(table, y, x, rows, weight, freq)
    if xy.n < 3:
        return {'error': 'too few rows'}
    w, wf, f = xy.w, xy.wf, xy.f
    N = xy.N
    W = wf.sum()
    Sx, Sy = np.sum(wf * xy.x), np.sum(wf * xy.y)
    Sxx, Syy, Sxy = np.sum(wf * xy.x ** 2), np.sum(wf * xy.y ** 2), np.sum(wf * xy.x * xy.y)

    def fit(W_, Sx_, Sy_, Sxx_, Syy_, Sxy_):
        mx_, my_ = Sx_ / W_, Sy_ / W_
        cxx, cyy, cxy = Sxx_ - Sx_ * mx_, Syy_ - Sy_ * my_, Sxy_ - Sx_ * my_
        if mode == 'univariate':
            dl = cyy / cxx
        elif mode == 'equal':
            dl = np.ones_like(cxx)
        elif mode == 'x_to_y':
            dl = np.zeros_like(cxx)
        else:
            dl = np.full_like(cxx, float(ratio if ratio is not None else 1.0))
        b_ = _deming(cxx, cyy, cxy, dl)
        return b_, my_ - b_ * mx_, dl

    b, a, dl = fit(np.array(W), np.array(Sx), np.array(Sy), np.array(Sxx), np.array(Syy), np.array(Sxy))
    b, a, dl = float(b), float(a), float(dl)
    # the jackknife: leave out one observation (one unit of a row's Freq)
    bi, ai, _ = fit(W - w, Sx - w * xy.x, Sy - w * xy.y, Sxx - w * xy.x ** 2, Syy - w * xy.y ** 2, Sxy - w * xy.x * xy.y)
    keep = np.isfinite(bi) & (f > 0)
    bm = np.sum(f[keep] * bi[keep]) / np.sum(f[keep])
    am = np.sum(f[keep] * ai[keep]) / np.sum(f[keep])
    se_b = float(np.sqrt((N - 1) / N * np.sum(f[keep] * (bi[keep] - bm) ** 2)))
    se_a = float(np.sqrt((N - 1) / N * np.sum(f[keep] * (ai[keep] - am) ** 2)))
    t = float(stats.t.ppf(1 - alpha / 2, N - 2))
    mx, my = Sx / W, Sy / W
    sdx = math.sqrt((Sxx - Sx * mx) / W * N / (N - 1))
    sdy = math.sqrt((Syy - Sy * my) / W * N / (N - 1))
    r = (Sxy - Sx * my) / math.sqrt((Sxx - Sx * mx) * (Syy - Sy * my))
    g = np.array([float(xy.x.min()), float(xy.x.max())])
    out = {'kind': 'orth', 'mode': mode, 'ratio': dl, 'n': N, 'intercept': a, 'slope': b, 'se_intercept': se_a, 'se_slope': se_b,
           'lower': b - t * se_b, 'upper': b + t * se_b, 'lower_intercept': a - t * se_a, 'upper_intercept': a + t * se_a, 'alpha': alpha,
           'means': [{'variable': x, 'mean': float(mx), 'sd': sdx}, {'variable': y, 'mean': float(my), 'sd': sdy}], 'r': float(r),
           'terms': [{'term': 'Intercept', 'estimate': a}, {'term': x, 'estimate': b}], 'curve': {'x': g, 'fit': a + b * g}}
    c = _head(table_name, where)
    c.append(f'd = df[[{J(x)}, {J(y)}]].dropna(); sxx, syy, sxy = d[{J(x)}].var(), d[{J(y)}].var(), d[{J(x)}].cov(d[{J(y)}])')
    c.append(f'delta = {"syy / sxx" if mode == "univariate" else repr(dl)}   # var(Y error) / var(X error)')
    c.append('b = syy / sxy if delta == 0 else (syy - delta*sxx + np.sqrt((syy - delta*sxx)**2 + 4*delta*sxy**2)) / (2*sxy)')
    c.append(f'print(d[{J(y)}].mean() - b * d[{J(x)}].mean(), b)   # intercept, slope; the standard errors are jackknifed')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.density_ellipse')
def density_ellipse(table, y, x, levels=(0.95,), rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Density Ellipse: contours of the bivariate normal with the sample
    means and covariance that hold probability P; the correlation with its
    test and its Fisher-z confidence interval."""
    from statsmodels.stats.weightstats import DescrStatsW
    xy = _xy(table, y, x, rows, weight, freq)
    if xy.n < 3:
        return {'error': 'too few rows'}
    d = DescrStatsW(np.column_stack([xy.x, xy.y]), weights=xy.wf, ddof=1)
    mean = np.asarray(d.mean, float)
    cov = np.asarray(d.cov, float)
    sd = np.sqrt(np.diag(cov))
    N = xy.N
    if not (sd[0] > 0 and sd[1] > 0):
        return {'error': 'X or Y is constant'}
    r = float(cov[0, 1] / (sd[0] * sd[1]))
    if not xy.weighted:
        pr = stats.pearsonr(xy.x, xy.y)
        p = float(pr.pvalue)
        ci = pr.confidence_interval(1 - alpha)
        lo, hi = float(ci.low), float(ci.high)
    else:
        tt = r * math.sqrt((N - 2) / max(1e-300, 1 - r * r))
        p = float(2 * stats.t.sf(abs(tt), N - 2))
        z, s = math.atanh(max(-0.999999999, min(0.999999999, r))), 1 / math.sqrt(N - 3) if N > 3 else float('nan')
        q = stats.norm.ppf(1 - alpha / 2)
        lo, hi = math.tanh(z - q * s), math.tanh(z + q * s)
    try:
        L = np.linalg.cholesky(cov)
    except np.linalg.LinAlgError:
        return {'error': 'X and Y lie on a line'}
    th = np.linspace(0, 2 * np.pi, 121)
    circle = np.vstack([np.cos(th), np.sin(th)])
    ell = []
    for P in levels:
        c = math.sqrt(stats.chi2.ppf(float(P), 2))
        pts = mean[:, None] + c * (L @ circle)
        ell.append({'p': float(P), 'x': pts[0], 'y': pts[1]})
    out = {'kind': 'ellipse', 'n': N, 'means': [{'variable': x, 'mean': float(mean[0]), 'sd': float(sd[0])}, {'variable': y, 'mean': float(mean[1]), 'sd': float(sd[1])}],
           'r': r, 'p': p, 'lower': lo, 'upper': hi, 'alpha': alpha, 'cov': float(cov[0, 1]), 'ellipses': ell}
    c = _head(table_name, where, ['from scipy import stats'])
    c.append(f'd = df[[{J(x)}, {J(y)}]].dropna()')
    c.append(f'r = stats.pearsonr(d[{J(x)}], d[{J(y)}]); print(r.statistic, r.pvalue, r.confidence_interval({1 - alpha!r}))   # Fisher z interval')
    c.append(f'm, S = d.mean().to_numpy(), d.cov().to_numpy(); L = np.linalg.cholesky(S); t = np.linspace(0, 2*np.pi, 100)')
    c.append(f'ellipse = m[:, None] + np.sqrt(stats.chi2.ppf({levels[0] if levels else 0.95!r}, 2)) * (L @ np.vstack([np.cos(t), np.sin(t)]))')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.nonpar_density')
def nonpar_density(table, y, x, rows=None, weight=None, freq=None, grid=64, quantiles=(0.1, 0.25, 0.5, 0.75, 0.9), max_points=3000, alpha=0.05, where=None, table_name='data'):
    """Nonpar Density: a Gaussian kernel density of the standardised points
    (scipy.stats.gaussian_kde, Scott's bandwidth) with contours at the
    density exceeded by 90%, 75%, 50%, 25% and 10% of the points, so that
    each contour holds about that share of the points. Large tables are
    estimated from a random subsample of max_points rows (a fixed seed)."""
    xy = _xy(table, y, x, rows, weight, freq)
    if xy.n < 5:
        return {'error': 'too few rows'}
    idx = np.arange(xy.n)
    sub = False
    if xy.n > max_points:
        idx = np.sort(np.random.default_rng(SEED).choice(xy.n, max_points, replace=False))
        sub = True
    xv, yv, wv = xy.x[idx], xy.y[idx], xy.wf[idx]
    mx, my = np.average(xv, weights=wv), np.average(yv, weights=wv)
    sx = math.sqrt(np.average((xv - mx) ** 2, weights=wv)) or 1.0
    sy = math.sqrt(np.average((yv - my) ** 2, weights=wv)) or 1.0
    kde = stats.gaussian_kde(np.vstack([(xv - mx) / sx, (yv - my) / sy]), weights=wv)
    px = 0.12 * (xv.max() - xv.min() or 1)
    py = 0.12 * (yv.max() - yv.min() or 1)
    gx = np.linspace(xv.min() - px, xv.max() + px, grid)
    gy = np.linspace(yv.min() - py, yv.max() + py, grid)
    GX, GY = np.meshgrid(gx, gy)
    z = kde(np.vstack([((GX.ravel() - mx) / sx), ((GY.ravel() - my) / sy)])).reshape(GX.shape) / (sx * sy)
    dens = kde(np.vstack([(xv - mx) / sx, (yv - my) / sy])) / (sx * sy)
    order = np.argsort(dens)
    cw = np.cumsum(wv[order]) / wv.sum()
    lv = [{'q': float(q), 'value': float(dens[order][min(len(order) - 1, np.searchsorted(cw, q))])} for q in quantiles]
    out = {'kind': 'kde', 'x': gx, 'y': gy, 'z': z, 'levels': lv, 'bw': float(kde.factor), 'subsample': int(len(idx)) if sub else None, 'n': xy.N}
    c = _head(table_name, where, ['from scipy import stats'])
    c.append(f'd = df[[{J(x)}, {J(y)}]].dropna(); z = (d - d.mean()) / d.std(ddof=0)')
    c.append('kde = stats.gaussian_kde(z.to_numpy().T)   # density of the standardised points')
    c.append(f'levels = np.quantile(kde(z.to_numpy().T), {list(quantiles)!r})   # contour q holds about 1 - q of the points')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.fit_quantile')
def fit_quantile(table, y, x, tau=0.5, rows=None, weight=None, freq=None, alpha=0.05, want_rows=False, where=None, table_name='data'):
    """Fit Quantile: the line of the tau-quantile of Y given X (statsmodels
    QuantReg; standard errors by its default kernel sandwich)."""
    import statsmodels.api as sm
    xy = _xy(table, y, x, rows, weight, freq)
    if xy.n < 3:
        return {'error': 'too few rows'}
    tau = float(min(0.99, max(0.01, tau)))
    yv, xv, reps = xy.expand()
    notes = ['statsmodels\' QuantReg takes no weights: Weight is not used here.'] if weight else []
    X = sm.add_constant(xv, has_constant='add')
    res = sm.QuantReg(yv, X).fit(q=tau)
    b = np.asarray(res.params, float)
    g = np.array([float(xv.min()), float(xv.max())])
    out = {'kind': 'quantile', 'tau': tau, 'n': float(len(yv)), 'estimates': _estimates(res, ['Intercept', x], alpha),
           'terms': [{'term': 'Intercept', 'estimate': float(b[0])}, {'term': x, 'estimate': float(b[1])}],
           'prsquared': float(res.prsquared), 'notes': notes, 'curve': {'x': g, 'fit': b[0] + b[1] * g}}
    if want_rows:
        pr = b[0] + b[1] * xy.x
        out['row_values'] = {'rows': xy.rows, 'predicted': pr, 'residual': xy.y - pr}
    c = _head(table_name, where)
    c.append(f'd = df[[{J(x)}, {J(y)}]].dropna()')
    c.append(f'res = smf.quantreg({J(_q(y) + " ~ " + _q(x))}, d).fit(q={tau!r}); print(res.summary())')
    out['code'] = '\n'.join(c)
    return out


# ---- Oneway -------------------------------------------------------------------

class _OW:
    """A continuous Y by the levels of a categorical X."""

    def __init__(self, table, y, x, rows=None, weight=None, freq=None, block=None):
        df = data.frame(table, [y, x, block, weight, freq], rows)
        df, w, f = _wf(df, table, weight, freq)
        xs = df[x]
        if not isinstance(xs.dtype, pd.CategoricalDtype):
            xs = pd.Series(pd.Categorical(xs), index=df.index)
        xs = xs.cat.remove_unused_categories()
        self.levels = list(xs.cat.categories)
        self.code = xs.cat.codes.to_numpy().astype(int)
        self.y = df[y].to_numpy(float)
        self.w, self.f = w, f
        self.wf = w * f
        self.rows = df.index.to_numpy()
        self.k = len(self.levels)
        self.names = (y, x, block, weight, freq)
        self.weight, self.freq = weight, freq
        self.N = float(np.sum(f))
        self.block_code = None
        if block:
            bs = df[block]
            if not isinstance(bs.dtype, pd.CategoricalDtype):
                bs = pd.Series(pd.Categorical(bs), index=df.index)
            bs = bs.cat.remove_unused_categories()
            self.blocks = list(bs.cat.categories)
            self.block_code = bs.cat.codes.to_numpy().astype(int)

    def expanded(self):
        """(y, code, reps): Freq counted by repeating rows."""
        if not self.freq:
            return self.y, self.code, None
        r = _reps(self.f)
        return np.repeat(self.y, r), np.repeat(self.code, r), r

    def samples(self):
        y, code, _ = self.expanded()
        return [y[code == i] for i in range(self.k)]

    def cell_means(self):
        """The cell-means model, y on one indicator per level, with the
        page's weights: means, pooled standard errors and intervals."""
        X = np.zeros((len(self.y), self.k))
        X[np.arange(len(self.y)), self.code] = 1.0
        xy = _XY(self.y, None, self.w, self.f, self.rows, self.weight, self.freq)
        return _fit_wls(X, self.y, xy)


def _ow_code(G, table_name, where, imports=()):
    y, x, block, weight, freq = G.names
    c = _head(table_name, where, imports)
    c.append(f'd = df[[{", ".join(J(v) for v in (y, x, block, weight, freq) if v)}]].dropna()')
    return c


def _level_stats(G, alpha):
    from statsmodels.stats.weightstats import DescrStatsW
    try:
        y, code, _ = G.expanded()
    except ValueError:
        y = code = None   # fractional Freq: weighted quantiles instead
    out = []
    for i in range(G.k):
        yi = G.y[G.code == i]
        fi = G.f[G.code == i]
        n = float(fi.sum())
        d = DescrStatsW(yi, weights=fi, ddof=1)
        s = {'level': G.levels[i], 'index': i, 'n': n, 'mean_raw': float(d.mean), 'min': float(yi.min()), 'max': float(yi.max())}
        if n > 1:
            s['sd'] = float(d.std)
            s['se'] = float(d.std_mean)
            lo, hi = d.tconfint_mean(alpha)
            s['lower'], s['upper'] = float(lo), float(hi)
        if y is not None:
            ye = y[code == i]
            qs = np.quantile(ye, [0.1, 0.25, 0.5, 0.75, 0.9], method='weibull')
        else:
            ye = yi
            qs = np.asarray(d.quantile([0.1, 0.25, 0.5, 0.75, 0.9], return_pandas=False), float)
        s.update({'q10': float(qs[0]), 'q25': float(qs[1]), 'median': float(qs[2]), 'q75': float(qs[3]), 'q90': float(qs[4])})
        # the whiskers of an outlier box plot: the furthest values within 1.5 IQR
        iqr = qs[3] - qs[1]
        inside = ye[(ye >= qs[1] - 1.5 * iqr) & (ye <= qs[3] + 1.5 * iqr)]
        s['lo_fence'] = float(inside.min()) if len(inside) else float(qs[1])
        s['hi_fence'] = float(inside.max()) if len(inside) else float(qs[3])
        out.append(s)
    return out


@api('fitybyx.oneway')
def oneway(table, y, x, rows=None, weight=None, freq=None, block=None, alpha=0.05, where=None, table_name='data'):
    """Oneway: the levels' counts, means, standard deviations and
    quantiles; the one-way ANOVA (with a Block: the randomized block
    ANOVA, the block an additive effect) with its Summary of Fit and Means
    for Oneway Anova (pooled standard errors); for two levels the pooled t
    test."""
    from statsmodels.stats.weightstats import CompareMeans, DescrStatsW
    G = _OW(table, y, x, rows, weight, freq, block)
    if G.k < 1 or G.N < 2:
        return {'error': 'fewer than two rows with both values'}
    notes = []
    levels = _level_stats(G, alpha)
    out = {'levels': levels, 'k': G.k, 'n': G.N, 'n_rows': len(G.y), 'alpha': alpha, 'notes': notes,
           'grand_mean': float(np.average(G.y, weights=G.wf))}
    if G.k < 2:
        out['error_anova'] = 'X has one level: no analysis of variance'
        out['code'] = '\n'.join(_ow_code(G, table_name, where))
        return out
    # the cell-means model: weighted means with the pooled standard error
    cm = G.cell_means()
    ci = np.asarray(cm.conf_int(alpha))
    for i, s in enumerate(levels):
        s['mean'] = float(cm.params[i])
        s['se_pooled'] = float(cm.bse[i])
        s['lower_pooled'], s['upper_pooled'] = float(ci[i, 0]), float(ci[i, 1])
    effects = [[x]] + ([[block]] if block else [])
    d = models.build(table, y, effects, rows, weight, freq)
    f = _freq_of(table, freq, d.df.index)
    res = _fit_design(d, f)
    wf = np.asarray(d.weights, float) if d.weights is not None else np.ones(len(d.df))
    yv = d.df[d.y_alias].to_numpy(float)
    count = float(np.sum(f)) if f is not None else float(len(d.df))
    out['summary'] = _summary_of_fit(res, yv, wf, count if not weight else float(np.sum(wf)))
    for r_ in out['summary']['rows']:
        r_['stat'] = {'RSquare': 'Rsquare', 'RSquare Adj': 'Adj Rsquare'}.get(r_['stat'], r_['stat'])
    out['rmse'] = float(np.sqrt(res.mse_resid)) if res.df_resid > 0 else None
    out['df_error'] = float(res.df_resid)
    if block:
        et = models.effect_tests(d, res)['rows']
        mse = float(res.mse_resid)
        arows = []
        for e in et:
            arows.append({'source': e['source'], 'df': float(e['df']), 'ss': e['ss'], 'ms': e['ss'] / e['df'], 'f': e['stat'], 'p': e['p']})
        arows.append({'source': 'Error', 'df': float(res.df_resid), 'ss': float(res.ssr), 'ms': mse, 'f': None, 'p': None})
        arows.append({'source': 'C. Total', 'df': float(res.df_resid + res.df_model), 'ss': float(res.centered_tss), 'ms': None, 'f': None, 'p': None})
        out['anova'] = _tab([col('source', 'Source', 'text'), col('df', 'DF'), col('ss', 'Sum of Squares'), col('ms', 'Mean Square'),
                             col('f', 'F Ratio'), col('p', 'Prob > F', 'p')], arows)
        # least squares means of X, the block effect averaged
        from patsy import build_design_matrices
        di = res.model.data.design_info
        blocks = d.levels[d.alias[block]]
        L = []
        for lv in d.levels[d.alias[x]]:
            fr = d.frame_for({x: [lv] * len(blocks), block: blocks})
            L.append(np.asarray(build_design_matrices([di], fr)[0]).mean(axis=0))
        tt = res.t_test(np.array(L))
        eff = np.asarray(tt.effect).ravel()
        sd = np.asarray(tt.sd).ravel()
        tci = np.asarray(tt.conf_int(alpha))
        for i, s in enumerate(levels):
            s['lsmean'] = float(eff[i])
            s['se_lsmean'] = float(sd[i])
            s['lower_lsmean'], s['upper_lsmean'] = float(tci[i, 0]), float(tci[i, 1])
        bm = []
        for j, b in enumerate(G.blocks):
            sel = G.block_code == j
            bm.append({'level': b, 'n': float(G.f[sel].sum()), 'mean': float(np.average(G.y[sel], weights=G.wf[sel]))})
        out['block_means'] = bm
        out['block_levels'] = len(G.blocks)
    else:
        out['anova'] = _anova(res, x)
    if G.k == 2 and not block:
        a, b = [G.y[G.code == i] for i in (0, 1)]
        fa, fb = [G.f[G.code == i] for i in (0, 1)]
        cmp = CompareMeans(DescrStatsW(b, weights=fb), DescrStatsW(a, weights=fa))
        t, p, dof = cmp.ttest_ind(usevar='pooled')
        lo, hi = cmp.tconfint_diff(alpha=alpha, usevar='pooled')
        diff = float(np.average(b, weights=fb) - np.average(a, weights=fa))
        out['pooled_t'] = {'diff': diff, 'se': float(cmp.std_meandiff_pooledvar), 'lower': float(lo), 'upper': float(hi), 't': float(t), 'df': float(dof),
                           'p': float(p), 'p_greater': float(stats.t.sf(t, dof)), 'p_less': float(stats.t.cdf(t, dof)), 'confidence': 1 - alpha}
        if weight:
            notes.append('The pooled t test uses Freq and not Weight (statsmodels\' CompareMeans counts weights as frequencies).')
    c = _ow_code(G, table_name, where)
    formula = f'{_q(y)} ~ C({_q(x)})' + (f' + C({_q(block)})' if block else '')
    we = _wexpr(weight, freq)
    c.append(f'res = smf.{"wls" if we else "ols"}({J(formula)}, d{", weights=" + we if we else ""}).fit()')
    c.append(f'print(sm.stats.anova_lm(res, typ={3 if block else 1}))   # the Analysis of Variance')
    c.append(f'print(d.groupby({J(x)})[{J(y)}].agg(["count", "mean", "std"]))   # Means and Std Deviations')
    if G.k == 2 and not block:
        c.append(f'from scipy import stats; a, b = [g[{J(y)}] for _, g in d.groupby({J(x)})]; print(stats.ttest_ind(b, a))   # pooled t test, second level minus first')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.oneway_ttest')
def oneway_ttest(table, y, x, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """t Test: two levels, the second minus the first, without assuming
    equal variances (Welch-Satterthwaite degrees of freedom)."""
    from statsmodels.stats.weightstats import CompareMeans, DescrStatsW
    G = _OW(table, y, x, rows, weight, freq)
    if G.k != 2:
        return {'error': 't Test needs exactly two levels of X'}
    a, b = [G.y[G.code == i] for i in (0, 1)]
    fa, fb = [G.f[G.code == i] for i in (0, 1)]
    if fa.sum() < 2 or fb.sum() < 2:
        return {'error': 'each level needs two values'}
    cmp = CompareMeans(DescrStatsW(b, weights=fb), DescrStatsW(a, weights=fa))
    t, p, dof = cmp.ttest_ind(usevar='unequal')
    lo, hi = cmp.tconfint_diff(alpha=alpha, usevar='unequal')
    diff = float(np.average(b, weights=fb) - np.average(a, weights=fa))
    out = {'diff': diff, 'se': float(cmp.std_meandiff_separatevar), 'lower': float(lo), 'upper': float(hi), 't': float(t), 'df': float(dof), 'p': float(p),
           'p_greater': float(stats.t.sf(t, dof)), 'p_less': float(stats.t.cdf(t, dof)), 'confidence': 1 - alpha,
           'levels': G.levels, 'notes': ['Weight is not used by the t test.'] if weight else []}
    c = _ow_code(G, table_name, where, ['from scipy import stats'])
    c.append(f'a, b = [g[{J(y)}] for _, g in d.groupby({J(x)}, observed=True)]')
    c.append('print(stats.ttest_ind(b, a, equal_var=False))   # Welch: the second level minus the first')
    out['code'] = '\n'.join(c)
    return out


NCP_T_CODE = '''def ncp(t, df, q):   # the noncentrality at which t is the q quantile of the noncentral t
    return optimize.brentq(lambda lam: stats.nct.cdf(t, df, lam) - q, t - 10 - abs(t), t + 10 + abs(t))'''


def _two_levels(G):
    """The two levels' values and frequencies, the first level first."""
    a, b = [G.y[G.code == i] for i in (0, 1)]
    fa, fb = [G.f[G.code == i] for i in (0, 1)]
    return a, b, fa, fb


@api('fitybyx.oneway_effect')
def oneway_effect(table, y, x, rows=None, weight=None, freq=None, block=None, alpha=0.05, where=None, table_name='data'):
    """Effect Size of the one-way ANOVA: η² = SS_X/SS_total, ε² = (SS_X −
    df_X MS_E)/SS_total (Kelley 1935) and ω² = (SS_X − df_X MS_E)/(SS_total +
    MS_E) (Hays 1963); with a Block their partial forms, the block's sum of
    squares left out. The interval is the exact one of the population
    proportion of variance η²_pop = λ/(λ + df_X + df_E + 1), from the
    noncentral F whose λ puts the observed F at its upper and lower α/2
    points (Steiger 2004); the three estimates estimate that same
    proportion, with less bias from η² to ω²."""
    G = _OW(table, y, x, rows, weight, freq, block)
    if G.k < 2:
        return {'error': 'X has one level: no analysis of variance'}
    effects = [[x]] + ([[block]] if block else [])
    d = models.build(table, y, effects, rows, weight, freq)
    f = _freq_of(table, freq, d.df.index)
    res = _fit_design(d, f)
    df_e, ss_e = float(res.df_resid), float(res.ssr)
    if df_e <= 0:
        return {'error': 'no degrees of freedom for error'}
    if block:
        et = models.effect_tests(d, res)['rows'][0]
        ss_x, df_x = float(et['ss']), float(et['df'])
    else:
        ss_x, df_x = float(res.ess), float(res.df_model)
    ms_e = ss_e / df_e
    N = df_x + df_e + 1          # the observations (Freq summed) in the one-way layout
    count = float(np.sum(f)) if f is not None else float(len(d.df))
    ss_t = ss_x + ss_e
    F = (ss_x / df_x) / ms_e if ms_e > 0 else float('inf')
    lam_lo, lam_hi = ncf_interval(F, df_x, df_e, alpha) if math.isfinite(F) else (float('nan'), float('nan'))
    pop = lambda lam: lam / (lam + N)
    lo, hi = pop(lam_lo), pop(lam_hi)
    pre = 'Partial ' if block else ''
    rows_out = [
        {'effect': f'{pre}η² (eta²)', 'estimate': ss_x / ss_t, 'lower': lo, 'upper': hi, 'method': 'noncentral F'},
        {'effect': f'{pre}ε² (epsilon²)', 'estimate': (ss_x - df_x * ms_e) / ss_t, 'lower': lo, 'upper': hi, 'method': 'noncentral F'},
        {'effect': f'{pre}ω² (omega²)', 'estimate': (ss_x - df_x * ms_e) / (ss_x + (count - df_x) * ms_e), 'lower': lo, 'upper': hi, 'method': 'noncentral F'},
    ]
    notes = []
    if weight:
        notes.append('With Weight the sums of squares are weighted, as in the Analysis of Variance.')
    out = {'table': _es_table(rows_out, alpha), 'F': F, 'df_num': df_x, 'df_den': df_e, 'lambda': [lam_lo, lam_hi], 'n': count, 'alpha': alpha,
           'partial': bool(block), 'notes': notes}
    c = _ow_code(G, table_name, where, ['from scipy import stats, optimize'])
    if freq:
        c.append(_repeat_code(freq))
    formula = f'{_q(y)} ~ C({_q(x)})' + (f' + C({_q(block)})' if block else '')
    c.append(f'res = smf.{"wls" if weight else "ols"}({J(formula)}, d{", weights=d[" + J(weight) + "]" if weight else ""}).fit(); a = sm.stats.anova_lm(res, typ={3 if block else 1})')
    c.append(f'ss_x, df_x = a.loc[{J("C(" + _q(x) + ")")}, "sum_sq"], a.loc[{J("C(" + _q(x) + ")")}, "df"]; ss_e, df_e = res.ssr, res.df_resid; ms_e = ss_e / df_e')
    c.append('print(ss_x / (ss_x + ss_e), (ss_x - df_x*ms_e) / (ss_x + ss_e), (ss_x - df_x*ms_e) / (ss_x + (res.nobs - df_x)*ms_e))   # η², ε², ω²' + (' (partial)' if block else ''))
    c.append('F = ss_x / df_x / ms_e')
    c.append('def ncp(q):   # the noncentrality at which F is the q quantile of the noncentral F (0 when λ = 0 already puts it lower)')
    c.append('    g = lambda lam: stats.ncf.cdf(F, df_x, df_e, lam) - q')
    c.append('    return 0.0 if g(0) < 0 else optimize.brentq(g, 0, 100 + 10 * F * df_x)')
    c.append(f'lo, hi = ncp({1 - alpha / 2!r}), ncp({alpha / 2!r}); N = df_x + df_e + 1')
    c.append('print(lo / (lo + N), hi / (hi + N))   # the exact interval of the population η² (Steiger 2004)')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.ttest_effect')
def ttest_effect(table, y, x, kind='pooled', rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Effect Size of a two-level t test, the second level minus the first.
    pooled: Cohen's d = difference/s_pooled with the exact interval from the
    noncentral t of the pooled t (δ = λ√(1/n₁ + 1/n₂)), and Hedges' g =
    J(n₁ + n₂ − 2)·d. welch: d* = difference/√((s₁² + s₂²)/2), Cohen's
    (1988) standardizer for unequal variances, with Bonett's (2008)
    interval d* ± z·SE (no exact interval exists without equal variances),
    and g* = J(n₁ + n₂ − 2)·d*. Freq counts rows; Weight is not used, as in
    the t tests."""
    from statsmodels.stats.weightstats import DescrStatsW
    G = _OW(table, y, x, rows, weight, freq)
    if G.k != 2:
        return {'error': 'an effect size of a t test needs exactly two levels of X'}
    if kind not in ('pooled', 'welch'):
        return {'error': f'unknown t test {kind!r}'}
    a, b, fa, fb = _two_levels(G)
    da, db = DescrStatsW(a, weights=fa, ddof=1), DescrStatsW(b, weights=fb, ddof=1)
    n1, n2 = float(da.sum_weights), float(db.sum_weights)
    if n1 < 2 or n2 < 2:
        return {'error': 'each level needs two values'}
    v1, v2 = float(da.var), float(db.var)
    diff = float(db.mean - da.mean)
    df = n1 + n2 - 2
    z = float(stats.norm.ppf(1 - alpha / 2))
    notes = ['Weight is not used here, as in the t tests; Freq is.'] if weight else []
    if kind == 'pooled':
        sp = math.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / df)
        if not sp > 0:
            return {'error': 'no variation within the levels'}
        d = diff / sp
        k = math.sqrt(1 / n1 + 1 / n2)
        rows_out = smd_rows(d, d / k, df, k, alpha)
        out = {'table': _es_table(rows_out, alpha), 'standardizer': sp, 't': d / k, 'df': df, 'n1': n1, 'n2': n2, 'j': rows_out[1]['j']}
    else:
        s = math.sqrt((v1 + v2) / 2)
        if not s > 0:
            return {'error': 'no variation within the levels'}
        d = diff / s
        se = bonett_se(d, v1, v2, n1, n2)
        j = hedges_j(df)
        rows_out = [{'effect': "Cohen's d*", 'estimate': d, 'lower': d - z * se, 'upper': d + z * se, 'method': 'Bonett (2008)', 'se': se},
                    {'effect': "Hedges' g*", 'estimate': j * d, 'lower': j * (d - z * se), 'upper': j * (d + z * se), 'method': 'Bonett (2008) × J', 'se': j * se}]
        t_ = _tab([col('effect', 'Effect Size', 'text'), col('estimate', 'Estimate'), col('lower', f'Lower {100 * (1 - alpha):g}%'), col('upper', f'Upper {100 * (1 - alpha):g}%'),
                   col('method', 'Interval', 'text'), col('se', 'Std Err', hidden=True)], rows_out)
        out = {'table': t_, 'standardizer': s, 'df': df, 'n1': n1, 'n2': n2, 'j': j}
    out.update({'kind': kind, 'diff': diff, 'levels': G.levels, 'alpha': alpha, 'notes': notes})
    c = _ow_code(G, table_name, where, ['from scipy import stats, optimize, special'])
    if freq:
        c.append(_repeat_code(freq))
    c.append(f'a, b = [g[{J(y)}].to_numpy() for _, g in d.groupby({J(x)}, observed=True)]   # the first level, the second')
    c.append('n1, n2, v1, v2 = len(a), len(b), a.var(ddof=1), b.var(ddof=1); df_ = n1 + n2 - 2')
    c.append('J = np.exp(special.gammaln(df_ / 2) - 0.5 * np.log(df_ / 2) - special.gammaln((df_ - 1) / 2))   # Hedges\' exact correction')
    if kind == 'pooled':
        c.append(NCP_T_CODE)
        c.append('sp = np.sqrt(((n1 - 1)*v1 + (n2 - 1)*v2) / df_); d_ = (b.mean() - a.mean()) / sp; k = np.sqrt(1/n1 + 1/n2); t = d_ / k')
        c.append(f'lo, hi = ncp(t, df_, {1 - alpha / 2!r}) * k, ncp(t, df_, {alpha / 2!r}) * k')
        c.append("print(d_, lo, hi, J * d_, J * lo, J * hi)   # Cohen's d with its exact interval (noncentral t), Hedges' g = J d")
    else:
        c.append('s = np.sqrt((v1 + v2) / 2); d_ = (b.mean() - a.mean()) / s')
        c.append('se = np.sqrt(d_**2 * (v1**2/(n1 - 1) + v2**2/(n2 - 1)) / (8 * s**4) + (v1/(n1 - 1) + v2/(n2 - 1)) / s**2)   # Bonett (2008)')
        c.append(f'z = stats.norm.ppf({1 - alpha / 2!r}); print(d_, d_ - z*se, d_ + z*se, J * d_)   # d* with Bonett\'s interval, Hedges\' g* = J d*')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.oneway_bf')
def oneway_bf(table, y, x, r=JZS_R, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Bayes Factor of the two-sample t test (Rouder et al. 2009): the
    pooled t of the second level minus the first, a Cauchy(0, r) prior on δ
    = (μ₂ − μ₁)/σ under the alternative, equal variances; two-sided and
    one-sided (δ > 0, δ < 0). Freq counts rows; Weight is not used."""
    from statsmodels.stats.weightstats import DescrStatsW
    G = _OW(table, y, x, rows, weight, freq)
    if G.k != 2:
        return {'error': 'the Bayes factor of the t test needs exactly two levels of X'}
    if not (r and r > 0):
        return {'error': 'the scale of the Cauchy prior must be positive'}
    a, b, fa, fb = _two_levels(G)
    da, db = DescrStatsW(a, weights=fa, ddof=1), DescrStatsW(b, weights=fb, ddof=1)
    n1, n2 = float(da.sum_weights), float(db.sum_weights)
    if n1 < 2 or n2 < 2:
        return {'error': 'each level needs two values'}
    df = n1 + n2 - 2
    sp = math.sqrt(((n1 - 1) * float(da.var) + (n2 - 1) * float(db.var)) / df)
    if not sp > 0:
        return {'error': 'no variation within the levels'}
    t = float(db.mean - da.mean) / (sp * math.sqrt(1 / n1 + 1 / n2))
    ne = n1 * n2 / (n1 + n2)
    lv = [_lvtext(v) for v in G.levels]
    rows_out = jzs_rows(t, ne, df, r, ['δ ≠ 0', f'δ > 0 ({lv[1]} higher)', f'δ < 0 ({lv[1]} lower)'])
    out = {'table': _bf_table(rows_out), 't': t, 'df': df, 'n1': n1, 'n2': n2, 'n_eff': ne, 'r': r, 'levels': G.levels,
           'notes': ['Weight is not used here, as in the t tests; Freq is.'] if weight else []}
    c = _ow_code(G, table_name, where, ['from scipy import stats, integrate'])
    if freq:
        c.append(_repeat_code(freq))
    c.append(f'a, b = [g[{J(y)}].to_numpy() for _, g in d.groupby({J(x)}, observed=True)]')
    c.append('t, n1, n2 = stats.ttest_ind(b, a).statistic, len(a), len(b); n, df_ = n1*n2/(n1 + n2), n1 + n2 - 2   # the pooled t, second level minus first')
    c.append(JZS_CODE)
    c.append(f'bf, p = jzs(t, n, df_, {r!r}); print(bf, 2*bf*p, 2*bf*(1 - p))   # BF10: δ ≠ 0, δ > 0, δ < 0; BF01 = 1/BF10')
    out['code'] = '\n'.join(c)
    return out


def _letters(order, sig):
    """Connecting letters (the insert-absorb algorithm): levels in `order`
    (by mean, highest first); sig[i][j] true when i and j differ. Levels
    that share a letter are not significantly different. Returns each
    level's letters as a string with one position per letter column (a
    space where the level has not that letter), and the number of
    columns."""
    k = len(order)
    cols = [set(order)]
    for a in range(k):
        for b in range(a + 1, k):
            i, j = order[a], order[b]
            if not sig[i][j]:
                continue
            new = []
            for c in cols:
                if i in c and j in c:
                    new.append(c - {i})
                    new.append(c - {j})
                else:
                    new.append(c)
            kept = []
            for c in sorted([c for c in new if c], key=len, reverse=True):
                if not any(c <= d for d in kept):
                    kept.append(c)
            cols = kept
    pos = {lv: n for n, lv in enumerate(order)}
    cols.sort(key=lambda c: (min(pos[v] for v in c), -len(c)))
    alphabet = [chr(65 + i) for i in range(26)] + [chr(97 + i) for i in range(26)]
    names = [alphabet[n] if n < len(alphabet) else f'[{n + 1}]' for n in range(len(cols))]
    out = {lv: ' '.join(names[n] if lv in c else ' ' * len(names[n]) for n, c in enumerate(cols)).rstrip() for lv in order}
    return out, len(cols)


@api('fitybyx.oneway_compare')
def oneway_compare(table, y, x, method='student', control=None, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Compare Means: Each Pair, Student's t (pooled error, no
    adjustment); All Pairs, Tukey HSD (Tukey-Kramer: pairwise_tukeyhsd for
    the differences, scipy's studentized range for q* and the p-values);
    All Pairs, Games-Howell (unequal variances: each pair's Welch standard
    error and degrees of freedom, the studentized range); With Control,
    Dunnett's (scipy.stats.dunnett)."""
    from statsmodels.stats.multicomp import pairwise_tukeyhsd
    G = _OW(table, y, x, rows, weight, freq)
    if G.k < 2:
        return {'error': 'Compare Means needs two levels of X'}
    notes = []
    cm = G.cell_means()
    means = np.asarray(cm.params, float)
    dfe = float(cm.df_resid)
    mse = float(cm.mse_resid)
    n = np.array([G.f[G.code == i].sum() for i in range(G.k)])
    sw = np.array([G.wf[G.code == i].sum() for i in range(G.k)])
    if dfe <= 0:
        return {'error': 'no degrees of freedom for error'}
    order = [int(i) for i in np.argsort(-means, kind='stable')]
    pairs = []
    out = {'method': method, 'alpha': alpha, 'df': dfe, 'mse': mse, 'order': order, 'means': means, 'n': n, 'levels': G.levels, 'notes': notes}
    c = _ow_code(G, table_name, where)
    if method in ('student', 'tukey'):
        idx = [(i, j) for i in range(G.k) for j in range(i + 1, G.k)]
        if method == 'student':
            L = np.zeros((len(idx), G.k))
            for r, (i, j) in enumerate(idx):
                L[r, i], L[r, j] = 1, -1
            tt = cm.t_test(L)
            diffs, ses, ps = np.asarray(tt.effect).ravel(), np.asarray(tt.sd).ravel(), np.asarray(tt.pvalue).ravel()
            crit = float(stats.t.ppf(1 - alpha / 2, dfe))
            out['quantile'] = {'label': 't', 'value': crit}
            c.append(f'res = smf.ols({J(_q(y) + " ~ C(" + _q(x) + ") - 1")}, d).fit()   # the cell means, pooled error')
            c.append('print(res.t_test_pairwise(res.model.data.design_info.term_names[0]).result_frame)   # every pair, no adjustment')
        else:
            if weight:
                notes.append('pairwise_tukeyhsd takes no weights: Weight is not used here.')
            ye, ce, _ = G.expanded()
            tk = pairwise_tukeyhsd(ye, ce, alpha=alpha)
            gu = [int(v) for v in tk.groupsunique]
            k = len(gu)
            dfe = float(tk.df_total)
            md = np.asarray(tk.meandiffs, float)
            sp = np.asarray(tk.std_pairs, float)
            # statsmodels' pairs are (a, b) for a < b in groupsunique, the difference b - a
            pos = {}
            m = 0
            for a in range(k):
                for b in range(a + 1, k):
                    pos[(gu[a], gu[b])] = m
                    m += 1
            diffs, ses = np.zeros(len(idx)), np.zeros(len(idx))
            for r, (i, j) in enumerate(idx):
                q = pos[(i, j)]
                diffs[r] = -md[q]          # mean_i - mean_j
                ses[r] = sp[q] * math.sqrt(2)
            qcrit = float(stats.studentized_range.ppf(1 - alpha, k, dfe))
            crit = qcrit / math.sqrt(2)
            if len(idx) <= 300:
                ps = stats.studentized_range.sf(np.abs(diffs) / ses * math.sqrt(2), k, dfe)
            else:
                from statsmodels.stats.libqsturng import psturng
                ps = np.atleast_1d(psturng(np.abs(diffs) / ses * math.sqrt(2), k, dfe))
                notes.append('With more than 300 pairs the p-values are statsmodels\' psturng approximation (at least 0.001).')
            out['quantile'] = {'label': 'q*', 'value': crit}
            out['df'] = dfe
            notes.append('The differences are statsmodels\' pairwise_tukeyhsd; q* and the p-values are scipy\'s studentized range distribution (pairwise_tukeyhsd\'s own psturng approximation keeps p-values between 0.001 and 0.9).')
            c.append('from statsmodels.stats.multicomp import pairwise_tukeyhsd')
            c.append(f'tk = pairwise_tukeyhsd(d[{J(y)}], d[{J(x)}], alpha={alpha!r}); print(tk.summary())')
            c.append(f'from scipy import stats; print(stats.studentized_range.ppf({1 - alpha!r}, {k}, {dfe:g}) / np.sqrt(2))   # q*')
        for r, (i, j) in enumerate(idx):
            a, b = (i, j) if diffs[r] >= 0 else (j, i)
            dv = abs(float(diffs[r]))
            pairs.append({'i': a, 'j': b, 'diff': dv, 'se': float(ses[r]), 'lower': dv - crit * float(ses[r]), 'upper': dv + crit * float(ses[r]), 'p': float(ps[r])})
        pairs.sort(key=lambda p: -p['diff'])
        # the threshold matrix, Abs(Dif) - LSD, in the order of the means
        se_of = {}
        for p_ in pairs:
            se_of[(p_['i'], p_['j'])] = se_of[(p_['j'], p_['i'])] = p_['se']
        M = []
        for i in order:
            row = []
            for j in order:
                se_ij = se_of.get((i, j)) if i != j else math.sqrt(mse * 2 / sw[i]) if method == 'student' else math.sqrt(mse * 2 / n[i])
                row.append(abs(means[i] - means[j]) - crit * se_ij)
            M.append(row)
        out['matrix'] = M
        sig = [[False] * G.k for _ in range(G.k)]
        for p_ in pairs:
            if p_['p'] < alpha:
                sig[p_['i']][p_['j']] = sig[p_['j']][p_['i']] = True
        lets, ncols = _letters(order, sig)
        out['letters'] = [{'index': i, 'letters': lets[i], 'mean': float(means[i])} for i in order]
        out['pairs'] = pairs
    elif method == 'gameshowell':
        # Games and Howell (1976): each pair with its own (Welch) standard
        # error and degrees of freedom, p and intervals from the studentized
        # range of k levels on those degrees of freedom
        if weight:
            notes.append('Games-Howell uses each level\'s own variance and takes no weights: Weight is not used here.')
        smp = G.samples()
        if any(len(s) < 2 for s in smp):
            return {'error': 'Games-Howell needs two values in every level (it uses each level\'s own variance)'}
        mh = np.array([float(s.mean()) for s in smp])
        vh = np.array([float(s.var(ddof=1)) for s in smp])
        nh = np.array([float(len(s)) for s in smp])
        if not np.all(vh > 0):
            return {'error': 'a level has no variation: Games-Howell divides by each level\'s variance'}
        u = vh / nh

        def pair(i, j):
            se = math.sqrt(u[i] + u[j])
            dfw = (u[i] + u[j]) ** 2 / (u[i] ** 2 / (nh[i] - 1) + u[j] ** 2 / (nh[j] - 1))
            return se, dfw, float(stats.studentized_range.ppf(1 - alpha, G.k, dfw)) / math.sqrt(2)
        order = [int(i) for i in np.argsort(-mh, kind='stable')]
        out.update({'order': order, 'means': mh, 'n': nh, 'quantile': {'label': 'q* (each pair\'s)', 'value': None}})
        for i in range(G.k):
            for j in range(i + 1, G.k):
                se, dfw, crit = pair(i, j)
                a, b = (i, j) if mh[i] >= mh[j] else (j, i)
                dv = abs(float(mh[i] - mh[j]))
                pv = float(stats.studentized_range.sf(dv / se * math.sqrt(2), G.k, dfw))
                pairs.append({'i': a, 'j': b, 'diff': dv, 'se': se, 'lower': dv - crit * se, 'upper': dv + crit * se, 'p': min(1.0, max(0.0, pv)), 'df': dfw, 'q': crit})
        pairs.sort(key=lambda p: -p['diff'])
        M = []
        for i in order:
            row = []
            for j in order:
                se, dfw, crit = pair(i, j) if i != j else (math.sqrt(2 * u[i]), 2 * (nh[i] - 1), float(stats.studentized_range.ppf(1 - alpha, G.k, 2 * (nh[i] - 1))) / math.sqrt(2))
                row.append(abs(mh[i] - mh[j]) - crit * se)
            M.append(row)
        out['matrix'] = M
        sig = [[False] * G.k for _ in range(G.k)]
        for p_ in pairs:
            if p_['p'] < alpha:
                sig[p_['i']][p_['j']] = sig[p_['j']][p_['i']] = True
        lets, ncols = _letters(order, sig)
        out['letters'] = [{'index': i, 'letters': lets[i], 'mean': float(mh[i])} for i in order]
        out['pairs'] = pairs
        notes.append('Games-Howell: each difference over its own standard error √(s²ᵢ/nᵢ + s²ⱼ/nⱼ), with the Welch-Satterthwaite degrees of freedom of the pair; p-values and intervals from scipy\'s studentized range distribution of k levels on those degrees of freedom. It does not assume equal variances.')
        c = _ow_code(G, table_name, where, ['from scipy import stats', 'import itertools'])
        if freq:
            c.append(_repeat_code(freq))
        c.append(f'g = d.groupby({J(x)}, observed=True)[{J(y)}]; m, v, n = g.mean(), g.var(), g.count(); k = len(m)')
        c.append('for i, j in itertools.combinations(m.index, 2):   # Games-Howell, each pair')
        c.append('    a, b = v[i]/n[i], v[j]/n[j]; se = np.sqrt(a + b); df_ = (a + b)**2 / (a**2/(n[i] - 1) + b**2/(n[j] - 1))')
        c.append(f'    q = stats.studentized_range.ppf({1 - alpha!r}, k, df_) / np.sqrt(2)   # the pair\'s own quantile')
        c.append('    print(i, j, m[i] - m[j], se, df_, stats.studentized_range.sf(abs(m[i] - m[j]) / se * np.sqrt(2), k, df_), m[i] - m[j] - q*se, m[i] - m[j] + q*se)')
    elif method == 'dunnett':
        ci_ = G.levels.index(control) if control in G.levels else 0
        if weight:
            notes.append('scipy\'s dunnett takes no weights: Weight is not used here.')
        smp = G.samples()
        others = [i for i in range(G.k) if i != ci_]
        if any(len(smp[i]) < 1 for i in range(G.k)) or len(smp[ci_]) < 1:
            return {'error': 'every level needs values'}
        rs = stats.dunnett(*[smp[i] for i in others], control=smp[ci_], rng=np.random.default_rng(SEED))
        ci = rs.confidence_interval(1 - alpha)
        mse_e = float(np.sum([np.sum((s - s.mean()) ** 2) for s in smp]) / (sum(len(s) for s in smp) - G.k))
        dfe = float(sum(len(s) for s in smp) - G.k)
        n0 = len(smp[ci_])
        for r, i in enumerate(others):
            dv = float(smp[i].mean() - smp[ci_].mean())
            se = math.sqrt(mse_e * (1 / len(smp[i]) + 1 / n0))
            pairs.append({'i': i, 'j': ci_, 'diff': dv, 'se': se, 'lower': float(ci.low[r]), 'upper': float(ci.high[r]), 'p': float(rs.pvalue[r])})
        dcrit = float(np.median([(p_['upper'] - p_['diff']) / p_['se'] for p_ in pairs])) if pairs else None
        out['quantile'] = {'label': '|d|', 'value': dcrit}
        out['control'] = ci_
        out['df'] = dfe
        out['mse'] = mse_e
        out['pairs'] = sorted(pairs, key=lambda p: -p['diff'])
        out['matrix_control'] = [{'index': p_['i'], 'value': abs(p_['diff']) - dcrit * p_['se']} for p_ in pairs]
        notes.append('scipy.stats.dunnett computes the p-values and intervals from the multivariate t distribution by quasi-Monte Carlo integration (fixed seed).')
        c.append(f'from scipy import stats; s = {{k: g[{J(y)}].to_numpy() for k, g in d.groupby({J(x)}, observed=True)}}; ctrl = s.pop({J(control) if control is not None else "list(s)[0]"})')
        c.append(f'r = stats.dunnett(*s.values(), control=ctrl); print(r.pvalue, r.confidence_interval({1 - alpha!r}))')
    else:
        return {'error': f'unknown comparison {method!r}'}
    out['code'] = '\n'.join(c)
    return out


def _scores(y, kind):
    """Linear rank scores of the pooled values: Wilcoxon (ranks), Median
    (1 above the median, averaged over ties) or van der Waerden (normal
    quantiles of the mid-ranks)."""
    N = len(y)
    r = stats.rankdata(y, method='average')
    if kind == 'wilcoxon':
        return r
    if kind == 'median':
        a = (r > (N + 1) / 2).astype(float)
        # tied values share the average of their scores
        s = pd.Series(a).groupby(y).transform('mean').to_numpy()
        return s
    return stats.norm.ppf(r / (N + 1))


@api('fitybyx.oneway_nonpar')
def oneway_nonpar(table, y, x, test='wilcoxon', rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Nonparametric ▸ Wilcoxon / Kruskal-Wallis, Median and van der
    Waerden tests as linear rank tests (the form SAS and JMP use): each
    level's score sum against its expectation, the one-way chi-square
    (N-1) sum n_i (mean_i - mean)^2 / sum (a - mean)^2 on k-1 df, and for
    two levels the normal approximation (with a continuity correction for
    the Wilcoxon test)."""
    G = _OW(table, y, x, rows, weight, freq)
    if G.k < 2:
        return {'error': 'a rank test needs two levels of X'}
    yv, code, _ = G.expanded()
    N = len(yv)
    a = _scores(yv, test)
    abar = float(a.mean())
    ss = float(np.sum((a - abar) ** 2))
    s2 = ss / (N - 1)
    lv = []
    for i in range(G.k):
        ai = a[code == i]
        ni = len(ai)
        S = float(ai.sum())
        E = ni * abar
        V = ni * (N - ni) * s2 / N
        lv.append({'index': i, 'count': ni, 'score_sum': S, 'expected': E, 'score_mean': S / ni if ni else None,
                   'std0': (S - E) / math.sqrt(V) if V > 0 else None})
    chi = float((N - 1) * sum(l['count'] * (l['score_mean'] - abar) ** 2 for l in lv if l['count']) / ss) if ss > 0 else None
    dfree = G.k - 1
    out = {'test': test, 'levels': lv, 'chisq': chi, 'df': dfree, 'p': float(stats.chi2.sf(chi, dfree)) if chi is not None else None,
           'notes': ['Weight is not used by the rank tests.'] if weight else []}
    if G.k == 2:
        small = 0 if lv[0]['count'] <= lv[1]['count'] else 1
        l0 = lv[small]
        V = l0['count'] * (N - l0['count']) * s2 / N
        dev = l0['score_sum'] - l0['expected']
        if test == 'wilcoxon' and dev != 0:
            dev = dev - 0.5 * np.sign(dev)
        z = dev / math.sqrt(V) if V > 0 else None
        out['two_sample'] = {'S': l0['score_sum'], 'level': small, 'Z': z, 'p': float(2 * stats.norm.sf(abs(z))) if z is not None else None,
                             'p_greater': float(stats.norm.sf(z)) if z is not None else None, 'p_less': float(stats.norm.cdf(z)) if z is not None else None}
    c = _ow_code(G, table_name, where, ['from scipy import stats'])
    c.append(f'groups = [g[{J(y)}].to_numpy() for _, g in d.groupby({J(x)}, observed=True)]')
    if test == 'wilcoxon':
        c.append('print(stats.kruskal(*groups))   # the ChiSquare approximation (ties corrected)')
        if G.k == 2:
            c.append('print(stats.mannwhitneyu(groups[0], groups[1], use_continuity=True, method="asymptotic"))   # the 2-sample normal approximation')
    elif test == 'median':
        c.append('stat, p, med, tab = stats.median_test(*groups, correction=False)')
        c.append(f'print(stat * ({N} - 1) / {N}, p)   # scipy\'s Pearson chi-square times (N-1)/N is the linear rank form')
    else:
        c.append(f'a = stats.norm.ppf(stats.rankdata(d[{J(y)}]) / (len(d) + 1)); m = pd.Series(a).groupby(d[{J(x)}].to_numpy()).agg(["count", "mean"])')
        c.append('print((len(a) - 1) * (m["count"] * (m["mean"] - a.mean())**2).sum() / ((a - a.mean())**2).sum())   # van der Waerden chi-square')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.oneway_ks')
def oneway_ks(table, y, x, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Kolmogorov-Smirnov Two-Sample Test (scipy.stats.ks_2samp): D =
    max |F1 - F2| and the one-sided D+ = max(F1 - F2), D- = max(F2 - F1),
    with JMP's KS = D sqrt(n1 n2)/n and KSa = KS sqrt(n)."""
    G = _OW(table, y, x, rows, weight, freq)
    if G.k != 2:
        return {'error': 'the Kolmogorov-Smirnov test needs exactly two levels of X'}
    a, b = G.samples()
    n1, n2 = len(a), len(b)
    two = stats.ks_2samp(a, b)
    gr = stats.ks_2samp(a, b, alternative='greater')
    ls = stats.ks_2samp(a, b, alternative='less')
    n = n1 + n2
    D = float(two.statistic)
    KS = D * math.sqrt(n1 * n2) / n
    grid = np.sort(np.concatenate([a, b]))
    F1 = np.searchsorted(np.sort(a), grid, side='right') / n1
    F2 = np.searchsorted(np.sort(b), grid, side='right') / n2
    Fp = (n1 * F1 + n2 * F2) / n
    j = int(np.argmax(np.abs(F1 - F2)))
    out = {'n1': n1, 'n2': n2, 'D': D, 'p': float(two.pvalue), 'D_plus': float(gr.statistic), 'p_plus': float(gr.pvalue), 'D_minus': float(ls.statistic),
           'p_minus': float(ls.pvalue), 'KS': KS, 'KSa': KS * math.sqrt(n),
           'levels': [{'index': 0, 'count': n1, 'edf': float(F1[j]), 'dev': float(F1[j] - Fp[j])}, {'index': 1, 'count': n2, 'edf': float(F2[j]), 'dev': float(F2[j] - Fp[j])}],
           'method': getattr(two, 'method', None), 'notes': ['Weight is not used here.'] if weight else []}
    c = _ow_code(G, table_name, where, ['from scipy import stats'])
    c.append(f'a, b = [g[{J(y)}].to_numpy() for _, g in d.groupby({J(x)}, observed=True)]')
    c.append('print(stats.ks_2samp(a, b), stats.ks_2samp(a, b, alternative="greater"), stats.ks_2samp(a, b, alternative="less"))')
    out['code'] = '\n'.join(c)
    return out


def _pair_z(a, b, continuity):
    """The Wilcoxon statistic of a against b with the two ranked together:
    the difference of mean ranks, its standard error and Z (ties
    corrected)."""
    y = np.concatenate([a, b])
    N = len(y)
    r = stats.rankdata(y, method='average')
    ra, rb = r[:len(a)], r[len(a):]
    s2 = float(np.sum((r - r.mean()) ** 2) / (N - 1))
    S = float(ra.sum())
    E = len(a) * (N + 1) / 2
    V = len(a) * len(b) * s2 / N
    dev = S - E
    if continuity and dev != 0:
        dev -= 0.5 * np.sign(dev)
    z = dev / math.sqrt(V) if V > 0 else 0.0
    return float(ra.mean() - rb.mean()), math.sqrt(s2 * (1 / len(a) + 1 / len(b))), z


def _hodges_lehmann(a, b, alpha):
    """The Hodges-Lehmann estimate of the shift a - b, with the distribution
    free interval from the Mann-Whitney distribution's normal
    approximation. None for very large groups."""
    n1, n2 = len(a), len(b)
    if n1 * n2 > 4_000_000:
        return None, None, None
    d = np.sort(np.subtract.outer(a, b).ravel())
    est = float(np.median(d))
    z = stats.norm.ppf(1 - alpha / 2)
    k = int(math.floor(n1 * n2 / 2 - z * math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)))
    if k < 1 or k > len(d):
        return est, None, None
    return est, float(d[k - 1]), float(d[len(d) - k])


@api('fitybyx.oneway_nonpar_mc')
def oneway_nonpar_mc(table, y, x, method='wilcoxon', control=None, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Nonparametric Multiple Comparisons: Wilcoxon Each Pair (no
    adjustment), Steel-Dwass All Pairs (p from the studentized range with
    infinite df), Steel With Control (p from the multivariate normal of the
    comparisons), Dunn All Pairs and Dunn With Control for joint ranks
    (Bonferroni adjusted with statsmodels' multipletests)."""
    from statsmodels.stats.multitest import multipletests
    G = _OW(table, y, x, rows, weight, freq)
    if G.k < 2:
        return {'error': 'needs two levels of X'}
    smp = G.samples()
    k = G.k
    ci_ = G.levels.index(control) if control in G.levels else 0
    pairs = []
    notes = ['Weight is not used by the rank comparisons.'] if weight else []
    c = _ow_code(G, table_name, where, ['from scipy import stats'])
    c.append(f'groups = {{lv: g[{J(y)}].to_numpy() for lv, g in d.groupby({J(x)}, observed=True)}}')
    if method in ('wilcoxon', 'steel_dwass', 'steel_control'):
        if method == 'steel_control':
            idx = [(i, ci_) for i in range(k) if i != ci_]
        else:
            idx = [(i, j) for i in range(k) for j in range(i + 1, k)]
        zs = []
        for i, j in idx:
            md, se, z = _pair_z(smp[i], smp[j], continuity=(method == 'wilcoxon'))
            hl, lo, hi = _hodges_lehmann(smp[i], smp[j], alpha)
            pairs.append({'i': i, 'j': j, 'diff': md, 'se': se, 'z': z, 'hl': hl, 'lower': lo, 'upper': hi})
            zs.append(z)
        zs = np.abs(np.array(zs))
        if method == 'wilcoxon':
            ps = 2 * stats.norm.sf(zs)
            c.append('a, b = list(groups.values())[:2]; print(stats.mannwhitneyu(a, b, use_continuity=True, method="asymptotic"))   # one pair; repeat for each')
        elif method == 'steel_dwass':
            ps = stats.studentized_range.sf(zs * math.sqrt(2), k, np.inf)
            notes.append('Steel-Dwass: each pair ranked on its own, Z without a continuity correction, p = P(Q > √2|Z|) for the studentized range of k levels with infinite degrees of freedom.')
            c.append(f'# each pair: z from the ranks of the two groups; p = stats.studentized_range.sf(np.sqrt(2) * abs(z), {k}, np.inf)')
        else:
            ns = np.array([len(s) for s in smp], float)
            oth = [i for i in range(k) if i != ci_]
            lam = np.sqrt(ns[oth] / (ns[oth] + ns[ci_]))
            R = np.outer(lam, lam)
            np.fill_diagonal(R, 1.0)
            mvn = stats.multivariate_normal(cov=R)
            ps = np.array([1 - mvn.cdf(np.full(len(oth), z), lower_limit=np.full(len(oth), -z), rng=np.random.default_rng(SEED)) for z in zs])
            ps = np.clip(ps, 0, 1)
            notes.append('Steel with control: each level ranked with the control, p from the multivariate normal of the comparisons (correlations √(n_i n_j/((n_i+n_0)(n_j+n_0)))), scipy\'s quasi-Monte Carlo integration.')
        for p_, pv in zip(pairs, ps):
            p_['p'] = float(pv)
    elif method in ('dunn_all', 'dunn_control'):
        yv, code, _ = G.expanded()
        N = len(yv)
        r = stats.rankdata(yv, method='average')
        _, tc = np.unique(yv, return_counts=True)
        s2 = N * (N + 1) / 12 - float(np.sum(tc ** 3 - tc)) / (12 * (N - 1))
        rbar = np.array([r[code == i].mean() for i in range(k)])
        ns = np.array([np.sum(code == i) for i in range(k)], float)
        idx = [(i, ci_) for i in range(k) if i != ci_] if method == 'dunn_control' else [(i, j) for i in range(k) for j in range(i + 1, k)]
        raw = []
        for i, j in idx:
            se = math.sqrt(s2 * (1 / ns[i] + 1 / ns[j]))
            z = (rbar[i] - rbar[j]) / se
            pairs.append({'i': i, 'j': j, 'diff': float(rbar[i] - rbar[j]), 'se': se, 'z': float(z)})
            raw.append(2 * stats.norm.sf(abs(z)))
        adj = multipletests(raw, method='bonferroni')[1] if raw else []
        for p_, pv, pr in zip(pairs, adj, raw):
            p_['p'] = float(pv)
            p_['p_raw'] = float(pr)
        notes.append('Dunn\'s test: the levels\' mean ranks in the joint ranking; the p-values are Bonferroni adjusted (statsmodels multipletests) over the comparisons shown.')
        c.append(f'r = stats.rankdata(d[{J(y)}]); rb = pd.Series(r).groupby(d[{J(x)}].to_numpy()).agg(["mean", "count"])')
        c.append('# z = (rb_i - rb_j) / sqrt(s2 (1/n_i + 1/n_j)), s2 = N(N+1)/12 - sum(t^3-t)/(12(N-1)); from statsmodels.stats.multitest import multipletests')
    else:
        return {'error': f'unknown method {method!r}'}
    out = {'method': method, 'pairs': pairs, 'k': k, 'control': ci_, 'alpha': alpha, 'notes': notes}
    if method == 'steel_dwass':
        out['quantile'] = float(stats.studentized_range.ppf(1 - alpha, k, np.inf) / math.sqrt(2))
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.oneway_unequal_var')
def oneway_unequal_var(table, y, x, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Unequal Variances: O'Brien[.5], Brown-Forsythe, Levene and Bartlett
    (scipy), the two-sided F test for two levels, and Welch's ANOVA
    (statsmodels anova_oneway, use_var='unequal')."""
    from statsmodels.stats.oneway import anova_oneway
    G = _OW(table, y, x, rows, weight, freq)
    if G.k < 2:
        return {'error': 'needs two levels of X'}
    smp = G.samples()
    if any(len(s) < 2 for s in smp):
        return {'error': 'every level needs two values'}
    lv = []
    for i, s in enumerate(smp):
        lv.append({'index': i, 'count': len(s), 'sd': float(np.std(s, ddof=1)), 'mad_mean': float(np.mean(np.abs(s - s.mean()))),
                   'mad_median': float(np.mean(np.abs(s - np.median(s))))})
    N = sum(len(s) for s in smp)
    k = G.k
    tests = []
    ob = stats.f_oneway(*stats.obrientransform(*smp)) if all(len(s) > 2 for s in smp) else None
    if ob is not None:
        tests.append({'test': 'O\'Brien[.5]', 'f': float(ob.statistic), 'dfn': k - 1, 'dfd': N - k, 'p': float(ob.pvalue)})
    bf = stats.levene(*smp, center='median')
    tests.append({'test': 'Brown-Forsythe', 'f': float(bf.statistic), 'dfn': k - 1, 'dfd': N - k, 'p': float(bf.pvalue)})
    le = stats.levene(*smp, center='mean')
    tests.append({'test': 'Levene', 'f': float(le.statistic), 'dfn': k - 1, 'dfd': N - k, 'p': float(le.pvalue)})
    ba = stats.bartlett(*smp)
    tests.append({'test': 'Bartlett', 'f': float(ba.statistic) / (k - 1), 'dfn': k - 1, 'dfd': None, 'p': float(ba.pvalue)})
    if k == 2:
        v = [np.var(s, ddof=1) for s in smp]
        big = int(np.argmax(v))
        F = v[big] / v[1 - big]
        dn, dd = len(smp[big]) - 1, len(smp[1 - big]) - 1
        tests.append({'test': 'F Test 2-sided', 'f': float(F), 'dfn': dn, 'dfd': dd, 'p': float(min(1.0, 2 * stats.f.sf(F, dn, dd)))})
    ye, ce, _ = G.expanded()
    wr = anova_oneway(ye, ce, use_var='unequal')
    welch = {'f': float(wr.statistic), 'dfn': float(wr.df_num), 'dfd': float(wr.df_denom), 'p': float(wr.pvalue)}
    if k == 2:
        welch['t'] = math.sqrt(welch['f'])
    out = {'levels': lv, 'tests': tests, 'welch': welch, 'notes': (['Weight is not used by these tests.'] if weight else []) +
           ['Bartlett\'s χ² is shown as F = χ²/(k−1) on (k−1, ∞) degrees of freedom, as JMP shows it; the p-value is the χ² test\'s.']}
    c = _ow_code(G, table_name, where, ['from scipy import stats', 'from statsmodels.stats.oneway import anova_oneway'])
    c.append(f'groups = [g[{J(y)}].to_numpy() for _, g in d.groupby({J(x)}, observed=True)]')
    c.append('print(stats.f_oneway(*stats.obrientransform(*groups)))   # O\'Brien[.5]')
    c.append('print(stats.levene(*groups, center="median"), stats.levene(*groups, center="mean"), stats.bartlett(*groups))   # Brown-Forsythe, Levene, Bartlett')
    c.append(f'print(anova_oneway(d[{J(y)}], d[{J(x)}], use_var="unequal"))   # Welch\'s ANOVA')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.oneway_equivalence')
def oneway_equivalence(table, y, x, delta=1.0, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Equivalence Test ▸ Means: for every pair, two one-sided t tests that
    the difference lies within ±delta (statsmodels ttost_ind, the pair's
    pooled variance)."""
    from statsmodels.stats.weightstats import ttost_ind
    G = _OW(table, y, x, rows, weight, freq)
    if G.k < 2:
        return {'error': 'needs two levels of X'}
    if not delta or delta <= 0:
        return {'error': 'the difference considered practically zero must be positive'}
    smp = G.samples()
    rows_out = []
    for i in range(G.k):
        for j in range(i + 1, G.k):
            a, b = smp[j], smp[i]
            if len(a) < 2 or len(b) < 2:
                continue
            p, lower, upper = ttost_ind(a, b, -delta, delta, usevar='pooled')
            dfree = len(a) + len(b) - 2
            sp = math.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / dfree)
            se = sp * math.sqrt(1 / len(a) + 1 / len(b))
            diff = float(a.mean() - b.mean())
            t = stats.t.ppf(1 - alpha, dfree)
            rows_out.append({'i': j, 'j': i, 'diff': diff, 'se': se, 't_lower': float(lower[0]), 'p_lower': float(lower[1]), 't_upper': float(upper[0]),
                             'p_upper': float(upper[1]), 'p': float(p), 'df': float(dfree), 'lower': diff - t * se, 'upper': diff + t * se})
    out = {'delta': delta, 'alpha': alpha, 'pairs': rows_out,
           'notes': ['Each pair uses its own pooled variance (statsmodels ttost_ind); with more than two levels JMP pools the error of all levels.'] + (['Weight is not used here.'] if weight else [])}
    c = _ow_code(G, table_name, where, ['from statsmodels.stats.weightstats import ttost_ind'])
    c.append(f'g = [s[{J(y)}].to_numpy() for _, s in d.groupby({J(x)}, observed=True)]')
    c.append(f'print(ttost_ind(g[1], g[0], {-delta!r}, {delta!r}, usevar="pooled"))   # p, (t, p, df) lower, (t, p, df) upper')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.oneway_power')
def oneway_power(table, y, x, alpha=0.05, sigma=None, delta=None, nobs=None, rows=None, weight=None, freq=None, where=None, table_name='data'):
    """Power: the power of the one-way F test (statsmodels
    FTestAnovaPower, effect size f = delta/sigma, noncentrality N f²) for
    the given alpha, sigma (default: the RMSE), delta (default: the
    standard deviation of the level effects, sqrt(sum n_i (mean_i -
    mean)^2 / N)) and numbers of observations; the least significant
    number and value."""
    from statsmodels.stats.power import FTestAnovaPower
    from scipy.optimize import brentq
    G = _OW(table, y, x, rows, weight, freq)
    if G.k < 2:
        return {'error': 'needs two levels of X'}
    cm = G.cell_means()
    means = np.asarray(cm.params, float)
    n = np.array([G.f[G.code == i].sum() for i in range(G.k)])
    N = float(n.sum())
    gm = float(np.sum(n * means) / N)
    if sigma is None:
        sigma = float(np.sqrt(cm.mse_resid))
    if delta is None:
        delta = float(np.sqrt(np.sum(n * (means - gm) ** 2) / N))
    k = G.k
    nlist = [float(v) for v in (nobs if nobs else [N])]
    alist = [float(a) for a in (alpha if isinstance(alpha, (list, tuple)) else [alpha])]
    pw = FTestAnovaPower()
    rows_out = []
    for a in alist:
        for nn in nlist:
            if nn <= k:
                continue
            p = float(pw.power(effect_size=delta / sigma, nobs=nn, alpha=a, k_groups=k)) if sigma > 0 else None
            rows_out.append({'alpha': a, 'sigma': sigma, 'delta': delta, 'n': nn, 'power': p})
    # least significant number: the N at which F = N delta^2/((k-1) sigma^2) reaches its critical value
    a0 = alist[0]
    lsn = None
    if delta > 0 and sigma > 0:
        fn = lambda nn: nn * delta ** 2 / ((k - 1) * sigma ** 2) - stats.f.ppf(1 - a0, k - 1, nn - k)
        try:
            lsn = float(brentq(fn, k + 1e-6, 1e9))
        except ValueError:
            lsn = None
    lsv = float(math.sqrt(stats.f.ppf(1 - a0, k - 1, N - k) * (k - 1) * sigma ** 2 / N)) if N > k else None
    n80 = None
    try:
        n80 = float(pw.solve_power(effect_size=delta / sigma, nobs=None, alpha=a0, power=0.8, k_groups=k)) if delta > 0 and sigma > 0 else None
    except Exception:
        n80 = None
    out = {'rows': rows_out, 'k': k, 'lsn': lsn, 'lsv': lsv, 'n80': n80, 'sigma': sigma, 'delta': delta, 'n': N}
    c = _ow_code(G, table_name, where, ['from statsmodels.stats.power import FTestAnovaPower'])
    c.append(f'print(FTestAnovaPower().power(effect_size={delta!r} / {sigma!r}, nobs={nlist[0]!r}, alpha={a0!r}, k_groups={k}))')
    out['code'] = '\n'.join(c)
    return out


def _anom_h(n, alpha, df=None):
    """The exact ANOM critical value: P(max_i |T_i| <= h) = 1 - alpha for
    the multivariate t (df None: normal) of (mean_i - mean)/(s sqrt((N -
    n_i)/(N n_i))), whose correlations are -sqrt(n_i n_j/((N - n_i)(N -
    n_j))). scipy's quasi-Monte Carlo integral does not take the singular
    matrix, so it gets the matrix plus 1e-8 on the diagonal."""
    from scipy.optimize import brentq
    n = np.asarray(n, float)
    N = n.sum()
    k = len(n)
    lam = np.sqrt(n / (N - n))
    R = -np.outer(lam, lam)
    np.fill_diagonal(R, 1.0)
    R = R + 1e-8 * np.eye(k)
    d = np.sqrt(np.diag(R))
    R = R / np.outer(d, d)
    if df is None:
        f = lambda h: stats.multivariate_normal.cdf(np.full(k, h), cov=R, maxpts=40000 * k, lower_limit=np.full(k, -h), rng=np.random.default_rng(SEED)) - (1 - alpha)
        lo, hi = stats.norm.ppf(1 - alpha / 2) * 0.9, stats.norm.ppf(1 - alpha / (2 * k)) * 1.1
    else:
        mv = stats.multivariate_t(shape=R, df=df)
        f = lambda h: mv.cdf(np.full(k, h), lower_limit=np.full(k, -h), maxpts=40000, random_state=np.random.default_rng(SEED)) - (1 - alpha)
        lo, hi = stats.t.ppf(1 - alpha / 2, df) * 0.9, stats.t.ppf(1 - alpha / (2 * k), df) * 1.1
    return float(brentq(f, lo, hi, xtol=1e-5))


@api('fitybyx.oneway_anom')
def oneway_anom(table, y, x, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Analysis of Means: each level's mean against decision limits around
    the grand mean, mean ± h s sqrt((N - n_i)/(N n_i)), with the exact
    critical value h (see _anom_h)."""
    G = _OW(table, y, x, rows, weight, freq)
    if G.k < 2:
        return {'error': 'needs two levels of X'}
    smp = G.samples()
    n = np.array([len(s) for s in smp], float)
    N = n.sum()
    dfe = N - G.k
    if dfe <= 0:
        return {'error': 'no degrees of freedom for error'}
    means = np.array([s.mean() for s in smp])
    gm = float(np.sum(n * means) / N)
    s = math.sqrt(sum(np.sum((v - v.mean()) ** 2) for v in smp) / dfe)
    h = _anom_h(n, alpha, dfe)
    lv = []
    for i in range(G.k):
        half = h * s * math.sqrt((N - n[i]) / (N * n[i]))
        lv.append({'index': i, 'n': float(n[i]), 'mean': float(means[i]), 'ldl': gm - half, 'udl': gm + half, 'out': bool(abs(means[i] - gm) > half)})
    out = {'levels': lv, 'grand_mean': gm, 'h': h, 's': s, 'df': dfe, 'alpha': alpha, 'notes': ['Weight is not used here.'] if weight else []}
    c = _ow_code(G, table_name, where, ['from scipy import stats'])
    c.append(f'g = d.groupby({J(x)}, observed=True)[{J(y)}]; n, m = g.count().to_numpy(), g.mean().to_numpy(); N, k = n.sum(), len(n)')
    c.append('s = np.sqrt(g.var().to_numpy().dot(n - 1) / (N - k)); lam = np.sqrt(n / (N - n)); R = -np.outer(lam, lam); np.fill_diagonal(R, 1 + 1e-8)')
    c.append(f'mv = stats.multivariate_t(shape=R / (1 + 1e-8), df=N - k)   # then solve mv.cdf(h*ones, lower_limit=-h*ones) = {1 - alpha} for h')
    c.append(f'h = {h!r}; print(m.dot(n) / N - h * s * np.sqrt((N - n) / (N * n)), m.dot(n) / N + h * s * np.sqrt((N - n) / (N * n)))   # decision limits')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.oneway_densities')
def oneway_densities(table, y, x, rows=None, weight=None, freq=None, grid=160, alpha=0.05, where=None, table_name='data'):
    """Densities: a Gaussian kernel density of Y in each level (scipy
    gaussian_kde, Scott's bandwidth) on a common grid, and the levels'
    shares of the rows."""
    G = _OW(table, y, x, rows, weight, freq)
    lo, hi = float(G.y.min()), float(G.y.max())
    pad = 0.1 * (hi - lo if hi > lo else 1)
    g = np.linspace(lo - pad, hi + pad, grid)
    dens = []
    for i in range(G.k):
        yi, fi = G.y[G.code == i], G.f[G.code == i]
        share = float(fi.sum() / G.N)
        if len(np.unique(yi)) < 2:
            dens.append({'index': i, 'share': share, 'density': None})
            continue
        kd = stats.gaussian_kde(yi, weights=fi)
        dens.append({'index': i, 'share': share, 'density': kd(g)})
    out = {'x': g, 'levels': dens}
    c = _ow_code(G, table_name, where, ['from scipy import stats'])
    c.append(f'for lv, s in d.groupby({J(x)}, observed=True)[{J(y)}]: print(lv, stats.gaussian_kde(s.to_numpy())(np.linspace(s.min(), s.max(), 5)))')
    out['code'] = '\n'.join(c)
    return out


def _repeat_code(freq, frame='d'):
    """The line that counts Freq by repeating rows, for the code shown."""
    return f'{frame} = {frame}.loc[{frame}.index.repeat({frame}[{J(freq)}].round().astype(int))]   # Freq: each row counted that many times'


@api('fitybyx.oneway_brunner')
def oneway_brunner(table, y, x, rows=None, weight=None, freq=None, alpha=0.05, tost=None, where=None, table_name='data'):
    """Nonparametric ▸ Brunner-Munzel: for each pair of levels (a later
    level against an earlier one) the probability of superiority p =
    P(Y_a > Y_b) + P(Y_a = Y_b)/2 from the ranks, its confidence interval
    and the Brunner-Munzel test of p = 1/2, which does not assume that the
    two distributions are the same under the null (statsmodels
    rank_compare_2indep, t with Welch-Satterthwaite type degrees of
    freedom). With tost = {low, upp}: the equivalence test low < p < upp
    (tost_prob_superior), two one-sided tests."""
    from statsmodels.stats.multitest import multipletests
    from statsmodels.stats.nonparametric import rank_compare_2indep
    G = _OW(table, y, x, rows, weight, freq)
    if G.k < 2:
        return {'error': 'the Brunner-Munzel test needs two levels of X'}
    smp = G.samples()
    low = upp = None
    if tost:
        low, upp = float(tost.get('low')), float(tost.get('upp'))
        if not (0 <= low < upp <= 1):
            return {'error': 'the equivalence bounds must satisfy 0 ≤ lower < upper ≤ 1'}
    notes = []
    pairs, eq = [], []
    for i in range(G.k):
        for j in range(i + 1, G.k):
            a, b = smp[j], smp[i]
            if len(a) < 2 or len(b) < 2:
                notes.append(f'{_lvtext(G.levels[j])} and {_lvtext(G.levels[i])}: each level needs two values.')
                continue
            # a zero variance (the levels do not overlap, or every value is
            # the same) makes the statistic infinite: reported below
            with np.errstate(divide='ignore', invalid='ignore'):
                r = rank_compare_2indep(a, b, use_t=True)
            row = {'i': j, 'j': i, 'n1': len(a), 'n2': len(b), 'prob': float(r.prob1), 'somersd': float(r.somersd1)}
            if not r.var > 0:
                row.update({'se': 0.0, 'lower': None, 'upper': None, 'stat': None, 'df': None, 'p': None, 'p_greater': None, 'p_less': None})
                notes.append(f'{_lvtext(G.levels[j])} against {_lvtext(G.levels[i])}: the rank variance is zero (the levels do not overlap, or every value is the same), so there is no Brunner-Munzel test or interval.')
                pairs.append(row)
                continue
            lo, hi = r.conf_int(alpha=alpha)
            dlo, dhi = r.confint_lintransf(const=-1, slope=2, alpha=alpha)
            row.update({'se': float(math.sqrt(r.var_prob)), 'lower': float(lo), 'upper': float(hi), 'stat': float(r.statistic), 'df': float(r.df),
                        'p': float(r.pvalue), 'p_greater': float(r.test_prob_superior(0.5, alternative='larger').pvalue),
                        'p_less': float(r.test_prob_superior(0.5, alternative='smaller').pvalue), 'd_lower': float(dlo), 'd_upper': float(dhi)})
            pairs.append(row)
            if tost:
                tt = r.tost_prob_superior(low, upp)
                lo2, hi2 = r.conf_int(alpha=2 * alpha)
                eq.append({'i': j, 'j': i, 'prob': float(r.prob1), 'lower': float(lo2), 'upper': float(hi2),
                           't_lower': float(tt.results_larger.statistic), 'p_lower': float(tt.results_larger.pvalue),
                           't_upper': float(tt.results_smaller.statistic), 'p_upper': float(tt.results_smaller.pvalue), 'p': float(tt.pvalue), 'df': float(r.df)})
    ps = [p_['p'] for p_ in pairs if p_['p'] is not None]
    if len(ps) > 1:
        adj = iter(multipletests(ps, method='holm')[1])
        for p_ in pairs:
            if p_['p'] is not None:
                p_['p_holm'] = float(next(adj))
    if weight:
        notes.append('Weight is not used by the rank statistics; Freq is counted by repeating rows.')
    out = {'pairs': pairs, 'alpha': alpha, 'k': G.k, 'levels': G.levels, 'notes': notes}
    if tost:
        out['tost'] = {'low': low, 'upp': upp, 'pairs': eq}
    c = _ow_code(G, table_name, where, ['from statsmodels.stats.nonparametric import rank_compare_2indep'])
    if freq:
        c.append(_repeat_code(freq))
    c.append(f'g = {{lv: s.to_numpy() for lv, s in d.groupby({J(x)}, observed=True)[{J(y)}]}}')
    if pairs:
        a_, b_ = G.levels[pairs[0]['i']], G.levels[pairs[0]['j']]
        c.append(f'r = rank_compare_2indep(g[{_lvcode(a_)}], g[{_lvcode(b_)}])   # P({_lvtext(a_)} > {_lvtext(b_)}) + P(=)/2; the same for each pair')
        c.append(f'print(r.prob1, r.conf_int(alpha={alpha!r}), r.statistic, r.df, r.pvalue)   # estimate, interval, Brunner-Munzel t, DF, Prob>|t|')
        if tost:
            c.append(f'print(r.tost_prob_superior({low!r}, {upp!r}))   # the equivalence test: p, then the two one-sided tests')
    out['code'] = '\n'.join(c)
    return out


# Compare Rates: the methods statsmodels has for the test and the interval
RATE_TESTS = {'ratio': ['score', 'wald', 'score-log', 'wald-log', 'sqrt', 'exact-cond', 'cond-midp', 'etest-score', 'etest-wald'],
              'diff': ['score', 'wald', 'waldccv', 'etest-score', 'etest-wald']}
RATE_CIS = {'ratio': ['score', 'score-log', 'wald-log', 'waldcc', 'sqrtcc', 'mover', 'exact-cond'],
            'diff': ['score', 'wald', 'waldccv', 'mover']}
ETEST_MAX_MEAN = 1000.0     # the E-test sums over a grid of counts squared: larger expected counts are too big for the browser


def _counts_check(yv):
    return bool(len(yv)) and bool(np.all(yv >= 0)) and bool(np.all(np.abs(yv - np.rint(yv)) < 1e-9))


def _rate_test(c1, e1, c2, e2, method, ci_method, compare, alpha):
    """One comparison of two Poisson rates, count1/exposure1 against
    count2/exposure2: test_poisson_2indep two-sided and one-sided, and the
    interval confint_poisson_2indep ('exact-cond': the Clopper-Pearson
    interval of the conditional binomial, which statsmodels does not give).
    An interval that inverts a test is checked against that test; with a
    zero count statsmodels' inversion can fail, and the test is inverted
    here instead. Returns the row and notes."""
    from statsmodels.stats.proportion import proportion_confint
    from statsmodels.stats.rates import confint_poisson_2indep, test_poisson_2indep
    notes = []
    row = {'count1': c1, 'exposure1': e1, 'count2': c2, 'exposure2': e2, 'rate1': c1 / e1, 'rate2': c2 / e2,
           'stat': None, 'p': None, 'p_greater': None, 'p_less': None, 'lower': None, 'upper': None}
    r1, r2 = c1 / e1, c2 / e2
    if compare == 'ratio':
        row['estimate'] = r1 / r2 if r2 > 0 else (np.inf if r1 > 0 else None)
    else:
        row['estimate'] = r1 - r2
    if c1 + c2 == 0:
        notes.append('No events in either level: no test or interval.')
        return row, notes
    zero = c1 == 0 or c2 == 0
    m = method
    if compare == 'ratio' and zero and m in ('score-log', 'wald-log'):
        notes.append(f'The {m} test takes the logs of both counts: it is not defined with no events in one level.')
        m = None
    if m and m.startswith('etest'):
        mean = max(c1, c2, (c1 + c2) / 2)
        if mean > ETEST_MAX_MEAN:
            notes.append(f'The E-test sums over every pair of counts up to about {mean:.0f}; above {ETEST_MAX_MEAN:.0f} that grid is too large here. At such counts the score test is accurate.')
            m = None
    if m:
        with np.errstate(divide='ignore', invalid='ignore'):
            t2 = test_poisson_2indep(c1, e1, c2, e2, method=m, compare=compare)
            tg = test_poisson_2indep(c1, e1, c2, e2, method=m, compare=compare, alternative='larger')
            tl = test_poisson_2indep(c1, e1, c2, e2, method=m, compare=compare, alternative='smaller')
        row.update({'stat': _fin(t2.statistic), 'p': _fin(t2.pvalue), 'p_greater': _fin(tg.pvalue), 'p_less': _fin(tl.pvalue)})
    cm = ci_method
    if compare == 'ratio' and zero and cm in ('score-log', 'wald-log'):
        notes.append(f'The {cm} interval takes the logs of both counts: it is not defined with no events in one level.')
        cm = None
    if cm == 'exact-cond':
        pl, pu = proportion_confint(c1, c1 + c2, alpha=alpha, method='beta')
        row['lower'] = pl / (1 - pl) * e2 / e1
        row['upper'] = pu / (1 - pu) * e2 / e1 if pu < 1 else np.inf
    elif cm:
        with np.errstate(divide='ignore', invalid='ignore'):
            try:
                ci = confint_poisson_2indep(c1, e1, c2, e2, method=cm, compare=compare, alpha=alpha)
            except (ValueError, ZeroDivisionError, FloatingPointError):
                ci = (np.nan, np.nan)
        if cm in ('score', 'score-log'):
            pf = lambda v: test_poisson_2indep(c1, e1, c2, e2, value=v, method=cm, compare=compare).pvalue
            est = row['estimate'] if row['estimate'] is not None else None
            if not _ci_checked(ci, pf, alpha, est):
                if compare == 'ratio':
                    center = (c1 + 0.5) / (c2 + 0.5) * e2 / e1
                    ci = _invert_test(pf, alpha, center, log=True)
                else:
                    span = math.sqrt((c1 + 0.5) / e1 ** 2 + (c2 + 0.5) / e2 ** 2)
                    ci = _invert_test(pf, alpha, r1 - r2, span=span)
                notes.append(f'statsmodels\' {cm} interval failed (a zero count); the interval is its test inverted by root finding here.')
        row['lower'], row['upper'] = _fin(ci[0]), _fin(ci[1])
    return row, notes


@api('fitybyx.oneway_rates')
def oneway_rates(table, y, x, exposure=None, compare='ratio', method='score', ci_method='score', control=None, rows=None,
                 weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Compare Rates: Y counts events, each row a unit observed for its
    Exposure (1 without one). Each level's rate is its total count over its
    total exposure, with the exact (Garwood) interval (confint_poisson).
    Each pair of levels, or each level against a control, is compared by
    the ratio or the difference of the rates (statsmodels
    test_poisson_2indep, confint_poisson_2indep), and all levels together
    by the likelihood-ratio test of a Poisson GLM with the log exposure as
    offset."""
    import statsmodels.api as sm
    from statsmodels.stats.multitest import multipletests
    from statsmodels.stats.rates import confint_poisson
    if compare not in RATE_TESTS:
        return {'error': f'unknown comparison {compare!r}'}
    if method not in RATE_TESTS[compare]:
        return {'error': f'the {method} test is not one statsmodels has for a rate {compare}'}
    if ci_method not in RATE_CIS[compare]:
        return {'error': f'the {ci_method} interval is not one statsmodels has for a rate {compare}'}
    if exposure and exposure in (y, x):
        return {'error': 'the exposure must be a column other than Y and X'}
    df = data.frame(table, [y, x, exposure, weight, freq], rows)
    df, w, f = _wf(df, table, weight, freq)
    yv = df[y].to_numpy(float)
    ev = df[exposure].to_numpy(float) if exposure else np.ones(len(df))
    ok = np.isfinite(yv) & np.isfinite(ev) & (ev > 0)
    notes = []
    if exposure and (~ok).sum():
        notes.append(f'{int((~ok).sum())} row(s) with an exposure that is not positive are left out.')
    df, yv, ev, f = df[ok], yv[ok], ev[ok], f[ok]
    if not _counts_check(yv):
        return {'error': 'Compare Rates needs counts in Y: whole numbers of zero or more'}
    try:
        reps = _reps(f) if freq else None
    except ValueError as e:
        return {'error': str(e)}
    fr = reps.astype(float) if reps is not None else np.ones(len(yv))
    xs = df[x]
    if not isinstance(xs.dtype, pd.CategoricalDtype):
        xs = pd.Series(pd.Categorical(xs), index=df.index)
    xs = xs.cat.remove_unused_categories()
    levels = list(xs.cat.categories)
    code = xs.cat.codes.to_numpy().astype(int)
    k = len(levels)
    if k < 2:
        return {'error': 'Compare Rates needs two levels of X'}
    C = np.bincount(code, weights=fr * yv, minlength=k)
    E = np.bincount(code, weights=fr * ev, minlength=k)
    Nu = np.bincount(code, weights=fr, minlength=k)
    lv_rows = []
    for i in range(k):
        lo, hi = confint_poisson(C[i], E[i], method='exact-c', alpha=alpha)
        lv_rows.append({'index': i, 'level': levels[i], 'n': float(Nu[i]), 'count': float(C[i]), 'exposure': float(E[i]), 'rate': float(C[i] / E[i]),
                        'lower': float(lo), 'upper': float(hi)})
    ci_ = None
    if control is not None:
        for i, lv in enumerate(levels):
            if _lvtext(lv) == _lvtext(control):
                ci_ = i
    idx = [(i, ci_) for i in range(k) if i != ci_] if ci_ is not None else [(j, i) for i in range(k) for j in range(i + 1, k)]
    pairs = []
    seen = set()
    for a, b in idx:
        row, nts = _rate_test(float(C[a]), float(E[a]), float(C[b]), float(E[b]), method, ci_method, compare, alpha)
        row.update({'i': a, 'j': b})
        pairs.append(row)
        for t in nts:
            key = t
            if key not in seen:
                seen.add(key)
                notes.append(f'{_lvtext(levels[a])} against {_lvtext(levels[b])}: {t}' if len(idx) > 1 else t)
    ps = [p_['p'] for p_ in pairs if p_['p'] is not None]
    if len(ps) > 1:
        adj = iter(multipletests(ps, method='holm')[1])
        for p_ in pairs:
            if p_['p'] is not None:
                p_['p_holm'] = float(next(adj))
    # every level together: the Poisson GLM of the rows, log exposure as offset
    X = np.zeros((len(yv), k))
    X[np.arange(len(yv)), code] = 1.0
    lr = None
    if C.sum() > 0:
        if np.all(C > 0):
            full = sm.GLM(yv, X, family=sm.families.Poisson(), exposure=ev, freq_weights=fr).fit()
            null = sm.GLM(yv, np.ones((len(yv), 1)), family=sm.families.Poisson(), exposure=ev, freq_weights=fr).fit()
            stat = float(2 * (full.llf - null.llf))
            disp = float(full.pearson_chi2 / full.df_resid) if full.df_resid > 0 else None
            lr = {'chisq': max(stat, 0.0), 'df': k - 1, 'p': float(stats.chi2.sf(max(stat, 0.0), k - 1)), 'dispersion': disp, 'df_resid': float(full.df_resid), 'source': 'glm'}
        else:
            # a level without events: the GLM's estimate for it is minus
            # infinity; the likelihood ratio is its limit, from the totals
            rbar = C.sum() / E.sum()
            with np.errstate(divide='ignore', invalid='ignore'):
                terms = np.where(C > 0, C * np.log(C / (E * rbar)), 0.0)
            stat = float(2 * terms.sum())
            mu = ev * (C / E)[code]
            dfr = float(fr.sum() - k)
            with np.errstate(divide='ignore', invalid='ignore'):
                pear = float(np.sum(np.where(mu > 0, fr * (yv - mu) ** 2 / mu, 0.0)))
            lr = {'chisq': stat, 'df': k - 1, 'p': float(stats.chi2.sf(stat, k - 1)), 'dispersion': pear / dfr if dfr > 0 else None, 'df_resid': dfr, 'source': 'totals'}
            notes.append('A level has no events: its GLM estimate would be minus infinity, so the likelihood ratio is computed from the totals, its limit.')
    if lr and lr['dispersion'] is not None and lr['dispersion'] > 1.5:
        notes.append(f'The Pearson χ²/DF of the Poisson model is {lr["dispersion"]:.3g}: the counts vary more than a Poisson allows, and these tests treat the evidence as stronger than it is. A negative binomial model (Count Regression) allows for it.')
    if weight:
        notes.append('Weight is not used; Freq is counted as that many units.')
    out = {'levels': lv_rows, 'pairs': pairs, 'lr': lr, 'compare': compare, 'method': method, 'ci_method': ci_method, 'control': ci_, 'k': k,
           'alpha': alpha, 'exposure': exposure, 'level_values': levels, 'notes': notes}
    # the code: totals per level, the pair tests, the GLM
    c = _head(table_name, where, ['from statsmodels.stats.rates import test_poisson_2indep, confint_poisson_2indep'])
    c.append(f'd = df[[{", ".join(J(v) for v in (y, x, exposure, freq) if v)}]].dropna()')
    if exposure:
        c.append(f'd = d[d[{J(exposure)}] > 0]')
    fw = f'd[{J(freq)}]' if freq else '1'
    ex = f'd[{J(exposure)}]' if exposure else '1'
    c.append(f'd = d.assign(_count=d[{J(y)}] * {fw}, _exposure={ex} * {fw})')
    c.append(f't = d.groupby({J(x)}, observed=True)[["_count", "_exposure"]].sum(); print(t.assign(rate=t._count / t._exposure))   # each level\'s total count, exposure and rate')
    if pairs:
        a_, b_ = levels[pairs[0]['i']], levels[pairs[0]['j']]
        c.append(f'c1, e1 = t.loc[{_lvcode(a_)}]; c2, e2 = t.loc[{_lvcode(b_)}]   # {_lvtext(a_)} against {_lvtext(b_)}; the same for each pair')
        c.append(f'print(test_poisson_2indep(c1, e1, c2, e2, method={J(method)}, compare={J(compare)}))')
        if ci_method == 'exact-cond':
            c.append('from statsmodels.stats.proportion import proportion_confint')
            c.append(f'pl, pu = proportion_confint(c1, c1 + c2, alpha={alpha!r}, method="beta"); print(pl / (1 - pl) * e2 / e1, pu / (1 - pu) * e2 / e1)   # exact conditional interval of the ratio')
        else:
            c.append(f'print(confint_poisson_2indep(c1, e1, c2, e2, method={J(ci_method)}, compare={J(compare)}, alpha={alpha!r}))')
    glm_kw = f'family=sm.families.Poisson(){", exposure=d[" + J(exposure) + "]" if exposure else ""}{", freq_weights=d[" + J(freq) + "]" if freq else ""}'
    c.append(f'full = smf.glm({J(_q(y) + " ~ C(" + _q(x) + ")")}, d, {glm_kw}).fit()')
    c.append(f'null = smf.glm({J(_q(y) + " ~ 1")}, d, {glm_kw}).fit()')
    c.append('print(2 * (full.llf - null.llf), full.pearson_chi2 / full.df_resid)   # the likelihood-ratio chi-square (k - 1 DF), the dispersion')
    out['code'] = '\n'.join(c)
    return out


# ---- Logistic -----------------------------------------------------------------

def _expit(v):
    return 1 / (1 + np.exp(-v))


def _logit_frame(table, y, x, rows, weight, freq):
    df = data.frame(table, [y, x, weight, freq], rows)
    df, w, f = _wf(df, table, weight, freq)
    ys = df[y]
    if not isinstance(ys.dtype, pd.CategoricalDtype):
        raise ValueError(f'{y} is not ordinal or nominal')
    xv = df[x].to_numpy(float)
    ok = np.isfinite(xv)
    df, w, f, xv = df[ok], w[ok], f[ok], xv[ok]
    ys = df[y].cat.remove_unused_categories()
    return df, ys, xv, w, f


def _probs(model, xv):
    """The probability of each level at xv from the model description the
    page also gets: binary {coef: [a, b]} for the log odds of the first
    level; nominal {coef: [[a_j, b_j]]} against the last level; ordinal
    {alpha: [a_j], beta} for logit P(Y <= level j) = a_j + beta x."""
    xv = np.asarray(xv, float)
    if model['kind'] == 'binary':
        a, b = model['coef']
        p0 = _expit(a + b * xv)
        return np.column_stack([p0, 1 - p0])
    if model['kind'] == 'nominal':
        eta = np.column_stack([a + b * xv for a, b in model['coef']] + [np.zeros_like(xv)])
        eta -= eta.max(axis=1, keepdims=True)
        e = np.exp(eta)
        return e / e.sum(axis=1, keepdims=True)
    cum = np.column_stack([_expit(a + model['beta'] * xv) for a in model['alpha']] + [np.ones_like(xv)])
    return np.diff(np.column_stack([np.zeros_like(xv), cum]), axis=1)


def _logistic_fit(table, y, x, rows, weight, freq, target):
    """Fit the logistic model JMP would: binary (Logit, or GLM Binomial
    with frequency weights when weighted), nominal (MNLogit, the last level
    the reference) or ordinal (OrderedModel, cumulative logit)."""
    import statsmodels.api as sm
    df, ys, xv, w, f = _logit_frame(table, y, x, rows, weight, freq)
    levels = list(ys.cat.categories)
    k = len(levels)
    if k < 2:
        raise ValueError(f'{y} has one level in these rows')
    code = ys.cat.codes.to_numpy().astype(int)
    wf = w * f
    notes = []
    fit = {'levels': levels, 'k': k, 'code': code, 'x': xv, 'wf': wf, 'rows': df.index.to_numpy(), 'notes': notes, 'N': float(wf.sum())}
    X = sm.add_constant(xv, has_constant='add')
    if k == 2:
        t = 0
        if target is not None:
            for i, lv in enumerate(levels):
                if _lvtext(lv) == _lvtext(target):
                    t = i
        yb = (code == t).astype(float)
        if weight or freq:
            res = sm.GLM(yb, X, family=sm.families.Binomial(), freq_weights=wf).fit()
            llnull = float(res.llnull)
        else:
            res = sm.Logit(yb, X).fit(disp=0)
            llnull = float(res.llnull)
        b = np.asarray(res.params, float)
        cov = np.asarray(res.cov_params(), float)
        fit.update({'kind': 'binary', 'target': t, 'llf': float(res.llf), 'llnull': llnull, 'nparm': 2, 'df': 1,
                    'params': [{'term': 'Intercept', 'estimate': b[0], 'se': math.sqrt(cov[0, 0]), 'group': t}, {'term': x, 'estimate': b[1], 'se': math.sqrt(cov[1, 1]), 'group': t}],
                    'cov': cov, 'coef_target': b})
        s = 1.0 if t == 0 else -1.0
        fit['model'] = {'kind': 'binary', 'coef': [s * b[0], s * b[1]]}
        return fit
    if weight:
        notes.append(f'statsmodels\' {"OrderedModel" if ys.cat.ordered else "MNLogit"} takes no weights: Weight is not used here.')
    reps = _reps(f) if freq else None
    if reps is not None:
        xe, ce = np.repeat(xv, reps), np.repeat(code, reps)
    else:
        xe, ce = xv, code
    if ys.cat.ordered:
        from statsmodels.miscmodels.ordinal_model import OrderedModel
        endog = pd.Series(pd.Categorical.from_codes(ce, categories=list(range(k)), ordered=True))
        mod = OrderedModel(endog, xe[:, None], distr='logit')
        res = mod.fit(method='bfgs', disp=0, maxiter=500)
        p = np.asarray(res.params, float)
        cov = np.asarray(res.cov_params(), float)
        th = mod.transform_threshold_params(p)[1:-1]
        # d theta_j / d (theta_0, u_1, ..., u_j): 1, exp(u_1), ..., exp(u_j)
        Jm = np.zeros((k - 1, k))
        Jm[:, 0] = 0.0
        for j in range(k - 1):
            Jm[j, 1] = 1.0
            for m in range(1, j + 1):
                Jm[j, 1 + m] = math.exp(p[1 + m])
        # the page's parameters: [alpha_1..alpha_{k-1}, beta], beta = -beta_statsmodels
        Jfull = np.zeros((k, k))
        Jfull[:k - 1, :] = Jm
        Jfull[k - 1, 0] = -1.0
        cv = Jfull @ cov @ Jfull.T
        params = [{'term': f'Intercept[{_lvtext(levels[j])}]', 'estimate': float(th[j]), 'se': math.sqrt(cv[j, j]), 'group': None} for j in range(k - 1)]
        params.append({'term': x, 'estimate': float(-p[0]), 'se': math.sqrt(cv[k - 1, k - 1]), 'group': None})
        fit.update({'kind': 'ordinal', 'llf': float(res.llf), 'llnull': float(res.llnull), 'nparm': k, 'df': 1, 'params': params, 'cov': cv,
                    'model': {'kind': 'ordinal', 'alpha': [float(v) for v in th], 'beta': float(-p[0])}})
        return fit
    # nominal: statsmodels' reference is its first category, so the last level goes first
    ce2 = (ce + 1) % k
    res = sm.MNLogit(ce2, sm.add_constant(xe, has_constant='add')).fit(disp=0, maxiter=200)
    P = np.asarray(res.params, float)       # (2, k-1): column m is level m against the last
    cov = np.asarray(res.cov_params(), float)
    params = []
    coef = []
    for m in range(k - 1):
        coef.append([float(P[0, m]), float(P[1, m])])
        params.append({'term': 'Intercept', 'estimate': float(P[0, m]), 'se': math.sqrt(cov[2 * m, 2 * m]), 'group': m})
        params.append({'term': x, 'estimate': float(P[1, m]), 'se': math.sqrt(cov[2 * m + 1, 2 * m + 1]), 'group': m})
    fit.update({'kind': 'nominal', 'llf': float(res.llf), 'llnull': float(res.llnull), 'nparm': 2 * (k - 1), 'df': k - 1, 'params': params, 'cov': cov,
                'model': {'kind': 'nominal', 'coef': coef}})
    return fit


def _roc(score, pos, w):
    """The ROC curve of a score for positives `pos` (weights w): the
    thresholds from high to low; ties move together, as the Mann-Whitney
    AUC counts them."""
    order = np.argsort(-score, kind='stable')
    s, p, ww = score[order], pos[order], w[order]
    tp = np.cumsum(ww * p)
    fp = np.cumsum(ww * (1 - p))
    last = np.r_[np.nonzero(np.diff(s))[0], len(s) - 1]
    TP = np.r_[0, tp[last]]
    FP = np.r_[0, fp[last]]
    P, Nn = TP[-1], FP[-1]
    if P <= 0 or Nn <= 0:
        return None
    tpr, fpr = TP / P, FP / Nn
    auc = float(np.trapezoid(tpr, fpr)) if hasattr(np, 'trapezoid') else float(np.trapz(tpr, fpr))
    keep = _thin(len(tpr), 400)
    return {'fpr': fpr[keep], 'tpr': tpr[keep], 'auc': auc, 'cut': np.r_[np.inf, s[last]][keep]}


def _lift(score, pos, w):
    order = np.argsort(-score, kind='stable')
    p, ww = pos[order], w[order]
    cw = np.cumsum(ww)
    rate = np.sum(ww * p) / cw[-1]
    if rate <= 0:
        return None
    lift = (np.cumsum(ww * p) / cw) / rate
    portion = cw / cw[-1]
    keep = _thin(len(lift), 300)
    return {'portion': portion[keep], 'lift': lift[keep]}


@api('fitybyx.logistic')
def logistic(table, y, x, rows=None, weight=None, freq=None, alpha=0.05, target=None, where=None, table_name='data'):
    """Logistic: the Whole Model Test (likelihood ratio chi-square, the
    -LogLikelihoods, RSquare (U), AICc, BIC), Fit Details, Parameter
    Estimates with Wald chi-squares, unit and range Odds Ratios, the
    confusion matrix, ROC and lift curves."""
    fit = _logistic_fit(table, y, x, rows, weight, freq, target)
    k, levels, code, xv, wf = fit['k'], fit['levels'], fit['code'], fit['x'], fit['wf']
    N = fit['N']
    llf, lln = fit['llf'], fit['llnull']
    chi = 2 * (llf - lln)
    p = fit['nparm']
    P = _probs(fit['model'], xv)
    pa = P[np.arange(len(code)), code]
    pred = np.argmax(P, axis=1)
    z = stats.norm.ppf(1 - alpha / 2)
    est = []
    for q in fit['params']:
        e, se = q['estimate'], q['se']
        est.append({'term': q['term'], 'estimate': e, 'se': se, 'chisq': (e / se) ** 2 if se > 0 else None, 'p': float(stats.chi2.sf((e / se) ** 2, 1)) if se > 0 else None,
                    'lower': e - z * se, 'upper': e + z * se, 'group': q['group']})
    rng_x = float(xv.max() - xv.min())
    odds = []
    for q in est:
        if q['term'] != x:
            continue
        b, se = q['estimate'], q['se']
        odds.append({'group': q['group'], 'unit': math.exp(b), 'unit_lower': math.exp(b - z * se), 'unit_upper': math.exp(b + z * se),
                     'range': math.exp(b * rng_x), 'range_lower': math.exp((b - z * se) * rng_x), 'range_upper': math.exp((b + z * se) * rng_x), 'range_width': rng_x})
    conf = np.zeros((k, k))
    np.add.at(conf, (code, pred), wf)
    whole = [
        {'model': 'Difference', 'nll': llf - lln, 'df': fit['df'], 'chisq': chi, 'p': float(stats.chi2.sf(chi, fit['df']))},
        {'model': 'Full', 'nll': -llf, 'df': None, 'chisq': None, 'p': None},
        {'model': 'Reduced', 'nll': -lln, 'df': None, 'chisq': None, 'p': None},
    ]
    aicc = -2 * llf + 2 * p + (2 * p * (p + 1) / (N - p - 1) if N - p - 1 > 0 else float('nan'))
    bic = -2 * llf + p * math.log(N)
    gen = (1 - math.exp(2 * (lln - llf) / N)) / (1 - math.exp(2 * lln / N)) if lln < 0 else None
    details = [
        {'measure': 'Entropy RSquare', 'value': 1 - llf / lln if lln else None},
        {'measure': 'Generalized RSquare', 'value': gen},
        {'measure': 'Mean -Log p', 'value': -llf / N},
        {'measure': 'RMSE', 'value': math.sqrt(float(np.sum(wf * (1 - pa) ** 2)) / N)},
        {'measure': 'Mean Abs Dev', 'value': float(np.sum(wf * np.abs(1 - pa))) / N},
        {'measure': 'Misclassification Rate', 'value': float(np.sum(wf * (pred != code))) / N},
        {'measure': 'N', 'value': N},
    ]
    roc, lift = [], []
    targets = [fit['target']] if k == 2 else list(range(k))
    for j in targets:
        r = _roc(P[:, j], (code == j).astype(float), wf)
        if r:
            r['level'] = j
            roc.append(r)
        lf = _lift(P[:, j], (code == j).astype(float), wf)
        if lf:
            lf['level'] = j
            lift.append(lf)
    out = {'kind': fit['kind'], 'levels': levels, 'k': k, 'target': fit.get('target'), 'n': N, 'whole': whole, 'rsquare_u': 1 - llf / lln if lln else None,
           'aicc': aicc, 'bic': bic, 'details': details, 'estimates': est, 'odds': odds, 'confusion': conf, 'roc': roc, 'lift': lift,
           'model': fit['model'], 'x_range': [float(xv.min()), float(xv.max())], 'notes': fit['notes'], 'alpha': alpha}
    g = _grid(float(xv.min()), float(xv.max()), 200)
    Pg = _probs(fit['model'], g)
    out['curve'] = {'x': g, 'cum': np.cumsum(Pg, axis=1)[:, :-1].T}
    c = _head(table_name, where)
    c.append(f'd = df[[{J(x)}, {J(y)}{", " + J(weight) if weight else ""}{", " + J(freq) if freq else ""}]].dropna()')
    lv = [_lvtext(v) for v in levels]
    we = _wexpr(weight, freq)
    if fit['kind'] == 'binary':
        tl = lv[fit['target']]
        if we:
            c.append(f'res = smf.glm({J(f"I({_q(y)} == {J(tl)}) ~ {_q(x)}")}, d, family=sm.families.Binomial(), freq_weights={we}).fit()   # log odds of {tl}')
        else:
            c.append(f'd["_y"] = (d[{J(y)}].astype(str) == {J(tl)}).astype(int)   # log odds of {tl} against {lv[1 - fit["target"]]}')
            c.append(f'res = smf.logit({J("_y ~ " + _q(x))}, d).fit()')
        c.append('print(res.summary(), res.llf, res.llnull)')
    elif fit['kind'] == 'nominal':
        c.append(f'order = {J(lv[-1:] + lv[:-1])}   # the last level first: statsmodels\' reference')
        c.append(f'yc = pd.Categorical(d[{J(y)}].astype(str), categories=order).codes')
        c.append(f'res = sm.MNLogit(yc, sm.add_constant(d[{J(x)}])).fit(); print(res.summary())   # log odds of each level against {lv[-1]}')
    else:
        c.append('from statsmodels.miscmodels.ordinal_model import OrderedModel')
        c.append(f'yc = pd.Categorical(d[{J(y)}].astype(str), categories={J(lv)}, ordered=True)')
        c.append(f'res = OrderedModel(pd.Series(yc), d[[{J(x)}]], distr="logit").fit(method="bfgs")')
        c.append('print(res.summary())   # statsmodels: P(Y <= j) = F(threshold_j - b x); JMP reports the thresholds and -b')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.logistic_rows')
def logistic_rows(table, y, x, rows=None, weight=None, freq=None, target=None, alpha=0.05, where=None, table_name='data'):
    """Save Probability Formula, as values: each row's probability of each
    level and its most likely level."""
    fit = _logistic_fit(table, y, x, rows, weight, freq, target)
    P = _probs(fit['model'], fit['x'])
    return {'rows': fit['rows'], 'levels': fit['levels'], 'probs': P.T, 'most_likely': np.argmax(P, axis=1)}


@api('fitybyx.logistic_inverse')
def logistic_inverse(table, y, x, probs=(0.5,), rows=None, weight=None, freq=None, alpha=0.05, target=None, where=None, table_name='data'):
    """Inverse Prediction (binary response): the X at which the probability
    of the target level is p, with Fieller's confidence limits."""
    fit = _logistic_fit(table, y, x, rows, weight, freq, target)
    if fit['kind'] != 'binary':
        return {'error': 'Inverse Prediction is for a two-level response'}
    a, b = fit['coef_target']
    V = fit['cov']
    z = stats.norm.ppf(1 - alpha / 2)
    out = []
    for p in probs:
        p = float(p)
        if not 0 < p < 1:
            continue
        L = math.log(p / (1 - p))
        xp = (L - a) / b
        A = b * b - z * z * V[1, 1]
        B = 2 * ((a - L) * b - z * z * V[0, 1])
        C = (a - L) ** 2 - z * z * V[0, 0]
        lo = hi = None
        disc = B * B - 4 * A * C
        if A > 0 and disc >= 0:
            r1, r2 = (-B - math.sqrt(disc)) / (2 * A), (-B + math.sqrt(disc)) / (2 * A)
            lo, hi = min(r1, r2), max(r1, r2)
        out.append({'p': p, 'x': xp, 'lower': lo, 'upper': hi})
    c = _head(table_name, where)
    c.append('# a, b and their covariance V from the logistic fit: x = (log(p/(1-p)) - a)/b; Fieller: solve (a + b x - L)^2 = z^2 (V00 + 2 x V01 + x^2 V11)')
    return {'rows': out, 'alpha': alpha, 'target': fit['target'], 'levels': fit['levels'], 'code': '\n'.join(c)}


# ---- Contingency --------------------------------------------------------------

def _crosstab(table, y, x, rows, weight, freq):
    df = data.frame(table, [y, x, weight, freq], rows)
    df, w, f = _wf(df, table, weight, freq)

    def cat(s):
        if not isinstance(s.dtype, pd.CategoricalDtype):
            s = pd.Series(pd.Categorical(s), index=s.index)
        return s.cat.remove_unused_categories()
    xs, ys = cat(df[x]), cat(df[y])
    xl, yl = list(xs.cat.categories), list(ys.cat.categories)
    xc, yc = xs.cat.codes.to_numpy(), ys.cat.codes.to_numpy()
    n = np.zeros((len(xl), len(yl)))
    np.add.at(n, (xc, yc), w * f)
    return n, xl, yl, df, w, f


def _ct_code(table_name, where, y, x, weight, freq, imports=()):
    c = _head(table_name, where, imports)
    we = _wexpr(weight, freq, 'df')
    if we:
        c.append(f'n = df.assign(_w={we}).pivot_table(index={J(x)}, columns={J(y)}, values="_w", aggfunc="sum", fill_value=0)')
    else:
        c.append(f'n = pd.crosstab(df[{J(x)}], df[{J(y)}])   # X levels as rows, Y levels as columns')
    return c


@api('fitybyx.contingency')
def contingency(table, y, x, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Contingency: the table of counts (X levels as rows, Y levels as
    columns) with expected counts, deviations and cell chi-squares; Tests:
    the likelihood ratio and Pearson chi-squares, and Fisher's exact test
    (2x2 with its one-sided forms; larger tables when small)."""
    n, xl, yl, df, w, f = _crosstab(table, y, x, rows, weight, freq)
    N = float(n.sum())
    r, c_ = n.shape
    out = {'x_levels': xl, 'y_levels': yl, 'counts': n, 'n': N}
    if N <= 0:
        return {'error': 'no rows with both values'}
    rs, cs = n.sum(1), n.sum(0)
    E = np.outer(rs, cs) / N
    out['expected'] = E
    with np.errstate(divide='ignore', invalid='ignore'):
        out['cellchi'] = np.where(E > 0, (n - E) ** 2 / E, np.nan)
    notes = []
    if r >= 2 and c_ >= 2:
        pe = stats.chi2_contingency(n, correction=False)
        lr = stats.chi2_contingency(n, correction=False, lambda_='log-likelihood')
        dof = int(pe.dof)
        # -LogLikelihoods: the model is the association, C. Total the entropy of Y
        with np.errstate(divide='ignore', invalid='ignore'):
            tot = float(-np.sum(np.where(cs > 0, cs * np.log(cs / N), 0.0)))
        model = float(lr.statistic) / 2
        out['loglike'] = {'n': N, 'df': dof, 'nll': model, 'rsq': model / tot if tot > 0 else None, 'nll_total': tot}
        out['tests'] = [{'test': 'Likelihood Ratio', 'chisq': float(lr.statistic), 'df': dof, 'p': float(lr.pvalue)},
                        {'test': 'Pearson', 'chisq': float(pe.statistic), 'df': dof, 'p': float(pe.pvalue)}]
        out['rsquare_u'] = model / tot if tot > 0 else None
        small = float(np.mean(E < 5))
        if small > 0.2:
            notes.append(f'Warning: {100 * small:.0f}% of the cells have an expected count less than 5, ChiSquare suspect.')
        if N / (r * c_) < 5:
            notes.append('Warning: the average cell count is less than 5, LR ChiSquare suspect.')
        integer = bool(np.all(np.abs(n - np.rint(n)) < 1e-9))
        if integer and r == 2 and c_ == 2:
            ni = np.rint(n).astype(int)
            fl = stats.fisher_exact(ni, alternative='less')
            fr = stats.fisher_exact(ni, alternative='greater')
            ft = stats.fisher_exact(ni)
            out['fisher'] = {'left': float(fl.pvalue), 'right': float(fr.pvalue), 'two': float(ft.pvalue), 'odds': float(ft.statistic)}
        elif integer and N <= 300 and r * c_ <= 30:
            try:
                ft = stats.fisher_exact(np.rint(n).astype(int))
                out['fisher'] = {'two': float(ft.pvalue)}
            except Exception:
                pass
    out['notes'] = notes
    c = _ct_code(table_name, where, y, x, weight, freq, ['from scipy import stats'])
    c.append('print(stats.chi2_contingency(n, correction=False))   # Pearson')
    c.append('print(stats.chi2_contingency(n, correction=False, lambda_="log-likelihood"))   # likelihood ratio G²')
    if r == 2 and c_ == 2:
        c.append('print(stats.fisher_exact(n), stats.fisher_exact(n, alternative="less"), stats.fisher_exact(n, alternative="greater"))   # 2-Tail, Left, Right')
    out['code'] = '\n'.join(c)
    return out


def _pq(n):
    """A_ij and D_ij: the counts concordant and discordant with cell ij."""
    r, c = n.shape
    P = np.zeros((r + 1, c + 1))
    P[1:, 1:] = n.cumsum(0).cumsum(1)
    tot = P[r, c]
    i = np.arange(r)[:, None]
    j = np.arange(c)[None, :]
    below_left = P[i, j]
    above_right = tot - P[i + 1, c] - P[r, j + 1] + P[i + 1, j + 1]
    below_right = P[i, c] - P[i, j + 1]
    above_left = P[r, j] - P[i + 1, j]
    return above_right + below_left, below_right + above_left


def _measures(n):
    """Measures of association with their asymptotic standard errors
    (ASE1), by the formulas of SAS PROC FREQ, which JMP follows."""
    n = np.asarray(n, float)
    N = n.sum()
    r, c = n.shape
    ni, nj = n.sum(1), n.sum(0)
    A, D = _pq(n)
    P = float(np.sum(n * A))
    Q = float(np.sum(n * D))
    d = A - D
    out = []

    def add(name, v, se):
        out.append({'measure': name, 'value': v, 'se': se})
    if P + Q > 0:
        g = (P - Q) / (P + Q)
        add('Gamma', g, 4 / (P + Q) ** 2 * math.sqrt(float(np.sum(n * (Q * A - P * D) ** 2))))
    wr = N * N - float(np.sum(ni ** 2))
    wc = N * N - float(np.sum(nj ** 2))
    if wr > 0 and wc > 0:
        wv = math.sqrt(wr * wc)
        tb = (P - Q) / wv
        v = ni[:, None] * wc + nj[None, :] * wr
        s = float(np.sum(n * (2 * wv * d + tb * v) ** 2)) - N ** 3 * tb * tb * (wr + wc) ** 2
        add('Kendall\'s Tau-b', tb, math.sqrt(max(0.0, s)) / wv ** 2)
    m = min(r, c)
    if m > 1:
        tc = m * (P - Q) / (N * N * (m - 1))
        add('Stuart\'s Tau-c', tc, 2 * m / ((m - 1) * N * N) * math.sqrt(max(0.0, float(np.sum(n * d * d)) - (P - Q) ** 2 / N)))
    if wr > 0:
        add('Somers\' D C|R', (P - Q) / wr, 2 / wr ** 2 * math.sqrt(float(np.sum(n * (wr * d - (P - Q) * (N - ni[:, None])) ** 2))))
    if wc > 0:
        add('Somers\' D R|C', (P - Q) / wc, 2 / wc ** 2 * math.sqrt(float(np.sum(n * (wc * d - (P - Q) * (N - nj[None, :])) ** 2))))
    # lambda: the proportional reduction in the error of guessing
    ri = n.max(1)
    rmax = nj.max()
    li = n.argmax(1)
    l_ = int(nj.argmax())
    if N - rmax > 0:
        lam = (float(ri.sum()) - rmax) / (N - rmax)
        s = float(ri.sum() + rmax - 2 * ri[li == l_].sum())
        add('Lambda Asymmetric C|R', lam, math.sqrt(max(0.0, (N - ri.sum()) / (N - rmax) ** 3 * s)))
    cj = n.max(0)
    cmax = ni.max()
    lj = n.argmax(0)
    k_ = int(ni.argmax())
    if N - cmax > 0:
        lam = (float(cj.sum()) - cmax) / (N - cmax)
        s = float(cj.sum() + cmax - 2 * cj[lj == k_].sum())
        add('Lambda Asymmetric R|C', lam, math.sqrt(max(0.0, (N - cj.sum()) / (N - cmax) ** 3 * s)))
    if 2 * N - rmax - cmax > 0:
        def lam_sym(p):
            return (p.max(1).sum() + p.max(0).sum() - p.sum(0).max() - p.sum(1).max()) / (2 - p.sum(0).max() - p.sum(1).max())
        add('Lambda Symmetric', float(lam_sym(n / N)), _delta_se(lam_sym, n))
    # uncertainty coefficients, from the entropies
    with np.errstate(divide='ignore', invalid='ignore'):
        Hx = float(-np.sum(np.where(ni > 0, ni / N * np.log(ni / N), 0)))
        Hy = float(-np.sum(np.where(nj > 0, nj / N * np.log(nj / N), 0)))
        Hxy = float(-np.sum(np.where(n > 0, n / N * np.log(n / N), 0)))
        ln_ij = np.where(n > 0, np.log(n / N), 0)
        ln_i = np.log(ni / N)[:, None]
        ln_j = np.log(nj / N)[None, :]
    if Hy > 0:
        u = (Hx + Hy - Hxy) / Hy
        s = float(np.sum(n * (Hy * (ln_ij - ln_i) + (Hx - Hxy) * ln_j) ** 2))
        add('Uncertainty Coef C|R', u, math.sqrt(max(0.0, s)) / (N * Hy * Hy))
    if Hx > 0:
        u = (Hx + Hy - Hxy) / Hx
        s = float(np.sum(n * (Hx * (ln_ij - ln_j) + (Hy - Hxy) * ln_i) ** 2))
        add('Uncertainty Coef R|C', u, math.sqrt(max(0.0, s)) / (N * Hx * Hx))
    if Hx + Hy > 0:
        u = 2 * (Hx + Hy - Hxy) / (Hx + Hy)
        s = float(np.sum(n * (Hxy * (ln_i + ln_j) - (Hx + Hy) * ln_ij) ** 2))
        add('Uncertainty Coef Symmetric', u, 2 * math.sqrt(max(0.0, s)) / (N * (Hx + Hy) ** 2))
    return out


def _delta_se(fn, n, h=1e-6):
    """The delta-method standard error of fn(proportions) under the
    multinomial: sqrt((sum p d^2 - (sum p d)^2)/N), d the gradient."""
    n = np.asarray(n, float)
    N = n.sum()
    p = n / N
    g = np.zeros_like(p)
    for idx in np.ndindex(p.shape):
        a, b = p.copy(), p.copy()
        a[idx] += h
        b[idx] -= h
        g[idx] = (fn(a) - fn(b)) / (2 * h)
    v = float(np.sum(p * g * g) - np.sum(p * g) ** 2)
    return math.sqrt(max(0.0, v / N))


@api('fitybyx.contingency_measures')
def contingency_measures(table, y, x, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Measures of Association: gamma, Kendall's tau-b, Stuart's tau-c,
    Somers' D, lambda, uncertainty coefficients (SAS/JMP formulas, numpy),
    with Wald intervals from their ASE; Cramér's V, the contingency
    coefficient and Tschuprow's T (scipy.stats.contingency.association)."""
    n, xl, yl, df, w, f = _crosstab(table, y, x, rows, weight, freq)
    if n.shape[0] < 2 or n.shape[1] < 2:
        return {'error': 'needs two levels of each variable'}
    z = stats.norm.ppf(1 - alpha / 2)
    ms = _measures(n)
    for m in ms:
        m['lower'] = m['value'] - z * m['se'] if m['se'] is not None else None
        m['upper'] = m['value'] + z * m['se'] if m['se'] is not None else None
    other = []
    ni = np.rint(n).astype(int)
    if np.all(np.abs(n - ni) < 1e-9):
        for meth, lab in (('cramer', 'Cramér\'s V'), ('pearson', 'Contingency Coefficient'), ('tschuprow', 'Tschuprow\'s T')):
            try:
                other.append({'measure': lab, 'value': float(stats.contingency.association(ni, method=meth))})
            except Exception:
                pass
    out = {'measures': ms, 'other': other, 'alpha': alpha,
           'notes': ['Gamma, tau-b, tau-c, Somers\' D, lambda and the uncertainty coefficients are computed with numpy by the formulas of SAS PROC FREQ (statsmodels has none of them); tau-b and Somers\' D agree with scipy\'s kendalltau and somersd. The intervals are value ± z·Std Err.']}
    c = _ct_code(table_name, where, y, x, weight, freq, ['from scipy import stats'])
    c.append('print(stats.somersd(n.to_numpy()).statistic, stats.contingency.association(n.to_numpy(), method="cramer"))   # Somers\' D R|C in scipy\'s orientation, Cramér\'s V')
    c.append(f'print(stats.kendalltau(df[{J(x)}].astype("category").cat.codes, df[{J(y)}].astype("category").cat.codes))   # tau-b (level order = sorted)')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.contingency_agreement')
def contingency_agreement(table, y, x, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Agreement Statistic: Cohen's kappa (statsmodels cohens_kappa) of the
    square table over the levels of both columns, and Bowker's test of
    symmetry (statsmodels SquareTable.symmetry)."""
    from statsmodels.stats.inter_rater import cohens_kappa
    from statsmodels.stats.contingency_tables import SquareTable
    n, xl, yl, df, w, f = _crosstab(table, y, x, rows, weight, freq)
    names = []
    for v in list(xl) + list(yl):
        if _lvtext(v) not in names:
            names.append(_lvtext(v))
    k = len(names)
    sq = np.zeros((k, k))
    for i, a in enumerate(xl):
        for j, b in enumerate(yl):
            sq[names.index(_lvtext(a)), names.index(_lvtext(b))] += n[i, j]
    if k < 2:
        return {'error': 'needs two levels'}
    if not set(_lvtext(v) for v in xl) & set(_lvtext(v) for v in yl):
        return {'error': 'Agreement Statistic compares two ratings on the same scale: X and Y have no level in common'}
    kr = cohens_kappa(sq)
    zq = stats.norm.ppf(1 - alpha / 2)
    out = {'levels': names, 'table': sq, 'kappa': float(kr.kappa), 'se': float(kr.std_kappa), 'lower': float(kr.kappa - zq * kr.std_kappa), 'upper': float(kr.kappa + zq * kr.std_kappa),
           'z': float(kr.z_value), 'p_greater': float(kr.pvalue_one_sided), 'p_two': float(kr.pvalue_two_sided), 'se0': float(kr.std_kappa0)}
    try:
        b = SquareTable(sq, shift_zeros=False).symmetry(method='bowker')
        out['bowker'] = {'chisq': float(b.statistic), 'df': int(b.df), 'p': float(b.pvalue)}
    except Exception:
        pass
    out['notes'] = ['The levels are matched by their text; a level missing from one column is a row or column of zeros.',
                    'Prob>Z uses the standard error under no agreement (std_kappa0); the interval uses the standard error of the estimate.']
    c = _ct_code(table_name, where, y, x, weight, freq, ['from statsmodels.stats.inter_rater import cohens_kappa', 'from statsmodels.stats.contingency_tables import SquareTable'])
    c.append('lv = sorted(set(n.index.astype(str)) | set(n.columns.astype(str))); sq = n.rename(index=str, columns=str).reindex(index=lv, columns=lv, fill_value=0)')
    c.append('print(cohens_kappa(sq.to_numpy()))   # kappa, its standard error, a 95% interval, the z test')
    c.append('print(SquareTable(sq.to_numpy(), shift_zeros=False).symmetry())   # Bowker')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.contingency_2x2')
def contingency_2x2(table, y, x, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Relative Risk, Odds Ratio and Risk Difference of a 2x2 table
    (statsmodels Table2x2 and confint_proportions_2indep), and McNemar's
    test."""
    from statsmodels.stats.contingency_tables import Table2x2, mcnemar
    from statsmodels.stats.proportion import confint_proportions_2indep
    n, xl, yl, df, w, f = _crosstab(table, y, x, rows, weight, freq)
    if n.shape != (2, 2):
        return {'error': 'Relative Risk and Odds Ratio need a 2x2 table'}
    risks = []
    for j in (0, 1):
        t = Table2x2(n[:, [j, 1 - j]], shift_zeros=False)
        lo, hi = t.riskratio_confint(alpha=alpha)
        p1, p2 = n[0, j] / n[0].sum(), n[1, j] / n[1].sum()
        dl, dh = confint_proportions_2indep(n[0, j], n[0].sum(), n[1, j], n[1].sum(), method='wald', compare='diff', alpha=alpha)
        risks.append({'response': j, 'rr': float(t.riskratio), 'lower': float(lo), 'upper': float(hi), 'p1': float(p1), 'p2': float(p2),
                      'diff': float(p1 - p2), 'diff_lower': float(dl), 'diff_upper': float(dh)})
    t = Table2x2(n, shift_zeros=False)
    lo, hi = t.oddsratio_confint(alpha=alpha)
    out = {'risks': risks, 'odds': {'or': float(t.oddsratio), 'lower': float(lo), 'upper': float(hi), 'se_log': float(t.log_oddsratio_se)}, 'alpha': alpha}
    ni = np.rint(n)
    if np.all(np.abs(n - ni) < 1e-9):
        mc = mcnemar(ni, exact=False, correction=False)
        me = mcnemar(ni, exact=True)
        out['mcnemar'] = {'chisq': float(mc.statistic), 'p': float(mc.pvalue), 'p_exact': float(me.pvalue)}
    c = _ct_code(table_name, where, y, x, weight, freq, ['from statsmodels.stats.contingency_tables import Table2x2, mcnemar'])
    c.append('t = Table2x2(n.to_numpy()); print(t.riskratio, t.riskratio_confint(), t.oddsratio, t.oddsratio_confint())   # P(first Y level | first X level) / P(... | second)')
    c.append('print(mcnemar(n.to_numpy(), exact=False, correction=False), mcnemar(n.to_numpy(), exact=True))')
    out['code'] = '\n'.join(c)
    return out


# Two Sample Test for Proportions: (statsmodels method, correction, label, needs every cell > 0, test available)
TWOPROP_METHODS = {
    'diff': [('wald', True, 'Wald', False, True), ('agresti-caffo', True, 'Agresti-Caffo (adjusted Wald, as JMP)', False, True),
             ('newcomb', True, 'Newcombe (hybrid score)', False, False), ('score', True, 'Miettinen-Nurminen (score)', False, True)],
    'ratio': [('log', True, 'Katz (log)', True, True), ('log-adjusted', True, 'Adjusted log (0.5 added)', False, True),
              ('score', False, 'Koopman (score)', False, True), ('score', True, 'Miettinen-Nurminen (score)', False, True)],
    'odds-ratio': [('logit', True, 'Woolf (logit)', True, True), ('logit-adjusted', True, 'Gart (adjusted logit, 0.5 added)', False, True),
                   ('logit-smoothed', True, 'Independence-smoothed logit', False, True), ('score', True, 'Miettinen-Nurminen (score)', False, True)],
}


@api('fitybyx.contingency_twoprop')
def contingency_twoprop(table, y, x, compare='diff', response=None, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Two Sample Test for Proportions: the proportion of one Y level
    (response, default the first) in the first X level against the second,
    compared as a difference, a ratio (relative risk) or an odds ratio, by
    each of statsmodels' methods: confint_proportions_2indep for the
    interval, test_proportions_2indep for the test that the two are equal.
    JMP's report is the Agresti-Caffo (adjusted Wald) difference."""
    from statsmodels.stats.proportion import confint_proportions_2indep, test_proportions_2indep
    if compare not in TWOPROP_METHODS:
        return {'error': f'unknown comparison {compare!r}'}
    n, xl, yl, df, w, f = _crosstab(table, y, x, rows, weight, freq)
    if n.shape != (2, 2):
        return {'error': 'the Two Sample Test for Proportions needs two levels of X and two of Y'}
    j = 0
    if response is not None:
        for jj, lv in enumerate(yl):
            if _lvtext(lv) == _lvtext(response):
                j = jj
    c1, n1, c2, n2 = float(n[0, j]), float(n[0].sum()), float(n[1, j]), float(n[1].sum())
    if n1 <= 0 or n2 <= 0:
        return {'error': 'each level of X needs rows'}
    p1, p2 = c1 / n1, c2 / n2
    null = 0.0 if compare == 'diff' else 1.0
    with np.errstate(divide='ignore', invalid='ignore'):
        est = {'diff': p1 - p2, 'ratio': p1 / p2 if p2 > 0 else (np.inf if p1 > 0 else np.nan),
               'odds-ratio': (p1 / (1 - p1)) / (p2 / (1 - p2)) if 0 < p2 < 1 and p1 < 1 else np.nan}[compare]
    zero = min(c1, c2, n1 - c1, n2 - c2) <= 0
    cell0 = {'diff': False, 'ratio': min(c1, c2) <= 0, 'odds-ratio': zero}[compare]
    rows_out, notes = [], []
    for m, corr, label, needs, has_test in TWOPROP_METHODS[compare]:
        row = {'method': label, 'key': m, 'correction': corr, 'lower': None, 'upper': None, 'z': None, 'p': None, 'p_greater': None, 'p_less': None}
        if needs and cell0:
            row['note'] = 'not defined with a zero count'
            rows_out.append(row)
            continue
        # zero cells make statsmodels' root finding divide by zero on the way: the results are checked below
        with np.errstate(divide='ignore', invalid='ignore'):
            try:
                lo, hi = confint_proportions_2indep(c1, n1, c2, n2, method=m, compare=compare, alpha=alpha, correction=corr)
                row['lower'], row['upper'] = _fin(lo), _fin(hi)
            except (ValueError, ZeroDivisionError, FloatingPointError):
                row['note'] = 'statsmodels\' interval fails with a zero count'
            if has_test:
                try:
                    t2 = test_proportions_2indep(c1, n1, c2, n2, value=null, method=m, compare=compare, correction=corr)
                    tg = test_proportions_2indep(c1, n1, c2, n2, value=null, method=m, compare=compare, correction=corr, alternative='larger')
                    tl = test_proportions_2indep(c1, n1, c2, n2, value=null, method=m, compare=compare, correction=corr, alternative='smaller')
                    row.update({'z': _fin(t2.statistic), 'p': _fin(t2.pvalue), 'p_greater': _fin(tg.pvalue), 'p_less': _fin(tl.pvalue)})
                except (ValueError, ZeroDivisionError, FloatingPointError):
                    pass
        if row['lower'] is not None and row['upper'] is not None and not row['lower'] <= row['upper']:
            row['lower'] = row['upper'] = None
            row['note'] = 'statsmodels\' interval fails with a zero count'
        rows_out.append(row)
    if zero:
        notes.append('A cell of the table is zero: the Katz, Woolf and some score methods are not defined or fall back; the adjusted methods add 0.5 (or 1) to the counts.')
    if weight or freq:
        integer = bool(np.all(np.abs(n - np.rint(n)) < 1e-9))
        if not integer:
            notes.append('The counts are weighted (not whole numbers): the methods are used as they are, which assumes the weights are frequencies.')
    ylab, x1, x2 = _lvtext(yl[j]), _lvtext(xl[0]), _lvtext(xl[1])
    what = {'diff': f'P({ylab}|{x1}) − P({ylab}|{x2})', 'ratio': f'P({ylab}|{x1}) / P({ylab}|{x2})',
            'odds-ratio': f'Odds({ylab}|{x1}) / Odds({ylab}|{x2})'}[compare]
    out = {'compare': compare, 'response': j, 'y_levels': yl, 'x_levels': xl, 'counts': n, 'count1': c1, 'nobs1': n1, 'count2': c2, 'nobs2': n2,
           'p1': p1, 'p2': p2, 'estimate': _fin(est), 'null': null, 'description': what, 'methods': rows_out, 'alpha': alpha, 'notes': notes}
    c = _ct_code(table_name, where, y, x, weight, freq, ['from statsmodels.stats.proportion import test_proportions_2indep, confint_proportions_2indep'])
    c.append(f'count1, nobs1 = n.loc[{_lvcode(xl[0])}, {_lvcode(yl[j])}], n.loc[{_lvcode(xl[0])}].sum()   # {ylab} in {x1}')
    c.append(f'count2, nobs2 = n.loc[{_lvcode(xl[1])}, {_lvcode(yl[j])}], n.loc[{_lvcode(xl[1])}].sum()   # {ylab} in {x2}')
    for m, corr, label, needs, has_test in TWOPROP_METHODS[compare]:
        args = f'count1, nobs1, count2, nobs2, method={J(m)}, compare={J(compare)}{"" if corr else ", correction=False"}'
        line = f'print({J(label)}, confint_proportions_2indep({args}, alpha={alpha!r})'
        line += f', test_proportions_2indep({args}).pvalue)' if has_test else ')'
        c.append(line)
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.contingency_cmh')
def contingency_cmh(table, y, x, strata, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Cochran Mantel Haenszel: a 2x2 table (X by Y) in each level of the
    grouping column, their pooled Mantel-Haenszel odds ratio, the CMH test
    that it is one and the Breslow-Day test that the odds ratios are equal
    (statsmodels StratifiedTable)."""
    from statsmodels.stats.contingency_tables import StratifiedTable
    df = data.frame(table, [y, x, strata, weight, freq], rows)
    df, w, f = _wf(df, table, weight, freq)

    def cat(s):
        if not isinstance(s.dtype, pd.CategoricalDtype):
            s = pd.Series(pd.Categorical(s), index=s.index)
        return s.cat.remove_unused_categories()
    xs, ys, ss = cat(df[x]), cat(df[y]), cat(df[strata])
    if len(xs.cat.categories) != 2 or len(ys.cat.categories) != 2:
        return {'error': 'statsmodels\' Cochran-Mantel-Haenszel test is for 2x2 tables in each stratum: X and Y need two levels each'}
    tabs = []
    names = []
    for j, lv in enumerate(ss.cat.categories):
        sel = (ss.cat.codes == j).to_numpy()
        t = np.zeros((2, 2))
        np.add.at(t, (xs.cat.codes.to_numpy()[sel], ys.cat.codes.to_numpy()[sel]), (w * f)[sel])
        if t.sum(1).min() > 0 and t.sum(0).min() > 0:
            tabs.append(t)
            names.append(lv)
    if not tabs:
        return {'error': 'no stratum has both levels of X and of Y'}
    from statsmodels.stats.contingency_tables import Table2x2
    st = StratifiedTable([t for t in tabs])
    tn = st.test_null_odds(correction=False)
    lo, hi = st.oddsratio_pooled_confint(alpha=alpha)
    notes = []
    out = {'strata': len(tabs), 'strata_levels': names, 'cmh': {'chisq': float(tn.statistic), 'df': 1, 'p': float(tn.pvalue)},
           'or_mh': float(st.oddsratio_pooled), 'lower': float(lo), 'upper': float(hi), 'alpha': alpha,
           'rr_mh': _fin(st.riskratio_pooled), 'se_log_or': _fin(st.logodds_pooled_se)}
    # R's mantelhaen.test corrects by 0.5 only when |sum(a - E(a))| >= 0.5;
    # statsmodels always subtracts it: the same guard is kept here
    cube = st.table
    dev = float(np.abs(np.sum(cube[0, 0, :] - cube[0, :, :].sum(0) * cube[:, 0, :].sum(0) / cube.sum((0, 1)))))
    if dev >= 0.5:
        tc = st.test_null_odds(correction=True)
        out['cmh_cc'] = {'chisq': float(tc.statistic), 'df': 1, 'p': float(tc.pvalue)}
    else:
        out['cmh_cc'] = {'chisq': 0.0, 'df': 1, 'p': 1.0}
        notes.append('|Σ(a − E(a))| is below 0.5: the continuity-corrected statistic is 0, as in R\'s mantelhaen.test (statsmodels would square a negative difference).')
    if len(tabs) > 1:
        with np.errstate(divide='ignore', invalid='ignore'):
            te = st.test_equal_odds(adjust=False)
            ta = st.test_equal_odds(adjust=True)
        if np.isfinite(te.statistic):
            out['breslow_day'] = {'chisq': float(te.statistic), 'df': len(tabs) - 1, 'p': float(te.pvalue)}
        if np.isfinite(ta.statistic):
            out['breslow_day_tarone'] = {'chisq': float(ta.statistic), 'df': len(tabs) - 1, 'p': float(ta.pvalue)}
    by = []
    for lv, t in zip(names, tabs):
        row = {'level': lv, 'n': float(t.sum()), 'a': float(t[0, 0]), 'b': float(t[0, 1]), 'c': float(t[1, 0]), 'd': float(t[1, 1]),
               'or': None, 'lower': None, 'upper': None}
        if np.all(t > 0):
            t2 = Table2x2(t, shift_zeros=False)
            l2, h2 = t2.oddsratio_confint(alpha=alpha)
            row.update({'or': float(t2.oddsratio), 'lower': float(l2), 'upper': float(h2)})
        by.append(row)
    out['by_stratum'] = by
    if any(r_['or'] is None for r_ in by):
        notes.append('A stratum with a zero cell has no finite odds ratio of its own; it still counts in the Mantel-Haenszel estimate and tests.')
    out['notes'] = notes
    c = _head(table_name, where, ['from statsmodels.stats.contingency_tables import StratifiedTable'])
    we = _wexpr(weight, freq, 'df')
    order = f'.reindex(index=[{", ".join(_lvcode(v) for v in xs.cat.categories)}], columns=[{", ".join(_lvcode(v) for v in ys.cat.categories)}], fill_value=0)'
    if we:
        c.append(f'df = df.assign(_n={we})')
        c.append(f'tabs = [g.pivot_table(index={J(x)}, columns={J(y)}, values="_n", aggfunc="sum", fill_value=0){order}.to_numpy() for _, g in df.groupby({J(strata)})]')
    else:
        c.append(f'tabs = [pd.crosstab(g[{J(x)}], g[{J(y)}]){order}.to_numpy() for _, g in df.groupby({J(strata)})]   # the levels in the table\'s order')
    c.append('st = StratifiedTable([t for t in tabs if t.sum(0).min() > 0 and t.sum(1).min() > 0])')
    c.append(f'print(st.test_null_odds(correction=False), st.test_null_odds(correction=True), st.oddsratio_pooled, st.oddsratio_pooled_confint(alpha={alpha!r}), st.riskratio_pooled)')
    c.append('print(st.test_equal_odds(adjust=False), st.test_equal_odds(adjust=True))   # Breslow-Day, and with Tarone\'s adjustment')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.contingency_trend')
def contingency_trend(table, y, x, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Cochran Armitage Trend Test: a two-level variable against the
    ordered levels of the other (scores 0, 1, 2, ...), statsmodels'
    Table.test_ordinal_association; shown also with the binomial variance
    of the Cochran-Armitage test as SAS and JMP compute it."""
    from statsmodels.stats.contingency_tables import Table
    n, xl, yl, df, w, f = _crosstab(table, y, x, rows, weight, freq)
    r, c_ = n.shape
    if 2 not in (r, c_) or min(r, c_) < 2:
        return {'error': 'the trend test needs a two-level variable'}
    res = Table(n, shift_zeros=False).test_ordinal_association()
    N = float(n.sum())
    z_ca = float(res.zscore) * math.sqrt(N / (N - 1))
    out = {'z_perm': float(res.zscore), 'p_perm': float(res.pvalue), 'z': z_ca, 'p_two': float(2 * stats.norm.sf(abs(z_ca))),
           'p_greater': float(stats.norm.sf(z_ca)), 'p_less': float(stats.norm.cdf(z_ca)), 'statistic': float(res.statistic), 'n': N,
           'notes': ['statsmodels\' test_ordinal_association uses the permutation variance, (N−1)r²; the Cochran-Armitage test of SAS and JMP uses the binomial variance, N r², so its Z is √(N/(N−1)) times statsmodels\' z. Both are shown.']}
    c = _ct_code(table_name, where, y, x, weight, freq, ['from statsmodels.stats.contingency_tables import Table'])
    c.append('r = Table(n.to_numpy(), shift_zeros=False).test_ordinal_association(); print(r.zscore, r.pvalue)')
    c.append('print(r.zscore * np.sqrt(n.to_numpy().sum() / (n.to_numpy().sum() - 1)))   # the Cochran-Armitage Z')
    out['code'] = '\n'.join(c)
    return out


@api('fitybyx.contingency_anomp')
def contingency_anomp(table, y, x, event=None, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Analysis of Means for Proportions: the proportion of one response
    level in each X level against decision limits around the overall
    proportion, p ± h sqrt(p(1 - p)(N - n_i)/(N n_i)), the normal
    approximation to the binomial with the exact ANOM critical value for
    infinite degrees of freedom."""
    n, xl, yl, df, w, f = _crosstab(table, y, x, rows, weight, freq)
    if len(yl) != 2:
        return {'error': 'Analysis of Means for Proportions needs a two-level response'}
    if len(xl) < 2:
        return {'error': 'needs two levels of X'}
    j = 0
    if event is not None:
        for i, lv in enumerate(yl):
            if _lvtext(lv) == _lvtext(event):
                j = i
    ni = n.sum(1)
    N = float(ni.sum())
    pbar = float(n[:, j].sum() / N)
    h = _anom_h(ni, alpha)
    lv = []
    for i in range(len(xl)):
        half = h * math.sqrt(pbar * (1 - pbar) * (N - ni[i]) / (N * ni[i]))
        p = float(n[i, j] / ni[i])
        lv.append({'index': i, 'level': xl[i], 'n': float(ni[i]), 'p': p, 'ldl': max(0.0, pbar - half), 'udl': min(1.0, pbar + half), 'out': bool(abs(p - pbar) > half)})
    c = _ct_code(table_name, where, y, x, weight, freq)
    c.append(f'p = n.iloc[:, {j}] / n.sum(1); pbar = n.iloc[:, {j}].sum() / n.to_numpy().sum(); ni, N = n.sum(1), n.to_numpy().sum()')
    c.append(f'h = {h!r}   # the ANOM critical value for infinite df (multivariate normal)')
    c.append('print(p, pbar - h*np.sqrt(pbar*(1-pbar)*(N-ni)/(N*ni)), pbar + h*np.sqrt(pbar*(1-pbar)*(N-ni)/(N*ni)))')
    return {'levels': lv, 'event': j, 'y_levels': yl, 'pbar': pbar, 'h': h, 'alpha': alpha, 'code': '\n'.join(c)}


@api('fitybyx.contingency_ca')
def contingency_ca(table, y, x, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """Correspondence Analysis: the singular value decomposition of the
    standardised residuals (P - r c')/sqrt(r c'), the principal inertias
    and the principal coordinates of the X and Y levels."""
    n, xl, yl, df, w, f = _crosstab(table, y, x, rows, weight, freq)
    r, c_ = n.shape
    if min(r, c_) < 2:
        return {'error': 'needs two levels of each variable'}
    N = n.sum()
    P = n / N
    rm, cm = P.sum(1), P.sum(0)
    S = (P - np.outer(rm, cm)) / np.sqrt(np.outer(rm, cm))
    U, s, Vt = np.linalg.svd(S, full_matrices=False)
    k = min(r, c_) - 1
    s = s[:k]
    F = U[:, :k] * s / np.sqrt(rm)[:, None]
    G = Vt.T[:, :k] * s / np.sqrt(cm)[:, None]
    # a sign convention: the largest coordinate of each dimension among the X levels is positive
    for d in range(k):
        if F[np.argmax(np.abs(F[:, d])), d] < 0:
            F[:, d] *= -1
            G[:, d] *= -1
    inertia = s ** 2
    tot = inertia.sum()
    out = {'details': [{'dim': d + 1, 'sv': float(s[d]), 'inertia': float(inertia[d]), 'portion': float(inertia[d] / tot) if tot > 0 else None,
                        'cum': float(inertia[:d + 1].sum() / tot) if tot > 0 else None} for d in range(k)],
           'rows': [{'level': xl[i], 'mass': float(rm[i]), 'c1': float(F[i, 0]), 'c2': float(F[i, 1]) if k > 1 else None} for i in range(r)],
           'cols': [{'level': yl[j], 'mass': float(cm[j]), 'c1': float(G[j, 0]), 'c2': float(G[j, 1]) if k > 1 else None} for j in range(c_)],
           'chisq': float(N * tot)}
    c = _ct_code(table_name, where, y, x, weight, freq)
    c.append('P = n.to_numpy() / n.to_numpy().sum(); r, c = P.sum(1), P.sum(0); S = (P - np.outer(r, c)) / np.sqrt(np.outer(r, c))')
    c.append('U, s, Vt = np.linalg.svd(S, full_matrices=False); print(s**2)   # principal inertias')
    c.append('print(U * s / np.sqrt(r)[:, None], Vt.T * s / np.sqrt(c)[:, None])   # row and column principal coordinates')
    out['code'] = '\n'.join(c)
    return out


# ---- Matched Pairs ----------------------------------------------------------------

@api('matchedpairs.analyze')
def matched_pairs(table, y1, y2, group=None, rows=None, alpha=0.05, where=None, table_name='data'):
    """Matched Pairs: the difference y2 - y1 against zero (paired t test,
    Wilcoxon signed rank, sign test), the correlation of the pair, the
    points of the Tukey mean-difference plot, and with a grouping column
    the differences and means compared across the groups."""
    from statsmodels.stats.weightstats import DescrStatsW
    from statsmodels.stats.descriptivestats import sign_test
    if y1 == y2:
        return {'error': 'the two responses are the same column'}
    df = data.frame(table, [y1, y2, group], rows)
    a = df[y1].to_numpy(float)
    b = df[y2].to_numpy(float)
    d = b - a
    m = (a + b) / 2
    n = len(d)
    if n < 2:
        return {'error': 'fewer than two complete pairs'}
    ds = DescrStatsW(d, ddof=1)
    t, p, dof = ds.ttest_mean(0.0)
    lo, hi = ds.tconfint_mean(alpha)
    r = stats.pearsonr(a, b) if n > 2 and np.std(a) > 0 and np.std(b) > 0 else None
    out = {'n': n, 'mean1': float(a.mean()), 'mean2': float(b.mean()), 'diff': float(ds.mean), 'se': float(ds.std_mean), 'sd': float(ds.std),
           'lower': float(lo), 'upper': float(hi), 't': float(t), 'df': float(dof), 'p': float(p), 'p_greater': float(stats.t.sf(t, dof)), 'p_less': float(stats.t.cdf(t, dof)),
           'r': float(r.statistic) if r is not None else None, 'alpha': alpha, 'rows': df.index.to_numpy(), 'd': d, 'm': m}
    nz = d[d != 0]
    if len(nz) >= 1:
        ranks = stats.rankdata(np.abs(nz))
        S = float(np.sum(np.sign(nz) * ranks) / 2)
        wt = stats.wilcoxon(nz) if len(nz) >= 2 else None
        out['wilcoxon'] = {'S': S, 'p_two': float(wt.pvalue) if wt is not None else None,
                           'p_greater': float(stats.wilcoxon(nz, alternative='greater').pvalue) if wt is not None else None,
                           'p_less': float(stats.wilcoxon(nz, alternative='less').pvalue) if wt is not None else None, 'n': len(nz)}
        M, ps = sign_test(d, 0.0)
        npos = int(np.sum(d > 0))
        out['sign'] = {'M': float(M), 'p_two': float(ps), 'p_greater': float(stats.binomtest(npos, len(nz), 0.5, alternative='greater').pvalue),
                       'p_less': float(stats.binomtest(npos, len(nz), 0.5, alternative='less').pvalue), 'n_pos': npos, 'n_neg': int(np.sum(d < 0)), 'n': len(nz)}
    if group:
        gs = df[group]
        if not isinstance(gs.dtype, pd.CategoricalDtype):
            gs = pd.Series(pd.Categorical(gs), index=df.index)
        gs = gs.cat.remove_unused_categories()
        gl = list(gs.cat.categories)
        gc = gs.cat.codes.to_numpy()
        across = []
        for i, lv in enumerate(gl):
            s = gc == i
            across.append({'level': lv, 'count': int(s.sum()), 'diff': float(d[s].mean()), 'mean': float(m[s].mean())})
        out['across'] = across
        if len(gl) >= 2 and all(np.sum(gc == i) >= 1 for i in range(len(gl))) and n > len(gl):
            fd = stats.f_oneway(*[d[gc == i] for i in range(len(gl))])
            fm = stats.f_oneway(*[m[gc == i] for i in range(len(gl))])
            out['across_tests'] = [{'what': 'Mean Difference', 'f': float(fd.statistic), 'dfn': len(gl) - 1, 'dfd': n - len(gl), 'p': float(fd.pvalue)},
                                   {'what': 'Mean Mean', 'f': float(fm.statistic), 'dfn': len(gl) - 1, 'dfd': n - len(gl), 'p': float(fm.pvalue)}]
        out['group_levels'] = gl
        out['group_code'] = gc
    c = _head(table_name, where, ['from scipy import stats', 'from statsmodels.stats.descriptivestats import sign_test'])
    c.append(f'd = df[[{J(y1)}, {J(y2)}{", " + J(group) if group else ""}]].dropna(); dif = d[{J(y2)}] - d[{J(y1)}]')
    c.append(f'print(stats.ttest_rel(d[{J(y2)}], d[{J(y1)}]))   # the paired t test of {y2} - {y1}')
    c.append('print(stats.wilcoxon(dif[dif != 0]), sign_test(dif, 0))   # Wilcoxon signed rank, sign test (M, p)')
    c.append(f'print(stats.pearsonr(d[{J(y1)}], d[{J(y2)}]))')
    if group:
        c.append(f'print(stats.f_oneway(*[g for _, g in dif.groupby(d[{J(group)}])]))   # the mean difference across the groups')
    out['code'] = '\n'.join(c)
    return out


def _pairs_of(table, y1, y2, rows):
    df = data.frame(table, [y1, y2], rows)
    a = df[y1].to_numpy(float)
    b = df[y2].to_numpy(float)
    return a, b, b - a


@api('matchedpairs.effect')
def matched_effect(table, y1, y2, rows=None, alpha=0.05, where=None, table_name='data'):
    """Effect Size of the paired difference y2 − y1: Cohen's d_z = mean
    difference/SD of the differences, with the exact interval from the
    noncentral t of the paired t (δ_z = λ/√n), Hedges' g_z = J(n − 1)·d_z,
    and d_av = mean difference/√((s₁² + s₂²)/2), comparable with a
    two-group d (Cumming 2012; Lakens 2013), with Bonett's (2008)
    interval."""
    if y1 == y2:
        return {'error': 'the two responses are the same column'}
    a, b, d = _pairs_of(table, y1, y2, rows)
    n = len(d)
    if n < 3:
        return {'error': 'fewer than three complete pairs'}
    sd = float(np.std(d, ddof=1))
    v1, v2 = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
    if not sd > 0 or not (v1 + v2) > 0:
        return {'error': 'the differences do not vary: no standardized effect'}
    dz = float(d.mean()) / sd
    rows_out = smd_rows(dz, dz * math.sqrt(n), n - 1, 1 / math.sqrt(n), alpha, names=("Cohen's d_z", "Hedges' g_z"))
    rho = float(np.corrcoef(a, b)[0, 1]) if v1 > 0 and v2 > 0 else 0.0
    dav = float(d.mean()) / math.sqrt((v1 + v2) / 2)
    se = bonett_se(dav, v1, v2, n, n, r=rho)
    z = float(stats.norm.ppf(1 - alpha / 2))
    rows_out.append({'effect': "Cohen's d_av", 'estimate': dav, 'lower': dav - z * se, 'upper': dav + z * se, 'method': 'Bonett (2008)', 'se': se})
    lv = f'{100 * (1 - alpha):g}%'
    t_ = _tab([col('effect', 'Effect Size', 'text'), col('estimate', 'Estimate'), col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}'),
               col('method', 'Interval', 'text'), col('se', 'Std Err', hidden=True)], rows_out)
    out = {'table': t_, 'n': n, 'r': rho, 'sd_diff': sd, 'alpha': alpha}
    c = _head(table_name, where, ['from scipy import stats, optimize, special'])
    c.append(f'd = df[[{J(y1)}, {J(y2)}]].dropna(); a, b = d[{J(y1)}].to_numpy(), d[{J(y2)}].to_numpy(); dif = b - a; n = len(dif)')
    c.append(NCP_T_CODE)
    c.append(f'dz = dif.mean() / dif.std(ddof=1); t = dz * np.sqrt(n); lo, hi = ncp(t, n - 1, {1 - alpha / 2!r}) / np.sqrt(n), ncp(t, n - 1, {alpha / 2!r}) / np.sqrt(n)')
    c.append('J = np.exp(special.gammaln((n - 1) / 2) - 0.5 * np.log((n - 1) / 2) - special.gammaln((n - 2) / 2))   # Hedges\' exact correction')
    c.append("print(dz, lo, hi, J * dz)   # Cohen's d_z with its exact interval (noncentral t), Hedges' g_z")
    c.append('v1, v2, r = a.var(ddof=1), b.var(ddof=1), np.corrcoef(a, b)[0, 1]; s2 = (v1 + v2) / 2; dav = dif.mean() / np.sqrt(s2)')
    c.append('se = np.sqrt(dav**2 * (v1**2 + v2**2 + 2*r**2*v1*v2) / (8*(n - 1)*s2**2) + (v1 + v2 - 2*r*np.sqrt(v1*v2)) / ((n - 1)*s2))   # Bonett (2008)')
    c.append(f'z = stats.norm.ppf({1 - alpha / 2!r}); print(dav, dav - z*se, dav + z*se)   # d_av with Bonett\'s interval')
    out['code'] = '\n'.join(c)
    return out


@api('matchedpairs.bayes')
def matched_bayes(table, y1, y2, r=JZS_R, rows=None, alpha=0.05, where=None, table_name='data'):
    """Bayes Factor of the paired t test (Rouder et al. 2009): the
    differences y2 − y1 as one sample, a Cauchy(0, r) prior on δ = mean
    difference/SD under the alternative; two-sided and one-sided."""
    if y1 == y2:
        return {'error': 'the two responses are the same column'}
    if not (r and r > 0):
        return {'error': 'the scale of the Cauchy prior must be positive'}
    a, b, d = _pairs_of(table, y1, y2, rows)
    n = len(d)
    if n < 2:
        return {'error': 'fewer than two complete pairs'}
    sd = float(np.std(d, ddof=1))
    if not sd > 0:
        return {'error': 'the differences do not vary: no t statistic'}
    t = float(d.mean()) / (sd / math.sqrt(n))
    rows_out = jzs_rows(t, n, n - 1, r, ['δ ≠ 0', f'δ > 0 ({y2} higher)', f'δ < 0 ({y2} lower)'])
    out = {'table': _bf_table(rows_out), 't': t, 'n': n, 'df': n - 1, 'r': r}
    c = _head(table_name, where, ['from scipy import stats, integrate'])
    c.append(f'd = df[[{J(y1)}, {J(y2)}]].dropna(); dif = d[{J(y2)}] - d[{J(y1)}]; n = len(dif)')
    c.append('t = stats.ttest_1samp(dif, 0).statistic   # the paired t')
    c.append(JZS_CODE)
    c.append(f'bf, p = jzs(t, n, n - 1, {r!r}); print(bf, 2*bf*p, 2*bf*(1 - p))   # BF10: δ ≠ 0, δ > 0, δ < 0; BF01 = 1/BF10')
    out['code'] = '\n'.join(c)
    return out


def _binary_text(table, columns, rows):
    """The responses as text (12.0 as 12, missing as None) and the values
    found, in the order of the columns' levels (numbers ascending)."""
    df = data.frame(table, columns, rows, dropna=False)
    txt, order = {}, []
    for c in columns:
        s = df[c]
        if isinstance(s.dtype, pd.CategoricalDtype):
            t = pd.Series([None if pd.isna(v) else _lvtext(v) for v in s.astype(object)], index=s.index, dtype=object)
            cand = [_lvtext(v) for v in s.cat.categories]
        else:
            vals = s.to_numpy(float)
            t = pd.Series([_lvtext(float(v)) if np.isfinite(v) else None for v in vals], index=s.index, dtype=object)
            cand = [_lvtext(float(v)) for v in np.unique(vals[np.isfinite(vals)])]
        present = set(t.dropna())
        order += [v for v in cand if v in present and v not in order]
        txt[c] = t
    return pd.DataFrame(txt), order


@api('matchedpairs.binary')
def matched_binary(table, columns, success=None, exact=True, correction=False, rows=None, alpha=0.05, where=None, table_name='data'):
    """Matched Pairs with binary responses: Cochran's Q test that every
    column has the same probability of the success level (statsmodels
    cochrans_q, on the rows with every response), and McNemar's test for
    each pair of columns (statsmodels mcnemar, each pair on its own complete
    rows): the chi-square, with or without the continuity correction, and
    the exact binomial test."""
    from statsmodels.stats.contingency_tables import cochrans_q, mcnemar
    from statsmodels.stats.multitest import multipletests
    cols = list(dict.fromkeys(c for c in columns if c))
    if len(cols) < 2:
        return {'error': 'Cochran\'s Q and McNemar\'s test need two or more responses'}
    T, order = _binary_text(table, cols, rows)
    if len(order) > 2:
        return {'error': f'Cochran\'s Q and McNemar\'s test take binary responses: these columns hold {len(order)} different values'}
    if len(order) < 2:
        return {'error': 'every response has the same value: there is nothing to compare'}
    succ = _lvtext(success) if success is not None and _lvtext(success) in order else order[-1]
    fail = order[0] if order[1] == succ else order[1]
    notes = []
    comp = T.notna().all(axis=1).to_numpy()
    X = (T[comp] == succ).astype(int).to_numpy()
    n, k = X.shape
    colsum, rowsum = X.sum(0), X.sum(1)
    columns_out = [{'column': c, 'n': n, 'count': int(colsum[i]), 'prop': float(colsum[i] / n) if n else None} for i, c in enumerate(cols)]
    discordant = int(np.sum((rowsum > 0) & (rowsum < k)))
    q = None
    if n < 2:
        notes.append('Fewer than two rows have every response: no Cochran\'s Q test.')
    elif discordant == 0:
        notes.append('No row has both outcomes, so every column has the same proportion: Cochran\'s Q is not defined (0/0).')
    else:
        r = cochrans_q(X, return_object=True)
        q = {'q': float(r.statistic), 'df': int(r.df), 'p': float(r.pvalue), 'n': n, 'k': k, 'discordant': discordant}
    pairs = []
    for i in range(k):
        for j in range(i + 1, k):
            a, b = T[cols[i]], T[cols[j]]
            ok = (a.notna() & b.notna()).to_numpy()
            xa = (a[ok] == succ).to_numpy()
            xb = (b[ok] == succ).to_numpy()
            m = int(ok.sum())
            n11, n10, n01, n00 = int(np.sum(xa & xb)), int(np.sum(xa & ~xb)), int(np.sum(~xa & xb)), int(np.sum(~xa & ~xb))
            row = {'i': i, 'j': j, 'n': m, 'n11': n11, 'n10': n10, 'n01': n01, 'n00': n00,
                   'p1': float(xa.mean()) if m else None, 'p2': float(xb.mean()) if m else None, 'diff': float(xb.mean() - xa.mean()) if m else None,
                   'chisq': None, 'p': None, 'p_exact': None}
            if m and n10 + n01 == 0:
                # statsmodels divides by n10 + n01: without a discordant pair
                # the statistic is 0/0 (or 1/0 with the correction)
                row.update({'chisq': 0.0, 'p': 1.0, 'p_exact': 1.0})
                notes.append(f'{cols[i]} and {cols[j]}: no discordant pair, so the proportions are equal (χ² = 0, p = 1).')
            elif m:
                tab = np.array([[n11, n10], [n01, n00]], float)
                if correction and n10 == n01:
                    row.update({'chisq': 0.0, 'p': 1.0})   # R's convention; statsmodels gives (0 - 1)²/(b + c)
                else:
                    mc = mcnemar(tab, exact=False, correction=bool(correction))
                    row.update({'chisq': float(mc.statistic), 'p': float(mc.pvalue)})
                row['p_exact'] = float(mcnemar(tab, exact=True).pvalue)
            pairs.append(row)
    key = 'p_exact' if exact else 'p'
    ps = [p_[key] for p_ in pairs if p_[key] is not None]
    if len(ps) > 1:
        adj = iter(multipletests(ps, method='holm')[1])
        for p_ in pairs:
            if p_[key] is not None:
                p_['p_holm'] = float(next(adj))
    out = {'columns': columns_out, 'cochran': q, 'pairs': pairs, 'success': succ, 'failure': fail, 'values': order, 'exact': bool(exact),
           'correction': bool(correction), 'n_complete': n, 'notes': notes, 'names': cols}
    # the code: the success indicator of each column, then the tests
    def is_succ(c, frame='d'):
        num = data.meta(table, c).get('dataType') == 'numeric'
        lit = _lvcode(float(succ)) if num else J(succ)
        return f'({frame}[{J(c)}] == {lit})'
    c = _head(table_name, where, ['from statsmodels.stats.contingency_tables import cochrans_q, mcnemar'])
    c.append(f'd = df[[{", ".join(J(v) for v in cols)}]].dropna()')
    c.append(f'X = pd.DataFrame({{{", ".join(f"{J(v)}: {is_succ(v)}" for v in cols)}}}).astype(int)   # 1: {succ}')
    c.append('print(cochrans_q(X.to_numpy()))   # Q, DF and p on the rows with every response')
    c.append(f'dd = df[[{J(cols[0])}, {J(cols[1])}]].dropna()   # one pair on its own complete rows; the same for each pair')
    c.append(f't = pd.crosstab({is_succ(cols[0], "dd")}, {is_succ(cols[1], "dd")}).reindex(index=[True, False], columns=[True, False], fill_value=0).to_numpy()')
    c.append(f'print(mcnemar(t, exact=False, correction={bool(correction)}), mcnemar(t, exact=True))   # chi-square, exact binomial')
    out['code'] = '\n'.join(c)
    return out
