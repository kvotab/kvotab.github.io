#!/usr/bin/env python3
"""Analyze > Distribution's backend (resources/py/smui/distribution.py),
checked against scipy and statsmodels called directly, and against the
definitions JMP documents: quantiles by (n+1)p, the normal quantile plot
at r/(n+1), Wilson intervals for proportions.

    python3 resources/tests/smui/test_distribution.py
"""
import math
import sys

import numpy as np
from scipy import stats
from statsmodels.stats.proportion import proportion_confint
from statsmodels.stats.weightstats import DescrStatsW

from backend import Checks, call, table

check = Checks()
rng = np.random.default_rng(20260926)
x = rng.normal(50, 7, 83)
x[5] = np.nan
g = rng.choice(['a', 'b', 'c'], 83, p=[0.5, 0.3, 0.2]).tolist()
w = rng.uniform(0.5, 2, 83)
tid = table({'x': x, 'g': g, 'w': w})
xs = x[np.isfinite(x)]
n = len(xs)

r = call('distribution.continuous', table=tid, column='x')
m = r['moments']
check('n and n missing', (m['n'], r['n_missing']), (float(n), 1))
check.near('mean', m['mean'], float(np.mean(xs)))
check.near('std dev (n-1)', m['sd'], float(np.std(xs, ddof=1)))
check.near('std err mean', m['se'], float(np.std(xs, ddof=1) / math.sqrt(n)))
lo, hi = stats.t.interval(0.95, n - 1, loc=np.mean(xs), scale=np.std(xs, ddof=1) / math.sqrt(n))
check.near('lower 95% mean', m['lower'], float(lo))
check.near('upper 95% mean', m['upper'], float(hi))
check.near('skewness (unbiased)', m['skewness'], float(stats.skew(xs, bias=False)))
check.near('kurtosis (unbiased excess)', m['kurtosis'], float(stats.kurtosis(xs, bias=False)))
# JMP's quantiles: the (n+1)p-th order statistic, interpolated
srt = np.sort(xs)


def jmp_q(p):
    h = (n + 1) * p
    if h <= 1:
        return srt[0]
    if h >= n:
        return srt[-1]
    k = int(math.floor(h))
    return srt[k - 1] + (h - k) * (srt[k] - srt[k - 1])


for q in r['quantiles']:
    check.near(f'quantile {q["p"]}', q['value'], float(jmp_q(q['p'])))
check('quantile labels', [q['label'] for q in r['quantiles'] if q['label']], ['maximum', 'quartile', 'median', 'quartile', 'minimum'])
sw = [t for t in r['normality'] if t['test'].startswith('Shapiro')][0]
check.near('Shapiro-Wilk W', sw['stat'], float(stats.shapiro(xs).statistic))
check.near('robust mean is Huber', m['robust_mean'], float(np.asarray(__import__('statsmodels.robust.scale', fromlist=['Huber']).Huber()(xs)[0])), rel=1e-7)
check('code shown', 'DescrStatsW' in r['code'], True)

# weights
rw = call('distribution.continuous', table=tid, column='x', weight='w')
ww = w[np.isfinite(x)]
d = DescrStatsW(xs, weights=ww, ddof=1)
check.near('weighted mean', rw['moments']['mean'], float(d.mean))
check.near('weighted sd', rw['moments']['sd'], float(d.std))
check('weighted: no normality tests', rw['normality'], None)

# normal quantile plot positions
qq = call('distribution.qq', table=tid, column='x')
check.near('qq first z', qq['z'][0], float(stats.norm.ppf(1 / (n + 1))))
check('qq rows are table rows', sorted(qq['rows'])[:6], [0, 1, 2, 3, 4, 6])

# tests
tm = call('distribution.test_mean', table=tid, column='x', mu=48)
t_ref = stats.ttest_1samp(xs, 48)
check.near('t test', tm['t']['stat'], float(t_ref.statistic))
check.near('t test p', tm['t']['p_two'], float(t_ref.pvalue))
check.near('wilcoxon p', tm['wilcoxon']['p_two'], float(stats.wilcoxon(xs - 48).pvalue))
ts = call('distribution.test_sd', table=tid, column='x', sigma=6)
check.near('chi-square of sd', ts['chi2'], float((n - 1) * np.var(xs, ddof=1) / 36))
eq = call('distribution.equivalence', table=tid, column='x', low=45, upp=55)
check.near('TOST p', eq['p'], float(DescrStatsW(xs, ddof=1).ttost_mean(45, 55)[0]))
iv = call('distribution.intervals', table=tid, column='x', alpha=0.05, k_future=1, coverage=0.9)
half = stats.t.ppf(0.975, n - 1) * np.std(xs, ddof=1) * math.sqrt(1 + 1 / n)
check.near('prediction interval', iv['prediction']['upper'], float(np.mean(xs) + half))

