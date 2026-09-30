"""JMP data tables (.jmp), read without JMP.

JMP's file format is not published. This reader is a port to Python of
JMPReader.jl (https://github.com/jaakkor2/JMPReader.jl, at commit a0bc789,
2026-09-20), which found its way through the format; its licence:

    MIT License. Copyright (C) 2024 Jaakko Ruohio

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to
    the following conditions:

    The above copyright notice and this permission notice (including the
    next paragraph) shall be included in all copies or substantial
    portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
    OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
    MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
    IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
    CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
    TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
    SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

What comes across: the columns' names and values, numbers (floats and 1,
2 and 4 byte integers, with their missing values), text (fixed and
variable width, compressed or not, pooled), dates and date-times (as the
page's dates), times of day and durations (as seconds), currencies and
geographic coordinates (as numbers), fixed decimals (as the format).
And the table's scripts, as their JSL text (see _scripts: found in files
of JMP 18, not in JMPReader.jl). What does not: the modeling types, which
the format keeps where no reader has found them (numbers come in
continuous, text nominal, as from a CSV file); value orders and labels,
formulas (their values come), column properties; row-state columns are
left out.
"""
import re
import struct
import zlib

import numpy as np

MAGIC = bytes([0xff, 0xff, 0x00, 0x00, 0x07, 0x00, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x02, 0x00])
GZIP_START = bytes([0xef, 0xbe, 0xfe, 0xca])          # 0xcafebeef: a compressed section follows
JMP_TO_UNIX = 2082844800                             # seconds from 1904-01-01 (JMP's day 0) to 1970-01-01

# The kinds of numeric column, by the format bytes dt4 and dt5 (JMPReader.jl, column.jl)
_PLAIN = {0x00, 0x03, 0x42, 0x43, 0x44, 0x59, 0x60, 0x63, 0x5f, 0x54, 0x55, 0x56, 0x51, 0x52, 0x53}
_DATE_SAME = {0x65, 0x66, 0x67, 0x6e, 0x6f, 0x70, 0x71, 0x72, 0x75, 0x76, 0x7a, 0x7f, 0x88, 0x8b}
_DATE_PAIRS = {(0x67, 0x65), (0x6f, 0x65), (0x72, 0x65), (0x72, 0x6f), (0x72, 0x7f), (0x72, 0x80), (0x7f, 0x72), (0x88, 0x65), (0x88, 0x7a)}
_DT_DT5 = {0x69, 0x6a, 0x73, 0x74, 0x77, 0x78, 0x7e, 0x81}
_DT_DT4 = {0x69, 0x6a, 0x6c, 0x6d, 0x73, 0x74, 0x77, 0x78, 0x79, 0x7b, 0x7c, 0x7d, 0x7e, 0x80, 0x81, 0x82, 0x86, 0x87, 0x89, 0x8a}
_DT_PAIRS = {(0x77, 0x80), (0x77, 0x7f), (0x89, 0x65)}
_DURATION_SAME = {0x0c, 0x6b, 0x6c, 0x6d, 0x83, 0x84, 0x85}


class _Bytes:
    """The file's bytes with a read position, little-endian as JMP writes them."""

    def __init__(self, b):
        self.b = b
        self.p = 0

    def read(self, n):
        if n < 0 or self.p + n > len(self.b):
            raise ValueError('the file ends early: not a JMP data table, or a damaged one')
        out = self.b[self.p:self.p + n]
        self.p += n
        return out

    def unpack(self, fmt, n=1):
        size = struct.calcsize('<' + fmt)
        vals = struct.unpack(f'<{n}{fmt}', self.read(size * n))
        return vals if n > 1 else vals[0]

    def skip(self, n):
        self.p += n

    def until(self, seq):
        """To just after the next occurrence of seq."""
        i = self.b.find(seq, self.p)
        if i < 0:
            raise ValueError('the file does not have the parts a JMP data table has')
        self.p = i + len(seq)

    def string(self, width):
        n = self.unpack({1: 'b', 2: 'h', 4: 'i'}[width])
        return self.read(n).decode('utf-8', errors='replace')


