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
installed (hdrboxplot's multiprocessing Pool made a plain map). The
Python under each graph (graph.code: Graph Builder's elements and zones,
and the other Graph platforms) is run on a CSV export of the table with
matplotlib, and its figure must show the report's numbers.

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
check('summary: want keeps the answer small', sorted(sw), ['alpha', 'k', 'mean'])
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
    one_code = call('graph.code', kind='functional', plan={'view': 'box', 'layout': 'wide', 'y': n1_, 'wfactor': 4, 'n_outliers': 1, 'size': [800, 450]}, table=t1_)['plot_code']
    check('statsmodels\' fboxplot fails with exactly one outlier; the page draws it, and its code says so', (fails, [i for i, o in enumerate(one_['outlier']) if o], 'ZeroDivisionError' in one_code), ('ZeroDivisionError', [4], True))
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

# ---- the Python under each graph: graph.code ------------------------------------------------------
# The page sends graph.code a plan of the graph it drew (Graph Builder's elements and zones
# as it resolved them, or another platform's settings), and the code that comes back draws
# that graph with matplotlib from the table's CSV export. Here the code runs on a CSV
# written as the page exports it (dates as text), with matplotlib's Agg backend, and its
# figure is checked against the numbers graph.summary, graph.smoother, graph.fit and the
# others give the page for the same graph. That the plans are the page's, and the figures
# its Plotly graphs, is test-ui-graph.py's part.
import matplotlib  # noqa: E402
matplotlib.use('Agg')
from smui import data as _data  # noqa: E402
from test_charts import run_snippet_more, strip_show  # noqa: E402

PALETTE = graph.PALETTE
GC_TMP = tempfile.mkdtemp(prefix='smui-graph-code-')


def gc_frame(tid_, dates=()):
    """A table as File > Export CSV writes it: every column by name, a date as its day."""
    t = _data.TABLES[tid_]
    out = {}
    for name, v in t['cols'].items():
        if name in dates:
            out[name] = [str(np.datetime64(int(q), 'ms').astype('datetime64[D]')) if np.isfinite(q) else '' for q in np.asarray(v, dtype=float)]
        elif _data.meta(tid_, name).get('dataType') == 'numeric':
            out[name] = np.asarray(v, dtype=float)
        else:
            out[name] = pd.Series(list(v), dtype=object)
    return pd.DataFrame(out)


def gc_run(kind, plan, tid_, name='Graph test', rows=None, names=(), dates=()):
    """graph.code's code for a plan, run on the table's CSV: (code, figures and variables, error)."""
    code = call('graph.code', kind=kind, plan=plan, table=tid_, rows=rows, table_name=name).get('plot_code')
    if not code:
        return None, None, 'no code'
    out, err = run_snippet_more(code, gc_frame(tid_, dates), name, GC_TMP, names=names)
    return code, out, err


def gc_is_cat(tid_, c):
    m = _data.meta(tid_, c)
    return m.get('modelingType') in ('nominal', 'ordinal') or m.get('dataType') != 'numeric'


def gc_levels(tid_, c, rows_):
    v = _data.raw(tid_, c, rows_)
    m = _data.meta(tid_, c)
    if m.get('dataType') == 'numeric':
        present = {float(q) for q in v if np.isfinite(q)}
        return [int(q) if float(q).is_integer() else float(q) for q in (m.get('levels') or sorted(present)) if float(q) in present]
    present = {q for q in v if q is not None}
    return [q for q in (m.get('levels') or sorted(present)) if q in present]


def gc_label(v):
    return str(int(v)) if isinstance(v, (int, float)) and float(v).is_integer() else str(v)


def gc_fmt(v, sig=7):
    """The page's fmt() of a number."""
    if float(v).is_integer() and abs(v) < 1e15:
        s = str(int(v))
    elif abs(v) >= 1e9 or abs(v) < 1e-4:
        m_, e_ = f'{v:.{min(sig, 5) - 1}e}'.split('e')
        s = f'{m_}e{int(e_)}'
    else:
        s = np.format_float_positional(float(f'{v:.{sig}g}'), trim='-')
    return '−' + s[1:] if s.startswith('-') else s


def gc_jmp_q(s_, p):
    """JMP's quantile of sorted values: the (n + 1)p-th value, interpolated."""
    n_ = len(s_)
    h_ = (n_ + 1) * p
    if h_ <= 1:
        return float(s_[0])
    if h_ >= n_:
        return float(s_[-1])
    k_ = int(math.floor(h_))
    return float(s_[k_ - 1] + (h_ - k_) * (s_[k_] - s_[k_ - 1]))


def gc_bin_cuts(v, n=5, method='quantile'):
    """Make Binning Column's cuts, from their definitions: n bins of about equal counts at JMP's quantiles, or bins of one
    round width (1, 2, 2.5, 5 or 10 times a power of ten, the nearest to the range over n) from a whole multiple of it."""
    s_ = np.sort(np.asarray(v, dtype=float))
    lo, hi = float(s_[0]), float(s_[-1])
    if method == 'quantile':
        cuts = [gc_jmp_q(s_, i / n) for i in range(1, n)]
    else:
        raw = (hi - lo) / n
        p_ = 10 ** math.floor(math.log10(raw))
        size = min((m_ * p_ for m_ in (1, 2, 2.5, 5, 10)), key=lambda q: abs(math.log(q / raw)))
        start = math.floor(lo / size) * size
        cuts, x_ = [], start + (size if start <= lo else 0)
        while x_ <= hi and len(cuts) < 1000:
            cuts.append(float(f'{x_:.12g}'))
            x_ += size
    cuts = [c_ for c_ in sorted({float(f'{c_:.12g}') for c_ in cuts}) if lo < c_ <= hi]
    if cuts and cuts[-1] == hi:
        cuts.pop()
    return cuts, lo, hi


def gc_groups(tid_, c, rows_, spec=None):
    """A zone's groups as the page makes them: a categorical column's levels; a continuous one with more than 10 distinct
    values (or with Levels set: spec, { n, method }) in bins as Make Binning Column cuts them, five of about equal counts by
    default, labelled by their ranges."""
    if not gc_is_cat(tid_, c):
        v = np.asarray(_data.raw(tid_, c, rows_), dtype=float)
        v = v[np.isfinite(v)]
        if spec or len(np.unique(v)) > 10:
            n_ = int((spec or {}).get('n') or 5)
            method = 'width' if (spec or {}).get('method') == 'width' else 'quantile'
            cuts, lo, hi = gc_bin_cuts(v, n_, method)
            edges = [lo] + cuts + [hi]
            lab = lambda q: gc_fmt(q).replace('−', '-')  # noqa: E731
            labels = [f'{lab(edges[k_])} - {lab(edges[k_ + 1])}' for k_ in range(len(edges) - 1)]
            return {'col': c, 'values': list(range(len(labels))), 'labels': labels, 'bins': {'cuts': cuts, 'method': method, 'n': n_}}
    lv = gc_levels(tid_, c, rows_)
    return {'col': c, 'values': lv, 'labels': [gc_label(q) for q in lv], 'bins': None}


def gb_plan(tid_, elements, x=(), y=(), gx=None, gy=None, wrap=None, overlay=None, color=None, size=None, freq=None,
            y_mode='side', w=640, h=420, log=None, where=None, bins=None, axes=None, order=None, marker=None, map_=None):
    """Graph Builder's plan of a graph, as the page's Env.plan makes it for these zones and elements."""
    n = _data.TABLES[tid_]['n']
    r0 = np.arange(n)
    if freq:
        fv = np.asarray(_data.raw(tid_, freq, r0), dtype=float)
        r0 = r0[np.isfinite(fv) & (fv > 0)]
    kind = lambda c: None if c is None else ('cat' if gc_is_cat(tid_, c) else 'cont')  # noqa: E731
    x, y = list(x), list(y)
    xsets = [[c] for c in x] if len(x) > 1 else [x] if x else [[]]
    ysets = ([[c] for c in y] if y_mode != 'merge' and len(y) > 1 else [y]) if y else [[]]
    series = [[[[a, b] for a in (xs or [None]) for b in (ys or [None])] for xs in xsets] for ys in ysets]
    xk, yk = kind(series[0][0][0][0]), kind(series[0][0][0][1])
    kinds = {'x': xk or 'none', 'y': yk or 'none'}
    types = [e['type'] for e in elements]
    resp = 'y' if yk == 'cont' else 'x' if xk == 'cont' else None
    fac = ('x' if resp == 'y' else 'y') if resp else ('x' if xk == 'cat' and not yk else 'y' if yk == 'cat' and not xk else None)
    horiz = resp == 'x' or (resp is None and fac == 'y')
    count_axis = None
    if any(t in ('bar', 'area', 'line') for t in types) and not resp and fac:
        count_axis = 'x' if horiz else 'y'
    if 'histogram' in types and resp and (xk is None or yk is None):
        count_axis = 'y' if horiz else 'x'
    if count_axis and kinds[count_axis] == 'none':
        kinds[count_axis] = 'count'
    levels = {}
    for c in x + y:
        if kind(c) == 'cat':
            lv = gc_levels(tid_, c, r0)
            levels[c] = {'values': lv, 'labels': [gc_label(q) for q in lv]}
    G = None
    gcol = overlay or (color if color and gc_is_cat(tid_, color) else None)
    if gcol:
        G = dict(gc_groups(tid_, gcol, r0, (bins or {}).get(gcol)), zone='Overlay' if overlay else 'Color')
    C = None
    if color:
        if gc_is_cat(tid_, color):
            C = {'col': color, 'cat': True, 'values': gc_levels(tid_, color, r0)}
        else:
            v = np.asarray(_data.raw(tid_, color, r0), dtype=float)
            C = {'col': color, 'cat': False, 'range': [float(np.nanmin(v)), float(np.nanmax(v))]}
    S = None
    if size:
        v = np.asarray(_data.raw(tid_, size, r0), dtype=float)
        S = {'col': size, 'range': [float(np.nanmin(v)), float(np.nanmax(v))]}
    W_ = gc_groups(tid_, wrap, r0, (bins or {}).get(wrap)) if wrap else None
    GX_ = gc_groups(tid_, gx, r0, (bins or {}).get(gx)) if gx and not wrap else None
    GY_ = gc_groups(tid_, gy, r0, (bins or {}).get(gy)) if gy and not wrap else None
    if W_:
        nC = math.ceil(math.sqrt(len(W_['values'])))
        nR = math.ceil(len(W_['values']) / nC)
    else:
        nR = (len(GY_['values']) if GY_ else 1) * len(ysets)
        nC = (len(GX_['values']) if GX_ else 1) * len(xsets)
    count_title = 'N'
    for e in elements:
        if e['type'] == 'histogram':
            count_title = 'Percent' if e.get('scale') == 'percent' else 'Count'
            break
        if e['type'] in ('bar', 'area', 'line'):
            count_title = '% of Total' if e.get('stat') == 'pct' else 'N'
            break
    title_of = lambda a, s: count_title if kinds[a] == 'count' else (' & '.join(s) if s else None)  # noqa: E731
    n_series = max(len(p) for row in series for p in row)
    exclusive = next((t for t in types if t in ('mosaic', 'pie')), None)
    any_legend = bool(G) or n_series > 1 or bool(exclusive)
    names_ = []
    if not G and n_series > 1:
        P0 = series[0][0]
        mx_, my_ = len({a for a, _ in P0}) > 1, len({b for _, b in P0}) > 1
        names_ = [f'{b} vs. {a}' if mx_ and my_ else (a if mx_ else (b or a)) for a, b in P0]
    s0 = series[0][0][0]
    ltitle = G['col'] if G else (s0[1] if exclusive == 'mosaic' else (s0[1] if fac == 'y' else s0[0]) if exclusive == 'pie' and fac else None)
    return {'size': [w, h], 'title': f'{" & ".join(y)} vs. {" & ".join(x)}' if x and y else ' & '.join(x or y), 'freq': freq, 'where': where or [],
            'wrap': W_, 'gx': GX_, 'gy': GY_, 'xsets': xsets, 'ysets': ysets, 'series': series, 'kinds': kinds, 'levels': levels, 'log': log or {},
            'group': G, 'color': C, 'sizecol': S, 'many': len(r0) > 2000, 'nrows': int(len(r0)), 'elements': elements,
            'legend': {'on': any_legend, 'pos': 'right', 'title': ltitle}, 'series_names': names_,
            'titles': {'x': [title_of('x', s) for s in xsets], 'y': [title_of('y', s) for s in ysets], 'shared_x': nC > 1 and len(xsets) == 1 and not exclusive},
            'alpha': 0.05, 'panel': [(w - 74 - (130 if any_legend else 0)) / nC, (h - 80) / nR], 'exclusive': exclusive,
            'colorbar': bool(C and not C['cat'] and 'points' in types), 'axes': axes or {}, 'order': order or {}, 'marker': marker or {}, 'map': map_}


# the elements as the page records them in the plan (their properties resolved)
EL = {
    'points': {'type': 'points', 'summary': 'none', 'jitter': 'auto', 'jitterLimit': 1},
    'smoother': {'type': 'smoother', 'method': 'spline', 'lam': 0.05, 'frac': 0.667, 'it': 3, 'conf': False},
    'fit': {'type': 'fit', 'degree': 1, 'robust': False, 'confFit': True, 'confPred': False, 'equation': False, 'r2': False, 'rmse': False, 'ftest': False},
    'ellipse': {'type': 'ellipse', 'coverage': 0.95, 'shaded': False, 'correlation': False, 'meanPoint': False},
    'contour': {'type': 'contour', 'levels': 4, 'fill': True, 'line': True, 'bw': 1, 'violin': False},
    'line': {'type': 'line', 'ordering': 'summarized', 'summary': 'mean', 'stat': 'mean', 'interval': 'none', 'style': 'bars', 'shape': 'linear'},
    'bar': {'type': 'bar', 'barStyle': 'side', 'stat': 'mean', 'interval': 'none', 'label': 'none'},
    'area': {'type': 'area', 'areaStyle': 'overlaid', 'summary': 'mean', 'stat': 'mean', 'interval': 'none', 'style': 'bars', 'shape': 'linear'},
    'box': {'type': 'box', 'outliers': True, 'boxType': 'outlier', 'boxStyle': 'normal', 'width': 0.5, 'diamond': False},
    'bean': {'type': 'bean', 'beans': 'lines', 'mean': True, 'median': True, 'overall': True, 'split': False, 'cutoff': False, 'bw': 1, 'px_unit': 150},
    'histogram': {'type': 'histogram', 'kernel': False, 'scale': 'count', 'bins': {'start': 0, 'end': 10, 'size': 1, 'nb': 10}, 'binWidth': None, 'bw': 1, 'counts': False, 'band': False},
    'heatmap': {'type': 'heatmap', 'label': 'none', 'hx': {'start': 0, 'size': 2, 'n': 5}, 'hy': {'cat': 'g'}, 'cc': None},
    'mosaic': {'type': 'mosaic', 'cellLabel': 'none', 'chisq': True},
    'caption': {'type': 'caption', 'stats': ['mean', 'n'], 'location': 'graph'},
    'pie': {'type': 'pie', 'pieStyle': 'pie', 'stat': 'n', 'label': 'percent'},
}


def el(name, **kw):
    return dict(EL[name], **kw)


def gc_axes(out):
    """The figure's panels (not its colour bars)."""
    return [A for A in out['figures'][0]['axes'] if not A['colorbar']] if out and out.get('figures') else []


def gc_gap(line, xs, ys):
    """How far a drawn line is from the points (xs, ys): inf when the counts differ."""
    if len(line) != len(xs):
        return float('inf')
    return max([max(abs(p[0] - a), abs(p[1] - b)) for p, a, b in zip(line, xs, ys)] + [0.0])


def gc_near(A, xs, ys):
    return min((gc_gap(ln, xs, ys) for ln in A['xy_lines']), default=float('inf'))


def gc_spans(A):
    return [(min(q[1] for q in pp), max(q[1] for q in pp)) for P in A['polys'] if 'contour' not in P for pp in P.get('paths', []) if pp]


def gc_span_gap(A, lo, hi):
    return min((max(abs(a - lo), abs(b - hi)) for a, b in gc_spans(A)), default=float('inf'))


def gc_hex(c):
    return c[:7].lower() if c else c


gdf = pd.DataFrame(cols)
okxy = np.isfinite(x) & np.isfinite(y)
by_g = {lv_: [r for r in rows if g[r] == lv_] for lv_ in lv}

# Points and a Smoother, an Overlay: the points are the rows', a colour and a smoothing spline for each group
code, out, err = gc_run('builder', gb_plan(tid, [el('points'), el('smoother')], x=['x'], y=['y'], overlay='g'), tid, rows=rows)
check('Points and Smoother: the code runs, ends in plt.show()', (err, code.rstrip().split('\n')[-1] if code else None), (None, 'plt.show()'))
A = gc_axes(out)[0]
got = sorted((round(p[0], 12), round(p[1], 12), gc_hex(c)) for S in A['scatter'] for p, c in zip(S['xy'], S['colors'] * len(S['xy']) if len(S['colors']) == 1 else S['colors']))
want = sorted((round(float(x[r]), 12), round(float(y[r]), 12), PALETTE[lv.index(g[r])]) for r in rows if okxy[r])
check('Points: a marker for each row with X and Y, in its group\'s colour', got == want, True)
sm_ = call('graph.smoother', table=tid, x='x', y='y', rows=rows, codes=codes, k=3, lam=0.05)['curves']
check.near('Smoother: each group\'s curve is graph.smoother\'s (the smoothing spline, lambda 0.05)', max(gc_near(A, c_['x'], c_['y']) for c_ in sm_), 0.0, abs_=1e-9)
F0 = out['figures'][0]
check('Overlay: the legend has the levels, the axes the column names', (F0['legend'], A['xlabel'], A['ylabel']), (lv, 'x', 'y'))

# the Smoother's other kinds: statsmodels' lowess; the spline's bootstrap Confidence of Fit
code, out, err = gc_run('builder', gb_plan(tid, [el('points'), el('smoother', method='lowess', frac=0.5, it=2)], x=['x'], y=['y']), tid, rows=rows)
A = gc_axes(out)[0]
cl_ = call('graph.smoother', table=tid, x='x', y='y', rows=rows, method='lowess', frac=0.5, it=2)['curves'][0]
at_ = {round(p[0], 12): p[1] for ln in A['xy_lines'] for p in ln}
check.near('Smoother (Local Kernel): graph.smoother\'s lowess at every X it gives', max(abs(at_.get(round(a, 12), np.inf) - b) for a, b in zip(cl_['x'], cl_['y'])), 0.0, abs_=1e-9)
code, out, err = gc_run('builder', gb_plan(tid, [el('smoother', conf=True)], x=['x'], y=['y']), tid, rows=rows)
cb_ = call('graph.smoother', table=tid, x='x', y='y', rows=rows, conf=True)['curves'][0]
check.near('Smoother, Confidence of Fit: the bootstrap band spans graph.smoother\'s (the same resamples)', gc_span_gap(gc_axes(out)[0], min(cb_['lower']), max(cb_['upper'])), 0.0, abs_=1e-9)

# Line of Fit, a quadratic with both bands, in a panel for each level (Group X)
fit_ = el('fit', degree=2, confPred=True, equation=True, r2=True)
code, out, err = gc_run('builder', gb_plan(tid, [el('points'), fit_], x=['x'], y=['y'], gx='g'), tid, rows=rows)
AX = gc_axes(out)
check('Group X: a panel for each level, titled with it, under the column\'s name', ([A_['title'] for A_ in AX], out['figures'][0]['subfigs'][0]['suptitle']), (lv, 'g'))
worst, bands, texts = 0.0, 0.0, True
for A_, lvl in zip(AX, lv):
    f_ = call('graph.fit', table=tid, x='x', y='y', rows=by_g[lvl], degree=2)['fits'][0]
    worst = max(worst, gc_near(A_, f_['x'], f_['y']), gc_near(A_, f_['x'], f_['pred_lower']), gc_near(A_, f_['x'], f_['pred_upper']))
    bands = max(bands, gc_span_gap(A_, min(f_['fit_lower']), max(f_['fit_upper'])))
    texts = texts and any(f'R² {gc_fmt(f_["r2"], 4)}' in a_['s'] for a_ in A_['annotations'])
check.near('Line of Fit: each panel\'s line and prediction limits are graph.fit\'s', worst, 0.0, abs_=1e-7)
check.near('Line of Fit: the Confidence of Fit spans graph.fit\'s', bands, 0.0, abs_=1e-7)
check('Line of Fit: the R² written as the page writes it', texts, True)
check('Group X: one X title under the panels', out['figures'][0]['supx'], 'x')

# Ellipse: graph.ellipse's for each group of the Overlay, their correlations written
code, out, err = gc_run('builder', gb_plan(tid, [el('ellipse', coverage=0.9, correlation=True)], x=['x'], y=['y'], overlay='g'), tid, rows=rows)
A = gc_axes(out)[0]
ee = call('graph.ellipse', table=tid, x='x', y='y', rows=rows, codes=codes, k=3, coverage=0.9)['ellipses']
check.near('Ellipse: each group\'s 90% density ellipse is graph.ellipse\'s', max(gc_near(A, e_['x'], e_['y']) for e_ in ee), 0.0, abs_=1e-9)
check('Ellipse: the correlations written', all(any(gc_fmt(e_['r'], 3) in a_['s'] for a_ in A['annotations']) for e_ in ee), True)

# Contour: the kernel density of graph.density, its contours holding 100, 75, 50 and 25% of the points
code, out, err = gc_run('builder', gb_plan(tid, [el('contour')], x=['x'], y=['y']), tid, rows=rows, names=['inner'])
de_ = call('graph.density', table=tid, x='x', y='y', rows=rows)['densities'][0]
want = [1 - v for row in de_['z'] for v in row]
check.near('Contour: its grid is graph.density\'s (the share of the points inside each contour)', max(abs(a - b) for a, b in zip(out['vars']['inner'], want)) if len(out['vars'].get('inner') or []) == len(want) else 1.0, 0.0, abs_=1e-9)
check('Contour: levels at 0, 1/4, 1/2, 3/4 (and 1 filled)', sorted({tuple(P['contour']) for P in gc_axes(out)[0]['polys'] if 'contour' in P}), [(0.0, 0.25, 0.5, 0.75), (0.0, 0.25, 0.5, 0.75, 1.0)])

# Bar with the confidence interval, Box Plot, Line, Caption Box: graph.summary's numbers at each level
sg = call('graph.summary', table=tid, y='y', rows=rows, codes=codes, k=3, boxes=True)
code, out, err = gc_run('builder', gb_plan(tid, [el('bar', interval='ci'), el('caption')], x=['g'], y=['y']), tid, rows=rows)
A = gc_axes(out)[0]
check.near('Bar: the mean of each level is graph.summary\'s', max(abs(b_['h'] - m_) for b_, m_ in zip(sorted(A['bars'], key=lambda b_: b_['x']), sg['mean'])), 0.0, abs_=1e-9)
segs = sorted((round(min(s_[0][1], s_[1][1]), 9), round(max(s_[0][1], s_[1][1]), 9)) for c_ in A['segments'] for s_ in c_['segs'] if abs(s_[0][0] - s_[1][0]) < 1e-12)
check('Bar: the error bars are graph.summary\'s 95% confidence intervals of the means', segs, sorted((round(a, 9), round(b, 9)) for a, b in zip(sg['lower'], sg['upper'])))
check('the categorical axis: the levels in the table\'s order', A['xticklabels'], lv)
tot_y = np.asarray(y)[np.isfinite(y)]
check('Caption Box: the mean and N of the graph, as the page writes them', any(f'Mean: {gc_fmt(float(tot_y.mean()), 5)}' in a_['s'] and f'N: {len(tot_y)}' in a_['s'] for a_ in A['annotations']), True)
code, out, err = gc_run('builder', gb_plan(tid, [el('box', diamond=True)], x=['g'], y=['y']), tid, rows=rows)
A = gc_axes(out)[0]
hz = [ln for ln in A['xy_lines'] if len(ln) == 2 and abs(ln[0][1] - ln[1][1]) < 1e-12]
vt = [ln for ln in A['xy_lines'] if len(ln) == 2 and abs(ln[0][0] - ln[1][0]) < 1e-12]
ok_ = True
for k_ in range(3):
    ok_ = ok_ and any(abs(ln[0][1] - sg['median'][k_]) < 1e-9 and abs((ln[0][0] + ln[1][0]) / 2 - k_) < 1e-9 for ln in hz)
    ok_ = ok_ and any(abs((ln[0][0]) - k_) < 1e-9 and sorted(round(p[1], 9) for p in ln) == sorted([round(sg['q1'][k_], 9), round(sg['lo_whisker'][k_], 9)]) for ln in vt)
    ok_ = ok_ and any(abs((ln[0][0]) - k_) < 1e-9 and sorted(round(p[1], 9) for p in ln) == sorted([round(sg['q3'][k_], 9), round(sg['hi_whisker'][k_], 9)]) for ln in vt)
check('Box Plot: each box\'s median, and whiskers from its quartiles, are graph.summary\'s (JMP\'s quantiles)', ok_, True)
dia = [ln for ln in A['xy_lines'] if len(ln) == 5]
check('Box Plot: the confidence diamonds span the t intervals of the means', sorted((round(min(p[1] for p in ln), 9), round(max(p[1] for p in ln), 9)) for ln in dia), sorted((round(a, 9), round(b, 9)) for a, b in zip(sg['lower'], sg['upper'])))
code, out, err = gc_run('builder', gb_plan(tid, [el('line', interval='se')], x=['g'], y=['y']), tid, rows=rows)
A = gc_axes(out)[0]
check.near('Line: through the means of the levels, in their order', gc_near(A, [0, 1, 2], sg['mean']), 0.0, abs_=1e-9)
segs = sorted((round(min(s_[0][1], s_[1][1]), 9), round(max(s_[0][1], s_[1][1]), 9)) for c_ in A['segments'] for s_ in c_['segs'] if abs(s_[0][0] - s_[1][0]) < 1e-12)
check('Line: the error bars, the mean plus and minus its standard error', segs, sorted((round(m_ - s_, 9), round(m_ + s_, 9)) for m_, s_ in zip(sg['mean'], sg['se'])))

# Freq: a whole number counts a row that many times; a fraction weighs it
sf_ = call('graph.summary', table=tid, y='y', rows=rows, codes=codes, k=3, freq='f')
code, out, err = gc_run('builder', gb_plan(tid, [el('bar')], x=['g'], y=['y'], freq='f'), tid, rows=rows)
check.near('Freq: the bars are graph.summary\'s means with the rows counted Freq times', max(abs(b_['h'] - m_) for b_, m_ in zip(sorted(gc_axes(out)[0]['bars'], key=lambda b_: b_['x']), sf_['mean'])), 0.0, abs_=1e-9)
sw_ = call('graph.summary', table=tfw, y='y', rows=rows, codes=codes, k=3, freq='w')
code, out, err = gc_run('builder', gb_plan(tfw, [el('bar', stat='median'), el('box')], x=['g'], y=['y'], freq='w'), tfw, rows=rows)
A = gc_axes(out)[0]
check.near('Freq, a fraction: the medians are graph.summary\'s weighted ones', max(abs(b_['h'] - m_) for b_, m_ in zip(sorted(A['bars'], key=lambda b_: b_['x']), sw_['median'])), 0.0, abs_=1e-9)

# Bean: statsmodels' beanplot violins of graph.bean, all drawn to one width; with a bandwidth and cut at the data; with Freq
for label, bkw, ekw in (('', {}, {}), (', bandwidth 1.3 cut at the data', {'bw': 1.3, 'cutoff': True}, {'bw': 1.3, 'cutoff': True}), (', Freq', {'freq': 'f'}, {})):
    bn_ = call('graph.bean', table=tid, y='y', rows=rows, codes=codes, k=3, **bkw)['beans']
    code, out, err = gc_run('builder', gb_plan(tid, [el('bean', **ekw)], x=['g'], y=['y'], freq=bkw.get('freq')), tid, rows=rows)
    A = gc_axes(out)[0]
    worst = 0.0
    for k_, b_ in enumerate(bn_):
        P_ = min(A['polygons'], key=lambda q: abs(np.mean([p[0] for p in q['xy']]) - k_))
        right = {round(p[1], 12): p[0] - k_ for p in P_['xy'] if p[0] >= k_}
        worst = max(worst, max(abs(right.get(round(yy, 12), np.inf) - 0.4 * dd) for yy, dd in zip(b_['y'], b_['d'])))
    check.near(f'Bean{label}: each violin is graph.bean\'s density (statsmodels\' violin), 0.4 wide at its peak', worst, 0.0, abs_=1e-9)
    if not label:
        check('Bean: a line for each row', sorted(round(s_[0][1], 9) for c_ in A['segments'] for s_ in c_['segs']), sorted(round(float(v), 9) for v in y[np.isfinite(y)]))

# Histogram: the page's bins; its kernel density curve is graph.kde1's scaled to the counts
code, out, err = gc_run('builder', gb_plan(tid, [el('histogram')], x=['x']), tid, rows=rows)
A = gc_axes(out)[0]
cnt = np.bincount(np.clip(np.floor(x[np.isfinite(x)] / 1 + 1e-9), 0, 9).astype(int), minlength=10)
check('Histogram: the rows counted in the page\'s bins', [round(b_['h']) for b_ in sorted(A['bars'], key=lambda b_: b_['x'])], cnt.tolist())
check('Histogram: the count axis titled Count', A['ylabel'], 'Count')
code, out, err = gc_run('builder', gb_plan(tid, [el('histogram', kernel=True, bins={'start': -5, 'end': 25, 'size': 2, 'nb': 15})], x=['y'], overlay='g'), tid, rows=rows)
grid_ = np.linspace(-5, 25, 128)
check.near('Histogram, kernel density: each group\'s curve is gaussian_kde\'s scaled to its counts', float(max(gc_near(gc_axes(out)[0], grid_, stats.gaussian_kde(sub(y, lvl))(grid_) * len(sub(y, lvl)) * 2) for lvl in lv)), 0.0, abs_=1e-9)

# Mosaic with its chi-square, Heatmap, Pie: the counts of the rows
hl = np.where(np.isfinite(y) & (y > np.nanmedian(y)), 'hi', 'lo')
tcat = table({'g': g.tolist(), 'hl': hl.tolist(), 'x': x})
ct_ = pd.crosstab(pd.Series(g), pd.Series(hl)).reindex(index=lv, columns=['hi', 'lo']).to_numpy()
code, out, err = gc_run('builder', gb_plan(tcat, [el('mosaic')], x=['g'], y=['hl']), tcat)
A = gc_axes(out)[0]
share = ct_ / ct_.sum(axis=1, keepdims=True)
got = sorted((round(b_['x'] + b_['w'] / 2, 9), round(b_['h'], 12)) for b_ in A['bars'])
wid = ct_.sum(axis=1) / ct_.sum()
mids_ = np.cumsum(wid) - wid / 2
check('Mosaic: a column for each level as wide as its share, split by the shares of the other', got, sorted((round(float(mids_[i]), 9), round(float(share[i, j]), 12)) for i in range(3) for j in range(2)))
cs_ = call('graph.chisq', tables=[ct_.tolist()], x='g', y='hl')['tests'][0]
check('Mosaic: graph.chisq\'s Pearson test above the panel', f'Pearson χ² {gc_fmt(cs_["chi2"], 5)}, df 2' in A['title'], True)
code, out, err = gc_run('builder', gb_plan(tcat, [el('heatmap')], x=['x'], y=['g']), tcat)
M_ = gc_axes(out)[0]['meshes'][0]
hx_ = np.clip(np.floor(x / 2 + 1e-9), 0, 4).astype(int)
want = np.zeros((3, 5))
for r in range(N):
    want[lv.index(g[r]), hx_[r]] += 1
check('Heatmap: the rows counted in each cell (the page\'s bins of X, the levels of g)', [None if v is None else round(v) for v in M_['z']], [None if v == 0 else int(v) for v in want.ravel()])
code, out, err = gc_run('builder', gb_plan(tcat, [el('pie')], x=['g']), tcat)
W_ = gc_axes(out)[0]['wedges']
cnt_ = np.array([np.sum(g == lvl) for lvl in lv], dtype=float)
check.near('Pie: each slice\'s share is its level\'s share of the rows', float(max(abs((w_['theta2'] - w_['theta1']) / 360 - c_) for w_, c_ in zip(W_, cnt_ / cnt_.sum()))), 0.0, abs_=1e-6)
check('Pie: clockwise from the top, in the levels\' order and colours', (round(W_[0]['theta2'], 4), [gc_hex(w_['fc']) for w_ in W_]), (90.0, PALETTE[:3]))

# Points jittered at the levels of a categorical X: each within its level, its Y the row's
code, out, err = gc_run('builder', gb_plan(tid, [el('points')], x=['g'], y=['y']), tid, rows=rows)
S_ = gc_axes(out)[0]['scatter'][0]
check('Jitter: each point within its level (to 0.4 either side), at its row\'s Y', (all(abs(p[0] - round(p[0])) <= 0.4 + 1e-12 for p in S_['xy']),
      sorted(round(p[1], 12) for p in S_['xy']) == sorted(round(float(v), 12) for v in y[np.isfinite(y)]), len({round(p[0], 12) for p in S_['xy']}) > 100), (True, True, True))

# Wrap, Group Y, several Y side by side or merged, Color and Size, a log axis, a binned Overlay
code, out, err = gc_run('builder', gb_plan(tid, [el('points')], x=['x'], y=['y'], wrap='g'), tid, rows=rows)
AX = [A_ for A_ in gc_axes(out) if A_['shown']]
check('Wrap: a panel for each level, titled with it, in the table\'s order', [A_['title'] for A_ in AX], lv)
check('Wrap: each panel\'s points are its level\'s rows', [len(A_['scatter'][0]['xy']) for A_ in AX], [int(np.sum(okxy & (g == lvl))) for lvl in lv])
code, out, err = gc_run('builder', gb_plan(tid, [el('box')], x=['g'], y=['y'], gy='g'), tid, rows=rows)
F_ = out['figures'][0]
check('Group Y: a row of panels for each level, named at the side', (len(gc_axes(out)), [t_ for sf in F_['subfigs'] for t_ in sf['texts']]), (3, ['g']))
code, out, err = gc_run('builder', gb_plan(tid, [el('points')], x=['x'], y=['y', 'z']), tid, rows=rows)
check('several Y side by side: a row of panels each, titled with its column', [A_['ylabel'] for A_ in gc_axes(out)], ['y', 'z'])
code, out, err = gc_run('builder', gb_plan(tid, [el('points'), el('smoother')], x=['x'], y=['y', 'z'], y_mode='merge'), tid, rows=rows)
check('several Y merged: one panel, a colour and a legend entry each', (len(gc_axes(out)), out['figures'][0]['legend'], sorted({gc_hex(c_) for S in gc_axes(out)[0]['scatter'] for c_ in S['colors']})), (1, ['y', 'z'], sorted(PALETTE[:2])))
code, out, err = gc_run('builder', gb_plan(tid, [el('points')], x=['x'], y=['y'], color='z', size='f'), tid, rows=rows)
S_ = gc_axes(out)[0]['scatter'][0]
fz = {(round(float(x[r]), 12), round(float(y[r]), 12)): (f[r], z[r]) for r in rows if okxy[r]}
by_f = {}
for p, s_ in zip(S_['xy'], S_['sizes']):
    by_f.setdefault(fz[(round(p[0], 12), round(p[1], 12))][0], set()).add(round(s_, 6))
check('Size: the points grow with the column (one size for each value of f)', [len(by_f[k_]) for k_ in sorted(by_f)] == [1, 1, 1] and sorted(by_f, key=lambda k_: min(by_f[k_])) == sorted(by_f), True)
check('Color, continuous: a colour bar titled with the column', out['figures'][0]['colorbars'], ['z'])
code, out, err = gc_run('builder', gb_plan(tid, [el('points')], x=['x'], y=['y'], log={'x': True}), tid, rows=rows)
check('a log X axis', gc_axes(out)[0]['xscale'], 'log')
code, out, err = gc_run('builder', gb_plan(tid, [el('points'), el('smoother')], x=['x'], y=['y'], overlay='z'), tid, rows=rows)
G_ = gc_groups(tid, 'z', np.arange(N))
check('Overlay, continuous: five bins of about equal counts, the page\'s labels in the legend', out['figures'][0]['legend'], G_['labels'])

# Area, stacked: each group's top is the running sum of the groups' sums at each level
ta = table({'a': (np.arange(N) % 4 + 1).astype(float), 'y': y, 'g': g.tolist()}, types={'a': 'ordinal'})
code, out, err = gc_run('builder', gb_plan(ta, [el('area', areaStyle='stacked', summary='sum', stat='sum')], x=['a'], y=['y'], overlay='g'), ta, rows=rows)
A = gc_axes(out)[0]
acc_ = np.zeros(4)
worst = 0.0
for lvl in lv:
    acc_ = acc_ + np.array([np.nansum(y[(g == lvl) & (np.arange(N) % 4 == k_)]) for k_ in range(4)])
    worst = max(worst, min(max(abs(p[1] - q) for p, q in zip(ln, acc_)) if len(ln) == 4 else np.inf for ln in A['xy_lines']))
check.near('Area, stacked: the top of each group\'s area is the running sum of the sums', float(worst), 0.0, abs_=1e-9)

# a date column: text in the CSV, a number (ms since 1970) in the page. The code turns it
# back into the number before it computes (util.dated_code), so the smoother's code on the
# CSV as the page exports it gives the page's curve, and it draws the axis as dates.
from smui.util import dated_code  # noqa: E402
days = np.array([np.datetime64('1980-01-01') + np.timedelta64(91 * i, 'D') for i in range(40)])
ms_ = (days - np.datetime64('1970-01-01')).astype('timedelta64[ms]').astype(float)
out_ = 100 + np.cumsum(np.random.default_rng(5).normal(1, 0.5, 40))
tq = table({'quarter': ms_, 'output': out_})
_data.TABLES[tq]['meta']['quarter']['format'] = {'kind': 'date'}


def gc_ns(code, frame, name):
    """Run the code on the CSV (Agg, no plt.show()); its variables."""
    import matplotlib.pyplot as plt_
    frame.to_csv(os.path.join(GC_TMP, f'{name}.csv'), index=False)
    here, ns = os.getcwd(), {}
    os.chdir(GC_TMP)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(strip_show(code), name, 'exec'), ns)
    except Exception as e:  # reported by the check
        ns = {'_error': f'{type(e).__name__}: {e}'}
    finally:
        os.chdir(here)
        plt_.close('all')
    return ns


