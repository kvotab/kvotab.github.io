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
# ---------------------------------------------------------------------------
# The code keeps the report's rows, and the graphs' code
# ---------------------------------------------------------------------------
# Each result's code runs on the whole table as File > Export CSV writes it
# (a date as YYYY-MM-DD text) and keeps the report's rows: a By group's
# where lines, and the drop of the group's rows the report leaves out. Each
# graph's matplotlib code (plot_code) runs with the Agg backend there, and
# its figure is checked against the report's numbers drawn as the page draws
# them (smui-p-quality.js).
import tempfile as _tempfile  # noqa: E402

from smui import util as U  # noqa: E402
from test_charts import close, maxdiff, run_snippet  # noqa: E402

CTMP = _tempfile.mkdtemp(prefix='smui-quality-')
U_PAL = ['#2f6690', '#d9822b', '#3a7d44', '#b0413e', '#6c5b7b', '#1f9e89', '#c0a000', '#8c564b', '#e377c2', '#7f7f7f', '#17becf', '#9467bd']
QC = {'point': '#2f6690', 'line': '#2f66908c', 'limit': '#c0392b', 'center': '#2e7d32', 'flag': '#d62728', 'zone': '#3c281e4c', 'muted': '#786b5d'}


def export(tid):
    """The table as File > Export CSV writes it: every column, a date as YYYY-MM-DD text."""
    from smui import data as D
    t = D.TABLES[tid]
    cols = {}
    for name, v in t['cols'].items():
        m = t['meta'][name]
        if m.get('dataType') == 'numeric':
            v = np.asarray(v, dtype=float)
            if (m.get('format') or {}).get('kind') == 'date':
                v = pd.Series([pd.Timestamp(int(x), unit='ms').strftime('%Y-%m-%d') if np.isfinite(x) else None for x in v], dtype=object)
        else:
            v = pd.Series(list(v), dtype=object)
        cols[name] = v
    return pd.DataFrame(cols)


def dated(code, tid):
    """The code as the page shows it: ctx.code turns a date column it names back into the page's number."""
    return U.dated_code(code, U.date_columns(tid))


def jmp_q(v, p):
    """JMP's quantile, written out: the (n + 1)p-th of the sorted values, interpolated; before the first or after the last, that value."""
    s_ = sorted(float(x_) for x_ in v)
    h = (len(s_) + 1) * p
    if h <= 1:
        return s_[0]
    if h >= len(s_):
        return s_[-1]
    k_ = int(math.floor(h))
    return s_[k_ - 1] + (h - k_) * (s_[k_] - s_[k_ - 1])


def jmp_box(v):
    """A box as JMP draws it: the (n + 1)p quartiles, the whiskers to the furthest values within 1.5 IQR of the box."""
    q1, med, q3 = jmp_q(v, 0.25), jmp_q(v, 0.5), jmp_q(v, 0.75)
    iqr = q3 - q1
    return q1, med, q3, min(x_ for x_ in v if x_ >= q1 - 1.5 * iqr), max(x_ for x_ in v if x_ <= q3 + 1.5 * iqr)


def bxp_boxes(ax, width):
    """The boxes matplotlib's bxp drew (patch_artist): each as (median, q1, q3, lower whisker, upper whisker), in drawing order."""
    meds = [ln['y'][0] for ln in ax['lines'] if len(ln['y']) == 2 and ln['y'][0] == ln['y'][1] and abs(ln['x'][1] - ln['x'][0] - width) < 1e-9]
    pats = [sorted({p_[1] for p_ in pa['xy'] if p_[1] is not None}) for pa in ax['patches'] if pa['type'] == 'PathPatch']
    whisk = [ln['y'] for ln in ax['lines'] if len(ln['x']) == 2 and ln['x'][0] == ln['x'][1] and len(ln['y']) == 2]
    lows = [min(w_) for w_ in whisk[0::2]]
    highs = [max(w_) for w_ in whisk[1::2]]
    return [(m_, b_[0], b_[-1], lo_, hi_) for m_, b_, lo_, hi_ in zip(meds, pats, lows, highs)]


def run_graph_code(label, code, tid, n_figs=1):
    """Run a graph's code on the table's CSV: its figures (checked to run, to end in plt.show())."""
    figs, err = run_snippet(dated(code, tid), export(tid), 'data', CTMP)
    check(f'{label}: the code runs', err, None)
    check(f'{label}: it ends in plt.show() and draws {n_figs} figure{"s" if n_figs > 1 else ""}', (code.rstrip().split('\n')[-1], len(figs or [])), ('plt.show()', n_figs))
    return figs or []


def run_ns(code, tid):
    """Run a result's code on the table's CSV: its variables."""
    here = os.getcwd()
    export(tid).to_csv(os.path.join(CTMP, 'data.csv'), index=False)
    os.chdir(CTMP)
    ns = {}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(dated(code, tid), 'code', 'exec'), ns)
    finally:
        os.chdir(here)
    return ns


def line_like(ax, X, Y, color=None, ls=None, rel=1e-9, abs_=1e-12):
    """A line of the axes with these points, colour (as a prefix: the probe keeps the alpha) and line style."""
    for ln in ax['lines']:
        if color is not None and not (ln['color'] or '').startswith(color):
            continue
        if ls is not None and ln['ls'] != ls:
            continue
        if close(ln['x'], X, rel, abs_) and close(ln['y'], Y, rel, abs_):
            return ln
    return None


def nums(a):
    return [None if v is None or (isinstance(v, float) and not math.isfinite(v)) else float(v) for v in a]


def step_line(xs, ys, breaks):
    """smui-p-quality.js stepLine: each point's value over [x - 1/2, x + 1/2], broken where the phase changes or a value is missing."""
    X, Y = [], []
    for i in range(len(xs)):
        y = ys[i]
        if y is None:
            continue
        if (i == 0 or i in breaks or ys[i - 1] is None) and X:
            X.append(None)
            Y.append(None)
        X.append(xs[i] - 0.5)
        Y.append(y)
        if i == len(xs) - 1 or (i + 1) in breaks or ys[i + 1] is None:
            X.append(xs[i] + 0.5)
            Y.append(y)
    return X, Y


def fmt5(v):
    """SM.util.fmt(v, {sig: 5}) for the usual range of limits."""
    s_ = str(int(v)) if float(v).is_integer() and abs(v) < 1e15 else f'{v:.5g}'
    return s_.replace('-', '−')


