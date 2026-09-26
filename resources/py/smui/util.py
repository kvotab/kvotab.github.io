"""JSON out, and small helpers every analysis module uses."""
import json
import math

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
    lines.append(f'df = pd.read_csv({json.dumps(table_name + ".csv")})   # the table, as File > Export CSV writes it')
    return '\n'.join(lines)


def finite(x):
    x = np.asarray(x, dtype=float)
    return x[np.isfinite(x)]
