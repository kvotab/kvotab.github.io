"""Multivariate Methods, Clustering and Screening: the backend.

Analyze > Multivariate Methods
  Multivariate          correlations (row-wise or pairwise), their tests and
                        Fisher-z intervals, inverse and partial correlations,
                        covariances, simple statistics, Spearman, Kendall and
                        Hoeffding, Mahalanobis, jackknife and T² distances,
                        Cronbach's alpha; beyond JMP intraclass correlations
                        (Shrout and Fleiss, McGraw and Wong) and Kendall's W
  Principal Components  statsmodels PCA on correlations, covariances or the
                        unscaled data; Bartlett's test of equal eigenvalues;
                        rotations of the components
  Factor Analysis       statsmodels Factor (principal axis, maximum
                        likelihood) with the rotations of factor_rotation
  Discriminant          linear, quadratic and regularized discriminant
                        analysis, canonical analysis, statsmodels MANOVA
  Multiple Correspondence Analysis   the SVD of the indicator matrix
  Multidimensional Scaling           classical (Torgerson) scaling
Analyze > Clustering
  Hierarchical Cluster  scipy.cluster.hierarchy, with JMP's distances
  K Means Cluster       seeded k-means++ with restarts, the cubic clustering
                        criterion of Sarle (1983)
Analyze > Screening
  Response Screening    every Y against every X, Benjamini-Hochberg FDR
  Explore Outliers      quantile range, robust fit (Huber, Cauchy, quartile),
                        robust Mahalanobis (FAST-MCD), k nearest neighbours

Results for rows carry `rows`, the page's row numbers, so the page can link
and save them. Every result has its `code`.
"""
import json
import math
import warnings

import numpy as np
import pandas as pd
from scipy import linalg as sla
from scipy import stats

from . import data
from .registry import api
from .util import code_head

J = json.dumps


# ---- shared helpers ------------------------------------------------------------

def _frame(table, columns, rows=None, weight=None, freq=None, dropna=True):
    """The named columns as floats (index = the page's row numbers), with
    case weights (weight x freq) and frequencies. Rows with a missing, zero
    or negative weight or frequency are dropped; with dropna, also rows with
    a missing value in any of the columns."""
    names = [c for c in dict.fromkeys(columns) if c]
    extra = [c for c in (weight, freq) if c and c not in names]
    df = data.frame(table, names + extra, rows, dropna=False, as_category=False)
    for c in names + extra:
        if df[c].dtype == object:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    w = np.ones(len(df))
    f = np.ones(len(df))
    if weight:
        w = w * df[weight].to_numpy(float)
    if freq:
        f = df[freq].to_numpy(float)
        w = w * f
    ok = np.isfinite(w) & (w > 0)
    if dropna and names:
        ok &= df[names].notna().all(axis=1).to_numpy()
    out = df.loc[ok, names].astype(float)
    return out, w[ok], f[ok]


def _nobs(f, freq):
    """The number of observations: the sum of the frequencies, or rows."""
    return float(np.sum(f)) if freq else float(len(f))


def _wmean_cov(X, w, ddof=1):
    sw = float(np.sum(w))
    m = (w[:, None] * X).sum(0) / sw
    C = X - m
    cov = (w[:, None] * C).T @ C / (sw - ddof)
    return m, cov


def _cov_to_corr(cov):
    d = np.sqrt(np.diag(cov))
    with np.errstate(divide='ignore', invalid='ignore'):
        r = cov / np.outer(d, d)
    np.fill_diagonal(r, 1.0)
    return r


def _corr_tests(r, n, alpha=0.05):
    """p-values (t with n-2 df) and Fisher-z confidence limits of
    correlations r estimated from n observations."""
    r = np.asarray(r, float)
    n = np.broadcast_to(np.asarray(n, float), r.shape)
    with np.errstate(divide='ignore', invalid='ignore'):
        df = n - 2
        t = r * np.sqrt(df / (1 - r * r))
        p = 2 * stats.t.sf(np.abs(t), df)
        p = np.where(np.abs(r) >= 1, 0.0, p)
        p = np.where(df > 0, p, np.nan)
        z = np.arctanh(np.clip(r, -1 + 1e-15, 1 - 1e-15))
        zc = stats.norm.ppf(1 - alpha / 2)
        se = 1 / np.sqrt(n - 3)
        lo = np.where(n > 3, np.tanh(z - zc * se), np.nan)
        hi = np.where(n > 3, np.tanh(z + zc * se), np.nan)
    return p, lo, hi


def _mat(a):
    return [[None if not np.isfinite(v) else float(v) for v in row] for row in np.asarray(a, float)]


def _sign_fix(V):
    """Eigenvectors with the largest-magnitude entry of each positive (the
    sign of an eigenvector is arbitrary; this makes it reproducible)."""
    V = np.array(V, float)
    for j in range(V.shape[1]):
        k = int(np.argmax(np.abs(V[:, j])))
        if V[k, j] < 0:
            V[:, j] = -V[:, j]
    return V


def _q(name):
    """A column name in a formula."""
    return name if name.isidentifier() else f'Q({J(name)})'


def _cols_expr(cols):
    return '[' + ', '.join(J(c) for c in cols) + ']'


# ---- Multivariate: correlations --------------------------------------------------

def _simple(df, w, f, freq, cols):
    out = []
    for c in cols:
        x = df[c].to_numpy(float) if c in df else np.array([])
        ok = np.isfinite(x)
        x, ww, ff = x[ok], w[ok], f[ok]
        n = _nobs(ff, freq)
        if len(x) == 0:
            out.append({'column': c, 'n': 0, 'mean': None, 'sd': None, 'sum': None, 'min': None, 'max': None})
            continue
        sw = float(ww.sum())
        m = float((ww * x).sum() / sw)
        sd = float(math.sqrt((ww * (x - m) ** 2).sum() / (sw - 1))) if sw > 1 else None
        out.append({'column': c, 'n': n, 'mean': m, 'sd': sd, 'sum': float((ww * x).sum()), 'min': float(x.min()), 'max': float(x.max())})
    return out


def _pair_stats(x, y, w):
    sw = float(w.sum())
    mx, my = (w * x).sum() / sw, (w * y).sum() / sw
    dx, dy = x - mx, y - my
    sxy, sxx, syy = (w * dx * dy).sum(), (w * dx * dx).sum(), (w * dy * dy).sum()
    r = sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else float('nan')
    cov = sxy / (sw - 1) if sw > 1 else float('nan')
    return r, cov


@api('multivariate.fit')
def mv_fit(table, columns, rows=None, weight=None, freq=None, method='rowwise', alpha=0.05, table_name='data'):
    """Correlations, covariances, inverse and partial correlations, their
    tests, and the simple statistics of the Multivariate platform."""
    cols = list(columns)
    p = len(cols)
    full, wf, ff = _frame(table, cols, rows, weight, freq, dropna=False)
    X = full.to_numpy(float)
    complete = np.isfinite(X).all(axis=1) if p else np.zeros(0, bool)
    Xc, wc, fc = X[complete], wf[complete], ff[complete]
    n_rows = int(complete.sum())
    n_rw = _nobs(fc, freq)
    pairwise = method == 'pairwise'
    if p < 2:
        return {'error': 'Multivariate needs at least two columns'}
    # pairwise quantities: every pair on its own complete rows
    cnt = np.zeros((p, p))
    rp = np.eye(p)
    cvp = np.zeros((p, p))
    fin = np.isfinite(X)
    for i in range(p):
        oki = fin[:, i]
        x = X[oki, i]
        cnt[i, i] = _nobs(ff[oki], freq)
        if len(x) > 1:
            _, cvp[i, i] = _pair_stats(x, x, wf[oki])
        else:
            cvp[i, i] = np.nan
        for j in range(i + 1, p):
            ok = oki & fin[:, j]
            cnt[i, j] = cnt[j, i] = _nobs(ff[ok], freq)
            if ok.sum() > 1:
                r, cv = _pair_stats(X[ok, i], X[ok, j], wf[ok])
            else:
                r, cv = float('nan'), float('nan')
            rp[i, j] = rp[j, i] = r
            cvp[i, j] = cvp[j, i] = cv
    if pairwise:
        R, S, N = rp, cvp, cnt
    else:
        if n_rows < 2:
            return {'error': 'fewer than two rows without missing values; try the pairwise method'}
        _, S = _wmean_cov(Xc, wc)
        R = _cov_to_corr(S)
        N = np.full((p, p), n_rw)
    P, LO, HI = _corr_tests(R, N, alpha)
    np.fill_diagonal(P, np.nan)
    out = {'names': cols, 'method': 'Pairwise' if pairwise else 'Row-wise', 'n': n_rw, 'n_rows': n_rows,
           'n_missing_rows': int(len(X) - n_rows), 'alpha': alpha,
           'corr': _mat(R), 'count': _mat(N), 'p': _mat(P), 'lower': _mat(LO), 'upper': _mat(HI), 'cov': _mat(S)}
    # inverse and partial correlations (of the matrix in use)
    try:
        if not np.all(np.isfinite(R)):
            raise np.linalg.LinAlgError('missing correlations')
        if np.linalg.matrix_rank(R) < p:
            raise np.linalg.LinAlgError('singular')
        Ri = np.linalg.inv(R)
        d = np.sqrt(np.diag(Ri))
        Pc = -Ri / np.outer(d, d)
        np.fill_diagonal(Pc, 1.0)
        # a partial correlation given the other p-2 variables: t with n-p df
        nn = float(np.min(N)) if pairwise else n_rw
        with np.errstate(divide='ignore', invalid='ignore'):
            dfp = nn - p
            tp = Pc * np.sqrt(dfp / (1 - Pc * Pc))
            Pp = 2 * stats.t.sf(np.abs(tp), dfp) if dfp > 0 else np.full((p, p), np.nan)
        np.fill_diagonal(Pp, np.nan)
        out.update({'inv': _mat(Ri), 'partial': _mat(Pc), 'partial_p': _mat(Pp), 'partial_df': dfp})
    except np.linalg.LinAlgError:
        out.update({'inv': None, 'partial': None, 'partial_p': None,
                    'singular': 'The correlation matrix is singular (a column is a linear combination of others, or there are too few rows): no inverse or partial correlations.'})
    out['uni'] = _simple(full, wf, ff, freq, cols)
    out['multi'] = _simple(full[complete], wc, fc, freq, cols)
    # the Pairwise Correlations report: always pairwise
    pp, plo, phi = _corr_tests(rp, cnt, alpha)
    pairs = []
    for i in range(p):
        for j in range(i + 1, p):
            pairs.append({'var': cols[j], 'by': cols[i], 'i': j, 'j': i, 'r': rp[i, j], 'count': cnt[i, j],
                          'lower': plo[i, j], 'upper': phi[i, j], 'p': pp[i, j]})
    out['pairs'] = pairs
    wexpr = _weight_code(weight, freq)
    c = [code_head(table_name, ['from scipy import stats']), f'X = df[{_cols_expr(cols)}]']
    if wexpr:
        c += ['from statsmodels.stats.weightstats import DescrStatsW',
              f'w = {wexpr}', 'ok = X.notna().all(axis=1) & w.gt(0)',
              'd = DescrStatsW(X[ok], weights=w[ok], ddof=1)',
              'print(d.corrcoef)   # correlations', 'print(d.cov)        # covariances']
    elif pairwise:
        c += ['print(X.corr())   # pandas: pairwise complete rows', 'print(X.cov())']
    else:
        c += ['Xc = X.dropna()', 'R = Xc.corr(); print(R)', 'print(Xc.cov())',
              'Ri = np.linalg.inv(R)   # inverse correlations; the diagonal is the VIF',
              'd = np.sqrt(np.diag(Ri)); print(-Ri / np.outer(d, d))   # partial correlations (off the diagonal)']
    c += ['xy = X.iloc[:, [0, 1]].dropna(); print(stats.pearsonr(xy.iloc[:, 0], xy.iloc[:, 1]))   # r and p of one pair, on its complete rows' if not wexpr else '']
    out['code'] = '\n'.join(x for x in c if x)
    return out


def _weight_code(weight, freq):
    parts = [f'df[{J(v)}]' for v in (weight, freq) if v]
    return ' * '.join(parts)


# ---- Multivariate: nonparametric measures --------------------------------------------

_BKR_CACHE = {}


def _bkr_lambdas(J_=40):
    j = np.arange(1, J_ + 1, dtype=float)
    lam = 1.0 / (2.0 * np.outer(j * j, j * j)).ravel()
    total = math.pi ** 4 / 72.0                   # sum over all j, k of 1/(2 j^2 k^2)
    total2 = (math.pi ** 4 / 90.0) ** 2 / 4.0     # sum of squares
    return lam, total - lam.sum(), total2 - (lam * lam).sum()


def bkr_sf(x):
    """P(T > x) for T = sum over j, k >= 1 of chi2_1 / (2 j^2 k^2): the limit
    distribution of Blum, Kiefer and Rosenblatt (1961), which SAS and JMP
    use for Hoeffding's D through T = (n-1) pi^4/60 D + pi^4/72. Imhof's
    (1961) inversion over 1600 terms; the rest of the sum enters through its
    first two cumulants."""
    from scipy import integrate
    if not np.isfinite(x):
        return float('nan')
    if x <= 0:
        return 1.0
    key = round(float(x), 10)
    if key in _BKR_CACHE:
        return _BKR_CACHE[key]
    lam, rest1, rest2 = _bkr_lambdas()

    def f(u):
        if u <= 0:
            return 0.5 * (lam.sum() + rest1 - x)   # the limit of sin(theta)/u at 0
        th = 0.5 * np.arctan(lam * u).sum() + 0.5 * rest1 * u - 0.5 * x * u
        lrho = 0.25 * np.log1p((lam * u) ** 2).sum() + 0.25 * rest2 * u * u
        if lrho > 700:
            return 0.0
        return math.sin(th) / (u * math.exp(lrho))
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        val, _ = integrate.quad(f, 0, np.inf, limit=400)
    pv = float(min(1.0, max(0.0, 0.5 + val / math.pi)))
    _BKR_CACHE[key] = pv
    return pv


def hoeffding_d(x, y):
    """Hoeffding's D (1948), scaled by 30 as SAS and JMP report it, with
    average ranks for ties and the bivariate ranks Q of Hoeffding's formula
    (a point tied on one coordinate and below on the other counts 1/2, tied
    on both 1/4). Returns (D, p) with p from the Blum-Kiefer-Rosenblatt
    limit."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    n = len(x)
    if n < 5:
        return float('nan'), float('nan')
    R = stats.rankdata(x)
    S = stats.rankdata(y)
    Q = np.empty(n)
    step = max(1, 1_000_000 // max(n, 1))   # blocks of about a million pairs: bounded memory in Pyodide
    for a in range(0, n, step):
        b = min(n, a + step)
        dx = x[a:b, None] - x[None, :]
        dy = y[a:b, None] - y[None, :]
        cx = np.where(dx > 0, 1.0, np.where(dx == 0, 0.5, 0.0))
        cy = np.where(dy > 0, 1.0, np.where(dy == 0, 0.5, 0.0))
        Q[a:b] = 1.0 + (cx * cy).sum(axis=1) - 0.25
    D1 = np.sum((Q - 1) * (Q - 2))
    D2 = np.sum((R - 1) * (R - 2) * (S - 1) * (S - 2))
    D3 = np.sum((R - 2) * (S - 2) * (Q - 1))
    D = 30.0 * ((n - 2) * (n - 3) * D1 + D2 - 2 * (n - 2) * D3) / (n * (n - 1) * (n - 2) * (n - 3) * (n - 4))
    T = (n - 1) * math.pi ** 4 / 60.0 * D + math.pi ** 4 / 72.0
    return float(D), bkr_sf(T)


HOEFFDING_CODE = """def hoeffding(x, y):   # JMP's (and SAS's) Hoeffding's D
    n = len(x); R, S = stats.rankdata(x), stats.rankdata(y)
    cx = np.where(x[:, None] > x, 1.0, np.where(x[:, None] == x, 0.5, 0.0))
    cy = np.where(y[:, None] > y, 1.0, np.where(y[:, None] == y, 0.5, 0.0))
    Q = 1 + (cx * cy).sum(1) - 0.25
    D1, D2, D3 = ((Q - 1) * (Q - 2)).sum(), ((R - 1) * (R - 2) * (S - 1) * (S - 2)).sum(), ((R - 2) * (S - 2) * (Q - 1)).sum()
    return 30 * ((n - 2) * (n - 3) * D1 + D2 - 2 * (n - 2) * D3) / (n * (n - 1) * (n - 2) * (n - 3) * (n - 4))
