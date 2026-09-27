#!/usr/bin/env python3
"""Analyze > Specialized Modeling > Gaussian Process's backend
(resources/py/smui/gaussproc.py), through registry.dispatch as the page
calls it: the model against scikit-learn's GaussianProcessRegressor called
directly with the same kernel, bounds and seed (and the progress optimizer
against scikit-learn's own); JMP's theta against the RBF kernel; -2
LogLikelihood against scipy's multivariate normal; the jackknife closed
form against refitting without each row; the functional ANOVA against the
exact double sum (1-D moments by scipy quad), against quasi-Monte Carlo of
the model's own predictions, and on the Ishigami function, whose Sobol
indices are known (Ishigami and Homma 1990); the marginal curves, the
profiler's band, Save, the row cap, missing values, the warnings in the
report's words, and the Python shown under the report run on a CSV export.

    python3 resources/tests/smui/test_gaussproc.py
"""
import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd

from backend import FAILED, Checks, call, table

check = Checks()
check('gaussproc.py imports', 'gaussproc' in FAILED, False)
from smui import gaussproc as G, registry  # noqa: E402

try:
    from scipy import integrate, stats
    from scipy.special import erf
    from scipy.stats import qmc
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, ConstantKernel, Matern, WhiteKernel
except ImportError:
    print('scikit-learn 1.8 is needed for these tests (Pyodide 314.0.7 has 1.8.0)')
    sys.exit(1)

G.PROGRESS = False


def mx(a, b):
    return float(np.max(np.abs(np.asarray(a, float) - np.asarray(b, float))))


def ishigami(X, a=7.0, b=0.1):
    return np.sin(X[:, 0]) + a * np.sin(X[:, 1]) ** 2 + b * X[:, 2] ** 4 * np.sin(X[:, 0])


# the Ishigami function's variances on [-pi, pi]^3 (a = 7, b = 0.1)
A_, B_ = 7.0, 0.1
V_ISH = A_ ** 2 / 8 + B_ * math.pi ** 4 / 5 + B_ ** 2 * math.pi ** 8 / 18 + 0.5
S_ISH = {'1': 0.5 * (1 + B_ * math.pi ** 4 / 5) ** 2 / V_ISH, '2': A_ ** 2 / 8 / V_ISH, '3': 0.0, '13': 8 * B_ ** 2 * math.pi ** 8 / 225 / V_ISH}

# ---- registration ---------------------------------------------------------------------------------------------
for fn in ('gaussproc.fit', 'gaussproc.save', 'gaussproc.profile', 'gaussproc.maximize', 'gaussproc.importance'):
    check(f'{fn} is registered and loads scikit-learn first', (fn in registry.names(), json.loads(registry.packages_for(fn))), (True, ['scikit-learn']))

# ---- the tables ---------------------------------------------------------------------------------------------
rng = np.random.default_rng(20260927)
n = 60
Xs = rng.uniform(0, 1, (n, 3)) * np.array([2.0, 10.0, 1.0]) + np.array([0.0, 100.0, -0.5])
fsmooth = np.sin(2 * Xs[:, 0]) + 0.02 * (Xs[:, 1] - 105) ** 2 + 0.8 * Xs[:, 0] * Xs[:, 2]
ynoisy = fsmooth + rng.normal(0, 0.15, n)
ymiss = ynoisy.copy()
ymiss[[2, 9]] = np.nan
x3m = Xs[:, 2].copy()
x3m[[4]] = np.nan
cols = {'y': list(fsmooth), 'yn': list(ynoisy), 'ym': [None if np.isnan(v) else v for v in ymiss], 'x1': list(Xs[:, 0]), 'x2': list(Xs[:, 1]), 'x3': list(Xs[:, 2]),
        'x3m': [None if np.isnan(v) else v for v in x3m], 'g': list(rng.choice(['a', 'b'], n)), 'const': [1.0] * n}
T = table(cols, types={'g': 'nominal'})
XN = ['x1', 'x2', 'x3']


def direct(X, y, corr='gaussian', nugget=False, restarts=0, seed=0, jitter=1e-10):
    """scikit-learn's GaussianProcessRegressor with the report's kernel, called directly (default optimizer)."""
    span, sd = X.max(axis=0) - X.min(axis=0), X.std(axis=0, ddof=1)
    bounds = np.column_stack([1e-3 * span, 1e3 * span])
    base = RBF(sd.copy(), bounds) if corr == 'gaussian' else Matern(sd.copy(), bounds, nu=2.5 if corr == 'matern52' else 1.5)
    k = ConstantKernel(1.0, (1e-4, 1e4)) * base
    if nugget:
        k = k + WhiteKernel(1e-2, (1e-10, 10.0))
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')      # the bounds warnings: the report's own are checked below
        return GaussianProcessRegressor(k, alpha=jitter, normalize_y=True, n_restarts_optimizer=restarts, random_state=seed).fit(X, y)


