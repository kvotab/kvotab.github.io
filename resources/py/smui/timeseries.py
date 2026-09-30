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
  and what JMP does not have:
  structural       UnobservedComponents: level/trend, seasonal (dummy or
                   trigonometric), cycle, AR part, inputs; the smoothed
                   components with their bands
  regime switching MarkovRegression and MarkovAutoregression from the default
                   start and seeded random starts (local maxima)
  filters          hpfilter, bkfilter, cffilter
  subseries        the data of month_plot / quarter_plot / seasonal_plot
  theta            ThetaModel (with the IMA(1, 1) prediction interval)
  Zivot-Andrews    zivot_andrews, with the break date
  ARDL             ardl_select_order, ARDL, UECM and the PSS bounds test

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
    hold   Forecast on Holdback: the last values held back from the fit
           ({'y', 't', 'rows', 'n'}), or None; y, t, rows and X are then the
           training part, and Xf starts with the inputs of the held-back slots
    cut    slots left out after the holdback (an origin of the rolling-origin
           cross-validation: the series as it was at that time)
    season the lag of the (seasonal) naive forecast that scales MASE
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
        self.hold = None
        self.cut = 0
        self.season = 1

    @property
    def n(self):
        return len(self.y)

    def future(self, h):
        """The time points of h periods after the series (the held-back
        slots' own times, when values are held back)."""
        h = int(h or 0)
        if h <= 0 or not len(self.t):
            return []
        if self.hold is not None and h <= self.hold['n']:
            return [float(v) for v in self.hold['t'][:h]]
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


def load(table, y, time=None, rows=None, excluded=None, inputs=None, holdback=0, cut=0, season=0):
    """The series of column y (and the input columns) for the given rows.
    holdback: the last values held back from the fit (Forecast on Holdback);
    cut: the slots after them left out (an origin of the cross-validation);
    season: the seasonal period that scales MASE (1 when not known)."""
    S = _load(table, y, time, rows, excluded, inputs)
    _split(S, int(cut or 0), int(holdback or 0))
    s = int(season or 0)
    S.season = s if s >= 2 and S.n > s else 1
    return S


def _split(S, cut, h):
    """Forecast on Holdback and the cross-validation's origins: the last cut
    slots left out, then the last h of the rest held back. Their inputs come
    first in Xf, the inputs' future values."""
    if cut <= 0 and h <= 0:
        return
    if cut + h + 3 > S.n:
        raise NoSeries(f'the series has {S.n} values: too few to hold back {h}' + (f' after leaving out {cut}' if cut else ''))

    def cut_off(k):
        m = S.n - k
        S.Xf = {c: np.concatenate([np.asarray(S.X[c][m:], dtype=float), np.asarray(S.Xf.get(c, []), dtype=float)]) for c in S.inputs}
        part = {'y': S.y[m:].copy(), 't': S.t[m:].copy(), 'rows': S.rows[m:], 'n': k}
        S.y, S.t, S.rows = S.y[:m], S.t[:m], S.rows[:m]
        S.X = {c: np.asarray(v[:m], dtype=float) for c, v in S.X.items()}
        return part

    if cut > 0:
        cut_off(cut)
        S.cut = cut
    if h > 0:
        S.hold = cut_off(h)
        if not np.isfinite(S.hold['y']).any():
            raise NoSeries(f'the last {h} values held back are all missing')


def _load(table, y, time=None, rows=None, excluded=None, inputs=None):
    """load() before the holdback: the whole span."""
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
    S.table, S.rows_arg = table, (None if rows is None else [int(r) for r in rows])
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

def left_out(table, rows, where=None):
    """The rows of the report's By group that it leaves out (filtered out by
    the Local Data Filter), as the table's row numbers: the code drops them,
    as the page never sends them. Excluded rows are not among them: they are
    sent, and count as missing values in their place."""
    if rows is None or table not in data.TABLES:
        return []
    mask = np.ones(data.TABLES[table]['n'], dtype=bool)
    for w in where or []:
        mask &= np.asarray(data.raw(table, w.get('column')) == w.get('value'), dtype=bool)
    keep = {int(r) for r in rows}
    return [int(r) for r in np.flatnonzero(mask) if int(r) not in keep]


def _code_series(S, table_name, where=None, imports=()):
    """Python that builds, from a CSV export of the table, d (the table in
    time order, indexed by the Time ID) and y (the series over its span)."""
    return [code_head(table_name, list(imports))] + _series_lines(S, where)


def _series_lines(S, where=None, graph=False):
    """The lines of _code_series after its head; a graph's code also gets t,
    the time axis as the page draws it (the dates, the Time ID's values, or
    the row numbers of the table)."""
    Y = json.dumps(S.y_name)
    lines = []
    for w in where or []:
        lines.append(f'df = df[df[{json.dumps(w.get("column"))}] == {w.get("value")!r}]   # the By group')
    drop = left_out(getattr(S, 'table', None), getattr(S, 'rows_arg', None), where)
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
    lines.append(f'y = d[{Y}]')
    lines.append('y = y.loc[y.first_valid_index():y.last_valid_index()]')
    if S.excluded_pos:
        lines.append(f'y.iloc[{S.excluded_pos}] = np.nan   # rows excluded in the table count as missing')
    lines += _hold_lines(S)
    if graph:
        lines += _time_lines(S)
    return lines


def _hold_lines(S):
    """The series as the fit takes it: the slots after a cross-validation
    origin left out, and the last values held back (y_hold) from y."""
    out = []
    if S.cut:
        out.append(f'y = y.iloc[:-{S.cut}]   # the series as it was at this origin: the last {_plural(S.cut, "value")} left out')
    if S.hold is not None:
        k = S.hold['n']
        out.append(f'y_all = y; y, y_hold = y_all.iloc[:-{k}], y_all.iloc[-{k}:]   # Forecast on Holdback: the last {_plural(k, "value")} held back, the model fitted on the rest')
    return out


def _time_lines(S, name='t', of='y'):
    """t, the time axis as the page draws it (the dates, the Time ID's values,
    or the row numbers of the table); t_hold and t_all too with a holdback."""
    def one(nm, series):
        if S.time_name:
            return f'{nm} = {series}.index'
        return f'{nm} = df.index.to_numpy()[{series}.index] + 1'
    what = ("the dates" if S.kind in DATE_KINDS else S.time_name) if S.time_name else 'the row numbers, as the page has them'
    out = [f'{one(name, of)}   # the time axis: {what}']
    if S.hold is not None and of == 'y':
        out.append(f'{one("t_hold", "y_hold")}; {one("t_all", "y_all")}   # the times of the held-back values, and of every value')
    return out


# ---- the graphs as matplotlib code ---------------------------------------------
# Under each graph the report shows Python that draws it with matplotlib from a
# CSV export of the table, as the notebook runs it: the report's rows, the light
# theme's colours, the graph's size. The function that makes a graph's numbers
# writes its code, as a recipe (a list) that the page puts together: lines;
# {'set': 'size'} and {'set': 'color'}, where the page writes the graph's size
# in the report (inches, at 100 pixels an inch) and a model's colour; and
# {'if': [flags], 'lines': [...]}, parts the page keeps when its display
# options say so (Show Points, Show Prediction Interval, the Mean Line ...;
# '!flag': when it is off). So neither a display option nor the room there is
# fits a model again. assemble() puts a recipe together as the page does.
BASE, RED, MUTED, INK = '#2f6690', '#b0413e', '#786b5d', '#352921'   # the report's points, fits, muted and text, light theme
BAR_FILL, BAND = '#6f93b8', '#2f6ec7'   # the diagnostics charts' bars and ±2 standard error marks (smui-timeseries.css)
REGIMES = ['#2a78d6', '#eb6834', '#1baf7a']   # the regimes, light theme (smui-p-timeseries.js)
PT = 0.72   # points per pixel, at 100 pixels an inch
SIZE, COLOR = {'set': 'size'}, {'set': 'color'}
J = json.dumps
DIAG_IMPORT = 'from statsmodels.tsa.stattools import acf, levinson_durbin'


def assemble(parts, flags=None, size=None, color=None):
    """A recipe put together as the page's recipe() does it: its lines, the
    parts whose flags all hold (a flag '!x' holds when x is off), and
    size = (w, h) in inches and color = "#..." where it asks for them."""
    flags = flags or {}

    def on(f):
        return not flags.get(f[1:]) if f.startswith('!') else bool(flags.get(f))

    out = []
    for p in parts or []:
        if isinstance(p, str):
            out.append(p)
        elif 'set' in p:
            if p['set'] == 'size':
                out.append(f'size = ({size[0] / 100:g}, {size[1] / 100:g})   # the graph\'s size in the report, in inches (100 pixels an inch)')
            elif p['set'] == 'color':
                out.append(f'color = "{color}"   # the model\'s colour in the report')
        elif all(on(f) for f in p.get('if', [])) and p.get('lines'):
            out.append(assemble(p['lines'], flags, size, color))
    return '\n'.join(out)


def _pt(px):
    """A width or a marker size of the page, in pixels, in points."""
    return f'{px * PT:.3g}'


def _when(flags, *lines):
    return {'if': list(flags), 'lines': list(lines)}


def _head(S, table_name, where=None, imports=()):
    """The top of a graph's code: the table, the series (y) and its time axis (t)."""
    return [code_head(table_name, ['import matplotlib.pyplot as plt', *imports])] + _series_lines(S, where, graph=True)


def _xlabel(S):
    return S.time_name or 'Row'


def _labels(S, ylabel, title, ax='ax'):
    return [f'{ax}.set_xlabel({J(_xlabel(S))})', f'{ax}.set_ylabel({J(ylabel)})', f'{ax}.set_title({J(title)})']


def _trace(x, v, points=True, lines=True, color=BASE, ax='ax', size=5, width=1.2, extra=''):
    """One series as the page's seriesTrace draws it: points, the lines between
    them, or both. color: a colour, or a Python name that holds one."""
    c = f'"{color}"' if color.startswith('#') else color
    if points and lines:
        return f'{ax}.plot({x}, {v}, color={c}, linewidth={_pt(width)}, marker="o", markersize={_pt(size)}{extra})'
    if points:
        return f'{ax}.plot({x}, {v}, color={c}, linestyle="", marker="o", markersize={_pt(size)}{extra})'
    return f'{ax}.plot({x}, {v}, color={c}, linewidth={_pt(width)}{extra})'


def _series_draw(x, v, mean=None, ax='ax'):
    """The page's seriesPlot: the series as Show Points and Connecting Lines
    choose, and the Mean Line."""
    parts = [_when(['points', 'lines'], _trace(x, v, ax=ax) + '   # Show Points and Connecting Lines'),
             _when(['points', '!lines'], _trace(x, v, lines=False, ax=ax) + '   # Show Points'),
             _when(['!points', 'lines'], _trace(x, v, points=False, ax=ax) + '   # Connecting Lines')]
    if mean:
        parts.append(_when(['mean'], f'{ax}.axhline({mean}, color="{RED}", linewidth={_pt(1)}, linestyle=":")   # Mean Line: the mean of the series'))
    return parts


def _series_recipe(head, x, v, name, title, S, mean=None, before=()):
    """A series graph (seriesPlot): its points or lines, the mean line, the labels."""
    return [*head, *before, '', SIZE, 'fig, ax = plt.subplots(figsize=size, layout="constrained")',
            *_series_draw(x, v, mean), *_labels(S, name, title), 'plt.show()']


def _fixed_series_recipe(head, x, v, name, title, S, before=(), extra=()):
    """A series graph with its points and lines always shown (and more on it)."""
    return [*head, *before, '', SIZE, 'fig, ax = plt.subplots(figsize=size, layout="constrained")',
            _trace(x, v), *extra, *_labels(S, name, title), 'plt.show()']


def _future_line(S, h):
    """t_f: the times of the h forecast periods, as S.future has them."""
    if S.hold is not None and h <= S.hold['n']:
        return f't_f = t_hold{"" if h == S.hold["n"] else f"[:{h}]"}   # the forecasts are of the held-back values'
    if S.kind in DATE_KINDS and S.offset is not None:
        return f't_f = pd.date_range(t[-1], periods={h + 1}, freq={S.freq!r})[1:]   # the next {h} dates of the calendar'
    if S.kind in DATE_KINDS:
        return f't_f = t[-1] + pd.to_timedelta({S.step!r} * np.arange(1, {h + 1}), unit="ms")   # the median spacing of the dates'
    return f't_f = t[-1] + {S.step!r} * np.arange(1, {h + 1})   # the next {h} steps of the time axis'


def _diag_recipes(head, x_lines, nlags, residual=False):
    """The four diagnostics charts of the page, as JMP draws them in its
    tables: a bar per lag (lag 0 at the top), the Autocorrelation with ±2
    Bartlett standard errors, the Partial Autocorrelation with ±2/√N, the
    Variogram and the AR Coefficients, all from x as the report takes it."""
    K = max(1, int(nlags or 25))
    calc = [*x_lines,
            'v = x.loc[x.first_valid_index():x.last_valid_index()]   # from its first value to its last',
            'n = int(v.count())',
            f'K = min({K}, n - 1)   # the lags: Autocorrelation Lags of the launch, at most n − 1',
            'r = acf(v, nlags=K, fft=False, missing="conservative")   # a missing value inside is left out pairwise']

    def chart(extra, value, label, title, lags='np.arange(K + 1)', rng='-1, 1', band=None):
        L = [*head, *calc, *extra, f'lags = {lags}',
             'fig, ax = plt.subplots(figsize=(3.4, 0.9 + 0.16 * len(lags)), layout="constrained")',
             f'ax.barh(lags, {value}, height=0.7, color="{BAR_FILL}")']
        if band:
            L += [f'for side in (1, -1):   # {band[1]}',
                  f'    ax.plot(side * {band[0]}, lags[1:], linestyle="", marker="|", markersize=7, markeredgewidth={_pt(1.3)}, color="{BAND}")']
        L += [f'ax.axvline(0, color="{MUTED}", linewidth={_pt(1)})', f'ax.set_xlim({rng})', 'ax.invert_yaxis()   # lag by lag down the chart, as the table has them',
              f'ax.set_xlabel({J(label)})', 'ax.set_ylabel("Lag")', f'ax.set_title({J(title)})', 'plt.show()']
        return L

    auto = ('m = max(1e-12, np.nanmax(np.abs({0}))); lo = -m if (np.asarray({0}) < 0).any() else 0.0'
            '   # the range of the values, as the page scales these bars')
    return {
        'acf': chart(['se = np.sqrt(np.r_[0.0, 1 / n, (1 + 2 * np.cumsum(r[1:-1] ** 2)) / n])[:K + 1]   # Bartlett\'s large-lag standard errors'],
                     'r', 'AutoCorr', 'Residual Autocorrelation' if residual else 'Autocorrelation', band=('2 * se[1:]', '±2 standard errors')),
        'pacf': chart(['_, _, pac, _, _ = levinson_durbin(r, nlags=K, isacov=True)   # Levinson-Durbin on the autocorrelations (pacf\'s "ldb")'],
                      'pac', 'Partial', 'Residual Partial Autocorrelation' if residual else 'Partial Autocorrelation', band=('np.full(K, 2 / np.sqrt(n))', '±2/√N')),
        'variogram': chart(['vario = (1 - r[1:]) / (1 - r[1])   # the variance of differences k apart over that of differences one apart',
                            auto.format('vario')], 'vario', 'Variogram', 'Variogram', lags='np.arange(1, K + 1)', rng='lo, m'),
        'ar': chart(['_, arc, _, _, _ = levinson_durbin(r, nlags=K, isacov=True)   # the AR(K) coefficients (Yule-Walker)', auto.format('arc')],
                    'arc', 'AR Coef', 'AR Coefficients', lags='np.arange(1, K + 1)', rng='lo, m'),
    }


# A model's graphs. Its fit lines (the model fitted as its code in the report
# fits it) leave, over the slots of the series: fitted (the one-step-ahead
# predictions), fit_lo and fit_hi (their prediction interval), resid; and with
# forecasts t_f, f_mean, f_lower and f_upper. Its draw lines put the model on
# ax in its colour, as the page's forecastTraces: the predictions, the
# forecasts from the last of them, the band (pi) and the one-step intervals
# (onestep), with its name in the legend (legend) on Model Comparison's plot.
def _model_draw(S, name, h, onestep=True):
    L = [_when(['legend'], f'ax.plot(t, fitted, color=color, linewidth={_pt(1.3)}, label={J(name)})   # the one-step-ahead predictions'),
         _when(['!legend'], f'ax.plot(t, fitted, color=color, linewidth={_pt(1.3)})   # the one-step-ahead predictions')]
    if h:
        L += ['x_f = t[-1:].append(t_f)' if S.kind in DATE_KINDS else 'x_f = np.r_[t[-1], t_f]',
              'y0 = fitted[-1] if np.isfinite(fitted[-1]) else y.iloc[-1]   # the forecasts go on from the last prediction',
              _when(['pi'], 'lo0 = fit_lo[-1] if np.isfinite(fit_lo[-1]) else f_lower[0]', 'hi0 = fit_hi[-1] if np.isfinite(fit_hi[-1]) else f_upper[0]',
                    f'ax.plot(x_f, np.r_[hi0, f_upper], color=color, alpha=0.6, linewidth={_pt(1)})',
                    f'ax.plot(x_f, np.r_[lo0, f_lower], color=color, alpha=0.6, linewidth={_pt(1)})',
                    'ax.fill_between(x_f, np.r_[lo0, f_lower], np.r_[hi0, f_upper], color=color, alpha=0.13, linewidth=0)   # the prediction interval'),
              f'ax.plot(x_f, np.r_[y0, f_mean], color=color, linewidth={_pt(2)}, marker="o", markersize={_pt(3)})   # the forecasts']
    if onestep:
        L.append(_when(['pi', 'onestep'], f'ax.plot(t, fit_hi, color=color, alpha=0.45, linewidth={_pt(0.8)}, linestyle=":")   # the one-step prediction interval',
                       f'ax.plot(t, fit_lo, color=color, alpha=0.45, linewidth={_pt(0.8)}, linestyle=":")'))
    return L


def _resid_corr(name, nlags, partial=False):
    """The model's residual autocorrelations (or partial ones) on ax, for the
    overlays under Model Comparison's plot; nmax keeps the most residuals,
    for the ±2/√n lines."""
    L = ['e = pd.Series(resid); e = e.loc[e.first_valid_index():e.last_valid_index()]   # the residuals, from the first to the last',
         f'n_e = int(e.count()); K = min({max(1, int(nlags or 25))}, n_e - 1); nmax = max(nmax, n_e)',
         'r = acf(e, nlags=K, fft=False, missing="conservative")']
    if partial:
        L.append('_, _, r, _, _ = levinson_durbin(r, nlags=K, isacov=True)   # the partial autocorrelations')
    L.append(f'ax.plot(np.arange(1, K + 1), r[1:], color=color, linewidth={_pt(1.2)}, marker="o", markersize={_pt(4)}, label={J(name)})')
    return L


def _model_plots(S, table_name, where, name, imports, fit, h, nlags, onestep=True):
    """A model's graphs as recipes (the forecast, the residuals, the residual
    diagnostics), and its fragment for the page's Model Comparison: the
    imports, the series lines, the fit, the draw and the residual
    correlations. With values held back, the forecast graph shows every
    value and shades the held-back ones, and 'holdback' is the code of the
    holdback statistics (the fragment's hb_def and hb, for the page's)."""
    imports = ['from scipy import stats', *imports]
    body = [*_head(S, table_name, where, imports), *fit]
    draw = _model_draw(S, name, h, onestep)
    fig = ['', SIZE, COLOR, 'fig, ax = plt.subplots(figsize=size, layout="constrained")']
    held = S.hold is not None
    data = (_trace('t_all', 'y_all', lines=False) + '   # Show Points: the data, the held-back values too') if held else (_trace('t', 'y', lines=False) + '   # Show Points: the data')
    codes = {
        'forecast': [*body, *fig, _when(['points'], data), *draw,
                     f'ax.axvline(t[-1], color="{MUTED}", linewidth={_pt(1)}, linestyle=":")   # the end of the {"values the model is fitted to" if held else "data"}',
                     *([_hold_span()] if held else []),
                     *_labels(S, S.y_name, f'{name} forecast'), 'plt.show()'],
        'resid': [*body, *fig, _trace('t', 'resid', lines=False, color='color') + '   # the residuals',
                  f'ax.axhline(0, color="{MUTED}", linewidth={_pt(1)})', *_labels(S, 'Residual', f'{name} residuals'), 'plt.show()'],
        **_diag_recipes([*_head(S, table_name, where, [*imports, DIAG_IMPORT]), *fit], ['x = pd.Series(resid)   # the residuals'], nlags, residual=True),
    }
    codes['runs'] = [code_head(table_name, imports), *_series_lines(S, where, graph=True), *fit, *_runs_lines('resid', 'zero', 'the residuals')]
    frag = {'name': name, 'imports': imports, 'series': _series_lines(S, where, graph=True), 'fit': fit, 'draw': draw,
            'racf': _resid_corr(name, nlags), 'rpacf': _resid_corr(name, nlags, partial=True)}
    if held and h:
        codes['holdback'] = [code_head(table_name, imports), *_series_lines(S, where, graph=True), *fit, *HB_DEF,
                             f'print(pd.Series({_hb_call(S)}))   # {name}: the forecasts of the held-back values']
        frag.update(hb_def=HB_DEF, hb=_hb_call(S))
    return codes, frag


def _hold_span():
    """The holdback shaded, as the page shades it."""
    return f'ax.axvspan(t[-1], t_hold[-1], color="{MUTED}", alpha=0.12, linewidth=0)   # the held-back values'


# Forecast on Holdback: the statistics of the forecast errors on the held-back
# values (MASE scaled by the training values' in-sample (seasonal) naive MAE,
# Hyndman and Koehler 2006), as _holdback_stats computes them.
HB_DEF = [
    'def holdback_stats(actual, forecast, train, lag):   # the errors of the forecasts of the held-back values',
    '    a = np.asarray(actual, dtype=float); e = a - np.asarray(forecast, dtype=float)[:len(a)]; ok = np.isfinite(e)',
    '    v = np.asarray(train, dtype=float); scale = np.nanmean(np.abs(v[lag:] - v[:-lag]))   # MASE\'s scale: the (seasonal) naive one-step MAE on the training values',
    '    mse = np.mean(e[ok] ** 2)',
    '    return {"N": int(ok.sum()), "RMSE": np.sqrt(mse), "MSE": mse, "MAPE": 100 * np.mean(np.abs(e[ok] / a[ok])) if (a[ok] != 0).all() else np.nan,',
    '            "MAE": np.mean(np.abs(e[ok])), "Mean Error": np.mean(e[ok]), "MASE": np.mean(np.abs(e[ok])) / scale}']


def _hb_call(S):
    return f'holdback_stats(y_hold, f_mean, y, {S.season})'


def _holdback_stats(S, mean):
    """The forecast errors on the held-back values and their statistics: N,
    RMSE, MSE, MAPE, MAE, the mean error and MASE (the MAE over the training
    values' in-sample MAE of the naive forecast at lag S.season)."""
    a = np.asarray(S.hold['y'], dtype=float)
    f = np.full(len(a), np.nan)
    m = np.asarray(mean if mean is not None else [], dtype=float)[:len(a)]
    f[:len(m)] = m
    e = a - f
    ok = np.isfinite(e)
    v = np.asarray(S.y, dtype=float)
    lag = int(S.season or 1)
    dv = np.abs(v[lag:] - v[:-lag]) if len(v) > lag else np.array([])
    dv = dv[np.isfinite(dv)]
    scale = float(dv.mean()) if len(dv) else float('nan')
    out = {'n': int(ok.sum()), 'lag': lag, 'scale': _f(scale), 't': _arr(S.hold['t']), 'rows': S.hold['rows'],
           'actual': _arr(a), 'forecast': _arr(f), 'error': _arr(e)}
    if not ok.any():
        return {**out, 'rmse': None, 'mse': None, 'mape': None, 'mae': None, 'me': None, 'mase': None}
    ee, aa = e[ok], a[ok]
    mse = float(np.mean(ee ** 2))
    mae = float(np.mean(np.abs(ee)))
    return {**out, 'rmse': _f(math.sqrt(mse)), 'mse': _f(mse), 'mape': _f(100 * np.mean(np.abs(ee / aa))) if (aa != 0).all() else None,
            'mae': _f(mae), 'me': _f(np.mean(ee)), 'mase': _f(mae / scale) if scale > 0 else None}