def page_chart(res, o):
    """What the page draws of each chart (chartFigure), from the report's numbers."""
    units = res['units']
    N = len(units)
    xs = list(range(1, N + 1))
    breaks = {i for i in range(1, N) if units[i]['phase'] != units[i - 1]['phase']}
    out = []
    for pn in res['panels']:
        P = {'steps': [], 'zones': [], 'labels': [], 'ylabel': pn['ylabel']}
        vals = nums(pn['values'])
        lower = nums(pn['lower']) if pn.get('lower') is not None else None
        cl, sd = nums(pn['cl']), nums(pn['sd'])
        kz = (pn.get('k') or res['k']) / 3
        span = [v for v in vals + (lower or []) if v is not None]
        if (o.get('zones') or o.get('shade')) and pn['zones']:
            for m in (1, 2):
                for sg in (-1, 1):
                    ys = [c + sg * m * kz * q if c is not None and q is not None else None for c, q in zip(cl, sd)]
                    P['zones'].append(step_line(xs, ys, breaks))
                    span += [v for v in ys if v is not None]
        P['shade'] = bool(o.get('shade') and pn['zones'])
        if o.get('limits', True) and pn['key'] != 'run':
            for key in ('ucl', 'lcl'):
                ys = nums(pn[key])
                if any(v is not None for v in ys):
                    P['steps'].append((step_line(xs, ys, breaks), QC['limit']))
                    span += [v for v in ys if v is not None]
        if o.get('center', True):
            P['steps'].append((step_line(xs, cl, breaks), QC['center']))
            span += [v for v in cl if v is not None]
        if pn.get('data') is not None:
            P['data'] = nums(pn['data'])
            span += [v for v in P['data'] if v is not None]
        flagged = [bool(t) for t in pn['tests']]
        if pn['key'] == 'cusum':
            P['red'] = [f_ and v is not None and u is not None and v > u for f_, v, u in zip(flagged, vals, nums(pn['ucl']))]
            P['lower_red'] = [f_ and v is not None and u is not None and v < u for f_, v, u in zip(flagged, lower, nums(pn['lcl']))]
        else:
            P['red'] = flagged
        J_ = []
        for i, v in enumerate(vals):
            if i in breaks:
                J_.append((None, None))
            J_.append((xs[i], v))
        P['joined'] = ([a for a, _ in J_], [b for _, b in J_])
        P['points'] = vals
        P['lower'] = lower
        texts = []
        for i, t in enumerate(pn['tests']):
            if not t:
                continue
            yv = vals[i] if vals[i] is not None else (lower[i] if lower else None)
            if yv is None:
                continue
            if pn['key'] == 'cusum' and lower and lower[i] is not None and abs(lower[i]) > abs(vals[i] or 0):
                yv = lower[i]
            texts.append((xs[i], yv, ','.join(str(v) for v in t)))
        P['texts'] = texts

        def last(a):
            return next((v for v in reversed(a) if v is not None), None)
        if o.get('limits', True) and pn['key'] != 'run':
            for name, key in (('UCL', 'ucl'), ('LCL', 'lcl')):
                v = last(nums(pn[key]))
                if v is not None:
                    P['labels'].append(f'{name}={fmt5(v)}')
        if o.get('center', True) and last(cl) is not None:
            P['labels'].append(f'{"Target" if pn["key"] == "cusum" else "Avg"}={fmt5(last(cl))}')
        lo, hi = min(span), max(span)
        dd = (hi - lo) * 0.1 if hi > lo else (abs(lo) * 0.05 or 1)
        P['range'] = [lo - dd, hi + dd]
        out.append(P)
    return out, breaks


def check_chart(label, res, F, o, x_title, ticks=None):
    """A control chart's figure against the page's drawing of the report's numbers."""
    want, breaks = page_chart(res, o)
    axes = F['axes']
    check(f'{label}: a plot for each chart', len(axes), len(want))
    N = len(res['units'])
    xs = list(range(1, N + 1))
    for ax, P in zip(axes, want):
        tag = f'{label} ({P["ylabel"]})'
        check(f'{tag}: the limits and the center line, by point and phase', bool(P['steps']) and all(line_like(ax, X, Y, color=c, ls='-') is not None for (X, Y), c in P['steps']), True)
        if P['zones']:
            check(f'{tag}: the zones, dotted', all(line_like(ax, X, Y, color=QC['zone'], ls=':') is not None for X, Y in P['zones']), True)
        if P['shade']:
            check(f'{tag}: the zones shaded, five bands', len(ax['polys']), 5)
        check(f'{tag}: the points joined, broken between phases', line_like(ax, *P['joined'], color=QC['line'], rel=1e-12) is not None, True)
        main = [s_ for s_ in ax['scatter'] if len(s_['xy']) == N and s_['colors'] and s_['colors'][0][:7] in (QC['point'], QC['flag'])]
        got = main[0] if main else {'xy': [], 'colors': []}
        check(f'{tag}: the points', close([q for p_ in got['xy'] for q in p_], [q for x_, v in zip(xs, P['points']) for q in (x_, v)], 1e-12, 1e-12), True)
        want_c = [QC['flag'] if r_ else QC['point'] for r_ in P['red']]
        got_c = [c[:7] for c in got['colors']]
        check(f'{tag}: the points failing a test in red', got_c == want_c or (len(set(want_c)) == 1 and set(got_c) == set(want_c)), True)
        if P['lower'] is not None:
            gl = main[1] if len(main) > 1 else {'xy': []}
            check(f'{tag}: the lower sums', close([q for p_ in gl['xy'] for q in p_], [q for x_, v in zip(xs, P['lower']) for q in (x_, v)], 1e-12, 1e-12), True)
        if P.get('data') is not None:
            dd = [s_ for s_ in ax['scatter'] if len(s_['xy']) == N and not s_['colors']]
            check(f'{tag}: the subgroup means, open circles', bool(dd) and close([p_[1] for p_ in dd[0]['xy']], P['data'], 1e-12, 1e-12), True)
        texts = sorted((round(t['x'], 9), round(t['y'], 9), t['s']) for t in ax['texts'] if t['s'][:1].isdigit())
        check(f'{tag}: the tests\' numbers over the failing points', texts, sorted((round(a, 9), round(b, 9), s_) for a, b, s_ in P['texts']))
        check(f'{tag}: the limits\' values at the right', [t['s'] for t in ax['texts'] if t['x'] is not None and abs(t['x'] - 1.004) < 1e-12], P['labels'])
        check(f'{tag}: the y range, a tenth beyond what is drawn, and the title', (close(ax['ylim'], P['range'], 1e-9, 1e-12), ax['ylabel']), (True, P['ylabel']))
    bottom = axes[-1]
    check(f'{label}: the x axis', (bottom['xlabel'], close(bottom['xlim'], [0.5, N + 0.5], 1e-12)), (x_title, True))
    if ticks is not None:
        check(f'{label}: the subgroups on the axis, as the page labels them', [t for t in bottom['xticklabels'] if t], ticks)
    vlines = [ln for ln in axes[0]['lines'] if ln['ls'] == '--' and (ln['color'] or '')[:7] == QC['muted']]
    check(f'{label}: a dashed line between phases', sorted(ln['x'][0] for ln in vlines), sorted(b + 0.5 for b in breaks))
    if breaks:
        bounds = [0, *sorted(breaks), N]
        names = [next((q['label'] for q in res['phases'] if q['code'] == res['units'][a]['phase']), '') for a in bounds[:-1]]
        check(f'{label}: the phases named above', [t['s'] for t in axes[0]['texts'] if t['y'] == 1.0], names)


