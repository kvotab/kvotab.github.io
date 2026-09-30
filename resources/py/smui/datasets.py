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


def _stata_value_labels(data, codes):
    """Stata's value labels, {column: [[code, label], ...]}: the file read
    again with its labels applied, each row's code paired with its label
    (public pandas only; a code without a label keeps its number)."""
    import io
    try:
        with pd.io.stata.StataReader(io.BytesIO(data)) as rd:
            cat = rd.read(convert_categoricals=True, order_categoricals=False)
    except Exception:  # labels that pandas cannot apply (not unique): the codes alone
        return {}
    out = {}
    for c in cat.columns:
        s = cat[c]
        if c not in codes.columns or not isinstance(s.dtype, pd.CategoricalDtype):
            continue
        pairs = {}
        for code, lab in zip(codes[c].to_numpy(), s.to_numpy()):
            if isinstance(lab, str) and not pd.isna(code):
                pairs.setdefault(float(code), lab)
        if pairs:
            out[str(c)] = [[k, v] for k, v in sorted(pairs.items())]
    return out


@api('datasets.read_file')
def read_file(name, data):
    """A Stata (.dta) or SAS (.sas7bdat, .xpt) file, read by pandas, or a
    JMP data table (.jmp, jmp.py). Stata's value labels become the Value
    Labels property of their numeric column, which keeps the codes (nominal,
    its levels in coded order), as JMP opens a labelled file; dates stay
    dates."""
    import io
    lower = name.lower()
    if lower.endswith('.jmp'):
        from . import jmp
        return jmp.read(name, data)
    buf = io.BytesIO(data)
    notes = ''
    vlabels = {}
    if lower.endswith('.dta'):
        with pd.io.stata.StataReader(buf) as rd:
            df = rd.read(convert_categoricals=False)
            try:
                notes = rd.data_label or ''
                labels = rd.variable_labels()
            except Exception:
                labels = {}
        buf.seek(0)
        # Whether the codes' order means anything is the user's call
        # (Column Info), so nominal.
        vlabels = _stata_value_labels(data, df)
    elif lower.endswith('.sas7bdat'):
        df = pd.read_sas(buf, format='sas7bdat', encoding='latin-1')
        labels = {}
    elif lower.endswith('.xpt'):
        df = pd.read_sas(buf, format='xport', encoding='latin-1')
        labels = {}
    else:
        raise ValueError(f'not a Stata, SAS or JMP file: {name}')
    df = df.reset_index(drop=True)
    cols = _columns(df)
    for c in cols:
        if labels.get(c['name']):
            c['notes'] = labels[c['name']]
        if vlabels.get(c['name']) and c['dataType'] == 'numeric':
            c['valueLabels'] = vlabels[c['name']]
            c['modelingType'] = 'nominal'
    return {'name': name.rsplit('.', 1)[0], 'columns': cols, 'note': notes, 'rows': int(len(df))}