def _z_line(level):
    return f'z = stats.norm.ppf({0.5 + level / 2:.6g})   # {100 * level:g}% intervals'


def _band_lines(valid='ok', fitted='fv', se='se', resid=None):
    """fitted, fit_lo, fit_hi and resid over the slots, where the fit statistics take them."""
    return [f'fitted = np.where({valid}, {fitted}, np.nan)',
            f'fit_lo, fit_hi = fitted - z * {se}, fitted + z * {se}',
            f'resid = np.where({valid}, {resid}, np.nan)' if resid else f'resid = np.where({valid}, y.to_numpy() - {fitted}, np.nan)']


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


RUNS_CUTOFFS = {'mean': 'the mean', 'median': 'the median', 'zero': 'zero'}


def runs_test(x, cutoff='mean', correction=True):
    """The Wald-Wolfowitz runs test of randomness about the mean, the median
    or zero: the values present, in time order, as at or above the cutoff
    (statsmodels' runstest_1samp's rule) or below it; R, the number of runs,
    against E = 2 n1 n2 / N + 1 and V = 2 n1 n2 (2 n1 n2 - N) / (N^2 (N - 1)).
    Below N = 50 the distance R - E is shrunk by 1/2, the continuity
    correction of the SAS manual that statsmodels follows; statsmodels 0.14.6
    moves a distance of less than 1/2 away from 0 by 1/2 instead of to 0."""
    v = np.asarray(x, dtype=float)
    v = v[np.isfinite(v)]
    N = len(v)
    cutoff = cutoff if cutoff in RUNS_CUTOFFS else 'mean'
    if N < 3:
        return {'error': 'the runs test needs at least 3 values', 'cutoff': cutoff}
    c = float(np.mean(v)) if cutoff == 'mean' else float(np.median(v)) if cutoff == 'median' else 0.0
    above = v >= c
    n1, n2 = int(above.sum()), int(N - above.sum())
    if not n1 or not n2:
        return {'error': f'every value is {"at or above" if n1 else "below"} {RUNS_CUTOFFS[cutoff]}', 'cutoff': cutoff, 'value': c}
    runs = 1 + int(np.sum(above[1:] != above[:-1]))
    E = 2.0 * n1 * n2 / N + 1
    V = 2.0 * n1 * n2 * (2.0 * n1 * n2 - N) / (N ** 2 * (N - 1.0))
    d = runs - E
    corrected = bool(correction) and N < 50
    if corrected:
        d = math.copysign(max(0.0, abs(d) - 0.5), d)
    z = d / math.sqrt(V) if V > 0 else float('nan')
    return {'cutoff': cutoff, 'value': _f(c), 'n': N, 'n_above': n1, 'n_below': n2, 'runs': runs, 'expected': _f(E), 'sd': _f(math.sqrt(V)) if V > 0 else None,
            'z': _f(z), 'p': _f(2 * stats.norm.sf(abs(z))) if math.isfinite(z) else None, 'corrected': corrected}


def _runs_lines(x_expr, cutoff, what):
    """The runs test's code on the values of x_expr (in time order)."""
    c = {'mean': 'np.mean(v)', 'median': 'np.median(v)', 'zero': '0.0'}[cutoff]
    return [f'v = pd.Series({x_expr}).dropna().to_numpy()   # {what}: the values present, in time order',
            f'c = {c}   # about {RUNS_CUTOFFS[cutoff]}',
            'above = v >= c; N, n1 = len(v), int(np.sum(v >= c)); n2 = N - n1   # at or above the cutoff (statsmodels\' rule), and below it',
            'runs = 1 + int(np.sum(above[1:] != above[:-1]))   # the runs',
            'E = 2 * n1 * n2 / N + 1; V = 2 * n1 * n2 * (2 * n1 * n2 - N) / (N ** 2 * (N - 1))   # their expectation and variance',
            'd = runs - E',
            'if N < 50:   # the continuity correction of the SAS manual: |R − E| less 1/2 (statsmodels 0.14.6 moves |d| < 1/2 the wrong way)',
            '    d = np.sign(d) * max(0.0, abs(d) - 0.5)',
            'z = d / np.sqrt(V); p = 2 * stats.norm.sf(abs(z))',
            'print(pd.Series({"Runs": runs, "Expected Runs": E, "N At or Above": n1, "N Below": n2, "z": z, "Prob > |z|": p}))']


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
    out['plot_code'] = {'series': _series_recipe(_head(S, table_name, where), 't', 'y', y, f'{y} time series', S, mean='y.mean()'),
                        **_diag_recipes(_head(S, table_name, where, [DIAG_IMPORT]), ['x = y   # the series'], nlags)}
    # the lines that build y and t, for the graphs the page works out (the lag plot)
    out['plot_frag'] = {'series': _series_lines(S, where, graph=True)}
    # the runs test about the mean, the median or zero (Runs Test in the red triangle), with its code
    out['runs'] = {c: runs_test(S.y, c) for c in RUNS_CUTOFFS}
    out['runs_code'] = {c: [*_code_series(S, table_name, where, ['from scipy import stats']), *_runs_lines('y', c, 'the series')] for c in RUNS_CUTOFFS}
    return out


@api('timeseries.input')
@_quietly
def input_series(table, y, time=None, rows=None, nlags=25, where=None, table_name='data'):
    """An input series (Input List), for the Input Time Series Panel."""
    try:
        S = load(table, y, time, rows)
    except NoSeries as e:
        return {'error': str(e)}
    return {'y': y, 'kind': S.kind, 't': _arr(S.t), 'values': _arr(S.y), 'rows': S.rows, 'diag': diagnostics(S.y, nlags),
            'stationarity': stationarity(S.y),
            'plot_code': {'series': _fixed_series_recipe(_head(S, table_name, where), 't', 'y', y, f'{y} time series', S),
                          **_diag_recipes(_head(S, table_name, where, [DIAG_IMPORT]), ['x = y   # the input series'], nlags)}}


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
    imp = 'from statsmodels.tsa.statespace.tools import diff'
    wl = [f'w = diff(y, k_diff={d}, k_seasonal_diff={D}, seasonal_periods={s if D else 1})   # (1 − B)^{d} (1 − B^{s})^{D} y: '
          f'the first {out["start"]} value{"s" if out["start"] != 1 else ""} lost']
    name = f'{y} differenced'
    out['plot_code'] = {'series': _series_recipe(_head(S, table_name, where, [imp]), 't[len(t) - len(w):]', 'w', name, f'{name} time series', S,
                                                 mean='w.mean()', before=wl),
                        **_diag_recipes(_head(S, table_name, where, [imp, DIAG_IMPORT]), [*wl, 'x = w'], nlags)}
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
    fit = ['k = np.arange(1, len(y) + 1)   # 1, 2, … the observation number',
           'res = sm.OLS(y.to_numpy(), sm.add_constant(k), missing="drop").fit()',
           'trend = res.params[0] + res.params[1] * k   # the least squares line']
    out['plot_code'] = _derived_plots(S, table_name, where, fit, 'trend', 'Linear Trend', f'Detrended {y}', nlags)
    return out


def _derived_plots(S, table_name, where, fit, part, label, dname, nlags):
    """Remove Linear Trend and Remove Cycle: the series with the fitted line
    (fit), the series with it removed (series) and that one's diagnostics."""
    y = S.y_name
    head = _head(S, table_name, where)
    return {'fit': _fixed_series_recipe(head, 't', 'y', y, f'{y} {label.lower()}', S, before=fit,
                                        extra=[f'ax.plot(t, {part}, color="{RED}", linewidth={_pt(1.6)})   # the {label.lower()}']),
            'series': _fixed_series_recipe(head, 't', f'y - {part}', dname, f'{dname} time series', S, before=fit),
            **_diag_recipes(_head(S, table_name, where, [DIAG_IMPORT]), [*fit, f'x = y - {part}   # {dname[0].lower()}{dname[1:]}'], nlags)}


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
    design = 'sm.add_constant(X, has_constant="add")' if constant else 'X'
    fit = ['k = np.arange(len(y))   # 0, 1, … one less than the observation number',
           f'X = np.column_stack([np.cos(2 * np.pi * k / {U!r}), np.sin(2 * np.pi * k / {U!r})])',
           f'res = sm.OLS(y.to_numpy(), {design}, missing="drop").fit()',
           f'a, b = res.params[{1 if constant else 0}:]; A, P = np.hypot(a, b), np.arctan2(-b, a)   # the amplitude and the phase',
           f'cycle = {"res.params[0] + " if constant else ""}A * np.cos(2 * np.pi * k / {U!r} + P)']
    out['plot_code'] = _derived_plots(S, table_name, where, fit, 'cycle', 'Cycle', f'Decycled {y}', nlags)
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
    label = f'STL Decomposition (period {s}{", robust" if robust else ""})' if method == 'stl' else f'Seasonal Decomposition ({model or "additive"}, period {s})'
    p = [*_head(S, table_name, where, ['from statsmodels.tsa.seasonal import STL' if method == 'stl' else 'from statsmodels.tsa.seasonal import seasonal_decompose']),
         'yf = y.interpolate(limit_direction="both")   # the missing values filled for the decomposition' if miss.any() else 'yf = y',
         f'res = STL(yf, period={s}, robust={bool(robust)}).fit()' if method == 'stl' else f'res = seasonal_decompose(yf, model={("multiplicative" if mult else "additive")!r}, period={s})',
         f'adjusted, resid = yf {"/" if mult else "-"} res.seasonal, res.resid.copy()   # the seasonally adjusted series, the irregular part']
    if miss.any():
        p.append('adjusted[y.isna()] = np.nan; resid[y.isna()] = np.nan   # missing where the series is')
    p += ['', SIZE, 'fig, axes = plt.subplots(4, 1, sharex=True, figsize=size, layout="constrained", gridspec_kw={"height_ratios": [27, 20, 20, 21]})',
          _trace('t', 'y', ax='axes[0]') + '   # the series',
          f'axes[0].plot(t, adjusted, color="{RED}", linewidth={_pt(1.2)})   # seasonally adjusted',
          'for ax, part in zip(axes[1:], (res.trend, res.seasonal, resid)):',
          f'    ax.plot(t, part, color="{BASE}", linewidth={_pt(1.2)})',
          'for ax, title in zip(axes, ("Original and adjusted", "Trend", "Seasonal", "Irregular")):',
          '    ax.set_title(title, loc="left", fontsize=8)',
          f'axes[-1].set_xlabel({J(_xlabel(S))})', f'fig.suptitle({J(label)}, fontsize=10)', 'plt.show()']
    out['plot_code'] = {'decomp': p}
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
    p = [*_head(S, table_name, where),
         'v = y.dropna().to_numpy(); N = len(v); i = np.arange(N)   # the values present',
         'C = np.exp(-2j * np.pi * i / N) * np.fft.fft(v)   # sums over t = 1 … N',
         'a, b = 2 / N * C.real, -2 / N * C.imag; I = N / 2 * (a ** 2 + b ** 2)   # the Fourier coefficients and the periodogram at i/N',
         'q = N // 2 if N % 2 == 0 else (N - 1) // 2; Iq, freq = I[1:q + 1], i[1:q + 1] / N']
    if q > m + 1:
        p += ['m = max(1, int(round(q ** 0.5 / 2)))   # the smoothing\'s half-width',
              'w = m + 1 - np.abs(np.arange(-m, m + 1)); w = w / w.sum()   # triangular weights over 2m + 1 frequencies',
              'ext = np.concatenate([Iq[1:m + 1][::-1], Iq, Iq[-m - 1:-1][::-1]])   # the periodogram reflected at the ends',
              'density = np.convolve(ext, w, mode="valid") / (4 * np.pi)   # the smoothed periodogram, scaled by 1/(4π)']
    else:
        p.append('density = Iq / (4 * np.pi)   # too few frequencies to smooth')
    p += ['', SIZE, 'fig, ax = plt.subplots(figsize=size, layout="constrained")']
    line = f'color="{RED}", linewidth={_pt(1.8)}'
    out['plot_code'] = {
        'period': [*p, f'ax.plot(1 / freq, density, {line})', 'ax.set_xscale("log")',
                   'ax.set_xlabel("Period")', 'ax.set_ylabel("Spectral density")', f'ax.set_title({J(y + " spectral density by period")})', 'plt.show()'],
        'frequency': [*p, f'ax.plot(freq, Iq / (4 * np.pi), color="{BASE}80", linestyle="", marker="o", markersize={_pt(4)}, label="Periodogram")   # scaled as the density',
                      f'ax.plot(freq, density, {line}, label="Spectral density")',
                      'ax.set_xlabel("Frequency")', 'ax.set_ylabel("Spectral density")', f'ax.set_title({J(y + " spectral density by frequency")})',
                      'fig.legend(loc="outside lower center", ncols=2, frameon=False, fontsize=8)', 'plt.show()']}
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
    c = _code_series(S, table_name, where, ['from statsmodels.tsa.stattools import ccf'])
    for name in S.inputs:
        c.append(f'x = d.loc[y.index, {json.dumps(name)}]')
        c.append(f'print(ccf(y, x, adjusted=False, fft=False)[:{K + 1}])   # lags 0..{K}: corr(y[t+k], x[t]); ccf(x, y) for the negative lags')
    return {'lags': lags, 'n': n, 'inputs': res, 'code': '\n'.join(c), 'plot_code': {'ccf': _ccf_recipe(S, table_name, where, res, nlags)}}


