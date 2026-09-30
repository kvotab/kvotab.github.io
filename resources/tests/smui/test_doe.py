#!/usr/bin/env python3
"""The DOE backend (resources/py/smui/doe.py and power.py): the designs of
DOE > Classical and DOE > Special Purpose, Evaluate Design, and Sample Size
and Power.

The designs are checked by their defining properties: every combination of
a full factorial, orthogonal and balanced two-level columns, the resolution
of each fractional factorial against Montgomery's table (Design and Analysis
of Experiments, table 8.14) and its alias structure, the orthogonality of
the Plackett-Burman designs, the rotatability and orthogonality conditions
of central composite designs, the Box-Behnken structure, and one point per
stratum of a Latin hypercube. Evaluate Design against the efficiencies of an
orthogonal design and the noncentral F. Power against statsmodels called
directly and textbook numbers (one-sample t: n = 33.4 for d = 0.5; two-sample:
63.8 per group; Cohen's f = 0.25 for four groups; the pooled two-proportion
z test; six sigma is 3.4 defects per million). Split plots and blocked full
factorials by their structure (each whole plot one setting of the
hard-to-change factors with every combination of the others, its runs
together; each block a complete replicate), their code, the design's model
fitted by Fit Model's REML against the exact split-plot F tests (Kenward-Roger
df 4 on the whole plots, 20 within them), and Simulate Responses' formula.

    python3 resources/tests/smui/test_doe.py
"""
import itertools
import math
import sys
from collections import Counter

import numpy as np
from scipy import stats

from backend import FAILED, Checks, call, table

check = Checks()
check('doe module imports', FAILED.get('doe'), None)
check('power module imports', FAILED.get('power'), None)
from smui import doe as D  # noqa: E402


def coded(res, names, lows=None, highs=None):
    cols = {c['name']: c['values'] for c in res['columns']}
    X = []
    for j, nm in enumerate(names):
        v = np.array(cols[nm], dtype=float)
        lo, hi = (lows[j], highs[j]) if lows else (v.min(), v.max())
        X.append((v - (lo + hi) / 2) / ((hi - lo) / 2))
    return np.column_stack(X)


cf = lambda name, lo=-1, hi=1: {'name': name, 'kind': 'continuous', 'low': lo, 'high': hi}

# ---------------------------------------------------------------------------
# Full factorial
fs = [cf('Temp', 150, 200), cf('Time', 10, 20), {'name': 'Catalyst', 'kind': 'categorical', 'levels': ['A', 'B', 'C']}]
r = call('doe.full_factorial', factors=fs, responses=[{'name': 'Yield'}, {'name': 'Cost'}], replicates=1, center_points=3, seed=11)
cols = {c['name']: c for c in r['columns']}
check('runs: 2·2·3 combinations × 2 + 3 center points', r['n_runs'], 27)
check('column order: Pattern, factors, responses', [c['name'] for c in r['columns']], ['Pattern', 'Temp', 'Time', 'Catalyst', 'Yield', 'Cost'])
combos = Counter(zip(cols['Temp']['values'], cols['Time']['values'], cols['Catalyst']['values']))
check('every combination twice', all(combos[(t, m, c)] == 2 for t in (150.0, 200.0) for m in (10.0, 20.0) for c in 'ABC'), True)
check('center points at the middle', combos[(175.0, 15.0, 'A')] + combos[(175.0, 15.0, 'B')] + combos[(175.0, 15.0, 'C')], 3)
check('modeling types', [(c['name'], c['modelingType']) for c in r['columns']], [('Pattern', 'nominal'), ('Temp', 'continuous'), ('Time', 'continuous'), ('Catalyst', 'nominal'), ('Yield', 'continuous'), ('Cost', 'continuous')])
check('the responses are empty', all(v is None for v in cols['Yield']['values']), True)
check('patterns: − and + for continuous, the level number for categorical, 0 at the center', set(cols['Pattern']['values']), {a + b + c for a in '−+' for b in '−+' for c in '123'} | {'001', '002', '003'})
check('a pattern per run', Counter(cols['Pattern']['values'])['−+2'], 2)
r2 = call('doe.full_factorial', factors=fs, replicates=1, center_points=3, seed=11)
check('the same seed gives the same run order', r2['columns'][1]['values'], r['columns'][1]['values'])
r3 = call('doe.full_factorial', factors=fs, replicates=1, center_points=3, seed=12)
check('another seed another order', r3['columns'][1]['values'] != r['columns'][1]['values'], True)
check('the notes give the seed', 'seed 11' in r['notes'], True)
r4 = call('doe.full_factorial', factors=[cf('A'), cf('B'), cf('C')], order='sort_lr')
X = coded(r4, ['A', 'B', 'C'])
check('2^3 sorted left to right: the first factor changes slowest', X[:, 0].tolist(), [-1.0] * 4 + [1.0] * 4)
check('2^3: orthogonal columns', np.allclose(X.T @ X, 8 * np.eye(3)), True)
check('coding in the column notes', r4['columns'][1]['notes'], 'Factor. Coding [low, high]: -1, 1')
try:
    call('doe.full_factorial', factors=[cf('A', 2, 1)])
    check('low above high is refused', False, True)
except Exception as e:
    check('low above high is refused', 'low value' in str(e), True)

# ---------------------------------------------------------------------------
# Screening: fractional factorials, resolution, aliases
MONT = {(3, 4): 3, (4, 8): 4, (5, 16): 5, (5, 8): 3, (6, 32): 6, (6, 16): 4, (6, 8): 3, (7, 64): 7, (7, 32): 4, (7, 16): 4, (7, 8): 3,
        (8, 64): 5, (8, 32): 4, (8, 16): 4, (9, 128): 6, (9, 64): 4, (9, 32): 4, (9, 16): 3, (10, 128): 5, (10, 64): 4, (10, 32): 4,
        (10, 16): 3, (11, 128): 5, (11, 64): 4, (11, 32): 4, (11, 16): 3}
bad = [(k, n) for (k, n), res in MONT.items() if D.resolution(k, int(math.log2(n)), D.GENERATORS[k][n]) != res]
check('every generator set has the resolution of Montgomery\'s table 8.14', bad, [])
for k in range(3, 12):
    lst = call('doe.screening_designs', n_factors=k)['designs']
    for d in lst:
        if d['type'] == 'Full Factorial' and 2 ** k > 64:
            continue
        fsk = [cf(f'X{i + 1}') for i in range(k)]
        res = call('doe.screening', factors=fsk, design=d['key'], order='keep', seed=1)
        Xk = coded(res, [f'X{i + 1}' for i in range(k)])
        N = len(Xk)
        ok = N == d['runs'] and np.allclose(Xk.T @ Xk, N * np.eye(k)) and np.allclose(Xk.sum(axis=0), 0)
        if not ok:
            check(f'{k} factors, {d["key"]}: orthogonal and balanced', False, True)
check('every screening design of 3 to 11 factors: orthogonal, balanced columns of the listed runs', True, True)
res = call('doe.screening', factors=[cf(n) for n in 'ABCD'], design='ff:8', order='keep')
check('2^(4−1): I = ABCD', res['defining_relation'], ['I = A*B*C*D'])
al = {a['effect']: a['aliases'] for a in res['aliases']}
check('2^(4−1): A is aliased with BCD', al['A'], 'B*C*D')
check('2^(4−1): AB with CD', al['A*B'], 'C*D')
Xf = coded(res, list('ABCD'))
check('2^(4−1): D = ABC in the runs', np.allclose(Xf[:, 3], Xf[:, 0] * Xf[:, 1] * Xf[:, 2]), True)
res = call('doe.screening', factors=[cf(f'X{i}') for i in range(1, 7)], design='ff:16', order='keep')
check('2^(6−2): resolution IV', res['design']['resolution'], 'IV')
words = [w for w in res['defining_relation']]
check('2^(6−2): three words of length 4', sorted(len(w.split('=')[1].strip().split('*')) for w in words), [4, 4, 4])
res = call('doe.screening', factors=[cf(f'X{i}') for i in range(1, 8)], design='auto')
check('auto picks the smallest resolution IV design for 7 factors (16 runs)', (res['n_runs'], res['design']['resolution']), (16, 'IV'))
# Plackett-Burman
for N in (12, 20, 24):
    M = D._pb_matrix(N)
    check(f'Plackett-Burman {N}: orthogonal, balanced columns', np.allclose(M.T @ M, N * np.eye(N - 1)) and np.allclose(M.sum(axis=0), 0), True)