D = hoeffding(x, y); T = (len(x) - 1) * np.pi**4 / 60 * D + np.pi**4 / 72
print(D, T)   # p-value: P(sum over j,k of chi2_1/(2 j^2 k^2) > T), the Blum-Kiefer-Rosenblatt law"""


@api('multivariate.nonparametric')
def mv_nonparametric(table, columns, rows=None, measure='spearman', weight=None, freq=None, table_name='data'):
    """Spearman's rho, Kendall's tau-b or Hoeffding's D for every pair, each
    on its own complete rows. As in JMP, a weight only excludes the rows
    whose weight is missing or not positive."""
    cols = list(columns)
    full, _, _ = _frame(table, cols, rows, weight, freq, dropna=False)
    X = full.to_numpy(float)
    fin = np.isfinite(X)
    pairs = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            ok = fin[:, i] & fin[:, j]
            x, y = X[ok, i], X[ok, j]
            n = int(ok.sum())
            v, pv = float('nan'), float('nan')
            if n >= 3 and np.ptp(x) > 0 and np.ptp(y) > 0:
                if measure == 'kendall':
                    res = stats.kendalltau(x, y, variant='b', method='asymptotic')
                    v, pv = float(res.statistic), float(res.pvalue)
                elif measure == 'hoeffding':
                    v, pv = hoeffding_d(x, y)
                else:
                    res = stats.spearmanr(x, y)
                    v, pv = float(res.statistic), float(res.pvalue)
            pairs.append({'var': cols[j], 'by': cols[i], 'i': j, 'j': i, 'value': v, 'p': pv, 'count': n})
    fn = {'spearman': 'print(stats.spearmanr(x, y))', 'kendall': 'print(stats.kendalltau(x, y, variant="b", method="asymptotic"))',
          'hoeffding': HOEFFDING_CODE}[measure]
    code = '\n'.join([code_head(table_name, ['from scipy import stats']),
                      f'X = df[{_cols_expr(cols)}]',
                      'xy = X.iloc[:, [0, 1]].dropna(); x, y = xy.iloc[:, 0].to_numpy(), xy.iloc[:, 1].to_numpy()   # one pair, its complete rows',
                      fn])
    return {'measure': measure, 'pairs': pairs, 'code': code}


# ---- Multivariate: distance correlation -------------------------------------------------------

DCOR_MAX_N = 2000          # the distance matrices are n x n: a larger pair is subsampled
DCOR_PERM_WORK = 3e8       # permutations x n^2 over all pairs: about 5 s in Pyodide, 0.8 s a pair of 500 rows
DCOR_SEED = 20260926


def _dcor_b(n):
    """statsmodels' number of permutations for n observations."""
    return int(np.floor(200 + 5000 / n))


@api('multivariate.distance')
def mv_distance(table, columns, rows=None, weight=None, freq=None, method='auto', table_name='data'):
    """Distance correlation (Székely, Rizzo and Bakirov 2007) of every pair,
    each on its own complete rows: statsmodels' distance_statistics (dCor,
    dCov and the distance variances, V-statistics) and its
    distance_covariance_test, whose p-value comes from permutations of the
    rows for n ≤ 500 (statsmodels' rule; the permutations use a fixed seed)
    and from the asymptotic bound otherwise. Freq is counted by repeating
    rows; Weight only leaves out rows without a positive weight. A pair with
    more than 2000 rows is a seeded random subsample of 2000."""
    import warnings as _w
    from statsmodels.stats.dist_dependence_measures import distance_covariance_test, distance_statistics
    from statsmodels.tools.sm_exceptions import HypothesisTestWarning
    cols = list(columns)
    p = len(cols)
    if p < 2:
        return {'error': 'distance correlations need two or more columns'}
    full, _, ff = _frame(table, cols, rows, weight, freq, dropna=False)
    X = full.to_numpy(float)
    fin = np.isfinite(X)
    reps = None
    if freq:
        rr = np.rint(ff)
        if np.any(np.abs(ff - rr) > 1e-9):
            return {'error': 'Freq must hold whole numbers for the distance correlations (it is counted by repeating rows)'}
        reps = rr.astype(int)
    idx = [(i, j) for i in range(p) for j in range(i + 1, p)]
    sizes = {}
    for i, j in idx:
        ok = fin[:, i] & fin[:, j]
        sizes[(i, j)] = int(reps[ok].sum()) if reps is not None else int(ok.sum())
    # the permutation test's work over all pairs; beyond the budget the asymptotic test
    work = sum(_dcor_b(n) * n * n for n in (min(v, DCOR_MAX_N) for v in sizes.values()) if 4 <= n <= 500)
    asym = method == 'asym' or work > DCOR_PERM_WORK
    notes = []
    if method != 'asym' and work > DCOR_PERM_WORK:
        notes.append('The permutation tests of every pair would take too long here: the p-values are the asymptotic ones.')
    M = np.eye(p)
    pairs = []
    subsampled = False
    for i, j in idx:
        ok = fin[:, i] & fin[:, j]
        x, y = X[ok, i], X[ok, j]
        if reps is not None:
            x, y = np.repeat(x, reps[ok]), np.repeat(y, reps[ok])
        n = len(x)
        if n > DCOR_MAX_N:
            keep = np.sort(np.random.default_rng(DCOR_SEED).choice(n, DCOR_MAX_N, replace=False))
            x, y = x[keep], y[keep]
            subsampled = True
        row = {'var': cols[j], 'by': cols[i], 'i': j, 'j': i, 'count': n, 'used': len(x), 'dcor': None, 'dcov': None, 'dvar_x': None, 'dvar_y': None,
               'stat': None, 'z': None, 'p': None, 'method': '', 'B': None, 'r': None}
        if len(x) < 4 or np.ptp(x) == 0 or np.ptp(y) == 0:
            row['method'] = 'too few distinct values'
            M[i, j] = M[j, i] = np.nan
            pairs.append(row)
            continue
        st = distance_statistics(x, y)
        state = np.random.get_state()
        np.random.seed(DCOR_SEED)
        try:
            with _w.catch_warnings(record=True) as caught:
                _w.simplefilter('always')
                stat, pv, chosen = distance_covariance_test(x, y, method='asym' if asym else 'auto')
        finally:
            np.random.set_state(state)
        fell = [str(w.message) for w in caught if issubclass(w.category, HypothesisTestWarning)]
        for w in caught:   # to the report, as dispatch collects them
            _w.warn(str(w.message), w.category)
        m = len(x)
        row.update({'dcor': float(st.distance_correlation), 'dcov': float(st.distance_covariance), 'dvar_x': float(st.dvar_x), 'dvar_y': float(st.dvar_y),
                    'stat': float(st.test_statistic), 'z': float(math.sqrt(st.test_statistic / st.S)) if st.S > 0 else None, 'p': float(pv),
                    'r': float(np.corrcoef(x, y)[0, 1])})
        B = _dcor_b(m)
        if chosen == 'emp' and not fell:
            row.update({'method': f'permutation (B = {B})', 'B': B})
        elif chosen == 'emp':
            # statsmodels replaces a permutation p-value of 0 or 1 by the asymptotic one
            none = 'was 0' in fell[0]
            row.update({'method': f'asymptotic: {"no" if none else "every"} permutation of {B} {"reached" if none else "exceeded"} it', 'B': B,
                        'p_perm_below': 1.0 / B if none else None})
        else:
            row['method'] = 'asymptotic'
        M[i, j] = M[j, i] = row['dcor']
        pairs.append(row)
    if subsampled:
        notes.append(f'Pairs with more than {DCOR_MAX_N} rows use a random subsample of {DCOR_MAX_N} (fixed seed): the distance matrices are n × n.')
    if weight:
        notes.append('Weight is not used by the distance statistics; it only leaves out rows without a positive weight.')
    first = pairs[0] if pairs else None
    c = [code_head(table_name, ['from statsmodels.stats.dist_dependence_measures import distance_covariance_test, distance_statistics'])]
    if first:
        a, b = first['by'], first['var']
        keep = [a, b] + [v for v in (weight, freq) if v]
        c.append(f'xy = df[[{", ".join(J(v) for v in keep)}]].dropna()   # one pair on its complete rows; the same for each pair')
        if weight:
            c.append(f'xy = xy[xy[{J(weight)}] > 0]')
        if freq:
            c.append(f'xy = xy.loc[xy.index.repeat(xy[{J(freq)}].round().astype(int))]   # Freq: each row counted that many times')
        if first['count'] > DCOR_MAX_N:
            c.append(f'xy = xy.iloc[np.sort(np.random.default_rng({DCOR_SEED}).choice(len(xy), {DCOR_MAX_N}, replace=False))]   # the subsample')
        c.append(f'x, y = xy[{J(a)}].to_numpy(), xy[{J(b)}].to_numpy()')
        c.append('print(distance_statistics(x, y))   # dCor, dCov, the distance variances; test_statistic is n·dCov²')
        c.append(f'np.random.seed({DCOR_SEED}); print(distance_covariance_test(x, y, method={J("asym" if asym else "auto")}))   # statistic, p, method (permutations for n ≤ 500)')
    return {'names': cols, 'matrix': _mat(M), 'pairs': pairs, 'asym': asym, 'notes': notes, 'code': '\n'.join(c)}


# ---- Multivariate: outlier distances ------------------------------------------------------

def _mahal(Xc, S):
    Si = np.linalg.pinv(S)
    return np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', Xc, Si, Xc), 0))


@api('multivariate.outliers')
def mv_outliers(table, columns, rows=None, alpha=0.05, table_name='data'):
    """Mahalanobis, jackknife and T-squared distances of each row, with the
    upper control limits JMP draws (Mason and Young 2002, Penny 1996)."""
    cols = list(columns)
    df, _, _ = _frame(table, cols, rows)
    X = df.to_numpy(float)
    n, p = X.shape
    if n <= p + 1:
        return {'error': f'too few rows without missing values ({n}) for {p} columns'}
    m = X.mean(0)
    S = np.cov(X, rowvar=False, ddof=1).reshape(p, p)
    M = _mahal(X - m, S)
    M2 = M * M
    with np.errstate(divide='ignore', invalid='ignore'):
        den = 1 - n * M2 / (n - 1) ** 2
        J2 = (n - 2) * n * n / (n - 1) ** 3 * M2 / den
        Jd = np.sqrt(np.where(den > 0, J2, np.nan))
    b = stats.beta.ppf(1 - alpha, p / 2, (n - p - 1) / 2)
    ucl_t2 = (n - 1) ** 2 / n * b
    ucl_m = math.sqrt(ucl_t2)
    d = 1 - n * ucl_t2 / (n - 1) ** 2
    ucl_j = math.sqrt((n - 2) * n * n / (n - 1) ** 3 * ucl_t2 / d) if d > 0 else None
    code = '\n'.join([code_head(table_name, ['from scipy import stats']),
                      f'X = df[{_cols_expr(cols)}].dropna(); n, p = X.shape',
                      'S = np.cov(X, rowvar=False); e = (X - X.mean()).to_numpy()',
                      'M2 = np.einsum("ij,jk,ik->i", e, np.linalg.pinv(S), e)   # squared Mahalanobis distance = T²',
                      'J = np.sqrt((n - 2) * n**2 / (n - 1)**3 * M2 / (1 - n * M2 / (n - 1)**2))   # jackknife distance',
                      f'ucl_t2 = (n - 1)**2 / n * stats.beta.ppf({1 - alpha:g}, p / 2, (n - p - 1) / 2)',
                      'print(np.sqrt(M2)[:5], J[:5], ucl_t2)'])
    return {'rows': df.index.to_numpy(), 'mahal': M, 'jack': Jd, 't2': M2, 'n': n, 'p': p, 'alpha': alpha,
            'ucl_mahal': ucl_m, 'ucl_jack': ucl_j, 'ucl_t2': ucl_t2, 'code': code}


# ---- Multivariate: item reliability ----------------------------------------------------------

def _alpha(S):
    k = S.shape[0]
    if k < 2:
        return float('nan')
    v = np.trace(S) / k
    c = (S.sum() - np.trace(S)) / (k * (k - 1))
    return float(k * c / (v + (k - 1) * c))


@api('multivariate.reliability')
def mv_reliability(table, columns, rows=None, weight=None, freq=None, table_name='data'):
    """Cronbach's alpha, raw (k c/(v + (k-1) c), c the mean covariance, v the
    mean variance) and standardized (k r/(1 + (k-1) r)), for the whole set
    and with each item left out; and each item's correlation with the sum
    of the others."""
    cols = list(columns)
    df, w, _ = _frame(table, cols, rows, weight, freq)
    X = df.to_numpy(float)
    if len(X) < 3 or len(cols) < 2:
        return {'error': 'needs two or more columns and three or more rows without missing values'}
    _, S = _wmean_cov(X, w)
    R = _cov_to_corr(S)
    items = []
    for i, c in enumerate(cols):
        keep = [j for j in range(len(cols)) if j != i]
        Sk, Rk = S[np.ix_(keep, keep)], R[np.ix_(keep, keep)]
        rest = X[:, keep].sum(1)
        it, _ = _pair_stats(X[:, i], rest, w)
        items.append({'column': c, 'alpha': _alpha(Sk) if len(keep) > 1 else None,
                      'std_alpha': _alpha(Rk) if len(keep) > 1 else None, 'item_total': it})
    code = '\n'.join([code_head(table_name), f'X = df[{_cols_expr(cols)}].dropna(); k = X.shape[1]',
                      'S = X.cov().to_numpy(); v = np.trace(S) / k; c = (S.sum() - np.trace(S)) / (k * (k - 1))',
                      "print('alpha', k * c / (v + (k - 1) * c))",
                      "r = (X.corr().to_numpy().sum() - k) / (k * (k - 1)); print('standardized alpha', k * r / (1 + (k - 1) * r))"])
    return {'alpha': _alpha(S), 'std_alpha': _alpha(R), 'k': len(cols), 'n': len(X), 'items': items, 'code': code}


# ---- Multivariate: intraclass correlations and Kendall's W (Item Reliability) -------------------
# Not in JMP; the standard references. The Y columns are the raters (or
# items), the rows the targets (objects) they rate; only the rows rated by
# every rater count.

_ICC_FORMS = (
    # (name, Shrout and Fleiss's name, model, single rater?)
    ('ICC(1,1)', 'ICC(1,1)', 'One-way random, one rater', True),
    ('ICC(A,1)', 'ICC(2,1)', 'Two-way, absolute agreement, one rater', True),
    ('ICC(C,1)', 'ICC(3,1)', 'Two-way, consistency, one rater', True),
    ('ICC(1,k)', 'ICC(1,k)', 'One-way random, mean of k raters', False),
    ('ICC(A,k)', 'ICC(2,k)', 'Two-way, absolute agreement, mean of k raters', False),
    ('ICC(C,k)', 'ICC(3,k)', 'Two-way, consistency, mean of k raters', False),
)


