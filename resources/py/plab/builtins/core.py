"""The language's own functions: output, errors, classes, sizes, the
workspace, eval and feval, timing and the format command."""
import math
import re
import sys
import time

import numpy as np

from . import bi
from ._util import (err, nargchk, noout, maxout, arr, darr, out, opt_str, sval, ival, num, is_str, bool_out,
                    NUMERIC_CLASSES)
from .fmt import sprintf as _sprintf, unescape
from ..values import (MError, NOVAL, Char, Cell, Struct, Str, FH, Obj, F64, C128, INT_TYPES, DTYPE_CLASS,
                      class_of, shape_of, numel, py_str, share, share_all, EMPTY, is_numeric, is_real, size_str,
                      to_float, Interrupt)
from .. import display as D
from .. import runtime as R


def _text(v, fn):
    t = type(v)
    if t is Char:
        return v.str()
    if t is Str and v.a.size == 1:
        s = v.a.flat[0]
        return '' if s is None else s
    raise err('MATLAB:invalidType', 'The format must be a character vector or string scalar.' if fn in ('sprintf', 'fprintf') else 'Expected text.', fn)


# ---- output -------------------------------------------------------------------------

@bi('disp')
def disp(nargout, *args):
    nargchk(args, 1, 1, 'disp')
    noout(nargout, 'disp')
    R.write(D.disp_text(args[0]))
    return None


@bi('display', ws=True)
def display_(W, nargout, *args):
    nargchk(args, 1, 2, 'display')
    name = py_str(args[1]) if len(args) > 1 else 'ans'
    R.write(D.display(name, args[0]))
    return None


@bi('sprintf')
def sprintf(nargout, *args):
    nargchk(args, 1, None, 'sprintf')
    fmt = args[0]
    if type(fmt) is Str and fmt.a.size == 1:
        s = _sprintf(_text(fmt, 'sprintf'), args[1:])
        return Str.of(s)
    s = _sprintf(_text(fmt, 'sprintf'), args[1:])
    if nargout > 1:
        return (Char.of(s), Char.of(''))
    return Char.of(s)


@bi('fprintf')
def fprintf(nargout, *args):
    nargchk(args, 1, None, 'fprintf')
    fid = 1
    if not is_str(args[0]):
        if type(args[0]) in (float, np.ndarray, bool) and numel(args[0]) == 1 and len(args) >= 2:
            fid = int(num(args[0]))
            args = args[1:]
        elif len(args) == 1:
            # fprintf(x) with a number: written as %f? the language prints it with %s rules
            s = _sprintf('%s', args)
            R.write(s)
            return float(len(s)) if nargout else None
    s = _sprintf(_text(args[0], 'fprintf'), args[1:])
    if fid == 1:
        R.write(s)
    elif fid == 2:
        R.write(s, 'err')
    else:
        from .iofun import file_write_text
        file_write_text(fid, s)
    if nargout:
        return float(len(s.encode('utf-8')))
    return None


@bi('newline')
def newline(nargout, *args):
    nargchk(args, 0, 0, 'newline')
    return Char.of('\n')


# ---- errors and warnings ---------------------------------------------------------------

_ID_RE = re.compile(r'^[A-Za-z][\w-]*(:[\w-]+)+$')


def _message(args, fn):
    """(identifier, message) from error/warning arguments."""
    if not args:
        return '', ''
    if len(args) == 1:
        a = args[0]
        if type(a) is Struct:
            msg = py_str(a.f['message'].item(0)) if 'message' in a.f else ''
            ident = py_str(a.f['identifier'].item(0)) if 'identifier' in a.f else ''
            return ident, msg
        return '', _text(a, fn)
    first = _text(args[0], fn)
    if _ID_RE.match(first) and not any(c in first for c in ' %\\'):
        fmt = _text(args[1], fn)
        return first, _sprintf(fmt, args[2:])
    return '', _sprintf(first, args[1:])


@bi('error')
def error(nargout, *args):
    nargchk(args, 1, None, 'error')
    if len(args) == 1 and type(args[0]) is Struct and args[0].size == 0:
        return None
    ident, msg = _message(args, 'error')
    if len(args) == 1 and type(args[0]) in (Char, Str):
        # one argument is the message as written, escapes and all
        msg = _text(args[0], 'error')
    if not msg and len(args) == 1:
        return None
    e = MError(ident, msg)
    e.from_error_fn = True
    raise e


@bi('warning', ws=True)
def warning(W, nargout, *args):
    if not args:
        return None
    first = opt_str(args[0])
    if first is not None and first.lower() in ('on', 'off', 'query'):
        state = first.lower()
        ident = opt_str(args[1]) if len(args) > 1 else 'all'
        if state != 'query':
            if ident == 'all':
                R.WARN_STATE.clear()
            R.WARN_STATE[ident] = state
        return None
    if first is not None and first.lower() in ('backtrace', 'verbose'):
        return None
    ident, msg = _message(args, 'warning')
    if len(args) == 1:
        msg = _text(args[0], 'warning')
    R.warn(ident, msg)
    return None