def _ccf_recipe(S, table_name, where, res, nlags):
    """Cross Correlation's charts, a panel for each input the report has, as
    its tables draw them: a bar per lag from −K to K, ±2 standard errors."""
    ok = [c['input'] for c in res if not c.get('error')]
    if not ok:
        return None
    complete = all(np.isfinite(S.y).all() and np.isfinite(S.X[c]).all() for c in ok)
    p = [*_head(S, table_name, where, ['from statsmodels.tsa.stattools import ccf'] if complete else []),
         'n = int(y.count())',
         f'K = min({max(1, int(nlags or 25))}, n - 2)   # the lags either way: Autocorrelation Lags of the launch, at most n − 2',
         'lags = np.arange(-K, K + 1)',
         'se = 1 / np.sqrt(np.maximum(1, n - np.abs(lags)))   # the standard error of each lag, 1/√(n − |k|)',
         f'inputs = {J(ok)}',
         'fig, axes = plt.subplots(1, len(inputs), figsize=(3.4 * len(inputs), 0.9 + 0.16 * len(lags)), squeeze=False, layout="constrained")',
         'for ax, name in zip(axes[0], inputs):',
         '    x = d.loc[y.index, name]']
    if complete:
        p.append('    r = np.r_[ccf(x, y, adjusted=False, fft=False)[1:K + 1][::-1], ccf(y, x, adjusted=False, fft=False)[:K + 1]]   # corr(y[t+k], x[t]) for k = −K … K')
    else:   # as the report: over the pairs present, each series about its own mean
        p += ['    ok = (y.notna() & x.notna()).to_numpy(); m = int(ok.sum())',
              '    yc, xc = np.nan_to_num((y - y.mean()).to_numpy()), np.nan_to_num((x - x.mean()).to_numpy())   # missing values count as 0',
              '    r = np.array([np.sum(yc[k:] * xc[:len(xc) - k]) if k >= 0 else np.sum(yc[:k] * xc[-k:]) for k in lags]) / (m * y.std(ddof=0) * x.std(ddof=0))']
    p += [f'    ax.barh(lags, r, height=0.7, color="{BAR_FILL}")',
          '    for side in (1, -1):   # ±2 standard errors',
          f'        ax.plot(side * 2 * se, lags, linestyle="", marker="|", markersize=7, markeredgewidth={_pt(1.3)}, color="{BAND}")',
          f'    ax.axvline(0, color="{MUTED}", linewidth={_pt(1)})',
          '    ax.set_xlim(-1, 1); ax.invert_yaxis()   # lag by lag down the chart, as the table has them',
          f'    ax.set_xlabel("Cross Corr"); ax.set_ylabel("Lag"); ax.set_title({J(S.y_name + " with ")} + name)',
          'plt.show()']
    return p


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
           'resid_diag': diagnostics(resid, nlags, model_df), 'resid_runs': runs_test(resid, cutoff='zero'), 'notes': notes, 'code': code}
    out.update(extra)
    ov = out.pop('fit_lo_override', None)
    if ov:                  # limits that are not the prediction ± z se (a Box-Cox model's, transformed back)
        out['fit_lo'], out['fit_hi'] = ov
    if S.hold is not None:
        out['holdback'] = _holdback_stats(S, (fc or {}).get('mean'))
        hb_code = (out.get('plot_code') or {}).pop('holdback', None)
        if hb_code:
            out['code'] = f'{code}\n\n# Forecast on Holdback: the model fitted without the last {_plural(S.hold["n"], "value")}, its forecasts of them and their errors\n{assemble(hb_code)}'
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
        if S.hold is not None and h and not np.isfinite(xf[:S.hold['n']]).all():
            raise NoSeries(f'{c} has missing values in the held-back rows: the forecasts of them need every value of the inputs')
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
        elif h and S.hold is not None:
            notes.append(f'{c}: the forecasts of the held-back values take its values in the {_plural(h, "held-back row")}.')
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
          level=0.95, h=25, maxiter=200, inputs=None, nlags=25, where=None, table_name='data', holdback=0, cut=0, season=0):
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
        S = load(table, y, time, rows, excluded, [sp['name'] for sp in specs], holdback=holdback, cut=cut, season=season)
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
    held = S.hold is not None
    if specs:
        c.append('# the inputs, lagged as in the model; X_future: their values for the forecast periods')
        cols_code = []
        for sp in specs:
            b0, r0 = int(sp.get('lag') or 0), int(sp.get('num') or 0)
            for j in range(b0, b0 + r0 + 1):
                label = sp['name'] if j == 0 else f'{sp["name"]}(t−{j})'
                cols_code.append(f'{json.dumps(label)}: d[{json.dumps(sp["name"])}].reindex({"y_all" if held else "y"}.index).shift({j})')
        x_future = 'X_future = X_all.loc[y_hold.index].to_numpy()   # the inputs of the held-back rows' if held else \
            'X_future = pd.DataFrame({' + ', '.join(f'{json.dumps(nm)}: {[_f(v) for v in Ef[:, j]]}' for j, nm in enumerate(xnames)) + '})'
        if held:
            c.append('X_all = pd.DataFrame({' + ', '.join(cols_code) + '}); X = X_all.loc[y.index]')
        else:
            c.append('X = pd.DataFrame({' + ', '.join(cols_code) + '})')
        if start:
            c.append(f'y, X = y.iloc[{start}:], X.iloc[{start}:]')
        if h:
            c.append(x_future)
    trend_code = repr(trend)
    c.append(f'res = ARIMA(y{", exog=X" if specs else ""}, order=({p}, {d}, {q}), seasonal_order=({P}, {D}, {Q}, {s}), trend={trend_code}, '
             f'enforce_stationarity={bool(constrain)}, enforce_invertibility={bool(constrain)}).fit(method_kwargs={{"maxiter": {int(maxiter or 200)}}})')
    c.append('print(res.summary())')
    if intercept and mu_factor != 1:
        c.append(f'# JMP\'s Intercept (the mean of the differenced series) is the trend coefficient times {mu_factor}')
    if h:
        c.append(f'print(res.get_forecast({h}{", exog=X_future" if specs else ""}).summary_frame(alpha={1 - level:.6g}))')
    # the graphs: the model fitted as above, then its predictions over the slots of the series
    fit = []
    if specs:
        if held:
            fit.append('X_all = pd.DataFrame({' + ', '.join(cols_code) + '}); X = X_all.loc[y.index]   # the inputs, lagged as in the model')
        else:
            fit.append('X = pd.DataFrame({' + ', '.join(cols_code) + '})   # the inputs, lagged as in the model')
        fit.append(f'yf, Xf = y.iloc[{start}:], X.iloc[{start}:]   # the first {start} have no lagged inputs' if start else 'yf, Xf = y, X')
        if h:
            fit.append(x_future if held else 'X_future = pd.DataFrame({' + ', '.join(f'{json.dumps(nm)}: {[_f(v) for v in Ef[:, j]]}' for j, nm in enumerate(xnames)) + '})   # the inputs of the forecast periods')
    else:
        fit.append('yf = y   # the series the model is fitted to')
    fit += [f'res = ARIMA(yf{", exog=Xf" if specs else ""}, order=({p}, {d}, {q}), seasonal_order=({P}, {D}, {Q}, {s}), trend={trend_code}, '
            f'enforce_stationarity={bool(constrain)}, enforce_invertibility={bool(constrain)}).fit(method_kwargs={{"maxiter": {int(maxiter or 200)}}})',
            _z_line(level), 'fv = np.asarray(res.fittedvalues, dtype=float)',
            'ok = yf.notna().to_numpy() & (np.arange(len(yf)) >= res.loglikelihood_burn) & np.isfinite(fv)   # the predictions the fit statistics take',
            'se = np.asarray(res.get_prediction().se_mean, dtype=float)']
    fit += _band_lines(resid='np.asarray(res.resid, dtype=float)')
    if start:
        fit.append(f'fitted, fit_lo, fit_hi, resid = (np.r_[np.full({start}, np.nan), v] for v in (fitted, fit_lo, fit_hi, resid))   # on the slots of the series')
    if h:
        fit += [f'fc = res.get_forecast({h}{", exog=X_future" if specs else ""})',
                f'f_mean, (f_lower, f_upper) = fc.predicted_mean.to_numpy(), fc.conf_int(alpha={1 - level:.6g}).to_numpy().T', _future_line(S, h)]
    plot_code, plot_frag = _model_plots(S, table_name, where, name, ['from statsmodels.tsa.arima.model import ARIMA'], fit, h, nlags)
    return _model_out(S, 'arima', name, pad(fitted), pad(resid), pad(fit_se), level, fcd, st, summary,
                      {'columns': 'arima', 'rows': rows_p}, nlags, p + q + P + Q, notes, '\n'.join(c),
                      plot_code=plot_code, plot_frag=plot_frag,
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


def smoothing_name(method, s=12, multiplicative=False, weights=None, boxcox=None):
    """JMP's names; a model with Custom constraints or a Box-Cox
    transformation says so, so that two fits of one method differ."""
    label = SMOOTHERS[method][0]
    if method == 'winters' and multiplicative:
        label = 'Winters Method (Multiplicative)'
    name = f'{label}({s})' if method in ('seasonal', 'winters') else label
    extra = []
    for kk, (mode, a, b) in (weights or {}).items():
        sym = WEIGHT_SYMBOLS[kk]
        if mode == 'fix':
            extra.append(f'{sym} = {a:g}')
        elif mode == 'bound':
            extra.append(f'{sym} in [{a:g}, {b:g}]')
    if boxcox is not None:
        extra.append(f'Box-Cox λ = {boxcox:g}')
    return f'{name}, {", ".join(extra)}' if extra else name


WEIGHT_SYMBOLS = {'alpha': 'α', 'gamma': 'γ', 'phi': 'φ', 'delta': 'δ'}


def _search_alpha(fit_at, lo, hi):
    """The alpha in [lo, hi] with the least sum of squared one-step errors:
    minimize_scalar's bounded search, or a bound itself (the search only
    comes near a bound, where a constrained optimum often is)."""
    from scipy.optimize import minimize_scalar
    opt = minimize_scalar(lambda a: fit_at(a).sse, bounds=(lo, hi), method='bounded', options={'xatol': 1e-7})
    return float(min([float(opt.x), lo, hi], key=lambda a: fit_at(a).sse))


def smoothing_weights(method, weights):
    """JMP's Custom constraints as {weight: (mode, a, b)}: ('fix', value,
    None) or ('bound', lower, upper), within 0 and 1 (statsmodels'
    holtwinters takes no weight outside them); the weights left out are free
    within 0 and 1 (Zero To One). An error message for what is not
    possible."""
    out = {}
    keys = SMOOTHERS[method][1]
    for kk, spec in (weights or {}).items():
        if kk not in keys or not isinstance(spec, dict):
            continue
        if spec.get('fix') is not None:
            v = float(spec['fix'])
            if not 0 <= v <= 1 or (kk == 'alpha' and v <= 0):
                return None, f'{WEIGHT_SYMBOLS[kk]} fixed at {v:g}: a value within 0 and 1' + (' and above 0' if kk == 'alpha' else '')
            out[kk] = ('fix', v, None)
        elif spec.get('lo') is not None or spec.get('hi') is not None:
            lo = float(spec['lo']) if spec.get('lo') is not None else 0.0
            hi = float(spec['hi']) if spec.get('hi') is not None else 1.0
            if not 0 <= lo < hi <= 1:
                return None, f'{WEIGHT_SYMBOLS[kk]} bounded by {lo:g} and {hi:g}: bounds within 0 and 1, the lower below the upper'
            if (lo, hi) != (0.0, 1.0):
                out[kk] = ('bound', lo, hi)
    return out, None


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


def _hw_model(x, method, s, multiplicative, bounds=None, **init):
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    trend = 'add' if method in ('double', 'linear', 'damped', 'winters') else None
    seas = ('mul' if multiplicative else 'add') if method in ('seasonal', 'winters') else None
    kw = {'trend': trend, 'damped_trend': method == 'damped', 'seasonal': seas, 'seasonal_periods': s if seas else None}
    if init:
        return ExponentialSmoothing(x, initialization_method='known', **kw, **init)
    b = {'damping_trend': (0.0, 1.0)} if method == 'damped' else {}
    b.update(bounds or {})
    if b:
        kw['bounds'] = b
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
           nlags=25, where=None, table_name='data', holdback=0, cut=0, season=0, weights=None, boxcox=None):
    """JMP's smoothing models with statsmodels' holtwinters: the weights and the
    starting states chosen to minimise the sum of squared one-step errors
    (initialization_method='estimated'); JMP's prediction intervals from the
    moving-average weights of the equivalent ARIMA model.

    weights: JMP's Custom constraints, {weight: {'fix': v} or {'lo': a, 'hi':
    b}} for alpha, gamma, phi and delta (Zero To One, the default, leaves them
    free within 0 and 1). statsmodels takes a fixed or bounded alpha, gamma
    and phi as they are; its seasonal weight is delta (1 - alpha), so a fixed
    or bounded delta with alpha free is fitted by a search over alpha, the
    rest estimated for each alpha. boxcox: a lambda; the model is fitted to
    the Box-Cox transform (x^lambda - 1)/lambda (log x at 0), and the
    predictions, forecasts and limits are transformed back."""
    from scipy.special import boxcox as bc, inv_boxcox
    from statsmodels.tools.numdiff import approx_hess3
    if method not in SMOOTHERS:
        return {'error': f'no smoothing model {method!r}'}
    try:
        S = load(table, y, time, rows, excluded, holdback=holdback, cut=cut, season=season)
    except NoSeries as e:
        return {'error': str(e)}
    s = int(s or 0)
    seasonal = method in ('seasonal', 'winters')
    mult = bool(multiplicative) and method == 'winters'
    if seasonal and s < 2:
        return {'error': 'a seasonal smoothing model needs at least 2 observations per period'}
    W, werr = smoothing_weights(method, weights)
    if werr:
        return {'error': werr}
    lam = None if boxcox in (None, '') else float(boxcox)
    x, miss = _filled(S)
    n = len(x)
    need = 2 * s + 2 if seasonal else 6
    if n < need:
        return {'error': f'too few observations ({n}) for this model; it needs {need}'}
    if lam is not None and not (x > 0).all():
        return {'error': 'the Box-Cox transformation needs every value above zero'}
    xt = bc(x, lam) if lam is not None else x          # the series the model is fitted to
    if mult and not (xt > 0).all():
        return {'error': 'the multiplicative Winters method needs every value above zero' + (' after the Box-Cox transformation' if lam is not None else '')}
    level = float(level or 0.95)
    h = max(0, int(h or 0))
    notes = []
    keys = SMOOTHERS[method][1]
    mode = {kk: W.get(kk, ('free', 0.0, 1.0)) for kk in keys}
    fixed_sm, bounds_sm = {}, {}
    SMK = {'alpha': 'smoothing_level', 'gamma': 'smoothing_trend', 'phi': 'damping_trend'}
    for kk in ('alpha', 'gamma', 'phi'):
        if kk in keys and method != 'double':
            m_, lo_, hi_ = mode[kk]
            if m_ == 'fix':
                fixed_sm[SMK[kk]] = lo_
            elif m_ == 'bound':
                bounds_sm[SMK[kk]] = (lo_, hi_)
    dm = mode.get('delta', ('free', 0.0, 1.0))
    a_fixed = mode['alpha'][1] if mode['alpha'][0] == 'fix' else None
    if seasonal and dm[0] != 'free' and a_fixed is not None:
        if dm[0] == 'fix':
            fixed_sm['smoothing_seasonal'] = dm[1] * (1 - a_fixed)
        else:
            bounds_sm['smoothing_seasonal'] = (dm[1] * (1 - a_fixed), dm[2] * (1 - a_fixed))
    nested = seasonal and dm[0] != 'free' and a_fixed is None      # delta constrained, alpha free: a search over alpha
    a_lo, a_hi = (max(1e-4, mode['alpha'][1]), min(1 - 1e-6, mode['alpha'][2])) if mode['alpha'][0] == 'bound' else (1e-4, 1 - 1e-6)
    try:
        with _quiet():
            if method == 'double':
                def fit_at(a):
                    m = _hw_model(xt, 'linear', s, False)
                    with m.fix_params({'smoothing_level': a * (2 - a), 'smoothing_trend': a / (2 - a)}):
                        return m.fit()
                if a_fixed is not None:
                    th = {'alpha': a_fixed}
                else:
                    th = {'alpha': _search_alpha(fit_at, a_lo, a_hi)}
                res = fit_at(th['alpha'])
            else:
                if nested:
                    def fit_at(a):
                        fx, bd = dict(fixed_sm, smoothing_level=a), {k2: v2 for k2, v2 in bounds_sm.items() if k2 != 'smoothing_level'}
                        if dm[0] == 'fix':
                            fx['smoothing_seasonal'] = dm[1] * (1 - a)
                        else:
                            bd['smoothing_seasonal'] = (dm[1] * (1 - a), dm[2] * (1 - a))
                        m = _hw_model(xt, method, s, mult, bounds=bd)
                        with m.fix_params(fx):
                            return m.fit()
                    res = fit_at(_search_alpha(fit_at, a_lo, a_hi))
                else:
                    m = _hw_model(xt, method, s, mult, bounds=bounds_sm)
                    if fixed_sm:
                        with m.fix_params(fixed_sm):
                            res = m.fit()
                    else:
                        res = m.fit()
                pv = res.params
                th = {'alpha': float(pv['smoothing_level'])}
                if method in ('linear', 'damped', 'winters'):
                    th['gamma'] = float(pv['smoothing_trend'])
                if method == 'damped':
                    th['phi'] = float(pv['damping_trend'])
                if seasonal:
                    th['delta'] = float(pv['smoothing_seasonal']) / (1 - th['alpha']) if th['alpha'] < 1 else 0.0
    except ValueError as e:        # statsmodels refuses constraints it cannot meet (a trend weight fixed above the level weight ...)
        return {'error': f'statsmodels cannot fit these constraints: {e}'}
    pv = res.params
    fitted_t = np.array(res.fittedvalues, dtype=float)       # on the scale of the fit
    fitted = inv_boxcox(fitted_t, lam) if lam is not None else fitted_t
    valid = ~miss & np.isfinite(fitted)
    k = sum(1 for kk in keys if mode[kk][0] != 'fix')        # the weights estimated
    sse_t = float(np.sum((xt - fitted_t)[valid] ** 2))
    nv = int(valid.sum())
    m2ll = nv * (math.log(2 * math.pi * sse_t / nv) + 1)
    if lam is not None:
        m2ll -= 2 * (lam - 1) * float(np.sum(np.log(x[valid])))   # the Jacobian: the likelihood of the values themselves
    st = _fit_stats(x, fitted, valid, k, m2ll)
    sig_t = math.sqrt(sse_t / (nv - k)) if nv > k else float('nan')     # the one-step errors' standard deviation, on the fit's scale
    # standard errors: the Hessian of the Gaussian log-likelihood of the
    # one-step errors in the weights, the starting states held
    init = {'initial_level': float(pv['initial_level'])}
    if method in ('double', 'linear', 'damped', 'winters'):
        init['initial_trend'] = float(pv['initial_trend'])
    if seasonal:
        init['initial_seasonal'] = np.asarray(pv['initial_seasons'], dtype=float)
    free = [kk for kk in keys if mode[kk][0] != 'fix' and max(1e-5, mode[kk][1] + 1e-5) < th[kk] < min(1 - 1e-5, mode[kk][2] - 1e-5)]

    def llf(v):
        t2 = dict(th)
        t2.update(zip(free, v))
        with _quiet():
            r2 = _hw_model(xt, 'linear' if method == 'double' else method, s, mult, **init).fit(**_sm_values(method, t2), optimized=False)
        e = (xt - np.asarray(r2.fittedvalues, dtype=float))[valid]
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
        m_ = mode[kk][0]
        rows_p.append({'term': label, 'estimate': _f(e), 'se': se[kk], 't': _f(tt[0]) if m_ != 'fix' else None, 'p': _f(pp[0]) if m_ != 'fix' else None,
                       'bound': kk not in free, 'constraint': 'Fixed' if m_ == 'fix' else f'Bounded [{mode[kk][1]:g}, {mode[kk][2]:g}]' if m_ == 'bound' else 'Zero To One'})
    smv = _sm_values(method, th)
    notes.append('statsmodels\' parameters: ' + ', '.join(f'{kk} = {v:.6g}' for kk, v in smv.items()) +
                 (f'; starting level {init["initial_level"]:.6g}' + (f', trend {init["initial_trend"]:.6g}' if 'initial_trend' in init else '') +
                  (f' and {s} seasonal states' if seasonal else '') + ', estimated with the weights.'))
    notes.append('The weights and the starting states minimise the sum of squared one-step errors (holtwinters, initialization_method '
                 '"estimated"); JMP fits the equivalent ARIMA model, so its estimates, and above all its starting values, differ. '
                 'k counts the smoothing weights estimated, as JMP does; the Std Errors come from the Hessian of the likelihood with the '
                 'starting states held.')
    if W:
        parts = [f'{WEIGHT_NAMES[kk].lower()} fixed at {mode[kk][1]:g}' if mode[kk][0] == 'fix' else f'{WEIGHT_NAMES[kk].lower()} within {mode[kk][1]:g} and {mode[kk][2]:g}'
                 for kk in keys if mode[kk][0] != 'free']
        notes.append('Custom constraints: ' + '; '.join(parts) + ('; the others within 0 and 1 (Zero To One).' if len(parts) < len(keys) else '.')
                     + (' statsmodels\' seasonal weight is δ(1 − α), so α is searched for (minimize_scalar), the other weights estimated at each α.' if nested else ''))
    if any(r['bound'] and mode[kk][0] != 'fix' for r, kk in zip(rows_p, keys)):
        notes.append('A weight at the edge of its range has no standard error.')
    if method == 'linear' or method == 'damped' or method == 'winters':
        notes.append('statsmodels keeps the trend weight at or below the level weight, and the seasonal weight at or below 1 − α.')
    if lam is not None:
        notes.append(f'Box-Cox transformation, λ = {lam:g}: the model is fitted to {"log y" if lam == 0 else f"(y^{lam:g} − 1)/{lam:g}"}; the predictions, the forecasts and their '
                     'limits are transformed back (so the forecasts are medians, not means), the Std Err Pred by the delta method. The fit statistics are those of '
                     'the values themselves: the residuals on their scale, and −2LogLikelihood with the Jacobian of the transformation, so that AIC compares with '
                     'the other models\'.')
    if miss.any():
        notes.append(f'{int(miss.sum())} missing value{"s" if miss.sum() > 1 else ""} filled by linear interpolation for the fit; they are left out of the fit statistics.')
    z = stats.norm.ppf(0.5 + level / 2)

    def back(v):
        return inv_boxcox(np.asarray(v, dtype=float), lam) if lam is not None else np.asarray(v, dtype=float)

    def slope(v):            # d back / d v, for the delta method
        v = np.asarray(v, dtype=float)
        if lam is None:
            return np.ones_like(v)
        return np.exp(v) if lam == 0 else np.power(np.maximum(1 + lam * v, 0), 1 / lam - 1)

    with _quiet():
        if h:
            mean_t = np.asarray(res.forecast(h), dtype=float)
            if mult:
                sims = np.asarray(res.simulate(h, repetitions=2000, error='add', random_state=SEED), dtype=float).reshape(h, -1)
                lo_t = np.quantile(sims, 0.5 - level / 2, axis=1)
                hi_t = np.quantile(sims, 0.5 + level / 2, axis=1)
                fse_t = sims.std(axis=1, ddof=1)
                notes.append('Prediction intervals of the multiplicative model: quantiles of 2000 simulated paths (statsmodels\' simulate, a fixed seed).')
            else:
                fse_t = sig_t * np.sqrt(psi_variance(method, th, s, h))
                lo_t, hi_t = mean_t - z * fse_t, mean_t + z * fse_t
            fcd = _forecast(S, h, back(mean_t), fse_t * slope(mean_t), back(lo_t), back(hi_t))
        else:
            fcd = _forecast(S, 0, [], [], [], [])
    fitted_v = np.where(valid, fitted, np.nan)
    resid = np.where(valid, x - fitted, np.nan)
    fit_se = np.where(valid, sig_t * slope(fitted_t), np.nan)
    fit_lo = np.where(valid, back(fitted_t - z * sig_t), np.nan)
    fit_hi = np.where(valid, back(fitted_t + z * sig_t), np.nan)
    summary = [['DF', st['df'], 'int'], ['Sum of Squared Errors', st['sse']], ['Variance Estimate', st['variance']],
               ['Standard Deviation', st['sd']], ["Akaike's 'A' Information Criterion", st['aic']], ["Schwarz's Bayesian Criterion", st['sbc']],
               ['AICc', st['aicc']], ['RSquare', st['rsquare']], ['RSquare Adj', st['rsquare_adj']], ['MAPE', st['mape']], ['MAE', st['mae']],
               ['−2LogLikelihood', st['m2ll']]]
    if lam is not None:
        summary.append(['Box-Cox λ', lam])
    name = smoothing_name(method, s, mult, W, lam)
    # the code: the model fitted as the report fits it
    imports = ['from statsmodels.tsa.holtwinters import ExponentialSmoothing']
    if method == 'double' or nested:
        imports.append('from scipy.optimize import minimize_scalar')
    if lam is not None:
        imports.append('from scipy.special import boxcox, inv_boxcox')
    trend = 'add' if method in ('double', 'linear', 'damped', 'winters') else None
    seas = ('mul' if mult else 'add') if seasonal else None

    def maker(series, bounds_expr):
        extra = (f', seasonal_periods={s}' if seasonal else '') + ', initialization_method="estimated"'
        if bounds_expr:
            extra += f', bounds={bounds_expr}'
        return f'ExponentialSmoothing({series}, trend={trend!r}, damped_trend={method == "damped"}, seasonal={seas!r}{extra})'

    def bounds_text(bd, dyn=None):
        items = ([('damping_trend', (0.0, 1.0))] if method == 'damped' and 'damping_trend' not in bd else []) + list(bd.items())
        parts = [f'"{k2}": ({v2[0]!r}, {v2[1]!r})' for k2, v2 in items]
        if dyn:
            parts.append(dyn)
        return '{' + ', '.join(parts) + '}' if parts else ''

    def fit_lines(series):
        """The fit, as the report does it, on the series named so."""
        if method == 'double':
            head = ['def fit_at(a):   # Brown\'s method is Holt\'s with level a(2 − a) and trend a/(2 − a)',
                    f'    m = {maker(series, bounds_text({}))}',
                    '    with m.fix_params({"smoothing_level": a * (2 - a), "smoothing_trend": a / (2 - a)}):',
                    '        return m.fit()']
            if a_fixed is not None:
                return head + [f'a = {a_fixed!r}   # α fixed (Custom)', 'res = fit_at(a)']
            return head + [f'a = minimize_scalar(lambda a: fit_at(a).sse, bounds=({a_lo!r}, {a_hi!r}), method="bounded", options={{"xatol": 1e-7}}).x   # the least squared one-step errors',
                           f'a = min([a, {a_lo!r}, {a_hi!r}], key=lambda a: fit_at(a).sse)   # or a bound, where the search only comes near it',
                           'res = fit_at(a)']
        if nested:
            other = {k2: v2 for k2, v2 in bounds_sm.items() if k2 != 'smoothing_level'}
            fx = ', '.join([f'"{k2}": {v2!r}' for k2, v2 in fixed_sm.items()] + ['"smoothing_level": a'] + ([f'"smoothing_seasonal": {dm[1]!r} * (1 - a)'] if dm[0] == 'fix' else []))
            dyn = None if dm[0] == 'fix' else f'"smoothing_seasonal": ({dm[1]!r} * (1 - a), {dm[2]!r} * (1 - a))'
            return ['def fit_at(a):   # α held at a; statsmodels\' seasonal weight is δ(1 − α)',
                    f'    m = {maker(series, bounds_text(other, dyn))}',
                    f'    with m.fix_params({{{fx}}}):',
                    '        return m.fit()',
                    f'a = minimize_scalar(lambda a: fit_at(a).sse, bounds=({a_lo!r}, {a_hi!r}), method="bounded", options={{"xatol": 1e-7}}).x   # α, the others estimated at each α',
                    f'a = min([a, {a_lo!r}, {a_hi!r}], key=lambda a: fit_at(a).sse)   # or a bound, where the search only comes near it',
                    'res = fit_at(a)']
        mk = maker(series, bounds_text(bounds_sm))
        if fixed_sm:
            fx = ', '.join(f'"{k2}": {v2!r}' for k2, v2 in fixed_sm.items())
            return [f'm = {mk}', f'with m.fix_params({{{fx}}}):   # the weights fixed (Custom)', '    res = m.fit()']
        return [f'res = {mk}.fit()']

    c = _code_series(S, table_name, where, imports)
    if miss.any():
        c.append('y = y.interpolate(limit_direction="both")')
    if lam is not None:
        c.append(f'lam = {lam!r}; yb = pd.Series(boxcox(y.to_numpy(), lam), index=y.index)   # the Box-Cox transformation')
    c += fit_lines('yb' if lam is not None else 'y')
    c += ['print(res.params_formatted)', (f'print(inv_boxcox(np.asarray(res.forecast({h})), lam))   # transformed back' if lam is not None else f'print(res.forecast({h}))') if h else 'print(res.fittedvalues)']
    # the graphs: the model fitted as above; the intervals from its moving-average weights, as the report's
    fit = ['yi = y.interpolate(limit_direction="both")   # the missing values filled for the fit' if miss.any() else 'yi = y']
    if lam is not None:
        fit.append(f'lam = {lam!r}; yb = pd.Series(boxcox(yi.to_numpy(), lam), index=yi.index)   # the Box-Cox transformation, the scale of the fit')
    fit += fit_lines('yb' if lam is not None else 'yi')
    yfit = 'yb' if lam is not None else 'yi'
    fit += [_z_line(level), 'fv = np.asarray(res.fittedvalues, dtype=float)' + ('   # on the scale of the fit' if lam is not None else ''),
            'ok = y.notna().to_numpy() & np.isfinite(fv)   # the one-step errors the fit statistics take',
            f'sd = np.sqrt(np.sum(({yfit}.to_numpy() - fv)[ok] ** 2) / (ok.sum() - {k}))   # the standard deviation of the one-step errors ({_plural(k, "weight")} estimated)']
    if lam is not None:
        fit += ['fb = np.where(ok, fv, np.nan)   # the one-step predictions on the scale of the fit',
                'fitted, fit_lo, fit_hi = inv_boxcox(fb, lam), inv_boxcox(fb - z * sd, lam), inv_boxcox(fb + z * sd, lam)   # and their limits, transformed back',
                'resid = np.where(ok, yi.to_numpy() - fitted, np.nan)']
    else:
        fit += _band_lines(se='sd', resid='yi.to_numpy() - fv')
    if h:
        fit.append(f'f_mean = np.asarray(res.forecast({h}), dtype=float)')
        if mult:
            fit += [f'sims = np.asarray(res.simulate({h}, repetitions=2000, error="add", random_state={SEED}), dtype=float).reshape({h}, -1)',
                    f'f_lower, f_upper = np.quantile(sims, [{0.5 - level / 2:.6g}, {0.5 + level / 2:.6g}], axis=1)   # the quantiles of 2000 simulated paths (a fixed seed)']
        else:
            a_ = 'a' if method == 'double' else 'res.params["smoothing_level"]'
            psi = {'simple': f'np.full({h - 1}, {a_})', 'double': 'a * (2 + (j - 1) * a)',
                   'linear': f'{a_} * (1 + j * res.params["smoothing_trend"])',
                   'damped': f'{a_} * (1 + res.params["smoothing_trend"] * np.cumsum(res.params["damping_trend"] ** j))',
                   'seasonal': f'{a_} + (j % {s} == 0) * res.params["smoothing_seasonal"]',
                   'winters': f'{a_} * (1 + j * res.params["smoothing_trend"]) + (j % {s} == 0) * res.params["smoothing_seasonal"]'}[method]
            fit += [f'j = np.arange(1, {h})   # the moving-average weights ψ_j of the model\'s ARIMA form (JMP\'s statistical details)',
                    f'psi = {psi}',
                    'f_se = sd * np.sqrt(np.r_[1.0, 1.0 + np.cumsum(psi ** 2)])   # the h-step forecast error: σ²(1 + Σ ψ_j²)',
                    'f_lower, f_upper = f_mean - z * f_se, f_mean + z * f_se']
        if lam is not None:
            fit.append('f_mean, f_lower, f_upper = (inv_boxcox(v, lam) for v in (f_mean, f_lower, f_upper))   # transformed back')
        fit.append(_future_line(S, h))
    plot_code, plot_frag = _model_plots(S, table_name, where, name, imports, fit, h, nlags)
    return _model_out(S, 'smooth', name, fitted_v, resid, fit_se, level, fcd, st, summary,
                      {'columns': 'smooth', 'rows': rows_p}, nlags, k, notes, '\n'.join(c), plot_code=plot_code, plot_frag=plot_frag,
                      weights=th, fit_lo_override=[_arr(fit_lo), _arr(fit_hi)] if lam is not None else None,
                      sm={'aic': _f(res.aic), 'aicc': _f(res.aicc), 'bic': _f(res.bic), 'sse': _f(res.sse)},
                      spec={'method': method, 's': s, 'multiplicative': mult, 'weights': {kk: list(v) for kk, v in W.items()}, 'boxcox': lam})


# ---- benchmarks: Naive, Seasonal Naive, Drift ------------------------------------------------------

BENCH_NAMES = {'naive': 'Naive', 'snaive': 'Seasonal Naive', 'drift': 'Drift'}


def bench_name(method, s=12):
    return f'Seasonal Naive({s})' if method == 'snaive' else BENCH_NAMES.get(method, method)


def _last_valid(v):
    ok = np.flatnonzero(np.isfinite(v))
    return (int(ok[0]), int(ok[-1])) if len(ok) else (None, None)


