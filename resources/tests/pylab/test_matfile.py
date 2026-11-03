"""MAT-files read by load (resources/py/plab/matfile.py): each layout the
reader knows, in files this script writes, and the same values back through
save.

    python3 test_matfile.py      (from any folder; needs numpy, scipy and h5py)

The files come from SciPy's writer (Level 4 and Level 5), from h5py in the
layout of version 7.3 files as the open-source readers document it, and from
data elements written out (matfixtures.py: text in UTF-8, UTF-16 and UTF-32,
big-endian files, small elements, logical sparse matrices, objects, function
handles, string arrays kept as objects in the file's subsystem, damaged and
hostile files). Each case loads a file with the
language's own commands and checks the variables, their classes and the
warnings.
"""
import asyncio
import json
import math
import os
import shutil
import struct
import sys
import tempfile
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab import matfile as MF  # noqa: E402
from plab import worker_api  # noqa: E402
from plab.values import Char, Cell, Struct, Str, FH, Sparse, class_of  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-matfile-')
R.STATE['cwd'] = TMP

failed = []
checks = [0]


def check(label, ok, detail=''):
    checks[0] += 1
    if not ok:
        failed.append(label)
        print(f'FAIL  {label}  {detail}')


def run(code):
    """Run code in a fresh base workspace: (workspace, output text)."""
    R.BASE.clear()
    R.BASE.gnames.clear()
    R.take_output()
    asyncio.run(R.execute(code))
    return R.BASE, R.take_output()


def val(v):
    """A plain Python form of a value for comparing."""
    t = type(v)
    if t is float or t is bool or t is complex:
        return v
    if t is np.ndarray:
        if v.size == 1 and v.ndim == 2:
            return v.reshape(-1)[0].item()
        return v.tolist()
    if t is Sparse:
        return v.dense().tolist()
    if t is Char:
        return v.str() if v.a.shape[0] <= 1 else v.row_strs()
    if t is Str:
        return [s for s in v.a.reshape(-1, order='F')] if v.a.size != 1 else v.a.flat[0]
    if t is Cell:
        return [val(x) for x in v.a.reshape(-1, order='F')]
    if t is Struct:
        if v.size == 1:
            return {k: val(v.get1(k)) for k in v.f}
        return [{k: val(a.reshape(-1, order='F')[i]) for k, a in v.f.items()} for i in range(v.size)]
    return v


def same(a, b):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return list(a) == list(b) and all(same(a[k], b[k]) for k in a)
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


def case(label, code, want=None, cls=None, shape=None, shows=(), hides=(), error=None, absent=()):
    try:
        W, out = run(code)
    except Exception as e:  # noqa: BLE001 -- a crash is a failure, with its reason
        check(label, False, f'raised {type(e).__name__}: {e}')
        return None
    if error is not None:
        check(f'{label}: error', error in out, repr(out))
        return W
    if 'Error' in out:
        check(f'{label}: no error', False, repr(out))
    for name, w in (want or {}).items():
        got = val(W[name]) if name in W else '(none)'
        check(f'{label}: {name}', same(got, w), f'got {got!r}, want {w!r}')
    for name, c in (cls or {}).items():
        got = class_of(W[name]) if name in W else '(none)'
        check(f'{label}: class({name})', got == c, f'got {got}, want {c}')
    for name, s in (shape or {}).items():
        got = tuple(getattr(W[name], 'shape', (1, 1))) if name in W else None
        check(f'{label}: size({name})', got == s, f'got {got}, want {s}')
    for s in shows:
        check(f'{label}: shows {s[:50]!r}', s in out, repr(out))
    for s in hides:
        check(f'{label}: does not show {s[:50]!r}', s not in out, repr(out))
    for name in absent:
        check(f'{label}: no {name}', name not in W)
    return W


def path(name):
    return os.path.join(TMP, name)


# ---- Level 5 written element by element ------------------------------------------------------------

from matfixtures import el, matrix, double, chars, struct1, compressed, header, strings_v5, strings_v73  # noqa: E402


def write(name, data):
    with open(path(name), 'wb') as f:
        f.write(data)


EMOJI = '\U0001F600'
u16 = 'Ångström µ ✓ δ ' + EMOJI
units32 = np.frombuffer(('a' + EMOJI + 'b').encode('utf-32-le'), '<u4')


def fhandle(name, text, kind, workspace=None):
    """A function handle as a struct describing it, with the captured values (name, element) if any."""
    fields = [('function', chars('', text)), ('type', chars('', kind)), ('file', chars('', ''))]
    if workspace:
        fields.append(('workspace', struct1('', workspace)))
    return matrix(16, (1, 1), name, [struct1('', [('function_handle', struct1('', fields))])])


deep = double('', 7)
for _ in range(70):
    deep = matrix(1, (1, 1), '', [deep])

