#!/usr/bin/env python3
"""Fit Curve and Nonlinear's backend (resources/py/smui/nonlinear.py).

Nonlinear against NIST's Statistical Reference Datasets for nonlinear
regression (https://www.itl.nist.gov/div898/strd/nls/nls_main.shtml; data
and certified values typed in from NIST's pages, which are in the public
domain): Misra1a (lower difficulty), Thurber and MGH09 (higher), from both
of NIST's starting points. Fit Curve's automatic starting values on the NIST
problems whose models are in its library (DanWood: Power; Rat42: Logistic
3P; Eckerle4: Gaussian Peak; MGH17: Biexponential 5P), and against
scipy's curve_fit on simulated data, with groups, weights and frequencies.
And the model language: what it accepts, and that it refuses everything
else.

    python3 resources/tests/smui/test_nonlinear.py
"""
import ast
import math
import os
import sys

import numpy as np
from scipy import stats
from scipy.optimize import curve_fit
from scipy.special import expit

from backend import FAILED, PY, Checks, call, table

check = Checks()
check('nonlinear.py imports', FAILED.get('nonlinear'), None)

# ---- NIST StRD -------------------------------------------------------------------------------
MISRA1A = dict(
    y=[10.07, 14.73, 17.94, 23.93, 29.61, 35.18, 40.02, 44.82, 50.76, 55.05, 61.01, 66.40, 75.47, 81.78],
    x=[77.6, 114.9, 141.1, 190.8, 239.9, 289.0, 332.8, 378.4, 434.8, 477.3, 536.8, 593.1, 689.1, 760.0],
    model='b1*(1-exp(-b2*x))', starts=[{'b1': 500, 'b2': 1e-4}, {'b1': 250, 'b2': 5e-4}],
    cert=[2.3894212918E+02, 5.5015643181E-04], se=[2.7070075241E+00, 7.2668688436E-06], rss=1.2455138894E-01, rsd=1.0187876330E-01, df=12)
THURBER = dict(
    y=[80.574, 84.248, 87.264, 87.195, 89.076, 89.608, 89.868, 90.101, 92.405, 95.854, 100.696, 101.060, 401.672, 390.724, 567.534, 635.316, 733.054,
       759.087, 894.206, 990.785, 1090.109, 1080.914, 1122.643, 1178.351, 1260.531, 1273.514, 1288.339, 1327.543, 1353.863, 1414.509, 1425.208,
       1421.384, 1442.962, 1464.350, 1468.705, 1447.894, 1457.628],
    x=[-3.067, -2.981, -2.921, -2.912, -2.840, -2.797, -2.702, -2.699, -2.633, -2.481, -2.363, -2.322, -1.501, -1.460, -1.274, -1.212, -1.100,
       -1.046, -0.915, -0.714, -0.566, -0.545, -0.400, -0.309, -0.109, -0.103, 0.010, 0.119, 0.377, 0.790, 0.963, 1.006, 1.115, 1.572, 1.841,
       2.047, 2.200],
    model='(b1 + b2*x + b3*x**2 + b4*x**3) / (1 + b5*x + b6*x**2 + b7*x**3)',
    starts=[dict(b1=1000, b2=1000, b3=400, b4=40, b5=0.7, b6=0.3, b7=0.03), dict(b1=1300, b2=1500, b3=500, b4=75, b5=1, b6=0.4, b7=0.05)],
    cert=[1.2881396800E+03, 1.4910792535E+03, 5.8323836877E+02, 7.5416644291E+01, 9.6629502864E-01, 3.9797285797E-01, 4.9727297349E-02],
    se=[4.6647963344E+00, 3.9571156086E+01, 2.8698696102E+01, 5.5675370270E+00, 3.1333340687E-02, 1.4984928198E-02, 6.5842344623E-03],
    rss=5.6427082397E+03, rsd=1.3714600784E+01, df=30)
