"""Writing HDF5 as Kompartment writes it, byte for byte.

A port of the application's ``src/io/hdf5.js``: the same narrow writer --
groups, arrays of doubles, floats, integers and strings, attributes on both --
laying out the same tree in the same bytes, so a file written from Python is
the file the application would have written::

    from kompartment.io import hdf5

    root = hdf5.group({'model': 'Two boxes'})
    hdf5.put(root, ['time'], hdf5.dataset([0.0, 1.0, 2.0], hdf5.F64, {'unit': 'year'}))
    hdf5.put(root, ['IndexLists', 'Radionuclides'], hdf5.dataset(['Cs-137', 'H-3'], hdf5.STR))
    hdf5.put(root, ['Soil', 'Cs-137'], hdf5.dataset([1.0, 0.9, 0.8]))
    data = hdf5.write_hdf5(root)            # bytes

**Which HDF5.** Version 2 object headers with a group's links held in the
header itself ("compact" storage), which needs no B-tree: a link is a message,
and a group of four hundred children is four hundred messages. Every version
2 structure ends in a Jenkins lookup3 checksum (:func:`lookup3`). libhdf5 has
read and written these since 1.8; ``h5py``, ``h5ls``, ``h5dump`` and the
result browser's h5wasm open them.

**Strings** are variable-length UTF-8 in a global heap collection, pooled:
``TRUE`` is in the file once however many datasets say it. A boolean
attribute is written as the string ``TRUE`` or ``FALSE``, which is what
Ecolego's own files hold.

**The tree** is made of :func:`group` and :func:`dataset` nodes put together
with :func:`put`. Children are written in the order they were put, which is
what keeps a result file's nuclides in the model's order. Attributes are
written in the order JavaScript lists an object's keys: keys that are array
indices (``'0'``, ``'17'``) first, in numeric order, then the rest in the
order they were set -- which is insertion order for any ordinary name.

Values are converted as the application converts them: a number that is not
a float is turned into one as JavaScript's ``Number()`` would (``None`` is 0, a
numeric string its number, anything else NaN), a float32 dataset rounds to
nearest, an int32 dataset wraps as JavaScript's ``Int32Array`` does, and text
is written as ``String()`` writes it. numpy arrays are accepted wherever a list
is, and a two-dimensional one gives its shape when no ``dims`` is given.

References: the HDF5 File Format Specification version 3.0, sections III.A
(superblock version 2), IV.A (object headers version 2 and their messages) and
III.E (global heap). The checksum is ``H5_checksum_lookup3`` from
``H5checksum.c``.
"""

from __future__ import annotations

import math
import re
import struct
import sys
from array import array
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..errors import KompartmentError
from .csv import is_js_boolean, js_string, js_to_number

__all__ = [
    'HDF5Error', 'Datatype', 'F64', 'F32', 'I32', 'STR', 'Group', 'Dataset',
    'group', 'dataset', 'put', 'lookup3', 'write_hdf5',
]

#: What a file starts with: \x89 H D F \r \n \x1a \n.
SIGNATURE = b'\x89HDF\r\n\x1a\n'

# Message types, from the specification's table.
MSG_NIL = 0x00
MSG_DATASPACE = 0x01
MSG_LINK_INFO = 0x02
MSG_DATATYPE = 0x03
MSG_FILL_VALUE = 0x05
MSG_LINK = 0x06
MSG_LAYOUT = 0x08
MSG_GROUP_INFO = 0x0a
MSG_ATTRIBUTE = 0x0c
MSG_ATTRIBUTE_INFO = 0x15

#: A global heap collection has to be at least this big, and every
#: variable-length string in the file lives in one of them.
HEAP_MINIMUM = 4096

#: Past this many objects the two-byte index in a heap ID runs out.
HEAP_MAX_OBJECTS = 60000

_LITTLE = sys.byteorder == 'little'
_M32 = 0xFFFFFFFF


class HDF5Error(KompartmentError, ValueError):
    """A tree that cannot be written: a name with a slash in it, two things at
    one path, a shape that does not match its values, a datatype this writer
    does not know."""


# --- the datatypes this writer knows ----------------------------------------