def _metadata(r):
    r.p = 0
    r.until(bytes([0x07, 0x00, 0x08, 0x00, 0x00, 0x00]))
    r.p -= 38
    nrows = r.unpack('q')
    ncols = r.unpack('i')
    r.skip(2 * 5)
    charset = r.string(4).rstrip('\0')
    r.skip(2 * 3)
    r.unpack('d')                                    # the time it was saved
    r.skip(2)
    build = r.string(4)
    m = re.search(r'Version (.*)$', build)
    if not m:
        raise ValueError('could not tell which JMP wrote the file')
    after_build = r.p
    n_visible, n_hidden = _seek_to_column_index(r, ncols)
    r.skip(4 * (n_visible + n_hidden))               # the visible and hidden columns
    r.skip(2 * ncols)                                # display widths
    r.skip(4 * 7)
    names, offsets = _column_info(r, ncols)
    return {'nrows': nrows, 'ncols': ncols, 'names': names, 'offsets': offsets, 'version': m.group(1).strip(), 'charset': charset,
            'header': (after_build, min(offsets) if offsets else len(r.b))}


# ---- the table's scripts ----------------------------------------------------
# JMP 18 keeps them in the header, after the build string, as one block:
#   03 00, its length (8 bytes), the number of scripts (2 bytes), and each
#   script as a kind byte (03), its length (4 bytes) and its JSL text, the
#   script's name applied to its body: Source(Open("...", ...)).
# That was read from the files JMP 18.2 wrote for JMPReader.jl's tests (a
# Source script each); the format is not published, so the block is taken
# only when every length adds up exactly and every text is a JSL call.
_SCRIPT_BLOCK = b'\x03\x00'
_MAX_SCRIPT = 1 << 20


def _script_name(text):
    """(name, body) of a script's text Name(body), or None. The name may be
    written plain (Source, Distribution of height), as Name("...") or as
    "..."n."""
    t = text.strip()
    if not t.endswith(')'):
        return None
    if t.startswith('"') or t.startswith('Name('):
        q = t.index('"')
        i, out = q + 1, []
        while i < len(t) and t[i] != '"':
            if t.startswith('\\!"', i) or t.startswith('\\"', i):
                out.append('"')
                i += 3 if t[i + 1] == '!' else 2
                continue
            out.append(t[i])
            i += 1
        if i >= len(t):
            return None
        rest = t[i + 1:].lstrip()
        if t.startswith('Name('):
            if not rest.startswith(')'):
                return None
            rest = rest[1:].lstrip()
        elif rest.startswith('n'):
            rest = rest[1:].lstrip()
        else:
            return None
        name = ''.join(out)
    else:
        k = t.find('(')
        if k <= 0:
            return None
        name, rest = t[:k].strip(), t[k:]
        if not name or '"' in name or ')' in name:
            return None
    if not rest.startswith('('):
        return None
    body = rest[1:-1].strip()
    name = ' '.join(name.split())
    return (name, body) if name and body else None


def _scripts(b, start, end):
    """The table's scripts as [{name, jsl}] (empty when there are none, or
    when what looks like their block does not read cleanly)."""
    i = b.find(_SCRIPT_BLOCK, start, end)
    while 0 <= i < end:
        got = _script_block(b, i, end)
        if got is not None:
            return got
        i = b.find(_SCRIPT_BLOCK, i + 1, end)
    return []


def _script_block(b, i, end):
    if i + 12 > end:
        return None
    size = struct.unpack_from('<q', b, i + 2)[0]
    at = i + 10
    if size < 2 or at + size > end:
        return None
    count = struct.unpack_from('<H', b, at)[0]
    if not 1 <= count <= 1000:
        return None
    p, stop, out = at + 2, at + size, []
    for _ in range(count):
        if p + 5 > stop:
            return None
        kind = b[p]
        n = struct.unpack_from('<I', b, p + 1)[0]
        p += 5
        if kind != 0x03 or n < 3 or n > _MAX_SCRIPT or p + n > stop:
            return None
        try:
            text = b[p:p + n].decode('utf-8')
        except UnicodeDecodeError:
            return None
        p += n
        named = _script_name(text)
        if named is None:
            return None
        out.append({'name': named[0], 'jsl': named[1]})
    return out if p == stop else None


def _seek_to_column_index(r, ncols):
    r.p = 2
    while True:
        r.until(b'\xff\xff')
        while r.p < len(r.b) and r.b[r.p] == 0xff:
            r.p += 1
        if r.p >= len(r.b):
            raise ValueError('could not find the columns of the JMP table')
        r.skip(10)
        n_visible = r.unpack('I')
        n_hidden = r.unpack('I')
        r.skip(8)
        if n_visible + n_hidden == ncols:
            return n_visible, n_hidden
        r.skip(-18)


