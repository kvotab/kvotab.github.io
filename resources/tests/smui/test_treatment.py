#!/usr/bin/env python3
"""Analyze > Specialized Modeling > Treatment Effects' backend
(resources/py/smui/treatment.py), checked

  * against statsmodels called directly: Logit and Probit for the
    propensity model, TreatmentEffect's ipw, aipw, aipw_wls, ra and ipw_ra
    (with effect_group=1 for the effect on the treated), OLS with HC0 for the
    outcome models, CompareMeans for the difference in means;
  * against formulas written here: the IPW (normalised) estimator and its
    potential-outcome means, RA, AIPW, IPW-RA and AIPW (WLS) as averages of
    fitted values, the effects on the treated, standardized mean differences
    and variance ratios before and after weighting, the weights and their
    effective sizes, the common support, the trimming;
  * against the M-estimation sandwich written here with analytic
    derivatives (IPW, RA, AIPW, IPW-RA and IPW's effect on the treated): the
    GMM standard errors statsmodels computes by numerical derivatives, on the
    standardized designs the page gives it;
  * on simulated data with a known effect: the adjusted estimates are close
    to the true ATE and ATT, the unadjusted difference is not.

It also shows why the page standardizes the designs (statsmodels' GMM
Jacobian takes a fixed step of 1e-4, too coarse for a covariate in large
units) and why it carries its own AIPW (WLS) and IPW-RA moment classes
(statsmodels 0.14.6 slices the propensity parameters as params[-6:]): with a
six-parameter propensity model the page's classes give statsmodels' own
numbers. The Python under each result runs on the table exported as CSV
and gives the report's numbers.

    python3 resources/tests/smui/test_treatment.py
"""
import contextlib
import inspect
import io
import math
import os
import sys
import tempfile

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.treatment.treatment_effects as te
from statsmodels.stats.weightstats import CompareMeans, DescrStatsW
from statsmodels.treatment.treatment_effects import TreatmentEffect, ate_ipw

from backend import FAILED, Checks, call, table

check = Checks()
check('treatment.py imports', FAILED.get('treatment'), None)
if 'treatment' in FAILED:
    sys.exit(check.done())


# ---- a simulated observational study --------------------------------------------------------
REG = ['East', 'North', 'South', 'West']
TAKE = {'East': -0.35, 'North': 0.0, 'South': 0.45, 'West': 0.15}
PAY = {'East': 900.0, 'North': 0.0, 'South': -1800.0, 'West': 1400.0}


def simulate(n, seed, prior_scale=1.0):
    """Take-up of a programme depends on age, education, prior earnings and
    region (a logit, so the propensity model is right); earnings depend on
    them too, and the effect is 2000 + 250 (12 - education)."""
    rng = np.random.default_rng(seed)
    age = np.clip(np.round(rng.normal(34, 9, n)), 18, 60)
    educ = np.clip(np.round(rng.normal(12, 2.2, n)), 8, 18)
    region = np.array(REG)[rng.integers(0, 4, n)]
    out = rng.uniform(size=n) < 0.25 - 0.02 * (educ - 12)
    prior = np.where(out, 0.0, np.round(np.exp(rng.normal(9.75 + 0.06 * (educ - 12) + 0.008 * (age - 34), 0.45, n)) / 10) * 10)
    lin = -0.6 - 0.045 * (age - 34) - 0.28 * (educ - 12) - 0.03 * (prior / 1000 - 14) + np.vectorize(TAKE.get)(region)
    p = 1 / (1 + np.exp(-lin))
    T = (rng.uniform(size=n) < p).astype(int)
    base = 7000 + 0.55 * prior + 650 * (educ - 12) + 110 * (age - 34) - 6 * (age - 34) ** 2 + np.vectorize(PAY.get)(region)
    tau = 2000 + 250 * (12 - educ)
    e = rng.normal(0, 3800, n)
    y0, y1 = base + e, base + tau + e
    lp = 0.3 + 0.18 * (educ - 12) + 0.00004 * (prior - 14000) - 0.02 * (age - 34)
    u = rng.uniform(size=n)
    emp0, emp1 = (u < 1 / (1 + np.exp(-lp))).astype(float), (u < 1 / (1 + np.exp(-(lp + 0.55)))).astype(float)
    df = pd.DataFrame({'age': age, 'education': educ, 'prior earnings': prior * prior_scale, 'region': region, 'program': T,
                       'earnings': np.where(T == 1, y1, y0), 'employed': np.where(T == 1, emp1, emp0)})
    truth = {'ate': float(np.mean(y1 - y0)), 'att': float(np.mean((y1 - y0)[T == 1])),
             'ate_emp': float(np.mean(emp1 - emp0)), 'att_emp': float(np.mean((emp1 - emp0)[T == 1]))}
    return df, truth


def as_table(df, types=None):
    return table({c: df[c].tolist() for c in df.columns}, types=types or {'region': 'nominal', 'program': 'nominal'})


def design(df, cols, levels=REG):
    """The design by hand, named as the report names the terms: the
    intercept, each continuous column, each level of region but the last
    (effect coding: 1 at the level, -1 at the last level)."""
    out = {'Intercept': np.ones(len(df))}
    for c in cols:
        if c == 'region':
            for lv in levels[:-1]:
                out[f'region[{lv}]'] = np.where(df[c] == lv, 1.0, np.where(df[c] == levels[-1], -1.0, 0.0))
        else:
            out[c] = df[c].to_numpy(float)
    return pd.DataFrame(out)


def std(M):
    M = np.asarray(M, dtype=float)
    return np.column_stack([M[:, 0], (M[:, 1:] - M[:, 1:].mean(0)) / M[:, 1:].std(0)])


@contextlib.contextmanager
def statsmodels_patched():
    """statsmodels' own AIPW (WLS) and IPW-RA moment classes with their
    params[-6:] replaced by params[2 * k + 1:] in the source: the patch the
    page's Python shows."""
    old = te._AIPWWLSGMM, te._IPWRAGMM
    ns = dict(te.__dict__)
    for name in ('_AIPWWLSGMM', '_IPWRAGMM'):
        src = inspect.getsource(getattr(te, name))
        exec(src.replace('params[-6:]', 'params[2 * k + 1:]'), ns)
    te._AIPWWLSGMM, te._IPWRAGMM = ns['_AIPWWLSGMM'], ns['_IPWRAGMM']
    try:
        yield
    finally:
        te._AIPWWLSGMM, te._IPWRAGMM = old


COVS = ['age', 'education', 'prior earnings', 'region']
df, truth = simulate(1000, 20260926)
tid = as_table(df)
base = dict(table=tid, y='earnings', treatment='program', treated=1, outcome=COVS)
t = df['program'].to_numpy(int)
y = df['earnings'].to_numpy(float)
Xd = design(df, COVS)
X = Xd.to_numpy()

# ---- the propensity score model -----------------------------------------------------------
r = call('treatment.fit', **base)
check('fit: no error', r.get('error'), None)
check('the sample: rows, treated, control', (r['n'], r['n_treated'], r['n_control'], r['n_missing']), (1000, int(t.sum()), int(1000 - t.sum()), 0))
check('the levels: treated 1, control 0', (r['treated'], r['control'], r['treated_text'], r['control_text']), (1, 0, '1', '0'))
lg = sm.Logit(t, Xd).fit(disp=0)
est = {e['term']: e for e in r['propensity']['estimates']['rows']}
check('Parameter Estimates: the terms, effect coded', sorted(est), sorted(Xd.columns))
for term in Xd.columns:
    check.near(f'logit estimate {term}', est[term]['estimate'], float(lg.params[term]), rel=1e-7)
    check.near(f'logit std error {term}', est[term]['se'], float(lg.bse[term]), rel=1e-6)
