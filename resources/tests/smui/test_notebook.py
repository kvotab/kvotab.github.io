#!/usr/bin/env python3
"""The notebook's Python (smui/notebook.py), outside the browser.

A cell's outputs in the order they were made, as Jupyter keeps them: what
it prints (stdout and stderr, runs of one stream joined), the value of its
last line (not after a trailing ;), rich displays (pandas' HTML, a
statsmodels summary, a Plotly figure dict, display()), matplotlib figures
at plt.show() and at the end of the cell (SVG, or PNG at twice the size for
many points), errors with a traceback that starts at the cell, SyntaxError
included. Namespaces per notebook, reset(), a fresh namespace on request,
top-level await, the execution count. The page's tables: table() with the
modeling types as dtypes and dates as datetimes, table_names(), and
new_table() turning a DataFrame into the page's columns.

    python3 resources/tests/smui/test_notebook.py
"""
import asyncio
import base64
import json
import sys

from backend import Checks
from smui import data, notebook

check = Checks()

data.set_table('t1', 1, [
    {'name': 'x', 'dataType': 'numeric', 'modelingType': 'continuous'},
    {'name': 'g', 'dataType': 'character', 'modelingType': 'nominal', 'levels': ['b', 'a']},
    {'name': 'o', 'dataType': 'numeric', 'modelingType': 'ordinal', 'levels': [3, 1, 2]},
    {'name': 'd', 'dataType': 'numeric', 'modelingType': 'continuous', 'format': {'kind': 'date'}},
], [[1.0, 2.0, float('nan'), 4.0], ['a', 'b', None, 'a'], [1.0, 2.0, 3.0, 1.0], [0.0, 86400000.0, 172800000.0, float('nan')]])
INFO = {'tables': [{'id': 't1', 'name': 'Tiny'}], 'current': 't1', 'label': 'Notebook 1'}


def run(code, nb='nb', **kw):
    info = dict(INFO, **kw)
    return json.loads(asyncio.run(notebook.run_cell(nb, code, json.dumps(info))))


def kinds(r):
    return [(o['type'], o.get('name') or sorted(o.get('data', {})) or o.get('ename')) for o in r['outputs']]


# ---- outputs, in order -------------------------------------------------------------------------------
r = run('print("a"); print("b")\nimport sys\nprint("warn", file=sys.stderr)\n6 * 7')
check('prints join into one stdout output, then stderr, then the value of the last line', kinds(r), [('stream', 'stdout'), ('stream', 'stderr'), ('result', ['text/plain'])])
check('... their text and the value', (r['outputs'][0]['text'], r['outputs'][1]['text'], r['outputs'][2]['data']['text/plain']), ('a\nb\n', 'warn\n', '42'))
check('a trailing ; keeps the last value quiet', run('x = 5\nx;')['outputs'], [])
check('... a comment after it too', run('x;  # quiet')['outputs'], [])
check('None is not shown', run('None')['outputs'], [])
check('an assignment last shows nothing', run('y = 3')['outputs'], [])
r = run('import pandas as pd\npd.DataFrame({"a": [1, 2]})')
check('a DataFrame shows as HTML, with its text', (sorted(r['outputs'][0]['data']), '<table' in r['outputs'][0]['data']['text/html']), (['text/html', 'text/plain'], True))
r = run('display("one", 2)\n"three"')
check('display() shows each object at once, before the last value', [o['data']['text/plain'] for o in r['outputs']], ["'one'", '2', "'three'"])
r = run('{"data": [{"type": "bar", "x": [1, 2], "y": [3, 4]}], "layout": {"title": {"text": "t"}}}')
check('a Plotly figure dict goes as a Plotly figure', 'application/vnd.plotly.v1+json' in r['outputs'][0]['data'], True)
check('... a dict with other keys does not', 'application/vnd.plotly.v1+json' in run('{"data": [{"x": 1}], "other": 1}')['outputs'][0]['data'], False)
r = run('import statsmodels.formula.api as smf\nimport numpy as np\nd = pd.DataFrame({"y": np.arange(10.0) ** 1.5, "x": np.arange(10.0)})\nsmf.ols("y ~ x", d).fit().summary()')
check('a statsmodels summary shows as its HTML tables', ('text/html' in r['outputs'][-1]['data'], 'OLS Regression Results' in r['outputs'][-1]['data']['text/html']), (True, True))


class Broken:
    def _repr_html_(self):
        raise RuntimeError('no')

    def __repr__(self):
        return 'Broken()'


notebook.NAMESPACES.setdefault('nb', {})['Broken'] = Broken
r = run('Broken()')
check('a rich repr that fails falls back to the text', r['outputs'][0]['data'], {'text/plain': 'Broken()'})
check('a class is shown by its name, not asked for its reprs', run('Broken')['outputs'][0]['data'], {'text/plain': repr(Broken)})

# ---- errors -------------------------------------------------------------------------------------------------
r = run('print("before")\n1/0')
e = r['outputs'][-1]
check('an error comes after what the cell printed, as an error output', (kinds(r)[0], e['type'], e['ename'], e['evalue']), (('stream', 'stdout'), 'error', 'ZeroDivisionError', 'division by zero'))
check('... its traceback starts at the cell (named after the notebook, with its count)', (e['traceback'][0], e['traceback'][1].startswith('  File "<Notebook 1 ['), e['traceback'][-1]), ('Traceback (most recent call last):', True, 'ZeroDivisionError: division by zero'))
check('... with the line of code', any('1/0' in t for t in e['traceback']), True)
r = run('def f():\n    return g()\n\ndef g():\n    raise ValueError("deep")\nf()')
check('a traceback goes through the functions of the cell', sum('in f' in t or 'in g' in t for t in r['outputs'][0]['traceback']), 2)
r = run('x = (1,')
check('a SyntaxError shows where', (r['outputs'][0]['ename'], any('^' in t for t in r['outputs'][0]['traceback'])), ('SyntaxError', True))
check('SystemExit is an error of the cell, not the end of the engine', run('import sys\nsys.exit(3)')['outputs'][0]['ename'], 'SystemExit')

