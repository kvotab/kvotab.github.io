"""Calling Python: py.module.function(...), py.list(...) and the like, the
Python objects they give (their attributes and methods read with dots),
pyrun and pyrunfile, pyenv and pyargs.

The Python is the one PyLAB runs on (in the page, the browser's Pyodide,
with NumPy, SciPy and the modules the page has loaded). Values cross as
follows. Going in: a number or logical scalar becomes a float, int (of an
integer class), complex or bool; a vector a 1-D NumPy array and a matrix a
2-D one; [] None; char and string scalars str (string arrays and char
matrices lists of str); a cell a tuple; a struct a dict (a struct array a
list of them); a function handle a Python function that calls it; a Python
object itself. Coming back: None is [], bool logical, int int64, float
double, complex complex double, str char; anything else stays a Python
object, which double, single, the integer classes, logical, cell, char,
string and struct convert."""
import builtins as _pybuiltins
import contextlib
import importlib
import io
import os
import shlex
import sys
import types

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, is_str, darr, out
from ..values import MError, Obj, FH, Char, Cell, Struct, Str, Sparse, EMPTY, py_str, text_list, class_of
from .. import runtime as R


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, KeyError) as e:
                raise err(f'MATLAB:Python:{names[0]}', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


# ---- running Python: its printing into the Command Window, its errors as the language's ---------------------------------------------

class _Out(io.TextIOBase):
    def writable(self):
        return True

    def write(self, s):
        if s:
            R.write(s)
        return len(s)


@contextlib.contextmanager
def _running():
    o = _Out()
    try:
        with contextlib.redirect_stdout(o), contextlib.redirect_stderr(o):
            yield
    except MError:
        raise
    except SystemExit as e:
        raise MError('MATLAB:Python:SystemExit', f'Python exited (SystemExit {e.code}).')
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        raise MError('MATLAB:Python:PyException', f'Python Error: {type(e).__name__}: {e}')


# ---- values in and out ------------------------------------------------------------------------------------------------------------------

def to_py(v):
    """A value of the language as Python takes it."""
    if isinstance(v, PyObj):
        return v.obj
    if isinstance(v, PyKwargs):
        raise MError('MATLAB:Python:pyargs', 'pyargs come after the other arguments of a Python call.')
    t = type(v)
    if t in (float, bool, complex, int):
        return v
    if t is Char:
        return v.str() if v.a.shape[0] <= 1 else list(v.row_strs())
    if t is Str:
        return v.a.flat[0] if v.a.size == 1 else [x for x in v.a.reshape(-1, order='F')]
    if t is Cell:
        return tuple(to_py(x) for x in v.a.reshape(-1, order='F'))
    if t is Struct:
        if v.size == 1:
            return {k: to_py(v.get1(k)) for k in v.keys}
        return [{k: to_py(x) for k, x in v.elem(i).items()} for i in range(v.size)]
    if t is np.ndarray:
        if v.size == 0 and v.shape == (0, 0) and v.dtype == np.float64:
            return None
        if v.size == 1:
            return v.reshape(-1)[0].item()
        if v.ndim == 2 and 1 in v.shape:
            return np.array(v.reshape(-1, order='F'))
        return np.array(v)
    if t is Sparse:
        return v.m.copy()
    if isinstance(v, FH):
        return _callback(v)
    raise MError('MATLAB:Python:UnsupportedInput', f'A value of class {class_of(v)} cannot be passed to Python.')


def from_py(o):
    """A Python value as the language has it: the simple ones converted, the rest kept as Python objects."""
    if o is None:
        return EMPTY()
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, int):
        if -2 ** 63 <= o < 2 ** 63:
            return out(np.array([[o]], dtype=np.int64), 'int64')
        return PyObj.of(o)
    if isinstance(o, np.integer):
        return out(np.array([[o]]), np.dtype(type(o)).name)
    if isinstance(o, np.float32):
        return out(np.array([[o]], dtype=np.float32), 'single')
    if isinstance(o, (float, np.floating)):
        return float(o)
    if isinstance(o, (complex, np.complexfloating)):
        z = complex(o)
        return z if z.imag else complex(z.real, 0.0)
    if isinstance(o, str):
        return Char.of(o)
    return PyObj.of(o)


def _callback(f):
    """A function handle as a Python function: called with Python values, giving one back."""
    def call(*args, **kw):
        if kw:
            raise TypeError('a function handle takes no keyword arguments')
        r = f.scall(1, *[from_py(a) for a in args])
        return to_py(r) if r is not None else None
    call.__name__ = 'plab_function_handle'
    return call


