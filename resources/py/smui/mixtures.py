"""Analyze > Clustering > Normal Mixtures.

The rows as a mixture of multivariate normal distributions, fitted by EM
(scikit-learn's GaussianMixture) for one number of clusters or a range,
compared by -2 log likelihood, AICc and BIC; for each fit the mixing
proportions, the clusters' means, standard deviations and correlations, and
every row's probability of each cluster.

  covariance  full       a covariance matrix for each cluster
              diag       one for each cluster, without correlations
              tied       one covariance matrix for all the clusters
              spherical  one variance for each cluster, the same in every column

JMP's Outlier Cluster, a uniform distribution over the box that holds the
rows, is not in scikit-learn. With it, outlier_em() runs the EM of the
normal clusters and the uniform one from GaussianMixture's own k-means
starts; without the uniform cluster it is GaussianMixture's EM, which the
tests check.

By default the columns are fitted on the standardized scale (Columns Scaled
Individually); the means, standard deviations and log likelihoods are
reported in the columns' own units. A Freq column repeats its rows.
"""
import inspect
import json
import math

import numpy as np

from . import data, predictive, profile
from .registry import api
from .util import code_head

SK = predictive.SK
COVARIANCES = ('full', 'diag', 'tied', 'spherical')
REG_COVAR = 1e-6
MAX_OBS = 200000          # rows after Freq repeats them
MAX_FITS = 20             # numbers of clusters in one range
J = json.dumps


def _dated(obj, table):
    """Code that reads the table's CSV (a string, or the strings of a list
    or dict) with the line that turns each date column it names back into
    the page's number, as dispatch does for the keys code and *_code."""
    from .util import date_columns, dated_code
    cols = date_columns(table)
    if not cols:
        return obj
    if isinstance(obj, str):
        return dated_code(obj, cols)
    if isinstance(obj, list):
        return [_dated(v, table) for v in obj]
    if isinstance(obj, dict):
        return {k: _dated(v, table) for k, v in obj.items()}
    return obj


# ---------------------------------------------------------------------------
# the EM with an outlier cluster (its source goes into the code shown)
# ---------------------------------------------------------------------------

def mixture_log_parts(Z, weights, means, covariances, log_box=None):
    """log(weight x density) of each cluster at the rows of Z: the normal
    clusters, then the uniform one when log_box (its log density) is given."""
    import numpy as np
    from scipy import linalg
    n, p = Z.shape
    k = len(means)
    out = np.empty((n, k + (log_box is not None)))
    for j in range(k):
        try:
            c = linalg.cholesky(covariances[j], lower=True)
        except linalg.LinAlgError:
            raise ValueError('the mixture could not be fitted: a cluster has no spread (too few distinct rows); '
                             'try fewer clusters or another covariance structure')
        y = linalg.solve_triangular(c, (Z - means[j]).T, lower=True)
        out[:, j] = np.log(weights[j]) - 0.5 * (np.sum(y * y, axis=0) + p * np.log(2 * np.pi)) - np.log(np.diag(c)).sum()
    if log_box is not None:
        out[:, k] = np.log(weights[k]) + log_box
    return out


