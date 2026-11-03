"""The runtime the compiled code calls as R.<name>: workspaces, calls,
function handles, output, errors, and the session that runs commands and
files.

One session per Python process: the worker's. Its state is module-level.
"""
import asyncio
import math
import os
import re
import sys
import time
import types
import traceback

import numpy as np

from .values import (MError, Interrupt, NOVAL, COLON, Char, Str, Cell, Struct, FH, Obj, F64, C128,
                     EMPTY, share, share_all, is_shared, writable, class_of, shape_of, numel,
                     scalar_out, is_empty_double, py_str, to_float, size_str, Unset, Sparse)
from .ops import (plus, minus, times, rdivide, ldivide, power, mtimes, mrdivide, mldivide, mpower,
                  uminus, uplus, not_, and_, or_, xor, eq, ne, lt, le, gt, ge, transpose, ctranspose,
                  colon, truth, sc_truth, hcat, vcat, matrix, cat)
from .index import (idx, cidx, cidx1, fld, fld1, dyn_name, asgn, casgn, fasgn, asgn_chain, endv, one)
from . import display as D
from . import ops as _ops

INF = math.inf
NINF = -math.inf
NAN = math.nan

GLOBALS = {}
PERSISTENT = {}


# ---- workspaces -------------------------------------------------------------------

class Workspace(dict):
    """A function's (or the base) variables. A name with no value raises the
    language's error; a parameter not passed says so."""
    __slots__ = ('fname', 'params', 'gnames', 'nargs', 'imports')

    def __init__(self, fname='base', params=()):
        super().__init__()
        self.fname = fname
        self.params = params
        self.gnames = set()
        self.nargs = (-1, -1)
        self.imports = None          # import pkg.* and import pkg.name, in this workspace

    def __missing__(self, key):
        if key in self.params:
            raise MError('MATLAB:minrhs', 'Not enough input arguments.')
        raise MError('MATLAB:UndefinedFunction', f"Unrecognized function or variable '{key}'.")


class NestedWorkspace(Workspace):
    """A nested function's variables. The names it shares with the functions
    around it (`outer`: name -> the workspace of the nearest one that has it)
    are read and written there, so the functions see each other's changes;
    the rest are its own."""
    __slots__ = ('outer',)

    def __init__(self, fname, params, outer):
        super().__init__(fname, params)
        self.outer = outer

    def __getitem__(self, key):
        o = self.outer.get(key)
        return o[key] if o is not None else dict.__getitem__(self, key)

    def __setitem__(self, key, value):
        o = self.outer.get(key)
        if o is not None:
            o[key] = value
        else:
            dict.__setitem__(self, key, value)

    def __delitem__(self, key):
        o = self.outer.get(key)
        if o is not None:
            del o[key]
        else:
            dict.__delitem__(self, key)

    def __contains__(self, key):
        o = self.outer.get(key)
        return key in o if o is not None else dict.__contains__(self, key)

    def get(self, key, default=None):
        o = self.outer.get(key)
        return o.get(key, default) if o is not None else dict.get(self, key, default)

    def pop(self, key, *default):
        o = self.outer.get(key)
        return o.pop(key, *default) if o is not None else dict.pop(self, key, *default)

    def keys(self):
        return list(dict.keys(self)) + [k for k, o in self.outer.items() if k in o]

    def __iter__(self):
        return iter(self.keys())

    def __len__(self):
        return len(self.keys())

    def items(self):
        return [(k, self[k]) for k in self.keys()]

    def values(self):
        return [self[k] for k in self.keys()]


BASE = Workspace('base')


def declare_global(W, name):
    if name not in GLOBALS:
        v = W.get(name, NOVAL) if isinstance(W, dict) else NOVAL
        GLOBALS[name] = EMPTY() if v is NOVAL else v
    W.gnames.add(name)
    if name in W:
        del W[name]


def persistent_store(path, fname):
    key = (path, fname)
    s = PERSISTENT.get(key)
    if s is None:
        s = PERSISTENT[key] = {}
    return s


def varargin(args):
    c = Cell.of_list(list(args))
    share_all(c.a)
    return c


def too_many_inputs(name):
    e = MError('MATLAB:TooManyInputs', 'Too many input arguments.')
    e.fn = name
    return e


# ---- arguments blocks ---------------------------------------------------------------------------------

_CONVERTIBLE = {'double', 'single', 'int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32', 'uint64', 'logical',
                'char', 'string', 'cellstr'}


def _arg_where(pos, field):
    return f"Invalid value for '{field}' argument." if field else f'Invalid argument at position {pos}.'


def _builtin(name, *args):
    info = BUILTINS[name]
    r = info.fn(BASE, 1, *args) if info.ws else info.fn(1, *args)
    return run_sync(r) if info.aw else r


def check_arg(v, pos, field, dims, cls, where=None):
    """An argument of an arguments block made its class (converted when it
    can be: a number to another kind, text to char or string) and its size
    (a scalar spread to a fixed size, a vector turned the way asked)."""
    where = where or _arg_where(pos, field)
    if cls:
        c = class_of(v)
        if c != cls:
            if cls in _CONVERTIBLE and c not in ('cell', 'struct', 'function_handle') or cls == 'string' and c == 'cell':
                try:
                    v = _builtin(cls, v)
                except MError:
                    raise MError('MATLAB:validation:UnableToConvert', f'{where} Value must be of class {cls}, or convertible to it.')
            elif not _builtin('isa', v, Char.of(cls)):
                raise MError('MATLAB:validation:UnableToConvert', f'{where} Value must be of class {cls}.')
    if dims:
        shp = tuple(shape_of(v))
        want = tuple(dims)

        def fits(s):
            s = s + (1,) * (len(want) - len(s))
            return all(x == 1 for x in s[len(want):]) and all(w is None or w == x for w, x in zip(want, s))
        if not fits(shp):
            n = numel(v)
            if n == 1 and all(w is not None for w in want):
                v = _builtin('repmat', v, np.array([[float(w) for w in want]]))
            elif len(want) == 2 and 1 in want and sum(1 for x in shp if x != 1) <= 1 and len(shp) == 2 and \
                    (want[0] if want[1] == 1 else want[1]) in (None, n):
                v = _builtin('reshape', v, float(n if want[0] != 1 else 1), float(1 if want[0] != 1 else n))
            else:
                raise MError('MATLAB:validation:IncompatibleSize',
                             f"{where} Value must be of size {'x'.join(':' if w is None else str(w) for w in want)}.")
    return v


