"""Tables and Tabulate: the backend of the Tables menu (Summary, Stack,
Split, Transpose, Join, Update, Missing Data Pattern), Analyze > Tabulate,
Cols > Columns Viewer, Analyze > Screening > Explore Missing Values and the
Python Script window.

Groups follow the page's order: the value order of a categorical column,
ascending numbers otherwise, missing values last (JMP puts a missing group
in the summary, as its own row). Quantiles are JMP's, numpy's 'weibull'
method: the (n+1)p-th value in order, interpolated. Freq repeats a row; a
Weight weights the moments as statsmodels' DescrStatsW does (the same as
Analyze > Distribution on this page).

A result is a list of columns, {name, dataType, values, ...}, that the
page turns into a data table; `from` names the source column whose
modeling type, value order and format the new column keeps.
"""
import contextlib
import io
import json
import math
import traceback

import numpy as np
import pandas as pd
from statsmodels.stats.weightstats import DescrStatsW

from . import data
from .registry import api
from .util import code_head, col, table as rtable

MAX_SCRIPT_OUTPUT = 200000


# ---- columns and groups ---------------------------------------------------------
def _n(tid):
    return data.TABLES[tid]['n']


def _idx(tid, rows):
    return np.arange(_n(tid)) if rows is None else np.asarray(rows, dtype=int)


def _numeric(tid, name):
    return data.meta(tid, name).get('dataType') == 'numeric'


def _categorical(tid, name):
    return data.meta(tid, name).get('modelingType') in ('nominal', 'ordinal')


_CLEAN = {}


def _clean(tid, name):
    """A column's values. A JavaScript null reaches Pyodide as its jsnull,
    which data.set_table keeps as the text 'jsnull'; the page sends every
    level of a categorical column (every character column is one), so a
    value outside the levels is a missing value."""
    t = data.TABLES[tid]
    key = (tid, t['version'], name)
    v = _CLEAN.get(key)
    if v is None:
        v = t['cols'][name]
        m = t['meta'][name]
        if m.get('dataType') == 'numeric':
            v = v.astype(float)
        elif m.get('levels') is not None:
            ok = {str(x) for x in m['levels']}
            v = np.array([x if (x is not None and x in ok) else None for x in v], dtype=object)
        else:
            v = np.array([None if (x is None or x == 'jsnull') else x for x in v], dtype=object)
        if len(_CLEAN) > 64:
            _CLEAN.clear()
        _CLEAN[key] = v
    return v


def _raw(tid, name, idx):
    return _clean(tid, name)[idx]


def _frame(tid, names, rows=None):
    """The columns as a DataFrame indexed by the page's row numbers, as
    data.frame(dropna=False) makes it: nominal and ordinal columns as
    Categoricals in the page's level order (ordinal ordered)."""
    idx = _idx(tid, rows)
    out = {}
    for nm in names:
        m = data.meta(tid, nm)
        v = _raw(tid, nm, idx)
        if m.get('modelingType') in ('nominal', 'ordinal'):
            numeric = m.get('dataType') == 'numeric'
            levels = [float(x) for x in (m.get('levels') or [])] if numeric else [str(x) for x in (m.get('levels') or [])]
            vals = [None if (x is None or (numeric and math.isnan(x))) else x for x in v]
            out[nm] = pd.Series(pd.Categorical(vals, categories=list(dict.fromkeys(levels)), ordered=m.get('modelingType') == 'ordinal'), index=idx)
        elif m.get('dataType') == 'numeric':
            out[nm] = pd.Series(v, index=idx, dtype=float)
        else:
            out[nm] = pd.Series(v, index=idx, dtype=object)
    return pd.DataFrame(out, index=idx)


def _missing(v):
    if v.dtype.kind == 'f':
        return np.isnan(v)
    return np.array([x is None or (isinstance(x, float) and math.isnan(x)) or x == '' for x in v], dtype=bool)


def _text(x):
    """A value as text, the way the page writes a number (15 digits)."""
    if x is None:
        return None
    if isinstance(x, (float, np.floating)):
        return None if math.isnan(x) else ('%.15g' % float(x))
    if isinstance(x, (int, np.integer)):
        return str(int(x))
    return str(x)


def _val(x):
    """A value for JSON: floats as floats (NaN for missing), text as text."""
    if x is None:
        return None
    if isinstance(x, (float, np.floating)):
        return float(x)
    if isinstance(x, (int, np.integer)):
        return float(x)
    return str(x)


def _codes(tid, name, idx):
    """Integer codes of a column's values in the page's order, missing last:
    (codes, the value of each code, missing)."""
    m = data.meta(tid, name)
    v = _raw(tid, name, idx)
    numeric = m.get('dataType') == 'numeric'
    miss = _missing(v)
    if m.get('modelingType') in ('nominal', 'ordinal') and m.get('levels') is not None:
        cats = [float(x) for x in m['levels']] if numeric else [str(x) for x in m['levels']]
        cats = list(dict.fromkeys(cats))
        present = set(v[~miss].tolist())
        cats += sorted(present - set(cats), key=lambda x: (isinstance(x, str), x))
    else:
        cats = sorted(set(v[~miss].tolist()))
    vv = v if numeric else np.array([None if mm else x for x, mm in zip(v, miss)], dtype=object)
    codes = np.asarray(pd.Categorical(vv, categories=cats).codes, dtype=np.int64)
    codes = np.where(codes < 0, len(cats), codes)
    return codes, cats, miss


def _groups(tid, names, idx):
    """The rows grouped by the columns, groups in the page's order: the group
    of each row and, per group, the value of each column (None or NaN for
    missing)."""
    if not names:
        return np.zeros(len(idx), dtype=np.int64), [()]
    cs = [_codes(tid, nm, idx) for nm in names]
    if not len(idx):
        return np.zeros(0, dtype=np.int64), []
    mat = np.column_stack([c[0] for c in cs])
    uniq, inv = np.unique(mat, axis=0, return_inverse=True)
    labels = []
    for row in uniq:
        lab = []
        for k, (codes, cats, miss) in enumerate(cs):
            c = int(row[k])
            if c >= len(cats):
                lab.append(float('nan') if _numeric(tid, names[k]) else None)
            else:
                lab.append(cats[c])
        labels.append(tuple(lab))
    return np.asarray(inv).reshape(-1), labels


def _slices(key):
    """For integer keys per row: {key: row positions}, in row order."""
    key = np.asarray(key)
    if not len(key):
        return {}
    order = np.argsort(key, kind='stable')
    ks = key[order]
    starts = np.concatenate([[0], np.flatnonzero(np.diff(ks)) + 1])
    ends = np.concatenate([starts[1:], [len(ks)]])
    return {int(ks[a]): order[a:b] for a, b in zip(starts, ends)}


def _unique_names(names):
    seen, out = {}, []
    for nm in names:
        base = nm
        k = seen.get(base, 0)
        new = base if k == 0 else f'{base} {k + 1}'
        while new in seen:
            k += 1
            new = f'{base} {k + 1}'
        seen[base] = k + 1
        seen.setdefault(new, 1)
        out.append(new)
    return out