# ---- the model: scikit-learn's, called directly ----------------------------------------------------------------------------
for yname, corr, nug, rs in (('y', 'gaussian', False, 0), ('yn', 'gaussian', True, 2), ('yn', 'matern52', True, 0), ('y', 'matern32', False, 1)):
    label = f'{yname}, {corr}, nugget {nug}, {rs} restarts'
    r = call('gaussproc.fit', table=T, y=yname, x=XN, correlation=corr, nugget=nug, restarts=rs, seed=17)
    M = G._model(T, None, yname, XN, corr, nug, 400, rs, 17)
    yv = np.asarray(cols[yname], float)
    gp = direct(Xs, yv, corr, nug, rs, 17)
    check.near(f'{label}: the fitted hyperparameters are scikit-learn\'s default fit\'s (the progress optimizer changes nothing)', mx(M.gp.kernel_.theta, gp.kernel_.theta), 0.0, abs_=1e-12)
    check.near(f'{label}: the same log marginal likelihood', M.gp.log_marginal_likelihood_value_, gp.log_marginal_likelihood_value_, 1e-12)
    prod = gp.kernel_.k1 if nug else gp.kernel_
    c, ell = prod.k1.constant_value, np.asarray(prod.k2.length_scale)
    check.near(f'{label}: Length Scale', mx([row['length'] for row in r['report']], ell), 0.0, abs_=1e-9 * float(ell.max()))
    if corr == 'gaussian':
        check.near(f'{label}: Theta = 1/(2 l^2)', mx([row['theta'] for row in r['report']], 1 / (2 * ell ** 2)), 0.0, abs_=1e-12)
    s = yv.std()
    check.near(f'{label}: Mu is the mean of Y (normalize_y)', r['mu'], yv.mean(), 1e-12)
    check.near(f'{label}: Sigma² = the constant kernel times var(Y)', r['sigma2'], c * s ** 2, 1e-10)
    if nug:
        check.near(f'{label}: Nugget = noise / constant', r['nugget'], gp.kernel_.k2.noise_level / c, 1e-9)
    K = gp.kernel_(Xs) + 1e-10 * np.eye(n)
    try:
        ll, how = stats.multivariate_normal(mean=np.full(n, yv.mean()), cov=s ** 2 * K, allow_singular=False).logpdf(yv), 'scipy multivariate_normal'
    except np.linalg.LinAlgError:     # an interpolating fit: K is too ill-conditioned for scipy's check; its Cholesky
        Lc = np.linalg.cholesky(s ** 2 * K)
        z_ = np.linalg.solve(Lc, yv - yv.mean())
        ll, how = -0.5 * z_ @ z_ - np.log(np.diag(Lc)).sum() - n / 2 * math.log(2 * math.pi), 'its Cholesky'
    # an interpolating fit's K is near-singular (condition about 1e14): two Cholesky codes part in the fourth digit
    check.near(f'{label}: -2 LogLikelihood = -2 log N(y; mu, s^2 K) ({how})', r['m2ll'], -2 * ll, 1e-6 if how.startswith('scipy') else 1e-3)
    check(f'{label}: the report names the kernel', r['kernel'], str(M.gp.kernel_))

# JMP's Gaussian correlation is scikit-learn's RBF with theta = 1 / (2 l^2)
M = G._model(T, None, 'yn', XN, 'gaussian', True, 400, 0, 3)
ell = M.ell
theta = 1 / (2 * ell ** 2)
D2 = (Xs[:, None, :] - Xs[None, :, :]) ** 2
R_jmp = np.exp(-np.sum(theta * D2, axis=2))
check.near('JMP\'s exp(-Σ θ (x - x\')²) is scikit-learn\'s RBF correlation', mx(R_jmp, M.base(Xs)), 0.0, abs_=1e-13)

