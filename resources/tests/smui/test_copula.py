#!/usr/bin/env python3
"""Analyze > Multivariate Methods > Copulas' backend
(resources/py/smui/copula.py), checked against statsmodels'
distributions.copula called directly (densities, cdfs, Kendall's tau, the
tau inversion, CopulaDistribution, the draws), against closed forms and
numerical integrals (Kendall's tau = 4 E C(U, V) - 1, Spearman's rho =
12 ∫∫C - 3, the tail dependence as a limit, the t copula's cdf), against
scipy's optimisers run here on statsmodels' log densities, on simulated
data with known parameters (the fits near the truth, the right family best
by AIC, the standard errors against the spread of the estimates), and by
running the Python shown under each result on a CSV export of the table.
It also pins the statsmodels 0.14.6 faults the backend works around.

    python3 resources/tests/smui/test_copula.py
"""
import math
import os
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd
from scipy import integrate, optimize, stats
import statsmodels
from statsmodels.distributions.copula.api import (ClaytonCopula, CopulaDistribution, FrankCopula, GaussianCopula,
                                                  GumbelCopula, IndependenceCopula, StudentTCopula)
from statsmodels.distributions.copula.archimedean import tau_frank as sm_tau_frank

from backend import FAILED, Checks, call, table

check = Checks()
check('copula.py imports', 'copula' in FAILED, False)
from smui import copula as C  # noqa: E402
from smui import distribution  # noqa: E402

SM_0146 = statsmodels.__version__ == '0.14.6'
rng = np.random.default_rng(20260927)
G = np.random.default_rng(1).random((400, 2))            # points in the unit square
G3 = np.random.default_rng(2).random((300, 3))
R3 = np.array([[1.0, 0.5, -0.3], [0.5, 1.0, 0.2], [-0.3, 0.2, 1.0]])


def mx(a, b):
    return float(np.max(np.abs(np.asarray(a, float) - np.asarray(b, float))))


# ---- the log densities against statsmodels ------------------------------------------------------------
for r in (-0.8, -0.2, 0.3, 0.9):
    check.near(f'Gaussian log density = statsmodels GaussianCopula(corr={r}).logpdf', mx(C.logpdf('gaussian', G, [r]), GaussianCopula(corr=r).logpdf(G)), 0.0, abs_=1e-10)
check.near('Gaussian log density, three columns = statsmodels', mx(C.logpdf('gaussian', G3, R3[np.triu_indices(3, 1)]), GaussianCopula(corr=R3, k_dim=3).logpdf(G3)), 0.0, abs_=1e-10)
for r, nu in ((0.5, 4.0), (-0.7, 1.5), (0.95, 30.0)):
    check.near(f't log density = statsmodels StudentTCopula(corr={r}, df={nu}).logpdf', mx(C.logpdf('t', G, [r, nu]), StudentTCopula(corr=r, df=nu).logpdf(G)), 0.0, abs_=1e-9)
check.near('t log density, three columns = statsmodels', mx(C.logpdf('t', G3, list(R3[np.triu_indices(3, 1)]) + [5.0]), StudentTCopula(corr=R3, df=5.0, k_dim=3).logpdf(G3)), 0.0, abs_=1e-9)
# far from the diagonal the Gaussian density underflows in statsmodels' pdf form; the log form keeps its value
far = np.array([[0.001, 0.999]])
check('statsmodels\' Gaussian log density underflows far from the diagonal at ρ = 0.999', bool(np.isfinite(GaussianCopula(corr=0.999).logpdf(far)[0])), False)
z = stats.norm.ppf(far[0])
lc = -0.5 * math.log(1 - 0.999 ** 2) - (0.999 ** 2 * (z[0] ** 2 + z[1] ** 2) - 2 * 0.999 * z[0] * z[1]) / (2 * (1 - 0.999 ** 2))
check.near('the log form gives the closed-form value there', float(C.logpdf('gaussian', far, [0.999])[0]), lc, rel=1e-9)
for th in (0.5, 3.0, 12.0):
    check.near(f'Frank log density = statsmodels FrankCopula().logpdf, θ = {th}', mx(C.logpdf('frank', G, [th]), FrankCopula().logpdf(G, args=(th,))), 0.0, abs_=1e-8)
low = G.sum(axis=1) <= 1
check.near('Frank, θ = 25: = statsmodels where u + v ≤ 1', mx(C.logpdf('frank', G[low], [25.0]), FrankCopula().logpdf(G[low], args=(25.0,))), 0.0, abs_=1e-12)
check.near('and = statsmodels at (1 - u, 1 - v) above it (radial symmetry; statsmodels\' own digits go there)', mx(C.logpdf('frank', G[~low], [25.0]), FrankCopula().logpdf(1 - G[~low], args=(25.0,))), 0.0, abs_=1e-12)
check('statsmodels\' Frank at (u, v) and (1 - u, 1 - v) part by more than 1e-6 above u + v = 1 at θ = 25 (its lost digits)', mx(FrankCopula().logpdf(G[~low], args=(25.0,)), FrankCopula().logpdf(1 - G[~low], args=(25.0,))) > 1e-6, True)
for th in (-0.5, -3.0, -12.0):
    check.near(f'Frank log density = log of statsmodels\' pdf, θ = {th}', mx(C.logpdf('frank', G, [th]), np.log(FrankCopula().pdf(G, args=(th,)))), 0.0, abs_=1e-9)
if SM_0146:
    check('statsmodels 0.14.6: FrankCopula.logpdf is NaN for every θ < 0 (the log of a negative number)', bool(np.all(np.isnan(FrankCopula().logpdf(G, args=(-3.0,))))), True)
    corner = np.array([[0.99, 0.995]])
    check('statsmodels 0.14.6: Frank\'s log density near (1, 1) is not finite at θ = 40', bool(np.isfinite(FrankCopula().logpdf(corner, args=(40.0,))[0])), False)
th = 40.0
v = 1 - corner[0]
exact = math.log(th * -math.expm1(-th)) - th * v.sum() - 2 * math.log(-math.expm1(-th) - (-math.expm1(-th * v[0])) * (-math.expm1(-th * v[1])))
check.near('the reflected evaluation gives Frank\'s closed form there (radial symmetry)', float(C.logpdf('frank', np.array([[0.99, 0.995]]), [40.0])[0]), exact, rel=1e-10)
for th in (0.7, 2.5, 9.0):
    a = (1 + th) * np.prod(G, 1) ** (-1 - th) * (np.sum(G ** -th, 1) - 1) ** (-2 - 1 / th)
    check.near(f'Clayton log density = statsmodels = the closed form, θ = {th}', mx(C.logpdf('clayton', G, [th]), np.log(a)), 0.0, abs_=1e-9)
    check.near(f'Gumbel log density = log of statsmodels\' pdf, θ = {1 + th / 3:.3f}', mx(C.logpdf('gumbel', G, [1 + th / 3]), np.log(GumbelCopula().pdf(G, args=(1 + th / 3,)))), 0.0, abs_=1e-9)
flip = {90: np.column_stack([1 - G[:, 0], G[:, 1]]), 180: 1 - G, 270: np.column_stack([G[:, 0], 1 - G[:, 1]])}
for rot, w in flip.items():
    check.near(f'Clayton rotated {rot}°: statsmodels\' density at the turned point', mx(C.logpdf(f'clayton{rot}', G, [2.0]), ClaytonCopula().logpdf(w, args=(2.0,))), 0.0, abs_=1e-12)
    check.near(f'Gumbel rotated {rot}°: statsmodels\' density at the turned point', mx(C.logpdf(f'gumbel{rot}', G, [1.7]), GumbelCopula().logpdf(w, args=(1.7,))), 0.0, abs_=1e-12)
check('independence: log density 0', mx(C.logpdf('indep', G, []), 0.0), 0.0)
check.near('Frank with -θ is Frank with θ turned by 90° (c-θ(u, v) = cθ(u, 1 - v))', mx(C.logpdf('frank', G, [-4.0]), C.logpdf('frank', flip[270], [4.0])), 0.0, abs_=1e-12)