def arg_error(e, pos, field):
    """A validator's error, told against the argument it was checking."""
    return MError(e.identifier or 'MATLAB:validators:failed', f'{_arg_where(pos, field)} {e.message}')


def nv_args(rest, fields, fname, k):
    """Name-value pairs after the positional arguments as {field: value}:
    names matched without regard to case (or by a unique start)."""
    if len(rest) % 2:
        raise MError('MATLAB:validators:missingValue', f'Name-value arguments of {fname} must come in pairs.')
    low = {f.lower(): f for f in fields}
    out = {}
    for i in range(0, len(rest), 2):
        n = rest[i]
        if type(n) not in (Char, Str) or numel(n) == 0:
            raise MError('MATLAB:TooManyInputs', f'Invalid argument at position {k + i + 1}: a name-value argument of {fname} must start with its name.')
        s = py_str(n)
        f = low.get(s.lower())
        if f is None:
            hits = [v for key, v in low.items() if key.startswith(s.lower())]
            f = hits[0] if len(hits) == 1 else None
        if f is None:
            raise MError('MATLAB:validators:unknownName', f"'{s}' is not a name-value argument of {fname}. Its names: {', '.join(fields)}.")
        out[f] = share(rest[i + 1])
    return out


def nv_struct(d, fields):
    """The name-value arguments given or defaulted, as a struct in their declared order."""
    return Struct.scalar({f: d[f] for f in fields if f in d})


def too_many_outputs(name):
    e = MError('MATLAB:TooManyOutputs', 'Too many output arguments.')
    e.fn = name
    return e


def fout(W, outs, nargout, fname):
    """A function's outputs, as a call asked for them."""
    if not outs:
        return None
    if outs[-1] == 'varargout':
        fixed = list(outs[:-1])
        vals = []
        for o in fixed:
            vals.append(W.get(o, NOVAL))
        vo = W.get('varargout', NOVAL)
        if vo is not NOVAL:
            if type(vo) is not Cell:
                raise MError('MATLAB:varargoutNotCell', 'The variable varargout must be a cell array.')
            vals += vo.items()
    else:
        vals = [W.get(o, NOVAL) for o in outs]
        fixed = outs
    want = max(nargout, 1)
    if nargout <= 1:
        v = vals[0] if vals else NOVAL
        if v is NOVAL:
            if nargout == 0:
                return None
            name = outs[0]
            raise MError('MATLAB:unassignedOutputs', f'Output argument "{name}" (and possibly others) not assigned a value in the execution with "{fname}" function.')
        return v
    if len(vals) < nargout:
        raise MError('MATLAB:TooManyOutputs', 'Too many output arguments.') if outs[-1] != 'varargout' else MError('MATLAB:unassignedOutputs', f'Output argument "varargout{{{len(vals) - len(fixed) + 1}}}" not assigned a value in the execution with "{fname}" function.')
    for i in range(nargout):
        if vals[i] is NOVAL:
            name = outs[i] if i < len(fixed) else f'varargout{{{i - len(fixed) + 1}}}'
            raise MError('MATLAB:unassignedOutputs', f'Output argument "{name}" (and possibly others) not assigned a value in the execution with "{fname}" function.')
    return tuple(vals[:nargout])


def outs(r, n):
    """The n values of a multiple assignment from a call's result."""
    if n <= 1:
        if r is None:
            raise MError('MATLAB:TooManyOutputs', 'Too many output arguments.')
        return (r,)
    if r is None or not isinstance(r, tuple):
        raise MError('MATLAB:TooManyOutputs', 'Too many output arguments.')
    if len(r) < n:
        raise MError('MATLAB:TooManyOutputs', 'Too many output arguments.')
    return r


def need(vals, n):
    if len(vals) < n:
        raise MError('MATLAB:needMoreRhsOutputs', 'Insufficient number of outputs from right hand side of equal sign to satisfy assignment.')
    return vals


def single_out(v, n):
    if n > 1 if isinstance(n, int) else int(n) > 1:
        raise MError('MATLAB:TooManyOutputs', 'Too many output arguments.')
    return v


def idx_n(A, args, nargout):
    """Indexing where a call could also be meant (nargout given)."""
    if nargout > 1:
        raise MError('MATLAB:TooManyOutputs', 'Too many output arguments.')
    return idx(A, args)


def cellmat(rows):
    """A { ... } literal: every value is one element (a cell inside braces
    stays a cell, nested)."""
    out_rows = []
    for r in rows:
        if not r:
            continue
        a = np.empty((1, len(r)), object)
        for j, v in enumerate(r):
            a[0, j] = share(v)
        out_rows.append(a)
    if not out_rows:
        return Cell.empty()
    if len(out_rows) == 1:
        return Cell(out_rows[0])
    n = out_rows[0].shape[1]
    for a in out_rows:
        if a.shape[1] != n:
            raise MError('MATLAB:catenate:dimensionMismatch', 'Dimensions of arrays being concatenated are not consistent.')
    return Cell(np.vstack(out_rows))


# ---- conditions -------------------------------------------------------------------

def is_false1(v):
    """A scalar that is false: the left of & in an if stops there."""
    t = type(v)
    if t is bool:
        return not v
    if t is float:
        return v == 0.0
    return numel(v) == 1 and not truth(v) if t is np.ndarray else False


def is_true1(v):
    t = type(v)
    if t is bool:
        return v
    if t is float:
        return v != 0.0 and v == v
    return numel(v) == 1 and truth(v) if t is np.ndarray else False


def swmatch(v, case):
    """switch: a case matches by ==  for numbers, strcmp for text, and a
    cell case matches if any element does."""
    tc = type(case)
    if tc is Cell:
        for x in case.a.reshape(-1, order='F'):
            if swmatch(v, x):
                return True
        return False
    tv = type(v)
    if tv in (Char, Str) or tc in (Char, Str):
        if tv not in (Char, Str) or tc not in (Char, Str):
            return False
        try:
            return py_str(v) == py_str(case)
        except MError:
            return False
    if numel(case) == 0 or numel(v) == 0:
        return False
    if numel(v) != 1:
        raise MError('MATLAB:switch:caseExpressionNotScalar', 'SWITCH expression must be a scalar or a character vector.')
    try:
        r = eq(v, case)
    except MError:
        return False
    if type(r) is bool:
        return r
    return bool(np.all(r)) if numel(case) == 1 else False