def _column(name, values, numeric=None, **extra):
    vals = list(values)
    if numeric is None:
        numeric = all(v is None or isinstance(v, (int, float, np.integer, np.floating)) for v in vals)
    if numeric:
        vals = [None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v) for v in vals]
    else:
        vals = [_text(v) for v in vals]
    d = {'name': name, 'dataType': 'numeric' if numeric else 'character', 'values': vals}
    d.update(extra)
    return d


# ---- statistics of one group ------------------------------------------------------
STATS = ['N', 'Mean', 'Std Dev', 'Min', 'Max', 'Range', 'Sum', 'Median', 'Quantiles', 'N Missing', 'N Categories',
         '% of Total', 'CV', 'Std Err', 'Variance', 'Geometric Mean', 'Interquartile Range', 'Mode']
TEXT_STATS = {'N', 'N Missing', 'N Categories', '% of Total', 'Mode'}


def _qlabel(p):
    return f'Quantiles{p:g}'


def _stat(kind, x, f=None, w=None, p=None):
    """One statistic of the values x of a group. f: frequencies, w: weights
    (rows with a missing or nonpositive one are gone already)."""
    ok = ~np.isnan(x)
    xs = x[ok]
    n = len(xs)
    fs = f[ok] if f is not None else None
    ww = (fs if fs is not None else 1.0) * (w[ok] if w is not None else 1.0)
    if np.isscalar(ww):
        ww = np.full(n, float(ww))
    if kind == 'N':
        return float(fs.sum()) if fs is not None else float(n)
    if kind == 'N Missing':
        return float(np.sum(~ok))
    if kind == 'N Categories':
        return float(len(np.unique(xs)))
    if n == 0:
        return float('nan')
    if kind == 'Mean':
        return float(np.average(xs, weights=ww))
    if kind == 'Sum':
        return float(np.sum(ww * xs))
    if kind == 'Min':
        return float(np.min(xs))
    if kind == 'Max':
        return float(np.max(xs))
    if kind == 'Range':
        return float(np.max(xs) - np.min(xs))
    if kind in ('Std Dev', 'Variance', 'Std Err', 'CV'):
        if ww.sum() <= 1:
            return float('nan')
        d = DescrStatsW(xs, weights=ww, ddof=1)
        if kind == 'Std Dev':
            return float(d.std)
        if kind == 'Variance':
            return float(d.var)
        if kind == 'Std Err':
            return float(d.std_mean)
        mean = float(d.mean)
        return 100 * float(d.std) / mean if mean else float('nan')
    if kind == 'Geometric Mean':
        return float(np.exp(np.average(np.log(xs), weights=ww))) if np.all(xs > 0) else float('nan')
    if kind in ('Median', 'Quantiles', 'Interquartile Range'):
        def q(pp):
            if w is not None:
                return float(DescrStatsW(xs, weights=ww).quantile([pp], return_pandas=False)[0])
            vals = np.repeat(xs, np.floor(fs).astype(int)) if fs is not None else xs
            return float(np.quantile(vals, pp, method='weibull')) if len(vals) else float('nan')
        if kind == 'Median':
            return q(0.5)
        if kind == 'Interquartile Range':
            return q(0.75) - q(0.25)
        return q(p / 100.0)
    if kind == 'Mode':
        vals, counts = np.unique(xs, return_counts=True)
        return float(vals[np.argmax(counts)])
    return float('nan')


def _text_stat(kind, v, f=None):
    miss = _missing(v)
    if kind == 'N':
        return float(f[~miss].sum()) if f is not None else float(np.sum(~miss))
    if kind == 'N Missing':
        return float(np.sum(miss))
    if kind == 'N Categories':
        return float(len(set(v[~miss].tolist())))
    if kind == 'Mode':
        vals = v[~miss].tolist()
        if not vals:
            return None
        s = pd.Series(vals).value_counts()
        best = s[s == s.max()].index.tolist()
        return sorted(best)[0]
    return float('nan')


def _weights(tid, idx, weight=None, freq=None):
    """Drop the rows whose Freq or Weight is missing or not positive; the
    frequencies and weights of the rest."""
    keep = np.ones(len(idx), dtype=bool)
    f = w = None
    if freq:
        f = _raw(tid, freq, idx)
        keep &= np.isfinite(f) & (f > 0)
    if weight:
        w = _raw(tid, weight, idx)
        keep &= np.isfinite(w) & (w > 0)
    return idx[keep], (f[keep] if f is not None else None), (w[keep] if w is not None else None)


def _stat_name(fmt, stat, column, sub=None):
    if fmt == 'column':
        base = column
    elif fmt == 'stat of column':
        base = f'{stat} of {column}'
    elif fmt == 'column stat':
        base = f'{column} {stat}'
    else:
        return f'{stat}({column}, {sub})' if sub else f'{stat}({column})'
    return f'{base}, {sub}' if sub else base


# ---- Tables > Summary --------------------------------------------------------------
@api('tables.summary')
def summary(table, group=(), columns=(), stats=('Mean',), subgroup=(), weight=None, freq=None, quantiles=(25, 75),
            name_format='stat(column)', rows=None, table_name='data'):
    group, columns, subgroup = list(group or []), list(columns or []), list(subgroup or [])
    stats = [s for s in (stats or []) if s in STATS]
    idx, f, w = _weights(table, _idx(table, rows), weight, freq)
    gid, glabels = _groups(table, group, idx)
    sid, slabels = _groups(table, subgroup, idx)
    G, S = len(glabels), len(slabels)
    cells = _slices(gid * max(S, 1) + sid) if len(idx) else {}
    by_group = _slices(gid) if len(idx) else {}
    out = []
    for k, g in enumerate(group):
        out.append(_column(g, [lab[k] for lab in glabels], _numeric(table, g), role='group', source=g))
    out.append(_column('N Rows', [float(len(by_group.get(j, []))) for j in range(G)], True, role='n'))
    for c in columns:
        numeric = _numeric(table, c)
        x = _raw(table, c, idx)
        for s in stats:
            if not numeric and s not in TEXT_STATS:
                continue
            plist = [float(p) for p in (quantiles or [])] if s == 'Quantiles' else [None]
            for p in plist:
                label = _qlabel(p) if s == 'Quantiles' else s
                if s == '% of Total':
                    total = (_text_stat('N', x, f) if not numeric else _stat('Sum', x, f, w))
                for j in range(S):
                    sub = ', '.join(_text(v) or '.' for v in slabels[j]) if subgroup else None
                    vals = []
                    for gi in range(G):
                        pos = cells.get(gi * max(S, 1) + j)
                        if pos is None:
                            vals.append(float('nan') if s not in ('N', 'N Missing') else 0.0)
                            continue
                        xs = x[pos]
                        fs = f[pos] if f is not None else None
                        ws = w[pos] if w is not None else None
                        if s == '% of Total':
                            part = _text_stat('N', xs, fs) if not numeric else _stat('Sum', xs, fs, ws)
                            vals.append(100.0 * part / total if total else float('nan'))
                        elif numeric:
                            vals.append(_stat(s, xs, fs, ws, p))
                        else:
                            vals.append(_text_stat(s, xs, fs))
                    is_num = not (s == 'Mode' and not numeric)
                    out.append(_column(_stat_name(name_format, label, c, sub), vals, is_num, role='stat', stat=s, column=c,
                                       source=c if s in ('Mean', 'Min', 'Max', 'Median', 'Quantiles', 'Mode', 'Sum') else None, sub=sub))
    names = _unique_names([o['name'] for o in out])
    for o, nm in zip(out, names):
        o['name'] = nm
    return {'columns': out, 'nrows': G, 'code': _summary_code(table_name, group, columns, stats, quantiles, subgroup, weight, freq)}