MGH09 = dict(
    y=[1.957000E-01, 1.947000E-01, 1.735000E-01, 1.600000E-01, 8.440000E-02, 6.270000E-02, 4.560000E-02, 3.420000E-02, 3.230000E-02, 2.350000E-02, 2.460000E-02],
    x=[4.000000E+00, 2.000000E+00, 1.000000E+00, 5.000000E-01, 2.500000E-01, 1.670000E-01, 1.250000E-01, 1.000000E-01, 8.330000E-02, 7.140000E-02, 6.250000E-02],
    model='b1*(x^2+x*b2) / (x^2+x*b3+b4)', starts=[dict(b1=25, b2=39, b3=41.5, b4=39), dict(b1=0.25, b2=0.39, b3=0.415, b4=0.39)],
    cert=[1.9280693458E-01, 1.9128232873E-01, 1.2305650693E-01, 1.3606233068E-01], se=[1.1435312227E-02, 1.9633220911E-01, 8.0842031232E-02, 9.0025542308E-02],
    rss=3.0750560385E-04, rsd=6.6279236551E-03, df=7)

for name, d in (('Misra1a', MISRA1A), ('Thurber', THURBER), ('MGH09', MGH09)):
    tid = table({'y': d['y'], 'x': d['x']})
    for k, st in enumerate(d['starts'], 1):
        r = call('nonlinear.fit', table=tid, y='y', model=d['model'], start=st)
        if 'error' in r:
            check(f'{name} start {k}', r['error'], None)
            continue
        rows = r['estimates']['rows']
        for i, (row, c, s) in enumerate(zip(rows, d['cert'], d['se'])):
            check.near(f'{name} start {k}: b{i + 1}', row['estimate'], c, rel=2e-6)
            check.near(f'{name} start {k}: SE of b{i + 1}', row['se'], s, rel=1e-5)
        check.near(f'{name} start {k}: residual sum of squares', r['solution']['sse'], d['rss'], rel=1e-8)
        check.near(f'{name} start {k}: residual standard deviation', r['solution']['rmse'], d['rsd'], rel=1e-8)
        check(f'{name} start {k}: degrees of freedom', r['solution']['dfe'], float(d['df']))
        check(f'{name} start {k}: converged', r['status']['converged'], True)

# ---- Fit Curve's library on NIST problems, from its own starting values -------------------------
DANWOOD = dict(y=[2.138, 3.421, 3.597, 4.340, 4.882, 5.660], x=[1.309, 1.471, 1.490, 1.565, 1.611, 1.680])
RAT42 = dict(y=[8.930, 10.800, 18.590, 22.330, 39.350, 56.110, 61.730, 64.620, 67.080], x=[9.0, 14.0, 21.0, 28.0, 42.0, 57.0, 63.0, 70.0, 79.0])
ECKERLE4 = dict(
    y=[0.0001575, 0.0001699, 0.0002350, 0.0003102, 0.0004917, 0.0008710, 0.0017418, 0.0046400, 0.0065895, 0.0097302, 0.0149002, 0.0237310, 0.0401683,
       0.0712559, 0.1264458, 0.2073413, 0.2902366, 0.3445623, 0.3698049, 0.3668534, 0.3106727, 0.2078154, 0.1164354, 0.0616764, 0.0337200, 0.0194023,
       0.0117831, 0.0074357, 0.0022732, 0.0008800, 0.0004579, 0.0002345, 0.0001586, 0.0001143, 0.0000710],
    x=[400.0, 405.0, 410.0, 415.0, 420.0, 425.0, 430.0, 435.0, 436.5, 438.0, 439.5, 441.0, 442.5, 444.0, 445.5, 447.0, 448.5, 450.0, 451.5, 453.0, 454.5,
       456.0, 457.5, 459.0, 460.5, 462.0, 463.5, 465.0, 470.0, 475.0, 480.0, 485.0, 490.0, 495.0, 500.0])
MGH17 = dict(
    y=[0.844, 0.908, 0.932, 0.936, 0.925, 0.908, 0.881, 0.850, 0.818, 0.784, 0.751, 0.718, 0.685, 0.658, 0.628, 0.603, 0.580, 0.558, 0.538, 0.522,
       0.506, 0.490, 0.478, 0.467, 0.457, 0.448, 0.438, 0.431, 0.424, 0.420, 0.414, 0.411, 0.406],
    x=[10.0 * i for i in range(33)])