# ---- loops and yielding -------------------------------------------------------------

def forrange(a, b, s=None):
    """The values of a for loop over a:b or a:s:b."""
    if s is None:
        r = _ops.frange(a, b)
        if r is not None:
            return r
        return forit(colon(a, b))
    r = _ops.frange(a, s, b)
    if r is not None:
        return r
    return forit(colon(a, s, b))


class LoopRange:
    """The values of a parfor loop over a range of whole numbers, as floats:
    gone through more than once (the pool is tried first) and never made."""
    __slots__ = ('first', 'step', 'count')

    def __init__(self, first, step, count):
        self.first, self.step, self.count = first, step, count

    def __iter__(self):
        return map(float, range(self.first, self.first + self.step * self.count, self.step))

    def __len__(self):
        return self.count


def parfor_values(a, b, s=None):
    """A parfor loop's values: a LoopRange for a range of whole numbers,
    else the values a for loop takes."""
    start, step, stop = (a, 1.0, b) if s is None else (a, b, s)
    if type(start) is float and type(step) is float and type(stop) is float and start == start and stop == stop \
            and start == int(start) and step == int(step) and step != 0 and abs(start) < 2 ** 52 and abs(stop) < 2 ** 52:
        n = int(math.floor((stop - start) / step + 1e-9)) + 1
        return LoopRange(int(start), int(step), max(n, 0))
    return forit(colon(a, b) if s is None else colon(a, b, s))


async def parfor(W, fn, plan, vals, maxw):
    """A parfor loop on the pool's workers: True when it ran there, False when
    the caller runs it here one pass at a time (no pool, or something it
    needs cannot go to the workers)."""
    from .builtins.parallel import run_parfor
    return await run_parfor(W, fn, plan, vals, maxw)


def parfor_note(reason, line, path, noted):
    """Say once (noted: the module's own record) why a parfor loop's passes
    run one at a time."""
    key = (line, reason)
    if key in noted:
        return
    noted.add(key)
    where = f'at line {line}' if path == 'command' else f'in {os.path.basename(path)} at line {line}'
    warn('MATLAB:parfor:serial', f'The parfor loop {where} runs one pass at a time: {reason}.')


class _RedUnset:
    """A reduction a worker has not reached yet."""
    def __repr__(self):
        return 'RED_UNSET'


RED_UNSET = _RedUnset()


def red_join(op, prefix, cur, v):
    """cur op v (or v op cur when prefix): one step of a reduction, or the
    join of two parts of it."""
    a, b = (v, cur) if prefix else (cur, v)
    if op == '+':
        return plus(a, b)
    if op == '-':
        return minus(a, b)
    if op == '.*':
        return times(a, b)
    if op == '*':
        return mtimes(a, b)
    if op == '&':
        return and_(a, b)
    if op == '|':
        return or_(a, b)
    if op == 'h':
        return hcat([a, b])
    if op == 'v':
        return vcat([a, b])
    return BUILTINS[op].fn(1, a, b)


def red_step(op, prefix, cur, v):
    """A worker's reduction step: its first sets the part (x - e starts it at
    -e, so that the parts are joined by +)."""
    if cur is RED_UNSET:
        return uminus(v) if op == '-' else share(v)
    return red_join(op, prefix, cur, v)


def parfor_collect(W, ks, sliced, reds):
    """What a block of passes sends back: each sliced variable's slice for
    each pass (None where the pass set none), and each reduction's part
    (None when no pass reached it)."""
    slices = {}
    for name, brace, pattern in sliced:
        x = W.get(name, NOVAL)
        got = []
        for k in ks:
            if x is NOVAL:
                got.append(None)
                continue
            args = tuple(float(k) if p == 'k' else COLON if p == ':' else float(p) for p in pattern)
            try:
                got.append(cidx1(x, args) if brace else idx(x, args))
            except MError:
                got.append(None)
        slices[name] = got
    parts = {}
    for name in reds:
        v = W.get(name, RED_UNSET)
        parts[name] = None if v is RED_UNSET else v
    return {'slices': slices, 'reds': parts}


class ArgNames:
    """The names of a call's arguments that are plain variables (None for
    the others): the compiler passes them last to table and timetable,
    which name their variables after them."""
    __slots__ = ('names',)

    def __init__(self, names):
        self.names = names


class _NoVObj:
    pass


VOBJ = _NoVObj         # vobj.VObj (vobj.py sets it)


def forit(v):
    """A for loop takes the columns of its value one at a time."""
    t = type(v)
    if t is float or t is bool or t is complex:
        return (v,)
    if isinstance(v, VOBJ):
        return v.columns()
    if t is Sparse:
        from . import sparsemat
        return sparsemat.columns(v)
    if t is np.ndarray:
        if v.size == 0:
            return ()
        if v.ndim == 2 and v.shape[0] == 1:
            if v.dtype == np.float64 or v.dtype == np.bool_ or v.dtype == np.complex128:
                return v.reshape(-1).tolist() if v.dtype != np.complex128 else [complex(x) for x in v.reshape(-1)]
            return [v[:, j:j + 1].copy() for j in range(v.shape[1])]
        a = v.reshape(v.shape[0], -1, order='F')
        return [scalar_out(a[:, j:j + 1].copy()) for j in range(a.shape[1])]
    if t is Char:
        a = v.a.reshape(v.a.shape[0], -1, order='F') if v.a.ndim > 2 else v.a
        return [Char(a[:, j:j + 1].copy()) for j in range(a.shape[1])] if a.size else ()
    if t is Cell:
        a = v.a.reshape(v.a.shape[0], -1, order='F') if v.a.ndim > 2 else v.a
        out = []
        for j in range(a.shape[1]):
            col = a[:, j:j + 1].copy()
            share_all(col)
            out.append(Cell(col))
        return out
    if t is Str:
        a = v.a
        return [Str(a[:, j:j + 1].copy()) for j in range(a.shape[1])] if a.size else ()
    if t is Struct:
        out = []
        for j in range(v.shape[1] if len(v.shape) > 1 else 1):
            out.append(idx(v, (COLON, float(j + 1))))
        return out
    return (v,)