def _summary_code(table_name, group, columns, stats, quantiles, subgroup, weight, freq):
    fn = {'N': 'count', 'Mean': 'mean', 'Std Dev': 'std', 'Min': 'min', 'Max': 'max', 'Sum': 'sum', 'Variance': 'var',
          'Std Err': 'sem', 'Median': 'median'}
    lines = [code_head(table_name)]
    keys = group + subgroup
    if keys:
        lines.append(f'g = df.groupby({json.dumps(keys)}, dropna=False)   # groups with a missing value are kept')
        lines.append('out = pd.DataFrame({"N Rows": g.size()})')
    else:
        lines.append('g = df.groupby(lambda i: 0)   # one group: every row')
        lines.append('out = pd.DataFrame({"N Rows": g.size()})')
    if weight or freq:
        lines.append('# The table has a Weight or Freq column: the moments are DescrStatsW\'s with weights = weight * freq,')
        lines.append('# as statsmodels.stats.weightstats.DescrStatsW(x, weights=w, ddof=1).mean, .std, .std_mean compute them.')
    for c in columns:
        q = json.dumps(c)
        for s in stats:
            if s in fn:
                lines.append(f'out[{json.dumps(f"{s}({c})")}] = g[{q}].{fn[s]}()')
            elif s == 'Quantiles':
                for p in quantiles or []:
                    lines.append(f'out[{json.dumps(f"{_qlabel(float(p))}({c})")}] = g[{q}].apply(lambda s: np.quantile(s.dropna(), {float(p) / 100:g}, method="weibull"))')
            elif s == 'Range':
                lines.append(f'out[{json.dumps(f"Range({c})")}] = g[{q}].max() - g[{q}].min()')
            elif s == 'N Missing':
                lines.append(f'out[{json.dumps(f"N Missing({c})")}] = g[{q}].apply(lambda s: s.isna().sum())')
            elif s == 'N Categories':
                lines.append(f'out[{json.dumps(f"N Categories({c})")}] = g[{q}].nunique()')
            elif s == 'CV':
                lines.append(f'out[{json.dumps(f"CV({c})")}] = 100 * g[{q}].std() / g[{q}].mean()')
            elif s == '% of Total':
                lines.append(f'out[{json.dumps(f"% of Total({c})")}] = 100 * g[{q}].sum() / df[{q}].sum()')
    if subgroup:
        lines.append(f'out = out.unstack({json.dumps(subgroup)})   # the Subgroup levels side by side')
    lines.append('print(out)')
    return '\n'.join(lines)


# ---- Tables > Stack ---------------------------------------------------------------------
@api('tables.stack')
def stack(table, columns, keep=(), data_name='Data', label_name='Label', id_name=None, by_row=True, drop_missing=False, rows=None, table_name='data'):
    columns, keep = list(columns), list(keep or [])
    idx = _idx(table, rows)
    n, k = len(idx), len(columns)
    numeric = all(_numeric(table, c) for c in columns)
    raw = [_raw(table, c, idx) for c in columns]
    mat = np.empty((n, k), dtype=float if numeric else object)
    for j, v in enumerate(raw):
        mat[:, j] = v if numeric or not _numeric(table, columns[j]) else [_text(x) for x in v]
    if by_row:
        flat = mat.reshape(-1)
        src = np.repeat(np.arange(n), k)
        lab = np.tile(np.arange(k), n)
    else:
        flat = mat.T.reshape(-1)
        src = np.tile(np.arange(n), k)
        lab = np.repeat(np.arange(k), n)
    if drop_missing:
        ok = ~_missing(flat)
        flat, src, lab = flat[ok], src[ok], lab[ok]
    out = []
    for c in keep:
        v = _raw(table, c, idx)[src]
        out.append(_column(c, v.tolist(), _numeric(table, c), source=c))
    if id_name:
        out.append(_column(id_name, (idx[src] + 1).astype(float).tolist(), True, role='id'))
    out.append(_column(label_name, [columns[j] for j in lab], False, role='label', levels=columns))
    out.append(_column(data_name, flat.tolist(), numeric, role='data', source=columns[0] if len(set(data.meta(table, c).get('modelingType') for c in columns)) == 1 else None))
    names = _unique_names([o['name'] for o in out])
    for o, nm in zip(out, names):
        o['name'] = nm
    code = '\n'.join([code_head(table_name),
                      f'long = df.melt(id_vars={json.dumps(keep)}, value_vars={json.dumps(columns)}, var_name={json.dumps(label_name)}, value_name={json.dumps(data_name)}{", ignore_index=False" if by_row else ""})',
                      *(['long = long.sort_index(kind="stable")   # stacked by row: each row\'s values together'] if by_row else []),
                      *([f'long = long.dropna(subset=[{json.dumps(data_name)}])'] if drop_missing else []),
                      'print(long)'])
    return {'columns': out, 'nrows': len(flat), 'code': code}


