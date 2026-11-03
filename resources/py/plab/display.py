"""How values are shown: `x = 5` without a semicolon, disp(x), and the short
forms used inside cells and structs.

The number formats follow the `format` command: short (4 decimals), long
(15), shortE/longE, shortG/longG, bank, rat, hex and +; loose or compact
spacing. Arrays wider than the Command Window are cut into column blocks.
"""
import math
import struct as _struct
import numpy as np

from .values import (Char, Cell, Struct, Str, FH, Obj, F64, C128, DTYPE_CLASS, INT_TYPES,
                     class_of, size_str, NOVAL, Sparse)

FMT = {'mode': 'short', 'spacing': 'loose', 'width': 80}

TIMES = '×'


def _isint_arr(a):
    with np.errstate(invalid='ignore'):
        return bool(np.all(a == np.round(a)))


def _special(x):
    if x != x:
        return 'NaN'
    return 'Inf' if x > 0 else '-Inf'


# ---- real numbers ------------------------------------------------------------

def _real_plan(A, mode):
    """For a real double array: (scale exponent or None, a function from a
    value to its text, the column width)."""
    fin = A[np.isfinite(A)]
    maxabs = float(np.max(np.abs(fin))) if fin.size else 0.0
    allint = fin.size == 0 or _isint_arr(fin)
    if mode in ('short', 'long'):
        if allint and maxabs < 1e9:
            if mode == 'short' or True:
                w = 6 if maxabs < 1000 else 12
                if any(x < 0 for x in fin.flat) and maxabs >= 1000:
                    w = max(w, len(str(int(maxabs))) + 3)
                return None, (lambda x: f'{int(x):d}' if math.isfinite(x) else _special(x)), w
        dec = 4 if mode == 'short' else 15
        scalar = A.size == 1
        if scalar:
            x = float(A.reshape(-1)[0])
            if not math.isfinite(x):
                return None, _special, 6
            ax = abs(x)
            if 1e-3 <= ax < 1e3 or ax == 0:
                if mode == 'long':
                    d = max(1, int(math.floor(math.log10(ax))) + 1) if ax >= 1 else 1
                    dec = 16 - d if ax >= 1 else 15
                return None, (lambda v, dec=dec: f'{v:.{dec}f}' if math.isfinite(v) else _special(v)), (10 if mode == 'short' else dec + 5)
            return None, (lambda v: f'{v:.{dec}e}' if math.isfinite(v) else _special(v)), dec + 9
        if maxabs == 0 or (1e-3 <= maxabs < 1e3):
            if mode == 'short':
                ip = len(str(int(maxabs))) if maxabs >= 1 else 1
                w = max(10, ip + 6 + (1 if np.any(fin < 0) else 0) + 1)
                return None, (lambda v: ('0' if v == 0 else f'{v:.4f}') if math.isfinite(v) else _special(v)), w
            ip = len(str(int(maxabs))) if maxabs >= 1 else 1
            d = 15 if maxabs < 10 else max(15 - (ip - 1), 1)
            w = ip + d + 5
            return None, (lambda v, d=d: ('0' if v == 0 else f'{v:.{d}f}') if math.isfinite(v) else _special(v)), w
        k = int(math.floor(math.log10(maxabs)))
        s = 10.0 ** k
        dec2 = 4 if mode == 'short' else 15
        w = 10 if mode == 'short' else 20
        return k, (lambda v, s=s, dec2=dec2: ('0' if v == 0 else f'{v / s:.{dec2}f}') if math.isfinite(v) else _special(v)), w
    if mode in ('shortE', 'longE'):
        dec = 4 if mode == 'shortE' else 15
        return None, (lambda v: f'{v:.{dec}e}' if math.isfinite(v) else _special(v)), dec + 9
    if mode in ('shortG', 'longG'):
        p = 5 if mode == 'shortG' else 15
        texts = [_g(float(v), p) for v in A.flat]
        w = max([len(t) for t in texts] + [1]) + 2
        w = max(w, 5 if mode == 'shortG' else 10) + 3
        return None, (lambda v: _g(v, p)), w
    if mode == 'bank':
        return None, (lambda v: f'{v:.2f}' if math.isfinite(v) else _special(v)), max(10, len(f'{maxabs:.2f}') + 4)
    if mode == 'rat':
        texts = [rat_text(float(v)) for v in A.flat]
        w = max([len(t) for t in texts] + [1]) + 3
        return None, rat_text, max(w, 6)
    if mode == 'hex':
        return None, (lambda v: _struct.pack('>d', v).hex()), 19
    if mode == '+':
        return None, (lambda v: '+' if v > 0 else ('-' if v < 0 else ' ')), 1
    return _real_plan(A, 'short')


