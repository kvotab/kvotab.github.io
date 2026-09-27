"""Analyze > Multivariate Methods > Copulas: the backend.

A copula is the joint distribution of the ranks of some columns: what is
left of their dependence once each column's own distribution is taken
away. The platform works on pseudo-observations, u = rank/(n + 1) with
ties averaged (R copula's pobs), and fits the copula families of
statsmodels.distributions.copula to them:

  Independence   C(u, v) = uv, the reference
  Gaussian       any number of columns (a correlation matrix)
  Student t      any number of columns (a correlation matrix and ν)
  Clayton        lower-tail dependence; Frank (none, and negative τ too);
  Gumbel         upper-tail dependence; for two columns
  rotations      Clayton and Gumbel turned by 180° (survival), 90° or 270°
                 (negative dependence), as VineCopula defines them

Two estimators. statsmodels offers the inversion of Kendall's τ
(fit_corr_param, theta_from_tau, corr_from_tau) and no likelihood fit;
maximum pseudo-likelihood (Genest, Ghoudi and Rivest 1995) is written
here: the log density of statsmodels' copulas summed over the
pseudo-observations and maximised (scipy.optimize), with standard errors
from the numerical Hessian (statsmodels.tools.numdiff.approx_hess). Those
standard errors treat the pseudo-observations as if they were the true
uniforms: they leave out that the ranks estimate the margins, and are too
small (R copula's fitCopula(method="ml") on pseudo-observations gives the
same; its method="mpl" corrects them). With τ inversion the standard error
is the delta method on the U-statistic variance of Kendall's τ.

Where statsmodels 0.14.6 is wrong or loses its digits the numbers are
computed otherwise, and said so where they are used:

  * StudentTCopula.dependence_tail: (df + 1)(1 - ρ)/1 + ρ where
    (ν + 1)(1 - ρ)/(1 + ρ) is meant; the tail dependence is 2 t_{ν+1}(-√…)
  * StudentTCopula.spearmans_rho is the Gaussian copula's (6/π) asin(ρ/2);
    the t copula's comes from its normal variance mixture form: ρ_S =
    3 E sign((X1 - X1')(X2 - X2'')) over independent copies, which given
    the mixing variables is a Gaussian sign probability, so that ρ_S =
    (6/π) E asin(ρW/√((W + W')(W + W''))) with W, W', W'' independent
    copies of the mixing variable (inverse gamma for the t)
  * StudentTCopula.cdf is not implemented: a quadrature of the conditional
    distribution function is used
  * FrankCopula.logpdf takes the log of a negative number for every θ < 0
    (NaN), and its logpdf and cdf lose their digits near (1, 1) for θ above
    about 30; FrankCopula.tau and theta_from_tau use a series that diverges
    for θ < -1; FrankCopula.rvs fails for θ < 0 (and for θ above about 37).
    Frank's copula with -θ is the one with θ turned by 90°, and it is
    radially symmetric: it is evaluated for |θ| at the point of each pair
    nearer to (0, 0), τ(-θ) = -τ(θ), and draws are by conditional
    inversion (statsmodels' ppfcond_2g1, in log form)
  * the Gaussian and t log densities are statsmodels' formulas (scipy's
    multivariate density over the product of the univariate ones) taken in
    log form, so that they do not underflow far from the diagonal
"""
import json
import math

import numpy as np
from scipy import integrate, optimize, special, stats
from statsmodels.distributions.copula.api import (ClaytonCopula, CopulaDistribution, FrankCopula, GaussianCopula,
                                                  GumbelCopula, IndependenceCopula, StudentTCopula)
from statsmodels.distributions.copula.copulas import Copula
from statsmodels.tools.numdiff import approx_hess

from . import data
from .registry import api
from .util import code_head

# ---- the families ---------------------------------------------------------------

ORDER = ['indep', 'gaussian', 't', 'clayton', 'clayton180', 'clayton90', 'clayton270', 'frank',
         'gumbel', 'gumbel180', 'gumbel90', 'gumbel270']
LABEL = {
    'indep': 'Independence', 'gaussian': 'Gaussian', 't': 'Student t', 'frank': 'Frank',
    'clayton': 'Clayton', 'clayton180': 'Survival Clayton (180°)', 'clayton90': 'Clayton (90°)', 'clayton270': 'Clayton (270°)',
    'gumbel': 'Gumbel', 'gumbel180': 'Survival Gumbel (180°)', 'gumbel90': 'Gumbel (90°)', 'gumbel270': 'Gumbel (270°)',
}
BASE = {k: ('clayton' if k.startswith('clayton') else 'gumbel' if k.startswith('gumbel') else k) for k in ORDER}
ROT = {k: (int(k[len(BASE[k]):]) if k[len(BASE[k]):] else 0) for k in ORDER}
MULTI = ('indep', 'gaussian', 't')          # the families fitted to more than two columns
NU_MIN, NU_MAX = 1.0, 200.0                   # the t copula's ν
RHO_MAX = 0.999
BOUNDS = {                                    # the natural parameter's range, for maximum likelihood
    'clayton': (1e-4, 40.0), 'gumbel': (1.0 + 1e-6, 50.0), 'frank': (-100.0, 100.0), 'gaussian': (-RHO_MAX, RHO_MAX),
}
# Each one-parameter family is optimised on a scale where its range is an
# interval of moderate length: log θ, log(θ − 1), asinh(θ/2), atanh ρ.
TO_S = {'clayton': np.log, 'gumbel': lambda t: np.log(t - 1.0), 'frank': lambda t: np.arcsinh(t / 2.0), 'gaussian': np.arctanh}
FROM_S = {'clayton': np.exp, 'gumbel': lambda s: 1.0 + np.exp(s), 'frank': lambda s: 2.0 * np.sinh(s), 'gaussian': np.tanh}
S_BOUNDS = {b: (float(TO_S[b](lo)), float(TO_S[b](hi))) for b, (lo, hi) in BOUNDS.items()}
S_BACK = {'clayton': 'np.exp({})', 'gumbel': '1.0 + np.exp({})', 'frank': '2.0 * np.sinh({})', 'gaussian': 'np.tanh({})'}
S_NAME = {'clayton': 'log θ', 'gumbel': 'log(θ − 1)', 'frank': 'asinh(θ/2)', 'gaussian': 'atanh ρ'}
LOG_NU = float(math.log(NU_MAX))
A_RHO = float(np.arctanh(RHO_MAX))


def applies(key, tau):
    """Whether a family can describe dependence of the sign of Kendall's τ."""
    if key in ('clayton', 'gumbel', 'clayton180', 'gumbel180'):
        return tau > 0
    if key in ('clayton90', 'clayton270', 'gumbel90', 'gumbel270'):
        return tau < 0
    return True


def chosen_families(families, rotations, tau, k):
    """The families to fit. With rotations 'auto' (VineCopula's rotations =
    TRUE) Clayton and Gumbel come with their survival (180°) versions when
    Kendall's τ is positive and as their 90° and 270° rotations when it is
    negative; 'all' fits every rotation, 'none' the unrotated ones."""
    fams = [f for f in (families or ['indep', 'gaussian', 't', 'clayton', 'frank', 'gumbel']) if f in ORDER]
    out = []
    for f in fams:
        if f in ('clayton', 'gumbel'):
            if rotations == 'all':
                out += [f, f'{f}180', f'{f}90', f'{f}270']
            elif rotations == 'none':
                out.append(f)
            else:
                out += [f, f'{f}180'] if tau >= 0 else [f'{f}90', f'{f}270']
        else:
            out.append(f)
    out = [f for f in ORDER if f in out]
    if k > 2:
        out = [f for f in out if f in MULTI]
    return out


# ---- the numerical pieces (their source goes into the Python code shown) --------------

def pobs(x):
    """Pseudo-observations: the ranks of each column (ties averaged) over n + 1."""
    x = np.asarray(x, dtype=float)
    return stats.rankdata(x, axis=0) / (len(x) + 1)


def rotate(u, rot):
    """Where the unrotated copula is evaluated for the copula turned by rot
    degrees (VineCopula: 90° is c(1 - u1, u2), 180° c(1 - u1, 1 - u2), 270°
    c(u1, 1 - u2)); it also turns draws of the unrotated one into draws of
    the rotated one."""
    u = np.array(u, dtype=float)
    if rot in (90, 180):
        u[:, 0] = 1 - u[:, 0]
    if rot in (180, 270):
        u[:, 1] = 1 - u[:, 1]
    return u


def frank_logpdf(u, th):
    """Log density of Frank's copula: statsmodels' FrankCopula().logpdf where
    it is accurate. Its formula takes the log of a negative number when
    theta < 0 and loses digits near (1, 1) when theta is large; the copula with
    -theta is the one with theta turned by 90 degrees and is radially symmetric, so
    it is evaluated for |theta| at the point of the pair nearer to (0, 0)."""
    u = np.array(u, dtype=float)
    if abs(th) < 1e-12:
        return np.zeros(len(u))
    if th < 0:
        u[:, 1] = 1 - u[:, 1]
    far = u.sum(axis=1) > 1
    u[far] = 1 - u[far]
    return FrankCopula().logpdf(u, args=(abs(th),))


def frank_cdf(u, th):
    """C(u, v) of Frank's copula: statsmodels' FrankCopula().cdf at the point
    nearer to (0, 0), by C(u, v) = u + v - 1 + C(1 - u, 1 - v), and for
    theta < 0 by C(u, v) = u - C|theta|(u, 1 - v)."""
    u = np.array(u, dtype=float)
    if abs(th) < 1e-12:
        return u[:, 0] * u[:, 1]
    if th < 0:
        return u[:, 0] - frank_cdf(np.column_stack([u[:, 0], 1 - u[:, 1]]), -th)
    far = u.sum(axis=1) > 1
    out = np.empty(len(u))
    if (~far).any():
        out[~far] = FrankCopula().cdf(u[~far], args=(th,))
    if far.any():
        out[far] = u[far].sum(axis=1) - 1 + FrankCopula().cdf(1 - u[far], args=(th,))
    return out


def frank_ppfcond(q, u1, th):
    """The v with P(V <= v | U = u1) = q under Frank's copula: statsmodels'
    FrankCopula().ppfcond_2g1 written with logaddexp, so that it holds for
    theta of either sign and of any size."""
    if abs(th) < 1e-12:
        return np.asarray(q, dtype=float)
    a = np.log1p(-q) - th * u1
    return -(np.logaddexp(a, np.log(q) - th) - np.logaddexp(np.log(q), a)) / th


def frank_rvs(n, th, rng):
    """Draws from Frank's copula by conditional inversion (statsmodels'
    FrankCopula.rvs needs theta > 0, and fails for theta above about 37)."""
    w = rng.random((n, 2))
    return np.column_stack([w[:, 0], frank_ppfcond(w[:, 1], w[:, 0], th)])


