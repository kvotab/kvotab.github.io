"""Graph: the statistics behind the Graph menu.

Graph Builder's elements (Smoother, Line of Fit, Ellipse, Contour, the
summary statistics behind Bar, Line, Area, Points, Box Plot and Caption Box,
the kernel densities of Histogram and Violin, Mosaic's chi-square, Bean's
violins), the ellipses, fit lines and densities of Scatterplot Matrix, the
gridded surfaces of Contour Plot and Surface Plot, and the Functional Data
Plot's band depths, functional boxplot and HDR boxplot.

Groups come as parallel arrays: rows, the page's row numbers (None: every
row of the table, in order), and codes, the group of each row from 0 to
k - 1 (None: one group; a negative code leaves the row out). Results come
back one entry per group, in group order, so the page can put them back in
the right panel and colour.

The Smoother is JMP's: a cubic smoothing spline on standardized X with
lambda 0.05. scipy's make_smoothing_spline minimises the same penalised
sum of squares, sum w (y - f(x))^2 + lambda * integral f''(x)^2 dx; its
'Local Kernel' alternative is statsmodels' lowess.

statsmodels' graphics (fboxplot, hdrboxplot, rainbowplot, beanplot) draw
with matplotlib, which the page does not load: their numbers are computed
here, with statsmodels' own functions where they can be called without a
figure (banddepth, PCA, KDEMultivariate, the violin of beanplot), and the
page draws them.

graph.code writes the Python under each graph of the menu: matplotlib code
that draws the same graph from the table's CSV export, the calculations
above written into it, from the plan of what the page drew (see "The graphs
as matplotlib code" below).
"""
import json
import math
import re

import numpy as np
from scipy import stats
from scipy.interpolate import griddata, make_smoothing_spline
from scipy.signal import fftconvolve

from . import data
from .registry import api
from .util import code_head, one_line

# JMP's quantiles are the (n+1)p-th order statistics: numpy's 'weibull'.
QUANTILES = [0.0, 0.005, 0.025, 0.10, 0.25, 0.50, 0.75, 0.90, 0.975, 0.995, 1.0]
QUANTILE_KEYS = ['q0', 'q005', 'q025', 'q10', 'q25', 'q50', 'q75', 'q90', 'q975', 'q995', 'q100']
BOOTSTRAP = 100          # resamples for the smoother's Confidence of Fit (fewer for many points)
EXACT_KDE = 1500         # above this many points the 2-D density is binned (FFT)
HDR_GRID = 161           # the score plane's grid for the HDR boxplot's bands, per axis
BD2_COUNTED = 400        # the most curves the band depth is counted for (O(n^3 p))


# ---- the rows, the groups and the columns -------------------------------------
def _rows(table, rows):
    n = data.TABLES[table]['n']
    return np.arange(n) if rows is None else np.asarray(rows, dtype=int)


def _codes(codes, m, k=None):
    c = np.zeros(m, dtype=int) if codes is None else np.asarray(codes, dtype=int)
    if len(c) != m:
        raise ValueError('codes and rows differ in length')
    if k is None:
        k = int(c.max()) + 1 if len(c) else 0
    return c, int(k)


def _num(table, name, rows):
    if data.meta(table, name).get('dataType') != 'numeric':
        raise ValueError(f'{name} is not numeric')
    return np.asarray(data.raw(table, name, rows), dtype=float)


def _freq(table, freq, rows, m):
    if not freq:
        return np.ones(m)
    f = _num(table, freq, rows)
    return np.where(np.isfinite(f) & (f > 0), f, 0.0)


def _split(codes, k):
    """The positions of each group's rows."""
    order = np.argsort(codes, kind='stable')
    bounds = np.searchsorted(codes[order], np.arange(k + 1))
    return [order[bounds[g]:bounds[g + 1]] for g in range(k)]


def _replicate(w):
    """Integer frequencies, for methods that take no weights (a row counts
    that many times); None when the weights are not whole numbers."""
    if np.all(w == 1):
        return None
    if np.all(np.abs(w - np.round(w)) < 1e-9) and w.sum() <= 2_000_000:
        return np.round(w).astype(int)
    return None


def _pairs(table, x, y, rows, codes, k, freq):
    r = _rows(table, rows)
    c, k = _codes(codes, len(r), k)
    xv, yv = _num(table, x, r), _num(table, y, r)
    f = _freq(table, freq, r, len(r))
    ok = np.isfinite(xv) & np.isfinite(yv) & (f > 0) & (c >= 0) & (c < k)
    return xv[ok], yv[ok], f[ok], c[ok], k


# ---- the Python under a graph: JSON text for names and strings -------------------
def _j(s):
    return json.dumps(s)


# ---- summary statistics ---------------------------------------------------------
def _weibull(ys, start, cnt, p):
    """JMP's quantile (numpy's 'weibull') of each group of a sorted array."""
    out = np.full(len(cnt), np.nan)
    has = cnt > 0
    if not has.any():
        return out
    s, n = start[has], cnt[has]
    h = (n + 1) * p
    kf = np.floor(h)
    frac = h - kf
    kf = kf.astype(int)
    lo = s + np.clip(kf - 1, 0, n - 1)
    hi = s + np.clip(kf, 0, n - 1)
    v = ys[lo] + frac * (ys[hi] - ys[lo])
    v = np.where(h <= 1, ys[s], v)
    v = np.where(h >= n, ys[s + n - 1], v)
    out[has] = v
    return out


@api('graph.summary')
def summary(table, y, rows=None, codes=None, k=None, freq=None, alpha=0.05, boxes=False, want=None, by=None, table_name='data'):
    """N, mean, standard deviation, standard error, the t confidence
    interval of the mean, sum, minimum, maximum and JMP's quantiles of y in
    each group; with boxes, the whiskers of the outlier box plot (the
    furthest values within 1.5 IQR of the quartiles). want: the keys to
    return (all when None), to keep the answer small for many groups."""
    r = _rows(table, rows)
    c, k = _codes(codes, len(r), k)
    yv = _num(table, y, r)
    f = _freq(table, freq, r, len(r))
    ok = np.isfinite(yv) & (f > 0) & (c >= 0) & (c < k)
    yv, f, c = yv[ok], f[ok], c[ok]
    n_rows = np.bincount(c, minlength=k).astype(float)
    n = np.bincount(c, weights=f, minlength=k)
    total = np.bincount(c, weights=f * yv, minlength=k)
    with np.errstate(invalid='ignore', divide='ignore'):
        mean = total / n
        dev = yv - mean[c] if len(c) else yv
        ss = np.bincount(c, weights=f * dev * dev, minlength=k)
        var = np.where(n > 1, ss / (n - 1), np.nan)
        sd = np.sqrt(var)
        se = sd / np.sqrt(n)
        tq = np.where(n > 1, stats.t.ppf(1 - alpha / 2, np.maximum(n - 1, 1)), np.nan)
    mn = np.full(k, np.inf)
    mx = np.full(k, -np.inf)
    np.minimum.at(mn, c, yv)
    np.maximum.at(mx, c, yv)
    empty = n_rows == 0
    mn[empty] = np.nan
    mx[empty] = np.nan
    # Quantiles: a row with Freq f counts f times (whole frequencies), as in JMP.
    rep = _replicate(f) if freq else None
    if freq and rep is None and np.any(f != 1):
        from statsmodels.stats.weightstats import DescrStatsW
        qs = {key: np.full(k, np.nan) for key in QUANTILE_KEYS}
        for g, idx in enumerate(_split(c, k)):
            if len(idx):
                v = DescrStatsW(yv[idx], weights=f[idx]).quantile(QUANTILES, return_pandas=False)
                for key, val in zip(QUANTILE_KEYS, v):
                    qs[key][g] = val
        ys, start, cnt = None, None, None
    else:
        yq, cq = (np.repeat(yv, rep), np.repeat(c, rep)) if rep is not None else (yv, c)
        order = np.lexsort((yq, cq))
        ys, cs = yq[order], cq[order]
        start = np.searchsorted(cs, np.arange(k))
        cnt = np.searchsorted(cs, np.arange(k), side='right') - start
        qs = {key: _weibull(ys, start, cnt, p) for key, p in zip(QUANTILE_KEYS, QUANTILES)}
    out = {
        'k': k, 'n': n, 'n_rows': n_rows, 'sum': total, 'mean': mean, 'sd': sd, 'var': var, 'se': se,
        'lower': mean - tq * se, 'upper': mean + tq * se, 'min': mn, 'max': mx,
        'median': qs['q50'], 'q1': qs['q25'], 'q3': qs['q75'], 'quantiles': qs, 'alpha': alpha,
    }
    if boxes:
        lo_w, hi_w = np.full(k, np.nan), np.full(k, np.nan)
        q1, q3 = qs['q25'], qs['q75']
        for g, idx in enumerate(_split(c, k)):
            if not len(idx):
                continue
            seg = np.sort(yv[idx])
            iqr = q3[g] - q1[g]
            inside = seg[(seg >= q1[g] - 1.5 * iqr) & (seg <= q3[g] + 1.5 * iqr)]
            if len(inside):
                lo_w[g], hi_w[g] = inside[0], inside[-1]
        out['lo_whisker'], out['hi_whisker'] = lo_w, hi_w
    if want:
        keep = set(want) | {'k', 'alpha'}
        out = {key: v for key, v in out.items() if key in keep}
    return out


# ---- the Smoother ----------------------------------------------------------------
def _spline_fit(z, y, w, lam):
    """A smoothing spline through tied x values: the mean of y at each x,
    weighted by the count, gives the same penalised fit."""
    zu, inv = np.unique(z, return_inverse=True)
    wu = np.bincount(inv, weights=w)
    yu = np.bincount(inv, weights=w * y) / wu
    return make_smoothing_spline(zu, yu, w=wu, lam=lam)


