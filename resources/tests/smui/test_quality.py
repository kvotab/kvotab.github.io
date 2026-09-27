#!/usr/bin/env python3
"""Analyze > Quality and Process's backend (resources/py/smui/quality.py):
Control Chart Builder, Process Capability, Pareto Plot and the Variability /
Attribute Gauge Chart.

Checked against: the printed factors for control charts (Montgomery,
Introduction to Statistical Quality Control, Appendix VI; d2 and d3 to four
places as in ASTM E2587) and their closed forms; the control-limit formulas
computed here from the data; hand-made sequences for each Western Electric /
Nelson test; the capability formulas (and scipy's noncentral t for the
one-sided intervals); pandas counts and scipy's G test for the Pareto plot;
statsmodels' anova_lm and MixedLM called directly for the variance
components; statsmodels' fleiss_kappa and cohens_kappa for the attribute
gauge. The data are simulated with a fixed seed.

    python3 resources/tests/smui/test_quality.py
"""
import math
import sys

import numpy as np
import pandas as pd
from scipy import integrate, stats

from backend import FAILED, Checks, call, table

check = Checks()
check('quality module imports', FAILED.get('quality'), None)
from smui import quality as Q  # noqa: E402

rng = np.random.default_rng(20260926)

# ---------------------------------------------------------------------------
# The constants, against the printed table. The table's D3 and D4 are made
# from the rounded d2 and d3, so they may differ from the exact values by up
# to one unit in the last place; that is the tolerance.
# n: A2, A3, c4, B3, B4, d2, d3, D3, D4
MONTGOMERY = {
    2: (1.880, 2.659, 0.7979, 0, 3.267, 1.128, 0.853, 0, 3.267),
    3: (1.023, 1.954, 0.8862, 0, 2.568, 1.693, 0.888, 0, 2.574),
    4: (0.729, 1.628, 0.9213, 0, 2.266, 2.059, 0.880, 0, 2.282),
    5: (0.577, 1.427, 0.9400, 0, 2.089, 2.326, 0.864, 0, 2.114),
    6: (0.483, 1.287, 0.9515, 0.030, 1.970, 2.534, 0.848, 0, 2.004),
    7: (0.419, 1.182, 0.9594, 0.118, 1.882, 2.704, 0.833, 0.076, 1.924),
    8: (0.373, 1.099, 0.9650, 0.185, 1.815, 2.847, 0.820, 0.136, 1.864),
    9: (0.337, 1.032, 0.9693, 0.239, 1.761, 2.970, 0.808, 0.184, 1.816),
    10: (0.308, 0.975, 0.9727, 0.284, 1.716, 3.078, 0.797, 0.223, 1.777),
    11: (0.285, 0.927, 0.9754, 0.321, 1.679, 3.173, 0.787, 0.256, 1.744),
    12: (0.266, 0.886, 0.9776, 0.354, 1.646, 3.258, 0.778, 0.283, 1.717),
    13: (0.249, 0.850, 0.9794, 0.382, 1.618, 3.336, 0.770, 0.307, 1.693),
    14: (0.235, 0.817, 0.9810, 0.406, 1.594, 3.407, 0.763, 0.328, 1.672),
    15: (0.223, 0.789, 0.9823, 0.428, 1.572, 3.472, 0.756, 0.347, 1.653),
    16: (0.212, 0.763, 0.9835, 0.448, 1.552, 3.532, 0.750, 0.363, 1.637),
    17: (0.203, 0.739, 0.9845, 0.466, 1.534, 3.588, 0.744, 0.378, 1.622),
    18: (0.194, 0.718, 0.9854, 0.482, 1.518, 3.640, 0.739, 0.391, 1.608),
    19: (0.187, 0.698, 0.9862, 0.497, 1.503, 3.689, 0.734, 0.403, 1.597),
    20: (0.180, 0.680, 0.9869, 0.510, 1.490, 3.735, 0.729, 0.415, 1.585),
    21: (0.173, 0.663, 0.9876, 0.523, 1.477, 3.778, 0.724, 0.425, 1.575),
    22: (0.167, 0.647, 0.9882, 0.534, 1.466, 3.819, 0.720, 0.434, 1.566),
    23: (0.162, 0.633, 0.9887, 0.545, 1.455, 3.858, 0.716, 0.443, 1.557),
    24: (0.157, 0.619, 0.9892, 0.555, 1.445, 3.895, 0.712, 0.451, 1.548),
    25: (0.153, 0.606, 0.9896, 0.565, 1.435, 3.931, 0.708, 0.459, 1.541),
}
KEYS = ('A2', 'A3', 'c4', 'B3', 'B4', 'd2', 'd3', 'D3', 'D4')
worst = {k: 0.0 for k in KEYS}
for n, vals in MONTGOMERY.items():
    f = Q.factors(n)
    for k, v in zip(KEYS, vals):
        worst[k] = max(worst[k], abs(f[k] - v))
for k in KEYS:
    unit = 1e-4 if k == 'c4' else 1e-3
    check(f'{k} for n = 2..25 within one unit of the printed table (worst {worst[k]:.5f})', worst[k] <= unit + 1e-12)
# four places (ASTM E2587)
ASTM = {2: (1.1284, 0.8525), 3: (1.6926, 0.8884), 4: (2.0588, 0.8798), 5: (2.3259, 0.8641), 6: (2.5344, 0.8480), 7: (2.7044, 0.8332),
        8: (2.8472, 0.8198), 9: (2.9700, 0.8078), 10: (3.0775, 0.7971)}
