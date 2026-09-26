#!/usr/bin/env python3
"""Reading foreign files in the engine (datasets.read_file): a Stata file
written here by pandas, with value labels and variable labels, comes back
as the page's columns; and the statsmodels datasets list and load.

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
check('value labels become nominal levels in coded order', (cols['grade']['dataType'], cols['grade']['modelingType'], cols['grade']['valueOrder']), ('character', 'nominal', ['low', 'mid', 'high']))
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