b1, b2, b3 = 7.2462237576E+01, 2.6180768402E+00, 6.7359200066E-02
cases = [
    ('DanWood', DANWOOD, 'power', [7.6886226176E-01, 3.8604055871E+00], [1.8281973860E-02, 5.1726610913E-02], 4.3173084083E-03),
    # Rat42, y = b1 / (1 + exp(b2 - b3 x)): Logistic 3P with a = b3, b = b2/b3, c = b1
    ('Rat42', RAT42, 'logistic3', [b3, b2 / b3, b1], [3.4465663377E-03, None, 1.7340283401E+00], 8.0565229338E+00),
    # Eckerle4, y = (b1/b2) exp(-((x - b3)/b2)^2 / 2): Gaussian Peak with a = b1/b2, b = b3, c = b2
    ('Eckerle4', ECKERLE4, 'gaussian', [1.5543827178E+00 / 4.0888321754E+00, 4.5154121844E+02, 4.0888321754E+00], [None, 4.6800518816E-02, 4.6803020753E-02], 1.4635887487E-03),
    # MGH17, y = b1 + b2 exp(-x b4) + b3 exp(-x b5): Biexponential 5P, a = b1, b = b2, c = b4, d = b3, f = b5
    ('MGH17', MGH17, 'biexp5', [3.7541005211E-01, 1.9358469127E+00, 1.2867534640E-02, -1.4646871366E+00, 2.2122699662E-02],
     [2.0723153551E-03, 2.2031669222E-01, 4.4861358114E-04, 2.2175707739E-01, 8.9471996575E-04], 5.4648946975E-05),
]
for name, d, model, cert, se, rss in cases:
    tid = table({'y': d['y'], 'x': d['x']})
    r = call('fitcurve.fit', table=tid, y='y', x='x', model=model)
    g = r['groups'][0]
    est = [e['estimate'] for e in g['estimates']]
    ses = [e['se'] for e in g['estimates']]
    if model == 'biexp5' and abs(est[2] - cert[2]) > abs(est[4] - cert[2]):   # the two exponentials in the other order
        est = [est[0], est[3], est[4], est[1], est[2]]
        ses = [ses[0], ses[3], ses[4], ses[1], ses[2]]
    for i, c in enumerate(cert):
        check.near(f'Fit Curve {r["label"]} on {name}: parameter {i + 1}', est[i], c, rel=1e-6)
        if se[i] is not None:
            check.near(f'Fit Curve {r["label"]} on {name}: SE {i + 1}', ses[i], se[i], rel=1e-5)
    check.near(f'Fit Curve {r["label"]} on {name}: SSE', g['summary']['sse'], rss, rel=1e-8)

# ---- Fit Curve against curve_fit, with groups, weights and frequencies ------------------------------
rng = np.random.default_rng(20260926)
x = np.tile(np.linspace(0, 10, 25), 3)
grp = np.repeat(['A', 'B', 'C'], 25)
shift = {'A': 4.0, 'B': 5.0, 'C': 6.5}


def l4(x, a, b, c, d):
    return c + (d - c) * expit(a * (x - b))


y = np.array([l4(xi, 1.2, shift[gi], 2, 12) for xi, gi in zip(x, grp)]) + rng.normal(0, 0.3, len(x))
tid = table({'y': y, 'x': x, 'g': grp.tolist()})
r = call('fitcurve.fit', table=tid, y='y', x='x', model='logistic4', group='g', parallel=True, equal=True, inverse=[7.0], ci=True)
check('one fit per group, in order', [g['level'] for g in r['groups']], ['A', 'B', 'C'])
sse_sep = 0.0
for g in r['groups']:
    m = grp == g['level']
    p, cov = curve_fit(l4, x[m], y[m], p0=[1, 5, 2, 12], ftol=1e-14, xtol=1e-14, gtol=1e-14, maxfev=20000)
    est = [e['estimate'] for e in g['estimates']]
    se = [e['se'] for e in g['estimates']]
    for i, nm in enumerate(['Growth Rate', 'Inflection Point', 'Lower Asymptote', 'Upper Asymptote']):
        check.near(f'Logistic 4P {g["level"]}: {nm} = curve_fit', est[i], float(p[i]), rel=1e-6)
        check.near(f'Logistic 4P {g["level"]}: SE of {nm} = curve_fit', se[i], float(np.sqrt(cov[i, i])), rel=1e-4)
    sse_g = float(np.sum((y[m] - l4(x[m], *p)) ** 2))
    check.near(f'{g["level"]}: SSE', g['summary']['sse'], sse_g, rel=1e-8)
    check(f'{g["level"]}: SSE no larger than curve_fit\'s', g['summary']['sse'] <= sse_g * (1 + 1e-12), True)
    sse_sep += sse_g
    inv = g['inverse'][0]
    check.near(f'{g["level"]}: inverse prediction reaches y = 7', l4(inv['x'], *est), 7.0, rel=1e-9)
    check(f'{g["level"]}: a band around the curve', all(lo <= yy <= hi for lo, yy, hi in zip(g['curve']['lower'], g['curve']['y'], g['curve']['upper'])), True)