_TICK = [0, 0.0]
YIELD_EVERY = 0.05
SYNC = [0]
INTERRUPT = [False]
T_DEBUG = [False]


def tk():
    """Called once per loop iteration: true when it is time to look up
    (Ctrl+C, output to send)."""
    n = _TICK[0] + 1
    if n < 200:
        _TICK[0] = n
        return False
    _TICK[0] = 0
    now = time.perf_counter()
    if now - _TICK[1] >= YIELD_EVERY or INTERRUPT[0]:
        return True
    return False


async def H(W, line, mod):
    """The hook between statements: Ctrl+C, the debugger, and a moment for
    the page."""
    if INTERRUPT[0]:
        INTERRUPT[0] = False
        raise Interrupt()
    if SYNC[0]:
        return
    if DEBUGGER.active:
        await DEBUGGER.hook(W, line, mod)
    now = time.perf_counter()
    if now - _TICK[1] >= YIELD_EVERY:
        _TICK[1] = now
        flush()
        await asyncio.sleep(0)
        if INTERRUPT[0]:
            INTERRUPT[0] = False
            raise Interrupt()


def run_sync(coro):
    """Run a coroutine to its end without an event loop (for callbacks from
    SciPy). It must not wait for anything."""
    SYNC[0] += 1
    try:
        try:
            coro.send(None)
        except StopIteration as e:
            return e.value
        coro.close()
        raise MError('MATLAB:callbackWait', 'This function cannot wait for input here (it runs inside a numerical routine).')
    finally:
        SYNC[0] -= 1


class _Debugger:
    active = False

    def wants(self, path):
        return False

    async def hook(self, W, line, mod):
        pass

    async def keyboard(self, W):
        raise MError('MATLAB:keyboard', 'keyboard: the debugger is not available here.')


DEBUGGER = _Debugger()

EVENT_HOOK = [None]       # fn(dict): events for the page (clc, figures, files)
INPUT_HOOK = [None]       # async fn(prompt, kind) -> str: the page's answer


PAGE_HOOK = [None]        # async fn(request) -> answer: the page draws, measures or asks
FLUSH_FIGURES = None      # set by the graphics module


async def ask_page(request):
    """Ask the page for something only it can give (a figure drawn to a
    picture, mouse clicks) and wait for the answer."""
    flush()
    if PAGE_HOOK[0] is None or SYNC[0]:
        return None
    return await PAGE_HOOK[0](request)


def flush_figures():
    if FLUSH_FIGURES is not None:
        FLUSH_FIGURES()


async def ask_input(prompt, kind='line'):
    """Wait for the user to answer (input(), pause with no time)."""
    flush()
    if INPUT_HOOK[0] is None:
        raise MError('MATLAB:input:noInput', 'Input is not available here.')
    if SYNC[0]:
        raise MError('MATLAB:callbackWait', 'This function cannot wait for input here (it runs inside a numerical routine).')
    return await INPUT_HOOK[0](prompt, kind)


async def sleep(t):
    """pause(t): flush the output and figures, then wait."""
    flush()
    if EVENT_HOOK[0] is not None:
        EVENT_HOOK[0]({'type': 'drawnow'})
    if SYNC[0]:
        end = time.perf_counter() + t
        while time.perf_counter() < end:
            pass
        return
    from .uievents import process
    end = time.perf_counter() + t
    while True:
        left = end - time.perf_counter()
        if left <= 0:
            break
        await asyncio.sleep(min(left, 0.05))
        if INTERRUPT[0]:
            INTERRUPT[0] = False
            raise Interrupt()
        # the callbacks of what people did meanwhile run here, as at drawnow
        await process(wait=False)
    _TICK[1] = time.perf_counter()


class Cleanup(Obj):
    """onCleanup(f): runs f when the variable holding it goes."""
    __slots__ = ('f', 'done')
    cls = 'onCleanup'
    is_handle = True

    def __init__(self, f):
        self.f = f
        self.done = False

    def __del__(self):
        if not self.done:
            self.done = True
            try:
                if isinstance(self.f, FH):
                    self.f.scall(0)
            except Exception:
                pass


# ---- function handles ---------------------------------------------------------------

class Anon(FH):
    """@(x) ...: the compiled body and the values it captured."""
    __slots__ = ('fn', 'src', 'cap', 'nparams', 'vararg')

    def __init__(self, fn, src, cap, nparams, vararg=False):
        self.fn = fn
        self.src = src
        self.cap = cap
        self.nparams = nparams
        self.vararg = vararg

    def text(self):
        return self.src

    async def acall(self, nargout, *args):
        if len(args) > self.nparams and not self.vararg:
            raise MError('MATLAB:TooManyInputs', 'Too many input arguments.')
        return await self.fn(nargout, self.cap, args)

    def scall(self, nargout, *args):
        return run_sync(self.acall(nargout, *args))

    def name(self):
        return self.src


class NamedFH(FH):
    """@name: a function found by name when called (a builtin or a file)."""
    __slots__ = ('fname', 'target')

    def __init__(self, fname, target=None):
        self.fname = fname
        self.target = target

    def text(self):
        return '@' + self.fname

    async def acall(self, nargout, *args):
        if self.target is not None:
            return await self.target(nargout, *args)
        return await call(None, self.fname, nargout, args)

    def scall(self, nargout, *args):
        info = BUILTINS.get(self.fname)
        if info is not None and not info.aw and not info.ws and self.target is None and not _user_file(self.fname) \
                and not any(getattr(a, 'ci', None) is not None for a in args):
            return info.fn(nargout, *args)
        return run_sync(self.acall(nargout, *args))

    def name(self):
        return self.fname


def fh(name):
    return NamedFH(name)


def LocalFH(name, fn):
    return NamedFH(name, fn)


async def fcall(f, nargout, args):
    """f(args) for a function handle."""
    return await f.acall(nargout, *args)


def anon_ws(cap, params, args):
    W = Workspace('@', tuple(p for p in params if p != '~'))
    W.update(cap)
    n = len(args)
    for i, p in enumerate(params):
        if p == 'varargin':
            W['varargin'] = varargin(args[i:])
            break
        if i < n and p != '~':
            W[p] = share(args[i])
    return W


def anon_one(v, nargout):
    if nargout > 1:
        raise MError('MATLAB:TooManyOutputs', 'Too many output arguments.')
    return v