# the Process data again, with a date for each subgroup, operators and attribute counts
days = np.datetime64('2026-03-02') + (sub - 1)
ms = (days.astype('datetime64[ms]').astype(np.int64)).astype(float)
oper = rng.choice(['Ann', 'Bo'], 125).tolist()
insp = rng.integers(80, 121, 125).astype(float)
defects = rng.binomial(insp.astype(int), 0.06).astype(float)
tq = table({'subgroup': sub, 'day': ms, 'd': x, 'phase': list(ph), 'operator': oper, 'n': insp, 'bad': defects},
           types={'subgroup': 'ordinal'}, levels={'phase': ['before', 'after']})
from smui import data as _D  # noqa: E402
_D.TABLES[tq]['meta']['day']['format'] = {'kind': 'date'}
left_out = [2, 7, 61]
rows_q = [i for i in range(125) if i not in left_out]
charts = [('xbar_r', {}, {'zones': True, 'shade': True}), ('xbar_s', {'tests': [1, 2, 5, 6]}, {}), ('ir', {'subgroup': None, 'tests': [1, 2, 3, 4, 5, 6, 7, 8]}, {'zones': True}),
          ('lj', {'subgroup': None}, {'center': False}), ('run', {'tests': [2, 3, 4]}, {}), ('ewma', {'lam': 0.3}, {}), ('cusum', {'target': 10.0, 'head_start': True}, {'limits': False}),
          ('p', {'y': 'bad', 'n_trials': 'n'}, {}), ('np', {'y': 'bad', 'n_trials': 'n'}, {}), ('c', {'y': 'bad'}, {}), ('u', {'y': 'bad', 'n_trials': 'n'}, {'zones': True}),
          ('xbar_r', {'phase': 'phase', 'tests': [1, 2, 3, 4, 5, 6, 7, 8], 'dispersion_tests': True}, {'zones': True}),
          ('ir', {'subgroup': None, 'phase': 'phase', 'sigma': 'mmr', 'mr_span': 3}, {}), ('xbar_r', {'subgroup': None, 'subgroup_size': 5, 'phase': 'phase'}, {}),
          ('xbar_s', {'subgroup': 'day', 'sigma': 'pooled', 'rows': rows_q, 'known_mean': 10.05}, {}),
          ('xbar_r', {'where': [{'column': 'operator', 'value': 'Ann'}], 'rows': [i for i in range(125) if oper[i] == 'Ann' and i not in left_out]}, {'shade': True})]
for chart, kw, o in charts:
    kw = dict(kw)
    args = dict(table=tq, y=kw.pop('y', 'd'), subgroup=kw.pop('subgroup', 'subgroup'), chart=chart, plot=o, tests=kw.pop('tests', [1]), table_name='data', **kw)
    r = call('quality.control_chart', **args)
    tag = f'control chart code: {r["chart_label"]} ({", ".join(f"{k}={v}" for k, v in kw.items() if k != "rows") or "defaults"}{", rows left out" if "rows" in kw else ""})'
    figs = run_graph_code(tag, r['plot_code'], tq)
    if figs:
        ticks = [u['label'] for u in r['units']] if args['subgroup'] == 'day' else None
        check_chart(tag, r, figs[0], o, args['subgroup'] or 'Sample', ticks)
        check(f'{tag}: the figure\'s size, the title', (figs[0]['size'], figs[0]['suptitle']),
              ([max(520, min(820, 170 + 18 * len(r['units']))) / 100, (440 if len(r['panels']) > 1 else 300) / 100], r['chart_label'] + ('' if r['chart_label'].endswith('Chart') else ' chart') + f' of {args["y"]}'))
    if chart in ('xbar_r', 'xbar_s', 'ir', 'lj', 'ewma', 'cusum') and 'where' not in kw and 'phase' not in kw:   # the code's sigma is over every phase
        ns = run_ns(r['code'], tq)
        s_want = r['summary']['sigma'][-1]['sigma']
        check.near(f'{tag}: its statistics code gives the report\'s sigma', float(ns.get('sigma', np.nan)), s_want, rel=1e-9)
# a date subgroup: the code's ticks are the dates the page shows
r = call('quality.control_chart', table=tq, y='d', subgroup='day', chart='xbar_r', plot={}, table_name='data')
check('a date subgroup: the page labels the points by their dates', [u['label'] for u in r['units']][:2], ['2026-03-02', '2026-03-03'])
check('... and the code turns the column back into the page\'s number after reading it', dated(r['plot_code'], tq).count('pd.to_datetime(df["day"])'), 1)
# By and rows left out: the statistics code keeps the report's rows
wh = [{'column': 'operator', 'value': 'Bo'}]
rows_bo = [i for i in range(125) if oper[i] == 'Bo' and i not in left_out]
r = call('quality.control_chart', table=tq, y='d', subgroup='subgroup', chart='xbar_r', where=wh, rows=rows_bo, table_name='data')
drop_bo = [i for i in left_out if oper[i] == 'Bo']
check('the code keeps the By group\'s rows and drops the ones the report leaves out',
      [ln for ln in r['code'].split('\n') if 'only the rows where' in ln or 'leaves out' in ln],
      ['df = df[df["operator"] == "Bo"]   # only the rows where operator is Bo'] + ([f'df = df.drop(index=[{", ".join(map(str, drop_bo))}])   # the rows the report leaves out'] if drop_bo else []))
