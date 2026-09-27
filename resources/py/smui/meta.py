"""Meta-Analysis (Analyze > Specialized Modeling): one study per row.

A study's effect comes from one of three layouts of columns:

  es    an effect and its standard error (or variance), as published; the
        effect may be a log ratio, shown back-transformed
  cont  n, mean and standard deviation of a treatment and a control group:
        Hedges' g (statsmodels' effectsize_smd, RevMan's formulas) or the
        raw mean difference
  bin   events and totals of a treatment and a control group: log odds
        ratio, log risk ratio or risk difference (effectsize_2proportions)

The studies are pooled by statsmodels' combine_effects: the fixed effect
(inverse variance) and random effects with the DerSimonian-Laird ('chi2')
or the Paule-Mandel ('iterated') between-study variance. Three of its
corners are worked around here, and the report says so:

  * a DerSimonian-Laird tau^2 below zero (Q under its degrees of freedom)
    is left negative by combine_effects; the estimator is max(0, .), so the
    random-effects results are then the fixed-effect ones;
  * a numeric zero_correction is added to the counts of every study but to
    the totals of the studies with a zero cell only, so it is applied here
    to the studies with a zero cell alone;
  * k = 1 gives NaN: a single study is its own pooled estimate.

Paule-Mandel is left at statsmodels' tolerance (it stops at |Q - df| <
1e-5, tau^2 good to about six digits): its iteration sets tau^2 = 0 when
the estimating equation is below zero at any step, and with a tolerance
under about 1e-7 rounding at the root does that in several per cent of
heterogeneous data sets.

REML is not in statsmodels' meta_analysis: its tau^2 is the root of the
restricted-likelihood score (scipy's brentq), and the pooled estimate with
those weights is statsmodels' WLS with the scale fixed at one. The same WLS
does the meta-regression, with the residual tau^2 of the chosen method. The
odds ratio also gets the Mantel-Haenszel estimate of statsmodels'
StratifiedTable (RevMan's default for binary outcomes).
"""
import json
import math

import numpy as np
import pandas as pd
from scipy import optimize, stats
import statsmodels.api as sm
from statsmodels.stats.meta_analysis import combine_effects, effectsize_2proportions, effectsize_smd

from . import data
from .registry import api
from .util import code_head

# key: (the effect as computed, the scale it is shown on, plural, log scale)
MEASURES = {
    'es': ('Effect', 'Effect', 'Effects', False),
    'es_log': ('Log Ratio', 'Ratio', 'Ratios', True),
    'smd': ("Hedges' g", "Hedges' g", 'Standardized Mean Differences', False),
    'md': ('Mean Difference', 'Mean Difference', 'Mean Differences', False),
    'or': ('Log Odds Ratio', 'Odds Ratio', 'Odds Ratios', True),
    'rr': ('Log Risk Ratio', 'Risk Ratio', 'Risk Ratios', True),
    'rd': ('Risk Difference', 'Risk Difference', 'Risk Differences', False),
}
METHODS = {'dl': 'DerSimonian–Laird', 'pm': 'Paule–Mandel', 'reml': 'REML'}
LAYOUT_ROLES = {'es': ('effect', 'se'), 'cont': ('n1', 'mean1', 'sd1', 'n2', 'mean2', 'sd2'), 'bin': ('events1', 'total1', 'events2', 'total2')}
ROLE_LABEL = {'effect': 'Effect', 'se': 'Std Error', 'n1': 'N (Treatment)', 'mean1': 'Mean (Treatment)', 'sd1': 'Std Dev (Treatment)',
              'n2': 'N (Control)', 'mean2': 'Mean (Control)', 'sd2': 'Std Dev (Control)', 'events1': 'Events (Treatment)',
              'total1': 'N (Treatment)', 'events2': 'Events (Control)', 'total2': 'N (Control)'}
IMPORTS = ['from scipy import stats, optimize',
           'from statsmodels.stats.meta_analysis import combine_effects, effectsize_2proportions, effectsize_smd']


# ---- the studies -------------------------------------------------------------------------

def _measure(inp):
    layout = inp.get('layout') or 'es'
    if layout == 'es':
        return 'es_log' if inp.get('log') else 'es'
    m = inp.get('measure')
    if layout == 'cont':
        return m if m in ('smd', 'md') else 'smd'
    return m if m in ('or', 'rr', 'rd') else 'or'


def _cc(inp):
    """The continuity correction: a number added to every cell, 'tac', or None."""
    c = inp.get('cc', 0.5)
    if c in (None, 'none', 0, '0'):
        return None
    if c == 'tac':
        return 'tac'
    try:
        c = float(c)
    except (TypeError, ValueError):
        return 0.5
    return c if c > 0 else None


def _text(v):
    """A label value as the page shows it: whole numbers without '.0'."""
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        if not np.isfinite(v):
            return None
        v = float(v)
        return str(int(v)) if v.is_integer() else f'{v:.6g}'
    return str(v)


class Studies:
    """The studies of a report: page rows, labels, groups, effects and
    variances, and what was left out and why."""

    def __init__(self):
        self.rows = np.zeros(0, dtype=int)
        self.labels, self.groups, self.levels = [], None, []
        self.eff = np.zeros(0)
        self.var = np.zeros(0)
        self.dropped, self.corrected = [], []
        self.counts = None
        self.measure = 'es'
        self.code = []
        self.error = None

    @property
    def k(self):
        return len(self.eff)

    @property
    def se(self):
        return np.sqrt(self.var)

    def subset(self, keep):
        s = Studies()
        keep = np.asarray(keep)
        s.rows, s.eff, s.var = self.rows[keep], self.eff[keep], self.var[keep]
        idx = np.flatnonzero(keep) if keep.dtype == bool else keep
        s.labels = [self.labels[i] for i in idx]
        s.groups = [self.groups[i] for i in idx] if self.groups is not None else None
        s.levels, s.measure = self.levels, self.measure
        if self.counts is not None:
            s.counts = {k: v[keep] for k, v in self.counts.items()}
        return s


