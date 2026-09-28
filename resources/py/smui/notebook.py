"""The notebook's Python: cells run here, in the engine the reports use.

The page's notebook (smui-notebook.js) and the reports' editable code
blocks send a cell's code to run_cell(). Each notebook has a namespace of
its own, which lives until the notebook is restarted (reset()) or the
engine is. A cell may use top-level await (await micropip.install(...)).
What it prints and shows comes back as a list of outputs, in the order
they were made, the way Jupyter keeps them:

  {'type': 'stream', 'name': 'stdout' | 'stderr', 'text': str}
  {'type': 'result' | 'display', 'data': {mime: value}}
      text/plain, text/html, text/markdown, image/svg+xml, image/png
      (base64), and application/vnd.plotly.v1+json (a figure the page
      draws with its own Plotly)
  {'type': 'error', 'ename': str, 'evalue': str, 'traceback': [str]}

The last expression of a cell shows itself (a trailing ; keeps it quiet),
and so does every matplotlib figure still open when the cell ends;
plt.show() shows the open figures at once.

The page's tables are here already (data.TABLES). The page also writes
each one as the CSV file the reports' code reads ("<name>.csv", as File >
Export CSV writes it), so that code runs as it is. And in a cell:

    import smui
    smui.table_names()           the names of the open tables
    smui.table("Students")       one as a DataFrame: the modeling types as
                                 dtypes (ordinal and nominal columns as
                                 categoricals in the table's value order),
                                 date columns as datetimes
    smui.new_table(df, "Name")   a DataFrame back to the page, as a table
    display(x, ...)              show now (also smui.display)
"""
import ast
import base64
import contextlib
import inspect
import io
import json
import linecache
import os
import sys
import tokenize
import traceback

import numpy as np
import pandas as pd

from . import data
from .registry import api
from .util import clean

# The worker has no screen: matplotlib draws off screen (nb_backend is Agg,
# with a show() that hands the figures to the cell's outputs).
os.environ.setdefault('MPLBACKEND', 'module://smui.nb_backend')

NAMESPACES = {}          # notebook id -> its globals
COUNTS = {}              # notebook id -> the last execution count
TABLE_IDS = {}           # a page table's name -> its id, from the last run
CURRENT = [None]         # the page's current table id
TEXT_LIMIT = 400_000     # characters of one output's text kept
HEAVY = 4000             # a figure with more points than this goes as PNG

_run = None              # the outputs of the cell being run


class _Run:
    def __init__(self):
        self.outputs = []
        self.tables = []

    def stream(self, name, text):
        last = self.outputs[-1] if self.outputs else None
        if last and last['type'] == 'stream' and last['name'] == name:
            if len(last['text']) < TEXT_LIMIT:
                last['text'] = (last['text'] + text)[:TEXT_LIMIT]
        else:
            self.outputs.append({'type': 'stream', 'name': name, 'text': text[:TEXT_LIMIT]})

    def show(self, obj, kind='display'):
        data, meta = bundle(obj)
        self.outputs.append({'type': kind, 'data': data, 'metadata': meta})


class _Stream(io.TextIOBase):
    """sys.stdout and sys.stderr while a cell runs."""

    def __init__(self, name):
        self._name = name

    @property
    def encoding(self):
        return 'utf-8'

    def writable(self):
        return True

    def isatty(self):
        return False

    def write(self, s):
        if not isinstance(s, str):
            s = str(s)
        if s and _run is not None:
            _run.stream(self._name, s)
        return len(s)


# ---- what an object looks like -----------------------------------------------------------
def _figure(obj):
    mod = sys.modules.get('matplotlib.figure')
    return obj if mod is not None and isinstance(obj, mod.Figure) else None


def _points(fig):
    n = 0
    for ax in fig.axes:
        for line in ax.lines:
            n += len(line.get_xdata())
        for c in ax.collections:
            try:
                n += len(c.get_offsets())
            except Exception:  # noqa: BLE001 - a collection without offsets
                pass
        n += len(ax.patches)
    return n


