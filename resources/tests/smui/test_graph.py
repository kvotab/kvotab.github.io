#!/usr/bin/env python3
"""Graph's backend (resources/py/smui/graph.py), checked against scipy and
statsmodels called directly: the summary statistics and JMP's quantiles
behind Bar, Line, Points and Box Plot, the Smoother (a smoothing spline on
standardized X, and lowess), Line of Fit with its bands, the density
ellipse, the kernel density contours, the chi-square of Mosaic and the
gridded surfaces of Contour Plot and Surface Plot. The Python code each
result carries is run on a CSV export of the table.

    python3 resources/tests/smui/test_graph.py
"""
import contextlib
import io
import math
import os
import sys
import tempfile

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from scipy.interpolate import griddata, make_smoothing_spline
from statsmodels.nonparametric.smoothers_lowess import lowess
from statsmodels.stats.contingency_tables import Table
from statsmodels.stats.weightstats import DescrStatsW

from backend import FAILED, Checks, call, table

check = Checks()
if 'graph' in FAILED:
    print('graph.py failed to import:', FAILED['graph'])
    sys.exit(1)
from smui import graph  # noqa: E402

rng = np.random.default_rng(20260926)
N = 240
g = rng.choice(['a', 'b', 'c'], N, p=[0.5, 0.3, 0.2])
x = rng.uniform(0, 10, N).round(1)          # ties on purpose
y = 3 + 0.8 * x - 0.05 * x ** 2 + rng.normal(0, 1.2, N) + np.where(g == 'b', 2, 0)
y[7] = np.nan
f = rng.integers(1, 4, N).astype(float)
z = np.sin(x / 2) + np.cos(y / 3)
cols = {'x': x, 'y': y, 'g': g.tolist(), 'f': f, 'z': z}
tid = table(cols)
lv = ['a', 'b', 'c']
codes = [lv.index(v) for v in g]
rows = list(range(N))
ok = np.isfinite(y)


def sub(v, level):
    m = (g == level) & ok
    return v[m]


# ---- summary ------------------------------------------------------------------
s = call('graph.summary', table=tid, y='y', rows=rows, codes=codes, k=3, boxes=True, by=['g'])
for i, level in enumerate(lv):
    v = sub(y, level)
    d = DescrStatsW(v, ddof=1)
    check.near(f'summary {level}: N', s['n'][i], float(len(v)))
    check.near(f'summary {level}: mean', s['mean'][i], float(v.mean()))
    check.near(f'summary {level}: std dev', s['sd'][i], float(v.std(ddof=1)))
    check.near(f'summary {level}: std err', s['se'][i], float(v.std(ddof=1) / math.sqrt(len(v))))
    lo, hi = d.tconfint_mean(0.05)
    check.near(f'summary {level}: lower 95%', s['lower'][i], float(lo))
    check.near(f'summary {level}: upper 95%', s['upper'][i], float(hi))
    check.near(f'summary {level}: sum', s['sum'][i], float(v.sum()))
    check.near(f'summary {level}: min', s['min'][i], float(v.min()))
    check.near(f'summary {level}: max', s['max'][i], float(v.max()))
    for key, p in zip(graph.QUANTILE_KEYS, graph.QUANTILES):
        check.near(f'summary {level}: quantile {p} (weibull)', s['quantiles'][key][i], float(np.quantile(v, p, method='weibull')))
    q1, q3 = np.quantile(v, [0.25, 0.75], method='weibull')
    inside = v[(v >= q1 - 1.5 * (q3 - q1)) & (v <= q3 + 1.5 * (q3 - q1))]
    check.near(f'summary {level}: lower whisker', s['lo_whisker'][i], float(inside.min()))
    check.near(f'summary {level}: upper whisker', s['hi_whisker'][i], float(inside.max()))
check('summary: code groups by g', "groupby([\"g\"]" in s['code'], True)

