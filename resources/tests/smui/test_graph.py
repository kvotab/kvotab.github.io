#!/usr/bin/env python3
"""Graph's backend (resources/py/smui/graph.py), checked against scipy and
statsmodels called directly: the summary statistics and JMP's quantiles
behind Bar, Line, Points and Box Plot, the Smoother (a smoothing spline on
standardized X, and lowess), Line of Fit with its bands, the density
ellipse, the kernel density contours, the chi-square of Mosaic, the
gridded surfaces of Contour Plot and Surface Plot, Bean's violins
(statsmodels' beanplot), and the Functional Data Plot: band depths
(statsmodels' banddepth, and the definitions counted by brute force),
fboxplot's order, regions and outliers, hdrboxplot's outliers, modal curve
and bands, compared with statsmodels' own figures where matplotlib is
installed (hdrboxplot's multiprocessing Pool made a plain map). The Python
code each result carries is run on a CSV export of the table, and for the
new results it must give the report's numbers.

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

# ---- Functional Data Plot and Bean: statsmodels' functional graphics ----------------------
# statsmodels draws fboxplot, hdrboxplot and beanplot with matplotlib; where it is installed
# they are run here (Agg), with hdrboxplot's multiprocessing Pool made a plain map (the same
# calls, one after the other), and the page's numbers are compared with theirs.
import itertools  # noqa: E402

import statsmodels.graphics.functional as smf_functional  # noqa: E402
from statsmodels.graphics.boxplots import _single_violin  # noqa: E402
from statsmodels.graphics.functional import banddepth  # noqa: E402
from statsmodels.multivariate.pca import PCA  # noqa: E402
from statsmodels.nonparametric.kernel_density import KDEMultivariate  # noqa: E402

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    HAVE_MPL = True
except ImportError:  # the checks against statsmodels' figures are then left out
    HAVE_MPL = False
    print('matplotlib is not installed: the checks against statsmodels\' own figures are left out')


class SerialPool:
    """hdrboxplot's Pool, as a plain map: the same calls in turn."""

    def __init__(self, *a, **k):
        pass

    def map(self, f, it):
        return list(map(f, it))

    def terminate(self):
        pass

    def close(self):
        pass


smf_functional.Pool = SerialPool


def curves_sim(n=60, p=24, seed=11, decimals=None):
    """Daily cycles with a random level, amplitude and peak, AR(1) noise, and
    six unusual curves (three in magnitude, three in shape)."""
    r = np.random.default_rng(seed)
    h = np.arange(p) * 24.0 / p
    X = np.empty((n, p))
    for i in range(n):
        level, amp, peak = r.normal(13.5, 1.2), max(1.5, r.normal(4.8, 0.6)), 15 + r.normal(0, 0.5)
        e = 0.0
        for j in range(p):
            e = 0.7 * e + r.normal(0, 0.22)
            X[i, j] = level + amp * np.cos(2 * np.pi * (h[j] - peak) / 24) + e
    X[6] += 9
    X[23] -= 8
    X[41] += 6.5
    X[13] -= 7 / (1 + np.exp(-(h - 13) / 0.7))
    X[30] = X[30].mean() + 4.5 * np.cos(2 * np.pi * (h - 3) / 24)
    X[52] = X[52].mean() + 0.5 * np.cos(2 * np.pi * (h - 15) / 24)
    return X.round(decimals) if decimals is not None else X


def wide_table(X, names=None, extra=None):
    names = names or [str(j) for j in range(X.shape[1])]
    cols = {nm: X[:, j] for j, nm in enumerate(names)}
    cols.update(extra or {})
    return table(cols), names


def bd2_definition(Y):
    """Lopez-Pintado and Romo's band depth, J = 2, by brute force: the share of
    the pairs of curves whose band holds the curve at every point."""
    n = len(Y)
    out = np.zeros(n)
    for i in range(n):
        for j, k in itertools.combinations(range(n), 2):
            lo, hi = np.minimum(Y[j], Y[k]), np.maximum(Y[j], Y[k])
            out[i] += np.all((Y[i] >= lo) & (Y[i] <= hi))
    return out / (n * (n - 1) / 2)


def mbd_definition(Y):
    n = len(Y)
    out = np.zeros(n)
    for i in range(n):
        for j, k in itertools.combinations(range(n), 2):
            lo, hi = np.minimum(Y[j], Y[k]), np.maximum(Y[j], Y[k])
            out[i] += np.mean((Y[i] >= lo) & (Y[i] <= hi))
    return out / (n * (n - 1) / 2)