def figure_bundle(fig):
    """A figure as SVG (as PNG, drawn at twice the size and shown at half,
    when it has many points), with a line of text: (data, metadata)."""
    w, h = fig.get_size_inches() * fig.dpi
    text = f'<Figure size {w:.0f}x{h:.0f} with {len(fig.axes)} Axes>'
    if _points(fig) > HEAVY:
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=fig.dpi * 2, bbox_inches='tight')
        png = buf.getvalue()
        width = int.from_bytes(png[16:20], 'big') // 2          # from the PNG's header
        return {'image/png': base64.b64encode(png).decode('ascii'), 'text/plain': text}, {'image/png': {'width': width}}
    buf = io.StringIO()
    fig.savefig(buf, format='svg', bbox_inches='tight')
    return {'image/svg+xml': buf.getvalue(), 'text/plain': text}, {}


def _plotly(obj):
    """A Plotly figure: a plotly object, or a dict of data (and layout)."""
    to_json = getattr(obj, 'to_plotly_json', None)
    if callable(to_json) and not inspect.isclass(obj):
        try:
            return clean(to_json())
        except Exception:  # noqa: BLE001
            return None
    if isinstance(obj, dict) and isinstance(obj.get('data'), (list, tuple)) and set(obj) <= {'data', 'layout', 'config', 'frames'} \
            and obj['data'] and all(isinstance(t, dict) for t in obj['data']):
        return clean(obj)
    return None


_RICH = (('text/html', '_repr_html_'), ('text/markdown', '_repr_markdown_'),
         ('image/svg+xml', '_repr_svg_'), ('image/png', '_repr_png_'))


def _text(obj):
    try:
        s = repr(obj)
    except Exception as e:  # noqa: BLE001 - a broken __repr__
        s = f'<{type(obj).__name__} object: repr failed: {e}>'
    return s if len(s) <= TEXT_LIMIT else s[:TEXT_LIMIT] + ' …'


def bundle(obj):
    """The mime bundle of obj, as Jupyter's display makes it: (data, metadata)."""
    fig = _figure(obj)
    if fig is not None:
        return figure_bundle(fig)
    out = {}
    plot = _plotly(obj)
    if plot is not None:
        out['application/vnd.plotly.v1+json'] = plot
    if not inspect.isclass(obj):
        for mime, attr in _RICH:
            meth = getattr(type(obj), attr, None) and getattr(obj, attr, None)
            if not callable(meth):
                continue
            try:
                v = meth()
            except Exception:  # noqa: BLE001 - a rich repr that fails falls back to text
                continue
            if isinstance(v, tuple):
                v = v[0]
            if isinstance(v, (bytes, bytearray)) and mime == 'image/png':
                v = base64.b64encode(bytes(v)).decode('ascii')
            if isinstance(v, str) and v:
                out[mime] = v if len(v) <= 4 * TEXT_LIMIT else v[:4 * TEXT_LIMIT]
    out['text/plain'] = _text(obj)
    return out, {}


def display(*objs):
    """Show each object under the cell now, as its last line would be."""
    if _run is None:
        for o in objs:
            print(_text(o))
        return
    for o in objs:
        _run.show(o)


def flush_figures():
    """Show the open matplotlib figures, then close them (plt.show() in a cell)."""
    plt = sys.modules.get('matplotlib.pyplot')
    if plt is None or _run is None:
        return
    for num in plt.get_fignums():
        data, meta = figure_bundle(plt.figure(num))
        _run.outputs.append({'type': 'display', 'data': data, 'metadata': meta})
    plt.close('all')


# ---- the page's tables --------------------------------------------------------------------
def table_names():
    """The names of the tables open in the page. (Not smui.tables: that is the
    Tables platform's module.)"""
    return list(TABLE_IDS)


def _table_id(name):
    if name is None:
        return CURRENT[0]
    if name in TABLE_IDS:
        return TABLE_IDS[name]
    same = [k for k in TABLE_IDS if k.casefold() == str(name).casefold()]
    return TABLE_IDS[same[0]] if len(same) == 1 else None


