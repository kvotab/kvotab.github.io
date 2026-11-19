"""The entries of a ZIP archive, read as the application reads one: ``unzip``
in ``src/io/zip.js``, which is what reads an Ecolego project, a workbook, a
model saved as an archive and the run beside it.

The end record nearest the end of the file is the one read; the ZIP64 end
record where the locator says it is; as many central records as the end
record counts, from where it says they start; each entry's name as UTF-8
whatever its flag says, less a leading byte-order mark; ZIP64 sizes from the
first ZIP64 record only. Stored and deflated entries only, no encrypted ones,
no CRC check. A deflated ``.xml`` entry is inflated as the directory is read,
everything else when it is first asked for, all of it within one allowance
for the whole archive (256 MB) and one for each entry. A name repeated in the
directory keeps its first place and its last entry, as a JavaScript ``Map``
does. Every number the file gives is checked before it is used, and what
cannot be read is said in the application's words.

A 64-bit count from the file is kept whole here, where the application holds
it as a double: no comparison below can tell the two apart -- one that large
is past the end of any archive either way -- and a message writes it as
JavaScript writes the double that holds it.

The bytes are inflated by :mod:`zlib`, the application's by its own inflater
or the platform's: a damaged deflate stream is named in zlib's words where
the two do not name it alike (see ``_INFLATE_MESSAGES``).
"""

from __future__ import annotations

import math
import zlib
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple, Type

from ..jsonio import js_number

#: The most one entry, and the whole archive, may expand to (``MAX_INFLATED``).
MAX_INFLATED = 256 * 1024 * 1024


class ZipError(ValueError):
    """An archive, or an entry of one, that cannot be read: the application's ``ZipError``."""


def _number(x: float) -> str:
    """``String(x)`` of a number the file gave, as the double that holds it."""
    return js_number(float(x))


def _mb(x: float) -> str:
    """``Math.round(x / 1048576)``, written as JavaScript writes it."""
    return js_number(float(math.floor(float(x) / 1048576 + 0.5)))


# zlib's words for the damage the application's own inflater (src/io/inflate.js,
# which is what Node reads archives with) names the same way. Anything else in
# a damaged entry is said in zlib's words: the two decoders do not notice every
# fault at the same point, so no table could make them agree on all of them.
_INFLATE_MESSAGES = {
    'invalid block type': 'Invalid block type',
    'invalid stored block lengths': 'Stored block length check failed',
    'invalid distance too far back': 'Back-reference points before the output',
}


class ZipEntries(Mapping[str, bytes]):
    """The entries of an archive, by name in the directory's order: a mapping
    whose values are produced on first access and kept (``ZipEntries`` in
    ``src/io/zip.js``). Iterating it gives the names; ``items()`` inflates."""

    def __init__(self, inflate_limit: int, entry_limit: int, error: Type[Exception]) -> None:
        self._entries: Dict[str, Any] = {}
        self.limit = inflate_limit
        self.entry = entry_limit
        self.spent = 0
        self.error = error

    def __getitem__(self, name: str) -> bytes:
        held = self._entries[name]
        if callable(held):
            held = held()
            self._entries[name] = held
        return held

    def __iter__(self) -> Iterator[str]:
        return iter(list(self._entries))

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: object) -> bool:
        return name in self._entries

    def names(self) -> List[str]:
        return list(self._entries)

    # The decompression allowance, shared by every entry (`Budget`).
    def _check(self, name: str, size: float) -> None:
        if size <= self.limit - self.spent:
            return
        raise self.error(
            f"'{name}' takes this archive past the {_mb(self.limit)} MB this reader will decompress in total: "
            f'{_mb(self.spent)} MB have come out already and this entry adds {_mb(size)} more. No real project '
            'expands that far, so the archive is either damaged or built to exhaust memory.')

    def _inflate(self, name: str, raw: bytes, expected: int) -> bytes:
        """One deflated entry, within what is left of the allowance, checked
        against the size the directory claims (``inflateEntry``)."""
        if expected > self.entry:
            raise self.error(
                f"'{name}' says it expands to {_mb(expected)} MB, past the {_mb(self.entry)} MB this reader will "
                'decompress. No real model is that large.')
        self._check(name, expected)
        limit = min(self.entry, self.limit - self.spent)
        d = zlib.decompressobj(-15)
        try:
            buf = d.decompress(raw, limit + 1)
        except zlib.error as e:
            why = str(e).split(': ', 1)[-1]
            raise self.error(f"Could not decompress '{name}': {_INFLATE_MESSAGES.get(why, why)}") from None
        if len(buf) > limit:
            raise self.error(
                f"Could not decompress '{name}': the entry expands to more than {_mb(limit)} MB, which is far "
                'larger than any real model -- the archive is either damaged or built to exhaust memory')
        if not d.eof:
            raise self.error(f"Could not decompress '{name}': Compressed data ended unexpectedly")
        self._check(name, len(buf))
        self.spent += len(buf)
        if expected and len(buf) != expected:
            raise self.error(
                f"'{name}' inflated to {len(buf)} bytes but the directory says {_number(expected)}; the archive "
                'looks damaged.')
        return buf

    def _put(self, name: str, held: Any) -> None:
        # `Map.set`: a name already there keeps its place.
        self._entries[name] = held