ns = run_ns(r['code'], tq)
check.near('... and gives the group\'s sigma', float(ns['sigma']), r['summary']['sigma'][0]['sigma'], rel=1e-9)
check.near('... and its grand mean', float(ns['center']), r['summary']['sigma'][0]['center'], rel=1e-12)
rt = call('quality.runs_test', table=tq, y='d', subgroup='subgroup', where=wh, rows=rows_bo, table_name='Process')
check('the runs test\'s code reads the report\'s table, not data.csv', ('"Process.csv"' in rt['code'], 'df = df[df["operator"] == "Bo"]' in rt['code']), (True, True))

# ---- Process Capability: the histograms, the goal plot, the box plots, the index plot


def nice_bins(v):
    """SM.report.niceBins: bins at round numbers, about as many as Sturges' rule asks for."""
    n_, lo, hi = len(v), min(v), max(v)
    if lo == hi:
        return lo - 0.5, 1.0, 1
    k_ = max(5, min(40, math.ceil(math.log2(n_) + 1)))
    raw = (hi - lo) / k_
    p_ = 10 ** math.floor(math.log10(raw))
    size_ = min((m_ * p_ for m_ in (1, 2, 2.5, 5, 10)), key=lambda s_: abs(math.log(s_ / raw)))
    start = math.floor(lo / size_) * size_
    end = math.ceil(hi / size_) * size_
    if end <= hi:
        end += size_
    return start, size_, max(1, round((end - start) / size_))


c1 = np.round(10 + rng.normal(0, 0.15, 125), 3)
c2 = np.round(rng.lognormal(1.0, 0.3, 125), 3)
c3 = np.round(5 + rng.normal(0, 0.3, 125), 3)
c1[9] = np.nan
tc = table({'subgroup': sub, 'a': c1, 'b': c2, 'c': c3, 'operator': oper}, types={'subgroup': 'ordinal'})
specs_c = {'a': {'lsl': 9.5, 'target': 10.0, 'usl': 10.6}, 'b': {'lsl': 0.8, 'usl': 7.5}, 'c': {'usl': 6.2}}
fc = export(tc)
for sg, within, dist, goal_w, rows_c in ((None, None, {'b': 'lognormal'}, False, None), ('subgroup', None, {'b': 'best'}, True, rows_q), ('subgroup', 'std', {}, False, None),
                                         (None, 'mmr', {'b': 'weibull', 'c': 'gamma'}, True, rows_q), ('subgroup', 'pooled', {}, True, None)):
    bins = {}
    for c_ in ('a', 'b', 'c'):
        v_ = fc.loc[rows_c if rows_c else fc.index, c_].dropna().to_numpy()
        start, size_, nb = nice_bins(list(v_))
        bins[c_] = {'start': start, 'size': size_, 'nb': nb, 'end': start + nb * size_}
    plot = {'bins': bins, 'curves': {'a': {'within': True, 'overall': True}, 'c': {'within': False, 'overall': True}}, 'goal': {'ppk': 1.2, 'within': goal_w}}
    r = call('quality.capability', table=tc, columns=['a', 'b', 'c'], rows=rows_c, specs=specs_c, subgroup=sg, within=within, dist=dist, plot=plot, table_name='data')
    tag = f'capability code ({sg or "moving range"}, {within or "default"} within sigma, {dist or "normal"}{", rows left out" if rows_c else ""})'
    pc = r['plot_code']
    for cr in r['columns']:
        c_ = cr['column']
        F = run_graph_code(f'{tag}: {c_} histogram', pc['hist'][c_], tc)
        if not F:
            continue
        ax = F[0]['axes'][0]
        v_ = fc.loc[rows_c if rows_c else fc.index, c_].dropna().to_numpy()
        b = bins[c_]
        cnt = np.bincount(np.clip(np.floor((v_ - b['start']) / b['size'] + 1e-9), 0, b['nb'] - 1).astype(int), minlength=b['nb'])
        check(f'{tag}: {c_}: the bars are the page\'s counts in its bins', ([bb['h'] for bb in ax['bars']], close([bb['w'] for bb in ax['bars']], [b['size']] * b['nb'])), ([float(q) for q in cnt], True))
        lims = [q for q in (cr.get('lsl'), cr.get('target'), cr.get('usl')) if q is not None]
        lo_, hi_ = min([b['start']] + lims), max([b['end']] + lims)
        pad = 0.04 * (hi_ - lo_ or 1)
        grid = np.linspace(lo_ - pad, hi_ + pad, 160)
        scale_ = len(v_) * b['size']
        lines_ = {ln['label']: ln for ln in ax['lines'] if not ln['label'].startswith('_')}
        cur = plot['curves'].get(c_, {'within': True, 'overall': True})
        if cr['dist'] == 'normal':
            for key, sdk in (('Overall', 'sd_overall'), ('Within', 'sd_within')):
                on = cur['overall' if key == 'Overall' else 'within'] and cr.get(sdk) and cr[sdk] > 0
                if on:
                    want = scale_ * stats.norm.pdf(grid, cr['mean'], cr[sdk])
                    check.near(f'{tag}: {c_}: the {key.lower()} normal curve (the report\'s mean and sigma)', maxdiff(lines_.get(key, {}).get('y'), list(want)) / max(want), 0, abs_=1e-9)
                else:
                    check(f'{tag}: {c_}: no {key.lower()} curve', key in lines_, False)
        else:
            want = [scale_ * q for q in cr['curve']['pdf']]
            ln = lines_.get(cr['fit']['label'])
            check.near(f'{tag}: {c_}: the fitted {cr["fit"]["label"]} density on its grid', maxdiff(ln and ln['x'], cr['curve']['x']) + maxdiff(ln and ln['y'], want) / max(want), 0, abs_=1e-6)
        check(f'{tag}: {c_}: the spec limits and their names', (sorted(ln['x'][0] for ln in ax['lines'] if len(set(ln['x'])) == 1), sorted(t['s'] for t in ax['texts'])),
              (sorted(lims), sorted(n_ for n_, v in (('LSL', cr.get('lsl')), ('Target', cr.get('target')), ('USL', cr.get('usl'))) if v is not None)))
        check(f'{tag}: {c_}: the range and the titles', (close(ax['xlim'], [lo_ - pad, hi_ + pad], 1e-12), ax['xlabel'], ax['ylabel'], F[0]['suptitle']), (True, c_, 'Count', f'{c_} capability histogram'))
    F = run_graph_code(f'{tag}: goal plot', pc['goal'], tc)
    if F:
        ax = F[0]['axes'][0]
        pts = [q for q in r['columns'] if q.get('goal')]
        want = [[q['goal']['x'], q['goal']['y_within' if goal_w else 'y_overall']] for q in pts]
        check.near(f'{tag}: goal plot: each column at its spec-normalised mean shift and {"within" if goal_w else "overall"} sigma', maxdiff([a for p_ in ax['scatter'][0]['xy'] for a in p_], [a for p_ in want for a in p_]), 0, abs_=1e-9)
        tri = [p_ for p_ in ax['patches'] if p_['type'] == 'Polygon'][0]['xy']
        check.near(f'{tag}: goal plot: the triangle of the goal Ppk 1.2', maxdiff([a for p_ in tri[:3] for a in p_], [-0.5, 0, 0, 1 / 7.2, 0.5, 0]), 0, abs_=1e-12)
        ymax, xmax = max(1 / 7.2 * 1.4, max(p_[1] for p_ in want) * 1.15), max(0.55, max(abs(p_[0]) for p_ in want) * 1.15)
        check(f'{tag}: goal plot: the ranges, the labels', (close(ax['xlim'], [-xmax, xmax]), close(ax['ylim'], [0, ymax]), ax['ylabel'], [t['s'] for t in ax['texts']]),
              (True, True, f'Spec-Normalized {"Within" if goal_w else "Overall"} Std Dev', [q['column'] for q in pts]))
    F = run_graph_code(f'{tag}: box plots', pc['boxes'], tc)
    if F:
        ax = F[0]['axes'][0]
        both = [q for q in r['columns'] if q.get('lsl') is not None and q.get('usl') is not None]
        want, fl = [], []
        for q in both:
            t_ = q['target'] if q['target'] is not None else (q['lsl'] + q['usl']) / 2
            v_ = list((fc.loc[rows_c if rows_c else fc.index, q['column']].dropna().to_numpy() - t_) / (q['usl'] - q['lsl']))
            q1, med, q3, lo_w, hi_w = jmp_box(v_)
            want.append((med, q1, q3, lo_w, hi_w))
            fl.append(sorted(x_ for x_ in v_ if x_ < lo_w or x_ > hi_w))
        check(f'{tag}: box plots: each box as JMP draws it (the (n + 1)p quartiles, the whiskers within 1.5 IQR)', close([a for b_ in bxp_boxes(ax, 0.5) for a in b_], [a for w_ in want for a in w_], 1e-9, 1e-12), True)
        got_fl = [sorted(ln['y']) for ln in ax['lines'] if ln['marker'] == 'o']
        check(f'{tag}: box plots: the values beyond the whiskers as points', [g_ for g_ in got_fl if g_] == [f_ for f_ in fl if f_] and len(got_fl) == len(fl), True)
        lo_ = [((q['lsl'] - (q['target'] if q['target'] is not None else (q['lsl'] + q['usl']) / 2)) / (q['usl'] - q['lsl'])) for q in both[:1]][0]
        check(f'{tag}: box plots: the limits and the target', sorted(round(ln['y'][0], 12) for ln in ax['lines'] if len(set(ln['y'])) == 1 and len(ln['x']) == 2 and ln['x'] == [0.0, 1.0]),
              sorted(round(v, 12) for v in (lo_, lo_ + 1, 0.0)))
    F = run_graph_code(f'{tag}: index plot', pc['index'], tc)
    if F:
        ax = F[0]['axes'][0]
        idx_ = lambda q, nm: next((a['estimate'] for a in (q.get('within') or []) + (q.get('overall') or []) if a['index'] == nm), None)  # noqa: E731
        got_p = [bb['h'] for bb in ax['bars'] if bb['fc'].startswith('#b0413e')]
        got_c = [None if bb['h'] != bb['h'] else bb['h'] for bb in ax['bars'] if bb['fc'].startswith('#2e7d32')]
        check.near(f'{tag}: index plot: Ppk of every column', maxdiff(got_p, [idx_(q, 'Ppk') for q in r['columns']]), 0, abs_=1e-9)
        check(f'{tag}: index plot: Cpk (none for a nonnormal fit)', close(got_c, [idx_(q, 'Cpk') for q in r['columns']], 1e-9), True)
    ns = run_ns(r['code'], tc)
    last_ = r['columns'][-1]
    check.near(f'{tag}: the statistics code gives the last column\'s within sigma', float(ns['sw']), last_['sd_within'], rel=1e-9)
    check.near(f'{tag}: ... and its overall one', float(ns['so']), last_['sd_overall'], rel=1e-12)

