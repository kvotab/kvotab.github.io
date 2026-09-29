"""Analyze > Specialized Modeling > Gaussian Process.

JMP's Gaussian Process platform on scikit-learn's GaussianProcessRegressor:
one model per continuous Y over continuous X's, fitted by maximum
likelihood with normalize_y (the optimizer's restarts drawn from the
report's seed).

  JMP's Gaussian correlation   r(x, x') = exp(-sum_k theta_k (x_k - x'_k)^2)
  scikit-learn's RBF kernel    k(x, x') = exp(-sum_k (x_k - x'_k)^2 / (2 l_k^2))

so theta_k = 1 / (2 l_k^2), l_k the length scale of column k in the
column's own units (the factors are not rescaled). The kernel is
ConstantKernel (sigma^2 in units of the variance of Y) times RBF, plus
WhiteKernel with Estimate Nugget Parameter; JMP's nugget is the ridge on the
correlation matrix, noise / sigma^2. JMP's other correlation, Cubic, is not
in scikit-learn; Matern (nu = 5/2 or 3/2) is offered under its own name.

JMP fits every row. Pyodide is single-threaded and the fit grows as n^3, so
more rows than max_rows (the launch's Rows to Fit, 400) are fitted on a random
subset of that size drawn from the seed; the other rows are predicted.

The report: the jackknife (leave-one-out) predictions with the kernel held,
in closed form (Rasmussen and Williams 2006, eq. 5.12); the functional ANOVA
of the fitted surface with the factors uniform over their ranges: each
factor's main effect E[f | x_k] and each pair's E[f | x_k, x_l], the other
factors integrated in closed form and the factor's own range by
Gauss-Legendre quadrature (the product form of the Gaussian correlation);
the total variance over scrambled Sobol points. Matern is not a product
over the factors: its indices are pick-freeze quasi-Monte Carlo estimates.
"""
import inspect
import json
import math
import warnings

import numpy as np

from . import predictive, profile
from .registry import api

CORRELATIONS = {'gaussian': 'Gaussian', 'matern52': 'Matérn ν = 5/2', 'matern32': 'Matérn ν = 3/2'}
PROGRESS = True          # 'smui:progress' lines while the optimizer runs (the page shows them)
QMC_TOTAL = 14           # 2^14 Sobol points for the total variance
QMC_PICK = 12            # 2^12 base points for the Matern pick-freeze estimates
AUTO_RESTARTS, AUTO_ROWS = 2, 150   # Optimizer Restarts left empty: 2 for at most 150 rows fitted, else none


# ---------------------------------------------------------------------------
# the helpers the shown code carries (their source goes under the report)
# ---------------------------------------------------------------------------

def jackknife(gp, y):
    """Leave-one-out predictions of the rows a fitted GaussianProcessRegressor
    learned from, its kernel and normalize_y's mean and scale held
    (Rasmussen and Williams 2006, eq. 5.12): y_i - [K^-1 y]_i / [K^-1]_ii on
    the normalized scale, and the standard deviation sqrt(1 / [K^-1]_ii)."""
    import numpy as np
    from scipy.linalg import cho_solve
    m, s = y.mean(), y.std()
    Kinv = cho_solve((gp.L_, True), np.eye(len(y)))
    dg = np.diag(Kinv)
    pred = m + s * ((y - m) / s - np.ravel(gp.alpha_) / dg)
    return pred, s / np.sqrt(dg)


