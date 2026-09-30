#!/usr/bin/env python3
"""DOE > Sample Size Explorers > Test Calculators (resources/py/smui/calculators.py),
through registry.dispatch as the page calls it.

Two Means against scipy's t tests on raw samples of our own whose summary
statistics are the calculator's inputs (Welch and pooled, the three
alternatives, a hypothesized difference as a shifted sample, the interval
of the difference and the degrees of freedom), each mean's interval, the
effect sizes against the formulas written out here (the noncentral t
inverted by bisection, Hedges' J from the gamma function, Bonett's
standard error); Two Proportions against the closed forms (the pooled z
test, Wald, Agresti-Caffo, Newcombe from Wilson's intervals, Katz, Woolf),
the score interval against its own test (it inverts it), each group's
Wilson interval; the graph's density, its shaded tails (their area is the
p-value) and critical values, and its matplotlib code; Multiple Tests
against Holm's and Benjamini-Hochberg's step formulas and multipletests;
the errors; and every code block run, giving the report's numbers.

    python3 resources/tests/smui/test_calculators.py
"""
import contextlib
import io
import math
import os
import tempfile

import numpy as np
import pandas as pd
from scipy import special, stats

from backend import FAILED, Checks, call
from test_charts import run_snippet

check = Checks()
check('calculators.py imports', FAILED.get('calculators'), None)
tmp = tempfile.mkdtemp(prefix='smui-calc-')


def run(code):
    """A code block run on its own: what it prints."""
    buf = io.StringIO()
    ns = {'__name__': '__main__'}
    with contextlib.redirect_stdout(buf):
        exec(code, ns)
    return buf.getvalue(), ns


def compute(*tests, alpha=0.05):
    return call('calculators.compute', tests=list(tests), alpha=alpha)


def means_test(a, b, **kw):
    """A Two Means test whose inputs are the summary statistics of samples a and b."""
    t = {'key': kw.pop('key', 'm'), 'kind': 'means', 'name': kw.pop('name', 'M'),
         'g1': {'name': 'B', 'mean': float(np.mean(a)), 'sd': float(np.std(a, ddof=1)), 'n': len(a)},
         'g2': {'name': 'A', 'mean': float(np.mean(b)), 'sd': float(np.std(b, ddof=1)), 'n': len(b)}}
    t.update(kw)
    return t


rng = np.random.default_rng(20260929)
a = rng.normal(51.0, 12.0, 83)
b = rng.normal(47.5, 17.0, 64)

# ---- Two Means: Welch and pooled against scipy's t tests on the rows ---------------------------
for variance, equal in (('unequal', False), ('equal', True)):
    for d0 in (0.0, 1.75):
        for alt in ('two-sided', 'greater', 'less'):
            r = compute(means_test(a, b, null=d0 or '', alternative=alt, variance=variance))['tests'][0]
            lab = f'Two Means, {variance}, d0 {d0}, {alt}'
            ref = {x: stats.ttest_ind(a - d0, b, equal_var=equal, alternative=x) for x in ('two-sided', 'greater', 'less')}
            check.near(f'{lab}: t = scipy\'s on the rows (the first sample shifted by d0)', r['t'], float(ref['two-sided'].statistic), 1e-10)
            check.near(f'{lab}: DF', r['df'], float(ref['two-sided'].df), 1e-10)
            check.near(f'{lab}: Prob > |t|', r['p_two'], float(ref['two-sided'].pvalue), 1e-9)
            check.near(f'{lab}: Prob > t', r['p_greater'], float(ref['greater'].pvalue), 1e-9)
            check.near(f'{lab}: Prob < t', r['p_less'], float(ref['less'].pvalue), 1e-9)
            check.near(f'{lab}: the chosen p-value', r['p'], float(ref[alt].pvalue), 1e-9)
            ci = stats.ttest_ind(a, b, equal_var=equal).confidence_interval(0.95)
            check.near(f'{lab}: Lower CL Dif = scipy\'s interval of the difference', r['lower'], float(ci.low), 1e-9)
            check.near(f'{lab}: Upper CL Dif', r['upper'], float(ci.high), 1e-9)
            check.near(f'{lab}: the difference', r['diff'], float(np.mean(a) - np.mean(b)), 1e-12)