X = curves_sim()
tw, hours = wide_table(X, extra={'day': [f'Day {i + 1:02d}' for i in range(len(X))], 'site': ['Coast' if i % 2 == 0 else 'Inland' for i in range(len(X))]})
fb = call('graph.fbox', table=tw, y=hours)
check('fbox: 60 curves at 24 points', (fb['n'], fb['p']), (60, 24))
check('fbox: X is the number in each column name', fb['x'][:3], [0.0, 1.0, 2.0])
check('fbox: a curve per row, its row', fb['rows'][:3], [[0], [1], [2]])
check('fbox: no ties in unrounded curves', fb['ties'], 0)
check.near('MBD: statsmodels\' banddepth itself', float(np.max(np.abs(np.array(fb['depth']) - banddepth(X, method='MBD')))), 0.0, abs_=1e-15)
f20 = call('graph.fbox', table=tw, y=hours, rows=list(range(20)))
check.near('MBD: the definition (the share of each band the curve is in, averaged over the points)', float(np.max(np.abs(np.array(f20['depth']) - mbd_definition(X[:20])))), 0.0, abs_=1e-12)
b2 = call('graph.fbox', table=tw, y=hours, method='BD2')
check.near('BD2: statsmodels\' banddepth itself', float(np.max(np.abs(np.array(b2['depth']) - banddepth(X, method='BD2')))), 0.0, abs_=1e-15)
bx = call('graph.fbox', table=tw, y=hours, method='BD2x')
check.near('BD2 counted: the definition, by brute force', float(np.max(np.abs(np.array(bx['depth']) - bd2_definition(X)))), 0.0, abs_=1e-12)
check('statsmodels\' BD2 is at least the counted band depth', bool(np.all(np.array(b2['depth']) >= np.array(bx['depth']) - 1e-12)), True)
check('statsmodels\' BD2 differs from the definition for some curves here', int(np.sum(np.abs(np.array(b2['depth']) - np.array(bx['depth'])) > 1e-12)) > 0, True)
# the smallest case where the rank formula counts a pair that makes no band around the curve
ce = np.array([[1.0, 1.0], [0.0, 2.0], [2.0, 0.0], [3.0, 3.0]])
tce, nce = wide_table(ce)
cc_sm, cc_ex = call('graph.fbox', table=tce, y=nce, method='BD2')['depth'][0], call('graph.fbox', table=tce, y=nce, method='BD2x')['depth'][0]
check('BD2 of four curves: statsmodels 5/6, the definition 4/6', (round(cc_sm, 12), round(cc_ex, 12)), (round(5 / 6, 12), round(4 / 6, 12)))
# ties: the counted depth takes a curve on a band's edge as in it
Xt = np.array([[0, 0, 0], [1, 1, 1], [1, 2, 1], [2, 2, 2], [0, 1, 2.0]])
tt_, ntt = wide_table(Xt)
check.near('BD2 counted with ties: the definition', float(np.max(np.abs(np.array(call('graph.fbox', table=tt_, y=ntt, method='BD2x')['depth']) - bd2_definition(Xt)))), 0.0, abs_=1e-12)
check('ties are counted: values equal to another at the same point', call('graph.fbox', table=tt_, y=ntt)['ties'], sum(5 - len(np.unique(Xt[:, j])) for j in range(3)))

# fboxplot's order, regions and outliers, against statsmodels' own
order = np.argsort(banddepth(X, 'MBD'))[::-1]
check('fbox: the order is fboxplot\'s (deepest first)', fb['order'], order.tolist())
check('fbox: the median is the deepest curve', fb['median'], int(order[0]))
central = X[order[:30]]
check.near('fbox: the 50% central region is the envelope of the 30 deepest (lower)', float(np.max(np.abs(np.array(fb['lower']) - central.min(axis=0)))), 0.0, abs_=1e-12)
check.near('fbox: ... (upper)', float(np.max(np.abs(np.array(fb['upper']) - central.max(axis=0)))), 0.0, abs_=1e-12)
m = np.median(central, axis=0)
hi_f = m + 1.5 * (central.max(axis=0) - m)
check.near('fbox: fboxplot\'s upper fence, the median plus 1.5 times its distance to the region\'s edge', float(np.max(np.abs(np.array(fb['fence_hi']) - hi_f))), 0.0, abs_=1e-12)
ranks = np.empty(60, int)
ranks[order] = np.arange(1, 61)
check('fbox: ranks, 1 the deepest', fb['rank'], ranks.tolist())
if HAVE_MPL:
    for meth, wf in (('MBD', 1.5), ('BD2', 1.5), ('MBD', 2.58)):
        fig, d_sm, ix_sm, out_sm = smf_functional.fboxplot(X, method=meth, wfactor=wf)
        plt.close(fig)
        r_ = call('graph.fbox', table=tw, y=hours, method=meth, wfactor=wf)
        check(f'fboxplot {meth}, wfactor {wf}: the same order', r_['order'], ix_sm.tolist())
        check(f'fboxplot {meth}, wfactor {wf}: the same outliers', [i for i, o in enumerate(r_['outlier']) if o], out_sm.tolist())
        check.near(f'fboxplot {meth}, wfactor {wf}: the same depths', float(np.max(np.abs(np.array(r_['depth']) - d_sm))), 0.0, abs_=1e-15)
    fig, ax = plt.subplots()
    smf_functional.fboxplot(X, method='MBD', wfactor=1.5, ax=ax)
    poly = [c for c in ax.collections if c.get_paths()]
    v_outer = poly[0].get_paths()[0].vertices
    check.near('fboxplot draws the same envelope of the non-outliers (its top at the first point)', float(np.max(v_outer[:, 1][np.isclose(v_outer[:, 0], 0)])), float(np.array(fb['env_hi'])[0]), rel=1e-12)
    plt.close(fig)
    fig, ax = plt.subplots()
    smf_functional.rainbowplot(X, method='MBD', ax=ax)
    check('rainbowplot draws the median last, the deepest curve', bool(np.allclose(ax.lines[-1].get_ydata(), X[fb['median']])), True)
    plt.close(fig)
