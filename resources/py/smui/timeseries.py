"""Time Series (Analyze > Specialized Modeling > Time Series): the backend.

JMP's Time Series platform on statsmodels.tsa:

  the series       one column in time order. Excluded rows count as missing
                   values, as in JMP, so that the spacing of the series is
                   kept; a date Time ID gives the calendar frequency
                   (pandas.infer_freq, and gaps are allowed), the seasonal
                   period and the dates of the forecasts
  diagnostics      acf with Bartlett's standard errors, the partial
                   autocorrelations by Levinson-Durbin, acorr_ljungbox, the
                   variogram and the AR coefficients from the
                   autocorrelations, adfuller ('n', 'c', 'ct'), kpss
  transforms       differencing (statespace.tools.diff), a linear trend or a
                   cosine cycle removed by OLS, seasonal_decompose, STL
  spectral density the periodogram and its smoothed version, Fisher's kappa
                   and Bartlett's Kolmogorov-Smirnov
  models           ARIMA and seasonal ARIMA by exact maximum likelihood
                   (tsa.arima.model.ARIMA), transfer functions as regression
                   with ARIMA errors, the smoothing models of tsa.holtwinters,
                   and state space smoothing (ETSModel)

Every model result is aligned to the slots of the series (the rows in time
order, with missing time points inserted), so the page can draw, compare and
save the models side by side.
"""
import functools
import json
import math
import warnings
from contextlib import contextmanager
from decimal import Decimal, localcontext

import numpy as np
import pandas as pd
from scipy import stats

from . import data
from .registry import api
from .util import code_head

DATE_KINDS = ('date', 'datetime')
SEED = 20260926          # simulated prediction intervals: the same numbers every time


class NoSeries(ValueError):
    pass


@contextmanager
def _quiet():
    """Drop numpy's and pandas' deprecation notices raised inside statsmodels:
    they say nothing about the fit. Every other warning (a fit that did not
    converge, non-stationary starting values) still reaches the report."""
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=DeprecationWarning)
        warnings.filterwarnings('ignore', category=FutureWarning)
        yield


def _quietly(fn):
    """An API function run inside _quiet()."""
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        with _quiet():
            return fn(*args, **kwargs)
    return inner


