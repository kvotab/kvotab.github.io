"""The page's Python package (resources/py/smui) outside the browser, for
the backend tests: the same modules Pyodide imports, called the way the
page calls them, through registry.dispatch and a JSON round trip.

    from backend import table, call
    tid = table({'x': [1.0, 2.0, 3.0], 'g': ['a', 'b', 'a']}, types={'g': 'nominal'})
    r = call('distribution.continuous', table=tid, column='x')

Run the tests with a Python that has numpy, scipy, pandas, patsy and
statsmodels (0.14.x, as in Pyodide).
"""
import importlib
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.abspath(os.path.join(HERE, '..', '..', 'py'))
if PY not in sys.path:
    sys.path.insert(0, PY)

import smui  # noqa: E402
from smui import data, registry  # noqa: E402

with open(os.path.join(PY, 'smui', 'manifest.json')) as f:
    MANIFEST = json.load(f)
FAILED = {}
for _m in MANIFEST['modules']:
    if not os.path.exists(os.path.join(PY, 'smui', f'{_m}.py')):
        continue
    try:
        importlib.import_module(f'smui.{_m}')
    except Exception as e:  # reported by the tests that need the module
        FAILED[_m] = e

_n = 0


def table(columns, types=None, levels=None, tid=None):
    """A table on the Python side as the page sends it. columns: {name:
    values}; a column of strings is character, else numeric (None or NaN
    missing). types: {name: modeling type}; levels: {name: [levels]}."""
    global _n
    _n += 1
    tid = tid or f't{_n}'
    types = types or {}
    levels = levels or {}
    meta, arrays = [], []
    for name, vals in columns.items():
        vals = list(vals)
        char = any(isinstance(v, str) for v in vals)
        mt = types.get(name) or ('nominal' if char else 'continuous')
        if char:
            arr = [None if v is None else str(v) for v in vals]
        else:
            arr = [float('nan') if v is None else float(v) for v in vals]
        lv = levels.get(name)
        if lv is None and mt != 'continuous':
            present = sorted({v for v in arr if v is not None and not (isinstance(v, float) and math.isnan(v))}, key=lambda v: (isinstance(v, str), v))
            lv = present
        meta.append({'name': name, 'dataType': 'character' if char else 'numeric', 'modelingType': mt, 'levels': lv, 'format': None})
        arrays.append(arr)
    data.set_table(tid, 1, meta, arrays)
    return tid


def call(fn, **payload):
    """Run a backend function as the page does; the result as the page gets it."""
    return json.loads(registry.dispatch(fn, json.dumps(payload)))


class Checks:
    def __init__(self):
        self.n = 0
        self.failed = []

    def __call__(self, label, got, want=True):
        self.n += 1
        ok = got == want
        print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
        if not ok:
            self.failed.append(label)
        return ok

    def near(self, label, got, want, rel=1e-9, abs_=0.0):
        self.n += 1
        ok = isinstance(got, (int, float)) and isinstance(want, (int, float)) and math.isfinite(got) and abs(got - want) <= max(abs_, rel * max(1.0, abs(want)))
        print(f'{"ok  " if ok else "FAIL"}  {label}: {got!r}' + ('' if ok else f' (expected {want!r})'))
        if not ok:
            self.failed.append(label)
        return ok

    def done(self):
        print(f'\n{self.n - len(self.failed)} of {self.n} checks passed')
        if self.failed:
            print('failed:', *self.failed, sep='\n  ')
        return 0 if not self.failed else 1