res = call('doe.screening', factors=[cf(f'X{i}') for i in range(1, 12)], design='pb:12', order='keep')
Xp = coded(res, [f'X{i}' for i in range(1, 12)])
two = Xp[:, 1] * Xp[:, 2]
check('PB 12: a main effect is aliased with a 2FI by ±1/3', abs(float(Xp[:, 0] @ two) / 12), 1 / 3)
check('PB 12 with center points and categorical two-level factors', call('doe.screening', factors=[cf('A'), {'name': 'B', 'kind': 'categorical', 'levels': ['lo', 'hi']}, cf('C'), cf('E')], design='pb:12', center_points=2)['n_runs'], 14)
try:
    call('doe.screening', factors=[cf('A'), {'name': 'B', 'kind': 'categorical', 'levels': ['a', 'b', 'c']}])
    check('three-level factor refused', False, True)
except Exception as e:
    check('three-level factor refused', 'two-level' in str(e), True)

# ---------------------------------------------------------------------------
# Response surface designs
for k in range(2, 9):
    for axial in ('rotatable', 'orthogonal', 'face'):
        nc = D.CCD_CENTER[k]
        res = call('doe.rsm', factors=[cf(f'X{i}') for i in range(k)], design=f'ccd:{axial}', order='keep')
        X = coded(res, [f'X{i}' for i in range(k)], [-1] * k, [1] * k)
        F = len(D._ccd_cube(k)[0])
        a = res['alpha']
        if axial == 'rotatable':
            ok = abs(a - F ** 0.25) < 1e-12
            # rotatability: sum x_i^4 = 3 sum x_i^2 x_j^2 for every pair
            ok = ok and all(abs(np.sum(X[:, i] ** 4) - 3 * np.sum(X[:, i] ** 2 * X[:, j] ** 2)) < 1e-9 for i in range(k) for j in range(k) if i != j)
            check(f'CCD rotatable, {k} factors: α = F^¼ = {a:.4f} and the moment condition holds', ok, True)
        elif axial == 'orthogonal':
            Q = X ** 2 - (X ** 2).mean(axis=0)
            ok = all(abs(float(Q[:, i] @ Q[:, j])) < 1e-9 for i in range(k) for j in range(i + 1, k)) if k > 1 else True
            check(f'CCD orthogonal, {k} factors: the centred squares are uncorrelated (α = {a:.4f})', ok, True)
        else:
            check(f'CCD face centred, {k} factors: α = 1, three levels', (a, sorted(set(np.round(X[:, 0], 9)))), (1.0, [-1.0, 0.0, 1.0]))
        check(f'CCD {axial}, {k} factors: {F} + {2 * k} + {nc} runs', res['n_runs'], F + 2 * k + nc)
res = call('doe.rsm', factors=[cf('A'), cf('B'), cf('C')], design='ccd:custom', alpha=1.5, order='keep')
check('CCD with a given α', max(abs(coded(res, list('ABC'), [-1] * 3, [1] * 3)[:, 0])), 1.5)
res = call('doe.rsm', factors=[cf('A', 0, 10), cf('B'), cf('C')], design='ccd:rotatable', inscribe=True, order='keep')
check('inscribed CCD stays inside the limits', (min(res['columns'][1]['values']), max(res['columns'][1]['values'])), (0.0, 10.0))
BBD_RUNS = {3: 15, 4: 27, 5: 46, 6: 54, 7: 62}
for k in range(3, 8):
    res = call('doe.rsm', factors=[cf(f'X{i}') for i in range(k)], design='bbd', order='keep')
    X = coded(res, [f'X{i}' for i in range(k)], [-1] * k, [1] * k)
    three = all(sorted(set(X[:, j])) == [-1.0, 0.0, 1.0] for j in range(k))
    corners = int(np.sum(np.all(np.abs(X) == 1, axis=1)))
    # the full quadratic model is estimable
    cols_ = [np.ones(len(X))] + [X[:, j] for j in range(k)] + [X[:, i] * X[:, j] for i, j in itertools.combinations(range(k), 2)] + [X[:, j] ** 2 for j in range(k)]
    Mq = np.column_stack(cols_)
    check(f'Box-Behnken, {k} factors: {BBD_RUNS[k]} runs, three levels, no corners, quadratic model estimable',
          (res['n_runs'], three, corners, int(np.linalg.matrix_rank(Mq))), (BBD_RUNS[k], True, 0, Mq.shape[1]))
try:
    call('doe.rsm', factors=[cf('A'), cf('B')], design='bbd')
    check('Box-Behnken needs three factors', False, True)
except Exception as e:
    check('Box-Behnken needs three factors', '3 to 7' in str(e), True)

# ---------------------------------------------------------------------------
# Space filling
fs3 = [cf('A', 0, 1), cf('B', 10, 20), cf('C', -5, 5)]
for m in ('lhs', 'sobol', 'halton', 'uniform', 'maximin'):
    res = call('doe.space_filling', factors=fs3, n_runs=16, method=m, seed=7)
    V = np.column_stack([np.array(c['values'], float) for c in res['columns'][:3]])
    inside = bool(np.all(V[:, 0] >= 0) and np.all(V[:, 0] <= 1) and np.all(V[:, 1] >= 10) and np.all(V[:, 1] <= 20) and np.all(V[:, 2] >= -5) and np.all(V[:, 2] <= 5))
    U = (V - np.array([0, 10, -5])) / np.array([1, 10, 10])
    strata = all(sorted(np.floor(U[:, j] * 16).astype(int).tolist()) == list(range(16)) for j in range(3))
    if m in ('lhs', 'maximin', 'sobol'):
        check(f'{m}: inside the ranges, one point in each of the 16 strata of every factor', (inside, strata), (True, True))
    else:
        check(f'{m}: inside the ranges', inside, True)
    again = call('doe.space_filling', factors=fs3, n_runs=16, method=m, seed=7)
    check(f'{m}: the seed reproduces the design', again['columns'][0]['values'], res['columns'][0]['values'])
lhs = call('doe.space_filling', factors=fs3, n_runs=16, method='lhs', seed=7)
mm = call('doe.space_filling', factors=fs3, n_runs=16, method='maximin', seed=7)
check('the maximin design spreads the points further than the LHS', mm['min_distance'] > lhs['min_distance'], True)
check('the discrepancy is reported (scipy)', lhs['discrepancy'] > 0 and 'discrepancy' in lhs['notes'], True)
check('the notes give the seed, drawn or given', f"Random seed {lhs['seed']}." in lhs['notes'], True)