def _f(x):
    """A float for JSON, or None."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _arr(a):
    return [_f(v) for v in np.asarray(a, dtype=float).ravel()]


# ---- the series ------------------------------------------------------------

class Series:
    """One column in time order over its span (first to last non-missing value).

    y      values, NaN where missing (missing, excluded, or an inserted time point)
    t      the time axis: epoch milliseconds (dates), the Time ID's values, or
           row numbers from 1
    rows   the table row of each slot (None for an inserted time point)
    kind   'date', 'datetime', 'numeric' or 'index'
    offset a pandas DateOffset when the dates follow a calendar frequency
    X, Xf  the input columns over the span, and in the rows after it
    """

    def __init__(self):
        self.notes = []
        self.offset = None
        self.freq = None
        self.freq_label = None
        self.period = None
        self.step = 1.0
        self.irregular = False
        self.inserted = 0
        self.X = {}
        self.Xf = {}
        self.excluded_pos = []

    @property
    def n(self):
        return len(self.y)

    def future(self, h):
        """The time points of h periods after the series."""
        h = int(h or 0)
        if h <= 0 or not len(self.t):
            return []
        if self.kind in DATE_KINDS and self.offset is not None:
            last = pd.Timestamp(int(self.t[-1]), unit='ms')
            fut = pd.date_range(last, periods=h + 1, freq=self.offset)[1:]
            return [float(v) for v in _ms(fut)]
        return [float(self.t[-1] + self.step * (k + 1)) for k in range(h)]


def _ms(idx):
    """Epoch milliseconds of a DatetimeIndex, whatever its unit."""
    return np.asarray((pd.DatetimeIndex(idx) - pd.Timestamp(0)) // pd.Timedelta(milliseconds=1), dtype=np.int64)


def _dates(ms):
    return pd.DatetimeIndex(pd.Timestamp(0) + pd.to_timedelta(np.asarray(ms, dtype=np.int64), unit='ms'))


FREQ_LABELS = [('Year', 'yearly', 1, 'years'), ('Quarter', 'quarterly', 4, 'quarters'), ('SemiMonth', 'semi-monthly', 24, 'half months'),
               ('Month', 'monthly', 12, 'months'), ('Week', 'weekly', 52, 'weeks'), ('BusinessDay', 'business daily', 5, 'business days'),
               ('Day', 'daily', 7, 'days'), ('Hour', 'hourly', 24, 'hours'), ('Minute', 'by minute', 60, 'minutes'),
               ('Second', 'by second', 60, 'seconds')]


def _period_of(off):
    """The seasonal period that goes with a calendar frequency (12 for monthly
    data, 4 for quarterly ...), and a word for the frequency."""
    name = type(off).__name__
    for key, label, per, unit in FREQ_LABELS:
        if key in name:
            n = abs(int(getattr(off, 'n', 1) or 1))
            if n == 1:
                return per, label
            return (per // n if per % n == 0 and per // n > 1 else None), f'every {n} {unit}'
    return None, None


def _grid_size(off, first, last):
    """About how many points a calendar grid has between two dates."""
    name = type(off).__name__
    months = (last.year - first.year) * 12 + (last.month - first.month)
    n = abs(int(getattr(off, 'n', 1) or 1))
    if 'Year' in name:
        return months / 12 / n + 1
    if 'Quarter' in name:
        return months / 3 / n + 1
    if 'Month' in name:
        return months / n + 1
    if 'Week' in name:
        return (last - first).days / 7 / n + 1
    try:
        return (last - first) / pd.Timedelta(off) + 1
    except (TypeError, ValueError):
        return float('inf')


def _date_offset(dates):
    """The calendar frequency of increasing dates: pandas.infer_freq first,
    then the coarsest frequency whose grid holds every date (so that a series
    with a few time points missing still has its frequency)."""
    if len(dates) < 2 or not dates.is_unique or not dates.is_monotonic_increasing:
        return None
    if len(dates) >= 3:
        try:
            f = pd.infer_freq(dates)
        except (TypeError, ValueError):
            f = None
        if f:
            try:
                return pd.tseries.frequencies.to_offset(f)
            except ValueError:
                pass
    d0 = dates[0]
    O = pd.offsets
    cands = [O.YearBegin(month=d0.month), O.YearEnd(month=d0.month),
             O.QuarterBegin(startingMonth=(d0.month - 1) % 3 + 1), O.QuarterEnd(startingMonth=(d0.month - 1) % 3 + 1),
             O.MonthBegin(), O.MonthEnd(), O.Week(weekday=d0.weekday()), O.Day(), O.Hour(), O.Minute(), O.Second()]
    for off in cands:
        try:
            if _grid_size(off, dates[0], dates[-1]) > 3 * len(dates) + 10:
                continue
            if not all(off.is_on_offset(d) for d in dates):
                continue
            grid = pd.date_range(dates[0], dates[-1], freq=off)
        except Exception:
            continue
        if len(grid) and dates.isin(grid).all():
            return off
    return None


def load(table, y, time=None, rows=None, excluded=None, inputs=None):
    """The series of column y (and the input columns) for the given rows."""
    if time == y:
        time = None
    inputs = [c for c in dict.fromkeys(inputs or []) if c and c not in (y, time)]
    names = [y] + ([time] if time else []) + inputs
    df = data.frame(table, names, rows, dropna=False, as_category=False)
    S = Series()
    S.y_name, S.time_name, S.inputs = y, time, inputs
    if excluded:
        ex = df.index.isin([int(r) for r in excluded])
        if ex.any():
            df.loc[ex, y] = np.nan
    S.kind = 'index'
    if time:
        fmt = (data.meta(table, time) or {}).get('format') or {}
        S.kind = fmt.get('kind') if fmt.get('kind') in DATE_KINDS else 'numeric'
        tv = df[time].to_numpy(dtype=float)
        bad = ~np.isfinite(tv)
        if bad.any():
            S.notes.append(f'{int(bad.sum())} row{"s" if bad.sum() > 1 else ""} with no {time} left out.')
            df = df[~bad]
        if not df[time].is_monotonic_increasing:
            df = df.sort_values(time, kind='mergesort')
            S.notes.append(f'The rows are taken in the order of {time}, not the order of the table.')
        if df[time].duplicated().any():
            S.notes.append(f'{int(df[time].duplicated().sum())} rows repeat a {time} value: the series is taken in row order and treated as equally spaced.')
    yv = df[y].to_numpy(dtype=float)
    ok = np.isfinite(yv)
    if not ok.any():
        raise NoSeries(f'{y} has no values in these rows')
    i0 = int(np.argmax(ok))
    i1 = len(ok) - 1 - int(np.argmax(ok[::-1]))
    span, after = df.iloc[i0:i1 + 1], df.iloc[i1 + 1:]
    rows_ = [int(r) for r in span.index]
    yv = span[y].to_numpy(dtype=float)
    X = {c: span[c].to_numpy(dtype=float) for c in inputs}
    S.Xf = {c: after[c].to_numpy(dtype=float) for c in inputs}
    ex_set = set(int(r) for r in (excluded or []))
    if S.kind == 'index':
        t = np.array(rows_, dtype=float) + 1
    elif S.kind in DATE_KINDS:
        ms = span[time].to_numpy(dtype=float).astype(np.int64)
        dates = _dates(ms)
        off = _date_offset(dates) if dates.is_unique else None
        if off is not None:
            grid = pd.date_range(dates[0], dates[-1], freq=off)
            if len(grid) > len(dates):
                pos = grid.get_indexer(dates)
                y2 = np.full(len(grid), np.nan)
                y2[pos] = yv
                r2 = [None] * len(grid)
                for k, p in enumerate(pos):
                    r2[p] = rows_[k]
                X2 = {}
                for c, v in X.items():
                    X2[c] = np.full(len(grid), np.nan)
                    X2[c][pos] = v
                S.inserted = len(grid) - len(dates)
                S.notes.append(f'{S.inserted} time point{"s" if S.inserted > 1 else ""} between the first and the last date '
                               f'{"have" if S.inserted > 1 else "has"} no row in the table and count{"" if S.inserted > 1 else "s"} as missing.')
                yv, rows_, X, ms = y2, r2, X2, _ms(grid)
            S.offset = off
            S.freq = off.freqstr
            S.period, S.freq_label = _period_of(off)
        else:
            S.irregular = True
            d = np.diff(ms)
            S.step = float(np.median(d)) if len(d) else 86400000.0
            S.notes.append('The dates follow no calendar frequency: the models treat the observations as equally spaced '
                           'and the forecasts continue the median spacing.')
        t = ms.astype(float)
    else:
        tv = span[time].to_numpy(dtype=float)
        d = np.diff(tv)
        step = float(np.median(d)) if len(d) else 1.0
        if step > 0:
            k = d / step
            if np.allclose(k, np.round(k), atol=1e-6) and (np.round(k) >= 1).all() and (np.round(k) > 1).any() and np.round(k).sum() <= 3 * len(tv) + 10:
                idx = np.concatenate([[0], np.cumsum(np.round(k).astype(int))])
                m = int(idx[-1]) + 1
                y2 = np.full(m, np.nan)
                y2[idx] = yv
                r2 = [None] * m
                for j, p in enumerate(idx):
                    r2[p] = rows_[j]
                X2 = {c: np.full(m, np.nan) for c in X}
                for c in X:
                    X2[c][idx] = X[c]
                S.inserted = m - len(tv)
                S.notes.append(f'{S.inserted} time point{"s" if S.inserted > 1 else ""} missing from the steps of {time} count as missing.')
                yv, rows_, X = y2, r2, X2
                tv = tv[0] + step * np.arange(m)
            elif not np.allclose(k, 1, atol=1e-6):
                S.irregular = True
                S.notes.append(f'{time} is not equally spaced: the models treat the observations as equally spaced.')
        else:
            step = 1.0
        S.step = step
        t = tv
    S.y, S.t, S.rows, S.X = yv, np.asarray(t, dtype=float), rows_, X
    S.excluded_pos = [k for k, r in enumerate(rows_) if r is not None and r in ex_set]
    if S.excluded_pos:
        S.notes.append(f'{len(S.excluded_pos)} excluded row{"s" if len(S.excluded_pos) > 1 else ""} count as missing values, '
                       'as in JMP, so that the spacing of the series is kept.')
    return S


def _filled(S):
    """The series with its missing values filled by linear interpolation, for
    the fits that take no missing values; and the mask of the filled ones."""
    miss = ~np.isfinite(S.y)
    if not miss.any():
        return S.y.copy(), miss
    x = pd.Series(S.y).interpolate(method='linear', limit_direction='both').to_numpy(dtype=float)
    return x, miss


# ---- code shown under the results -------------------------------------------

def _code_series(S, table_name, where=None, imports=()):
    """Python that builds, from a CSV export of the table, d (the table in
    time order, indexed by the Time ID) and y (the series over its span)."""
    Y = json.dumps(S.y_name)
    lines = [code_head(table_name, list(imports))]
    for w in where or []:
        lines.append(f'df = df[df[{json.dumps(w.get("column"))}] == {w.get("value")!r}]   # the By group')
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
    lines.append(f'y = d[{Y}]')
    lines.append('y = y.loc[y.first_valid_index():y.last_valid_index()]')
    if S.excluded_pos:
        lines.append(f'y.iloc[{S.excluded_pos}] = np.nan   # rows excluded in the table count as missing')
    return lines


# ---- the diagnostics ---------------------------------------------------------

def diagnostics(x, nlags=25, model_df=0):
    """Autocorrelations (lag 0 to K) with Bartlett's large-lag standard errors
    and Ljung-Box Q, partial autocorrelations (Levinson-Durbin on the
    autocorrelations, standard error 1/sqrt(n)), the variogram
    (1 - r_k)/(1 - r_1) and the coefficients of the AR(K) fit by Yule-Walker.
    Missing values inside the series are left out pairwise (acf's
    missing='conservative')."""
    from statsmodels.stats.diagnostic import acorr_ljungbox
    from statsmodels.tsa.stattools import acf, levinson_durbin
    x = np.asarray(x, dtype=float)
    ok = np.isfinite(x)
    if ok.any():
        i0 = int(np.argmax(ok))
        i1 = len(ok) - 1 - int(np.argmax(ok[::-1]))
        x, ok = x[i0:i1 + 1], ok[i0:i1 + 1]
    n = int(ok.sum())
    out = {'n': n, 'n_missing': int((~ok).sum()), 'mean': _f(np.nanmean(x)) if n else None,
           'sd': _f(np.nanstd(x, ddof=1)) if n > 1 else None}
    if n < 4 or not np.nanstd(x) > 0:
        out['error'] = 'too few values, or no variation, for autocorrelations'
        return out
    K = int(min(max(1, int(nlags or 25)), n - 1))
    missing = bool((~ok).any())
    with _quiet():
        r = acf(x, nlags=K, fft=False, missing='conservative' if missing else 'none')
    r = np.asarray(r, dtype=float)
    se = np.sqrt(np.r_[0.0, 1.0 / n, (1 + 2 * np.cumsum(r[1:-1] ** 2)) / n])[:K + 1]
    lags = np.arange(1, K + 1)
    if not missing:
        with _quiet():
            lb = acorr_ljungbox(x, lags=K, model_df=int(model_df), return_df=True)
        q, p = lb['lb_stat'].to_numpy(dtype=float), lb['lb_pvalue'].to_numpy(dtype=float)
    else:
        q = n * (n + 2) * np.cumsum(r[1:] ** 2 / (n - lags))
        dfq = lags - int(model_df)
        p = np.where(dfq > 0, stats.chi2.sf(q, np.maximum(dfq, 1)), np.nan)
    with _quiet():
        _, arc, pac, _, _ = levinson_durbin(r, nlags=K, isacov=True)
    vario = (1 - r[1:]) / (1 - r[1]) if abs(1 - r[1]) > 1e-12 else np.full(K, np.nan)
    out.update({
        'K': K, 'missing': missing,
        'acf': {'lag': list(range(K + 1)), 'r': _arr(r), 'se': _arr(se), 'q': [None] + _arr(q), 'p': [None] + _arr(p)},
        'pacf': {'lag': list(range(K + 1)), 'r': _arr(pac), 'se': [0.0] + [1 / math.sqrt(n)] * K},
        'variogram': {'lag': list(range(1, K + 1)), 'v': _arr(vario)},
        'ar': {'lag': list(range(1, K + 1)), 'coef': _arr(arc)},
        'model_df': int(model_df),
    })
    return out


def stationarity(x):
    """Augmented Dickey-Fuller tests against a random walk with zero mean, a
    non-zero mean and a linear trend (regression 'n', 'c', 'ct'; lags by AIC)
    and the KPSS tests of level and trend stationarity."""
    from statsmodels.tools.sm_exceptions import InterpolationWarning
    from statsmodels.tsa.stattools import adfuller, kpss
    v = np.asarray(x, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < 12 or not np.std(v) > 0:
        return {'error': 'the stationarity tests need at least 12 values that vary'}
    adf = []
    for label, reg in (('Zero Mean ADF', 'n'), ('Single Mean ADF', 'c'), ('Trend ADF', 'ct')):
        try:
            with _quiet():
                st, p, lag, nobs, crit, _ = adfuller(v, regression=reg, autolag='AIC')
            adf.append({'test': label, 'regression': reg, 'stat': _f(st), 'p': _f(p), 'lags': int(lag), 'nobs': int(nobs),
                        'c1': _f(crit['1%']), 'c5': _f(crit['5%']), 'c10': _f(crit['10%'])})
        except Exception as e:  # too short for the lags, a constant series
            adf.append({'test': label, 'regression': reg, 'error': str(e)})
    kp = []
    for label, reg in (('KPSS Level', 'c'), ('KPSS Trend', 'ct')):
        try:
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter('always')
                st, p, lags, crit = kpss(v, regression=reg, nlags='auto')
            bound = None
            for m in w:
                if issubclass(m.category, InterpolationWarning):
                    bound = '>' if 'greater' in str(m.message) else '<'
                elif not issubclass(m.category, (DeprecationWarning, FutureWarning)):
                    warnings.warn(str(m.message), m.category)
            kp.append({'test': label, 'regression': reg, 'stat': _f(st), 'p': _f(p), 'p_bound': bound, 'lags': int(lags),
                       'c1': _f(crit['1%']), 'c5': _f(crit['5%']), 'c10': _f(crit['10%'])})
        except Exception as e:
            kp.append({'test': label, 'regression': reg, 'error': str(e)})
    return {'adf': adf, 'kpss': kp, 'n': int(len(v))}


def _slots(S, values, start=0):
    """Values for the slots of the series from `start` on, None before."""
    out = [None] * S.n
    for k, v in enumerate(values):
        if start + k < S.n:
            out[start + k] = _f(v)
    return out


@api('timeseries.series')
@_quietly
def series(table, y, time=None, rows=None, excluded=None, nlags=25, where=None, table_name='data'):
    """The series, its summary (mean, SD, N, the ADF tests), its basic
    diagnostics and the stationarity tests."""
    try:
        S = load(table, y, time, rows, excluded)
    except NoSeries as e:
        return {'error': str(e)}
    out = {'y': y, 'time': S.time_name, 'kind': S.kind, 'n': S.n, 't': _arr(S.t), 'values': _arr(S.y), 'rows': S.rows,
           'freq': S.freq, 'freq_label': S.freq_label, 'period_auto': S.period, 'irregular': S.irregular,
           'step': S.step, 'inserted': S.inserted, 'excluded_pos': S.excluded_pos, 'notes': S.notes}
    out['diag'] = diagnostics(S.y, nlags)
    out['stationarity'] = stationarity(S.y)
    c = _code_series(S, table_name, where, ['from statsmodels.tsa.stattools import acf, pacf, adfuller, kpss',
                                              'from statsmodels.stats.diagnostic import acorr_ljungbox'])
    K = out['diag'].get('K', nlags)
    miss = ', missing="conservative"' if out['diag'].get('missing') else ''
    c += [f'print(y.mean(), y.std(), y.count())   # Mean, SD, N',
          f'print(acf(y, nlags={K}, fft=False{miss}))   # AutoCorr; ±2 standard errors: 2*sqrt((1 + 2*cumsum(r**2))/N)',
          f'print(pacf(y.dropna(), nlags={K}, method="ldb"))   # Partial (Levinson-Durbin on the autocorrelations)',
          f'print(acorr_ljungbox(y.dropna(), lags={K}))   # Ljung-Box Q and p-Value',
          'for reg in ("n", "c", "ct"):   # Zero Mean, Single Mean and Trend ADF',
          '    print(reg, adfuller(y.dropna(), regression=reg, autolag="AIC")[:4])',
          'print(kpss(y.dropna(), regression="c", nlags="auto"), kpss(y.dropna(), regression="ct", nlags="auto"))']
    out['code'] = '\n'.join(c)
    return out


@api('timeseries.input')
@_quietly
def input_series(table, y, time=None, rows=None, nlags=25, table_name='data'):
    """An input series (Input List), for the Input Time Series Panel."""
    try:
        S = load(table, y, time, rows)
    except NoSeries as e:
        return {'error': str(e)}
    return {'y': y, 'kind': S.kind, 't': _arr(S.t), 'values': _arr(S.y), 'rows': S.rows, 'diag': diagnostics(S.y, nlags),
            'stationarity': stationarity(S.y)}


# ---- differencing and decomposition -------------------------------------------

def _derived(S, name, values, nlags, extra=None):
    """A series derived from S (differenced, detrended ...), with its diagnostics."""
    v = np.asarray(values, dtype=float)
    out = {'name': name, 'values': _slots(S, v, S.n - len(v)), 'start': S.n - len(v),
           'diag': diagnostics(v, nlags), 'stationarity': stationarity(v)}
    if extra:
        out.update(extra)
    return out


@api('timeseries.difference')
@_quietly
def difference(table, y, time=None, rows=None, excluded=None, d=1, D=0, s=12, nlags=25, where=None, table_name='data'):
    """w_t = (1 - B)^d (1 - B^s)^D y_t."""
    from statsmodels.tsa.statespace.tools import diff
    S = load(table, y, time, rows, excluded)
    d, D, s = int(d or 0), int(D or 0), int(s or 0)
    if D and s < 2:
        return {'error': 'seasonal differencing needs at least 2 observations per period'}
    if d + D * s >= S.n - 3:
        return {'error': 'the series is too short for this differencing'}
    w = np.asarray(diff(S.y, k_diff=d, k_seasonal_diff=D, seasonal_periods=s if D else 1), dtype=float)
    out = _derived(S, f'Difference of {y}', w, nlags, {'d': d, 'D': D, 's': s})
    c = _code_series(S, table_name, where, ['from statsmodels.tsa.statespace.tools import diff', 'from statsmodels.tsa.stattools import acf, pacf'])
    c += [f'w = diff(y, k_diff={d}, k_seasonal_diff={D}, seasonal_periods={s if D else 1})   # (1 - B)^{d} (1 - B^{s})^{D} y',
          f'print(w.describe()); print(acf(w, nlags={out["diag"].get("K", nlags)}, fft=False, missing="conservative"))']
    out['code'] = '\n'.join(c)
    return out


@api('timeseries.detrend')
@_quietly
def detrend(table, y, time=None, rows=None, excluded=None, nlags=25, where=None, table_name='data'):
    """Remove Linear Trend: y_t = b0 + b1 t + e_t by least squares, t = 1..N."""
    import statsmodels.api as sm
    S = load(table, y, time, rows, excluded)
    t = np.arange(1, S.n + 1, dtype=float)
    with _quiet():
        res = sm.OLS(S.y, sm.add_constant(t), missing='drop').fit()
    trend = res.params[0] + res.params[1] * t
    dfree = res.df_resid
    params = [{'term': 'Intercept (β0)', 'estimate': _f(res.params[0]), 'se': _f(res.bse[0]), 't': _f(res.tvalues[0]), 'p': _f(res.pvalues[0])},
              {'term': 'Time (β1)', 'estimate': _f(res.params[1]), 'se': _f(res.bse[1]), 't': _f(res.tvalues[1]), 'p': _f(res.pvalues[1])}]
    out = _derived(S, f'Detrended {y}', S.y - trend, nlags, {'params': params, 'trend': _arr(trend), 'df': _f(dfree), 'rsquare': _f(res.rsquared)})
    c = _code_series(S, table_name, where)
    c += ['t = np.arange(1, len(y) + 1)', 'res = sm.OLS(y.to_numpy(), sm.add_constant(t), missing="drop").fit(); print(res.summary())',
          'detrended = y - (res.params[0] + res.params[1] * t)']
    out['code'] = '\n'.join(c)
    return out


@api('timeseries.decycle')
@_quietly
def decycle(table, y, time=None, rows=None, excluded=None, units=12, constant=True, nlags=25, where=None, table_name='data'):
    """Remove Cycle: y_t = C + A cos(2 pi t / U + P) + e_t, t = 0..N-1, by least
    squares on the cosine and sine terms."""
    import statsmodels.api as sm
    S = load(table, y, time, rows, excluded)
    U = float(units or 0)
    if not U > 1:
        return {'error': 'the number of units per cycle must be above 1'}
    t = np.arange(S.n, dtype=float)
    Xc = np.column_stack([np.cos(2 * np.pi * t / U), np.sin(2 * np.pi * t / U)])
    if constant:
        Xc = sm.add_constant(Xc, has_constant='add')
    with _quiet():
        res = sm.OLS(S.y, Xc, missing='drop').fit()
    b = res.params
    C = float(b[0]) if constant else 0.0
    a, bs = (float(b[1]), float(b[2])) if constant else (float(b[0]), float(b[1]))
    A = math.hypot(a, bs)
    P = math.atan2(-bs, a)
    cycle = C + A * np.cos(2 * np.pi * t / U + P)
    params = [{'term': 'Constant', 'estimate': C if constant else None}, {'term': 'Amplitude', 'estimate': A},
              {'term': 'Units per Cycle', 'estimate': U}, {'term': 'Phase', 'estimate': P}]
    out = _derived(S, f'Decycled {y}', S.y - cycle, nlags, {'params': params, 'cycle': _arr(cycle), 'units': U, 'constant': bool(constant)})
    c = _code_series(S, table_name, where)
    c += ['t = np.arange(len(y))', f'X = np.column_stack([np.cos(2*np.pi*t/{U!r}), np.sin(2*np.pi*t/{U!r})])',
          f'res = sm.OLS(y.to_numpy(), {"sm.add_constant(X)" if constant else "X"}, missing="drop").fit()',
          f'a, b = res.params[{1 if constant else 0}:]; A, P = np.hypot(a, b), np.arctan2(-b, a)   # amplitude, phase',
          f'cycle = {"res.params[0] + " if constant else ""}A * np.cos(2*np.pi*t/{U!r} + P); decycled = y - cycle']
    out['code'] = '\n'.join(c)
    return out


@api('timeseries.decompose')
@_quietly
def decompose(table, y, time=None, rows=None, excluded=None, method='classical', period=12, model='additive', robust=False,
              nlags=None, where=None, table_name='data'):
    """Seasonal decomposition: moving averages (seasonal_decompose) or STL."""
    from statsmodels.tsa.seasonal import STL, seasonal_decompose
    S = load(table, y, time, rows, excluded)
    s = int(period or 0)
    if s < 2:
        return {'error': 'the period must be at least 2'}
    if S.n < 2 * s + 1:
        return {'error': f'the series needs at least two full periods ({2 * s + 1} values)'}
    x, miss = _filled(S)
    mult = model == 'multiplicative'
    if mult and not (x > 0).all():
        return {'error': 'a multiplicative decomposition needs every value above zero'}
    with _quiet():
        if method == 'stl':
            res = STL(x, period=s, robust=bool(robust)).fit()
            mult = False
        else:
            res = seasonal_decompose(x, model='multiplicative' if mult else 'additive', period=s)
    trend, seas, resid = (np.asarray(v, dtype=float) for v in (res.trend, res.seasonal, res.resid))
    adj = x / seas if mult else x - seas
    for v in (adj, resid):
        v[miss] = np.nan
    out = {'method': method, 'period': s, 'model': 'multiplicative' if mult else 'additive', 'robust': bool(robust),
           'trend': _arr(trend), 'seasonal': _arr(seas), 'resid': _arr(resid), 'adjusted': _arr(adj), 'filled': int(miss.sum())}
    if miss.any():
        out['notes'] = [f'{int(miss.sum())} missing values were filled by linear interpolation for the decomposition.']
    c = _code_series(S, table_name, where, ['from statsmodels.tsa.seasonal import STL, seasonal_decompose'])
    if miss.any():
        c.append('y = y.interpolate(limit_direction="both")')
    if method == 'stl':
        c.append(f'res = STL(y, period={s}, robust={bool(robust)}).fit()')
    else:
        c.append(f'res = seasonal_decompose(y, model={("multiplicative" if mult else "additive")!r}, period={s})')
    c.append('print(res.trend, res.seasonal, res.resid)   # adjusted: ' + ('y / res.seasonal' if mult else 'y - res.seasonal'))
    out['code'] = '\n'.join(c)
    return out


# ---- spectral density ----------------------------------------------------------

def fisher_kappa_p(kappa, q):
    """Pr(K > kappa) for Fisher's kappa over q frequencies:
    1 - sum_j (-1)^j C(q, j) max(1 - j kappa/q, 0)^(q-1), in exact decimal
    arithmetic (the terms cancel); beyond q = 3000 the Gumbel limit
    1 - (1 - exp(-kappa))^q."""
    q = int(q)
    if q < 2 or kappa is None or not math.isfinite(kappa):
        return None
    x = kappa / q
    if x >= 1:
        return 0.0
    if q > 3000:
        return float(-np.expm1(q * np.log1p(-math.exp(-kappa))))
    with localcontext() as c:
        c.prec = int(q * 0.30103) + 40
        X = Decimal(x)
        total = Decimal(0)
        for j in range(1, q + 1):
            base = 1 - j * X
            if base <= 0:
                break
            term = Decimal(math.comb(q, j)) * base ** (q - 1)
            total = total + term if j % 2 else total - term
        p = float(total)
    return min(1.0, max(0.0, p))


@api('timeseries.spectral')
@_quietly
def spectral(table, y, time=None, rows=None, excluded=None, nlags=None, where=None, table_name='data'):
    """The periodogram I(f_i) = (N/2)(a_i^2 + b_i^2) at f_i = i/N, with a_i and
    b_i the least squares Fourier coefficients (t = 1..N); the spectral
    density, the periodogram smoothed and scaled by 1/(4 pi); the white noise
    tests."""
    S = load(table, y, time, rows, excluded)
    v = S.y[np.isfinite(S.y)]
    N = len(v)
    if N < 8:
        return {'error': 'the spectral density needs at least 8 values'}
    F = np.fft.fft(v)
    i = np.arange(N)
    C = np.exp(-2j * np.pi * i / N) * F          # sum over t = 1..N of v_t exp(-2 pi i f t)
    a = 2.0 / N * C.real
    b = -2.0 / N * C.imag
    I = N / 2.0 * (a ** 2 + b ** 2)
    q = N // 2 if N % 2 == 0 else (N - 1) // 2
    Iq = I[1:q + 1]
    # triangular smoothing weights over 2m + 1 frequencies, reflected at the ends
    m = max(1, int(round(math.sqrt(q) / 2)))
    w = np.array([m + 1 - abs(j) for j in range(-m, m + 1)], dtype=float)
    w /= w.sum()
    ext = np.concatenate([Iq[1:m + 1][::-1], Iq, Iq[-m - 1:-1][::-1]]) if q > m + 1 else Iq
    sm_ = np.convolve(ext, w, mode='valid') if q > m + 1 else Iq.copy()
    dens = sm_ / (4 * np.pi)
    total = float(Iq.sum())
    kappa = float(q * Iq.max() / total) if total > 0 else None
    U = np.cumsum(Iq) / total if total > 0 else np.zeros(q)
    D = float(np.max(np.abs(U - np.arange(1, q + 1) / q))) if total > 0 else None
    freq = i[1:q + 1] / N
    out = {'N': N, 'q': q, 'm': m, 'frequency': _arr(freq), 'period': _arr(1 / freq), 'periodogram': _arr(Iq), 'density': _arr(dens),
           'sine': _arr(a[:q + 1]), 'cosine': _arr(b[:q + 1]), 'periodogram0': _f(I[0]),
           'kappa': _f(kappa), 'p_kappa': fisher_kappa_p(kappa, q) if kappa is not None else None,
           'bartlett': _f(D), 'p_bartlett': _f(stats.kstwobign.sf(D * math.sqrt(q))) if D is not None else None,
           'crit5': 1.36 / math.sqrt(q), 'crit1': 1.63 / math.sqrt(q),
           'dropped': int((~np.isfinite(S.y)).sum())}
    c = _code_series(S, table_name, where, ['from scipy import stats'])
    c += ['v = y.dropna().to_numpy(); N = len(v); i = np.arange(N)',
          'C = np.exp(-2j*np.pi*i/N) * np.fft.fft(v)   # sums over t = 1..N',
          'a, b = 2/N*C.real, -2/N*C.imag; I = N/2*(a**2 + b**2)   # Fourier coefficients and the periodogram at i/N',
          'q = N//2 if N % 2 == 0 else (N - 1)//2; Iq = I[1:q + 1]',
          'kappa = q*Iq.max()/Iq.sum()   # Fisher\'s kappa',
          'D = np.abs(np.cumsum(Iq)/Iq.sum() - np.arange(1, q + 1)/q).max()   # Bartlett\'s Kolmogorov-Smirnov',
          'print(kappa, D, stats.kstwobign.sf(D*np.sqrt(q)))']
    out['code'] = '\n'.join(c)
    return out


# ---- cross correlation -----------------------------------------------------------

def _ccf_pair(yv, xv, K):
    """corr(y_t+k, x_t) for k = -K..K (the input leads for k > 0), with
    statsmodels' ccf, or pairwise over the non-missing values."""
    from statsmodels.tsa.stattools import ccf
    ok = np.isfinite(yv) & np.isfinite(xv)
    if ok.all():
        with _quiet():
            pos = ccf(yv, xv, adjusted=False, fft=False)[:K + 1]
            neg = ccf(xv, yv, adjusted=False, fft=False)[:K + 1]
        return np.concatenate([neg[1:][::-1], pos])
    ym, xm = np.nanmean(yv), np.nanmean(xv)
    sy, sx = np.nanstd(yv), np.nanstd(xv)
    n = int(ok.sum())
    yc, xc = np.nan_to_num(yv - ym), np.nan_to_num(xv - xm)
    out = []
    for k in range(-K, K + 1):
        if k >= 0:
            s = np.sum(yc[k:] * xc[:len(xc) - k])
        else:
            s = np.sum(yc[:len(yc) + k] * xc[-k:])
        out.append(s / (n * sy * sx))
    return np.array(out)