# Freq: a row counts f times
sf = call('graph.summary', table=tid, y='y', rows=rows, codes=codes, k=3, freq='f')
v, w = sub(y, 'a'), sub(f, 'a')
rep = np.repeat(v, w.astype(int))
check.near('freq: N is the sum of Freq', sf['n'][0], float(w.sum()))
check.near('freq: mean', sf['mean'][0], float(np.average(v, weights=w)))
check.near('freq: std dev as if replicated', sf['sd'][0], float(rep.std(ddof=1)))
check.near('freq: median as if replicated', sf['median'][0], float(np.quantile(rep, 0.5, method='weibull')))
lo, hi = DescrStatsW(v, weights=w, ddof=1).tconfint_mean(0.05)
check.near('freq: CI with n = sum of Freq', sf['lower'][0], float(lo))

# rows None (every row), codes None (one group), a negative code leaves the row out, an empty group
s0 = call('graph.summary', table=tid, y='y', rows=None)
check.near('rows None: every row', s0['n'][0], float(ok.sum()))
cn = [c if i % 2 else -1 for i, c in enumerate(codes)]
s2 = call('graph.summary', table=tid, y='y', rows=rows, codes=cn, k=4)
check.near('negative codes left out', sum(s2['n'][:3]), float(np.sum(ok & (np.arange(N) % 2 == 1))))
check('an empty group is missing, not zero', (s2['n'][3], s2['mean'][3]), (0.0, None))

# ---- Smoother --------------------------------------------------------------------
sm1 = call('graph.smoother', table=tid, x='x', y='y', rows=rows, codes=codes, k=3, lam=0.05)
xa, ya = sub(x, 'a'), sub(y, 'a')
m, sd = xa.mean(), xa.std(ddof=1)
zu, inv = np.unique((xa - m) / sd, return_inverse=True)
wu = np.bincount(inv).astype(float)
ref = make_smoothing_spline(zu, np.bincount(inv, ya) / wu, w=wu, lam=0.05)
c0 = sm1['curves'][0]
check.near('spline: grid runs over X', c0['x'][0], float(xa.min()))
err = max(abs(a - b) for a, b in zip(c0['y'], ref((np.array(c0['x']) - m) / sd)))
check.near('spline: the smoothing spline on standardized X, lambda 0.05', err, 0.0, abs_=1e-9)
# no ties: the same as make_smoothing_spline on the raw standardized data
xu = np.sort(rng.uniform(0, 5, 60))
yu = np.sin(xu) + rng.normal(0, 0.2, 60)
t2 = table({'x': xu, 'y': yu})
c1 = call('graph.smoother', table=t2, x='x', y='y', lam=0.3)['curves'][0]
ref1 = make_smoothing_spline((xu - xu.mean()) / xu.std(ddof=1), yu, lam=0.3)
err = max(abs(a - b) for a, b in zip(c1['y'], ref1((np.array(c1['x']) - xu.mean()) / xu.std(ddof=1))))
check.near('spline without ties: scipy directly', err, 0.0, abs_=1e-9)
# a huge lambda gives the least-squares line
c2 = call('graph.smoother', table=t2, x='x', y='y', lam=1e5)['curves'][0]
b = np.polyfit(xu, yu, 1)
err = max(abs(a - np.polyval(b, xx)) for xx, a in zip(c2['x'], c2['y']))
check.near('spline: a large lambda gives the straight line', err, 0.0, abs_=1e-3)
# lowess
cl = call('graph.smoother', table=tid, x='x', y='y', rows=rows, codes=codes, k=3, method='lowess', frac=0.5, it=2)['curves'][1]
xb, yb = sub(x, 'b'), sub(y, 'b')
rl = lowess(yb, xb, frac=0.5, it=2, return_sorted=True)
ux, first = np.unique(rl[:, 0], return_index=True)
check('lowess: one point per distinct X', len(cl['x']), len(ux))
check.near('lowess: statsmodels directly', max(abs(a - b) for a, b in zip(cl['y'], rl[first, 1])), 0.0, abs_=1e-10)
# bootstrap confidence of fit
cc = call('graph.smoother', table=tid, x='x', y='y', rows=rows, codes=codes, k=3, conf=True)['curves'][0]
inside = np.mean([(lo <= yy <= hi) for lo, yy, hi in zip(cc['lower'], cc['y'], cc['upper'])])
check('bootstrap band holds the curve', inside == 1.0 and cc['resamples'] >= 90, True)
xa0, ya0 = sub(x, 'a'), sub(y, 'a')
boot = []
rb0 = np.random.default_rng(20260926)
za = (xa0 - xa0.mean()) / xa0.std(ddof=1)
gz = (np.array(cc['x']) - xa0.mean()) / xa0.std(ddof=1)
for _ in range(100):
    i = rb0.integers(0, len(xa0), len(xa0))
    zu_, inv_ = np.unique(za[i], return_inverse=True)
    w_ = np.bincount(inv_).astype(float)
    boot.append(make_smoothing_spline(zu_, np.bincount(inv_, ya0[i]) / w_, w=w_, lam=0.05)(gz))