# ---------------------------------------------------------------------------
# Evaluate Design
ff = call('doe.full_factorial', factors=[cf('X1', 0, 10), cf('X2'), cf('X3')], order='keep')
t_ff = table({c['name']: c['values'] for c in ff['columns'] if c['name'] in ('X1', 'X2', 'X3')})
e = call('doe.evaluate', table=t_ff, factors=['X1', 'X2', 'X3'], model='main', coding={'X1': [0, 10]})
dg = {row[0]: row[1] for row in e['diagnostics']}
check('2^3, main effects: D, G and A efficiency 100', (round(dg['D Efficiency'], 9), round(dg['G Efficiency'], 9), round(dg['A Efficiency'], 9)), (100.0, 100.0, 100.0))
lam = 1.0 / (1 / 8)
pw = float(stats.ncf.sf(stats.f.ppf(0.95, 1, 4), 1, 4, lam))
check.near('power of a term (noncentral F, coefficient 1, RMSE 1)', e['power']['rows'][1]['power'], pw, rel=1e-12)
check('VIF 1 in an orthogonal design', all(abs(v['vif'] - 1) < 1e-9 for v in e['vif']['rows']), True)
check('main effects are clear of the two-factor interactions', np.allclose(np.array(e['alias']['matrix'])[1:], 0), True)
check.near('average variance of prediction = p/N·(1 + k/3 ...) for the cube: (1 + 3/3)/8', dg['Average Variance of Prediction'], (1 + 3 * (1 / 3)) / 8, rel=2e-3)
check.near('the largest relative prediction variance is at a corner: (1 + 3)/8', dg['Maximum Relative Prediction Variance'], 0.5, rel=1e-9)
check('fraction of design space: 101 quantiles, rising', (len(e['fds']['variance']), bool(np.all(np.diff(e['fds']['variance']) >= 0))), (101, True))
e2 = call('doe.evaluate', table=t_ff, factors=['X1', 'X2', 'X3'], model='2fi', coding={'X1': [0, 10]})
check('2^3 with interactions: 7 parameters, 1 error df', (e2['p'], e2['df_error']), (7, 1))
pb = call('doe.screening', factors=[cf(f'X{i}') for i in range(1, 12)], design='pb:12', order='keep')
t_pb = table({c['name']: c['values'] for c in pb['columns'] if c['name'].startswith('X')})
e3 = call('doe.evaluate', table=t_pb, factors=[f'X{i}' for i in range(1, 12)], model='main')
A = np.array(e3['alias']['matrix'])
check('PB 12 alias matrix: ±1/3 or 0', sorted({round(abs(v), 9) for v in A[1:].ravel()}), [0.0, round(1 / 3, 9)])
cols2 = e3['alias']['cols']
check('PB 12: X1 is clear of the interactions that contain X1', all(abs(A[1, j]) < 1e-12 for j, nm in enumerate(cols2) if 'X1' in nm.split('*')), True)
ccd = call('doe.rsm', factors=[cf('A'), cf('B')], design='ccd:rotatable', order='keep')
t_ccd = table({c['name']: c['values'] for c in ccd['columns'] if c['name'] in ('A', 'B')})
e4 = call('doe.evaluate', table=t_ccd, factors=['A', 'B'], model='rsm', coding={'A': [-1, 1], 'B': [-1, 1]})
check('rotatable CCD, RSM model: 6 parameters and a D efficiency below 100', (e4['p'], 0 < dict((r[0], r[1]) for r in e4['diagnostics'])['D Efficiency'] < 100), (6, True))
prof = e4['profile'][0]
check('rotatable: the prediction variance profile is symmetric', np.allclose(prof['variance'], prof['variance'][::-1]), True)
e5 = call('doe.evaluate', table=t_pb, factors=[f'X{i}' for i in range(1, 12)], model='2fi')
check('too many terms for the runs: an error that says so', 'cannot be estimated' in e5.get('error', ''), True)
tc = table({'A': [-1, 1, -1, 1, 0], 'G': ['a', 'a', 'b', 'b', 'c']})
e6 = call('doe.evaluate', table=tc, factors=['A', 'G'], model='main')
check('a categorical factor: effect coding, power of the whole effect', (e6['names'], len(e6['effect_power']['rows'])), (['Intercept', 'A', 'G[a]', 'G[b]'], 1))

# ---------------------------------------------------------------------------
# Sample Size and Power
from statsmodels.stats.power import FTestAnovaPower, NormalIndPower, TTestIndPower, TTestPower  # noqa: E402
from statsmodels.stats.proportion import power_proportions_2indep, proportion_effectsize  # noqa: E402

P = lambda **kw: call('power.compute', **kw)
r = P(situation='one_mean', sd=2, diff=1, power=0.8)
check.near('one sample mean: n (TTestPower)', r['values']['n'], TTestPower().solve_power(effect_size=0.5, alpha=0.05, power=0.8), rel=1e-6)
check.near('one sample mean: textbook n = 33.37 for d = 0.5', r['values']['n'], 33.367, abs_=0.001)
check('whole sample size 34', r['rows'][0][1], 34)
r = P(situation='one_mean', sd=1, diff=0.5, n=34)
check.near('one sample mean: power', r['values']['power'], TTestPower().power(effect_size=0.5, nobs=34, alpha=0.05), rel=1e-10)
r = P(situation='one_mean', sd=1, n=34, power=0.8)
check.near('one sample mean: the difference has power 0.8', TTestPower().power(effect_size=r['values']['diff'], nobs=34, alpha=0.05), 0.8, rel=1e-9)
check.near('one sample mean: the difference (TTestPower.solve_power, its tolerance)', r['values']['diff'], TTestPower().solve_power(nobs=34, alpha=0.05, power=0.8), rel=1e-5)
r = P(situation='one_mean', sd=1, diff=0.5, n=30, extra=2)
check.near('extra parameters take error degrees of freedom', r['values']['power'],
           float(stats.nct.sf(stats.t.ppf(0.975, 27), 27, 0.5 * math.sqrt(30)) + stats.nct.cdf(-stats.t.ppf(0.975, 27), 27, 0.5 * math.sqrt(30))), rel=1e-9)
r = P(situation='one_mean', sd=1, diff=0.5, power=0.8, sides=1)
check.near('one-sided', r['values']['n'], TTestPower().solve_power(effect_size=0.5, alpha=0.05, power=0.8, alternative='larger'), rel=1e-6)
r = P(situation='two_means', sd=1, diff=0.5, power=0.8)
check.near('two sample means: total n = 2 × 63.77', r['values']['n'], 2 * TTestIndPower().solve_power(effect_size=0.5, alpha=0.05, power=0.8), rel=1e-6)
r = P(situation='two_means', sd=1, diff=0.5, n=100, ratio=1.5)
check.near('two sample means, unequal groups', r['values']['power'], TTestIndPower().power(effect_size=0.5, nobs1=40, alpha=0.05, ratio=1.5), rel=1e-10)
r = P(situation='k_means', sd=1, means=[0, 0, 0.5, 0.5], power=0.8)
check.near("k sample means: Cohen's f = 0.25", r['rows'][0][1], 0.25, rel=1e-12)
check.near('k sample means: total n (FTestAnovaPower)', r['values']['n'], FTestAnovaPower().solve_power(effect_size=0.25, alpha=0.05, power=0.8, k_groups=4), rel=1e-6)
r = P(situation='one_prop', p0=0.5, p1=0.6, power=0.8)
h = proportion_effectsize(0.6, 0.5)
check.near("one proportion: n = ((z₀.₉₇₅ + z₀.₈)/h)²", r['values']['n'], ((stats.norm.ppf(0.975) + stats.norm.ppf(0.8)) / h) ** 2, rel=1e-4)
check.near('one proportion: n (NormalIndPower, one sample)', r['values']['n'], NormalIndPower().solve_power(effect_size=h, alpha=0.05, power=0.8, ratio=0), rel=1e-8)
r = P(situation='one_prop', p0=0.5, p1=0.6, n=200)
lo = stats.binom.ppf(0.025, 200, 0.5)
exact = [row for row in r['rows'] if 'exact' in row[0]][0][1]
xs = np.arange(201)
reject = [x_ for x_ in xs if stats.binomtest(int(x_), 200, 0.5).pvalue <= 0.05]
check.near('one proportion: exact power over the binomial test\'s rejection region', exact, float(stats.binom.pmf(reject, 200, 0.6).sum()), rel=1e-9)
r = P(situation='two_props', p1=0.6, p2=0.5, power=0.8)
pbar = 0.55
n_fleiss = (stats.norm.ppf(0.975) * math.sqrt(2 * pbar * (1 - pbar)) + stats.norm.ppf(0.8) * math.sqrt(0.6 * 0.4 + 0.5 * 0.5)) ** 2 / 0.01
check.near('two proportions: n per group by the pooled-z formula (387.3)', r['values']['n'], n_fleiss, rel=1e-3)
r = P(situation='two_props', p1=0.6, p2=0.5, n=300, n2=450)
check.near('two proportions: power (power_proportions_2indep)', r['values']['power'], power_proportions_2indep(0.1, 0.5, 300, ratio=1.5, alpha=0.05).power, rel=1e-10)
r = P(situation='one_var', var0=1, dvar=1, n=20, sides=1)
check.near('one variance: power = P(χ² > χ²₀.₉₅ σ₀²/σ₁²)', r['values']['power'], float(stats.chi2.sf(stats.chi2.ppf(0.95, 19) / 2, 19)), rel=1e-12)
r = P(situation='one_var', var0=1, dvar=-0.5, n=30, sides=1)
check.near('one variance, smaller', r['values']['power'], float(stats.chi2.cdf(stats.chi2.ppf(0.05, 29) * 2, 29)), rel=1e-12)
r = P(situation='one_var', var0=1, dvar=1, power=0.8, sides=1)
n_ = r['rows'][0][1]
check('one variance: the whole n is the first with the power', stats.chi2.sf(stats.chi2.ppf(0.95, n_ - 1) / 2, n_ - 1) >= 0.8 > stats.chi2.sf(stats.chi2.ppf(0.95, n_ - 2) / 2, n_ - 2), True)
r = P(situation='poisson', lam0=2, dlam=0.5, n=50, sides=1)
z = stats.norm.ppf(0.95)
check.near('counts per unit: normal approximation', r['values']['power'], float(stats.norm.sf((2 + z * math.sqrt(2 / 50) - 2.5) / math.sqrt(2.5 / 50))), rel=1e-12)
ex = [row for row in r['rows'] if 'exact' in row[0]][0][1]
c = int(stats.poisson.isf(0.05, 100)) + 1
while stats.poisson.sf(c - 2, 100) <= 0.05:
    c -= 1