r = compute(means_test(a, b, variance='equal'))['tests'][0]
for i, s in enumerate((a, b)):
    lo, hi = stats.t.interval(0.95, len(s) - 1, loc=np.mean(s), scale=stats.sem(s))
    check.near(f'each mean\'s interval: group {i + 1}, lower', r['summary'][i]['lower'], float(lo), 1e-10)
    check.near(f'each mean\'s interval: group {i + 1}, upper', r['summary'][i]['upper'], float(hi), 1e-10)
    check.near(f'each mean\'s standard error: group {i + 1}', r['summary'][i]['se'], float(stats.sem(s)), 1e-12)
check('the groups keep their names', (r['groups'], [g['group'] for g in r['summary']]), (['B', 'A'], ['B', 'A']))

# ---- the effect sizes, from the formulas -----------------------------------------------------
n1, n2 = len(a), len(b)
v1, v2 = np.var(a, ddof=1), np.var(b, ddof=1)
df_p = n1 + n2 - 2
sp = math.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / df_p)
diff = np.mean(a) - np.mean(b)
J = special.gamma(df_p / 2) / (math.sqrt(df_p / 2) * special.gamma((df_p - 1) / 2))


def lam_at(t, df, q):
    """The noncentrality at which t is the q quantile of the noncentral t, by bisection."""
    lo, hi = t - 20, t + 20
    for _ in range(200):
        mid = (lo + hi) / 2
        if stats.nct.cdf(t, df, mid) > q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


k = math.sqrt(1 / n1 + 1 / n2)
d = diff / sp
eff = {e['effect']: e for e in r['effect']}
check.near("pooled: Cohen's d = the difference over the pooled SD", eff["Cohen's d"]['estimate'], d, 1e-12)
check.near("... its lower limit, the noncentral t inverted", eff["Cohen's d"]['lower'], lam_at(d / k, df_p, 0.975) * k, 1e-7)
check.near("... its upper limit", eff["Cohen's d"]['upper'], lam_at(d / k, df_p, 0.025) * k, 1e-7)
check.near("Hedges' g = J d, J from the gamma function", eff["Hedges' g"]['estimate'], J * d, 1e-12)
r = compute(means_test(a, b, variance='unequal'))['tests'][0]
eff = {e['effect']: e for e in r['effect']}
s_ = math.sqrt((v1 + v2) / 2)
ds = diff / s_
se_b = math.sqrt(ds * ds * (v1 * v1 / (n1 - 1) + v2 * v2 / (n2 - 1)) / (8 * s_ ** 4) + (v1 / (n1 - 1) + v2 / (n2 - 1)) / s_ ** 2)
check.near("Welch: d* = the difference over the root mean variance", eff["Cohen's d*"]['estimate'], ds, 1e-12)
check.near("... Bonett's interval", eff["Cohen's d*"]['lower'], ds - stats.norm.ppf(0.975) * se_b, 1e-12)
check.near("... g* = J d*", eff["Hedges' g*"]['estimate'], J * ds, 1e-12)

# ---- the graph: the density, the tails whose area is the p-value, the critical values -----------
for alt in ('two-sided', 'greater', 'less'):
    r = compute(means_test(a, b, alternative=alt))['tests'][0]
    c = r['curve']
    x = np.asarray(c['x'])
    check.near(f'graph ({alt}): the t density of the report\'s DF', float(np.max(np.abs(np.asarray(c['y']) - stats.t.pdf(x, r['df'])))), 0, 1e-13)
    area = sum(float(np.trapezoid(t_['y'], t_['x'])) for t_ in c['tails'])
    far = stats.t.sf(c['half'], r['df']) * (2 if alt == 'two-sided' else 1)   # the part beyond the graph's edge
    check.near(f'graph ({alt}): the shaded area is the p-value', area + far, r['p'], 2e-4)
    want = [stats.t.ppf(0.025, r['df']), stats.t.ppf(0.975, r['df'])] if alt == 'two-sided' else [stats.t.ppf(0.95 if alt == 'greater' else 0.05, r['df'])]
    check.near(f'graph ({alt}): the critical values at alpha', max(abs(p - q) for p, q in zip(c['crit'], want)) + abs(len(c['crit']) - len(want)), 0, 1e-12)
    check('graph: the observed statistic, the axis', (c['stat'] == r['t'], c['label'], c['half'] >= max(4, abs(r['t']) + 1) - 1e-12), (True, 't Ratio', True))
    figs, err = run_snippet(r['plot_code'], pd.DataFrame({'x': [0]}), 'data', tmp)
    check(f'graph ({alt}): its code runs, ending in plt.show()', (err, r['plot_code'].rstrip().split('\n')[-1]), (None, 'plt.show()'))
    if figs:
        ax = figs[0]['axes'][0]
        dens = [ln for ln in ax['lines'] if len(ln['x']) > 10][0]
        check.near(f'graph ({alt}): the code\'s density is the page\'s', max(abs(p - q) for p, q in zip(dens['y'], c['y'])) + abs(len(dens['y']) - len(c['y'])), 0, 1e-12)
        vx = sorted(ln['x'][0] for ln in ax['lines'] if len(ln['x']) == 2 and ln['x'][0] == ln['x'][1])
        check.near(f'graph ({alt}): the critical values and the statistic as vertical lines', max(abs(p - q) for p, q in zip(vx, sorted(c['crit'] + [c['stat']]))) + abs(len(vx) - len(c['crit']) - 1), 0, 1e-12)
        check(f'graph ({alt}): a shaded area per tail, the titles, the size', (len(ax['polys']), ax['title'], ax['xlabel'], ax['ylabel'], figs[0]['size']),
              (len(c['tails']), 'M: t Ratio', 't Ratio', 'Density', [4.2, 2.8]))