def load(table, inp, rows=None):
    """The studies from the columns named in inp (see LAYOUT_ROLES)."""
    S = Studies()
    inp = inp or {}
    layout = inp.get('layout') or 'es'
    if layout not in LAYOUT_ROLES:
        S.error = f'unknown layout {layout!r}'
        return S
    S.measure = _measure(inp)
    names = [inp.get(r) for r in LAYOUT_ROLES[layout]]
    missing = [ROLE_LABEL[r] for r, n in zip(LAYOUT_ROLES[layout], names) if not n]
    if missing:
        S.error = 'cast a column into ' + ', '.join(missing)
        return S
    idx = np.arange(data.TABLES[table]['n']) if rows is None else np.asarray(rows, dtype=int)
    num = {r: data.series(table, n, idx, as_category=False).to_numpy(float) for r, n in zip(LAYOUT_ROLES[layout], names)}
    lab_name, grp_name = inp.get('label'), inp.get('group')
    if lab_name:
        lv = data.series(table, lab_name, idx, as_category=False).tolist()
        labels = [_text(v) or f'Row {r + 1}' for v, r in zip(lv, idx)]
    else:
        labels = [f'Row {r + 1}' for r in idx]
    groups = None
    ok = np.ones(len(idx), dtype=bool)
    reason = [None] * len(idx)

    def drop(mask, why):
        for i in np.flatnonzero(mask & ok):
            reason[i] = why
        ok[mask] = False

    if grp_name:
        g = data.series(table, grp_name, idx, as_category=True)
        gv = [None if (x is None or (isinstance(x, float) and np.isnan(x))) else _text(x) for x in g.tolist()]
        groups = gv
        drop(np.array([x is None for x in gv], dtype=bool), 'missing Group value')
        cats = [_text(c) for c in g.cat.categories] if hasattr(g, 'cat') else sorted({x for x in gv if x is not None})
        S.levels = [c for c in cats if c in set(x for x, o in zip(gv, ok) if o)]
    anymiss = np.zeros(len(idx), dtype=bool)
    for a in num.values():
        anymiss |= ~np.isfinite(a)
    drop(anymiss, 'a missing value')
    corrected = np.zeros(len(idx), dtype=bool)
    eff = np.full(len(idx), np.nan)
    var = np.full(len(idx), np.nan)
    if layout == 'es':
        y, s = num['effect'], num['se']
        drop(~(s > 0), 'the standard error is not above zero' if not inp.get('var') else 'the variance is not above zero')
        eff[ok] = y[ok]
        var[ok] = (s[ok] if inp.get('var') else s[ok] ** 2)
    elif layout == 'cont':
        n1, m1, s1, n2, m2, s2 = (num[r] for r in LAYOUT_ROLES['cont'])
        drop(~((n1 >= 2) & (n2 >= 2)), 'a group has fewer than 2 subjects')
        drop(~((s1 > 0) & (s2 > 0)), 'a standard deviation is not above zero')
        if S.measure == 'smd':
            g_, v_ = effectsize_smd(m1[ok], s1[ok], n1[ok], m2[ok], s2[ok], n2[ok])
            eff[ok], var[ok] = g_, v_
        else:
            eff[ok] = m1[ok] - m2[ok]
            var[ok] = s1[ok] ** 2 / n1[ok] + s2[ok] ** 2 / n2[ok]
    else:
        e1, n1, e2, n2 = (num[r] for r in LAYOUT_ROLES['bin'])
        drop(~((n1 > 0) & (n2 > 0)), 'a group total is not above zero')
        drop(~((e1 >= 0) & (e2 >= 0) & (e1 <= n1) & (e2 <= n2)), 'the events are not between 0 and the total')
        z1 = (e1 == 0) | (e1 == n1)
        z2 = (e2 == 0) | (e2 == n2)
        stat = {'or': 'odds-ratio', 'rr': 'risk-ratio', 'rd': 'diff'}[S.measure]
        cc = _cc(inp)
        if S.measure == 'rd':
            # the risk difference needs a correction only where its variance is zero
            need = z1 & z2
            if cc is None:
                drop(need, 'both proportions are 0 or 1: the variance is zero (no continuity correction)')
        else:
            both = ((e1 == 0) & (e2 == 0)) | ((e1 == n1) & (e2 == n2))
            drop(both, 'no events (or only events) in both groups: no information on a ratio')
            need = z1 | z2
            if cc is None:
                drop(need, 'a zero cell and no continuity correction')
        plain = ok & ~need
        fix = ok & need
        if plain.any():
            eff[plain], var[plain] = effectsize_2proportions(e1[plain], n1[plain], e2[plain], n2[plain], statistic=stat)
        if fix.any():
            eff[fix], var[fix] = effectsize_2proportions(e1[fix], n1[fix], e2[fix], n2[fix], statistic=stat, zero_correction=cc)
            corrected = fix
        S.counts = {'e1': e1, 'n1': n1, 'e2': e2, 'n2': n2}
    drop(~(np.isfinite(eff) & np.isfinite(var) & (var > 0)), 'the effect or its variance is not finite')
    S.dropped = [{'row': int(r), 'reason': why} for r, why, o in zip(idx, reason, ok) if not o]
    S.corrected = [int(r) for r, c, o in zip(idx, corrected, ok) if c and o]
    S.rows = idx[ok]
    S.eff, S.var = eff[ok], var[ok]
    S.labels = [lab for lab, o in zip(labels, ok) if o]
    if groups is not None:
        S.groups = [g_ for g_, o in zip(groups, ok) if o]
    if S.counts is not None:
        S.counts = {k: v[ok] for k, v in S.counts.items()}
    S.code = _code_studies(S, inp, layout, names)
    return S


def _code_studies(S, inp, layout, names):
    """Lines that compute eff and var (and labels) from df, the table as
    exported, for the studies of the report."""
    q = json.dumps
    rows = [int(r) for r in S.rows]
    c = [f'd = df.loc[{rows}]   # the studies of the report: the rows used']
    if layout == 'es':
        c.append(f'eff = d[{q(names[0])}].to_numpy(float)')
        c.append(f'var = d[{q(names[1])}].to_numpy(float)' + ('' if inp.get('var') else ' ** 2   # the standard errors squared'))
    elif layout == 'cont':
        a = ', '.join(f'd[{q(n)}].to_numpy(float)' for n in names)
        c.append(f'n1, m1, s1, n2, m2, s2 = {a}')
        if S.measure == 'smd':
            c.append("eff, var = effectsize_smd(m1, s1, n1, m2, s2, n2)   # Hedges' g, bias corrected, and its variance")
        else:
            c.append('eff, var = m1 - m2, s1 ** 2 / n1 + s2 ** 2 / n2   # the mean difference and its variance')
    else:
        a = ', '.join(f'd[{q(n)}].to_numpy(float)' for n in names)
        stat = {'or': 'odds-ratio', 'rr': 'risk-ratio', 'rd': 'diff'}[S.measure]
        c.append(f'e1, n1, e2, n2 = {a}')
        cc = _cc(inp)
        if S.corrected:
            if S.measure == 'rd':
                c.append('fix = ((e1 == 0) | (e1 == n1)) & ((e2 == 0) | (e2 == n2))   # both proportions 0 or 1')
            else:
                c.append('fix = (e1 == 0) | (e1 == n1) | (e2 == 0) | (e2 == n2)   # a zero cell')
            c.append('eff, var = np.empty(len(d)), np.empty(len(d))')
            c.append(f'eff[~fix], var[~fix] = effectsize_2proportions(e1[~fix], n1[~fix], e2[~fix], n2[~fix], statistic={q(stat)})')
            c.append(f'eff[fix], var[fix] = effectsize_2proportions(e1[fix], n1[fix], e2[fix], n2[fix], statistic={q(stat)}, zero_correction={cc!r})'
                     '   # only these studies: statsmodels would add it to every study\'s counts')
        else:
            c.append(f'eff, var = effectsize_2proportions(e1, n1, e2, n2, statistic={q(stat)})')
    return c