check.near('counts per unit: exact Poisson power', ex, float(stats.poisson.sf(c - 1, 125)), rel=1e-12)
r = P(situation='sigma', defects=3.4, opportunities=1e6)
check.near('six sigma is 3.4 defects per million', r['values']['sigma_level'], 6.0, abs_=0.001)
r = P(situation='one_mean', sd=1, diff=0.5)
check('only the difference: a power curve against n', ('n' in r['curves'], r['solved']), (True, None))
check('the curve rises with n', r['curves']['n']['y'][5] < r['curves']['n']['y'][-1], True)
r = P(situation='one_mean', sd=1, n=20)
check('only n: a power curve against the difference, from α', (round(r['curves']['diff']['y'][0], 9), r['curves']['diff']['y'][-1] > 0.9), (0.05, True))
check('bad α', 'error' in P(situation='one_mean', sd=1, diff=1, n=10, alpha=1.5), True)
check('the code runs statsmodels', 'TTestPower' in P(situation='one_mean', sd=1, diff=0.5, n=10)['code'], True)
# the Python code of a result runs and gives the report's numbers
import contextlib  # noqa: E402
import io  # noqa: E402


def run_code(code):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(code, 'code', 'exec'), {})
    return buf.getvalue()


for sit, kw in (('one_mean', dict(sd=1, diff=0.5, n=30)), ('two_means', dict(sd=1, diff=0.5, n=128)), ('k_means', dict(sd=1, means=[0, 0, .5, .5], n=180)),
                ('one_prop', dict(p0=.5, p1=.6, n=200)), ('two_props', dict(p1=.6, p2=.5, n=400)), ('one_var', dict(var0=1, dvar=1, n=20)),
                ('poisson', dict(lam0=2, dlam=.5, n=50)), ('sigma', dict(defects=3.4, opportunities=1e6))):
    r = P(situation=sit, **kw)
    first = float(run_code(r['code']).split()[0])
    want = r['values'].get('power') if sit != 'sigma' else r['values']['sigma_level']
    check.near(f'{sit}: the code prints the report\'s answer', first, want, rel=1e-9)
for m in ('lhs', 'sobol', 'halton', 'uniform', 'maximin'):
    r = call('doe.space_filling', factors=fs3, n_runs=16, method=m, seed=7)
    check.near(f'{m}: the code reproduces the design (its discrepancy)', float(run_code(r['code']).split()[-1]), r['discrepancy'], rel=1e-12)
for k in (3, 5, 8):
    r = call('doe.rsm', factors=[cf(f'X{i}') for i in range(k)], design='ccd:rotatable')
    check(f'the CCD code for {k} factors makes the runs', run_code(r['code']).strip(), f'({r["n_runs"]}, {k})')
for k in (4, 6, 7):
    r = call('doe.rsm', factors=[cf(f'X{i}') for i in range(k)], design='bbd')
    check(f'the Box-Behnken code for {k} factors makes the runs', run_code(r['code']).strip(), f'({r["n_runs"]}, {k})')
for d in ('ff:16', 'pb:12', 'full'):
    r = call('doe.screening', factors=[cf(f'X{i}') for i in range(6 if d != 'full' else 4)], design=d)
    check(f'the {d} screening code shows orthogonal columns', run_code(r['code']).strip().startswith('[['), True)
run_code(call('doe.full_factorial', factors=fs, seed=3)['code'])
check('the full factorial code runs', True, True)

# ---------------------------------------------------------------------------
# The graphs' matplotlib code (and the Design Diagnostics' code), run on the whole table's CSV
import os  # noqa: E402
import tempfile  # noqa: E402
import warnings  # noqa: E402

import pandas as pd  # noqa: E402

from test_charts import run_snippet  # noqa: E402

work = tempfile.mkdtemp(prefix='smui-doe-')


def md(a, b):
    a, b = np.asarray(a, float).ravel(), np.asarray(b, float).ravel()
    return float(np.max(np.abs(a - b))) if a.shape == b.shape and a.size else float('inf')


def figure(label, code, frame):
    figs, err = run_snippet(code, frame, 'data', work)
    check(f'{label}: the code runs', err, None)
    check(f'{label}: it ends with plt.show()', code.rstrip().split('\n')[-1], 'plt.show()')
    check(f'{label}: one figure', len(figs or []), 1)
    return figs[0] if figs else None


def code_vars(code, frame, label):
    frame.to_csv(os.path.join(work, 'data.csv'), index=False)
    ns, here = {}, os.getcwd()
    os.chdir(work)
    try:
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter('ignore')
            exec(compile(code, label, 'exec'), ns)
    except Exception as ex:   # the check below reports it
        ns['__error__'] = f'{type(ex).__name__}: {ex}'
    finally:
        os.chdir(here)
    check(f'{label}: the code runs', ns.get('__error__'), None)
    return ns


