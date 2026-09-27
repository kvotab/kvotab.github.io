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
for meth in ('dl', 'pm', 'reml'):
    mm_ = call('meta.regression', table=tid, inputs=BIN, covariates=['dose (mg)', 'quality'], method=meth, table_name='data')
    p = run(mm_['code'] + '\nprint(*fit.params)')
    check(f'the meta-regression code runs ({meth})', p.returncode, 0)
    if not p.returncode:
        lines = p.stdout.strip().splitlines()
        check.near(f'and gives the report\'s τ² ({meth})', float(lines[0]), mm_['tau2'], rel=1e-8, abs_=1e-12)
        check.near(f'and coefficients ({meth})', max(abs(a_ - t_['est']) for a_, t_ in zip(last(p), mm_['terms'])), 0.0, abs_=1e-8)
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

sys.exit(check.done())