n_all = len(y)
check.near('total SSE', r['summary']['sse'], sse_sep, rel=1e-8)
# the parallel model, fitted here with curve_fit: shared a, c, d and one b per group


def parallel(xg, a, c, d, bA, bB, bC):
    xx, gi = xg
    b = np.choose(gi.astype(int), [bA, bB, bC])
    return c + (d - c) * expit(a * (xx - b))


gi = np.array([['A', 'B', 'C'].index(v) for v in grp], dtype=float)
pp, _ = curve_fit(parallel, (x, gi), y, p0=[1, 2, 12, 4, 5, 6.5], ftol=1e-14, xtol=1e-14, gtol=1e-14, maxfev=20000)
sse_par = float(np.sum((y - parallel((x, gi), *pp)) ** 2))
F = ((sse_par - sse_sep) / 6) / (sse_sep / (n_all - 12))
check.near('parallel model SSE = curve_fit\'s', r['parallel']['sse_parallel'], sse_par, rel=1e-7)
check.near('parallelism F = ((SSE_par - SSE_sep)/6) / (SSE_sep/63)', r['parallel']['F'], F, rel=1e-6)
check.near('its p-value', r['parallel']['p'], float(stats.f.sf(F, 6, n_all - 12)), rel=1e-5)
p1, _ = curve_fit(l4, x, y, p0=[1, 5, 2, 12], ftol=1e-14, xtol=1e-14, gtol=1e-14, maxfev=20000)
sse1 = float(np.sum((y - l4(x, *p1)) ** 2))
check.near('equal parameters: one curve\'s SSE', r['equal']['sse_common'], sse1, rel=1e-8)
check.near('equal parameters F', r['equal']['F'], ((sse1 - sse_sep) / 8) / (sse_sep / (n_all - 12)), rel=1e-6)
# AICc counts the error variance: K = k + 1 per model
s = r['groups'][0]['summary']
nn, kk = 25, 5
m2ll = nn * math.log(2 * math.pi * s['sse'] / nn) + nn
check.near('AICc = -2LL + 2K + 2K(K+1)/(n-K-1), K = k + 1', s['aicc'], m2ll + 2 * kk + 2 * kk * (kk + 1) / (nn - kk - 1))
check('predictions for every row with an x', len(r['pred']['rows']), 75)
check('residuals for the fitted rows', sorted(r['resid']['rows']), list(range(75)))

# weights and frequencies: curve_fit with sigma = 1/sqrt(w) on the rows repeated by their counts
yd = l4(x, -1.0, 5, 1, 9) + rng.normal(0, 0.2, len(x))
fr = rng.integers(1, 4, len(x)).astype(float)
wt = rng.uniform(0.5, 2, len(x))
tw = table({'y': yd, 'x': x, 'f': fr, 'w': wt})
rw = call('fitcurve.fit', table=tw, y='y', x='x', model='logistic4', freq='f', weight='w')
rep = np.repeat(np.arange(len(x)), fr.astype(int))
pw, covw = curve_fit(l4, x[rep], yd[rep], p0=[-1, 5, 1, 9], sigma=1 / np.sqrt(wt[rep]), ftol=1e-14, xtol=1e-14, gtol=1e-14, maxfev=20000)
gw = rw['groups'][0]
check.near('decreasing curve, Weight and Freq: growth rate', gw['estimates'][0]['estimate'], float(pw[0]), rel=1e-6)
check.near('its SE', gw['estimates'][0]['se'], float(np.sqrt(covw[0, 0])), rel=1e-4)
check('N is the sum of the counts', gw['summary']['n'], float(fr.sum()))
# every model of the library fits a curve simulated from it
from smui import nonlinear as NL  # noqa: E402
truth = {'linear': [2, 0.5], 'quadratic': [1, 0.5, -0.03], 'cubic': [1, 0.2, 0.05, -0.004], 'quartic': [1, 0.2, 0.05, -0.004, 1e-4],
         'quintic': [1, 0.2, 0.05, -0.004, 1e-4, 1e-6], 'logistic2': [0.8, 5], 'logistic3': [0.9, 4, 20], 'logistic4': [1.1, 5, 2, 12],
         'logistic5': [1.0, 5, 2, 12, 0.6], 'probit2': [0.6, 5], 'probit4': [0.7, 5, 1, 9], 'gompertz3': [18, 0.9, 4], 'gompertz4': [2, 12, 0.8, 5],
         'weibullgrowth': [15, 5, 3], 'exp2': [2, 0.25], 'exp3': [3, 10, -0.4], 'biexp4': [10, 1.5, 4, 0.15], 'biexp5': [1, 10, 1.5, 4, 0.15],
         'mechanistic': [20, 0.9, 0.35], 'gaussian': [8, 5, 1.2], 'lorentzian': [8, 1.1, 5], 'onecomp': [50, 0.25, 1.5], 'michaelis': [10, 2.5],
         'power': [2, 1.6], 'log': [3, 2]}