def icc_forms(MSR, MSC, MSE, MSW, n, k, alpha=0.05):
    """The six intraclass correlations from the mean squares of the two-way
    ANOVA of n targets by k raters (MSR between targets, MSC between raters,
    MSE residual, MSW within targets), with their F tests of rho = 0 and
    1 - alpha confidence intervals: McGraw and Wong (1996), Tables 4, 7 and 8
    (Shrout and Fleiss 1979 for their cases 1, 2 and 3). The absolute-agreement
    intervals are McGraw and Wong's approximation (Satterthwaite's DF); the
    others are exact. Returns {name: (icc, F, df1, df2, lower, upper)}."""
    q = 1 - alpha / 2
    df_r, df_w, df_e = n - 1, n * (k - 1), (n - 1) * (k - 1)

    def ratio(a, b):
        return a / b if b > 0 else float('inf') if a > 0 else float('nan')
    out = {}
    # one-way: targets random, the raters of a target a sample (F = MSR/MSW)
    F1 = ratio(MSR, MSW)
    FL, FU = F1 / stats.f.ppf(q, df_r, df_w), F1 * stats.f.ppf(q, df_w, df_r)
    out['ICC(1,1)'] = ((MSR - MSW) / (MSR + (k - 1) * MSW), F1, df_r, df_w, (FL - 1) / (FL + k - 1), (FU - 1) / (FU + k - 1))
    out['ICC(1,k)'] = ((MSR - MSW) / MSR, F1, df_r, df_w, 1 - 1 / FL, 1 - 1 / FU)
    # two-way, consistency: the raters' means do not count (F = MSR/MSE)
    F3 = ratio(MSR, MSE)
    FL, FU = F3 / stats.f.ppf(q, df_r, df_e), F3 * stats.f.ppf(q, df_e, df_r)
    out['ICC(C,1)'] = ((MSR - MSE) / (MSR + (k - 1) * MSE), F3, df_r, df_e, (FL - 1) / (FL + k - 1), (FU - 1) / (FU + k - 1))
    out['ICC(C,k)'] = ((MSR - MSE) / MSR, F3, df_r, df_e, 1 - 1 / FL, 1 - 1 / FU)
    # two-way, absolute agreement: the raters' means count too; the test of rho = 0 is F = MSR/MSE
    r1 = (MSR - MSE) / (MSR + (k - 1) * MSE + k * (MSC - MSE) / n)
    rk = (MSR - MSE) / (MSR + (MSC - MSE) / n)
    lo1 = hi1 = lok = hik = float('nan')
    if r1 < 1:
        a = k * r1 / (n * (1 - r1))
        b = 1 + k * r1 * (n - 1) / (n * (1 - r1))
        den = (a * MSC) ** 2 / (k - 1) + (b * MSE) ** 2 / df_e
        v = (a * MSC + b * MSE) ** 2 / den if den > 0 else float('nan')
        if np.isfinite(v) and v > 0:
            Fs, Fs2 = stats.f.ppf(q, df_r, v), stats.f.ppf(q, v, df_r)
            lo1 = n * (MSR - Fs * MSE) / (Fs * (k * MSC + (k * n - k - n) * MSE) + n * MSR)
            hi1 = n * (Fs2 * MSR - MSE) / (k * MSC + (k * n - k - n) * MSE + n * Fs2 * MSR)
            lok = n * (MSR - Fs * MSE) / (Fs * (MSC - MSE) + n * MSR)
            hik = n * (Fs2 * MSR - MSE) / (MSC - MSE + n * Fs2 * MSR)
    out['ICC(A,1)'] = (r1, F3, df_r, df_e, lo1, hi1)
    out['ICC(A,k)'] = (rk, F3, df_r, df_e, lok, hik)
    return out


@api('multivariate.icc')
def mv_icc(table, columns, rows=None, weight=None, freq=None, alpha=0.05, table_name='data'):
    """Intraclass correlations of the ratings of the rows (targets) by the
    columns (raters): the two-way ANOVA without replication and the six forms
    of Shrout and Fleiss (1979) in McGraw and Wong's (1996) names, each with
    its F test and confidence interval. Weight and Freq count a row that many
    times (as for Cronbach's alpha)."""
    cols = list(columns)
    k = len(cols)
    full, _, _ = _frame(table, cols, rows, weight, freq, dropna=False)
    df, w, _ = _frame(table, cols, rows, weight, freq)
    X = df.to_numpy(float)
    N = float(np.sum(w))
    if k < 2 or len(X) < 2 or N < 2:
        return {'error': 'Intraclass correlations need two or more columns (the raters) and two or more rows rated by all of them'}
    left = int(len(full) - len(X))
    g = float(np.sum(w[:, None] * X) / (N * k))
    rmean = X.mean(axis=1)
    cmean = (w[:, None] * X).sum(axis=0) / N
    ssr = float(k * np.sum(w * (rmean - g) ** 2))
    ssc = float(N * np.sum((cmean - g) ** 2))
    sst = float(np.sum(w[:, None] * (X - g) ** 2))
    sse = max(sst - ssr - ssc, 0.0)
    df_r, df_c, df_e, df_w = N - 1, k - 1, (N - 1) * (k - 1), N * (k - 1)
    MSR, MSC, MSE, MSW = ssr / df_r, ssc / df_c, sse / df_e, (ssc + sse) / df_w
    if not (MSE > 0 and MSW > 0 and MSR > 0):
        return {'error': 'The ratings do not vary within the targets (or not at all): no intraclass correlations'}
    anova = [
        {'source': 'Between Targets', 'df': df_r, 'ss': ssr, 'ms': MSR, 'f': MSR / MSE, 'p': float(stats.f.sf(MSR / MSE, df_r, df_e))},
        {'source': 'Between Raters', 'df': df_c, 'ss': ssc, 'ms': MSC, 'f': MSC / MSE, 'p': float(stats.f.sf(MSC / MSE, df_c, df_e))},
        {'source': 'Residual', 'df': df_e, 'ss': sse, 'ms': MSE, 'f': None, 'p': None},
        {'source': 'Within Targets', 'df': df_w, 'ss': ssc + sse, 'ms': MSW, 'f': None, 'p': None},
        {'source': 'Total', 'df': N * k - 1, 'ss': sst, 'ms': None, 'f': None, 'p': None},
    ]
    forms = icc_forms(MSR, MSC, MSE, MSW, N, k, alpha)
    out_rows = []
    for name, sf, model, _one in _ICC_FORMS:
        v, F, d1, d2, lo, hi = forms[name]
        out_rows.append({'form': name, 'sf': sf, 'model': model, 'icc': v, 'f': F, 'df1': d1, 'df2': d2,
                         'p': float(stats.f.sf(F, d1, d2)) if np.isfinite(F) else None, 'lower': lo, 'upper': hi})
    wexpr = _weight_code(weight, freq)
    c = [code_head(table_name, ['from scipy import stats'])]
    c.append(f'X = df[{_cols_expr(cols)}]   # the raters are the columns, the targets the rows')
    if wexpr:
        c += [f'w = {wexpr}', 'ok = X.notna().all(axis=1) & w.gt(0); X, w = X[ok].to_numpy(), w[ok].to_numpy()   # every rater, a positive weight']
    else:
        c += ['X = X.dropna().to_numpy(); w = np.ones(len(X))   # the targets rated by every rater']
    c += ['n, k = w.sum(), X.shape[1]; g = (w[:, None] * X).sum() / (n * k)',
          'SSR = k * (w * (X.mean(1) - g) ** 2).sum(); SSC = n * (((w[:, None] * X).sum(0) / n - g) ** 2).sum()',
          'SSE = (w[:, None] * (X - g) ** 2).sum() - SSR - SSC',
          'MSR, MSC, MSE, MSW = SSR / (n - 1), SSC / (k - 1), SSE / ((n - 1) * (k - 1)), (SSC + SSE) / (n * (k - 1))',
          'icc = {"ICC(1,1)": (MSR - MSW) / (MSR + (k - 1) * MSW), "ICC(A,1)": (MSR - MSE) / (MSR + (k - 1) * MSE + k * (MSC - MSE) / n),',
          '       "ICC(C,1)": (MSR - MSE) / (MSR + (k - 1) * MSE), "ICC(1,k)": (MSR - MSW) / MSR,',
          '       "ICC(A,k)": (MSR - MSE) / (MSR + (MSC - MSE) / n), "ICC(C,k)": (MSR - MSE) / MSR}   # McGraw and Wong (1996)',
          'print(icc)',
          'dr, dw, de = n - 1, n * (k - 1), (n - 1) * (k - 1); F1, F3 = MSR / MSW, MSR / MSE   # the F tests of rho = 0',
          'print(stats.f.sf(F1, dr, dw), stats.f.sf(F3, dr, de))   # ICC(1, .); the two-way forms',
          f'q, Q = {1 - alpha / 2!r}, stats.f.ppf',
          'L1, U1, L3, U3 = F1 / Q(q, dr, dw), F1 * Q(q, dw, dr), F3 / Q(q, dr, de), F3 * Q(q, de, dr)',
          'r = icc["ICC(A,1)"]; a = k * r / (n * (1 - r)); b = 1 + k * r * (n - 1) / (n * (1 - r))',
          'v = (a * MSC + b * MSE) ** 2 / ((a * MSC) ** 2 / (k - 1) + (b * MSE) ** 2 / de); Fs, Ft = Q(q, dr, v), Q(q, v, dr)   # Satterthwaite',
          'ci = {"ICC(1,1)": ((L1 - 1) / (L1 + k - 1), (U1 - 1) / (U1 + k - 1)), "ICC(1,k)": (1 - 1 / L1, 1 - 1 / U1),',
          '      "ICC(C,1)": ((L3 - 1) / (L3 + k - 1), (U3 - 1) / (U3 + k - 1)), "ICC(C,k)": (1 - 1 / L3, 1 - 1 / U3),',
          '      "ICC(A,1)": (n * (MSR - Fs * MSE) / (Fs * (k * MSC + (k * n - k - n) * MSE) + n * MSR), n * (Ft * MSR - MSE) / (k * MSC + (k * n - k - n) * MSE + n * Ft * MSR)),',
          '      "ICC(A,k)": (n * (MSR - Fs * MSE) / (Fs * (MSC - MSE) + n * MSR), n * (Ft * MSR - MSE) / (MSC - MSE + n * Ft * MSR))}',
          'print(ci)   # McGraw and Wong (1996), Table 7: exact, but approximate for absolute agreement']
    notes = []
    if left:
        why = ' (or without a positive Weight or Freq)' if weight or freq else ''
        notes.append(f'{left} row{"" if left == 1 else "s"} without a rating from every rater{why} left out.')
    if weight or freq:
        notes.append('Weight and Freq count each row that many times.')
    return {'n': N, 'n_rows': int(len(X)), 'k': k, 'left_out': left, 'alpha': alpha, 'anova': anova, 'icc': out_rows,
            'ms': {'MSR': MSR, 'MSC': MSC, 'MSE': MSE, 'MSW': MSW}, 'notes': notes, 'code': '\n'.join(c)}


def kendall_w(X):
    """Kendall's coefficient of concordance of the columns (raters) of X over
    its rows (objects), with the correction for ties: each rater ranks the
    objects (tied ones share the mean rank), S is the sum of squared
    deviations of the objects' rank sums from their mean, and
    W = 12 S / (m² (n³ - n) - m T), T = sum over raters and tie groups of
    t³ - t (Kendall and Babington Smith 1939; Kendall 1948). The chi-square
    m (n - 1) W on n - 1 DF is Friedman's (1937) statistic, ties corrected."""
    X = np.asarray(X, float)
    n, m = X.shape
    R = np.column_stack([stats.rankdata(X[:, j]) for j in range(m)])
    Ri = R.sum(axis=1)
    S = float(np.sum((Ri - Ri.mean()) ** 2))
    T = 0.0
    for j in range(m):
        _, t = np.unique(X[:, j], return_counts=True)
        T += float(np.sum(t ** 3 - t))
    den = m * m * (n ** 3 - n) - m * T
    W = 12 * S / den if den > 0 else float('nan')
    return W, S, T, Ri


@api('multivariate.kendall_w')
def mv_kendall_w(table, columns, rows=None, weight=None, freq=None, table_name='data'):
    """Kendall's W of the columns (raters) over the rows (objects) rated by
    all of them, its chi-square test (Friedman's) and the mean Spearman
    correlation of the pairs of raters. As for the nonparametric
    correlations, Weight and Freq only leave out rows without a positive
    value."""
    cols = list(columns)
    m = len(cols)
    full, _, _ = _frame(table, cols, rows, weight, freq, dropna=False)
    df, _, _ = _frame(table, cols, rows, weight, freq)
    X = df.to_numpy(float)
    n = len(X)
    if m < 2 or n < 2:
        return {'error': "Kendall's W needs two or more columns (the raters) and two or more rows rated by all of them"}
    W, S, T, _ = kendall_w(X)
    if not np.isfinite(W):
        return {'error': "Every rater ties every object: Kendall's W is not defined"}
    chi2 = m * (n - 1) * W
    rs = stats.spearmanr(X).statistic if m > 2 else stats.spearmanr(X[:, 0], X[:, 1]).statistic
    rs = np.atleast_2d(rs)
    mean_rs = float(np.nanmean(rs[np.triu_indices(m, 1)])) if m > 2 else float(rs[0, 0])
    left = int(len(full) - n)
    c = [code_head(table_name, ['from scipy import stats']),
         f'X = df[{_cols_expr(cols)}].dropna().to_numpy(); n, m = X.shape   # the objects are the rows, the raters the columns',
         'R = np.column_stack([stats.rankdata(X[:, j]) for j in range(m)])   # each rater ranks the objects (ties: mean ranks)',
         'S = ((R.sum(1) - R.sum(1).mean()) ** 2).sum()',
         'T = 0',
         'for j in range(m):   # the ties of each rater: t^3 - t for each group of t tied objects',
         '    t = np.unique(X[:, j], return_counts=True)[1]; T += (t ** 3 - t).sum()',
         'W = 12 * S / (m * m * (n ** 3 - n) - m * T); chi2 = m * (n - 1) * W',
         'print(W, chi2, n - 1, stats.chi2.sf(chi2, n - 1))']
    if n >= 3:
        c.append('print(stats.friedmanchisquare(*X), chi2)   # Friedman\'s test is the same chi-square: W = chi2 / (m (n - 1))')
    notes = []
    if left:
        notes.append(f'{left} row{"" if left == 1 else "s"} without a rating from every rater left out.')
    if weight or freq:
        notes.append('Weight and Freq are not used by these rank statistics; they only leave out rows without a positive value.')
    return {'w': W, 'chi2': chi2, 'df': n - 1, 'p': float(stats.chi2.sf(chi2, n - 1)), 'n': n, 'm': m, 's': S, 'ties': T, 'mean_spearman': mean_rs,
            'left_out': left, 'notes': notes, 'code': '\n'.join(c)}


@api('multivariate.cluster_order')
def mv_cluster_order(corr, table=None, rows=None):
    """An order of the variables that puts similar ones together (Cluster the
    Correlations): average linkage on 1 - r."""
    from scipy.cluster.hierarchy import leaves_list, linkage
    from scipy.spatial.distance import squareform
    R = np.array([[np.nan if v is None else v for v in row] for row in corr], float)
    R = np.nan_to_num(R, nan=0.0)
    D = np.clip(1 - R, 0, 2)
    np.fill_diagonal(D, 0)
    if len(R) < 3:
        return {'order': list(range(len(R)))}
    Z = linkage(squareform((D + D.T) / 2, checks=False), 'average')
    return {'order': leaves_list(Z).tolist()}


# ---- rotations (Principal Components and Factor Analysis) --------------------------------------

# name -> (label, kind, how). Orthomax weights follow SAS PROC FACTOR's
# definitions (which JMP names): varimax 1, quartimax 0, biquartimax 1/2,
# equamax k/2, parsimax p(k-1)/(p+k-2), factor parsimax p. The oblique
# members are the Crawford-Ferguson family with kappa = gamma/p (Browne 2001).
ROTATIONS = {
    'varimax': ('Varimax', 'orthogonal'), 'quartimax': ('Quartimax', 'orthogonal'), 'biquartimax': ('Biquartimax', 'orthogonal'),
    'equamax': ('Equamax', 'orthogonal'), 'parsimax': ('Parsimax', 'orthogonal'), 'factorparsimax': ('Factorparsimax', 'orthogonal'),
    'orthomax': ('Orthomax', 'orthogonal'),
    'promax': ('Promax', 'oblique'), 'quartimin': ('Quartimin', 'oblique'), 'biquartimin': ('Biquartimin', 'oblique'),
    'covarimin': ('Covarimin', 'oblique'), 'oblimin': ('Oblimin', 'oblique'), 'obvarimax': ('Obvarimax', 'oblique'),
    'obequamax': ('Obequamax', 'oblique'), 'obparsimax': ('Obparsimax', 'oblique'), 'obfactorparsimax': ('Obfactorparsimax', 'oblique'),
}