@api('timeseries.ccf')
@_quietly
def cross_correlation(table, y, inputs=None, time=None, rows=None, excluded=None, nlags=25, where=None, table_name='data'):
    """Cross Correlation of the series with each input, lags -K..K; standard
    errors 1/sqrt(n - |k|)."""
    S = load(table, y, time, rows, excluded, inputs)
    n = int(np.isfinite(S.y).sum())
    K = int(min(max(1, int(nlags or 25)), n - 2))
    lags = list(range(-K, K + 1))
    res = []
    for c in S.inputs:
        xv = S.X[c]
        if not np.isfinite(xv).any() or not np.nanstd(xv) > 0:
            res.append({'input': c, 'error': f'{c} has no variation in these rows'})
            continue
        r = _ccf_pair(S.y, xv, K)
        res.append({'input': c, 'lag': lags, 'r': _arr(r), 'se': [1 / math.sqrt(max(1, n - abs(k))) for k in lags]})
    c = _code_series(S, table_name, None, ['from statsmodels.tsa.stattools import ccf'])
    for name in S.inputs:
        c.append(f'x = d.loc[y.index, {json.dumps(name)}]')
        c.append(f'print(ccf(y, x, adjusted=False, fft=False)[:{K + 1}])   # lags 0..{K}: corr(y[t+k], x[t]); ccf(x, y) for the negative lags')
    return {'lags': lags, 'n': n, 'inputs': res, 'code': '\n'.join(c)}