def evaluate_checks(tag, e, frame, factors):
    dg = {row[0]: row[1] for row in e['diagnostics']}
    ns = code_vars(e['code'], frame, f'{tag}: the Design Diagnostics\' code')
    if 'V' in ns:
        check.near(f'{tag}: its variances are the report\'s', md(np.diag(ns['V']), [r_['variance'] for r_ in e['variance']['rows']]), 0.0, abs_=1e-12)
        check.near(f'{tag}: its powers', md(ns['power'], [r_['power'] if r_['power'] is not None else np.nan for r_ in e['power']['rows']]), 0.0, abs_=1e-12)
        check.near(f'{tag}: its D, G and A efficiencies', md([ns['d_efficiency'], ns['g_efficiency'], ns['a_efficiency']], [dg['D Efficiency'], dg['G Efficiency'], dg['A Efficiency']]), 0.0, abs_=1e-9)
        check.near(f'{tag}: its average and largest prediction variance', md([ns['pv'].mean(), ns['pmax']], [dg['Average Variance of Prediction'], dg['Maximum Relative Prediction Variance']]), 0.0, abs_=1e-12)
    top = 1.08 * max(max(p['variance']) for p in e['profile'])
    for p, code in zip(e['profile'], e['plot_code']['profile']):
        F = figure(f'{tag}: prediction variance of {p["factor"]}', code, frame)
        if not F:
            continue
        ax = F['axes'][0]
        ln = ax['lines'][0] if ax['lines'] else {'x': [], 'y': []}
        xs = p['x'] if p['kind'] == 'continuous' else list(range(len(p['x'])))
        check.near(f'{tag}: prediction variance of {p["factor"]}: the curve is the report\'s', max(md(ln['x'], xs), md(ln['y'], p['variance'])), 0.0, abs_=1e-12)
        check.near(f'{tag}: prediction variance of {p["factor"]}: the scale every factor shares', ax['ylim'][1], top, abs_=1e-12)
        if p['kind'] != 'continuous':
            check(f'{tag}: prediction variance of {p["factor"]}: its levels, as markers', ([t for t in ax['xticklabels'] if t], ln['marker']), (p['x'], 'o'))
        check(f'{tag}: prediction variance of {p["factor"]}: the titles and the size', (ax['xlabel'], ax['ylabel'], ax['title'], F['size']), (p['factor'], 'Variance', f'Prediction variance {p["factor"]}', [2.0, 2.0]))
    F = figure(f'{tag}: fraction of design space', e['plot_code']['fds'], frame)
    if F:
        ax = F['axes'][0]
        ln = ax['lines'][0] if ax['lines'] else {'x': [], 'y': []}
        check.near(f'{tag}: fraction of design space: the curve is the report\'s (the same sample)', max(md(ln['x'], e['fds']['fraction']), md(ln['y'], e['fds']['variance'])), 0.0, abs_=1e-12)
        check(f'{tag}: fraction of design space: the axes, the titles and the size', (ax['xlim'], ax['ylim'][0], ax['xlabel'], ax['ylabel'], ax['title'], F['size']),
              ([0.0, 1.0], 0.0, 'Fraction of Space', 'Prediction Variance', 'Fraction of design space', [3.8, 2.6]))
    F = figure(f'{tag}: color map on correlations', e['plot_code']['colormap'], frame)
    if F:
        ax = F['axes'][0]
        C = e['correlation']
        k = len(C['names'])
        img = ax['images'][0] if ax['images'] else {'shape': [], 'data': []}
        check.near(f'{tag}: color map: the absolute correlations of the terms and the alias terms', md(img['data'], np.abs(np.asarray(C['matrix'], float))) if img['shape'] == [k, k] else 1e9, 0.0, abs_=1e-12)
        check(f'{tag}: color map: the names on both axes', ([t for t in ax['xticklabels'] if t], [t for t in ax['yticklabels'] if t]), (C['names'], C['names']))
        vl = [ln['x'][0] for ln in ax['lines'] if len(ln['x']) == 2 and ln['x'][0] == ln['x'][1]]
        check(f'{tag}: color map: the dotted line before the alias terms', vl, [C['n_model'] - 0.5] if C['n_model'] < k else [])
        check(f'{tag}: color map: the colour bar, the title and the size', (F['axes'][1]['ylabel'] if len(F['axes']) > 1 else None, ax['title'], F['size']),
              ('|r|', 'Color map on correlations', [max(320, min(720, 140 + 26 * k)) / 100, max(300, min(720, 120 + 26 * k)) / 100]))


# a full factorial with a categorical factor and center points; one continuous factor coded in its notes, one by the data's range
ffd = call('doe.full_factorial', factors=[cf('Temp', 150, 200), cf('Time', 10, 20), {'name': 'Cat', 'kind': 'categorical', 'levels': ['a', 'b', 'c']}], center_points=3, seed=5)
cols_d = {c['name']: c['values'] for c in ffd['columns'] if c['name'] != 'Y'}
nd = len(cols_d['Temp'])
cols_d['blk'] = ['u' if i % 4 else 'v' for i in range(nd)]
t_d = table(cols_d, levels={'Cat': ['a', 'b', 'c']})
frame_d = pd.DataFrame(cols_d)
kept_d = [i for i in range(nd) if i not in (4, 9)]
e = call('doe.evaluate', table=t_d, factors=['Temp', 'Time', 'Cat'], model='2fi', coding={'Temp': [150, 200]}, rows=kept_d, table_name='data')
check('Evaluate Design with rows left out: the code drops them', 'df = df.drop(index=[4, 9])   # the rows the report leaves out' in e['code'], True)
evaluate_checks('Evaluate Design (2FI, rows left out)', e, frame_d, ['Temp', 'Time', 'Cat'])
grp_d = [i for i in range(nd) if cols_d['blk'][i] == 'u' and i != 9]
e = call('doe.evaluate', table=t_d, factors=['Temp', 'Time', 'Cat'], model='main', rows=grp_d, where=[{'column': 'blk', 'value': 'u'}], alpha=0.1, rmse=2, coefficient=1.5, table_name='data')
check('Evaluate Design in a By group: the code keeps the group, drops the row left out', ('df = df[df["blk"] == "u"]' in e['code'], 'df = df.drop(index=[9])' in e['code']), (True, True))
evaluate_checks('Evaluate Design (main effects, a By group, power settings)', e, frame_d, ['Temp', 'Time', 'Cat'])
# a By level with a line break (a table from a file is hostile input): the comment stays one line
cols_h = {**cols_d, 'blk': ['u\nimport os; os.system("x")' if b == 'u' else b for b in cols_d['blk']]}
t_h = table(cols_h, levels={'Cat': ['a', 'b', 'c']})
e = call('doe.evaluate', table=t_h, factors=['Temp', 'Time', 'Cat'], model='main', rows=grp_d, where=[{'column': 'blk', 'value': cols_h['blk'][0] if cols_h['blk'][0] != 'v' else cols_h['blk'][1]}], table_name='data')
by_line = [ln for ln in e['code'].split('\n') if 'only the rows where' in ln]
check('Evaluate Design: a By level with a line break stays in its string and its one-line comment',
      (len(by_line), any(ln.lstrip().startswith('import os') for ln in e['code'].split('\n')), by_line[0].endswith('is u import os; os.system("x")') if by_line else None), (1, False, True))
# a rotatable CCD with a numeric nominal factor (levels 1 and 2), the response surface model
ccd2 = call('doe.rsm', factors=[cf('A'), cf('B')], design='ccd:rotatable', order='keep', replicates=1)
cols_c = {c['name']: c['values'] for c in ccd2['columns'] if c['name'] in ('A', 'B')}
cols_c['G'] = [1.0] * 8 + [2.0] * 8 + [float(1 + i % 2) for i in range(len(cols_c['A']) - 16)]   # the second copy of the design at the other level
t_c = table(cols_c, types={'G': 'nominal'})
e = call('doe.evaluate', table=t_c, factors=['A', 'B', 'G'], model='rsm', coding={'A': [-1, 1], 'B': [-1, 1]}, table_name='data')
check('RSM with a numeric categorical factor: its levels as text', e['factors'][2]['levels'], ['1', '2'])
evaluate_checks('Evaluate Design (RSM, a numeric categorical factor)', e, pd.DataFrame(cols_c), ['A', 'B', 'G'])