# a small case where Hazen's rule (Plotly's own) gives other quartiles than JMP's (n + 1)p rule
tsm = table({'x': [1.0, 2, 3, 4, 5, 6, 7, 8, 9, 30], 'g': ['a'] * 5 + ['b'] * 5, 'y': [1.0, 2, 3, 4, 20, 5, 6, 7, 8, 9]})
v10 = [1.0, 2, 3, 4, 5, 6, 7, 8, 9, 30]
check('the small case: Hazen\'s quartiles differ from the (n + 1)p ones', (list(np.quantile(v10, [0.25, 0.75], method='hazen')), [jmp_q(v10, 0.25), jmp_q(v10, 0.75)]), ([3.0, 8.0], [2.75, 8.25]))
check('the small case: np.quantile(method="weibull") is the (n + 1)p rule', list(np.quantile(v10, [0.25, 0.5, 0.75], method='weibull')), [jmp_q(v10, 0.25), jmp_q(v10, 0.5), jmp_q(v10, 0.75)])
r = call('quality.capability', table=tsm, columns=['x'], specs={'x': {'lsl': 0.0, 'target': 20.0, 'usl': 40.0}}, plot={'bins': {}}, table_name='data')
F = run_graph_code('capability box plot code, the small case', r['plot_code']['boxes'], tsm)
if F:
    b_ = bxp_boxes(F[0]['axes'][0], 0.5)
    sc = [(v - 20) / 40 for v in v10]
    check('the small case: the box is JMP\'s: quartiles (2.75, 5.5, 8.25), whiskers 1 and 9, the value 30 beyond them', (close([a for q in b_ for a in q], [(5.5 - 20) / 40, (2.75 - 20) / 40, (8.25 - 20) / 40, (1 - 20) / 40, (9 - 20) / 40], 1e-12), [ln['y'] for ln in F[0]['axes'][0]['lines'] if ln['marker'] == 'o']),
          (True, [[(30 - 20) / 40]]))
