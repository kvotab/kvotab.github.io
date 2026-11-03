"""Text: character arrays, string arrays and cell arrays of character
vectors. Most functions take any of the three and give back the kind they
were given (a string array in, a string array out)."""
import math
import re

import numpy as np

from . import bi
from ._util import (err, nargchk, noout, maxout, arr, darr, out, opt_str, sval, ival, num, is_str, bool_out,
                    like_class, strip_flags, cellstr_list, to_cell_of_char)
from .fmt import sprintf as _sprintf, unescape
from ..values import (MError, NOVAL, Char, Cell, Struct, Str, FH, Obj, F64, C128, INT_TYPES, DTYPE_CLASS,
                      class_of, shape_of, numel, _2d, EMPTY, py_str, share_all, text_list)
from ..strings import to_str_array, num_text
from .. import runtime as R


# ---- the three kinds of text ------------------------------------------------------------

class _TextIn:
    """Text arguments mapped element by element: remembers the kind so the
    result can be given back the same way."""

    def __init__(self, v, fn):
        t = type(v)
        self.kind = None
        if t is Char:
            if v.a.ndim == 2 and v.a.shape[0] > 1:
                self.kind = 'charmat'
                self.items = v.row_strs()
                self.shape = (v.a.shape[0], 1)
            else:
                self.kind = 'char'
                self.items = [v.str()]
                self.shape = (1, 1)
        elif t is Str:
            self.kind = 'string'
            self.items = list(v.a.reshape(-1, order='F'))
            self.shape = v.a.shape
        elif t is Cell:
            self.kind = 'cell'
            self.items = []
            for x in v.a.reshape(-1, order='F'):
                if type(x) is Char:
                    self.items.append(x.str())
                elif type(x) is Str and x.a.size == 1:
                    self.items.append(x.a.flat[0])
                else:
                    raise err('MATLAB:invalidInput', 'Cell array elements must be character vectors.' if fn else '', fn)
            self.shape = v.a.shape
        else:
            raise err('MATLAB:invalidType', f'The first input must be text: a character vector, a cell array of character vectors, or a string array.', fn)

    def back(self, results):
        """Text results, as the input's kind."""
        if self.kind == 'char':
            return Char.of(results[0]) if results[0] is not None else Char.of('')
        if self.kind == 'charmat':
            return Char.rows(results)
        if self.kind == 'string':
            return Str.from_list(results, self.shape)
        return Cell.of_list([Char.of(s if s is not None else '') for s in results], self.shape)

    def back_values(self, results, empty=None):
        """Non-text results: one value for a char vector, an array or cell
        for the others."""
        if self.kind in ('char',):
            return results[0]
        return results


def _logical_result(tin, vals):
    if tin.kind == 'char':
        return bool(vals[0])
    a = np.array(vals, bool).reshape(tin.shape, order='F')
    return out(a)


# ---- making text ---------------------------------------------------------------------------

@bi('char')
def char(nargout, *args):
    if not args:
        return Char.of('')
    if len(args) == 1:
        v = args[0]
        t = type(v)
        if t is Char:
            return v
        if t is Str:
            strs = ['' if s is None else s for s in v.a.reshape(-1, order='F')]
            if v.a.size == 1:
                return Char.of(strs[0])
            return Char.rows(strs)
        if t is Cell:
            return Char.rows(cellstr_list(v))
        a = arr(v, 'char')
        if a.dtype.kind == 'c':
            a = a.real
        if a.dtype.kind == 'f' and np.any((a < 0) | (a != np.floor(a))):
            a = np.where(a < 0, 0, np.floor(a))
        return Char(_2d(np.clip(np.nan_to_num(a.astype(F64)), 0, 65535).astype(np.uint16)))
    rows = []
    for v in args:
        if type(v) is Cell:
            rows += cellstr_list(v)
        elif type(v) is Str:
            rows += cellstr_list(v)
        elif type(v) is Char:
            rows += v.row_strs() if v.a.shape[0] > 1 else [v.str()]
        else:
            rows.append(char(1, v).str())
    return Char.rows(rows)


@bi('string')
def string(nargout, *args):
    if not args:
        return Str.of('')
    v = args[0]
    if type(v) is Char and v.a.shape[0] > 1 and v.a.ndim == 2:
        return Str.from_list(v.row_strs(), (v.a.shape[0], 1))
    return to_str_array(v)


@bi('strings')
def strings(nargout, *args):
    from ._util import dims_from
    shape, _, _ = dims_from(args, 'strings', allow_class=False) if args else ((1, 1), None, None)
    a = np.empty(shape, object)
    a.fill('')
    return Str(a)


@bi('cellstr')
def cellstr(nargout, *args):
    nargchk(args, 1, 1, 'cellstr')
    v = args[0]
    if type(v) is Cell:
        for x in v.a.flat:
            if type(x) is not Char:
                raise err('MATLAB:cellstr:InputClass', 'Element must be a character vector.' if True else '', 'cellstr')
        return v
    if type(v) is Char:
        if v.a.size == 0:
            return Cell.of_list([Char.of('')])
        rows = [r.rstrip(' ') for r in v.row_strs()]
        return Cell.of_list([Char.of(r) for r in rows], (len(rows), 1))
    if type(v) is Str:
        return Cell.of_list([Char.of('' if s is None else s) for s in v.a.reshape(-1, order='F')], v.a.shape)
    raise err('MATLAB:cellstr:InputClass', 'Input must be a string array, character array, or cell array of character vectors.', 'cellstr')


@bi('blanks')
def blanks(nargout, *args):
    n = ival(args[0], 'n', 'blanks')
    return Char(np.full((1, n), 32, np.uint16)) if n > 0 else Char(np.zeros((1, 0), np.uint16))


@bi('convertStringsToChars')
def convert_strings_to_chars(nargout, *args):
    res = []
    for v in args:
        if type(v) is Str:
            if v.a.size == 1:
                res.append(Char.of(v.a.flat[0] or ''))
            else:
                res.append(cellstr(1, v))
        else:
            res.append(v)
    return res[0] if nargout <= 1 else tuple(res)


@bi('convertCharsToStrings')
def convert_chars_to_strings(nargout, *args):
    res = [to_str_array(v) if type(v) in (Char, Cell) else v for v in args]
    return res[0] if nargout <= 1 else tuple(res)


# ---- numbers to text and back -------------------------------------------------------------

def _num2str_scalar(x):
    if isinstance(x, (bool, np.bool_)):
        return '1' if x else '0'
    if isinstance(x, complex) or isinstance(x, np.complexfloating):
        z = complex(x)
        re_ = _num2str_scalar(z.real)
        im = _num2str_scalar(abs(z.imag))
        return f'{re_}{"-" if z.imag < 0 else "+"}{im}i'
    x = float(x)
    if x != x:
        return 'NaN'
    if math.isinf(x):
        return 'Inf' if x > 0 else '-Inf'
    if x == int(x):
        return str(int(x))
    d = max(int(math.floor(math.log10(abs(x)))), 0) + 5
    s = f'{x:.{d}g}'
    if 'e' in s:
        m, e = s.split('e')
        s = f'{m}e{int(e):+03d}'
    return s