def fanova_rbf(Xf, w, ell, lo, hi, predict, seed, m=14, refine=1.0):
    """Functional ANOVA of f(x) = mu + sum_i w_i prod_k exp(-(x_k - x_ik)^2 / (2 l_k^2))
    (a Gaussian process mean with the Gaussian correlation) with every
    factor uniform on [lo, hi]. The main effect E[f | x_k] and a pair's
    E[f | x_k, x_l] integrate the other factors in closed form (erf) and are
    squared and integrated over their own ranges by Gauss-Legendre
    quadrature; the total variance is exact for one or two factors and over
    2^m scrambled Sobol points for more. Returns the total variance, each
    main effect's variance, and each pair's closed variance
    Var E[f | x_k, x_l] (its interaction adds nothing beyond the mains when
    it equals their sum)."""
    import numpy as np
    from scipy.special import erf
    from scipy.stats import qmc
    n, d = Xf.shape
    W = hi - lo
    r2 = np.sqrt(2.0)
    # E exp(-(x_k - x_ik)^2 / (2 l_k^2)) over the range of x_k
    m1 = ell * np.sqrt(np.pi / 2) * (erf((hi - Xf) / (r2 * ell)) - erf((lo - Xf) / (r2 * ell))) / W
    Phi, om = [], []
    for k in range(d):
        q = int(min(256, max(24, np.ceil(refine * (4 * W[k] / ell[k] + 16)))))
        t, wt = np.polynomial.legendre.leggauss(q)
        Phi.append(np.exp(-(lo[k] + (t + 1) * W[k] / 2 - Xf[:, [k]]) ** 2 / (2 * ell[k] ** 2)))
        om.append(wt / 2)
    main = np.zeros(d)
    for k in range(d):
        g = (w * np.prod(np.delete(m1, k, axis=1), axis=1)) @ Phi[k]
        main[k] = om[k] @ g ** 2 - (om[k] @ g) ** 2
    closed = np.zeros((d, d))
    for k in range(d):
        for j in range(k + 1, d):
            a = w * np.prod(np.delete(m1, [k, j], axis=1), axis=1)
            G = (Phi[k] * a[:, None]).T @ Phi[j]
            closed[k, j] = closed[j, k] = om[k] @ G ** 2 @ om[j] - (om[k] @ G @ om[j]) ** 2
    if d == 1:
        V = main[0]
    elif d == 2:
        V = closed[0, 1]
    else:
        V = float(np.var(predict(lo + W * qmc.Sobol(d, scramble=True, seed=seed).random_base2(m))))
    return V, main, closed


def marginal_rbf(Xf, w, mu, ell, lo, hi, k, t):
    """The marginal model curve of factor k at the values t: E[f | x_k = t]
    with the other factors uniform over their ranges (in closed form)."""
    import numpy as np
    from scipy.special import erf
    r2 = np.sqrt(2.0)
    m1 = ell * np.sqrt(np.pi / 2) * (erf((hi - Xf) / (r2 * ell)) - erf((lo - Xf) / (r2 * ell))) / (hi - lo)
    a = w * np.prod(np.delete(m1, k, axis=1), axis=1)
    return mu + np.exp(-(np.asarray(t)[None, :] - Xf[:, [k]]) ** 2 / (2 * ell[k] ** 2)).T @ a


def fanova_mc(predict, lo, hi, seed, m=12):
    """The same functional ANOVA of any fitted surface predict(X) by
    pick-freeze quasi-Monte Carlo (Saltelli 2010): A and B are 2^m scrambled
    Sobol points in the box, A_B the points of A with the columns of the
    factor (or the pair) taken from B, and Var E[f | those columns] =
    mean(f(B) (f(A_B) - f(A))). Monte Carlo error remains."""
    import numpy as np
    from scipy.stats import qmc
    d = len(lo)
    W = hi - lo
    u = qmc.Sobol(2 * d, scramble=True, seed=seed).random_base2(m)
    A, B = lo + W * u[:, :d], lo + W * u[:, d:]
    fA, fB = predict(A), predict(B)
    V = float(np.var(np.r_[fA, fB]))
    main = np.zeros(d)
    closed = np.zeros((d, d))
    for k in range(d):
        AB = A.copy()
        AB[:, k] = B[:, k]
        main[k] = np.mean(fB * (predict(AB) - fA))
    for k in range(d):
        for j in range(k + 1, d):
            AB = A.copy()
            AB[:, [k, j]] = B[:, [k, j]]
            closed[k, j] = closed[j, k] = np.mean(fB * (predict(AB) - fA))
    return V, main, closed


def marginal_mc(predict, lo, hi, k, t, seed, m=12, most=256):
    """The marginal model curve of factor k by quasi-Monte Carlo: the mean
    prediction at x_k = t over the first `most` of the same Sobol points."""
    import numpy as np
    from scipy.stats import qmc
    d = len(lo)
    A = lo + (hi - lo) * qmc.Sobol(2 * d, scramble=True, seed=seed).random_base2(m)[:most, :d]
    out = []
    for v in t:
        Z = A.copy()
        Z[:, k] = v
        out.append(float(np.mean(predict(Z))))
    return np.array(out)