def _split_args(args):
    pos, kw = [], {}
    for a in args:
        if isinstance(a, PyKwargs):
            kw.update(a.kw)
        elif kw:
            raise MError('MATLAB:Python:pyargs', 'pyargs come after the other arguments of a Python call.')
        else:
            pos.append(to_py(a))
    return pos, kw


def py_class(o):
    t = type(o)
    mod = getattr(t, '__module__', '') or ''
    if mod in ('builtins', ''):
        return 'py.' + t.__name__
    return 'py.' + mod + '.' + t.__name__


# ---- Python objects ---------------------------------------------------------------------------------------------------------------------

class PyObj(Obj):
    """A Python object: its attributes read and set with dots, items taken with (), converted as the module says."""
    is_handle = True

    def __init__(self, o):
        self.obj = o

    @staticmethod
    def of(o):
        return PyCallable(o) if callable(o) else PyObj(o)

    @property
    def cls(self):
        return py_class(self.obj)

    def getprop(self, name):
        o = self.obj
        with _running():
            try:
                v = getattr(o, name)
            except AttributeError:
                v = None
                if isinstance(o, types.ModuleType):
                    try:
                        v = importlib.import_module(f'{o.__name__}.{name}')
                    except ImportError:
                        v = None
                if v is None:
                    raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{self.cls}'.")
        return from_py(v)

    def setprop(self, name, value):
        with _running():
            setattr(self.obj, name, to_py(value))

    def propnames(self):
        return [n for n in dir(self.obj) if not n.startswith('_')]

    def index(self, args):
        """p(k) of a sequence (from 1), p(key) of a mapping."""
        o = self.obj
        if len(args) != 1:
            raise MError('MATLAB:Python:index', f'A Python {type(o).__name__} takes one index.')
        k = args[0]
        with _running():
            if is_str(k):
                return from_py(o[py_str(k)])
            i = np.asarray(darr(k)).reshape(-1)
            if i.size == 1:
                return from_py(o[int(i[0]) - 1])
            return PyObj.of(type(o)(o[int(j) - 1] for j in i) if isinstance(o, (list, tuple)) else [o[int(j) - 1] for j in i])

    def display_lines(self):
        with _running():
            text = repr(self.obj)
        lines = text.split('\n')
        if len(lines) > 30:
            lines = lines[:30] + ['...']
        lines = [ln if len(ln) <= 200 else ln[:200] + '...' for ln in lines]
        return [f'  Python {type(self.obj).__name__} with value:', ''] + ['    ' + ln for ln in lines]


class PyCallable(FH, PyObj):
    """A Python function, method or class: called as a function handle is."""

    def text(self):
        return 'py.' + getattr(self.obj, '__qualname__', type(self.obj).__name__)

    def name(self):
        return self.text()

    async def acall(self, nargout, *args):
        return self.scall(nargout, *args)

    def scall(self, nargout, *args):
        pos, kw = _split_args(args)
        with _running():
            r = self.obj(*pos, **kw)
        if nargout > 1:
            raise MError('MATLAB:TooManyOutputs', 'A Python call gives one output (a tuple stays one Python object).')
        if nargout == 0 and r is None:
            return None
        return from_py(r)


class PyKwargs(Obj):
    """pyargs('name', value, ...): keyword arguments for a Python call."""
    cls = 'pyargs'

    def __init__(self, kw):
        self.kw = kw

    def display_lines(self):
        return ['  pyargs with keywords:', ''] + [f'    {k}: {v!r}' for k, v in self.kw.items()]


def _resolve(name):
    """py.a.b.c: the module a (or Python's builtin a), then its attributes (submodules imported as needed)."""
    parts = name.split('.')[1:]
    if not parts or not all(parts):
        raise MError('MATLAB:Python:name', f"'{name}' does not name a Python module, function or value.")
    head = parts[0]
    with _running():
        if hasattr(_pybuiltins, head):
            o = getattr(_pybuiltins, head)
        else:
            try:
                o = importlib.import_module(head)
            except ImportError:
                raise MError('MATLAB:undefinedVarOrClass', f"Unable to resolve the name '{name}': Python has no module named '{head}' here.")
        for k, p in enumerate(parts[1:]):
            try:
                o = getattr(o, p)
            except AttributeError:
                sub = None
                if isinstance(o, types.ModuleType):
                    try:
                        sub = importlib.import_module(f'{o.__name__}.{p}')
                    except ImportError:
                        sub = None
                if sub is None:
                    raise MError('MATLAB:undefinedVarOrClass', f"Unable to resolve the name '{name}': '{'.'.join(parts[:k + 1])}' has no '{p}'.")
                o = sub
    return o