check('d2, d3 to four places for n = 2..10', all(abs(Q.d2(n) - a) <= 1e-4 and abs(Q.d3(n) - b) <= 1e-4 for n, (a, b) in ASTM.items()))
check.near('d2(2) = 2/√π', Q.d2(2), 2 / math.sqrt(math.pi), rel=1e-9)
check.near('d3(2) = √(2 − 4/π)', Q.d3(2), math.sqrt(2 - 4 / math.pi), rel=1e-8)
check.near('d2(3) = 3/√π', Q.d2(3), 3 / math.sqrt(math.pi), rel=1e-9)
check.near('c4(2) = √(2/π)', Q.c4(2), math.sqrt(2 / math.pi), rel=1e-12)
# an independent d2 by scipy's quad
d2_quad = lambda n: integrate.quad(lambda x: 1 - stats.norm.cdf(x) ** n - stats.norm.sf(x) ** n, -np.inf, np.inf)[0]
check('d2 agrees with scipy quad for n = 2..25', max(abs(Q.d2(n) - d2_quad(n)) for n in range(2, 26)) < 1e-9)
check.near('median moving range divisor d4(2)', Q.D4_2, 0.954, abs_=5e-4)
ct = call('quality.constants', n_max=10)
check('constants table rows', len(ct['table']['rows']), 9)

# ---------------------------------------------------------------------------
# XBar & R, XBar & S on 25 subgroups of 5, a shift after subgroup 18
sub = np.repeat(np.arange(1, 26), 5)
x = 10 + (sub > 18) * 0.25 + rng.normal(0, 0.14, 125)
x = np.round(x, 3)
ph = np.where(sub <= 18, 'before', 'after')
tid = table({'subgroup': sub, 'd': x, 'phase': list(ph)}, types={'subgroup': 'ordinal'}, levels={'phase': ['before', 'after']})
g = pd.DataFrame({'s': sub, 'x': x}).groupby('s')['x']
xbar, rng_, sdev = g.mean().to_numpy(), (g.max() - g.min()).to_numpy(), g.std(ddof=1).to_numpy()
xbb, rbar, sbar = float(x.mean()), float(rng_.mean()), float(sdev.mean())

r = call('quality.control_chart', table=tid, y='d', subgroup='subgroup', chart='xbar_r')
xb, rp = r['panels'][0], r['panels'][1]
check('XBar & R: 25 points of 5 rows', (len(r['units']), {u['n'] for u in r['units']}), (25, {5}))
check('each point carries its rows', r['units'][3]['rows'], list(range(15, 20)))
check.near('XBar center is the grand mean', xb['cl'][0], xbb)
check.near('XBar UCL = X̿ + A2·R̄ (A2 = 0.577)', xb['ucl'][0], xbb + 0.577 * rbar, abs_=0.0005 * rbar)
check.near('XBar UCL = X̿ + 3 R̄/(d2 √n) exactly', xb['ucl'][0], xbb + 3 * rbar / (d2_quad(5) * math.sqrt(5)), rel=1e-9)
check.near('R center = R̄', rp['cl'][0], rbar, rel=1e-9)
check.near('R UCL = D4·R̄ (D4 = 2.114)', rp['ucl'][0], 2.114 * rbar, abs_=0.0006 * rbar)
check('R LCL = 0 for n = 5 (D3 = 0)', rp['lcl'][0], 0.0)
check.near('sigma = R̄/d2', r['summary']['sigma'][0]['sigma'], rbar / d2_quad(5), rel=1e-9)
check('the Limit Summaries hold both charts', [row['points'] for row in r['limits']['rows']], ['Mean(d)', 'Range(d)'])
check('the code shows R/d2', 'r / n.map(d2)' in r['code'], True)

r = call('quality.control_chart', table=tid, y='d', subgroup='subgroup', chart='xbar_s')
xb, sp = r['panels'][0], r['panels'][1]
check.near('XBar & S: UCL = X̿ + A3·S̄ (A3 = 1.427)', xb['ucl'][0], xbb + 1.427 * sbar, abs_=0.0005 * sbar)
check.near('S UCL = B4·S̄ (B4 = 2.089)', sp['ucl'][0], 2.089 * sbar, abs_=0.0005 * sbar)
check.near('S center = S̄', sp['cl'][0], sbar, rel=1e-9)

# unequal subgroups: sigma = mean(R_i/d2(n_i)), limits per subgroup
keep = np.ones(125, bool)
keep[[0, 1, 7, 30, 31, 32]] = False
tid2 = table({'subgroup': sub[keep], 'd': x[keep]}, types={'subgroup': 'ordinal'})
gg = pd.DataFrame({'s': sub[keep], 'x': x[keep]}).groupby('s')['x']
nn = gg.size().to_numpy()
sig = float(np.mean((gg.max() - gg.min()).to_numpy() / np.array([d2_quad(k) for k in nn])))
r = call('quality.control_chart', table=tid2, y='d', subgroup='subgroup', chart='xbar_r')
check.near('unequal n: sigma is the mean of R_i/d2(n_i)', r['summary']['sigma'][0]['sigma'], sig, rel=1e-9)
check.near('unequal n: the UCL of a subgroup of 2', r['panels'][0]['ucl'][6], float(x[keep].mean()) + 3 * sig / math.sqrt(2), rel=1e-9)
check('unequal n: the Limit Summaries say the sizes vary', r['limits']['rows'][0]['n'], '2 to 5')