# ---- pooling -----------------------------------------------------------------------------

def _est(est, se, alpha, df=None):
    """An estimate with its interval and test: normal, or t with df."""
    est, se = float(est), float(se)
    if df:
        crit = stats.t.isf(alpha / 2, df)
        stat = est / se if se > 0 else float('nan')
        p = float(2 * stats.t.sf(abs(stat), df)) if se > 0 else float('nan')
    else:
        crit = stats.norm.isf(alpha / 2)
        stat = est / se if se > 0 else float('nan')
        p = float(2 * stats.norm.sf(abs(stat))) if se > 0 else float('nan')
    return {'est': est, 'se': se, 'lower': est - crit * se, 'upper': est + crit * se, 'z': stat, 'p': p, 'df': df}


def _hat(var, X, t2=0.0):
    """W and P = W - W X (X'WX)^-1 X'W for weights 1/(var + t2)."""
    w = 1.0 / (var + t2)
    WX = X * w[:, None]
    A = np.linalg.pinv(X.T @ WX)
    P = np.diag(w) - WX @ A @ WX.T
    return w, P


def tau2_dl(eff, var, X=None):
    """The method-of-moments (DerSimonian-Laird) tau^2, with covariates the
    generalisation of Raudenbush (2009): (Q_E - (k - p)) / tr(P), at least 0."""
    X = np.ones((len(eff), 1)) if X is None else X
    k, p = X.shape
    _, P = _hat(var, X)
    qe = float(eff @ P @ eff)
    return max(0.0, (qe - (k - p)) / float(np.trace(P)))


def _root(f, grow_from):
    """The root of a decreasing function f on [0, inf) with f(0) > 0."""
    hi = max(grow_from, 1e-8)
    for _ in range(200):
        if f(hi) < 0:
            break
        hi *= 4
    return float(optimize.brentq(f, 0.0, hi, xtol=1e-14, rtol=1e-12, maxiter=500))


def tau2_pm(eff, var, X=None):
    """Paule-Mandel: tau^2 with the generalised Q equal to its degrees of freedom."""
    X = np.ones((len(eff), 1)) if X is None else X
    k, p = X.shape

    def f(t2):
        _, P = _hat(var, X, t2)
        return float(eff @ P @ eff) - (k - p)

    if f(0.0) <= 0:
        return 0.0
    return _root(f, 10 * float(np.var(eff)) + float(np.max(var)))


def tau2_reml(eff, var, X=None):
    """REML: the root of the restricted log likelihood's score in tau^2,
    y'PPy - tr(P) (Viechtbauer 2005), or 0 when the score is negative there."""
    X = np.ones((len(eff), 1)) if X is None else X

    def score(t2):
        _, P = _hat(var, X, t2)
        Py = P @ eff
        return float(Py @ Py - np.trace(P))

    if score(0.0) <= 0:
        return 0.0
    return _root(score, 10 * float(np.var(eff)) + float(np.max(var)))


def _ce(eff, var, method, alpha):
    """combine_effects. With a DerSimonian-Laird tau^2 below zero it takes
    square roots of negative variances and warns; those numbers are the ones
    replaced here (random = fixed), so those warnings are dropped; any other
    warning goes on to the report."""
    import warnings
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        if method == 'pm':
            res = combine_effects(eff, var, method_re='iterated', alpha=alpha)
        else:
            res = combine_effects(eff, var, method_re='chi2', alpha=alpha)
    for w in caught:
        if res.tau2 < 0 and issubclass(w.category, RuntimeWarning) and 'sqrt' in str(w.message):
            continue
        # Q = 0 (identical effects): statsmodels' i2 = 1 - 1/h2 divides by
        # zero; I^2 is 0 then, as pool() reports it
        if res.q == 0 and issubclass(w.category, RuntimeWarning) and 'divide by zero' in str(w.message):
            continue
        warnings.warn_explicit(w.message, w.category, w.filename, w.lineno)
    return res


def pool(eff, var, method='dl', alpha=0.05, hksj=False, X1=None):
    """The fixed effect and the random effects of one method, statsmodels'
    numbers: {'fe', 're', 'tau2', 'w_fe', 'w_re', 'q', 'df', 'p', 'i2', 'h2',
    'raw_tau2', 'res'}. hksj: the random-effects interval of Hartung-Knapp."""
    eff = np.asarray(eff, dtype=float)
    var = np.asarray(var, dtype=float)
    k = len(eff)
    if k == 1:
        one = _est(eff[0], math.sqrt(var[0]), alpha)
        return {'k': 1, 'fe': one, 're': dict(one), 're_hk': None, 're_show': dict(one), 'tau2': 0.0, 'raw_tau2': None, 'w_fe': np.ones(1),
                'w_re': np.ones(1), 'q': 0.0, 'df': 0, 'p': None, 'i2': None, 'h2': None, 'res': None}
    res = _ce(eff, var, 'pm' if method == 'pm' else 'dl', alpha)
    fe = _est(res.mean_effect_fe, res.sd_eff_w_fe, alpha)
    i2 = float(res.i2)
    out = {'k': k, 'fe': fe, 'res': res, 'q': float(res.q), 'df': k - 1, 'p': float(res.test_homogeneity().pvalue),
           'i2': i2 if np.isfinite(i2) else 0.0, 'h2': float(res.h2), 'w_fe': np.asarray(res.weights_rel_fe, dtype=float)}
    if method in ('dl', 'pm'):
        raw = float(res.tau2)
        if raw > 0:
            out['re'] = _est(res.mean_effect_re, res.sd_eff_w_re, alpha)
            out['re_hk'] = _est(res.mean_effect_re, res.sd_eff_w_re_hksj, alpha, df=k - 1)
            out['w_re'] = np.asarray(res.weights_rel_re, dtype=float)
        else:
            # tau^2 = 0: the random-effects model is the fixed-effect one
            out['re'] = dict(fe)
            out['re_hk'] = _est(res.mean_effect_fe, res.sd_eff_w_fe_hksj, alpha, df=k - 1)
            out['w_re'] = out['w_fe'].copy()
        out['tau2'] = max(0.0, raw)
        out['raw_tau2'] = raw
    else:
        t2 = tau2_reml(eff, var)
        X = np.ones((k, 1))
        f = sm.WLS(eff, X, weights=1.0 / (var + t2)).fit(cov_type='fixed scale')
        out['re'] = _est(f.params[0], f.bse[0], alpha)
        f2 = sm.WLS(eff, X, weights=1.0 / (var + t2)).fit()   # the scale estimated: Hartung-Knapp
        out['re_hk'] = _est(f2.params[0], f2.bse[0], alpha, df=k - 1)
        w = 1.0 / (var + t2)
        out['w_re'] = w / w.sum()
        out['tau2'] = t2
        out['raw_tau2'] = t2
    if hksj:
        out['re_show'] = out['re_hk']
    else:
        out['re_show'] = out['re']
    return out