@bi('lastwarn', nout=2)
def lastwarn(nargout, *args):
    msg, ident = R.LASTWARN[0]
    if args:
        R.LASTWARN[0] = (_text(args[0], 'lastwarn'), _text(args[1], 'lastwarn') if len(args) > 1 else '')
    if nargout > 1:
        return Char.of(msg), Char.of(ident)
    return Char.of(msg)


@bi('lasterr', nout=2)
def lasterr(nargout, *args):
    e = R.LASTERR[0]
    msg = e.message if e else ''
    ident = e.identifier if e else ''
    if nargout > 1:
        return Char.of(msg), Char.of(ident)
    return Char.of(msg)


@bi('MException')
def mexception(nargout, *args):
    nargchk(args, 2, None, 'MException')
    ident = _text(args[0], 'MException')
    msg = _sprintf(_text(args[1], 'MException'), args[2:])
    return R.MExc(MError(ident, msg))


@bi('throw', 'throwAsCaller')
def throw(nargout, *args):
    nargchk(args, 1, 1, 'throw')
    e = args[0]
    if not isinstance(e, R.MExc):
        raise err('MATLAB:invalidType', 'Input must be an MException object.', 'throw')
    m = MError(e.err.identifier, e.err.message, e.err.cause)
    m.from_error_fn = True
    raise m


@bi('rethrow')
def rethrow(nargout, *args):
    nargchk(args, 1, 1, 'rethrow')
    e = args[0]
    if isinstance(e, R.MExc):
        raise e.err
    if type(e) is Struct:
        ident, msg = _message([e], 'rethrow')
        raise MError(ident, msg)
    raise err('MATLAB:invalidType', 'Input must be an MException object or a struct.', 'rethrow')


@bi('getReport')
def getreport(nargout, *args):
    e = args[0]
    if not isinstance(e, R.MExc):
        raise err('MATLAB:invalidType', 'Input must be an MException object.', 'getReport')
    text = R.format_error(e.err).rstrip('\n')
    text = re.sub('\x01[^\x02]*\x02', '', text).replace('\x03', '')
    return Char.of(text)


@bi('addCause')
def addcause(nargout, *args):
    e, c = args
    e.err.cause.append(c.err)
    return e


@bi('assert')
def assert_(nargout, *args):
    nargchk(args, 1, None, 'assert')
    c = args[0]
    ok = R.truth(c) if numel(c) > 0 else False
    if not ok:
        if len(args) == 1:
            raise err('MATLAB:assertion:failed', 'Assertion failed.')
        ident, msg = _message(args[1:], 'assert')
        e = MError(ident or 'MATLAB:assertion:failed', msg)
        raise e
    return None


@bi('narginchk', ws=True)
def narginchk(W, nargout, *args):
    lo, hi = num(args[0]), num(args[1])
    n = W.nargs[0]
    if n < lo:
        raise err('MATLAB:narginchk:notEnoughInputs', 'Not enough input arguments.')
    if n > hi:
        raise err('MATLAB:narginchk:tooManyInputs', 'Too many input arguments.')
    return None


@bi('nargoutchk', ws=True)
def nargoutchk(W, nargout, *args):
    lo, hi = num(args[0]), num(args[1])
    n = W.nargs[1]
    if n < lo:
        raise err('MATLAB:nargoutchk:notEnoughOutputs', 'Not enough output arguments.')
    if n > hi:
        raise err('MATLAB:nargoutchk:tooManyOutputs', 'Too many output arguments.')
    return None


@bi('nargin', 'nargout', ws=True)
def nargin_fn(W, nargout, *args):
    if not args:
        n = W.nargs
        if n[0] < 0:
            raise err('MATLAB:nargin:isScript', 'You can only call nargin/nargout from within a MATLAB function.')
        return float(n[0])
    f = args[0]
    name = f.fname if isinstance(f, R.NamedFH) else py_str(f) if is_str(f) else None
    if isinstance(f, R.Anon):
        return float(-(f.nparams + 1) if f.vararg else f.nparams)
    if name is None:
        raise err('MATLAB:nargin:invalidInput', 'Input must be a function name or handle.')
    p = R.find_file(name)
    if p is None:
        raise err('MATLAB:nargin:isBuiltin', f'"{name}" is a built-in function: its number of inputs is not fixed.')
    mod = R.load_file(p)
    fdef = mod.prog.funcs[0] if mod.prog.funcs else None
    if fdef is None:
        raise err('MATLAB:nargin:isScript', f'"{name}" is a script.')
    ps = fdef.params
    return float(-len(ps) if ps and ps[-1] == 'varargin' else len(ps))


# ---- classes and tests --------------------------------------------------------------

@bi('class')
def class_(nargout, *args):
    nargchk(args, 1, 1, 'class')
    return Char.of(class_of(args[0]))


_ISA_GROUPS = {
    'numeric': lambda c: c in ('double', 'single') or c in INT_TYPES,
    'float': lambda c: c in ('double', 'single'),
    'integer': lambda c: c in INT_TYPES,
}