def _u16(data: bytes, at: int) -> int:
    return int.from_bytes(data[at:at + 2], 'little')


def _u32(data: bytes, at: int) -> int:
    return int.from_bytes(data[at:at + 4], 'little')


def _u64(data: bytes, at: int) -> int:
    return int.from_bytes(data[at:at + 8], 'little')


def _end_record(data: bytes) -> Optional[Tuple[int, int, int]]:
    """``findEOCD``: the end of central directory record in the last 64 KB, the
    one nearest the end, as ``(where, entries, directory offset)``; None when
    there is none."""
    size = len(data)
    if size < 22:
        return None
    at = data.rfind(b'PK\x05\x06', max(0, size - 0x10000 - 22), size - 18)
    if at < 0:
        return None
    return at, _u16(data, at + 10), _u32(data, at + 16)


def _zip64_end(data: bytes, end_at: int, error: Type[Exception]) -> Optional[Tuple[int, int]]:
    """``findZip64``: the ZIP64 end record the locator before the end record
    points at, as ``(entries, directory offset)``; None when there is none."""
    locator = end_at - 20
    if locator < 0 or locator + 20 > len(data):
        return None
    if data[locator:locator + 4] != b'PK\x06\x07':
        return None
    at = _u64(data, locator + 8)
    # 56 bytes: through the central directory offset, the last field wanted.
    if at > 2 ** 53 - 1 or at + 56 > len(data):
        raise error(f'This archive says its ZIP64 directory is at byte {at}, which is outside its own '
                    f'{len(data)} bytes.')
    if data[at:at + 4] != b'PK\x06\x06':
        return None
    return _u64(data, at + 32), _u64(data, at + 48)


def _zip64_sizes(data: bytes, start: int, length: int, sizes: Tuple[int, int, int], name: str,
                 error: Type[Exception]) -> Tuple[int, int, int]:
    """``readZip64Extra``: the sizes and offset a central record left at
    0xFFFFFFFF, from the first ZIP64 record in its extra field -- the
    uncompressed size, the compressed size and the offset, those that are
    saturated, in that order. Any record after the first is not read."""
    expected, compressed, offset = sizes
    p = start
    # The walk is clamped to the archive, and each 64-bit read to its record.
    end = min(start + length, len(data))
    while p + 4 <= end:
        kind = _u16(data, p)
        size = _u16(data, p + 2)
        if kind == 0x0001:
            q = p + 4
            stop = min(p + 4 + size, end)

            def take() -> int:
                nonlocal q
                if q + 8 > stop:
                    raise error(f"The ZIP64 record for '{name}' says it is {size} bytes long but does not hold the "
                                'sizes it promises; the archive looks damaged.')
                v = _u64(data, q)
                q += 8
                return v
            if expected == 0xFFFFFFFF:
                expected = take()
            if compressed == 0xFFFFFFFF:
                compressed = take()
            if offset == 0xFFFFFFFF:
                offset = take()
            break
        p += 4 + size
    return expected, compressed, offset