@dataclass(frozen=True)
class Datatype:
    """One of the datatypes the writer knows: :data:`F64`, :data:`F32`,
    :data:`I32` or :data:`STR`.

    ``kind`` is ``'float'``, ``'int'`` or ``'vlenstr'`` and ``size`` the bytes
    one value takes; a float also carries where its exponent and mantissa sit
    (``exp_loc``, ``exp``, ``mant``) and its exponent ``bias``, an integer
    whether it is ``signed``. The JavaScript spells ``exp_loc`` ``expLoc``.
    """

    kind: str
    size: int
    exp: int = 0
    exp_loc: int = 0
    mant: int = 0
    bias: int = 0
    signed: bool = False


#: IEEE 754 doubles, little-endian: what a result series is.
F64 = Datatype('float', 8, exp=11, exp_loc=52, mant=52, bias=1023)
#: The same, half the size, for a series that does not need the digits.
F32 = Datatype('float', 4, exp=8, exp_loc=23, mant=23, bias=127)
#: A signed 32-bit integer: counts.
I32 = Datatype('int', 4, signed=True)
#: A variable-length UTF-8 string, held in the global heap.
STR = Datatype('vlenstr', 16)


def _le(n: Any, width: int = 8) -> List[int]:
    """``Math.floor(n / 2 ** (8 * i)) & 0xff`` for each byte: a number as
    little-endian bytes, the way the JavaScript spells it out -- negative
    numbers come out as all ones, which for -1 is the undefined address."""
    if isinstance(n, bool) or not isinstance(n, int):
        x = js_to_number(n)
        if math.isnan(x) or math.isinf(x):
            return [0] * width
        if x != int(x):
            return [math.floor(x / 2.0 ** (8 * i)) & 0xFF for i in range(width)]
        n = int(x)
    return [(n >> (8 * i)) & 0xFF for i in range(width)]


def _datatype_bytes(dt: Datatype) -> bytes:
    """The datatype message for one of the datatypes above.

    Version 1, which is the version every reader understands. The layout is a
    class-and-version byte, three bytes of class-specific flags, a four-byte
    size, and then properties whose shape depends on the class.
    """
    out = bytearray()

    def prefix(cls: int, bits: int, size: int) -> None:
        out.append((1 << 4) | cls)
        out.extend([bits & 0xFF, (bits >> 8) & 0xFF, (bits >> 16) & 0xFF])
        out.extend(_le(size, 4))

    def u16(v: int) -> None:
        out.extend([v & 0xFF, (v >> 8) & 0xFF])

    kind = getattr(dt, 'kind', None)
    if kind == 'float':
        # Bit 0 clear is little-endian; bits 4-5 = 2 is the usual "the leading
        # mantissa bit is implied"; bits 8-15 say where the sign sits, which
        # for these is the top bit.
        sign = dt.size * 8 - 1
        prefix(1, 0x20 | (sign << 8), dt.size)
        u16(0)  # bit offset
        u16(dt.size * 8)  # bit precision
        out.extend([dt.exp_loc & 0xFF, dt.exp & 0xFF, 0, dt.mant & 0xFF])
        out.extend(_le(dt.bias, 4))
        return bytes(out)
    if kind == 'int':
        prefix(0, 0x08 if dt.signed else 0x00, dt.size)
        u16(0)
        u16(dt.size * 8)
        return bytes(out)
    if kind == 'vlenstr':
        # Class 9, variable-length. Bits 0-3 = 1 says the sequence is a string;
        # bits 4-7 are its padding rule and bits 8-11 its character set.
        prefix(9, 0x01 | (0 << 4) | (1 << 8), 16)
        # The parent type is one character, which libhdf5 writes as an
        # eight-bit unsigned integer rather than as a one-byte string: the
        # byte-for-byte shape the library produces.
        out.append((1 << 4) | 0)  # version 1, class 0 (fixed-point)
        out.extend([0, 0, 0])  # little-endian, unsigned, no padding
        out.extend(_le(1, 4))  # one byte wide
        u16(0)  # bit offset
        u16(8)  # bit precision
        return bytes(out)
    raise HDF5Error(f"No datatype for '{'undefined' if kind is None else js_string(kind)}'")


def _dataspace_bytes(dims: Sequence[Any]) -> bytes:
    """The dataspace message: how many values, in how many dimensions.

    Version 2, whose "type" byte tells a scalar (no dimensions) from a
    one-element array -- a distinction the reader keeps, and which decides
    whether an attribute comes back as a value or as a list of one.
    """
    out = [2, len(dims) & 0xFF, 0, 1 if dims else 0]
    for n in dims:
        out.extend(_le(n))
    return bytes(out)