@bi('isa')
def isa(nargout, *args):
    nargchk(args, 2, 2, 'isa')
    c = class_of(args[0])
    name = sval(args[1], 'class name', 'isa')
    g = _ISA_GROUPS.get(name)
    if g is not None:
        return g(c)
    if c == name:
        return True
    v = args[0]
    if isinstance(v, Obj):
        return name in getattr(v, 'superclasses', ())
    return False


def _pred(name, fn):
    def f(nargout, *args):
        nargchk(args, 1, 1, name)
        return fn(args[0])
    f.__name__ = name
    bi(name)(f)


_pred('isnumeric', lambda v: is_numeric(v))
_pred('isreal', lambda v: is_real(v) if (is_numeric(v) or type(v) in (bool, Char) or (type(v) is np.ndarray)) else not isinstance(v, (Cell, Struct)) and type(v) is not Str and False or type(v) in (Char, bool) or (type(v) is np.ndarray and v.dtype.kind != 'c'))
_pred('isfloat', lambda v: class_of(v) in ('double', 'single'))
_pred('isinteger', lambda v: class_of(v) in INT_TYPES)
_pred('islogical', lambda v: class_of(v) == 'logical')
_pred('ischar', lambda v: type(v) is Char)
_pred('iscell', lambda v: type(v) is Cell)
_pred('isstruct', lambda v: type(v) is Struct)
_pred('isstring', lambda v: type(v) is Str)
_pred('istext', lambda v: type(v) in (Char, Str))
_pred('isobject', lambda v: isinstance(v, Obj) and not getattr(v, 'is_graphics', False))
_pred('isempty', lambda v: numel(v) == 0)
_pred('isscalar', lambda v: numel(v) == 1 and len(shape_of(v)) == 2)
_pred('ismatrix', lambda v: len(shape_of(v)) == 2)
_pred('isvector', lambda v: len(shape_of(v)) == 2 and (shape_of(v)[0] == 1 or shape_of(v)[1] == 1) and numel(v) >= 1)
_pred('isrow', lambda v: len(shape_of(v)) == 2 and shape_of(v)[0] == 1)
_pred('iscolumn', lambda v: len(shape_of(v)) == 2 and shape_of(v)[1] == 1)
_pred('issquare', lambda v: len(shape_of(v)) == 2 and shape_of(v)[0] == shape_of(v)[1])
_pred('iscellstr', lambda v: type(v) is Cell and all(type(x) is Char and (x.a.ndim == 2 and x.a.shape[0] <= 1) for x in v.a.flat))
_pred('issparse', lambda v: getattr(v, 'is_sparse', False))
_pred('isdiag', lambda v: bool(np.all(np.diag(np.diag(arr(v))) == arr(v))) if arr(v).ndim == 2 else False)


@bi('isreal')
def isreal(nargout, *args):
    nargchk(args, 1, 1, 'isreal')
    v = args[0]
    t = type(v)
    if t is complex:
        return False
    if t is np.ndarray:
        return v.dtype.kind != 'c'
    if t in (Cell, Struct, Str) or isinstance(v, (FH, Obj)):
        return False
    return True


@bi('isequal', 'isequaln')
def isequal(nargout, *args):
    nargchk(args, 2, None, 'isequal')
    nan_eq = False
    a = args[0]
    for b in args[1:]:
        if not _equal(a, b, nan_eq):
            return False
    return True


@bi('isequaln')
def isequaln(nargout, *args):
    nargchk(args, 2, None, 'isequaln')
    a = args[0]
    for b in args[1:]:
        if not _equal(a, b, True):
            return False
    return True


def _equal(a, b, nan_eq):
    ta, tb = type(a), type(b)
    if shape_of(a) != shape_of(b):
        return False
    num_like = (float, bool, complex, np.ndarray, Char, int)
    if ta in num_like and tb in num_like:
        A = arr(a)
        B = arr(b)
        if A.dtype.kind == 'O' or B.dtype.kind == 'O':
            return False
        with np.errstate(invalid='ignore'):
            eq = A == B
            if nan_eq:
                both = np.isnan(A.astype(C128) if A.dtype.kind == 'c' else A.astype(float)) & np.isnan(B.astype(C128) if B.dtype.kind == 'c' else B.astype(float))
                eq = eq | both
        return bool(np.all(eq))
    if ta is Str and tb in (Str, Char) or tb is Str and ta in (Str, Char):
        from ..strings import to_str_array
        A, B = to_str_array(a), to_str_array(b)
        return A.a.shape == B.a.shape and all(x == y for x, y in zip(A.a.flat, B.a.flat))
    if ta is Cell and tb is Cell:
        return all(_equal(x, y, nan_eq) for x, y in zip(a.a.flat, b.a.flat))
    if ta is Struct and tb is Struct:
        if set(a.f) != set(b.f):
            return False
        for k in a.f:
            for x, y in zip(a.f[k].flat, b.f[k].flat):
                if not _equal(x, y, nan_eq):
                    return False
        return True
    if isinstance(a, FH) and isinstance(b, FH):
        return a is b or (isinstance(a, R.NamedFH) and isinstance(b, R.NamedFH) and a.fname == b.fname)
    if isinstance(a, Obj) and isinstance(b, Obj):
        return a is b or (hasattr(a, 'equals') and a.equals(b))
    return False