def _g(v, p):
    if not math.isfinite(v):
        return _special(v)
    if v == int(v) and abs(v) < 10 ** p:
        return str(int(v))
    s = f'{v:.{p}g}'
    if 'e' in s:
        mant, ex = s.split('e')
        e = int(ex)
        s = f'{mant}e{"+" if e >= 0 else "-"}{abs(e):02d}'
    return s


def rat_text(x, tol=None):
    """A continued-fraction approximation, as `format rat` and rats show."""
    if not math.isfinite(x):
        return _special(x)
    if x == int(x):
        return str(int(x))
    if tol is None:
        tol = 1e-6 * abs(x) if x != 0 else 1e-6
    # expansion of x as [a0; a1, a2, ...]
    n0, d0, n1, d1 = 1, 0, 0, 1
    y = x
    for _ in range(20):
        a = math.floor(y) if y >= 0 else math.ceil(y) if False else math.floor(y + 0.5) if False else round(y)
        n0, n1 = a * n0 + n1, n0
        d0, d1 = a * d0 + d1, d0
        if d0 != 0 and abs(x - n0 / d0) < tol:
            break
        f = y - a
        if f == 0:
            break
        y = 1.0 / f
    if d0 < 0:
        n0, d0 = -n0, -d0
    if d0 == 1:
        return str(n0)
    return f'{n0}/{d0}'