# ---- the jackknife: closed form against refitting without each row -------------------------------------------------------------
for yname, nug in (('yn', True), ('y', False)):
    M = G._model(T, None, yname, XN, 'gaussian', nug, 400, 0, 5)
    jack, jsd = G.jackknife(M.gp, M.yf)
    m, s = M.yf.mean(), M.yf.std()
    yn = (M.yf - m) / s
    brute, bsd = [], []
    for i in range(n):
        keep = np.arange(n) != i
        g1 = GaussianProcessRegressor(M.gp.kernel_, alpha=M.jitter, optimizer=None, normalize_y=False).fit(M.Xf[keep], yn[keep])
        p, sd = g1.predict(M.Xf[[i]], return_std=True)
        brute.append(m + s * p[0])
        bsd.append(s * sd[0])
    tol = 1e-7 if nug else 1e-4 * float(np.ptp(M.yf))
    check.near(f'the jackknife (closed form) = the model refitted without each row, kernel held ({"nugget" if nug else "noiseless"})', mx(jack, brute), 0.0, abs_=tol)
    if nug:
        check.near('its standard deviation = the refitted model\'s predictive sd', mx(jsd, bsd), 0.0, abs_=1e-6)
r = call('gaussproc.fit', table=T, y='yn', x=XN, nugget=True, restarts=0, seed=5)
M = G._model(T, None, 'yn', XN, 'gaussian', True, 400, 0, 5)
jack, _ = G.jackknife(M.gp, M.yf)
check.near('the report\'s jackknife predictions are those', mx(r['jackknife'], jack), 0.0, abs_=1e-12)
res = M.yf - jack
check.near('Jackknife RSquare = 1 - SSE/SST of them', r['jack_rsquare'], 1 - np.sum(res ** 2) / np.sum((M.yf - M.yf.mean()) ** 2), 1e-12)
check.near('Jackknife RASE', r['jack_rase'], math.sqrt(np.mean(res ** 2)), 1e-12)
check('every row fitted, none left to predict', (r['n'], r['n_fit'], r['other_rows'], r['capped']), (n, n, [], False))
check('Optimizer Restarts left empty: 2 for at most 150 rows fitted', call('gaussproc.fit', table=T, y='yn', x=XN, nugget=True, seed=5)['restarts'], 2)

# ---- the functional ANOVA ---------------------------------------------------------------------------------------------------------------
# (1) a surface of Gaussian terms with small weights: the exact double sum, 1-D moments by quad


def exact_sum(Xf, w, ell, lo, hi, moments='quad'):
    """V, the main effects' and the pairs' closed variances of
    sum_i w_i prod_k exp(-(x_k - x_ik)^2 / (2 l_k^2)), each factor uniform:
    the double sums over the terms, with the 1-D moments by quad (or erf)."""
    n_, d = Xf.shape
    W_ = hi - lo
    m1 = np.zeros((n_, d))
    M2 = np.zeros((d, n_, n_))
    for k in range(d):
        for i in range(n_):
            if moments == 'quad':
                m1[i, k] = integrate.quad(lambda t: math.exp(-(t - Xf[i, k]) ** 2 / (2 * ell[k] ** 2)), lo[k], hi[k], epsabs=1e-14, epsrel=1e-13)[0] / W_[k]
            else:
                m1[i, k] = ell[k] * math.sqrt(math.pi / 2) * (erf((hi[k] - Xf[i, k]) / (math.sqrt(2) * ell[k])) - erf((lo[k] - Xf[i, k]) / (math.sqrt(2) * ell[k]))) / W_[k]
            for j in range(i, n_):
                if moments == 'quad':
                    v = integrate.quad(lambda t: math.exp(-((t - Xf[i, k]) ** 2 + (t - Xf[j, k]) ** 2) / (2 * ell[k] ** 2)), lo[k], hi[k], epsabs=1e-14, epsrel=1e-13)[0] / W_[k]
                else:
                    mid = (Xf[i, k] + Xf[j, k]) / 2
                    v = math.exp(-(Xf[i, k] - Xf[j, k]) ** 2 / (4 * ell[k] ** 2)) * ell[k] * math.sqrt(math.pi) / 2 * (erf((hi[k] - mid) / ell[k]) - erf((lo[k] - mid) / ell[k])) / W_[k]
                M2[k, i, j] = M2[k, j, i] = v

    def var_of(keep):
        rest = [j for j in range(d) if j not in keep]
        a = w * np.prod(m1[:, rest], axis=1)
        Gm = np.outer(a, a)
        for j in keep:
            Gm = Gm * M2[j]
        return Gm.sum() - (a @ np.prod(m1[:, list(keep)], axis=1)) ** 2
    V = var_of(list(range(d)))
    main = np.array([var_of([k]) for k in range(d)])
    closed = np.zeros((d, d))
    for k in range(d):
        for j in range(k + 1, d):
            closed[k, j] = closed[j, k] = var_of([k, j])
    return V, main, closed