def _column_info(r, ncols):
    while True:
        two = r.read(2)
        if two in (b'\xfc\xff', b'\xfd\xff', b'\xfe\xff', b'\xff\xff'):
            n = r.unpack('q')
            r.skip(n)
        else:
            r.skip(-2)
            break
    ncols2 = r.unpack('i')
    if ncols2 != ncols:
        raise ValueError(f'the numbers of columns read from two places do not agree ({ncols}, {ncols2})')
    offsets = list(r.unpack('q', ncols)) if ncols > 1 else [r.unpack('q')]
    names = []
    for off in offsets:
        r.p = off
        names.append(r.string(2))
    return names, offsets


def _ints(a, width, n):
    dtype = {1: '<i1', 2: '<i2', 4: '<i4'}.get(width, '<f8')
    size = np.dtype(dtype).itemsize
    raw = np.frombuffer(a[len(a) - size * n:], dtype=dtype, count=n)
    if dtype == '<f8':
        return raw.astype(float)
    out = raw.astype(float)
    out[raw == np.iinfo(raw.dtype).min + 1] = np.nan          # JMP's missing integer
    return out


def _texts(data, widths):
    out, at = [], 0
    for w in widths:
        w = int(w)
        s = data[at:at + w].decode('utf-8', errors='replace')
        at += w
        out.append(s if s != '' else None)
    return out


def _column(r, info, i):
    """The ith column: (values, dataType, format or None, note or None); None for a row-state column."""
    n = info['nrows']
    start = info['offsets'][i]
    end = len(r.b) if i == info['ncols'] - 1 else info['offsets'][i + 1]
    r.p = start
    r.string(2)
    dt1, dt2, dt3, dt4, dt5, dt6 = r.read(6)
    mark = r.p
    if dt1 in (0x09, 0x0a):                           # compressed
        r.until(GZIP_START)
        gzlen = r.unpack('Q')
        r.unpack('Q')                                 # its length unpacked
        a = zlib.decompress(r.read(gzlen), 16 + zlib.MAX_WBITS)
    else:
        a = r.b[start:end]
    r.p = mark

    # numbers: floats, dates, times, durations, integers in the float slot
    if dt1 in (0x01, 0x0a):
        vals = _ints(a, dt6, n)
        if (dt4 == dt5 and dt4 in _PLAIN) or dt5 in (0x5e, 0x63):
            fmt = {'kind': 'fixed', 'digits': int(dt4)} if dt5 in (0x5e, 0x63) and dt4 <= 12 else None
            return vals, 'numeric', fmt, None
        secs = vals
        ms = np.where(np.isnan(secs), np.nan, (secs - JMP_TO_UNIX) * 1000.0)
        if (dt4 == dt5 and dt4 in _DATE_SAME) or (dt4, dt5) in _DATE_PAIRS:
            return ms, 'numeric', {'kind': 'date'}, None
        if (dt5 in _DT_DT5 and dt4 in _DT_DT4) or (dt4 == dt5 and dt4 in (0x79, 0x7d)) or (dt4, dt5) in _DT_PAIRS:
            return ms, 'numeric', {'kind': 'datetime'}, None
        if dt4 == dt5 == 0x82:
            return np.where(np.isnan(secs), np.nan, np.mod(secs, 86400.0)), 'numeric', None, 'a time of day, in seconds after midnight'
        if (dt4 == dt5 and dt4 in _DURATION_SAME) or (dt4, dt5) == (0x84, 0x79):
            return secs, 'numeric', None, 'a duration, in seconds'
        return vals, 'numeric', None, None
    if dt1 in (0xff, 0xfe, 0xfc):                     # byte integers
        return _ints(a, dt5, n), 'numeric', None, None
    if dt1 == 0x09 and dt2 == 0x03:                   # row states: markers and colours, not data
        return None
    if dt1 == 0x03 and dt2 == 0x03:
        return np.frombuffer(a[len(a) - 8 * n:], dtype='<i8', count=n).astype(float), 'numeric', None, None

    # text
    if dt1 in (0x02, 0x09) and dt2 in (0x01, 0x02):
        if ((dt3, dt4) == (0, 0) and dt5 > 0) or (1 <= dt3 <= 7 and dt4 == 0):   # a fixed width
            w = dt5
            data = a[len(a) - n * w:]
            return [(data[k * w:(k + 1) * w].split(b'\0', 1)[0].decode('utf-8', errors='replace') or None) for k in range(n)], 'character', None, None
        if (dt3, dt4, dt5) == (0, 0, 0):                                           # a width per value
            if dt1 == 0x09:                                                        # compressed
                if struct.unpack_from('<q', a, 0)[0] == len(a):                    # pooled: an index per row into a list of values
                    q = _Bytes(a)
                    q.unpack('q')
                    q.skip(9)
                    q.unpack('q')
                    wb = q.unpack('b')
                    idx = np.array(q.unpack({1: 'B', 2: 'H', 4: 'I'}[wb], n) if n > 1 else [q.unpack({1: 'B', 2: 'H', 4: 'I'}[wb])])
                    wb2 = q.unpack('b')
                    tf = {1: 'b', 2: 'h'}.get(wb2)
                    if tf is None:
                        raise ValueError(f'column {info["names"][i]}: an unknown kind of pooled text')
                    pool = []
                    for _ in range(int(idx.max()) if len(idx) else 0):
                        k = q.unpack(tf)
                        pool.append(q.read(k).decode('utf-8', errors='replace'))
                    return [(pool[j - 1] or None) if j else None for j in idx.tolist()], 'character', None, None
                wbytes = a[8]
                if wbytes == 1:
                    widths = np.frombuffer(a[13:13 + n], dtype='<i1')
                    data = a[13 + n:]
                elif wbytes == 2:
                    widths = np.frombuffer(a[13:13 + 2 * n], dtype='<i2')
                    data = a[13 + 2 * n:]
                else:
                    raise ValueError(f'column {info["names"][i]}: an unknown width of text lengths ({wbytes})')
                return _texts(data, widths), 'character', None, None
            r.skip(6)                                                              # not compressed
            n1 = r.unpack('q')
            r.skip(n1)
            r.skip(2)
            n2 = r.unpack('I')
            r.skip(n2 + 8)
            wbytes = r.unpack('B')
            r.unpack('I')                                                          # the longest
            tf = {1: 'b', 2: 'h', 4: 'i'}.get(wbytes)
            if tf is None:
                raise ValueError(f'column {info["names"][i]}: an unknown width of text lengths ({wbytes})')
            widths = r.unpack(tf, n) if n > 1 else [r.unpack(tf)]
            total = int(sum(widths))
            return _texts(r.b[end - total:end], widths), 'character', None, None
    return np.full(n, np.nan), 'numeric', None, f'not read: a kind of column this reader does not know ({dt1:02x} {dt2:02x} {dt3:02x} {dt4:02x} {dt5:02x} {dt6:02x})'