# fits
f = call('distribution.fit', table=tid, column='x', dist='normal')
check.near('normal fit mu', f['params'][0]['estimate'], float(np.mean(xs)))
check.near('normal fit sigma (n-1)', f['params'][1]['estimate'], float(np.std(xs, ddof=1)))
fw = call('distribution.fit', table=tid, column='x', dist='weibull')
c, loc, scale = stats.weibull_min.fit(xs, floc=0)
check.near('weibull scale', fw['params'][0]['estimate'], float(scale), rel=1e-4)
check.near('weibull shape', fw['params'][1]['estimate'], float(c), rel=1e-4)
check('weibull has standard errors', all(p['se'] and p['se'] > 0 for p in fw['params']), True)
fa = call('distribution.fit_all', table=tid, column='x')
check('fit all sorted by AICc', [x['aicc'] for x in fa['fits']] == sorted(x['aicc'] for x in fa['fits']), True)
check.near('AICc weights sum to one', sum(x['weight'] for x in fa['fits']), 1.0)

# more of JMP's Continuous Fit list
tw = stats.t.rvs(4, loc=3, scale=2, size=83, random_state=5)
k = np.random.default_rng(3).negative_binomial(3, 0.4, 83).astype(float)
mix = np.concatenate([np.random.default_rng(4).normal(10, 1, 50), np.random.default_rng(5).normal(16, 1, 33)])
tid2 = table({'t': tw.tolist(), 'k': k.tolist(), 'mix': mix.tolist()})
ft = call('distribution.fit', table=tid2, column='t', dist='t')
df_, loc_, sc_ = stats.t.fit(tw)
check.near("Student's t location as scipy", ft['params'][0]['estimate'], float(loc_), rel=1e-4)
check.near("Student's t df as scipy", ft['params'][2]['estimate'], float(df_), rel=1e-3)
fm = call('distribution.fit', table=tid2, column='mix', dist='normal2')
check('normal 2 mixture finds the components', (round(fm['params'][0]['estimate']), round(fm['params'][1]['estimate'])), (10, 16))
check.near('mixture proportion', fm['params'][4]['estimate'], 50 / 83, abs_=0.05)
import statsmodels.api as sm
nb = sm.NegativeBinomial(k, np.ones(len(k))).fit(disp=0)
alpha_nb = float(nb.params[-1])
fn = call('distribution.fit', table=tid2, column='k', dist='negbin')
check.near('Gamma Poisson mean = sample mean', fn['params'][0]['estimate'], float(np.mean(k)), rel=1e-4)
check.near('Gamma Poisson σ = 1 + α μ (statsmodels NB2)', fn['params'][1]['estimate'], 1 + alpha_nb * float(np.mean(k)), rel=1e-3)
fk = call('distribution.fit', table=tid2, column='mix', dist='kde')
check.near('smooth curve integrates to one', float(np.trapezoid(fk['curve']['pdf'], fk['curve']['x'])), 1.0, abs_=0.01)

# capability
cp = call('distribution.capability', table=tid, column='x', lsl=30, usl=70)
s = float(np.std(xs, ddof=1))
check.near('Cp overall', cp['sigma']['overall']['cp'], 40 / (6 * s))
check.near('Cpk overall', cp['sigma']['overall']['cpk'], min(70 - np.mean(xs), np.mean(xs) - 30) / (3 * s))

# categorical
cr = call('distribution.categorical', table=tid, column='g')
counts = {lv: g.count(lv) for lv in 'abc'}
check('level counts', [(l['level'], l['count']) for l in cr['levels']], [(k, float(v)) for k, v in counts.items()])
lo, hi = proportion_confint(counts['a'], 83, method='wilson')
check.near('Wilson interval', cr['levels'][0]['lower'], float(lo))
tp = call('distribution.test_probs', table=tid, column='g', probs={'a': 1, 'b': 1, 'c': 1})
check.near('Pearson chi-square', tp['tests'][1]['stat'], float(stats.chisquare(list(counts.values())).statistic))
# rows subset and the error path
check('rows subset (row 5 is missing)', call('distribution.continuous', table=tid, column='x', rows=list(range(10)))['moments']['n'], 9.0)
check('no values', 'error' in call('distribution.continuous', table=tid, column='x', rows=[5]), True)
sys.exit(check.done())