def _h_i2_ci(q, k, alpha):
    """H and I^2 with Higgins & Thompson's (2002) interval for ln H, as R's
    meta package reports them; H at least 1, I^2 at least 0."""
    df = k - 1
    if k < 3 or not q > 0:
        return None
    H = math.sqrt(q / df)
    if q > k:
        se = 0.5 * (math.log(q) - math.log(k - 1)) / (math.sqrt(2 * q) - math.sqrt(2 * k - 3))
    else:
        se = math.sqrt(1 / (2 * (k - 2)) * (1 - 1 / (3 * (k - 2) ** 2)))
    z = stats.norm.isf(alpha / 2)
    lo, hi = math.exp(math.log(H) - z * se), math.exp(math.log(H) + z * se)
    i2 = lambda h: (h * h - 1) / (h * h)   # noqa: E731
    H, lo, hi = max(H, 1.0), max(lo, 1.0), max(hi, 1.0)
    return {'h': H, 'h_lower': lo, 'h_upper': hi, 'i2': i2(H), 'i2_lower': i2(lo), 'i2_upper': i2(hi)}


def qgen(eff, var, t2):
    """The generalised Q: sum of w (y - mean_w)^2 with w = 1/(v + tau^2)."""
    w = 1.0 / (var + t2)
    m = float(w @ eff / w.sum())
    return float(w @ (eff - m) ** 2)


def tau2_qprofile(eff, var, alpha):
    """Viechtbauer's (2007) Q-profile interval for tau^2 (metafor's default)."""
    k = len(eff)
    if k < 2:
        return None, None
    q0 = qgen(eff, var, 0.0)
    out = []
    for crit in (stats.chi2.isf(alpha / 2, k - 1), stats.chi2.ppf(alpha / 2, k - 1)):
        if q0 <= crit:
            out.append(0.0)
        else:
            out.append(_root(lambda t, c=crit: qgen(eff, var, t) - c, 10 * float(np.var(eff)) + float(np.max(var))))
    return out[0], out[1]


def _code_pool(method, alpha, hksj=False):
    """Lines that pool eff and var as the report does (the random effects of `method`)."""
    c = [f'res = combine_effects(eff, var, method_re="chi2", row_names=labels, alpha={alpha!r})   # fixed effect; DerSimonian-Laird random effects',
         f'pm = combine_effects(eff, var, method_re="iterated", alpha={alpha!r})   # Paule-Mandel',
         'print(res.summary_frame())',
         'k, fe, se_fe = len(eff), res.mean_effect_fe, res.sd_eff_w_fe',
         '# DerSimonian-Laird is max(0, (Q - df)/C); statsmodels leaves it negative when Q < df, and then random = fixed',
         'dl = (res.mean_effect_re, res.sd_eff_w_re, res.tau2) if res.tau2 > 0 else (fe, se_fe, 0.0)',
         'pm_ = (pm.mean_effect_re, pm.sd_eff_w_re, pm.tau2) if pm.tau2 > 0 else (fe, se_fe, 0.0)',
         'def reml_score(t2):   # the REML score in tau^2 (y\'PPy - tr P), zero at the REML estimate',
         '    w = 1 / (var + t2); m = w @ eff / w.sum()',
         '    return (w ** 2) @ (eff - m) ** 2 - w.sum() + (w ** 2).sum() / w.sum()',
         't2 = 0.0 if reml_score(0) <= 0 else optimize.brentq(reml_score, 0, 100 * (eff.var() + var.max()), xtol=1e-14)',
         'fit = sm.WLS(eff, np.ones(k), weights=1 / (var + t2)).fit(cov_type="fixed scale")',
         'reml = (fit.params[0], fit.bse[0], t2)',
         'print(res.test_homogeneity())   # Q, its p-value and df',
         f'est, se, tau2 = {{"dl": dl, "pm": pm_, "reml": reml}}[{method!r}]',
         f't = stats.t.isf({alpha / 2!r}, k - 2); print("prediction interval", est - t * np.sqrt(tau2 + se ** 2), est + t * np.sqrt(tau2 + se ** 2))',
         'print(fe, se_fe, dl[0], dl[1], dl[2], pm_[0], pm_[2], reml[0], reml[2])']
    if hksj:
        # Hartung-Knapp: the WLS scale and t with k - 1 degrees of freedom (summary_frame's "wls" rows use the normal quantile)
        c += ['hk_dl = res.conf_int(alpha=%r, use_t=True)[3] if res.tau2 > 0 else res.conf_int(alpha=%r, use_t=True)[2]' % (alpha, alpha),
              'hk_pm = pm.conf_int(alpha=%r, use_t=True)[3] if pm.tau2 > 0 else pm.conf_int(alpha=%r, use_t=True)[2]' % (alpha, alpha),
              'hk_reml = sm.WLS(eff, np.ones(k), weights=1 / (var + t2)).fit().conf_int(alpha=%r)[0]   # the scale estimated: t on k - 1 df' % alpha,
              'print("Hartung-Knapp", *hk_dl, *hk_pm, *hk_reml)']
    return c