r = call('quality.variability', table=tsm, y='y', xs=['g'], plot={'boxes': True}, table_name='data')
F = run_graph_code('variability box plot code, the small case', r['plot_code'], tsm)
if F:
    want = [jmp_box([1.0, 2, 3, 4, 20]), jmp_box([5.0, 6, 7, 8, 9])]
    check('the small case: each cell\'s box is JMP\'s (quartiles 1.5, 3, 12 of a; the whiskers 1 and 20)', close([a for q in bxp_boxes(F[0]['axes'][0], 0.5) for a in q], [a for q1, med, q3, lo_w, hi_w in want for a in (med, q1, q3, lo_w, hi_w)], 1e-12), True)
    check('... where Hazen\'s rule gives other quartiles of a', list(np.quantile([1.0, 2, 3, 4, 20], [0.25, 0.75], method='hazen')) != [want[0][0], want[0][2]], True)

# ---- Pareto
rq = np.random.default_rng(4)
causes2 = rq.choice(['scratch', 'dent', 'crack', 'stain', 'burr', 'chip'], 300, p=[.4, .25, .15, .1, .06, .04]).tolist()
shift2 = rq.choice(['night', 'day'], 300).tolist()
line2 = rq.choice(['L1', 'L2'], 300).tolist()
w2 = rq.integers(0, 4, 300).astype(float)
num2 = rq.choice([1, 2, 10, 20], 300, p=[.4, .3, .2, .1]).astype(float)
tp2 = table({'cause': causes2, 'shift': shift2, 'line': line2, 'w': w2, 'num': num2}, types={'num': 'nominal'}, levels={'shift': ['night', 'day']})
rows_p = [i for i in range(300) if i % 17]
for kw, plot in (({}, {}), ({'freq': 'w'}, {'percent': True, 'legend': True, 'nLegend': True, 'cumLabels': True}), ({'combine': {'below': 8}}, {'cumAxis': False}),
                 ({'combine': {'top': 3}, 'rows': rows_p}, {'cumPoints': False}), ({'groups': ['shift']}, {}), ({'groups': ['shift', 'line'], 'freq': 'w'}, {'percent': True, 'cumAxis': False}),
                 ({'cause': 'num'}, {}), ({'groups': ['shift']}, {'ungroup': 'overall'})):
    kw = dict(kw)
    args = dict(table=tp2, cause=kw.pop('cause', 'cause'), plot=plot, table_name='data', **kw)
    r = call('quality.pareto', **args)
    tag = f'Pareto code ({", ".join(f"{k}={v}" for k, v in kw.items() if k != "rows") or "counts"}{", rows left out" if "rows" in kw else ""}; {", ".join(sorted(plot)) or "the defaults"})'
    cells = r.get('groups') if (r.get('groups') and plot.get('ungroup') != 'overall') else None
    want_sets = [(g_['counts'], g_['total'] or 1, g_) for g_ in cells] if cells else [([c_['count'] for c_ in r['causes']], r['total'], None)]
    codes = r['plot_code']['cells'] if cells else [r['plot_code']['overall']]
    check(f'{tag}: a code block for each plot', len(codes), len(want_sets))
    for code, (cnt, total, g_) in zip(codes, want_sets):
        F = run_graph_code(f'{tag}{": " + g_["label"] if g_ else ""}', code, tp2)
        if not F:
            continue
        ax = F[0]['axes'][0]
        pct = plot.get('percent')
        hs = [100 * c_ / total for c_ in cnt] if pct else list(cnt)
        check.near(f'{tag}: the bars', maxdiff([b_['h'] for b_ in ax['bars']], hs), 0, abs_=1e-9)
        check(f'{tag}: the causes, largest first, Other last', [t for t in ax['xticklabels'] if t], [c_['cause'] for c_ in r['causes']])
        cum = list(np.cumsum(cnt) * 100 / total)
        ymax = 100 if pct else max(max(hs), 1)
        if plot.get('cumAxis', True):
            cx = F[0]['axes'][1]
            check(f'{tag}: the cumulative percent on its own axis', (close(cx['lines'][0]['y'], cum, 1e-9), close(cx['ylim'], [0, 105]), cx['lines'][0]['marker']), (True, True, 'None' if plot.get('cumPoints', True) is False else 'o'))
        else:
            check(f'{tag}: the cumulative percent on the bars\' axis', close(ax['lines'][0]['y'], cum if pct else [c_ / 100 * ymax for c_ in cum], 1e-9), True)
        check(f'{tag}: the y range and title', (close(ax['ylim'], [0, ymax * 1.05], 1e-9), ax['ylabel']), (True, 'Percent' if pct else 'Count'))
        want_title = 'Pareto plot' + (f' {", ".join(args["groups"])} = {g_["label"]} (N {g_["total"]:g})' if g_ else '')
        check(f'{tag}: the title', F[0]['suptitle'], want_title)
        if plot.get('legend'):
            check(f'{tag}: the Category Legend\'s colours', [b_['fc'][:7] for b_ in ax['bars']], U_PAL[:len(cnt)])
        if plot.get('nLegend'):
            check(f'{tag}: the N Legend', [t['s'] for t in ax['texts'] if t['s'].startswith('N = ')], [f'N = {total:g}'])
    ns = run_ns(r['code'], tp2)
    got = [((f'{i:.10g}' if isinstance(i, float) else str(i)), float(v)) for i, v in ns['counts'].items()]
    check(f'{tag}: the statistics code counts the report\'s rows, in its order, the small causes combined as it combines them', got, [(c_['cause'], c_['count']) for c_ in r['causes']])
# the rate test's code on every cell of the report's grid: an empty cell (no chip at night), two grouping columns, combined causes
rows_e = [i for i in range(300) if not (causes2[i] == 'chip' and shift2[i] == 'night')]
for kw in ({'groups': ['shift']}, {'groups': ['shift', 'line'], 'freq': 'w'}, {'groups': ['shift'], 'combine': {'below': 8}}):
    r = call('quality.pareto', table=tp2, cause='cause', rows=rows_e, table_name='data', **kw)
    ns = run_ns(r['code'], tp2)
    tag = f'Pareto code, Test Rates Across Groups ({", ".join(f"{k}={v}" for k, v in kw.items())}, an empty cell)'
    check.near(f'{tag}: the deviance is the report\'s likelihood ratio', float(ns['fit'].deviance), r['test']['lr'], rel=1e-9)
    check(f'{tag}: its degrees of freedom', int(ns['fit'].df_resid), r['test']['df'])