def gauss_logpdf(u, R):
    """Log density of the Gaussian copula with correlation matrix R: statsmodels'
    GaussianCopula(corr=R).logpdf(u) = log(phi_R(z) / prod phi(z_i)), z = Phi^-1(u),
    taken in log form so that it does not underflow."""
    z = stats.norm.ppf(u)
    R = np.asarray(R, dtype=float)
    lf = stats.multivariate_normal(mean=np.zeros(len(R)), cov=R).logpdf(z)
    return np.atleast_1d(lf) - stats.norm.logpdf(z).sum(axis=1)


def t_logpdf(u, R, nu, x=None):
    """Log density of the t copula: statsmodels' StudentTCopula(corr=R, df=nu).logpdf(u)
    = log(t_R,nu(x) / prod t_nu(x_i)), x = t_nu^-1(u), in log form (x may be given
    when nu is fixed)."""
    if x is None:
        x = stats.t.ppf(u, nu)
    R = np.asarray(R, dtype=float)
    if len(R) == 2:
        r = R[0, 1]
        q = (x[:, 0] ** 2 - 2 * r * x[:, 0] * x[:, 1] + x[:, 1] ** 2) / (1 - r * r)
        lf = (special.gammaln((nu + 2) / 2) - special.gammaln(nu / 2) - np.log(nu * np.pi)
              - 0.5 * np.log1p(-r * r) - (nu + 2) / 2 * np.log1p(q / nu))
    else:
        lf = np.atleast_1d(stats.multivariate_t(loc=np.zeros(len(R)), shape=R, df=nu).logpdf(x))
    return lf - stats.t.logpdf(x, nu).sum(axis=1)


def _cos_nodes(m=64):
    """Gauss-Legendre nodes and weights on (0, 1) after p = (1 - cos(pi w))/2,
    which gathers them at the ends."""
    x, w = np.polynomial.legendre.leggauss(m)
    t = (x + 1) / 2
    return (1 - np.cos(np.pi * t)) / 2, w / 2 * np.pi / 2 * np.sin(np.pi * t)


_T_NODES = _cos_nodes(64)


def t2_cdf(u, r, nu):
    """C(u, v) of the bivariate t copula (statsmodels' StudentTCopula has no
    cdf): the integral over s in (0, u) of P(V <= v | U = s) =
    t_nu+1((y - r x) / sqrt((nu + x^2)(1 - r^2)/(nu + 1))), x = t_nu^-1(s),
    y = t_nu^-1(v), by 64-point Gauss-Legendre after s = u(1 - cos(pi w))/2."""
    u = np.asarray(u, dtype=float)
    p, w = _T_NODES
    xs = stats.t.ppf(u[:, :1] * p[None, :], nu)
    y = stats.t.ppf(u[:, 1], nu)[:, None]
    h = stats.t.cdf((y - r * xs) / np.sqrt((nu + xs * xs) * (1 - r * r) / (nu + 1)), nu + 1)
    return u[:, 0] * (h @ w)


def fit1(nll, lo, hi, n_grid=24):
    """The minimum of nll on [lo, hi]: the best point of a grid, then Brent's
    bounded search between its neighbours."""
    def f(s):
        v = nll(s)
        return float(v) if np.isfinite(v) else 1e300
    g = np.linspace(lo, hi, n_grid)
    fg = [f(s) for s in g]
    i = int(np.argmin(fg))
    r = optimize.minimize_scalar(f, bounds=(g[max(i - 1, 0)], g[min(i + 1, n_grid - 1)]), method='bounded',
                                 options={'xatol': 1e-10, 'maxiter': 500})
    return float(r.x) if r.fun <= fg[i] else float(g[i])


def corr_from_cpc(y, k):
    """A correlation matrix from k(k - 1)/2 unbounded numbers: tanh(y) are
    its canonical partial correlations (the LKJ construction), so every y
    gives a positive definite matrix."""
    z = iter(np.tanh(np.asarray(y, dtype=float)))
    W = np.zeros((k, k))
    W[0, 0] = 1.0
    for i in range(1, k):
        s = 0.0
        for j in range(i):
            W[i, j] = next(z) * math.sqrt(max(1.0 - s, 0.0))
            s += W[i, j] ** 2
        W[i, i] = math.sqrt(max(1.0 - s, 0.0))
    return W @ W.T


def cpc_from_corr(R):
    """The inverse of corr_from_cpc."""
    W = np.linalg.cholesky(np.asarray(R, dtype=float))
    k = len(W)
    y = []
    for i in range(1, k):
        s = 0.0
        for j in range(i):
            z = W[i, j] / math.sqrt(max(1.0 - s, 1e-300))
            y.append(np.arctanh(np.clip(z, -0.999999, 0.999999)))
            s += W[i, j] ** 2
    return np.array(y)


def corr_matrix(r, k):
    """The k x k correlation matrix whose upper triangle, row by row, is r."""
    R = np.eye(k)
    R[np.triu_indices(k, 1)] = r
    return R + np.triu(R, 1).T


def emp_copula(u, at=None):
    """The empirical copula of the pseudo-observations u (n x 2) at the
    points at (u itself when None): the share of the rows with u1 <= a1 and
    u2 <= a2."""
    u = np.asarray(u, dtype=float)
    at = u if at is None else np.asarray(at, dtype=float)
    out = np.empty(len(at))
    for s in range(0, len(at), 512):
        a = at[s:s + 512]
        out[s:s + 512] = ((u[None, :, 0] <= a[:, None, 0]) & (u[None, :, 1] <= a[:, None, 1])).mean(axis=1)
    return out


# ---- a family's density, cdf, draws and dependence measures ------------------------------------

def logpdf(key, u, p):
    """The log density of family key with parameters p at the points u."""
    u = np.asarray(u, dtype=float)
    k = u.shape[1]
    if key == 'indep':
        return np.zeros(len(u))
    if key == 'gaussian':
        return gauss_logpdf(u, corr_matrix(p, k))
    if key == 't':
        return t_logpdf(u, corr_matrix(p[:-1], k), p[-1])
    base, rot = BASE[key], ROT[key]
    v = rotate(u, rot) if rot else u
    if base == 'frank':
        return frank_logpdf(v, p[0])
    if base == 'clayton':
        return ClaytonCopula().logpdf(v, args=(p[0],))
    return GumbelCopula().logpdf(v, args=(p[0],))


def cdf(key, u, p):
    """C(u) of family key (two columns; Gaussian and independence any number)."""
    u = np.asarray(u, dtype=float)
    k = u.shape[1]
    if key == 'indep':
        return np.prod(u, axis=1)
    if key == 'gaussian':
        return np.atleast_1d(GaussianCopula(corr=corr_matrix(p, k), k_dim=k).cdf(u))
    if key == 't':
        return t2_cdf(u, p[0], p[1])
    base, rot = BASE[key], ROT[key]
    if base == 'frank':
        return frank_cdf(u, p[0])
    C = ClaytonCopula() if base == 'clayton' else GumbelCopula()
    f = lambda w: np.clip(C.cdf(w, args=(p[0],)), 0.0, 1.0)
    u1, u2 = u[:, 0], u[:, 1]
    if rot == 0:
        return f(u)
    if rot == 90:
        return u2 - f(np.column_stack([1 - u1, u2]))
    if rot == 180:
        return u1 + u2 - 1 + f(1 - u)
    return u1 - f(np.column_stack([u1, 1 - u2]))


def rvs(key, n, p, rng, k=2):
    """n draws from family key (statsmodels' rvs, Frank's by conditional inversion)."""
    if key == 'indep':
        return IndependenceCopula(k_dim=k).rvs(n, random_state=rng)
    if key == 'gaussian':
        return GaussianCopula(corr=corr_matrix(p, k), k_dim=k).rvs(n, random_state=rng)
    if key == 't':
        return StudentTCopula(corr=corr_matrix(p[:-1], k), df=p[-1], k_dim=k).rvs(n, random_state=rng)
    base, rot = BASE[key], ROT[key]
    if base == 'frank':
        return frank_rvs(n, p[0], rng)
    if base == 'clayton':
        x = ClaytonCopula(theta=p[0]).rvs(n, random_state=rng)
    elif p[0] <= 1 + 1e-9:
        x = IndependenceCopula().rvs(n, random_state=rng)
    else:
        x = GumbelCopula(theta=p[0]).rvs(n, random_state=rng)
    return rotate(x, rot) if rot else x


class FittedCopula(Copula):
    """A fitted family as a statsmodels Copula, for CopulaDistribution."""

    def __init__(self, key, p, k_dim=2):
        super().__init__(k_dim=k_dim)
        self.key, self.p = key, list(p)

    def pdf(self, u, args=()):
        return np.exp(self.logpdf(u))

    def logpdf(self, u, args=()):
        return logpdf(self.key, np.atleast_2d(u), self.p)

    def cdf(self, u, args=()):
        return cdf(self.key, np.atleast_2d(u), self.p)

    def rvs(self, nobs=1, args=(), random_state=None):
        return rvs(self.key, nobs, self.p, np.random.default_rng(random_state), self.k_dim)


def tau_frank(th):
    """Kendall's tau of Frank's copula: statsmodels' tau_frank for theta > 0 and
    tau(-theta) = -tau(theta) (its series diverges for theta < -1)."""
    from statsmodels.distributions.copula.archimedean import tau_frank as sm_tau
    if abs(th) < 1e-12:
        return 0.0
    return float(np.sign(th) * sm_tau(abs(th)))


def debye(k, x):
    """The Debye function D_k(x) = (k/x^k) times the integral of t^k/(e^t - 1) from 0 to x."""
    return k / x ** k * integrate.quad(lambda t: t ** k / np.expm1(t) if t > 0 else (1.0 if k == 1 else 0.0), 0, x, epsabs=1e-14, epsrel=1e-12, limit=200)[0]


def rho_frank(th):
    """Spearman's rho of Frank's copula: 1 - 12(D1(theta) - D2(theta))/theta, D_k the Debye functions."""
    if abs(th) < 1e-8:
        return 0.0
    a = abs(th)
    return float(np.sign(th) * (1 - 12 / a * (debye(1, a) - debye(2, a))))


def rho_t(r, nu, m=40):
    """Spearman's rho of the t copula: (6/pi) E asin(r / sqrt((1 + G/G1)(1 + G/G2)))
    with G, G1, G2 independent Gamma(nu/2) (a normal variance mixture's rho_S),
    by Gauss-Legendre over their quantiles."""
    p, w = _cos_nodes(m)
    g = stats.gamma.ppf(p, nu / 2)
    G, G1, G2 = np.meshgrid(g, g, g, indexing='ij', sparse=True)
    W = w[:, None, None] * w[None, :, None] * w[None, None, :]
    return float(6 / np.pi * np.sum(W * np.arcsin(r / np.sqrt((1 + G / G1) * (1 + G / G2)))))