@bi('num2str')
def num2str(nargout, *args):
    nargchk(args, 1, 2, 'num2str')
    v = args[0]
    if type(v) is Char:
        return v
    if type(v) is Str:
        return Char.of(py_str(v))
    if type(v) in (Cell, Struct):
        raise err('MATLAB:num2str:invalidInput', 'Input to num2str must be numeric.' if True else '', 'num2str')
    a = arr(v, 'num2str')
    if len(args) > 1:
        f = args[1]
        if is_str(f):
            fmt = py_str(f)
            rows = []
            A = a if a.ndim == 2 else a.reshape(a.shape[0], -1, order='F')
            for r in A:
                rows.append(_sprintf(fmt, [np.array([r])]))
            return Char.rows(rows) if len(rows) != 1 else Char.of(rows[0])
        prec = ival(f, 'precision', 'num2str')
        A = a if a.ndim == 2 else a.reshape(a.shape[0], -1, order='F')
        texts = [[(f'{float(x):.{prec}g}' if A.dtype.kind != 'c' else _num2str_scalar(x)) for x in row] for row in A]
        texts = [[_fix_exp(t) for t in row] for row in texts]
        return _columns(texts)
    if a.size == 1:
        return Char.of(_num2str_scalar(a.reshape(-1)[0] if a.dtype.kind != 'b' else bool(a.reshape(-1)[0])))
    if a.size == 0:
        return Char.of('')
    A = a if a.ndim == 2 else a.reshape(a.shape[0], -1, order='F')
    if A.dtype.kind in 'iub' or (A.dtype.kind == 'f' and np.all(np.isfinite(A) == np.isfinite(A)) and np.all((A == np.round(A)) | ~np.isfinite(A))):
        texts = [[_num2str_scalar(int(x) if A.dtype.kind in 'iu' else (float(x) if A.dtype.kind != 'b' else bool(x))) for x in row] for row in A]
        return _columns(texts, sep=2)
    if A.dtype.kind == 'c':
        texts = [[_num2str_scalar(x) for x in row] for row in A]
        return _columns(texts)
    fin = A[np.isfinite(A)]
    mx = float(np.max(np.abs(fin))) if fin.size else 1.0
    d = max(int(math.floor(math.log10(mx))) if mx > 0 else 0, 0) + 5
    texts = [[_fix_exp(f'{float(x):.{d}g}') if math.isfinite(x) else ('NaN' if x != x else ('Inf' if x > 0 else '-Inf')) for x in row] for row in A]
    return _columns(texts, sep=2)


def _fix_exp(s):
    if 'e' in s:
        m, e = s.split('e')
        return f'{m}e{int(e):+03d}'
    return s


def _columns(texts, sep=2):
    ncol = len(texts[0]) if texts else 0
    widths = [max(len(texts[i][j]) for i in range(len(texts))) for j in range(ncol)]
    rows = []
    for row in texts:
        rows.append((' ' * sep).join(t.rjust(widths[j]) for j, t in enumerate(row)))
    if len(rows) == 1:
        return Char.of(rows[0])
    return Char.rows(rows)


@bi('int2str')
def int2str(nargout, *args):
    a = arr(args[0])
    from .elfun import _round_half
    r = _round_half(a.astype(F64)) if a.dtype.kind == 'f' else a
    return num2str(1, out(r) if r.dtype.kind == 'f' else r)


@bi('mat2str')
def mat2str(nargout, *args):
    nargchk(args, 1, 3, 'mat2str')
    v = args[0]
    prec = 15
    with_class = False
    for a in args[1:]:
        s = opt_str(a)
        if s == 'class':
            with_class = True
        elif s is None:
            prec = ival(a, 'precision', 'mat2str')
    if type(v) is Char:
        rows = v.row_strs() if v.a.shape[0] != 1 else [v.str()]
        parts = ["'" + r.replace("'", "''") + "'" for r in rows]
        return Char.of(parts[0] if len(parts) == 1 else '[' + ';'.join(parts) + ']')
    if type(v) is Str:
        parts = ['"' + (s or '') + '"' for s in v.a.reshape(-1)]
        return Char.of(parts[0] if len(parts) == 1 else '[' + ' '.join(parts) + ']')
    a = arr(v, 'mat2str')
    if a.ndim > 2:
        raise err('MATLAB:mat2str:TwoDInput', 'Input matrix must be 2-D.', 'mat2str')

    def f(x):
        if a.dtype.kind == 'b':
            return 'true' if x else 'false'
        if isinstance(x, (complex, np.complexfloating)):
            z = complex(x)
            return f(z.real) + ('-' if z.imag < 0 else '+') + f(abs(z.imag)) + 'i'
        x = float(x)
        if x != x:
            return 'NaN'
        if math.isinf(x):
            return 'Inf' if x > 0 else '-Inf'
        s = f'{x:.{prec}g}'
        if 'e' in s:
            m, e = s.split('e')
            s = f'{m}e{"+" if int(e) >= 0 else "-"}{abs(int(e)):02d}'
        return s
    rows = [' '.join(f(x) for x in row) for row in a]
    s = rows[0] if a.size == 1 else '[' + ';'.join(rows) + ']'
    if a.size == 0:
        s = '[]' if a.shape == (0, 0) else f'zeros({a.shape[0]},{a.shape[1]})'
    if with_class and class_of(v) != 'double':
        s = f'{class_of(v)}({s})'
    return Char.of(s)


@bi('str2num', ws=True, nout=2, arr=False)
def str2num(W, nargout, *args):
    nargchk(args, 1, 2, 'str2num')
    v = args[0]
    if type(v) is Char and v.a.shape[0] > 1:
        text = ';'.join(v.row_strs())
    else:
        text = sval(v, 'text', 'str2num')
    ok = True
    try:
        ws = R.Workspace('str2num')
        fn, mod = R.compile_command('plabTmpValue = [' + text + '];', ws)
        R.run_sync(fn(ws))
        val = ws['plabTmpValue']
    except MError:
        val = EMPTY()
        ok = False
    if nargout >= 2:
        return val, ok
    return val


_NUM_RE = re.compile(r'^\s*([+-]?)\s*((?:\d[\d,]*\.?\d*|\.\d+)(?:[eEdD][+-]?\d+)?|inf|infinity|nan)\s*$', re.I)
_CPLX_RE = re.compile(r'^\s*([+-]?\s*(?:(?:\d[\d,]*\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|inf|nan)?)\s*([+-])\s*((?:(?:\d[\d,]*\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|inf|nan)?)\s*\*?\s*[ij]\s*$', re.I)
_IMAG_RE = re.compile(r'^\s*([+-]?)\s*((?:(?:\d[\d,]*\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|inf|nan)?)\s*\*?\s*[ij]\s*$', re.I)


def parse_double(s):
    if s is None:
        return math.nan
    m = _NUM_RE.match(s)
    if m:
        body = m.group(2).replace(',', '').replace('d', 'e').replace('D', 'e')
        bl = body.lower()
        x = math.inf if bl.startswith('inf') else math.nan if bl == 'nan' else float(body)
        return -x if m.group(1) == '-' else x
    m = _IMAG_RE.match(s)
    if m:
        body = m.group(2) or '1'
        x = float(body.replace(',', '')) if body.lower() not in ('inf', 'nan') else float(body)
        return complex(0, -x if m.group(1) == '-' else x)
    m = _CPLX_RE.match(s)
    if m and m.group(1).strip():
        re_s = m.group(1).replace(' ', '').replace(',', '')
        im_s = (m.group(3) or '1').replace(',', '')
        try:
            re_v = float(re_s)
            im_v = float(im_s)
        except ValueError:
            return math.nan
        return complex(re_v, -im_v if m.group(2) == '-' else im_v)
    return math.nan