# ---- the code gives the report's numbers ------------------------------------------------------
for variance in ('unequal', 'equal'):
    r = compute(means_test(a, b, null=0.5, alternative='greater', variance=variance))['tests'][0]
    out, ns = run(r['code'])
    check(f'Two Means code ({variance}): runs and prints scipy\'s test for each alternative', out.count('Ttest_indResult'), 3)
    check.near(f'Two Means code ({variance}): its Std Err Dif', float(ns['se']), r['se'], 1e-12)
    check.near(f'Two Means code ({variance}): its DF', float(ns['df_']), r['df'], 1e-12)
    check.near(f'Two Means code ({variance}): its effect size', float(ns['d']), r['effect'][0]['estimate'], 1e-12)
    if variance == 'equal':
        check.near('Two Means code (equal): its exact interval of d', float(ns['lo']), r['effect'][0]['lower'], 1e-9)

# ---- Two Proportions against the closed forms -----------------------------------------------------
x1, m1, x2, m2 = 61, 1310, 38, 1275
p1, p2 = x1 / m1, x2 / m2
z975 = stats.norm.ppf(0.975)


def props(**kw):
    t = {'key': 'p', 'kind': 'props', 'name': 'P', 'g1': {'name': 'B', 'count': x1, 'n': m1}, 'g2': {'name': 'A', 'count': x2, 'n': m2}}
    t.update(kw)
    return compute(t)['tests'][0]


pool = (x1 + x2) / (m1 + m2)
zp = (p1 - p2) / math.sqrt(pool * (1 - pool) * (1 / m1 + 1 / m2))
for alt, want in (('two-sided', 2 * stats.norm.sf(abs(zp))), ('greater', stats.norm.sf(zp)), ('less', stats.norm.cdf(zp))):
    r = props(alternative=alt)
    check.near(f'Two Proportions, the default (score) at 0: the pooled z ({alt})', r['z'], zp, 1e-10)
    check.near(f'... its p-value ({alt})', r['p'], want, 1e-10)
check.near('the estimate is the difference of the proportions', r['estimate'], p1 - p2, 1e-14)
mt = {m['key']: m for m in r['methods']}
se_w = math.sqrt(p1 * (1 - p1) / m1 + p2 * (1 - p2) / m2)
check.near('Wald: z', mt['wald']['z'], (p1 - p2) / se_w, 1e-10)
check.near('Wald: the interval', max(abs(mt['wald']['lower'] - (p1 - p2 - z975 * se_w)), abs(mt['wald']['upper'] - (p1 - p2 + z975 * se_w))), 0, 1e-12)
q1, q2 = (x1 + 1) / (m1 + 2), (x2 + 1) / (m2 + 2)
se_ac = math.sqrt(q1 * (1 - q1) / (m1 + 2) + q2 * (1 - q2) / (m2 + 2))
check.near('Agresti-Caffo: one success and one failure added to each group, z', mt['agresti-caffo']['z'], (q1 - q2) / se_ac, 1e-10)
check.near('Agresti-Caffo: the interval', max(abs(mt['agresti-caffo']['lower'] - (q1 - q2 - z975 * se_ac)), abs(mt['agresti-caffo']['upper'] - (q1 - q2 + z975 * se_ac))), 0, 1e-12)