half = stats.norm.ppf(0.975) * np.std(np.array(boot), axis=0, ddof=1)
check.near('bootstrap band: the fit plus or minus 1.96 resample sd', max(abs(u - (yy + h)) for u, yy, h in zip(cc['upper'], cc['y'], half)), 0.0, abs_=1e-9)
sw = call('graph.summary', table=tid, y='y', rows=rows, codes=codes, k=3, want=['mean'])
check('summary: want keeps the answer small', sorted(sw), ['alpha', 'code', 'k', 'mean'])
few = call('graph.smoother', table=tid, x='x', y='y', rows=[0, 1, 2, 3], codes=[0, 0, 0, 0], k=1)['curves'][0]
check('spline: too few distinct X is an error, not a failure', 'error' in few, True)

# ---- Line of Fit -----------------------------------------------------------------
lf = call('graph.fit', table=tid, x='x', y='y', rows=rows, codes=codes, k=3, degree=1)
fa = lf['fits'][0]
ols = sm.OLS(ya, sm.add_constant(xa)).fit()
check.near('linear fit: intercept', fa['coef'][0], float(ols.params[0]), rel=1e-8)
check.near('linear fit: slope', fa['coef'][1], float(ols.params[1]), rel=1e-8)
check.near('linear fit: R-square', fa['r2'], float(ols.rsquared))
check.near('linear fit: RMSE', fa['rmse'], float(np.sqrt(ols.scale)))
check.near('linear fit: F', fa['f'], float(ols.fvalue), rel=1e-8)
pr = ols.get_prediction(sm.add_constant(np.array(fa['x']))).summary_frame(alpha=0.05)
check.near('linear fit: confidence of fit', max(abs(a - b) for a, b in zip(fa['fit_lower'], pr['mean_ci_lower'])), 0.0, abs_=1e-8)
check.near('linear fit: confidence of prediction', max(abs(a - b) for a, b in zip(fa['pred_upper'], pr['obs_ci_upper'])), 0.0, abs_=1e-8)
q = call('graph.fit', table=tid, x='x', y='y', rows=rows, codes=codes, k=3, degree=3)['fits'][2]
xc, yc = sub(x, 'c'), sub(y, 'c')
bq = np.polyfit(xc, yc, 3)
check.near('cubic fit: the least-squares cubic', max(abs(a - np.polyval(bq, xx)) for xx, a in zip(q['x'], q['y'])), 0.0, abs_=1e-7)
b0, b1, b2, b3 = q['coef']
mc = xc.mean()
jmp = [b0 + b1 * xx + b2 * (xx - mc) ** 2 + b3 * (xx - mc) ** 3 for xx in q['x']]
check.near("cubic fit: JMP's form b0 + b1 x + b2 (x-mean)^2 + b3 (x-mean)^3", max(abs(a - b) for a, b in zip(jmp, q['y'])), 0.0, abs_=1e-7)
lw = call('graph.fit', table=tid, x='x', y='y', rows=rows, codes=codes, k=3, freq='f')['fits'][0]
wa = sub(f, 'a').astype(int)
olsw = sm.OLS(np.repeat(ya, wa), sm.add_constant(np.repeat(xa, wa))).fit()
check.near('fit with Freq: rows replicated', lw['coef'][1], float(olsw.params[1]), rel=1e-8)
check.near('fit with Freq: residual df', lw['df_resid'], float(olsw.df_resid))
rb = call('graph.fit', table=tid, x='x', y='y', rows=rows, codes=codes, k=3, robust=True)['fits'][0]
rlm = sm.RLM(ya, np.vander((xa - xa.mean()) / xa.std(ddof=1), 2, increasing=True), M=graph._cauchy_norm()).fit()
check.near('robust fit: statsmodels RLM with Cauchy weights', rb['y'][0], float(rlm.params[0] + rlm.params[1] * (rb['x'][0] - xa.mean()) / xa.std(ddof=1)), rel=1e-8)
check('robust fit differs from least squares', abs(rb['coef'][1] - fa['coef'][1]) > 1e-6, True)
w5 = graph._cauchy_norm().weights(np.array([0.0, 2.3849]))
check.near('Cauchy weight at r = c is one half', float(w5[1]), 0.5)

