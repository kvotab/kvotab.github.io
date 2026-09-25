"""Reading HDF5 as Kompartment reads it.

A port of the application's ``src/io/hdf5read.js``: every dataset in a file,
by path, with its values, its dimensions and its attributes, read the way the
application reads them -- the same values, the same refusals, the same
messages -- so a data file or a result file opens in Python as it opens in
the page::

    from kompartment.io.hdf5read import read_hdf5

    got = read_hdf5(open('results.h5', 'rb').read())   # or read_hdf5('results.h5')
    for d in got['datasets']:
        print(d['path'], d['dims'], d['attrs'].get('unit'), d['values'][:3])
    print(got['problems'])

It takes what it is given, which is whatever wrote the file:

- **Version 1 object headers**, where a group is a *symbol table* -- a
  version 1 B-tree of names beside a local heap holding them. That is what
  h5py and libhdf5 write by default, and what the data files arrive as.
- **Version 2 object headers**, where a group's links are messages in its own
  header. That is what :mod:`kompartment.io.hdf5` and the application write.
- **Chunked datasets**, with the deflate, shuffle and Fletcher-32 filters
  undone: what h5py writes the moment anything is compressed.

Numbers, integers included, come back as ``array('d')`` -- the bytes and
nothing else, as the application keeps them in a ``Float64Array`` -- strings
as lists of ``str``, and an empty or unreadable dataset as ``[]``. An
attribute holding one value comes back as that value rather than a list of
one. What the reader does not open -- compound, enumerated-sequence and
reference types, fractal-heap links, more than two dimensions -- is refused by
name in ``problems`` rather than coming back empty.

References: the HDF5 File Format Specification version 3.0 -- II.A (the
superblock), III.A (symbol tables), IV.A (object headers, both versions) and
their messages, V.A (version 1 B-trees).
"""

from __future__ import annotations

import math
import os
import struct
import zlib
from array import array
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from ..errors import KompartmentError
from .csv import js_string

__all__ = ['HDF5ReadError', 'read_hdf5']

SIGNATURE = b'\x89HDF\r\n\x1a\n'

MSG_NIL = 0x00
MSG_DATASPACE = 0x01
MSG_DATATYPE = 0x03
MSG_FILL_OLD = 0x04
MSG_FILL = 0x05
MSG_LINK = 0x06
MSG_LAYOUT = 0x08
MSG_ATTRIBUTE = 0x0c
MSG_FILTER = 0x0b
MSG_OBJECT_HEADER_CONTINUATION = 0x10
MSG_SYMBOL_TABLE = 0x11

# The filters a chunk may have been put through, by the id HDF5 gives them.
FILTER_DEFLATE = 1
FILTER_SHUFFLE = 2
FILTER_FLETCHER32 = 3

#: The most one compressed chunk may expand to, as the application's inflater allows.
MAX_INFLATED = 256 * 1024 * 1024

_U16 = struct.Struct('<H').unpack_from
_U32 = struct.Struct('<I').unpack_from


class HDF5ReadError(KompartmentError, ValueError):
    """A file this reader cannot read: not HDF5, a superblock or object header
    version it does not know, or an address past what a file can hold."""


class _OutOfBounds(HDF5ReadError):
    """What JavaScript calls a RangeError, in its words: a read past the end of
    the bytes (``DataView``'s message, the default), or an array longer than an
    array can be -- so a damaged file is reported as the application reports it."""

    def __init__(self, message: str = 'Offset is outside the bounds of the DataView') -> None:
        super().__init__(message)


#: The longest ``Float64Array`` and the longest ``Array`` the application's
#: JavaScript engine (V8) will make.
MAX_TYPED_ARRAY_LENGTH = 2 ** 32
MAX_ARRAY_LENGTH = 2 ** 32 - 1


def _utf8(b: bytes) -> str:
    """``TextDecoder('utf-8')``: invalid bytes as U+FFFD, a leading BOM dropped."""
    return b.decode('utf-8-sig', 'replace')