# every density integrates to 1 over the unit square (Gauss-Legendre in the probability scale)
xg, wg = np.polynomial.legendre.leggauss(200)
tg = (xg + 1) / 2
UU, VV = np.meshgrid(tg, tg, indexing='ij')
UV = np.column_stack([UU.ravel(), VV.ravel()])
W2 = np.outer(wg / 2, wg / 2).ravel()
for key, p in (('gaussian', [0.6]), ('t', [0.5, 6.0]), ('frank', [-5.0]), ('frank', [5.0]), ('clayton', [0.8]), ('gumbel', [1.4]), ('clayton90', [0.8]), ('gumbel270', [1.4])):
    check.near(f'{key} {p}: the density integrates to 1', float(np.sum(W2 * np.exp(C.logpdf(key, UV, p)))), 1.0, abs_=2e-3)

# ---- the cdfs ------------------------------------------------------------------------------------------
for th in (0.6, 4.0):
    check.near(f'Clayton cdf = statsmodels, θ = {th}', mx(C.cdf('clayton', G, [th]), ClaytonCopula().cdf(G, args=(th,))), 0.0, abs_=1e-12)
    check.near(f'Gumbel cdf = statsmodels, θ = {1 + th}', mx(C.cdf('gumbel', G, [1 + th]), GumbelCopula().cdf(G, args=(1 + th,))), 0.0, abs_=1e-12)
for th in (-8.0, -1.0, 1.0, 8.0):
    check.near(f'Frank cdf = statsmodels, θ = {th}', mx(C.cdf('frank', G, [th]), FrankCopula(theta=th).cdf(G)), 0.0, abs_=1e-10)
if SM_0146:
    check('statsmodels 0.14.6: Frank\'s cdf near (1, 1) is not finite at θ = 40', bool(np.isfinite(FrankCopula(theta=40.0).cdf(np.array([[0.99, 0.999]]))[0])), False)
Cc = C.cdf('frank', np.array([[0.99, 0.999]]), [40.0])[0]
check('the reflected Frank cdf stays within the Fréchet bounds there', 0.99 + 0.999 - 1 <= Cc <= 0.99, True)
check.near('Gaussian cdf = statsmodels GaussianCopula.cdf', mx(C.cdf('gaussian', G[:50], [0.4]), GaussianCopula(corr=0.4).cdf(G[:50])), 0.0, abs_=1e-12)
mt = stats.multivariate_t(loc=[0, 0], shape=[[1, 0.6], [0.6, 1]], df=4)
qmc = [float(mt.cdf(stats.t.ppf(pt, 4), maxpts=2_000_000, random_state=3)) for pt in G[:8]]
check.near('t copula cdf (quadrature) = scipy multivariate_t.cdf (quasi-Monte Carlo)', mx(C.cdf('t', G[:8], [0.6, 4.0]), qmc), 0.0, abs_=2e-5)
pt = np.array([[0.3, 0.7]])
dq = integrate.dblquad(lambda y, x: mt.pdf([x, y]), -np.inf, stats.t.ppf(0.3, 4), -np.inf, stats.t.ppf(0.7, 4), epsabs=1e-11, epsrel=1e-11)[0]
check.near('t copula cdf = the double integral of the bivariate t density', float(C.cdf('t', pt, [0.6, 4.0])[0]), dq, abs_=1e-8)
if SM_0146:
    try:
        StudentTCopula(corr=0.6, df=4).cdf(pt)
        check('statsmodels 0.14.6: StudentTCopula.cdf is not implemented', False, True)
    except NotImplementedError:
        check('statsmodels 0.14.6: StudentTCopula.cdf is not implemented', True, True)
for key, p in (('clayton90', [2.0]), ('clayton180', [2.0]), ('clayton270', [2.0]), ('gumbel90', [1.8]), ('t', [-0.5, 3.0]), ('frank', [-6.0])):
    b = [float(C.cdf(key, np.array([[0.37, 1.0 - 1e-15]]), p)[0]), float(C.cdf(key, np.array([[1.0 - 1e-15, 0.61]]), p)[0]), float(C.cdf(key, np.array([[0.37, 1e-15]]), p)[0])]
    check.near(f'{key}: C(u, 1) = u, C(1, v) = v, C(u, 0) = 0', mx(b, [0.37, 0.61, 0.0]), 0.0, abs_=1e-6)
    e = 1e-4
    a0 = np.array([[0.4, 0.3]])
    d2 = (C.cdf(key, a0 + [e, e], p) - C.cdf(key, a0 + [e, -e], p) - C.cdf(key, a0 + [-e, e], p) + C.cdf(key, a0 - e, p))[0] / (4 * e * e)
    check.near(f'{key}: the density is the mixed derivative of the cdf', float(d2), float(np.exp(C.logpdf(key, a0, p))[0]), rel=2e-4)

# ---- Kendall's tau ------------------------------------------------------------------------------------------
for th in (0.5, 2.0, 7.0):
    m = C.measures('clayton', [th])
    check.near(f'Clayton τ = θ/(θ + 2) = statsmodels\' tau, θ = {th}', m['tau'], th / (th + 2), rel=1e-12)
    check.near(f'Gumbel τ = 1 - 1/θ = statsmodels\' tau, θ = {1 + th}', C.measures('gumbel', [1 + th])['tau'], GumbelCopula().tau(theta=1 + th), rel=1e-12)
for r in (-0.6, 0.2, 0.85):
    check.near(f'Gaussian and t τ = (2/π) asin ρ, ρ = {r}', C.measures('t', [r, 5.0])['tau'], 2 / np.pi * math.asin(r), rel=1e-12)


def tau_numeric(key, p):
    """4 ∫∫ C dC - 1 by 200 x 200 Gauss-Legendre."""
    return float(4 * np.sum(W2 * C.cdf(key, UV, p) * np.exp(C.logpdf(key, UV, p))) - 1)


for key, p in (('frank', [4.0]), ('frank', [-10.0]), ('frank', [0.4]), ('clayton', [1.5]), ('gumbel', [2.2]), ('gaussian', [0.5]), ('clayton90', [1.5])):
    check.near(f'{key} {p}: τ = 4 E C(U, V) - 1 (numerically)', C.measures(key, p)['tau'], tau_numeric(key, p), abs_=2e-3)
if SM_0146:
    check('statsmodels 0.14.6: tau_frank(-10) is not a correlation (its series diverges below θ = -1)', abs(float(sm_tau_frank(-10.0))) > 1, True)
check.near('Frank τ(-θ) = -τ(θ) here', C.tau_frank(-10.0), -float(sm_tau_frank(10.0)), rel=1e-12)

# ---- Spearman's rho -------------------------------------------------------------------------------------------
def rho_dblquad(key, p):
    return 12 * integrate.dblquad(lambda v, u: float(C.cdf(key, np.array([[u, v]]), p)[0]), 0, 1, 0, 1, epsabs=1e-10, epsrel=1e-10)[0] - 3


for key, p in (('frank', [5.0]), ('frank', [-8.0]), ('clayton', [3.0]), ('gumbel', [1.9]), ('gaussian', [0.7])):
    check.near(f'{key} {p}: Spearman\'s ρ = 12 ∫∫C - 3 (scipy dblquad)', C.measures(key, p)['rho_s'], rho_dblquad(key, p), abs_=1e-7)
for r, nu in ((0.5, 4.0), (0.8, 1.0), (-0.6, 3.0)):
    two_d = float(12 * np.sum(W2 * C.t2_cdf(UV, r, nu)) - 3)
    check.near(f't copula ρ_S from its mixture form = 12 ∫∫C - 3, ρ = {r}, ν = {nu}', C.rho_t(r, nu), two_d, abs_=2e-6)
    if SM_0146:
        check(f'statsmodels 0.14.6: the t copula\'s spearmans_rho is the Gaussian copula\'s (6/π) asin(ρ/2), ρ = {r}, ν = {nu}',
              abs(float(StudentTCopula(corr=r, df=nu).spearmans_rho()) - 6 / np.pi * math.asin(r / 2)) < 1e-12 and abs(C.rho_t(r, nu) - 6 / np.pi * math.asin(r / 2)) > 5e-3, True)
xt = StudentTCopula(corr=0.5, df=4.0).rvs(300_000, random_state=np.random.default_rng(9))
check.near('t copula ρ_S against 300 000 draws of statsmodels\' rvs', C.rho_t(0.5, 4.0), float(stats.spearmanr(xt[:, 0], xt[:, 1])[0]), abs_=0.004)
check.near('rotated 90°: ρ_S and τ change sign', C.measures('gumbel90', [2.0])['rho_s'], -C.measures('gumbel', [2.0])['rho_s'], rel=1e-12)