def rho_numeric(cdf):
    """Spearman's rho = 12 (the integral of C over the unit square) - 3, by
    128 x 128 Gauss-Legendre (for the copulas without a closed form)."""
    x, w = np.polynomial.legendre.leggauss(128)
    t = (x + 1) / 2
    U, V = np.meshgrid(t, t, indexing='ij')
    C = cdf(np.column_stack([U.ravel(), V.ravel()])).reshape(U.shape)
    return float(12 * np.sum(np.outer(w / 2, w / 2) * C) - 3)


def t_tail(r, nu):
    """The t copula's tail dependence, 2 t_nu+1(-sqrt((nu + 1)(1 - r)/(1 + r))) (Joe
    2014 p. 182; statsmodels' dependence_tail divides by 1 where 1 + r is meant)."""
    if r >= 1:
        return 1.0
    return float(2 * stats.t.cdf(-math.sqrt((nu + 1) * (1 - r) / (1 + r)), nu + 1))


def measures(key, p):
    """Kendall's tau, Spearman's rho and the tail dependence of a bivariate family:
    lower (0, 0), upper (1, 1), upper left (0, 1) and lower right (1, 0)."""
    if key == 'indep':
        return {'tau': 0.0, 'rho_s': 0.0, 'lambda_l': 0.0, 'lambda_u': 0.0, 'lambda_ul': 0.0, 'lambda_lr': 0.0}
    if key in ('gaussian', 't'):
        r = float(p[0])
        tau = float(GaussianCopula().tau(corr=np.array([[1.0, r], [r, 1.0]])))
        if key == 'gaussian':
            lam = GaussianCopula(corr=r).dependence_tail()
            return {'tau': tau, 'rho_s': float(6 / np.pi * np.arcsin(r / 2)), 'lambda_l': float(lam[0]), 'lambda_u': float(lam[1]), 'lambda_ul': 0.0, 'lambda_lr': 0.0}
        lam = t_tail(r, p[1])
        lam_neg = t_tail(-r, p[1])   # the t copula also has dependence in the other two corners
        return {'tau': tau, 'rho_s': rho_t(r, p[1]), 'lambda_l': lam, 'lambda_u': lam, 'lambda_ul': lam_neg, 'lambda_lr': lam_neg}
    base, rot = BASE[key], ROT[key]
    th = float(p[0])
    if base == 'frank':
        return {'tau': tau_frank(th), 'rho_s': rho_frank(th), 'lambda_l': 0.0, 'lambda_u': 0.0, 'lambda_ul': 0.0, 'lambda_lr': 0.0}
    if base == 'clayton':
        tau = float(ClaytonCopula().tau(theta=th))
        lo, up = 2 ** (-1 / th), 0.0
    else:
        tau = float(GumbelCopula().tau(theta=th))
        lo, up = 0.0, 2 - 2 ** (1 / th)
    C = ClaytonCopula() if base == 'clayton' else GumbelCopula()
    rho = rho_numeric(lambda w: np.clip(C.cdf(w, args=(th,)), 0.0, 1.0))
    if rot == 0:
        return {'tau': tau, 'rho_s': rho, 'lambda_l': lo, 'lambda_u': up, 'lambda_ul': 0.0, 'lambda_lr': 0.0}
    if rot == 180:
        return {'tau': tau, 'rho_s': rho, 'lambda_l': up, 'lambda_u': lo, 'lambda_ul': 0.0, 'lambda_lr': 0.0}
    if rot == 90:     # the unrotated (0, 0) goes to (1, 0), (1, 1) to (0, 1)
        return {'tau': -tau, 'rho_s': -rho, 'lambda_l': 0.0, 'lambda_u': 0.0, 'lambda_ul': up, 'lambda_lr': lo}
    return {'tau': -tau, 'rho_s': -rho, 'lambda_l': 0.0, 'lambda_u': 0.0, 'lambda_ul': lo, 'lambda_lr': up}


def from_tau(key, tau):
    """The parameter with Kendall's tau (statsmodels' corr_from_tau and theta_from_tau)."""
    if key in ('gaussian', 't'):
        return float(GaussianCopula().corr_from_tau(tau))
    base = BASE[key]
    a = abs(tau)
    if base == 'clayton':
        return float(ClaytonCopula().theta_from_tau(a))
    if base == 'gumbel':
        return float(GumbelCopula().theta_from_tau(a))
    # Frank: statsmodels' theta_from_tau is right for tau > 0 (its series fails below -0.11)
    return float(np.sign(tau) * FrankCopula().theta_from_tau(a)) if a > 1e-12 else 0.0


def dparam_dtau(key, tau, th):
    """d parameter / d tau, for the delta method."""
    if key in ('gaussian', 't'):
        return math.pi / 2 * math.cos(math.pi * tau / 2)
    base = BASE[key]
    a = abs(tau)
    if base == 'clayton':
        return 2 / (1 - a) ** 2
    if base == 'gumbel':
        return 1 / (1 - a) ** 2
    t = abs(th)
    if t < 1e-6:
        return 9.0
    d1 = debye(1, t)
    return 1 / (4 / t ** 2 * (1 - 2 * d1 + t / math.expm1(t)))


# ---- fitting ----------------------------------------------------------------------------------

def t_profile(u, nu):
    """The largest log pseudo-likelihood of the bivariate t copula with nu
    degrees of freedom, and the r that gives it: t_logpdf summed, with the
    terms that do not depend on r computed once."""
    x = stats.t.ppf(u, nu)
    rest = special.gammaln((nu + 2) / 2) - special.gammaln(nu / 2) - np.log(nu * np.pi) - stats.t.logpdf(x, nu).sum(axis=1)
    s2, xy = x[:, 0] ** 2 + x[:, 1] ** 2, x[:, 0] * x[:, 1]

    def ll(a):
        r = np.tanh(a)
        return np.sum(rest - 0.5 * np.log1p(-r * r) - (nu + 2) / 2 * np.log1p((s2 - 2 * r * xy) / (1 - r * r) / nu))
    a = fit1(lambda a: -ll(a), -3.8002011672501994, 3.8002011672501994, 12)   # atanh of ±0.999
    return float(ll(a)), float(np.tanh(a))


def emp_copula_self(u):
    """The empirical copula of u (n x 2) at its own points, by a Fenwick tree
    for large n (the share of the rows at or below each row in both columns)."""
    n = len(u)
    if n <= 4000:
        return emp_copula(u)
    r2 = stats.rankdata(u[:, 1], method='max').astype(int)
    order = np.lexsort((u[:, 1], u[:, 0]))
    tree = [0] * (n + 1)
    out = np.empty(n)
    u1 = u[order, 0]
    i = 0
    while i < n:
        j = i
        while j < n and u1[j] == u1[i]:
            j += 1
        for t in order[i:j]:
            k = r2[t]
            while k <= n:
                tree[k] += 1
                k += k & -k
        for t in order[i:j]:
            k, c = r2[t], 0
            while k > 0:
                c += tree[k]
                k -= k & -k
            out[t] = c
        i = j
    return out / n


def tau_se(u):
    """The standard error of Kendall's tau: 2 sd(4 C_n(U_i, V_i) - 2 U_i - 2 V_i)/sqrt(n),
    the U-statistic variance with the empirical copula for C."""
    h = 4 * emp_copula_self(u) - 2 * u[:, 0] - 2 * u[:, 1]
    return float(2 * np.std(h, ddof=1) / math.sqrt(len(u)))


def _hess_se(ll, est):
    """Standard errors from the numerical Hessian of the log likelihood ll(params)."""
    est = np.asarray(est, dtype=float)
    try:
        with np.errstate(all='ignore'):
            H = approx_hess(est, ll)
        cov = np.linalg.inv(-H)
        se = np.sqrt(np.diag(cov))
        if not np.all(np.isfinite(se)) or np.any(np.diag(cov) <= 0):
            se = np.where(np.diag(cov) > 0, se, np.nan)
        return se
    except Exception:
        return np.full(len(est), np.nan)


def ggr_se(lobs, u, est):
    """Rank-corrected standard errors of the maximum pseudo-likelihood
    estimate (Genest, Ghoudi and Rivest 1995): the variance B^-1 S B^-1 / n,
    B the information per row (from the Hessian), S the covariance of the
    score plus W_c(U_ic) for each column c, W_c(t) the mean over the rows
    with U_jc >= t of the score's derivative in u_c. Derivatives by central
    differences; this is the correction R copula's fitCopula(method =
    "mpl") makes, which the Hessian alone leaves out. lobs(q, w) is the log
    density of each row of w with parameters q."""
    u = np.asarray(u, dtype=float)
    n, kk = u.shape
    est = np.asarray(est, dtype=float)
    p = len(est)
    ll = lambda q, w=u: lobs(q, w)      # the log density of each row
    with np.errstate(all='ignore'):
        H = approx_hess(est, lambda q: ll(q).sum())
        h = 1e-4 * np.maximum(np.abs(est), 0.1)
        score = np.empty((n, p))
        for a in range(p):
            e = np.zeros(p)
            e[a] = h[a]
            score[:, a] = (ll(est + e) - ll(est - e)) / (2 * h[a])
        total = score.copy()
        for c in range(kk):
            d = 1e-4 * np.minimum(u[:, c], 1 - u[:, c])
            up, dn = u.copy(), u.copy()
            up[:, c] += d
            dn[:, c] -= d
            order = np.argsort(u[:, c], kind='stable')
            su = u[order, c]
            first = np.searchsorted(su, u[:, c], side='left')
            for a in range(p):
                e = np.zeros(p)
                e[a] = h[a]
                mixed = (ll(est + e, up) - ll(est + e, dn) - ll(est - e, up) + ll(est - e, dn)) / (4 * h[a] * d)
                tail = np.cumsum(mixed[order][::-1])[::-1]       # sums over the rows at or above each sorted value
                total[:, a] += tail[first] / n
        Binv = np.linalg.inv(-H / n)
        S = np.atleast_2d(np.cov(total, rowvar=False))
        V = Binv @ S @ Binv / n
    se = np.sqrt(np.diag(V))
    return np.where(np.isfinite(se), se, np.nan)


def _hse(ses, ll, est):
    """_hess_se, or NaN when the standard errors are not wanted."""
    return _hess_se(ll, est) if ses else np.full(len(np.atleast_1d(est)), np.nan)