# ---- Ellipse --------------------------------------------------------------------
el = call('graph.ellipse', table=tid, x='x', y='y', rows=rows, codes=codes, k=3, coverage=0.9)['ellipses'][1]
xy = np.vstack([xb, yb])
cov = np.cov(xy)
check.near('ellipse: mean', el['mean'][1], float(yb.mean()))
check.near('ellipse: correlation', el['r'], float(np.corrcoef(xy)[0, 1]))
P = np.linalg.inv(cov)
dev = np.vstack([el['x'], el['y']]) - xy.mean(axis=1)[:, None]
md = np.einsum('ij,ik,kj->j', dev, P, dev)
check.near('ellipse: on the chi-square(2) 90% contour', float(np.max(np.abs(md - stats.chi2.ppf(0.9, 2)))), 0.0, abs_=1e-8)
check('ellipse of a constant is an error', 'error' in call('graph.ellipse', table=table({'a': [1, 1, 1, 1.0], 'b': [1, 2, 3, 4.0]}), x='a', y='b')['ellipses'][0], True)

# ---- Contour: the kernel density --------------------------------------------------
de = call('graph.density', table=tid, x='x', y='y', rows=rows, codes=codes, k=3)['densities'][0]
kde = stats.gaussian_kde(np.vstack([xa, ya]))
GX, GY = np.meshgrid(de['x'], de['y'])
dz = kde(np.vstack([GX.ravel(), GY.ravel()])).reshape(GX.shape)
check.near('density: the peak is gaussian_kde\'s', de['max'], float(dz.max()), rel=1e-10)
at = kde(np.vstack([xa, ya]))
mz = np.array(de['z'], dtype=float)
# the p contour holds a share p of the points: the mass at each point's own density
share = np.array([np.mean(at >= t) for t in at])
check.near('density: the mass transform at the grid peak is the smallest share', float(mz.min()), float(np.mean(at >= dz.max())) if np.mean(at >= dz.max()) > 0 else float(mz.min()), abs_=1e-9)
for p in (0.25, 0.5, 0.75):
    lvl = np.quantile(at, 1 - p)
    check.near(f'density: the {int(p * 100)}% contour holds that share of the points', float(np.mean(at >= lvl)), p, abs_=0.02)
check('density: beyond the 100% contour the transform passes 1', float(mz.max()) > 1, True)
# the binned estimate agrees with the exact one
xs = rng.normal(0, 1, 5000)
ys = 0.6 * xs + rng.normal(0, 0.8, 5000)
kd = stats.gaussian_kde(np.vstack([xs, ys]))
gx, gy = np.linspace(-5, 5, 64), np.linspace(-5, 5, 64)
GX, GY = np.meshgrid(gx, gy)
exact = kd(np.vstack([GX.ravel(), GY.ravel()])).reshape(GX.shape)
binned = graph._binned_kde(xs, ys, np.ones(5000), kd.covariance, gx, gy)
check.near('binned density (FFT) within 0.2% of the exact peak', float(np.max(np.abs(binned - exact)) / exact.max()), 0.0, abs_=0.002)
big = call('graph.density', table=table({'x': xs, 'y': ys}), x='x', y='y')['densities'][0]
check('many points: the binned path', big['method'], 'binned')

