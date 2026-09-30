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
import inspect
import json
import math
import warnings

import numpy as np
import pandas as pd
from scipy import linalg as sla
from scipy import stats

from . import data
from .registry import api
from .util import code_head, formula_num, formula_ref, formula_str, one_line

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


# ---- the code's rows: the By group's, without the rows the report leaves out ------------

def _lit(v):
    """A value as a Python literal: text in double quotes, 3 for 3.0."""
    if isinstance(v, str):
        return J(v)
    if isinstance(v, (bool, np.bool_)):
        return 'True' if v else 'False'
    if isinstance(v, (int, float, np.integer, np.floating)):
        f = float(v)
        if not math.isfinite(f):
            return 'np.nan' if f != f else ('np.inf' if f > 0 else '-np.inf')
        return str(int(f)) if f.is_integer() and abs(f) < 1e15 else repr(f)
    return J(v)


def _lvtext(v):
    """A level as text, as the page shows it: 12 for 12.0."""
    if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, (bool, np.bool_)):
        f = float(v)
        return str(int(f)) if f.is_integer() and abs(f) < 1e15 else repr(f)
    return str(v)


def _value_text(table, name, v):
    """A value of a column as the page shows it: a date as its day."""
    try:
        m = data.meta(table, name)
    except (KeyError, TypeError):
        m = {}
    kind = (m.get('format') or {}).get('kind') if m.get('dataType') == 'numeric' else None
    if kind in ('date', 'datetime') and isinstance(v, (int, float)) and math.isfinite(v):
        import datetime
        d = datetime.datetime(1970, 1, 1) + datetime.timedelta(milliseconds=float(v))
        return d.strftime('%Y-%m-%d %H:%M:%S' if kind == 'datetime' else '%Y-%m-%d')
    return _lvtext(v)


def _keep_lines(table, rows, where=None):
    """The lines after the read_csv line that keep the report's rows of the
    table as exported: a By group's rows (a line per By column), and of those
    the ones the report uses (rows excluded or filtered out are dropped)."""
    L = []
    t = data.TABLES.get(table) if table is not None else None
    n = t['n'] if t else 0
    match = np.ones(n, dtype=bool)
    for w in where or []:
        c, v = w.get('column'), w.get('value')
        if not t or c not in t['cols']:
            continue
        raw = data.raw(table, c)
        if data.meta(table, c).get('dataType') == 'numeric':
            match &= np.asarray(raw, dtype=float) == float(v)
        else:
            match &= np.array([x == v for x in raw], dtype=bool)
        L.append(f'df = df[df[{J(c)}] == {_lit(v)}]   # only the rows where {one_line(c)} is {one_line(_value_text(table, c, v))}')
    if rows is not None and n:
        keep = np.zeros(n, dtype=bool)
        keep[np.asarray(rows, dtype=int)] = True
        drop = np.flatnonzero(match & ~keep)
        if len(drop):
            L.append(f'df = df.drop(index={drop.tolist()})   # the rows the report leaves out')
    return L


def _head(table, rows, where, table_name, imports=()):
    """The top of a snippet: the standard head (the table read from its CSV
    export as df), then the lines that keep the report's rows."""
    return '\n'.join([code_head(table_name, list(imports))] + _keep_lines(table, rows, where))


# ---- saved columns: every row of the group, and formula text --------------------------------
# A saved score, cluster or probability goes to every row whose columns are
# present, excluded rows and rows the report filters out included (as JMP's
# saved formulas compute them). Where the model has a closed form the column
# is a live formula in the page's language (resources/js/smui-formula.js):
# :name or :"name" for a column, numbers in their shortest round-trip form.
# Two traps of that language shape the text: Exp of a large number is
# missing (not infinite), so a softmax is written with the largest term
# taken out (Min of the squared distances); and Match(x, ...) takes a
# missing x for a missing value, so an argmin by Match is guarded by
# Is Missing. In a By group the formula is If(<the group>, ..., .): the
# other groups have their own fits.

def _group_rows(table, where=None):
    """The table's rows in the By group (every row without one), whatever
    their row states."""
    n = data.TABLES[table]['n']
    match = np.ones(n, dtype=bool)
    for w in where or []:
        c, v = w.get('column'), w.get('value')
        if c not in data.TABLES[table]['cols']:
            continue
        raw = data.raw(table, c)
        if data.meta(table, c).get('dataType') == 'numeric':
            match &= np.asarray(raw, dtype=float) == float(v)
        else:
            match &= np.array([x == v for x in raw], dtype=bool)
    return np.flatnonzero(match)


def _present_rows(table, cols, where=None):
    """The rows of the By group with every one of the numeric columns
    present, and their values (rows x columns)."""
    idx = _group_rows(table, where)
    X = np.column_stack([pd.to_numeric(data.series(table, c, idx, as_category=False), errors='coerce').to_numpy(float) for c in cols]) if cols else np.zeros((len(idx), 0))
    ok = np.isfinite(X).all(axis=1)
    return idx[ok], X[ok]


def _fnum(x):
    """A number in formula text; a missing or infinite one cannot be saved."""
    x = float(x)
    if not math.isfinite(x):
        raise ValueError('the fit has a missing or infinite number: no formula can be saved')
    return formula_num(x)


def _fz(name, center=0.0, scale=1.0):
    """A column centred and scaled: :x, (:x - c), ((:x - c) / s)."""
    ref = formula_ref(name)
    c, s = float(center), float(scale)
    e = ref if c == 0 else f'({ref} {"+" if c < 0 else "-"} {_fnum(abs(c))})'
    return e if s == 1 else f'({e} / {_fnum(s)})'


def _flin(coefs, exprs, const=0.0):
    """Σ coef·expr + const as formula text, the signs as operators (a zero
    coefficient left out)."""
    parts = []
    for c, e in zip(coefs, exprs):
        c = float(c)
        if c == 0.0:
            continue
        parts.append((c < 0, f'{_fnum(abs(c))} * {e}'))
    const = float(const)
    if const != 0.0 or not parts:
        parts.append((const < 0, _fnum(abs(const))))
    out = []
    for i, (neg, t) in enumerate(parts):
        out.append((f'-{t}' if neg else t) if i == 0 else f'{"-" if neg else "+"} {t}')
    return ' '.join(out)


def _fsum(exprs):
    """expr + expr + ...: a sum that is missing when any of them is."""
    return ' + '.join(exprs) if exprs else '0'


def _grouped(expr):
    """True when the whole expression is one parenthesized group (quoted
    names, which may hold parentheses, skipped)."""
    if not (expr.startswith('(') and expr.endswith(')')):
        return False
    depth, i, n = 0, 0, len(expr)
    while i < n:
        ch = expr[i]
        if ch == '"':
            i += 1
            while i < n and expr[i] != '"':
                i += 2 if expr[i] == '\\' else 1
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0 and i < n - 1:
                return False
        i += 1
    return depth == 0


def _fsq(expr):
    """expr squared: (expr) ^ 2 (^ binds tighter than every other operator)."""
    return f'{expr} ^ 2' if _grouped(expr) or formula_ref(expr[1:]) == expr else f'({expr}) ^ 2'


def _fmissing_guard(names):
    """A test that is 1 when any of the numeric columns is missing: their sum is."""
    return f'Is Missing({_fsum([formula_ref(c) for c in names])})'


def _fargmin(dists, results, names):
    """The result of the smallest of the expressions (the first of equal
    ones), missing when a column is: If(Is Missing(...), ., Match(Min(...), d1, r1, ...))."""
    pairs = ', '.join(f'{d}, {r}' for d, r in zip(dists, results))
    return f'If({_fmissing_guard(names)}, ., Match(Min({", ".join(dists)}), {pairs}))'


def _fvalue(table, name, v):
    """A value of a column in formula text: a quoted text or a number."""
    if data.meta(table, name).get('dataType') == 'numeric':
        return _fnum(v)
    return formula_str(v)


def _fguard(table, expr, where=None):
    """expr for the By group's rows only: If(:g == "a" & ..., expr, .)."""
    conds = [f'{formula_ref(w["column"])} == {_fvalue(table, w["column"], w["value"])}' for w in (where or [])
             if w.get('column') in data.TABLES[table]['cols']]
    if not conds:
        return expr
    return f'If({" & ".join(conds)}, {expr}, .)'


def _by_words(table, where=None):
    """The By group, for a saved column's notes: ' (where g is a)'."""
    ws = [f'{w["column"]} is {_value_text(table, w["column"], w["value"])}' for w in (where or []) if w.get('column') in data.TABLES[table]['cols']]
    return f' (the rows where {" and ".join(ws)})' if ws else ''


# ---- the graphs as matplotlib code ------------------------------------------------------------
# Under each graph the report shows Python that draws it with matplotlib from a
# CSV export of the table, as the notebook runs it: the report's rows, the
# numbers computed from the data as the report computes them (the same fits),
# the page's colours in its light theme, the graph's size at 100 pixels an
# inch. The page puts each block right under its graph; it writes the
# scatterplot matrix's itself (the page chose its bins).
PLT = 'import matplotlib.pyplot as plt'
BASE, BAR, RED, TEXT, MUTED, GRID, BLUE = '#2f6690', '#8fa9c2', '#c0392b', '#352921', '#786b5d', '#e0d7ce', '#2f6ec7'
PALETTE = ['#2f6690', '#d9822b', '#3a7d44', '#b0413e', '#6c5b7b', '#1f9e89', '#c0a000', '#8c564b', '#e377c2', '#7f7f7f', '#17becf', '#9467bd']
DIVERGING = [BLUE, '#f6f3f0', RED]        # the page's colour maps (light theme): blue for -1, red for +1
PX = 0.72                                  # points per pixel, at 100 pixels an inch


def _lw(px):
    """A line width in points from the page's pixels."""
    return f'{px * PX:.3g}'


def _area(px):
    """A marker's area in points² (matplotlib's s) from the page's diameter in pixels."""
    return f'{(px * PX) ** 2:.3g}'


def _msize(px):
    """A marker's size in points (plot's markersize) from the page's pixels."""
    return f'{px * PX:.3g}'


def _fig(w, h):
    return f'fig, ax = plt.subplots(figsize=({round(w) / 100:g}, {round(h) / 100:g}), layout="constrained")'


def _plot_head(table, rows, where, table_name, imports=()):
    return _head(table, rows, where, table_name, [PLT, *imports])


# Functions a graph's code defines when it needs them.
FMT_DEF = [
    'def fmt(v, sig=7):',
    '    """A number as the page writes it: up to sig significant digits, no trailing zeros, − for minus."""',
    '    if v is None or not np.isfinite(v):',
    '        return "."',
    '    if float(v).is_integer() and abs(v) < 1e15:',
    '        s = str(int(v))',
    '    elif abs(v) >= 1e9 or abs(v) < 1e-4:',
    '        m, e = f"{v:.{min(sig, 5) - 1}e}".split("e")',
    '        s = f"{m}e{int(e)}"',
    '    else:',
    '        s = np.format_float_positional(float(f"{v:.{sig}g}"), trim="-")',
    '    return "−" + s[1:] if s.startswith("-") else s']
ELLIPSE_DEF = [
    'def ellipse(mx, my, sx, sy, r, level):',
    '    """The page\'s density ellipse: the contour of a bivariate normal with these means, standard deviations',
    '    and correlation that holds `level` of it, at 73 points."""',
    '    c = np.sqrt(-2 * np.log(1 - level))   # the square root of the chi-square quantile with 2 DF',
    '    t = 2 * np.pi * np.arange(73) / 72',
    '    r = min(max(r, -0.999999), 0.999999)',
    '    return mx + c * sx * np.cos(t), my + c * sy * (r * np.cos(t) + np.sqrt(1 - r * r) * np.sin(t))']


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
def mv_fit(table, columns, rows=None, weight=None, freq=None, method='rowwise', alpha=0.05, where=None, table_name='data'):
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
    c = [_head(table, rows, where, table_name, ['from scipy import stats']), f'X = df[{_cols_expr(cols)}]']
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
    head = lambda imports: _plot_head(table, rows, where, table_name, imports)  # noqa: E731
    out.update(_colormap_codes(head, cols, weight, freq, pairwise, alpha))
    return out


def _weight_code(weight, freq):
    parts = [f'df[{J(v)}]' for v in (weight, freq) if v]
    return ' * '.join(parts)


def _corr_lines(cols, weight, freq, pairwise):
    """Lines that compute R, the correlations of the columns, and N, the
    observations behind each, as multivariate.fit does."""
    L = [f'X = df[{_cols_expr(cols)}]']
    wexpr = _weight_code(weight, freq)
    fexpr = f'df[{J(freq)}]' if freq else 'pd.Series(1.0, index=df.index)'
    if not pairwise:
        if wexpr:
            L += [f'w = {wexpr}   # {"Weight times Freq" if weight and freq else "Weight" if weight else "Freq"}',
                  'ok = X.notna().all(axis=1) & w.gt(0)   # row-wise: the rows with every column and a positive weight',
                  'R = DescrStatsW(X[ok], weights=w[ok], ddof=1).corrcoef   # the weighted correlations',
                  f'N = np.full(R.shape, float({fexpr}[ok].sum()))   # the observations: {"the sum of Freq" if freq else "the rows"}']
        else:
            L += ['Xc = X.dropna()   # row-wise: the rows with every column', 'R = Xc.corr().to_numpy()',
                  'N = np.full(R.shape, float(len(Xc)))   # the observations']
    elif wexpr:
        L += [f'w = {wexpr}   # {"Weight times Freq" if weight and freq else "Weight" if weight else "Freq"}', f'f = {fexpr}',
              'p = X.shape[1]; R = np.eye(p); N = np.zeros((p, p))',
              'for i in range(p):   # pairwise: each pair on the rows where both are present',
              '    for j in range(p):',
              '        ok = X.iloc[:, i].notna() & X.iloc[:, j].notna() & w.gt(0)',
              '        N[i, j] = f[ok].sum()',
              '        if i != j:',
              '            x, y, wt = X.iloc[:, i][ok], X.iloc[:, j][ok], w[ok]',
              '            dx, dy = x - np.average(x, weights=wt), y - np.average(y, weights=wt)',
              '            R[i, j] = (wt * dx * dy).sum() / np.sqrt((wt * dx * dx).sum() * (wt * dy * dy).sum())']
    else:
        L += ['R = X.corr().to_numpy()   # pairwise: each pair on the rows where both are present',
              'M = X.notna().to_numpy(float); N = M.T @ M   # the rows of each pair']
    return L


def _heatmap_lines(p, title, vmin, vmax, colors, value, text):
    """Lines that draw the matrix Z over the names as the page's colour maps:
    the first name at the top, a white gap between the cells, the values as
    text in the cells for twelve columns or fewer."""
    sz = max(260, min(620, 60 + 46 * p))
    L = [f'cmap = LinearSegmentedColormap.from_list("page", {J(colors)})   # the page\'s colour scale, {value}',
         _fig(sz + 60, sz),
         f'im = ax.imshow(Z, cmap=cmap, vmin={vmin}, vmax={vmax})',
         'ax.set_xticks(range(len(names)), names, rotation=40, ha="right")',
         'ax.set_yticks(range(len(names)), names)',
         'ax.set_xticks(np.arange(len(names) + 1) - 0.5, minor=True)',
         'ax.set_yticks(np.arange(len(names) + 1) - 0.5, minor=True)',
         f'ax.grid(which="minor", color="white", linewidth={_lw(1)})',
         'ax.tick_params(which="both", length=0)',
         'for side in ax.spines.values():',
         '    side.set_visible(False)']
    if p <= 12:
        L += ['',
              'def ink(v):   # the text on a cell: dark on a light cell, light on a dark one',
              '    r, g, b, _ = cmap(im.norm(v))',
              '    return "#1d1712" if 0.299 * r + 0.587 * g + 0.114 * b > 0.55 else "#f7f1ea"',
              '',
              'for i in range(len(names)):',
              '    for j in range(len(names)):',
              f'        ax.text(j, i, {text}, ha="center", va="center", fontsize=7, color=ink(Z[i, j]))']
    L += ['fig.colorbar(im, ax=ax, shrink=0.8)', f'ax.set_title({J(title)})', 'plt.show()']
    return L