@bi('str2double')
def str2double(nargout, *args):
    nargchk(args, 1, 1, 'str2double')
    v = args[0]
    t = type(v)
    if t is Char:
        if v.a.ndim == 2 and v.a.shape[0] > 1:
            return math.nan
        r = parse_double(v.str())
        return r
    if t is Str:
        vals = [parse_double(s) for s in v.a.reshape(-1, order='F')]
    elif t is Cell:
        vals = [parse_double(py_str(x)) if type(x) in (Char, Str) else math.nan for x in v.a.reshape(-1, order='F')]
    else:
        return math.nan
    a = np.array(vals, dtype=C128 if any(isinstance(x, complex) for x in vals) else F64)
    return out(a.reshape(v.a.shape, order='F'))


@bi('dec2bin')
def dec2bin(nargout, *args):
    a = arr(args[0]).reshape(-1, order='F')
    n = ival(args[1]) if len(args) > 1 else 0
    if np.any(a < 0):
        a = np.where(a < 0, a + 2.0 ** 8 if False else a, a)
    strs = [format(int(x), 'b') for x in a]
    w = max([len(s) for s in strs] + [n])
    return Char.rows([s.rjust(w, '0') for s in strs]) if len(strs) != 1 else Char.of(strs[0].rjust(w, '0'))


@bi('dec2hex')
def dec2hex(nargout, *args):
    a = arr(args[0]).reshape(-1, order='F')
    n = ival(args[1]) if len(args) > 1 else 0
    strs = [format(int(x), 'X') for x in a]
    w = max([len(s) for s in strs] + [n])
    return Char.rows([s.rjust(w, '0') for s in strs]) if len(strs) != 1 else Char.of(strs[0].rjust(w, '0'))


@bi('dec2base')
def dec2base(nargout, *args):
    a = arr(args[0]).reshape(-1, order='F')
    base = ival(args[1])
    n = ival(args[2]) if len(args) > 2 else 0
    digits = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'

    def conv(x):
        x = int(x)
        if x == 0:
            return '0'
        s = ''
        while x:
            s = digits[x % base] + s
            x //= base
        return s
    strs = [conv(x) for x in a]
    w = max([len(s) for s in strs] + [n])
    return Char.rows([s.rjust(w, '0') for s in strs]) if len(strs) != 1 else Char.of(strs[0].rjust(w, '0'))


def _from_base(args, base, fn):
    v = args[0]
    strs = text_list(v)
    vals = []
    for s in strs:
        s = s.strip().replace(' ', '')
        try:
            vals.append(float(int(s, base)) if s else 0.0)
        except ValueError:
            raise err(f'MATLAB:{fn}:IllegalBinaryString', f'Input must be a valid number in base {base}.', fn)
    if len(vals) == 1:
        return vals[0]
    return out(np.array(vals).reshape(-1, 1))


@bi('bin2dec')
def bin2dec(nargout, *args):
    return _from_base(args, 2, 'bin2dec')


@bi('hex2dec')
def hex2dec(nargout, *args):
    return _from_base(args, 16, 'hex2dec')


@bi('base2dec')
def base2dec(nargout, *args):
    return _from_base(args[:1], ival(args[1]), 'base2dec')


@bi('num2hex')
def num2hex(nargout, *args):
    import struct
    a = darr(args[0]).reshape(-1, order='F').real
    return Char.rows([struct.pack('>d', float(x)).hex() for x in a])


@bi('hex2num')
def hex2num(nargout, *args):
    import struct
    vals = [struct.unpack('>d', bytes.fromhex(s.ljust(16, '0')))[0] for s in text_list(args[0])]
    return vals[0] if len(vals) == 1 else out(np.array(vals).reshape(-1, 1))


# ---- case, blanks, trimming --------------------------------------------------------------

def _case_map(v, fn):
    """upper and lower of char arrays of any shape (a character code at a
    time: one whose case changes into more letters stays), of strings, and of
    each element of a cell."""
    t = type(v)
    if t is Char:
        codes = np.asarray(v.a)
        out_ = codes.copy()
        for u in np.unique(codes):
            c = fn(chr(int(u)))
            if len(c) == 1 and ord(c) < 65536:
                out_[codes == u] = ord(c)
        return Char(out_)
    if t is Cell:
        a = np.empty(v.a.shape, object)
        for idx in np.ndindex(v.a.shape):
            a[idx] = _case_map(v.a[idx], fn)
        return Cell(a)
    if t is Str:
        a = np.empty(v.a.shape, object)
        for idx in np.ndindex(v.a.shape):
            x = v.a[idx]
            a[idx] = None if x is None else fn(x)
        return Str(a)
    return v


def _map_text(name, fn):
    def f(nargout, *args):
        nargchk(args, 1, None, name)
        v = args[0]
        if type(v) not in (Char, Str, Cell):
            if name in ('upper', 'lower'):
                return v
            raise err('MATLAB:invalidType', f'Input must be text.', name)
        if name in ('upper', 'lower'):
            return _case_map(v, fn)
        tin = _TextIn(v, name)
        return tin.back([None if s is None else fn(s, *args[1:]) if name in ('strip',) else (None if s is None else fn(s)) for s in tin.items])
    f.__name__ = name
    bi(name)(f)


_map_text('upper', str.upper)
_map_text('lower', str.lower)
_map_text('strtrim', lambda s: s.strip(' \t\n\r\f\v\x00\u00a0'))
_map_text('deblank', lambda s: s.rstrip(' \t\n\r\f\v\x00'))
_map_text('reverse', lambda s: s[::-1])


@bi('strip')
def strip(nargout, *args):
    v = args[0]
    side = 'both'
    chars = None
    if len(args) > 1:
        s = opt_str(args[1])
        if s in ('left', 'right', 'both'):
            side = s
            if len(args) > 2:
                chars = py_str(args[2])
        else:
            chars = s
    tin = _TextIn(v, 'strip')

    def f(s):
        if s is None:
            return None
        if side == 'left':
            return s.lstrip(chars) if chars else s.lstrip()
        if side == 'right':
            return s.rstrip(chars) if chars else s.rstrip()
        return s.strip(chars) if chars else s.strip()
    return tin.back([f(s) for s in tin.items])


@bi('pad')
def pad(nargout, *args):
    v = args[0]
    tin = _TextIn(v, 'pad')
    width = None
    side = 'right'
    ch = ' '
    for a in args[1:]:
        s = opt_str(a)
        if s in ('left', 'right', 'both'):
            side = s
        elif s is not None:
            ch = s
        else:
            width = ival(a)
    if width is None:
        width = max([len(s or '') for s in tin.items] + [0])

    def f(s):
        if s is None:
            return None
        if side == 'left':
            return s.rjust(width, ch)
        if side == 'both':
            return s.center(width, ch)
        return s.ljust(width, ch)
    return tin.back([f(s) for s in tin.items])


