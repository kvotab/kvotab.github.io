#!/usr/bin/env python3
"""Reliability and Survival's backend (resources/py/smui/survival.py):
Survival, Life Distribution, Fit Parametric Survival and Fit Proportional
Hazards, checked against statsmodels and scipy called directly, against
independent computations written out here (the product-limit estimate and
Greenwood's formula by their definitions, the log-rank statistic from
observed and expected failures, the Cox partial likelihood), against closed
forms (the exponential maximum likelihood estimate with censoring; normal
and lognormal fits without censoring; the Kaplan-Meier mean of uncensored
data, which is the sample mean), and on statsmodels' own heart transplant
data (statsmodels.datasets.heart) at run time.

    python3 resources/tests/smui/test_survival.py
"""
import math
import sys

import numpy as np
import pandas as pd
from scipy import optimize, stats
from statsmodels.duration.hazard_regression import PHReg
from statsmodels.duration.survfunc import SurvfuncRight, survdiff

from backend import FAILED, Checks, call, table

check = Checks()
check('survival.py imports', FAILED.get('survival'), None)


# ---- Kaplan-Meier on a small example, checked by its definition ---------------
# ten times, three censored (+): 2, 3, 3, 4+, 5, 7+, 8, 9, 9+, 12
T = [2, 3, 3, 4, 5, 7, 8, 9, 9, 12]
CENS = [0, 0, 0, 1, 0, 1, 0, 0, 1, 0]       # 1 = censored
tid = table({'t': T, 'c': CENS}, types={'c': 'nominal'})
r = call('survival.km', table=tid, time='t', censor='c', censor_code='1', times=[5, 10], probs=[0.5])
g = r['groups'][0]
check('counts', (g['n'], g['failed'], g['censored']), (10, 7, 3))


def km_by_hand(t, e):
    """S(t) and Greenwood's variance, straight from the definitions."""
    t, e = np.asarray(t, float), np.asarray(e, float)
    out, s, v = [], 1.0, 0.0
    for u in np.unique(t[e > 0]):
        n = np.sum(t >= u)
        d = np.sum((t == u) & (e > 0))
        s *= 1 - d / n
        if n > d:
            v += d / (n * (n - d))
        # where everyone left fails, S = 0 and Greenwood's formula is 0/0:
        # statsmodels leaves the standard error undefined there
        out.append((u, s, s * math.sqrt(v) if n > d else None, n, d))
    return out


ev = 1 - np.array(CENS)
hand = km_by_hand(T, ev)
tab = g['table']
for u, s, se, n, d in hand:
    i = tab['time'].index(u)
    check.near(f'S({u:g}) by the product-limit definition', tab['surv'][i], s)
    if se is None:
        check(f'Greenwood standard error at {u:g} is undefined (S = 0)', tab['se'][i], None)
    else:
        check.near(f'Greenwood standard error at {u:g}', tab['se'][i], se)
    check(f'at risk and failures at {u:g}', (tab['at_risk'][i], tab['failed'][i]), (float(n), float(d)))
# censored times carry the estimate of the last failure
i4 = tab['time'].index(4)
check.near('S(4), a censored time, is S(3)', tab['surv'][i4], hand[1][1])
check('censored count at 9', tab['censored'][tab['time'].index(9)], 1.0)
# pointwise log(-log) limits
z = stats.norm.ppf(0.975)
u, s, se, n, d = hand[2]   # t = 5
v = se / abs(s * math.log(s))
i5 = tab['time'].index(5)
check.near('lower limit, log(-log) Greenwood', tab['lower'][i5], s ** math.exp(z * v))
check.near('upper limit, log(-log) Greenwood', tab['upper'][i5], s ** math.exp(-z * v))
# restricted mean: area under the steps to the largest time, and its variance sum
steps = [(0.0, 1.0)] + [(h[0], h[1]) for h in hand]
area = sum(steps[k][1] * ((steps[k + 1][0] if k + 1 < len(steps) else 12.0) - steps[k][0]) for k in range(len(steps)))
check.near('restricted mean', g['mean'], area)
var = 0.0
for k, (uu, ss, _, nn, dd) in enumerate(hand):
    a = sum(hand[j][1] * ((hand[j + 1][0] if j + 1 < len(hand) else 12.0) - hand[j][0]) for j in range(k, len(hand)))
    if nn > dd:
        var += a * a * dd / (nn * (nn - dd))