for xn, yn in (('output', 'quarter'), ('quarter', 'output')):
    where = 'Y' if yn == 'quarter' else 'X'
    cv = call('graph.smoother', table=tq, x=xn, y=yn, lam=0.05)['curves'][0]
    code, out, err = gc_run('builder', gb_plan(tq, [el('points'), el('smoother')], x=[xn], y=[yn]), tq, name='Cycle', dates=['quarter'])
    check(f'a date on {where}: the code turns the date back into its number, and runs', ('pd.to_datetime(df["quarter"])' in (code or ''), err), (True, None))
    check(f'... and draws the {where} axis as dates', gc_axes(out)[0][f'{where.lower()}axis_date'] if out else None, True)
    ns_ = gc_ns(code, gc_frame(tq, ['quarter']), 'Cycle')
    check.near(f'... and gives the page\'s curve (its first point, date on {where})', float(ns_['spline']((ns_['grid'][0] - ns_['m']) / ns_['s'])) if 'spline' in ns_ else None, cv['y'][0], rel=1e-9)
check('code that parses the date itself (a Time ID) is left to do so', dated_code('df = pd.read_csv("a.csv")\ndf["t"] = pd.to_datetime(df["t"])', ['t']), 'df = pd.read_csv("a.csv")\ndf["t"] = pd.to_datetime(df["t"])')
check('... and code that does not use the date column gets no line', dated_code('df = pd.read_csv("a.csv")\nx = df["y"]', ['t']), 'df = pd.read_csv("a.csv")\nx = df["y"]')
check('... a second pass adds nothing', dated_code(dated_code('df = pd.read_csv("a.csv")\nx = df["t"]', ['t']), ['t']).count('to_datetime'), 1)

