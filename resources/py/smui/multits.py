"""Multivariate Time Series (Analyze > Specialized Modeling > Multivariate
Time Series): the backend. Vector autoregressions and cointegration, which
JMP does not have, on statsmodels.tsa.vector_ar:

  the series       two or more columns in time order, read as the Time
                   Series platform reads one (timeseries.load: a date Time ID
                   gives the calendar frequency, missing dates are inserted,
                   excluded rows count as missing), over the span where every
                   series has a value. A VAR needs every time point, so the
                   missing values inside are filled by linear interpolation,
                   and the report says so. Optionally the logarithm and the
                   first difference of every series.
  stationarity     adfuller and kpss of each series, with the VAR's
                   deterministic terms
  lag order        VAR.select_order: AIC, BIC, FPE and HQIC of every lag on
                   the same sample
  VAR(p)           VAR.fit by least squares: the coefficients of every
                   equation, the residual correlations, the eigenvalues of
                   the companion matrix, test_whiteness and test_normality
  causality        test_causality for every ordered pair (and all the others
                   together), test_inst_causality
  impulse response irf, with asymptotic bands (stderr, cum_effect_stderr) or
                   Monte Carlo bands (errband_mc); the Cholesky ordering by
                   refitting on the columns in the order asked for
  FEVD             fevd
  forecasts        forecast_interval; after a difference (and a log) the
                   forecasts are also carried back to the original units
  cointegration    coint_johansen and select_coint_rank, VECM, and the
                   Engle-Granger test (stattools.coint)

Every result carries the Python that computes it from a CSV export of the
table.
"""
import functools
import json
import math
import warnings
from contextlib import contextmanager

import numpy as np
import pandas as pd
from scipy import stats

from .registry import api
from .timeseries import BASE, DATE_KINDS, MUTED, SIZE, NoSeries, _pt, _when, left_out, load as _load_series
from .util import code_head

J = json.dumps
PALETTE = ['#2f6690', '#d9822b', '#3a7d44', '#b0413e', '#6c5b7b', '#1f9e89', '#c0a000', '#8c564b', '#e377c2', '#7f7f7f', '#17becf', '#9467bd']   # the page's, light theme
GRID, SURFACE = '#e0d7ce', '#fcf7f2'   # kvot.css, light theme

SEED = 20260926          # Monte Carlo bands: the same numbers every time
CRITERIA = ('aic', 'bic', 'hqic', 'fpe')
TRENDS = {'c': 'Constant', 'ct': 'Constant and linear trend', 'n': 'None'}
N_TREND = {'c': 1, 'ct': 2, 'n': 0}
DETERMINISTIC = {'n': 'None', 'co': 'Constant (unrestricted)', 'ci': 'Constant in the cointegrating relation',
                 'colo': 'Constant and linear trend (unrestricted)', 'cili': 'Constant, and a linear trend in the cointegrating relation'}
DET_ORDER = {-1: 'no deterministic terms', 0: 'a constant (unrestricted: a linear trend in the levels)',
             1: 'a constant and a linear trend (unrestricted)'}


@contextmanager
def _quiet():
    """Drop numpy's and pandas' deprecation notices raised inside statsmodels;
    every other warning still reaches the report."""
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=DeprecationWarning)
        warnings.filterwarnings('ignore', category=FutureWarning)
        yield


def _f(x):
    """A float for JSON, or None."""
    try:
        v = float(np.real(x))
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _arr(a):
    return [_f(v) for v in np.asarray(a, dtype=float).ravel()]


def _mat(a):
    return [[_f(v) for v in row] for row in np.asarray(a, dtype=float)]


def _cube(a):
    return [_mat(m) for m in np.asarray(a, dtype=float)]