check.near('standard error of the mean', g['mean_se'], math.sqrt(var))
check('mean not biased: the largest time is a failure', g['mean_biased'], False)
# quantiles and their interval: statsmodels called directly
sf = SurvfuncRight(np.array(T, float), ev)
check.near('median', g['median'], float(sf.quantile(0.5)))
with np.errstate(all='ignore'):
    lo, hi = sf.quantile_ci(0.5, alpha=0.05, method='cloglog')
check.near('median interval, lower (quantile_ci)', g['median_lower'], float(lo))
check('median interval, upper (quantile_ci)', g['median_upper'], float(hi) if np.isfinite(hi) else 'Infinity')
check.near('25% failures', g['q25'], float(sf.quantile(0.25)))
check.near('estimate at t = 10', g['est_times'][1]['surv'], [h[1] for h in hand if h[0] <= 10][-1])
check.near('time quantile at p = 0.5', g['est_probs'][0]['time'], float(sf.quantile(0.5)))
check('one point per row, the page\'s rows', sorted(g['points']['rows']), list(range(10)))
check('code shown', 'SurvfuncRight' in r['code'], True)

# ---- uncensored data: the mean is the sample mean, its variance sum/(n^2) --------
rng = np.random.default_rng(20260926)
x = np.round(rng.exponential(10, 37), 1) + 0.1
tu = table({'t': x})
gu = call('survival.km', table=tu, time='t')['groups'][0]
check.near('uncensored: mean = sample mean', gu['mean'], float(x.mean()))
check.near('uncensored: SE = sqrt(sum (x - mean)^2) / n', gu['mean_se'], float(np.sqrt(((x - x.mean()) ** 2).sum()) / len(x)))

# ---- groups, tests between groups, censor codes, Freq ------------------------------
n = 160
grp = rng.choice(['placebo', 'drug', 'high'], n).tolist()
scale = np.where(np.array(grp) == 'placebo', 10.0, np.where(np.array(grp) == 'drug', 15.0, 19.0))
tt = rng.weibull(1.4, n) * scale
cc = rng.uniform(4, 30, n)
obs = np.round(np.minimum(tt, cc), 2)
cen = (tt > cc).astype(int)
yesno = ['yes' if c else 'no' for c in cen]
tg = table({'t': obs, 'c': cen.astype(float), 'cy': yesno, 'g': grp}, types={'c': 'nominal'}, levels={'g': ['placebo', 'drug', 'high']})
rg = call('survival.km', table=tg, time='t', censor='c', censor_code='1', group='g')
check('groups in the page\'s level order', [x['level'] for x in rg['groups']], ['placebo', 'drug', 'high'])
evg = 1 - cen
codes = np.array([['placebo', 'drug', 'high'].index(v) for v in grp])
for label, wt, kw in (('Log-Rank', None, {}), ('Wilcoxon', 'gb', {}), ('Tarone-Ware', 'tw', {}), ('Fleming-Harrington (ρ = 1)', 'fh', {'fh_p': 1.0})):
    chi, p = survdiff(obs, evg, codes, weight_type=wt, **kw)
    row = [x for x in rg['tests']['rows'] if x['test'] == label][0]
    check.near(f'{label} chi-square = survdiff', row['chisq'], float(chi))
    check.near(f'{label} p-value', row['p'], float(p))
    check(f'{label} DF', row['df'], 2)
# the log-rank statistic from observed minus expected, written out (two groups)
m2 = codes < 2
t2, e2, g2 = obs[m2], evg[m2], codes[m2]
O = E = V = 0.0
for u in np.unique(t2[e2 > 0]):
    at = t2 >= u
    nn, n1 = at.sum(), (at & (g2 == 1)).sum()
    dd = ((t2 == u) & (e2 > 0)).sum()
    d1 = ((t2 == u) & (e2 > 0) & (g2 == 1)).sum()
    O += d1
    E += dd * n1 / nn
    if nn > 1:
        V += dd * (n1 / nn) * (1 - n1 / nn) * (nn - dd) / (nn - 1)
