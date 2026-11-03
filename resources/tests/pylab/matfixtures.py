"""MAT-files written for the pylab tests, element by element: no file here
is written by MATLAB.

    el, matrix, double, chars, struct1, compressed, header
                     Level 5 data elements and arrays, in either byte order
    strings_v5(variables, order='<', compress=False) -> the bytes of a file
    strings_v73(path, variables)                     -> writes a -v7.3 file

MATLAB keeps a string array as an object: the variable holds a reference
into the file's object data (its subsystem, a FileWrapper__ cell), where
the object's property 'any' holds the text. The layout written here is the
one the open-source mat-io reader documents (github.com/foreverallama/matio,
BSD-3-Clause), at version 4 of the metadata, each string array one object.

variables maps a name to a string array (a numpy object array in MATLAB's
shape: str, or None for a missing string), to a number, to ('cell', [values])
for a 1xn cell, or to ('any', uint64 words) for an object whose 'any' is
given as it is (damaged on purpose).
"""
import struct
import zlib

import numpy as np

MCOS_MAGIC = 0xDD000000
MISSING = (1 << 64) - 1


# ---- Level 5 data elements --------------------------------------------------------------------

def el(t, data, o='<'):
    """A data element: small (in eight bytes) when its data fits in four."""
    n = len(data)
    if n <= 4 and t not in (14, 15):
        return struct.pack(o + 'I', (n << 16) | t) + data.ljust(4, b'\0')
    return struct.pack(o + 'II', t, n) + data + b'\0' * (-n % 8)


def matrix(klass, dims, name, parts=(), flags=0, o='<'):
    body = el(6, struct.pack(o + 'II', klass | flags, 0), o)
    if klass != 17:
        body += el(5, struct.pack(o + f'{len(dims)}i', *dims), o)
    body += el(1, name.encode(), o) + b''.join(parts)
    return struct.pack(o + 'II', 14, len(body)) + body


def double(name, a, o='<'):
    a = np.atleast_2d(np.asarray(a, float))
    return matrix(6, a.shape, name, [el(9, a.astype(o + 'f8').tobytes(order='F'), o)], o=o)


def chars(name, s, o='<'):
    units = np.frombuffer(s.encode('utf-16-le', 'surrogatepass'), '<u2')
    return matrix(4, (1, units.size), name, [el(4, units.astype(o + 'u2').tobytes(), o)], o=o)


def struct1(name, fields, o='<'):
    """A 1x1 struct of the given (name, element) pairs."""
    flen = 32
    names = b''.join(k.encode().ljust(flen, b'\0') for k, _ in fields)
    return matrix(2, (1, 1), name, [el(5, struct.pack(o + 'i', flen), o), el(1, names, o)] + [v for _, v in fields], o=o)


def compressed(element, o='<'):
    z = zlib.compress(element)
    return struct.pack(o + 'II', 15, len(z)) + z


def header(o='<', sub=0, text='MATLAB 5.0 MAT-file, written by the pylab tests'):
    return (text.encode().ljust(116, b' ') + struct.pack(o + 'Q', sub) + struct.pack(o + 'H', 0x0100)
            + (b'IM' if o == '<' else b'MI'))


# ---- string arrays as objects ------------------------------------------------------------------