check.near('ChiSquare is the Wald z squared (age)', est['age']['chisq'], float(lg.tvalues['age'] ** 2), rel=1e-6)
check.near('Prob>ChiSq (education)', est['education']['p'], float(lg.pvalues['education']), rel=1e-5)
check.near('Lower 95% (age)', est['age']['lower'], float(lg.conf_int().loc['age', 0]), rel=1e-6)
whole = {w['model']: w for w in r['propensity']['whole']['rows']}
check.near('Whole Model Test: ChiSquare = 2 (llf - llnull)', whole['Difference']['chisq'], float(lg.llr), rel=1e-7)
check.near('Whole Model Test: Prob>ChiSq', whole['Difference']['p'], float(lg.llr_pvalue), rel=1e-5, abs_=1e-300)
check('Whole Model Test: DF', whole['Difference']['df'], int(lg.df_model))
check.near('-LogLikelihood (full)', whole['Full']['nll'], float(-lg.llf), rel=1e-9)
fit = r['propensity']['fit']
check.near('RSquare (U) is McFadden\'s', fit['rsquare_u'], float(lg.prsquared), rel=1e-9)
k = len(lg.params)
check.near('AICc', fit['aicc'], float(-2 * lg.llf + 2 * k + 2 * k * (k + 1) / (1000 - k - 1)), rel=1e-9)
check.near('BIC', fit['bic'], float(-2 * lg.llf + k * math.log(1000)), rel=1e-9)
p = np.asarray(lg.predict(), dtype=float)
p1, p0 = p[t == 1], p[t == 0]
auc = float(np.mean((p1[:, None] > p0[None, :]) + 0.5 * (p1[:, None] == p0[None, :])))
check.near('Area under the ROC curve, from every treated-control pair', fit['auc'], auc, rel=1e-9)
check('converged, no separation', (fit['converged'], r['propensity']['separation']['state']), (True, 'none'))
sc = r['scores']
check('scores: one per row, the page\'s row numbers', sc['rows'], list(range(1000)))
check.near('propensity scores are the logit\'s', float(np.max(np.abs(np.array(sc['ps']) - p))), 0.0, abs_=1e-9)
pr = call('treatment.fit', link='probit', **base)
pb = sm.Probit(t, Xd).fit(disp=0)
estp = {e['term']: e for e in pr['propensity']['estimates']['rows']}
check.near('Probit: estimate (prior earnings)', estp['prior earnings']['estimate'], float(pb.params['prior earnings']), rel=1e-7)
check.near('Probit: std error (region[South])', estp['region[South]']['se'], float(pb.bse['region[South]']), rel=1e-6)
check('Probit: the footer says so', pr['propensity']['estimates']['footer'].startswith('Probit'), True)

# ---- weights, overlap, balance -------------------------------------------------------------
w = t / p + (1 - t) / (1 - p)
w_att = t + (1 - t) * p / (1 - p)
check.near('IPW weights t/p + (1 - t)/(1 - p)', float(np.max(np.abs(np.array(sc['w_ate']) - w))), 0.0, abs_=1e-7)
check.near('ATT weights t + (1 - t) p/(1 - p)', float(np.max(np.abs(np.array(sc['w_att']) - w_att))), 0.0, abs_=1e-7)
ws = r['weights']['ate']
check.near('effective size of the weighted treated, (sum w)^2 / sum w^2', ws['treated']['ess'], float(w[t == 1].sum() ** 2 / np.sum(w[t == 1] ** 2)), rel=1e-7)
check.near('effective size of the weighted controls', ws['control']['ess'], float(w[t == 0].sum() ** 2 / np.sum(w[t == 0] ** 2)), rel=1e-7)
check.near('the largest weight', ws['max'], float(w.max()), rel=1e-7)
check('weights above 10', ws['n_over_10'], int(np.sum(w > 10)))
ov = r['overlap']
lo, hi = max(p1.min(), p0.min()), min(p1.max(), p0.max())
check.near('common support: from the larger of the two minima', ov['support'][0], float(lo), rel=1e-7)
check.near('common support: to the smaller of the two maxima', ov['support'][1], float(hi), rel=1e-7)
check('rows outside the common support', ov['n_outside'], int(np.sum((p < lo) | (p > hi))))
check('rows the GMM clips (outside [0.01, 0.99])', ov['n_clip'], int(np.sum((p < 0.01) | (p > 0.99))))


def smd(x, ww, binary):
    def mv(x, ww):
        m = np.average(x, weights=ww)
        if binary:
            return m, m * (1 - m)
        return m, np.sum(ww * (x - m) ** 2) * ww.sum() / (ww.sum() ** 2 - np.sum(ww ** 2))
    (m1, v1), (m0, v0) = mv(x[t == 1], ww[t == 1]), mv(x[t == 0], ww[t == 0])
    return (m1 - m0) / math.sqrt((v1 + v0) / 2), (v1 / v0 if not binary else None)


bal = {b['term']: b for b in r['balance']}
check('balance: every continuous covariate and every level', list(bal), ['age', 'education', 'prior earnings'] + [f'region[{lv}]' for lv in REG])
x_age = df['age'].to_numpy(float)
s1, s0 = x_age[t == 1].std(ddof=1), x_age[t == 0].std(ddof=1)
check.near('SMD of age: (mean1 - mean0) / sqrt((s1² + s0²)/2), unweighted', bal['age']['smd'], float((x_age[t == 1].mean() - x_age[t == 0].mean()) / math.sqrt((s1 ** 2 + s0 ** 2) / 2)), rel=1e-9)
check.near('variance ratio of age, unweighted', bal['age']['vr'], float(s1 ** 2 / s0 ** 2), rel=1e-9)
for term in ['education', 'prior earnings']:
    x = df[term].to_numpy(float)
    check.near(f'SMD of {term}, IPW weighted', bal[term]['smd_w'], smd(x, w, False)[0], rel=1e-7)
    check.near(f'variance ratio of {term}, IPW weighted', bal[term]['vr_w'], smd(x, w, False)[1], rel=1e-7)
    check.near(f'SMD of {term}, ATT weights', bal[term]['smd_att'], smd(x, w_att, False)[0], rel=1e-7)
xs = (df['region'] == 'South').to_numpy(float)
m1, m0 = xs[t == 1].mean(), xs[t == 0].mean()
check.near('SMD of a level: (p1 - p0) / sqrt((p1 q1 + p0 q0)/2)', bal['region[South]']['smd'], float((m1 - m0) / math.sqrt((m1 * (1 - m1) + m0 * (1 - m0)) / 2)), rel=1e-9)
check.near('SMD of a level, weighted', bal['region[South]']['smd_w'], smd(xs, w, True)[0], rel=1e-7)
check('no variance ratio for a level', bal['region[South]']['vr'], None)
check('weighting balances the covariates: every |SMD| after below 0.1', all(abs(b['smd_w']) < 0.1 for b in r['balance']), True)
check('and prior earnings was out of balance before', abs(bal['prior earnings']['smd']) > 0.2, True)