def indices(V, main, closed):
    """JMP's Model Report from the variances: each Main Effect V_k / V, each
    pair's Interaction (V_kl - V_k - V_l) / V, and the Total Sensitivity, a
    factor's main effect plus its interactions."""
    import numpy as np
    d = len(main)
    S = main / V
    inter = np.zeros((d, d))
    for k in range(d):
        for j in range(d):
            if j != k:
                inter[k, j] = (closed[k, j] - main[k] - main[j]) / V
    return S, inter, S + inter.sum(axis=1)


_HELPERS = (jackknife, fanova_rbf, marginal_rbf, fanova_mc, marginal_mc, indices)


def _source(fn):
    try:
        return inspect.getsource(fn).rstrip()
    except (OSError, TypeError):   # no source file (should not happen): name it at least
        return f'# {fn.__name__}: see resources/py/smui/gaussproc.py'


# ---------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------

def _kernel(correlation, nugget, span, sd):
    """The kernel before the fit: the length scales start at the columns'
    standard deviations (scikit-learn's usual 1 on standardized columns) and
    may go from 1/1000 to 1000 times the columns' ranges."""
    from sklearn.gaussian_process.kernels import RBF, ConstantKernel, Matern, WhiteKernel
    bounds = np.column_stack([1e-3 * span, 1e3 * span])
    if correlation == 'gaussian':
        base = RBF(length_scale=sd.copy(), length_scale_bounds=bounds)
    elif correlation in ('matern52', 'matern32'):
        base = Matern(length_scale=sd.copy(), length_scale_bounds=bounds, nu=2.5 if correlation == 'matern52' else 1.5)
    else:
        raise ValueError(f'unknown correlation type {correlation!r}')
    k = ConstantKernel(1.0, (1e-4, 1e4)) * base
    if nugget:
        k = k + WhiteKernel(1e-2, (1e-10, 10.0))
    return k


def _kernel_code(correlation, nugget):
    L = ['span, sd = hi - lo, Xf.std(axis=0, ddof=1)',
         'bounds = np.column_stack([1e-3 * span, 1e3 * span])   # each length scale from 1/1000 to 1000 times its range, starting at the sd']
    if correlation == 'gaussian':
        L.append('kernel = ConstantKernel(1.0, (1e-4, 1e4)) * RBF(length_scale=sd, length_scale_bounds=bounds)   # JMP\'s Gaussian correlation')
    else:
        nu = 2.5 if correlation == 'matern52' else 1.5
        L.append(f'kernel = ConstantKernel(1.0, (1e-4, 1e4)) * Matern(length_scale=sd, length_scale_bounds=bounds, nu={nu})   # not JMP\'s Cubic')
    if nugget:
        L.append('kernel = kernel + WhiteKernel(1e-2, (1e-10, 10.0))   # Estimate Nugget Parameter')
    return L


def _parts(gp, nugget):
    """(sigma^2 on the normalized scale, the correlation kernel, the noise)."""
    k = gp.kernel_
    prod = k.k1 if nugget else k
    return float(prod.k1.constant_value), prod.k2, (float(k.k2.noise_level) if nugget else 0.0)


def _optimizer(total):
    """scikit-learn's own L-BFGS-B (what optimizer='fmin_l_bfgs_b' runs),
    with a progress line after each start."""
    import scipy.optimize
    from sklearn.exceptions import ConvergenceWarning
    done = [0]

    def opt(obj_func, initial_theta, bounds):
        res = scipy.optimize.minimize(obj_func, initial_theta, method='L-BFGS-B', jac=True, bounds=bounds)
        if res.status != 0:
            warnings.warn(f'lbfgs failed to converge after {res.nit} iteration(s) (status={res.status}): {res.message}', ConvergenceWarning)
        done[0] += 1
        if PROGRESS:
            print(f'smui:progress gaussproc {done[0]} {total}', flush=True)
        return res.x, res.fun
    return opt


def _fit_idx(n, max_rows, seed):
    if n <= max_rows:
        return np.arange(n)
    return np.sort(np.random.default_rng(int(seed)).choice(n, int(max_rows), replace=False))