r3 = np.random.default_rng(7)
Xt = r3.uniform(0, 1, (6, 3)) * np.array([1.0, 4.0, 0.5])
wt = r3.normal(0, 1, 6)
lt = np.array([0.3, 1.5, 0.2])
lo_t, hi_t = np.array([0.0, 0.0, 0.0]), np.array([1.0, 4.0, 0.5])


def f_terms(X):
    return (np.exp(-((X[:, None, :] - Xt[None, :, :]) ** 2) / (2 * lt ** 2)).prod(axis=2)) @ wt


Ve, me, ce = exact_sum(Xt, wt, lt, lo_t, hi_t)
Vq, mq, cq = G.fanova_rbf(Xt, wt, lt, lo_t, hi_t, f_terms, seed=1, m=16)
check.near('fanova_rbf: each main effect\'s variance = the exact double sum (quad moments)', mx(mq, me), 0.0, abs_=1e-11 * Ve)
check.near('... each pair\'s closed variance too', mx(cq[np.triu_indices(3, 1)], ce[np.triu_indices(3, 1)]), 0.0, abs_=1e-11 * Ve)
check.near('... the total variance by 2^16 scrambled Sobol points, to 0.1%', Vq / Ve, 1.0, abs_=1e-3)
Vr, mr, cr = G.fanova_rbf(Xt, wt, lt, lo_t, hi_t, f_terms, seed=1, m=16, refine=2.0)
check.near('twice the quadrature nodes change nothing (the rule is converged)', max(mx(mr, mq), mx(cr, cq)), 0.0, abs_=1e-13 * Ve)
Ve2, me2, ce2 = exact_sum(Xt[:, :2], wt, lt[:2], lo_t[:2], hi_t[:2])
V2, m2_, c2 = G.fanova_rbf(Xt[:, :2], wt, lt[:2], lo_t[:2], hi_t[:2], None, seed=1)
check.near('two factors: the total variance is exact (the pair\'s quadrature)', V2, Ve2, 1e-11 * max(1.0, 1 / Ve2))
V1, m1_, _ = G.fanova_rbf(Xt[:, :1], wt, lt[:1], lo_t[:1], hi_t[:1], None, seed=1)
Ve1, me1, _ = exact_sum(Xt[:, :1], wt, lt[:1], lo_t[:1], hi_t[:1])
check.near('one factor: the total variance is its main effect\'s, exact', V1, Ve1, 1e-11)
Sx, Ix, Tx = G.indices(Ve, me, ce)
check.near('indices: Main Effect = V_k / V', mx(Sx, me / Ve), 0.0, abs_=1e-15)
check.near('indices: Interaction = (V_kl - V_k - V_l) / V', Ix[0, 2], (ce[0, 2] - me[0] - me[2]) / Ve, 1e-15)
check.near('indices: Total Sensitivity = the main effect plus its interactions (JMP\'s)', mx(Tx, Sx + Ix.sum(axis=1)), 0.0, abs_=1e-15)

# (2) the Ishigami function: its known indices by pick-freeze quasi-Monte Carlo
lo_i, hi_i = np.full(3, -math.pi), np.full(3, math.pi)
V_mc, main_mc, closed_mc = G.fanova_mc(ishigami, lo_i, hi_i, seed=3, m=16)
S_mc, I_mc, T_mc = G.indices(V_mc, main_mc, closed_mc)
check.near('fanova_mc on Ishigami: V = a²/8 + bπ⁴/5 + b²π⁸/18 + 1/2', V_mc / V_ISH, 1.0, abs_=0.005)
check.near('... S1 = (1 + bπ⁴/5)²/(2V) = 0.3139', S_mc[0], S_ISH['1'], abs_=0.01)
check.near('... S2 = a²/(8V) = 0.4424', S_mc[1], S_ISH['2'], abs_=0.01)
check.near('... S3 = 0', S_mc[2], 0.0, abs_=0.01)
check.near('... S13 = 8b²π⁸/(225V) = 0.2437', I_mc[0, 2], S_ISH['13'], abs_=0.01)
check.near('... S12 = S23 = 0', max(abs(I_mc[0, 1]), abs(I_mc[1, 2])), 0.0, abs_=0.01)
check.near('... Total Sensitivity of x3 is S13', T_mc[2], S_ISH['13'], abs_=0.015)