# ---- models: the common parts -----------------------------------------------------

def _fit_stats(y, fitted, valid, k, m2ll, ss_innov=None):
    """JMP's fit statistics from the one-step-ahead forecasts over the valid
    observations: n, DF = n - k, sums of squares, the variance estimate,
    AIC = -2LL + 2k, SBC = -2LL + k ln n, AICc, RSquare, RSquare Adj, MAPE, MAE."""
    y, fitted = np.asarray(y, dtype=float), np.asarray(fitted, dtype=float)
    e = (y - fitted)[valid]
    yy = y[valid]
    n = int(valid.sum())
    sse = float(np.sum(e ** 2))
    ssi = float(ss_innov) if ss_innov is not None else sse
    dfree = n - k
    sst = float(np.sum((yy - yy.mean()) ** 2)) if n else float('nan')
    r2 = 1 - sse / sst if sst > 0 else float('nan')
    aic = m2ll + 2 * k
    out = {'n': n, 'k': k, 'df': dfree, 'sse': sse, 'ssi': ssi, 'variance': ssi / dfree if dfree > 0 else float('nan'),
           'm2ll': m2ll, 'aic': aic, 'sbc': m2ll + k * math.log(n) if n > 0 else float('nan'),
           'aicc': aic + 2 * k * (k + 1) / (n - k - 1) if n - k - 1 > 0 else float('nan'),
           'rsquare': r2, 'rsquare_adj': 1 - (n - 1) / dfree * (1 - r2) if dfree > 0 else float('nan'),
           'mape': float(100 * np.mean(np.abs(e / yy))) if n and np.all(yy != 0) else float('nan'),
           'mae': float(np.mean(np.abs(e))) if n else float('nan')}
    out['sd'] = math.sqrt(out['variance']) if out['variance'] >= 0 else float('nan')
    return {k2: _f(v) if isinstance(v, float) else v for k2, v in out.items()}