def _code_pooled_fn(method, alpha, hksj):
    """A Python function pooled(eff, var) -> (estimate, std error, tau2) for
    the random effects of the report, for the loops of leave-one-out and
    cumulative meta-analysis."""
    name = METHODS[method]
    if method in ('dl', 'pm'):
        mre = 'chi2' if method == 'dl' else 'iterated'
        se_re, se_fe = ('r.sd_eff_w_re_hksj', 'r.sd_eff_w_fe_hksj') if hksj else ('r.sd_eff_w_re', 'r.sd_eff_w_fe')
        return [f'def pooled(eff, var):   # the random effects of the report ({name}{", Hartung-Knapp" if hksj else ""}): estimate, std error, tau2',
                '    if len(eff) == 1:',
                '        return eff[0], np.sqrt(var[0]), 0.0   # one study is its own estimate',
                f'    r = combine_effects(eff, var, method_re="{mre}", alpha={alpha!r})',
                f'    return (r.mean_effect_re, {se_re}, r.tau2) if r.tau2 > 0 else (r.mean_effect_fe, {se_fe}, 0.0)']
    return [f'def pooled(eff, var):   # the random effects of the report (REML{", Hartung-Knapp" if hksj else ""}): estimate, std error, tau2',
            '    if len(eff) == 1:',
            '        return eff[0], np.sqrt(var[0]), 0.0   # one study is its own estimate',
            '    def score(t2):',
            '        w = 1 / (var + t2); m = w @ eff / w.sum()',
            '        return (w ** 2) @ (eff - m) ** 2 - w.sum() + (w ** 2).sum() / w.sum()',
            '    t2 = 0.0 if score(0) <= 0 else optimize.brentq(score, 0, 100 * (eff.var() + var.max()), xtol=1e-14)',
            f'    fit = sm.WLS(eff, np.ones(len(eff)), weights=1 / (var + t2)).fit({"" if hksj else "cov_type=" + json.dumps("fixed scale")})',
            '    return fit.params[0], fit.bse[0], t2']


def _label_line(S, inp):
    lab = inp.get('label')
    if lab:
        return f'labels = d[{json.dumps(lab)}].astype(str).tolist()'
    return 'labels = [f"Row {i + 1}" for i in d.index]'


def _disp(measure, x):
    if x is None or not np.isfinite(x):
        return None
    return math.exp(x) if MEASURES[measure][3] else float(x)


def _with_disp(measure, d):
    """An estimate dict with the back-transformed values of a log measure."""
    if MEASURES[measure][3]:
        d = dict(d)
        d['ratio'], d['ratio_lower'], d['ratio_upper'] = (_disp(measure, d.get(k)) for k in ('est' if 'est' in d else 'eff', 'lower', 'upper'))
    return d


def _mh(S, alpha):
    """Mantel-Haenszel odds ratio (statsmodels StratifiedTable), with the
    Robins-Breslow-Greenland standard error."""
    from statsmodels.stats.contingency_tables import StratifiedTable
    c = S.counts
    tabs = [np.array([[a, n - a], [b, m - b]], dtype=float) for a, n, b, m in zip(c['e1'], c['n1'], c['e2'], c['n2'])]
    if len(tabs) < 1:
        return None
    try:
        st = StratifiedTable(tabs)
        lo = float(st.logodds_pooled)
        se = float(st.logodds_pooled_se)
    except Exception:   # a degenerate set of tables
        return None
    if not (np.isfinite(lo) and np.isfinite(se) and se > 0):
        return None
    out = _est(lo, se, alpha)
    ci = st.logodds_pooled_confint(alpha)
    out['lower'], out['upper'] = float(ci[0]), float(ci[1])
    try:
        bd = st.test_equal_odds()
        out['breslow_day'] = {'stat': float(bd.statistic), 'p': float(bd.pvalue), 'df': len(tabs) - 1}
    except Exception:
        out['breslow_day'] = None
    return out


# ---- the report's main call ---------------------------------------------------------------

@api('meta.combine')
def combine(table, inputs, rows=None, method='dl', alpha=0.05, hksj=False, table_name='data'):
    """Everything the forest plot, the summary estimates, the heterogeneity
    and the subgroups need."""
    S = load(table, inputs, rows)
    m = S.measure
    head = {'measure': _measure_info(m), 'dropped': S.dropped, 'corrected': S.corrected, 'k': S.k, 'method': method,
            'method_label': METHODS.get(method, method), 'alpha': alpha, 'hksj': bool(hksj)}
    if S.error:
        return {**head, 'error': S.error}
    if S.k == 0:
        return {**head, 'error': 'no study has the values it needs' + (f' ({S.dropped[0]["reason"]}, …)' if S.dropped else '')}
    k = S.k
    P = {meth: pool(S.eff, S.var, meth, alpha, hksj) for meth in METHODS}
    ch = P[method]
    se = S.se
    zc = stats.norm.isf(alpha / 2)
    studies = []
    for i in range(k):
        e, s = float(S.eff[i]), float(se[i])
        st = {'row': int(S.rows[i]), 'label': S.labels[i], 'group': S.groups[i] if S.groups is not None else None,
              'eff': e, 'se': s, 'var': float(S.var[i]), 'lower': e - zc * s, 'upper': e + zc * s,
              'w_fe': float(ch['w_fe'][i]), 'w_re': float(ch['w_re'][i]), 'z': e / s, 'p': float(2 * stats.norm.sf(abs(e / s)))}
        studies.append(_with_disp(m, st))
    pooled = [dict(_with_disp(m, P['dl']['fe']), key='fe', model='Fixed effect', method='Inverse variance', tau2=None)]
    mh = _mh(S, alpha) if m == 'or' else None
    if mh:
        c = S.counts
        wmh = (c['n1'] - c['e1']) * c['e2'] / (c['n1'] + c['n2'])   # b c / n: the Mantel-Haenszel weights
        if wmh.sum() > 0:
            for st_, wv in zip(studies, wmh / wmh.sum()):
                st_['w_mh'] = float(wv)
    if mh:
        pooled.append(dict(_with_disp(m, mh), key='mh', model='Fixed effect', method='Mantel–Haenszel', tau2=None))
    for meth, lab in METHODS.items():
        pooled.append(dict(_with_disp(m, P[meth]['re']), key=meth, model='Random effects', method=lab, tau2=P[meth]['tau2']))
    hk = [dict(_with_disp(m, P[meth]['re_hk']), key=meth, model='Random effects, Hartung–Knapp', method=lab, tau2=P[meth]['tau2'])
          for meth, lab in METHODS.items() if P[meth].get('re_hk')] if k >= 2 else []
    het = {'q': P['dl']['q'], 'df': k - 1, 'p': P['dl']['p'], 'i2_raw': P['dl']['i2'], 'h2_raw': P['dl']['h2']}
    if k >= 2:
        het['i2'] = max(0.0, P['dl']['i2'])
        het['h'] = math.sqrt(max(1.0, P['dl']['h2']))
        ci = _h_i2_ci(P['dl']['q'], k, alpha)
        if ci:
            het.update({'i2_lower': ci['i2_lower'], 'i2_upper': ci['i2_upper'], 'h_lower': ci['h_lower'], 'h_upper': ci['h_upper']})
        lo, hi = tau2_qprofile(S.eff, S.var, alpha)
        het.update({'tau2': ch['tau2'], 'tau': math.sqrt(ch['tau2']), 'tau2_lower': lo, 'tau2_upper': hi,
                    'tau_lower': math.sqrt(lo) if lo is not None else None, 'tau_upper': math.sqrt(hi) if hi is not None else None})
        w = 1.0 / S.var
        het['s2'] = (k - 1) * w.sum() / (w.sum() ** 2 - (w ** 2).sum())   # the typical within-study variance
    pi = None
    if k >= 3:
        re = ch['re']
        t = stats.t.isf(alpha / 2, k - 2)
        half = t * math.sqrt(ch['tau2'] + re['se'] ** 2)
        pi = _with_disp(m, {'est': re['est'], 'lower': re['est'] - half, 'upper': re['est'] + half, 'df': k - 2})
    out = {**head, 'studies': studies, 'pooled': pooled, 'hksj_rows': hk,
           'chosen': {'fe': _with_disp(m, ch['fe']), 're': _with_disp(m, ch['re_show']), 're_z': _with_disp(m, ch['re']), 'tau2': ch['tau2']},
           'het': het, 'pi': pi, 'mh': mh, 'raw_tau2_dl': P['dl']['raw_tau2']}
    if S.groups is not None:
        out['subgroups'] = _subgroups(S, method, alpha, hksj)
    lines = [code_head(table_name, IMPORTS)] + S.code + [_label_line(S, inputs)] + _code_pool(method, alpha, hksj)
    out['code'] = '\n'.join(lines)
    return out