def _wald(name, est, se, kind, z):
    """A parameter row with a Wald interval on the scale where the parameter
    is unbounded (log, log(theta - 1), Fisher's z), turned back."""
    row = {'name': name, 'estimate': float(est), 'se': float(se) if np.isfinite(se) else None, 'lower': None, 'upper': None}
    if not np.isfinite(se):
        return row
    if kind == 'log':
        lo, hi = est * math.exp(-z * se / est), est * math.exp(z * se / est)
    elif kind == 'log1':
        d = est - 1
        lo, hi = 1 + d * math.exp(-z * se / d), 1 + d * math.exp(z * se / d)
    elif kind == 'z':
        a, sa = math.atanh(est), se / (1 - est * est)
        lo, hi = math.tanh(a - z * sa), math.tanh(a + z * sa)
    else:
        lo, hi = est - z * se, est + z * se
    row['lower'], row['upper'] = float(lo), float(hi)
    return row


def _pairs(k):
    return [(i, j) for i in range(k) for j in range(i + 1, k)]


def fit_family(key, u, method='mpl', taus=None, tau_ses=None, ses=True):
    """Fit one family to the pseudo-observations u (n x k). Returns the
    parameters (values), their standard errors (unless ses is False: the
    bootstrap needs the estimates only) and the log likelihood."""
    n, k = u.shape
    out = {'family': key, 'label': LABEL[key], 'bound': []}
    if key == 'indep':
        out.update(values=[], se=[], loglik=0.0)
        return out
    pairs = _pairs(k)
    if taus is None:
        taus = [float(stats.kendalltau(u[:, i], u[:, j])[0]) for i, j in pairs]
    tau = taus[0]
    with np.errstate(all='ignore'):
        if key in ('gaussian', 't'):
            return _fit_elliptical(key, u, method, taus, tau_ses, out, ses)
        base = BASE[key]
        if method == 'itau':
            if not applies(key, tau):
                out['error'] = (f'not applicable: Kendall\'s τ is {"negative" if tau < 0 else "positive" if tau > 0 else "zero"}, '
                                f'and {LABEL[key]} has {"positive" if applies(key, 1) else "negative"} dependence only')
                return out
            th = from_tau(key, tau)
            se = abs(dparam_dtau(key, tau, th)) * (tau_ses[0] if tau_ses else tau_se(u) if ses else float('nan'))
            out.update(values=[th], se=[se], loglik=float(logpdf(key, u, [th]).sum()))
            return out
        lo, hi = BOUNDS[base]
        back = FROM_S[base]
        s = fit1(lambda s: -logpdf(key, u, [back(s)]).sum(), *S_BOUNDS[base])
        th = float(back(s))
        se = _hse(ses, lambda q: logpdf(key, u, q).sum(), [th])[0]
        if (base == 'clayton' and th < 1.0001e-4) or (base == 'gumbel' and th - 1 < 1.0001e-6) or th > 0.9999 * hi or th < 0.9999 * lo < 0:
            out['bound'].append(0)
            se = float('nan')
        out.update(values=[th], se=[float(se)], loglik=float(logpdf(key, u, [th]).sum()))
        out['se_rank'] = _rank_se(key, u, out) if ses else [float('nan')] * len(out['values'])
    return out


def _rank_se(key, u, f):
    """ggr_se of a maximum pseudo-likelihood fit; a parameter at its bound
    is held there (its standard error NaN)."""
    v = np.asarray(f['values'], dtype=float)
    free = [a for a in range(len(v)) if a not in (f.get('bound') or [])]
    se = np.full(len(v), np.nan)
    if not free:
        return [float(x) for x in se]

    def lobs(q, w):
        full = v.copy()
        full[free] = q
        return logpdf(key, w, full)
    try:
        se[free] = ggr_se(lobs, u, v[free])
    except Exception:
        pass
    return [float(x) for x in se]


def _fit_elliptical(key, u, method, taus, tau_ses, out, ses=True):
    n, k = u.shape
    pairs = _pairs(k)
    m = len(pairs)
    if method == 'itau':
        r = np.array([from_tau('gaussian', t) for t in taus])
        R = corr_matrix(r, k)
        if k > 2 and np.min(np.linalg.eigvalsh(R)) <= 1e-8:
            from statsmodels.stats.correlation_tools import corr_nearest
            R = corr_nearest(R, threshold=1e-6)
            r = R[np.triu_indices(k, 1)]
            out['nearest'] = True
        sts = tau_ses if tau_ses is not None else [tau_se(u[:, [i, j]]) if ses else float('nan') for i, j in pairs]
        se = [abs(dparam_dtau('gaussian', t, None)) * s for t, s in zip(taus, sts)]
        if key == 'gaussian':
            out.update(values=list(map(float, r)), se=list(map(float, se)), loglik=float(gauss_logpdf(u, R).sum()))
            return out
        # nu by maximum likelihood with R at its tau estimate (R copula's itau.mpl)
        s = fit1(lambda s: -t_logpdf(u, R, np.exp(s)).sum(), 0.0, LOG_NU, 16)
        nu = float(np.exp(s))
        se_nu = _hse(ses, lambda q: t_logpdf(u, R, q[0]).sum(), [nu])[0]
        if nu > 0.999 * NU_MAX or nu < 1.001 * NU_MIN:
            out['bound'].append(m)
            se_nu = float('nan')
        out.update(values=list(map(float, r)) + [nu], se=list(map(float, se)) + [float(se_nu)], loglik=float(t_logpdf(u, R, nu).sum()))
        return out
    if k == 2:
        if key == 'gaussian':
            a = fit1(lambda a: -gauss_logpdf(u, [[1, np.tanh(a)], [np.tanh(a), 1]]).sum(), *S_BOUNDS['gaussian'])
            r = float(np.tanh(a))
            se = _hse(ses, lambda q: gauss_logpdf(u, [[1, q[0]], [q[0], 1]]).sum(), [r])
            if abs(r) > 0.9999 * RHO_MAX:
                out['bound'].append(0)
                se = [float('nan')]
            out.update(values=[r], se=[float(se[0])], loglik=float(gauss_logpdf(u, [[1, r], [r, 1]]).sum()))
            out['se_rank'] = _rank_se(key, u, out) if ses else [float('nan')] * len(out['values'])
            return out
        s = fit1(lambda s: -t_profile(u, np.exp(s))[0], 0.0, LOG_NU, 16)
        nu = float(np.exp(s))
        llf, r = t_profile(u, nu)
        se = _hse(ses, lambda q: t_logpdf(u, [[1, q[0]], [q[0], 1]], q[1]).sum(), [r, nu])
        if abs(r) > 0.9999 * RHO_MAX:
            out['bound'].append(0)
            se[0] = np.nan
        if nu > 0.999 * NU_MAX or nu < 1.001 * NU_MIN:
            out['bound'].append(1)
            se = [float('nan'), float('nan')] if not np.isfinite(se[0]) else [se[0], float('nan')]
            # with nu at a bound the Hessian in r alone
            se[0] = _hse(ses, lambda q: t_logpdf(u, [[1, q[0]], [q[0], 1]], nu).sum(), [r])[0]
        out.update(values=[r, nu], se=list(map(float, se)), loglik=float(llf))
        out['se_rank'] = _rank_se(key, u, out) if ses else [float('nan')] * len(out['values'])
        return out
    # more than two columns: the correlation matrix through its canonical partial correlations
    z = stats.norm.ppf(u)
    R0 = np.corrcoef(z, rowvar=False)
    y0 = cpc_from_corr(R0)
    if key == 'gaussian':
        res = optimize.minimize(lambda y: -gauss_logpdf(u, corr_from_cpc(y, k)).sum(), y0, method='BFGS', options={'gtol': 1e-7, 'maxiter': 2000})
        R = corr_from_cpc(res.x, k)
        r = R[np.triu_indices(k, 1)]
        se = _hse(ses, lambda q: gauss_logpdf(u, corr_matrix(q, k)).sum(), r)
        out.update(values=list(map(float, r)), se=list(map(float, se)), loglik=float(gauss_logpdf(u, R).sum()))
        out['se_rank'] = _rank_se(key, u, out) if ses else [float('nan')] * len(out['values'])
        return out
    R0 = corr_matrix([from_tau('gaussian', t) for t in taus], k)
    if np.min(np.linalg.eigvalsh(R0)) <= 1e-8:
        from statsmodels.stats.correlation_tools import corr_nearest
        R0 = corr_nearest(R0, threshold=1e-6)
    grid = [1.5, 3.0, 6.0, 12.0, 25.0, 50.0, 100.0]
    nu0 = grid[int(np.argmax([t_logpdf(u, R0, g).sum() for g in grid]))]
    v0 = np.r_[cpc_from_corr(R0), math.log(nu0)]
    f = lambda v: -t_logpdf(u, corr_from_cpc(v[:-1], k), np.exp(v[-1])).sum()
    res = optimize.minimize(f, v0, method='L-BFGS-B', bounds=[(None, None)] * m + [(0.0, LOG_NU)], options={'ftol': 1e-13, 'gtol': 1e-8, 'maxiter': 3000})
    R = corr_from_cpc(res.x[:-1], k)
    nu = float(np.exp(res.x[-1]))
    r = R[np.triu_indices(k, 1)]
    est = np.r_[r, nu]
    if nu > 0.999 * NU_MAX or nu < 1.001 * NU_MIN:
        out['bound'].append(m)
        se = np.r_[_hse(ses, lambda q: t_logpdf(u, corr_matrix(q, k), nu).sum(), r), np.nan]
    else:
        se = _hse(ses, lambda q: t_logpdf(u, corr_matrix(q[:-1], k), q[-1]).sum(), est)
    out.update(values=list(map(float, est)), se=list(map(float, se)), loglik=float(t_logpdf(u, R, nu).sum()))
    out['se_rank'] = _rank_se(key, u, out) if ses else [float('nan')] * len(out['values'])
    return out


def param_rows(key, values, se, names, alpha=0.05):
    """The parameter table rows of a fit, with Wald intervals."""
    z = stats.norm.ppf(1 - alpha / 2)
    if key == 'indep':
        return []
    if key in ('gaussian', 't'):
        k = int(round((1 + math.sqrt(1 + 8 * (len(values) - (key == 't')))) / 2))
        pairs = _pairs(k)
        rows = [_wald('ρ' if k == 2 else f'ρ({names[i]}, {names[j]})', values[q], se[q], 'z', z) for q, (i, j) in enumerate(pairs)]
        if key == 't':
            rows.append(_wald('ν (degrees of freedom)', values[-1], se[-1], 'log', z))
        return rows
    base = BASE[key]
    return [_wald('θ', values[0], se[0], {'clayton': 'log', 'gumbel': 'log1', 'frank': 'plain'}[base], z)]


def bivariate(key, values, i, j, k):
    """The parameters of the bivariate margin (i, j) of a fitted family."""
    if key not in ('gaussian', 't') or k == 2:
        return list(values)
    q = _pairs(k).index((i, j))
    return [values[q]] + ([values[-1]] if key == 't' else [])