if HAVE_MPL:
    # statsmodels problem: fboxplot colours its outliers by ii / (number of outliers - 1)
    X1 = np.random.default_rng(0).normal(0, 0.1, (30, 10)) + np.linspace(0, 1, 10)
    X1[4] += 3
    t1_, n1_ = wide_table(X1)
    one_ = call('graph.fbox', table=t1_, y=n1_, wfactor=4)
    try:
        smf_functional.fboxplot(X1, wfactor=4)
        fails = None
    except ZeroDivisionError:
        fails = 'ZeroDivisionError'
    plt.close('all')
    check('statsmodels\' fboxplot fails with exactly one outlier; the page draws it, and its code says so', (fails, [i for i, o in enumerate(one_['outlier']) if o], 'ZeroDivisionError' in one_['code']), ('ZeroDivisionError', [4], True))
out_sm15 = [i for i, o in enumerate(fb['outlier']) if o]
check('fboxplot\'s fences at 1.5 flag many curves (a third or more here)', len(out_sm15) >= 15, True)
sg = call('graph.fbox', table=tw, y=hours, rule='sungenton')
rng_ = central.max(axis=0) - central.min(axis=0)
check.near('Sun and Genton\'s fences: the envelope plus 1.5 times its range', float(np.max(np.abs(np.array(sg['fence_hi']) - (central.max(axis=0) + 1.5 * rng_)))), 0.0, abs_=1e-12)
out_sg = [i for i, o in enumerate(sg['outlier']) if o]
check('Sun and Genton\'s fences flag the magnitude outliers', all(i in out_sg for i in (6, 23)), True)
check('Sun and Genton\'s fences flag few curves', len(out_sg) <= 8, True)
keep = ~np.array(fb['outlier'])
check.near('fbox: the envelope of the non-outlying curves', float(np.max(np.abs(np.array(fb['env_lo']) - X[keep].min(axis=0)))), 0.0, abs_=1e-12)