def _measure_info(m):
    eff, disp, plural, log = MEASURES[m]
    return {'key': m, 'effect': eff, 'display': disp, 'plural': plural, 'log': log, 'null': 1.0 if log else 0.0}


def _subgroups(S, method, alpha, hksj):
    groups = []
    fe_est, fe_var, re_est, re_var = [], [], [], []
    for lv in S.levels:
        keep = np.array([g == lv for g in S.groups], dtype=bool)
        if not keep.any():
            continue
        s = S.subset(keep)
        p = pool(s.eff, s.var, method, alpha, hksj)
        mh = _mh(s, alpha) if S.measure == 'or' else None
        g = {'level': lv, 'k': s.k, 'rows': [int(r) for r in s.rows], 'fe': _with_disp(S.measure, p['fe']), 're': _with_disp(S.measure, p['re_show']),
             'mh': _with_disp(S.measure, mh) if mh else None,
             'q': p['q'], 'df': p['df'], 'p': p['p'], 'i2': max(0.0, p['i2']) if p['i2'] is not None else None, 'tau2': p['tau2']}
        groups.append(g)
        fe_est.append(p['fe']['est'])
        fe_var.append(p['fe']['se'] ** 2)
        re_est.append(p['re']['est'])
        re_var.append(p['re']['se'] ** 2)
    tests = []
    if len(groups) >= 2:
        # Q between: statsmodels' Q of the subgroup estimates; for the fixed
        # effect it is Q total minus the Q within the subgroups
        for label, e, v in (('Fixed effect', fe_est, fe_var), (f'Random effects ({METHODS[method]})', re_est, re_var)):
            r = combine_effects(np.array(e), np.array(v), method_re='chi2', alpha=alpha)
            qb = float(r.q)
            df = len(e) - 1
            tests.append({'model': label, 'q': qb, 'df': df, 'p': float(stats.chi2.sf(qb, df)), 'i2': max(0.0, (qb - df) / qb) if qb > 0 else 0.0})
    return {'groups': groups, 'tests': tests}


# ---- small-study effects -----------------------------------------------------------------

@api('meta.bias')
def bias(table, inputs, rows=None, method='dl', alpha=0.05, table_name='data'):
    """The funnel plot's points; Egger's regression test and Begg's rank
    correlation."""
    S = load(table, inputs, rows)
    if S.error or S.k == 0:
        return {'error': S.error or 'no studies'}
    k = S.k
    se = S.se
    p = pool(S.eff, S.var, method, alpha)
    out = {'k': k, 'measure': _measure_info(S.measure), 'rows': [int(r) for r in S.rows], 'labels': S.labels,
           'eff': S.eff.tolist(), 'se': se.tolist(), 'fe': p['fe']['est'], 're': p['re']['est'], 'w_re': p['w_re'].tolist()}
    if k >= 3 and np.ptp(se) <= 1e-12 * float(np.max(se)):
        out['same_se'] = True   # the precision is constant: no regression on it, no rank correlation with the variance
    elif k >= 3:
        ols = sm.OLS(S.eff / se, sm.add_constant(1.0 / se)).fit()
        ci = ols.conf_int(alpha)
        out['egger'] = {'intercept': float(ols.params[0]), 'se': float(ols.bse[0]), 't': float(ols.tvalues[0]), 'p': float(ols.pvalues[0]),
                        'lower': float(ci[0, 0]), 'upper': float(ci[0, 1]), 'slope': float(ols.params[1]), 'slope_se': float(ols.bse[1]),
                        'slope_t': float(ols.tvalues[1]), 'slope_p': float(ols.pvalues[1]), 'slope_lower': float(ci[1, 0]), 'slope_upper': float(ci[1, 1]),
                        'df': float(ols.df_resid)}
        vfe = 1.0 / np.sum(1.0 / S.var)
        tstar = (S.eff - p['fe']['est']) / np.sqrt(S.var - vfe)
        kt = stats.kendalltau(tstar, S.var)
        out['begg'] = {'tau': float(kt.statistic), 'p': float(kt.pvalue), 'n': k}
    c = [code_head(table_name, IMPORTS)] + S.code + [
        'se = np.sqrt(var)',
        'egger = sm.OLS(eff / se, sm.add_constant(1 / se)).fit()   # the standardized effect on the precision',
        f'print(egger.summary(alpha={alpha!r}))   # the intercept (const) is the small-study bias',
        'fe = (eff / var).sum() / (1 / var).sum()',
        'tstar = (eff - fe) / np.sqrt(var - 1 / (1 / var).sum())   # Begg and Mazumdar\'s standardized effects',
        'print(stats.kendalltau(tstar, var))',
        'print(egger.params[0], egger.bse[0], egger.pvalues[0])']
    out['code'] = '\n'.join(c)
    return out