# ---- tail dependence ------------------------------------------------------------------------------------------
q = 1e-9
check.near('Clayton λL = 2^(-1/θ) = lim C(q, q)/q', C.measures('clayton', [1.3])['lambda_l'], float(ClaytonCopula().cdf(np.array([[q, q]]), args=(1.3,))[0] / q), rel=1e-6)
q = 1e-7
check.near('Gumbel λU = 2 - 2^(1/θ) = lim (1 - 2(1 - q) + C(1 - q, 1 - q))/q', C.measures('gumbel', [1.8])['lambda_u'], float((1 - 2 * (1 - q) + GumbelCopula().cdf(np.array([[1 - q, 1 - q]]), args=(1.8,))[0]) / q), rel=1e-4)
r, nu = 0.5, 4.0
x = stats.t.ppf(1e-13, nu)
h = stats.t.cdf((x - r * x) / math.sqrt((nu + x * x) * (1 - r * r) / (nu + 1)), nu + 1)
check.near('t λ = 2 t_ν+1(-√((ν + 1)(1 - ρ)/(1 + ρ))) = the limit of 2 P(V ≤ u | U = u)', C.t_tail(r, nu), 2 * float(h), rel=1e-5)
if SM_0146:
    check('statsmodels 0.14.6: StudentTCopula.dependence_tail is not that (it divides by 1 for 1 + ρ)', abs(float(StudentTCopula(corr=r, df=nu).dependence_tail()[0]) - C.t_tail(r, nu)) > 0.05, True)
m = C.measures('clayton90', [2.0])
check('Clayton 90°: no diagonal tails, its lower tail in the lower right corner', (m['lambda_l'], m['lambda_u'], m['lambda_lr'] > 0.7, m['lambda_ul']), (0.0, 0.0, True, 0.0))
m = C.measures('gumbel180', [2.0])
check.near('survival Gumbel: its tail moves to the lower corner', m['lambda_l'], 2 - 2 ** 0.5, rel=1e-12)
m = C.measures('t', [-0.4, 3.0])
check.near('t with ρ < 0: the off-diagonal corners carry λ(-ρ)', m['lambda_ul'], C.t_tail(0.4, 3.0), rel=1e-12)

# ---- tau inversion: statsmodels' theta_from_tau, and Frank for negative tau ------------------------------------------------
for tau in (-0.6, -0.2, 0.2, 0.6):
    th = C.from_tau('frank', tau)
    check.near(f'Frank θ(τ = {tau}) has that τ', C.tau_frank(th), tau, abs_=1e-9)
if SM_0146:
    th_sm = FrankCopula().theta_from_tau(-0.5)
    check('statsmodels 0.14.6: FrankCopula.theta_from_tau(-0.5) misses (its τ is not -0.5)', abs(C.tau_frank(th_sm) + 0.5) > 1e-3, True)
u_c = C.pobs(C.rvs('clayton', 800, [2.0], np.random.default_rng(4)))
f = C.fit_family('clayton', u_c, 'itau')
check.near('Clayton by τ = statsmodels ClaytonCopula().fit_corr_param', f['values'][0], float(ClaytonCopula().fit_corr_param(u_c)), rel=1e-12)
f = C.fit_family('gumbel', u_c, 'itau')
check.near('Gumbel by τ = statsmodels GumbelCopula().fit_corr_param', f['values'][0], float(GumbelCopula().fit_corr_param(u_c)), rel=1e-12)
f = C.fit_family('gaussian', u_c, 'itau')
check.near('Gaussian by τ = statsmodels GaussianCopula().fit_corr_param', f['values'][0], float(GaussianCopula().fit_corr_param(u_c)), rel=1e-12)
check('Clayton by τ with negative τ: not applicable', 'error' in C.fit_family('clayton', 1 - np.column_stack([u_c[:, 0], 1 - u_c[:, 1]]), 'itau'), True)

# ---- maximum pseudo-likelihood --------------------------------------------------------------------------------------------------
# against scipy's optimiser run here on statsmodels' own log densities
for key, sm_ll, lo, hi in (('clayton', lambda t: ClaytonCopula().logpdf(u_c, args=(t,)).sum(), 1e-3, 40), ('gumbel', lambda t: GumbelCopula().logpdf(u_c, args=(t,)).sum(), 1.0001, 20),
                           ('frank', lambda t: np.log(FrankCopula().pdf(u_c, args=(t,))).sum(), 0.01, 40), ('gaussian', lambda t: GaussianCopula(corr=t).logpdf(u_c).sum(), -0.99, 0.99)):
    ref = optimize.minimize_scalar(lambda t: -sm_ll(t), bounds=(lo, hi), method='bounded', options={'xatol': 1e-10}).x
    f = C.fit_family(key, u_c, 'mpl')
    check.near(f'{key}: the maximum pseudo-likelihood estimate = scipy\'s bounded search on statsmodels\' log density', f['values'][0], float(ref), rel=1e-6)
    check.near(f'{key}: and its log likelihood', f['loglik'], float(sm_ll(ref)), rel=1e-9)
ft = C.fit_family('t', u_c, 'mpl')
ref = optimize.minimize(lambda v: -StudentTCopula(corr=math.tanh(v[0]), df=math.exp(v[1])).logpdf(u_c).sum(), [0.7, 1.5], method='Nelder-Mead', options={'xatol': 1e-10, 'fatol': 1e-12, 'maxiter': 5000})
check.near('t: ρ = Nelder-Mead on statsmodels\' StudentTCopula log density', ft['values'][0], math.tanh(ref.x[0]), rel=1e-5)
check.near('t: ν too', ft['values'][1], math.exp(ref.x[1]), rel=1e-4)
check.near('t: the log likelihood', ft['loglik'], -ref.fun, rel=1e-9)
# the Hessian standard error = 1/sqrt(-d²l/dθ²) by a central difference written here
f = C.fit_family('clayton', u_c, 'mpl')
t0, hh = f['values'][0], 1e-4
d2 = (ClaytonCopula().logpdf(u_c, args=(t0 + hh,)).sum() - 2 * ClaytonCopula().logpdf(u_c, args=(t0,)).sum() + ClaytonCopula().logpdf(u_c, args=(t0 - hh,)).sum()) / hh ** 2
check.near('Clayton Hessian standard error = 1/√(−l″) by a central difference', f['se'][0], 1 / math.sqrt(-d2), rel=1e-4)

# the Standard Errors option: the reported standard error and interval follow it
rh = call('copula.fit', table=table({'a': u_c[:, 0], 'b': u_c[:, 1]}), columns=['a', 'b'], se='hessian')
rr = call('copula.fit', table=table({'a': u_c[:, 0], 'b': u_c[:, 1]}), columns=['a', 'b'], se='rank')
fh = next(x for x in rh['fits'] if x['family'] == 'clayton')
fr_ = next(x for x in rr['fits'] if x['family'] == 'clayton')
check('Standard Errors = Hessian: the reported standard error is the Hessian\'s', (fh['se'] == fh['se_hessian'], rh['se_kind']), (True, 'hessian'))
check('Standard Errors = Rank-Corrected: the rank-corrected one, larger, and so the interval', (fr_['se'] == fr_['se_rank'], fr_['se'][0] > fh['se'][0], fr_['params'][0]['upper'] > fh['params'][0]['upper'], rr['se_kind']), (True, True, True, 'rank'))
check('both are in the parameter rows either way', (fh['params'][0]['se_rank'] == fr_['se_rank'][0], fr_['params'][0]['se_hessian'] == fh['se'][0]), (True, True))

# known truth: each family fitted to 3000 draws of itself
for key, p in (('gaussian', [0.6]), ('t', [0.5, 4.0]), ('clayton', [2.0]), ('frank', [-5.0]), ('gumbel', [1.8]), ('clayton90', [1.5]), ('gumbel180', [2.5]), ('gumbel270', [1.6])):
    ut = C.pobs(C.rvs(key, 3000, p, np.random.default_rng(11)))
    tid = table({'a': ut[:, 0], 'b': ut[:, 1]})
    res = call('copula.fit', table=tid, columns=['a', 'b'], rotations='all', se='rank')
    ff = next(x for x in res['fits'] if x['family'] == key)
    zmax = max(abs(e - t) / s for e, t, s in zip(ff['values'], p, ff['se']))
    check(f'{key} {p}: the estimates within 3.5 rank-corrected standard errors of the truth ({[round(v, 3) for v in ff["values"]]})', zmax < 3.5, True)
    check(f'{key} {p}: the true family has the smallest AIC', res['best'], key)