def anon_list(vals, nargout):
    if nargout <= 1:
        return one(vals)
    if len(vals) < nargout:
        raise MError('MATLAB:needMoreRhsOutputs', 'Insufficient number of outputs from right hand side of equal sign to satisfy assignment.')
    return tuple(vals[:nargout])


# ---- calls by name ------------------------------------------------------------------

BUILTINS = {}          # name -> Info (filled by builtins.load())
B = types.SimpleNamespace()


async def vget(W, name):
    """A name in a script that may be a variable now or a function."""
    v = W.get(name, NOVAL) if W is not None else NOVAL
    if v is not NOVAL:
        return v
    return await call(W, name, 1, ())


async def call(W, name, nargout, args):
    """A call to a function by name: a variable of that name first (made at
    run time, by load or eval), then a file on the path, then a builtin."""
    if W is not None and name in W and name not in ('ans',):
        v = W[name]
        if isinstance(v, FH):
            return await v.acall(nargout, *args)
        if nargout > 1:
            raise MError('MATLAB:TooManyOutputs', 'Too many output arguments.')
        return idx(v, args) if args else v
    if W is not None and getattr(W, 'gnames', None) and name in W.gnames:
        v = GLOBALS.get(name, NOVAL)
        return idx(v, args) if args else v
    if W is not None and '.' in name:
        # s.a.b compiled as a package function's name because s was no
        # variable then: a field of the variable if there is one now
        base, *fields = name.split('.')
        v = W.get(base, NOVAL)
        if v is NOVAL and base in getattr(W, 'gnames', ()):
            v = GLOBALS.get(base, NOVAL)
        if v is not NOVAL:
            for f in fields:
                v = fld1(v, f)
            if args and isinstance(v, FH):
                return await v.acall(nargout, *args)
            if nargout > 1:
                raise MError('MATLAB:TooManyOutputs', 'Too many output arguments.')
            return idx(v, args) if args else v
    if args:
        # a method of an object among the arguments comes first
        from . import classdef as CD
        r = await CD.dispatch(name, nargout, args)
        if r is not NOVAL:
            return r
    full = imported(W, name.split('.', 1)[0])
    if full is not None:
        # a name an import gave: pkg.name (and pkg.Cls.member)
        name = full + name[len(name.split('.', 1)[0]):]
    if '.' in name and name.count('.') == 1:
        # ClassName.staticMethod(...) or ClassName.Constant
        from . import classdef as CD
        base, rest = name.split('.')
        r = await CD.static_or_const(base, rest, nargout, args, sys.modules[__name__])
        if r is not NOVAL:
            return r
    if '.' in name and name.count('.') > 1 and resolve(name) is None:
        # pkg.Cls.staticMethod(...), ClassName.Member.prop, ClassName.Member.method(...):
        # the longest start that is a class, then its member, then fields
        from . import classdef as CD
        parts = name.split('.')
        for k in range(len(parts) - 1, 0, -1):
            base = '.'.join(parts[:k])
            if find_file(base) is None:
                continue
            fields = parts[k + 1:]
            r = await CD.static_or_const(base, parts[k], nargout if not fields else 1, args if not fields else (), sys.modules[__name__])
            if r is NOVAL:
                break
            if not fields:
                return r
            for f in fields[:-1]:
                r = fld1(r, f)
            v = fld1(r, fields[-1])
            if isinstance(v, FH):
                return await v.acall(nargout, *args)
            return idx(v, args) if args else v
    target = resolve(name)
    if target is None:
        raise MError('MATLAB:UndefinedFunction', f"Unrecognized function or variable '{name}'.")
    kind, obj = target
    if kind == 'builtin':
        info = obj
        if info.ws:
            r = info.fn(W if W is not None else BASE, nargout, *args)
        else:
            r = info.fn(nargout, *args)
        if info.aw:
            r = await r
        return r
    if kind == 'script':
        if args:
            raise MError('MATLAB:scriptNotAFunction', f"Attempt to execute SCRIPT {name} as a function:\n{obj.path}")
        if nargout > 0:
            raise MError('MATLAB:scriptNotAFunction', f"Attempt to execute SCRIPT {name} as a function:\n{obj.path}")
        await run_script(obj, W if W is not None else BASE)
        return None
    return await obj(nargout, *args)


# ---- results and display --------------------------------------------------------------

_out = []
OUT_HOOK = [None]       # fn(text, kind) to send output somewhere
_last_flush = [0.0]


def write(text, kind='out'):
    if not text:
        return
    if OUT_HOOK[0] is not None:
        _out.append((kind, text))
        if len(_out) > 200:
            flush()
    else:
        _out.append((kind, text))


def flush():
    if OUT_HOOK[0] is not None and _out:
        # join consecutive pieces of the same kind
        merged = []
        for k, t in _out:
            if merged and merged[-1][0] == k:
                merged[-1][1].append(t)
            else:
                merged.append((k, [t]))
        _out.clear()
        for k, ts in merged:
            OUT_HOOK[0](''.join(ts), k)


def take_output():
    text = ''.join(t for k, t in _out)
    _out.clear()
    return text


def show(W, name):
    write(D.display(name, W[name]))


def show_value(name, v):
    write(D.display(name, v))


def ans_list(W, vals, show_it):
    for v in vals:
        W['ans'] = share(v)
        if show_it:
            write(D.display('ans', v))


def warn(ident, msg):
    if WARN_STATE.get(ident, WARN_STATE.get('all', 'on')) == 'off':
        return
    LASTWARN[0] = (msg, ident)
    write(f'Warning: {msg}\n', 'warn')


WARN_STATE = {}
LASTWARN = [('', '')]
_ops._warn_hook[0] = warn


# ---- errors -------------------------------------------------------------------------