# ---- Tables > Split ---------------------------------------------------------------------
@api('tables.split')
def split(table, split_by, columns, group=(), keep=(), rows=None, table_name='data'):
    columns, group, keep = list(columns), list(group or []), list(keep or [])
    idx = _idx(table, rows)
    lcodes, lcats, lmiss = _codes(table, split_by, idx)
    idx = idx[~lmiss]
    lcodes = lcodes[~lmiss]
    gid, glabels = _groups(table, group, idx)
    L = max(1, len(lcats))
    # A group with the same Split By value twice gets a second row.
    key = pd.Series(gid * L + lcodes)
    occ = key.groupby(key).cumcount().to_numpy() if len(idx) else np.zeros(0, dtype=int)
    if len(idx):
        outkey = np.column_stack([gid, occ])
        uniq, inv = np.unique(outkey, axis=0, return_inverse=True)
        inv = np.asarray(inv).reshape(-1)
    else:
        uniq, inv = np.zeros((0, 2), dtype=int), np.zeros(0, dtype=int)
    R = len(uniq)
    first = np.full(R, -1)
    for r in range(len(idx) - 1, -1, -1):
        first[inv[r]] = r
    out = []
    for k, g in enumerate(group):
        out.append(_column(g, [glabels[int(u[0])][k] for u in uniq], _numeric(table, g), role='group', source=g))
    for c in keep:
        v = _raw(table, c, idx)
        out.append(_column(c, [v[first[r]] if first[r] >= 0 else None for r in range(R)], _numeric(table, c), role='keep', source=c))
    used = sorted(set(lcodes.tolist()))
    for c in columns:
        v = _raw(table, c, idx)
        numeric = _numeric(table, c)
        for lv in used:
            vals = [float('nan') if numeric else None] * R
            for r in np.flatnonzero(lcodes == lv):
                vals[inv[r]] = v[r]
            name = _text(lcats[lv]) if len(columns) == 1 else f'{c} {_text(lcats[lv])}'
            out.append(_column(name, vals, numeric, role='split', source=c, level=_val(lcats[lv]), split_column=c))
    names = _unique_names([o['name'] for o in out])
    for o, nm in zip(out, names):
        o['name'] = nm
    code = '\n'.join([code_head(table_name),
                      f'd = df.dropna(subset=[{json.dumps(split_by)}]).copy()',
                      f'd["_row"] = d.groupby({json.dumps(group + [split_by])}, dropna=False).cumcount()   # a repeated level makes a new row',
                      f'wide = d.pivot(index={json.dumps(group + ["_row"])}, columns={json.dumps(split_by)}, values={json.dumps(columns if len(columns) > 1 else columns[0])})',
                      'print(wide.reset_index())'])
    return {'columns': out, 'nrows': R, 'code': code}


# ---- Tables > Transpose -------------------------------------------------------------------
@api('tables.transpose')
def transpose(table, columns, label=None, by=(), rows=None, label_name='Label', table_name='data'):
    columns, by = list(columns), list(by or [])
    idx = _idx(table, rows)
    numeric = all(_numeric(table, c) for c in columns)
    gid, glabels = _groups(table, by, idx)
    blocks = _slices(gid) if len(idx) else {}
    order = sorted(blocks)
    # names of the new columns: the Label column's values, or Row 1, Row 2, ...
    names, where = [], []
    for j in order:
        pos = blocks[j]
        if label:
            lv = _raw(table, label, idx[pos])
            texts = [(_text(x) or '.') for x in lv]
        else:
            texts = [f'Row {i + 1}' for i in range(len(pos))]
        seen, placed = {}, []
        for tx in texts:
            k = seen.get(tx, 0)
            seen[tx] = k + 1
            nm = tx if k == 0 else f'{tx} {k + 1}'
            if nm not in names:
                names.append(nm)
            placed.append(names.index(nm))
        where.append(placed)
    out_rows = []
    for bi, j in enumerate(order):
        pos = blocks[j]
        for c in columns:
            v = _raw(table, c, idx[pos])
            cells = [None] * len(names)
            for p, x in zip(where[bi], v):
                cells[p] = x if numeric or not _numeric(table, c) else _text(x)
            out_rows.append((glabels[j], c, cells))
    out = []
    for k, b in enumerate(by):
        out.append(_column(b, [r[0][k] for r in out_rows], _numeric(table, b), role='group', source=b))
    out.append(_column(label_name, [r[1] for r in out_rows], False, role='label', levels=columns))
    for p, nm in enumerate(names):
        out.append(_column(nm, [r[2][p] for r in out_rows], numeric, role='value'))
    uniq = _unique_names([o['name'] for o in out])
    for o, nm in zip(out, uniq):
        o['name'] = nm
    code = '\n'.join([code_head(table_name),
                      f't = df[{json.dumps(columns)}]' + (f'.set_axis(df[{json.dumps(label)}].astype(str))' if label else '') + '.T',
                      f't.index.name = {json.dumps(label_name)}',
                      'print(t.reset_index())'])
    return {'columns': out, 'nrows': len(out_rows), 'code': code}


# ---- Tables > Join and Update ---------------------------------------------------------------
def _keys(tid, names, idx, as_text):
    """A key per row from the matching columns; None when one is missing (a
    missing value matches nothing)."""
    parts = []
    for nm, txt in zip(names, as_text):
        v = _raw(tid, nm, idx)
        miss = _missing(v)
        if txt:
            parts.append([None if m else _text(x) for x, m in zip(v, miss)])
        else:
            parts.append([None if m else float(x) for x, m in zip(v, miss)])
    keys = []
    for i in range(len(idx)):
        k = tuple(p[i] for p in parts)
        keys.append(None if any(x is None for x in k) else k)
    return keys


def _match_types(left, right, pairs):
    """Compare as text when one side of a pair is character."""
    return [not (_numeric(left, a) and _numeric(right, b)) for a, b in pairs]


def _first_by_key(keys):
    out = {}
    for i, k in enumerate(keys):
        if k is not None and k not in out:
            out[k] = i
    return out