# the curves from other layouts
names = ['week 3', 'week 1', 'week 2', 'week 10']
Xs = X[:10, :4]
t4, _ = wide_table(Xs, names=names)
w4 = call('graph.fbox', table=t4, y=names)
check('X from names: the columns in the order of their numbers', (w4['x'], w4['names']), ([1.0, 2.0, 3.0, 10.0], ['week 1', 'week 2', 'week 3', 'week 10']))
check('X from names: a note that the order changed', any('order of the numbers' in s for s in w4['notes']), True)
check.near('X from names: the curves reordered with them', float(np.max(np.abs(np.array(w4['curves']) - Xs[:, [1, 2, 0, 3]]))), 0.0, abs_=1e-15)
t5, _ = wide_table(Xs, names=['a', 'b', 'c', 'd'])
w5 = call('graph.fbox', table=t5, y=['a', 'b', 'c', 'd'])
check('names without numbers: X is the column order, with a note', (w5['x'], w5['source'], bool(w5['notes'])), ([1.0, 2.0, 3.0, 4.0], 'order', True))
check('X Values, Column Order: the order even for number names', call('graph.fbox', table=t4, y=names, xmode='order')['x'], [1.0, 2.0, 3.0, 4.0])
Xm = X[:12, :5].copy()
Xm[3, 2] = np.nan
t6, n6 = wide_table(Xm)
w6 = call('graph.fbox', table=t6, y=n6)
check('a row with a missing value is left out', (w6['n'], w6['dropped'], [3] in w6['rows']), (11, 1, False))
check('rows: only some rows (a By group)', call('graph.fbox', table=tw, y=hours, rows=list(range(0, 60, 2)))['rows'][:3], [[0], [2], [4]])
check('fewer than three curves: an error, not a failure', 'error' in call('graph.fbox', table=tw, y=hours, rows=[0, 1]), True)
# stacked: the same curves as rows, with an ID, X and Y column (rows shuffled)
L = [(i, float(j), X[i, j]) for i in range(20) for j in range(24)]
perm = rng.permutation(len(L))
ids_l = [f'c{L[k][0]:02d}' for k in perm]
tl = table({'id': ids_l, 'x': [L[k][1] for k in perm], 'y': [L[k][2] for k in perm]})
lg = call('graph.fbox', table=tl, layout='long', id='id', x='x', y='y')
check('stacked: a curve per ID, at the X they share', (lg['n'], lg['p'], lg['interp']), (20, 24, None))
check.near('stacked: the same depths as the rows (statsmodels\' MBD)', float(np.max(np.abs(np.array(lg['depth']) - banddepth(X[:20], 'MBD')))), 0.0, abs_=1e-15)
check('stacked: each curve\'s rows', sorted(lg['rows'][0]) == sorted(k for k, q in enumerate(perm) if L[q][0] == 0), True)
# stacked at different X: interpolated to common points over the range every curve covers
rr = np.random.default_rng(5)
xs_i = [np.sort(rr.uniform(0, 24, 30 + i % 7)) for i in range(15)]
ys_i = [np.sin(xx / 4) + 0.1 * i for i, xx in enumerate(xs_i)]
tl2 = table({'id': [f'k{i}' for i, xx in enumerate(xs_i) for _ in xx], 'x': np.concatenate(xs_i), 'y': np.concatenate(ys_i)})
lg2 = call('graph.fbox', table=tl2, layout='long', id='id', x='x', y='y')
lo, hi = max(xx.min() for xx in xs_i), min(xx.max() for xx in xs_i)
npts = int(np.median([len(xx) for xx in xs_i]))
check('stacked at different X: interpolated to the median count of points over the common range', (lg2['interp']['points'], round(lg2['interp']['lo'], 12), round(lg2['interp']['hi'], 12)), (npts, round(lo, 12), round(hi, 12)))
grid_ = np.linspace(lo, hi, npts)
id_of_row = [i for i, xx in enumerate(xs_i) for _ in xx]
worst = max(float(np.max(np.abs(np.array(cv) - np.interp(grid_, xs_i[id_of_row[rs[0]]], ys_i[id_of_row[rs[0]]])))) for cv, rs in zip(lg2['curves'], lg2['rows']))
check.near('stacked at different X: numpy.interp of each curve', worst, 0.0, abs_=1e-12)
# stacked without X: the order of each ID's rows; values at the same X averaged
tl3 = table({'id': ['a', 'a', 'a', 'b', 'b', 'b', 'c', 'c', 'c'], 'y': [1, 2, 3, 2, 3, 4, 0, 5, 1.0]})
lg3 = call('graph.fbox', table=tl3, layout='long', id='id', y='y')
check('stacked without X: X is the order of the rows', (lg3['x'], lg3['curves'][2]), ([1.0, 2.0, 3.0], [0.0, 5.0, 1.0]))
tl4 = table({'id': ['a', 'a', 'a', 'b', 'b', 'c', 'c'], 'x': [1, 1, 2, 1, 2, 1, 2.0], 'y': [1, 3, 5, 2, 4, 0, 1.0]})
lg4 = call('graph.fbox', table=tl4, layout='long', id='id', x='x', y='y')
check('stacked: values at the same X averaged', (lg4['averaged'], lg4['curves'][0]), (True, [2.0, 5.0]))
check('stacked: curves in the ID column\'s level order', call('graph.fbox', table=table({'id': ['b', 'b', 'a', 'a', 'c', 'c'], 'y': [1, 2, 3, 4, 5, 6.0]}, levels={'id': ['c', 'a', 'b']}), layout='long', id='id', y='y')['curves'], [[5.0, 6.0], [3.0, 4.0], [1.0, 2.0]])

# ---- the HDR boxplot ---------------------------------------------------------------------------
hd = call('graph.hdr', table=tw, y=hours)
pca = PCA(X, ncomp=2)
S = np.asarray(pca.factors)
ks = KDEMultivariate(S, bw='normal_reference', var_type='cc')
dens = ks.pdf(S)
check.near('HDR: the scores are statsmodels PCA\'s factors (two, each point standardized)', float(np.max(np.abs(np.array(hd['scores']) - S))), 0.0, abs_=1e-12)
check.near('HDR: the density at each curve is KDEMultivariate\'s', float(np.max(np.abs(np.array(hd['density']) - dens))), 0.0, abs_=1e-12)
check.near('HDR: the normal reference bandwidths', float(np.max(np.abs(np.array(hd['bw']) - ks.bw))), 0.0, abs_=1e-15)
for a, key in ((0.5, '50'), (0.9, '90'), (0.95, 'threshold')):
    check.near(f'HDR: the level of the {key} region, numpy\'s midpoint percentile', hd['levels'][key], float(np.percentile(dens, 100 * (1 - a), method='midpoint')), rel=1e-12)