# ---- the unadjusted difference in means ----------------------------------------------------------
nv = r['naive']
cm = CompareMeans(DescrStatsW(y[t == 1]), DescrStatsW(y[t == 0]))
check.near('difference in means', nv['estimate'], float(y[t == 1].mean() - y[t == 0].mean()), rel=1e-12)
check.near('its standard error sqrt(s1²/n1 + s0²/n0)', nv['se'], float(math.sqrt(y[t == 1].var(ddof=1) / t.sum() + y[t == 0].var(ddof=1) / (1000 - t.sum()))), rel=1e-9)
check.near('its z test (CompareMeans, unequal variances)', nv['z'], float(cm.ztest_ind(usevar='unequal')[0]), rel=1e-9)
check.near('its lower limit', nv['lower'], float(cm.zconfint_diff(usevar='unequal')[0]), rel=1e-9)

# ---- the estimates, against statsmodels called directly ---------------------------------------------
e = call('treatment.estimates', **base)
check('estimates: no error', e.get('error'), None)
E = {x['key']: x for x in e['estimates']}
check('the five estimators, in order', [x['label'] for x in e['estimates']], ['IPW', 'AIPW', 'AIPW (WLS)', 'RA', 'IPW-RA'])
check('none failed', [x.get('error') for x in e['estimates']], [None] * 5)
ps_std = sm.Logit(t, std(X)).fit(disp=0)
teff = TreatmentEffect(sm.OLS(y, std(X)), t, results_select=ps_std)
with statsmodels_patched():
    direct = {k: getattr(teff, k)() for k in ('ipw', 'aipw', 'aipw_wls', 'ra', 'ipw_ra')}
for k, rd in direct.items():
    for j, part in enumerate(('ate', 'pom0', 'pom1')):
        check.near(f'{k} {part}: statsmodels\' estimate', E[k][part]['estimate'], float(rd.effect[j]), rel=1e-9)
        check.near(f'{k} {part}: statsmodels\' GMM standard error', E[k][part]['se'], float(rd.sd[j]), rel=1e-6)
    check.near(f'{k}: z', E[k]['ate']['z'], float(rd.statistic[0]), rel=1e-6)
    check.near(f'{k}: p', E[k]['ate']['p'], float(rd.pvalue[0]), rel=1e-4, abs_=1e-300)
    check.near(f'{k}: lower 95%', E[k]['ate']['lower'], float(rd.conf_int(alpha=0.05)[0, 0]), rel=1e-7)
    check.near(f'{k}: the GMM solution is the closed form (no propensity is clipped)', E[k]['gmm_gap'], 0.0, abs_=1e-7)
e90 = call('treatment.estimates', alpha=0.1, estimators=['ra'], **base)
check.near('α = 0.1: the 90% interval', e90['estimates'][0]['ate']['upper'], float(direct['ra'].conf_int(alpha=0.1)[0, 1]), rel=1e-7)
check('estimators= picks some', [x['key'] for x in e90['estimates']], ['ra'])

# ---- ... and against formulas -------------------------------------------------------------------------
pom1 = np.sum(t * y / p) / np.sum(t / p)
pom0 = np.sum((1 - t) * y / (1 - p)) / np.sum((1 - t) / (1 - p))
check.near('IPW POM1 = sum(t y / p) / sum(t / p)', E['ipw']['pom1']['estimate'], float(pom1), rel=1e-8)
check.near('IPW POM0 = sum((1-t) y / (1-p)) / sum((1-t) / (1-p))', E['ipw']['pom0']['estimate'], float(pom0), rel=1e-8)
check.near('IPW ATE = POM1 - POM0', E['ipw']['ate']['estimate'], float(pom1 - pom0), rel=1e-8)
b0 = np.linalg.lstsq(X[t == 0], y[t == 0], rcond=None)[0]
b1 = np.linalg.lstsq(X[t == 1], y[t == 1], rcond=None)[0]
f0, f1 = X @ b0, X @ b1
check.near('RA ATE = mean(X b1) - mean(X b0), least squares in each group', E['ra']['ate']['estimate'], float(f1.mean() - f0.mean()), rel=1e-8)
check.near('RA POM0 = mean(X b0)', E['ra']['pom0']['estimate'], float(f0.mean()), rel=1e-9)
a1 = np.mean(f1 + t * (y - f1) / p)
a0 = np.mean(f0 + (1 - t) * (y - f0) / (1 - p))
check.near('AIPW POM1 = mean(f1 + t (y - f1)/p)', E['aipw']['pom1']['estimate'], float(a1), rel=1e-8)
check.near('AIPW ATE', E['aipw']['ate']['estimate'], float(a1 - a0), rel=1e-7)


def wls(Xg, yg, wg):
    sw = np.sqrt(wg)
    return np.linalg.lstsq(Xg * sw[:, None], yg * sw, rcond=None)[0]


c0 = wls(X[t == 0], y[t == 0], 1 / (1 - p[t == 0]))
c1 = wls(X[t == 1], y[t == 1], 1 / p[t == 1])
check.near('IPW-RA ATE: weighted least squares with 1/p and 1/(1-p), predictions averaged', E['ipw_ra']['ate']['estimate'], float(np.mean(X @ c1) - np.mean(X @ c0)), rel=1e-7)
d0 = wls(X[t == 0], y[t == 0], p[t == 0] / (1 - p[t == 0]) ** 2)
d1 = wls(X[t == 1], y[t == 1], (1 - p[t == 1]) / p[t == 1] ** 2)
g0, g1 = X @ d0, X @ d1
check.near('AIPW (WLS) ATE: weights (1-p)/p² and p/(1-p)², then the AIPW formula', E['aipw_wls']['ate']['estimate'],
           float(np.mean(g1 + t * (y - g1) / p) - np.mean(g0 + (1 - t) * (y - g0) / (1 - p))), rel=1e-7)

# ---- the effect on the treated ----------------------------------------------------------------------------
a = call('treatment.estimates', effect_group=1, **base)
A_ = {x['key']: x for x in a['estimates']}
check('ATT: IPW, RA and IPW-RA (statsmodels has no ATT for AIPW)', [x['label'] for x in a['estimates']], ['IPW', 'RA', 'IPW-RA'])
with statsmodels_patched():
    direct_att = {k: getattr(teff, k)(effect_group=1) for k in ('ipw', 'ra', 'ipw_ra')}
for k, rd in direct_att.items():
    check.near(f'ATT {k}: statsmodels\' estimate', A_[k]['ate']['estimate'], float(rd.effect[0]), rel=1e-9)
    check.near(f'ATT {k}: statsmodels\' standard error', A_[k]['ate']['se'], float(rd.sd[0]), rel=1e-6)
odds = p / (1 - p)
check.near('IPW ATT = mean(y | treated) - sum((1-t) y p/(1-p)) / sum((1-t) p/(1-p))', A_['ipw']['ate']['estimate'],
           float(y[t == 1].mean() - np.sum((1 - t) * y * odds) / np.sum((1 - t) * odds)), rel=1e-8)
check.near('RA ATT = mean over the treated of X b1 - X b0', A_['ra']['ate']['estimate'], float(np.mean((f1 - f0)[t == 1])), rel=1e-8)
e0 = wls(X[t == 0], y[t == 0], odds[t == 0])
check.near('IPW-RA ATT: controls weighted by p/(1-p), the treated by 1', A_['ipw_ra']['ate']['estimate'], float(np.mean((X @ b1 - X @ e0)[t == 1])), rel=1e-7)
check.near('the ATT POM1 is the treated\'s mean outcome', A_['ra']['pom1']['estimate'], float(y[t == 1].mean()), rel=1e-9)


