#!/usr/bin/env python3
"""Analyze > Specialized Modeling > Meta-Analysis's backend
(resources/py/smui/meta.py), checked against statsmodels' meta_analysis,
StratifiedTable, OLS and WLS called directly, against the formulas written
out here (DerSimonian and Laird 1986, Paule and Mandel 1982, the REML
equation of Viechtbauer 2005, Higgins and Thompson 2002, Viechtbauer's
2007 Q-profile, Hartung and Knapp 2001, Higgins, Thompson and
Spiegelhalter's 2009 prediction interval, Egger et al. 1997, Begg and
Mazumdar 1994, RevMan's Hedges' g and zero-cell rules), against a small
example whose numbers are worked by hand, and by running the Python shown
under each result on a CSV export of the table.

    python3 resources/tests/smui/test_meta.py
"""
import math
import os
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd
from scipy import optimize, stats
import statsmodels.api as sm
from statsmodels.stats.contingency_tables import StratifiedTable
from statsmodels.stats.meta_analysis import combine_effects, effectsize_2proportions, effectsize_smd

from backend import FAILED, Checks, call, table

check = Checks()
check('meta.py imports', 'meta' in FAILED, False)
from smui import meta  # noqa: E402

rng = np.random.default_rng(20260926)

# ---- a simulated set of binary trials ------------------------------------------------------
k = 14
n1 = rng.integers(25, 320, k).astype(float)
n2 = np.round(n1 * rng.uniform(0.85, 1.15, k))
pc = rng.uniform(0.08, 0.35, k)
theta = rng.normal(-0.35, 0.3, k)
pt = 1 / (1 + np.exp(-(np.log(pc / (1 - pc)) + theta)))
e1 = rng.binomial(n1.astype(int), pt).astype(float)
e2 = rng.binomial(n2.astype(int), pc).astype(float)
e1[3], n1[3], e2[3], n2[3] = 0, 24, 3, 25        # a zero cell
e1[9], e2[9] = 0, 0                               # a double zero: left out of ratios
year = rng.permutation(np.arange(1991, 1991 + k)).astype(float)
quality = rng.choice(['low', 'moderate', 'high'], k).tolist()
dose = np.round(rng.uniform(10, 80, k), 1)
labels = [f'Trial {chr(65 + i)}' for i in range(k)]
cols = {'study': labels, 'year': year, 'events T': e1, 'n T': n1, 'events C': e2, 'n C': n2, 'quality': quality, 'dose (mg)': dose}
tid = table(cols, types={'quality': 'ordinal'}, levels={'quality': ['low', 'moderate', 'high']})
BIN = {'layout': 'bin', 'events1': 'events T', 'total1': 'n T', 'events2': 'events C', 'total2': 'n C', 'label': 'study', 'measure': 'or', 'cc': 0.5}

# ---- effect sizes ----------------------------------------------------------------------------
r = call('meta.combine', table=tid, inputs=BIN, method='dl', alpha=0.05, table_name='data')
check('no error', r.get('error'), None)
check('the double-zero study is left out, with its reason', [(d['row'], 'both groups' in d['reason']) for d in r['dropped']], [(9, True)])
check('the zero-cell study is corrected', r['corrected'], [3])
keep = np.arange(k) != 9
st = {s['row']: s for s in r['studies']}
plain = keep & ~np.isin(np.arange(k), [3])
e_sm, v_sm = effectsize_2proportions(e1[plain], n1[plain], e2[plain], n2[plain], statistic='odds-ratio')
check.near('log odds ratios = effectsize_2proportions', max(abs(st[i]['eff'] - e) for i, e in zip(np.flatnonzero(plain), e_sm)), 0.0, abs_=1e-13)
check.near('their variances too', max(abs(st[i]['var'] - v) for i, v in zip(np.flatnonzero(plain), v_sm)), 0.0, abs_=1e-13)
a, b, c, d = e1[3] + 0.5, n1[3] - e1[3] + 0.5, e2[3] + 0.5, n2[3] - e2[3] + 0.5
check.near('the zero-cell study: log((a+½)(d+½)/((b+½)(c+½)))', st[3]['eff'], math.log(a * d / (b * c)), rel=1e-12)
check.near('and its variance, the sum of 1/(cell+½)', st[3]['var'], 1 / a + 1 / b + 1 / c + 1 / d, rel=1e-12)
# statsmodels' own zero_correction=0.5 moves the studies without zeros too: why it is applied to the zero studies alone
e_all, _ = effectsize_2proportions(e1[keep], n1[keep], e2[keep], n2[keep], statistic='odds-ratio', zero_correction=0.5)
first = np.flatnonzero(plain)[0]
check('statsmodels\' float zero_correction shifts a study without zeros (the reason for the workaround)', abs(e_all[0] - st[first]['eff']) > 1e-4, True)
check.near('the odds ratio shown is exp of the log odds ratio', st[0]['ratio'], math.exp(st[0]['eff']), rel=1e-12)
eff = np.array([st[i]['eff'] for i in sorted(st)])
var = np.array([st[i]['var'] for i in sorted(st)])
check('rows in table order', sorted(st) == [s['row'] for s in r['studies']], True)

# risk ratio, risk difference, treatment-arm correction, no correction
rr = call('meta.combine', table=tid, inputs={**BIN, 'measure': 'rr'})
e_rr, v_rr = effectsize_2proportions(e1[plain], n1[plain], e2[plain], n2[plain], statistic='risk-ratio')
check.near('log risk ratios = effectsize_2proportions', rr['studies'][0]['eff'], float(e_rr[0]), rel=1e-12)
rd = call('meta.combine', table=tid, inputs={**BIN, 'measure': 'rd'})
check('risk difference keeps the double-zero study (its variance is not zero: corrected)', 9 in [s['row'] for s in rd['studies']], True)
check('and corrects only the study whose variance would be zero', rd['corrected'], [9])
e_rd, v_rd = effectsize_2proportions(e1[3:4], n1[3:4], e2[3:4], n2[3:4], statistic='diff')
check.near('the single-zero study is a plain risk difference', rd['studies'][3]['eff'], float(e_rd[0]), rel=1e-12)
nc = call('meta.combine', table=tid, inputs={**BIN, 'cc': 'none'})
check('no correction: the zero-cell study is left out', sorted(dd['row'] for dd in nc['dropped']), [3, 9])
tac = call('meta.combine', table=tid, inputs={**BIN, 'cc': 'tac'})
e_tac, v_tac = effectsize_2proportions(e1[3:4], n1[3:4], e2[3:4], n2[3:4], statistic='odds-ratio', zero_correction='tac')
check.near('treatment-arm correction = statsmodels "tac" for the zero study', tac['studies'][3]['eff'], float(e_tac[0]), rel=1e-12)

# two groups, continuous; effect and standard error
m1, m2 = rng.normal(10, 1, k), rng.normal(9.4, 1, k)
s1, s2 = rng.uniform(1.5, 3, k), rng.uniform(1.5, 3, k)
tc = table({'n1': n1, 'm1': m1, 's1': s1, 'n2': n2, 'm2': m2, 's2': s2, 'g': quality}, types={'g': 'nominal'})
CONT = {'layout': 'cont', 'n1': 'n1', 'mean1': 'm1', 'sd1': 's1', 'n2': 'n2', 'mean2': 'm2', 'sd2': 's2', 'measure': 'smd'}
rc = call('meta.combine', table=tc, inputs=CONT)
g_sm, vg_sm = effectsize_smd(m1, s1, n1, m2, s2, n2)
check.near("Hedges' g = effectsize_smd", max(abs(np.array([s['eff'] for s in rc['studies']]) - g_sm)), 0.0, abs_=1e-13)
N = n1 + n2
sp = np.sqrt(((n1 - 1) * s1 ** 2 + (n2 - 1) * s2 ** 2) / (N - 2))
g = (1 - 3 / (4 * N - 9)) * (m1 - m2) / sp
check.near("Hedges' g by RevMan's formula, J = 1 - 3/(4N - 9)", rc['studies'][5]['eff'], float(g[5]), rel=1e-12)
check.near("its variance N/(n1 n2) + g²/(2(N - 3.94))", rc['studies'][5]['var'], float(N[5] / (n1[5] * n2[5]) + g[5] ** 2 / (2 * (N[5] - 3.94))), rel=1e-12)
rm = call('meta.combine', table=tc, inputs={**CONT, 'measure': 'md'})
check.near('mean difference and its variance s1²/n1 + s2²/n2', (rm['studies'][2]['eff'], rm['studies'][2]['var']) == (float(m1[2] - m2[2]), float(s1[2] ** 2 / n1[2] + s2[2] ** 2 / n2[2])) and 1.0, 1.0)
se_col = np.sqrt(var)
te = table({'y': eff, 'se': se_col, 'v': var, 'lab': [labels[i] for i in sorted(st)]})
ES = {'layout': 'es', 'effect': 'y', 'se': 'se', 'label': 'lab'}
re_ = call('meta.combine', table=te, inputs=ES)
check.near('effect and standard error: the same pooled estimate', re_['chosen']['re']['est'], r['chosen']['re']['est'], rel=1e-12)
re_v = call('meta.combine', table=te, inputs={**ES, 'se': 'v', 'var': True})
check.near('a variance column gives the same', re_v['chosen']['re']['est'], r['chosen']['re']['est'], rel=1e-12)
re_l = call('meta.combine', table=te, inputs={**ES, 'log': True})
check('a log ratio is shown as a ratio', (re_l['measure']['display'], re_l['measure']['null'], re_l['measure']['log']), ('Ratio', 1.0, True))
bad = table({'y': [0.1, 0.2, np.nan, 0.3], 'se': [0.1, -0.2, 0.1, 0.1]})
rb = call('meta.combine', table=bad, inputs={'layout': 'es', 'effect': 'y', 'se': 'se'})
check('rows left out: a missing value, a negative standard error', [(dd['row'], dd['reason']) for dd in rb['dropped']], [(1, 'the standard error is not above zero'), (2, 'a missing value')])
check('roles missing: an error', 'error' in call('meta.combine', table=tid, inputs={'layout': 'bin', 'events1': 'events T'}), True)