class _Reader:
    """A cursor over the file, with the offset and length sizes it was told."""

    def __init__(self, data: bytes, offset_size: int = 8, length_size: int = 8) -> None:
        self.u8 = data
        self.n = len(data)
        self.offset_size = offset_size
        self.length_size = length_size
        # Global heap collections already walked, for globalHeapString.
        self.heaps: Dict[int, Dict[str, Any]] = {}

    def _check(self, p: int, k: int) -> None:
        if p < 0 or p + k > self.n:
            raise _OutOfBounds()

    def u8_at(self, p: int) -> int:
        self._check(p, 1)
        return self.u8[p]

    def u16(self, p: int) -> int:
        self._check(p, 2)
        return _U16(self.u8, p)[0]

    def u32(self, p: int) -> int:
        self._check(p, 4)
        return _U32(self.u8, p)[0]

    def unpack(self, fmt: str, p: int, size: int) -> Any:
        self._check(p, size)
        return struct.unpack_from(fmt, self.u8, p)[0]

    def sized(self, p: int, size: int) -> Optional[int]:
        """An offset or a length, which are 2, 4 or 8 bytes depending on the
        file. ``None`` is the all-ones "not here" address."""
        if size == 2:
            v = self.u16(p)
            return None if v == 0xFFFF else v
        if size == 4:
            v = self.u32(p)
            return None if v == 0xFFFFFFFF else v
        if size == 8:
            lo = self.u32(p)
            hi = self.u32(p + 4)
            if lo == 0xFFFFFFFF and hi == 0xFFFFFFFF:
                return None
            if hi > 0x1FFFFF:
                raise HDF5ReadError('This file addresses more than 8 EB.')
            return hi * 4294967296 + lo
        v = 0
        for i in range(size - 1, -1, -1):
            v = v * 256 + self.u8_at(p + i)
        return v

    def offset(self, p: int) -> Optional[int]:
        return self.sized(p, self.offset_size)

    def length(self, p: int) -> Optional[int]:
        return self.sized(p, self.length_size)

    def name(self, p: Optional[int]) -> Tuple[str, int]:
        """A NUL-terminated name, and where the next byte is. A position that
        is not a number (``None``) reads as the empty name, as NaN does in the
        JavaScript."""
        if p is None:
            return '', 0
        end = self.u8.find(b'\0', p) if p < self.n else -1
        if end < 0:
            end = max(p, self.n)
        return _utf8(self.u8[p:end]), end + 1

    def is_(self, p: Optional[int], text: bytes) -> bool:
        if p is None or p < 0:
            return False
        return self.u8[p:p + len(text)] == text


def _find_superblock(data: bytes) -> int:
    """Where the superblock is: byte 0, or a power-of-two offset after it."""
    at = 0
    while at < len(data):
        if data[at:at + 8] == SIGNATURE:
            return at
        if at > 0x100000:
            break
        at = 512 if at == 0 else at * 2
    raise HDF5ReadError('This is not an HDF5 file — the signature is missing.')


def _superblock(data: bytes) -> Tuple[_Reader, Optional[int]]:
    """The superblock, and where the root object is.

    Versions 0 and 1 end in a *symbol table entry* for the root group, whose
    second field is the object header's address. Versions 2 and 3 name that
    address directly.
    """
    base = _find_superblock(data)
    probe = _Reader(data)
    version = probe.u8_at(base + 8)
    if version > 3:
        raise HDF5ReadError(f'Superblock version {version} is newer than this reader.')
    if version <= 1:
        offset_size = probe.u8_at(base + 13)
        length_size = probe.u8_at(base + 14)
        r = _Reader(data, offset_size, length_size)
        # Base address, free-space, end-of-file, driver, then the root entry.
        p = base + 24 + (4 if version == 1 else 0)
        p += offset_size * 4
        # A symbol table entry: link name offset, object header address, ...
        return r, r.offset(p + offset_size)
    offset_size = probe.u8_at(base + 9)
    length_size = probe.u8_at(base + 10)
    r = _Reader(data, offset_size, length_size)
    return r, r.offset(base + 12 + offset_size * 3)


# --- object headers -----------------------------------------------------------

Message = Tuple[int, int, int]  # (type, at, size)


def _messages_of(r: _Reader, address: Optional[int], seen: Optional[Set[int]] = None) -> List[Message]:
    """Every message of one object, both header versions, continuations followed."""
    seen = set() if seen is None else seen
    if address is None or address in seen:
        return []
    seen.add(address)
    return _messages_v2(r, address, seen) if r.is_(address, b'OHDR') else _messages_v1(r, address, seen)


def _messages_v1(r: _Reader, address: int, seen: Set[int]) -> List[Message]:
    """Version 1: a chunk of messages, and every continuation it points at.

    Driven by the chunk's *bounds* rather than by the message count, and a
    continuation does not end the chunk it sits in: an object with two of them
    has messages between the two and after the second.
    """
    version = r.u8_at(address)
    if version != 1:
        raise HDF5ReadError(f'Object header version {version} is not one this reads.')
    out: List[Message] = []
    queue = [(address + 16, address + 16 + r.u32(address + 8))]
    while queue:
        p, end = queue.pop(0)
        while p + 8 <= end:
            kind = r.u16(p)
            size = r.u16(p + 2)
            at = p + 8
            p = at + size
            if p > end:
                break
            # A NIL message is the space a deleted one left behind.
            if kind == MSG_NIL:
                continue
            if kind == MSG_OBJECT_HEADER_CONTINUATION:
                to = r.offset(at)
                ln = r.length(at + r.offset_size)
                if to is not None and ln and to not in seen:
                    seen.add(to)
                    queue.append((to, to + ln))
                continue
            out.append((kind, at, size))
    return out