@api('timeseries.benchmark')
@_quietly
def benchmark(table, y, time=None, rows=None, excluded=None, method='naive', s=12, level=0.95, h=25, nlags=25, where=None,
              table_name='data', holdback=0, cut=0, season=0):
    """The benchmarks a forecasting model should beat (Hyndman and
    Athanasopoulos, Forecasting: Principles and Practice, 5.2 and 5.5):
    Naive, every forecast the last value (a random walk); Seasonal Naive, the
    value of the same season one period earlier; Drift, the last value plus
    h times the average change b = (y_T - y_1)/(T - 1). The one-step-ahead
    predictions are y_{t-1}, y_{t-s} and y_{t-1} + b. Standard errors:
    sigma sqrt(h), sigma sqrt(k + 1) with k = floor((h - 1)/s), and
    sigma sqrt(h (1 + h/(T - 1))), the drift's own uncertainty included;
    sigma^2 is the mean squared one-step error (over n - 1 for Drift, which
    estimates b)."""
    if method not in BENCH_NAMES:
        return {'error': f'no benchmark {method!r}'}
    try:
        S = load(table, y, time, rows, excluded, holdback=holdback, cut=cut, season=season)
    except NoSeries as e:
        return {'error': str(e)}
    s = int(s or 0)
    lag = s if method == 'snaive' else 1
    if method == 'snaive' and s < 2:
        return {'error': 'Seasonal Naive needs a seasonal period of at least 2'}
    v = np.asarray(S.y, dtype=float)
    n = len(v)
    i0, i1 = _last_valid(v)
    if i1 is None or n < lag + 3:
        return {'error': f'too few observations ({n}) for this benchmark'}
    level = float(level or 0.95)
    h = max(0, int(h or 0))
    fitted = np.full(n, np.nan)
    fitted[lag:] = v[:-lag]
    k = 0
    b = b_se = None
    if method == 'drift':
        if i1 <= i0:
            return {'error': 'Drift needs two values'}
        b = (v[i1] - v[i0]) / (i1 - i0)
        fitted = fitted + b
        k = 1
    valid = np.isfinite(v) & np.isfinite(fitted)
    nv = int(valid.sum())
    if nv - k < 2:
        return {'error': f'too few one-step errors ({nv}) for this benchmark'}
    sse = float(np.sum((v - fitted)[valid] ** 2))
    m2ll = nv * (math.log(2 * math.pi * sse / nv) + 1) if sse > 0 else float('nan')
    st = _fit_stats(v, fitted, valid, k, m2ll)
    sig = st['sd'] if st['sd'] is not None else float('nan')
    notes = []
    rows_p = []
    span = i1 - i0
    if method == 'drift':
        b_se = sig / math.sqrt(span)
        tt, pp = _pvals_t([b], [b_se], st['df'] or 1)
        rows_p.append({'term': 'Drift (b)', 'estimate': _f(b), 'se': _f(b_se), 't': _f(tt[0]), 'p': _f(pp[0])})
    z = stats.norm.ppf(0.5 + level / 2)
    if h:
        steps = n - 1 - i1 + np.arange(1, h + 1)          # the periods from the last value
        if method == 'naive':
            mean, fse = np.full(h, v[i1]), sig * np.sqrt(steps)
        elif method == 'drift':
            mean, fse = v[i1] + steps * b, sig * np.sqrt(steps * (1 + steps / span))
        else:
            mean = np.array([v[n - lag + ((j - 1) % lag)] for j in range(1, h + 1)], dtype=float)
            fse = sig * np.sqrt(np.floor((np.arange(1, h + 1) - 1) / lag) + 1)
        fcd = _forecast(S, h, mean, fse, mean - z * fse, mean + z * fse)
    else:
        fcd = _forecast(S, 0, [], [], [], [])
    what = {'naive': 'the last value', 'snaive': f'the value of the same season one period ({s}) before', 'drift': 'the last value plus the average change per period'}[method]
    notes.append(f'{bench_name(method, s)}: every forecast is {what}; the one-step-ahead predictions in the sample are '
                 + {'naive': 'the value before', 'snaive': f'the value {s} periods before', 'drift': 'the value before plus the drift b = (y_T − y_1)/(T − 1), from all the data'}[method] + '. '
                 + {'naive': 'Standard errors σ√h, those of a random walk.', 'snaive': 'Standard errors σ√(k + 1), k the whole periods before the horizon (floor((h − 1)/s)).',
                    'drift': 'Standard errors σ√(h(1 + h/(T − 1))): the random walk\'s, and the uncertainty of b.'}[method]
                 + ' A benchmark every model should beat (Hyndman and Athanasopoulos, Forecasting: Principles and Practice).')
    notes.append(f'σ² is the mean squared one-step error{" over n − 1 (b is estimated)" if k else ""}; k = {k}, n = {nv}.')
    if i1 < n - 1:
        notes.append(f'The forecasts go on from the last value present, {_plural(n - 1 - i1, "slot")} before the end.')
    summary = [['DF', st['df'], 'int'], ['Sum of Squared Errors', st['sse']], ['Variance Estimate', st['variance']], ['Standard Deviation', st['sd']],
               ["Akaike's 'A' Information Criterion", st['aic']], ["Schwarz's Bayesian Criterion", st['sbc']], ['AICc', st['aicc']],
               ['RSquare', st['rsquare']], ['RSquare Adj', st['rsquare_adj']], ['MAPE', st['mape']], ['MAE', st['mae']], ['−2LogLikelihood', st['m2ll']]]
    name = bench_name(method, s)
    # the code: the one-step predictions, the forecasts and their standard errors, by the formulas
    lines = ['yv = y.to_numpy()', f'fv = np.r_[np.full({lag}, np.nan), yv[:-{lag}]]   # the value {lag} period{"s" if lag > 1 else ""} before',
             'ok_ = np.flatnonzero(np.isfinite(yv)); i0, i1 = ok_[0], ok_[-1]   # the first and the last value present']
    if method == 'drift':
        lines += ['b = (yv[i1] - yv[i0]) / (i1 - i0)   # the drift: the average change per period', 'fv = fv + b']
    lines += ['ok = np.isfinite(yv) & np.isfinite(fv)   # the one-step errors',
              f'sd = np.sqrt(np.sum((yv - fv)[ok] ** 2) / (ok.sum() - {k}))   # σ: the root mean squared one-step error{" (b estimated)" if k else ""}']
    fc_lines = []
    if h:
        fc_lines.append(f'steps = len(yv) - 1 - i1 + np.arange(1, {h + 1})   # the periods from the last value')
        if method == 'naive':
            fc_lines += ['f_mean = np.full(len(steps), yv[i1]); f_se = sd * np.sqrt(steps)   # a random walk']
        elif method == 'drift':
            fc_lines += ['f_mean = yv[i1] + steps * b; f_se = sd * np.sqrt(steps * (1 + steps / (i1 - i0)))   # a random walk with drift, b estimated']
        else:
            fc_lines += [f'f_mean = np.array([yv[len(yv) - {lag} + (j - 1) % {lag}] for j in range(1, {h + 1})])   # the same season one period before',
                         f'f_se = sd * np.sqrt(np.floor((np.arange(1, {h + 1}) - 1) / {lag}) + 1)']
        fc_lines.append('f_lower, f_upper = f_mean - z * f_se, f_mean + z * f_se')
    c = _code_series(S, table_name, where, ['from scipy import stats']) + lines + [_z_line(level), *fc_lines,
                                                                                 'print(pd.DataFrame({"forecast": f_mean, "lower": f_lower, "upper": f_upper}))' if h else 'print(sd)']
    fit = [*lines, _z_line(level), *_band_lines(se='sd', resid='yv - fv'), *fc_lines, *([_future_line(S, h)] if h else [])]
    plot_code, plot_frag = _model_plots(S, table_name, where, name, [], fit, h, nlags)
    return _model_out(S, 'bench', name, np.where(valid, fitted, np.nan), np.where(valid, v - fitted, np.nan), np.where(valid, sig, np.nan), level, fcd, st,
                      summary, {'columns': 'smooth', 'rows': rows_p}, nlags, 0, notes, '\n'.join(c), plot_code=plot_code, plot_frag=plot_frag,
                      drift=_f(b), spec={'method': method, 's': s})


# ---- Simple Moving Average ---------------------------------------------------------------------------

SMA_CENTERING = {'none': 'No Centering', 'centered': 'Centered', 'double': 'Centered and Double Smoothed'}


def sma_name(width, centering='none'):
    return f'Simple Moving Average({width}{", centered" if centering == "centered" else ", centered and double smoothed" if centering == "double" else ""})'