# ---- sensitivity ---------------------------------------------------------------------------

@api('meta.leave_one_out')
def leave_one_out(table, inputs, rows=None, method='dl', alpha=0.05, hksj=False, table_name='data'):
    S = load(table, inputs, rows)
    if S.error or S.k == 0:
        return {'error': S.error or 'no studies'}
    k = S.k
    if k < 3:
        return {'error': 'leave-one-out needs three studies or more'}
    m = S.measure
    out = []
    for i in range(k):
        keep = np.ones(k, dtype=bool)
        keep[i] = False
        p = pool(S.eff[keep], S.var[keep], method, alpha, hksj)
        r = _with_disp(m, p['re_show'])
        out.append({'row': int(S.rows[i]), 'label': S.labels[i], **r, 'fe': p['fe']['est'], 'tau2': p['tau2'],
                    'i2': max(0.0, p['i2']) if p['i2'] is not None else None, 'q': p['q'], 'q_p': p['p']})
    full = pool(S.eff, S.var, method, alpha, hksj)
    c = [code_head(table_name, IMPORTS)] + S.code + [_label_line(S, inputs)] + _code_pooled_fn(method, alpha, hksj) + [
        'for i in range(len(eff)):   # each study left out in turn',
        '    keep = np.arange(len(eff)) != i',
        '    print(labels[i], *pooled(eff[keep], var[keep]))']
    return {'measure': _measure_info(m), 'rows': out, 'full': _with_disp(m, full['re_show']), 'method': method, 'hksj': bool(hksj), 'code': '\n'.join(c)}


@api('meta.cumulative')
def cumulative(table, inputs, rows=None, order_by=None, descending=False, method='dl', alpha=0.05, hksj=False, table_name='data'):
    """The pooled estimate as the studies come in, in the order of a column."""
    S = load(table, inputs, rows)
    if S.error or S.k == 0:
        return {'error': S.error or 'no studies'}
    m = S.measure
    k = S.k
    levels = None
    if order_by:
        s = data.series(table, order_by, S.rows, as_category=True)
        if hasattr(s, 'cat'):
            levels = list(s.cat.categories)
            key = s.cat.codes.to_numpy(float)
            key[key < 0] = np.nan
            shown = [_text(v) for v in s.tolist()]
        else:
            key = s.to_numpy(float)
            shown = [_text(v) for v in key]
    else:
        key = np.arange(k, dtype=float)
        shown = [str(int(r) + 1) for r in S.rows]
    miss = ~np.isfinite(key)
    kk = np.where(miss, np.inf, -key if descending else key)
    order = np.lexsort((np.arange(k), kk))   # by the column, ties in row order; missing last
    out = []
    for j in range(1, k + 1):
        sel = order[:j]
        p = pool(S.eff[sel], S.var[sel], method, alpha, hksj)
        i = order[j - 1]
        r = _with_disp(m, p['re_show'])
        out.append({'row': int(S.rows[i]), 'label': S.labels[i], 'value': shown[i], 'k': j, **r, 'fe': p['fe']['est'], 'tau2': p['tau2'],
                    'i2': max(0.0, p['i2']) if p['i2'] is not None else None})
    q = json.dumps
    if order_by and levels is not None:
        keyline = [f'key = pd.Categorical(d[{q(order_by)}], categories={_py_levels(levels)}).codes.astype(float)   # the level order of the table',
                   'key[key < 0] = np.nan']
    elif order_by:
        keyline = [f'key = d[{q(order_by)}].to_numpy(float)']
    else:
        keyline = ['key = np.arange(len(eff), dtype=float)   # row order']
    if descending:
        keyline.append('key = -key   # descending')
    c = [code_head(table_name, IMPORTS)] + S.code + [_label_line(S, inputs)] + _code_pooled_fn(method, alpha, hksj) + keyline + [
        'order = np.lexsort((np.arange(len(key)), np.where(np.isnan(key), np.inf, key)))   # ties in row order, missing last',
        'for j in range(1, len(eff) + 1):   # the first j studies',
        '    sel = order[:j]',
        '    print(j, labels[sel[-1]], *pooled(eff[sel], var[sel]))']
    return {'measure': _measure_info(m), 'rows': out, 'order_by': order_by, 'descending': bool(descending), 'method': method, 'hksj': bool(hksj),
            'n_missing_order': int(miss.sum()), 'code': '\n'.join(c)}


# ---- meta-regression -----------------------------------------------------------------------