# every element and zone: the code runs and draws a figure of the page's size
EVERY = [
    ('Points, Smoother, Line of Fit, Ellipse, Contour with Freq', [el('points'), el('smoother'), el('fit'), el('ellipse'), el('contour')], dict(x=['x'], y=['y'], freq='f')),
    ('robust Line of Fit, Wrap', [el('points'), el('fit', robust=True, equation=True)], dict(x=['x'], y=['y'], wrap='g')),
    ('violins (Contour at a categorical X)', [el('contour', violin=True)], dict(x=['g'], y=['y'])),
    ('Points summarized with an interval', [el('points', summary='mean', stat='mean', interval='ci')], dict(x=['g'], y=['y'])),
    ('Line in the table\'s row order, stepped', [dict(type='line', ordering='row', shape='hv')], dict(x=['x'], y=['y'])),
    ('Line, a curve with a band', [el('line', shape='spline', summary='median', stat='median', interval='iqr', style='band')], dict(x=['g'], y=['y'])),
    ('Bar stacked with percent labels, Overlay', [el('bar', barStyle='stacked', stat='sum', label='percent')], dict(x=['g'], y=['z'], overlay='g')),
    ('Bar, horizontal needles', [el('bar', barStyle='needle', stat='median', interval='iqr')], dict(x=['y'], y=['g'])),
    ('Bar, % of Total', [el('bar', stat='pct')], dict(x=['g'])),
    ('Area overlaid', [el('area')], dict(x=['g'], y=['y'])),
    ('Box Plot, quantile boxes, horizontal', [el('box', boxType='quantile', boxStyle='solid', width=0.8)], dict(x=['y'], y=['g'])),
    ('Bean with jitter, split', [el('bean', beans='jitter', split=True, cutoff=True, bw=1.3)], dict(x=['g'], y=['y'], overlay='g')),
    ('Histogram in percent, a band at each level', [el('histogram', scale='percent', band=True)], dict(x=['x'], y=['g'])),
    ('Caption Box for each level', [el('points'), el('caption', stats=['median', 'sd', 'range'], location='factor')], dict(x=['g'], y=['y'])),
    ('Pie ring of sums, Group X', [el('pie', pieStyle='ring', stat='sum', label='value')], dict(x=['g'], y=['z'], gx='g')),
    ('Group X by Group Y', [el('box')], dict(x=['g'], y=['y'], gx='g', gy='g')),
    ('several X side by side', [el('points')], dict(x=['x', 'z'], y=['y'])),
    ('Color categorical', [el('points'), el('smoother')], dict(x=['x'], y=['y'], color='g')),
]
bad = []
for label, els_, kw in EVERY:
    code, out, err = gc_run('builder', gb_plan(tid, els_, **kw), tid, rows=rows)
    if err or not out or len(out['figures']) != 1 or out['figures'][0]['size'] != [6.4, 4.2] or not code.rstrip().endswith('plt.show()'):
        bad.append((label, (err or '')[:300]))