# ---- pooling ------------------------------------------------------------------------------------
kk = len(eff)
w = 1 / var
fe = float(w @ eff / w.sum())
P = {x['key']: x for x in r['pooled']}
check.near('fixed effect = Σwy/Σw', P['fe']['est'], fe, rel=1e-12)
check.near('its standard error = 1/√Σw', P['fe']['se'], float(1 / math.sqrt(w.sum())), rel=1e-12)
Q = float(w @ (eff - fe) ** 2)
C = float(w.sum() - (w ** 2).sum() / w.sum())
t2_dl = max(0.0, (Q - (kk - 1)) / C)
check('the data are heterogeneous (Q > df)', Q > kk - 1, True)
check.near('DerSimonian-Laird τ² = (Q - df)/C', P['dl']['tau2'], t2_dl, rel=1e-12)
cm = combine_effects(eff, var, method_re='chi2')
check.near('DerSimonian-Laird estimate = combine_effects', P['dl']['est'], float(cm.mean_effect_re), rel=1e-12)
check.near('and its standard error', P['dl']['se'], float(cm.sd_eff_w_re), rel=1e-12)
ci = cm.conf_int(alpha=0.05, use_t=False)[1]
check.near('and its interval', P['dl']['lower'], float(ci[0]), rel=1e-12)
check.near('the z test p-value', P['dl']['p'], float(2 * stats.norm.sf(abs(cm.mean_effect_re / cm.sd_eff_w_re))), rel=1e-10)
cp = combine_effects(eff, var, method_re='iterated')
check.near('Paule-Mandel = combine_effects("iterated")', P['pm']['est'], float(cp.mean_effect_re), rel=1e-12)
check.near('Paule-Mandel τ² = combine_effects', P['pm']['tau2'], float(cp.tau2), rel=1e-12)


def qg(t2, y=eff, v=var):
    ww = 1 / (v + t2)
    mm = ww @ y / ww.sum()
    return float(ww @ (y - mm) ** 2)


t2_pm = optimize.brentq(lambda t: qg(t) - (kk - 1), 0, 10)
check.near('Paule-Mandel τ² solves Q(τ²) = k - 1 (statsmodels stops at |Q - df| < 1e-5)', P['pm']['tau2'], t2_pm, rel=1e-4)


def reml_ll(t2, y=eff, v=var):
    ww = 1 / (v + t2)
    mm = ww @ y / ww.sum()
    return -0.5 * (np.sum(np.log(v + t2)) + math.log(ww.sum()) + ww @ (y - mm) ** 2)


t2_ml = optimize.minimize_scalar(lambda t: -reml_ll(t), bounds=(0, 10), method='bounded', options={'xatol': 1e-12}).x
check.near('REML τ² maximises the restricted likelihood', P['reml']['tau2'], float(t2_ml), rel=1e-5)
wr = 1 / (var + P['reml']['tau2'])
mu_r = wr @ eff / wr.sum()
fixed_point = float((wr ** 2) @ ((eff - mu_r) ** 2 - var) / (wr ** 2).sum() + 1 / wr.sum())
check.near('and solves the REML equation τ² = Σw²((y-μ)² - v)/Σw² + 1/Σw', P['reml']['tau2'], fixed_point, rel=1e-9)
check.near('REML estimate = Σwy/Σw with w = 1/(v + τ²)', P['reml']['est'], float(mu_r), rel=1e-12)
check.near('the helpers with an intercept only: DL = statsmodels', meta.tau2_dl(eff, var), t2_dl, rel=1e-12)
check.near('PM = the Q-root', meta.tau2_pm(eff, var), t2_pm, rel=1e-9)
# Hartung-Knapp
hk = {x['key']: x for x in r['hksj_rows']}
wd = 1 / (var + t2_dl)
mu = wd @ eff / wd.sum()
se_hk = math.sqrt(float(wd @ (eff - mu) ** 2) / ((kk - 1) * wd.sum()))
check.near('Hartung-Knapp standard error √(Σw(y-μ)²/((k-1)Σw))', hk['dl']['se'], se_hk, rel=1e-12)
check.near('its interval uses t(k - 1): = combine_effects conf_int(use_t=True)', hk['dl']['upper'], float(cm.conf_int(alpha=0.05, use_t=True)[3][1]), rel=1e-12)
# prediction interval
tq = stats.t.isf(0.025, kk - 2)
check.near('prediction interval μ ± t(k-2)√(τ² + SE²)', r['pi']['upper'], float(mu + tq * math.sqrt(t2_dl + 1 / wd.sum())), rel=1e-12)
# Mantel-Haenszel
sti = StratifiedTable([np.array([[e1[i], n1[i] - e1[i]], [e2[i], n2[i] - e2[i]]]) for i in np.flatnonzero(keep)])
check.near('Mantel-Haenszel = StratifiedTable.logodds_pooled', P['mh']['est'], float(sti.logodds_pooled), rel=1e-12)
num = sum(e1[i] * (n2[i] - e2[i]) / (n1[i] + n2[i]) for i in np.flatnonzero(keep))
den = sum((n1[i] - e1[i]) * e2[i] / (n1[i] + n2[i]) for i in np.flatnonzero(keep))
check.near('= log(Σad/n / Σbc/n)', P['mh']['est'], math.log(num / den), rel=1e-12)
check.near('its Robins-Breslow-Greenland standard error', P['mh']['se'], float(sti.logodds_pooled_se), rel=1e-12)
bc_n = np.array([(n1[i] - e1[i]) * e2[i] / (n1[i] + n2[i]) for i in np.flatnonzero(keep)])
check.near('the Mantel-Haenszel weights of the studies are bc/n, normalised', max(abs(s_['w_mh'] - w_) for s_, w_ in zip(r['studies'], bc_n / bc_n.sum())), 0.0, abs_=1e-14)
or_raw = np.array([e1[i] * (n2[i] - e2[i]) / ((n1[i] - e1[i]) * e2[i]) for i in np.flatnonzero(keep)])   # raw odds ratios, no correction
check.near('with them exp(MH) = Σ w·OR, the raw odds ratios pooled', math.exp(P['mh']['est']), float((bc_n / bc_n.sum()) @ or_raw), rel=1e-12)

# ---- heterogeneity ------------------------------------------------------------------------------
h = r['het']
check.near('Q = Σw(y - fixed)²', h['q'], Q, rel=1e-12)
check.near('its p-value, χ²(k-1)', h['p'], float(stats.chi2.sf(Q, kk - 1)), rel=1e-10)
check.near('I² = (Q - df)/Q', h['i2'], (Q - (kk - 1)) / Q, rel=1e-12)
check.near('H = √(Q/df)', h['h'], math.sqrt(Q / (kk - 1)), rel=1e-12)
selnH = 0.5 * (math.log(Q) - math.log(kk - 1)) / (math.sqrt(2 * Q) - math.sqrt(2 * kk - 3))
Hlo = math.sqrt(Q / (kk - 1)) * math.exp(-stats.norm.isf(0.025) * selnH)
check.near('H lower limit, Higgins and Thompson\'s SE of ln H', h['h_lower'], max(1.0, Hlo), rel=1e-12)
check.near('I² lower limit = (H² - 1)/H² at it', h['i2_lower'], max(0.0, (Hlo ** 2 - 1) / Hlo ** 2), rel=1e-12)
check.near('τ² Q-profile lower limit: Q(τ²) = χ²(0.975, k-1)', qg(h['tau2_lower']), float(stats.chi2.isf(0.025, kk - 1)), rel=1e-9)
check.near('τ² Q-profile upper limit: Q(τ²) = χ²(0.025, k-1)', qg(h['tau2_upper']), float(stats.chi2.ppf(0.025, kk - 1)), rel=1e-9)

