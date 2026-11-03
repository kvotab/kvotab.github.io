"""MAT-files (Level 5: what save -v6 and -v7 write) written element by
element, with the language's objects (tables, timetables, datetimes,
durations, calendarDurations, categoricals, string arrays) in the file's
object data.

    write(path, variables, compress=True) -> [(name, why it was left out)]

save uses SciPy's writer for files without objects, and this one for files
with them: SciPy cannot write objects. Each object is a reference in the
variable (an opaque element: 'MCOS', the class, [0xDD000000, dimensions,
object numbers, class number]) into the subsystem, an array of bytes at
the end of the file (its offset in the header) that is a small MAT stream
of its own: a struct whose field MCOS is the FileWrapper__ object, a cell
of the metadata, an empty element, each saved property, and three cells
for each class. The metadata (version 4): the number of names, 8 offsets,
the names, then the regions: (1) each class (namespace, name, 0, 0), (2)
the properties of objects saved through saveobj (string, timetable), (3)
each object (class, 0, 0, saveobj record, record, dependency), (4) the
properties of the others, (5) dynamic properties, (6) nothing, (7) eight
zero bytes. A property record is a count, then (name, 1, saved cell)
triples, padded to an even length. This is the layout the open-source
mat-io reader and writer document (github.com/foreverallama/matio,
BSD-3-Clause, (c) 2025 foreverallama); matobjects.py has each class's
properties."""
import datetime as _dt
import struct
import zlib

import numpy as np

from .values import Char, Cell, Struct, Str, Sparse, FH, Obj, INT_TYPES
from . import matobjects as MO

MCOS_MAGIC = 0xDD000000
mi = dict(INT8=1, UINT8=2, INT16=3, UINT16=4, INT32=5, UINT32=6, SINGLE=7, DOUBLE=9, INT64=12, UINT64=13, MATRIX=14,
          COMPRESSED=15, UTF8=16, UTF16=17)
MX_CELL, MX_STRUCT, MX_CHAR, MX_SPARSE, MX_DOUBLE, MX_SINGLE, MX_OPAQUE = 1, 2, 4, 5, 6, 7, 17
MX_INT = {'int8': (8, mi['INT8']), 'uint8': (9, mi['UINT8']), 'int16': (10, mi['INT16']), 'uint16': (11, mi['UINT16']),
          'int32': (12, mi['INT32']), 'uint32': (13, mi['UINT32']), 'int64': (14, mi['INT64']), 'uint64': (15, mi['UINT64'])}
F_COMPLEX, F_LOGICAL = 0x0800, 0x0200


class NotSaved(Exception):
    pass


class _Ref:
    """An object in a value, replaced by its reference into the subsystem."""
    __slots__ = ('cname', 'meta')

    def __init__(self, cname, meta):
        self.cname = cname
        self.meta = meta


# ---- data elements -------------------------------------------------------------------------------------

def _el(t, data):
    n = len(data)
    return struct.pack('<II', t, n) + data + b'\0' * (-n % 8)


def _matrix(klass, dims, name, parts, flags=0, nzmax=0):
    body = _el(mi['UINT32'], struct.pack('<II', klass | flags, nzmax))
    if klass != MX_OPAQUE:
        body += _el(mi['INT32'], struct.pack(f'<{len(dims)}i', *dims))
    body += _el(mi['INT8'], name.encode('ascii')) + b''.join(parts)
    return struct.pack('<II', mi['MATRIX'], len(body)) + body


def _dims(shape):
    shape = tuple(int(x) for x in shape)
    return shape if len(shape) >= 2 else (shape + (1, 1))[:2] if shape else (1, 1)