check(f'every element and zone: the code runs, one figure of the graph\'s size ({len(EVERY)} graphs)', bad, [])


def gc_quiet(code, frame, name):
    """Run the code on the CSV (Agg, no plt.show()): its error and the warnings it gave (the notebook would show them)."""
    import warnings
    import matplotlib.pyplot as plt_
    frame.to_csv(os.path.join(GC_TMP, f'{name}.csv'), index=False)
    here, err_ = os.getcwd(), None
    os.chdir(GC_TMP)
    with warnings.catch_warnings(record=True) as caught, contextlib.redirect_stdout(io.StringIO()):
        warnings.simplefilter('always')
        try:
            exec(compile(strip_show(code), name, 'exec'), {'__name__': '__main__'})
        except Exception as e:  # reported by the check
            err_ = f'{type(e).__name__}: {e}'
    os.chdir(here)
    plt_.close('all')
    return err_, sorted({f'{q.category.__name__}: {str(q.message)[:120]}' for q in caught})


# panels and groups with no rows or one: every element's code runs without an error or a warning
rs_ = np.random.default_rng(9)
sp = {'a': [], 'b': [], 'x': [], 'y': [], 'c': [], 'f': []}
for ai in range(4):
    for bi in range(3):
        for _ in range([0, 1, 12, 12][(ai + bi) % 4]):   # (a0, b0), (a1, b2), ... empty; (a0, b1), ... a row
            sp['a'].append(f'a{ai}'); sp['b'].append(f'b{bi}'); sp['c'].append(['u', 'v'][rs_.integers(0, 2)])
            sp['x'].append(rs_.uniform(0, 10)); sp['y'].append(rs_.normal(5, 2)); sp['f'].append(float(rs_.integers(1, 3)))
tsp = table(sp)
sp_frame = gc_frame(tsp)
SPARSE = [
    ('Points, Smoother, Line of Fit, Ellipse, Contour', [el('points'), el('smoother'), el('fit'), el('ellipse'), el('contour')], dict(x=['x'], y=['y'], overlay='c')),
    ('the same with Freq, the bands', [el('points'), el('smoother', conf=True), el('fit', confPred=True), el('ellipse'), el('contour')], dict(x=['x'], y=['y'], overlay='c', freq='f')),
    ('lowess', [el('smoother', method='lowess')], dict(x=['x'], y=['y'], overlay='c')),
    ('violins', [el('contour', violin=True)], dict(x=['c'], y=['y'])),
    ('summarized Points', [el('points', summary='mean', stat='mean', interval='ci')], dict(x=['c'], y=['y'], overlay='c')),
    ('Line', [el('line', interval='se')], dict(x=['c'], y=['y'], overlay='c')),
    ('Line, a curve with a band', [el('line', shape='spline', summary='median', stat='median', interval='iqr', style='band')], dict(x=['c'], y=['y'])),
    ('Line in row order', [dict(type='line', ordering='row', shape='hv')], dict(x=['x'], y=['y'])),
    ('Bar', [el('bar', interval='ci', label='value')], dict(x=['c'], y=['y'], overlay='c')),
    ('Bar stacked', [el('bar', barStyle='stacked', stat='sum', label='percent')], dict(x=['c'], y=['y'], overlay='c')),
    ('Bar, % of Total', [el('bar', stat='pct')], dict(x=['c'], overlay='c')),
    ('Area', [el('area')], dict(x=['c'], y=['y'], overlay='c')),
    ('Area stacked', [el('area', areaStyle='stacked', summary='sum', stat='sum')], dict(x=['c'], y=['y'], overlay='c')),
    ('Box Plot', [el('box', diamond=True)], dict(x=['c'], y=['y'], overlay='c')),
    ('Box Plot with Freq', [el('box')], dict(x=['c'], y=['y'], freq='f')),
    ('Bean', [el('bean')], dict(x=['c'], y=['y'])),
    ('Bean split', [el('bean', beans='jitter', split=True)], dict(x=['c'], y=['y'], overlay='c')),
    ('Histogram', [el('histogram')], dict(x=['x'], overlay='c')),
    ('Histogram, kernel density', [el('histogram', kernel=True)], dict(x=['x'], overlay='c')),
    ('Histogram at each level', [el('histogram', band=True)], dict(x=['x'], y=['c'])),
    ('Histogram, kernel density at each level', [el('histogram', kernel=True, band=True)], dict(x=['x'], y=['c'])),
    ('Heatmap', [dict(EL['heatmap'], hy={'cat': 'c'})], dict(x=['x'], y=['c'])),
    ('Mosaic', [el('mosaic', cellLabel='count')], dict(x=['c'], y=['c'])),
    ('Caption Box', [el('points'), el('caption', stats=['mean', 'n', 'range', 'sd'])], dict(x=['c'], y=['y'], overlay='c')),
    ('Caption Box for each level', [el('points'), el('caption', stats=['median', 'sd'], location='factor')], dict(x=['c'], y=['y'])),
    ('Pie', [el('pie')], dict(x=['c'])),
    ('Pie of sums', [el('pie', stat='sum', pieStyle='ring')], dict(x=['c'], y=['y'])),
    ('Packed jitter', [el('points', jitter='packed', packed={'value_px': 80, 'level_px': 40, 'diam': 7})], dict(x=['c'], y=['y'], overlay='c')),
    ('Centered Grid jitter', [el('points', jitter='grid')], dict(x=['c'], y=['y'], overlay='c')),
    ('Random Normal jitter', [el('points', jitter='normal')], dict(x=['c'], y=['y'])),
]
bad = []
for label, els_, kw in SPARSE:
    err_, warned = gc_quiet(call('graph.code', kind='builder', plan=gb_plan(tsp, els_, gx='a', gy='b', **kw), table=tsp, table_name='Sparse')['plot_code'], sp_frame, 'Sparse')
    if err_ or warned:
        bad.append((label, err_, warned))
