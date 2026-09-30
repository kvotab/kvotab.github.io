"""JSL to Python: the translator behind smui.html's JSL converter.

jsl.py reads a JSL script into a tree; this module writes the Python that
does what the script does, with pandas for the data tables, numpy for the
matrices, scipy and the standard library for the rest, and notes on
everything that did not convert. convert() (the page's 'jsl.convert')
returns the script, the notes, and one step for each platform launch that
the page runs as its own analysis: the page puts that analysis's Python
where the step's marker line is.

How JSL maps to Python here:

- Values: numbers, strings, lists (Python lists), matrices (2-D numpy
  arrays, as JSL's always are), associative arrays (dicts), "." (np.nan).
  JSL's subscripts count from 1 and Python's from 0: a literal subscript is
  lowered as it is written, any other gets "- 1"; a matrix subscript of 0
  means every row or column. JSL's * between two matrices is a matrix
  product (@); a matrix is known from a literal, J(), Identity() and the
  matrix functions, and where it cannot be known * stays, with a note.
- Data tables are pandas DataFrames. A table the page has open is read as
  File > Export CSV writes it ("<name>.csv"), as the page's own code reads
  it. A column formula becomes one vectorised assignment (If to np.where,
  Col Mean to a groupby transform, Lag to shift); what cannot be
  vectorised runs row by row. Row states (selected, excluded, hidden,
  labeled) become boolean masks; an analysis later in the script leaves
  the excluded rows out, as JMP does.
- Dates are pandas Timestamps: JMP counts seconds from 1 January 1904,
  and where the script does arithmetic in seconds the translation says so.
- Platform launches that the page has become steps: the roles and options
  in the page's own terms, and a marker in the Python where the page puts
  that analysis's code. The rest of the language that has no sound Python
  meaning (display boxes, expressions as data, report objects) is left as
  a "# NOT CONVERTED" comment with a note.
"""
import builtins
import contextlib
import json
import keyword
import math
import re
import warnings

from . import jsl
from .registry import api
from .util import clean, one_line

# Python's operator precedence, loose to tight
P_IF, P_OR, P_AND, P_NOT, P_CMP, P_BOR, P_BXOR, P_BAND, P_SHIFT, P_ADD, P_MUL, P_UNARY, P_POW, P_ATOM = range(1, 15)

# tests set this, so that a fault of the translator shows as an exception
STRICT = False

RESERVED = set(keyword.kwlist) | set(keyword.softkwlist) | set(dir(builtins)) | {
    'np', 'pd', 'stats', 'special', 'sm', 'smf', 'plt', 'math', 're', 'os', 'sys', 'time', 'collections',
    'rng', 'row', 'df', 'JMP_EPOCH'}


class Unconvertible(Exception):
    """Something without a sound Python meaning: the statement is left as a comment."""

    def __init__(self, why, node=None):
        super().__init__(why)
        self.why = why
        self.node = node


class Dynamic(Exception):
    """Columns (or a table) chosen while the script runs: a launch cannot be mapped."""


class E:
    """A translated expression: its Python code, the precedence of its
    outermost operator, and what the translator knows of its value."""
    __slots__ = ('code', 'prec', 'type', 'info')

    def __init__(self, code, prec=P_ATOM, type='unknown', info=None):
        self.code, self.prec, self.type, self.info = code, prec, type, info

    def __repr__(self):
        return f'E({self.code!r}, {self.type})'


NUMBER = re.compile(r'-?\d+(\.\d*)?([eE][-+]?\d+)?')


def par(e, prec):
    """e's code, in parentheses when its operator binds looser than prec (and
    a number that an attribute or subscript follows: 5.real is no Python)."""
    if e.prec < prec or (prec >= P_ATOM and NUMBER.fullmatch(e.code)):
        return f'({e.code})'
    return e.code


def str_body(v, quote='"'):
    """The inside of a Python string literal in the given quote: backslashes,
    that quote, control characters and lone surrogates escaped."""
    out = []
    for ch in v:
        o = ord(ch)
        if ch == '\\' or ch == quote:
            out.append('\\' + ch)
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\t':
            out.append('\\t')
        elif ch == '\r':
            out.append('\\r')
        elif o < 32 or o == 127:
            out.append(f'\\x{o:02x}')
        elif 0xD800 <= o <= 0xDFFF:
            out.append(f'\\u{o:04x}')
        else:
            out.append(ch)
    return ''.join(out)


def lit(v):
    """A Python literal for a number or a string."""
    if v is None:
        return 'np.nan'
    if isinstance(v, bool):
        return 'True' if v else 'False'
    if isinstance(v, str):
        return '"' + str_body(v) + '"'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return 'np.nan'
        if math.isinf(v):
            return 'np.inf' if v > 0 else '-np.inf'
        if v == int(v) and abs(v) < 1e15:
            return repr(float(v))
        return repr(v)
    return repr(v)


def num_e(v):
    t = 'int' if isinstance(v, int) and not isinstance(v, bool) else 'num'
    code = lit(v)
    return E(code, P_UNARY if code.startswith('-') else P_ATOM, t)


def is_num_type(t):
    return t in ('int', 'num', 'bool')


class Ctx:
    """Where an expression is: 'scalar' (plain Python), 'vec' (a column
    formula over a table, vectorised) or 'row' (a loop over a table's rows,
    the row number in `row`, 0-based). cond: only its truth matters."""
    __slots__ = ('mode', 'frame', 'cond')

    def __init__(self, mode='scalar', frame=None, cond=False):
        self.mode, self.frame, self.cond = mode, frame, cond

    def but(self, **kw):
        c = Ctx(self.mode, self.frame, self.cond)
        for k, v in kw.items():
            setattr(c, k, v)
        return c


SCALAR = Ctx()


class Frame:
    """A data table as a DataFrame: its Python variable, JMP name, columns."""

    def __init__(self, var, name, page=None, origin='script'):
        self.var = var
        self.name = name
        self.page = page          # the page's table (from `tables`), when it is one
        self.origin = origin      # 'page', 'file' or 'script'
        self.cols = {}            # key -> {'name', 'dtype', 'mt', 'new'}
        self.known = False        # the column list is complete
        self.masks = {}           # 'selected', 'excluded', 'hidden', 'labeled' -> variable
        if page:
            for c in page.get('columns') or []:
                self.add_col(c.get('name', ''), c.get('dataType'), c.get('modelingType'), new=False)
            self.known = True

    def add_col(self, name, dtype=None, mt=None, new=True):
        k = jsl.name_key(name)
        old = self.cols.get(k)
        if old:
            if dtype:
                old['dtype'] = dtype
            if mt:
                old['mt'] = mt
            return old
        self.cols[k] = {'name': name, 'dtype': dtype, 'mt': mt or ('nominal' if dtype == 'character' else ('continuous' if dtype == 'numeric' else None)), 'new': new}
        return self.cols[k]

    def col(self, name):
        return self.cols.get(jsl.name_key(name))

    def copy_cols(self, other, names=None):
        for c in other.cols.values():
            if names is None or jsl.name_key(c['name']) in names:
                self.cols[jsl.name_key(c['name'])] = dict(c)
        self.known = other.known if names is None else True


class ColRef:
    """A column of a table: its name (when known as it is written) and the
    Python expression of the name (a string literal, or a variable's)."""
    __slots__ = ('frame', 'name', 'code')

    def __init__(self, frame, name, code=None):
        self.frame, self.name = frame, name
        self.code = code if code is not None else lit(name)

    def series(self):
        return f'{self.frame.var}[{self.code}]'


def show_label(src):
    """An expression as Show() prints it: its runs of whitespace made one
    space, except inside strings."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 3 if src.startswith('\\!', j) else 1
            out.append(src[i:j + 1])
            i = j + 1
        elif c.isspace():
            while i < n and src[i].isspace():
                i += 1
            out.append(' ')
        else:
            out.append(c)
            i += 1
    return ''.join(out).strip()


def excerpt(text, n=70):
    """The first line of a piece of JSL, shortened, for a comment."""
    one = ' '.join(text.strip().split())
    return one if len(one) <= n else one[:n - 1].rstrip() + '…'


def ident(text):
    """A Python identifier from a JSL name."""
    s = re.sub(r'\W+', '_', text.strip(), flags=re.UNICODE).strip('_')
    s = re.sub(r'_+', '_', s)
    if not s:
        s = 'x'
    if s[0].isdigit():
        s = f'v_{s}'
    if not s.isidentifier():
        s = 'x_' + re.sub(r'[^0-9a-zA-Z_]', '_', s)
    return s


def snake(text):
    """A variable name for a table: its name in lower case with underscores."""
    s = ident(text).lower()
    return s if len(s) <= 30 else s[:30].rstrip('_')


class _Core:
    def __init__(self, program, tables=None, current=None):
        self.p = program
        self.tables = [t for t in (tables or []) if isinstance(t, dict) and t.get('name')]
        self.current_name = current
        self.body = []            # (indent, text)
        self.ind = 0
        self.notes = []
        self._note_keys = set()
        self.steps = []
        self.helpers = []
        self.names = {}           # JSL key -> Python name
        self.taken = set()        # Python names in use
        self.vtypes = {}          # JSL key -> E (type and info) of the variable's last value
        self.frames = []
        self.cur = None           # the current data table
        self.preload = []         # the page's current table, read first when the script uses it without naming it
        self.comments = sorted(program.comments, key=lambda c: c[0])
        self.ci = 0
        self.loops = []           # {'incr': [lines to run before continue]}
        self.funcs = []           # the functions being written: {'globals': set, 'locals': set}
        self.shifted = set()      # loop counters written 0-based (only ever used as subscripts)
        self.rng = None           # the random generator's variable, once made
        self.cur_line = 1         # the line of the statement being translated

    # ---- output ------------------------------------------------------------
    def emit(self, text):
        for line in text.split('\n'):
            self.body.append((self.ind, line))

    @contextlib.contextmanager
    def block(self):
        self.ind += 1
        start = len(self.body)
        try:
            yield
        finally:
            if not any(ind >= self.ind and t.strip() and not t.lstrip().startswith('#') for ind, t in self.body[start:]):
                self.body.append((self.ind, 'pass'))
            self.ind -= 1

    def note(self, line, severity, text, once=None):
        key = once or (line, text)
        if key in self._note_keys:
            return
        self._note_keys.add(key)
        self.notes.append({'line': int(line or 0), 'severity': severity, 'text': text})

    def flush_comments(self, line):
        while self.ci < len(self.comments) and self.comments[self.ci][0] < line:
            ln, text, alone = self.comments[self.ci]
            self.ci += 1
            if text and alone and not text.startswith('!'):
                # a line of its own for each line of the comment: Python ends a
                # line at \r too, where JSL does not, and no text may end the
                # comment and become code
                for piece in re.split(r'\r\n|\r|\n', text):
                    self.emit(f'# {one_line(piece)}' if piece.strip() else '#')

    def not_converted(self, node, why, severity='warn'):
        src = self.p.source(node)
        self.emit(f'# NOT CONVERTED (line {node.line}): {excerpt(src)}')
        self.note(node.line, severity, why)

    def helper(self, name):
        if name not in self.helpers:
            for dep in HELPER_DEPS.get(name, ()):
                self.helper(dep)
            self.helpers.append(name)
        return name

    # ---- names ---------------------------------------------------------------
    def py(self, key, display=None):
        """The Python name of a JSL variable, the same for every spelling."""
        if key in self.names:
            return self.names[key]
        base = ident(display or key)
        if base in RESERVED or base.startswith('jsl_'):
            base += '_'
        name, k = base, 2
        while name in self.taken:
            name = f'{base}{k}'
            k += 1
        self.names[key] = name
        self.taken.add(name)
        return name

    def fresh(self, base):
        """A new Python name for something the translation makes."""
        base = ident(base)
        if base in RESERVED:
            base += '_'
        name, k = base, 2
        while name in self.taken:
            name = f'{base}{k}'
            k += 1
        self.taken.add(name)
        return name

    # ---- tables ----------------------------------------------------------------
    def page_table(self, name):
        """The page's table of this name (case does not matter), or None."""
        if not name:
            return None
        k = jsl.name_key(name)
        for t in self.tables:
            if jsl.name_key(t['name']) == k:
                return t
        return None

    def read_line(self, var, name, path=None):
        """The line that reads a table the page has, as its own code does."""
        return f'# the table, as File > Export CSV writes it (an empty field is missing)\n{var} = pd.read_csv({lit(name + ".csv")}, float_precision="round_trip", keep_default_na=False, na_values=[""])'

    def current_frame(self, node=None):
        """The current data table; the page's current table when the script
        has not opened or made one."""
        if self.cur is not None:
            return self.cur
        name = self.current_name
        page = self.page_table(name) if name else None
        if page is None and len(self.tables) == 1:
            page = self.tables[0]
        var = self.fresh('dt') if 'dt' not in self.names else self.fresh('dt_current')
        if page is not None:
            fr = Frame(var, page['name'], page, 'page')
            self.preload.append(self.read_line(var, page['name']))
        else:
            fr = Frame(var, name or 'data', None, 'page')
            self.preload.append(self.read_line(var, name or 'data'))
            self.note(node.line if node is not None else 1, 'warn',
                      'The script uses the current data table, and the page has none open: the translation reads "data.csv"; open the table in the page first (or change the file name).',
                      once='no-current')
        self.frames.append(fr)
        self.cur = fr
        return fr

    def frame_by_name(self, name):
        k = jsl.name_key(name)
        for f in reversed(self.frames):
            if jsl.name_key(f.name) == k:
                return f
        return None

    def new_frame(self, var, name, origin='script', page=None):
        fr = Frame(var, name, page, origin)
        self.frames.append(fr)
        return fr

    def column_of(self, fr, name, node):
        """The column's name as the table has it; a note when the table
        does not have it."""
        c = fr.col(name)
        if c:
            return c['name']
        if fr.known and node is not None:
            self.note(node.line, 'warn', f'{fr.name} has no column {name}; the translation uses the name as written.', once=('nocol', fr.name, jsl.name_key(name)))
        return name

    # ---- variables' types ---------------------------------------------------------
    def settype(self, key, e):
        old = self.vtypes.get(key)
        if old is not None and self.loops and old.type != e.type:
            # a variable that changes kind in a loop: nothing is known of it
            e = E(e.code, e.prec, 'unknown')
        self.vtypes[key] = E(None, P_ATOM, e.type, e.info)

    def typeof(self, key):
        v = self.vtypes.get(key)
        return v.type if v else 'unknown'


class NotVec(Exception):
    """A formula that cannot be written as whole-column operations."""


# JSL functions, by their canonical names: a method of the translator each
FN = {}


def fn(*names):
    def deco(f):
        for n in names:
            FN[jsl.name_key(n)] = f
        return f
    return deco


class _Expr(_Core):
    # ---- the entry -------------------------------------------------------------
    def x(self, node, ctx=SCALAR):
        m = getattr(self, 'x_' + node.kind, None)
        if m is None:
            raise Unconvertible(f'{node.kind} has no Python translation', node)
        return m(node, ctx)

    def xs(self, nodes, ctx):
        return [self.x(n, ctx) for n in nodes]

    def nargs(self, node, lo, hi=None):
        # Empty items at the end are dropped; one before a real argument
        # would move the arguments after it, so it is not guessed at.
        kinds = [a.kind for a in node.args]
        while kinds and kinds[-1] == 'empty':
            kinds.pop()
        if 'empty' in kinds:
            raise Unconvertible(f'{node.value}() with an empty argument ({kinds.index("empty") + 1} of {len(kinds)})', node)
        n = len([a for a in node.args if a.kind != 'empty'])
        hi = lo if hi is None else hi
        if n < lo or (hi >= 0 and n > hi):
            want = f'{lo}' if lo == hi else (f'{lo} to {hi}' if hi >= 0 else f'at least {lo}')
            raise Unconvertible(f'{node.value}() takes {want} arguments here, and has {n}', node)
        return [a for a in node.args if a.kind != 'empty']

    def vec(self, ctx):
        return ctx.mode == 'vec'

    # ---- literals ---------------------------------------------------------------
    def x_num(self, node, ctx):
        return num_e(node.value)

    def x_str(self, node, ctx):
        return E(lit(node.value), P_ATOM, 'str')

    def x_missing(self, node, ctx):
        return E('np.nan', P_ATOM, 'num')

    def x_empty(self, node, ctx):
        return E('None', P_ATOM, 'none')

    def x_date(self, node, ctx):
        y, mo, d, hh, mi, ss = node.extra['ymd']
        self.date_note(node)
        text = f'{y:04d}-{mo:02d}-{d:02d}'
        if hh or mi or ss:
            sec = f'{ss:09.6f}'.rstrip('0').rstrip('.') if ss != int(ss) else f'{int(ss):02d}'
            text += f' {hh:02d}:{mi:02d}:{sec}'
        return E(f'pd.Timestamp({lit(text)})', P_ATOM, 'date')

    def date_note(self, node):
        self.note(node.line, 'info', 'Dates: JMP counts date-times in seconds from 1 January 1904; here they are pandas Timestamps, and a difference of two is a Timedelta (.total_seconds() gives JMP\'s number of seconds).', once='dates')

    def x_list(self, node, ctx):
        items = []
        names = []
        for a in node.args:
            if a.kind == 'empty':
                self.note(node.line, 'warn', 'An empty item in a list is left out here: check the length of the list.', once=('emptyitem', node.line))
                continue
            ref = self.colref(a, ctx, quiet=True)
            if ref is not None and ref.name is not None:
                items.append(lit(ref.name))
                names.append(ref.name)
                continue
            items.append(self.x(a, ctx).code)
            if a.kind == 'str':
                names.append(a.value)
        # a list of column references or of strings: the column names it may stand for (Eval(cols) in a role)
        info = {'columns': names} if names and len(names) == len(items) else None
        return E('[' + ', '.join(items) + ']', P_ATOM, 'list', info)

    def x_matrix(self, node, ctx):
        rows = node.value
        if not rows:
            return E('np.empty((0, 0))', P_ATOM, 'matrix', (0, 0))
        cell = lambda v: 'np.nan' if v is None else lit(v)
        if all(len(r) == 1 for r in rows) and len(rows) > 1:
            code = 'np.array([[' + ', '.join(cell(r[0]) for r in rows) + ']]).T'
            return E(code, P_ATOM, 'matrix', (len(rows), 1))
        code = 'np.array([' + ', '.join('[' + ', '.join(cell(v) for v in r) + ']' for r in rows) + '])'
        return E(code, P_ATOM, 'matrix', (len(rows), len(rows[0])))

    def x_assoc(self, node, ctx):
        items = []
        for p in node.args:
            k, v = p.args
            items.append(f'{self.x(k, ctx).code}: {self.x(v, ctx).code}')
        body = '{' + ', '.join(items) + '}'
        d = node.extra.get('default')
        if d is not None:
            return E(f'collections.defaultdict(lambda: {self.x(d, ctx).code}, {body})', P_ATOM, 'dict')
        return E(body, P_ATOM, 'dict')

    # ---- names -------------------------------------------------------------------
    def x_name(self, node, ctx):
        key = node.key
        if key in self.shifted:
            return E(f'{self.py(key)} + 1', P_ADD, 'int')
        if key == 'exception_msg':
            return E(self.py(key, 'exception_msg'), P_ATOM, 'unknown')
        known = key in self.vtypes or key in self.names
        fr = ctx.frame if ctx.mode in ('vec', 'row') else None
        if not known:
            # an unscoped name that is no variable: a column of the table, as JMP resolves it
            fr2 = fr or self.cur
            if fr2 is not None and fr2.col(node.value):
                return self.col_value(ColRef(fr2, fr2.col(node.value)['name']), ctx, node)
        if fr is not None and fr.col(node.value) and key not in self.vtypes:
            return self.col_value(ColRef(fr, fr.col(node.value)['name']), ctx, node)
        v = self.vtypes.get(key)
        if v is not None and v.type == 'frame' and isinstance(v.info, Frame):
            return E(v.info.var, P_ATOM, 'frame', v.info)
        if v is not None and v.type == 'col' and isinstance(v.info, ColRef):
            # a name that holds a column stands for the column
            return self.col_value(v.info, ctx, node)
        return E(self.py(key, node.value), P_ATOM, v.type if v else 'unknown', v.info if v else None)

    def x_global(self, node, ctx):
        v = self.vtypes.get(node.key)
        if self.funcs:
            self.funcs[-1]['globals'].add(node.key)
        return E(self.py(node.key, node.value), P_ATOM, v.type if v else 'unknown', v.info if v else None)

    def x_scope(self, node, ctx):
        left = node.args[0]
        if left.kind == 'name' and left.key in ('here', 'global', 'local', 'window'):
            v = self.vtypes.get(node.key)
            return E(self.py(node.key, node.value), P_ATOM, v.type if v else 'unknown', v.info if v else None)
        ref = self.colref(node, ctx)
        if ref is not None:
            return self.col_value(ref, ctx, node)
        raise Unconvertible(f'{self.p.source(node)}: a variable of a namespace; namespaces have no translation here', node)

    def x_col(self, node, ctx):
        return self.col_value(self.colref(node, ctx), ctx, node)

    # ---- columns ---------------------------------------------------------------------
    def frame_of(self, node, ctx=SCALAR, need=True):
        """The table a JSL expression stands for, or None."""
        if node.kind == 'name':
            v = self.vtypes.get(node.key)
            if v is not None and v.type == 'frame':
                return v.info
            if need:
                raise Unconvertible(f'{node.value} is not known to be a data table here', node)
            return None
        if node.is_call('currentdatatable') and not node.args:
            return self.current_frame(node)
        if node.is_call('datatable', 'getdatatable') and len(node.args) == 1:
            return self.table_by_arg(node.args[0], node)
        if need:
            raise Unconvertible(f'{self.p.source(node)} is not known to be a data table here', node)
        return None

    def table_by_arg(self, arg, node):
        if arg.kind == 'str':
            fr = self.frame_by_name(arg.value)
            if fr is not None:
                return fr
            page = self.page_table(arg.value)
            var = self.fresh(snake(arg.value) if snake(arg.value) not in ('', 'x') else 'dt')
            fr = self.new_frame(var, page['name'] if page else arg.value, 'page' if page else 'file', page)
            self.emit(self.read_line(var, fr.name))
            if page is None:
                self.note(node.line, 'warn', f'Data Table("{arg.value}"): the page has no table of that name open; the translation reads "{arg.value}.csv".', once=('notable', arg.value))
            return fr
        if arg.kind == 'num' and arg.value == 1 and self.frames:
            return self.frames[0]
        raise Unconvertible(f'{self.p.source(node)}: a table chosen while the script runs', node)

    def colref(self, node, ctx=SCALAR, quiet=False):
        """The column a JSL expression names: :x, dt:x, Column(dt, "x"),
        As Column(...), a bare column name; or None."""
        k = node.kind
        if k == 'col':
            fr = ctx.frame if ctx.mode in ('vec', 'row') and ctx.frame is not None else self.current_frame(node)
            return ColRef(fr, self.column_of(fr, node.value, node))
        if k == 'scope':
            left = node.args[0]
            if left.kind == 'name' and left.key in ('here', 'global', 'local', 'window'):
                return None
            fr = self.frame_of(left, ctx, need=not quiet)
            if fr is None:
                return None
            return ColRef(fr, self.column_of(fr, node.value, node))
        if k == 'call' and node.key in ('column', 'ascolumn', 'colstoredvalue') and node.args:
            args = [a for a in node.args if a.kind != 'empty']
            fr = None
            if len(args) >= 2 and not (args[0].kind == 'str' or args[0].kind == 'num'):
                fr = self.frame_of(args[0], ctx, need=False)
                if fr is not None:
                    args = args[1:]
            if fr is None:
                fr = ctx.frame if ctx.mode in ('vec', 'row') and ctx.frame is not None else self.current_frame(node)
            a = args[0]
            if node.key == 'colstoredvalue' and len(args) > 1:
                raise Unconvertible('Col Stored Value() with a row', node)
            if a.kind == 'str':
                return ColRef(fr, self.column_of(fr, a.value, node))
            if a.kind == 'name' and self.typeof(a.key) == 'unknown' and a.key not in self.names and fr.col(a.value):
                return ColRef(fr, fr.col(a.value)['name'])
            if a.kind == 'col':
                return ColRef(fr, self.column_of(fr, a.value, node))
            if a.kind == 'num' and float(a.value).is_integer():
                cols = [c['name'] for c in fr.cols.values()]
                i = int(a.value)
                if fr.known and 1 <= i <= len(cols):
                    return ColRef(fr, cols[i - 1])
                return ColRef(fr, None, f'{fr.var}.columns[{i - 1}]')
            e = self.x(a, SCALAR)
            if is_num_type(e.type):
                return ColRef(fr, None, f'{fr.var}.columns[{self.idx(a, SCALAR).code}]')
            return ColRef(fr, None, e.code)
        if k == 'name' and node.key not in self.vtypes and node.key not in self.names:
            fr = ctx.frame if ctx.mode in ('vec', 'row') and ctx.frame is not None else self.cur
            if fr is not None and fr.col(node.value):
                return ColRef(fr, fr.col(node.value)['name'])
        return None

    def col_value(self, ref, ctx, node):
        """A column where its value is wanted: the whole column in a formula
        or outside a row loop, the cell of the row in one."""
        fr = ref.frame
        if ctx.mode == 'row' and ctx.frame is fr:
            return E(f'{fr.var}.loc[row, {ref.code}]', P_ATOM, self.col_type(ref), ref)
        return E(ref.series(), P_ATOM, 'series', ref)

    def col_type(self, ref):
        c = ref.frame.col(ref.name) if ref.name else None
        if c and c.get('dtype') == 'character':
            return 'str'
        if c and c.get('dtype') == 'numeric':
            return 'num'
        return 'unknown'

    def is_char_col(self, e):
        ref = e.info if isinstance(e.info, ColRef) else None
        c = ref.frame.col(ref.name) if ref and ref.name else None
        return bool(c and c.get('dtype') == 'character')

    # ---- subscripts: 1-based JSL, 0-based Python ------------------------------------------
    def offset(self, node, ctx):
        """(e, k): the value of node is e + k (e None for a whole number)."""
        if node.kind == 'num' and float(node.value).is_integer():
            return None, int(node.value)
        if node.kind == 'name' and node.key in self.shifted:
            return E(self.py(node.key), P_ATOM, 'int'), 1
        if node.is_call('row') and not node.args and ctx.mode == 'row':
            return E('row', P_ATOM, 'int'), 1
        if node.kind == 'binop' and node.value in ('+', '-') and node.args[1].kind == 'num' and float(node.args[1].value).is_integer():
            e, k = self.offset(node.args[0], ctx)
            c = int(node.args[1].value)
            return e, k + (c if node.value == '+' else -c)
        e = self.x(node, ctx)
        if ctx.mode == 'vec' and e.type == 'series':
            raise NotVec()
        return e, 0

    def idx(self, node, ctx):
        """A 1-based subscript as a 0-based Python index."""
        e, k = self.offset(node, ctx)
        return self._plus(e, k - 1)

    def plus1(self, node, ctx):
        """node + 1, folded (the end of a range that includes node)."""
        e, k = self.offset(node, ctx)
        return self._plus(e, k + 1).code

    @staticmethod
    def _plus(e, k):
        if e is None:
            return E(str(k), P_UNARY if k < 0 else P_ATOM, 'int')
        if k == 0:
            return e
        return E(f'{par(e, P_ADD)} {"+" if k > 0 else "-"} {abs(k)}', P_ADD, 'int' if e.type == 'int' else e.type)

    def sub_part(self, node, ctx, allow_all=True):
        """One subscript of a matrix: ('all',), ('one', code), ('list', code), ('slice', code)."""
        if node.kind == 'num' and node.value == 0 and allow_all:
            return ('all', ':')
        if node.kind == 'binop' and node.value == '::':
            a = self.idx(node.args[0], ctx).code
            b = self.x(node.args[1], ctx)
            return ('slice', f'{a}:{b.code if b.prec >= P_ADD else "(" + b.code + ")"}')
        if node.kind == 'list' or node.kind == 'matrix':
            if node.kind == 'list' and all(a.kind == 'num' for a in node.args):
                return ('list', '[' + ', '.join(str(int(a.value) - 1) for a in node.args) + ']')
            if node.kind == 'matrix' and all(v is not None for r in node.value for v in r):
                flat = [v for r in node.value for v in r]
                return ('list', '[' + ', '.join(str(int(v) - 1) for v in flat) + ']')
            e = self.x(node, ctx)
            return ('list', f'np.ravel({e.code}).astype(int) - 1')
        e = self.x(node, ctx)
        if ctx.mode == 'vec' and e.type == 'series':
            raise NotVec()
        if e.type in ('matrix', 'rows', 'list'):
            return ('list', f'np.ravel({e.code}).astype(int) - 1')
        return ('one', self.idx(node, ctx).code)

    def x_subscript(self, node, ctx):
        base, subs = node.args[0], node.args[1:]
        if not subs or any(a.kind == 'empty' for a in subs):
            raise Unconvertible('a subscript without an index', node)
        # a column's cells: :x[i], dt:x[i], Column("x")[i]
        ref = self.colref(base, ctx, quiet=True) if base.kind in ('col', 'scope', 'call', 'name') else None
        if ref is not None and len(subs) == 1:
            return self.cell(ref, subs[0], ctx, node)
        if base.kind == 'name' and self.typeof(base.key) == 'frame' or base.is_call('currentdatatable', 'datatable'):
            return self.table_cell(self.frame_of(base, ctx), subs, ctx, node)
        if base.kind in ('num', 'missing', 'date'):
            raise Unconvertible('a subscript of a number', node)
        b = self.x(base, ctx)
        t = b.type
        if t == 'dict':
            if len(subs) != 1:
                raise Unconvertible('an associative array takes one subscript', node)
            return E(f'{par(b, P_ATOM)}[{self.x(subs[0], ctx).code}]', P_ATOM, 'unknown')
        if t == 'matrix':
            return self.matrix_sub(b, subs, ctx, node)
        if t == 'str':
            raise Unconvertible('a string with a subscript: use Substr()', node)
        if len(subs) == 2 and t in ('unknown', 'series'):
            return self.matrix_sub(b, subs, ctx, node)
        if len(subs) != 1:
            raise Unconvertible('a subscript of this kind', node)
        s = subs[0]
        part = self.sub_part(s, ctx, allow_all=False)
        if part[0] == 'one':
            return E(f'{par(b, P_ATOM)}[{part[1]}]', P_ATOM, 'unknown')
        if part[0] == 'slice':
            return E(f'{par(b, P_ATOM)}[{part[1]}]', P_ATOM, t)
        if t == 'rows':
            return E(f'{par(b, P_ATOM)}[{part[1]}]', P_ATOM, 'rows')
        return E(f'[{par(b, P_ATOM)}[k] for k in {part[1]}]', P_ATOM, 'list')

    def matrix_sub(self, b, subs, ctx, node):
        m = par(b, P_ATOM)
        if len(subs) == 1:
            part = self.sub_part(subs[0], ctx, allow_all=False)
            if part[0] == 'one':
                return E(f'{m}.flat[{part[1]}]', P_ATOM, 'num')
            return E(f'{m}.flat[{part[1]}]', P_ATOM, 'matrix')
        if len(subs) != 2:
            raise Unconvertible('a matrix takes one or two subscripts', node)
        r, c = (self.sub_part(s, ctx) for s in subs)
        if r[0] == 'one' and c[0] == 'one':
            return E(f'{m}[{r[1]}, {c[1]}]', P_ATOM, 'num')
        if r[0] == 'all' and c[0] == 'all':
            return E(m, P_ATOM, 'matrix')
        # keep two dimensions, as JSL does: one row or column is [i]
        rc = f'[{r[1]}]' if r[0] == 'one' else r[1]
        cc = f'[{c[1]}]' if c[0] == 'one' else c[1]
        if r[0] == 'list' and c[0] == 'list':
            return E(f'{m}[np.ix_({r[1]}, {c[1]})]', P_ATOM, 'matrix')
        return E(f'{m}[{rc}, {cc}]', P_ATOM, 'matrix')

    def cell(self, ref, sub, ctx, node):
        """A column's cell (or cells) by 1-based row number."""
        fr = ref.frame
        if ctx.mode == 'vec':
            # :x[Row() - k] in a formula is Lag
            if sub.kind == 'binop' and sub.value in ('-', '+') and sub.args[0].is_call('row') and sub.args[1].kind == 'num':
                k = int(sub.args[1].value) * (1 if sub.value == '-' else -1)
                return E(f'{ref.series()}.shift({k})', P_ATOM, 'series', ref)
            if sub.is_call('row') and not sub.args:
                return E(ref.series(), P_ATOM, 'series', ref)
            if any(n.is_call('row') for n in sub.walk()):
                raise NotVec()
            ctx = SCALAR
        part = self.sub_part(sub, ctx, allow_all=True)
        if part[0] == 'all':
            return E(ref.series(), P_ATOM, 'series', ref)
        if part[0] == 'one':
            return E(f'{fr.var}.loc[{part[1]}, {ref.code}]', P_ATOM, self.col_type(ref), ref)
        if part[0] == 'slice':
            return E(f'{fr.var}[{ref.code}].iloc[{part[1]}].to_numpy()', P_ATOM, 'matrix')
        return E(f'{fr.var}.loc[{part[1]}, {ref.code}].to_numpy()', P_ATOM, 'matrix')

    def table_cell(self, fr, subs, ctx, node):
        if len(subs) != 2:
            raise Unconvertible('a data table takes a row and a column subscript', node)
        r, c = subs
        rp = self.sub_part(r, ctx)
        if c.kind == 'str':
            cc = lit(self.column_of(fr, c.value, node))
            if rp[0] == 'one':
                return E(f'{fr.var}.loc[{rp[1]}, {cc}]', P_ATOM, 'unknown')
            if rp[0] == 'all':
                return E(f'{fr.var}[{cc}]', P_ATOM, 'series')
            return E(f'{fr.var}.loc[{rp[1]}, {cc}].to_numpy()', P_ATOM, 'matrix')
        if c.kind == 'num' and float(c.value).is_integer():
            j = int(c.value) - 1
            if rp[0] == 'one':
                return E(f'{fr.var}.iloc[{rp[1]}, {j}]', P_ATOM, 'unknown')
            return E(f'{fr.var}.iloc[{rp[1]}, {j}]', P_ATOM, 'series')
        if c.kind == 'list' and all(a.kind == 'str' for a in c.args):
            cols = '[' + ', '.join(lit(self.column_of(fr, a.value, node)) for a in c.args) + ']'
            rr = ':' if rp[0] == 'all' else (f'[{rp[1]}]' if rp[0] == 'one' else rp[1])
            return E(f'{fr.var}.loc[{rr}, {cols}].to_numpy()', P_ATOM, 'matrix')
        ce = self.x(c, SCALAR)
        if rp[0] == 'one':
            return E(f'{fr.var}.loc[{rp[1]}, {ce.code}]', P_ATOM, 'unknown')
        raise Unconvertible('this data table subscript', node)

    # ---- operators ------------------------------------------------------------------------
    def x_binop(self, node, ctx):
        op = node.value
        a, b = node.args
        if op in ('&', '|', ':&', ':|'):
            return self.logic(node, ctx)
        if op == '::':
            ea = self.x(a, ctx)
            return E(f'np.arange({ea.code}, {self.plus1(b, ctx)})', P_ATOM, 'rows')
        ea, eb = self.x(a, ctx), self.x(b, ctx)
        if op in ('+', '-'):
            return self.add(op, ea, eb, node, ctx)
        if op in ('*', '/'):
            return self.mul(op, ea, eb, node, ctx)
        if op == ':*':
            return E(f'{par(ea, P_MUL)} * {par(eb, P_MUL + 1)}', P_MUL, ea.type if ea.type == 'matrix' else eb.type)
        if op == ':/':
            return E(f'{par(ea, P_MUL)} / {par(eb, P_MUL + 1)}', P_MUL, 'matrix' if 'matrix' in (ea.type, eb.type) else 'num')
        if op == '^':
            t = 'series' if 'series' in (ea.type, eb.type) else ('matrix' if ea.type == 'matrix' else 'num')
            return E(f'{par(ea, P_POW + 1)} ** {par(eb, P_UNARY)}', P_POW, t)
        if op == '||':
            return self.concat(ea, eb, node, ctx)
        if op == '|/':
            if ctx.mode == 'vec':
                raise NotVec()
            return E(f'np.vstack([{ea.code}, {eb.code}])', P_ATOM, 'matrix')
        raise Unconvertible(f'the operator {op}', node)

    def add(self, op, ea, eb, node, ctx):
        ta, tb = ea.type, eb.type
        # dates: seconds added to a date are a Timedelta; a Timedelta in seconds where a number is wanted
        if ta == 'date' and is_num_type(tb):
            return E(f'{par(ea, P_ADD)} {op} pd.Timedelta(seconds={eb.code})', P_ADD, 'date')
        if ta == 'date' and tb == 'delta':
            return E(f'{par(ea, P_ADD)} {op} {par(eb, P_ADD + 1)}', P_ADD, 'date')
        if ta == 'date' and tb == 'date' and op == '-':
            return E(f'{par(ea, P_ADD)} - {par(eb, P_ADD + 1)}', P_ADD, 'delta')
        if ta == 'delta' and is_num_type(tb):
            ea = self.seconds(ea)
        elif tb == 'delta' and is_num_type(ta):
            eb = self.seconds(eb)
        t = self.arith_type(ea, eb)
        if op == '+' and (ta == 'list' or tb == 'list'):
            raise Unconvertible('+ with a list: JSL adds to each item', node)
        return E(f'{par(ea, P_ADD)} {op} {par(eb, P_ADD + 1)}', P_ADD, t)

    def seconds(self, e):
        return E(f'{par(e, P_ATOM)}.total_seconds()', P_ATOM, 'num') if e.type == 'delta' else e

    def arith_type(self, ea, eb):
        ts = (ea.type, eb.type)
        if 'series' in ts:
            return 'series'
        if 'matrix' in ts:
            return 'matrix'
        if 'rows' in ts:
            return 'rows'
        if ts == ('int', 'int'):
            return 'int'
        if all(is_num_type(t) for t in ts):
            return 'num'
        return 'unknown'

    def mul(self, op, ea, eb, node, ctx):
        ta, tb = ea.type, eb.type
        if ta == 'delta' and op == '/' and tb == 'delta':
            return E(f'{par(ea, P_MUL)} / {par(eb, P_MUL + 1)}', P_MUL, 'num')
        if ta == 'delta':
            ea = self.seconds(ea)
        if tb == 'delta':
            eb = self.seconds(eb)
        if ta == 'matrix' and tb == 'matrix':
            if op == '*':
                return E(f'{par(ea, P_MUL)} @ {par(eb, P_MUL + 1)}', P_MUL, 'matrix')
            return E(f'{par(ea, P_MUL)} @ np.linalg.inv({eb.code})', P_MUL, 'matrix')
        if ctx.mode == 'scalar' and ((ta == 'matrix' and tb == 'unknown') or (tb == 'matrix' and ta == 'unknown')):
            self.note(node.line, 'warn', f'{excerpt(self.p.source(node), 50)}: JSL\'s * is a matrix product when both sides are matrices; one side\'s kind is not known here, so * (element by element) is kept: write @ if both are matrices.', once=('matmul', node.line))
        if ta == 'unknown' and tb == 'unknown' and ctx.mode == 'scalar' and op == '*' and self.matrices_in_use():
            self.note(node.line, 'info', f'{excerpt(self.p.source(node), 50)}: the kinds of both sides are not known; if both are matrices, JSL\'s * is a matrix product (@ in Python). It is kept as * here.', once='matmul?')
        t = self.arith_type(ea, eb)
        if op == '/' and t in ('int',):
            t = 'num'
        return E(f'{par(ea, P_MUL)} {op} {par(eb, P_MUL + 1)}', P_MUL, t)

    def matrices_in_use(self):
        return any(v.type == 'matrix' for v in self.vtypes.values())

    def concat(self, ea, eb, node, ctx):
        ts = (ea.type, eb.type)
        if 'matrix' in ts:
            if ctx.mode == 'vec':
                raise NotVec()
            return E(f'np.hstack([{ea.code}, {eb.code}])', P_ATOM, 'matrix')
        if 'list' in ts:
            return E(f'{par(ea, P_ADD)} + {par(eb, P_ADD + 1)}', P_ADD, 'list')
        if ctx.mode == 'vec' and 'series' in ts:
            return E(f'{par(ea, P_ADD)} + {par(eb, P_ADD + 1)}', P_ADD, 'series')
        if any(is_num_type(t) for t in ts):
            self.note(node.line, 'warn', f'{excerpt(self.p.source(node), 50)}: || joins strings; a number there is an error in JSL (use Char()).', once=('concatnum', node.line))
        return E(f'{par(ea, P_ADD)} + {par(eb, P_ADD + 1)}', P_ADD, 'str')

    def logic(self, node, ctx):
        op = node.value.lstrip(':')
        # flatten a & b & c
        parts = []

        def flat(n, top=False):
            # the node itself is always split; a part in parentheses is kept whole
            if n.kind == 'binop' and n.value.lstrip(':') == op and (top or not n.extra.get('paren')):
                flat(n.args[0])
                flat(n.args[1])
            else:
                parts.append(n)
        flat(node, top=True)
        if ctx.mode == 'vec':
            es = [self.x(p, ctx.but(cond=True)) for p in parts]
            if not any(e.type == 'series' for e in es):
                word = ' and ' if op == '&' else ' or '
                prec = P_AND if op == '&' else P_OR
                return E(word.join(par(e, prec + 1) for e in es), prec, 'bool')
            prec = P_BAND if op == '&' else P_BOR
            return E(f' {op} '.join(par(e, prec + 1) for e in es), prec, 'series')
        es = [self.x(p, ctx.but(cond=True)) for p in parts]
        word, prec = (' and ', P_AND) if op == '&' else (' or ', P_OR)
        return E(word.join(par(e, prec + 1) for e in es), prec, 'bool')

    def x_cmp(self, node, ctx):
        ops, operands = node.value, node.args
        if any(o in ('>>', '>?') for o in ops):
            raise Unconvertible('a pattern assignment (>> or >?) of JSL\'s pattern matching', node)
        # x == . and x != . test for a missing value
        if len(ops) == 1 and ops[0] in ('==', '!=') and any(o.kind == 'missing' for o in operands):
            other = operands[0] if operands[1].kind == 'missing' else operands[1]
            e = self.x(other, ctx)
            miss = self.missing_test(e, ctx)
            if ops[0] == '==':
                return miss
            if miss.type == 'series' and not miss.code.endswith('.isna()'):
                return E(f'~{par(miss, P_UNARY + 1)}', P_UNARY, 'series')
            if miss.code.endswith('.isna()'):
                return E(miss.code[:-len('.isna()')] + '.notna()', P_ATOM, miss.type)
            if miss.code.startswith('pd.isna('):
                return E('pd.notna(' + miss.code[len('pd.isna('):], P_ATOM, miss.type)
            return E(f'not {par(miss, P_NOT)}', P_NOT, 'bool')
        es = [self.x(o, ctx) for o in operands]
        # a date against a number of seconds
        for i in range(len(es)):
            if es[i].type == 'delta' and any(is_num_type(e.type) for e in es):
                es[i] = self.seconds(es[i])
        vec = ctx.mode == 'vec' and any(e.type == 'series' for e in es)
        if vec or (len(ops) > 1 and any(e.type in ('series', 'matrix') for e in es)):
            pieces = [f'({par(es[i], P_CMP + 1)} {ops[i]} {par(es[i + 1], P_CMP + 1)})' for i in range(len(ops))]
            if len(pieces) == 1:
                return E(pieces[0][1:-1], P_CMP, 'series')
            return E(' & '.join(pieces), P_BAND, 'series')
        out = par(es[0], P_CMP + 1)
        for o, e in zip(ops, es[1:]):
            out += f' {o} {par(e, P_CMP + 1)}'
        t = 'matrix' if any(e.type == 'matrix' for e in es) else 'bool'
        return E(out, P_CMP, t)

    def missing_test(self, e, ctx):
        if e.type == 'series':
            if self.is_char_col(e):
                return E(f'({e.code}.isna() | ({e.code} == ""))', P_ATOM, 'series')
            return E(f'{par(e, P_ATOM)}.isna()', P_ATOM, 'series')
        if e.type == 'str':
            return E(f'{par(e, P_CMP + 1)} == ""', P_CMP, 'bool')
        return E(f'pd.isna({e.code})', P_ATOM, 'bool' if e.type != 'matrix' else 'matrix')

    def x_unary(self, node, ctx):
        op = node.value
        e = self.x(node.args[0], ctx.but(cond=op == '!') if op == '!' else ctx)
        if op == '+':
            return e
        if op == '-':
            if node.args[0].kind == 'num':
                return num_e(-node.args[0].value)
            return E(f'-{par(e, P_UNARY)}', P_UNARY, e.type if e.type != 'bool' else 'int')
        if e.type in ('series',) or (ctx.mode == 'vec' and e.type == 'series'):
            return E(f'~{par(e, P_UNARY + 1)}', P_UNARY, 'series')
        if e.type == 'matrix':
            return E(f'({e.code}) == 0', P_CMP, 'matrix')
        return E(f'not {par(e, P_NOT)}', P_NOT, 'bool')

    def x_postfix(self, node, ctx):
        if node.value == '`':
            e = self.x(node.args[0], ctx)
            if ctx.mode == 'vec':
                raise NotVec()
            return E(f'{par(e, P_ATOM)}.T', P_ATOM, 'matrix', (e.info[1], e.info[0]) if isinstance(e.info, tuple) and len(e.info) == 2 else None)
        raise Unconvertible(f'{node.value} inside an expression (write it as its own statement)', node)

    def x_assign(self, node, ctx):
        target, value = node.args
        if node.value == '=' and target.kind == 'name' and ctx.mode != 'vec':
            v = self.x(value, ctx)
            self.settype(target.key, v)
            return E(f'({self.py(target.key, target.value)} := {v.code})', P_ATOM, v.type, v.info)
        raise Unconvertible('an assignment inside an expression', node)

    def x_glue(self, node, ctx):
        raise Unconvertible('several expressions (joined by ";") where one value is wanted', node)

    def x_send(self, node, ctx):
        e = self.send(node, ctx, want=True)
        if e is None or e.code is None:
            raise Unconvertible('a message that gives no value, where a value is wanted', node)
        return e

    def x_call(self, node, ctx):
        key = node.key
        if node.extra.get('scope') is not None:
            raise Unconvertible(f'{self.p.source(node)}: a function of a namespace or class', node)
        h = FN.get(key)
        if h is not None:
            return h(self, node, ctx)
        v = self.vtypes.get(key)
        if v is not None and v.type == 'func':
            if ctx.mode == 'vec':
                raise NotVec()
            args = [self.x(a, ctx).code for a in node.args if a.kind != 'empty']
            return E(f'{self.py(key)}({", ".join(args)})', P_ATOM, 'unknown')
        if key in PLATFORMS:
            raise Unconvertible(f'{node.value}() inside an expression: a launch is converted when it stands alone, or is assigned to a name', node)
        if key in DISPLAY:
            raise Unconvertible(f'{node.value}(): windows, reports and display boxes have no Python counterpart here', node)
        if key in META and META[key]:
            raise Unconvertible(META[key], node)
        raise Unconvertible(f'{node.value}() has no Python translation here', node)


# numeric functions of one argument: (plain Python or numpy, the same for a column)
NUMERIC = {
    'sqrt': 'np.sqrt', 'exp': 'np.exp', 'ln': 'np.log', 'log10': 'np.log10', 'log1p': 'np.log1p', 'expm1': 'np.expm1',
    'floor': 'np.floor', 'ceiling': 'np.ceil', 'sine': 'np.sin', 'sin': 'np.sin', 'cosine': 'np.cos', 'cos': 'np.cos',
    'tangent': 'np.tan', 'tan': 'np.tan', 'arcsine': 'np.arcsin', 'arsin': 'np.arcsin', 'arccosine': 'np.arccos', 'arcos': 'np.arccos',
    'sinh': 'np.sinh', 'cosh': 'np.cosh', 'tanh': 'np.tanh', 'arcsinh': 'np.arcsinh', 'arccosh': 'np.arccosh', 'arctanh': 'np.arctanh',
    'lgamma': 'special.gammaln', 'digamma': 'special.digamma', 'logist': 'special.expit', 'logit': 'special.logit',
}

# probability functions: JSL name -> (scipy call, the order of JSL's arguments as scipy's)
DISTRIBUTIONS = {
    # continuous: x (or p) first
    'normaldistribution': ('stats.norm.cdf', 'x,loc=0,scale=1'), 'normaldensity': ('stats.norm.pdf', 'x,loc=0,scale=1'),
    'normalquantile': ('stats.norm.ppf', 'x,loc=0,scale=1'), 'probit': ('stats.norm.ppf', 'x,loc=0,scale=1'),
    'normallogdensity': ('stats.norm.logpdf', 'x,loc=0,scale=1'), 'normallogdistribution': ('stats.norm.logcdf', 'x,loc=0,scale=1'),
    'normallogcdistribution': ('stats.norm.logsf', 'x,loc=0,scale=1'),
    'tdistribution': ('stats.t.cdf', 'x,df'), 'studentstdistribution': ('stats.t.cdf', 'x,df'),
    'tdensity': ('stats.t.pdf', 'x,df'), 'studentstdensity': ('stats.t.pdf', 'x,df'),
    'tquantile': ('stats.t.ppf', 'x,df'), 'studentstquantile': ('stats.t.ppf', 'x,df'),
    'chisquaredistribution': ('stats.chi2.cdf', 'x,df'), 'chisquaredensity': ('stats.chi2.pdf', 'x,df'), 'chisquarequantile': ('stats.chi2.ppf', 'x,df'),
    'fdistribution': ('stats.f.cdf', 'x,dfn,dfd'), 'fdensity': ('stats.f.pdf', 'x,dfn,dfd'), 'fquantile': ('stats.f.ppf', 'x,dfn,dfd'),
    'expdistribution': ('stats.expon.cdf', 'x,scale=1'), 'exponentialdistribution': ('stats.expon.cdf', 'x,scale=1'),
    'expdensity': ('stats.expon.pdf', 'x,scale=1'), 'exponentialdensity': ('stats.expon.pdf', 'x,scale=1'), 'expquantile': ('stats.expon.ppf', 'x,scale=1'),
    'gammadistribution': ('stats.gamma.cdf', 'x,a=1,scale=1,loc=0'), 'igamma': ('stats.gamma.cdf', 'x,a=1,scale=1,loc=0'),
    'gammadensity': ('stats.gamma.pdf', 'x,a=1,scale=1,loc=0'), 'gammaquantile': ('stats.gamma.ppf', 'x,a=1,scale=1,loc=0'),
    'betadistribution': ('stats.beta.cdf', 'x,a,b,loc=0,scale=1'), 'betadensity': ('stats.beta.pdf', 'x,a,b,loc=0,scale=1'), 'betaquantile': ('stats.beta.ppf', 'x,a,b,loc=0,scale=1'),
    'weibulldistribution': ('stats.weibull_min.cdf', 'x,c,scale=1,loc=0'), 'weibulldensity': ('stats.weibull_min.pdf', 'x,c,scale=1,loc=0'),
    'weibullquantile': ('stats.weibull_min.ppf', 'x,c,scale=1,loc=0'),
    'cauchydistribution': ('stats.cauchy.cdf', 'x,loc=0,scale=1'), 'cauchydensity': ('stats.cauchy.pdf', 'x,loc=0,scale=1'), 'cauchyquantile': ('stats.cauchy.ppf', 'x,loc=0,scale=1'),
    'logisticdistribution': ('stats.logistic.cdf', 'x,loc,scale'), 'logisticdensity': ('stats.logistic.pdf', 'x,loc,scale'), 'logisticquantile': ('stats.logistic.ppf', 'x,loc,scale'),
    'sevdistribution': ('stats.gumbel_l.cdf', 'x,loc,scale'), 'sevdensity': ('stats.gumbel_l.pdf', 'x,loc,scale'), 'sevquantile': ('stats.gumbel_l.ppf', 'x,loc,scale'),
    'levdistribution': ('stats.gumbel_r.cdf', 'x,loc,scale'), 'levdensity': ('stats.gumbel_r.pdf', 'x,loc,scale'), 'levquantile': ('stats.gumbel_r.ppf', 'x,loc,scale'),
}
# lognormal: scipy's shape is sigma and its scale exp(mu)
LOGNORMAL = {'lognormaldistribution': 'cdf', 'lognormaldensity': 'pdf', 'lognormalquantile': 'ppf'}
# discrete: JSL's arguments as named
DISCRETE = {
    'poissondistribution': ('stats.poisson.cdf', ['mu', 'k'], '{k}, {mu}'), 'poissonprobability': ('stats.poisson.pmf', ['mu', 'k'], '{k}, {mu}'),
    'poissonquantile': ('stats.poisson.ppf', ['mu', 'q'], '{q}, {mu}'),
    'binomialdistribution': ('stats.binom.cdf', ['p', 'n', 'k'], '{k}, {n}, {p}'), 'binomialprobability': ('stats.binom.pmf', ['p', 'n', 'k'], '{k}, {n}, {p}'),
    'binomialquantile': ('stats.binom.ppf', ['p', 'n', 'q'], '{q}, {n}, {p}'),
    'negbinomialdistribution': ('stats.nbinom.cdf', ['p', 'n', 'k'], '{k}, {n}, {p}'), 'negbinomialprobability': ('stats.nbinom.pmf', ['p', 'n', 'k'], '{k}, {n}, {p}'),
    'hypergeometricdistribution': ('stats.hypergeom.cdf', ['N', 'K', 'n', 'x'], '{x}, {N}, {K}, {n}'),
    'hypergeometricprobability': ('stats.hypergeom.pmf', ['N', 'K', 'n', 'x'], '{x}, {N}, {K}, {n}'),
}

DATE_FORMATS = {
    'm/d/y': '%m/%d/%Y', 'mm/dd/yyyy': '%m/%d/%Y', 'm/d/y h:m': '%m/%d/%Y %I:%M %p', 'm/d/y h:m:s': '%m/%d/%Y %I:%M:%S %p',
    'd/m/y': '%d/%m/%Y', 'dd/mm/yyyy': '%d/%m/%Y', 'd/m/y h:m': '%d/%m/%Y %I:%M %p', 'd/m/y h:m:s': '%d/%m/%Y %I:%M:%S %p',
    'ddmonyyyy': '%d%b%Y', 'ddmonyyyy h:m': '%d%b%Y %I:%M %p', 'ddmonyyyy h:m:s': '%d%b%Y %I:%M:%S %p', 'ddmonyyyy:h:m:s': '%d%b%Y:%H:%M:%S',
    'monddyyyy': '%b%d%Y', 'monddyyyy h:m': '%b%d%Y %I:%M %p', 'yyyy-mm-dd': '%Y-%m-%d', 'yyyymmdd': '%Y%m%d', 'mmddyyyy': '%m%d%Y', 'ddmmyyyy': '%d%m%Y',
    'yyyy-mm-ddthh:mm:ss': '%Y-%m-%dT%H:%M:%S', 'yyyy-mm-ddthh:mm': '%Y-%m-%dT%H:%M', 'yyyy-mm-dd hh:mm:ss': '%Y-%m-%d %H:%M:%S', 'yyyy-mm-dd hh:mm': '%Y-%m-%d %H:%M',
    'h:m': '%I:%M %p', 'h:m:s': '%I:%M:%S %p', 'hr:m': '%H:%M', 'hr:m:s': '%H:%M:%S', 'mm/yyyy': '%m/%Y', 'mon yyyy': '%b %Y', 'yyyy': '%Y',
    'date long': '%A, %B %d, %Y', 'date abbrev': '%b %d, %Y', 'locale date': '%x', 'locale date time h:m': '%x %H:%M', 'locale date time h:m:s': '%x %X',
}


class _Lib(_Expr):
    def a(self, node, ctx, lo, hi=None):
        return [self.x(n, ctx) for n in self.nargs(node, lo, hi)]

    def only_scalar(self, node, ctx):
        if ctx.mode == 'vec':
            raise NotVec()

    # ---- arithmetic and logic as functions --------------------------------------------------
    def _fold(self, op, node, ctx, lo=1):
        args = self.nargs(node, lo, -1)
        out = args[0]
        for b in args[1:]:
            out = jsl.Node('binop', op, [out, b], line=node.line, start=node.start, end=node.end)
        return self.x(out, ctx)

    @fn('Add')
    def f_add(self, node, ctx):
        return self._fold('+', node, ctx) if node.args else E('0', P_ATOM, 'int')

    @fn('Subtract')
    def f_subtract(self, node, ctx):
        return self._fold('-', node, ctx, 2)

    @fn('Multiply')
    def f_multiply(self, node, ctx):
        return self._fold('*', node, ctx) if node.args else E('1', P_ATOM, 'int')

    @fn('Divide')
    def f_divide(self, node, ctx):
        args = self.nargs(node, 1, 2)
        if len(args) == 1:
            e = self.x(args[0], ctx)
            return E(f'1 / {par(e, P_MUL + 1)}', P_MUL, 'num')
        return self._fold('/', node, ctx, 2)

    @fn('Minus')
    def f_minus(self, node, ctx):
        (a,) = self.nargs(node, 1)
        return self.x(jsl.Node('unary', '-', [a], line=node.line, start=node.start, end=node.end), ctx)

    @fn('Power')
    def f_power(self, node, ctx):
        args = self.nargs(node, 1, 2)
        b = args[1] if len(args) == 2 else jsl.Node('num', 2, line=node.line)
        return self.x(jsl.Node('binop', '^', [args[0], b], line=node.line, start=node.start, end=node.end), ctx)

    @fn('Concat')
    def f_concat(self, node, ctx):
        return self._fold('||', node, ctx)

    @fn('E Mult')
    def f_emult(self, node, ctx):
        return self._fold(':*', node, ctx, 2)

    @fn('E Div')
    def f_ediv(self, node, ctx):
        return self._fold(':/', node, ctx, 2)

    @fn('Matrix Mult')
    def f_matmult(self, node, ctx):
        self.only_scalar(node, ctx)
        a, b = self.a(node, ctx, 2)
        return E(f'{par(a, P_MUL)} @ {par(b, P_MUL + 1)}', P_MUL, 'matrix')

    @fn('And', 'AndMZ')
    def f_and(self, node, ctx):
        return self._fold('&', node, ctx, 2)

    @fn('Or', 'OrMZ')
    def f_or(self, node, ctx):
        return self._fold('|', node, ctx, 2)

    @fn('Not')
    def f_not(self, node, ctx):
        (a,) = self.nargs(node, 1)
        return self.x(jsl.Node('unary', '!', [a], line=node.line, start=node.start, end=node.end), ctx)

    def _cmp_fn(self, op, node, ctx):
        args = self.nargs(node, 2, -1)
        return self.x(jsl.Node('cmp', [op] * (len(args) - 1), args, line=node.line, start=node.start, end=node.end), ctx)

    @fn('Equal')
    def f_equal(self, node, ctx):
        return self._cmp_fn('==', node, ctx)

    @fn('Not Equal')
    def f_notequal(self, node, ctx):
        return self._cmp_fn('!=', node, ctx)

    @fn('Less')
    def f_less(self, node, ctx):
        return self._cmp_fn('<', node, ctx)

    @fn('Less or Equal')
    def f_le(self, node, ctx):
        return self._cmp_fn('<=', node, ctx)

    @fn('Greater')
    def f_greater(self, node, ctx):
        return self._cmp_fn('>', node, ctx)

    @fn('Greater or Equal')
    def f_ge(self, node, ctx):
        return self._cmp_fn('>=', node, ctx)

    @fn('Less Less Equal')
    def f_lle(self, node, ctx):
        a = self.nargs(node, 3)
        return self.x(jsl.Node('cmp', ['<', '<='], a, line=node.line), ctx)

    @fn('Less Equal Less')
    def f_lel(self, node, ctx):
        a = self.nargs(node, 3)
        return self.x(jsl.Node('cmp', ['<=', '<'], a, line=node.line), ctx)

    # ---- numbers ----------------------------------------------------------------------------
    def numeric1(self, node, ctx, func):
        (e,) = self.a(node, ctx, 1)
        t = 'series' if e.type == 'series' else ('matrix' if e.type == 'matrix' else 'num')
        return E(f'{func}({e.code})', P_ATOM, t)

    @fn('Abs')
    def f_abs(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        if e.type in ('series', 'matrix'):
            return E(f'np.abs({e.code})', P_ATOM, e.type)
        return E(f'abs({e.code})', P_ATOM, e.type if is_num_type(e.type) else 'num')

    @fn('Log')
    def f_log(self, node, ctx):
        args = self.nargs(node, 1, 2)
        e = self.x(args[0], ctx)
        t = e.type if e.type in ('series', 'matrix') else 'num'
        if len(args) == 1:
            return E(f'np.log({e.code})', P_ATOM, t)
        b = args[1]
        if b.kind == 'num' and b.value in (10, 2):
            return E(f'np.log{int(b.value)}({e.code})', P_ATOM, t)
        be = self.x(b, ctx)
        return E(f'np.log({e.code}) / np.log({be.code})', P_MUL, t)

    @fn('Round')
    def f_round(self, node, ctx):
        args = self.a(node, ctx, 1, 2)
        self.helper('jsl_round')
        t = args[0].type if args[0].type in ('series', 'matrix') else 'num'
        return E(f'jsl_round({", ".join(a.code for a in args)})', P_ATOM, t)

    @fn('Modulo', 'Mod')
    def f_mod(self, node, ctx):
        a, b = self.a(node, ctx, 2)
        return E(f'np.fmod({a.code}, {b.code})', P_ATOM, self.arith_type(a, b) if self.arith_type(a, b) != 'int' else 'num')

    @fn('Root')
    def f_root(self, node, ctx):
        args = self.nargs(node, 1, 2)
        e = self.x(args[0], ctx)
        if len(args) == 1 or (args[1].kind == 'num' and args[1].value == 2):
            return E(f'np.sqrt({e.code})', P_ATOM, e.type if e.type in ('series', 'matrix') else 'num')
        r = self.x(args[1], ctx)
        return E(f'{par(e, P_POW + 1)} ** (1 / {par(r, P_MUL + 1)})', P_POW, e.type if e.type in ('series', 'matrix') else 'num')

    @fn('ArcTangent', 'ArcTan', 'ATan')
    def f_atan(self, node, ctx):
        args = self.a(node, ctx, 1, 2)
        t = 'series' if any(a.type == 'series' for a in args) else 'num'
        if len(args) == 2:
            return E(f'np.arctan2({args[0].code}, {args[1].code})', P_ATOM, t)
        return E(f'np.arctan({args[0].code})', P_ATOM, t)

    @fn('Pi')
    def f_pi(self, node, ctx):
        return E('np.pi', P_ATOM, 'num')

    @fn('e')
    def f_e(self, node, ctx):
        return E('np.e', P_ATOM, 'num')

    @fn('Gamma')
    def f_gamma(self, node, ctx):
        args = self.a(node, ctx, 1, 2)
        if len(args) == 2:
            return E(f'special.gamma({args[0].code}) * special.gammainc({args[0].code}, {args[1].code})', P_MUL, 'num')
        return E(f'special.gamma({args[0].code})', P_ATOM, 'series' if args[0].type == 'series' else 'num')

    @fn('Beta')
    def f_beta(self, node, ctx):
        a, b = self.a(node, ctx, 2)
        return E(f'special.beta({a.code}, {b.code})', P_ATOM, 'num')

    @fn('Trigamma')
    def f_trigamma(self, node, ctx):
        (a,) = self.a(node, ctx, 1)
        return E(f'special.polygamma(1, {a.code})', P_ATOM, 'num')

    @fn('Factorial')
    def f_factorial(self, node, ctx):
        (a,) = self.a(node, ctx, 1)
        if a.type == 'series':
            return E(f'special.factorial({a.code})', P_ATOM, 'series')
        return E(f'math.factorial(int({a.code}))', P_ATOM, 'int')

    @fn('N Choose K', 'NChooseK')
    def f_nchoosek(self, node, ctx):
        n, k = self.a(node, ctx, 2)
        if 'series' in (n.type, k.type):
            return E(f'special.comb({n.code}, {k.code})', P_ATOM, 'series')
        return E(f'math.comb(int({n.code}), int({k.code}))', P_ATOM, 'int')

    @fn('Logist Percent')
    def f_logistpct(self, node, ctx):
        (a,) = self.a(node, ctx, 1)
        return E(f'100 * special.expit({a.code})', P_MUL, 'num')

    @fn('Logit Percent')
    def f_logitpct(self, node, ctx):
        (a,) = self.a(node, ctx, 1)
        return E(f'special.logit({par(a, P_MUL)} / 100)', P_ATOM, 'num')

    @fn('Arrhenius')
    def f_arrhenius(self, node, ctx):
        (a,) = self.a(node, ctx, 1)
        return E(f'11604.5181215503 / ({a.code} + 273.15)', P_MUL, 'num')

    @fn('Arrhenius Inv')
    def f_arrheniusinv(self, node, ctx):
        (a,) = self.a(node, ctx, 1)
        return E(f'11604.5181215503 / {par(a, P_MUL + 1)} - 273.15', P_ADD, 'num')

    # ---- statistics of the arguments (row by row in a formula) -----------------------------
    STATS = {
        'max': ('np.nanmax', 'max'), 'min': ('np.nanmin', 'min'), 'mean': ('np.nanmean', 'mean'), 'median': ('np.nanmedian', 'median'),
        'sum': ('np.nansum', 'sum'), 'std': ('np.nanstd', 'std'), 'number': (None, 'count'), 'nmissing': (None, 'nmissing'),
    }

    def row_stat(self, node, ctx, how):
        args = self.nargs(node, 1, -1)
        es = [self.x(a, ctx) for a in args]
        npf, pdm = self.STATS[how]
        if ctx.mode == 'vec' and any(e.type == 'series' for e in es):
            if len(es) == 1:
                e = es[0]
                return {'count': E(f'{par(e, P_ATOM)}.notna().astype(int)', P_ATOM, 'series'),
                        'nmissing': E(f'{par(e, P_ATOM)}.isna().astype(int)', P_ATOM, 'series'),
                        'std': E('np.nan', P_ATOM, 'num')}.get(pdm, e)
            fr = ctx.frame
            if all(isinstance(e.info, ColRef) and e.info.frame is fr and e.code == e.info.series() for e in es):
                sel = f'{fr.var}[[{", ".join(e.info.code for e in es)}]]'
            elif all(e.type == 'series' for e in es):
                sel = f'pd.concat([{", ".join(e.code for e in es)}], axis=1)'
            elif pdm in ('max', 'min'):
                f = 'np.fmax' if pdm == 'max' else 'np.fmin'
                out = es[0].code
                for e in es[1:]:
                    out = f'{f}({out}, {e.code})'
                return E(out, P_ATOM, 'series')
            else:
                raise NotVec()
            tail = {'sum': '.sum(axis=1, min_count=1)', 'count': '.notna().sum(axis=1)', 'nmissing': '.isna().sum(axis=1)'}.get(pdm, f'.{pdm}(axis=1)')
            return E(sel + tail, P_ATOM, 'series')
        if len(es) == 1:
            e = es[0]
            if e.type == 'series':
                if pdm == 'count':
                    return E(f'{par(e, P_ATOM)}.count()', P_ATOM, 'int')
                if pdm == 'nmissing':
                    return E(f'{par(e, P_ATOM)}.isna().sum()', P_ATOM, 'int')
                return E(f'{par(e, P_ATOM)}.{pdm}()', P_ATOM, 'num')
            if e.type in ('matrix', 'list', 'rows', 'unknown'):
                if pdm == 'count':
                    return E(f'int(np.count_nonzero(pd.notna({e.code})))', P_ATOM, 'int')
                if pdm == 'nmissing':
                    return E(f'int(np.count_nonzero(pd.isna({e.code})))', P_ATOM, 'int')
                extra = ', ddof=1' if pdm == 'std' else ''
                return E(f'{npf}({e.code}{extra})', P_ATOM, 'num')
            if pdm in ('count', 'nmissing'):
                return E(f'int({"pd.notna" if pdm == "count" else "pd.isna"}({e.code}))', P_ATOM, 'int')
            return e
        if pdm in ('max', 'min') and all(e.type == 'str' for e in es):
            return E(f'{pdm}({", ".join(e.code for e in es)})', P_ATOM, 'str')
        lst = '[' + ', '.join(e.code for e in es) + ']'
        if pdm == 'count':
            return E(f'int(np.count_nonzero(pd.notna({lst})))', P_ATOM, 'int')
        if pdm == 'nmissing':
            return E(f'int(np.count_nonzero(pd.isna({lst})))', P_ATOM, 'int')
        extra = ', ddof=1' if pdm == 'std' else ''
        return E(f'{npf}({lst}{extra})', P_ATOM, 'num')

    @fn('Maximum', 'Max')
    def f_max(self, node, ctx):
        return self.row_stat(node, ctx, 'max')

    @fn('Minimum', 'Min')
    def f_min(self, node, ctx):
        return self.row_stat(node, ctx, 'min')

    @fn('Mean')
    def f_mean(self, node, ctx):
        return self.row_stat(node, ctx, 'mean')

    @fn('Median')
    def f_median(self, node, ctx):
        return self.row_stat(node, ctx, 'median')

    @fn('Sum')
    def f_sum(self, node, ctx):
        return self.row_stat(node, ctx, 'sum')

    @fn('Std Dev')
    def f_std(self, node, ctx):
        return self.row_stat(node, ctx, 'std')

    @fn('Number')
    def f_number(self, node, ctx):
        return self.row_stat(node, ctx, 'number')

    @fn('N Missing')
    def f_nmissing(self, node, ctx):
        return self.row_stat(node, ctx, 'nmissing')

    @fn('Quantile')
    def f_quantile(self, node, ctx):
        args = self.nargs(node, 2, -1)
        p = self.x(args[0], ctx)
        es = [self.x(a, ctx) for a in args[1:]]
        if ctx.mode == 'vec' and any(e.type == 'series' for e in es):
            raise NotVec()
        data = es[0].code if len(es) == 1 and es[0].type in ('matrix', 'list', 'series', 'rows', 'unknown') else '[' + ', '.join(e.code for e in es) + ']'
        return E(f'np.nanquantile({data}, {p.code}, method="weibull")', P_ATOM, 'num')

    @fn('Range')
    def f_range(self, node, ctx):
        self.only_scalar(node, ctx)
        es = self.a(node, ctx, 1, -1)
        data = es[0].code if len(es) == 1 else '[' + ', '.join(e.code for e in es) + ']'
        return E(f'np.array([[np.nanmin({data}), np.nanmax({data})]])', P_ATOM, 'matrix', (1, 2))

    @fn('SSQ')
    def f_ssq(self, node, ctx):
        es = self.a(node, ctx, 1, -1)
        data = es[0].code if len(es) == 1 else '[' + ', '.join(e.code for e in es) + ']'
        return E(f'np.nansum(np.square({data}))', P_ATOM, 'num')

    def _sum_over(self, node, ctx, agg):
        self.only_scalar(node, ctx)
        a = self.nargs(node, 3)
        init, limit, body = a
        if init.kind != 'assign' or init.value != '=' or init.args[0].kind != 'name':
            raise Unconvertible(f'{node.value}() needs i = start as its first argument', node)
        var = init.args[0]
        v = self.py(var.key, var.value)
        self.settype(var.key, E(v, P_ATOM, 'int'))
        start = self.x(init.args[1], ctx)
        end = self.plus1(limit, ctx)
        b = self.x(body, ctx)
        return E(f'{agg}({b.code} for {v} in range({start.code}, {end}))', P_ATOM, 'num')

    @fn('Summation')
    def f_summation(self, node, ctx):
        return self._sum_over(node, ctx, 'sum')

    @fn('Product')
    def f_product(self, node, ctx):
        return self._sum_over(node, ctx, 'math.prod')

    # ---- column statistics: a groupby transform with By columns --------------------------
    def col_stat(self, node, ctx, how):
        args = self.nargs(node, 1, -1)
        lead = 2 if how in ('quantile', 'movingavg') else 1
        if how == 'movingavg':
            lead = 1
            while lead < len(args) and args[lead].kind == 'num':
                lead += 1
        fr = ctx.frame if ctx.mode in ('vec', 'row') and ctx.frame is not None else self.current_frame(node)
        vctx = Ctx('vec', fr)
        e = self.x(args[0], vctx)
        by = []
        for b in args[lead:]:
            if b.kind == 'call' and b.key == 'tie':
                continue
            ref = self.colref(b, vctx)
            if ref is None or ref.name is None:
                raise Unconvertible(f'{node.value}(): a By argument that is not a column', node)
            by.append(ref.name)
        tie = next((b for b in args[lead:] if b.kind == 'call' and b.key == 'tie'), None)
        plain = isinstance(e.info, ColRef) and e.code == e.info.series()
        base = par(e, P_ATOM)
        grp = None
        if by:
            keys = lit(by[0]) if len(by) == 1 else '[' + ', '.join(lit(b) for b in by) + ']'
            grp = f'{fr.var}.groupby({keys}, dropna=False)[{e.info.code}]' if plain else f'{base}.groupby([{", ".join(fr.var + "[" + lit(b) + "]" for b in by)}], dropna=False)'
        simple = {'mean': 'mean', 'sum': 'sum', 'std': 'std', 'count': 'count', 'max': 'max', 'min': 'min', 'median': 'median'}
        if how in simple:
            if grp:
                out = E(f'{grp}.transform({lit(simple[how])})', P_ATOM, 'series')
            else:
                out = E(f'{base}.{simple[how]}()', P_ATOM, 'int' if how == 'count' else 'num')
        elif how == 'nmissing':
            out = E(f'{grp}.transform(lambda s: s.isna().sum())', P_ATOM, 'series') if grp else E(f'{base}.isna().sum()', P_ATOM, 'int')
        elif how == 'quantile':
            p = self.x(args[1], SCALAR).code
            out = E(f'{grp}.transform(lambda s: np.nanquantile(s, {p}, method="weibull"))', P_ATOM, 'series') if grp else E(f'np.nanquantile({e.code}, {p}, method="weibull")', P_ATOM, 'num')
        elif how == 'rank':
            method = 'first'
            if tie is not None and tie.args and tie.args[0].kind == 'str':
                method = {'average': 'average', 'minimum': 'min', 'row': 'first', 'arbitrary': 'first'}.get(tie.args[0].value.lower(), 'first')
            if method == 'first':
                self.note(node.line, 'info', 'Col Rank: JMP breaks ties arbitrarily; here tied values are ranked in row order (rank(method="first")).', once='colrank')
            out = E(f'{grp}.rank(method={lit(method)})' if grp else f'{base}.rank(method={lit(method)})', P_ATOM, 'series')
        elif how == 'cumsum':
            out = E(f'{grp}.cumsum()' if grp else f'{base}.cumsum()', P_ATOM, 'series')
        elif how == 'standardize':
            out = E(f'{grp}.transform(lambda s: (s - s.mean()) / s.std())', P_ATOM, 'series') if grp else E(f'({e.code} - {base}.mean()) / {base}.std()', P_MUL, 'series')
        elif how == 'mode':
            out = E(f'{grp}.transform(lambda s: s.mode().iloc[0])', P_ATOM, 'series') if grp else E(f'{base}.mode().iloc[0]', P_ATOM, 'num')
        elif how == 'movingavg':
            nums = [a.value for a in args[1:lead]]
            weighting = nums[0] if nums else 1
            before = int(nums[1]) if len(nums) > 1 else -1
            after = int(nums[2]) if len(nums) > 2 else 0
            if weighting != 1 or after != 0:
                raise Unconvertible('Col Moving Average() with weights, or with rows after the current one', node)
            if grp:
                raise Unconvertible('Col Moving Average() with By columns', node)
            roll = f'.rolling({before + 1}, min_periods=1).mean()' if before >= 0 else '.expanding().mean()'
            out = E(f'{base}{roll}', P_ATOM, 'series')
        else:
            raise Unconvertible(f'{node.value}()', node)
        if ctx.mode == 'row' and out.type == 'series':
            return E(f'{par(out, P_ATOM)}[row]', P_ATOM, 'num')
        return out

    @fn('Col Mean')
    def f_colmean(self, node, ctx):
        return self.col_stat(node, ctx, 'mean')

    @fn('Col Sum')
    def f_colsum(self, node, ctx):
        return self.col_stat(node, ctx, 'sum')

    @fn('Col Std Dev', 'Col StdDev')
    def f_colstd(self, node, ctx):
        return self.col_stat(node, ctx, 'std')

    @fn('Col Number', 'Col N')
    def f_coln(self, node, ctx):
        return self.col_stat(node, ctx, 'count')

    @fn('Col N Missing', 'Col NMissing')
    def f_colnmissing(self, node, ctx):
        return self.col_stat(node, ctx, 'nmissing')

    @fn('Col Maximum', 'Col Max')
    def f_colmax(self, node, ctx):
        return self.col_stat(node, ctx, 'max')

    @fn('Col Minimum', 'Col Min')
    def f_colmin(self, node, ctx):
        return self.col_stat(node, ctx, 'min')

    @fn('Col Median')
    def f_colmedian(self, node, ctx):
        return self.col_stat(node, ctx, 'median')

    @fn('Col Quantile')
    def f_colquantile(self, node, ctx):
        return self.col_stat(node, ctx, 'quantile')

    @fn('Col Rank')
    def f_colrank(self, node, ctx):
        return self.col_stat(node, ctx, 'rank')

    @fn('Col Cumulative Sum', 'Cumulative Sum')
    def f_colcumsum(self, node, ctx):
        return self.col_stat(node, ctx, 'cumsum')

    @fn('Col Standardize')
    def f_colstandardize(self, node, ctx):
        return self.col_stat(node, ctx, 'standardize')

    @fn('Col Mode')
    def f_colmode(self, node, ctx):
        return self.col_stat(node, ctx, 'mode')

    @fn('Col Moving Average', 'Moving Average')
    def f_colmovingavg(self, node, ctx):
        return self.col_stat(node, ctx, 'movingavg')

    # ---- rows ---------------------------------------------------------------------------------
    def the_frame(self, ctx, node):
        return ctx.frame if ctx.mode in ('vec', 'row') and ctx.frame is not None else self.current_frame(node)

    @fn('Lag')
    def f_lag(self, node, ctx):
        args = self.nargs(node, 1, 2)
        n = int(args[1].value) if len(args) == 2 and args[1].kind == 'num' else (None if len(args) == 2 else 1)
        if n is None:
            raise Unconvertible('Lag() with a lag that is not a number', node)
        if ctx.mode == 'row':
            ref = self.colref(args[0], ctx)
            if ref is None:
                raise Unconvertible('Lag() of an expression in a row loop', node)
            return E(f'({ref.frame.var}.loc[row - {n}, {ref.code}] if row >= {n} else np.nan)', P_ATOM, 'unknown')
        fr = self.the_frame(ctx, node)
        e = self.x(args[0], Ctx('vec', fr))
        return E(f'{par(e, P_ATOM)}.shift({n})', P_ATOM, 'series')

    @fn('Dif')
    def f_dif(self, node, ctx):
        args = self.nargs(node, 1, 2)
        n = int(args[1].value) if len(args) == 2 and args[1].kind == 'num' else (None if len(args) == 2 else 1)
        if n is None:
            raise Unconvertible('Dif() with a lag that is not a number', node)
        if ctx.mode == 'row':
            ref = self.colref(args[0], ctx)
            if ref is None:
                raise Unconvertible('Dif() of an expression in a row loop', node)
            v = f'{ref.frame.var}.loc[row, {ref.code}]'
            return E(f'({v} - {ref.frame.var}.loc[row - {n}, {ref.code}] if row >= {n} else np.nan)', P_ATOM, 'unknown')
        fr = self.the_frame(ctx, node)
        e = self.x(args[0], Ctx('vec', fr))
        return E(f'{par(e, P_ATOM)}.diff({n})', P_ATOM, 'series')

    @fn('Row')
    def f_row(self, node, ctx):
        if node.args:
            raise Unconvertible('Row() with an argument', node)
        if ctx.mode == 'row':
            return E('row + 1', P_ADD, 'int')
        if ctx.mode == 'vec':
            return E(f'np.arange(1, len({ctx.frame.var}) + 1)', P_ATOM, 'series')
        raise Unconvertible('Row() outside a formula or For Each Row: the current row has no Python counterpart', node)

    @fn('N Rows', 'N Row')
    def f_nrows(self, node, ctx):
        if not node.args or node.args[0].kind == 'empty':
            return E(f'len({self.the_frame(ctx, node).var})', P_ATOM, 'int')
        a = node.args[0]
        fr = self.frame_of(a, ctx, need=False) if a.kind in ('name', 'call') else None
        if fr is not None:
            return E(f'len({fr.var})', P_ATOM, 'int')
        e = self.x(a, SCALAR if ctx.mode == 'vec' else ctx)
        if e.type == 'matrix':
            return E(f'{par(e, P_ATOM)}.shape[0]', P_ATOM, 'int')
        if e.type in ('list', 'rows', 'series', 'dict'):
            return E(f'len({e.code})', P_ATOM, 'int')
        return E(f'np.shape({e.code})[0]', P_ATOM, 'int')

    @fn('N Cols', 'N Col')
    def f_ncols(self, node, ctx):
        if not node.args:
            return E(f'{self.the_frame(ctx, node).var}.shape[1]', P_ATOM, 'int')
        a = node.args[0]
        fr = self.frame_of(a, ctx, need=False) if a.kind in ('name', 'call') else None
        if fr is not None:
            return E(f'{fr.var}.shape[1]', P_ATOM, 'int')
        e = self.x(a, ctx)
        if e.type == 'matrix':
            return E(f'{par(e, P_ATOM)}.shape[1]', P_ATOM, 'int')
        return E(f'np.shape({e.code})[1]', P_ATOM, 'int')

    @fn('N Items')
    def f_nitems(self, node, ctx):
        (e,) = self.a(node, SCALAR if ctx.mode == 'vec' else ctx, 1)
        if e.type == 'matrix':
            return E(f'{par(e, P_ATOM)}.size', P_ATOM, 'int')
        return E(f'len({e.code})', P_ATOM, 'int')

    @fn('Sequence')
    def f_sequence(self, node, ctx):
        args = self.a(node, SCALAR, 2, 4)
        fr = self.the_frame(ctx, node)
        self.helper('jsl_sequence')
        code = f'jsl_sequence(len({fr.var}), {", ".join(a.code for a in args)})'
        if ctx.mode == 'row':
            return E(f'{code}[row]', P_ATOM, 'num')
        if ctx.mode != 'vec':
            raise Unconvertible('Sequence() outside a column formula', node)
        return E(code, P_ATOM, 'series')

    @fn('Count')
    def f_count(self, node, ctx):
        args = self.a(node, SCALAR, 4)
        fr = self.the_frame(ctx, node)
        self.helper('jsl_count')
        code = f'jsl_count(len({fr.var}), {", ".join(a.code for a in args)})'
        if ctx.mode == 'row':
            return E(f'{code}[row]', P_ATOM, 'num')
        if ctx.mode != 'vec':
            raise Unconvertible('Count() outside a column formula', node)
        return E(code, P_ATOM, 'series')

    # ---- conditions --------------------------------------------------------------------------
    def branches(self, node):
        """If's arguments as (condition, result) pairs and the else result."""
        args = list(node.args)
        pairs = [(args[i], args[i + 1]) for i in range(0, len(args) - 1, 2)]
        other = args[-1] if len(args) % 2 == 1 else None
        if other is not None and other.kind == 'empty':
            other = None
        return pairs, other

    def missing_like(self, es):
        return '""' if es and all(e.type == 'str' for e in es) else 'np.nan'

    @fn('If', 'IfMZ')
    def f_if(self, node, ctx):
        pairs, other = self.branches(node)
        if not pairs:
            raise Unconvertible('If() without a condition', node)
        if ctx.mode == 'vec':
            if node.key == 'if':
                self.note(node.line, 'info', 'In a formula, JMP gives a missing value where the condition is missing (a missing value compared); np.where and np.select take the else branch there.', once='vecif')
            conds = [self.x(c, ctx.but(cond=True)) for c, _ in pairs]
            vals = [self.x(v, ctx) for _, v in pairs]
            els = self.x(other, ctx) if other is not None else None
            default = els.code if els else self.missing_like(vals)
            if any(e.type == 'series' for e in conds + vals + ([els] if els else [])):
                if len(pairs) == 1:
                    return E(f'np.where({conds[0].code}, {vals[0].code}, {default})', P_ATOM, 'series')
                return E(f'np.select([{", ".join(c.code for c in conds)}], [{", ".join(v.code for v in vals)}], default={default})', P_ATOM, 'series')
            # a condition on no column: the plain conditional below
        for c, v in pairs:
            if v.kind == 'glue':
                raise Unconvertible('If() with several expressions in a branch, where one value is wanted', node)
        conds = [self.x(c, ctx.but(cond=True)) for c, _ in pairs]
        vals = [self.x(v, ctx) for _, v in pairs]
        els = self.x(other, ctx) if other is not None else E(self.missing_like(vals), P_ATOM, 'num')
        out = par(els, P_IF)
        for c, v in reversed(list(zip(conds, vals))):
            out = f'{par(v, P_IF + 1)} if {par(c, P_IF + 1)} else {out}'
        types = {v.type for v in vals + [els]}
        return E(out, P_IF, types.pop() if len(types) == 1 else 'unknown')

    @fn('Match', 'MatchMZ')
    def f_match(self, node, ctx):
        args = self.nargs(node, 3, -1)
        subject = self.x(args[0], ctx)
        rest = args[1:]
        pairs = [(rest[i], rest[i + 1]) for i in range(0, len(rest) - 1, 2)]
        other = rest[-1] if len(rest) % 2 == 1 else None
        keys = [self.x(k, SCALAR if ctx.mode == 'vec' else ctx) for k, _ in pairs]
        vals = [self.x(v, ctx) for _, v in pairs]
        els = self.x(other, ctx) if other is not None else E(self.missing_like(vals), P_ATOM, 'num')
        if ctx.mode == 'vec' and subject.type == 'series':
            conds = [f'{par(subject, P_CMP + 1)} == {par(k, P_CMP + 1)}' for k in keys]
            return E(f'np.select([{", ".join(conds)}], [{", ".join(v.code for v in vals)}], default={els.code})', P_ATOM, 'series')
        if all(k.prec == P_ATOM and pairs[i][0].kind in ('num', 'str') for i, k in enumerate(keys)) and all(pairs[i][1].kind in ('num', 'str', 'missing') for i in range(len(pairs))):
            table = '{' + ', '.join(f'{k.code}: {v.code}' for k, v in zip(keys, vals)) + '}'
            types = {v.type for v in vals + [els]}
            return E(f'{table}.get({subject.code}, {els.code})', P_ATOM, types.pop() if len(types) == 1 else 'unknown')
        out = par(els, P_IF)
        for k, v in reversed(list(zip(keys, vals))):
            out = f'{par(v, P_IF + 1)} if {par(subject, P_CMP + 1)} == {par(k, P_CMP + 1)} else {out}'
        return E(out, P_IF, 'unknown')

    @fn('Choose')
    def f_choose(self, node, ctx):
        args = self.nargs(node, 2, -1)
        subject = self.x(args[0], ctx)
        vals = [self.x(v, ctx) for v in args[1:-1]] if len(args) > 2 else []
        els = self.x(args[-1], ctx)
        if not vals:
            return els
        if ctx.mode == 'vec' and subject.type == 'series':
            conds = [f'{par(subject, P_CMP + 1)} == {i + 1}' for i in range(len(vals))]
            return E(f'np.select([{", ".join(conds)}], [{", ".join(v.code for v in vals)}], default={els.code})', P_ATOM, 'series')
        table = '{' + ', '.join(f'{i + 1}: {v.code}' for i, v in enumerate(vals)) + '}'
        return E(f'{table}.get({subject.code}, {els.code})', P_ATOM, 'unknown')

    @fn('Is Missing')
    def f_ismissing(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        return self.missing_test(e, ctx)

    @fn('Zero Or Missing')
    def f_zeroormissing(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        if e.type == 'series':
            return E(f'({e.code}.isna() | ({e.code} == 0))', P_ATOM, 'series')
        return E(f'(pd.isna({e.code}) or {par(e, P_CMP + 1)} == 0)', P_ATOM, 'bool')

    def _isa(self, node, ctx, types):
        self.only_scalar(node, ctx)
        (e,) = self.a(node, ctx, 1)
        return E(f'isinstance({e.code}, {types})', P_ATOM, 'bool')

    @fn('Is Number')
    def f_isnumber(self, node, ctx):
        return self._isa(node, ctx, '(int, float)')

    @fn('Is String')
    def f_isstring(self, node, ctx):
        return self._isa(node, ctx, 'str')

    @fn('Is List')
    def f_islist(self, node, ctx):
        return self._isa(node, ctx, 'list')

    @fn('Is Matrix')
    def f_ismatrix(self, node, ctx):
        return self._isa(node, ctx, 'np.ndarray')

    @fn('Is Associative Array')
    def f_isaa(self, node, ctx):
        return self._isa(node, ctx, 'dict')

    @fn('Is Empty')
    def f_isempty(self, node, ctx):
        self.only_scalar(node, ctx)
        (a,) = self.nargs(node, 1)
        if a.kind == 'name' and a.key not in self.vtypes and a.key not in self.names:
            self.note(node.line, 'info', f'Is Empty({a.value}): a name the script has not set; in Python that is a test of whether it is defined.', once=('isempty', a.key))
            return E(f'{lit(self.py(a.key, a.value))} not in globals()', P_CMP, 'bool')
        e = self.x(a, ctx)
        return E(f'{par(e, P_CMP + 1)} is None', P_CMP, 'bool')

    @fn('Type')
    def f_type(self, node, ctx):
        self.only_scalar(node, ctx)
        (e,) = self.a(node, ctx, 1)
        self.note(node.line, 'info', 'Type(): the Python type\'s name (int, float, str, list, ndarray, dict, DataFrame), not JMP\'s ("Number", "String", ...).', once='type')
        return E(f'type({e.code}).__name__', P_ATOM, 'str')

    @fn('Empty')
    def f_empty(self, node, ctx):
        return E('None', P_ATOM, 'none')

    # ---- strings -------------------------------------------------------------------------------
    @fn('Char')
    def f_char(self, node, ctx):
        args = self.a(node, ctx, 1, 3)
        e = args[0]
        if len(args) == 1:
            if e.type == 'str':
                return e
            if e.type == 'int':
                return E(f'str({e.code})', P_ATOM, 'str')
            self.helper('jsl_char')
            if e.type == 'series':
                return E(f'{par(e, P_ATOM)}.map(jsl_char)', P_ATOM, 'series')
            return E(f'jsl_char({e.code})', P_ATOM, 'str')
        self.helper('jsl_char')
        rest = ', '.join(a.code for a in args[1:])
        if e.type == 'series':
            return E(f'{par(e, P_ATOM)}.map(lambda v: jsl_char(v, {rest}))', P_ATOM, 'series')
        return E(f'jsl_char({e.code}, {rest})', P_ATOM, 'str')

    @fn('Num')
    def f_num(self, node, ctx):
        (a,) = self.nargs(node, 1)
        if a.kind == 'str':
            try:
                v = float(a.value.strip())
                return num_e(int(v) if v.is_integer() and 'e' not in a.value.lower() and '.' not in a.value else v)
            except ValueError:
                return E('np.nan', P_ATOM, 'num')
        e = self.x(a, ctx)
        if is_num_type(e.type):
            return e
        return E(f'pd.to_numeric({e.code}, errors="coerce")', P_ATOM, 'series' if e.type == 'series' else 'num')

    def str_method(self, e, method, args=''):
        if e.type == 'series':
            return E(f'{par(e, P_ATOM)}.str.{method}({args})', P_ATOM, 'series')
        return E(f'{par(e, P_ATOM)}.{method}({args})', P_ATOM, 'str')

    @fn('Uppercase')
    def f_upper(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        return self.str_method(e, 'upper')

    @fn('Lowercase')
    def f_lower(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        return self.str_method(e, 'lower')

    @fn('Titlecase')
    def f_title(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        return self.str_method(e, 'title')

    @fn('Trim', 'Trim Whitespace')
    def f_trim(self, node, ctx):
        args = self.nargs(node, 1, 2)
        e = self.x(args[0], ctx)
        how = 'both'
        if len(args) == 2:
            h = args[1]
            how = (h.value if h.kind in ('str', 'name') else 'both').lower()
        m = {'left': 'lstrip', 'right': 'rstrip'}.get(how, 'strip')
        return self.str_method(e, m)

    @fn('Collapse Whitespace')
    def f_collapse(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        if e.type == 'series':
            return E(f'{par(e, P_ATOM)}.str.split().str.join(" ")', P_ATOM, 'series')
        return E(f'" ".join({par(e, P_ATOM)}.split())', P_ATOM, 'str')

    @fn('Length')
    def f_length(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        if e.type == 'series':
            return E(f'{par(e, P_ATOM)}.str.len()', P_ATOM, 'series')
        if e.type == 'matrix':
            return E(f'{par(e, P_ATOM)}.size', P_ATOM, 'int')
        return E(f'len({e.code})', P_ATOM, 'int')

    @fn('Substr')
    def f_substr(self, node, ctx):
        args = self.nargs(node, 2, 3)
        s = self.x(args[0], ctx)
        e0, k0 = self.offset(args[1], ctx)
        start = self._plus(e0, k0 - 1)
        if len(args) == 3:
            if args[2].kind == 'num' and float(args[2].value).is_integer():
                # the end folded with the start: Substr(s, i, 1) is s[i - 1:i]
                end = self._plus(e0, k0 - 1 + int(args[2].value)).code
            else:
                n = self.x(args[2], ctx)
                end = n.code if start.code == '0' else f'{par(start, P_ADD)} + {par(n, P_ADD + 1)}'
            sl = f'{"" if start.code == "0" else start.code}:{end}'
        else:
            sl = f'{start.code}:'
        if s.type == 'series':
            return E(f'{par(s, P_ATOM)}.str[{sl}]', P_ATOM, 'series')
        return E(f'{par(s, P_ATOM)}[{sl}]', P_ATOM, 'str')

    @fn('Left')
    def f_left(self, node, ctx):
        args = self.a(node, ctx, 2, 3)
        s, n = args[0], args[1]
        code = f'{par(s, P_ATOM)}[:{n.code}]' if s.type != 'series' else f'{par(s, P_ATOM)}.str[:{n.code}]'
        if len(args) == 3:
            code = f'{code}.ljust({n.code}, {args[2].code})' if s.type != 'series' else f'{code}.str.ljust({n.code}, {args[2].code})'
        return E(code, P_ATOM, 'series' if s.type == 'series' else s.type if s.type in ('list',) else 'str')

    @fn('Right')
    def f_right(self, node, ctx):
        args = self.a(node, ctx, 2, 3)
        s, n = args[0], args[1]
        if n.code.isdigit() and int(n.code) > 0:
            sl = f'-{n.code}:'
        else:
            sl = f'len({s.code}) - {par(n, P_ADD + 1)}:' if s.type != 'series' else None
        if s.type == 'series':
            if sl is None:
                raise NotVec()
            code = f'{par(s, P_ATOM)}.str[{sl}]'
            if len(args) == 3:
                code += f'.str.rjust({n.code}, {args[2].code})'
            return E(code, P_ATOM, 'series')
        code = f'{par(s, P_ATOM)}[{sl}]'
        if len(args) == 3:
            code = f'{code}.rjust({n.code}, {args[2].code})'
        return E(code, P_ATOM, 'list' if s.type == 'list' else 'str')

    @fn('Word')
    def f_word(self, node, ctx):
        args = self.nargs(node, 2, 3)
        if args[0].kind == 'matrix':
            raise Unconvertible('Word() of a range of words', node)
        n = self.x(args[0], SCALAR)
        s = self.x(args[1], ctx)
        d = self.x(args[2], SCALAR) if len(args) == 3 else None
        if s.type == 'series' and d is None and n.code.lstrip('-').isdigit():
            k = int(n.code)
            return E(f'{par(s, P_ATOM)}.str.split().str[{k - 1 if k > 0 else k}]', P_ATOM, 'series')
        self.helper('jsl_word')
        extra = f', {d.code}' if d is not None else ''
        if s.type == 'series':
            return E(f'{par(s, P_ATOM)}.map(lambda v: jsl_word({n.code}, v{extra}))', P_ATOM, 'series')
        return E(f'jsl_word({n.code}, {s.code}{extra})', P_ATOM, 'str')

    @fn('Words')
    def f_words(self, node, ctx):
        self.only_scalar(node, ctx)
        args = self.a(node, ctx, 1, 2)
        if len(args) == 1:
            return E(f'{par(args[0], P_ATOM)}.split()', P_ATOM, 'list')
        self.helper('jsl_words')
        return E(f'jsl_words({args[0].code}, {args[1].code})', P_ATOM, 'list')

    @fn('Item')
    def f_item(self, node, ctx):
        args = self.nargs(node, 2, 3)
        n = self.x(args[0], SCALAR)
        s = self.x(args[1], ctx)
        extra = f', {self.x(args[2], SCALAR).code}' if len(args) == 3 else ''
        self.helper('jsl_item')
        if s.type == 'series':
            return E(f'{par(s, P_ATOM)}.map(lambda v: jsl_item({n.code}, v{extra}))', P_ATOM, 'series')
        return E(f'jsl_item({n.code}, {s.code}{extra})', P_ATOM, 'str')

    @fn('Items')
    def f_items(self, node, ctx):
        self.only_scalar(node, ctx)
        args = self.a(node, ctx, 1, 2)
        self.helper('jsl_items')
        return E(f'jsl_items({", ".join(a.code for a in args)})', P_ATOM, 'list')

    @fn('Contains')
    def f_contains(self, node, ctx):
        args = self.nargs(node, 2, 3)
        whole = self.x(args[0], ctx)
        part = self.x(args[1], ctx)
        if ctx.mode == 'vec':
            if whole.type == 'series' and len(args) == 2:
                if ctx.cond:
                    return E(f'{par(whole, P_ATOM)}.str.contains({part.code}, regex=False)', P_ATOM, 'series')
                return E(f'{par(whole, P_ATOM)}.str.find({part.code}) + 1', P_ADD, 'series')
            if part.type == 'series' and whole.type == 'list':
                if ctx.cond:
                    return E(f'{par(part, P_ATOM)}.isin({whole.code})', P_ATOM, 'series')
                return E(f'{par(part, P_ATOM)}.map(lambda v: {whole.code}.index(v) + 1 if v in {whole.code} else 0)', P_ATOM, 'series')
            if 'series' in (whole.type, part.type):
                raise NotVec()
        if len(args) == 2 and (ctx.cond or whole.type == 'dict'):
            if whole.type == 'dict' and not ctx.cond:
                return E(f'int({par(part, P_CMP + 1)} in {par(whole, P_CMP + 1)})', P_ATOM, 'int')
            return E(f'{par(part, P_CMP + 1)} in {par(whole, P_CMP + 1)}', P_CMP, 'bool')
        if len(args) == 2 and whole.type == 'str':
            return E(f'{par(whole, P_ATOM)}.find({part.code}) + 1', P_ADD, 'int')
        self.helper('jsl_contains')
        rest = f', {self.x(args[2], ctx).code}' if len(args) == 3 else ''
        return E(f'jsl_contains({whole.code}, {part.code}{rest})', P_ATOM, 'int')

    @fn('Starts With')
    def f_startswith(self, node, ctx):
        s, p = self.a(node, ctx, 2)
        return self.str_method(s, 'startswith', p.code) if s.type == 'series' else E(f'{par(s, P_ATOM)}.startswith({p.code})', P_ATOM, 'bool')

    @fn('Ends With')
    def f_endswith(self, node, ctx):
        s, p = self.a(node, ctx, 2)
        return self.str_method(s, 'endswith', p.code) if s.type == 'series' else E(f'{par(s, P_ATOM)}.endswith({p.code})', P_ATOM, 'bool')

    @fn('Substitute')
    def f_substitute(self, node, ctx):
        args = self.nargs(node, 3, -1)
        if args[0].is_call('expr', 'nameexpr') or any(a.is_call('expr') for a in args[1:]):
            raise Unconvertible('Substitute() on expressions: JSL expressions as data have no translation', node)
        s = self.x(args[0], ctx)
        pairs = [(self.x(args[i], ctx), self.x(args[i + 1], ctx)) for i in range(1, len(args) - 1, 2)]
        if s.type == 'list':
            out = s.code
            for a, b in pairs:
                out = f'[{b.code} if v == {a.code} else v for v in {out}]'
            return E(out, P_ATOM, 'list')
        out = par(s, P_ATOM)
        for a, b in pairs:
            out += f'.str.replace({a.code}, {b.code}, regex=False)' if s.type == 'series' else f'.replace({a.code}, {b.code})'
        return E(out, P_ATOM, 'series' if s.type == 'series' else 'str')

    @fn('Repeat')
    def f_repeat(self, node, ctx):
        args = self.a(node, ctx, 2, 3)
        if len(args) == 3 or args[0].type == 'matrix':
            reps = f'({args[1].code}, {args[2].code if len(args) == 3 else 1})'
            return E(f'np.tile({args[0].code}, {reps})', P_ATOM, 'matrix')
        return E(f'{par(args[0], P_MUL)} * {par(args[1], P_MUL + 1)}', P_MUL, args[0].type if args[0].type in ('list', 'str') else 'str')

    @fn('Reverse')
    def f_reverse(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        return E(f'{par(e, P_ATOM)}[::-1]', P_ATOM, e.type)

    @fn('Concat Items')
    def f_concatitems(self, node, ctx):
        args = self.a(node, ctx, 1, 2)
        d = args[1].code if len(args) == 2 else '" "'
        return E(f'{d}.join({args[0].code})', P_ATOM, 'str')

    @fn('Regex')
    def f_regex(self, node, ctx):
        args = self.nargs(node, 2, 5)
        s = self.x(args[0], ctx)
        pat = self.x(args[1], SCALAR)
        fmt_ = None
        flags = []
        for a in args[2:]:
            if a.kind in ('str', 'name') and a.value.replace(' ', '').upper() in ('IGNORECASE', 'GLOBALREPLACE'):
                flags.append(a.value.replace(' ', '').upper())
            else:
                fmt_ = self.x(a, SCALAR)
        self.note(node.line, 'info', 'Regex: JMP\'s regular expressions are Perl-like; Python\'s re module reads most of them the same way (not possessive quantifiers or \\Q...\\E).', once='regex')
        self.helper('jsl_regex')
        kw = []
        if fmt_ is not None:
            kw.append(fmt_.code)
        if 'IGNORECASE' in flags:
            kw.append('ignore_case=True')
        if 'GLOBALREPLACE' in flags:
            kw.append('global_replace=True')
        extra = ''.join(', ' + k for k in kw)
        if s.type == 'series':
            return E(f'{par(s, P_ATOM)}.map(lambda v: jsl_regex(v, {pat.code}{extra}))', P_ATOM, 'series')
        return E(f'jsl_regex({s.code}, {pat.code}{extra})', P_ATOM, 'unknown')

    @fn('Regex Match')
    def f_regexmatch(self, node, ctx):
        self.only_scalar(node, ctx)
        args = self.nargs(node, 2, 4)
        s, pat = self.x(args[0], ctx), self.x(args[1], ctx)
        match_case = any(a.kind in ('str', 'name') and a.value.replace(' ', '').upper() == 'MATCHCASE' for a in args[2:])
        self.helper('jsl_regex_match')
        return E(f'jsl_regex_match({s.code}, {pat.code}{", match_case=True" if match_case else ""})', P_ATOM, 'list')

    @fn('Munger')
    def f_munger(self, node, ctx):
        self.only_scalar(node, ctx)
        args = self.a(node, ctx, 3, 4)
        self.helper('jsl_munger')
        return E(f'jsl_munger({", ".join(a.code for a in args)})', P_ATOM, 'unknown')

    @fn('Eval Insert')
    def f_evalinsert(self, node, ctx):
        self.only_scalar(node, ctx)
        args = self.nargs(node, 1, 3)
        if args[0].kind != 'str':
            raise Unconvertible('Eval Insert() of a string made while the script runs', node)
        start = args[1].value if len(args) > 1 and args[1].kind == 'str' else '^'
        end = args[2].value if len(args) > 2 and args[2].kind == 'str' else start
        text = args[0].value
        out, i = [], 0
        while i < len(text):
            j = text.find(start, i)
            if j < 0:
                out.append(('t', text[i:]))
                break
            k = text.find(end, j + len(start))
            if k < 0:
                out.append(('t', text[i:]))
                break
            out.append(('t', text[i:j]))
            out.append(('e', text[j + len(start):k]))
            i = k + len(end)
        parts = []      # text, or the E of an expression
        for kind, v in out:
            if kind == 't':
                if v:
                    parts.append(v)
                continue
            try:
                sub = jsl.parse_expr(v)
            except ValueError:
                raise Unconvertible(f'Eval Insert(): ^{v}^ is not a JSL expression', node)
            e = self.x(sub, ctx)
            if e.type not in ('str', 'int'):
                self.helper('jsl_char')
                e = E(f'jsl_char({e.code})', P_ATOM, 'str')
            parts.append(e)
        codes = [p.code for p in parts if isinstance(p, E)]
        if not codes:
            return E(lit(''.join(parts)), P_ATOM, 'str')
        # Before Python 3.12 an f-string's {} may hold neither a backslash
        # nor the f-string's own quote: take the quote the expressions do
        # not use, and join the pieces when they use both.
        for q in ('"', "'"):
            if any('\\' in c or q in c or '\n' in c for c in codes):
                continue
            body = []
            for p in parts:
                if isinstance(p, E):
                    c = p.code
                    body.append('{(' + c + ')}' if c.startswith('{') or 'lambda' in c else '{' + c + '}')
                else:
                    body.append(str_body(p, q).replace('{', '{{').replace('}', '}}'))
            return E('f' + q + ''.join(body) + q, P_ATOM, 'str')
        pieces = [lit(p) if isinstance(p, str) else (p.code if p.type == 'str' else f'str({p.code})') for p in parts]
        return E(f'"".join([{", ".join(pieces)}])', P_ATOM, 'str')

    @fn('Format')
    def f_format(self, node, ctx):
        args = self.nargs(node, 1, -1)
        e = self.x(args[0], ctx)
        if len(args) == 1:
            return self.f_char(jsl.Node('call', 'Char', [args[0]], line=node.line, extra={'key': 'char'}), ctx)
        fmt_node = args[1]
        f = fmt_node.value.lower() if fmt_node.kind in ('str', 'name') else None
        nums = [a for a in args[2:] if a.kind == 'num']
        if f in ('best',):
            self.helper('jsl_char')
            return E(f'jsl_char({e.code}{", " + lit(nums[0].value) if nums else ""})', P_ATOM, 'str')
        if f in ('fixed dec', 'fixeddec'):
            d = int(nums[1].value) if len(nums) > 1 else 0
            sep = ',' if any(a.kind == 'str' and 'thousand' in a.value.lower() for a in args[2:]) else ''
            if e.type == 'series':
                return E(f'{par(e, P_ATOM)}.map(lambda v: f"{{v:{sep}.{d}f}}")', P_ATOM, 'series')
            return E(f'format({e.code}, "{sep}.{d}f")', P_ATOM, 'str')
        if f == 'percent':
            d = int(nums[1].value) if len(nums) > 1 else 0
            return E(f'format({e.code}, ".{d}%")', P_ATOM, 'str')
        if f in ('scientific', 'engineering'):
            d = int(nums[1].value) if len(nums) > 1 else 6
            return E(f'format({e.code}, ".{d}e")', P_ATOM, 'str')
        if f == 'pvalue':
            return E(f'("<.0001" if {par(e, P_CMP + 1)} < 0.0001 else format({e.code}, ".4f"))', P_ATOM, 'str')
        if f == 'currency':
            return E(f'format({e.code}, ",.2f")', P_ATOM, 'str')
        if f in DATE_FORMATS:
            return self.strftime(e, DATE_FORMATS[f])
        if f and f.replace(' ', '') in ('yyyyqq',):
            return E(f'"{{0.year}}Q{{0.quarter}}".format({self.as_date(e).code})', P_ATOM, 'str')
        raise Unconvertible(f'Format() with the format "{fmt_node.value if fmt_node.kind in ("str", "name") else "?"}"', node)

    @fn('Format Date')
    def f_formatdate(self, node, ctx):
        args = self.nargs(node, 2, 3)
        e = self.x(args[0], ctx)
        f = args[1].value.lower() if args[1].kind in ('str', 'name') else None
        if f in DATE_FORMATS:
            return self.strftime(e, DATE_FORMATS[f])
        if f and f.replace(' ', '') == 'yyyyqq':
            return E(f'"{{0.year}}Q{{0.quarter}}".format({self.as_date(e).code})', P_ATOM, 'str')
        raise Unconvertible('Format Date() with this format', node)

    def as_date(self, e):
        """e as a Timestamp: a number is JMP's seconds from 1 January 1904."""
        if e.type == 'date':
            return e
        if e.type in ('int', 'num'):
            return E(f'(pd.Timestamp("1904-01-01") + pd.Timedelta(seconds={e.code}))', P_ATOM, 'date')
        return E(f'pd.Timestamp({e.code})', P_ATOM, 'date')

    def strftime(self, e, fmt_):
        if e.type == 'series':
            return E(f'pd.to_datetime({e.code}).dt.strftime({lit(fmt_)})', P_ATOM, 'series')
        return E(f'{par(self.as_date(e), P_ATOM)}.strftime({lit(fmt_)})', P_ATOM, 'str')

    @fn('Hex', 'Char To Hex')
    def f_hex(self, node, ctx):
        args = self.nargs(node, 1, 2)
        if len(args) == 2 and args[1].kind == 'str' and args[1].value.lower() == 'integer':
            e = self.x(args[0], ctx)
            return E(f'format(int({e.code}), "X")', P_ATOM, 'str')
        raise Unconvertible('Hex() of this kind', node)

    @fn('Hex To Number')
    def f_hextonumber(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        return E(f'int({e.code}.replace(" ", ""), 16)', P_ATOM, 'int')

    # ---- lists and associative arrays ------------------------------------------------------------
    @fn('List')
    def f_list(self, node, ctx):
        return self.x_list(node, ctx)

    @fn('Eval List')
    def f_evallist(self, node, ctx):
        (a,) = self.nargs(node, 1)
        return self.x(a, ctx)

    @fn('Insert')
    def f_insert(self, node, ctx):
        self.only_scalar(node, ctx)
        args = self.a(node, ctx, 2, 3)
        src = args[0]
        if src.type == 'dict' and len(args) == 3:
            return E(f'{{**{src.code}, {args[1].code}: {args[2].code}}}', P_ATOM, 'dict')
        item = args[1].code if args[1].type == 'list' else f'[{args[1].code}]'
        if len(args) == 2:
            return E(f'{par(src, P_ADD)} + {item}', P_ADD, 'list')
        p = self.idx(self.nargs(node, 3)[2], ctx)
        return E(f'{par(src, P_ATOM)}[:{p.code}] + {item} + {par(src, P_ATOM)}[{p.code}:]', P_ADD, 'list')

    @fn('Remove')
    def f_remove(self, node, ctx):
        self.only_scalar(node, ctx)
        args = self.nargs(node, 2, 3)
        src = self.x(args[0], ctx)
        if src.type == 'dict':
            k = self.x(args[1], ctx)
            return E(f'{{k: v for k, v in {src.code}.items() if k != {k.code}}}', P_ATOM, 'dict')
        p = self.idx(args[1], ctx)
        n = self.x(args[2], ctx).code if len(args) == 3 else '1'
        end = str(int(p.code) + int(n)) if p.code.isdigit() and n.isdigit() else f'{par(p, P_ADD)} + {n}'
        return E(f'{par(src, P_ATOM)}[:{p.code}] + {par(src, P_ATOM)}[{end}:]', P_ADD, src.type)

    @fn('Sort List')
    def f_sortlist(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        return E(f'sorted({e.code})', P_ATOM, 'list')

    @fn('Sort Ascending')
    def f_sortasc(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        if e.type == 'list':
            return E(f'sorted({e.code})', P_ATOM, 'list')
        return E(f'np.sort({e.code}, axis=None).reshape(np.shape({e.code}))', P_ATOM, 'matrix')

    @fn('Sort Descending')
    def f_sortdesc(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        if e.type == 'list':
            return E(f'sorted({e.code}, reverse=True)', P_ATOM, 'list')
        return E(f'np.sort({e.code}, axis=None)[::-1].reshape(np.shape({e.code}))', P_ATOM, 'matrix')

    @fn('Shift')
    def f_shift(self, node, ctx):
        args = self.a(node, ctx, 1, 2)
        n = args[1].code if len(args) == 2 else '1'
        return E(f'{par(args[0], P_ATOM)}[{n}:] + {par(args[0], P_ATOM)}[:{n}]', P_ADD, 'list')

    @fn('Loc')
    def f_loc(self, node, ctx):
        self.only_scalar(node, ctx)
        args = self.a(node, ctx, 1, 2)
        src = args[0]
        if src.type == 'list':
            if len(args) != 2:
                raise Unconvertible('Loc() of a list takes the item to find', node)
            return E(f'[i + 1 for i, v in enumerate({src.code}) if v == {args[1].code}]', P_ATOM, 'list')
        if len(args) == 2:
            return E(f'np.flatnonzero(np.ravel({src.code}) == {par(args[1], P_CMP + 1)}) + 1', P_ADD, 'rows')
        return E(f'np.flatnonzero({src.code}) + 1', P_ADD, 'rows')

    @fn('Loc Max')
    def f_locmax(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        return E(f'int(np.nanargmax({e.code})) + 1', P_ADD, 'int')

    @fn('Loc Min')
    def f_locmin(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        return E(f'int(np.nanargmin({e.code})) + 1', P_ADD, 'int')

    @fn('Associative Array')
    def f_aa(self, node, ctx):
        self.only_scalar(node, ctx)
        args = [a for a in node.args if a.kind != 'empty']
        if not args:
            return E('{}', P_ATOM, 'dict')
        if len(args) == 1:
            ref = self.colref(args[0], ctx, quiet=True)
            if ref is not None:
                return E(f'dict.fromkeys({ref.series()}.dropna(), 1)', P_ATOM, 'dict')
            e = self.x(args[0], ctx)
            return E(f'dict({e.code})', P_ATOM, 'dict')
        k, v = (self.colref(a, ctx, quiet=True) for a in args[:2])
        kc = f'{k.series()}' if k else self.x(args[0], ctx).code
        vc = f'{v.series()}' if v else self.x(args[1], ctx).code
        return E(f'dict(zip({kc}, {vc}))', P_ATOM, 'dict')

    @fn('As List')
    def f_aslist(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        if isinstance(e.info, tuple) and len(e.info) == 2 and 1 in e.info:
            return E(f'np.ravel({e.code}).tolist()', P_ATOM, 'list')
        return E(f'{par(e, P_ATOM)}.tolist()', P_ATOM, 'list')

    # ---- matrices ----------------------------------------------------------------------------------
    @fn('J')
    def f_j(self, node, ctx):
        self.only_scalar(node, ctx)
        args = self.nargs(node, 1, 3)
        es = [self.x(a, ctx) for a in args]
        r = es[0]
        c = es[1] if len(es) > 1 else es[0]
        dims = [a for a in args[:2]] if len(args) > 1 else [args[0], args[0]]
        shape = tuple(int(d.value) if d.kind == 'num' else None for d in dims)
        if len(es) == 3:
            v = es[2]
            if v.type == 'unknown' and any(n.is_call(*RANDOM_KEYS) for n in args[2].walk()):
                raise Unconvertible('J() filled by a random function (JSL draws a value for each element)', node)
            if args[2].kind == 'num' and args[2].value == 0:
                return E(f'np.zeros(({r.code}, {c.code}))', P_ATOM, 'matrix', shape)
            if args[2].kind == 'num' and args[2].value == 1:
                return E(f'np.ones(({r.code}, {c.code}))', P_ATOM, 'matrix', shape)
            return E(f'np.full(({r.code}, {c.code}), {v.code})', P_ATOM, 'matrix', shape)
        return E(f'np.ones(({r.code}, {c.code}))', P_ATOM, 'matrix', shape)

    @fn('Identity')
    def f_identity(self, node, ctx):
        (n,) = self.a(node, ctx, 1)
        return E(f'np.eye({n.code})', P_ATOM, 'matrix')

    @fn('Index')
    def f_index(self, node, ctx):
        args = self.nargs(node, 2, 3)
        a = self.x(args[0], ctx)
        if len(args) == 3:
            step = self.x(args[2], ctx)
            return E(f'np.arange({a.code}, {self.x(args[1], ctx).code} + {par(step, P_ADD + 1)} / 2, {step.code})', P_ATOM, 'rows')
        return E(f'np.arange({a.code}, {self.plus1(args[1], ctx)})', P_ATOM, 'rows')

    def mat1(self, node, ctx, template, t='matrix'):
        self.only_scalar(node, ctx)
        (e,) = self.a(node, ctx, 1)
        return E(template.format(e.code), P_ATOM, t)

    @fn('Inverse', 'Inv')
    def f_inv(self, node, ctx):
        return self.mat1(node, ctx, 'np.linalg.inv({})')

    @fn('G Inverse')
    def f_ginv(self, node, ctx):
        return self.mat1(node, ctx, 'np.linalg.pinv({})')

    @fn('Det')
    def f_det(self, node, ctx):
        return self.mat1(node, ctx, 'np.linalg.det({})', 'num')

    @fn('Trace')
    def f_trace(self, node, ctx):
        return self.mat1(node, ctx, 'np.trace({})', 'num')

    @fn('Transpose')
    def f_transpose(self, node, ctx):
        self.only_scalar(node, ctx)
        (e,) = self.a(node, ctx, 1)
        return E(f'{par(e, P_ATOM)}.T', P_ATOM, 'matrix')

    @fn('Diag')
    def f_diag(self, node, ctx):
        self.only_scalar(node, ctx)
        args = self.a(node, ctx, 1, 2)
        e = args[0]
        if isinstance(e.info, tuple) and len(e.info) == 2 and e.info[0] == e.info[1] and e.info[0] not in (None, 1):
            code = f'np.diag(np.diag({e.code}))'
        else:
            code = f'np.diag(np.ravel({e.code}))'
        if len(args) == 2:
            raise Unconvertible('Diag() of two matrices', node)
        return E(code, P_ATOM, 'matrix')

    @fn('Vec Diag')
    def f_vecdiag(self, node, ctx):
        return self.mat1(node, ctx, 'np.diag({}).reshape(-1, 1)')

    @fn('Cholesky')
    def f_cholesky(self, node, ctx):
        return self.mat1(node, ctx, 'np.linalg.cholesky({})')

    @fn('Eigen')
    def f_eigen(self, node, ctx):
        self.helper('jsl_eigen')
        return self.mat1(node, ctx, 'jsl_eigen({})', 'list')

    @fn('SVD')
    def f_svd(self, node, ctx):
        self.helper('jsl_svd')
        return self.mat1(node, ctx, 'jsl_svd({})', 'list')

    @fn('Solve')
    def f_solve(self, node, ctx):
        self.only_scalar(node, ctx)
        a, b = self.a(node, ctx, 2)
        return E(f'np.linalg.solve({a.code}, {b.code})', P_ATOM, 'matrix')

    @fn('Shape')
    def f_shape(self, node, ctx):
        self.only_scalar(node, ctx)
        args = self.a(node, ctx, 2, 3)
        c = args[2].code if len(args) == 3 else '-1'
        return E(f'np.reshape({args[0].code}, ({args[1].code}, {c}))', P_ATOM, 'matrix')

    @fn('V Concat')
    def f_vconcat(self, node, ctx):
        self.only_scalar(node, ctx)
        es = self.a(node, ctx, 2, -1)
        return E(f'np.vstack([{", ".join(e.code for e in es)}])', P_ATOM, 'matrix')

    @fn('H Concat')
    def f_hconcat(self, node, ctx):
        self.only_scalar(node, ctx)
        es = self.a(node, ctx, 2, -1)
        return E(f'np.hstack([{", ".join(e.code for e in es)}])', P_ATOM, 'matrix')

    @fn('Direct Product')
    def f_kron(self, node, ctx):
        self.only_scalar(node, ctx)
        a, b = self.a(node, ctx, 2)
        return E(f'np.kron({a.code}, {b.code})', P_ATOM, 'matrix')

    @fn('E Max')
    def f_emax(self, node, ctx):
        a, b = self.a(node, ctx, 2)
        return E(f'np.maximum({a.code}, {b.code})', P_ATOM, 'matrix')

    @fn('E Min')
    def f_emin(self, node, ctx):
        a, b = self.a(node, ctx, 2)
        return E(f'np.minimum({a.code}, {b.code})', P_ATOM, 'matrix')

    @fn('All')
    def f_all(self, node, ctx):
        es = self.a(node, ctx, 1, -1)
        return E(' and '.join(f'bool(np.all({e.code}))' for e in es), P_AND if len(es) > 1 else P_ATOM, 'bool')

    @fn('Any')
    def f_any(self, node, ctx):
        es = self.a(node, ctx, 1, -1)
        return E(' or '.join(f'bool(np.any({e.code}))' for e in es), P_OR if len(es) > 1 else P_ATOM, 'bool')

    @fn('Matrix')
    def f_matrix(self, node, ctx):
        self.only_scalar(node, ctx)
        args = self.nargs(node, 1, 2)
        if len(args) == 2:
            r, c = self.x(args[0], ctx), self.x(args[1], ctx)
            return E(f'np.zeros(({r.code}, {c.code}))', P_ATOM, 'matrix')
        a = args[0]
        if a.kind == 'list' and a.args and all(x.kind == 'list' for x in a.args):
            rows = ['[' + ', '.join(self.x(v, ctx).code for v in r.args) + ']' for r in a.args]
            return E(f'np.array([{", ".join(rows)}], dtype=float)', P_ATOM, 'matrix')
        e = self.x(a, ctx)
        return E(f'np.array({e.code}, dtype=float).reshape(-1, 1)', P_ATOM, 'matrix')

    def vstat(self, node, ctx, how):
        self.only_scalar(node, ctx)
        args = self.a(node, ctx, 1, 2)
        m = args[0].code
        if how == 'std':
            return E(f'np.nanstd({m}, axis=0, ddof=1, keepdims=True)', P_ATOM, 'matrix')
        if how == 'quantile':
            return E(f'np.nanquantile({m}, {args[1].code}, axis=0, method="weibull", keepdims=True)', P_ATOM, 'matrix')
        if how == 'standardize':
            return E(f'({m} - np.nanmean({m}, axis=0)) / np.nanstd({m}, axis=0, ddof=1)', P_MUL, 'matrix')
        return E(f'np.nan{how}({m}, axis=0, keepdims=True)', P_ATOM, 'matrix')

    @fn('V Sum')
    def f_vsum(self, node, ctx):
        return self.vstat(node, ctx, 'sum')

    @fn('V Mean')
    def f_vmean(self, node, ctx):
        return self.vstat(node, ctx, 'mean')

    @fn('V Std')
    def f_vstd(self, node, ctx):
        return self.vstat(node, ctx, 'std')

    @fn('V Max')
    def f_vmax(self, node, ctx):
        return self.vstat(node, ctx, 'max')

    @fn('V Min')
    def f_vmin(self, node, ctx):
        return self.vstat(node, ctx, 'min')

    @fn('V Median')
    def f_vmedian(self, node, ctx):
        return self.vstat(node, ctx, 'median')

    @fn('V Quantile')
    def f_vquantile(self, node, ctx):
        return self.vstat(node, ctx, 'quantile')

    @fn('V Standardize')
    def f_vstandardize(self, node, ctx):
        return self.vstat(node, ctx, 'standardize')

    @fn('Correlation')
    def f_correlation(self, node, ctx):
        self.only_scalar(node, ctx)
        e = self.a(node, ctx, 1, -1)[0]
        return E(f'np.corrcoef({e.code}, rowvar=False)', P_ATOM, 'matrix')

    @fn('Covariance')
    def f_covariance(self, node, ctx):
        self.only_scalar(node, ctx)
        e = self.a(node, ctx, 1, -1)[0]
        return E(f'np.cov({e.code}, rowvar=False)', P_ATOM, 'matrix')

    @fn('Ranking')
    def f_ranking(self, node, ctx):
        self.only_scalar(node, ctx)
        (e,) = self.a(node, ctx, 1)
        return E(f'stats.rankdata({e.code}, method="ordinal")', P_ATOM, 'rows')

    @fn('Ranking Tie')
    def f_rankingtie(self, node, ctx):
        self.only_scalar(node, ctx)
        (e,) = self.a(node, ctx, 1)
        return E(f'stats.rankdata({e.code}, method="average")', P_ATOM, 'rows')

    @fn('Rank Index', 'Rank')
    def f_rankindex(self, node, ctx):
        self.only_scalar(node, ctx)
        (e,) = self.a(node, ctx, 1)
        return E(f'np.argsort(np.ravel({e.code}), kind="stable") + 1', P_ADD, 'rows')

    # ---- probability --------------------------------------------------------------------------------
    def distribution(self, node, ctx):
        func, spec = DISTRIBUTIONS[node.key]
        names = spec.split(',')
        args = self.a(node, ctx, 1, len(names))
        out = []
        for nm, e in zip(names, args):
            if '=' in nm:
                k, default = nm.split('=')
                if e.code != default:
                    out.append(f'{k}={e.code}')
            else:
                out.append(e.code)
        return E(f'{func}({", ".join(out)})', P_ATOM, 'series' if any(e.type == 'series' for e in args) else 'num')

    def lognormal(self, node, ctx):
        args = self.a(node, ctx, 1, 3)
        mu = args[1].code if len(args) > 1 else '0'
        sigma = args[2].code if len(args) > 2 else '1'
        return E(f'stats.lognorm.{LOGNORMAL[node.key]}({args[0].code}, {sigma}, scale=np.exp({mu}))', P_ATOM, 'num')

    def discrete(self, node, ctx):
        func, names, template = DISCRETE[node.key]
        args = self.a(node, ctx, len(names))
        return E(f'{func}({template.format(**{n: a.code for n, a in zip(names, args)})})', P_ATOM, 'num')

    # ---- random numbers ---------------------------------------------------------------------------------
    def rand(self, node, ctx):
        if self.rng is None:
            self.rng = 'rng'
            self.taken.add('rng')
            self.preload.insert(0, 'rng = np.random.default_rng()')
            self.note(node.line, 'info', 'Random numbers come from numpy\'s generator (rng): its streams differ from JMP\'s, so the values are not the ones JMP draws, even from the same seed.', once='random')
        return self.rng

    def size(self, ctx):
        return f'size=len({ctx.frame.var})' if ctx.mode == 'vec' else ''

    def rnd(self, node, ctx, call, args):
        g = self.rand(node, ctx)
        sz = self.size(ctx)
        inner = ', '.join([a for a in args if a] + ([sz] if sz else []))
        return E(f'{g}.{call}({inner})', P_ATOM, 'series' if sz else 'num')

    @fn('Random Uniform')
    def f_runiform(self, node, ctx):
        args = self.a(node, SCALAR, 0, 2)
        if len(args) == 1:
            return self.rnd(node, ctx, 'uniform', ['0', args[0].code])
        return self.rnd(node, ctx, 'uniform', [a.code for a in args])

    @fn('Random Normal')
    def f_rnormal(self, node, ctx):
        args = self.a(node, SCALAR, 0, 2)
        return self.rnd(node, ctx, 'normal', [a.code for a in args])

    @fn('Random Integer')
    def f_rinteger(self, node, ctx):
        args = self.a(node, SCALAR, 1, 2)
        lo, hi = ('1', args[0]) if len(args) == 1 else (args[0].code, args[1])
        e = self.rnd(node, ctx, 'integers', [lo, par(hi, P_ADD) + ' + 1'])
        return E(e.code, e.prec, 'int' if e.type == 'num' else e.type)

    @fn('Random Exp')
    def f_rexp(self, node, ctx):
        return self.rnd(node, ctx, 'exponential', [])

    @fn('Random Gamma')
    def f_rgamma(self, node, ctx):
        args = self.a(node, SCALAR, 1, 2)
        return self.rnd(node, ctx, 'gamma', [a.code for a in args])

    @fn('Random Beta')
    def f_rbeta(self, node, ctx):
        args = self.a(node, SCALAR, 2, 2)
        return self.rnd(node, ctx, 'beta', [a.code for a in args])

    @fn('Random Poisson')
    def f_rpoisson(self, node, ctx):
        args = self.a(node, SCALAR, 1)
        return self.rnd(node, ctx, 'poisson', [args[0].code])

    @fn('Random Binomial')
    def f_rbinomial(self, node, ctx):
        n, p = self.a(node, SCALAR, 2)
        return self.rnd(node, ctx, 'binomial', [n.code, p.code])

    @fn('Random Negative Binomial')
    def f_rnbinom(self, node, ctx):
        n, p = self.a(node, SCALAR, 2)
        return self.rnd(node, ctx, 'negative_binomial', [n.code, p.code])

    @fn('Random ChiSquare')
    def f_rchisq(self, node, ctx):
        args = self.a(node, SCALAR, 1)
        return self.rnd(node, ctx, 'chisquare', [args[0].code])

    @fn('Random t')
    def f_rt(self, node, ctx):
        args = self.a(node, SCALAR, 1)
        return self.rnd(node, ctx, 'standard_t', [args[0].code])

    @fn('Random F')
    def f_rf(self, node, ctx):
        a, b = self.a(node, SCALAR, 2)
        return self.rnd(node, ctx, 'f', [a.code, b.code])

    @fn('Random Lognormal')
    def f_rlognormal(self, node, ctx):
        args = self.a(node, SCALAR, 0, 2)
        return self.rnd(node, ctx, 'lognormal', [a.code for a in args])

    @fn('Random Logistic')
    def f_rlogistic(self, node, ctx):
        args = self.a(node, SCALAR, 0, 2)
        return self.rnd(node, ctx, 'logistic', [a.code for a in args])

    @fn('Random Cauchy')
    def f_rcauchy(self, node, ctx):
        return self.rnd(node, ctx, 'standard_cauchy', [])

    @fn('Random Weibull')
    def f_rweibull(self, node, ctx):
        args = self.a(node, SCALAR, 1, 2)
        e = self.rnd(node, ctx, 'weibull', [args[0].code])
        if len(args) == 2:
            return E(f'{par(args[1], P_MUL)} * {e.code}', P_MUL, e.type)
        return e

    @fn('Random Triangular')
    def f_rtriangular(self, node, ctx):
        args = self.a(node, SCALAR, 1, 3)
        if len(args) == 1:
            args = [E('0'), args[0], E('1')]
        elif len(args) == 2:
            args = [E('0'), args[0], args[1]]
        return self.rnd(node, ctx, 'triangular', [a.code for a in args])

    @fn('Random Shuffle')
    def f_rshuffle(self, node, ctx):
        self.only_scalar(node, ctx)
        (e,) = self.a(node, ctx, 1)
        return E(f'{self.rand(node, ctx)}.permutation({e.code})', P_ATOM, e.type)

    @fn('Random Index')
    def f_rindex(self, node, ctx):
        self.only_scalar(node, ctx)
        n, k = self.a(node, ctx, 2)
        return E(f'np.sort({self.rand(node, ctx)}.choice(np.arange(1, {par(n, P_ADD)} + 1), size={k.code}, replace=False))', P_ATOM, 'rows')

    @fn('Random Category')
    def f_rcategory(self, node, ctx):
        args = self.nargs(node, 3, -1)
        probs = [self.x(a, SCALAR) for a in args[0:-1:2]]
        vals = [self.x(a, SCALAR) for a in args[1:-1:2]]
        other = self.x(args[-1], SCALAR) if len(args) % 2 == 1 else None
        if other is None:
            raise Unconvertible('Random Category() without the else result', node)
        g = self.rand(node, ctx)
        sz = self.size(ctx)
        plist = '[' + ', '.join(p.code for p in probs) + ']'
        choices = '[' + ', '.join(v.code for v in vals + [other]) + ']'
        pcode = f'{plist} + [1 - sum({plist})]'
        return E(f'{g}.choice({choices}, p={pcode}{", " + sz if sz else ""})', P_ATOM, 'series' if sz else 'unknown')

    @fn('Random Multivariate Normal')
    def f_rmvn(self, node, ctx):
        self.only_scalar(node, ctx)
        args = self.a(node, ctx, 2, 3)
        n = f', size={args[2].code}' if len(args) == 3 else ''
        return E(f'{self.rand(node, ctx)}.multivariate_normal(np.ravel({args[0].code}), {args[1].code}{n})', P_ATOM, 'matrix')

    # ---- dates and times ------------------------------------------------------------------------------
    def date_part(self, node, ctx, attr, py=None):
        (e,) = self.a(node, ctx, 1)
        self.date_note(node)
        if e.type == 'series':
            return E(f'pd.to_datetime({e.code}).dt.{py or attr}', P_ATOM, 'series')
        d = par(e, P_ATOM) if e.type == 'date' else f'pd.Timestamp({e.code})'
        return E(f'{d}.{attr}', P_ATOM, 'int')

    @fn('Year')
    def f_year(self, node, ctx):
        return self.date_part(node, ctx, 'year')

    @fn('Month')
    def f_month(self, node, ctx):
        return self.date_part(node, ctx, 'month')

    @fn('Day')
    def f_day(self, node, ctx):
        return self.date_part(node, ctx, 'day')

    @fn('Hour')
    def f_hour(self, node, ctx):
        args = self.nargs(node, 1, 2)
        if len(args) == 2:
            raise Unconvertible('Hour() on the 12-hour clock', node)
        return self.date_part(node, ctx, 'hour')

    @fn('Minute')
    def f_minute(self, node, ctx):
        return self.date_part(node, ctx, 'minute')

    @fn('Second')
    def f_second(self, node, ctx):
        return self.date_part(node, ctx, 'second')

    @fn('Quarter')
    def f_quarter(self, node, ctx):
        return self.date_part(node, ctx, 'quarter')

    @fn('Day Of Year')
    def f_dayofyear(self, node, ctx):
        return self.date_part(node, ctx, 'dayofyear')

    @fn('Day Of Week')
    def f_dayofweek(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        self.date_note(node)
        if e.type == 'series':
            return E(f'(pd.to_datetime({e.code}).dt.dayofweek + 1) % 7 + 1', P_ADD, 'series')
        d = par(e, P_ATOM) if e.type == 'date' else f'pd.Timestamp({e.code})'
        return E(f'({d}.dayofweek + 1) % 7 + 1', P_ADD, 'int')

    @fn('Week Of Year')
    def f_weekofyear(self, node, ctx):
        args = self.nargs(node, 1, 2)
        e = self.x(args[0], ctx)
        rule = int(args[1].value) if len(args) == 2 and args[1].kind == 'num' else 1
        if e.type == 'series':
            d = f'pd.to_datetime({e.code}).dt'
            code = {1: f'{d}.strftime("%U").astype(int) + 1', 2: f'{d}.strftime("%U").astype(int)', 3: f'{d}.isocalendar().week'}[rule]
            return E(code, P_ADD, 'series')
        d = par(e, P_ATOM) if e.type == 'date' else f'pd.Timestamp({e.code})'
        code = {1: f'int({d}.strftime("%U")) + 1', 2: f'int({d}.strftime("%U"))', 3: f'{d}.isocalendar().week'}[rule]
        return E(code, P_ADD, 'int')

    @fn('Time Of Day')
    def f_timeofday(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        d = par(e, P_ATOM)
        if e.type == 'series':
            return E(f'(pd.to_datetime({e.code}) - pd.to_datetime({e.code}).dt.normalize()).dt.total_seconds()', P_ATOM, 'series')
        return E(f'({d} - {d}.normalize()).total_seconds()', P_ATOM, 'num')

    @fn('Today')
    def f_today(self, node, ctx):
        self.date_note(node)
        return E('pd.Timestamp.now()', P_ATOM, 'date')

    @fn('Date DMY')
    def f_datedmy(self, node, ctx):
        d, m, y = self.a(node, ctx, 3)
        self.date_note(node)
        if 'series' in (d.type, m.type, y.type):
            return E(f'pd.to_datetime(pd.DataFrame({{"year": {y.code}, "month": {m.code}, "day": {d.code}}}))', P_ATOM, 'series')
        return E(f'pd.Timestamp({y.code}, {m.code}, {d.code})', P_ATOM, 'date')

    @fn('Date MDY')
    def f_datemdy(self, node, ctx):
        m, d, y = self.a(node, ctx, 3)
        self.date_note(node)
        if 'series' in (d.type, m.type, y.type):
            return E(f'pd.to_datetime(pd.DataFrame({{"year": {y.code}, "month": {m.code}, "day": {d.code}}}))', P_ATOM, 'series')
        return E(f'pd.Timestamp({y.code}, {m.code}, {d.code})', P_ATOM, 'date')

    def in_unit(self, node, ctx, unit, factor=None):
        args = self.a(node, ctx, 0, 1)
        n = args[0].code if args else '1'
        self.date_note(node)
        if factor:
            return E(f'pd.Timedelta(days={factor} * {n})' if n != '1' else f'pd.Timedelta(days={factor})', P_ATOM, 'delta')
        return E(f'pd.Timedelta({unit}={n})', P_ATOM, 'delta')

    @fn('In Days')
    def f_indays(self, node, ctx):
        return self.in_unit(node, ctx, 'days')

    @fn('In Hours')
    def f_inhours(self, node, ctx):
        return self.in_unit(node, ctx, 'hours')

    @fn('In Minutes')
    def f_inminutes(self, node, ctx):
        return self.in_unit(node, ctx, 'minutes')

    @fn('In Weeks')
    def f_inweeks(self, node, ctx):
        return self.in_unit(node, ctx, 'weeks')

    @fn('In Years')
    def f_inyears(self, node, ctx):
        return self.in_unit(node, ctx, 'days', factor='365.25')

    @fn('As Date')
    def f_asdate(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        self.date_note(node)
        if e.type in ('date',):
            return e
        if e.type == 'series':
            return E(f'pd.Timestamp("1904-01-01") + pd.to_timedelta({e.code}, unit="s")', P_ADD, 'series')
        return E(f'pd.Timestamp("1904-01-01") + pd.Timedelta(seconds={e.code})', P_ADD, 'date')

    @fn('Date Difference')
    def f_datedifference(self, node, ctx):
        self.only_scalar(node, ctx)
        args = self.a(node, ctx, 3, 4)
        self.helper('jsl_date_difference')
        return E(f'jsl_date_difference({", ".join(a.code for a in args)})', P_ATOM, 'num')

    @fn('Date Increment')
    def f_dateincrement(self, node, ctx):
        self.only_scalar(node, ctx)
        args = self.a(node, ctx, 2, 4)
        self.helper('jsl_date_increment')
        return E(f'jsl_date_increment({", ".join(a.code for a in args)})', P_ATOM, 'date')

    @fn('Short Date', 'Abbrev Date')
    def f_shortdate(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        return self.strftime(e, '%m/%d/%Y')

    @fn('Long Date')
    def f_longdate(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        return self.strftime(e, '%A, %B %d, %Y')

    @fn('MDYHMS')
    def f_mdyhms(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        return self.strftime(e, '%m/%d/%y %H:%M:%S')

    @fn('Informat', 'Parse Date')
    def f_informat(self, node, ctx):
        args = self.nargs(node, 1, 2)
        e = self.x(args[0], ctx)
        self.date_note(node)
        if len(args) == 2 and args[1].kind == 'str':
            f = DATE_FORMATS.get(args[1].value.lower()) or {'mmddyyyy': '%m%d%Y', 'ddmmyyyy': '%d%m%Y', 'yyyymmdd': '%Y%m%d'}.get(args[1].value.lower())
            if f:
                return E(f'pd.to_datetime({e.code}, format={lit(f)})', P_ATOM, 'series' if e.type == 'series' else 'date')
        self.note(node.line, 'info', f'{node.value}(): the format is left to pandas to recognise.', once=('informat', node.line))
        return E(f'pd.to_datetime({e.code})', P_ATOM, 'series' if e.type == 'series' else 'date')

    @fn('Is Leap Year')
    def f_isleapyear(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        return E(f'calendar.isleap(int({e.code}))', P_ATOM, 'bool')

    @fn('Days In Month')
    def f_daysinmonth(self, node, ctx):
        y, m = self.a(node, ctx, 2)
        return E(f'calendar.monthrange(int({y.code}), int({m.code}))[1]', P_ATOM, 'int')

    @fn('HP Time')
    def f_hptime(self, node, ctx):
        return E('time.perf_counter() * 1e6', P_MUL, 'num')

    @fn('Tick Seconds')
    def f_tickseconds(self, node, ctx):
        return E('time.time()', P_ATOM, 'num')

    # ---- the environment ------------------------------------------------------------------------------
    @fn('Get Environment Variable')
    def f_getenv(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        return E(f'os.environ.get({e.code}, "")', P_ATOM, 'str')

    @fn('Host Is')
    def f_hostis(self, node, ctx):
        (a,) = self.nargs(node, 1)
        v = (a.value if a.kind in ('str', 'name') else '').lower()
        if v.startswith('win'):
            return E('sys.platform.startswith("win")', P_ATOM, 'bool')
        if v.startswith('mac'):
            return E('sys.platform == "darwin"', P_CMP, 'bool')
        if v.startswith('linux'):
            return E('sys.platform.startswith("linux")', P_ATOM, 'bool')
        raise Unconvertible('Host Is() with this argument', node)

    @fn('Get Default Directory')
    def f_getcwd(self, node, ctx):
        return E('os.getcwd()', P_ATOM, 'str')

    @fn('File Exists', 'Directory Exists', 'Is File', 'Is Directory')
    def f_fileexists(self, node, ctx):
        (e,) = self.a(node, ctx, 1)
        f = {'fileexists': 'os.path.exists', 'isfile': 'os.path.isfile', 'directoryexists': 'os.path.isdir', 'isdirectory': 'os.path.isdir'}[node.key]
        self.path_note(node)
        return E(f'{f}({e.code})', P_ATOM, 'bool')

    @fn('Files In Directory')
    def f_filesindir(self, node, ctx):
        args = self.a(node, ctx, 1, 2)
        self.path_note(node)
        return E(f'sorted(os.listdir({args[0].code}))', P_ATOM, 'list')

    @fn('Load Text File')
    def f_loadtext(self, node, ctx):
        args = self.a(node, ctx, 1, -1)
        self.path_note(node)
        return E(f'open({args[0].code}, encoding="utf-8").read()', P_ATOM, 'str')

    def path_note(self, node):
        src = self.p.source(node)
        if '$' in src:
            self.note(node.line, 'warn', 'A path with a JMP path variable ($DESKTOP, $DOCUMENTS, $SAMPLE_DATA ...): Python does not know them; change the path.', once=('pathvar', node.line))


RANDOM_KEYS = tuple(k for k in FN if k.startswith('random'))
for _k in DISTRIBUTIONS:
    FN[_k] = _Lib.distribution
for _k in LOGNORMAL:
    FN[_k] = _Lib.lognormal
for _k in DISCRETE:
    FN[_k] = _Lib.discrete
for _k, _f in NUMERIC.items():
    FN[_k] = (lambda f: lambda self, node, ctx: self.numeric1(node, ctx, f))(_f)


# statements, by their functions' canonical names
STMT = {}


def stmt(*names):
    def deco(f):
        for n in names:
            STMT[jsl.name_key(n)] = f
        return f
    return deco


# calls that only affect JMP's session or windows: dropped, with one note each
HARMLESS = {
    'namesdefaulttohere': 'Names Default To Here(): the names of a Python script are its own already',
    'clearlog': 'Clear Log(): there is no log to clear', 'closelog': 'Close Log(): no log', 'openlog': 'Open Log(): no log',
    'wait': 'Wait(): it only lets JMP update its windows', 'beep': 'Beep()', 'speak': 'Speak()', 'caption': 'Caption(): a message window',
    'statusmsg': 'Status Msg(): the status bar', 'clearglobals': 'Clear Globals()', 'clearsymbols': 'Clear Symbols()',
    'deleteglobals': 'Delete Globals()', 'deletesymbols': 'Delete Symbols()', 'showglobals': 'Show Globals()', 'showsymbols': 'Show Symbols()',
    'lockglobals': 'Lock Globals()', 'unlockglobals': 'Unlock Globals()', 'locksymbols': 'Lock Symbols()', 'unlocksymbols': 'Unlock Symbols()',
    'watch': 'Watch()', 'debugbreak': 'Debug Break()', 'setplatformpreference': 'platform preferences', 'setplatformpreferences': 'platform preferences',
    'platformpreference': 'platform preferences', 'platformpreferences': 'platform preferences', 'preference': 'preferences', 'preferences': 'preferences',
    'setpreference': 'preferences', 'setpreferences': 'preferences', 'pref': 'preferences', 'prefs': 'preferences',
    'suppressformulaeval': 'Suppress Formula Eval(): formulas are computed once here', 'showcommands': 'Show Commands()',
    'showproperties': 'Show Properties()', 'closeall': 'Close All(): windows', 'savelog': 'Save Log()', 'deletenamespaces': 'namespaces',
    'showpreferences': 'Show Preferences()', 'revertmenu': 'Revert Menu()', 'settoolbarvisibility': 'toolbars',
}

# calls that make windows or display boxes, or work on reports: not converted
DISPLAY = {'newwindow', 'dialog', 'textbox', 'texteditbox', 'buttonbox', 'outlinebox', 'vlistbox', 'hlistbox', 'panelbox', 'graphbox', 'graph',
           'tabbox', 'tabpagebox', 'tablebox', 'numbercolbox', 'stringcolbox', 'checkbox', 'radiobox', 'combobox', 'listbox', 'collistbox',
           'textedit', 'numbereditbox', 'sliderbox', 'spacerbox', 'borderbox', 'scrollbox', 'lineupbox', 'ifbox', 'mousebox',
           'picturebox', 'journalbox', 'webbrowserbox', 'currentreport', 'currentwindow', 'currentjournal', 'report', 'window',
           'expraspicture', 'newimage', 'pickfile', 'pickdirectory', 'savefiledialog', 'webbrowser', 'web', 'mail', 'runprogram',
           'getwindow', 'getwindowlist', 'newproject', 'thisproject', 'mainmenu', 'datafeed', 'opendatafeed', 'schedule', 'newsqlquery',
           'createdatabaseconnection', 'opendatabase', 'executesql', 'sascontrol', 'sasconnect', 'sassubmit', 'rsubmit', 'rinit', 'rconnect',
           'pythonsubmit', 'pythoninit', 'pythonconnect', 'pythonexecute', 'matlabsubmit', 'loaddll', 'newnamespace', 'namespace',
           'defineclass', 'newobject', 'excerptbox', 'contextbox', 'datafiltercontextbox', 'treebox', 'treenode',
           'calendarbox', 'popupbox', 'iconbox', 'matrixbox', 'scenebox', 'scriptbox', 'sheetbox', 'splitterbox', 'hsplitterbox', 'vsplitterbox',
           'vcenterbox', 'hcenterbox', 'wraplistbox', 'rangesliderbox', 'datatablebox', 'numbercoleditbox', 'stringcoleditbox', 'textedit',
           'busylight', 'filtercolselector', 'globalbox', 'hierbox', 'pagebreakbox', 'plotcolbox', 'tablistbox', 'vscrollbox', 'hscrollbox',
           'multiplefileimport', 'googlesheetimport', 'httprequest', 'newhttprequest', 'socket', 'xmlparse', 'parsexml', 'jsontodatatable',
           'openhelp', 'dispatch', 'sendtoreport', 'sendtobygroup'}

# JSL expressions kept as data: not converted
META = {'expr': 'Expr(): a JSL expression kept as data', 'nameexpr': 'Name Expr(): a JSL expression kept as data',
        'evalexpr': 'Eval Expr(): building JSL expressions', 'parse': 'Parse(): JSL text run as JSL', 'arg': 'Arg(): the parts of a JSL expression',
        'argexpr': 'Arg Expr(): the parts of a JSL expression', 'head': 'Head(): the parts of a JSL expression', 'headname': 'Head Name(): the parts of a JSL expression',
        'narg': 'N Arg(): the parts of a JSL expression', 'nargexpr': 'N Arg(): the parts of a JSL expression', 'extractexpr': 'Extract Expr(): matching JSL expressions',
        'include': 'Include(): another JSL file, run as JSL', 'asname': 'As Name(): a name made while the script runs', 'asglobal': 'As Global()',
        'asscoped': 'As Scoped(): namespaces', 'derivative': 'Derivative(): symbolic differentiation of a JSL expression',
        'simplifyexpr': 'Simplify Expr(): symbolic algebra', 'invertexpr': 'Invert Expr(): symbolic algebra', 'evalinsertinto': 'Eval Insert Into()',
        'patmatch': 'Pat Match(): JSL\'s pattern matching', 'send': 'Send(): a message to an object made while the script runs',
        'jmpversion': 'JMP Version(): there is no JMP here', 'jmpproductname': 'JMP Product Name(): there is no JMP here',
        'getlog': 'Get Log(): there is no log', 'logcapture': None, 'throw': None}


class _Stmt(_Lib):
    # ---- the program --------------------------------------------------------------------------
    def run(self):
        self.prescan()
        for st in self.p.statements:
            self.statement(st, SCALAR)
        self.flush_comments(10 ** 9)

    def prescan(self):
        """Where every name is used, for the globals of functions."""
        self.uses = {}
        for st in self.p.statements:
            for n in st.walk():
                if n.kind in ('name', 'global') or (n.kind == 'call' and n.extra.get('key')):
                    self.uses.setdefault(n.key, []).append(n.start)

    def statement(self, node, ctx, tail=False):
        self.flush_comments(node.line)
        self.cur_line = node.line
        try:
            self.st(node, ctx, tail)
        except Unconvertible as u:
            self.not_converted(node, u.why)
        except Dynamic as d:
            self.not_converted(node, str(d))
        except NotVec:
            self.not_converted(node, 'a formula that cannot be written for whole columns')
        except Exception as e:  # a fault of the translator: this statement is lost, not the script
            if STRICT:
                raise
            self.not_converted(node, f'the translation failed here ({type(e).__name__}: {e}); please report the script', 'error')

    def body_stmts(self, body, ctx, tail=False):
        if body is None or body.kind == 'empty':
            return
        items = body.args if body.kind == 'glue' else [body]
        items = [i for i in items if i.kind != 'empty']
        for k, it in enumerate(items):
            self.statement(it, ctx, tail and k == len(items) - 1)

    def st(self, node, ctx, tail=False):
        k = node.kind
        if k == 'glue':
            for a in node.args:
                self.statement(a, ctx, tail and a is node.args[-1])
            return
        if k == 'empty':
            return
        if k == 'assign':
            return self.assign(node, ctx, tail)
        if k == 'postfix' and node.value in ('++', '--'):
            target = self.target(node.args[0], ctx)
            self.emit(f'{target} {"+" if node.value == "++" else "-"}= 1')
            if tail:
                self.emit(f'return {target}')
            return
        if k == 'send':
            e = self.send(node, ctx, want=tail)
            if tail and e is not None and e.code:
                self.emit(f'return {e.code}')
            return
        if k == 'call':
            key = node.key
            if key in HARMLESS and not node.extra.get('scope'):
                self.note(node.line, 'info', f'{HARMLESS[key]}: dropped.', once=('harmless', key))
                return
            if key in PLATFORMS:
                return self.launch(node, ctx, None, None)
            h = STMT.get(key)
            if h is not None:
                return h(self, node, ctx, tail)
            if key in DISPLAY:
                raise Unconvertible(f'{node.value}(): windows and display boxes have no Python counterpart here', node)
            if key in META and META[key]:
                raise Unconvertible(META[key], node)
        e = self.x(node, ctx)
        if tail:
            self.emit(f'return {e.code}')
        elif e.code:
            self.emit(e.code)

    # ---- assignments -------------------------------------------------------------------------
    def target(self, node, ctx):
        """The Python for something assigned to."""
        k = node.kind
        if k == 'name':
            if self.funcs and node.key in self.funcs[-1]['globals_all']:
                self.funcs[-1]['globals'].add(node.key)
            return self.py(node.key, node.value)
        if k == 'global':
            if self.funcs:
                self.funcs[-1]['globals'].add(node.key)
            return self.py(node.key, node.value)
        if k == 'scope' and node.args[0].kind == 'name' and node.args[0].key in ('here', 'global', 'local'):
            return self.py(node.key, node.value)
        ref = self.colref(node, ctx, quiet=True) if k in ('col', 'scope', 'call') else None
        if ref is not None:
            if ctx.mode == 'row' and ctx.frame is ref.frame:
                return f'{ref.frame.var}.loc[row, {ref.code}]'
            if ctx.mode == 'vec':
                return ref.series()
            raise Unconvertible('a column assigned outside For Each Row (JMP sets the current row only)', node)
        if k == 'subscript':
            base, subs = node.args[0], node.args[1:]
            if not subs or any(a.kind == 'empty' for a in subs):
                raise Unconvertible('a subscript without an index', node)
            ref = self.colref(base, ctx, quiet=True) if base.kind in ('col', 'scope', 'call', 'name') else None
            if ref is not None and len(subs) == 1:
                part = self.sub_part(subs[0], ctx)
                if part[0] == 'one':
                    return f'{ref.frame.var}.loc[{part[1]}, {ref.code}]'
                if part[0] == 'all':
                    return ref.series()
                return f'{ref.frame.var}.loc[{part[1]}, {ref.code}]'
            if base.kind == 'name' and self.typeof(base.key) == 'frame':
                fr = self.frame_of(base, ctx)
                if len(subs) == 2 and subs[1].kind == 'str':
                    return f'{fr.var}.loc[{self.idx(subs[0], ctx).code}, {lit(self.column_of(fr, subs[1].value, node))}]'
                if len(subs) == 2 and subs[1].kind == 'num':
                    return f'{fr.var}.iloc[{self.idx(subs[0], ctx).code}, {int(subs[1].value) - 1}]'
                raise Unconvertible('this data table subscript', node)
            b = self.x(base, ctx)
            if b.type == 'dict':
                return f'{par(b, P_ATOM)}[{self.x(subs[0], ctx).code}]'
            if b.type == 'matrix' or len(subs) == 2:
                return self.matrix_sub(b, subs, ctx, node).code
            part = self.sub_part(subs[0], ctx, allow_all=False)
            if part[0] in ('one', 'slice'):
                return f'{par(b, P_ATOM)}[{part[1]}]'
            raise Unconvertible('an assignment to several items of a list', node)
        if k == 'list':
            return ', '.join(self.target(a, ctx) for a in node.args if a.kind != 'empty')
        raise Unconvertible(f'assigning to {self.p.source(node)}', node)

    def assign(self, node, ctx, tail):
        op = node.value
        target, value = node.args
        if op == '=' and target.kind in ('name', 'global') and ctx.mode != 'vec':
            if self.assign_special(node, target, value, ctx, tail):
                return
        if op == '=' and target.kind == 'list' and value.kind == 'list':
            lhs = self.target(target, ctx)
            rhs = ', '.join(self.x(a, ctx).code for a in value.args if a.kind != 'empty')
            self.emit(f'{lhs} = {rhs}')
            for t, v in zip([a for a in target.args if a.kind == 'name'], value.args):
                self.settype(t.key, self.x(v, ctx))
            return
        # Selected(Row State()) = ... and the other row states
        if target.is_call('selected', 'excluded', 'hidden', 'labeled') and target.args and target.args[0].is_call('rowstate'):
            return self.rowstate_assign(target, value, ctx)
        v = self.x(value, ctx)
        lhs = self.target(target, ctx)
        if op == '=':
            self.emit(f'{lhs} = {v.code}')
            if target.kind in ('name', 'global'):
                self.settype(target.key, v)
        elif op in ('+=', '-=', '*=', '/='):
            cur = self.x(target, ctx) if target.kind in ('name', 'global') else E(lhs, P_ATOM)
            if op == '*=' and cur.type == 'matrix' and v.type == 'matrix':
                self.emit(f'{lhs} = {lhs} @ {par(v, P_MUL + 1)}')
            elif cur.type == 'date' and is_num_type(v.type) and op in ('+=', '-='):
                self.emit(f'{lhs} {op} pd.Timedelta(seconds={v.code})')
            elif cur.type == 'list' and op == '+=':
                raise Unconvertible('+= on a list: JSL adds to every item', node)
            else:
                self.emit(f'{lhs} {op} {v.code}')
            if target.kind == 'name' and cur.type in ('int',) and v.type == 'int' and op != '/=':
                self.settype(target.key, E('', P_ATOM, 'int'))
            elif target.kind == 'name' and op == '/=':
                self.settype(target.key, E('', P_ATOM, 'num'))
        elif op == '||=':
            cur = self.x(target, ctx) if target.kind == 'name' else E(lhs, P_ATOM)
            if 'matrix' in (cur.type, v.type):
                self.emit(f'{lhs} = np.hstack([{lhs}, {v.code}])')
            else:
                self.emit(f'{lhs} += {v.code}')
        elif op == '|/=':
            self.emit(f'{lhs} = np.vstack([{lhs}, {v.code}])')
        else:
            raise Unconvertible(f'the assignment {op}', node)
        if tail:
            self.emit(f'return {lhs}')

    def assign_special(self, node, target, value, ctx, tail):
        """name = <something that is not a plain value>: a function, a table,
        a column, a launch, If with statements in its branches."""
        key = target.key
        var = self.py(key, target.value)
        if value.is_call('function'):
            self.define(target, value)
            return True
        if value.kind == 'call' and value.key in PLATFORMS:
            self.launch(value, ctx, None, target)
            return True
        if value.kind == 'send' and self.is_launch_send(value):
            self.launch(value.args[1], ctx, value.args[0], target)
            return True
        fr = self.table_value(value, ctx, var)
        if fr is not None:
            self.vtypes[key] = E(None, P_ATOM, 'frame', fr)
            if tail:
                self.emit(f'return {var}')
            return True
        if value.kind == 'send':
            e = self.send(value, ctx, want=True, target=var)
            if e is None:
                return True
            if e.type == 'platform':
                self.vtypes[key] = E(None, P_ATOM, 'platform', e.info)
                return True
            if e.type == 'frame' and isinstance(e.info, Frame) and e.code == e.info.var:
                if e.info.var != var:
                    self.emit(f'{var} = {e.code}')
                self.vtypes[key] = E(None, P_ATOM, 'frame', e.info)
                return True
            if e.type == 'col':
                self.emit(f'{var} = {lit(e.info.name) if e.info.name else e.info.code}   # a column of {e.info.frame.var}')
                self.vtypes[key] = E(None, P_ATOM, 'col', e.info)
                return True
            self.emit(f'{var} = {e.code}')
            self.settype(key, e)
            if tail:
                self.emit(f'return {var}')
            return True
        ref = self.colref(value, ctx, quiet=True) if value.is_call('column', 'ascolumn') else None
        if ref is not None:
            self.emit(f'{var} = {ref.code}   # a column of {ref.frame.var}')
            self.vtypes[key] = E(None, P_ATOM, 'col', ref)
            return True
        if value.is_call('newcolumn'):
            ref = self.new_column(value, self.current_frame(value), ctx)
            self.emit(f'{var} = {ref.code}   # a column of {ref.frame.var}')
            self.vtypes[key] = E(None, P_ATOM, 'col', ref)
            return True
        if value.is_call('if', 'ifmz') and any(v.kind == 'glue' for _, v in self.branches(value)[0]) or (value.is_call('if', 'ifmz') and len(value.args) > 7):
            self.assign_branches(target, value, ctx, tail)
            return True
        return False

    def assign_branches(self, target, value, ctx, tail):
        """x = If(c1, a; b, c2, d, e): the last value of each branch assigned."""
        pairs, other = self.branches(value)
        var = self.py(target.key, target.value)
        for i, (c, body) in enumerate(pairs):
            self.emit(f'{"if" if i == 0 else "elif"} {self.x(c, ctx.but(cond=True)).code}:')
            with self.block():
                self.branch_value(var, body, ctx)
        self.emit('else:')
        with self.block():
            if other is None:
                self.emit(f'{var} = np.nan')
            else:
                self.branch_value(var, other, ctx)
        if tail:
            self.emit(f'return {var}')

    def branch_value(self, var, body, ctx):
        items = body.args if body.kind == 'glue' else [body]
        for it in items[:-1]:
            self.statement(it, ctx)
        last = items[-1]
        e = self.x(last, ctx)
        self.emit(f'{var} = {e.code}')

    # ---- control flow ---------------------------------------------------------------------------
    def cond(self, node, ctx):
        if node.kind == 'glue':
            raise Unconvertible('a condition of several expressions', node)
        return self.x(node, ctx.but(cond=True)).code

    @stmt('If', 'IfMZ')
    def s_if(self, node, ctx, tail):
        pairs, other = self.branches(node)
        if not pairs:
            raise Unconvertible('If() without a condition', node)
        for i, (c, body) in enumerate(pairs):
            self.emit(f'{"if" if i == 0 else "elif"} {self.cond(c, ctx)}:')
            with self.block():
                self.body_stmts(body, ctx, tail)
        if other is not None:
            self.emit('else:')
            with self.block():
                self.body_stmts(other, ctx, tail)

    @stmt('Match', 'MatchMZ')
    def s_match(self, node, ctx, tail):
        args = self.nargs(node, 3, -1)
        subj = self.x(args[0], ctx)
        code = subj.code
        if not re.fullmatch(r'[A-Za-z_][\w.]*', code):
            code = self.fresh('value')
            self.emit(f'{code} = {subj.code}')
        rest = args[1:]
        pairs = [(rest[i], rest[i + 1]) for i in range(0, len(rest) - 1, 2)]
        other = rest[-1] if len(rest) % 2 == 1 else None
        for i, (v, body) in enumerate(pairs):
            ve = self.x(v, ctx)
            test = f'pd.isna({code})' if v.kind == 'missing' else f'{code} == {par(ve, P_CMP + 1)}'
            self.emit(f'{"if" if i == 0 else "elif"} {test}:')
            with self.block():
                self.body_stmts(body, ctx, tail)
        if other is not None:
            self.emit('else:')
            with self.block():
                self.body_stmts(other, ctx, tail)

    @stmt('Choose')
    def s_choose(self, node, ctx, tail):
        args = self.nargs(node, 2, -1)
        subj = self.x(args[0], ctx)
        code = subj.code
        if not re.fullmatch(r'[A-Za-z_][\w.]*', code):
            code = self.fresh('choice')
            self.emit(f'{code} = {subj.code}')
        for i, body in enumerate(args[1:-1]):
            self.emit(f'{"if" if i == 0 else "elif"} {code} == {i + 1}:')
            with self.block():
                self.body_stmts(body, ctx, tail)
        self.emit('else:')
        with self.block():
            self.body_stmts(args[-1], ctx, tail)

    def assigned_in(self, body):
        """The names the body assigns to, or changes in place."""
        out = set()
        if body is None:
            return out
        for n in body.walk():
            if n.kind == 'assign':
                t = n.args[0]
                if t.kind in ('name', 'global'):
                    out.add(t.key)
                if t.kind == 'list':
                    out.update(a.key for a in t.args if a.kind == 'name')
                if t.kind == 'subscript' and t.args[0].kind == 'name':
                    out.add(t.args[0].key)
            elif n.kind == 'postfix' and n.value in ('++', '--') and n.args[0].kind == 'name':
                out.add(n.args[0].key)
            elif n.kind == 'call' and n.key in ('insertinto', 'removefrom', 'concatto', 'substituteinto', 'shiftinto', 'reverseinto', 'sortlistinto', 'addto', 'subtractto', 'multiplyto', 'divideto', 'postincrement', 'postdecrement', 'vconcatto') and n.args and n.args[0].kind == 'name':
                out.add(n.args[0].key)
            elif n.kind == 'send' and n.args[0].kind == 'name':
                out.add(n.args[0].key)
            elif n.kind == 'call' and n.key in ('for', 'foreach', 'summation', 'product') and n.args:
                a0 = n.args[0]
                if a0.kind == 'assign' and a0.args[0].kind == 'name':
                    out.add(a0.args[0].key)
        return out

    def counting(self, init, cond, incr, body, ctx):
        """For(i = a, i <= b, i++, ...) as range(); None when it is not that."""
        if init.kind != 'assign' or init.value != '=' or init.args[0].kind != 'name':
            return None
        key = init.args[0].key
        if cond.kind != 'cmp' or len(cond.value) != 1:
            return None
        op = cond.value[0]
        a, b = cond.args
        flip = {'<': '>', '<=': '>=', '>': '<', '>=': '<='}
        if a.kind == 'name' and a.key == key:
            bound = b
        elif b.kind == 'name' and b.key == key and op in flip:
            bound, op = a, flip[op]
        else:
            return None
        if op not in ('<', '<=', '>', '>='):
            return None
        step = None
        if incr.kind == 'postfix' and incr.args[0].kind == 'name' and incr.args[0].key == key:
            step = 1 if incr.value == '++' else -1
        elif incr.kind == 'assign' and incr.args[0].kind == 'name' and incr.args[0].key == key:
            v = incr.args[1]
            if incr.value in ('+=', '-=') and v.kind == 'num' and float(v.value).is_integer():
                step = int(v.value) * (1 if incr.value == '+=' else -1)
            elif incr.value == '=' and v.kind == 'binop' and v.value in ('+', '-') and v.args[0].kind == 'name' and v.args[0].key == key and v.args[1].kind == 'num' and float(v.args[1].value).is_integer():
                step = int(v.args[1].value) * (1 if v.value == '+' else -1)
        elif incr.is_call('postincrement', 'postdecrement') and incr.args and incr.args[0].kind == 'name' and incr.args[0].key == key:
            step = 1 if incr.key == 'postincrement' else -1
        if not step or (op in ('<', '<=') and step < 0) or (op in ('>', '>=') and step > 0):
            return None
        changed = self.assigned_in(body)
        names_in_bound = {n.key for n in bound.walk() if n.kind == 'name'}
        if key in changed or names_in_bound & changed:
            return None
        if any(n.kind == 'call' and n.key not in ('nitems', 'nrows', 'nrow', 'ncols', 'ncol', 'length', 'min', 'max', 'minimum', 'maximum', 'floor', 'ceiling', 'round') for n in bound.walk()):
            return None
        start = init.args[1]
        if start.kind == 'num' and not float(start.value).is_integer():
            return None
        if bound.kind == 'num' and not float(bound.value).is_integer():
            return None
        se = self.x(start, ctx)
        be = self.x(bound, ctx)
        if se.type not in ('int', 'unknown', 'num') or be.type not in ('int', 'num', 'unknown', 'bool'):
            return None
        wrap = be.type != 'int'
        if op == '<=':
            end = f'int({be.code}) + 1' if wrap else self.plus1(bound, ctx)
        elif op == '<':
            end = f'math.ceil({be.code})' if wrap else be.code
        elif op == '>=':
            end = f'int({be.code}) - 1' if wrap else self._minus1(bound, ctx)
        else:
            end = f'math.floor({be.code})' if wrap else be.code
        start_code = se.code if se.type == 'int' else f'int({se.code})'
        shift = self.only_subscripts(body, key) and step == 1
        if shift:
            start_code = self._minus(start_code)
            end = self._minus(end)
        if step == 1:
            rng = f'range({end})' if start_code == '0' else f'range({start_code}, {end})'
        else:
            rng = f'range({start_code}, {end}, {step})'
        return key, init.args[0], rng, shift

    def _minus1(self, bound, ctx):
        e, k = self.offset(bound, ctx)
        return self._plus(e, k - 1).code

    @staticmethod
    def _minus(code):
        """code - 1, folded."""
        if re.fullmatch(r'-?\d+', code):
            return str(int(code) - 1)
        m = re.fullmatch(r'(.*) \+ (\d+)', code)
        if m:
            k = int(m.group(2)) - 1
            return m.group(1) if k == 0 else f'{m.group(1)} + {k}'
        return f'{code} - 1'

    def only_subscripts(self, body, key):
        """True when the counter is used only as a subscript of a list, a
        matrix or a column (so it can count from 0)."""
        ok = [True]
        seen = [False]

        def base_ok(b):
            if b.kind in ('col', 'scope'):
                return True
            if b.kind == 'call' and b.key in ('column', 'ascolumn'):
                return True
            if b.kind == 'name':
                t = self.typeof(b.key)
                if t in ('list', 'matrix', 'rows', 'frame', 'col'):
                    return True
                if t == 'unknown' and b.key not in self.vtypes and self.cur is not None and self.cur.col(b.value):
                    return True
            return False

        def visit(n, direct=False):
            if not ok[0]:
                return
            if n.kind == 'name' and n.key == key:
                seen[0] = True
                if not direct:
                    ok[0] = False
                return
            if n.kind == 'subscript':
                base, subs = n.args[0], n.args[1:]
                visit(base)
                for s in subs:
                    if s.kind == 'name' and s.key == key:
                        seen[0] = True
                        if not base_ok(base):
                            ok[0] = False
                    else:
                        visit(s)
                return
            if n.kind == 'call' and n.key == 'function':
                return
            for a in n.args:
                if isinstance(a, jsl.Node):
                    visit(a)
            d = n.extra.get('default')
            if isinstance(d, jsl.Node):
                visit(d)
        visit(body)
        return ok[0] and seen[0]

    @stmt('For')
    def s_for(self, node, ctx, tail):
        args = node.args
        if len(args) != 4:
            raise Unconvertible('For() takes an initialisation, a condition, an increment and a body', node)
        init, cond, incr, body = args
        rng = self.counting(init, cond, incr, body, ctx)
        if rng is not None:
            key, vnode, code, shift = rng
            var = self.py(key, vnode.value)
            self.emit(f'for {var} in {code}:')
            self.vtypes[key] = E(var, P_ATOM, 'int')
            if shift:
                self.shifted.add(key)
            self.loops.append({'incr': []})
            with self.block():
                self.body_stmts(body, ctx)
            self.loops.pop()
            self.shifted.discard(key)
            return
        self.statement(init, ctx)
        cc = 'True' if cond.kind == 'empty' else self.cond(cond, ctx)
        incr_nodes = [] if incr.kind == 'empty' else (incr.args if incr.kind == 'glue' else [incr])
        self.emit(f'while {cc}:')
        self.loops.append({'incr': incr_nodes})
        with self.block():
            self.body_stmts(body, ctx)
            for n in incr_nodes:
                self.statement(n, ctx)
        self.loops.pop()

    @stmt('While')
    def s_while(self, node, ctx, tail):
        a = node.args
        if len(a) != 2:
            raise Unconvertible('While() takes a condition and a body', node)
        self.emit(f'while {self.cond(a[0], ctx)}:')
        self.loops.append({'incr': []})
        with self.block():
            self.body_stmts(a[1], ctx)
        self.loops.pop()

    @stmt('For Each', 'Filter Each', 'Transform Each')
    def s_foreach(self, node, ctx, tail):
        args = [a for a in node.args]
        if len(args) not in (3, 4) or args[0].kind != 'list':
            raise Unconvertible(f'{node.value}() takes {{names}}, a container, (locals and) a body', node)
        names, container, body = args[0], args[1], args[-1]
        if node.key in ('filtereach', 'transformeach'):
            raise Unconvertible(f'{node.value}() as a statement: its result is not used', node)
        header, types = self.each_header(names, container, ctx, node)
        if len(args) == 4 and args[2].kind == 'list':
            for it in args[2].args:
                if it.kind == 'assign':
                    self.statement(it, ctx)
        self.emit(f'for {header}:')
        for k, t in types.items():
            self.vtypes[k] = E(None, P_ATOM, t)
        self.loops.append({'incr': []})
        with self.block():
            self.body_stmts(body, ctx)
        self.loops.pop()

    def each_header(self, names, container, ctx, node):
        """The 'target in iterable' of a For Each (and the loop names' types)."""
        # every name of the loop starts unknown: an earlier loop's kind does not carry over
        types = {n.key: 'unknown' for n in names.walk() if n.kind == 'name'}
        if container.is_call('across'):
            parts = [a for a in container.args if not a.is_call('count')]
            if any(a.is_call('count') for a in container.args):
                raise Unconvertible('Across() with Count()', node)
            if len(parts) == 1 and parts[0].kind == 'list':
                parts = parts[0].args
            iters = [self.x(p, ctx).code for p in parts]
            it = f'zip({", ".join(iters)})'
            first = names.args[0] if names.args else None
            if first is None or first.kind != 'list':
                raise Unconvertible('For Each() over Across() takes a list of names', node)
            target = ', '.join(self.py(a.key, a.value) for a in first.args)
            idx = names.args[1] if len(names.args) > 1 else None
            self.note(node.line, 'info', 'Across(): the containers are walked together with zip(), which stops at the shortest.', once='across')
            self.each_item = f'({target})'
            if idx is not None:
                return f'{self.py(idx.key, idx.value)}, ({target}) in enumerate({it}, start=1)', types
            return f'{target} in {it}', types
        if container.kind == 'binop' and container.value == '::':
            it = f'range({self.x(container.args[0], ctx).code}, {self.plus1(container.args[1], ctx)})'
            ce = E(it, P_ATOM, 'rows')
        else:
            ce = self.x(container, ctx)
            it = ce.code
            if ce.type == 'matrix':
                it = f'{par(ce, P_ATOM)}.flat'
            elif ce.type == 'series':
                it = f'{par(ce, P_ATOM)}'
        items = [a for a in names.args if a.kind != 'empty']
        if any(a.kind not in ('name', 'list') for a in items) or any(b.kind != 'name' for a in items if a.kind == 'list' for b in a.args):
            raise Unconvertible(f'{node.value}(): the loop\'s names must be names', node)
        if not items:
            idx = None
            target = '_'
        elif items[0].kind == 'list':
            kv = [a for a in items[0].args if a.kind == 'name']
            if len(kv) != 2:
                raise Unconvertible('For Each() with {{key, value}} takes two names', node)
            if ce.type == 'matrix':
                raise Unconvertible('For Each() over a matrix with {row, column}', node)
            it = f'sorted({ce.code}.items())'
            target = f'{self.py(kv[0].key, kv[0].value)}, {self.py(kv[1].key, kv[1].value)}'
            idx = items[1] if len(items) > 1 else None
        else:
            v = items[0]
            target = self.py(v.key, v.value)
            if ce.type == 'dict':
                it = f'sorted({ce.code})'
                self.note(node.line, 'info', 'For Each over an associative array with one name: here the name takes the keys, in JMP\'s (sorted) order.', once=('eachdict', node.line))
            if isinstance(ce.info, dict) and ce.info.get('columns'):
                types[v.key] = 'str'
            elif ce.type == 'rows':
                types[v.key] = 'int'
            idx = items[1] if len(items) > 1 else None
        self.each_item = target
        if idx is not None and idx.kind == 'name':
            types[idx.key] = 'int'
            return f'{self.py(idx.key, idx.value)}, {target} in enumerate({it}, start=1)', types
        return f'{target} in {it}', types

    @stmt('Break')
    def s_break(self, node, ctx, tail):
        self.emit('break')

    @stmt('Continue')
    def s_continue(self, node, ctx, tail):
        if self.loops:
            for n in self.loops[-1]['incr']:
                self.statement(n, ctx)
        self.emit('continue')

    @stmt('Return')
    def s_return(self, node, ctx, tail):
        es = [self.x(a, ctx) for a in node.args if a.kind != 'empty']
        if not self.funcs:
            raise Unconvertible('Return() outside a function', node)
        if not es:
            self.emit('return None')
        elif len(es) == 1:
            self.emit(f'return {es[0].code}')
        else:
            self.emit(f'return [{", ".join(e.code for e in es)}]')

    @stmt('Stop')
    def s_stop(self, node, ctx, tail):
        self.emit('raise SystemExit("Stop()")')

    @stmt('Throw')
    def s_throw(self, node, ctx, tail):
        es = [self.x(a, ctx) for a in node.args if a.kind != 'empty']
        self.emit(f'raise RuntimeError({es[0].code if es else ""})')

    @stmt('Try')
    def s_try(self, node, ctx, tail):
        args = node.args
        if not args:
            return
        body = args[0]
        handler = args[1] if len(args) > 1 else None
        uses = handler is not None and any(n.is_name('exception_msg') for n in handler.walk())
        self.note(node.line, 'info', 'Try(): JSL catches the errors JMP raises and Throw(); the Python except catches any exception' + (', and exception_msg is the Python exception (JSL gives a list with the message).' if uses else '.'), once=('try', uses))
        self.emit('try:')
        with self.block():
            self.body_stmts(body, ctx, tail)
        if uses:
            name = self.py('exception_msg', 'exception_msg')
            self.emit(f'except Exception as {name}:')
        else:
            self.emit('except Exception:')
        with self.block():
            self.body_stmts(handler, ctx, tail)

    @stmt('Local', 'Local Here')
    def s_local(self, node, ctx, tail):
        args = node.args
        if node.key == 'localhere':
            self.body_stmts(args[0] if args else None, ctx, tail)
            return
        if not args:
            return
        if args[0].kind == 'list':
            for it in args[0].args:
                if it.kind == 'assign':
                    self.statement(it, ctx)
            self.note(node.line, 'info', 'Local(): Python has no block of local names; they are ordinary names here.', once='local')
            self.body_stmts(args[1] if len(args) > 1 else None, ctx, tail)
        else:
            self.body_stmts(args[0], ctx, tail)

    @stmt('Log Capture')
    def s_logcapture(self, node, ctx, tail):
        self.body_stmts(node.args[0] if node.args else None, ctx, tail)

    @stmt('Glue', 'First')
    def s_glue(self, node, ctx, tail):
        for k, a in enumerate(node.args):
            self.statement(a, ctx, tail and k == len(node.args) - 1)

    @stmt('Eval')
    def s_eval(self, node, ctx, tail):
        args = self.nargs(node, 1)
        a = args[0]
        if a.is_call('parse') and len(a.args) == 1 and a.args[0].kind == 'str':
            prog = jsl.parse(a.args[0].value)
            if any(q.severity == 'error' for q in prog.problems) or not prog.statements:
                raise Unconvertible('Eval(Parse("...")) of text that is not valid JSL', node)
            self.note(node.line, 'info', 'Eval(Parse("...")): the text is converted as JSL where it stands.', once=('evalparse', node.line))
            for s in prog.statements:
                s.line = node.line
                s.start, s.end = node.start, node.end
                for n in s.walk():
                    n.line = node.line
                    n.start, n.end = node.start, node.end
                self.st(s, ctx)
            return
        if a.is_call('expr') and len(a.args) == 1:
            self.body_stmts(a.args[0], ctx, tail)
            return
        if a.kind == 'name' and self.typeof(a.key) == 'list':
            return
        raise Unconvertible('Eval() of an expression made while the script runs: JSL expressions as data have no translation', node)

    @stmt('Random Reset')
    def s_randomreset(self, node, ctx, tail):
        (seed,) = self.a(node, ctx, 1)
        if self.rng is None:
            self.rng = 'rng'
            self.taken.add('rng')
            self.note(node.line, 'info', 'Random Reset(): numpy\'s generator is seeded here; its streams differ from JMP\'s, so the values are not the ones JMP draws.', once='random')
        self.emit(f'{self.rng} = np.random.default_rng({seed.code})')

    # ---- output ----------------------------------------------------------------------------------------
    @stmt('Show')
    def s_show(self, node, ctx, tail):
        for a in node.args:
            if a.kind == 'empty':
                continue
            if a.kind == 'str':
                self.emit(f'print({lit(json.dumps(a.value, ensure_ascii=False))})')
                continue
            e = self.x(a, ctx)
            label = show_label(self.p.source(a))
            self.emit(f'print({lit(label + " =")}, {e.code})')

    @stmt('Print')
    def s_print(self, node, ctx, tail):
        for a in node.args:
            if a.kind != 'empty':
                self.emit(f'print({self.x(a, ctx).code})')

    @stmt('Print Matrix')
    def s_printmatrix(self, node, ctx, tail):
        a = self.nargs(node, 1, -1)[0]
        self.emit(f'print({self.x(a, ctx).code})')

    @stmt('Write')
    def s_write(self, node, ctx, tail):
        args = [a for a in node.args if a.kind != 'empty']
        if not args:
            return
        end = ''
        if args[-1].kind == 'str' and args[-1].value.endswith('\n'):
            last = args[-1].value[:-1]
            parts = [self.x(a, ctx).code for a in args[:-1]] + ([lit(last)] if last else [])
            end = None
        else:
            parts = [self.x(a, ctx).code for a in args]
        if len(parts) == 1 and args[0].kind != 'str' and self.x(args[0], ctx).type in ('num', 'unknown'):
            self.helper('jsl_char')
            parts = [f'jsl_char({parts[0]})']
        sep = ', sep=""' if len(parts) > 1 else ''
        if end is None:
            self.emit(f'print({", ".join(parts)}{sep})')
        else:
            self.emit(f'print({", ".join(parts)}{sep}, end="")')

    # ---- lists in place ----------------------------------------------------------------------------------
    def lvalue(self, node):
        """The first argument of a function that changes it in place must be a variable."""
        a = node.args[0] if node.args else None
        if a is None or a.kind not in ('name', 'global', 'scope', 'subscript'):
            raise Unconvertible(f'{node.value}() of something that is not a variable', node)

    def changed(self, node):
        """A list changed in place: what was known of its items no longer holds."""
        if node.kind == 'name' and node.key in self.vtypes and self.vtypes[node.key].type == 'list':
            self.vtypes[node.key] = E(None, P_ATOM, 'list')

    @stmt('Insert Into')
    def s_insertinto(self, node, ctx, tail):
        self.changed(node.args[0]) if node.args else None
        self.lvalue(node)
        args = self.nargs(node, 2, 3)
        dst = self.x(args[0], ctx)
        if dst.type == 'dict' and len(args) == 3:
            self.emit(f'{par(dst, P_ATOM)}[{self.x(args[1], ctx).code}] = {self.x(args[2], ctx).code}')
            return
        item = self.x(args[1], ctx)
        if dst.type == 'matrix':
            self.emit(f'{dst.code} = np.append({dst.code}, {item.code})')
            return
        if len(args) == 3:
            p = self.idx(args[2], ctx)
            if item.type == 'list':
                self.emit(f'{par(dst, P_ATOM)}[{p.code}:{p.code}] = {item.code}')
            else:
                self.emit(f'{par(dst, P_ATOM)}.insert({p.code}, {item.code})')
        elif item.type == 'list':
            self.emit(f'{par(dst, P_ATOM)}.extend({item.code})')
        else:
            self.emit(f'{par(dst, P_ATOM)}.append({item.code})')

    @stmt('Remove From')
    def s_removefrom(self, node, ctx, tail):
        self.changed(node.args[0]) if node.args else None
        self.lvalue(node)
        args = self.nargs(node, 2, 3)
        dst = self.x(args[0], ctx)
        if dst.type == 'dict':
            self.emit(f'{par(dst, P_ATOM)}.pop({self.x(args[1], ctx).code}, None)')
            return
        p = self.idx(args[1], ctx)
        if len(args) == 3:
            n = self.x(args[2], ctx)
            end = str(int(p.code) + int(n.code)) if p.code.isdigit() and n.code.isdigit() else f'{par(p, P_ADD)} + {par(n, P_ADD + 1)}'
            self.emit(f'del {par(dst, P_ATOM)}[{p.code}:{end}]')
        else:
            self.emit(f'del {par(dst, P_ATOM)}[{p.code}]')

    @stmt('Reverse Into')
    def s_reverseinto(self, node, ctx, tail):
        (e,) = self.a(node, ctx, 1)
        self.emit(f'{par(e, P_ATOM)}.reverse()')

    @stmt('Sort List Into')
    def s_sortlistinto(self, node, ctx, tail):
        (e,) = self.a(node, ctx, 1)
        self.emit(f'{par(e, P_ATOM)}.sort()')

    @stmt('Shift Into')
    def s_shiftinto(self, node, ctx, tail):
        args = self.a(node, ctx, 1, 2)
        n = args[1].code if len(args) == 2 else '1'
        d = par(args[0], P_ATOM)
        self.emit(f'{d}[:] = {d}[{n}:] + {d}[:{n}]')

    @stmt('Substitute Into')
    def s_substituteinto(self, node, ctx, tail):
        args = self.nargs(node, 3, -1)
        target = self.target(args[0], ctx)
        rest = jsl.Node('call', 'Substitute', args, line=node.line, start=node.start, end=node.end, extra={'key': 'substitute'})
        self.emit(f'{target} = {self.x(rest, ctx).code}')

    def _in_place(self, node, ctx, op):
        args = self.nargs(node, 2, -1)
        target = self.target(args[0], ctx)
        for a in args[1:]:
            v = self.x(a, ctx)
            if op == '||=':
                cur = self.x(args[0], ctx)
                if 'matrix' in (cur.type, v.type):
                    self.emit(f'{target} = np.hstack([{target}, {v.code}])')
                else:
                    self.emit(f'{target} += {v.code}')
            elif op == '|/=':
                self.emit(f'{target} = np.vstack([{target}, {v.code}])')
            else:
                self.emit(f'{target} {op} {v.code}')

    @stmt('Concat To')
    def s_concatto(self, node, ctx, tail):
        self._in_place(node, ctx, '||=')

    @stmt('V Concat To')
    def s_vconcatto(self, node, ctx, tail):
        self._in_place(node, ctx, '|/=')

    @stmt('Add To')
    def s_addto(self, node, ctx, tail):
        self._in_place(node, ctx, '+=')

    @stmt('Subtract To')
    def s_subtractto(self, node, ctx, tail):
        self._in_place(node, ctx, '-=')

    @stmt('Multiply To')
    def s_multiplyto(self, node, ctx, tail):
        self._in_place(node, ctx, '*=')

    @stmt('Divide To')
    def s_divideto(self, node, ctx, tail):
        self._in_place(node, ctx, '/=')

    @stmt('Post Increment', 'PostIncrement')
    def s_postinc(self, node, ctx, tail):
        (a,) = self.nargs(node, 1)
        self.emit(f'{self.target(a, ctx)} += 1')

    @stmt('Post Decrement', 'PostDecrement')
    def s_postdec(self, node, ctx, tail):
        (a,) = self.nargs(node, 1)
        self.emit(f'{self.target(a, ctx)} -= 1')

    @stmt('Assign')
    def s_assignfn(self, node, ctx, tail):
        a, b = self.nargs(node, 2)
        self.assign(jsl.Node('assign', '=', [a, b], line=node.line, start=node.start, end=node.end), ctx, tail)

    # ---- files ---------------------------------------------------------------------------------------------
    @stmt('Set Default Directory')
    def s_chdir(self, node, ctx, tail):
        (e,) = self.a(node, ctx, 1)
        self.path_note(node)
        self.emit(f'os.chdir({e.code})')

    @stmt('Create Directory')
    def s_mkdir(self, node, ctx, tail):
        (e,) = self.a(node, ctx, 1)
        self.path_note(node)
        self.emit(f'os.makedirs({e.code}, exist_ok=True)')

    @stmt('Delete File')
    def s_rm(self, node, ctx, tail):
        e = self.a(node, ctx, 1, 2)[0]
        self.path_note(node)
        self.emit(f'os.remove({e.code})')

    @stmt('Save Text File')
    def s_savetext(self, node, ctx, tail):
        args = self.nargs(node, 2, -1)
        p, text = self.x(args[0], ctx), self.x(args[1], ctx)
        mode = 'a' if any(a.is_call('mode') and a.args and a.args[0].kind == 'str' and a.args[0].value.lower() == 'append' for a in args[2:]) else 'w'
        self.path_note(node)
        self.emit(f'with open({p.code}, {lit(mode)}, encoding="utf-8") as f:')
        with self.block():
            self.emit(f'f.write({text.code})')

    # ---- functions --------------------------------------------------------------------------------------------
    def define(self, target, fnode):
        args = fnode.args
        if not args or args[0].kind != 'list':
            raise Unconvertible('Function() takes a list of arguments first', fnode)
        params = args[0]
        locals_node = args[1] if len(args) >= 3 and args[1].kind == 'list' else None
        body = args[-1] if len(args) >= 2 else None
        name = self.py(target.key, target.value)
        self.vtypes[target.key] = E(name, P_ATOM, 'func')
        plist, pkeys = [], set()
        for p in params.args:
            if p.kind == 'name':
                # after an optional argument, Python needs a default for every one
                late = any('=' in x for x in plist)
                plist.append(self.py(p.key, p.value) + ('=None' if late else ''))
                pkeys.add(p.key)
                if late:
                    self.note(fnode.line, 'info', f'{target.value}: an argument without a default after one with a default gets the default None here (Python needs it).', once=('lateparam', fnode.line))
            elif p.kind == 'assign' and p.args[0].kind == 'name':
                d = self.x(p.args[1], SCALAR)
                plist.append(f'{self.py(p.args[0].key, p.args[0].value)}={d.code}')
                pkeys.add(p.args[0].key)
            elif p.kind != 'empty':
                raise Unconvertible('a function argument of this kind', fnode)
        default_local = False
        lkeys = set()
        inits = []
        if locals_node is not None:
            for it in locals_node.args:
                if it.kind == 'name' and it.key == 'defaultlocal':
                    default_local = True
                elif it.kind == 'name':
                    lkeys.add(it.key)
                elif it.kind == 'assign' and it.args[0].kind == 'name':
                    lkeys.add(it.args[0].key)
                    inits.append(it)
        assigned = self.assigned_in(body) - pkeys - lkeys
        outside = set()
        if not default_local:
            for k in assigned:
                if any(not (fnode.start <= pos < fnode.end) for pos in self.uses.get(k, [])):
                    outside.add(k)
        saved = dict(self.vtypes)
        if self.ind == 0 and self.body and self.body[-1][1]:
            self.emit('')
        self.emit(f'def {name}({", ".join(plist)}):')
        self.funcs.append({'name': name, 'globals_all': outside, 'globals': set()})
        for k in pkeys | lkeys:
            self.vtypes[k] = E(None, P_ATOM, 'unknown')
        with self.block():
            mark = len(self.body)
            for it in inits:
                self.statement(it, SCALAR)
            self.body_stmts(body, SCALAR, tail=True)
            g = sorted(self.funcs[-1]['globals'] | {k for k in outside})
            if g:
                self.body.insert(mark, (self.ind, f'global {", ".join(self.py(k) for k in g)}'))
        self.funcs.pop()
        if self.ind == 0:
            self.emit('')
        for k in list(self.vtypes):
            if k in pkeys | lkeys and k in saved:
                self.vtypes[k] = saved[k]
            elif k in pkeys | lkeys:
                del self.vtypes[k]
        self.vtypes[target.key] = E(name, P_ATOM, 'func')

    @fn('Function')
    def f_function(self, node, ctx):
        args = node.args
        if not args or args[0].kind != 'list' or len(args) > 2:
            raise Unconvertible('a Function() that is not assigned to a name', node)
        body = args[-1]
        if body.kind in ('glue', 'assign') or (body.kind == 'call' and body.key in STMT):
            raise Unconvertible('a Function() of statements that is not assigned to a name', node)
        names = [self.py(p.key, p.value) for p in args[0].args if p.kind == 'name']
        saved = dict(self.vtypes)
        for p in args[0].args:
            if p.kind == 'name':
                self.vtypes[p.key] = E(None, P_ATOM, 'unknown')
        e = self.x(body, ctx)
        self.vtypes = saved
        return E(f'lambda {", ".join(names)}: {e.code}', P_IF - 1 if P_IF > 1 else 0, 'func')

    @fn('Transform Each', 'Filter Each')
    def f_transformeach(self, node, ctx):
        self.only_scalar(node, ctx)
        args = [a for a in node.args if a.kind != 'empty']
        if len(args) not in (3, 4) or args[0].kind != 'list':
            raise Unconvertible(f'{node.value}() takes {{names}}, a container and a body', node)
        names, container, body = args[0], args[1], args[-1]
        out_type = None
        if len(args) == 4 and args[2].is_call('output') and args[2].args and args[2].args[0].kind == 'str':
            out_type = jsl.name_key(args[2].args[0].value)
        elif len(args) == 4 and not (args[2].kind == 'list'):
            raise Unconvertible(f'{node.value}() with this third argument', node)
        if body.kind in ('glue', 'assign'):
            raise Unconvertible(f'{node.value}() with statements in its body', node)
        header, types = self.each_header(names, container, ctx, node)
        saved = dict(self.vtypes)
        for k, t in types.items():
            self.vtypes[k] = E(None, P_ATOM, t)
        for n in names.walk():
            if n.kind == 'name' and n.key not in self.vtypes:
                self.vtypes[n.key] = E(None, P_ATOM, 'unknown')
        try:
            b = self.x(body, ctx)
        finally:
            self.vtypes = saved
        item = self.each_item
        if node.key == 'filtereach':
            if ' in sorted(' in header and '.items())' in header and ', ' in item:
                k, v = item.split(', ', 1)
                return E('{' + f'{k}: {v} for {header} if {b.code}' + '}', P_ATOM, 'dict')
            if ', ' in item and not item.startswith('('):
                item = f'({item})'
            return E(f'[{item} for {header} if {b.code}]', P_ATOM, 'list')
        code = f'[{b.code} for {header}]'
        if out_type == 'matrix':
            return E(f'np.array({code})', P_ATOM, 'matrix')
        return E(code, P_ATOM, 'list')

    @fn('Recurse')
    def f_recurse(self, node, ctx):
        if not self.funcs:
            raise Unconvertible('Recurse() outside a function', node)
        args = [self.x(a, ctx).code for a in node.args if a.kind != 'empty']
        return E(f'{self.funcs[-1]["name"]}({", ".join(args)})', P_ATOM, 'unknown')

    @fn('Eval')
    def f_eval(self, node, ctx):
        args = self.nargs(node, 1)
        a = args[0]
        if a.is_call('parse') and len(a.args) == 1 and a.args[0].kind == 'str':
            try:
                sub = jsl.parse_expr(a.args[0].value)
            except ValueError:
                raise Unconvertible('Eval(Parse("...")) of text that is not valid JSL', node)
            return self.x(sub, ctx)
        if a.is_call('expr') and len(a.args) == 1:
            return self.x(a.args[0], ctx)
        if a.kind == 'name' and isinstance(getattr(self.vtypes.get(a.key), 'info', None), dict):
            return self.x(a, ctx)
        raise Unconvertible('Eval() of an expression made while the script runs: JSL expressions as data have no translation', node)


# messages, by their canonical names: to a data table, a column, an associative array
TMSG, CMSG, DMSG = {}, {}, {}


def msg(table, *names):
    def deco(f):
        for n in names:
            table[jsl.name_key(n)] = f
        return f
    return deco


# messages to a table or a column that only change how JMP shows it
TABLE_DISPLAY = {'bringwindowtofront', 'showwindow', 'minimizewindow', 'maximizewindow', 'begindataupdate', 'enddataupdate',
                 'clearcolumnselection', 'runformulas', 'rerunformulas', 'colorbycolumn', 'colorormarkbycolumn', 'markerbycolumn',
                 'colorrowsbyrowstate', 'markers', 'colors', 'gotorow', 'setdirty', 'optimizedisplay', 'maximizedisplay',
                 'suppressformulaeval', 'addpropertiestotable', 'addscriptstotable', 'newscript', 'setproperty', 'deletescripts',
                 'deletetableproperty', 'journal', 'groupcolumns', 'ungroupcolumns', 'setlabelcolumns', 'setscrolllockcolumns',
                 'lockdatatable', 'cleareditlock', 'seteditlock', 'compressfilewhensaved', 'disableundo', 'copytablescript',
                 'newdataview', 'closedatagrid', 'closesidepanels', 'setcellheight', 'setheaderheight', 'setrowidwidth',
                 'selectcolumns', 'invertcolumnselection', 'addcolumnproperties', 'setselected', 'nextselected', 'previousselected',
                 'colorcells', 'colorcellbyvalue', 'sethidden', 'setexcluded', 'setlabeled', 'setlabelled', 'preselectrole',
                 'setuseformarker', 'useformarker', 'inputformat', 'setinputformat', 'format', 'setdisplaywidth', 'setfieldwidth',
                 'lock', 'setlock', 'deleteproperty', 'deletecolumnproperty', 'deleteformula', 'suppresseval', 'evalformula',
                 'ignoreerrors', 'label', 'hide', 'exclude', 'resettransform', 'setscrolllocked', 'closewindow', 'automaticrecalc',
                 'redoanalysis', 'sizewindow', 'movewindow', 'zoomwindow', 'scrollwindow', 'title', 'setwindowtitle', 'bringtofront',
                 'savescripttodatatable', 'savebygroupscripttodatatable', 'reportview', 'dispatch', 'sendtoreport'}


class _Tables(_Stmt):
    # ---- tables as values -------------------------------------------------------------------------
    def table_value(self, value, ctx, var):
        """name = Open(...), New Table(...), Current Data Table(), Data Table(...),
        or another table's name: the Frame (None when value is none of these)."""
        if value.is_call('open'):
            return self.open_table(value, var)
        if value.is_call('newtable'):
            return self.new_table(value, var, ctx)
        if value.is_call('currentdatatable') and not value.args:
            if self.cur is not None:
                return self.cur
            fr = self.page_frame(var, self.current_name, value)
            return fr
        if value.is_call('datatable', 'getdatatable') and len(value.args) == 1 and value.args[0].kind == 'str':
            fr = self.frame_by_name(value.args[0].value)
            if fr is not None:
                return fr
            return self.page_frame(var, value.args[0].value, value)
        if value.kind == 'name' and self.typeof(value.key) == 'frame':
            return self.vtypes[value.key].info
        if value.is_call('astable'):
            fr = self.new_frame(var, var, 'script')
            args = [a for a in value.args if a.kind != 'empty']
            m = self.x(args[0], ctx)
            names = next((a.args[0] for a in args if a.kind == 'send' and a.args[1].is_call('columnnames')), None)
            cols = ''
            if names is not None:
                cols = f', columns={self.x(names.args[0] if names.kind == "call" else names, ctx).code}'
            self.emit(f'{var} = pd.DataFrame(np.atleast_2d({m.code}){cols})')
            self.cur = fr
            return fr
        return None

    def page_frame(self, var, name, node):
        page = self.page_table(name) if name else (self.tables[0] if len(self.tables) == 1 else None)
        fr = self.new_frame(var, page['name'] if page else (name or 'data'), 'page', page)
        self.emit(self.read_line(var, fr.name))
        if page is None:
            self.note(node.line, 'warn', f'The page has no table "{name or "current"}" open: the translation reads "{fr.name}.csv"; open the table in the page first.', once=('nopage', name))
        self.cur = fr
        return fr

    @stmt('Open')
    def s_open(self, node, ctx, tail):
        self.open_table(node, None)

    def open_table(self, node, var):
        args = [a for a in node.args if a.kind != 'empty']
        if not args or args[0].kind != 'str':
            raise Unconvertible('Open() of a path made while the script runs', node)
        path = args[0].value
        base = path.replace('\\', '/').rstrip('/').rsplit('/', 1)[-1]
        stem, ext = (base.rsplit('.', 1) + [''])[:2] if '.' in base else (base, '')
        ext = ext.lower()
        if var is None:
            var = self.fresh(snake(stem) if snake(stem) not in ('x',) else 'dt')
        rest = args[1:]
        if rest and not all(a.kind in ('name', 'str') and a.value.lower() in ('invisible', 'private') for a in rest):
            self.note(node.line, 'info', 'Open(): the import options are not carried over; pandas reads the file with its own defaults.', once=('openopts', node.line))
        if ext in ('jmp', ''):
            page = self.page_table(stem)
            name = page['name'] if page else stem
            fr = self.new_frame(var, name, 'page' if page else 'file', page)
            self.emit(self.read_line(var, name))
            if page is None:
                self.note(node.line, 'warn', f'Open("{base}"): the page has no table "{stem}" open, so the translation reads "{stem}.csv"; open the table in the page (or save it from JMP with File > Export as CSV) under that name.', once=('open', stem))
            else:
                self.note(node.line, 'info', f'Open("{base}"): read as the page\'s table {name}, from the CSV file the page writes for it.', once=('openpage', stem))
        else:
            if '$' in path:
                self.path_note(node)
            readers = {'csv': 'pd.read_csv({})', 'txt': 'pd.read_csv({}, sep=None, engine="python")', 'tsv': 'pd.read_csv({}, sep="\\t")',
                       'dat': 'pd.read_csv({}, sep=None, engine="python")', 'xlsx': 'pd.read_excel({})', 'xls': 'pd.read_excel({})',
                       'xlsm': 'pd.read_excel({})', 'sas7bdat': 'pd.read_sas({})', 'xpt': 'pd.read_sas({})', 'dta': 'pd.read_stata({})',
                       'sav': 'pd.read_spss({})', 'json': 'pd.read_json({})', 'parquet': 'pd.read_parquet({})'}
            if ext not in readers:
                raise Unconvertible(f'Open() of a .{ext} file: only data tables are read here', node)
            code = readers[ext].format(lit(path))
            sheet = next((a for a in rest if a.is_call('worksheets') and a.args and a.args[0].kind == 'str'), None)
            if sheet is not None:
                code = code[:-1] + f', sheet_name={lit(sheet.args[0].value)})'
            fr = self.new_frame(var, stem, 'file')
            self.emit(f'{var} = {code}')
        self.cur = fr
        return fr

    @stmt('New Table')
    def s_newtable(self, node, ctx, tail):
        self.new_table(node, None, ctx)

    def new_table(self, node, var, ctx):
        args = [self.unwrap(a) for a in node.args if a.kind != 'empty']
        name = args[0].value if args and args[0].kind == 'str' else 'Untitled'
        if var is None:
            var = self.fresh(snake(name) if name != 'Untitled' else 'dt')
        fr = self.new_frame(var, name, 'script')
        nrows = None
        specs = []
        for a in args[1:]:
            if a.is_call('addrows'):
                nrows = self.x(a.args[0], ctx).code if a.args else '1'
            elif a.is_call('newcolumn'):
                spec = self.column_spec(a, fr, ctx)
                if spec['name'] is None:
                    raise Unconvertible('New Table(): a New Column() whose name is made while the script runs', a)
                specs.append(spec)
            elif a.kind in ('str', 'name') and a.value.lower() in ('invisible', 'private', 'visible'):
                pass
            elif a.is_call('setrowstates', 'setcell'):
                raise Unconvertible(f'New Table() with {a.value}()', a)
            else:
                self.note(a.line, 'info', f'New Table(): {excerpt(self.p.source(a), 40)} is not carried over.', once=('newtable', a.line))
        data = [s for s in specs if s['values'] is not None]
        lens = {s['n'] for s in data}
        lines = []
        if data:
            if len(lens) > 1 or None in lens:
                items = [f'    {lit(s["name"])}: pd.Series({s["values"]}),' for s in data]
            else:
                items = [f'    {lit(s["name"])}: {s["values"]},' for s in data]
            lines.append(f'{var} = pd.DataFrame({{')
            lines.extend(items)
            lines.append('})')
            if nrows is not None and lens and lens != {None}:
                n0 = max(n for n in lens if n is not None)
                if nrows.isdigit() and int(nrows) > n0:
                    lines.append(f'{var} = {var}.reindex(range({nrows}))')
        elif nrows is not None:
            lines.append(f'{var} = pd.DataFrame(index=range({nrows}))')
        else:
            lines.append(f'{var} = pd.DataFrame()')
        for ln in lines:
            self.emit(ln)
        self.cur = fr
        for s in specs:
            fr.add_col(s['name'], s['dtype'], s['mt'])
        fr.known = True
        for s in specs:
            if s['values'] is None:
                self.fill_column(fr, s, ctx)
        return fr

    def unwrap(self, a):
        """A message given as an argument (<<Invisible) is its message."""
        if a.kind == 'send' and a.args[0].kind == 'empty':
            return a.args[1]
        return a

    DTYPES = {'numeric': 'numeric', 'character': 'character', 'rowstate': 'rowstate', 'expression': 'expression'}
    MTYPES = {'continuous': 'continuous', 'nominal': 'nominal', 'ordinal': 'ordinal', 'multipleresponse': 'nominal', 'unstructuredtext': 'nominal', 'none': None}

    def column_spec(self, node, fr, ctx):
        """New Column's arguments: name, data and modeling type, values or formula."""
        args = [self.unwrap(a) for a in node.args if a.kind != 'empty']
        if not args:
            raise Unconvertible('New Column() without a name', node)
        a0 = args[0]
        if a0.kind == 'str':
            name, name_code = a0.value, None
        else:
            e = self.x(a0, SCALAR)
            name, name_code = None, e.code
        spec = {'name': name, 'name_code': name_code, 'dtype': None, 'mt': None, 'formula': None, 'values': None, 'n': None, 'each': None, 'node': node}
        for a in args[1:]:
            k = a.key if a.kind in ('name', 'call') else (jsl.name_key(a.value) if a.kind == 'str' else None)
            if a.kind in ('name', 'str') and k in self.DTYPES:
                spec['dtype'] = self.DTYPES[k]
            elif a.kind in ('name', 'str') and k in self.MTYPES:
                spec['mt'] = self.MTYPES[k]
            elif a.is_call('formula', 'setformula') and a.args:
                spec['formula'] = a.args[0]
            elif a.is_call('setvalues', 'values') and a.args:
                v = a.args[0]
                if v.kind == 'matrix':
                    flat = [x for r in v.value for x in r]
                    spec['values'] = '[' + ', '.join('np.nan' if x is None else lit(x) for x in flat) + ']'
                    spec['n'] = len(flat)
                    spec['dtype'] = spec['dtype'] or 'numeric'
                elif v.kind == 'list':
                    items = [self.x(i, SCALAR) for i in v.args if i.kind != 'empty']
                    spec['values'] = '[' + ', '.join(i.code for i in items) + ']'
                    spec['n'] = len(items)
                    if not spec['dtype']:
                        spec['dtype'] = 'character' if items and all(i.type == 'str' for i in items) else 'numeric'
                else:
                    e = self.x(v, SCALAR)
                    spec['values'] = f'np.ravel({e.code})' if e.type == 'matrix' else e.code
            elif a.is_call('seteachvalue') and a.args:
                spec['each'] = a.args[0]
            elif a.is_call('like') and a.args:
                ref = self.colref(a.args[0], SCALAR, quiet=True)
                c = ref.frame.col(ref.name) if ref and ref.name else None
                if c:
                    spec['dtype'] = spec['dtype'] or c['dtype']
                    spec['mt'] = spec['mt'] or c['mt']
            else:
                self.note(a.line, 'info', 'New Column(): formats, widths and column properties are not carried over (they change how JMP shows the column).', once='colprops')
        if spec['dtype'] is None:
            spec['dtype'] = 'numeric'
        if spec['mt'] is None:
            spec['mt'] = 'nominal' if spec['dtype'] == 'character' else 'continuous'
        return spec

    def fill_column(self, fr, spec, ctx):
        """A column without values in the table's constructor: its formula,
        Set Each Value, or empty."""
        key = lit(spec['name']) if spec['name'] is not None else spec['name_code']
        ref = ColRef(fr, spec['name'], key)
        if spec['formula'] is not None:
            self.formula(ref, spec['formula'], spec['node'])
            self.note(spec['node'].line, 'info', 'Formula columns are computed once here, when the column is made; JMP keeps them up to date as the table changes.', once='formula')
        elif spec['each'] is not None:
            self.formula(ref, spec['each'], spec['node'])
        elif spec['values'] is not None:
            self.emit(f'{ref.series()} = {spec["values"]}' if spec['n'] is None else f'{ref.series()} = pd.Series({spec["values"]})')
        else:
            self.emit(f'{ref.series()} = {lit("") if spec["dtype"] == "character" else "np.nan"}')
        if spec['mt'] in ('nominal', 'ordinal') and spec['dtype'] == 'numeric':
            self.note(spec['node'].line, 'info', f'{spec["name"] or "The column"} is numeric with the {spec["mt"]} modeling type: pandas keeps the numbers; the modeling type matters to the page\'s analyses, which take it from the page\'s table.', once='mtnum')

    def new_column(self, node, fr, ctx):
        spec = self.column_spec(node, fr, ctx)
        if spec['name'] is not None:
            fr.add_col(spec['name'], spec['dtype'], spec['mt'])
        self.fill_column(fr, spec, ctx)
        return ColRef(fr, spec['name'], lit(spec['name']) if spec['name'] is not None else spec['name_code'])

    @stmt('New Column')
    def s_newcolumn(self, node, ctx, tail):
        self.new_column(node, self.current_frame(node), ctx)

    def formula(self, ref, expr, node):
        """A column formula: one vectorised assignment, or a loop over the rows."""
        fr = ref.frame
        snap = self.snapshot()
        try:
            if self.refers_to(expr, ref):
                raise NotVec()
            e = self.x(expr, Ctx('vec', fr))
            self.emit(f'{ref.series()} = {e.code}')
            return
        except NotVec:
            self.restore(snap)
        except Unconvertible:
            self.restore(snap)
            raise
        self.emit(f'for row in range(len({fr.var})):')
        with self.block():
            e = self.x(expr, Ctx('row', fr))
            self.emit(f'{fr.var}.loc[row, {ref.code}] = {e.code}')
        self.note(node.line, 'info', 'A formula that looks at other rows (or cannot be written for whole columns) is computed row by row.', once='rowloop')

    def refers_to(self, expr, ref):
        """True when a formula reads the column it makes (a running total):
        each row needs the rows before it, so it is computed row by row."""
        if ref.name is None:
            return False
        k = jsl.name_key(ref.name)
        for n in expr.walk():
            if n.kind in ('col', 'scope') and n.key == k:
                return True
            if n.kind == 'name' and n.key == k and n.key not in self.vtypes:
                return True
            if n.kind == 'call' and n.key in ('column', 'ascolumn') and n.args and n.args[-1].kind == 'str' and jsl.name_key(n.args[-1].value) == k:
                return True
        return False

    def snapshot(self):
        return (list(self.helpers), list(self.notes), set(self._note_keys), len(self.body))

    def restore(self, snap):
        self.helpers, self.notes, self._note_keys = list(snap[0]), list(snap[1]), set(snap[2])
        del self.body[snap[3]:]

    @stmt('Current Data Table')
    def s_currentdatatable(self, node, ctx, tail):
        if not node.args:
            return
        fr = self.frame_of(node.args[0], ctx, need=False)
        if fr is None and node.args[0].kind == 'str':
            fr = self.table_by_arg(node.args[0], node)
        if fr is None:
            raise Unconvertible('Current Data Table() of a table not known here', node)
        self.cur = fr

    @stmt('Data Table', 'Column', 'As Column')
    def s_noop_value(self, node, ctx, tail):
        return

    @stmt('Close')
    def s_close(self, node, ctx, tail):
        args = [a for a in node.args if a.kind != 'empty']
        fr = self.frame_of(args[0], ctx, need=False) if args else self.cur
        save = next((a for a in args[1:] if a.is_call('save') and a.args), None)
        if save is not None and fr is not None:
            self.save_table(fr, save.args[0], node)
        self.note(node.line, 'info', 'Close(): a DataFrame needs no closing; dropped.', once='close')
        if fr is not None and fr is self.cur:
            others = [f for f in self.frames if f is not fr]
            self.cur = others[-1] if others else None

    def save_table(self, fr, path_node, node):
        if path_node.kind != 'str':
            e = self.x(path_node, SCALAR)
            self.emit(f'{fr.var}.to_csv({e.code}, index=False)')
            return
        path = path_node.value
        low = path.lower()
        if low.endswith(('.xlsx', '.xls')):
            self.emit(f'{fr.var}.to_excel({lit(path)}, index=False)')
            return
        if low.endswith('.jmp') or '.' not in path.rsplit('/', 1)[-1]:
            new = (path[:-4] if low.endswith('.jmp') else path) + '.csv'
            self.note(node.line, 'info', f'Saved as a CSV file ({new.rsplit("/", 1)[-1]}), not as a JMP table.', once=('savecsv', node.line))
            path = new
        if '$' in path:
            self.path_note(node)
        self.emit(f'{fr.var}.to_csv({lit(path)}, index=False)')

    # ---- For Each Row ------------------------------------------------------------------------------
    @stmt('For Each Row')
    def s_foreachrow(self, node, ctx, tail):
        args = [a for a in node.args if a.kind != 'empty']
        if len(args) == 2:
            fr = self.frame_of(args[0], ctx)
            body = args[1]
        elif len(args) == 1:
            fr = self.current_frame(node)
            body = args[0]
        else:
            raise Unconvertible('For Each Row() takes a body (and a table)', node)
        if self.vector_rows(fr, body, node):
            return
        # the row-state masks the loop reads or sets exist before it
        for kind in self.rowstates_in(body):
            if kind not in fr.masks:
                self.mask(fr, kind, init=True)
        self.emit(f'for row in range(len({fr.var})):')
        rctx = Ctx('row', fr)
        self.loops.append({'incr': []})
        with self.block():
            self.body_stmts(body, rctx)
        self.loops.pop()

    def rowstates_in(self, body):
        out = []
        for n in body.walk():
            if n.is_call('selected', 'excluded', 'hidden', 'labeled') and n.args and n.args[0].is_call('rowstate'):
                if n.key not in out:
                    out.append(n.key)
        return out

    def vector_rows(self, fr, body, node):
        """For Each Row whose body only sets columns (maybe under If): whole-column
        assignments instead of a loop."""
        items = body.args if body.kind == 'glue' else [body]
        items = [i for i in items if i.kind != 'empty']
        assigned = set()

        def col_target(t):
            ref = self.colref(t, Ctx('vec', fr), quiet=True) if t.kind in ('col', 'scope', 'call', 'name') else None
            return ref if ref is not None and ref.frame is fr and ref.name is not None else None

        plan = []
        for it in items:
            if it.kind == 'assign' and it.value in ('=', '+=', '-=', '*=', '/='):
                t = it.args[0]
                if t.is_call('selected', 'excluded', 'hidden', 'labeled') and t.args and t.args[0].is_call('rowstate') and it.value == '=':
                    plan.append(('state', t.key, it.args[1]))
                    continue
                ref = col_target(t)
                if ref is None:
                    return False
                plan.append(('set', ref, it.value, it.args[1]))
                assigned.add(jsl.name_key(ref.name))
            elif it.is_call('if', 'ifmz'):
                pairs, other = self.branches(it)
                refs = []
                for body_ in [v for _, v in pairs] + ([other] if other is not None else []):
                    if body_.kind != 'assign' or body_.value != '=':
                        return False
                    ref = col_target(body_.args[0])
                    if ref is None:
                        return False
                    refs.append(ref)
                names = {jsl.name_key(r.name) for r in refs}
                if len(names) != 1:
                    return False
                plan.append(('if', refs[0], pairs, other))
                assigned.update(names)
            else:
                return False
        # a column set here and read from another row (a subscript, Lag, Dif) needs the loop
        for n in body.walk():
            if n.kind == 'subscript' and n.args[0].kind in ('col', 'scope', 'name', 'call'):
                return False
            if n.is_call('lag', 'dif', 'colcumulativesum', 'cumulativesum'):
                return False
        snap = self.snapshot()
        vctx = Ctx('vec', fr)
        lines = []
        try:
            for step in plan:
                if step[0] == 'set':
                    _, ref, op, value = step
                    e = self.x(value, vctx)
                    if op == '=':
                        lines.append(f'{ref.series()} = {e.code}')
                    else:
                        lines.append(f'{ref.series()} {op} {e.code}')
                elif step[0] == 'state':
                    _, kind, value = step
                    e = self.x(value, vctx.but(cond=True))
                    var = self.mask(fr, kind)
                    lines.append(f'{var} = {self.as_mask(e, fr)}')
                else:
                    _, ref, pairs, other = step
                    conds = [self.x(c, vctx.but(cond=True)) for c, _ in pairs]
                    vals = [self.x(v.args[1], vctx) for _, v in pairs]
                    if other is None and len(pairs) == 1:
                        lines.append(f'{fr.var}.loc[{conds[0].code}, {ref.code}] = {vals[0].code}')
                    elif other is not None and len(pairs) == 1:
                        els = self.x(other.args[1], vctx)
                        lines.append(f'{ref.series()} = np.where({conds[0].code}, {vals[0].code}, {els.code})')
                    else:
                        els = self.x(other.args[1], vctx).code if other is not None else ref.series()
                        lines.append(f'{ref.series()} = np.select([{", ".join(c.code for c in conds)}], [{", ".join(v.code for v in vals)}], default={els})')
        except (NotVec, Unconvertible):
            self.restore(snap)
            return False
        for ln in lines:
            self.emit(ln)
        return True

    def as_mask(self, e, fr):
        if e.type == 'series':
            return e.code
        return f'pd.Series({e.code}, index={fr.var}.index).astype(bool)'

    # ---- row states ------------------------------------------------------------------------------------
    def mask(self, fr, kind, init=False):
        """The variable of a table's row-state mask (selected, excluded, ...)."""
        if kind not in fr.masks:
            first = not any(f.masks for f in self.frames if f is not fr)
            var = self.fresh(kind if first else f'{fr.var}_{kind}')
            fr.masks[kind] = var
            if init:
                self.emit(f'{var} = pd.Series(False, index={fr.var}.index)')
            if kind == 'excluded':
                self.note(self.cur_line, 'info', 'Excluded rows: JMP\'s analyses leave them out; the analyses converted after them here take the rows where excluded is False.', once='excluded')
            if kind in ('hidden', 'labeled'):
                self.note(self.cur_line, 'info', f'{kind.title()} rows only change JMP\'s graphs: the mask is kept, and nothing uses it.', once=('rowstate', kind))
        return fr.masks[kind]

    def rowstate_assign(self, target, value, ctx):
        kind = target.key
        if ctx.mode != 'row':
            raise Unconvertible(f'{target.value}(Row State()) outside For Each Row', target)
        fr = ctx.frame
        var = self.mask(fr, kind)
        e = self.x(value, ctx)
        self.emit(f'{var}.loc[row] = bool({e.code})')

    @fn('Selected', 'Excluded', 'Hidden', 'Labeled')
    def f_rowstate_get(self, node, ctx):
        if not node.args or not node.args[0].is_call('rowstate'):
            raise Unconvertible(f'{node.value}() of a row state value', node)
        fr = ctx.frame if ctx.mode in ('vec', 'row') and ctx.frame is not None else self.current_frame(node)
        new = node.key not in fr.masks
        var = self.mask(fr, node.key)
        if new:
            self.emit(f'{var} = pd.Series(False, index={fr.var}.index)')
        if ctx.mode == 'row':
            return E(f'{var}.loc[row]', P_ATOM, 'bool')
        return E(var, P_ATOM, 'series')

    # ---- Summarize ----------------------------------------------------------------------------------------
    @stmt('Summarize')
    def s_summarize(self, node, ctx, tail):
        args = [a for a in node.args if a.kind != 'empty']
        fr = None
        if args and args[0].kind != 'assign':
            fr = self.frame_of(args[0], ctx)
            args = args[1:]
        fr = fr or self.current_frame(node)
        by = None
        stats_ = []
        for a in args:
            if a.kind != 'assign' or a.args[0].kind != 'name':
                raise Unconvertible('Summarize() takes name = statistic arguments', node)
            name, v = a.args
            if v.is_call('by'):
                refs = [self.colref(c, Ctx('vec', fr), quiet=True) for c in v.args]
                if not refs or any(r_ is None or r_.name is None for r_ in refs):
                    raise Unconvertible('Summarize(): a By() that is not columns', node)
                by = (name, refs)
            else:
                stats_.append((name, v))
        g = None
        if by is not None:
            cols = [r.name for r in by[1]]
            keys = lit(cols[0]) if len(cols) == 1 else '[' + ', '.join(lit(c) for c in cols) + ']'
            g = self.fresh('grouped')
            self.emit(f'{g} = {fr.var}.groupby({keys}, dropna=False)')
            self.helper('jsl_char')
            bvar = self.py(by[0].key, by[0].value)
            self.emit(f'{bvar} = [jsl_char(k) for k in {g}.groups]   # the By values, as strings (as JSL gives them)')
            self.vtypes[by[0].key] = E(None, P_ATOM, 'list')
        for name, v in stats_:
            var = self.py(name.key, name.value)
            k = v.key if v.kind in ('call', 'name') else None
            col = self.colref(v.args[0], Ctx('vec', fr)) if v.kind == 'call' and v.args else None
            if k == 'count' and col is None:
                code = f'{g}.size()' if g else f'len({fr.var})'
            else:
                if col is None:
                    raise Unconvertible(f'Summarize(): {self.p.source(v)}', node)
                how = {'count': 'count', 'sum': 'sum', 'mean': 'mean', 'min': 'min', 'max': 'max', 'stddev': 'std', 'first': 'first'}.get(k)
                if k == 'quantile' and len(v.args) == 2:
                    p = self.x(v.args[1], SCALAR).code
                    code = f'{g}[{col.code}].agg(lambda s: np.nanquantile(s, {p}, method="weibull"))' if g else f'np.nanquantile({col.series()}, {p}, method="weibull")'
                elif k == 'corr' and len(v.args) == 2:
                    other = self.colref(v.args[1], Ctx('vec', fr))
                    if g:
                        raise Unconvertible('Summarize(): Corr() with By', node)
                    code = f'{col.series()}.corr({other.series()})'
                elif how is None:
                    raise Unconvertible(f'Summarize(): the statistic {v.value}', node)
                elif how == 'first':
                    code = f'{g}[{col.code}].first()' if g else f'{col.series()}.iloc[0]'
                else:
                    code = f'{g}[{col.code}].{how}()' if g else f'{col.series()}.{how}()'
            if g:
                code += '.to_numpy().reshape(-1, 1)'
                self.vtypes[name.key] = E(None, P_ATOM, 'matrix')
            else:
                self.vtypes[name.key] = E(None, P_ATOM, 'num')
            self.emit(f'{var} = {code}')

    # ---- messages -----------------------------------------------------------------------------------------
    def is_launch_send(self, node):
        return node.kind == 'send' and node.args[1].kind == 'call' and node.args[1].key in PLATFORMS or (
            node.kind == 'send' and node.args[1].kind == 'name' and node.args[1].key in PLATFORMS)

    def receiver(self, obj, ctx, msg_key=None):
        """What a message goes to: ('frame', Frame), ('col', ColRef), ('platform', step), ('dict', E)."""
        if obj.kind == 'send':
            r = self.send(obj, ctx, want=True)
            if r is None:
                raise Unconvertible('a message to the result of a message that gives nothing', obj)
            if r.type in ('frame', 'col', 'platform') and r.info is not None:
                return (r.type, r.info)
            if r.type == 'dict':
                return ('dict', r)
            raise Unconvertible(f'messages to {excerpt(self.p.source(obj), 40)}: the result is not a table, a column or an analysis', obj)
        if obj.kind == 'name':
            v = self.vtypes.get(obj.key)
            if v is not None and v.type in ('frame', 'col', 'platform') and v.info is not None:
                return (v.type, v.info)
            if v is not None and v.type == 'dict':
                return ('dict', self.x(obj, ctx))
        if obj.kind in ('call',) and obj.key in PLATFORMS:
            step = self.launch(obj, ctx, None, None)
            if step is None:
                raise Unconvertible('messages to a launch that was not converted', obj)
            return ('platform', step)
        if obj.kind == 'call' and obj.key in ('open', 'newtable'):
            var = None
            fr = self.table_value(obj, ctx, var or self.fresh('dt'))
            return ('frame', fr)
        if obj.kind == 'call' and obj.key == 'newcolumn':
            return ('col', self.new_column(obj, self.current_frame(obj), ctx))
        if obj.kind in ('col', 'scope', 'call', 'name'):
            ref = self.colref(obj, ctx, quiet=True)
            if ref is not None:
                return ('col', ref)
        fr = self.frame_of(obj, ctx, need=False) if obj.kind in ('name', 'call') else None
        if fr is not None:
            return ('frame', fr)
        if obj.kind == 'name' and obj.key not in self.vtypes and obj.key not in self.names and msg_key in TMSG | {k: 1 for k in PLATFORMS}:
            fr = self.current_frame(obj)
            self.note(obj.line, 'warn', f'{obj.value} is not set in the script; it is taken as the current data table ({fr.name}).', once=('unset', obj.key))
            self.vtypes[obj.key] = E(None, P_ATOM, 'frame', fr)
            return ('frame', fr)
        if obj.kind == 'call' and obj.key in DISPLAY | {'report', 'window', 'currentreport'}:
            raise Unconvertible(f'messages to {obj.value}(): report and window objects have no Python counterpart', obj)
        if obj.kind == 'subscript' and obj.args[0].kind in ('call', 'name'):
            raise Unconvertible('messages to a part of a report (a display box): reports have no Python counterpart', obj)
        raise Unconvertible(f'messages to {excerpt(self.p.source(obj), 40)}: the translation does not know what it is', obj)

    def send(self, node, ctx, want=False, target=None):
        obj, m = node.args
        if obj.kind == 'empty':
            raise Unconvertible('a message given as an argument, where it has no meaning', node)
        msgs = [a for a in m.args if a.kind != 'empty'] if m.kind == 'list' else [m]
        kind, recv = self.receiver(obj, ctx, msgs[0].key if msgs and msgs[0].kind in ('name', 'call') else None)
        out = None
        for i, one in enumerate(msgs):
            last = i == len(msgs) - 1
            out = self.message(kind, recv, one, ctx, want and last, target if last else None, node)
        return out

    def message(self, kind, recv, m, ctx, want, target, node):
        if m.kind not in ('name', 'call'):
            raise Unconvertible(f'a message that is not a name: {excerpt(self.p.source(m), 40)}', node)
        key = m.key
        if kind == 'frame':
            if key in PLATFORMS:
                step = self.launch(m, ctx, recv, None, whole=node)
                return E(None, P_ATOM, 'platform', step) if step else None
            h = TMSG.get(key)
            if h is not None:
                return h(self, recv, m, ctx, want, target, node)
            if key in TABLE_DISPLAY:
                self.note(node.line, 'info', f'{m.value}: only changes how JMP shows the table; dropped.', once=('tdisp', key))
                return E(recv.var, P_ATOM, 'frame', recv)
            raise Unconvertible(f'the data table message {m.value}', node)
        if kind == 'col':
            h = CMSG.get(key)
            if h is not None:
                return h(self, recv, m, ctx, want, target, node)
            if key in TABLE_DISPLAY:
                self.note(node.line, 'info', f'{m.value}: a column property or display setting; dropped.', once=('cdisp', key))
                return E(recv.code, P_ATOM, 'col', recv)
            raise Unconvertible(f'the column message {m.value}', node)
        if kind == 'platform':
            return self.platform_message(recv, m, node, want)
        if kind == 'dict':
            h = DMSG.get(key)
            if h is None:
                raise Unconvertible(f'the associative array message {m.value}', node)
            return h(self, recv, m, ctx, want, target, node)
        raise Unconvertible('a message to this object', node)

    def result_var(self, target, base):
        return target or self.fresh(base)

    # ---- table messages ------------------------------------------------------------------------------------
    @msg(TMSG, 'New Column')
    def t_newcolumn(self, fr, m, ctx, want, target, node):
        ref = self.new_column(m, fr, ctx)
        return E(ref.code, P_ATOM, 'col', ref)

    @msg(TMSG, 'Add Rows')
    def t_addrows(self, fr, m, ctx, want, target, node):
        args = [a for a in m.args if a.kind != 'empty']
        if not args:
            raise Unconvertible('Add Rows() without a number (the dialog)', node)
        a = args[0]
        if a.kind == 'list':
            vals = []
            for it in a.args:
                if it.kind == 'assign':
                    ref = self.colref(it.args[0], Ctx('vec', fr), quiet=True)
                    vals.append(f'{lit(ref.name if ref else self.p.source(it.args[0]))}: [{self.x(it.args[1], SCALAR).code}]')
            self.emit(f'{fr.var} = pd.concat([{fr.var}, pd.DataFrame({{{", ".join(vals)}}})], ignore_index=True)')
        else:
            n = self.x(a, SCALAR)
            where = next((b for b in args[1:] if b.kind in ('str', 'name') and b.value.lower().replace(' ', '') == 'atstart'), None)
            if where is not None:
                self.emit(f'{fr.var} = pd.concat([pd.DataFrame(index=range({n.code})), {fr.var}], ignore_index=True)')
            else:
                self.emit(f'{fr.var} = pd.concat([{fr.var}, pd.DataFrame(index=range({n.code}))], ignore_index=True)')
        for kind, var in fr.masks.items():
            self.emit(f'{var} = {var}.reindex({fr.var}.index, fill_value=False)')
        return E(fr.var, P_ATOM, 'frame', fr)

    def col_names_arg(self, fr, args, node):
        names = []
        for a in args:
            a = self.unwrap(a)
            if a.kind == 'list':
                names.extend(self.col_names_arg(fr, a.args, node))
            elif a.kind == 'str':
                names.append(self.column_of(fr, a.value, node))
            elif a.kind == 'name' and self.typeof(a.key) == 'list' and isinstance(self.vtypes[a.key].info, dict):
                names.extend(self.vtypes[a.key].info['columns'])
            else:
                ref = self.colref(a, Ctx('vec', fr), quiet=True)
                if ref is None or ref.name is None:
                    raise Dynamic('columns chosen while the script runs')
                names.append(ref.name)
        return names

    @msg(TMSG, 'Delete Columns', 'Delete Column')
    def t_deletecolumns(self, fr, m, ctx, want, target, node):
        args = [a for a in m.args if a.kind != 'empty']
        if not args:
            raise Unconvertible('Delete Columns() of the selected columns', node)
        try:
            names = self.col_names_arg(fr, args, node)
            code = '[' + ', '.join(lit(n) for n in names) + ']'
            for n in names:
                fr.cols.pop(jsl.name_key(n), None)
        except Dynamic:
            code = self.x(args[0], SCALAR).code
        self.emit(f'{fr.var} = {fr.var}.drop(columns={code})')
        return E(fr.var, P_ATOM, 'frame', fr)

    @msg(TMSG, 'Delete Rows', 'Delete Row')
    def t_deleterows(self, fr, m, ctx, want, target, node):
        args = [a for a in m.args if a.kind != 'empty']
        if not args:
            sel = fr.masks.get('selected')
            if sel is None:
                raise Unconvertible('Delete Rows() of the selected rows, with no rows selected by the script', node)
            keep = f'~{sel}'
            self.emit(f'{fr.var} = {fr.var}[{keep}].reset_index(drop=True)')
            for kind, var in fr.masks.items():
                if kind != 'selected':
                    self.emit(f'{var} = {var}[{keep}].reset_index(drop=True)')
            self.emit(f'{sel} = pd.Series(False, index={fr.var}.index)')
            return E(fr.var, P_ATOM, 'frame', fr)
        part = self.sub_part(args[0], SCALAR, allow_all=False)
        rows = part[1] if part[0] in ('list', 'one') else None
        if part[0] == 'one':
            rows = f'[{part[1]}]'
        if part[0] == 'slice':
            rows = f'range({part[1].replace(":", ", ")})'
        self.emit(f'{fr.var} = {fr.var}.drop(index={rows}).reset_index(drop=True)')
        for kind, var in fr.masks.items():
            self.emit(f'{var} = {var}.drop(index={rows}).reset_index(drop=True)')
        return E(fr.var, P_ATOM, 'frame', fr)

    def where_arg(self, fr, cond, node):
        e = self.x(cond, Ctx('vec', fr, cond=True))
        return self.as_mask(e, fr)

    @msg(TMSG, 'Select Where')
    def t_selectwhere(self, fr, m, ctx, want, target, node):
        args = [self.unwrap(a) for a in m.args if a.kind != 'empty']
        if not args:
            raise Unconvertible('Select Where() without a condition', node)
        cond = self.where_arg(fr, args[0], node)
        mode = next((a for a in args[1:] if a.is_call('currentselection') and a.args and a.args[0].kind == 'str'), None)
        var = self.mask(fr, 'selected')
        how = mode.args[0].value.lower() if mode is not None else 'clear'
        if how == 'extend':
            self.emit(f'{var} = {var} | ({cond})')
        elif how == 'restrict':
            self.emit(f'{var} = {var} & ({cond})')
        else:
            self.emit(f'{var} = {cond}')
        return E(fr.var, P_ATOM, 'frame', fr)

    @msg(TMSG, 'Select Rows')
    def t_selectrows(self, fr, m, ctx, want, target, node):
        args = [a for a in m.args if a.kind != 'empty']
        part = self.sub_part(args[0], SCALAR, allow_all=False)
        rows = f'[{part[1]}]' if part[0] == 'one' else part[1]
        var = self.mask(fr, 'selected')
        self.emit(f'{var} = pd.Series({fr.var}.index.isin({rows}), index={fr.var}.index)')
        return E(fr.var, P_ATOM, 'frame', fr)

    @msg(TMSG, 'Select All Rows')
    def t_selectall(self, fr, m, ctx, want, target, node):
        var = self.mask(fr, 'selected')
        self.emit(f'{var} = pd.Series(True, index={fr.var}.index)')
        return E(fr.var, P_ATOM, 'frame', fr)

    @msg(TMSG, 'Clear Select', 'Clear Selection')
    def t_clearselect(self, fr, m, ctx, want, target, node):
        var = self.mask(fr, 'selected')
        self.emit(f'{var} = pd.Series(False, index={fr.var}.index)')
        return E(fr.var, P_ATOM, 'frame', fr)

    @msg(TMSG, 'Invert Row Selection')
    def t_invert(self, fr, m, ctx, want, target, node):
        var = self.mask(fr, 'selected', init=False)
        self.emit(f'{var} = ~{var}')
        return E(fr.var, P_ATOM, 'frame', fr)

    @msg(TMSG, 'Select Excluded', 'Select Hidden', 'Select Labeled')
    def t_selectstate(self, fr, m, ctx, want, target, node):
        kind = {'selectexcluded': 'excluded', 'selecthidden': 'hidden', 'selectlabeled': 'labeled'}[m.key]
        src = fr.masks.get(kind)
        var = self.mask(fr, 'selected')
        self.emit(f'{var} = {src}.copy()' if src else f'{var} = pd.Series(False, index={fr.var}.index)')
        return E(fr.var, P_ATOM, 'frame', fr)

    def _state_from_selected(self, fr, kind, on, node):
        sel = fr.masks.get('selected')
        if sel is None:
            raise Unconvertible(f'{kind.title()} the selected rows, with no rows selected by the script', node)
        had = kind in fr.masks
        var = self.mask(fr, kind)
        if on is None:
            self.emit(f'{var} = {var} ^ {sel}' if had else f'{var} = {sel}.copy()')
        elif on:
            self.emit(f'{var} = {var} | {sel}' if had else f'{var} = {sel}.copy()')
        else:
            self.emit(f'{var} = {var} & ~{sel}' if had else f'{var} = pd.Series(False, index={fr.var}.index)')

    @msg(TMSG, 'Exclude', 'Unexclude', 'Hide', 'Unhide', 'Label', 'Unlabel', 'Hide and Exclude')
    def t_rowstate(self, fr, m, ctx, want, target, node):
        k = m.key
        arg = m.args[0] if m.args and m.args[0].kind == 'num' else None
        on = None if arg is None else bool(arg.value)
        if k.startswith('un'):
            on = False
            k = k[2:]
        if k == 'hideandexclude':
            self._state_from_selected(fr, 'hidden', on, node)
            self._state_from_selected(fr, 'excluded', on, node)
        else:
            self._state_from_selected(fr, {'exclude': 'excluded', 'hide': 'hidden', 'label': 'labeled'}[k], on, node)
        return E(fr.var, P_ATOM, 'frame', fr)

    @msg(TMSG, 'Clear Row States')
    def t_clearrowstates(self, fr, m, ctx, want, target, node):
        for kind, var in fr.masks.items():
            self.emit(f'{var} = pd.Series(False, index={fr.var}.index)')
        return E(fr.var, P_ATOM, 'frame', fr)

    @msg(TMSG, 'Get Rows Where')
    def t_getrowswhere(self, fr, m, ctx, want, target, node):
        args = [self.unwrap(a) for a in m.args if a.kind != 'empty']
        cond = self.x(args[0], Ctx('vec', fr, cond=True))
        return E(f'np.flatnonzero({cond.code}) + 1', P_ADD, 'rows')

    @msg(TMSG, 'Get Selected Rows', 'Get Excluded Rows', 'Get Hidden Rows', 'Get Labeled Rows')
    def t_getstaterows(self, fr, m, ctx, want, target, node):
        kind = {'getselectedrows': 'selected', 'getexcludedrows': 'excluded', 'gethiddenrows': 'hidden', 'getlabeledrows': 'labeled'}[m.key]
        var = fr.masks.get(kind)
        if var is None:
            return E('np.array([], dtype=int)', P_ATOM, 'rows')
        return E(f'np.flatnonzero({var}) + 1', P_ADD, 'rows')

    @msg(TMSG, 'Get Column Names')
    def t_getcolumnnames(self, fr, m, ctx, want, target, node):
        filters = [a.value.lower() for a in m.args if a.kind in ('name', 'str')]
        mts = [f for f in filters if f in ('continuous', 'nominal', 'ordinal')]
        if mts:
            if not fr.known:
                raise Unconvertible('Get Column Names() by modeling type, of a table whose columns are not known', node)
            names = [c['name'] for c in fr.cols.values() if c.get('mt') in mts]
            self.note(node.line, 'info', f'Get Column Names({", ".join(mts)}): the names are the ones the page\'s table has now, written out.', once=('gcn', node.line))
            return E('[' + ', '.join(lit(n) for n in names) + ']', P_ATOM, 'list', {'columns': names})
        if 'numeric' in filters:
            code = f'{fr.var}.select_dtypes("number").columns.tolist()'
        elif 'character' in filters:
            code = f'{fr.var}.select_dtypes(exclude="number").columns.tolist()'
        else:
            code = f'{fr.var}.columns.tolist()'
        info = None
        if fr.known and not ('numeric' in filters or 'character' in filters):
            info = {'columns': [c['name'] for c in fr.cols.values()]}
        return E(code, P_ATOM, 'list', info)

    @msg(TMSG, 'Get Name')
    def t_getname(self, fr, m, ctx, want, target, node):
        return E(lit(fr.name), P_ATOM, 'str')

    @msg(TMSG, 'Set Name')
    def t_setname(self, fr, m, ctx, want, target, node):
        a = m.args[0] if m.args else None
        if a is None or a.kind != 'str':
            raise Unconvertible('Set Name() with a name made while the script runs', node)
        self.emit(f'# the table {fr.var} is now called "{one_line(a.value)}"')
        fr.name = a.value
        return E(lit(a.value), P_ATOM, 'str')

    @msg(TMSG, 'Get As Matrix', 'Get All Columns As Matrix')
    def t_getasmatrix(self, fr, m, ctx, want, target, node):
        args = [a for a in m.args if a.kind != 'empty']
        if not args:
            if m.key == 'getallcolumnsasmatrix':
                return E(f'{fr.var}.apply(lambda s: s if s.dtype.kind in "fiub" else pd.factorize(s, sort=True)[0] + 1.0).to_numpy(dtype=float)', P_ATOM, 'matrix')
            return E(f'{fr.var}.select_dtypes("number").to_numpy()', P_ATOM, 'matrix')
        a = args[0]
        if a.kind == 'list' and all(x.kind == 'num' for x in a.args):
            idx = '[' + ', '.join(str(int(x.value) - 1) for x in a.args) + ']'
            return E(f'{fr.var}.iloc[:, {idx}].to_numpy()', P_ATOM, 'matrix')
        names = self.col_names_arg(fr, args, node)
        return E(f'{fr.var}[[{", ".join(lit(n) for n in names)}]].to_numpy()', P_ATOM, 'matrix')

    @msg(TMSG, 'Save', 'Save As')
    def t_save(self, fr, m, ctx, want, target, node):
        args = [a for a in m.args if a.kind != 'empty']
        if not args:
            path = jsl.Node('str', fr.name + '.jmp', line=node.line)
        else:
            path = args[0]
        self.save_table(fr, path, node)
        return E(fr.var, P_ATOM, 'frame', fr)

    @msg(TMSG, 'Reorder By Name')
    def t_reorder(self, fr, m, ctx, want, target, node):
        self.emit(f'{fr.var} = {fr.var}[sorted({fr.var}.columns)]')
        return E(fr.var, P_ATOM, 'frame', fr)

    @msg(TMSG, 'Data Filter')
    def t_datafilter(self, fr, m, ctx, want, target, node):
        raise Unconvertible('Data Filter(): an interactive filter window (a Where() in a launch, or Select Where, converts)', node)

    @msg(TMSG, 'Get Data Table')
    def t_getdt(self, fr, m, ctx, want, target, node):
        return E(fr.var, P_ATOM, 'frame', fr)

    def output_name(self, args, default):
        for a in args:
            a = self.unwrap(a)
            if a.is_call('outputtablename', 'outputtable') and a.args and a.args[0].kind == 'str':
                return a.args[0].value
        return default

    def flags(self, args):
        return {a.value.lower().replace(' ', '') for a in (self.unwrap(x) for x in args) if a.kind in ('str', 'name')}

    def named(self, args, *keys):
        for a in args:
            a = self.unwrap(a)
            if a.kind == 'call' and a.key in keys:
                return a
        return None

    @msg(TMSG, 'Subset')
    def t_subset(self, fr, m, ctx, want, target, node):
        args = [a for a in m.args if a.kind != 'empty']
        flags = self.flags(args)
        cols_node = self.named(args, 'columns')
        rows_node = self.named(args, 'rows')
        rate = self.named(args, 'samplingrate')
        size = self.named(args, 'samplesize')
        if self.named(args, 'by') is not None:
            raise Unconvertible('Subset() with By(): a table for each group', node)
        sel_rows = self.named(args, 'selectedrows')
        use_sel = ('selectedrows' in flags) or (sel_rows is not None and (not sel_rows.args or (sel_rows.args[0].kind == 'num' and sel_rows.args[0].value)))
        code = fr.var
        names = None
        if rows_node is not None and rows_node.args:
            part = self.sub_part(rows_node.args[0], SCALAR, allow_all=False)
            rows = f'[{part[1]}]' if part[0] == 'one' else part[1]
            code = f'{fr.var}.iloc[{rows}]'
        elif use_sel or (fr.masks.get('selected') and rows_node is None and rate is None and size is None):
            sel = fr.masks.get('selected')
            if sel is None:
                raise Unconvertible('Subset() of the selected rows, with no rows selected by the script', node)
            if not use_sel:
                self.note(node.line, 'info', 'Subset(): JMP takes the selected rows when there are any; so does the translation.', once=('subsetsel', node.line))
            code = f'{fr.var}[{sel}]'
        if rate is not None and rate.args:
            code = f'{code}.sample(frac={self.x(rate.args[0], SCALAR).code}, random_state={self.rand(node, ctx)}).sort_index()'
        if size is not None and size.args:
            code = f'{code}.sample(n={self.x(size.args[0], SCALAR).code}, random_state={self.rand(node, ctx)}).sort_index()'
        if cols_node is not None:
            names = self.col_names_arg(fr, cols_node.args, node)
            code = f'{code}[[{", ".join(lit(n) for n in names)}]]'
        elif 'selectedcolumns' in flags:
            raise Unconvertible('Subset() of the selected columns', node)
        var = self.result_var(target, 'subset')
        self.emit(f'{var} = {code}.reset_index(drop=True)')
        new = self.new_frame(var, self.output_name(args, f'Subset of {fr.name}'), 'script')
        new.copy_cols(fr, {jsl.name_key(n) for n in names} if names else None)
        self.cur = new
        return E(var, P_ATOM, 'frame', new)

    SUMMARY_STATS = {'mean': ('Mean', 'mean'), 'stddev': ('Std Dev', 'std'), 'min': ('Min', 'min'), 'max': ('Max', 'max'),
                     'sum': ('Sum', 'sum'), 'median': ('Median', 'median'), 'n': ('N', 'count'), 'nmissing': ('N Missing', None),
                     'variance': ('Variance', 'var'), 'range': ('Range', None), 'cv': ('CV', None), 'stderr': ('Std Err', 'sem'),
                     'ncategories': ('N Categories', 'nunique')}

    @msg(TMSG, 'Summary')
    def t_summary(self, fr, m, ctx, want, target, node):
        args = [self.unwrap(a) for a in m.args if a.kind != 'empty']
        groups = []
        stats_ = []
        fmt_ = 'stat(column)'
        for a in args:
            if a.is_call('group'):
                groups.extend(self.col_names_arg(fr, a.args, node))
            elif a.is_call('subgroup'):
                raise Unconvertible('Summary() with Subgroup(): statistics in columns by the subgroups', node)
            elif a.is_call('freq', 'weight'):
                if not (a.args and a.args[0].kind == 'str' and a.args[0].value.lower() == 'none'):
                    self.note(node.line, 'warn', f'Summary(): {a.value}() is not applied; the statistics weigh every row alike.', once=('sumw', node.line))
            elif a.is_call('statisticscolumnnameformat') and a.args and a.args[0].kind == 'str':
                fmt_ = a.args[0].value.lower()
            elif a.kind == 'call' and a.key in self.SUMMARY_STATS:
                for c in (self.col_names_arg(fr, a.args, node) if a.args else [None]):
                    stats_.append((a.key, c))
            elif a.kind == 'name' and a.key == 'n':
                pass
            elif a.kind == 'call' and a.key in ('quantiles', 'quantile') and len(a.args) >= 2:
                p = self.x(a.args[0], SCALAR)
                for c in self.col_names_arg(fr, a.args[1:], node):
                    stats_.append(('quantile', (c, p.code)))
            elif a.kind in ('str', 'name') and a.value.lower().replace(' ', '') in ('invisible', 'private', 'includemarginalstatistics'):
                if 'marginal' in a.value.lower():
                    self.note(node.line, 'warn', 'Summary(): the marginal statistics are not added.', once=('marg', node.line))
            elif a.is_call('linktooriginaldatatable', 'outputtablename', 'outputtable'):
                pass
            else:
                self.note(node.line, 'info', f'Summary(): {excerpt(self.p.source(a), 30)} is not carried over.', once=('sumopt', a.line))

        def colname(label, c):
            if c is None:
                return label
            return {'column': c, 'stat of column': f'{label} of {c}', 'column stat': f'{c} {label}'}.get(fmt_, f'{label}({c})')

        var = self.result_var(target, 'summary')
        items = []
        if groups:
            g = self.fresh('grouped')
            keys = lit(groups[0]) if len(groups) == 1 else '[' + ', '.join(lit(c) for c in groups) + ']'
            self.emit(f'{g} = {fr.var}.groupby({keys}, dropna=False)')
            items.append((lit('N Rows'), f'{g}.size()'))
            for k, c in stats_:
                if k == 'quantile':
                    col, p = c
                    items.append((lit(f'Quantiles{p}({col})'), f'{g}[{lit(col)}].agg(lambda s: np.nanquantile(s, {p}, method="weibull"))'))
                    continue
                label, how = self.SUMMARY_STATS[k]
                if c is None:
                    continue
                if how:
                    code = f'{g}[{lit(c)}].{how}()'
                elif k == 'nmissing':
                    code = f'{g}[{lit(c)}].agg(lambda s: s.isna().sum())'
                elif k == 'range':
                    code = f'{g}[{lit(c)}].max() - {g}[{lit(c)}].min()'
                else:
                    code = f'100 * {g}[{lit(c)}].std() / {g}[{lit(c)}].mean()'
                items.append((lit(colname(label, c)), code))
            self.emit(f'{var} = pd.DataFrame({{')
            for k, v in items:
                self.emit(f'    {k}: {v},')
            self.emit('}).reset_index()')
        else:
            items.append((lit('N Rows'), f'[len({fr.var})]'))
            for k, c in stats_:
                if k == 'quantile':
                    col, p = c
                    items.append((lit(f'Quantiles{p}({col})'), f'[np.nanquantile({fr.var}[{lit(col)}], {p}, method="weibull")]'))
                    continue
                label, how = self.SUMMARY_STATS[k]
                if c is None:
                    continue
                s = f'{fr.var}[{lit(c)}]'
                code = {'nmissing': f'[{s}.isna().sum()]', 'range': f'[{s}.max() - {s}.min()]', 'cv': f'[100 * {s}.std() / {s}.mean()]'}.get(k, f'[{s}.{how}()]' if how else None)
                items.append((lit(colname(label, c)), code))
            self.emit(f'{var} = pd.DataFrame({{')
            for k, v in items:
                self.emit(f'    {k}: {v},')
            self.emit('})')
        new = self.new_frame(var, self.output_name(args, f'{fr.name} By ({", ".join(groups)})' if groups else f'Summary of {fr.name}'), 'script')
        for c in groups:
            old = fr.col(c)
            new.add_col(c, old['dtype'] if old else None, old['mt'] if old else None)
        for k, _ in items:
            new.add_col(json.loads(k), 'numeric', 'continuous')
        new.known = True
        self.cur = new
        return E(var, P_ATOM, 'frame', new)

    @msg(TMSG, 'Sort')
    def t_sort(self, fr, m, ctx, want, target, node):
        args = [self.unwrap(a) for a in m.args if a.kind != 'empty']
        by = self.named(args, 'by')
        if by is None:
            raise Unconvertible('Sort() without By()', node)
        cols = self.col_names_arg(fr, by.args, node)
        order = self.named(args, 'order')
        asc = []
        if order is not None:
            for a in order.args:
                v = a.value.lower() if a.kind in ('name', 'str') else 'ascending'
                asc.append('False' if v.startswith('desc') else 'True')
        asc = (asc + ['True'] * len(cols))[:len(cols)]
        keys = lit(cols[0]) if len(cols) == 1 else '[' + ', '.join(lit(c) for c in cols) + ']'
        a_ = asc[0] if len(set(asc)) == 1 else '[' + ', '.join(asc) + ']'
        opts = f'{keys}' + ('' if a_ == 'True' else f', ascending={a_}') + ', na_position="first"' + (', kind="stable"' if len(cols) == 1 else '') + ', ignore_index=True'
        if fr.masks:
            self.note(node.line, 'warn', 'Sort(): the row-state masks are not reordered with the rows.', once=('sortmask', node.line))
        if 'replacetable' in self.flags(args):
            self.emit(f'{fr.var} = {fr.var}.sort_values({opts})')
            return E(fr.var, P_ATOM, 'frame', fr)
        var = self.result_var(target, 'sorted_' + fr.var if not fr.var.startswith('sorted') else fr.var + '_sorted')
        self.emit(f'{var} = {fr.var}.sort_values({opts})')
        new = self.new_frame(var, self.output_name(args, f'{fr.name} Sorted'), 'script')
        new.copy_cols(fr)
        self.cur = new
        return E(var, P_ATOM, 'frame', new)

    @msg(TMSG, 'Stack')
    def t_stack(self, fr, m, ctx, want, target, node):
        args = [self.unwrap(a) for a in m.args if a.kind != 'empty']
        cols_node = self.named(args, 'columns')
        if cols_node is None:
            raise Unconvertible('Stack() without Columns()', node)
        cols = self.col_names_arg(fr, cols_node.args, node)
        label = self.named(args, 'sourcelabelcolumn')
        data = self.named(args, 'stackeddatacolumn')
        lab = label.args[0].value if label is not None and label.args and label.args[0].kind == 'str' else 'Label'
        dat = data.args[0].value if data is not None and data.args and data.args[0].kind == 'str' else 'Data'
        drop = self.named(args, 'dropallothercolumns')
        dropping = drop is not None and (not drop.args or (drop.args[0].kind == 'num' and drop.args[0].value))
        if self.named(args, 'numberofseries') is not None:
            raise Unconvertible('Stack() with Number of Series()', node)
        if dropping:
            ids = '[]'
            others = []
        elif fr.known:
            others = [c['name'] for c in fr.cols.values() if jsl.name_key(c['name']) not in {jsl.name_key(x) for x in cols}]
            ids = '[' + ', '.join(lit(c) for c in others) + ']'
        else:
            others = None
            ids = f'[c for c in {fr.var}.columns if c not in [{", ".join(lit(c) for c in cols)}]]'
        var = self.result_var(target, 'stacked')
        self.emit(f'{var} = {fr.var}.melt(id_vars={ids}, value_vars=[{", ".join(lit(c) for c in cols)}], var_name={lit(lab)}, value_name={lit(dat)}, ignore_index=False)')
        self.emit(f'{var} = {var}.sort_index(kind="stable").reset_index(drop=True)   # row by row, as JMP stacks')
        new = self.new_frame(var, self.output_name(args, 'Untitled'), 'script')
        if others is not None:
            for c in others:
                old = fr.col(c)
                new.add_col(c, old['dtype'] if old else None, old['mt'] if old else None)
            new.add_col(lab, 'character', 'nominal')
            new.add_col(dat, None, None)
            new.known = True
        self.cur = new
        return E(var, P_ATOM, 'frame', new)

    @msg(TMSG, 'Split')
    def t_split(self, fr, m, ctx, want, target, node):
        args = [self.unwrap(a) for a in m.args if a.kind != 'empty']
        by = self.named(args, 'splitby')
        what = self.named(args, 'split')
        if by is None or what is None:
            raise Unconvertible('Split() takes Split By() and Split()', node)
        by_c = self.col_names_arg(fr, by.args, node)
        what_c = self.col_names_arg(fr, what.args, node)
        if len(by_c) != 1 or len(what_c) != 1:
            raise Unconvertible('Split() of several columns, or by several', node)
        group = self.named(args, 'group')
        grp = self.col_names_arg(fr, group.args, node) if group is not None else []
        rem = self.named(args, 'remainingcolumns')
        drop_all = rem is not None and rem.args and rem.args[0].kind in ('str', 'name') and rem.args[0].value.lower().replace(' ', '') == 'dropall'
        if not drop_all and fr.known:
            used = {jsl.name_key(c) for c in by_c + what_c + grp}
            if any(jsl.name_key(c['name']) not in used for c in fr.cols.values()):
                self.note(node.line, 'warn', 'Split(): the remaining columns are not kept (JMP keeps them by default).', once=('splitrem', node.line))
        var = self.result_var(target, 'split')
        if grp:
            idx = lit(grp[0]) if len(grp) == 1 else '[' + ', '.join(lit(c) for c in grp) + ']'
            self.emit(f'{var} = {fr.var}.pivot(index={idx}, columns={lit(by_c[0])}, values={lit(what_c[0])}).reset_index().rename_axis(columns=None)')
        else:
            self.emit(f'{var} = ({fr.var}.assign(_row={fr.var}.groupby({lit(by_c[0])}).cumcount())')
            self.emit(f'    .pivot(index="_row", columns={lit(by_c[0])}, values={lit(what_c[0])}).reset_index(drop=True).rename_axis(columns=None))')
        new = self.new_frame(var, self.output_name(args, 'Untitled'), 'script')
        self.cur = new
        return E(var, P_ATOM, 'frame', new)

    @msg(TMSG, 'Join')
    def t_join(self, fr, m, ctx, want, target, node):
        args = [self.unwrap(a) for a in m.args if a.kind != 'empty']
        with_ = self.named(args, 'with')
        if with_ is None or not with_.args:
            raise Unconvertible('Join() without With()', node)
        other = self.frame_of(with_.args[0], ctx, need=False)
        if other is None and with_.args[0].kind == 'str':
            other = self.table_by_arg(with_.args[0], node)
        if other is None:
            raise Unconvertible('Join() with a table not known here', node)
        flags = self.flags(args)
        left, right = fr.var, other.var
        sel = self.named(args, 'select')
        selw = self.named(args, 'selectwith')
        var = self.result_var(target, 'joined')
        if 'byrownumber' in flags:
            code = f'pd.concat([{left}, {right}], axis=1)'
        elif 'cartesian' in flags:
            code = f'{left}.merge({right}, how="cross")'
        else:
            match = self.named(args, 'bymatchingcolumns', 'matchcolumns')
            if match is None:
                raise Unconvertible('Join() without By Matching Columns(), By Row Number or Cartesian', node)
            lk, rk = [], []
            for a in match.args:
                if a.kind == 'assign':
                    l = self.colref(a.args[0], Ctx('vec', fr), quiet=True)
                    r = self.colref(a.args[1], Ctx('vec', other), quiet=True)
                    if l is None or r is None:
                        raise Unconvertible('Join(): a matching column that is not a column', node)
                    lk.append(l.name)
                    rk.append(r.name)
            nm = self.named(args, 'includenonmatches', 'includenonmatch')
            how = 'inner'
            if nm is not None and len(nm.args) == 2 and all(a.kind == 'num' for a in nm.args):
                how = {(1, 0): 'left', (0, 1): 'right', (1, 1): 'outer'}.get((int(nm.args[0].value), int(nm.args[1].value)), 'inner')
            dm = self.named(args, 'dropmultiples')
            if dm is not None and len(dm.args) == 2 and all(a.kind == 'num' for a in dm.args):
                if dm.args[0].value:
                    left = f'{left}.drop_duplicates({lit(lk) if len(lk) > 1 else lit(lk[0])})'
                if dm.args[1].value:
                    right = f'{right}.drop_duplicates({lit(rk) if len(rk) > 1 else lit(rk[0])})'
            if sel is not None:
                cols = self.col_names_arg(fr, sel.args, node)
                left = f'{left}[{json.dumps(sorted(set(cols + lk), key=(cols + lk).index), ensure_ascii=False)}]'
            if selw is not None:
                cols = self.col_names_arg(other, selw.args, node)
                right = f'{right}[{json.dumps(sorted(set(cols + rk), key=(cols + rk).index), ensure_ascii=False)}]'
            keys = f'on={lit(lk[0])}' if lk == rk and len(lk) == 1 else (f'on={json.dumps(lk, ensure_ascii=False)}' if lk == rk else f'left_on={json.dumps(lk, ensure_ascii=False)}, right_on={json.dumps(rk, ensure_ascii=False)}')
            code = f'{left}.merge({right}, {keys}, how={lit(how)}, suffixes=("", {lit(" of " + other.name)}))'
            self.note(node.line, 'info', f'Join(): columns in both tables keep their names from the first; the second\'s are named "... of {other.name}".', once=('join', node.line))
        self.emit(f'{var} = {code}')
        new = self.new_frame(var, self.output_name(args, 'Untitled'), 'script')
        self.cur = new
        return E(var, P_ATOM, 'frame', new)

    @msg(TMSG, 'Concatenate')
    def t_concatenate(self, fr, m, ctx, want, target, node):
        args = [self.unwrap(a) for a in m.args if a.kind != 'empty']
        tables = [fr]
        for a in args:
            if a.kind in ('str',) or a.is_call('outputtablename', 'outputtable') or (a.kind == 'name' and a.key in ('appendtofirsttable', 'createsourcecolumn', 'keepformulas', 'private', 'invisible')):
                continue
            if a.kind == 'list':
                for b in a.args:
                    t = self.frame_of(b, ctx, need=False)
                    if t is not None:
                        tables.append(t)
                continue
            t = self.frame_of(a, ctx, need=False)
            if t is not None:
                tables.append(t)
        flags = self.flags(args)
        if len(tables) < 2:
            raise Unconvertible('Concatenate() with tables not known here', node)
        if 'createsourcecolumn' in flags:
            code = f'pd.concat([{", ".join(t.var for t in tables)}], keys=[{", ".join(lit(t.name) for t in tables)}], names=["Source Table"]).reset_index(level=0).reset_index(drop=True)'
        else:
            code = f'pd.concat([{", ".join(t.var for t in tables)}], ignore_index=True)'
        if 'appendtofirsttable' in flags:
            self.emit(f'{fr.var} = {code}')
            return E(fr.var, P_ATOM, 'frame', fr)
        var = self.result_var(target, 'concatenated')
        self.emit(f'{var} = {code}')
        new = self.new_frame(var, self.output_name(args, 'Untitled'), 'script')
        new.copy_cols(fr)
        self.cur = new
        return E(var, P_ATOM, 'frame', new)

    @msg(TMSG, 'Transpose')
    def t_transpose(self, fr, m, ctx, want, target, node):
        args = [self.unwrap(a) for a in m.args if a.kind != 'empty']
        cols_node = self.named(args, 'columns')
        label = self.named(args, 'label')
        var = self.result_var(target, 'transposed')
        cols = self.col_names_arg(fr, cols_node.args, node) if cols_node is not None else None
        sel = f'[[{", ".join(lit(c) for c in cols)}]]' if cols else ''
        if label is not None and label.args:
            lc = self.col_names_arg(fr, label.args, node)[0]
            self.emit(f'{var} = {fr.var}.set_index({lit(lc)}){sel}.T.rename_axis("Label").reset_index().rename_axis(columns=None)')
        else:
            src = f'{fr.var}{sel}' if sel else f'{fr.var}.select_dtypes("number")'
            self.emit(f'{var} = {src}.T.reset_index()')
            self.emit(f'{var}.columns = ["Label"] + [f"Row {{i + 1}}" for i in range(len({fr.var}))]')
        new = self.new_frame(var, self.output_name(args, f'Transpose of {fr.name}'), 'script')
        self.cur = new
        return E(var, P_ATOM, 'frame', new)

    # ---- column messages --------------------------------------------------------------------------------------
    def rename(self, ref, new, node):
        fr = ref.frame
        self.emit(f'{fr.var} = {fr.var}.rename(columns={{{ref.code}: {lit(new)}}})')
        if ref.name is not None:
            c = fr.cols.pop(jsl.name_key(ref.name), None)
            if c is not None:
                c = dict(c)
                c['name'] = new
                fr.cols[jsl.name_key(new)] = c
            else:
                fr.add_col(new)

    @msg(CMSG, 'Get Values', 'Get As Matrix')
    def c_getvalues(self, ref, m, ctx, want, target, node):
        c = ref.frame.col(ref.name) if ref.name else None
        if c and c.get('dtype') == 'character':
            return E(f'{ref.series()}.tolist()', P_ATOM, 'list')
        return E(f'{ref.frame.var}[[{ref.code}]].to_numpy()', P_ATOM, 'matrix', (None, 1))

    @msg(CMSG, 'Get Name')
    def c_getname(self, ref, m, ctx, want, target, node):
        return E(lit(ref.name) if ref.name else ref.code, P_ATOM, 'str')

    @msg(CMSG, 'Set Name')
    def c_setname(self, ref, m, ctx, want, target, node):
        a = m.args[0] if m.args else None
        if a is None or a.kind != 'str':
            e = self.x(a, SCALAR) if a is not None else None
            if e is None:
                raise Unconvertible('Set Name() without a name', node)
            self.emit(f'{ref.frame.var} = {ref.frame.var}.rename(columns={{{ref.code}: {e.code}}})')
            return E(ref.code, P_ATOM, 'col', ref)
        self.rename(ref, a.value, node)
        new = ColRef(ref.frame, a.value)
        return E(new.code, P_ATOM, 'col', new)

    @msg(CMSG, 'Set Values', 'Values')
    def c_setvalues(self, ref, m, ctx, want, target, node):
        (a,) = self.nargs(m, 1)
        e = self.x(a, SCALAR)
        code = f'np.ravel({e.code})' if e.type == 'matrix' else e.code
        self.emit(f'{ref.series()} = {code}')
        return E(ref.code, P_ATOM, 'col', ref)

    @msg(CMSG, 'Set Formula', 'Formula', 'Set Each Value')
    def c_setformula(self, ref, m, ctx, want, target, node):
        (a,) = self.nargs(m, 1)
        self.formula(ref, a, node)
        if m.key != 'seteachvalue':
            self.note(node.line, 'info', 'Formula columns are computed once here, when the column is made; JMP keeps them up to date as the table changes.', once='formula')
        return E(ref.code, P_ATOM, 'col', ref)

    @msg(CMSG, 'Set Modeling Type', 'Modeling Type')
    def c_setmt(self, ref, m, ctx, want, target, node):
        a = m.args[0] if m.args else None
        v = jsl.name_key(a.value) if a is not None and a.kind in ('str', 'name') else None
        if v not in ('continuous', 'nominal', 'ordinal'):
            raise Unconvertible('Set Modeling Type() of this kind', node)
        s = ref.series()
        if v == 'nominal':
            self.emit(f'{s} = {s}.astype("category")')
        elif v == 'ordinal':
            self.emit(f'{s} = pd.Categorical({s}, ordered=True)')
        else:
            self.emit(f'{s} = pd.to_numeric({s}, errors="coerce")')
        if ref.name:
            ref.frame.add_col(ref.name, mt=v, new=False)
        self.note(node.line, 'info', f'Set Modeling Type("{a.value}"): here a pandas dtype ({"category" if v != "continuous" else "float"}); the page\'s analyses take the modeling type from the page\'s table, so set it there too (Cols > Modeling Type).', once=('mt', ref.name, v))
        return E(ref.code, P_ATOM, 'col', ref)

    @msg(CMSG, 'Set Data Type', 'Data Type')
    def c_setdt(self, ref, m, ctx, want, target, node):
        a = m.args[0] if m.args else None
        v = jsl.name_key(a.value) if a is not None and a.kind in ('str', 'name') else None
        s = ref.series()
        if v == 'character':
            self.helper('jsl_char')
            self.emit(f'{s} = {s}.map(jsl_char).replace(".", "")   # missing values become empty text, as in JMP')
            if ref.name:
                ref.frame.add_col(ref.name, dtype='character', mt='nominal', new=False)
        elif v == 'numeric':
            self.emit(f'{s} = pd.to_numeric({s}, errors="coerce")')
            if ref.name:
                ref.frame.add_col(ref.name, dtype='numeric', new=False)
        else:
            raise Unconvertible('Set Data Type() of this kind', node)
        return E(ref.code, P_ATOM, 'col', ref)

    @msg(CMSG, 'Get Modeling Type')
    def c_getmt(self, ref, m, ctx, want, target, node):
        c = ref.frame.col(ref.name) if ref.name else None
        if not c or not c.get('mt'):
            raise Unconvertible('Get Modeling Type() of a column whose modeling type is not known', node)
        return E(lit(c['mt'].title()), P_ATOM, 'str')

    @msg(CMSG, 'Get Data Type')
    def c_getdt(self, ref, m, ctx, want, target, node):
        c = ref.frame.col(ref.name) if ref.name else None
        if not c or not c.get('dtype'):
            raise Unconvertible('Get Data Type() of a column whose data type is not known', node)
        return E(lit(c['dtype'].title()), P_ATOM, 'str')

    @msg(CMSG, 'Get Formula', 'Get Property', 'Get Script', 'Get Value Labels', 'Get Role')
    def c_get_unknown(self, ref, m, ctx, want, target, node):
        raise Unconvertible(f'{m.value}: JMP\'s column properties and formulas are not in the CSV the page writes', node)

    # ---- associative array messages ------------------------------------------------------------------------------
    @msg(DMSG, 'Get Keys')
    def d_keys(self, d, m, ctx, want, target, node):
        return E(f'sorted({d.code})', P_ATOM, 'list')

    @msg(DMSG, 'Get Values')
    def d_values(self, d, m, ctx, want, target, node):
        if m.args and m.args[0].kind != 'empty':
            keys = self.x(m.args[0], ctx)
            return E(f'[{d.code}[k] for k in {keys.code}]', P_ATOM, 'list')
        return E(f'[{d.code}[k] for k in sorted({d.code})]', P_ATOM, 'list')

    @msg(DMSG, 'Get Value')
    def d_value(self, d, m, ctx, want, target, node):
        (k,) = self.a(m, ctx, 1)
        return E(f'{par(d, P_ATOM)}[{k.code}]', P_ATOM, 'unknown')

    @msg(DMSG, 'Insert', 'Insert Item')
    def d_insert(self, d, m, ctx, want, target, node):
        args = self.a(m, ctx, 1, 2)
        v = args[1].code if len(args) == 2 else '1'
        self.emit(f'{par(d, P_ATOM)}[{args[0].code}] = {v}')
        return d

    @msg(DMSG, 'Remove', 'Remove Item')
    def d_remove(self, d, m, ctx, want, target, node):
        (k,) = self.a(m, ctx, 1)
        self.emit(f'{par(d, P_ATOM)}.pop({k.code}, None)')
        return d

    @msg(DMSG, 'Contains')
    def d_contains(self, d, m, ctx, want, target, node):
        (k,) = self.a(m, ctx, 1)
        return E(f'{par(k, P_CMP + 1)} in {par(d, P_CMP + 1)}', P_CMP, 'bool')

    @msg(DMSG, 'N Items')
    def d_nitems(self, d, m, ctx, want, target, node):
        return E(f'len({d.code})', P_ATOM, 'int')

    @msg(DMSG, 'Get Contents')
    def d_contents(self, d, m, ctx, want, target, node):
        return E(f'[list(kv) for kv in sorted({d.code}.items())]', P_ATOM, 'list')


# Set Alpha Level, as JMP writes it in scripts (with the Greek letter) and as users do
ALPHA_KEYS = ('setalphalevel', 'setαlevel', 'alphalevel', 'αlevel')

# JSL platform launches -> the page's platform ids (None: JMP has it, the page has not)
PLATFORMS = {
    'distribution': 'distribution', 'bivariate': 'fitybyx', 'oneway': 'fitybyx', 'contingency': 'fitybyx', 'logistic': 'fitybyx',
    'fitybyx': 'fitybyx', 'matchedpairs': 'matchedpairs', 'fitmodel': 'fitmodel', 'multivariate': 'multivariate',
    'principalcomponents': 'pca', 'factoranalysis': 'factor', 'discriminant': 'discriminant', 'hierarchicalcluster': 'hcluster',
    'kmeanscluster': 'kmeans', 'kmeans': 'kmeans', 'partition': 'partition', 'bootstrapforest': 'forest', 'boostedtree': 'boosted',
    'neural': 'neural', 'timeseries': 'timeseries', 'controlchartbuilder': 'controlchart', 'controlchart': 'controlchart',
    'survival': 'survival', 'lifedistribution': 'lifedist', 'fitparametricsurvival': 'parametric', 'fitproportionalhazards': 'phreg',
    'graphbuilder': 'graphbuilder', 'tabulate': 'tabulate', 'overlayplot': 'overlay', 'scatterplotmatrix': 'scattermatrix',
    'chart': 'chart', 'paretoplot': 'pareto', 'variabilitychart': 'variability', 'variabilityattributegaugechart': 'variability',
    'bubbleplot': 'bubble', 'cellplot': 'cellplot', 'treemap': 'treemap', 'parallelplot': 'parallel', 'ternaryplot': 'ternary',
    'scatterplot3d': 'scatter3d', 'processcapability': 'capability', 'fitcurve': 'fitcurve', 'nonlinear': 'nonlinear',
    'responsescreening': 'respscreen', 'exploreoutliers': 'outliers', 'exploremissingvalues': 'missing',
    'multidimensionalscaling': 'mds', 'multiplecorrespondenceanalysis': 'mca', 'normalmixtures': 'mixtures',
    'knearestneighbors': 'knn', 'naivebayes': 'naivebayes', 'supportvectormachines': 'svm', 'modelscreening': 'screening',
    'partialleastsquares': 'pls', 'gaussianprocess': 'gaussproc', 'textexplorer': 'text', 'columnsviewer': 'colviewer',
    'contourplot': 'contour', 'surfaceplot': 'surface', 'multivariateembedding': 'embedding',
    # JMP's platforms the page does not have
    'fitlifebyx': None, 'reliabilitygrowth': None, 'reliabilityblockdiagram': None, 'repairablesystemssimulation': None,
    'itemanalysis': None, 'choice': None, 'uplift': None, 'associationanalysis': None, 'structuralequationmodels': None,
    'functionaldataexplorer': None, 'measurementsystemsanalysis': None, 'processscreening': None, 'modelcomparison': None,
    'profiler': None, 'contourprofiler': None, 'surfaceprofiler': None, 'mixtureprofiler': None, 'customprofiler': None,
    'latentclassanalysis': None, 'clustervariables': None, 'predictorscreening': None, 'mixedmodel': None, 'diagram': None,
    'fitgroup': None, 'managespeclimits': None, 'uniformplot': None, 'dataviewer': None,
    'formuladepot': None, 'querybuilder': None, 'samplesizeexplorers': None, 'customdesign': None, 'doe': None,
    'singularvaluedecomposition': None, 'topicanalysis': None, 'featureselection': None,
}

# the page's roles of each platform
PAGE_ROLES = {
    'distribution': ['y', 'weight', 'freq', 'by'], 'fitybyx': ['y', 'x', 'block', 'weight', 'freq', 'by'], 'matchedpairs': ['y', 'x', 'by'],
    'fitmodel': ['y', 'weight', 'freq', 'validation', 'endog', 'instruments', 'offset', 'subject', 'time', 'subgroup', 'by'],
    'multivariate': ['y', 'weight', 'freq', 'by'], 'pca': ['y', 'weight', 'freq', 'by'], 'factor': ['y', 'weight', 'freq', 'by'],
    'discriminant': ['y', 'x', 'weight', 'freq', 'by'], 'hcluster': ['y', 'label', 'by'], 'kmeans': ['y', 'weight', 'freq', 'by'],
    'partition': ['y', 'x', 'weight', 'freq', 'validation', 'by'], 'forest': ['y', 'x', 'weight', 'freq', 'validation', 'by'],
    'boosted': ['y', 'x', 'weight', 'freq', 'validation', 'by'], 'neural': ['y', 'x', 'weight', 'freq', 'validation', 'by'],
    'knn': ['y', 'x', 'weight', 'freq', 'validation', 'by'], 'naivebayes': ['y', 'x', 'weight', 'freq', 'validation', 'by'],
    'svm': ['y', 'x', 'weight', 'freq', 'validation', 'by'], 'screening': ['y', 'x', 'weight', 'freq', 'validation', 'by'],
    'timeseries': ['y', 'inputs', 'time', 'by'], 'controlchart': ['y', 'subgroup', 'phase', 'ntrials', 'by'],
    'capability': ['y', 'subgroup', 'by'], 'pareto': ['y', 'x', 'freq', 'by'], 'variability': ['y', 'x', 'part', 'standard', 'by'],
    'survival': ['y', 'censor', 'group', 'freq', 'by'], 'lifedist': ['y', 'censor', 'freq', 'by'],
    'parametric': ['y', 'censor', 'x', 'freq', 'by'], 'phreg': ['y', 'censor', 'x', 'freq', 'by'],
    'fitcurve': ['y', 'x', 'group', 'weight', 'by'], 'nonlinear': ['y', 'weight', 'by'], 'respscreen': ['y', 'x', 'weight', 'freq', 'by'],
    'outliers': ['y', 'label', 'by'], 'missing': ['y', 'by'], 'mds': ['y', 'label', 'by'], 'mca': ['y', 'freq', 'by'],
    'mixtures': ['y', 'freq', 'by'], 'overlay': ['y', 'x', 'group', 'by'], 'scattermatrix': ['y', 'x', 'group', 'by'],
    'chart': ['y', 'x', 'by'], 'bubble': ['y', 'x', 'id', 'time', 'size', 'color', 'freq', 'by'], 'cellplot': ['y', 'x', 'by'],
    'treemap': ['x', 'size', 'color', 'by'], 'parallel': ['y', 'x', 'by'], 'ternary': ['y', 'color', 'by'], 'scatter3d': ['y', 'color', 'by'],
}

# JSL's role names -> the page's role keys (only those the platform has are kept)
ROLE_NAMES = {
    'y': 'y', 'x': 'x', 'by': 'by', 'weight': 'weight', 'freq': 'freq', 'block': 'block', 'label': 'label', 'group': 'group',
    'grouping': 'group', 'censor': 'censor', 'validation': 'validation', 'subgroup': 'subgroup', 'phase': 'phase', 'id': 'id',
    'sizes': 'size', 'size': 'size', 'coloring': 'color', 'color': 'color', 'cause': 'y', 'part': 'part', 'partsampleid': 'part',
    'standard': 'standard', 'offset': 'offset', 'column': 'y', 'columns': 'y', 'processvariables': 'y', 'timeid': 'time',
    'inputlist': 'inputs', 'input': 'inputs', 'categories': 'x', 'ntrials': 'ntrials',
    'endogenous': 'endog', 'instruments': 'instruments', 'subject': 'subject', 'time': 'time', 'ycolumns': 'y',
}

LAUNCH_DISPLAY = {'sendtoreport', 'dispatch', 'automaticrecalc', 'invisible', 'title', 'size', 'framesize', 'showcontrolpanel',
                  'reportview', 'columnswitcher', 'fitgroup', 'showlegend', 'legendposition', 'legendmodel', 'xaxisproportional',
                  'showpoints', 'grid', 'legend', 'sizewindow', 'bringwindowtofront', 'savescripttodatatable'}

# Distribution: JSL option -> (page option, kind)
DIST_BOOL = {'quantiles': 'quantiles', 'summarystatistics': 'summary', 'normalquantileplot': 'qq', 'outlierboxplot': 'box',
             'quantileboxplot': 'qbox', 'stemandleaf': 'stem', 'cdfplot': 'cdf', 'horizontallayout': 'horizontal',
             'histogram': 'histogram', 'showcounts': 'showCounts', 'showpercents': 'showPercents', 'frequencies': 'frequencies',
             'mosaicplot': 'mosaic', 'stderrprob': 'stderr', 'normalitytests': 'normality'}
DIST_FITS = {'normal': 'normal', 'cauchy': 'cauchy', "student'st": 't', 'studentst': 't', 't': 't', 'lognormal': 'lognormal', 'weibull': 'weibull',
             'exponential': 'exponential', 'gamma': 'gamma', 'beta': 'beta', 'logistic': 'logistic', 'normal2mixture': 'normal2',
             'normal3mixture': 'normal3', 'johnsonsu': 'johnsonsu', 'johnsonsb': 'johnsonsb', 'smoothcurve': 'kde', 'poisson': 'poisson',
             'gammapoisson': 'negbin', 'negativebinomial': 'negbin'}
DIST_STATS = {'mean': 'mean', 'stddev': 'sd', 'stderrmean': 'se', 'uppermeanconfidenceinterval': 'upper', 'lowermeanconfidenceinterval': 'lower',
              'uppermean': 'upper', 'lowermean': 'lower', 'n': 'n', 'sumweight': 'sumw', 'sum': 'sum', 'variance': 'var', 'skewness': 'skewness',
              'kurtosis': 'kurtosis', 'cv': 'cv', 'nmissing': 'nmiss', 'nzero': 'nzero', 'nunique': 'nunique', 'uncorrectedss': 'uss',
              'correctedss': 'css', 'autocorrelation': 'autocorr', 'minimum': 'min', 'maximum': 'max', 'median': 'median', 'mode': 'mode',
              'trimmedmean': 'trimmed', 'geometricmean': 'geomean', 'range': 'range', 'interquartilerange': 'iqr',
              'medianabsolutedeviation': 'mad', 'robustmean': 'robust_mean', 'robuststddev': 'robust_sd'}

FYX_OW_BOOL = {'ttest': 'ttest', 'boxplots': 'box', 'meandiamonds': 'diamonds', 'meanlines': 'meanLines', 'meancilines': 'ciLines',
               'meanerrorbars': 'errorBars', 'stddevlines': 'sdLines', 'grandmean': 'grandMean', 'connectmeans': 'connect',
               'comparisoncircles': 'circles', 'pointsjittered': 'jitter', 'points': 'points', 'unequalvariances': 'unequal',
               'anom': 'anom', 'cdfplot': 'cdf', 'showpoints': 'points'}
FYX_CT_BOOL = {'mosaicplot': 'mosaic', 'contingencytable': 'ctable', 'tests': 'tests', 'analysisofmeansforproportions': 'anomp',
               'correspondenceanalysis': 'ca', 'agreementstatistic': 'agree', 'relativerisk': 'rr', 'oddsratio': 'or',
               'riskdifference': 'rd', 'twosampletestforproportions': 'twoProp', 'measuresofassociation': 'measures',
               'cochranarmitagetrendtest': 'trend'}
FYX_LG_BOOL = {'logisticplot': 'lplot', 'oddsratios': 'odds', 'roccurve': 'roc', 'liftcurve': 'lift', 'confusionmatrix': 'confusion'}
FYX_BV_BOOL = {'histogramborders': 'hist', 'summarystatistics': 'summary', 'showpoints': 'points'}
CT_CELLS = {'count': 'count', 'total%': 'total', 'col%': 'col', 'row%': 'row', 'expected': 'expected', 'deviation': 'deviation', 'cellchisquare': 'cellchi'}

FM_PERSONALITY = {'standardleastsquares': 'standard', 'stepwise': 'stepwise', 'generalizedlinearmodel': 'glm', 'nominallogistic': 'nominal',
                  'ordinallogistic': 'ordinal', 'mixedmodel': 'mixed', 'manova': 'manova', 'generalizedregression': 'genreg'}
FM_DIST = {'normal': 'normal', 'binomial': 'binomial', 'poisson': 'poisson', 'gamma': 'gamma', 'inversegaussian': 'invgauss', 'negativebinomial': 'negbin'}
FM_LINK = {'identity': 'identity', 'logit': 'logit', 'probit': 'probit', 'log': 'log', 'reciprocal': 'reciprocal', 'comploglog': 'cloglog'}
FM_RUN = {'summaryoffit': 'summaryOfFit', 'analysisofvariance': 'anova', 'parameterestimates': 'estimates', 'lackoffit': 'lackOfFit',
          'effecttests': 'effectTests', 'effectdetails': 'effectDetails', 'plotactualbypredicted': 'plotActual',
          'plotresidualbypredicted': 'plotResidPred', 'plotresidualbyrow': 'plotResidRow', 'plotstudentizedresiduals': 'plotStudent',
          'ploteffectleverage': 'plotLeverage', 'plotresidualbynormalquantiles': 'plotResidQQ', 'plotregression': 'plotRegression',
          'boxcoxytransformation': 'boxcox', 'profiler': 'profiler', 'predictionprofiler': 'profiler', 'contourprofiler': 'contour',
          'interactionplots': 'interaction', 'sortedestimates': 'sortedEst', 'showpredictionexpression': 'expression',
          'sequentialtests': 'sequential', 'correlationofestimates': 'corr', 'press': 'press', 'durbinwatsontest': 'dw', 'aicc': 'aicc',
          'effectsummary': 'effectSummary', 'showallconfidenceintervals': 'showCI', 'likelihoodratiotests': 'effectTests',
          'oddsratios': 'odds', 'confusionmatrix': 'confusion', 'roccurve': 'roc', 'waldtests': 'wald', 'confidenceintervals': 'showCI',
          'wholemodeltest': 'wholeModel', 'goodnessoffitstatistic': 'gof', 'overdispersiontestsandintervals': 'overdispersion',
          'logisticplot': 'logisticPlot', 'fitdetails': 'fitDetails', 'studentizeddevianceresidualsbypredicted': 'studDev',
          'actualbypredictedplot': 'actualPred', 'linearpredictorplot': 'linPlot', 'randomeffectspredictions': 'blups'}

MV_BOOL = {'correlationsmultivariate': 'corr', 'correlationprobability': 'corrProb', 'ciofcorrelation': 'ci', 'inversecorrelations': 'inverse',
           'partialcorrelations': 'partial', 'covariancematrix': 'cov', 'pairwisecorrelations': 'pairwise',
           'univariatesimplestatistics': 'simpleUni', 'multivariatesimplestatistics': 'simpleMulti', 'mahalanobisdistances': 'mahal',
           'jackknifedistances': 'jack', 't²': 't2', 't²plot': 't2', 't2': 't2', 'colormaponcorrelations': 'cmCorr',
           'colormaponp-values': 'cmP', 'colormaponpvalues': 'cmP', 'clusterthecorrelations': 'cmCluster', "cronbach'sα": 'alpha:raw',
           'standardizedα': 'alpha:std', 'distancecorrelations': 'dcor', 'intraclasscorrelations': 'icc', "kendall'sw": 'kendallw'}
SPLOM = {'densityellipses': 'spEllipses', 'shadedellipses': 'spShaded', 'showcorrelations': 'spCorr', 'showhistogram': 'spHist',
         'showhistograms': 'spHist', 'fitline': 'spFit', 'showpoints': 'spPoints'}
PCA_BOOL = {'eigenvalues': 'eigen', 'eigenvectors': 'eigvec', 'bartletttest': 'bartlett', 'loadingmatrix': 'loadmat',
            'formattedloadingmatrix': 'fmtload', 'summaryplots': 'summary', 'biplot': 'biplot', 'screeplot': 'scree', 'scoreplot': 'score',
            'loadingplot': 'loadplot', 'scoreellipses': 'ellipse', 'correlations': 'corrmat', 'covariancematrix': 'covmat'}
GB_ELEMENTS = {'points': 'points', 'smoother': 'smoother', 'lineoffit': 'fit', 'ellipse': 'ellipse', 'contour': 'contour', 'line': 'line',
               'bar': 'bar', 'area': 'area', 'boxplot': 'box', 'histogram': 'histogram', 'heatmap': 'heatmap', 'mosaic': 'mosaic',
               'captionbox': 'caption', 'pie': 'pie', 'bean': 'bean'}
GB_ZONES = {'x': 'x', 'y': 'y', 'groupx': 'groupX', 'groupy': 'groupY', 'wrap': 'wrap', 'overlay': 'overlay', 'color': 'color',
            'size': 'size', 'freq': 'freq'}
GB_STATS = {'n': 'n', 'mean': 'mean', 'median': 'median', 'sum': 'sum', 'min': 'min', 'max': 'max', 'range': 'range', 'stddev': 'sd',
            'stderr': 'se', 'variance': 'var', '%oftotal': 'pct', 'firstquartile': 'q1', 'thirdquartile': 'q3'}


def truth(node):
    """An option's on/off: X, X(1) on; X(0) off."""
    if node.kind == 'name' or not node.args:
        return True
    a = node.args[0]
    if a.kind == 'num':
        return bool(a.value)
    return True


class _Platforms(_Tables):
    # ---- the launch ----------------------------------------------------------------------------
    def launch(self, node, ctx, recv, target, target_var=None, whole=None):
        """A platform launch: a step (the page's platform, roles and
        options) and its marker in the Python."""
        whole = whole or node
        key = node.key
        pid = PLATFORMS.get(key)
        if key in PLATFORMS and pid is None:
            raise Unconvertible(f'{node.value}: the page has no such platform', whole)
        if isinstance(recv, Frame):
            fr = recv
        elif isinstance(recv, jsl.Node):
            fr = self.frame_of(recv, ctx)
        else:
            fr = self.current_frame(node)
        args = [self.unwrap(a) for a in (node.args if node.kind == 'call' else []) if a.kind != 'empty']
        if key == 'tabulate':
            self.tabulate(fr, args, whole, target)
            return None
        roles_raw, opts, where, display = {}, [], None, []
        for a in args:
            k = a.key if a.kind in ('call', 'name') else None
            if k in ('where',) and a.args:
                where = a.args[0]
            elif k == 'localdatafilter':
                w = [n for n in a.walk() if n.kind == 'call' and n.key == 'where' and n.args]
                if w:
                    cond = w[0].args[0]
                    for more in w[1:]:
                        cond = jsl.Node('binop', '&', [cond, more.args[0]], line=a.line, start=a.start, end=a.end)
                    where = cond if where is None else jsl.Node('binop', '&', [where, cond], line=a.line)
                    self.note(whole.line, 'info', f'{node.value}: the Local Data Filter\'s selection becomes the rows of the analysis.', once=('ldf', whole.line))
                else:
                    display.append('Local Data Filter')
            elif k in LAUNCH_DISPLAY:
                display.append(a.value)
            elif k in ROLE_NAMES and a.kind == 'call' and key not in ('graphbuilder', 'controlchartbuilder', 'chart'):
                try:
                    roles_raw.setdefault(k, []).extend(self.role_names(fr, a.args, whole))
                except Dynamic:
                    if any(x.kind == 'num' for x in a.args):
                        opts.append(a)
                        continue
                    raise Dynamic(f'{node.value}: the columns are chosen while the script runs, so the launch is not converted')
            else:
                opts.append(a)
        step = {'id': f'p{len(self.steps) + 1}', 'line': whole.line, 'jsl': self.p.source(whole), 'platform': pid,
                'table': fr.page['name'] if fr.page else None, 'frame': fr.var, 'roles': {}, 'options': {}, 'where': None,
                'marker': None}
        mapper = getattr(self, f'map_{pid}', None)
        if mapper is None:
            self.map_generic(step, fr, roles_raw, opts, whole, node)
        else:
            mapper(step, fr, roles_raw, opts, whole, node)
        for r in list(step['roles']):
            if not step['roles'][r]:
                del step['roles'][r]
        # the rows: Where() and the rows the script excluded
        conds = []
        if 'excluded' in fr.masks:
            conds.append(f'~{fr.masks["excluded"]}')
        if where is not None:
            e = self.x(where, Ctx('vec', fr, cond=True))
            conds.append(par(e, P_BAND + 1) if conds else e.code)
            f = self.filter_spec(where, fr)
            step['filter'] = f
            if f is None:
                self.note(whole.line, 'info', f'{node.value}: Where({excerpt(self.p.source(where), 40)}) is the step\'s where; it is not one the page\'s Local Data Filter can hold.', once=('where', whole.line))
        if conds:
            step['where'] = ' & '.join(conds)
        if display:
            self.note(whole.line, 'info', f'{node.value}: display settings ({", ".join(sorted(set(display)))}) are not carried over.', once=('display', whole.line))
        new = sorted({c for cols in step['roles'].values() for c in cols if (fr.col(c) or {}).get('new')})
        if new:
            step['new_columns'] = new
            where_named = "the page's table " + fr.page['name'] if fr.page else "the page's table"
            self.note(whole.line, 'warn', f'{node.value} uses {", ".join(new)}, which the script makes; {where_named} does not have {"it" if len(new) == 1 else "them"}.', once=('newcols', whole.line))
        if self.loops:
            self.note(whole.line, 'info', f'{node.value} is inside a loop: the page puts its code there, and it runs each time round.', once=('loop', whole.line))
        step['marker'] = f'# <<smui:{step["id"]}>>'
        self.steps.append(step)
        self.emit(step['marker'])
        if target is not None:
            self.vtypes[target.key] = E(None, P_ATOM, 'platform', step)
        return step

    def role_names(self, fr, args, node):
        out = []
        for a in args:
            a = self.unwrap(a)
            if a.is_call('eval') and len(a.args) == 1:
                out.extend(self.role_names(fr, a.args, node))
                continue
            if a.kind == 'name' and self.typeof(a.key) == 'col':
                out.append(self.vtypes[a.key].info.name)
                continue
            if a.kind == 'call' and a.key in ('mean', 'sum', 'n', 'max', 'min', 'stddev', 'median', '%oftotal') and a.args:
                out.extend(self.role_names(fr, a.args, node))
                continue
            out.extend(self.col_names_arg(fr, [a], node))
        return [c for c in out if c is not None]

    def put_roles(self, step, pid, roles_raw, extra_map=None):
        allowed = PAGE_ROLES.get(pid, [])
        for k, cols in roles_raw.items():
            page = (extra_map or {}).get(k) or ROLE_NAMES.get(k)
            if page in allowed:
                lst = step['roles'].setdefault(page, [])
                lst.extend(c for c in cols if c not in lst)
            else:
                self.note(step['line'], 'warn', f'{k.title()}(): the page\'s {pid} has no such role; left out.', once=('role', step['line'], k))

    def unsupported(self, step, what, name, opts):
        if opts:
            names = ', '.join(sorted({excerpt(o.value if o.kind in ('call', 'name') else self.p.source(o), 40) for o in opts}))
            self.note(step['line'], 'info', f'{name}: {names}: {"not options" if len(opts) > 1 else "not an option"} of the page\'s {what}; left out (the analysis still runs).', once=('unsup', step['line']))

    def num_arg(self, node, i=0, default=None):
        args = [a for a in node.args if a.kind != 'empty'] if node.kind == 'call' else []
        if len(args) > i and args[i].kind == 'num':
            return args[i].value
        if len(args) > i and args[i].kind == 'unary' and args[i].args[0].kind == 'num':
            return -args[i].args[0].value
        return default

    def str_arg(self, node, i=0, default=None):
        args = [a for a in node.args if a.kind != 'empty'] if node.kind == 'call' else []
        if len(args) > i and args[i].kind in ('str', 'name'):
            return args[i].value
        return default

    def mt_of(self, fr, name):
        c = fr.col(name)
        return (c or {}).get('mt') or ('nominal' if (c or {}).get('dtype') == 'character' else 'continuous')

    # ---- where as the page's Local Data Filter ----------------------------------------------------
    def filter_spec(self, cond, fr):
        """A Where() the page's filter holds: [{col, levels}] or [{col, lo, hi}]; else None."""
        out = []

        def value(n):
            if n.kind in ('num', 'str'):
                return n.value
            if n.kind == 'unary' and n.value == '-' and n.args[0].kind == 'num':
                return -n.args[0].value
            raise ValueError

        def col(n):
            ref = self.colref(n, Ctx('vec', fr), quiet=True) if n.kind in ('col', 'scope', 'name', 'call') else None
            if ref is None or ref.name is None:
                raise ValueError
            return ref.name

        def part(n):
            if n.kind == 'binop' and n.value in ('&', ':&'):
                part(n.args[0])
                part(n.args[1])
                return
            if n.kind == 'binop' and n.value in ('|', ':|'):
                items = []

                def ors(m):
                    if m.kind == 'binop' and m.value in ('|', ':|'):
                        ors(m.args[0])
                        ors(m.args[1])
                    elif m.kind == 'cmp' and m.value == ['=='] and m.args[1].kind in ('num', 'str'):
                        items.append((col(m.args[0]), value(m.args[1])))
                    else:
                        raise ValueError
                ors(n)
                if len({c for c, _ in items}) != 1:
                    raise ValueError
                out.append({'col': items[0][0], 'levels': [v for _, v in items]})
                return
            if n.is_call('contains') and len(n.args) == 2 and n.args[0].kind == 'list':
                out.append({'col': col(n.args[1]), 'levels': [value(v) for v in n.args[0].args]})
                return
            if n.kind == 'cmp':
                ops, a = n.value, n.args
                if ops == ['=='] and a[1].kind in ('num', 'str'):
                    out.append({'col': col(a[0]), 'levels': [value(a[1])]})
                    return
                if ops == ['<=', '<='] and len(a) == 3:
                    out.append({'col': col(a[1]), 'lo': value(a[0]), 'hi': value(a[2])})
                    return
                if len(ops) == 1 and ops[0] in ('>=', '<='):
                    if a[1].kind in ('num',) or (a[1].kind == 'unary' and a[1].args[0].kind == 'num'):
                        c, v = col(a[0]), value(a[1])
                        out.append({'col': c, 'lo': v, 'hi': None} if ops[0] == '>=' else {'col': c, 'lo': None, 'hi': v})
                        return
                    c, v = col(a[1]), value(a[0])
                    out.append({'col': c, 'lo': None, 'hi': v} if ops[0] == '>=' else {'col': c, 'lo': v, 'hi': None})
                    return
            raise ValueError
        try:
            part(cond)
        except ValueError:
            return None
        return out

    # ---- Distribution ----------------------------------------------------------------------------------
    def map_distribution(self, step, fr, roles_raw, opts, whole, node):
        ys = list(roles_raw.pop('y', [])) + list(roles_raw.pop('column', [])) + list(roles_raw.pop('columns', []))
        o = step['options']
        left = []
        for a in opts:
            k = a.key
            if k in ('continuousdistribution', 'nominaldistribution', 'ordinaldistribution'):
                colnode = next((x for x in a.args if x.is_call('column')), None)
                if colnode is None:
                    left.append(a)
                    continue
                names = self.role_names(fr, colnode.args, whole)
                for c in names:
                    if c not in ys:
                        ys.append(c)
                for sub in a.args:
                    if sub is colnode or sub.kind == 'empty':
                        continue
                    sub = self.unwrap(sub)
                    for c in names:
                        if not self.dist_option(o, c, sub, fr, step):
                            left.append(sub)
            elif k == 'stack':
                o['stack'] = truth(a)
            elif k == 'uniformscaling':
                o['uniform'] = truth(a)
            elif k == 'histogramsonly':
                o['histOnly'] = truth(a)
            elif k == 'arrangeinrows':
                o['perRow'] = int(self.num_arg(a, 0, 0) or 0)
            elif not self.dist_option(o, None, a, fr, step):
                left.append(a)
        roles_raw['y'] = ys
        self.put_roles(step, 'distribution', roles_raw)
        seen = []
        for a in left:
            if a not in seen:
                seen.append(a)
        self.unsupported(step, 'Distribution', 'Distribution', seen)

    def dist_option(self, o, col, a, fr, step):
        """One Distribution option into the page's options (scoped by the column)."""
        if a.kind not in ('call', 'name'):
            return False
        k = a.key
        key = (lambda name: f'{col}|{name}' if col else name)
        cat = col is not None and self.mt_of(fr, col) in ('nominal', 'ordinal')
        if k in DIST_BOOL:
            o[key(DIST_BOOL[k])] = truth(a)
        elif k == 'vertical':
            o[key('horizontal')] = not truth(a)
        elif k in ('countaxis', 'probaxis', 'densityaxis'):
            if truth(a):
                o[key('axis')] = k[:-4]
        elif k in ('setbinwidth', 'binwidth'):
            w = self.num_arg(a)
            if w is None:
                return False
            o[key('binWidth')] = w
        elif k == 'testmean':
            mu = self.num_arg(a)
            if mu is None:
                return False
            o[key('testMean')] = {'mu': mu, 'sigma': self.num_arg(a, 1)}
        elif k == 'teststddev':
            s = self.num_arg(a)
            if s is None:
                return False
            o[key('testSd')] = {'sigma': s}
        elif k == 'confidenceinterval':
            lv = self.num_arg(a, 0, 0.95)
            o[key('ciCat' if cat else 'ci')] = lv
        elif k == 'predictioninterval':
            o[key('pi')] = {'level': self.num_arg(a, 0, 0.95), 'k': int(self.num_arg(a, 1, 1) or 1)}
        elif k == 'toleranceinterval':
            o[key('ti')] = {'level': self.num_arg(a, 0, 0.95), 'coverage': self.num_arg(a, 1, 0.9)}
        elif k == 'capabilityanalysis':
            lim = {}
            for s in a.args:
                if s.kind == 'call' and s.key in ('lsl', 'usl', 'target'):
                    lim[s.key] = self.num_arg(s)
            if not lim:
                return False
            o[key('cap')] = {'lsl': lim.get('lsl'), 'usl': lim.get('usl'), 'target': lim.get('target')}
        elif k == 'fitdistribution' or (k.startswith('fit') and k[3:] in DIST_FITS) or k in ('fitall', 'fitjohnson'):
            which = k[3:] if k != 'fitdistribution' else None
            if k == 'fitdistribution':
                inner = next((s for s in a.args if s.kind in ('name', 'call', 'str')), None)
                which = jsl.name_key(inner.value) if inner is not None else None
            if which in ('all', 'bestfit', 'allcontinuous'):
                o[key('fitAll')] = True
                return True
            if which == 'johnson':
                which = 'johnsonsu'
            fit = DIST_FITS.get(which)
            if fit is None:
                return False
            lst = o.setdefault(key('fits'), [])
            if fit not in lst:
                lst.append(fit)
        elif k == 'orderby':
            v = (self.str_arg(a) or '').lower()
            o[key('order')] = 'desc' if 'desc' in v else ('asc' if 'asc' in v else None)
        elif k == 'customizesummarystatistics':
            cur = list(o.get(key('stats'), ['mean', 'sd', 'se', 'upper', 'lower', 'n']))
            for s in a.args:
                if s.kind in ('call', 'name') and s.key in DIST_STATS:
                    st = DIST_STATS[s.key]
                    on = truth(s)
                    if on and st not in cur:
                        cur.append(st)
                    elif not on and st in cur:
                        cur.remove(st)
            o[key('stats')] = cur
        elif k in ('histogramcolor', 'outlierboxplotcolor', 'axissettings', 'histogramoptions', 'displayoptions', 'dispatch', 'sendtoreport'):
            return True
        else:
            return False
        return True

    # ---- Fit Y by X --------------------------------------------------------------------------------------
    def map_fitybyx(self, step, fr, roles_raw, opts, whole, node):
        kind = node.key if node.key in ('bivariate', 'oneway', 'contingency', 'logistic') else None
        self.put_roles(step, 'fitybyx', roles_raw)
        ys, xs = step['roles'].get('y', []), step['roles'].get('x', [])
        if not ys or not xs:
            raise Unconvertible(f'{node.value}: a launch without Y and X', whole)
        o = step['options']
        names = {}
        left = []
        page_kinds = {}
        for y in ys:
            for x in xs:
                if y == x:
                    continue
                yk = self.mt_of(fr, y) in ('nominal', 'ordinal')
                xk = self.mt_of(fr, x) in ('nominal', 'ordinal')
                pk = ('contingency' if xk else 'logistic') if yk else ('oneway' if xk else 'bivariate')
                page_kinds[(y, x)] = pk
                if kind and pk != kind:
                    want = {'bivariate': 'continuous by continuous', 'oneway': 'a continuous Y by a nominal or ordinal X',
                            'contingency': 'nominal or ordinal by nominal or ordinal', 'logistic': 'a nominal or ordinal Y by a continuous X'}[kind]
                    self.note(whole.line, 'warn', f'{node.value}({y} by {x}): the page chooses the analysis by the modeling types, and {y} by {x} is {pk.title()} there; {node.value} needs {want}. Change the modeling type in the page (Cols > Modeling Type) for a {node.value}.', once=('kind', whole.line, y, x))
                names[y] = y
                names[x] = x
                sc = f'{y}~{x}'
                use = kind or pk
                for a in opts:
                    if not self.fyx_option(o, sc, use, a, fr, names):
                        if a not in left:
                            left.append(a)
        step['kind'] = kind or (next(iter(page_kinds.values())) if len(set(page_kinds.values())) == 1 else 'mixed')
        o['__colNames'] = names
        self.unsupported(step, f'{kind.title() if kind else "Fit Y by X"}', node.value, left)

    def add_fit(self, o, sc, fit):
        lst = o.setdefault(f'{sc}|fits', [])
        fit = {'id': f'f{len(lst) + 1}', **fit}
        lst.append(fit)
        return fit

    def fit_suboptions(self, fit, a):
        for s in a.walk():
            if s is a or s.kind not in ('call', 'name'):
                continue
            k = s.key
            m = {'confidcurvesfit': 'cfit', 'confidcurvesindiv': 'cind', 'confidshadedfit': 'sfit', 'confidshadedindiv': 'sind',
                 'plotresiduals': 'resid', 'report': 'report', 'lineoffit': 'line'}.get(k)
            if m:
                fit[m] = truth(s)
            elif k in ALPHA_KEYS:
                v = self.num_arg(s)
                if v:
                    fit['alpha'] = v

    def fyx_option(self, o, sc, kind, a, fr, names):
        if a.kind not in ('call', 'name'):
            return False
        k = a.key
        if k in ALPHA_KEYS:
            v = self.num_arg(a)
            if v:
                o['alpha'] = v
            return True
        if k in ('xaxisproportional', 'xaxisproportion', 'dispatch', 'sendtoreport'):
            return True
        if kind == 'bivariate':
            fit = None
            if k == 'fitline':
                fit = self.add_fit(o, sc, {'kind': 'line'})
            elif k == 'fitmean':
                fit = self.add_fit(o, sc, {'kind': 'mean'})
            elif k == 'fitpolynomial':
                d = int(self.num_arg(a, 0, 2) or 2)
                fit = self.add_fit(o, sc, {'kind': 'line'} if d == 1 else {'kind': 'poly', 'degree': d})
            elif k == 'fitspline':
                lam = self.num_arg(a)
                std = any(s.kind == 'name' and s.key == 'standardized' for s in a.args)
                fit = self.add_fit(o, sc, {'kind': 'spline', 'lam': lam, 'standardize': std})
            elif k == 'kernelsmoother':
                fit = self.add_fit(o, sc, {'kind': 'lowess', 'frac': 0.667, 'it': 0})
                self.note(a.line, 'info', 'Kernel Smoother: the page draws statsmodels\' LOWESS instead of JMP\'s kernel smoother.', once='kernel')
            elif k == 'fiteachvalue':
                fit = self.add_fit(o, sc, {'kind': 'each'})
            elif k == 'fitorthogonal':
                text = ' '.join(jsl.name_key(s.value) for s in a.walk() if s.kind in ('name', 'str'))
                ratio = next((s.value for s in a.walk() if s.kind == 'num'), None)
                mode = 'equal' if 'equal' in text else ('x_to_y' if 'xtoy' in text else ('ratio' if ratio is not None else 'univariate'))
                fit = self.add_fit(o, sc, {'kind': 'orth', 'mode': mode, **({'ratio': ratio} if mode == 'ratio' else {})})
            elif k in ('fitrobust', 'robustfit'):
                fit = self.add_fit(o, sc, {'kind': 'robust', 'method': 'huber'})
            elif k == 'densityellipse':
                fit = self.add_fit(o, sc, {'kind': 'ellipse', 'p': self.num_arg(a, 0, 0.95)})
            elif k == 'nonpardensity':
                fit = self.add_fit(o, sc, {'kind': 'kde'})
            elif k == 'fitspecial':
                tr = {'log': 'log', 'naturallogarithm': 'log', 'squareroot': 'sqrt', 'sqrt': 'sqrt', 'square': 'square', 'reciprocal': 'reciprocal', 'exponential': 'exp', 'exp': 'exp'}
                f = {'kind': 'special', 'ytr': 'none', 'xtr': 'none', 'degree': 1, 'intercept': None, 'slope': None}
                for s in a.args:
                    if s.kind != 'call' or not s.args:
                        continue
                    v = jsl.name_key(self.str_arg(s) or '')
                    if s.key.startswith('x') and 'tran' in s.key:
                        f['xtr'] = tr.get(v, 'none')
                    elif s.key.startswith('y') and 'tran' in s.key:
                        f['ytr'] = tr.get(v, 'none')
                    elif s.key == 'degree':
                        f['degree'] = int(self.num_arg(s, 0, 1) or 1)
                    elif 'intercept' in s.key:
                        f['intercept'] = self.num_arg(s)
                    elif 'slope' in s.key:
                        f['slope'] = self.num_arg(s)
                fit = self.add_fit(o, sc, f)
            elif k == 'groupby':
                cols = self.role_names(fr, a.args, a)
                if cols:
                    o[f'{sc}|groupBy'] = cols[0]
                    names[cols[0]] = cols[0]
                return True
            elif k in FYX_BV_BOOL:
                o[f'{sc}|{FYX_BV_BOOL[k]}'] = truth(a)
                return True
            else:
                return False
            self.fit_suboptions(fit, a)
            return True
        if kind == 'oneway':
            if k in ('means', 'anova', 'meansanova', 'meansanovapooledt'):
                on = truth(a)
                o[f'{sc}|anova'] = on
                o[f'{sc}|diamonds'] = on
            elif k in ('meansandstddev', 'meansstddev'):
                on = truth(a)
                for x in ('meansd', 'meanLines', 'errorBars', 'sdLines'):
                    o[f'{sc}|{x}'] = on
            elif k == 'quantiles':
                on = truth(a)
                o[f'{sc}|quantiles'] = on
                o[f'{sc}|box'] = on
            elif k in FYX_OW_BOOL:
                o[f'{sc}|{FYX_OW_BOOL[k]}'] = truth(a)
            elif k in ('eachpair', 'allpairs', 'withcontrol'):
                if not truth(a):
                    return True
                method = {'eachpair': 'student', 'allpairs': 'tukey', 'withcontrol': 'dunnett'}[k]
                control = None
                if k == 'withcontrol':
                    lv = [s for s in a.walk() if s.kind in ('str', 'num') and s is not (a.args[0] if a.args else None)]
                    control = lv[0].value if lv else None
                lst = o.setdefault(f'{sc}|compare', [])
                if not any(c['method'] == method for c in lst):
                    lst.append({'method': method, 'control': control})
            elif k in ('wilcoxontest', 'mediantest', 'vanderwaerdentest', 'kolmogorovsmirnovtest', 'kolmogorovsmirnov'):
                if truth(a):
                    t = {'wilcoxontest': 'wilcoxon', 'mediantest': 'median', 'vanderwaerdentest': 'vdw'}.get(k, 'ks')
                    lst = o.setdefault(f'{sc}|np', [])
                    if t not in lst:
                        lst.append(t)
            elif k == 'nonparametricmultiplecomparisons':
                lst = o.setdefault(f'{sc}|npmc', [])
                for s in a.args:
                    if s.kind not in ('call', 'name') or not truth(s):
                        continue
                    m = {'wilcoxoneachpair': 'wilcoxon', 'steeldwassallpairs': 'steel_dwass', 'steelwithcontrol': 'steel_control',
                         'dunnwithcontrolforjointranks': 'dunn_control', 'dunnallpairsforjointranks': 'dunn_all'}.get(s.key)
                    if m:
                        ctl = next((v.value for v in s.walk() if v.kind == 'str'), None)
                        lst.append({'method': m, 'control': ctl})
            elif k == 'equivalencetest':
                d = next((s.value for s in a.walk() if s.kind == 'num'), None)
                if d is None:
                    return False
                o[f'{sc}|equiv'] = {'delta': d}
            elif k == 'analysisofmeansmethods':
                if any(s.kind in ('call', 'name') and s.key == 'anom' and truth(s) for s in a.args):
                    o[f'{sc}|anom'] = True
            elif k == 'normalquantileplot':
                qa = any(s.kind in ('call', 'name') and s.key == 'plotquantilebyactual' and truth(s) for s in a.args)
                o[f'{sc}|nqp'] = {'orient': 'qa' if qa else 'aq'}
            elif k in ('comparedensities', 'compositionofdensities', 'proportionofdensities'):
                if truth(a):
                    o[f'{sc}|densities'] = {'comparedensities': 'compare', 'compositionofdensities': 'composition', 'proportionofdensities': 'proportion'}[k]
            else:
                return False
            return True
        if kind == 'contingency':
            if k in FYX_CT_BOOL:
                o[f'{sc}|{FYX_CT_BOOL[k]}'] = truth(a)
                if k == 'contingencytable':
                    self.ct_cells(o, sc, a)
            elif k == 'crosstabs':
                self.ct_cells(o, sc, a)
            elif k == 'cochranmantelhaenszel':
                cols = self.role_names(fr, a.args, a)
                if not cols:
                    return False
                o[f'{sc}|cmh'] = cols[0]
                names[cols[0]] = cols[0]
            elif k in ('exacttest', "fisher'sexacttest", 'fishersexacttest'):
                return True
            else:
                return False
            return True
        if kind == 'logistic':
            if k in FYX_LG_BOOL:
                o[f'{sc}|{FYX_LG_BOOL[k]}'] = truth(a)
            elif k == 'inverseprediction':
                ps = [s.value for s in a.walk() if s.kind == 'num' and 0 < s.value < 1]
                if not ps:
                    return False
                o[f'{sc}|inverse'] = ps
            elif k in ('targetlevel', 'positivelevel'):
                v = next((s.value for s in a.args if s.kind in ('str', 'num')), None)
                if v is None:
                    return False
                o[f'{sc}|target'] = v
            else:
                return False
            return True
        return False

    def ct_cells(self, o, sc, a):
        cells = list(o.get(f'{sc}|cells', ['count', 'total', 'col', 'row']))
        touched = False
        for s in a.args:
            if s.kind in ('call', 'name') and s.key in CT_CELLS:
                touched = True
                c = CT_CELLS[s.key]
                if truth(s) and c not in cells:
                    cells.append(c)
                elif not truth(s) and c in cells:
                    cells.remove(c)
        if touched:
            order = ['count', 'total', 'col', 'row', 'expected', 'deviation', 'cellchi']
            o[f'{sc}|cells'] = [c for c in order if c in cells]

    # ---- Matched Pairs -----------------------------------------------------------------------------------
    def map_matchedpairs(self, step, fr, roles_raw, opts, whole, node):
        self.put_roles(step, 'matchedpairs', roles_raw)
        ys = step['roles'].get('y', [])
        o = step['options']
        left = []
        bools = {'plotdifbymean': 'plotMean', 'plotdifbyrow': 'plotRow', 'wilcoxonsignedrank': 'wilcoxon', 'signtest': 'sign'}
        for i in range(len(ys)):
            for j in range(i + 1, len(ys)):
                sc = f'{ys[i]}~{ys[j]}'
                for a in opts:
                    if a.kind in ('call', 'name') and a.key in bools:
                        o[f'{sc}|{bools[a.key]}'] = truth(a)
                    elif a.kind in ('call', 'name') and a.key in ALPHA_KEYS:
                        o['alpha'] = self.num_arg(a, 0, 0.05)
                    elif a.kind in ('call', 'name') and a.key in ('referenceframe', 'dispatch', 'sendtoreport'):
                        pass
                    elif a not in left:
                        left.append(a)
        self.unsupported(step, 'Matched Pairs', node.value, left)

    # ---- Fit Model -----------------------------------------------------------------------------------------
    def map_fitmodel(self, step, fr, roles_raw, opts, whole, node):
        o = step['options']
        effects = []
        left = []
        run = []
        for a in opts:
            k = a.key if a.kind in ('call', 'name') else None
            if k == 'effects':
                for t in a.args:
                    if t.kind != 'empty':
                        effects.append(self.effect_term(fr, t, whole))
            elif k == 'randomeffects':
                for t in a.args:
                    if t.kind != 'empty':
                        e = self.effect_term(fr, t, whole)
                        e['random'] = True
                        effects.append(e)
            elif k == 'personality':
                v = jsl.name_key(self.str_arg(a) or '')
                if v not in FM_PERSONALITY:
                    raise Unconvertible(f'Fit Model: the page\'s Fit Model has no personality "{self.str_arg(a)}"', whole)
                o['personality'] = FM_PERSONALITY[v]
            elif k in ('glmdistribution', 'distribution'):
                v = jsl.name_key(self.str_arg(a) or '')
                if v == 'exponential':
                    o['dist'] = 'gamma'
                    self.note(whole.line, 'warn', 'Fit Model: the Exponential distribution is fitted as a Gamma here (the exponential is a gamma with shape 1; the estimates of the mean agree, the dispersion is estimated).', once=('expo', whole.line))
                elif v in FM_DIST:
                    o['dist'] = FM_DIST[v]
                else:
                    left.append(a)
            elif k == 'linkfunction':
                v = jsl.name_key(self.str_arg(a) or '')
                if v in FM_LINK:
                    o['link'] = FM_LINK[v]
                else:
                    left.append(a)
            elif k == 'emphasis':
                v = jsl.name_key(self.str_arg(a) or '')
                o['emphasis'] = {'effectleverage': 'leverage', 'effectscreening': 'screening', 'minimalreport': 'minimal'}.get(v, 'leverage')
            elif k == 'nointercept':
                o['noIntercept'] = truth(a)
            elif k == 'nobounds':
                # JMP's Unbounded Variance Components (mixed.py): NoBounds(1) lets a variance component go below zero
                o['mxUnbounded'] = truth(a)
            elif k == 'targetlevel':
                v = next((s.value for s in a.args if s.kind in ('str', 'num')), None)
                if v is not None:
                    o['target'] = v
            elif k == 'centerpolynomials':
                if not truth(a):
                    self.note(whole.line, 'info', 'Fit Model: Center Polynomials(0) is not carried over; the page centres continuous columns in crossings, as JMP does by default.', once=('center', whole.line))
            elif k == 'method':
                v = jsl.name_key(self.str_arg(a) or '')
                if v not in ('reml', ''):
                    self.note(whole.line, 'info', f'Fit Model: Method("{self.str_arg(a)}") is not carried over; the page fits random effects by REML.', once=('method', whole.line))
            elif k in ('run', 'runmodel'):
                run.append(a)
            elif k in ('overdispersiontestsandintervals',):
                o['overdispersion'] = truth(a)
            elif k in ('keepdialogopen', 'firthbiasadjustedestimates'):
                if k == 'firthbiasadjustedestimates' and truth(a):
                    left.append(a)
            else:
                left.append(a)
        self.put_roles(step, 'fitmodel', roles_raw)
        ys = step['roles'].get('y', [])
        if not ys:
            raise Unconvertible('Fit Model without a Y', whole)
        if 'personality' not in o:
            mt = self.mt_of(fr, ys[0])
            o['personality'] = 'nominal' if mt == 'nominal' else ('ordinal' if mt == 'ordinal' else 'standard')
        step['extra'] = {'effects': effects}
        # random effects: Standard Least Squares (REML), Mixed Model, and a binomial or Poisson GLM (a generalized linear mixed model)
        if any(e['random'] for e in effects) and o['personality'] not in ('standard', 'mixed') and not (o['personality'] == 'glm' and o.get('dist') in ('binomial', 'poisson')):
            self.note(whole.line, 'warn', f'Fit Model: the page\'s {o["personality"]} personality takes fixed effects only; the random effects (&Random) are kept in the effects, and the page will ask for them to be taken off.', once=('fmrandom', whole.line))
        for r in run:
            for s in r.args:
                s = self.unwrap(s)
                if s.kind == 'send':
                    ref = self.colref(s.args[0], Ctx('vec', fr), quiet=True)
                    scope = ref.name if ref is not None else None
                    msgs = s.args[1].args if s.args[1].kind == 'list' else [s.args[1]]
                    for mm in msgs:
                        self.fm_run(o, scope, mm, left)
                elif s.kind in ('call', 'name'):
                    self.fm_run(o, None, s, left)
        self.unsupported(step, 'Fit Model', 'Fit Model', left)

    def fm_run(self, o, scope, m, left):
        if m.kind not in ('call', 'name'):
            return
        page = FM_RUN.get(m.key)
        if page is None:
            if m.key not in ('dispatch', 'sendtoreport', 'scaledestimates', 'plotresidualbypredictedplot'):
                left.append(m)
            elif m.key == 'scaledestimates' and truth(m):
                left.append(m)
            return
        o[f'{scope}|{page}' if scope else page] = truth(m)

    def effect_term(self, fr, t, whole):
        """One term of Effects(): {cols, names, nest, nestNames, random}."""
        random_ = False
        if t.kind == 'binop' and t.value in ('&', ':&'):
            attr = t.args[1]
            if attr.kind == 'name' and attr.key == 'random':
                random_ = True
            elif attr.kind == 'name' and attr.key in ('rs', 'mixture', 'excluded', 'knotted', 'logvariance'):
                self.note(whole.line, 'info', f'Fit Model: the effect attribute &{attr.value} is not carried over.', once=('attr', attr.key))
            else:
                raise Unconvertible(f'Fit Model: the effect {self.p.source(t)}', whole)
            t = t.args[0]
        cols, nest = [], []

        def crossing(n):
            if n.kind == 'binop' and n.value == '*':
                crossing(n.args[0])
                crossing(n.args[1])
            elif n.kind == 'subscript':
                crossing(n.args[0])
                for s in n.args[1:]:
                    nest.extend(self.role_names(fr, [s], whole))
            else:
                cols.extend(self.role_names(fr, [n], whole))
        crossing(t)
        return {'cols': list(cols), 'names': list(cols), 'nest': list(nest), 'nestNames': list(nest), 'random': random_}

    # ---- Multivariate, Principal Components ------------------------------------------------------------------
    def map_multivariate(self, step, fr, roles_raw, opts, whole, node):
        self.put_roles(step, 'multivariate', roles_raw)
        o = step['options']
        left = []
        for a in opts:
            if a.kind not in ('call', 'name'):
                if a.kind == 'str':
                    left.append(a)
                continue
            k = a.key
            if k == 'estimationmethod':
                v = jsl.name_key(self.str_arg(a) or '')
                if v in ('rowwise', 'pairwise'):
                    o['method'] = v
                elif v not in ('default', ''):
                    self.note(whole.line, 'info', f'Multivariate: Estimation Method("{self.str_arg(a)}") is not in the page (Row-wise and Pairwise are); it takes Row-wise.', once=('mvest', whole.line))
            elif k == 'scatterplotmatrix':
                o['splom'] = truth(a) if not a.args or a.args[0].kind == 'num' else True
                for s in a.args:
                    if s.kind in ('call', 'name') and s.key in SPLOM:
                        o[SPLOM[s.key]] = truth(s)
                    elif s.kind == 'call' and s.key == 'ellipsecoverage':
                        o['spLevel'] = self.num_arg(s, 0, 0.95)
            elif k in ('simplestatistics', 'itemreliability', 'colormaps', 'outlieranalysis'):
                for s in a.args:
                    if s.kind in ('call', 'name') and s.key in MV_BOOL:
                        o[MV_BOOL[s.key]] = truth(s)
            elif k == 'nonparametriccorrelations':
                for s in a.args:
                    if s.kind in ('call', 'name'):
                        for p in ('spearman', 'kendall', 'hoeffding'):
                            if s.key.startswith(p):
                                o[f'np:{p}'] = truth(s)
            elif any(k.startswith(p) for p in ('spearman', 'kendall', 'hoeffding')) and k != "kendall'sw":
                p = next(p for p in ('spearman', 'kendall', 'hoeffding') if k.startswith(p))
                o[f'np:{p}'] = truth(a)
            elif k in MV_BOOL:
                o[MV_BOOL[k]] = truth(a)
            elif k == 'matrixformat':
                v = jsl.name_key(self.str_arg(a) or '')
                o['matrixFormat'] = 'lower' if 'lower' in v else ('upper' if 'upper' in v else 'square')
            elif k in ALPHA_KEYS:
                o['alpha'] = self.num_arg(a, 0, 0.05)
            else:
                left.append(a)
        self.unsupported(step, 'Multivariate', 'Multivariate', left)

    def map_pca(self, step, fr, roles_raw, opts, whole, node):
        self.put_roles(step, 'pca', roles_raw)
        o = step['options']
        left = []
        for a in opts:
            if a.kind == 'str' or a.kind == 'name' and a.key.startswith('on'):
                v = jsl.name_key(a.value)
                if 'covariance' in v:
                    o['on'] = 'covariances'
                elif 'unscaled' in v:
                    o['on'] = 'unscaled'
                elif 'correlation' in v:
                    o['on'] = 'correlations'
                else:
                    left.append(a)
                continue
            if a.kind not in ('call', 'name'):
                continue
            k = a.key
            if k in PCA_BOOL:
                o[PCA_BOOL[k]] = truth(a)
            elif k == 'estimationmethod':
                v = jsl.name_key(self.str_arg(a) or '')
                if v not in ('default', 'rowwise', ''):
                    self.note(whole.line, 'info', f'Principal Components: Estimation Method("{self.str_arg(a)}") is not in the page; it uses the rows with every column.', once=('pcaest', whole.line))
            elif k in ('saveprincipalcomponents', 'saverotatedcomponents'):
                self.note(whole.line, 'info', 'Principal Components: saved components are not carried over (the page\'s Save Columns makes them).', once=('pcasave', whole.line))
            else:
                left.append(a)
        self.unsupported(step, 'Principal Components', 'Principal Components', left)

    # ---- the other platforms: roles, and the options each takes ---------------------------------------------------
    def map_generic(self, step, fr, roles_raw, opts, whole, node):
        pid = step['platform']
        extra = {}
        if pid == 'timeseries':
            extra = {'x': 'time'}
        if pid in ('controlchart',):
            extra = {'x': 'subgroup'}
        self.put_roles(step, pid, roles_raw, extra)
        o = step['options']
        left = []
        for a in opts:
            if not self.generic_option(pid, o, a, fr, step, whole):
                left.append(a)
        self.unsupported(step, node.value, node.value, left)

    def generic_option(self, pid, o, a, fr, step, whole):
        if a.kind not in ('call', 'name'):
            return False
        k = a.key
        if k in ALPHA_KEYS:
            o['alpha'] = self.num_arg(a, 0, 0.05)
            return True
        if pid in ('partition', 'forest', 'boosted', 'neural', 'knn', 'naivebayes', 'svm', 'screening'):
            if k == 'validationportion':
                o['portion'] = self.num_arg(a, 0, 0)
                return True
            if k == 'informativemissing':
                o['missing'] = truth(a)
                return True
            if k in ('randomseed', 'setrandomseed'):
                v = self.num_arg(a)
                if v is not None:
                    o['seed'] = str(int(v))
                return True
            if pid == 'partition' and k == 'minimumsizesplit':
                o['minsize'] = self.num_arg(a, 0, 5)
                return True
            if pid == 'partition' and k in ('splitbest', 'split'):
                n = int(self.num_arg(a, 0, 1) or 1)
                o.setdefault('steps', []).append({'op': 'split', 'n': n})
                return True
            if pid == 'partition' and k == 'method':
                v = jsl.name_key(self.str_arg(a) or '')
                if v in ('decisiontree', ''):
                    return True
                return False
            if pid == 'knn' and k in ('k', 'numberofneighbors'):
                o['k'] = int(self.num_arg(a, 0, 10) or 10)
                return True
        if pid == 'hcluster':
            if k == 'method':
                v = jsl.name_key(self.str_arg(a) or '')
                if v in ('average', 'centroid', 'ward', 'single', 'complete'):
                    o['method'] = v
                    return True
                return False
            if k in ('standardizedata', 'standardizeby'):
                if k == 'standardizedata':
                    o['standardize'] = 'columns' if truth(a) else 'none'
                else:
                    v = jsl.name_key(self.str_arg(a) or '')
                    o['standardize'] = {'columns': 'columns', 'rows': 'rows'}.get(v, 'none')
                return True
            if k == 'numberofclusters':
                o['ncluster'] = int(self.num_arg(a, 0, 1) or 1)
                return True
            if k == 'twowayclustering':
                o['twoWay'] = truth(a)
                return True
        if pid == 'kmeans':
            if k == 'numberofclusters':
                o['k'] = int(self.num_arg(a, 0, 3) or 3)
                return True
            if k == 'columnsscaledindividually':
                o['scaled'] = truth(a)
                return True
            if k in ('go',):
                return True
        if pid == 'discriminant':
            if k == 'discriminantmethod':
                v = jsl.name_key(self.str_arg(a) or '')
                m = next((x for x in ('linear', 'quadratic', 'regularized') if v.startswith(x)), None)
                if m:
                    o['method'] = m
                    return True
                return False
            if k == 'stepwisevariableselection':
                o['stepwise'] = truth(a)
                return True
        if pid == 'timeseries':
            if k in ('forecastperiods', 'numberofforecastperiods'):
                o['forecast'] = int(self.num_arg(a, 0, 25) or 25)
                return True
            if k in ('autocorrelationlags', 'numberofautocorrelationlags'):
                o['nlags'] = int(self.num_arg(a, 0, 25) or 25)
                return True
            if k in ('forecastperiodicity', 'seasonalperiod'):
                o['period'] = int(self.num_arg(a, 0, 0) or 0) or None
                return True
        if pid == 'survival':
            if k == 'censorcode':
                v = next((s.value for s in a.args if s.kind in ('num', 'str')), 1)
                o['censorCode'] = str(int(v) if isinstance(v, float) and v.is_integer() else v)
                return True
            if k in ('plotfailure', 'failureplot'):
                o['failure'] = truth(a)
                return True
        if pid in ('lifedist', 'parametric', 'phreg') and k == 'censorcode':
            v = next((s.value for s in a.args if s.kind in ('num', 'str')), 1)
            o['censorCode'] = str(int(v) if isinstance(v, float) and v.is_integer() else v)
            return True
        if pid == 'variability' and k == 'model':
            v = jsl.name_key(self.str_arg(a) or '')
            if v in ('crossed', 'nested', 'main effect', 'maineffect', 'crossedthennested', 'nestedthencrossed'):
                o['model'] = 'nested' if v == 'nested' else 'crossed'
                return True
            return False
        if pid == 'scattermatrix' and k == 'matrixformat':
            v = jsl.name_key(self.str_arg(a) or '')
            o['format'] = 'lower' if 'lower' in v else ('upper' if 'upper' in v else 'square')
            return True
        if pid == 'graphbuilder':
            return self.graph_builder(o, a, fr, step, whole)
        if pid == 'controlchart':
            return self.control_chart(o, a, fr, step, whole)
        if pid == 'chart':
            return self.chart_option(o, a, fr, step)
        return False

    def graph_builder(self, o, a, fr, step, whole):
        gb = o.setdefault('gb', {'v': 1, 'zones': {}, 'elements': [], 'auto': True})
        k = a.key
        if k == 'variables':
            for z in a.args:
                if z.kind != 'call' or z.key not in GB_ZONES:
                    self.note(whole.line, 'info', f'Graph Builder: {excerpt(self.p.source(z), 30)} is not carried over.', once=('gbz', z.line))
                    continue
                names = self.role_names(fr, [x for x in z.args if not x.kind == 'call'], whole)
                gb['zones'].setdefault(GB_ZONES[z.key], []).extend({'id': n, 'name': n} for n in names)
            return True
        if k == 'elements':
            for el_ in a.args:
                if el_.kind not in ('call', 'name') or el_.key not in GB_ELEMENTS:
                    self.note(whole.line, 'info', f'Graph Builder: the element {excerpt(self.p.source(el_), 30)} is not in the page.', once=('gbe', el_.line))
                    continue
                e = {'type': GB_ELEMENTS[el_.key]}
                for s in el_.args if el_.kind == 'call' else []:
                    if s.kind == 'call' and s.key == 'summarystatistic':
                        v = jsl.name_key(self.str_arg(s) or '')
                        if v in GB_STATS:
                            e['summary'] = GB_STATS[v]
                gb['elements'].append(e)
                gb['auto'] = False
            return True
        if k in ('showcontrolpanel', 'size', 'legendposition', 'fitto window', 'fittowindow', 'includemissingcategories'):
            return True
        return False

    def control_chart(self, o, a, fr, step, whole):
        k = a.key
        charts = {'xbar': 'xbar_r', 'r': 'xbar_r', 's': 'xbar_s', 'individualmeasurement': 'ir', 'movingrange': 'ir', 'p': 'p', 'np': 'np',
                  'c': 'c', 'u': 'u', 'ewma': 'ewma', 'cusum': 'cusum', 'leveyjennings': 'lj', 'runchart': 'run'}
        if k == 'variables':
            for z in a.args:
                if z.kind == 'call' and z.key in ('y', 'subgroup', 'phase', 'ntrials'):
                    names = self.role_names(fr, z.args, whole)
                    step['roles'].setdefault(z.key, []).extend(names)
            return True
        if k == 'chartcol' and a.args:
            names = self.role_names(fr, [a.args[0]], whole)
            step['roles'].setdefault('y', []).extend(names)
            kinds = [charts.get(s.key) for s in a.args[1:] if s.kind in ('name', 'call')]
            kinds = [c for c in kinds if c]
            if kinds:
                o['chart'] = 'xbar_s' if 'xbar_s' in kinds else kinds[0]
            return True
        if k == 'samplesize' and a.args:
            if a.args[0].kind == 'num':
                o['subgroupSize'] = int(a.args[0].value)
            else:
                step['roles'].setdefault('subgroup', []).extend(self.role_names(fr, a.args, whole))
            return True
        if k in ('chart', 'charttype', 'ksigma', 'showlimitsummaries', 'showcontrolpanel', 'size'):
            return True
        return False

    def chart_option(self, o, a, fr, step):
        k = a.key
        if k in ('barchart', 'linechart', 'piechart', 'needlechart', 'pointchart'):
            if truth(a):
                o['kind'] = {'barchart': 'bar', 'linechart': 'line', 'piechart': 'pie', 'needlechart': 'needle', 'pointchart': 'point'}[k]
            return True
        if k in ('horizontal', 'overlay'):
            o[k] = truth(a)
            return True
        return False

    # ---- messages to a launched analysis -------------------------------------------------------------------------
    def platform_message(self, step, m, node, want):
        k = m.key
        if k in ('report', 'topreport', 'getscript', 'getscriptwithdatatable', 'savepicture', 'journal', 'journalwindow',
                 'saveinteractivehtml', 'savescripttoscriptwindow', 'copyscript', 'getwebsupport', 'viewwebxml', 'saveas', 'print window', 'printwindow'):
            raise Unconvertible(f'{m.value}: the report of a launch has no Python counterpart here', node)
        if k == 'getdatatable':
            fr = next((f for f in self.frames if f.var == step['frame']), None)
            return E(step['frame'], P_ATOM, 'frame', fr)
        if k in TABLE_DISPLAY or k in LAUNCH_DISPLAY or k in ('closewindow', 'redoanalysis', 'relaunchanalysis', 'automaticrecalc', 'localdatafilter'):
            self.note(node.line, 'info', f'{m.value}: dropped (it acts on JMP\'s window).', once=('pdisp', k))
            return None
        pid = step['platform']
        fr = next((f for f in self.frames if f.var == step['frame']), None) or self.cur
        o = step['options']
        done = False
        if pid == 'distribution':
            ys = step['roles'].get('y', [])
            done = self.dist_option(o, ys[0] if len(ys) == 1 else None, m, fr, step)
        elif pid == 'fitybyx':
            names = o.setdefault('__colNames', {})
            done = True
            for y in step['roles'].get('y', []):
                for x in step['roles'].get('x', []):
                    if y != x:
                        use = step.get('kind') if step.get('kind') in ('bivariate', 'oneway', 'contingency', 'logistic') else None
                        use = use or ('bivariate' if self.mt_of(fr, y) == 'continuous' and self.mt_of(fr, x) == 'continuous' else 'oneway')
                        done = self.fyx_option(o, f'{y}~{x}', use, m, fr, names) and done
        elif pid == 'multivariate':
            before = dict(o)
            self.map_multivariate({'roles': {}, 'options': o, 'line': step['line']}, fr, {}, [m], node, m)
            done = o != before
        elif pid == 'pca':
            before = dict(o)
            self.map_pca({'roles': {}, 'options': o, 'line': step['line']}, fr, {}, [m], node, m)
            done = o != before
        elif pid == 'fitmodel':
            left = []
            self.fm_run(o, None, m, left)
            done = not left
        else:
            done = self.generic_option(pid, o, m, fr, step, node)
        if done:
            self.note(node.line, 'info', f'{m.value}: added to the analysis of line {step["line"]} ({step["id"]}).', once=('padd', node.line, k))
        else:
            self.note(node.line, 'info', f'{m.value}: not an option of the page\'s analysis of line {step["line"]}; left out.', once=('pnot', node.line, k))
        return E(step['frame'], P_ATOM, 'platform', step) if want else None

    # ---- Tabulate: straight to pandas -------------------------------------------------------------------------------
    # Tabulate's statistics that pandas' aggregations match
    TAB_STATS = {'n': 'count', 'mean': 'mean', 'stddev': 'std', 'min': 'min', 'max': 'max', 'sum': 'sum', 'median': 'median', 'variance': 'var'}

    def tabulate(self, fr, args, whole, target):
        tables = [a for a in args if a.kind == 'call' and a.key == 'addtable']
        if len(tables) != 1:
            raise Unconvertible('Tabulate(): one Add Table() is converted', whole)
        rows, cols, analysis, stats_ = [], [], [], []

        def collect(n, where):
            for s in n.args:
                if s.kind != 'call':
                    continue
                if s.key == 'groupingcolumns':
                    (rows if where == 'row' else cols).extend(self.role_names(fr, s.args, whole))
                elif s.key == 'analysiscolumns':
                    analysis.extend(self.role_names(fr, s.args, whole))
                elif s.key == 'statistics':
                    for st in s.args:
                        if st.kind in ('name', 'call'):
                            stats_.append(st.key)
                elif s.key in ('rowtable', 'columntable'):
                    collect(s, 'row' if s.key == 'rowtable' else 'col')
        collect(tables[0], None)
        if not rows and not cols:
            raise Unconvertible('Tabulate() without grouping columns', whole)
        funcs = []
        for s in stats_ or (['mean'] if analysis else ['n']):
            f = self.TAB_STATS.get(s)
            if f is None:
                raise Unconvertible(f'Tabulate(): the statistic {s}', whole)
            funcs.append(f)
        var = self.py(target.key, target.value) if target is not None else self.fresh('tabulate')
        idx = '[' + ', '.join(lit(c) for c in rows) + ']' if rows else None
        col = '[' + ', '.join(lit(c) for c in cols) + ']' if cols else None
        f = lit(funcs[0]) if len(funcs) == 1 else '[' + ', '.join(lit(x) for x in funcs) + ']'
        if analysis:
            values = lit(analysis[0]) if len(analysis) == 1 else '[' + ', '.join(lit(a) for a in analysis) + ']'
            cols_part = f'columns={col}, ' if idx and col else ''
            code = f'{fr.var}.pivot_table(index={idx or col}, {cols_part}values={values}, aggfunc={f})'
        elif rows and cols:
            code = f'pd.crosstab([{", ".join(f"{fr.var}[{lit(c)}]" for c in rows)}], [{", ".join(f"{fr.var}[{lit(c)}]" for c in cols)}])'
        else:
            keys = rows or cols
            code = f'{fr.var}.groupby({lit(keys[0]) if len(keys) == 1 else "[" + ", ".join(lit(k) for k in keys) + "]"}, dropna=False).size()'
        self.emit(f'{var} = {code}')
        self.emit(f'print({var})')
        self.note(whole.line, 'info', 'Tabulate: the table is made with pandas (pivot_table or crosstab) and printed; its layout is pandas\', not JMP\'s.', once=('tab', whole.line))


# ---- the helpers a converted script may need, written into it when it does -----------------------

HELPERS = {
    'jsl_char': '''def jsl_char(x, width=None, decimals=None):
    """JSL's Char(): a number as text with at most 15 significant digits and no
    ".0" on a whole number, a missing value as "."; with a width (and decimals),
    as many decimals as fit in it."""
    if isinstance(x, str):
        return x
    if x is None:
        return "."
    if isinstance(x, (list, tuple)):
        return "{" + ", ".join(jsl_char(v) if not isinstance(v, str) else '"' + v + '"' for v in x) + "}"
    if isinstance(x, dict):
        def q(v):
            return '"' + v + '"' if isinstance(v, str) else jsl_char(v)
        try:
            keys = sorted(x, key=lambda k: (isinstance(k, str), k))
        except TypeError:
            keys = list(x)
        return "[" + ", ".join(q(k) + " => " + q(x[k]) for k in keys) + "]" if keys else "[=>]"
    if isinstance(x, np.ndarray):
        return "[" + ", ".join(" ".join(jsl_char(v) for v in row) for row in np.atleast_2d(x)) + "]"
    if isinstance(x, (bool, np.bool_)):
        return "1" if x else "0"
    try:
        x = float(x)
    except (TypeError, ValueError):
        return str(x)
    if np.isnan(x):
        return "."
    if width is None:
        text = f"{x:.15g}"
        return text[:-2] if text.endswith(".0") else text
    for d in range(int(decimals) if decimals is not None else 15, -1, -1):
        text = f"{x:.{d}f}".rstrip("0").rstrip(".") if d else f"{x:.0f}"
        if len(text) <= width:
            return text
    return f"{x:.{max(0, int(width) - 6)}e}"''',
    'jsl_round': '''def jsl_round(x, places=0):
    """JSL's Round(): halves away from zero (Python's round() goes to the even one)."""
    f = 10.0 ** places
    return np.sign(x) * np.floor(np.abs(x) * f + 0.5) / f''',
    'jsl_words': '''def jsl_words(text, delimiters=" "):
    """JSL's Words(): the words between runs of any of the delimiter characters."""
    if delimiters == "":
        return list(text)
    return [w for w in re.split("[" + re.escape(delimiters) + "]+", text) if w]''',
    'jsl_word': '''def jsl_word(n, text, delimiters=" "):
    """JSL's Word(): the nth word (1 is the first, -1 the last), "" when there is none."""
    words = jsl_words(text, delimiters)
    n = int(n)
    if n > 0 and n <= len(words):
        return words[n - 1]
    if n < 0 and -n <= len(words):
        return words[n]
    return ""''',
    'jsl_items': '''def jsl_items(text, delimiters=" "):
    """JSL's Items(): the items between delimiter characters, each delimiter
    ending one (so two together make an empty item); none at the ends."""
    if delimiters == "":
        return list(text)
    inner = text.strip(delimiters)
    return re.split("[" + re.escape(delimiters) + "]", inner) if inner else []''',
    'jsl_item': '''def jsl_item(n, text, delimiters=" "):
    """JSL's Item(): the nth of the items (see jsl_items), "" when there is none."""
    items = jsl_items(text, delimiters)
    n = int(n)
    if n > 0 and n <= len(items):
        return items[n - 1]
    if n < 0 and -n <= len(items):
        return items[n]
    return ""''',
    'jsl_contains': '''def jsl_contains(whole, part, start=1):
    """JSL's Contains(): the position (from 1) of part in a string or a list,
    0 when it is not there; for a dict, 1 when part is one of its keys. A
    negative start searches backwards from that far from the end."""
    if isinstance(whole, dict):
        return int(part in whole)
    if isinstance(whole, str):
        if start < 0:
            return whole.rfind(part, 0, len(whole) + int(start) + len(part)) + 1
        return whole.find(part, int(start) - 1) + 1
    items = list(whole)
    for i in range(int(start) - 1, len(items)):
        if items[i] == part:
            return i + 1
    return 0''',
    'jsl_regex': '''def jsl_regex(text, pattern, format=r"\\0", ignore_case=False, global_replace=False):
    """JSL's Regex(): the first match, with the whole match and its groups (JSL's
    backreferences) filled into format, or missing (nan) when there is none; with
    global_replace every match is replaced by format."""
    flags = re.IGNORECASE if ignore_case else 0
    repl = re.sub(r"\\\\(\\d)", r"\\\\g<\\1>", format)
    if global_replace:
        return re.sub(pattern, repl, text, flags=flags)
    m = re.search(pattern, text, flags)
    return np.nan if m is None else m.expand(repl)''',
    'jsl_regex_match': '''def jsl_regex_match(text, pattern, match_case=False):
    """JSL's Regex Match(): the whole match and its groups, as a list; [] when
    there is no match. JSL matches without regard to case unless asked."""
    m = re.search(pattern, text, 0 if match_case else re.IGNORECASE)
    if m is None:
        return []
    return [m.group(0)] + ["" if g is None else g for g in m.groups()]''',
    'jsl_munger': '''def jsl_munger(text, start, find, replacement=None):
    """JSL's Munger(): with a string to find, its position from start (0 if
    absent) or, with a replacement, text with its first occurrence from start
    replaced; with a number of characters, those characters from start, or
    replaced."""
    i = max(0, min(int(start), len(text) + 1) - 1)
    if isinstance(find, str):
        at = text.find(find, i)
        if replacement is None:
            return at + 1
        return text if at < 0 else text[:at] + replacement + text[at + len(find):]
    n = int(find)
    if replacement is None:
        return text[i:i + n]
    return text[:i] + replacement + text[i + n:]''',
    'jsl_sequence': '''def jsl_sequence(n_rows, start, stop, step=1, repeat=1):
    """JSL's Sequence() in a column formula: start, start + step, ... up to stop,
    each repeat times, over and over down the n_rows rows."""
    one = np.repeat(np.arange(start, stop + step / 2, step), int(repeat))
    return np.resize(one, n_rows)''',
    'jsl_count': '''def jsl_count(n_rows, start, stop, steps, times):
    """JSL's Count() in a column formula: `steps` values from start to stop,
    both included, each `times` times, over and over down the rows."""
    one = np.repeat(np.linspace(start, stop, int(steps)), int(times))
    return np.resize(one, n_rows)''',
    'jsl_eigen': '''def jsl_eigen(a):
    """JSL's Eigen() of a symmetric matrix: [eigenvalues (largest first, as a
    column), eigenvectors (as columns)]."""
    values, vectors = np.linalg.eigh(a)
    order = np.argsort(values)[::-1]
    return [values[order].reshape(-1, 1), vectors[:, order]]''',
    'jsl_svd': '''def jsl_svd(a):
    """JSL's SVD(): [U, the singular values (a column), V], with a = U diag(M) V'."""
    u, s, vt = np.linalg.svd(a, full_matrices=False)
    return [u, s.reshape(-1, 1), vt.T]''',
    'jsl_date_difference': '''def jsl_date_difference(d1, d2, interval, alignment="Start"):
    """JSL's Date Difference(): from d1 to d2 in intervals ("year" ... "second").
    "Start" counts the interval boundaries crossed, "Actual" the whole intervals,
    "Fractional" the fraction of an average interval."""
    d1, d2 = pd.Timestamp(d1), pd.Timestamp(d2)
    unit = interval.lower().rstrip("s")
    how = alignment.lower()
    seconds = {"week": 604800, "day": 86400, "hour": 3600, "minute": 60, "second": 1}
    months = {"year": 12, "quarter": 3, "month": 1}
    if unit in seconds:
        size = seconds[unit]
        if how == "fractional":
            return (d2 - d1).total_seconds() / size
        if how == "actual":
            return float(int((d2 - d1).total_seconds() / size))
        floor = {"week": lambda d: (d - pd.Timedelta(days=(d.dayofweek + 1) % 7)).normalize(), "day": lambda d: d.normalize(),
                 "hour": lambda d: d.floor("h"), "minute": lambda d: d.floor("min"), "second": lambda d: d.floor("s")}[unit]
        return float(round((floor(d2) - floor(d1)).total_seconds() / size))
    k = months[unit]
    if how == "fractional":
        return (d2 - d1).total_seconds() / (365.2425 * 86400 * k / 12)
    m1, m2 = d1.year * 12 + d1.month - 1, d2.year * 12 + d2.month - 1
    if how == "start":
        return float(m2 // k - m1 // k)
    whole = (m2 - m1) // k
    if d1 + pd.DateOffset(months=whole * k) > d2:
        whole -= 1
    return float(whole)''',
    'jsl_date_increment': '''def jsl_date_increment(d, interval, n=1, alignment="Start"):
    """JSL's Date Increment(): d plus n intervals; with "Start" (the default)
    d is first moved back to the start of its interval."""
    d = pd.Timestamp(d)
    unit = interval.lower().rstrip("s")
    if alignment.lower() == "start":
        d = {"year": lambda t: t.replace(month=1, day=1).normalize(),
             "quarter": lambda t: t.replace(month=3 * ((t.month - 1) // 3) + 1, day=1).normalize(),
             "month": lambda t: t.replace(day=1).normalize(),
             "week": lambda t: (t - pd.Timedelta(days=(t.dayofweek + 1) % 7)).normalize(),
             "day": lambda t: t.normalize(), "hour": lambda t: t.floor("h"), "minute": lambda t: t.floor("min"),
             "second": lambda t: t.floor("s")}[unit](d)
    step = {"year": pd.DateOffset(years=n), "quarter": pd.DateOffset(months=3 * n), "month": pd.DateOffset(months=n),
            "week": pd.Timedelta(weeks=n), "day": pd.Timedelta(days=n), "hour": pd.Timedelta(hours=n),
            "minute": pd.Timedelta(minutes=n), "second": pd.Timedelta(seconds=n)}[unit]
    return d + step''',
}
HELPER_DEPS = {'jsl_word': ('jsl_words',), 'jsl_item': ('jsl_items',)}

IMPORTS = [
    (r'\bnp\.', 'import numpy as np'), (r'\bpd\.', 'import pandas as pd'), (r'\bstats\.', 'from scipy import stats'),
    (r'\bspecial\.', 'from scipy import special'), (r'\bmath\.', 'import math'), (r'\bre\.', 'import re'), (r'\bos\.', 'import os'),
    (r'\bsys\.', 'import sys'), (r'\btime\.', 'import time'), (r'\bcalendar\.', 'import calendar'), (r'\bcollections\.', 'import collections'),
    (r'\bplt\.', 'import matplotlib.pyplot as plt'),
]


class Translator(_Platforms):
    def assemble(self):
        body = [('    ' * ind) + text if text else '' for ind, text in self.body]
        helpers = [HELPERS[h] for h in self.helpers]
        pre = list(self.preload)
        text_all = '\n'.join(helpers + pre + body)
        imports = []
        for pat, line in IMPORTS:
            if re.search(pat, text_all) and line not in imports:
                imports.append(line)
        # the helpers use numpy and re themselves
        if helpers and 'import numpy as np' not in imports:
            imports.insert(0, 'import numpy as np')
        out = ['# Python translation of a JSL script (smui.html); the notes list what did not convert.']
        if imports:
            out.append('')
            out.extend(imports)
        if helpers:
            out.append('')
            out.append('')
            out.append('\n\n\n'.join(helpers))
            out.append('')
        if pre:
            out.append('')
            out.extend(pre)
        if body:
            out.append('')
            out.extend(body)
        text = '\n'.join(out).rstrip() + '\n'
        return text


def convert_text(text, tables=None, current=None):
    """The work of jsl.convert, without the JSON round trip."""
    prog = jsl.parse(text or '')
    t = Translator(prog, tables, current)
    notes = [{'line': q.line, 'severity': q.severity, 'text': q.text} for q in prog.problems]
    if not prog.ok:
        return {'python': '# The JSL could not be read: see the notes.\n', 'notes': notes, 'steps': [], 'ok': False}
    t.run()
    python = t.assemble()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        try:
            compile(python, '<converted JSL>', 'exec')
        except SyntaxError as e:
            # a translation that is not valid Python is a fault here: say so rather than hand it over
            notes.append({'line': 0, 'severity': 'error', 'text': f'The translation is not valid Python ({e.msg}, line {e.lineno}); please report the script.'})
    for w in caught:
        # such as a subscript of a number: the JSL there is most likely wrong too
        if issubclass(w.category, SyntaxWarning):
            notes.append({'line': 0, 'severity': 'warn', 'text': f'Python warns about line {w.lineno} of the translation: {str(w.message).rstrip(".")}' + ('' if str(w.message).endswith('?') else '.')})
    all_notes = notes + t.notes
    all_notes.sort(key=lambda n: (n['line'], {'error': 0, 'warn': 1, 'info': 2}.get(n['severity'], 3)))
    return {'python': python, 'notes': all_notes, 'steps': t.steps, 'ok': True}


@api('jsl.convert')
def convert(text, tables=None, current=None):
    """A JSL script as Python. tables: the page's open tables, [{name, columns:
    [{name, dataType, modelingType}]}]; current: the name of the page's
    current table. Returns {python, notes: [{line, severity, text}], steps:
    [{id, line, jsl, platform, table, frame, roles, options, where, marker,
    ...}], ok}; ok is False only when nothing of the script could be read."""
    return clean(convert_text(text, tables, current))