@bi('strjust')
def strjust(nargout, *args):
    v = args[0]
    side = opt_str(args[1]) if len(args) > 1 else 'right'
    rows = v.row_strs() if type(v) is Char else text_list(v)
    w = max([len(r) for r in rows] + [0])
    res = []
    for r in rows:
        t = r.strip(' ')
        res.append(t.rjust(w) if side == 'right' else t.ljust(w) if side == 'left' else t.center(w))
    return Char.rows(res)


@bi('strlength')
def strlength(nargout, *args):
    tin = _TextIn(args[0], 'strlength')
    vals = [float(len(s)) if s is not None else math.nan for s in tin.items]
    if tin.kind == 'char':
        return vals[0]
    return out(np.array(vals).reshape(tin.shape, order='F'))


# ---- comparison ------------------------------------------------------------------------

def _cmp_fn(name, fn):
    def f(nargout, *args):
        nargchk(args, 2, 3, name)
        a, b = args[0], args[1]
        n = ival(args[2], 'n', name) if len(args) > 2 else None
        ta, tb = type(a), type(b)

        def one_text(v):
            t = type(v)
            if t is Char:
                if v.a.ndim == 2 and v.a.shape[0] <= 1:
                    return True, v.str()
                return True, None
            if t is Str and v.a.size == 1:
                return True, v.a.flat[0]
            return False, None
        sa, xa = one_text(a)
        sb, xb = one_text(b)
        if sa and sb:
            if xa is None or xb is None:
                if ta is Char and tb is Char:
                    return bool(a.a.shape == b.a.shape and np.array_equal(a.a, b.a) and fn(a.str(), b.str(), n))
                return False
            if ta is Char and tb is Char and n is None and a.a.shape != b.a.shape:
                return False                    # two char arrays are the same only at the same size
            return bool(fn(xa, xb, n))
        # element-wise with cells or string arrays
        if ta in (Cell, Str) or tb in (Cell, Str):
            la = _cmp_list(a)
            lb = _cmp_list(b)
            if la is None or lb is None:
                return False if not (ta in (Cell, Str) or tb in (Cell, Str)) else out(np.zeros(shape_of(a) if ta in (Cell, Str) else shape_of(b), bool))
            ca, cb = ta in (Cell, Str), tb in (Cell, Str)
            # a text, or a cell of one, against each element of the other
            if not ca or (cb and len(la) == 1 and len(lb) != 1):
                shape = shape_of(b)
                vals = [x is not None and la[0] is not None and fn(la[0], x, n) for x in lb]
            elif not cb or len(lb) == 1:
                shape = shape_of(a)
                vals = [x is not None and lb[0] is not None and fn(x, lb[0], n) for x in la]
            else:
                if shape_of(a) != shape_of(b):
                    raise err('MATLAB:strcmp:InputsSizeMismatch', 'Inputs must be the same size or either one can be a scalar.', name)
                shape = shape_of(a)
                vals = [x is not None and y is not None and fn(x, y, n) for x, y in zip(la, lb)]
            return out(np.array(vals, bool).reshape(shape, order='F'))
        return False
    f.__name__ = name
    bi(name)(f)


def _cmp_list(v):
    t = type(v)
    if t is Cell:
        return [x.str() if type(x) is Char and x.a.shape[0] <= 1 else (x.a.flat[0] if type(x) is Str and x.a.size == 1 else None) for x in v.a.reshape(-1, order='F')]
    if t is Str:
        return list(v.a.reshape(-1, order='F'))
    if t is Char:
        return [v.str()] if v.a.shape[0] <= 1 else None
    return [None]


_cmp_fn('strcmp', lambda a, b, n: a == b)
_cmp_fn('strcmpi', lambda a, b, n: a.lower() == b.lower())
# the first n characters as they are: a text shorter than n is compared whole
_cmp_fn('strncmp', lambda a, b, n: a[:n] == b[:n])
_cmp_fn('strncmpi', lambda a, b, n: a[:n].lower() == b[:n].lower())


@bi('matches')
def matches(nargout, *args):
    tin = _TextIn(args[0], 'matches')
    pats = text_list(args[1])
    rest, flags = strip_flags(args[2:], ())
    ic = False
    for i in range(0, len(args) - 2, 2):
        if opt_str(args[2 + i]).lower() == 'ignorecase':
            ic = bool(arr(args[3 + i]).reshape(-1)[0])
    vals = [s is not None and any((s.lower() == p.lower()) if ic else s == p for p in pats) for s in tin.items]
    return _logical_result(tin, vals)


# ---- searching --------------------------------------------------------------------------

def _ic_option(args):
    ic = False
    rest = []
    i = 0
    while i < len(args):
        s = opt_str(args[i])
        if s is not None and s.lower() == 'ignorecase' and i + 1 < len(args):
            ic = bool(arr(args[i + 1]).reshape(-1)[0])
            i += 2
            continue
        rest.append(args[i])
        i += 1
    return ic, rest


@bi('contains')
def contains(nargout, *args):
    nargchk(args, 2, 4, 'contains')
    tin = _TextIn(args[0], 'contains')
    pats = text_list(args[1])
    ic, _ = _ic_option(args[2:])
    if ic:
        vals = [s is not None and any(p.lower() in s.lower() for p in pats) for s in tin.items]
    else:
        vals = [s is not None and any(p in s for p in pats) for s in tin.items]
    return _logical_result(tin, vals)


@bi('startsWith')
def startswith(nargout, *args):
    tin = _TextIn(args[0], 'startsWith')
    pats = tuple(text_list(args[1]))
    ic, _ = _ic_option(args[2:])
    vals = [s is not None and (s.lower().startswith(tuple(p.lower() for p in pats)) if ic else s.startswith(pats)) for s in tin.items]
    return _logical_result(tin, vals)


@bi('endsWith')
def endswith(nargout, *args):
    tin = _TextIn(args[0], 'endsWith')
    pats = tuple(text_list(args[1]))
    ic, _ = _ic_option(args[2:])
    vals = [s is not None and (s.lower().endswith(tuple(p.lower() for p in pats)) if ic else s.endswith(pats)) for s in tin.items]
    return _logical_result(tin, vals)


@bi('strfind')
def strfind(nargout, *args):
    nargchk(args, 2, 4, 'strfind')
    v = args[0]
    pat = sval(args[1], 'pattern', 'strfind') if type(args[1]) is not Cell else None
    overlaps = True
    if len(args) > 3 and opt_str(args[2]).lower() == 'forcecelloutput':
        pass

    def find_all(s):
        if not pat:
            return np.zeros((1, 0)) if True else EMPTY()
        res = []
        i = s.find(pat)
        while i >= 0:
            res.append(i + 1)
            i = s.find(pat, i + 1)
        if not res:
            return EMPTY() if False else np.zeros((1, 0))
        return out(np.array([res], F64))
    if type(v) is Char:
        r = find_all(v.str())
        if type(r) is np.ndarray and r.size == 0:
            return np.zeros((1, 0))
        return r
    tin = _TextIn(v, 'strfind')
    return Cell.of_list([find_all(s or '') for s in tin.items], tin.shape)


@bi('count')
def count(nargout, *args):
    tin = _TextIn(args[0], 'count')
    pats = text_list(args[1])
    ic, _ = _ic_option(args[2:])
    vals = []
    for s in tin.items:
        if s is None:
            vals.append(math.nan)
            continue
        ss = s.lower() if ic else s
        c = 0
        for p in pats:
            pp = p.lower() if ic else p
            if pp:
                c += ss.count(pp)
        vals.append(float(c))
    if tin.kind == 'char':
        return vals[0]
    return out(np.array(vals).reshape(tin.shape, order='F'))