# ---- namespaces, counts, await ---------------------------------------------------------------------------
run('kept = 11', nb='a')
check('a notebook keeps its variables', run('kept', nb='a')['outputs'][0]['data']['text/plain'], '11')
check('... another notebook has its own', run('kept', nb='b')['outputs'][0]['ename'], 'NameError')
check('the count goes up per notebook', [run('1', nb='c')['count'] for _ in range(3)], [1, 2, 3])
notebook.reset('a')
check('reset() forgets the variables and the count', (run('kept', nb='a')['outputs'][0]['ename'], notebook.COUNTS['a']), ('NameError', 1))
run('z = 1', nb='d')
check('fresh: a namespace of its own first (a report\'s code block)', run('z', nb='d', fresh=True)['outputs'][0]['ename'], 'NameError')
check('the last value is kept as _', (run('40 + 2', nb='e') and run('_ + 1', nb='e'))['outputs'][0]['data']['text/plain'], '43')
r = run('import asyncio\nawait asyncio.sleep(0)\nasync def h():\n    return 5\nawait h()')
check('top-level await, and an awaited value last', r['outputs'][0]['data']['text/plain'], '5')

# ---- figures ------------------------------------------------------------------------------------------------------
r = run('import matplotlib.pyplot as plt\nplt.plot([1, 2, 3])\nplt.show()\nprint("after")\nplt.figure()\nplt.bar([1, 2], [3, 4])\nNone')
check('plt.show() shows the figure where it is; one left open shows at the end', kinds(r), [('display', ['image/svg+xml', 'text/plain']), ('stream', 'stdout'), ('display', ['image/svg+xml', 'text/plain'])])
check('... as SVG', r['outputs'][0]['data']['image/svg+xml'].lstrip().startswith('<?xml'), True)
check('... and the figures are closed after', run('plt.get_fignums()')['outputs'][0]['data']['text/plain'], '[]')
r = run('import numpy as np\nv = np.random.default_rng(0).normal(size=6000)\nplt.scatter(v, v);')
png = base64.b64decode(r['outputs'][0]['data']['image/png'])
check('a figure of many points goes as PNG, at twice its size, shown at half', (png[:4], r['outputs'][0]['metadata']['image/png']['width'] * 2 in (int.from_bytes(png[16:20], 'big'), int.from_bytes(png[16:20], 'big') - 1)), (b'\x89PNG', True))
r = run('fig, ax = plt.subplots()\nax.plot([1, 2])\nfig')
check('a figure as the last value shows once', [k for k in kinds(r)], [('display', ['image/svg+xml', 'text/plain'])])
check('matplotlib draws with the page\'s backend', run('import matplotlib\nmatplotlib.get_backend()')['outputs'][0]['data']['text/plain'], "'module://smui.nb_backend'")

# ---- the page's tables ------------------------------------------------------------------------------------------------
r = run('import smui\nt = smui.table("tiny")\n[str(t[c].dtype) for c in t], list(t["g"].cat.categories), list(t["o"].cat.categories), t["o"].cat.ordered, str(t["d"].iloc[1].date()), t["d"].isna().tolist()')
check('table(): continuous float, nominal and ordinal categorical in the value order, dates as datetimes', r['outputs'][0]['data']['text/plain'],
      "(['float64', 'category', 'category', 'datetime64[ms]'], ['b', 'a'], [3.0, 1.0, 2.0], True, '1970-01-02', [False, False, False, True])")
check('table() without a name is the current table; table_names() lists them', run('len(smui.table()), smui.table_names()')['outputs'][0]['data']['text/plain'], "(4, ['Tiny'])")
check('a name that is not open says which are', 'the open tables' in run('smui.table("Nope")')['outputs'][0]['evalue'], True)
r = run('out = pd.DataFrame({"n": [1, 2], "f": [0.5, float("nan")], "s": ["a", None], "b": [True, False], '
        '"c": pd.Categorical(["hi", "lo"], categories=["lo", "hi"], ordered=True), "d": pd.to_datetime(["2020-01-01 00:00", "2020-01-02 06:00"])})\nsmui.new_table(out, "Made")')
cols = {c['name']: c for c in r['tables'][0]['columns']}
check('new_table(): the name and the columns in order', (r['tables'][0]['name'], list(cols)), ('Made', ['n', 'f', 's', 'b', 'c', 'd']))
check('... numbers continuous, missing as None', (cols['n']['modelingType'], cols['f']['values']), ('continuous', [0.5, None]))
check('... text nominal, booleans nominal 0/1', ((cols['s']['dataType'], cols['s']['values']), (cols['b']['modelingType'], cols['b']['values'])), (('character', ['a', None]), ('nominal', [1.0, 0.0])))
check('... an ordered categorical ordinal in its order', (cols['c']['modelingType'], cols['c']['valueOrder']), ('ordinal', ['lo', 'hi']))
check('... datetimes as milliseconds, with a date and time format when they have times', (cols['d']['format'], cols['d']['values'][0]), ({'kind': 'datetime'}, 1577836800000.0))
r = run('smui.new_table(pd.DataFrame({"g": ["a", "b", "a"], "v": [1, 2, 3]}).groupby("g")["v"].sum())')
check('a groupby result keeps its keys as a column', [c['name'] for c in r['tables'][0]['columns']], ['g', 'v'])

sys.exit(check.done())