def read(name, data):
    """A .jmp file as the page's table: {name, columns, note, rows}."""
    b = bytes(data)
    if b[:len(MAGIC)] != MAGIC:
        raise ValueError(f'{name} is not a JMP data table (or it is damaged)')
    r = _Bytes(b)
    info = _metadata(r)
    cols, skipped, unread = [], [], []
    for i, cname in enumerate(info['names']):
        got = _column(r, info, i)
        if got is None:
            skipped.append(cname)
            continue
        vals, dtype, fmt, note = got
        c = {'name': cname, 'dataType': dtype}
        if dtype == 'numeric':
            c['values'] = [None if v != v else float(v) for v in np.asarray(vals, dtype=float).tolist()]
            c['modelingType'] = 'continuous'
        else:
            c['values'] = list(vals)
            c['modelingType'] = 'nominal'
        if fmt:
            c['format'] = fmt
        if note:
            c['notes'] = note
            if note.startswith('not read'):
                unread.append(cname)
        cols.append(c)
    scripts = _scripts(b, *info['header'])
    notes = [f'Read from a JMP {info["version"]} data table.',
             'Modeling types are not kept in a form this page can read: numbers came in continuous and text nominal; change them in the Columns panel where JMP had them otherwise.']
    if skipped:
        notes.append(f'Row-state columns left out: {", ".join(skipped)}.')
    if unread:
        notes.append(f'Columns of a kind the reader does not know (all missing): {", ".join(unread)}.')
    if scripts:
        notes.append(f'Its table script{"s" if len(scripts) > 1 else ""} ({", ".join(s["name"] for s in scripts)}) came as JSL: the Table panel lists them, and a click runs the analyses they launch here.')
    return {'name': name.rsplit('.', 1)[0], 'columns': cols, 'note': ' '.join(notes), 'rows': int(info['nrows']), 'scripts': scripts}