def _load(table, columns, rows):
    """The complete rows of the columns (as floats), their page row numbers,
    and the number of rows before those with a missing value were dropped."""
    df = data.frame(table, columns, rows, as_category=False)
    idx = df.index.to_numpy()
    X = df[list(columns)].to_numpy(float)
    ok = np.all(np.isfinite(X), axis=1)
    n_all = data.TABLES[table]['n'] if rows is None else len(rows)
    return X[ok], idx[ok], n_all


def _rows_lines(table, rows):
    """The lines that keep the report's rows in the code."""
    if rows is None:
        return []
    n_all = data.TABLES[table]['n'] if table in data.TABLES else None
    keep = [int(r) for r in rows]
    if n_all is not None and len(keep) > n_all / 2:
        drop = sorted(set(range(n_all)) - set(keep))
        return [f'df = df.drop(index={drop})   # the rows the report leaves out'] if drop else []
    return [f'df = df.loc[{keep}]   # the rows of the report']


@api('copula.fit')
def fit(table, columns, rows=None, families=None, method='mpl', rotations='auto', se='hessian', alpha=0.05, table_name='data'):
    """Pseudo-observations, rank correlations, and each family's fit with its
    dependence measures, best first by AIC."""
    columns = list(columns or [])
    if len(columns) < 2:
        return {'error': 'choose two or more columns'}
    X, idx, n_all = _load(table, columns, rows)
    n, k = X.shape
    out = {'columns': columns, 'n': n, 'k': k, 'n_missing': int(n_all - n), 'method': method, 'rotations': rotations, 'alpha': alpha,
           'se_kind': 'delta' if method == 'itau' else ('rank' if se == 'rank' else 'hessian')}
    if n < 5:
        out['error'] = f'{n} rows with a value in every column: at least 5 are needed'
        return out
    distinct = [len(np.unique(X[:, c])) for c in range(k)]
    one = [columns[c] for c in range(k) if distinct[c] < 2]
    if one:
        out['error'] = f'{", ".join(one)} {"has" if len(one) == 1 else "have"} a single value on these rows: a copula needs values that vary'
        return out
    ties = [int(n - d) for d in distinct]
    out['ties'] = ties
    u = pobs(X)
    out['rows'] = [int(r) for r in idx]
    out['u'] = u.T.tolist()
    pairs = _pairs(k)
    dep = []
    taus, ses = [], []
    for i, j in pairs:
        kt = stats.kendalltau(X[:, i], X[:, j])
        sp = stats.spearmanr(X[:, i], X[:, j])
        s_tau = tau_se(u[:, [i, j]])
        taus.append(float(kt.statistic))
        ses.append(s_tau)
        dep.append({'i': i, 'j': j, 'var': columns[j], 'by': columns[i], 'n': n, 'tau': float(kt.statistic), 'tau_p': float(kt.pvalue), 'tau_se': s_tau,
                    'rho': float(sp.statistic), 'rho_p': float(sp.pvalue)})
    out['dependence'] = dep
    fams = chosen_families(families, rotations, taus[0], k)
    fits = []
    for key in fams:
        try:
            f = fit_family(key, u, method, taus, ses)
        except Exception as e:     # a family that fails is reported, the others go on
            f = {'family': key, 'label': LABEL[key], 'error': f'{type(e).__name__}: {e}'}
        if 'error' not in f:
            p = len(f['values'])
            f['k'] = p
            f['aic'] = -2 * f['loglik'] + 2 * p
            f['aicc'] = f['aic'] + (2 * p * (p + 1) / (n - p - 1) if n - p - 1 > 0 else float('nan'))
            f['bic'] = -2 * f['loglik'] + p * math.log(n)
            f['se_hessian'] = list(f['se'])
            if method == 'mpl' and se == 'rank' and 'se_rank' in f:
                f['se'] = list(f['se_rank'])
            f['params'] = param_rows(key, f['values'], f['se'], columns, alpha)
            for q, row in enumerate(f['params']):
                row['se_hessian'] = f['se_hessian'][q] if np.isfinite(f['se_hessian'][q]) else None
                row['se_rank'] = f['se_rank'][q] if 'se_rank' in f and np.isfinite(f['se_rank'][q]) else None
            for q in f.get('bound', []):
                f['params'][q]['bound'] = True
            f['measures'] = [dict(i=i, j=j, **measures(key, bivariate(key, f['values'], i, j, k))) for i, j in pairs]
            f['note'] = _fit_note(key, f, method, taus[0])
        fits.append(f)
    ok = [f for f in fits if 'error' not in f]
    ok.sort(key=lambda f: f['aic'])
    best = ok[0]['aic'] if ok else None
    tot = sum(math.exp(-0.5 * (f['aic'] - best)) for f in ok) if ok else 0
    for f in ok:
        f['delta'] = f['aic'] - best
        f['weight'] = math.exp(-0.5 * f['delta']) / tot
    out['fits'] = ok + [f for f in fits if 'error' in f]
    out['best'] = ok[0]['family'] if ok else None
    out['families'] = fams
    out['code'] = fit_code(table, table_name, rows, columns, [f for f in fams if any(g['family'] == f for g in ok)], method, k)
    return out


def _fit_note(key, f, method, tau):
    b = f.get('bound') or []
    if not b:
        if f.get('nearest'):
            return 'The correlations from Kendall\'s τ did not make a positive definite matrix; the nearest one is used (statsmodels corr_nearest).'
        return None
    if key == 't' and (len(f['values']) - 1) in b:
        nu = f['values'][-1]
        return (f'ν is at its upper bound ({NU_MAX:g}): the tails are no heavier than the Gaussian copula\'s, which says the same with one parameter less.'
                if nu > 2 else f'ν is at its lower bound ({NU_MIN:g}).')
    if key in ('gaussian', 't'):
        return f'ρ is at its bound (±{RHO_MAX:g}).'
    th = f['values'][0]
    base = BASE[key]
    if (base == 'clayton' and th < 1e-3) or (base == 'gumbel' and th < 1 + 1e-3):
        wrong = not applies(key, tau) and tau != 0
        return (f'θ is at the lower bound: the fit is the independence copula'
                + (f' ({LABEL[key]} cannot describe {"negative" if tau < 0 else "positive"} dependence; the rotations can).' if wrong else '.'))
    return f'θ is at its bound ({th:.4g}).'


# ---- the Python shown under the report -----------------------------------------------------------

def _src(*fns):
    """The source of the helpers the code uses (the functions the report runs)."""
    import inspect
    return '\n\n'.join(inspect.getsource(f).rstrip() for f in fns)


_HESS_SE = '''def hess_se(ll, est):
    """Standard errors from the numerical Hessian of the log likelihood (statsmodels' approx_hess)."""
    return np.sqrt(np.diag(np.linalg.inv(-approx_hess(np.asarray(est, dtype=float), ll))))'''

_SM_CLASS = {'clayton': 'ClaytonCopula', 'gumbel': 'GumbelCopula'}


def _lobs_text(key, k=2):
    """The log density of each row of w as a lambda of the parameters q and w."""
    if key == 'gaussian':
        return 'lambda q, w: gauss_logpdf(w, [[1, q[0]], [q[0], 1]])' if k == 2 else 'lambda q, w: gauss_logpdf(w, corr_matrix(q, k))'
    if key == 't':
        return 'lambda q, w: t_logpdf(w, [[1, q[0]], [q[0], 1]], q[1])' if k == 2 else 'lambda q, w: t_logpdf(w, corr_matrix(q[:-1], k), q[-1])'
    base, rot = BASE[key], ROT[key]
    v = f'rotate(w, {rot})' if rot else 'w'
    if base == 'frank':
        return f'lambda q, w: frank_logpdf({v}, q[0])'
    return f'lambda q, w: {_SM_CLASS[base]}().logpdf({v}, args=(q[0],))'


def _ll_lines(key, k=2):
    return [f'lobs = {_lobs_text(key, k)}   # the log density of each row', 'll = lambda q: lobs(q, u).sum()   # the log pseudo-likelihood']


def fit_code(table, table_name, rows, columns, fams, method, k):
    need = {'fit1': method == 'mpl', 'rotate': any(ROT[f] for f in fams), 'frank': any(BASE[f] == 'frank' for f in fams),
            'gauss': 'gaussian' in fams, 't': 't' in fams}
    imports = ['import math', 'from scipy import integrate, optimize, special, stats',
               'from statsmodels.distributions.copula.api import ClaytonCopula, FrankCopula, GaussianCopula, GumbelCopula, StudentTCopula',
               'from statsmodels.tools.numdiff import approx_hess']
    c = [code_head(table_name, imports)] + _rows_lines(table, rows)
    c += [f'x = df[{json.dumps(columns)}].dropna().to_numpy()',
          'u = stats.rankdata(x, axis=0) / (len(x) + 1)   # pseudo-observations: the ranks (ties averaged) over n + 1',
          f'n, k = u.shape', '']
    helpers = [emp_copula]
    if need['fit1'] or need['t']:
        helpers.append(fit1)
    if method == 'mpl':
        helpers.append(ggr_se)
    if need['rotate']:
        helpers.append(rotate)
    if need['frank']:
        helpers += [frank_logpdf, debye, rho_frank, tau_frank]
    if need['gauss']:
        helpers.append(gauss_logpdf)
    if need['t']:
        helpers += [t_logpdf, t_tail, _cos_nodes, rho_t]
        if method == 'mpl' and k == 2:
            helpers.append(t_profile)
    if any(BASE[f] in ('clayton', 'gumbel') for f in fams):
        helpers.append(rho_numeric)
    if k > 2:
        helpers += [corr_matrix, corr_from_cpc, cpc_from_corr]
    c += [_src(*helpers), '', _HESS_SE, '']
    c += ['# Kendall\'s tau (tau-b, with the standard error of its U-statistic) and Spearman\'s rho of each pair',
          'taus, ses = [], []',
          f'for i, j in {_pairs(k)}:',
          '    kt, sp = stats.kendalltau(x[:, i], x[:, j]), stats.spearmanr(x[:, i], x[:, j])',
          '    se = 2 * np.std(4 * emp_copula(u[:, [i, j]]) - 2 * u[:, i] - 2 * u[:, j], ddof=1) / np.sqrt(n)',
          '    taus.append(kt.statistic); ses.append(se)',
          '    print("pair", i, j, kt.statistic, kt.pvalue, se, sp.statistic, sp.pvalue)',
          'tau, se_tau = taus[0], ses[0]', '']
    for key in fams:
        c += _family_code(key, method, k) + ['']
    return '\n'.join(c).rstrip()