# Sample Size and Power: each situation, with each field computed, and its two curves
cases = [('one_mean', dict(sd=2, diff=1, power=0.8)), ('one_mean', dict(sd=1, diff=0.5, n=34)), ('one_mean', dict(sd=1, n=34, power=0.8)),
         ('one_mean', dict(sd=1, diff=-0.4, n=40, sides=1)), ('one_mean', dict(sd=1, diff=0.5, n=30, extra=2)), ('one_mean', dict(sd=1, diff=0.5)),
         ('two_means', dict(sd=1, diff=0.5, power=0.8)), ('two_means', dict(sd=1, diff=0.5, n=100, ratio=1.5)), ('two_means', dict(sd=1.5, n=80, power=0.9)),
         ('k_means', dict(sd=1, means=[0, 0, 0.5, 0.5], power=0.8)), ('k_means', dict(sd=1, means=[10, 11, 12], n=30, extra=1)),
         ('one_prop', dict(p0=0.5, p1=0.6, power=0.8)), ('one_prop', dict(p0=0.5, p1=0.4, n=120, sides=1)), ('one_prop', dict(p0=0.3, n=80, power=0.8)),
         ('two_props', dict(p1=0.6, p2=0.5, power=0.8)), ('two_props', dict(p1=0.6, p2=0.5, n=300, n2=450)), ('two_props', dict(p2=0.5, n=200, power=0.8)),
         ('two_props', dict(p1=0.35, p2=0.5, n=150, sides=1)),
         ('two_props', dict(p1=0.65, p2=0.5, n=200, null_diff=0.05, sides=1)), ('two_props', dict(p1=0.65, p2=0.5, power=0.8, null_diff=0.05)),
         ('two_props', dict(p2=0.5, n=200, power=0.8, null_diff=0.05, sides=1)), ('two_props', dict(p1=0.35, p2=0.5, n=150, n2=225, null_diff=-0.05)),
         ('one_var', dict(var0=1, dvar=1, n=20, sides=1)), ('one_var', dict(var0=1, dvar=-0.5, n=30, sides=1)), ('one_var', dict(var0=2, dvar=1, power=0.8)),
         ('one_var', dict(var0=1, n=25, power=0.8, sides=1)),
         ('poisson', dict(lam0=2, dlam=0.5, n=50, sides=1)), ('poisson', dict(lam0=2, dlam=0.5, power=0.8)), ('poisson', dict(lam0=3, n=40, power=0.9))]
EFFECT = {'one_mean': 'diff', 'two_means': 'diff', 'one_prop': 'p1', 'two_props': 'p1', 'one_var': 'dvar', 'poisson': 'dlam'}
blank = pd.DataFrame({'x': [0.0]})
for sit, kw in cases:
    r = P(situation=sit, **kw)
    tag = f'Sample Size and Power, {sit} {", ".join(f"{k}={v}" for k, v in kw.items())}'
    check(f'{tag}: a block for each curve', sorted((r.get('plot_code') or {}).keys()), sorted(r['curves'].keys()))
    for key, c in r['curves'].items():
        code = r['plot_code'][key]
        check(f'{tag}, {key} curve: no table to read', 'read_csv' in code, False)
        F = figure(f'{tag}, {key} curve', code, blank)
        if not F:
            continue
        ax = F['axes'][0]
        main = [ln for ln in ax['lines'] if ln['label'] in ('Power', 'Normal approximation')]
        check.near(f'{tag}, {key} curve: the power along the report\'s grid', max(md(main[0]['x'], c['x']), md(main[0]['y'], [np.nan if v is None else v for v in c['y']])) if main else 1e9, 0.0, abs_=1e-9)
        ex = [ln for ln in ax['lines'] if ln['label'] == 'Exact']
        if c.get('y_exact') is not None:
            check.near(f'{tag}, {key} curve: the exact power', md(ex[0]['y'], c['y_exact']) if ex else 1e9, 0.0, abs_=1e-12)
            check(f'{tag}, {key} curve: the exact power in steps along n, the legend under the graph', (ex[0]['drawstyle'] if ex else None, F['legend'][:2]),
                  ('steps-post' if key == 'n' else 'default', ['Normal approximation', 'Exact']))
        else:
            check(f'{tag}, {key} curve: one curve, no legend', (len(ex), F['legend']), (0, []))
        here = [ln for ln in ax['lines'] if ln['label'] == 'Here']
        ekey = 'n' if key == 'n' else EFFECT.get(sit)
        want_at = (r['values'].get(ekey), r['values'].get('power'))
        if all(v is not None and np.isfinite(v) for v in want_at):
            check.near(f'{tag}, {key} curve: the report\'s point', md(here[0]['x'] + here[0]['y'], list(want_at)) if here else 1e9, 0.0, abs_=1e-7)
        else:
            check(f'{tag}, {key} curve: no point without a value', here, [])
        level = [ln for ln in ax['lines'] if ln['ls'] == ':']
        check.near(f'{tag}, {key} curve: the line at α', level[0]['y'][0] if level else None, r['alpha'], abs_=1e-15)
        check(f'{tag}, {key} curve: the axes, the titles and the size', (ax['ylim'], ax['xlabel'], ax['ylabel'], ax['title'], F['size']),
              ([0.0, 1.02], c['label'], 'Power', f'Power vs {c["label"]}', [3.8, 3.0 if c.get('y_exact') is not None else 2.7]))

# ---- Two Sample Proportions with a margin (a Null Difference δ0 other than 0): the normal approximation with
# unpooled variances (Chow, Shao and Wang, Sample Size Calculations in Clinical Research), worked here by hand;
# with δ0 = 0 the pooled z test of statsmodels, as before
def by_hand_power(p1, p2, n1, n2, d0, alpha, two):
    z = abs(p1 - p2 - d0) / math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return stats.norm.cdf(z - stats.norm.ppf(1 - alpha / 2 if two else 1 - alpha))


def by_hand_n(p1, p2, d0, alpha, power, two, r=1.0):
    c = stats.norm.ppf(1 - alpha / 2 if two else 1 - alpha)
    return (c + stats.norm.ppf(power)) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2) / r) / (p1 - p2 - d0) ** 2


for kw, n2_, two in ((dict(p1=0.65, p2=0.5, n=200, null_diff=0.05, sides=1), 200, False), (dict(p1=0.65, p2=0.5, n=200, null_diff=0.05), 200, True),
                     (dict(p1=0.35, p2=0.5, n=150, n2=225, null_diff=-0.05, sides=1), 225, False), (dict(p1=0.58, p2=0.5, n=400, null_diff=-0.1, alpha=0.1), 400, True)):
    r = P(situation='two_props', **kw)
    want = by_hand_power(kw['p1'], kw['p2'], kw['n'], n2_, kw['null_diff'], kw.get('alpha', 0.05), two)
    check.near(f'two proportions with a margin {kw}: the power, worked by hand', r['values']['power'], float(want), rel=1e-12)
    check(f'... the note names the method ({kw})', ('Chow, Shao and Wang' in r['notes'][0], 'unpooled' in r['notes'][0], 'two-sided' in r['notes'][0]), (True, True, two))
    o = run_code(r['code']).split()
    check.near(f'... its code prints that power ({kw})', float(o[0]), r['values']['power'], rel=1e-12)
    check.near(f'... and gives back the sample size from it ({kw})', float(o[1]), kw['n'], rel=1e-9)
for kw, two in ((dict(p1=0.65, p2=0.5, power=0.8, null_diff=0.05, sides=1), False), (dict(p1=0.65, p2=0.5, power=0.9, null_diff=0.05), True),
                (dict(p1=0.85, p2=0.65, power=0.8, null_diff=-0.1, sides=1), False), (dict(p1=0.3, p2=0.5, power=0.8, null_diff=-0.1), True)):
    r = P(situation='two_props', **kw)
    want = by_hand_n(kw['p1'], kw['p2'], kw['null_diff'], 0.05, kw['power'], two)
    check.near(f'two proportions with a margin {kw}: the sample size, worked by hand', r['values']['n'], float(want), rel=1e-12)
    check.near(f'... it has the power', float(by_hand_power(kw['p1'], kw['p2'], r['values']['n'], r['values']['n'], kw['null_diff'], 0.05, two)), kw['power'], rel=1e-12)
    whole = next(row for row in r['rows'] if row[0].startswith('Whole sample size'))[1]
    check(f'... the whole sample size is the first with the power ({kw})',
          (by_hand_power(kw['p1'], kw['p2'], whole, whole, kw['null_diff'], 0.05, two) >= kw['power'], by_hand_power(kw['p1'], kw['p2'], whole - 1, whole - 1, kw['null_diff'], 0.05, two) < kw['power']), (True, True))
    o = run_code(r['code']).split()
    check.near(f'... its code prints the power at that size and the size ({kw})', max(abs(float(o[0]) - kw['power']), abs(float(o[1]) - r['values']['n']) / r['values']['n']), 0.0, abs_=1e-12)