# ---- a small example worked by hand -----------------------------------------------------------
# effects 0, 2, 4 with variance 1 each: fixed = 2, Q = 8, C = 3 - 1 = 2, τ²(DL) = (8 - 2)/2 = 3;
# with equal variances Paule-Mandel (8/(1 + τ²) = 2) and REML (s² - v = 4 - 1) give 3 too;
# the random-effects SE is √((1 + 3)/3); I² = 6/8, H = 2.
th = table({'y': [0.0, 2.0, 4.0], 'se': [1.0, 1.0, 1.0]})
rh = call('meta.combine', table=th, inputs={'layout': 'es', 'effect': 'y', 'se': 'se'})
ph = {x['key']: x for x in rh['pooled']}
check('by hand: fixed effect 2, SE √(1/3)', (round(ph['fe']['est'], 12), round(ph['fe']['se'], 12)), (2.0, round(math.sqrt(1 / 3), 12)))
check('by hand: τ² = 3 by DerSimonian-Laird, Paule-Mandel and REML', [round(ph[m_]['tau2'], 4) for m_ in ('dl', 'pm', 'reml')], [3.0, 3.0, 3.0])
check.near('by hand: random-effects SE √(4/3)', ph['dl']['se'], math.sqrt(4 / 3), rel=1e-12)
check('by hand: Q = 8, I² = 75%, H = 2', (round(rh['het']['q'], 12), round(rh['het']['i2'], 12), round(rh['het']['h'], 12)), (8.0, 0.75, 2.0))
# Q below its degrees of freedom: statsmodels' DerSimonian-Laird τ² is negative; the report uses 0
tl = table({'y': [0.10, 0.12, 0.11, 0.09], 'se': list(np.sqrt([0.04, 0.05, 0.03, 0.06]))})
rl = call('meta.combine', table=tl, inputs={'layout': 'es', 'effect': 'y', 'se': 'se'})
pl = {x['key']: x for x in rl['pooled']}
check('Q < df: statsmodels leaves τ² negative', rl['raw_tau2_dl'] < 0, True)
check('the report: τ² = 0 and random = fixed', (pl['dl']['tau2'], pl['dl']['est'] == pl['fe']['est'], pl['pm']['tau2'], pl['reml']['tau2']), (0.0, True, 0.0, 0.0))
check('I² is 0 and H is 1 (truncated)', (rl['het']['i2'], rl['het']['h']), (0.0, 1.0))
check('and statsmodels\' square-root warnings for those replaced numbers do not reach the report', rl.get('warnings'), None)
tq = table({'y': [0.2, 0.2, 0.2], 'se': [0.1, 0.2, 0.3]})
rq = call('meta.combine', table=tq, inputs={'layout': 'es', 'effect': 'y', 'se': 'se'})
check('identical effects (Q = 0): I² 0, H 1, no division warning', (rq['het']['q'], rq['het']['i2'], rq['het']['h'], rq.get('warnings')), (0.0, 0.0, 1.0, None))
t2s = table({'y': [0.2, 0.3], 'se': [0.1, 0.2]})
r2s = call('meta.combine', table=t2s, inputs={'layout': 'es', 'effect': 'y', 'se': 'se'}, method='pm')
check('two studies: pooled, no prediction interval', (r2s['k'], r2s['pi']), (2, None))
te3 = table({'y': [0.1, 0.4, 0.2, 0.3], 'se': [0.2, 0.2, 0.2, 0.2]})
be3 = call('meta.bias', table=te3, inputs={'layout': 'es', 'effect': 'y', 'se': 'se'})
check('equal standard errors: no Egger regression (the precision is constant), no warning', (be3.get('same_se'), 'egger' in be3, be3.get('warnings')), (True, False, None))
check('two studies: no small-study tests', 'egger' in call('meta.bias', table=t2s, inputs={'layout': 'es', 'effect': 'y', 'se': 'se'}), False)
check('two studies: leave-one-out says it needs three', 'three' in call('meta.leave_one_out', table=t2s, inputs={'layout': 'es', 'effect': 'y', 'se': 'se'})['error'], True)
t1 = table({'y': [0.3], 'se': [0.2]})
r1 = call('meta.combine', table=t1, inputs={'layout': 'es', 'effect': 'y', 'se': 'se'})
check('one study: its own estimate, no NaN', (r1['chosen']['re']['est'], r1['chosen']['re']['se'], r1['pi']), (0.3, 0.2, None))

# ---- subgroups ---------------------------------------------------------------------------------------
rg = call('meta.combine', table=tid, inputs={**BIN, 'group': 'quality'}, method='dl')
sg = rg['subgroups']
check('subgroups in the level order', [g_['level'] for g_ in sg['groups']], [lv for lv in ['low', 'moderate', 'high'] if any(quality[i] == lv for i in np.flatnonzero(keep))])
qw = 0.0
for g_ in sg['groups']:
    idx = [i for i, s in enumerate(r['studies']) if quality[s['row']] == g_['level']]
    if len(idx) > 1:
        cg = combine_effects(eff[idx], var[idx], method_re='chi2')
        check.near(f'subgroup {g_["level"]}: fixed = combine_effects', g_['fe']['est'], float(cg.mean_effect_fe), rel=1e-12)
        check.near(f'subgroup {g_["level"]}: random = combine_effects', g_['re']['est'], float(cg.mean_effect_re if cg.tau2 > 0 else cg.mean_effect_fe), rel=1e-12)
        qw += float(cg.q)
tf = sg['tests'][0]
check.near('fixed-effect Q between = Q total - Σ Q within', tf['q'], Q - qw, rel=1e-9)
check('its df is the number of subgroups - 1', tf['df'], len(sg['groups']) - 1)
check('a random-effects test too', sg['tests'][1]['model'].startswith('Random effects'), True)

# ---- small-study effects ------------------------------------------------------------------------
bi = call('meta.bias', table=tid, inputs=BIN, method='dl', table_name='data')
se_ = np.sqrt(var)
ols = sm.OLS(eff / se_, sm.add_constant(1 / se_)).fit()
check.near("Egger's intercept = OLS of y/se on 1/se", bi['egger']['intercept'], float(ols.params[0]), rel=1e-12)
check.near('its p-value, t(k - 2)', bi['egger']['p'], float(ols.pvalues[0]), rel=1e-10)
wls = sm.WLS(eff, sm.add_constant(se_), weights=1 / var).fit()
check.near('= the slope of y on se weighted by 1/v (the same regression)', bi['egger']['intercept'], float(wls.params[1]), rel=1e-9)
tstar = (eff - fe) / np.sqrt(var - 1 / w.sum())
check.near("Begg's Kendall τ of the standardized effects and the variances", bi['begg']['tau'], float(stats.kendalltau(tstar, var).statistic), rel=1e-12)

# ---- sensitivity --------------------------------------------------------------------------------------
lo = call('meta.leave_one_out', table=tid, inputs=BIN, method='dl', table_name='data')
check('leave-one-out: one line per study', len(lo['rows']), kk)
cl = combine_effects(eff[1:], var[1:], method_re='chi2')
check.near('leaving out the first = combine_effects of the rest', lo['rows'][0]['est'], float(cl.mean_effect_re if cl.tau2 > 0 else cl.mean_effect_fe), rel=1e-12)
cu = call('meta.cumulative', table=tid, inputs=BIN, order_by='year', method='dl', table_name='data')
yr = [year[s['row']] for s in r['studies']]
check('cumulative: studies in the order of year', [cols['year'][row['row']] for row in cu['rows']], sorted(yr))
check.near('its last line is the whole meta-analysis', cu['rows'][-1]['est'], P['dl']['est'], rel=1e-12)
check('its first line is one study', (cu['rows'][0]['k'], cu['rows'][0]['tau2']), (1, 0.0))
cq = call('meta.cumulative', table=tid, inputs=BIN, order_by='quality', descending=True, method='pm')
check('by an ordinal column, descending', [quality[row['row']] for row in cq['rows']][:1], ['high'])