# (3) a Gaussian process fitted to 300 runs of Ishigami: the Model Report near the known indices
Xi = lo_i + (hi_i - lo_i) * qmc.LatinHypercube(3, seed=11).random(300)
Ti = table({'y': list(ishigami(Xi)), 'x1': list(Xi[:, 0]), 'x2': list(Xi[:, 1]), 'x3': list(Xi[:, 2])})
ri = call('gaussproc.fit', table=Ti, y='y', x=XN, seed=2)
check('the Ishigami fit has no error', 'error' in ri, False)
if 'error' not in ri:
    rep = {row['column']: row for row in ri['report']}
    check('... and none for more than 150 (it is slow)', ri['restarts'], 0)
    check.near('Ishigami, a GP of 300 runs: the jackknife RSquare is high', ri['jack_rsquare'], 1.0, abs_=0.02)
    check.near('... Main Effect of x1 near 0.3139', rep['x1']['main'], S_ISH['1'], abs_=0.03)
    check.near('... Main Effect of x2 near 0.4424', rep['x2']['main'], S_ISH['2'], abs_=0.03)
    check.near('... Main Effect of x3 near 0', rep['x3']['main'], 0.0, abs_=0.02)
    check.near('... the x1 by x3 interaction near 0.2437', rep['x1']['i2'], S_ISH['13'], abs_=0.04)
    check.near('... the table is symmetric: x3\'s x1 Interaction is x1\'s x3 Interaction', rep['x3']['i0'], rep['x1']['i2'], abs_=1e-12)
    check('... and a factor has no interaction with itself', (rep['x1']['i0'], rep['x2']['i1']), (None, None))
    check.near('... Total Sensitivity = Main Effect + the interactions', max(abs(rw['total'] - rw['main'] - sum(rw[f'i{j}'] for j in range(3) if rw[f'i{j}'] is not None)) for rw in ri['report']), 0.0, abs_=1e-12)
    Mi = G._model(Ti, None, 'y', XN, 'gaussian', False, 400, 0, 2)
    Vm2, mm2, cm2 = G.fanova_mc(Mi.gp.predict, Mi.lo, Mi.hi, seed=9, m=14)
    check.near('... and near the same model\'s pick-freeze estimates (its own surface)', mx(G.indices(Vm2, mm2, cm2)[0], [rep[c]['main'] for c in XN]), 0.0, abs_=0.01)

# (4) a fitted, well-conditioned model: fanova_rbf against the exact double sum (erf moments)
M = G._model(T, None, 'yn', XN, 'gaussian', True, 400, 0, 5)
Vd, md, cd = exact_sum(M.Xf, M.w, M.ell, M.lo, M.hi, moments='erf')
Vg, mg, cg = G.fanova_rbf(M.Xf, M.w, M.ell, M.lo, M.hi, M.gp.predict, seed=5, m=14)
check.near('a fitted model (with a nugget): main effects = the exact double sum', mx(mg, md) / Vd, 0.0, abs_=1e-9)
check.near('... pairs too', mx(cg[np.triu_indices(3, 1)], cd[np.triu_indices(3, 1)]) / Vd, 0.0, abs_=1e-9)
check.near('... the total variance over 2^14 Sobol points, to 0.1%', Vg / Vd, 1.0, abs_=1e-3)
# (5) a noiseless fit: the double sum breaks down (weights near 1e8), the quadrature of values does not
Mq = G._model(T, None, 'y', XN, 'gaussian', False, 400, 0, 5)
Vq_, mq_, cq_ = G.fanova_rbf(Mq.Xf, Mq.w, Mq.ell, Mq.lo, Mq.hi, Mq.gp.predict, seed=5, m=14)
Vmc, mmc, cmc = G.fanova_mc(Mq.gp.predict, Mq.lo, Mq.hi, seed=4, m=15)
check('a noiseless fit has large weights (the reason the double sum is not used)', float(np.max(np.abs(Mq.w))) > 1e3, True)
check.near('... its main effects by quadrature agree with pick-freeze Monte Carlo of its predictions', mx(mq_ / Vq_, mmc / Vmc), 0.0, abs_=0.01)
rq = call('gaussproc.fit', table=T, y='y', x=XN, restarts=0, seed=5)
S_, I_, T_ = G.indices(Vq_, mq_, cq_)
check.near('the report\'s Main Effects are fanova_rbf\'s', mx([row['main'] for row in rq['report']], np.where(np.abs(S_) < 1e-9, 0, S_)), 0.0, abs_=1e-12)
check('the report says how: quadrature', rq['fanova'], 'quadrature')