# --- the tree ---------------------------------------------------------------

class Group:
    """A group: attributes and children (``{kind: 'group', attrs, children}``).

    ``attrs`` is a dictionary of attribute values and ``children`` a dictionary
    of name to :class:`Group` or :class:`Dataset`, kept -- and written -- in
    the order the children were put.
    """

    __slots__ = ('attrs', 'children')
    kind = 'group'

    def __init__(self, attrs: Optional[Dict[str, Any]] = None) -> None:
        self.attrs: Dict[str, Any] = {} if attrs is None else attrs
        self.children: Dict[str, Union['Group', 'Dataset']] = {}

    def __repr__(self) -> str:
        return f'Group(attrs={self.attrs!r}, children={list(self.children)!r})'


class Dataset:
    """A dataset: values, their :class:`Datatype`, attributes and, for a
    matrix, its dimensions (``{kind: 'dataset', data, dt, attrs, dims}``)."""

    __slots__ = ('data', 'dt', 'attrs', 'dims')
    kind = 'dataset'

    def __init__(self, data: Any, dt: Datatype = F64, attrs: Optional[Dict[str, Any]] = None,
                 dims: Optional[List[Any]] = None) -> None:
        self.data = data
        self.dt = dt
        self.attrs: Dict[str, Any] = {} if attrs is None else attrs
        self.dims = dims

    def __repr__(self) -> str:
        n = _length(self.data)
        return f'Dataset({n} values, {self.dt.kind}{self.dt.size * 8}, dims={self.dims!r})'


def _is_numpy_array(value: Any) -> bool:
    return type(value).__module__ == 'numpy' and type(value).__name__ == 'ndarray'


def _length(data: Any) -> int:
    """``data.length ?? 0``: how many values, or none for something that is not
    a list at all (a bare number is not one)."""
    if _is_numpy_array(data):
        return int(data.size)
    try:
        return len(data)
    except TypeError:
        return 0


def group(attrs: Optional[Dict[str, Any]] = None) -> Group:
    """A group, with the attributes given (``group``).

    Children are kept in insertion order, and written in it: a compact group
    is searched linearly, so any order reads, and insertion order is the one
    that puts a result file's nuclides in the order the model lists them.
    The dictionary is held, not copied.
    """
    return Group(attrs)


def dataset(data: Any, dt: Datatype = F64, attrs: Optional[Dict[str, Any]] = None,
            dims: Optional[Sequence[Any]] = None) -> Dataset:
    """A dataset: values, their type and attributes (``dataset``).

    ``data`` is a list (or tuple, ``array.array`` or numpy array) of numbers,
    or of strings for :data:`STR`. ``dims`` is for the one case that is not a
    list: a probabilistic result, one row per output time and one column per
    realisation. The values are still given flat -- HDF5 stores them flat, the
    last dimension varying fastest -- so with ``dims=[times, realisations]``,
    ``data[t * n + r]`` is realisation ``r`` at time ``t``. ``dims=[]`` writes
    a single value as a scalar.

    A numpy array of two or more dimensions is taken flat, in C order, with its
    shape as ``dims`` unless ``dims`` is given. An iterator is read into a
    list. A bare number is not a list and gives an empty dataset, as it does in
    the application.

    Raises :class:`HDF5Error` when ``dims`` does not multiply out to the number
    of values.
    """
    if _is_numpy_array(data):
        if dims is None and data.ndim >= 2:
            dims = [int(d) for d in data.shape]
        data = data.reshape(-1)
    elif not isinstance(data, (str, bytes)) and not hasattr(data, '__len__') and hasattr(data, '__iter__'):
        data = list(data)
    if dims is not None:
        dims = list(dims)
        want = 1.0
        for d in dims:
            want *= js_to_number(d)
        got = _length(data)
        if want != got:
            shape = '×'.join('' if d is None else js_string(d) for d in dims)
            raise HDF5Error(f'A {shape} dataset holds {js_string(want)} values and was given {got}')
    return Dataset(data, dt, attrs, dims)