def _colormap_codes(head, cols, weight, freq, pairwise, alpha):
    """The code of the three colour maps of Multivariate: on the
    correlations, on their p-values, and the correlations clustered."""
    p = len(cols)
    imports = ['from matplotlib.colors import LinearSegmentedColormap']
    if weight or freq:
        imports.insert(0, 'from statsmodels.stats.weightstats import DescrStatsW')
    base = _corr_lines(cols, weight, freq, pairwise)
    names = f'names = {J(cols)}'
    corr_text = 'f"{Z[i, j]:.2f}".replace("-", "−")'
    corr = [head(imports), *base, names, 'Z = R',
            *_heatmap_lines(p, 'Color Map On Correlations', -1, 1, DIVERGING, 'blue for −1, red for +1', corr_text)]
    pv = [head(['from scipy import stats', *imports]), *base,
          'with np.errstate(divide="ignore", invalid="ignore"):',
          '    t = R * np.sqrt((N - 2) / (1 - R ** 2))',
          '    Z = np.where(np.abs(R) >= 1, 0.0, 2 * stats.t.sf(np.abs(t), N - 2))   # t tests of zero correlation on N − 2 DF',
          'Z = np.where(N > 2, Z, np.nan)',
          'np.fill_diagonal(Z, np.nan)   # none on the diagonal',
          names,
          f'alpha = {alpha!r}',
          '',
          'def fmt_p(v):   # a p-value as the page writes it: four decimals, <.0001, a star below alpha',
          '    return "." if np.isnan(v) else ("<.0001" if v < 0.0001 else f"{v:.4f}") + ("*" if v < alpha else "")',
          '',
          *_heatmap_lines(p, 'Color Map On p-values', 0, 1, [RED, DIVERGING[1], BLUE], 'red for p = 0, blue for p = 1', '"" if i == j else fmt_p(Z[i, j])')]
    cl = [head(['from scipy.cluster.hierarchy import leaves_list, linkage', 'from scipy.spatial.distance import squareform', *imports]), *base, names,
          'D = np.clip(1 - np.nan_to_num(R), 0, 2)   # the columns\' distances: 1 − r',
          'np.fill_diagonal(D, 0)',
          'order = leaves_list(linkage(squareform((D + D.T) / 2, checks=False), "average")) if len(R) >= 3 else np.arange(len(R))   # similar columns together: average linkage',
          'Z, names = R[np.ix_(order, order)], [names[k] for k in order]',
          *_heatmap_lines(p, 'Cluster the Correlations', -1, 1, DIVERGING, 'blue for −1, red for +1', corr_text)]
    return {'cm_corr_code': '\n'.join(corr), 'cm_p_code': '\n'.join(pv), 'cm_cluster_code': '\n'.join(cl)}


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
def mv_nonparametric(table, columns, rows=None, measure='spearman', weight=None, freq=None, where=None, table_name='data'):
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
    code = '\n'.join([_head(table, rows, where, table_name, ['from scipy import stats']),
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
def mv_distance(table, columns, rows=None, weight=None, freq=None, method='auto', where=None, table_name='data'):
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
    c = [_head(table, rows, where, table_name, ['from statsmodels.stats.dist_dependence_measures import distance_covariance_test, distance_statistics'])]
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
def mv_outliers(table, columns, rows=None, alpha=0.05, where=None, table_name='data'):
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
    code = '\n'.join([_head(table, rows, where, table_name, ['from scipy import stats']),
                      f'X = df[{_cols_expr(cols)}].dropna(); n, p = X.shape',
                      'S = np.cov(X, rowvar=False); e = (X - X.mean()).to_numpy()',
                      'M2 = np.einsum("ij,jk,ik->i", e, np.linalg.pinv(S), e)   # squared Mahalanobis distance = T²',
                      'J = np.sqrt((n - 2) * n**2 / (n - 1)**3 * M2 / (1 - n * M2 / (n - 1)**2))   # jackknife distance',
                      f'ucl_t2 = (n - 1)**2 / n * stats.beta.ppf({1 - alpha:g}, p / 2, (n - p - 1) / 2)',
                      'print(np.sqrt(M2)[:5], J[:5], ucl_t2)'])
    out = {'rows': df.index.to_numpy(), 'mahal': M, 'jack': Jd, 't2': M2, 'n': n, 'p': p, 'alpha': alpha,
           'ucl_mahal': ucl_m, 'ucl_jack': ucl_j, 'ucl_t2': ucl_t2, 'code': code}
    fit = [f'X = df[{_cols_expr(cols)}].dropna(); n, p = X.shape   # the rows with every column',
           'e = (X - X.mean()).to_numpy()',
           'M2 = np.einsum("ij,jk,ik->i", e, np.linalg.pinv(np.cov(X, rowvar=False).reshape(p, p)), e)   # T², the squared Mahalanobis distance',
           f'ucl_t2 = (n - 1) ** 2 / n * stats.beta.ppf({1 - alpha!r}, p / 2, (n - p - 1) / 2)   # its upper control limit at α = {alpha:g} (Mason and Young 2002)']
    kinds = {'mahal': ('Mahalanobis Distances', 'Mahalanobis Distance',
                       ['d, ucl = np.sqrt(M2), np.sqrt(ucl_t2)']),
             'jack': ('Jackknife Distances', 'Jackknife Distance',
                      ['c = (n - 2) * n ** 2 / (n - 1) ** 3   # each row left out of its own mean and covariance',
                       'with np.errstate(divide="ignore", invalid="ignore"):',
                       '    den = 1 - n * M2 / (n - 1) ** 2',
                       '    d = np.sqrt(np.where(den > 0, c * M2 / den, np.nan))',
                       '    den = 1 - n * ucl_t2 / (n - 1) ** 2',
                       '    ucl = np.sqrt(c * ucl_t2 / den) if den > 0 else None']),
             't2': ('T²', 'T²', ['d, ucl = M2, ucl_t2'])}
    for key, (title, ytitle, lines) in kinds.items():
        out[f'{key}_code'] = '\n'.join([_plot_head(table, rows, where, table_name, ['from scipy import stats']), *fit, *lines,
                                        *_row_plot_lines('X.index + 1', 'd', 'ucl', 'UCL', ytitle, title, 560, 250)])
    return out


def _row_plot_lines(x, y, limit, label, ytitle, title, w, h, limit_text=None):
    """Lines that draw one value per row against the row number, as the
    page's plots of distances: a dashed red limit with its value at the right."""
    L = []
    if limit:
        L += FMT_DEF
    L += [_fig(w, h), f'ax.scatter({x}, {y}, s={_area(5)}, color="{BASE}")']
    if limit:
        text = limit_text or f'f"{label} {{fmt({limit}, 5)}}"'
        L += [f'if {limit} is not None and np.isfinite({limit}):',
              f'    ax.axhline({limit}, color="{RED}", linewidth={_lw(1.2)}, linestyle="--")',
              f'    ax.text(1, {limit}, {text}, transform=ax.get_yaxis_transform(), ha="right", va="bottom", fontsize=7, color="{RED}")']
    L += ['ax.set_ylim(bottom=0)', 'ax.set_xlabel("Row Number")', f'ax.set_ylabel({J(ytitle)})', f'ax.set_title({J(title)})', 'plt.show()']
    return L


# ---- Multivariate: item reliability ----------------------------------------------------------

def _alpha(S):
    k = S.shape[0]
    if k < 2:
        return float('nan')
    v = np.trace(S) / k
    c = (S.sum() - np.trace(S)) / (k * (k - 1))
    return float(k * c / (v + (k - 1) * c))


@api('multivariate.reliability')
def mv_reliability(table, columns, rows=None, weight=None, freq=None, where=None, table_name='data'):
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
    code = '\n'.join([_head(table, rows, where, table_name), f'X = df[{_cols_expr(cols)}].dropna(); k = X.shape[1]',
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
def mv_icc(table, columns, rows=None, weight=None, freq=None, alpha=0.05, where=None, table_name='data'):
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
    c = [_head(table, rows, where, table_name, ['from scipy import stats'])]
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
def mv_kendall_w(table, columns, rows=None, weight=None, freq=None, where=None, table_name='data'):
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
    c = [_head(table, rows, where, table_name, ['from scipy import stats']),
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
            gamma=None, kaiser=True, alpha=0.05, plot=None, where=None, table_name='data'):
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
        _head(table, rows, where, table_name, ['from statsmodels.multivariate.pca import PCA']),
        f'X = df[{_cols_expr(cols)}].dropna(); n = len(X)',
        f'pc = PCA(X, {scale_line}, normalize=False, method="eig")',
        f'eig = pc.eigenvals / {divisor}   # the eigenvalues as JMP scales them (statsmodels standardizes with the n divisor)',
        'print(eig, 100 * eig / eig.sum())',
        'print(pc.eigenvecs)   # eigenvectors (the sign of each is arbitrary)',
    ] + (['print(pc.eigenvecs * np.sqrt(eig.to_numpy()))   # loadings: correlations of variables and components'] if on == 'correlations' else []))
    if plot is not None:
        a = min(int((plot or {}).get('x', 0) or 0), k - 1)
        b = min(max(int((plot or {}).get('y', 1) if (plot or {}).get('y') is not None else 1), 0), k - 1)
        rot = (rotation, out['rotation']['k'], gamma, kaiser) if 'rotation' in out else None
        out.update(_pca_codes(lambda imports: _plot_head(table, rows, where, table_name, imports), cols, weight, freq, on, a, b,
                              bool((plot or {}).get('ellipse')), rot))
    return out


PCA_ON = {'correlations': 'Correlations', 'covariances': 'Covariances', 'unscaled': 'Unscaled'}


@api('pca.save')
def pca_save(table, columns, rows=None, weight=None, freq=None, on='correlations', n=None, what='components', rotation=None,
             n_rotate=None, gamma=None, kaiser=True, where=None):
    """Save Principal Components (the first n) and Save Rotated Components as
    formula columns. A score is linear in the columns: Prin j = Σ v_ij z_i,
    z_i the column centred by the fitted mean (and on correlations divided
    by the fitted standard deviation; unscaled: the column itself), so the
    formula gives the report's scores on its rows and scores every other
    row whose columns are present. A rotated component is the standardized
    component scores times the rotation: Σ_i (V D^-1/2 T)_ij z_i."""
    cols = list(columns)
    r = pca_fit(table, cols, rows, weight, freq, on, rotation if what == 'rotated' else None, n_rotate, gamma, kaiser)
    if 'error' in r:
        return r
    center, scale = np.asarray(r['center'], float), np.asarray(r['scale'], float)
    z = [_fz(c, center[i], scale[i]) for i, c in enumerate(cols)]
    V = np.asarray(r['eigenvectors'], float)
    vals = np.asarray(r['eigenvalues'], float)
    how = {'correlations': 'the columns standardized by the fitted means and standard deviations',
           'covariances': 'the columns centred by the fitted means', 'unscaled': 'the columns as they are'}[on]
    out = []
    if what == 'rotated':
        R = r.get('rotation')
        if not R:
            return {'error': 'choose a rotation first: Factor Rotation…'}
        kr = R['k']
        if np.any(vals[:kr] <= 0):
            return {'error': 'a rotated component has a zero eigenvalue: its standardized scores are not defined'}
        W = V[:, :kr] / np.sqrt(vals[:kr])[None, :] @ np.asarray(R['T'], float)
        for j in range(kr):
            out.append({'name': f'Rotated Prin{j + 1}', 'formula': _fguard(table, _flin(W[:, j], z), where),
                        'notes': f'{R["label"]} rotation of {kr} principal components on {PCA_ON[on]} (standardized component scores times the rotation), a formula of {how}{_by_words(table, where)}'})
    else:
        k = len(vals) if n is None else max(1, min(int(n), len(vals)))
        for j in range(k):
            out.append({'name': f'Prin{j + 1}', 'formula': _fguard(table, _flin(V[:, j], z), where),
                        'notes': f'principal component {j + 1} on {PCA_ON[on]}: the eigenvector times {how}{_by_words(table, where)}'})
    return {'columns': out, 'n_rows': r['n_rows']}


def _weights_lines(cols, weight, freq, what='the rows with every column'):
    """Lines that give X (numpy), the report's rows of the columns, and w,
    their weights (Weight times Freq; ones without them)."""
    wexpr = _weight_code(weight, freq)
    if wexpr:
        return [f'X = df[{_cols_expr(cols)}]', f'w = {wexpr}   # {"Weight times Freq" if weight and freq else "Weight" if weight else "Freq"}',
                f'ok = X.notna().all(axis=1) & w.gt(0)   # {what} and a positive weight',
                'X, w = X[ok], w[ok].to_numpy()']
    return [f'X = df[{_cols_expr(cols)}].dropna()   # {what}', 'w = np.ones(len(X))']


def _pca_lines(cols, weight, freq, on):
    """Lines that find the principal components as pca.fit does: eig (the
    eigenvalues), V (the eigenvectors), scores and loadings."""
    L = _weights_lines(cols, weight, freq) + ['X = X.to_numpy()']
    if on == 'correlations':
        L += ['center = (w[:, None] * X).sum(0) / w.sum()   # the means',
              'scale = np.sqrt((w[:, None] * (X - center) ** 2).sum(0) / (w.sum() - 1))   # the standard deviations',
              'Z = (X - center) / scale   # on correlations: each column standardized',
              'denom = w.sum() - 1']
    elif on == 'covariances':
        L += ['center = (w[:, None] * X).sum(0) / w.sum()   # the means', 'Z = X - center   # on covariances: each column centred',
              'denom = w.sum() - 1']
    else:
        L += ['Z = X   # unscaled: the cross products X′X/n', 'denom = w.sum()']
    L += ['M = Z * np.sqrt(w)[:, None]',
          'pc = PCA(M, standardize=False, demean=False, normalize=False, method="eig")',
          'eig = np.asarray(pc.eigenvals) / denom   # the eigenvalues, as the report scales them',
          'eig = np.where(eig > 1e-12 * max(1.0, abs(eig[0])), eig, 0.0)   # rounding noise as 0',
          'V = np.asarray(pc.eigenvecs)',
          'V = V * np.sign(V[np.abs(V).argmax(axis=0), np.arange(V.shape[1])])   # each eigenvector\'s largest entry positive, as the report makes it',
          'scores = Z @ V   # Prin1, Prin2, ...']
    if on == 'correlations':
        L.append('loadings = V * np.sqrt(eig)   # the correlations of the columns with the components')
    else:
        L += ['C = M.T @ M / denom', 'loadings = V * np.sqrt(eig) / np.sqrt(np.diag(C))[:, None]   # the correlations of the columns with the components']
    return L


def _rotate_lines(method, gamma, kaiser, p, k):
    """Lines that rotate the loadings A (p x k) as rotate() does: L, the
    rotated loadings, and T, the rotation (statsmodels' factor_rotation)."""
    if not method or method == 'none' or k < 2:
        return ['L, T = A.copy(), np.eye(A.shape[1])   # no rotation']
    L = []
    if kaiser:
        L += ['h = np.sqrt((A ** 2).sum(axis=1)); h = np.where(h > 0, h, 1.0)   # Kaiser\'s normalization: each column\'s loadings to unit length',
              'An = A / h[:, None]']
    else:
        L += ['h = np.ones(len(A)); An = A']
    ortho = {'varimax': (1.0, 'varimax: orthomax with γ = 1'), 'quartimax': (0.0, 'quartimax: orthomax with γ = 0'),
             'biquartimax': (0.5, 'biquartimax: orthomax with γ = 1/2'), 'equamax': (k / 2.0, f'equamax: orthomax with γ = k/2 ({k} factors)'),
             'parsimax': (p * (k - 1) / (p + k - 2), f'parsimax: orthomax with γ = p(k − 1)/(p + k − 2) ({p} columns, {k} factors)'),
             'factorparsimax': (float(p), f'factor parsimax: orthomax with γ = p ({p} columns)'),
             'orthomax': (1.0 if gamma is None else float(gamma), 'orthomax')}
    obl = {'quartimin': (0.0, 'quartimin: oblimin with γ = 0'), 'biquartimin': (0.5, 'biquartimin: oblimin with γ = 1/2'),
           'covarimin': (1.0, 'covarimin: oblimin with γ = 1'), 'oblimin': (0.0 if gamma is None else float(gamma), 'oblimin')}
    cf = {'obvarimax': (1.0 / p, 'obvarimax: Crawford-Ferguson with κ = 1/p'), 'obequamax': (k / (2.0 * p), 'obequamax: Crawford-Ferguson with κ = k/(2p)'),
          'obparsimax': ((k - 1) / (p + k - 2), 'obparsimax: Crawford-Ferguson with κ = (k − 1)/(p + k − 2)'), 'obfactorparsimax': (1.0, 'obfactorparsimax: Crawford-Ferguson with κ = 1')}
    if method in ortho:
        g, why = ortho[method]
        L.append(f'L, T = rotate_factors(An, "orthomax", {g!r})   # {why}')
    elif method in obl:
        g, why = obl[method]
        L.append(f'L, T = rotate_factors(An, "oblimin", {g!r}, "oblique")   # {why}')
    elif method in cf:
        g, why = cf[method]
        L.append(f'L, T = rotate_factors(An, "CF", {g!r}, "oblique")   # {why}')
    elif method == 'promax':
        L += ['V, _ = rotate_factors(An, "orthomax", 1.0)   # promax (Hendrickson and White, power 3, as SAS computes it): varimax,',
              'H = V * np.abs(V) ** 2   # the target: the varimax loadings cubed, their signs kept,',
              'U = np.linalg.lstsq(An, H, rcond=None)[0]   # the least-squares map to it,',
              'U = U @ np.diag(np.sqrt(np.diag(np.linalg.inv(U.T @ U))))   # scaled so that the factors\' correlations have a unit diagonal',
              'L, T = An @ U, np.linalg.inv(U).T']
    else:
        return ['L, T = A.copy(), np.eye(A.shape[1])   # no rotation']
    L += ['L = L * h[:, None]   # scaled back',
          'o = np.argsort(-(L * L).sum(axis=0)); L, T = L[:, o], T[:, o]   # the factors in the order of the variance they explain',
          's = np.where(L.sum(axis=0) < 0, -1.0, 1.0); L, T = L * s, T * s   # each factor\'s loadings summing to a positive number']
    return L


def _zero_lines():
    """The zero lines of a graph whose axes have them (the page's grid colour)."""
    return [f'ax.axhline(0, color="{GRID}", linewidth={_lw(1)}, zorder=0)', f'ax.axvline(0, color="{GRID}", linewidth={_lw(1)}, zorder=0)']


def _loading_plot_lines(Lx, Ly, xname, yname, unit, w, h, title='Loading Plot', many=False):
    """Lines that draw the page's loading plot of the columns: a ray to each,
    a red diamond at its end with its name, the unit circle."""
    L = [_fig(w, h), f'lx, ly = {Lx}, {Ly}',
         'for xi, yi in zip(lx, ly):',
         f'    ax.plot([0, xi], [0, yi], color="{MUTED}", linewidth={_lw(1)})   # a ray from the origin to each column',
         f'ax.scatter(lx, ly, s={_area(7)}, marker="D", color="{RED}", zorder=3)']
    if not many:
        L += ['for name, xi, yi in zip(names, lx, ly):', '    ax.text(xi, yi, name, ha="center", va="bottom", fontsize=7)']
    if unit:
        L += [f'ax.add_patch(plt.Circle((0, 0), 1, fill=False, color="{GRID}", linewidth={_lw(1)}))   # the unit circle',
              'ax.set_xlim(-1.15, 1.15)', 'ax.set_ylim(-1.15, 1.15)']
    L += _zero_lines() + ['ax.set_aspect("equal")', f'ax.set_xlabel({J(xname)})', f'ax.set_ylabel({J(yname)})', f'ax.set_title({J(title)})', 'plt.show()']
    return L


def _pca_codes(head, cols, weight, freq, on, a, b, ellipse, rot):
    """The code of Principal Components' graphs: the eigenvalues as bars and
    the scree plot, the score plot (the Summary Plots' and the Score Plot's),
    the loading plots, the biplot and the rotated components' loading plot."""
    imp = ['from statsmodels.multivariate.pca import PCA']
    fit = _pca_lines(cols, weight, freq, on) + [f'names = {J(cols)}']
    one = on == 'correlations'
    ref = [f'ax.axhline(1, color="{RED}", linewidth={_lw(1)}, linestyle=":")   # an eigenvalue of 1'] if one else []
    xs = 'np.arange(1, len(eig) + 1)'
    out = {}
    out['eigen_code'] = '\n'.join([head(imp), *fit, _fig(250, 240), f'ax.bar({xs}, eig, color="{BAR}")', *ref,
                                   f'ax.set_xticks({xs})', 'ax.set_ylim(bottom=0)', 'ax.set_xlabel("Number")', 'ax.set_ylabel("Eigenvalue")',
                                   'ax.set_title("Eigenvalues")', 'plt.show()'])
    out['scree_code'] = '\n'.join([head(imp), *fit, _fig(380, 260),
                                   f'ax.plot({xs}, eig, color="{BASE}", linewidth={_lw(1.5)}, marker="o", markersize={_msize(7)})', *ref,
                                   f'ax.set_xticks({xs})', 'ax.set_ylim(bottom=0)', 'ax.set_xlabel("Number of Components")', 'ax.set_ylabel("Eigenvalue")',
                                   'ax.set_title("Scree Plot")', 'plt.show()'])

    def score(w, h):
        L = [head(imp), *fit, f'x, y = scores[:, {a}], scores[:, {b}]   # Prin{a + 1} and Prin{b + 1}']
        if ellipse:
            L += ['', *ELLIPSE_DEF, '',
                  ('r = 0.0   # the same component on both axes' if a == b else 'r = np.corrcoef(x, y)[0, 1]'),
                  'ex, ey = ellipse(x.mean(), y.mean(), x.std(ddof=1), y.std(ddof=1), r, 0.95)   # Score Ellipses: 95% of a bivariate normal with the scores\' means, standard deviations and correlation']
        L += [_fig(w, h), f'ax.scatter(x, y, s={_area(6)}, color="{BASE}")']
        if ellipse:
            L.append(f'ax.plot(ex, ey, color="{RED}", linewidth={_lw(1)})')
        L += _zero_lines() + [f'ax.set_xlabel("Prin{a + 1}")', f'ax.set_ylabel("Prin{b + 1}")', 'ax.set_title("Score Plot")', 'plt.show()']
        return '\n'.join(L)
    out['score_summary_code'] = score(300, 280)
    out['score_code'] = score(440, 380)
    many = len(cols) > 30
    unit = on != 'unscaled'
    out['loading_summary_code'] = '\n'.join([head(imp), *fit, *_loading_plot_lines(f'loadings[:, {a}]', f'loadings[:, {b}]', f'Prin{a + 1}', f'Prin{b + 1}', unit, 300, 280, many=many)])
    out['loading_code'] = '\n'.join([head(imp), *fit, *_loading_plot_lines(f'loadings[:, {a}]', f'loadings[:, {b}]', f'Prin{a + 1}', f'Prin{b + 1}', unit, 420, 380, many=many)])
    out['biplot_code'] = '\n'.join([head(imp), *fit, f'x, y = scores[:, {a}], scores[:, {b}]',
                                    f'la, lb = loadings[:, {a}], loadings[:, {b}]',
                                    'lmax = max(np.abs(la).max(), np.abs(lb).max())',
                                    's = 0.85 * max(np.abs(x).max(), np.abs(y).max()) / lmax if lmax > 0 else 1.0   # the rays scaled to the spread of the scores',
                                    _fig(460, 400), f'ax.scatter(x, y, s={_area(5)}, color="{BASE}")',
                                    'for name, xi, yi in zip(names, s * la, s * lb):',
                                    f'    ax.plot([0, xi], [0, yi], color="{RED}", linewidth={_lw(1.2)})',
                                    '    ax.text(xi, yi, name, ha="center", va="bottom", fontsize=7.5)',
                                    *_zero_lines(), f'ax.set_xlabel("Prin{a + 1}")', f'ax.set_ylabel("Prin{b + 1}")', 'ax.set_title("Biplot")', 'plt.show()'])
    if rot:
        method, kr, gamma, kaiser = rot
        out['rotated_code'] = '\n'.join([head(imp + ['from statsmodels.multivariate.factor_rotation import rotate_factors']), *fit,
                                         f'A = loadings[:, :{kr}]   # the first {kr} components\' loadings, rotated',
                                         *_rotate_lines(method, gamma, kaiser, len(cols), kr),
                                         *_loading_plot_lines('L[:, 0]', 'L[:, 1]', 'Factor 1', 'Factor 2', True, 380, 340, many=many)])
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
def factor_eigen(table, columns, rows=None, weight=None, freq=None, where=None, table_name='data'):
    """The first part of the Factor Analysis report: the eigenvalues of the
    correlation matrix, the default number of factors, sphericity, KMO."""
    _, out = _fa_prelim(table, columns, rows, weight, freq)
    out['code'] = '\n'.join([_head(table, rows, where, table_name), f'X = df[{_cols_expr(list(columns))}].dropna()',
                             'R = X.corr().to_numpy(); ev = np.sort(np.linalg.eigvalsh(R))[::-1]',
                             'print(ev, 100 * ev / ev.sum())   # eigenvalues; the default number of factors is the count of those >= 1',
                             'p, n = R.shape[0], len(X); chi2 = -(n - 1 - (2 * p + 5) / 6) * np.log(np.linalg.det(R))   # Bartlett\'s sphericity, p(p-1)/2 df'])
    if 'error' not in out:
        out['scree_code'] = '\n'.join([_plot_head(table, rows, where, table_name), *_fa_corr_lines(list(columns), weight, freq),
                                       'eig = np.sort(np.linalg.eigvalsh(R))[::-1]   # the eigenvalues of the correlation matrix',
                                       _fig(380, 260), 'xs = np.arange(1, len(eig) + 1)',
                                       f'ax.plot(xs, eig, color="{BASE}", linewidth={_lw(1.5)}, marker="o", markersize={_msize(7)})',
                                       f'ax.axhline(1, color="{RED}", linewidth={_lw(1)}, linestyle=":")   # an eigenvalue of 1',
                                       'ax.set_xticks(xs)', 'ax.set_ylim(bottom=0)', 'ax.set_xlabel("Number of Components")', 'ax.set_ylabel("Eigenvalue")',
                                       'ax.set_title("Scree Plot")', 'plt.show()'])
    return out


def _fa_corr_lines(cols, weight, freq):
    """Lines that give X, w and R, the (weighted) correlations of the rows with
    every column, and nobs, as Factor Analysis computes them."""
    return _weights_lines(cols, weight, freq) + [
        f'nobs = {"float(df.loc[X.index, " + J(freq) + "].sum())" if freq else "len(X)"}   # the observations',
        'X = X.to_numpy()',
        'm = (w[:, None] * X).sum(0) / w.sum()',
        'S = (w[:, None] * (X - m)).T @ (X - m) / (w.sum() - 1)   # the covariances',
        'd = np.sqrt(np.diag(S)); R = S / np.outer(d, d); np.fill_diagonal(R, 1.0)   # the correlations']


@api('factor.fit')
def factor_fit(table, columns, rows=None, weight=None, freq=None, n_factors=None, method='ml', prior='smc',
               rotation='varimax', gamma=None, kaiser=True, plot=None, where=None, table_name='data'):
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
    A = np.real(np.asarray(res.loadings_no_rot))   # maximum likelihood gives them as complex numbers with no imaginary part
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
    s_center, s_scale = X.mean(0), X.std(0, ddof=1)
    Zs = (X - s_center) / s_scale
    scores = Zs @ coef
    out.update({'unrotated': _mat(A), 'rotated': _mat(L), 'rotation_matrix': _mat(T), 'phi': _mat(Phi), 'oblique': bool(oblique),
                'structure': _mat(L @ Phi) if oblique else None, 'communality': comm, 'uniqueness': uniq,
                'rotation': rotation or 'none', 'rotation_label': ROTATIONS.get(rotation, ('None', ''))[0] if rotation else 'None',
                'order': _sort_order(L), 'order_unrotated': _sort_order(A), 'score_coef': _mat(coef),
                'scores': _mat(scores), 'rows': df.index.to_numpy(), 'kaiser': bool(kaiser),
                'score_center': s_center, 'score_scale': s_scale})
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
    out['code'] = _fa_stats_code(lambda imports: _head(table, rows, where, table_name, imports), cols, weight, freq, k, n_factors, method, prior,
                                 rotation, gamma, kaiser)
    if plot is not None:
        out.update(_fa_codes(lambda imports: _plot_head(table, rows, where, table_name, imports), cols, weight, freq, k, n_factors, method, prior,
                             rotation, gamma, kaiser, plot))
    return out


@api('factor.save')
def factor_save(table, columns, rows=None, weight=None, freq=None, n_factors=None, method='ml', prior='smc',
                rotation='varimax', gamma=None, kaiser=True, where=None):
    """Save Rotated Components: each factor's score as a formula column,
    Thurstone's regression score Σ_i b_ij (x_i − mean_i)/sd_i with the score
    coefficients b and the means and standard deviations of the report's
    rows, as the report computes the scores; every row whose columns are
    present gets one."""
    cols = list(columns)
    r = factor_fit(table, cols, rows, weight, freq, n_factors, method, prior, rotation, gamma, kaiser)
    if 'error' in r:
        return r
    B = np.asarray(r['score_coef'], float)
    z = [_fz(c, r['score_center'][i], r['score_scale'][i]) for i, c in enumerate(cols)]
    label = r['rotation_label']
    out = [{'name': f'Factor{j + 1}', 'formula': _fguard(table, _flin(B[:, j], z), where),
            'notes': f'factor score (Thurstone\'s regression method), {r["k"]} factors, {FA_METHOD_LABEL.get(r["method"], r["method"])}, {label} rotation: a formula of the columns standardized by the report\'s means and standard deviations{_by_words(table, where)}'}
           for j in range(r['k'])]
    return {'columns': out, 'n_rows': r['n_rows']}


FA_METHOD_LABEL = {'ml': 'Maximum Likelihood', 'pa': 'Principal Axis'}


def _fa_fit_lines(cols, weight, freq, k, n_factors, method, prior, rotation, gamma, kaiser):
    """Lines that fit the factor model as factor.fit does: R from the
    weighted covariances, k, statsmodels' Factor, A (the unrotated loadings,
    signs as the report makes them) and L, T (the report's rotation)."""
    p = len(cols)
    kline = [f'k = {k}   # the number of factors (Model Launch)'] if n_factors else [
        'k = max(1, int((np.linalg.eigvalsh(R) >= 1 - 1e-12).sum()))   # the number of factors: the eigenvalues of at least 1',
        f'k = min(k, {p - 1 if method == "ml" else p})']
    return [*_fa_corr_lines(cols, weight, freq), *kline,
            f'res = Factor(corr=R, n_factor=k, method={method!r}, smc={prior == "smc"}, nobs=int(round(nobs)), endog_names={J(cols)}).fit()',
            'A = np.real(np.asarray(res.loadings_no_rot))   # (maximum likelihood gives them as complex numbers with no imaginary part)',
            'A = A * np.where(A.sum(axis=0) < 0, -1.0, 1.0)   # each factor\'s loadings summing to a positive number, as the report makes them',
            *_rotate_lines(rotation if k > 1 else None, gamma, kaiser, p, k),
            f'names = {J(cols)}']


FA_IMPORTS = ['from statsmodels.multivariate.factor import Factor', 'from statsmodels.multivariate.factor_rotation import rotate_factors']


def _fa_stats_code(head, cols, weight, freq, k, n_factors, method, prior, rotation, gamma, kaiser):
    """The code of a factor fit's report: the weighted correlations, the fit,
    the report's rotation with its normalization, the communalities, the
    variance explained, the test of enough factors and the factor scores."""
    oblique = ROTATIONS.get(rotation, ('', 'orthogonal'))[1] == 'oblique' and k > 1
    L = [head(['from scipy import stats', *FA_IMPORTS]), *_fa_fit_lines(cols, weight, freq, k, n_factors, method, prior, rotation, gamma, kaiser),
         'p = len(names)',
         'print(pd.DataFrame(L, index=names, columns=[f"Factor {j + 1}" for j in range(k)]))   # the (rotated) factor loadings',
         'comm = (A ** 2).sum(axis=1)   # Final Communality Estimates, of the unrotated fit',
         f'uniq = {"np.asarray(res.uniqueness)   # the uniquenesses maximum likelihood estimates" if method == "ml" else "1 - comm   # the uniquenesses"}',
         'print(pd.DataFrame({"Communality": comm, "Uniqueness": uniq}, index=names))',
         'Phi = T.T @ T   # the factors\' correlations (the identity for an orthogonal rotation)']
    if oblique:
        L += ['print(pd.DataFrame(Phi, index=range(1, k + 1), columns=range(1, k + 1)))   # Interfactor Correlations',
              'variance = ((L @ Phi) ** 2).sum(axis=0)   # the Variance Explained by Each Factor Ignoring Other Factors: the squared structure']
    else:
        L += ['variance = (L ** 2).sum(axis=0)   # the Variance Explained by Each Factor']
    L.append(f'print(pd.DataFrame({{"Variance": variance, "Percent": 100 * variance / p{", " + chr(34) + "Cum Percent" + chr(34) + ": 100 * np.cumsum(variance) / p" if not oblique else ""}}}, index=[f"Factor {{j + 1}}" for j in range(k)]))')
    if method == 'ml':
        L += ['Sig = A @ A.T + np.diag(uniq)   # the correlations the factors imply',
              'crit = np.log(np.linalg.det(Sig)) - np.log(np.linalg.det(R)) + np.trace(R @ np.linalg.inv(Sig)) - p   # the ML discrepancy',
              'dfm = ((p - k) ** 2 - (p + k)) / 2',
              'chi2 = (nobs - 1 - (2 * p + 5) / 6 - 2 * k / 3) * crit   # Bartlett\'s corrected chi-square',
              'print("H0: the factors are sufficient", chi2, dfm, stats.chi2.sf(chi2, dfm) if dfm > 0 else None)']
    L += ['res.loadings, res.rotation_matrix = L, T',
          'coef = np.asarray(res.factor_score_params(method="regression"))   # Thurstone\'s regression scores (Save Rotated Components)',
          'scores = (X - X.mean(0)) / X.std(0, ddof=1) @ coef',
          'print(scores[:5])']
    return '\n'.join(L)

def _fa_codes(head, cols, weight, freq, k, n_factors, method, prior, rotation, gamma, kaiser, plot):
    """The code of a factor fit's loading plot and score plot, the fit made as
    factor.fit makes it."""
    p = len(cols)
    a = min(int(plot.get('x', 0) or 0), k - 1)
    b = min(int(plot.get('y', 1) if plot.get('y') is not None else 1), k - 1)
    imp = FA_IMPORTS
    fit = _fa_fit_lines(cols, weight, freq, k, n_factors, method, prior, rotation, gamma, kaiser)
    out = {}
    if k >= 2:
        out['loading_code'] = '\n'.join([head(imp), *fit, *_loading_plot_lines(f'L[:, {a}]', f'L[:, {b}]', f'Factor {a + 1}', f'Factor {b + 1}', True, 380, 340, many=p > 30)])
    bs = b if k > 1 else 0
    out['score_code'] = '\n'.join([head(imp), *fit,
                                   'res.loadings, res.rotation_matrix = L, T',
                                   'coef = np.asarray(res.factor_score_params(method="regression"))   # Thurstone\'s regression scores, as the report',
                                   'scores = (X - X.mean(0)) / X.std(0, ddof=1) @ coef',
                                   f'x = scores[:, {a}]', f'y = scores[:, {bs}]' if k > 1 else 'y = np.zeros(len(x))   # one factor',
                                   _fig(420, 360), f'ax.scatter(x, y, s={_area(6)}, color="{BASE}")', *_zero_lines(),
                                   f'ax.set_xlabel("Factor {a + 1}")', f'ax.set_ylabel({J(f"Factor {bs + 1}" if k > 1 else "")})', 'ax.set_title("Score Plot")', 'plt.show()'])
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


# The sets of a Validation column, as the predictive platforms read one
# (predictive.prepare): 0 or Training, 1 or Validation, 2 or Test.
SETS = ('Training', 'Validation', 'Test')
SET_NAMES = {'training': 0, 'train': 0, 'validation': 1, 'valid': 1, 'test': 2}


def _sets_of(table, validation, index):
    """Each row's set from a Validation column: 0 Training, 1 Validation,
    2 Test (the numbers or the words); -1 where it has no value. A column
    with other values (k folds) is refused: Discriminant holds rows back,
    it does not cross-validate."""
    m = data.meta(table, validation)
    raw = data.raw(table, validation, index)
    if m.get('dataType') == 'numeric':
        v = np.asarray(raw, dtype=float)
        ok = np.isfinite(v)
        vals = sorted(set(np.unique(v[ok]).tolist()))
        bad = [x for x in vals if x not in (0.0, 1.0, 2.0)]
        if bad:
            folds = ' (a column of more than three values holds k folds, which Discriminant does not take)' if len(vals) > 3 else ''
            raise ValueError(f'{validation}: a Validation column holds 0 (training), 1 (validation) and 2 (test); it has {", ".join(_lvtext(b) for b in bad[:5])}{folds}')
        return np.where(ok, v, -1).astype(int)
    out = []
    for vv in raw:
        if vv is None or (isinstance(vv, float) and math.isnan(vv)):
            out.append(-1)
            continue
        k = SET_NAMES.get(str(vv).strip().lower())
        if k is None:
            raise ValueError(f'{validation}: a Validation column holds Training, Validation and Test (or 0, 1, 2); it has {vv}')
        out.append(k)
    return np.array(out, dtype=int)


def _disc_core(table, ycols, x, rows, weight, freq, method, lam, gam, priors, prior_values, validation):
    """The discriminant fit on the training rows (every row without a
    Validation column) and the classification of every row: the groups'
    means and covariances, the pooled within covariance, each group's
    inverse covariance and log determinant for the method, the priors,
    SqDist and the posterior probabilities."""
    df, w, f = _cat_frame(table, ycols, x, rows, weight, freq)
    notes = []
    if validation:
        sets = _sets_of(table, validation, df.index.to_numpy())
        if (sets < 0).any():
            notes.append(f'{int((sets < 0).sum())} rows with no {validation} value are left out.')
        keep = sets >= 0
        df, w, f, sets = df[keep], w[keep], f[keep], sets[keep]
        if not (sets == 0).any():
            raise ValueError(f'{validation} leaves no training rows (0 or Training)')
    else:
        sets = np.zeros(len(df), dtype=int)
    g = df[x]
    levels_all = list(g.cat.categories) if hasattr(g, 'cat') else sorted(g.unique())
    tr = sets == 0
    present = [lv for lv in levels_all if (g[tr] == lv).any()]
    if len(present) < 2:
        raise ValueError('the categories column needs at least two levels with data' + (' in the training rows' if validation else ''))
    known = g.isin(present).to_numpy()
    if not known.all():
        notes.append(f'{int((~known).sum())} rows of a category the training rows do not have are left out (the model has no mean for it).')
        df, w, f, sets = df[known], w[known], f[known], sets[known]
        g = df[x]
        tr = sets == 0
    Y = df[ycols].to_numpy(float)
    n, p = Y.shape
    T = len(present)
    code_idx = np.array([present.index(v) for v in g], int)
    Yt, ct, wt = Y[tr], code_idx[tr], w[tr]
    sw = float(wt.sum())
    means, covs, sws = [], [], []
    E = np.zeros((p, p))
    for t in range(T):
        m_ = ct == t
        wg = wt[m_]
        swt = float(wg.sum())
        mt = (wg[:, None] * Yt[m_]).sum(0) / swt
        Ct = Yt[m_] - mt
        Et = (wg[:, None] * Ct).T @ Ct
        E += Et
        covs.append(Et / (swt - 1) if swt > 1 else np.full((p, p), np.nan))
        means.append(mt)
        sws.append(swt)
    means = np.array(means)
    gm = (wt[:, None] * Yt).sum(0) / sw
    Sp = E / (sw - T)
    B = sum(sws[t] * np.outer(means[t] - gm, means[t] - gm) for t in range(T))
    # priors
    if priors == 'proportional':
        q = np.array(sws) / sw
    elif priors == 'other' and prior_values:
        q = np.array([float(prior_values.get(_pkey(lv), prior_values.get(str(lv), 0)) or 0) for lv in present])
        q = q / q.sum() if q.sum() > 0 else np.full(T, 1 / T)
    else:
        q = np.full(T, 1.0 / T)
    # the covariance of each group for the chosen method
    Sinv, logdets, Sigs = [], [], []
    if method == 'linear':
        Spi = np.linalg.pinv(Sp)
        Sinv = [Spi] * T
        logdets = [0.0] * T
        Sigs = [Sp] * T
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
            Sigs.append(Sig)
    D2 = np.empty((n, T))
    for t in range(T):
        e = Y - means[t]
        D2[:, t] = np.einsum('ij,jk,ik->i', e, Sinv[t], e)
    SqDist = D2 + np.array(logdets)[None, :] - 2 * np.log(q)[None, :]
    a = -0.5 * SqDist
    a = a - a.max(1, keepdims=True)
    P = np.exp(a)
    P = P / P.sum(1, keepdims=True)
    return {'weight': weight, 'df': df, 'w': w, 'f': f, 'sets': sets, 'tr': tr, 'present': present, 'levels_all': levels_all, 'Y': Y, 'n': n, 'p': p, 'T': T,
            'code_idx': code_idx, 'sw': sw, 'means': means, 'covs': covs, 'sws': sws, 'E': E, 'gm': gm, 'Sp': Sp, 'B': B, 'q': q,
            'Sinv': Sinv, 'Sigs': Sigs, 'logdets': logdets, 'SqDist': SqDist, 'P': P, 'notes': notes}


def _disc_set_summaries(C):
    """Score Summaries and confusion counts of each set present: the rows
    misclassified (by their weights), the entropy RSquare against the
    training shares of the groups, −2 log likelihood."""
    P, code_idx, w, sets, T = C['P'], C['code_idx'], C['w'], C['sets'], C['T']
    shares = np.array(C['sws']) / C['sw']
    pred = P.argmax(1)
    prob_act = P[np.arange(C['n']), code_idx]
    mis = pred != code_idx
    out, confs = [], []
    for k in range(3):
        m = sets == k
        if not m.any():
            continue
        wk = w[m]
        swk = float(wk.sum())
        ll = float(np.sum(wk * np.log(np.maximum(prob_act[m], 1e-300))))
        ll0 = float(np.sum(wk * np.log(shares[code_idx[m]])))
        out.append({'set': SETS[k], 'n_mis': float(np.sum(wk * mis[m])), 'pct_mis': 100 * float(np.sum(wk * mis[m])) / swk,
                    'entropy_r2': 1 - ll / ll0 if ll0 != 0 else None, 'm2ll': -2 * ll, 'n': swk})
        conf = np.zeros((T, T))
        np.add.at(conf, (code_idx[m], pred[m]), wk)
        confs.append({'set': SETS[k], 'matrix': _mat(conf)})
    return out, confs


def _disc_prepared(C, freq, ycols, labels):
    """The pieces predictive.report() reads (its ROC and lift curves): the
    groups as the response, each row's set, the frequencies."""
    from . import predictive
    P_ = predictive.Prepared()
    P_.kind = 'categorical'
    P_.index = C['df'].index.to_numpy()
    P_.target = C['code_idx']
    P_.levels = [_level_value(v) for v in C['present']]
    P_.labels = list(labels)
    P_.sets = C['sets']
    P_.w = C['w']
    P_.freq = C['f'] if freq else None
    P_.spec = {'weight': C.get('weight'), 'freq': freq}
    P_.features = list(ycols)
    return P_


@api('discriminant.fit')
def disc_fit(table, y, x, rows=None, weight=None, freq=None, method='linear', lam=0.5, gam=0.0,
             priors='equal', prior_values=None, alpha=0.05, plot=None, validation=None, curves=False, decision=False, where=None, table_name='data'):
    """Discriminant analysis as JMP reports it: squared distances, posterior
    probabilities and classification (linear: pooled covariance; quadratic:
    each group's; regularized: Friedman's compromise), the canonical
    analysis of the between and pooled within matrices, and the multivariate
    tests (statsmodels MANOVA). With a Validation column (JMP Pro) the model
    is fitted to the training rows and every row is scored: the Score
    Summaries and confusion counts of each set. curves: the ROC and lift
    curves of each set (predictive.report)."""
    ycols = list(y)
    try:
        C = _disc_core(table, ycols, x, rows, weight, freq, method, lam, gam, priors, prior_values, validation)
    except ValueError as e:
        return {'error': str(e)}
    df, w, sets, tr, present, levels_all = C['df'], C['w'], C['sets'], C['tr'], C['present'], C['levels_all']
    Y, n, p, T, code_idx, sw = C['Y'], C['n'], C['p'], C['T'], C['code_idx'], C['sw']
    means, covs, sws, E, gm, Sp, B, q = C['means'], C['covs'], C['sws'], C['E'], C['gm'], C['Sp'], C['B'], C['q']
    logdets, SqDist, P, notes = C['logdets'], C['SqDist'], C['P'], C['notes']
    nobs = _nobs(C['f'][tr], freq)
    pred = P.argmax(1)
    prob_act = P[np.arange(n), code_idx]
    mis = pred != code_idx
    with np.errstate(divide='ignore'):
        nll = -np.log(np.maximum(prob_act, 1e-300))
    summaries, confs = _disc_set_summaries(C)
    # canonical analysis on the training rows: eigenvalues of E^-1 H (H = the between SSCP)
    canon = None
    wt, Yt = w[tr], Y[tr]
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
        Tcov = ((wt[:, None] * (Yt - gm)).T @ (Yt - gm)) / (sw - 1)
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
    tests = _manova_tests(Yt, code_idx[tr], T, wt if (weight or freq) else None)
    train = summaries[0]
    out = {'names': ycols, 'x': x, 'levels': [_level_value(v) for v in present], 'n': nobs, 'n_rows': int(tr.sum()), 'T': T, 'p': p,
           'method': method, 'lam': lam, 'gam': gam, 'priors': q, 'rows': df.index.to_numpy(), 'actual': code_idx,
           'pred': pred, 'prob': _mat(P), 'sqdist': _mat(SqDist), 'prob_actual': prob_act, 'neg_log_prob': nll,
           'misclassified': mis, 'counts': sws, 'means': _mat(means), 'grand_mean': gm, 'pooled_cov': _mat(Sp),
           'pooled_corr': _mat(_cov_to_corr(Sp)), 'group_cov': [_mat(c) for c in covs], 'logdet': logdets,
           'model_cov': [_mat(S) for S in C['Sigs']],
           'summary': {k: train[k] for k in ('n_mis', 'pct_mis', 'entropy_r2', 'm2ll', 'n')},
           'confusion': confs[0]['matrix'], 'canonical': canon, 'tests': tests, 'notes': notes}
    if validation:
        out.update({'validation': validation, 'sets': sets, 'summaries': summaries, 'confusions': confs})
    char = data.meta(table, x).get('dataType') != 'numeric'
    vnum = bool(validation) and data.meta(table, validation).get('dataType') == 'numeric'
    labels = [_lvtext(v) for v in present]
    spec = {'ycols': ycols, 'x': x, 'weight': weight, 'freq': freq, 'char': char, 'levels': levels_all, 'labels': labels, 'method': method,
            'lam': lam, 'gam': gam, 'priors': priors, 'q': q, 'validation': validation, 'vnum': vnum}
    out['code'] = _disc_stats_code(lambda imports: _head(table, rows, where, table_name, imports), spec)
    if plot is not None:
        head = lambda imports: _plot_head(table, rows, where, table_name, imports)  # noqa: E731
        out.update(_disc_codes(head, spec, plot, canon is not None))
    if curves or (decision and T == 2):
        from . import predictive
        head_code = '\n'.join([_head(table, rows, where, table_name, ['from scipy import linalg', PLT]), *_disc_fit_lines(spec), *_disc_post_lines(spec),
                               *([] if validation else ['sets = np.zeros(n, dtype=int)   # every row trains the model']),
                               'y, fitted = t, P   # each row\'s group and its probability of every group: the curves\' input'])
        if curves:
            fit = predictive.report(_disc_prepared(C, freq, ycols, labels), P, head=head_code)
            out['fit'] = {k: fit[k] for k in ('kind', 'sets', 'roc', 'lift', 'plots', 'levels')}
        if decision and T == 2:
            out['threshold'] = predictive.threshold(code_idx, P, labels, sets, w if (weight or freq) else None, df.index.to_numpy(),
                                                    head=head_code, values=[_level_value(v) for v in present])
    return out


def _disc_classify(C, Y):
    """SqDist and the posterior probabilities of rows Y by the fit C."""
    T = C['T']
    D2 = np.column_stack([np.einsum('ij,jk,ik->i', Y - C['means'][t], C['Sinv'][t], Y - C['means'][t]) for t in range(T)])
    SqDist = D2 + np.array(C['logdets'])[None, :] - 2 * np.log(C['q'])[None, :]
    a = -0.5 * SqDist
    a = a - a.max(1, keepdims=True)
    P = np.exp(a)
    return SqDist, P / P.sum(1, keepdims=True)


@api('discriminant.probs')
def disc_probs(table, y, x, rows=None, weight=None, freq=None, method='linear', lam=0.5, gam=0.0, priors='equal', prior_values=None,
               validation=None, where=None):
    """Prob[group] of every row of the By group whose covariates are
    present, from the report's fit, as values (the Decision Threshold's Save
    Threshold Formula reads them when the formula columns are not there)."""
    ycols = list(y)
    C = _disc_core(table, ycols, x, rows, weight, freq, method, lam, gam, priors, prior_values, validation)
    idx, Y = _present_rows(table, ycols, where)
    _, P = _disc_classify(C, Y) if len(idx) else (None, np.zeros((0, C['T'])))
    labels = [_lvtext(v) for v in C['present']]
    return {'rows': idx.tolist(), 'prob': P.tolist(), 'names': [f'Prob[{lb}]' for lb in labels]}


def _disc_masks(spec):
    """The training rows' masks in the code: every row without a Validation
    column (the code is then as it was), else the rows with sets == 0."""
    if spec.get('validation'):
        return {'g': lambda k: f'tr & (t == {k})', 'w': 'w[tr]', 'Y': 'Y[tr]', 'n': 'tr.sum()', 't': 't[tr]'}
    return {'g': lambda k: f't == {k}', 'w': 'w', 'Y': 'Y', 'n': 'n', 't': 't'}


def _disc_fit_lines(spec):
    """Lines that take the rows and groups as discriminant.fit does: d, w, Y,
    the categories in the table's order (levels), each row's t, and the
    groups' weighted counts and means, E and the pooled covariance Sp (of
    the training rows, with a Validation column: sets, tr)."""
    ycols, x, weight, freq, char, levels, v = spec['ycols'], spec['x'], spec['weight'], spec['freq'], spec['char'], spec['levels'], spec.get('validation')
    need = [*ycols, x, *[c for c in (weight, freq, v) if c]]
    wexpr = ' * '.join(f'd[{J(c)}]' for c in (weight, freq) if c)
    fit = [f'd = df.dropna(subset={J(list(dict.fromkeys(need)))})   # the rows with every covariate and a category{" and a set" if v else ""}']
    if wexpr:
        fit += [f'd = d[{wexpr} > 0]   # and a positive weight', f'w = ({wexpr}).to_numpy()   # {"Weight times Freq" if weight and freq else "Weight" if weight else "Freq"}']
    else:
        fit.append('w = np.ones(len(d))')
    fit += [f'Y = d[{J(ycols)}].to_numpy()',
            f'g = d[{J(x)}]{".astype(str)" if char else ""}']
    if v:
        if spec.get('vnum'):
            fit.append(f'sets = d[{J(v)}].to_numpy(int)   # {v}: 0 training, 1 validation, 2 test')
        else:
            fit.append(f'sets = d[{J(v)}].str.strip().str.lower().map({J(SET_NAMES)}).to_numpy(int)   # {v}: 0 training, 1 validation, 2 test')
        fit += [f'levels = [v for v in {_py_list(levels)} if (g[sets == 0] == v).any()]   # the categories of the training rows, in the table\'s order',
                'known = g.isin(levels).to_numpy()   # a row of a category the training rows lack cannot be scored',
                'd, w, Y, g, sets = d[known], w[known], Y[known], g[known], sets[known]',
                'tr = sets == 0   # the training rows fit the model; every row is scored']
    else:
        fit.append(f'levels = [v for v in {_py_list(levels)} if (g == v).any()]   # the categories in the table\'s order')
    M = _disc_masks(spec)
    k = 'k'
    fit += ['T, (n, p) = len(levels), Y.shape',
            't = np.array([levels.index(v) for v in g])   # each row\'s category',
            f'counts = np.array([w[{M["g"](k)}].sum() for k in range(T)])',
            f'means = np.array([(w[{M["g"](k)}, None] * Y[{M["g"](k)}]).sum(0) / counts[k] for k in range(T)])',
            f'E = sum((w[{M["g"](k)}, None] * (Y[{M["g"](k)}] - means[k])).T @ (Y[{M["g"](k)}] - means[k]) for k in range(T))   # the within-groups cross products{" of the training rows" if v else ""}',
            f'gm = ({M["w"]}[:, None] * {M["Y"]}).sum(0) / {M["w"]}.sum()   # the grand mean',
            f'Sp = E / ({M["w"]}.sum() - T)   # the pooled within-groups covariance']
    return fit


def _disc_post_lines(spec):
    """Lines that classify the rows as the report does: the priors q, each
    group's covariance for the method, SqDist, the posterior probabilities P."""
    method, lam, gam, priors, q = spec['method'], spec['lam'], spec['gam'], spec['priors'], spec['q']
    M = _disc_masks(spec)
    if priors == 'proportional':
        L = ['q = counts / counts.sum()   # the priors: proportional to occurrence']
    elif priors == 'other':
        L = [f'q = np.array({_py_list(list(q))})   # the priors given (Specify Priors), scaled to sum to one']
    else:
        L = ['q = np.full(T, 1 / T)   # the priors: equal probabilities']
    if method == 'linear':
        L += ['Si, logdet = [np.linalg.pinv(Sp)] * T, np.zeros(T)   # linear: one covariance for every group, the pooled one']
    else:
        lam_, gam_ = (0.0, 0.0) if method == 'quadratic' else (float(lam), float(gam))
        L += [f'lam, gam = {lam_!r}, {gam_!r}   # {"quadratic: each group its own covariance" if method == "quadratic" else "regularized: λ toward the pooled covariance, γ toward the diagonal"}',
              'Si, logdet = [], []',
              'for k in range(T):',
              f'    wk, Ck = w[{M["g"]("k")}], Y[{M["g"]("k")}] - means[k]',
              '    Sk = (wk[:, None] * Ck).T @ Ck / (wk.sum() - 1) if wk.sum() > 1 else Sp.copy()   # one row: the pooled covariance',
              '    dz = np.diag(Sk) <= 1e-12 * np.maximum(np.diag(Sp), 1e-300)   # a covariate constant within the group: its covariances from the pooled matrix',
              '    Sk[dz, :] = Sp[dz, :]; Sk[:, dz] = Sp[:, dz]',
              '    Mix = lam * Sp + (1 - lam) * Sk',
              '    Sig = (1 - gam) * Mix + gam * np.diag(np.diag(Mix))',
              '    sign, ld = np.linalg.slogdet(Sig)',
              '    Si.append(np.linalg.pinv(Sig)); logdet.append(ld if sign > 0 else np.nan)',
              'logdet = np.array(logdet)']
    L += ['D2 = np.column_stack([np.einsum("ij,jk,ik->i", Y - means[k], Si[k], Y - means[k]) for k in range(T)])   # the squared Mahalanobis distances',
          f'SqDist = D2 + logdet - 2 * np.log(q)   # SqDist: less 2 log(prior){"" if method == "linear" else ", plus log|S| of the group"}; the smallest wins',
          'a = -0.5 * SqDist',
          'P = np.exp(a - a.max(1, keepdims=True)); P = P / P.sum(1, keepdims=True)   # the posterior probabilities',
          'nll = -np.log(np.maximum(P[np.arange(n), t], 1e-300))   # −log of the probability of the row\'s own group',
          'mis = P.argmax(1) != t   # misclassified']
    return L


def _disc_canon_lines(spec):
    M = _disc_masks(spec)
    return [
        'B = sum(counts[k] * np.outer(means[k] - gm, means[k] - gm) for k in range(T))   # the between-groups cross products',
        'vals, vecs = linalg.eigh(B, E)   # the canonical variables: the eigenvectors of E⁻¹B',
        'o = np.argsort(vals)[::-1]; vals, vecs = vals[o], vecs[:, o]',
        'm = min(T - 1, p)',
        f'raw = vecs[:, :m] * np.sqrt({M["w"]}.sum() - T)   # scaled to unit pooled within-group variance',
        'sd = np.sqrt(np.diag(Sp))',
        'raw = raw * np.where((raw * sd[:, None]).sum(0) < 0, -1.0, 1.0)   # each one\'s standardized coefficients summing to a positive number',
        'std = raw * sd[:, None]   # the standardized scoring coefficients',
        'cs = (Y - gm) @ raw   # the canonical scores',
        'cm = (means - gm) @ raw   # the groups\' means on them']


def _disc_stats_code(head, spec):
    """The code of Discriminant's report: the classification of each row with
    the report's method, priors, weights and order of the categories, the
    Score Summaries (of each set, with a Validation column), the canonical
    correlations and the multivariate tests."""
    M = _disc_masks(spec)
    L = [head(['from scipy import linalg', 'from statsmodels.multivariate.manova import MANOVA']),
         *_disc_fit_lines(spec), *_disc_post_lines(spec),
         f'labels = {J(spec["labels"])}',
         'print(pd.DataFrame(P, index=d.index + 1, columns=[f"Prob[{v}]" for v in labels]))   # Probabilities to Each Group (by row number)']
    if spec.get('validation'):
        L += ['for k, name in enumerate(["Training", "Validation", "Test"]):   # the Score Summaries and the confusion counts of each set',
              '    s = sets == k',
              '    if not s.any():',
              '        continue',
              '    conf = np.zeros((T, T))',
              '    np.add.at(conf, (t[s], P[s].argmax(1)), w[s])   # each row counted by its weight (Weight times Freq; 1 without them)',
              '    print(name, pd.DataFrame(conf, index=labels, columns=labels))   # the Confusion Matrix: Actual (the rows) by Predicted',
              '    ll = (w[s] * np.log(np.maximum(P[s, t[s]], 1e-300))).sum()   # the log likelihood of the classification',
              '    ll0 = (w[s] * np.log(counts[t[s]] / counts.sum())).sum()   # ... and of the training shares of the groups alone',
              '    print(name, "Number Misclassified", w[s][mis[s]].sum(), "Percent", 100 * w[s][mis[s]].sum() / w[s].sum(), "Entropy RSquare", 1 - ll / ll0, "−2LogLikelihood", -2 * ll)']
    else:
        L += ['conf = np.zeros((T, T))',
              'np.add.at(conf, (t, P.argmax(1)), w)   # each row counted by its weight (Weight times Freq; 1 without them)',
              'print(pd.DataFrame(conf, index=labels, columns=labels))   # the Confusion Matrix: Actual (the rows) by Predicted',
              'll = (w * np.log(np.maximum(P[np.arange(n), t], 1e-300))).sum()   # the log likelihood of the classification',
              'll0 = (w * np.log(counts[t] / w.sum())).sum()   # ... and of the groups\' shares alone',
              'print("Number Misclassified", w[mis].sum(), "Percent", 100 * w[mis].sum() / w.sum(), "Entropy RSquare", 1 - ll / ll0, "−2LogLikelihood", -2 * ll)']
    L += [*_disc_canon_lines(spec),
          'cancorr = np.sqrt(np.maximum(vals[:m], 0) / (1 + np.maximum(vals[:m], 0)))',
          'print("Canonical correlations", cancorr)',
          f'Xd = np.column_stack([np.ones({M["n"]})] + [({M["t"]} == k).astype(float) for k in range(1, T)])   # an intercept and the categories after the first',
          f'sq = np.sqrt({M["w"]} / {M["w"]}.mean())   # {"the rows scaled by the square roots of their weights" if spec["weight"] or spec["freq"] else "(no weights: ones)"}',
          'Lc = np.zeros((T - 1, T)); Lc[:, 1:] = np.eye(T - 1)   # the hypothesis: the categories do not differ',
          f'tests = MANOVA({M["Y"]} * sq[:, None], Xd * sq[:, None]).mv_test([("categories", Lc)]).results["categories"]["stat"]',
          'print(tests)   # Wilks, Pillai, Hotelling-Lawley, Roy']
    return '\n'.join(L)


def _disc_codes(head, spec, plot, canonical):
    """The code of Discriminant's graphs: the canonical plot, the rows'
    −log(probability) of their own group and the scatterplot matrix with the
    groups' ellipses, the fit made as discriminant.fit makes it."""
    ycols, labels, v = spec['ycols'], spec['labels'], spec.get('validation')
    fit = _disc_fit_lines(spec)
    out = {}
    if canonical and plot.get('canonical', True):
        pts, cl, c50, rays = (bool(plot.get(k, dflt)) for k, dflt in (('points', True), ('cl', True), ('c50', False), ('rays', True)))
        L = [head(['from scipy import linalg']), *fit, *_disc_canon_lines(spec),
             f'labels = {J(labels)}',
             f'colors = {J(PALETTE)}   # the page\'s palette, a colour for each category',
             'two = m >= 2']
        if cl or c50:
            L += ['', *ELLIPSE_DEF, '']
        L += ['if two:',
              '    x, y = cs[:, 0], cs[:, 1]',
              'else:   # one canonical variable (two groups): the rows by their group, jittered as the page jitters them',
              '    h = np.sin(np.arange(n) * 12.9898 + 78.233) * 43758.5453',
              '    x, y = cs[:, 0], t + (h - np.floor(h) - 0.5) * 0.5',
              'fig, ax = plt.subplots(figsize=(5.4, 4.6 if two else 3.2), layout="constrained")']
        if pts:
            if v:
                L += [f'ax.scatter(x[tr], y[tr], s={_area(6)}, c=[colors[k % len(colors)] for k in t[tr]])   # the training rows',
                      f'ax.scatter(x[~tr], y[~tr], s={_area(6)}, facecolors="none", edgecolors=[colors[k % len(colors)] for k in t[~tr]])   # the validation and test rows, open']
            else:
                L.append(f'ax.scatter(x, y, s={_area(6)}, c=[colors[k % len(colors)] for k in t])')
        L += ['for k, name in enumerate(labels):',
              '    mx, my = cm[k, 0], (cm[k, 1] if two else k)',
              '    color = colors[k % len(colors)]',
              f'    ax.plot(mx, my, marker="+", markersize={_msize(16)}, markeredgewidth={_lw(2.2)}, color=color, linestyle="none", label=name)   # the group\'s mean']
        if cl:
            L += ['    if two:   # its 95% confidence region',
                  '        ex, ey = ellipse(mx, my, 1 / np.sqrt(counts[k]), 1 / np.sqrt(counts[k]), 0, 0.95)',
                  f'        ax.plot(ex, ey, color=color, linewidth={_lw(1.4)})',
                  '    else:',
                  '        hw = 1.96 / np.sqrt(counts[k])',
                  f'        ax.plot([mx - hw, mx + hw], [my, my], color=color, linewidth={_lw(3)})']
        if c50:
            L += ['    if two:   # where half of a group\'s rows fall (a normal with unit variance)',
                  '        ex, ey = ellipse(mx, my, 1, 1, 0, 0.5)',
                  f'        ax.plot(ex, ey, color=color, linewidth={_lw(1)}, linestyle=":")',
                  '    else:',
                  f'        ax.plot([mx - 0.6745, mx + 0.6745], [my + 0.3, my + 0.3], color=color, linewidth={_lw(1)}, linestyle=":")']
        if rays:
            L += ['oy = 0 if two else T - 0.5',
                  f'for j, name in enumerate({J(ycols)}):   # the biplot rays: the standardized scoring coefficients × 1.5',
                  '    dx, dy = 1.5 * std[j, 0], (1.5 * std[j, 1] if two else 0.25 * (j + 1) / p)',
                  f'    ax.plot([0, dx], [oy, oy + dy], color="{MUTED}", linewidth={_lw(1.2)})',
                  f'    ax.annotate("", xy=(dx, oy + dy), xytext=(0, oy), arrowprops={{"arrowstyle": "-|>", "color": "{MUTED}", "lw": {_lw(1.2)}, "shrinkA": 0, "shrinkB": 0}})',
                  '    ax.text(dx, oy + dy, name, ha="left" if dx >= 0 else "right", va="center", fontsize=7.5)']
        L += [f'ax.axvline(0, color="{GRID}", linewidth={_lw(1)}, zorder=0)',
              'if two:',
              f'    ax.axhline(0, color="{GRID}", linewidth={_lw(1)}, zorder=0)',
              '    ax.set_aspect("equal")',
              '    ax.set_ylabel("Canonical2")',
              'else:',
              '    ax.set_yticks(range(T), labels)',
              '    ax.set_ylim(-0.8, T + 0.2)',
              'ax.set_xlabel("Canonical1")',
              'ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=min(T, 6), frameon=False, fontsize=7.5)',
              'ax.set_title("Canonical Plot")', 'plt.show()']
        out['canonical_code'] = '\n'.join(L)
    # the rows' posterior probabilities, as the report computes them
    L = [head([]), *fit, *_disc_post_lines(spec),
         'row = d.index.to_numpy() + 1',
         _fig(520, 230),
         f'ax.scatter(row[~mis], nll[~mis], s={_area(6)}, color="{BASE}")',
         f'ax.scatter(row[mis], nll[mis], s={_area(6)}, marker="x", color="{RED}")   # the misclassified rows',
         'ax.set_ylim(bottom=0)', 'ax.set_xlabel("Row Number")', 'ax.set_ylabel("−Log(Prob(Actual))")', 'ax.set_title("Discriminant scores by row")', 'plt.show()']
    out['scores_code'] = '\n'.join(L)
    sp = plot.get('splom')
    if sp:
        out['splom_code'] = _disc_splom_code(head, spec, sp)
    return out


def _disc_splom_code(head, spec, sp):
    """The Scatterplot Matrix of the covariates (lower triangular, as JMP's):
    the rows in the colours of their groups and each group's normal ellipse
    with its mean and the covariance the method uses (the pooled within
    covariance for the linear method), covering `level` of the group."""
    ycols, labels = spec['ycols'], spec['labels']
    W, H, level = sp.get('width', 600), sp.get('height', 600), float(sp.get('level', 0.9))
    L = [head(['from scipy import linalg']), *_disc_fit_lines(spec), *_disc_post_lines(spec),
         f'labels, names = {J(labels)}, {J(ycols)}',
         f'colors = {J(PALETTE)}   # the page\'s palette, a colour for each category',
         f'level = {level!r}   # the ellipses\' coverage',
         'Sig = [np.linalg.pinv(S) for S in Si]   # each group\'s covariance for the method (the inverse of the inverse used to classify)',
         '', *ELLIPSE_DEF, '',
         'g_ = len(names) - 1',
         f'fig, axes = plt.subplots(g_, g_, figsize=({round(W) / 100:g}, {round(H) / 100:g}), squeeze=False, layout="constrained")',
         'for ax in axes.flat:',
         '    ax.set_visible(False)',
         'for i in range(1, len(names)):   # below the diagonal: each covariate against each one before it',
         '    for j in range(i):',
         '        ax = axes[i - 1, j]',
         '        ax.set_visible(True)',
         f'        ax.scatter(Y[:, j], Y[:, i], s={_area(4)}, c=[colors[k % len(colors)] for k in t], linewidths=0)',
         '        for k in range(T):   # each group\'s ellipse for the pair',
         '            S = Sig[k]',
         '            sx, sy = np.sqrt(S[j, j]), np.sqrt(S[i, i])',
         '            ex, ey = ellipse(means[k, j], means[k, i], sx, sy, S[i, j] / (sx * sy), level)',
         *([f'            ax.fill(ex, ey, color=colors[k % len(colors)], alpha={0x22 / 255:.4g}, linewidth=0)   # Shaded Ellipses'] if sp.get('shaded') else []),
         f'            ax.plot(ex, ey, color=colors[k % len(colors)], linewidth={_lw(1.2)})',
         '        ax.tick_params(labelsize=6.5)',
         '        if i == len(names) - 1:',
         '            ax.set_xlabel(names[j], fontsize=7.6)',
         '        if j == 0:',
         '            ax.set_ylabel(names[i], fontsize=7.6)',
         'fig.suptitle("Scatterplot Matrix", fontsize=10)', 'plt.show()']
    return '\n'.join(L)


def _py_list(vals):
    """A list of values as a Python literal."""
    return '[' + ', '.join(_lit(v) for v in vals) + ']'


def _manova_tests(Y, codes, T, w=None):
    """Wilks' lambda, Pillai's trace, Hotelling-Lawley and Roy from
    statsmodels' MANOVA of the covariates on the categories (the groups the
    rows have: codes 0 .. T − 1)."""
    from statsmodels.multivariate.manova import MANOVA
    try:
        Y = np.asarray(Y, float)
        codes = np.asarray(codes, int)
        Xd = np.column_stack([np.ones(len(Y))] + [(codes == j).astype(float) for j in range(1, T)])
        if w is not None:
            sq = np.sqrt(w / np.mean(w))
            Y = Y * sq[:, None]
            Xd = Xd * sq[:, None]
        L = np.zeros((T - 1, T))
        L[:, 1:] = np.eye(T - 1)
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


def _quad_formula(A, mean, cols):
    """(y − mean)ᵀ A (y − mean) as formula text, A symmetric and positive
    semidefinite (an inverse covariance): the sum of the squares of the
    linear forms √λ_k v_kᵀ(y − mean) of A's eigenvectors (a zero eigenvalue
    of a pseudo-inverse left out)."""
    lam, V = np.linalg.eigh((np.asarray(A, float) + np.asarray(A, float).T) / 2)
    top = max(float(lam.max()), 0.0)
    z = [_fz(c, mean[i]) for i, c in enumerate(cols)]
    terms = [_fsq(_flin(math.sqrt(lam[k]) * V[:, k], z)) for k in range(len(lam)) if lam[k] > 1e-13 * top]
    return _fsum(terms)


def _ph(j):
    """A placeholder for the j-th column saved in the same batch: the page
    writes that column's reference in its place (its name may have been
    made unique)."""
    return '{{col:%d}}' % j


@api('discriminant.save')
def disc_save(table, y, x, rows=None, weight=None, freq=None, method='linear', lam=0.5, gam=0.0, priors='equal', prior_values=None,
              validation=None, what='formulas', where=None):
    """Save Formulas (JMP's): SqDist[group], the squared Mahalanobis distance
    to the group's mean with the method's covariance, plus log|S| of the
    group for quadratic and regularized, less 2 log(prior); Prob[group],
    exp(−SqDist/2) over its sum (written with the smallest SqDist taken out,
    as a probability is never missing where the distances are not); and
    Pred <X>, the group of the smallest SqDist. canonical: Save Canonical
    Scores, Canon[j] = Σ_i c_ij (y_i − the grand mean), formulas too. The
    fit is the report's (the training rows with a Validation column)."""
    ycols = list(y)
    try:
        C = _disc_core(table, ycols, x, rows, weight, freq, method, lam, gam, priors, prior_values, validation)
    except ValueError as e:
        return {'error': str(e)}
    labels = [_lvtext(v) for v in C['present']]
    T = C['T']
    by = _by_words(table, where)
    meth = {'linear': 'linear, the pooled covariance', 'quadratic': 'quadratic, each group\'s covariance', 'regularized': 'regularized'}.get(method, method)
    if what == 'canonical':
        B, E, Sp, gm, sw = C['B'], C['E'], C['Sp'], C['gm'], C['sw']
        try:
            vals, vecs = sla.eigh(B, E)
        except (np.linalg.LinAlgError, ValueError) as e:
            return {'error': f'no canonical scores: {e}'}
        order = np.argsort(vals)[::-1]
        m = min(T - 1, C['p'])
        raw = vecs[:, order][:, :m] * math.sqrt(sw - T)
        raw = raw * np.where((raw * np.sqrt(np.diag(Sp))[:, None]).sum(0) < 0, -1.0, 1.0)
        z = [_fz(c, gm[i]) for i, c in enumerate(ycols)]
        return {'columns': [{'name': f'Canon[{j + 1}]', 'formula': _fguard(table, _flin(raw[:, j], z), where),
                             'notes': f'canonical score {j + 1} from Discriminant: the scoring coefficients times the covariates less their grand mean{by}'}
                            for j in range(m)]}
    cols = []
    for t in range(T):
        const = (C['logdets'][t] if method != 'linear' else 0.0) - 2 * math.log(C['q'][t])
        quad = _quad_formula(C['Sinv'][t], C['means'][t], ycols)
        expr = f'{quad} + {_fnum(const)}' if const > 0 else f'{quad} - {_fnum(-const)}' if const < 0 else quad
        cols.append({'name': f'SqDist[{labels[t]}]', 'formula': _fguard(table, expr, where),
                     'notes': f'the squared distance to the mean of {x} = {labels[t]} ({meth}){" plus log|S| of the group" if method != "linear" else ""}, less 2 log(prior), from Discriminant{by}'})
    S = [_ph(t) for t in range(T)]
    mn = f'Min({", ".join(S)})'
    ex = [f'Exp(-0.5 * ({s} - {mn}))' for s in S]
    for t in range(T):
        cols.append({'name': f'Prob[{labels[t]}]', 'formula': f'{ex[t]} / ({" + ".join(ex)})',
                     'notes': f'the posterior probability of {x} = {labels[t]}: exp(−SqDist/2) over its sum, from Discriminant{by}'})
    char = data.meta(table, x).get('dataType') != 'numeric'
    res = [formula_str(lb) if char else _fnum(v) for lb, v in zip(labels, C['present'])]
    chain = []
    for t in range(T - 1):
        chain.append(' & '.join(f'{S[t]} <= {S[u]}' for u in range(t + 1, T)))
        chain.append(res[t])
    pred = f'If({", ".join(chain)}, {res[-1]})'
    meta = data.meta(table, x)
    cols.append({'name': f'Pred {x}', 'formula': pred, 'modelingType': meta.get('modelingType') or 'nominal',
                 'notes': f'the most probable group, the smallest SqDist, from Discriminant{by}'})
    return {'columns': cols}


@api('discriminant.stepwise')
def disc_stepwise(table, y, x, rows=None, entered=None, weight=None, freq=None, validation=None):
    """JMP's stepwise panel: for each covariate, the analysis-of-covariance F
    test of the categories with the covariate as the response and the
    covariates already entered as predictors (statsmodels OLS); with a
    Validation column, on the training rows."""
    import statsmodels.api as sm
    ycols = list(y)
    entered = [c for c in (entered or []) if c in ycols]
    df, w, _ = _cat_frame(table, ycols, x, rows, weight, freq)
    if validation:
        try:
            s = _sets_of(table, validation, df.index.to_numpy())
        except ValueError as e:
            return {'error': str(e)}
        df, w = df[s == 0], w[s == 0]
    g = pd.Categorical(df[x])
    D = pd.get_dummies(g, drop_first=True).to_numpy(float)
    D = D[:, D.any(axis=0)] if D.size else D
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
# The Distance option, beyond JMP (whose distances are the squared Euclidean
# ones): for Single, Complete and Average linkage. Ward and Centroid join on
# squared Euclidean distances, which their definitions need.
HC_DISTANCES = {'sqeuclidean': 'Squared Euclidean', 'euclidean': 'Euclidean', 'cityblock': 'City Block',
                'chebyshev': 'Chebyshev', 'correlation': 'Correlation (1 − r)', 'mahalanobis': 'Mahalanobis',
                'jaccard': 'Jaccard', 'gower': 'Gower'}
HC_MAX_SILHOUETTE = 2000   # rows for the silhouettes (their n x n dissimilarities)


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


def huber_center_scale(X):
    """Huber's M-estimates of the location and scale of each column
    (statsmodels.robust.scale.Huber, his proposal 2): JMP's Standardize
    Robustly. A column where they fail (most values equal) takes its mean
    and standard deviation."""
    from statsmodels.robust.scale import Huber
    m, s = [], []
    for j in range(X.shape[1]):
        v = X[:, j]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                loc, sc = Huber(maxiter=100)(v)
            loc, sc = float(np.asarray(loc).item()), float(np.asarray(sc).item())
            if not (math.isfinite(loc) and math.isfinite(sc) and sc > 0):
                raise ValueError
        except Exception:
            loc, sc = float(np.mean(v)), float(np.std(v, ddof=1)) if len(v) > 1 else 1.0
        m.append(loc)
        s.append(sc if sc > 0 else 1.0)
    return np.array(m), np.array(s)


def gower_condensed(X, cat):
    """Gower's (1971) dissimilarity of every pair of rows, condensed as
    scipy's pdist gives them: the mean over the columns of |x_i − x_j|/range
    for a numeric column and of 0 or 1 (the same level or not) for a
    categorical one (a constant column adds 0). X: rows x columns (objects
    for the categorical ones); cat: which columns are categorical."""
    from scipy.spatial.distance import pdist
    n, p = X.shape
    D = np.zeros(n * (n - 1) // 2)
    for j in range(p):
        if cat[j]:
            codes = pd.factorize(pd.Series(X[:, j], dtype=object))[0].astype(float)
            D += pdist(codes[:, None], 'hamming')
        else:
            v = np.asarray(X[:, j], dtype=float)
            rg = float(v.max() - v.min())
            if rg > 0:
                D += pdist(v[:, None], 'cityblock') / rg
    return D / p


def cut_tree(merges, n, k, order):
    """The page's k clusters (smui-p-multivariate.js clustersAt): the first
    n − k joins, each cluster numbered 0, 1, ... in the order of its first
    leaf in the dendrogram."""
    parent = np.full(2 * n - 1, -1)
    for s, (a, b) in enumerate(np.asarray(merges, int)):
        parent[a] = parent[b] = n + s
    root = np.arange(2 * n - 1)
    for v in range(2 * n - k - 1, -1, -1):
        if 0 <= parent[v] < 2 * n - k:
            root[v] = root[parent[v]]
    number = {}
    for leaf in order:
        number.setdefault(int(root[leaf]), len(number))
    return np.array([number[int(root[i])] for i in range(n)])


def _silhouette_from_sums(S, cnt, lab):
    """Each row's silhouette from S (rows x clusters: the sum of its
    dissimilarities to each cluster's rows), the clusters' sizes and each
    row's cluster; a cluster of size 0 is not there."""
    n = len(lab)
    own = cnt[lab]
    a = np.where(own > 1, S[np.arange(n), lab] / np.maximum(own - 1, 1), 0.0)
    with np.errstate(divide='ignore', invalid='ignore'):
        M = S / np.where(cnt > 0, cnt, 1)[None, :]
    M[:, cnt == 0] = np.inf
    M[np.arange(n), lab] = np.inf
    b = M.min(1)
    den = np.maximum(a, b)
    return np.where((own > 1) & (den > 0) & np.isfinite(b), (b - a) / np.where(den > 0, den, 1), 0.0)


def silhouettes(D, lab):
    """Rousseeuw's (1987) silhouette of each row, (b − a)/max(a, b): a the
    mean dissimilarity to the other rows of its cluster, b the smallest mean
    dissimilarity to the rows of another cluster; 0 for a row alone in its
    cluster (as scikit-learn's silhouette_samples has it). D: n x n."""
    lab = np.asarray(lab, int)
    k = int(lab.max()) + 1
    S = np.column_stack([D[:, lab == c].sum(1) for c in range(k)])
    return _silhouette_from_sums(S, np.bincount(lab, minlength=k), lab)


def silhouette_path(D, merges, n, kmax):
    """The mean silhouette of the tree cut into k clusters, k = 2 .. kmax, in
    one pass up the tree: the sums of each row's dissimilarities to the kmax
    clusters, then each join adds two clusters' sums together."""
    merges = np.asarray(merges, int)
    kmax = int(min(kmax, n - 1))
    if kmax < 2:
        return {}
    parent = np.full(2 * n - 1, -1)
    for s, (a, b) in enumerate(merges):
        parent[a] = parent[b] = n + s
    root = np.arange(2 * n - 1)
    for v in range(2 * n - kmax - 1, -1, -1):
        if 0 <= parent[v] < 2 * n - kmax:
            root[v] = root[parent[v]]
    col_of = {}
    lab = np.array([col_of.setdefault(int(root[i]), len(col_of)) for i in range(n)])
    S = np.column_stack([D[:, lab == c].sum(1) for c in range(kmax)])
    cnt = np.bincount(lab, minlength=kmax).astype(float)
    out = {}
    for k in range(kmax, 1, -1):
        out[k] = float(np.mean(_silhouette_from_sums(S, cnt, lab)))
        a, b = merges[n - k]           # the join that leaves k − 1 clusters
        ca, cb = col_of[int(a)], col_of[int(b)]
        S[:, ca] += S[:, cb]
        S[:, cb] = 0.0
        cnt[ca] += cnt[cb]
        cnt[cb] = 0
        lab[lab == cb] = ca
        col_of[n + n - k] = ca
    return out


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


def _hc_nominal(table, cols):
    """The Y columns Gower takes as categorical: nominal ones, and any of text."""
    return [c for c in cols if data.meta(table, c).get('modelingType') == 'nominal' or data.meta(table, c).get('dataType') != 'numeric']


def _hc_data(table, cols, rows, standardize='columns', robust=False, impute=False, matrix=False, distance='sqeuclidean', where=None):
    """The rows Hierarchical Cluster joins and what it joins them by: a dict
    of the rows (the table's row numbers), X (their numeric columns, missing
    values imputed with impute; None for a distance matrix), Xs (the data the
    clustering sees: X standardized as asked, robustly by Huber's estimates
    with robust; Jaccard: 0/1, present or not; Gower: the numeric columns
    over their ranges; None with a nominal column or a distance matrix),
    center and scale (the column standardization, for the closest-cluster
    formula), Dc (the condensed dissimilarities, when the joins are not
    JMP's coordinate ones), cat (Gower's categorical columns) and notes."""
    from scipy.spatial.distance import pdist, squareform
    notes = []
    out = {'X': None, 'Xs': None, 'center': None, 'scale': None, 'Dc': None, 'cat': [], 'notes': notes, 'matrix': bool(matrix)}
    if matrix:
        grp = _group_rows(table, where)
        keep = np.asarray(sorted(set(grp.tolist()) & set(range(data.TABLES[table]['n'])) if rows is None else rows), dtype=int)
        keep = keep[np.isin(keep, grp)]
        if len(cols) == len(grp):
            pos = {int(r): j for j, r in enumerate(grp)}
            mcols = [cols[pos[int(r)]] for r in keep]   # the column of each object kept: its row's place among the group's rows
        elif len(cols) == len(keep):
            mcols = list(cols)
        else:
            raise ValueError(f'a distance matrix needs a column for each row: {len(grp)} rows{f" ({len(keep)} in the report)" if len(keep) != len(grp) else ""}, {len(cols)} columns')
        D = np.column_stack([pd.to_numeric(data.series(table, c, keep, as_category=False), errors='coerce').to_numpy(float) for c in mcols])
        D = np.where(np.isnan(D), D.T, D)
        if np.isnan(D).any():
            raise ValueError('the distance matrix has missing values on both sides of the diagonal')
        D = (D + D.T) / 2
        np.fill_diagonal(D, 0)
        if (D < 0).any():
            raise ValueError('the distance matrix has negative distances')
        out.update({'rows': keep, 'n': len(keep), 'Dc': squareform(D, checks=False), 'mcols': mcols})
        return out
    cat = _hc_nominal(table, cols) if distance == 'gower' else []
    bad = [c for c in cols if c not in cat and (data.meta(table, c).get('modelingType') == 'nominal' or data.meta(table, c).get('dataType') != 'numeric')]
    if bad:
        raise ValueError(f'{", ".join(bad)}: {"a nominal column" if len(bad) == 1 else "nominal columns"}; the Gower distance (Distance, in the launch or the red triangle) compares levels')
    num = [c for c in cols if c not in cat]
    df = data.frame(table, cols, rows, dropna=False, as_category=False)
    Xn = np.column_stack([pd.to_numeric(df[c], errors='coerce').to_numpy(float) for c in num]) if num else np.zeros((len(df), 0))
    ok_cat = np.ones(len(df), dtype=bool)
    for c in cat:
        ok_cat &= df[c].notna().to_numpy() & (df[c].astype(object) != '').to_numpy()
    miss = ~np.isfinite(Xn)
    if impute and num:
        if len(num) < 2:
            raise ValueError('Missing value imputation needs two or more numeric columns (the others predict a missing value)')
        some = miss.any(axis=1) & ~miss.all(axis=1)
        keep = ok_cat & ~miss.all(axis=1)
        if (~keep).sum():
            notes.append(f'{plural_rows(int((~keep).sum()))} with no value in any numeric column{" or a missing level" if cat else ""} left out.')
        Xk = Xn[keep]
        if miss[keep].any():
            from .tables import conditional_means, mvn_em
            mu, sig, _it = mvn_em(Xk)
            Xk = conditional_means(Xk, mu, sig)
            notes.append(f'{int(miss[keep].sum())} missing values in {plural_rows(int(some[keep].sum()))} imputed from a multivariate normal fitted by EM (the conditional means, as Explore Missing Values\' Multivariate Normal Imputation).')
        Xn, idx = Xk, df.index.to_numpy()[keep]
        catv = df.loc[idx, cat].to_numpy(object) if cat else None
    else:
        keep = ok_cat & ~miss.any(axis=1)
        if (~keep).sum():
            notes.append(f'{plural_rows(int((~keep).sum()))} with a missing value left out.')
        Xn, idx = Xn[keep], df.index.to_numpy()[keep]
        catv = df.loc[idx, cat].to_numpy(object) if cat else None
    n = len(idx)
    out.update({'rows': idx, 'n': n, 'num': num, 'cat': cat})
    if n < 2:
        return out
    out['X'] = Xn
    if distance == 'gower':
        allX = np.empty((n, len(cols)), dtype=object)
        for j, c in enumerate(cols):
            allX[:, j] = catv[:, cat.index(c)] if c in cat else Xn[:, num.index(c)]
        out['Dc'] = gower_condensed(allX, [c in cat for c in cols])
        if not cat:
            lo, rg = Xn.min(0), np.ptp(Xn, axis=0)
            out['Xs'] = (Xn - lo) / np.where(rg > 0, rg, 1.0)
            out['center'], out['scale'] = lo, np.where(rg > 0, rg, 1.0)
        if standardize != 'none' or robust:
            notes.append('Gower\'s distance scales each numeric column by its range: Standardize By is not used.')
        return out
    if distance == 'jaccard':
        out['Xs'] = (Xn != 0).astype(float)
        out['Dc'] = pdist(out['Xs'].astype(bool), 'jaccard')
        if standardize != 'none' or robust:
            notes.append('The Jaccard distance takes each value as present (not 0) or absent (0): Standardize By is not used.')
        return out
    if standardize == 'columns':
        if robust:
            center, scale = huber_center_scale(Xn)
        else:
            center, sd = Xn.mean(0), Xn.std(0, ddof=1)
            scale = np.where(sd > 0, sd, 1.0)
        out['center'], out['scale'] = center, scale
        Xs = (Xn - center) / scale
    else:
        Xs = _standardize(Xn, standardize)
        if robust:
            notes.append('Standardize Robustly applies to Standardize By Columns (Huber\'s estimates of each column\'s mean and standard deviation).')
        if standardize == 'none':
            out['center'], out['scale'] = np.zeros(Xn.shape[1]), np.ones(Xn.shape[1])
    out['Xs'] = Xs
    if distance == 'mahalanobis':
        out['Dc'] = pdist(Xs, 'mahalanobis', VI=np.linalg.pinv(np.cov(Xs, rowvar=False).reshape(Xs.shape[1], Xs.shape[1])))
    elif distance == 'correlation':
        if Xs.shape[1] < 2 or np.any(np.ptp(Xs, axis=1) == 0):
            raise ValueError('the correlation distance needs rows that vary across the columns: a row has the same value in every column')
        out['Dc'] = pdist(Xs, 'correlation')
    elif distance in ('euclidean', 'cityblock', 'chebyshev'):
        out['Dc'] = pdist(Xs, distance)
    return out


def plural_rows(k):
    return f'{k} row{"" if k == 1 else "s"}'


def _hc_linkage(H, method, distance):
    """The joins, with JMP's heights for coordinate data and squared
    Euclidean distances (jmp_linkage); with another distance or a distance
    matrix, scipy's linkage of the condensed dissimilarities (a distance
    matrix's Ward and Centroid take them as Euclidean, their heights then as
    JMP's: the increase in the within-cluster sum of squares, the squared
    distance of the means)."""
    from scipy.cluster.hierarchy import linkage
    if H['Dc'] is None:
        return jmp_linkage(H['Xs'], method)
    if method in ('ward', 'centroid') and not H['matrix']:
        raise ValueError(f'{method.title()} joins on squared Euclidean distances: the {HC_DISTANCES.get(distance, distance)} distance is for Single, Complete and Average linkage')
    Z = linkage(H['Dc'], method)
    if method == 'ward':
        Z[:, 2] = Z[:, 2] ** 2 / 2
    elif method == 'centroid':
        Z[:, 2] = Z[:, 2] ** 2
    return Z


def _hc_default_k(heights, n):
    """The page's default number of clusters: where the joining distance
    jumps most (the largest ratio of one join to the one before), 2 to 10."""
    best, ratio = min(3, n), -math.inf
    for q in range(2, min(10, n - 1) + 1):
        up, down = heights[n - q], heights[n - q - 1]
        r = up / down if down > 0 else (math.inf if up > 0 else 0)
        if r > ratio:
            best, ratio = q, r
    return best


def _hc_k(n_clusters, heights, n):
    k = _hc_default_k(heights, n) if n_clusters is None else int(math.floor(float(n_clusters) + 0.5))
    return max(1, min(n, k))


def _hc_silhouette_matrix(H, method, distance):
    """The dissimilarities the silhouettes use (n x n): the clustering's own,
    or the Euclidean distances where it joins on squared Euclidean ones."""
    from scipy.spatial.distance import pdist, squareform
    if H['Dc'] is not None:
        return squareform(H['Dc'])
    return squareform(pdist(H['Xs'], 'euclidean'))


@api('hcluster.fit')
def hcluster_fit(table, columns, rows=None, method='ward', standardize='columns', label=None, two_way=False, n_clusters=None, where=None,
                 robust=False, impute=False, matrix=False, distance='sqeuclidean', silhouette=False, table_name='data'):
    """Agglomerative clustering with JMP's distances. Returns the merges (for
    the dendrogram, the history and the clusters at any number, which the
    page computes), the rows, the cluster criterion and, for two-way
    clustering, the order of the columns. n_clusters: the report's Number of
    Clusters, for its code (None: the page's default, which the code computes).
    robust: Standardize Robustly (Huber's estimates); impute: Missing value
    imputation (EM); matrix: the columns are a distance matrix; distance
    (beyond JMP): the dissimilarity of Single, Complete and Average linkage;
    silhouette: the silhouettes of the chosen clusters and of each number of
    clusters (beyond JMP)."""
    from scipy.cluster.hierarchy import leaves_list
    cols = list(columns)
    distance = distance or 'sqeuclidean'
    if distance not in HC_DISTANCES:
        return {'error': f'no distance {distance!r}'}
    if matrix:
        distance = 'sqeuclidean'
    try:
        H = _hc_data(table, cols, rows, standardize, robust, impute, matrix, distance, where)
    except ValueError as e:
        return {'error': str(e)}
    n = H['n']
    if n < 2:
        return {'error': 'fewer than two rows without missing values' + (' (Missing value imputation keeps rows with some values)' if not impute and not matrix else '')}
    if n > 4000:
        return {'error': f'{n} rows: hierarchical clustering here takes at most 4000 rows (it keeps all n(n-1)/2 distances in memory); use K Means Cluster'}
    try:
        Z = _hc_linkage(H, method, distance)
    except ValueError as e:
        return {'error': str(e)}
    order = leaves_list(Z)
    Xs = H['Xs']
    coords = Xs is not None
    crit = []
    if coords:
        p = Xs.shape[1]
        r2 = partition_r2(Xs, Z)
        ev = np.linalg.eigvalsh(np.cov(Xs, rowvar=False).reshape(p, p)) if n > 1 else np.zeros(p)
        kmax = int(min(n - 1, max(10, round(n / 10))))
        for k in range(1, kmax + 1):
            e, cv = ccc(ev, n, k, r2[k]) if k >= 2 else (float('nan'), float('nan'))
            crit.append({'k': k, 'r2': r2[k], 'er2': e, 'ccc': cv})
    else:
        p = len(cols)
    idx = np.asarray(H['rows'], dtype=int)
    out = {'names': cols, 'n': n, 'method': method, 'standardize': standardize, 'rows': idx,
           'merges': Z[:, :2].astype(int), 'heights': Z[:, 2], 'sizes': Z[:, 3].astype(int), 'order': order,
           'criterion': crit, 'coords': coords, 'distance': distance, 'distance_label': HC_DISTANCES[distance], 'matrix': bool(matrix),
           'nominal': H['cat'], 'notes': H['notes'],
           'data': _mat(Xs) if coords and (two_way or n * p <= 20000) else None}
    if coords and H.get('center') is not None:
        out['center'], out['scale'] = H['center'], H['scale']
    if H['X'] is not None:
        X = H['X']
        out['mean'] = X.mean(0)
        sd = X.std(0, ddof=1) if n > 1 else np.ones(X.shape[1])
        out['sd'] = np.where(sd > 0, sd, 1.0)
        out['numeric'] = H['num']
        if impute:
            out['values'] = _mat(X)   # the imputed values of the numeric columns (the cluster summaries and the parallel plot use them)
    if two_way and coords and p >= 2:
        Zc = jmp_linkage(Xs.T, 'ward' if method in ('ward', 'centroid') else method)
        out['col_order'] = leaves_list(Zc).tolist()
        out['col_merges'] = Zc[:, :2].astype(int)
        out['col_heights'] = Zc[:, 2]
    k = _hc_k(n_clusters, Z[:, 2], n)
    if silhouette:
        if n > HC_MAX_SILHOUETTE:
            out['silhouette'] = {'error': f'{n} rows: the silhouettes are computed for up to {HC_MAX_SILHOUETTE} rows'}
        else:
            D = _hc_silhouette_matrix(H, method, distance)
            lab = cut_tree(Z[:, :2].astype(int), n, k, order)
            s = silhouettes(D, lab) if k >= 2 else np.zeros(n)
            path = silhouette_path(D, Z[:, :2].astype(int), n, min(30, n - 1))
            best = max(path, key=lambda q: path[q]) if path else None
            out['silhouette'] = {'k': k, 'values': s, 'mean': float(np.mean(s)) if k >= 2 else None,
                                 'clusters': [{'cluster': c + 1, 'count': int(np.sum(lab == c)), 'mean': float(np.mean(s[lab == c]))} for c in range(k)],
                                 'path': [{'k': q, 'mean': path[q]} for q in sorted(path)], 'best': best,
                                 'on': 'the Euclidean distances' if H['Dc'] is None else ('the distance matrix' if matrix else f'the {HC_DISTANCES[distance]} distances')}
    S = {'cols': cols, 'method': method, 'standardize': standardize, 'robust': bool(robust), 'impute': bool(impute), 'matrix': bool(matrix),
         'distance': distance, 'label': label, 'table': table, 'num': H.get('num', []), 'cat': H['cat'], 'mcols': H.get('mcols')}
    k_lines = _hc_k_lines(n_clusters, n)
    fit = _hc_fit_lines(S)
    summary = ['print(X.groupby(cluster).mean())   # Cluster Means',
               'print(X.groupby(cluster).std(ddof=0))   # Cluster Standard Deviations (the n divisor, as JMP\'s)'] if not matrix else []
    out['code'] = '\n'.join([_head(table, rows, where, table_name, _hc_imports(S)), *fit, *k_lines,
                             *HC_CLUSTERS,
                             'cluster = np.array([number[root[i]] + 1 for i in range(n)])   # each row\'s cluster, numbered in the order of the leaves (Save Clusters)',
                             'print(pd.Series(cluster, index=X.index + 1).value_counts().sort_index())   # the clusters\' sizes (the buttons under the dendrogram)',
                             *summary,
                             'first = list(range(n)) + [0] * (n - 1)   # the Clustering History: each join\'s leader and joiner, the first rows of the clusters joined',
                             'history = []',
                             'for s, (a, b) in enumerate(Z[:, :2].astype(int)):',
                             '    lead, join = sorted((first[a], first[b]))',
                             '    first[n + s] = lead',
                             '    history.append((n - 1 - s, heights[s], names[lead], names[join]))',
                             'print(pd.DataFrame(history[::-1], columns=["Number of Clusters", "Distance", "Leader", "Joiner"]))'])
    head = lambda imports: _plot_head(table, rows, where, table_name, imports)  # noqa: E731
    out.update(_hc_codes(head, S, n, p, k_lines, coords, bool(silhouette) and n <= HC_MAX_SILHOUETTE))
    return out


@api('hcluster.save')
def hcluster_save(table, columns, rows=None, method='ward', standardize='columns', n_clusters=None, robust=False, impute=False,
                  matrix=False, distance='sqeuclidean', where=None):
    """Save Formula for Closest Cluster (JMP's): a formula column of the
    cluster whose centroid is nearest by the squared Euclidean distance, in
    the space the clustering sees (the columns standardized as the report
    standardizes them; Jaccard: present or not; Gower: over their ranges),
    the clusters those of the report's Number of Clusters. Every row of the
    By group whose columns are present gets one, excluded rows too."""
    if matrix:
        return {'error': 'a distance matrix has no columns to measure a row by: Save Formula for Closest Cluster needs the rows\' values'}
    cols = list(columns)
    distance = distance or 'sqeuclidean'
    try:
        H = _hc_data(table, cols, rows, standardize, robust, impute, False, distance, where)
        if H['n'] < 2:
            return {'error': 'fewer than two rows without missing values'}
        Z = _hc_linkage(H, method, distance)
    except ValueError as e:
        return {'error': str(e)}
    if H['Xs'] is None:
        return {'error': 'nominal columns have no centroid: Save Formula for Closest Cluster needs numeric columns'}
    from scipy.cluster.hierarchy import leaves_list
    n = H['n']
    order = leaves_list(Z)
    k = _hc_k(n_clusters, Z[:, 2], n)
    lab = cut_tree(Z[:, :2].astype(int), n, k, order)
    M = np.array([H['Xs'][lab == c].mean(0) for c in range(k)])
    refs = [formula_ref(c) for c in cols]
    if distance == 'jaccard':
        z = [f'({r} != 0)' for r in refs]
        space = 'each value present (not 0) or not'
    elif standardize == 'rows' and distance != 'gower':
        mean_ = f'Mean({", ".join(refs)})'
        sd_ = f'Std Dev({", ".join(refs)})'
        z = [f'(({r} - {mean_}) / {sd_})' for r in refs]
        space = 'each row standardized across its columns'
    else:
        z = [_fz(c, H['center'][j], H['scale'][j]) for j, c in enumerate(cols)]
        space = {'gower': 'each column over its range', 'columns': 'the columns standardized' + (' robustly (Huber)' if robust else ''), 'none': 'the columns as they are'}.get(
            'gower' if distance == 'gower' else standardize, 'the columns standardized')
    dist = [_fsum([_fsq(f'{z[j]} - {_fnum(M[c, j])}' if M[c, j] >= 0 else f'{z[j]} + {_fnum(-M[c, j])}') for j in range(len(cols))]) for c in range(k)]
    expr = _fargmin(dist, [str(c + 1) for c in range(k)], cols)
    return {'columns': [{'name': 'Closest Cluster', 'formula': _fguard(table, expr, where), 'modelingType': 'nominal',
                         'notes': f'hierarchical clustering ({method}), {k} clusters: the cluster whose centroid is nearest by the squared Euclidean distance ({space}){_by_words(table, where)}'}],
            'k': k}


def _hc_imports(S):
    imp = list(HC_IMPORTS)
    if S['matrix'] or S['distance'] not in ('sqeuclidean',) or S['cat']:
        imp = ['from scipy.cluster.hierarchy import leaves_list, linkage', 'from scipy.spatial.distance import pdist, squareform']
    if S['robust'] and S['standardize'] == 'columns' and S['distance'] not in ('gower', 'jaccard'):
        imp.append('from statsmodels.robust.scale import Huber')
    return imp


HC_IMPORTS = ['from scipy.cluster.hierarchy import leaves_list, linkage', 'from scipy.spatial.distance import pdist']


def _hc_k_lines(n_clusters, n):
    """The report's number of clusters, or the lines that find the page's
    default: where the joining distance jumps most."""
    if n_clusters is not None:
        return [f'k = {max(1, min(n, int(math.floor(float(n_clusters) + 0.5))))}   # Number of Clusters, as the report has it']   # (rounded as the page rounds)
    return [HC_K, *HC_K_DEF]


GOWER_DEF = [
    'def gower(X, cat):',
    '    """Gower\'s dissimilarity of every pair of rows (condensed, as pdist): the mean over the columns of |x_i − x_j|/range',
    '    for a numeric column and 0 or 1 (the same level or not) for a categorical one."""',
    '    D = np.zeros(len(X) * (len(X) - 1) // 2)',
    '    for j in range(X.shape[1]):',
    '        if cat[j]:',
    '            D += pdist(pd.factorize(pd.Series(X[:, j], dtype=object))[0].astype(float)[:, None], "hamming")',
    '        else:',
    '            v = X[:, j].astype(float)',
    '            if np.ptp(v) > 0:',
    '                D += pdist(v[:, None], "cityblock") / np.ptp(v)',
    '    return D / X.shape[1]']
HUBER_LINES = [
    'center, scale = [], []   # Standardize Robustly: Huber\'s estimates of each column\'s location and scale',
    'for v in Xs.T:',
    '    try:',
    '        loc, sc = (float(np.asarray(e).item()) for e in Huber(maxiter=100)(v))',
    '        assert np.isfinite(loc) and np.isfinite(sc) and sc > 0',
    '    except Exception:   # most values equal: the mean and the standard deviation',
    '        loc, sc = v.mean(), v.std(ddof=1)',
    '    center.append(loc)',
    '    scale.append(sc if sc > 0 else 1.0)',
    'Xs = (Xs - np.array(center)) / np.array(scale)   # Standardize By: Columns, robustly']


def _hc_fit_lines(S):
    """Lines that cluster the rows as hcluster.fit does: X (the rows, a
    DataFrame of the numeric columns), Xs (the data the clustering sees), Z
    (the joins, with JMP's distances, or with the Distance option's), n,
    heights, order, and the rows' names."""
    cols, method, standardize, distance = S['cols'], S['method'], S['standardize'], S['distance']
    label, table = S['label'], S['table']
    L = []
    if S['matrix']:
        L += [f'X = df[{_cols_expr(S["mcols"])}]   # the distance matrix of the report\'s objects: a row and a column for each',
              'D = X.to_numpy(float)',
              'D = np.where(np.isnan(D), D.T, D)   # a missing entry from the other side of the diagonal',
              'D = (D + D.T) / 2',
              'np.fill_diagonal(D, 0)',
              f'Z = linkage(squareform(D, checks=False), "{method}")   # the joins of the distances as they are{" (taken as Euclidean)" if method in ("ward", "centroid") else ""}']
        if method == 'ward':
            L.append('Z[:, 2] = Z[:, 2] ** 2 / 2   # JMP\'s Ward heights: the increase in the within-cluster sum of squares')
        elif method == 'centroid':
            L.append('Z[:, 2] = Z[:, 2] ** 2   # JMP\'s centroid heights: the squared distance of the means')
    else:
        num, cat = S['num'], S['cat']
        if S['impute']:
            L += [f'X = df[{_cols_expr(num)}]',
                  *([f'X = X[df[{_cols_expr(cat)}].notna().all(axis=1) & (df[{_cols_expr(cat)}] != "").all(axis=1)]   # the rows with every level'] if cat else []),
                  'X = X[X.notna().any(axis=1)]   # the rows with a value in some column (Missing value imputation)',
                  '',
                  *inspect.getsource(_import_tables().mvn_em).rstrip().split('\n'), '', '',
                  *inspect.getsource(_import_tables().conditional_means).rstrip().split('\n'), '', '',
                  'mu, sigma, _ = mvn_em(X.to_numpy(float))   # a multivariate normal fitted by EM',
                  'X = pd.DataFrame(conditional_means(X.to_numpy(float), mu, sigma), index=X.index, columns=X.columns)   # each missing value: its conditional mean']
        else:
            L.append(f'X = df[{_cols_expr(cols)}].dropna()   # the rows with every column' if not cat else f'd = df[{_cols_expr(cols)}].dropna()   # the rows with every column')
            if cat:
                L.append(f'd = d[(d[{_cols_expr(cat)}] != "").all(axis=1)]')
                L.append(f'X = d[{_cols_expr(num)}]   # the numeric columns')
        if distance == 'gower':
            if S['impute'] and cat:
                L.append(f'd = df.loc[X.index, {_cols_expr(cols)}]')
                L.append(f'd[{_cols_expr(num)}] = X')
            elif not cat:
                L.append('d = X')
            L += ['', *GOWER_DEF, '',
                  f'cat = {[c in cat for c in cols]!r}   # the categorical columns (nominal, or text)',
                  f'Din = gower(d[{_cols_expr(cols)}].to_numpy(object), cat)   # Gower\'s dissimilarities: Standardize By is not used']
            if not cat:
                L.append('Xs = (X.to_numpy() - X.to_numpy().min(0)) / np.where(np.ptp(X.to_numpy(), axis=0) > 0, np.ptp(X.to_numpy(), axis=0), 1.0)   # each column over its range')
        elif distance == 'jaccard':
            L += ['Xs = (X.to_numpy() != 0).astype(float)   # present (not 0) or absent: Standardize By is not used',
                  'Din = pdist(Xs.astype(bool), "jaccard")   # the Jaccard distances']
        else:
            L.append('Xs = X.to_numpy()')
            if standardize == 'columns':
                if S['robust']:
                    L += HUBER_LINES
                else:
                    L += ['sd = Xs.std(0, ddof=1); sd = np.where(sd > 0, sd, 1.0)', 'Xs = (Xs - Xs.mean(0)) / sd   # Standardize By: Columns']
            elif standardize == 'rows':
                L += ['sd = Xs.std(1, ddof=1); sd = np.where(sd > 0, sd, 1.0)', 'Xs = (Xs - Xs.mean(1, keepdims=True)) / sd[:, None]   # Standardize By: Rows']
            if distance == 'mahalanobis':
                L.append('Din = pdist(Xs, "mahalanobis", VI=np.linalg.pinv(np.cov(Xs, rowvar=False).reshape(Xs.shape[1], -1)))   # the Mahalanobis distances')
            elif distance in ('euclidean', 'cityblock', 'chebyshev', 'correlation'):
                L.append(f'Din = pdist(Xs, "{distance}")   # the {HC_DISTANCES[distance]} distances')
        if distance == 'sqeuclidean':
            L += _linkage_lines('Z', 'Xs', method)
        else:
            L.append(f'Z = linkage(Din, "{method}")   # {method} linkage of the {HC_DISTANCES[distance]} distances')
    L += ['n = len(X)', 'heights, order = Z[:, 2], leaves_list(Z)   # the distance of each join; the leaves in the order of the dendrogram']
    if label:
        numeric = table is not None and label in data.TABLES.get(table, {}).get('meta', {}) and data.meta(table, label).get('dataType') == 'numeric'
        text = 'f"{v:.10g}"' if numeric else 'str(v)'
        L.append(f'names = [str(r + 1) if pd.isna(v) else {text} for r, v in df.loc[X.index, {J(label)}].items()]   # each row\'s label (its number without one)')
    else:
        L.append('names = [str(r + 1) for r in X.index]   # each row\'s number')
    return L


def _import_tables():
    from . import tables
    return tables


def _linkage_lines(Z, X, method, what=''):
    """The lines that join the rows of X with scipy's linkage and JMP's distances."""
    return {'single': [f'{Z} = linkage(pdist({X}, "sqeuclidean"), "single")   # {what}the smallest squared distance, as JMP'],
            'complete': [f'{Z} = linkage(pdist({X}, "sqeuclidean"), "complete")   # {what}the largest squared distance, as JMP'],
            'average': [f'{Z} = linkage(pdist({X}, "sqeuclidean"), "average")   # {what}the mean squared distance, as JMP'],
            'centroid': [f'{Z} = linkage({X}, "centroid")', f'{Z}[:, 2] = {Z}[:, 2] ** 2   # {what}JMP: the squared distance of the means'],
            'ward': [f'{Z} = linkage({X}, "ward")', f'{Z}[:, 2] = {Z}[:, 2] ** 2 / 2   # {what}JMP: the increase in the within-cluster sum of squares']}[method]


# The report's choices in Hierarchical Cluster's graphs: the page writes them
# into these lines (so that a new number of clusters needs no new fit).
HC_K = "k = None   # Number of Clusters: None takes the report's default"
HC_COLOR = 'color_clusters = False   # Color Clusters'
HC_K_DEF = [
    'if k is None:   # where the joining distance jumps most: the largest ratio of a join to the one before, 2 to 10 clusters',
    '    k, ratio = min(3, n), -np.inf',
    '    for q in range(2, min(10, n - 1) + 1):',
    '        up, down = heights[n - q], heights[n - q - 1]',
    '        r = up / down if down > 0 else (np.inf if up > 0 else 0)',
    '        if r > ratio:',
    '            k, ratio = q, r',
    'k = max(1, min(n, round(k)))']
# The k clusters as the page makes them: the first n − k joins, each cluster
# numbered in the order of the leaves of the dendrogram.
HC_CLUSTERS = [
    'merges = Z[:, :2].astype(int)',
    'parent = np.full(2 * n - 1, -1)',
    'for s, (a, b) in enumerate(merges):',
    '    parent[a] = parent[b] = n + s',
    'root = np.arange(2 * n - 1)   # the k clusters are the first n − k joins: each node\'s highest join among them',
    'for v in range(2 * n - k - 1, -1, -1):',
    '    if 0 <= parent[v] < 2 * n - k:',
    '        root[v] = root[parent[v]]',
    'number = {}   # the clusters numbered in the order of the leaves',
    'for leaf in order:',
    '    number.setdefault(root[leaf], len(number))']
CCC_DEF = [
    'def ccc(ev, n, q, r2):',
    '    """Sarle\'s (1983) cubic clustering criterion of q clusters with this R², as SAS computes it."""',
    '    s = np.sqrt(np.maximum(np.sort(ev)[::-1], 0))',
    '    s = s[s > 0]',
    '    p = len(s)',
    '    if q < 2 or q >= n or p == 0 or not r2 < 1:',
    '        return np.nan',
    '    pstar = 1',
    '    for j in range(1, min(p, q - 1) + 1):',
    '        if s[j - 1] / (np.prod(s[:j]) / q) ** (1 / j) >= 1:',
    '            pstar = j',
    '    u = s / (np.prod(s[:pstar]) / q) ** (1 / pstar)',
    '    b = np.sum(1 / (n + u[:pstar])) + np.sum(u[pstar:] ** 2 / (n + u[pstar:]))',
    '    er2 = 1 - (b / np.sum(u * u)) * ((n - q) ** 2 / n) * (1 + 4 / n)   # the R² expected of uniform data',
    '    return np.log((1 - er2) / (1 - r2)) * np.sqrt(n * pstar / 2) / (0.001 + er2) ** 1.2']
SILHOUETTE_DEF = [
    'def silhouettes(D, lab):',
    '    """Rousseeuw\'s silhouette of each row: (b − a)/max(a, b), a the mean dissimilarity to the other rows of its cluster,',
    '    b the smallest mean dissimilarity to another cluster\'s rows; 0 for a row alone in its cluster (as scikit-learn)."""',
    '    k = lab.max() + 1',
    '    S = np.column_stack([D[:, lab == c].sum(1) for c in range(k)])   # each row\'s dissimilarities to each cluster, summed',
    '    cnt = np.bincount(lab, minlength=k)',
    '    own = cnt[lab]',
    '    a = np.where(own > 1, S[np.arange(len(lab)), lab] / np.maximum(own - 1, 1), 0.0)',
    '    M = S / cnt',
    '    M[np.arange(len(lab)), lab] = np.inf',
    '    b = M.min(1)',
    '    den = np.maximum(a, b)',
    '    return np.where((own > 1) & (den > 0), (b - a) / np.where(den > 0, den, 1), 0.0)']


def _hc_silhouette_lines(S):
    """The dissimilarities of the silhouettes, from the fit's lines: the
    clustering's own, or the Euclidean distances of Xs."""
    if S['matrix']:
        return ['Dsil = D   # the distance matrix']
    if S['distance'] == 'sqeuclidean':
        return ['Dsil = squareform(pdist(Xs, "euclidean"))   # the Euclidean distances of the rows as clustered']
    return [f'Dsil = squareform(Din)   # the {HC_DISTANCES[S["distance"]]} distances']


def _hc_codes(head, S, n, p, k_lines, coords, silhouette=False):
    """The code of Hierarchical Cluster's graphs: the dendrogram, the
    distance graph, the cubic clustering criterion, two-way clustering, the
    parallel coordinate plot and the silhouettes."""
    cols, method, standardize = S['cols'], S['method'], S['standardize']
    imp = _hc_imports(S)
    fit = _hc_fit_lines(S)
    labels = n <= 150
    H = max(240, 13 * n + 60) if labels else 620
    out = {}
    out['dendro_code'] = '\n'.join([
        head(imp + ['from matplotlib.collections import LineCollection']), *fit, *k_lines, HC_COLOR,
        f'colors = {J(PALETTE)}   # the page\'s palette, a colour for each cluster',
        *HC_CLUSTERS,
        'pos, hh = np.zeros(2 * n - 1), np.zeros(2 * n - 1)   # each node\'s place along the leaves, and its height',
        'pos[order] = np.arange(n)',
        'for s, (a, b) in enumerate(merges):',
        '    pos[n + s], hh[n + s] = (pos[a] + pos[b]) / 2, heights[s]',
        'segs = [[(hh[a], pos[a]), (heights[s], pos[a]), (heights[s], pos[b]), (hh[b], pos[b])] for s, (a, b) in enumerate(merges)]',
        f'ink = [(colors[number[root[n + s]] % len(colors)] if color_clusters else "{TEXT}") if s < n - k else "{MUTED}" for s in range(n - 1)]   # the joins above the cut muted',
        'cut = 0 if k >= n else heights[n - 2] * 1.04 if k <= 1 else (heights[n - k - 1] + heights[n - k]) / 2',
        _fig(600, H),
        f'ax.add_collection(LineCollection(segs, colors=ink, linewidths={_lw(1.3)}))',
        f'ax.scatter(np.zeros(n), pos[order], s={_area(3 if n > 400 else 5)}, c=[colors[number[root[leaf]] % len(colors)] for leaf in order] if color_clusters else "{BASE}", zorder=3)',
        f'ax.axvline(cut, color="{RED}", linewidth={_lw(1.2)}, linestyle="--")',
        f'ax.text(cut, 1, f" {{k}} cluster{{\'s\' if k > 1 else \'\'}}", transform=ax.get_xaxis_transform(), ha="left", va="bottom", fontsize=7, color="{RED}")',
        'ax.autoscale_view()',
        'ax.set_xlim(left=0)',
        'ax.set_ylim(n - 0.5, -0.5)   # the first leaf at the top',
        ('ax.set_yticks(np.arange(n), [names[leaf] for leaf in order], fontsize=6.8)' if labels else 'ax.set_yticks([])'),
        'ax.tick_params(axis="y", length=0)',
        'ax.set_xlabel("Distance")', 'ax.set_title("Dendrogram")', 'plt.show()'])
    out['distgraph_code'] = '\n'.join([
        head(imp), *fit, *k_lines,
        'ks = np.arange(1, min(n - 1, 60) + 1)   # the number of clusters left after each of the last joins',
        _fig(600, 200),
        f'ax.plot(ks, heights[n - 1 - ks], color="{BASE}", linewidth={_lw(1.3)}, marker="o", markersize={_msize(5)})',
        f'ax.axvline(k, color="{RED}", linewidth={_lw(1)}, linestyle="--")',
        'ax.invert_xaxis()', 'ax.set_ylim(bottom=0)', 'ax.set_xlabel("Number of Clusters")', 'ax.set_ylabel("Distance")', 'ax.set_title("Distance Graph")', 'plt.show()'])
    if coords:
        out['ccc_code'] = '\n'.join([
            head(imp), *fit,
            'Tss = ((Xs - Xs.mean(0)) ** 2).sum()',
            'sums, cnt = {i: Xs[i] for i in range(n)}, {i: 1 for i in range(n)}',
            'W, r2 = 0.0, np.full(n + 1, np.nan)',
            'for s, (a, b) in enumerate(Z[:, :2].astype(int)):   # each join of K and L adds N_K N_L/(N_K + N_L)·|mean_K − mean_L|² to the within SS',
            '    W += cnt[a] * cnt[b] / (cnt[a] + cnt[b]) * ((sums[a] / cnt[a] - sums[b] / cnt[b]) ** 2).sum()',
            '    sums[n + s], cnt[n + s] = sums.pop(a) + sums.pop(b), cnt.pop(a) + cnt.pop(b)',
            '    r2[n - s - 1] = 1 - W / Tss   # the R² of the n − s − 1 clusters',
            '', *CCC_DEF, '',
            'ev = np.linalg.eigvalsh(np.cov(Xs, rowvar=False).reshape(Xs.shape[1], -1))   # of the covariance matrix',
            'ks = np.arange(1, int(min(n - 1, max(10, round(n / 10)))) + 1)',
            'crit = [ccc(ev, n, q, r2[q]) for q in ks]',
            _fig(420, 240),
            f'ax.plot(ks, crit, color="{BASE}", linewidth={_lw(2)}, marker="o", markersize={_msize(6)})',
            'ax.set_xlabel("Number of Clusters")', 'ax.set_ylabel("CCC")', 'ax.set_title("Cubic clustering criterion")', 'plt.show()'])
    if coords and p >= 2:
        tall = n <= 150
        col_method = 'ward' if method in ('ward', 'centroid') else method
        if standardize == 'none' or S['distance'] in ('gower', 'jaccard'):
            scale = ['im = ax.imshow(M, aspect="auto", cmap="viridis")   # the values']
        else:
            scale = [f'cmap = LinearSegmentedColormap.from_list("page", {J(DIVERGING)})   # the page\'s blue to red, centred at 0',
                     'm = np.abs(M).max()', 'im = ax.imshow(M, aspect="auto", cmap=cmap, vmin=-m, vmax=m)   # the standardized values']
        out['twoway_code'] = '\n'.join([
            head(imp + ([] if standardize == 'none' or S['distance'] in ('gower', 'jaccard') else ['from matplotlib.colors import LinearSegmentedColormap'])), *fit,
            *_linkage_lines('Zc', 'Xs.T', col_method, 'the columns, clustered too: '),
            'col_order = leaves_list(Zc)',
            f'cols = {J(cols)}',
            'M = Xs[np.ix_(order, col_order)]   # the rows in the dendrogram\'s order, the columns in their own',
            _fig(min(760, 120 + 40 * p), max(260, 13 * n + 90) if tall else 600), *scale,
            'ax.set_xticks(range(len(col_order)), [cols[j] for j in col_order], rotation=35, ha="right")',
            ('ax.set_yticks(range(n), [names[i] for i in order], fontsize=6.8)' if tall else 'ax.set_yticks([])'),
            'fig.colorbar(im, ax=ax, shrink=0.8)', 'ax.set_title("Two way clustering")', 'plt.show()'])
    if not S['matrix'] and S['num']:
        num = S['num']
        out['parallel_code'] = '\n'.join([
            head(imp + ['from matplotlib.collections import LineCollection']), *fit, *k_lines, *HC_CLUSTERS,
            'lab = np.array([number[root[i]] for i in range(n)])   # each row\'s cluster (0, 1, ...)',
            f'colors = {J(PALETTE)}   # the page\'s palette, a colour for each cluster',
            f'names = {J(num)}',
            f'V = X[names].to_numpy(float)',
            'mu, sd = V.mean(0), V.std(0, ddof=1)',
            'sd = np.where(sd > 0, sd, 1.0)',
            'Zp = (V - mu) / sd   # each value standardized by its column\'s mean and standard deviation over the rows clustered',
            'means = np.array([V[lab == c].mean(0) for c in range(k)])',
            _fig(min(760, 180 + 90 * len(num)), 320),
            f'ax.axhline(0, color="{MUTED}", linewidth={_lw(1)}, zorder=0)',
            f'show_rows = {len(num)} * len(Zp) <= 30000   # every row\'s line, with up to 30000 values',
            'for c in range(k):',
            '    color = colors[c % len(colors)]',
            '    if show_rows:',
            f'        ax.add_collection(LineCollection([list(zip(range(len(names)), z)) for z in Zp[lab == c]], colors=color, linewidths={_lw(0.6)}, alpha=0.25))',
            f'    ax.plot(range(len(names)), (means[c] - mu) / sd, color=color, linewidth={_lw(3)}, marker="o", markersize={_msize(7)}, label=f"Cluster {{c + 1}}")   # the cluster\'s mean',
            'ax.set_xticks(range(len(names)), names)',
            'ax.set_ylabel("Standardized value")',
            'ax.legend(frameon=False, fontsize=7.5)',
            'ax.set_title(f"Parallel coordinates, {k} clusters")', 'plt.show()'])
    if silhouette:
        imp_s = imp if 'squareform' in ' '.join(imp) else [x.replace('import pdist', 'import pdist, squareform') for x in imp]
        sil = [head(imp_s), *fit, *k_lines, *HC_CLUSTERS, 'lab = np.array([number[root[i]] for i in range(n)])   # each row\'s cluster (0, 1, ...)',
               *_hc_silhouette_lines(S), '', *SILHOUETTE_DEF, '']
        out['silhouette_code'] = '\n'.join([
            *sil,
            's = silhouettes(Dsil, lab) if k >= 2 else np.zeros(n)',
            'print(pd.DataFrame({"Cluster": lab + 1, "Silhouette": s}, index=X.index + 1).groupby("Cluster")["Silhouette"].agg(["count", "mean"]), s.mean())',
            f'colors = {J(PALETTE)}   # the page\'s palette, a colour for each cluster',
            'o = np.lexsort((-s, lab))   # the rows by cluster, each cluster\'s largest first',
            _fig(560, max(240, min(620, 3 * n + 80))),
            'ax.barh(np.arange(n), s[o], height=1.0, color=[colors[c % len(colors)] for c in lab[o]])',
            f'ax.axvline(s.mean(), color="{RED}", linewidth={_lw(1.2)}, linestyle="--")   # the mean silhouette',
            'ax.set_xlim(min(-0.1, s.min()) - 0.02, 1)   # the page\'s range: to 1, and a little below 0 or the smallest',
            'ax.set_ylim(n - 0.5, -0.5)', 'ax.set_yticks([])',
            'ax.set_xlabel("Silhouette")', 'ax.set_title(f"Silhouettes, {k} clusters")', 'plt.show()'])
        out['silhouette_k_code'] = '\n'.join([
            *sil,
            'ks, means = [], []',
            'for q in range(2, min(30, n - 1) + 1):   # the tree cut into q clusters, as the page cuts it',
            '    root_q = np.arange(2 * n - 1)',
            '    for v in range(2 * n - q - 1, -1, -1):',
            '        if 0 <= parent[v] < 2 * n - q:',
            '            root_q[v] = root_q[parent[v]]',
            '    num_q = {}',
            '    for leaf in order:',
            '        num_q.setdefault(root_q[leaf], len(num_q))',
            '    ks.append(q)',
            '    means.append(silhouettes(Dsil, np.array([num_q[root_q[i]] for i in range(n)])).mean())',
            _fig(420, 240),
            f'ax.plot(ks, means, color="{BASE}", linewidth={_lw(1.6)}, marker="o", markersize={_msize(6)})',
            f'ax.axvline(k, color="{RED}", linewidth={_lw(1)}, linestyle="--")   # the clusters shown',
            'ax.set_xlabel("Number of Clusters")', 'ax.set_ylabel("Mean Silhouette")', 'ax.set_title("Mean silhouette by number of clusters")', 'plt.show()'])
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


def lloyd_steps(X, C, w, steps=None, max_iter=300, tol=1e-10):
    """Lloyd's k-means a step at a time (K Means' Single Step): each step
    assigns every row to its nearest centre and moves each centre to the
    weighted mean of its rows; `steps` of them (None: until the centres stop
    moving, at most max_iter). Returns the labels of the last assignment,
    the centres (their means), the steps done, the last relative change of
    the centres, the within sum of squares and whether they stopped moving."""
    k, xx = len(C), (X * X).sum(1)
    scale = float(np.sqrt(((X - X.mean(0)) ** 2).sum(1).mean())) or 1.0
    it, change, lab = 0, float('nan'), None
    limit = max_iter if steps is None else int(steps)
    while it < limit:
        it += 1
        lab = np.maximum(xx[:, None] - 2 * X @ C.T + (C * C).sum(1)[None, :], 0).argmin(1)   # the nearest centre
        new = C.copy()
        for j in range(k):
            m = lab == j
            if m.any():
                new[j] = (w[m, None] * X[m]).sum(0) / w[m].sum()   # the weighted mean of its rows
        change = float(np.sqrt(((new - C) ** 2).sum(1)).max()) / scale
        C = new
        if change <= tol:
            break
    wss = float((w * ((X - C[lab]) ** 2).sum(1)).sum()) if lab is not None else float('nan')
    return lab, C, it, change, wss, bool(change <= tol)


@api('kmeans.fit')
def kmeans_fit(table, columns, rows=None, k_min=3, k_max=None, standardize=True, seed=20260926, restarts=10, max_iter=300,
               weight=None, freq=None, single=False, steps=None, where=None, table_name='data'):
    """k-means for each k in a range: k-means++ starts (seeded) and Lloyd's
    iterations, the best of several restarts by the within sum of squares.
    Each fit gets the cubic clustering criterion (Sarle 1983), the pseudo F
    (Calinski-Harabasz) and R-square; the clusters are numbered by size.
    single (JMP's Single Step): one k-means++ start for each k, from the same
    stream, and steps[k] of Lloyd's steps from it (0: the starting centres
    only; None: until they stop moving); the clusters keep the numbers of
    their starting centres."""
    cols = list(columns)
    steps = {int(a): (None if b is None else max(0, int(b))) for a, b in (steps or {}).items()}
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
        if single:
            C0 = _kmeanspp(X, k, rng)
            s_k = steps.get(k, 0)
            if s_k == 0:   # the starting centres, no rows assigned yet (JMP: no cluster assignments)
                seeds = mu + sd * C0 if standardize else C0
                fits.append({'k': k, 'step': 0, 'labels': None, 'seeds': _mat(seeds), 'converged': False, 'counts': None, 'means': None, 'sds': None,
                             'iterations': 0, 'criterion': None, 'wss': None, 'r2': None, 'er2': None, 'ccc': None, 'pseudo_f': None, 'distance': None,
                             'centers_scaled': _mat(C0)})
                continue
            lab, C, it, change, wss, conv = lloyd_steps(X, C0, w, s_k, max_iter)
        else:
            best = None
            for _ in range(max(1, int(restarts))):
                C0 = _kmeanspp(X, k, rng)
                res = lloyd(X, C0, w, max_iter)
                if best is None or res[4] < best[4] - 1e-12:
                    best = res
            lab, C, it, change, wss = best
            conv = None
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
        dist = ((X - C[lab]) ** 2).sum(1)   # the squared Euclidean distance to its cluster's centre, where the clustering is (JMP's Distance)
        fits.append({'k': k, 'labels': lab, 'counts': counts, 'means': _mat(means), 'sds': _mat(sds), 'iterations': it,
                     'criterion': change, 'wss': wss, 'r2': r2, 'er2': er2, 'ccc': cc, 'pseudo_f': psf, 'distance': dist,
                     'centers_scaled': _mat(C), 'step': it if single else None, 'converged': conv})
    best = None
    vals = [(fi['ccc'], fi['k']) for fi in fits if fi['ccc'] is not None and np.isfinite(fi['ccc'])]
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
           'standardize': bool(standardize), 'mean': mu, 'sd': sd, 'seed': int(seed), 'restarts': int(restarts), 'single': bool(single),
           'pca': {'eigenvalues': evals, 'vectors': _mat(evecs), 'scores': _mat(pcs[:, :min(p, 4)])}}
    one = {k: steps.get(k, 0) for k in range(kmin, kmax + 1)} if single else None
    out['code'] = _km_stats_code(lambda imports: _head(table, rows, where, table_name, imports), cols, weight, freq, bool(standardize), int(seed),
                                 max(1, int(restarts)), int(max_iter), kmin, kmax, one)
    head = lambda imports: _plot_head(table, rows, where, table_name, imports)  # noqa: E731
    if sum(1 for f in fits if f['labels'] is not None) >= 2:
        out['comparison_code'] = _km_stats_code(head, cols, weight, freq, bool(standardize), int(seed), max(1, int(restarts)), int(max_iter), kmin, kmax, one, chart=True)
    for f in fits:
        if f['labels'] is not None:
            f.update(_km_codes(head, cols, weight, freq, bool(standardize), int(seed), max(1, int(restarts)), int(max_iter), kmin, f['k'], p, one))
    return out


@api('kmeans.save')
def kmeans_save(table, columns, k, rows=None, k_min=3, k_max=None, standardize=True, seed=20260926, restarts=10, max_iter=300,
                weight=None, freq=None, single=False, steps=None, what='clusters', where=None):
    """K Means' saved columns, for the fit with k clusters of this report.
    clusters: Cluster and Distance (the squared Euclidean distance to the
    cluster's centre, where the clustering is: the columns scaled by their
    standard deviations, or as they are) for every row of the By group
    whose columns are present, each in the cluster of the nearest centre
    (the report's own rows as the report has them); formula: Cluster
    Formula, that nearest centre as a live formula; distances: the k
    squared distances as formulas (JMP's Save Distance Formulas). The
    report's own rows keep its clusters: with Single Step before the end they
    were assigned to the centres before the last move, so there the nearest
    centre (the formula's rule) can differ."""
    cols = list(columns)
    r = kmeans_fit(table, cols, rows, k_min, k_max, standardize, seed, restarts, max_iter, weight, freq, single, steps)
    if 'error' in r:
        return r
    f = next((x for x in r['fits'] if x['k'] == int(k)), None)
    if f is None:
        return {'error': f'no fit with {k} clusters in this report'}
    if f['labels'] is None:
        return {'error': 'no clusters yet: Step or Go assigns the rows to the starting centres'}
    k = f['k']
    mu, sd = np.asarray(r['mean'], float), np.asarray(r['sd'], float)
    C = np.asarray(f['centers_scaled'], float)
    scaled = bool(r['standardize'])
    space = 'the columns scaled by their standard deviations' if scaled else 'the columns in their own units'
    by = _by_words(table, where)
    if what == 'clusters':
        idx, X0 = _present_rows(table, cols, where)
        Z = (X0 - mu) / sd if scaled else X0
        D = ((Z[:, None, :] - C[None, :, :]) ** 2).sum(2)
        lab = D.argmin(1)
        # the report's rows keep the report's clusters (the same once the fit has converged; Single Step's
        # earlier steps assigned them to the centres before the last move)
        own = dict(zip(np.asarray(r['rows'], int).tolist(), np.asarray(f['labels'], int).tolist()))
        lab = np.array([own.get(int(i), int(c)) for i, c in zip(idx, lab)], dtype=int)
        return {'columns': [
            {'name': 'Cluster', 'rows': idx, 'values': lab + 1, 'modelingType': 'nominal',
             'notes': f'k-means, {k} clusters: the nearest cluster centre ({space}){by}'},
            {'name': 'Distance', 'rows': idx, 'values': D[np.arange(len(idx)), lab],
             'notes': f'k-means, {k} clusters: the squared Euclidean distance to the nearest cluster centre ({space}){by}'}],
            'n_rows': r['n_rows']}
    # the squared distance to each centre: ((x − centre)/sd)² summed over the columns (centre = mu + sd · the scaled centre)
    M = mu + sd * C if scaled else C
    dist = [_fsum([_fsq(_fz(c, M[q, j], sd[j] if scaled else 1.0)) for j, c in enumerate(cols)]) for q in range(k)]
    if what == 'distances':
        return {'columns': [{'name': f'Distance to Cluster {q + 1}', 'formula': _fguard(table, dist[q], where),
                             'notes': f'k-means, {k} clusters: the squared Euclidean distance to the centre of cluster {q + 1} ({space}){by}'}
                            for q in range(k)], 'n_rows': r['n_rows']}
    return {'columns': [{'name': 'Cluster Formula', 'formula': _fguard(table, _fargmin(dist, [str(q + 1) for q in range(k)], cols), where),
                         'modelingType': 'nominal',
                         'notes': f'k-means, {k} clusters: the cluster of the nearest centre, by the squared Euclidean distance ({space}){by}'}],
            'n_rows': r['n_rows']}


# The report's choice in a k-means biplot, which the page writes into this line.
KM_RAYS = 'show_rays = True   # Biplot Rays'
KMEANS_DEF = [
    'def kmeans_pp(X, k, rng):',
    '    """k-means++ starts: a first row at random, then each next with a probability in proportion to its squared distance to the nearest start."""',
    '    n = len(X)',
    '    idx = [int(rng.integers(n))]',
    '    d2 = ((X - X[idx[0]]) ** 2).sum(1)',
    '    for _ in range(1, k):',
    '        tot = d2.sum()',
    '        cand = int(rng.integers(n)) if tot <= 0 else int(rng.choice(n, p=d2 / tot))',
    '        idx.append(cand)',
    '        d2 = np.minimum(d2, ((X - X[cand]) ** 2).sum(1))',
    '    return X[idx].copy()',
    '',
    '',
    'def lloyd(X, C, w, max_iter, tol=1e-10):',
    '    """Lloyd\'s k-means from the centres C: each row to its nearest centre, each centre to the weighted mean of its rows."""',
    '    k, xx = len(C), (X * X).sum(1)',
    '    scale = float(np.sqrt(((X - X.mean(0)) ** 2).sum(1).mean())) or 1.0',
    '',
    '    def dist(C):   # the squared distances of every row to every centre',
    '        return np.maximum(xx[:, None] - 2 * X @ C.T + (C * C).sum(1)[None, :], 0)',
    '    it, change = 0, np.nan',
    '    for it in range(1, max_iter + 1):',
    '        lab = dist(C).argmin(1)',
    '        W = np.zeros((k, len(X)))',
    '        W[lab, np.arange(len(X))] = w',
    '        tot = W.sum(1)',
    '        new, has = C.copy(), tot > 0',
    '        new[has] = (W[has] @ X) / tot[has, None]',
    '        change = float(np.sqrt(((new - C) ** 2).sum(1)).max()) / scale',
    '        C = new',
    '        if change <= tol:',
    '            break',
    '    lab = dist(C).argmin(1)',
    '    return lab, C, float((w * ((X - C[lab]) ** 2).sum(1)).sum()), it, change   # the clusters, the centres, the within SS, the steps, the last change']


def _km_stats_code(head, cols, weight, freq, standardize, seed, restarts, max_iter, kmin, kmax, single=None, chart=False):
    """The code of K Means' report: the report's own k-means (seeded
    k-means++ starts, Lloyd's iterations, the best of the restarts) for each
    number of clusters in turn, from one stream of random numbers, with the
    Cluster Comparison (CCC, pseudo F, RSquare) and each fit's clusters.
    single: {k: the steps of Single Step} (one start for each k); chart: the
    code of the Cluster Comparison's graph of the criteria by k instead."""
    if single is None:
        fit = [f'    for _ in range({restarts}):   # the best of {restarts} starts by the within sum of squares',
               f'        fit = lloyd(X, kmeans_pp(X, k, rng), w, {max_iter})',
               '        if best is None or fit[2] < best[2] - 1e-12:',
               '            best = fit',
               '    lab, C, wss, steps, change = best',
               '    order = np.argsort(-np.array([w[lab == j].sum() for j in range(k)]), kind="stable")   # the clusters numbered by size',
               '    remap = np.empty(k, int); remap[order] = np.arange(k); lab = remap[lab]']
        defs = KMEANS_DEF
    else:
        fit = ['    C0 = kmeans_pp(X, k, rng)   # Single Step: one start for each number of clusters, from the one stream',
               f'    if single_steps[k] == 0:',
               '        continue   # the starting centres only: no rows assigned yet',
               f'    lab, C, steps, change, wss, stopped = lloyd_steps(X, C0, w, single_steps[k], {max_iter})   # the clusters keep their starting centres\' numbers']
        defs = KMEANS_DEF + ['', '', *inspect.getsource(lloyd_steps).rstrip().split('\n')]
    L = [head(['import matplotlib.pyplot as plt'] if chart and 'plt' not in head([]) else []), *_weights_lines(cols, weight, freq),
         'X0 = X.to_numpy()',
         'mu = (w[:, None] * X0).sum(0) / w.sum()',
         'sd = np.sqrt((w[:, None] * (X0 - mu) ** 2).sum(0) / (w.sum() - 1)); sd = np.where(sd > 0, sd, 1.0)',
         'X = (X0 - mu) / sd   # Columns Scaled Individually' if standardize else 'X = X0.copy()   # the columns in their own units',
         '', *defs, '', *CCC_DEF, '',
         'Tss = (w[:, None] * (X - (w[:, None] * X).sum(0) / w.sum()) ** 2).sum()   # the total sum of squares',
         'm = (w[:, None] * X).sum(0) / w.sum()',
         'ev = np.linalg.eigvalsh((w[:, None] * (X - m)).T @ (X - m) / (w.sum() - 1))   # the eigenvalues of the covariances, for the CCC',
         f'rng = np.random.default_rng({seed})   # the report\'s seed',
         f'names = {J(cols)}',
         *([f'single_steps = {{{", ".join(f"{k}: {v!r}" for k, v in single.items())}}}   # Single Step: the steps of each number of clusters (None: until nothing moves)'] if single is not None else []),
         'comparison, fits = [], {}',
         f'for k in range({kmin}, {kmax + 1}):   # each number of clusters in turn',
         '    best = None',
         *fit,
         '    r2 = 1 - wss / Tss',
         '    comparison.append({"NCluster": k, "CCC": ccc(ev, w.sum(), k, r2) if k >= 2 else np.nan,',
         '                       "Pseudo F": (r2 / (k - 1)) / ((1 - r2) / (w.sum() - k)) if k >= 2 and r2 < 1 else np.nan,',
         '                       "RSquare": r2, "Within SS": wss, "Step": steps, "Criterion": change})',
         '    fits[k] = lab']
    if chart:
        L += ['cmp = pd.DataFrame(comparison)',
              'best = cmp.loc[cmp["CCC"].idxmax(), "NCluster"] if cmp["CCC"].notna().any() else None   # the Optimal CCC',
              f'fig, axes = plt.subplots(2, 2, figsize=(5.6, 4.2), sharex=True, layout="constrained")',
              'for ax, key in zip(axes.flat, ["CCC", "Pseudo F", "RSquare", "Within SS"]):',
              f'    ax.plot(cmp["NCluster"], cmp[key], color="{BASE}", linewidth={_lw(1.6)}, marker="o", markersize={_msize(6)})',
              '    if best is not None:',
              f'        ax.axvline(best, color="{RED}", linewidth={_lw(1)}, linestyle="--")   # the Optimal CCC',
              '    ax.set_title(key, fontsize=9)',
              'for ax in axes[1]:',
              '    ax.set_xlabel("NCluster")',
              'fig.suptitle("Cluster criteria by number of clusters", fontsize=10)', 'plt.show()']
        return '\n'.join(L)
    L += ['    counts = [w[lab == c].sum() for c in range(k)]',
          '    means = [(w[lab == c, None] * X0[lab == c]).sum(0) / counts[c] if counts[c] > 0 else np.full(len(names), np.nan) for c in range(k)]',
          '    sds = [np.sqrt((w[lab == c, None] * (X0[lab == c] - means[c]) ** 2).sum(0) / counts[c]) if counts[c] > 0 else np.full(len(names), np.nan) for c in range(k)]',
          '    print(f"K Means NCluster={k}: the counts", counts)',
          '    print(pd.DataFrame(means, columns=names, index=range(1, k + 1)))   # Cluster Means',
          '    print(pd.DataFrame(sds, columns=names, index=range(1, k + 1)))   # Cluster Standard Deviations (the n divisor)',
          'print(pd.DataFrame(comparison))   # Cluster Comparison: the largest CCC is the Optimal CCC']
    return '\n'.join(L)


def _km_fit_lines(cols, weight, freq, standardize, seed, restarts, max_iter, kmin, k, single=None):
    """Lines that fit k-means as kmeans.fit does: X0 (the rows), w, mu and sd,
    X (the data clustered), and lab, each row's cluster numbered by size
    (with Single Step, single: {k: steps}, by its starting centre)."""
    L = _weights_lines(cols, weight, freq) + ['X0 = X.to_numpy()',
                                              'mu = (w[:, None] * X0).sum(0) / w.sum()',
                                              'sd = np.sqrt((w[:, None] * (X0 - mu) ** 2).sum(0) / (w.sum() - 1)); sd = np.where(sd > 0, sd, 1.0)',
                                              'X = (X0 - mu) / sd   # Columns Scaled Individually' if standardize else 'X = X0.copy()   # the columns in their own units',
                                              '', *KMEANS_DEF, *(['', '', *inspect.getsource(lloyd_steps).rstrip().split('\n')] if single is not None else []), '',
                                              f'rng = np.random.default_rng({seed})   # the report\'s seed']
    if single is not None:
        L += [f'for q in range({kmin}, {k + 1}):   # Single Step: one start for each number of clusters, {kmin} to {k}, from one stream of random numbers',
              '    C0 = kmeans_pp(X, q, rng)',
              f'k = {k}',
              f'lab = lloyd_steps(X, C0, w, {single.get(k)!r}, {max_iter})[0]   # {"until nothing moves" if single.get(k) is None else f"{single.get(k)} steps"}; the clusters keep their starting centres\' numbers',
              'counts = np.array([w[lab == c].sum() for c in range(k)])']
        return L
    fit = [f'    for _ in range({restarts}):   # the best of {restarts} starts by the within sum of squares',
           f'        fit = lloyd(X, kmeans_pp(X, q, rng), w, {max_iter})',
           '        if best is None or fit[2] < best[2] - 1e-12:',
           '            best = fit']
    if kmin < k:
        L += [f'for q in range({kmin}, {k + 1}):   # the report fits {kmin} to {k} clusters in turn, from one stream of random numbers',
              '    best = None', *fit]
    else:
        L += [f'q, best = {k}, None', *[ln[4:] for ln in fit]]
    L += ['lab = best[0]',
          f'k = {k}',
          'order = np.argsort(-np.array([w[lab == j].sum() for j in range(k)]), kind="stable")   # the clusters numbered by size',
          'remap = np.empty(k, int); remap[order] = np.arange(k); lab = remap[lab]',
          'counts = np.array([w[lab == c].sum() for c in range(k)])']
    return L


def _km_codes(head, cols, weight, freq, standardize, seed, restarts, max_iter, kmin, k, p, single=None):
    """The code of a k-means fit's biplot and parallel coordinate plot."""
    fit = _km_fit_lines(cols, weight, freq, standardize, seed, restarts, max_iter, kmin, k, single) + [
        f'names = {J(cols)}', f'colors = {J(PALETTE)}   # the page\'s palette, a colour for each cluster']
    out = {}
    if p >= 2:
        L = [head([]), *fit,
             '',
             'def wcov(A, w):   # the weighted covariance matrix',
             '    m = (w[:, None] * A).sum(0) / w.sum()',
             '    return (w[:, None] * (A - m)).T @ (A - m) / (w.sum() - 1)',
             '',
             *ELLIPSE_DEF, '']
        if standardize:
            L += ['S = wcov(X, w); d = np.sqrt(np.diag(S)); S = S / np.outer(d, d); np.fill_diagonal(S, 1.0)   # the principal components of the correlations',
                  'ev, V = np.linalg.eigh(S); o = np.argsort(ev)[::-1]; ev, V = ev[o], V[:, o]',
                  'V = V * np.sign(V[np.abs(V).argmax(axis=0), np.arange(V.shape[1])])   # each eigenvector\'s largest entry positive',
                  'pcs = (X0 - mu) / sd @ V']
        else:
            L += ['ev, V = np.linalg.eigh(wcov(X0, w)); o = np.argsort(ev)[::-1]; ev, V = ev[o], V[:, o]   # the principal components of the covariances',
                  'V = V * np.sign(V[np.abs(V).argmax(axis=0), np.arange(V.shape[1])])   # each eigenvector\'s largest entry positive',
                  'pcs = (X0 - mu) @ V']
        L += ['x, y = pcs[:, 0], pcs[:, 1]',
              'tot = np.maximum(ev, 0).sum()',
              KM_RAYS,
              _fig(560, 420),
              f'ax.scatter(x, y, s={_area(5)}, c=[colors[c % len(colors)] for c in lab])',
              'for c in range(k):',
              '    i = lab == c',
              '    if not i.any():',
              '        continue',
              '    mx, my, color = x[i].mean(), y[i].mean(), colors[c % len(colors)]',
              '    if i.sum() > 2:   # a 90% ellipse around the cluster',
              '        C = np.cov(x[i], y[i])',
              '        sx, sy = np.sqrt(C[0, 0]), np.sqrt(C[1, 1])',
              '        ex, ey = ellipse(mx, my, sx, sy, C[0, 1] / (sx * sy) if sx > 0 and sy > 0 else 0, 0.9)',
              f'        ax.fill(ex, ey, color=color, alpha={0x22 / 255:.4g}, linewidth=0)',
              f'        ax.plot(ex, ey, color=color, linewidth={_lw(1)})',
              f'    ax.scatter([mx], [my], s=({PX} * (10 + 22 * np.sqrt(counts[c] / w.sum()))) ** 2, facecolors="none", edgecolors=color, linewidths={_lw(2)}, label=f"Cluster {{c + 1}}")   # its mean, as large as its share of the rows',
              '    ax.text(mx, my, str(c + 1), ha="center", va="center", fontsize=7.2)',
              'if show_rays:   # the columns\' directions, scaled to the spread of the rows',
              '    lmax = np.abs(V[:, :2]).max()',
              '    s = 0.8 * max(np.abs(x).max(), np.abs(y).max()) / lmax if lmax > 0 else 1.0',
              '    for name, vx, vy in zip(names, s * V[:, 0], s * V[:, 1]):',
              f'        ax.plot([0, vx], [0, vy], color="{MUTED}", linewidth={_lw(1)})',
              '        ax.text(vx, vy, name, ha="center", va="center", fontsize=7.2)',
              *_zero_lines(),
              'ax.set_xlabel(f"Prin1 ({100 * ev[0] / tot:.1f}%)")', 'ax.set_ylabel(f"Prin2 ({100 * ev[1] / tot:.1f}%)")',
              'ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1), frameon=False, fontsize=7.5)',
              f'ax.set_title("Biplot, {k} clusters")', 'plt.show()']
        out['biplot_code'] = '\n'.join(L)
    L = [head(['from matplotlib.collections import LineCollection']), *fit,
         'Z = (X0 - mu) / sd   # each value standardized by its column\'s mean and standard deviation',
         'means = np.array([(w[lab == c, None] * X0[lab == c]).sum(0) / counts[c] for c in range(k)])',
         _fig(min(760, 180 + 90 * p), 320),
         f'ax.axhline(0, color="{MUTED}", linewidth={_lw(1)}, zorder=0)',
         f'show_rows = {len(cols)} * len(Z) <= 30000   # every row\'s line, with up to 30000 values',
         'for c in range(k):',
         '    color = colors[c % len(colors)]',
         '    if show_rows:',
         f'        ax.add_collection(LineCollection([list(zip(range(len(names)), z)) for z in Z[lab == c]], colors=color, linewidths={_lw(0.6)}, alpha=0.25))',
         f'    ax.plot(range(len(names)), (means[c] - mu) / sd, color=color, linewidth={_lw(3)}, marker="o", markersize={_msize(7)}, label=f"Cluster {{c + 1}}")   # the cluster\'s mean',
         'ax.set_xticks(range(len(names)), names)',
         'ax.set_ylabel("Standardized value")',
         'ax.legend(frameon=False, fontsize=7.5)',
         f'ax.set_title("Parallel coordinates, {k} clusters")', 'plt.show()']
    out['parallel_code'] = '\n'.join(L)
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
def respscreen_fit(table, y, x, rows=None, weight=None, freq=None, max_logworth=1000, alpha=0.05, where=None, table_name='data'):
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
    out = {'results': res, 'n_tests': m, 'alpha': alpha,
           'n_sig': int(np.sum(fdr[good] < alpha)) if m else 0, 'n_sig_raw': int(np.sum(pv[good] < alpha)) if m else 0}
    levels = {c: [_level_value(v) for v in (df[c].cat.categories if hasattr(df[c], 'cat') else sorted(df[c].dropna().unique()))]
              for c in dict.fromkeys(ys + xs) if iscat[c]}
    char = {c: data.meta(table, c).get('dataType') != 'numeric' for c in levels}
    out['code'] = _rs_stats_code(lambda imports: _head(table, rows, where, table_name, imports), ys, xs, weight, freq, levels, char, alpha, cap)
    out.update(_rs_codes(lambda imports: _plot_head(table, rows, where, table_name, imports), ys, xs, weight, freq, levels, char, alpha, cap))
    return out


SCREEN_DEF = [
    'def robust_sd(y):   # a robust σ: IQR/1.349, or the standard deviation when the IQR is too small',
    '    q1, q3 = np.quantile(y, [0.25, 0.75])',
    '    return (q3 - q1) / 1.3489795 if q3 - q1 > 0 and q3 - q1 > np.ptp(y) / 20 else float(np.std(y, ddof=1))',
    '',
    '',
    'def screen(y, x, ycat, xcat, w):',
    '    """One test of y by x as Fit Y by X makes it: (p, effect size, R², statistic, DF, test), None where there is none.',
    '    w: frequency weights (Weight times Freq), or None."""',
    '    n = len(y)',
    '    if n < 3 or np.ptp(y) == 0 or np.ptp(x) == 0:',
    '        return None, None, None, None, None, None',
    '    if not ycat:',
    '        s = robust_sd(y)',
    '        if xcat:   # the Oneway ANOVA F',
    '            lv = np.unique(x)',
    '            if w is None:',
    '                groups = [y[x == v] for v in lv]',
    '                F, p = stats.f_oneway(*groups)',
    '                ssb, sst = sum(len(g) * (g.mean() - y.mean()) ** 2 for g in groups), ((y - y.mean()) ** 2).sum()',
    '            else:',
    '                fit = sm.WLS(y, np.column_stack([np.ones(n)] + [(x == v).astype(float) for v in lv[1:]]), weights=w).fit()',
    '                F, p, ssb, sst = fit.fvalue, fit.f_pvalue, fit.ess, fit.centered_tss',
    '            return p, (np.sqrt(ssb / (len(lv) - 1)) / s if s > 0 else None), (ssb / sst if sst > 0 else None), F, len(lv) - 1, "ANOVA F"',
    '        if w is None:   # the regression F',
    '            lr = stats.linregress(x, y)',
    '            p, r2 = lr.pvalue, lr.rvalue ** 2',
    '            F, ssm = (r2 * (n - 2) / (1 - r2) if r2 < 1 else np.inf), r2 * ((y - y.mean()) ** 2).sum()',
    '        else:',
    '            fit = sm.WLS(y, sm.add_constant(x), weights=w).fit()',
    '            F, p, r2, ssm = fit.fvalue, fit.f_pvalue, fit.rsquared, fit.ess',
    '        return p, (np.sqrt(ssm) / s if s > 0 else None), r2, F, 1, "Regression F"',
    '    ylv = np.unique(y)',
    '    if xcat:   # the likelihood-ratio chi-square of the contingency table',
    '        xlv = np.unique(x)',
    '        tab = np.zeros((len(ylv), len(xlv)))',
    '        np.add.at(tab, (np.searchsorted(ylv, y), np.searchsorted(xlv, x)), np.ones(n) if w is None else w)',
    '        g2, p, dof, _ = stats.chi2_contingency(tab, correction=False, lambda_="log-likelihood")',
    '        chi = stats.chi2_contingency(tab, correction=False)[0]',
    '        return p, (np.sqrt(chi / dof) if dof > 0 else None), None, g2, dof, "ChiSquare (LR)"',
    '    X = sm.add_constant(x.astype(float))   # the likelihood-ratio chi-square of the logistic fit',
    '    try:',
    '        with warnings.catch_warnings():',
    '            warnings.simplefilter("ignore")',
    '            if len(ylv) == 2:',
    '                yb = (y == ylv[1]).astype(float)',
    '                if w is None:',
    '                    llr = sm.Logit(yb, X).fit(disp=0).llr',
    '                else:',
    '                    fam = sm.families.Binomial()',
    '                    llr = 2 * (sm.GLM(yb, X, family=fam, freq_weights=w).fit().llf - sm.GLM(yb, np.ones((n, 1)), family=fam, freq_weights=w).fit().llf)',
    '                dfm = 1',
    '            else:',
    '                llr, dfm = sm.MNLogit(np.searchsorted(ylv, y), X).fit(disp=0, method="newton", maxiter=100).llr, len(ylv) - 1',
    '    except Exception:',
    '        return None, None, None, None, None, None',
    '    return stats.chi2.sf(llr, dfm), np.sqrt(max(llr, 0) / dfm), None, llr, dfm, "Logistic LR ChiSquare"']

RS_IMPORTS = ['import warnings', 'from scipy import stats', 'from statsmodels.stats.multitest import multipletests']


def _rs_fit_lines(ys, xs, weight, freq, levels, char, alpha, cap):
    """Lines that make every test of the report as it makes them: each Y by
    each X on the rows where both have a value and Weight and Freq are
    positive (their product the frequency weight), the FDR p-values, the
    LogWorths and the rank fractions."""
    L = [f'levels = {{{", ".join(f"{J(c)}: {_py_list(v)}" for c, v in levels.items())}}}   # the categorical columns\' levels, in the table\'s order',
         '',
         'def values(c):   # a column as numbers: a categorical column\'s level numbers',
         '    if c not in levels:',
         '        return df[c].to_numpy(float)',
         f'    codes = pd.Categorical(df[c].astype(str) if c in {J([c for c, v in char.items() if v])} else df[c], categories=levels[c]).codes',
         '    return np.where(codes < 0, np.nan, codes.astype(float))',
         '',
         *SCREEN_DEF, '']
    wexpr = _weight_code(weight, freq)
    if wexpr:
        L += [f'w = ({wexpr}).to_numpy(float)   # frequency weights: {"Weight times Freq" if weight and freq else "Weight" if weight else "Freq"}', 'okw = np.isfinite(w) & (w > 0)']
    else:
        L += ['w, okw = None, np.ones(len(df), dtype=bool)']
    L += ['tests, pairs, count = [], [], []   # every Y by every X',
          f'for yc in {J(ys)}:',
          f'    for xc in {J(xs)}:',
          '        if yc == xc:',
          '            continue',
          '        y, x = values(yc), values(xc)',
          '        ok = okw & np.isfinite(y) & np.isfinite(x)',
          '        tests.append(screen(y[ok], x[ok], yc in levels, xc in levels, None if w is None else w[ok]))',
          '        pairs.append((yc, xc))',
          '        count.append(ok.sum() if w is None else w[ok].sum())',
          'p, effect, r2 = (np.array([np.nan if t[j] is None else t[j] for t in tests], float) for j in range(3))',
          'good = np.isfinite(p)   # the pairs that could be tested',
          'fdr = np.full(len(p), np.nan)',
          f'fdr[good] = multipletests(np.clip(p[good], 0, 1), alpha={alpha!r}, method="fdr_bh")[1]   # Benjamini and Hochberg',
          f'cap = {float(cap)!r}   # Max Logworth',
          'fdr_logworth = np.minimum(-np.log10(np.maximum(fdr, 1e-320)), cap)',
          'rank = np.empty(len(p)); rank[np.argsort(-np.where(good, fdr_logworth, -np.inf), kind="stable")] = np.arange(1, len(p) + 1)',
          'rank_fraction = rank / good.sum()   # the tests in order of significance',
          f'alpha = {alpha!r}']
    return L


def _rs_stats_code(head, ys, xs, weight, freq, levels, char, alpha, cap):
    """The code of Response Screening's PValues table: every test as the
    report makes it (Weight and Freq as frequency weights), sorted by FDR
    LogWorth."""
    L = [head(RS_IMPORTS), *_rs_fit_lines(ys, xs, weight, freq, levels, char, alpha, cap),
         'logworth = np.minimum(-np.log10(np.maximum(p, 1e-320)), cap)',
         'res = pd.DataFrame(pairs, columns=["Y", "X"]).assign(Count=count, PValue=p, LogWorth=logworth, FDR_PValue=fdr, FDR_LogWorth=fdr_logworth,',
         '    Effect_Size=effect, Rank_Fraction=np.where(good, rank_fraction, np.nan), RSquare=r2, Test=[t[5] for t in tests],',
         '    Statistic=[np.nan if t[3] is None else t[3] for t in tests], DF=[np.nan if t[4] is None else t[4] for t in tests])',
         'print(res.sort_values("FDR_LogWorth", ascending=False, kind="stable"))   # the PValues table',
         'print(good.sum(), "tests;", (p[good] < alpha).sum(), "with p <", alpha, ";", (fdr[good] < alpha).sum(), "with FDR p <", alpha)']
    return '\n'.join(L)


def _rs_codes(head, ys, xs, weight, freq, levels, char, alpha, cap):
    """The code of Response Screening's three graphs: every test made as the
    report makes it, the FDR p-values, LogWorths and rank fractions."""
    imp = RS_IMPORTS
    fit = _rs_fit_lines(ys, xs, weight, freq, levels, char, alpha, cap)
    out = {}
    out['fdr_code'] = '\n'.join([head(imp), *fit,
                                 'i = np.flatnonzero(good)[np.argsort(rank_fraction[good], kind="stable")]',
                                 _fig(520, 340),
                                 f'ax.scatter(rank_fraction[i], np.maximum(p[i], 1e-300), s={_area(6)}, color="{RED}", label="PValue")',
                                 f'ax.scatter(rank_fraction[i], np.maximum(fdr[i], 1e-300), s={_area(6)}, marker="D", color="{BLUE}", label="FDR PValue")',
                                 f'ax.plot([0, 1], [alpha, alpha], color="{BLUE}", linewidth={_lw(1.2)}, label=f"α = {{alpha}}")',
                                 'q = np.maximum(1e-3, np.arange(51) / 50)',
                                 f'ax.plot(q, alpha * q, color="{RED}", linewidth={_lw(1.2)}, linestyle=":", label="FDR threshold for p")   # below it, significant at the false discovery rate α',
                                 'ax.set_yscale("log")', 'ax.set_xlim(0, 1.02)', 'ax.set_xlabel("Rank Fraction")', 'ax.set_ylabel("PValue")',
                                 'ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=4, frameon=False, fontsize=7.5)',
                                 'ax.set_title("FDR PValue Plot")', 'plt.show()'])
    out['effect_code'] = '\n'.join([head(imp), *fit,
                                    'i = np.flatnonzero(good)',
                                    _fig(500, 320),
                                    f'ax.scatter(effect[i], fdr_logworth[i], s={_area(7)}, c=["{RED}" if fdr[j] < alpha else "{MUTED}" for j in i])   # red: significant at the FDR α',
                                    f'ax.axhline(2, color="{RED}", linewidth={_lw(1)}, linestyle=":")   # FDR p = 0.01',
                                    'ax.set_xlim(left=0)', 'ax.set_ylim(bottom=0)', 'ax.set_xlabel("Effect Size")', 'ax.set_ylabel("FDR LogWorth")',
                                    'ax.set_title("FDR LogWorth by Effect Size")', 'plt.show()'])
    out['r2_code'] = '\n'.join([head(imp), *fit,
                                'i = np.flatnonzero(good & np.isfinite(r2))   # the continuous responses',
                                _fig(480, 300),
                                f'ax.scatter(r2[i], fdr_logworth[i], s={_area(7)}, color="{BASE}")',
                                'ax.set_xlim(0, 1)', 'ax.set_ylim(bottom=0)', 'ax.set_xlabel("RSquare")', 'ax.set_ylabel("FDR LogWorth")',
                                'ax.set_title("FDR LogWorth by RSquare")', 'plt.show()'])
    return out


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
def outliers_quantile(table, columns, rows=None, tail=0.1, q=3.0, integers=False, where=None, table_name='data'):
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
    code = '\n'.join([_head(table, rows, where, table_name), f'for c in {_cols_expr(list(columns))}:',
                      '    v = df[c].dropna()',
                      f'    lo, hi = np.quantile(v, [{tail}, {1 - tail}], method="weibull"); iqr = hi - lo',
                      f'    print(c, v[(v < lo - {q} * iqr) | (v > hi + {q} * iqr)].tolist())'])
    return {'columns': out, 'cells': cells, 'nines': nines, 'tail': tail, 'q': q, 'code': code}


@api('outliers.robust')
def outliers_robust(table, columns, rows=None, method='huber', k=4.0, where=None, table_name='data'):
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
    code = '\n'.join([_head(table, rows, where, table_name, ['from scipy import stats', 'from statsmodels.robust.scale import Huber']),
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
def outliers_multivariate(table, columns, rows=None, alpha=0.05, seed=20260926, where=None, table_name='data'):
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
    code = '\n'.join([_head(table, rows, where, table_name, ['from scipy import stats']), f'X = df[{_cols_expr(cols)}].dropna().to_numpy(); p = X.shape[1]',
                      'e = X - X.mean(0); md = np.sqrt(np.einsum("ij,jk,ik->i", e, np.linalg.inv(np.cov(X, rowvar=False)), e))   # classical',
                      f'limit = np.sqrt(stats.chi2.ppf({1 - alpha:g}, p)); print(md[:5], limit)',
                      '# the robust distances replace the mean and covariance by the reweighted minimum covariance determinant',
                      '# estimate (FAST-MCD); with scikit-learn: from sklearn.covariance import MinCovDet',
                      '# rd = np.sqrt(MinCovDet(random_state=0).fit(X).mahalanobis(X))'])
    out = {'rows': df.index.to_numpy(), 'robust': rd, 'classical': md, 'limit': lim, 'alpha': alpha, 'n': n, 'p': p, 'h': est['h'],
           'mean': est['mean'], 'cov': _mat(est['cov']), 'count': int(np.sum(rd > lim)), 'code': code}
    out.update(_mro_codes(lambda imports: _plot_head(table, rows, where, table_name, imports), cols, alpha, int(seed)))
    return out


MCD_DEF = [
    'def cstep(X, idx, h, steps):',
    '    """C-steps (Rousseeuw and Van Driessen 1999): the h rows nearest the mean and covariance of the rows idx, again."""',
    '    p = X.shape[1]',
    '    m, S, ld = X[idx].mean(0), np.cov(X[idx], rowvar=False).reshape(p, p), None',
    '    for _ in range(steps):',
    '        if np.linalg.slogdet(S)[0] <= 0:',
    '            return idx, m, S, -np.inf',
    '        d = np.einsum("ij,jk,ik->i", X - m, np.linalg.inv(S), X - m)',
    '        new = np.argsort(d, kind="stable")[:h]',
    '        m2, S2 = X[new].mean(0), np.cov(X[new], rowvar=False).reshape(p, p)',
    '        sg2, ld2 = np.linalg.slogdet(S2)',
    '        if sg2 <= 0:',
    '            return new, m2, S2, -np.inf',
    '        same = set(new.tolist()) == set(idx.tolist())',
    '        idx, m, S, ld = new, m2, S2, ld2',
    '        if same:',
    '            break',
    '    return idx, m, S, np.linalg.slogdet(S)[1] if ld is None else ld',
    '',
    '',
    'def mcd_raw(X, h, rng, n_starts=500, n_best=10):',
    '    """FAST-MCD: C-steps from random (p + 1)-subsets; the mean and covariance of the h rows with the smallest determinant found."""',
    '    n, p = X.shape',
    '    starts = []',
    '    for _ in range(n_starts):',
    '        sub = rng.choice(n, p + 1, replace=False)',
    '        S = np.cov(X[sub], rowvar=False).reshape(p, p)',
    '        tries = 0',
    '        while np.linalg.matrix_rank(S) < p and len(sub) < n and tries < n:   # a singular start: one more row',
    '            sub = np.concatenate([sub, rng.choice(np.setdiff1d(np.arange(n), sub), 1)])',
    '            S = np.cov(X[sub], rowvar=False).reshape(p, p)',
    '            tries += 1',
    '        m = X[sub].mean(0)',
    '        try:',
    '            d = np.einsum("ij,jk,ik->i", X - m, np.linalg.pinv(S), X - m)',
    '        except np.linalg.LinAlgError:',
    '            continue',
    '        starts.append(cstep(X, np.argsort(d, kind="stable")[:h], h, 2))',
    '    starts = sorted((s for s in starts if np.isfinite(s[3])), key=lambda s: s[3])',
    '    best, seen = None, set()',
    '    for idx, m, S, ld in starts[:n_best * 3]:   # the best starts, taken to convergence',
    '        key = tuple(sorted(idx.tolist()))',
    '        if key in seen:',
    '            continue',
    '        seen.add(key)',
    '        res = cstep(X, idx, h, 100)',
    '        if best is None or res[3] < best[3]:',
    '            best = res',
    '        if len(seen) >= n_best:',
    '            break',
    '    return best[1], best[2]',
    '',
    '',
    'def mcd(X, seed):',
    '    """The reweighted minimum covariance determinant estimate of the mean and covariance, as the report computes it."""',
    '    n, p = X.shape',
    '    h = (n + p + 1) // 2',
    '    rng = np.random.default_rng(seed)',
    '    if n > 1500:   # FAST-MCD on a subsample of 1500 rows, then C-steps on them all',
    '        sub = rng.choice(n, 1500, replace=False)',
    '        m0, S0 = mcd_raw(X[sub], (1500 + p + 1) // 2, rng)',
    '        idx = np.argsort(np.einsum("ij,jk,ik->i", X - m0, np.linalg.inv(S0), X - m0), kind="stable")[:h]',
    '        for _ in range(100):',
    '            m, S = X[idx].mean(0), np.cov(X[idx], rowvar=False)',
    '            new = np.argsort(np.einsum("ij,jk,ik->i", X - m, np.linalg.inv(S), X - m), kind="stable")[:h]',
    '            if set(new.tolist()) == set(idx.tolist()):',
    '                break',
    '            idx = new',
    '        m, S = X[idx].mean(0), np.cov(X[idx], rowvar=False).reshape(p, p)',
    '    else:',
    '        m, S = mcd_raw(X, h, rng)',
    '    S = S * ((h / n) / stats.chi2.cdf(stats.chi2.ppf(h / n, p), p + 2))   # the consistency factor for normal data',
    '    keep = np.einsum("ij,jk,ik->i", X - m, np.linalg.inv(S), X - m) <= stats.chi2.ppf(0.975, p)   # reweighted: the rows within the 0.975 quantile',
    '    m, S = X[keep].mean(0), np.cov(X[keep], rowvar=False).reshape(p, p)',
    '    delta = keep.mean()',
    '    return m, S * (delta / stats.chi2.cdf(stats.chi2.ppf(delta, p), p + 2) if delta < 1 else 1.0)']


def _mro_codes(head, cols, alpha, seed):
    """The code of Multivariate Robust Outliers' two graphs: the robust
    distances by row, and against the classical ones."""
    fit = [f'X = df[{_cols_expr(cols)}].dropna()   # the rows with every column', 'rows, X = X.index.to_numpy(), X.to_numpy()', 'p = X.shape[1]',
           '', *MCD_DEF, '',
           f'm, S = mcd(X, {seed})   # the report\'s seed',
           'rd = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", X - m, np.linalg.pinv(S), X - m), 0))   # the robust distances',
           'e = X - X.mean(0)',
           'md = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", e, np.linalg.pinv(np.cov(X, rowvar=False).reshape(p, p)), e), 0))   # the classical Mahalanobis distances',
           f'limit = np.sqrt(stats.chi2.ppf({1 - alpha!r}, p))   # the square root of the {1 - alpha:g} chi-square quantile with p DF']
    imp = ['from scipy import stats']
    out = {'robust_code': '\n'.join([head(imp), *fit,
                                     *_row_plot_lines('rows + 1', 'rd', 'limit', '', 'Robust Distance', 'Robust distances by row', 520, 250,
                                                      limit_text=f'f"√χ²({{fmt({1 - alpha!r})}}, {{p}}) {{fmt(limit, 5)}}"')]),
           'dd_code': '\n'.join([head(imp), *fit, _fig(360, 250),
                                 f'ax.scatter(md, rd, s={_area(5)}, color="{BASE}")',
                                 f'ax.axhline(limit, color="{RED}", linewidth={_lw(1)}, linestyle="--")',
                                 f'ax.axvline(limit, color="{RED}", linewidth={_lw(1)}, linestyle="--")',
                                 'ax.set_xlim(left=0)', 'ax.set_ylim(bottom=0)', 'ax.set_xlabel("Mahalanobis Distance")', 'ax.set_ylabel("Robust Distance")',
                                 'ax.set_title("Distance-distance plot")', 'plt.show()'])}
    return out


def _knn_codes(head, cols, K, ks):
    """The code of the k-nearest-neighbour plots: a graph for each k."""
    fit = [f'X = df[{_cols_expr(cols)}].dropna()   # the rows with every column', 'rows, X = X.index.to_numpy(), X.to_numpy()',
           'Z = np.empty_like(X)',
           'for j in range(X.shape[1]):   # each column centred at its median and scaled by max(Q3 − median, median − Q1)/z(0.75), or wider quantiles while that is 0',
           '    v, s = X[:, j], 0.0',
           '    med = np.median(v)',
           '    for lo, hi in ((0.25, 0.75), (0.1, 0.9), (0.05, 0.95), (0.01, 0.99), (0.0, 1.0)):',
           '        ql, qh = np.quantile(v, [lo, hi])',
           '        s = max(qh - med, med - ql) / stats.norm.ppf(hi)',
           '        if s > 0:',
           '            break',
           '    Z[:, j] = (v - med) / (s if s > 0 else 1.0)',
           f'd, _ = cKDTree(Z).query(Z, k={K + 1})   # the distances to the nearest {K} neighbours (the first is the row itself)']
    return [{'k': k, 'plot_code': '\n'.join([head(['from scipy import stats', 'from scipy.spatial import cKDTree']), *fit,
                                             *_row_plot_lines('rows + 1', f'd[:, {k}]', None, None, f'Distance to neighbor {k}', f'k = {k}', 380, 220)])}
            for k in ks]


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
def outliers_knn(table, columns, rows=None, k=8, where=None, table_name='data'):
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
    code = '\n'.join([_head(table, rows, where, table_name, ['from scipy.spatial import cKDTree']), f'X = df[{_cols_expr(cols)}].dropna().to_numpy()',
                      'med = np.median(X, 0); q1, q3 = np.quantile(X, [0.25, 0.75], axis=0)',
                      'X = (X - med) / (np.maximum(q3 - med, med - q1) / 0.6744897501960817)   # centred at the median, scaled robustly',
                      f'd, _ = cKDTree(X).query(X, k={K + 1}); print(d[:, 1:])   # distance to the 1st..{K}th neighbour'])
    return {'rows': df.index.to_numpy(), 'ks': ks, 'dist': {str(kk): dist[:, kk] for kk in ks}, 'K': K, 'code': code,
            'plots': _knn_codes(lambda imports: _plot_head(table, rows, where, table_name, imports), cols, K, ks)}


# ---- Multiple Correspondence Analysis ------------------------------------------------------------------

@api('mca.fit')
def mca_fit(table, columns, rows=None, freq=None, plot=None, where=None, table_name='data'):
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
    blocks, levels, order = [], [], {}
    for c in cols:
        s = df[c]
        cats = list(s.cat.categories) if hasattr(s, 'cat') else sorted(s.unique())
        order[c] = [_level_value(v) for v in cats]
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
    code = '\n'.join([_head(table, rows, where, table_name), f'X = df[{_cols_expr(cols)}].dropna().astype(str)',
                      'Z = pd.get_dummies(X).to_numpy(float); P = Z / Z.sum(); r, c = P.sum(1), P.sum(0)',
                      'S = (P - np.outer(r, c)) / np.sqrt(np.outer(r, c)); U, s, Vt = np.linalg.svd(S, full_matrices=False)',
                      f'k = Z.shape[1] - {Q}; inertia = s[:k]**2; print(s[:k], inertia, 100 * inertia / inertia.sum())',
                      'G = Vt.T[:, :k] * s[:k] / np.sqrt(c)[:, None]   # principal coordinates of the levels (sign arbitrary)'])
    out = {'names': cols, 'n': float(f.sum()), 'n_rows': n, 'Q': Q, 'J': Jn, 'K': K, 'levels': levels, 'singular': sv, 'inertia': lam,
           'percent': 100 * lam / total if total > 0 else lam * 0, 'cum': 100 * np.cumsum(lam) / total if total > 0 else lam * 0,
           'total_inertia': total, 'adjusted': {'greenacre': adj, 'greenacre_pct': 100 * adj / g_total if g_total > 0 else adj * 0,
                                                'benzecri_pct': 100 * adj / adj.sum() if adj.sum() > 0 else adj * 0, 'greenacre_total': g_total},
           'rows': df.index.to_numpy(), 'row_coords': _mat(F[:, :min(K, 4)]), 'burt': _mat(burt), 'code': code}
    if plot is not None:
        out.update(_mca_codes(lambda imports: _plot_head(table, rows, where, table_name, imports), table, cols, freq, order, K, plot))
    return out


def _mca_codes(head, table, cols, freq, levels, K, plot):
    """The code of Multiple Correspondence Analysis' two graphs, the levels'
    and the rows' principal coordinates found as mca.fit finds them."""
    a = min(int(plot.get('x', 0) or 0), K - 1)
    b = min(int(plot.get('y', 1) if plot.get('y') is not None else 1), K - 1)
    char = [c for c in cols if data.meta(table, c).get('dataType') != 'numeric']
    need = [*cols, *([freq] if freq else [])]
    fit = [f'd = df.dropna(subset={J(need)})   # the rows with every column']
    if freq:
        fit += [f'f = d[{J(freq)}].to_numpy(float)   # Freq', 'd, f = d[f > 0], f[f > 0]']
    else:
        fit.append('f = np.ones(len(d))')
    fit += [f'levels = {{{", ".join(f"{J(c)}: {_py_list(v)}" for c, v in levels.items())}}}   # each column\'s levels, in the table\'s order',
            '',
            'def level_text(v):   # a level as the page shows it',
            '    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)',
            '',
            'blocks, texts = [], {}',
            'for c in levels:   # the indicator matrix: a column for each level that occurs',
            f'    s = (d[c].astype(str) if c in {J(char)} else d[c]).to_numpy(dtype=object)',
            '    present = [v for v in levels[c] if (s == v).any()]',
            '    blocks.append((s[:, None] == np.array(present, dtype=object)[None, :]).astype(float))',
            '    texts[c] = [level_text(v) for v in present]',
            'Z = np.hstack(blocks)',
            'P = Z * f[:, None] / (Z * f[:, None]).sum()',
            'r, c = P.sum(1), P.sum(0)',
            'U, sv, Vt = np.linalg.svd((P - np.outer(r, c)) / np.sqrt(np.outer(r, c)), full_matrices=False)   # the standardized residuals',
            f'K = {K}   # the dimensions: J − Q (the levels less the columns)',
            'sv, U, V = sv[:K], U[:, :K], Vt.T[:, :K]',
            'G = V * sv / np.sqrt(c)[:, None]   # the levels\' principal coordinates',
            'F = U * sv / np.sqrt(r)[:, None]   # the rows\'',
            'sg = np.where(G[np.argmax(np.abs(G), axis=0), np.arange(K)] < 0, -1.0, 1.0)   # each dimension\'s largest coordinate positive, as the report makes it',
            'G, F = G * sg, F * sg',
            'percent = 100 * sv ** 2 / (sv ** 2).sum()   # each dimension\'s share of the inertia']
    out = {}
    L = [head([]), *fit,
         f'colors = {J(PALETTE)}   # the page\'s palette, a colour for each column',
         'symbols = ["o", "s", "D", "^", "P", "X"]',
         _fig(560, 440),
         'start = 0',
         'for i, col in enumerate(levels):',
         '    g = G[start:start + len(texts[col])]',
         '    start += len(texts[col])',
         f'    x, y = g[:, {a}], {f"g[:, {b}]" if K > 1 else "np.zeros(len(g))"}',
         f'    ax.scatter(x, y, s={_area(8)}, marker=symbols[i % len(symbols)], color=colors[i % len(colors)], label=col)',
         '    if len(g) <= 40:',
         '        for name, xi, yi in zip(texts[col], x, y):',
         '            ax.text(xi, yi, name, ha="center", va="bottom", fontsize=7.2)',
         *_zero_lines(),
         f'ax.set_xlabel(f"c{a + 1} ({{percent[{a}]:.1f}}%)")',
         f'ax.set_ylabel(f"c{b + 1} ({{percent[{b}]:.1f}}%)")' if K > 1 else 'ax.set_ylabel("")',
         'ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=min(len(levels), 6), frameon=False, fontsize=7.5)',
         'ax.set_title("Correspondence Analysis")', 'plt.show()']
    out['plot_code'] = '\n'.join(L)
    m = min(K, 4)
    ia, ib = min(a, m - 1), min(b, m - 1)
    out['rows_code'] = '\n'.join([head([]), *fit,
                                  f'x, y = F[:, {ia}], {f"F[:, {ib}]" if m > 1 else "np.zeros(len(F))"}   # each row in principal coordinates (rows with the same levels coincide)',
                                  _fig(480, 380), f'ax.scatter(x, y, s={_area(6)}, color="{BASE}")', *_zero_lines(),
                                  f'ax.set_xlabel(f"c{min(a, 3) + 1} ({{percent[{min(a, 3)}]:.1f}}%)")',
                                  f'ax.set_ylabel(f"c{min(b, 3) + 1} ({{percent[{min(b, 3)}]:.1f}}%)")' if K > 1 else 'ax.set_ylabel("")',
                                  'ax.set_title("MCA row plot")', 'plt.show()'])
    return out


def _mds_codes(head, table, cols, standardize, matrix, label, n, k, n_pairs, seed):
    """The code of Multidimensional Scaling's map and Shepard diagram, the
    scaling made as mds.fit makes it."""
    if matrix:
        fit = [f'X = df[{_cols_expr(cols)}]   # the columns are a matrix of the distances between the rows\' objects',
               'D = X.to_numpy(float)',
               'D = np.where(np.isnan(D), D.T, D)   # a missing distance from the other side of the diagonal',
               'D = (D + D.T) / 2   # made symmetric',
               'np.fill_diagonal(D, 0)']
    else:
        fit = [f'X = df[{_cols_expr(cols)}].dropna()   # the objects: the rows with every attribute', 'A = X.to_numpy()']
        if standardize:
            fit += ['sd = A.std(0, ddof=1)', 'A = (A - A.mean(0)) / np.where(sd > 0, sd, 1.0)   # the columns standardized']
        fit.append('D = squareform(pdist(A))   # the Euclidean distances')
    fit += ['n = len(D)',
            'C = np.eye(n) - 1 / n',
            'ev, V = np.linalg.eigh(-0.5 * C @ (D ** 2) @ C)   # classical scaling: the doubly centred squared distances',
            'o = np.argsort(ev)[::-1]; ev, V = ev[o], V[:, o]',
            'k = int(min((ev > 1e-10 * max(1.0, abs(ev[0]))).sum(), 4))   # the dimensions with a positive eigenvalue, at most 4',
            'V = V[:, :k] * np.sign(V[np.abs(V[:, :k]).argmax(axis=0), np.arange(k)])   # each dimension\'s largest entry positive',
            'coords = V * np.sqrt(ev[:k])']
    imp = ['from scipy.spatial.distance import pdist, squareform']
    if label:
        numeric = data.meta(table, label).get('dataType') == 'numeric'
        text = 'f"{v:.10g}"' if numeric else 'str(v)'
        names = f'names = [str(r + 1) if pd.isna(v) else {text} for r, v in df.loc[X.index, {J(label)}].items()]   # each object\'s label (its row number without one)'
    else:
        names = 'names = [str(r + 1) for r in X.index]   # each object\'s row number'
    two = k >= 2
    L = [head(imp), *fit, 'x, y = coords[:, 0], ' + ('coords[:, 1]' if two else 'np.zeros(n)'), _fig(520, 440),
         f'ax.scatter(x, y, s={_area(6)}, color="{BASE}")']
    if n <= 60:
        L += [names, 'for name, xi, yi in zip(names, x, y):', '    ax.text(xi, yi, name, ha="center", va="bottom", fontsize=6.8)']
    L += [*_zero_lines(), 'ax.set_aspect("equal")', 'ax.set_xlabel("Dimension 1")', f'ax.set_ylabel("{"Dimension 2" if two else ""}")',
          'ax.set_title("Multidimensional Scaling Plot")', 'plt.show()']
    out = {'plot_code': '\n'.join(L)}
    S = [head(imp), *fit,
         'iu = np.triu_indices(n, 1)',
         'd, dh = D[iu], squareform(pdist(coords[:, :min(2, k)]))[iu]   # each pair\'s distance in the data and in the two-dimensional map']
    if n_pairs > 3000:
        S.append(f'take = np.sort(np.random.default_rng({seed}).choice(len(d), 3000, replace=False))   # a sample of 3000 of the pairs (the report\'s seed)')
        S.append('d, dh = d[take], dh[take]')
    S += [_fig(380, 320), f'ax.scatter(d, dh, s={_area(3)}, color="{BASE}", alpha=0.6)',
          'mx = max(d.max(), dh.max())',
          f'ax.plot([0, mx], [0, mx], color="{RED}", linewidth={_lw(1)})   # on the line the map is exact',
          'ax.set_xlim(left=0)', 'ax.set_ylim(bottom=0)', 'ax.set_xlabel("Distance")', 'ax.set_ylabel("Map Distance")', 'ax.set_title("Shepard Diagram")', 'plt.show()']
    out['shepard_code'] = '\n'.join(S)
    return out


# ---- Multidimensional Scaling ----------------------------------------------------------------------------

@api('mds.fit')
def mds_fit(table, columns, rows=None, standardize=True, matrix=False, label=None, seed=20260926, where=None, table_name='data'):
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
    code = '\n'.join([_head(table, rows, where, table_name, ['from scipy.spatial.distance import pdist, squareform']),
                      f'X = df[{_cols_expr(cols)}]' + ('.to_numpy(); D = (X + X.T) / 2   # the columns are the distance matrix' if matrix else '.dropna()'),
                      '' if matrix else ('X = (X - X.mean()) / X.std()   # standardized columns' if standardize else ''),
                      '' if matrix else 'D = squareform(pdist(X))',
                      'n = len(D); J = np.eye(n) - 1 / n; B = -0.5 * J @ (D**2) @ J',
                      'ev, V = np.linalg.eigh(B); o = np.argsort(ev)[::-1]; ev, V = ev[o], V[:, o]',
                      'coords = V[:, :2] * np.sqrt(ev[:2]); print(ev[:4], coords[:5])   # classical MDS (sign arbitrary)'])
    out = {'names': cols, 'n': n, 'rows': df.index.to_numpy(), 'coords': _mat(Xc), 'eigenvalues': evp[:20], 'percent': 100 * evp[:20] / evp.sum(),
           'k': kmax, 'stress': stress, 'r2': r2, 'shepard': {'d': d[take], 'dhat': dh[take]}, 'n_pairs': int(len(d)), 'matrix': bool(matrix),
           'negative': float(-neg.sum() / np.abs(ev).sum()) if len(neg) else 0.0, 'code': code}
    out.update(_mds_codes(lambda imports: _plot_head(table, rows, where, table_name, imports), table, cols, standardize, matrix, label, n, kmax, int(len(d)), int(seed)))
    return out