hand = header() + b''.join([
    matrix(4, (1, len(u16.encode('utf-16-le')) // 2), 'u16', [el(17, u16.encode('utf-16-le'))]),
    matrix(4, (1, 4), 'u32', [el(18, units32.tobytes())]),
    matrix(4, (1, 3), 'u8', [el(16, ('x' + EMOJI).encode('utf-8'))]),
    matrix(4, (2, 2), 'cm', [el(4, np.array([ord(c) for c in 'acbd'], '<u2').tobytes())]),
    matrix(6, (1, 1), 'smalld', [el(2, bytes([7]))]),
    matrix(5, (3, 2), 'lsp', [el(5, np.array([0, 2], '<i4').tobytes()), el(5, np.array([0, 1, 2], '<i4').tobytes()),
                              el(2, bytes([1, 1]))], flags=0x200),
    matrix(2, (0, 0), 'es', [el(5, struct.pack('<i', 32)), el(1, b'a'.ljust(32, b'\0') + b'b'.ljust(32, b'\0'))]),
    matrix(3, (1, 1), 'obj', [el(1, b'myclass'), el(5, struct.pack('<i', 32)), el(1, b'v'.ljust(32, b'\0')), double('', 5)]),
    fhandle('fh', 'sin', 'simple'),
    fhandle('fa', '@(x)x.^2+1', 'anonymous'),
    fhandle('fw', '@(x)x+a', 'anonymous', [('a', double('', 3))]),
    matrix(8, (1, 2), 'ci', [el(1, bytes([1, 2])), el(1, bytes([3, 4]))], flags=0x800),
    matrix(17, None, 'str', [el(1, b'MCOS'), el(1, b'string'), matrix(13, (1, 6), '', [el(6, np.arange(6, dtype='<u4').tobytes())])]),
    matrix(1, (1, 1), 'deep', [deep]),
    matrix(5, (100000, 100000), 'bigsp', [el(5, np.array([0], '<i4').tobytes()), el(5, np.r_[0, np.ones(100000)].astype('<i4').tobytes()),
                                          el(9, np.array([1.0]).tobytes())]),
    double('after', 42),
])
write('hand.mat', hand)

case('Level 5 text in every encoding', "load('hand.mat', 'u*', 'cm', 'smalld')",
     want={'u16': u16, 'u32': 'a' + EMOJI + 'b', 'u8': 'x' + EMOJI, 'cm': ['ab', 'cd'], 'smalld': 7.0},
     cls={'u16': 'char', 'smalld': 'double'}, shape={'u32': (1, 4), 'u8': (1, 3), 'cm': (2, 2)})
case('a logical sparse matrix', "load('hand.mat', 'lsp'); k = issparse(lsp);", want={'lsp': [[True, False], [False, False], [False, True]], 'k': True},
     cls={'lsp': 'logical'})
case('a sparse matrix too large to hold full stays sparse', "load('hand.mat', 'bigsp'); k = issparse(bigsp); n = nnz(bigsp); s = size(bigsp); v = bigsp(1, 1);",
     want={'k': True, 'n': 1.0, 's': [[100000.0, 100000.0]]}, hides=['Warning'])
case('an empty struct keeps its fields', "load('hand.mat', 'es'); f = fieldnames(es)'; n = numel(es);", want={'f': ['a', 'b'], 'n': 0.0},
     cls={'es': 'struct'})
case('an old-style object loads as a struct, with a warning', "load('hand.mat', 'obj'); v = obj.v;", want={'v': 5.0},
     shows=["Warning: Variable 'obj' was loaded, but it was saved as an object of class 'myclass' and is now a struct."])
case('function handles', "load('hand.mat', 'f*'); a = fh(0); b = fa(2); c = fw(1); t = func2str(fa);",
     want={'a': 0.0, 'b': 5.0, 'c': 4.0, 't': '@(x)x.^2+1'}, cls={'fh': 'function_handle'})
case('a complex integer keeps its real part', "load('hand.mat', 'ci')", want={'ci': [[1, 2]]}, cls={'ci': 'int8'},
     shows=["Warning: Variable 'ci' was loaded, but its imaginary part was left out"])
W = case('variables that cannot be read are left out, the rest load', "load('hand.mat')",
         want={'after': 42.0, 'u8': 'x' + EMOJI},
         shows=["Warning: Variable 'str' was not loaded: its text is kept in the file's object data, which the file does not have.",
                "Warning: Variable 'deep' was not loaded: its cells and structs are nested too deeply."])
check('the unreadable variables are absent', W is not None and not ({'str', 'deep'} & set(W.keys())))
case('S = load(...) gives a struct of the variables', "S = load('hand.mat', 'after', 'cm'); f = fieldnames(S)'; a = S.after;",
     want={'f': ['cm', 'after'], 'a': 42.0}, hides=['Warning'])
case('a name not in the file is warned about', "load('hand.mat', 'after', 'nosuch')", want={'after': 42.0},
     shows=["Warning: Variable 'nosuch' not found."])
case('command syntax', 'load hand.mat after', want={'after': 42.0})

# big-endian, compressed and not
be = header('>') + double('m', [[1, 2, 3], [4, 5, 6]], '>') + matrix(10, (1, 2), 'k', [el(3, np.array([1, -2], '>i2').tobytes(), '>')], o='>') \
    + struct1('s', [('a', chars('', 'hé', '>'))], '>') + compressed(double('z', [1, 2, 3], '>'), '>')
be = be.replace(struct1('s', [('a', chars('', 'hé', '>'))], '>'), matrix(2, (1, 1), 's', [
    el(5, struct.pack('>i', 32), '>'), el(1, b'a'.ljust(32, b'\0'), '>'), chars('', 'hé', '>')], o='>'))
write('be.mat', be)
case('a big-endian Level 5 file', "load('be.mat'); a = s.a;", want={'m': [[1, 2, 3], [4, 5, 6]], 'k': [[1, -2]], 'a': 'hé', 'z': [[1, 2, 3]]},
     cls={'k': 'int16'})

# the subsystem's element (named by the header's offset) is no variable
body = double('v', 1)
sub = matrix(9, (1, 4), '', [el(2, bytes([1, 2, 3, 4]))])
write('subsys.mat', header(sub=128 + len(body)) + body + sub)
case('the subsystem data is not a variable', "load('subsys.mat'); n = numel(who);", want={'v': 1.0, 'n': 1.0}, hides=['Warning'])

# damaged and hostile files
two = header() + compressed(double('a', [1, 2, 3])) + compressed(double('b', [4, 5, 6]))
write('cut.mat', two[:len(two) - 10])
case('a file cut short loads what comes before the cut', "load('cut.mat')", want={'a': [[1, 2, 3]]},
     shows=['Warning: Part of cut.mat could not be read: the rest of the file is damaged.'])
rng = np.random.default_rng(1)
big = rng.random(5000)
z = zlib.compress(double('b', big))
bad = bytearray(header() + compressed(double('a', [1, 2, 3])) + compressed(double('b', big)) + compressed(double('c', 9)))
at = 128 + 8 + len(zlib.compress(double('a', [1, 2, 3]))) + 8 + 30000
bad[at:at + 16] = bytes(16)
write('corrupt.mat', bytes(bad))
case('damaged compressed data spoils one variable only', "load('corrupt.mat')", want={'a': [[1, 2, 3]], 'c': 9.0},
     shows=["Warning: Variable 'b' was not loaded: its compressed data is damaged."])
bad[128 + 8 + 2:128 + 8 + 10] = b'\xff' * 8
write('corrupt2.mat', bytes(bad))
case('a variable whose name cannot be read', "load('corrupt2.mat')", want={'c': 9.0},
     shows=['Warning: Part of corrupt2.mat could not be read: its compressed data is damaged.'])
write('notmat.mat', b'hello, this is text and not a MAT-file\n' * 10)
case('a text file named .mat is refused', "load('notmat.mat')", error='is not a MAT-file')
write('empty.mat', b'')
case('an empty file is refused', "load('empty.mat')", error='the file is empty')
write('bomb.mat', header() + compressed(matrix(9, (1, 3_000_000), 'big', [el(2, bytes(3_000_000))])) + double('ok', 1))
MF.INFLATE_LIMIT, kept = 1 << 20, MF.INFLATE_LIMIT
case('inflating stops at the limit', "load('bomb.mat')", want={'ok': 1.0},
     shows=["Warning: Variable 'big' was not loaded: it is larger than 1 GB once uncompressed."])
MF.INFLATE_LIMIT = kept
lie = header() + matrix(6, (1000, 1000), 'lie', [el(9, np.array([1.0, 2.0]).tobytes())]) + double('ok', 1)
write('lie.mat', lie)
case('a size the data does not have', "load('lie.mat')", want={'ok': 1.0},
     shows=["Warning: Variable 'lie' was not loaded: its data does not match its size."])

# names from a file never become code: a variable or a field whose name is not a name is left out,
# and a function handle's text must be one anonymous function
names = header() + b''.join([
    double("a;disp(66)", 1), double('\x01', 2), double('fine', 3),
    struct1('st', [('ok', double('', 4)), ("b;disp(77)", double('', 5))]),
    fhandle('evil', '@(x)x; disp(99)', 'anonymous'),
])
write('names.mat', names)
W = case('names that are not names are left out', "load('names.mat'); k = fieldnames(st)'; o = st.ok;",
         want={'fine': 3.0, 'k': ['ok'], 'o': 4.0},
         shows=["Warning: Variable 'a;disp(66)' was not loaded: its name is not a valid variable name.",
                "Warning: Variable '?' was not loaded: its name is not a valid variable name.",
                "Warning: Variable 'st' was loaded, but its field 'b;disp(77)' was left out (not a valid field name).",
                "Warning: Variable 'evil' was not loaded: its function handle does not compile here (Invalid anonymous function: @(x)x; disp(99))."],
         hides=['    66\n', '    77\n', '    99\n'])
if W is not None:
    check('no variable with a name that is not a name', sorted(W.keys()), ['fine', 'k', 'o', 'st'])
write('v4names.mat', struct.pack('<5i', 0, 1, 1, 0, 4) + b'a b\0' + np.array([1.0]).tobytes() + struct.pack('<5i', 0, 1, 1, 0, 2) + b'c\0' + np.array([2.0]).tobytes())
case('a Level 4 name that is not a name', "load('v4names.mat')", want={'c': 2.0},
     shows=["Warning: Variable 'a b' was not loaded: its name is not a valid variable name."])

# ---- Level 4 -------------------------------------------------------------------------------------
import scipy.io as sio  # noqa: E402
import scipy.sparse as sps  # noqa: E402

sio.savemat(path('v4.mat'), {'m': np.arange(6.).reshape(2, 3), 'c': np.array([[1 + 2j, 3]]),
                             'sp': sps.csc_matrix(np.array([[0., 1.], [2., 0.]])), 't': np.array(['ab', 'cd'])}, format='4')
case('Level 4 from SciPy', "load('v4.mat')", want={'m': [[0, 1, 2], [3, 4, 5]], 'c': [[1 + 2j, 3]], 'sp': [[0, 1], [2, 0]], 't': ['ab', 'cd']},
     cls={'t': 'char', 'sp': 'double'})
v4be = struct.pack('>5i', 1000, 1, 2, 0, 2) + b'x\0' + np.array([1.5, 2.5], '>f8').tobytes()
write('v4be.mat', v4be)
case('a big-endian Level 4 file', "load('v4be.mat')", want={'x': [[1.5, 2.5]]})
write('v4cut.mat', v4be + struct.pack('<5i', 0, 3, 3, 0, 2) + b'y\0' + b'\0' * 20)
case('a Level 4 file cut short', "load('v4cut.mat')", want={'x': [[1.5, 2.5]]},
     shows=["Warning: Variable 'y' was not loaded: the file ends inside it."])

# ---- Level 5 from SciPy ----------------------------------------------------------------------------
sa = np.zeros((1, 3), dtype=[('x', object), ('y', object)])
sa[0, 0] = (1.0, 'p')
sa[0, 1] = (np.array([[1., 2.]]), 'q')
sa[0, 2] = ('three', 'r')
scipy_vars = {
    'd3': np.arange(24.).reshape(2, 3, 4, order='F'), 'z': np.array([[1 + 2j, 3 - 4j]]),
    'i8': np.array([[-128, 127]], np.int8), 'u64': np.array([[2**64 - 1, 2**53 + 1]], np.uint64),
    'i64': np.array([[-2**63, 2**63 - 1]], np.int64), 's': np.array([[1.5, 2.5]], np.float32),
    'lg': np.array([[True, False], [False, True]]), 'chm': np.array(['abc', 'def']), 'emo': 'smile ' + EMOJI,
    'cel': np.array([[1.0, 'two', np.array([[3., 4.]])]], dtype=object), 'st': {'a': 1.0, 'b': 'text', 'c': {'n': np.eye(2)}},
    'sp': sps.csc_matrix(np.array([[1., 0, 0], [0, 0, 2], [3, 0, 0]])), 'spz': sps.csc_matrix(np.array([[1 + 1j, 0], [0, 2]])),
    'empty': np.zeros((0, 3)), 'sa': sa,
}
for comp in (False, True):
    name = f'scipy{"7" if comp else "6"}.mat'
    sio.savemat(path(name), scipy_vars, do_compression=comp)
    case(f'Level 5 from SciPy ({"compressed" if comp else "not compressed"})',
         f"load('{name}'); d = d3(2, 3, 4); n = st.c.n; c2 = cel{{2}}; x2 = sa(2).x; y3 = sa(3).y; k = [issparse(sp) issparse(spz)];",
         want={'k': [[True, True]], 'd': 23.0, 'z': [[1 + 2j, 3 - 4j]], 'i8': [[-128, 127]], 'u64': [[2**64 - 1, 2**53 + 1]], 'i64': [[-2**63, 2**63 - 1]],
               's': [[1.5, 2.5]], 'lg': [[True, False], [False, True]], 'chm': ['abc', 'def'], 'emo': 'smile ' + EMOJI,
               'n': [[1, 0], [0, 1]], 'c2': 'two', 'sp': [[1, 0, 0], [0, 0, 2], [3, 0, 0]], 'spz': [[1 + 1j, 0], [0, 2]],
               'x2': [[1, 2]], 'y3': 'r'},
         cls={'i8': 'int8', 'u64': 'uint64', 'i64': 'int64', 's': 'single', 'lg': 'logical', 'cel': 'cell', 'st': 'struct', 'sa': 'struct'},
         shape={'d3': (2, 3, 4), 'empty': (0, 3), 'sa': (1, 3), 'emo': (1, 8)}, hides=['Warning'])

# ---- version 7.3 (HDF5) ----------------------------------------------------------------------------
import h5py  # noqa: E402


def h5matfile(name, build):
    with h5py.File(path(name), 'w', userblock_size=512) as f:
        build(f)
    with open(path(name), 'r+b') as fh:
        fh.write(b'MATLAB 7.3 MAT-file, written by test_matfile.py'.ljust(116, b' ') + b'\0' * 8 + struct.pack('<H', 0x0200) + b'IM')


def put(g, name, a, cls, **attrs):
    """MATLAB's array a (in its own shape) as a dataset: HDF5 keeps the dimensions reversed."""
    ds = g.create_dataset(name, data=np.asarray(a).T)
    ds.attrs['MATLAB_class'] = np.bytes_(cls)
    for k, v in attrs.items():
        ds.attrs[k] = v
    return ds


def fields_attr(g, names):
    dt = h5py.vlen_dtype(np.dtype('S1'))
    data = np.empty(len(names), object)
    for i, n in enumerate(names):
        data[i] = np.array([bytes([c]) for c in n.encode()], dtype='S1')
    g.attrs.create('MATLAB_fields', data=data, dtype=dt)


def build73(f):
    refs = f.create_group('#refs#')
    put(f, 'd', [[1, 2, 3], [4, 5, 6]], 'double')
    z = np.zeros((1, 2), dtype=[('real', '<f8'), ('imag', '<f8')])
    z['real'], z['imag'] = [1, 3], [2, -4]
    put(f, 'z', z, 'double')
    put(f, 'c', np.frombuffer(('hé' + EMOJI).encode('utf-16-le', 'surrogatepass'), '<u2').reshape(1, -1), 'char', MATLAB_int_decode=np.int32(2))
    put(f, 'l', np.array([[1, 0], [0, 1]], np.uint8), 'logical', MATLAB_int_decode=np.int32(1))
    put(f, 'i', np.array([[1, -2]], np.int8), 'int8')
    put(f, 'u64', np.array([[2**64 - 1]], np.uint64), 'uint64')
    put(f, 's1', np.array([[0.5]], np.float32), 'single')
    put(f, 'nd', np.arange(24.).reshape(2, 3, 4, order='F'), 'double')
    e = f.create_dataset('e', data=np.array([0, 3], np.uint64))
    e.attrs['MATLAB_class'] = np.bytes_('double')
    e.attrs['MATLAB_empty'] = np.uint8(1)
    ec = f.create_dataset('ec', data=np.array([0, 0], np.uint64))
    ec.attrs['MATLAB_class'] = np.bytes_('char')
    ec.attrs['MATLAB_empty'] = np.uint8(1)
    a = put(refs, 'a', [[5.0]], 'double')
    b = put(refs, 'b', np.array([[ord('x')]], np.uint16), 'char')
    cel = f.create_dataset('cel', data=np.array([[a.ref], [b.ref]], dtype=h5py.ref_dtype))
    cel.attrs['MATLAB_class'] = np.bytes_('cell')
    st = f.create_group('st')
    st.attrs['MATLAB_class'] = np.bytes_('struct')
    fields_attr(st, ['b', 'a'])
    put(st, 'a', [[1.0]], 'double')
    put(st, 'b', np.array([[ord(ch) for ch in 'txt']], np.uint16), 'char')
    sa = f.create_group('sa')
    sa.attrs['MATLAB_class'] = np.bytes_('struct')
    fields_attr(sa, ['x'])
    x1 = put(refs, 'x1', [[1.0]], 'double')
    x2 = put(refs, 'x2', np.array([[ord(ch) for ch in 'two']], np.uint16), 'char')
    x3 = put(refs, 'x3', [[3.0, 4.0]], 'double')
    sa.create_dataset('x', data=np.array([[x1.ref], [x2.ref], [x3.ref]], dtype=h5py.ref_dtype))
    sp = f.create_group('sp')
    sp.attrs['MATLAB_class'] = np.bytes_('double')
    sp.attrs['MATLAB_sparse'] = np.uint64(3)
    sp.create_dataset('data', data=np.array([1.0, 3.0, 2.0]))
    sp.create_dataset('ir', data=np.array([0, 2, 1], np.uint64))
    sp.create_dataset('jc', data=np.array([0, 2, 2, 3], np.uint64))
    s = f.create_dataset('str', data=np.arange(6, dtype=np.uint32).reshape(6, 1))
    s.attrs['MATLAB_class'] = np.bytes_('string')
    s.attrs['MATLAB_object_decode'] = np.int32(3)
    fhg = f.create_group('fh')
    fhg.attrs['MATLAB_class'] = np.bytes_('function_handle')
    f.create_dataset('plain', data=np.array([1, 2, 3], np.float32))


h5matfile('v73.mat', build73)


def build73names(f):
    put(f, 'bad name', [[1.0]], 'double')
    put(f, 'good', [[2.0]], 'double')
    g = f.create_group('st')
    g.attrs['MATLAB_class'] = np.bytes_('struct')
    put(g, 'x y', [[3.0]], 'double')
    put(g, 'z', [[4.0]], 'double')


h5matfile('v73names.mat', build73names)
case('version 7.3 names that are not names', "load('v73names.mat'); k = fieldnames(st)';", want={'good': 2.0, 'k': ['z']},
     shows=["Warning: Variable 'bad name' was not loaded: its name is not a valid variable name.",
            "Warning: Variable 'st' was loaded, but its field 'x y' was left out (not a valid field name)."])
W = case('version 7.3 (HDF5)', "load('v73.mat'); c1 = cel{1}; c2 = cel{2}; sb = st.b; x2 = sa(2).x; x3 = sa(3).x; f = fieldnames(st)'; k = issparse(sp);",
         want={'k': True, 'd': [[1, 2, 3], [4, 5, 6]], 'z': [[1 + 2j, 3 - 4j]], 'c': 'hé' + EMOJI, 'l': [[True, False], [False, True]],
               'i': [[1, -2]], 'u64': 2**64 - 1, 's1': 0.5, 'c1': 5.0, 'c2': 'x', 'sb': 'txt', 'x2': 'two', 'x3': [[3, 4]],
               'sp': [[1, 0, 0], [0, 0, 2], [3, 0, 0]], 'plain': [[1, 2, 3]], 'f': ['b', 'a']},
         cls={'c': 'char', 'l': 'logical', 'i': 'int8', 'u64': 'uint64', 's1': 'single', 'e': 'double', 'ec': 'char',
              'sa': 'struct', 'plain': 'single'},
         shape={'nd': (2, 3, 4), 'e': (0, 3), 'ec': (0, 0), 'sa': (1, 3), 'cel': (1, 2)},
         shows=["Warning: Variable 'str' was not loaded: its text is kept in the file's object data, which the file does not have.",
                "Warning: Variable 'fh' was not loaded: it is a function handle"])
if W is not None:
    check('version 7.3: an N-D array keeps its order', val(W['nd'])[1][2][3] == 23.0, val(W['nd']))

# ---- string arrays: objects whose text is in the file's object data (its subsystem) ---------------------
S = lambda rows: np.array(rows, dtype=object)  # noqa: E731 -- a string array in MATLAB's shape; None is <missing>
STRINGS = {'hello': S([['hello']]), 'arr': S([['alpha', 'beta'], ['gamma', 'δέλτα ' + EMOJI]]),
           'gaps': S([[None, 'x', '']]), 'none': np.empty((0, 3), object), 'num': 4.0}
WANT = {'hello': 'hello', 'g21': 'gamma', 'g22': 'δέλτα ' + EMOJI, 'gaps': [None, 'x', ''], 'n': 0.0, 'num': 4.0,
        'm': [[True, False, False]], 'k': 'x'}
LOOK = "g21 = arr(2, 1); g22 = arr(2, 2); n = numel(none); m = ismissing(gaps); k = gaps(2);"
for label, name, data in (('Level 5', 'str5.mat', strings_v5(STRINGS)),
                          ('Level 5 compressed', 'str5z.mat', strings_v5(STRINGS, compress=True)),
                          ('Level 5 big-endian', 'str5be.mat', strings_v5(STRINGS, order='>'))):
    write(name, data)
    case(f'string arrays ({label})', f"load('{name}'); {LOOK}", want=WANT,
         cls={'hello': 'string', 'arr': 'string', 'gaps': 'string', 'none': 'string', 'k': 'string'},
         shape={'arr': (2, 2), 'gaps': (1, 3), 'none': (0, 3)}, hides=['Warning'])
strings_v73(path('str73.mat'), STRINGS)
case('string arrays (version 7.3)', f"load('str73.mat'); {LOOK}", want=WANT,
     cls={'hello': 'string', 'arr': 'string', 'none': 'string'}, shape={'arr': (2, 2), 'none': (0, 3)}, hides=['Warning'])
write('strcell.mat', strings_v5({'c': ('cell', [S([['in a cell']]), 5.0, S([['b', 'c']])])}))
case('string arrays in a cell', "load('strcell.mat'); a = c{1}; b = c{3}; k = class(c{1});",
     want={'a': 'in a cell', 'b': ['b', 'c'], 'k': 'string'}, hides=['Warning'])
case('a string array shows as one', "load('str5.mat'); arr", shows=['arr =\n\n  2×2 string array\n'], absent=['ans'])

# damaged object data leaves the strings out, never the rest
bad_any = np.frombuffer(np.array([1, 2, 1, 1, 50], np.uint64).tobytes() + 'short'.encode('utf-16-le').ljust(16, b'\0'), '<u8')
write('strbad.mat', strings_v5({'ok': S([['fine']]), 'bad': ('any', bad_any), 'num': 3.0}))
case('a string whose text is cut short', "load('strbad.mat')", want={'ok': 'fine', 'num': 3.0},
     shows=["Warning: Variable 'bad' was not loaded: its text is damaged (shorter than its lengths)."])
data = bytearray(strings_v5({'s': S([['x']]), 'num': 3.0}))
at = data.index(struct.pack('<2i', 4, 2))      # the metadata's version
data[at:at + 4] = struct.pack('<i', 9)
write('strversion.mat', bytes(data))
case('object data of a version not known here', "load('strversion.mat')", want={'num': 3.0},
     shows=["Warning: Variable 's' was not loaded: its text is kept in the file's object data, which could not be read "
            "(its version (9) is not known here)."])
data = bytearray(strings_v5({'s': S([['x']]), 'num': 3.0}))
at = data.index(np.array([0xDD000000, 2, 1, 1, 1, 1], '<u4').tobytes())
data[at + 16:at + 20] = struct.pack('<I', 77)  # an object that is not there
write('strobject.mat', bytes(data))
case('a reference to an object that is not there', "load('strobject.mat')", want={'num': 3.0},
     shows=["Warning: Variable 's' was not loaded: it is damaged (an object that is not there)."])

# ---- the Details panel's list, from the headers -----------------------------------------------------
for name, want in (('v4.mat', {'m': ('2×3', 'double'), 'sp': ('2×2', 'double'), 't': ('2×2', 'char')}),
                   ('scipy7.mat', {'d3': ('2×3×4', 'double'), 'lg': ('2×2', 'logical'), 'sa': ('1×3', 'struct'), 'sp': ('3×3', 'double')}),
                   ('hand.mat', {'str': ('', 'string'), 'fh': ('1×1', 'function_handle'), 'obj': ('1×1', 'myclass'), 'es': ('0×0', 'struct')}),
                   ('v73.mat', {'sa': ('1×3', 'struct'), 'sp': ('3×3', 'double'), 'e': ('0×3', 'double'), 'str': ('', 'string'),
                                'plain': ('1×3', 'single')}),
                   ('str5z.mat', {'arr': ('2×2', 'string'), 'none': ('0×3', 'string'), 'num': ('1×1', 'double')}),
                   ('str73.mat', {'arr': ('2×2', 'string'), 'gaps': ('1×3', 'string')})):
    info = json.loads(worker_api.file_info(path(name)))
    rows = {v['name']: (v['size'], v['class']) for v in info.get('vars', [])}
    for k, w in want.items():
        check(f'Details of {name}: {k}', rows.get(k) == w, f'got {rows.get(k)}, want {w}; {info}')

# ---- back through save ------------------------------------------------------------------------------
RT = ("a = int16([1 -2; 3 4]); b = single(pi); c = {1, 'two'; [3 4], {5}}; s(2).x = 'y'; s(1).x = [1 2 3]; "
      "t = struct('n', struct('m', magic(3))); u = 'Ångström'; m = ['ab'; 'cd']; l = [true false]; z = [1+2i 3]; "
      "e = zeros(0, 3); n3 = reshape(1:24, 2, 3, 4); q = uint64(18446744073709551615); "
      "sp = sparse([1 3], [1 2], [4 5], 3, 2); sl = sp > 4; ")
for ver in ('-v7', '-v6'):
    case(f'save {ver} and load', RT + f"save('rt.mat', '{ver}'); clear; load('rt.mat'); c22 = c{{2,2}}; s2 = s(2).x; tm = t.n.m(2, 3); "
         "k = [issparse(sp) issparse(sl)];",
         want={'k': [[True, True]], 'sp': [[4, 0], [0, 0], [0, 5]], 'sl': [[False, False], [False, False], [False, True]], 'a': [[1, -2], [3, 4]], 'c22': [5.0], 's2': 'y', 'tm': 7.0, 'u': 'Ångström', 'm': ['ab', 'cd'], 'l': [[True, False]],
               'z': [[1 + 2j, 3]], 'q': 2**64 - 1},
         cls={'a': 'int16', 'b': 'single', 'c': 'cell', 's': 'struct', 'l': 'logical', 'q': 'uint64', 'sl': 'logical'},
         shape={'e': (0, 3), 'n3': (2, 3, 4), 's': (1, 2)}, hides=['Warning'])
case('save -append keeps what the file holds', "x = 1; save('ap.mat', 'x'); y = 2; save('ap.mat', 'y', '-append'); clear; load('ap.mat');",
     want={'x': 1.0, 'y': 2.0})
size = os.path.getsize(path('hand.mat'))
case('save -append refuses to lose a variable it cannot read', "y = 2; save('hand.mat', 'y', '-append');",
     error="Unable to append to hand.mat: its variable 'str' cannot be read or written here, and would be lost. Nothing was saved.")
check('save -append left the file as it was', os.path.getsize(path('hand.mat')) == size)
case('matfile and importdata', "m = matfile('be.mat'); k = m.k; z = importdata('be.mat'); zk = z.k; w = importdata('v4be.mat');",
     want={'k': [[1, -2]], 'zk': [[1, -2]], 'w': [[1.5, 2.5]]})
write('data.dat', bytes(open(path('v4be.mat'), 'rb').read()))
case('load -mat reads a MAT-file of any name', "load('data.dat', '-mat')", want={'x': [[1.5, 2.5]]})
case('load of a text file still reads numbers', "fid = fopen('nums.txt', 'w'); fprintf(fid, '1 2\\n3 4\\n'); fclose(fid); load('nums.txt')",
     want={'nums': [[1, 2], [3, 4]]})

# ---- tables, timetables, datetimes, durations, calendarDurations and categoricals --------------------
OBJS = """t = datetime(2026,1,1,10,30,0) + days(0:2); t(2) = NaT; t.Format = 'yyyy-MM-dd HH:mm';
tz = datetime(2026,6,1,12,0,0,'TimeZone','Europe/Stockholm');
d = hours([1.5 NaN 3]); cdur = calmonths(2) + caldays([1 5]);
c = categorical({'lo','hi','lo',''}, {'lo','hi'}, 'Ordinal', true); cp = categorical({'a'}, {'a','b'}, 'Protected', true);
s = ["one" "two"; "three" "four"];
T = table([1;2;3], {'a';'b';'c'}, categorical({'x';'y';'x'}), datetime(2026,1,1)+days([0;1;2]), ["p";"q";"r"], int8([1;2;3]), [true;false;true], 'VariableNames', {'n','s','c','d','st','i','b'}, 'RowNames', {'r1','r2','r3'});
T.Properties.Description = 'demo'; T.Properties.VariableUnits = {'m','','','','','',''}; T.Properties.DimensionNames = {'Obs', 'Vars'};
TT = timetable(datetime(2026,1,1)+hours([0;1;2]), [1;2;3], {'x';'y';'z'}, 'VariableNames', {'v', 'w'});
TD = timetable(seconds([0;1]), [4;5]);
C = {t, 5, c}; S.when = t; S.names = s; S.n = 1;
x = magic(3);"""
for flag, label in (('', '-v7, compressed'), (", '-v6'", '-v6')):
    W, out = run(OBJS + f"""
save('objs.mat', 't', 'tz', 'd', 'cdur', 'c', 'cp', 's', 'T', 'TT', 'TD', 'C', 'S', 'x'{flag});
keep = struct('t', t, 'tz', tz, 'd', d, 'cdur', cdur, 'c', c, 's', s, 'x', x); keep.T = T; keep.TT = TT; keep.TD = TD; keep.cp = cp; keep.C = C; keep.S = S;
clear('-regexp', '^(?!keep$).*'); L = load('objs.mat');
eqs = [isequaln(L.t, keep.t), isequal(L.tz, keep.tz), isequaln(L.d, keep.d), isequal(L.cdur, keep.cdur), isequaln(L.c, keep.c), isequal(L.s, keep.s), ...
       isequal(L.T, keep.T), isequal(L.TT, keep.TT), isequal(L.TD, keep.TD), isequal(L.x, keep.x), isequaln(L.C{{1}}, keep.C{{1}}), isequaln(L.C{{3}}, keep.C{{3}}), ...
       isequaln(L.S.when, keep.S.when), isequal(L.S.names, keep.S.names)];
fmt = L.t.Format; zone = L.tz.TimeZone; dfmt = L.d.Format; ord = isordinal(L.c); prot = isprotected(L.cp); cats = categories(L.c);
desc = L.T.Properties.Description; units = L.T.Properties.VariableUnits; rows = L.T.Properties.RowNames; dims = L.T.Properties.DimensionNames;
classes = cellfun(@(v) class(L.T.(v)), L.T.Properties.VariableNames, 'UniformOutput', false); tclass = class(L.TT.Time); ddclass = class(L.TD.Time);
sclass = class(L.s);""")
    check(f'objects round trip through save and load ({label}): each value as it was', bool(np.all(np.asarray(W['eqs']))), (np.asarray(W['eqs']).tolist(), out[-300:]))
    check(f'... ({label}) the datetime format and time zone, the duration format', val(W['fmt']) == 'yyyy-MM-dd HH:mm' and val(W['zone']) == 'Europe/Stockholm' and val(W['dfmt']) == 'h',
          (val(W['fmt']), val(W['zone']), val(W['dfmt'])))
    check(f'... ({label}) ordinal and protected categoricals, their categories', W['ord'] is True and W['prot'] is True and val(W['cats']) == ['lo', 'hi'], (W['ord'], W['prot'], val(W['cats'])))
    check(f'... ({label}) the table\'s description, units, row and dimension names', val(W['desc']) == 'demo' and val(W['units'])[0] == 'm' and val(W['rows']) == ['r1', 'r2', 'r3']
          and val(W['dims']) == ['Obs', 'Vars'], (val(W['desc']), val(W['units']), val(W['rows']), val(W['dims'])))
    check(f'... ({label}) each variable\'s class; the row times\'', val(W['classes']) == ['double', 'cell', 'categorical', 'datetime', 'string', 'int8', 'logical']
          and val(W['tclass']) == 'datetime' and val(W['ddclass']) == 'duration', (val(W['classes']), val(W['tclass'])))
    check(f'... ({label}) a string array stays a string array', val(W['sclass']) == 'string', val(W['sclass']))

W, out = run(OBJS + """save('app.mat', 'x'); save('app.mat', 'T', '-append'); save('app.mat', 'c', '-append'); L = load('app.mat'); f = fieldnames(L)';
ok = isequal(L.T, T) && isequaln(L.c, c) && isequal(L.x, x);""")
check('-append keeps the objects already in the file and adds more', W['ok'] is True and val(W['f']) == ['x', 'T', 'c'], (val(W['f']), out[-200:]))
W, out = run(OBJS + "fh = @(x) x + 1; save('mixed.mat', 'T', 'fh', 'x'); L = load('mixed.mat'); f = fieldnames(L)';")
check('with objects, a function handle is still left out with a warning, the rest saved', val(W['f']) == ['T', 'x'] and "'fh'" in out and 'not saved' in out, (val(W['f']), out[-200:]))
W, out = run(OBJS + "save('old.mat', 'T', 'x', '-v4'); L = load('old.mat'); f = fieldnames(L)';")
check('-v4 has no objects: a table is left out with a warning', val(W['f']) == ['x'] and "'T'" in out, (val(W['f']), out[-200:]))

# a -v7.3 file of objects, laid out as MATLAB keeps them in HDF5
from matfixtures import objects_v73  # noqa: E402
W0 = dict(run(OBJS)[0])
objects_v73(path('obj73.mat'), {'when': W0['t'], 'cat': W0['c'], 'T': W0['T'], 'TT': W0['TT'], 'num': np.array([[1.0, 2.0]])})
W, out = run("L = load('obj73.mat'); f = fieldnames(L)'; c1 = class(L.when); c2 = class(L.cat); c3 = class(L.T); c4 = class(L.TT); "
             "nat = isnat(L.when); cats = categories(L.cat); dv = class(L.T.d); h = height(L.TT); n = L.num;")
check('-v7.3: datetime, categorical, table and timetable objects read from #subsystem#',
      sorted(val(W['f'])) == sorted(['when', 'cat', 'T', 'TT', 'num']) and [val(W[k]) for k in ('c1', 'c2', 'c3', 'c4')] == ['datetime', 'categorical', 'table', 'timetable'], (val(W['f']), out[-300:]))
check('... the NaT, the categories, the datetime variable inside the table, the timetable\'s rows',
      np.array_equal(np.asarray(W['nat']), [[False, True, False]]) and val(W['cats']) == ['lo', 'hi'] and val(W['dv']) == 'datetime' and W['h'] == 3,
      (W['nat'], val(W['cats']), val(W['dv']), W['h']))

# damaged object data: the objects are left out with a warning, the rest loads
from plab import matwrite  # noqa: E402
matwrite.write(path('bad.mat'), {'T': W0['T'], 'x': np.array([[7.0]])}, compress=False)
raw = bytearray(open(path('bad.mat'), 'rb').read())
at = raw.index(b'FileWrapper__')
ver = raw.index(struct.pack('<I', 4), at)
raw[ver:ver + 4] = struct.pack('<I', 9)
open(path('bad.mat'), 'wb').write(bytes(raw))
W, out = run("L = load('bad.mat'); f = fieldnames(L)';")
check('damaged object data: the table is left out with a warning saying why, x loads', val(W['f']) == ['x'] and "'T'" in out and 'version' in out, (val(W['f']), out[-300:]))

# ---- who -file and whos -file --------------------------------------------------------------------------
W, out = run(OBJS + """save('listed.mat', 'T', 't', 'x', 's'); clear('-regexp', '^(?!x$).*');
whos -file listed.mat
who -file listed
s = whos('-file', 'listed.mat'); names = {s.name}; sizes = {s.size}; classes = {s.class}; bytes = [s.bytes];
w = who('-file', 'listed.mat', 't*'); wx = whos('-file', 'listed.mat', 'x'); xb = wx.bytes;""")
check("whos -file lists a MAT-file's variables, sorted, with sizes and classes",
      val(W['names']) == ['s', 'T', 't', 'x'] and val(W['classes']) == ['string', 'table', 'datetime', 'double']
      and [np.asarray(x).reshape(-1).tolist() for x in W['sizes'].a.reshape(-1)] == [[2, 2], [3, 7], [1, 3], [3, 3]], (val(W['names']), val(W['classes'])))
check('... its printed table names them; who -file the names alone', 'Name' in out and 'datetime' in out and 'Variables in the file listed:' in out
      and '  T  ' in out, out[-600:])
check("... wildcards (as case-sensitive as names); a double's bytes", val(W['w']) == ['t'] and W['xb'] == 72, (val(W['w']), W['xb']))
W, out = run("""whos -file bad.mat
s = whos('-file', 'bad.mat'); names = {s.name}; classes = {s.class};""")
check('whos -file lists a variable it cannot read from its header (the damaged table), the rest as read',
      val(W['names']) == ['T', 'x'] and val(W['classes'])[0] == 'table', (val(W['names']), val(W['classes'])))
for code, words in (("whos -file nosuch.mat", 'No such file'), ("whos -file", 'name of a MAT-file'), ("who -file notmat.txt", 'not a MAT-file')):
    with open(path('notmat.txt'), 'w') as fh:
        fh.write('plain text\n')
    W, out = run(f"try\n{code}\nm = 'none';\ncatch e\nm = e.message;\nend")
    check(f'{code}: an error saying why', words in val(W['m']), val(W['m']))
W, out = run("x = 1; y = int8([1 2]); whos; s = whos; n = numel(s); c = who('y');")
check('whos and who of the workspace as before', 'int8' in out and W['n'] == 2 and val(W['c']) == ['y'], out[-200:])

shutil.rmtree(TMP, ignore_errors=True)
print(f'\n{checks[0] - len(failed)} of {checks[0]} checks passed')
sys.exit(1 if failed else 0)
