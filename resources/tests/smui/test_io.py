#!/usr/bin/env python3
"""Reading foreign files in the engine (datasets.read_file): a Stata file
written here by pandas, with value labels and variable labels, comes back
as the page's columns (value labels as the Value Labels property of the
coded column, as JMP opens a labelled file); and the statsmodels datasets
list and load.

    python3 resources/tests/smui/test_io.py
"""
import io
import json
import sys

import numpy as np
import pandas as pd

from backend import Checks, call
from smui import registry

check = Checks()
rng = np.random.default_rng(7)
df = pd.DataFrame({
    'x': rng.normal(size=12),
    'n': np.arange(12, dtype='int16'),
    'grade': pd.Categorical(rng.choice(['low', 'mid', 'high'], 12), categories=['low', 'mid', 'high'], ordered=True),
    'name': [f'r{i}' for i in range(12)],
})
df.loc[3, 'x'] = np.nan
buf = io.BytesIO()
df.to_stata(buf, write_index=False, variable_labels={'x': 'a normal draw'}, data_label='made by the test')
r = json.loads(registry.dispatch_bytes('datasets.read_file', json.dumps({'name': 'demo.dta'}), buf.getvalue()))
cols = {c['name']: c for c in r['columns']}
check('the columns', list(cols), ['x', 'n', 'grade', 'name'])
check('numbers with a missing value', (cols['x']['values'][3], round(cols['x']['values'][0], 12)), (None, round(float(df.x[0]), 12)))
# value labels: the codes stay the values (pandas writes a Categorical's codes, 0, 1, 2), their labels the Value Labels property, nominal
codes_ = df['grade'].cat.codes.astype(float).tolist()
check('value labels: the column keeps its codes, numeric and nominal', (cols['grade']['dataType'], cols['grade']['modelingType'], cols['grade']['values']), ('numeric', 'nominal', codes_))
check('... and the labels are its Value Labels, in coded order', cols['grade']['valueLabels'], [[0.0, 'low'], [1.0, 'mid'], [2.0, 'high']])
# a partly labelled column: a code without a label keeps its number and no label
part = pd.DataFrame({'q': [1, 2, 3, 9, 1]})
buf2 = io.BytesIO()
part.to_stata(buf2, write_index=False, value_labels={'q': {1: 'agree', 2: 'neutral', 3: 'disagree'}})
r2 = json.loads(registry.dispatch_bytes('datasets.read_file', json.dumps({'name': 'part.dta'}), buf2.getvalue()))
q_ = r2['columns'][0]
check('a code without a label (9) keeps its number and gets none', (q_['values'], q_['valueLabels']), ([1.0, 2.0, 3.0, 9.0, 1.0], [[1.0, 'agree'], [2.0, 'neutral'], [3.0, 'disagree']]))
check('variable label as the column notes', cols['x'].get('notes'), 'a normal draw')
check('data label as the table note', r['note'], 'made by the test')
check('the name without the extension', r['name'], 'demo')
try:
    registry.dispatch_bytes('datasets.read_file', json.dumps({'name': 'x.sav'}), b'')
    check('an unknown type is refused', False, True)
except ValueError:
    check('an unknown type is refused', True, True)
lst = call('datasets.list')
check('statsmodels datasets listed', len(lst) >= 20 and all('title' in d for d in lst), True)
lon = call('datasets.load', name='longley')
check('longley loads', (lon['columns'][0]['name'], len(lon['columns'][0]['values'])), ('TOTEMP', 16))
sys.exit(check.done())