def put(root: Group, path: Sequence[str], node: Union[Group, Dataset]) -> Union[Group, Dataset]:
    """Puts ``node`` at ``path`` in ``root``, making the groups on the way (``put``).

    ``path`` is a list of names, ``['Soil', 'Cs-137']``; empty names are
    skipped. A name with a slash in it cannot be a link name -- that is the one
    character HDF5 reserves -- so it is refused, and so is a second thing at
    one path, or anything put inside a dataset: two results with one name is a
    bug in whoever built the tree. Returns ``node``.
    """
    if isinstance(path, (str, bytes)):
        raise TypeError('a path is a list of names, not one string')
    parts = [p for p in path if p != '']
    if not parts:
        raise HDF5Error('Nothing can be put at the root itself')
    at: Any = root
    for part in parts[:-1]:
        if '/' in part:
            raise HDF5Error(f"'{part}' cannot be a name: it has a slash in it")
        nxt = at.children.get(part)
        if nxt is None:
            nxt = group()
            at.children[part] = nxt
        elif nxt.kind != 'group':
            raise HDF5Error(f"'{part}' is a dataset, so nothing can be put inside it")
        at = nxt
    last = parts[-1]
    if '/' in last:
        raise HDF5Error(f"'{last}' cannot be a name: it has a slash in it")
    if last in at.children:
        raise HDF5Error(f"There is already something at {'/'.join(parts)}")
    at.children[last] = node
    return node


# --- the checksum -----------------------------------------------------------

def _rot(x: int, k: int) -> int:
    return ((x << k) | (x >> (32 - k))) & _M32


def lookup3(data: Union[bytes, bytearray, memoryview], start: int = 0, length: Optional[int] = None) -> int:
    """Jenkins' lookup3 over ``length`` bytes of ``data`` from ``start``
    (``lookup3``; the JavaScript calls ``start`` ``from``).

    As ``H5_checksum_lookup3`` calls it, with an initial value of zero. Every
    version 2 structure ends with four bytes of this over everything before
    it, and a reader that does not like the answer will not open the file.
    """
    if length is None:
        length = len(data) - start
    chunk = bytes(data[start:start + length])
    if len(chunk) < length:  # past the end reads as zeros, as in the JavaScript
        chunk += b'\0' * (length - len(chunk))
    a = b = c = (0xDEADBEEF + length) & _M32
    n = length
    # Twelve bytes at a time while more than twelve are left: the last one to
    # twelve go through the tail below.
    blocks = (n - 1) // 12 if n > 12 else 0
    words = struct.unpack_from(f'<{3 * blocks}I', chunk, 0) if blocks else ()
    for i in range(0, 3 * blocks, 3):
        a = (a + words[i]) & _M32
        b = (b + words[i + 1]) & _M32
        c = (c + words[i + 2]) & _M32
        a = ((a - c) & _M32) ^ _rot(c, 4)
        c = (c + b) & _M32
        b = ((b - a) & _M32) ^ _rot(a, 6)
        a = (a + c) & _M32
        c = ((c - b) & _M32) ^ _rot(b, 8)
        b = (b + a) & _M32
        a = ((a - c) & _M32) ^ _rot(c, 16)
        c = (c + b) & _M32
        b = ((b - a) & _M32) ^ _rot(a, 19)
        a = (a + c) & _M32
        c = ((c - b) & _M32) ^ _rot(b, 4)
        b = (b + a) & _M32
    k = 12 * blocks
    n -= k
    if n == 0:
        return c
    # The tail, byte by byte, as the C's fall-through switch adds it.
    t = chunk[k:k + n]
    if n >= 12:
        c += t[11] << 24
    if n >= 11:
        c += t[10] << 16
    if n >= 10:
        c += t[9] << 8
    if n >= 9:
        c += t[8]
    if n >= 8:
        b += t[7] << 24
    if n >= 7:
        b += t[6] << 16
    if n >= 6:
        b += t[5] << 8
    if n >= 5:
        b += t[4]
    if n >= 4:
        a += t[3] << 24
    if n >= 3:
        a += t[2] << 16
    if n >= 2:
        a += t[1] << 8
    a += t[0]
    a &= _M32
    b &= _M32
    c &= _M32
    c = ((c ^ b) - _rot(b, 14)) & _M32
    a = ((a ^ c) - _rot(c, 11)) & _M32
    b = ((b ^ a) - _rot(a, 25)) & _M32
    c = ((c ^ b) - _rot(b, 16)) & _M32
    a = ((a ^ c) - _rot(c, 4)) & _M32
    b = ((b ^ a) - _rot(a, 14)) & _M32
    c = ((c ^ b) - _rot(b, 24)) & _M32
    return c


# --- JavaScript's view of the values ------------------------------------------