class MExc(Obj):
    """An MException value: identifier, message, stack, cause."""
    __slots__ = ('err',)
    cls = 'MException'

    def __init__(self, err):
        self.err = err

    def getprop(self, name):
        e = self.err
        if name == 'message':
            return Char.of(e.message)
        if name == 'identifier':
            return Char.of(e.identifier)
        if name == 'stack':
            st = Struct((len(e.stack), 1), {k: np.empty((len(e.stack), 1), object) for k in ('file', 'name', 'line')})
            for i, (nm, fl, ln) in enumerate(e.stack):
                st.f['file'][i, 0] = Char.of(fl)
                st.f['name'][i, 0] = Char.of(nm)
                st.f['line'][i, 0] = float(ln)
            return st
        if name == 'cause':
            return Cell.of_list([MExc(c) for c in e.cause], (len(e.cause), 1))
        if name == 'Correction':
            return EMPTY()
        return super().getprop(name)

    def propnames(self):
        return ['identifier', 'message', 'cause', 'stack']

    def display_lines(self):
        e = self.err
        lines = ['  MException with properties:', '']
        lines.append(f"    identifier: '{e.identifier}'")
        lines.append(f"       message: '{e.message}'")
        lines.append(f"         cause: {{{len(e.cause)}×1 cell}}")
        lines.append(f"         stack: [{len(e.stack)}×1 struct]")
        lines.append('    Correction: []')
        return lines


def mexc(e):
    return MExc(e)


def caught(e):
    """An exception caught by try/catch, as the language's error (Python
    errors from the runtime included). It is the last error too, as
    `catch, errordlg(lasterr)` expects."""
    if isinstance(e, MError):
        if not e.stack:
            e.stack = stack_of(e.__traceback__)
        LASTERR[0] = e
        return e
    m = as_merror(e)
    m.stack = stack_of(e.__traceback__)
    LASTERR[0] = m
    return m


def as_merror(e):
    if isinstance(e, MError):
        return e
    if isinstance(e, KeyError):
        return MError('MATLAB:internal', f'Internal error: missing key {e}.')
    if isinstance(e, RecursionError):
        return MError('MATLAB:recursionLimit', 'Maximum recursion limit reached.')
    if isinstance(e, MemoryError):
        return MError('MATLAB:nomem', 'Out of memory.')
    if isinstance(e, TypeError):
        s = str(e)
        if 'positional argument' in s or 'takes' in s and 'given' in s:
            if 'missing' in s:
                return MError('MATLAB:minrhs', 'Not enough input arguments.')
            return MError('MATLAB:TooManyInputs', 'Too many input arguments.')
    if isinstance(e, ZeroDivisionError):
        return MError('MATLAB:divideByZero', 'Division by zero.')
    if isinstance(e, (np.linalg.LinAlgError,)):
        return MError('MATLAB:linalg', str(e))
    m = MError('MATLAB:internal', f'{type(e).__name__}: {e}')
    m.internal = traceback.format_exception(type(e), e, e.__traceback__)
    return m


MODULES = {}       # python filename -> CompiledModule


def stack_of(tb):
    """The compiled frames a traceback went through: [(name, file, line)],
    innermost first."""
    out = []
    while tb is not None:
        fr = tb.tb_frame
        fn = fr.f_code.co_filename
        if fn.startswith('<plab:'):
            mod = MODULES.get(fn)
            if mod is not None:
                pyline = tb.tb_lineno
                ml = mod.linemap[pyline - 1] if 0 < pyline <= len(mod.linemap) else 0
                name = fr.f_code.co_name
                if name.startswith('LF_'):
                    name = name[3:]
                    if mod.kind == 'function' and name != mod.name:
                        name = f'{mod.name}>{name}'
                elif name == 'SCRIPT':
                    name = mod.name
                elif name.startswith('_A'):
                    name = mod.ns.get('_ANON_TEXT', {}).get(name, '@(...)') if mod.ns else '@(...)'
                out.append((name, mod.path, ml))
        tb = tb.tb_next
    out.reverse()
    return out


def stack_of_frames():
    """The compiled functions running now, innermost first: [{name, file,
    line}] (for the debugger's stack list)."""
    f = sys._getframe(1)
    out = []
    while f is not None:
        fn = f.f_code.co_filename
        if fn.startswith('<plab:') and fn in MODULES:
            mod = MODULES[fn]
            nm = f.f_code.co_name
            if nm.startswith('LF_') or nm == 'SCRIPT':
                ln = mod.linemap[f.f_lineno - 1] if 0 < f.f_lineno <= len(mod.linemap) else 0
                name = nm[3:] if nm.startswith('LF_') else mod.name
                if mod.path != 'command':
                    out.append({'name': name, 'file': mod.path, 'line': ln})
        f = f.f_back
    return out


def source_line(path, line):
    mod = None
    for m in MODULES.values():
        if m.path == path:
            mod = m
            break
    text = mod.text if mod else None
    if text is None:
        return ''
    lines = text.split('\n')
    if 0 < line <= len(lines):
        return lines[line - 1]
    return ''


def link(path, line, text):
    """Output text that the page shows as a link to a file's line."""
    return f'\x01{path}:{line}\x02{text}\x03'


def format_error(e):
    """The text the Command Window shows for an error."""
    if isinstance(e, Interrupt):
        return 'Operation terminated by user.\n'
    m = as_merror(e)
    stack = m.stack or stack_of(e.__traceback__)
    lines = []
    user_frames = [s for s in stack if not s[0].startswith('@(') or True]
    if getattr(m, 'from_error_fn', False) and user_frames:
        name, path, ln = user_frames[0]
        label = name.split('>')[-1] if '>' not in name else name
        lines.append('Error using ' + (link(path, ln, label) if path != 'command' else label))
        lines.append(m.message)
        rest = user_frames[1:]
    elif m.fn:
        lines.append(f'Error using {m.fn}')
        lines.append(m.message)
        rest = user_frames
    else:
        lines.append(m.message)
        rest = user_frames
    if m.identifier == 'MATLAB:UndefinedFunction':
        mm = re.match(r"Unrecognized function or variable '([A-Za-z]\w*)'\.$", m.message)
        if mm:
            lines += where_else(mm.group(1))
    rest = [f for f in rest if f[0] != 'command']
    if rest:
        lines.append('')
        for name, path, ln in rest:
            if name.startswith('@'):
                # an anonymous function is named by its text, with no line
                lines.append('Error in ' + (link(path, ln, name) if path != 'command' else name))
                continue
            lines.append('Error in ' + link(path, ln, f'{name} (line {ln})'))
            src = source_line(path, ln)
            if src:
                lines.append(src.lstrip())
    text = '\n'.join(lines)
    return text + '\n'


# ---- files and the path -----------------------------------------------------------------

STATE = {'cwd': '/home/user', 'path': [], 'epoch': 0}
_file_cache = {}      # path -> (mtime, size, epoch, CompiledModule)
_resolve_cache = {}