def table(name=None):
    """A table open in the page as a DataFrame (the current one without a
    name): continuous columns as floats, ordinal and nominal ones as
    categoricals in the table's value order (ordered for ordinal), date
    columns as datetimes. The index is the page's row number, from 0."""
    tid = _table_id(name)
    if tid is None or tid not in data.TABLES:
        have = ', '.join(repr(k) for k in TABLE_IDS) or 'none'
        raise KeyError(f'no open table {name!r} (the open tables: {have})' if name is not None else f'no current table (the open tables: {have})')
    t = data.TABLES[tid]
    cols = {}
    for c, m in t['meta'].items():
        s = data.series(tid, c)
        kind = (m.get('format') or {}).get('kind')
        if m.get('dataType') == 'numeric' and m.get('modelingType') == 'continuous' and kind in ('date', 'datetime'):
            s = pd.to_datetime(s, unit='ms')
        cols[c] = s
    return pd.DataFrame(cols, index=pd.RangeIndex(t['n']))


def _column(name, s):
    """One column of a DataFrame as the page's table takes it."""
    if isinstance(s.dtype, pd.CategoricalDtype):
        cats = s.cat.categories
        numeric = pd.api.types.is_numeric_dtype(cats)
        conv = (lambda v: float(v)) if numeric else (lambda v: str(v))
        return {'name': name, 'dataType': 'numeric' if numeric else 'character',
                'modelingType': 'ordinal' if s.cat.ordered else 'nominal',
                'valueOrder': [conv(v) for v in cats],
                'values': [None if pd.isna(v) else conv(v) for v in s]}
    if pd.api.types.is_bool_dtype(s):
        return {'name': name, 'dataType': 'numeric', 'modelingType': 'nominal',
                'values': [None if pd.isna(v) else float(bool(v)) for v in s]}
    if pd.api.types.is_datetime64_any_dtype(s):
        d = s.dt.tz_convert(None) if getattr(s.dt, 'tz', None) is not None else s
        ms = (d - pd.Timestamp(0)) / pd.Timedelta(milliseconds=1)
        timed = bool(((d.dropna() - d.dropna().dt.normalize()) != pd.Timedelta(0)).any())
        return {'name': name, 'dataType': 'numeric', 'modelingType': 'continuous',
                'format': {'kind': 'datetime' if timed else 'date'},
                'values': [None if pd.isna(v) else float(v) for v in ms]}
    if pd.api.types.is_timedelta64_dtype(s):
        return {'name': name, 'dataType': 'numeric', 'modelingType': 'continuous', 'notes': 'seconds',
                'values': [None if pd.isna(v) else v / pd.Timedelta(seconds=1) for v in s]}
    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_complex_dtype(s):
        v = s.to_numpy(dtype=float, na_value=np.nan)
        return {'name': name, 'dataType': 'numeric', 'modelingType': 'continuous',
                'values': [None if not np.isfinite(x) and np.isnan(x) else float(x) for x in v]}
    return {'name': name, 'dataType': 'character', 'modelingType': 'nominal',
            'values': [None if (v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA or v is pd.NaT) else str(v) for v in s]}


def new_table(frame, name=None):
    """Put a DataFrame (or anything pandas makes one of) into the page as a
    new table. An index that is not the plain row count (a groupby's keys,
    say) becomes columns first. Categoricals keep their order and become
    nominal (ordinal when ordered), booleans nominal 0/1, datetimes dates."""
    if _run is None:
        raise RuntimeError('smui.new_table works in a notebook cell')
    df = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
    idx = df.index
    if not (isinstance(idx, pd.RangeIndex) and idx.start == 0 and idx.step == 1):
        df = df.reset_index()
    names = [' '.join(str(p) for p in c if str(p)) if isinstance(c, tuple) else str(c) for c in df.columns]
    cols = [_column(n, df.iloc[:, i]) for i, n in enumerate(names)]
    title = name or getattr(frame, 'name', None) or 'From Python'
    _run.tables.append({'name': str(title), 'columns': cols})
    return f'{title}: {len(df)} rows, {len(cols)} columns, sent to the page'


# ---- running a cell -----------------------------------------------------------------------
def _quiet(code):
    """True when the cell's last statement ends with ';' (IPython's rule)."""
    try:
        toks = [t for t in tokenize.generate_tokens(io.StringIO(code).readline)
                if t.type not in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.ENDMARKER, tokenize.INDENT, tokenize.DEDENT)]
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return False
    return bool(toks) and toks[-1].type == tokenize.OP and toks[-1].string == ';'