# the standard errors against the spread of the estimates (200 samples of 400)
est, sh, sr, si, ti, ts = [], [], [], [], [], []
g5 = np.random.default_rng(5)
for _ in range(200):
    ub = C.pobs(C.rvs('clayton', 400, [2.0], g5))
    fm = C.fit_family('clayton', ub, 'mpl')
    fi = C.fit_family('clayton', ub, 'itau')
    est.append(fm['values'][0]); sh.append(fm['se'][0]); sr.append(fm['se_rank'][0]); si.append(fi['se'][0])
    ti.append(fi['values'][0]); ts.append(C.tau_se(ub))
sd = np.std(est, ddof=1)
check('Clayton: the Hessian standard error is too small (below 80% of the spread): it ignores the ranks', np.mean(sh) / sd < 0.8, True)
check('Clayton: the rank-corrected standard error matches the spread (ratio 0.85 to 1.15)', 0.85 < np.mean(sr) / sd < 1.15, True)
check('Clayton by τ: the delta-method standard error matches the spread of its estimates', 0.85 < np.mean(si) / np.std(ti, ddof=1) < 1.15, True)
tau_hat = [t / (t + 2) for t in ti]      # Clayton's θ from τ is 2τ/(1 - τ): τ back from it
check('Kendall\'s τ: its U-statistic standard error matches the spread of τ (ratio 0.85 to 1.15)', 0.85 < np.mean(ts) / np.std(tau_hat, ddof=1) < 1.15, True)

# three columns
u3 = C.rvs('t', 1500, list(R3[np.triu_indices(3, 1)]) + [5.0], np.random.default_rng(6), k=3)
tid3 = table({'p': u3[:, 0], 'q': u3[:, 1], 'r': u3[:, 2]})
r3 = call('copula.fit', table=tid3, columns=['p', 'q', 'r'])
check('three columns: Gaussian, t and independence only', sorted(f_['family'] for f_ in r3['fits']), ['gaussian', 'indep', 't'])
f3 = next(f_ for f_ in r3['fits'] if f_['family'] == 't')
check('three columns: the t copula has the smallest AIC', r3['best'], 't')
check('three columns: the correlations and ν near the truth (0.5, -0.3, 0.2; 5)', max(abs(a - b) for a, b in zip(f3['values'][:3], [0.5, -0.3, 0.2])) < 0.06 and abs(f3['values'][3] - 5) < 1.5, True)
fg3 = next(f_ for f_ in r3['fits'] if f_['family'] == 'gaussian')
v3 = C.pobs(u3)
grad = optimize.approx_fprime(np.array(fg3['values']), lambda q_: C.gauss_logpdf(v3, C.corr_matrix(q_, 3)).sum(), 1e-6)
check('three columns: the Gaussian fit is a maximum (its gradient is 0)', float(np.max(np.abs(grad))) < 0.05, True)
check('three columns: one Pseudo-observation list per column', (len(r3['u']), len(r3['u'][0])), (3, 1500))
check('three columns: three pairs of rank correlations', [(d['i'], d['j']) for d in r3['dependence']], [(0, 1), (0, 2), (1, 2)])

# ---- the fit call: families, rotations, rows, missing values, ties ---------------------------------------------------------------
check('rotations auto, τ > 0: Clayton and Gumbel with their survival copulas', C.chosen_families(None, 'auto', 0.3, 2), ['indep', 'gaussian', 't', 'clayton', 'clayton180', 'frank', 'gumbel', 'gumbel180'])
check('rotations auto, τ < 0: their 90° and 270° rotations', C.chosen_families(None, 'auto', -0.3, 2), ['indep', 'gaussian', 't', 'clayton90', 'clayton270', 'frank', 'gumbel90', 'gumbel270'])
check('rotations none', C.chosen_families(['clayton', 'gumbel'], 'none', -0.3, 2), ['clayton', 'gumbel'])
check('rotations all', len(C.chosen_families(['clayton', 'gumbel'], 'all', 0.3, 2)), 8)
xa = rng.normal(size=60)
ya = xa + rng.normal(size=60)
ya[[3, 17]] = np.nan
xa[25] = np.nan
xt_ = np.round(xa, 1)
tm = table({'x': xt_, 'y': ya})
rm = call('copula.fit', table=tm, columns=['x', 'y'])
ok = np.isfinite(xt_) & np.isfinite(ya)
check('rows with a missing value are left out, and counted', (rm['n'], rm['n_missing']), (int(ok.sum()), 3))
check('the pseudo-observations are rankdata (ties averaged)/(n + 1)', mx(rm['u'][0], stats.rankdata(xt_[ok]) / (ok.sum() + 1)), 0.0)
check('ties are counted', rm['ties'][0], int(ok.sum() - len(np.unique(xt_[ok]))))
check('the rows used are the page\'s', rm['rows'], [int(i) for i in np.flatnonzero(ok)])
rs = call('copula.fit', table=tm, columns=['x', 'y'], rows=list(range(30)))
check('a row list (a By group, exclusions) limits the fit', rs['n'], int(ok[:30].sum()))
check('one column: an error', 'error' in call('copula.fit', table=tm, columns=['x']), True)
check('too few rows: an error', 'error' in call('copula.fit', table=tm, columns=['x', 'y'], rows=[0, 1, 2, 4]), True)
tconst = table({'x': xa, 'c': np.ones(60)})
check('a column with a single value: an error that names it', call('copula.fit', table=tconst, columns=['x', 'c']).get('error', '').startswith('c has a single value'), True)
r3c = call('copula.fit', table=tid3, columns=['p', 'q', 'r'], families=['clayton', 'frank'])
check('three columns with only one-pair families ticked: nothing to fit, no error', (r3c.get('error'), r3c['fits'], r3c['best']), (None, [], None))
ri = call('copula.fit', table=tm, columns=['x', 'y'], families=['indep'])
check('independence alone: log likelihood 0, no parameter', (ri['fits'][0]['loglik'], ri['fits'][0]['k'], ri['fits'][0]['aic']), (0.0, 0, 0.0))

# ---- the Python shown runs on a CSV export and gives the report's numbers ---------------------------------------------------------
work = tempfile.mkdtemp()


def run(code):
    p_ = subprocess.run([sys.executable, '-c', code], cwd=work, capture_output=True, text=True, timeout=600)
    if p_.returncode:
        print(p_.stderr[-2000:])
    return p_


def printed(out):
    got = {}
    for ln in out.splitlines():
        t = ln.split()
        if t and t[0] in ('fit', 'measures', 'rank_se'):
            got[f'{t[0]} {t[1]}'] = [float(v) for v in t[2:]]
        elif t and t[0] == 'pair':
            got[f'pair {t[1]} {t[2]}'] = [float(v) for v in t[3:]]
    return got


def compare(res, got, label):
    worst, n = 0.0, 0
    for d in res['dependence']:
        g = got.get(f'pair {d["i"]} {d["j"]}')
        w = [d['tau'], d['tau_p'], d['tau_se'], d['rho'], d['rho_p']]
        worst = max(worst, max(abs(a - b) / max(1e-300, abs(b)) if b else abs(a) for a, b in zip(g, w)))
        n += 1
    for f_ in res['fits']:
        if 'error' in f_ or f_['family'] == 'indep' or f_.get('bound'):
            continue
        pairs = [(got[f'fit {f_["family"]}'], f_['values'] + f_['se_hessian'] + [f_['loglik']])]
        if 'se_rank' in f_:
            pairs.append((got[f'rank_se {f_["family"]}'], f_['se_rank']))
        if res['k'] == 2:
            m_ = f_['measures'][0]
            pairs.append((got[f'measures {f_["family"]}'], [m_['tau'], m_['rho_s'], m_['lambda_l'], m_['lambda_u']]))
        for g, w in pairs:
            worst = max(worst, max(abs(a - b) / max(1e-12, abs(b)) for a, b in zip(g, w)))
            n += 1
    check.near(f'{label}: the code prints the report\'s numbers ({n} groups of numbers)', worst, 0.0, abs_=1e-12)


uc = C.rvs('clayton', 400, [2.0], np.random.default_rng(3))
xc = stats.gamma(2.0, scale=1.5).ppf(uc[:, 0])
yc = stats.lognorm(0.5, scale=math.exp(1.0)).ppf(uc[:, 1])
cols = {'soil moisture (%)': np.round(xc, 3), 'flow "m3/s"': yc}
tc = table(cols)
pd.DataFrame(cols).to_csv(os.path.join(work, 'data.csv'), index=False)
for kw in ({'method': 'mpl'}, {'method': 'itau'}, {'method': 'mpl', 'rotations': 'all', 'se': 'rank'}):
    res = call('copula.fit', table=tc, columns=list(cols), table_name='data', **kw)
    p_ = run(res['code'])
    check(f'the Copula Comparison code runs ({kw})', p_.returncode, 0)
    if not p_.returncode:
        compare(res, printed(p_.stdout), str(kw))