@bi('strtok', nout=2)
def strtok(nargout, *args):
    v = args[0]
    delims = py_str(args[1]) if len(args) > 1 else ' \t\n\x0b\x0c\r\x00'

    def tok(s):
        i = 0
        while i < len(s) and s[i] in delims:
            i += 1
        j = i
        while j < len(s) and s[j] not in delims:
            j += 1
        return s[i:j], s[j:]
    if type(v) is Char:
        t, r = tok(v.str())
        return (Char.of(t), Char.of(r)) if nargout >= 2 else Char.of(t)
    tin = _TextIn(v, 'strtok')
    pairs = [tok(s or '') for s in tin.items]
    toks = tin.back([p[0] for p in pairs])
    rems = tin.back([p[1] for p in pairs])
    return (toks, rems) if nargout >= 2 else toks


# ---- replacing ----------------------------------------------------------------------------

@bi('strrep')
def strrep(nargout, *args):
    nargchk(args, 3, 3, 'strrep')
    tin = _TextIn(args[0], 'strrep')
    old = sval(args[1], 'pattern', 'strrep')
    new = sval(args[2], 'replacement', 'strrep')

    def rep(s):
        if s is None or not old:
            return s
        # every occurrence, overlapping ones too, as the language does
        idx = []
        i = s.find(old)
        while i >= 0:
            idx.append(i)
            i = s.find(old, i + 1)
        if not idx:
            return s
        overlapping = any(b - a < len(old) for a, b in zip(idx, idx[1:]))
        if not overlapping:
            return s.replace(old, new)
        outp = []
        last = 0
        for k in idx:
            if k >= last:
                outp.append(s[last:k])
            outp.append(new)
            last = k + len(old)
        outp.append(s[last:])
        return ''.join(outp)
    return tin.back([rep(s) for s in tin.items])


@bi('replace')
def replace(nargout, *args):
    nargchk(args, 3, 3, 'replace')
    tin = _TextIn(args[0], 'replace')
    olds = text_list(args[1])
    news = text_list(args[2])
    if len(news) == 1:
        news = news * len(olds)

    def rep(s):
        if s is None:
            return s
        pattern = '|'.join(re.escape(o) for o in sorted(olds, key=len, reverse=True) if o)
        if not pattern:
            return s
        m = dict(zip(olds, news))
        return re.sub(pattern, lambda mm: m[mm.group(0)], s)
    return tin.back([rep(s) for s in tin.items])


@bi('erase')
def erase(nargout, *args):
    tin = _TextIn(args[0], 'erase')
    pats = sorted(text_list(args[1]), key=len, reverse=True)

    def f(s):
        if s is None:
            return s
        for p in pats:
            if p:
                s = s.replace(p, '')
        return s
    return tin.back([f(s) for s in tin.items])


def _between(s, a, b):
    i = s.find(a)
    if i < 0:
        return None
    i += len(a)
    j = s.find(b, i)
    if j < 0:
        return None
    return s[i:j]


@bi('extractBefore')
def extract_before(nargout, *args):
    tin = _TextIn(args[0], 'extractBefore')
    p = args[1]

    def f(s):
        if s is None:
            return None
        if is_str(p):
            k = s.find(py_str(p))
            return s[:k] if k >= 0 else None
        k = ival(p)
        return s[:k - 1]
    r = [f(s) for s in tin.items]
    if tin.kind == 'char' and r[0] is None:
        return Char.of('')
    return tin.back(r)


@bi('extractAfter')
def extract_after(nargout, *args):
    tin = _TextIn(args[0], 'extractAfter')
    p = args[1]

    def f(s):
        if s is None:
            return None
        if is_str(p):
            q = py_str(p)
            k = s.find(q)
            return s[k + len(q):] if k >= 0 else None
        k = ival(p)
        return s[k:]
    r = [f(s) for s in tin.items]
    if tin.kind == 'char' and r[0] is None:
        return Char.of('')
    return tin.back(r)


@bi('extractBetween')
def extract_between(nargout, *args):
    tin = _TextIn(args[0], 'extractBetween')
    a, b = args[1], args[2]

    def f(s):
        if is_str(a):
            return _between(s, py_str(a), py_str(b))
        return s[ival(a) - 1:ival(b)]
    res = [f(s or '') for s in tin.items]
    if tin.kind == 'char':
        return Cell.of_list([Char.of(res[0] or '')]) if res[0] is not None else Cell.empty((0, 1))
    return tin.back([r or '' for r in res])


@bi('insertAfter')
def insert_after(nargout, *args):
    tin = _TextIn(args[0], 'insertAfter')
    p, new = args[1], py_str(args[2])

    def f(s):
        if is_str(p):
            q = py_str(p)
            return s.replace(q, q + new)
        k = ival(p)
        return s[:k] + new + s[k:]
    return tin.back([f(s or '') for s in tin.items])


@bi('insertBefore')
def insert_before(nargout, *args):
    tin = _TextIn(args[0], 'insertBefore')
    p, new = args[1], py_str(args[2])

    def f(s):
        if is_str(p):
            q = py_str(p)
            return s.replace(q, new + q)
        k = ival(p)
        return s[:k - 1] + new + s[k - 1:]
    return tin.back([f(s or '') for s in tin.items])


# ---- joining and splitting -----------------------------------------------------------------

@bi('strcat')
def strcat(nargout, *args):
    if not args:
        return Char.of('')
    if any(type(a) is Str for a in args):
        r = to_str_array(args[0])
        from ..ops import str_plus
        for a in args[1:]:
            r = str_plus(r, a)
        return r
    if any(type(a) is Cell for a in args):
        n = max(numel(a) for a in args if type(a) is Cell)
        shape = next(shape_of(a) for a in args if type(a) is Cell and numel(a) == n)
        parts = []
        for a in args:
            if type(a) is Cell:
                lst = cellstr_list(a)
                parts.append(lst if len(lst) == n else lst * n)
            else:
                parts.append([py_str(a)] * n)
        res = [''.join(p[i] for p in parts) for i in range(n)]
        return Cell.of_list([Char.of(s) for s in res], shape)
    # char arrays: trailing blanks of each argument are removed
    rows = None
    for a in args:
        if type(a) is Char and a.a.ndim == 2 and a.a.shape[0] > 1:
            rows = a.a.shape[0]
    if rows:
        res = [''] * rows
        for a in args:
            if type(a) is Char:
                rs = a.row_strs() if a.a.shape[0] > 1 else [a.str()] * rows
            else:
                rs = [py_str(a)] * rows
            res = [x + y.rstrip(' \t\n\x0b\x0c\r\x00') for x, y in zip(res, rs)]
        return Char.rows(res)
    s = ''
    for a in args:
        if type(a) is Char:
            s += a.str().rstrip(' \t\n\x0b\x0c\r\x00')
        elif type(a) in (float, np.ndarray, bool):
            s += char(1, a).str()
        else:
            s += py_str(a)
    return Char.of(s)