async def _execute(code, ns, filename):
    """Run the cell; return (value of the last expression, whether there was one)."""
    tree = ast.parse(code, filename=filename, mode='exec')
    last = None
    if tree.body and isinstance(tree.body[-1], ast.Expr) and not _quiet(code):
        last = ast.Expression(tree.body.pop().value)
    flags = ast.PyCF_ALLOW_TOP_LEVEL_AWAIT
    if tree.body:
        r = eval(compile(tree, filename, 'exec', flags=flags), ns)  # noqa: S307 - the user's own cell
        if inspect.iscoroutine(r):
            await r
    if last is None:
        return None, False
    v = eval(compile(last, filename, 'eval', flags=flags), ns)  # noqa: S307
    if inspect.iscoroutine(v):
        v = await v
    return v, True


def _traceback(e, filename_prefix):
    """The error as Python prints it, without this module's own frames."""
    if isinstance(e, SyntaxError):
        lines = traceback.format_exception_only(type(e), e)
    else:
        frames = traceback.extract_tb(e.__traceback__)
        start = next((i for i, f in enumerate(frames) if f.filename.startswith(filename_prefix)), 0)
        lines = ['Traceback (most recent call last):\n'] + traceback.format_list(frames[start:]) + traceback.format_exception_only(type(e), e)
    return ''.join(lines).rstrip('\n').split('\n')


def _namespace(nb):
    ns = NAMESPACES.get(nb)
    if ns is None:
        ns = {'__name__': '__main__', '__builtins__': __builtins__, 'display': display}
        NAMESPACES[nb] = ns
    return ns


def _matplotlib_ready():
    """If matplotlib is in, make sure it draws with this page's backend."""
    mpl = sys.modules.get('matplotlib')
    if mpl is None:
        return
    want = 'module://smui.nb_backend'
    try:
        if mpl.get_backend() != want:
            mpl.use(want, force=True)
    except Exception:  # noqa: BLE001 - keep the user's backend if ours will not load
        pass


async def run_cell(nb, code, info_json='{}'):
    """Run one cell of notebook nb. info: {tables: [{id, name}], current (a
    table id), label (the notebook's name, for tracebacks), fresh (a new
    namespace first: a report's code block runs on its own)}. Returns JSON:
    {outputs, tables (new ones for the page), count}."""
    global _run
    info = json.loads(info_json) if info_json else {}
    TABLE_IDS.clear()
    for t in info.get('tables') or []:
        TABLE_IDS[t['name']] = t['id']
    CURRENT[0] = info.get('current')
    if info.get('fresh'):
        reset(nb)
    ns = _namespace(nb)
    count = COUNTS.get(nb, 0) + 1
    COUNTS[nb] = count
    label = str(info.get('label') or 'cell')
    filename = f'<{label} [{count}]>'
    linecache.cache[filename] = (len(code), None, [ln + '\n' for ln in code.split('\n')], filename)
    run = _Run()
    prev, _run = _run, run
    try:
        _matplotlib_ready()
        with contextlib.redirect_stdout(_Stream('stdout')), contextlib.redirect_stderr(_Stream('stderr')):
            try:
                value, has = await _execute(code, ns, filename)
                _matplotlib_ready()
                if has and value is not None:
                    fig = _figure(value)
                    if fig is not None:
                        # the figure shows once: with the others still open
                        plt = sys.modules.get('matplotlib.pyplot')
                        if plt is None or fig.number not in plt.get_fignums():
                            run.show(fig, 'result')
                    else:
                        run.show(value, 'result')
                    ns['_'] = value
                flush_figures()
            except BaseException as e:  # noqa: BLE001 - every error of the cell is its output, SystemExit too
                flush_figures()
                run.outputs.append({'type': 'error', 'ename': type(e).__name__, 'evalue': str(e), 'traceback': _traceback(e, '<')})
    finally:
        _run = prev
    return json.dumps(clean({'outputs': run.outputs, 'tables': run.tables, 'count': count}), allow_nan=False)


@api('nb.reset')
def reset(nb):
    """Forget a notebook's variables (Restart, and before a code block runs)."""
    NAMESPACES.pop(nb, None)
    COUNTS.pop(nb, None)
    plt = sys.modules.get('matplotlib.pyplot')
    if plt is not None:
        plt.close('all')
    return {'ok': True}