def py_call(name, nargout, args):
    """The runtime's call of a name starting py.: a callable is called (with no arguments when none are given),
    anything else is its value (indexed when given arguments)."""
    o = _resolve(name)
    if callable(o) and not isinstance(o, types.ModuleType):
        return PyCallable(o).scall(nargout, *args)
    v = from_py(o)
    if args:
        if not isinstance(v, PyObj):
            raise MError('MATLAB:Python:index', f"'{name}' is not a Python function.")
        return v.index(args)
    return v


R.PY_CALL[0] = py_call


# ---- pyrun, pyrunfile, pyenv, pyargs ----------------------------------------------------------------------------------------------------

PY_MAIN = {'__name__': '__main__', '__builtins__': _pybuiltins}


def _code(v, fn):
    if isinstance(v, Char):
        return v.str() if v.a.shape[0] <= 1 else '\n'.join(v.row_strs())
    if isinstance(v, (Str, Cell)):
        return '\n'.join(str(x) for x in text_list(v))
    raise err(f'MATLAB:{fn}:code', f'{fn} takes Python code as text.', fn)


def _outnames(v, fn):
    if isinstance(v, Char):
        names = [v.str()] if v.a.size else []
    elif isinstance(v, (Str, Cell)):
        names = [str(x) for x in text_list(v)]
    else:
        raise err(f'MATLAB:{fn}:outputs', f'The outputs of {fn} are named by text.', fn)
    return names


def _run_in(ns, code, filename, outs, pairs, nargout, fn):
    if len(pairs) % 2:
        raise err(f'MATLAB:{fn}:pairs', f'The inputs of {fn} come as names and values.', fn)
    for i in range(0, len(pairs), 2):
        ns[py_str(pairs[i])] = to_py(pairs[i + 1])
    with _running():
        exec(compile(code, filename, 'exec'), ns)
    if nargout > max(len(outs), 1):
        raise MError('MATLAB:TooManyOutputs', 'Too many output arguments: name an output of the Python code for each.')
    vals = []
    for n in outs[:max(nargout, 1)]:
        if n not in ns:
            raise err(f'MATLAB:{fn}:noOutput', f"The Python code made no variable '{n}'.", fn)
        vals.append(from_py(ns[n]))
    if not vals:
        return None
    return tuple(vals) if nargout > 1 else vals[0]


@bi('pyrun', nout=99)
def pyrun(nargout, *args):
    """pyrun(code), outvars = pyrun(code, outputs, Name, Value): Python code run in the session's __main__ (its variables kept from one pyrun to the next)."""
    nargchk(args, 1, 99, 'pyrun')
    code = _code(args[0], 'pyrun')
    outs = _outnames(args[1], 'pyrun') if len(args) > 1 else []
    return _run_in(PY_MAIN, code, '<pyrun>', outs, args[2:], nargout, 'pyrun')


@bi('pyrunfile', nout=99)
def pyrunfile(nargout, *args):
    """pyrunfile('file.py args'), outvars = pyrunfile(file, outputs, Name, Value): a Python file run in a namespace of its own, sys.argv set from the text after its name."""
    nargchk(args, 1, 99, 'pyrunfile')
    words = shlex.split(py_str(args[0]))
    if not words:
        raise err('MATLAB:pyrunfile:file', 'pyrunfile takes the name of a Python file.', 'pyrunfile')
    path = words[0]
    if not os.path.isabs(path):
        path = os.path.join(R.STATE.get('cwd') or os.getcwd(), path)
    if not os.path.isfile(path):
        raise err('MATLAB:pyrunfile:noFile', f"There is no file '{words[0]}'.", 'pyrunfile')
    with open(path, encoding='utf-8') as f:
        code = f.read()
    outs = _outnames(args[1], 'pyrunfile') if len(args) > 1 else []
    ns = {'__name__': '__main__', '__file__': path, '__builtins__': _pybuiltins}
    old = sys.argv
    sys.argv = [path] + words[1:]
    try:
        return _run_in(ns, code, path, outs, args[2:], nargout, 'pyrunfile')
    finally:
        sys.argv = old


class PyEnv(Obj):
    cls = 'matlab.pyclient.PythonEnvironment'
    KEYS = ('Version', 'Executable', 'Library', 'Home', 'Status', 'ExecutionMode', 'ProcessID', 'ProcessName')

    def values(self):
        browser = sys.platform == 'emscripten'
        return {'Version': f'{sys.version_info.major}.{sys.version_info.minor}', 'Executable': '' if browser else sys.executable,
                'Library': '', 'Home': sys.prefix, 'Status': 'Loaded', 'ExecutionMode': 'InProcess',
                'ProcessID': str(os.getpid()), 'ProcessName': 'Pyodide (the browser)' if browser else 'PyLAB'}

    def getprop(self, name):
        for k, v in self.values().items():
            if k.lower() == name.lower():
                return Str.of(v)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'PythonEnvironment'.")

    def propnames(self):
        return list(self.KEYS)

    def display_lines(self):
        vals = self.values()
        w = max(len(k) for k in self.KEYS)
        return ['  PythonEnvironment with properties:', ''] + [f'    {k.rjust(w)}: "{vals[k]}"' for k in self.KEYS]