def _translate(w, names, y):
    """scikit-learn's warning that a hyperparameter ended at a bound, in the
    report's words (kept as a warning)."""
    text = str(w.message)
    if 'close to the specified' not in text:
        return text
    low = 'lower bound' in text
    try:
        dim = int(text.split('dimension ')[1].split(' ')[0])
    except (IndexError, ValueError):
        dim = 0
    if 'length_scale' in text:
        nm = names[dim] if dim < len(names) else f'factor {dim + 1}'
        if low:
            return f'{nm}: the length scale ended at its lower bound (1/1000 of the range of {nm}): the surface changes faster along {nm} than the rows can show.'
        return f'{nm}: the length scale ended at its upper bound (1000 times the range of {nm}): θ is about 0, {nm} has no effect the model can detect on {y}.'
    if 'noise_level' in text:
        return ('The nugget ended at its lower bound: the model goes through the rows (they look noiseless).' if low
                else 'The nugget ended at its upper bound: the rows look like noise about a constant.')
    if 'constant_value' in text:
        return ('σ² ended at its lower bound (1/10000 of the variance of Y).' if low
                else 'σ² ended at its upper bound (10000 times the variance of Y): the surface is smoother than the search allows (close to a polynomial); the estimates are limits of the search, not a maximum.')
    return text


class _Model:
    pass


def _build(table, rows, y, x, correlation, nugget, max_rows, restarts, seed):
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.gaussian_process import GaussianProcessRegressor
    x = list(x or [])
    if not y:
        raise ValueError('choose a Y, Response')
    if not x:
        raise ValueError('choose at least one X')
    if y in x:
        raise ValueError(f'{y} cannot be both the response and a factor')
    P = predictive.prepare(table, y, x, rows, missing='drop', categorical_y=False)
    n, d = P.X.shape
    if n < 3:
        raise ValueError(f'{y}: {n} rows with the response and every factor; a Gaussian process needs at least 3')
    max_rows = max(3, int(max_rows))
    fit = _fit_idx(n, max_rows, seed)
    Xf, yf = P.X[fit], P.target[fit]
    lo, hi = Xf.min(axis=0), Xf.max(axis=0)
    span = hi - lo
    for nm, s in zip(P.x, span):
        if not s > 0:
            raise ValueError(f'{nm} has one value in the rows fitted')
    if not np.std(yf) > 0:
        raise ValueError(f'{y} has one value in these rows')
    restarts = (AUTO_RESTARTS if len(fit) <= AUTO_ROWS else 0) if restarts is None or restarts == '' else max(0, int(restarts))
    M = _Model()
    M.P, M.fit, M.Xf, M.yf, M.lo, M.hi, M.x, M.y = P, fit, Xf, yf, lo, hi, list(P.x), y
    M.correlation, M.nugget, M.seed, M.restarts, M.max_rows = correlation, bool(nugget), int(seed), restarts, max_rows
    M.jitter = 1e-10
    M.warnings = []
    for jitter in (1e-10, 1e-8, 1e-6, 1e-4):
        gp = GaussianProcessRegressor(_kernel(correlation, nugget, span, Xf.std(axis=0, ddof=1)), alpha=jitter, normalize_y=True, n_restarts_optimizer=restarts,
                                      random_state=int(seed), optimizer=_optimizer(1 + restarts))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            try:
                gp.fit(Xf, yf)
            except np.linalg.LinAlgError:
                continue
        M.jitter = jitter
        for w in caught:
            if issubclass(w.category, (DeprecationWarning, PendingDeprecationWarning, FutureWarning)):
                continue
            cat = w.category if issubclass(w.category, Warning) else UserWarning
            text = _translate(w, M.x, y) if issubclass(cat, ConvergenceWarning) else str(w.message)
            if (cat, text) not in M.warnings:
                M.warnings.append((cat, text))
        break
    else:
        raise ValueError(f'{y}: the correlation matrix stays singular (rows with the same factor values and different responses): turn on Estimate Nugget Parameter')
    M.gp = gp
    M.mu, M.s = float(yf.mean()), float(yf.std())
    M.c, M.base, M.noise = _parts(gp, nugget)
    M.ell = np.atleast_1d(np.asarray(M.base.length_scale, dtype=float)) * np.ones(d)
    M.w = M.s * M.c * np.ravel(gp.alpha_)
    return M