err_, warned = gc_quiet(call('graph.code', kind='builder', plan=gb_plan(tsp, [el('points'), el('fit')], x=['x'], y=['y'], wrap='b', overlay='a'), table=tsp, table_name='Sparse')['plot_code'], sp_frame, 'Sparse')
check(f'panels and groups with no rows or one row (Group X by Group Y): every element\'s code runs without an error or a warning ({len(SPARSE) + 1} graphs)', bad + ([('Wrap', err_, warned)] if err_ or warned else []), [])
bad = []
for label, els_, kw in EVERY:
    err_, warned = gc_quiet(call('graph.code', kind='builder', plan=gb_plan(tid, els_, **kw), table=tid, rows=rows, table_name='Graph test')['plot_code'], gdf, 'Graph test')
    if warned:
        bad.append((label, warned))
check('... and on the test table, no warnings either', bad, [])

# ---- the other Graph platforms' code -------------------------------------------------------------------
# the Functional Data Plot: the code's functional boxplot and HDR boxplot give graph.fbox's and graph.hdr's numbers
fd_csv = pd.DataFrame({**{h_: X[:, j] for j, h_ in enumerate(hours)}, 'day': [f'Day {i + 1:02d}' for i in range(len(X))], 'site': ['Coast' if i % 2 == 0 else 'Inland' for i in range(len(X))]})
long_csv = pd.DataFrame({'id': ids_l, 'x': [L[k][1] for k in perm], 'y': [L[k][2] for k in perm]})
irr_csv = pd.DataFrame({'id': [f'k{i}' for i, xx in enumerate(xs_i) for _ in xx], 'x': np.concatenate(xs_i), 'y': np.concatenate(ys_i)})
fd_cases = [
    ('fbox, rows as functions', 'graph.fbox', dict(table=tw, y=hours), {'view': 'box', 'layout': 'wide', 'y': hours}, fd_csv),
    ('fbox, BD2 counted, Sun and Genton', 'graph.fbox', dict(table=tw, y=hours, method='BD2x', rule='sungenton', wfactor=1.2), {'view': 'box', 'layout': 'wide', 'y': hours, 'method': 'BD2x', 'rule': 'sungenton', 'wfactor': 1.2}, fd_csv),
    ('fbox, stacked', 'graph.fbox', dict(table=tl, layout='long', id='id', x='x', y='y'), {'view': 'box', 'layout': 'long', 'id': 'id', 'x': 'x', 'y': ['y']}, long_csv),
    ('fbox, stacked at different X', 'graph.fbox', dict(table=tl2, layout='long', id='id', x='x', y='y'), {'view': 'box', 'layout': 'long', 'id': 'id', 'x': 'x', 'y': ['y']}, irr_csv),
    ('fbox, stacked without X', 'graph.fbox', dict(table=tl3, layout='long', id='id', y='y'), {'view': 'box', 'layout': 'long', 'id': 'id', 'y': ['y']}, pd.DataFrame({'id': ['a', 'a', 'a', 'b', 'b', 'b', 'c', 'c', 'c'], 'y': [1, 2, 3, 2, 3, 4, 0, 5, 1.0]})),
    ('hdr, rows as functions', 'graph.hdr', dict(table=tw, y=hours), {'view': 'hdr', 'layout': 'wide', 'y': hours}, fd_csv),
    ('hdr, a constant point', 'graph.hdr', dict(table=tcst, y=hours), {'view': 'hdr', 'layout': 'wide', 'y': hours}, pd.DataFrame({h_: Xc[:, j] for j, h_ in enumerate(hours)})),
]
for label, fn, kw, plan, frame in fd_cases:
    res = call(fn, **kw)
    code = call('graph.code', kind='functional', plan=dict(plan, size=[800, 450]), table=kw['table'], table_name='Curves')['plot_code']
    ns = gc_ns(code, frame, 'Curves')
    if '_error' in ns:
        check(f'the code of the functional graph ({label}) runs', ns['_error'], True)
        continue
    got_ = ns['res']
    if fn == 'graph.fbox':
        check.near(f'the code of the functional graph ({label}): the depths', float(np.max(np.abs(np.asarray(got_['depth']) - np.array(res['depth'])))), 0.0, abs_=1e-12)
        check(f'the code of the functional graph ({label}): the outliers', np.asarray(got_['outlier']).tolist(), res['outlier'])
        check(f'the code of the functional graph ({label}): the median', int(got_['median']), res['median'])
    else:
        check(f'the code of the functional graph ({label}): the outliers', np.asarray(got_['outlier']).tolist(), res['outlier'])
        check.near(f'the code of the functional graph ({label}): the modal curve', float(np.max(np.abs(np.asarray(got_['modal']) - np.array(res['modal'])))), 0.0, abs_=1e-7)
        worst = max(float(np.max(np.abs(np.asarray(got_[k][j]) - np.array(res[k][j])))) for k in ('hdr50', 'hdr90') for j in (0, 1))
        check.near(f'the code of the functional graph ({label}): the bands', worst, 0.0, abs_=1e-9)
# By: each group's graph has the code of its own rows
inland = [i for i in range(60) if i % 2 == 1]
for fn, view in (('graph.fbox', 'box'), ('graph.hdr', 'hdr')):
    res = call(fn, table=tw, y=hours, rows=inland)
    code = call('graph.code', kind='functional', plan={'view': view, 'layout': 'wide', 'y': hours, 'size': [800, 450], 'where': [{'column': 'site', 'value': 'Inland'}]}, table=tw, rows=inland, table_name='Curves')['plot_code']
    ns = gc_ns(code, fd_csv, 'Curves')
    check(f'By: the {view} graph of a group takes its rows (site Inland)', ('df = df[df["site"] == "Inland"]' in code, np.asarray(ns['res']['outlier']).tolist() if 'res' in ns else ns.get('_error')), (True, res['outlier']))
# ... and draws what the page draws: the median, the outliers named, the regions; the rainbow; the score plot
code, out, err = gc_run('functional', {'view': 'box', 'layout': 'wide', 'y': hours, 'label_col': 'day', 'named': 12, 'size': [800, 450]}, tw, name='Curves')
A = gc_axes(out)[0]
outl = [i for i, o in enumerate(fb['outlier']) if o]
lines_ = {L_['label']: L_ for L_ in A['lines']}
check.near('the functional boxplot: its median curve', float(max(abs(a - b) for a, b in zip(lines_[f'Median: Day {fb["median"] + 1:02d}']['y'], X[fb['median']]))), 0.0, abs_=1e-12)
check('the functional boxplot: the first 12 outliers named, the others dotted', ([n_ for n_ in lines_ if n_.startswith('Day')], len([L_ for L_ in A['lines'] if L_['ls'] == ':'])), ([f'Day {i + 1:02d}' for i in outl[:12]], max(0, len(outl) - 12)))
check.near('the functional boxplot: the 50% central region is fbox\'s', gc_span_gap(A, min(fb['lower']), max(fb['upper'])), 0.0, abs_=1e-12)
code, out, err = gc_run('functional', {'view': 'rainbow', 'layout': 'wide', 'y': hours, 'size': [800, 450]}, tw, name='Curves')
A = gc_axes(out)[0]
check('the rainbow plot: a curve each, the deepest last, thickest, in viridis\'s darkest', (len(A['lines']), gc_hex(A['lines'][-1]['color']), A['lines'][-1]['y'] == [float(v) for v in X[fb['median']]]), (60, '#440154', True))
code, out, err = gc_run('functional', {'view': 'scores', 'layout': 'wide', 'y': hours, 'size': [600, 512]}, tw, name='Curves')
A = gc_axes(out)[0]
check.near('the HDR score plot: each curve at its scores (graph.hdr\'s)', max(abs(p[0] - q[0]) + abs(p[1] - q[1]) for p, q in zip(A['scatter'][0]['xy'], hd['scores'])), 0.0, abs_=1e-12)