check('HDR: the outliers, density below the 5th percentile', [i for i, o in enumerate(hd['outlier']) if o], np.where(dens < np.percentile(dens, 5, method='midpoint'))[0].tolist())
check('HDR: about 5% of the curves are outliers', sum(hd['outlier']), 3)
check.near('HDR: the share of the variance', hd['explained'][0], float(pca.rsquare[1]), rel=1e-12)
pts = np.random.default_rng(3).uniform(S.min(axis=0), S.max(axis=0), size=(40, 2))
check.near('the vectorized density is KDEMultivariate\'s', float(np.max(np.abs(graph._kde_at(S, ks.bw, pts) - ks.pdf(pts)) / ks.pdf(pts))), 0.0, abs_=1e-12)
a0 = smf_functional._inverse_transform(pca, np.asarray(hd['mode'])[None])[0]
check.near('HDR: the modal curve is the curve rebuilt from the mode', float(np.max(np.abs(np.array(hd['modal']) - a0))), 0.0, abs_=1e-10)
check('HDR: the mode is the density\'s highest point on a fine grid', float(ks.pdf(np.asarray(hd['mode'])[None])) >= float(np.max(graph._kde_at(S, ks.bw, np.c_[[g.ravel() for g in np.meshgrid(np.linspace(*S[:, 0][[S[:, 0].argmin(), S[:, 0].argmax()]], 301), np.linspace(*S[:, 1][[S[:, 1].argmin(), S[:, 1].argmax()]], 301), indexing='ij')]].T))) - 1e-9, True)
up50, lo50 = np.array(hd['hdr50'][0]), np.array(hd['hdr50'][1])
up90, lo90 = np.array(hd['hdr90'][0]), np.array(hd['hdr90'][1])
width = float(np.min(up90 - lo90))
check('HDR: the 50% band lies inside the 90% band', bool(np.all(up50 <= up90 + 1e-9) and np.all(lo50 >= lo90 - 1e-9)), True)
# the bands by a much finer grid, taking only its points (no contour crossings)
fine = call('graph.hdr', table=tw, y=hours, grid=401)
check.near('HDR bands: a 401 x 401 grid agrees within 0.1% of the band width', float(max(np.max(np.abs(np.array(fine['hdr90'][0]) - up90)), np.max(np.abs(np.array(fine['hdr50'][1]) - lo50)))) / width, 0.0, abs_=1e-3)
if HAVE_MPL:
    for seed in (1, None):
        fig, res = smf_functional.hdrboxplot(X, seed=seed)
        plt.close(fig)
        tag = 'brute force (a seed given)' if seed else 'differential evolution (no seed)'
        check(f'hdrboxplot, {tag}: the same outliers', res.outliers_idx.tolist(), [i for i, o in enumerate(hd['outlier']) if o])
        check.near(f'hdrboxplot, {tag}: the same modal curve', float(np.max(np.abs(res.median - np.array(hd['modal'])))) / width, 0.0, abs_=1e-4)
        sm50, sm90 = np.array(res.hdr_50), np.array(res.hdr_90)
        inside = min(float(np.min(up50 - sm50[0])), float(np.min(sm50[1] - lo50)), float(np.min(up90 - sm90[0])), float(np.min(sm90[1] - lo90)))
        check(f'hdrboxplot, {tag}: its bands lie within the page\'s (to 0.5% of the width)', inside >= -0.005 * width, True)
        far = max(float(np.max(np.abs(up50 - sm50[0]))), float(np.max(np.abs(lo50 - sm50[1]))), float(np.max(np.abs(up90 - sm90[0]))), float(np.max(np.abs(lo90 - sm90[1]))))
        check(f'hdrboxplot, {tag}: and close to them (within 10% of the width)', far <= 0.10 * width, True)
    # statsmodels problem: _band_quantiles passes (seed, use_brute) to _min_max_band, which reads (use_brute, seed)
    _, r1 = smf_functional.hdrboxplot(X, seed=1)
    _, r2 = smf_functional.hdrboxplot(X, seed=12345)
    check('statsmodels: any seed gives the same bands (the seed turns on the brute-force search)', bool(np.array_equal(r1.hdr_50, r2.hdr_50) and np.array_equal(r1.hdr_90, r2.hdr_90)), True)
    _, r3 = smf_functional.hdrboxplot(X, use_brute=True)
    check('statsmodels: use_brute=True does not search by brute force', bool(np.array_equal(r3.hdr_50, r1.hdr_50)), False)
    plt.close('all')
h9 = call('graph.hdr', table=tw, y=hours, threshold=0.9)
check('HDR: threshold 0.9, density below the 10th percentile', [i for i, o in enumerate(h9['outlier']) if o], np.where(dens < np.percentile(dens, 10, method='midpoint'))[0].tolist())
hc = call('graph.hdr', table=tw, y=hours, bw='cv_ml')
check.near('HDR: cross-validated bandwidths, KDEMultivariate\'s', float(np.max(np.abs(np.array(hc['bw']) - KDEMultivariate(S, bw='cv_ml', var_type='cc').bw))), 0.0, abs_=1e-10)
Xc = X.copy()
Xc[:, 0] = 5.0
tcst, _ = wide_table(Xc)
hcst = call('graph.hdr', table=tcst, y=hours)
try:
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        PCA(Xc, ncomp=2)
    pca_fails = False