def _without_bom(text: str) -> str:
    return text[1:] if text.startswith('\ufeff') else text


def unzip(data: Any, *, inflate_limit: int = MAX_INFLATED, entry_limit: int = MAX_INFLATED,
          error: Type[Exception] = ZipError) -> ZipEntries:
    """The entries of a ZIP archive, read as the application's ``unzip`` reads
    them (see the module's notes). ``inflate_limit`` is what the whole archive
    may inflate to and ``entry_limit`` one entry, the application's 256 MB
    unless a test says otherwise. What cannot be read raises ``error`` with
    the application's words -- as the archive is read, or when an entry left
    deflated is first asked for."""
    data = bytes(data)
    found = _end_record(data)
    if found is None:
        raise error('This does not look like a ZIP archive. An Ecolego project (.eco) is a zipped project folder; '
                    'a bare model.xml should be opened directly instead.')
    end_at, entry_count, p = found
    # ZIP64, for the rare enormous project.
    if entry_count == 0xFFFF or p == 0xFFFFFFFF:
        z64 = _zip64_end(data, end_at, error)
        if z64 is not None:
            entry_count, p = z64

    out = ZipEntries(inflate_limit, entry_limit, error)
    size = len(data)
    i = 0
    while i < entry_count:
        i += 1
        if p < 0 or p + 46 > size or data[p:p + 4] != b'PK\x01\x02':
            raise error('The central directory is damaged')
        flags = _u16(data, p + 8)
        method = _u16(data, p + 10)
        compressed = _u32(data, p + 20)
        expected = _u32(data, p + 24)
        name_len = _u16(data, p + 28)
        extra_len = _u16(data, p + 30)
        comment_len = _u16(data, p + 32)
        offset = _u32(data, p + 42)
        # The record's three variable parts have to fit too.
        if p + 46 + name_len + extra_len + comment_len > size:
            raise error(f'The central directory runs past the end of this {size}-byte archive')
        name = _without_bom(data[p + 46:p + 46 + name_len].decode('utf-8', 'replace'))
        if flags & 0x1:
            raise error(f"'{name}' is encrypted. Ecolego can obfuscate a project on save; re-save it without that "
                        'option, or export the model, before importing.')
        # ZIP64 extended information, when the 32-bit fields are saturated.
        if compressed == 0xFFFFFFFF or expected == 0xFFFFFFFF or offset == 0xFFFFFFFF:
            expected, compressed, offset = _zip64_sizes(data, p + 46 + name_len, extra_len,
                                                        (expected, compressed, offset), name, error)
        p += 46 + name_len + extra_len + comment_len
        if name.endswith('/'):
            continue  # a directory
        if offset < 0 or offset + 30 > size:
            raise error(f"'{name}' says its data begins at byte {_number(offset)}, which is outside this "
                        f'{size}-byte archive.')
        # The local header repeats the name and extra field, and its extra
        # field length can differ from the central one.
        if data[offset:offset + 4] != b'PK\x03\x04':
            raise error(f"The local header for '{name}' is damaged")
        start = offset + 30 + _u16(data, offset + 26) + _u16(data, offset + 28)
        if start > size or start + compressed > size:
            raise error(f"'{name}' claims {_number(compressed)} bytes from {start}, which runs past the end of this "
                        f'{size}-byte archive.')
        raw = data[start:start + compressed]
        if method == 0:
            out._put(name, _stored(raw))
        elif method == 8:
            if name.lower().endswith('.xml'):
                out._put(name, out._inflate(name, raw, expected))
            else:
                out._put(name, _deferred(out, name, raw, expected))
        else:
            raise error(f"'{name}' uses compression method {method}, which is not supported (only stored and "
                        'deflate are).')
    return out


def _stored(raw: bytes) -> Callable[[], bytes]:
    return lambda: bytes(raw)


def _deferred(entries: ZipEntries, name: str, raw: bytes, expected: int) -> Callable[[], bytes]:
    return lambda: entries._inflate(name, raw, expected)