def rotate(A, method='varimax', gamma=None, kaiser=True, power=3):
    """Rotate the loadings A (p x k) with statsmodels' factor_rotation.
    Returns (L, T, Phi): L = A T for orthogonal rotations and L = A (T')^-1
    for oblique ones (statsmodels' convention), Phi = T'T the correlations of
    the rotated factors. Kaiser's normalization (rows scaled to unit length
    before the rotation, and back after) is SAS PROC FACTOR's default."""
    from statsmodels.multivariate.factor_rotation import rotate_factors
    A = np.asarray(A, float)
    p, k = A.shape
    if k < 2 or method in (None, '', 'none'):
        return A.copy(), np.eye(k), np.eye(k)
    h = np.sqrt((A * A).sum(1)) if kaiser else np.ones(p)
    h = np.where(h > 0, h, 1.0)
    An = A / h[:, None]
    ortho = {'varimax': 1.0, 'quartimax': 0.0, 'biquartimax': 0.5, 'equamax': k / 2.0,
             'parsimax': p * (k - 1) / (p + k - 2), 'factorparsimax': float(p),
             'orthomax': 1.0 if gamma is None else float(gamma)}
    obl = {'quartimin': 0.0, 'biquartimin': 0.5, 'covarimin': 1.0, 'oblimin': 0.0 if gamma is None else float(gamma)}
    cf = {'obvarimax': 1.0 / p, 'obequamax': k / (2.0 * p), 'obparsimax': (k - 1) / (p + k - 2), 'obfactorparsimax': 1.0}
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        if method in ortho:
            L, T = rotate_factors(An, 'orthomax', ortho[method])
        elif method in obl:
            L, T = rotate_factors(An, 'oblimin', obl[method], 'oblique')
        elif method in cf:
            L, T = rotate_factors(An, 'CF', cf[method], 'oblique')
        elif method == 'promax':
            # Hendrickson and White's promax as SAS and R compute it: varimax,
            # the target V|V|^(power-1), the least-squares (Procrustes) map U
            # of A to it, columns scaled so that the factor correlations
            # (U'U)^-1 have a unit diagonal; the pattern is A U. statsmodels'
            # promax returns A (UD)^-T instead, which does not approximate its
            # target unless U is orthogonal. In statsmodels' oblique
            # convention L = A (T')^-1, T = U^-T.
            V, _ = rotate_factors(An, 'orthomax', 1.0)
            H = V * np.abs(V) ** (power - 1)
            U = np.linalg.lstsq(An, H, rcond=None)[0]
            U = U @ np.diag(np.sqrt(np.diag(np.linalg.inv(U.T @ U))))
            L = An @ U
            T = np.linalg.inv(U).T
        else:
            raise ValueError(f'no rotation {method!r}')
    L = L * h[:, None]
    # order the rotated factors by the variance they explain, and make each
    # factor's column sum positive
    var = (L * L).sum(0)
    order = np.argsort(-var)
    L, T = L[:, order], T[:, order]
    sg = np.where(L.sum(0) < 0, -1.0, 1.0)
    L, T = L * sg, T * sg
    Phi = T.T @ T
    return L, T, Phi


# ---- Principal Components ----------------------------------------------------------------------

def _pca_core(X, w, on):
    """Eigen decomposition of the correlation, covariance or unscaled
    cross-product matrix through statsmodels' PCA (on the weighted,
    centred and scaled data). Returns the JMP-scaled eigenvalues and the
    eigenvectors, the centring and scaling, and the matrix itself."""
    from statsmodels.multivariate.pca import PCA
    sw = float(np.sum(w))
    if on == 'unscaled':
        center = np.zeros(X.shape[1])
        scale = np.ones(X.shape[1])
        denom = sw
    else:
        center = (w[:, None] * X).sum(0) / sw
        var = (w[:, None] * (X - center) ** 2).sum(0) / (sw - 1)
        scale = np.sqrt(var) if on == 'correlations' else np.ones(X.shape[1])
        denom = sw - 1
    if on == 'correlations' and np.any(scale <= 0):
        raise ValueError('a column is constant: its correlations are not defined')
    Z = (X - center) / scale
    M = Z * np.sqrt(w)[:, None]
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        pc = PCA(M, standardize=False, demean=False, normalize=False, method='eig')
    vals = np.asarray(pc.eigenvals, float) / denom
    vecs = _sign_fix(np.asarray(pc.eigenvecs, float))
    vals = np.where(vals > 1e-12 * max(1.0, abs(vals[0])), vals, 0.0)
    C = M.T @ M / denom
    return vals, vecs, center, scale, Z, C


def bartlett_equal(vals, nobs):
    """Bartlett's (1950) test that the eigenvalues from the kth on are equal,
    as Jackson (2003) gives it: chi2 = nu (q ln(mean) - sum ln), nu = n - 1,
    df = (q - 1)(q + 2)/2 for the q = p - k + 1 last eigenvalues."""
    p = len(vals)
    nu = nobs - 1
    out = []
    for k in range(p):
        q = p - k
        lam = np.asarray(vals[k:], float)
        if q < 2 or np.any(lam <= 0):
            out.append({'chi2': None, 'df': None, 'p': None})
            continue
        chi2 = nu * (q * math.log(lam.mean()) - np.log(lam).sum())
        df = (q - 1) * (q + 2) / 2
        out.append({'chi2': chi2, 'df': df, 'p': float(stats.chi2.sf(chi2, df))})
    return out


@api('pca.fit')
def pca_fit(table, columns, rows=None, weight=None, freq=None, on='correlations', rotation=None, n_rotate=None,
            gamma=None, kaiser=True, alpha=0.05, table_name='data'):
    """Principal components as JMP reports them: eigenvalues scaled to the
    matrix analysed, eigenvectors of norm one, loadings (the correlations of
    variables and components for on-correlations and on-covariances), and
    the scores: the centred (and for correlations scaled) rows times the
    eigenvectors."""
    cols = list(columns)
    df, w, f = _frame(table, cols, rows, weight, freq)
    X = df.to_numpy(float)
    n, p = X.shape
    if n < 2:
        return {'error': 'fewer than two rows without missing values'}
    try:
        vals, V, center, scale, Z, C = _pca_core(X, w, on)
    except ValueError as e:
        return {'error': str(e)}
    nobs = _nobs(f, freq)
    k = len(vals)
    V = V[:, :k]
    total = float(np.sum(vals))
    sq = np.sqrt(np.maximum(vals, 0))
    if on == 'correlations':
        load = V * sq
    elif on == 'covariances':
        load = V * sq / np.sqrt(np.diag(C))[:, None]
    else:
        load = V * sq / np.sqrt(np.diag(C))[:, None]
    scores = Z @ V
    out = {'names': cols, 'on': on, 'n': nobs, 'n_rows': n, 'rows': df.index.to_numpy(),
           'eigenvalues': vals, 'percent': 100 * vals / total if total > 0 else vals * np.nan,
           'cum': 100 * np.cumsum(vals) / total if total > 0 else vals * np.nan,
           'bartlett': bartlett_equal(vals, nobs), 'eigenvectors': _mat(V), 'loadings': _mat(load),
           'scores': _mat(scores), 'center': center, 'scale': scale, 'matrix': _mat(C),
           'corr': _mat(_cov_to_corr(C)) if on != 'unscaled' else None}
    if rotation and rotation != 'none':
        kr = int(n_rotate or max(1, int(np.sum(vals >= 1)) if on == 'correlations' else 2))
        kr = max(2, min(kr, k))
        L, T, Phi = rotate(load[:, :kr], rotation, gamma, kaiser)
        # rotated component scores: standardized component scores times T
        with np.errstate(divide='ignore', invalid='ignore'):
            Fz = scores[:, :kr] / np.where(sq[:kr] > 0, sq[:kr], np.nan)
        out['rotation'] = {'method': rotation, 'label': ROTATIONS.get(rotation, (rotation, ''))[0],
                           'kind': ROTATIONS.get(rotation, ('', 'orthogonal'))[1], 'k': kr,
                           'loadings': _mat(L), 'T': _mat(T), 'phi': _mat(Phi),
                           'variance': (L * L).sum(0), 'scores': _mat(Fz @ T), 'kaiser': bool(kaiser)}
    scale_line = {'correlations': 'standardize=True', 'covariances': 'standardize=False, demean=True', 'unscaled': 'standardize=False, demean=False'}[on]
    divisor = {'correlations': 'n', 'covariances': '(n - 1)', 'unscaled': 'n'}[on]
    out['code'] = '\n'.join([
        code_head(table_name, ['from statsmodels.multivariate.pca import PCA']),
        f'X = df[{_cols_expr(cols)}].dropna(); n = len(X)',
        f'pc = PCA(X, {scale_line}, normalize=False, method="eig")',
        f'eig = pc.eigenvals / {divisor}   # the eigenvalues as JMP scales them (statsmodels standardizes with the n divisor)',
        'print(eig, 100 * eig / eig.sum())',
        'print(pc.eigenvecs)   # eigenvectors (the sign of each is arbitrary)',
    ] + (['print(pc.eigenvecs * np.sqrt(eig.to_numpy()))   # loadings: correlations of variables and components'] if on == 'correlations' else []))
    return out


# ---- Factor Analysis ------------------------------------------------------------------------------

def _smc(R):
    try:
        return 1 - 1 / np.diag(np.linalg.inv(R))
    except np.linalg.LinAlgError:
        return np.full(len(R), np.nan)


def _kmo(R):
    Ri = np.linalg.inv(R)
    d = np.sqrt(np.diag(Ri))
    A = -Ri / np.outer(d, d)          # anti-image (partial) correlations
    off = ~np.eye(len(R), dtype=bool)
    r2 = np.where(off, R * R, 0)
    a2 = np.where(off, A * A, 0)
    items = r2.sum(0) / (r2.sum(0) + a2.sum(0))
    overall = r2.sum() / (r2.sum() + a2.sum())
    return float(overall), items


def _sort_order(L):
    """Variables grouped by the factor with their largest absolute loading,
    and by decreasing loading within a factor (SAS's REORDER)."""
    L = np.asarray(L, float)
    top = np.argmax(np.abs(L), axis=1)
    return sorted(range(len(L)), key=lambda i: (top[i], -abs(L[i, top[i]])))


def _fa_prelim(table, columns, rows, weight, freq):
    """The correlation matrix of a factor analysis, its eigenvalues, the
    default number of factors (eigenvalues of at least one), Bartlett's
    test of sphericity and the Kaiser-Meyer-Olkin measure."""
    cols = list(columns)
    df, w, f = _frame(table, cols, rows, weight, freq)
    X = df.to_numpy(float)
    n, p = X.shape
    nobs = _nobs(f, freq)
    if n < 3 or p < 2:
        return None, {'error': 'needs two or more columns and three or more rows without missing values'}
    _, S = _wmean_cov(X, w)
    if np.any(np.diag(S) <= 0):
        return None, {'error': 'a column is constant'}
    R = _cov_to_corr(S)
    ev = np.sort(np.linalg.eigvalsh(R))[::-1]
    n_default = max(1, int(np.sum(ev >= 1 - 1e-12)))
    out = {'names': cols, 'n': nobs, 'n_rows': n, 'n_default': n_default,
           'eigen': {'values': ev, 'percent': 100 * ev / ev.sum(), 'cum': 100 * np.cumsum(ev) / ev.sum()}}
    detR = np.linalg.det(R)
    if detR > 0:
        chi = -(nobs - 1 - (2 * p + 5) / 6) * math.log(detR)
        dfs = p * (p - 1) / 2
        out['sphericity'] = {'chi2': chi, 'df': dfs, 'p': float(stats.chi2.sf(chi, dfs))}
        overall, items = _kmo(R)
        out['kmo'] = {'overall': overall, 'items': items}
    return (df, X, w, nobs, R, detR), out