# consecutive subgroups of a given size equal the subgroup column
r2 = call('quality.control_chart', table=tid, y='d', subgroup_size=5, chart='xbar_r')
check.near('a subgroup size of 5 gives the same limits', r2['panels'][0]['ucl'][0], xbb + 3 * rbar / (d2_quad(5) * math.sqrt(5)), rel=1e-9)

# phases: limits of their own
r = call('quality.control_chart', table=tid, y='d', subgroup='subgroup', phase='phase', chart='xbar_r')
first, last = r['panels'][0]['cl'][0], r['panels'][0]['cl'][-1]
check.near('phase 1 center', first, float(x[sub <= 18].mean()))
check.near('phase 2 center', last, float(x[sub > 18].mean()))
check('two phases in the Limit Summaries', [row['phase'] for row in r['limits']['rows']], ['before', 'after', 'before', 'after'])

# ---------------------------------------------------------------------------
# Individuals and moving range
xi = np.round(rng.normal(50, 2, 40), 2)
tid3 = table({'x': xi})
mr = np.abs(np.diff(xi))
r = call('quality.control_chart', table=tid3, y='x', chart='ir')
ip, mp = r['panels']
check.near('I chart: sigma = MR̄/1.128', r['summary']['sigma'][0]['sigma'], mr.mean() / d2_quad(2), rel=1e-9)
check.near('I chart UCL = x̄ + 3 MR̄/d2(2)', ip['ucl'][0], xi.mean() + 3 * mr.mean() / d2_quad(2), rel=1e-9)
check.near('MR chart UCL = 3.267 MR̄', mp['ucl'][1], 3.267 * mr.mean(), abs_=0.0005 * mr.mean())
check('the first moving range is missing', mp['values'][0], None)
r = call('quality.control_chart', table=tid3, y='x', chart='lj')
check.near('Levey Jennings: sigma is the standard deviation', r['summary']['sigma'][0]['sigma'], float(np.std(xi, ddof=1)), rel=1e-12)
r = call('quality.control_chart', table=tid3, y='x', chart='ir', sigma='mmr')
check.near('median moving range', r['summary']['sigma'][0]['sigma'], float(np.median(mr)) / (math.sqrt(2) * stats.norm.ppf(0.75)), rel=1e-12)
# over a span of w rows the divisor is the median range of w normal values
# (the published table: 1.588, 1.978, 2.257, 2.472 for 3 to 6), not 0.954
for w_, v_ in ((3, 1.588), (4, 1.978), (5, 2.257), (6, 2.472)):
    check.near(f'median range of {w_} normal values, d4({w_})', Q.d4(w_), v_, abs_=5e-4)
_rw = np.random.default_rng(7).standard_normal((200000, 3))
check.near('d4(3) is the median of simulated ranges of three', Q.d4(3), float(np.median(np.ptp(_rw, axis=1))), abs_=0.01)
mr3 = np.array([np.ptp(xi[i - 2:i + 1]) for i in range(2, len(xi))])
r = call('quality.control_chart', table=tid3, y='x', chart='ir', sigma='mmr', mr_span=3)
check.near('median moving range over a span of 3: median / d4(3)', r['summary']['sigma'][0]['sigma'], float(np.median(mr3)) / Q.d4(3), rel=1e-12)
r = call('quality.control_chart', table=tid3, y='x', chart='ir', known_mean=50, known_sigma=2)
check('known mean and sigma', (r['panels'][0]['cl'][0], r['panels'][0]['ucl'][0], r['panels'][0]['lcl'][0]), (50.0, 56.0, 44.0))

# ---------------------------------------------------------------------------
# Attribute charts
lots = 20
size = rng.integers(80, 121, lots)
defect = rng.binomial(size, 0.06)
tid4 = table({'lot': np.arange(1, lots + 1), 'bad': defect, 'n': size}, types={'lot': 'ordinal'})
pbar = defect.sum() / size.sum()
r = call('quality.control_chart', table=tid4, y='bad', subgroup='lot', n_trials='n', chart='p')
pp = r['panels'][0]
check.near('P chart: center p̄ = Σd/Σn', pp['cl'][0], pbar, rel=1e-12)
check.near('P chart UCL of lot 1', pp['ucl'][0], pbar + 3 * math.sqrt(pbar * (1 - pbar) / size[0]), rel=1e-12)
check.near('P chart LCL of lot 5', pp['lcl'][4], max(0, pbar - 3 * math.sqrt(pbar * (1 - pbar) / size[4])), rel=1e-12)
check.near('P chart point', pp['values'][2], defect[2] / size[2], rel=1e-12)
r = call('quality.control_chart', table=tid4, y='bad', subgroup='lot', n_trials='n', chart='np')
check.near('NP chart UCL of lot 3', r['panels'][0]['ucl'][2], size[2] * pbar + 3 * math.sqrt(size[2] * pbar * (1 - pbar)), rel=1e-12)
cnt = rng.poisson(4.2, 30)
tid5 = table({'unit': np.arange(1, 31), 'defects': cnt, 'area': rng.uniform(0.8, 1.6, 30).round(2)}, types={'unit': 'ordinal'})
r = call('quality.control_chart', table=tid5, y='defects', subgroup='unit', chart='c')
cbar = cnt.mean()
check.near('C chart UCL = c̄ + 3√c̄', r['panels'][0]['ucl'][0], cbar + 3 * math.sqrt(cbar), rel=1e-12)
check.near('C chart LCL', r['panels'][0]['lcl'][0], max(0.0, cbar - 3 * math.sqrt(cbar)), rel=1e-12)
area = np.array(call('quality.control_chart', table=tid5, y='area', subgroup='unit', chart='run')['panels'][0]['values'])
r = call('quality.control_chart', table=tid5, y='defects', subgroup='unit', n_trials='area', chart='u')
ubar = cnt.sum() / area.sum()
check.near('U chart center ū = Σc/Σn', r['panels'][0]['cl'][0], ubar, rel=1e-12)
check.near('U chart UCL of unit 7', r['panels'][0]['ucl'][6], ubar + 3 * math.sqrt(ubar / area[6]), rel=1e-12)
bad = call('quality.control_chart', table=tid4, y='n', subgroup='lot', n_trials='bad', chart='p')
check('P chart refuses more defects than inspected', 'error' in bad, True)
# a 0/1 column with subgroups: the rows are the units inspected
flag = rng.binomial(1, 0.1, 200)
tid6 = table({'s': np.repeat(np.arange(1, 21), 10), 'defective': flag}, types={'s': 'ordinal'})
r = call('quality.control_chart', table=tid6, y='defective', subgroup='s', chart='p')
check.near('P chart of a 0/1 column: the rows are the sample size', r['panels'][0]['cl'][0], flag.mean(), rel=1e-12)

