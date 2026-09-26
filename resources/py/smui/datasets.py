"""The example datasets that come with statsmodels (statsmodels.datasets).

They are part of the statsmodels package that the page loads; each carries
its own source and copyright note, which the page shows with it.
"""
import importlib

import numpy as np
import pandas as pd

from .registry import api

NAMES = ['anes96', 'cancer', 'ccard', 'china_smoking', 'co2', 'committee', 'copper', 'cpunish', 'danish_data', 'elnino',
         'engel', 'fair', 'fertility', 'grunfeld', 'heart', 'interest_inflation', 'longley', 'macrodata', 'modechoice',
         'nile', 'randhie', 'scotland', 'spector', 'stackloss', 'star98', 'statecrime', 'strikes', 'sunspots']


def _mod(name):
    if name not in NAMES:
        raise KeyError(f'no statsmodels dataset {name!r}')
    return importlib.import_module(f'statsmodels.datasets.{name}')


@api('datasets.list')
def list_datasets():
    out = []
    for n in NAMES:
        try:
            m = _mod(n)
            out.append({'name': n, 'title': getattr(m, 'TITLE', n).strip(), 'short': ' '.join(str(getattr(m, 'DESCRSHORT', '')).split()),
                        'copyright': ' '.join(str(getattr(m, 'COPYRIGHT', '')).split())})
        except Exception as e:  # a dataset that fails to import is left out, not fatal
            out.append({'name': n, 'title': n, 'short': f'not available: {e}', 'copyright': ''})
    return out


def _columns(df):
    cols = []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            cols.append({'name': str(c), 'dataType': 'numeric', 'format': {'kind': 'date'},
                         'values': [None if pd.isna(x) else int(pd.Timestamp(x).value // 1_000_000) for x in s]})
        elif pd.api.types.is_numeric_dtype(s):
            cols.append({'name': str(c), 'dataType': 'numeric', 'values': s.astype(float).tolist()})
        elif isinstance(s.dtype, pd.CategoricalDtype):
            vals = [None if pd.isna(x) else str(x) for x in s]
            cols.append({'name': str(c), 'dataType': 'character', 'values': vals, 'valueOrder': [str(x) for x in s.cat.categories],
                         'modelingType': 'ordinal' if s.cat.ordered else 'nominal'})
        else:
            cols.append({'name': str(c), 'dataType': 'character', 'values': [None if pd.isna(x) else str(x) for x in s]})
    return cols


@api('datasets.load')
def load(name):
    m = _mod(name)
    ds = m.load_pandas()
    df = ds.data if isinstance(getattr(ds, 'data', None), pd.DataFrame) else pd.concat([ds.endog, ds.exog], axis=1)
    df = df.reset_index() if not isinstance(df.index, pd.RangeIndex) else df
    cols = _columns(df)
    return {'name': name, 'title': getattr(m, 'TITLE', name).strip(), 'columns': cols,
            'note': ' '.join(str(getattr(m, 'DESCRSHORT', '')).split()), 'copyright': ' '.join(str(getattr(m, 'COPYRIGHT', '')).split()),
            'source': ' '.join(str(getattr(m, 'SOURCE', '')).split())}


@api('datasets.read_file')
def read_file(name, data):
    """A Stata (.dta) or SAS (.sas7bdat, .xpt) file, read by pandas. Stata's
    value labels become nominal levels in their coded order; dates stay dates."""
    import io
    lower = name.lower()
    buf = io.BytesIO(data)
    notes = ''
    if lower.endswith('.dta'):
        with pd.io.stata.StataReader(buf) as rd:
            # Value labels give the levels and their order; whether the
            # order means anything is the user's call (Column Info), so nominal.
            df = rd.read(convert_categoricals=True, order_categoricals=False)
            try:
                notes = rd.data_label or ''
                labels = rd.variable_labels()
            except Exception:
                labels = {}
        buf.seek(0)
    elif lower.endswith('.sas7bdat'):
        df = pd.read_sas(buf, format='sas7bdat', encoding='latin-1')
        labels = {}
    elif lower.endswith('.xpt'):
        df = pd.read_sas(buf, format='xport', encoding='latin-1')
        labels = {}
    else:
        raise ValueError(f'not a Stata or SAS file: {name}')
    df = df.reset_index(drop=True)
    cols = _columns(df)
    for c in cols:
        if labels.get(c['name']):
            c['notes'] = labels[c['name']]
    return {'name': name.rsplit('.', 1)[0], 'columns': cols, 'note': notes, 'rows': int(len(df))}