# ---- the marginal model curves -----------------------------------------------------------------------------------------------
tgrid = np.linspace(M.lo[0], M.hi[0], 7)
curve = G.marginal_rbf(M.Xf, M.w, M.mu, M.ell, M.lo, M.hi, 0, tgrid)
U = qmc.Sobol(3, scramble=True, seed=8).random_base2(13)
Z = M.lo + (M.hi - M.lo) * U
avg = [float(np.mean(M.gp.predict(np.column_stack([np.full(len(Z), t), Z[:, 1], Z[:, 2]])))) for t in tgrid]
check.near('marginal_rbf = the prediction averaged over the other factors (2^13 Sobol points)', mx(curve, avg) / float(np.ptp(M.yf)), 0.0, abs_=2e-3)
rn = call('gaussproc.fit', table=T, y='yn', x=XN, nugget=True, restarts=0, seed=5)
check.near('the report\'s marginal curves are marginal_rbf on 61 points', mx(rn['marginal'][2]['f'], G.marginal_rbf(M.Xf, M.w, M.mu, M.ell, M.lo, M.hi, 2, np.linspace(M.lo[2], M.hi[2], 61))), 0.0, abs_=1e-12)
check('one curve per factor, over its range', [(c_['x'], len(c_['t']), c_['t'][0] == M.lo[k], c_['t'][-1] == M.hi[k]) for k, c_ in enumerate(rn['marginal'])], [(nm, 61, True, True) for nm in XN])
w_leg = np.polynomial.legendre.leggauss(40)
t_ = M.lo[1] + (w_leg[0] + 1) * (M.hi[1] - M.lo[1]) / 2
check.near('the mean of a marginal curve is the mean of the surface', float(w_leg[1] @ G.marginal_rbf(M.Xf, M.w, M.mu, M.ell, M.lo, M.hi, 1, t_) / 2), float(M.mu + M.w @ np.prod(M.ell * math.sqrt(math.pi / 2) * (erf((M.hi - M.Xf) / (math.sqrt(2) * M.ell)) - erf((M.lo - M.Xf) / (math.sqrt(2) * M.ell))) / (M.hi - M.lo), axis=1)), 1e-9)
rmt = call('gaussproc.fit', table=T, y='yn', x=XN, nugget=True, correlation='matern52', restarts=0, seed=5)
Mm = G._model(T, None, 'yn', XN, 'matern52', True, 400, 0, 5)
A = Mm.lo + (Mm.hi - Mm.lo) * qmc.Sobol(6, scramble=True, seed=5).random_base2(12)[:256, :3]
t0 = rmt['marginal'][0]['t'][10]
check.near('Matérn: the marginal curve is the mean prediction over the first 256 Sobol points', rmt['marginal'][0]['f'][10], float(np.mean(Mm.gp.predict(np.column_stack([np.full(256, t0), A[:, 1], A[:, 2]])))), 1e-10)
check('Matérn: the report says how (quasi-Monte Carlo) and has no Theta', (rmt['fanova'], rmt['report'][0]['theta']), ('qmc', None))
Vx, mx_, cx = G.fanova_mc(Mm.gp.predict, Mm.lo, Mm.hi, seed=5, m=12)
check.near('Matérn: the Main Effects are fanova_mc\'s with the seed', mx([row['main'] for row in rmt['report']], mx_ / Vx), 0.0, abs_=1e-12)