@api('tables.join')
def join(table, with_table, match=(), how='inner', by_row=False, cartesian=False, drop_left=False, drop_right=False,
         match_flag=False, left_columns=None, right_columns=None, merge_keys=True, rows=None, with_rows=None,
         left_name='main', right_name='with', table_name='data'):
    left, right = table, with_table
    li, ri = _idx(left, rows), _idx(right, with_rows)
    lnames = list(left_columns) if left_columns else list(data.TABLES[left]['meta'])
    rnames = list(right_columns) if right_columns else list(data.TABLES[right]['meta'])
    pairs = [tuple(p) for p in (match or [])]
    if not (by_row or cartesian) and not pairs:
        raise ValueError('choose the columns to match, or join by row number')
    lpos, rpos = np.arange(len(li)), np.arange(len(ri))
    if pairs and not (by_row or cartesian):
        txt = _match_types(left, right, pairs)
        lk = _keys(left, [a for a, _ in pairs], li, txt)
        rk = _keys(right, [b for _, b in pairs], ri, txt)
        if drop_left:
            keepl = set(_first_by_key(lk).values()) | {i for i, k in enumerate(lk) if k is None}
            lpos = np.array(sorted(keepl), dtype=int)
        if drop_right:
            keepr = set(_first_by_key(rk).values()) | {i for i, k in enumerate(rk) if k is None}
            rpos = np.array(sorted(keepr), dtype=int)
        rmap = {}
        for j in rpos:
            k = rk[j]
            if k is not None:
                rmap.setdefault(k, []).append(int(j))
        out_pairs, used = [], set()
        for i in lpos:
            hits = rmap.get(lk[i]) if lk[i] is not None else None
            if hits:
                for j in hits:
                    out_pairs.append((int(i), j, 3))
                    used.add(j)
            elif how in ('left', 'outer'):
                out_pairs.append((int(i), None, 1))
        if how in ('right', 'outer'):
            for j in rpos:
                if int(j) not in used:
                    out_pairs.append((None, int(j), 2))
    elif cartesian:
        out_pairs = [(int(i), int(j), 3) for i in lpos for j in rpos]
    else:
        nl, nr = len(lpos), len(rpos)
        m = {'inner': min(nl, nr), 'left': nl, 'right': nr, 'outer': max(nl, nr)}.get(how, min(nl, nr))
        out_pairs = [(i if i < nl else None, i if i < nr else None, (1 if i < nl else 0) + (2 if i < nr else 0)) for i in range(m)]
    key_left = {a for a, _ in pairs} if merge_keys and not (by_row or cartesian) else set()
    key_right = {b: a for a, b in pairs} if merge_keys and not (by_row or cartesian) else {}
    rkeep = [c for c in rnames if c not in key_right]
    clash = set(lnames) & set(rkeep)
    out = []
    lcol = {}
    for c in lnames:
        v = _raw(left, c, li)
        numeric = _numeric(left, c)
        vals = []
        right_src = None
        if c in key_left:
            b = [bb for aa, bb in pairs if aa == c][0]
            right_src = (_raw(right, b, ri), _numeric(right, b))
        for i, j, _ in out_pairs:
            if i is not None:
                vals.append(v[i])
            elif right_src is not None and j is not None:
                x = right_src[0][j]
                vals.append(x if right_src[1] == numeric else (_text(x) if not numeric else _num(x)))
            else:
                vals.append(None)
        name = f'{c} of {left_name}' if c in clash else c
        out.append(_column(name, vals, numeric, side='left', source=c))
        lcol[c] = name
    for c in rkeep:
        v = _raw(right, c, ri)
        numeric = _numeric(right, c)
        vals = [v[j] if j is not None else None for _, j, _ in out_pairs]
        name = f'{c} of {right_name}' if c in clash else c
        out.append(_column(name, vals, numeric, side='right', source=c))
    if match_flag:
        out.append(_column('Match Flag', [float(fl) for _, _, fl in out_pairs], True, role='flag'))
    names = _unique_names([o['name'] for o in out])
    for o, nm in zip(out, names):
        o['name'] = nm
    how_pd = {'inner': 'inner', 'left': 'left', 'right': 'right', 'outer': 'outer'}.get(how, 'inner')
    code = [code_head(table_name), f'other = pd.read_csv({json.dumps(right_name + ".csv")})']
    if cartesian:
        code.append('joined = df.merge(other, how="cross")')
    elif by_row:
        code.append(f'joined = pd.concat([df, other], axis=1, join={json.dumps("inner" if how == "inner" else "outer")})   # row 1 with row 1, ...')
    else:
        if drop_left:
            code.append(f'df = df.drop_duplicates(subset={json.dumps([a for a, _ in pairs])})')
        if drop_right:
            code.append(f'other = other.drop_duplicates(subset={json.dumps([b for _, b in pairs])})')
        code.append(f'joined = df.merge(other, how={json.dumps(how_pd)}, left_on={json.dumps([a for a, _ in pairs])}, right_on={json.dumps([b for _, b in pairs])}, indicator={bool(match_flag)})')
        code.append('# pandas matches a missing key with a missing key; this page does not (drop them first to agree)')
    code.append('print(joined)')
    return {'columns': out, 'nrows': len(out_pairs), 'matched': int(sum(1 for p in out_pairs if p[2] == 3)), 'code': '\n'.join(code)}


def _num(x):
    if x is None:
        return None
    try:
        return float(str(x).strip().replace('−', '-'))
    except ValueError:
        return None


@api('tables.update')
def update(table, with_table, match=(), by_row=False, replace=None, add=None, ignore_missing=True, table_name='data'):
    """Values of the current table replaced by the matching rows of another,
    and columns of the other added: the first matching row counts."""
    left, right = table, with_table
    li, ri = _idx(left, None), _idx(right, None)
    lnames, rnames = list(data.TABLES[left]['meta']), list(data.TABLES[right]['meta'])
    pairs = [tuple(p) for p in (match or [])]
    if by_row:
        hit = [i if i < len(ri) else None for i in range(len(li))]
    else:
        if not pairs:
            raise ValueError('choose the columns to match, or update by row number')
        txt = _match_types(left, right, pairs)
        lk = _keys(left, [a for a, _ in pairs], li, txt)
        first = _first_by_key(_keys(right, [b for _, b in pairs], ri, txt))
        hit = [first.get(k) if k is not None else None for k in lk]
    rkeys = {b for _, b in pairs}
    lkeys = {a for a, _ in pairs}
    common = [c for c in lnames if c in rnames and c not in lkeys and c not in rkeys]
    extra = [c for c in rnames if c not in lnames and c not in rkeys]
    rep = common if replace is None else [c for c in replace if c in common]
    addc = extra if add is None else [c for c in add if c in extra]
    upd = []
    for c in rep:
        old = _raw(left, c, li)
        new = _raw(right, c, ri)
        lnum, rnum = _numeric(left, c), _numeric(right, c)
        vals, changed = old.tolist(), 0
        for i, j in enumerate(hit):
            if j is None:
                continue
            x = new[j]
            miss = x is None or (isinstance(x, float) and math.isnan(x))
            if miss and ignore_missing:
                continue
            x = x if lnum == rnum else (_num(x) if lnum else _text(x))
            before = vals[i]
            same = (before == x) or (isinstance(before, float) and isinstance(x, float) and math.isnan(before) and math.isnan(x))
            if not same:
                changed += 1
            vals[i] = x
        upd.append(_column(c, vals, lnum, changed=changed))
    added = []
    for c in addc:
        new = _raw(right, c, ri)
        added.append(_column(c, [new[j] if j is not None else None for j in hit], _numeric(right, c), source=c))
    code = [code_head(table_name), 'other = pd.read_csv("other.csv")']
    if pairs:
        code.append(f'first = other.drop_duplicates(subset={json.dumps([b for _, b in pairs])})')
        code.append(f'm = df[{json.dumps([a for a, _ in pairs])}].merge(first, how="left", left_on={json.dumps([a for a, _ in pairs])}, right_on={json.dumps([b for _, b in pairs])})')
        for c in rep:
            code.append(f'df[{json.dumps(c)}] = m[{json.dumps(c + "_y" if c in lnames else c)}].combine_first(df[{json.dumps(c)}])' if ignore_missing else f'df[{json.dumps(c)}] = m[{json.dumps(c)}]')
    code.append('print(df)')
    return {'update': upd, 'add': added, 'matched': int(sum(1 for j in hit if j is not None)), 'code': '\n'.join(code)}


# ---- Tables > Missing Data Pattern, and Explore Missing Values ---------------------------------
def _miss_matrix(tid, columns, idx):
    return np.column_stack([_missing(_raw(tid, c, idx)) for c in columns]) if columns else np.zeros((len(idx), 0), dtype=bool)


@api('tables.missing_pattern')
def missing_pattern(table, columns, rows=None, table_name='data'):
    columns = list(columns)
    idx = _idx(table, rows)
    M = _miss_matrix(table, columns, idx)
    pats = [''.join('1' if b else '0' for b in r) for r in M]
    counts = pd.Series(pats, dtype=object).value_counts() if pats else pd.Series(dtype=object)
    keys = sorted(counts.index.tolist())
    out = [_column('Count', [float(counts[k]) for k in keys], True, role='count'),
           _column('Number of columns missing', [float(k.count('1')) for k in keys], True),
           _column('Patterns', keys, False, role='pattern')]
    for j, c in enumerate(columns):
        out.append(_column(c, [float(k[j]) for k in keys], True, role='indicator', column=c))
    code = '\n'.join([code_head(table_name),
                      f'm = df[{json.dumps(columns)}].isna().astype(int)',
                      'pattern = m.astype(str).agg("".join, axis=1)',
                      'print(pattern.value_counts().sort_index())'])
    return {'columns': out, 'nrows': len(keys), 'code': code}