class CompiledModule:
    def __init__(self, path, name, text, src, linemap, kind, ns):
        self.path = path
        self.name = name
        self.text = text
        self.src = src
        self.linemap = linemap
        self.kind = kind
        self.ns = ns


def bump_epoch():
    """Files were added, removed or changed: compiled code is rebuilt as it
    is next called."""
    STATE['epoch'] += 1
    _resolve_cache.clear()


def search_dirs():
    return [STATE['cwd']] + [p for p in STATE['path'] if p != STATE['cwd']]


def _user_file(name):
    if name in _resolve_cache:
        r = _resolve_cache[name]
        return r is not None and r[0] != 'builtin'
    for d in search_dirs():
        p = os.path.join(d, name + '.m')
        if os.path.isfile(p):
            return True
    return False


def find_file(name):
    if '.' in name:
        # pkg.f and pkg.sub.Cls: +pkg/f.m, +pkg/+sub/Cls.m (or its @Cls folder)
        *pkgs, last = name.split('.')
        if not all(re.fullmatch(r'[A-Za-z]\w*', x) for x in pkgs + [last]):
            return None
        rel = os.path.join(*['+' + x for x in pkgs])
        for d in search_dirs():
            for p in (os.path.join(d, rel, last + '.m'), os.path.join(d, rel, '@' + last, last + '.m')):
                if os.path.isfile(p):
                    return p
        return None
    for d in search_dirs():
        p = os.path.join(d, name + '.m')
        if os.path.isfile(p):
            return p
    return None


def imported(W, name):
    """The full name an import in W gives a bare name (import pkg.* or import pkg.name), or None."""
    imps = getattr(W, 'imports', None) if W is not None else None
    if not imps or '.' in name:
        return None
    for imp in reversed(imps):
        if imp.endswith('.*'):
            full = imp[:-1] + name
            if find_file(full) is not None:
                return full
        elif imp.rsplit('.', 1)[-1] == name:
            return imp
    return None


_FUNCTION_LINE = re.compile(r'function\b\s*(?:\[[^\]]*\]\s*=\s*|[A-Za-z]\w*\s*=\s*)?([A-Za-z]\w*)')


def where_else(name):
    """For the Command Window's error when a name is no function or
    variable: lines that say where a program of that name is after all.
    A file name.m in a folder under the home folder that is not searched,
    or a file in a searched folder whose function is called name (a file
    is called by its own name). Looked for only when the error is shown,
    never for one that try/catch takes."""
    searched = set(search_dirs())
    home = STATE.get('home', '/home/user')
    out = []
    folders = []
    seen = 0
    for d, subs, files in os.walk(home):
        seen += 1
        if seen > 2000:
            break
        subs[:] = sorted(s for s in subs if not s.startswith('.')) if d[len(home):].count('/') < 5 else []
        if d not in searched and name + '.m' in files:
            folders.append(d)
    if folders:
        where = folders[0] if len(folders) == 1 else ', '.join(folders[:3]) + (' and more' if len(folders) > 3 else '')
        out.append(f'{name}.m is in {where}, which is not the current folder or on the path: cd to its folder, or add the folder with addpath, to call {name}.')
    others = []
    seen = 0
    for d in search_dirs():
        try:
            entries = sorted(os.listdir(d))
        except OSError:
            continue
        for f in entries:
            if not f.endswith('.m') or f == name + '.m':
                continue
            seen += 1
            if seen > 1000:
                break
            try:
                head = read_source(os.path.join(d, f), 8192)
            except OSError:
                continue
            for k, ln in enumerate(head.splitlines()):
                s = ln.strip()
                if s and not s.startswith('%'):
                    mm = _FUNCTION_LINE.match(s)
                    if mm and mm.group(1) == name:
                        others.append((os.path.join(d, f), k + 1))
                    break
    for p, line in others[:3]:
        out.append(f'{link(p, line, os.path.basename(p))} in {os.path.dirname(p)} has the function {name}, but a program file is called by its own name, '
                   f'{os.path.splitext(os.path.basename(p))[0]}: rename the file {name}.m to call it as {name}.')
    return out


def resolve(name):
    r = _resolve_cache.get(name)
    if r is not None:
        kind, obj, epoch = r
        if epoch == STATE['epoch']:
            if kind == 'file':
                return _file_target(obj)
            return kind, obj
    p = find_file(name)
    if p is not None:
        _resolve_cache[name] = ('file', p, STATE['epoch'])
        return _file_target(p)
    info = BUILTINS.get(name)
    if info is not None:
        _resolve_cache[name] = ('builtin', info, STATE['epoch'])
        return 'builtin', info
    return None


def _file_target(path):
    mod = load_file(path)
    if mod.kind == 'script':
        return 'script', mod
    return 'function', mod.ns['MAIN']


def source_text(data):
    """The text of a program file's bytes: UTF-8, or for a file of an older
    release that is not UTF-8, Windows-1252 (in which letters such as 'ö'
    and signs such as '®' were written then)."""
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError as e:
        if e.reason == 'unexpected end of data' and e.start >= len(data) - 3:
            # a part read: the last letter was cut
            return data[:e.start].decode('utf-8-sig', errors='replace')
        return data.decode('cp1252', errors='replace')


def read_source(path, limit=-1):
    with open(path, 'rb') as f:
        return source_text(f.read(limit))


def load_file(path):
    """The compiled module of a file (compiled again when the file or the
    set of files changed)."""
    st = os.stat(path)
    c = _file_cache.get(path)
    if c is not None and c[0] == st.st_mtime_ns and c[1] == st.st_size and c[2] == STATE['epoch']:
        return c[3]
    text = read_source(path)
    mod = compile_file(path, text)
    _file_cache[path] = (st.st_mtime_ns, st.st_size, STATE['epoch'], mod)
    return mod