def _pvals_t(est, se, dfree):
    est, se = np.asarray(est, dtype=float), np.asarray(se, dtype=float)
    with np.errstate(divide='ignore', invalid='ignore'):
        t = est / se
    p = 2 * stats.t.sf(np.abs(t), max(1, dfree))
    return t, p


def _model_out(S, kind, name, fitted, resid, fit_se, level, fc, st, summary, params, nlags, model_df, notes, code, **extra):
    """The result every model returns, aligned to the slots of the series."""
    z = stats.norm.ppf(0.5 + level / 2)
    fitted = np.asarray(fitted, dtype=float)
    fit_se = np.asarray(fit_se, dtype=float) if fit_se is not None else np.full(S.n, np.nan)
    resid = np.asarray(resid, dtype=float)
    out = {'kind': kind, 'name': name, 'level': level, 'n': S.n,
           'fitted': _arr(fitted), 'fit_se': _arr(fit_se), 'fit_lo': _arr(fitted - z * fit_se), 'fit_hi': _arr(fitted + z * fit_se),
           'resid': _arr(resid), 'forecast': fc, 'stats': st, 'summary': summary, 'params': params,
           'resid_diag': diagnostics(resid, nlags, model_df), 'notes': notes, 'code': code}
    out.update(extra)
    return out


def _forecast(S, h, mean, se, lo, hi):
    return {'t': S.future(h), 'mean': _arr(mean), 'se': _arr(se), 'lower': _arr(lo), 'upper': _arr(hi)}


# ---- ARIMA, seasonal ARIMA and transfer functions ----------------------------------------

def arima_name(p, d, q, P=0, D=0, Q=0, s=0, intercept=True, inputs=None):
    """JMP's names: AR(1), MA(2), ARMA(1, 1), I(1), IMA(1, 1), ARI(1, 1),
    ARIMA(p, d, q), Seasonal ARIMA(p, d, q)(P, D, Q)s."""
    if P or D or Q:
        base = f'Seasonal ARIMA({p}, {d}, {q})({P}, {D}, {Q}){s}'
    elif d == 0:
        base = f'AR({p})' if p and not q else f'MA({q})' if q and not p else f'ARMA({p}, {q})' if p and q else 'ARIMA(0, 0, 0)'
    else:
        base = f'I({d})' if not p and not q else f'ARI({p}, {d})' if p and not q else f'IMA({d}, {q})' if q and not p else f'ARIMA({p}, {d}, {q})'
    if inputs:
        base = f'Transfer Function {base} with {", ".join(_input_label(sp) for sp in inputs)}'
    if not intercept:
        base += ' No Intercept'
    return base


def _input_label(sp):
    lag, num = int(sp.get('lag') or 0), int(sp.get('num') or 0)
    if not lag and not num:
        return sp['name']
    lags = f'lag {lag}' if not num else f'lags {lag}–{lag + num}'
    return f'{sp["name"]} ({lags})'


def _exog(S, specs, h):
    """The regressors of a transfer function: each input at lags b..b+r, over
    the span and h periods after it. The future values are the rows after the
    series in the table (Y missing, the inputs present), as JMP takes them;
    beyond those the last value is held."""
    if not specs:
        return None, None, [], 0, []
    notes = []
    cols, fcols, names = [], [], []
    start = 0
    for sp in specs:
        c = sp['name']
        b, r = max(0, int(sp.get('lag') or 0)), max(0, int(sp.get('num') or 0))
        x = np.asarray(S.X[c], dtype=float)
        xf = np.asarray(S.Xf.get(c, []), dtype=float)
        xf = xf[:h]
        k_known = int(np.isfinite(xf).sum()) if len(xf) else 0
        if np.isfinite(xf).all():
            k_known = len(xf)
        else:
            bad = int(np.argmax(~np.isfinite(xf)))
            xf = xf[:bad]
            k_known = bad
        if len(xf) < h:
            last = xf[-1] if len(xf) else x[np.isfinite(x)][-1] if np.isfinite(x).any() else np.nan
            if h > len(xf):
                notes.append(f'{c}: {k_known} future value{"s" if k_known != 1 else ""} from the table, the last value ({last:.6g}) held for the remaining {h - len(xf)} period{"s" if h - len(xf) != 1 else ""}.')
            xf = np.concatenate([xf, np.full(h - len(xf), last)])
        elif h:
            notes.append(f'{c}: the {h} future values come from the rows after the series in the table.')
        full = np.concatenate([x, xf])
        for j in range(b, b + r + 1):
            sh = np.full(len(full), np.nan)
            sh[j:] = full[:len(full) - j] if j else full
            cols.append(sh[:S.n])
            fcols.append(sh[S.n:])
            names.append(c if j == 0 else f'{c}(t−{j})')
            start = max(start, j)
    E = np.column_stack(cols)
    Ef = np.column_stack(fcols) if h else np.zeros((0, len(cols)))
    bad = ~np.isfinite(E[start:]).all(axis=1)
    if bad.any():
        raise NoSeries(f'the inputs have {int(bad.sum())} missing values inside the series; a transfer function needs every input value')
    if start:
        notes.append(f'The first {start} observation{"s" if start > 1 else ""} are left out of the fit: the lagged inputs are not known there.')
    return E, Ef, names, start, notes