# ---- meta-regression ----------------------------------------------------------------------------------
mr = call('meta.regression', table=tid, inputs=BIN, covariates=['dose (mg)'], method='dl', table_name='data')
check('no error', mr.get('error'), None)
X = sm.add_constant(dose[keep])
W0 = np.diag(1 / var)
Pm = W0 - W0 @ X @ np.linalg.inv(X.T @ W0 @ X) @ X.T @ W0
qe = float(eff @ Pm @ eff)
t2_mm = max(0.0, (qe - (kk - 2)) / float(np.trace(Pm)))
check.near('residual τ² by the method of moments (Q_E - (k - p))/tr P', mr['tau2'], t2_mm, rel=1e-10)
check.near('Q_E = the weighted residual sum of squares at τ² = 0', mr['qe'], qe, rel=1e-10)
wf = sm.WLS(eff, X, weights=1 / (var + t2_mm)).fit(cov_type='fixed scale')
check.near('slope = WLS with the weights 1/(v + τ²)', mr['terms'][1]['est'], float(wf.params[1]), rel=1e-10)
check.near('its standard error, the scale fixed at 1', mr['terms'][1]['se'], float(wf.bse[1]), rel=1e-10)
check('term names', [t_['term'] for t_ in mr['terms']], ['Intercept', 'dose (mg)'])
check.near('Q_M (one covariate) = z²', mr['qm']['stat'], float(wf.tvalues[1] ** 2), rel=1e-9)
mr2 = call('meta.regression', table=tid, inputs=BIN, covariates=['dose (mg)', 'quality'], method='reml', table_name='data')
Xq = pd.get_dummies(pd.Categorical([quality[i] for i in np.flatnonzero(keep)], categories=['low', 'moderate', 'high']), drop_first=True).to_numpy(float)
X2 = np.column_stack([np.ones(kk), Xq, dose[keep]])


def reml_ll_x(t2):
    ww = 1 / (var + t2)
    XtWX = X2.T @ (X2 * ww[:, None])
    beta = np.linalg.solve(XtWX, X2.T @ (ww * eff))
    res_ = eff - X2 @ beta
    return -0.5 * (np.sum(np.log(var + t2)) + np.linalg.slogdet(XtWX)[1] + ww @ res_ ** 2)


t2_x = optimize.minimize_scalar(lambda t: -reml_ll_x(t), bounds=(0, 5), method='bounded', options={'xatol': 1e-12}).x
check.near('residual REML τ² with a nominal covariate maximises the restricted likelihood', mr2['tau2'], float(t2_x), rel=1e-4, abs_=1e-8)
check('nominal covariates dummy coded against the first level', [t_['term'] for t_ in mr2['terms']], ['Intercept', 'quality[moderate]', 'quality[high]', 'dose (mg)'])
check('a bubble-plot curve for the continuous covariate only', [c_['covariate'] for c_ in mr2['curves']], ['dose (mg)'])
check('too few studies: an error', 'error' in call('meta.regression', table=th, inputs={'layout': 'es', 'effect': 'y', 'se': 'se'}, covariates=['se']), True)
# a covariate such as a year (about 2000 beside the intercept): the same model as with the year centered, so the same τ²
# and standard errors; X'WX formed from it squares the design's condition number (τ² was good to six digits)
tyc = table({**cols, 'year c': year - 2000}, types={'quality': 'ordinal'}, levels={'quality': ['low', 'moderate', 'high']})
for meth in ('dl', 'pm', 'reml'):
    for covs in (['year'], ['year', 'dose (mg)', 'quality']):
        ra = call('meta.regression', table=tyc, inputs=BIN, covariates=covs, method=meth)
        rc_ = call('meta.regression', table=tyc, inputs=BIN, covariates=['year c' if c_ == 'year' else c_ for c_ in covs], method=meth)
        check.near(f'a year covariate: τ² as with the year centered ({meth}, {len(covs)} covariates)', ra['tau2'], rc_['tau2'], rel=1e-10)
        check.near(f'and the slope\'s standard error ({meth}, {len(covs)} covariates)', ra['terms'][1]['se'], rc_['terms'][1]['se'], rel=1e-10)

# ---- methods and Hartung-Knapp through the other calls ---------------------------------------------------
r_pm = call('meta.combine', table=tid, inputs=BIN, method='pm', hksj=True)
check.near('with Hartung-Knapp the forest plot\'s random effects are the HK ones', r_pm['chosen']['re']['se'], [x for x in r_pm['hksj_rows'] if x['key'] == 'pm'][0]['se'], rel=1e-12)
check('and they are t intervals', r_pm['chosen']['re']['df'], kk - 1)
sv = call('meta.save', table=tid, inputs=BIN)
check.near('Save Columns: weights in per cent sum to 100', sum(sv['w_re']), 100.0, rel=1e-12)
check('Save Columns: one value per study row', len(sv['rows']), kk)

# ---- the Python shown under each result runs on a CSV export and gives the report's numbers -------------
work = tempfile.mkdtemp()
pd.DataFrame(cols).to_csv(os.path.join(work, 'data.csv'), index=False)


def run(code):
    p = subprocess.run([sys.executable, '-c', code], cwd=work, capture_output=True, text=True, timeout=300)
    if p.returncode:
        print(p.stderr[-800:])
    return p


def last(p):
    return [float(x) for x in p.stdout.strip().splitlines()[-1].split()]


for meth in ('dl', 'pm', 'reml'):
    rr_ = call('meta.combine', table=tid, inputs=BIN, method=meth, table_name='data')
    p = run(rr_['code'])
    check(f'the Summary Estimates code runs ({meth})', p.returncode, 0)
    if not p.returncode:
        vals = last(p)
        pp = {x['key']: x for x in rr_['pooled']}
        want = [pp['fe']['est'], pp['fe']['se'], pp['dl']['est'], pp['dl']['se'], pp['dl']['tau2'], pp['pm']['est'], pp['pm']['tau2'], pp['reml']['est'], pp['reml']['tau2']]
        check.near(f'and prints the report\'s estimates and τ² ({meth})', max(abs(a_ - b_) / max(1e-12, abs(b_)) for a_, b_ in zip(vals, want)), 0.0, abs_=1e-9)
        pi_line = [ln for ln in p.stdout.splitlines() if ln.startswith('prediction interval')][0].split()[2:]
        check.near(f'and the prediction interval ({meth})', float(pi_line[1]), rr_['pi']['upper'], rel=1e-9)
rh_ = call('meta.combine', table=tid, inputs=BIN, method='dl', hksj=True, table_name='data')
p = run(rh_['code'])
check('the Summary Estimates code with Hartung-Knapp runs', p.returncode, 0)
if not p.returncode:
    hk_line = [float(x) for x in [ln for ln in p.stdout.splitlines() if ln.startswith('Hartung-Knapp')][0].split()[1:]]
    hkr = {x['key']: x for x in rh_['hksj_rows']}
    want = [hkr['dl']['lower'], hkr['dl']['upper'], hkr['pm']['lower'], hkr['pm']['upper'], hkr['reml']['lower'], hkr['reml']['upper']]
    check.near('and prints the report\'s Hartung-Knapp intervals (DL, PM, REML)', max(abs(a_ - b_) for a_, b_ in zip(hk_line, want)), 0.0, abs_=1e-9)
p = run(bi['code'])
check("Egger's code runs", p.returncode, 0)
if not p.returncode:
    check.near("and gives the report's intercept", last(p)[0], bi['egger']['intercept'], rel=1e-9)
for meth, hks in (('dl', False), ('reml', True)):
    lo_ = call('meta.leave_one_out', table=tid, inputs=BIN, method=meth, hksj=hks, table_name='data')
    p = run(lo_['code'])
    check(f'the leave-one-out code runs ({meth})', p.returncode, 0)
    if not p.returncode:
        lines = [ln.rsplit(' ', 3)[1:] for ln in p.stdout.strip().splitlines()]
        check.near(f'and gives every leave-one-out estimate and SE ({meth}{", HK" if hks else ""})',
                   max(max(abs(float(a_) - row['est']), abs(float(b_) - row['se'])) for (a_, b_, _), row in zip(lines, lo_['rows'])), 0.0, abs_=1e-9)
cu2 = call('meta.cumulative', table=tid, inputs=BIN, order_by='quality', method='pm', table_name='data')
p = run(cu2['code'])
check('the cumulative code runs', p.returncode, 0)
if not p.returncode:
    lines = [ln.rsplit(' ', 3) for ln in p.stdout.strip().splitlines()]
    check.near('and gives every cumulative estimate', max(abs(float(ln[1]) - row['est']) for ln, row in zip(lines, cu2['rows'])), 0.0, abs_=1e-9)
    check('in the same order', [int(ln[0].split()[0]) for ln in lines], [row['k'] for row in cu2['rows']])