def outlier_em(Z, k, covariance='full', tours=10, seed=0, max_iter=500, tol=1e-6, reg_covar=1e-6, uniform=True, start=0.05):
    """EM for k normal clusters and, with uniform=True, a uniform cluster over
    the box that holds the rows of Z. The starts are GaussianMixture's: the
    labels of one k-means run per tour, all from one random state; the tour
    with the largest mean log likelihood is kept. The uniform cluster starts
    with the weight `start`. covariance: 'full', 'diag', 'tied' or 'spherical'.
    Returns the weights (the uniform cluster's last), means, covariances
    (k x p x p), the uniform cluster's log density, iterations, convergence."""
    import warnings
    import numpy as np
    from scipy.special import logsumexp
    from sklearn.cluster import KMeans
    from sklearn.exceptions import ConvergenceWarning
    n, p = Z.shape
    eps = 10 * np.finfo(float).eps
    log_box = -np.log(np.ptp(Z, axis=0)).sum() if uniform else None

    def m_step(r):
        # the normal clusters' weights, means and covariances from their responsibilities r (n x k)
        nk = r.sum(axis=0) + eps
        means = r.T @ Z / nk[:, None]
        covs = np.empty((k, p, p))
        for j in range(k):
            d = Z - means[j]
            covs[j] = (r[:, j, None] * d).T @ d / nk[j]
        if covariance == 'tied':
            covs[:] = np.tensordot(nk, covs, axes=1) / nk.sum()
        elif covariance in ('diag', 'spherical'):
            v = np.diagonal(covs, axis1=1, axis2=2).copy()
            if covariance == 'spherical':
                v[:] = v.mean(axis=1, keepdims=True)
            covs = np.zeros((k, p, p))
            covs[:, np.arange(p), np.arange(p)] = v
        covs[:, np.arange(p), np.arange(p)] += reg_covar
        return nk, means, covs

    rs = np.random.RandomState(seed)
    best = None
    for tour in range(tours):
        labels = KMeans(n_clusters=k, n_init=1, random_state=rs).fit(Z).labels_
        r = np.zeros((n, k))
        r[np.arange(n), labels] = 1
        nk, means, covs = m_step(r)
        weights = nk / n
        if uniform:
            weights = np.append((1 - start) * weights, start)
        lower, converged, it = -np.inf, False, 0
        for it in range(1, max_iter + 1):
            prev = lower
            logp = mixture_log_parts(Z, weights, means, covs, log_box)
            logf = logsumexp(logp, axis=1)
            r = np.exp(logp - logf[:, None])
            nk, means, covs = m_step(r[:, :k])
            tot = r.sum(axis=0) + eps
            weights = tot / tot.sum()
            lower = logf.mean()
            if abs(lower - prev) < tol:
                converged = True
                break
        if best is None or lower > best['lower_bound']:
            best = {'weights': weights, 'means': means, 'covariances': covs, 'log_box': log_box,
                    'lower_bound': lower, 'n_iter': it, 'converged': converged}
    if not best['converged'] and max_iter > 0:
        warnings.warn('Best performing initialization did not converge. Try more iterations or a looser '
                      'convergence criterion.', ConvergenceWarning)
    return best


# ---------------------------------------------------------------------------
# the data and the fits
# ---------------------------------------------------------------------------

class Data:
    """The rows of one report: X (unique rows, the columns' units), their
    frequencies f (or None), and the fitting scale."""

    def __init__(self, table, columns, rows, freq, standardize):
        cols = [c for c in dict.fromkeys(columns or []) if c]
        if not cols:
            raise ValueError('choose one or more Y, Columns')
        if freq and freq in cols:
            raise ValueError(f'{freq} cannot be both a Y column and the Freq')
        names = cols + ([freq] if freq else [])
        df = data.frame(table, names, rows, dropna=False, as_category=False)
        for c in names:
            if df[c].dtype == object:
                raise ValueError(f'{c} is not numeric')
        n0 = len(df)
        ok = np.isfinite(df[names].to_numpy(float)).all(axis=1)
        self.notes = []
        if (~ok).sum():
            self.notes.append(f'{int((~ok).sum())} row{"s" if (~ok).sum() != 1 else ""} with a missing value left out.')
        df = df[ok]
        f = None
        if freq:
            fv = df[freq].to_numpy(float)
            keep = fv >= 1
            if (~keep).sum():
                self.notes.append(f'{int((~keep).sum())} row{"s" if (~keep).sum() != 1 else ""} with a frequency below 1 left out.')
            if np.any(fv[keep] != np.floor(fv[keep])):
                self.notes.append(f'{freq} holds fractions: frequencies are rounded down to whole numbers.')
            df = df[keep]
            f = np.floor(fv[keep]).astype(int)
        self.table, self.cols, self.freq = table, cols, freq
        self.rows_in = rows
        self.index = np.asarray(df.index, dtype=int)
        self.X = df[cols].to_numpy(float)
        self.f = f
        self.n_rows = len(self.X)
        self.n_left = n0 - self.n_rows
        self.N = int(f.sum()) if f is not None else self.n_rows
        if self.N > MAX_OBS:
            raise ValueError(f'{freq} adds up to {self.N} rows: more than the {MAX_OBS} the page fits')
        self.p = len(cols)
        self.Xf = np.repeat(self.X, f, axis=0) if f is not None else self.X
        if self.n_rows < 2:
            raise ValueError('fewer than two rows with every column')
        const = [c for c, v in zip(cols, np.ptp(self.X, axis=0)) if not v > 0]
        if const:
            raise ValueError(f'{", ".join(const)} {"has" if len(const) == 1 else "have"} a single value in these rows: nothing to cluster by')
        self.standardize = bool(standardize)
        if self.standardize:
            self.m = self.Xf.mean(axis=0)
            self.s = self.Xf.std(axis=0, ddof=1)
        else:
            self.m = np.zeros(self.p)
            self.s = np.ones(self.p)
        self.Z = (self.X - self.m) / self.s
        self.Zf = (self.Xf - self.m) / self.s

    def counts(self, labels, m):
        f = np.ones(self.n_rows) if self.f is None else self.f
        return np.bincount(labels, weights=f, minlength=m)