def _ms(idx):
    return np.asarray((pd.DatetimeIndex(idx) - pd.Timestamp(0)) // pd.Timedelta(milliseconds=1), dtype=np.int64)


def _plural(n, one, many=None):
    return f'{n} {one if n == 1 else (many or one + "s")}'


# ---- the series ------------------------------------------------------------

class Prep:
    """The series of a report, ready for statsmodels.

    names, exog   the Y columns and the exogenous columns
    S             the Time Series platform's reading of the first Y (time
                  axis, frequency, rows), with the others alongside
    a, b          the span in S's slots where every column has a value
    L, X0, t0, rows0   the levels over that span (logs with log=True), the
                  exogenous columns, the times and the table rows
    Y, X, t, rows the series as analysed: L, or its first differences
    raw           the Y values over the span as in the table (missing kept)
    """

    @property
    def k(self):
        return len(self.names)

    @property
    def m(self):
        return len(self.exog)

    @property
    def n(self):
        return len(self.Y)

    def frame(self, order=None):
        df = pd.DataFrame(self.Y, columns=self.names)
        return df[list(order)] if order else df

    def exog_frame(self):
        return pd.DataFrame(self.X, columns=self.exog) if self.exog else None

    def label(self, name):
        """The name of a series as analysed: log x, Δ x, Δ log x."""
        return f'{"Δ " if self.diff else ""}{"log " if self.log else ""}{name}'

    def future(self, h):
        """The times of h periods after the span."""
        S = self.S
        h = int(h or 0)
        if h <= 0 or not len(self.t):
            return []
        last = self.t[-1]
        if S.kind in DATE_KINDS and S.offset is not None:
            fut = pd.date_range(pd.Timestamp(int(last), unit='ms'), periods=h + 1, freq=S.offset)[1:]
            return [float(v) for v in _ms(fut)]
        return [float(last + S.step * (i + 1)) for i in range(h)]

    def exog_future(self, h):
        """The exogenous columns for h periods after the span: the slots after
        it, then the rows after the series in the table (Y missing, the
        inputs present), as the Time Series platform takes them; beyond those
        the last value is held."""
        if not self.exog or h <= 0:
            return None, []
        cols, notes = [], []
        for j, c in enumerate(self.exog):
            v = np.asarray(self.xnext[c], dtype=float)
            bad = ~np.isfinite(v)
            known = v[:int(np.argmax(bad))] if bad.any() else v
            known = known[:h]
            if len(known) < h:
                last = known[-1] if len(known) else self.X0[-1, j]
                notes.append(f'{c}: {_plural(len(known), "future value")} from the table, the last value ({last:.6g}) held for the '
                             f'remaining {_plural(h - len(known), "period")}.')
                known = np.concatenate([known, np.full(h - len(known), last)])
            else:
                notes.append(f'{c}: the {h} future values come from the rows after the series in the table.')
            cols.append(known)
        return np.column_stack(cols), notes


def prepare(table, y, time=None, rows=None, excluded=None, exog=None, log=False, diff=False):
    """The Y columns (two or more) and the exogenous ones over the span where
    all have a value, missing values inside filled by linear interpolation,
    then log and first difference if asked for."""
    names = [c for c in dict.fromkeys(y or []) if c and c != time]
    if len(names) < 2:
        raise NoSeries('a vector autoregression needs at least two series (Y, Time Series)')
    ex = [c for c in dict.fromkeys(exog or []) if c and c not in names and c != time]
    S = _load_series(table, names[0], time, rows, excluded, inputs=names[1:] + ex)
    full = np.column_stack([np.asarray(S.y, dtype=float)] + [np.asarray(S.X[c], dtype=float) for c in names[1:]])
    if S.excluded_pos:
        full[S.excluded_pos, :] = np.nan        # an excluded row is missing in every series
    xfull = np.column_stack([np.asarray(S.X[c], dtype=float) for c in ex]) if ex else None
    cols = [(names[j], full[:, j]) for j in range(len(names))] + ([(ex[j], xfull[:, j]) for j in range(len(ex))] if ex else [])
    firsts, lasts = [], []
    for c, v in cols:
        ok = np.isfinite(v)
        if not ok.any():
            raise NoSeries(f'{c} has no values in these rows')
        firsts.append(int(np.argmax(ok)))
        lasts.append(len(v) - 1 - int(np.argmax(ok[::-1])))
    a, b = max(firsts), min(lasts)
    if b - a + 1 < 8:
        raise NoSeries('too few time points where every series has a value (at least 8 are needed)')
    P = Prep()
    P.names, P.exog, P.S, P.a, P.b = names, ex, S, a, b
    P.log, P.diff = bool(log), bool(diff)
    P.notes = list(S.notes)
    P.rows_arg = None if rows is None else [int(r) for r in rows]
    raw = full[a:b + 1].copy()
    P.raw = raw
    P.t0 = np.asarray(S.t[a:b + 1], dtype=float)
    P.rows0 = list(S.rows[a:b + 1])
    P.excl_rel = [k - a for k in S.excluded_pos if a <= k <= b]
    if a > 0 or b < S.n - 1:
        P.notes.append(f'The analysis runs over the {b - a + 1} time points where every series has a value '
                       f'({_plural(a, "point")} left out at the start, {_plural(S.n - 1 - b, "point")} at the end).')
    L = raw.copy()
    P.filled = {}
    for j, c in enumerate(names):
        miss = ~np.isfinite(L[:, j])
        if miss.any():
            P.filled[c] = int(miss.sum())
            L[:, j] = pd.Series(L[:, j]).interpolate(method='linear', limit_direction='both').to_numpy(dtype=float)
    P.xfilled = {}
    X0 = None
    if ex:
        X0 = xfull[a:b + 1].copy()
        for j, c in enumerate(ex):
            miss = ~np.isfinite(X0[:, j])
            if miss.any():
                P.xfilled[c] = int(miss.sum())
                X0[:, j] = pd.Series(X0[:, j]).interpolate(method='linear', limit_direction='both').to_numpy(dtype=float)
    if P.filled or P.xfilled:
        parts = [f'{c} {n}' for c, n in list(P.filled.items()) + list(P.xfilled.items())]
        total = sum(P.filled.values()) + sum(P.xfilled.values())
        P.notes.append(f'A VAR needs every time point: {_plural(total, "missing value")} inside the span (excluded rows, missing cells, '
                       f'dates with no row) {"was" if total == 1 else "were"} filled by linear interpolation ({", ".join(parts)}).')
    if P.log:
        bad = [c for j, c in enumerate(names) if not (L[:, j] > 0).all()]
        if bad:
            raise NoSeries(f'Log Transform needs every value above zero: {", ".join(bad)} {"has" if len(bad) == 1 else "have"} some at or below zero')
        L = np.log(L)
    P.L, P.X0 = L, X0
    # the exogenous values after the span, for the forecasts
    P.xnext = {}
    for j, c in enumerate(ex):
        P.xnext[c] = np.concatenate([xfull[b + 1:, j], np.asarray(S.Xf.get(c, []), dtype=float)])
    if P.diff:
        P.Y, P.t, P.rows = np.diff(L, axis=0), P.t0[1:], P.rows0[1:]
        P.X = X0[1:] if ex else None
    else:
        P.Y, P.t, P.rows, P.X = L, P.t0, P.rows0, X0
    if len(P.Y) < 8:
        raise NoSeries('too few time points after differencing')
    flat = [c for j, c in enumerate(names) if not np.std(P.Y[:, j]) > 0]
    if flat:
        raise NoSeries(f'{", ".join(flat)} {"does" if len(flat) == 1 else "do"} not vary over these rows'
                       f'{" after differencing" if P.diff else ""}: every series of a VAR must')
    xflat = [c for j, c in enumerate(ex) if not np.std(P.X[:, j]) > 0]
    if xflat:
        raise NoSeries(f'the exogenous column{"s" if len(xflat) > 1 else ""} {", ".join(xflat)} {"does" if len(xflat) == 1 else "do"} not vary '
                       'over these rows: it would be a second constant')
    return P


# ---- the code shown under the results ----------------------------------------

def _time_label(P, k):
    """A .loc label for slot k of S: the date as text, the Time ID's value, or
    the position among the rows of the table (or of the By group)."""
    S = P.S
    if S.time_name:
        if S.kind in DATE_KINDS:
            ts = pd.Timestamp(int(S.t[k]), unit='ms')
            return json.dumps(ts.strftime('%Y-%m-%d %H:%M:%S' if (ts.hour or ts.minute or ts.second) else '%Y-%m-%d'))
        return repr(float(S.t[k]))
    r = S.rows[k]
    if P.rows_arg is None:
        return str(int(r))
    return str(P.rows_arg.index(int(r)))


def _code_data(P, table_name, where=None, imports=(), levels=False, keep_levels=False, graph=False):
    """Python that builds, from a CSV export of the table, Y (the series as
    analysed, indexed by the Time ID) and X (the exogenous columns). levels:
    stop before the difference (the cointegration tests take the levels);
    keep_levels: keep them as L before differencing (for the forecasts in the
    units of the table); graph: a graph's code, which also keeps raw, the
    table's values over the span (the graphs show those, gaps and all)."""
    S = P.S
    lines = [code_head(table_name, (['import matplotlib.pyplot as plt'] if graph else []) + list(imports))]
    for w in where or []:
        lines.append(f'df = df[df[{json.dumps(w.get("column"))}] == {w.get("value")!r}]   # the By group')
    drop = left_out(S.table, P.rows_arg, where)
    if drop:
        lines.append(f'df = df.drop(index={drop})   # the rows the report leaves out')
    if S.time_name:
        T = json.dumps(S.time_name)
        if S.kind in DATE_KINDS:
            lines.append(f'df[{T}] = pd.to_datetime(df[{T}])')
            if S.offset is not None:
                lines.append(f'd = df.dropna(subset=[{T}]).sort_values({T}).set_index({T}).asfreq({S.freq!r})   # {S.freq_label or S.freq}; missing dates inserted')
            else:
                lines.append(f'd = df.dropna(subset=[{T}]).sort_values({T}).set_index({T})')
        else:
            lines.append(f'd = df.dropna(subset=[{T}]).sort_values({T}).set_index({T})')
            if S.inserted:
                lines.append(f'd = d.reindex(d.index[0] + {S.step!r} * np.arange(round((d.index[-1] - d.index[0]) / {S.step!r}) + 1))   # the missing time steps')
    else:
        lines.append('d = df.reset_index(drop=True)')
    lines.append(f'Y = d.loc[{_time_label(P, P.a)}:{_time_label(P, P.b)}, {json.dumps(P.names)}].copy()   # where every series has a value')
    if P.excl_rel:
        lines.append(f'Y.iloc[{P.excl_rel}] = np.nan   # rows excluded in the table count as missing')
    if graph:
        lines.append('raw = Y.copy()   # the table\'s values over the span, missing ones as gaps')
    if P.filled:
        lines.append('Y = Y.interpolate(limit_direction="both")   # a VAR needs every time point: missing values filled linearly')
    if P.log:
        lines.append('Y = np.log(Y)')
    if P.diff:
        if levels:
            lines.append('# the levels (not the differences): the cointegration tests and the VECM take them')
        else:
            if keep_levels:
                lines.append('L = Y.copy()   # the levels, for the forecasts in the units of the table')
            lines.append('Y = Y.diff().iloc[1:]   # first differences')
    if P.exog:
        lines.append(f'X = d.loc[Y.index, {json.dumps(P.exog)}]' + ('.interpolate(limit_direction="both")' if P.xfilled else ''))
    return lines


def _fit_code(P, p, trend, order=None):
    Y = f'Y[{json.dumps(list(order))}]' if order and list(order) != P.names else 'Y'
    return f'res = VAR({Y}{", exog=X" if P.exog else ""}).fit({int(p)}, trend={trend!r})'


# ---- the graphs as matplotlib code ---------------------------------------------
# As in Time Series (timeseries.py, which says how): each graph's code is a
# recipe that the page puts together, with the graph's size in the report
# where it says {'set': 'size'} and the parts that its options keep.

def _tx(P, frame):
    """The time axis of a frame of the code (its index), as the page draws it."""
    return f'{frame}.index' if P.S.time_name else f'df.index.to_numpy()[{frame}.index] + 1   # the row numbers, as the page has them'


def _future(P, h, last):
    """t_f: the times of the h forecast periods, as Prep.future has them."""
    S = P.S
    if S.kind in DATE_KINDS and S.offset is not None:
        return f't_f = pd.date_range({last}, periods={h + 1}, freq={S.freq!r})[1:]   # the next {h} dates of the calendar'
    if S.kind in DATE_KINDS:
        return f't_f = {last} + pd.to_timedelta({S.step!r} * np.arange(1, {h + 1}), unit="ms")   # the median spacing of the dates'
    return f't_f = {last} + {S.step!r} * np.arange(1, {h + 1})   # the next {h} steps of the time axis'


def _series_plot(P, table_name, where):
    """The Time Series Graph: the series as analysed on one axis, or as Small Multiples."""
    shown = 'raw'
    if P.log:
        shown = f'np.log({shown})'
    if P.diff:
        shown = f'{shown}.diff().iloc[1:]'
    xl = J(P.S.time_name or 'Row')
    pts = f'linewidth={_pt(1.2)}, marker="o", markersize={_pt(4)}'
    return [*_code_data(P, table_name, where, graph=True),
            f'shown = {shown}   # the series as analysed, with the gaps of the table' if shown != 'raw' else 'shown = raw',
            f't = {_tx(P, "shown")}', f'labels = {J([P.label(c) for c in P.names])}', f'palette = {J(PALETTE)}   # the page\'s colours', '', SIZE,
            _when(['!multiples'], 'fig, ax = plt.subplots(figsize=size, layout="constrained")',
                  'for i, c in enumerate(shown):',
                  f'    ax.plot(t, shown[c], color=palette[i % len(palette)], {pts}, label=labels[i])',
                  f'ax.set_xlabel({xl}); ax.set_ylabel({J("Series as analysed" if P.log or P.diff else "Value")})',
                  'fig.legend(loc="outside lower center", ncols=min(4, len(labels)), frameon=False, fontsize=8)'),
            _when(['multiples'], 'fig, axes = plt.subplots(len(labels), 1, sharex=True, squeeze=False, figsize=size, layout="constrained")   # Small Multiples',
                  'for i, (c, ax) in enumerate(zip(shown, axes[:, 0])):',
                  f'    ax.plot(t, shown[c], color=palette[i % len(palette)], {pts})',
                  '    ax.set_ylabel(labels[i], fontsize=8)',
                  f'axes[-1, 0].set_xlabel({xl})'),
            'fig.suptitle("Time Series Graph", fontsize=10)', 'plt.show()']


def _heatmap(labels, rows, cmap, lo, hi, text, title):
    """The page's heatmap of a matrix M: the colour map, the values in the cells (up to ten columns), the labels."""
    L = ['', SIZE, 'fig, ax = plt.subplots(figsize=size, layout="constrained")', f'im = ax.imshow(M, vmin={lo}, vmax={hi}, cmap={cmap})']
    if len(labels) <= 10:
        L += ['for i in range(M.shape[0]):', '    for j in range(M.shape[1]):', '        if np.isfinite(M[i, j]):',
              f'            ax.text(j, i, {text}, ha="center", va="center", fontsize=8)']
    rot = ', rotation=35, ha="right"' if len(labels) > 4 else ''
    return L + [f'ax.set_xticks(range({len(labels)}), {J(labels)}{rot}); ax.set_yticks(range({len(rows)}), {J(rows)})',
                'fig.colorbar(im, ax=ax, shrink=0.85)', f'ax.set_title({J(title)})', 'plt.show()']


def _forecast_plot(P, title, obs, fitted):
    """The forecast graph (the page's forecastPlot): a panel for each series,
    the data, the one-step-ahead predictions (fitted: their name, or None),
    the forecasts from the last value, their band, the end of the data. The
    lines before it leave obs (a frame), t_o, t_f, names, f_mean, f_lower and
    f_upper (h × k)."""
    L = [f'palette = {J(PALETTE)}   # the page\'s colours', '', SIZE,
         'fig, axes = plt.subplots(len(names), 1, sharex=True, squeeze=False, figsize=size, layout="constrained")',
         'x_f = t_o[-1:].append(t_f)' if P.S.kind in DATE_KINDS else 'x_f = np.r_[t_o[-1], t_f]',
         'for i, ax in enumerate(axes[:, 0]):',
         '    c = palette[i % len(palette)]',
         f'    ax.plot(t_o, {obs}.iloc[:, i], color=c + "b3", linewidth={_pt(1)}, marker="o", markersize={_pt(3.5)}, markerfacecolor=c, markeredgecolor=c)   # the data']
    if fitted:
        L.append(f'    ax.plot(t_o, {fitted}[:, i], color=c, linewidth={_pt(1)}, linestyle=":")   # the one-step-ahead predictions')
    L += [f'    y0 = {obs}.iloc[-1, i]   # the forecasts go on from the last value',
          f'    ax.plot(x_f, np.r_[y0, f_upper[:, i]], color=c, alpha=0.55, linewidth={_pt(0.8)})',
          f'    ax.plot(x_f, np.r_[y0, f_lower[:, i]], color=c, alpha=0.55, linewidth={_pt(0.8)})',
          '    ax.fill_between(x_f, np.r_[y0, f_lower[:, i]], np.r_[y0, f_upper[:, i]], color=c, alpha=0.14, linewidth=0)   # the interval',
          f'    ax.plot(x_f, np.r_[y0, f_mean[:, i]], color=c, linewidth={_pt(2)}, marker="o", markersize={_pt(3)})   # the forecasts',
          f'    ax.axvline(t_o[-1], color="{MUTED}", linewidth={_pt(1)}, linestyle=":")   # the end of the data',
          '    ax.set_ylabel(names[i], fontsize=8)',
          f'axes[-1, 0].set_xlabel({J(P.S.time_name or "Row")})', f'fig.suptitle({J(title)}, fontsize=10)', 'plt.show()']
    return L


def _fit(P, p, trend='c', order=None):
    from statsmodels.tsa.api import VAR
    p = int(p or 0)
    if p < 1:
        raise NoSeries('the lag order must be at least 1')
    if trend not in N_TREND:
        raise NoSeries(f'no trend {trend!r}: use c, ct or n')
    per_eq = P.k * p + N_TREND[trend] + P.m
    if P.n - p - per_eq < P.k:
        raise NoSeries(f'too few observations ({P.n}) for a VAR({p}): each equation has {per_eq} coefficients')
    with _quiet():
        return VAR(P.frame(order), exog=P.exog_frame()).fit(p, trend=trend)


def _order(P, order):
    """A Cholesky ordering: a permutation of the Y columns, or None."""
    if not order:
        return None
    order = [c for c in order if c in P.names]
    if sorted(order) != sorted(P.names) or len(order) != P.k:
        return None
    return None if order == P.names else order


def _common(fn):
    """An API function on the prepared series: a NoSeries (too few values, no
    variation, a bad option) becomes {'error': ...} for the report."""
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        try:
            with _quiet():
                return fn(*args, **kwargs)
        except NoSeries as e:
            return {'error': str(e)}
        except np.linalg.LinAlgError as e:
            return {'error': f'the fit failed ({e}): a series may be constant, or two may be the same up to a scale'}
    return inner


# ---- the series and their stationarity ------------------------------------------

def _adf_kpss(v, trend='c'):
    from statsmodels.tools.sm_exceptions import InterpolationWarning
    from statsmodels.tsa.stattools import adfuller, kpss
    out = {}
    try:
        st, p, lag, nobs, crit, _ = adfuller(v, regression=trend, autolag='AIC')
        out.update({'adf': _f(st), 'adf_p': _f(p), 'adf_lags': int(lag)})
    except Exception as e:  # too short for the lags
        out['adf_error'] = str(e)
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            st, p, lags, crit = kpss(v, regression='ct' if trend == 'ct' else 'c', nlags='auto')
        bound = None
        for m in w:
            if issubclass(m.category, InterpolationWarning):
                bound = '>' if 'greater' in str(m.message) else '<'
            elif not issubclass(m.category, (DeprecationWarning, FutureWarning)):
                warnings.warn(str(m.message), m.category)
        out.update({'kpss': _f(st), 'kpss_p': _f(p), 'kpss_bound': bound, 'kpss_lags': int(lags)})
    except Exception as e:
        out['kpss_error'] = str(e)
    return out


def _verdict(r, alpha):
    a, k = r.get('adf_p'), r.get('kpss_p')
    if a is None or k is None:
        return 'too short to tell'
    adf_says = a < alpha                    # rejects a unit root
    kpss_says = not (k < alpha)             # does not reject stationarity
    if adf_says and kpss_says:
        return 'stationary'
    if not adf_says and not kpss_says:
        return 'unit root: difference'
    return 'unclear'


@api('multits.series')
@_common
def series(table, y, time=None, rows=None, excluded=None, exog=None, log=False, diff=False, trend='c', alpha=0.05,
           where=None, table_name='data'):
    """The series as analysed, on their time axis, with ADF and KPSS tests."""
    P = prepare(table, y, time, rows, excluded, exog, log, diff)
    S = P.S
    reg = trend if trend in N_TREND else 'c'
    summary = []
    for j, c in enumerate(P.names):
        v = P.Y[:, j]
        r = {'series': P.label(c), 'column': c, 'n': int(len(v)), 'mean': _f(np.mean(v)), 'sd': _f(np.std(v, ddof=1)),
             'filled': P.filled.get(c, 0)}
        if np.std(v) > 0 and len(v) >= 12:
            r.update(_adf_kpss(v, reg))
        else:
            r['adf_error'] = r['kpss_error'] = 'needs at least 12 values that vary'
        r['verdict'] = _verdict(r, alpha)
        summary.append(r)
    shown = P.Y.copy()
    if not P.filled:
        values = shown
    else:   # the plot shows the values of the table: the filled ones are gaps
        miss = ~np.isfinite(P.raw)
        values = shown.copy()
        if P.diff:
            gone = miss[1:] | miss[:-1]
            values[gone] = np.nan
        else:
            values[miss] = np.nan
    out = {'names': P.names, 'labels': [P.label(c) for c in P.names], 'exog': P.exog, 'time': S.time_name, 'kind': S.kind,
           'freq': S.freq, 'freq_label': S.freq_label, 'irregular': S.irregular, 'n': P.n, 't': _arr(P.t), 'rows': P.rows,
           'values': [_arr(values[:, j]) for j in range(P.k)], 'filled': P.filled, 'log': P.log, 'diff': P.diff,
           'trend': reg, 'stationarity': summary, 'notes': P.notes, 'alpha': alpha}
    c = _code_data(P, table_name, where, ['from statsmodels.tsa.stattools import adfuller, kpss'])
    c += ['for c in Y:   # ADF (a small p-value: no unit root) and KPSS (a small p-value: not stationary)',
          f'    print(c, adfuller(Y[c], regression={reg!r}, autolag="AIC")[:2], kpss(Y[c], regression={("ct" if reg == "ct" else "c")!r}, nlags="auto")[:2])']
    out['code'] = '\n'.join(c)
    out['plot_code'] = {'series': _series_plot(P, table_name, where)}
    return out


# ---- lag order selection ------------------------------------------------------

def max_lag(P, trend):
    """The largest lag whose VAR can be fitted on the common sample: statsmodels'
    (n - k - trend terms) // (k + 1), less the exogenous columns."""
    return int((P.n - P.k - N_TREND.get(trend, 1) - P.m) // (1 + P.k))


@api('multits.select_order')
@_common
def select_order(table, y, time=None, rows=None, excluded=None, exog=None, log=False, diff=False, maxlags=8, trend='c',
                 where=None, table_name='data'):
    """VAR.select_order: every lag from 0 to maxlags fitted on the same
    n - maxlags observations, so that the criteria compare."""
    from statsmodels.tsa.api import VAR
    P = prepare(table, y, time, rows, excluded, exog, log, diff)
    asked = max(1, int(maxlags or 8))
    cap = max_lag(P, trend)
    if cap < 1:
        raise NoSeries(f'too few observations ({P.n}) to select a lag for {P.k} series')
    ml = min(asked, cap)
    with _quiet():
        sel = VAR(P.frame(), exog=P.exog_frame()).select_order(ml, trend=trend)
    # statsmodels starts at lag 1 when there is neither a trend nor an
    # exogenous column (a VAR(0) would have nothing to fit)
    p_min = 0 if P.exog or trend != 'n' else 1
    rows_ = [{'lag': q, **{c: _f(sel.ics[c][q - p_min]) for c in CRITERIA}} for q in range(p_min, ml + 1)]
    chosen = {c: int(sel.selected_orders[c]) for c in CRITERIA}
    notes = []
    if ml < asked:
        notes.append(f'The maximum lag is {ml}, not {asked}: a VAR({ml + 1}) of {P.k} series cannot be fitted on {P.n} observations.')
    c = _code_data(P, table_name, where, ['from statsmodels.tsa.api import VAR'])
    c += [f'sel = VAR(Y{", exog=X" if P.exog else ""}).select_order({ml}, trend={trend!r})',
          'print(sel.summary()); print(sel.selected_orders)']
    return {'maxlags': ml, 'asked': asked, 'nobs': int(P.n - ml), 'trend': trend, 'rows': rows_, 'selected': chosen,
            'notes': notes, 'code': '\n'.join(c)}


# ---- the VAR(p) fit ---------------------------------------------------------------

def _terms(res, P, order=None):
    """(JMP-style term, statsmodels' name) of each row of res.params: the trend
    terms, the exogenous columns, then lag 1 of every series, lag 2 ..."""
    names = list(order) if order else P.names
    kt = int(res.k_trend)
    sm_names = list(res.exog_names) if hasattr(res, 'exog_names') else list(res.params.index)
    out = []
    for j, nm in enumerate(sm_names):
        if j < kt:
            out.append(({'const': 'Intercept', 'trend': 'Time Trend'}.get(nm, nm), nm, 0))
        elif j < kt + P.m:
            out.append((P.exog[j - kt], nm, 0))
        else:
            i = j - kt - P.m
            lag, var = i // len(names) + 1, names[i % len(names)]
            out.append((f'{var}(t−{lag})', nm, lag))
    return out


def companion_eigenvalues(res):
    from statsmodels.tsa.vector_ar.util import comp_matrix
    return np.linalg.eigvals(comp_matrix(res.coefs))


@api('multits.var')
@_common
def var_fit(table, y, time=None, rows=None, excluded=None, exog=None, log=False, diff=False, p=1, trend='c', alpha=0.05,
            whiteness_lags=None, adjusted=False, where=None, table_name='data'):
    """The VAR(p) by least squares, equation by equation, with its
    diagnostics."""
    P = prepare(table, y, time, rows, excluded, exog, log, diff)
    res = _fit(P, p, trend)
    p = int(res.k_ar)
    params, se, tv, pv = (np.asarray(x, dtype=float) for x in (res.params, res.stderr, res.tvalues, res.pvalues))
    terms = _terms(res, P)
    equations = []
    for i, c in enumerate(P.names):
        equations.append({'name': c, 'label': P.label(c), 'rows': [
            {'term': term, 'sm': nm, 'lag': lag, 'estimate': _f(params[j, i]), 'se': _f(se[j, i]), 't': _f(tv[j, i]), 'p': _f(pv[j, i])}
            for j, (term, nm, lag) in enumerate(terms)]})
    eig = companion_eigenvalues(res)
    order_ = np.argsort(-np.abs(eig), kind='stable')
    eig = eig[order_]
    stability = {'stable': bool(res.is_stable()), 'max_modulus': _f(np.max(np.abs(eig))) if len(eig) else None,
                 'eigenvalues': [{'real': _f(e.real), 'imag': _f(e.imag), 'modulus': _f(abs(e)),
                                  'period': _f(2 * math.pi / abs(math.atan2(e.imag, e.real))) if abs(e.imag) > 1e-12 else None} for e in eig]}
    wl = int(whiteness_lags) if whiteness_lags else max(10, p + 4)
    wl = max(wl, p + 1)
    diag = {}
    try:
        w = res.test_whiteness(nlags=wl, signif=alpha, adjusted=bool(adjusted))
        diag['whiteness'] = {'stat': _f(w.test_statistic), 'crit': _f(w.crit_value), 'p': _f(w.pvalue), 'df': int(w.df), 'nlags': wl, 'adjusted': bool(adjusted)}
    except Exception as e:  # too few observations for the lags
        diag['whiteness'] = {'error': str(e), 'nlags': wl}
    try:
        nt = res.test_normality(signif=alpha)
        diag['normality'] = {'stat': _f(nt.test_statistic), 'crit': _f(nt.crit_value), 'p': _f(nt.pvalue), 'df': int(nt.df)}
    except Exception as e:
        diag['normality'] = {'error': str(e)}
    resid = np.asarray(res.resid, dtype=float)
    sd = np.sqrt(np.diag(np.asarray(res.sigma_u, dtype=float)))
    out = {'p': p, 'trend': trend, 'trend_label': TRENDS[trend], 'k': P.k, 'names': P.names, 'labels': [P.label(c) for c in P.names],
           'exog': P.exog, 'nobs': int(res.nobs), 'df_resid': int(res.df_resid), 'per_eq': int(res.df_model),
           'summary': {'llf': _f(res.llf), 'aic': _f(res.aic), 'bic': _f(res.bic), 'hqic': _f(res.hqic), 'fpe': _f(res.fpe),
                       'detomega': _f(res.detomega)},
           'equations': equations, 'resid_corr': _mat(res.resid_corr), 'resid_sd': _arr(sd), 'sigma_u': _mat(res.sigma_u),
           'stability': stability, **diag, 'alpha': alpha,
           'resid': {'rows': P.rows[p:], 't': _arr(P.t[p:]), 'values': [_arr(resid[:, i]) for i in range(P.k)]},
           'notes': P.notes}
    c = _code_data(P, table_name, where, ['from statsmodels.tsa.api import VAR', 'from statsmodels.tsa.vector_ar.util import comp_matrix'])
    c += [_fit_code(P, p, trend), 'print(res.summary())   # coefficients, standard errors, t and p (normal) by equation',
          'print(np.linalg.eigvals(comp_matrix(res.coefs)), res.is_stable())   # stable: every eigenvalue inside the unit circle',
          f'print(res.test_whiteness(nlags={wl}, signif={alpha!r}, adjusted={bool(adjusted)}).summary())',
          f'print(res.test_normality(signif={alpha!r}).summary())']
    out['code'] = '\n'.join(c)
    labels = [P.label(x) for x in P.names]
    fit = _fit_code(P, p, trend)
    corr = [*_code_data(P, table_name, where, ['from statsmodels.tsa.api import VAR', 'from matplotlib.colors import LinearSegmentedColormap'], graph=True), fit,
            'M = np.asarray(res.resid_corr)   # the correlations of the equations\' residuals',
            *_heatmap(labels, labels, 'LinearSegmentedColormap.from_list("diverging", ["#2f6ec7", "#f6f3f0", "#c0392b"])', -1, 1,
                      'f"{M[i, j]:.3f}".replace("-", "−")', 'Residual correlation colour map')]
    stab = [*_code_data(P, table_name, where, ['from statsmodels.tsa.api import VAR', 'from statsmodels.tsa.vector_ar.util import comp_matrix'], graph=True), fit,
            'eig = np.linalg.eigvals(comp_matrix(res.coefs)); eig = eig[np.argsort(-np.abs(eig), kind="stable")]   # the companion matrix\'s eigenvalues, the largest first',
            'th = np.linspace(0, 2 * np.pi, 121); lim = max(1.15, *(np.abs(eig) + 0.1))', '', SIZE,
            'fig, ax = plt.subplots(figsize=size, layout="constrained")',
            f'ax.axhline(0, color="{GRID}", linewidth={_pt(1)}); ax.axvline(0, color="{GRID}", linewidth={_pt(1)})',
            f'ax.plot(np.cos(th), np.sin(th), color="{MUTED}", linewidth={_pt(1)})   # the unit circle',
            f'ax.scatter(eig.real, eig.imag, s={(8 * 0.72) ** 2:.4g}, c=["{BASE}" if abs(e) < 1 else "#c0392b" for e in eig], edgecolors="{SURFACE}", linewidths={_pt(1)})'
            '   # red: on or outside the circle',
            'ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim); ax.set_aspect("equal")',
            'ax.set_xlabel("Real"); ax.set_ylabel("Imaginary"); ax.set_title("Companion matrix eigenvalues")', 'plt.show()']
    out['plot_code'] = {'corr': corr, 'stability': stab}
    return out


# ---- Granger causality ---------------------------------------------------------------

def _test_row(t, caused, causing):
    df = t.df
    row = {'caused': caused, 'causing': causing, 'stat': _f(t.test_statistic), 'crit': _f(t.crit_value), 'p': _f(t.pvalue)}
    if isinstance(df, (tuple, list)):
        row['df'], row['df_den'] = int(df[0]), int(df[1])
    else:
        row['df'], row['df_den'] = int(df), None
    return row


@api('multits.granger')
@_common
def granger(table, y, time=None, rows=None, excluded=None, exog=None, log=False, diff=False, p=1, trend='c', kind='f',
            alpha=0.05, where=None, table_name='data'):
    """test_causality for every ordered pair (does x help to forecast y beyond
    y's own past and the others'?), for all the others together, and
    test_inst_causality for each series."""
    P = prepare(table, y, time, rows, excluded, exog, log, diff)
    res = _fit(P, p, trend)
    kind = 'wald' if kind == 'wald' else 'f'
    k = P.k
    M = [[None] * k for _ in range(k)]
    tests = []
    for j in range(k):
        for i in range(k):
            if i == j:
                continue
            t = res.test_causality(j, [i], kind=kind, signif=alpha)
            M[i][j] = _f(t.pvalue)
            tests.append(_test_row(t, P.names[j], P.names[i]))
    others = []
    if k > 2:
        for j in range(k):
            t = res.test_causality(j, [i for i in range(k) if i != j], kind=kind, signif=alpha)
            row = _test_row(t, P.names[j], 'all the others')
            others.append(row)
            tests.append(row)
    inst = []
    for i in range(k):
        t = res.test_inst_causality(i, signif=alpha)
        inst.append({'variable': P.names[i], 'stat': _f(t.test_statistic), 'crit': _f(t.crit_value), 'p': _f(t.pvalue), 'df': int(t.df)})
    c = _code_data(P, table_name, where, ['from statsmodels.tsa.api import VAR'])
    c += [_fit_code(P, int(res.k_ar), trend),
          'names = list(Y.columns)',
          'for caused in names:   # row: the causing series; H0: it does not Granger-cause the caused one',
          '    for causing in names:',
          '        if causing != caused:',
          f'            print(causing, "->", caused, res.test_causality(caused, [causing], kind={kind!r}).pvalue)']
    if k > 2:
        c.append(f'    print("all the others ->", caused, res.test_causality(caused, [x for x in names if x != caused], kind={kind!r}).pvalue)')
    c.append('for x in names:   # instantaneous causality: are the residuals correlated?')
    c.append('    print(x, res.test_inst_causality(x).pvalue)')
    rows = P.names + (['all the others'] if k > 2 else [])
    a = min(0.5, max(1e-4, float(alpha)))
    g = [*_code_data(P, table_name, where, ['from statsmodels.tsa.api import VAR', 'from matplotlib.colors import LinearSegmentedColormap'], graph=True),
         _fit_code(P, int(res.k_ar), trend), 'names = list(Y.columns); k = len(names)',
         f'M = np.full(({len(rows)}, k), np.nan)   # the p-values: the row causes the column',
         'for j, caused in enumerate(names):', '    for i, causing in enumerate(names):', '        if i != j:',
         f'            M[i, j] = res.test_causality(caused, [causing], kind={kind!r}, signif={alpha!r}).pvalue']
    if k > 2:
        g.append(f'    M[k, j] = res.test_causality(caused, [x for x in names if x != caused], kind={kind!r}, signif={alpha!r}).pvalue   # all the others together')
    g += [f'a = {a!r}   # α: red below it, the deeper the smaller; blue toward 1',
          'cmap = LinearSegmentedColormap.from_list("p", [(0, "#c0392b"), (a / 10, "#cf5747"), (a, "#ebb3a6"), (a + 1e-6, "#f6f3f0"), (1, "#bccfe6")])',
          *_heatmap(P.names, rows, 'cmap', 0, 1, f'("<.0001" if M[i, j] < 0.0001 else f"{{M[i, j]:.4f}}") + ("*" if M[i, j] < {alpha!r} else "")',
                    'Granger causality p-values')]
    return {'kind': kind, 'names': P.names, 'p': int(res.k_ar), 'matrix': M, 'others': [r['p'] for r in others], 'tests': tests,
            'inst': inst, 'alpha': alpha, 'code': '\n'.join(c), 'plot_code': {'granger': g}}


# ---- impulse responses and the variance decomposition -----------------------------------

@api('multits.irf')
@_common
def irf(table, y, time=None, rows=None, excluded=None, exog=None, log=False, diff=False, p=1, trend='c', horizon=10,
        orth=True, cumulative=False, bands='asym', repl=1000, alpha=0.05, order=None, where=None, table_name='data'):
    """Impulse responses over 0..horizon: orthogonalized (a one standard
    deviation shock through the Cholesky factor of the residual covariance, in
    the order of the columns) or not, cumulative or not, with asymptotic or
    Monte Carlo bands."""
    P = prepare(table, y, time, rows, excluded, exog, log, diff)
    order = _order(P, order)
    names = list(order) if order else P.names
    res = _fit(P, p, trend, order)
    H = max(1, min(200, int(horizon or 10)))
    ir = res.irf(H)
    orth, cumulative = bool(orth), bool(cumulative)
    if cumulative:
        val = ir.orth_cum_effects if orth else ir.cum_effects
    else:
        val = ir.orth_irfs if orth else ir.irfs
    val = np.asarray(val, dtype=float)
    lo = hi = None
    repl = max(50, min(10000, int(repl or 1000)))
    notes = []
    what = 'cumulative ' if cumulative else ''
    if bands == 'mc':
        seed = np.random.MT19937(SEED)
        fn = ir.cum_errband_mc if cumulative else ir.errband_mc
        lo, hi = (np.asarray(x, dtype=float) for x in fn(orth=orth, repl=repl, signif=alpha, seed=seed))
        band = (f'{100 * (1 - alpha):g}% Monte Carlo bands: the fitted VAR simulated {repl} times, refitted each time, and the '
                f'{100 * alpha / 2:g}% and {100 * (1 - alpha / 2):g}% points of the {what}responses (statsmodels\' '
                f'{"cum_errband_mc" if cumulative else "errband_mc"}; a fixed seed, {SEED}).')
        if P.exog:
            notes.append('The simulations leave out the exogenous columns (statsmodels simulates the VAR with its intercept only), '
                         'so the Monte Carlo bands are approximate here; the asymptotic ones take them into account.')
    elif bands == 'asym':
        se = np.asarray(ir.cum_effect_stderr(orth=orth) if cumulative else ir.stderr(orth=orth), dtype=float)
        q = stats.norm.ppf(1 - alpha / 2)
        lo, hi = val - q * se, val + q * se
        band = (f'{100 * (1 - alpha):g}% asymptotic bands: ± {q:.4g} standard errors from the delta method (Lütkepohl 2005, '
                f'section 3.7; statsmodels\' {"cum_effect_stderr" if cumulative else "stderr"}).')
    else:
        band = 'No confidence bands.'
    shock = (f'Orthogonalized: a shock of one standard deviation, through the Cholesky factor of the residual covariance in the '
             f'order {", ".join(names)}; a series responds at once only to the shocks of the series before it.' if orth else
             'Not orthogonalized: a shock of one unit in one equation\'s error, the others held at zero (the moving average '
             'coefficients of the VAR).')
    c = _code_data(P, table_name, where, ['from statsmodels.tsa.api import VAR', 'from scipy import stats'])
    c += [_fit_code(P, int(res.k_ar), trend, order), f'irf = res.irf({H})']
    attr = ('orth_cum_effects' if orth else 'cum_effects') if cumulative else ('orth_irfs' if orth else 'irfs')
    c.append(f'resp = irf.{attr}   # resp[h, response, impulse]')
    if bands == 'mc':
        c.append(f'# a bit generator as the seed: with an integer seed statsmodels 0.14 draws the same path in every replication')
        c.append(f'lower, upper = irf.{"cum_errband_mc" if cumulative else "errband_mc"}(orth={orth}, repl={repl}, signif={alpha!r}, seed=np.random.MT19937({SEED}))')
    elif bands == 'asym':
        c.append(f'se = irf.{"cum_effect_stderr" if cumulative else "stderr"}(orth={orth}); q = stats.norm.ppf(1 - {alpha!r}/2)')
        c.append('lower, upper = resp - q*se, resp + q*se')
    # the graph: the same responses and bands, a cell for each response (row) and shock (column)
    head = c.index(f'irf = res.irf({H})')
    g = [*_code_data(P, table_name, where, ['from statsmodels.tsa.api import VAR', 'from scipy import stats'], graph=True), *c[head - 1:],
         f'names = {J(names)}', f'H = {H}; h = np.arange(H + 1)', '', SIZE,
         'fig, axes = plt.subplots(len(names), len(names), sharex=True, squeeze=False, figsize=size, layout="constrained")',
         'for i, response in enumerate(names):   # a row for each responding series',
         '    for j, impulse in enumerate(names):   # a column for each shock',
         '        ax = axes[i, j]']
    if lo is not None:
        g += [f'        ax.fill_between(h, lower[:, i, j], upper[:, i, j], color="{BASE}", alpha=0.14, linewidth=0)   # the band',
              f'        ax.plot(h, upper[:, i, j], color="{BASE}", alpha=0.4, linewidth={_pt(0.8)}); ax.plot(h, lower[:, i, j], color="{BASE}", alpha=0.4, linewidth={_pt(0.8)})']
    g += [f'        ax.plot(h, resp[:, i, j], color="{BASE}", linewidth={_pt(1.6)}, marker="o", markersize={_pt(3.5)})',
          f'        ax.plot([0, H], [0, 0], color="{MUTED}", linewidth={_pt(0.8)}, linestyle=":")',
          '        ax.set_title(f"{impulse} → {response}", fontsize=8); ax.set_xlim(-0.3, H + 0.3)',
          'for ax in axes[-1]:', '    ax.set_xlabel("h")', 'fig.suptitle("Impulse responses", fontsize=10)', 'plt.show()']
    return {'names': names, 'labels': [P.label(x) for x in names], 'horizon': H, 'orth': orth, 'cumulative': cumulative,
            'bands': bands if bands in ('asym', 'mc') else 'none', 'repl': repl, 'seed': SEED, 'alpha': alpha,
            'values': _cube(val), 'lower': _cube(lo) if lo is not None else None, 'upper': _cube(hi) if hi is not None else None,
            'band_note': band, 'shock_note': shock, 'notes': notes, 'code': '\n'.join(c), 'plot_code': {'irf': g}}


@api('multits.fevd')
@_common
def fevd(table, y, time=None, rows=None, excluded=None, exog=None, log=False, diff=False, p=1, trend='c', horizon=10,
         order=None, where=None, table_name='data'):
    """The forecast error variance decomposition: the share of each series'
    h-step forecast error variance due to each orthogonalized shock."""
    P = prepare(table, y, time, rows, excluded, exog, log, diff)
    order = _order(P, order)
    names = list(order) if order else P.names
    res = _fit(P, p, trend, order)
    H = max(1, min(200, int(horizon or 10)))
    fe = res.fevd(H)
    c = _code_data(P, table_name, where, ['from statsmodels.tsa.api import VAR'])
    c += [_fit_code(P, int(res.k_ar), trend, order), f'fevd = res.fevd({H})', 'fevd.summary()   # fevd.decomp[series, h - 1, shock]']
    g = [*_code_data(P, table_name, where, ['from statsmodels.tsa.api import VAR', 'from matplotlib.ticker import PercentFormatter'], graph=True),
         _fit_code(P, int(res.k_ar), trend, order), f'dec = res.fevd({H}).decomp   # dec[series, h − 1, shock]',
         f'names, labels = {J(names)}, {J([P.label(x) for x in names])}', f'palette = {J(PALETTE)}   # the page\'s colours', f'hs = np.arange(1, {H + 1})', '', SIZE,
         'fig, axes = plt.subplots(len(names), 1, sharex=True, squeeze=False, figsize=size, layout="constrained")',
         'for i, ax in enumerate(axes[:, 0]):   # a panel for each series',
         '    bottom = np.zeros(len(hs))',
         '    for j, shock in enumerate(names):   # the share of each shock, stacked',
         '        ax.bar(hs, dec[i, :, j], bottom=bottom, width=0.82, color=palette[j % len(palette)], label=shock)',
         '        bottom = bottom + dec[i, :, j]',
         '    ax.set_ylim(0, 1); ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0)); ax.set_ylabel(labels[i], fontsize=8)',
         'axes[-1, 0].set_xlabel("Steps ahead")',
         'fig.legend(*axes[0, 0].get_legend_handles_labels(), loc="outside lower center", ncols=min(4, len(names)), frameon=False, fontsize=8)',
         'fig.suptitle("Variance decomposition", fontsize=10)', 'plt.show()']
    return {'names': names, 'labels': [P.label(x) for x in names], 'horizon': H, 'decomp': _cube(fe.decomp), 'code': '\n'.join(c), 'plot_code': {'fevd': g}}


# ---- forecasts ------------------------------------------------------------------------------

def level_forecast(res, last_level, mean, h):
    """The forecasts of a VAR in first differences summed back onto the last
    level, and their variances: the level h steps ahead is the last level plus
    the first h differences, whose error is sum_s Psi_(h-s) u_(T+s) with Psi_m
    the cumulated moving average coefficients, so its covariance is
    sum_(m<h) Psi_m Sigma_u Psi_m' (statsmodels' mse with Psi for Phi)."""
    psi = np.cumsum(np.asarray(res.ma_rep(h - 1), dtype=float), axis=0)[:h]
    sig = np.asarray(res.sigma_u, dtype=float)
    cov = np.cumsum(np.einsum('hij,jk,hlk->hil', psi, sig, psi), axis=0)
    lev = np.asarray(last_level, dtype=float) + np.cumsum(mean, axis=0)
    return lev, np.sqrt(np.diagonal(cov, axis1=1, axis2=2))


@api('multits.forecast')
@_common
def forecast(table, y, time=None, rows=None, excluded=None, exog=None, log=False, diff=False, p=1, trend='c', h=12,
             alpha=0.05, original=True, where=None, table_name='data'):
    """forecast_interval of the VAR, h periods on from the end of the span;
    for a transformed series also in the units of the table: the differences
    summed back onto the last level (with the variances of the sums) and the
    logarithm undone (so the forecast is the median)."""
    P = prepare(table, y, time, rows, excluded, exog, log, diff)
    res = _fit(P, p, trend)
    p = int(res.k_ar)
    h = max(1, min(1000, int(h or 12)))
    Xf, notes = P.exog_future(h)
    with _quiet():
        mean, lo, hi = (np.asarray(v, dtype=float) for v in res.forecast_interval(P.Y[-p:], h, alpha=alpha, exog_future=Xf))
    q = stats.norm.ppf(1 - alpha / 2)
    se = (hi - mean) / q
    fitted = np.asarray(res.fittedvalues, dtype=float)
    transformed = P.log or P.diff
    back = bool(original) and transformed
    out = {'names': P.names, 'labels': [P.label(c) for c in P.names], 'h': h, 'p': p, 'level': 1 - alpha, 't': P.future(h),
           'transformed': {'mean': _mat(mean.T), 'lower': _mat(lo.T), 'upper': _mat(hi.T), 'se': _mat(se.T),
                           'fitted': [[None] * p + _arr(fitted[:, i]) for i in range(P.k)], 'observed': [_arr(P.Y[:, i]) for i in range(P.k)],
                           't_obs': _arr(P.t), 'rows': P.rows},
           'units': 'original' if back else 'as analysed', 'notes': notes}
    if back:
        if P.diff:
            lev, lse = level_forecast(res, P.L[-1], mean, h)
            flo, fhi = lev - q * lse, lev + q * lse
            fit_lev = P.L[p:-1] + fitted if len(fitted) else fitted       # level t = level t-1 + the predicted difference
            fit_lev = np.vstack([np.full((p + 1, P.k), np.nan), fit_lev])
        else:
            lev, lse, flo, fhi = mean, se, lo, hi
            fit_lev = np.vstack([np.full((p, P.k), np.nan), fitted])
        if P.log:
            lev, flo, fhi, fit_lev = np.exp(lev), np.exp(flo), np.exp(fhi), np.exp(fit_lev)
            lse = None
        out['original'] = {'mean': _mat(lev.T), 'lower': _mat(flo.T), 'upper': _mat(fhi.T), 'se': _mat(lse.T) if lse is not None else None,
                           'fitted': [_arr(fit_lev[:, i]) for i in range(P.k)], 'observed': [_arr(P.raw[:, i]) for i in range(P.k)],
                           't_obs': _arr(P.t0), 'rows': P.rows0}
        how = []
        if P.diff:
            how.append('the forecast differences are summed onto the last level, and the intervals use the variance of those sums '
                       '(Σ Ψₘ Σᵤ Ψₘ\' with Ψₘ the cumulated moving average coefficients)')
        if P.log:
            how.append('exp() undoes the logarithm, so the forecast is the median and the interval is not symmetric')
        out['original_note'] = 'In the units of the table: ' + '; '.join(how) + '.'
    c = _code_data(P, table_name, where, ['from statsmodels.tsa.api import VAR', 'from scipy import stats'], keep_levels=back and P.diff)
    c.append(_fit_code(P, p, trend))
    if P.exog:
        c.append('X_future = np.array(' + json.dumps([[_f(v) for v in row] for row in Xf]) + ')   # the exogenous columns after the span')
    c.append(f'mean, lower, upper = res.forecast_interval(Y.values[-{p}:], {h}, alpha={alpha!r}{", exog_future=X_future" if P.exog else ""})')
    if back and P.diff:
        c += ['# in the units of the table: the differences summed onto the last level, with the variances of the sums',
              'level = L.iloc[-1].to_numpy() + np.cumsum(mean, axis=0)',
              f'psi = np.cumsum(res.ma_rep({h - 1}), axis=0)   # cumulated moving average coefficients',
              f'var = np.cumsum([np.diag(m @ np.asarray(res.sigma_u) @ m.T) for m in psi], axis=0); q = stats.norm.ppf(1 - {alpha!r}/2)',
              'lower_level, upper_level = level - q*np.sqrt(var), level + q*np.sqrt(var)']
        if P.log:
            c.append('level, lower_level, upper_level = np.exp(level), np.exp(lower_level), np.exp(upper_level)   # medians')
    elif back and P.log:
        c.append('level, lower_level, upper_level = np.exp(mean), np.exp(lower), np.exp(upper)   # medians, in the units of the table')
    out['code'] = '\n'.join(c)
    # the graph: the same forecasts, and the one-step-ahead predictions, in the units the page shows
    g = [*_code_data(P, table_name, where, ['from statsmodels.tsa.api import VAR', 'from scipy import stats'], keep_levels=back and P.diff, graph=True),
         *c[c.index(_fit_code(P, p, trend)):], 'fv = np.asarray(res.fittedvalues, dtype=float)   # the one-step-ahead predictions']
    if not back:
        g += ['obs, t_o = Y, ' + _tx(P, 'Y'), f'fitted = np.vstack([np.full(({p}, {P.k}), np.nan), fv])',
              'f_mean, f_lower, f_upper = mean, lower, upper', f'names = {J([P.label(x) for x in P.names])}']
    else:
        if P.diff:
            g += ['f_mean, f_lower, f_upper = level, lower_level, upper_level',
                  f'fitted = np.vstack([np.full(({p + 1}, {P.k}), np.nan), L.to_numpy()[{p}:-1] + fv])   # each level the one before plus the predicted difference']
            if P.log:
                g.append('fitted = np.exp(fitted)')
        else:
            g += ['f_mean, f_lower, f_upper = level, lower_level, upper_level', f'fitted = np.exp(np.vstack([np.full(({p}, {P.k}), np.nan), fv]))']
        g += ['obs, t_o = raw, ' + _tx(P, 'raw') + '   # the table\'s values', f'names = {J(P.names)}']
    g += [_future(P, h, 't_o[-1]'), *_forecast_plot(P, 'VAR forecasts', 'obs', 'fitted')]
    out['plot_code'] = {'forecast': g}
    return out


# ---- cointegration ---------------------------------------------------------------------------------

def _levels(P):
    return pd.DataFrame(P.L, columns=P.names)


@api('multits.johansen')
@_common
def johansen(table, y, time=None, rows=None, excluded=None, exog=None, log=False, diff=False, det_order=0, k_ar_diff=1,
             method='trace', alpha=0.05, where=None, table_name='data'):
    """Johansen's trace and maximum eigenvalue tests of the cointegration rank
    (coint_johansen) on the levels (logs, with Log Transform), and the rank
    that select_coint_rank chooses."""
    from statsmodels.tsa.vector_ar.vecm import coint_johansen, select_coint_rank
    P = prepare(table, y, time, rows, excluded, exog, log, diff)
    det_order = int(det_order)
    if det_order not in (-1, 0, 1):
        raise NoSeries('det_order must be -1, 0 or 1')
    kd = max(0, int(k_ar_diff or 0))
    if len(P.L) - kd - 1 < P.k * (kd + 1) + 2:
        raise NoSeries(f'too few observations ({len(P.L)}) for {kd} lagged differences')
    method = 'maxeig' if method == 'maxeig' else 'trace'
    signif = min((0.1, 0.05, 0.01), key=lambda s: abs(s - alpha))
    # coint_johansen takes the eigenvalues of a product of symmetric matrices
    # with np.linalg.eig, which returns them as complex numbers with zero
    # imaginary parts; storing them in its float arrays makes numpy warn.
    # The warning says nothing about the test unless the parts are not zero.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        jr = coint_johansen(P.L, det_order, kd)
        rk = select_coint_rank(P.L, det_order, kd, method=method, signif=signif)
    imag = float(np.max(np.abs(np.imag(np.asarray(jr.eig))))) if np.iscomplexobj(jr.eig) else 0.0
    for w in caught:
        if issubclass(w.category, np.exceptions.ComplexWarning if hasattr(np, 'exceptions') else np.ComplexWarning) and imag <= 1e-9:
            continue
        warnings.warn(str(w.message), w.category)
    eig = np.real(np.asarray(jr.eig))
    rows_ = []
    for r in range(P.k):
        rows_.append({'rank': r, 'h0': f'r ≤ {r}', 'eig': _f(eig[r]), 'trace': _f(jr.lr1[r]), 'trace90': _f(jr.cvt[r, 0]),
                      'trace95': _f(jr.cvt[r, 1]), 'trace99': _f(jr.cvt[r, 2]), 'maxeig': _f(jr.lr2[r]), 'max90': _f(jr.cvm[r, 0]),
                      'max95': _f(jr.cvm[r, 1]), 'max99': _f(jr.cvm[r, 2])})
    notes = []
    if abs(signif - alpha) > 1e-12:
        notes.append(f'The critical values are tabulated at 10%, 5% and 1%: the rank is chosen at {100 * signif:g}%, the nearest to α = {alpha:g}.')
    c = _code_data(P, table_name, where, levels=True, imports=['from statsmodels.tsa.vector_ar.vecm import coint_johansen, select_coint_rank'])
    c += [f'jr = coint_johansen(Y, {det_order}, {kd})   # det_order {det_order}: {DET_ORDER[det_order]}',
          'print(jr.eig, jr.lr1, jr.cvt, jr.lr2, jr.cvm)   # eigenvalues; trace and max-eigenvalue statistics with their 90/95/99% critical values',
          f'print(select_coint_rank(Y, {det_order}, {kd}, method={method!r}, signif={signif!r}).summary())']
    return {'names': P.names, 'det_order': det_order, 'det_label': DET_ORDER[det_order], 'k_ar_diff': kd, 'method': method,
            'signif': signif, 'rank': int(rk.rank), 'rows': rows_, 'nobs': int(len(P.L) - kd - 1),
            'evec': _mat(np.real(np.asarray(jr.evec))), 'log': P.log, 'notes': notes, 'code': '\n'.join(c)}


@api('multits.vecm')
@_common
def vecm(table, y, time=None, rows=None, excluded=None, exog=None, log=False, diff=False, rank=1, k_ar_diff=1,
         deterministic='co', h=12, alpha=0.05, where=None, table_name='data'):
    """The vector error correction model of the given cointegration rank by
    maximum likelihood (statsmodels' VECM): the loadings alpha, the
    cointegrating vectors beta (normalised: the first r rows are the identity),
    the short-run coefficients Gamma, and forecasts of the levels."""
    from statsmodels.tsa.vector_ar.vecm import VECM
    P = prepare(table, y, time, rows, excluded, exog, log, diff)
    r = 1 if rank is None else int(rank)
    if not 1 <= r <= P.k - 1:
        raise NoSeries(f'the cointegration rank of a VECM is 1 to {P.k - 1}')
    det = deterministic if deterministic in DETERMINISTIC else 'co'
    kd = max(0, int(k_ar_diff or 0))
    if len(P.L) - kd - 1 < P.k * (kd + 1) + r + 3:
        raise NoSeries(f'too few observations ({len(P.L)}) for this VECM')
    X = pd.DataFrame(P.X0, columns=P.exog) if P.exog else None
    with _quiet():
        res = VECM(_levels(P), exog=X, k_ar_diff=kd, coint_rank=r, deterministic=det).fit()
    names = P.names
    ec = [f'ec{j + 1}' for j in range(r)]

    def cells(est, se, tv, pv, i, j):
        return {'estimate': _f(est[i, j]), 'se': _f(se[i, j]), 'z': _f(tv[i, j]), 'p': _f(pv[i, j])}

    A = [np.asarray(x, dtype=float) for x in (res.alpha, res.stderr_alpha, res.tvalues_alpha, res.pvalues_alpha)]
    alpha_rows = [{'equation': names[i], 'term': ec[j], **cells(*A, i, j)} for i in range(P.k) for j in range(r)]
    B = [np.asarray(x, dtype=float) for x in (res.beta, res.stderr_beta, res.tvalues_beta, res.pvalues_beta)]
    beta_rows = []
    for j in range(r):
        for i in range(P.k):
            row = {'relation': ec[j], 'variable': names[i], **cells(*B, i, j)}
            if i < r:   # the normalisation: fixed, not estimated
                row.update({'se': None, 'z': None, 'p': None})
            beta_rows.append(row)
    if det in ('ci', 'cili'):
        DC = [np.asarray(x, dtype=float) for x in (res.det_coef_coint, res.stderr_det_coef_coint, res.tvalues_det_coef_coint, res.pvalues_det_coef_coint)]
        det_names = (['Constant'] if 'ci' in det else []) + (['Time Trend'] if 'li' in det else [])
        for j in range(r):
            for i, nm in enumerate(det_names):
                beta_rows.append({'relation': ec[j], 'variable': nm, **cells(*DC, i, j)})
    G = [np.asarray(x, dtype=float) for x in (res.gamma, res.stderr_gamma, res.tvalues_gamma, res.pvalues_gamma)]
    gamma = []
    for i in range(P.k):
        rows_g = []
        for lag in range(kd):
            for jv in range(P.k):
                col = lag * P.k + jv
                rows_g.append({'term': f'Δ{names[jv]}(t−{lag + 1})', 'lag': lag + 1, **cells(*G, i, col)})
        gamma.append({'equation': names[i], 'rows': rows_g})
    det_rows = []
    dnames = (['Intercept'] if 'co' in det else []) + (['Time Trend'] if 'lo' in det else []) + list(P.exog)
    if dnames:
        D = [np.asarray(x, dtype=float) for x in (res.det_coef, res.stderr_det_coef, res.tvalues_det_coef, res.pvalues_det_coef)]
        for i in range(P.k):
            for j, nm in enumerate(dnames):
                if j < D[0].shape[1]:
                    det_rows.append({'equation': names[i], 'term': nm, **cells(*D, i, j)})
    h = max(1, min(1000, int(h or 12)))
    Xf, notes = P.exog_future(h)
    with _quiet():
        fc, lo, hi = (np.asarray(v, dtype=float) for v in res.predict(steps=h, alpha=alpha, exog_fc=Xf))
    if P.log:
        fc, lo, hi = np.exp(fc), np.exp(lo), np.exp(hi)
        notes.append('exp() undoes the logarithm: the forecasts are medians and the intervals are not symmetric.')
    t_fc = P.future(h)
    c = _code_data(P, table_name, where, levels=True, imports=['from statsmodels.tsa.vector_ar.vecm import VECM'])
    if P.exog:
        c.append('X_future = np.array(' + json.dumps([[_f(v) for v in row] for row in Xf]) + ')')
    c += [f'res = VECM(Y{", exog=X" if P.exog else ""}, k_ar_diff={kd}, coint_rank={r}, deterministic={det!r}).fit()',
          'print(res.summary())   # alpha (loadings), beta (cointegrating vectors, first rows the identity), Gamma',
          f'fc, lower, upper = res.predict(steps={h}, alpha={alpha!r}{", exog_fc=X_future" if P.exog else ""})']
    if P.log:
        c.append('fc, lower, upper = np.exp(fc), np.exp(lower), np.exp(upper)   # in the units of the table')
    first = next(i for i, ln in enumerate(c) if ln.startswith('X_future = ') or ln.startswith('res = VECM('))
    g = [*_code_data(P, table_name, where, levels=True, imports=['from statsmodels.tsa.vector_ar.vecm import VECM'], graph=True),
         *(ln for ln in c[first:] if not ln.startswith('print('))]   # the fit and the forecasts, as above
    g += ['f_mean, f_lower, f_upper = fc, lower, upper', 'obs, t_o = raw, ' + _tx(P, 'raw') + '   # the table\'s values', f'names = {J(names)}',
          _future(P, h, 't_o[-1]'), *_forecast_plot(P, 'VECM forecasts', 'obs', None)]
    return {'names': names, 'rank': r, 'k_ar_diff': kd, 'deterministic': det, 'det_label': DETERMINISTIC[det], 'nobs': int(res.nobs),
            'plot_code': {'forecast': g},
            'llf': _f(res.llf), 'alpha': alpha_rows, 'beta': beta_rows, 'beta_matrix': _mat(B[0]), 'alpha_matrix': _mat(A[0]),
            'gamma': gamma, 'det': det_rows, 'sigma_u': _mat(res.sigma_u),
            'forecast': {'t': t_fc, 'mean': _mat(fc.T), 'lower': _mat(lo.T), 'upper': _mat(hi.T), 'level': 1 - alpha},
            'observed': {'t': _arr(P.t0), 'rows': P.rows0, 'values': [_arr(P.raw[:, i]) for i in range(P.k)]},
            'log': P.log, 'notes': notes, 'code': '\n'.join(c)}


@api('multits.engle_granger')
@_common
def engle_granger(table, y, time=None, rows=None, excluded=None, exog=None, log=False, diff=False, trend='c',
                  where=None, table_name='data'):
    """The Engle-Granger test (statsmodels.tsa.stattools.coint): each series
    regressed on the others by least squares, then an ADF test of the
    residuals with MacKinnon's p-values for that many series."""
    from statsmodels.tsa.stattools import coint
    P = prepare(table, y, time, rows, excluded, exog, log, diff)
    tr = trend if trend in ('c', 'ct', 'n') else 'c'
    rows_ = []
    for j, c in enumerate(P.names):
        others = [i for i in range(P.k) if i != j]
        t, pv, crit = coint(P.L[:, j], P.L[:, others], trend=tr, autolag='aic')
        rows_.append({'dependent': c, 'regressors': ', '.join(P.names[i] for i in others), 'stat': _f(t), 'p': _f(pv),
                      'c1': _f(crit[0]), 'c5': _f(crit[1]), 'c10': _f(crit[2])})
    c = _code_data(P, table_name, where, levels=True, imports=['from statsmodels.tsa.stattools import coint'])
    c += ['for c in Y:   # each series on the others; H0: no cointegration',
          f'    print(c, coint(Y[c], Y.drop(columns=c), trend={tr!r}, autolag="aic"))   # t, p-value, 1/5/10% critical values']
    return {'names': P.names, 'trend': tr, 'rows': rows_, 'nobs': int(len(P.L)), 'log': P.log, 'code': '\n'.join(c)}