@bi('pyenv')
def pyenv(nargout, *args):
    """pe = pyenv: the Python PyLAB runs on (its version, where it is, that it runs in the same process). It cannot be changed."""
    if len(args) % 2:
        raise err('MATLAB:pyenv:pairs', 'pyenv takes names and values.', 'pyenv')
    for i in range(0, len(args), 2):
        k, v = py_str(args[i]).lower(), py_str(args[i + 1])
        if k == 'executionmode' and v.lower() == 'inprocess':
            continue
        raise err('MATLAB:pyenv:fixed', f"PyLAB runs on its own Python{' (the browser’s Pyodide)' if sys.platform == 'emscripten' else ''}, in its own process: {py_str(args[i])} cannot be changed.", 'pyenv')
    return PyEnv()


@bi('pyargs')
def pyargs(nargout, *args):
    """kw = pyargs('name', value, ...): keyword arguments for a Python call, given last: py.f(x, pyargs('k', 2))."""
    if len(args) % 2:
        raise err('MATLAB:pyargs:pairs', 'pyargs takes names and values.', 'pyargs')
    return PyKwargs({py_str(args[i]): to_py(args[i + 1]) for i in range(0, len(args), 2)})


# ---- converting Python objects -----------------------------------------------------------------------------------------------------------

def _numeric(o, fn):
    with _running():
        try:
            a = np.asarray(list(o) if isinstance(o, (range, set, frozenset)) or (hasattr(o, '__iter__') and not hasattr(o, '__array__') and not isinstance(o, (list, tuple))) else o)
        except Exception:
            raise MError(f'MATLAB:Python:{fn}', f'This Python {type(o).__name__} cannot be converted with {fn}.')
    if a.dtype == object or a.dtype.kind in 'USV':
        raise MError(f'MATLAB:Python:{fn}', f'This Python {type(o).__name__} holds values that are not numbers: {fn} cannot convert it.')
    if a.ndim == 0:
        return a.reshape(1, 1)
    if a.ndim == 1:
        return a.reshape(1, -1)
    return a


def _convert(fn):
    def handler(nargout, p, *rest):
        if rest:
            raise err(f'MATLAB:{fn}:Python', f'{fn} of a Python object takes nothing more.', fn)
        o = p.obj
        if fn in ('char', 'string'):
            if fn == 'string' and isinstance(o, (list, tuple)) and all(isinstance(x, str) for x in o):
                return Str.from_list(list(o), (1, len(o)))
            with _running():
                s = str(o)
            return Char.of(s) if fn == 'char' else Str.of(s)
        if fn == 'cell':
            with _running():
                items = list(o.values() if isinstance(o, dict) else o)
            return Cell.of_list([from_py(x) for x in items], (1, len(items)))
        if fn == 'struct':
            if not hasattr(o, 'keys'):
                raise err('MATLAB:struct:Python', f'struct takes a Python dict, not a {type(o).__name__}.', fn)
            from ..index import field_name
            with _running():
                items = list(o.items())
            return Struct.scalar({field_name(str(k), 'struct'): from_py(v) for k, v in items})
        if fn == 'length':
            with _running():
                return float(len(o))
        a = _numeric(o, fn)
        if fn == 'logical':
            return out(a.astype(bool))
        if a.dtype.kind == 'c' and fn in ('double', 'single'):
            return out(a.astype(np.complex128 if fn == 'double' else np.complex64), fn)
        return out(a.astype(np.float64), fn) if fn in ('double', 'single') else out(np.asarray(a, np.float64), fn)
    return handler


def _wrap(name, handler):
    info = REG.get(name)
    if info is None:
        return
    orig = info.fn
    ws, aw = info.ws, info.aw
    if aw:
        async def f(*a):
            args = a[2:] if ws else a[1:]
            if args and isinstance(args[0], PyObj):
                return handler(a[1] if ws else a[0], *args)
            return await orig(*a)
    else:
        def f(*a):
            args = a[2:] if ws else a[1:]
            if args and isinstance(args[0], PyObj):
                return handler(a[1] if ws else a[0], *args)
            return orig(*a)
    info.fn = f


for _n in ('double', 'single', 'logical', 'int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32', 'uint64', 'cell', 'char', 'string', 'struct', 'length'):
    _wrap(_n, _convert(_n))