def _spline(xs, ys, ws, lam, n_grid, conf, alpha):
    if len(np.unique(xs)) < 5:
        return {'error': 'the spline needs at least 5 distinct X values'}
    W = ws.sum()
    m = float(np.sum(ws * xs) / W)
    sd = float(np.sqrt(np.sum(ws * (xs - m) ** 2) / (W - 1))) if W > 1 else 0.0
    if not sd > 0:
        return {'error': 'X does not vary'}
    z = (xs - m) / sd
    fn = _spline_fit(z, ys, ws, lam)
    grid = np.linspace(xs.min(), xs.max(), n_grid)
    gz = (grid - m) / sd
    out = {'x': grid, 'y': fn(gz), 'n': W, 'mean': m, 'sd': sd}
    if conf:
        # Case resampling; for many points fewer resamples, and the band is
        # the normal one, the fit plus or minus z times the resamples' spread.
        rng = np.random.default_rng(20260926)
        B = BOOTSTRAP if len(xs) <= 2000 else max(25, 200_000 // len(xs))
        curves = []
        for _ in range(B):
            i = rng.integers(0, len(xs), len(xs))
            if len(np.unique(z[i])) < 5:
                continue
            try:
                curves.append(_spline_fit(z[i], ys[i], ws[i], lam)(gz))
            except Exception:
                continue
        if len(curves) >= 10:
            spread = np.std(np.array(curves), axis=0, ddof=1)
            zq = stats.norm.ppf(1 - alpha / 2)
            out['lower'], out['upper'] = out['y'] - zq * spread, out['y'] + zq * spread
            out['resamples'] = len(curves)
    return out


def _lowess(xs, ys, ws, frac, it, n_grid):
    from statsmodels.nonparametric.smoothers_lowess import lowess
    rep = _replicate(ws)
    if rep is not None:
        xs, ys = np.repeat(xs, rep), np.repeat(ys, rep)
    if len(np.unique(xs)) < 3:
        return {'error': 'the local kernel smoother needs at least 3 distinct X values'}
    delta = 0.01 * float(np.ptp(xs)) if len(xs) > 1000 else 0.0
    res = lowess(ys, xs, frac=frac, it=it, delta=delta, return_sorted=True)
    ux, first = np.unique(res[:, 0], return_index=True)
    fy = res[first, 1]
    if len(ux) > 4 * n_grid:
        keep = np.unique(np.linspace(0, len(ux) - 1, 4 * n_grid).round().astype(int))
        ux, fy = ux[keep], fy[keep]
    return {'x': ux, 'y': fy, 'n': float(len(xs)), 'delta': delta}


@api('graph.smoother')
def smoother(table, x, y, rows=None, codes=None, k=None, method='spline', lam=0.05, frac=2 / 3, it=3, conf=False,
             alpha=0.05, freq=None, n_grid=120, by=None, table_name='data'):
    """Graph Builder's Smoother in each group. method 'spline': a cubic
    smoothing spline on standardized X (JMP's; lambda 0.05 by default), with
    an optional bootstrap Confidence of Fit; 'lowess': statsmodels' lowess
    with span frac and it robustifying iterations (JMP's Local Kernel)."""
    xv, yv, f, c, k = _pairs(table, x, y, rows, codes, k, freq)
    curves = []
    for idx in _split(c, k):
        try:
            if len(idx) < 3:
                curves.append({'error': 'too few points'})
            elif method == 'lowess':
                curves.append(_lowess(xv[idx], yv[idx], f[idx], float(frac), int(it), n_grid))
            else:
                curves.append(_spline(xv[idx], yv[idx], f[idx], float(lam), n_grid, bool(conf), alpha))
        except Exception as e:  # one group's failure should not lose the others
            curves.append({'error': str(e)})
    return {'curves': curves, 'method': method}


# ---- Line of Fit -----------------------------------------------------------------
def _cauchy_norm():
    from statsmodels.robust.norms import RobustNorm

    class Cauchy(RobustNorm):
        """Cauchy weights, w = 1 / (1 + (r/c)^2), c = 2.3849 (95% efficiency)."""
        def __init__(self, c=2.3849):
            self.c = c

        def rho(self, z):
            return self.c ** 2 / 2 * np.log1p((np.asarray(z) / self.c) ** 2)

        def psi(self, z):
            z = np.asarray(z)
            return z / (1 + (z / self.c) ** 2)

        def weights(self, z):
            return 1 / (1 + (np.asarray(z) / self.c) ** 2)

        def psi_deriv(self, z):
            u = (np.asarray(z) / self.c) ** 2
            return (1 - u) / (1 + u) ** 2

    return Cauchy()


def _polyfit(xs, ys, ws, degree, robust, alpha, n_grid):
    import statsmodels.api as sm
    rep = _replicate(ws)
    if rep is not None:
        xs, ys = np.repeat(xs, rep), np.repeat(ys, rep)
    p = degree + 1
    if len(np.unique(xs)) < p or len(xs) <= p:
        return {'error': f'a degree {degree} fit needs more than {p} points with {p} distinct X values'}
    m = float(xs.mean())
    s = float(xs.std(ddof=1)) or 1.0
    # Scaled (x - mean)/sd for a well-conditioned design; the coefficients go
    # back to JMP's form, b0 + b1*x + b2*(x - mean)^2 + b3*(x - mean)^3.
    X = np.vander((xs - m) / s, p, increasing=True)
    grid = np.linspace(xs.min(), xs.max(), n_grid)
    Xg = np.vander((grid - m) / s, p, increasing=True)
    out = {'x': grid, 'n': float(len(xs)), 'mean': m, 'degree': degree}
    if robust:
        res = sm.RLM(ys, X, M=_cauchy_norm()).fit()
        pred = Xg @ res.params
        se = np.sqrt(np.einsum('ij,jk,ik->i', Xg, res.cov_params(), Xg))
        zq = stats.norm.ppf(1 - alpha / 2)
        out.update(y=pred, fit_lower=pred - zq * se, fit_upper=pred + zq * se, rmse=float(res.scale), robust=True)
    else:
        res = sm.OLS(ys, X).fit()
        sf = res.get_prediction(Xg).summary_frame(alpha=alpha)
        out.update(y=sf['mean'].to_numpy(), fit_lower=sf['mean_ci_lower'].to_numpy(), fit_upper=sf['mean_ci_upper'].to_numpy(),
                   pred_lower=sf['obs_ci_lower'].to_numpy(), pred_upper=sf['obs_ci_upper'].to_numpy(),
                   r2=float(res.rsquared), rmse=float(np.sqrt(res.scale)), f=float(res.fvalue) if degree else None,
                   p=float(res.f_pvalue) if degree else None, df_model=float(res.df_model), df_resid=float(res.df_resid))
    c = res.params / s ** np.arange(p)       # coefficients of (x - mean)^j
    coef = c.copy()
    if p > 1:
        coef[0] = c[0] - c[1] * m                # the linear term on x itself, as JMP writes it
    out['coef'] = coef
    return out


@api('graph.fit')
def fit(table, x, y, rows=None, codes=None, k=None, degree=1, robust=False, alpha=0.05, freq=None, n_grid=100,
        by=None, table_name='data'):
    """Graph Builder's Line of Fit in each group: a polynomial of degree 1
    to 3 by least squares (statsmodels OLS), with the confidence band of the
    fit and of individual predictions, R-square, RMSE and the F test; or a
    robust fit with Cauchy weights (statsmodels RLM)."""
    degree = max(1, min(3, int(degree)))
    xv, yv, f, c, k = _pairs(table, x, y, rows, codes, k, freq)
    fits = []
    for idx in _split(c, k):
        try:
            fits.append(_polyfit(xv[idx], yv[idx], f[idx], degree, bool(robust), alpha, n_grid) if len(idx) > 1 else {'error': 'too few points'})
        except Exception as e:
            fits.append({'error': str(e)})
    return {'fits': fits}


# ---- Ellipse ------------------------------------------------------------------------
@api('graph.ellipse')
def ellipse(table, x, y, rows=None, codes=None, k=None, coverage=0.95, freq=None, n_points=96, by=None, table_name='data'):
    """The bivariate normal density ellipse of each group: the contour of
    the normal with the sample means and covariance that holds the given
    share of that normal (radius^2 the chi-square(2) quantile)."""
    xv, yv, f, c, k = _pairs(table, x, y, rows, codes, k, freq)
    r2 = float(stats.chi2.ppf(coverage, 2))
    t = np.linspace(0, 2 * np.pi, n_points)
    circle = np.vstack([np.cos(t), np.sin(t)])
    out = []
    for idx in _split(c, k):
        xs, ys, ws = xv[idx], yv[idx], f[idx]
        W = ws.sum()
        if len(idx) < 3 or W < 3:
            out.append({'error': 'too few points'})
            continue
        mu = np.array([np.sum(ws * xs), np.sum(ws * ys)]) / W
        dx, dy = xs - mu[0], ys - mu[1]
        cov = np.array([[np.sum(ws * dx * dx), np.sum(ws * dx * dy)], [np.sum(ws * dx * dy), np.sum(ws * dy * dy)]]) / (W - 1)
        try:
            L = np.linalg.cholesky(cov)
        except np.linalg.LinAlgError:
            out.append({'error': 'X and Y are collinear or constant'})
            continue
        pts = mu[:, None] + np.sqrt(r2) * (L @ circle)
        out.append({'x': pts[0], 'y': pts[1], 'mean': mu, 'sd': np.sqrt(np.diag(cov)), 'r': float(cov[0, 1] / np.sqrt(cov[0, 0] * cov[1, 1])), 'n': W})
    return {'ellipses': out, 'coverage': coverage}


# ---- Contour: the bivariate kernel density ------------------------------------------
def _kernel_grid(C, dx, dy, G):
    """The Gaussian kernel with covariance C on grid offsets, for binned
    estimation."""
    Lx = int(min(G, np.ceil(4 * np.sqrt(C[0, 0]) / dx)))
    Ly = int(min(G, np.ceil(4 * np.sqrt(C[1, 1]) / dy)))
    ox, oy = np.arange(-Lx, Lx + 1) * dx, np.arange(-Ly, Ly + 1) * dy
    OX, OY = np.meshgrid(ox, oy)
    P = np.linalg.inv(C)
    q = P[0, 0] * OX * OX + 2 * P[0, 1] * OX * OY + P[1, 1] * OY * OY
    return np.exp(-0.5 * q) / (2 * np.pi * np.sqrt(np.linalg.det(C)))


def _binned_kde(xs, ys, ws, C, gx, gy, refine=4):
    """The kernel density on the grid by linear binning and an FFT
    convolution (as KernSmooth does), on a grid `refine` times finer than
    the one returned: close to exact, and fast for many points."""
    fine_x = np.linspace(gx[0], gx[-1], refine * (len(gx) - 1) + 1)
    fine_y = np.linspace(gy[0], gy[-1], refine * (len(gy) - 1) + 1)
    return _binned_on(xs, ys, ws, C, fine_x, fine_y)[::refine, ::refine]


def _binned_on(xs, ys, ws, C, gx, gy):
    G = len(gx)
    dx, dy = gx[1] - gx[0], gy[1] - gy[0]
    fx, fy = (xs - gx[0]) / dx, (ys - gy[0]) / dy
    ix, iy = np.clip(np.floor(fx).astype(int), 0, G - 2), np.clip(np.floor(fy).astype(int), 0, G - 2)
    tx, ty = np.clip(fx - ix, 0, 1), np.clip(fy - iy, 0, 1)
    counts = np.zeros((G, G))
    np.add.at(counts, (iy, ix), ws * (1 - tx) * (1 - ty))
    np.add.at(counts, (iy, ix + 1), ws * tx * (1 - ty))
    np.add.at(counts, (iy + 1, ix), ws * (1 - tx) * ty)
    np.add.at(counts, (iy + 1, ix + 1), ws * tx * ty)
    dz = fftconvolve(counts, _kernel_grid(C, dx, dy, G), mode='same') / ws.sum()
    return np.maximum(dz, 0)


def _mass(dz, dd, wd):
    """For each grid value, the share of the points whose density is at
    least as high: the contour of this at p encloses a share p of the data.
    Below the lowest density at a point it goes on past 1, so the 100%
    contour is drawn too."""
    order = np.argsort(dd)
    s, w = dd[order], wd[order]
    tail = np.cumsum(w[::-1])[::-1] / w.sum()          # share with density >= s_i
    m = np.interp(dz, s, tail)
    lo = s[0] if s[0] > 0 else 1e-300
    return np.where(dz < s[0], 1 + (s[0] - dz) / lo, m)


@api('graph.density')
def density(table, x, y, rows=None, codes=None, k=None, bw=1.0, grid=64, freq=None, by=None, table_name='data'):
    """A bivariate Gaussian kernel density (scipy's gaussian_kde, Scott's
    bandwidth times bw) of each group on a grid, returned as the share of
    the points inside each density contour: the page draws the contours at
    1/levels, 2/levels, ..., 100%."""
    xv, yv, f, c, k = _pairs(table, x, y, rows, codes, k, freq)
    out = []
    for idx in _split(c, k):
        xs, ys, ws = xv[idx], yv[idx], f[idx]
        try:
            if len(idx) < 3 or len(np.unique(xs)) < 2 or len(np.unique(ys)) < 2:
                out.append({'error': 'too few distinct points'})
                continue
            kde = stats.gaussian_kde(np.vstack([xs, ys]), weights=None if np.all(ws == 1) else ws)
            if bw != 1:
                kde.set_bandwidth(kde.factor * float(bw))
            C = kde.covariance
            px, py = 3 * np.sqrt(C[0, 0]), 3 * np.sqrt(C[1, 1])
            gx = np.linspace(xs.min() - px, xs.max() + px, grid)
            gy = np.linspace(ys.min() - py, ys.max() + py, grid)
            GX, GY = np.meshgrid(gx, gy)
            if len(xs) <= EXACT_KDE:
                dz = kde(np.vstack([GX.ravel(), GY.ravel()])).reshape(GX.shape)
                dd = kde(np.vstack([xs, ys]))
                method = 'exact'
            else:
                from scipy.interpolate import RegularGridInterpolator
                dz = _binned_kde(xs, ys, ws, C, gx, gy)
                dd = RegularGridInterpolator((gy, gx), dz)(np.c_[ys, xs])
                method = 'binned'
            out.append({'x': gx, 'y': gy, 'z': _mass(dz, dd, ws), 'max': float(dz.max()), 'n': float(ws.sum()), 'factor': float(kde.factor), 'method': method})
        except Exception as e:
            out.append({'error': str(e)})
    return {'densities': out}


@api('graph.kde1')
def kde1(table, y, rows=None, codes=None, k=None, bw=1.0, grid=128, lo=None, hi=None, freq=None, by=None, table_name='data'):
    """A one-dimensional Gaussian kernel density of y in each group (scipy's
    gaussian_kde, Scott's bandwidth times bw), for Histogram's Kernel
    Density style and the Violin."""
    r = _rows(table, rows)
    c, k = _codes(codes, len(r), k)
    yv = _num(table, y, r)
    f = _freq(table, freq, r, len(r))
    ok = np.isfinite(yv) & (f > 0) & (c >= 0) & (c < k)
    yv, f, c = yv[ok], f[ok], c[ok]
    out = []
    for idx in _split(c, k):
        ys, ws = yv[idx], f[idx]
        if len(idx) < 2 or np.ptp(ys) == 0:
            out.append({'error': 'too few distinct values'})
            continue
        kde = stats.gaussian_kde(ys, weights=None if np.all(ws == 1) else ws)
        if bw != 1:
            kde.set_bandwidth(kde.factor * float(bw))
        h = float(np.sqrt(kde.covariance[0, 0]))
        a = float(lo) if lo is not None else ys.min() - 3 * h
        b = float(hi) if hi is not None else ys.max() + 3 * h
        g = np.linspace(a, b, grid)
        out.append({'y': g, 'd': kde(g), 'n': float(ws.sum()), 'bandwidth': h})
    return {'densities': out}


# ---- Mosaic: the chi-square test of the cells ----------------------------------------
@api('graph.chisq')
def chisq(tables, x=None, y=None, table=None, rows=None, table_name='data'):
    """Pearson's and the likelihood-ratio chi-square test of independence of
    each contingency table (rows: X levels, columns: Y levels), from
    scipy.stats.chi2_contingency."""
    out = []
    for t in tables:
        a = np.asarray(t, dtype=float)
        a = a[a.sum(axis=1) > 0][:, a.sum(axis=0) > 0] if a.size else a
        if a.ndim != 2 or a.shape[0] < 2 or a.shape[1] < 2:
            out.append({'error': 'needs two levels of each variable'})
            continue
        chi2, p, df, expected = stats.chi2_contingency(a, correction=False)
        g2, gp, _, _ = stats.chi2_contingency(a, correction=False, lambda_='log-likelihood')
        out.append({'chi2': chi2, 'p': p, 'df': df, 'lr': g2, 'lr_p': gp, 'n': a.sum(), 'min_expected': float(expected.min())})
    return {'tests': out}


# ---- Contour Plot and Surface Plot: values on a grid -----------------------------------
@api('graph.interp')
def interp(table, x, y, z, rows=None, method='linear', grid=60, table_name='data'):
    """z interpolated on a regular grid over the range of x and y
    (scipy.interpolate.griddata: linear or cubic on the Delaunay
    triangulation, or nearest); outside the points' hull there is no value.
    Points at the same (x, y) are averaged first."""
    r = _rows(table, rows)
    xv, yv, zv = _num(table, x, r), _num(table, y, r), _num(table, z, r)
    ok = np.isfinite(xv) & np.isfinite(yv) & np.isfinite(zv)
    xv, yv, zv = xv[ok], yv[ok], zv[ok]
    if len(xv) < 3:
        return {'error': 'fewer than three points with X, Y and Z'}
    pts, inv = np.unique(np.c_[xv, yv], axis=0, return_inverse=True)
    inv = np.asarray(inv).ravel()
    zu = np.bincount(inv, weights=zv) / np.bincount(inv)
    if len(pts) < 3 or np.ptp(pts[:, 0]) == 0 or np.ptp(pts[:, 1]) == 0:
        return {'error': 'X and Y need at least three distinct points that are not on a line'}
    if method == 'cubic' and len(pts) < 4:
        method = 'linear'
    gx = np.linspace(pts[:, 0].min(), pts[:, 0].max(), grid)
    gy = np.linspace(pts[:, 1].min(), pts[:, 1].max(), grid)
    GX, GY = np.meshgrid(gx, gy)
    try:
        gz = griddata(pts, zu, (GX, GY), method=method)
    except Exception as e:  # Qhull: the points are on a line
        return {'error': f'the points cannot be triangulated: {str(e).splitlines()[0]}'}
    return {'x': gx, 'y': gy, 'z': gz, 'n': int(len(xv)), 'points': int(len(pts)), 'method': method,
            'zmin': float(np.nanmin(gz)) if np.isfinite(gz).any() else None, 'zmax': float(np.nanmax(gz)) if np.isfinite(gz).any() else None}


# ---- Bean: statsmodels' beanplot, one violin per group ---------------------------------
class _NoAxes:
    """Where statsmodels would draw a violin: nowhere, the page draws it."""

    def fill_betweenx(self, *args, **kwargs):
        return None


def _bean_opts(bw, cutoff, cutoff_val):
    opts = {'cutoff': bool(cutoff), 'cutoff_val': float(cutoff_val), 'cutoff_type': 'std'}
    if float(bw) != 1:
        scale = float(bw)
        opts['bw_factor'] = lambda kde: kde.scotts_factor() * scale
    return opts


def _violin(ys, ws, bw, cutoff, cutoff_val):
    """One group of statsmodels' beanplot: its _single_violin (a Gaussian
    kernel density, scipy's gaussian_kde with Scott's factor times bw, at 100
    points from the minimum to the maximum, widened on each side by
    cutoff_val standard deviations unless cut at the data) scaled to 1 at its
    peak, and the mean and median beanplot marks. A whole-number Freq counts
    a row that many times; any other Freq weights the same density."""
    from statsmodels.graphics.boxplots import _single_violin
    opts = _bean_opts(bw, cutoff, cutoff_val)
    rep = None if np.all(ws == 1) else _replicate(ws)
    if np.all(ws == 1) or rep is not None:
        v = ys if rep is None else np.repeat(ys, rep)
        grid, violin = _single_violin(_NoAxes(), 0.0, v, 1.0, 'both', opts)
        kde = stats.gaussian_kde(v, bw_method=opts.get('bw_factor'))
        return {'y': grid, 'd': violin, 'mean': float(np.mean(v)), 'median': float(np.median(v)), 'n': float(len(v)),
                'bandwidth': float(np.sqrt(kde.covariance[0, 0]))}
    from statsmodels.stats.weightstats import DescrStatsW
    kde = stats.gaussian_kde(ys, bw_method=opts.get('bw_factor'), weights=ws)
    W = float(ws.sum())
    m = float(np.sum(ws * ys) / W)
    s = 0.0 if cutoff else float(cutoff_val) * float(np.sqrt(np.sum(ws * (ys - m) ** 2) / W))
    grid = np.linspace(ys.min() - s, ys.max() + s, 100)
    d = kde(grid)
    return {'y': grid, 'd': d / d.max(), 'mean': m, 'median': float(DescrStatsW(ys, weights=ws).quantile([0.5], return_pandas=False)[0]),
            'n': W, 'bandwidth': float(np.sqrt(kde.covariance[0, 0])), 'weighted': True}


@api('graph.bean')
def bean(table, y, rows=None, codes=None, k=None, bw=1.0, cutoff=False, cutoff_val=1.5, freq=None, by=None, table_name='data'):
    """Graph Builder's Bean: statsmodels' beanplot of y in each group (the
    violin, the mean line and the median mark; the page draws a line per
    observation), and the n of each group, from which the page takes the
    overall mean line of Kampstra's bean plot. A group with fewer than two
    distinct values gets its marks and no violin."""
    r = _rows(table, rows)
    c, k = _codes(codes, len(r), k)
    yv = _num(table, y, r)
    f = _freq(table, freq, r, len(r))
    ok = np.isfinite(yv) & (f > 0) & (c >= 0) & (c < k)
    yv, f, c = yv[ok], f[ok], c[ok]
    out = []
    for idx in _split(c, k):
        ys, ws = yv[idx], f[idx]
        if not len(idx):
            out.append({'error': 'no values', 'n': 0.0})
            continue
        if len(idx) < 2 or np.ptp(ys) == 0:
            out.append({'error': 'too few distinct values for a violin', 'n': float(ws.sum()), 'mean': float(np.average(ys, weights=ws)), 'median': float(np.median(ys))})
            continue
        try:
            out.append(_violin(ys, ws, bw, cutoff, cutoff_val))
        except Exception as e:  # one group's failure should not lose the others
            out.append({'error': str(e), 'n': float(ws.sum()), 'mean': float(np.average(ys, weights=ws))})
    return {'beans': out}


# ---- Functional Data Plot: the curves ----------------------------------------------------
_NUMBER = re.compile(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?')


def _name_values(names):
    """The number in each column name ('0', '2.5', 'week 3', 'T12'); None
    unless every name holds exactly one and no two are the same."""
    vals = []
    for s in names:
        m = _NUMBER.findall(str(s))
        if len(m) != 1:
            return None
        vals.append(float(m[0]))
    return vals if len(set(vals)) == len(vals) else None


def _curves(table, layout, y, rows, id=None, x=None, xmode='names'):
    """The curves as a matrix (a row per curve, a column per point along
    them), the points' X, and the page's rows of each curve.

    layout 'wide' (JMP's Rows as Functions): each row is a curve, the Y
    columns its values. X is the number in each column name (xmode
    'names', when every name holds one; the columns are then taken in the
    order of X) or the column order. A row with a missing value is left out.

    layout 'long' (Stacked): the ID column names the curve of each row, X
    (or the order of an ID's rows) places Y along it; values at the same X
    are averaged. When every curve has the same X values, they are the
    points; otherwise each curve is interpolated linearly (numpy.interp) to
    equally spaced points, as many as a curve has in the median, over the
    range of X that every curve covers."""
    r = _rows(table, rows)
    notes = []
    if layout != 'long':
        names = [c for c in (y if isinstance(y, (list, tuple)) else [y]) if c]
        if len(names) < 2:
            raise ValueError('Rows as Functions needs two or more Y columns, a column for each point along the curves')
        M = np.column_stack([_num(table, c, r) for c in names])
        xs = _name_values(names) if xmode != 'order' else None
        source = 'names' if xs is not None else 'order'
        if xs is None:
            if xmode != 'order':
                notes.append(f'The Y column names are not all numbers: X is the column order, 1 to {len(names)}.')
            xs = list(range(1, len(names) + 1))
        xs = np.asarray(xs, dtype=float)
        order = np.argsort(xs, kind='stable')
        if np.any(order != np.arange(len(order))):
            notes.append('The Y columns are taken in the order of the numbers in their names.')
        xs, M, names = xs[order], M[:, order], [names[i] for i in order]
        ok = np.all(np.isfinite(M), axis=1)
        return {'layout': 'wide', 'Y': M[ok], 'x': xs, 'rows': [[int(v)] for v in r[ok]], 'names': names, 'source': source,
                'dropped': int(np.sum(~ok)), 'interp': None, 'averaged': False, 'notes': notes}
    yname = y[0] if isinstance(y, (list, tuple)) else y
    if not id or not yname:
        raise ValueError('Stacked data needs an ID column (a curve for each level) and a Y column')
    yv = _num(table, yname, r)
    xv = _num(table, x, r) if x else None
    m = data.meta(table, id)
    iv = data.raw(table, id, r)
    if m.get('dataType') == 'numeric':
        iv = np.asarray(iv, dtype=float)
        has = np.isfinite(iv)
    else:
        has = np.array([v is not None for v in iv], dtype=bool)
    ok = has & np.isfinite(yv) & (np.isfinite(xv) if xv is not None else True)
    levels = m.get('levels') if m.get('modelingType') in ('nominal', 'ordinal') and m.get('levels') else None
    if levels is None:
        levels = sorted({float(v) for v in iv[ok]}) if m.get('dataType') == 'numeric' else sorted({v for v in iv[ok]})
    pos = {v: i for i, v in enumerate(levels)}
    code = np.array([pos.get(v, -1) for v in iv[ok]], dtype=int)
    rr, yy = r[ok][code >= 0], yv[ok][code >= 0]
    xx = xv[ok][code >= 0] if xv is not None else None
    code = code[code >= 0]
    per = []
    averaged = False
    for g, idx in enumerate(_split(code, len(levels))):
        if not len(idx):
            continue
        idx = np.sort(idx)
        xg = xx[idx] if xx is not None else np.arange(1, len(idx) + 1, dtype=float)
        ux, inv = np.unique(xg, return_inverse=True)
        uy = np.bincount(inv, weights=yy[idx]) / np.bincount(inv)
        averaged = averaged or len(ux) < len(xg)
        per.append((levels[g], rr[idx], ux, uy))
    if not per:
        raise ValueError('no curve has a value')
    interp = None
    same = all(len(q[2]) == len(per[0][2]) and np.array_equal(q[2], per[0][2]) for q in per)
    if same:
        grid, Y = per[0][2], np.array([q[3] for q in per])
    else:
        use = [q for q in per if len(q[2]) >= 2]
        if not use:
            raise ValueError('no curve has two or more points')
        lo, hi = max(q[2][0] for q in use), min(q[2][-1] for q in use)
        if not hi > lo:
            raise ValueError('the curves have no range of X in common, so they cannot be put on common points')
        npts = int(np.clip(np.median([len(q[2]) for q in use]), 2, 500))
        grid = np.linspace(lo, hi, npts)
        Y = np.array([np.interp(grid, q[2], q[3]) for q in use])
        interp = {'lo': float(lo), 'hi': float(hi), 'points': npts, 'left_out': len(per) - len(use)}
        per = use
    if len(grid) < 2:
        raise ValueError('the curves need two or more points each')
    return {'layout': 'long', 'Y': Y, 'x': np.asarray(grid, dtype=float), 'rows': [[int(v) for v in q[1]] for q in per],
            'keys': [q[0] for q in per], 'source': 'column' if x else 'order', 'dropped': 0, 'interp': interp, 'averaged': averaged, 'notes': notes}


def _curves_code(layout, C, y, id, x):
    """The Python that reads the curves from the CSV export: a function
    curves(d) -> (x, data, ids), data a row per curve."""
    if layout != 'long':
        cols = C['names']
        xs = [float(v) for v in C['x']]
        xtxt = 'the numbers in the column names' if C['source'] == 'names' else 'the column order'
        return [f'cols = {_j(cols)}   # the Y columns, in the order of X',
                'def curves(d):',
                '    d = d.dropna(subset=cols)   # a curve per row that has every value',
                f'    return np.array({xs!r}), d[cols].to_numpy(), d.index + 1   # X: {xtxt}; rows numbered from 1, as the page']
    yname = y[0] if isinstance(y, (list, tuple)) else y
    lines = ['def curves(d):', f'    d = d.dropna(subset={_j([c for c in (id, x, yname) if c])})']
    xcol = x
    if not x:
        lines.append(f'    d = d.assign(_x=d.groupby({_j(id)}).cumcount() + 1.0)   # X: the order of each ID\'s rows')
        xcol = '_x'
    lines += [f'    means = {{k: g.groupby({_j(xcol)})[{_j(yname)}].mean() for k, g in d.groupby({_j(id)})}}   # a curve per ID; the same X averaged',
              '    xs = [s.index.to_numpy(float) for s in means.values()]',
              '    if all(len(v) == len(xs[0]) and np.array_equal(v, xs[0]) for v in xs):   # the same X for every curve',
              '        return xs[0], np.array([s.to_numpy() for s in means.values()]), list(means)',
              '    means = {k: s for k, s in means.items() if len(s) > 1}',
              '    lo, hi = max(s.index.min() for s in means.values()), min(s.index.max() for s in means.values())',
              '    x = np.linspace(lo, hi, int(np.clip(np.median([len(s) for s in means.values()]), 2, 500)))   # the X every curve covers',
              '    return x, np.array([np.interp(x, s.index.to_numpy(float), s.to_numpy()) for s in means.values()]), list(means)']
    return lines


# ---- Functional Data Plot: band depth and the functional boxplot -------------------------
def _band_depth(Y, method):
    """statsmodels' banddepth, 'MBD' or 'BD2'; or 'BD2x', the band depth
    counted from its definition (Lopez-Pintado and Romo): the share of the
    bands of two curves that hold the curve at every point, a curve on a
    band's edge being in it. statsmodels' BD2 is the rank formula
    ((n - highest rank)(lowest rank - 1) + n - 1) / C(n, 2), which counts
    pairs of curves that do not make a band around the curve."""
    if method == 'BD2x':
        n = len(Y)
        cnt = np.empty(n)
        for i in range(n):
            s = np.sign(Y - Y[i])
            up, dn = (s > 0).astype(float), (s < 0).astype(float)
            clash = up @ up.T + dn @ dn.T      # the points where both curves of a pair are above, or both below
            cnt[i] = np.count_nonzero(np.triu(clash == 0, 1))
        return cnt / (n * (n - 1) / 2)
    from statsmodels.graphics.functional import banddepth
    return banddepth(Y, method='BD2' if method == 'BD2' else 'MBD')


def _ties(Y):
    """How many values equal another at the same point."""
    return int(sum(Y.shape[0] - len(np.unique(Y[:, j])) for j in range(Y.shape[1])))


@api('graph.fbox')
def fbox(table, y=None, rows=None, layout='wide', id=None, x=None, xmode='names', method='MBD', wfactor=1.5,
         rule='statsmodels', by=None, table_name='data'):
    """statsmodels' functional boxplot (fboxplot) without its figure: the
    curves ordered by band depth (banddepth, 'MBD' or 'BD2', or 'BD2x'
    counted), the median (the deepest curve), the 50% central region (the
    envelope of the n // 2 deepest curves), the fences and the outliers (a
    curve that passes a fence at any point), and the envelope of the curves
    that are not outliers. rule 'statsmodels': fboxplot's fences, the
    central region stretched wfactor times about the pointwise median of its
    curves; 'sungenton': Sun and Genton's (R's fda::fbplot), the region's
    envelope plus wfactor times its range."""
    C = _curves(table, layout, y, rows, id, x, xmode)
    Y = C['Y']
    n, p = Y.shape
    base = {'layout': C['layout'], 'x': C['x'], 'curves': Y, 'rows': C['rows'], 'n': n, 'p': p, 'dropped': C['dropped'],
            'interp': C['interp'], 'averaged': C['averaged'], 'source': C['source'], 'names': C.get('names'), 'notes': list(C['notes'])}
    if n < 3:
        return {**base, 'error': f'{n} complete curve{"" if n == 1 else "s"}: a functional boxplot needs three or more'}
    method = method if method in ('MBD', 'BD2', 'BD2x') else 'MBD'
    if method == 'BD2x' and n > BD2_COUNTED:
        base['notes'].append(f'The band depth is counted for up to {BD2_COUNTED} curves; for {n}, statsmodels\' formula is used.')
        method = 'BD2'
    depth = np.asarray(_band_depth(Y, method), dtype=float)
    ix = np.argsort(depth)[::-1]              # fboxplot's order: the deepest curve first
    rank = np.empty(n, dtype=int)
    rank[ix] = np.arange(1, n + 1)
    half = n // 2
    central = Y[ix[:half]]
    lower, upper = central.min(axis=0), central.max(axis=0)
    inner = np.median(central, axis=0)
    wf = float(wfactor)
    if rule == 'sungenton':
        lo_f, hi_f = lower - wf * (upper - lower), upper + wf * (upper - lower)
    else:
        rule = 'statsmodels'
        lo_f, hi_f = inner - (inner - lower) * wf, inner + (upper - inner) * wf
    outlier = np.any(Y > hi_f, axis=1) | np.any(Y < lo_f, axis=1)
    keep = Y[~outlier] if np.any(~outlier) else central
    return {**base, 'method': method, 'rule': rule, 'wfactor': wf, 'depth': depth, 'rank': rank, 'median': int(ix[0]),
            'order': ix, 'central': half, 'lower': lower, 'upper': upper, 'inner': inner, 'fence_lo': lo_f, 'fence_hi': hi_f,
            'outlier': outlier, 'env_lo': keep.min(axis=0), 'env_hi': keep.max(axis=0), 'ties': _ties(Y)}


def _fbox_def_lines(method, rule, wf):
    """The Python of the functional boxplot of the curves (graph.fbox's): a
    function of the data, a curve per row."""
    body = []
    if method == 'BD2x':
        body += ['def counted_bd2(data):   # the band depth counted from its definition: the bands of two curves that hold the curve at every point',
                 '    n, out = len(data), []',
                 '    for i in range(n):',
                 '        s = np.sign(data - data[i])',
                 '        clash = (s > 0).astype(float) @ (s > 0).T + (s < 0).astype(float) @ (s < 0).T   # both above, or both below',
                 '        out.append(np.count_nonzero(np.triu(clash == 0, 1)) / (n * (n - 1) / 2))',
                 '    return np.array(out)']
        depth_line = '    depth = counted_bd2(data)'
    else:
        depth_line = f'    depth = banddepth(data, method={_j(method)})   # statsmodels\' band depth of each curve'
    fence = ('    fence_lo, fence_hi = lower - wfactor * (upper - lower), upper + wfactor * (upper - lower)   # Sun and Genton\'s fences'
             if rule == 'sungenton' else
             '    fence_lo, fence_hi = m - wfactor * (m - lower), m + wfactor * (upper - m)   # fboxplot\'s fences')
    body += [f'def functional_boxplot(data, wfactor={wf:g}):',
             depth_line,
             '    order = np.argsort(depth)[::-1]              # the deepest first, as fboxplot orders them',
             '    central = data[order[: len(data) // 2]]      # the 50% central region: the deepest half',
             '    lower, upper = central.min(axis=0), central.max(axis=0)',
             '    m = np.median(central, axis=0)',
             fence,
             '    outlier = ((data < fence_lo) | (data > fence_hi)).any(axis=1)',
             '    keep = data[~outlier] if (~outlier).any() else central',
             '    return dict(depth=depth, rank=order.argsort() + 1, order=order, median=order[0], lower=lower, upper=upper,',
             '                fence_lo=fence_lo, fence_hi=fence_hi, outlier=outlier, envelope=(keep.min(axis=0), keep.max(axis=0)))']
    return body


# ---- Functional Data Plot: the HDR boxplot ------------------------------------------------
def _kde_at(S, bw, pts, chunk=4096):
    """statsmodels' KDEMultivariate density (a product of Gaussian kernels
    with the bandwidths bw) at many points at once: its gpke sum, vectorized."""
    out = np.empty(len(pts))
    norm = len(S) * np.prod(bw) * (2 * np.pi) ** (S.shape[1] / 2)
    for a in range(0, len(pts), chunk):
        z = (pts[a:a + chunk, None, :] - S[None, :, :]) / bw
        out[a:a + chunk] = np.exp(-0.5 * np.einsum('ijk,ijk->ij', z, z)).sum(axis=1) / norm
    return out


def _crossings(g1, g2, Z, level):
    """The points on the grid's edges where Z crosses level, by linear
    interpolation: the level's contour, as marching squares finds it."""
    pts = []
    a, b = Z[:-1, :], Z[1:, :]
    i, j = np.nonzero((a - level) * (b - level) < 0)
    f = (level - a[i, j]) / (b[i, j] - a[i, j])
    pts.append(np.c_[g1[i] + f * (g1[i + 1] - g1[i]), g2[j]])
    a, b = Z[:, :-1], Z[:, 1:]
    i, j = np.nonzero((a - level) * (b - level) < 0)
    f = (level - a[i, j]) / (b[i, j] - a[i, j])
    pts.append(np.c_[g1[i], g2[j] + f * (g2[j + 1] - g2[j])])
    return np.vstack(pts)


@api('graph.hdr')
def hdr(table, y=None, rows=None, layout='wide', id=None, x=None, xmode='names', threshold=0.95, bw='normal_reference',
        grid=HDR_GRID, by=None, table_name='data'):
    """statsmodels' HDR boxplot (hdrboxplot) without its figure. As there:
    the principal components of the curves (statsmodels PCA, two components,
    each point standardized), a Gaussian kernel density of the two scores
    (KDEMultivariate, normal reference bandwidths), the density's levels at
    its 50th, 10th and (1 - threshold) percentiles at the curves (numpy's
    midpoint rule), the outliers (density below the last), the modal curve
    (the curve rebuilt from the density's highest point), and the 50% and
    90% bands: the pointwise range of the curves rebuilt from the scores in
    each region, within the range of the scores; the 90% band from the
    region outside the 50% one, as hdrboxplot takes it. hdrboxplot searches
    for each end of each band with differential evolution (or a brute-force
    grid); here the rebuilt curve, affine in the scores, is taken at the
    grid points inside the region and where its contour crosses the grid's
    edges (a grid x grid lattice over the scores' range), and the mode is
    polished with Nelder-Mead from the grid's best point. A point where
    every curve has the same value is left out of the PCA (it cannot be
    standardized) and keeps that value."""
    from scipy import optimize
    from statsmodels.graphics.functional import _inverse_transform
    from statsmodels.multivariate.pca import PCA
    from statsmodels.nonparametric.kernel_density import KDEMultivariate
    C = _curves(table, layout, y, rows, id, x, xmode)
    Y = C['Y']
    n, p = Y.shape
    base = {'layout': C['layout'], 'x': C['x'], 'rows': C['rows'], 'n': n, 'p': p, 'notes': list(C['notes'])}
    if n < 5:
        return {**base, 'error': f'{n} complete curve{"" if n == 1 else "s"}: an HDR boxplot needs five or more'}
    vary = Y.std(axis=0) > 1e-12 * max(1.0, float(np.abs(Y).max()))
    if vary.sum() < 2:
        return {**base, 'error': 'the curves differ at fewer than two points'}
    thr = float(threshold)
    if not 0.5 < thr < 1:
        return {**base, 'error': 'the outlier threshold must be between 0.5 and 1'}
    bw = bw if bw in ('normal_reference', 'cv_ml', 'cv_ls') else 'normal_reference'
    Yv = Y[:, vary]
    pca = PCA(Yv, ncomp=2)
    S = np.asarray(pca.factors, dtype=float)[:, :2]
    ks = KDEMultivariate(S, bw=bw, var_type='cc')
    dens = np.atleast_1d(np.asarray(ks.pdf(S), dtype=float))
    alpha = sorted([thr, 0.9, 0.5], reverse=True)
    level = {a: float(np.percentile(dens, (1 - a) * 100, method='midpoint')) for a in alpha}
    outlier = dens < level[thr]
    lo, hi = S.min(axis=0), S.max(axis=0)
    G = int(np.clip(grid, 21, 401))
    g1, g2 = np.linspace(lo[0], hi[0], G), np.linspace(lo[1], hi[1], G)
    A, B = np.meshgrid(g1, g2, indexing='ij')
    nodes = np.c_[A.ravel(), B.ravel()]
    Z = _kde_at(S, np.asarray(ks.bw, dtype=float), nodes).reshape(G, G)
    a0 = np.asarray(_inverse_transform(pca, np.zeros((1, 2))), dtype=float)[0]
    M = np.asarray(_inverse_transform(pca, np.eye(2)), dtype=float) - a0

    def rebuild(s):
        full = np.tile(Y[0], (len(s), 1))
        full[:, vary] = a0 + s @ M
        return full

    def band(pmin, pmax):
        inside = (Z > pmin) & (Z < pmax)
        pts = [nodes[inside.ravel()], _crossings(g1, g2, Z, pmin)]
        if pmax < 1e6:
            pts.append(_crossings(g1, g2, Z, pmax))
        P = np.vstack(pts)
        if not len(P):
            return [None, None]
        top, bot = np.full(p, -np.inf), np.full(p, np.inf)
        for a in range(0, len(P), 4096):
            V = rebuild(P[a:a + 4096])
            top, bot = np.maximum(top, V.max(axis=0)), np.minimum(bot, V.min(axis=0))
        return [top, bot]

    k0 = int(np.argmax(Z))
    res = optimize.minimize(lambda s: -float(np.ravel(ks.pdf(s.reshape(1, -1)))[0]), nodes[k0], method='Nelder-Mead',
                            bounds=list(zip(lo, hi)), options={'xatol': 1e-10, 'fatol': 1e-14, 'maxiter': 4000})
    mode = res.x if -res.fun >= Z.ravel()[k0] else nodes[k0]
    pad = 0.25 * (hi - lo)
    d1, d2 = np.linspace(lo[0] - pad[0], hi[0] + pad[0], 81), np.linspace(lo[1] - pad[1], hi[1] + pad[1], 81)
    DA, DB = np.meshgrid(d1, d2, indexing='ij')
    DZ = _kde_at(S, np.asarray(ks.bw, dtype=float), np.c_[DA.ravel(), DB.ravel()]).reshape(81, 81)
    rsq = np.asarray(pca.rsquare, dtype=float)
    return {**base, 'scores': S, 'explained': [float(rsq[1]), float(rsq[2] - rsq[1])] if len(rsq) > 2 else None, 'bw': np.asarray(ks.bw, dtype=float),
            'bw_method': bw, 'density': dens, 'levels': {'50': level[0.5], '90': level[0.9], 'threshold': level[thr]}, 'threshold': thr,
            'outlier': outlier, 'mode': mode, 'modal': rebuild(np.asarray(mode)[None])[0], 'hdr50': band(level[0.5], 1e6),
            'hdr90': band(level[0.9], level[0.5]), 'constant': int((~vary).sum()), 'grid_n': G,
            'grid': {'x': d1, 'y': d2, 'z': DZ.T}}


def _hdr_def_lines(vary_all, thr, G, bw):
    """The Python of the HDR boxplot of the curves (graph.hdr's): a function
    of the data, a curve per row; it gives back the density of the scores
    (kde) and the variance the two components hold too, for the score plot."""
    body = ['from scipy import optimize',
            'from statsmodels.graphics.functional import _inverse_transform   # hdrboxplot\'s own: scores back to curves',
            'from statsmodels.multivariate.pca import PCA',
            'from statsmodels.nonparametric.kernel_density import KDEMultivariate',
            f'def hdr_boxplot(data, threshold={thr:g}, n_grid={G}):']
    if not vary_all:
        body += ['    vary = data.std(axis=0) > 0   # a point where every curve is the same cannot be standardized: left out of the PCA',
                 '    full, data = data, data[:, vary]']
    body += ['    pca = PCA(data, ncomp=2)                       # as hdrboxplot: each point standardized',
             '    scores = np.asarray(pca.factors)',
             f'    kde = KDEMultivariate(scores, bw={_j(bw)}, var_type="cc")',
             '    dens = kde.pdf(scores)                         # the density at each curve',
             '    lev = {a: np.percentile(dens, 100 * (1 - a), method="midpoint") for a in (threshold, 0.9, 0.5)}',
             '    g1, g2 = (np.linspace(a, b, n_grid) for a, b in zip(scores.min(axis=0), scores.max(axis=0)))',
             '    G1, G2 = np.meshgrid(g1, g2, indexing="ij")',
             '    z = kde.pdf(np.c_[G1.ravel(), G2.ravel()]).reshape(G1.shape)   # the density over the scores\' range',
             '    def edge(level):   # where the density crosses level on the grid\'s edges: its contour',
             '        out = []',
             '        for z0, z1, a0, a1, b0, b1 in ((z[:-1], z[1:], G1[:-1], G1[1:], G2[:-1], G2[1:]), (z[:, :-1], z[:, 1:], G1[:, :-1], G1[:, 1:], G2[:, :-1], G2[:, 1:])):',
             '            m = (z0 - level) * (z1 - level) < 0',
             '            f = (level - z0[m]) / (z1[m] - z0[m])',
             '            out.append(np.c_[a0[m] + f * (a1[m] - a0[m]), b0[m] + f * (b1[m] - b0[m])])',
             '        return np.vstack(out)']
    rebuild_txt = '_rebuild(_inverse_transform(pca, pts))' if not vary_all else '_inverse_transform(pca, pts)'
    if not vary_all:
        body += ['    def _rebuild(v):',
                 '        out = np.tile(full[0], (len(v), 1))',
                 '        out[:, vary] = v',
                 '        return out']
    body += ['    def band(lo, hi):   # the pointwise range of the curves rebuilt from the scores in a region',
             '        inside = (z > lo) & (z < hi)',
             '        pts = np.vstack([np.c_[G1[inside], G2[inside]], edge(lo)] + ([edge(hi)] if hi < 1e6 else []))',
             f'        curves = {rebuild_txt}',
             '        return curves.max(axis=0), curves.min(axis=0)',
             '    best = np.unravel_index(z.argmax(), z.shape)',
             '    mode = optimize.minimize(lambda s: -kde.pdf(s[None]), [g1[best[0]], g2[best[1]]], method="Nelder-Mead",',
             '                             bounds=[(g1[0], g1[-1]), (g2[0], g2[-1])], options={"xatol": 1e-10, "fatol": 1e-14, "maxiter": 4000}).x',
             '    return dict(scores=scores, dens=dens, levels=lev, outlier=dens < lev[threshold], mode=mode, kde=kde,',
             '                explained=(pca.rsquare[1], pca.rsquare[2] - pca.rsquare[1]),',
             f'                modal={rebuild_txt.replace("pts", "mode[None]")}[0], hdr50=band(lev[0.5], 1e6), hdr90=band(lev[0.9], lev[0.5]))   # hdrboxplot takes the 90% band outside the 50% one']
    return body



# =====================================================================================
# The graphs as matplotlib code
# =====================================================================================
# Under every graph of the Graph menu the page shows Python that draws the same
# graph with matplotlib from a CSV export of the table, as the notebook runs it:
# the report's rows, the page's colours in its light theme, the graph's size at
# 100 pixels an inch. The page sends a plan of what it drew (the columns in the
# zones and the levels it found, the panels, the elements with their settings,
# and what it chose itself: bins, the jitter's geometry). What the page and the
# functions above compute from the data (counts, summaries, jitter, smoothers,
# fits, densities) the code computes from the data, by the same methods; only
# what the page chose is written into it as numbers. graph.code writes it.
PALETTE = ['#2f6690', '#d9822b', '#3a7d44', '#b0413e', '#6c5b7b', '#1f9e89', '#c0a000', '#8c564b', '#e377c2', '#7f7f7f', '#17becf', '#9467bd']
TEXT, MUTED, GRIDLINE, SURFACE = '#352921', '#786b5d', '#e0d7ce', '#fcf7f2'   # kvot.css, light theme
POINT, INK, BAR, FIT_RED, BOX_BLUE, MISSING = '#2f6690', '#1f4e79', '#8fa9c2', '#b0413e', '#4a6f94', '#aaaaaa'
RAMP = ['#2f6ec7', '#b0b0b0', '#c0392b']        # the page's blue-grey-red (SM.util.ramp at 0, 0.5, 1)
HEAT = ['#eef3f8', '#7aa3c8', '#1f4e79']        # a heatmap's counts, light theme
PX = 0.72                                       # points per pixel: a figure at 100 pixels an inch


class _Py:
    """Python source, a line at a time, indented by blocks."""

    def __init__(self):
        self.lines = []
        self.ind = 0

    def __call__(self, *lines):
        for ln in lines:
            if ln is not None:
                self.lines.append(('    ' * self.ind + ln) if ln else '')
        return self

    def block(self, head):
        py = self

        class _Block:
            def __enter__(self):
                py(head)
                py.ind += 1

            def __exit__(self, *exc):
                py.ind -= 1
        return _Block()

    def text(self):
        return '\n'.join(self.lines)


def _py(v):
    """A JSON value as a Python literal: text in double quotes, a whole
    number without a point."""
    if v is None:
        return 'None'
    if isinstance(v, bool):
        return 'True' if v else 'False'
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        v = float(v)
        if v != v:
            return 'np.nan'
        if v in (float('inf'), float('-inf')):
            return 'np.inf' if v > 0 else '-np.inf'
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
    if isinstance(v, (list, tuple)):
        return '[' + ', '.join(_py(x) for x in v) + ']'
    return json.dumps(v)


def _nm(v, sig=6):
    """A number for the code, rounded where the page's choice was rounder."""
    v = float(v)
    return _py(float(f'{v:.{sig}g}')) if abs(v) < 1e15 else _py(v)


def _inch(px):
    return f'{round(float(px)) / 100:g}'


def _js_number(v):
    """A number as the page's String() writes it (a level's label)."""
    v = float(v)
    if v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    r = repr(v)
    if 'e' in r:
        m, e = r.split('e')
        return f'{m}e{"+" if int(e) >= 0 else "-"}{abs(int(e))}'
    return r


def _is_date(table, name):
    try:
        m = data.meta(table, name)
    except KeyError:
        return False
    return m.get('dataType') == 'numeric' and (m.get('format') or {}).get('kind') in ('date', 'datetime')


def _value_text(table, name, v):
    """A value as the page shows it: a date as its day, a number as String()
    writes it."""
    if v is None:
        return ''
    if isinstance(v, (int, float)) and _is_date(table, name):
        import datetime
        d = datetime.datetime(1970, 1, 1) + datetime.timedelta(milliseconds=float(v))
        kind = (data.meta(table, name).get('format') or {}).get('kind')
        return d.strftime('%Y-%m-%d %H:%M:%S' if kind == 'datetime' else '%Y-%m-%d')
    return _js_number(v) if isinstance(v, (int, float)) else str(v)


def _keep_lines(table, rows, where=None):
    """After the head: the rows of the report's By group (the where lines),
    and of those the ones the report uses: excluded and filtered rows are
    dropped, as the other platforms' code drops them."""
    L = []
    n = data.TABLES[table]['n'] if table in data.TABLES else 0
    match = np.ones(n, dtype=bool)
    for w in where or []:
        col, val = w['column'], w['value']
        v = data.raw(table, col)
        if data.meta(table, col).get('dataType') == 'numeric':
            match &= np.asarray(v, dtype=float) == float(val)
        else:
            match &= np.array([x == val for x in v], dtype=bool)
        L.append(f'df = df[df[{_j(col)}] == {_py(val)}]   # only the rows where {one_line(col)} is {one_line(_value_text(table, col, val))}')
    if rows is not None and n:
        keep = np.zeros(n, dtype=bool)
        keep[np.asarray(rows, dtype=int)] = True
        drop = np.nonzero(match & ~keep)[0]
        if len(drop):
            L.append(f'df = df.drop(index=[{", ".join(str(int(r)) for r in drop)}])   # the rows the report leaves out')
    return L


def _whole(table, name, rows):
    """Whether a Freq column holds whole numbers where it is positive (a row
    then counts that many times, as rows repeated)."""
    f = np.asarray(data.raw(table, name, rows), dtype=float)
    f = f[np.isfinite(f) & (f > 0)]
    return bool(np.all(np.abs(f - np.round(f)) < 1e-9) and f.sum() <= 2_000_000)


# Functions the code defines when it needs them, each once, before the figure.
_HELPERS = {
    'hash01': [
        'def hash01(rows, salt):',
        '    """The page\'s jitter: a number in [0, 1) that belongs to each row (by its number), so that a redraw leaves every point where it was."""',
        '    h = (np.asarray(rows, dtype=np.uint64) + 1) ^ np.uint64((salt + 7) * 0x9E3779B1 & 0xFFFFFFFF)',
        '    h = h * 0x85EBCA6B & 0xFFFFFFFF',
        '    h ^= h >> 13',
        '    h = h * 0xC2B2AE35 & 0xFFFFFFFF',
        '    h ^= h >> 16',
        '    return h / 2.0 ** 32'],
    'normal': [
        'def normal_jitter(rows, salt, limit):',
        '    """Random Normal jitter: offsets from a normal distribution (Box-Muller on the rows\' own numbers), most near the middle."""',
        '    u = np.maximum(1e-9, hash01(rows, salt))',
        '    return np.clip(np.sqrt(-2 * np.log(u)) * np.cos(2 * np.pi * hash01(rows, salt + 11)) * limit / 6, -0.48, 0.48)'],
    'grid': [
        'def centered_grid(at, v, limit):',
        '    """Centered Grid jitter: at each place, the points in the same fortieth of the values\' range set side by side."""',
        '    at, v = np.asarray(at, dtype=float), np.asarray(v, dtype=float)',
        '    lo, hi = (v.min(), v.max()) if len(v) else (0.0, 1.0)',
        '    b = np.minimum(39, np.floor((v - lo) / (hi - lo) * 40)) if hi > lo else np.zeros(len(v))',
        '    cells = pd.DataFrame({"at": at, "b": b})',
        '    i = cells.groupby(["at", "b"]).cumcount().to_numpy()',
        '    d = min(0.09, 0.8 * limit / max(1, cells.value_counts().max() if len(v) else 1))',
        '    return np.ceil(i / 2) * np.where(i % 2 == 1, 1, -1) * d'],
    'packed': [
        'def packed(rows, at, v, value_px, level_px, diam, limit):',
        '    """Packed jitter, a beeswarm as the page packs it: at each place the points in order of their value, each at the offset nearest',
        '    the middle where it covers no point placed before it, in pixels (value_px and level_px: pixels per unit of the value axis and',
        '    per level); a place whose points need more than its room is squeezed into it. The offsets, in levels."""',
        '    rows, at, v = np.asarray(rows), np.asarray(at, dtype=float), np.asarray(v, dtype=float)',
        '    off = np.zeros(len(v))',
        '    room = 0.5 * limit * level_px',
        '    for place in np.unique(at):',
        '        idx = np.nonzero(at == place)[0]',
        '        idx = idx[np.lexsort((rows[idx], v[idx]))]   # in order of the value, then of the row',
        '        done, widest = [], 0.0   # the points placed, (value in pixels, offset), in order of the value',
        '        for i in idx:',
        '            vp = v[i] * value_px',
        '            blocked = []',
        '            for q, o in reversed(done):',
        '                if vp - q >= diam:',
        '                    break',
        '                half = np.sqrt(max(0.0, diam * diam - (vp - q) ** 2))',
        '                blocked.append((o - half, o + half))',
        '            places = sorted([0.0] + [c for ab in blocked for c in ab], key=lambda c: (abs(c), c))',
        '            o = next((c for c in places if all(c <= a + 1e-6 or c >= b - 1e-6 for a, b in blocked)), 0.0)',
        '            k = len(done)',
        '            while k > 0 and done[k - 1][0] > vp:',
        '                k -= 1',
        '            done.insert(k, (vp, o))',
        '            widest = max(widest, abs(o))',
        '            off[i] = o',
        '        off[idx] *= (room / widest if widest > room else 1.0) / level_px',
        '    return off'],
    'fmt': [
        'def fmt(v, sig=7):',
        '    """A number as the page writes it (as JMP does): up to sig significant digits, no trailing zeros, − for minus."""',
        '    if v is None or np.isnan(v):',
        '        return "."',
        '    if np.isinf(v):',
        '        return "∞" if v > 0 else "−∞"',
        '    if float(v).is_integer() and abs(v) < 1e15:',
        '        s = str(int(v))',
        '    elif abs(v) >= 1e9 or abs(v) < 1e-4:',
        '        m, e = f"{v:.{min(sig, 5) - 1}e}".split("e")',
        '        s = f"{m}e{int(e)}"',
        '    else:',
        '        s = np.format_float_positional(float(f"{v:.{sig}g}"), trim="-")',
        '    return "−" + s[1:] if s.startswith("-") else s'],
    'fmt_p': [
        'def fmt_p(p, alpha=0.05):',
        '    """A p-value as the page writes it: four decimals, <.0001, a star below alpha."""',
        '    return ("<.0001" if p < 0.0001 else f"{p:.4f}") + ("*" if p < alpha else "")'],
    'cauchy': [
        'class Cauchy(sm.robust.norms.RobustNorm):',
        '    """Cauchy weights 1 / (1 + (r/c)^2), c = 2.3849: JMP\'s Robust Cauchy fit."""',
        '    c = 2.3849',
        '',
        '    def rho(self, z):',
        '        return self.c ** 2 / 2 * np.log1p((np.asarray(z) / self.c) ** 2)',
        '',
        '    def psi(self, z):',
        '        return np.asarray(z) / (1 + (np.asarray(z) / self.c) ** 2)',
        '',
        '    def weights(self, z):',
        '        return 1 / (1 + (np.asarray(z) / self.c) ** 2)',
        '',
        '    def psi_deriv(self, z):',
        '        u = (np.asarray(z) / self.c) ** 2',
        '        return (1 - u) / (1 + u) ** 2'],
    'weighted': [
        'def weighted_stats(g, key, y, f, alpha):',
        '    """The statistics of y at each place (key), a row weighing f (a Freq that is not a whole number), as the page computes them:',
        '    weighted moments with the sum of f as N, and DescrStatsW\'s weighted quantiles."""',
        '    out = {}',
        '    for k, s in g.groupby(key):',
        '        v, w = s[y].to_numpy(float), s[f].to_numpy(float)',
        '        n = w.sum()',
        '        mean = np.sum(w * v) / n',
        '        var = np.sum(w * (v - mean) ** 2) / (n - 1) if n > 1 else np.nan',
        '        q1, median, q3 = DescrStatsW(v, weights=w).quantile([0.25, 0.5, 0.75], return_pandas=False)',
        '        out[k] = {"n": n, "sum": np.sum(w * v), "mean": mean, "sd": np.sqrt(var), "se": np.sqrt(var / n), "var": var,',
        '                  "min": v.min(), "max": v.max(), "q1": q1, "median": median, "q3": q3}',
        '    st = pd.DataFrame.from_dict(out, orient="index").sort_index()',
        '    st["lower"], st["upper"] = stats.t.interval(1 - alpha, st["n"] - 1, loc=st["mean"], scale=st["se"])',
        '    return st'],
    'curve': [
        'def curve(x, y, width, height):',
        '    """The Curve connection: Plotly\'s spline through the vertices (smoothing 1, its centripetal tangents), worked out on the',
        '    panel\'s pixels (width by height over the vertices\' span) as the page draws it, and sampled for matplotlib."""',
        '    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)',
        '    if len(x) < 3:',
        '        return x, y',
        '    sx, sy = width / (np.ptp(x) or 1.0), height / (np.ptp(y) or 1.0)',
        '    p = np.c_[x * sx, y * sy]',
        '    tangents = []',
        '    for a, b, c in zip(p[:-2], p[1:-1], p[2:]):',
        '        d1, d2 = a - b, c - b',
        '        l1, l2 = np.hypot(*d1) ** 0.5, np.hypot(*d2) ** 0.5',
        '        num = l2 * l2 * d1 - l1 * l1 * d2',
        '        tangents.append((b + (num / (3 * l2 * (l1 + l2)) if l2 else 0), b - (num / (3 * l1 * (l1 + l2)) if l1 else 0)))',
        '    t = np.linspace(0, 1, 16)[:, None]',
        '    parts = [(1 - t) ** 2 * p[0] + 2 * (1 - t) * t * tangents[0][0] + t ** 2 * p[1]]',
        '    for i in range(2, len(p) - 1):',
        '        a, b = tangents[i - 2][1], tangents[i - 1][0]',
        '        parts.append((1 - t) ** 3 * p[i - 1] + 3 * (1 - t) ** 2 * t * a + 3 * (1 - t) * t ** 2 * b + t ** 3 * p[i])',
        '    parts.append((1 - t) ** 2 * p[-2] + 2 * (1 - t) * t * tangents[-1][1] + t ** 2 * p[-1])',
        '    q = np.vstack(parts)',
        '    return q[:, 0] / sx, q[:, 1] / sy'],
    'box': [
        'def box(v, f=None, quantile=False):',
        '    """A box plot of the values v, a row counting f times (Freq), with JMP\'s quartiles, the (n + 1)p-th values: the whiskers reach',
        '    the furthest values within 1.5 IQR of the box and the values beyond are outliers (quantile=True: the minimum and the maximum)."""',
        '    v = np.asarray(v, dtype=float)',
        '    q1, med, q3 = np.quantile(v if f is None else np.repeat(v, np.asarray(f).round().astype(int)), [0.25, 0.5, 0.75], method="weibull")',
        '    if quantile:',
        '        return {"q1": q1, "med": med, "q3": q3, "whislo": v.min(), "whishi": v.max(), "fliers": []}',
        '    inside = v[(v >= q1 - 1.5 * (q3 - q1)) & (v <= q3 + 1.5 * (q3 - q1))]',
        '    lo, hi = inside.min(), inside.max()',
        '    return {"q1": q1, "med": med, "q3": q3, "whislo": lo, "whishi": hi, "fliers": v[(v < lo) | (v > hi)]}'],
    'wbox': [
        'def weighted_box(v, f, quantile=False):',
        '    """A box plot of the values v, a row weighing f (a Freq that is not a whole number), as the page draws it: DescrStatsW\'s weighted',
        '    quartiles, and the whiskers to the furthest values within 1.5 IQR of the box (quantile=True: the minimum and the maximum)."""',
        '    v = np.asarray(v, dtype=float)',
        '    q1, med, q3 = DescrStatsW(v, weights=np.asarray(f, dtype=float)).quantile([0.25, 0.5, 0.75], return_pandas=False)',
        '    if quantile:',
        '        return {"q1": q1, "med": med, "q3": q3, "whislo": v.min(), "whishi": v.max(), "fliers": []}',
        '    inside = v[(v >= q1 - 1.5 * (q3 - q1)) & (v <= q3 + 1.5 * (q3 - q1))]',
        '    lo, hi = inside.min(), inside.max()',
        '    return {"q1": q1, "med": med, "q3": q3, "whislo": lo, "whishi": hi, "fliers": v[(v < lo) | (v > hi)]}'],
    'mass': [
        'def shares(dens, at, w):',
        '    """For each density value, the share of the points (weights w) whose density is at least as high: the contour of this at p',
        '    holds a share p of the points. Below the lowest density at a point it goes on past 1, so that the 100% contour is drawn too."""',
        '    order = np.argsort(at)',
        '    s, ws = at[order], w[order]',
        '    tail = np.cumsum(ws[::-1])[::-1] / ws.sum()',
        '    lo = s[0] if s[0] > 0 else 1e-300',
        '    return np.where(dens < s[0], 1 + (s[0] - dens) / lo, np.interp(dens, s, tail))'],
    'binned': [
        'def binned_kde(xv, yv, w, cov, gx, gy, refine=4):',
        '    """The kernel density on the grid by linear binning and an FFT convolution (as KernSmooth does), on a grid four times finer',
        '    than the one returned: close to exact, and fast for many points."""',
        '    fx, fy = np.linspace(gx[0], gx[-1], refine * (len(gx) - 1) + 1), np.linspace(gy[0], gy[-1], refine * (len(gy) - 1) + 1)',
        '    n, dx, dy = len(fx), fx[1] - fx[0], fy[1] - fy[0]',
        '    ux, uy = (xv - fx[0]) / dx, (yv - fy[0]) / dy',
        '    ix, iy = np.clip(np.floor(ux).astype(int), 0, n - 2), np.clip(np.floor(uy).astype(int), 0, n - 2)',
        '    tx, ty = np.clip(ux - ix, 0, 1), np.clip(uy - iy, 0, 1)',
        '    counts = np.zeros((n, n))',
        '    for a, b, share in ((0, 0, (1 - tx) * (1 - ty)), (0, 1, tx * (1 - ty)), (1, 0, (1 - tx) * ty), (1, 1, tx * ty)):',
        '        np.add.at(counts, (iy + a, ix + b), w * share)',
        '    lx, ly = int(min(n, np.ceil(4 * np.sqrt(cov[0, 0]) / dx))), int(min(n, np.ceil(4 * np.sqrt(cov[1, 1]) / dy)))',
        '    ox, oy = np.meshgrid(np.arange(-lx, lx + 1) * dx, np.arange(-ly, ly + 1) * dy)',
        '    P = np.linalg.inv(cov)',
        '    kernel = np.exp(-0.5 * (P[0, 0] * ox * ox + 2 * P[0, 1] * ox * oy + P[1, 1] * oy * oy)) / (2 * np.pi * np.sqrt(np.linalg.det(cov)))',
        '    return np.maximum(fftconvolve(counts, kernel, mode="same") / w.sum(), 0)[::refine, ::refine]'],
}
_HELPERS['ticks'] = [
    'def ticks_every(lo, hi, step, start=0.0, log=False):',
    '    """The ticks from lo to hi as the graph above has them (Axis Settings\' Increment): at start + k·step, or on a log scale at start·step^k."""',
    '    if log:',
    '        k = np.arange(np.ceil(np.log(lo / start) / np.log(step) - 1e-9), np.floor(np.log(hi / start) / np.log(step) + 1e-9) + 1)',
    '        return start * step ** k',
    '    k = np.arange(np.ceil((lo - start) / step - 1e-9), np.floor((hi - start) / step + 1e-9) + 1)',
    '    return start + step * k']

_HELPERS['boundaries'] = [
    'def boundaries(name, layer):',
    '    """The map\'s boundaries, the file the page\'s map fetched from Plotly\'s site (cdn.plot.ly/<name>.json: Natural Earth\'s',
    '    1:110 million shapes as TopoJSON), read here too (a copy of it beside the table\'s CSV first, if there is one) and one of its',
    '    layers decoded with numpy: {region id: [rings of (longitude, latitude)]}, the countries by ISO 3166 code, the US states',
    '    ("subunits") by postal code. None when it cannot be read (offline): the map is then drawn without it."""',
    '    try:',
    '        if os.path.exists(f"{name}.json"):',
    '            with open(f"{name}.json") as f:',
    '                topo = json.load(f)',
    '        else:',
    '            try:',
    '                from pyodide.http import open_url   # in the page\'s Python (Pyodide, in the browser)',
    '                topo = json.loads(open_url(f"https://cdn.plot.ly/{name}.json").read())',
    '            except ImportError:   # elsewhere: over https, with certifi\'s certificates when it is there',
    '                import ssl',
    '                import urllib.request',
    '                try:',
    '                    import certifi',
    '                    ctx = ssl.create_default_context(cafile=certifi.where())',
    '                except ImportError:',
    '                    ctx = ssl.create_default_context()',
    '                with urllib.request.urlopen(f"https://cdn.plot.ly/{name}.json", timeout=60, context=ctx) as f:',
    '                    topo = json.load(f)',
    '    except Exception as e:',
    '        warnings.warn(f"the map\'s boundaries ({name}.json) could not be read: {e}")',
    '        return None',
    '    (sx, sy), (tx, ty) = topo["transform"]["scale"], topo["transform"]["translate"]',
    '    arcs = [np.cumsum(np.asarray(a, dtype=float), axis=0) * (sx, sy) + (tx, ty) for a in topo["arcs"]]   # quantized, delta-encoded',
    '',
    '    def ring(ix):   # a ring of arcs, the ones with a negative index reversed (~i)',
    '        parts = [arcs[i] if i >= 0 else arcs[~i][::-1] for i in ix]',
    '        return np.concatenate([parts[0]] + [q[1:] for q in parts[1:]])',
    '    out = {}',
    '    for k, geom in enumerate(topo["objects"][layer]["geometries"]):',
    '        polys = [geom["arcs"]] if geom["type"] == "Polygon" else geom["arcs"] if geom["type"] == "MultiPolygon" else []',
    '        out[geom.get("id", k)] = [ring(r) for poly in polys for r in poly]',
    '    return out']

# the map's colours in the light theme, as the page's (smui-p-graph.js geoLayout): the land, the borders
MAP_LAND, MAP_BORDER = '#e0d7ce8c', '#786b5d80'

# Axis Settings' reference lines (smui-axis.js): their colours in the light theme, and matplotlib's line styles.
_REF_COLORS = {'gray': '#786b5d', 'red': '#b0413e', 'blue': '#1f4e79', 'green': '#3a7d44', 'orange': '#b8651b'}
_REF_DASHES = {'solid': '-', 'dash': '--', 'dot': ':'}
DAY_MS = 86400000


def _bins_line(spec, label):
    """The Python that cuts a grouping column into the page's bins, as Make
    Binning Column cuts them (a bin holds its lower cut, the last one its
    maximum): each row's bin number, in the column's name and (bins)."""
    b = spec['bins']
    cuts = [float(c) for c in (b.get('cuts') or [])]
    k = len(cuts) + 1
    how = f'{k} bins of an equal width' if b.get('method') == 'width' else f'{k} bins of about equal counts, cut at its quantiles'
    return (f'df[{_j(spec["col"] + " (bins)")}] = pd.cut(df[{_j(spec["col"])}], {_py([float("-inf")] + cuts + [float("inf")])}, right=False, labels=False)'
            f'   # {label}: {spec["col"]} in {how} (a bin holds its lower cut), as Make Binning Column cuts it')


def axis_settings_lines(s, a, ax='ax', log=False, date=False):
    """The Python that gives the matplotlib axes ax (the Python of it) the
    Axis Settings s of its a axis ('x' or 'y'), as the page draws them
    (smui-axis.js): the scale, the order, the ends (an end not given stays
    as drawn), the ticks every increment from the minimum (or 0; on a log
    scale the increment is the ratio between ticks, from the minimum or 1;
    on a date axis days), and the reference lines and ranges with their
    labels. log: the axis's scale with the settings; date: the axis shows
    dates (matplotlib counts days since 1970, the page milliseconds).
    Returns (lines, whether they use ticks_every)."""
    L = []
    if not s:
        return L, False
    val = (lambda v: _py(v / DAY_MS)) if date else _py   # a date: days since 1970, matplotlib's unit on a date axis
    if s.get('log') is not None:
        L.append(f'{ax}.set_{a}scale({json.dumps("log" if s["log"] else "linear")})   # Scale: {"Log" if s["log"] else "Linear"}')
    rev = False
    if s.get('reverse') is not None:
        rev = bool(s['reverse'])
        L += [f'if {"not " if rev else ""}{ax}.{a}axis_inverted():', f'    {ax}.invert_{a}axis()   # Reverse Order: {"on" if rev else "off"}']
    lo, hi = s.get('min'), s.get('max')
    ends = ('left', 'right') if a == 'x' else ('bottom', 'top')
    if lo is not None and hi is not None:
        L.append(f'{ax}.set_{a}lim({val(hi)}, {val(lo)})   # Minimum and Maximum (reversed)' if rev else f'{ax}.set_{a}lim({val(lo)}, {val(hi)})   # Minimum and Maximum')
    elif lo is not None:
        L.append(f'{ax}.set_{a}lim({ends[1 if rev else 0]}={val(lo)})   # Minimum')
    elif hi is not None:
        L.append(f'{ax}.set_{a}lim({ends[0 if rev else 1]}={val(hi)})   # Maximum')
    ticks = False
    inc = s.get('inc')
    if inc:
        ticks = True
        if log:
            L.append(f'{ax}.set_{a}ticks(ticks_every(*sorted({ax}.get_{a}lim()), {_py(inc)}, start={_py(lo if lo is not None else 1)}, log=True))   # Increment: a tick every × {_py(inc)}')
        elif date:
            L.append(f'{ax}.set_{a}ticks(ticks_every(*sorted({ax}.get_{a}lim()), {_py(inc)}, start={_py((lo or 0) / DAY_MS)}))   # Increment: a tick every {_py(inc)} day{"" if inc == 1 else "s"}')
        else:
            L.append(f'{ax}.set_{a}ticks(ticks_every(*sorted({ax}.get_{a}lim()), {_py(inc)}, start={_py(lo if lo is not None else 0)}))   # Increment: a tick every {_py(inc)}')
    for r in s.get('refs') or []:
        col = json.dumps(_REF_COLORS.get(r.get('color'), _REF_COLORS['gray']))
        v, to = r['value'], r.get('to')
        a0, b0 = (min(v, to), max(v, to)) if to is not None else (v, v)
        span = 'axvspan' if a == 'x' else 'axhspan'
        line = 'axvline' if a == 'x' else 'axhline'
        if to is not None:
            L.append(f'{ax}.{span}({val(a0)}, {val(b0)}, color={col}, alpha=0.16, linewidth=0, zorder=0)   # a reference range')
        else:
            L.append(f'{ax}.{line}({val(a0)}, color={col}, linewidth={_lw(1.5)}, linestyle={json.dumps(_REF_DASHES.get(r.get("dash"), "-"))})   # a reference line')
        if r.get('label'):
            mid = a0 if to is None else (math.sqrt(a0 * b0) if log else (a0 + b0) / 2)
            if a == 'x':
                L.append(f'{ax}.annotate({json.dumps(r["label"])}, ({val(mid)}, 1), xycoords=("data", "axes fraction"), xytext=(3, -2), textcoords="offset points", ha="left", va="top", fontsize=8, color={col})')
            else:
                L.append(f'{ax}.annotate({json.dumps(r["label"])}, (1, {val(mid)}), xycoords=("axes fraction", "data"), xytext=(-2, 2), textcoords="offset points", ha="right", va="bottom", fontsize=8, color={col})')
    return L, ticks


# The imports each helper needs.
_HELPER_IMPORTS = {'boundaries': ['import json', 'import os', 'import warnings', 'from matplotlib.collections import LineCollection, PolyCollection'],
                   'weighted': ['from scipy import stats', 'from statsmodels.stats.weightstats import DescrStatsW'],
                   'wbox': ['from statsmodels.stats.weightstats import DescrStatsW'],
                   'binned': ['from scipy.signal import fftconvolve']}


def _roles(xk, yk):
    """What the X and Y columns make of the axes, as the page's axesRoles: the
    response is the continuous one (Y when both are), the factor the other."""
    if yk == 'cont':
        return {'resp': 'y', 'fac': 'x' if xk else None, 'horiz': False, 'fac_cat': xk == 'cat'}
    if xk == 'cont':
        return {'resp': 'x', 'fac': 'y' if yk else None, 'horiz': True, 'fac_cat': yk == 'cat'}
    if xk == 'cat' and not yk:
        return {'resp': None, 'fac': 'x', 'horiz': False, 'fac_cat': True}
    if yk == 'cat' and not xk:
        return {'resp': None, 'fac': 'y', 'horiz': True, 'fac_cat': True}
    return {'resp': None, 'fac': None, 'horiz': False, 'fac_cat': False}


def _lw(px):
    """A line width in points from the page's pixels."""
    return f'{px * PX:.3g}'


def _area(px):
    """A marker's area in points² (matplotlib's s) from the page's diameter in pixels."""
    return f'{(px * PX) ** 2:.3g}'


class _Cell:
    """One cell of an element's loops: its rows are g; x and y the Python of its
    columns' names, color the Python of its colour, si and gi the Python of
    its series' and group's numbers (0 when there is one)."""

    def __init__(self, x, y, color, si, gi):
        self.x, self.y, self.color, self.si, self.gi = x, y, color, si, gi


class _GB:
    """Graph Builder's graph (and the legacy Chart's, which Graph Builder's
    elements draw) as matplotlib code, from the page's plan of it."""

    ELEMENTS = ('map', 'points', 'smoother', 'fit', 'ellipse', 'contour', 'line', 'bar', 'area', 'box', 'bean', 'histogram', 'heatmap', 'mosaic', 'caption', 'pie')
    # the legend's sample for each element: a marker, a line or a patch
    SAMPLE = {'map': 'patch', 'points': 'marker', 'smoother': 'line', 'fit': 'line', 'ellipse': 'line', 'contour': 'line', 'line': 'line', 'bar': 'patch', 'area': 'patch',
              'box': 'patch', 'bean': 'patch', 'histogram': 'patch'}

    def __init__(self, table, plan, rows, table_name):
        P = plan
        self.table, self.P, self.rows, self.table_name = table, P, rows, table_name
        self.imports = ['import matplotlib.pyplot as plt']
        self.helpers = []
        self.pre = _Py()           # constants, after the helpers
        self.w = _Py()             # the figure
        self.freq = P.get('freq') or None
        self.whole = bool(self.freq) and _whole(table, self.freq, rows)
        kinds = P.get('kinds') or {}
        self.kind = {'x': kinds.get('x', 'none'), 'y': kinds.get('y', 'none')}
        self.xk = self.kind['x'] if self.kind['x'] in ('cat', 'cont') else None
        self.yk = self.kind['y'] if self.kind['y'] in ('cat', 'cont') else None
        self.R = _roles(self.xk, self.yk)
        self.levels = P.get('levels') or {}
        self.group = P.get('group') or None
        self.els = [e for e in (P.get('elements') or []) if e.get('type') in self.ELEMENTS]
        self.series = P.get('series') or [[[[None, None]]]]
        self.nS = max([len(s) for row in self.series for s in row] + [1])
        self.nG = len(self.group['values']) if self.group else 0
        self.slots = max(1, self.nG) * (self.nS if self.nS > 1 else 1)
        self.alpha = float(P.get('alpha') or 0.05)
        xs0, ys0 = ((P.get('xsets') or [[]])[0] or [None])[0], ((P.get('ysets') or [[]])[0] or [None])[0]
        self.date = {'x': bool(xs0) and self.kind['x'] == 'cont' and _is_date(table, xs0),
                     'y': bool(ys0) and self.kind['y'] == 'cont' and _is_date(table, ys0)}
        self.log = {k: bool((P.get('log') or {}).get(k)) and not self.date[k] and self.kind[k] == 'cont' for k in ('x', 'y')}
        self.many = bool(P.get('many'))
        self.geo = P.get('map') or None      # a map: Map Shapes, or points on a Background Map
        M = P.get('marker') or {}
        # Marker Size (a diameter in pixels) and Transparency (an opacity) as set on the graph, or None: the graph's own
        self.msize = float(M['size']) if isinstance(M.get('size'), (int, float)) and M['size'] > 0 else None
        self.malpha = float(M['alpha']) if isinstance(M.get('alpha'), (int, float)) and 0 <= M['alpha'] <= 1 else None
        self.pf = 'df'             # the rows of the panel being written
        self.corner = set()        # the counts of lines of text in the panel's corners
        self.helpers_consts = set()

    # ---- small pieces ----------------------------------------------------------------
    def need(self, *names):
        for n in names:
            if n in _HELPERS and n not in self.helpers:
                for i in _HELPER_IMPORTS.get(n, []):
                    self.imp(i)
                self.helpers.append(n)
            elif n not in _HELPERS:
                self.imp(n)

    def imp(self, line):
        if line not in self.imports:
            self.imports.append(line)

    def drawn(self, axis, expr):
        """The Python of coordinates as matplotlib draws them: a date axis as dates."""
        return f'pd.to_datetime({expr}, unit="ms")' if self.date[axis] else expr

    def place(self, axis, col, frame='g'):
        """The Python of the rows' places on an axis: a level's number, a value, or 0."""
        k = self.kind[axis]
        if col is None or k in ('none', 'count'):
            return f'np.zeros(len({frame}))'
        if k == 'cat':
            return f'{frame}[{col}].map(place[{col}])'
        return f'{frame}[{col}]'

    def key(self, fac, frame='g'):
        """The Python that groups the rows by the factor's places (a level's number, a value), or by one place without a factor."""
        if fac is None:
            return f'np.zeros(len({frame}), dtype=int)'
        return f'{frame}[{fac}].map(place[{fac}])' if self.R['fac_cat'] else f'{frame}[{fac}]'

    def colcode(self, v):
        return _j(v) if isinstance(v, str) else _py(v)

    # ---- the whole ---------------------------------------------------------------------
    def code(self):
        P = self.P
        self.consts()
        self.figure()
        self.finish()
        head = code_head(self.table_name, self.imports[:1] + sorted(self.imports[1:], key=lambda s: (not s.startswith('import'), s)))
        lines = [head] + _keep_lines(self.table, self.rows, P.get('where'))
        if self.freq:
            lines.append(f'df = df[df[{_j(self.freq)}] > 0]   # Freq: a row counts {self.freq} times; rows without a positive count are left out')
        for n in self.helpers:
            lines += [''] + _HELPERS[n]
        if self.helpers:
            lines.append('')
        lines += self.pre.lines + self.w.lines + ['plt.show()']
        return '\n'.join(lines)

    def consts(self):
        """The levels and bins the page found, as the code's constants."""
        pre, P = self.pre, self.P
        if self.geo:
            self.geo_consts()
        for zone, label in (('wrap', 'Wrap'), ('gx', 'Group X'), ('gy', 'Group Y')):
            spec = P.get(zone)
            if spec and spec.get('bins'):
                pre(_bins_line(spec, label))
        G = self.group
        if G:
            if G.get('bins'):
                pre(_bins_line(G, G['zone']))
            pre(f'groups = {_py(G["values"])}   # {G["zone"]}: {"the bins" if G.get("bins") else "the levels"} of {G["col"]}, in the table\'s order',
                f'colors = {_py([PALETTE[i % len(PALETTE)] for i in range(len(G["values"]))])}   # a colour for each: the page\'s palette')
        C = P.get('color')
        if C and C.get('cat') and not (G and G['col'] == C['col']):
            pre(f'color_of = {{{", ".join(f"{self.colcode(v)}: {_j(PALETTE[i % len(PALETTE)])}" for i, v in enumerate(C["values"]))}}}   # Color: a colour for each level of {C["col"]}')
        if C and not C.get('cat') and C.get('range'):
            self.imp('from matplotlib.colors import LinearSegmentedColormap')
            pre(f'ramp = LinearSegmentedColormap.from_list("ramp", {_py(RAMP)}).with_extremes(bad="{MISSING}")   # the page\'s blue-grey-red, grey for a missing value')
        cat = {c: v for c, v in self.levels.items()}
        if cat:
            order = {c: o for c, o in (P.get('order') or {}).items() if c in cat and o}
            pre(f'levels = {{{", ".join(f"{_j(c)}: {_py(v["values"])}" for c, v in cat.items())}}}   # the levels of each categorical axis column, in the {"order the graph shows them" if order else "table\'s order"}')
            for c, o in order.items():
                self.order_lines(c, o)
            pre('place = {c: {v: k for k, v in enumerate(lv)} for c, lv in levels.items()}   # a level\'s place on its axis: 0, 1, 2, ...')

    def order_lines(self, c, o):
        """Order By of a categorical axis column: its levels sorted by a
        statistic of another column (or by their count of rows) over the
        graph's rows, as the page sorts them: a row counts Freq times; ties,
        and a level without a value, keep their order, the latter last."""
        pre, f = self.pre, self.freq
        by = o.get('by')
        stat = o.get('stat') if o.get('stat') in ('median', 'sum') else 'mean'
        desc = bool(o.get('desc'))
        C = _j(c)
        if not by:
            what = 'their count of rows' + (' (Freq counted)' if f else '')
            pre(f'key = df.dropna(subset=[{C}]).groupby({C})[{_j(f)}].sum()' if f else f'key = df.dropna(subset=[{C}]).groupby({C}).size()')
        else:
            B = _j(by)
            what = f'the {stat} of {by}' + (' (Freq counted)' if f else '')
            pre(f'd = df.dropna(subset=[{C}, {B}])')
            if stat == 'median':
                pre(f'key = d.loc[d.index.repeat(d[{_j(f)}].round().astype(int))].groupby({C})[{B}].median()' if f else f'key = d.groupby({C})[{B}].median()')
            elif stat == 'sum':
                pre(f'key = (d[{B}] * d[{_j(f)}]).groupby(d[{C}]).sum()' if f else f'key = d.groupby({C})[{B}].sum()')
            else:
                pre(f'key = (d[{B}] * d[{_j(f)}]).groupby(d[{C}]).sum() / d[{_j(f)}].groupby(d[{C}]).sum()' if f else f'key = d.groupby({C})[{B}].mean()')
        pre(f'levels[{C}] = sorted(levels[{C}], key=lambda v: (pd.isna(key.get(v)), {"-" if desc else ""}key.get(v, 0)))   # Order By: the levels of {c} by {what}, {"descending" if desc else "ascending"}')

    # ---- the figure and its panels -------------------------------------------------------
    def grid(self):
        P = self.P
        wrap, gx, gy = P.get('wrap'), P.get('gx'), P.get('gy')
        xsets, ysets = P.get('xsets') or [[]], P.get('ysets') or [[]]
        if wrap:
            k = max(1, len(wrap['values']))
            nC = math.ceil(math.sqrt(k))
            return math.ceil(k / nC), nC
        return (len(gy['values']) if gy else 1) * len(ysets), (len(gx['values']) if gx else 1) * len(xsets)

    def panel_values(self, spec):
        """The Python of a panel column's levels (or bins), their labels, and of its column in the rows."""
        col = spec['col'] + ' (bins)' if spec.get('bins') else spec['col']
        vals = list(range(len(spec['labels']))) if spec.get('bins') else spec['values']
        return _py(vals), _py(spec['labels']), _j(col)

    def figure(self):
        P, w = self.P, self.w
        wrap, gx, gy = P.get('wrap'), P.get('gx'), P.get('gy')
        xsets, ysets = P.get('xsets') or [[]], P.get('ysets') or [[]]
        NX, NY = len(xsets), len(ysets)
        nR, nC = self.grid()
        self.nR, self.nC = nR, nC
        W, H = P.get('size') or [640, 420]
        size = f'figsize=({_inch(W)}, {_inch(H)})'
        self.single = not (wrap or gx or gy) and nR == 1 and nC == 1
        title = P.get('title')
        excl = P.get('exclusive')
        w('')
        if self.single:
            w(f'fig, ax = plt.subplots({size}, layout="constrained")')
        else:
            sx = 'True' if wrap else ('False' if excl == 'mosaic' else '"col"')
            sy = 'True' if wrap else '"row"'
            head = wrap or gx
            if head or gy:
                w(f'fig = plt.figure({size}, layout="constrained")')
                if title:
                    w(f'fig.suptitle({_j(title)})')
                if gy:
                    w('sub, side = fig.subfigures(1, 2, width_ratios=[24, 1])   # the panels, and on their right the name of the column of Group Y',
                      f'side.text(0.5, 0.5, {_j(gy["col"])}, rotation=-90, ha="center", va="center", fontsize=9, fontweight="bold")')
                else:
                    w('sub = fig.subfigures()   # the panels, under the name of the column that makes them')
                if head:
                    w(f'sub.suptitle({_j(head["col"])}, fontsize=9, fontweight="bold")')
                w(f'axes = sub.subplots({nR}, {nC}, sharex={sx}, sharey={sy}, squeeze=False)')
            else:
                w(f'fig, axes = plt.subplots({nR}, {nC}, {size}, sharex={sx}, sharey={sy}, squeeze=False, layout="constrained")')
                if title:
                    w(f'fig.suptitle({_j(title)})')
        self.pre_panels()
        pairs0 = self.series[0][0]
        if self.single:
            self.pf = 'df'
            self.set_pairs(pairs0, None, None)
            self.panel()
            return
        if wrap:
            k = len(wrap['values'])
            vals, labs, col = self.panel_values(wrap)
            with w.block(f'for ax, level, label in zip(axes.flat, {vals}, {labs}):   # Wrap: a panel for each level of {wrap["col"]}'):
                w(f'p = df[df[{col}] == level]', 'ax.set_title(label, fontsize=9)')
                self.pf = 'p'
                self.set_pairs(pairs0, None, None)
                self.panel()
            if nR * nC > k:
                with w.block(f'for ax in axes.flat[{k}:]:'):
                    w('ax.set_visible(False)   # the places of the grid without a panel')
                below = [i for i in range(k) if i + nC >= k and i + nC < nR * nC]
                if below:
                    with w.block(f'for ax in axes.flat[{below[0]}:{below[-1] + 1}]:'):
                        w('ax.xaxis.set_tick_params(labelbottom=True)   # a panel with none below it shows its X values')
            return
        # Group Y by Group X, and the X and Y columns side by side
        xs_side, ys_side = NX > 1, NY > 1
        opened = []
        conds = []
        if gy:
            vals, labs, col = self.panel_values(gy)
            if not gx and not xs_side and not ys_side:
                opened.append(w.block(f'for ax, b, blabel in zip(axes[:, 0], {vals}, {labs}):   # Group Y: a row of panels for each level of {gy["col"]}'))
            else:
                opened.append(w.block(f'for r, (b, blabel) in enumerate(zip({vals}, {labs})):   # Group Y: a row of panels for each level of {gy["col"]}'))
            opened[-1].__enter__()
            conds.append(f'(df[{col}] == b)')
        if gx:
            vals, labs, col = self.panel_values(gx)
            if not gy and not xs_side and not ys_side:
                opened.append(w.block(f'for ax, a, alabel in zip(axes[0], {vals}, {labs}):   # Group X: a column of panels for each level of {gx["col"]}'))
            else:
                opened.append(w.block(f'for c, (a, alabel) in enumerate(zip({vals}, {labs})):   # Group X: a column of panels for each level of {gx["col"]}'))
            opened[-1].__enter__()
            conds.append(f'(df[{col}] == a)')
        if conds:
            w(f'p = df[{" & ".join(conds)}]' if len(conds) > 1 else f'p = df[{conds[0][1:-1]}]')
            self.pf = 'p'
        else:
            self.pf = 'df'
        xv = yv = None
        if ys_side:
            opened.append(w.block(f'for i, y in enumerate({_py([s[0] if s else None for s in ysets])}):   # Y: the columns side by side, a row of panels each'))
            opened[-1].__enter__()
            yv = 'y'
        if xs_side:
            opened.append(w.block(f'for j, x in enumerate({_py([s[0] if s else None for s in xsets])}):   # X: the columns side by side, a column of panels each'))
            opened[-1].__enter__()
            xv = 'x'
        simple = (gx or gy) and not xs_side and not ys_side and not (gx and gy)
        if not simple:
            r = ' + '.join([t for t in ((f'r * {NY}' if NY > 1 else 'r') if gy else None, 'i' if ys_side else None) if t]) or '0'
            c = ' + '.join([t for t in ((f'c * {NX}' if NX > 1 else 'c') if gx else None, 'j' if xs_side else None) if t]) or '0'
            w(f'ax = axes[{r}, {c}]')
        if gx:
            first = [t for t in ('r == 0' if gy else None, 'j == 0' if xs_side else None, 'i == 0' if ys_side else None) if t]
            if first:
                with w.block(f'if {" and ".join(first)}:'):
                    w('ax.set_title(alabel, fontsize=9)')
            else:
                w('ax.set_title(alabel, fontsize=9)')
        if gy:
            last = [t for t in (f'c == {len(gx["values"]) - 1}' if gx else None, f'j == {NX - 1}' if xs_side else None, 'i == 0' if ys_side else None) if t]
            note = 'ax.annotate(blabel, (1, 0.5), xycoords="axes fraction", xytext=(4, 0), textcoords="offset points", rotation=-90, ha="left", va="center", fontsize=9)'
            if last:
                with w.block(f'if {" and ".join(last)}:'):
                    w(note)
            else:
                w(note)
        self.set_pairs(pairs0, xv, yv)
        self.panel()
        for b in reversed(opened):
            b.__exit__(None, None, None)

    def set_pairs(self, pairs, xv, yv):
        """The series of the panel being written: the Python of their X and Y columns' names."""
        out = []
        for x, y in pairs:
            out.append((xv if xv else (_j(x) if x else None), yv if yv else (_j(y) if y else None)))
        self.pairs = out

    def pre_panels(self):
        """What some elements find over every panel before any is drawn (the longest bar of the histograms, the widest violin)."""
        for e in self.els:
            fn = getattr(self, f'pre_{e["type"]}', None)
            if fn:
                fn(e)

    def panel(self):
        """One panel: its elements in the page's drawing order, then its axes."""
        self.corner = set()
        if self.geo:
            self.geo_background()
        for e in self.els:
            getattr(self, f'el_{e["type"]}')(e)
        self.axes_of_panel()

    # ---- a map ---------------------------------------------------------------------------------
    def geo_consts(self):
        """A map's boundaries (Plotly's own file, as the page's map has them), once."""
        G, pre = self.geo, self.pre
        self.need('boundaries')
        f, usa = G.get('file') or 'world_110m', G.get('scope') == 'usa'
        sh = G.get('shape') or None
        pre('', '# The map: matplotlib alone has no map projections and no boundaries (cartopy and geopandas, which have them, are not',
            '# in Pyodide). The boundaries here are the page\'s own, from the same file, drawn in longitude and latitude (an',
            f'# equirectangular map, scaled at its middle latitude), where the page draws Plotly\'s {"Albers USA (Alaska and Hawaii moved in)" if usa else "natural earth"} projection.',
            f'land, borders = boundaries({_j(f)}, "land"), boundaries({_j(f)}, {_j("subunits" if usa else "countries")})')
        if sh:
            layer = 'subunits' if sh.get('mode') == 'usa' else 'countries'
            how = {'usa': 'a US state (its postal code)', 'iso3': 'a country (its ISO 3166 code)', 'names': 'a country (its ISO 3166 code, as the page\'s map matched the name)'}.get(sh.get('mode'), 'a region')
            pre(f'regions = {"borders" if layer == ("subunits" if usa else "countries") else f"boundaries({_j(f)}, {_j(layer)})"}   # the regions of Map Shapes',
                f'ids = {json.dumps(sh.get("ids") or {}, ensure_ascii=False)}   # {sh["col"]}: each value\'s region, {how}')

    def geo_background(self):
        w, usa = self.w, (self.geo or {}).get('scope') == 'usa'
        w('drawn = []   # what the map shows, which its view fits (the page\'s map fits its points and regions)')
        with w.block('if land:'):
            w(f'ax.add_collection(PolyCollection([r for rs in land.values() for r in rs], facecolors="{MAP_LAND}", edgecolors="none", zorder=0), autolim=False)')
        with w.block('if borders:'):
            w(f'ax.add_collection(LineCollection([r for rs in borders.values() for r in rs], colors="{MAP_BORDER}", linewidths={_lw(0.5)}, zorder=0.5), autolim=False)')

    def el_map(self, e):
        """Map Shapes: each region filled by a statistic of the Color column over its
        rows (a categorical one's most common level), or by its count of rows."""
        w, P = self.w, self.P
        sh = (self.geo or {}).get('shape') or {}
        if not sh:
            return
        stat = e.get('stat') or 'n'
        C = P.get('color')
        cont = bool(C and not C.get('cat'))
        col = _j(sh['col'])
        lab = dict(_STAT_LABEL).get(stat, stat)
        what = 'its count of rows' if stat == 'n' and not cont else (f'the most common level of {C["col"]}' if stat == 'level' else f'the {lab} of {C["col"]} over its rows')
        w(f'# Map Shapes: each region of {sh["col"]} filled by {what}{" (Freq counted)" if self.freq else ""}')
        w(f'g = {self.pf}.assign(region={self.pf}[{col}].map(ids)).dropna(subset=["region"])')
        if stat == 'level':
            cc = _j(C['col'])
            f = self.freq
            w((f'n = g.groupby(["region", {cc}])[{_j(f)}].sum()' if f else f'n = g.groupby(["region", {cc}]).size()') + '.rename("n").reset_index()',
              f'n["k"] = n[{cc}].map({{v: k for k, v in enumerate({_py(C["values"])})}})   # each level\'s place (its colour)',
              'n = n.dropna(subset=["k"]).sort_values(["region", "n", "k"], ascending=[True, False, True]).drop_duplicates("region")   # a region\'s most common level (a tie: the first)',
              'value = dict(zip(n["region"], n["k"].astype(int)))')
        else:
            resp = _j(C['col']) if cont else None
            if resp:
                w(f'g = g.dropna(subset=[{resp}])')
            self.stat_lines('"region"', resp if stat != 'n' else None, self.stat_needs(stat, None, resp) if stat != 'n' else [])
            w(f'value = {self.stat_value(stat, resp)}.dropna().to_dict()')
        w('polys, vals = [], []')
        with w.block('for rid, v in value.items():'):
            with w.block('for ring in (regions or {}).get(rid, []):'):
                w('polys.append(ring)', 'vals.append(v)')
        if stat == 'level':
            w(f'pc = PolyCollection(polys, facecolors=[{_py(PALETTE)}[int(k) % 12] for k in vals], edgecolors="{SURFACE}", linewidths={_lw(0.6)}, zorder=1)')
        else:
            lo, hi = e.get('range') or [0, 1]
            if not cont:
                if 'counts_map' not in self.helpers_consts:
                    self.imp('from matplotlib.colors import LinearSegmentedColormap')
                    self.pre(f'counts_map = LinearSegmentedColormap.from_list("counts", {_py(HEAT)})   # the page\'s scale of counts')
                    self.helpers_consts.add('counts_map')
            w(f'pc = PolyCollection(polys, array=np.asarray(vals, dtype=float), cmap={"ramp" if cont else "counts_map"}, norm=plt.Normalize({_nm(lo, 12)}, {_nm(hi, 12)}), edgecolors="{SURFACE}", linewidths={_lw(0.6)}, zorder=1)')
        w('ax.add_collection(pc)', 'drawn += polys')

    def geo_axes(self):
        """A map's view: what is drawn on it (the whole lower 48 at least, for US States), longitude and latitude in proportion."""
        w, usa = self.w, (self.geo or {}).get('scope') == 'usa'
        w('parts = drawn + [np.ma.filled(c.get_offsets().astype(float), np.nan) for c in ax.collections if not isinstance(c, (PolyCollection, LineCollection)) and len(c.get_offsets())]   # the regions and the points',
          'pts = np.concatenate(parts) if parts else np.empty((0, 2))')
        if usa:
            w('pts = np.concatenate([pts, [[-125, 24], [-66.5, 49.5]]])   # the lower 48 states at least, as the page\'s US map shows them')
        with w.block('if len(pts):'):
            w('(x0, y0), (x1, y1) = np.nanmin(pts, axis=0), np.nanmax(pts, axis=0)',
              'dx, dy = max(x1 - x0, 1) * 0.05, max(y1 - y0, 1) * 0.05',
              'ax.set_xlim(max(-180, x0 - dx), min(180, x1 + dx))',
              'ax.set_ylim(max(-90, y0 - dy), min(90, y1 + dy))')
        w('ax.set_aspect(1 / np.cos(np.radians(np.clip(np.mean(ax.get_ylim()), -80, 80))))   # a degree of longitude as long as it is there')

    # ---- the loops of an element over a panel's series and groups ---------------------------
    def cells(self, need, dflt, before=None, groups=True, si=False, gi=None):
        """Opens the loops of one element over the panel's series and groups
        and writes g, the cell's rows (those with every column in need(x, y)).
        Returns (the cell, the blocks to close). before(x, y) writes what the
        element finds over the series' groups first."""
        w = self.w
        blocks = []
        pairs = self.pairs
        color = _j(dflt) if dflt else None
        si_expr = '0'
        if len(pairs) > 1:
            xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
            colors = [_j(PALETTE[i % len(PALETTE)]) for i in range(len(pairs))]
            with_color = not self.group
            if len(set(xs)) == 1:
                X, Y = xs[0], 'y'
                items = ys
                var = 'y'
            elif len(set(ys)) == 1:
                X, Y = 'x', ys[0]
                items = xs
                var = 'x'
            else:
                X, Y = 'x', 'y'
                items = [f'({a}, {b})' for a, b in pairs]
                var = '(x, y)'
            if with_color:
                head = f'for si, ({var}, color) in enumerate(zip([{", ".join(items)}], [{", ".join(colors)}])):' if si else f'for {var}, color in zip([{", ".join(items)}], [{", ".join(colors)}]):'
                color = 'color'
            else:
                head = f'for si, {var} in enumerate([{", ".join(items)}]):' if si else f'for {var} in [{", ".join(items)}]:'
            b = w.block(head + '   # the columns merged on an axis')
            b.__enter__()
            blocks.append(b)
            si_expr = 'si'
        else:
            X, Y = pairs[0]
        if before:
            before(X, Y)
        frame = self.pf
        if gi is None:
            gi = si
        if groups and self.group:
            head = 'for gi, (group, color) in enumerate(zip(groups, colors)):' if gi else 'for group, color in zip(groups, colors):'
            b = w.block(head)
            b.__enter__()
            blocks.append(b)
            gcol = _j(self.group['col'] + ' (bins)' if self.group.get('bins') else self.group['col'])
            frame = f'{frame}[{frame}[{gcol}] == group]'
            color = 'color'
        gi_expr = 'gi' if (groups and self.group and gi) else '0'
        cols = [c for c in need(X, Y) if c]
        cols = list(dict.fromkeys(cols))
        w(f'g = {frame}.dropna(subset=[{", ".join(cols)}])' if cols else f'g = {frame}')
        return _Cell(X, Y, color, si_expr, gi_expr), blocks

    def close(self, blocks):
        for b in reversed(blocks):
            b.__exit__(None, None, None)

    def resp_fac(self, c):
        """The Python of a cell's response and factor columns."""
        pick = {'x': c.x, 'y': c.y}
        return (pick[self.R['resp']] if self.R['resp'] else None), (pick[self.R['fac']] if self.R['fac'] else None)

    def in_groups(self, frame, cols=()):
        """The Python of a frame's rows that belong to a group (Overlay, Color) and have every column in cols."""
        cols = [c for c in cols if c]
        drop = f'.dropna(subset=[{", ".join(dict.fromkeys(cols))}])' if cols else ''
        if not self.group:
            return f'{frame}{drop}'
        gcol = _j(self.group['col'] + ' (bins)' if self.group.get('bins') else self.group['col'])
        return f'{frame}[{frame}[{gcol}].isin(groups)]{drop}'

    # ---- Points ---------------------------------------------------------------------------------
    def el_points(self, e):
        if (e.get('summary') or 'none') != 'none':
            return self.summary_marks(e, 'markers')
        w = self.w
        jit = e.get('jitter') or 'auto'
        lim = 0.8 * float(e['jitterLimit'] if e.get('jitterLimit') is not None else 1)
        jx = jit != 'none' and self.xk != 'cont' and self.kind['x'] != 'count'
        jy = jit != 'none' and self.yk != 'cont' and self.kind['y'] != 'count'
        special = jit in ('grid', 'packed') and jx != jy
        how = {'normal': 'Random Normal', 'grid': 'Centered Grid', 'packed': 'Packed', 'none': ''}.get(jit, 'Random Uniform') if (jx or jy) else ''
        w(f'# Points: a marker for each row{f", jittered across its level ({how}, limit {_nm(lim / 0.8)})" if how else ""}')
        pack = None
        if jit == 'packed' and special:
            pack = e.get('packed') or {}
            self.need('packed')

        def before(X, Y):
            if not pack:
                return
            at_axis, v_axis = ('x', 'y') if jx else ('y', 'x')
            cat = X if jx else Y
            val = Y if jx else X
            w(f'q = {self.pf}.dropna(subset=[{", ".join(c for c in (X, Y) if c)}])   # Packed: every point of the panel at once, whatever its group')
            with w.block('if len(q) <= 20000:   # (the page packs up to 20000 points in a panel)'):
                w(f'span = 1.1 * np.ptp(q[{val}]) or 1.0   # the value axis as the page sizes it (with 5% each side)',
                  f'off = pd.Series(packed(q.index, {self.place(at_axis, cat, "q")}, q[{val}], {_nm(pack.get("value_px", 300), 17)} / span, {_nm(pack.get("level_px", 100), 17)}, {_nm(pack.get("diam", 7), 17)}, {_nm(lim / 0.8)}), index=q.index)')
            with w.block('else:   # more: Random Uniform, as the page'):
                self.need('hash01')
                w(f'off = pd.Series((hash01(q.index, {1 if jx else 2}) - 0.5) * {_nm(lim)}, index=q.index)')

        c, blocks = self.cells(lambda X, Y: [X, Y], None, before=before)
        X, Y = c.x, c.y
        xs, ys = self.place('x', X), self.place('y', Y)
        if jit == 'grid' and special:
            self.need('grid')
            w(f'shift = centered_grid({xs if jx else ys}, {ys if jx else xs}, {_nm(lim / 0.8)})')
            if jx:
                xs = f'{xs} + shift'
            else:
                ys = f'{ys} + shift'
        elif pack:
            if jx:
                xs = f'{xs} + off[g.index]'
            else:
                ys = f'{ys} + off[g.index]'
        else:
            for axis, on, salt in (('x', jx, 1), ('y', jy, 2)):
                if not on:
                    continue
                self.need('hash01')
                if jit == 'normal':
                    self.need('normal')
                    add = f'normal_jitter(g.index, {salt}, {_nm(lim)})'
                else:
                    add = f'(hash01(g.index, {salt}) - 0.5) * {_nm(lim)}'
                if axis == 'x':
                    xs = f'{xs} + {add}'
                else:
                    ys = f'{ys} + {add}'
        args = [self.drawn('x', xs), self.drawn('y', ys)]
        S = self.P.get('sizecol')
        if S:
            lo, hi = S['range']
            u = f'np.sqrt((g[{_j(S["col"])}] - {_nm(lo, 12)}) / {_nm(hi - lo, 12)})' if hi > lo else 'np.sqrt(0.5)'
            f_ = self.msize / 6 if self.msize else 1   # Marker Size scales the Size zone's sizes too
            k_ = f' * {_nm(f_, 12)}' if f_ != 1 else ''
            args.append(f's=np.where(g[{_j(S["col"])}].notna(), ({PX} * (4 + 18 * {u}){k_}) ** 2, {_area(3 * f_)})')
        else:
            args.append(f's={_area(self.msize or (4 if self.many else 6))}')
        C = self.P.get('color')
        if C and not C.get('cat') and C.get('range'):
            lo, hi = C['range']
            if not hi > lo:
                lo, hi = lo - 1, hi + 1
            args.append(f'c=g[{_j(C["col"])}], cmap=ramp, vmin={_nm(lo, 12)}, vmax={_nm(hi, 12)}, plotnonfinite=True')
        elif C and C.get('cat') and not (self.group and self.group['col'] == C['col']):
            args.append(f'color=g[{_j(C["col"])}].map(color_of).fillna("{MISSING}")')
        else:
            args.append(f'color={c.color or _j(POINT)}')
        alpha = self.malpha if self.malpha is not None else (0.7 if S else 0.65 if self.many else 0.9)
        if S:
            args.append(f'alpha={_nm(alpha)}, edgecolors="{TEXT}66", linewidths={_lw(0.6)}')
        else:
            args.append(f'alpha={_nm(alpha)}, linewidths=0')
        said = [t for t, on in (('Marker Size', self.msize), ('Transparency', self.malpha is not None)) if on]
        w(f'ax.scatter({", ".join(args)}){"   # " + " and ".join(said) + " as set on the graph" if said else ""}')
        self.close(blocks)

    # ---- the statistics at each place of a factor -----------------------------------------------
    def stat_lines(self, key, resp, want):
        """Lines that give st, the statistics of resp in want at each place
        (key), as graph.summary computes them: N and Sum count a row Freq
        times; JMP's quantiles; the t interval of the mean."""
        w, f = self.w, self.freq
        if resp is None:
            w(f'st = g.groupby({key})[{_j(f)}].sum().to_frame("n")   # N: the Freq counts of each place' if f else f'st = g.groupby({key}).size().to_frame("n")   # N: the rows at each place')
            return
        if f and not self.whole:
            self.need('weighted')
            w(f'st = weighted_stats(g, {key}, {resp}, {_j(f)}, {_nm(self.alpha)})')
            return
        if f:
            w(f'g = g.loc[g.index.repeat(g[{_j(f)}].round().astype(int))]   # Freq: a row counts that many times')
        agg = {'n': 'n="count"', 'sum': 'sum="sum"', 'mean': 'mean="mean"', 'median': 'median="median"', 'min': 'min="min"', 'max': 'max="max"',
               'sd': 'sd="std"', 'se': 'se="sem"', 'var': 'var="var"',
               'q1': 'q1=lambda v: np.quantile(v, 0.25, method="weibull")', 'q3': 'q3=lambda v: np.quantile(v, 0.75, method="weibull")'}
        need = list(dict.fromkeys(['n'] + [s for s in want if s in agg] + (['mean', 'se'] if 'lower' in want else [])))
        w(f'st = g.groupby({key})[{resp}].agg({", ".join(agg[s] for s in need)})   # at each place{"; the quartiles JMP\'s, the (n + 1)p-th values" if "q1" in need or "q3" in need else ""}')
        if 'lower' in want:
            self.imp('from scipy import stats')
            w(f'st["lower"], st["upper"] = stats.t.interval({_nm(1 - self.alpha)}, st["n"] - 1, loc=st["mean"], scale=st["se"])   # the t interval of the mean')

    @staticmethod
    def stat_needs(stat, interval, resp):
        """The columns of st a statistic and an error interval need."""
        need = []
        if stat == 'range':
            need += ['min', 'max']
        elif stat == 'pct':
            need += ['sum'] if resp else []
        elif stat not in ('n',):
            need.append(stat)
        need += {'ci': ['mean', 'lower'], 'se': ['mean', 'se'], 'sd': ['mean', 'sd'], 'range': ['min', 'max'], 'iqr': ['q1', 'q3']}.get(interval or 'none', [])
        return need

    @staticmethod
    def stat_value(stat, resp):
        if stat == 'range':
            return '(st["max"] - st["min"])'
        if stat == 'pct':
            return f'100 * st["{"sum" if resp else "n"}"] / total'
        return f'st["{stat}"]'

    def err_expr(self, kind, val):
        """The Python of an error bar's lengths: symmetric for a standard error or deviation, else to each end of the interval."""
        if kind in ('se', 'sd'):
            return f'st["{kind}"]'
        lo, hi = self.interval_ends(kind)
        return f'[{val} - {lo}, {hi} - {val}]'

    @staticmethod
    def interval_ends(kind):
        return {'ci': ('st["lower"]', 'st["upper"]'), 'se': ('st["mean"] - st["se"]', 'st["mean"] + st["se"]'),
                'sd': ('st["mean"] - st["sd"]', 'st["mean"] + st["sd"]'), 'range': ('st["min"]', 'st["max"]'), 'iqr': ('st["q1"]', 'st["q3"]')}[kind]

    def total_line(self, X, Y):
        """total: the panel's sum of the response (or its count of rows), over every group, for % of Total."""
        c = _Cell(X, Y, None, '0', '0')
        resp, fac = self.resp_fac(c)
        q = self.in_groups(self.pf, (resp, fac))
        f = self.freq
        if resp:
            self.w(f'q = {q}', f'total = (q[{resp}] * q[{_j(f)}]).sum()   # the panel\'s sum of the response (Freq counted), for % of Total' if f else f'total = q[{resp}].sum()   # the panel\'s sum of the response, for % of Total')
        else:
            self.w(f'q = {q}', f'total = q[{_j(f)}].sum()   # the panel\'s count of rows, for % of Total' if f else 'total = len(q)   # the panel\'s count of rows, for % of Total')

    def band_line(self, fac):
        """band: the room of one place of a continuous factor, the narrowest step between two of its values (1 for levels)."""
        if self.R['fac_cat'] or fac is None:
            return '1'
        self.w(f'u = np.unique(df[{fac}].dropna())',
               'band = np.diff(u).min() if len(u) > 1 else (abs(u[0]) or 1.0 if len(u) else 1.0)   # a place\'s room: the narrowest step between two values')
        return 'band'

    # ---- summary statistics as points, a line or an area ------------------------------------
    def connect(self, e):
        """The Python of a line's connection: straight, a step, or a curve."""
        return e.get('shape') or 'linear'

    def curve_xy(self, at, val):
        """The vertices as the page's Curve joins them."""
        self.need('curve')
        cw, rh = (self.P.get('panel') or [400, 300])
        return f'curve({at}, {val}, {_nm(cw, 17)}, {_nm(rh, 17)})'

    def summary_marks(self, e, mode, fill=None):
        """Points with a Summary Statistic, a Line through the statistic at each
        place, or an Area under it: the statistic of each cell at each place."""
        w, R = self.w, self.R
        stat = e.get('stat') or e.get('summary') or 'mean'
        interval = e.get('interval') if e.get('interval') not in (None, 'none') else None
        what = {'markers': 'Points', 'lines': 'Line', 'area': 'Area'}[mode]
        lab = dict(_STAT_LABEL).get(stat, stat)
        w(f'# {what}: the {lab} at each place{f", with its {_INTERVAL_LABEL[interval]}" if interval else ""}')
        markers = mode == 'markers'
        slots = self.slots
        need_total = stat == 'pct'

        def before(X, Y):
            if need_total:
                self.total_line(X, Y)

        dflt = POINT if markers else INK
        c, blocks = self.cells(lambda X, Y: [x for x in self.resp_fac(_Cell(X, Y, None, '0', '0'))], dflt, before=before, si=markers and slots > 1 and R['fac_cat'])
        resp, fac = self.resp_fac(c)
        key = self.key(fac)
        self.stat_lines(key, resp, self.stat_needs(stat, interval, resp))
        at = 'st.index'
        if markers and slots > 1 and R['fac_cat']:
            slot = self.slot_expr(c)
            at = f'st.index + (-0.4 + ({slot} + 0.5) * {_nm(0.8 / slots, 12)}) * 0.6   # side by side within the level'
            w(f'at = {at}')
            at = 'at'
        val = self.stat_value(stat, resp)
        horiz = R['horiz']
        fa, ra = ('y', 'x') if horiz else ('x', 'y')
        A, V = self.drawn(fa, at), self.drawn(ra, val)
        xy = (V, A) if horiz else (A, V)
        color = c.color
        if interval:
            lo, hi = self.interval_ends(interval)
            if e.get('style') == 'band' and not markers:
                fb = 'fill_betweenx' if horiz else 'fill_between'
                w(f'ax.{fb}({A}, {self.drawn(ra, lo)}, {self.drawn(ra, hi)}, color={color}, alpha=0.18, linewidth=0)   # the Error Band')
            else:
                err = 'xerr' if horiz else 'yerr'
                w(f'ax.errorbar({xy[0]}, {xy[1]}, {err}={self.err_expr(interval, val)}, fmt="none", ecolor={color}, elinewidth={_lw(1.3)}, capsize={_nm(4 * PX)})')
        if markers:
            alpha = f', alpha={_nm(self.malpha)}' if self.malpha is not None else ''
            w(f'ax.scatter({xy[0]}, {xy[1]}, s={_area((self.msize or 6) + 2)}, color={color}{alpha})')
        else:
            shape = self.connect(e)
            if shape == 'spline':
                w(f'cx, cy = {self.curve_xy(val if horiz else at, at if horiz else val)}',
                  f'ax.plot({self.drawn("x", "cx")}, {self.drawn("y", "cy")}, color={color}, linewidth={_lw(2)})   # Curve')
                w(f'ax.plot({xy[0]}, {xy[1]}, "o", markersize={_nm(5 * PX)}, color={color})')
            else:
                step = ', drawstyle="steps-post"' if shape == 'hv' else ''
                w(f'ax.plot({xy[0]}, {xy[1]}, color={color}, linewidth={_lw(2)}, marker="o", markersize={_nm(5 * PX)}{step})')
        self.close(blocks)

    def slot_expr(self, c):
        """The Python of a cell's place among the bars (boxes, beans) side by side at a level."""
        nG = max(1, self.nG)
        parts = []
        if self.nS > 1:
            parts.append(f'{c.si} * {nG}' if nG > 1 else c.si)
        if self.group:
            parts.append(c.gi)
        return ' + '.join(parts) if parts else '0'

    # ---- Line -------------------------------------------------------------------------------------
    def el_line(self, e):
        if e.get('ordering') != 'row':
            return self.summary_marks(e, 'lines')
        w, R = self.w, self.R
        w('# Line: a vertex for every row, joined in the table\'s order')
        c, blocks = self.cells(lambda X, Y: [X, Y], INK)
        xs, ys = self.drawn('x', self.place('x', c.x)), self.drawn('y', self.place('y', c.y))
        shape = self.connect(e)
        if shape == 'spline':
            w(f'cx, cy = {self.curve_xy(self.place("x", c.x), self.place("y", c.y))}',
              f'ax.plot({self.drawn("x", "cx")}, {self.drawn("y", "cy")}, color={c.color}, linewidth={_lw(1.6)})   # Curve',
              f'ax.plot({xs}, {ys}, "o", markersize={_nm(4 * PX)}, color={c.color})')
        else:
            step = '' if shape != 'hv' else (', drawstyle="steps-pre"' if R['horiz'] else ', drawstyle="steps-post"')
            w(f'ax.plot({xs}, {ys}, color={c.color}, linewidth={_lw(1.6)}, marker="o", markersize={_nm(4 * PX)}{step})')
        self.close(blocks)

    # ---- Area -------------------------------------------------------------------------------------
    def el_area(self, e):
        if e.get('areaStyle') != 'stacked':
            return self.el_area_overlaid(e)
        w, R = self.w, self.R
        stat = e.get('stat') or 'mean'
        lab = dict(_STAT_LABEL).get(stat, stat)
        w(f'# Area, stacked: the {lab} at each place, the groups\' areas on top of one another')
        horiz = R['horiz']
        fa, ra = ('y', 'x') if horiz else ('x', 'y')
        shape = self.connect(e)
        opened = []
        pairs = self.pairs
        # one stack for each series (merged columns), its groups on top of one another
        if len(pairs) > 1:
            items = [f'({a}, {b})' for a, b in pairs]
            b = w.block(f'for x, y in [{", ".join(items)}]:   # the columns merged on an axis, a stack each')
            b.__enter__()
            opened.append(b)
            X, Y = 'x', 'y'
        else:
            X, Y = pairs[0]
        cell = _Cell(X, Y, None, '0', '0')
        resp, fac = self.resp_fac(cell)
        if stat == 'pct':
            self.total_line(X, Y)
        w('parts, hues = {}, {}')
        if self.group:
            b = w.block('for group, color in zip(groups, colors):')
            b.__enter__()
            gcol = _j(self.group['col'] + ' (bins)' if self.group.get('bins') else self.group['col'])
            w(f'g = {self.pf}[{self.pf}[{gcol}] == group].dropna(subset=[{", ".join(x for x in (resp, fac) if x)}])')
            name = 'group'
        else:
            b = None
            w(f'g = {self.pf}.dropna(subset=[{", ".join(x for x in (resp, fac) if x)}])')
            name = '0'
        with w.block('if len(g):'):
            self.stat_lines(self.key(fac), resp, self.stat_needs(stat, None, resp))
            w(f'parts[{name}], hues[{name}] = {self.stat_value(stat, resp)}, {"color" if self.group else _j(INK if len(pairs) == 1 else PALETTE[0])}')
        if b:
            b.__exit__(None, None, None)
        w('stack = pd.DataFrame(parts).fillna(0.0)   # every group\'s places; a group with no rows at a place adds 0 there (Plotly\'s infer zero)',
          'bottom = np.zeros(len(stack))')
        with w.block('for name, v in stack.items():'):
            top = 'bottom + v.to_numpy()'
            A = self.drawn(fa, 'stack.index')
            fb = 'fill_betweenx' if horiz else 'fill_between'
            step = ', step="post"' if shape == 'hv' else ''
            w(f'ax.{fb}({A}, {self.drawn(ra, "bottom")}, {self.drawn(ra, top)}, color=hues[name], alpha=0.55, linewidth=0{step})')
            ds = ', drawstyle="steps-post"' if shape == 'hv' else ''
            xy = (self.drawn(ra, top), A) if horiz else (A, self.drawn(ra, top))
            w(f'ax.plot({xy[0]}, {xy[1]}, color=hues[name], linewidth={_lw(2)}{ds})',
              f'bottom = {top}')
        self.close(opened)

    def el_area_overlaid(self, e):
        w, R = self.w, self.R
        stat = e.get('stat') or 'mean'
        lab = dict(_STAT_LABEL).get(stat, stat)
        w(f'# Area: the {lab} at each place, the area under it filled')

        def before(X, Y):
            if stat == 'pct':
                self.total_line(X, Y)
        c, blocks = self.cells(lambda X, Y: [x for x in self.resp_fac(_Cell(X, Y, None, '0', '0'))], INK, before=before)
        resp, fac = self.resp_fac(c)
        self.stat_lines(self.key(fac), resp, self.stat_needs(stat, None, resp))
        horiz = R['horiz']
        fa, ra = ('y', 'x') if horiz else ('x', 'y')
        val = self.stat_value(stat, resp)
        A, V = self.drawn(fa, 'st.index'), self.drawn(ra, val)
        shape = self.connect(e)
        fb = 'fill_betweenx' if horiz else 'fill_between'
        step = ', step="post"' if shape == 'hv' else ''
        w(f'ax.{fb}({A}, 0, {V}, color={c.color}, alpha=0.32, linewidth=0{step})')
        xy = (V, A) if horiz else (A, V)
        ds = ', drawstyle="steps-post"' if shape == 'hv' else ''
        w(f'ax.plot({xy[0]}, {xy[1]}, color={c.color}, linewidth={_lw(2)}{ds})')
        self.close(blocks)

    # ---- Bar ----------------------------------------------------------------------------------------
    def el_bar(self, e):
        w, R = self.w, self.R
        stat = e.get('stat') or 'mean'
        interval = e.get('interval') if e.get('interval') not in (None, 'none') else None
        style = e.get('barStyle') or 'side'
        label = e.get('label') or 'none'
        lab = dict(_STAT_LABEL).get(stat, stat)
        w(f'# Bar: the {lab} at each place{f", with its {_INTERVAL_LABEL[interval]}" if interval else ""}{", stacked" if style == "stacked" else ", as needles" if style == "needle" else ""}')
        slots = self.slots
        stacked, needle = style == 'stacked', style == 'needle'
        if stacked:
            w('base = {}   # Stacked: where the next bar starts, at each place and for each sign')

        def before(X, Y):
            if stat == 'pct' or label == 'percent':
                self.total_line(X, Y)
            fac = self.resp_fac(_Cell(X, Y, None, '0', '0'))[1]
            self.band = self.band_line(fac)

        c, blocks = self.cells(lambda X, Y: [x for x in self.resp_fac(_Cell(X, Y, None, '0', '0'))], BAR, before=before, si=slots > 1)
        resp, fac = self.resp_fac(c)
        band = self.band
        self.stat_lines(self.key(fac), resp, self.stat_needs(stat, interval, resp) + (['sum'] if label == 'percent' and resp else []))
        width = f'0.8 * {band}' if stacked else f'0.08 * {band}' if needle else f'{_nm(0.8 / slots * 0.92, 12)} * {band}'
        width = width.replace(' * 1', '') if band == '1' else width
        if stacked or slots == 1:
            w('at = st.index')
        else:
            slot = self.slot_expr(c)
            w(f'at = st.index + (-0.4 + ({slot} + 0.5) * {_nm(0.8 / slots, 12)}) * {band}   # side by side within the place'.replace(' * 1   #', '   #'))
        w(f'v = ({self.stat_value(stat, resp)}).fillna(0.0)')
        horiz = R['horiz']
        fa, ra = ('y', 'x') if horiz else ('x', 'y')
        if stacked:
            w('start = np.array([base.get((q, x < 0), 0.0) for q, x in zip(st.index, v)])')
            with w.block('for q, x, s0 in zip(st.index, v, start):'):
                w('base[(q, x < 0)] = s0 + x')
        # the page's colour: a second merged column's groups a lighter shade
        color = c.color
        shade = color
        edge = ''
        if self.group and self.nS > 1:
            edge = f', edgecolor={color}, linewidth={_lw(1)}'
            shade = f'to_rgba({color}, max(0.35, 1 - 0.3 * {c.si})) if {c.si} else {color}'
            self.imp('from matplotlib.colors import to_rgba')
        fn = 'barh' if horiz else 'bar'
        size = 'height' if horiz else 'width'
        base_kw = (', left=' if horiz else ', bottom=') + self.drawn(ra, 'start') if stacked else ''
        if self.date[fa] and not R['fac_cat']:
            width = f'({width}) / 86400000'   # a date axis in days
        w(f'bars = ax.{fn}({self.drawn(fa, "at")}, v, {size}={width}{base_kw}, color={shade}{edge})')
        if label != 'none':
            self.need('fmt')
            if label == 'percent':
                num = f'100 * st["{"sum" if resp else "n"}"] / total'
                w(f'ax.bar_label(bars, labels=[f"{{q:.1f}}%" for q in {num}], label_type="{"center" if stacked else "edge"}", fontsize=7)   # Label by Percent of Total Values')
            else:
                w(f'ax.bar_label(bars, labels=[fmt(q) for q in v], label_type="{"center" if stacked else "edge"}", fontsize=7)   # Label by Value')
        if interval:
            lo, hi = self.interval_ends(interval)
            err = 'xerr' if horiz else 'yerr'
            top = 'start + v' if stacked else 'v'
            xy = (top, self.drawn(fa, 'at')) if horiz else (self.drawn(fa, 'at'), top)
            w(f'ax.errorbar({xy[0]}, {xy[1]}, {err}={self.err_expr(interval, "v")}, fmt="none", ecolor="{TEXT}", elinewidth={_lw(1.2)}, capsize={_nm(4 * PX)})')
        self.close(blocks)


    # ---- Box Plot ---------------------------------------------------------------------------------------
    def el_box(self, e):
        w, R = self.w, self.R
        quant = e.get('boxType') == 'quantile'
        style = e.get('boxStyle') or 'normal'
        w(f'# Box Plot: {"quantile boxes (the whiskers to the minimum and the maximum)" if quant else "outlier boxes (the whiskers to the furthest values within 1.5 IQR)"} with JMP\'s quartiles, at each place')
        self.need('box')
        slots = self.slots
        self.imp('from matplotlib.colors import to_rgba')

        def before(X, Y):
            fac = self.resp_fac(_Cell(X, Y, None, '0', '0'))[1]
            self.band = self.band_line(fac)

        c, blocks = self.cells(lambda X, Y: [x for x in self.resp_fac(_Cell(X, Y, None, '0', '0'))], BOX_BLUE, before=before, si=slots > 1)
        resp, fac = self.resp_fac(c)
        band = self.band
        f = self.freq
        key = self.key(fac)
        if f and not self.whole:
            self.need('wbox')
            w(f'boxes = {{k: weighted_box(s[{resp}], s[{_j(f)}]{", quantile=True" if quant else ""}) for k, s in g.groupby({key})}}   # Freq: the quartiles weighted (DescrStatsW)')
        elif f:
            w(f'boxes = {{k: box(s[{resp}], s[{_j(f)}]{", quantile=True" if quant else ""}) for k, s in g.groupby({key})}}   # Freq: the quartiles count a row that many times')
        else:
            w(f'boxes = {{k: box(v{", quantile=True" if quant else ""}) for k, v in g.groupby({key})[{resp}]}}')
        wid = float(e['width']) if e.get('width') is not None else 0.5
        wid = min(1.0, max(0.05, wid)) * 1.1 * (0.8 / slots) * (0.4 if style == 'thin' else 1)
        width = f'{_nm(wid, 12)} * {band}' if band != '1' else _nm(wid, 12)
        if slots == 1:
            w('at = np.array(list(boxes), dtype=float)')
        else:
            slot = self.slot_expr(c)
            w(f'at = np.array(list(boxes), dtype=float) + (-0.4 + ({slot} + 0.5) * {_nm(0.8 / slots, 12)}){" * " + band if band != "1" else ""}   # side by side within the place')
        fill = f'to_rgba({c.color}, 0.7)' if style == 'solid' else ('"none"' if style == 'thin' else f'to_rgba({c.color}, 0.18)')
        line = f'"{TEXT}"' if style == 'solid' else c.color
        lw = _lw(1 if style == 'thin' else 1.4)
        orient = ', orientation="horizontal"' if R['horiz'] else ''
        pos = 'at'
        if self.date['y' if R['horiz'] else 'x'] and not R['fac_cat']:
            pos = 'at / 86400000'   # a date axis: bxp takes its places in days
        fl = f'{{"marker": "o", "markersize": {_nm((self.msize or 5) * PX)}, "markerfacecolor": {c.color}, "markeredgecolor": "none"{", " + chr(34) + "alpha" + chr(34) + ": " + _nm(self.malpha) if self.malpha is not None else ""}}}'
        show = 'False' if quant or e.get('outliers') is False else 'True'
        with w.block('if boxes:   # (a panel or group without values has none)'):
            w(f'ax.bxp(list(boxes.values()), positions={pos}, widths={width}{orient}, patch_artist=True, showfliers={show},',
              f'       boxprops={{"facecolor": {fill}, "edgecolor": {line}, "linewidth": {lw}}}, medianprops={{"color": {line}, "linewidth": {lw}}},',
              f'       whiskerprops={{"color": {line}, "linewidth": {lw}}}, capprops={{"color": {line}, "linewidth": {lw}}}, capwidths={width} * 0.5, flierprops={fl})')
        if e.get('diamond'):
            self.stat_lines(key, resp, ['mean', 'lower'])
            hw = f'{_nm(wid / 2, 12)}' + (f' * {band}' if band != '1' else '')
            with w.block('for q, m, lo, hi in zip(at, st["mean"], st["lower"], st["upper"]):   # the Confidence Diamond: the mean and its t interval'):
                pts = f'[q, q + {hw}, q, q - {hw}, q], [lo, m, hi, m, lo]'
                if R['horiz']:
                    pts = f'[lo, m, hi, m, lo], [q, q + {hw}, q, q - {hw}, q]'
                w(f'ax.plot({pts}, color="#c0392b", linewidth={_lw(1.3)})')
        self.close(blocks)

    # ---- Histogram --------------------------------------------------------------------------------------
    def hist_setup(self, e):
        b = e.get('bins') or {}
        if not getattr(self, '_hist_bins', False):
            self.pre(f'start, size, nb, end = {_nm(b.get("start", 0), 15)}, {_nm(b.get("size", 1), 15)}, {int(b.get("nb", 1))}, {_nm(b.get("end", b.get("start", 0) + b.get("nb", 1) * b.get("size", 1)), 15)}   # the histogram\'s bins, the page\'s{" (Bin Width)" if e.get("binWidth") else ""}: every panel and group has the same')
            self._hist_bins = True

    def kde1_lines(self, v, f, bw, lo=None, hi=None, n=128, name='kde'):
        """Lines of a one-dimensional density of the values v (weights f): scipy's
        gaussian_kde, Scott's bandwidth times bw, on a grid (as graph.kde1)."""
        self.imp('from scipy import stats')
        w = self.w
        w(f'{name} = stats.gaussian_kde({v}{", weights=" + f if f else ""})')
        if float(bw) != 1:
            w(f'{name}.set_bandwidth({name}.factor * {_nm(bw)})')
        if lo is None:
            w(f'h = np.sqrt({name}.covariance[0, 0])', f'grid = np.linspace({v}.min() - 3 * h, {v}.max() + 3 * h, {n})')
        else:
            w(f'grid = np.linspace({lo}, {hi}, {n})')
        w(f'dens = {name}(grid)')

    def pre_histogram(self, e):
        """The longest bar (or curve) of every histogram in a band, over every panel: each is drawn to it."""
        if not e.get('band'):
            return
        self.hist_setup(e)
        w = self.pre
        cols = self.all_keys()
        pairs = self.pairs_all()
        resp_fac = [self.resp_fac(_Cell(x, y, None, '0', '0')) for x, y in pairs]
        f = self.freq
        pct = e.get('scale') == 'percent'
        kernel = e.get('kernel')
        w('most = 0.0   # the longest bar of every histogram: all of them are drawn to it, as the page scales them')
        for resp, fac in dict.fromkeys(resp_fac):
            keys = cols + [fac]
            with w.block(f'for _, s in {self.in_groups("df", [resp] + keys)}.groupby([{", ".join(dict.fromkeys(keys))}]):'):
                tot = f'tot = {"s[" + _j(f) + "].sum()" if f else "len(s)"}'
                if kernel:
                    if not pct:
                        w(tot)
                    with w.block(f'if len(s) > 1 and np.ptp(s[{resp}]) > 0:'):
                        w(f'kde = stats.gaussian_kde(s[{resp}]{", weights=s[" + _j(f) + "]" if f else ""})')
                        if float(e.get('bw') or 1) != 1:
                            w(f'kde.set_bandwidth(kde.factor * {_nm(e.get("bw"))})')
                        w(f'most = max(most, kde(np.linspace(start, end, 128)).max() * {"size * 100" if pct else "tot * size"})')
                    self.imp('from scipy import stats')
                else:
                    w(f'k = np.clip(np.floor((s[{resp}] - start) / size + 1e-9), 0, nb - 1).astype(int)')
                    if pct:
                        w(tot)
                    w(f'most = max(most, np.bincount(k, {"weights=s[" + _j(f) + "], " if f else ""}minlength=nb).max(){" * 100 / tot" if pct else ""})')

    def el_histogram(self, e):
        w, R = self.w, self.R
        self.hist_setup(e)
        band = bool(e.get('band'))
        kernel = bool(e.get('kernel'))
        pct = e.get('scale') == 'percent'
        f = self.freq
        w(f'# Histogram: {"a kernel density curve (scipy\'s gaussian_kde), scaled to the counts" if kernel else "the rows counted in the bins"}{" in percent" if pct else ""}{", one for each level, from the edge of its room" if band else ""}')
        colors_bar = self.group or self.nS > 1

        def need(X, Y):
            resp, fac = self.resp_fac(_Cell(X, Y, None, '0', '0'))
            return [resp, fac] if band else [resp]
        c, blocks = self.cells(need, BAR if not kernel else INK)
        resp, fac = self.resp_fac(c)
        opened = []
        if band:
            b = w.block(f'for level, s in g.groupby({self.key(fac)}):   # a histogram at each level')
            b.__enter__()
            opened.append(b)
            frame = 's'
        else:
            frame = 'g'
        with w.block(f'if len({frame}) > 1 and np.ptp({frame}[{resp}]) > 0:   # a density needs two distinct values' if kernel else f'if len({frame}):'):
            if not (kernel and pct):
                w(f'tot = {frame}[{_j(f)}].sum()' if f else f'tot = len({frame})')
            scale = ' * 100 / tot' if pct else ''
            horiz = R['horiz']
            if kernel:
                self.kde1_lines(f'{frame}[{resp}]', f'{frame}[{_j(f)}]' if f else None, e.get('bw') or 1, 'start', 'end')
                sc = ' * 0.8 / most' if band else ''
                w(f'L = dens * size * 100{sc}   # the density scaled to the counts, in percent of the rows' if pct
                  else f'L = dens * tot * size{sc}   # the density scaled to the counts')
                col = c.color
                along = self.drawn('x' if horiz else 'y', 'grid')
                if band:
                    q = 'level + 0.4' if horiz else 'level - 0.4'
                    sign = '-' if horiz else '+'
                    if horiz:
                        w(f'ax.fill({self.drawn("x", "np.r_[grid, grid[-1], grid[0]]")}, np.r_[{q} {sign} L, {q}, {q}], facecolor=to_rgba({col}, 0.2), edgecolor={col}, linewidth={_lw(1.8)})')
                    else:
                        w(f'ax.fill(np.r_[{q} {sign} L, {q}, {q}], {self.drawn("y", "np.r_[grid, grid[-1], grid[0]]")}, facecolor=to_rgba({col}, 0.2), edgecolor={col}, linewidth={_lw(1.8)})')
                    self.imp('from matplotlib.colors import to_rgba')
                elif horiz:
                    w(f'ax.fill_between({along}, 0, L, color={col}, alpha=0.2, linewidth=0)', f'ax.plot({along}, L, color={col}, linewidth={_lw(1.8)})')
                else:
                    w(f'ax.fill_betweenx({along}, 0, L, color={col}, alpha=0.2, linewidth=0)', f'ax.plot(L, {along}, color={col}, linewidth={_lw(1.8)})')
            else:
                w(f'k = np.clip(np.floor(({frame}[{resp}] - start) / size + 1e-9), 0, nb - 1).astype(int)   # each value\'s bin, as the page counts',
                  f'counts = np.bincount(k, {"weights=" + frame + "[" + _j(f) + "], " if f else ""}minlength=nb){scale}',
                  'mids = start + (np.arange(nb) + 0.5) * size')
                col = f'to_rgba({c.color}, 0.6)' if colors_bar else c.color
                if colors_bar:
                    self.imp('from matplotlib.colors import to_rgba')
                size_ = 'size / 86400000' if self.date['x' if horiz else 'y'] else 'size'
                mids = self.drawn('x' if horiz else 'y', 'mids')
                if band:
                    if horiz:
                        w(f'bars = ax.bar({mids}, -counts * 0.8 / most, width={size_}, bottom=level + 0.4, color={col}, edgecolor="{SURFACE}", linewidth={_lw(0.6)})')
                    else:
                        w(f'bars = ax.barh({mids}, counts * 0.8 / most, height={size_}, left=level - 0.4, color={col}, edgecolor="{SURFACE}", linewidth={_lw(0.6)})')
                elif horiz:
                    w(f'bars = ax.bar({mids}, counts, width={size_}, color={col}, edgecolor="{SURFACE}", linewidth={_lw(0.6)})')
                else:
                    w(f'bars = ax.barh({mids}, counts, height={size_}, color={col}, edgecolor="{SURFACE}", linewidth={_lw(0.6)})')
                if e.get('counts'):
                    self.need('fmt')
                    w('ax.bar_label(bars, labels=[fmt(q) if q else "" for q in counts], fontsize=6.5)   # Counts')
        self.close(opened)
        self.close(blocks)

    # ---- Heatmap ---------------------------------------------------------------------------------------
    def heat_axis(self, spec, col, axis):
        """The Python of a heatmap axis: each row's cell number, the cells' edges, their count."""
        if spec is None or col is None:
            return 'np.zeros(len(g), dtype=int)', 'np.array([-0.5, 0.5])', 1
        if spec.get('cat'):
            k = len(self.levels.get(spec['cat'], {}).get('values', []))
            return f'g[{col}].map(place[{col}])', f'np.arange({k + 1}) - 0.5', k
        n = int(spec['n'])
        s0, sz = _nm(spec['start'], 15), _nm(spec['size'], 15)
        return f'np.clip(np.floor((g[{col}] - {s0}) / {sz} + 1e-9), 0, {n - 1})', self.drawn(axis, f'{s0} + {sz} * np.arange({n + 1})'), n

    def el_heatmap(self, e):
        w = self.w
        cc = e.get('cc')
        f = self.freq
        w(f'# Heatmap: {"the mean of " + cc if cc else "the count of rows"} in each cell of X by Y, on one colour scale for every panel')
        if not getattr(self, '_heat_first', False):
            self.pre('meshes = []   # the heatmaps of every panel, to be put on one colour scale')
            if not cc:
                self.imp('from matplotlib.colors import LinearSegmentedColormap')
                self.pre(f'counts_map = LinearSegmentedColormap.from_list("counts", {_py(HEAT)})   # the page\'s scale of counts')
            elif not self.P.get('color') or self.P['color'].get('cat'):
                self.imp('from matplotlib.colors import LinearSegmentedColormap')
                self.pre(f'ramp = LinearSegmentedColormap.from_list("ramp", {_py(RAMP)}).with_extremes(bad="{MISSING}")   # the page\'s blue-grey-red')
            self._heat_first = True
        X, Y = self.pairs[0]
        need = [x for x in (X, Y, _j(cc) if cc else None) if x]
        w(f'g = {self.pf}.dropna(subset=[{", ".join(dict.fromkeys(need))}])')
        ix, xedges, nx = self.heat_axis(e.get('hx'), X, 'x')
        iy, yedges, ny = self.heat_axis(e.get('hy'), Y, 'y')
        wt = f'g[{_j(f)}]' if f else 'pd.Series(1.0, index=g.index)'
        w(f'cell = pd.DataFrame({{"i": {iy}, "j": {ix}, "w": {wt}}})   # each row\'s cell: its row i (Y) and column j (X)')
        if cc:
            w(f'cell["v"] = g[{_j(cc)}] * cell["w"]',
              'sums = cell.groupby(["i", "j"])[["w", "v"]].sum()',
              f'Z = np.full(({ny}, {nx}), np.nan)',
              'Z[sums.index.get_level_values(0).astype(int), sums.index.get_level_values(1).astype(int)] = sums["v"] / sums["w"]   # the Freq-weighted mean in each cell' if f else 'Z[sums.index.get_level_values(0).astype(int), sums.index.get_level_values(1).astype(int)] = sums["v"] / sums["w"]   # the mean in each cell',
              'N = np.zeros_like(Z)',
              'N[sums.index.get_level_values(0).astype(int), sums.index.get_level_values(1).astype(int)] = sums["w"]')
        else:
            w('n = cell.groupby(["i", "j"])["w"].sum()',
              f'Z = np.full(({ny}, {nx}), np.nan)',
              'Z[n.index.get_level_values(0).astype(int), n.index.get_level_values(1).astype(int)] = n   # a cell without rows is left out',
              'N = np.nan_to_num(Z)')
        w(f'meshes.append(ax.pcolormesh({xedges}, {yedges}, Z, cmap={"ramp" if cc else "counts_map"}, edgecolors="white", linewidth={_lw(1)}))')
        label = e.get('label') or 'none'
        if label != 'none':
            self.need('fmt')
            with w.block('for i, j in zip(*np.nonzero(~np.isnan(Z))):'):
                cx = f'({xedges})[j:j + 2].mean()' if not self.date['x'] else f'{xedges}[j] + ({xedges}[j + 1] - {xedges}[j]) / 2'
                cy = f'({yedges})[i:i + 2].mean()' if not self.date['y'] else f'{yedges}[i] + ({yedges}[i + 1] - {yedges}[i]) / 2'
                txt = 'f"{100 * N[i, j] / N.sum():.1f}%"' if label == 'percent' else ('fmt(float(f"{Z[i, j]:.3g}"))' if cc else 'fmt(Z[i, j])')
                w(f'ax.text({cx}, {cy}, {txt}, ha="center", va="center", fontsize=7)')


    # ---- Mosaic ------------------------------------------------------------------------------------------
    def el_mosaic(self, e):
        w = self.w
        X, Y = [_j(v) if v else None for v in self.series[0][0][0]]
        x_name, y_name = self.series[0][0][0]
        xl = self.levels.get(x_name, {})
        f = self.freq
        w(f'# Mosaic: a column for each level of {x_name} as wide as its share of the rows, split by the shares of the levels of {y_name}')
        w(f'counts = pd.crosstab({self.pf}[{X}], {self.pf}[{Y}]{", values=" + self.pf + "[" + _j(f) + "], aggfunc=\"sum\"" if f else ""}).reindex(index=levels[{X}], columns=levels[{Y}]).fillna(0.0)',
          'n = counts.to_numpy()')
        self.imp('from matplotlib.colors import to_rgba')
        lab = e.get('cellLabel') or 'none'
        labels = xl.get('labels') or []
        with w.block('if n.sum() > 0:   # (a panel without rows is left empty)'):
            w('widths = n.sum(axis=1) / n.sum()   # each X level\'s share of the rows',
              'left = np.cumsum(widths) - widths',
              'mids = left + widths / 2',
              'heights = n / np.where(n.sum(axis=1, keepdims=True) > 0, n.sum(axis=1, keepdims=True), 1)   # the shares of the Y levels within each X level',
              'bottoms = np.cumsum(heights, axis=1) - heights')
            with w.block(f'for j in range(n.shape[1]):   # a colour for each level of {y_name}, the page\'s palette'):
                w(f'bars = ax.bar(mids, heights[:, j], width=np.maximum(0, widths - 0.012), bottom=bottoms[:, j], color=to_rgba({_py(PALETTE)}[j % {len(PALETTE)}], 0.85), edgecolor="{SURFACE}", linewidth={_lw(1)})')
                if lab == 'count':
                    self.need('fmt')
                    w('ax.bar_label(bars, labels=[fmt(q) if q else "" for q in n[:, j]], label_type="center", fontsize=7)   # Label by Count')
                elif lab == 'percent':
                    w('ax.bar_label(bars, labels=[f"{100 * q:.1f}%" if q else "" for q in heights[:, j]], label_type="center", fontsize=7)   # Label by Percent')
            w(f'ax.set_xticks(mids, {_py(labels)})')
        self.imp('from matplotlib.ticker import PercentFormatter')
        w('ax.set_xlim(0, 1)', 'ax.set_ylim(0, 1)', 'ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))')
        if e.get('chisq'):
            self.imp('from scipy import stats')
            self.need('fmt', 'fmt_p')
            w('used = n[n.sum(axis=1) > 0][:, n.sum(axis=0) > 0]   # the levels with rows')
            with w.block('if used.shape[0] > 1 and used.shape[1] > 1:'):
                w('chi2, p_, df_, expected = stats.chi2_contingency(used, correction=False)   # Pearson\'s test of independence, as graph.chisq',
                  'test = f"Pearson χ² {fmt(chi2, 5)}, df {df_}, p {fmt_p(p_)}"')
            with w.block('else:'):
                w('test = "needs two levels of each variable"')
            w('ax.set_title((ax.get_title() + "\\n" if ax.get_title() else "") + test, fontsize=8)   # above the panel, as the page writes it')

    # ---- Caption Box --------------------------------------------------------------------------------------
    def el_caption(self, e):
        w, R = self.w, self.R
        stats_ = (e.get('stats') or ['mean'])[:5]
        per = e.get('location') == 'factor'
        names = dict(_STAT_LABEL)
        w(f'# Caption Box: {", ".join(names.get(s_, s_) for s_ in stats_)} of the response{" at each place" if per else ", in the corner"}')
        self.need('fmt')
        c, blocks = self.cells(lambda X, Y: [x for x in self.resp_fac(_Cell(X, Y, None, '0', '0'))[:2 if per else 1]], None, gi=True)
        resp, fac = self.resp_fac(c)
        want = [s_ for s_ in stats_]
        need = []
        for s_ in want:
            need += ['min', 'max'] if s_ == 'range' else [s_]
        self.stat_lines(self.key(fac) if per else self.key(None), resp, [x for x in need if x != 'n'])
        color = c.color if self.group else f'"{TEXT}"'
        k = len(stats_)
        lines = ' + "\\n" + '.join(f'"{names.get(s_, s_)}: " + fmt({self.stat_value(s_, resp).replace("st[", "row[")}, 5)' for s_ in stats_)
        shift = f'-{c.gi} * {(12 if per and fac else 13) * k * PX:g}' if self.group else '0'
        with w.block('for pos, row in st.iterrows():   # a place on the axis, its statistics'):
            w(f'text = {lines}')
            if per and fac:
                if R['horiz']:
                    w(f'ax.annotate(text, (0.99, pos), xycoords=("axes fraction", "data"), xytext=(0, {shift}), textcoords="offset points", ha="right", va="center", fontsize=7, color={color})')
                else:
                    w(f'ax.annotate(text, ({self.drawn("x", "pos")}, 0.99), xycoords=("data", "axes fraction"), xytext=(0, {shift}), textcoords="offset points", ha="center", va="top", fontsize=7, color={color})')
            else:
                w(f'ax.annotate(text, (0.99, 0.99), xycoords="axes fraction", xytext=(0, {shift}), textcoords="offset points", ha="right", va="top", fontsize=7, color={color}, bbox={{"facecolor": "{SURFACE}", "alpha": 0.75, "edgecolor": "none"}})')
        self.close(blocks)

    # ---- Pie -------------------------------------------------------------------------------------------
    def el_pie(self, e):
        w = self.w
        stat = e.get('stat') or 'n'
        label = e.get('label') or 'percent'
        ring = e.get('pieStyle') == 'ring'
        X, Y = [_j(v) if v else None for v in self.series[0][0][0]]
        resp, fac = self.resp_fac(_Cell(X, Y, None, '0', '0'))
        names = dict(_STAT_LABEL)
        w(f'# Pie: a slice for each level{f" of {json.loads(fac)}" if fac else ""}, its {names.get(stat, stat)}{f" of {json.loads(resp)}" if resp and stat != "n" else ""}')
        cols = [x for x in (resp, fac) if x]
        w(f'g = {self.pf}.dropna(subset=[{", ".join(cols)}])' if cols else f'g = {self.pf}')
        self.stat_lines(self.key(fac), resp if stat != 'n' else None, self.stat_needs(stat, None, resp) if stat != 'n' else [])
        w(f'v = {self.stat_value(stat, resp)}.clip(lower=0).fillna(0.0)   # a negative value makes an empty slice')
        text = {'percent': 'autopct=lambda q: f"{q:.3g}%"', 'value': 'labels=[f"{q:.10g}" for q in v], labeldistance=0.6', 'level': 'labels=[names[int(k)] for k in v.index], labeldistance=0.6' if fac else 'labels=[""]', 'none': None}.get(label)
        kinds = [f'colors=[{_py(PALETTE)}[int(k) % {len(PALETTE)}] for k in v.index]', 'startangle=90, counterclock=False']
        if text:
            kinds.append(text)
        kinds.append(f'wedgeprops={{"edgecolor": "{SURFACE}", "linewidth": {_lw(1)}{", " + chr(34) + "width" + chr(34) + ": 0.55" if ring else ""}}}, textprops={{"fontsize": 7}}')
        fl = self.levels.get(json.loads(fac), {}).get('labels', []) if fac and self.R['fac_cat'] else []
        if fl:
            w(f'names = {_py(fl)}   # the levels\' labels')
        with w.block('if v.sum() > 0:   # (a panel without rows, or of zeros, has no slices)'):
            w(f'wedges = ax.pie(v, {", ".join(kinds)})[0]')
        w('ax.set_aspect("equal")')
        self._pie = True


    # ---- the model elements: numpy arrays of a cell's X and Y (and Freq) ---------------------------
    def arrays(self, c):
        w = self.w
        w(f'xv, yv = g[{c.x}].to_numpy(float), g[{c.y}].to_numpy(float)')
        if self.freq:
            w(f'fv = g[{_j(self.freq)}].to_numpy(float)   # Freq: a row counts fv times')

    def repeat_whole(self):
        """Freq of whole numbers: the rows repeated, as graph.py repeats them for methods without weights."""
        if self.freq and self.whole:
            self.w('xv, yv = np.repeat(xv, fv.astype(int)), np.repeat(yv, fv.astype(int))   # Freq: a row counts that many times')

    def corner_count(self, name='k', where='top left'):
        """A count of the lines of text in a corner of the panel so far (the fits' equations, the correlations)."""
        if name not in self.corner:
            self.w(f'{name} = 0   # the lines of text written in the panel\'s {where} corner so far')
            self.corner.add(name)

    # ---- Smoother ------------------------------------------------------------------------------------------
    def el_smoother(self, e):
        w = self.w
        lowess_ = e.get('method') == 'lowess'
        f = self.freq
        if lowess_:
            frac, it = float(e.get('frac', 2 / 3)), int(e.get('it', 3))
            w(f'# Smoother: statsmodels\' lowess (span {_nm(frac)}, {it} robustifying iterations), the page\'s Local Kernel')
            self.imp('from statsmodels.nonparametric.smoothers_lowess import lowess')
        else:
            lam = float(e.get('lam', 0.05))
            w(f'# Smoother: JMP\'s cubic smoothing spline on standardized X, lambda {_nm(lam)} (scipy\'s make_smoothing_spline){"; its Confidence of Fit by the bootstrap" if e.get("conf") else ""}')
            self.imp('from scipy.interpolate import make_smoothing_spline')
        c, blocks = self.cells(lambda X, Y: [X, Y], INK)
        self.arrays(c)
        X, Y = self.drawn('x', 'grid'), self.drawn('y', 'fit')
        if lowess_:
            self.repeat_whole()
            with w.block('if len(np.unique(xv)) >= 3:   # the local kernel smoother needs 3 distinct X values'):
                w(f'fit = lowess(yv, xv, frac={_nm(frac, 12)}, it={it}, delta=0.01 * np.ptp(xv) if len(xv) > 1000 else 0.0)   # sorted X and the smoothed Y',
                  'grid, first = np.unique(fit[:, 0], return_index=True)',
                  'fit = fit[first, 1]',
                  f'ax.plot({X}, {Y}, color={c.color}, linewidth={_lw(2.2)})')
            self.close(blocks)
            return
        with w.block('if len(np.unique(xv)) >= 5 and fv.sum() > 1:   # the spline needs 5 distinct X values (and more than one row\'s weight)' if f
                     else 'if len(np.unique(xv)) >= 5:   # the spline needs 5 distinct X values'):
            if f:
                w('m = np.average(xv, weights=fv)',
                  's = np.sqrt(np.sum(fv * (xv - m) ** 2) / (fv.sum() - 1))   # JMP standardizes X (Freq-weighted)')
            else:
                w('m, s = xv.mean(), xv.std(ddof=1)   # JMP standardizes X')
            w('z, inv = np.unique((xv - m) / s, return_inverse=True)')
            if f:
                w('w = np.bincount(inv, weights=fv)   # tied X: the mean of Y, weighted by the count',
                  f'spline = make_smoothing_spline(z, np.bincount(inv, fv * yv) / w, w=w, lam={_nm(lam, 12)})')
            else:
                w('w = np.bincount(inv).astype(float)   # tied X: the mean of Y, weighted by the count',
                  f'spline = make_smoothing_spline(z, np.bincount(inv, yv) / w, w=w, lam={_nm(lam, 12)})')
            w('grid = np.linspace(xv.min(), xv.max(), 120)', 'fit = spline((grid - m) / s)')
            if e.get('conf'):
                self.imp('from scipy import stats')
                w('rng = np.random.default_rng(20260926)   # the page\'s resamples, from its seed: the band is the same at every redraw',
                  'zr, curves = (xv - m) / s, []')
                with w.block('for _ in range(100 if len(xv) <= 2000 else max(25, 200000 // len(xv))):'):
                    w('i = rng.integers(0, len(xv), len(xv))',
                      'zi, ii = np.unique(zr[i], return_inverse=True)')
                    with w.block('if len(zi) < 5:'):
                        w('continue')
                    w('wi = np.bincount(ii, weights=fv[i])' if f else 'wi = np.bincount(ii).astype(float)')
                    with w.block('try:'):
                        w(f'curves.append(make_smoothing_spline(zi, np.bincount(ii, {"fv[i] * yv[i]" if f else "yv[i]"}) / wi, w=wi, lam={_nm(lam, 12)})((grid - m) / s))')
                    with w.block('except Exception:'):
                        w('continue')
                with w.block('if len(curves) >= 10:'):
                    w(f'half = stats.norm.ppf({_nm(1 - self.alpha / 2)}) * np.std(curves, axis=0, ddof=1)   # the fit plus or minus z times the resamples\' spread',
                      f'ax.fill_between({X}, {self.drawn("y", "fit - half")}, {self.drawn("y", "fit + half")}, color={c.color}, alpha=0.18, linewidth=0)   # Confidence of Fit')
            w(f'ax.plot({X}, {Y}, color={c.color}, linewidth={_lw(2.2)})')
        self.close(blocks)

    # ---- Line of Fit ----------------------------------------------------------------------------------------
    def el_fit(self, e):
        w = self.w
        deg = max(1, min(3, int(e.get('degree') or 1)))
        p = deg + 1
        robust = bool(e.get('robust'))
        what = {1: 'line', 2: 'quadratic', 3: 'cubic'}[deg]
        a = self.alpha
        w(f'# Line of Fit: a {"robust " if robust else ""}{what} (statsmodels {"RLM with Cauchy weights" if robust else "OLS"}){f", its {_nm(100 * (1 - a))}% Confidence of Fit" if e.get("confFit", True) else ""}{f" and of Prediction" if e.get("confPred") and not robust else ""}')
        if robust:
            self.need('cauchy')
            self.imp('from scipy import stats')
        texts = [t for t in ('equation', 'r2', 'rmse', 'ftest') if e.get(t) and not (robust and t in ('r2', 'ftest'))]
        if texts:
            self.need('fmt')
            if 'ftest' in texts:
                self.need('fmt_p')
            self.corner_count()
        c, blocks = self.cells(lambda X, Y: [X, Y], FIT_RED)
        self.arrays(c)
        self.repeat_whole()
        G = self.drawn('x', 'grid')
        with w.block(f'if len(np.unique(xv)) >= {p} and len(xv) > {p}:   # a degree {deg} fit needs more than {p} rows at {p} distinct X values'):
            w('m, s = xv.mean(), xv.std(ddof=1) or 1.0   # fitted on standardized X: the same line, better conditioned',
              f'X = np.vander((xv - m) / s, {p}, increasing=True)',
              'grid = np.linspace(xv.min(), xv.max(), 100)',
              f'at = np.vander((grid - m) / s, {p}, increasing=True)')
            if robust:
                w('fit = sm.RLM(yv, X, M=Cauchy()).fit()',
                  'pred = at @ fit.params',
                  'se = np.sqrt(np.einsum("ij,jk,ik->i", at, fit.cov_params(), at))',
                  f'z = stats.norm.ppf({_nm(1 - a / 2)})   # the robust band takes the normal quantile')
                if e.get('confFit', True):
                    w(f'ax.fill_between({G}, {self.drawn("y", "pred - z * se")}, {self.drawn("y", "pred + z * se")}, color={c.color}, alpha=0.16, linewidth=0)   # Confidence of Fit')
                w(f'ax.plot({G}, {self.drawn("y", "pred")}, color={c.color}, linewidth={_lw(2)})')
            else:
                w('fit = sm.OLS(yv, X).fit()',
                  f'band = fit.get_prediction(at).summary_frame(alpha={_nm(a)})')
                if e.get('confFit', True):
                    w(f'ax.fill_between({G}, {self.drawn("y", "band[" + chr(34) + "mean_ci_lower" + chr(34) + "]")}, {self.drawn("y", "band[" + chr(34) + "mean_ci_upper" + chr(34) + "]")}, color={c.color}, alpha=0.16, linewidth=0)   # Confidence of Fit')
                if e.get('confPred'):
                    for k_ in ('obs_ci_lower', 'obs_ci_upper'):
                        w(f'ax.plot({G}, {self.drawn("y", "band[" + chr(34) + k_ + chr(34) + "]")}, color={c.color}, linewidth={_lw(1)}, linestyle="--")   # Confidence of Prediction')
                w(f'ax.plot({G}, {self.drawn("y", "band[" + chr(34) + "mean" + chr(34) + "]")}, color={c.color}, linewidth={_lw(2)})')
            if texts:
                w('text = []')
                if 'equation' in texts:
                    w(f'b = fit.params / s ** np.arange({p})   # the coefficients of (x - mean)^j',
                      f'terms = [fmt(b[0] - b[1] * m, 4), ("− " if b[1] < 0 else "+ ") + fmt(abs(b[1]), 4) + "·" + {c.x}]')
                    for j_, sup in ((2, '²'), (3, '³')):
                        if deg >= j_:
                            w(f'terms.append(("− " if b[{j_}] < 0 else "+ ") + fmt(abs(b[{j_}]), 4) + "·(" + {c.x} + " − " + fmt(m, 4) + "){sup}")')
                    w(f'text += [{c.y} + " =", " ".join(terms[:2])] + ([" ".join(terms[2:])] if len(terms) > 2 else [])   # the equation as JMP writes it')
                if 'r2' in texts:
                    w('text.append(f"R² {fmt(fit.rsquared, 4)}")')
                if 'rmse' in texts:
                    w('text.append(f"RMSE {fmt(fit.scale, 4)}")   # RLM\'s robust estimate of the residuals\' scale' if robust else 'text.append(f"RMSE {fmt(np.sqrt(fit.scale), 4)}")')
                if 'ftest' in texts:
                    w('text.append(f"F {fmt(fit.fvalue, 4)}, p {fmt_p(fit.f_pvalue)}")')
                tc = c.color if (self.group or self.nS > 1) else f'"{TEXT}"'
                w(f'ax.annotate("\\n".join(text), (0.01, 0.99), xycoords="axes fraction", xytext=(0, -13 * {PX} * k), textcoords="offset points", ha="left", va="top", fontsize=7, color={tc},',
                  f'            bbox={{"facecolor": "{SURFACE}", "alpha": 0.7, "edgecolor": "none", "pad": 1}})',
                  'k += len(text)')
        self.close(blocks)

    # ---- Ellipse ----------------------------------------------------------------------------------------------
    def el_ellipse(self, e):
        w = self.w
        cov_ = float(e.get('coverage') or 0.95)
        self.imp('from scipy import stats')
        w(f'# Ellipse: the density ellipse of the bivariate normal with the means and covariance of X and Y, holding {_nm(100 * cov_)}% of it')
        if e.get('correlation'):
            self.need('fmt')
            self.corner_count('kr', 'lower right')
        c, blocks = self.cells(lambda X, Y: [X, Y], INK)
        w(f'xy = g[[{c.x}, {c.y}]].to_numpy(float)')
        f = self.freq
        if f:
            w(f'fv = g[{_j(f)}].to_numpy(float)   # Freq: a row counts fv times')
        with w.block(f'if len(xy) >= 3{" and fv.sum() >= 3" if f else ""}:'):
            if f:
                w('mu = np.average(xy, axis=0, weights=fv)', 'cov = (fv * (xy - mu).T) @ (xy - mu) / (fv.sum() - 1)')
            else:
                w('mu, cov = xy.mean(axis=0), np.cov(xy.T)')
            with w.block('if np.linalg.eigvalsh(cov).min() > 0:   # X and Y neither constant nor on a line'):
                w('t = np.linspace(0, 2 * np.pi, 96)',
                  f'ellipse = mu[:, None] + np.sqrt(stats.chi2.ppf({_nm(cov_)}, 2)) * np.linalg.cholesky(cov) @ np.vstack([np.cos(t), np.sin(t)])')
                ex, ey = self.drawn('x', 'ellipse[0]'), self.drawn('y', 'ellipse[1]')
                if e.get('shaded'):
                    w(f'ax.fill({ex}, {ey}, color={c.color}, alpha=0.14, linewidth=0)   # Shaded')
                w(f'ax.plot({ex}, {ey}, color={c.color}, linewidth={_lw(1.6)})')
                if e.get('meanPoint'):
                    w(f'ax.plot({self.drawn("x", "mu[0]")}, {self.drawn("y", "mu[1]")}, marker="+", markersize={_nm(10 * PX)}, color={c.color}, linestyle="")   # the Mean Point')
                if e.get('correlation'):
                    tc = c.color if (self.group or self.nS > 1) else f'"{TEXT}"'
                    w(f'ax.annotate(f"r {{fmt(cov[0, 1] / np.sqrt(cov[0, 0] * cov[1, 1]), 4)}}", (0.99, 0.01), xycoords="axes fraction", xytext=(0, 13 * {PX} * kr), textcoords="offset points", ha="right", va="bottom", fontsize=7, color={tc})',
                      'kr += 1')
        self.close(blocks)


    # ---- Contour -------------------------------------------------------------------------------------------
    def el_contour(self, e):
        if e.get('violin'):
            return self.el_violins(e)
        w = self.w
        L = max(1, min(20, int(round(float(e.get('levels') or 4)))))
        bw = float(e.get('bw') or 1)
        fill, line = e.get('fill') is not False, e.get('line') is not False
        self.imp('from scipy import stats')
        self.need('mass')
        self.imp('from matplotlib.colors import to_rgba')
        w(f'# Contour: a Gaussian kernel density (scipy\'s gaussian_kde, Scott\'s bandwidth{" times " + _nm(bw) if bw != 1 else ""}); its {L} contours hold 100%{", " + ", ".join(f"{_nm(100 * (L - k) / L, 4)}%" for k in range(1, L)) if L > 1 else ""} of the points')
        many = int(self.P.get('nrows') or 0) > 1500
        if many:
            self.need('binned')
            self.imp('from scipy.interpolate import RegularGridInterpolator')
        c, blocks = self.cells(lambda X, Y: [X, Y], INK)
        self.arrays(c)
        if not self.freq:
            w('fv = np.ones(len(xv))')
        with w.block('if len(xv) >= 3 and len(np.unique(xv)) > 1 and len(np.unique(yv)) > 1:'):
            w(f'kde = stats.gaussian_kde(np.vstack([xv, yv]){", weights=fv" if self.freq else ""})')
            if bw != 1:
                w(f'kde.set_bandwidth(kde.factor * {_nm(bw)})')
            w('C = kde.covariance',
              'gx = np.linspace(xv.min() - 3 * np.sqrt(C[0, 0]), xv.max() + 3 * np.sqrt(C[0, 0]), 64)',
              'gy = np.linspace(yv.min() - 3 * np.sqrt(C[1, 1]), yv.max() + 3 * np.sqrt(C[1, 1]), 64)')
            exact = ['GX, GY = np.meshgrid(gx, gy)',
                     'dens = kde(np.vstack([GX.ravel(), GY.ravel()])).reshape(GX.shape)',
                     'at = kde(np.vstack([xv, yv]))   # the density at each point']
            if many:
                with w.block('if len(xv) <= 1500:'):
                    w(*exact)
                with w.block('else:   # many points: binned, as the page does'):
                    w('dens = binned_kde(xv, yv, fv, C, gx, gy)',
                      'at = RegularGridInterpolator((gy, gx), dens)(np.c_[yv, xv])')
            else:
                w(*exact)
            w('inner = 1 - shares(dens, at, fv)   # rises towards the mode; its contour at k/L holds a share 1 - k/L of the points')
            X, Y = self.drawn('x', 'gx'), self.drawn('y', 'gy')
            if fill:
                w(f'ax.contourf({X}, {Y}, inner, levels=np.arange({L + 1}) / {L}, colors=[to_rgba({c.color}, a) for a in 0.1 + 0.52 * np.arange({L}) / {L}])   # darker where the points are densest')
            if line:
                w(f'ax.contour({X}, {Y}, inner, levels=np.arange({L}) / {L}, colors=[to_rgba({c.color}, {0.9 if fill else 1})], linewidths={_lw(1)})')
        self.close(blocks)

    def pre_contour(self, e):
        """Violins: the widest density of every violin over every panel, for one scale."""
        if not e.get('violin'):
            return
        pre = self.pre
        bw = float(e.get('bw') or 1)
        self.imp('from scipy import stats')
        pre('def violin(v, w=None):',
            f'    """The density of the values v, weights w (scipy\'s gaussian_kde, Scott\'s bandwidth{" times " + _nm(bw) if bw != 1 else ""}), from 3 bandwidths below the smallest to 3 above the largest."""',
            '    kde = stats.gaussian_kde(v, weights=w)')
        if bw != 1:
            pre(f'    kde.set_bandwidth(kde.factor * {_nm(bw)})')
        pre('    h = np.sqrt(kde.covariance[0, 0])',
            '    grid = np.linspace(v.min() - 3 * h, v.max() + 3 * h, 128)',
            '    return grid, kde(grid)', '')
        f = self.freq
        keys = self.all_keys()
        pre('most = 0.0   # the widest density of all the violins: every one is drawn to it')
        for resp, fac in dict.fromkeys(self.resp_fac(_Cell(x, y, None, '0', '0')) for x, y in self.pairs_all()):
            ks = keys + [fac]
            with pre.block(f'for _, s in {self.in_groups("df", [resp] + ks)}.groupby([{", ".join(dict.fromkeys(ks))}]):'):
                with pre.block(f'if len(s) > 1 and np.ptp(s[{resp}]) > 0:'):
                    pre(f'most = max(most, violin(s[{resp}].to_numpy(float){", s[" + _j(f) + "].to_numpy(float)" if f else ""})[1].max())')
        pre('')

    def el_violins(self, e):
        w, R = self.w, self.R
        fill, line = e.get('fill') is not False, e.get('line') is not False
        slots = self.slots
        w('# Contour with a categorical axis: a violin of the density of the response at each level, all to one scale')
        self.imp('from matplotlib.colors import to_rgba')
        c, blocks = self.cells(lambda X, Y: [x for x in self.resp_fac(_Cell(X, Y, None, '0', '0'))], INK, si=slots > 1)
        resp, fac = self.resp_fac(c)
        f = self.freq
        off = '' if slots == 1 else f' + (-0.4 + ({self.slot_expr(c)} + 0.5) * {_nm(0.8 / slots, 12)})'
        with w.block(f'for level, s in g.groupby({self.key(fac)}):'):
            with w.block(f'if len(s) > 1 and np.ptp(s[{resp}]) > 0:'):
                w(f'grid, dens = violin(s[{resp}].to_numpy(float){", s[" + _j(f) + "].to_numpy(float)" if f else ""})',
                  f'across = level{off} + np.r_[dens, -dens[::-1]] * {_nm(0.4 / slots, 12)} / most',
                  'along = np.r_[grid, grid[::-1]]')
                xy = (self.drawn('x', 'along'), 'across') if R['horiz'] else ('across', self.drawn('y', 'along'))
                w(f'ax.fill({xy[0]}, {xy[1]}, facecolor=to_rgba({c.color}, {0.25 if fill else 0}), edgecolor={c.color}, linewidth={_lw(1.2) if line else 0})')
        self.close(blocks)

    # ---- Bean -----------------------------------------------------------------------------------------------
    def pre_bean(self, e):
        pre = self.pre
        bw = float(e.get('bw') or 1)
        cut = bool(e.get('cutoff'))
        self.imp('from scipy import stats')
        bwm = f', bw_method=lambda k: k.scotts_factor() * {_nm(bw)}' if bw != 1 else ''
        pre('def bean(v, w=None):',
            '    """statsmodels\' beanplot violin of the values v (weights w, a Freq that is not a whole number): a Gaussian kernel density',
            f'    (Scott\'s rule{" times " + _nm(bw) if bw != 1 else ""}) at 100 points {"from the smallest value to the largest" if cut else "from 1.5 standard deviations below the smallest value to 1.5 above the largest"}, scaled to 1 at its peak."""',
            f'    kde = stats.gaussian_kde(v{bwm}, weights=w)')
        if cut:
            pre('    s = 0.0   # cut at the data')
        else:
            pre('    s = 1.5 * (v.std() if w is None else np.sqrt(np.average((v - np.average(v, weights=w)) ** 2, weights=w)))')
        pre('    grid = np.linspace(v.min() - s, v.max() + s, 100)',
            '    d = kde(grid)',
            '    return grid, d / d.max()', '')

    def el_bean(self, e):
        w, R = self.w, self.R
        f = self.freq
        split = bool(e.get('split'))
        slots = 1 if split else self.slots
        px = float(e.get('px_unit') or 60)
        beans = e.get('beans') or 'lines'
        med = '#b0302a'
        horiz = R['horiz']
        w(f'# Bean: statsmodels\' beanplot at each level: its violin, {"a line for each row" if beans == "lines" else "a dot for each row" if beans == "jitter" else "no rows"}, the mean (the long line) and the median (the cross){"; the first group on the left of each bean, the second on the right" if split else ""}')
        self.imp('from matplotlib.colors import to_rgba')
        if beans == 'jitter':
            self.need('hash01')

        def before(X, Y):
            if e.get('overall') is not False:
                resp, fac = self.resp_fac(_Cell(X, Y, None, '0', '0'))
                q = self.in_groups(self.pf, (resp, fac))
                w(f'q = {q}',
                  f'overall = np.average(q[{resp}], weights=q[{_j(f)}]) if len(q) else np.nan   # the panel\'s mean' if f else f'overall = q[{resp}].mean()   # the panel\'s mean')
                col = f'{_py(PALETTE)}[si % {len(PALETTE)}]' if self.nS > 1 else f'"{MUTED}"'
                line = 'axvline' if R['horiz'] else 'axhline'
                w(f'ax.{line}({self.drawn("x" if R["horiz"] else "y", "overall")}, color={col}, linewidth={_lw(1.3)}, linestyle=":", zorder=0)   # the Overall Mean, dotted across the panel as in Kampstra\'s bean plot')
        c, blocks = self.cells(lambda X, Y: [x for x in self.resp_fac(_Cell(X, Y, None, '0', '0'))], INK, before=before, si=slots > 1, gi=split or slots > 1)
        resp, fac = self.resp_fac(c)
        off = '' if (split or slots == 1) else f' + (-0.4 + ({self.slot_expr(c)} + 0.5) * {_nm(0.8 / slots, 12)})'
        half = _nm(0.4 / slots, 12)
        blen = min(max(round((0.25 if split else 0.5 / slots) * px), 4), 90) / px / 2
        with w.block(f'for level, s in g.groupby({self.key(fac)}):'):
            w(f'pos = level{off}' if off else 'pos = level')
            w(f'v, rows = s[{resp}].to_numpy(float), s.index')
            if f and self.whole:
                w(f'v = np.repeat(v, s[{_j(f)}].round().astype(int))   # Freq: a row counts that many times',
                  'mean, median = v.mean(), np.median(v)')
                wt = ''
            elif f:
                self.imp('from statsmodels.stats.weightstats import DescrStatsW')
                w(f'fw = s[{_j(f)}].to_numpy(float)',
                  'mean = np.average(v, weights=fw)',
                  'median = DescrStatsW(v, weights=fw).quantile([0.5], return_pandas=False)[0] if len(v) > 1 and np.ptp(v) > 0 else np.median(v)')
                wt = ', fw'
            else:
                w('mean, median = v.mean(), np.median(v)')
                wt = ''
            raw = f's[{resp}].to_numpy(float)'
            with w.block('if len(v) > 1 and np.ptp(v) > 0:'):
                w(f'grid, d = bean(v{wt})')
                if split:
                    w(f'across = np.r_[pos + (1 if gi else -1) * d * {half}, pos, pos]', 'along = np.r_[grid, grid[-1], grid[0]]')
                else:
                    w(f'across = pos + np.r_[d, -d[::-1]] * {half}', 'along = np.r_[grid, grid[::-1]]')
                xy = (self.drawn('x', 'along'), 'across') if horiz else ('across', self.drawn('y', 'along'))
                w(f'ax.fill({xy[0]}, {xy[1]}, facecolor=to_rgba({c.color}, 0.2), edgecolor={c.color}, linewidth={_lw(1.1)})')
                if beans == 'jitter':
                    u = 'hash01(rows, 23)'
                    spread = f'(1 if gi else -1) * {u}' if split else f'(2 * {u} - 1)'
                    w(f'dots = pos + {spread} * np.interp({raw}, grid, d) * {half}   # a dot for each row, spread across the violin\'s width')
                    xy = (self.drawn('x', raw), 'dots') if horiz else ('dots', self.drawn('y', raw))
                    w(f'ax.scatter({xy[0]}, {xy[1]}, s={_area(4.5)}, color={c.color}, alpha=0.85, linewidths=0)')
            center = 'pos + (1 if gi else -1) * 0.125' if split else 'pos'
            if beans == 'lines':
                seg = f'{center} - {_nm(blen, 17)}, {center} + {_nm(blen, 17)}'
                if horiz:
                    w(f'ax.vlines({self.drawn("x", raw)}, {seg}, color=to_rgba({c.color}, 0.8), linewidth={_lw(1.1)})   # a line for each row')
                else:
                    w(f'ax.hlines({self.drawn("y", raw)}, {seg}, color=to_rgba({c.color}, 0.8), linewidth={_lw(1.1)})   # a line for each row')
            if e.get('mean') is not False:
                ends = 'pos, pos + (1 if gi else -1) * 0.5' if split else f'pos - {_nm(0.25 / slots, 12)}, pos + {_nm(0.25 / slots, 12)}'
                if horiz:
                    w(f'ax.plot({self.drawn("x", "[mean, mean]")}, [{ends}], color="{TEXT}", linewidth={_lw(2.6)})   # the mean')
                else:
                    w(f'ax.plot([{ends}], {self.drawn("y", "[mean, mean]")}, color="{TEXT}", linewidth={_lw(2.6)})   # the mean')
            if e.get('median') is not False:
                at = 'pos + (1 if gi else -1) * 0.08' if split else 'pos'
                xy = (self.drawn('x', 'median'), at) if horiz else (at, self.drawn('y', 'median'))
                w(f'ax.plot({xy[0]}, {xy[1]}, marker="+", markersize={_nm(11 * PX)}, markeredgewidth={_lw(2)}, color="{med}", linestyle="")   # the median')
        self.close(blocks)

    # ---- the axes ----------------------------------------------------------------------------------------------
    def all_keys(self):
        """The Python of the columns that make the cells: the panels' and the groups'."""
        keys = []
        for zone in ('wrap', 'gx', 'gy'):
            spec = self.P.get(zone)
            if spec:
                keys.append(_j(spec['col'] + ' (bins)' if spec.get('bins') else spec['col']))
        if self.group:
            keys.append(_j(self.group['col'] + ' (bins)' if self.group.get('bins') else self.group['col']))
        return keys

    def pairs_all(self):
        """Every series' columns, over every kind of panel."""
        out = []
        for row in self.series:
            for pairs in row:
                for x, y in pairs:
                    out.append((_j(x) if x else None, _j(y) if y else None))
        return list(dict.fromkeys(out))

    def tick_labels(self, col):
        """The Python of a categorical axis column's tick labels: its levels, or the page's labels of them."""
        spec = self.levels.get(json.loads(col), {}) if col and col.startswith('"') else None
        if spec is None:   # a column of the loop: the labels by name
            if any(v.get('labels') != [_js_number(x) if isinstance(x, (int, float)) else str(x) for x in v.get('values', [])] for v in self.levels.values()):
                if 'ticks' not in self.helpers_consts:
                    pairs = ', '.join(f'{_j(c)}: {_py(v.get("labels"))}' for c, v in self.levels.items())
                    self.pre(f'ticks = {{{pairs}}}   # the levels\' labels, as the page shows them')
                    self.helpers_consts.add('ticks')
                return f'ticks[{col}]'
            return f'levels[{col}]'
        labels = spec.get('labels') or []
        plain = [_js_number(x) if isinstance(x, (int, float)) else str(x) for x in spec.get('values', [])]
        if labels == plain:
            return f'levels[{col}]'
        if json.loads(col) in (self.P.get('order') or {}):   # sorted by Order By: each level's own label
            return f'[{_py(dict(zip([str(v) for v in spec.get("values", [])], labels)))}[str(v)] for v in levels[{col}]]'
        return _py(labels)

    def axes_of_panel(self):
        w = self.w
        if self.geo:
            return self.geo_axes()
        excl = self.P.get('exclusive')
        if excl == 'pie':
            w('ax.axis("off")')
            return
        if excl == 'mosaic':
            return
        X, Y = self.pairs[0] if self.pairs else (None, None)
        for axis, col in (('x', X), ('y', Y)):
            k = self.kind[axis]
            if k == 'cat' and col:
                n = f'len(levels[{col}])'
                w(f'ax.set_{axis}ticks(range({n}), {self.tick_labels(col)})')
                w(f'ax.set_xlim(-0.5, {n} - 0.5)' if axis == 'x' else f'ax.set_ylim({n} - 0.5, -0.5)   # the first level at the top')
            elif k == 'none':
                w(f'ax.set_{axis}ticks([])', f'ax.set_{axis}lim(-0.5, 0.5)   # no column on {axis.upper()}')
            elif k == 'count':
                w('ax.set_xlim(left=0)' if axis == 'x' else 'ax.set_ylim(bottom=0)')
            elif self.log[axis]:
                w(f'ax.set_{axis}scale("log")')

    def axis_settings(self):
        """The axes as set on the graph (Axis Settings), on every panel, once
        they are all drawn: the settings of each panel's X and Y columns."""
        w, P = self.w, self.P
        A = P.get('axes') or {}
        if P.get('exclusive') or not (any(A.get('x') or []) or any(A.get('y') or [])):
            return
        NX, NY = len(P.get('xsets') or [[]]), len(P.get('ysets') or [[]])
        per = {}
        for a, n in (('x', NX), ('y', NY)):
            sets = list(A.get(a) or [])[:n] + [None] * max(0, n - len(A.get(a) or []))
            kinds = []
            for s in sets:
                eff_log = s.get('log') if s and s.get('log') is not None else self.log[a]
                lines, ticks = axis_settings_lines(s, a, 'ax', log=bool(eff_log) and not self.date[a], date=self.date[a])
                if ticks:
                    self.need('ticks')
                kinds.append(lines)
            per[a] = kinds
        w('', '# Axis Settings: the axes as set on the graph (double-click an axis there, or right-click it)')
        same = {a: all(k == per[a][0] for k in per[a]) for a in per}
        if self.single:
            for a in ('x', 'y'):
                w(*per[a][0])
            return
        indexed = not same['x'] or not same['y']
        with w.block('for k, ax in enumerate(axes.flat):' if indexed else 'for ax in axes.flat:   # every panel'):
            for a, var, n in (('x', 'j', NX), ('y', 'i', NY)):
                if same[a]:
                    w(*per[a][0])
                    continue
                w(f'{var} = k % {self.nC} % {NX}   # the panel\'s X column' if a == 'x' else f'{var} = k // {self.nC} % {NY}   # the panel\'s Y column')
                first = True
                for q, lines in enumerate(per[a]):
                    if not lines:
                        continue
                    with w.block(f'{"if" if first else "elif"} {var} == {q}:'):
                        w(*lines)
                    first = False

    def finish(self):
        w, P = self.w, self.P
        excl = P.get('exclusive')
        T = P.get('titles') or {}
        self.axis_settings()
        tx, ty = T.get('x') or [], T.get('y') or []
        NX, NY = len(P.get('xsets') or [[]]), len(P.get('ysets') or [[]])
        wrap = P.get('wrap')
        if excl != 'pie':
            if self.single:
                if tx and tx[0]:
                    w(f'ax.set_xlabel({_j(tx[0])})')
                if ty and ty[0]:
                    w(f'ax.set_ylabel({_j(ty[0])})')
            else:
                if T.get('shared_x') and tx and tx[0]:
                    w(f'fig.supxlabel({_j(tx[0])}, fontsize=10)   # one X title under the panels')
                elif tx and any(tx):
                    if wrap:
                        k = len(wrap['values'])
                        bottom = [i for i in range(k) if i + self.nC >= k]
                        with w.block(f'for i in {_py(bottom)}:   # the panels with none below them'):
                            w(f'axes.flat[i].set_xlabel({_j(tx[0])})')
                    else:
                        labs = [tx[c % NX] for c in range(self.nC)]
                        if len(set(labs)) == 1:
                            with w.block('for ax in axes[-1]:'):
                                w(f'ax.set_xlabel({_j(labs[0])})')
                        else:
                            with w.block(f'for ax, title in zip(axes[-1], {_py(labs)}):'):
                                w('ax.set_xlabel(title)')
                if ty and any(ty):
                    labs = [ty[r % NY] for r in range(self.nR)]
                    if len(set(labs)) == 1:
                        with w.block('for ax in axes[:, 0]:'):
                            w(f'ax.set_ylabel({_j(labs[0])})')
                    else:
                        with w.block(f'for ax, title in zip(axes[:, 0], {_py(labs)}):'):
                            w('ax.set_ylabel(title)')
        where = 'ax' if self.single else 'axes'
        if any(e['type'] == 'heatmap' for e in self.els):
            cc = next(e.get('cc') for e in self.els if e['type'] == 'heatmap')
            w('cells = np.concatenate([np.ma.filled(m.get_array(), np.nan).ravel() for m in meshes])   # every panel\'s cells',
              'lo, hi = np.nanmin(cells), np.nanmax(cells)')
            with w.block('for m in meshes:'):
                w('m.set_clim(lo, hi)   # one colour scale for every panel')
            w(f'fig.colorbar(meshes[0], ax={where}, label={_j(f"Mean({cc})" if cc else "Count")})')
        for e in self.els:
            if e['type'] == 'map' and e.get('stat') != 'level' and (self.geo or {}).get('shape'):
                lo, hi = e.get('range') or [0, 1]
                cont = bool(P.get('color') and not P['color'].get('cat'))
                w(f'fig.colorbar(plt.cm.ScalarMappable(norm=plt.Normalize({_nm(lo, 12)}, {_nm(hi, 12)}), cmap={"ramp" if cont else "counts_map"}), ax={where}, label={_j(e.get("label") or "N")})')
        C = P.get('color')
        if P.get('colorbar') and C and not C.get('cat') and C.get('range'):
            lo, hi = C['range']
            w(f'fig.colorbar(plt.cm.ScalarMappable(norm=plt.Normalize({_nm(lo, 12)}, {_nm(hi, 12)}), cmap=ramp), ax={where}, label={_j(C["col"])})')
        self.legend()
        title = P.get('title')
        if title and self.single:
            chi = any(e['type'] == 'mosaic' and e.get('chisq') for e in self.els)
            w(f'fig.suptitle({_j(title)})' if chi else f'ax.set_title({_j(title)})')

    def legend(self):
        w, P = self.w, self.P
        L = P.get('legend') or {}
        if not L.get('on'):
            return
        excl = P.get('exclusive')
        title = L.get('title')
        if excl == 'pie':
            X, Y = self.series[0][0][0]
            fac = Y if self.R['fac'] == 'y' else X
            spec = self.levels.get(fac, {}) if fac else {}
            labels = spec.get('labels') or []
            colors = [PALETTE[i % len(PALETTE)] for i in range(len(labels))]
            kind = 'patch'
        elif excl == 'mosaic':
            spec = self.levels.get(self.series[0][0][0][1], {})
            labels = spec.get('labels') or []
            colors = [PALETTE[i % len(PALETTE)] for i in range(len(labels))]
            kind = 'patch'
        elif self.group:
            labels = self.group['labels']
            colors = [PALETTE[i % len(PALETTE)] for i in range(len(labels))]
            kind = next((self.SAMPLE[e['type']] for e in self.els if e['type'] in self.SAMPLE), 'marker')
        else:
            labels = P.get('series_names') or []
            colors = [PALETTE[i % len(PALETTE)] for i in range(len(labels))]
            kind = next((self.SAMPLE[e['type']] for e in self.els if e['type'] in self.SAMPLE), 'marker')
        if not labels:
            return
        if kind == 'patch':
            self.imp('from matplotlib.patches import Patch')
            handles = f'[Patch(color=c) for c in {_py(colors)}]'
        elif kind == 'line':
            handles = f'[plt.Line2D([], [], color=c, linewidth={_lw(2)}) for c in {_py(colors)}]'
        else:
            handles = f'[plt.Line2D([], [], color=c, marker="o", linestyle="", markersize={_nm(6 * PX)}) for c in {_py(colors)}]'
        pos = L.get('pos') or 'right'
        tt = f', title={_j(title)}' if title else ''
        if pos == 'inside':
            host = 'ax' if self.single else 'fig'
            w(f'{host}.legend({handles}, {_py(labels)}{tt}, loc="upper right", fontsize=8)')
        elif pos == 'bottom':
            w(f'fig.legend({handles}, {_py(labels)}{tt}, loc="outside lower center", ncols={min(6, len(labels))}, frameon=False, fontsize=8)')
        else:
            w(f'fig.legend({handles}, {_py(labels)}{tt}, loc="outside right upper", frameon=False, fontsize=8)')


_STAT_LABEL = [('n', 'N'), ('mean', 'Mean'), ('median', 'Median'), ('sum', 'Sum'), ('min', 'Min'), ('max', 'Max'), ('range', 'Range'), ('sd', 'Std Dev'),
               ('se', 'Std Err'), ('var', 'Variance'), ('pct', '% of Total'), ('q1', 'First Quartile'), ('q3', 'Third Quartile')]
_INTERVAL_LABEL = {'range': 'range', 'se': 'standard error either side', 'sd': 'standard deviation either side', 'ci': 't confidence interval', 'iqr': 'interquartile range'}




# ---- the other graphs of the Graph menu ----------------------------------------------------
def _head_lines(table, plan, rows, table_name, imports):
    """The head and the report's rows (a By group's, without the rows it leaves out)."""
    extra = sorted(dict.fromkeys(imports), key=lambda s: (not s.startswith('import'), s))
    return [code_head(table_name, ['import matplotlib.pyplot as plt'] + extra)] + _keep_lines(table, rows, plan.get('where'))


def _marker(plan, size, alpha):
    """A point plot's Marker Size (a diameter in pixels) and Transparency (an
    opacity) as set on the graph (the plan's marker), else the graph's own
    size and alpha; and whether each was set."""
    M = plan.get('marker') or {}
    ms = M.get('size') if isinstance(M.get('size'), (int, float)) and M['size'] > 0 else None
    ma = M.get('alpha') if isinstance(M.get('alpha'), (int, float)) and 0 <= M['alpha'] <= 1 else None
    return (float(ms) if ms else size), (float(ma) if ma is not None else alpha), ms is not None, ma is not None


def _group_consts(G, what='Grouping'):
    """The Python of a grouping column's levels and their colours (the page's palette)."""
    return [f'groups = {_py(G["values"])}   # {what}: the levels of {G["col"]}, in the table\'s order',
            f'colors = {_py([PALETTE[i % len(PALETTE)] for i in range(len(G["values"]))])}   # a colour for each: the page\'s palette']


def _overlay_code(table, plan, rows, table_name):
    """The legacy Overlay Plot: Y columns against one X (or the row number),
    points and lines, on a left and a right axis, or each on an axis of its
    own, stacked."""
    P = plan
    ys = P.get('ys') or []
    X, G = P.get('x'), P.get('group')
    over, sort, thru = P.get('overlayY', True), P.get('sortX', True), P.get('thru', False)
    W, H = P.get('size') or [640, 380]
    w = _Py()
    imports = []
    if G:
        w(*_group_consts(G))
    if X:
        order = f'.sort_values({_j(X)}, kind="stable")' if sort else ''
        w(f'd = df[df[{_j(X)}].notna()]{order}   # the rows with an X{", in the order of X (Sort X)" if sort else ", in the table" + chr(39) + "s order"}')
        xs = f'g[{_j(X)}]'
    else:
        w('d = df   # X: the row number')
        xs = 'g.index + 1'
    w('')
    right = over and any(y.get('right') for y in ys)
    if over:
        w(f'fig, ax = plt.subplots(figsize=({_inch(W)}, {_inch(H)}), layout="constrained")')
        if right:
            w('ax2 = ax.twinx()   # the right axis (Y Options > Right Scale)')
    else:
        w(f'fig, axes = plt.subplots({len(ys)}, 1, figsize=({_inch(W)}, {_inch(H)}), sharex=True, squeeze=False, layout="constrained")   # a Y on each axis (Overlay Y\'s off)')
    for i, y in enumerate(ys):
        col = y['col']
        on = ('ax2' if y.get('right') else 'ax') if over else f'axes[{i}, 0]'
        marks, line = y.get('points', True), y.get('connect', True)
        if not marks and not line:
            marks = True
        msize, malpha, _, alpha_set = _marker(P, 5, 1)
        style = [f'marker="o", markersize={_nm(msize * PX)}' if marks else 'marker=""', f'linestyle="{"-" if line else ""}"', f'linewidth={_lw(1.5)}']
        # Transparency: the markers only (their face colour takes it), the line stays opaque
        face = (lambda c_: f', markerfacecolor=to_rgba({c_}, {_nm(malpha)}), markeredgewidth=0') if marks and alpha_set else (lambda c_: '')
        if marks and alpha_set:
            imports.append('from matplotlib.colors import to_rgba')
        if y.get('step'):
            style.append('drawstyle="steps-post"')
        w(f'# {col}{", on the right axis" if y.get("right") and over else ""}{", connected through missing values" if thru else ""}')
        pick = f'd.dropna(subset=[{_j(col)}])' if thru else 'd'
        if G:
            with w.block('for group, color in zip(groups, colors):'):
                w(f'g = {pick}[{pick}[{_j(G["col"])}] == group]' if not thru else f'g = {pick}',
                  *( [f'g = g[g[{_j(G["col"])}] == group]'] if thru else []),
                  f'{on}.plot({xs}, g[{_j(col)}], {", ".join(style)}, color=color{face("color")}, label={_j(col + ", ")} + str(group))')
                if y.get('needle'):
                    w(f'{on}.vlines({xs}, 0, g[{_j(col)}], color=color, alpha=0.6, linewidth={_lw(1)})   # Needle')
        else:
            color = _j(PALETTE[i % len(PALETTE)])
            w(f'g = {pick}', f'{on}.plot({xs}, g[{_j(col)}], {", ".join(style)}, color={color}{face(color)}, label={_j(col)})')
            if y.get('needle'):
                w(f'{on}.vlines({xs}, 0, g[{_j(col)}], color={color}, alpha=0.6, linewidth={_lw(1)})   # Needle')
    xt = X or 'Row'
    if over:
        w(f'ax.set_xlabel({_j(xt)})', f'ax.set_ylabel({_j(", ".join(y["col"] for y in ys if not (y.get("right"))))})')
        if right:
            w(f'ax2.set_ylabel({_j(", ".join(y["col"] for y in ys if y.get("right")))})')
        if len(ys) > 1 or G:
            both = '[a + b for a, b in zip(ax.get_legend_handles_labels(), ax2.get_legend_handles_labels())]' if right else 'ax.get_legend_handles_labels()'
            w(f'fig.legend(*{both}, loc="outside right upper", frameon=False, fontsize=8)')
    else:
        for i, y in enumerate(ys):
            w(f'axes[{i}, 0].set_ylabel({_j(y["col"])})')
        w(f'axes[-1, 0].set_xlabel({_j(xt)})')
        if len(ys) > 1 or G:
            w('handles, labels = [sum(q, []) for q in zip(*[a.get_legend_handles_labels() for a in axes[:, 0]])]',
              'fig.legend(handles, labels, loc="outside right upper", frameon=False, fontsize=8)')
    return '\n'.join(_head_lines(table, plan, rows, table_name, imports) + w.lines + ['plt.show()'])



def _matrix_code(table, plan, rows, table_name):
    """Scatterplot Matrix: a scatterplot of every pair of columns (Y by X, or
    each pair once in a triangle, or twice), with the fit lines, density
    ellipses and density contours of each group, and histograms on the
    diagonal."""
    P = plan
    R_, C_ = P.get('rows') or [], P.get('cols') or []
    rect = bool(P.get('rect'))
    fm = 'square' if rect else (P.get('format') or 'lower')
    G = P.get('group')
    W, H = P.get('size') or [600, 600]
    k, m = len(R_), len(C_)
    imports = []
    w = _Py()
    if G:
        w(*_group_consts(G, 'Group'))
        w('color_of = dict(zip(groups, colors))')
    bins = P.get('bins') or {}
    if P.get('hist') and bins:
        w(f'bins = {{{", ".join(f"{_j(c)}: ({_nm(b["start"], 15)}, {_nm(b["size"], 15)}, {int(b["nb"])})" for c, b in bins.items())}}}   # each column\'s histogram: the page\'s bins (start, width, count)')
    if P.get('ellipses') or P.get('nonpar'):
        imports.append('from scipy import stats')
    if P.get('ellipses') or P.get('fit') or P.get('nonpar'):
        imports.append('from matplotlib.colors import to_rgba')
    w('', f'fig, axes = plt.subplots({k}, {m}, figsize=({_inch(W)}, {_inch(H)}), sharex="col", squeeze=False, layout="constrained")',
      f'rows_, cols = {_py(R_)}, {_py(C_)}   # the matrix: {"the Y columns (down) by the X columns (across)" if rect else "every pair of the columns"}')
    with w.block('for i, y in enumerate(rows_):'):
        with w.block('for j, x in enumerate(cols):'):
            w('ax = axes[i, j]')
            if not rect and fm != 'square':
                with w.block(f'if j {">" if fm == "lower" else "<"} i:   # {fm.capitalize()} Triangular: each pair once'):
                    w('ax.set_visible(False)', 'continue')
            if not rect:
                with w.block('if i == j:   # the diagonal: the column\'s name' + (' and its histogram' if P.get('hist') else '')):
                    if P.get('hist'):
                        w('start, size, nb = bins[x]',
                          'v = df[x].dropna()',
                          'counts = np.bincount(np.clip(np.floor((v - start) / size + 1e-9), 0, nb - 1).astype(int), minlength=nb)',
                          f'ax.bar(start + (np.arange(nb) + 0.5) * size, counts, width=size, color="{BAR}", edgecolor="{SURFACE}", linewidth={_lw(0.4)})',
                          'ax.text(0.5, 0.97, x, transform=ax.transAxes, ha="center", va="top", fontweight="bold", fontsize=8)',
                          'ax.set_yticks([])')
                    else:
                        w('ax.text(0.5, 0.5, x, transform=ax.transAxes, ha="center", va="center", fontweight="bold", fontsize=8)',
                          'ax.set_yticks([])')
                    w('continue')
            w('g = df.dropna(subset=[x, y])')
            if P.get('points', True):
                color = f'g[{_j(G["col"])}].map(color_of).fillna("{MISSING}")' if G else f'"{POINT}"'
                msize, malpha, size_set, alpha_set = _marker(P, None, 0.85)
                size = _area(msize) if size_set else f'({PX} * (3 if len(g) > 1500 else 4.5)) ** 2'
                w(f'ax.scatter(g[x], g[y], s={size}, color={color}, alpha={_nm(malpha)}, linewidths=0){"   # Marker Size, Transparency" if size_set or alpha_set else ""}')
            stats_ = [t for t in ('ellipses', 'fit', 'nonpar') if P.get(t)]
            if stats_:
                if G:
                    b = w.block('for group, color in zip(groups, colors):   # each group its own')
                    b.__enter__()
                    w(f's = g[g[{_j(G["col"])}] == group]')
                else:
                    b = None
                    w('s, color = g, "' + INK + '"')
                w('xv, yv = s[x].to_numpy(float), s[y].to_numpy(float)')
                if P.get('ellipses'):
                    cov = float(P.get('coverage') or 0.95)
                    with w.block('if len(xv) >= 3:'):
                        w('mu, cov = np.mean([xv, yv], axis=1), np.cov(xv, yv)')
                        with w.block('if np.linalg.eigvalsh(cov).min() > 0:'):
                            w('t = np.linspace(0, 2 * np.pi, 96)',
                              f'e = mu[:, None] + np.sqrt(stats.chi2.ppf({_nm(cov)}, 2)) * np.linalg.cholesky(cov) @ np.vstack([np.cos(t), np.sin(t)])   # the density ellipse, {_nm(100 * cov)}%')
                            if P.get('shaded'):
                                w('ax.fill(e[0], e[1], color=to_rgba(color, 0.12), linewidth=0)')
                            w(f'ax.plot(e[0], e[1], color=color, linewidth={_lw(1.3)})')
                if P.get('fit'):
                    with w.block('if len(np.unique(xv)) >= 2 and len(xv) > 2:'):
                        w('mx, sx = xv.mean(), xv.std(ddof=1) or 1.0',
                          'fit = sm.OLS(yv, np.vander((xv - mx) / sx, 2, increasing=True)).fit()   # the least squares line',
                          'gx = np.linspace(xv.min(), xv.max(), 40)',
                          'band = fit.get_prediction(np.vander((gx - mx) / sx, 2, increasing=True)).summary_frame(alpha=0.05)',
                          'ax.fill_between(gx, band["mean_ci_lower"], band["mean_ci_upper"], color=to_rgba(color, 0.14), linewidth=0)   # its 95% band',
                          f'ax.plot(gx, band["mean"], color=color, linewidth={_lw(1.6)})')
                if P.get('nonpar'):
                    many = int(P.get('nrows') or 0) > 1500
                    with w.block('if len(xv) >= 3 and len(np.unique(xv)) > 1 and len(np.unique(yv)) > 1:'):
                        w('kde = stats.gaussian_kde(np.vstack([xv, yv]))   # Scott\'s bandwidth',
                          'C = kde.covariance',
                          'gx = np.linspace(xv.min() - 3 * np.sqrt(C[0, 0]), xv.max() + 3 * np.sqrt(C[0, 0]), 48)',
                          'gy = np.linspace(yv.min() - 3 * np.sqrt(C[1, 1]), yv.max() + 3 * np.sqrt(C[1, 1]), 48)')
                        exact = ['GX, GY = np.meshgrid(gx, gy)', 'dens = kde(np.vstack([GX.ravel(), GY.ravel()])).reshape(GX.shape)', 'at = kde(np.vstack([xv, yv]))']
                        if many:
                            with w.block('if len(xv) <= 1500:'):
                                w(*exact)
                            with w.block('else:   # many points: binned, as the page does'):
                                w('dens = binned_kde(xv, yv, np.ones(len(xv)), C, gx, gy)', 'at = RegularGridInterpolator((gy, gx), dens)(np.c_[yv, xv])')
                            imports.append('from scipy.interpolate import RegularGridInterpolator')
                        else:
                            w(*exact)
                        w('inner = 1 - shares(dens, at, np.ones(len(xv)))',
                          f'ax.contour(gx, gy, inner, levels=[0, 0.25, 0.5, 0.75], colors=[color], linewidths={_lw(1)})   # holding 100, 75, 50 and 25% of the points')
                if b:
                    b.__exit__(None, None, None)
    # which cells are scatterplots: the Y of a row shared by them, the titles on the outer ones (as the page places them)
    plain = [[(rect or (i != j and not ((fm == 'lower' and j > i) or (fm == 'upper' and j < i)))) for j in range(m)] for i in range(k)]
    share = [[j for j in range(m) if plain[i][j]] for i in range(k)]
    if any(len(js) > 1 for js in share):
        with w.block(f'for i, js in enumerate({_py(share)}):   # a row\'s scatterplots share their Y'):
            with w.block('for j in js[1:]:'):
                w('axes[i, j].sharey(axes[i, js[0]])')
    for j in range(m):
        at = k - 1 if plain[k - 1][j] else (0 if plain[0][j] else None)
        if at is not None:
            w(f'axes[{at}, {j}].set_xlabel({_j(C_[j])})')
    for i in range(k):
        at = 0 if plain[i][0] else (m - 1 if plain[i][m - 1] else None)
        if at is not None:
            w(f'axes[{i}, {at}].set_ylabel({_j(R_[i])})')
    if G:
        w(f'fig.legend([plt.Line2D([], [], marker="o", linestyle="", color=c) for c in colors], {_py(G["labels"])}, title={_j(G["col"])}, loc="outside right upper", frameon=False, fontsize=8)')
    helpers = []
    if P.get('nonpar'):
        helpers += _HELPERS['mass'] + ['']
        if int(P.get('nrows') or 0) > 1500:
            helpers += _HELPERS['binned'] + ['']
            imports.append('from scipy.signal import fftconvolve')
    head = _head_lines(table, plan, rows, table_name, imports)
    return '\n'.join(head + ([''] + helpers if helpers else []) + w.lines + ['plt.show()'])



def _bubble_code(table, plan, rows, table_name):
    """Bubble Plot: a bubble for the rows of each ID (or each row) at their
    mean X and Y (Freq-weighted), its area the sum of Sizes (or the count of
    rows), its colour from Coloring; with Time, the bubbles at the first
    time, as the page shows them before Play."""
    P = plan
    X, Y, ids, T = P['x'], P['y'], P.get('ids') or [], P.get('time')
    Z, F, C = P.get('sizes'), P.get('freq'), P.get('color')
    W, H = P.get('size') or [640, 420]
    imports = []
    w = _Py()
    need = [X, Y] + ids + ([T] if T else [])
    w(f'd = df.dropna(subset={_py(need)})' + (f'\nd = d[d[{_j(F)}] > 0]   # Freq: rows with a positive count' if F else ''))
    w('d = d.assign(_w=' + (f'd[{_j(F)}]' if F else '1.0') + ')   # each row\'s weight' + (' (Freq)' if F else ''))
    if Z:
        w(f'd["_s"] = d[{_j(Z)}].fillna(0.0)   # Sizes: a bubble\'s area is the sum of these (a missing value adds nothing)')
    else:
        w('d["_s"] = d["_w"]   # a bubble\'s area is its count of rows' + (' (the sum of Freq)' if F else ''))
    if ids:
        w(f'keys = {_py(([T] if T else []) + ids)}   # {"a bubble for each ID at each time" if T else "a bubble for each ID"}')
    else:
        w('d["_row"] = d.index', f'keys = {_py([T] if T else [])} + ["_row"]   # every row is a bubble')
    w('d["_wx"], d["_wy"] = d["_w"] * d[' + _j(X) + '], d["_w"] * d[' + _j(Y) + ']',
      'sums = d.groupby(keys, sort=False)[["_w", "_wx", "_wy", "_s"]].sum()',
      'bubbles = pd.DataFrame({"x": sums["_wx"] / sums["_w"], "y": sums["_wy"] / sums["_w"], "size": sums["_s"].clip(lower=0)})')
    if C and C.get('cat'):
        w(f'levels = {_py(C["values"])}   # Coloring: the levels of {C["col"]}',
          f'palette = {_py(PALETTE)}',
          f'tally = d.dropna(subset=[{_j(C["col"])}]).assign(_lv=lambda q: q[{_j(C["col"])}].map({{v: k for k, v in enumerate(levels)}}))',
          'most = tally.groupby(keys + ["_lv"], sort=False)["_w"].sum().reset_index().sort_values("_lv", kind="stable")',
          'most = most.loc[most.groupby(keys, sort=False)["_w"].idxmax()].set_index(keys)["_lv"]   # the level most of a bubble\'s rows have (a tie: the first)',
          f'bubbles["color"] = [palette[int(most[k]) % 12] if k in most.index else "{MISSING}" for k in bubbles.index]')
    elif C and C.get('range'):
        lo, hi = C['range']
        imports.append('from matplotlib.colors import LinearSegmentedColormap')
        w(f'ramp = LinearSegmentedColormap.from_list("ramp", {_py(RAMP)})   # the page\'s blue-grey-red',
          f'c = d.dropna(subset=[{_j(C["col"])}]).assign(_wc=lambda q: q["_w"] * q[{_j(C["col"])}]).groupby(keys, sort=False)[["_wc", "_w"]].sum()',
          f'mean_c = (c["_wc"] / c["_w"]).reindex(bubbles.index)   # the mean of {C["col"]} in each bubble')
        if hi > lo:
            w(f'bubbles["color"] = [ramp((m - {_nm(lo, 15)}) / {_nm(hi - lo, 15)}) if np.isfinite(m) else "{POINT}" for m in mean_c]')
        else:
            w(f'bubbles["color"] = [ramp(0.5) if np.isfinite(m) else "{POINT}" for m in mean_c]')
    else:
        w(f'bubbles["color"] = "{POINT}"')
    max_px = 46 * float(P.get('scale') or 1)
    w('smax = bubbles["size"].max()   # the largest bubble at any time: Plotly\'s area scale (sizeref) is set by it',
      f'radius = np.sqrt(bubbles["size"] / 2 / (2 * smax / {_nm(max_px ** 2, 15)})) if smax > 0 else 0 * bubbles["size"]   # in pixels, as Plotly sizes an area: sqrt(size / 2 / sizeref)',
      'bubbles["px"] = np.where(radius > 0, 2 * np.maximum(radius, 2), 0)   # the diameter: the radius at least 2 pixels (a bubble of size 0 is not drawn)')
    if T and not P.get('allTimes'):
        w(f'first = bubbles.loc[{_py(P.get("time0"))}]   # the first time\'s bubbles ({T} = {P.get("time0_label") or _py(P.get("time0"))}), as the page shows them before Play')
    else:
        w('first = bubbles')
    ex, ey = P.get('xrange'), P.get('yrange')
    w('', f'fig, ax = plt.subplots(figsize=({_inch(W)}, {_inch(H)}), layout="constrained")',
      f'bub = ax.scatter(first["x"], first["y"], s=({PX} * first["px"]) ** 2, c=list(first["color"]), alpha={_nm(_marker(P, 1, 0.72)[1])}, edgecolors="{TEXT}80", linewidths={_lw(0.6)})')
    if P.get('label'):
        lab = P.get('label_col')
        if ids:
            w(f'd["_label"] = d[{_py(ids)}].astype(str).agg(", ".join, axis=1)   # Label: a bubble\'s ID')
        elif lab:
            w(f'd["_label"] = d[{_j(lab)}].astype(str)   # Label: the row\'s label')
        else:
            w('d["_label"] = "row " + (d.index + 1).astype(str)   # Label: the row\'s number')
        w('texts = d.groupby(keys, sort=False)["_label"].first()')
        if T and not P.get('allTimes'):
            w(f'texts = texts.loc[{_py(P.get("time0"))}]')
        with w.block('for x, y, text in zip(first["x"], first["y"], texts.reindex(first.index)):'):
            w('ax.text(x, y, text, ha="center", va="center", fontsize=6.5)')
    if ex:
        w(f'ax.set_xlim({_nm(ex[0], 15)}, {_nm(ex[1], 15)})   # the page\'s range: the rows\' X and 8% each side')
    if ey:
        w(f'ax.set_ylim({_nm(ey[0], 15)}, {_nm(ey[1], 15)})')
    w(f'ax.set_xlabel({_j(X)})', f'ax.set_ylabel({_j(Y)})')
    if C and C.get('cat'):
        w(f'fig.legend([plt.Line2D([], [], marker="o", linestyle="", color=palette[k % 12]) for k in range(len(levels))], {_py(C.get("labels") or [str(v) for v in C["values"]])}, title={_j(C["col"])}, loc="outside right upper", frameon=False, fontsize=8)')
    if T and not P.get('allTimes'):
        w(f'# An animation over {T}, as the page\'s Play: matplotlib.animation.FuncAnimation(fig, step, frames={_py(P.get("times") or [])}),',
          '# where step(t) puts the bubbles of time t: bub.set_offsets(bubbles.loc[t][["x", "y"]]); bub.set_sizes((0.72 * bubbles.loc[t]["px"]) ** 2),',
          '# bub.set_facecolors(bubbles.loc[t]["color"]); and anim.save("bubbles.gif") or, in a notebook, HTML(anim.to_jshtml()).')
    return '\n'.join(_head_lines(table, plan, rows, table_name, imports) + w.lines + ['plt.show()'])



def _parallel_code(table, plan, rows, table_name):
    """Parallel Plot: each row a line across an axis for each column (each on
    its range, on one scale, or standardized), coloured by a grouping."""
    P = plan
    cols = P.get('ys') or []
    k = len(cols)
    G = P.get('group')
    scale, center = P.get('scale') or 'range', bool(P.get('center'))
    rev = [c for c in (P.get('reverse') or []) if c in cols]
    W, H = P.get('size') or [600, 380]
    w = _Py()
    if G:
        w(*_group_consts(G))
    w(f'cols = {_py(cols)}   # an axis for each, from left to right',
      'd = df.dropna(subset=cols)   # the rows with every value')
    if scale == 'std':
        w('U = (d[cols] - d[cols].mean()) / d[cols].std().replace(0, 1)   # Standardize: (value − mean)/std dev')
    elif scale == 'uniform':
        w('U = d[cols] - d[cols].mean()   # Scale Uniformly, Center at Zero: each column\'s mean moved to 0' if center else 'U = d[cols].copy()   # Scale Uniformly: the values themselves')
    else:
        w('lo, hi = d[cols].min(), d[cols].max()',
          'U = ((d[cols] - lo) / (hi - lo)).fillna(0.5)   # each axis from its column\'s minimum (0) to its maximum (1)',
          'U.loc[:, hi == lo] = 0.5')
    if rev:
        w(f'U[{_py(rev)}] = {"1 - U[" + _py(rev) + "]" if scale == "range" else "-U[" + _py(rev) + "]"}   # Reverse Axes')
    n = int(P.get('nrows') or 0)
    alpha = 0.35 if n > 500 else 0.65
    w('', f'fig, ax = plt.subplots(figsize=({_inch(W)}, {_inch(H)}), layout="constrained")')
    style = f'alpha={alpha}, linewidth={_lw(1)}, marker="o", markersize={_nm(3 * PX)}, markerfacecolor=color, markeredgewidth=0'
    if G:
        with w.block('for group, color in zip(groups, colors):'):
            w(f'rows_ = U[d[{_j(G["col"])}] == group]',
              f'ax.plot(range({k}), rows_.to_numpy().T, color=color, {style})   # a line for each row')
    else:
        w(f'color = "{BOX_BLUE}"', f'ax.plot(range({k}), U.to_numpy().T, color=color, {style})   # a line for each row')
    with w.block(f'for j in range({k}):'):
        w(f'ax.axvline(j, color="{MUTED}", linewidth={_lw(1)})   # the axes')
    names = [('↓ ' if c in rev else '') + c for c in cols]
    w(f'ax.set_xticks(range({k}), {_py(names)})', f'ax.set_xlim(-0.25, {k} - 0.75)')
    if scale == 'range':
        w('ax.set_ylim(-0.04, 1.04)', 'ax.set_yticks([])')
        with w.block('for j, c in enumerate(cols):   # each axis\'s range, as the page writes it'):
            w(f'top, bottom = (lo[c], hi[c]) if c in {_py(rev)} else (hi[c], lo[c])   # a reversed axis has its minimum at the top' if rev else 'top, bottom = hi[c], lo[c]',
              'ax.annotate(fmt(top, 4), (j, 1), xycoords=("data", "axes fraction"), ha="center", va="bottom", fontsize=7, color="' + MUTED + '")',
              'ax.annotate(fmt(bottom, 4), (j, 0), xycoords=("data", "axes fraction"), ha="center", va="top", fontsize=7, color="' + MUTED + '")')
        helpers = _HELPERS['fmt'] + ['']
    else:
        w(f'ax.set_ylabel({_j("Standardized value" if scale == "std" else "Value − mean" if center else "Value")})')
        helpers = []
    if G:
        w(f'fig.legend([plt.Line2D([], [], color=c) for c in colors], {_py(G["labels"])}, title={_j(G["col"])}, loc="outside right upper", frameon=False, fontsize=8)')
    head = _head_lines(table, plan, rows, table_name, [])
    return '\n'.join(head + ([''] + helpers if helpers else []) + w.lines + ['plt.show()'])


def _cell_code(table, plan, rows, table_name):
    """Cell Plot: the rows as rows of cells, a column of cells for each
    column: continuous columns standardized (or on one scale) blue to red,
    categorical ones a colour for each level, missing values blank."""
    P = plan
    cols = P.get('ys') or []
    cats = P.get('cats') or {}
    uni, center = bool(P.get('uniform')), bool(P.get('center'))
    W, H = P.get('size') or [500, 400]
    w = _Py()
    w(f'cols = {_py(cols)}',
      f'levels = {{{", ".join(f"{_j(c)}: {_py(v)}" for c, v in cats.items())}}}   # the categorical columns\' levels, in the table\'s order' if cats else None,
      'd = df   # every row, in the table\'s order',
      f'ramp = LinearSegmentedColormap.from_list("ramp", {_py(RAMP)})   # the page\'s blue-grey-red',
      f'palette = {_py(PALETTE)}')
    cont = [c for c in cols if c not in cats]
    if uni and cont:
        if center:
            w(f'a = np.nanmax(np.abs(d[{_py(cont)}].to_numpy(float)))', 'lo, hi = -a, a   # Scale Uniformly, Center at Zero')
        else:
            w(f'lo, hi = np.nanmin(d[{_py(cont)}].to_numpy(float)), np.nanmax(d[{_py(cont)}].to_numpy(float))   # Scale Uniformly: one scale for every continuous column')
    w('Z = np.full((len(d), len(cols)), np.nan)   # the number each cell is coloured by',
      'rgba = np.zeros((len(d), len(cols), 4))   # its colour (a missing value: none)')
    with w.block('for j, c in enumerate(cols):'):
        if cats:
            with w.block('if c in levels:   # a colour for each level'):
                w('Z[:, j] = d[c].map({v: k for k, v in enumerate(levels[c])})',
                  'ok = ~np.isnan(Z[:, j])',
                  'rgba[ok, j] = to_rgba_array([palette[int(k) % 12] for k in Z[ok, j]])')
            b = w.block('else:')
            b.__enter__()
        if uni:
            w('Z[:, j] = d[c]', 'norm = (Z[:, j] - lo) / (hi - lo)')
        else:
            w('sd = d[c].std()', 'sd = sd if sd > 0 else 1.0',
              'Z[:, j] = (d[c] - ' + ('0' if center else 'd[c].mean()') + ') / sd   # in standard deviations' + (' about zero' if center else ''), 'norm = (Z[:, j] + 3) / 6   # from −3 to 3')
        w('ok = ~np.isnan(Z[:, j])', 'rgba[ok, j] = ramp(np.clip(norm[ok], 0, 1))')
        if cats:
            b.__exit__(None, None, None)
    n = int(P.get('nrows') or 0)
    labels = P.get('labels')
    w('', f'fig, ax = plt.subplots(figsize=({_inch(W)}, {_inch(H)}), layout="constrained")',
      'ax.imshow(rgba, aspect="auto", interpolation="nearest")',
      'ax.set_xticks(range(len(cols)), cols)', 'ax.xaxis.tick_top()',
      'ax.set_xticks(np.arange(len(cols) + 1) - 0.5, minor=True)', f'ax.grid(which="minor", axis="x", color="white", linewidth={_lw(1)})')
    if labels is not None:
        w(f'ax.set_yticks(range(len(d)), {_py(labels)})   # the rows\' labels' if len(labels) <= 80 else 'ax.set_yticks([])')
        if n <= 150:
            w('ax.set_yticks(np.arange(len(d) + 1) - 0.5, minor=True)', f'ax.grid(which="minor", axis="y", color="white", linewidth={_lw(1)})')
    else:
        w('ax.set_yticks([])', f'ax.set_ylabel("{n} rows")')
    w('ax.tick_params(which="minor", length=0)')
    if P.get('legend', True) and cont:
        w(f'fig.colorbar(plt.cm.ScalarMappable(norm=plt.Normalize({"lo, hi" if uni else "-3, 3"}), cmap=ramp), ax=ax, label={_j("Value" if uni else "Standardized")}, shrink=0.6)')
    imports = ['from matplotlib.colors import LinearSegmentedColormap, to_rgba_array']
    return '\n'.join(_head_lines(table, plan, rows, table_name, imports) + [x for x in w.lines] + ['plt.show()'])

_TREEMAP_LAYOUT = [
    'def squarify(values, x0, y0, x1, y1):',
    '    """d3\'s squarified treemap (ratio 1, Plotly\'s tiling): the tiles of values within the box, in rows as near to squares as they',
    '    can be, in the order given; each tile as (x0, y0, x1, y1), y down as on the page."""',
    '    out, i0, n, value = [None] * len(values), 0, len(values), float(sum(values))',
    '    while i0 < n:',
    '        dx, dy = x1 - x0, y1 - y0',
    '        i1 = i0',
    '        total = values[i1]',
    '        i1 += 1',
    '        while not total and i1 < n:',
    '            total = values[i1]',
    '            i1 += 1',
    '        lo = hi = total',
    '        alpha = max(dy / dx, dx / dy) / value',
    '        beta = total * total * alpha',
    '        best = max(hi / beta, beta / lo)',
    '        while i1 < n:',
    '            v = values[i1]',
    '            total += v',
    '            lo, hi = min(lo, v), max(hi, v)',
    '            beta = total * total * alpha',
    '            ratio = max(hi / beta, beta / lo)',
    '            if ratio > best:',
    '                total -= v',
    '                break',
    '            best = ratio',
    '            i1 += 1',
    '        row = range(i0, i1)',
    '        if dx < dy:   # a row across the box, at its top',
    '            y = y0 + dy * total / value if value else y1',
    '            k = (x1 - x0) / total if total else 0',
    '            x = x0',
    '            for i in row:',
    '                out[i] = (x, y0, x + values[i] * k, y)',
    '                x += values[i] * k',
    '            y0 = y',
    '        else:   # a column down the box, at its left',
    '            x = x0 + dx * total / value if value else x1',
    '            k = (y1 - y0) / total if total else 0',
    '            y = y0',
    '            for i in row:',
    '                out[i] = (x0, y, x, y + values[i] * k)',
    '                y += values[i] * k',
    '            x0 = x',
    '        value -= total',
    '        i0 = i1',
    '    return out',
    '',
    'def inset(box, p):',
    '    """A box less p on each side (a box too small keeps its middle), as d3 pads its tiles."""',
    '    x0, y0, x1, y1 = box[0] + p, box[1] + p, box[2] - p, box[3] - p',
    '    if x1 < x0:',
    '        x0 = x1 = (x0 + x1) / 2',
    '    if y1 < y0:',
    '        y0 = y1 = (y0 + y1) / 2',
    '    return (x0, y0, x1, y1)',
    '',
    'def children_box(box, inner=3, top=22, side=5.5):',
    '    """Where a tile\'s children go: Plotly\'s padding, 22 pixels of header at the top, 5.5 on the other sides, 3 between tiles."""',
    '    p = inner / 2',
    '    return inset((box[0] + side - p, box[1] + top - p, box[2] - side + p, box[3] - side + p), 0)',
]



def _treemap_code(table, plan, rows, table_name):
    """Treemap: a tile for each level of the first category, its area the
    count of rows (or the sum of Sizes), split into tiles for the levels of a
    second; laid out as the page's Plotly does (d3's squarified treemap, its
    paddings), on the graph's pixels."""
    P = plan
    cats = P.get('cats') or []
    levels = P.get('levels') or {}
    Z, C = P.get('sizes'), P.get('color')
    W, H = P.get('size') or [600, 360]
    pw, ph = P.get('area') or [W - 8, H - 30]
    w = _Py()
    need = cats + ([Z] if Z else [])
    w(f'd = df.dropna(subset={_py(need)})' + (f'\nd = d[d[{_j(Z)}] > 0]   # Sizes: the rows with a positive value' if Z else ''),
      f'd = d.assign(_v={"d[" + _j(Z) + "]" if Z else "1.0"})   # a row\'s share of the area: {"its " + Z if Z else "one row"}',
      f'order = {{{", ".join(f"{_j(c)}: {_py(levels.get(c, []))}" for c in cats)}}}   # the tiles in the table\'s order of the levels',
      f'palette = {_py(PALETTE)}')
    if C and C.get('range'):
        lo, hi = C['range']
        w(f'ramp = LinearSegmentedColormap.from_list("ramp", {_py(RAMP)})   # Coloring: the mean of {C["col"]}, blue to red')
    elif C and C.get('cat'):
        w(f'color_of = {{{", ".join(f"{_py(v)}: {_j(PALETTE[i % len(PALETTE)])}" for i, v in enumerate(C["values"]))}}}   # Coloring: the level of {C["col"]} of a tile\'s first row')

    def color_expr(frame, depth, top):
        if C and C.get('range'):
            lo, hi = C['range']
            u = f'(m - {_nm(lo, 15)}) / {_nm(hi - lo, 15)}' if hi > lo else '0.5'
            return f'(lambda m: ramp({u}) if np.isfinite(m) else "#999999")({frame}[{_j(C["col"])}].mean())'
        if C and C.get('cat'):
            return f'color_of.get({frame}[{_j(C["col"])}].iloc[0], "{MISSING}")'
        return f'to_rgba(palette[{top} % 12], {0.9 if depth == 0 else 0.62})'
    w('', f'fig, ax = plt.subplots(figsize=({_inch(W)}, {_inch(H)}), layout="constrained")',
      f'box = children_box((0, 0, {_nm(pw, 15)}, {_nm(ph, 15)}))   # the plot\'s pixels, less the padding of the tiles\' header',
      f'first = d.groupby({_j(cats[0])})["_v"].sum().reindex(order[{_j(cats[0])}]).dropna()   # the tiles of {cats[0]}')
    w(f'tiles = [inset(t, 1.5) for t in squarify(list(first), *box)] if len(first) > 1 else [(0, 0, {_nm(pw, 15)}, {_nm(ph, 15)})]   # 3 pixels between tiles; a tile alone is the whole plot')
    with w.block('for top, ((level, value), tile) in enumerate(zip(first.items(), tiles)):'):
        w(f's = d[d[{_j(cats[0])}] == level]',
          f'ax.add_patch(Rectangle((tile[0], {_nm(ph, 15)} - tile[3]), tile[2] - tile[0], tile[3] - tile[1], facecolor={color_expr("s", 0, "top")}, edgecolor="{SURFACE}", linewidth={_lw(1)}))')
        if len(cats) > 1:
            w(f'ax.text(tile[0] + 4, {_nm(ph, 15)} - tile[1] - 4, f"{{level}}", ha="left", va="top", fontsize=7.5)   # the tile\'s header')
            w(f'second = s.groupby({_j(cats[1])})["_v"].sum().reindex(order[{_j(cats[1])}]).dropna()   # its tiles of {cats[1]}')
            with w.block('for (sub, v), inner in zip(second.items(), squarify(list(second), *children_box(tile))):'):
                w('inner = inset(inner, 1.5)',
                  f'ss = s[s[{_j(cats[1])}] == sub]',
                  f'ax.add_patch(Rectangle((inner[0], {_nm(ph, 15)} - inner[3]), inner[2] - inner[0], inner[3] - inner[1], facecolor={color_expr("ss", 1, "top")}, edgecolor="{SURFACE}", linewidth={_lw(1)}))',
                  f'ax.text(inner[0] + 4, {_nm(ph, 15)} - inner[1] - 4, f"{{sub}}\\n{{v:.10g}}\\n{{100 * v / value:.0f}}% of {{level}}", ha="left", va="top", fontsize=7)')
        else:
            w(f'ax.text(tile[0] + 4, {_nm(ph, 15)} - tile[1] - 4, f"{{level}}\\n{{value:.10g}}\\n{{100 * value / first.sum():.0f}}%", ha="left", va="top", fontsize=7)')
    w(f'ax.set_xlim(0, {_nm(pw, 15)})', f'ax.set_ylim(0, {_nm(ph, 15)})', 'ax.set_aspect("equal")', 'ax.axis("off")')
    helpers = _TREEMAP_LAYOUT + ['']
    imports = ['from matplotlib.patches import Rectangle', 'from matplotlib.colors import to_rgba'] + (['from matplotlib.colors import LinearSegmentedColormap'] if C and C.get('range') else [])
    return '\n'.join(_head_lines(table, plan, rows, table_name, imports) + [''] + helpers + w.lines + ['plt.show()'])


def _ternary_code(table, plan, rows, table_name):
    """Ternary Plot: three components as shares of their sum, a point in the
    triangle for each row (barycentric coordinates, worked out here)."""
    P = plan
    A, B, Cc = P['cols']
    C = P.get('color')
    W, H = P.get('size') or [600, 540]
    w = _Py()
    w(f'd = df.dropna(subset={_py([A, B, Cc])})',
      f'd = d[(d[{_py([A, B, Cc])}] >= 0).all(axis=1) & (d[{_j(A)}] + d[{_j(B)}] + d[{_j(Cc)}] > 0)]   # no negative value, a sum above zero',
      f's = d[{_j(A)}] + d[{_j(B)}] + d[{_j(Cc)}]',
      f'a, b, c = d[{_j(A)}] / s, d[{_j(B)}] / s, d[{_j(Cc)}] / s   # the shares',
      'x, y = 0.5 * a + c, np.sqrt(3) / 2 * a   # in the triangle: a at the top, b at the bottom left, c at the bottom right')
    if C and C.get('cat'):
        w(f'palette = {_py(PALETTE)}', f'color_of = {{{", ".join(f"{_py(v)}: palette[{i % len(PALETTE)}]" for i, v in enumerate(C["values"]))}}}   # Coloring: a colour for each level of {C["col"]}',
          f'colors = d[{_j(C["col"])}].map(color_of).fillna("{MISSING}")')
        cl = 'color=colors'
    elif C and C.get('range'):
        lo, hi = C['range']
        w(f'ramp = LinearSegmentedColormap.from_list("ramp", {_py(RAMP)}).with_extremes(bad="{MISSING}")')
        cl = f'c=d[{_j(C["col"])}], cmap=ramp, vmin={_nm(lo, 15)}, vmax={_nm(hi if hi > lo else lo + 1, 15)}, plotnonfinite=True'
    else:
        cl = f'color="{POINT}"'
    w('', f'fig, ax = plt.subplots(figsize=({_inch(W)}, {_inch(H)}), layout="constrained")',
      f'ax.plot([0, 1, 0.5, 0], [0, 0, np.sqrt(3) / 2, 0], color="{MUTED}", linewidth={_lw(1)})   # the triangle')
    with w.block('for q in (0.2, 0.4, 0.6, 0.8):   # the grid: each share at 20, 40, 60 and 80%'):
        w(f'ax.plot([0.5 * q, 1 - 0.5 * q], [np.sqrt(3) / 2 * q] * 2, color="{GRIDLINE}", linewidth={_lw(1)})   # a = q',
          f'ax.plot([1 - q, 0.5 * (1 - q)], [0, np.sqrt(3) / 2 * (1 - q)], color="{GRIDLINE}", linewidth={_lw(1)})   # b = q',
          f'ax.plot([q, 0.5 + 0.5 * q], [0, np.sqrt(3) / 2 * (1 - q)], color="{GRIDLINE}", linewidth={_lw(1)})   # c = q')
    msize, malpha, _, alpha_set = _marker(P, 6, 1)
    w(f'ax.scatter(x, y, s={_area(msize)}, {cl}{", alpha=" + _nm(malpha) if alpha_set else ""}, linewidths=0)',
      f'ax.text(0.5, np.sqrt(3) / 2 + 0.03, {_j(A)}, ha="center", va="bottom")',
      f'ax.text(-0.03, -0.03, {_j(B)}, ha="right", va="top")',
      f'ax.text(1.03, -0.03, {_j(Cc)}, ha="left", va="top")',
      'ax.set_aspect("equal")', 'ax.axis("off")')
    if C and C.get('cat'):
        w(f'fig.legend([plt.Line2D([], [], marker="o", linestyle="", color=palette[k % 12]) for k in range({len(C["values"])})], {_py(C.get("labels") or [str(v) for v in C["values"]])}, title={_j(C["col"])}, loc="outside right upper", frameon=False, fontsize=8)')
    elif C and C.get('range'):
        w(f'fig.colorbar(ax.collections[-1], ax=ax, label={_j(C["col"])}, shrink=0.6)')
    imports = ['from matplotlib.colors import LinearSegmentedColormap'] if C and C.get('range') else []
    return '\n'.join(_head_lines(table, plan, rows, table_name, imports) + w.lines + ['plt.show()'])


def _scatter3d_code(table, plan, rows, table_name):
    """Scatterplot 3D: three columns as a cloud of points (mplot3d), with drop
    lines down to the lowest Z."""
    P = plan
    X, Y, Zc = P['cols']
    C = P.get('color')
    W, H = P.get('size') or [640, 520]
    ps = P.get('pointSize') if isinstance(P.get('pointSize'), (int, float)) and P['pointSize'] > 0 else 3.5   # the page's size for this many points
    w = _Py()
    w(f'd = df.dropna(subset={_py([X, Y, Zc])})   # the rows with all three values')
    if C and C.get('cat'):
        w(f'palette = {_py(PALETTE)}', f'color_of = {{{", ".join(f"{_py(v)}: palette[{i % len(PALETTE)}]" for i, v in enumerate(C["values"]))}}}   # Coloring: a colour for each level of {C["col"]}',
          f'colors = d[{_j(C["col"])}].map(color_of).fillna("{MISSING}")')
        cl = 'color=colors'
    elif C and C.get('range'):
        lo, hi = C['range']
        w(f'ramp = LinearSegmentedColormap.from_list("ramp", {_py(RAMP)}).with_extremes(bad="{MISSING}")')
        cl = f'c=d[{_j(C["col"])}], cmap=ramp, vmin={_nm(lo, 15)}, vmax={_nm(hi if hi > lo else lo + 1, 15)}, plotnonfinite=True'
    else:
        cl = f'color="{POINT}"'
    w('', f'fig = plt.figure(figsize=({_inch(W)}, {_inch(H)}), layout="constrained")',
      'ax = fig.add_subplot(projection="3d")',
      f'ax.scatter(d[{_j(X)}], d[{_j(Y)}], d[{_j(Zc)}], s={_area(_marker(P, ps, 1)[0])}, {cl}{", alpha=" + _nm(_marker(P, ps, 1)[1]) if _marker(P, ps, 1)[3] else ""}, depthshade=False, linewidths=0)')
    if P.get('drop'):
        w(f'zmin = d[{_j(Zc)}].min()')
        with w.block(f'for x, y, z in zip(d[{_j(X)}], d[{_j(Y)}], d[{_j(Zc)}]):   # Drop Lines: from each point down to the lowest Z'):
            w(f'ax.plot([x, x], [y, y], [zmin, z], color="{MUTED}80", linewidth={_lw(1)})')
    w(f'ax.set_xlabel({_j(X)})', f'ax.set_ylabel({_j(Y)})', f'ax.set_zlabel({_j(Zc)})',
      'ax.set_box_aspect((1, 1, 1))   # a cube, as the page\'s', 'ax.view_init(elev=35.26, azim=45)   # Plotly\'s first view: from (1.25, 1.25, 1.25)')
    if C and C.get('cat'):
        w(f'fig.legend([plt.Line2D([], [], marker="o", linestyle="", color=palette[k % 12]) for k in range({len(C["values"])})], {_py(C.get("labels") or [str(v) for v in C["values"]])}, title={_j(C["col"])}, loc="outside right upper", frameon=False, fontsize=8)')
    imports = ['from matplotlib.colors import LinearSegmentedColormap'] if C and C.get('range') else []
    return '\n'.join(_head_lines(table, plan, rows, table_name, imports) + w.lines + ['plt.show()'])



# The colour themes of Contour Plot and Surface Plot, as Plotly draws them.
_THEMES = {'ramp': ('Blue to Gray to Red', RAMP), 'viridis': ('Viridis', None),
           'blues': ('Blues', [(0, '#050aac'), (0.35, '#283cbe'), (0.5, '#4664f5'), (0.6, '#5a78f5'), (0.7, '#6a89f7'), (1, '#dcdcdc')]),
           'spectral': ('Spectral (Plotly\'s Portland)', [(0, '#0c3383'), (0.25, '#0a88ba'), (0.5, '#f2d338'), (0.75, '#f28f38'), (1, '#d91e1e')])}


def _grid_lines(P):
    """The values between the points, on a grid (as graph.interp)."""
    x, y, z = _j(P['x']), _j(P['y']), _j(P['z'])
    n = int(P.get('grid') or 60)
    method = P.get('method') or 'linear'
    return [f'd = df[[{x}, {y}, {z}]].dropna()',
            f'means = d.groupby([{x}, {y}], as_index=False).mean()   # rows at the same place: their mean',
            ('method = "cubic" if len(means) >= 4 else "linear"   # the report\'s cubic interpolation (linear with fewer than four points)' if method == 'cubic'
             else f'method = {_j(method)}   # the report\'s interpolation'),
            f'gx, gy = np.linspace(means[{x}].min(), means[{x}].max(), {n}), np.linspace(means[{y}].min(), means[{y}].max(), {n})',
            f'gz = griddata(means[[{x}, {y}]].to_numpy(), means[{z}].to_numpy(), tuple(np.meshgrid(gx, gy)), method=method)   # {n} x {n}; none outside the points\' hull']


def _theme_lines(theme):
    label, stops = _THEMES.get(theme, _THEMES['ramp'])
    if stops is None:
        return ['cmap = plt.cm.viridis   # Color Theme: Viridis'], []
    pairs = stops if isinstance(stops[0], tuple) else [(0, stops[0]), (0.5, stops[1]), (1, stops[2])]
    return [f'cmap = LinearSegmentedColormap.from_list("theme", {_py([list(q) for q in pairs])})   # Color Theme: {label}'], ['from matplotlib.colors import LinearSegmentedColormap']


def _contour_code(table, plan, rows, table_name):
    """Contour Plot: the values of Z between the points, interpolated on
    their Delaunay triangulation (griddata), as contour lines or bands at the
    page's levels."""
    P = plan
    W, H = P.get('size') or [600, 470]
    lv = P.get('levels') or {}
    theme, timp = _theme_lines(P.get('theme') or 'ramp')
    fill = bool(P.get('fill'))
    w = _Py()
    w(*_grid_lines(P), *theme,
      f'levels = np.arange({_nm(lv.get("start", 0), 15)}, {_nm(lv.get("end", 1), 15)} + {_nm(lv.get("size", 1), 15)} / 2, {_nm(lv.get("size", 1), 15)})   # the page\'s contours: every {_nm(lv.get("size", 1))} from {_nm(lv.get("start", 0))} to {_nm(lv.get("end", 1))}',
      'norm = plt.Normalize(np.nanmin(gz), np.nanmax(gz))   # the colours over the range of the values',
      '', f'fig, ax = plt.subplots(figsize=({_inch(W)}, {_inch(H)}), layout="constrained")')
    if fill:
        w('ax.contourf(gx, gy, gz, levels=levels, cmap=cmap, norm=norm, extend="both")   # Fill Areas',
          f'lines = ax.contour(gx, gy, gz, levels=levels, colors="#000000", linewidths={_lw(1.4)})   # with the contours over them, black as Plotly draws them')
    else:
        w(f'lines = ax.contour(gx, gy, gz, levels=levels, cmap=cmap, norm=norm, linewidths={_lw(1.4)})')
    if P.get('labels'):
        w(f'ax.clabel(lines, fontsize=7, colors="{TEXT}")   # Label Contours')
    if P.get('points', True):
        msize, malpha, _, _ = _marker(P, 5, 0.75)
        w(f'ax.scatter(d[{_j(P["x"])}], d[{_j(P["y"])}], s={_area(msize)}, color="#3d3229", alpha={_nm(malpha)}, linewidths=0)   # Show Data Points')
    w(f'fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax, label={_j(P["z"])})',
      f'ax.set_xlabel({_j(P["x"])})', f'ax.set_ylabel({_j(P["y"])})')
    return '\n'.join(_head_lines(table, plan, rows, table_name, ['from scipy.interpolate import griddata'] + timp) + w.lines + ['plt.show()'])


def _surface_code(table, plan, rows, table_name):
    """Surface Plot: the values of Z between the points as a surface over the
    grid of X (griddata), with the points around it (mplot3d)."""
    P = plan
    W, H = P.get('size') or [640, 520]
    theme, timp = _theme_lines(P.get('theme') or 'ramp')
    w = _Py()
    w(*_grid_lines(P), *theme,
      '', f'fig = plt.figure(figsize=({_inch(W)}, {_inch(H)}), layout="constrained")',
      'ax = fig.add_subplot(projection="3d")',
      'GX, GY = np.meshgrid(gx, gy)',
      'surface = ax.plot_surface(GX, GY, gz, cmap=cmap, vmin=np.nanmin(gz), vmax=np.nanmax(gz), alpha=0.92, linewidth=0)   # outside the points\' hull: no surface')
    if P.get('contours'):
        w('ax.contour(GX, GY, gz, cmap=cmap, linewidths=0.8)   # Show Contours: on the surface,',
          'ax.contour(GX, GY, gz, zdir="z", offset=np.nanmin(gz), cmap=cmap, linewidths=0.8)   # and projected below it')
    if P.get('points', True):
        msize, malpha, _, alpha_set = _marker(P, 3, 1)
        w(f'ax.scatter(d[{_j(P["x"])}], d[{_j(P["y"])}], d[{_j(P["z"])}], s={_area(msize)}, color="#2b221b"{", alpha=" + _nm(malpha) if alpha_set else ""}, depthshade=False, linewidths=0)   # Show Data Points')
    w(f'ax.set_xlabel({_j(P["x"])})', f'ax.set_ylabel({_j(P["y"])})', f'ax.set_zlabel({_j(P["z"])})',
      'ax.set_box_aspect((1, 1, 1))', 'ax.view_init(elev=35.26, azim=45)   # Plotly\'s first view: from (1.25, 1.25, 1.25)',
      f'fig.colorbar(surface, ax=ax, label={_j(P["z"])}, shrink=0.7)')
    return '\n'.join(_head_lines(table, plan, rows, table_name, ['from scipy.interpolate import griddata'] + timp) + w.lines + ['plt.show()'])



# The functional graphs' colours: the palette without the selection's orange, and viridis's stops.
_FD_COLORS = [c for c in PALETTE if c != '#d9822b']
_VIRIDIS = ['#440154', '#482878', '#3e4989', '#31688e', '#26828e', '#1f9e89', '#35b779', '#6ece58', '#b5de2b', '#fde725']


def _fd_code(table, plan, rows, table_name):
    """The Functional Data Plot's graphs: the functional boxplot, the rainbow
    plot, the HDR boxplot and its score plot. The curves as graph.fbox and
    graph.hdr read them (a row per curve, or stacked with an ID), their
    depths, regions and outliers computed as there, then drawn as the page
    draws them."""
    P = plan
    view = P.get('view') or 'box'
    layout, y, id_, x, xmode = P.get('layout') or 'wide', P.get('y'), P.get('id'), P.get('x'), P.get('xmode') or 'names'
    C = _curves(table, layout, y, rows, id_, x, xmode)
    W, H = P.get('size') or [800, 450]
    imports = ['from matplotlib.colors import to_rgba']
    body = _curves_code(C['layout'], C, y, id_, x)
    Y = C['Y']
    if view in ('box', 'rainbow'):
        method = P.get('method') or 'MBD'
        if method == 'BD2x' and len(Y) > BD2_COUNTED:
            method = 'BD2'
        rule = 'sungenton' if P.get('rule') == 'sungenton' else 'statsmodels'
        wf = float(P.get('wfactor') or 1.5)
        body += _fbox_def_lines(method, rule, wf)
        imports.append('from statsmodels.graphics.functional import banddepth')
        call = 'functional_boxplot(data)'
    else:
        vary = Y.std(axis=0) > 1e-12 * max(1.0, float(np.abs(Y).max())) if len(Y) else np.ones(Y.shape[1], dtype=bool)
        thr = float(P.get('threshold') or 0.95)
        bw = P.get('bw') if P.get('bw') in ('normal_reference', 'cv_ml', 'cv_ls') else 'normal_reference'
        body += _hdr_def_lines(bool(np.all(vary)), thr, int(np.clip(P.get('grid') or HDR_GRID, 21, 401)), bw)
        call = 'hdr_boxplot(data)'
    w = _Py()
    w('', 'x, data, ids = curves(df)', f'res = {call}')
    # the curves' names, as the page shows them: the ID's value, or the row's label, or its number
    idcol = P.get('label_col')
    if layout == 'long':
        w('names = [str(k) for k in ids]   # a curve for each ID')
    elif idcol:
        w(f'names = [str(v) for v in df.loc[ids - 1, {_j(idcol)}]]   # the curves\' names: their rows\' {idcol}')
    else:
        w('names = [f"row {r}" for r in ids]')
    xt, yt = P.get('xtitle') or 'X', P.get('ytitle') or 'Y'
    datex = bool(P.get('date_x'))
    X = 'pd.to_datetime(x, unit="ms")' if datex else 'x'
    named = int(P.get('named') or 12)
    w('', f'fig, ax = plt.subplots(figsize=({_inch(W)}, {_inch(H)}), layout="constrained")')
    ink = TEXT
    if view == 'box':
        w(f'ax.fill_between({X}, *res["envelope"], color=to_rgba("{ink}", 0.12), linewidth=0, label="Non-outlying envelope")',
          f'ax.fill_between({X}, res["lower"], res["upper"], color=to_rgba("{ink}", 0.3), linewidth=0, label="50% central region")',
          'out = np.nonzero(res["outlier"])[0]   # the outlying curves, in the order of the rows')
        if P.get('curves'):
            w('rest = [c for c in range(len(data)) if not res["outlier"][c] and c != res["median"]]',
              f'ax.plot({X}, data[rest].T, color=to_rgba("{ink}", 0.3), linewidth={_lw(0.8)})   # Show Curves: the other curves')
        if P.get('fences'):
            w(f'ax.plot({X}, res["fence_lo"], {X}, res["fence_hi"], color=to_rgba("{ink}", 0.75), linewidth={_lw(1)}, linestyle="--")   # Show Fences')
        w(f'ax.plot({X}, data[res["median"]], color="{ink}", linewidth={_lw(2.6)}, label="Median: " + names[res["median"]])   # the deepest curve')
        w(f'colors = {_py(_FD_COLORS)}   # the outliers\' colours: the page\'s palette without the selection\'s orange')
        with w.block(f'for i, c in enumerate(out[:{named}]):'):
            w(f'ax.plot({X}, data[c], color=colors[i % len(colors)], linewidth={_lw(1.6)}, label=names[c])')
        with w.block(f'if len(out) > {named}:'):
            w(f'more = ax.plot({X}, data[out[{named}:]].T, color=to_rgba("{MUTED}", 0.9), linewidth={_lw(1.1)}, linestyle=":")',
              f'more[0].set_label(f"{{len(out) - {named}}} more outliers")')
        n_out = int(P.get('n_outliers', -1))
        sm = 'BD2' if (P.get('method') or 'MBD') == 'BD2x' else (P.get('method') or 'MBD')
        w(f'# sm.graphics.fboxplot(data, xdata=x, method={_j(sm)}, wfactor={float(P.get("wfactor") or 1.5):g}) draws the statsmodels version'
          + ('; its fences are fboxplot\'s own' if P.get('rule') == 'sungenton' else '')
          + ('; with exactly one outlier it stops with a ZeroDivisionError (statsmodels 0.14)' if n_out == 1 else ''))
    elif view == 'rainbow':
        imports.append('from matplotlib.colors import LinearSegmentedColormap')
        w(f'depth_map = LinearSegmentedColormap.from_list("depth", {_py(_VIRIDIS)})   # viridis\'s stops, as the page colours depth',
          'n = len(data)',
          'q = (res["rank"] - 1) / max(1, n - 1)   # 0 for the deepest curve, 1 for the least deep',
          'order = [c for c in res["order"][::-1] if c != res["median"]]   # the least deep first: the deepest on top')
        with w.block('if n <= 150:'):
            with w.block('for c in order:'):
                w(f'ax.plot({X}, data[c], color=depth_map(0.88 * q[c]), linewidth={_lw(1.1)})')
        with w.block('else:   # many curves: forty shades of depth'):
            w('shade = np.minimum(39, np.floor(q[order] * 40)).astype(int)')
            with w.block('for b in range(39, -1, -1):'):
                w('pick = [c for c, s in zip(order, shade) if s == b]')
                with w.block('if pick:'):
                    w(f'ax.plot({X}, data[pick].T, color=depth_map(0.88 * (b + 0.5) / 40), linewidth={_lw(1)})')
        w(f'ax.plot({X}, data[res["median"]], color=depth_map(0), linewidth={_lw(3)})   # the median, thickest and on top',
          'bar = fig.colorbar(plt.cm.ScalarMappable(norm=plt.Normalize(1, n), cmap=LinearSegmentedColormap.from_list("ranks", [depth_map(0.88 * u) for u in np.linspace(0, 1, 5)])), ax=ax, label="Depth rank", ticks=[1, n])',
          'bar.ax.set_yticklabels(["1: deepest", str(n)])',
          f'# sm.graphics.rainbowplot(data, xdata=x, method={_j({"BD2x": "BD2", "BD2": "BD2"}.get(P.get("method"), "MBD"))}) colours the curves by the same depth')
    elif view == 'hdr':
        inkb = INK
        w('rest = np.nonzero(~res["outlier"])[0]',
          f'lines = ax.plot({X}, data[rest].T, color=to_rgba("{TEXT}", 0.2), linewidth={_lw(0.8)})',
          'if lines:',
          '    lines[0].set_label("Curves")',
          f'ax.fill_between({X}, res["hdr90"][1], res["hdr90"][0], color=to_rgba("{inkb}", 0.2), linewidth=0, label="90% HDR")',
          f'ax.fill_between({X}, res["hdr50"][1], res["hdr50"][0], color=to_rgba("{inkb}", 0.42), linewidth=0, label="50% HDR")',
          f'ax.plot({X}, res["modal"], color="{inkb}", linewidth={_lw(2.6)}, label="Modal curve")',
          'out = np.nonzero(res["outlier"])[0]',
          f'colors = {_py(_FD_COLORS)}')
        with w.block(f'for i, c in enumerate(out[:{named}]):'):
            w(f'ax.plot({X}, data[c], color=colors[i % len(colors)], linewidth={_lw(1.6)}, label=names[c])')
        with w.block(f'if len(out) > {named}:'):
            w(f'more = ax.plot({X}, data[out[{named}:]].T, color=to_rgba("{MUTED}", 0.9), linewidth={_lw(1.1)}, linestyle=":")',
              f'more[0].set_label(f"{{len(out) - {named}}} more outliers")')
        w('# sm.graphics.hdrboxplot(data, xdata=x) draws the statsmodels version (it runs a multiprocessing Pool, and searches the bands with differential evolution)')
    else:   # the HDR boxplot's score plot
        inkb = INK
        w('S = res["scores"]',
          'lo, hi = S.min(axis=0), S.max(axis=0)',
          'pad = 0.25 * (hi - lo)',
          'g1, g2 = np.linspace(lo[0] - pad[0], hi[0] + pad[0], 81), np.linspace(lo[1] - pad[1], hi[1] + pad[1], 81)',
          'G1, G2 = np.meshgrid(g1, g2)',
          'Z = res["kde"].pdf(np.c_[G1.ravel(), G2.ravel()]).reshape(G1.shape)   # the density of the scores',
          f'ax.contourf(g1, g2, Z, levels=[res["levels"][0.9], np.inf], colors=[to_rgba("{inkb}", 0.14)])   # the 90% region',
          f'ax.contourf(g1, g2, Z, levels=[res["levels"][0.5], np.inf], colors=[to_rgba("{inkb}", 0.3)])   # the 50% region',
          f'ax.contour(g1, g2, Z, levels=[res["levels"][0.9], res["levels"][0.5]], colors=[to_rgba("{inkb}", 0.75)], linewidths={_lw(1)})',
          f'ax.contour(g1, g2, Z, levels=[res["levels"][{float(P.get("threshold") or 0.95):g}]], colors=[to_rgba("{inkb}", 0.75)], linewidths={_lw(1)}, linestyles="--")   # outliers outside',
          f'ax.scatter(S[:, 0], S[:, 1], s={_area(7)}, color=np.where(res["outlier"], "#b0302a", "{POINT}"), linewidths=0)',
          f'ax.plot(*res["mode"], marker="x", markersize={_nm(13 * PX)}, markeredgewidth={_lw(2)}, color="{TEXT}", linestyle="")   # the mode: the modal curve')
        with w.block('for c in np.nonzero(res["outlier"])[0][:20]:'):
            w('ax.annotate(names[c], S[c], xytext=(4, 0), textcoords="offset points", ha="left", va="center", fontsize=7, color="#b0302a")')
        w('ax.set_xlim(g1[0], g1[-1])', 'ax.set_ylim(g2[0], g2[-1])',
          'ax.set_xlabel(f"PC1 score ({100 * res[\'explained\'][0]:.1f}% of the variance)")',
          'ax.set_ylabel(f"PC2 score ({100 * res[\'explained\'][1]:.1f}%)")')
    if view != 'scores':
        if P.get('ticks'):
            w(f'ax.set_xticks(x, {_py(P["ticks"])})   # the Y columns\' names')
        w(f'ax.set_xlabel({_j(xt)})', f'ax.set_ylabel({_j(yt)})')
        if view != 'rainbow':
            w(f'fig.legend(loc="outside lower center", ncols={1 if W < 460 else 2}, frameon=False, fontsize=8)   # under the graph, as the page\'s at this width' if W < 620
              else 'fig.legend(loc="outside right upper", frameon=False, fontsize=8)')
    head = _head_lines(table, plan, rows, table_name, imports)
    return '\n'.join(head + [''] + body + w.lines + ['plt.show()'])


_WRITERS = {'builder': lambda table, plan, rows, name: _GB(table, plan, rows, name).code(), 'overlay': _overlay_code, 'matrix': _matrix_code, 'bubble': _bubble_code, 'parallel': _parallel_code, 'cell': _cell_code, 'treemap': _treemap_code, 'ternary': _ternary_code, 'scatter3d': _scatter3d_code, 'contour': _contour_code, 'surface': _surface_code, 'functional': _fd_code}


@api('graph.code')
def plot_code(kind, plan, table=None, rows=None, table_name='data'):
    """The Python that draws a graph of the Graph menu with matplotlib from a
    CSV export of the table, as the page draws it: kind names the graph
    (builder: Graph Builder's, and the legacy Chart's), plan says what the
    page drew. It computes from the rows what the page and graph.py
    computed, and ends in plt.show()."""
    if kind not in _WRITERS:
        raise ValueError(f'no code for a graph of kind {kind!r}')
    return {'plot_code': _WRITERS[kind](table, plan or {}, rows, table_name)}