# ---------------------------------------------------------------------------
# EWMA and CUSUM
lam, L = 0.2, 3.0
r = call('quality.control_chart', table=tid, y='d', subgroup='subgroup', chart='ewma', lam=lam, ewma_l=L)
pn = r['panels'][0]
s_hat = rbar / d2_quad(5)
z, var, zs, ucl = xbb, 0.0, [], []
for m in xbar:
    z = lam * m + (1 - lam) * z
    var = (1 - lam) ** 2 * var + lam ** 2 * s_hat ** 2 / 5
    zs.append(z)
    ucl.append(xbb + L * math.sqrt(var))
check('EWMA statistic', np.allclose(pn['values'], zs, rtol=0, atol=1e-12), True)
check('EWMA limits from the exact variance', np.allclose(pn['ucl'], ucl, rtol=0, atol=1e-12), True)
check.near('EWMA asymptotic UCL in the summary', r['limits']['rows'][0]['ucl'], xbb + L * s_hat * math.sqrt(lam / ((2 - lam) * 5)), rel=1e-12)
rs = call('quality.control_chart', table=tid, y='d', subgroup='subgroup', chart='ewma', lam=lam, ewma_l=L, target=10.0, tests=[1])
alarms = [i for i, t in enumerate(rs['panels'][0]['tests']) if t]
check('EWMA about the target 10 signals the shift after subgroup 18, not before', (bool(alarms), min(alarms) >= 18 if alarms else None), (True, True))
check('EWMA about the target: the center line is the target', rs['panels'][0]['cl'][0], 10.0)
h, k = 4.0, 0.5
r = call('quality.control_chart', table=tid, y='d', subgroup='subgroup', chart='cusum', cusum_h=h, cusum_k=k, target=10.0, tests=[1])
pn = r['panels'][0]
se = s_hat / math.sqrt(5)
cp_, cm_, ups, los = 0.0, 0.0, [], []
for m in xbar:
    zz = (m - 10.0) / se
    cp_ = max(0.0, cp_ + zz - k)
    cm_ = max(0.0, cm_ - zz - k)
    ups.append(cp_ * se)
    los.append(-cm_ * se)
check('CUSUM upper sums', np.allclose(pn['values'], ups, atol=1e-12), True)
check('CUSUM lower sums', np.allclose(pn['lower'], los, atol=1e-12), True)
check.near('CUSUM decision interval H = h·σ/√n', pn['ucl'][0], h * se, rel=1e-12)
first_alarm = next(i for i in range(25) if ups[i] > h * se or -los[i] > h * se)
check('CUSUM alarms where C exceeds H', next(i for i, t in enumerate(pn['tests']) if t), first_alarm)
check('CUSUM in-control ARL (Siegmund, h = 4, k = 0.5) about 168', abs(pn['arl']['in_control'] - 168) < 3, True)

# ---------------------------------------------------------------------------
# The Western Electric / Nelson tests, each on a sequence made for it
def fires(seq, test, want):
    v = np.asarray(seq, float)
    n = len(v)
    flags = Q.nelson(v, np.zeros(n), np.ones(n), np.full(n, -3.0), np.full(n, 3.0), [test])
    got = [i for i, f in enumerate(flags) if test in f]
    return check(f'test {test} fires at {want}', got, want)


calm = [0.3, -0.4, 0.5, -0.2, 0.1, -0.6, 0.4, -0.3]
fires(calm + [3.5] + calm, 1, [8])
fires([-0.5] + [0.5] * 9 + [-0.5], 2, [9])
fires([0.5] * 9 + [0.0] + [0.5] * 8, 2, [8])        # a point on the center line breaks the run
fires([0, -0.5, -0.3, 0.1, 0.4, 0.8, 1.2, 0.2], 3, [6])
fires([0.1 * (-1) ** i for i in range(14)], 4, [13])
fires([0.2, 2.5, 0.3, 2.4, 0.1], 5, [3])
fires([0.2, 2.5, -2.4, 0.3], 5, [])                 # zone A on both sides is not the same side
fires([1.5, 1.2, 0.2, 1.4, 1.1, -0.3], 6, [4])
fires([0.3 * (-1) ** i for i in range(15)] + [1.5], 7, [14])
fires([1.5 * (-1) ** i for i in range(8)], 8, [7])
flags = Q.nelson([np.nan, 0.5, 0.5], [0, 0, 0], [1, 1, 1], [-3, -3, -3], [3, 3, 3], [2], test_n={2: 2})
check('tests skip missing points; customised run length', [i for i, f in enumerate(flags) if f], [2])
r = call('quality.control_chart', table=tid, y='d', subgroup='subgroup', chart='xbar_r', tests=[1, 2, 3, 4, 5, 6, 7, 8])
tt = r['tests_table']['rows']
check('the shift after subgroup 18 fails a test late in the chart', any(int(row['label']) > 18 for row in tt), True)
check('the tests table names the subgroup and the tests', set(tt[0]) >= {'chart', 'label', 'value', 'tests', 'n_rows'}, True)
check('the test descriptions', r['test_text']['2'], '9 points in a row on one side of the center line')