except Exception:
    pca_fails = True
check('a point where every curve is the same: statsmodels\' PCA fails on it', pca_fails, True)
check('... the page leaves it out of the PCA and keeps its value', (hcst.get('error'), hcst['constant'], hcst['hdr50'][0][0], hcst['modal'][0]), (None, 1, 5.0, 5.0))
check.near('... and the rest is the HDR boxplot of the other points', float(np.max(np.abs(np.array(hcst['density']) - KDEMultivariate(np.asarray(PCA(Xc[:, 1:], ncomp=2).factors), bw='normal_reference', var_type='cc').pdf(np.asarray(PCA(Xc[:, 1:], ncomp=2).factors))))), 0.0, abs_=1e-12)
check('fewer than five curves: an error', 'error' in call('graph.hdr', table=tw, y=hours, rows=[0, 1, 2, 3]), True)
hlong = call('graph.hdr', table=tl, layout='long', id='id', x='x', y='y')
check.near('HDR of stacked curves: the same as of the rows', float(np.max(np.abs(np.array(hlong['density']) - KDEMultivariate(np.asarray(PCA(X[:20], ncomp=2).factors), bw='normal_reference', var_type='cc').pdf(np.asarray(PCA(X[:20], ncomp=2).factors))))), 0.0, abs_=1e-12)

# ---- Bean: statsmodels' beanplot ---------------------------------------------------------------------
class NoAxes:
    def fill_betweenx(self, *a, **k):
        return None


vb = y.copy()
ok_b = np.isfinite(vb)
be = call('graph.bean', table=tid, y='y', rows=rows, codes=codes, k=3, by=['g'])
for i, level in enumerate(lv):
    v = sub(y, level)
    grid_b, viol = _single_violin(NoAxes(), 0.0, v, 1.0, 'both', {})
    check.near(f'bean {level}: statsmodels\' violin grid (100 points, 1.5 sd past the data)', float(np.max(np.abs(np.array(be['beans'][i]['y']) - grid_b))), 0.0, abs_=1e-12)
    check.near(f'bean {level}: statsmodels\' violin, scaled to its peak', float(np.max(np.abs(np.array(be['beans'][i]['d']) - viol))), 0.0, abs_=1e-12)
    kd = stats.gaussian_kde(v)
    gg = np.linspace(v.min() - 1.5 * v.std(), v.max() + 1.5 * v.std(), 100)
    check.near(f'bean {level}: the published recipe (gaussian_kde, Scott)', float(np.max(np.abs(np.array(be['beans'][i]['d']) - kd(gg) / kd(gg).max()))), 0.0, abs_=1e-12)
    check.near(f'bean {level}: the mean line', be['beans'][i]['mean'], float(v.mean()))
    check.near(f'bean {level}: the median mark', be['beans'][i]['median'], float(np.median(v)))
if HAVE_MPL:
    groups = [sub(y, level) for level in lv]
    fig, ax = plt.subplots()
    sm.graphics.beanplot(groups, ax=ax)
    polys = [c for c in ax.collections if type(c).__name__ in ('PolyCollection', 'FillBetweenPolyCollection')]
    width_b = min(0.15 * max(2, 1.0), 0.4)
    worst = 0.0
    for i, pc in enumerate(polys[:3]):
        vtx = pc.get_paths()[0].vertices
        right = vtx[vtx[:, 0] >= i + 1]
        dd = np.interp(right[:, 1], be['beans'][i]['y'], be['beans'][i]['d'])
        worst = max(worst, float(np.max(np.abs(right[:, 0] - (i + 1) - width_b * dd))))
    check.near('beanplot draws the page\'s violins (its polygons, three groups)', worst, 0.0, abs_=1e-9)
    plt.close(fig)
bw15 = call('graph.bean', table=tid, y='y', rows=rows, codes=codes, k=3, bw=1.5, cutoff=True)['beans'][0]
va = sub(y, 'a')
kd = stats.gaussian_kde(va, bw_method=lambda k: k.scotts_factor() * 1.5)
gg = np.linspace(va.min(), va.max(), 100)
check.near('bean: bandwidth scale 1.5 and cut at the data', float(np.max(np.abs(np.array(bw15['d']) - kd(gg) / kd(gg).max()))), 0.0, abs_=1e-12)
check('bean: cut at the data, the grid ends at the data', (bw15['y'][0], bw15['y'][-1]), (float(va.min()), float(va.max())))
bf = call('graph.bean', table=tid, y='y', rows=rows, codes=codes, k=3, freq='f', by=['g'])['beans'][0]
rep_a = np.repeat(va, sub(f, 'a').astype(int))
check.near('bean with Freq: the rows repeated (statsmodels\' violin)', float(np.max(np.abs(np.array(bf['d']) - _single_violin(NoAxes(), 0.0, rep_a, 1.0, 'both', {})[1]))), 0.0, abs_=1e-12)
check.near('bean with Freq: n is the sum of Freq', bf['n'], float(sub(f, 'a').sum()))
fw = f * 0.5
tfw = table({'y': y, 'g': g.tolist(), 'w': fw})
bw_ = call('graph.bean', table=tfw, y='y', rows=rows, codes=codes, k=3, freq='w')['beans'][0]
kdw = stats.gaussian_kde(va, weights=sub(fw, 'a'))
mw = float(np.average(va, weights=sub(fw, 'a')))
sw_ = 1.5 * float(np.sqrt(np.average((va - mw) ** 2, weights=sub(fw, 'a'))))
gw = np.linspace(va.min() - sw_, va.max() + sw_, 100)
check.near('bean with a fractional Freq: the weighted density', float(np.max(np.abs(np.array(bw_['d']) - kdw(gw) / kdw(gw).max()))), 0.0, abs_=1e-12)
check.near('bean with a fractional Freq: the weighted mean', bw_['mean'], mw)
one = call('graph.bean', table=tid, y='y', rows=[0, 1, 2], codes=[0, 1, 1], k=2)['beans']
check('bean: one value, the marks without a violin', ('error' in one[0], one[0]['n'], one[0]['mean'] == y[0]), (True, 1.0, True))

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