# ---- sizes -------------------------------------------------------------------------------

@bi('size', nout=99)
def size(nargout, *args):
    nargchk(args, 1, None, 'size')
    sh = shape_of(args[0])
    if len(args) >= 2:
        dims = []
        for d in args[1:]:
            a = arr(d)
            for x in a.reshape(-1):
                k = int(x)
                if k < 1:
                    raise err('MATLAB:getdimarg:dimensionMustBePositiveInteger', 'Dimension argument must be a positive integer scalar or a vector of positive integers.', 'size')
                dims.append(float(sh[k - 1]) if k <= len(sh) else 1.0)
        if nargout <= 1:
            return dims[0] if len(dims) == 1 else np.array([dims])
        return tuple(dims)
    if nargout <= 1:
        return np.array([[float(d) for d in sh]])
    vals = [float(d) for d in sh[:nargout - 1]]
    while len(vals) < nargout - 1:
        vals.append(1.0)
    rest = 1
    for d in sh[nargout - 1:]:
        rest *= d
    vals.append(float(rest))
    return tuple(vals)


@bi('numel')
def numel_(nargout, *args):
    nargchk(args, 1, None, 'numel')
    return float(numel(args[0]))


@bi('length')
def length(nargout, *args):
    nargchk(args, 1, 1, 'length')
    sh = shape_of(args[0])
    return 0.0 if 0 in sh else float(max(sh))


@bi('ndims')
def ndims(nargout, *args):
    nargchk(args, 1, 1, 'ndims')
    return float(len(shape_of(args[0])))


@bi('isvarname')
def isvarname(nargout, *args):
    s = args[0]
    if not is_str(s):
        return False
    from ..lexer import KEYWORDS
    t = py_str(s)
    return bool(re.fullmatch(r'[A-Za-z]\w{0,62}', t)) and t not in KEYWORDS


@bi('iskeyword')
def iskeyword(nargout, *args):
    from ..lexer import KEYWORDS
    if not args:
        return Cell.of_list([Char.of(k) for k in sorted(KEYWORDS)], (len(KEYWORDS), 1))
    return py_str(args[0]) in KEYWORDS


@bi('matlab.lang.makeValidName', 'genvarname')
def makevalidname(nargout, *args):
    s = py_str(args[0])
    s = re.sub(r'\W', '_', s)
    if not s or not s[0].isalpha():
        s = 'x' + s
    return Char.of(s)


# ---- the workspace -------------------------------------------------------------------

def _caller_ws(depth=1):
    """The workspace of the compiled function `depth` calls up from the one
    running a builtin (0: the one that called the builtin)."""
    f = sys._getframe(1)
    seen = 0
    while f is not None:
        if f.f_code.co_filename.startswith('<plab:') and 'W' in f.f_locals:
            W = f.f_locals['W']
            if isinstance(W, R.Workspace) and W.fname != '@':
                if seen == depth:
                    return W
                seen += 1
        f = f.f_back
    return R.BASE


@bi('exist', ws=True)
def exist(W, nargout, *args):
    nargchk(args, 1, 2, 'exist')
    name = sval(args[0], 'name', 'exist')
    kind = opt_str(args[1]).lower() if len(args) > 1 else None
    import os
    if kind in (None, 'var'):
        if name in W or name in getattr(W, 'gnames', ()):
            return 1.0
        if kind == 'var':
            return 0.0
    if kind in (None, 'file'):
        if R.find_file(name):
            return 2.0
        p = _abs_path(name)
        if os.path.isfile(p):
            return 2.0
        if kind is None and os.path.isdir(p):
            return 7.0
    if kind in (None, 'builtin'):
        if name in R.BUILTINS:
            return 5.0
    if kind in ('dir',):
        return 7.0 if os.path.isdir(_abs_path(name)) else 0.0
    if kind == 'file' and os.path.isdir(_abs_path(name)):
        return 7.0
    return 0.0


def _abs_path(p):
    import os
    if os.path.isabs(p):
        return p
    return os.path.normpath(os.path.join(R.STATE['cwd'], p))


