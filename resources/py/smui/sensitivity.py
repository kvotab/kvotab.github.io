"""Analyze > Screening > Sensitivity Analysis: which inputs an output depends on.

A Monte Carlo sample is a table: a row per realisation, the inputs drawn for
it and the outputs it gave. This reads such a table as it is, with no model
runs of its own:

    Measures            Pearson's and Spearman's correlations of each input
                        with the output; the standardized regression
                        coefficients (SRC) and partial correlation
                        coefficients (PCC) of the regression of the output on
                        every input, and their rank forms (SRRC, PRCC), with
                        the R² of each regression; a first-order index S1
                        estimated by binning the input
    Distribution-based  EASI's first-order index, Borgonovo's
                        moment-independent δ, PAWN, mutual information above
                        chance, and each input's share of the discrepancy
    Regional            the realisations above a threshold against the rest,
                        and the Kolmogorov-Smirnov distance between each
                        input's two distributions, with dummy inputs for what
                        chance alone gives

These are the measures of Kompartment's What drove it, computed as there:
ported from kompartment/src/domain/sensitivity.js, gsa.js (GlobalSensitivity.jl)
and salib.js (SALib), and test_sensitivity.py checks each against those
functions on the same samples, the random draws handed to both. The
estimators are plain functions of numpy arrays, and a report's code prints
their source, so the code gives the report's numbers.

δ is read on the output's normal scores and mutual information on ranks, as
there: neither changes under a monotone transformation of the output, and on
an output that spans decades a kernel density on a linear grid, or
equal-width bins, cannot resolve it. EASI and S1 are shares of the variance,
which does change, and read the values (or their logarithms, Log Output).
"""
import inspect
import json
import math

import numpy as np
from scipy import linalg, stats
from scipy.stats import qmc

from . import data
from .registry import api
from .util import code_head, one_line

J = json.dumps
BASE, OTHER = '#2f6690', '#3a7d44'   # the page's points, and the realisations at or below a threshold (light theme)
SEED = 1                   # the default seed of the bootstraps, shuffles and dummy inputs
BOOTS = 100                # δ's bootstrap resamples and mutual information's shuffles
DUMMIES = 10               # the regional analysis's dummy inputs
MIN_ROWS = 10              # realisations an output needs, at least
MIN_DISTRIBUTION = 20      # ... for the distribution-based measures
DISCREPANCY_WORK = 4e8     # inputs × realisations²: the discrepancy costs the square of the sample


# ---------------------------------------------------------------------------
# the estimators (their source is in the code under each result)
# ---------------------------------------------------------------------------