check.near('the example of 0.85 against 0.65 with the margin −0.1, one-sided: n = (z(0.95) + z(0.8))² (0.85·0.15 + 0.65·0.35) / 0.3²',
           P(situation='two_props', p1=0.85, p2=0.65, power=0.8, null_diff=-0.1, sides=1)['values']['n'], (stats.norm.ppf(0.95) + stats.norm.ppf(0.8)) ** 2 * (0.85 * 0.15 + 0.65 * 0.35) / 0.3 ** 2, rel=1e-12)
r = P(situation='two_props', p2=0.5, n=200, power=0.8, null_diff=0.05, sides=1)
check('with a margin, Proportion 1 from the sample size and the power: above p2 + δ0, with the power',
      (r['solved'], r['values']['p1'] > 0.55, abs(by_hand_power(r['values']['p1'], 0.5, 200, 200, 0.05, 0.05, False) - 0.8) < 1e-9), ('p1', True, True))
r = P(situation='two_props', p1=0.55, p2=0.5, power=0.8, null_diff=0.05)
check('with a margin: no sample size when p1 − p2 is the margin itself (and no error)', (r.get('error'), r['values']['n']), (None, None))
# δ0 = 0: statsmodels' pooled test, unchanged
r = P(situation='two_props', p1=0.6, p2=0.5, n=300, n2=450)
check.near('δ0 = 0: the pooled test\'s power (power_proportions_2indep), unchanged', r['values']['power'], power_proportions_2indep(0.1, 0.5, 300, ratio=1.5, alpha=0.05).power, rel=1e-12)
check('δ0 = 0: the note and the code are the pooled test\'s', ('pooled variance' in r['notes'][0], 'power_proportions_2indep(' in r['code'], 'Chow' in r['code']), (True, True, False))
check('δ0 = 0: the graphs\' code too', all('power_proportions_2indep(' in c and 'unpooled' not in c for c in r['plot_code'].values()), True)
r = P(situation='two_props', p1=0.6, p2=0.5, power=0.8)
check.near('δ0 = 0: the sample size, unchanged (387.3 per group)', r['values']['n'], n_fleiss, rel=1e-3)
r = P(situation='two_props', p1=0.65, p2=0.5, power=0.8, null_diff=0.05)
check('with a margin: the graphs\' code is the formula\'s, the sample size solved from it', (all('unpooled' in c and 'power_proportions_2indep' not in c for c in r['plot_code'].values()),
      all('max(2.0, zsum ** 2' in c for c in r['plot_code'].values())), (True, True))

# ---------------------------------------------------------------------------
# Split plots (factors that are hard to change) and replicates as blocks: the designs by their
# defining properties, the design's model, its exact tests by Fit Model's REML (Kenward-Roger), and
# Simulate Responses' formula
import pandas as pd  # noqa: E402
import statsmodels.api as sm  # noqa: E402
import statsmodels.formula.api as smf  # noqa: E402

hard = lambda f: {**f, 'changes': 'hard'}
spf = [hard(cf('A', 10, 20)), hard(cf('B')), cf('C'), {'name': 'D', 'kind': 'categorical', 'levels': ['p', 'q', 'r']}]
sp = call('doe.full_factorial', factors=spf, responses=[{'name': 'Y'}], seed=5)
spc = {c['name']: c['values'] for c in sp['columns']}
check('split plot: the columns (a Whole Plots column after the factors)', [c['name'] for c in sp['columns']], ['Pattern', 'A', 'B', 'C', 'D', 'Whole Plots', 'Y'])
check('split plot: Whole Plots is nominal', [c['modelingType'] for c in sp['columns'] if c['name'] == 'Whole Plots'], ['nominal'])
check('split plot: the default whole plots, each of the 4 hard-to-change settings twice; 6 runs in each', (sp['whole_plots'], sp['n_runs']), (8, 48))
wpl = spc['Whole Plots']
runs_of = {w: [i for i, x in enumerate(wpl) if x == w] for w in dict.fromkeys(wpl)}
check('split plot: the whole plots are numbered 1 to 8 in run order', list(runs_of), [str(i) for i in range(1, 9)])
check('split plot: each whole plot\'s runs are together (a restricted randomization)', all(v == list(range(v[0], v[0] + len(v))) for v in runs_of.values()), True)
check('split plot: A and B are constant in each whole plot', all(len({(spc['A'][i], spc['B'][i]) for i in v}) == 1 for v in runs_of.values()), True)
check('split plot: every combination of C and D once in each whole plot', all(sorted((spc['C'][i], spc['D'][i]) for i in v) == sorted(itertools.product([-1.0, 1.0], 'pqr')) for v in runs_of.values()), True)
check('split plot: each setting of A and B in two whole plots', sorted(Counter((spc['A'][v[0]], spc['B'][v[0]]) for v in runs_of.values()).values()), [2, 2, 2, 2])
std = call('doe.full_factorial', factors=spf, seed=5, order='keep')
stdc = {c['name']: c['values'] for c in std['columns']}
check('split plot, standard order: the whole plots cycle through the settings, the runs in order', ([(stdc['A'][6 * k], stdc['B'][6 * k]) for k in range(8)], [(stdc['C'][i], stdc['D'][i]) for i in range(6)]),
      ([(10.0, -1.0), (10.0, 1.0), (20.0, -1.0), (20.0, 1.0)] * 2, list(itertools.product([-1.0, 1.0], 'pqr'))))
check('split plot, randomized: not the standard order', [(spc['A'][6 * k], spc['B'][6 * k]) for k in range(8)] != [(stdc['A'][6 * k], stdc['B'][6 * k]) for k in range(8)]
      or [(spc['C'][i], spc['D'][i]) for i in range(6)] != [(stdc['C'][i], stdc['D'][i]) for i in range(6)], True)
sp2 = call('doe.full_factorial', factors=spf, seed=5)
check('split plot: the same seed, the same design', [c['values'] for c in sp2['columns']], [c['values'] for c in sp['columns']])
sp12 = call('doe.full_factorial', factors=spf, seed=5, whole_plots=12)
check('split plot: 12 whole plots, each setting in 3', (sp12['n_runs'], sorted(Counter(zip(*[[v for i, v in enumerate(c['values']) if i % 6 == 0] for c in sp12['columns'] if c['name'] in ('A', 'B')])).values())), (72, [3, 3, 3, 3]))
check('split plot: the default follows the replicates (one whole plot per setting and copy)', call('doe.full_factorial', factors=spf, seed=5, replicates=2)['whole_plots'], 12)


def refused(fn, **kw):
    """The message a refused call raises (as the page shows it), or None."""
    try:
        call(fn, **kw)
    except Exception as e:  # the page shows the message
        return str(e)
    return None


for bad, want in ((dict(whole_plots=6), 'multiple of 4'), (dict(factors=[hard(cf('A')), hard(cf('B'))]), 'easy to change')):
    check(f'split plot: refused ({want})', want in (refused('doe.full_factorial', **{'factors': spf, 'seed': 5, **bad}) or ''), True)
one = call('doe.full_factorial', factors=spf, seed=5, whole_plots=4)
check('split plot with one whole plot per setting: a note, and no Whole Plots term in the model',
      ('cannot be told from' in one['notes'], [e['names'] for e in one['model']['effects'] if e['random']]), (True, []))
check('split plot: center points are not added', ('not added to a split-plot' in call('doe.full_factorial', factors=spf, seed=5, center_points=2)['notes'], call('doe.full_factorial', factors=spf, seed=5, center_points=2)['n_runs']), (True, 48))
code_ns = {}
with contextlib.redirect_stdout(io.StringIO()):
    exec(compile(sp['code'], 'code', 'exec'), code_ns)
dcode = code_ns['d']
check('split plot: the code makes the same design, run for run', [dcode['Whole Plots'].tolist()] + [dcode[c].tolist() for c in 'ABCD'], [wpl] + [spc[c] for c in 'ABCD'])

# the design's model: the full factorial (it leaves 20 error df within whole plots), Whole Plots random
eff = sp['model']['effects']
check('the model: Y, the full factorial of A, B, C, D (15 terms), Whole Plots random',
      (sp['model']['roles'], len([e for e in eff if not e['random']]), [e['names'] for e in eff if e['random']], sp['model']['options']['personality']),
      ({'y': ['Y']}, 15, [['Whole Plots']], 'standard'))