# runs test (statsmodels)
from statsmodels.sandbox.stats.runs import runstest_1samp  # noqa: E402
rt = call('quality.runs_test', table=tid3, y='x')
zr, pr = runstest_1samp(xi, cutoff=np.median(xi), correction=True)
check.near('runs test z (statsmodels)', rt['z'], float(zr), rel=1e-12)

# ---------------------------------------------------------------------------
# Process capability
lsl, usl, target = 9.4, 10.6, 10.0
r = call('quality.capability', table=tid, columns=['d'], specs={'d': {'lsl': lsl, 'usl': usl, 'target': target}}, subgroup='subgroup')
c = r['columns'][0]
s_w = rbar / d2_quad(5)
s_o = float(np.std(x, ddof=1))
mu = float(x.mean())
idx = lambda rows, name: next(rw for rw in rows if rw['index'] == name)
check.near('within sigma: average of ranges', c['sd_within'], s_w, rel=1e-9)
check.near('Cp = (USL − LSL)/6σw', idx(c['within'], 'Cp')['estimate'], (usl - lsl) / (6 * s_w), rel=1e-9)
check.near('Cpk = min(USL − x̄, x̄ − LSL)/3σw', idx(c['within'], 'Cpk')['estimate'], min(usl - mu, mu - lsl) / (3 * s_w), rel=1e-9)
check.near('Pp', idx(c['overall'], 'Pp')['estimate'], (usl - lsl) / (6 * s_o), rel=1e-12)
check.near('Ppk', idx(c['overall'], 'Ppk')['estimate'], min(usl - mu, mu - lsl) / (3 * s_o), rel=1e-12)
check.near('Cpm = min(T − LSL, USL − T)/3√(s² + (x̄ − T)²)', idx(c['overall'], 'Cpm')['estimate'], min(target - lsl, usl - target) / (3 * math.sqrt(s_o ** 2 + (mu - target) ** 2)), rel=1e-12)
n = len(x)
pp_ = idx(c['overall'], 'Pp')
check.near('Pp lower limit (χ², n − 1)', pp_['lower'], pp_['estimate'] * math.sqrt(stats.chi2.ppf(0.025, n - 1) / (n - 1)), rel=1e-12)
ppk = idx(c['overall'], 'Ppk')
check.near('Ppk interval (Bissell)', ppk['upper'], ppk['estimate'] + 1.959963984540054 * math.sqrt(1 / (9 * n) + ppk['estimate'] ** 2 / (2 * (n - 1))), rel=1e-12)
ppu = idx(c['overall'], 'Ppu')
t_obs = 3 * math.sqrt(n) * ppu['estimate']
check.near('Ppu lower limit (noncentral t)', stats.nct.sf(t_obs, n - 1, 3 * math.sqrt(n) * ppu['lower']), 0.025, abs_=1e-8)
check.near('Ppu upper limit (noncentral t)', stats.nct.cdf(t_obs, n - 1, 3 * math.sqrt(n) * ppu['upper']), 0.025, abs_=1e-8)
check.near('stability index = σ overall/σ within', c['stability'], s_o / s_w, rel=1e-9)
check.near('expected above USL, overall', c['expected_overall']['above'], float(stats.norm.sf((usl - mu) / s_o)), rel=1e-12)
check.near('expected below LSL, within', c['expected_within']['below'], float(stats.norm.cdf((lsl - mu) / s_w)), rel=1e-9)
check('observed outside', (c['observed']['n_below'], c['observed']['n_above']), (int(np.sum(x < lsl)), int(np.sum(x > usl))))
check.near('goal plot x = (x̄ − T)/(USL − LSL)', c['goal']['x'], (mu - target) / (usl - lsl), rel=1e-12)
check.near('goal plot y = s/(USL − LSL)', c['goal']['y_overall'], s_o / (usl - lsl), rel=1e-12)
r = call('quality.capability', table=tid, columns=['d'], specs={'d': {'lsl': lsl, 'usl': usl}}, subgroup='subgroup', within='pooled')
sp_ = math.sqrt(np.sum(4 * sdev ** 2) / 100) / Q.c4(101)
check.near('pooled unbiased standard deviation', r['columns'][0]['sd_within'], sp_, rel=1e-12)
r = call('quality.capability', table=tid3, columns=['x'], specs={'x': {'usl': 56}})
check.near('individuals: moving range within sigma, one-sided Cpu', idx(r['columns'][0]['within'], 'Cpu')['estimate'], (56 - xi.mean()) / (3 * mr.mean() / d2_quad(2)), rel=1e-9)
check('one spec limit: no Cp', any(rw['index'] == 'Cp' for rw in r['columns'][0]['within']), False)
# nonnormal: the percentile method on a lognormal fit
yl = np.round(rng.lognormal(1.0, 0.35, 150), 4)
tid7 = table({'y': yl})
r = call('quality.capability', table=tid7, columns=['y'], specs={'y': {'lsl': 0.8, 'usl': 7.5}}, dist={'y': 'lognormal'})
c = r['columns'][0]
s_, loc_, sc_ = stats.lognorm.fit(yl, floc=0)
fr = stats.lognorm(s_, loc=0, scale=sc_)
p_lo, p50, p_hi = fr.ppf([0.00135, 0.5, 0.99865])
check.near('lognormal Ppk by percentiles', idx(c['overall'], 'Ppk')['estimate'], min((7.5 - p50) / (p_hi - p50), (p50 - 0.8) / (p50 - p_lo)), rel=1e-9)
check.near('lognormal Pp by percentiles', idx(c['overall'], 'Pp')['estimate'], (7.5 - 0.8) / (p_hi - p_lo), rel=1e-9)
check.near('lognormal expected above USL', c['expected_overall']['above'], float(fr.sf(7.5)), rel=1e-9)
check('nonnormal: no within indices', c['within'], [])
r = call('quality.capability', table=tid7, columns=['y'], specs={'y': {'lsl': 0.8, 'usl': 7.5}}, dist={'y': 'best'})
check('best fit compares four families by AICc', [f['dist'] for f in r['columns'][0]['fit']['compared']][:1], [r['columns'][0]['dist']])
r = call('quality.capability', table=tid, columns=['d'], specs={'d': {}})
check('no spec limits: an error', 'error' in r['columns'][0], True)