def _model(table, rows, y, x, correlation='gaussian', nugget=False, max_rows=400, restarts=None, seed=None):
    seed = predictive.seed_of(seed)
    seed = 0 if seed is None else seed
    restarts = None if restarts is None or restarts == '' else int(restarts)
    spec = {'y': y, 'x': list(x or []), 'correlation': correlation, 'nugget': bool(nugget), 'max_rows': int(max_rows), 'restarts': restarts, 'seed': seed}
    return predictive.cached('gaussproc', table, rows, spec, lambda: _build(table, rows, **spec))


def _predict(M):
    return lambda X: M.gp.predict(np.asarray(X, dtype=float))


def _fanova(M):
    """(V, main, closed, method) of the model's surface over the fit rows' ranges."""
    if M.correlation == 'gaussian':
        V, main, closed = fanova_rbf(M.Xf, M.w, M.ell, M.lo, M.hi, _predict(M), M.seed, m=QMC_TOTAL)
        return V, main, closed, 'quadrature'
    V, main, closed = fanova_mc(_predict(M), M.lo, M.hi, M.seed, m=QMC_PICK)
    return V, main, closed, 'qmc'


def _marginals(M, grid=61):
    out = []
    for k, nm in enumerate(M.x):
        t = np.linspace(M.lo[k], M.hi[k], grid)
        if M.correlation == 'gaussian':
            f = marginal_rbf(M.Xf, M.w, M.mu, M.ell, M.lo, M.hi, k, t)
        else:
            f = marginal_mc(_predict(M), M.lo, M.hi, k, t, M.seed, m=QMC_PICK)
        out.append({'x': nm, 't': t.tolist(), 'f': np.asarray(f, dtype=float).tolist()})
    return out


# ---------------------------------------------------------------------------
# the code under the report
# ---------------------------------------------------------------------------

def _fit_lines(M):
    """The model as the report fits it: the rows fitted, the kernel, the fit and its parameters."""
    L = []
    if len(M.P.index) > M.max_rows:
        L.append(f'fit = np.sort(np.random.default_rng({M.seed}).choice(len(d), {M.max_rows}, replace=False))   # the {M.max_rows} rows the model is fitted to')
    else:
        L.append('fit = np.arange(len(d))   # every row fits the model')
    L.append('Xf, yf = X[fit], y[fit]')
    L.append('lo, hi = Xf.min(axis=0), Xf.max(axis=0)')
    L += _kernel_code(M.correlation, M.nugget)
    L.append(f'gp = GaussianProcessRegressor(kernel, alpha={M.jitter!r}, normalize_y=True, n_restarts_optimizer={M.restarts}, random_state={M.seed}).fit(Xf, yf)')
    L.append('')
    L.append('k = gp.kernel_')
    L.append('prod = k.k1   # (ConstantKernel * correlation) + WhiteKernel' if M.nugget else 'prod = k   # ConstantKernel * correlation')
    L.append('c, ell = prod.k1.constant_value, np.atleast_1d(prod.k2.length_scale) * np.ones(X.shape[1])')
    L.append('mu, s = yf.mean(), yf.std()   # normalize_y')
    return L