def _family_code(key, method, k):
    lab = LABEL[key]
    if key == 'indep':
        return [f'print("fit indep", 0.0)   # {lab}: no parameter, log likelihood 0']
    if key in ('gaussian', 't') and k > 2:
        return _family_code_k(key, method)
    if method == 'itau':
        if key in ('gaussian', 't'):
            lines = [f'# {lab}: ρ from Kendall\'s τ (statsmodels corr_from_tau), its standard error by the delta method',
                     'r = GaussianCopula().corr_from_tau(tau); se_r = np.pi / 2 * np.cos(np.pi * tau / 2) * se_tau']
            if key == 'gaussian':
                return lines + ['print("fit gaussian", r, se_r, gauss_logpdf(u, [[1, r], [r, 1]]).sum())',
                                'print("measures gaussian", 2 / np.pi * np.arcsin(r), 6 / np.pi * np.arcsin(r / 2), 0.0, 0.0)']
            return lines + ['# ν by maximum pseudo-likelihood with ρ fixed (R copula\'s itau.mpl)',
                            'R = [[1, r], [r, 1]]',
                            f'nu = np.exp(fit1(lambda s: -t_logpdf(u, R, np.exp(s)).sum(), 0.0, {LOG_NU!r}, 16))',
                            'se_nu = hess_se(lambda q: t_logpdf(u, R, q[0]).sum(), [nu])[0]',
                            'print("fit t", r, nu, se_r, se_nu, t_logpdf(u, R, nu).sum())',
                            'print("measures t", 2 / np.pi * np.arcsin(r), rho_t(r, nu), t_tail(r, nu), t_tail(r, nu))']
        base = BASE[key]
        cls = {'clayton': 'ClaytonCopula', 'gumbel': 'GumbelCopula', 'frank': 'FrankCopula'}[base]
        deriv = {'clayton': '2 / (1 - abs(tau)) ** 2', 'gumbel': '1 / (1 - abs(tau)) ** 2',
                 'frank': '1 / (4 / th ** 2 * (1 - 2 * debye(1, abs(th)) + abs(th) / math.expm1(abs(th))))'}[base]
        lines = [f'# {lab}: θ from |Kendall\'s τ| (statsmodels theta_from_tau), its standard error by the delta method']
        if base == 'frank':
            lines.append('th = np.sign(tau) * FrankCopula().theta_from_tau(abs(tau))   # statsmodels\' series fails for negative τ: by symmetry')
        else:
            lines.append(f'th = {cls}().theta_from_tau(abs(tau))')
        lines.append(f'se = abs({deriv}) * se_tau')
        lines += _ll_lines(key) + [f'print("fit {key}", th, se, ll([th]))'] + _measures_code(key)
        return lines
    # maximum pseudo-likelihood
    if key == 'gaussian':
        lo, hi = S_BOUNDS['gaussian']
        return [f'# {lab}: maximum pseudo-likelihood over atanh ρ'] + _ll_lines(key) + [
                f'r = float(np.tanh(fit1(lambda a: -gauss_logpdf(u, [[1, np.tanh(a)], [np.tanh(a), 1]]).sum(), {lo!r}, {hi!r})))',
                'print("fit gaussian", r, *hess_se(ll, [r]), ll([r]))',
                'print("rank_se gaussian", *ggr_se(lobs, u, [r]))   # rank-corrected (Genest, Ghoudi and Rivest 1995)'] + _measures_code(key)
    if key == 't':
        return [f'# {lab}: maximum pseudo-likelihood; for each ν the best ρ (t_profile), then the best ν over log ν',
                f'nu = float(np.exp(fit1(lambda s: -t_profile(u, np.exp(s))[0], 0.0, {LOG_NU!r}, 16)))',
                'llt, r = t_profile(u, nu)'] + _ll_lines(key) + [
                'print("fit t", r, nu, *hess_se(ll, [r, nu]), llt)',
                'print("rank_se t", *ggr_se(lobs, u, [r, nu]))   # rank-corrected (Genest, Ghoudi and Rivest 1995)'] + _measures_code(key)
    base = BASE[key]
    lo, hi = S_BOUNDS[base]
    back = S_BACK[base]
    return [f'# {lab}: maximum pseudo-likelihood over {S_NAME[base]}'] + _ll_lines(key) + [
            f'th = float({back.format(f"fit1(lambda s: -ll([{back.format(chr(115))}]), {lo!r}, {hi!r})")})',
            f'print("fit {key}", th, *hess_se(ll, [th]), ll([th]))',
            f'print("rank_se {key}", *ggr_se(lobs, u, [th]))   # rank-corrected (Genest, Ghoudi and Rivest 1995)'] + _measures_code(key)


def _measures_code(key):
    """Kendall's tau, Spearman's rho and the tail dependence implied by a fit."""
    if key == 'gaussian':
        return ['print("measures gaussian", 2 / np.pi * np.arcsin(r), 6 / np.pi * np.arcsin(r / 2), 0.0, 0.0)']
    if key == 't':
        return ['print("measures t", 2 / np.pi * np.arcsin(r), rho_t(r, nu), t_tail(r, nu), t_tail(r, nu))   # tau, rho_S, lambda_L, lambda_U']
    base, rot = BASE[key], ROT[key]
    if base == 'frank':
        return [f'print("measures {key}", tau_frank(th), rho_frank(th), 0.0, 0.0)']
    cls = _SM_CLASS[base]
    sign = '-' if rot in (90, 270) else ''
    if base == 'clayton':
        lam = ['2 ** (-1 / th)', '0.0']
    else:
        lam = ['0.0', '2 - 2 ** (1 / th)']
    if rot == 180:
        lam = lam[::-1]
    elif rot in (90, 270):
        lam = ['0.0', '0.0']   # the rotated tails are in the corners (0, 1) and (1, 0)
    return [f'rho_s = rho_numeric(lambda w: np.clip({cls}().cdf(w, args=(th,)), 0.0, 1.0))   # 12 ∫∫C − 3 of the unrotated copula',
            f'print("measures {key}", {sign}{cls}().tau(theta=th), {sign}rho_s, {lam[0]}, {lam[1]})']


def _family_code_k(key, method):
    lab = LABEL[key]
    if method == 'itau':
        lines = [f'# {lab}: the correlations from Kendall\'s τ (statsmodels corr_from_tau), made positive definite when they are not',
                 'R = corr_matrix([GaussianCopula().corr_from_tau(t) for t in taus], k)',
                 'if np.min(np.linalg.eigvalsh(R)) <= 1e-8:',
                 '    from statsmodels.stats.correlation_tools import corr_nearest',
                 '    R = corr_nearest(R, threshold=1e-6)',
                 'r = R[np.triu_indices(k, 1)]',
                 'se_r = [np.pi / 2 * np.cos(np.pi * t / 2) * s for t, s in zip(taus, ses)]']
        if key == 'gaussian':
            return lines + ['print("fit gaussian", *r, *se_r, gauss_logpdf(u, R).sum())']
        return lines + [f'nu = np.exp(fit1(lambda s: -t_logpdf(u, R, np.exp(s)).sum(), 0.0, {LOG_NU!r}, 16))',
                        'print("fit t", *r, nu, *se_r, hess_se(lambda q: t_logpdf(u, R, q[0]).sum(), [nu])[0], t_logpdf(u, R, nu).sum())']
    if key == 'gaussian':
        return [f'# {lab}: maximum pseudo-likelihood over the canonical partial correlations (BFGS), from the normal scores\' correlations',
                'y0 = cpc_from_corr(np.corrcoef(stats.norm.ppf(u), rowvar=False))',
                "res = optimize.minimize(lambda y: -gauss_logpdf(u, corr_from_cpc(y, k)).sum(), y0, method='BFGS', options={'gtol': 1e-7, 'maxiter': 2000})",
                'R = corr_from_cpc(res.x, k); r = R[np.triu_indices(k, 1)]'] + _ll_lines(key, 3) + [
                'print("fit gaussian", *r, *hess_se(ll, r), gauss_logpdf(u, R).sum())',
                'print("rank_se gaussian", *ggr_se(lobs, u, r))']
    return [f'# {lab}: maximum pseudo-likelihood over the canonical partial correlations and log ν (L-BFGS-B), from the τ correlations',
            'R0 = corr_matrix([GaussianCopula().corr_from_tau(t) for t in taus], k)',
            'if np.min(np.linalg.eigvalsh(R0)) <= 1e-8:',
            '    from statsmodels.stats.correlation_tools import corr_nearest',
            '    R0 = corr_nearest(R0, threshold=1e-6)',
            'grid = [1.5, 3.0, 6.0, 12.0, 25.0, 50.0, 100.0]',
            'nu0 = grid[int(np.argmax([t_logpdf(u, R0, g).sum() for g in grid]))]',
            'm = k * (k - 1) // 2',
            'f = lambda v: -t_logpdf(u, corr_from_cpc(v[:-1], k), np.exp(v[-1])).sum()',
            f"res = optimize.minimize(f, np.r_[cpc_from_corr(R0), math.log(nu0)], method='L-BFGS-B', bounds=[(None, None)] * m + [(0.0, {LOG_NU!r})], options={{'ftol': 1e-13, 'gtol': 1e-8, 'maxiter': 3000}})",
            'R = corr_from_cpc(res.x[:-1], k); nu = float(np.exp(res.x[-1])); r = R[np.triu_indices(k, 1)]'] + _ll_lines(key, 3) + [
            'print("fit t", *r, nu, *hess_se(ll, np.r_[r, nu]), t_logpdf(u, R, nu).sum())',
            'print("rank_se t", *ggr_se(lobs, u, np.r_[r, nu]))']


# ---- contours --------------------------------------------------------------------------------------

def _hdr(z, dA, probs=(0.5, 0.75, 0.9, 0.95)):
    """The density levels whose upper regions hold the given shares of the
    mass on the grid (highest density regions)."""
    v = np.sort(np.asarray(z, dtype=float).ravel())[::-1]
    v = v[np.isfinite(v)]
    if not len(v):
        return []
    mass = np.cumsum(v) * dA
    out = []
    for p in probs:
        i = int(np.searchsorted(mass, p * mass[-1]))
        out.append({'p': p, 'level': float(v[min(i, len(v) - 1)])})
    return out


# The density levels drawn on the unit square: above 1 the copula makes a
# pair of values more likely than independence would, below 1 less likely.
UNIT_LEVELS = (0.125, 0.25, 0.5, 2.0, 4.0, 8.0, 16.0, 32.0)


def _unit_levels(z, min_share=0.004):
    """The levels of UNIT_LEVELS whose region (density above a level above 1,
    below a level below 1) covers at least min_share of the square: at most
    four above 1 and two below."""
    v = np.asarray(z, dtype=float).ravel()
    v = v[np.isfinite(v)]
    up = [c for c in UNIT_LEVELS if c > 1 and np.mean(v >= c) >= min_share][:4]
    down = [c for c in UNIT_LEVELS if c < 1 and np.mean(v <= c) >= min_share][::-1][:2][::-1]
    return [{'level': c, 'kind': 'density'} for c in down + up]