@api('tables.missing_report')
def missing_report(table, columns, rows=None, table_name='data'):
    columns = list(columns)
    idx = _idx(table, rows)
    n = len(idx)
    M = _miss_matrix(table, columns, idx)
    per = M.sum(axis=0) if n else np.zeros(len(columns))
    cols = [{'column': c, 'n_missing': int(per[j]), 'pct': (100.0 * per[j] / n) if n else None, 'n': n} for j, c in enumerate(columns)]
    pats = [''.join('1' if b else '0' for b in r) for r in M]
    counts = pd.Series(pats, dtype=object).value_counts() if pats else pd.Series(dtype=object)
    keys = sorted(counts.index.tolist(), key=lambda k: (k.count('1'), k))
    patterns = [{'pattern': k, 'count': int(counts[k]), 'n_missing': k.count('1'), 'columns': [c for c, b in zip(columns, k) if b == '1']} for k in keys]
    code = '\n'.join([code_head(table_name),
                      f'd = df[{json.dumps(columns)}]',
                      'print(d.isna().sum(), 100 * d.isna().mean())',
                      'print(d.isna().astype(int).astype(str).agg("".join, axis=1).value_counts())'])
    return {'columns': cols, 'patterns': patterns, 'n': n, 'rows_with_missing': int(M.any(axis=1).sum()) if n else 0,
            'cells_missing': int(M.sum()), 'code': code}