res = call('copula.fit', table=tc, columns=list(cols), rows=list(range(0, 400, 2)), table_name='data')
p_ = run(res['code'])
check('the code with a row list runs', p_.returncode, 0)
if not p_.returncode:
    compare(res, printed(p_.stdout), 'rows 0, 2, 4, …')
un = C.rvs('frank', 300, [-4.0], np.random.default_rng(8))
pd.DataFrame({'a': un[:, 0], 'b': un[:, 1]}).to_csv(os.path.join(work, 'neg.csv'), index=False)
tn = table({'a': un[:, 0], 'b': un[:, 1]})
for method in ('mpl', 'itau'):
    res = call('copula.fit', table=tn, columns=['a', 'b'], method=method, table_name='neg')
    p_ = run(res['code'])
    check(f'negative dependence: the code runs ({method})', p_.returncode, 0)
    if not p_.returncode:
        compare(res, printed(p_.stdout), f'negative dependence, {method}')
pd.DataFrame({'p': u3[:, 0], 'q': u3[:, 1], 'r': u3[:, 2]}).to_csv(os.path.join(work, 'three.csv'), index=False)
for method in ('mpl', 'itau'):
    res = call('copula.fit', table=tid3, columns=['p', 'q', 'r'], method=method, table_name='three')
    p_ = run(res['code'])
    check(f'three columns: the code runs ({method})', p_.returncode, 0)
    if not p_.returncode:
        compare(res, printed(p_.stdout), f'three columns, {method}')

# ---- density grids for the contours ---------------------------------------------------------------------------------------------------------
d = call('copula.density', family='clayton', params=[2.0], scale='uniform', m=80)
Z = np.array(d['z'], dtype=float)
check.near('the uniform grid holds the density: its mean is about 1', float(np.nanmean(Z)), 1.0, abs_=0.02)
check.near('the grid is statsmodels\' density at its points', float(Z[10, 30]), float(ClaytonCopula().pdf(np.array([[d['x'][30], d['y'][10]]]), args=(2.0,))[0]), rel=1e-10)
lv = [x['level'] for x in d['levels']]
check('on the unit square the levels are densities around 1 (1/8 … 32), sorted', all(x['kind'] == 'density' for x in d['levels']) and set(lv) <= set(C.UNIT_LEVELS) and lv == sorted(lv) and 1.0 not in lv, True)
check('each drawn level holds at least 0.4% of the square above it (below it under 1)', all((np.mean(Z >= l) if l > 1 else np.mean(Z <= l)) >= 0.004 for l in lv), True)
check('Clayton θ = 2: 1/2 and 2, 4 are drawn (8 holds too little of the square)', {0.5, 2.0, 4.0} <= set(lv) and 8.0 not in lv, True)
dn = call('copula.density', family='gaussian', params=[0.5], scale='normal', m=60)
g_ = np.array(dn['x'])
Zn = np.array(dn['z'], dtype=float)
check.near('normal scores: the density is the bivariate normal\'s', float(Zn[20, 35]), float(stats.multivariate_normal(cov=[[1, 0.5], [0.5, 1]]).pdf([g_[35], g_[20]])), rel=1e-9)
ln = [x['level'] for x in dn['levels']]
check('normal scores: highest-density levels, falling as the mass rises (50, 75, 90, 95%)', [x['p'] for x in dn['levels']] == [0.5, 0.75, 0.9, 0.95] and all(x['kind'] == 'hdr' for x in dn['levels']) and ln == sorted(ln, reverse=True), True)
check.near('the 50% level encloses half the grid\'s mass', float(np.sum(Zn[Zn >= ln[0]]) / np.sum(Zn)), 0.5, abs_=0.01)
rho2 = 0.5
q50 = math.exp(-stats.chi2.ppf(0.5, 2) / 2) / (2 * math.pi * math.sqrt(1 - rho2 ** 2))
check.near('and is the bivariate normal\'s 50% ellipse: exp(−χ²₂(0.5)/2)/(2π√(1 − ρ²))', ln[0], q50, rel=0.02)
check('independence: a flat density, no contours', call('copula.density', family='indep', params=[], scale='uniform')['levels'], [])

# ---- margins -----------------------------------------------------------------------------------------------------------------------
mg = call('copula.margins', table=tc, columns=list(cols), table_name='data')
x0 = np.round(xc, 3)
for c_, xv in zip(mg['columns'], (x0, yc)):
    ref_ = {k_: distribution._fit_one(xv, k_) for k_ in C.MARGINS}
    ref_ = {k_: v_ for k_, v_ in ref_.items() if 'error' not in v_}
    best_ = min(ref_, key=lambda k_: ref_[k_]['aicc'])
    check(f'{c_["column"]}: the margin with the smallest AICc is chosen ({best_})', c_['chosen']['dist'], best_)
    check.near(f'{c_["column"]}: its parameters are Distribution\'s fit', mx(c_['chosen']['values'], [p_['estimate'] for p_ in ref_[best_]['params']]), 0.0, abs_=1e-12)
check('the gamma column is gamma or Weibull, the lognormal one lognormal', (mg['columns'][0]['chosen']['dist'] in ('gamma', 'weibull'), mg['columns'][1]['chosen']['dist']), (True, 'lognormal'))
me = call('copula.margins', table=tc, columns=list(cols), choice={'flow "m3/s"': 'empirical', 'soil moisture (%)': 'normal'})
check('a chosen margin, and the empirical one', (me['columns'][0]['chosen']['dist'], me['columns'][1]['chosen']['dist']), ('normal', 'empirical'))
p_ = run(mg['code'])
check('the Margins code runs', p_.returncode, 0)
if not p_.returncode:
    lines = [ln for ln in p_.stdout.splitlines() if ln.strip()]
    check('and prints one line per column', len(lines), 2)
emp = C.Empirical(yc)
check.near('the empirical margin: F at the i-th smallest value is i/(n + 1)', float(emp.cdf(np.sort(yc)[99])), 100 / 401, rel=1e-12)
check.near('its quantiles are np.quantile(method="weibull") (JMP\'s)', float(emp.ppf(0.37)), float(np.quantile(yc, 0.37, method='weibull')), rel=1e-12)

# ---- the joint distribution: statsmodels' CopulaDistribution ---------------------------------------------------------------------------
specs = [{'dist': c_['chosen']['dist'], 'values': c_['chosen']['values']} for c_ in mg['columns']]
fr = call('copula.fit', table=tc, columns=list(cols))
fc = next(f_ for f_ in fr['fits'] if f_['family'] == 'clayton')
th = fc['values'][0]
margins_sm = [C.frozen(s_['dist'], s_['values']) for s_ in specs]
jd = call('copula.joint', table=tc, columns=list(cols), family='clayton', params=[th], margins=specs, m=50)
cd = CopulaDistribution(ClaytonCopula(theta=th), margins_sm)
ptj = np.array([[jd['x'][20], jd['y'][15]]])
check.near('joint density on the grid = statsmodels CopulaDistribution(ClaytonCopula, margins).pdf', float(np.array(jd['z'])[15, 20]), float(cd.pdf(ptj)[0]), rel=1e-9)
pr = call('copula.prob', table=tc, columns=list(cols), family='clayton', params=[th], margins=specs, x=2.5, y=3.0)
check.near('P(X ≤ x, Y ≤ y) = CopulaDistribution.cdf', pr['model']['le'], float(cd.cdf(np.array([[2.5, 3.0]]))[0]), rel=1e-12)
u_, v_ = margins_sm[0].cdf(2.5), margins_sm[1].cdf(3.0)
check.near('P(Y > y | X > x) = (1 - u - v + C)/(1 - u)', pr['model']['gt_gt'], (1 - u_ - v_ + pr['model']['le']) / (1 - u_), rel=1e-12)
check.near('independence: P(both ≤) = uv', pr['indep']['le'], u_ * v_, rel=1e-12)
lx, ly = x0 <= 2.5, yc <= 3.0
check.near('the observed share of both ≤', pr['observed']['le'], float(np.mean(lx & ly)), rel=1e-12)
check.near('the observed P(Y > y | X > x)', pr['observed']['gt_gt'], float(np.sum(~lx & ~ly) / np.sum(~lx)), rel=1e-12)
pr0 = call('copula.prob', table=tc, columns=list(cols), family='clayton', params=[th], margins=specs)
check.near('without a point: the medians', pr0['x'], float(np.median(x0)), rel=1e-12)
pt_ = call('copula.prob', table=tc, columns=list(cols), family='t', params=[0.6, 4.0], margins=specs, x=2.5, y=3.0)
ref_t = float(mt.cdf(stats.t.ppf([u_, v_], 4), maxpts=2_000_000, random_state=5))
check.near('the t copula\'s P(X ≤ x, Y ≤ y) = scipy multivariate_t.cdf at the margins\' quantiles', pt_['model']['le'], ref_t, abs_=2e-5)