def regression_measures(X, y):
    """The standardized regression coefficients (SRC), the partial correlation
    coefficients (PCC) and the R² of the least-squares fit of y on every
    column of X. With every column standardized, SRC_k is the coefficient
    beta_k, and PCC_k = beta_k / sqrt(beta_k² + (1 - R²) (R⁻¹)_kk), R the
    inputs' correlation matrix, with beta_k's sign. A constant column gets
    NaN; all do when R is singular (two inputs that are the same numbers) or
    there are too few rows. On ranks they are SRRC and PRCC."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    m, K = X.shape
    src, pcc = np.full(K, np.nan), np.full(K, np.nan)
    sd = X.std(axis=0, ddof=1) if m > 1 else np.zeros(K)
    use = np.flatnonzero(sd > 0)
    sy = y.std(ddof=1) if m > 1 else 0.0
    if m < 4 or not sy > 0 or not 0 < len(use) < m - 1:
        return src, pcc, np.nan
    Z = (X[:, use] - X[:, use].mean(axis=0)) / sd[use]
    zy = (y - y.mean()) / sy
    R = Z.T @ Z / (m - 1)
    r = Z.T @ zy / (m - 1)
    try:
        L = np.linalg.cholesky(R)
    except np.linalg.LinAlgError:
        return src, pcc, np.nan
    if np.min(np.diag(L)) ** 2 <= 1e-10:      # singular for the purpose
        return src, pcc, np.nan
    Rinv = linalg.cho_solve((L, True), np.eye(len(use)))
    beta = Rinv @ r
    r2 = float(r @ beta)
    denom = beta ** 2 + max(0.0, 1 - r2) * np.diag(Rinv)
    src[use] = beta
    pcc[use] = np.sign(beta) * np.sqrt(np.divide(beta ** 2, denom, out=np.zeros_like(beta), where=denom > 0))
    return src, pcc, r2


def first_order_index(x, y, bins=None):
    """S1 = Var(E[y | x]) / Var(y), estimated by binning: the rows sorted by x
    and cut into bins of equal count (the square root of the rows, 4 to 50),
    the variance of the bin means over the variance of y, less the bins/n
    that the noise in the bin means adds on average, within [0, 1]. NaN for
    fewer than 10 rows or a constant x."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    m = len(x)
    if m < 10:
        return np.nan
    order = np.argsort(x, kind='stable')
    if x[order[0]] == x[order[-1]]:
        return np.nan
    mean = y.mean()
    total = np.mean((y - mean) ** 2)
    if not total > 0:
        return np.nan
    B = bins or max(4, min(50, math.floor(math.sqrt(m) + 0.5)))
    ys = y[order]
    between = 0.0
    for b in range(B):
        lo, hi = b * m // B, (b + 1) * m // B
        if hi > lo:
            between += (hi - lo) * (ys[lo:hi].mean() - mean) ** 2
    return float(min(1.0, max(0.0, between / m / total - B / m)))


