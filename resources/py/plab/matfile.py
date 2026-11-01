"""MAT-files read into the language's values.

    read(path, names=None, make_fh=None) -> (values, problems)
    variables(path)                      -> [(name, size, class)]
    kind(path)                           -> 'v73', 'v5', 'v4' or None

values holds the variables by name, in the file's order. problems holds a
warning, (name, text), for each variable that could not be read or was read
with a loss; the other variables are read all the same. A file that is not a
MAT-file, or whose start is damaged, raises MatError. names keeps only the
variables that match one of its patterns (* and ? are wildcards).
variables() lists what a file holds from the arrays' headers, without
reading their data.

Level 5 files (those saved with -v6 or -v7: compressed or not, in either
byte order) and Level 4 files are read here; -v7.3 files are HDF5 and are
read through h5py, which the caller makes importable first. The layouts are
the ones the open-source readers (SciPy, h5py, hdf5storage) know. Objects
whose layout is not published, such as string arrays, tables and datetimes,
are reported as problems, not guessed at.

make_fh(text, captured) makes a saved function handle again from its text
('@(x) x + 1' or a function's name) and, for an anonymous function, a dict
of the values it captured (or None); without it, function handles are
reported as problems.

Nothing in a file is trusted: sizes are checked against the data before any
array is made, inflated data is capped, nesting is limited, and a variable
or a field whose name is not a name is left out.
"""
import fnmatch
import re
import struct

import numpy as np

from .values import Char, Cell, Struct, F64, C128, INT_TYPES, EMPTY
from .ops import finish


# a variable's or a field's name: the desktop writes names into code, so
# nothing else from a file becomes one
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]*')
BAD_NAME = 'its name is not a valid variable name'


def shown(name):
    """A name from a file, fit to print."""
    t = ''.join(c if c.isprintable() else '?' for c in name)
    return t if len(t) <= 64 else t[:61] + '...'


class MatError(Exception):
    """The file cannot be read at all."""


class Unreadable(Exception):
    """One variable cannot be read; the message says why."""


INFLATE_LIMIT = 1 << 30      # bytes one variable may take once inflated
FULL_LIMIT = 1 << 26         # elements of a sparse matrix held as a full one
DEPTH_LIMIT = 64             # cells and structs inside each other
NODE_LIMIT = 1_000_000       # arrays in a -v7.3 file (its references may share them)
HEAD = 4104                  # bytes enough to tell the kind of file
HDF5_SIGNATURE = b'\x89HDF\r\n\x1a\n'

# Level 5: the types of data elements and the classes of arrays
MI_DTYPE = {1: 'i1', 2: 'u1', 3: 'i2', 4: 'u2', 5: 'i4', 6: 'u4', 7: 'f4', 9: 'f8', 12: 'i8', 13: 'u8'}
MI_MATRIX, MI_COMPRESSED, MI_UTF8, MI_UTF16, MI_UTF32 = 14, 15, 16, 17, 18
NUMERIC = {6: 'double', 7: 'single', 8: 'int8', 9: 'uint8', 10: 'int16', 11: 'uint16',
           12: 'int32', 13: 'uint32', 14: 'int64', 15: 'uint64'}
MX_CELL, MX_STRUCT, MX_OBJECT, MX_CHAR, MX_SPARSE, MX_FUNCTION, MX_OPAQUE = 1, 2, 3, 4, 5, 16, 17
F_COMPLEX, F_LOGICAL = 0x800, 0x200

# Level 4: the precision digit of a record's type
V4_DTYPE = {0: 'f8', 1: 'f4', 2: 'i4', 3: 'i2', 4: 'u2', 5: 'u1'}

CLASSES = {'double', 'single', 'logical', 'char', 'cell', 'struct'} | set(INT_TYPES)


def _shape(dims):
    """MATLAB's size as the shape a value keeps: no trailing ones past the second."""
    d = [int(x) for x in dims]
    if len(d) < 2:
        d = [1] * (2 - len(d)) + d
    while len(d) > 2 and d[-1] == 1:
        d.pop()
    return tuple(d)


def _count(dims):
    n = 1
    for d in dims:
        n *= d
    return n


def _numeric(a, cls):
    """A numpy array (MATLAB's shape) as the value of a numeric class."""
    if cls == 'double':
        return finish(a.astype(C128 if a.dtype.kind == 'c' else F64), 'double')
    if cls == 'logical':
        return finish(a != 0, 'logical')
    if cls == 'single':
        return finish(a, 'single')
    # integers keep every bit (the rounding path goes through doubles)
    return a.astype(INT_TYPES[cls]).reshape(_shape(a.shape))