@api('copula.density')
def density(family='indep', params=None, scale='uniform', m=60, table=None, rows=None):
    """A bivariate copula's density on a grid for contours. On the unit square
    the levels are densities (2, 4, 8, ... and 1/2, 1/4, ...: how many times
    more or less likely than under independence); with standard normal
    margins (normal scores) they are the levels that enclose 50, 75, 90 and
    95% of the distribution."""
    params = list(params or [])
    m = int(max(10, min(m, 150)))
    with np.errstate(all='ignore'):
        if scale == 'normal':
            g = np.linspace(-3.3, 3.3, m)
            Z1, Z2 = np.meshgrid(g, g)
            uv = stats.norm.cdf(np.column_stack([Z1.ravel(), Z2.ravel()]))
            lz = logpdf(family, uv, params) + stats.norm.logpdf(Z1.ravel()) + stats.norm.logpdf(Z2.ravel())
            dA = (g[1] - g[0]) ** 2
        else:
            g = (np.arange(m) + 0.5) / m
            U, V = np.meshgrid(g, g)
            lz = logpdf(family, np.column_stack([U.ravel(), V.ravel()]), params)
            dA = 1.0 / (m * m)
        z = np.exp(lz).reshape(m, m)
    z[~np.isfinite(z)] = np.nan
    flat = bool(np.nanmax(z) - np.nanmin(z) < 1e-9 * max(1.0, np.nanmax(z)))
    levels = [] if flat else (_unit_levels(z) if scale != 'normal' else [dict(lv, kind='hdr') for lv in _hdr(z, dA)])
    return {'x': g.tolist(), 'y': g.tolist(), 'z': z.tolist(), 'levels': levels, 'scale': scale, 'family': family}


# ---- margins ----------------------------------------------------------------------------------------

MARGINS = ['normal', 'lognormal', 'gamma', 'weibull', 'exponential', 'logistic', 't', 'beta']
SCIPY = {'normal': 'norm', 'lognormal': 'lognorm', 'gamma': 'gamma', 'weibull': 'weibull_min', 'exponential': 'expon',
         'logistic': 'logistic', 't': 't', 'beta': 'beta'}


def frozen(dist, v):
    """A scipy distribution from the Distribution platform's parameters."""
    if dist == 'normal':
        return stats.norm(v[0], v[1])
    if dist == 'lognormal':
        return stats.lognorm(v[1], scale=math.exp(v[0]))
    if dist == 'gamma':
        return stats.gamma(v[0], scale=v[1])
    if dist == 'weibull':
        return stats.weibull_min(v[1], scale=v[0])
    if dist == 'exponential':
        return stats.expon(scale=v[0])
    if dist == 'logistic':
        return stats.logistic(v[0], v[1])
    if dist == 't':
        return stats.t(v[2], v[0], v[1])
    if dist == 'beta':
        return stats.beta(v[0], v[1])
    raise KeyError(f'no margin {dist!r}')


def frozen_text(dist, v):
    """frozen() as Python."""
    r = [repr(float(a)) for a in v]
    form = {'normal': 'stats.norm({0}, {1})', 'lognormal': 'stats.lognorm({1}, scale=math.exp({0}))',
            'gamma': 'stats.gamma({0}, scale={1})', 'weibull': 'stats.weibull_min({1}, scale={0})',
            'exponential': 'stats.expon(scale={0})', 'logistic': 'stats.logistic({0}, {1})',
            't': 'stats.t({2}, {0}, {1})', 'beta': 'stats.beta({0}, {1})'}[dist]
    return form.format(*r)


class Empirical:
    """A column's empirical distribution as a margin: the cdf interpolates
    i/(n + 1) between the sorted values (0 below the smallest, 1 above the
    largest), the quantile function is its inverse (np.quantile's weibull
    method: JMP's quantiles), the density a Gaussian kernel estimate (for
    contours only)."""

    def __init__(self, x):
        self.xs = np.sort(np.asarray(x, dtype=float))
        self.p = np.arange(1, len(self.xs) + 1) / (len(self.xs) + 1)
        self._kde = None

    def cdf(self, v):
        return np.interp(v, self.xs, self.p, left=0.0, right=1.0)

    def ppf(self, q):
        return np.quantile(self.xs, q, method='weibull')

    def pdf(self, v):
        if self._kde is None:
            self._kde = stats.gaussian_kde(self.xs)
        return self._kde(np.atleast_1d(v))

    def logpdf(self, v):
        return np.log(self.pdf(v))

    def support(self):
        return (-np.inf, np.inf)


def margin(spec, x):
    """A margin from its spec {dist, values}, or the empirical one."""
    if not spec or spec.get('dist') == 'empirical':
        return Empirical(x)
    return frozen(spec['dist'], spec['values'])


@api('copula.margins')
def margins(table, columns, rows=None, choice=None, alpha=0.05, table_name='data'):
    """A distribution for each column, on the rows the copula uses: the
    Distribution platform's maximum likelihood fits compared by AICc, the
    best (or the one chosen, or the empirical distribution) kept."""
    import warnings
    from .distribution import _fit_one
    columns = list(columns or [])
    X, idx, _ = _load(table, columns, rows)
    choice = choice or {}
    out = {'columns': [], 'n': len(X)}
    code = [code_head(table_name, ['import math', 'from scipy import stats'])] + _rows_lines(table, rows)
    code.append(f'x = df[{json.dumps(columns)}].dropna().to_numpy()   # the rows with a value in every column, as the copula uses')
    for c, name in enumerate(columns):
        x = X[:, c]
        cands = []
        for key in MARGINS:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                r = _fit_one(x, key, alpha)
            if 'error' in r:
                continue
            msgs = [str(w.message) for w in caught if not issubclass(w.category, (DeprecationWarning, FutureWarning))]
            cands.append({'dist': key, 'label': r['label'], 'k': r['k'], 'loglik': r['loglik'], 'aicc': r['aicc'], 'bic': r['bic'],
                          'params': r['params'], 'values': [p['estimate'] for p in r['params']], 'curve': r.get('curve'),
                          'warning': msgs[0] if msgs else None})
        cands.sort(key=lambda f: f['aicc'] if f['aicc'] is not None and np.isfinite(f['aicc']) else np.inf)
        best = cands[0]['aicc'] if cands else None
        for f in cands:
            f['delta'] = f['aicc'] - best
        want = choice.get(name) or 'auto'
        if want == 'empirical' or not cands:
            kde = stats.gaussian_kde(x)
            lo, hi = float(np.min(x)), float(np.max(x))
            bw = float(kde.factor * np.std(x, ddof=1))
            g = np.linspace(lo - 3 * bw, hi + 3 * bw, 200)
            chosen = {'dist': 'empirical', 'label': 'Empirical', 'values': [], 'params': [], 'curve': {'x': g.tolist(), 'pdf': kde(g).tolist()}}
        else:
            chosen = next((f for f in cands if f['dist'] == want), cands[0])
            if chosen.get('warning'):
                warnings.warn(f'{name}, {chosen["label"]} margin: {chosen["warning"]}')
        out['columns'].append({'column': name, 'n': len(x), 'auto': cands[0]['dist'] if cands else 'empirical', 'want': want,
                               'candidates': [{k2: v for k2, v in f.items() if k2 != 'curve'} for f in cands],
                               'chosen': chosen})
        code.append(f'# {name}: {chosen["label"]}' + (' (the smallest AICc)' if want == 'auto' else ''))
        if chosen['dist'] == 'empirical':
            code.append(f'print({json.dumps(name)}, "empirical: F(v) interpolates i/(n + 1) between the sorted values")')
        elif chosen['dist'] == 'normal':
            code.append(f'print({json.dumps(name)}, x[:, {c}].mean(), x[:, {c}].std(ddof=1))   # μ and σ (the sample standard deviation, as JMP reports it)')
        else:
            floc = ', floc=0' if chosen['dist'] in ('lognormal', 'gamma', 'weibull', 'exponential') else ', floc=0, fscale=1' if chosen['dist'] == 'beta' else ''
            code.append(f'print({json.dumps(name)}, stats.{SCIPY[chosen["dist"]]}.fit(x[:, {c}]{floc}))   # maximum likelihood (scipy\'s parametrisation)')
    out['code'] = '\n'.join(code)
    return out


# ---- the joint distribution ----------------------------------------------------------------------------

def _pair_data(table, columns, rows, pair):
    X, idx, _ = _load(table, columns, rows)
    i, j = (pair or [0, 1])[:2]
    return X, idx, int(i), int(j)


@api('copula.joint')
def joint(table, columns, rows=None, family='indep', params=None, margins=None, pair=None, m=60):
    """The joint density on the data scale, c(F1(x), F2(y)) f1(x) f2(y) on a
    grid, and its highest-density levels (statsmodels' CopulaDistribution)."""
    X, idx, i, j = _pair_data(table, columns, rows, pair)
    ms = [margin((margins or [None, None])[0], X[:, i]), margin((margins or [None, None])[1], X[:, j])]
    grids = []
    for q, c in enumerate((i, j)):
        x = X[:, c]
        lo, hi = float(np.min(x)), float(np.max(x))
        pad = 0.1 * (hi - lo if hi > lo else abs(hi) + 1)
        a, b = ms[q].support()
        span = (hi - lo) or 1.0
        g0, g1 = max(lo - pad, a + 1e-6 * span if np.isfinite(a) else -np.inf), min(hi + pad, b - 1e-6 * span if np.isfinite(b) else np.inf)
        grids.append(np.linspace(g0, g1, int(m)))
    GX, GY = np.meshgrid(grids[0], grids[1])
    xy = np.column_stack([GX.ravel(), GY.ravel()])
    dist = CopulaDistribution(FittedCopula(family, list(params or [])), ms)
    with np.errstate(all='ignore'):
        u = np.clip(np.column_stack([ms[0].cdf(xy[:, 0]), ms[1].cdf(xy[:, 1])]), 1e-12, 1 - 1e-12)
        lz = logpdf(family, u, list(params or [])) + ms[0].logpdf(xy[:, 0]) + ms[1].logpdf(xy[:, 1])
        z = np.exp(lz).reshape(GX.shape)
    z[~np.isfinite(z)] = np.nan
    dA = (grids[0][1] - grids[0][0]) * (grids[1][1] - grids[1][0])
    # the density at a middle point, from statsmodels' CopulaDistribution, as a check of the grid
    mid = np.array([[float(np.median(X[:, i])), float(np.median(X[:, j]))]])
    with np.errstate(all='ignore'):
        sm_mid = float(np.atleast_1d(dist.pdf(mid))[0])
    return {'x': grids[0].tolist(), 'y': grids[1].tolist(), 'z': z.tolist(), 'levels': _hdr(np.nan_to_num(z), dA),
            'check': {'at': mid[0].tolist(), 'pdf': sm_mid}}