check('every model in the library has a test', sorted(truth) == sorted(NL.MODELS), True)
xs = np.linspace(0.3, 10, 40)
for key, p in truth.items():
    f = NL.MODELS[key][4]
    y0 = f(xs, p)
    yy = y0 + rng.normal(0, 0.02 * np.ptp(y0), len(xs))
    rr = call('fitcurve.fit', table=table({'y': yy, 'x': xs}), y='y', x='x', model=key)
    est = [e['estimate'] for e in rr['groups'][0]['estimates']]
    err = float(np.sqrt(np.mean((f(xs, est) - y0) ** 2)) / np.ptp(y0))
    check(f'{NL.MODELS[key][0]}: the fitted curve follows the true one', err < 0.02 and rr['summary']['rsquare'] > 0.99, True)
check('Power needs x above zero', 'error' in call('fitcurve.fit', table=table({'y': [1.0, 2, 3, 4], 'x': [-1.0, 1, 2, 3]}), y='y', x='x', model='power'), True)
check('too few points', 'error' in call('fitcurve.fit', table=table({'y': [1.0, 2], 'x': [1.0, 2]}), y='y', x='x', model='logistic4'), True)

# ---- Nonlinear with weights, frequencies, column names with spaces ------------------------------------
tn = table({'resp': yd, 'dose (mg)': x, 'f': fr, 'w': wt})
rn = call('nonlinear.fit', table=tn, y='resp', model='c + (d - c) / (1 + exp(-a * (:"dose (mg)" - b)))', start={'a': -1, 'b': 5, 'c': 1, 'd': 9}, freq='f', weight='w')
ests = {row['parameter']: row for row in rn['estimates']['rows']}
check('parameters in the order they appear', [row['parameter'] for row in rn['estimates']['rows']], ['c', 'd', 'a', 'b'])
for i, nm in enumerate(['a', 'b', 'c', 'd']):
    check.near(f'Nonlinear {nm} = curve_fit, with Weight and Freq', ests[nm]['estimate'], float(pw[i]), rel=1e-6)
    check.near(f'Nonlinear SE of {nm} = curve_fit', ests[nm]['se'], float(np.sqrt(covw[i, i])), rel=1e-4)
check('the column as :"name"', rn['columns'], ['dose (mg)'])
check('a curve for a one-column model', len(rn['curve']['x']), 200)
rn2 = call('nonlinear.fit', table=tn, y='resp', model='c + (d - c) / (1 + exp(-a * (:Name("dose (mg)") - b)))', start={'a': -1, 'b': 5, 'c': 1, 'd': 9}, freq='f', weight='w')
check.near(':Name("…") is the same column', rn2['estimates']['rows'][1]['estimate'], rn['estimates']['rows'][1]['estimate'], rel=1e-12)
check('predictions and residuals have the page\'s rows', (len(rn['pred']['rows']), len(rn['resid']['rows'])), (75, 75))
check('missing starting values start at 1, and say so', call('nonlinear.fit', table=tn, y='resp', model='a + b * :f')['missing_start'], ['a', 'b'])