# ---- the variability chart and the attribute gauge's graphs
rv = np.random.default_rng(5)
ops_, parts_, reps_ = 3, 8, 3
pe_, oe_ = rv.normal(0, 2.0, parts_), rv.normal(0, 0.5, ops_)
vrows = [(['Cy', 'Ann', 'Bo'][o_], p_ + 1, round(10 + pe_[p_] + oe_[o_] + rv.normal(0, 0.4), 4)) for o_ in range(ops_) for p_ in range(parts_) for _ in range(reps_)]
vd = pd.DataFrame(vrows, columns=['Operator', 'Part', 'Y'])
vd.loc[5, 'Y'] = np.nan
vd['day'] = (np.datetime64('2026-01-05') + (vd['Part'].to_numpy() - 1) * 7).astype('datetime64[ms]').astype(np.int64).astype(float)
tv = table({'Operator': vd['Operator'].tolist(), 'Part': vd['Part'].tolist(), 'Y': vd['Y'].tolist(), 'day': vd['day'].tolist()}, types={'Part': 'nominal'}, levels={'Operator': ['Cy', 'Ann', 'Bo']})
_D.TABLES[tv]['meta']['day']['format'] = {'kind': 'date'}
keep_v = [i for i in range(len(vd)) if i not in (0, 40)]
for kw, plot in (({}, {}), ({'rows': keep_v}, {'points': True, 'boxes': True, 'jitter': True, 'connect': True, 'groupMeans': True, 'grandMean': True, 'grandMedian': True, 'sLimits': True}),
                 ({'xs': ['Part']}, {'sdChart': False}), ({'components': True, 'gauge': True}, {'meanSd': False, 'rangeBars': False}), ({'xs': ['Operator', 'day']}, {})):
    kw = dict(kw)
    args = dict(table=tv, y='Y', xs=kw.pop('xs', ['Operator', 'Part']), plot=plot, table_name='data', **kw)
    r = call('quality.variability', **args)
    tag = f'variability chart code ({" / ".join(args["xs"])}{", rows left out" if "rows" in kw else ""}; {", ".join(sorted(plot)) or "the defaults"})'
    F = run_graph_code(tag, r['plot_code'], tv)
    if not F:
        continue
    ax = F[0]['axes'][0]
    cells_ = r['cells']
    m_ = len(cells_)
    o = lambda k, d=False: plot.get(k, d)  # noqa: E731
    if o('cellMeans', True):
        ln = [q for q in ax['lines'] if q['marker'] == '_']
        check(f'{tag}: the cell means', bool(ln) and close(ln[0]['y'], [c_['mean'] for c_ in cells_], 1e-12) and ln[0]['ls'] == ('-' if o('connect') else 'None'), True)
    if o('points', True):
        pts = ax['scatter'][0]['xy']
        wy = [v for c_ in cells_ for v in vd.loc[c_['rows'], 'Y']]
        wx = [i + 1 for i, c_ in enumerate(cells_) for _ in c_['rows']]
        check(f'{tag}: each point at its cell{" (jittered)" if o("jitter") else ""}, its value', len(pts) == len(wy) and all(abs(p_[1] - v) < 1e-12 and abs(p_[0] - x_) <= (0.18 + 1e-9 if o('jitter') else 1e-12) for p_, v, x_ in zip(pts, wy, wx)), True)
    if o('rangeBars', True):
        segs = [s_ for c_ in ax['segments'] for s_ in c_['segs']]
        check(f'{tag}: the range bars', sorted((s_[0][0], s_[0][1], s_[1][1]) for s_ in segs), sorted((i + 1, c_['min'], c_['max']) for i, c_ in enumerate(cells_) if c_['n'] > 1))
    if o('grandMean'):
        check(f'{tag}: the grand mean', any(close(q['y'], [r['grand_mean']] * 2, 1e-12) for q in ax['lines']), True)
    if o('grandMedian'):
        check(f'{tag}: the grand median, dashed', any(close(q['y'], [r['grand_median']] * 2, 1e-12) and q['ls'] == '--' for q in ax['lines']), True)
    if o('groupMeans'):
        check(f'{tag}: the group means', all(any(close(q['x'], [g_['first'] + 0.6, g_['last'] + 1.4]) and close(q['y'], [g_['mean']] * 2, 1e-12) for q in ax['lines']) for g_ in r['group_means']), True)
    if o('boxes'):
        want = [jmp_box(list(vd.loc[c_['rows'], 'Y'].to_numpy(float))) for c_ in cells_]
        check(f'{tag}: each cell\'s box as JMP draws it (the (n + 1)p quartiles, the whiskers within 1.5 IQR)', close([a for b_ in bxp_boxes(ax, 0.5) for a in b_], [a for q1, med, q3, lo_w, hi_w in want for a in (med, q1, q3, lo_w, hi_w)], 1e-9, 1e-12), True)
    lo_, hi_ = min(c_['min'] for c_ in cells_), max(c_['max'] for c_ in cells_)
    check(f'{tag}: the y range', close(ax['ylim'], [lo_ - 0.06 * (hi_ - lo_), hi_ + 0.06 * (hi_ - lo_)], 1e-9), True)
    bottom = F[0]['axes'][-1]
    check(f'{tag}: the inner levels as ticks, as the page labels them; the title', ([t for t in bottom['xticklabels'] if t], bottom['xlabel']), ([c_['levels'][-1] for c_ in cells_], ' / '.join(r['factors'])))
    if len(r['factors']) > 1:
        want, start = [], 0
        for i in range(1, m_ + 1):
            if i < m_ and cells_[i]['levels'][:1] == cells_[start]['levels'][:1]:
                continue
            want.append(cells_[start]['levels'][0])
            start = i
        check(f'{tag}: the outer levels under the inner ones', [t['s'] for t in bottom['texts']], want)
    if o('sdChart', True):
        bx = F[0]['axes'][1]
        check(f'{tag}: the cells\' standard deviations', close([q for q in bx['lines'] if q['marker'] == 'o'][0]['y'], [c_['sd'] for c_ in cells_], 1e-12), True)
        if o('meanSd', True):
            check(f'{tag}: their mean', any(close(q['y'], [r['mean_sd']] * 2, 1e-12) for q in bx['lines']), True)
        if o('sLimits'):
            for key in ('ucl', 'lcl'):
                X_, Y_ = step_line(list(range(1, m_ + 1)), [s_[key] if s_ else None for s_ in r['s_limits']], set())
                check(f'{tag}: the S chart\'s {key.upper()}', any(close(q['x'], X_) and close(q['y'], Y_, 1e-9) for q in bx['lines']), True)
    ns = run_ns(r['code'], tv)
    check(f'{tag}: the statistics code gives the report\'s cells', close(list(ns['cells']['mean']), [c_['mean'] for c_ in cells_], 1e-12), True)