def compile_file(path, text):
    from .compiler import compile_source
    from . import classdef as CD
    name = os.path.splitext(os.path.basename(path))[0]
    if CD.is_classdef(text):
        import sys as _sys
        ci = CD.build(path, text, _sys.modules[__name__])

        async def construct(nargout, *args):
            return await CD.construct(ci, nargout, args)
        mod = CompiledModule(path, name, text, '', {}, 'class', {'MAIN': construct})
        mod.classinfo = ci
        return mod
    kind_hint = 'file'
    src, linemap, prog = compile_source(text, BUILTINS, kind='file', user_funcs=_user_file, modname=name, path=path)
    if prog.kind == 'function':
        fname = prog.funcs[0].name
        if fname != name:
            pass   # the file name wins, as in the language
        modkind = 'function'
    else:
        modkind = 'script'
    pyfile = f'<plab:{path}>'
    code = compile(src, pyfile, 'exec')
    ns = make_ns(path)
    exec(code, ns)
    if modkind == 'function':
        ns['MAIN'] = ns[f'LF_{prog.funcs[0].name}']
    mod = CompiledModule(path, name, text, src, linemap, modkind, ns)
    mod.prog = prog
    MODULES[pyfile] = mod
    return mod


def make_ns(path):
    from . import runtime as R_mod
    return {'R': R_mod, 'B': B, 'NOVAL': NOVAL, 'COLON': COLON, 'FH': FH, 'G': GLOBALS, '_PF_NOTED': set(),
            'T_': DEBUGGER.active and DEBUGGER.wants(path) if hasattr(DEBUGGER, 'wants') else False,
            'M_': path, '__name__': f'plab_{os.path.basename(path)}'}


async def run_script(mod, W):
    """A script runs in the caller's workspace; it is compiled for the
    names that workspace holds."""
    from .compiler import compile_source
    key_names = frozenset(W.keys())
    fh_names = frozenset(k for k, v in W.items() if isinstance(v, FH))
    gn = frozenset(getattr(W, 'gnames', ()))
    cache = getattr(mod, 'variants', None)
    if cache is None:
        cache = mod.variants = {}
    used = getattr(mod, 'used_names', None)
    if used is None:
        from .compiler import uses_names
        used = mod.used_names = uses_names(mod.prog.body) | set().union(*[uses_names(f.body) for f in mod.prog.funcs]) if mod.prog.funcs else uses_names(mod.prog.body)
    sig = (frozenset(n for n in key_names if n in used), frozenset(n for n in fh_names if n in used), gn)
    entry = cache.get(sig)
    if entry is None:
        src, linemap, prog = compile_source(mod.text, BUILTINS, kind='file', user_funcs=_user_file,
                                            ws_names=sig[0], ws_fh=sig[1], ws_globals=gn,
                                            modname=mod.name, path=mod.path)
        pyfile = f'<plab:{mod.path}>'
        code = compile(src, pyfile, 'exec')
        ns = make_ns(mod.path)
        exec(code, ns)
        m2 = CompiledModule(mod.path, mod.name, mod.text, src, linemap, 'script', ns)
        MODULES[pyfile] = m2
        entry = cache[sig] = (ns['SCRIPT'], m2)
    fn, m2 = entry
    MODULES[f'<plab:{mod.path}>'] = m2
    await fn(W)


# ---- the session ------------------------------------------------------------------------

_cmd_n = [0]


def compile_command(text, W=None):
    """A command line, compiled against the base workspace's names."""
    from .compiler import compile_source
    W = W if W is not None else BASE
    names = set(W.keys())
    fh_names = set(k for k, v in W.items() if isinstance(v, FH))
    src, linemap, prog = compile_source(text, BUILTINS, kind='command', user_funcs=_user_file,
                                        ws_names=names, ws_fh=fh_names, ws_globals=W.gnames,
                                        modname='command', path='command')
    _cmd_n[0] += 1
    pyfile = f'<plab:command#{_cmd_n[0]}>'
    code = compile(src, pyfile, 'exec')
    ns = make_ns('command')
    exec(code, ns)
    mod = CompiledModule('command', 'command', text, src, linemap, 'command', ns)
    MODULES[pyfile] = mod
    # keep the last few commands' modules (their anonymous functions may still be called)
    return ns['SCRIPT'], mod


async def execute(text, W=None):
    """Run a command line. Errors are written to the output; returns True
    when it ran to the end."""
    W = W if W is not None else BASE
    try:
        fn, mod = compile_command(text, W)
    except MError as e:
        write(format_parse_error(e, text), 'err')
        return False
    try:
        await fn(W)
        return True
    except Interrupt:
        flush()
        write('Operation terminated by user.\n', 'err')
        return False
    except MError as e:
        e.stack = e.stack or stack_of(e.__traceback__)
        LASTERR[0] = e
        write(format_error(e), 'err')
        return False
    except RecursionError as e:
        m = MError('MATLAB:recursionLimit', 'Maximum recursion limit reached. Use set(0,\'RecursionLimit\',N) to change the limit. Be aware that exceeding your available stack space can crash the program and/or your computer.')
        m.stack = stack_of(e.__traceback__)
        LASTERR[0] = m
        write(format_error(m), 'err')
        return False
    except Exception as e:
        m = as_merror(e)
        m.stack = stack_of(e.__traceback__)
        LASTERR[0] = m
        write(format_error(m), 'err')
        if getattr(m, 'internal', None):
            write(''.join(m.internal[-3:]), 'internal')
        return False


LASTERR = [None]


def format_parse_error(e, text):
    line = getattr(e, 'line', None)
    pos = getattr(e, 'pos', None)
    lines = text.split('\n')
    out = []
    if line and 0 < line <= len(lines) and pos is not None:
        start = sum(len(l) + 1 for l in lines[:line - 1])
        col = max(0, pos - start)
        src = lines[line - 1]
        out.append(' ' + src)
        out.append(' ' + ' ' * col + '↑')
    out.append('Error: ' + e.message)
    return '\n'.join(out) + '\n'


def shell_escape(cmd):
    raise MError('MATLAB:shell', 'Operating system commands are not available here.')


# ---- startup ----------------------------------------------------------------------------

BI = {}      # dotted names (containers.Map): name -> function


def setup():
    from . import builtins as BIM
    BIM.load(BUILTINS)
    B.__dict__.clear()
    BI.clear()
    from .compiler import pyname
    for name, info in BUILTINS.items():
        if '.' in name:
            BI[name] = info.fn
        else:
            setattr(B, pyname(name), info.fn)
    # what enumeration members answer (char, string, the number classes ...) in
    # front from the start: a class first loaded inside a call's arguments
    # comes after that call's function was looked up
    from . import classdef as CD
    CD._OVERRIDDEN.clear()
    for name in CD.ENUM_METHODS + CD.NUMERIC_METHODS:
        CD.install_override(name, sys.modules[__name__])