# ---- the standard errors, by the sandwich with analytic derivatives -------------------------------------
def sandwich(psi, Amat):
    n = psi.shape[0]
    Ai = np.linalg.inv(Amat)
    V = Ai @ (psi.T @ psi / n) @ Ai.T / n
    return math.sqrt(V[0, 0]), math.sqrt(V[1, 1]), math.sqrt(V[0, 0] + V[1, 1] + 2 * V[0, 1])


def se_ipw(res):
    ate, pom0_ = res['ate']['estimate'], res['pom0']['estimate']
    pom1_ = ate + pom0_
    n, kz = X.shape
    ww = t / p + (1 - t) / (1 - p)
    r_ = y - pom0_ - t * ate
    psi = np.column_stack([ww * r_ * t, ww * r_, (t - p)[:, None] * X])
    Am = np.zeros((2 + kz, 2 + kz))
    Am[0, 0] = Am[0, 1] = Am[1, 0] = -np.mean(t / p)
    Am[1, 1] = -np.mean(ww)
    dd1 = -t * (y - pom1_) * (1 - p) / p
    dd0 = (1 - t) * (y - pom0_) * p / (1 - p)
    Am[0, 2:] = np.mean(dd1[:, None] * X, 0)
    Am[1, 2:] = np.mean((dd1 + dd0)[:, None] * X, 0)
    Am[2:, 2:] = -(X * (p * (1 - p))[:, None]).T @ X / n
    return sandwich(psi, Am)


def se_ra(res):
    n, kx = X.shape
    psi = np.column_stack([f1 - f0 - res['ate']['estimate'], f0 - res['pom0']['estimate'], (1 - t)[:, None] * X * (y - f0)[:, None], t[:, None] * X * (y - f1)[:, None]])
    Am = np.zeros((2 + 2 * kx, 2 + 2 * kx))
    xm = X.mean(0)
    Am[0, 0] = Am[1, 1] = -1
    Am[0, 2:2 + kx], Am[0, 2 + kx:], Am[1, 2:2 + kx] = -xm, xm, xm
    Am[2:2 + kx, 2:2 + kx] = -(X * (1 - t)[:, None]).T @ X / n
    Am[2 + kx:, 2 + kx:] = -(X * t[:, None]).T @ X / n
    return sandwich(psi, Am)


def se_aipw(res):
    n, kx = X.shape
    ate, pom0_ = res['ate']['estimate'], res['pom0']['estimate']
    m1_ = f1 + t * (y - f1) / p
    m0_ = f0 + (1 - t) * (y - f0) / (1 - p)
    psi = np.column_stack([m1_ - m0_ - ate, m0_ - pom0_, (1 - t)[:, None] * X * (y - f0)[:, None], t[:, None] * X * (y - f1)[:, None], (t - p)[:, None] * X])
    K = 2 + 3 * kx
    Am = np.zeros((K, K))
    B0, B1, BS = slice(2, 2 + kx), slice(2 + kx, 2 + 2 * kx), slice(2 + 2 * kx, K)
    Am[0, 0] = Am[1, 1] = -1
    Am[0, B1] = np.mean(X * (1 - t / p)[:, None], 0)
    Am[0, B0] = np.mean(X * (-1 + (1 - t) / (1 - p))[:, None], 0)
    Am[0, BS] = np.mean(X * (-t * (y - f1) * (1 - p) / p - (1 - t) * (y - f0) * p / (1 - p))[:, None], 0)
    Am[1, B0] = np.mean(X * (1 - (1 - t) / (1 - p))[:, None], 0)
    Am[1, BS] = np.mean(X * ((1 - t) * (y - f0) * p / (1 - p))[:, None], 0)
    Am[B0, B0] = -(X * (1 - t)[:, None]).T @ X / n
    Am[B1, B1] = -(X * t[:, None]).T @ X / n
    Am[BS, BS] = -(X * (p * (1 - p))[:, None]).T @ X / n
    return sandwich(psi, Am)


def se_ipwra(res):
    n, kx = X.shape
    h0, h1 = X @ c0, X @ c1
    psi = np.column_stack([h1 - h0 - res['ate']['estimate'], h0 - res['pom0']['estimate'], ((1 - t) / (1 - p))[:, None] * X * (y - h0)[:, None],
                           (t / p)[:, None] * X * (y - h1)[:, None], (t - p)[:, None] * X])
    K = 2 + 3 * kx
    Am = np.zeros((K, K))
    B0, B1, BS = slice(2, 2 + kx), slice(2 + kx, 2 + 2 * kx), slice(2 + 2 * kx, K)
    xm = X.mean(0)
    Am[0, 0] = Am[1, 1] = -1
    Am[0, B0], Am[0, B1], Am[1, B0] = -xm, xm, xm
    Am[B0, B0] = -(X * ((1 - t) / (1 - p))[:, None]).T @ X / n
    Am[B1, B1] = -(X * (t / p)[:, None]).T @ X / n
    Am[B0, BS] = (X * ((1 - t) * (y - h0) * p / (1 - p))[:, None]).T @ X / n
    Am[B1, BS] = -(X * (t * (y - h1) * (1 - p) / p)[:, None]).T @ X / n
    Am[BS, BS] = -(X * (p * (1 - p))[:, None]).T @ X / n
    return sandwich(psi, Am)


def se_ipw_att(res):
    n, kz = X.shape
    att, pom0_ = res['ate']['estimate'], res['pom0']['estimate']
    pom1_ = att + pom0_
    psi = np.column_stack([t * (y - pom1_), t * (y - pom1_) + (1 - t) * odds * (y - pom0_), (t - p)[:, None] * X])
    Am = np.zeros((2 + kz, 2 + kz))
    Am[0, 0] = Am[0, 1] = Am[1, 0] = -np.mean(t)
    Am[1, 1] = -np.mean(t + (1 - t) * odds)
    Am[1, 2:] = np.mean(X * ((1 - t) * (y - pom0_) * odds)[:, None], 0)
    Am[2:, 2:] = -(X * (p * (1 - p))[:, None]).T @ X / n
    return sandwich(psi, Am)


for k, fn in (('ipw', se_ipw), ('ra', se_ra), ('aipw', se_aipw), ('ipw_ra', se_ipwra)):
    want = fn(E[k])
    for j, part in enumerate(('ate', 'pom0', 'pom1')):
        check.near(f'{k} {part} standard error = the sandwich with analytic derivatives', E[k][part]['se'], want[j], rel=2e-6)
want = se_ipw_att(A_['ipw'])
check.near('IPW ATT standard error = the sandwich', A_['ipw']['ate']['se'], want[0], rel=2e-6)
check.near('IPW ATT POM0 standard error = the sandwich', A_['ipw']['pom0']['se'], want[1], rel=2e-6)