def string_words(arr, o='<'):
    """A string array as its property 'any': 1, the number of dimensions, the size, each string's
    length in UTF-16 code units (all ones when missing), then the text, four code units a uint64
    word. The words as the file holds them (bytes in its order)."""
    codec = 'utf-16-le' if o == '<' else 'utf-16-be'
    counts, text = [], b''
    for s in arr.reshape(-1, order='F'):
        if s is None:
            counts.append(MISSING)
            continue
        b = s.encode(codec, 'surrogatepass')
        counts.append(len(b) // 2)
        text += b
    text += b'\0' * (-len(text) % 8)
    head = np.array([1, arr.ndim, *arr.shape, *counts], dtype=np.uint64)
    return head.astype(o + 'u8').tobytes() + text


def fwrap_metadata(n, o='<'):
    """The FileWrapper__ metadata (version 4) of n string objects, each with one saved property."""
    names = b'any\0string\0'
    names += b'\0' * (-len(names) % 8)
    classes = [0, 0, 0, 0, 0, 2, 0, 0]                      # class 1: no namespace, name 2 (string)
    saveobj = [0, 0] + [x for k in range(n) for x in (1, 1, 1, k)]   # one property, 'any', saved cell k
    objects = [0] * 6 + [x for k in range(n) for x in (1, 0, 0, k + 1, 0, k + 1)]
    nobj = [0, 0]
    dynprops = [0, 0] * (n + 1)
    regions = [classes, saveobj, objects, nobj, dynprops]
    offs = [40 + len(names)]
    for r in regions:
        offs.append(offs[-1] + 4 * len(r))
    offs += [offs[-1], offs[-1] + 8]                        # region 6 empty, region 7 eight zero bytes
    return (struct.pack(o + '2i', 4, 2) + struct.pack(o + '8i', *offs) + names
            + b''.join(struct.pack(o + f'{len(r)}i', *r) for r in regions) + bytes(8))


def _strings_of(variables):
    """The string arrays among the variables (in cells too), in order: each becomes an object."""
    out = []
    for v in variables.values():
        for x in (v[1] if isinstance(v, tuple) and v[0] == 'cell' else [v]):
            if isinstance(x, np.ndarray) or (isinstance(x, tuple) and x[0] == 'any'):
                out.append(x)
    return out


def strings_v5(variables, order='<', compress=False):
    """A Level 5 file of the variables, with the subsystem that holds the strings' text."""
    o = order
    objs = _strings_of(variables)
    ids = {id(x): k + 1 for k, x in enumerate(objs)}

    def ref(name, x):
        meta = np.array([MCOS_MAGIC, 2, 1, 1, ids[id(x)], 1], np.uint32)
        return matrix(17, None, name, [el(1, b'MCOS', o), el(1, b'string', o),
                                       matrix(13, (6, 1), '', [el(6, meta.astype(o + 'u4').tobytes(), o)], o=o)], o=o)

    def value(name, v):
        if isinstance(v, np.ndarray) or (isinstance(v, tuple) and v[0] == 'any'):
            return ref(name, v)
        if isinstance(v, tuple) and v[0] == 'cell':
            return matrix(1, (1, len(v[1])), name, [value('', x) for x in v[1]], o=o)
        return double(name, v, o)

    def anyprop(x):
        words = x[1].astype(o + 'u8').tobytes() if isinstance(x, tuple) else string_words(x, o)
        return matrix(15, (1, len(words) // 8), '', [el(13, words, o)], o=o)

    empty = matrix(6, (0, 0), '', [], o=o)
    per_class = matrix(1, (2, 1), '', [empty, empty], o=o)
    meta = fwrap_metadata(len(objs), o)
    items = ([matrix(9, (len(meta), 1), '', [el(2, meta, o)], o=o), empty]
             + [anyprop(x) for x in objs]
             + [per_class, matrix(13, (2, 1), '', [el(6, bytes(8), o)], o=o), per_class])
    fwrap = matrix(17, None, '', [el(1, b'MCOS', o), el(1, b'FileWrapper__', o), matrix(1, (len(items), 1), '', items, o=o)], o=o)
    stream = struct.pack(o + 'H', 0x0100) + (b'IM' if o == '<' else b'MI') + bytes(4) + struct1('', [('MCOS', fwrap)], o)
    subsys = matrix(9, (1, len(stream)), '', [el(2, stream, o)], o=o)
    wrap = (lambda e: compressed(e, o)) if compress else (lambda e: e)
    body = b''.join(wrap(value(k, v)) for k, v in variables.items())
    return header(o, sub=128 + len(body) if objs else 0) + body + (wrap(subsys) if objs else b'')


def strings_v73(path, variables):
    """A -v7.3 file of the variables (string arrays and numbers): the objects' data in #subsystem#."""
    import h5py
    objs = _strings_of(variables)
    ids = {id(x): k + 1 for k, x in enumerate(objs)}
    with h5py.File(path, 'w', userblock_size=512) as f:
        refs = f.create_group('#refs#')

        def put(name, a, cls):
            # MATLAB's array a (in its own shape): HDF5 keeps the dimensions reversed
            ds = refs.create_dataset(name, data=np.asarray(a).T)
            ds.attrs['MATLAB_class'] = np.bytes_(cls)
            return ds

        meta = np.frombuffer(fwrap_metadata(len(objs)), np.uint8).reshape(-1, 1)
        items = [put('meta', meta, 'uint8'), put('empty', np.zeros((0, 0)), 'double')]
        for k, x in enumerate(objs):
            words = x[1].astype('<u8') if isinstance(x, tuple) else np.frombuffer(string_words(x), '<u8')
            items.append(put(f'any{k}', words.reshape(1, -1), 'uint64'))
        items += [put('c3', np.zeros((0, 0)), 'double'), put('alias', np.zeros((2, 1), np.uint32), 'uint32'),
                  put('defaults', np.zeros((0, 0)), 'double')]
        g = f.create_group('#subsystem#')
        ds = g.create_dataset('MCOS', data=np.array([[i.ref for i in items]], dtype=h5py.ref_dtype))
        ds.attrs['MATLAB_class'] = np.bytes_('FileWrapper__')
        ds.attrs['MATLAB_object_decode'] = np.int32(3)
        for name, v in variables.items():
            if id(v) in ids:
                d = f.create_dataset(name, data=np.array([[MCOS_MAGIC, 2, 1, 1, ids[id(v)], 1]], np.uint32))
                d.attrs['MATLAB_class'] = np.bytes_('string')
                d.attrs['MATLAB_object_decode'] = np.int32(3)
            else:
                d = f.create_dataset(name, data=np.atleast_2d(np.asarray(v, float)).T)
                d.attrs['MATLAB_class'] = np.bytes_('double')
    with open(path, 'r+b') as fh:
        fh.write(b'MATLAB 7.3 MAT-file, written by the pylab tests'.ljust(116, b' ') + bytes(8) + struct.pack('<H', 0x0200) + b'IM')


# ---- other objects (tables, datetimes, ...) in a -v7.3 file ---------------------------------------------

def objects_v73(path, variables):
    """A -v7.3 file of the variables (the language's values: tables, datetimes, categoricals and plain
    arrays), the objects' saved properties in #subsystem# as references to arrays in #refs#: numbers
    and text as datasets, cells as datasets of references, structs as groups, an object held in a
    property as its uint32 reference. The objects are numbered and their metadata made by
    plab/matwrite.py's Subsystem, which save uses for Level 5 files."""
    import h5py
    from plab import matwrite
    from plab.values import Char as _Char, Cell as _Cell, Struct as _Struct
    sub = matwrite.Subsystem()
    prepared = {k: sub.prepare(v) for k, v in variables.items()}
    with h5py.File(path, 'w', userblock_size=512) as f:
        refs = f.create_group('#refs#')
        count = [0]

        def put(v, where=None, name=None):
            """The array v written (in #refs# unless where and name are given): its node."""
            if where is None:
                count[0] += 1
                where, name = refs, f'n{count[0]}'
            if isinstance(v, matwrite._Ref):
                d = where.create_dataset(name, data=np.asarray(v.meta, np.uint32).T)
                d.attrs['MATLAB_class'] = np.bytes_(v.cname)
                d.attrs['MATLAB_object_decode'] = np.int32(3)
                return d
            if isinstance(v, _Struct):
                g = where.create_group(name)
                g.attrs['MATLAB_class'] = np.bytes_('struct')
                g.attrs['MATLAB_fields'] = np.array([np.frombuffer(k.encode(), 'S1') for k in v.f], dtype=h5py.vlen_dtype(np.dtype('S1')))
                for k in v.f:
                    put(v.f[k].reshape(-1)[0], g, k)
                return g
            if isinstance(v, _Cell):
                kids = [put(x).ref for x in v.a.reshape(-1, order='F')]
                arr = np.array(kids, dtype=h5py.ref_dtype).reshape(v.a.shape, order='F') if kids else np.zeros(2, np.uint64)
                d = where.create_dataset(name, data=arr.T if kids else arr)
                d.attrs['MATLAB_class'] = np.bytes_('cell')
                if not kids:
                    d.attrs['MATLAB_empty'] = np.uint8(1)
                return d
            if isinstance(v, _Char):
                d = where.create_dataset(name, data=np.asarray(v.a, np.uint16).T if v.a.size else np.array(v.a.shape, np.uint64))
                d.attrs['MATLAB_class'] = np.bytes_('char')
                if not v.a.size:
                    d.attrs['MATLAB_empty'] = np.uint8(1)
                return d
            a = np.atleast_2d(np.asarray(v))
            cls = 'logical' if a.dtype == bool else 'double' if a.dtype.kind == 'f' else a.dtype.name
            if a.size == 0:
                d = where.create_dataset(name, data=np.array(a.shape, np.uint64))
                d.attrs['MATLAB_empty'] = np.uint8(1)
            else:
                d = where.create_dataset(name, data=(a.astype(np.uint8) if a.dtype == bool else a).T)
            d.attrs['MATLAB_class'] = np.bytes_(cls)
            return d

        meta = np.frombuffer(sub.metadata(), np.uint8).reshape(-1, 1)
        items = [put(meta), put(np.zeros((0, 0)))] + [put(v) for v in sub.saved]
        items += [put(np.zeros((0, 0))), put(np.array(sub.aliases, np.uint32).reshape(-1, 1)), put(np.zeros((0, 0)))]
        g = f.create_group('#subsystem#')
        ds = g.create_dataset('MCOS', data=np.array([[i.ref for i in items]], dtype=h5py.ref_dtype))
        ds.attrs['MATLAB_class'] = np.bytes_('FileWrapper__')
        ds.attrs['MATLAB_object_decode'] = np.int32(3)
        for name, v in prepared.items():
            put(v, f, name)
    with open(path, 'r+b') as fh:
        fh.write(b'MATLAB 7.3 MAT-file, written by the pylab tests'.ljust(116, b' ') + bytes(8) + struct.pack('<H', 0x0200) + b'IM')