def _messages_v2(r: _Reader, address: int, seen: Set[int]) -> List[Message]:
    version = r.u8_at(address + 4)
    if version != 2:
        raise HDF5ReadError(f'Object header version {version} is not one this reads.')
    flags = r.u8_at(address + 5)
    p = address + 6
    if flags & 0x20:
        p += 16  # access, modification, change, birth times
    if flags & 0x10:
        p += 4  # maximum compact and minimum dense
    size_bytes = [1, 2, 4, 8][flags & 3]
    chunk_size = r.sized(p, size_bytes)
    p += size_bytes
    out: List[Message] = []
    if chunk_size is None:  # NaN in the JavaScript: no message is read
        return out
    # The gap at the end is the checksum, which is not read.
    _messages_v2_chunks(r, p, p + chunk_size - 4, bool(flags & 4), seen, out)
    return out


def _messages_v2_chunks(r: _Reader, p: int, end: int, tracked: bool, seen: Set[int],
                        out: List[Message]) -> None:
    """The messages of a version 2 chunk, a continuation's messages in their
    place. The JavaScript recurses into each continuation (``continuedV2``);
    this keeps a stack of its own, in the same order."""
    stack = [(p, end)]
    while stack:
        p, end = stack.pop()
        while p + 4 <= end:
            kind = r.u8_at(p)
            ln = r.u16(p + 1)
            at = p + 4 + (2 if tracked else 0)
            p = at + ln
            if kind == MSG_OBJECT_HEADER_CONTINUATION:
                to = r.offset(at)
                how_big = r.length(at + r.offset_size)
                if to is None or to in seen:
                    continue
                seen.add(to)
                if not r.is_(to, b'OCHK'):
                    continue
                stack.append((p, end))
                stack.append((to + 4, to + (how_big or 0) - 4))
                break
            out.append((kind, at, ln))


# --- links: both ways a group holds its children --------------------------------

def _link_message(r: _Reader, at: int) -> Optional[Dict[str, Any]]:
    """A version 2 LINK message: ``{name, address}``."""
    version = r.u8_at(at)
    if version != 1:
        return None
    flags = r.u8_at(at + 1)
    p = at + 2
    if flags & 0x08:
        p += 1  # link type, when not hard
    if flags & 0x04:
        p += 8  # creation order
    if flags & 0x10:
        p += 1  # character set
    len_bytes = [1, 2, 4, 8][flags & 3]
    ln = r.sized(p, len_bytes)
    p += len_bytes
    if ln is None:
        # An all-ones length is NaN in the JavaScript: the name reads as
        # empty, and the address is read from where a NaN offset reads, byte 0.
        name, address_at = '', 0
    else:
        name = _utf8(r.u8[p:p + ln])
        address_at = p + ln
    # Only a hard link has an address; a soft or external one names a path.
    if flags & 0x08 and r.u8_at(at + 2) != 0:
        return {'name': name, 'address': None}
    return {'name': name, 'address': r.offset(address_at)}


def _local_heap(r: _Reader, address: Optional[int]) -> Optional[Callable[[Optional[int]], str]]:
    """A local heap: the strings a symbol table's names are offsets into."""
    if address is None or not r.is_(address, b'HEAP'):
        return None
    data = r.offset(address + 8 + r.length_size * 2)

    def name_of(offset: Optional[int]) -> str:
        if data is None:
            return ''
        return r.name(None if offset is None else data + offset)[0]

    return name_of