# ---------------------------------------------------------------------------
# Pareto
causes = rng.choice(['scratch', 'dent', 'crack', 'stain', 'burr', 'chip'], 300, p=[.4, .25, .15, .1, .06, .04]).tolist()
shift = rng.choice(['day', 'night'], 300).tolist()
w = rng.integers(1, 4, 300)
tid8 = table({'cause': causes, 'shift': shift, 'w': w})
r = call('quality.pareto', table=tid8, cause='cause')
vc = pd.Series(causes).value_counts()
check('causes largest first', [cc['cause'] for cc in r['causes']], list(vc.index))
check('counts', [cc['count'] for cc in r['causes']], [float(v) for v in vc.to_numpy()])
check.near('cumulative percent ends at 1', r['causes'][-1]['cum'], 1.0)
check('rows of a cause', sorted(r['causes'][0]['rows']), [i for i, c_ in enumerate(causes) if c_ == vc.index[0]])
r = call('quality.pareto', table=tid8, cause='cause', freq='w')
vw = pd.DataFrame({'c': causes, 'w': w}).groupby('c')['w'].sum().sort_values(ascending=False)
check('Freq weights the counts', [cc['count'] for cc in r['causes']], [float(v) for v in vw.to_numpy()])
r = call('quality.pareto', table=tid8, cause='cause', combine={'below': 8})
small = [k for k, v in vc.items() if v / 300 < 0.08]
check('Combine Causes below 8% into Other', (r['causes'][-1]['cause'], r['causes'][-1]['count']), ('Other', float(sum(vc[k] for k in small))))
r = call('quality.pareto', table=tid8, cause='cause', groups=['shift'])
tab = pd.crosstab(pd.Series(shift, name='s'), pd.Series(causes, name='c'))
g_stat = stats.chi2_contingency(tab.to_numpy(), correction=False, lambda_='log-likelihood')
check.near('Test Rates Across Groups: the Poisson deviance is the G statistic', r['test']['lr'], float(g_stat[0]), rel=1e-7)
check.near('and the Pearson chi-square', r['test']['pearson'], float(stats.chi2_contingency(tab.to_numpy(), correction=False)[0]), rel=1e-9)
check('one cell per group level', [gr['label'] for gr in r['groups']], ['day', 'night'])

# ---------------------------------------------------------------------------
# Variability chart, variance components, Gauge R&R: 3 operators x 10 parts x 3
ops, parts, reps = 3, 10, 3
pe, oe, ope = rng.normal(0, 2.0, parts), rng.normal(0, 0.5, ops), rng.normal(0, 0.3, (ops, parts))
rows = [(f'O{o + 1}', p + 1, round(10 + pe[p] + oe[o] + ope[o, p] + rng.normal(0, 0.4), 4)) for o in range(ops) for p in range(parts) for _ in range(reps)]
gd = pd.DataFrame(rows, columns=['Operator', 'Part', 'Y'])
tid9 = table({'Operator': gd['Operator'].tolist(), 'Part': gd['Part'].tolist(), 'Y': gd['Y'].tolist()}, types={'Part': 'nominal'})
r = call('quality.variability', table=tid9, y='Y', xs=['Operator', 'Part'], gauge=True, tolerance=24.0)
check('30 cells of 3', (len(r['cells']), {cl['n'] for cl in r['cells']}), (30, {3}))
check('cells in nested order', r['cells'][10]['levels'], ['O2', '1'])
import statsmodels.api as sm  # noqa: E402
import statsmodels.formula.api as smf  # noqa: E402
a = sm.stats.anova_lm(smf.ols('Y ~ C(Operator) * C(Part)', gd.assign(Part=gd['Part'].astype(str))).fit(), typ=1)
ms = a['mean_sq']
mse, msop, mso, msp = ms['Residual'], ms['C(Operator):C(Part)'], ms['C(Operator)'], ms['C(Part)']
want = {'Operator': max(0, (mso - msop) / (parts * reps)), 'Part': max(0, (msp - msop) / (ops * reps)), 'Operator*Part': max(0, (msop - mse) / reps), 'Within': mse}
comp = {rw['component']: rw['var'] for rw in r['components']['table']['rows']}
check('EMS method for the balanced crossed design', r['components']['method'], 'EMS')
for kk, vv in want.items():
    check.near(f'EMS variance component {kk}', comp[kk], vv, rel=1e-9)