def mvn_em(X, max_iter=500, tol=1e-10):
    """Maximum likelihood mean and covariance of a multivariate normal from
    data with missing values (NaN), by the EM algorithm; the covariance
    divides by n. Returns (mu, sigma, iterations)."""
    X = np.asarray(X, dtype=float)
    n, p = X.shape
    miss = np.isnan(X)
    if np.any(miss.all(axis=0)):
        raise ValueError('a column has no values')
    mu = np.nanmean(X, axis=0)
    sig = np.diag(np.nanvar(X, axis=0))
    sig[sig == 0] = 1e-12
    pats, inv = np.unique(miss, axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    groups = [(pats[g], np.flatnonzero(inv == g)) for g in range(len(pats))]
    it = 0
    for it in range(1, max_iter + 1):
        T1 = np.zeros(p)
        T2 = np.zeros((p, p))
        for pm, rows in groups:
            o, m = ~pm, pm
            full = X[rows].copy()
            if m.any():
                if o.any():
                    B = np.linalg.solve(sig[np.ix_(o, o)], sig[np.ix_(o, m)]).T
                    full[:, m] = mu[m] + (full[:, o] - mu[o]) @ B.T
                    C = sig[np.ix_(m, m)] - B @ sig[np.ix_(o, m)]
                else:
                    full[:, m] = mu[m]
                    C = sig[np.ix_(m, m)]
                T2[np.ix_(m, m)] += len(rows) * C
            T1 += full.sum(axis=0)
            T2 += full.T @ full
        mu_new = T1 / n
        sig_new = T2 / n - np.outer(mu_new, mu_new)
        done = np.max(np.abs(mu_new - mu)) <= tol * (1 + np.max(np.abs(mu))) and np.max(np.abs(sig_new - sig)) <= tol * (1 + np.max(np.abs(sig)))
        mu, sig = mu_new, sig_new
        if done:
            break
    return mu, sig, it


def conditional_means(X, mu, sig):
    """Each missing value replaced by its expectation given the row's
    observed values under N(mu, sig): least squares imputation."""
    X = np.asarray(X, dtype=float).copy()
    miss = np.isnan(X)
    for r in np.flatnonzero(miss.any(axis=1)):
        m = miss[r]
        o = ~m
        if o.any():
            X[r, m] = mu[m] + sig[np.ix_(m, o)] @ np.linalg.solve(sig[np.ix_(o, o)], X[r, o] - mu[o])
        else:
            X[r, m] = mu[m]
    return X


@api('tables.impute')
def impute(table, columns, method='mean', rows=None, seed=1, n_iter=10, table_name='data'):
    columns = [c for c in columns if _numeric(table, c)]
    if not columns:
        raise ValueError('imputation takes numeric columns')
    idx = _idx(table, rows)
    X = np.column_stack([_raw(table, c, idx) for c in columns])
    miss = np.isnan(X)
    info = {}
    if method in ('mean', 'median'):
        fill = np.nanmean(X, axis=0) if method == 'mean' else np.nanmedian(X, axis=0)
        Y = np.where(miss, fill, X)
        info['fill'] = fill
        code = [code_head(table_name), f'cols = {json.dumps(columns)}', f'df[cols] = df[cols].fillna(df[cols].{method}())']
    elif method == 'mvn':
        if len(columns) < 2:
            raise ValueError('multivariate normal imputation needs two or more columns')
        mu, sig, it = mvn_em(X)
        Y = conditional_means(X, mu, sig)
        info.update({'mean': mu, 'cov': sig, 'iterations': it})
        code = [code_head(table_name), f'X = df[{json.dumps(columns)}].to_numpy(float)',
                '# EM for the mean and covariance of a multivariate normal, then each missing value by its',
                '# conditional expectation given the observed ones (the functions are in smui/tables.py):',
                'mu, sigma, iterations = mvn_em(X)', 'X_imputed = conditional_means(X, mu, sigma)']
    elif method == 'mice':
        from statsmodels.imputation.mice import MICEData
        safe = [f'v{j}' for j in range(len(columns))]
        df = pd.DataFrame(X, columns=safe)
        np.random.seed(int(seed) % (2 ** 32))
        imp = MICEData(df)
        imp.update_all(int(n_iter))
        Y = imp.data[safe].to_numpy(float)
        info.update({'iterations': int(n_iter), 'seed': int(seed)})
        code = [code_head(table_name, ['from statsmodels.imputation.mice import MICEData']),
                f'cols = {json.dumps(columns)}', 'd = df[cols].set_axis([f"v{j}" for j in range(len(cols))], axis=1)   # names patsy can read',
                f'np.random.seed({int(seed)})', 'imp = MICEData(d)', f'imp.update_all({int(n_iter)})', 'print(imp.data)']
    else:
        raise ValueError(f'no imputation method {method!r}')
    out = []
    for j, c in enumerate(columns):
        out.append({'name': c, 'values': [float(v) for v in Y[:, j]], 'imputed': int(miss[:, j].sum())})
    return {'columns': out, 'rows': idx.tolist(), 'method': method, 'info': info, 'code': '\n'.join(code)}


# ---- Cols > Columns Viewer -----------------------------------------------------------------------
@api('tables.colviewer')
def colviewer(table, columns=None, rows=None, table_name='data'):
    names = list(columns) if columns else list(data.TABLES[table]['meta'])
    idx = _idx(table, rows)
    out = []
    for c in names:
        m = data.meta(table, c)
        v = _raw(table, c, idx)
        miss = _missing(v)
        r = {'column': c, 'type': m.get('modelingType'), 'dataType': m.get('dataType'), 'n': int(np.sum(~miss)), 'n_missing': int(np.sum(miss)),
             'n_categories': int(len(set(v[~miss].tolist())))}
        if m.get('dataType') == 'numeric' and r['n']:
            xs = v[~miss]
            r.update({'min': float(np.min(xs)), 'max': float(np.max(xs))})
            if m.get('modelingType') == 'continuous':
                q = np.quantile(xs, [0.25, 0.5, 0.75], method='weibull')
                r.update({'mean': float(np.mean(xs)), 'sd': float(np.std(xs, ddof=1)) if len(xs) > 1 else None,
                          'lq': float(q[0]), 'median': float(q[1]), 'uq': float(q[2])})
        out.append(r)
    cols = [col('column', 'Columns', 'text'), col('n', 'N', 'int'), col('n_missing', 'N Missing', 'int'), col('n_categories', 'N Categories', 'int'),
            col('min', 'Min'), col('max', 'Max'), col('mean', 'Mean'), col('sd', 'Std Dev'), col('median', 'Median'),
            col('lq', 'Lower Quartile'), col('uq', 'Upper Quartile')]
    code = '\n'.join([code_head(table_name), f'd = df[{json.dumps(names)}]',
                      'num = d.select_dtypes("number")',
                      'print(pd.DataFrame({"N": d.count(), "N Missing": d.isna().sum(), "N Categories": d.nunique()}))',
                      'print(num.agg(["min", "max", "mean", "std"]).T)',
                      'print(num.apply(lambda s: np.quantile(s.dropna(), [0.25, 0.5, 0.75], method="weibull")).T)'])
    return {'table': rtable(cols, out), 'rows': out, 'code': code}


# ---- Analyze > Tabulate ------------------------------------------------------------------------
TAB_STATS = ['N', 'Mean', 'Std Dev', 'Min', 'Max', 'Range', 'Sum', 'Median', 'Quantiles', '% of Total', 'Column %', 'Row %',
             'N Missing', 'Mode', 'Variance', 'Std Err', 'CV', 'Interquartile Range']
COUNT_STATS = ['N', '% of Total', 'Column %', 'Row %']


def _entries(tid, chains, idx, add_all):
    """The row (or column) headings: for each chain of nested columns its
    level combinations present in the rows, in the page's order; then All.
    Each heading has the mask of its rows (None: every row)."""
    out = []
    for b, chain in enumerate(chains):
        if not chain:
            out.append({'block': b, 'levels': [], 'all': True, 'mask': None})
            continue
        gid, labels = _groups(tid, chain, idx)
        for g in range(len(labels)):
            out.append({'block': b, 'levels': list(zip(chain, labels[g])), 'all': False, 'mask': gid == g})
    if add_all and any(chains):
        out.append({'block': len(chains), 'levels': [], 'all': True, 'mask': None})
    return out


@api('tables.tabulate')
def tabulate(table, row_chains=(), col_chains=(), analysis=(), stats=('N',), all_rows=False, all_cols=False,
             include_missing=False, quantiles=(25, 75), freq=None, rows=None, table_name='data'):
    rchains = [list(c) for c in (row_chains or []) if c] or [[]]
    cchains = [list(c) for c in (col_chains or []) if c] or [[]]
    analysis = list(analysis or [])
    stats = [s for s in (stats or []) if s in TAB_STATS] or ['N']
    if not analysis:
        stats = [s for s in stats if s in COUNT_STATS] or ['N']
    idx, f, _ = _weights(table, _idx(table, rows), None, freq)
    # As in JMP, a row with a missing value in a grouping column leaves the
    # whole table, unless missing values are to be a level of their own.
    grouping = list(dict.fromkeys(nm for c in rchains + cchains for nm in c))
    if not include_missing and grouping and len(idx):
        ok = np.ones(len(idx), dtype=bool)
        for nm in grouping:
            ok &= ~_missing(_raw(table, nm, idx))
        idx = idx[ok]
        f = f[ok] if f is not None else None
    n = len(idx)
    ff = f if f is not None else np.ones(n)
    rentries = _entries(table, rchains, idx, all_rows)
    centries = _entries(table, cchains, idx, all_cols)
    xs = {a: _raw(table, a, idx) for a in analysis}
    expanded = []
    for s in stats:
        if s == 'Quantiles':
            expanded += [('Quantiles', float(p), f'Quantile {float(p):g}%') for p in (quantiles or [25, 75])]
        else:
            expanded.append((s, None, s))
    heads = [{'entry': ce, 'ci': ci, 'analysis': a, 'stat': s, 'p': p, 'label': label}
             for ci, ce in enumerate(centries) for a in (analysis or [None]) for s, p, label in expanded]
    ones = np.ones(n, dtype=bool)
    rmasks = [re['mask'] if re['mask'] is not None else ones for re in rentries]
    cmasks = [ce['mask'] if ce['mask'] is not None else ones for ce in centries]

    def amount(mask, a):
        """What a percentage is of: a count, or the sum of the analysis column."""
        if a is None or not _numeric(table, a):
            if a is None:
                return float(ff[mask].sum())
            ok = ~_missing(xs[a][mask])
            return float(ff[mask][ok].sum())
        x = xs[a][mask]
        ok = ~np.isnan(x)
        return float(np.sum(x[ok] * ff[mask][ok]))

    values = []
    for ri in range(len(rentries)):
        line = []
        for h in heads:
            ci = h['ci']
            mask = rmasks[ri] & cmasks[ci]
            a, s = h['analysis'], h['stat']
            if s in ('% of Total', 'Column %', 'Row %'):
                base = ones if s == '% of Total' else cmasks[ci] if s == 'Column %' else rmasks[ri]
                tot = amount(base, a)
                line.append(100.0 * amount(mask, a) / tot if tot else None)
            elif a is None:
                line.append(float(ff[mask].sum()))
            else:
                x = xs[a][mask]
                fx = ff[mask] if f is not None else None
                if _numeric(table, a):
                    line.append(_stat(s, x, fx, None, h['p']))
                else:
                    line.append(_text_stat(s, x, fx) if s in TEXT_STATS else None)
        values.append(line)
    row_vars = list(dict.fromkeys(nm for c in rchains for nm in c))
    rows_out = [{'levels': [[k, _val(v)] for k, v in re['levels']], 'all': re['all'], 'block': re['block']} for re in rentries]
    cols_out = [{'levels': [[k, _val(v)] for k, v in h['entry']['levels']], 'all': h['entry']['all'] and bool(any(cchains)), 'analysis': h['analysis'],
                 'stat': h['stat'], 'label': h['label']} for h in heads]
    code = [code_head(table_name)]
    idx_vars = row_vars
    col_vars = list(dict.fromkeys(nm for c in cchains for nm in c))
    agg = {'N': 'count', 'Mean': 'mean', 'Std Dev': 'std', 'Min': 'min', 'Max': 'max', 'Sum': 'sum', 'Median': 'median', 'Variance': 'var', 'Std Err': 'sem'}
    fns = [agg[s] for s in stats if s in agg] or ['count']
    if analysis:
        code.append(f'print(pd.pivot_table(df, index={json.dumps(idx_vars) if idx_vars else "None"}, columns={json.dumps(col_vars) if col_vars else "None"}, values={json.dumps(analysis)}, aggfunc={json.dumps(fns)}, margins={bool(all_rows or all_cols)}, observed=True))')
    else:
        code.append(f'print(pd.crosstab({"[" + ", ".join(f"df[{json.dumps(v)}]" for v in idx_vars) + "]" if idx_vars else "pd.Series(0, index=df.index)"}, {"[" + ", ".join(f"df[{json.dumps(v)}]" for v in col_vars) + "]" if col_vars else "pd.Series(\'N\', index=df.index)"}, margins={bool(all_rows or all_cols)}))')
    code.append('# quantiles as JMP computes them: np.quantile(x, p, method="weibull")')
    return {'row_vars': row_vars, 'rows': rows_out, 'cols': cols_out, 'values': values, 'n': n, 'code': '\n'.join(code)}


# ---- File > Python Script ------------------------------------------------------------------------
def _frame_out(obj, limit=2_000_000):
    """A DataFrame (or Series) as columns for a new data table."""
    df = obj.to_frame(name=obj.name if obj.name is not None else 'value') if isinstance(obj, pd.Series) else obj
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [' '.join(str(x) for x in c if str(x) != '') for c in df.columns]
    ix = df.index
    if isinstance(ix, pd.MultiIndex) or ix.name is not None or not pd.api.types.is_integer_dtype(ix.dtype):
        df = df.reset_index()          # group keys, labels: a column of their own
    else:
        df = df.reset_index(drop=True)   # row numbers: not a column
    if df.shape[0] * max(1, df.shape[1]) > limit:
        raise ValueError(f'the result has {df.shape[0]} rows and {df.shape[1]} columns, more than this page makes into a table')
    out = []
    for name in df.columns:
        s = df[name]
        entry = {'name': str(name)}
        if isinstance(s.dtype, pd.CategoricalDtype):
            cats = [_text(c) for c in s.cat.categories]
            entry.update({'dataType': 'character', 'values': [None if pd.isna(v) else _text(v) for v in s.astype(object)],
                          'modelingType': 'ordinal' if s.cat.ordered else 'nominal', 'levels': cats})
        elif pd.api.types.is_bool_dtype(s):
            entry.update({'dataType': 'numeric', 'values': [None if pd.isna(v) else float(v) for v in s.astype(object)]})
        elif pd.api.types.is_datetime64_any_dtype(s):
            ms = s.dt.tz_localize(None) if getattr(s.dt, 'tz', None) is not None else s
            vals = (ms.astype('datetime64[ns]').astype('int64') / 1e6).where(~s.isna())
            entry.update({'dataType': 'numeric', 'values': [None if pd.isna(v) else float(v) for v in vals], 'format': {'kind': 'datetime'}})
        elif pd.api.types.is_timedelta64_dtype(s):
            entry.update({'dataType': 'numeric', 'values': [None if pd.isna(v) else v.total_seconds() * 1000 for v in s]})
        elif pd.api.types.is_numeric_dtype(s):
            entry.update({'dataType': 'numeric', 'values': [None if pd.isna(v) else float(v) for v in s.astype(float)]})
        else:
            entry.update({'dataType': 'character', 'values': [None if (v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA) else _text(v) for v in s.astype(object)]})
        out.append(entry)
    names = _unique_names([e['name'] for e in out])
    for e, nm in zip(out, names):
        e['name'] = nm
    return {'columns': out, 'nrows': int(df.shape[0])}


def _script_error(e, code):
    lines = code.split('\n')
    if isinstance(e, SyntaxError):
        where = f' (line {e.lineno}{f", column {e.offset}" if e.offset else ""})' if e.lineno else ''
        tb = ''
        if e.lineno and 1 <= e.lineno <= len(lines):
            tb = f'  line {e.lineno}: {lines[e.lineno - 1]}\n' + (' ' * (9 + len(str(e.lineno)) + (e.offset or 1) - 1) + '^' if e.offset else '')
        return f'SyntaxError: {e.msg}{where}', tb
    frames = [fr for fr in traceback.extract_tb(e.__traceback__) if fr.filename == '<script>']
    tb = '\n'.join(f'  line {fr.lineno}: {lines[fr.lineno - 1].strip() if fr.lineno and fr.lineno <= len(lines) else ""}' for fr in frames)
    where = f' (line {frames[-1].lineno})' if frames else ''
    return f'{type(e).__name__}: {e}{where}', tb


@api('tables.run_script')
def run_script(table, code, rows=None, table_name='data'):
    """Run the user's Python against df, the table's rows as a DataFrame with
    the real column names (nominal and ordinal columns as Categoricals, in the
    page's level order). A fresh namespace each run; stdout and stderr are
    captured; a DataFrame left in `result` can become a data table."""
    import scipy.stats as stats
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    names = list(data.TABLES[table]['meta']) if table in data.TABLES else []
    df = _frame(table, names, rows) if names else pd.DataFrame()
    ns = {'__name__': '__script__', 'df': df, 'np': np, 'pd': pd, 'sm': sm, 'smf': smf, 'stats': stats}
    buf = io.StringIO()
    error = tb = None
    try:
        compiled = compile(str(code), '<script>', 'exec')
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            exec(compiled, ns)
    except SystemExit as e:
        error = f'SystemExit: {e}'
    except Exception as e:   # the script's error is shown, not raised
        error, tb = _script_error(e, str(code))
    text = buf.getvalue()
    if len(text) > MAX_SCRIPT_OUTPUT:
        text = text[:MAX_SCRIPT_OUTPUT // 2] + f'\n… {len(text) - MAX_SCRIPT_OUTPUT} characters left out …\n' + text[-MAX_SCRIPT_OUTPUT // 2:]
    out = {'stdout': text, 'error': error, 'traceback': tb, 'result': None, 'result_type': None, 'result_repr': None, 'code': str(code)}
    if 'result' in ns:
        res = ns['result']
        out['result_type'] = type(res).__name__
        if isinstance(res, (pd.DataFrame, pd.Series)):
            try:
                out['result'] = _frame_out(res)
                out['result_repr'] = str(res)[:4000]
            except Exception as e:
                out['result_repr'] = f'(could not make a table of it: {e})'
        else:
            try:
                out['result_repr'] = repr(res)[:4000]
            except Exception as e:
                out['result_repr'] = f'(no repr: {e})'
    return out