# ---- why the designs are standardized: statsmodels on the raw design, prior earnings in dollars ----------
raw = TreatmentEffect(sm.OLS(y, X), t, results_select=sm.Logit(t, X).fit(disp=0))
se_raw = float(raw.ipw().sd[0])
check('statsmodels\' IPW standard error on the raw design is far off (fixed step 1e-4 in the GMM\'s derivatives)', se_raw > 1.5 * E['ipw']['ate']['se'], True)
check.near('the same estimate either way', float(raw.ipw().effect[0]), E['ipw']['ate']['estimate'], rel=1e-8)
df_k, _ = simulate(1000, 20260926, prior_scale=0.001)   # prior earnings in thousands
tk = as_table(df_k)
ek = call('treatment.estimates', table=tk, y='earnings', treatment='program', treated=1, outcome=COVS, estimators=['ipw', 'ipw_ra'])
check.near('in thousands: the same IPW standard error', ek['estimates'][0]['ate']['se'], E['ipw']['ate']['se'], rel=1e-6)
check.near('in thousands: the same IPW-RA standard error', ek['estimates'][1]['ate']['se'], E['ipw_ra']['ate']['se'], rel=1e-6)

# ---- the params[-6:] slice: with a six-parameter propensity model the page's classes are statsmodels' -----
six = ['age', 'education', 'prior earnings', 'region']   # 1 + 1 + 1 + 1 + 3 = 7; drop education for six
e6 = call('treatment.estimates', table=tid, y='earnings', treatment='program', treated=1, outcome=six, covariates=['age', 'prior earnings', 'region'], estimators=['aipw_wls', 'ipw_ra'])
Z6 = design(df, ['age', 'prior earnings', 'region']).to_numpy()
check('six parameters in that propensity model', e6['k_select'], 6)
t6 = TreatmentEffect(sm.OLS(y, std(X)), t, results_select=sm.Logit(t, std(Z6)).fit(disp=0))
check.near('AIPW (WLS) with six: statsmodels\' own, unpatched', e6['estimates'][0]['ate']['se'], float(t6.aipw_wls().sd[0]), rel=1e-6)
check.near('IPW-RA with six: statsmodels\' own, unpatched', e6['estimates'][1]['ate']['se'], float(t6.ipw_ra().sd[0]), rel=1e-6)
try:
    TreatmentEffect(sm.OLS(y, std(X)), t, results_select=ps_std).ipw_ra()
    unpatched = 'ran'
except ValueError:
    unpatched = 'fails'
check('with seven, statsmodels\' own ipw_ra() fails (hence the page\'s classes)', unpatched, 'fails')

# ---- known truth --------------------------------------------------------------------------------------------
big, tr = simulate(6000, 7)
tb = as_table(big)
bb = dict(table=tb, y='earnings', treatment='program', treated=1, outcome=COVS)
eb = call('treatment.estimates', **bb)
for x in eb['estimates']:
    zdev = (x['ate']['estimate'] - tr['ate']) / x['ate']['se']
    check(f'{x["label"]} is within 3 standard errors of the true ATE {tr["ate"]:.1f} ({x["ate"]["estimate"]:.1f}, z = {zdev:+.2f})', abs(zdev) < 3, True)
ab = call('treatment.estimates', effect_group=1, **bb)
for x in ab['estimates']:
    zdev = (x['ate']['estimate'] - tr['att']) / x['ate']['se']
    check(f'{x["label"]} is within 3 standard errors of the true ATT {tr["att"]:.1f} ({x["ate"]["estimate"]:.1f}, z = {zdev:+.2f})', abs(zdev) < 3, True)
nb = call('treatment.fit', **bb)['naive']
check(f'the unadjusted difference ({nb["estimate"]:.0f}) is more than 5 standard errors from the truth', abs(nb['estimate'] - tr['ate']) > 5 * nb['se'], True)
eb2 = call('treatment.estimates', table=tb, y='employed', treatment='program', treated=1, outcome=COVS)
for x in eb2['estimates']:
    zdev = (x['ate']['estimate'] - tr['ate_emp']) / x['ate']['se']
    check(f'a 0/1 outcome: {x["label"]} within 3 SE of the true risk difference {tr["ate_emp"]:.3f} (z = {zdev:+.2f})', abs(zdev) < 3, True)
check('a 0/1 outcome is noticed', call('treatment.fit', table=tb, y='employed', treatment='program', treated=1, outcome=COVS)['binary_y'], True)

# ---- the outcome models ----------------------------------------------------------------------------------
om = call('treatment.outcome_models', **base)
G = {g['group']: g for g in om['groups']}
for name, g in (('control', 0), ('treated', 1)):
    ref = sm.OLS(y[t == g], Xd[t == g]).fit(cov_type='HC0')
    ests = {x['term']: x for x in G[name]['estimates']['rows']}
    check.near(f'{name} outcome model: estimate (education)', ests['education']['estimate'], float(ref.params['education']), rel=1e-8)
    check.near(f'{name} outcome model: HC0 std error (region[East])', ests['region[East]']['se'], float(ref.bse['region[East]']), rel=1e-8)
    check.near(f'{name} outcome model: RSquare', G[name]['rsquare'], float(ref.rsquared), rel=1e-9)
    check(f'{name} outcome model: N', G[name]['n'], int(np.sum(t == g)))

# ---- trimming ---------------------------------------------------------------------------------------------
eps = 0.08
rt = call('treatment.fit', trim=eps, **base)
keep = (p >= eps) & (p <= 1 - eps)
check('trimming: the rows outside [ε, 1 - ε] of the full model', rt['trim']['rows'], [int(i) for i in np.where(~keep)[0]])
check('trimming: how many, by group', (rt['trim']['n_dropped'], rt['trim']['n_dropped_treated'], rt['trim']['n_dropped_control']),
      (int((~keep).sum()), int((~keep & (t == 1)).sum()), int((~keep & (t == 0)).sum())))
check('trimming: the rest are analysed', rt['n'], int(keep.sum()))
lk = sm.Logit(t[keep], design(df[keep], COVS)).fit(disp=0)
check.near('the propensity model is refitted on the rows left', {x['term']: x for x in rt['propensity']['estimates']['rows']}['age']['estimate'], float(lk.params['age']), rel=1e-7)
etr = call('treatment.estimates', trim=eps, estimators=['ra'], **base)
Xk = X[keep]
bk0 = np.linalg.lstsq(Xk[t[keep] == 0], y[keep][t[keep] == 0], rcond=None)[0]
bk1 = np.linalg.lstsq(Xk[t[keep] == 1], y[keep][t[keep] == 1], rcond=None)[0]
check.near('the estimates use the rows left (RA)', etr['estimates'][0]['ate']['estimate'], float(np.mean(Xk @ bk1) - np.mean(Xk @ bk0)), rel=1e-8)
check('no trimming: trim is none', r['trim'], None)
r0 = call('treatment.fit', trim=0.001, **base)
check('a small ε that drops nothing', (r0['trim']['n_dropped'], r0['n']), (0, 1000))