r = call('quality.variability', table=tv, y='Y', xs=['day'], plot={}, table_name='data')
check('a date factor: the page labels the cells by their dates', r['cells'][0]['levels'], ['2026-01-05'])
ta = np.random.default_rng(6)
truth2 = ta.choice(['good', 'bad', 'fair'], 12)
arows2 = [(p_ + 1, rater, truth2[p_] if ta.uniform() > 0.2 else ta.choice(['good', 'bad', 'fair']), truth2[p_]) for p_ in range(12) for rater in ['C', 'A', 'B'] for _ in range(2)]
ad2 = pd.DataFrame(arows2, columns=['part', 'rater', 'rating', 'std'])
ta2 = table({c_: ad2[c_].tolist() for c_ in ad2.columns}, types={'part': 'nominal'}, levels={'rater': ['C', 'A', 'B']})
for kw in ({}, {'standard': 'std', 'rows': [i for i in range(len(ad2)) if i % 11]}):
    r = call('quality.attribute_gauge', table=ta2, y='rating', rater='rater', part='part', plot={}, table_name='data', **kw)
    tag = f'attribute gauge code{" (a standard, rows left out)" if kw else ""}'
    for key, what, title in (('parts', 'parts', 'Agreement by part'), ('raters', 'rater_table', 'Agreement by rater')):
        F = run_graph_code(f'{tag}: {title}', r['plot_code'][key], ta2)
        if not F:
            continue
        ax = F[0]['axes'][0]
        got = ax['lines'][0]['y'] if key == 'parts' else [p_[1] for p_ in ax['scatter'][0]['xy']]
        check(f'{tag}: {title}: the agreements', close(got, [None if q['agree'] is None else 100 * q['agree'] for q in r[what]], 1e-12), True)
        check(f'{tag}: {title}: the ticks, the range, the title', ([t for t in ax['xticklabels'] if t], close(ax['ylim'], [-5, 105]), F[0]['suptitle']),
              ([q['part' if key == 'parts' else 'rater'] for q in r[what]], True, title))
    ns = run_ns(r['code'], ta2)
    if r.get('fleiss'):
        check.near(f'{tag}: the statistics code gives the report\'s Fleiss kappa', float(ns['fleiss_kappa'](ns['counts'].to_numpy(), method='fleiss')), r['fleiss']['rows'][-1]['kappa'], rel=1e-12)
    else:
        check(f'{tag}: the parts rated unequally often: no Fleiss kappa in the report, and the code runs without it', (r.get('fleiss_note') is not None, int(ns['counts'].sum(axis=1).nunique()) > 1), (True, True))

# ---- Show Alarm Report: the tests each chart runs, and the code of the alarms -----------------------------------------
# The page counts each chart's samples out of control (failing a test the chart runs) and the alarm rate from the
# charts' tests; the code under the report recomputes the charts and their tests from the CSV (its own test
# functions) and must give the same counts. The tests a chart runs: the chosen ones on the charts of the process, test
# 1 alone on the range, standard deviation and moving range charts unless the dispersion tests are on, test 1 on EWMA
# and CUSUM (no zones), tests 2 to 4 on a run chart (no limits).
for chart, kw, o in charts:
    kw = dict(kw)
    tests_ = kw.pop('tests', [1, 2, 3, 5, 6])
    args = dict(table=tq, y=kw.pop('y', 'd'), subgroup=kw.pop('subgroup', 'subgroup'), chart=chart, plot=o, tests=tests_, alarm=True, table_name='data', **kw)
    r = call('quality.control_chart', **args)
    tag = f'Alarm Report ({chart}{", phases" if args.get("phase") else ""}{", a By group" if args.get("where") else ""}{", rows left out" if args.get("rows") else ""})'
    if 'error' in r:
        check(f'{tag}: no error', r['error'], None)
        continue
    want_used = []
    for pn in r['panels']:
        if pn['key'] in ('ewma', 'cusum'):
            want_used.append([1] if 1 in tests_ else [])
        elif pn['key'] == 'run':
            want_used.append([t for t in sorted(tests_) if t in (2, 3, 4)])
        elif pn['key'] in ('r', 's', 'mr') and not args.get('dispersion_tests'):
            want_used.append([1] if 1 in tests_ else [])
        else:
            want_used.append(sorted(tests_))
    check(f'{tag}: the tests each chart runs', [pn['tests_used'] for pn in r['panels']], want_used)
    check(f'{tag}: a chart fails only the tests it runs', all(set(t) <= set(pn['tests_used']) for pn in r['panels'] for t in pn['tests']), True)
    ns = run_ns(r['alarm_code'], tq)
    want = []
    for q, pn in enumerate(r['panels']):
        v = np.array([np.nan if x is None else x for x in pn['values']], dtype=float)
        ok = np.isfinite(v)
        out = np.array([bool(t) for t in pn['tests']]) & ok
        want.append((q + 1, pn['title'], int(ok.sum()), int(out.sum())))
    check(f'{tag}: the code\'s samples and samples out of control are the report\'s', [tuple(x[:4]) for x in ns.get('report', [])], want)
    check.near(f'{tag}: ... and its alarm rates', max((abs(x[4] - x[3] / x[2]) if x[2] else 0.0) for x in ns.get('report', [(0, '', 1, 0, 0.0)])), 0.0, abs_=1e-15)
    check(f'{tag}: the code has no graph', ('plt.' in r['alarm_code'], 'matplotlib' in r['alarm_code']), (False, False))
    if args.get('where'):
        check(f'{tag}: the code keeps the By group', 'df = df[df["operator"] == "Ann"]' in r['alarm_code'], True)
r = call('quality.control_chart', table=tq, y='d', subgroup='subgroup', chart='xbar_r', tests=[], alarm=True, plot={})
check('Alarm Report without tests: no code (nothing to report)', 'alarm_code' in r, False)
r = call('quality.control_chart', table=tq, y='d', subgroup='subgroup', chart='xbar_r', tests=[1], plot={})
check('without Show Alarm Report: no alarm code', 'alarm_code' in r, False)

sys.exit(check.done())