# ---- simulation: statsmodels' draws, repeatable, and the code gives the same table ---------------------------------------------------------
sm_ = call('copula.simulate', table=tc, columns=list(cols), family='clayton', params=[th], margins=specs, n=700, seed=42, table_name='data')
ref_sim = CopulaDistribution(ClaytonCopula(theta=th), margins_sm).rvs(700, random_state=np.random.default_rng(42))
check.near('Simulate = statsmodels CopulaDistribution(ClaytonCopula(θ), margins).rvs(n, random_state=default_rng(seed))', mx(np.array(sm_['values']).T, ref_sim), 0.0, abs_=0.0)
check('the same seed, the same table', call('copula.simulate', table=tc, columns=list(cols), family='clayton', params=[th], margins=specs, n=700, seed=42)['values'] == sm_['values'], True)
p_ = run(sm_['code'] + '\nprint(repr(sim.to_numpy().tolist()))')
check('the Simulate code runs', p_.returncode, 0)
if not p_.returncode:
    got = np.array(eval(p_.stdout.strip().splitlines()[-1]))
    check.near('and makes the same table', mx(got, np.array(sm_['values']).T), 0.0, abs_=0.0)
for key, p in (('frank', [-6.0]), ('frank', [60.0]), ('gumbel90', [2.0]), ('clayton270', [3.0]), ('t', [0.5, 4.0]), ('gaussian', [-0.4]), ('indep', [])):
    s_ = call('copula.simulate', table=tc, columns=list(cols), family=key, params=p, scale='uniform', n=20000, seed=3, table_name='data')
    a_ = np.array(s_['values']).T
    tau_want = C.measures(key, p)['tau']
    check.near(f'{key} {p}: 20 000 draws have Kendall\'s τ {tau_want:.3f}', float(stats.kendalltau(a_[:, 0], a_[:, 1])[0]), tau_want, abs_=0.012)
    p_ = run(s_['code'] + '\nprint(repr(sim.to_numpy()[:50].tolist()))')
    ok_ = p_.returncode == 0 and mx(np.array(eval(p_.stdout.strip().splitlines()[-1])), a_[:50]) == 0.0
    check(f'{key}: the Simulate code makes the same draws', ok_, True)
if SM_0146:
    try:
        FrankCopula(theta=-6.0).rvs(5, random_state=1)
        check('statsmodels 0.14.6: FrankCopula.rvs fails for θ < 0', False, True)
    except Exception:
        check('statsmodels 0.14.6: FrankCopula.rvs fails for θ < 0', True, True)
w_ = np.random.default_rng(0).random((5, 2))
check.near('Frank\'s conditional inverse = statsmodels ppfcond_2g1 (θ = 5 and -5)',
           max(mx(C.frank_ppfcond(w_[:, 1], w_[:, 0], t_), FrankCopula().ppfcond_2g1(w_[:, 1:], w_[:, :1], args=(t_,)).ravel()) for t_ in (5.0, -5.0)), 0.0, abs_=1e-12)
se_ = call('copula.simulate', table=tc, columns=list(cols), family='gaussian', params=[0.5], margins=[{'dist': 'empirical'}, {'dist': 'empirical'}], n=300, seed=2, table_name='data')
a_ = np.array(se_['values']).T
check('empirical margins: the draws are within the data\'s range', bool(a_[:, 0].min() >= x0.min() and a_[:, 1].max() <= yc.max()), True)
p_ = run(se_['code'] + '\nprint(repr(sim.to_numpy().tolist()))')
check('the Simulate code with empirical margins makes the same table', p_.returncode == 0 and mx(np.array(eval(p_.stdout.strip().splitlines()[-1])), a_) < 1e-12, True)
s3 = call('copula.simulate', table=tid3, columns=['p', 'q', 'r'], family='t', params=f3['values'], scale='uniform', n=4000, seed=1)
a3 = np.array(s3['values']).T
check('three columns: draws of the fitted t copula, correlated as it is', abs(float(stats.kendalltau(a3[:, 0], a3[:, 2])[0]) - 2 / np.pi * math.asin(f3['values'][1])) < 0.03, True)
check('too many draws: an error', 'error' in call('copula.simulate', table=tc, columns=list(cols), family='indep', params=[], n=2_000_000), True)

# ---- goodness of fit ------------------------------------------------------------------------------------------------------------------
ug = C.pobs(C.rvs('clayton', 150, [2.0], np.random.default_rng(12)))
tg_ = table({'a': ug[:, 0], 'b': ug[:, 1]})
gf = call('copula.gof', table=tg_, columns=['a', 'b'], families=['clayton', 'gaussian', 'gumbel', 'indep'], rotations='none', B=60, seed=4)
byf = {r_['family']: r_ for r_ in gf['rows']}
check.near('Sn = Σ (Cn(Ui) - C(Ui))² by hand', byf['clayton']['S'], float(np.sum((np.array([np.mean((ug[:, 0] <= a) & (ug[:, 1] <= b)) for a, b in ug]) - ClaytonCopula().cdf(ug, args=(C.fit_family('clayton', ug)['values'][0],))) ** 2)), rel=1e-10)
check('data from Clayton: Clayton is not rejected (p > 0.1)', byf['clayton']['p'] > 0.1, True)
check('and independence is (p < 0.02)', byf['indep']['p'] < 0.02, True)
check('p = (#{Sn* ≥ Sn} + 1/2)/(B + 1) takes those values', all(abs(r_['p'] * (r_['B'] + 1) - 0.5 - round(r_['p'] * (r_['B'] + 1) - 0.5)) < 1e-9 for r_ in gf['rows']), True)
check('the same seed, the same p-values', call('copula.gof', table=tg_, columns=['a', 'b'], families=['clayton', 'gaussian', 'gumbel', 'indep'], rotations='none', B=60, seed=4)['rows'] == gf['rows'], True)
# the size of the test: data from the Gaussian copula, 25 samples of 120, B = 40
pv = []
for s in range(25):
    ux = C.pobs(C.rvs('gaussian', 120, [0.5], np.random.default_rng(1000 + s)))
    tx = table({'a': ux[:, 0], 'b': ux[:, 1]})
    pv.append(call('copula.gof', table=tx, columns=['a', 'b'], families=['gaussian'], B=40, seed=s)['rows'][0]['p'])
check(f'the test holds its size: of 25 Gaussian samples, few p < 0.05 ({sum(p_ < 0.05 for p_ in pv)}), and p spreads over (0, 1) (mean {np.mean(pv):.2f})', sum(p_ < 0.05 for p_ in pv) <= 4 and 0.3 < np.mean(pv) < 0.7, True)
check('three columns: no goodness of fit', 'error' in call('copula.gof', table=tid3, columns=['p', 'q', 'r']), True)

# ---- tail concentration ------------------------------------------------------------------------------------------------------------------
tl = call('copula.tails', table=tc, columns=list(cols), fits=[{'family': 'clayton', 'params': [th]}])
qq = np.array(tl['q'])
uu = C.pobs(np.column_stack([x0, yc]))
emp_ = [np.mean((uu[:, 0] <= a) & (uu[:, 1] <= a)) / a if a <= 0.5 else np.mean((uu[:, 0] > a) & (uu[:, 1] > a)) / (1 - a) for a in qq]
check.near('the data\'s tail concentration by hand', mx(tl['empirical'], emp_), 0.0, abs_=1e-12)
cq = ClaytonCopula().cdf(np.column_stack([qq, qq]), args=(th,))
check.near('the fit\'s: C(q, q)/q and (1 - 2q + C(q, q))/(1 - q)', mx(tl['fits'][0]['values'], np.where(qq <= 0.5, cq / qq, (1 - 2 * qq + cq) / (1 - qq))), 0.0, abs_=1e-12)