@bi('clear', 'clearvars', ws=True)
def clear(W, nargout, *args):
    noout(nargout, 'clear')
    names = [sval(a, 'name', 'clear') for a in args]
    if not names:
        W.clear()
        W.gnames.clear()
        return None
    import fnmatch
    if names[0] in ('all', '-all'):
        W.clear()
        W.gnames.clear()
        R.GLOBALS.clear()
        R.PERSISTENT.clear()
        R.bump_epoch()
        return None
    if names[0] in ('functions', '-functions', 'classes', '-classes', 'import', 'mex'):
        R.PERSISTENT.clear()
        R.bump_epoch()
        return None
    if names[0] in ('global', '-global'):
        targets = names[1:] or list(R.GLOBALS)
        for n in targets:
            for k in fnmatch.filter(list(R.GLOBALS), n):
                R.GLOBALS.pop(k, None)
                W.gnames.discard(k)
        return None
    if names[0] in ('variables', '-variables', 'vars'):
        names = names[1:]
        if not names:
            W.clear()
            return None
    if names[0] == '-except':
        keep = set()
        for n in names[1:]:
            keep.update(fnmatch.filter(list(W), n))
        for k in list(W):
            if k not in keep:
                del W[k]
        return None
    if names[0] == '-regexp':
        for pat in names[1:]:
            for k in list(W):
                if re.match(pat, k):
                    del W[k]
        return None
    if '-except' in names:
        i = names.index('-except')
        keep = set()
        for n in names[i + 1:]:
            keep.update(fnmatch.filter(list(W), n))
        for n in names[:i]:
            for k in fnmatch.filter(list(W), n):
                if k not in keep:
                    del W[k]
        return None
    for n in names:
        if any(c in n for c in '*?['):
            for k in fnmatch.filter(list(W), n):
                del W[k]
        else:
            W.pop(n, None)
            if n in W.gnames:
                W.gnames.discard(n)
    return None


@bi('who', ws=True)
def who(W, nargout, *args):
    names = sorted(W.keys(), key=lambda s: (s.lower(), s))
    if args:
        import fnmatch
        pats = [sval(a, 'name', 'who') for a in args]
        names = [n for n in names if any(fnmatch.fnmatch(n, p) for p in pats)]
    if nargout:
        return Cell.of_list([Char.of(n) for n in names], (len(names), 1))
    if not names:
        return None
    lines = ['', 'Your variables are:', '']
    row = ''
    for n in names:
        row += n + '  '
    lines.append(row)
    lines.append('')
    R.write('\n'.join(lines) + '\n')
    return None


def _bytes(v):
    t = type(v)
    if t is float:
        return 8
    if t is bool:
        return 1
    if t is complex:
        return 16
    if t is np.ndarray:
        return int(v.nbytes)
    if t is Char:
        return int(v.a.size * 2)
    if t is Cell:
        return int(sum(_bytes(x) + 104 for x in v.a.flat))
    if t is Struct:
        return int(sum(_bytes(x) + 104 for a in v.f.values() for x in a.flat) + 64 * len(v.f))
    if t is Str:
        return int(sum(len(s or '') * 2 + 104 for s in v.a.flat))
    return 8


@bi('whos', ws=True)
def whos(W, nargout, *args):
    names = sorted(W.keys(), key=lambda s: (s.lower(), s))
    if args:
        import fnmatch
        pats = [sval(a, 'name', 'whos') for a in args]
        names = [n for n in names if any(fnmatch.fnmatch(n, p) for p in pats)]
    rows = []
    for n in names:
        v = W[n]
        sz = 'x'.join(str(d) for d in shape_of(v))
        attrs = []
        if n in W.gnames:
            attrs.append('global')
        if type(v) is complex or (type(v) is np.ndarray and v.dtype.kind == 'c'):
            attrs.append('complex')
        rows.append((n, sz, _bytes(v), class_of(v), ', '.join(attrs)))
    if nargout:
        s = Struct((len(rows), 1), {k: np.empty((len(rows), 1), object) for k in ('name', 'size', 'bytes', 'class', 'global', 'sparse', 'complex', 'nesting', 'persistent')})
        for i, (n, sz, b, c, at) in enumerate(rows):
            s.f['name'][i, 0] = Char.of(n)
            s.f['size'][i, 0] = np.array([[float(d) for d in shape_of(W[n])]])
            s.f['bytes'][i, 0] = float(b)
            s.f['class'][i, 0] = Char.of(c)
            s.f['global'][i, 0] = 'global' in at
            s.f['sparse'][i, 0] = False
            s.f['complex'][i, 0] = 'complex' in at
            s.f['nesting'][i, 0] = Struct.scalar({'function': Char.of(''), 'level': 1.0})
            s.f['persistent'][i, 0] = False
        return s
    if not rows:
        return None
    wn = max(4, max(len(r[0]) for r in rows))
    lines = [f"  {'Name'.ljust(wn)}      {'Size'.ljust(16)}{'Bytes'.rjust(5)}  {'Class'.ljust(10)}Attributes", '']
    for n, sz, b, c, at in rows:
        lines.append(f"  {n.ljust(wn)}      {sz.ljust(16)}{str(b).rjust(5)}  {c.ljust(10)}{at}")
    lines.append('')
    R.write('\n'.join(lines) + '\n')
    return None


@bi('assignin', ws=True)
def assignin(W, nargout, *args):
    nargchk(args, 3, 3, 'assignin')
    where = sval(args[0], 'workspace', 'assignin')
    name = sval(args[1], 'variable name', 'assignin')
    if not re.fullmatch(r'[A-Za-z]\w*', name):
        raise err('MATLAB:assigninInvalidVariable', f'Invalid variable name "{name}" in ASSIGNIN.', 'assignin')
    target = R.BASE if where == 'base' else _caller_ws(1)
    target[name] = share(args[2])
    return None