class Mixture:
    """A fitted mixture on the fitting scale: the normal clusters' weights
    (largest first), means and covariances (k x p x p), and the uniform
    cluster's weight (last) and log density when there is one."""

    def __init__(self, weights, means, covs, log_box=None, gm=None, order=None, n_iter=0, converged=True):
        self.weights = np.asarray(weights, float)
        self.means = np.asarray(means, float)
        self.covs = np.asarray(covs, float)
        self.log_box = log_box
        self.gm = gm
        self.order = order
        self.n_iter = int(n_iter)
        self.converged = bool(converged)
        self.k = len(self.means)

    @property
    def outlier(self):
        return self.log_box is not None

    def proba(self, Z):
        """Every cluster's probability at the rows of Z (the uniform last)."""
        if self.gm is not None:
            return self.gm.predict_proba(Z)[:, self.order]
        from scipy.special import logsumexp
        lp = mixture_log_parts(Z, self.weights, self.means, self.covs, self.log_box)
        return np.exp(lp - logsumexp(lp, axis=1)[:, None])

    def loglik(self, Z):
        """The log likelihood of the rows of Z (on the fitting scale)."""
        if self.gm is not None:
            return float(self.gm.score(Z) * len(Z))
        from scipy.special import logsumexp
        return float(logsumexp(mixture_log_parts(Z, self.weights, self.means, self.covs, self.log_box), axis=1).sum())


def _full_covs(gm):
    """GaussianMixture's covariances as k x p x p matrices, whatever their type."""
    k, p = gm.means_.shape
    c = np.asarray(gm.covariances_, float)
    if gm.covariance_type == 'full':
        return c.copy()
    if gm.covariance_type == 'tied':
        return np.repeat(c[None], k, axis=0)
    out = np.zeros((k, p, p))
    v = c if gm.covariance_type == 'diag' else np.repeat(c[:, None], p, axis=1)
    out[:, np.arange(p), np.arange(p)] = v
    return out