an = {rw['source']: rw for rw in r['components']['anova']['rows']}
check.near('F for Operator uses the Operator*Part mean square', an['Operator']['f'], mso / msop, rel=1e-9)
gg_ = r['gauge']
grr = math.sqrt(want['Within'] + want['Operator'] + want['Operator*Part'])
tv = math.sqrt(grr ** 2 + want['Part'])
check.near('%Gauge R&R = 100 RR/TV', gg_['pct_grr'], 100 * grr / tv, rel=1e-9)
check('number of distinct categories = floor(1.41 PV/RR)', gg_['ndc'], int(math.floor(1.41 * math.sqrt(want['Part']) / grr)))
check.near('P/T = 6 RR/tolerance', gg_['p_to_t'], 6 * grr / 24.0, rel=1e-9)
check.near('discrimination ratio √(2 PV²/RR² + 1)', gg_['discrimination'], math.sqrt(2 * want['Part'] / grr ** 2 + 1), rel=1e-9)
rr = {rw['source']: rw for rw in gg_['table']['rows']}
check.near('Repeatability variation = 6 σ_within', rr['Repeatability']['variation'], 6 * math.sqrt(mse), rel=1e-9)
check.near('Reproducibility = Operator + Operator*Part', rr['Reproducibility']['var'], want['Operator'] + want['Operator*Part'], rel=1e-9)
# REML, against MixedLM called directly
r2 = call('quality.variability', table=tid9, y='Y', xs=['Operator', 'Part'], method='reml')
md = smf.mixedlm('Y ~ 1', gd.assign(Part=gd['Part'].astype(str)), groups=np.ones(len(gd)), re_formula='0',
                 vc_formula={'O': '0 + C(Operator)', 'P': '0 + C(Part)', 'OP': '0 + C(Operator):C(Part)'})
res = md.fit(reml=True)
direct = dict(zip(md.exog_vc.names, res.vcomp))
comp2 = {rw['component']: rw['var'] for rw in r2['components']['table']['rows']}
check('REML method', r2['components']['method'], 'REML')
check.near('REML Part component (MixedLM)', comp2['Part'], float(direct['P']), rel=1e-6)
check.near('REML Operator*Part component', comp2['Operator*Part'], float(direct['OP']), rel=1e-5, abs_=1e-6)
check.near('REML within = MixedLM scale', comp2['Within'], float(res.scale), rel=1e-6)
if min(want.values()) > 0:
    check.near('balanced data: REML = EMS (Part)', comp2['Part'], want['Part'], rel=1e-4)
# nested: parts within operators
nest = gd.copy()
nest['Part'] = nest['Operator'] + '-' + nest['Part'].astype(str)
tid10 = table({'Operator': nest['Operator'].tolist(), 'Part': nest['Part'].tolist(), 'Y': nest['Y'].tolist()})
r3 = call('quality.variability', table=tid10, y='Y', xs=['Operator', 'Part'], model='nested')
a3 = sm.stats.anova_lm(smf.ols('Y ~ C(Operator) + C(Operator):C(Part)', nest).fit(), typ=1)
m3 = a3['mean_sq']
c3 = {rw['component']: rw['var'] for rw in r3['components']['table']['rows']}
check.near('nested: Part[Operator] = (MS_P(O) − MS_E)/r', c3['Part[Operator]'], (m3['C(Operator):C(Part)'] - m3['Residual']) / reps, rel=1e-9)
check.near('nested: Operator = (MS_O − MS_P(O))/(b r)', c3['Operator'], max(0.0, (m3['C(Operator)'] - m3['C(Operator):C(Part)']) / (parts * reps)), rel=1e-9, abs_=1e-12)
# unbalanced: best picks REML
tid11 = table({'Operator': gd['Operator'].tolist()[:-2], 'Part': gd['Part'].tolist()[:-2], 'Y': gd['Y'].tolist()[:-2]}, types={'Part': 'nominal'})
r4 = call('quality.variability', table=tid11, y='Y', xs=['Operator', 'Part'])
check('unbalanced data: REML', (r4['components']['method'], r4['components']['balanced']), ('REML', False))
# no replicates: the interaction becomes the within term
one = gd.groupby(['Operator', 'Part'], as_index=False).first()
tid12 = table({'Operator': one['Operator'].tolist(), 'Part': one['Part'].tolist(), 'Y': one['Y'].tolist()}, types={'Part': 'nominal'})
r5 = call('quality.variability', table=tid12, y='Y', xs=['Operator', 'Part'])
check('no replicates: the interaction goes into Within', [rw['component'] for rw in r5['components']['table']['rows']], ['Operator', 'Part', 'Within', 'Total'])

# ---------------------------------------------------------------------------
# Attribute gauge
truth = rng.choice(['good', 'bad'], 20)
arows = []
for p_ in range(20):
    for rater in ['A', 'B', 'C']:
        for _ in range(2):
            v_ = truth[p_] if rng.uniform() > 0.12 else ('good' if truth[p_] == 'bad' else 'bad')
            arows.append((p_ + 1, rater, v_, truth[p_]))