@api('timeseries.arima')
@_quietly
def arima(table, y, time=None, rows=None, excluded=None, p=0, d=0, q=0, P=0, D=0, Q=0, s=12, intercept=True, constrain=True,
          level=0.95, h=25, maxiter=200, inputs=None, nlags=25, where=None, table_name='data'):
    """ARIMA(p, d, q)(P, D, Q)s by exact maximum likelihood (the Kalman filter;
    missing values are skipped), with the intercept as the mean mu of the
    differenced series, JMP's parameterisation: statsmodels' ARIMA fits it as
    a trend t^(d+D) whose coefficient times (d+D)! s^D is mu. Inputs make it a
    transfer function: regression on the inputs with ARIMA errors."""
    from statsmodels.tsa.arima.model import ARIMA
    p, d, q, P, D, Q, s = (max(0, int(v or 0)) for v in (p, d, q, P, D, Q, s))
    seasonal = bool(P or D or Q) and s >= 2
    if not seasonal:
        P = D = Q = 0
        s = 0
    level = float(level or 0.95)
    h = max(0, int(h or 0))
    specs = [sp for sp in (inputs or []) if sp and sp.get('name')]
    try:
        S = load(table, y, time, rows, excluded, [sp['name'] for sp in specs])
        E, Ef, xnames, start, xnotes = _exog(S, specs, h)
    except NoSeries as e:
        return {'error': str(e)}
    notes = list(xnotes)
    yfit = S.y[start:]
    mdeg = d + D
    trend = ('c' if mdeg == 0 else [0] * mdeg + [1]) if intercept else 'n'
    mu_factor = math.factorial(mdeg) * (s ** D if seasonal else 1)
    k_est = p + q + P + Q + (1 if intercept else 0) + len(xnames)
    nobs = int(np.isfinite(yfit).sum())
    if nobs - (d + D * s) < k_est + 3:
        return {'error': f'too few observations ({nobs}) for {k_est} parameters after differencing'}
    endog = pd.Series(yfit, name=y)
    exog = pd.DataFrame(E[start:], columns=xnames) if E is not None else None
    model = ARIMA(endog, exog=exog, order=(p, d, q), seasonal_order=(P, D, Q, s), trend=trend,
                  enforce_stationarity=bool(constrain), enforce_invertibility=bool(constrain))
    its = []
    with _quiet():
        res = model.fit(method_kwargs={'maxiter': int(maxiter or 200), 'callback': lambda xk: its.append(np.array(xk, dtype=float))})
        history = []
        for k, xk in enumerate(its[:500]):
            try:
                history.append({'iter': k + 1, 'm2ll': _f(-2 * model.loglike(xk, transformed=False))})
            except Exception:
                break
    names = list(res.param_names)
    est = np.array(res.params, dtype=float)
    se = np.array(res.bse, dtype=float)
    sigma2 = float(est[names.index('sigma2')])
    burn = int(res.loglikelihood_burn)
    fitted = np.array(res.fittedvalues, dtype=float)
    resid = np.array(res.resid, dtype=float)
    zst = np.array(res.filter_results.standardized_forecasts_error[0], dtype=float)
    valid = np.isfinite(yfit) & (np.arange(len(yfit)) >= burn) & np.isfinite(fitted)
    k = len(est) - 1
    st = _fit_stats(yfit, fitted, valid, k, -2 * float(res.llf), ss_innov=sigma2 * float(np.nansum(zst[valid] ** 2)))
    dfree = st['df'] or 1
    # the parameter estimates, with JMP's names and the mean mu
    k_trend = int(getattr(res.model, 'k_trend', 0) or 0)
    rows_p = []
    mu = mu_se = None
    ar1, sar1 = 1.0, 1.0
    for j, nm in enumerate(names):
        if nm == 'sigma2':
            continue
        e, s_ = est[j], se[j]
        if j < k_trend:
            mu, mu_se = e * mu_factor, s_ * mu_factor
            term, factor, lag, e, s_ = 'Intercept', '', 0, mu, mu_se
        elif nm in xnames:
            term, factor, lag = nm, '', int(nm.split('−')[1].rstrip(')')) if '−' in nm else 0
        else:
            part, rest = nm.split('.', 1)
            if rest.startswith('S.L'):
                lag = int(rest[3:])
                term, factor = f'{part.upper()}2,{lag}', 2
                if part == 'ar':
                    sar1 -= e
            else:
                lag = int(rest[1:])
                term, factor = (f'{part.upper()}1,{lag}' if seasonal else f'{part.upper()}{lag}'), 1
                if part == 'ar':
                    ar1 -= e
        tt, pp = _pvals_t([e], [s_], dfree)
        rows_p.append({'term': term, 'factor': factor, 'lag': lag, 'estimate': _f(e), 'se': _f(s_), 't': _f(tt[0]), 'p': _f(pp[0]),
                       'sm': nm if j >= k_trend else f'{nm} × {mu_factor}' if mu_factor != 1 else nm})
    constant = {'estimate': _f(mu * ar1 * sar1), 'mu': _f(mu)} if mu is not None else None
    try:
        ar_roots = np.asarray(res.arroots)
        ma_roots = np.asarray(res.maroots)
    except Exception:
        ar_roots = ma_roots = np.array([])
    stable = bool(np.all(np.abs(ar_roots) > 1)) if ar_roots.size else True
    invertible = bool(np.all(np.abs(ma_roots) > 1)) if ma_roots.size else True
    # one-step-ahead prediction intervals in the sample, and the forecasts
    with _quiet():
        pr = res.get_prediction()
        fit_se = np.array(pr.se_mean, dtype=float)
        if h:
            fc = res.get_forecast(h, exog=pd.DataFrame(Ef, columns=xnames) if E is not None else None)
            ci = np.asarray(fc.conf_int(alpha=1 - level), dtype=float)
            fcd = _forecast(S, h, fc.predicted_mean, fc.se_mean, ci[:, 0], ci[:, 1])
        else:
            fcd = _forecast(S, 0, [], [], [], [])
    fitted[~valid] = np.nan
    resid = np.where(valid, resid, np.nan)
    fit_se[~valid] = np.nan
    pad = lambda v: np.concatenate([np.full(start, np.nan), v])   # noqa: E731
    conv = bool(res.mle_retvals.get('converged', True)) if isinstance(res.mle_retvals, dict) else True
    n_iter = int(res.mle_retvals.get('iterations', len(its))) if isinstance(res.mle_retvals, dict) else len(its)
    summary = [['DF', st['df'], 'int'], ['Sum of Squared Innovations', st['ssi']], ['Sum of Squared Residuals', st['sse']],
               ['Variance Estimate', st['variance']], ['Standard Deviation', st['sd']],
               ["Akaike's 'A' Information Criterion", st['aic']], ["Schwarz's Bayesian Criterion", st['sbc']], ['AICc', st['aicc']],
               ['RSquare', st['rsquare']], ['RSquare Adj', st['rsquare_adj']], ['MAPE', st['mape']], ['MAE', st['mae']],
               ['−2LogLikelihood', st['m2ll']], ['Stable', 'Yes' if stable else 'No', 'text'], ['Invertible', 'Yes' if invertible else 'No', 'text']]
    taken = f' after the {burn} observation{"s" if burn != 1 else ""} the differencing takes' if burn else ''
    notes.append(f'Exact maximum likelihood with the Kalman filter, as JMP fits ARIMA models. statsmodels counts σ² as a parameter: '
                 f'its AIC is {res.aic:.6g} and its BIC {res.bic:.6g}; the table follows JMP, k = {k} (the variance not counted), n = {st["n"]}{taken}.')
    notes.append('MA terms have statsmodels\' sign: θ(B) = 1 + θ₁B + …; JMP writes 1 − θ₁B − …, so its MA estimates have the opposite sign.')
    if not stable or not invertible:
        notes.append(f'The fitted model is {"not stable" if not stable else ""}{" and " if not stable and not invertible else ""}{"not invertible" if not invertible else ""}; try Constrain fit.')
    name = arima_name(p, d, q, P, D, Q, s, intercept, specs)
    c = _code_series(S, table_name, where, ['from statsmodels.tsa.arima.model import ARIMA'])
    if specs:
        c.append('# the inputs, lagged as in the model; X_future: their values for the forecast periods')
        cols_code = []
        for sp in specs:
            b0, r0 = int(sp.get('lag') or 0), int(sp.get('num') or 0)
            for j in range(b0, b0 + r0 + 1):
                label = sp['name'] if j == 0 else f'{sp["name"]}(t−{j})'
                cols_code.append(f'{json.dumps(label)}: d[{json.dumps(sp["name"])}].reindex(y.index).shift({j})')
        c.append('X = pd.DataFrame({' + ', '.join(cols_code) + '})')
        if start:
            c.append(f'y, X = y.iloc[{start}:], X.iloc[{start}:]')
        if h:
            c.append('X_future = pd.DataFrame({' + ', '.join(f'{json.dumps(nm)}: {[_f(v) for v in Ef[:, j]]}' for j, nm in enumerate(xnames)) + '})')
    trend_code = repr(trend)
    c.append(f'res = ARIMA(y{", exog=X" if specs else ""}, order=({p}, {d}, {q}), seasonal_order=({P}, {D}, {Q}, {s}), trend={trend_code}, '
             f'enforce_stationarity={bool(constrain)}, enforce_invertibility={bool(constrain)}).fit(method_kwargs={{"maxiter": {int(maxiter or 200)}}})')
    c.append('print(res.summary())')
    if intercept and mu_factor != 1:
        c.append(f'# JMP\'s Intercept (the mean of the differenced series) is the trend coefficient times {mu_factor}')
    if h:
        c.append(f'print(res.get_forecast({h}{", exog=X_future" if specs else ""}).summary_frame(alpha={1 - level:.6g}))')
    return _model_out(S, 'arima', name, pad(fitted), pad(resid), pad(fit_se), level, fcd, st, summary,
                      {'columns': 'arima', 'rows': rows_p}, nlags, p + q + P + Q, notes, '\n'.join(c),
                      constant=constant, iterations=history, converged=conv, n_iter=n_iter, stable=stable, invertible=invertible,
                      sm={'aic': _f(res.aic), 'bic': _f(res.bic), 'aicc': _f(res.aicc), 'llf': _f(res.llf), 'sigma2': _f(sigma2)},
                      spec={'p': p, 'd': d, 'q': q, 'P': P, 'D': D, 'Q': Q, 's': s, 'intercept': bool(intercept), 'constrain': bool(constrain)})


# ---- smoothing models (tsa.holtwinters) ----------------------------------------------------

SMOOTHERS = {
    'simple': ('Simple Exponential Smoothing', ['alpha']),
    'double': ('Double (Brown) Exponential Smoothing', ['alpha']),
    'linear': ('Linear (Holt) Exponential Smoothing', ['alpha', 'gamma']),
    'damped': ('Damped-Trend Linear Exponential Smoothing', ['alpha', 'gamma', 'phi']),
    'seasonal': ('Seasonal Exponential Smoothing', ['alpha', 'delta']),
    'winters': ('Winters Method (Additive)', ['alpha', 'gamma', 'delta']),
}
WEIGHT_NAMES = {'alpha': 'Level Smoothing Weight', 'gamma': 'Trend Smoothing Weight', 'phi': 'Damping Smoothing Weight',
                'delta': 'Seasonal Smoothing Weight'}


def smoothing_name(method, s=12, multiplicative=False):
    label = SMOOTHERS[method][0]
    if method == 'winters' and multiplicative:
        label = 'Winters Method (Multiplicative)'
    return f'{label}({s})' if method in ('seasonal', 'winters') else label


def _sm_values(method, th):
    """statsmodels' smoothing parameters from JMP's weights: Brown's alpha is
    Holt's with level alpha(2 - alpha) and trend alpha/(2 - alpha); the
    seasonal weight delta is statsmodels' smoothing_seasonal / (1 - alpha)."""
    a = th['alpha']
    if method == 'double':
        return {'smoothing_level': a * (2 - a), 'smoothing_trend': a / (2 - a)}
    v = {'smoothing_level': a}
    if 'gamma' in th:
        v['smoothing_trend'] = th['gamma']
    if 'phi' in th:
        v['damping_trend'] = th['phi']
    if 'delta' in th:
        v['smoothing_seasonal'] = th['delta'] * (1 - a)
    return v