@bi('evalin', ws=True, aw=True, nout=99, arr=False)
async def evalin(W, nargout, *args):
    nargchk(args, 2, 3, 'evalin')
    where = sval(args[0], 'workspace', 'evalin')
    target = R.BASE if where == 'base' else _caller_ws(1)
    return await _eval_in(target, sval(args[1], 'expression', 'evalin'), sval(args[2], 'expression', 'evalin') if len(args) > 2 else None, nargout)


@bi('eval', ws=True, aw=True, nout=99, arr=False)
async def eval_(W, nargout, *args):
    nargchk(args, 1, 2, 'eval')
    return await _eval_in(W, sval(args[0], 'expression', 'eval'), sval(args[1], 'expression', 'eval') if len(args) > 1 else None, nargout)


async def _eval_in(W, text, catch_text, nargout):
    if nargout > 0:
        # an expression whose value is wanted
        try:
            fn, mod = R.compile_command('plabTmpEval = ' + text.strip().rstrip(';') + ';' if nargout == 1 else f"[{', '.join(f'plabTmpEval{i}' for i in range(nargout))}] = {text.strip().rstrip(';')};", W)
            await fn(W)
            if nargout == 1:
                return W.pop('plabTmpEval')
            return tuple(W.pop(f'plabTmpEval{i}') for i in range(nargout))
        except MError:
            if catch_text is None:
                raise
            return await _eval_in(W, catch_text, None, nargout)
    try:
        fn, mod = R.compile_command(text, W)
        await fn(W)
    except MError as e:
        if catch_text is None:
            raise
        R.LASTERR[0] = e
        fn, mod = R.compile_command(catch_text, W)
        await fn(W)
    return None


@bi('evalc', ws=True, aw=True, arr=False)
async def evalc(W, nargout, *args):
    nargchk(args, 1, 2, 'evalc')
    saved = list(R._out)
    hook = R.OUT_HOOK[0]
    R.flush()
    R._out.clear()
    R.OUT_HOOK[0] = None
    try:
        await _eval_in(W, sval(args[0], 'expression', 'evalc'), sval(args[1], 'expression', 'evalc') if len(args) > 1 else None, 0)
        text = R.take_output()
    finally:
        R.OUT_HOOK[0] = hook
    return Char.of(text)


@bi('feval', ws=True, aw=True, nout=99, arr=False)
async def feval(W, nargout, *args):
    nargchk(args, 1, None, 'feval')
    f = args[0]
    if isinstance(f, FH):
        return await f.acall(nargout, *args[1:])
    name = sval(f, 'function name', 'feval')
    return await R.call(None, name, nargout, args[1:])


@bi('builtin', ws=True, aw=True, nout=99, arr=False)
async def builtin_(W, nargout, *args):
    name = sval(args[0], 'function name', 'builtin')
    info = R.BUILTINS.get(name)
    if info is None:
        raise err('MATLAB:UndefinedFunction', f"Unrecognized function or variable '{name}'.")
    r = info.fn(W, nargout, *args[1:]) if info.ws else info.fn(nargout, *args[1:])
    if info.aw:
        r = await r
    return r


@bi('func2str')
def func2str(nargout, *args):
    nargchk(args, 1, 1, 'func2str')
    f = args[0]
    if not isinstance(f, FH):
        raise err('MATLAB:func2str:InputNotFunctionHandle', 'Input must be a function handle.', 'func2str')
    t = f.text()
    return Char.of(t[1:] if isinstance(f, R.NamedFH) else t)


def anon_from_text(s, captured=None):
    """An anonymous function from its text, capturing the values given by
    name (as when it was made where they were variables)."""
    from ..compiler import compile_source
    from .. import parser as P
    ws = R.Workspace('str2func')
    for k, v in (captured or {}).items():
        ws[k] = v
    src, linemap, prog = compile_source('plabTmpFn = ' + s + ';', R.BUILTINS, kind='command', user_funcs=R._user_file,
                                        ws_names=tuple(ws))
    # the text is run as an assignment: it must be one anonymous function, and nothing after it
    if len(prog.body) != 1 or type(prog.body[0]) is not P.Assign or type(prog.body[0].rhs) is not P.Anon or prog.funcs:
        raise err('MATLAB:str2func:invalidFunctionName', f'Invalid anonymous function: {s}', 'str2func')
    R._cmd_n[0] += 1
    pyfile = f'<plab:str2func#{R._cmd_n[0]}>'
    code = compile(src, pyfile, 'exec')
    ns = R.make_ns('command')
    exec(code, ns)
    R.MODULES[pyfile] = R.CompiledModule('command', 'str2func', s, src, linemap, 'command', ns)
    R.run_sync(ns['SCRIPT'](ws))
    return ws['plabTmpFn']


@bi('str2func', ws=True, arr=False)
def str2func(W, nargout, *args):
    nargchk(args, 1, 2, 'str2func')
    s = sval(args[0], 'function name', 'str2func').strip()
    if s.startswith('@'):
        return anon_from_text(s)
    return R.NamedFH(s)