def element(name, v):
    """The miMATRIX element of a value (objects already replaced by references)."""
    if isinstance(v, _Ref):
        return _matrix(MX_OPAQUE, None, name, [_el(mi['INT8'], b'MCOS'), _el(mi['INT8'], v.cname.encode('ascii')),
                                               element('', v.meta)])
    if v is None:
        return _matrix(MX_DOUBLE, (0, 0), name, [_el(mi['DOUBLE'], b'')])
    t = type(v)
    if t in (float, int, bool, complex) or isinstance(v, (np.floating, np.integer, np.bool_)):
        return element(name, np.array([[v]]))
    if t is Char:
        units = np.asarray(v.a, np.uint16)
        return _matrix(MX_CHAR, _dims(units.shape), name, [_el(mi['UINT16'], units.astype('<u2').tobytes(order='F'))])
    if t is Cell:
        a = v.a
        return _matrix(MX_CELL, _dims(a.shape), name, [element('', x) for x in a.reshape(-1, order='F')])
    if t is Struct:
        keys = list(v.f)
        flen = max([32] + [len(k) + 1 for k in keys])
        flen += -flen % 8 if flen > 32 else 0
        names = b''.join(k.encode('ascii').ljust(flen, b'\0') for k in keys)
        parts = [_el(mi['INT32'], struct.pack('<i', flen)), _el(mi['INT8'], names)]
        for i in range(int(np.prod(v.shape))):
            for k in keys:
                parts.append(element('', v.f[k].reshape(-1, order='F')[i]))
        return _matrix(MX_STRUCT, _dims(v.shape), name, parts)
    if t is Sparse:
        m = v.m.tocsc()
        m.sort_indices()
        data = m.data
        logical = data.dtype == bool
        parts = [_el(mi['INT32'], m.indices.astype('<i4').tobytes()), _el(mi['INT32'], m.indptr.astype('<i4').tobytes())]
        if logical:
            parts.append(_el(mi['UINT8'], data.astype(np.uint8).tobytes()))
        else:
            parts.append(_el(mi['DOUBLE'], np.real(data).astype('<f8').tobytes()))
            if np.iscomplexobj(data):
                parts.append(_el(mi['DOUBLE'], np.imag(data).astype('<f8').tobytes()))
        flags = F_LOGICAL if logical else (F_COMPLEX if np.iscomplexobj(data) else 0)
        return _matrix(MX_SPARSE, m.shape, name, parts, flags, max(1, m.nnz))
    if t is np.ndarray:
        a = v
        dims = _dims(a.shape)
        if a.dtype == bool:
            return _matrix(9, dims, name, [_el(mi['UINT8'], a.astype(np.uint8).tobytes(order='F'))], F_LOGICAL)
        if a.dtype.kind == 'c':
            single = a.dtype == np.complex64
            dt, mt, cls = ('<f4', mi['SINGLE'], MX_SINGLE) if single else ('<f8', mi['DOUBLE'], MX_DOUBLE)
            return _matrix(cls, dims, name, [_el(mt, a.real.astype(dt).tobytes(order='F')),
                                             _el(mt, a.imag.astype(dt).tobytes(order='F'))], F_COMPLEX)
        if a.dtype == np.float32:
            return _matrix(MX_SINGLE, dims, name, [_el(mi['SINGLE'], a.astype('<f4').tobytes(order='F'))])
        if a.dtype.name in MX_INT:
            cls, mt = MX_INT[a.dtype.name]
            return _matrix(cls, dims, name, [_el(mt, a.astype(a.dtype.newbyteorder('<')).tobytes(order='F'))])
        if a.dtype.kind in 'fiu':
            return _matrix(MX_DOUBLE, dims, name, [_el(mi['DOUBLE'], a.astype('<f8').tobytes(order='F'))])
        if a.dtype.kind == 'O' and a.size == 0:
            return _matrix(MX_CELL, dims, name, [])
    raise NotSaved(f'a value of class {type(v).__name__} cannot be saved')


# ---- the subsystem -----------------------------------------------------------------------------------------