# ---- the graphs' matplotlib code, run with Agg on the CSV, against the report's numbers ----------------------------------
from test_charts import run_snippet_more  # noqa: E402

chart_dir = tempfile.mkdtemp(prefix='smui-copula-charts-')
CONTOUR_C = '#b0413eff'


def cop_graph(kind, plot, label, tid_, frame_, columns, method='mpl', names=(), rows=None):
    rr = call('copula.plot_code', table=tid_, columns=columns, kind=kind, plot=plot, method=method, rows=rows)
    code = rr.get('plot_code') or ''
    check(f'{label}: the code is written', rr.get('error'), None)
    out, err = run_snippet_more(code, frame_, 'data', chart_dir, names=names)
    check(f'{label}: the code runs', err, None)
    check(f'{label}: it ends with plt.show()', code.rstrip().split('\n')[-1] if code else None, 'plt.show()')
    check(f'{label}: one figure', len(out['figures']) if out else 0, 1)
    return (out['figures'][0] if out and out['figures'] else None), (out['vars'] if out else {}), code


def rel_gap(a, b):
    a, b = np.asarray(a, dtype=float).ravel(), np.asarray(b, dtype=float).ravel()
    if a.shape != b.shape:
        return float('inf')
    ok = np.isfinite(a) & np.isfinite(b)
    if not np.array_equal(np.isfinite(a), np.isfinite(b)):
        return float('inf')
    return float(np.max(np.abs(a[ok] - b[ok]) / np.maximum(1e-300, np.maximum(np.abs(a[ok]), np.abs(b[ok]))))) if ok.any() else 0.0


def contour_levels(A):
    return [p_['contour'][0] for p_ in A['polys'] if 'contour' in p_]


def nice_bins_c(v):
    lo, hi = float(np.min(v)), float(np.max(v))
    k = max(5, min(40, math.ceil(math.log2(len(v)) + 1)))
    raw = (hi - lo) / k
    p_ = 10 ** math.floor(math.log10(raw))
    size = min((m_ * p_ for m_ in (1, 2, 2.5, 5, 10)), key=lambda s_: abs(math.log(s_ / raw)))
    start = math.floor(lo / size) * size
    end = math.ceil(hi / size) * size
    if end <= hi:
        end += size
    return {'start': start, 'end': end, 'size': size}


cnames = list(cols)
cframe = pd.DataFrame(cols)
for method in ('mpl', 'itau'):
    frc = call('copula.fit', table=tc, columns=cnames, method=method, rotations='all')
    oks = [f_ for f_ in frc['fits'] if 'error' not in f_]
    U = np.array(frc['u']).T
    for f_ in oks:
        for scale in ('uniform', 'normal'):
            if method == 'itau' and scale == 'normal' and f_['family'] not in ('clayton', 't'):
                continue
            lab = f'pseudo-observations, {f_["family"]} ({method}, {scale})'
            F, V, code = cop_graph('pseudo', {'family': f_['family'], 'pair': [0, 1], 'scale': scale, 'n': frc['n']}, lab, tc, cframe, cnames, method, names=('params', 'z', 'levels'))
            if not F:
                continue
            A = F['axes'][0]
            check.near(f'{lab}: the code\'s fit is the report\'s', rel_gap(V.get('params') or [], f_['values']) if f_['values'] else 0.0, 0.0, abs_=1e-9)
            pts = np.asarray(A['scatter'][0]['xy'])
            want = stats.norm.ppf(U) if scale == 'normal' else U
            check.near(f'{lab}: the points are the report\'s pseudo-observations', rel_gap(pts, want), 0.0, abs_=1e-12)
            dn_ = call('copula.density', family=f_['family'], params=f_['values'], scale=scale)
            want_lv = [x['level'] for x in dn_['levels']]
            if f_['family'] == 'indep':
                check(f'{lab}: no contours', contour_levels(A), [])
                continue
            check.near(f'{lab}: the density grid is the report\'s', rel_gap(V.get('z'), dn_['z']), 0.0, abs_=1e-7)
            check.near(f'{lab}: the contour levels are the report\'s', rel_gap(contour_levels(A), want_lv), 0.0, abs_=1e-7)
            if scale == 'uniform':
                check(f'{lab}: labelled, as the page\'s density contours', len(A['texts']) > 0 or not want_lv, True)
            check(f'{lab}: the titles', (A['xlabel'], A['title']), (f'{cnames[0]}: {"normal score" if scale == "normal" else "rank/(n + 1)"}', f'Pseudo-observations of {cnames[0]} and {cnames[1]}'))
    # the tail concentration of every fitted copula (the page leaves the independence copula out)
    fams = [f_['family'] for f_ in oks if f_['family'] != 'indep']
    F, V, code = cop_graph('tails', {'fits': fams, 'pair': [0, 1]}, f'tail concentration ({method})', tc, cframe, cnames, method)
    tl = call('copula.tails', table=tc, columns=cnames, pair=[0, 1], fits=[{'family': f_['family'], 'params': f_['values']} for f_ in oks if f_['family'] != 'indep'])
    if F:
        axs = [a_ for a_ in F['axes'] if a_['title']]
        check(f'tail concentration ({method}): a panel for each copula, titled as the page', [a_['title'] for a_ in axs], [C.LABEL[k_] for k_ in fams])
        ok_d = all(rel_gap([p_[1] for p_ in a_['scatter'][0]['xy']], tl['empirical']) < 1e-12 and rel_gap([p_[0] for p_ in a_['scatter'][0]['xy']], tl['q']) < 1e-12 for a_ in axs)
        check(f'tail concentration ({method}): the data\'s dots in every panel, the report\'s', ok_d, True)
        worst = max(rel_gap([ln for ln in a_['lines'] if ln['color'] == CONTOUR_C][0]['y'], m_['values']) for a_, m_ in zip(axs, tl['fits']))
        check.near(f'tail concentration ({method}): each copula\'s line, the report\'s', worst, 0.0, abs_=1e-8)
        check(f'tail concentration ({method}): the dotted line at q = ½, the ranges', all([ln['x'] for ln in a_['lines'] if ln['ls'] == ':'] == [[0.5, 0.5]] and a_['xlim'] == [0.0, 1.0] and a_['ylim'] == [0.0, 1.02] for a_ in axs), True)