def _code(M, table_name, rows, fanova_method):
    P = M.P
    imports = ['from scipy.linalg import cho_solve', 'from scipy.special import erf', 'from scipy.stats import qmc',
               'from sklearn.gaussian_process import GaussianProcessRegressor',
               'from sklearn.gaussian_process.kernels import RBF, ConstantKernel, Matern, WhiteKernel']
    L = P.code(table_name, rows, extra_imports=imports)
    L.append('')
    L += _fit_lines(M)
    if M.correlation == 'gaussian':
        L.append('print("Theta", 1 / (2 * ell ** 2))   # JMP\'s exp(-Σ θ (x - x\')²) is exp(-Σ (x - x\')² / (2 ℓ²))')
    L.append('print("Length Scale", ell)')
    L.append('print("Mu", mu, "Sigma²", c * s ** 2' + (', "Nugget", k.k2.noise_level / c)' if M.nugget else ')'))
    L.append('print("-2 LogLikelihood", -2 * (gp.log_marginal_likelihood_value_ - len(yf) * np.log(s)))')
    L.append('')
    L.append(_source(jackknife))
    L.append('')
    L.append('jack, jack_sd = jackknife(gp, yf)')
    L.append('print("Jackknife predictions", jack[:5], "...")')
    L.append('')
    helpers = [fanova_rbf, marginal_rbf, indices] if fanova_method == 'quadrature' else [fanova_mc, marginal_mc, indices]
    for h in helpers:
        L.append(_source(h))
        L.append('')
    if fanova_method == 'quadrature':
        L.append('w = s * c * gp.alpha_   # the fitted mean is mu + Σ_i w_i Π_k exp(-(x_k - x_ik)² / (2 ℓ_k²))')
        L.append(f'V, main, closed = fanova_rbf(Xf, w, ell, lo, hi, gp.predict, seed={M.seed}, m={QMC_TOTAL})')
    else:
        L.append(f'V, main, closed = fanova_mc(gp.predict, lo, hi, seed={M.seed}, m={QMC_PICK})')
    L.append('S, inter, total = indices(V, main, closed)')
    L.append('print("Total Sensitivity", total)')
    L.append('print("Main Effect", S)')
    L.append('print("Interactions", inter)')
    if fanova_method == 'quadrature':
        L.append('curve = marginal_rbf(Xf, w, mu, ell, lo, hi, 0, np.linspace(lo[0], hi[0], 61))   # the first factor\'s marginal model curve')
    else:
        L.append(f'curve = marginal_mc(gp.predict, lo, hi, 0, np.linspace(lo[0], hi[0], 61), seed={M.seed}, m={QMC_PICK})')
    return '\n'.join(L)


# ---------------------------------------------------------------------------
# the graphs' code (smui-p-gaussproc.js puts each under its graph)
# ---------------------------------------------------------------------------

OTHER = '#3a7d44'   # the rows not fitted (smui-p-gaussproc.js colors().other, light theme)


def _graph_head(M, table_name, rows, how):
    """The head of the report's graphs: the model fitted as the report fits it, the jackknife
    predictions of the rows fitted, the other rows predicted by the whole model, and the helper of the
    marginal model curves."""
    imports = ['from sklearn.gaussian_process import GaussianProcessRegressor',
               'from sklearn.gaussian_process.kernels import RBF, ConstantKernel, Matern, WhiteKernel', predictive.PLT]
    L = M.P.code(table_name, rows, extra_imports=imports)
    L.append('')
    L += _fit_lines(M)
    L += ['', _source(jackknife), '',
          'jack, jack_sd = jackknife(gp, yf)   # each fitted row predicted without it, the kernel held',
          'other = np.setdiff1d(np.arange(len(d)), fit)   # the rows not fitted (more than Rows to Fit), predicted by the whole model',
          'opred = gp.predict(X[other]) if len(other) else np.zeros(0)', '']
    if how == 'quadrature':
        L += [_source(marginal_rbf), '',
              'w = s * c * np.ravel(gp.alpha_)   # the fitted mean is mu + Σ_i w_i Π_k exp(-(x_k - x_ik)² / (2 ℓ_k²))']
    else:
        L += [_source(marginal_mc)]
    return '\n'.join(L)


def _abp_tail(M, n, n_other):
    """Actual by Predicted Plot: each row fitted against its jackknife prediction, the other rows
    (diamonds) against the whole model's."""
    J = json.dumps
    size = 14 if n <= 600 else 8 if n <= 2000 else 5   # the page's marker size by the number of rows
    L = [predictive.figure(430, 380),
         f'ax.scatter(jack, yf, s={size}, color="{predictive.BASE}", label="Jackknife (rows fitted)")']
    if n_other:
        L.append(f'ax.scatter(opred, y[other], s={size}, marker="D", color="{OTHER}", label="Predicted (not fitted)")')
    L += ['v = np.r_[jack, yf, opred, y[other]]',
          'v = v[np.isfinite(v)]',
          f'ax.plot([v.min(), v.max()], [v.min(), v.max()], color="{predictive.MUTED}", linewidth=1, linestyle=":")   # actual = predicted',
          f'ax.set_xlabel({J(M.y + " Jackknife Predicted")})', f'ax.set_ylabel({J(M.y)})',
          f'ax.set_title({J(M.y + " actual by jackknife predicted")}, wrap=True)']
    if n_other:
        L.append('fig.legend(loc="outside upper left", ncols=2, frameon=False, fontsize=8)')
    L.append('plt.show()')
    return '\n'.join(L)