def easi(x, y, harmonics=4):
    """EASI (Plischke 2010), a first-order index from any sample: the outputs
    in the order of x, folded into a triangle (the even places going up, the
    odd ones coming back down) so that they are periodic in x, and the share
    of their power in the first harmonics; then less the bias a random sample
    leaves in that (Tissot and Prieur 2012). Returns (S1, corrected S1)."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    ys = y[np.argsort(np.asarray(x, dtype=float), kind='stable')]
    folded = np.concatenate([ys[0::2], ys[1::2][::-1]])
    F = np.fft.rfft(folded - folded.mean())
    P = F.real ** 2 + F.imag ** 2
    top = len(P) - 2
    s = P[1:min(harmonics, top) + 1].sum() / P[1:top + 1].sum()
    lam = 2 * harmonics / n
    return float(s), float(s - lam / (1 - lam) * (1 - s))


def kde_bandwidth(v, fallback=None):
    """Silverman's rule, 0.9 min(sd, IQR/1.34) n^(-1/5), as KernelDensity.jl
    has it. A sample with no spread takes fallback (the whole output's)."""
    n = len(v)
    if n <= 1:
        return 0.9 if fallback is None else fallback
    sd = np.std(v, ddof=1)
    width = min(sd, (np.quantile(v, 0.75) - np.quantile(v, 0.25)) / 1.34)
    if width == 0:
        if sd == 0 and fallback is not None:
            return fallback
        width = sd if sd > 0 else 1.0
    return 0.9 * width * n ** -0.2


def kde(v, npoints=2048, fallback=None):
    """A Gaussian kernel density estimate as KernelDensity.jl makes one: the
    values binned linearly onto npoints points from 4 bandwidths below the
    least to 4 above the greatest, smoothed in Fourier space, and a quadratic
    B-spline through that (Interpolations.jl's) to read it anywhere.
    Returns (lo, hi, step, spline coefficients)."""
    v = np.asarray(v, dtype=float)
    bw = kde_bandwidth(v, fallback)
    lo, hi = v.min() - 4 * bw, v.max() + 4 * bw
    s = (hi - lo) / (npoints - 1)
    mid = lo + np.arange(npoints) * s
    mid[-1] = hi
    k = np.searchsorted(mid, v)                 # the first point at or above each value
    ainc, w = 1 / (s * s), 1 / len(v)
    grid = np.bincount(k - 1, (mid[k] - v) * ainc * w, npoints) + np.bincount(k, (v - mid[k - 1]) * ainc * w, npoints)
    f = np.fft.rfft(grid)
    t = np.arange(len(f)) * (-2 * np.pi / (s * npoints))
    dens = np.maximum(np.fft.irfft(f * np.exp(-bw * bw / 2 * t * t), npoints), 0)
    # the spline's coefficients, one more at each end: c[0] and c[n + 1]
    # from the second derivative at the ends being zero
    c = np.empty(npoints + 2)
    c[1], c[npoints] = dens[0], dens[-1]
    rhs = dens[1:-1].copy()
    rhs[0] -= c[1] / 8
    rhs[-1] -= c[npoints] / 8
    band = np.array([np.full(npoints - 2, 0.125), np.full(npoints - 2, 0.75), np.full(npoints - 2, 0.125)])
    c[2:npoints] = linalg.solve_banded((1, 1), band, rhs)
    c[0], c[npoints + 1] = 2 * c[1] - c[2], 2 * c[npoints] - c[npoints - 1]
    return lo, hi, s, c


def kde_pdf(k, xs):
    """The density estimate k (from kde) at xs, zero outside its grid."""
    lo, hi, s, c = k
    n = len(c) - 2
    xs = np.asarray(xs, dtype=float)
    out = np.zeros(len(xs))
    inside = (xs >= lo) & (xs <= hi)
    xi = (xs[inside] - lo) / s + 1
    xm = np.where(xi < n + 0.5, np.floor(xi + 0.5), np.ceil(xi + 0.5) - 1).astype(int)
    d = xi - xm
    out[inside] = (d - 0.5) ** 2 / 2 * c[xm - 1] + (0.75 - d * d) * c[xm] + (d + 0.5) ** 2 / 2 * c[xm + 1]
    return out


def delta_classes(n):
    """The classes the input is cut into for δ (Plischke, Borgonovo and Smith 2013), at most 48."""
    e = 2 / (7 + math.tanh((1500 - n) / 500))
    return min(math.ceil(n ** e), 48)


def delta_once(x, y, ygrid, cut):
    """δ of one sample: half the mean (over the classes of x, by its ranks) of
    the area between y's density and its density in the class."""
    if np.all(y == y[0]):
        return 0.0
    fallback = kde_bandwidth(y)
    fy = kde_pdf(kde(y), ygrid)
    rank = stats.rankdata(x, method='min')
    total = 0.0
    for j in range(len(cut) - 1):
        members = y[(rank > cut[j]) & (rank <= cut[j + 1])]
        if len(members):
            diff = np.abs(fy - kde_pdf(kde(members, fallback=fallback), ygrid))
            total += len(members) * np.sum(np.diff(ygrid) * (diff[:-1] + diff[1:])) / 2
    return total / (2 * len(y))


def delta_moment(x, y, rng=None, boots=100, conf=0.95, grid=2048, resamples=None):
    """Borgonovo's moment-independent δ: how far knowing x moves y's whole
    distribution, estimated from a sample as Plischke, Borgonovo and Smith
    (2013) do (and GlobalSensitivity.jl): the bias a bootstrap measures taken
    off, and an interval around that. Returns (δ, adjusted δ, low, high)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(y)
    M = delta_classes(n)
    cut = np.arange(M + 1) * n / M
    ygrid = np.linspace(y.min(), y.max(), grid)
    delta = delta_once(x, y, ygrid, cut)
    if resamples is None:
        resamples = rng.integers(0, n, size=(boots, n))
    if not len(resamples):
        return delta, delta, np.nan, np.nan
    bs = np.array([delta_once(x[r], y[r], ygrid, cut) for r in resamples])
    adjusted = 2 * delta - bs.mean()
    band = stats.norm.ppf(0.5 + conf / 2) * bs.std(ddof=1) / math.sqrt(len(bs))
    return delta, adjusted, adjusted - band, adjusted + band


def mutual_information(x, y, rng=None, boots=100, conf=0.95, shuffles=None):
    """Mutual information in bits, from histograms of the square root of n
    bins a side (as ComplexityMeasures.jl bins them); its chance level, the
    conf quantile of the same with y shuffled; and what is above that.
    Returns (mutual information, chance level, above chance)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(y)
    bins = math.floor(math.sqrt(n) + 0.5)

    def binned(v):   # bins of equal width, the top edge two floats above the greatest value
        top = np.nextafter(np.nextafter(v.max(), np.inf), np.inf)
        return np.floor((v - v.min()) / ((top - v.min()) / bins)).astype(np.int64)

    def entropy(keys):
        p = np.unique(keys, return_counts=True)[1] / n
        return float(-np.sum(p * np.log2(p)))

    bx, by = binned(x), binned(y)
    hx, hy = entropy(bx), entropy(by)
    mi = hx + hy - entropy(bx * (bins + 2) + by)
    if shuffles is None:
        shuffles = [rng.permutation(n) for _ in range(boots)]
    nulls = np.array([hx + hy - entropy(bx * (bins + 2) + by[s]) for s in shuffles])
    bound = float(np.quantile(nulls, conf)) if len(nulls) else np.nan
    return mi, bound, max(0.0, mi - bound)


def pawn(x, y, slides=10):
    """PAWN (Pianosi and Wagener 2015, 2018): x cut by its quantiles into
    slides slices of equal count, and in each the Kolmogorov-Smirnov distance
    between y's distribution there and its distribution overall; the
    statistics of those distances across the slices (the median is the one
    reported)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    edges = np.quantile(x, np.minimum(1, np.arange(slides + 1) * (1 / slides)))
    ks = []
    for s in range(slides):
        inside = (x >= edges[s]) & (x < edges[s + 1])   # half open, as SALib's: the largest x is in none
        if inside.any():
            ks.append(stats.ks_2samp(y[inside], y).statistic)
    ks = np.array(ks)
    return {'minimum': ks.min(), 'mean': ks.mean(), 'median': np.median(ks), 'maximum': ks.max(), 'stdev': ks.std(), 'cv': ks.std() / ks.mean()}


def discrepancy_shares(X, y, method='WD'):
    """Each input's share of the discrepancy (Puy, Roy and Saltelli 2022, as
    SALib computes it): the discrepancy of the points (input, output), each
    on its ranks over n less a half, the output's then scaled onto [0, 1],
    over the sum of every input's. An input the output does not depend on
    spreads the points evenly over the square, and has a small one."""
    X = np.asarray(X, dtype=float)
    n = len(y)
    v = (stats.rankdata(y) - 0.5) / n
    v = (v - v.min()) / (v.max() - v.min())
    raw = np.array([qmc.discrepancy(np.column_stack([(stats.rankdata(X[:, k]) - 0.5) / n, v]), method=method) for k in range(X.shape[1])])
    return raw / raw.sum()


def regional(X, y, threshold, rng, dummies=10):
    """Regional sensitivity analysis (Monte Carlo filtering, Hornberger and
    Spear 1981): the rows whose output is above the threshold against the
    rest, and for each input the Kolmogorov-Smirnov distance between its two
    distributions with the p-value of the two-sample test. Dummy inputs,
    uniform draws the output never saw, say how far apart chance alone puts
    the two. Returns (above, distances, p-values, the dummies' mean and sd)."""
    above = y > threshold
    tests = [stats.ks_2samp(X[above, k], X[~above, k]) for k in range(X.shape[1])]
    chance = [stats.ks_2samp(u[above], u[~above]).statistic for u in rng.random((dummies, len(y)))]
    return (above, np.array([t.statistic for t in tests]), np.array([t.pvalue for t in tests]),
            float(np.mean(chance)), float(np.std(chance, ddof=1)))


# ---------------------------------------------------------------------------
# the sample: the realisations an output is analysed over
# ---------------------------------------------------------------------------

def _sample(table, rows, y, x, log_y):
    """The rows of the report with the output and every input present (and,
    on logarithms, the output above zero): X, the output (logged or not),
    the page's row numbers, and how many were left out and why."""
    names = [y] + [c for c in x if c != y]
    df = data.frame(table, names, rows, dropna=False, as_category=False)
    A = df.to_numpy(float)
    ok = np.isfinite(A).all(axis=1)
    missing = int((~ok).sum())
    nonpositive = 0
    if log_y:
        pos = A[:, 0] > 0
        nonpositive = int((ok & ~pos).sum())
        ok &= pos
    A = A[ok]
    v = np.log(A[:, 0]) if log_y else A[:, 0]
    return {'X': A[:, 1:], 'y': v, 'raw': A[:, 0], 'index': df.index.to_numpy()[ok], 'n': int(ok.sum()),
            'missing': missing, 'nonpositive': nonpositive, 'inputs': names[1:]}


def _left_out(S, y):
    """What the notes say of the realisations not analysed, or None."""
    bits = []
    if S['missing']:
        bits.append(f'{S["missing"]:,} with the output or an input missing')
    if S['nonpositive']:
        bits.append(f'{S["nonpositive"]:,} with {y} not above zero, which has no logarithm')
    return '; '.join(bits) or None


def _varies(v):
    return len(v) > 1 and bool(np.any(v != v[0]))


# ---------------------------------------------------------------------------
# the code under each result
# ---------------------------------------------------------------------------

def _source(*fns):
    return '\n\n\n'.join(inspect.getsource(f).rstrip() for f in fns)


def _rows_code(table, rows):
    """The line that keeps the report's rows of the table as exported (a By
    group, rows excluded or filtered out); none when it has every row."""
    if rows is None:
        return []
    n = data.TABLES[table]['n'] if table in data.TABLES else None
    keep = [int(r) for r in rows]
    if n is not None and len(keep) > n / 2:
        drop = sorted(set(range(n)) - set(keep))
        return [f'df = df.drop(index={drop})   # the rows the report leaves out'] if drop else []
    return [f'df = df.loc[{keep}]   # the rows of the report']


def _sample_code(table, rows, y, x, log_y, table_name, imports):
    """The head of every snippet: the table, the report's rows, the
    realisations with the output and every input present, X and y."""
    L = [code_head(table_name, imports), *_rows_code(table, rows),
         f'inputs = {J(list(x))}',
         f'd = df[inputs + [{J(y)}]]',
         'd = d[np.isfinite(d).all(axis=1)]   # the realisations with the output and every input present']
    if log_y:
        L.append(f'd = d[d[{J(y)}] > 0]   # Log Output: those whose output has a logarithm')
    L.append('X = d[inputs].to_numpy(float)')
    L.append(f'y = np.log(d[{J(y)}].to_numpy(float))   # Log Output' if log_y else f'y = d[{J(y)}].to_numpy(float)')
    return L


# ---------------------------------------------------------------------------
# the page's calls
# ---------------------------------------------------------------------------

@api('sensitivity.measures')
def measures(table, y, x, rows=None, log_y=False, table_name='data'):
    """The Measures of one output: for each input Pearson's and Spearman's
    correlations (with their p-values), SRC, PCC, SRRC, PRCC and S1; the R²
    of the regression and of the regression on ranks."""
    S = _sample(table, rows, y, x, log_y)
    if S['n'] < MIN_ROWS:
        return {'error': f'{S["n"]} realisations with {y} and every input present{" (and above zero, on logarithms)" if log_y else ""}: at least {MIN_ROWS} are needed'}
    X, v = S['X'], S['y']
    src, pcc, r2 = regression_measures(X, v)
    srrc, prcc, r2_rank = regression_measures(stats.rankdata(X, axis=0), stats.rankdata(v))
    out = []
    for k, name in enumerate(S['inputs']):
        xk = X[:, k]
        row = {'input': name, 'pearson': np.nan, 'pearson_p': np.nan, 'spearman': np.nan, 'spearman_p': np.nan,
               'src': src[k], 'pcc': pcc[k], 'srrc': srrc[k], 'prcc': prcc[k], 's1': np.nan, 'constant': not _varies(xk)}
        if _varies(xk) and _varies(v):
            row['pearson'], row['pearson_p'] = stats.pearsonr(xk, v)
            row['spearman'], row['spearman_p'] = stats.spearmanr(xk, v)
            row['s1'] = first_order_index(xk, v)
        out.append(row)
    L = _sample_code(table, rows, y, x, log_y, table_name, ['import math', 'from scipy import linalg, stats'])
    L += ['', '', _source(regression_measures, first_order_index), '', '',
          'src, pcc, r2 = regression_measures(X, y)',
          'srrc, prcc, r2_rank = regression_measures(stats.rankdata(X, axis=0), stats.rankdata(y))   # on ranks',
          'K = range(len(inputs))',
          'table = pd.DataFrame({"Input": inputs,',
          '                      "Pearson": [stats.pearsonr(X[:, k], y)[0] for k in K], "Spearman": [stats.spearmanr(X[:, k], y)[0] for k in K],',
          '                      "SRC": src, "PCC": pcc, "SRRC": srrc, "PRCC": prcc, "S1": [first_order_index(X[:, k], y) for k in K]})',
          'print(table)',
          'print("R²", r2, "R² on ranks", r2_rank, "realisations", len(y))']
    plots = _sample_code(table, rows, y, x, log_y, table_name, ['import matplotlib.pyplot as plt'])
    plots += ['', 'across = min(4, len(inputs))   # four to a row, as the page lays them out',
              'fig, axes = plt.subplots(-(-len(inputs) // across), across, figsize=(2.9 * across, 2.5 * -(-len(inputs) // across)), squeeze=False, layout="constrained")',
              'for ax, name, x in zip(axes.flat, inputs, X.T):',
              f'    ax.scatter(x, {"np.exp(y)" if log_y else "y"}, s=4, color="{BASE}")',
              *(['    ax.set_yscale("log")'] if log_y else []),
              '    ax.set_xlabel(name)',
              f'    ax.set_ylabel({J(y)})',
              'for ax in axes.flat[len(inputs):]:',
              '    ax.set_visible(False)',
              'plt.show()']
    return {'output': y, 'n': S['n'], 'left_out': _left_out(S, y), 'log_y': bool(log_y), 'index': S['index'],
            'r2': r2, 'r2_rank': r2_rank, 'rows': out, 'code': '\n'.join(L), 'plots_code': '\n'.join(plots)}


@api('sensitivity.distribution')
def distribution(table, y, x, rows=None, log_y=False, boots=BOOTS, seed=SEED, table_name='data'):
    """The distribution-based measures of one output: for each input EASI's
    first-order index (corrected), δ (adjusted, with its interval), PAWN
    (the median and greatest distance over the slices), mutual information
    (in bits, its chance level, what is above it) and the share of the
    discrepancy. Each input's random draws come from the seed and its place,
    np.random.default_rng([seed, k]): δ's resamples, then the shuffles."""
    S = _sample(table, rows, y, x, log_y)
    if S['n'] < MIN_DISTRIBUTION:
        return {'error': f'{S["n"]} realisations with {y} and every input present: the distribution-based measures need at least {MIN_DISTRIBUTION}'}
    X, v = S['X'], S['y']
    n, K = X.shape
    boots, seed = int(boots), int(seed)
    if not _varies(v):
        return {'error': f'{y} has one value in every realisation analysed: there is nothing to attribute'}
    scores = stats.norm.ppf((stats.rankdata(v) - 0.5) / n)
    ry = stats.rankdata(v)
    out = []
    for k, name in enumerate(S['inputs']):
        xk = X[:, k]
        row = {'input': name, 'easi': np.nan, 'delta': np.nan, 'delta_low': np.nan, 'delta_high': np.nan, 'pawn': np.nan, 'pawn_max': np.nan,
               'mi': np.nan, 'mi_bound': np.nan, 'mi_above': np.nan, 'discrepancy': np.nan, 'constant': not _varies(xk)}
        if _varies(xk):
            rng = np.random.default_rng([seed, k])
            row['easi'] = easi(xk, v)[1]
            _, row['delta'], row['delta_low'], row['delta_high'] = delta_moment(xk, scores, rng, boots=boots)
            row['mi'], row['mi_bound'], row['mi_above'] = mutual_information(stats.rankdata(xk), ry, rng, boots=boots)
            pw = pawn(xk, v)
            row['pawn'], row['pawn_max'] = pw['median'], pw['maximum']
        out.append(row)
        print(f'smui:progress sensitivity {k + 1} {K} {one_line(y)}: {one_line(name)}', flush=True)
    varying = [k for k in range(K) if not out[k]['constant']]
    discrepancy = bool(varying) and len(varying) * n * n <= DISCREPANCY_WORK
    if discrepancy:
        for k, share in zip(varying, discrepancy_shares(X[:, varying], v)):
            out[k]['discrepancy'] = share
    L = _sample_code(table, rows, y, x, log_y, table_name, ['import math', 'from scipy import linalg, stats', 'from scipy.stats import qmc'])
    L += ['', '', _source(easi, kde_bandwidth, kde, kde_pdf, delta_classes, delta_once, delta_moment, mutual_information, pawn, discrepancy_shares), '', '',
          f'seed, boots = {seed}, {boots}',
          'scores = stats.norm.ppf((stats.rankdata(y) - 0.5) / len(y))   # δ is read on the normal scores of the output, mutual information on ranks',
          'varying = [k for k in range(len(inputs)) if np.ptp(X[:, k]) > 0]   # a constant input has no measures',
          'rows = []',
          'for k in varying:',
          '    name, x = inputs[k], X[:, k]',
          '    rng = np.random.default_rng([seed, k])   # δ\'s resamples, then the shuffles',
          '    delta, adjusted, low, high = delta_moment(x, scores, rng, boots=boots)',
          '    mi, chance, above = mutual_information(stats.rankdata(x), stats.rankdata(y), rng, boots=boots)',
          '    pw = pawn(x, y)',
          '    rows.append({"Input": name, "S1 (EASI)": easi(x, y)[1], "δ": adjusted, "δ Lower": low, "δ Upper": high,',
          '                 "PAWN": pw["median"], "PAWN Max": pw["maximum"], "MI": mi, "MI Chance": chance, "MI Above": above})',
          'table = pd.DataFrame(rows)']
    if discrepancy:
        L.append('table["Discrepancy"] = discrepancy_shares(X[:, varying], y)')
    L.append('print(table)')
    return {'output': y, 'n': n, 'left_out': _left_out(S, y), 'rows': out, 'boots': boots, 'seed': seed,
            'discrepancy': discrepancy, 'code': '\n'.join(L)}


@api('sensitivity.regional')
def regional_split(table, y, x, rows=None, log_y=False, split='mean', value=None, seed=SEED, table_name='data'):
    """Regional sensitivity analysis of one output: the realisations above
    the threshold against the rest. split: 'mean' (of the output, or of its
    logarithms with Log Output: the geometric mean), 'median', 'quantile'
    (value, a probability) or 'value' (value, in the output's units).
    Returns each input's KS distance and p-value, the dummies' level, the
    threshold in the output's units and the rows above it."""
    S = _sample(table, rows, y, x, log_y)
    if S['n'] < MIN_ROWS:
        return {'error': f'{S["n"]} realisations with {y} and every input present: at least {MIN_ROWS} are needed'}
    X, v = S['X'], S['y']
    n, K = X.shape
    seed = int(seed)
    if split == 'value':
        if value is None or not math.isfinite(float(value)):
            return {'error': 'the threshold is not a number'}
        if log_y and not float(value) > 0:
            return {'error': 'with Log Output the threshold is in the output\'s units and has to be above zero'}
        t = math.log(float(value)) if log_y else float(value)
        how = f'{float(value):.6g}'
        line = f'threshold = {"np.log(" if log_y else ""}{float(value)!r}{")" if log_y else ""}   # the threshold given'
    elif split == 'quantile':
        p = float(value) if value is not None else float('nan')
        if not 0 < p < 1:
            return {'error': 'the quantile is a probability between 0 and 1'}
        t = float(np.quantile(v, p))
        how = f'the {p:g} quantile'
        line = f'threshold = np.quantile(y, {p!r})'
    elif split == 'median':
        t = float(np.median(v))
        how = 'the median'
        line = 'threshold = np.median(y)'
    else:
        t = float(np.mean(v))
        how = 'the geometric mean' if log_y else 'the mean'
        line = f'threshold = y.mean()   # {how}'
    above = v > t
    if not 0 < int(above.sum()) < n:
        return {'error': f'every realisation is {"above" if above.all() else "at or below"} the threshold ({how}): there are not two groups to compare'}
    rng = np.random.default_rng([seed, K])
    above, ks, p, dummy_mean, dummy_sd = regional(X, v, t, rng, DUMMIES)
    out = [{'input': name, 'ks': ks[k], 'p': p[k], 'constant': not _varies(X[:, k])} for k, name in enumerate(S['inputs'])]
    L = _sample_code(table, rows, y, x, log_y, table_name, ['from scipy import stats'])
    L += ['', '', _source(regional), '', '', line,
          f'rng = np.random.default_rng([{seed}, len(inputs)])   # the dummy inputs\' draws',
          f'above, ks, p, dummy_mean, dummy_sd = regional(X, y, threshold, rng, dummies={DUMMIES})',
          'print(pd.DataFrame({"Input": inputs, "KS": ks, "Prob > KS": p}))',
          'print("above the threshold", above.sum(), "of", len(y), "; dummy inputs", dummy_mean, "±", dummy_sd)']
    plots = _sample_code(table, rows, y, x, log_y, table_name, ['import matplotlib.pyplot as plt'])
    plots += ['', line, 'above = y > threshold',
              'across = min(4, len(inputs))   # four to a row, as the page lays them out',
              'fig, axes = plt.subplots(-(-len(inputs) // across), across, figsize=(2.9 * across, 2.5 * -(-len(inputs) // across)), squeeze=False, layout="constrained")',
              'for ax, name, x in zip(axes.flat, inputs, X.T):',
              f'    for part, label, color in ((x[above], "above", "{BASE}"), (x[~above], "at or below", "{OTHER}")):',
              '        s = np.sort(part)',
              '        ax.step(s, np.arange(1, len(s) + 1) / len(s), where="post", color=color, label=label)',
              '    ax.set_xlabel(name)',
              '    ax.set_ylabel("Cumulative probability")',
              'for ax in axes.flat[len(inputs):]:',
              '    ax.set_visible(False)',
              'axes.flat[0].legend(fontsize=8, frameon=False)',
              'plt.show()']
    return {'output': y, 'n': n, 'left_out': _left_out(S, y), 'threshold': math.exp(t) if log_y else t, 'how': how, 'split': split,
            'above': int(above.sum()), 'below': int(n - above.sum()), 'rows': out, 'dummy_mean': dummy_mean, 'dummy_sd': dummy_sd,
            'above_rows': S['index'][above], 'below_rows': S['index'][~above], 'seed': seed, 'code': '\n'.join(L), 'plots_code': '\n'.join(plots)}