t2b = table({'t': t2, 'c': 1 - e2, 'g': [['placebo', 'drug'][k] for k in g2]}, types={'c': 'nominal'}, levels={'g': ['placebo', 'drug']})
lr2 = call('survival.km', table=t2b, time='t', censor='c', censor_code=1, group='g')['tests']['rows'][0]
check.near('log-rank = (O - E)^2 / V by hand', lr2['chisq'], (O - E) ** 2 / V)
# a character censor column and its code give the same curves
ry = call('survival.km', table=tg, time='t', censor='cy', censor_code='yes', group='g')
check('character censor code', [x['failed'] for x in ry['groups']], [x['failed'] for x in rg['groups']])
check.near('same log-rank with the character code', ry['tests']['rows'][0]['chisq'], rg['tests']['rows'][0]['chisq'])
try:
    call('survival.km', table=tg, time='t', censor='c', censor_code='x')
    refused = False
except ValueError as ex:
    refused = 'not a number' in str(ex)
check('a code that is not a number, for a numeric censor column, is refused', refused, True)
# Freq: a row with count k is k rows
small_t = [3.0, 5.0, 5.0, 8.0, 11.0, 13.0]
small_c = [0, 0, 1, 0, 1, 0]
small_f = [2, 1, 3, 1, 2, 1]
tf = table({'t': small_t, 'c': small_c, 'f': small_f}, types={'c': 'nominal'})
te = table({'t': np.repeat(small_t, small_f), 'c': np.repeat(small_c, small_f)}, types={'c': 'nominal'})
a = call('survival.km', table=tf, time='t', censor='c', censor_code=1, freq='f')['groups'][0]
b = call('survival.km', table=te, time='t', censor='c', censor_code=1)['groups'][0]
check('Freq: the same estimates as repeated rows', a['table']['surv'], b['table']['surv'])
check.near('Freq: the same mean', a['mean'], b['mean'])
check('Freq: one point per row still', len(a['points']['rows']), 6)
# rows: the page's subset, and all rows as None
sub = call('survival.km', table=tg, time='t', censor='c', censor_code=1, rows=list(range(0, n, 2)))
check('rows subset', sum(x['n'] for x in sub['groups']), n // 2)
check('rows=None is every row', sum(x['n'] for x in call('survival.km', table=tg, time='t', rows=None)['groups']), n)

# ---- parametric fits with censoring --------------------------------------------------
data = stats.CensoredData(uncensored=obs[evg > 0], right=obs[evg == 0])
fg = call('survival.fit_groups', table=tg, time='t', censor='c', censor_code=1, dists=['exponential', 'weibull', 'lognormal'])
ex = fg['fits'][0]['params'][0]
theta = obs.sum() / evg.sum()
check.near('exponential θ = total time / failures', ex['estimate'], theta, rel=1e-7)
check.near('exponential SE = θ / sqrt(failures)', ex['se'], theta / math.sqrt(evg.sum()), rel=1e-5)
wb = {p['parameter']: p['estimate'] for p in fg['fits'][1]['params']}
c_sc, _, sc_sc = stats.weibull_min.fit(data, floc=0)
check.near('Weibull α = scipy weibull_min (CensoredData)', wb['α (scale)'], float(sc_sc), rel=2e-4)
check.near('Weibull β = scipy', wb['β (shape)'], float(c_sc), rel=2e-4)
ll_ours = -fg['fits'][1]['fit'][0]['m2ll'] / 2
ll_sc = float(np.sum(stats.weibull_min.logpdf(obs[evg > 0], c_sc, scale=sc_sc)) + np.sum(stats.weibull_min.logsf(obs[evg == 0], c_sc, scale=sc_sc)))
check('Weibull log-likelihood at least scipy\'s', ll_ours >= ll_sc - 1e-7, True)
check.near('Weibull log-likelihood = scipy\'s', ll_ours, ll_sc, rel=1e-7)
ln = fg['fits'][2]['params']
s_ln, _, e_ln = stats.lognorm.fit(data, floc=0)
check.near('lognormal μ = log scipy scale', ln[0]['estimate'], math.log(e_ln), rel=2e-4)
check.near('lognormal σ = scipy', ln[1]['estimate'], float(s_ln), rel=2e-4)
# uncensored lognormal: closed form
lx = np.log(x)
fu = call('survival.fit_groups', table=tu, time='t', dists=['lognormal'])['fits'][0]['params']
check.near('uncensored lognormal μ = mean log t', fu[0]['estimate'], float(lx.mean()), rel=1e-7)
check.near('uncensored lognormal σ = sd log t (n)', fu[1]['estimate'], float(lx.std()), rel=1e-6)
check.near('SE of μ = σ / sqrt(n)', fu[0]['se'], float(lx.std() / math.sqrt(len(x))), rel=1e-4)
check.near('SE of σ = σ / sqrt(2n)', fu[1]['se'], float(lx.std() / math.sqrt(2 * len(x))), rel=1e-4)
bad = call('survival.fit_groups', table=table({'t': [-1.0, 2.0, 3.0]}), time='t', dists=['weibull'])
check('Weibull on a negative time says so', bad['fits'][0]['fit'][0].get('error'), 'needs every time above zero')
none = call('survival.fit_groups', table=table({'t': [1.0, 2.0], 'c': [1.0, 1.0]}), time='t', censor='c', censor_code=1, dists=['weibull'])
check('no failures: no fit', none['fits'][0]['fit'][0].get('error'), 'no failures: every time is censored')

# ---- Life Distribution ----------------------------------------------------------------
ld = call('lifedist.fit', table=tg, time='t', censor='c', censor_code=1, dists=['weibull', 'lognormal', 'loglogistic', 'frechet', 'exponential', 'normal', 'logistic', 'sev', 'lev'],
          times=[10.0], probs=[0.1, 0.5])
check('all nine fitted', len([f for f in ld['fits'] if 'error' not in f]), 9)
check('comparisons sorted by AICc', [c['aicc'] for c in ld['comparison']['rows']] == sorted(c['aicc'] for c in ld['comparison']['rows']), True)
check.near('AICc weights sum to one', sum(c['weight'] for c in ld['comparison']['rows']), 1.0)
by = {f['dist']: f for f in ld['fits']}
nobs = float(n)
for c in ld['comparison']['rows']:
    k = c['k']
    check.near(f'{c["label"]} AICc = -2LL + 2k + 2k(k+1)/(n-k-1)', c['aicc'], c['m2ll'] + 2 * k + 2 * k * (k + 1) / (nobs - k - 1))
# every family against scipy's censored maximum likelihood
scipy_of = {'weibull': (stats.weibull_min, {'floc': 0}), 'lognormal': (stats.lognorm, {'floc': 0}), 'loglogistic': (stats.fisk, {'floc': 0}),
            'frechet': (stats.invweibull, {'floc': 0}), 'normal': (stats.norm, {}), 'logistic': (stats.logistic, {}), 'sev': (stats.gumbel_l, {}), 'lev': (stats.gumbel_r, {})}
for key, (dist, kw) in scipy_of.items():
    par = dist.fit(data, **kw)
    ll_sc = float(np.sum(dist.logpdf(obs[evg > 0], *par)) + np.sum(dist.logsf(obs[evg == 0], *par)))
    ll_ours = -by[key]['m2ll'] / 2
    check(f'{key}: log-likelihood at least scipy\'s', ll_ours >= ll_sc - 1e-6, True)
    check.near(f'{key}: log-likelihood = scipy\'s', ll_ours, ll_sc, rel=1e-6)
w = by['weibull']
alpha_w, beta_w = math.exp(w['mu']), 1 / w['sigma']
check.near('calculator: F(10) = Weibull CDF', w['at_times'][0]['F'], float(stats.weibull_min.cdf(10.0, beta_w, scale=alpha_w)))
check.near('calculator: B10 life = α(-log 0.9)^(1/β)', w['at_probs'][0]['time'], alpha_w * (-math.log(0.9)) ** (1 / beta_w))
check('calculator limits bracket the estimate', w['at_probs'][1]['lower'] < w['at_probs'][1]['time'] < w['at_probs'][1]['upper'], True)
check('probability plot: a point per failed row', len(ld['points']['rows']), int(evg.sum()))
check('points at the middle of the jump, inside (0, 1)', all(0 < p < 1 for p in ld['points']['prob']), True)

# ---- Fit Parametric Survival -------------------------------------------------------------
# lognormal without censoring is least squares on log t
age = rng.normal(55, 9, n)
yt = np.exp(1.5 + 0.02 * (age - 55) + np.where(np.array(grp) == 'drug', 0.4, 0.0) + rng.normal(0, 0.5, n))
tp = table({'t': yt, 'age': age, 'g': grp, 'c': cen.astype(float)}, types={'c': 'nominal'}, levels={'g': ['placebo', 'drug', 'high']})
pr = call('parametric.fit', table=tp, time='t', effects=['age', 'g'], dist='lognormal')
import statsmodels.formula.api as smf  # noqa: E402
dfp = pd.DataFrame({'ly': np.log(yt), 'age': age, 'g': pd.Categorical(grp, categories=['placebo', 'drug', 'high'])})
ols = smf.ols('ly ~ age + C(g, Sum)', dfp).fit()
est = {r_['term']: r_['estimate'] for r_ in pr['estimates']['rows']}
check.near('lognormal AFT, no censoring: intercept = OLS', est['Intercept'], float(ols.params['Intercept']), rel=1e-6)
check.near('slope of age = OLS', est['age'], float(ols.params['age']), rel=1e-5)
check.near('g[placebo] = OLS effect coding', est['g[placebo]'], float(ols.params['C(g, Sum)[S.placebo]']), rel=1e-5)
check.near('σ = sqrt(SSR / n)', est['σ (scale)'], math.sqrt(ols.ssr / n), rel=1e-6)
wh = pr['whole']['rows']
check.near('whole model: chi-square = 2 x difference', wh[0]['chisq'], 2 * (wh[2]['nll'] - wh[1]['nll']))
check('whole model DF', wh[0]['df'], 3)
# exponential with a two-level effect: the MLE is total time over failures in each group
two = ['a' if k % 2 else 'b' for k in range(n)]
te2 = rng.exponential(np.where(np.array(two) == 'a', 8.0, 14.0))
ce2 = rng.uniform(3, 30, n)
o2, c2 = np.minimum(te2, ce2), (te2 > ce2).astype(float)
tx = table({'t': o2, 'c': c2, 'two': two}, types={'c': 'nominal'}, levels={'two': ['a', 'b']})
px = call('parametric.fit', table=tx, time='t', effects=['two'], censor='c', censor_code=1, dist='exponential')
ea = {r_['term']: r_['estimate'] for r_ in px['estimates']['rows']}
th = {k: o2[np.array(two) == k].sum() / (1 - c2[np.array(two) == k]).sum() for k in ('a', 'b')}
check.near('exponential AFT: intercept = mean of the log θs', ea['Intercept'], (math.log(th['a']) + math.log(th['b'])) / 2, rel=1e-6)
check.near('exponential AFT: two[a] = half their difference', ea['two[a]'], (math.log(th['a']) - math.log(th['b'])) / 2, rel=1e-5)
check.near('one effect: its LR test is the whole-model test', px['lr']['rows'][0]['chisq'], px['whole']['rows'][0]['chisq'], rel=1e-6)
# Weibull AFT against its likelihood maximised independently
pw = call('parametric.fit', table=tp, time='t', effects=['age'], censor='c', censor_code=1, dist='weibull')
Xw = np.column_stack([np.ones(n), age])
evw = 1 - cen
lyt = np.log(yt)


def nll(p):
    s = math.exp(p[-1])
    zz = (lyt - Xw @ p[:-1]) / s
    return -np.sum(np.where(evw > 0, zz - np.exp(zz) - math.log(s) - lyt, -np.exp(zz)))


opt = optimize.minimize(nll, np.r_[lyt.mean(), 0.0, 0.0], method='BFGS', options={'gtol': 1e-9})
opt = optimize.minimize(nll, opt.x, method='Nelder-Mead', options={'xatol': 1e-10, 'fatol': 1e-12, 'maxiter': 20000})
ew = {r_['term']: r_['estimate'] for r_ in pw['estimates']['rows']}
check.near('Weibull AFT intercept = scipy.optimize', ew['Intercept'], float(opt.x[0]), rel=1e-5)
check.near('Weibull AFT slope = scipy.optimize', ew['age'], float(opt.x[1]), rel=1e-4, abs_=1e-6)
check.near('Weibull AFT σ', ew['σ (scale)'], math.exp(opt.x[2]), rel=1e-5)
check.near('Weibull AFT -2LL', pw['summary']['m2ll'], 2 * opt.fun, rel=1e-9)
sq = call('parametric.save', table=tp, time='t', effects=['age'], censor='c', censor_code=1, dist='weibull', what='quantile', value=0.5)
med0 = math.exp(ew['Intercept'] + ew['age'] * age[0] + ew['σ (scale)'] * math.log(-math.log(0.5)))
check.near('saved median of row 1', sq['values'][0], med0, rel=1e-8)
check('saved rows are the page\'s rows', sq['rows'][:3], [0, 1, 2])

# ---- Fit Proportional Hazards ------------------------------------------------------------------
ph = call('phreg.fit', table=tp, time='t', effects=['g', 'age'], censor='c', censor_code=1)
dph = pd.DataFrame({'t': yt, 'e': evw, 'age': age, 'g': pd.Categorical(grp, categories=['placebo', 'drug', 'high'])})
m = PHReg.from_formula('t ~ C(g, Sum) + age', dph, status=dph['e'].to_numpy())
res = m.fit(disp=0)
pe = {r_['term']: r_ for r_ in ph['estimates']['rows']}
check.near('PH g[placebo] = PHReg', pe['g[placebo]']['estimate'], float(res.params[0]), rel=1e-6)
check.near('PH age = PHReg', pe['age']['estimate'], float(res.params[2]), rel=1e-6)
check.near('PH SE = PHReg', pe['age']['se'], float(res.bse[2]), rel=1e-6)
check.near('-LogLikelihood of the full model', ph['whole']['rows'][1]['nll'], -float(res.llf), rel=1e-9)
check.near('LR chi-square = 2(llf - llf at 0)', ph['whole']['rows'][0]['chisq'], 2 * (res.llf - m.loglike(np.zeros(3))), rel=1e-8)
red = PHReg.from_formula('t ~ age', dph, status=dph['e'].to_numpy()).fit(disp=0)
lr_g = [x for x in ph['lr']['rows'] if x['source'] == 'g'][0]
check.near('effect LR test of g: refit without it', lr_g['chisq'], 2 * (res.llf - red.llf), rel=1e-6)
check('its DF', lr_g['df'], 2)
check.near('unit risk ratio = exp(β)', ph['unit']['rows'][0]['rr'], math.exp(float(res.params[2])), rel=1e-6)
rr = {(x['level1'], x['level2']): x['rr'] for x in ph['nominal'][0]['table']['rows']}
bp, bd = float(res.params[0]), float(res.params[1])
check.near('risk ratio placebo / drug = exp(β_placebo − β_drug)', rr[('placebo', 'drug')], math.exp(bp - bd), rel=1e-6)
check.near('risk ratio high / placebo (high = −β_placebo − β_drug)', rr[('high', 'placebo')], math.exp(-bp - bd - bp), rel=1e-6)
# the Breslow baseline: its left limits are statsmodels' baseline_cumulative_hazard
bt, bh, bs = res.baseline_cumulative_hazard[0]
xbar = res.model.exog.mean(axis=0)
H_mean = -np.log(np.array(ph['baseline']['surv'][1:-1]))
H0_right = H_mean / math.exp(float(xbar @ res.params))
check.near('baseline: H(t−) = statsmodels\' cumulative hazard', float(np.max(np.abs(np.r_[0.0, H0_right[:-1]] - bh))), 0.0, abs_=1e-10)
# the partial likelihood of one binary effect, no ties, written out
tb = np.round(rng.exponential(10, 40), 6) + np.arange(40) * 1e-6
xb = (np.arange(40) % 2).astype(float)
eb = (rng.uniform(size=40) < 0.8).astype(float)
t1 = table({'t': tb, 'c': 1 - eb, 'x': xb}, types={'c': 'nominal'})
p1 = call('phreg.fit', table=t1, time='t', effects=['x'], censor='c', censor_code=1)
beta = p1['estimates']['rows'][0]['estimate']
pl = sum(beta * xb[i] - math.log(np.sum(np.exp(beta * xb[tb >= tb[i]]))) for i in range(40) if eb[i] > 0)
check.near('partial log-likelihood by its definition', -p1['whole']['rows'][1]['nll'], pl, rel=1e-9)
check('risk scores for every row', len(p1['scores']['rows']), 40)
efr = call('phreg.fit', table=tp, time='t', effects=['age'], censor='c', censor_code=1, ties='efron')
mref = PHReg(yt, age[:, None], status=evw, ties='efron').fit(disp=0)
check.near('Efron ties = PHReg(ties="efron")', efr['estimates']['rows'][0]['estimate'], float(mref.params[0]), rel=1e-6)
check('PH needs effects', 'error' in call('phreg.fit', table=tp, time='t', effects=[]), True)

# ---- the Python shown under each result runs on a CSV export of the table ---------------------------
import os  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
work = tempfile.mkdtemp()
pd.DataFrame({'t': yt, 'age': age, 'g': grp, 'c': cen.astype(float)}).to_csv(os.path.join(work, 'data.csv'), index=False)
for fn, kw in (('survival.km', dict(group='g')), ('survival.fit_groups', dict(dists=['weibull', 'lognormal', 'exponential'])),
               ('lifedist.fit', dict(dists=['weibull', 'lognormal', 'normal', 'sev', 'lev', 'logistic', 'loglogistic', 'frechet', 'exponential'])),
               ('parametric.fit', dict(effects=['g', 'age'], dist='weibull')), ('phreg.fit', dict(effects=['g', 'age']))):
    code = call(fn, table=tp, time='t', censor='c', censor_code=1, table_name='data', **kw)['code']
    run = subprocess.run([sys.executable, '-c', code], cwd=work, capture_output=True, text=True, timeout=300)
    check(f'the code of {fn} runs', run.returncode, 0) or print(run.stderr[-600:])
# and prints this page's numbers: the Weibull regression's -2 log L
code = call('parametric.fit', table=tp, time='t', effects=['g', 'age'], censor='c', censor_code=1, dist='weibull', table_name='data')
run = subprocess.run([sys.executable, '-c', code['code']], cwd=work, capture_output=True, text=True, timeout=300)
check.near('the code\'s -2 log L is the report\'s', float(run.stdout.split()[-1]), code['summary']['m2ll'], rel=1e-6)

# ---- statsmodels' own survival data, at run time ---------------------------------------------------
try:
    import statsmodels.api as sm
    heart = sm.datasets.heart.load_pandas().data
except Exception as e:  # pragma: no cover - the dataset ships with statsmodels
    heart = None
    print('skip heart:', e)
if heart is not None:
    th_ = table({'survival': heart['survival'].to_numpy(float), 'censors': heart['censors'].to_numpy(float), 'age': heart['age'].to_numpy(float)}, types={'censors': 'nominal'})
    # censors: 1 = died, so the censored rows carry 0
    hk = call('survival.km', table=th_, time='survival', censor='censors', censor_code=0)['groups'][0]
    sfh = SurvfuncRight(heart['survival'].to_numpy(float), heart['censors'].to_numpy(float))
    check.near('heart: median survival = SurvfuncRight', hk['median'], float(sfh.quantile(0.5)))
    check('heart: deaths', hk['failed'], int(heart['censors'].sum()))
    hp = call('phreg.fit', table=th_, time='survival', effects=['age'], censor='censors', censor_code=0)
    ref = PHReg(heart['survival'].to_numpy(float), heart[['age']].to_numpy(float), status=heart['censors'].to_numpy(float)).fit(disp=0)
    check.near('heart: PH age coefficient = PHReg', hp['estimates']['rows'][0]['estimate'], float(ref.params[0]), rel=1e-6)

sys.exit(check.done())