def moving_average(v, w, centering='none'):
    """The moving average of width w over v (NaN where a window is not
    whole): trailing, the value and the w - 1 before it; centered, the
    window around the value (for an even width one more value before it
    than after, as pandas' rolling(center=True)); double, for an even width
    the mean of the two nearly centered windows, weights 1/2w at the ends
    and 1/w inside (the 2 x w moving average of classical decomposition)."""
    x = pd.Series(np.asarray(v, dtype=float))
    if centering == 'double':
        m = x.rolling(w, min_periods=w).mean()
        return ((m.shift(-(w // 2)) + m.shift(-(w // 2 - 1))) / 2).to_numpy()
    return x.rolling(w, min_periods=w, center=centering == 'centered').mean().to_numpy()


@api('timeseries.sma')
@_quietly
def sma(table, y, time=None, rows=None, excluded=None, width=3, centering='none', level=0.95, h=25, nlags=25, where=None,
        table_name='data', holdback=0, cut=0, season=0):
    """JMP's Simple Moving Average: the mean of w consecutive values, the
    smoothed series with No Centering (trailing), Centered, or Centered and
    Double Smoothed (an even width). As a forecast the average trails: the
    one-step-ahead prediction of y_t is the mean of the w values before it,
    and every forecast is the mean of the last w values, with the
    one-step errors' standard deviation (a level that stays where it is)."""
    try:
        S = load(table, y, time, rows, excluded, holdback=holdback, cut=cut, season=season)
    except NoSeries as e:
        return {'error': str(e)}
    w = int(width or 0)
    centering = centering if centering in SMA_CENTERING else 'none'
    if w < 1:
        return {'error': 'the width of the moving average must be at least 1'}
    if centering == 'double' and w % 2:
        return {'error': 'Centered and Double Smoothed is for an even width; an odd width centers on its own'}
    v = np.asarray(S.y, dtype=float)
    n = len(v)
    if n < w + 3:
        return {'error': f'too few observations ({n}) for a moving average of width {w}'}
    level = float(level or 0.95)
    h = max(0, int(h or 0))
    smoothed = moving_average(v, w, centering)
    trail = moving_average(v, w, 'none')
    fitted = np.r_[np.nan, trail[:-1]]                  # the mean of the w values before each one
    valid = np.isfinite(v) & np.isfinite(fitted)
    nv = int(valid.sum())
    if nv < 2:
        return {'error': 'too few whole windows for one-step predictions (missing values break the windows)'}
    sse = float(np.sum((v - fitted)[valid] ** 2))
    st = _fit_stats(v, fitted, valid, 0, nv * (math.log(2 * math.pi * sse / nv) + 1) if sse > 0 else float('nan'))
    sig = st['sd'] if st['sd'] is not None else float('nan')
    z = stats.norm.ppf(0.5 + level / 2)
    last = trail[-1]
    notes = []
    if h:
        if not np.isfinite(last):
            return {'error': f'the last {w} values have a missing value: no forecast'}
        mean, fse = np.full(h, last), np.full(h, sig)
        fcd = _forecast(S, h, mean, fse, mean - z * fse, mean + z * fse)
    else:
        fcd = _forecast(S, 0, [], [], [], [])
    how = {'none': 'the value and the ones before it (No Centering)', 'centered': 'centered on the value' + (' (an even width: one value more before it than after)' if w % 2 == 0 else ''),
           'double': f'the mean of the two nearly centered windows (weights 1/{2 * w} at the ends and 1/{w} inside)'}[centering]
    tail = f', {float(last):.6g}' if np.isfinite(last) else ' (none: the last window has a missing value)'
    notes.append(f'The smoothed series: the mean of {_plural(w, "consecutive value")}, {how}. As a forecast the average trails: the one-step-ahead '
                 f'prediction of each value is the mean of the {w} before it, and every forecast is the mean of the last {w}{tail}.')
    notes.append('The prediction interval is ±z times the one-step errors\' standard deviation at every horizon: right when the level stays where it is, '
                 'as the moving average assumes; a series that wanders gets wider errors further ahead. k = 0 (the width is chosen, not estimated). '
                 'A window with a missing value gives no average.')
    summary = [['DF', st['df'], 'int'], ['Sum of Squared Errors', st['sse']], ['Variance Estimate', st['variance']], ['Standard Deviation', st['sd']],
               ["Akaike's 'A' Information Criterion", st['aic']], ["Schwarz's Bayesian Criterion", st['sbc']], ['AICc', st['aicc']],
               ['RSquare', st['rsquare']], ['RSquare Adj', st['rsquare_adj']], ['MAPE', st['mape']], ['MAE', st['mae']], ['−2LogLikelihood', st['m2ll']],
               ['Width', w, 'int'], ['Centering', SMA_CENTERING[centering], 'text']]
    name = sma_name(w, centering)
    smooth_line = {'none': f'ma = y.rolling({w}).mean()   # No Centering: the value and the {w - 1} before it',
                   'centered': f'ma = y.rolling({w}, center=True).mean()   # Centered' + (' (an even width: one value more before than after)' if w % 2 == 0 else ''),
                   'double': f'm = y.rolling({w}).mean(); ma = (m.shift(-{w // 2}) + m.shift(-{w // 2 - 1})) / 2   # Centered and Double Smoothed: the two nearly centered windows'}[centering]
    base = [smooth_line, f'fv = y.rolling({w}).mean().shift(1).to_numpy()   # the one-step-ahead prediction: the mean of the {w} values before']
    fc_lines = [f'f_mean = np.full({h}, y.iloc[-{w}:].mean()); f_se = np.full({h}, sd)   # every forecast: the mean of the last {w}',
                'f_lower, f_upper = f_mean - z * f_se, f_mean + z * f_se'] if h else []
    common = ['ok = y.notna().to_numpy() & np.isfinite(fv)', 'sd = np.sqrt(np.mean((y.to_numpy() - fv)[ok] ** 2))   # the one-step errors\' standard deviation (k = 0)']
    c = _code_series(S, table_name, where, ['from scipy import stats']) + base + common + [_z_line(level), *fc_lines,
                                                                                         'print(ma); ' + ('print(pd.DataFrame({"forecast": f_mean, "lower": f_lower, "upper": f_upper}))' if h else 'print(sd)')]
    fit = [*base, *common, _z_line(level), *_band_lines(se='sd'), *fc_lines, *([_future_line(S, h)] if h else [])]
    plot_code, plot_frag = _model_plots(S, table_name, where, name, [], fit, h, nlags)
    head = _head(S, table_name, where, ['from scipy import stats'])
    plot_code['smoothed'] = [*head, *fit, '', SIZE, COLOR, 'fig, ax = plt.subplots(figsize=size, layout="constrained")',
                             _trace('t', 'y', lines=False) + '   # the data',
                             f'ax.plot(t, ma, color=color, linewidth={_pt(1.6)})   # the moving average',
                             *_labels(S, S.y_name, f'{name} smoothed series'), 'plt.show()']
    return _model_out(S, 'sma', name, np.where(valid, fitted, np.nan), np.where(valid, v - fitted, np.nan), np.where(valid, sig, np.nan), level, fcd, st,
                      summary, {'columns': 'smooth', 'rows': []}, nlags, 0, notes, '\n'.join(c), plot_code=plot_code, plot_frag=plot_frag,
                      smoothed=_arr(smoothed), width=w, centering=centering, spec={'width': w, 'centering': centering})


# ---- state space smoothing (ETSModel) ----------------------------------------------------------

ETS_NAMES = {'smoothing_level': 'Level Smoothing (α)', 'smoothing_trend': 'Trend Smoothing (β)', 'smoothing_seasonal': 'Seasonal Smoothing (γ)',
             'damping_trend': 'Damping (φ)', 'initial_level': 'Initial Level', 'initial_trend': 'Initial Trend'}


def ets_name(error, trend, seasonal, s=12):
    code = f'{"A" if error == "add" else "M"},{trend or "N"},{seasonal or "N"}'
    return f'State Space Smoothing ETS({code}){s if seasonal and seasonal != "N" else ""}'


@api('timeseries.ets')
@_quietly
def ets(table, y, time=None, rows=None, excluded=None, error='add', trend='N', seasonal='N', s=12, level=0.95, h=25, maxiter=1000,
        nlags=25, where=None, table_name='data', holdback=0, cut=0, season=0):
    """A state space smoothing model ETS(error, trend, seasonal) of Hyndman et
    al. (2008) by maximum likelihood (statsmodels' ETSModel)."""
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel
    try:
        S = load(table, y, time, rows, excluded, holdback=holdback, cut=cut, season=season)
    except NoSeries as e:
        return {'error': str(e)}
    error = 'mul' if error in ('mul', 'M') else 'add'
    trend = {'A': 'A', 'Ad': 'Ad', 'add': 'A', 'M': 'M', 'Md': 'Md', 'mul': 'M'}.get(trend, 'N')
    seasonal = {'A': 'A', 'M': 'M', 'add': 'A', 'mul': 'M'}.get(seasonal, 'N')
    s = int(s or 0)
    if seasonal != 'N' and s < 2:
        return {'error': 'a seasonal model needs at least 2 observations per period'}
    x, miss = _filled(S)
    n = len(x)
    mul_trend = trend in ('M', 'Md')
    if (error == 'mul' or seasonal == 'M' or mul_trend) and not (x > 0).all():
        return {'error': 'multiplicative errors, trend or seasonality need every value above zero'}
    if n < (2 * s + 4 if seasonal != 'N' else 8):
        return {'error': f'too few observations ({n}) for this model'}
    level = float(level or 0.95)
    h = max(0, int(h or 0))
    sm_trend = 'mul' if mul_trend else 'add' if trend != 'N' else None
    model = ETSModel(pd.Series(x), error=error, trend=sm_trend, damped_trend=trend in ('Ad', 'Md'),
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
             f'{ {"N": "no", "A": "additive", "Ad": "additive damped", "M": "multiplicative", "Md": "multiplicative damped"}[trend]} trend, '
             f'{ {"N": "no", "A": "additive", "M": "multiplicative"}[seasonal]} seasonality'
             f'{f" (period {s})" if seasonal != "N" else ""}.',
             'AIC, AICc and BIC are statsmodels\': Nparm counts the smoothing parameters, the starting states and σ. '
             'Their likelihood is not comparable with the ARIMA models\' (JMP gives the same caution).']
    simulated = error == 'mul' or seasonal == 'M' or mul_trend
    if simulated:
        notes.append('Prediction intervals: quantiles of 2000 simulated paths (a fixed seed).')
    if mul_trend:
        notes.append('A multiplicative trend grows by a factor each period (damped: one that shrinks towards 1 over the forecasts); '
                     'Hyndman et al. (2008) warn that it can forecast too far.')
    if miss.any():
        notes.append(f'{int(miss.sum())} missing value{"s" if miss.sum() > 1 else ""} filled by linear interpolation for the fit; they are left out of the fit statistics.')
    c = _code_series(S, table_name, where, ['from statsmodels.tsa.exponential_smoothing.ets import ETSModel'])
    if miss.any():
        c.append('y = y.interpolate(limit_direction="both")')
    c.append(f'res = ETSModel(y.reset_index(drop=True), error={error!r}, trend={sm_trend!r}, damped_trend={trend in ("Ad", "Md")}, '
             f'seasonal={({"A": "add", "M": "mul"}.get(seasonal))!r}{", seasonal_periods=" + str(s) if seasonal != "N" else ""}).fit(disp=False)')
    c.append('print(res.summary())')
    if h:
        c.append(f'print(res.get_prediction(start=len(y), end=len(y) + {h - 1}).summary_frame(alpha={1 - level:.6g}))')
    fitted_v = np.where(valid, fitted, np.nan)
    resid = np.where(valid, x - fitted, np.nan)
    # the graphs: the model fitted as above (the page's iterations), its predictions and the simulated or exact intervals
    fit = ['yi = y.interpolate(limit_direction="both")   # the missing values filled for the fit' if miss.any() else 'yi = y',
           f'res = ETSModel(yi.reset_index(drop=True), error={error!r}, trend={sm_trend!r}, damped_trend={trend in ("Ad", "Md")}, '
           f'seasonal={({"A": "add", "M": "mul"}.get(seasonal))!r}{", seasonal_periods=" + str(s) if seasonal != "N" else ""}, '
           f'initialization_method="estimated").fit(disp=False, maxiter={int(maxiter or 1000)})',
           _z_line(level), 'fv = np.asarray(res.fittedvalues, dtype=float)',
           'ok = y.notna().to_numpy() & np.isfinite(fv)   # the one-step errors the fit statistics take',
           'se = np.sqrt(res.mse)' + (' * np.abs(fv)   # multiplicative errors: relative to the prediction' if error == 'mul' else '   # the standard deviation of the one-step errors'),
           *_band_lines(resid='yi.to_numpy() - fv')]
    if h:
        fit += [f'fr = res.get_prediction(start=len(yi), end=len(yi) + {h - 1}, simulate_repetitions=2000, random_state={SEED}).summary_frame(alpha={1 - level:.6g})',
                'f_mean, f_lower, f_upper = (fr[k].to_numpy() for k in ("mean", "pi_lower", "pi_upper"))'
                + ('   # simulated (a fixed seed)' if simulated else ''), _future_line(S, h)]
    name = ets_name(error, trend, seasonal, s)
    plot_code, plot_frag = _model_plots(S, table_name, where, name, ['from statsmodels.tsa.exponential_smoothing.ets import ETSModel'], fit, h, nlags)
    head = _head(S, table_name, where, plot_frag['imports'])
    plot_code['states'] = {k2: [*head, *fit, '', SIZE, COLOR, 'fig, ax = plt.subplots(figsize=size, layout="constrained")',
                                f'ax.plot(t, res.states[{J(k2)}].to_numpy(), color=color, linewidth={_pt(1.4)})   # the {k2} state',
                                *_labels(S, k2[:1].upper() + k2[1:], f'{name} {k2}'), 'plt.show()'] for k2 in comp}
    return _model_out(S, 'ets', name, fitted_v, resid, np.where(valid, fit_se, np.nan), level, fcd, st, summary,
                      {'columns': 'ets', 'rows': rows_p}, nlags, 0, notes, '\n'.join(c), plot_code=plot_code, plot_frag=plot_frag,
                      states=comp, sigma=sigma, nparm=nparm, sm={'aic': _f(res.aic), 'aicc': _f(res.aicc), 'bic': _f(res.bic), 'llf': _f(res.llf)},
                      spec={'error': error, 'trend': trend, 'seasonal': seasonal, 's': s})


# ---- the calendar, for the models that need it ------------------------------------------------------

def _per_year(S):
    """Observations per year of a calendar frequency (12 for monthly data,
    4 for quarterly ...), or None when the dates follow no such frequency."""
    if S.offset is None:
        return None
    name = type(S.offset).__name__
    n = abs(int(getattr(S.offset, 'n', 1) or 1))
    for key, per in (('Year', 1), ('Quarter', 4), ('SemiMonth', 24), ('Month', 12), ('Week', 52)):
        if key in name:
            return per / n
    return None


def _endog(S, values=None):
    """The series as statsmodels gets it, and as the code shown builds it: a
    Series indexed by its dates when they follow a calendar frequency (so that
    statsmodels knows the frequency, as the code's y from asfreq() does), else
    a plain array (statsmodels would ignore the index anyway)."""
    v = np.asarray(S.y if values is None else values, dtype=float)
    if S.kind in DATE_KINDS and S.offset is not None:
        idx = pd.date_range(pd.Timestamp(int(S.t[0]), unit='ms'), periods=S.n, freq=S.offset)
        return pd.Series(v, index=idx)
    return v


def _plural(n, one, many=None):
    return f'{n} {one if n == 1 else (many or one + "s")}'


# ---- structural models (UnobservedComponents) ---------------------------------------------------------

# statsmodels' level/trend specifications, in its order, with the model each is
UC_TRENDS = {
    'irregular': 'no trend: y = ε',
    'fixed intercept': 'fixed intercept: y = μ',
    'deterministic constant': 'deterministic constant: y = μ + ε',
    'local level': 'local level: y = μ_t + ε, μ_t = μ_t−1 + η',
    'random walk': 'random walk: y = μ_t, μ_t = μ_t−1 + η',
    'fixed slope': 'fixed slope: y = μ_t, μ_t = μ_t−1 + β',
    'deterministic trend': 'deterministic trend: y = μ_t + ε, μ_t = μ_t−1 + β',
    'local linear deterministic trend': 'local linear deterministic trend: μ_t = μ_t−1 + β + η',
    'random walk with drift': 'random walk with drift: y = μ_t, μ_t = μ_t−1 + β + η',
    'local linear trend': 'local linear trend: μ_t = μ_t−1 + β_t−1 + η, β_t = β_t−1 + ζ',
    'smooth trend': 'smooth trend: μ_t = μ_t−1 + β_t−1, β_t = β_t−1 + ζ',
    'random trend': 'random trend: y = μ_t, μ_t = μ_t−1 + β_t−1, β_t = β_t−1 + ζ',
}


def _uc_label(name):
    """A report name for one of UnobservedComponents' parameters."""
    fixed = {'sigma2.irregular': 'Irregular Variance (σ²ε)', 'sigma2.level': 'Level Variance (σ²η)', 'sigma2.trend': 'Slope Variance (σ²ζ)',
             'sigma2.seasonal': 'Seasonal Variance (σ²ω)', 'sigma2.cycle': 'Cycle Variance (σ²κ)', 'frequency.cycle': 'Cycle Frequency (λ)',
             'damping.cycle': 'Cycle Damping (ρ)', 'sigma2.ar': 'AR Innovation Variance'}
    if name in fixed:
        return fixed[name]
    if name.startswith('sigma2.freq_seasonal_'):
        return f'Trigonometric Seasonal {name[len("sigma2.freq_seasonal_"):]} Variance'
    if name.startswith('ar.L'):
        return f'AR{name[4:]}'
    if name.startswith('beta.'):
        return name[5:]
    return name


def uc_name(trend, seasonal=0, freq=None, cycle=False, ar=0, inputs=None):
    """A model's name: its components joined, as statsmodels' summary names them."""
    parts = [trend if trend != 'irregular' else 'no trend']
    if seasonal:
        parts.append(f'seasonal({seasonal})')
    for f in freq or []:
        parts.append(f'trigonometric seasonal({f["period"]}, {f["harmonics"]})')
    if cycle:
        parts.append('cycle')
    if ar:
        parts.append(f'AR({ar})')
    parts += list(inputs or [])
    return 'Structural: ' + ' + '.join(parts)


def _period_text(p):
    return '∞' if not math.isfinite(p) else f'{p:.6g}'


@api('timeseries.structural')
@_quietly
def structural(table, y, time=None, rows=None, excluded=None, trend='local linear trend', seasonal=0, stoch_seasonal=True,
               freq_period=0, freq_harmonics=0, stoch_freq=True, cycle=False, stoch_cycle=True, damped_cycle=True,
               cycle_lo=None, cycle_hi=None, ar=0, inputs=None, exact=False, level=0.95, h=25, maxiter=200,
               nlags=25, where=None, table_name='data', holdback=0, cut=0, season=0):
    """A structural time series model, y = level + seasonal + cycle +
    autoregressive + regression + irregular, by maximum likelihood with the
    Kalman filter (statsmodels' UnobservedComponents), its smoothed components
    with their bands, and forecasts."""
    from statsmodels.tsa.statespace.structural import UnobservedComponents
    trend = trend if trend in UC_TRENDS else 'local linear trend'
    seasonal, ar = max(0, int(seasonal or 0)), max(0, int(ar or 0))
    fp = max(0, int(freq_period or 0))
    fh = max(0, int(freq_harmonics or 0)) or fp // 2
    if seasonal == 1 or fp == 1:
        return {'error': 'a seasonal period must be at least 2'}
    if fp and not 1 <= fh <= fp // 2:
        return {'error': f'the trigonometric seasonal of period {fp} takes 1 to {fp // 2} harmonics'}
    level = float(level or 0.95)
    h = max(0, int(h or 0))
    names_in = [c for c in dict.fromkeys(inputs or []) if c and c != y]
    try:
        S = load(table, y, time, rows, excluded, names_in, holdback=holdback, cut=cut, season=season)
        E, Ef, xnames, _start, xnotes = _exog(S, [{'name': c} for c in names_in], h)
    except NoSeries as e:
        return {'error': str(e)}
    notes = list(xnotes)
    endog = _endog(S)
    index = endog.index if isinstance(endog, pd.Series) else None
    exog = pd.DataFrame(E, columns=xnames, index=index) if E is not None else None
    freq = [{'period': fp, 'harmonics': fh}] if fp else None
    kw = {'level': trend}
    if seasonal:
        kw.update(seasonal=seasonal, stochastic_seasonal=bool(stoch_seasonal))
    if freq:
        kw.update(freq_seasonal=freq, stochastic_freq_seasonal=[bool(stoch_freq)])
    if cycle:
        kw.update(cycle=True, stochastic_cycle=bool(stoch_cycle), damped_cycle=bool(damped_cycle))
        lo = float(cycle_lo) if cycle_lo not in (None, '') else None
        hi = float(cycle_hi) if cycle_hi not in (None, '') else None
        if lo is not None or hi is not None:
            lo, hi = (lo if lo is not None else 2.0), (hi if hi is not None else math.inf)
            if not 2 <= lo < hi:
                return {'error': 'the bounds on the period of the cycle: from 2 periods up, the lower below the upper'}
            kw['cycle_period_bounds'] = (lo, hi)
    if ar:
        kw['autoregressive'] = ar
    if exog is not None:
        kw['exog'] = exog
    kw['use_exact_diffuse'] = bool(exact)
    nobs = int(np.isfinite(S.y).sum())
    model = UnobservedComponents(endog, **kw)
    k_all = len(model.param_names)
    if nobs < k_all + model.k_states + 3:
        return {'error': f'too few observations ({nobs}) for a model with {model.k_states} states and {k_all} parameters'}
    its = []
    with _quiet():
        res = model.fit(method='lbfgs', maxiter=int(maxiter or 200), pgtol=1e-7, factr=1e4, disp=False,
                        callback=lambda xk: its.append(np.array(xk, dtype=float)))
    names = list(res.param_names)
    est = np.asarray(res.params, dtype=float)
    with _quiet():
        se = np.asarray(res.bse, dtype=float)
        zv = np.asarray(res.zvalues, dtype=float)
        pv = np.asarray(res.pvalues, dtype=float)
    rows_p = [{'term': _uc_label(nm), 'estimate': _f(est[j]), 'se': _f(se[j]), 'z': _f(zv[j]), 'p': _f(pv[j]), 'sm': nm} for j, nm in enumerate(names)]
    burn = max(int(res.loglikelihood_burn), int(getattr(res, 'nobs_diffuse', 0) or 0))
    fitted = np.asarray(res.fittedvalues, dtype=float)
    valid = np.isfinite(S.y) & (np.arange(S.n) >= burn) & np.isfinite(fitted)
    k = max(0, int(res.df_model) - 1)          # JMP's count: one variance (the scale) not counted
    st = _fit_stats(S.y, fitted, valid, k, -2 * float(res.llf))
    zc = stats.norm.ppf(0.5 + level / 2)
    with _quiet():
        pr = res.get_prediction()
        fit_se = np.asarray(pr.se_mean, dtype=float)
        if h:
            fc = res.get_forecast(h, exog=Ef if E is not None else None)
            ci = np.asarray(fc.conf_int(alpha=1 - level), dtype=float)
            fcd = _forecast(S, h, fc.predicted_mean, fc.se_mean, ci[:, 0], ci[:, 1])
        else:
            fcd = _forecast(S, 0, [], [], [], [])
    # the smoothed components, with their bands (statsmodels' plot_components)
    comps = []

    def add(key, label, b):
        if b is None or b['smoothed'] is None:
            return
        m = np.asarray(b['smoothed'], dtype=float)
        s_ = np.sqrt(np.clip(np.asarray(b['smoothed_cov'], dtype=float), 0, None))
        comps.append({'key': key, 'label': label, 'mean': _arr(m), 'lower': _arr(m - zc * s_), 'upper': _arr(m + zc * s_)})

    with _quiet():
        add('level', 'Level', res.level)
        add('trend', 'Trend (slope)', res.trend)
        add('seasonal', 'Seasonal', res.seasonal)
        for i, b in enumerate(res.freq_seasonal or []):
            add(f'freq_seasonal{i}', f'Trigonometric seasonal {freq[i]["period"]}({freq[i]["harmonics"]})', b)
        add('cycle', 'Cycle', res.cycle)
        add('autoregressive', 'Autoregressive', res.autoregressive)
    if E is not None:
        beta = np.array([est[names.index(f'beta.{c}')] for c in xnames])
        comps.append({'key': 'regression', 'label': 'Regression effect', 'mean': _arr(E @ beta), 'lower': None, 'upper': None})
    if model.irregular:
        sr = res.smoother_results
        m = np.asarray(sr.smoothed_measurement_disturbance[0], dtype=float)
        s_ = np.sqrt(np.clip(np.asarray(sr.smoothed_measurement_disturbance_cov[0, 0], dtype=float), 0, None))
        comps.append({'key': 'irregular', 'label': 'Irregular', 'mean': _arr(m), 'lower': _arr(m - zc * s_), 'upper': _arr(m + zc * s_)})
    lo_f, hi_f = model.cycle_frequency_bound if cycle else (None, None)
    summary = [['DF', st['df'], 'int'], ['Sum of Squared Residuals', st['sse']], ['Variance Estimate', st['variance']], ['Standard Deviation', st['sd']],
               ["Akaike's 'A' Information Criterion", st['aic']], ["Schwarz's Bayesian Criterion", st['sbc']], ['AICc', st['aicc']],
               ['RSquare', st['rsquare']], ['RSquare Adj', st['rsquare_adj']], ['MAPE', st['mape']], ['MAE', st['mae']], ['−2LogLikelihood', st['m2ll']]]
    if cycle:
        lam = est[names.index('frequency.cycle')]
        summary.append(['Cycle Period (2π/λ)', 2 * math.pi / lam if lam > 0 else None])
    summary.append(['Diffuse Initialization', 'exact' if exact else 'approximate', 'text'])
    conv = bool(res.mle_retvals.get('converged', True)) if isinstance(res.mle_retvals, dict) else True
    n_iter = int(res.mle_retvals.get('iterations', len(its))) if isinstance(res.mle_retvals, dict) else len(its)
    if exact:
        notes.append(f'Maximum likelihood with the Kalman filter, which skips missing values; the nonstationary states start from the exact diffuse '
                     f'initialization of Durbin and Koopman ({_plural(int(res.nobs_diffuse), "diffuse observation")}), whose likelihood KFAS reports too. '
                     'The fit statistics leave out the diffuse observations.')
    else:
        notes.append('Maximum likelihood with the Kalman filter (statsmodels\' UnobservedComponents), which skips missing values. The nonstationary '
                     'states start from statsmodels\' approximate diffuse initialization (a very large variance), so the first '
                     f'{_plural(burn, "observation")} are left out of the likelihood and of the fit statistics; Exact diffuse initialization '
                     'in the dialog gives Durbin and Koopman\'s exact likelihood instead.')
    notes.append(f'statsmodels counts every parameter{" and diffuse state" if exact else ""} in its AIC: {res.aic:.6g} (BIC {res.bic:.6g}); '
                 f'the table leaves one variance (the scale) out, as JMP leaves out the variance of ARIMA models: k = {k}, n = {st["n"]}.')
    notes.append('Standard errors from the outer product of the gradients (statsmodels\' default). A z test of a variance against 0 lies at the '
                 'edge of the parameter space, where it is conservative; a variance at 0 means that component is fixed.')
    if cycle:
        dflt = '' if 'cycle_period_bounds' in kw else " (statsmodels' default for this frequency)"
        notes.append(f'The period of the cycle is bounded to {_period_text(2 * math.pi / hi_f)} to '
                     f'{_period_text(2 * math.pi / lo_f if lo_f > 0 else math.inf)} periods{dflt}. '
                     'Cycle models often have several local maxima of the likelihood; try other bounds if the cycle looks wrong.')
    if trend in ('fixed intercept', 'fixed slope') and not (seasonal and stoch_seasonal) and not freq and not (cycle and stoch_cycle) and not ar:
        notes.append('The model has no stochastic part: statsmodels adds an irregular component.')
    if not conv:
        notes.append(f'The fit did not converge within {int(maxiter or 200)} iterations: raise Maximum Iterations in the red triangle.')
    name = uc_name(trend, seasonal, freq, cycle, ar, names_in)
    # the code
    c = _code_series(S, table_name, where, ['from statsmodels.tsa.statespace.structural import UnobservedComponents'])
    dated = isinstance(endog, pd.Series)
    held = S.hold is not None
    x_future = f'X_future = d.loc[y_hold.index, {json.dumps(names_in)}].to_numpy()   # the inputs of the held-back rows' if held else \
        'X_future = pd.DataFrame({' + ', '.join(f'{json.dumps(nm)}: {[_f(v) for v in Ef[:, j]]}' for j, nm in enumerate(xnames)) + '})'
    if names_in:
        c.append(f'X = d.loc[y.index, {json.dumps(names_in)}]' + ('' if dated else '.reset_index(drop=True)'))
        if h:
            c.append(x_future)
    args = [f'level={trend!r}']
    if seasonal:
        args.append(f'seasonal={seasonal}, stochastic_seasonal={bool(stoch_seasonal)}')
    if freq:
        args.append(f'freq_seasonal=[{{"period": {fp}, "harmonics": {fh}}}], stochastic_freq_seasonal=[{bool(stoch_freq)}]')
    if cycle:
        args.append(f'cycle=True, stochastic_cycle={bool(stoch_cycle)}, damped_cycle={bool(damped_cycle)}')
        if 'cycle_period_bounds' in kw:
            args.append(f'cycle_period_bounds=({kw["cycle_period_bounds"][0]!r}, {"np.inf" if not math.isfinite(kw["cycle_period_bounds"][1]) else repr(kw["cycle_period_bounds"][1])})')
    if ar:
        args.append(f'autoregressive={ar}')
    if names_in:
        args.append('exog=X')
    args.append(f'use_exact_diffuse={bool(exact)}')
    c.append(f'mod = UnobservedComponents({"y" if dated else "y.to_numpy()"}, {", ".join(args)})')
    c.append(f'res = mod.fit(method="lbfgs", maxiter={int(maxiter or 200)}, pgtol=1e-7, factr=1e4, disp=False)')
    c.append('print(res.summary())')
    c.append('print(res.level.smoothed, res.level.smoothed_cov)   # also res.trend, res.seasonal, res.freq_seasonal, res.cycle, res.autoregressive')
    if h:
        c.append(f'print(res.get_forecast({h}{", exog=X_future" if names_in else ""}).summary_frame(alpha={1 - level:.6g}))')
    # the iteration history last: loglike() updates the model's matrices
    history = []
    with _quiet():
        for j, xk in enumerate(its[:500]):
            try:
                history.append({'iter': j + 1, 'm2ll': _f(-2 * model.loglike(xk, transformed=False))})
            except Exception:
                break
    fitted_v = np.where(valid, fitted, np.nan)
    resid = np.where(valid, S.y - fitted, np.nan)
    fit_se = np.where(valid, fit_se, np.nan)
    # the graphs: the model fitted as above, its one-step predictions after the diffuse start, the forecasts
    fit = []
    if names_in:
        fit.append(f'X = d.loc[y.index, {json.dumps(names_in)}]' + ('' if dated else '.reset_index(drop=True)') + '   # the inputs')
        if h:
            fit.append(x_future if held else x_future + '   # the inputs of the forecast periods')
    fit += [c[next(i for i, ln in enumerate(c) if ln.startswith('mod = UnobservedComponents('))],
            f'res = mod.fit(method="lbfgs", maxiter={int(maxiter or 200)}, pgtol=1e-7, factr=1e4, disp=False)',
            _z_line(level), 'fv = np.asarray(res.fittedvalues, dtype=float)',
            'burn = max(res.loglikelihood_burn, res.nobs_diffuse or 0)   # the diffuse start, left out of the fit statistics',
            'ok = y.notna().to_numpy() & (np.arange(len(y)) >= burn) & np.isfinite(fv)',
            'se = np.asarray(res.get_prediction().se_mean, dtype=float)', *_band_lines()]
    if h:
        fit += [f'fc = res.get_forecast({h}{", exog=X_future" if names_in else ""})',
                f'f_mean, (f_lower, f_upper) = np.asarray(fc.predicted_mean, dtype=float), np.asarray(fc.conf_int(alpha={1 - level:.6g}), dtype=float).T', _future_line(S, h)]
    plot_code, plot_frag = _model_plots(S, table_name, where, name, ['from statsmodels.tsa.statespace.structural import UnobservedComponents'], fit, h, nlags)
    part = {'level': 'res.level', 'trend': 'res.trend', 'seasonal': 'res.seasonal', 'cycle': 'res.cycle', 'autoregressive': 'res.autoregressive'}
    cp = [*_head(S, table_name, where, plot_frag['imports']), *fit,
          'parts = []   # the smoothed components (label, mean, lower, upper), with their bands from the smoothed variances']
    for comp_ in comps:
        key, label = comp_['key'], comp_['label']
        if key in part or key.startswith('freq_seasonal'):
            src = part.get(key) or f'res.freq_seasonal[{int(key[len("freq_seasonal"):])}]'
            cp.append(f'm, s = np.asarray({src}.smoothed, dtype=float), np.sqrt(np.clip(np.asarray({src}.smoothed_cov, dtype=float), 0, None)); '
                      f'parts.append(({J(label)}, m, m - z * s, m + z * s))')
        elif key == 'regression':
            cp.append(f'beta = np.asarray(res.params)[[res.model.param_names.index("beta." + c) for c in {json.dumps(xnames)}]]; '
                      f'parts.append(({J(label)}, np.asarray(X, dtype=float) @ beta, None, None))   # the inputs times their coefficients')
        elif key == 'irregular':
            cp.append('e = res.smoother_results; m = np.asarray(e.smoothed_measurement_disturbance[0], dtype=float); '
                      's = np.sqrt(np.clip(np.asarray(e.smoothed_measurement_disturbance_cov[0, 0], dtype=float), 0, None)); '
                      f'parts.append(({J(label)}, m, m - z * s, m + z * s))')
    cp += ['', SIZE, COLOR, 'fig, axes = plt.subplots(len(parts), 1, sharex=True, squeeze=False, figsize=size, layout="constrained")',
           'for ax, (label, m, lo, hi) in zip(axes[:, 0], parts):',
           '    if label == "Level":',
           '        ' + _trace('t', 'y', lines=False, color=MUTED, size=4) + '   # the data',
           '    if lo is not None:',
           f'        ax.fill_between(t, lo, hi, color=color, alpha=0.18, linewidth=0)   # the {100 * level:g}% band',
           f'    ax.plot(t, m, color=color, linewidth={_pt(1.5)})',
           '    ax.set_title(label, loc="left", fontsize=8)',
           f'axes[-1, 0].set_xlabel({J(_xlabel(S))})', f'fig.suptitle({J(name + " components")}, fontsize=10)', 'plt.show()']
    plot_code['components'] = cp
    return _model_out(S, 'uc', name, fitted_v, resid, fit_se, level, fcd, st, summary, {'columns': 'uc', 'rows': rows_p}, nlags, 0, notes,
                      '\n'.join(c), components=comps, iterations=history, converged=conv, n_iter=n_iter, burn=burn,
                      plot_code=plot_code, plot_frag=plot_frag,
                      cycle_bounds=[_f(2 * math.pi / hi_f), _f(2 * math.pi / lo_f) if lo_f and lo_f > 0 else None] if cycle else None,
                      sm={'aic': _f(res.aic), 'bic': _f(res.bic), 'aicc': _f(res.aicc), 'llf': _f(res.llf), 'df_model': int(res.df_model)},
                      spec={'trend': trend, 'seasonal': seasonal, 'freq': freq, 'cycle': bool(cycle), 'ar': ar, 'inputs': names_in, 'exact': bool(exact)})


# ---- regime switching (MarkovRegression, MarkovAutoregression) -------------------------------------------

def markov_name(k, order=0, trend='c', switching_trend=True, switching_variance=False, switching_ar=True):
    parts = [f'{k} regimes']
    if order:
        parts.append(f'AR({order})')
    sw = []
    if switching_trend and trend != 'n':
        sw.append({'c': 'mean', 'ct': 'mean and trend'}.get(trend, trend))
    if order and switching_ar:
        sw.append('AR')
    if switching_variance:
        sw.append('variance')
    return 'Regime Switching: ' + ', '.join(parts) + (f', switching {" and ".join(sw)}' if sw else '')


def _ms_spread(names, y, k):
    """A start that spreads the regimes over the data: the intercepts at the
    quantiles (j + 1/2)/k of the series, sticky regimes (a 0.9 chance of
    staying), variances var(y)/k, AR coefficients and trends at 0.
    statsmodels' own start puts the intercepts at 0 and at a fraction of the
    OLS intercept, close together, from where the fit often ends where the
    regimes are the same."""
    q = np.quantile(y, (np.arange(k) + 0.5) / k)
    out = []
    for nm in names:
        if nm.startswith('p['):
            i, j = (int(v) for v in nm[2:-1].split('->'))
            out.append(0.9 if i == j else 0.1 / (k - 1))
        elif nm.startswith('const['):
            out.append(float(q[int(nm[6:-1])]))
        elif nm == 'const':
            out.append(float(np.mean(y)))
        elif nm.startswith('sigma2'):
            out.append(float(np.var(y)) / k)
        else:
            out.append(0.0)
    return np.array(out)


def _ms_scale(names, y):
    """The half-widths of the random starts on statsmodels' unconstrained
    scale, matched to the data: 1 for the transition logits, sd(y) for the
    intercepts (sd(y)/n for trends), sd(y)/2 for the standard deviations
    (statsmodels squares them into variances), 1/2 for the AR coefficients."""
    sd, n = float(np.std(y)), len(y)
    return np.array([1.0 if nm.startswith('p[') else 0.5 * sd if nm.startswith('sigma2') else sd if nm.startswith('const')
                     else sd / n if nm.startswith('x1') else 0.5 for nm in names])


def _ms_term(name):
    """statsmodels' parameter name split into the report's term and regime:
    const[1] -> ('Intercept', 1), ar.L2 -> ('AR2', None), p[0->1] -> ('P(0 → 1)', None)."""
    import re
    m = re.match(r'^p\[(\d+)->(\d+)\]$', name)
    if m:
        return f'P({m.group(1)} → {m.group(2)})', None, True
    m = re.match(r'^(.*?)\[(\d+)\]$', name)
    base, regime = (m.group(1), int(m.group(2))) if m else (name, None)
    label = {'const': 'Intercept', 'x1': 'Trend', 'sigma2': 'Variance'}.get(base)
    if label is None:
        label = f'AR{base[4:]}' if base.startswith('ar.L') else base
    return label, regime, False


@api('timeseries.markov')
@_quietly
def markov(table, y, time=None, rows=None, excluded=None, k=2, order=0, trend='c', switching_trend=True, switching_variance=False,
           switching_ar=True, starts=5, maxiter=100, level=0.95, h=25, nlags=25, where=None, table_name='data', holdback=0, cut=0, season=0):
    """A Markov switching model: k regimes with their own mean (and trend),
    variance or AR coefficients, and the Markov chain that moves between them
    (Hamilton 1989; statsmodels' MarkovRegression and MarkovAutoregression),
    by maximum likelihood from the default start and from random starts."""
    from statsmodels.tools.sm_exceptions import ConvergenceWarning
    from statsmodels.tsa.regime_switching.markov_autoregression import MarkovAutoregression
    from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression
    k, order = int(k or 2), max(0, int(order or 0))
    trend = trend if trend in ('n', 'c', 'ct') else 'c'
    starts, maxiter = max(0, min(50, int(starts or 0))), max(5, int(maxiter or 100))
    level = float(level or 0.95)
    if k not in (2, 3):
        return {'error': 'the number of regimes: 2 or 3'}
    switching_trend = bool(switching_trend) and trend != 'n'
    switching_ar = bool(switching_ar) and order > 0
    if not (switching_trend or switching_variance or switching_ar):
        return {'error': 'nothing switches: choose a switching mean, variance or AR part'}
    try:
        S = load(table, y, time, rows, excluded, holdback=holdback, cut=cut, season=season)
    except NoSeries as e:
        return {'error': str(e)}
    x, miss = _filled(S)
    n = len(x)
    if n - order < 10 * k:
        return {'error': f'too few observations ({n}) for {k} regimes'}
    with _quiet():
        if order:
            mod = MarkovAutoregression(x, k_regimes=k, order=order, trend=trend, switching_ar=switching_ar,
                                       switching_trend=switching_trend, switching_variance=bool(switching_variance))
        else:
            mod = MarkovRegression(x, k_regimes=k, trend=trend, switching_trend=switching_trend, switching_variance=bool(switching_variance))
        spread = _ms_spread(mod.param_names, x[order:] if order else x, k)
        u0 = np.asarray(mod.untransform_params(spread), dtype=float)
        rng = np.random.default_rng(SEED)
        scale = _ms_scale(mod.param_names, x)
    draws = ['default', 'quantiles'] + [u0 + rng.uniform(-1, 1, size=u0.size) * scale for _ in range(starts)]
    tried, best = [], None
    for i, dr in enumerate(draws):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            try:
                if isinstance(dr, str):
                    p = mod.fit(maxiter=maxiter, return_params=True) if dr == 'default' else mod.fit(start_params=spread, maxiter=maxiter, return_params=True)
                else:
                    p = mod.fit(start_params=dr, transformed=False, maxiter=maxiter, return_params=True)
                ll, err = float(mod.loglike(p)), None
            except Exception as e:  # a start that fails is reported in the Starts table
                p, ll, err = None, float('nan'), f'{type(e).__name__}: {e}'
        ws = [w for w in caught if not issubclass(w.category, (DeprecationWarning, FutureWarning))]
        conv = err is None and math.isfinite(ll) and not any(issubclass(w.category, ConvergenceWarning) for w in ws)
        label = {'default': 'statsmodels\' default', 'quantiles': 'regimes at the quantiles'}.get(dr, f'random {i - 1}') if isinstance(dr, str) else f'random {i - 1}'
        tried.append({'start': label, 'm2ll': _f(-2 * ll), 'converged': 'Yes' if conv else 'No', 'note': err or ''})
        # a later start wins only by more than rounding, so that equal maxima keep the earlier start's regime labels
        if p is not None and math.isfinite(ll) and (best is None or ll > best[1] + 1e-6):
            best = (np.asarray(p, dtype=float), ll, ws, i)
    if best is None:
        return {'error': 'no start gave a finite likelihood; try fewer regimes or another model', 'starts': tried}
    for row in tried:
        row['best'] = ''
    tried[best[3]]['best'] = '★ best'
    # the warnings of the fit that is reported, not of the starts left behind
    for w in best[2]:
        warnings.warn(str(w.message), w.category)
    with _quiet():
        res = mod.smooth(best[0], cov_type='approx')
        names = list(mod.param_names)
        est = np.asarray(res.params, dtype=float)
        se = np.asarray(res.bse, dtype=float)
        zv = np.asarray(res.tvalues, dtype=float)
        pv = np.asarray(res.pvalues, dtype=float)
    rows_p, per = [], {}
    for j, nm in enumerate(names):
        term, regime, trans = _ms_term(nm)
        rows_p.append({'term': term, 'regime': '' if regime is None else str(regime), 'estimate': _f(est[j]), 'se': _f(se[j]),
                       'z': _f(zv[j]), 'p': _f(pv[j]), 'sm': nm})
        if not trans:
            per.setdefault(term, {'term': term, 'switching': 'Yes' if regime is not None else 'No'})
            for r in (range(k) if regime is None else [regime]):
                per[term][f'r{r}'] = _f(est[j])
    P = np.asarray(res.regime_transition, dtype=float)[:, :, 0]      # P[to, from]
    trans = [{'from': f'Regime {i}', **{f'r{j}': _f(P[j, i]) for j in range(k)}} for i in range(k)]
    durations = np.asarray(res.expected_durations, dtype=float).ravel()
    sm_prob = np.asarray(res.smoothed_marginal_probabilities, dtype=float)
    ft_prob = np.asarray(res.filtered_marginal_probabilities, dtype=float)
    pad = lambda v: np.concatenate([np.full(order, np.nan), np.asarray(v, dtype=float)])   # noqa: E731
    prob = [_arr(pad(sm_prob[:, j])) for j in range(k)]
    fprob = [_arr(pad(ft_prob[:, j])) for j in range(k)]
    most = np.argmax(sm_prob, axis=1)
    regimes = []
    for j in range(k):
        regimes.append({'regime': f'Regime {j}', 'duration': '∞' if durations[j] == np.inf else _f(durations[j]), 'periods': int((most == j).sum()),
                        'share': _f(float(np.mean(sm_prob[:, j]))), 'stay': _f(P[j, j])})
    with _quiet():
        fitted = np.asarray(res.predict(probabilities='predicted'), dtype=float)
    fitted_full = pad(fitted)
    valid = ~miss & np.isfinite(fitted_full) & (np.arange(n) >= order)
    kk = max(0, len(est) - 1)                 # JMP's count: one variance (the scale) not counted
    st = _fit_stats(x, fitted_full, valid, kk, -2 * float(res.llf))
    summary = [['DF', st['df'], 'int'], ['Sum of Squared Residuals', st['sse']], ['Variance Estimate', st['variance']], ['Standard Deviation', st['sd']],
               ["Akaike's 'A' Information Criterion", st['aic']], ["Schwarz's Bayesian Criterion", st['sbc']], ['AICc', st['aicc']],
               ['RSquare', st['rsquare']], ['RSquare Adj', st['rsquare_adj']], ['MAPE', st['mape']], ['MAE', st['mae']], ['−2LogLikelihood', st['m2ll']],
               ['Regimes', k, 'int'], ['Starts', len(draws), 'int']]
    notes = [f'Maximum likelihood by the Hamilton filter (statsmodels\' {"MarkovAutoregression" if order else "MarkovRegression"}): '
             'BFGS after five EM steps, from statsmodels\' default start, from a start with the regimes\' intercepts at the quantiles of '
             f'the series, and from {_plural(starts, "random start")} around that one (uniform, on a scale matched to the data, seed {SEED}); '
             'the highest likelihood is kept. Regime-switching likelihoods often have several local maxima, and some starts fail: '
             'the Starts table shows where each one ended.',
             'The regimes are numbered as statsmodels numbers them, from 0; which one is which (high or low mean) can change with the data '
             'or the starts. The smoothed probabilities use all the data (Kim\'s smoother), the filtered ones the data up to each time.',
             f'statsmodels counts every parameter in its AIC: {res.aic:.6g} (BIC {res.bic:.6g}); the table leaves one variance out, '
             f'as JMP does for ARIMA models: k = {kk}.',
             'statsmodels does not forecast Markov switching models: the predictions are one step ahead, E[y_t | y before t], '
             'from the predicted regime probabilities.']
    if order:
        notes.append(f'The likelihood is conditional on the first {_plural(order, "observation")}, the lags\' starting values.')
    if miss.any():
        notes.append(f'{_plural(int(miss.sum()), "missing value")} filled by linear interpolation for the fit: the Hamilton filter needs every value. '
                     'They are left out of the fit statistics.')
    cls = 'MarkovAutoregression' if order else 'MarkovRegression'
    imp = f'from statsmodels.tsa.regime_switching.{"markov_autoregression" if order else "markov_regression"} import {cls}'
    c = _code_series(S, table_name, where, [imp])
    if miss.any():
        c.append('y = y.interpolate(limit_direction="both")   # the Hamilton filter needs every value')
    args = [f'k_regimes={k}'] + ([f'order={order}'] if order else []) + [f'trend={trend!r}', f'switching_trend={switching_trend}']
    if order:
        args.append(f'switching_ar={switching_ar}')
    args.append(f'switching_variance={bool(switching_variance)}')
    c += [f'x = y.to_numpy(); k = {k}',
          f'mod = {cls}(x, {", ".join(args)})',
          f'xs = x[{order}:]; q = np.quantile(xs, (np.arange(k) + 0.5) / k); sd = x.std()   # a start with the regimes spread over the data',
          'spread = np.array([(0.9 if nm[2] == nm[5] else 0.1 / (k - 1)) if nm.startswith("p[") else q[int(nm[6:-1])] if nm.startswith("const[")',
          '                   else xs.mean() if nm == "const" else xs.var() / k if nm.startswith("sigma2") else 0.0 for nm in mod.param_names])',
          'scale = np.array([1.0 if nm.startswith("p[") else 0.5 * sd if nm.startswith("sigma2") else sd if nm.startswith("const")',
          '                  else sd / len(x) if nm.startswith("x1") else 0.5 for nm in mod.param_names])',
          f'rng = np.random.default_rng({SEED}); u0 = mod.untransform_params(spread)',
          f'starts = ["default", "quantiles"] + [u0 + rng.uniform(-1, 1, size=u0.size) * scale for _ in range({starts})]',
          'best, best_llf = None, -np.inf',
          'for s in starts:   # the likelihood has local maxima: keep the best of several starts',
          '    try:',
          f'        if isinstance(s, str):',
          f'            p = mod.fit(maxiter={maxiter}, return_params=True) if s == "default" else mod.fit(start_params=spread, maxiter={maxiter}, return_params=True)',
          '        else:',
          f'            p = mod.fit(start_params=s, transformed=False, maxiter={maxiter}, return_params=True)',
          '    except Exception:',
          '        continue',
          '    llf = mod.loglike(p)',
          '    if np.isfinite(llf) and llf > best_llf + 1e-6:   # equal maxima keep the earlier start',
          '        best, best_llf = p, llf',
          'res = mod.smooth(best, cov_type="approx")',
          'print(res.summary())',
          'print(res.regime_transition[:, :, 0].T)   # from regime (row) to regime (column)',
          'print(res.expected_durations)',
          'print(res.smoothed_marginal_probabilities)   # P(regime at t | all the data)']
    name = markov_name(k, order, trend, switching_trend, switching_variance, switching_ar)
    resid = np.where(valid, x - fitted_full, np.nan)
    # the graphs: the model fitted as above (the same starts, the same seed), its one-step predictions and probabilities
    i0, i1 = c.index(f'x = y.to_numpy(); k = {k}'), c.index('res = mod.smooth(best, cov_type="approx")')
    fit = ['yi = y.interpolate(limit_direction="both")   # the Hamilton filter needs every value' if miss.any() else 'yi = y',
           f'x = yi.to_numpy(); k = {k}', *c[i0 + 1:i1 + 1],
           f'fv = np.r_[np.full({order}, np.nan), res.predict(probabilities="predicted")]   # E[y_t | y before t], from the predicted regime probabilities',
           f'ok = y.notna().to_numpy() & np.isfinite(fv) & (np.arange(len(y)) >= {order})',
           'fitted, resid = np.where(ok, fv, np.nan), np.where(ok, x - fv, np.nan)   # statsmodels gives these models no prediction intervals',
           f'prob = np.vstack([np.full(({order}, k), np.nan), res.smoothed_marginal_probabilities])   # P(regime at t | all the data)']
    plot_code, plot_frag = _model_plots(S, table_name, where, name, [imp], fit, 0, nlags, onestep=False)
    head = [*_head(S, table_name, where, plot_frag['imports']), *fit]
    tnum = '((t - pd.Timestamp(0)) / pd.Timedelta(milliseconds=1)).to_numpy()' if S.kind in DATE_KINDS else 'np.asarray(t, dtype=float)'
    back = 'pd.to_datetime(edges, unit="ms")' if S.kind in DATE_KINDS else 'edges'
    plot_code['regimes'] = [
        *head, f'most = np.r_[np.full({order}, -1), np.argmax(res.smoothed_marginal_probabilities, axis=1)]   # the most likely regime at each time',
        f'tn = {tnum}; step = (tn[-1] - tn[0]) / (len(tn) - 1) if len(tn) > 1 else 1.0',
        f'edges = {back.replace("edges", "np.r_[tn[0] - step / 2, (tn[:-1] + tn[1:]) / 2, tn[-1] + step / 2]")}   # halfway between the times',
        f'colors = {J(REGIMES)}   # the regimes\' colours', '', SIZE, 'fig, ax = plt.subplots(figsize=size, layout="constrained")',
        'i = 0', 'while i < len(most):   # a band over each run of one regime', '    j = i + 1',
        '    while j < len(most) and most[j] == most[i]:', '        j += 1',
        '    if most[i] >= 0:', '        ax.axvspan(edges[i], edges[j], color=colors[most[i]], alpha=0.16, linewidth=0)', '    i = j',
        _trace('t', 'y', color=INK, extra=f', label={J(S.y_name)}') + '   # the series, in the ink that reads on every band',
        'from matplotlib.patches import Patch',
        'handles = ax.get_legend_handles_labels()[0] + [Patch(color=colors[j], alpha=0.45, label=f"Regime {j} most likely") for j in range(k)]',
        'fig.legend(handles=handles, loc="outside lower center", ncols=min(4, len(handles)), frameon=False, fontsize=8)',
        *_labels(S, S.y_name, f'{name} regimes'), 'plt.show()']
    plot_code['prob'] = [
        *head, f'colors = {J(REGIMES)}   # the regimes\' colours', '', SIZE, 'fig, ax = plt.subplots(figsize=size, layout="constrained")',
        'for j in range(k):',
        f'    ax.plot(t, prob[:, j], color=colors[j], linewidth={_pt(1.5)}, marker="o", markersize={_pt(3)}, label=f"Regime {{j}}")',
        _when(['fprob'], f'fprob = np.vstack([np.full(({order}, k), np.nan), res.filtered_marginal_probabilities])   # P(regime at t | the data up to t)',
              'for j in range(k):   # Filtered Probabilities',
              f'    ax.plot(t, fprob[:, j], color=colors[j], linewidth={_pt(1)}, linestyle=":", label=f"Regime {{j}} filtered")'),
        'ax.set_ylim(-0.03, 1.03)', 'fig.legend(loc="outside lower center", ncols=4, frameon=False, fontsize=8)',
        *_labels(S, 'Smoothed probability', f'{name} smoothed probabilities'), 'plt.show()']
    return _model_out(S, 'markov', name, np.where(valid, fitted_full, np.nan), resid, None, level, _forecast(S, 0, [], [], [], []), st, summary,
                      {'columns': 'markov', 'rows': rows_p}, nlags, 0, notes, '\n'.join(c), plot_code=plot_code, plot_frag=plot_frag,
                      k=k, order=order, per_regime=list(per.values()), transition=trans, regimes=regimes, prob=prob, fprob=fprob,
                      starts=tried, most=[None] * order + [int(v) for v in most],
                      sm={'aic': _f(res.aic), 'bic': _f(res.bic), 'llf': _f(res.llf)},
                      spec={'k': k, 'order': order, 'trend': trend, 'switching_trend': switching_trend, 'switching_variance': bool(switching_variance),
                            'switching_ar': switching_ar, 'starts': starts})


# ---- filters: Hodrick-Prescott, Baxter-King, Christiano-Fitzgerald -----------------------------------

def filter_defaults(S):
    """The defaults for the frequency: HP lambda by Ravn and Uhlig's rule
    1600 (s/4)^4 (6.25 yearly, 1600 quarterly, 129600 monthly), and the
    business-cycle band of 1.5 to 8 years with Baxter and King's K of 3 years;
    statsmodels' own defaults (1600; 6, 32 and 12) when the frequency is not
    known."""
    f = _per_year(S)
    if f is None:
        return {'per_year': None, 'lamb': 1600.0, 'low': 6.0, 'high': 32.0, 'K': 12}
    return {'per_year': f, 'lamb': 1600.0 * (f / 4.0) ** 4, 'low': max(2.0, 1.5 * f), 'high': 8.0 * f, 'K': max(1, int(round(3 * f)))}


FILTER_NAMES = {'hp': 'Hodrick-Prescott Filter', 'bk': 'Baxter-King Filter', 'cf': 'Christiano-Fitzgerald Filter'}


@api('timeseries.filter')
@_quietly
def filter_series(table, y, time=None, rows=None, excluded=None, method='hp', lamb=None, low=None, high=None, K=None, drift=True,
                  nlags=25, where=None, table_name='data'):
    """Trend and cycle by the Hodrick-Prescott filter (hpfilter), the
    Baxter-King band pass (bkfilter) or the Christiano-Fitzgerald asymmetric
    band pass (cffilter)."""
    from statsmodels.tsa.filters.bk_filter import bkfilter
    from statsmodels.tsa.filters.cf_filter import cffilter
    from statsmodels.tsa.filters.hp_filter import hpfilter
    if method not in FILTER_NAMES:
        return {'error': f'no filter {method!r}'}
    try:
        S = load(table, y, time, rows, excluded)
    except NoSeries as e:
        return {'error': str(e)}
    x, miss = _filled(S)
    n = len(x)
    D = filter_defaults(S)
    notes = []
    out = {'method': method, 'name': FILTER_NAMES[method], 'defaults': D}
    imports = []
    if method == 'hp':
        lam = float(lamb) if lamb not in (None, '') else D['lamb']
        if not lam > 0:
            return {'error': 'λ must be above 0'}
        if n < 4:
            return {'error': 'the filter needs at least 4 values'}
        cycle, trend = hpfilter(x, lam)
        out.update(lamb=lam, label=f'Hodrick-Prescott Filter (λ = {lam:.6g})')
        imports.append('from statsmodels.tsa.filters.hp_filter import hpfilter')
        call = f'cycle, trend = hpfilter(y, lamb={lam!r})'
        rule = D['per_year'] and abs(lam - D['lamb']) <= 1e-9 * D['lamb']
        notes.append('The trend minimises Σ(y − τ)² + λ Σ(Δ²τ)², that is τ = (I + λK\'K)⁻¹ y with K the second differences; the cycle is y − τ. '
                     + (f'λ = {lam:.6g} is Ravn and Uhlig\'s rule 1600 (s/4)⁴ for s = {D["per_year"]:.6g} observations a year.' if rule
                        else 'statsmodels\' default λ = 1600 is meant for quarterly data.' if lamb in (None, '') else ''))
    else:
        lo = float(low) if low not in (None, '') else D['low']
        hi = float(high) if high not in (None, '') else D['high']
        if not 2 <= lo < hi:
            return {'error': 'the band: periods from 2 up, the shorter below the longer'}
        if method == 'bk':
            KK = int(K) if K not in (None, '') else D['K']
            if KK < 1 or n <= 2 * KK + 2:
                return {'error': f'the series is too short for K = {KK}: it needs more than {2 * KK + 2} values'}
            cyc = np.asarray(bkfilter(x, lo, hi, KK), dtype=float)
            cycle = np.full(n, np.nan)
            cycle[KK:n - KK] = cyc
            trend = x - cycle
            out.update(low=lo, high=hi, K=KK, label=f'Baxter-King Filter ({lo:.6g} to {hi:.6g} periods, K = {KK})')
            imports.append('from statsmodels.tsa.filters.bk_filter import bkfilter')
            call = f'cycle = bkfilter(y, low={lo!r}, high={hi!r}, K={KK}); trend = y.iloc[{KK}:{n - KK}] - cycle   # K values lost at each end'
            notes.append(f'A symmetric moving average of 2K + 1 = {2 * KK + 1} terms that passes the cycles of {lo:.6g} to {hi:.6g} periods '
                         f'(the ideal band-pass weights cut at K and shifted to sum to zero); the first and the last {KK} values are lost. '
                         'What is left, y − cycle, is the trend and the noise faster than the band.')
        else:
            cycle, trend = cffilter(x, lo, hi, bool(drift))
            out.update(low=lo, high=hi, drift=bool(drift), label=f'Christiano-Fitzgerald Filter ({lo:.6g} to {hi:.6g} periods)')
            imports.append('from statsmodels.tsa.filters.cf_filter import cffilter')
            call = f'cycle, trend = cffilter(y, low={lo!r}, high={hi!r}, drift={bool(drift)})'
            notes.append(f'The asymmetric band pass of Christiano and Fitzgerald for a random walk: every value uses the whole series, so none is lost; '
                         f'it passes the cycles of {lo:.6g} to {hi:.6g} periods{" after the drift (a line through the first and last values) is removed" if drift else ""}. '
                         'trend is y − cycle.')
    cycle = np.asarray(cycle, dtype=float)
    trend = np.asarray(trend, dtype=float)
    if miss.any():
        cycle[miss] = np.nan
        notes.append(f'{_plural(int(miss.sum()), "missing value")} filled by linear interpolation for the filter; the cycle is left missing there.')
    ok = np.isfinite(cycle)
    out.update(trend=_arr(trend), cycle=_arr(cycle), cycle_sd=_f(np.std(cycle[ok], ddof=1)) if ok.sum() > 1 else None,
               cycle_n=int(ok.sum()), notes=notes, cycle_diag=diagnostics(cycle, nlags))
    c = _code_series(S, table_name, where, imports)
    if miss.any():
        c.append('y = y.interpolate(limit_direction="both")')
    c += [call, 'print(trend, cycle)']
    out['code'] = '\n'.join(c)
    p = [*_head(S, table_name, where, imports),
         'yf = y.interpolate(limit_direction="both")   # the missing values filled for the filter' if miss.any() else 'yf = y']
    if method == 'hp':
        p.append(f'cycle, trend = hpfilter(yf, lamb={out["lamb"]!r})')
    elif method == 'bk':
        p += [f'cycle = bkfilter(yf, low={out["low"]!r}, high={out["high"]!r}, K={out["K"]}).reindex(yf.index)   # K values lost at each end',
              'trend = yf - cycle   # y − cycle']
    else:
        p.append(f'cycle, trend = cffilter(yf, low={out["low"]!r}, high={out["high"]!r}, drift={bool(drift)})')
    if miss.any():
        p.append('cycle[y.isna()] = np.nan   # missing where the series is')
    p += ['', SIZE, 'fig, (ax, cx) = plt.subplots(2, 1, sharex=True, figsize=size, layout="constrained", gridspec_kw={"height_ratios": [53, 37]})',
          _trace('t', 'y', lines=False) + '   # the series',
          f'ax.plot(t, trend, color="{RED}", linewidth={_pt(1.8)})   # {"y − cycle" if method == "bk" else "the trend"}',
          f'cx.plot(t, cycle, color="{BASE}", linewidth={_pt(1.4)})   # the cycle',
          f'ax.set_title({J(S.y_name + (" and y − cycle" if method == "bk" else " and trend"))}, loc="left", fontsize=8); cx.set_title("Cycle", loc="left", fontsize=8)',
          f'ax.set_ylabel({J(S.y_name)}); cx.set_ylabel("Cycle"); cx.set_xlabel({J(_xlabel(S))})',
          f'fig.suptitle({J(out["label"])}, fontsize=10)', 'plt.show()']
    out['plot_code'] = {'filter': p}
    return out


# ---- the seasonal subseries plot ----------------------------------------------------------------------------

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


@api('timeseries.subseries')
@_quietly
def subseries(table, y, time=None, rows=None, excluded=None, period=12, nlags=None, where=None, table_name='data'):
    """The seasonal subseries plot of statsmodels' month_plot, quarter_plot and
    seasonal_plot: the values of each season (January, February ... or the
    k-th observation of each period) in time order side by side, each with the
    mean of the season. Monthly and quarterly dates are grouped by the calendar
    month or quarter, daily ones by the weekday, the rest by the position in
    the period counted from the first observation."""
    try:
        S = load(table, y, time, rows, excluded)
    except NoSeries as e:
        return {'error': str(e)}
    s = int(period or 0)
    by = 'position'
    dates = _dates(S.t.astype(np.int64)) if S.kind in DATE_KINDS else None
    if dates is not None and S.offset is not None:
        name = type(S.offset).__name__
        one = abs(int(getattr(S.offset, 'n', 1) or 1)) == 1
        if 'Month' in name and 'Semi' not in name and one and s == 12:
            by = 'month'
        elif 'Quarter' in name and one and s == 4:
            by = 'quarter'
        elif name in ('Day', 'BusinessDay') and one and s in (7, 5):
            by = 'weekday'
    if by == 'position' and s < 2:
        return {'error': 'the seasonal period must be at least 2'}
    if by == 'month':
        season, labels = np.asarray(dates.month) - 1, MONTHS
    elif by == 'quarter':
        season, labels = np.asarray(dates.quarter) - 1, ['Q1', 'Q2', 'Q3', 'Q4']
    elif by == 'weekday':
        season, labels = np.asarray(dates.dayofweek), WEEKDAYS
    else:
        season, labels = np.arange(S.n) % s, [str(j + 1) for j in range(s)]
    if S.n < 2 * len(set(season.tolist())):
        return {'error': 'the series needs at least two values of every season'}
    seasons, start = [], 0
    for j in range(len(labels)):
        idx = np.flatnonzero(season == j)
        if not len(idx):
            continue
        v = S.y[idx]
        ok = np.isfinite(v)
        seasons.append({'label': labels[j], 'x': list(range(start, start + len(idx))), 'slots': idx.tolist(), 'values': _arr(v),
                        'rows': [S.rows[i] for i in idx], 't': _arr(S.t[idx]), 'mean': _f(v[ok].mean()) if ok.any() else None,
                        'n': int(ok.sum()), 'sd': _f(v[ok].std(ddof=1)) if ok.sum() > 1 else None})
        start += len(idx)
    notes = []
    if not np.isfinite(S.y).all():
        notes.append('The mean of a season is that of its values present; statsmodels\' seasonal_plot draws no mean for a season with a missing value.')
    c = _code_series(S, table_name, where, ['from statsmodels.graphics.tsaplots import month_plot, quarter_plot, seasonal_plot'])
    if by == 'month':
        c += ['month_plot(y)   # matplotlib', 'print(y.groupby(y.index.month).mean())   # the mean lines']
    elif by == 'quarter':
        c += ['quarter_plot(y)   # matplotlib', 'print(y.groupby(y.index.quarter).mean())   # the mean lines']
    elif by == 'weekday':
        c += [f'seasonal_plot(y.groupby(y.index.dayofweek), {json.dumps(labels[:len(seasons)])})   # matplotlib',
              'print(y.groupby(y.index.dayofweek).mean())']
    else:
        c += [f'season = np.arange(len(y)) % {s}   # the position in the period, from the first value',
              f'seasonal_plot(y.groupby(season), {json.dumps([x["label"] for x in seasons])})   # matplotlib',
              'print(y.groupby(season).mean())']
    season_of = {'month': 'season = np.asarray(t.month) - 1   # the calendar month', 'quarter': 'season = np.asarray(t.quarter) - 1   # the quarter',
                 'weekday': 'season = np.asarray(t.dayofweek)   # the weekday, Monday first',
                 'position': f'season = np.arange(len(y)) % {s}   # the position in the period, from the first value'}[by]
    plot = [*_head(S, table_name, where), season_of, f'labels = {J(labels)}',
            '', SIZE, 'fig, ax = plt.subplots(figsize=size, layout="constrained")',
            'start, ticks, names = 0, [], []',
            'for j, label in enumerate(labels):   # each season\'s values side by side, in time order',
            '    v = y.to_numpy()[season == j]',
            '    if not len(v):', '        continue',
            '    x = start + np.arange(len(v))',
            '    ' + _trace('x', 'v'),
            '    if np.isfinite(v).any():',
            f'        ax.plot([x[0] - 0.35, x[-1] + 0.35], [np.nanmean(v)] * 2, color="{RED}", linewidth={_pt(2.5)})   # the mean of the season',
            '    ticks.append((x[0] + x[-1]) / 2); names.append(label); start += len(v)',
            'ax.set_xticks(ticks, names)',
            f'ax.set_xlabel({J("Position in the period of " + str(s) if by == "position" else "")})', f'ax.set_ylabel({J(y)})',
            f'ax.set_title({J(y + " seasonal subseries")})', 'plt.show()']
    return {'by': by, 'period': s if by == 'position' else len(labels), 'seasons': seasons, 'notes': notes, 'code': '\n'.join(c),
            'plot_code': {'subseries': plot}}


# ---- the theta model ---------------------------------------------------------------------------------------

@api('timeseries.theta')
@_quietly
def theta_model(table, y, time=None, rows=None, excluded=None, period=12, deseasonalize=True, use_test=True, method='auto', theta=2.0,
                use_mle=False, level=0.95, h=25, nlags=25, where=None, table_name='data', holdback=0, cut=0, season=0):
    """The theta method of Assimakopoulos and Nikolopoulos (2000) with
    statsmodels' ThetaModel: the series is tested for seasonality and
    deseasonalized, alpha comes from simple exponential smoothing and b0
    from a linear trend (or both from an IMA(1, 1) with drift by MLE), and the
    forecasts combine the two theta lines (Hyndman and Billah 2003)."""
    from statsmodels.tsa.forecasting.theta import ThetaModel
    try:
        S = load(table, y, time, rows, excluded, holdback=holdback, cut=cut, season=season)
    except NoSeries as e:
        return {'error': str(e)}
    x, miss = _filled(S)
    n = len(x)
    level = float(level or 0.95)
    h = max(0, int(h or 0))
    th = float(theta if theta not in (None, '') else 2.0)
    if not th >= 1:
        return {'error': 'θ must be at least 1'}
    if n < 8:
        return {'error': 'the theta model needs at least 8 values'}
    s = int(period or 0)
    notes = []
    des = bool(deseasonalize) and s >= 2
    if des and n < 2 * s:
        des = False
        notes.append(f'The series is shorter than two periods of {s}: it is not deseasonalized.')
    method = method if method in ('auto', 'additive', 'multiplicative') else 'auto'
    with _quiet():
        mod = ThetaModel(x, period=s if des else None, deseasonalize=des, use_test=bool(use_test), method=method)
        res = mod.fit(use_mle=bool(use_mle))
        b0, alpha = (float(v) for v in res.params)
        seasonal_found = bool(des and mod._has_seasonality)
        meth = mod.method
        sigma2 = float(res.sigma2)
        if h:
            mean = np.asarray(res.forecast(h, theta=th), dtype=float)
            pi_sm = res.prediction_intervals(h, theta=th, alpha=1 - level)
            sm_lo, sm_hi = pi_sm['lower'].to_numpy(dtype=float), pi_sm['upper'].to_numpy(dtype=float)
        yd, seas = mod._deseasonalize_data() if seasonal_found else (x, np.empty(0))
    z = stats.norm.ppf(0.5 + level / 2)
    if h:
        # statsmodels' prediction_intervals take sigma^2 (1 + (h - 1)(1 + (alpha - 1)^2)); the
        # IMA(1, 1) that the theta method is has psi_j = alpha, so sigma^2 (1 + (h - 1) alpha^2)
        fse = math.sqrt(sigma2) * np.sqrt(1 + np.arange(h) * alpha ** 2)
        fcd = _forecast(S, h, mean, fse, mean - z * fse, mean + z * fse)
        fcd['sm_lower'], fcd['sm_upper'] = _arr(sm_lo), _arr(sm_hi)
    else:
        fcd = _forecast(S, 0, [], [], [], [])
    # the one-step-ahead theta forecasts from every origin, with the parameters of the whole fit:
    # simple exponential smoothing from the first value, plus the drift of the theta line
    w = (th - 1) / th if th < 4.0 / np.finfo(np.double).eps else 1.0
    yd = np.asarray(yd, dtype=float)
    lev = np.empty(n)
    prev = yd[0]
    for j in range(n):
        lev[j] = prev                       # the forecast of yd[j] from yd[:j]
        prev = prev + alpha * (yd[j] - prev)
    one = prev                              # the forecast of the next value, statsmodels' one_step
    jj = np.arange(n, dtype=float)
    drift = b0 * (1 / alpha - (1 - alpha) ** jj / alpha) if alpha > 0 else np.zeros(n)
    fitted = w * drift + lev
    if seasonal_found:
        fac = np.asarray(seas, dtype=float)[np.arange(n) % s]
        fitted = fitted * fac if meth.startswith('mul') else fitted + fac
    fitted[0] = np.nan
    valid = ~miss & np.isfinite(fitted)
    sse = float(np.sum((x - fitted)[valid] ** 2))
    nv = int(valid.sum())
    st = _fit_stats(x, fitted, valid, 2, nv * (math.log(2 * math.pi * sse / nv) + 1) if sse > 0 else float('nan'))
    rows_p = [{'term': 'Trend Slope (b0)', 'estimate': _f(b0)}, {'term': 'Level Smoothing Weight (α)', 'estimate': _f(alpha)},
              {'term': 'Theta (θ)', 'estimate': _f(th)}, {'term': 'Innovation Variance (σ²)', 'estimate': _f(sigma2)}]
    summary = [['DF', st['df'], 'int'], ['Sum of Squared Errors', st['sse']], ['Variance Estimate', st['variance']], ['Standard Deviation', st['sd']],
               ["Akaike's 'A' Information Criterion", st['aic']], ["Schwarz's Bayesian Criterion", st['sbc']], ['AICc', st['aicc']],
               ['RSquare', st['rsquare']], ['RSquare Adj', st['rsquare_adj']], ['MAPE', st['mape']], ['MAE', st['mae']], ['−2LogLikelihood', st['m2ll']],
               ['Method', 'IMA(1, 1) by MLE' if use_mle else 'OLS and SES', 'text'],
               ['Deseasonalized', (f'{"multiplicative" if meth.startswith("mul") else "additive"}, period {s}' if seasonal_found else 'no'), 'text']]
    notes.append(f'ThetaModel: the forecast is ((θ − 1)/θ) b0 [h − 1 + 1/α − (1 − α)^T/α] plus the simple exponential smoothing forecast, '
                 f'{"reseasonalized" if seasonal_found else "with no seasonal adjustment"}; θ = 2 is the original theta method, which is simple '
                 'exponential smoothing with half the slope as drift (Hyndman and Billah 2003).')
    if des:
        notes.append('The seasonality test (the autocorrelation at the seasonal lag, at 10%) ' + (
            'found a seasonal pattern: the series is deseasonalized by seasonal_decompose.' if seasonal_found else
            'found no seasonal pattern: the series is not deseasonalized.') if use_test else
            ('The series is deseasonalized by seasonal_decompose without the seasonality test.'))
    if h:
        ratio = (sm_hi[-1] - mean[-1]) / (z * fse[-1]) if fse[-1] > 0 else float('nan')
        notes.append(f'Prediction intervals: σ√(1 + (h − 1)α²), those of the IMA(1, 1) with drift that the method is, with statsmodels\' σ² = {sigma2:.6g}. '
                     f'statsmodels 0.14.6\'s prediction_intervals use σ²(1 + (h − 1)(1 + (α − 1)²)) instead, which is not that model\'s variance: '
                     f'its interval at h = {h} is {ratio:.3g} times as wide. '
                     + ('statsmodels takes σ² from an IMA(1, 1) with drift fitted to the series as it is, before any deseasonalizing.' if not use_mle else ''))
    notes.append('Theta has no likelihood of its own: the fit statistics are those of the one-step-ahead theta forecasts from each origin with the '
                 'parameters of the whole fit (k = 2: α and b0), as for the smoothing models.')
    if miss.any():
        notes.append(f'{_plural(int(miss.sum()), "missing value")} filled by linear interpolation for the fit; they are left out of the fit statistics.')
    c = _code_series(S, table_name, where, ['from statsmodels.tsa.forecasting.theta import ThetaModel'])
    if miss.any():
        c.append('y = y.interpolate(limit_direction="both")')
    c.append(f'mod = ThetaModel(y.to_numpy(), period={s if des else None}, deseasonalize={des}, use_test={bool(use_test)}, method={method!r})')
    c.append(f'res = mod.fit(use_mle={bool(use_mle)}); print(res.summary())')
    if h:
        c.append(f'fc = res.forecast({h}, theta={th!r})')
        c.append(f'alpha = res.params["alpha"]; half = {z:.6f} * np.sqrt(res.sigma2 * (1 + np.arange({h}) * alpha**2))   # the IMA(1, 1) interval')
        c.append('print(pd.DataFrame({"forecast": fc, "lower": fc - half, "upper": fc + half}))')
        c.append(f'print(res.prediction_intervals({h}, theta={th!r}, alpha={1 - level:.6g}))   # statsmodels\' own, wider')
    fitted_v = np.where(valid, fitted, np.nan)
    resid = np.where(valid, x - fitted, np.nan)
    sd = st['sd'] if st['sd'] is not None else float('nan')
    # the graphs: the model fitted as above, and the one-step theta forecasts from each origin as the report makes them
    name = f'Theta Model (θ = {th:.6g})'
    fit = ['yi = y.interpolate(limit_direction="both")   # the missing values filled for the fit' if miss.any() else 'yi = y',
           f'mod = ThetaModel(yi.to_numpy(), period={s if des else None}, deseasonalize={des}, use_test={bool(use_test)}, method={method!r})',
           f'res = mod.fit(use_mle={bool(use_mle)})', f'theta, b0, alpha = {th!r}, res.params["b0"], res.params["alpha"]',
           'yd, fac = mod._deseasonalize_data() if mod._has_seasonality else (yi.to_numpy(), None)   # the series as the fit takes it (statsmodels\' own deseasonalizing)',
           'lev = np.empty(len(yd)); prev = yd[0]',
           'for j in range(len(yd)):   # simple exponential smoothing: the forecast of each value from the ones before it',
           '    lev[j] = prev; prev = prev + alpha * (yd[j] - prev)',
           'fv = (theta - 1) / theta * b0 * (1 / alpha - (1 - alpha) ** np.arange(len(yd)) / alpha) + lev   # with the drift of the theta line']
    if seasonal_found:
        fit.append(f'fv = fv * fac[np.arange(len(yd)) % {s}] if mod.method.startswith("mul") else fv + fac[np.arange(len(yd)) % {s}]   # the seasonal pattern put back')
    fit += ['fv[0] = np.nan   # the first value has no forecast', _z_line(level), 'ok = y.notna().to_numpy() & np.isfinite(fv)',
            'sd = np.sqrt(np.sum((yi.to_numpy() - fv)[ok] ** 2) / (ok.sum() - 2))   # the standard deviation of the one-step errors (α and b0 fitted)',
            *_band_lines(se='sd', resid='yi.to_numpy() - fv')]
    if h:
        fit += [f'f_mean = np.asarray(res.forecast({h}, theta=theta), dtype=float)',
                f'f_se = np.sqrt(res.sigma2 * (1 + np.arange({h}) * alpha ** 2))   # the IMA(1, 1) with drift that the method is: σ²(1 + (h − 1)α²)',
                'f_lower, f_upper = f_mean - z * f_se, f_mean + z * f_se',
                _when(['smpi'], f'pi = res.prediction_intervals({h}, theta=theta, alpha={1 - level:.6g})   # statsmodels\' Prediction Intervals (the red triangle)',
                      'f_lower, f_upper = pi["lower"].to_numpy(), pi["upper"].to_numpy()'),
                _future_line(S, h)]
    plot_code, plot_frag = _model_plots(S, table_name, where, name, ['from statsmodels.tsa.forecasting.theta import ThetaModel'], fit, h, nlags)
    return _model_out(S, 'theta', name, fitted_v, resid, np.where(valid, sd, np.nan), level, fcd, st, summary,
                      {'columns': 'theta', 'rows': rows_p}, nlags, 1, notes, '\n'.join(c), plot_code=plot_code, plot_frag=plot_frag,
                      b0=_f(b0), alpha=_f(alpha), sigma2=_f(sigma2), one_step=_f(one), seasonal_found=seasonal_found, method=meth,
                      spec={'theta': th, 'period': s, 'deseasonalize': des, 'use_test': bool(use_test), 'use_mle': bool(use_mle)})


# ---- the Zivot-Andrews test --------------------------------------------------------------------------------

ZA_LABELS = (('c', 'Break in intercept'), ('t', 'Break in trend'), ('ct', 'Break in intercept and trend'))


@api('timeseries.zivot')
@_quietly
def zivot(table, y, time=None, rows=None, excluded=None, trim=0.15, maxlag=None, autolag='AIC', nlags=None, where=None, table_name='data'):
    """The Zivot-Andrews test of a unit root against a stationary series with
    one break in the intercept, the trend or both at an unknown date
    (statsmodels' zivot_andrews); the break date is the one that makes the
    test statistic smallest."""
    from statsmodels.tsa.stattools import zivot_andrews
    try:
        S = load(table, y, time, rows, excluded)
    except NoSeries as e:
        return {'error': str(e)}
    pos = np.flatnonzero(np.isfinite(S.y))
    v = S.y[pos]
    trim = float(trim if trim not in (None, '') else 0.15)
    ml = int(maxlag) if maxlag not in (None, '') else None
    al = autolag if autolag in ('AIC', 'BIC', 't-stat') else None
    if len(v) < 20:
        return {'error': 'the Zivot-Andrews test needs at least 20 values'}
    out = []
    for reg, label in ZA_LABELS:
        try:
            with _quiet():
                st, p, cv, lags, bp = zivot_andrews(v, trim=trim, maxlag=ml, regression=reg, autolag=al)
            slot = int(pos[int(bp)])
            out.append({'test': label, 'regression': reg, 'stat': _f(st), 'p': _f(p), 'lags': int(lags), 'break_slot': slot,
                        'break': _f(S.t[slot]), 'break_row': S.rows[slot], 'c1': _f(cv['1%']), 'c5': _f(cv['5%']), 'c10': _f(cv['10%'])})
        except (ValueError, np.linalg.LinAlgError) as e:
            out.append({'test': label, 'regression': reg, 'error': str(e)})
    c = _code_series(S, table_name, where, ['from statsmodels.tsa.stattools import zivot_andrews'])
    c += ['v = y.dropna()',
          'for reg in ("c", "t", "ct"):   # a break in the intercept, the trend, both',
          f'    stat, p, crit, lags, bp = zivot_andrews(v.to_numpy(), trim={trim!r}, maxlag={ml!r}, regression=reg, autolag={al!r})',
          '    print(reg, stat, p, crit, lags, v.index[bp])   # the break: the last observation before the shift']
    notes = ['H0: a unit root with a break; H1: stationary with a break at an unknown date, where the test statistic (the t ratio of the lagged level) '
             'is smallest. The break date is the last observation before the shift (Zivot and Andrews\' T_B). statsmodels follows Baum\'s '
             'approximation (the lags chosen once, for the model without breaks) and interpolates p-values and critical values in its own '
             'simulated tables, which are close to Zivot and Andrews\' (1992).']
    if len(v) < S.n:
        notes.append(f'{_plural(S.n - len(v), "missing value")} left out, as in the ADF tests.')
    regs = [(t['regression'], {'c': 'intercept', 't': 'trend', 'ct': 'both'}[t['regression']]) for t in out if not t.get('error')]
    plot = None
    if regs:
        dated = S.kind in DATE_KINDS
        plot = [*_head(S, table_name, where, ['from statsmodels.tsa.stattools import zivot_andrews', *(['import matplotlib.dates as mdates'] if dated else [])]),
                'pos = np.flatnonzero(y.notna().to_numpy()); v = y.to_numpy()[pos]   # the values present',
                'breaks = {}   # each break date, with the models that put the break there',
                f'for reg, short in {tuple(regs)!r}:',
                f'    bp = zivot_andrews(v, trim={trim!r}, maxlag={ml!r}, regression=reg, autolag={al!r})[4]',
                ('    when = mdates.date2num(t[pos[bp]])   # the last observation before the shift, in the date axis\'s days' if dated else
                 '    when = float(t[pos[bp]])   # the last observation before the shift'),
                '    breaks.setdefault(when, []).append(short)',
                '', SIZE, 'fig, ax = plt.subplots(figsize=size, layout="constrained")', _trace('t', 'y'),
                'for i, (when, models) in enumerate(breaks.items()):',
                f'    ax.axvline(when, color="{RED}", linewidth={_pt(1.3)}, linestyle=(":", "--", "-.")[i % 3])',
                f'    ax.text(when, 1 - 0.1 * i, " " + ", ".join(models), transform=ax.get_xaxis_transform(), ha="left", va="top", fontsize=7, color="{MUTED}")',
                *_labels(S, S.y_name, f'{S.y_name} Zivot-Andrews breaks'), 'plt.show()']
    return {'tests': out, 'n': int(len(v)), 'trim': trim, 'notes': notes, 'code': '\n'.join(c), 'plot_code': {'breaks': plot}}


# ---- ARDL, the error correction form and the bounds test --------------------------------------------------

PSS_CASES = {1: 'no intercept, no trend', 2: 'restricted intercept, no trend', 3: 'unrestricted intercept, no trend',
             4: 'unrestricted intercept, restricted trend', 5: 'unrestricted intercept and trend'}
CASES_OF_TREND = {'n': (1,), 'c': (3, 2), 'ct': (4, 5)}


def _lags_text(v, ar=False):
    """A lag specification of ardl_select_order's tables: None (left out), a
    largest lag (the lags 1 to p of y, 0 to q of an input), or the lags
    themselves (a global search)."""
    if v is None:
        return 'none'
    if isinstance(v, (tuple, list)):
        return ', '.join(str(int(x)) for x in v) if len(v) else 'none'
    lo = 1 if ar else 0
    return 'none' if int(v) < lo else str(lo) if int(v) == lo else f'{lo}–{int(v)}'


def pss_bounds(stat, k, case):
    """The PSS (2001) bounds for k inputs from statsmodels' own tables
    (statsmodels.tsa.ardl.pss_critical_values, 32 million simulations) and
    its p-value response surfaces. UECMResults.bounds_test in statsmodels
    0.14.6 looks the tables up at k + 1 (the number of variables with y), so
    they are read here at k, the number of inputs, as the tables are keyed."""
    from statsmodels.tsa.ardl import pss_critical_values as pss
    from statsmodels.tsa.ardl.model import _pss_pvalue
    lo, hi = pss.crit_vals[(k, case, False)], pss.crit_vals[(k, case, True)]
    rows = [{'level': f'{100 - pct:g}%', 'pct': float(pct), 'lower': _f(lo[i]), 'upper': _f(hi[i])} for i, pct in enumerate(pss.crit_percentiles)]
    return rows, _f(_pss_pvalue(stat, k, case, False)), _f(_pss_pvalue(stat, k, case, True))


@api('timeseries.ardl')
@_quietly
def ardl(table, y, time=None, rows=None, excluded=None, inputs=None, maxlag=4, maxorder=4, order=None, trend='c', ic='aic', glob=False,
         causal=False, seasonal=False, period=12, case=None, level=0.95, h=25, nlags=25, where=None, table_name='data', holdback=0, cut=0, season=0):
    """An autoregressive distributed lag model of the series on the inputs,
    ARDL(p, q1, ..., qk) by least squares (statsmodels' ARDL), its orders
    chosen by AIC or BIC (ardl_select_order) unless given; the long-run
    coefficients of the level relation, the unrestricted error correction
    form (UECM) and the Pesaran, Shin and Smith (2001) bounds test of a
    level relationship; forecasts with the inputs' future values."""
    from statsmodels.tsa.ardl import ARDL, UECM, ardl_select_order
    names_in = [c for c in dict.fromkeys(inputs or []) if c and c != y]
    if not names_in:
        return {'error': 'ARDL models need inputs: cast columns in Input List'}
    if len(names_in) > 9:
        return {'error': 'at most 9 inputs (statsmodels\' bounds test tables go to 10 variables)'}
    trend = trend if trend in ('n', 'c', 'ct') else 'c'
    ic = 'bic' if ic == 'bic' else 'aic'
    level = float(level or 0.95)
    h = max(0, int(h or 0))
    maxlag, maxorder = max(1, int(maxlag or 1)), max(0, int(maxorder or 0))
    s = int(period or 0)
    seasonal = bool(seasonal) and s >= 2
    try:
        S = load(table, y, time, rows, excluded, names_in, holdback=holdback, cut=cut, season=season)
        E, Ef, xnames, _start, xnotes = _exog(S, [{'name': c} for c in names_in], h)
    except NoSeries as e:
        return {'error': str(e)}
    notes = list(xnotes)
    x, miss = _filled(S)
    n = len(x)
    Y = pd.Series(x, name=y)
    X = pd.DataFrame(E, columns=xnames)
    kw = {'trend': trend, 'causal': bool(causal), 'seasonal': seasonal, 'period': s if seasonal else None}
    sel = None
    with _quiet():
        if order:
            p_ = int(order.get('p') or 0)
            q_ = {c: (None if order.get('q', {}).get(c) in (None, '') else int(order['q'][c])) for c in names_in}
            use = [c for c in names_in if q_[c] is not None]
            model = ARDL(Y, p_ or None, X[use] if use else None, {c: q_[c] for c in use} if use else 0, **kw)
            how = 'as given'
        else:
            n_models = (maxlag + 1) * (maxorder + 2) ** len(names_in)
            if glob:
                bits = maxlag + len(names_in) * (maxorder + 1)
                n_models = 2 ** bits
                if n_models > 4096:
                    return {'error': f'the global search would fit {n_models} models; at most 4096 (lower the largest lags)'}
            if n - max(maxlag, maxorder) < 3 * (1 + maxlag + len(names_in) * (maxorder + 1)):
                return {'error': f'too few observations ({n}) for lags up to {max(maxlag, maxorder)} of {1 + len(names_in)} series'}
            sel = ardl_select_order(Y, maxlag, X, maxorder, ic=ic, glob=bool(glob), **kw)
            model = sel.model
            how = f'by {ic.upper()} among {n_models} models'
        res = model.fit()
    yname = model.endog_names
    pnames = list(res.params.index)
    est = np.asarray(res.params, dtype=float)
    C = np.asarray(res.cov_params(), dtype=float)
    ar_lags = [int(v) for v in (model.ar_lags or [])]
    dl = {c: [int(v) for v in lags] for c, lags in (model.dl_lags or {}).items()}
    inc = [c for c in names_in if c in dl and len(dl[c])]
    dropped = [c for c in names_in if c not in inc]
    with _quiet():
        se, tv, pv = (np.asarray(v, dtype=float) for v in (res.bse, res.tvalues, res.pvalues))
    rows_p = []
    for j, nm in enumerate(pnames):
        term = 'Intercept' if nm == 'const' else 'Trend' if nm == 'trend' else nm
        rows_p.append({'term': term, 'estimate': _f(est[j]), 'se': _f(se[j]), 't': _f(tv[j]), 'p': _f(pv[j]), 'sm': nm})
    # the long-run coefficients of the level relation y = θ0 + θ'x, by the delta method
    # (the negatives of UECM's ci_params, with its ci_bse)
    ar_idx = [pnames.index(f'{yname}.L{i}') for i in ar_lags]
    den = 1.0 - float(est[ar_idx].sum()) if ar_idx else 1.0
    lr = []
    terms = [('Intercept', [pnames.index('const')] if 'const' in pnames else []), ('Trend', [pnames.index('trend')] if 'trend' in pnames else [])]
    terms += [(c, [pnames.index(f'{c}.L{j}') for j in dl[c]]) for c in inc]
    for label, cols in terms:
        if not cols:
            continue
        num = float(est[cols].sum())
        g = np.zeros(len(est))
        g[cols] = 1.0 / den
        g[ar_idx] = num / den ** 2
        th = num / den
        s_ = math.sqrt(max(0.0, float(g @ C @ g)))
        t_ = th / s_ if s_ > 0 else float('nan')
        # normal p-values, as UECM's ci_pvalues have them
        lr.append({'term': label, 'estimate': _f(th), 'se': _f(s_), 't': _f(t_), 'p': _f(2 * stats.norm.sf(abs(t_))) if math.isfinite(t_) else None})
    # the unrestricted error correction form and the bounds test
    case = int(case) if case not in (None, '') else CASES_OF_TREND[trend][0]
    if case not in CASES_OF_TREND[trend]:
        return {'error': f'bounds test case {case} does not go with the trend {trend!r}: the cases are {", ".join(map(str, CASES_OF_TREND[trend]))}'}
    bounds, ecm = None, None
    if inc:
        lags_u = max([1] + ar_lags)
        order_u = {c: max(1, max(dl[c])) for c in inc}
        raised = [c for c in inc if max(dl[c]) < 1]
        with _quiet():
            ures = UECM(Y, lags_u, X[inc], order_u, trend=trend, causal=bool(causal)).fit()
            bt = ures.bounds_test(case=case)
        stat = float(bt.stat)
        kx = len(inc)
        crit, p_lo, p_hi = pss_bounds(stat, kx, case)
        sm_crit = [{'level': f'{100 - float(pct):g}%', 'lower': _f(bt.crit_vals['lower'].iloc[i]), 'upper': _f(bt.crit_vals['upper'].iloc[i])}
                   for i, pct in enumerate(bt.crit_vals.index)]
        c95 = next(r for r in crit if r['pct'] == 95.0)
        verdict = ('reject' if stat > c95['upper'] else 'accept' if stat < c95['lower'] else 'inconclusive')
        bounds = {'stat': _f(stat), 'case': case, 'case_label': PSS_CASES[case], 'k': kx, 'crit': crit, 'p_lower': p_lo, 'p_upper': p_hi,
                  'verdict': verdict, 'sm_crit': sm_crit, 'sm_p_lower': _f(bt.p_values['lower']), 'sm_p_upper': _f(bt.p_values['upper']),
                  'n_restrictions': int(kx + 1 + (1 if case in (2, 4) else 0)), 'raised': raised}
        un = list(ures.params.index)
        with _quiet():
            use_ = np.asarray(ures.bse, dtype=float), np.asarray(ures.tvalues, dtype=float), np.asarray(ures.pvalues, dtype=float)
        ecm = [{'term': 'Intercept' if nm == 'const' else 'Trend' if nm == 'trend' else nm, 'estimate': _f(ures.params.iloc[j]), 'se': _f(use_[0][j]),
                't': _f(use_[1][j]), 'p': _f(use_[2][j]), 'sm': nm} for j, nm in enumerate(un)]
        speed = _f(ures.params.get(f'{yname}.L1'))
    else:
        speed = None
        notes.append('The selected model has no input left: there is no level relation to test.')
    # fitted values, forecasts
    fitted = np.full(n, np.nan)
    fv = np.asarray(res.fittedvalues, dtype=float)
    fitted[n - len(fv):] = fv
    with _quiet():
        pr = res.get_prediction()
        fse_in = np.full(n, np.nan)
        fse_in[n - len(fv):] = np.asarray(pr.se_mean, dtype=float)[-len(fv):]
        if h:
            Xf = pd.DataFrame(Ef, columns=xnames)
            pf = res.get_prediction(start=n, end=n + h - 1, exog_oos=Xf)
            sf = pf.summary_frame(alpha=1 - level)
            fcd = _forecast(S, h, sf['mean'], sf['mean_se'], sf['mean_ci_lower'], sf['mean_ci_upper'])
        else:
            fcd = _forecast(S, 0, [], [], [], [])
    valid = ~miss & np.isfinite(fitted)
    kk = len(est)                             # JMP's count: the variance not counted
    st = _fit_stats(x, fitted, valid, kk, -2 * float(res.llf))
    ordr = tuple(int(v) for v in model.ardl_order)
    name = f'ARDL({", ".join(str(v) for v in ordr)}) with {", ".join(inc) if inc else "no input"}'
    summary = [['DF', st['df'], 'int'], ['Sum of Squared Errors', st['sse']], ['Variance Estimate', st['variance']], ['Standard Deviation', st['sd']],
               ["Akaike's 'A' Information Criterion", st['aic']], ["Schwarz's Bayesian Criterion", st['sbc']], ['AICc', st['aicc']],
               ['RSquare', st['rsquare']], ['RSquare Adj', st['rsquare_adj']], ['MAPE', st['mape']], ['MAE', st['mae']], ['−2LogLikelihood', st['m2ll']],
               ['Orders', how, 'text']]
    selection = []
    if sel is not None:
        crit_s = sel.aic if ic == 'aic' else sel.bic
        for rank, (val, spec) in enumerate(crit_s.head(10).items(), 1):
            lags, orders = spec
            selection.append({'rank': rank, 'ic': _f(val), 'ar': _lags_text(lags, ar=True), **{f'q_{c}': _lags_text((orders or {}).get(c)) for c in names_in}})
    hold = n - len(fv)
    notes.insert(0, f'Least squares, the conditional maximum likelihood of statsmodels\' ARDL: the first {_plural(hold, "observation")} '
                    f'give the lags their starting values. Orders {how}' + (f' ({"all subsets of lags" if glob else "every lag up to each order"}; '
                                                                          f'up to {maxlag} lags of {y} and {maxorder} of each input).' if sel is not None else '.'))
    notes.append(f'statsmodels counts σ² in its AIC: {res.aic:.6g} (BIC {res.bic:.6g}); the table follows JMP, k = {kk}.')
    if dropped:
        notes.append(f'The selection leaves out {", ".join(dropped)}.')
    if miss.any():
        notes.append(f'{_plural(int(miss.sum()), "missing value")} of {y} filled by linear interpolation for the fit: least squares on lags needs every value.')
    if bounds:
        if bounds['raised']:
            notes.append(f'The error correction form needs a lagged level of every input: {", ".join(bounds["raised"])} enter it with order 1.')
        if seasonal:
            notes.append('statsmodels\' bounds test refits the error correction form without the seasonal dummies.')
    # the code
    c = _code_series(S, table_name, where, ['from statsmodels.tsa.ardl import ARDL, UECM, ardl_select_order',
                                              'from statsmodels.tsa.ardl import pss_critical_values',
                                              'from statsmodels.tsa.ardl.model import _pss_pvalue'])
    if miss.any():
        c.append('y = y.interpolate(limit_direction="both")')
    c.append(f'Y = pd.Series(y.to_numpy(), name={json.dumps(y)})')
    c.append(f'X = d.loc[y.index, {json.dumps(names_in)}].reset_index(drop=True)')
    extra = f', trend={trend!r}' + (', causal=True' if causal else '') + (f', seasonal=True, period={s}' if seasonal else '')
    if order:
        use = [cc for cc in names_in if order.get('q', {}).get(cc) not in (None, '')]
        qd = '{' + ', '.join(f'{json.dumps(cc)}: {int(order["q"][cc])}' for cc in use) + '}'
        c.append(f'res = ARDL(Y, {int(order.get("p") or 0) or None}, X[{json.dumps(use)}], {qd}{extra}).fit()')
    else:
        c.append(f'sel = ardl_select_order(Y, {maxlag}, X, {maxorder}, ic={ic!r}{", glob=True" if glob else ""}{extra})')
        c.append(f'print(sel.{ic}.head(10))   # the best orders')
        c.append('res = sel.model.fit()')
    c.append('print(res.summary())')
    if bounds:
        c.append(f'uecm = UECM(Y, {max([1] + ar_lags)}, X[{json.dumps(inc)}], {json.dumps({cc: max(1, max(dl[cc])) for cc in inc})}, trend={trend!r}'
                 f'{", causal=True" if causal else ""}).fit()')
        c.append('print(uecm.summary()); print(uecm.ci_summary())   # the error correction form; the level relation is minus ci_params')
        c.append(f'bt = uecm.bounds_test(case={case}); print(bt.stat)')
        c.append(f'k = {len(inc)}   # the inputs: statsmodels 0.14.6\'s bounds_test reads its tables at k + 1, so read them at k')
        c.append(f'print(pd.DataFrame({{"lower": pss_critical_values.crit_vals[(k, {case}, False)], "upper": pss_critical_values.crit_vals[(k, {case}, True)]}}, '
                 'index=pss_critical_values.crit_percentiles))')
        c.append(f'print(_pss_pvalue(bt.stat, k, {case}, False), _pss_pvalue(bt.stat, k, {case}, True))   # p-values, all I(0) and all I(1)')
    held = S.hold is not None
    x_future = f'X_future = d.loc[y_hold.index, {json.dumps(names_in)}].reset_index(drop=True)   # the inputs of the held-back rows' if held else \
        'X_future = pd.DataFrame({' + ', '.join(f'{json.dumps(nm)}: {[_f(v) for v in Ef[:, j]]}' for j, nm in enumerate(xnames)) + '})'
    if h:
        c.append(x_future)
        c.append(f'print(res.get_prediction(start=len(Y), end=len(Y) + {h - 1}, exog_oos=X_future).summary_frame(alpha={1 - level:.6g}))')
    resid = np.where(valid, x - fitted, np.nan)
    # the graphs: the model fitted as above (the same order search), its predictions after the lags' starting values, the forecasts
    fit = ['yi = y.interpolate(limit_direction="both")   # the missing values filled for the fit' if miss.any() else 'yi = y',
           f'Y = pd.Series(yi.to_numpy(), name={json.dumps(y)})', f'X = d.loc[y.index, {json.dumps(names_in)}].reset_index(drop=True)   # the inputs']
    if order:
        fit.append(f'res = ARDL(Y, {int(order.get("p") or 0) or None}, X[{json.dumps(use)}], {qd}{extra}).fit()')
    else:
        fit.append(f'res = ardl_select_order(Y, {maxlag}, X, {maxorder}, ic={ic!r}{", glob=True" if glob else ""}{extra}).model.fit()   # the orders by {ic.upper()}')
    fit += [_z_line(level), 'pad = np.full(len(Y) - len(res.fittedvalues), np.nan)   # the first observations give the lags their starting values',
            'fv = np.r_[pad, np.asarray(res.fittedvalues, dtype=float)]',
            'se = np.r_[pad, np.asarray(res.get_prediction().se_mean, dtype=float)[-len(res.fittedvalues):]]',
            'ok = y.notna().to_numpy() & np.isfinite(fv)', *_band_lines(resid='yi.to_numpy() - fv')]
    if h:
        fit += [x_future if held else x_future + '   # the inputs of the forecast periods',
                f'sf = res.get_prediction(start=len(Y), end=len(Y) + {h - 1}, exog_oos=X_future).summary_frame(alpha={1 - level:.6g})',
                'f_mean, f_lower, f_upper = (sf[k].to_numpy() for k in ("mean", "mean_ci_lower", "mean_ci_upper"))', _future_line(S, h)]
    plot_code, plot_frag = _model_plots(S, table_name, where, name, ['from statsmodels.tsa.ardl import ARDL' if order else 'from statsmodels.tsa.ardl import ardl_select_order'],
                                        fit, h, nlags)
    return _model_out(S, 'ardl', name, np.where(valid, fitted, np.nan), resid, np.where(valid, fse_in, np.nan), level, fcd, st, summary,
                      {'columns': 'ardl', 'rows': rows_p}, nlags, len(ar_lags), notes, '\n'.join(c), plot_code=plot_code, plot_frag=plot_frag,
                      order=list(ordr), inputs_used=inc, long_run=lr, bounds=bounds, ecm=ecm, speed=speed, selection=selection,
                      sm={'aic': _f(res.aic), 'bic': _f(res.bic), 'llf': _f(res.llf), 'sigma2': _f(res.sigma2)},
                      spec={'trend': trend, 'ic': ic, 'glob': bool(glob), 'maxlag': maxlag, 'maxorder': maxorder, 'case': case,
                            'order': {'p': len(ar_lags) and max(ar_lags), 'q': {c_: (max(dl[c_]) if c_ in inc else None) for c_ in names_in}}})


# ---- models of models: the averaged forecast, the rolling-origin cross-validation ------------------------

MODEL_FNS = ('timeseries.arima', 'timeseries.smooth', 'timeseries.ets', 'timeseries.structural', 'timeseries.theta', 'timeseries.ardl',
             'timeseries.benchmark', 'timeseries.sma', 'timeseries.markov', 'timeseries.average')


def _run_member(member, base):
    """A model of the report, fitted by its own function (by name, as the page
    calls it) on the series and rows of the call."""
    from .registry import API
    fn = member.get('fn')
    if fn not in MODEL_FNS:
        return {'error': f'no model function {fn!r}'}
    args = {**(member.get('args') or {}), **base}
    import inspect
    sig = inspect.signature(API[fn])
    return API[fn](**{k: v for k, v in args.items() if k in sig.parameters})


def _indent(lines, pad='    '):
    return [pad + ln if ln else ln for ln in '\n'.join(lines).split('\n')]


@api('timeseries.average')
@_quietly
def average(table, y, members=None, time=None, rows=None, excluded=None, level=0.95, h=25, nlags=25, where=None, table_name='data',
            holdback=0, cut=0, season=0):
    """The averaged forecast of some of the report's models: the mean of
    their one-step-ahead predictions (where every member has one), of their
    forecasts, and of their prediction limits. The limits are the mean of the
    members': the members' forecast errors are correlated, and the standard
    error of the mean forecast is at most the mean of their standard errors
    (exactly that when the errors move together), so the interval errs on
    the wide side."""
    members = [m for m in (members or []) if isinstance(m, dict)]
    if len(members) < 2:
        return {'error': 'an averaged forecast needs at least two models'}
    try:
        S = load(table, y, time, rows, excluded, holdback=holdback, cut=cut, season=season)
    except NoSeries as e:
        return {'error': str(e)}
    level = float(level or 0.95)
    h = max(0, int(h or 0))
    base = dict(table=table, y=y, time=time, rows=rows, excluded=excluded, level=level, h=h, nlags=nlags, where=where, table_name=table_name,
                holdback=holdback, cut=cut, season=season)
    res = [_run_member(m, base) for m in members]
    names = [r.get('name') or m.get('name') or m.get('fn') for r, m in zip(res, members)]
    bad = [f'{nm}: {r["error"]}' for nm, r in zip(names, res) if r.get('error')]
    if bad:
        return {'error': 'a member could not be fitted: ' + '; '.join(bad)}
    if any(r.get('kind') == 'markov' for r in res):
        return {'error': 'a regime-switching model has no forecasts to average'}
    if h and any(len((r.get('forecast') or {}).get('mean') or []) < h for r in res):
        return {'error': 'every member needs its forecasts'}
    A = lambda key: np.array([[np.nan if v is None else v for v in r[key]] for r in res], dtype=float)   # noqa: E731
    F = lambda key: np.array([[np.nan if v is None else v for v in r['forecast'][key][:h]] for r in res], dtype=float)   # noqa: E731
    with np.errstate(invalid='ignore'):
        fitted = A('fitted').mean(axis=0)            # NaN where a member has no prediction
        fit_lo, fit_hi, fit_se = A('fit_lo').mean(axis=0), A('fit_hi').mean(axis=0), A('fit_se').mean(axis=0)
    v = np.asarray(S.y, dtype=float)
    valid = np.isfinite(v) & np.isfinite(fitted)
    if valid.sum() < 3:
        return {'error': 'the members\' one-step-ahead predictions have too few slots in common'}
    st = _fit_stats(v, fitted, valid, 0, float('nan'))
    if h:
        fcd = _forecast(S, h, F('mean').mean(axis=0), F('se').mean(axis=0), F('lower').mean(axis=0), F('upper').mean(axis=0))
    else:
        fcd = _forecast(S, 0, [], [], [], [])
    name = 'Average of ' + ', '.join(names)
    notes = [f'The mean of {_plural(len(res), "model")}\' one-step-ahead predictions (where every one has a prediction), forecasts and prediction limits: '
             + '; '.join(names) + '.',
             'The limits are the mean of the members\' limits: the members\' forecast errors are correlated, and the standard error of the mean forecast is at most '
             'the mean of their standard errors (exactly that when the errors move together), so the interval errs on the wide side. '
             'An average has no likelihood of its own: AIC and SBC are left out; MAPE, MAE and (with Forecast on Holdback) the holdback statistics compare.']
    summary = [['DF', st['df'], 'int'], ['Sum of Squared Errors', st['sse']], ['Variance Estimate', st['variance']], ['Standard Deviation', st['sd']],
               ['RSquare', st['rsquare']], ['RSquare Adj', st['rsquare_adj']], ['MAPE', st['mape']], ['MAE', st['mae']], ['Members', len(res), 'int']]
    for key in ('aic', 'sbc', 'aicc', 'm2ll'):
        st[key] = None
    # the code: each member fitted as in its report, then the mean
    imports = []
    for r in res:
        for i in (r.get('plot_frag') or {}).get('imports', []):
            if i not in imports and i != 'from scipy import stats':
                imports.append(i)
    fit = ['members_ = []   # (fitted, fit_lo, fit_hi, f_mean, f_lower, f_upper) of each member']
    for nm, r in zip(names, res):
        fit += ['', f'# {nm}, fitted as in its report', *r['plot_frag']['fit'],
                'members_.append((fitted, fit_lo, fit_hi' + (', f_mean, f_lower, f_upper))' if h else '))')]
    k6 = 6 if h else 3
    fit += ['', f'{"fitted, fit_lo, fit_hi, f_mean, f_lower, f_upper" if h else "fitted, fit_lo, fit_hi"} = (np.mean([m_[i] for m_ in members_], axis=0) for i in range({k6}))   # the mean: missing where a member has no prediction',
            'resid = y.to_numpy() - fitted']
    if h:
        fit.append(_future_line(S, h))
    plot_code, plot_frag = _model_plots(S, table_name, where, name, imports, fit, h, nlags)
    c = [code_head(table_name, ['from scipy import stats', *imports]), *_series_lines(S, where, graph=True), *fit,
         'print(pd.DataFrame({"forecast": f_mean, "lower": f_lower, "upper": f_upper}))' if h else 'print(fitted)']
    return _model_out(S, 'avg', name, np.where(valid, fitted, np.nan), np.where(valid, v - fitted, np.nan), np.where(valid, fit_se, np.nan), level, fcd, st,
                      summary, {'columns': 'smooth', 'rows': []}, nlags, 0, notes, '\n'.join(c), plot_code=plot_code, plot_frag=plot_frag,
                      fit_lo_override=[_arr(np.where(valid, fit_lo, np.nan)), _arr(np.where(valid, fit_hi, np.nan))],
                      members=names, spec={'members': [m.get('fn') for m in members]})


@api('timeseries.cv')
@_quietly
def cross_validate(table, y, models=None, time=None, rows=None, excluded=None, origins=5, horizon=12, step=None, nlags=25, where=None,
                   table_name='data', season=0):
    """Rolling-origin cross-validation (evaluation on a rolling forecasting
    origin): each model is fitted on the series up to an origin (an expanding
    window, the earliest origin first) and forecasts the next `horizon`
    values; origins are `step` apart, the last one `horizon` before the end.
    RMSE, MAE and MAPE for each origin and model, and their means over the
    origins. 'smui:progress tscv <done> <total>' lines for the page."""
    models = [m for m in (models or []) if isinstance(m, dict)]
    if not models:
        return {'error': 'no models to cross-validate'}
    K, H = max(1, int(origins or 5)), max(1, int(horizon or 12))
    step = max(1, int(step or H))
    try:
        S0 = load(table, y, time, rows, excluded)
    except NoSeries as e:
        return {'error': str(e)}
    cuts = [(K - 1 - j) * step for j in range(K)]           # the values left out after each origin's horizon
    if cuts[0] + H + 8 > S0.n:
        return {'error': f'the series has {S0.n} values: too few for {_plural(K, "origin")} {step} apart and a horizon of {H} (the first origin would keep {S0.n - cuts[0] - H})'}
    total, done = len(models) * K, 0
    print(f'smui:progress tscv 0 {total}', flush=True)
    out, fit_lines, imports = [], {}, []
    for m in models:
        mname = m.get('name') or m.get('fn')
        per = []
        for j, cut in enumerate(cuts):
            base = dict(table=table, y=y, time=time, rows=rows, excluded=excluded, h=H, nlags=nlags, where=where, table_name=table_name,
                        holdback=H, cut=cut, season=season)
            try:
                r = _run_member(m, base)
            except Exception as e:  # noqa: BLE001 - a fit that fails at one origin is reported there
                r = {'error': f'{type(e).__name__}: {e}'}
            done += 1
            print(f'smui:progress tscv {done} {total}', flush=True)
            n_train = S0.n - cut - H
            row = {'origin': j + 1, 't': _f(S0.t[n_train - 1]), 'n_train': n_train}
            hb = r.get('holdback') if not r.get('error') else None
            if r.get('error') or not hb or hb.get('rmse') is None:
                row['error'] = r.get('error') or 'no forecasts'
            else:
                row.update(n=hb['n'], rmse=hb['rmse'], mae=hb['mae'], mape=hb['mape'])
                if m.get('id') not in fit_lines and r.get('plot_frag'):
                    mname = r.get('name') or mname
                    fit_lines[m.get('id')] = (mname, r['plot_frag']['fit'])
                    for i in r['plot_frag'].get('imports', []):
                        if i not in imports:
                            imports.append(i)
            per.append(row)
        ok = [p for p in per if not p.get('error')]
        mean = {k: _f(np.mean([p[k] for p in ok])) if ok and all(p.get(k) is not None for p in ok) else None for k in ('rmse', 'mae', 'mape')}
        out.append({'id': m.get('id'), 'name': mname, 'origins': per, 'n_ok': len(ok), **mean})
    # the code: every origin, every model fitted on the series up to it, as in its report
    S1 = load(table, y, time, rows, excluded, holdback=H, season=season)
    lines = [code_head(table_name, [i for i in imports]), *_series_lines(S0, where, graph=False),
             f'y_cv, h = y, {H}   # the whole series, and the horizon', f'cuts = {cuts}   # the values after each origin\'s horizon, the earliest origin first',
             *HB_DEF, 'rows_cv = []', 'for cut in cuts:   # the series as it was at each origin: every value up to it, then the next h held back',
             '    y_all = y_cv.iloc[:len(y_cv) - cut]; y, y_hold = y_all.iloc[:-h], y_all.iloc[-h:]',
             *_indent(_time_lines(S1))]
    for mid, (mname, fl) in fit_lines.items():
        lines += _indent(['', f'# {mname}, fitted as in its report', *fl,
                          f'rows_cv.append({{"Model": {J(mname)}, "Origin": t[-1], **holdback_stats(y_hold, f_mean, y, {S1.season})}})'])
    lines += ['cv = pd.DataFrame(rows_cv); print(cv[["Model", "Origin", "N", "RMSE", "MAE", "MAPE"]].to_string())',
              'print(cv.groupby("Model", sort=False)[["RMSE", "MAE", "MAPE"]].mean().to_string())   # the means over the origins']
    return {'models': out, 'origins': K, 'horizon': H, 'step': step, 'cuts': cuts, 'n': S0.n,
            't_origins': [_f(S0.t[S0.n - c_ - H - 1]) for c_ in cuts], 'code': '\n'.join(lines)}