for meth, covs in (('dl', ['dose (mg)', 'quality']), ('pm', ['dose (mg)', 'quality']), ('reml', ['dose (mg)', 'quality']), ('pm', ['year', 'dose (mg)'])):
    mm_ = call('meta.regression', table=tid, inputs=BIN, covariates=covs, method=meth, table_name='data')
    p = run(mm_['code'] + '\nprint(*fit.params)')
    check(f'the meta-regression code runs ({meth}, {", ".join(covs)})', p.returncode, 0)
    if not p.returncode:
        lines = p.stdout.strip().splitlines()
        check.near(f'and gives the report\'s τ² ({meth}, {", ".join(covs)})', float(lines[0]), mm_['tau2'], rel=1e-10, abs_=1e-12)
        check.near(f'and coefficients ({meth}, {", ".join(covs)})', max(abs(a_ - t_['est']) for a_, t_ in zip(last(p), mm_['terms'])), 0.0, abs_=1e-8)
rcont = call('meta.combine', table=tc, inputs=CONT, table_name='cont')
pd.DataFrame({'n1': n1, 'm1': m1, 's1': s1, 'n2': n2, 'm2': m2, 's2': s2, 'g': quality}).to_csv(os.path.join(work, 'cont.csv'), index=False)
p = run(rcont['code'])
check("the Hedges' g code runs", p.returncode, 0)
if not p.returncode:
    check.near('and gives the report\'s random effects', last(p)[2], [x for x in rcont['pooled'] if x['key'] == 'dl'][0]['est'], rel=1e-9)
# rows excluded in the report: the code keeps the report's rows
rx = call('meta.combine', table=tid, inputs=BIN, rows=[i for i in range(k) if i not in (0, 5)], table_name='data')
p = run(rx['code'])
if not p.returncode:
    check.near('with rows left out, the code keeps the report\'s rows', last(p)[0], [x for x in rx['pooled'] if x['key'] == 'fe'][0]['est'], rel=1e-9)
else:
    check('the code with rows left out runs', p.returncode, 0)


# ---- the graphs' matplotlib code, run with Agg on the CSV, against the report's numbers --------------------------------
# meta.plot_code writes the code under each graph from what the page chose (sent
# here as the page sends it); the figure it draws must hold the report's
# numbers: the forest plot's rows and texts as smui-p-meta.js forestItems
# writes them from meta.combine, its squares, diamonds and prediction
# interval; the leave-one-out and cumulative estimates; the funnel's points
# and lines from meta.bias; the bubble plots' studies, fit and band from
# meta.regression.
from decimal import Decimal, ROUND_HALF_UP  # noqa: E402

from test_charts import maxdiff, run_snippet_more  # noqa: E402

chart_dir = tempfile.mkdtemp(prefix='smui-meta-charts-')
STUDY_C, RE_C, TEXT_C, MUTED_C = '#2a6db3ff', '#b0413eff', '#352921ff', '#786b5dff'
METHOD_NAME = {'dl': 'DerSimonian–Laird', 'pm': 'Paule–Mandel', 'reml': 'REML'}


def js_fixed(v, digits):
    """SM.util.fmt(v, { digits }): JavaScript's toFixed (the exact binary value, halves away from zero), a minus sign."""
    if v is None or not math.isfinite(v):
        return '.'
    s_ = str(Decimal(float(v)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))
    return '−' + s_[1:] if s_.startswith('-') else s_


def js_sig(v, digits):
    """SM.util.fmt(v, { sig })."""
    v = float(v)
    if v.is_integer() and abs(v) < 1e15:
        s_ = str(int(v))
    elif abs(v) >= 1e9 or abs(v) < 1e-4:
        m_, e_ = f'{v:.{min(digits, 5) - 1}e}'.split('e')
        s_ = f'{m_}e{int(e_)}'
    else:
        s_ = f'{v:.{digits}g}'
        s_ = str(int(float(s_))) if 'e' in s_ else (s_.rstrip('0').rstrip('.') if '.' in s_ else s_)
    return '−' + s_[1:] if s_.startswith('-') else s_


def js_ptext(p):
    return '.' if p is None or not math.isfinite(p) else ('< 0.0001' if p < 0.0001 else f'= {js_fixed(p, 4)}')


check('the page\'s formats: toFixed rounds halves away from zero', [js_fixed(x, 2) for x in (0.125, -0.125, 2.675, 1.005, 0.5)], ['0.13', '−0.13', '2.67', '1.00', '0.50'])


def forest_items(res, o):
    """smui-p-meta.js forestItems from meta.combine's result and the page's options o."""
    fe_on, re_on = o.get('showFE', True), o.get('showRE', True)
    both = fe_on and re_on
    mh_on = bool(o.get('mh')) and bool(res.get('mh'))
    srt = o.get('sort', 'table')
    lo_ = o.get('labelOrder') or []

    def order(lst):
        if srt == 'effect':
            return sorted(lst, key=lambda s_: s_['eff'])
        if srt == 'weight':
            return sorted(lst, key=lambda s_: -s_['w_re'])
        if srt == 'precision':
            return sorted(lst, key=lambda s_: s_['se'])
        if srt == 'label':
            return sorted(lst, key=lambda s_: lo_.index(s_['row']))
        return list(lst)

    wfe = lambda s_: s_['w_mh'] if mh_on and s_.get('w_mh') is not None else s_['w_fe']   # noqa: E731
    study = lambda s_: {'kind': 'study', 'label': s_['label'], 'est': s_['eff'], 'lo': s_['lower'], 'hi': s_['upper'], 'wFE': wfe(s_), 'wRE': s_['w_re']}   # noqa: E731

    def het(i2, tau2, q, df, p):
        parts = [f'I² = {js_fixed(100 * i2, 0)}%'] if i2 is not None else []
        if tau2 is not None:
            parts.append(f'τ² = {js_sig(tau2, 3)}')
        if q is not None and df:
            parts.append(f'Q = {js_fixed(q, 2)}, df = {df}, p {js_ptext(p)}')
        return 'Heterogeneity: ' + '; '.join(parts) if parts else None

    items = [{'kind': 'head'}]
    sg_on = bool(res.get('subgroups')) and o.get('subgroups', True)
    if sg_on:
        for g_ in res['subgroups']['groups']:
            items.append({'kind': 'group', 'label': g_['level']})
            members = [s_ for s_ in res['studies'] if s_['group'] == g_['level']]
            items += [study(s_) for s_ in order(members)]
            wf, wr = sum(wfe(s_) for s_ in members), sum(s_['w_re'] for s_ in members)
            gfe = g_['mh'] if mh_on and g_['mh'] else g_['fe']
            if fe_on and g_['k'] > 1:
                items.append({'kind': 'diamond', 'which': 'fe', 'sub': True, 'label': 'Subtotal, fixed effect (M–H)' if mh_on and g_['mh'] else 'Subtotal, fixed effect',
                              'est': gfe['est'], 'lo': gfe['lower'], 'hi': gfe['upper'], 'wFE': wf, 'wRE': None if both else wr})
            if re_on and g_['k'] > 1:
                items.append({'kind': 'diamond', 'which': 're', 'sub': True, 'label': 'Subtotal, random effects', 'est': g_['re']['est'], 'lo': g_['re']['lower'], 'hi': g_['re']['upper'],
                              'wFE': None if both else wf, 'wRE': wr})
            if o.get('stats', True) and g_['k'] > 1:
                t_ = het(g_['i2'], g_['tau2'] if re_on else None, g_['q'], g_['df'], g_['p'])
                if t_:
                    items.append({'kind': 'text', 'label': t_})
            items.append({'kind': 'gap'})
    else:
        items += [study(s_) for s_ in order(res['studies'])] + [{'kind': 'gap'}]
    ch = res['chosen']
    fed = res['mh'] if mh_on else ch['fe']
    if fe_on:
        items.append({'kind': 'diamond', 'which': 'fe', 'sub': False, 'label': 'Fixed effect (Mantel–Haenszel)' if mh_on else 'Fixed effect', 'est': fed['est'], 'lo': fed['lower'], 'hi': fed['upper'],
                      'wFE': 1, 'wRE': None if both else 1})
    if re_on:
        items.append({'kind': 'diamond', 'which': 're', 'sub': False, 'label': f'Random effects ({METHOD_NAME[res["method"]]}{", HK" if res["hksj"] else ""})',
                      'est': ch['re']['est'], 'lo': ch['re']['lower'], 'hi': ch['re']['upper'], 'wFE': None if both else 1, 'wRE': 1})
    if re_on and o.get('showPI', True) and res['pi']:
        items.append({'kind': 'pi', 'label': 'Prediction interval', 'est': res['pi']['est'], 'lo': res['pi']['lower'], 'hi': res['pi']['upper']})
    if o.get('stats', True):
        h_ = res['het']
        t_ = het(h_.get('i2'), h_.get('tau2') if re_on else None, h_['q'], h_['df'], h_['p'])
        if t_ and res['k'] > 1:
            items.append({'kind': 'text', 'label': t_})
        main = ch['re'] if re_on else ch['fe']
        if main.get('p') is not None:
            items.append({'kind': 'text', 'label': f'Test for overall effect{" (random)" if re_on else ""}: {"t" if main.get("df") else "z"} = {js_fixed(main["z"], 2)}, p {js_ptext(main["p"])}'})
        if sg_on and res['subgroups']['tests']:
            tt = res['subgroups']['tests'][1 if re_on else 0]
            items.append({'kind': 'text', 'label': f'Test for subgroup differences ({"random" if re_on else "fixed"}): Q = {js_fixed(tt["q"], 2)}, df = {tt["df"]}, p {js_ptext(tt["p"])}'})
    y_ = 0.0
    for it in items:
        if it['kind'] == 'head':
            it['y'] = -1.25
        elif it['kind'] == 'gap':
            it['y'] = None
            y_ += 0.5
        else:
            it['y'] = y_
            y_ += 1
    return items, y_ - 1