def _empty_of(cls, dims):
    shape = _shape(dims)
    if _count(shape):
        raise Unreadable('its size is damaged (an empty array with elements)')
    if cls == 'char':
        return Char(np.zeros(shape, np.uint16))
    if cls == 'cell':
        return Cell(np.empty(shape, object))
    if cls == 'struct':
        return Struct(shape, {})
    if cls in INT_TYPES:
        return np.zeros(shape, INT_TYPES[cls])
    return _numeric(np.zeros(shape), cls if cls in CLASSES else 'double')


def _full(rows, cols, vals, m, n):
    """A sparse matrix's entries (0-based) as the full matrix this language holds."""
    if m * n > FULL_LIMIT:
        raise Unreadable(f'it is a sparse {m}x{n} matrix, too large to hold here (sparse matrices are held as full ones)')
    rows = np.asarray(rows, np.int64)
    cols = np.asarray(cols, np.int64)
    if rows.size and (rows.min() < 0 or rows.max() >= m or cols.min() < 0 or cols.max() >= n):
        raise Unreadable('its sparse indices are out of range')
    a = np.zeros((m, n), C128 if np.iscomplexobj(vals) else F64)
    np.add.at(a, (rows, cols), vals)
    return a


def _keeper(names):
    if not names:
        return lambda name: True
    return lambda name: any(fnmatch.fnmatchcase(name, p) for p in names)


def kind_of(head):
    """'v73', 'v5', 'v4' or None from a file's first bytes (HEAD of them)."""
    for at in (512, 0, 1024, 2048, 4096):
        if head[at:at + 8] == HDF5_SIGNATURE:
            return 'v73'
    if len(head) >= 128 and head[126:128] in (b'IM', b'MI') and 0 not in head[:4]:
        return 'v5'
    if _v4_header(head, 0) is not None:
        return 'v4'
    return None


def kind(path):
    with open(path, 'rb') as f:
        return kind_of(f.read(HEAD))


def read(path, names=None, make_fh=None):
    keep = _keeper(names)
    with open(path, 'rb') as f:
        head = f.read(HEAD)
        k = kind_of(head)
        if k == 'v73':
            f.close()
            return _read_v73(path, keep, make_fh)
        if not head:
            raise MatError('the file is empty')
        if k is None:
            raise MatError('it is not a MAT-file')
        f.seek(0)
        data = memoryview(f.read())
    if k == 'v5':
        return _V5(data, make_fh).read(keep)
    return _read_v4(data, keep)


def variables(path):
    with open(path, 'rb') as f:
        head = f.read(HEAD)
        k = kind_of(head)
        if k == 'v73':
            f.close()
            return _list_v73(path)
        if k is None:
            raise MatError('the file is empty' if not head else 'it is not a MAT-file')
        f.seek(0)
        data = memoryview(f.read())
    if k == 'v5':
        return _V5(data, None).list()
    return _list_v4(data)


# ---- Level 5 ---------------------------------------------------------------------------------