# ---- rows, missing values, levels, errors ------------------------------------------------------------------
sub = list(range(0, 1000, 2))
rs = call('treatment.estimates', rows=sub, estimators=['ipw'], **base)
ts, ys, Xs_ = t[sub], y[sub], X[sub]
ps_sub = sm.Logit(ts, Xs_).fit(disp=0).predict()
check.near('a subset of rows (a By group)', rs['estimates'][0]['ate']['estimate'], float(ate_ipw(ys, ts, ps_sub)[0]), rel=1e-8)
dm = df.copy()
dm.loc[[3, 17], 'age'] = np.nan
cols_m = {c: dm[c].tolist() for c in dm.columns}
cols_m['region'][5] = None   # a missing text value
tm_ = table(cols_m, types={'region': 'nominal', 'program': 'nominal'})
dm.loc[[5], 'region'] = np.nan
rm = call('treatment.fit', table=tm_, y='earnings', treatment='program', treated=1, outcome=COVS)
check('rows with a missing covariate are left out, and counted', (rm['n'], rm['n_missing']), (997, 3))
check('their row numbers are not among the scores', {3, 5, 17} & set(rm['scores']['rows']), set())
cols_nan = {c: df[c].tolist() for c in df.columns}
cols_nan['region'][7] = 'nan'   # a text value patsy may take for missing
tn = table(cols_nan, types={'region': 'nominal', 'program': 'nominal'})
rn = call('treatment.fit', table=tn, y='earnings', treatment='program', treated=1, outcome=COVS)
check('a text value "nan": every part has the same rows', (rn.get('error'), len(rn['scores']['rows']) == rn['n'], rn['n'] + rn['n_missing']), (None, True, 1000))
check('... and the estimates run', call('treatment.estimates', table=tn, y='earnings', treatment='program', treated=1, outcome=COVS, estimators=['ra'])['estimates'][0].get('error'), None)
rs1 = call('treatment.fit', table=tid, y='earnings', treatment='program', treated='1', outcome=COVS)
check('the treated level may come as text', (rs1['treated'], rs1['n_treated']), (1, int(t.sum())))
rs0 = call('treatment.fit', table=tid, y='earnings', treatment='program', treated=0, outcome=COVS)
check('the other level as the treated one flips the effect', round(rs0['naive']['estimate'], 6), round(-r['naive']['estimate'], 6))
e0_ = call('treatment.estimates', table=tid, y='earnings', treatment='program', treated=0, outcome=COVS, estimators=['aipw'])
check.near('... and the AIPW estimate', e0_['estimates'][0]['ate']['estimate'], -E['aipw']['ate']['estimate'], rel=1e-7)
dc = df.copy()
dc['program'] = np.where(df['program'] == 1, 'trained', 'not trained')
tc = as_table(dc)
rc = call('treatment.fit', table=tc, y='earnings', treatment='program', treated='trained', outcome=COVS)
check('a character treatment column', (rc['treated'], rc['control'], rc['n_treated']), ('trained', 'not trained', int(t.sum())))
rd_ = call('treatment.fit', table=tc, y='earnings', treatment='program', outcome=COVS)
check('without a treated level, the second level (in value order) is the treated one', rd_['treated'], 'trained')
d3 = df.copy()
d3['program'] = np.where(df['age'] > 40, 2, df['program'])
check('three levels are refused', 'two levels' in call('treatment.fit', table=as_table(d3), y='earnings', treatment='program', outcome=COVS).get('error', ''), True)
check('Y among the covariates is refused', 'outcome' in call('treatment.fit', table=tid, y='earnings', treatment='program', outcome=['earnings', 'age']).get('error', ''), True)
check('no covariates are refused', 'covariates' in call('treatment.fit', table=tid, y='earnings', treatment='program').get('error', ''), True)
check('a level that is not there is refused', 'not among' in call('treatment.fit', table=tid, y='earnings', treatment='program', treated=7, outcome=COVS).get('error', ''), True)
rt2 = call('treatment.fit', table=tid, y='earnings', treatment='program', treated=1, outcome=['age'], covariates=['age', 'education', 'prior earnings', 'region'])
check('different covariates for the two models', ([x['term'] for x in rt2['propensity']['estimates']['rows']][-1], len(rt2['balance'])), ('prior earnings', 7))
eo = call('treatment.outcome_models', table=tid, y='earnings', treatment='program', treated=1, outcome=[], covariates=COVS)
check('no outcome covariates: the outcome models are the group means', [round(g['estimates']['rows'][0]['estimate'], 6) for g in eo['groups']],
      [round(float(y[t == 0].mean()), 6), round(float(y[t == 1].mean()), 6)])
en = call('treatment.estimates', table=tid, y='earnings', treatment='program', treated=1, outcome=[], covariates=COVS, estimators=['ra'])
check.near('... and RA is the difference in means', en['estimates'][0]['ate']['estimate'], float(y[t == 1].mean() - y[t == 0].mean()), rel=1e-9)

# ---- separation -----------------------------------------------------------------------------------------------
dsep = df.copy()
dsep.loc[dsep['region'] == 'East', 'program'] = 1   # everyone in the East takes part
tsep = as_table(dsep)
rq = call('treatment.fit', table=tsep, y='earnings', treatment='program', treated=1, outcome=COVS)
sep = rq['propensity']['separation']
check('a level with only treated rows is named', [(x['column'], x['level'], x['all']) for x in sep['levels']], [('region', 'East', 'treated')])
check('... and called quasi-separation', sep['state'], 'quasi')
eq_ = call('treatment.estimates', table=tsep, y='earnings', treatment='program', treated=1, outcome=COVS, estimators=['ra', 'aipw'])
check('RA and AIPW say where the outcome model is singular', all('singular' in (x.get('error') or '') for x in eq_['estimates']), True)
dpf = df.copy()
dpf['program'] = (df['age'] > 36).astype(int)
rpf = call('treatment.fit', table=as_table(dpf), y='earnings', treatment='program', treated=1, outcome=COVS)
check('complete separation by age: every row predicted with certainty, or no convergence', rpf.get('error') is not None or rpf['propensity']['separation']['state'] in ('complete', 'quasi'), True)

# ---- clipping: statsmodels clips the propensity scores inside the GMM ---------------------------------------
dx, _ = simulate(1200, 99)
dx['prior earnings'] = dx['prior earnings'] * 3   # stronger selection: some propensities near 0
dx['program'] = (np.random.default_rng(5).uniform(size=len(dx)) < 1 / (1 + np.exp(-(1.5 - 0.00012 * dx['prior earnings'] - 0.3 * (dx['education'] - 12))))).astype(int)
tx = as_table(dx)
rx = call('treatment.fit', table=tx, y='earnings', treatment='program', treated=1, outcome=COVS)
ex = call('treatment.estimates', table=tx, y='earnings', treatment='program', treated=1, outcome=COVS, estimators=['ipw'])
check(f'rows outside [0.01, 0.99] are counted ({rx["overlap"]["n_clip"]})', rx['overlap']['n_clip'] > 0, True)
check('and the estimates say how many', ex['n_clip'], rx['overlap']['n_clip'])
check('with clipping, the GMM solution of IPW moves from the closed form', ex['estimates'][0]['gmm_gap'] > 1e-7, True)

# ---- the Python under each result runs on the table exported as CSV --------------------------------------------
tmp = tempfile.mkdtemp(prefix='smui-treatment-')


def maxdiff_(a, b):
    return max((abs(x - y) for x, y in zip(a, b)), default=0.0) if len(a) == len(b) else float('inf')


def run_code(code, frame, name):
    frame.to_csv(os.path.join(tmp, f'{name}.csv'), index=False)
    ns = {}
    here = os.getcwd()
    os.chdir(tmp)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(code, name, 'exec'), ns)
        return ns, None
    except Exception as ex_:
        return ns, f'{type(ex_).__name__}: {ex_}'
    finally:
        os.chdir(here)