@bi('functions')
def functions(nargout, *args):
    f = args[0]
    if isinstance(f, R.Anon):
        return Struct.scalar({'function': Char.of(f.text()), 'type': Char.of('anonymous'), 'file': Char.of(''),
                              'workspace': Cell.of_list([Struct.scalar(dict(f.cap))])})
    return Struct.scalar({'function': Char.of(f.fname), 'type': Char.of('simple'), 'file': Char.of(R.find_file(f.fname) or '')})


@bi('deal', nout=99, arr=False)
def deal(nargout, *args):
    n = max(nargout, 1)
    if len(args) == 1:
        v = share(args[0])
        return v if n == 1 else tuple(v for _ in range(n))
    if len(args) != n:
        raise err('MATLAB:deal:narginNargoutMismatch', 'The number of outputs should match the number of inputs.', 'deal')
    return args[0] if n == 1 else tuple(args)


# ---- timing and the session -------------------------------------------------------------

_TIC = [None]


@bi('tic')
def tic(nargout, *args):
    t = time.perf_counter()
    if nargout:
        return np.array([[int(t * 1e6)]], np.uint64)
    _TIC[0] = t
    return None


@bi('toc')
def toc(nargout, *args):
    if args:
        t0 = int(arr(args[0]).reshape(-1)[0]) / 1e6
    else:
        if _TIC[0] is None:
            raise err('MATLAB:toc:callTicFirst', 'You must call TIC without an output argument before calling TOC without an input argument.', 'toc')
        t0 = _TIC[0]
    e = time.perf_counter() - t0
    if nargout:
        return e
    R.write(f'Elapsed time is {e:.6f} seconds.\n')
    return None


@bi('cputime')
def cputime(nargout, *args):
    return time.process_time()


@bi('format')
def format_(nargout, *args):
    noout(nargout, 'format')
    if not args:
        D.FMT['mode'] = 'short'
        D.FMT['spacing'] = 'loose'
        return None
    words = [sval(a, 'format', 'format') for a in args]
    for w in words:
        lw = w.lower()
        if lw in ('compact', 'loose'):
            D.FMT['spacing'] = lw
        elif lw in ('short', 'long', 'shorte', 'longe', 'shortg', 'longg', 'bank', 'rat', 'hex', '+', 'shorteng', 'longeng'):
            D.FMT['mode'] = {'shorte': 'shortE', 'longe': 'longE', 'shortg': 'shortG', 'longg': 'longG',
                             'shorteng': 'shortE', 'longeng': 'longE'}.get(lw, lw)
        elif lw in ('e', 'g') and words and words[0].lower() in ('short', 'long'):
            D.FMT['mode'] = words[0].lower() + lw.upper()
        elif lw == 'default':
            D.FMT['mode'] = 'short'
            D.FMT['spacing'] = 'loose'
        else:
            raise err('MATLAB:format:UnknownFormat', f"Unknown format '{w}'.", 'format')
    return None


@bi('clc')
def clc(nargout, *args):
    noout(nargout, 'clc')
    R.flush()
    R._out.clear()
    if R.EVENT_HOOK[0]:
        R.EVENT_HOOK[0]({'type': 'clc'})
    return None


@bi('more', 'echo', 'diary', 'profile')
def ignored(nargout, *args):
    return None


@bi('input', aw=True, arr=False)
async def input_(nargout, *args):
    nargchk(args, 0, 2, 'input')
    prompt = _text(args[0], 'input') if args else ''
    as_text = len(args) > 1 and opt_str(args[1]) == 's'
    R.flush()
    while True:
        reply = await R.ask_input(unescape(prompt) if '\\' in prompt else prompt)
        if as_text:
            return Char.of(reply)
        if not reply.strip():
            return EMPTY()
        try:
            W = R.Workspace('input')
            W.update(R.BASE)
            fn, mod = R.compile_command('plabTmpInput = ' + reply + ';', W)
            await fn(W)
            return W['plabTmpInput']
        except MError as e:
            R.write(R.format_error(e), 'err')


@bi('keyboard', ws=True, aw=True)
async def keyboard(W, nargout, *args):
    await R.DEBUGGER.keyboard(W)
    return None


@bi('pause', aw=True)
async def pause(nargout, *args):
    if args:
        s = opt_str(args[0])
        if s is not None:
            return None
        t = num(args[0])
        if t != t or t <= 0:
            return None
        await R.sleep(t)
        return None
    R.flush()
    await R.ask_input('', 'key')
    return None


@bi('exit', 'quit')
def quit_(nargout, *args):
    raise err('MATLAB:quit', 'This page cannot be closed by a command: close the browser tab.')


@bi('help', arr=False)
def help_(nargout, *args):
    """help NAME in a program (typed at the prompt, the page answers it):
    the help printed, or with an output given back as text."""
    from ..help import help_for
    nargchk(args, 0, 1, 'help')
    h = help_for(sval(args[0], 'name', 'help') if args else '')
    if nargout:
        return Char.of('' if h['kind'] == 'missing' else h['text'])
    R.write(h['text'] if h['text'].endswith('\n') else h['text'] + '\n')
    return None