# the joint model and the margins, with the margins chosen by AICc and others
for choice in ({}, {'soil moisture (%)': 'normal', 'flow "m3/s"': 'empirical'}, {'soil moisture (%)': 'weibull', 'flow "m3/s"': 't'}):
    mg_ = call('copula.margins', table=tc, columns=cnames, choice=choice)
    specs_ = [{'dist': c_['chosen']['dist'], 'values': c_['chosen']['values']} for c_ in mg_['columns']]
    dists_ = {str(q): c_['chosen']['dist'] for q, c_ in enumerate(mg_['columns'])}
    tag = '/'.join(dists_.values())
    frc = call('copula.fit', table=tc, columns=cnames)
    for fam in ('clayton', 'gumbel180', 'indep'):
        f_ = next(x for x in frc['fits'] if x.get('family') == fam)
        lab = f'joint model, {fam} with {tag} margins'
        F, V, code = cop_graph('joint', {'family': fam, 'pair': [0, 1], 'margins': dists_}, lab, tc, cframe, cnames, names=('z', 'gx', 'gy'))
        if not F:
            continue
        A = F['axes'][0]
        jd = call('copula.joint', table=tc, columns=cnames, family=fam, params=f_['values'], margins=specs_, pair=[0, 1])
        check.near(f'{lab}: the data\'s points', rel_gap(A['scatter'][0]['xy'], np.column_stack([cols[cnames[0]], cols[cnames[1]]])), 0.0, abs_=1e-12)
        # the code fits the margins by scipy's maximum likelihood (as the Margins code shows), the report by Distribution's refinement of
        # it: the same maximum (a Weibull's log likelihoods agree to 5e-8), a flat one, so the densities agree to about 1e-3 in the grid's corners
        check.near(f'{lab}: the grid, the report\'s', max(rel_gap(V.get('gx'), jd['x']), rel_gap(V.get('gy'), jd['y'])), 0.0, abs_=1e-6)
        check.near(f'{lab}: the joint density on it, the report\'s', rel_gap(V.get('z'), jd['z']), 0.0, abs_=1e-3)
        check.near(f'{lab}: the highest-density levels, the report\'s', rel_gap(contour_levels(A), [x['level'] for x in jd['levels']]), 0.0, abs_=1e-3)
        check(f'{lab}: the titles', (A['xlabel'], A['ylabel'], A['title']), (cnames[0], cnames[1], f'{cnames[0]} and {cnames[1]} with the joint model'))
    for q, c_ in enumerate(mg_['columns']):
        xv = np.asarray(cols[cnames[q]], dtype=float)
        bins = nice_bins_c(xv)
        lab = f'{c_["column"]} histogram with its {c_["chosen"]["dist"]} margin'
        F, V, code = cop_graph('margin', {'column': q, 'dist': c_['chosen']['dist'], 'bins': bins}, lab, tc, cframe, cnames)
        if not F:
            continue
        A = F['axes'][0]
        nb = max(1, round((bins['end'] - bins['start']) / bins['size']))
        cnt = np.zeros(nb)
        for v in xv:
            cnt[min(nb - 1, max(0, math.floor((v - bins['start']) / bins['size'] + 1e-9)))] += 1
        check(f'{lab}: the bars count the rows in the page\'s bins', [b_['h'] for b_ in A['bars']], cnt.tolist())
        cv = c_['chosen']['curve']
        ln = A['lines'][0] if A['lines'] else {'x': [], 'y': []}
        check.near(f'{lab}: the curve is the report\'s margin as counts per bin', max(rel_gap(ln['x'], cv['x']), rel_gap(ln['y'], np.asarray(cv['pdf']) * len(xv) * bins['size'])), 0.0, abs_=1e-3)
        check(f'{lab}: the titles', (A['xlabel'], A['ylabel'], A['title']), (c_['column'], 'Count', f'{c_["column"]} histogram with its margin'))
    # simulated draws of the joint model: the report's (the same seed), on the data scale and the copula's
    for fam, sc_ in (('clayton', 'data'), ('frank', 'uniform'), ('t', 'data'), ('gumbel180', 'data')):
        f_ = next(x for x in frc['fits'] if x.get('family') == fam)
        lab = f'simulated and observed, {fam} ({sc_}, {tag} margins)'
        F, V, code = cop_graph('simulate', {'family': fam, 'pair': [0, 1], 'margins': dists_, 'n': 300, 'seed': 7, 'scale': sc_, 'n_obs': frc['n']}, lab, tc, cframe, cnames)
        if not F:
            continue
        A = F['axes'][0]
        sim_ = call('copula.simulate', table=tc, columns=cnames, family=fam, params=f_['values'], margins=specs_ if sc_ == 'data' else None, n=300, seed=7, scale=sc_)
        got = [x for x in A['scatter'] if x['label'] == 'Simulated']
        check.near(f'{lab}: the draws are the report\'s', rel_gap(got[0]['xy'] if got else [], np.column_stack(sim_['values'][:2])), 0.0, abs_=1e-9 if sc_ == 'uniform' else 1e-3)
        obs = [x for x in A['scatter'] if x['label'] == 'Observed']
        want = np.array(frc['u']).T if sc_ == 'uniform' else np.column_stack([cols[cnames[0]], cols[cnames[1]]])
        check.near(f'{lab}: the observed rows', rel_gap(obs[0]['xy'] if obs else [], want), 0.0, abs_=1e-12)
        check(f'{lab}: the legend and the title', (F['legend'], A['title']), (['Simulated', 'Observed'], f'Simulated and observed {cnames[0]} and {cnames[1]}'))
# three columns: the scatterplot matrix, and a pair of the fit's margins
fr3 = call('copula.fit', table=tid3, columns=['p', 'q', 'r'])
frame3 = pd.DataFrame({'p': u3[:, 0], 'q': u3[:, 1], 'r': u3[:, 2]})
U3 = np.array(fr3['u']).T
for fam in ('gaussian', 't'):
    f_ = next(x for x in fr3['fits'] if x.get('family') == fam)
    for scale in ('uniform', 'normal'):
        lab = f'scatterplot matrix, {fam} ({scale})'
        F, V, code = cop_graph('splom', {'family': fam, 'scale': scale, 'size': 120, 'n': fr3['n']}, lab, tid3, frame3, ['p', 'q', 'r'], names=('params',))
        if not F:
            continue
        check.near(f'{lab}: the code\'s fit is the report\'s', rel_gap(V.get('params'), f_['values']), 0.0, abs_=1e-7)
        vis = [a_ for a_ in F['axes'] if a_['shown']]
        check(f'{lab}: the lower triangle, three cells', len(vis), 3)
        ok_p, ok_l = True, True
        cells = [(c_, r_) for r_ in range(1, 3) for c_ in range(r_)]
        for a_, (c_, r_) in zip(vis, cells):
            want = stats.norm.ppf(U3) if scale == 'normal' else U3
            ok_p &= rel_gap(a_['scatter'][0]['xy'], want[:, [c_, r_]]) < 1e-12
            qq = C.bivariate(fam, f_['values'], c_, r_, 3)
            dn_ = call('copula.density', family=fam, params=qq, scale=scale, m=40)
            ok_l &= rel_gap(contour_levels(a_), [x['level'] for x in dn_['levels']]) < 1e-6
        check(f'{lab}: each cell\'s points, the report\'s pseudo-observations', ok_p, True)
        check(f'{lab}: each cell\'s contours, the report\'s pair margin\'s levels', ok_l, True)
        check(f'{lab}: the column names on the edges, the title', ([a_['xlabel'] for a_ in vis], [a_['ylabel'] for a_ in vis], F['suptitle']),
              (['', 'p', 'q'], ['q', 'r', ''], 'Scatterplot matrix of the pseudo-observations'))
    lab = f'pseudo-observations of q and r, {fam} (three columns)'
    F, V, code = cop_graph('pseudo', {'family': fam, 'pair': [1, 2], 'scale': 'uniform', 'n': fr3['n']}, lab, tid3, frame3, ['p', 'q', 'r'], names=('z',))
    if F:
        dn_ = call('copula.density', family=fam, params=C.bivariate(fam, f_['values'], 1, 2, 3), scale='uniform')
        check.near(f'{lab}: the pair\'s margin of the fit, the report\'s density', rel_gap(V.get('z'), dn_['z']), 0.0, abs_=1e-6)
        check.near(f'{lab}: the points', rel_gap(F['axes'][0]['scatter'][0]['xy'], U3[:, [1, 2]]), 0.0, abs_=1e-12)
# the report's rows (a row list) and negative dependence
rows_ = list(range(0, 400, 2))
frc = call('copula.fit', table=tc, columns=cnames, rows=rows_)
f_ = next(x for x in frc['fits'] if x.get('family') == 'clayton')
F, V, code = cop_graph('pseudo', {'family': 'clayton', 'pair': [0, 1], 'scale': 'uniform'}, 'pseudo-observations of every other row', tc, cframe, cnames, rows=rows_, names=('params',))
if F:
    check('every other row: the code keeps the report\'s rows', 'df = df.loc[' in code, True)
    check.near('every other row: its fit is the report\'s', rel_gap(V.get('params'), f_['values']), 0.0, abs_=1e-9)
    check.near('every other row: the points', rel_gap(F['axes'][0]['scatter'][0]['xy'], np.array(frc['u']).T), 0.0, abs_=1e-12)
frn = call('copula.fit', table=tn, columns=['a', 'b'])
for fam in [x['family'] for x in frn['fits'] if 'error' not in x and x['family'] in ('clayton90', 'gumbel270', 'frank')]:
    f_ = next(x for x in frn['fits'] if x['family'] == fam)
    F, V, code = cop_graph('pseudo', {'family': fam, 'pair': [0, 1], 'scale': 'uniform'}, f'negative dependence, {fam}', tn, pd.DataFrame({'a': un[:, 0], 'b': un[:, 1]}), ['a', 'b'], names=('params', 'levels'))
    if F:
        dn_ = call('copula.density', family=fam, params=f_['values'], scale='uniform')
        check.near(f'negative dependence, {fam}: the fit and the levels are the report\'s', max(rel_gap(V.get('params'), f_['values']), rel_gap(contour_levels(F['axes'][0]), [x['level'] for x in dn_['levels']])), 0.0, abs_=1e-7)
check('an unknown graph is refused', 'error' in call('copula.plot_code', table=tc, columns=cnames, kind='pie'), True)
check('an unknown copula is refused', 'error' in call('copula.plot_code', table=tc, columns=cnames, kind='pseudo', plot={'family': 'nope'}), True)

sys.exit(check.done())