def _marginal_tail(M, k, how, grid=61):
    """Marginal Model Plot of factor k: its main effect E[f | x_k] over its range in the rows fitted, on
    the scale every factor's plot shares (from the lowest to the highest of all the curves)."""
    J = json.dumps
    d = len(M.x)
    if how == 'quadrature':
        curve = 'marginal_rbf(Xf, w, mu, ell, lo, hi, j, ts[j])'
    else:
        curve = f'marginal_mc(gp.predict, lo, hi, j, ts[j], seed={M.seed}, m={QMC_PICK})'
    return '\n'.join([
        f'ts = [np.linspace(lo[j], hi[j], {grid}) for j in range(X.shape[1])]',
        f'curves = [{curve} for j in range(X.shape[1])]   # every factor\'s curve: the plots share the scale',
        'f_lo, f_hi = min(f.min() for f in curves), max(f.max() for f in curves)',
        'pad = 0.06 * ((f_hi - f_lo) or abs(f_hi) or 1)',
        predictive.figure(260 if d > 3 else 300, 230),   # the page's width (240 for more than three factors, 260 at least)
        f'ax.plot(ts[{k}], curves[{k}], color="{predictive.BASE}", linewidth=2)   # {M.x[k]}',
        'ax.set_ylim(f_lo - pad, f_hi + pad)',
        f'ax.set_xlabel({J(M.x[k])})', f'ax.set_ylabel({J(M.y)})',
        f'ax.set_title({J(M.y + " marginal model plot of " + M.x[k])}, wrap=True)',   # wrapped when longer than the graph is wide
        'plt.show()'])


# ---------------------------------------------------------------------------
# the page's calls
# ---------------------------------------------------------------------------

@api('gaussproc.fit', packages=predictive.SK)
def fit(table, y, x, rows=None, correlation='gaussian', nugget=False, max_rows=400, restarts=None, seed=None, table_name='data'):
    """The report of one response: jackknife actual by predicted, the Model
    Report (theta, the functional ANOVA, -2 LogLikelihood, mu, sigma^2, the
    nugget), the marginal model curves."""
    try:
        M = _model(table, rows, y, x, correlation, nugget, max_rows, restarts, seed)
    except ValueError as e:
        return {'error': str(e)}
    for cat, text in M.warnings:
        warnings.warn(text, cat)
    P = M.P
    n, d = P.X.shape
    jack, jsd = jackknife(M.gp, M.yf)
    r = M.yf - jack
    sst = float(np.sum((M.yf - M.yf.mean()) ** 2))
    other = np.setdiff1d(np.arange(n), M.fit)
    opred = M.gp.predict(P.X[other]) if len(other) else np.zeros(0)
    V, main, closed, how = _fanova(M)
    S, inter, total = indices(V, main, closed) if V > 0 else (np.full(d, np.nan), np.full((d, d), np.nan), np.full(d, np.nan))
    if how == 'quadrature':            # round-off of exact zeros (a factor with no effect) shows as 0
        S, inter, total = (np.where(np.abs(a) < 1e-9, 0.0, a) for a in (S, inter, total))
    report = []
    for k, nm in enumerate(M.x):
        row = {'column': nm, 'theta': float(1 / (2 * M.ell[k] ** 2)) if M.correlation == 'gaussian' else None, 'length': float(M.ell[k]),
               'total': float(total[k]), 'main': float(S[k])}
        for j in range(d):
            row[f'i{j}'] = None if j == k else float(inter[k, j])
        report.append(row)
    lml = float(M.gp.log_marginal_likelihood_value_)
    notes = [t.replace(' (Informative Missing is off)', '').replace('missing a factor', 'missing a factor (an X)') for t in P.notes]
    if not M.nugget and sst > 0 and 1 - float(np.sum(r * r)) / sst < 0.1:
        notes.append(f'The jackknife predicts {y} hardly better than its mean: without a nugget the model must go through every row, and for noisy rows the likelihood prefers short length scales that take them for noise. With a noisy {y}, turn on Estimate Nugget Parameter.')
    if not M.nugget:
        _, first, counts = np.unique(M.Xf, axis=0, return_index=True, return_counts=True)
        rep = int(np.sum(counts - 1))
        if rep:
            notes.append(f'{rep} of the rows fitted repeat the factor values of another row: without a nugget the model must go through every row; with replicates, turn on Estimate Nugget Parameter.')
    if M.jitter > 1e-10:
        notes.append(f'The correlation matrix was singular: {M.jitter:g} (of the variance of {y}) was added to its diagonal, as JMP sets a nugget to avoid a singular variance matrix.')
    return {
        'y': y, 'x': M.x, 'n': int(n), 'n_fit': int(len(M.fit)), 'capped': bool(n > M.max_rows), 'max_rows': M.max_rows, 'seed': M.seed,
        'correlation': M.correlation, 'correlation_label': CORRELATIONS[M.correlation], 'kernel': str(M.gp.kernel_), 'jitter': M.jitter, 'restarts': M.restarts,
        'fit_rows': P.index[M.fit].tolist(), 'actual': M.yf.tolist(), 'jackknife': jack.tolist(), 'jack_sd': jsd.tolist(),
        'other_rows': P.index[other].tolist(), 'other_actual': P.target[other].tolist(), 'other_pred': np.asarray(opred, dtype=float).tolist(),
        'report': report, 'V': float(V), 'fanova': how,
        'mu': M.mu, 'sigma2': M.c * M.s ** 2, 'nugget': (M.noise / M.c) if M.nugget else None, 'noise_var': M.noise * M.s ** 2 if M.nugget else None,
        'm2ll': -2 * (lml - len(M.yf) * math.log(M.s)), 'lml_normalized': lml,
        'jack_rsquare': 1 - float(np.sum(r * r)) / sst if sst > 0 else None, 'jack_rase': math.sqrt(float(np.mean(r * r))),
        'marginal': _marginals(M), 'ranges': [[float(a), float(b)] for a, b in zip(M.lo, M.hi)],
        'notes': notes, 'code': _code(M, table_name, rows, how),
        'plots': {'head_code': _graph_head(M, table_name, rows, how), 'abp': _abp_tail(M, n, len(other)),
                  'marginal': [_marginal_tail(M, k, how) for k in range(d)]},
    }