# ---- the profiler: the prediction and the band of the process's standard deviation -------------------------------------------------
pr = call('gaussproc.profile', table=T, y='yn', x=XN, nugget=True, restarts=0, seed=5, alpha=0.1, current={'x1': 1.2}, grid=9)
check('the profiler\'s factors: the rows\' ranges and means', [(f['name'], f['min'], f['max']) for f in pr['factors']], [(nm, float(M.lo[k]), float(M.hi[k])) for k, nm in enumerate(XN)])
check.near('the current values: as set, or the mean', abs(pr['factors'][0]['current'] - 1.2) + abs(pr['factors'][1]['current'] - float(M.Xf[:, 1].mean())), 0.0, abs_=1e-12)
cur = np.array([[1.2, pr['factors'][1]['current'], pr['factors'][2]['current']]])
g_ = np.linspace(M.lo[1], M.hi[1], 9)
Xg = np.repeat(cur, 9, axis=0)
Xg[:, 1] = g_
mu_, sd_ = M.gp.predict(Xg, return_std=True)
tr1 = pr['responses'][0]['traces'][1]
z = stats.norm.ppf(0.95)
check.near('a trace is predict() over the factor, the others at their current values', mx(tr1['pred'], mu_), 0.0, abs_=1e-12)
check.near('its band is ± z(1 - α/2) standard deviations (α from the report)', mx(tr1['upper'], mu_ + z * sd_) + mx(tr1['lower'], mu_ - z * sd_), 0.0, abs_=1e-12)
imp = call('gaussproc.importance', table=T, y='yn', x=XN, nugget=True, seed=5, imp_n=256, imp_seed=1)
check('Assess Variable Importance runs on the model (a row per factor)', [row_['column'] for row_ in imp['responses'][0]['rows']], XN)

# ---- Save: every row with the factors, excluded rows too --------------------------------------------------------------------------
sv = call('gaussproc.save', table=T, y='yn', x=['x1', 'x2', 'x3m'], nugget=True, restarts=0, seed=5, rows=list(range(40)))
Ms = G._model(T, list(range(40)), 'yn', ['x1', 'x2', 'x3m'], 'gaussian', True, 400, 0, 5)
ok = ~np.isnan(x3m)
check('Save: every row of the table with every factor (the rows of the report or not)', sv['rows'], np.flatnonzero(ok).tolist())
pm, ps = Ms.gp.predict(np.column_stack([Xs[:, 0], Xs[:, 1], x3m])[ok], return_std=True)
check.near('Save Prediction = predict()', mx(sv['pred'], pm), 0.0, abs_=1e-12)
check.near('Save Std Error = predict(return_std=True)', mx(sv['std'], ps), 0.0, abs_=1e-12)
check('Save Jackknife Predicted Values: the rows fitted', sv['jack_rows'], [i for i in range(40) if ok[i]])

# ---- the rows: a cap, missing values, a row list ----------------------------------------------------------------------------------
rc = call('gaussproc.fit', table=T, y='yn', x=XN, nugget=True, max_rows=25, restarts=0, seed=8)
fit_idx = np.sort(np.random.default_rng(8).choice(n, 25, replace=False))
check('Rows to Fit 25 of 60: a random subset from the seed fits the model', (rc['capped'], rc['n_fit'], rc['fit_rows']), (True, 25, fit_idx.tolist()))
Mc = G._model(T, None, 'yn', XN, 'gaussian', True, 25, 0, 8)
other = np.setdiff1d(np.arange(n), fit_idx)
check('... the other rows are predicted by it', (rc['other_rows'], bool(np.allclose(rc['other_pred'], Mc.gp.predict(Xs[other])))), (other.tolist(), True))
check.near('... the jackknife is of the 25', len(rc['jackknife']), 25, 0)
rm = call('gaussproc.fit', table=T, y='ym', x=['x1', 'x2', 'x3m'], seed=8)
check('rows missing Y or an X are left out and said so', (rm['n'], any('no ym' in t for t in rm['notes']), any('missing a factor' in t for t in rm['notes'])), (n - 3, True, True))
rr = call('gaussproc.fit', table=T, y='yn', x=XN, nugget=True, rows=list(range(0, 60, 2)), seed=8)
check('a row list (a By group, exclusions) limits the fit', (rr['n'], rr['fit_rows'][:3]), (30, [0, 2, 4]))
check('an X that is also the Y: an error', 'error' in call('gaussproc.fit', table=T, y='yn', x=['yn', 'x1']), True)
check('a constant X: an error that names it', call('gaussproc.fit', table=T, y='yn', x=['x1', 'const']).get('error', '').startswith('const has one value'), True)
check('fewer than 3 rows: an error', 'error' in call('gaussproc.fit', table=T, y='yn', x=XN, rows=[0, 1]), True)