def _hw_model(x, method, s, multiplicative, **init):
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    trend = 'add' if method in ('double', 'linear', 'damped', 'winters') else None
    seas = ('mul' if multiplicative else 'add') if method in ('seasonal', 'winters') else None
    kw = {'trend': trend, 'damped_trend': method == 'damped', 'seasonal': seas, 'seasonal_periods': s if seas else None}
    if method == 'damped' and not init:
        kw['bounds'] = {'damping_trend': (0.0, 1.0)}
    if init:
        return ExponentialSmoothing(x, initialization_method='known', **kw, **init)
    return ExponentialSmoothing(x, initialization_method='estimated', **kw)


def psi_variance(method, th, s, h):
    """1 + sum_{j<h} psi_j^2 for h = 1..H, from the moving-average forms of the
    smoothing models (JMP's statistical details), so that the h-step
    forecast variance is sigma^2 times it."""
    if h <= 0:
        return np.zeros(0)
    j = np.arange(1, h, dtype=float)
    a = th['alpha']
    if method == 'simple':
        psi = np.full(len(j), a)
    elif method == 'double':
        psi = 2 * a + (j - 1) * a * a
    elif method == 'linear':
        psi = a + j * a * th['gamma']
    elif method == 'damped':
        psi = a + a * th['gamma'] * np.cumsum(th['phi'] ** j)
    elif method == 'seasonal':
        psi = a + (j % s == 0) * th['delta'] * (1 - a)
    else:
        psi = a + j * a * th['gamma'] + (j % s == 0) * th['delta'] * (1 - a)
    return np.concatenate([[1.0], 1.0 + np.cumsum(psi ** 2)])


@api('timeseries.smooth')
@_quietly
def smooth(table, y, time=None, rows=None, excluded=None, method='simple', s=12, level=0.95, h=25, multiplicative=False,
           nlags=25, where=None, table_name='data'):
    """JMP's smoothing models with statsmodels' holtwinters: the weights and the
    starting states chosen to minimise the sum of squared one-step errors
    (initialization_method='estimated'); JMP's prediction intervals from the
    moving-average weights of the equivalent ARIMA model."""
    from scipy.optimize import minimize_scalar
    from statsmodels.tools.numdiff import approx_hess3
    if method not in SMOOTHERS:
        return {'error': f'no smoothing model {method!r}'}
    try:
        S = load(table, y, time, rows, excluded)
    except NoSeries as e:
        return {'error': str(e)}
    s = int(s or 0)
    seasonal = method in ('seasonal', 'winters')
    mult = bool(multiplicative) and method == 'winters'
    if seasonal and s < 2:
        return {'error': 'a seasonal smoothing model needs at least 2 observations per period'}
    x, miss = _filled(S)
    n = len(x)
    need = 2 * s + 2 if seasonal else 6
    if n < need:
        return {'error': f'too few observations ({n}) for this model; it needs {need}'}
    if mult and not (x > 0).all():
        return {'error': 'the multiplicative Winters method needs every value above zero'}
    level = float(level or 0.95)
    h = max(0, int(h or 0))
    notes = []
    with _quiet():
        if method == 'double':
            def fit_at(a):
                m = _hw_model(x, 'linear', s, False)
                with m.fix_params({'smoothing_level': a * (2 - a), 'smoothing_trend': a / (2 - a)}):
                    return m.fit()
            opt = minimize_scalar(lambda a: fit_at(a).sse, bounds=(1e-4, 1 - 1e-6), method='bounded', options={'xatol': 1e-7})
            res = fit_at(float(opt.x))
            th = {'alpha': float(opt.x)}
        else:
            res = _hw_model(x, method, s, mult).fit()
            pv = res.params
            th = {'alpha': float(pv['smoothing_level'])}
            if method in ('linear', 'damped', 'winters'):
                th['gamma'] = float(pv['smoothing_trend'])
            if method == 'damped':
                th['phi'] = float(pv['damping_trend'])
            if seasonal:
                th['delta'] = float(pv['smoothing_seasonal']) / (1 - th['alpha']) if th['alpha'] < 1 else 0.0
    pv = res.params
    fitted = np.array(res.fittedvalues, dtype=float)
    valid = ~miss & np.isfinite(fitted)
    keys = SMOOTHERS[method][1]
    k = len(keys)
    sse = float(np.sum((x - fitted)[valid] ** 2))
    nv = int(valid.sum())
    m2ll = nv * (math.log(2 * math.pi * sse / nv) + 1)
    st = _fit_stats(x, fitted, valid, k, m2ll)
    # standard errors: the Hessian of the Gaussian log-likelihood of the
    # one-step errors in the weights, the starting states held
    init = {'initial_level': float(pv['initial_level'])}
    if method in ('double', 'linear', 'damped', 'winters'):
        init['initial_trend'] = float(pv['initial_trend'])
    if seasonal:
        init['initial_seasonal'] = np.asarray(pv['initial_seasons'], dtype=float)
    free = [kk for kk in keys if 1e-5 < th[kk] < 1 - 1e-5]

    def llf(v):
        t2 = dict(th)
        t2.update(zip(free, v))
        with _quiet():
            r2 = _hw_model(x, 'linear' if method == 'double' else method, s, mult, **init).fit(**_sm_values(method, t2), optimized=False)
        e = (x - np.asarray(r2.fittedvalues, dtype=float))[valid]
        ss = float(np.sum(e ** 2))
        return -0.5 * nv * (math.log(2 * math.pi * ss / nv) + 1)

    se = {kk: None for kk in keys}
    if free:
        try:
            H = approx_hess3(np.array([th[kk] for kk in free]), llf)
            cov = np.linalg.inv(-H)
            for i, kk in enumerate(free):
                se[kk] = _f(math.sqrt(cov[i, i])) if cov[i, i] > 0 else None
        except (np.linalg.LinAlgError, ValueError, OverflowError):
            pass
    dfree = st['df'] or 1
    rows_p = []
    for kk in keys:
        e = th[kk]
        tt, pp = _pvals_t([e], [se[kk] if se[kk] is not None else np.nan], dfree)
        label = 'Level and Trend Smoothing Weight' if method == 'double' else WEIGHT_NAMES[kk]
        rows_p.append({'term': label, 'estimate': _f(e), 'se': se[kk], 't': _f(tt[0]), 'p': _f(pp[0]), 'bound': kk not in free})
    smv = _sm_values(method, th)
    notes.append('statsmodels\' parameters: ' + ', '.join(f'{kk} = {v:.6g}' for kk, v in smv.items()) +
                 (f'; starting level {init["initial_level"]:.6g}' + (f', trend {init["initial_trend"]:.6g}' if 'initial_trend' in init else '') +
                  (f' and {s} seasonal states' if seasonal else '') + ', estimated with the weights.'))
    notes.append('The weights and the starting states minimise the sum of squared one-step errors (holtwinters, initialization_method '
                 '"estimated"); JMP fits the equivalent ARIMA model, so its estimates, and above all its starting values, differ. '
                 'k counts the smoothing weights only, as JMP does; the Std Errors come from the Hessian of the likelihood with the '
                 'starting states held.')
    if any(r['bound'] for r in rows_p):
        notes.append('A weight at the edge of its range (0 or 1) has no standard error.')
    if method == 'linear' or method == 'damped' or method == 'winters':
        notes.append('statsmodels keeps the trend weight at or below the level weight, and the seasonal weight at or below 1 − α.')
    if miss.any():
        notes.append(f'{int(miss.sum())} missing value{"s" if miss.sum() > 1 else ""} filled by linear interpolation for the fit; they are left out of the fit statistics.')
    z = stats.norm.ppf(0.5 + level / 2)
    sig = st['sd'] if st['sd'] is not None else float('nan')
    with _quiet():
        if h:
            mean = np.asarray(res.forecast(h), dtype=float)
            if mult:
                sims = np.asarray(res.simulate(h, repetitions=2000, error='add', random_state=SEED), dtype=float).reshape(h, -1)
                lo = np.quantile(sims, 0.5 - level / 2, axis=1)
                hi = np.quantile(sims, 0.5 + level / 2, axis=1)
                fse = sims.std(axis=1, ddof=1)
                notes.append('Prediction intervals of the multiplicative model: quantiles of 2000 simulated paths (statsmodels\' simulate, a fixed seed).')
            else:
                fse = sig * np.sqrt(psi_variance(method, th, s, h))
                lo, hi = mean - z * fse, mean + z * fse
            fcd = _forecast(S, h, mean, fse, lo, hi)
        else:
            fcd = _forecast(S, 0, [], [], [], [])
    fitted_v = np.where(valid, fitted, np.nan)
    resid = np.where(valid, x - fitted, np.nan)
    summary = [['DF', st['df'], 'int'], ['Sum of Squared Errors', st['sse']], ['Variance Estimate', st['variance']],
               ['Standard Deviation', st['sd']], ["Akaike's 'A' Information Criterion", st['aic']], ["Schwarz's Bayesian Criterion", st['sbc']],
               ['AICc', st['aicc']], ['RSquare', st['rsquare']], ['RSquare Adj', st['rsquare_adj']], ['MAPE', st['mape']], ['MAE', st['mae']],
               ['−2LogLikelihood', st['m2ll']]]
    name = smoothing_name(method, s, mult)
    c = _code_series(S, table_name, where, ['from statsmodels.tsa.holtwinters import ExponentialSmoothing'])
    if miss.any():
        c.append('y = y.interpolate(limit_direction="both")')
    trend = 'add' if method in ('double', 'linear', 'damped', 'winters') else None
    seas = ('mul' if mult else 'add') if seasonal else None
    extra = (f', seasonal_periods={s}' if seasonal else '') + ', initialization_method="estimated"'
    if method == 'damped':
        extra += ', bounds={"damping_trend": (0.0, 1.0)}'
    mk = f'ExponentialSmoothing(y, trend={trend!r}, damped_trend={method == "damped"}, seasonal={seas!r}{extra})'
    if method == 'double':
        c += ['from scipy.optimize import minimize_scalar',
              'def fit_at(a):   # Brown\'s method is Holt\'s with level a(2 - a) and trend a/(2 - a)',
              f'    m = {mk}',
              '    with m.fix_params({"smoothing_level": a*(2 - a), "smoothing_trend": a/(2 - a)}):',
              '        return m.fit()',
              'a = minimize_scalar(lambda a: fit_at(a).sse, bounds=(1e-4, 1 - 1e-6), method="bounded").x',
              'res = fit_at(a)']
    else:
        c.append(f'res = {mk}.fit()')
    c += ['print(res.params_formatted)', f'print(res.forecast({h}))' if h else 'print(res.fittedvalues)']
    return _model_out(S, 'smooth', name, fitted_v, resid, np.where(valid, sig, np.nan), level, fcd, st, summary,
                      {'columns': 'smooth', 'rows': rows_p}, nlags, k, notes, '\n'.join(c),
                      weights=th, sm={'aic': _f(res.aic), 'aicc': _f(res.aicc), 'bic': _f(res.bic), 'sse': _f(res.sse)},
                      spec={'method': method, 's': s, 'multiplicative': mult})