class _V5:
    def __init__(self, data, make_fh):
        self.data = data
        self.o = '<' if bytes(data[126:128]) == b'IM' else '>'
        self.make_fh = make_fh
        self.notes = []

    # data elements
    def tag(self, b, p, end):
        """The data element at p: (type, size, where its data starts, where the next one starts)."""
        if p + 8 > end:
            raise Unreadable('the file ends inside it')
        word, n = struct.unpack_from(self.o + 'II', b, p)
        if word >> 16:
            # a small element: its size in the upper half, its data in the next four bytes
            if word >> 16 > 4:
                raise Unreadable('it is damaged (a data element is malformed)')
            return word & 0xFFFF, word >> 16, p + 4, p + 8
        if n > end - p - 8:
            raise Unreadable('the file ends inside it')
        return word, n, p + 8, min(end, p + 8 + ((n + 7) & ~7))

    def numbers(self, b, t, d, n):
        code = MI_DTYPE.get(t)
        if code is None:
            raise Unreadable(f'it holds data of an unknown type ({t})')
        dt = np.dtype(self.o + code)
        return np.frombuffer(b, dt, n // dt.itemsize, d)

    def text(self, b, p, end):
        t, n, d, p = self.tag(b, p, end)
        return bytes(b[d:d + n]).split(b'\0', 1)[0].decode('utf-8', 'replace'), p

    def chars(self, b, t, d, n, dims):
        """Text data as UTF-16 code units in MATLAB's shape, whichever way it was stored."""
        count = _count(dims)
        if t in (MI_UTF8, MI_UTF32):
            raw = bytes(b[d:d + n])
            codec = 'utf-8' if t == MI_UTF8 else ('utf-32-le' if self.o == '<' else 'utf-32-be')
            try:
                s = raw.decode(codec, 'surrogatepass')
            except UnicodeDecodeError:
                s = raw.decode(codec, 'replace')
            units = np.frombuffer(s.encode('utf-16-le', 'surrogatepass'), '<u2').astype(np.uint16)
            if units.size != count and len(s) == count:
                # the size counts characters, not UTF-16 units (as SciPy writes it)
                if _count(dims[1:]) == dims[1] and dims[0] == 1:
                    return units.reshape(1, -1)
                self.notes.append('characters outside the Basic Multilingual Plane were replaced by \ufffd')
                units = np.array([ord(c) if ord(c) < 0x10000 else 0xFFFD for c in s], np.uint16)
        else:
            units = self.numbers(b, 4 if t == MI_UTF16 else t, d, n).astype(np.uint16)
        if units.size != count:
            raise Unreadable('its text does not match its size')
        return units.reshape(dims, order='F').reshape(_shape(dims))

    def header(self, b, p, end):
        """An array's flags, size and name: (class, flags, size, name, where its data starts)."""
        t, n, d, p = self.tag(b, p, end)
        if t != 6 or n < 8:
            raise Unreadable('its array flags are damaged')
        word = struct.unpack_from(self.o + 'I', b, d)[0]
        klass = word & 0xFF
        if klass == MX_OPAQUE:
            name, p = self.text(b, p, end)
            return klass, word, None, name, p
        t, n, d, p = self.tag(b, p, end)
        dims = [int(x) for x in self.numbers(b, t, d, n)]
        if len(dims) < 2 or min(dims) < 0:
            raise Unreadable('its size is damaged')
        name, p = self.text(b, p, end)
        return klass, word, dims, name, p

    # the variables
    def top(self, keep, data_wanted=True):
        """Each variable at the top level: (name, its element's contents as (buffer, start, end) or an
        Unreadable, where it was)."""
        b = self.data
        end = len(b)
        o = self.o
        sub = struct.unpack_from(o + 'Q', b, 116)[0] if end >= 124 else 0
        p = 128
        while p + 8 <= end:
            at = p
            word, n = struct.unpack_from(o + 'II', b, p)
            if word >> 16 or n > end - p - 8:
                yield None, Unreadable('the rest of the file is damaged'), at
                return
            d, p = p + 8, p + 8 + n
            if at == sub or n == 0 or word not in (MI_MATRIX, MI_COMPRESSED):
                continue
            if word == MI_MATRIX:
                try:
                    name = self.header(b, d, d + n)[3]
                except Unreadable as e:
                    yield '', e, at
                    continue
                if name and keep(name):
                    yield name, (b, d, d + n), at
                continue
            # compressed: inflate enough to read the name, then all of it if it is wanted
            raw = b[d:d + n]
            full = None
            try:
                try:
                    inner = _inflate(raw, HEAD)
                    name = self.inner_name(inner)
                except Unreadable:
                    full = inner = _inflate(raw, INFLATE_LIMIT)
                    name = self.inner_name(inner)
            except Unreadable as e:
                yield '', e, at
                continue
            if not name or not keep(name):
                continue
            if data_wanted and full is None:
                try:
                    inner = _inflate(raw, INFLATE_LIMIT)
                except Unreadable as e:
                    yield name, e, at
                    continue
            m = struct.unpack_from(o + 'I', inner, 4)[0]
            yield name, (inner, 8, min(len(inner), 8 + m)), at

    def inner_name(self, inner):
        """The name of the array a compressed element holds ('' for an empty one, None if it holds no array)."""
        if len(inner) < 8:
            raise Unreadable('its compressed data is damaged')
        t, m = struct.unpack_from(self.o + 'II', inner, 0)
        if t != MI_MATRIX:
            return None
        if m == 0:
            return ''
        return self.header(inner, 8, min(len(inner), 8 + m))[3]

    def read(self, keep):
        values, problems = {}, []
        for name, where, _ in self.top(keep):
            if isinstance(where, Unreadable):
                problems.append((name or '', str(where)))
                continue
            if not NAME.fullmatch(name):
                problems.append((name, BAD_NAME))
                continue
            self.notes = []
            try:
                b, p, end = where
                klass, word, dims, _, p = self.header(b, p, end)
                values[name] = self.body(b, p, end, klass, word, dims, 0)
            except Unreadable as e:
                problems.append((name, str(e)))
            except (ValueError, TypeError, IndexError, OverflowError, struct.error) as e:
                problems.append((name, f'it is damaged ({e})'))
            except MemoryError:
                problems.append((name, 'it is too large to read here'))
            problems.extend((name, n) for n in self.notes)
        return values, problems

    def list(self):
        rows = []
        for name, where, _ in self.top(lambda n: True, data_wanted=False):
            if isinstance(where, Unreadable):
                continue
            try:
                b, p, end = where
                klass, word, dims, _, p = self.header(b, p, end)
            except Unreadable:
                continue
            if klass == MX_OPAQUE:
                try:
                    p = self.text(b, p, end)[1]
                    cls = self.text(b, p, end)[0]
                except Unreadable:
                    cls = 'object'
                rows.append((name, None, cls))
                continue
            if klass == MX_OBJECT:
                try:
                    cls = self.text(b, p, end)[0]
                except Unreadable:
                    cls = 'object'
            elif klass == MX_FUNCTION:
                cls, dims = 'function_handle', [1, 1]
            else:
                cls = {MX_CELL: 'cell', MX_STRUCT: 'struct', MX_CHAR: 'char', MX_SPARSE: 'double'}.get(klass) or NUMERIC.get(klass, '?')
                if word & F_LOGICAL:
                    cls = 'logical'
            rows.append((name, _shape(dims), cls))
        return rows

    def element(self, b, p, end, depth):
        """The array in the miMATRIX element at p, and where the next element starts."""
        t, n, d, nxt = self.tag(b, p, end)
        if t != MI_MATRIX:
            raise Unreadable('it is damaged (an element is not an array)')
        if n == 0:
            return EMPTY(), nxt
        if depth >= DEPTH_LIMIT:
            raise Unreadable('its cells and structs are nested too deeply')
        klass, word, dims, _, q = self.header(b, d, d + n)
        return self.body(b, q, d + n, klass, word, dims, depth + 1), nxt

    def body(self, b, p, end, klass, word, dims, depth):
        count = _count(dims) if dims is not None else 0
        if klass in NUMERIC:
            cls = NUMERIC[klass]
            t, n, d, p = self.tag(b, p, end)
            re = self.numbers(b, t, d, n)
            if re.size != count:
                raise Unreadable('its data does not match its size')
            if word & F_LOGICAL:
                return _numeric(re.reshape(dims, order='F'), 'logical')
            if not word & F_COMPLEX:
                return _numeric(re.reshape(dims, order='F'), cls)
            t, n, d, p = self.tag(b, p, end)
            im = self.numbers(b, t, d, n)
            if im.size != count:
                raise Unreadable('its imaginary part does not match its size')
            if cls in INT_TYPES:
                self.notes.append('its imaginary part was left out (integers are real here)')
                return _numeric(re.reshape(dims, order='F'), cls)
            ft = np.complex64 if cls == 'single' else C128
            z = re.astype(ft) + 1j * im.astype(ft)
            return _numeric(z.astype(ft).reshape(dims, order='F'), cls)
        if klass == MX_CHAR:
            if count == 0:
                return Char(np.zeros(_shape(dims), np.uint16))
            t, n, d, p = self.tag(b, p, end)
            return Char(self.chars(b, t, d, n, dims))
        if klass == MX_CELL:
            if count > (end - p) // 8:
                raise Unreadable('its size is damaged')
            items = np.empty(count, object)
            for i in range(count):
                items[i], p = self.element(b, p, end, depth)
            return Cell(items.reshape(_shape(dims), order='F'))
        if klass in (MX_STRUCT, MX_OBJECT):
            if klass == MX_OBJECT:
                cname, p = self.text(b, p, end)
                self.notes.append(f"it was saved as an object of class '{cname}' and is now a struct")
            t, n, d, p = self.tag(b, p, end)
            flen = int(self.numbers(b, t, d, n)[0]) if n else 0
            t, n, d, p = self.tag(b, p, end)
            raw = bytes(b[d:d + n])
            # each field's name in a slot of flen bytes, padded with NULs
            slots = [raw[i:i + flen].split(b'\0', 1)[0].decode('utf-8', 'replace') for i in range(0, len(raw) - flen + 1, flen)] if flen > 0 else []
            if count * len(slots) > (end - p) // 8:
                raise Unreadable('its size is damaged')
            bad = [k for k in slots if k and not NAME.fullmatch(k)]
            if bad:
                self.notes.append(f"its field '{shown(bad[0])}'{f' and {len(bad) - 1} more' if len(bad) > 1 else ''} "
                                  'was left out (not a valid field name)')
            fields = {k: np.empty(count, object) for k in dict.fromkeys(k for k in slots if k and NAME.fullmatch(k))}
            for i in range(count if slots else 0):
                for k in slots:
                    v, p = self.element(b, p, end, depth)
                    if k in fields:
                        fields[k][i] = v
            shape = _shape(dims)
            return Struct(shape, {k: a.reshape(shape, order='F') for k, a in fields.items()})
        if klass == MX_SPARSE:
            if len(dims) != 2:
                raise Unreadable('its size is damaged')
            m, n_ = dims
            t, k, d, p = self.tag(b, p, end)
            ir = self.numbers(b, t, d, k)
            t, k, d, p = self.tag(b, p, end)
            jc = self.numbers(b, t, d, k).astype(np.int64)
            if jc.size != n_ + 1 or (jc.size and (jc[0] != 0 or np.any(np.diff(jc) < 0))):
                raise Unreadable('its sparse layout is damaged')
            nnz = int(jc[-1]) if jc.size else 0
            if p < end:
                t, k, d, p = self.tag(b, p, end)
                pr = self.numbers(b, t, d, k)
            else:
                pr = np.ones(nnz)
            if ir.size < nnz or pr.size < nnz:
                raise Unreadable('its sparse layout is damaged')
            vals = pr[:nnz].astype(F64)
            if word & F_COMPLEX:
                t, k, d, p = self.tag(b, p, end)
                pi = self.numbers(b, t, d, k)
                if pi.size < nnz:
                    raise Unreadable('its sparse layout is damaged')
                vals = vals + 1j * pi[:nnz].astype(F64)
            a = _full(ir[:nnz], np.repeat(np.arange(n_), np.diff(jc)), vals, m, n_)
            return _numeric(a, 'logical' if word & F_LOGICAL else 'double')
        if klass == MX_FUNCTION:
            v, p = self.element(b, p, end, depth)
            return self.handle(v)
        if klass == MX_OPAQUE:
            kind_, p = self.text(b, p, end)
            cname, p = self.text(b, p, end)
            raise Unreadable(f"it is an object of class '{cname}', and objects (string arrays, tables, datetimes "
                             "and the like) cannot be read from MAT-files here")
        raise Unreadable(f'its class is unknown ({klass})')

    def handle(self, v):
        """A function handle from the struct that describes it."""
        if self.make_fh is None:
            raise Unreadable('it is a function handle')
        info = _handle_info(v, 0)
        if info is None:
            raise Unreadable('it is a function handle in a form not known here')
        text, captured = info
        return self.make_fh(text, captured)


def _handle_info(v, depth):
    """The text of a saved function handle and the values it captured, found in its description."""
    if depth > 4:
        return None
    if type(v) is Struct and v.size == 1:
        if 'function' in v.f and type(v.get1('function')) is Char:
            text = v.get1('function').str()
            captured = None
            ws = v.get1('workspace') if 'workspace' in v.f else None
            if type(ws) is Cell and ws.a.size == 1:
                ws = ws.a.flat[0]
            if type(ws) is Struct and ws.size == 1:
                captured = {k: ws.get1(k) for k in ws.f}
            return text, captured
        for k in v.f:
            r = _handle_info(v.get1(k), depth + 1)
            if r is not None:
                return r
    if type(v) is Cell:
        for x in v.a.flat:
            r = _handle_info(x, depth + 1)
            if r is not None:
                return r
    return None


def _inflate(raw, limit):
    import zlib
    z = zlib.decompressobj()
    try:
        out = z.decompress(bytes(raw), limit)
    except zlib.error:
        raise Unreadable('its compressed data is damaged')
    if z.unconsumed_tail and limit == INFLATE_LIMIT:
        raise Unreadable('it is larger than 1 GB once uncompressed')
    return memoryview(out)


# ---- Level 4 -------------------------------------------------------------------------------------

def _v4_header(b, p):
    """The header of the Level 4 record at p: (byte order, precision, type, rows, columns, imaginary,
    name length), or None if there is none."""
    if len(b) - p < 20:
        return None
    for order, machine in (('<', 0), ('>', 1)):
        t, m, n, imagf, namlen = struct.unpack_from(order + '5i', b, p)
        if not 0 <= t <= 4052:
            continue
        M, O, P, T = t // 1000, t // 100 % 10, t // 10 % 10, t % 10
        if M != machine or O != 0 or P > 5 or T > 2 or m < 0 or n < 0 or imagf not in (0, 1) or not 1 <= namlen <= 4096:
            continue
        return order, P, T, m, n, imagf, namlen
    return None


def _v4_records(b):
    """Each record: (name, its header, where its data starts) or (None, why, None) when the file is damaged."""
    p = 0
    while p < len(b):
        h = _v4_header(b, p)
        if h is None:
            yield None, 'the rest of the file is damaged', None
            return
        order, P, T, m, n, imagf, namlen = h
        p += 20
        name = bytes(b[p:p + namlen]).split(b'\0', 1)[0].decode('latin-1')
        p += namlen
        size = m * n * np.dtype(V4_DTYPE[P]).itemsize * (2 if imagf else 1)
        if p + size > len(b):
            yield name, 'the file ends inside it', None
            return
        yield name, h, p
        p += size


def _read_v4(b, keep):
    values, problems = {}, []
    for name, h, p in _v4_records(b):
        if p is None:
            if name is None and not values and not problems:
                raise MatError('it is not a MAT-file')
            problems.append((name or '', h))
            break
        if not keep(name):
            continue
        if not NAME.fullmatch(name):
            problems.append((name, BAD_NAME))
            continue
        order, P, T, m, n, imagf, _ = h
        dt = np.dtype(order + V4_DTYPE[P])
        re = np.frombuffer(b, dt, m * n, p).astype(F64).reshape((m, n), order='F')
        im = np.frombuffer(b, dt, m * n, p + m * n * dt.itemsize).astype(F64).reshape((m, n), order='F') if imagf else None
        try:
            if T == 1:
                values[name] = Char(re.astype(np.uint16))
            elif T == 2:
                # rows of [i j re (im)], one-based; the last row holds the size
                if n not in (3, 4) or m < 1:
                    raise Unreadable('its sparse layout is damaged')
                vals = re[:-1, 2] + (1j * re[:-1, 3] if n == 4 else 0) + (1j * im[:-1, 2] if im is not None else 0)
                a = _full(re[:-1, 0] - 1, re[:-1, 1] - 1, vals, int(re[-1, 0]), int(re[-1, 1]))
                values[name] = _numeric(a, 'double')
            else:
                values[name] = _numeric(re + 1j * im if im is not None else re, 'double')
        except Unreadable as e:
            problems.append((name, str(e)))
    return values, problems


def _list_v4(b):
    rows = []
    for name, h, p in _v4_records(b):
        if p is None:
            break
        order, P, T, m, n, imagf, _ = h
        if T == 2 and n in (3, 4) and m >= 1:
            dt = np.dtype(order + V4_DTYPE[P])
            last = np.frombuffer(b, dt, m * n, p).reshape((m, n), order='F')[-1]
            rows.append((name, (int(last[0]), int(last[1])), 'double'))
        else:
            rows.append((name, (m, n), 'char' if T == 1 else 'double'))
    return rows


# ---- -v7.3 (HDF5) --------------------------------------------------------------------------------

def _h5py():
    try:
        import h5py
    except ImportError:
        raise MatError('MAT-files of version 7.3 are HDF5 files, and reading them needs the h5py package')
    return h5py


def _attr_text(v):
    if v is None:
        return None
    if isinstance(v, (bytes, np.bytes_)):
        return bytes(v).decode('utf-8', 'replace')
    if isinstance(v, np.ndarray) and v.size == 1:
        return _attr_text(v.reshape(-1)[0])
    return str(v)


def _field_names(attr):
    names = []
    for x in np.asarray(attr, dtype=object).reshape(-1):
        if isinstance(x, (bytes, np.bytes_)):
            names.append(bytes(x).decode('utf-8', 'replace'))
        else:
            names.append(b''.join(bytes(c) for c in np.asarray(x).reshape(-1)).decode('utf-8', 'replace'))
    return names


def _open_h5(path):
    h5py = _h5py()
    try:
        return h5py, h5py.File(path, 'r')
    except (OSError, ValueError) as e:
        raise MatError(f'its HDF5 data cannot be read ({e})')


def _h5_names(g):
    """The names in an HDF5 group (as text; a damaged group cannot be listed)."""
    try:
        return [k.decode('utf-8', 'replace') if isinstance(k, bytes) else str(k) for k in g.keys()]
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as e:
        raise MatError(f'its HDF5 data is damaged ({e})')


def _read_v73(path, keep, make_fh):
    h5py, f = _open_h5(path)
    values, problems = {}, []
    with f:
        r = _H5(h5py, f, make_fh)
        for name in _h5_names(f):
            if name.startswith('#') or not keep(name):
                continue
            if not NAME.fullmatch(name):
                problems.append((name, BAD_NAME))
                continue
            r.notes = []
            try:
                values[name] = r.value(f[name], 0)
            except Unreadable as e:
                problems.append((name, str(e)))
            except (ValueError, TypeError, IndexError, KeyError, OSError, RuntimeError, AttributeError) as e:
                problems.append((name, f'it is damaged ({e})'))
            except MemoryError:
                problems.append((name, 'it is too large to read here'))
            problems.extend((name, n) for n in r.notes)
    return values, problems


def _list_v73(path):
    h5py, f = _open_h5(path)
    rows = []
    with f:
        for name in _h5_names(f):
            if name.startswith('#'):
                continue
            cls = None
            try:
                node = f[name]
                cls = _attr_text(node.attrs.get('MATLAB_class'))
                if isinstance(node, h5py.Group):
                    if 'MATLAB_sparse' in node.attrs:
                        shape = (int(np.asarray(node.attrs['MATLAB_sparse']).reshape(-1)[0]), node['jc'].shape[0] - 1 if 'jc' in node else 0)
                    else:
                        kids = [node[k] for k in node]
                        shape = (1, 1)
                        if kids and all(isinstance(k, h5py.Dataset) and k.dtype.kind == 'O' and 'MATLAB_class' not in k.attrs for k in kids):
                            shape = _shape(kids[0].shape[::-1])
                    rows.append((name, shape, cls or 'struct'))
                elif node.attrs.get('MATLAB_empty'):
                    _fits(node)
                    rows.append((name, _shape(np.asarray(node[()]).reshape(-1)), cls or 'double'))
                else:
                    if cls is None:
                        cls = _class_of_dtype(node.dtype)
                    rows.append((name, None if 'MATLAB_object_decode' in node.attrs else _shape(node.shape[::-1]), cls))
            except (Unreadable, ValueError, TypeError, KeyError, OSError, RuntimeError, AttributeError):
                rows.append((name, None, cls or '?'))
    return rows


def _fits(ds):
    """A dataset is read whole: refuse one larger than a variable may be (HDF5
    can declare a huge dataset that takes no room in the file)."""
    if not isinstance(ds.size, int) or ds.size * max(1, ds.dtype.itemsize) > INFLATE_LIMIT:
        raise Unreadable('it is larger than 1 GB')


def _class_of_dtype(dt):
    """The class of an HDF5 dataset written without MATLAB's attributes."""
    if dt.kind in 'SUO':
        return 'cell' if dt.kind == 'O' else 'char'
    if dt.kind == 'b':
        return 'logical'
    if dt in (np.float32, np.complex64):
        return 'single'
    return {np.dtype(t).newbyteorder('='): c for c, t in INT_TYPES.items()}.get(dt.newbyteorder('='), 'double')


class _H5:
    def __init__(self, h5py, f, make_fh):
        self.h5py = h5py
        self.f = f
        self.make_fh = make_fh
        self.notes = []
        self.left = NODE_LIMIT

    def deref(self, ref, depth):
        try:
            node = self.f[ref]
        except (ValueError, KeyError, TypeError) as e:
            raise Unreadable(f'it is damaged (a reference leads nowhere: {e})')
        return self.value(node, depth + 1)

    def value(self, node, depth):
        if depth > DEPTH_LIMIT:
            raise Unreadable('its cells and structs are nested too deeply')
        self.left -= 1
        if self.left < 0:
            raise Unreadable(f'it holds more than {NODE_LIMIT:,} arrays')
        if not isinstance(node, (self.h5py.Group, self.h5py.Dataset)):
            raise Unreadable('it is damaged (it is not an array)')
        cls = _attr_text(node.attrs.get('MATLAB_class'))
        if isinstance(node, self.h5py.Group):
            if 'MATLAB_sparse' in node.attrs:
                return self.sparse(node, cls)
            if cls in (None, 'struct'):
                return self.struct(node, depth)
            if cls == 'function_handle':
                raise Unreadable('it is a function handle, which cannot be read from MAT-files of version 7.3 here')
            raise Unreadable(f"it is an object of class '{cls}', and objects cannot be read from MAT-files here")
        if 'MATLAB_object_decode' in node.attrs or (cls is not None and cls not in CLASSES):
            raise Unreadable(f"it is an object of class '{cls}', and objects (string arrays, tables, datetimes and "
                             "the like) cannot be read from MAT-files here")
        _fits(node)
        if node.attrs.get('MATLAB_empty'):
            # an empty array keeps its size as its data
            return _empty_of(cls or 'double', np.asarray(node[()]).reshape(-1))
        data = np.asarray(node[()])
        if data.dtype.kind == 'O' and self.h5py.check_dtype(ref=node.dtype) is not None:
            items = np.empty(data.shape, object)
            for i in range(data.size):
                items.flat[i] = self.deref(data.flat[i], depth)
            return Cell(np.transpose(items).reshape(_shape(data.shape[::-1])))
        if data.dtype.names and 'real' in data.dtype.names and 'imag' in data.dtype.names:
            data = data['real'] + 1j * data['imag']
        # HDF5 keeps an array with MATLAB's dimensions reversed
        a = np.transpose(data).reshape(_shape(data.shape[::-1]))
        if cls == 'char':
            return Char(a.astype(np.uint16))
        if cls is None:
            if a.dtype.kind in 'SUO':
                return self.strings(a)
            cls = _class_of_dtype(a.dtype)
        if a.dtype.kind == 'c' and cls in INT_TYPES:
            self.notes.append('its imaginary part was left out (integers are real here)')
            a = a.real
        return _numeric(a, cls)

    def strings(self, a):
        """Text an HDF5 file holds as strings (not as MATLAB writes it): a row of text, or a cell of them."""
        def text(x):
            return Char.of(x.decode('utf-8', 'replace') if isinstance(x, (bytes, np.bytes_)) else str(x))
        if a.size == 1:
            return text(a.reshape(-1)[0])
        items = np.empty(a.shape, object)
        for i in range(a.size):
            items.flat[i] = text(a.flat[i])
        return Cell(items)

    def sparse(self, node, cls):
        for k in ('jc', 'ir', 'data'):
            if k in node:
                _fits(node[k])
        m = int(np.asarray(node.attrs['MATLAB_sparse']).reshape(-1)[0])
        jc = np.asarray(node['jc'][()]).astype(np.int64).reshape(-1) if 'jc' in node else np.zeros(1, np.int64)
        n = jc.size - 1
        if n < 0 or jc[0] != 0 or np.any(np.diff(jc) < 0):
            raise Unreadable('its sparse layout is damaged')
        nnz = int(jc[-1])
        ir = np.asarray(node['ir'][()]).reshape(-1) if 'ir' in node else np.zeros(0, np.int64)
        data = np.asarray(node['data'][()]) if 'data' in node else np.ones(nnz)
        if data.dtype.names and 'real' in data.dtype.names:
            data = data['real'] + 1j * data['imag']
        data = data.reshape(-1)
        if ir.size < nnz or data.size < nnz:
            raise Unreadable('its sparse layout is damaged')
        a = _full(ir[:nnz], np.repeat(np.arange(n), np.diff(jc)), data[:nnz].astype(C128 if data.dtype.kind == 'c' else F64), m, n)
        return _numeric(a, 'logical' if cls == 'logical' else 'double')

    def struct(self, node, depth):
        order = _field_names(node.attrs['MATLAB_fields']) if 'MATLAB_fields' in node.attrs else []
        kids = _h5_names(node)
        names = [k for k in order if k in kids] + [k for k in kids if k not in order]
        bad = [k for k in names if not NAME.fullmatch(k)]
        if bad:
            self.notes.append(f"its field '{shown(bad[0])}'{f' and {len(bad) - 1} more' if len(bad) > 1 else ''} "
                              'was left out (not a valid field name)')
            names = [k for k in names if NAME.fullmatch(k)]
            order = [k for k in order if NAME.fullmatch(k)]
        if node.attrs.get('MATLAB_empty'):
            return Struct((0, 0), {k: np.empty((0, 0), object) for k in order})
        kids = [node[k] for k in names]
        # a struct array keeps each field as an array of references, one per element
        if kids and all(isinstance(k, self.h5py.Dataset) and 'MATLAB_class' not in k.attrs
                        and self.h5py.check_dtype(ref=k.dtype) is not None for k in kids):
            shape = kids[0].shape
            if all(k.shape == shape for k in kids):
                out_shape = _shape(shape[::-1])
                fields = {}
                for k, ds in zip(names, kids):
                    refs = np.asarray(ds[()])
                    items = np.empty(refs.shape, object)
                    for i in range(refs.size):
                        items.flat[i] = self.deref(refs.flat[i], depth)
                    fields[k] = np.transpose(items).reshape(out_shape)
                return Struct(out_shape, fields)
        return Struct.scalar({k: self.value(ds, depth + 1) for k, ds in zip(names, kids)})