def _symbol_table(r: _Reader, tree_at: Optional[int], heap_at: Optional[int],
                  out: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every child of a version 1 group, by walking its B-tree."""
    name_of = _local_heap(r, heap_at)
    if not name_of:
        return out
    _walk_tree(r, tree_at, name_of, out, set())
    return out


def _walk_tree(r: _Reader, address: Optional[int], name_of: Callable[[Optional[int]], str],
               out: List[Dict[str, Any]], seen: Set[int]) -> None:
    if address is None or address in seen or not r.is_(address, b'TREE'):
        return
    seen.add(address)
    kind = r.u8_at(address + 4)
    level = r.u8_at(address + 5)
    used = r.u16(address + 6)
    # Keys and children alternate: K+1 keys around K children. A group node's
    # key is one length-sized offset into the heap.
    p = address + 8 + r.offset_size * 2
    for _ in range(used):
        p += r.length_size  # the key before this child
        child = r.offset(p)
        p += r.offset_size
        if kind != 0:
            continue  # a chunk tree, not a group's
        if level > 0:
            _walk_tree(r, child, name_of, out, seen)
        else:
            _read_snod(r, child, name_of, out)


def _read_snod(r: _Reader, address: Optional[int], name_of: Callable[[Optional[int]], str],
               out: List[Dict[str, Any]]) -> None:
    if address is None or not r.is_(address, b'SNOD'):
        return
    used = r.u16(address + 6)
    entry = r.offset_size * 2 + 4 + 4 + 16
    for i in range(used):
        at = address + 8 + i * entry
        name = name_of(r.offset(at))
        header = r.offset(at + r.offset_size)
        kind = r.u32(at + r.offset_size * 2)
        # Cache type 2 is a symbolic link, which points at a path rather than
        # an object; there is nothing under it to read.
        if kind == 2:
            continue
        out.append({'name': name, 'address': header})


# --- datatype, dataspace, layout ----------------------------------------------

_UNSUPPORTED_CLASSES = {
    2: 'a time', 4: 'a bitfield', 5: 'an opaque type', 6: 'a compound type',
    7: 'a reference', 10: 'an array',
}


def _datatype(r: _Reader, at: int) -> Dict[str, Any]:
    b0 = r.u8_at(at)
    cls = b0 & 0x0F
    flags = r.u8_at(at + 1) | (r.u8_at(at + 2) << 8) | (r.u8_at(at + 3) << 16)
    size = r.u32(at + 4)
    if cls == 0:
        return {'cls': 'int', 'size': size, 'signed': bool(flags & 0x08), 'little': not flags & 1}
    if cls == 1:
        return {'cls': 'float', 'size': size, 'little': not flags & 1}
    if cls == 3:
        return {'cls': 'string', 'size': size, 'padding': flags & 0x0F}
    if cls == 9:
        # A variable-length *string* is type 1 in the low nibble of the flags;
        # anything else is a variable-length sequence of something.
        if flags & 0x0F != 1:
            return {'cls': 'unsupported', 'what': 'a variable-length sequence'}
        return {'cls': 'vlenstr', 'size': size}
    if cls == 8:
        # An enumeration is a base type with names hung off it -- a Python
        # True written by h5py is one -- and what comes back is the number.
        base = _datatype(r, at + 8)
        return base if base['cls'] == 'unsupported' else dict(base, size=base['size'] or size)
    return {'cls': 'unsupported', 'what': _UNSUPPORTED_CLASSES.get(cls, f'datatype class {cls}')}


def _dataspace(r: _Reader, at: int) -> Dict[str, Any]:
    version = r.u8_at(at)
    rank = r.u8_at(at + 1)
    r.u8_at(at + 2)  # the flags, read and not used, as in the JavaScript
    # Version 2 says the kind in byte 3: 0 is *scalar* -- one element, no
    # dimensions -- 1 is simple, and 2 is the null dataspace that holds nothing.
    if version == 2 and r.u8_at(at + 3) == 2:
        return {'dims': [], 'count': 0}
    p = at + (8 if version == 1 else 4)
    dims: List[Optional[int]] = []
    for _ in range(rank):
        dims.append(r.length(p))
        p += r.length_size
    if rank == 0:
        return {'dims': dims, 'count': 1}
    # Multiplied as JavaScript multiplies, in doubles: an undefined dimension
    # makes it NaN, and a product past 2^53 rounds as it does there.
    count = 1.0
    for d in dims:
        count = math.nan if d is None else count * d
    return {'dims': dims, 'count': count}


def _layout(r: _Reader, at: int) -> Dict[str, Any]:
    """Where the data is: ``{kind, address, size}`` or a refusal."""
    version = r.u8_at(at)
    if version in (1, 2):
        rank = r.u8_at(at + 1)
        cls = r.u8_at(at + 2)
        if cls == 0:
            return {'kind': 'compact', 'address': at + 8 + rank * 4 + 4, 'size': None}
        if cls == 1:
            return {'kind': 'contiguous', 'address': r.offset(at + 8), 'size': None}
        # Version 1 puts the address first and the sizes after, and counts the
        # element size among them exactly as version 3 does.
        address = r.offset(at + 8)
        dims = [r.u32(at + 8 + r.offset_size + i * 4) for i in range(rank)]
        return {'kind': 'chunked', 'address': address, 'ndims': rank, 'chunk': dims[:-1],
                'elem': dims[rank - 1] if rank else None}
    if version in (3, 4):
        cls = r.u8_at(at + 1)
        if cls == 0:
            return {'kind': 'compact', 'address': at + 4, 'size': r.u16(at + 2)}
        if cls == 1:
            return {'kind': 'contiguous', 'address': r.offset(at + 2),
                    'size': r.length(at + 2 + r.offset_size)}
        if cls == 2:
            # `ndims` counts one more than the dataset's rank: the last entry
            # of the size list is the element size, not a dimension.
            ndims = r.u8_at(at + 2)
            address = r.offset(at + 3)
            dims = [r.u32(at + 3 + r.offset_size + i * 4) for i in range(ndims)]
            return {'kind': 'chunked', 'address': address, 'ndims': ndims, 'chunk': dims[:-1],
                    'elem': dims[ndims - 1] if ndims else None}
        return {'kind': 'unsupported', 'what': 'a virtual layout'}
    return {'kind': 'unsupported', 'what': f'layout version {version}'}


# --- chunks -------------------------------------------------------------------

def _filter_pipeline(r: _Reader, at: int) -> List[Dict[str, Any]]:
    """The filters a dataset's chunks were put through, in the order they were
    applied. Undoing them means walking this backwards."""
    version = r.u8_at(at)
    count = r.u8_at(at + 1)
    p = at + (8 if version == 1 else 2)
    out: List[Dict[str, Any]] = []
    i = 0
    while i < count and p < r.n:
        fid = r.u16(p)
        # Version 2 writes the name length only for a filter it does not know
        # by number; version 1 always writes it.
        named = version == 1 or fid >= 256
        name_len = r.u16(p + 2) if named else 0
        values = r.u16(p + 6)
        p += 8 + (-(-name_len // 8) * 8 if version == 1 else name_len)
        client = [r.u32(p + k * 4) for k in range(values)]
        p += -(-values // 2) * 8 if version == 1 else values * 4
        out.append({'id': fid, 'client': client})
        i += 1
    return out


#: zlib's words for a damaged stream, and the application's inflater's for the
#: same fault. The rest of zlib's refusals have no one counterpart -- that
#: inflater does not check its Huffman tables, and names the symbol it choked on
#: instead -- and are passed on in zlib's words.
_INFLATE_WORDS = {
    'invalid distance too far back': 'Back-reference points before the output',
    'invalid stored block lengths': 'Stored block length check failed',
    'invalid block type': 'Invalid block type',
}


def _inflate(data: bytes) -> bytes:
    """Raw deflate, bounded as the application's inflater is bounded."""
    d = zlib.decompressobj(-15)
    try:
        out = d.decompress(data, MAX_INFLATED + 1)
    except zlib.error as e:
        said = str(e)
        for words, theirs in _INFLATE_WORDS.items():
            if said.endswith(words):
                raise HDF5ReadError(theirs) from None
        raise HDF5ReadError(said) from None
    if len(out) > MAX_INFLATED or d.unconsumed_tail:
        raise HDF5ReadError(
            f'the entry expands to more than {round(MAX_INFLATED / 1048576)} MB, which is far '
            'larger than any real model -- the archive is either damaged or built to exhaust memory')
    if not d.eof:
        raise HDF5ReadError('Compressed data ended unexpectedly')
    return out


def _unfilter(data: bytes, filters: List[Dict[str, Any]], mask: int) -> bytes:
    """A chunk's bytes, with whatever was done to them undone."""
    out = data
    for i in range(len(filters) - 1, -1, -1):
        # A chunk may skip a filter -- the pipeline is per dataset and the mask
        # is per chunk, which is how HDF5 stores an incompressible one.
        if mask & (1 << (i & 31)):
            continue
        f = filters[i]
        if f['id'] == FILTER_DEFLATE:
            # The gzip filter writes a zlib stream: two header bytes, the
            # deflate data, then an Adler-32 this does not check.
            out = _inflate(out[2:])
        elif f['id'] == FILTER_SHUFFLE:
            out = _unshuffle(out, (f['client'][0] if f['client'] else 0) or 1)
        elif f['id'] == FILTER_FLETCHER32:
            # A checksum of the four bytes at the end, and nothing else.
            out = out[:max(0, len(out) - 4)]
        else:
            raise HDF5ReadError(f"filter {f['id']} is one this reader does not undo")
    return out


def _unshuffle(data: bytes, size: int) -> bytes:
    """Shuffle, undone: the filter writes every element's first byte, then
    every element's second, and so on."""
    if size <= 1:
        return data
    n = len(data) // size
    if n == 0:
        # Not one whole element: all of it is the tail, copied as it lies. (The
        # JavaScript walks `size` empty rows first, which with a nonsense size
        # read out of a damaged pipeline is billions of them.)
        return bytes(data)
    out = bytearray(len(data))
    for b in range(size):
        out[b:n * size:size] = data[b * n:(b + 1) * n]
    # A tail that is not a whole element is copied as it lies.
    out[n * size:] = data[n * size:]
    return bytes(out)


def _to_fixed0(x: float) -> str:
    """``x.toFixed(0)``: halves away from zero, on the exact binary value, and
    past 10^21 the number as ``String`` writes it."""
    if abs(x) >= 1e21:
        return js_string(x)
    return str(int(Decimal(x).quantize(Decimal(1), rounding=ROUND_HALF_UP)))


def _read_chunks(r: _Reader, where: Dict[str, Any], filters: List[Dict[str, Any]],
                 dims: List[Optional[int]], elem: int) -> bytes:
    """Every chunk of a dataset, assembled into one run of bytes.

    The B-tree's keys carry each chunk's *offset* in the dataset, so a chunk is
    placed rather than appended.
    """
    total = 1.0  # in doubles, as the JavaScript multiplies
    for d in dims:
        total = math.nan if d is None else total * d
    total = math.nan if elem is None else total * elem
    if math.isnan(total) or math.isinf(total) or total <= 0:
        return b''
    if total > 1 << 30:
        raise HDF5ReadError(f'{_to_fixed0(total / 1e6)} MB is more than this reads at once')
    out = bytearray(int(total))
    key_size = 4 + 4 + 8 * where['ndims']

    def on_chunk(key: int, address: int) -> None:
        size = r.u32(key)
        mask = r.u32(key + 4)
        offset = [r.sized(key + 8 + i * 8, 8) for i in range(where['ndims'] - 1)]
        try:
            data = _unfilter(r.u8[address:address + size], filters, mask)
        except Exception as e:  # noqa: BLE001 -- the JavaScript catches everything here
            raise HDF5ReadError(f'a chunk could not be read — {e}') from None
        _place(out, data, dims, where['chunk'], offset, elem)

    _walk_chunk_tree(r, where['address'], key_size, set(), on_chunk)
    return bytes(out)


def _walk_chunk_tree(r: _Reader, address: Optional[int], key_size: int, seen: Set[int],
                     on_chunk: Callable[[int, int], None]) -> None:
    if address is None or address in seen or not r.is_(address, b'TREE'):
        return
    seen.add(address)
    if r.u8_at(address + 4) != 1:
        return
    level = r.u8_at(address + 5)
    used = r.u16(address + 6)
    p = address + 8 + r.offset_size * 2
    for _ in range(used):
        key = p
        p += key_size
        child = r.offset(p)
        p += r.offset_size
        if level > 0:
            _walk_chunk_tree(r, child, key_size, seen, on_chunk)
        elif child is not None:
            on_chunk(key, child)


def _place(out: bytearray, data: bytes, dims: List[Optional[int]], chunk: List[int],
           offset: List[Optional[int]], elem: int) -> None:
    """One chunk's bytes into the dataset, at the offset its key gave."""
    if len(dims) <= 1:
        start = (offset[0] if offset and offset[0] is not None else 0) * elem
        room = min(len(data), len(out) - start)
        if room > 0:
            out[start:start + room] = data[:room]
        return
    # Two dimensions, which is a matrix of realisations: rows of the chunk go
    # into rows of the dataset, and a chunk narrower than the dataset leaves
    # the rest of each row alone.
    rows, cols = dims[0], dims[1]
    cr, cc = chunk[0], chunk[1]
    r0 = offset[0] if len(offset) > 0 and offset[0] is not None else 0
    c0 = offset[1] if len(offset) > 1 and offset[1] is not None else 0
    i = 0
    while i < cr and r0 + i < rows:
        width = min(cc, cols - c0) * elem
        start = i * cc * elem
        to = ((r0 + i) * cols + c0) * elem
        if start + width <= len(data) and to + width <= len(out):
            piece = data[start:start + width] if width > 0 else b''
            if to + len(piece) > len(out):
                raise _OutOfBounds('offset is out of bounds')
            out[to:to + len(piece)] = piece
        i += 1


def _falsy_count(n: Any) -> bool:
    """``!n`` for a count that may be NaN."""
    return n is None or n != n or n == 0


def _read_values(r: _Reader, typ: Dict[str, Any], space: Dict[str, Any],
                 where: Dict[str, Any]) -> Union[array, List[Any]]:
    """The elements themselves, as numbers or as strings."""
    count = space['count']
    if _falsy_count(count) or where.get('address') is None:
        return []
    n = int(count)
    p = where['address']
    cls = typ['cls']
    if cls in ('float', 'int') and n > MAX_TYPED_ARRAY_LENGTH:
        raise _OutOfBounds(f'Invalid typed array length: {js_string(count)}')
    if cls in ('string', 'vlenstr') and n > MAX_ARRAY_LENGTH:
        raise _OutOfBounds('Invalid array length')
    if cls == 'float':
        size = 4 if typ['size'] == 4 else 8
        order = '<' if typ['little'] else '>'
        r._check(p, n * size)
        return array('d', struct.unpack_from(f"{order}{n}{'f' if size == 4 else 'd'}", r.u8, p))
    if cls == 'int':
        size = typ['size']
        signed = typ['signed']
        if size in (1, 2, 4):
            # An unsigned 2- or 4-byte integer is read little-endian whatever
            # the type says, as the JavaScript reads it.
            order = '<' if typ['little'] or not signed else '>'
            code = {1: 'b', 2: 'h', 4: 'i'}[size]
            r._check(p, n * size)
            return array('d', struct.unpack_from(f'{order}{n}{code if signed else code.upper()}', r.u8, p))
        # One at a time, as the JavaScript reads them: an all-ones value is 0,
        # and one past 2^53 is refused with the reason it gives.
        values = []
        for i in range(n):
            v = r.sized(p + i * size, size)
            values.append(float(v if v is not None else 0))
        return array('d', values)
    if cls == 'string':
        size = typ['size']
        strings = []
        for i in range(n):
            raw = r.u8[p + i * size:p + (i + 1) * size]
            strings.append(_utf8(raw.rstrip(b'\0')))
        return strings
    if cls == 'vlenstr':
        return [_global_heap_string(r, p + i * typ['size']) for i in range(n)]
    return []


def _global_heap_string(r: _Reader, at: int) -> str:
    """A variable-length string, which is a pointer into a global heap collection.

    The id is a length, then the collection's address, then the object's index
    inside it. The collection is a run of objects each carrying its own size,
    walked from the start until the object is found -- here once per
    collection, remembering what it passed, which finds the same object and
    fails at the same place as walking it again for every string would.
    """
    length = r.u32(at)
    collection = r.offset(at + 4)
    index = r.u32(at + 4 + r.offset_size)
    if collection is None or not r.is_(collection, b'GCOL'):
        return ''
    heap = r.heaps.get(collection)
    if heap is None:
        p = collection + 8 + r.length_size
        heap = {'p': p, 'end': collection + (r.length(collection + 8) or 0), 'found': {}, 'done': False}
        r.heaps[collection] = heap
    found = heap['found']
    while index not in found and not heap['done']:
        p = heap['p']
        if not p + 8 <= heap['end']:
            heap['done'] = True
            break
        oid = r.u16(p)
        size = r.length(p + 8)
        body = p + 8 + r.length_size
        if oid == 0:
            heap['done'] = True
            break
        if oid not in found:
            found[oid] = (body, size)
        # Objects are padded to a multiple of eight.
        heap['p'] = body + -(-(size or 0) // 8) * 8
    if index not in found:
        return ''
    body, size = found[index]
    take = min(length, length if size is None else size)
    return _utf8(r.u8[body:body + take])


def _attribute(r: _Reader, at: int) -> Optional[Dict[str, Any]]:
    """One attribute message, whichever version wrote it."""
    version = r.u8_at(at)
    if version == 1:
        name_len = r.u16(at + 2)
        type_len = r.u16(at + 4)
        space_len = r.u16(at + 6)
        p = at + 8
        name = r.name(p)[0]
        p += -(-name_len // 8) * 8
        typ = _datatype(r, p)
        p += -(-type_len // 8) * 8
        space = _dataspace(r, p)
        p += -(-space_len // 8) * 8
        return {'name': name, 'value': _read_values(r, typ, space, {'address': p}), 'type': typ, 'space': space}
    if version not in (2, 3):
        return None
    flags = r.u8_at(at + 1)
    name_len = r.u16(at + 2)
    type_len = r.u16(at + 4)
    space_len = r.u16(at + 6)
    p = at + 8 + (1 if version == 3 else 0)
    name = _utf8(r.u8[p:p + name_len - 1]) if name_len >= 1 else ''
    p += name_len
    # A shared datatype or dataspace points elsewhere; a data file does not use
    # them, and reading one as if it were inline would be nonsense.
    if flags & 3:
        return {'name': name, 'value': [], 'shared': True}
    typ = _datatype(r, p)
    p += type_len
    space = _dataspace(r, p)
    p += space_len
    return {'name': name, 'value': _read_values(r, typ, space, {'address': p}), 'type': typ, 'space': space}


def _js_order(obj: Dict[str, Any]) -> Dict[str, Any]:
    """The keys of an object in the order JavaScript lists them: array indices
    first, in numeric order, then the rest as they were set."""
    def index(k: str) -> bool:
        return (k == '0' or (k[:1] in '123456789' and k.isdigit() and k.isascii())) and int(k) < 0xFFFFFFFF

    first = sorted((k for k in obj if index(k)), key=int)
    if not first:
        return obj
    return {**{k: obj[k] for k in first}, **{k: v for k, v in obj.items() if not index(k)}}


# --- the walk -------------------------------------------------------------------

def read_hdf5(data: Union[bytes, bytearray, memoryview, str, 'os.PathLike[str]']) -> Dict[str, Any]:
    """Every dataset in a file, by path (``readHDF5``).

    ``data`` is the file's bytes, or a path to read them from. Returns
    ``{'datasets': [...], 'problems': [...]}``: each dataset a dictionary of
    ``path`` (``'/Soil/Cs-137'``), ``values``, ``dims`` (``[]`` for a scalar,
    ``[times, realisations]`` for a matrix, whose values are flat with the
    last dimension varying fastest) and ``attrs``; each problem a sentence
    saying what could not be read and why.

    Numbers come back as ``array('d')``, strings as a list, and an attribute
    of one value as that value. The JavaScript is ``async``; this is not.
    Raises :class:`HDF5ReadError` for a file that is not HDF5 at all, or whose
    superblock or group structure cannot be followed.
    """
    if isinstance(data, (str, os.PathLike)):
        data = Path(data).read_bytes()
    buf = bytes(data)
    r, root = _superblock(buf)
    datasets: List[Dict[str, Any]] = []
    problems: List[str] = []
    _walk(r, root, '', datasets, problems, set(), 0)
    return {'datasets': datasets, 'problems': problems}


def _walk(r: _Reader, address: Optional[int], path: str, datasets: List[Dict[str, Any]],
          problems: List[str], seen: Set[int], depth: int) -> None:
    if address is None:
        return
    # A cycle is possible through a hard link that points back up, and a
    # hundred levels is far past any real tree.
    if address in seen or depth > 100:
        return
    seen.add(address)

    try:
        messages = _messages_of(r, address)
    except Exception as e:  # noqa: BLE001 -- as the JavaScript's catch, which takes everything
        problems.append(f"{path or '/'}: {e}")
        return

    attrs: Dict[str, Any] = {}
    for kind, at, _ in messages:
        if kind != MSG_ATTRIBUTE:
            continue
        try:
            a = _attribute(r, at)
            if not a or not a['name']:
                continue
            if a['name'] == '__proto__':
                # Assigned in the JavaScript, this sets the object's prototype
                # rather than adding a key, and the attribute is not among them.
                continue
            # One value rather than a list of one: `unit` is a string, not a
            # string in a box.
            attrs[a['name']] = a['value'][0] if len(a['value']) == 1 else a['value']
        except Exception as e:  # noqa: BLE001
            problems.append(f"{path or '/'}: an attribute could not be read — {e}")
    attrs = _js_order(attrs)

    children: List[Dict[str, Any]] = []
    for kind, at, _ in messages:
        if kind == MSG_LINK:
            link = _link_message(r, at)
            if link is not None and link['address'] is not None:
                children.append(link)
        elif kind == MSG_SYMBOL_TABLE:
            tree = r.offset(at)
            heap = r.offset(at + r.offset_size)
            _symbol_table(r, tree, heap, children)

    if children:
        for c in children:
            _walk(r, c['address'], f"{path}/{c['name']}", datasets, problems, seen, depth + 1)
        return

    # No links: a dataset, or an empty group. A dataset is the one with a
    # layout, which is what says where its elements are.
    layout_msg = next((m for m in messages if m[0] == MSG_LAYOUT), None)
    if layout_msg is None:
        return
    type_msg = next((m for m in messages if m[0] == MSG_DATATYPE), None)
    space_msg = next((m for m in messages if m[0] == MSG_DATASPACE), None)
    if type_msg is None or space_msg is None:
        return

    typ = _datatype(r, type_msg[1])
    if typ['cls'] == 'unsupported':
        problems.append(f"{path}: holds {typ['what']}, which this reader does not open.")
        return
    where = _layout(r, layout_msg[1])
    if where['kind'] == 'unsupported':
        problems.append(f"{path}: is stored with {where['what']}, which this reader does not open.")
        return
    space = _dataspace(r, space_msg[1])
    # Two dimensions is a matrix of realisations, which comes back flat with
    # `dims` saying how to read it: `values[t * n + i]` is realisation `i` at
    # time `t`.
    if len(space['dims']) > 2:
        shape = '×'.join('' if d is None else js_string(d) for d in space['dims'])
        problems.append(f'{path}: is {shape}, and this reads one or two dimensions.')
        return
    try:
        read = where
        reader = r
        if where['kind'] == 'chunked':
            # The chunks, assembled and unfiltered, read as if they had been
            # one run of bytes all along -- through a reader of their own, with
            # the default eight-byte offsets.
            pipe = next((m for m in messages if m[0] == MSG_FILTER), None)
            chunks = _read_chunks(r, where, _filter_pipeline(r, pipe[1]) if pipe else [],
                                  space['dims'], where['elem'] or typ['size'])
            reader = _Reader(chunks)
            read = {'kind': 'contiguous', 'address': 0, 'size': len(chunks)}
        datasets.append({
            'path': path,
            'values': _read_values(reader, typ, space, read),
            'dims': space['dims'],
            'attrs': attrs,
        })
    except Exception as e:  # noqa: BLE001
        problems.append(f'{path}: {e}')