@bi('strvcat')
def strvcat(nargout, *args):
    rows = []
    for a in args:
        if type(a) is Cell:
            rows += cellstr_list(a)
        elif type(a) is Char:
            rows += [r for r in (a.row_strs() if a.a.shape[0] > 1 else [a.str()]) if r]
        elif type(a) is Str:
            rows += cellstr_list(a)
        else:
            c = char(1, a)                  # numbers are character codes
            rows += c.row_strs() if c.a.shape[0] > 1 else [c.str()]
    rows = [r for r in rows if r]
    return Char.rows(rows)


@bi('strjoin')
def strjoin(nargout, *args):
    nargchk(args, 1, 2, 'strjoin')
    items = cellstr_list(args[0])
    if len(args) > 1:
        if type(args[1]) is Cell:
            ds = cellstr_list(args[1])
            s = ''
            for i, it in enumerate(items):
                s += it
                if i < len(ds) and i < len(items) - 1:
                    s += unescape(ds[i])
            return Char.of(s)
        d = unescape(py_str(args[1]))
    else:
        d = ' '
    r = d.join(items)
    return Str.of(r) if type(args[0]) is Str else Char.of(r)


@bi('join')
def join(nargout, *args):
    v = args[0]
    d = py_str(args[1]) if len(args) > 1 else ' '
    items = text_list(v)
    if type(v) is Str and v.a.ndim == 2 and v.a.shape[0] > 1 and v.a.shape[1] > 1:
        rows = [d.join(x or '' for x in row) for row in v.a]
        return Str.from_list(rows, (len(rows), 1))
    r = d.join(items)
    return Str.of(r) if type(v) is Str else Char.of(r)


@bi('strsplit', nout=2)
def strsplit(nargout, *args):
    nargchk(args, 1, None, 'strsplit')
    s = sval(args[0], 'text', 'strsplit')
    rest = list(args[1:])
    delims = None
    collapse = True
    regex = False
    if rest and opt_str(rest[0]) is not None and opt_str(rest[0]).lower() not in ('collapsedelimiters', 'delimitertype') or (rest and type(rest[0]) is Cell):
        delims = text_list(rest[0])
        rest = rest[1:]
    if rest and opt_str(rest[0]) is None and type(rest[0]) is not Cell and numel(rest[0]) == 1:
        collapse = bool(arr(rest[0]).reshape(-1)[0])       # a collapse flag in its place (as Octave takes it)
        rest = rest[1:]
    i = 0
    while i < len(rest):
        k = opt_str(rest[i])
        if k is None or i + 1 >= len(rest) or k.lower() not in ('collapsedelimiters', 'delimitertype'):
            raise err('MATLAB:strsplit:InvalidParameter', 'strsplit takes the text, the delimiters, and CollapseDelimiters or DelimiterType with their values.', 'strsplit')
        if k.lower() == 'collapsedelimiters':
            collapse = bool(arr(rest[i + 1]).reshape(-1)[0])
        else:
            v = (opt_str(rest[i + 1]) or '').lower()
            if not v or not ('regularexpression'.startswith(v) or 'simple'.startswith(v)):
                raise err('MATLAB:strsplit:InvalidDelimiterType', "DelimiterType is 'Simple' or 'RegularExpression'.", 'strsplit')
            regex = 'regularexpression'.startswith(v)
        i += 2
    if delims is None:
        pat = r'\s'
    elif regex:
        pat = '|'.join(delims)
    else:
        pat = '|'.join(re.escape(unescape(d)) for d in sorted(delims, key=len, reverse=True))
    if collapse:
        pat = f'(?:{pat})+'
    parts = re.split(pat, s)
    seps = re.findall(pat, s)
    c = Cell.of_list([Char.of(p) for p in parts])
    if nargout >= 2:
        return c, Cell.of_list([Char.of(x) for x in seps])
    return c


@bi('split', nout=2)
def split(nargout, *args):
    v = args[0]
    delims = text_list(args[1]) if len(args) > 1 else None
    s = py_str(v) if type(v) in (Char, Str) and numel(v) <= 1 or type(v) is Char else None
    items = text_list(v) if s is None else [s]
    pat = r'\s+' if delims is None else '|'.join(re.escape(d) for d in sorted(delims, key=len, reverse=True))
    if len(items) == 1:
        parts = re.split(pat, items[0])
        if delims is None:
            parts = re.split(r'\s+', items[0].strip()) if items[0].strip() else ['']
        shape = (len(parts), 1)
        return Str.from_list(parts, shape) if type(v) is Str or True else None
    rows = [re.split(pat, x) for x in items]
    n = len(rows[0])
    a = np.empty((len(rows), n), object)
    for i, r in enumerate(rows):
        a[i, :] = r
    return Str(a)


@bi('splitlines')
def splitlines(nargout, *args):
    s = py_str(args[0])
    parts = re.split(r'\r\n|\n|\r', s)
    return Str.from_list(parts, (len(parts), 1))


@bi('compose')
def compose(nargout, *args):
    fmt = py_str(args[0])
    if len(args) == 1:
        return Str.of(unescape(fmt))
    # one string per row of the arguments
    cols = [arr(a) if type(a) not in (Str, Cell) else a for a in args[1:]]
    n = max((c.shape[0] if type(c) is np.ndarray else numel(c)) for c in cols)
    res = []
    for i in range(n):
        row = []
        for c in cols:
            if type(c) is np.ndarray:
                row.append(c[min(i, c.shape[0] - 1)].reshape(1, -1))
            else:
                row.append(Char.of(text_list(c)[min(i, numel(c) - 1)]))
        res.append(_sprintf(fmt, row))
    return Str.from_list(res, (len(res), 1))


# ---- character tests ------------------------------------------------------------------------

def _char_test(name, fn):
    def f(nargout, *args):
        v = args[0]
        if type(v) is Char:
            a = v.a
            r = np.vectorize(lambda c: fn(chr(c)), otypes=[bool])(a) if a.size else np.zeros(a.shape, bool)
            return out(r)
        if type(v) is Str and v.a.size == 1:
            s = v.a.flat[0] or ''
            return out(np.array([[fn(c) for c in s]], bool).reshape(1, -1))
        return out(np.zeros(shape_of(v), bool))
    f.__name__ = name
    bi(name)(f)


_char_test('isspace', lambda c: c in ' \t\n\r\f\v')
_char_test('isletter', lambda c: c.isalpha())


@bi('isstrprop')
def isstrprop(nargout, *args):
    kind = py_str(args[1]).lower()
    tests = {'alpha': str.isalpha, 'alphanum': str.isalnum, 'digit': lambda c: c in '0123456789',
             'lower': str.islower, 'upper': str.isupper, 'wspace': lambda c: c in ' \t\n\r\f\v',
             'punct': lambda c: (not c.isalnum()) and c.isprintable() and not c.isspace(),
             'cntrl': lambda c: ord(c) < 32 or ord(c) == 127, 'graphic': lambda c: c.isprintable() and not c.isspace(),
             'print': lambda c: c.isprintable(), 'xdigit': lambda c: c in '0123456789abcdefABCDEF'}
    fn = tests.get(kind)
    if fn is None:
        raise err('MATLAB:isstrprop:InvalidCategory', f"Invalid category '{kind}'.", 'isstrprop')
    v = args[0]
    if type(v) is Char:
        a = v.a
        return out(np.vectorize(lambda c: fn(chr(c)), otypes=[bool])(a) if a.size else np.zeros(a.shape, bool))
    if type(v) is Cell:
        return Cell.of_list([isstrprop(1, x, args[1]) for x in v.a.reshape(-1, order='F')], v.a.shape)
    if type(v) is Str and v.a.size == 1:
        return out(np.array([[fn(c) for c in (v.a.flat[0] or '')]], bool).reshape(1, -1))
    a = arr(v)
    return out(np.vectorize(lambda c: fn(chr(int(c))) if 0 <= c < 0x110000 else False, otypes=[bool])(a))