def _wrap_columns(cols_text, w, width):
    """Cut a matrix's columns into blocks that fit the window: [(first,
    last, lines)]."""
    ncols = len(cols_text[0]) if cols_text else 0
    per = max(1, (width - 0) // max(w, 1))
    if ncols <= per:
        return [(0, ncols, cols_text)]
    blocks = []
    for c0 in range(0, ncols, per):
        c1 = min(ncols, c0 + per)
        blocks.append((c0, c1, [r[c0:c1] for r in cols_text]))
    return blocks


def _block_title(c0, c1, ncols):
    if c1 - c0 == 1:
        return f'  Column {c0 + 1}'
    if c1 == ncols:
        return f'  Columns {c0 + 1} through {c1}' if c1 - c0 > 1 else f'  Column {c1}'
    return f'  Columns {c0 + 1} through {c1}'


def real_matrix_lines(A, mode=None, width=None):
    """The lines of a real 2-D array (numbers in double)."""
    mode = mode or FMT['mode']
    width = width or FMT['width']
    A = np.asarray(A, F64)
    k, f, w = _real_plan(A, mode)
    rows, cols = A.shape
    cells = [[f(float(A[i, j])).rjust(w) for j in range(cols)] for i in range(rows)]
    head = []
    if k is not None:
        head = [f'   1.0e{"+" if k >= 0 else "-"}{abs(k):02d} *', '']
    return head, cells, w


def complex_matrix_lines(A, mode=None, width=None):
    mode = mode or FMT['mode']
    A = np.asarray(A, C128)
    re, im = A.real, A.imag
    allv = np.concatenate([re.reshape(-1), im.reshape(-1)])
    fin = allv[np.isfinite(allv)]
    maxabs = float(np.max(np.abs(fin))) if fin.size else 0.0
    allint = fin.size == 0 or _isint_arr(fin)
    k = None
    if mode in ('shortG', 'longG'):
        p = 5 if mode == 'shortG' else 15
        fr = lambda v: _g(v, p)
        fi = lambda v: _g(abs(v), p)
    elif mode in ('shortE', 'longE'):
        d = 4 if mode == 'shortE' else 15
        fr = lambda v: f'{v:.{d}e}' if math.isfinite(v) else _special(v)
        fi = lambda v: f'{abs(v):.{d}e}' if math.isfinite(v) else _special(abs(v))
    elif mode == 'rat':
        fr = rat_text
        fi = lambda v: rat_text(abs(v))
    else:
        d = 4 if mode in ('short', 'bank') else 15
        if mode == 'bank':
            d = 2
        if maxabs >= 1e3 or (0 < maxabs < 1e-3):
            if A.size == 1:
                fr = lambda v: f'{v:.{d}e}' if math.isfinite(v) else _special(v)
                fi = lambda v: f'{abs(v):.{d}e}' if math.isfinite(v) else _special(abs(v))
            else:
                k = int(math.floor(math.log10(maxabs)))
                s = 10.0 ** k
                fr = lambda v, s=s: f'{v / s:.{d}f}' if math.isfinite(v) else _special(v)
                fi = lambda v, s=s: f'{abs(v) / s:.{d}f}' if math.isfinite(v) else _special(abs(v))
        else:
            fr = lambda v: f'{v:.{d}f}' if math.isfinite(v) else _special(v)
            fi = lambda v: f'{abs(v):.{d}f}' if math.isfinite(v) else _special(abs(v))
    rtexts = [[fr(float(re[i, j])) for j in range(A.shape[1])] for i in range(A.shape[0])]
    itexts = [[fi(float(im[i, j])) for j in range(A.shape[1])] for i in range(A.shape[0])]
    wr = max([len(t) for r in rtexts for t in r] + [1]) + 3
    wi = max([len(t) for r in itexts for t in r] + [1])
    cells = []
    for i in range(A.shape[0]):
        row = []
        for j in range(A.shape[1]):
            sign = '-' if (im[i, j] < 0 or (im[i, j] == 0 and math.copysign(1, im[i, j]) < 0)) else '+'
            row.append(rtexts[i][j].rjust(wr) + f' {sign} ' + itexts[i][j].rjust(wi) + 'i')
        cells.append(row)
    head = []
    if k is not None:
        head = [f'   1.0e{"+" if k >= 0 else "-"}{abs(k):02d} *', '']
    return head, cells, wr + 3 + wi + 1


def int_matrix_lines(A):
    texts = [[str(int(A[i, j])) for j in range(A.shape[1])] for i in range(A.shape[0])]
    w = max([len(t) for r in texts for t in r] + [1]) + 3
    return [], [[t.rjust(w) for t in r] for r in texts], w


def logical_matrix_lines(A):
    texts = [['1' if A[i, j] else '0' for j in range(A.shape[1])] for i in range(A.shape[0])]
    return [], [[t.rjust(4) for t in r] for r in texts], 4


def matrix2d_lines(A, width=None):
    """The lines of a 2-D numeric or logical array, column blocks and all."""
    width = width or FMT['width']
    k = A.dtype.kind
    if k == 'b':
        head, cells, w = logical_matrix_lines(A)
    elif k in 'iu':
        head, cells, w = int_matrix_lines(A)
    elif k == 'c':
        head, cells, w = complex_matrix_lines(A)
    else:
        head, cells, w = real_matrix_lines(A)
    ncols = A.shape[1]
    blocks = _wrap_columns(cells, w, width)
    out = list(head)
    if len(blocks) == 1:
        out += [''.join(r) for r in cells]
        return out
    loose = FMT['spacing'] == 'loose'
    for bi, (c0, c1, rows) in enumerate(blocks):
        out.append(_block_title(c0, c1, ncols))
        if loose:
            out.append('')
        out += [''.join(r) for r in rows]
        if loose and bi < len(blocks) - 1:
            out.append('')
    return out


# ---- short forms in cells and structs -----------------------------------------

def _num_inline(v):
    """A number or small row as it reads inside a cell or struct."""
    a = np.asarray(v)
    if a.dtype.kind == 'b':
        return ' '.join('1' if x else '0' for x in a.reshape(-1))
    if a.dtype.kind in 'iu':
        return ' '.join(str(int(x)) for x in a.reshape(-1))
    if a.dtype.kind == 'c':
        parts = []
        for z in a.reshape(-1):
            parts.append(_inline_complex(complex(z)))
        return ' '.join(parts)
    vals = a.reshape(-1).astype(F64)
    fin = vals[np.isfinite(vals)]
    allint = fin.size == 0 or _isint_arr(fin)
    out = []
    mode = FMT['mode']
    for x in vals:
        x = float(x)
        if not math.isfinite(x):
            out.append(_special(x))
        elif (allint and abs(x) < 1e9) or x == 0:
            out.append(str(int(x)))
        elif mode in ('long', 'longG', 'longE'):
            out.append(_g(x, 15) if mode != 'longE' else f'{x:.15e}')
        else:
            ax = abs(x)
            if 1e-3 <= ax < 1e3:
                out.append(f'{x:.4f}')
            else:
                out.append(f'{x:.4e}')
    return ' '.join(out)


def _inline_complex(z):
    re, im = z.real, z.imag
    if re == int(re) and im == int(im) and abs(re) < 1e9 and abs(im) < 1e9:
        r, i = str(int(re)), str(int(abs(im)))
    else:
        r, i = f'{re:.4f}', f'{abs(im):.4f}'
    return f'{r}{"-" if im < 0 else "+"}{i}i'


def summary(v, brackets='[]'):
    """The short form of a value: 1, [1 2 3], [3×3 double], 'abc', {1×2
    cell}, [1×1 struct], @(x)x+1."""
    t = type(v)
    if t is float or t is bool or t is complex or (t is np.ndarray and v.size == 1 and v.ndim == 2):
        if brackets == '{}':
            return '[' + _num_inline(v) + ']'
        return _num_inline(v)
    if t is np.ndarray:
        cls = DTYPE_CLASS.get(v.dtype, 'double')
        if v.size == 0:
            if v.shape == (0, 0) and cls == 'double':
                return '[]'
            return f'{size_str(v.shape)} {cls}' if brackets == '{}' else f'[{size_str(v.shape)} {cls}]'
        if v.ndim == 2 and v.shape[0] == 1 and v.shape[1] <= 10:
            text = _num_inline(v)
            if len(text) < 60:
                return f'[{text}]'
        return f'{size_str(v.shape)} {cls}' if brackets == '{}' else f'[{size_str(v.shape)} {cls}]'
    if t is Char:
        if v.a.ndim == 2 and v.a.shape[0] == 1:
            return "'" + v.str().replace('\n', '↵') + "'"
        if v.a.size == 0:
            return "''" if v.a.shape == (0, 0) else f'{size_str(v.a.shape)} char'
        return f'{size_str(v.a.shape)} char' if brackets == '{}' else f'[{size_str(v.a.shape)} char]'
    if t is Str:
        if v.a.size == 1:
            s = v.a.flat[0]
            return '<missing>' if s is None else '"' + s + '"'
        return f'{size_str(v.a.shape)} string' if brackets == '{}' else f'[{size_str(v.a.shape)} string]'
    if t is Cell:
        if v.a.size == 0 and v.a.shape == (0, 0):
            return '{}' if brackets != '{}' else '0×0 cell'
        return f'{size_str(v.a.shape)} cell' if brackets == '{}' else '{' + f'{size_str(v.a.shape)} cell' + '}'
    if t is Struct:
        return f'{size_str(v.shape)} struct' if brackets == '{}' else f'[{size_str(v.shape)} struct]'
    if t is Sparse:
        text = f'{size_str(v.shape)} sparse {v.cls}'
        return text if brackets == '{}' else f'[{text}]'
    if isinstance(v, FH):
        return v.text()
    if isinstance(v, VOBJ):
        return v.summary_text(brackets)
    if isinstance(v, Obj):
        return f'{size_str(getattr(v, "shape", (1, 1)))} {v.cls}' if brackets == '{}' else f'[{size_str(getattr(v, "shape", (1, 1)))} {v.cls}]'
    return f'[1×1 {class_of(v)}]'


def cell_lines(c):
    """The rows of a cell array: {[1]}    {'abc'}"""
    a = c.a
    if a.ndim > 2:
        a = a.reshape(a.shape[0], -1, order='F')
    texts = [['{' + summary(a[i, j], '{}') + '}' for j in range(a.shape[1])] for i in range(a.shape[0])]
    widths = [max(len(texts[i][j]) for i in range(a.shape[0])) for j in range(a.shape[1])]
    lines = []
    for i in range(a.shape[0]):
        parts = []
        for j in range(a.shape[1]):
            parts.append(texts[i][j].ljust(widths[j]) if j < a.shape[1] - 1 else texts[i][j])
        lines.append('    ' + '    '.join(parts))
    return lines


def struct_field_lines(s, indent=4):
    names = list(s.f)
    if not names:
        return []
    w = max(len(n) for n in names)
    lines = []
    for n in names:
        v = s.f[n].reshape(-1)[0]
        lines.append(' ' * indent + n.rjust(w) + ': ' + summary(v))
    return lines


def _header_kind(shape):
    if len(shape) == 2:
        if shape[0] == 1 and shape[1] != 1:
            return 'row vector'
        if shape[1] == 1 and shape[0] != 1:
            return 'column vector'
        return 'matrix'
    return 'array'


def _empty_text(cls, shape):
    if len(shape) == 2:
        if shape[0] == 1:
            return f'{size_str(shape)} empty {cls} row vector'
        if shape[1] == 1:
            return f'{size_str(shape)} empty {cls} column vector'
        return f'{size_str(shape)} empty {cls} matrix'
    return f'{size_str(shape)} empty {cls} array'


def _nd_pages(shape):
    """The index tuples of the 2-D pages of an N-D array, in order."""
    rest = shape[2:]
    idx = [0] * len(rest)
    while True:
        yield tuple(idx)
        k = 0
        while k < len(rest):
            idx[k] += 1
            if idx[k] < rest[k]:
                break
            idx[k] = 0
            k += 1
        if k == len(rest):
            return


def body_lines(v):
    """The lines that show a value's contents (without its name line), and
    whether a header comes before them."""
    t = type(v)
    if t is float or t is complex:
        return matrix2d_lines(np.array([[v]], C128 if t is complex else F64))
    if t is bool:
        return ['  logical', '', '   ' + ('1' if v else '0')] if FMT['spacing'] == 'loose' else ['  logical', '   ' + ('1' if v else '0')]
    if t is np.ndarray:
        cls = DTYPE_CLASS.get(v.dtype, 'double')
        if v.size == 0:
            if v.shape == (0, 0) and cls == 'double':
                return ['     []']
            return ['  ' + _empty_text(cls, v.shape)]
        head = []
        if cls == 'logical' or cls in INT_TYPES:
            if v.size == 1:
                head = ['  ' + cls]
            else:
                kind = 'array' if cls == 'logical' else _header_kind(v.shape)
                head = [f'  {size_str(v.shape)} {cls} {kind}']
            if FMT['spacing'] == 'loose':
                head.append('')
        if v.ndim == 2:
            return head + matrix2d_lines(v if v.dtype.kind != 'f' or v.dtype == F64 else v.astype(F64))
        return head + ['__ND__']
    if t is Char:
        a = v.a
        if a.size == 0:
            return ['  ' + f'{size_str(a.shape)} empty char array']
        if a.ndim == 2 and a.shape[0] == 1:
            return ["    '" + v.str() + "'"]
        lines = [f'  {size_str(a.shape)} char array']
        if FMT['spacing'] == 'loose':
            lines.append('')
        if a.ndim == 2:
            lines += ["    '" + r + "'" for r in v.row_strs()]
        else:
            lines += ["    '" + r + "'" for r in v.row_strs()]
        return lines
    if t is Str:
        a = v.a
        if a.size == 1:
            s = a.flat[0]
            return ['    <missing>' if s is None else '    "' + s + '"']
        if a.size == 0:
            return ['  ' + _empty_text('string', a.shape).replace(' matrix', ' array')]
        lines = [f'  {size_str(a.shape)} string array']
        if FMT['spacing'] == 'loose':
            lines.append('')
        a2 = a if a.ndim == 2 else a.reshape(a.shape[0], -1, order='F')
        texts = [['<missing>' if x is None else '"' + x + '"' for x in row] for row in a2]
        widths = [max(len(texts[i][j]) for i in range(a2.shape[0])) for j in range(a2.shape[1])]
        for row in texts:
            lines.append('    ' + '    '.join(x.ljust(widths[j]) if j < len(row) - 1 else x for j, x in enumerate(row)))
        return lines
    if t is Cell:
        a = v.a
        if a.size == 0:
            return ['  ' + f'{size_str(a.shape)} empty cell array']
        lines = [f'  {size_str(a.shape)} cell array']
        if FMT['spacing'] == 'loose':
            lines.append('')
        lines += cell_lines(v)
        return lines
    if t is Struct:
        if v.shape == (1, 1):
            lines = ['  struct with fields:']
            if FMT['spacing'] == 'loose':
                lines.append('')
            fl = struct_field_lines(v)
            if not fl:
                lines = ['  struct with no fields.']
            return lines + fl
        if v.size == 0:
            lines = [f'  {size_str(v.shape)} empty struct array with fields:'] if v.f else [f'  {size_str(v.shape)} empty struct array with no fields.']
        else:
            lines = [f'  {size_str(v.shape)} struct array with fields:'] if v.f else [f'  {size_str(v.shape)} struct array with no fields.']
        if v.f:
            if FMT['spacing'] == 'loose':
                lines.append('')
            lines += ['    ' + n for n in v.f]
        return lines
    if isinstance(v, FH):
        lines = ['  function_handle with value:']
        if FMT['spacing'] == 'loose':
            lines.append('')
        lines.append('    ' + v.text())
        return lines
    if isinstance(v, Obj):
        return v.display_lines() if hasattr(v, 'display_lines') else ['  ' + v.cls]
    if v is NOVAL:
        return ['     []']
    return ['  ' + repr(v)]


class _NoSym:
    pass


VOBJ = _NoSym         # vobj.VObj (vobj.py sets it)
SYM = _NoSym          # symbolic.Sym (symbolic.py sets it)
SYMOPS = None


def display(name, v):
    """`name = value` as the Command Window shows it."""
    if type(v) is SYM:
        return SYMOPS.display(name, v)
    if type(v) is Sparse:
        from . import sparsemat
        return sparsemat.display(name, v)
    if getattr(v, 'custom_display', None) is not None:
        r = v.custom_display(name)
        if r is not None:
            return r
    loose = FMT['spacing'] == 'loose'
    t = type(v)
    if t is np.ndarray and v.ndim > 2 and v.size > 0:
        return _display_nd(name, v)
    if t in (Char, Cell, Str) and v.a.ndim > 2 and t is not Char and v.a.size > 0 and False:
        pass
    lines = body_lines(v)
    out = []
    eq = f'{name} =' if not (t is Struct or isinstance(v, (Obj, FH)) or t is Cell) else f'{name} = '
    out.append(eq)
    if loose:
        out.append('')
    out += lines
    if loose:
        out.append('')
    return '\n'.join(out) + '\n'


def _display_nd(name, v):
    loose = FMT['spacing'] == 'loose'
    out = []
    cls = DTYPE_CLASS.get(v.dtype, 'double')
    for page in _nd_pages(v.shape):
        sub = v[(slice(None), slice(None)) + page]
        label = f'{name}(:,:,' + ','.join(str(p + 1) for p in page) + ') ='
        out.append(label)
        if loose:
            out.append('')
        out += matrix2d_lines(sub if sub.dtype.kind != 'f' or sub.dtype == F64 else sub.astype(F64))
        if loose:
            out.append('')
            out.append('')
    if loose and out and out[-1] == '':
        out.pop()
    return '\n'.join(out) + '\n'


def disp_text(v):
    """What disp(v) prints."""
    t = type(v)
    if t is SYM:
        return SYMOPS.disp_text(v)
    if t is Sparse:
        from . import sparsemat
        return sparsemat.disp_text(v)
    if isinstance(v, VOBJ):
        lines = v.disp_lines()
        return '\n'.join(lines) + '\n' if lines else ''
    if t is Char:
        if v.a.size == 0:
            return ''
        return '\n'.join(v.row_strs()) + '\n'
    if t is Str:
        if v.a.size == 1:
            s = v.a.flat[0]
            return ('<missing>' if s is None else s) + '\n'
    if t is np.ndarray and v.size == 0:
        return ''
    if t is np.ndarray and v.ndim > 2:
        text = _display_nd('ans', v)
        return '\n'.join(line for line in text.split('\n') if not line.startswith('ans(')) if False else text.replace('ans(', '(')
    if t is bool:
        return '   ' + ('1' if v else '0') + '\n'
    if t is np.ndarray and (v.dtype.kind == 'b' or v.dtype.kind in 'iu'):
        return '\n'.join(matrix2d_lines(v)) + '\n'
    if t is Cell and v.a.size == 0:
        return ''
    if t is Struct and v.shape == (1, 1):
        return '\n'.join(struct_field_lines(v)) + '\n'
    if t is Cell:
        return '\n'.join(cell_lines(v)) + '\n'
    lines = body_lines(v)
    if t is Str and v.a.size > 1:
        lines = [l for l in lines[1:] if l != ''] if lines and 'string array' in lines[0] else lines
    if isinstance(v, FH):
        return '    ' + v.text() + '\n'
    return '\n'.join(lines) + '\n'


def size_class_text(v):
    """'1×3 double' and the like (Workspace's Size and Class columns)."""
    from .values import shape_of
    return size_str(shape_of(v)), class_of(v)


def value_preview(v, limit=60):
    """The Value column of the Workspace: the value itself when short."""
    t = type(v)
    if t is float or t is bool or t is complex:
        s = _num_inline(v)
        return s
    if t is Sparse:
        return f'{size_str(v.shape)} sparse {v.cls}'
    if t is np.ndarray:
        if v.size == 0:
            return '[]' if v.shape == (0, 0) else f'{size_str(v.shape)} {class_of(v)}'
        if v.size == 1:
            return _num_inline(v)
        if v.ndim == 2 and v.size <= 12:
            rows = []
            for i in range(v.shape[0]):
                rows.append(','.join(_num_inline(v[i, j:j + 1]) for j in range(v.shape[1])))
            s = '[' + ';'.join(rows) + ']'
            if len(s) <= limit:
                return s
        return f'{size_str(v.shape)} {class_of(v)}'
    s = summary(v)
    if len(s) > limit:
        s = s[:limit - 1] + '…'
    return s