# ---- state space smoothing (ETSModel) ----------------------------------------------------------

ETS_NAMES = {'smoothing_level': 'Level Smoothing (α)', 'smoothing_trend': 'Trend Smoothing (β)', 'smoothing_seasonal': 'Seasonal Smoothing (γ)',
             'damping_trend': 'Damping (φ)', 'initial_level': 'Initial Level', 'initial_trend': 'Initial Trend'}


def ets_name(error, trend, seasonal, s=12):
    code = f'{"A" if error == "add" else "M"},{trend or "N"},{seasonal or "N"}'
    return f'State Space Smoothing ETS({code}){s if seasonal and seasonal != "N" else ""}'


@api('timeseries.ets')
@_quietly
def ets(table, y, time=None, rows=None, excluded=None, error='add', trend='N', seasonal='N', s=12, level=0.95, h=25, maxiter=1000,
        nlags=25, where=None, table_name='data'):
    """A state space smoothing model ETS(error, trend, seasonal) of Hyndman et
    al. (2008) by maximum likelihood (statsmodels' ETSModel)."""
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel
    try:
        S = load(table, y, time, rows, excluded)
    except NoSeries as e:
        return {'error': str(e)}
    error = 'mul' if error in ('mul', 'M') else 'add'
    trend = {'A': 'A', 'Ad': 'Ad', 'add': 'A'}.get(trend, 'N')
    seasonal = {'A': 'A', 'M': 'M', 'add': 'A', 'mul': 'M'}.get(seasonal, 'N')
    s = int(s or 0)
    if seasonal != 'N' and s < 2:
        return {'error': 'a seasonal model needs at least 2 observations per period'}
    x, miss = _filled(S)
    n = len(x)
    if (error == 'mul' or seasonal == 'M') and not (x > 0).all():
        return {'error': 'multiplicative errors or seasonality need every value above zero'}
    if n < (2 * s + 4 if seasonal != 'N' else 8):
        return {'error': f'too few observations ({n}) for this model'}
    level = float(level or 0.95)
    h = max(0, int(h or 0))
    model = ETSModel(pd.Series(x), error=error, trend='add' if trend != 'N' else None, damped_trend=trend == 'Ad',
                     seasonal={'A': 'add', 'M': 'mul'}.get(seasonal), seasonal_periods=s if seasonal != 'N' else None,
                     initialization_method='estimated')
    with _quiet():
        res = model.fit(disp=False, maxiter=int(maxiter or 1000))
    fitted = np.array(res.fittedvalues, dtype=float)
    valid = ~miss & np.isfinite(fitted)
    nparm = int(len(res.params) + 1)
    st = _fit_stats(x, fitted, valid, nparm, -2 * float(res.llf))
    # the information criteria are statsmodels': the likelihood of the ETS model
    st.update({'aic': _f(res.aic), 'aicc': _f(res.aicc), 'sbc': _f(res.bic)})
    sigma = math.sqrt(float(res.mse)) if res.mse is not None and res.mse >= 0 else None
    names = list(res.param_names)
    est = np.array(res.params, dtype=float)
    try:
        se = np.array(res.bse, dtype=float)
    except Exception:
        se = np.full(len(est), np.nan)
    z = stats.norm.ppf(0.5 + level / 2)
    zc = stats.norm.ppf(0.975)
    rows_p = []
    for j, nm in enumerate(names):
        label = ETS_NAMES.get(nm) or (f'Initial Seasonal {int(nm.split(".")[1]) + 1}' if nm.startswith('initial_seasonal') else nm)
        e, s_ = est[j], se[j]
        rows_p.append({'term': label, 'estimate': _f(e), 'se': _f(s_), 'lower': _f(e - zc * s_), 'upper': _f(e + zc * s_), 'sm': nm})
    with _quiet():
        if h:
            pr = res.get_prediction(start=n, end=n + h - 1, simulate_repetitions=2000, random_state=SEED)
            fr = pr.summary_frame(alpha=1 - level)
            mean = fr['mean'].to_numpy(dtype=float)
            fv = np.asarray(getattr(pr, 'forecast_variance', np.full(h, np.nan)), dtype=float)
            fse = np.sqrt(fv) if np.isfinite(fv).all() else (fr['pi_upper'].to_numpy(dtype=float) - fr['pi_lower'].to_numpy(dtype=float)) / (2 * z)
            fcd = _forecast(S, h, mean, fse, fr['pi_lower'], fr['pi_upper'])
        else:
            fcd = _forecast(S, 0, [], [], [], [])
    fit_se = np.full(n, sigma if sigma is not None else np.nan)
    if error == 'mul':
        fit_se = fit_se * np.abs(fitted)
    states = res.states
    comp = {c: _arr(states[c]) for c in states.columns} if hasattr(states, 'columns') else {}
    summary = [['−2LogLikelihood', st['m2ll']], ['AIC', st['aic']], ['AICc', st['aicc']], ['BIC', st['sbc']], ['Nparm', nparm, 'int'],
               ['Sigma', sigma], ['RSquare', st['rsquare']], ['RSquare Adj', st['rsquare_adj']], ['MAPE', st['mape']], ['MAE', st['mae']]]
    notes = [f'Model type: {"multiplicative" if error == "mul" else "additive"} errors, '
             f'{ {"N": "no", "A": "additive", "Ad": "additive damped"}[trend]} trend, '
             f'{ {"N": "no", "A": "additive", "M": "multiplicative"}[seasonal]} seasonality'
             f'{f" (period {s})" if seasonal != "N" else ""}.',
             'AIC, AICc and BIC are statsmodels\': Nparm counts the smoothing parameters, the starting states and σ. '
             'Their likelihood is not comparable with the ARIMA models\' (JMP gives the same caution).']
    if error == 'mul' or seasonal == 'M':
        notes.append('Prediction intervals: quantiles of 2000 simulated paths (a fixed seed).')
    if miss.any():
        notes.append(f'{int(miss.sum())} missing value{"s" if miss.sum() > 1 else ""} filled by linear interpolation for the fit; they are left out of the fit statistics.')
    c = _code_series(S, table_name, where, ['from statsmodels.tsa.exponential_smoothing.ets import ETSModel'])
    if miss.any():
        c.append('y = y.interpolate(limit_direction="both")')
    c.append(f'res = ETSModel(y.reset_index(drop=True), error={error!r}, trend={("add" if trend != "N" else None)!r}, damped_trend={trend == "Ad"}, '
             f'seasonal={({"A": "add", "M": "mul"}.get(seasonal))!r}{", seasonal_periods=" + str(s) if seasonal != "N" else ""}).fit(disp=False)')
    c.append('print(res.summary())')
    if h:
        c.append(f'print(res.get_prediction(start=len(y), end=len(y) + {h - 1}).summary_frame(alpha={1 - level:.6g}))')
    fitted_v = np.where(valid, fitted, np.nan)
    resid = np.where(valid, x - fitted, np.nan)
    return _model_out(S, 'ets', ets_name(error, trend, seasonal, s), fitted_v, resid, np.where(valid, fit_se, np.nan), level, fcd, st, summary,
                      {'columns': 'ets', 'rows': rows_p}, nlags, 0, notes, '\n'.join(c),
                      states=comp, sigma=sigma, nparm=nparm, sm={'aic': _f(res.aic), 'aicc': _f(res.aicc), 'bic': _f(res.bic), 'llf': _f(res.llf)},
                      spec={'error': error, 'trend': trend, 'seasonal': seasonal, 's': s})