def wilson(x, n):
    ph, z = x / n, z975
    c = (ph + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return c - h, c + h


(l1, u1), (l2, u2) = wilson(x1, m1), wilson(x2, m2)
check.near('each group\'s Wilson interval', max(abs(r['summary'][0]['lower'] - l1), abs(r['summary'][0]['upper'] - u1), abs(r['summary'][1]['lower'] - l2), abs(r['summary'][1]['upper'] - u2)), 0, 1e-12)
nw_lo = p1 - p2 - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
nw_hi = p1 - p2 + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
check.near('Newcombe\'s interval from the two Wilson intervals', max(abs(mt['newcomb']['lower'] - nw_lo), abs(mt['newcomb']['upper'] - nw_hi)), 0, 1e-12)
check('Newcombe\'s is an interval only', mt['newcomb']['z'], None)
# the score interval inverts the score test: at its limits the two-sided p-value is alpha
for key in ('score', 'mn'):
    lo, hi = mt[key]['lower'], mt[key]['upper']
    pl = props(null=lo, method=key)['p_two']
    ph = props(null=hi, method=key)['p_two']
    check.near(f'{key}: the test at the interval\'s lower limit gives p = alpha', pl, 0.05, 2e-4)
    check.near(f'{key}: ... and at its upper limit', ph, 0.05, 2e-4)
check('Miettinen-Nurminen\'s factor makes the score test a little less sure', mt['mn']['p_two'] > mt['score']['p_two'], True)
# ratio and odds ratio: Katz's and Woolf's intervals by hand
r = props(compare='ratio', method='log')
mt = {m['key']: m for m in r['methods']}
se_k = math.sqrt(1 / x1 - 1 / m1 + 1 / x2 - 1 / m2)
check.near('Ratio: the estimate p1/p2', r['estimate'], p1 / p2, 1e-14)
check.near('Katz (log): the interval', max(abs(mt['log']['lower'] - p1 / p2 * math.exp(-z975 * se_k)), abs(mt['log']['upper'] - p1 / p2 * math.exp(z975 * se_k))), 0, 1e-10)
check.near('Katz (log): z of log(p1/p2) at a null ratio of 1', r['z'], math.log(p1 / p2) / se_k, 1e-10)
r = props(compare='odds-ratio', method='logit')
mt = {m['key']: m for m in r['methods']}
orr = (x1 / (m1 - x1)) / (x2 / (m2 - x2))
se_o = math.sqrt(1 / x1 + 1 / (m1 - x1) + 1 / x2 + 1 / (m2 - x2))
check.near('Odds ratio: the estimate', r['estimate'], orr, 1e-12)
check.near('Woolf (logit): the interval', max(abs(mt['logit']['lower'] - orr * math.exp(-z975 * se_o)), abs(mt['logit']['upper'] - orr * math.exp(z975 * se_o))), 0, 1e-10)
check.near('Woolf (logit): z', r['z'], math.log(orr) / se_o, 1e-10)
r = props(compare='ratio', null=1.2, alternative='less')
check('a hypothesized ratio and a one-sided test', (r['null'], r['alternative'], r['p'] == r['p_less']), (1.2, 'less', True))

# ---- the proportions' graph and the code -----------------------------------------------------------
r = props()
c = r['curve']
check.near('proportions: the graph is the standard normal density', float(np.max(np.abs(np.asarray(c['y']) - stats.norm.pdf(np.asarray(c['x']))))), 0, 1e-14)
check('... its axis is z', (c['label'], c['df']), ('z', None))
out, ns = run(r['code'])
check('Two Proportions code: runs, every method printed', all(m['method'] in out for m in r['methods']), True)
check.near('... its default test gives the report\'s z', float(__import__('statsmodels.stats.proportion', fromlist=['x']).test_proportions_2indep(x1, m1, x2, m2, method='score', correction=False).statistic), r['z'], 1e-12)
figs, err = run_snippet(r['plot_code'], pd.DataFrame({'x': [0]}), 'data', tmp)
check('proportions: the graph\'s code runs', err, None)

# ---- zero counts, errors ----------------------------------------------------------------------------
r = compute({'key': 'z', 'kind': 'props', 'g1': {'count': 0, 'n': 40}, 'g2': {'count': 6, 'n': 45}, 'compare': 'ratio', 'method': 'score'})['tests'][0]
check('a zero count: the score test still works, a note says why others do not', ('error' not in r, any('0' in n for n in r['notes'])), (True, True))
bad = compute({'key': 'e1', 'kind': 'props', 'g1': {'count': 5, 'n': 3}, 'g2': {'count': 1, 'n': 10}},
              {'key': 'e2', 'kind': 'means', 'g1': {'mean': 1, 'sd': 1, 'n': 1}, 'g2': {'mean': 1, 'sd': 1, 'n': 5}},
              {'key': 'e3', 'kind': 'means', 'g1': {'mean': 1, 'sd': 0, 'n': 3}, 'g2': {'mean': 2, 'sd': 0, 'n': 5}},
              {'key': 'e4', 'kind': 'props', 'g1': {'count': 1, 'n': 3}, 'g2': {'count': 1, 'n': 10}, 'compare': 'ratio', 'null': -1},
              {'key': 'e5', 'kind': 'props', 'g1': {'count': 1, 'n': 3}, 'g2': {'count': 1, 'n': 10}, 'method': 'newcomb'},
              {'key': 'e6', 'kind': 'means', 'g1': {'mean': 'x', 'sd': 1, 'n': 5}, 'g2': {'mean': 1, 'sd': 1, 'n': 5}})['tests']
check('errors are each test\'s own, in words', [t.get('error') for t in bad],
      ['Count 1: from 0 to N 1', 'N 1: at least 2 (a standard deviation needs two values)', 'both standard deviations are 0: no test',
       'Hypothesized Value: a ratio above 0', "the method 'newcomb' has no test of the difference", 'Mean 1: not a number'])
try:
    compute(means_test(a, b), alpha=1.5)
    check('α 1.5 refused', False, True)
except Exception as e:
    check('α 1.5 refused', 'α' in str(e), True)

# ---- Multiple Tests: Holm and Benjamini-Hochberg by their step formulas, and multipletests ---------------
tests = [means_test(a, b, key='a', name='Uploads', alternative='greater'),
         {'key': 'b', 'kind': 'props', 'name': 'Conversions', 'g1': {'count': x1, 'n': m1}, 'g2': {'count': x2, 'n': m2}, 'alternative': 'greater'},
         means_test(rng.normal(10, 3, 40), rng.normal(10.4, 3, 45), key='c', name='Minutes'),
         {'key': 'd', 'kind': 'props', 'name': 'Bad', 'g1': {'count': 9, 'n': 3}, 'g2': {'count': 1, 'n': 3}}]
R = compute(*tests, alpha=0.05)
M = R['multiple']
p = np.array([t['p'] for t in R['tests'] if 'error' not in t])
check('Multiple Tests: the good tests only, by name, their chosen p-values', ([r_['test'] for r_ in M['rows']], [r_['p'] for r_ in M['rows']]), (['Uploads', 'Conversions', 'Minutes'], p.tolist()))
o = np.argsort(p)
m_ = len(p)
holm = np.empty(m_)
holm[o] = np.minimum(1, np.maximum.accumulate(p[o] * (m_ - np.arange(m_))))
bh = np.empty(m_)
bh[o] = np.minimum(1, np.minimum.accumulate((p[o] * m_ / (np.arange(m_) + 1))[::-1])[::-1])
check.near('Holm = the step-down formula', float(np.max(np.abs(np.array([r_['holm'] for r_ in M['rows']]) - holm))), 0, 1e-14)
check.near('Benjamini-Hochberg = the step-up formula', float(np.max(np.abs(np.array([r_['fdr_bh'] for r_ in M['rows']]) - bh))), 0, 1e-14)
check.near('Bonferroni = m p, at most 1', float(np.max(np.abs(np.array([r_['bonferroni'] for r_ in M['rows']]) - np.minimum(1, m_ * p)))), 0, 1e-14)
from statsmodels.stats.multitest import multipletests
worst = max(float(np.max(np.abs(np.array([r_[k] for r_ in M['rows']]) - multipletests(p, alpha=0.05, method=k)[1]))) for k in ('sidak', 'holm-sidak', 'simes-hochberg', 'hommel', 'fdr_by'))
check.near('the other methods = multipletests\'', worst, 0, 1e-14)
check('Holm and Benjamini-Hochberg shown, the rest in the Columns menu', [(m['key'], m['shown']) for m in M['methods']][:3], [('holm', True), ('fdr_bh', True), ('bonferroni', False)])
out, ns = run(M['code'])
check('Multiple Tests code: runs and prints every method', all(k in out for k in ('holm', 'fdr_bh', 'hommel')), True)
one = compute(means_test(a, b))
check('one test: no Multiple Tests', 'multiple' in one, False)

raise SystemExit(check.done())