@bi('validatestring')
def validatestring(nargout, *args):
    s = py_str(args[0])
    opts = text_list(args[1])
    hits = [o for o in opts if o.lower().startswith(s.lower())]
    if not hits:
        raise err('MATLAB:unrecognizedStringChoice', f"Expected input to match one of these values:\n\n{', '.join(repr(o) for o in opts)}\n\nThe input, '{s}', did not match any of the valid values.", 'validatestring')
    exact = [o for o in hits if o.lower() == s.lower()]
    return Char.of((exact or hits)[0])


# ---- regular expressions --------------------------------------------------------------------

def _py_pattern(p):
    """The language's regular expressions in Python's dialect: named groups
    (?<name>...), word boundaries \\< and \\> (start and end of a word),
    and flag groups such as (?i) or (?-s) anywhere, which Python takes only as
    scoped groups: they run to the end of the group they stand in."""
    p = re.sub(r'\(\?<([A-Za-z]\w*)>', r'(?P<\1>', p)
    out_, i, n = [], 0, len(p)
    stack = [[]]                # the scoped flag groups open at each group depth
    in_class = False
    while i < n:
        c = p[i]
        if c == '\\' and i + 1 < n:
            nxt = p[i + 1]
            if nxt == '<' and not in_class:
                out_.append(r'(?<!\w)(?=\w)')
            elif nxt == '>' and not in_class:
                out_.append(r'(?<=\w)(?!\w)')
            else:
                out_.append(p[i:i + 2])
            i += 2
            continue
        if in_class:
            if c == ']':
                in_class = False
            out_.append(c)
            i += 1
            continue
        if c == '[':
            in_class = True
            out_.append(c)
            if i + 1 < n and p[i + 1] == '^':
                out_.append('^')
                i += 1
            if i + 1 < n and p[i + 1] == ']':
                out_.append(']')
                i += 1
            i += 1
            continue
        m = re.match(r'\(\?([imsx]*)(?:-([imsx]+))?\)', p[i:]) if c == '(' else None
        if m and (m.group(1) or m.group(2)):
            on, off = m.group(1), m.group(2) or ''
            g = f'(?{on}' + (f'-{off}' if off else '') + ':'
            out_.append(g)
            stack[-1].append(g)
            i += m.end()
            continue
        if c == '(':
            stack.append([])
        elif c == ')' and len(stack) > 1:
            out_.append(')' * len(stack.pop()))
        elif c == '|' and stack[-1]:
            # the flags hold for the alternatives after this one too: close, then open again
            out_.append(')' * len(stack[-1]) + '|' + ''.join(stack[-1]))
            i += 1
            continue
        out_.append(c)
        i += 1
    out_.append(')' * sum(len(x) for x in stack))
    return ''.join(out_)


def _py_replacement(r):
    """The language's replacement text as a function of a match: $N and
    $<name> are tokens ($0 the whole match), \\$ and \\\\ a dollar and a
    backslash, \\n, \\t and the like their characters, and a backslash before
    any other character that character."""
    esc = {'n': '\n', 't': '\t', 'r': '\r', 'a': '\a', 'f': '\f', 'v': '\v', 'b': '\b'}
    parts, i, lit = [], 0, []
    while i < len(r):
        c = r[i]
        if c == '\\' and i + 1 < len(r):
            lit.append(esc.get(r[i + 1], r[i + 1]))
            i += 2
            continue
        if c == '$':
            m = re.match(r'\$(\d+)|\$<([A-Za-z]\w*)>|\$\{(\d+)\}', r[i:])
            if m:
                parts.append(''.join(lit))
                lit = []
                parts.append(int(m.group(1) or m.group(3)) if (m.group(1) or m.group(3)) else ('name', m.group(2)))
                i += m.end()
                continue
        lit.append(c)
        i += 1
    parts.append(''.join(lit))

    def f(m):
        res = []
        for part in parts:
            if isinstance(part, tuple):
                res.append((m.group(part[1]) or '') if part[1] in m.re.groupindex else '')
            elif isinstance(part, int):
                res.append((m.group(part) or '') if part <= m.re.groups else '')
            else:
                res.append(part)
        return ''.join(res)
    return f


def _re_flags(opts):
    flags = 0
    for o in opts:
        if o == 'ignorecase':
            flags |= re.I
        elif o == 'matchcase':
            flags &= ~re.I
        elif o == 'lineanchors':
            flags |= re.M
        elif o == 'dotexceptnewline':
            pass
        elif o == 'freespacing':
            flags |= re.X
    if 'dotexceptnewline' not in opts:
        flags |= re.S
    return flags


_SELECTORS = ('match', 'tokens', 'names', 'start', 'end', 'split', 'tokenextents')


