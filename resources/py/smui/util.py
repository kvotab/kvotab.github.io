"""JSON out, and small helpers every analysis module uses."""
import json
import math
import re

import numpy as np
import pandas as pd


def clean(obj):
    """Plain Python for json: numpy scalars and arrays, pandas objects, and
    NaN as None (JSON has no NaN); an infinity becomes the string
    'Infinity' or '-Infinity'."""
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        x = float(obj)
        if math.isnan(x):
            return None
        if math.isinf(x):
            return 'Infinity' if x > 0 else '-Infinity'
        return x
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [clean(v) for v in obj.tolist()]
    if isinstance(obj, pd.Series):
        return [clean(v) for v in obj.tolist()]
    if isinstance(obj, pd.DataFrame):
        return [{str(k): clean(v) for k, v in row.items()} for row in obj.to_dict('records')]
    if isinstance(obj, (pd.Timestamp, np.datetime64)):
        return str(obj)
    return str(obj)


def to_json(obj):
    return json.dumps(clean(obj), allow_nan=False)


def table(columns, rows, **extra):
    """A report table: columns [{key, label, fmt}], rows [dict]. fmt is one
    of num, int, p, pct, text; the page formats as JMP does."""
    out = {'columns': columns, 'rows': rows}
    out.update(extra)
    return out


def col(key, label=None, fmt='num', **extra):
    d = {'key': key, 'label': key if label is None else label, 'fmt': fmt}
    d.update(extra)
    return d


def q(name):
    """A column name in a patsy formula: bare only when it is a plain name
    that is neither a Python keyword (yield, class) nor patsy's C, I or Q."""
    import keyword
    ok = name.isidentifier() and not keyword.iskeyword(name) and name not in ('C', 'I', 'Q')
    return name if ok else f'Q({json.dumps(name)})'


def code_head(table_name, extra_imports=()):
    lines = ['import numpy as np', 'import pandas as pd', 'import statsmodels.api as sm', 'import statsmodels.formula.api as smf']
    lines += list(extra_imports)
    # round_trip: every number exactly as exported (the default parser can be
    # off in the last digit, which an iterative fit can feel)
    lines.append(f'df = pd.read_csv({json.dumps(table_name + ".csv")}, float_precision="round_trip")   # the table, as File > Export CSV writes it')
    return '\n'.join(lines)


# ---- dates in the code ------------------------------------------------------
# The page keeps a date as a number, milliseconds since 1970, and computes on
# that number; File > Export CSV (and the notebook's files) write it as text,
# 2024-01-31. Code that reads the CSV must turn such a column back into the
# number before it computes with it, or it computes with text.
DATE_KINDS = ('date', 'datetime')
_READ = re.compile(r'^df = pd\.read_csv\(')


def date_columns(table):
    """The table's number columns shown as dates (any modeling type)."""
    from . import data
    t = data.TABLES.get(table) if table is not None else None
    if not t:
        return []
    return [c for c, m in t['meta'].items() if m.get('dataType') == 'numeric' and (m.get('format') or {}).get('kind') in DATE_KINDS]


def date_line(name):
    q = json.dumps(name)
    return f'df[{q}] = (pd.to_datetime(df[{q}]) - pd.Timestamp(0)) / pd.Timedelta(milliseconds=1)   # a date: text in the CSV, milliseconds since 1970 here as in the page'


def dated_code(code, columns):
    """code with, after each line that reads the table's CSV, a line turning
    each date column it uses back into the page's number. A column the code
    parses itself (pd.to_datetime(df[...]): a time series' Time ID) is left
    to it; code that has the line already is left as it is."""
    if not isinstance(code, str) or not columns or 'pd.read_csv(' not in code:
        return code
    need = []
    for c in columns:
        q = json.dumps(c)
        if q not in code and repr(c) not in code:
            continue
        if re.search(r'pd\.to_datetime\(\s*df\[\s*' + re.escape(q), code) or re.search(r'pd\.to_datetime\(\s*df\[\s*' + re.escape(repr(c)), code):
            continue
        need.append(c)
    if not need:
        return code
    out = []
    for line in code.split('\n'):
        out.append(line)
        if _READ.match(line):
            out += [date_line(c) for c in need]
    return '\n'.join(out)


def dated_result(obj, columns, depth=0):
    """dated_code() on every code string of a result (the keys code and
    *_code, at any depth), in place."""
    if not columns or depth > 5:
        return obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and (k == 'code' or k.endswith('_code')):
                obj[k] = dated_code(v, columns)
            elif isinstance(v, (dict, list)):
                dated_result(v, columns, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                dated_result(v, columns, depth + 1)
    return obj


def finite(x):
    x = np.asarray(x, dtype=float)
    return x[np.isfinite(x)]