@api('copula.prob')
def prob(table, columns, rows=None, family='indep', params=None, margins=None, pair=None, x=None, y=None, table_name='data'):
    """Joint and conditional probabilities at (x, y) under the copula with
    the margins, under independence with the same margins, and in the data."""
    X, idx, i, j = _pair_data(table, columns, rows, pair)
    a, b = X[:, i], X[:, j]
    x = float(np.median(a)) if x is None else float(x)
    y = float(np.median(b)) if y is None else float(y)
    ms = [margin((margins or [None, None])[0], a), margin((margins or [None, None])[1], b)]
    u, v = float(ms[0].cdf(x)), float(ms[1].cdf(y))
    with np.errstate(all='ignore'):
        C = float(cdf(family, np.array([[min(max(u, 1e-15), 1 - 1e-15), min(max(v, 1e-15), 1 - 1e-15)]]), list(params or []))[0]) if 0 < u < 1 and 0 < v < 1 else (u * v if u in (0, 1) or v in (0, 1) else float('nan'))
    C = min(max(C, max(0.0, u + v - 1)), min(u, v))    # within the Fréchet bounds (numerical noise)

    def probs(u, v, C):
        both_gt = 1 - u - v + C
        return {'px': u, 'py': v, 'le': C, 'gt': both_gt, 'le_le': C / u if u > 0 else None, 'gt_gt': both_gt / (1 - u) if u < 1 else None}
    le_x, le_y = a <= x, b <= y
    n = len(a)
    obs = {'px': float(le_x.mean()), 'py': float(le_y.mean()), 'le': float((le_x & le_y).mean()), 'gt': float((~le_x & ~le_y).mean()),
           'le_le': float((le_x & le_y).sum() / le_x.sum()) if le_x.any() else None,
           'gt_gt': float((~le_x & ~le_y).sum() / (~le_x).sum()) if (~le_x).any() else None,
           'n_le_x': int(le_x.sum()), 'n_gt_x': int((~le_x).sum())}
    return {'x': x, 'y': y, 'model': probs(u, v, C), 'indep': probs(u, v, u * v), 'observed': obs, 'n': n,
            'columns': [columns[i], columns[j]]}


@api('copula.simulate')
def simulate(table, columns, rows=None, family='indep', params=None, margins=None, n=None, seed=1, scale='data', table_name='data'):
    """n draws of the fitted joint model, seeded: the copula's draws, turned
    into the margins' values by their quantile functions (statsmodels'
    CopulaDistribution.rvs); scale 'uniform' keeps the copula's draws."""
    columns = list(columns or [])
    k = len(columns)
    X, idx, _ = _load(table, columns, rows)
    n = int(n or len(X))
    if not 1 <= n <= 1_000_000:
        return {'error': 'the number of draws must be between 1 and 1 000 000'}
    seed = int(seed)
    params = list(params or [])
    rng = np.random.default_rng(seed)
    if scale == 'uniform':
        sim = FittedCopula(family, params, k).rvs(n, random_state=rng)
    else:
        ms = [margin((margins or [None] * k)[c], X[:, c]) for c in range(k)]
        sim = CopulaDistribution(FittedCopula(family, params, k), ms).rvs(n, random_state=rng)
    out = {'names': columns, 'values': sim.T.tolist(), 'n': n, 'seed': seed, 'family': family, 'scale': scale}
    out['code'] = simulate_code(table, table_name, rows, columns, family, params, margins, n, seed, scale, k)
    return out


def _rvs_text(family, params, k):
    """Draws of the copula as Python, with rng the generator."""
    if family == 'indep':
        return f'IndependenceCopula(k_dim={k}).rvs(n, random_state=rng)'
    if family == 'gaussian':
        return f'GaussianCopula(corr={corr_matrix(params, k).tolist()!r}, k_dim={k}).rvs(n, random_state=rng)'
    if family == 't':
        return f'StudentTCopula(corr={corr_matrix(params[:-1], k).tolist()!r}, df={params[-1]!r}, k_dim={k}).rvs(n, random_state=rng)'
    base, rot = BASE[family], ROT[family]
    th = float(params[0])
    if base == 'frank':
        return f'frank_rvs(n, {th!r}, rng)'
    if base == 'gumbel' and th <= 1 + 1e-9:
        d = 'IndependenceCopula().rvs(n, random_state=rng)'
    else:
        d = f'{_SM_CLASS[base]}(theta={th!r}).rvs(n, random_state=rng)'
    return f'rotate({d}, {rot})' if rot else d


def simulate_code(table, table_name, rows, columns, family, params, margins, n, seed, scale, k):
    imports = ['import math', 'from scipy import stats',
               'from statsmodels.distributions.copula.api import ClaytonCopula, GaussianCopula, GumbelCopula, IndependenceCopula, StudentTCopula']
    c = [code_head(table_name, imports)] + _rows_lines(table, rows)
    c.append(f'x = df[{json.dumps(columns)}].dropna().to_numpy()')
    helpers = []
    if ROT.get(family):
        helpers.append(rotate)
    if BASE.get(family) == 'frank':
        helpers += [frank_ppfcond, frank_rvs]
    if helpers:
        c += ['', _src(*helpers), '']
    c += [f'n, rng = {n}, np.random.default_rng({seed})', f'u = {_rvs_text(family, params, k)}   # the copula ({LABEL[family]})']
    if scale == 'uniform':
        c.append('sim = u')
    else:
        ms = []
        for q in range(k):
            spec = (margins or [None] * k)[q]
            if not spec or spec.get('dist') == 'empirical':
                ms.append(f'lambda p: np.quantile(x[:, {q}], p, method="weibull"),   # {columns[q]}: empirical')
            else:
                ms.append(f'{frozen_text(spec["dist"], spec["values"])}.ppf,   # {columns[q]}')
        c.append('ppf = [' + '\n       '.join(ms) + '\n]')
        c.append('# the margins\' quantiles of the copula\'s draws, as statsmodels\' CopulaDistribution.rvs makes them')
        c.append('sim = np.column_stack([f(0.5 + (1 - 1e-10) * (u[:, c] - 0.5)) for c, f in enumerate(ppf)])')
    c.append(f'sim = pd.DataFrame(sim, columns={json.dumps(columns)})')
    c.append('print(sim.head())')
    return '\n'.join(c)


# ---- goodness of fit and tail concentration -------------------------------------------------------------

def cvm(u, key, p):
    """Genest, Remillard and Beaudoin's (2009) S_n: the sum over the rows of
    (C_n(U_i) - C(U_i))^2, C_n the empirical copula."""
    return float(np.sum((emp_copula_self(u) - cdf(key, u, p)) ** 2))


@api('copula.gof')
def gof(table, columns, rows=None, families=None, method='mpl', rotations='auto', B=100, seed=1, table_name='data'):
    """The Cramér-von Mises statistic S_n of each family with a parametric
    bootstrap p-value (R copula's gofCopula(simulation = "pb")): draw n from
    the fitted copula, take pseudo-observations, fit again, compute S_n;
    p = (#{S_n* >= S_n} + 1/2)/(B + 1)."""
    columns = list(columns or [])
    X, idx, _ = _load(table, columns, rows)
    n, k = X.shape
    if k != 2:
        return {'error': 'the goodness-of-fit test is for two columns'}
    if n < 10:
        return {'error': 'too few rows for a goodness-of-fit test'}
    B = int(max(10, min(B, 5000)))
    u = pobs(X)
    tau = float(stats.kendalltau(X[:, 0], X[:, 1])[0])
    fams = chosen_families(families, rotations, tau, k)
    rows_out = []
    for key in fams:
        with np.errstate(all='ignore'):
            f = fit_family(key, u, method, ses=False)
            if 'error' in f:
                continue
            S = cvm(u, key, f['values'])
            rng = np.random.default_rng([int(seed), ORDER.index(key)])
            Sb = []
            for _ in range(B):
                ub = pobs(rvs(key, n, f['values'], rng))
                fb = fit_family(key, ub, method, ses=False)
                if 'error' in fb:
                    continue
                Sb.append(cvm(ub, key, fb['values']))
        Sb = np.asarray(Sb)
        rows_out.append({'family': key, 'label': LABEL[key], 'S': S, 'p': float((np.sum(Sb >= S) + 0.5) / (len(Sb) + 1)), 'B': int(len(Sb)),
                         'S_mean': float(Sb.mean()) if len(Sb) else None})
    return {'rows': rows_out, 'B': B, 'seed': int(seed), 'method': method, 'n': n,
            'code': gof_code(table, table_name, rows, columns, method)}


def gof_code(table, table_name, rows, columns, method):
    c = [code_head(table_name, ['from scipy import stats'])] + _rows_lines(table, rows)
    c += [f'x = df[{json.dumps(columns)}].dropna().to_numpy()',
          'u = stats.rankdata(x, axis=0) / (len(x) + 1)',
          '', _src(emp_copula), '',
          '# S_n of a fitted copula with its cdf C: the squared distance of the empirical copula from it, summed over the rows',
          'Sn = lambda u, C: np.sum((emp_copula(u) - C(u)) ** 2)',
          f'# the bootstrap: B times draw n from the fitted copula, take pseudo-observations, fit it again ({"maximum pseudo-likelihood" if method == "mpl" else "Kendall\'s τ"}) and compute Sn;',
          '# p = (the count of Sn* >= Sn + 1/2)/(B + 1). The fits and cdfs are those in the Copula Comparison code.']
    return '\n'.join(c)


@api('copula.tails')
def tails(table, columns, rows=None, fits=None, pair=None):
    """The tail concentration function: C(q, q)/q for q <= 1/2 and
    (1 - 2q + C(q, q))/(1 - q) above, for each fit; for the data the shares
    of the rows with both at or below q (over q) and both above it (over
    1 - q), which ties do not bias."""
    X, idx, i, j = _pair_data(table, columns, rows, pair)
    u = pobs(X[:, [i, j]])
    q = np.round(np.arange(0.02, 0.99, 0.01), 2)
    lo = q <= 0.5

    def conc(Cqq):
        return np.where(lo, Cqq / q, (1 - 2 * q + Cqq) / (1 - q))
    below = np.array([np.mean((u[:, 0] <= a) & (u[:, 1] <= a)) for a in q])
    above = np.array([np.mean((u[:, 0] > a) & (u[:, 1] > a)) for a in q])
    emp = np.where(lo, below / q, above / (1 - q))
    out = {'q': q.tolist(), 'empirical': emp.tolist(), 'fits': []}
    for f in fits or []:
        with np.errstate(all='ignore'):
            Cqq = cdf(f['family'], np.column_stack([q, q]), list(f.get('params') or []))
        out['fits'].append({'family': f['family'], 'label': LABEL.get(f['family'], f['family']), 'values': conc(Cqq).tolist()})
    return out