def _regexp(args, nargout, ignorecase=False, fn='regexp'):
    nargchk(args, 2, None, fn)
    v = args[0]
    pats = args[1]
    opts = [opt_str(a).lower() for a in args[2:] if opt_str(a) is not None]
    once = 'once' in opts
    selected = [o for o in opts if o in _SELECTORS]
    flagopts = [o for o in opts if o not in _SELECTORS]
    if ignorecase:
        flagopts.insert(0, 'ignorecase')        # regexpi: unless 'matchcase' follows
    if type(v) in (Cell, Str) and not (type(v) is Str and v.a.size == 1):
        # one result per text
        items = text_list(v)
        shape = shape_of(v)
        n = max(nargout, 1)
        if type(pats) in (Cell, Str) and len(text_list(pats)) == len(items) and len(items) > 1:
            plist = text_list(pats)            # a pattern for each text
            per = [_regexp([Char.of(s), Char.of(p)] + list(args[2:]), n, ignorecase, fn) for s, p in zip(items, plist)]
        else:
            per = [_regexp([Char.of(s)] + list(args[1:]), n, ignorecase, fn) for s in items]
        if n == 1:
            return Cell.of_list([p for p in per], shape)
        return tuple(Cell.of_list([p[k] for p in per], shape) for k in range(n))
    if type(pats) in (Cell, Str) and not (type(pats) is Str and pats.a.size == 1):
        # a pattern for each result
        plist = text_list(pats)
        n = max(nargout, 1)
        per = [_regexp([v, Char.of(p)] + list(args[2:]), n, ignorecase, fn) for p in plist]
        shape = shape_of(pats)
        if n == 1:
            return Cell.of_list(per, shape)
        return tuple(Cell.of_list([p[k] for p in per], shape) for k in range(n))
    s = py_str(v)
    pat = _py_pattern(py_str(pats))
    try:
        rx = re.compile(pat, _re_flags(flagopts))
    except re.error as e:
        raise err('MATLAB:regexp:badPattern', f'The regular expression is not valid: {e}.', fn)
    ms = list(rx.finditer(s))
    if 'emptymatch' not in flagopts:
        ms = [m for m in ms if m.end() > m.start()]      # empty matches only when asked for
    if once:
        ms = ms[:1]

    def tokens_of(m):
        if m.re.groups == 0:
            return Cell.of_list([Char.of(m.group(0))])
        return Cell.of_list([Char.of(g if g is not None else '') for g in m.groups()])

    def extents_of(m):
        if m.re.groups == 0:
            return out(np.array([[m.start() + 1, m.end()]], F64))
        return out(np.array([[m.start(i) + 1, m.end(i)] for i in range(1, m.re.groups + 1)], F64))

    def names_of(m):
        names = list(rx.groupindex)
        return Struct.scalar({k: Char.of(m.group(k) or '') for k in names})

    def split_parts():
        parts = []
        last = 0
        for m in ms:
            parts.append(Char.of(s[last:m.start()]))
            last = m.end()
        parts.append(Char.of(s[last:]))
        return Cell.of_list(parts)

    results = {}
    if once:
        m = ms[0] if ms else None
        results['start'] = float(m.start() + 1) if m else np.zeros((1, 0))
        results['end'] = float(m.end()) if m else np.zeros((1, 0))
        results['match'] = Char.of(m.group(0)) if m else Char.of('')
        results['tokens'] = tokens_of(m) if m else Cell.empty((1, 0))
        results['names'] = names_of(m) if m else Struct.empty((0, 0), list(rx.groupindex))
        results['tokenextents'] = extents_of(m) if m else np.zeros((0, 2))
        results['split'] = split_parts()
    else:
        results['start'] = out(np.array([[m.start() + 1 for m in ms]], F64)) if ms else np.zeros((1, 0))
        results['end'] = out(np.array([[m.end() for m in ms]], F64)) if ms else np.zeros((1, 0))
        results['match'] = Cell.of_list([Char.of(m.group(0)) for m in ms]) if ms else Cell.empty((1, 0))
        results['tokens'] = Cell.of_list([tokens_of(m) for m in ms]) if ms else Cell.empty((1, 0))
        results['tokenextents'] = Cell.of_list([extents_of(m) for m in ms]) if ms else Cell.empty((1, 0))
        if rx.groupindex:
            if ms:
                st = Struct((1, len(ms)), {k: np.empty((1, len(ms)), object) for k in rx.groupindex})
                for i, m in enumerate(ms):
                    for k in rx.groupindex:
                        st.f[k][0, i] = Char.of(m.group(k) or '')
                results['names'] = st
            else:
                results['names'] = Struct.empty((0, 0), list(rx.groupindex))
        else:
            results['names'] = Struct.scalar({})
        results['split'] = split_parts()
    order = selected or ['start', 'end', 'tokenextents', 'match', 'tokens', 'names', 'split']
    if not selected:
        order = ['start', 'end', 'tokenextents', 'match', 'tokens', 'names', 'split']
    n = max(nargout, 1)
    vals = [results[k] for k in order[:n]]
    if len(vals) < n:
        # remaining outputs in the default order after the selected ones
        rest = [k for k in ['start', 'end', 'tokenextents', 'match', 'tokens', 'names', 'split'] if k not in order]
        vals += [results[k] for k in rest[:n - len(vals)]]
    return vals[0] if n == 1 else tuple(vals)


@bi('regexp', nout=7, arr=False)
def regexp(nargout, *args):
    return _regexp(args, nargout, False, 'regexp')


@bi('regexpi', nout=7, arr=False)
def regexpi(nargout, *args):
    return _regexp(args, nargout, True, 'regexpi')


@bi('regexprep')
def regexprep(nargout, *args):
    nargchk(args, 3, None, 'regexprep')
    v = args[0]
    pats = text_list(args[1])
    reps = text_list(args[2])
    opts = [opt_str(a).lower() for a in args[3:] if opt_str(a) is not None]
    once = 'once' in opts
    flags = _re_flags([o for o in opts if o != 'once'])
    if len(reps) == 1:
        reps = reps * len(pats)

    def f(s):
        if s is None:
            return None
        for p, r in zip(pats, reps):
            rx = re.compile(_py_pattern(p), flags)
            fr = _py_replacement(r)
            done = [0]

            def sub(m, fr=fr):
                # an empty match is left as it is unless 'emptymatch'; 'once' counts real replacements
                if (m.end() == m.start() and 'emptymatch' not in opts) or (once and done[0]):
                    return m.group(0)
                done[0] += 1
                return fr(m)
            s = rx.sub(sub, s)
        return s
    if type(v) is Char:
        return Char.of(f(v.str()))
    tin = _TextIn(v, 'regexprep')
    return tin.back([f(s) for s in tin.items])


_SYM_TOKEN = re.compile(r"'[^']*'|\"[^\"]*\"|(?<![\w.])\d+\.?\d*(?:[eEdD][+-]?\d+)?|(?<![\w.])\.\d+(?:[eEdD][+-]?\d+)?|[A-Za-z]\w*")
_SYM_SKIP = {'i', 'j', 'pi', 'Inf', 'inf', 'NaN', 'nan', 'eps'}


@bi('symvar')
def symvar(nargout, *args):
    """The variables an expression uses, sorted: its names other than i, j,
    pi, Inf, NaN, eps and the functions there are."""
    from .. import runtime as R
    nargchk(args, 1, 1, 'symvar')
    s = sval(args[0], 'expression', 'symvar')
    names = set()
    for m in _SYM_TOKEN.finditer(s):
        t = m.group(0)
        if not (t[0].isalpha()) or t in _SYM_SKIP or t in names:
            continue
        if R.resolve(t) is not None:
            continue        # a function (or a program file)
        names.add(t)
    found = sorted(names)
    return Cell.of_list([Char.of(n) for n in found], (len(found), 1)) if found else Cell.empty((0, 1))


@bi('regexptranslate')
def regexptranslate(nargout, *args):
    kind = py_str(args[0]).lower()
    s = py_str(args[1])
    if kind == 'escape':
        return Char.of(re.escape(s))
    if kind == 'wildcard':
        return Char.of(s.replace('.', r'\.').replace('*', '.*').replace('?', '.'))
    return Char.of(s)


@bi('sscanf', nout=4)
def sscanf(nargout, *args):
    nargchk(args, 2, 3, 'sscanf')
    s = py_str(args[0])
    fmt = py_str(args[1])
    from .iofun import scan_text
    vals, count, errmsg, nxt = scan_text(s, fmt, args[2] if len(args) > 2 else None)
    if nargout <= 1:
        return vals
    return (vals, float(count), Char.of(errmsg), float(nxt))[:nargout]


@bi('strmatch')
def strmatch(nargout, *args):
    nargchk(args, 2, 3, 'strmatch')
    s = py_str(args[0])
    a = args[1]
    if type(a) is Char:
        rows = a.row_strs() if a.a.shape[0] > 1 else [a.str()]
    else:
        rows = cellstr_list(a) if type(a) is Cell else [x or '' for x in to_str_array(a).a.reshape(-1, order='F')]
    exact = len(args) > 2 and sval(args[2], 'option', 'strmatch').lower() == 'exact'
    # rows of a char matrix are padded: trailing blanks and nulls never count
    hits = [i + 1.0 for i, r in enumerate(rows) if (r.rstrip(' \0') == s if exact else r.startswith(s))]
    return np.array(hits, float).reshape(-1, 1)