# ---- the warnings in the report's words, and the notes ------------------------------------------------------------------------------
rw_ = rng.uniform(0, 1, (40, 2))
Tw = table({'y': list(np.sin(4 * rw_[:, 0])), 'x1': list(rw_[:, 0]), 'x2': list(rw_[:, 1])})
r = call('gaussproc.fit', table=Tw, y='y', x=['x1', 'x2'], seed=1)
check('a factor with no effect: the length scale at its upper bound, said with the column\'s name', any(w.startswith('ConvergenceWarning: x2: the length scale ended at its upper bound') for w in r.get('warnings', [])), True)
check('... its Theta is about 0 and its Main Effect 0', (r['report'][1]['theta'] < 1e-5, abs(r['report'][1]['main']) < 1e-6), (True, True))
tn = table({'y': list(rng.normal(size=50)), 'x1': list(rng.uniform(size=50)), 'x2': list(rng.uniform(size=50))})
r = call('gaussproc.fit', table=tn, y='y', x=['x1', 'x2'], seed=1)
check('pure noise without a nugget: every length scale at its lower bound, and the note says to estimate the nugget', any('Estimate Nugget Parameter' in t for t in r['notes']), True)
td = table({'y': [1.0, 2.0, 1.5, 3.0, 2.5, 2.7], 'x1': [0.0, 0.0, 1.0, 2.0, 3.0, 4.0]})
r = call('gaussproc.fit', table=td, y='y', x=['x1'], seed=1)
check('replicated factor values without a nugget: a note', any('repeat the factor values' in t for t in r.get('notes', [])), True)

# ---- the Python under the report, on a CSV export ---------------------------------------------------------------------------------
work = tempfile.mkdtemp()
pd.DataFrame(cols).to_csv(os.path.join(work, 'data.csv'), index=False)
DUMP = '''
import json
out = {"ell": ell.tolist(), "mu": float(mu), "sigma2": float(c * s ** 2), "m2ll": float(-2 * (gp.log_marginal_likelihood_value_ - len(yf) * np.log(s))),
       "jack": jack.tolist(), "S": S.tolist(), "inter": inter.tolist(), "total": total.tolist(), "curve": np.asarray(curve).tolist(), "fit": np.asarray(d.index[fit]).tolist()}
if "WhiteKernel" in str(gp.kernel_):
    out["nugget"] = float(k.k2.noise_level / c)
print("JSON" + json.dumps(out))
'''
for label, kw in (('Gaussian with a nugget', {'y': 'yn', 'x': XN, 'nugget': True}),
                  ('Gaussian, noiseless, a row list and Rows to Fit 20, one restart', {'y': 'y', 'x': XN, 'rows': list(range(5, 55)), 'max_rows': 20, 'restarts': 1}),
                  ('Matérn 5/2 with a nugget, missing values', {'y': 'ym', 'x': ['x1', 'x2', 'x3m'], 'nugget': True, 'correlation': 'matern52'}),
                  ('one factor, Matérn 3/2', {'y': 'yn', 'x': ['x1'], 'correlation': 'matern32'})):
    r = call('gaussproc.fit', table=T, seed=31, table_name='data', **kw)
    p_ = subprocess.run([sys.executable, '-c', r['code'] + '\n' + DUMP], cwd=work, capture_output=True, text=True, timeout=600)
    if p_.returncode:
        print(p_.stderr[-2500:])
        check(f'the code runs: {label}', p_.returncode, 0)
        continue
    got = json.loads([ln for ln in p_.stdout.splitlines() if ln.startswith('JSON')][-1][4:])
    worst = max(mx(got['ell'], [row['length'] for row in r['report']]) / max(got['ell']),
                abs(got['mu'] - r['mu']) / max(1, abs(r['mu'])), abs(got['sigma2'] - r['sigma2']) / r['sigma2'], abs(got['m2ll'] - r['m2ll']) / max(1, abs(r['m2ll'])),
                mx(got['jack'], r['jackknife']) / max(1, float(np.ptp(r['actual']))),
                mx(got['S'], [row['main'] for row in r['report']]), mx(got['total'], [row['total'] for row in r['report']]),
                mx(got['curve'], r['marginal'][0]['f']) / max(1, float(np.ptp(r['actual']))))
    if 'nugget' in got:
        worst = max(worst, abs(got['nugget'] - r['nugget']) / r['nugget'])
    d = len(r['x'])
    worst = max(worst, max((abs(got['inter'][kk][jj] - r['report'][kk][f'i{jj}']) for kk in range(d) for jj in range(d) if jj != kk), default=0.0))
    # noiseless: the near-singular K turns the CSV's last digits (pandas' parser) into 1e-8
    check.near(f'the code prints the report\'s numbers: {label}', worst, 0.0, abs_=1e-6 if 'noiseless' in label else 1e-9)
    check(f'... and fits the same rows: {label}', got['fit'], r['fit_rows'])

sys.exit(check.done())