# ---- the Python shown under each result runs on a CSV export of the table -----------------------------
import subprocess  # noqa: E402
import tempfile  # noqa: E402
work = tempfile.mkdtemp()
import pandas as pd  # noqa: E402
pd.DataFrame({'resp': yd, 'dose (mg)': x, 'f': fr, 'w': wt}).to_csv(os.path.join(work, 'data.csv'), index=False)
tc = table({'resp': yd, 'dose (mg)': x, 'f': fr, 'w': wt})
for model in ('logistic4', 'gompertz4', 'quadratic', 'mechanistic'):
    rr = call('fitcurve.fit', table=tc, y='resp', x='dose (mg)', model=model, table_name='data')
    run = subprocess.run([sys.executable, '-c', rr['code']], cwd=work, capture_output=True, text=True, timeout=120)
    check(f'the code of Fit Curve {rr["label"]} runs', run.returncode, 0) or print(run.stderr[-600:])
rr = call('nonlinear.fit', table=tc, y='resp', model='c + (d - c) / (1 + exp(-a * (:"dose (mg)" - b)))', start={'a': -1, 'b': 5, 'c': 1, 'd': 9}, table_name='data')
run = subprocess.run([sys.executable, '-c', rr['code']], cwd=work, capture_output=True, text=True, timeout=120)
check('the code of Nonlinear runs', run.returncode, 0) or print(run.stderr[-600:])
import re  # noqa: E402
printed = [float(v) for v in re.findall(r'-?\d+\.\d+(?:e-?\d+)?', run.stdout)]
a_est = rr['estimates']['rows'][2]['estimate']
check('and prints the report\'s estimate of a', any(abs(v - a_est) <= 1e-5 * abs(a_est) for v in printed), True)

# ---- the model language ----------------------------------------------------------------------------
tl = table({'y': [1.0, 2, 3, 5, 8], 'x': [1.0, 2, 3, 4, 5], 'dose': [0.5, 1, 2, 4, 8]})
ok = [('a * exp(-b * :x) + c', ['a', 'b', 'c'], ['x']), ('a*x^2 + b', ['a', 'b'], ['x']), ('where(:x > 2.5, a, b) + c * dose', ['a', 'b', 'c'], ['x', 'dose']),
      ('Exp(a) + log10(b + :x) + minimum(a, :x) + maximum(b, 1e-3)', ['a', 'b'], ['x']), ('-a + +b * pi', ['a', 'b'], [])]
for text, params, cols in ok:
    r = call('nonlinear.parse', table=tl, model=text)
    check(f'accepts {text}', (r.get('params'), r.get('columns')), (params, cols))
check('a name given a starting value is a parameter, not the column', call('nonlinear.parse', table=tl, model='a * dose', declared=['dose'])['params'], ['a', 'dose'])
refuse = ["__import__('os').system('true')", 'a.__class__', '(lambda: 1)()', 'a[0]', 'open(a)', '"text" + a', 'exp(x=a)', 'a if b else c',
          'a < b < c', '[a, b]', 'a, b', 'x @ a', 'a // b', 'a % b', '{a: 1}', 'f"{a}"', 'eval(a)', 'exp(a, b)', 'exp', ':nosuch + a',
          '_hidden * a', 'a and b', 'not a', '(a := 2)', '*a', 'a ' * 3000, '(' * 300 + 'a' + ')' * 300, '-' * 300 + 'a', '1 + 2', 'True * a', '1j * a']
for text in refuse:
    r = call('nonlinear.parse', table=tl, model=text)
    check(f'refuses {text[:40]!r}', 'error' in r, True)
check('a refused model does not fit', 'error' in call('nonlinear.fit', table=tl, y='y', model="__import__('os')", start={}), True)
check('huge powers overflow to inf, not an exception', 'error' in call('nonlinear.fit', table=tl, y='y', model='a * 10 ** (10 ** 10) * x', start={'a': 1}), True)
# the module calls no eval, exec, compile or __import__ anywhere
src = open(os.path.join(PY, 'smui', 'nonlinear.py'), encoding='utf-8').read()
calls = {n.func.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
check('nonlinear.py never calls eval, exec, compile or __import__', sorted(calls & {'eval', 'exec', 'compile', '__import__'}), [])

sys.exit(check.done())
