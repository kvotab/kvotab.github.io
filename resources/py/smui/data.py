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

Column properties come in the meta (smui-table.js has what they mean):
missingCodes, the stored values the analyses treat as missing (they arrive
missing already, and are masked here again); valueLabels, [value, label]
pairs for a backend that writes a level itself (value_labels(),
level_label()); the values themselves are never replaced by their labels,
so a level the page sends (a target level, a By value) still matches.
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
        codes = _codes(m)
        if codes:
            if m.get('dataType') == 'numeric':
                v = np.where(np.isin(v, np.asarray(codes, dtype=float)), np.nan, v)
            else:
                v = np.array([None if x in codes else x for x in v], dtype=object)
        cols[m['name']] = v
        n = max(n, len(v))
    TABLES[tid] = {'version': int(version), 'meta': {m['name']: m for m in meta}, 'cols': cols, 'n': n}


def _codes(m):
    """A column's Missing Value Codes from its meta (numbers or texts)."""
    codes = m.get('missingCodes') or []
    try:
        codes = list(codes)
    except TypeError:
        return []
    if m.get('dataType') == 'numeric':
        return [float(x) for x in codes if isinstance(x, (int, float)) and not isinstance(x, bool)]
    return [x for x in codes if isinstance(x, str)]


def missing_codes(tid, name):
    """The Missing Value Codes of a column (Column Info), [] when it has none."""
    return _codes(meta(tid, name))


def value_labels(tid, name):
    """The Value Labels of a column (Column Info) as {value: label}: float
    values for a numeric column, texts for a character one; {} without."""
    m = meta(tid, name)
    out = {}
    for p in m.get('valueLabels') or []:
        try:
            v, lab = p[0], p[1]
        except (TypeError, IndexError, KeyError):
            continue
        if not isinstance(lab, str):
            continue
        if m.get('dataType') == 'numeric':
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[float(v)] = lab
        elif isinstance(v, str):
            out[v] = lab
    return out


def level_label(tid, name, value, default=None):
    """A level as the page shows it: its value label, or default (the value
    as text when default is None)."""
    labels = value_labels(tid, name)
    key = value
    if meta(tid, name).get('dataType') == 'numeric':
        try:
            key = float(value)
        except (TypeError, ValueError):
            key = value
    if key in labels:
        return labels[key]
    if default is not None:
        return default
    if isinstance(key, float) and key.is_integer():
        return str(int(key))
    return str(value)


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