def n_parameters(k, p, covariance, outlier=False):
    """The number of free parameters, as scikit-learn counts them, and one
    more for the outlier cluster's proportion."""
    cov = {'full': k * p * (p + 1) // 2, 'diag': k * p, 'tied': p * (p + 1) // 2, 'spherical': k}[covariance]
    return int(cov + k * p + k - 1 + (1 if outlier else 0))


def _criteria(loglik, q, N):
    aicc = -2 * loglik + 2 * q + (2 * q * (q + 1) / (N - q - 1) if N - q - 1 > 0 else math.inf)
    return {'loglik': loglik, 'm2ll': -2 * loglik, 'n_params': q, 'aic': -2 * loglik + 2 * q, 'aicc': aicc, 'bic': -2 * loglik + q * math.log(N)}


def quiet_threadpoolctl():
    """Pyodide 314's threadpoolctl calls a deprecated JsProxy method the
    first time scikit-learn asks for its thread pools; its RuntimeWarning
    says nothing about the analysis, so the controller is made once
    without it (scikit-learn keeps it)."""
    import warnings
    try:
        from sklearn.utils import parallel
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', message=r'JsProxy\.as_object_map', category=RuntimeWarning)
            parallel._get_threadpool_controller()
    except Exception:   # another scikit-learn: nothing to quiet
        pass


def _fit_k(D, k, covariance, tours, seed, max_iter, tol, outlier):
    quiet_threadpoolctl()
    if outlier:
        r = outlier_em(D.Zf, k, covariance, tours, seed, max_iter, tol, REG_COVAR, uniform=True)
        w = r['weights']
        order = np.argsort(-w[:k], kind='stable')
        return Mixture(np.append(w[:k][order], w[k]), r['means'][order], r['covariances'][order], log_box=r['log_box'],
                       n_iter=r['n_iter'], converged=r['converged'])
    from sklearn.mixture import GaussianMixture
    gm = GaussianMixture(n_components=k, covariance_type=covariance, n_init=tours, max_iter=max_iter, tol=tol,
                         reg_covar=REG_COVAR, random_state=seed).fit(D.Zf)
    order = np.argsort(-gm.weights_, kind='stable')
    return Mixture(gm.weights_[order], gm.means_[order], _full_covs(gm)[order], gm=gm, order=order, n_iter=gm.n_iter_, converged=gm.converged_)


def _spec(columns, freq, k_min, k_max, covariance, tours, outlier, standardize, seed, max_iter, tol):
    """The settings, checked: they key the cache of fits."""
    kmin = max(1, int(k_min or 3))
    kmax = max(kmin, int(k_max or kmin))
    kmax = min(kmax, kmin + MAX_FITS - 1)
    if covariance not in COVARIANCES:
        raise ValueError(f'the covariance structure is one of {", ".join(COVARIANCES)}')
    tours = int(10 if tours is None else tours)
    if not 1 <= tours <= 100:
        raise ValueError('Tours is a whole number from 1 to 100')
    max_iter = int(500 if max_iter is None else max_iter)
    if not 1 <= max_iter <= 10000:
        raise ValueError('Maximum Iterations is a whole number from 1 to 10000')
    tol = float(tol if tol is not None else 1e-6)
    if not tol > 0:
        raise ValueError('the convergence criterion is a positive number')
    seed = predictive.seed_of(seed)
    return {'columns': list(columns or []), 'freq': freq or None, 'k_min': kmin, 'k_max': kmax, 'covariance': covariance,
            'tours': tours, 'outlier': bool(outlier), 'standardize': bool(standardize), 'seed': 0 if seed is None else seed,
            'max_iter': max_iter, 'tol': tol}


def _fits(table, rows, spec):
    """(Data, {k: Mixture or error text}) for these settings, remembered."""
    def build():
        D = Data(table, spec['columns'], rows, spec['freq'], spec['standardize'])
        out = {}
        ks = list(range(spec['k_min'], spec['k_max'] + 1))
        for i, k in enumerate(ks):
            if D.n_rows < k + 1 or D.N < k + 1:
                out[k] = f'{D.n_rows} rows: too few for {k} clusters'
            else:
                try:
                    out[k] = _fit_k(D, k, spec['covariance'], spec['tours'], spec['seed'], spec['max_iter'], spec['tol'], spec['outlier'])
                except ValueError as e:
                    out[k] = str(e)
            if len(ks) > 1:
                print(f'smui:progress mixtures {i + 1} {len(ks)}', flush=True)
        return D, out
    return predictive.cached('mixtures', table, rows, spec, build, keep=24)


def _to_units(D, M):
    """A fit in the columns' own units."""
    s = D.s
    means = D.m + M.means * s
    covs = M.covs * np.outer(s, s)[None]
    sds = np.sqrt(np.diagonal(covs, axis1=1, axis2=2))
    with np.errstate(divide='ignore', invalid='ignore'):
        corrs = covs / (sds[:, :, None] * sds[:, None, :])
    return means, covs, sds, corrs


def _pca(D):
    """Principal components of the fitting data (the correlations when the
    columns are scaled, else the covariances), for the biplot."""
    c = D.Xf.mean(axis=0)
    sc = D.s if D.standardize else np.ones(D.p)
    Zp = (D.Xf - c) / sc
    C = np.cov(Zp, rowvar=False, ddof=1)
    evals, evecs = np.linalg.eigh(np.atleast_2d(C))
    o = np.argsort(evals)[::-1]
    evals, evecs = evals[o], evecs[:, o]
    for j in range(evecs.shape[1]):
        i = int(np.argmax(np.abs(evecs[:, j])))
        if evecs[i, j] < 0:
            evecs[:, j] = -evecs[:, j]
    return c, sc, evals, evecs


def _mat(a):
    a = np.asarray(a, float)
    return np.where(np.isfinite(a), a, np.nan).tolist()


def _fit_out(D, M, k, spec, pca):
    means, covs, sds, corrs = _to_units(D, M)
    ll = M.loglik(D.Zf) - D.N * float(np.log(D.s).sum())
    q = n_parameters(k, D.p, spec['covariance'], M.outlier)
    prob = M.proba(D.Z)
    labels = np.argmax(prob, axis=1)
    m = k + (1 if M.outlier else 0)
    out = {'k': k, **_criteria(ll, q, D.N), 'converged': M.converged, 'n_iter': M.n_iter,
           'weights': M.weights[:k].tolist(), 'outlier_weight': float(M.weights[k]) if M.outlier else None,
           'means': _mat(means), 'sds': _mat(sds), 'covs': [_mat(c) for c in covs], 'corrs': [_mat(c) for c in corrs],
           'labels': labels.tolist(), 'pmax': prob[np.arange(len(prob)), labels].tolist(),
           'counts': D.counts(labels, m).tolist()}
    if M.outlier:
        # the uniform cluster's density in the columns' units
        out['outlier_density'] = float(math.exp(M.log_box) / np.prod(D.s))
    if pca is not None:
        c, sc, evals, E = pca
        E2 = E[:, :2]
        mz = (means - c) / sc
        cz = covs / np.outer(sc, sc)[None]
        out['pc_means'] = _mat(mz @ E2)
        out['pc_covs'] = [_mat(E2.T @ cj @ E2) for cj in cz]
    return out


def _lit(v):
    """A value as a Python literal: 12.0 as 12, text quoted."""
    if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
        f = float(v)
        return str(int(f)) if f.is_integer() and abs(f) < 1e15 else repr(f)
    return J(str(v))


def _keep_lines(table, rows, where=None):
    """After the code's head: the By group's rows (its where lines) and, of
    those, the ones the report uses (excluded and filtered rows dropped)."""
    L = []
    n = data.TABLES[table]['n'] if table in data.TABLES else 0
    match = np.ones(n, dtype=bool)
    for w in where or []:
        v = data.raw(table, w['column'])
        num = data.meta(table, w['column']).get('dataType') == 'numeric'
        match &= (np.asarray(v, dtype=float) == float(w['value'])) if num else np.array([x == w['value'] for x in v], dtype=bool)
        shown = w['value'] if isinstance(w['value'], str) else _lit(w['value'])
        L.append(f'df = df[df[{J(w["column"])}] == {_lit(w["value"])}]   # only the rows where {w["column"]} is {shown}')
    if rows is not None and n:
        keep = np.zeros(n, dtype=bool)
        keep[np.asarray(rows, dtype=int)] = True
        drop = np.flatnonzero(match & ~keep).tolist()
        if drop and not where and keep.sum() <= n / 2:
            return [f'df = df.loc[{np.flatnonzero(keep).tolist()}]   # the rows of the report']
        if drop:
            L.append(f'df = df.drop(index={drop})   # the rows the report leaves out')
    return L


def _code_data(D, table_name, extra, where=None):
    """The lines that build X, Xf, the scale and Z, Zf as the report does."""
    L = [code_head(table_name, extra)]
    L += _keep_lines(D.table, D.rows_in, where)
    names = D.cols + ([D.freq] if D.freq else [])
    L.append(f'd = df[{J(names)}].dropna()   # the rows with every column')
    if D.freq:
        L.append(f'd = d[d[{J(D.freq)}] >= 1]   # a frequency below 1 leaves the row out')
        L.append(f'f = np.floor(d[{J(D.freq)}].to_numpy(float)).astype(int)   # Freq, in whole numbers')
    L.append(f'X = d[{J(D.cols)}].to_numpy(float)')
    L.append('Xf = np.repeat(X, f, axis=0)   # each row as many times as its frequency' if D.freq else 'Xf = X')
    if D.standardize:
        L.append('m, s = Xf.mean(axis=0), Xf.std(axis=0, ddof=1)   # Columns Scaled Individually')
    else:
        L.append('m, s = np.zeros(X.shape[1]), np.ones(X.shape[1])   # the columns as they are')
    L.append('Z, Zf = (X - m) / s, (Xf - m) / s')
    L.append('N, p = Zf.shape')
    return L


def _code_fit_lines(spec, k_expr, indent=''):
    """The lines that fit one number of clusters into `fit` (weights, means,
    covariances on the fitting scale) and `ll` (the log likelihood)."""
    cov = spec['covariance']
    if spec['outlier']:
        return [f'{indent}fit = outlier_em(Zf, {k_expr}, {J(cov)}, {spec["tours"]}, {spec["seed"]}, {spec["max_iter"]}, {spec["tol"]!r})',
                f'{indent}ll = logsumexp(mixture_log_parts(Zf, fit["weights"], fit["means"], fit["covariances"], fit["log_box"]), axis=1).sum()']
    return [f'{indent}gm = GaussianMixture(n_components={k_expr}, covariance_type={J(cov)}, n_init={spec["tours"]}, max_iter={spec["max_iter"]}, tol={spec["tol"]!r}, reg_covar={REG_COVAR!r}, random_state={spec["seed"]}).fit(Zf)',
            f'{indent}ll = gm.score(Zf) * N']


def _q_expr(cov, outlier):
    e = {'full': 'k * p * (p + 1) // 2', 'diag': 'k * p', 'tied': 'p * (p + 1) // 2', 'spherical': 'k'}[cov]
    return f'{e} + k * p + k - 1' + (' + 1' if outlier else '')


def _code_extra(spec):
    if spec['outlier']:
        return ['from scipy.special import logsumexp']
    return ['from sklearn.mixture import GaussianMixture']


def _code_functions(spec):
    if not spec['outlier']:
        return []
    try:
        return ['', inspect.getsource(mixture_log_parts).rstrip(), '', '', inspect.getsource(outlier_em).rstrip(), '']
    except (OSError, TypeError):
        return ['# (the source of outlier_em is in resources/py/smui/mixtures.py)']


def _code_comparison(D, spec, table_name, where=None):
    L = _code_data(D, table_name, _code_extra(spec), where) + _code_functions(spec)
    L.append(f'for k in range({spec["k_min"]}, {spec["k_max"] + 1}):')
    L += _code_fit_lines(spec, 'k', '    ')
    L.append('    ll -= N * np.log(s).sum()   # the log likelihood in the columns\' own units')
    L.append(f'    q = {_q_expr(spec["covariance"], spec["outlier"])}   # covariances, means and proportions')
    L.append('    aicc = -2 * ll + 2 * q + 2 * q * (q + 1) / (N - q - 1)')
    L.append('    bic = -2 * ll + q * np.log(N)')
    L.append('    print("fit", k, -2 * ll, q, aicc, bic)')
    return '\n'.join(L)


def _code_fitted(D, spec, k, table_name, where=None, extra=()):
    """The lines up to one fit's proportions w, means mu and covariances cov
    on the fitting scale, each row's probabilities and its cluster."""
    L = _code_data(D, table_name, _code_extra(spec) + list(extra), where) + _code_functions(spec)
    L += _code_fit_lines(spec, str(k))
    if spec['outlier']:
        L.append(f'w, mu, cov = fit["weights"], fit["means"], fit["covariances"]')
        L.append(f'order = np.argsort(-w[:{k}], kind="stable")   # clusters numbered by their proportion, the outlier cluster last')
        L.append(f'w, mu, cov = np.append(w[:{k}][order], w[{k}]), mu[order], cov[order]')
        L.append('lp = mixture_log_parts(Z, w, mu, cov, fit["log_box"])')
        L.append('prob = np.exp(lp - logsumexp(lp, axis=1)[:, None])   # each row\'s probability of each cluster')
    else:
        L.append('order = np.argsort(-gm.weights_, kind="stable")   # clusters numbered by their proportion')
        L.append('w, mu = gm.weights_[order], gm.means_[order]')
        cov = spec['covariance']
        if cov == 'full':
            L.append('cov = gm.covariances_[order]')
        elif cov == 'tied':
            L.append(f'cov = np.repeat(gm.covariances_[None], {k}, axis=0)')
        elif cov == 'diag':
            L.append('cov = np.array([np.diag(v) for v in gm.covariances_[order]])')
        else:
            L.append('cov = np.array([v * np.eye(p) for v in gm.covariances_[order]])')
        L.append('prob = gm.predict_proba(Z)[:, order]   # each row\'s probability of each cluster')
    L.append('cluster = prob.argmax(axis=1)   # the most likely cluster' + (f' ({k}: the outlier cluster)' if spec['outlier'] else ''))
    return L


def _code_detail(D, spec, k, table_name, where=None):
    L = _code_fitted(D, spec, k, table_name, where)
    L.append(f'count = np.bincount(cluster, weights={"f" if D.freq else "None"}, minlength=prob.shape[1])')
    L.append('means = m + mu * s   # in the columns\' own units')
    L.append('sds = np.sqrt(np.diagonal(cov, axis1=1, axis2=2)) * s')
    L.append('print("proportion", *w)')
    L.append('print("count", *count)')
    L.append(f'for j in range({k}):')
    L.append('    print("mean", j + 1, *means[j])')
    L.append('    print("sd", j + 1, *sds[j])')
    return '\n'.join(L)


# ---- the graphs as matplotlib code -------------------------------------------------
# The page draws the scatterplot matrix, the mixture density and the biplot
# with its own choices (the columns shown, the ellipses' coverage, the bins,
# the size): their code is the fit's own lines (fit_head: the fit, each row's
# cluster, the means and covariances in the columns' units), the principal
# components' (pca_lines) for the biplot, and the page's drawing. The Cluster
# Criteria graph's code is whole (criteria_code).
BASE, RED = '#2f6690', '#b0413e'


def _code_plot_head(D, spec, k, table_name, where=None):
    """The fit's lines for its graphs: the rows, the fit, and in the columns'
    own units the means and covariances (and the outlier cluster's density)."""
    L = _code_fitted(D, spec, k, table_name, where, ['import matplotlib.pyplot as plt'])
    L.append('means = m + mu * s   # the clusters\' means in the columns\' own units')
    L.append('covs = cov * np.outer(s, s)   # and their covariances')
    if spec['outlier']:
        L.append('box_density = np.exp(fit["log_box"]) / np.prod(s)   # the outlier cluster: uniform over the box that holds the rows')
    return '\n'.join(L)


PCA_LINES = [
    'c = Xf.mean(axis=0)   # the principal components of the columns as fitted (scaled: of their correlations)',
    'evals, evecs = np.linalg.eigh(np.atleast_2d(np.cov((Xf - c) / s, rowvar=False, ddof=1)))',
    'o = np.argsort(evals)[::-1]',
    'evals, evecs = evals[o], evecs[:, o]',
    'for j in range(evecs.shape[1]):   # each component signed so that its largest loading is positive',
    '    if evecs[np.argmax(np.abs(evecs[:, j])), j] < 0:',
    '        evecs[:, j] = -evecs[:, j]',
    'E2 = evecs[:, :2]',
    'scores = ((X - c) / s) @ E2   # the rows on the first two components',
    'pc_means = ((means - c) / s) @ E2   # each cluster\'s normal distribution carried onto them',
    'pc_covs = np.array([E2.T @ (cv / np.outer(s, s)) @ E2 for cv in covs])']


def _code_criteria(D, spec, ks, table_name, where=None):
    """The Cluster Criteria graph: BIC and AICc of each number of clusters."""
    L = _code_data(D, table_name, _code_extra(spec) + ['import matplotlib.pyplot as plt'], where) + _code_functions(spec)
    L += [f'ks = {list(ks)}   # the numbers of clusters fitted', 'bic, aicc = [], []', 'for k in ks:']
    L += _code_fit_lines(spec, 'k', '    ')
    L += ['    ll -= N * np.log(s).sum()   # the log likelihood in the columns\' own units',
          f'    q = {_q_expr(spec["covariance"], spec["outlier"])}   # covariances, means and proportions',
          '    aicc.append(-2 * ll + 2 * q + 2 * q * (q + 1) / (N - q - 1) if N - q - 1 > 0 else np.inf)',
          '    bic.append(-2 * ll + q * np.log(N))',
          'fig, ax = plt.subplots(figsize=(4.6, 2.5), layout="constrained")',
          f'ax.plot(ks, bic, color="{BASE}", linewidth=1.15, marker="o", markersize=4.3, label="BIC")',
          f'ax.plot(ks, aicc, color="{RED}", linewidth=1, linestyle=":", marker="s", markersize=3.6, label="AICc")',
          'ax.set_xticks(ks)', 'ax.set_xlabel("NCluster")', 'ax.set_ylabel("Criterion")',
          'ax.legend(frameon=False, fontsize=7.5)', 'ax.set_title("Cluster criteria")', 'plt.show()']
    return '\n'.join(L)


# ---------------------------------------------------------------------------
# the entry points
# ---------------------------------------------------------------------------

@api('mixtures.fit', packages=SK)
def fit(table, columns, rows=None, freq=None, k_min=3, k_max=None, covariance='full', tours=10, outlier=False,
        standardize=True, seed=None, max_iter=500, tol=1e-6, choose='bic', where=None, table_name='data'):
    """Normal mixtures for each number of clusters from k_min to k_max: the
    Cluster Comparison, and for every fit its proportions, means, standard
    deviations, correlations and the most likely cluster of each row; the
    code of each (and the lines its graphs' code starts with: fit_head,
    pca_lines; and the whole criteria_code)."""
    try:
        spec = _spec(columns, freq, k_min, k_max, covariance, tours, outlier, standardize, seed, max_iter, tol)
        D, fits = _fits(table, rows, spec)
    except ValueError as e:
        return {'error': str(e)}
    pca = _pca(D) if D.p > 2 else None
    out_fits = []
    for k, M in fits.items():
        if isinstance(M, str):
            out_fits.append({'k': k, 'error': M})
        else:
            f = _fit_out(D, M, k, spec, pca)
            f['code'] = _code_detail(D, spec, k, table_name, where)
            f['fit_head'] = _dated(_code_plot_head(D, spec, k, table_name, where), table)
            out_fits.append(f)
    key = 'aicc' if choose == 'aicc' else 'bic'
    ok = [f for f in out_fits if 'error' not in f and f[key] is not None and math.isfinite(f[key])]
    best = min(ok, key=lambda f: f[key])['k'] if ok else None
    out = {'names': D.cols, 'n': D.N, 'n_rows': D.n_rows, 'n_left': D.n_left, 'rows': D.index.tolist(), 'notes': D.notes,
           'standardize': D.standardize, 'center': D.m.tolist(), 'scale': D.s.tolist(), 'fits': out_fits, 'best': best,
           'choose': key, 'seed': spec['seed'], 'tours': spec['tours'], 'covariance': spec['covariance'], 'outlier': spec['outlier'],
           'max_iter': spec['max_iter'], 'tol': spec['tol'], 'p': D.p,
           'box': {'lo': D.X.min(axis=0).tolist(), 'hi': D.X.max(axis=0).tolist()} if spec['outlier'] else None,
           'code': _code_comparison(D, spec, table_name, where)}
    good = [f['k'] for f in out_fits if 'error' not in f]
    if len(good) >= 3:
        out['criteria_code'] = _code_criteria(D, spec, good, table_name, where)
    if pca is not None:
        c, sc, evals, E = pca
        out['pca'] = {'eigenvalues': evals.tolist(), 'vectors': _mat(E[:, :2]), 'scores': _mat(((D.X - c) / sc) @ E[:, :2])}
        out['pca_lines'] = '\n'.join(PCA_LINES)
    return out


@api('mixtures.save', packages=SK)
def save(table, columns, k, rows=None, freq=None, k_min=3, k_max=None, covariance='full', tours=10, outlier=False,
         standardize=True, seed=None, max_iter=500, tol=1e-6):
    """Save Mixture Probabilities and Save Clusters: each cluster's
    probability and the most likely cluster of every row of the report."""
    spec = _spec(columns, freq, k_min, k_max, covariance, tours, outlier, standardize, seed, max_iter, tol)
    D, fits = _fits(table, rows, spec)
    M = fits.get(int(k))
    if M is None:
        raise ValueError(f'no fit with {k} clusters in this report')
    if isinstance(M, str):
        raise ValueError(M)
    prob = M.proba(D.Z)
    names = [f'Prob[Cluster {j + 1}]' for j in range(M.k)] + (['Prob[Outlier]'] if M.outlier else [])
    return {'rows': D.index.tolist(), 'prob': prob.tolist(), 'names': names, 'cluster': (np.argmax(prob, axis=1) + 1).tolist(),
            'k': M.k, 'outlier': M.outlier}


def _profile_build(table, rows=None, columns=(), k=3, freq=None, k_min=3, k_max=None, covariance='full', tours=10, outlier=False,
                   standardize=True, seed=None, max_iter=500, tol=1e-6, choose=None):
    """The Prediction Profiler's view of one fit: each cluster's probability
    as the columns vary."""
    spec = _spec(columns, freq, k_min, k_max, covariance, tours, outlier, standardize, seed, max_iter, tol)
    D, fits = _fits(table, rows, spec)
    M = fits.get(int(k))
    if M is None or isinstance(M, str):
        raise ValueError(M if isinstance(M, str) else f'no fit with {k} clusters in this report')
    factors = [{'name': c, 'type': 'continuous', 'min': float(D.X[:, j].min()), 'max': float(D.X[:, j].max()),
                'mean': float(D.Xf[:, j].mean())} for j, c in enumerate(D.cols)]

    def run(settings):
        X = np.array([[float(s[c]) for c in D.cols] for s in settings])
        pr = M.proba((X - D.m) / D.s)
        names = [f'Prob[Cluster {j + 1}]' for j in range(M.k)] + (['Prob[Outlier]'] if M.outlier else [])
        return [{'name': nm, 'pred': pr[:, j], 'lower': None, 'upper': None, 'bounded': True} for j, nm in enumerate(names)]
    return profile.Predictor(factors, run, data={c: D.Xf[:, j] for j, c in enumerate(D.cols)})


profile.expose('mixtures', _profile_build, packages=SK)