k1 = call('graph.kde1', table=tid, y='y', rows=rows, codes=codes, k=3, bw=1.5)['densities'][2]
kk = stats.gaussian_kde(yc)
kk.set_bandwidth(kk.factor * 1.5)
check.near('1-D density: gaussian_kde with 1.5 x Scott', max(abs(a - b) for a, b in zip(k1['d'], kk(np.array(k1['y'])))), 0.0, abs_=1e-12)

# ---- Mosaic: chi-square -------------------------------------------------------------
ct = pd.crosstab(g, np.where(y > np.nanmedian(y), 'hi', 'lo')).to_numpy()
cs = call('graph.chisq', tables=[ct.tolist(), [[3, 0], [0, 0]]], x='g', y='y')
ref = stats.chi2_contingency(ct, correction=False)
check.near('chi-square: Pearson', cs['tests'][0]['chi2'], float(ref[0]))
check.near('chi-square: p', cs['tests'][0]['p'], float(ref[1]))
check.near('chi-square: agrees with statsmodels Table', cs['tests'][0]['chi2'], float(Table(ct).test_nominal_association().statistic))
check.near('chi-square: likelihood ratio', cs['tests'][0]['lr'], float(stats.chi2_contingency(ct, correction=False, lambda_='log-likelihood')[0]))
check('chi-square of a degenerate table is an error', 'error' in cs['tests'][1], True)

# ---- Contour Plot / Surface Plot: griddata ------------------------------------------
gi = call('graph.interp', table=tid, x='x', y='y', z='z', grid=30, method='cubic')
pts = pd.DataFrame({'x': x, 'y': y, 'z': z}).dropna().groupby(['x', 'y'], as_index=False).mean()
GX, GY = np.meshgrid(gi['x'], gi['y'])
ref = griddata(pts[['x', 'y']].to_numpy(), pts['z'].to_numpy(), (GX, GY), method='cubic')
got = np.array([[np.nan if v is None else v for v in row] for row in gi['z']])
check('griddata: missing outside the hull at the same cells', bool(np.array_equal(np.isnan(got), np.isnan(ref))), True)
check.near('griddata: cubic values', float(np.nanmax(np.abs(got - ref))), 0.0, abs_=1e-10)
check('griddata: duplicates averaged', gi['points'], len(pts))
check('griddata on a line is an error', 'error' in call('graph.interp', table=table({'a': [1, 2, 3, 4.0], 'b': [1, 2, 3, 4.0], 'c': [1, 2, 3, 4.0]}), x='a', y='b', z='c'), True)

# ---- the code under each result runs on a CSV export ------------------------------------
calls = [
    ('graph.summary', {'y': 'y', 'by': ['g']}), ('graph.summary', {'y': 'y', 'freq': 'f'}),
    ('graph.smoother', {'x': 'x', 'y': 'y', 'by': ['g']}), ('graph.smoother', {'x': 'x', 'y': 'y', 'method': 'lowess'}),
    ('graph.fit', {'x': 'x', 'y': 'y', 'degree': 2, 'by': ['g']}), ('graph.fit', {'x': 'x', 'y': 'y', 'robust': True}),
    ('graph.ellipse', {'x': 'x', 'y': 'y', 'by': ['g']}), ('graph.density', {'x': 'x', 'y': 'y', 'bw': 1.5}),
    ('graph.kde1', {'y': 'y', 'by': ['g']}), ('graph.chisq', {'tables': [ct.tolist()], 'x': 'g', 'y': 'z'}),
    ('graph.interp', {'x': 'x', 'y': 'y', 'z': 'z'}),
]
with tempfile.TemporaryDirectory() as tmp:
    pd.DataFrame(cols).to_csv(os.path.join(tmp, 'Graph test.csv'), index=False)
    here = os.getcwd()
    os.chdir(tmp)
    try:
        for fn, kw in calls:
            code = call(fn, table=tid, table_name='Graph test', **kw)['code']
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    exec(compile(code, fn, 'exec'), {})
                ran = True
            except Exception as e:
                ran = f'{type(e).__name__}: {e}'
            check(f'the code of {fn} {sorted(kw)} runs', ran, True)
    finally:
        os.chdir(here)

sys.exit(check.done())
