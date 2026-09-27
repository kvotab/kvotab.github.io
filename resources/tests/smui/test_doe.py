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
z test; six sigma is 3.4 defects per million).

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
sys.exit(check.done())