rf = call('treatment.fit', table_name='Job training', **base)
ns, err = run_code(rf['code'], df, 'Job training')
check('fit: the code runs', err, None)
if not err:
    got = {x['term']: x['estimate'] for x in rf['propensity']['estimates']['rows']}
    names = ns['Z'].design_info.column_names
    labels = {n_: (n_ if n_ == 'Intercept' else None) for n_ in names}
    check.near('its propensity model has the report\'s intercept', float(ns['ps'].params[0]), got['Intercept'], rel=1e-9)
    check.near('its propensity model has the report\'s coefficients (prior earnings)', float(ns['ps'].params[names.index('Q("prior earnings")')]), got['prior earnings'], rel=1e-9)
    smd_code = ns['smd']
    for b in rf['balance']:
        check.near(f'its balance table: SMD of {b["term"]}', float(smd_code.loc[b['term'], 'SMD']), b['smd'], rel=1e-9)
        check.near(f'its balance table: weighted SMD of {b["term"]}', float(smd_code.loc[b['term'], 'SMD (weighted)']), b['smd_w'], rel=1e-7)
    check.near('its difference in means', float(ns['cm'].d1.mean - ns['cm'].d2.mean), rf['naive']['estimate'], rel=1e-12)
    check.near('its weights', float(np.max(np.abs(ns['w'] - np.array(rf['scores']['w_ate'])))), 0.0, abs_=1e-9)
for label, kw in (('ATE', {}), ('ATT', {'effect_group': 1}), ('probit', {'link': 'probit', 'estimators': ['aipw', 'ipw_ra']}),
                  ('trimmed', {'trim': 0.08, 'estimators': ['ipw', 'aipw_wls']}), ('a subset of rows', {'rows': sub, 'estimators': ['ra', 'ipw']}),
                  ('rows mostly', {'rows': list(range(40, 1000)), 'estimators': ['ipw']})):
    rr = call('treatment.estimates', table_name='Job training', **base, **kw)
    ns, err = run_code(rr['code'], df, 'Job training')
    check(f'estimates ({label}): the code runs', err, None)
    if err:
        print(rr['code'])
        continue
    for x in rr['estimates']:
        got = ns['res'][x['label']]
        check.near(f'estimates ({label}): {x["label"]} as the report', float(got.effect[0]), x['ate']['estimate'], rel=1e-9)
        check.near(f'estimates ({label}): {x["label"]} standard error as the report', float(got.sd[0]), x['ate']['se'], rel=1e-7)
        check.near(f'estimates ({label}): {x["label"]} POM1 as the report', float(got.effect[2]), x['pom1']['estimate'], rel=1e-9)
check('the code of IPW alone needs no patch', 'inspect.getsource' in call('treatment.estimates', estimators=['ipw', 'ra'], **base)['code'], False)
ro = call('treatment.outcome_models', table_name='Job training', **base)
ns, err = run_code(ro['code'], df, 'Job training')
check('outcome models: the code runs', err, None)
if not err:
    check.near('its control model has the report\'s intercept', float(ns['fits'][0].params[0]), ro['groups'][0]['estimates']['rows'][0]['estimate'], rel=1e-9)
    check.near('its treated model has the report\'s HC0 standard error', float(ns['fits'][1].bse[0]), ro['groups'][1]['estimates']['rows'][0]['se'], rel=1e-9)
rct = call('treatment.estimates', table=tc, y='earnings', treatment='program', treated='trained', outcome=COVS, estimators=['ra'], table_name='Job training 2')
ns, err = run_code(rct['code'], dc, 'Job training 2')
check('a character treatment: the code runs', err, None)
if not err:
    check.near('... and gives the report\'s RA', float(ns['res']['RA'].effect[0]), rct['estimates'][0]['ate']['estimate'], rel=1e-9)
ft = call('treatment.fit', trim=0.08, table_name='Job training', **base)
ns, err = run_code(ft['code'], df, 'Job training')
check('fit, trimmed: the code runs', err, None)
if not err:
    check('... on the rows the report keeps', int(len(ns['t'])), ft['n'])
rnm = call('treatment.fit', table=tm_, y='earnings', treatment='program', treated=1, outcome=COVS, table_name='missing')
ns, err = run_code(rnm['code'], dm, 'missing')
check('missing values: the code runs and drops the same rows', (err, None if err else int(len(ns['t']))), (None, 997))

# ---- the graphs' matplotlib code, run with Agg on the CSV, against the report's numbers ----------------------------------
from test_charts import run_snippet_more  # noqa: E402

TREATED, CONTROL, MUTED, ACCENT = '#b8406eff', '#2e6fbaff', '#786b5dff', '#bb6c5dff'


def nice_bins(v):
    """SM.report.niceBins, as the page chooses the weights' bins."""
    v = [x for x in v if isinstance(x, (int, float)) and math.isfinite(x)]
    lo, hi = min(v), max(v)
    k = max(5, min(40, math.ceil(math.log2(len(v)) + 1)))
    raw = (hi - lo) / k
    p_ = 10 ** math.floor(math.log10(raw))
    size = min((m * p_ for m in (1, 2, 2.5, 5, 10)), key=lambda s_: abs(math.log(s_ / raw)))
    start = math.floor(lo / size) * size
    end = math.ceil(hi / size) * size
    if end <= hi:
        end += size
    return {'start': start, 'end': end, 'size': size}


def chart(kind, plot, label, **kw):
    r = call('treatment.plot_code', kind=kind, plot=plot, **{**base, **kw})
    check(f'{label}: the code is written', r.get('error'), None)
    code = r.get('plot_code') or ''
    out, err = run_snippet_more(code, df, 'data', tmp)
    check(f'{label}: the code runs', err, None)
    check(f'{label}: it ends with plt.show()', code.rstrip().split('\n')[-1] if code else None, 'plt.show()')
    check(f'{label}: one figure', len(out['figures']) if out else 0, 1)
    return (out['figures'][0] if out and out['figures'] else None), code


def page_counts(values, t_, bins):
    """The two groups' counts in the page's bins (groupHistogram)."""
    nb = max(1, round((bins['end'] - bins['start']) / bins['size']))
    c1, c0 = np.zeros(nb), np.zeros(nb)
    for v, g in zip(values, t_):
        if not (isinstance(v, (int, float)) and math.isfinite(v)):
            continue
        j = min(nb - 1, max(0, math.floor((v - bins['start']) / bins['size'] + 1e-9)))
        (c1 if g == 1 else c0)[j] += 1
    return c1, c0


for tag, plot, kw in (('mirrored, the common support', {'size': 0.05, 'mirror': True, 'support': True}, {}),
                      ('overlaid, bins of 0.1, trimmed at 0.03', {'size': 0.1, 'mirror': False, 'support': False}, {'trim': 0.03})):
    F, code = chart('overlap', plot, f'overlap ({tag})', **kw)
    rr = call('treatment.fit', **{**base, **kw})
    if not F:
        continue
    A = F['axes'][0]
    sc = rr['scores']
    c1, c0 = page_counts(sc['ps'], sc['t'], {'start': 0.0, 'end': 1.0, 'size': plot['size']})
    b1 = [b for b in A['bars'] if b['fc'] == (TREATED if plot['mirror'] else TREATED[:7] + '9e')]
    b0 = [b for b in A['bars'] if b['fc'] == (CONTROL if plot['mirror'] else CONTROL[:7] + '9e')]
    check(f'overlap ({tag}): the treated bars are the page\'s counts of the report\'s propensity scores', [b['h'] for b in b1], c1.tolist())
    check(f'overlap ({tag}): the controls\' {"below the axis" if plot["mirror"] else "overlaid"}', [b['h'] for b in b0], (-c0 if plot['mirror'] else c0).tolist())
    check.near(f'overlap ({tag}): the bins\' width', b1[0]['w'] if b1 else None, plot['size'], rel=1e-12)
    if plot['mirror']:
        top = max(1, c1.max(), c0.max())
        check(f'overlap ({tag}): the range, 1.1 times the largest count either way', A['ylim'], [-1.1 * top, 1.1 * top])
    spans = [b for b in A['bars'] if b['fc'] == '#5a504617']
    lo_, hi_ = rr['overlap']['support']
    want = ([(0.0, lo_)] if lo_ > 0 else []) + ([(hi_, 1.0)] if hi_ < 1 else [])
    check(f'overlap ({tag}): outside the report\'s common support shaded', [(round(b['x'], 12), round(b['x'] + b['w'], 12)) for b in spans], [(round(a, 12), round(b, 12)) for a, b in want] if plot['support'] else [])
    trims = [ln for ln in A['lines'] if ln['color'] == ACCENT]
    check(f'overlap ({tag}): the trimming thresholds', [ln['x'][0] for ln in trims], [kw['trim'], 1 - kw['trim']] if 'trim' in kw else [])
    check(f'overlap ({tag}): the titles and the legend', (A['xlabel'], A['ylabel'], A['title'], F['legend']), ('Propensity Score, P(program = 1)', 'Count', 'propensity score overlap', ['program = 1', 'program = 0']))