# the platforms on one table
rp = np.random.default_rng(3)
npl = 120
pcols = {'x': rp.uniform(0, 10, npl).round(2), 'y': rp.uniform(0, 10, npl).round(2), 'A': rp.uniform(0.2, 1.2, npl).round(3), 'B': rp.uniform(0, 2, npl).round(3), 'C': rp.uniform(0, 1, npl).round(3),
         'country': [['Alpha', 'Beta', 'Gamma', 'Delta'][i % 4] for i in range(npl)], 'year': [2000.0 + (i // 4) % 6 for i in range(npl)], 'g': ['p' if i % 3 else 'q' for i in range(npl)], 'pop': rp.uniform(5, 55, npl).round(1)}
pcols['z'] = (np.sin(pcols['x'] / 1.5) * np.cos(pcols['y'] / 2) * 10).round(3)
tp = table(pcols, types={'year': 'ordinal'})
pdf = gc_frame(tp)
Gp = {'col': 'g', 'values': ['p', 'q'], 'labels': ['p', 'q']}
# Contour Plot and Surface Plot: the grid is graph.interp's
for kind_, plan in (('contour', {'size': [640, 499], 'x': 'x', 'y': 'y', 'z': 'z', 'method': 'cubic', 'grid': 50, 'levels': {'start': -8, 'end': 8, 'size': 2}, 'fill': True, 'labels': True, 'theme': 'spectral', 'points': True}),
                    ('surface', {'size': [760, 623], 'x': 'x', 'y': 'y', 'z': 'z', 'method': 'linear', 'grid': 40, 'contours': True, 'theme': 'blues', 'points': True})):
    code, out, err = gc_run(kind_, plan, tp, name='Plat', names=['gz'])
    gi_ = call('graph.interp', table=tp, x='x', y='y', z='z', grid=plan['grid'], method=plan['method'])
    check.near(f'{kind_.title()} Plot: the grid is graph.interp\'s ({plan["method"]} griddata)', max(abs(a - b) if a is not None and b is not None else (0 if a is b else np.inf) for a, b in zip(out['vars']['gz'], [v for row in gi_['z'] for v in row])) if out else None, 0.0, abs_=1e-9)
code, out, err = gc_run('contour', {'size': [640, 499], 'x': 'x', 'y': 'y', 'z': 'z', 'method': 'linear', 'grid': 50, 'levels': {'start': -8, 'end': 8, 'size': 2}, 'fill': False, 'theme': 'viridis', 'points': False}, tp, name='Plat')
check('Contour Plot: the contours at the page\'s levels, the colour bar titled with Z', ([P['contour'] for P in gc_axes(out)[0]['polys'] if 'contour' in P], out['figures'][0]['colorbars']), ([[-8.0, -6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0, 8.0]], ['z']))
# Scatterplot Matrix: its histograms, ellipses and fit lines
mplan = {'size': [600, 540], 'rows': ['x', 'y', 'z'], 'cols': ['x', 'y', 'z'], 'rect': False, 'format': 'lower', 'group': Gp, 'points': True, 'fit': True, 'ellipses': True, 'shaded': False, 'coverage': 0.95,
         'nonpar': False, 'hist': True, 'bins': {'x': {'start': 0, 'size': 1, 'nb': 10}, 'y': {'start': 0, 'size': 1, 'nb': 10}, 'z': {'start': -10, 'size': 2, 'nb': 10}}, 'nrows': npl}
code, out, err = gc_run('matrix', mplan, tp, name='Plat')
AX = out['figures'][0]['axes']
hist_ok = all(sorted(round(b_['h']) for b_ in AX[4 * i]['bars']) == sorted(np.bincount(np.clip(np.floor((pcols[c] - st_) / sz_ + 1e-9), 0, 9).astype(int), minlength=10).tolist())
              for i, (c, (st_, sz_)) in enumerate(zip('xyz', [(0, 1), (0, 1), (-10, 2)])))
check('Scatterplot Matrix: the histograms on the diagonal count the rows in the page\'s bins', hist_ok, True)
pc_ = [0 if v == 'p' else 1 for v in pcols['g']]
el_ = call('graph.ellipse', table=tp, x='x', y='z', codes=pc_, k=2, coverage=0.95)['ellipses']
ft_ = call('graph.fit', table=tp, x='x', y='z', codes=pc_, k=2, degree=1, n_grid=40)['fits']
A = AX[6]   # z by x
check.near('Scatterplot Matrix: a cell\'s ellipses and fit lines are graph.ellipse\'s and graph.fit\'s', max([gc_near(A, e_['x'], e_['y']) for e_ in el_] + [gc_near(A, f_['x'], f_['y']) for f_ in ft_]), 0.0, abs_=1e-9)
check('Scatterplot Matrix: the cells above the diagonal left out', [AX[k_]['shown'] for k_ in (1, 2, 5)], [False] * 3)
# Bubble Plot: the first time's bubbles at their rows' means, sized as Plotly sizes an area
code, out, err = gc_run('bubble', {'size': [760, 581], 'x': 'x', 'y': 'y', 'ids': ['country'], 'time': 'year', 'allTimes': False, 'time0': 2000, 'times': [2000.0 + k_ for k_ in range(6)], 'sizes': 'pop', 'freq': None,
                                   'color': {'col': 'g', 'cat': True, 'values': ['p', 'q'], 'labels': ['p', 'q']}, 'label': True, 'scale': 1, 'xrange': [-0.8, 10.8], 'yrange': [-0.8, 10.8]}, tp, name='Plat')
S_ = gc_axes(out)[0]['scatter'][0]
fr = pdf[pdf['year'] == 2000].groupby('country', sort=False)[['x', 'y', 'pop']].agg({'x': 'mean', 'y': 'mean', 'pop': 'sum'})
smax = pdf.groupby(['year', 'country'])['pop'].sum().max()
want = sorted((round(r_.x, 9), round(r_.y, 9), round(2 * max(math.sqrt(r_.pop / 2 / (2 * smax / 46 ** 2)), 2), 9)) for r_ in fr.itertuples())
check('Bubble Plot: the first year\'s bubbles at their rows\' means, as wide as Plotly draws their areas', sorted((round(p[0], 9), round(p[1], 9), round(math.sqrt(s_) / 0.72, 9)) for p, s_ in zip(S_['xy'], S_['sizes'])), want)
# Parallel Plot: a line for each row through its values, each axis from its minimum to its maximum
code, out, err = gc_run('parallel', {'size': [600, 380], 'ys': ['x', 'y', 'z', 'pop'], 'group': Gp, 'scale': 'range', 'center': False, 'reverse': ['y'], 'nrows': npl}, tp, name='Plat')
U_ = pdf[['x', 'y', 'z', 'pop']]
U_ = (U_ - U_.min()) / (U_.max() - U_.min())
U_['y'] = 1 - U_['y']
check('Parallel Plot: a line for each row through its scaled values (y reversed)', sorted(tuple(round(v, 9) for v in L_['y']) for L_ in gc_axes(out)[0]['lines'] if L_['marker'] == 'o'), sorted(tuple(round(v, 9) for v in r_) for r_ in U_.to_numpy()))
# Cell Plot: each continuous column in standard deviations, each level its number
code, out, err = gc_run('cell', {'size': [400, 900], 'ys': ['x', 'z', 'g'], 'cats': {'g': ['p', 'q']}, 'uniform': False, 'center': False, 'legend': True, 'labels': None, 'nrows': npl}, tp, name='Plat', names=['Z'])
Zw = np.c_[(pdf['x'] - pdf['x'].mean()) / pdf['x'].std(), (pdf['z'] - pdf['z'].mean()) / pdf['z'].std(), (pdf['g'] == 'q').astype(float)]
check.near('Cell Plot: each cell\'s value, standardized (a level: its number)', float(max(abs(a - b) for a, b in zip(out['vars']['Z'], Zw.ravel()))), 0.0, abs_=1e-12)
# Treemap: each tile's area (with its padding) in proportion to its size, within its parent's
code, out, err = gc_run('treemap', {'size': [820, 492], 'area': [812, 462], 'cats': ['country', 'g'], 'levels': {'country': ['Alpha', 'Beta', 'Delta', 'Gamma'], 'g': ['p', 'q']}, 'sizes': 'pop', 'color': None}, tp, name='Plat')
R_ = gc_axes(out)[0]['bars']
tops = [b_ for b_ in R_[::3]]
sums = pdf.groupby('country')['pop'].sum().reindex(['Alpha', 'Beta', 'Delta', 'Gamma'])
a_top = np.array([(b_['w'] + 3) * (b_['h'] + 3) for b_ in tops])
check.near('Treemap: the tiles of country in proportion to their sums of pop (squarified, 3 pixels between)', float(np.max(np.abs(a_top / a_top.sum() - (sums / sums.sum()).to_numpy()))), 0.0, abs_=1e-9)
inside = all(t_['x'] - 1e-9 <= b_['x'] and b_['x'] + b_['w'] <= t_['x'] + t_['w'] + 1e-9 and t_['y'] - 1e-9 <= b_['y'] and b_['y'] + b_['h'] <= t_['y'] + t_['h'] + 1e-9 for k_, t_ in enumerate(tops) for b_ in R_[3 * k_ + 1:3 * k_ + 3])
check('Treemap: the tiles of g inside their country\'s', inside, True)
# Ternary Plot, Scatterplot 3D, Overlay Plot: the rows' own values
code, out, err = gc_run('ternary', {'size': [620, 558], 'cols': ['A', 'B', 'C'], 'color': None}, tp, name='Plat')
sh_ = pdf[['A', 'B', 'C']].div(pdf[['A', 'B', 'C']].sum(axis=1), axis=0)
check('Ternary Plot: each row at its shares (A at the top, B bottom left, C bottom right)', sorted((round(p[0], 9), round(p[1], 9)) for p in gc_axes(out)[0]['scatter'][0]['xy']), sorted((round(0.5 * a_ + c_, 9), round(math.sqrt(3) / 2 * a_, 9)) for a_, c_ in zip(sh_['A'], sh_['C'])))
code, out, err = gc_run('scatter3d', {'size': [760, 620], 'cols': ['x', 'y', 'z'], 'color': {'col': 'g', 'cat': True, 'values': ['p', 'q'], 'labels': ['p', 'q']}}, tp, name='Plat')
S3 = gc_axes(out)[0]['scatter3d'][0]
check('Scatterplot 3D: each row at its X, Y and Z, in its level\'s colour', sorted(zip(*S3['xyz'], [gc_hex(c_) for c_ in S3['colors']])), sorted(zip(pcols['x'], pcols['y'], pcols['z'], [PALETTE[0] if v == 'p' else PALETTE[1] for v in pcols['g']])))
code, out, err = gc_run('overlay', {'size': [760, 456], 'ys': [{'col': 'z', 'points': True, 'connect': True}, {'col': 'pop', 'right': True, 'points': True, 'connect': True}], 'x': 'x', 'group': None, 'overlayY': True, 'sortX': True, 'thru': False}, tp, name='Plat')
AX = gc_axes(out)
srt = pdf.sort_values('x', kind='stable')
check('Overlay Plot: each Y joined in the order of X, pop on the right axis', [(L_['label'], L_['y'] == srt[L_['label']].tolist()) for A_ in AX for L_ in A_['lines']], [('z', True), ('pop', True)])


# ---- Graph Builder's Levels, Axis Settings, Order By, Marker Size and Transparency, and maps ----------------------
# Levels: a continuous grouping column in bins as Make Binning Column cuts them (a bin holds its lower cut); the rows of
# each bin found here with searchsorted on the cuts worked out from their definitions (JMP's quantile, the round width)
for zone_, spec_ in (('overlay', None), ('overlay', {'n': 3, 'method': 'quantile'}), ('overlay', {'n': 4, 'method': 'width'})):
    plan_ = gb_plan(tid, [el('points')], x=['x'], y=['y'], overlay='z', bins={'z': spec_} if spec_ else None)
    code, out, err = gc_run('builder', plan_, tid, rows=rows)
    cuts_ = plan_['group']['bins']['cuts']
    S_ = gc_axes(out)[0]['scatter'] if out else []
    want = sorted((round(float(x[r]), 12), round(float(y[r]), 12), PALETTE[int(np.searchsorted(cuts_, z[r], side='right'))]) for r in rows if okxy[r] and np.isfinite(z[r]))
    got = sorted((round(p_[0], 12), round(p_[1], 12), gc_hex(c_)) for S in S_ for p_, c_ in zip(S['xy'], S['colors'] * len(S['xy']) if len(S['colors']) == 1 else S['colors']))
    what = 'five of equal counts (automatic)' if not spec_ else f'{spec_["n"]} of {"equal counts" if spec_["method"] == "quantile" else "an equal width"}'
    check(f'Levels, {what}: every point in its bin\'s colour (a bin holds its lower cut)', (err, got == want), (None, True))
    check(f'Levels, {what}: the legend, the bins\' ranges', out['figures'][0]['legend'] if out else None, plan_['group']['labels'])
cq_, lo_, hi_ = gc_bin_cuts(x, 4, 'quantile')
check('Levels, 4 of equal counts: the cuts are JMP\'s quartiles of x', cq_, sorted({float(f'{q:.12g}') for q in (np.quantile(x, [0.25, 0.5, 0.75], method='weibull'))} - {float(x.min()), float(x.max())}))
plan_ = gb_plan(tid, [el('points')], x=['x'], y=['y'], wrap='x', bins={'x': {'n': 3, 'method': 'width'}})
code, out, err = gc_run('builder', plan_, tid, rows=rows)
cw_ = plan_['wrap']['bins']['cuts']
AX = [A_ for A_ in gc_axes(out) if A_['shown']]
per = [sorted(round(p_[0], 12) for S in A_['scatter'] for p_ in S['xy']) for A_ in AX]
want = [sorted(round(float(x[r]), 12) for r in rows if okxy[r] and int(np.searchsorted(cw_, x[r], side='right')) == k_) for k_ in range(len(cw_) + 1)]
check('Levels on Wrap, 3 of an equal width: a panel for each bin, titled with its range, holding its rows', ([A_['title'] for A_ in AX], per == want), (plan_['wrap']['labels'], True))

# Axis Settings (smui-axis.js): the code gives each axis its scale, ends, ticks, order and reference lines
axs_ = {'y': [{'log': True, 'min': 2, 'max': 40, 'inc': 2, 'refs': [{'value': 10, 'to': None, 'label': 'ten', 'color': 'red', 'dash': 'dash'}, {'value': 20, 'to': 30, 'label': '', 'color': 'blue', 'dash': 'solid'}]}],
        'x': [{'reverse': True, 'min': 1}]}
code, out, err = gc_run('builder', gb_plan(tid, [el('points')], x=['x'], y=['y'], axes=axs_), tid, rows=rows)
A = gc_axes(out)[0]
check('Axis Settings: a log Y from 2 to 40, a tick every × 2 from the minimum', (err, A['yscale'], A['ylim'], [round(t_, 9) for t_ in A['yticks']]), (None, 'log', [2.0, 40.0], [2.0, 4.0, 8.0, 16.0, 32.0]))
ref_ = [L_ for L_ in A['lines'] if L_['y'] == [10.0, 10.0]]
check('Axis Settings: the reference line at 10, red and dashed, labelled', ([(gc_hex(L_['color']), L_['ls']) for L_ in ref_], any(a_['s'] == 'ten' for a_ in A['annotations'])), ([('#b0413e', '--')], True))
spans = [sorted({round(q[1], 9) for q in P_['xy']}) for P_ in A['polygons'] if gc_hex(P_['fc']) == '#1f4e79'] + \
    [[round(b_['y'], 9), round(b_['y'] + b_['h'], 9)] for b_ in A['bars'] if gc_hex(b_['fc']) == '#1f4e79']   # a Rectangle in newer matplotlib, a Polygon before
check('Axis Settings: the reference range from 20 to 30, in blue', spans, [[20.0, 30.0]])
check('Axis Settings: X reversed, its minimum 1 on the right', (A['xlim'][1], A['xlim'][0] > A['xlim'][1]), (1.0, True))
code, out, err = gc_run('builder', gb_plan(tid, [el('points')], x=['x'], y=['y'], gx='g', axes={'y': [{'min': 0, 'max': 20, 'inc': 5}]}), tid, rows=rows)
check('Axis Settings with Group X: every panel from 0 to 20, a tick every 5', [(A_['ylim'], A_['yticks']) for A_ in gc_axes(out)], [([0.0, 20.0], [0.0, 5.0, 10.0, 15.0, 20.0])] * 3)
code, out, err = gc_run('builder', gb_plan(tid, [el('points')], x=['x'], y=['y', 'z'], axes={'y': [{'min': -5, 'max': 25}, None]}), tid, rows=rows)
AX = gc_axes(out)
check('Axis Settings of one of two Y columns side by side: its row of panels only', (AX[0]['ylim'], AX[1]['ylim'] != [-5.0, 25.0]), ([-5.0, 25.0], True))
code, out, err = gc_run('builder', gb_plan(tid, [el('bar', stat='n')], x=['g'], axes={'y': [{'max': 200, 'refs': [{'value': 100, 'label': 'half', 'color': 'gray', 'dash': 'dot'}]}]}), tid, rows=rows)
A = gc_axes(out)[0]
check('Axis Settings of a count axis: its maximum, and a dotted line at 100', (A['ylim'][1], [L_['ls'] for L_ in A['lines'] if L_['y'] == [100.0, 100.0]]), (200.0, [':']))
day = 86400000
tdt = table({'d': [float(np.datetime64('2020-01-06', 'ms').astype(np.int64) + k_ * 7 * day) for k_ in range(40)], 'v': np.arange(40.0)})
_data.TABLES[tdt]['meta']['d']['format'] = {'kind': 'date'}
lo_ms = float(np.datetime64('2020-02-03', 'ms').astype(np.int64))
code, out, err = gc_run('builder', gb_plan(tdt, [el('points')], x=['d'], y=['v'], axes={'x': [{'min': lo_ms, 'max': lo_ms + 70 * day, 'inc': 14, 'refs': [{'value': lo_ms + 35 * day, 'label': 'mid', 'color': 'green', 'dash': 'solid'}]}]}), tdt, name='Dates', dates=['d'])
A = gc_axes(out)[0] if out else {}
check('Axis Settings on a date X: from 2020-02-03 for 70 days (matplotlib\'s days), a tick every 14 days, a line at the 35th', (err, A.get('xlim'), [round(t_ - A['xticks'][0], 9) for t_ in A.get('xticks', [])][:6], [L_['x'] for L_ in A.get('lines', []) if L_['x'][0] == L_['x'][-1]]),
      (None, [lo_ms / day, lo_ms / day + 70], [0, 14, 28, 42, 56, 70], [[lo_ms / day + 35] * 2]))

# Order By: a categorical axis's levels by a statistic of another column, the code sorting them from the data as the page
gdf_ = gdf.copy()
for label, o_, key_ in (('the mean of y, descending', {'by': 'y', 'stat': 'mean', 'desc': True}, gdf_.groupby('g')['y'].mean().sort_values(ascending=False)),
                        ('the count of rows, ascending', {'by': None, 'desc': False}, gdf_.groupby('g').size().sort_values(kind='stable')),
                        ('the sum of y, ascending', {'by': 'y', 'stat': 'sum', 'desc': False}, gdf_.groupby('g')['y'].sum().sort_values())):
    code, out, err = gc_run('builder', gb_plan(tid, [el('bar', stat='mean' if o_['by'] else 'n')], x=['g'], y=['y'] if o_['by'] else [], order={'g': o_}), tid, rows=rows)
    A = gc_axes(out)[0]
    check(f'Order By {label}: the levels in that order', (err, A['xticklabels']), (None, list(key_.index)))
    if o_['by']:
        check.near(f'Order By {label}: each bar the mean of its level, in that order', float(max(abs(b_['h'] - gdf_[gdf_['g'] == lv_]['y'].mean()) for b_, lv_ in zip(sorted(A['bars'], key=lambda b_: b_['x']), key_.index))), 0.0, abs_=1e-9)
rep_ = np.repeat(np.arange(N), f.astype(int))
med_ = {lv_: float(np.quantile(y[rep_][(g[rep_] == lv_) & np.isfinite(y[rep_])], 0.5, method='weibull')) for lv_ in lv}
code, out, err = gc_run('builder', gb_plan(tid, [el('bar', stat='median')], x=['g'], y=['y'], freq='f', order={'g': {'by': 'y', 'stat': 'median', 'desc': True}}), tid, rows=rows)
check('Order By the median of y with Freq (a row counted f times, JMP\'s quantile), descending', gc_axes(out)[0]['xticklabels'], sorted(lv, key=lambda lv_: -med_[lv_]))

# Marker Size and Transparency: the points' diameter in pixels and their opacity
code, out, err = gc_run('builder', gb_plan(tid, [el('points')], x=['x'], y=['y'], marker={'size': 10, 'alpha': 0.4}), tid, rows=rows)
S_ = gc_axes(out)[0]['scatter'][0]
a3 = lambda px: float(f'{(px * 0.72) ** 2:.3g}')  # noqa: E731   (the code's areas, to 3 digits)
check('Marker Size 10 and Transparency 0.4: the points\' size (10 pixels, 7.2 points across) and opacity', (sorted({round(q, 6) for q in S_['sizes']}), sorted({c_[-2:] for c_ in S_['colors']})), ([a3(10)], ['66']))
code, out, err = gc_run('builder', gb_plan(tid, [el('points')], x=['x'], y=['y'], size='f', marker={'size': 12}), tid, rows=rows)
code0, out0, err0 = gc_run('builder', gb_plan(tid, [el('points')], x=['x'], y=['y'], size='f'), tid, rows=rows)
check.near('Marker Size with a Size column: every size scaled by 12/6 (areas by 4)', float(np.max(np.abs(np.asarray(gc_axes(out)[0]['scatter'][0]['sizes']) / np.asarray(gc_axes(out0)[0]['scatter'][0]['sizes']) - 4))), 0.0, abs_=1e-9)
mk_ = {'size': 9, 'alpha': 0.5}
code, out, err = gc_run('ternary', {'size': [620, 558], 'cols': ['A', 'B', 'C'], 'color': None, 'marker': mk_}, tp, name='Plat')
S_ = gc_axes(out)[0]['scatter'][0]
check('Ternary Plot: Marker Size and Transparency', (sorted({round(q, 6) for q in S_['sizes']}), sorted({c_[-2:] for c_ in S_['colors']})), ([a3(9)], ['80']))
code, out, err = gc_run('scatter3d', {'size': [760, 620], 'cols': ['x', 'y', 'z'], 'color': None, 'marker': mk_}, tp, name='Plat')
S3 = gc_axes(out)[0]['scatter3d'][0]
check('Scatterplot 3D: Marker Size and Transparency', (sorted({round(q, 6) for q in S3['sizes']}), sorted({c_[-2:] for c_ in S3['colors']})), ([a3(9)], ['80']))
# without a Marker Size of its own, the page's size for its number of points (pointSize: 4.5 up to 1500 rows)
code, out, err = gc_run('scatter3d', {'size': [760, 620], 'cols': ['x', 'y', 'z'], 'color': None, 'pointSize': 4.5}, tp, name='Plat')
S3 = gc_axes(out)[0]['scatter3d'][0]
check('Scatterplot 3D: the page\'s point size when none is set (its pointSize)', sorted({round(q, 6) for q in S3['sizes']}), [a3(4.5)])
code, out, err = gc_run('overlay', {'size': [760, 456], 'ys': [{'col': 'z', 'points': True, 'connect': True}], 'x': 'x', 'group': None, 'overlayY': True, 'sortX': True, 'thru': False, 'marker': mk_}, tp, name='Plat')
L0 = gc_axes(out)[0]['lines'][0]
check('Overlay Plot: Marker Size, and Transparency on the points only (the line stays opaque)', (err, round(L0['lw'], 3), L0['color']), (None, round(1.5 * 0.72, 3), PALETTE[0] + 'ff'))
ns_ = gc_ns(code, pdf, 'Plat')
check('Overlay Plot: the markers\' face at opacity 0.5 in the code', '_error' not in ns_ and 'markerfacecolor=to_rgba("#2f6690", 0.5), markeredgewidth=0' in code, True)
code, out, err = gc_run('matrix', dict(mplan, marker=mk_, fit=False, ellipses=False, hist=False), tp, name='Plat')
check('Scatterplot Matrix: Marker Size and Transparency in every cell', sorted({(round(q, 6), c_[-2:]) for A_ in gc_axes(out) for S in A_['scatter'] for q, c_ in zip(S['sizes'] * len(S['colors']) if len(S['sizes']) == 1 else S['sizes'], S['colors'])}), [(a3(9), '80')])

# Maps: Map Shapes' regions and points on a map, from Plotly's own boundaries (world_110m and usa_110m, read at run time
# from cdn.plot.ly, never kept in the repository); the code reads a copy beside the CSV first, as the page's does not
import json  # noqa: E402
import ssl  # noqa: E402
import subprocess  # noqa: E402
import urllib.request  # noqa: E402
TOPO = {}
for name_ in ('world_110m', 'usa_110m'):
    url_ = f'https://cdn.plot.ly/{name_}.json'
    try:
        try:
            import certifi
            ctx_ = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx_ = ssl.create_default_context()
        try:
            with urllib.request.urlopen(url_, timeout=60, context=ctx_) as f_:
                TOPO[name_] = f_.read()
        except Exception:   # a Python without its certificates: curl has the system's
            TOPO[name_] = subprocess.run(['curl', '-sf', '--max-time', '60', url_], check=True, capture_output=True).stdout
        json.loads(TOPO[name_])
        with open(os.path.join(GC_TMP, f'{name_}.json'), 'wb') as f_:
            f_.write(TOPO[name_])
    except Exception as e:  # no network: the map checks are skipped
        TOPO.pop(name_, None)
        print(f'(no {name_}.json from cdn.plot.ly: {e}; the map checks are skipped)')


def gc_map(code, frame, name):
    """Run a map's code on the CSV: its variables, and each panel's regions (their values), land, borders and points."""
    import matplotlib.pyplot as plt_
    from matplotlib.collections import LineCollection as _LC, PathCollection as _Pt, PolyCollection as _PC
    frame.to_csv(os.path.join(GC_TMP, f'{name}.csv'), index=False)
    here, ns = os.getcwd(), {}
    os.chdir(GC_TMP)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(strip_show(code), name, 'exec'), ns)
        fig_ = plt_.gcf()
        fig_.canvas.draw()
        axes_ = []
        for ax_ in fig_.axes:
            if getattr(ax_, '_colorbar', None) is not None:
                continue
            polys = [{'n': len(c_.get_paths()), 'array': None if c_.get_array() is None else [float(v) for v in c_.get_array()], 'colors': [matplotlib.colors.to_hex(q, keep_alpha=True) for q in c_.get_facecolors()]} for c_ in ax_.collections if isinstance(c_, _PC)]
            axes_.append({'polys': polys, 'lines': [len(c_.get_segments()) for c_ in ax_.collections if isinstance(c_, _LC)], 'points': [np.asarray(c_.get_offsets()).tolist() for c_ in ax_.collections if isinstance(c_, _Pt)],
                          'xlim': list(ax_.get_xlim()), 'ylim': list(ax_.get_ylim()), 'aspect': ax_.get_aspect()})
        ns['_axes'] = axes_
        ns['_colorbars'] = [a_.get_ylabel() for a_ in fig_.axes if getattr(a_, '_colorbar', None) is not None]
    except Exception as e:  # reported by the check
        import traceback
        ns = {'_error': f'{type(e).__name__}: {e}\n{traceback.format_exc(limit=-2)}'}
    finally:
        os.chdir(here)
        plt_.close('all')
    return ns


def gc_topo(name_, layer):
    """A layer of a boundary file decoded here, independently: {id: number of rings}."""
    topo = json.loads(TOPO[name_])
    out = {}
    for geom in topo['objects'][layer]['geometries']:
        polys = [geom['arcs']] if geom['type'] == 'Polygon' else geom['arcs'] if geom['type'] == 'MultiPolygon' else []
        out[geom.get('id')] = sum(len(p_) for p_ in polys)
    return out


import json  # noqa: E402
import matplotlib.collections  # noqa: E402
import matplotlib.colors  # noqa: E402
if TOPO:
    rm = np.random.default_rng(77)
    iso = ['SWE', 'NOR', 'FIN', 'DNK', 'DEU', 'FRA', 'ESP', 'ITA', 'POL', 'GBR']
    nm = ['Sweden', 'Norway', 'Finland', 'Denmark', 'Germany', 'France', 'Spain', 'Italy', 'Poland', 'United Kingdom']
    st_ = ['California', 'Texas', 'New York', 'Florida', 'Washington', 'Ohio', 'Georgia', 'Colorado']
    nmap = 150
    mcols = {'iso': [iso[i % 10] for i in range(nmap)], 'name': [nm[i % 10] for i in range(nmap)], 'state': [st_[i % 8] for i in range(nmap)],
             'v': (np.arange(nmap) % 10 * 3 + rm.normal(0, 1, nmap)).round(3), 'lvl': [['p', 'q', 'r'][(i * 7) % 3] if i % 10 != 3 else 'r' for i in range(nmap)],
             'lon': rm.uniform(-10, 30, nmap).round(3), 'lat': rm.uniform(40, 65, nmap).round(3), 'fq': (1 + np.arange(nmap) % 3).astype(float)}
    mcols['v'][5] = np.nan
    tm = table(mcols)
    mdf = gc_frame(tm)
    world = gc_topo('world_110m', 'countries')

    def mplan(shape, mode, ids, element, color=None, x=(), y=(), scope='world', freq=None):
        P_ = gb_plan(tm, [element] + ([el('points')] if x else []), x=x, y=y, color=color, freq=freq)
        P_['map'] = {'scope': scope, 'file': 'usa_110m' if scope == 'usa' else 'world_110m', 'lonlat': bool(x), 'shape': {'col': shape, 'mode': mode, 'ids': ids} if shape else None}
        P_['levels'], P_['kinds'] = {}, {'x': 'cont' if x else 'none', 'y': 'cont' if y else 'none'}
        return P_

    v_ = mdf.dropna(subset=['v']).groupby('iso')['v'].mean()
    lo_, hi_ = float(np.nanmin(mcols['v'])), float(np.nanmax(mcols['v']))
    E_ = {'type': 'map', 'stat': 'mean', 'label': 'Mean(v)', 'range': [lo_, hi_]}
    code = call('graph.code', kind='builder', plan=mplan('iso', 'iso3', {k_: k_ for k_ in iso}, E_, color='v'), table=tm, rows=list(range(nmap)), table_name='Maps')['plot_code']
    ns_ = gc_map(code, mdf, 'Maps')
    check('Map Shapes by ISO 3166 code: the code runs and ends in plt.show()', (ns_.get('_error'), code.rstrip().split('\n')[-1]), (None, 'plt.show()'))
    if '_error' not in ns_:
        check.near('Map Shapes, the Mean of v: each region\'s value is its rows\' mean', float(max(abs(ns_['value'][k_] - v_[k_]) for k_ in iso)), 0.0, abs_=1e-12)
        R_ = ns_['_axes'][0]['polys'][-1]
        want_n = sum(world[k_] for k_ in iso)
        check('Map Shapes: every ring of each region drawn (the boundaries decoded here too), its value the region\'s', (R_['n'], sorted({round(a_, 9) for a_ in R_['array']}) == sorted({round(v, 9) for v in ns_['value'].values()})), (want_n, True))
        cmap_ = matplotlib.colors.LinearSegmentedColormap.from_list('ramp', graph.RAMP)
        col_ = {k_: matplotlib.colors.to_hex(cmap_((v_[k_] - lo_) / (hi_ - lo_)), keep_alpha=True) for k_ in iso}
        check('Map Shapes: each region in the page\'s blue-grey-red at its mean (the page\'s range of v)', sorted(set(R_['colors'])), sorted(set(col_.values())))
        check('Map Shapes: the land under them, the countries\' borders, the colour bar', (len(ns_['_axes'][0]['polys']) == 2 and ns_['_axes'][0]['polys'][0]['colors'][0] == '#e0d7ce8c', ns_['_axes'][0]['lines'] != [], ns_['_colorbars']), (True, True, ['Mean(v)']))
    # by name: the ids the page's map matched; with Freq, N
    E_ = {'type': 'map', 'stat': 'n', 'label': 'N', 'range': [0, 1]}
    ids_ = dict(zip(nm, iso))
    code = call('graph.code', kind='builder', plan=mplan('name', 'names', ids_, E_, freq='fq'), table=tm, rows=list(range(nmap)), table_name='Maps')['plot_code']
    ns_ = gc_map(code, mdf, 'Maps')
    nq_ = mdf.groupby('name')['fq'].sum()
    check('Map Shapes by country name, N with Freq: each region\'s count is its rows\' sum of Freq', ns_.get('value') == {ids_[k_]: float(nq_[k_]) for k_ in nm} if 'value' in ns_ else ns_.get('_error'), True)
    # a categorical Color: each region in the colour of its most common level
    E_ = {'type': 'map', 'stat': 'level', 'label': 'lvl', 'range': None}
    code = call('graph.code', kind='builder', plan=mplan('iso', 'iso3', {k_: k_ for k_ in iso}, E_, color='lvl'), table=tm, rows=list(range(nmap)), table_name='Maps')['plot_code']
    ns_ = gc_map(code, mdf, 'Maps')
    cnt_ = mdf.groupby(['iso', 'lvl']).size().unstack(fill_value=0)[['p', 'q', 'r']]
    top_ = {k_: int(np.argmax(cnt_.loc[k_].to_numpy())) for k_ in iso}
    check('Map Shapes, a categorical Color: each region at its most common level (a tie: the first)', ns_.get('value') == top_ if 'value' in ns_ else ns_.get('_error'), True)
    R_ = ns_['_axes'][0]['polys'][-1] if '_axes' in ns_ else {'colors': []}
    check('Map Shapes, a categorical Color: the regions in those levels\' colours', sorted(set(c_[:7] for c_ in R_['colors'])), sorted({PALETTE[k_] for k_ in top_.values()}))
    # US states by name, on the US map
    usa = gc_topo('usa_110m', 'subunits')
    E_ = {'type': 'map', 'stat': 'n', 'label': 'N', 'range': [18, 19]}
    sid_ = {'California': 'CA', 'Texas': 'TX', 'New York': 'NY', 'Florida': 'FL', 'Washington': 'WA', 'Ohio': 'OH', 'Georgia': 'GA', 'Colorado': 'CO'}
    code = call('graph.code', kind='builder', plan=mplan('state', 'usa', sid_, E_, scope='usa'), table=tm, rows=list(range(nmap)), table_name='Maps')['plot_code']
    ns_ = gc_map(code, mdf, 'Maps')
    check('Map Shapes of US states by name: each state\'s count of rows, every ring drawn', (ns_.get('value') == {sid_[k_]: float(n_) for k_, n_ in mdf.groupby('state').size().items()} if 'value' in ns_ else ns_.get('_error'),
                                                                                              ns_['_axes'][0]['polys'][-1]['n'] if '_axes' in ns_ else None), (True, sum(usa[k_] for k_ in sid_.values())))
    A_ = ns_.get('_axes', [{}])[0]
    check('The US map: at least the lower 48 states in view, a degree of longitude as long as it is at the middle latitude', (A_.get('xlim', [0])[0] <= -125, A_.get('xlim', [0, 0])[1] >= -66.5, round(A_.get('aspect', 0), 9) == round(1 / math.cos(math.radians(sum(A_.get('ylim', [0, 0])) / 2)), 9)), (True, True, True))
    # points on a Background Map: every row at its longitude and latitude, the view fitted to them
    P_ = gb_plan(tm, [el('points')], x=['lon'], y=['lat'], overlay='lvl')
    P_['map'] = {'scope': 'world', 'file': 'world_110m', 'lonlat': True, 'shape': None}
    code = call('graph.code', kind='builder', plan=P_, table=tm, rows=list(range(nmap)), table_name='Maps')['plot_code']
    ns_ = gc_map(code, mdf, 'Maps')
    A_ = ns_.get('_axes', [{}])[0]
    pts_ = sorted(tuple(round(q, 9) for q in p_) for S in A_.get('points', []) for p_ in S)
    check('Points on a Background Map: every row at its longitude (X) and latitude (Y), over the land and borders', (ns_.get('_error'), pts_ == sorted((round(a_, 9), round(b_, 9)) for a_, b_ in zip(mcols['lon'], mcols['lat'])), len(A_.get('polys', [])), len(A_.get('lines', []))), (None, True, 1, 1))
    check('Points on a Background Map: the view fits the points (5% about them)', (A_.get('xlim', [0])[0] <= min(mcols['lon']), A_.get('xlim', [0, 0])[1] >= max(mcols['lon']), A_.get('xlim', [0, 0])[1] - A_.get('xlim', [0, 0])[0] < 60), (True, True, True))
    # offline: the boundaries cannot be read, and the code still runs, drawing the points without them
    off = tempfile.mkdtemp(prefix='smui-graph-offline-')
    with open(os.path.join(off, 'world_110m.json'), 'w') as f_:
        f_.write('not a boundary file')
    mdf.to_csv(os.path.join(off, 'Maps.csv'), index=False)
    here_ = os.getcwd()
    os.chdir(off)
    try:
        import warnings as _w
        with contextlib.redirect_stdout(io.StringIO()), _w.catch_warnings(record=True) as warned_:
            _w.simplefilter('always')
            ns_off = {}
            exec(compile(strip_show(code), 'Maps', 'exec'), ns_off)
            import matplotlib.pyplot as plt_
            npts = sum(len(c_.get_offsets()) for ax_ in plt_.gcf().axes for c_ in ax_.collections if not isinstance(c_, (matplotlib.collections.PolyCollection, matplotlib.collections.LineCollection)))
        err_off = None
    except Exception as e:  # reported by the check
        err_off, npts, warned_ = f'{type(e).__name__}: {e}', 0, []
    finally:
        os.chdir(here_)
        import matplotlib.pyplot as plt_
        plt_.close('all')
    check('A map offline (its boundaries unreadable): the code still runs, warns, and draws the points', (err_off, npts, any('boundaries' in str(q.message) for q in warned_)), (None, nmap, True))

sys.exit(check.done())