def _kmax_ml(p):
    return max(1, int((2 * p + 1 - math.sqrt(8 * p + 1)) // 2))


@api('factor.eigen')
def factor_eigen(table, columns, rows=None, weight=None, freq=None, table_name='data'):
    """The first part of the Factor Analysis report: the eigenvalues of the
    correlation matrix, the default number of factors, sphericity, KMO."""
    _, out = _fa_prelim(table, columns, rows, weight, freq)
    out['code'] = '\n'.join([code_head(table_name), f'X = df[{_cols_expr(list(columns))}].dropna()',
                             'R = X.corr().to_numpy(); ev = np.sort(np.linalg.eigvalsh(R))[::-1]',
                             'print(ev, 100 * ev / ev.sum())   # eigenvalues; the default number of factors is the count of those >= 1',
                             'p, n = R.shape[0], len(X); chi2 = -(n - 1 - (2 * p + 5) / 6) * np.log(np.linalg.det(R))   # Bartlett\'s sphericity, p(p-1)/2 df'])
    return out


@api('factor.fit')
def factor_fit(table, columns, rows=None, weight=None, freq=None, n_factors=None, method='ml', prior='smc',
               rotation='varimax', gamma=None, kaiser=True, table_name='data'):
    """Factor analysis with statsmodels' Factor (principal axis or maximum
    likelihood, on the correlation matrix), rotated with factor_rotation."""
    from statsmodels.multivariate.factor import Factor
    cols = list(columns)
    pre, out = _fa_prelim(table, columns, rows, weight, freq)
    if pre is None:
        return out
    df, X, w, nobs, R, detR = pre
    n, p = X.shape
    n_default = out['n_default']
    k = int(n_factors) if n_factors else n_default
    k = max(1, min(k, p - 1 if method == 'ml' else p))
    out.update({'k': k, 'method': method, 'prior': prior})
    if method == 'ml' and ((p - k) ** 2 - (p + k)) < 0:
        out['identify'] = f'{k} factors for {p} columns leave negative degrees of freedom: the maximum likelihood model is not identified (at most {_kmax_ml(p)} factor{"" if _kmax_ml(p) == 1 else "s"}).'
    smc = _smc(R)
    prior_c = smc if prior == 'smc' else np.ones(p)
    out['prior_communality'] = prior_c
    if prior == 'smc' and np.all(np.isfinite(smc)):
        Rr = R.copy()
        np.fill_diagonal(Rr, smc)
        rev = np.sort(np.linalg.eigvalsh(Rr))[::-1]
        out['reduced_eigen'] = {'values': rev, 'percent': 100 * rev / rev.sum(), 'cum': 100 * np.cumsum(rev) / rev.sum()}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            model = Factor(corr=R, n_factor=k, method=method, smc=(prior == 'smc'), nobs=int(round(nobs)), endog_names=cols)
            res = model.fit()
    except Exception as e:  # a singular or indefinite matrix, too many factors
        out['error'] = f'the factor model could not be fitted: {e}'
        return out
    A = np.asarray(res.loadings_no_rot, float)
    A = A * np.where(A.sum(0) < 0, -1.0, 1.0)
    L, T, Phi = rotate(A, rotation, gamma, kaiser) if k > 1 else (A.copy(), np.eye(k), np.eye(k))
    oblique = ROTATIONS.get(rotation, ('', 'orthogonal'))[1] == 'oblique' and k > 1
    # Final communalities from the unrotated fit; uniqueness 1 - h2 for PA,
    # the ML estimate for ML.
    comm = (A * A).sum(1)
    uniq = np.asarray(res.uniqueness, float) if method == 'ml' else 1 - comm
    res.loadings = L
    res.rotation_matrix = T
    coef = np.asarray(res.factor_score_params(method='regression'), float)   # Thurstone's regression scores
    Zs = (X - X.mean(0)) / X.std(0, ddof=1)
    scores = Zs @ coef
    out.update({'unrotated': _mat(A), 'rotated': _mat(L), 'rotation_matrix': _mat(T), 'phi': _mat(Phi), 'oblique': bool(oblique),
                'structure': _mat(L @ Phi) if oblique else None, 'communality': comm, 'uniqueness': uniq,
                'rotation': rotation or 'none', 'rotation_label': ROTATIONS.get(rotation, ('None', ''))[0] if rotation else 'None',
                'order': _sort_order(L), 'order_unrotated': _sort_order(A), 'score_coef': _mat(coef),
                'scores': _mat(scores), 'rows': df.index.to_numpy(), 'kaiser': bool(kaiser)})
    varL = (L * L).sum(0) if not oblique else (L * (L @ Phi)).sum(0)
    if oblique:   # ignoring the other factors: the squared structure coefficients
        St = L @ Phi
        varL = (St * St).sum(0)
    out['variance'] = [{'factor': f'Factor {j + 1}', 'variance': float(v), 'percent': 100 * float(v) / p,
                        'cum': 100 * float(np.sum(varL[:j + 1])) / p if not oblique else None} for j, v in enumerate(varL)]
    if method == 'ml':
        Sig = A @ A.T + np.diag(uniq)
        try:
            Fml = math.log(np.linalg.det(Sig)) - math.log(detR) + np.trace(R @ np.linalg.inv(Sig)) - p
        except (ValueError, np.linalg.LinAlgError):
            Fml = float('nan')
        dfm = ((p - k) ** 2 - (p + k)) / 2
        mult = nobs - 1 - (2 * p + 5) / 6 - 2 * k / 3
        chi = mult * Fml
        chi0 = (nobs - 1) * Fml
        out['ml_test'] = {'chi2': chi, 'df': dfm, 'p': float(stats.chi2.sf(chi, dfm)) if dfm > 0 else None, 'criterion': Fml}
        # measures of fit (SAS PROC FACTOR's): chi-square without Bartlett's correction,
        # AIC and BIC on it, Tucker-Lewis, RMSEA
        F0 = -math.log(detR) if detR > 0 else float('nan')
        df0 = p * (p - 1) / 2
        m0 = nobs - 1 - (2 * p + 5) / 6
        tli = ((m0 * F0 / df0) - (mult * Fml / dfm)) / ((m0 * F0 / df0) - 1) if dfm > 0 and df0 > 0 else None
        out['fit'] = {'chi2_uncorrected': chi0, 'aic': chi0 - 2 * dfm, 'bic': chi0 - dfm * math.log(nobs),
                      'tli': tli, 'rmsea': math.sqrt(max(chi0 / dfm - 1, 0) / (nobs - 1)) if dfm > 0 else None}
    out['code'] = '\n'.join([
        code_head(table_name, ['from statsmodels.multivariate.factor import Factor']),
        f'X = df[{_cols_expr(cols)}].dropna()',
        f'res = Factor(X, n_factor={k}, method={method!r}, smc={prior == "smc"}).fit()',
        'print(res.loadings_no_rot, res.communality)   # unrotated loadings, communalities',
        (f'res.rotate({rotation!r}); print(res.loadings)   # statsmodels\' {rotation} (JMP\'s rotations use Kaiser normalization; see the report note)'
         if rotation in ('varimax', 'quartimax', 'biquartimax', 'promax', 'parsimax') else '# rotation: statsmodels.multivariate.factor_rotation.rotate_factors'),
        'print(res.factor_scoring(method="regression")[:5])   # factor scores (Thurstone)'])
    return out


# ---- Discriminant --------------------------------------------------------------------------------

def _cat_frame(table, ycols, xcol, rows, weight, freq):
    df = data.frame(table, list(ycols) + [xcol] + [c for c in (weight, freq) if c], rows, dropna=True, as_category=True)
    for c in ycols:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=list(ycols))
    w = np.ones(len(df))
    f = np.ones(len(df))
    if weight:
        w = w * pd.to_numeric(df[weight], errors='coerce').to_numpy(float)
    if freq:
        f = pd.to_numeric(df[freq], errors='coerce').to_numpy(float)
        w = w * f
    ok = np.isfinite(w) & (w > 0)
    return df[ok], w[ok], f[ok]


def _level_value(v):
    if isinstance(v, (float, np.floating)) and float(v).is_integer():
        return float(v)
    return v if isinstance(v, str) else float(v) if isinstance(v, (int, float, np.integer, np.floating)) else str(v)


def _pkey(v):
    """A level as the page writes it: 3 for 3.0."""
    if isinstance(v, (float, np.floating)) and float(v).is_integer():
        return str(int(v))
    return str(v)


@api('discriminant.fit')
def disc_fit(table, y, x, rows=None, weight=None, freq=None, method='linear', lam=0.5, gam=0.0,
             priors='equal', prior_values=None, alpha=0.05, table_name='data'):
    """Discriminant analysis as JMP reports it: squared distances, posterior
    probabilities and classification (linear: pooled covariance; quadratic:
    each group's; regularized: Friedman's compromise), the canonical
    analysis of the between and pooled within matrices, and the multivariate
    tests (statsmodels MANOVA)."""
    ycols = list(y)
    df, w, f = _cat_frame(table, ycols, x, rows, weight, freq)
    g = df[x]
    levels_all = list(g.cat.categories) if hasattr(g, 'cat') else sorted(g.unique())
    present = [lv for lv in levels_all if (g == lv).any()]
    if len(present) < 2:
        return {'error': 'the categories column needs at least two levels with data'}
    Y = df[ycols].to_numpy(float)
    n, p = Y.shape
    T = len(present)
    code_idx = np.array([present.index(v) for v in g], int)
    nobs = _nobs(f, freq)
    sw = float(w.sum())
    means, covs, sws, logdets = [], [], [], []
    E = np.zeros((p, p))
    for t in range(T):
        m_ = code_idx == t
        wt = w[m_]
        swt = float(wt.sum())
        mt = (wt[:, None] * Y[m_]).sum(0) / swt
        Ct = Y[m_] - mt
        Et = (wt[:, None] * Ct).T @ Ct
        E += Et
        covs.append(Et / (swt - 1) if swt > 1 else np.full((p, p), np.nan))
        means.append(mt)
        sws.append(swt)
    means = np.array(means)
    gm = (w[:, None] * Y).sum(0) / sw
    Sp = E / (sw - T)
    B = sum(sws[t] * np.outer(means[t] - gm, means[t] - gm) for t in range(T))
    notes = []
    # priors
    if priors == 'proportional':
        q = np.array(sws) / sw
    elif priors == 'other' and prior_values:
        q = np.array([float(prior_values.get(_pkey(lv), prior_values.get(str(lv), 0)) or 0) for lv in present])
        q = q / q.sum() if q.sum() > 0 else np.full(T, 1 / T)
    else:
        q = np.full(T, 1.0 / T)
    # the covariance of each group for the chosen method
    Sinv = []
    if method == 'linear':
        Spi = np.linalg.pinv(Sp)
        Sinv = [Spi] * T
        logdets = [0.0] * T
    else:
        lam_ = 0.0 if method == 'quadratic' else float(lam)
        gam_ = 0.0 if method == 'quadratic' else float(gam)
        for t in range(T):
            St = covs[t]
            if not np.all(np.isfinite(St)):
                St = Sp.copy()
                notes.append(f'{present[t]}: one row; the pooled covariance is used for it')
            # a covariate constant within a group: its covariances from the pooled matrix
            dz = np.diag(St) <= 1e-12 * np.maximum(np.diag(Sp), 1e-300)
            if np.any(dz):
                St = St.copy()
                St[dz, :] = Sp[dz, :]
                St[:, dz] = Sp[:, dz]
                notes.append(f'{present[t]}: {", ".join(ycols[j] for j in np.where(dz)[0])} constant in this group; its covariances from the pooled matrix')
            Mix = lam_ * Sp + (1 - lam_) * St
            Sig = (1 - gam_) * Mix + gam_ * np.diag(np.diag(Mix))
            sgn, ld = np.linalg.slogdet(Sig)
            Sinv.append(np.linalg.pinv(Sig))
            logdets.append(ld if sgn > 0 else float('nan'))
    D2 = np.empty((n, T))
    for t in range(T):
        e = Y - means[t]
        D2[:, t] = np.einsum('ij,jk,ik->i', e, Sinv[t], e)
    SqDist = D2 + np.array(logdets)[None, :] - 2 * np.log(q)[None, :]
    a = -0.5 * SqDist
    a = a - a.max(1, keepdims=True)
    P = np.exp(a)
    P = P / P.sum(1, keepdims=True)
    pred = P.argmax(1)
    prob_act = P[np.arange(n), code_idx]
    mis = pred != code_idx
    with np.errstate(divide='ignore'):
        nll = -np.log(np.maximum(prob_act, 1e-300))
    # entropy RSquare against the model with no covariates (the class shares)
    shares = np.array(sws) / sw
    ll_full = float(np.sum(w * np.log(np.maximum(prob_act, 1e-300))))
    ll_red = float(np.sum(w * np.log(shares[code_idx])))
    conf = np.zeros((T, T))
    for a_, b_, ww in zip(code_idx, pred, w):
        conf[a_, b_] += ww
    # canonical analysis: eigenvalues of E^-1 H (H = the between SSCP)
    canon = None
    try:
        vals, vecs = sla.eigh(B, E)
        order = np.argsort(vals)[::-1]
        vals, vecs = vals[order], vecs[:, order]
        m = min(T - 1, p)
        vals, vecs = np.maximum(vals[:m], 0), vecs[:, :m]
        raw = vecs * math.sqrt(sw - T)                 # pooled within variance of each canonical variable 1
        raw = raw * np.where((raw * np.sqrt(np.diag(Sp))[:, None]).sum(0) < 0, -1.0, 1.0)
        std = raw * np.sqrt(np.diag(Sp))[:, None]      # pooled within-class standardized
        cs = (Y - gm) @ raw
        cm = (means - gm) @ raw
        cc = np.sqrt(vals / (1 + vals))
        lr = [float(np.prod(1 / (1 + vals[j:]))) for j in range(m)]
        # the likelihood ratio tests of each root and those after it (Rao's F)
        lr_tests = []
        for j in range(m):
            lam_j = lr[j]
            pk, qk = p - j, T - 1 - j
            ve = sw - T
            tpk = (pk * pk * qk * qk - 4) / (pk * pk + qk * qk - 5) if pk * pk + qk * qk - 5 > 0 else 1
            tt = math.sqrt(tpk) if tpk > 0 else 1
            df1 = pk * qk
            df2 = (ve - (pk - qk + 1) / 2) * tt - (pk * qk - 2) / 2
            Fv = (1 - lam_j ** (1 / tt)) / (lam_j ** (1 / tt)) * df2 / df1
            lr_tests.append({'F': Fv, 'numdf': df1, 'dendf': df2, 'p': float(stats.f.sf(Fv, df1, df2))})
        Tcov = ((w[:, None] * (Y - gm)).T @ (Y - gm)) / (sw - 1)
        tsd = np.sqrt(np.diag(Tcov))
        total_struct = (Tcov @ raw) / tsd[:, None] / np.sqrt(np.einsum('ij,jk,ki->i', raw.T, Tcov, raw))[None, :]
        within_struct = (Sp @ raw) / np.sqrt(np.diag(Sp))[:, None]
        Bc = B / (sw - 1)
        bsd = np.sqrt(np.maximum(np.diag(Bc), 0))
        with np.errstate(divide='ignore', invalid='ignore'):
            between_struct = (Bc @ raw) / bsd[:, None] / np.sqrt(np.maximum(np.einsum('ij,jk,ki->i', raw.T, Bc, raw), 1e-300))[None, :]
        canon = {'eigen': vals, 'percent': 100 * vals / vals.sum() if vals.sum() > 0 else vals * 0,
                 'cum': 100 * np.cumsum(vals) / vals.sum() if vals.sum() > 0 else vals * 0,
                 'cancorr': cc, 'lr': lr, 'lr_tests': lr_tests, 'raw': _mat(raw), 'std': _mat(std),
                 'scores': _mat(cs), 'means': _mat(cm), 'total_struct': _mat(total_struct),
                 'between_struct': _mat(between_struct), 'within_struct': _mat(within_struct), 'm': m}
    except (np.linalg.LinAlgError, ValueError) as e:
        notes.append(f'canonical analysis not available: {e}')
    tests = _manova_tests(df, ycols, x, w if (weight or freq) else None)
    out = {'names': ycols, 'x': x, 'levels': [_level_value(v) for v in present], 'n': nobs, 'n_rows': n, 'T': T, 'p': p,
           'method': method, 'lam': lam, 'gam': gam, 'priors': q, 'rows': df.index.to_numpy(), 'actual': code_idx,
           'pred': pred, 'prob': _mat(P), 'sqdist': _mat(SqDist), 'prob_actual': prob_act, 'neg_log_prob': nll,
           'misclassified': mis, 'counts': sws, 'means': _mat(means), 'grand_mean': gm, 'pooled_cov': _mat(Sp),
           'pooled_corr': _mat(_cov_to_corr(Sp)), 'group_cov': [_mat(c) for c in covs], 'logdet': logdets,
           'summary': {'n_mis': float(np.sum(w * mis)), 'pct_mis': 100 * float(np.sum(w * mis)) / sw,
                       'entropy_r2': 1 - ll_full / ll_red if ll_red != 0 else None, 'm2ll': -2 * ll_full, 'n': sw},
           'confusion': _mat(conf), 'canonical': canon, 'tests': tests, 'notes': notes}
    out['code'] = '\n'.join([
        code_head(table_name, ['from statsmodels.multivariate.manova import MANOVA']),
        f'd = df[{_cols_expr(ycols + [x])}].dropna(); Y = d[{_cols_expr(ycols)}].to_numpy(); g = d[{J(x)}].astype(str)',
        'lv = sorted(g.unique()); n, T = len(d), len(lv)',
        'means = np.array([Y[g == t].mean(0) for t in lv])',
        'Sp = sum((Y[g == t] - Y[g == t].mean(0)).T @ (Y[g == t] - Y[g == t].mean(0)) for t in lv) / (n - T)   # pooled within covariance',
        'Si = np.linalg.inv(Sp)',
        'D2 = np.array([np.einsum("ij,jk,ik->i", Y - m, Si, Y - m) for m in means]).T   # squared Mahalanobis distances',
        'P = np.exp(-D2 / 2); P /= P.sum(1, keepdims=True)   # posterior probabilities, equal priors (linear method)',
        "print(pd.crosstab(g, np.array(lv)[P.argmax(1)], rownames=['Actual'], colnames=['Predicted']))",
        f'print(MANOVA.from_formula({J(" + ".join(_q(c) for c in ycols) + " ~ C(" + _q(x) + ")")}, data=d).mv_test())   # Wilks, Pillai, Hotelling-Lawley, Roy'])
    return out


def _manova_tests(df, ycols, x, w=None):
    """Wilks' lambda, Pillai's trace, Hotelling-Lawley and Roy from
    statsmodels' MANOVA of the covariates on the categories."""
    from statsmodels.multivariate.manova import MANOVA
    try:
        Y = df[ycols].to_numpy(float)
        g = df[x]
        codes = pd.Categorical(g).codes
        k = int(codes.max()) + 1
        Xd = np.column_stack([np.ones(len(Y))] + [(codes == j).astype(float) for j in range(1, k)])
        if w is not None:
            sq = np.sqrt(w / np.mean(w))
            Y = Y * sq[:, None]
            Xd = Xd * sq[:, None]
        L = np.zeros((k - 1, k))
        L[:, 1:] = np.eye(k - 1)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            res = MANOVA(Y, Xd).mv_test([('categories', L)])
        st = res.results['categories']['stat']
        out = []
        for name, label in (("Wilks' lambda", "Wilks' Lambda"), ("Pillai's trace", "Pillai's Trace"),
                            ('Hotelling-Lawley trace', 'Hotelling-Lawley'), ("Roy's greatest root", "Roy's Max Root")):
            row = st.loc[name]
            out.append({'test': label, 'value': float(row['Value']), 'F': float(row['F Value']), 'numdf': float(row['Num DF']),
                        'dendf': float(row['Den DF']), 'p': float(row['Pr > F'])})
        return out
    except Exception as e:  # singular E, too few rows
        return [{'test': f'not available: {e}', 'value': None, 'F': None, 'numdf': None, 'dendf': None, 'p': None}]


@api('discriminant.stepwise')
def disc_stepwise(table, y, x, rows=None, entered=None, weight=None, freq=None):
    """JMP's stepwise panel: for each covariate, the analysis-of-covariance F
    test of the categories with the covariate as the response and the
    covariates already entered as predictors (statsmodels OLS)."""
    import statsmodels.api as sm
    ycols = list(y)
    entered = [c for c in (entered or []) if c in ycols]
    df, w, _ = _cat_frame(table, ycols, x, rows, weight, freq)
    g = pd.Categorical(df[x])
    D = pd.get_dummies(g, drop_first=True).to_numpy(float)
    out = []
    for c in ycols:
        others = [e for e in entered if e != c]
        base = np.column_stack([np.ones(len(df))] + [df[o].to_numpy(float) for o in others]) if others else np.ones((len(df), 1))
        full = np.column_stack([base, D])
        yv = df[c].to_numpy(float)
        try:
            r1 = sm.WLS(yv, full, weights=w).fit()
            r0 = sm.WLS(yv, base, weights=w).fit()
            Fv, pv, dfd = r1.compare_f_test(r0)
            out.append({'column': c, 'entered': c in entered, 'F': float(Fv), 'p': float(pv)})
        except Exception:
            out.append({'column': c, 'entered': c in entered, 'F': None, 'p': None})
    ins = [r for r in out if r['entered'] and r['p'] is not None]
    outs = [r for r in out if not r['entered'] and r['p'] is not None]
    return {'columns': out, 'n_in': len(entered), 'n_out': len(ycols) - len(entered),
            'smallest_p_enter': min((r['p'] for r in outs), default=None), 'largest_p_remove': max((r['p'] for r in ins), default=None)}


# ---- Hierarchical Cluster ------------------------------------------------------------------------

METHODS_H = ('average', 'centroid', 'ward', 'single', 'complete')


def _standardize(X, how):
    if how == 'columns':
        sd = X.std(0, ddof=1)
        sd = np.where(sd > 0, sd, 1.0)
        return (X - X.mean(0)) / sd
    if how == 'rows':
        sd = X.std(1, ddof=1)
        sd = np.where(sd > 0, sd, 1.0)
        return (X - X.mean(1, keepdims=True)) / sd[:, None]
    return X


def jmp_linkage(X, method):
    """scipy's linkage with the distances JMP (and SAS PROC CLUSTER) use for
    coordinate data: squared Euclidean distances between observations for
    average, single and complete linkage; the squared distance between the
    means for centroid; Ward's between-cluster sum of squares. Returns the
    linkage matrix with those heights."""
    from scipy.cluster.hierarchy import linkage
    from scipy.spatial.distance import pdist
    if method in ('single', 'complete', 'average'):
        Z = linkage(pdist(X, 'sqeuclidean'), method)
    elif method == 'centroid':
        Z = linkage(X, 'centroid')
        Z[:, 2] = Z[:, 2] ** 2
    elif method == 'ward':
        Z = linkage(X, 'ward')
        Z[:, 2] = Z[:, 2] ** 2 / 2          # scipy's Ward height is sqrt(2 x the increase in the within SS)
    else:
        raise ValueError(f'no method {method!r}')
    return Z


def partition_r2(X, Z):
    """R-square of the partition into k clusters for k = n..1, from the
    merges in Z: each merge of clusters K and L adds N_K N_L/(N_K + N_L)
    |mean_K - mean_L|^2 to the within sum of squares. Returns R2[k]."""
    n = len(X)
    Tss = float(((X - X.mean(0)) ** 2).sum())
    sums = {i: X[i].copy() for i in range(n)}
    cnt = {i: 1 for i in range(n)}
    W = 0.0
    r2 = np.full(n + 1, np.nan)
    r2[n] = 1.0
    for s, (a, b) in enumerate(Z[:, :2].astype(int)):
        ma, mb = sums[a] / cnt[a], sums[b] / cnt[b]
        W += cnt[a] * cnt[b] / (cnt[a] + cnt[b]) * float(((ma - mb) ** 2).sum())
        new = n + s
        sums[new] = sums.pop(a) + sums.pop(b)
        cnt[new] = cnt.pop(a) + cnt.pop(b)
        r2[n - s - 1] = 1 - W / Tss if Tss > 0 else np.nan
    return r2


def ccc(eigenvalues, n, q, r2):
    """Sarle's (1983) cubic clustering criterion and the approximate expected
    R-square under the uniform null hypothesis, as SAS computes them (the
    Fisher iris example of the PROC CLUSTER documentation reproduces). The
    s_j are the square roots of the eigenvalues of the covariance matrix;
    p* is the largest j < q with u_j >= 1 when c is computed from the first
    j of them."""
    s = np.sqrt(np.maximum(np.sort(np.asarray(eigenvalues, float))[::-1], 0))
    s = s[s > 0]
    p = len(s)
    if q < 2 or q >= n or p == 0:
        return float('nan'), float('nan')
    pstar = 1
    for j in range(1, min(p, q - 1) + 1):
        c = (np.prod(s[:j]) / q) ** (1 / j)
        if s[j - 1] / c >= 1:
            pstar = j
    c = (np.prod(s[:pstar]) / q) ** (1 / pstar)
    u = s / c
    b = np.sum(1 / (n + u[:pstar])) + np.sum(u[pstar:] ** 2 / (n + u[pstar:]))
    er2 = 1 - (b / np.sum(u * u)) * ((n - q) ** 2 / n) * (1 + 4 / n)
    if not np.isfinite(r2) or r2 >= 1:
        return float(er2), float('nan')
    val = math.log((1 - er2) / (1 - r2)) * math.sqrt(n * pstar / 2) / (0.001 + er2) ** 1.2
    return float(er2), float(val)


@api('hcluster.fit')
def hcluster_fit(table, columns, rows=None, method='ward', standardize='columns', label=None, two_way=False, table_name='data'):
    """Agglomerative clustering with JMP's distances. Returns the merges (for
    the dendrogram, the history and the clusters at any number, which the
    page computes), the rows, the cluster criterion and, for two-way
    clustering, the order of the columns."""
    from scipy.cluster.hierarchy import leaves_list
    cols = list(columns)
    df, _, _ = _frame(table, cols, rows)
    X = df.to_numpy(float)
    n, p = X.shape
    if n < 2:
        return {'error': 'fewer than two rows without missing values'}
    if n > 4000:
        return {'error': f'{n} rows: hierarchical clustering here takes at most 4000 rows (it keeps all n(n-1)/2 distances in memory); use K Means Cluster'}
    Xs = _standardize(X, standardize)
    Z = jmp_linkage(Xs, method)
    order = leaves_list(Z)
    r2 = partition_r2(Xs, Z)
    ev = np.linalg.eigvalsh(np.cov(Xs, rowvar=False).reshape(p, p)) if n > 1 else np.zeros(p)
    kmax = int(min(n - 1, max(10, round(n / 10))))
    crit = []
    for k in range(1, kmax + 1):
        e, cv = ccc(ev, n, k, r2[k]) if k >= 2 else (float('nan'), float('nan'))
        crit.append({'k': k, 'r2': r2[k], 'er2': e, 'ccc': cv})
    out = {'names': cols, 'n': n, 'method': method, 'standardize': standardize, 'rows': df.index.to_numpy(),
           'merges': Z[:, :2].astype(int), 'heights': Z[:, 2], 'sizes': Z[:, 3].astype(int), 'order': order,
           'criterion': crit, 'data': _mat(Xs) if two_way or n * p <= 20000 else None}
    if two_way and p >= 2:
        Zc = jmp_linkage(Xs.T, 'ward' if method in ('ward', 'centroid') else method)
        out['col_order'] = leaves_list(Zc).tolist()
        out['col_merges'] = Zc[:, :2].astype(int)
        out['col_heights'] = Zc[:, 2]
    std_line = {'columns': 'X = (X - X.mean()) / X.std()   # Standardize By: Columns', 'rows': 'X = X.sub(X.mean(1), axis=0).div(X.std(1), axis=0)   # by rows',
                'none': '# unstandardized'}.get(standardize, '')
    how = {'single': 'linkage(pdist(X, "sqeuclidean"), "single")', 'complete': 'linkage(pdist(X, "sqeuclidean"), "complete")',
           'average': 'linkage(pdist(X, "sqeuclidean"), "average")   # the average of squared distances, as JMP',
           'centroid': 'linkage(X, "centroid"); Z[:, 2] **= 2   # JMP: squared distance of the means',
           'ward': 'linkage(X, "ward"); Z[:, 2] = Z[:, 2]**2 / 2   # JMP: the increase in the within SS'}[method]
    out['code'] = '\n'.join([code_head(table_name, ['from scipy.cluster.hierarchy import linkage, fcluster, dendrogram', 'from scipy.spatial.distance import pdist']),
                             f'X = df[{_cols_expr(cols)}].dropna()', std_line, f'Z = {how}',
                             'print(fcluster(Z, 3, criterion="maxclust"))   # the clusters at 3'])
    return out


# ---- K Means Cluster -------------------------------------------------------------------------------

def _kmeanspp(X, k, rng):
    n = len(X)
    idx = [int(rng.integers(n))]
    d2 = ((X - X[idx[0]]) ** 2).sum(1)
    for _ in range(1, k):
        tot = d2.sum()
        if tot <= 0:
            cand = int(rng.integers(n))
        else:
            cand = int(rng.choice(n, p=d2 / tot))
        idx.append(cand)
        d2 = np.minimum(d2, ((X - X[cand]) ** 2).sum(1))
    return X[idx].copy()


def lloyd(X, C, w=None, max_iter=300, tol=1e-10):
    """Lloyd's k-means from the centres C. Returns (labels, centres,
    iterations, last relative change, within SS)."""
    w = np.ones(len(X)) if w is None else w
    k = len(C)
    it, change = 0, float('nan')
    scale = float(np.sqrt(((X - X.mean(0)) ** 2).sum(1).mean())) or 1.0
    xx = (X * X).sum(1)

    def dist(C):   # squared distances of every row to every centre, by one product
        return np.maximum(xx[:, None] - 2 * X @ C.T + (C * C).sum(1)[None, :], 0)
    for it in range(1, max_iter + 1):
        lab = dist(C).argmin(1)
        W = np.zeros((k, len(X)))
        W[lab, np.arange(len(X))] = w
        tot = W.sum(1)
        newC = C.copy()
        has = tot > 0
        newC[has] = (W[has] @ X) / tot[has, None]
        change = float(np.sqrt(((newC - C) ** 2).sum(1)).max()) / scale
        C = newC
        if change <= tol:
            break
    d = dist(C)
    lab = d.argmin(1)
    wss = float((w * ((X - C[lab]) ** 2).sum(1)).sum())
    return lab, C, it, change, wss


@api('kmeans.fit')
def kmeans_fit(table, columns, rows=None, k_min=3, k_max=None, standardize=True, seed=20260926, restarts=10, max_iter=300,
               weight=None, freq=None, table_name='data'):
    """k-means for each k in a range: k-means++ starts (seeded) and Lloyd's
    iterations, the best of several restarts by the within sum of squares.
    Each fit gets the cubic clustering criterion (Sarle 1983), the pseudo F
    (Calinski-Harabasz) and R-square; the clusters are numbered by size."""
    cols = list(columns)
    df, w, f = _frame(table, cols, rows, weight, freq)
    X0 = df.to_numpy(float)
    n, p = X0.shape
    kmin = max(1, int(k_min or 3))
    kmax = max(kmin, int(k_max or kmin))
    if n < kmin + 1:
        return {'error': f'{n} rows without missing values: too few for {kmin} clusters'}
    kmax = min(kmax, n - 1)
    mu = (w[:, None] * X0).sum(0) / w.sum()
    sd = np.sqrt((w[:, None] * (X0 - mu) ** 2).sum(0) / (w.sum() - 1))
    sd = np.where(sd > 0, sd, 1.0)
    X = (X0 - mu) / sd if standardize else X0.copy()
    rng = np.random.default_rng(int(seed))
    Tss = float((w[:, None] * (X - (w[:, None] * X).sum(0) / w.sum()) ** 2).sum())
    _, Sx = _wmean_cov(X, w)
    ev = np.linalg.eigvalsh(Sx)
    nobs = float(w.sum())
    fits = []
    for k in range(kmin, kmax + 1):
        best = None
        for _ in range(max(1, int(restarts))):
            C0 = _kmeanspp(X, k, rng)
            res = lloyd(X, C0, w, max_iter)
            if best is None or res[4] < best[4] - 1e-12:
                best = res
        lab, C, it, change, wss = best
        # number the clusters by decreasing size
        sizes = np.array([w[lab == j].sum() for j in range(k)])
        order = np.argsort(-sizes, kind='stable')
        remap = np.empty(k, int)
        remap[order] = np.arange(k)
        lab = remap[lab]
        C = C[order]
        r2 = 1 - wss / Tss if Tss > 0 else float('nan')
        er2, cc = ccc(ev, nobs, k, r2) if k >= 2 else (float('nan'), float('nan'))
        psf = (r2 / (k - 1)) / ((1 - r2) / (nobs - k)) if k >= 2 and r2 < 1 else float('nan')
        means, sds, counts = [], [], []
        for j in range(k):
            m = lab == j
            wj = w[m]
            counts.append(float(wj.sum()))
            if m.any():
                mj = (wj[:, None] * X0[m]).sum(0) / wj.sum()
                sj = np.sqrt((wj[:, None] * (X0[m] - mj) ** 2).sum(0) / wj.sum())
            else:
                mj, sj = np.full(p, np.nan), np.full(p, np.nan)
            means.append(mj)
            sds.append(sj)
        dist = ((X - C[lab]) ** 2).sum(1) if standardize else (((X0 - np.array(means)[lab]) / sd) ** 2).sum(1)
        fits.append({'k': k, 'labels': lab, 'counts': counts, 'means': _mat(means), 'sds': _mat(sds), 'iterations': it,
                     'criterion': change, 'wss': wss, 'r2': r2, 'er2': er2, 'ccc': cc, 'pseudo_f': psf, 'distance': dist,
                     'centers_scaled': _mat(C)})
    best = None
    vals = [(fi['ccc'], fi['k']) for fi in fits if np.isfinite(fi['ccc'])]
    if vals:
        best = max(vals)[1]
    # principal components of the clustering data for the biplots
    Cm = Sx if standardize else _wmean_cov(X0, w)[1]
    Cr = _cov_to_corr(Cm) if standardize else Cm
    evals, evecs = np.linalg.eigh(Cr)
    o = np.argsort(evals)[::-1]
    evals, evecs = evals[o], _sign_fix(evecs[:, o])
    Zb = ((X0 - mu) / sd) if standardize else (X0 - mu)
    pcs = Zb @ evecs
    out = {'names': cols, 'n': nobs, 'n_rows': n, 'rows': df.index.to_numpy(), 'fits': fits, 'best': best,
           'standardize': bool(standardize), 'mean': mu, 'sd': sd, 'seed': int(seed), 'restarts': int(restarts),
           'pca': {'eigenvalues': evals, 'vectors': _mat(evecs), 'scores': _mat(pcs[:, :min(p, 4)])}}
    out['code'] = '\n'.join([code_head(table_name, ['from scipy.cluster.vq import kmeans2']),
                             f'X = df[{_cols_expr(cols)}].dropna()',
                             'X = (X - X.mean()) / X.std()   # Columns Scaled Individually' if standardize else '',
                             f'centroids, labels = kmeans2(X.to_numpy(), {kmin}, minit="++", iter=100, rng=np.random.default_rng({int(seed)}))   # one k-means++ start; the page keeps the best of {int(restarts)}',
                             "print(np.bincount(labels), ((X.to_numpy() - centroids[labels])**2).sum())   # counts and the within SS"])
    return out


# ---- Response Screening -----------------------------------------------------------------------------

def _robust_sd(y):
    q1, q3 = np.quantile(y, [0.25, 0.75])
    iqr = q3 - q1
    rng = np.ptp(y)
    if iqr > 0 and iqr > rng / 20:
        return iqr / 1.3489795
    return float(np.std(y, ddof=1))


def _screen_pair(yv, xv, ycat, xcat, w):
    """One test of the Response Screening table. yv, xv numpy arrays (codes
    for categorical), w frequency weights or None."""
    import statsmodels.api as sm
    n = len(yv)
    cnt = float(w.sum()) if w is not None else float(n)
    r = {'count': cnt, 'test': None, 'p': None, 'effect': None, 'r2': None, 'stat': None, 'df': None}
    if n < 3:
        return r
    if not ycat:
        if np.ptp(yv) == 0:
            return r
        s_rob = _robust_sd(yv)
        if xcat:
            lv = np.unique(xv)
            if len(lv) < 2:
                return r
            if w is None:
                groups = [yv[xv == v] for v in lv]
                F, p = stats.f_oneway(*groups)
                sst = float(((yv - yv.mean()) ** 2).sum())
                ssb = float(sum(len(gv) * (gv.mean() - yv.mean()) ** 2 for gv in groups))
            else:
                D = np.column_stack([np.ones(n)] + [(xv == v).astype(float) for v in lv[1:]])
                res = sm.WLS(yv, D, weights=w).fit()
                F, p = float(res.fvalue), float(res.f_pvalue)
                ssb, sst = float(res.ess), float(res.centered_tss)
            dfm = len(lv) - 1
            r.update(test='ANOVA F', stat=float(F), df=dfm, p=float(p), r2=ssb / sst if sst > 0 else None,
                     effect=math.sqrt(ssb / dfm) / s_rob if s_rob > 0 else None)
        else:
            if np.ptp(xv) == 0:
                return r
            if w is None:
                lr = stats.linregress(xv, yv)
                r2 = float(lr.rvalue ** 2)
                p = float(lr.pvalue)
                F = r2 * (n - 2) / (1 - r2) if r2 < 1 else float('inf')
                ssm = r2 * float(((yv - yv.mean()) ** 2).sum())
            else:
                res = sm.WLS(yv, sm.add_constant(xv), weights=w).fit()
                F, p, r2, ssm = float(res.fvalue), float(res.f_pvalue), float(res.rsquared), float(res.ess)
            r.update(test='Regression F', stat=F, df=1, p=p, r2=r2, effect=math.sqrt(ssm) / s_rob if s_rob > 0 else None)
    else:
        ylv = np.unique(yv)
        if len(ylv) < 2:
            return r
        if xcat:
            xlv = np.unique(xv)
            if len(xlv) < 2:
                return r
            tab = np.zeros((len(ylv), len(xlv)))
            wv = np.ones(n) if w is None else w
            yi = np.searchsorted(ylv, yv)
            xi = np.searchsorted(xlv, xv)
            np.add.at(tab, (yi, xi), wv)
            with np.errstate(divide='ignore', invalid='ignore'):
                g2, p, dof, _ = stats.chi2_contingency(tab, correction=False, lambda_='log-likelihood')
                chi, _, _, _ = stats.chi2_contingency(tab, correction=False)
            r.update(test='ChiSquare (LR)', stat=float(g2), df=int(dof), p=float(p), effect=math.sqrt(chi / dof) if dof > 0 else None)
        else:
            if np.ptp(xv) == 0:
                return r
            Xd = sm.add_constant(xv.astype(float))
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    if len(ylv) == 2:
                        yb = (yv == ylv[1]).astype(float)
                        res = sm.GLM(yb, Xd, family=sm.families.Binomial(), freq_weights=w).fit() if w is not None else sm.Logit(yb, Xd).fit(disp=0)
                        if w is not None:
                            null = sm.GLM(yb, np.ones((n, 1)), family=sm.families.Binomial(), freq_weights=w).fit()
                            llr, dfm = 2 * (res.llf - null.llf), 1
                        else:
                            llr, dfm = float(res.llr), 1
                    else:
                        yi = np.searchsorted(ylv, yv)
                        res = sm.MNLogit(yi, Xd).fit(disp=0, method='newton', maxiter=100)
                        llr, dfm = float(res.llr), len(ylv) - 1
                p = float(stats.chi2.sf(llr, dfm))
                r.update(test='Logistic LR ChiSquare', stat=float(llr), df=dfm, p=p, effect=math.sqrt(max(llr, 0) / dfm))
            except Exception:
                return r
    return r


@api('respscreen.fit')
def respscreen_fit(table, y, x, rows=None, weight=None, freq=None, max_logworth=1000, alpha=0.05, table_name='data'):
    """Every Y against every X as Fit Y by X would test it: ANOVA or
    regression F for a continuous Y, the likelihood-ratio chi-square of the
    contingency table or of the logistic fit for a categorical one; the
    p-values adjusted to control the false discovery rate (statsmodels'
    multipletests, Benjamini-Hochberg)."""
    from statsmodels.stats.multitest import multipletests
    ys, xs = list(y), list(x)
    names = list(dict.fromkeys(ys + xs + [c for c in (weight, freq) if c]))
    df = data.frame(table, names, rows, dropna=False, as_category=True)
    wall = np.ones(len(df))
    if weight:
        wall = wall * pd.to_numeric(df[weight], errors='coerce').to_numpy(float)
    if freq:
        wall = wall * pd.to_numeric(df[freq], errors='coerce').to_numpy(float)
    okw = np.isfinite(wall) & (wall > 0)
    weighted = bool(weight or freq)
    iscat = {c: data.is_categorical(table, c) for c in names}
    codes = {}
    for c in ys + xs:
        s = df[c]
        if iscat[c]:
            cc = s.cat.codes.to_numpy() if hasattr(s, 'cat') else pd.Categorical(s).codes
            codes[c] = np.where(cc < 0, np.nan, cc.astype(float))
        else:
            codes[c] = pd.to_numeric(s, errors='coerce').to_numpy(float)
    res = []
    for yc in ys:
        for xc in xs:
            if yc == xc:
                continue
            yv, xv = codes[yc], codes[xc]
            ok = okw & np.isfinite(yv) & np.isfinite(xv)
            r = _screen_pair(yv[ok], xv[ok], iscat[yc], iscat[xc], wall[ok] if weighted else None)
            r.update(y=yc, x=xc, ytype='categorical' if iscat[yc] else 'continuous', xtype='categorical' if iscat[xc] else 'continuous')
            res.append(r)
    pv = np.array([r['p'] if r['p'] is not None else np.nan for r in res], float)
    good = np.isfinite(pv)
    fdr = np.full(len(res), np.nan)
    if good.any():
        fdr[good] = multipletests(np.clip(pv[good], 0, 1), alpha=alpha, method='fdr_bh')[1]
    cap = float(max_logworth or 1000)
    with np.errstate(divide='ignore'):
        lw = np.minimum(-np.log10(np.maximum(pv, 1e-320)), cap)
        flw = np.minimum(-np.log10(np.maximum(fdr, 1e-320)), cap)
    m = int(good.sum())
    order = np.argsort(-np.where(good, flw, -np.inf), kind='stable')
    rank = np.empty(len(res))
    rank[order] = np.arange(1, len(res) + 1)
    for i, r in enumerate(res):
        r['logworth'] = lw[i] if good[i] else None
        r['fdr_p'] = fdr[i] if good[i] else None
        r['fdr_logworth'] = flw[i] if good[i] else None
        r['rank_fraction'] = rank[i] / m if good[i] and m else None
    code = '\n'.join([code_head(table_name, ['from scipy import stats', 'from statsmodels.stats.multitest import multipletests']),
                      f'cat = {({c: bool(iscat[c]) for c in dict.fromkeys(ys + xs)})!r}   # categorical (nominal or ordinal) columns',
                      'res = []',
                      f'for y in {_cols_expr(ys)}:',
                      f'    for x in {_cols_expr(xs)}:',
                      '        if y == x: continue',
                      '        d = df[[y, x]].dropna()',
                      '        if not cat[y] and cat[x]: p = stats.f_oneway(*[g[y] for _, g in d.groupby(x)]).pvalue',
                      '        elif not cat[y]: p = stats.linregress(d[x], d[y]).pvalue',
                      '        elif cat[x]: p = stats.chi2_contingency(pd.crosstab(d[y], d[x]), correction=False, lambda_="log-likelihood")[1]',
                      '        else: p = sm.MNLogit(d[y].astype("category").cat.codes, sm.add_constant(d[x])).fit(disp=0).llr_pvalue',
                      '        res.append((y, x, p))',
                      'p = np.array([r[2] for r in res]); fdr = multipletests(p, method="fdr_bh")[1]',
                      'print(pd.DataFrame(res, columns=["Y", "X", "PValue"]).assign(LogWorth=-np.log10(p), FDR_PValue=fdr, FDR_LogWorth=-np.log10(fdr)).sort_values("FDR_LogWorth", ascending=False))'])
    return {'results': res, 'n_tests': m, 'alpha': alpha, 'code': code,
            'n_sig': int(np.sum(fdr[good] < alpha)) if m else 0, 'n_sig_raw': int(np.sum(pv[good] < alpha)) if m else 0}


# ---- Explore Outliers ----------------------------------------------------------------------------------

def _nines(v):
    """The largest all-nines number (9, 99, 999, ...) among the values, or None."""
    best = None
    for x in np.unique(v):
        if x > 0 and float(x).is_integer():
            s = str(int(x))
            if set(s) == {'9'}:
                best = x if best is None or x > best else best
    return best


@api('outliers.quantile')
def outliers_quantile(table, columns, rows=None, tail=0.1, q=3.0, integers=False, table_name='data'):
    """Quantile Range Outliers: values more than Q interquantile ranges
    below the tail quantile or above 1 - tail (quantiles as JMP's
    Distribution computes them, the (n+1)p-th order statistic)."""
    out = []
    cells = []
    nines = []
    for c in columns:
        s = data.series(table, c, rows, as_category=False)
        s = pd.to_numeric(s, errors='coerce').dropna()
        v = s.to_numpy(float)
        if len(v) < 2:
            out.append({'column': c, 'n': len(v)})
            continue
        lo_q, hi_q = np.quantile(v, [tail, 1 - tail], method='weibull')
        iqr = hi_q - lo_q
        lo_t, hi_t = lo_q - q * iqr, hi_q + q * iqr
        mask = (v < lo_t) | (v > hi_t)
        if integers:
            mask &= np.equal(np.mod(v, 1), 0)
        med = float(np.median(v))
        vals, counts = np.unique(v[mask], return_counts=True)
        out.append({'column': c, 'n': len(v), 'low_q': lo_q, 'high_q': hi_q, 'low_t': lo_t, 'high_t': hi_t,
                    'count': int(mask.sum()), 'values': [{'value': float(a), 'count': int(b)} for a, b in zip(vals, counts)],
                    'rows': s.index.to_numpy()[mask], 'low_rows': s.index.to_numpy()[v < lo_t], 'high_rows': s.index.to_numpy()[v > hi_t]})
        for r_, x in zip(s.index.to_numpy()[mask], v[mask]):
            cells.append({'column': c, 'row': int(r_), 'value': float(x), 'distance': (x - med) / iqr if iqr > 0 else None})
        nn = _nines(v)
        if nn is not None and nn > hi_q:
            nines.append({'column': c, 'value': nn, 'count': int(np.sum(v == nn)), 'high_q': hi_q, 'rows': s.index.to_numpy()[v == nn]})
    code = '\n'.join([code_head(table_name), f'for c in {_cols_expr(list(columns))}:',
                      '    v = df[c].dropna()',
                      f'    lo, hi = np.quantile(v, [{tail}, {1 - tail}], method="weibull"); iqr = hi - lo',
                      f'    print(c, v[(v < lo - {q} * iqr) | (v > hi + {q} * iqr)].tolist())'])
    return {'columns': out, 'cells': cells, 'nines': nines, 'tail': tail, 'q': q, 'code': code}


@api('outliers.robust')
def outliers_robust(table, columns, rows=None, method='huber', k=4.0, table_name='data'):
    """Robust Fit Outliers: a robust centre and spread per column (Huber's
    M-estimates from statsmodels, a Cauchy maximum-likelihood fit from
    scipy, or the median and IQR/1.34898), outliers beyond K spreads."""
    from statsmodels.robust.scale import Huber
    out, cells = [], []
    for c in columns:
        s = pd.to_numeric(data.series(table, c, rows, as_category=False), errors='coerce').dropna()
        v = s.to_numpy(float)
        if len(v) < 3:
            out.append({'column': c, 'n': len(v)})
            continue
        center = spread = float('nan')
        try:
            if method == 'cauchy':
                center, spread = stats.cauchy.fit(v)
            elif method == 'quartile':
                q1, med, q3 = np.quantile(v, [0.25, 0.5, 0.75], method='weibull')
                center, spread = med, (q3 - q1) / 1.34898
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    loc, sc = Huber(maxiter=100)(v)
                center, spread = float(np.asarray(loc).item()), float(np.asarray(sc).item())
        except Exception:
            q1, med, q3 = np.quantile(v, [0.25, 0.5, 0.75])
            center, spread = med, (q3 - q1) / 1.34898
        lo_t, hi_t = center - k * spread, center + k * spread
        mask = (v < lo_t) | (v > hi_t)
        vals, counts = np.unique(v[mask], return_counts=True)
        out.append({'column': c, 'n': len(v), 'center': center, 'spread': spread, 'low_t': lo_t, 'high_t': hi_t, 'count': int(mask.sum()),
                    'values': [{'value': float(a), 'count': int(b)} for a, b in zip(vals, counts)], 'rows': s.index.to_numpy()[mask]})
        for r_, x in zip(s.index.to_numpy()[mask], v[mask]):
            cells.append({'column': c, 'row': int(r_), 'value': float(x), 'distance': (x - center) / spread if spread > 0 else None})
    fn = {'huber': 'Huber()(v)   # statsmodels.robust.scale.Huber: (location, scale)', 'cauchy': 'stats.cauchy.fit(v)',
          'quartile': 'np.median(v), stats.iqr(v) / 1.34898'}[method if method in ('huber', 'cauchy', 'quartile') else 'huber']
    code = '\n'.join([code_head(table_name, ['from scipy import stats', 'from statsmodels.robust.scale import Huber']),
                      f'for c in {_cols_expr(list(columns))}:', '    v = df[c].dropna().to_numpy()', f'    center, spread = {fn}',
                      f'    print(c, v[np.abs(v - center) > {k} * spread])'])
    return {'columns': out, 'cells': cells, 'method': method, 'k': k, 'code': code}


def _mcd_raw(X, h, rng, n_starts=500, n_best=10):
    """FAST-MCD (Rousseeuw and Van Driessen 1999): C-steps from random
    (p+1)-subsets; returns (mean, cov, subset, log det)."""
    n, p = X.shape

    def cstep(idx, steps):
        m = X[idx].mean(0)
        S = np.cov(X[idx], rowvar=False).reshape(p, p)
        ld = None
        for _ in range(steps):
            sg, ld_ = np.linalg.slogdet(S)
            if sg <= 0:
                return idx, m, S, -np.inf
            d = np.einsum('ij,jk,ik->i', X - m, np.linalg.inv(S), X - m)
            new = np.argsort(d, kind='stable')[:h]
            m2 = X[new].mean(0)
            S2 = np.cov(X[new], rowvar=False).reshape(p, p)
            sg2, ld2 = np.linalg.slogdet(S2)
            if sg2 <= 0:
                return new, m2, S2, -np.inf
            same = set(new.tolist()) == set(idx.tolist())
            idx, m, S, ld = new, m2, S2, ld2
            if same:
                break
        if ld is None:
            sg, ld = np.linalg.slogdet(S)
        return idx, m, S, ld

    starts = []
    for _ in range(n_starts):
        sub = rng.choice(n, p + 1, replace=False)
        S = np.cov(X[sub], rowvar=False).reshape(p, p)
        tries = 0
        while np.linalg.matrix_rank(S) < p and len(sub) < n and tries < n:
            extra = rng.choice(np.setdiff1d(np.arange(n), sub), 1)
            sub = np.concatenate([sub, extra])
            S = np.cov(X[sub], rowvar=False).reshape(p, p)
            tries += 1
        m = X[sub].mean(0)
        try:
            d = np.einsum('ij,jk,ik->i', X - m, np.linalg.pinv(S), X - m)
        except np.linalg.LinAlgError:
            continue
        idx = np.argsort(d, kind='stable')[:h]
        starts.append(cstep(idx, 2))
    starts = [s for s in starts if np.isfinite(s[3])]
    if not starts:
        raise ValueError('every subset is singular')
    starts.sort(key=lambda s: s[3])
    best = None
    seen = set()
    for idx, m, S, ld in starts[:n_best * 3]:
        key = tuple(sorted(idx.tolist()))
        if key in seen:
            continue
        seen.add(key)
        res = cstep(idx, 100)
        if best is None or res[3] < best[3]:
            best = res
        if len(seen) >= n_best:
            break
    return best[1], best[2], best[0], best[3]


def mcd(X, seed=20260926, alpha_h=None):
    """The reweighted minimum covariance determinant estimate of location
    and scatter: FAST-MCD with h = (n + p + 1)//2, the consistency factor
    for the normal model, then one reweighting step with the rows whose
    squared robust distance is below the 0.975 chi-square quantile."""
    X = np.asarray(X, float)
    n, p = X.shape
    h = (n + p + 1) // 2 if alpha_h is None else int(alpha_h * n)
    rng = np.random.default_rng(seed)
    if n > 1500:
        sub = rng.choice(n, 1500, replace=False)
        m0, S0, idx0, _ = _mcd_raw(X[sub], (1500 + p + 1) // 2, rng)
        d = np.einsum('ij,jk,ik->i', X - m0, np.linalg.inv(S0), X - m0)
        idx = np.argsort(d, kind='stable')[:h]
        for _ in range(100):
            m = X[idx].mean(0)
            S = np.cov(X[idx], rowvar=False)
            d = np.einsum('ij,jk,ik->i', X - m, np.linalg.inv(S), X - m)
            new = np.argsort(d, kind='stable')[:h]
            if set(new.tolist()) == set(idx.tolist()):
                break
            idx = new
        m_raw, S_raw = X[idx].mean(0), np.cov(X[idx], rowvar=False).reshape(p, p)
    else:
        m_raw, S_raw, idx, _ = _mcd_raw(X, h, rng)
    frac = h / n
    cons = frac / stats.chi2.cdf(stats.chi2.ppf(frac, p), p + 2)
    S_raw = S_raw * cons
    d2 = np.einsum('ij,jk,ik->i', X - m_raw, np.linalg.inv(S_raw), X - m_raw)
    keep = d2 <= stats.chi2.ppf(0.975, p)
    m_rw = X[keep].mean(0)
    S_rw = np.cov(X[keep], rowvar=False).reshape(p, p)
    delta = keep.mean()
    cons2 = delta / stats.chi2.cdf(stats.chi2.ppf(delta, p), p + 2) if delta < 1 else 1.0
    S_rw = S_rw * cons2
    return {'mean': m_rw, 'cov': S_rw, 'raw_mean': m_raw, 'raw_cov': S_raw, 'subset': np.sort(idx), 'h': h}


@api('outliers.multivariate')
def outliers_multivariate(table, columns, rows=None, alpha=0.05, seed=20260926, table_name='data'):
    """Multivariate Robust Outliers: robust Mahalanobis distances from the
    reweighted MCD (FAST-MCD in numpy) beside the classical ones, with the
    square root of the chi-square quantile as the limit."""
    cols = list(columns)
    df, _, _ = _frame(table, cols, rows)
    X = df.to_numpy(float)
    n, p = X.shape
    if p < 1 or n < 2 * p + 2:
        return {'error': f'{n} rows without missing values: too few for a robust estimate in {p} dimensions'}
    try:
        est = mcd(X, seed)
    except (ValueError, np.linalg.LinAlgError) as e:
        return {'error': f'no robust estimate: {e}'}
    rd = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', X - est['mean'], np.linalg.pinv(est['cov']), X - est['mean']), 0))
    md = _mahal(X - X.mean(0), np.cov(X, rowvar=False).reshape(p, p))
    lim = math.sqrt(stats.chi2.ppf(1 - alpha, p))
    code = '\n'.join([code_head(table_name, ['from scipy import stats']), f'X = df[{_cols_expr(cols)}].dropna().to_numpy(); p = X.shape[1]',
                      'e = X - X.mean(0); md = np.sqrt(np.einsum("ij,jk,ik->i", e, np.linalg.inv(np.cov(X, rowvar=False)), e))   # classical',
                      f'limit = np.sqrt(stats.chi2.ppf({1 - alpha:g}, p)); print(md[:5], limit)',
                      '# the robust distances replace the mean and covariance by the reweighted minimum covariance determinant',
                      '# estimate (FAST-MCD); with scikit-learn: from sklearn.covariance import MinCovDet',
                      '# rd = np.sqrt(MinCovDet(random_state=0).fit(X).mahalanobis(X))'])
    return {'rows': df.index.to_numpy(), 'robust': rd, 'classical': md, 'limit': lim, 'alpha': alpha, 'n': n, 'p': p, 'h': est['h'],
            'mean': est['mean'], 'cov': _mat(est['cov']), 'count': int(np.sum(rd > lim)), 'code': code}


def _robust_scale_cols(X):
    """JMP's scaling for k nearest neighbours: centre at the median, divide by
    max(Q3 - median, median - Q1)/z(0.75), moving to more extreme quantiles
    while that is zero."""
    Z = np.empty_like(X)
    z75 = stats.norm.ppf(0.75)
    for j in range(X.shape[1]):
        v = X[:, j]
        med = np.median(v)
        s = 0.0
        for lo, hi in ((0.25, 0.75), (0.1, 0.9), (0.05, 0.95), (0.01, 0.99), (0.0, 1.0)):
            ql, qh = np.quantile(v, [lo, hi])
            s = max(qh - med, med - ql) / stats.norm.ppf(hi)
            if s > 0:
                break
        s = s if s > 0 else 1.0
        Z[:, j] = (v - med) / s
    return Z


@api('outliers.knn')
def outliers_knn(table, columns, rows=None, k=8, table_name='data'):
    """Multivariate k-Nearest Neighbor Outliers: the distance from each row to
    its kth nearest neighbour for k = 1, 2, 3, 5, 8, ... up to K (scipy's
    cKDTree), on robustly centred and scaled columns."""
    from scipy.spatial import cKDTree
    cols = list(columns)
    df, _, _ = _frame(table, cols, rows)
    X = df.to_numpy(float)
    n = len(X)
    K = int(max(1, min(int(k), n - 1)))
    if n < 3:
        return {'error': 'fewer than three rows without missing values'}
    Z = _robust_scale_cols(X)
    tree = cKDTree(Z)
    dist, _ = tree.query(Z, k=K + 1)
    fib = [1, 2]
    while fib[-1] + fib[-2] <= K:
        fib.append(fib[-1] + fib[-2])
    ks = sorted({x for x in [1, 2, 3] + fib if x <= K})
    code = '\n'.join([code_head(table_name, ['from scipy.spatial import cKDTree']), f'X = df[{_cols_expr(cols)}].dropna().to_numpy()',
                      'med = np.median(X, 0); q1, q3 = np.quantile(X, [0.25, 0.75], axis=0)',
                      'X = (X - med) / (np.maximum(q3 - med, med - q1) / 0.6744897501960817)   # centred at the median, scaled robustly',
                      f'd, _ = cKDTree(X).query(X, k={K + 1}); print(d[:, 1:])   # distance to the 1st..{K}th neighbour'])
    return {'rows': df.index.to_numpy(), 'ks': ks, 'dist': {str(kk): dist[:, kk] for kk in ks}, 'K': K, 'code': code}


# ---- Multiple Correspondence Analysis ------------------------------------------------------------------

@api('mca.fit')
def mca_fit(table, columns, rows=None, freq=None, table_name='data'):
    """Multiple correspondence analysis: the singular value decomposition of
    the standardized residuals of the indicator matrix (numpy), with the
    principal inertias, Greenacre's and Benzecri's adjusted inertias, the
    principal coordinates of the levels and of the rows, the levels'
    masses, qualities and inertias, and the Burt table."""
    cols = list(columns)
    names = cols + ([freq] if freq else [])
    df = data.frame(table, names, rows, dropna=True, as_category=True)
    f = pd.to_numeric(df[freq], errors='coerce').to_numpy(float) if freq else np.ones(len(df))
    ok = np.isfinite(f) & (f > 0)
    df, f = df[ok], f[ok]
    n, Q = len(df), len(cols)
    if Q < 2 or n < 2:
        return {'error': 'needs two or more categorical columns and two or more rows without missing values'}
    blocks, levels = [], []
    for c in cols:
        s = df[c]
        cats = list(s.cat.categories) if hasattr(s, 'cat') else sorted(s.unique())
        present = [lv for lv in cats if (s == lv).any()]
        codes = np.array([present.index(v) for v in s])
        B = np.zeros((n, len(present)))
        B[np.arange(n), codes] = 1
        blocks.append(B)
        levels += [{'column': c, 'level': _level_value(lv)} for lv in present]
    Z = np.hstack(blocks)
    Jn = Z.shape[1]
    N = float((Z * f[:, None]).sum())
    P = Z * f[:, None] / N
    r, c = P.sum(1), P.sum(0)
    S = (P - np.outer(r, c)) / np.sqrt(np.outer(r, c))
    U, sv, Vt = np.linalg.svd(S, full_matrices=False)
    K = int(min(Jn - Q, n - 1, len(sv)))
    if K < 1:
        return {'error': 'every column has one level: nothing to analyse'}
    sv, U, V = sv[:K], U[:, :K], Vt.T[:, :K]
    G = V * sv / np.sqrt(c)[:, None]          # principal coordinates of the levels
    F = U * sv / np.sqrt(r)[:, None]          # principal coordinates of the rows
    sg = np.where(G[np.argmax(np.abs(G), axis=0), np.arange(K)] < 0, -1.0, 1.0)
    G, F = G * sg, F * sg
    lam = sv ** 2
    total = float(lam.sum())
    # Benzecri's adjustment of the inertias above 1/Q (Greenacre 1984, p. 145),
    # and Greenacre's total to take percentages of. The inertias are those of
    # the indicator matrix, which are the singular values of the Burt table's
    # analysis: JMP's Inertia column; its Singular Value is their square root.
    adj = np.where(lam > 1 / Q, (Q / (Q - 1)) ** 2 * (lam - 1 / Q) ** 2, 0.0)
    g_total = Q / (Q - 1) * (float((lam ** 2).sum()) - (Jn - Q) / Q ** 2)
    d2 = (G ** 2).sum(1)
    for i, lv in enumerate(levels):
        lv.update(mass=float(c[i]), inertia=float(c[i] * d2[i] / total) if total > 0 else None,
                  quality=float((G[i, :min(2, K)] ** 2).sum() / d2[i]) if d2[i] > 0 else None,
                  coords=G[i].tolist(), contrib=(c[i] * G[i] ** 2 / lam).tolist())
    Zw = Z * f[:, None]
    burt = Z.T @ Zw
    code = '\n'.join([code_head(table_name), f'X = df[{_cols_expr(cols)}].dropna().astype(str)',
                      'Z = pd.get_dummies(X).to_numpy(float); P = Z / Z.sum(); r, c = P.sum(1), P.sum(0)',
                      'S = (P - np.outer(r, c)) / np.sqrt(np.outer(r, c)); U, s, Vt = np.linalg.svd(S, full_matrices=False)',
                      f'k = Z.shape[1] - {Q}; inertia = s[:k]**2; print(s[:k], inertia, 100 * inertia / inertia.sum())',
                      'G = Vt.T[:, :k] * s[:k] / np.sqrt(c)[:, None]   # principal coordinates of the levels (sign arbitrary)'])
    return {'names': cols, 'n': float(f.sum()), 'n_rows': n, 'Q': Q, 'J': Jn, 'K': K, 'levels': levels, 'singular': sv, 'inertia': lam,
            'percent': 100 * lam / total if total > 0 else lam * 0, 'cum': 100 * np.cumsum(lam) / total if total > 0 else lam * 0,
            'total_inertia': total, 'adjusted': {'greenacre': adj, 'greenacre_pct': 100 * adj / g_total if g_total > 0 else adj * 0,
                                                 'benzecri_pct': 100 * adj / adj.sum() if adj.sum() > 0 else adj * 0, 'greenacre_total': g_total},
            'rows': df.index.to_numpy(), 'row_coords': _mat(F[:, :min(K, 4)]), 'burt': _mat(burt), 'code': code}


# ---- Multidimensional Scaling ----------------------------------------------------------------------------

@api('mds.fit')
def mds_fit(table, columns, rows=None, standardize=True, matrix=False, label=None, seed=20260926, table_name='data'):
    """Classical (Torgerson) multidimensional scaling in numpy: the
    eigenvectors of the doubly centred squared distances. The distances are
    Euclidean between the rows (the columns standardized or not), or the
    columns themselves when they are a distance matrix (as many columns as
    rows). Returns the coordinates, the eigenvalues, Kruskal's stress for
    two dimensions and a Shepard diagram."""
    from scipy.spatial.distance import pdist, squareform
    cols = list(columns)
    df, _, _ = _frame(table, cols, rows, dropna=not matrix)
    if matrix:
        D = df.to_numpy(float)
        if D.shape[0] != D.shape[1]:
            return {'error': f'a distance matrix needs as many rows as columns: {D.shape[0]} rows, {D.shape[1]} columns'}
        D = np.where(np.isfinite(D), D, np.nan)
        D = np.where(np.isnan(D), D.T, D)
        if np.isnan(D).any():
            return {'error': 'the distance matrix has missing values on both sides of the diagonal'}
        D = (D + D.T) / 2
        np.fill_diagonal(D, 0)
        if (D < 0).any():
            return {'error': 'negative distances'}
    else:
        X = df.to_numpy(float)
        if standardize:
            sd = X.std(0, ddof=1)
            X = (X - X.mean(0)) / np.where(sd > 0, sd, 1.0)
        D = squareform(pdist(X))
    n = len(D)
    if n < 3:
        return {'error': 'fewer than three objects'}
    Jc = np.eye(n) - 1 / n
    B = -0.5 * Jc @ (D ** 2) @ Jc
    ev, V = np.linalg.eigh(B)
    o = np.argsort(ev)[::-1]
    ev, V = ev[o], V[:, o]
    pos = ev > 1e-10 * max(1.0, abs(ev[0]))
    kmax = int(min(pos.sum(), 4))
    if kmax < 1:
        return {'error': 'no positive eigenvalues'}
    Xc = _sign_fix(V[:, :kmax]) * np.sqrt(ev[:kmax])
    iu = np.triu_indices(n, 1)
    d = D[iu]
    k2 = min(2, kmax)
    dh = squareform(pdist(Xc[:, :k2]))[iu]
    stress = float(math.sqrt(((d - dh) ** 2).sum() / (d ** 2).sum())) if (d ** 2).sum() > 0 else float('nan')
    r2 = float(np.corrcoef(d, dh)[0, 1] ** 2) if len(d) > 1 and np.std(dh) > 0 else float('nan')
    take = np.arange(len(d))
    if len(d) > 3000:
        take = np.sort(np.random.default_rng(seed).choice(len(d), 3000, replace=False))
    tol = 1e-10 * max(1.0, abs(ev[0]))
    evp = ev[ev > tol]
    neg = ev[ev < -tol]
    code = '\n'.join([code_head(table_name, ['from scipy.spatial.distance import pdist, squareform']),
                      f'X = df[{_cols_expr(cols)}]' + ('.to_numpy(); D = (X + X.T) / 2   # the columns are the distance matrix' if matrix else '.dropna()'),
                      '' if matrix else ('X = (X - X.mean()) / X.std()   # standardized columns' if standardize else ''),
                      '' if matrix else 'D = squareform(pdist(X))',
                      'n = len(D); J = np.eye(n) - 1 / n; B = -0.5 * J @ (D**2) @ J',
                      'ev, V = np.linalg.eigh(B); o = np.argsort(ev)[::-1]; ev, V = ev[o], V[:, o]',
                      'coords = V[:, :2] * np.sqrt(ev[:2]); print(ev[:4], coords[:5])   # classical MDS (sign arbitrary)'])
    return {'names': cols, 'n': n, 'rows': df.index.to_numpy(), 'coords': _mat(Xc), 'eigenvalues': evp[:20], 'percent': 100 * evp[:20] / evp.sum(),
            'k': kmax, 'stress': stress, 'r2': r2, 'shepard': {'d': d[take], 'dhat': dh[take]}, 'n_pairs': int(len(d)), 'matrix': bool(matrix),
            'negative': float(-neg.sum() / np.abs(ev).sum()) if len(neg) else 0.0, 'code': code}