rr = call('treatment.fit', **base)
for wt in ('ate', 'att'):
    w = rr['scores']['w_' + wt]
    bins = nice_bins(w)
    F, code = chart('weights', {'wtype': wt, 'bins': bins, 'mirror': True}, f'weights ({wt})')
    if F:
        A = F['axes'][0]
        c1, c0 = page_counts(w, rr['scores']['t'], bins)
        check(f'weights ({wt}): the bars are the page\'s counts in its bins of the report\'s weights', ([b['h'] for b in A['bars'] if b['fc'] == TREATED], [b['h'] for b in A['bars'] if b['fc'] == CONTROL]), (c1.tolist(), (-c0).tolist()))
        check(f'weights ({wt}): the x range, the titles', (A['xlim'], A['xlabel'], A['title']), ([bins['start'], bins['end']], 'ATT Weight' if wt == 'att' else 'IPW Weight', 'weights histogram'))
for tag, plot in (('IPW, sorted', {'suffix': '_w', 'thr': 0.1, 'sort': True}), ('ATT, in the covariates\' order, threshold 0.2', {'suffix': '_att', 'thr': 0.2, 'sort': False})):
    F, code = chart('love', plot, f'Love plot ({tag})')
    if not F:
        continue
    A = F['axes'][0]
    bal = [b for b in rr['balance'] if b['smd'] is not None]
    if plot['sort']:
        bal = sorted(bal, key=lambda b: -abs(b['smd']))
    check(f'Love plot ({tag}): the covariates, top down, in the page\'s order', A['yticklabels'], [b['term'] for b in bal])
    un = [x for x in A['scatter'] if x['label'] == 'Unweighted']
    wtd = [x for x in A['scatter'] if x['label'].startswith('Weighted')]
    sfx = plot['suffix']
    check(f'Love plot ({tag}): the unweighted |SMD| of the report', bool(un) and maxdiff_([p_[0] for p_ in un[0]['xy']], [abs(b['smd']) for b in bal]) < 1e-9, True)
    check(f'Love plot ({tag}): the weighted |SMD| of the report', bool(wtd) and maxdiff_([p_[0] for p_ in wtd[0]['xy']], [abs(b['smd' + sfx]) for b in bal]) < 1e-7, True)
    check(f'Love plot ({tag}): the legend names the weights', F['legend'], ['Unweighted', f'Weighted ({"ATT" if sfx == "_att" else "IPW"} weights)'])
    thr_ = [ln for ln in A['lines'] if ln['color'] == ACCENT]
    check(f'Love plot ({tag}): the threshold line', [ln['x'][0] for ln in thr_], [plot['thr']])
    mx = max([plot['thr'] * 1.4] + [abs(b['smd']) for b in bal] + [abs(b['smd' + sfx]) for b in bal])
    check.near(f'Love plot ({tag}): the x range as the page\'s', A['xlim'][1], mx * 1.06, rel=1e-7)
    check(f'Love plot ({tag}): the titles', (A['xlabel'], A['title']), ('|Standardized Mean Difference|', 'Love plot'))
ate_r = call('treatment.estimates', **base)
att_r = call('treatment.estimates', effect_group=1, estimators=['ipw', 'ra', 'ipw_ra'], **base)
F, code = chart('estimates', {'ate': ['ipw', 'aipw', 'aipw_wls', 'ra', 'ipw_ra'], 'att': ['ipw', 'ra', 'ipw_ra']}, 'estimate comparison')
if F:
    A = F['axes'][0]
    want = [('Difference in Means', rr['naive']['estimate'], rr['naive']['lower'], rr['naive']['upper'])]
    want += [(e['label'], e['ate']['estimate'], e['ate']['lower'], e['ate']['upper']) for e in ate_r['estimates']]
    want += [(e['label'] + ' (ATT)', e['ate']['estimate'], e['ate']['lower'], e['ate']['upper']) for e in att_r['estimates']]
    check('estimate comparison: the items, top down, as the page lists them', A['yticklabels'], [w_[0] for w_ in want])
    pts = sorted((y_, x_) for ln in A['lines'] if ln['marker'] in ('s', 'o', 'D') for x_, y_ in zip(ln['x'], ln['y']))
    check('estimate comparison: each estimate the report\'s, in its row', len(pts) == len(want) and all(int(y_) == i and abs(x_ - w_[1]) <= 1e-7 * abs(w_[1]) for (y_, x_), (i, w_) in zip(pts, enumerate(want))), True)
    segs = sorted((min(s_[0][0], s_[1][0]), max(s_[0][0], s_[1][0]), s_[0][1]) for c_ in A['segments'] for s_ in c_['segs'])
    segs = sorted(segs, key=lambda z: z[2])
    check('estimate comparison: each interval the report\'s', len(segs) == len(want) and all(abs(a - w_[2]) <= 1e-6 * abs(w_[2]) + 1e-9 and abs(b - w_[3]) <= 1e-6 * abs(w_[3]) + 1e-9
                                                                                 for (a, b, _), w_ in zip(segs, want)), True)
    marks = {ln['marker']: (ln['color'], sorted(int(v) for v in ln['y'])) for ln in A['lines'] if ln['marker'] in ('s', 'o', 'D')}
    check('estimate comparison: the unadjusted square, the ATE circles, the ATT diamonds, in their colours', marks,
          {'s': (MUTED, [0]), 'o': ('#352921ff', [1, 2, 3, 4, 5]), 'D': (ACCENT, [6, 7, 8])})
    check('estimate comparison: the titles and the legend', (A['xlabel'], A['title'], F['legend']), ('Effect on earnings', 'estimate comparison', ['Unadjusted', 'ATE', 'ATT']))
F, code = chart('estimates', {'ate': ['ipw', 'ra'], 'att': []}, 'estimate comparison (IPW and RA, no ATT)')
if F:
    check('estimate comparison (IPW and RA): no patch, no ATT', ('inspect.getsource' in code, F['axes'][0]['yticklabels']), (False, ['Difference in Means', 'IPW', 'RA']))
check('an unknown graph is refused', 'error' in call('treatment.plot_code', kind='pie', **base), True)

sys.exit(check.done())