@bi('version')
def version(nargout, *args):
    return Char.of('PyLAB (MATLAB-language interpreter on Python)')


@bi('ver')
def ver(nargout, *args):
    import numpy, platform
    try:
        import scipy
        sv = scipy.__version__
    except Exception:
        sv = 'not loaded'
    R.write('-' * 74 + '\n')
    R.write(f'PyLAB, a MATLAB-language interpreter running on Python {platform.python_version()}\n')
    R.write(f'NumPy {numpy.__version__}, SciPy {sv}\n')
    R.write('-' * 74 + '\n')
    return None


@bi('computer')
def computer(nargout, *args):
    return Char.of('PYODIDE')


@bi('ispc')
def ispc(nargout, *args):
    return False


@bi('isunix')
def isunix(nargout, *args):
    return True


@bi('ismac')
def ismac(nargout, *args):
    return False


@bi('isdeployed')
def isdeployed(nargout, *args):
    return False


@bi('usejava')
def usejava(nargout, *args):
    return False


@bi('getenv')
def getenv(nargout, *args):
    import os
    return Char.of(os.environ.get(py_str(args[0]), ''))


@bi('setenv')
def setenv(nargout, *args):
    import os
    os.environ[py_str(args[0])] = py_str(args[1]) if len(args) > 1 else ''
    return None


@bi('inputname')
def inputname(nargout, *args):
    return Char.of('')


@bi('mfilename')
def mfilename(nargout, *args):
    """The name of the file whose code calls it (with 'fullpath', its path
    without .m); '' for a line typed in the Command Window."""
    import os
    nargchk(args, 0, 1, 'mfilename')
    opt = sval(args[0], 'option', 'mfilename').lower() if args else ''
    if opt not in ('', 'fullpath', 'class'):
        raise err('MATLAB:mfilename:InvalidInput', "The option must be 'fullpath' or 'class'.", 'mfilename')
    f = sys._getframe(1)
    while f is not None:
        mod = R.MODULES.get(f.f_code.co_filename)
        if mod is not None:
            if mod.path == 'command' or opt == 'class':
                return Char.of('')
            return Char.of(os.path.splitext(mod.path)[0] if opt == 'fullpath' else mod.name)
        f = f.f_back
    return Char.of('')


@bi('validateattributes')
def validateattributes(nargout, *args):
    nargchk(args, 3, None, 'validateattributes')
    v = args[0]
    classes = [py_str(x) for x in args[1].a.flat] if type(args[1]) is Cell else []
    if classes:
        c = class_of(v)
        ok = any(c == k or (k == 'numeric' and is_numeric(v)) or (k == 'float' and c in ('double', 'single')) for k in classes)
        if not ok:
            raise err('MATLAB:invalidType', f"Expected input to be one of these types:\n\n{', '.join(classes)}\n\nInstead its type was {c}.")
    attrs = [x for x in args[2].a.flat] if type(args[2]) is Cell else []
    i = 0
    while i < len(attrs):
        a = py_str(attrs[i]) if type(attrs[i]) in (Char, Str) else None
        A = arr(v) if is_numeric(v) or type(v) in (bool, Char) else None
        if a == 'positive' and A is not None and not np.all(A > 0):
            raise err('MATLAB:expectedPositive', 'Expected input to be positive.')
        if a == 'nonnegative' and A is not None and not np.all(A >= 0):
            raise err('MATLAB:expectedNonnegative', 'Expected input to be nonnegative.')
        if a == 'scalar' and numel(v) != 1:
            raise err('MATLAB:expectedScalar', 'Expected input to be a scalar.')
        if a == 'vector' and not (len(shape_of(v)) == 2 and 1 in shape_of(v)):
            raise err('MATLAB:expectedVector', 'Expected input to be a vector.')
        if a == 'integer' and A is not None and not np.all(A == np.round(A)):
            raise err('MATLAB:expectedInteger', 'Expected input to be integer-valued.')
        if a == 'finite' and A is not None and not np.all(np.isfinite(A)):
            raise err('MATLAB:expectedFinite', 'Expected input to be finite.')
        if a == 'nonempty' and numel(v) == 0:
            raise err('MATLAB:expectedNonempty', 'Expected input to be nonempty.')
        if a in ('size', '>', '>=', '<', '<=', 'numel', 'ncols', 'nrows', 'increasing', 'decreasing'):
            if a in ('>', '>=', '<', '<='):
                lim = num(attrs[i + 1])
                ok = {'>': A > lim, '>=': A >= lim, '<': A < lim, '<=': A <= lim}[a]
                if not np.all(ok):
                    raise err('MATLAB:notGreater', f'Expected input to be {a} {lim:g}.')
            i += 1 if a not in ('increasing', 'decreasing') else 0
        i += 1
    return None


@bi('onCleanup')
def oncleanup(nargout, *args):
    return R.Cleanup(args[0])


@bi('rng')
def rng(nargout, *args):
    from .elmat import rng_impl
    return rng_impl(nargout, *args)