ad = pd.DataFrame(arows, columns=['part', 'rater', 'rating', 'std'])
tid13 = table({c_: ad[c_].tolist() for c_ in ad.columns}, types={'part': 'nominal'})
r = call('quality.attribute_gauge', table=tid13, y='rating', rater='rater', part='part', standard='std')
from statsmodels.stats.inter_rater import cohens_kappa, fleiss_kappa  # noqa: E402
counts = ad.groupby('part')['rating'].value_counts().unstack(fill_value=0)[['bad', 'good']]
check.near("Fleiss' kappa (statsmodels)", r['fleiss']['rows'][-1]['kappa'], float(fleiss_kappa(counts.to_numpy(), method='fleiss')), rel=1e-12)
wide = ad.assign(trial=ad.groupby(['part', 'rater']).cumcount()).pivot_table(index=['part', 'trial'], columns='rater', values='rating', aggfunc='first')
kab = cohens_kappa(pd.crosstab(pd.Categorical(wide['A'], categories=['bad', 'good']), pd.Categorical(wide['B'], categories=['bad', 'good']), dropna=False).to_numpy())
check.near("Cohen's kappa A vs B (statsmodels)", r['pairs']['rows'][0]['kappa'], float(kab.kappa), rel=1e-12)
p1 = ad[ad['part'] == 1]['rating'].value_counts()
check.near('agreement of part 1: agreeing pairs over all pairs', r['parts'][0]['agree'], float(sum(c_ * (c_ - 1) / 2 for c_ in p1) / (6 * 5 / 2)), rel=1e-12)
eff = ad[ad['rater'] == 'A']
check.near('effectiveness of rater A', r['effectiveness']['rows'][0]['effectiveness'], float(np.mean(eff['rating'] == eff['std'])), rel=1e-12)

# ---------------------------------------------------------------------------
# The Python code of a result runs on a CSV export of the table
import contextlib  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402


def run_code(code):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(code, 'code', 'exec'), {})
    return buf.getvalue()


here = os.getcwd()
with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)
    try:
        pd.DataFrame({'subgroup': sub, 'd': x, 'phase': ph}).to_csv('Process.csv', index=False)
        pd.DataFrame({'cause': causes, 'shift': shift, 'w': w}).to_csv('Defects.csv', index=False)
        pd.DataFrame(rows, columns=['Operator', 'Part', 'Y']).to_csv('Gauge.csv', index=False)
        r = call('quality.control_chart', table=tid, y='d', subgroup='subgroup', chart='xbar_r', table_name='Process')
        out = run_code(r['code'])
        check('the XBar & R code prints the report\'s UCL', f"{r['limits']['rows'][0]['ucl']:.6f}"[:8] in out, True)
        r = call('quality.control_chart', table=tid, y='d', subgroup='subgroup', chart='ewma', table_name='Process')
        out = run_code(r['code'])
        check('the EWMA code prints the report\'s last limit', f"{r['panels'][0]['ucl'][-1]:.6f}" in out, True)
        r = call('quality.control_chart', table=tid, y='d', chart='ir', table_name='Process')
        out = run_code(r['code'])
        check('the Individuals code prints the report\'s limits (d2 by scipy quad: nine decimals)', f"{r['limits']['rows'][0]['ucl']:.9f}" in out, True)
        r = call('quality.control_chart', table=tid, y='d', chart='ir', sigma='mmr', mr_span=3, table_name='Process')
        out = run_code(r['code'])
        check('the median moving range code over a span of 3 prints the report\'s limits', f"{r['limits']['rows'][0]['ucl']:.8f}" in out, True)
        r = call('quality.control_chart', table=tid, y='d', subgroup='subgroup', chart='xbar_r', sigma='mmr', mr_span=3, table_name='Process')
        out = run_code(r['code'])
        check('... and on the subgroup means of an XBar chart', f"{r['limits']['rows'][0]['ucl']:.6f}"[:8] in out, True)
        r = call('quality.capability', table=tid, columns=['d'], specs={'d': {'lsl': lsl, 'usl': usl}}, subgroup='subgroup', table_name='Process')
        out = run_code(r['code'])
        cpk = next(i['estimate'] for i in r['columns'][0]['within'] if i['index'] == 'Cpk')
        check('the capability code prints the report\'s Cpk', f'Cpk {cpk:.10f}'[:14] in out, True)
        r = call('quality.pareto', table=tid8, cause='cause', groups=['shift'], table_name='Defects')
        out = run_code(r['code'])
        check('the Pareto code prints the rate test\'s deviance', f"{r['test']['lr']:.8f}"[:9] in out, True)
        r = call('quality.variability', table=tid9, y='Y', xs=['Operator', 'Part'], table_name='Gauge')
        out = run_code(r['code'])
        check('the variability code runs', 'Operator' in out, True)
    finally:
        os.chdir(here)

# rows: a subset, and rows=None for every row
r = call('quality.control_chart', table=tid, y='d', subgroup='subgroup', chart='xbar_r', rows=list(range(50)))
check('a row subset: 10 subgroups', len(r['units']), 10)
check('rows=None is every row', len(call('quality.control_chart', table=tid, y='d', subgroup='subgroup', rows=None)['units']), 25)
check('no values: an error', 'error' in call('quality.control_chart', table=tid, y='d', rows=[]), True)
check('XBar without subgroups: an error that says what to do', 'Subgroup' in call('quality.control_chart', table=tid3, y='x', chart='xbar_r').get('error', ''), True)
sys.exit(check.done())