check('the model: its terms by degree, as Fit Model\'s Full Factorial macro lists them', [e['names'] for e in eff[:6]], [['A'], ['B'], ['C'], ['D'], ['A', 'B'], ['A', 'C']])
# a response from the model: whole-plot and run errors; REML with the design's model
rng = np.random.default_rng(2024)
d = pd.DataFrame({k: spc[k] for k in ('A', 'B', 'C', 'D', 'Whole Plots')})
xa, xb = (d['A'] - 15) / 5, d['B']
wpe = dict(zip([str(i) for i in range(1, 9)], rng.normal(0, 1.5, 8)))
d['Y'] = 50 + 2 * xa - 1.5 * xb + 0.8 * d['C'] + d['D'].map({'p': 1.0, 'q': -0.5, 'r': -0.5}) + d['Whole Plots'].map(wpe) + rng.normal(0, 1, len(d))
tsp = table({k: d[k].tolist() for k in d.columns})
fit = call('fitmodel.mixed', table=tsp, y='Y', effects=[{'names': e['names'], 'random': e['random']} for e in eff])
check('the design\'s model fits (REML)', fit.get('error'), None)
tests = {t['source']: t for t in fit.get('tests', [])}
# the exact tests: the whole-plot terms on the whole plots' mean square (W - H = 4 df), the others on the error within
full = 'A * B * Cx * C(D, Sum)'   # (a column C would hide patsy's C())
do = d.rename(columns={'C': 'Cx', 'Whole Plots': 'WP'})
ols = smf.ols(f'Y ~ {full}', do).fit()
an = sm.stats.anova_lm(ols, typ=1)
olsw = smf.ols(f'Y ~ {full} + C(WP)', do).fit()
mse_sub, df_sub = float(olsw.ssr / olsw.df_resid), float(olsw.df_resid)
ms_wp, df_wp = float((ols.ssr - olsw.ssr) / (ols.df_resid - olsw.df_resid)), float(ols.df_resid - olsw.df_resid)
check('the within-whole-plot error has 20 df and the whole plots 4', (df_sub, df_wp), (20.0, 4.0))
for term, src, ms, dfd in (('A', 'A', ms_wp, df_wp), ('B', 'B', ms_wp, df_wp), ('A:B', 'A*B', ms_wp, df_wp), ('Cx', 'C', mse_sub, df_sub),
                           ('C(D, Sum)', 'D', mse_sub, df_sub), ('A:Cx', 'A*C', mse_sub, df_sub), ('B:C(D, Sum)', 'B*D', mse_sub, df_sub)):
    ms_t = float(an['mean_sq'][term])
    got = tests.get(src, {})
    check.near(f'the design\'s model: F of {src} = its exact test\'s (on the {"whole plots" if dfd == df_wp else "error within them"})', got.get('f'), ms_t / ms, rel=1e-6)
    check.near(f'the design\'s model: DFDen of {src} (Kenward-Roger) = {dfd:g}', got.get('dfden'), dfd, rel=1e-6)
vc = {v['effect']: v for v in fit.get('varcomp', [])}
check.near('the design\'s model: the Whole Plots variance = (MS whole plots - MSE) / 6', vc.get('Whole Plots', {}).get('var'), (ms_wp - mse_sub) / 6, rel=1e-6)

# replicates as blocks
bl = call('doe.full_factorial', factors=[cf('A'), cf('B'), {'name': 'C', 'kind': 'categorical', 'levels': ['x', 'y']}], replicates=2, center_points=2, blocks=True, seed=3)
blc = {c['name']: c['values'] for c in bl['columns']}
check('blocks: 3 blocks of 8 combinations and 2 center points', (bl['n_runs'], [c['name'] for c in bl['columns']], Counter(blc['Block'])), (30, ['Pattern', 'A', 'B', 'C', 'Block', 'Y'], {'1': 10, '2': 10, '3': 10}))
check('blocks: each block a complete replicate with its center points, its runs together',
      all(sorted(zip(blc['A'][10 * b:10 * b + 10], blc['B'][10 * b:10 * b + 10], blc['C'][10 * b:10 * b + 10])) == sorted(list(itertools.product([-1.0, 1.0], [-1.0, 1.0], 'xy')) + [(0.0, 0.0, 'x'), (0.0, 0.0, 'y')])
          and set(blc['Block'][10 * b:10 * b + 10]) == {str(b + 1)} for b in range(3)), True)
check('blocks: the model has Block as a random effect', [e['names'] for e in bl['model']['effects'] if e['random']], [['Block']])
bns = {}
with contextlib.redirect_stdout(io.StringIO()):
    exec(compile(bl['code'], 'code', 'exec'), bns)
check('blocks: the code makes the same design', [bns['d'][c].tolist() for c in ('A', 'B', 'C', 'Block')], [blc[c] for c in ('A', 'B', 'C', 'Block')])
check('no replicates: Replicates as Blocks makes no Block column', 'Block' in [c['name'] for c in call('doe.full_factorial', factors=[cf('A'), cf('B')], blocks=True, seed=3)['columns']], False)
ff0 = call('doe.full_factorial', factors=[cf('A'), cf('B'), cf('C')], seed=3)
check('the plain full factorial\'s model: no error df for the full factorial, so the main effects and two-factor interactions',
      ([e['names'] for e in ff0['model']['effects']], ff0['random']), ([['A'], ['B'], ['C'], ['A', 'B'], ['A', 'C'], ['B', 'C']], []))

# Simulate Responses: the coefficients asked for, and the formula
sim = sp['simulate']
check('Simulate Responses: a coefficient per term and level, labelled as the estimates',
      [lab for t in sim['terms'][:8] for lab in t['labels']], ['A', 'B', 'C', 'D[p]', 'D[q]', 'A*B', 'A*C', 'A*D[p]', 'A*D[q]', 'B*C'])
check('Simulate Responses: 1 for a main effect, 0 for an interaction; the σ\'s 1', ([x for t in sim['terms'][:5] for x in t['defaults']], sim['sigmas']), ([1.0, 1.0, 1.0, 1.0, 1.0, 0.0], {'Whole Plots': 1.0, 'Error': 1.0}))
coefs = [[0.0] * len(t['labels']) for t in sim['terms']]
coefs[0] = [2.0]
coefs[1] = [-1.5]
coefs[3] = [1.0, -0.5]
coefs[5] = [0.25]
f = call('doe.simulate_formula', factors=spf, terms=[t['names'] for t in sim['terms']], coefficients=coefs, intercept=50, sigmas={'Whole Plots': 1.5, 'Error': 1})
check('Simulate Responses: the formula',
      f.get('expr'), '50 + 2 * ((:A - 15) / 5) - 1.5 * :B + Match(:D, "p", 1, "r", -1, 0) - 0.5 * Match(:D, "q", 1, "r", -1, 0) + 0.25 * ((:A - 15) / 5) * :C'
      ' + 1.5 * Col Mean(Random Normal(), :"Whole Plots") * Sqrt(Col Number(:"Whole Plots", :"Whole Plots")) + Random Normal(0, 1)')
check('Simulate Responses: no draws with σ 0, and a level with a quote in its name', call('doe.simulate_formula', factors=[{'name': 'x y', 'kind': 'categorical', 'levels': ['a"b', 'c']}], terms=[['x y']], coefficients=[[3]], sigmas={'Error': 0})['expr'],
      '3 * Match(:"x y", "a\\"b", 1, "c", -1, 0)')
check('Simulate Responses: the wrong number of coefficients is refused', 'coefficient' in (refused('doe.simulate_formula', factors=spf, terms=[['D']], coefficients=[[1]]) or ''), True)
check('Simulate Responses: a negative σ is refused', 'σ' in (refused('doe.simulate_formula', factors=spf, terms=[['A']], coefficients=[[1]], sigmas={'Error': -1}) or ''), True)
sys.exit(check.done())