def _utf8(s: str) -> bytes:
    """``TextEncoder``: UTF-8, with a lone surrogate written as U+FFFD rather
    than refused, and a surrogate pair written as the character it makes."""
    try:
        return s.encode('utf-8')
    except UnicodeEncodeError:
        return s.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'replace').encode('utf-8')


_ARRAY_INDEX = re.compile(r'0|[1-9][0-9]*')


def _is_array_index(key: str) -> bool:
    return bool(_ARRAY_INDEX.fullmatch(key)) and int(key) < 0xFFFFFFFF


def _own_entries(obj: Optional[Dict[Any, Any]]) -> List[Tuple[str, Any]]:
    """``Object.entries(obj)``: array-index keys first, in numeric order, then
    every other key in the order it was first set."""
    if not obj:
        return []
    items: Dict[str, Any] = {}
    for k, v in obj.items():
        items[k if isinstance(k, str) else js_string(k)] = v
    first = sorted((k for k in items if _is_array_index(k)), key=int)
    return [(k, items[k]) for k in first] + [(k, v) for k, v in items.items() if not _is_array_index(k)]


def _is_list(value: Any) -> bool:
    """``Array.isArray(value) || ArrayBuffer.isView(value)``, in Python's types."""
    if isinstance(value, (list, tuple, range, array, bytes, bytearray, memoryview)):
        return True
    return _is_numpy_array(value) and value.ndim > 0


def _as_list(value: Any) -> List[Any]:
    if _is_numpy_array(value):
        return value.reshape(-1).tolist()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return list(bytes(value))
    return list(value)


def _flat(data: Any) -> Any:
    """The values of a dataset as something with a length, the way the
    JavaScript holds them: a numpy array flat, bytes as their numbers."""
    if _is_numpy_array(data):
        return data.reshape(-1)
    if isinstance(data, (bytes, bytearray, memoryview)):
        return list(bytes(data))
    return data


def _iterate(data: Any) -> List[Any]:
    """``Array.from(data)``: the elements, or none for something that is not a list."""
    data = _flat(data)
    if _is_numpy_array(data):
        return data.tolist()
    if isinstance(data, str) or hasattr(data, '__len__'):
        return list(data)
    return []


def _doubles(data: Any) -> array:
    """The values as doubles, as ``Float64Array.prototype.set`` converts them."""
    if _is_numpy_array(data) and data.dtype.kind in 'biuf':
        return array('d', data.astype('float64').tolist())
    if isinstance(data, array) and data.typecode in 'dfbBhHiIlLqQ':
        return array('d', data)
    try:
        return array('d', data)
    except (TypeError, OverflowError, ValueError):
        return array('d', [js_to_number(v) for v in _iterate(data)])


def _f64_bytes(data: Any) -> bytes:
    if _is_numpy_array(data) and data.dtype.kind in 'biuf':
        return data.astype('<f8').tobytes()
    out = _doubles(_flat(data))
    if not _LITTLE:
        out.byteswap()
    return out.tobytes()


def _f32_bytes(data: Any) -> bytes:
    """Doubles rounded to the nearest float32, overflowing to infinity, as a
    ``Float32Array`` stores them."""
    data = _flat(data)
    if _is_numpy_array(data) and data.dtype.kind in 'biuf':
        import numpy  # the input is numpy's, so numpy is there

        with numpy.errstate(over='ignore'):
            return data.astype('float64').astype('<f4').tobytes()
    out = array('f', _doubles(data))
    if not _LITTLE:
        out.byteswap()
    return out.tobytes()


def _to_int32(x: float) -> int:
    """``ToInt32``: truncated towards zero and wrapped modulo 2^32; NaN and the
    infinities are 0."""
    if math.isnan(x) or math.isinf(x):
        return 0
    i = int(x) & _M32
    return i - (1 << 32) if i & 0x80000000 else i


def _i32_bytes(data: Any) -> bytes:
    data = _flat(data)
    if _is_numpy_array(data) and data.dtype.kind in 'biu':
        return data.astype('int64').astype('<i4').tobytes()
    values = [_to_int32(v) for v in _doubles(data)]
    return struct.pack(f'<{len(values)}i', *values)


# --- the global heap --------------------------------------------------------