class Subsystem:
    """The objects of a file, numbered as they are met: their classes, property records and saved properties."""

    def __init__(self):
        self.names = []
        self.classes = [0, 0, 0, 0]
        self.class_index = {}
        self.aliases = [0]
        self.objects = [[0] * 6]
        self.saveobj = [[0, 0]]
        self.nobj = [[0, 0]]
        self.dynprops = [0, 0]
        self.saved = []
        self.n_objects = 0
        self.n_saveobj = 0
        self.n_nobj = 0

    def name(self, s):
        if s not in self.names:
            self.names.append(s)
        return self.names.index(s) + 1

    def class_id(self, cname):
        if cname in self.class_index:
            return self.class_index[cname]
        ns, _, nm = cname.rpartition('.')
        self.classes += [self.name(ns) if ns else 0, self.name(nm), 0, 0]
        self.aliases.append(0)
        self.class_index[cname] = len(self.class_index) + 1
        return self.class_index[cname]

    def prepare(self, v):
        """The value with every object in it (at any depth of cells and structs) replaced by its reference."""
        if MO.is_object(v):
            cname, props, saveobj = MO.to_props(v)
            oid, cid = self.add(cname, props, saveobj)
            meta = np.array([MCOS_MAGIC, 2, 1, 1, oid, cid], np.uint32).reshape(-1, 1)
            return _Ref(cname, meta)
        if type(v) is Cell:
            items = np.empty(v.a.shape, object)
            for i in range(v.a.size):
                items.flat[i] = self.prepare(v.a.flat[i])
            return Cell(items)
        if type(v) is Struct:
            return Struct(v.shape, {k: np.vectorize(self.prepare, otypes=[object])(a) if a.size else a.copy() for k, a in v.f.items()})
        return v

    def add(self, cname, props, saveobj):
        """An object: its number and its class's. Its properties are prepared (objects in them numbered
        after it), saved, and recorded; the dependency is the last object it holds."""
        self.n_objects += 1
        oid = self.n_objects
        record = []
        if saveobj:
            self.n_saveobj += 1
            rid = self.n_saveobj
            self.saveobj.append(record)
        else:
            self.n_nobj += 1
            rid = self.n_nobj
            self.nobj.append(record)
        meta = [0] * 6
        self.objects.append(meta)
        record.append(len(props))
        for k, value in props.items():
            idx = self.name(k)
            value = self.prepare(value)
            record += [idx, 1, len(self.saved)]
            self.saved.append(value)
        if len(record) % 2:
            record.append(0)
        self.dynprops += [0, 0]
        ndeps = self.n_objects - oid
        cid = self.class_id(cname)
        meta[0] = cid
        meta[3 if saveobj else 4] = rid
        meta[5] = oid + ndeps
        for i in range(1, ndeps + 1):
            self.objects[self.n_objects - ndeps + i][5] -= 1
        return oid, cid

    def metadata(self):
        names = b'\0'.join(n.encode('ascii') for n in self.names) + b'\0'
        names += b'\0' * (-len(names) % 8)
        flat = lambda rows: [x for r in rows for x in r]  # noqa: E731
        saveobj = flat(self.saveobj)
        regions = [np.array(self.classes, '<u4'),
                   np.array(saveobj if len(saveobj) > 2 else [], '<u4'),
                   np.array(flat(self.objects), '<u4'),
                   np.array(flat(self.nobj), '<u4'),
                   np.array(self.dynprops, '<u4'),
                   np.zeros(0, '<u4'),
                   np.zeros(2, '<u4')]
        offs = [40 + len(names)]
        for r in regions:
            offs.append(offs[-1] + r.nbytes)
        head = struct.pack('<2I', 4, len(self.names)) + struct.pack('<8I', *offs[:8])
        return head + names + b''.join(r.tobytes() for r in regions)

    def stream(self):
        """The subsystem's bytes: a version and byte order, then a struct whose field MCOS is the FileWrapper__ object."""
        meta = np.frombuffer(self.metadata(), np.uint8).reshape(-1, 1)
        per_class = Cell(np.empty((len(self.class_index) + 1, 1), object))
        for i in range(per_class.a.size):
            per_class.a.flat[i] = Struct((1, 0), {})
        items = ([element('', meta), struct.pack('<II', mi['MATRIX'], 0)]
                 + [element('', v) for v in self.saved]
                 + [element('', per_class), element('', np.array(self.aliases, np.uint32).reshape(-1, 1)), element('', per_class)])
        cell = _matrix(MX_CELL, (len(items), 1), '', items)
        fwrap = _matrix(MX_OPAQUE, None, '', [_el(mi['INT8'], b'MCOS'), _el(mi['INT8'], b'FileWrapper__'), cell])
        flen = 32
        top = _matrix(MX_STRUCT, (1, 1), '', [_el(mi['INT32'], struct.pack('<i', flen)), _el(mi['INT8'], b'MCOS'.ljust(flen, b'\0')), fwrap])
        return struct.pack('<H', 0x0100) + b'IM' + bytes(4) + top


# ---- files -------------------------------------------------------------------------------------------------

def write(path, variables, compress=True):
    """Write the variables (name -> value) as a Level 5 MAT-file; the variables that cannot be saved
    (function handles, graphics objects) are left out and listed."""
    sub = Subsystem()
    body = []
    left = []
    for name, v in variables.items():
        try:
            if isinstance(v, FH) or (isinstance(v, Obj) and not MO.is_object(v)):
                raise NotSaved(f'it is of class {getattr(v, "cls", type(v).__name__)}')
            body.append(element(name, sub.prepare(v)))
        except NotSaved as e:
            left.append((name, str(e)))
    wrap = (lambda e: struct.pack('<II', mi['COMPRESSED'], len(z := zlib.compress(e))) + z) if compress else (lambda e: e)
    chunks = [wrap(e) for e in body]
    text = f'MATLAB 5.0 MAT-file, Platform: PyLAB, Created on: {_dt.datetime.now():%a %b %d %H:%M:%S %Y}'
    offset = 0
    tail = b''
    if sub.n_objects:
        stream = np.frombuffer(sub.stream(), np.uint8)
        tail = wrap(element('', stream.reshape(1, -1)))
        offset = 128 + sum(len(c) for c in chunks)
    header = text.encode('ascii').ljust(116, b' ')[:116] + struct.pack('<Q', offset) + struct.pack('<H', 0x0100) + b'IM'
    with open(path, 'wb') as f:
        f.write(header)
        for c in chunks:
            f.write(c)
        f.write(tail)
    return left
