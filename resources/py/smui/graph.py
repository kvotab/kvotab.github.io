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
"""
import json
import re

import numpy as np
from scipy import stats
from scipy.interpolate import griddata, make_smoothing_spline
from scipy.signal import fftconvolve

from . import data
from .registry import api
from .util import code_head

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


# ---- the Python shown under a result -----------------------------------------
def _j(s):
    return json.dumps(s)


def _prelude(table_name, cols, freq, imports=()):
    lines = [code_head(table_name, list(imports))]
    need = [c for c in cols if c] + ([freq] if freq else [])
    lines.append(f'd = df.dropna(subset={_j(list(dict.fromkeys(need)))})')
    if freq:
        lines.append(f'd = d.loc[d.index.repeat(d[{_j(freq)}].clip(lower=0).round().astype(int))]   # Freq: a row counts that many times')
    return lines


def _loop(by, body):
    """body: lines that use d; with By groups, run them for each group."""
    if not by:
        return body
    return [f'for key, g in d.groupby({_j(list(by))}, observed=True):', '    print(key)'] + ['    ' + b.replace('d[', 'g[').replace('(d)', '(g)') for b in body]


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
    body = [f'x = d[{_j(y)}]']
    if by:
        body = [f'x = d.groupby({_j(list(by))}, observed=True)[{_j(y)}]']
        body += ["print(x.agg(['count', 'mean', 'std', 'sem', 'sum', 'min', 'max']))",
                 f"print(x.apply(lambda v: stats.t.interval({1 - alpha:g}, len(v) - 1, loc=v.mean(), scale=v.sem())))",
                 "print(x.apply(lambda v: np.quantile(v, [.25, .5, .75], method='weibull')))   # JMP's quantiles"]
    else:
        body += ["print(x.count(), x.mean(), x.std(), x.sem(), x.sum(), x.min(), x.max())",
                 f"print(stats.t.interval({1 - alpha:g}, len(x) - 1, loc=x.mean(), scale=x.sem()))",
                 "print(np.quantile(x, [.25, .5, .75], method='weibull'))   # JMP's quantiles, the (n+1)p-th values"]
    out['code'] = '\n'.join(_prelude(table_name, [y] + list(by or []), freq, ['from scipy import stats']) + body)
    if want:
        keep = set(want) | {'k', 'alpha', 'code'}
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
    if method == 'lowess':
        body = [f'x, y = d[{_j(x)}].to_numpy(), d[{_j(y)}].to_numpy()',
                f'fit = lowess(y, x, frac={float(frac):.6g}, it={int(it)}, delta=0.01 * np.ptp(x) if len(x) > 1000 else 0.0)',
                'print(fit)   # sorted x and the smoothed y']
        imports = ['from statsmodels.nonparametric.smoothers_lowess import lowess']
    else:
        body = [f'x, y = d[{_j(x)}].to_numpy(), d[{_j(y)}].to_numpy()',
                'm, s = x.mean(), x.std(ddof=1)   # JMP standardizes X',
                'z, inv = np.unique((x - m) / s, return_inverse=True)',
                'w = np.bincount(inv).astype(float)   # tied X: the mean of Y, weighted by the count',
                f'spline = make_smoothing_spline(z, np.bincount(inv, y) / w, w=w, lam={float(lam):.6g})',
                f'grid = np.linspace(x.min(), x.max(), {n_grid})',
                'print(np.c_[grid, spline((grid - m) / s)])']
        imports = ['from scipy.interpolate import make_smoothing_spline']
    return {'curves': curves, 'method': method,
            'code': '\n'.join(_prelude(table_name, [x, y] + list(by or []), freq, imports) + _loop(by, body))}


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
    terms = ' + '.join(['x'] + [f'I((x - x.mean())**{j})' for j in range(2, degree + 1)])
    frame = f'pd.DataFrame({{"x": d[{_j(x)}], "y": d[{_j(y)}]}})'
    head = []
    if robust:
        head = ['class Cauchy(sm.robust.norms.RobustNorm):   # Cauchy weights 1/(1 + (r/c)^2), as JMP\'s Robust Cauchy',
                '    c = 2.3849',
                '    def rho(self, z): return self.c**2 / 2 * np.log1p((z / self.c)**2)',
                '    def psi(self, z): return z / (1 + (z / self.c)**2)',
                '    def weights(self, z): return 1 / (1 + (z / self.c)**2)',
                '    def psi_deriv(self, z): u = (z / self.c)**2; return (1 - u) / (1 + u)**2']
        body = [f'fit = smf.rlm("y ~ {terms}", data={frame}, M=Cauchy()).fit()', 'print(fit.summary())']
    else:
        body = [f'fit = smf.ols("y ~ {terms}", data={frame}).fit()', 'print(fit.summary())',
                f'print(fit.get_prediction(pd.DataFrame({{"x": np.linspace(d[{_j(x)}].min(), d[{_j(x)}].max(), 5)}})).summary_frame(alpha={alpha:g}))']
    return {'fits': fits, 'code': '\n'.join(_prelude(table_name, [x, y] + list(by or []), freq) + head + _loop(by, body))}


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
    body = [f'xy = d[[{_j(x)}, {_j(y)}]].to_numpy()',
            'mu, cov = xy.mean(axis=0), np.cov(xy.T)',
            f'r2 = stats.chi2.ppf({coverage:g}, 2)   # the ellipse holds this share of the fitted bivariate normal',
            't = np.linspace(0, 2 * np.pi, 96)',
            'ellipse = mu[:, None] + np.sqrt(r2) * np.linalg.cholesky(cov) @ np.vstack([np.cos(t), np.sin(t)])',
            'print(mu, cov, np.corrcoef(xy.T)[0, 1])']
    return {'ellipses': out, 'coverage': coverage, 'code': '\n'.join(_prelude(table_name, [x, y] + list(by or []), freq, ['from scipy import stats']) + _loop(by, body))}


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
    body = [f'xy = d[[{_j(x)}, {_j(y)}]].to_numpy().T', 'kde = stats.gaussian_kde(xy)']
    if bw != 1:
        body.append(f'kde.set_bandwidth(kde.factor * {float(bw):g})')
    body += ['gx, gy = np.meshgrid(np.linspace(xy[0].min(), xy[0].max(), 64), np.linspace(xy[1].min(), xy[1].max(), 64))',
            'dens = kde(np.vstack([gx.ravel(), gy.ravel()])).reshape(gx.shape)',
            'at = kde(xy)   # the density at each point: the p contour is the level with a share p of the points above it',
            'print(np.quantile(at, [0.75, 0.5, 0.25, 0.0]))   # the levels of the 25%, 50%, 75% and 100% contours']
    return {'densities': out, 'code': '\n'.join(_prelude(table_name, [x, y] + list(by or []), freq, ['from scipy import stats']) + _loop(by, body))}


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
    body = [f'kde = stats.gaussian_kde(d[{_j(y)}])']
    if bw != 1:
        body.append(f'kde.set_bandwidth(kde.factor * {float(bw):g})')
    body += [f'grid = np.linspace(d[{_j(y)}].min(), d[{_j(y)}].max(), {grid})', 'print(np.c_[grid, kde(grid)])']
    return {'densities': out, 'code': '\n'.join(_prelude(table_name, [y] + list(by or []), freq, ['from scipy import stats']) + _loop(by, body))}


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
    lines = [code_head(table_name, ['from scipy import stats'])]
    if x and y:
        lines += [f'counts = pd.crosstab(df[{_j(x)}], df[{_j(y)}])',
                  'print(stats.chi2_contingency(counts, correction=False))                         # Pearson',
                  "print(stats.chi2_contingency(counts, correction=False, lambda_='log-likelihood'))   # likelihood ratio"]
    return {'tests': out, 'code': '\n'.join(lines)}


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
    body = [code_head(table_name, ['from scipy.interpolate import griddata']),
            f'd = df[[{_j(x)}, {_j(y)}, {_j(z)}]].dropna().groupby([{_j(x)}, {_j(y)}], as_index=False).mean()   # the same (x, y): the mean',
            f'gx, gy = np.meshgrid(np.linspace(d[{_j(x)}].min(), d[{_j(x)}].max(), {grid}), np.linspace(d[{_j(y)}].min(), d[{_j(y)}].max(), {grid}))',
            f'gz = griddata(d[[{_j(x)}, {_j(y)}]].to_numpy(), d[{_j(z)}].to_numpy(), (gx, gy), method={_j(method)})',
            'print(gz)']
    return {'x': gx, 'y': gy, 'z': gz, 'n': int(len(xv)), 'points': int(len(pts)), 'method': method,
            'zmin': float(np.nanmin(gz)) if np.isfinite(gz).any() else None, 'zmax': float(np.nanmax(gz)) if np.isfinite(gz).any() else None,
            'code': '\n'.join(body)}


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
    keys = list(by or [])
    kde = 'gaussian_kde(v)' if float(bw) == 1 else f'gaussian_kde(v, bw_method=lambda k: k.scotts_factor() * {float(bw):g})'
    spread = 's = 0.0   # cut at the data' if cutoff else f's = {float(cutoff_val):g} * v.std()   # the violin runs {float(cutoff_val):g} standard deviations past the data'
    one = [f'v = d[{_j(y)}].to_numpy()',
           f'kde = {kde}   # Scott\'s rule, as beanplot\'s violins',
           spread,
           'grid = np.linspace(v.min() - s, v.max() + s, 100)',
           'violin = kde(grid) / kde(grid).max()   # every violin is drawn to the same width',
           'print(len(v), v.mean(), np.median(v))   # the bean\'s n, mean line and median mark']
    lines = _prelude(table_name, [y] + keys, freq, ['from scipy.stats import gaussian_kde'])
    opts = {'cutoff': bool(cutoff), 'cutoff_val': float(cutoff_val)}
    if keys:
        lines += [f'for key, g in d.groupby({_j(keys)}, observed=True):   # a bean per group', '    print(key)']
        lines += ['    ' + s.replace('d[', 'g[') for s in one]
        lines += [f'print("overall mean", d[{_j(y)}].mean())   # the dotted line across the graph',
                  f'# sm.graphics.beanplot([g[{_j(y)}].to_numpy() for _, g in d.groupby({_j(keys)}, observed=True)], plot_opts={opts!r}) draws them (with matplotlib)']
    else:
        lines += one + [f'# sm.graphics.beanplot([v], plot_opts={opts!r}) draws it (with matplotlib)']
    return {'beans': out, 'code': '\n'.join(lines)}


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


def _fd_run(table_name, by, body, call, show):
    """The script around a function of the curves: for the table, or for
    each By group."""
    lines = [code_head(table_name, ['from statsmodels.graphics.functional import banddepth'])] + body
    if by:
        lines += [f'for key, g in df.dropna(subset={_j(list(by))}).groupby({_j(list(by))}, observed=True):',
                  '    print(key)', '    x, data, ids = curves(g)', f'    res = {call}', f'    {show}']
    else:
        lines += ['x, data, ids = curves(df)', f'res = {call}', show]
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
    body = _curves_code(C['layout'], C, y, id, x)
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
             '    return dict(depth=depth, rank=order.argsort() + 1, median=order[0], lower=lower, upper=upper,',
             '                fence_lo=fence_lo, fence_hi=fence_hi, outlier=outlier, envelope=(data[~outlier].min(axis=0), data[~outlier].max(axis=0)))']
    sm_method = 'BD2' if method == 'BD2x' else method
    show = 'print(pd.DataFrame({"depth": res["depth"], "rank": res["rank"], "outlier": res["outlier"]}, index=ids))'
    lines = _fd_run(table_name, by, body, 'functional_boxplot(data)', show)
    lines.append(f'# sm.graphics.fboxplot(data, xdata=x, method={_j(sm_method)}, wfactor={wf:g}) draws the statsmodels version (it needs matplotlib)'
                 + ('; its fences are fboxplot\'s own' if rule == 'sungenton' else '')
                 + ('; with exactly one outlier it stops with a ZeroDivisionError (statsmodels 0.14)' if int(outlier.sum()) == 1 else ''))
    lines.append(f'# sm.graphics.rainbowplot(data, xdata=x, method={_j(sm_method)}) colours the curves by the same depth')
    return {**base, 'method': method, 'rule': rule, 'wfactor': wf, 'depth': depth, 'rank': rank, 'median': int(ix[0]),
            'order': ix, 'central': half, 'lower': lower, 'upper': upper, 'inner': inner, 'fence_lo': lo_f, 'fence_hi': hi_f,
            'outlier': outlier, 'env_lo': keep.min(axis=0), 'env_hi': keep.max(axis=0), 'ties': _ties(Y), 'code': '\n'.join(lines)}


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
    body = _curves_code(C['layout'], C, y, id, x)
    body += ['from scipy import optimize',
             'from statsmodels.graphics.functional import _inverse_transform   # hdrboxplot\'s own: scores back to curves',
             'from statsmodels.multivariate.pca import PCA',
             'from statsmodels.nonparametric.kernel_density import KDEMultivariate',
             f'def hdr_boxplot(data, threshold={thr:g}, n_grid={G}):']
    if not vary.all():
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
    rebuild_txt = ('_rebuild(_inverse_transform(pca, pts))' if not vary.all() else '_inverse_transform(pca, pts)')
    if not vary.all():
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
             '    return dict(scores=scores, dens=dens, levels=lev, outlier=dens < lev[threshold],',
             f'                modal={rebuild_txt.replace("pts", "mode[None]")}[0], hdr50=band(lev[0.5], 1e6), hdr90=band(lev[0.9], lev[0.5]))   # hdrboxplot takes the 90% band outside the 50% one']
    show = 'print(pd.DataFrame({"density": res["dens"], "outlier": res["outlier"]}, index=ids))'
    lines = _fd_run(table_name, by, body, 'hdr_boxplot(data)', show)
    lines.append('# sm.graphics.hdrboxplot(data, xdata=x) draws the statsmodels version (it needs matplotlib, runs a multiprocessing Pool,'
                 ' and searches the bands with differential evolution)')
    return {**base, 'scores': S, 'explained': [float(rsq[1]), float(rsq[2] - rsq[1])] if len(rsq) > 2 else None, 'bw': np.asarray(ks.bw, dtype=float),
            'bw_method': bw, 'density': dens, 'levels': {'50': level[0.5], '90': level[0.9], 'threshold': level[thr]}, 'threshold': thr,
            'outlier': outlier, 'mode': mode, 'modal': rebuild(np.asarray(mode)[None])[0], 'hdr50': band(level[0.5], 1e6),
            'hdr90': band(level[0.9], level[0.5]), 'constant': int((~vary).sum()), 'grid_n': G,
            'grid': {'x': d1, 'y': d2, 'z': DZ.T}, 'code': '\n'.join(lines)}