class _Strings:
    """Every variable-length string in the file, pooled.

    A string on disk is not the characters: it is a 16-byte "global heap ID"
    -- how many bytes, which collection, which object in it -- and the
    characters live in the collection. libhdf5 inserts each string as it comes;
    here identical strings share one object, which for a result file is most
    of them. The two-byte object index is why there can be more than one
    collection.
    """

    def __init__(self) -> None:
        self.collections: List[List[bytes]] = [[]]
        self.where: Dict[str, Tuple[int, int, int]] = {}

    def add(self, text: Any) -> Tuple[int, int, int]:
        """The heap ID parts ``(collection, index, length)`` for ``text``,
        adding it if it is new."""
        s = js_string(text)
        found = self.where.get(s)
        if found:
            return found
        c = len(self.collections) - 1
        if len(self.collections[c]) >= HEAP_MAX_OBJECTS:
            self.collections.append([])
            c += 1
        data = _utf8(s)
        self.collections[c].append(data)
        hid = (c, len(self.collections[c]), len(data))
        self.where[s] = hid
        return hid

    def size(self, c: int) -> int:
        """How big collection ``c`` has to be, header and padding included."""
        n = 16
        for data in self.collections[c]:
            n += 16 + -(-len(data) // 8) * 8
        # The specification's minimum. Anything left over is described by a
        # free-space object, which is what index 0 means.
        return max(HEAP_MINIMUM, n + 16)


# --- laying the file out ----------------------------------------------------

class _Attribute:
    __slots__ = ('name', 'dt', 'dims', 'values', 'name_bytes')

    def __init__(self, name: str, dt: Datatype, dims: List[int], values: List[Any],
                 name_bytes: bytes) -> None:
        self.name = name
        self.dt = dt
        self.dims = dims
        self.values = values
        self.name_bytes = name_bytes


def _attribute(name: str, value: Any, strings: _Strings) -> _Attribute:
    """The values of an attribute, in a shape the writer can size and write."""
    listed = _is_list(value)
    values = _as_list(value) if listed else [value]
    dims = [len(values)] if listed else []
    # A boolean is written as TRUE or FALSE, which is what Ecolego's files say
    # (an enumerated type there) and what every reader of them tests for.
    text = any(isinstance(v, str) or is_js_boolean(v) for v in values)
    dt = STR if text else F64
    out: List[Any] = []
    for v in values:
        if not text:
            out.append(js_to_number(v))
        elif is_js_boolean(v):
            out.append(strings.add('TRUE' if v else 'FALSE'))
        else:
            out.append(strings.add(js_string(v)))
    return _Attribute(name, dt, dims, out, _utf8(name))


def _count(dims: Sequence[Any]) -> Any:
    """How many values a dataspace holds."""
    if not dims:
        return 1
    n: Any = 1
    for d in dims:
        n = n * d
    return n


def _attribute_size(a: _Attribute) -> int:
    """The bytes an attribute message takes, header excluded."""
    return (9 + len(a.name_bytes) + 1 + len(_datatype_bytes(a.dt)) + len(_dataspace_bytes(a.dims))
            + _count(a.dims) * a.dt.size)


def _link_size(name_bytes: bytes) -> int:
    """The bytes a link message takes, header excluded."""
    return 2 + (2 if len(name_bytes) > 255 else 1) + len(name_bytes) + 8


class _Object:
    __slots__ = ('node', 'name', 'name_bytes', 'attrs', 'addr', 'header_size', 'data_addr',
                 'data_size', 'children', 'dims', 'ids')

    def __init__(self, node: Any, name: str, name_bytes: bytes, attrs: List[_Attribute]) -> None:
        self.node = node
        self.name = name
        self.name_bytes = name_bytes
        self.attrs = attrs
        self.addr = 0
        self.header_size = 0
        self.data_addr = 0
        self.data_size = 0
        self.children: List[Tuple[str, bytes, '_Object']] = []
        self.dims: List[Any] = []
        self.ids: List[Tuple[int, int, int]] = []


def _plan(root: Group) -> Tuple[_Strings, List[int], List[_Object], _Object, int]:
    """Walks the tree once: normalises the attributes, pools the strings, and
    works out how big every object header and data block will be, and where
    everything goes.

    Depth first, each object before its children, as the JavaScript's
    recursive walk goes -- which fixes both the order of the headers and the
    order the strings enter the heap. Walked with a stack of its own rather
    than by recursion, so a deep tree is not refused for Python's sake.
    """
    strings = _Strings()
    objects: List[_Object] = []
    root_object: Optional[_Object] = None
    # (node, name, name bytes, the parent's list of children or None for the root)
    stack: List[Tuple[Any, str, bytes, Optional[list]]] = [(root, '', b'', None)]
    while stack:
        node, name, name_bytes, siblings = stack.pop()
        if siblings is not None and not name_bytes:
            raise HDF5Error('A link cannot have an empty name')
        attrs = [_attribute(k, v, strings) for k, v in _own_entries(node.attrs) if v is not None]
        o = _Object(node, name, name_bytes, attrs)
        objects.append(o)
        if siblings is None:
            root_object = o
        else:
            siblings.append((name, name_bytes, o))
        # Every object with attributes says so: without it a reader looks for
        # them in a fractal heap that is not there.
        msgs = sum(4 + _attribute_size(a) for a in attrs) + (4 + 18 if attrs else 0)
        if node.kind == 'group':
            kids = [(child_name, _utf8(child_name), child) for child_name, child in node.children.items()]
            msgs += 4 + 18 + 4 + 2  # link info, group info
            for _, child_bytes, _ in kids:
                msgs += 4 + _link_size(child_bytes)
            for child_name, child_bytes, child in reversed(kids):
                stack.append((child, child_name, child_bytes, o.children))
        else:
            data = _flat(node.data)
            n = _length(data)
            # A shape the caller gave, or the list it is: `dataset` has already
            # checked that the two agree about how many values there are.
            o.dims = list(node.dims) if node.dims is not None else [n]
            o.data_size = n * node.dt.size
            # Nothing to point at, and address zero is the superblock: a
            # dataset with no values says so with the undefined address.
            if not o.data_size:
                o.data_addr = -1
            if node.dt.kind == 'vlenstr':
                o.ids = [strings.add(s) for s in _iterate(data)]
            msgs += (4 + len(_dataspace_bytes(o.dims))
                     + 4 + len(_datatype_bytes(node.dt))
                     + 4 + 2  # fill value
                     + 4 + 18)  # layout
        o.header_size = 14 + msgs

    # Where everything goes. The superblock first, then the strings -- they
    # have to be placed before any header is written, because an attribute's
    # data is the address of the collection holding it.
    at = 48
    heap_at: List[int] = []
    for c in range(len(strings.collections)):
        heap_at.append(at)
        at += strings.size(c)
    for o in objects:
        o.addr = at
        at += o.header_size
    for o in objects:
        if o.node.kind != 'dataset' or not o.data_size:
            continue
        at = -(-at // 8) * 8
        o.data_addr = at
        at += o.data_size
    assert root_object is not None
    return strings, heap_at, objects, root_object, at


# --- writing ----------------------------------------------------------------

class _Out:
    """A cursor over the output, with the widths HDF5 uses."""

    def __init__(self, size: int) -> None:
        self.buf = bytearray(size)
        self.at = 0

    def seek(self, p: int) -> '_Out':
        self.at = p
        return self

    def byte(self, v: int) -> '_Out':
        self.buf[self.at] = v & 0xFF
        self.at += 1
        return self

    def bytes(self, data: Any) -> '_Out':
        if not isinstance(data, (bytes, bytearray)):
            data = bytes(v & 0xFF for v in data)
        self.buf[self.at:self.at + len(data)] = data
        self.at += len(data)
        return self

    def u16(self, v: int) -> '_Out':
        return self.byte(v).byte(v >> 8)

    def u32(self, v: int) -> '_Out':
        return self.byte(v).byte(v >> 8).byte(v >> 16).byte(v >> 24)

    def u64(self, v: int) -> '_Out':
        """Eight bytes, little-endian; -1 is the undefined address, all ones."""
        if v < 0:
            return self.bytes(b'\xff' * 8)
        return self.bytes(bytes(_le(v)))

    def checksum(self, start: int) -> '_Out':
        """Four bytes of lookup3 over everything written since ``start``."""
        return self.u32(lookup3(self.buf, start, self.at - start))


def _message(out: _Out, kind: int, body: Any) -> None:
    """One message: its four-byte header, then its bytes."""
    out.byte(kind).u16(len(body)).byte(0).bytes(body)


def _heap_id(out: _Out, hid: Tuple[int, int, int], heap_at: List[int]) -> None:
    """The 16 bytes that stand for one variable-length string."""
    collection, index, length = hid
    out.u32(length).u64(heap_at[collection]).u32(index)


def write_hdf5(root: Group) -> bytes:
    """The file, as bytes (``writeHDF5``).

    ``root`` is the tree, from :func:`group`, :func:`dataset` and :func:`put`.
    For the same tree the bytes are the application's, to the byte. Raises
    :class:`HDF5Error` when the root is not a group, a link has an empty name,
    or a datatype is not one the writer knows.
    """
    if getattr(root, 'kind', None) != 'group':
        raise HDF5Error('The root of a file is a group')
    strings, heap_at, objects, root_object, size = _plan(root)
    out = _Out(size)

    # --- the superblock, version 2.
    (out.bytes(SIGNATURE).byte(2).byte(8).byte(8).byte(0)
        .u64(0)  # base address
        .u64(-1)  # no superblock extension
        .u64(size)  # end of file
        .u64(root_object.addr)
        .checksum(0))

    # --- the strings.
    for c, objs in enumerate(strings.collections):
        start = heap_at[c]
        total = strings.size(c)
        out.seek(start).bytes(b'GCOL').byte(1).bytes(b'\0\0\0').u64(total)
        for i, data in enumerate(objs):
            # The reference count is what libhdf5 writes for a string the file
            # itself points at, which is nothing: it counts *references*, the
            # HDF5 kind, and there are none.
            out.u16(i + 1).u16(0).u32(0).u64(len(data))
            out.bytes(data)
            out.at = -(-out.at // 8) * 8
        # What is left is one object with index zero, which is how a collection
        # says "free space" -- and there always is some.
        left = start + total - out.at
        if left >= 16:
            out.u16(0).u16(0).u32(0).u64(left)

    # --- the objects.
    for o in objects:
        out.seek(o.addr).bytes(b'OHDR').byte(2).byte(2)
        out.u32(o.header_size - 14)
        node = o.node
        if node.kind == 'group':
            # Undefined addresses for both indexes: the links are here, in this
            # header, rather than in a fractal heap.
            _message(out, MSG_LINK_INFO, [0, 0] + [255] * 16)
            _message(out, MSG_GROUP_INFO, [0, 0])
            for _, name_bytes, child in o.children:
                long = len(name_bytes) > 255
                link = [1, 1 if long else 0]
                if long:
                    link.extend([len(name_bytes) & 0xFF, (len(name_bytes) >> 8) & 0xFF])
                else:
                    link.append(len(name_bytes))
                link.extend(name_bytes)
                link.extend(_le(child.addr))
                _message(out, MSG_LINK, link)
        else:
            _message(out, MSG_DATASPACE, _dataspace_bytes(o.dims))
            _message(out, MSG_DATATYPE, _datatype_bytes(node.dt))
            # Version 3, allocated late, with no fill value of its own: every
            # byte of this dataset is written, so there is nothing to fill.
            _message(out, MSG_FILL_VALUE, [3, 2])
            _message(out, MSG_LAYOUT, [3, 1] + _le(o.data_addr) + _le(o.data_size))
        if o.attrs:
            _message(out, MSG_ATTRIBUTE_INFO, [0, 0] + [255] * 16)
            for a in o.attrs:
                dt = _datatype_bytes(a.dt)
                ds = _dataspace_bytes(a.dims)
                out.byte(MSG_ATTRIBUTE).u16(_attribute_size(a)).byte(0)
                out.byte(3).byte(0).u16(len(a.name_bytes) + 1).u16(len(dt)).u16(len(ds)).byte(0)
                out.bytes(a.name_bytes).byte(0).bytes(dt).bytes(ds)
                if a.dt.kind == 'vlenstr':
                    for hid in a.values:
                        _heap_id(out, hid, heap_at)
                else:
                    for v in a.values:
                        struct.pack_into('<d', out.buf, out.at, v)
                        out.at += 8
        out.checksum(o.addr)

    # --- the numbers.
    for o in objects:
        if o.node.kind != 'dataset' or not o.data_size:
            continue
        out.seek(o.data_addr)
        dt, data = o.node.dt, o.node.data
        if dt.kind == 'vlenstr':
            for hid in o.ids:
                _heap_id(out, hid, heap_at)
            continue
        if dt.kind == 'float' and dt.size == 8:
            raw = _f64_bytes(data)
        elif dt.kind == 'float':
            raw = _f32_bytes(data)
        else:
            raw = _i32_bytes(data)
        out.buf[o.data_addr:o.data_addr + len(raw)] = raw
    return bytes(out.buf)