# ---- the code of the Functional Data Plot and of Bean gives the report's numbers --------------------
def run_code(code, files):
    """Run a result's code where the CSV exports are; its variables back."""
    with tempfile.TemporaryDirectory() as tmp:
        for name, frame in files.items():
            frame.to_csv(os.path.join(tmp, f'{name}.csv'), index=False)
        here = os.getcwd()
        os.chdir(tmp)
        ns = {}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(code, 'code', 'exec'), ns)
        except Exception as e:
            ns = {'_error': f'{type(e).__name__}: {e}'}
        finally:
            os.chdir(here)
    return ns


wide_csv = pd.DataFrame({**{h: X[:, j] for j, h in enumerate(hours)}, 'day': [f'Day {i + 1:02d}' for i in range(len(X))], 'site': ['Coast' if i % 2 == 0 else 'Inland' for i in range(len(X))]})
cases = [
    ('fbox, rows as functions', 'graph.fbox', dict(table=tw, y=hours), {'Curves': wide_csv}),
    ('fbox, BD2 counted, Sun and Genton', 'graph.fbox', dict(table=tw, y=hours, method='BD2x', rule='sungenton', wfactor=1.2), {'Curves': wide_csv}),
    ('fbox, stacked', 'graph.fbox', dict(table=tl, layout='long', id='id', x='x', y='y'), {'Curves': pd.DataFrame({'id': ids_l, 'x': [L[k][1] for k in perm], 'y': [L[k][2] for k in perm]})}),
    ('fbox, stacked at different X', 'graph.fbox', dict(table=tl2, layout='long', id='id', x='x', y='y'), {'Curves': pd.DataFrame({'id': [f'k{i}' for i, xx in enumerate(xs_i) for _ in xx], 'x': np.concatenate(xs_i), 'y': np.concatenate(ys_i)})}),
    ('fbox, stacked without X', 'graph.fbox', dict(table=tl3, layout='long', id='id', y='y'), {'Curves': pd.DataFrame({'id': ['a', 'a', 'a', 'b', 'b', 'b', 'c', 'c', 'c'], 'y': [1, 2, 3, 2, 3, 4, 0, 5, 1.0]})}),
    ('hdr, rows as functions', 'graph.hdr', dict(table=tw, y=hours), {'Curves': wide_csv}),
    ('hdr, a constant point', 'graph.hdr', dict(table=tcst, y=hours), {'Curves': pd.DataFrame({h: Xc[:, j] for j, h in enumerate(hours)})}),
]
for label, fn, kw, files in cases:
    res = call(fn, table_name='Curves', **kw)
    ns = run_code(res['code'], files)
    if '_error' in ns:
        check(f'the code of {label} runs', ns['_error'], True)
        continue
    out = ns['res']
    if fn == 'graph.fbox':
        check.near(f'the code of {label}: the depths', float(np.max(np.abs(np.asarray(out['depth']) - np.array(res['depth'])))), 0.0, abs_=1e-12)
        check(f'the code of {label}: the outliers', np.asarray(out['outlier']).tolist(), res['outlier'])
        check(f'the code of {label}: the median', int(out['median']), res['median'])
    else:
        check(f'the code of {label}: the outliers', np.asarray(out['outlier']).tolist(), res['outlier'])
        check.near(f'the code of {label}: the modal curve', float(np.max(np.abs(np.asarray(out['modal']) - np.array(res['modal'])))), 0.0, abs_=1e-7)
        worst = max(float(np.max(np.abs(np.asarray(out[k][j]) - np.array(res[k][j])))) for k in ('hdr50', 'hdr90') for j in (0, 1))
        check.near(f'the code of {label}: the bands', worst, 0.0, abs_=1e-9)