def page_decimals(res):
    if res['measure']['log']:
        return 2
    w_ = sorted(x for x in (s_['upper'] - s_['lower'] for s_ in res['studies']) if x > 0)
    med = w_[len(w_) // 2] if w_ else 1
    return max(0, min(4, 1 - math.floor(math.log10(med))))


def forest_layout(res, o, items, last, rng):
    """A layout as forestPlot makes one (the widths from the texts' lengths, a plot 380 pixels wide)."""
    both = o.get('showFE', True) and o.get('showRE', True)
    ncol = (2 if both else 1) if o.get('weights', True) else 0
    lab_w = 150.0
    ci_w = 170.0
    plot_w = 380.0
    W = round(lab_w + plot_w + ci_w + 62 * ncol + 16)
    inner = W - 16
    at, doms = 0.0, []
    for w_ in [lab_w, plot_w, ci_w] + [62] * ncol:
        doms.append([at / inner, min(1, (at + w_) / inner)])
        at += w_
    return {'W': W, 'H': round((last + 3.4) * 20 + 66), 'lab': doms[0], 'plot': doms[1], 'ci': doms[2], 'w': doms[3:], **rng}


def forest_check(label, tid_, inputs, frame_, name, o, rng, method='dl', hksj=False, rows=None):
    kw = dict(table=tid_, inputs=inputs, method=method, alpha=0.05, hksj=hksj, table_name=name)
    if rows is not None:
        kw['rows'] = rows
    res = call('meta.combine', **kw)
    items, last = forest_items(res, o)
    lay = forest_layout(res, o, items, last, rng)
    rr = call('meta.plot_code', kind='forest', plot={**o, 'layout': lay}, **kw)
    code = rr.get('plot_code') or ''
    check(f'{label}: the code is written', rr.get('error'), None)
    out, err = run_snippet_more(code, frame_, name, chart_dir)
    check(f'{label}: the code runs', err, None)
    if err:
        print(err)
        return None, code
    check(f'{label}: it ends with plt.show()', code.rstrip().split('\n')[-1], 'plt.show()')
    F = out['figures'][0]
    ax = F['axes'][0]
    m_ = res['measure']
    tx = math.exp if m_['log'] else (lambda v: v)
    log = m_['log'] and o.get('log', True)
    dec = page_decimals(res)
    both = o.get('showFE', True) and o.get('showRE', True)
    wkeys = (['wFE', 'wRE'] if both else ['wRE' if o.get('showRE', True) else 'wFE']) if o.get('weights', True) else []
    heads = {'wFE': 'Weight\nfixed', 'wRE': 'Weight\nrandom'} if both else {k_: 'Weight' for k_ in wkeys}
    W = lay['W']
    dom = {'lab': lay['lab'], 'ci': lay['ci'], **{k_: d_ for k_, d_ in zip(wkeys, lay['w'])}}
    fx = lambda c_, f: (8 + (dom[c_][0] + f * (dom[c_][1] - dom[c_][0])) * (W - 16)) / W   # noqa: E731
    ci_text = lambda it: f'{js_fixed(tx(it["est"]), dec)} [{js_fixed(tx(it["lo"]), dec)}, {js_fixed(tx(it["hi"]), dec)}]'   # noqa: E731
    cut = lambda s_: s_ if len(s_) <= 36 else s_[:35] + '…'   # noqa: E731
    want = [('Study', -1.25, fx('lab', 0.01)), (f'{m_["display"]} [95% CI]', -1.25, fx('ci', 0.99))] + [(heads[k_], -1.25, fx(k_, 0.97)) for k_ in wkeys]
    for it in items:
        if it['kind'] == 'text':
            want.append((it['label'], it['y'], fx('lab', 0.01)))
        elif it['kind'] not in ('head', 'gap'):
            want.append((cut(str(it['label'])), it['y'], fx('lab', 0.01)))
            if it['kind'] != 'group':
                want.append((ci_text(it), it['y'], fx('ci', 0.99)))
                want += [(f'{js_fixed(100 * it[k_], 1)}%', it['y'], fx(k_, 0.97)) for k_ in wkeys if it.get(k_) is not None]
    got = [(t_['s'], t_['y']) for t_ in ax['texts']]
    check(f'{label}: every text of the plot, row by row, as the page writes it from the report', got, [(s_, y_) for s_, y_, _ in want])
    if got != [(s_, y_) for s_, y_, _ in want]:
        for a_, b_ in zip(got, want):
            if a_ != b_[:2]:
                print('   got', a_, 'want', b_[:2])
                break
    check(f'{label}: the texts in their columns', len(ax['texts']) == len(want) and all(abs(t_['x'] - x_) < 2e-4 for t_, (_, _, x_) in zip(ax['texts'], want)), True)
    st = [it for it in items if it['kind'] == 'study']
    wk = [it['wRE' if o.get('showRE', True) else 'wFE'] for it in st]
    sq = ax['scatter'][0] if ax['scatter'] else {'xy': [], 'sizes': []}
    check(f'{label}: a square per study at its effect, in the plot\'s order', maxdiff([p_ for xy in sq['xy'] for p_ in xy], [v for it in st for v in (tx(it['est']), it['y'])]) < 1e-9, True)
    check(f'{label}: the squares\' areas from the weights', maxdiff(sq['sizes'], [(max(5, 17 * math.sqrt(w_ / max(max(wk), 1e-12))) * 0.72) ** 2 for w_ in wk]) < 1e-9, True)
    dia = [it for it in items if it['kind'] == 'diamond']
    polys = [p_ for p_ in ax['patches'] if p_['type'] == 'Polygon']
    want_d = [[tx(it['lo']), it['y'], tx(it['est']), it['y'] - (0.3 if it['sub'] else 0.36), tx(it['hi']), it['y'], tx(it['est']), it['y'] + (0.3 if it['sub'] else 0.36)] for it in dia]
    check(f'{label}: a diamond per pooled estimate, its interval, the report\'s', len(polys) == len(dia) and all(maxdiff([v for q_ in p_['xy'][:4] for v in q_], w_) < 1e-9 for p_, w_ in zip(polys, want_d)), True)
    check(f'{label}: the diamonds\' colours, the subtotals pale', [p_['fc'] for p_ in polys], [(RE_C if it['which'] == 're' else TEXT_C)[:7] + ('8c' if it['sub'] else 'ff') for it in dia])
    lo_x, hi_x = ax['xlim']
    ivs = [ln for ln in ax['lines'] if ln['color'] == TEXT_C and abs(ln['lw'] - 0.864) < 1e-9]
    check(f'{label}: the studies\' intervals, cut at the axis', maxdiff([v for ln in ivs for v in ln['x']], [v for it in st for v in (max(tx(it['lo']), lo_x), min(tx(it['hi']), hi_x))]) < 1e-9, True)
    arrows = sorted((ln['marker'], ln['y'][0]) for ln in ax['lines'] if ln['marker'] in ('<', '>'))
    check(f'{label}: an arrow where an interval runs past the axis', arrows, sorted([('<', it['y']) for it in st if tx(it['lo']) < lo_x] + [('>', it['y']) for it in st if tx(it['hi']) > hi_x]))
    pis = [it for it in items if it['kind'] == 'pi']
    pl = [ln for ln in ax['lines'] if abs(ln['lw'] - 2.16) < 1e-9]
    check(f'{label}: the prediction interval, the report\'s', len(pl) == len(pis) and all(maxdiff(ln['x'], [tx(it['lo']), tx(it['hi'])]) < 1e-9 for ln, it in zip(pl, pis)), True)
    null = 1.0 if m_['log'] else 0.0
    vals = [it for it in items if it['kind'] in ('study', 'diamond', 'pi')]
    y1 = max(it['y'] for it in vals) + 0.5
    check(f'{label}: the no-effect line', [ln['y'] for ln in ax['lines'] if ln['color'] == MUTED_C and ln['x'] == [null, null]], [[-0.5, y1]])
    mains = [it for it in dia if not it['sub']]
    pooled = next((it for it in mains if it['which'] == 're'), mains[0] if mains else None)
    dots = [ln['x'] for ln in ax['lines'] if ln['ls'] == ':']
    check(f'{label}: the pooled estimate\'s line', len(dots) == (1 if pooled and o.get('pooledLine', True) else 0) and (not dots or maxdiff(dots[0], [tx(pooled['est'])] * 2) < 1e-9), True)
    if log:
        check.near(f'{label}: the page\'s axis range (log)', maxdiff([math.log10(v) for v in ax['xlim']], rng['range']), 0.0, abs_=1e-5)
        check(f'{label}: a log axis with the page\'s ticks', (ax['xscale'], ax['xticks'] == [float(v) for v in rng.get('tickvals') or ax['xticks']], ax['xticklabels'] if rng.get('ticktext') else None),
              ('log', True, rng.get('ticktext')))
    else:
        check.near(f'{label}: the page\'s axis range', maxdiff(ax['xlim'], rng['range']), 0.0, abs_=1e-5)
        check(f'{label}: a linear axis', ax['xscale'], 'linear')
    check(f'{label}: the axis title', ax['xlabel'], m_['display'] + (' (log scale)' if log else ''))
    check(f'{label}: the page\'s size', F['size'], [W / 100, (lay['H'] + 26) / 100])
    check(f'{label}: the title', F['suptitle'], f'Forest plot of {m_["plural"]}')
    return res, code


# the trials: odds ratios on a log axis, every option at its default; an interval runs past the axis
frame_bin = pd.DataFrame(cols)
LOG_RNG = {'range': [-1.0, 0.62], 'tickvals': [0.1, 0.2, 0.5, 1, 2], 'ticktext': ['0.1', '0.2', '0.5', '1', '2']}
res_f, code_f = forest_check('forest plot (defaults)', tid, BIN, frame_bin, 'data', {}, LOG_RNG)
check('the forest code keeps the report\'s studies (the double zero left out)', 'd = df.loc[[0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13]]' in code_f, True)
check('and pools them with statsmodels\' combine_effects', 'combine_effects(eff, var, method_re="chi2")' in code_f, True)
# subgroups by quality, the Mantel-Haenszel fixed effect, sorted by effect
forest_check('forest plot (subgroups, Mantel–Haenszel, by effect)', tid, {**BIN, 'group': 'quality'}, frame_bin, 'data', {'mh': True, 'sort': 'effect'}, LOG_RNG)
# REML with Hartung-Knapp, the fixed effect alone (one weight column), ratios on a linear axis, sorted by weight
forest_check('forest plot (REML, HK, fixed effect only, linear ratios, by weight)', tid, BIN, frame_bin, 'data',
             {'showRE': False, 'log': False, 'sort': 'weight'}, {'range': [-0.2, 3.1]}, method='reml', hksj=True)
forest_check('forest plot (REML, HK, both, by precision)', tid, BIN, frame_bin, 'data', {'sort': 'precision'}, LOG_RNG, method='reml', hksj=True)
# Paule-Mandel, the random effects alone, by label in an order the page gives (reversed), no PI, no line, no weights, no statistics
lab_order = [s_['row'] for s_ in sorted(res_f['studies'], key=lambda s_: s_['label'], reverse=True)]
forest_check('forest plot (Paule–Mandel, random only, by label, the rest off)', tid, BIN, frame_bin, 'data',
             {'showFE': False, 'sort': 'label', 'labelOrder': lab_order, 'showPI': False, 'pooledLine': False, 'weights': False, 'stats': False}, LOG_RNG, method='pm')
forest_check('forest plot (subgroups, fixed effect only, no statistics)', tid, {**BIN, 'group': 'quality'}, frame_bin, 'data', {'showRE': False, 'stats': False}, LOG_RNG)
# Hedges' g: a linear axis, the texts' decimals from the intervals; rows left out in the report
frame_cont = pd.DataFrame({'n1': n1, 'm1': m1, 's1': s1, 'n2': n2, 'm2': m2, 's2': s2, 'g': quality})
_, code_c = forest_check("forest plot (Hedges' g, rows left out, by subgroup)", tc, {**CONT, 'group': 'g'}, frame_cont, 'cont', {}, {'range': [-0.9, 1.6]}, rows=[i for i in range(k) if i not in (2, 7)])
check("the Hedges' g forest code leaves out the report's rows", 'd = df.loc[[0, 1, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13]]' in code_c, True)
# published log ratios with numeric labels, one of them missing (the page's Row n); k = 2 and k = 1
frame_es = pd.DataFrame({'y': eff[:6], 'se': se_col[:6], 'id': [101.0, 102.0, None, 104.0, 105.5, 106.0]})
tes = table({'y': eff[:6], 'se': se_col[:6], 'id': [101.0, 102.0, None, 104.0, 105.5, 106.0]})
ESL = {'layout': 'es', 'effect': 'y', 'se': 'se', 'label': 'id', 'log': True}
res_es, _ = forest_check('forest plot (log ratios, numeric labels)', tes, ESL, frame_es, 'es', {}, {'range': [-0.9, 0.5]})
check('numeric labels as the page writes them, a missing one as its row', [s_['label'] for s_ in res_es['studies']], ['101', '102', 'Row 3', '104', '105.5', '106'])
forest_check('forest plot (two studies)', tes, ESL, frame_es, 'es', {}, {'range': [-0.9, 0.5]}, rows=[0, 1])
forest_check('forest plot (one study)', tes, ESL, frame_es, 'es', {}, {'range': [-0.9, 0.5]}, rows=[3])


def mini_check(label, kind, tid_, inputs, frame_, name, method='dl', hksj=False, order_by=None, descending=False, rng=None):
    kw = dict(table=tid_, inputs=inputs, method=method, alpha=0.05, hksj=hksj, table_name=name)
    if kind == 'loo':
        res = call('meta.leave_one_out', **kw)
        names = [f'without {x["label"]}' for x in res['rows']]
        full = res['full']['est']
    else:
        kw.update(order_by=order_by, descending=descending)
        res = call('meta.cumulative', **kw)
        names = [f'+ {x["label"]}' + (f' ({x["value"] if x["value"] is not None else "."})' if order_by else '') for x in res['rows']]
        full = res['rows'][-1]['est']
    m_ = res['measure']
    tx = math.exp if m_['log'] else (lambda v: v)
    n_ = len(res['rows'])
    plot = {'log': bool(m_['log']), 'width': 460, 'height': 22 * n_ + 64, **(rng or {'range': [-1.3, 0.4]})}
    rr = call('meta.plot_code', kind=kind, plot=plot, **kw)
    code = rr.get('plot_code') or ''
    check(f'{label}: the code is written', rr.get('error'), None)
    out, err = run_snippet_more(code, frame_, name, chart_dir)
    check(f'{label}: the code runs', err, None)
    if err:
        print(err)
        return
    ax = out['figures'][0]['axes'][0]
    check(f'{label}: a line per estimate, named as the page names it', ax['yticklabels'], names)
    check(f'{label}: the estimates, the report\'s', maxdiff([v for xy in ax['scatter'][0]['xy'] for v in xy], [v for i, x in enumerate(res['rows']) for v in (tx(x['est']), i)]) < 1e-9, True)
    ivs = [ln['x'] for ln in ax['lines'] if ln['color'] == TEXT_C]
    check(f'{label}: their intervals, the report\'s', maxdiff([v for x_ in ivs for v in x_], [v for x in res['rows'] for v in (tx(x['lower']), tx(x['upper']))]) < 1e-9, True)
    check(f'{label}: the line of the estimate from every study', maxdiff([ln['x'] for ln in ax['lines'] if ln['ls'] == ':'][0], [tx(full)] * 2) < 1e-9, True)
    check(f'{label}: the first line at the top', (ax['ylim'], ax['yinverted']), ([n_ - 0.4, -0.6], True))
    check.near(f'{label}: the page\'s axis range', maxdiff([math.log10(v) for v in ax['xlim']] if m_['log'] else ax['xlim'], plot['range']), 0.0, abs_=1e-5)
    check(f'{label}: the title and axis title', (ax['title'], ax['xlabel']), ('Leave-one-out estimates' if kind == 'loo' else 'Cumulative estimates', m_['display'] + (' (log scale)' if m_['log'] else '')))


mini_check('leave-one-out plot (DerSimonian–Laird)', 'loo', tid, BIN, frame_bin, 'data', rng={'range': [-0.7, 0.05], 'tickvals': [0.3, 0.5, 1], 'ticktext': ['0.3', '0.5', '1']})
mini_check('leave-one-out plot (REML, Hartung–Knapp)', 'loo', tid, BIN, frame_bin, 'data', method='reml', hksj=True)
mini_check('cumulative plot (by year, Paule–Mandel, HK)', 'cumulative', tid, BIN, frame_bin, 'data', method='pm', hksj=True, order_by='year', rng={'range': [-2.5, 0.8]})
mini_check('cumulative plot (by quality, descending)', 'cumulative', tid, BIN, frame_bin, 'data', order_by='quality', descending=True)
mini_check("cumulative plot (Hedges' g, row order)", 'cumulative', tc, CONT, frame_cont, 'cont', rng={'range': [-0.8, 1.2]})


def funnel_check(label, tid_, inputs, frame_, name, o, method='dl', rng=None):
    kw = dict(table=tid_, inputs=inputs, method=method, alpha=0.05, table_name=name)
    b = call('meta.bias', **kw)
    m_ = b['measure']
    tx = math.exp if m_['log'] else (lambda v: v)
    plot = {'log': bool(m_['log']), 'limits': o.get('limits', True), 're': o.get('re', False), 'egger': bool(o.get('egger')) and 'egger' in b, 'width': 480, 'height': 340,
            **(rng or {'range': [-2.2, 1.3]})}
    rr = call('meta.plot_code', kind='funnel', plot=plot, **kw)
    code = rr.get('plot_code') or ''
    check(f'{label}: the code is written', rr.get('error'), None)
    out, err = run_snippet_more(code, frame_, name, chart_dir)
    check(f'{label}: the code runs', err, None)
    if err:
        print(err)
        return
    ax = out['figures'][0]['axes'][0]
    smax = 1.08 * max(b['se'])
    z = stats.norm.isf(0.025)
    check(f'{label}: the studies at their effects and standard errors', maxdiff([v for xy in ax['scatter'][0]['xy'] for v in xy], [v for e_, s_ in zip(b['eff'], b['se']) for v in (tx(e_), s_)]) < 1e-9, True)
    lims = [ln for ln in ax['lines'] if ln['ls'] == '--']
    check(f'{label}: the pseudo 95% limits around the fixed effect', len(lims) == (1 if plot['limits'] else 0) and (not lims or maxdiff(lims[0]['x'] + lims[0]['y'], [tx(b['fe'] - z * smax), tx(b['fe']), tx(b['fe'] + z * smax), smax, 0, smax]) < 1e-9), True)
    fel = [ln for ln in ax['lines'] if ln['color'] == TEXT_C]
    check(f'{label}: the fixed effect\'s line', len(fel) == 1 and maxdiff(fel[0]['x'] + fel[0]['y'], [tx(b['fe'])] * 2 + [0, smax]) < 1e-9, True)
    rel_ = [ln for ln in ax['lines'] if ln['ls'] == ':']
    check(f'{label}: the random effects\' line when asked', len(rel_) == (1 if plot['re'] else 0) and (not rel_ or maxdiff(rel_[0]['x'], [tx(b['re'])] * 2) < 1e-9), True)
    eg = [ln for ln in ax['lines'] if ln['color'] == RE_C and ln['ls'] == '-']
    check(f'{label}: Egger\'s line when asked', len(eg) == (1 if plot['egger'] else 0) and (not eg or maxdiff(eg[0]['x'], [tx(b['egger']['slope']), tx(b['egger']['slope'] + b['egger']['intercept'] * smax)]) < 1e-9), True)
    check(f'{label}: the most precise at the top', maxdiff(ax['ylim'], [smax, 0]) < 1e-12 and ax['yinverted'], True)
    check.near(f'{label}: the page\'s axis range', maxdiff([math.log10(v) for v in ax['xlim']] if m_['log'] else ax['xlim'], plot['range']), 0.0, abs_=1e-5)
    check(f'{label}: the titles', (ax['title'], ax['xlabel'], ax['ylabel']), (f'Funnel plot of {m_["plural"]}', m_['display'] + (' (log scale)' if m_['log'] else ''), 'Standard Error'))


funnel_check('funnel plot (defaults)', tid, BIN, frame_bin, 'data', {})
funnel_check('funnel plot (every line, REML)', tid, BIN, frame_bin, 'data', {'re': True, 'egger': True}, method='reml')
funnel_check("funnel plot (Hedges' g, no limits, Egger)", tc, CONT, frame_cont, 'cont', {'limits': False, 'egger': True}, rng={'range': [-0.9, 1.4]})


def bubble_check(label, tid_, inputs, frame_, name, covs, method='dl', hksj=False):
    kw = dict(table=tid_, inputs=inputs, method=method, alpha=0.05, hksj=hksj, table_name=name)
    mr = call('meta.regression', covariates=covs, **kw)
    m_ = mr['measure']
    tx = math.exp if m_['log'] else (lambda v: v)
    check(f'{label}: a bubble plot per continuous covariate', [c_['covariate'] for c_ in mr['curves']], [c_ for c_ in covs if c_ != 'quality'])
    for cv in mr['curves']:
        lab = f'{label}, {cv["covariate"]}'
        plot = {'covariate': cv['covariate'], 'log': bool(m_['log']), 'width': 480, 'height': 330, 'range': [-1.6, 0.7]}
        rr = call('meta.plot_code', kind='bubble', covariates=covs, plot=plot, **kw)
        code = rr.get('plot_code') or ''
        check(f'{lab}: the code is written', rr.get('error'), None)
        out, err = run_snippet_more(code, frame_, name, chart_dir)
        check(f'{lab}: the code runs', err, None)
        if err:
            print(err)
            continue
        ax = out['figures'][0]['axes'][0]
        sc = ax['scatter'][0]
        check(f'{lab}: the studies at the covariate and their effects', maxdiff([v for xy in sc['xy'] for v in xy], [v for x_, e_ in zip(cv['x'], mr['eff']) for v in (x_, tx(e_))]) < 1e-9, True)
        check(f'{lab}: the bubbles\' areas from the weights', maxdiff(sc['sizes'], [(max(6, 34 * math.sqrt(w_ / max(mr['w']))) * 0.72) ** 2 for w_ in mr['w']]) < 1e-8, True)
        fit_l = [ln for ln in ax['lines'] if abs(ln['lw'] - 1.44) < 1e-9]
        check(f'{lab}: the fit, the report\'s curve', len(fit_l) == 1 and maxdiff(fit_l[0]['x'], cv['grid']) < 1e-12 and maxdiff(fit_l[0]['y'], [tx(v) for v in cv['fit']]) < 1e-8, True)
        verts = [q_ for p_ in ax['polys'][0]['paths'] for q_ in p_] if ax['polys'] else []
        at = {}
        for x_, y_ in verts:
            at.setdefault(round(x_, 9), []).append(y_)
        band_ok = len(verts) > 0 and all(any(abs(y_ - tx(lo_)) < 1e-8 * max(1, tx(lo_)) for y_ in at.get(round(g_, 9), [])) and any(abs(y_ - tx(hi_)) < 1e-8 * max(1, tx(hi_)) for y_ in at.get(round(g_, 9), []))
                                          for g_, lo_, hi_ in zip(cv['grid'], cv['lower'], cv['upper']))
        check(f'{lab}: the confidence band, the report\'s', band_ok, True)
        null = 1.0 if m_['log'] else 0.0
        check(f'{lab}: the no-effect line across the covariate', [ln['x'] for ln in ax['lines'] if ln['color'] == MUTED_C and ln['y'] == [null, null]], [[cv['grid'][0], cv['grid'][-1]]])
        check.near(f'{lab}: the page\'s axis range', maxdiff([math.log10(v) for v in ax['ylim']] if m_['log'] else ax['ylim'], plot['range']), 0.0, abs_=1e-5)
        check(f'{lab}: the titles', (ax['title'], ax['xlabel'], ax['ylabel']), (f'Bubble plot of {m_["display"]} by {cv["covariate"]}', cv['covariate'], m_['display'] + (' (log scale)' if m_['log'] else '')))


bubble_check('bubble plot (dose)', tid, BIN, frame_bin, 'data', ['dose (mg)'])
bubble_check('bubble plot (dose and year with quality, REML, HK)', tid, BIN, frame_bin, 'data', ['dose (mg)', 'quality', 'year'], method='reml', hksj=True)
bubble_check('bubble plot (dose and year, Paule–Mandel)', tid, BIN, frame_bin, 'data', ['year', 'dose (mg)'], method='pm')
check('no bubble plot for a nominal covariate: an error, said in words', call('meta.plot_code', table=tid, inputs=BIN, kind='bubble', covariates=['quality'], plot={'covariate': 'quality'}).get('error'),
      'no bubble plot for that covariate')
check('an unknown graph: an error', 'unknown graph' in call('meta.plot_code', table=tid, inputs=BIN, kind='pie', plot={}).get('error', ''), True)

sys.exit(check.done())
