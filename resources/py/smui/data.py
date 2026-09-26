"""The page's tables on the Python side.

The page sends a table when it has changed (its version), as a list of
column descriptions and a list of value arrays. An analysis asks for a
DataFrame of some columns and some rows; the modeling type decides the
dtype:

  continuous  float (a date column stays numeric: milliseconds since 1970)
  ordinal     an ordered pandas Categorical in the page's level order
  nominal     an unordered Categorical in the page's level order

The DataFrame's index is the row number in the page's table, so results
per row (residuals, predictions, scores) can go back to the right rows.
"""
import numpy as np
import pandas as pd

from .registry import api

TABLES = {}


def set_table(tid, version, meta, arrays):
    cols = {}
    n = 0
    for m, a in zip(meta, arrays):
        if m.get('dataType') == 'numeric':
            v = np.asarray(a, dtype=float)
        else:
            # Only strings are values; None (and anything else, such as a
            # stray JS null) is missing.
            v = np.array([x if isinstance(x, str) else (None if x is None or not isinstance(x, (int, float)) else str(x)) for x in a], dtype=object)
        cols[m['name']] = v
        n = max(n, len(v))
    TABLES[tid] = {'version': int(version), 'meta': {m['name']: m for m in meta}, 'cols': cols, 'n': n}


def version(tid):
    t = TABLES.get(tid)
    return t['version'] if t else None


def meta(tid, name):
    return TABLES[tid]['meta'][name]


def raw(tid, name, rows=None):
    v = TABLES[tid]['cols'][name]
    return v if rows is None else v[np.asarray(rows, dtype=int)]


def is_categorical(tid, name):
    return meta(tid, name).get('modelingType') in ('nominal', 'ordinal')


def series(tid, name, rows=None, as_category=True):
    m = meta(tid, name)
    idx = np.arange(TABLES[tid]['n']) if rows is None else np.asarray(rows, dtype=int)
    v = TABLES[tid]['cols'][name][idx]
    if as_category and m.get('modelingType') in ('nominal', 'ordinal'):
        levels = m.get('levels') or sorted({x for x in v if x is not None and not (isinstance(x, float) and np.isnan(x))})
        if m.get('dataType') == 'numeric':
            vals = [None if np.isnan(x) else float(x) for x in v]
            levels = [float(x) for x in levels]
        else:
            vals = list(v)
        return pd.Series(pd.Categorical(vals, categories=levels, ordered=m.get('modelingType') == 'ordinal'), index=idx, name=name)
    if m.get('dataType') == 'numeric':
        return pd.Series(v.astype(float), index=idx, name=name)
    return pd.Series(v, index=idx, name=name, dtype=object)


def frame(table, columns, rows=None, dropna=True, as_category=True):
    """A DataFrame of the named columns (duplicates dropped, order kept)."""
    names = list(dict.fromkeys([c for c in columns if c]))
    df = pd.DataFrame({c: series(table, c, rows, as_category) for c in names})
    if dropna and len(names):
        df = df.dropna(how='any')
    return df


def weights(df, table, weight=None, freq=None):
    """Case weights: the weight column times the frequency column. Rows with
    a missing, negative or zero weight or frequency are dropped from df."""
    w = np.ones(len(df))
    if weight:
        w = w * series(table, weight, df.index, as_category=False).to_numpy(float)
    if freq:
        w = w * series(table, freq, df.index, as_category=False).to_numpy(float)
    ok = np.isfinite(w) & (w > 0)
    return df[ok], w[ok]


@api('data.status')
def status(table=None):
    return {'tables': {k: v['version'] for k, v in TABLES.items()}, 'has': table in TABLES if table else None}
