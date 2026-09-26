"""Graph: the statistics behind the Graph menu.

Graph Builder's elements (Smoother, Line of Fit, Ellipse, Contour, the
summary statistics behind Bar, Line, Area, Points, Box Plot and Caption Box,
the kernel densities of Histogram and Violin, Mosaic's chi-square), the
ellipses, fit lines and densities of Scatterplot Matrix, and the gridded
surfaces of Contour Plot and Surface Plot.

Groups come as parallel arrays: rows, the page's row numbers (None: every
row of the table, in order), and codes, the group of each row from 0 to
k - 1 (None: one group; a negative code leaves the row out). Results come
back one entry per group, in group order, so the page can put them back in
the right panel and colour.

The Smoother is JMP's: a cubic smoothing spline on standardized X with
lambda 0.05. scipy's make_smoothing_spline minimises the same penalised
sum of squares, sum w (y - f(x))^2 + lambda * integral f''(x)^2 dx; its
'Local Kernel' alternative is statsmodels' lowess.
"""
import json

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