@api('meta.regression')
def regression(table, inputs, covariates=None, rows=None, method='dl', alpha=0.05, hksj=False, table_name='data'):
    """Weighted least squares of the effects on study-level covariates with
    the random-effects weights 1/(v + tau^2), tau^2 the residual
    between-study variance of the chosen method (a mixed-effects
    meta-regression, as metafor's rma with mods)."""
    from . import models
    import patsy
    S = load(table, inputs, rows)
    if S.error or S.k == 0:
        return {'error': S.error or 'no studies'}
    covariates = [c for c in (covariates or []) if c]
    if not covariates:
        return {'error': 'choose one or more covariates'}
    d = models.build(table, None, [[c] for c in covariates], rows=[int(r) for r in S.rows], center=False, coding='treatment')
    keep = np.isin(S.rows, d.df.index.to_numpy())
    n_dropped = int((~keep).sum())
    s = S.subset(keep)
    X0 = patsy.dmatrix(d.rhs, d.df, return_type='dataframe')
    X = X0.loc[s.rows]
    names = [d.label(c) for c in X.columns]
    Xa = X.to_numpy(float)
    k, p = Xa.shape
    if k <= p:
        return {'error': f'{k} studies with the covariates for {p} coefficients: too few'}
    if np.linalg.matrix_rank(Xa) < p:
        return {'error': 'the covariates are collinear (or a level has no study)'}
    t2 = {'dl': tau2_dl, 'pm': tau2_pm, 'reml': tau2_reml}[method](s.eff, s.var, Xa)
    t2_0 = {'dl': tau2_dl, 'pm': tau2_pm, 'reml': tau2_reml}[method](s.eff, s.var, None)
    w = 1.0 / (s.var + t2)
    fit = sm.WLS(s.eff, Xa, weights=w).fit(cov_type='fixed scale')
    fit_hk = sm.WLS(s.eff, Xa, weights=w).fit()
    use = fit_hk if hksj else fit
    ci = use.conf_int(alpha)
    est = [{'term': nm, 'est': float(b), 'se': float(e), 'z': float(t), 'p': float(pv), 'lower': float(ci[i, 0]), 'upper': float(ci[i, 1])}
           for i, (nm, b, e, t, pv) in enumerate(zip(names, use.params, use.bse, use.tvalues, use.pvalues))]
    fe0 = sm.WLS(s.eff, Xa, weights=1.0 / s.var).fit()
    qe = float(np.sum(fe0.wresid ** 2))   # the residual heterogeneity Q_E: sum of w e^2 at tau^2 = 0
    _, P0 = _hat(s.var, Xa)
    s2 = (k - p) / float(np.trace(P0))
    out = {'k': k, 'p': p, 'n_dropped': n_dropped, 'terms': est, 'tau2': t2, 'tau2_0': t2_0, 'i2': t2 / (t2 + s2) if t2 + s2 > 0 else 0.0,
           'r2': max(0.0, (t2_0 - t2) / t2_0) if t2_0 > 0 else None, 'qe': qe, 'qe_df': k - p, 'qe_p': float(stats.chi2.sf(qe, k - p)),
           'method': method, 'hksj': bool(hksj), 'measure': _measure_info(S.measure), 'rows': [int(r) for r in s.rows], 'labels': s.labels, 'eff': s.eff.tolist(),
           'w': (w / w.sum()).tolist()}
    if p > 1:
        R = np.eye(p)[1:]
        if hksj:
            ft = fit_hk.f_test(R)
            out['qm'] = {'stat': float(np.squeeze(ft.fvalue)), 'df': int(ft.df_num), 'df_den': int(ft.df_denom), 'p': float(ft.pvalue), 'test': 'F'}
        else:
            wt = fit.wald_test(R, scalar=True)
            out['qm'] = {'stat': float(wt.statistic), 'df': p - 1, 'p': float(wt.pvalue), 'test': 'ChiSquare'}
    # the bubble plots: each continuous covariate, the others at their means (or first level)
    curves = []
    V = use.cov_params()
    crit = stats.t.isf(alpha / 2, k - p) if hksj else stats.norm.isf(alpha / 2)
    for cname in covariates:
        a = d.alias[cname]
        if a in d.categorical:
            continue
        xv = d.df.loc[s.rows, a].to_numpy(float)
        grid = np.linspace(float(np.min(xv)), float(np.max(xv)), 60)
        fr = d.frame_for({cname: grid})
        Xn = np.asarray(patsy.build_design_matrices([X0.design_info], fr)[0])
        yhat = Xn @ use.params
        sehat = np.sqrt(np.einsum('ij,jk,ik->i', Xn, V, Xn))
        curves.append({'covariate': cname, 'x': xv.tolist(), 'grid': grid.tolist(), 'fit': yhat.tolist(),
                       'lower': (yhat - crit * sehat).tolist(), 'upper': (yhat + crit * sehat).tolist()})
    out['curves'] = curves
    q = json.dumps
    c = [code_head(table_name, IMPORTS + ['import patsy'])] + S.code + [
        f'X = patsy.dmatrix({q(_formula(d, covariates))}, d, return_type="dataframe")   # nominal covariates dummy coded against their first level',
        'pos = d.index.get_indexer(X.index)   # the studies with every covariate',
        'X, eff, var = X.to_numpy(float), eff[pos], var[pos]',
        'def P(t2):   # W - W X (X\'WX)^-1 X\'W with the weights 1/(v + t2)',
        '    w = 1 / (var + t2); WX = X * w[:, None]',
        '    return np.diag(w) - WX @ np.linalg.pinv(X.T @ WX) @ WX.T',
        'k, p = X.shape']
    if method == 'dl':
        c.append('tau2 = max(0, (eff @ P(0) @ eff - (k - p)) / np.trace(P(0)))   # method of moments (DerSimonian-Laird)')
    elif method == 'pm':
        c += ['f = lambda t2: eff @ P(t2) @ eff - (k - p)   # Paule-Mandel: the generalised Q equals its df',
              'tau2 = 0.0 if f(0) <= 0 else optimize.brentq(f, 0, 100 * (eff.var() + var.max()), xtol=1e-14)']
    else:
        c += ['score = lambda t2: (P(t2) @ eff) @ (P(t2) @ eff) - np.trace(P(t2))   # REML score',
              'tau2 = 0.0 if score(0) <= 0 else optimize.brentq(score, 0, 100 * (eff.var() + var.max()), xtol=1e-14)']
    c += [f'fit = sm.WLS(eff, X, weights=1 / (var + tau2)).fit({"" if hksj else "cov_type=" + q("fixed scale")})'
          + ('   # the scale estimated: Knapp-Hartung' if hksj else '   # the scale fixed at 1: z tests'),
          f'print(tau2); print(fit.summary(alpha={alpha!r}))']
    out['code'] = '\n'.join(c)
    return out


def _formula(d, covariates):
    parts = []
    for cname in covariates:
        a = d.alias[cname]
        qn = f'Q({json.dumps(cname)})'
        if a in d.categorical:
            lv = d.levels[a]
            parts.append(f'C({qn}, levels={_py_levels(lv)})')
        else:
            parts.append(qn)
    return ' + '.join(parts)


def _py_levels(lv):
    return '[' + ', '.join(repr(float(v)) if isinstance(v, (float, int, np.floating, np.integer)) else repr(str(v)) for v in lv) + ']'


# ---- save columns ------------------------------------------------------------------------

@api('meta.save')
def save(table, inputs, rows=None, method='dl', alpha=0.05):
    """Per-study values for Save Columns: the effect, its standard error and
    variance, the interval and the weights."""
    S = load(table, inputs, rows)
    if S.error or S.k == 0:
        return {'error': S.error or 'no studies'}
    p = pool(S.eff, S.var, method, alpha)
    zc = stats.norm.isf(alpha / 2)
    se = S.se
    return {'rows': [int(r) for r in S.rows], 'eff': S.eff.tolist(), 'se': se.tolist(), 'var': S.var.tolist(),
            'lower': (S.eff - zc * se).tolist(), 'upper': (S.eff + zc * se).tolist(),
            'w_fe': (100 * p['w_fe']).tolist(), 'w_re': (100 * p['w_re']).tolist(), 'measure': _measure_info(S.measure)}