@api('gaussproc.save', packages=predictive.SK)
def save(table, y, x, rows=None, correlation='gaussian', nugget=False, max_rows=400, restarts=None, seed=None):
    """Save Prediction and Save Std Error for every row of the table with
    every factor (a formula column would give them), and the jackknife
    predictions of the rows fitted."""
    M = _model(table, rows, y, x, correlation, nugget, max_rows, restarts, seed)
    X, rws = M.P.all_rows()
    pred, sd = M.gp.predict(X, return_std=True) if len(rws) else (np.zeros(0), np.zeros(0))
    jack, _ = jackknife(M.gp, M.yf)
    return {'y': y, 'rows': rws.tolist(), 'pred': np.asarray(pred, dtype=float).tolist(), 'std': np.asarray(sd, dtype=float).tolist(),
            'jack_rows': M.P.index[M.fit].tolist(), 'jack': jack.tolist()}


def _predictor(table, rows=None, y=None, x=(), correlation='gaussian', nugget=False, max_rows=400, restarts=None, seed=None, alpha=0.05):
    """The Prediction Profiler's view: the mean with a band of
    z(1 - alpha/2) standard deviations of scikit-learn's
    predict(return_std=True) (with a nugget, the noise is in it)."""
    from scipy.stats import norm
    M = _model(table, rows, y, x, correlation, nugget, max_rows, restarts, seed)
    z = float(norm.ppf(1 - float(alpha) / 2))
    factors = [{'name': nm, 'type': 'continuous', 'min': float(M.lo[k]), 'max': float(M.hi[k]), 'mean': float(M.Xf[:, k].mean())} for k, nm in enumerate(M.x)]

    def run(settings):
        X = np.array([[float(s[nm]) for nm in M.x] for s in settings], dtype=float)
        mean, sd = M.gp.predict(X, return_std=True)
        return [{'name': y, 'pred': mean, 'lower': mean - z * sd, 'upper': mean + z * sd, 'bounded': False}]
    return profile.Predictor(factors, run, data={nm: M.Xf[:, k].tolist() for k, nm in enumerate(M.x)})


profile.expose('gaussproc', _predictor, packages=predictive.SK, alpha=True)