# By: the code loops over the groups; its last is the report of the last group
inland = [i for i in range(60) if i % 2 == 1]
for fn in ('graph.fbox', 'graph.hdr'):
    res = call(fn, table=tw, y=hours, rows=inland, by=['site'], table_name='Curves')
    ns = run_code(res['code'], {'Curves': wide_csv})
    if '_error' in ns:
        check(f'the code of {fn} with By runs', ns['_error'], True)
        continue
    check(f'the code of {fn} with By: the last group (Inland) as its report', np.asarray(ns['res']['outlier']).tolist(), res['outlier'])
    if fn == 'graph.fbox':
        check.near('the code of graph.fbox with By: its depths', float(np.max(np.abs(np.asarray(ns['res']['depth']) - np.array(res['depth'])))), 0.0, abs_=1e-12)
bean_csv = pd.DataFrame(cols)
res = call('graph.bean', table=tid, y='y', rows=[r for r in rows if g[r] == 'b'], table_name='Beans')
ns = run_code(res['code'], {'Beans': bean_csv[bean_csv['g'] == 'b'].reset_index(drop=True)})
check.near('the code of graph.bean: its violin', float(np.max(np.abs(ns.get('violin', np.zeros(1)) - np.array(res['beans'][0]['d'])))) if 'violin' in ns else 1.0, 0.0, abs_=1e-12)
res = call('graph.bean', table=tid, y='y', rows=rows, codes=codes, k=3, by=['g'], bw=1.3, cutoff=True, table_name='Beans')
ns = run_code(res['code'], {'Beans': bean_csv})
check('the code of graph.bean with By runs', ns.get('_error', True), True)
check.near('the code of graph.bean with By: the last group\'s violin (c)', float(np.max(np.abs(ns['violin'] - np.array(res['beans'][2]['d'])))) if 'violin' in ns else 1.0, 0.0, abs_=1e-12)
res = call('graph.bean', table=tid, y='y', rows=rows, codes=codes, k=3, by=['g'], freq='f', table_name='Beans')
ns = run_code(res['code'], {'Beans': bean_csv})
check.near('the code of graph.bean with Freq: the rows repeated', float(np.max(np.abs(ns['violin'] - np.array(res['beans'][2]['d'])))) if 'violin' in ns else 1.0, 0.0, abs_=1e-12)

# ---- a date column: text in the CSV, a number (ms since 1970) in the page ---------------------------------
# The code turns it back into the number before it computes (util.dated_code),
# so the smoother's code on the CSV as the page exports it gives the page's curve.
import contextlib, io, os, tempfile  # noqa: E401,E402
from smui import data as _data  # noqa: E402
from smui.util import dated_code  # noqa: E402
days = np.array([np.datetime64('1980-01-01') + np.timedelta64(91 * i, 'D') for i in range(40)])
ms_ = (days - np.datetime64('1970-01-01')).astype('timedelta64[ms]').astype(float)
out_ = 100 + np.cumsum(np.random.default_rng(5).normal(1, 0.5, 40))
tq = table({'quarter': ms_, 'output': out_})
_data.TABLES[tq]['meta']['quarter']['format'] = {'kind': 'date'}
for xn, yn in (('output', 'quarter'), ('quarter', 'output')):
    r_ = call('graph.smoother', table=tq, x=xn, y=yn, lam=0.05, table_name='Cycle')
    code_ = r_['code']
    with tempfile.TemporaryDirectory() as tmp:
        pd.DataFrame({'quarter': [str(d) for d in days], 'output': out_}).to_csv(os.path.join(tmp, 'Cycle.csv'), index=False)
        here = os.getcwd()
        os.chdir(tmp)
        ns_ = {}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                exec(code_, ns_)
            err_ = None
        except Exception as e_:   # the check says it
            err_ = f'{type(e_).__name__}: {e_}'
        finally:
            os.chdir(here)
    check(f'a date on {"Y" if yn == "quarter" else "X"}: the code turns the date back into its number', ('pd.to_datetime(df["quarter"])' in code_, err_), (True, None))
    if err_ is None:
        cv = r_['curves'][0]
        check.near(f'... and gives the page\'s curve (its first point, date on {"Y" if yn == "quarter" else "X"})', float(ns_['spline']((ns_['grid'][0] - ns_['m']) / ns_['s'])), cv['y'][0], rel=1e-9)
check('code that parses the date itself (a Time ID) is left to do so', dated_code('df = pd.read_csv("a.csv")\ndf["t"] = pd.to_datetime(df["t"])', ['t']), 'df = pd.read_csv("a.csv")\ndf["t"] = pd.to_datetime(df["t"])')
check('... and code that does not use the date column gets no line', dated_code('df = pd.read_csv("a.csv")\nx = df["y"]', ['t']), 'df = pd.read_csv("a.csv")\nx = df["y"]')
check('... a second pass adds nothing', dated_code(dated_code('df = pd.read_csv("a.csv")\nx = df["t"]', ['t']), ['t']).count('to_datetime'), 1)

sys.exit(check.done())
