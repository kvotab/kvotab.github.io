#!/usr/bin/env python3
"""JMP data tables (.jmp) read in the engine (datasets.read_file, jmp.py),
checked against what JMPReader.jl, which jmp.py is a port of, expects of
its own test tables (its test/runtests.jl at the commit ported), and the
tables' scripts: the Source script JMP 18.2 wrote into three of them, and
a copy of one with its script block rewritten in place (two scripts, the
names' JSL forms; a block whose lengths do not add up gives none). The
tables are not ours: fetch-jmp-fixtures.py puts them in local/jmp/
(git-ignored); without them the checks are skipped.

    python3 resources/tests/smui/fetch-jmp-fixtures.py
    python3 resources/tests/smui/test_jmp.py
"""
import datetime
import json
import math
import os
import sys

from backend import Checks
from smui import registry

check = Checks()
HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = os.path.join(HERE, 'local', 'jmp')

if not os.path.isdir(LOCAL) or not os.listdir(LOCAL):
    print('(the .jmp test tables are not there: run fetch-jmp-fixtures.py; the checks are skipped)')
    sys.exit(check.done())


def read(name):
    with open(os.path.join(LOCAL, name), 'rb') as f:
        data = f.read()
    r = json.loads(registry.dispatch_bytes('datasets.read_file', json.dumps({'name': name}), data))
    if 'error' in r and 'columns' not in r:
        raise RuntimeError(f'{name}: {r["error"]}')
    return r, {c['name']: c for c in r['columns']}


def ms(*t):
    """A date or date-time as the page holds it: milliseconds since 1970 (UTC)."""
    return (datetime.datetime(*t, tzinfo=datetime.timezone.utc) - datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)).total_seconds() * 1000


def day(vals):
    """Dates on their day: JMP keeps a date's time of day, which its date
    format hides (and the page's does too); JMPReader.jl drops it."""
    return [None if v is None else math.floor(v / 86400000) * 86400000.0 for v in vals]


def near(a, b, tol=1e-9):
    return all((x is None and y is None) or (x is not None and y is not None and math.isclose(x, y, rel_tol=tol, abs_tol=tol)) for x, y in zip(a, b)) and len(a) == len(b)


# ---- example1.jmp: every common kind of column
r, c = read('example1.jmp')
check('example1: the columns, in their order', [x['name'] for x in r['columns']], ['ints', 'floats', 'charconstwidth', 'time', 'date', 'duration', 'charconstwidth2', 'charvariable16', 'formula', 'pressures', 'char utf8', 'charvariable8'])
check('example1: integers', c['ints']['values'], [1, 2, 3, 4])
check('example1: floats', c['floats']['values'], [11.1, 22.2, 33.3, 44.4])
check('example1: text of a fixed width', c['charconstwidth']['values'], ['a', 'b', 'c', 'd'])
check('example1: date-times, the last missing', (c['time']['values'][:3], c['time']['values'][3], c['time']['format']), ([ms(1976, 4, 1, 21, 12), ms(1984, 8, 6, 23, 58), ms(2003, 6, 2, 17)], None, {'kind': 'datetime'}))
check('example1: dates, the third missing', (day(c['date']['values']), c['date']['format']), ([ms(2024, 1, 13), ms(2024, 1, 14), None, ms(2032, 2, 12)], {'kind': 'date'}))
check('example1: durations, in seconds', (c['duration']['values'], 'seconds' in c['duration'].get('notes', '')), ([2322, 364, 229, 0], True))
check('example1: text of a fixed width, of different lengths', c['charconstwidth2']['values'], ['a', 'bb', 'ccc', 'dddd'])
check('example1: text of a width per value (16)', c['charvariable16']['values'], ['aa', 'bbbb', 'cccccccc', 'abcdefghij' * 13])
check('example1: a formula column\'s values', c['formula']['values'], ['2', '4', '6', '8'])
check('example1: floats with a missing value', near(c['pressures']['values'], [101.325, None, 2.6, 4.63309e110]), True)
check('example1: UTF-8 text', c['char utf8']['values'], ['ꙮꙮꙮ', '🚴💨', 'jäääär', '辛口'])
check('example1: text of a width per value (8)', c['charvariable8']['values'], ['a', 'bb', 'cc', 'abcdefghijkl'])
check('example1: numbers continuous, text nominal', (c['floats']['modelingType'], c['charconstwidth']['modelingType'], c['date']['dataType']), ('continuous', 'nominal', 'numeric'))
check('example1: the note says what JMP wrote it and that modeling types are guessed', ('Read from a JMP' in r['note'], 'Modeling types' in r['note']), (True, True))

# ---- compressed.jmp
r, c = read('compressed.jmp')
check('compressed: numbers', set(c['numeric']['values']), {1.0})
check('compressed: text of 1, 11 and 130 characters', (set(c['character1']['values']), set(c['character11']['values']), set(c['character130']['values'])), ({'a'}, {'abcdefghijk'}, {'abcdefghij' * 13}))
check('compressed: date-times', set(c['y-m-d h:m:s']['values']), {ms(1904, 1, 1, 0, 0, 1)})
check('compressed: dates', set(day(c['yyyy-mm-dd']['values'])), {ms(2024, 1, 20)})
check('compressed: durations', set(c['min:s']['values']), {196.0})

# ---- dates, durations and times in their many formats
r, c = read('date.jmp')
check('date: day-month-year', day(c['ddmmyyyy']['values']), [ms(2011, 5, 25), ms(1973, 5, 24), ms(2027, 5, 22), ms(2020, 5, 1)])
r, c = read('duration.jmp')
check('duration: days, hours, minutes, seconds', c[':day:hr:m:s']['values'], [88201.0] * 3)
r, c = read('time.jmp')
check('time: 20 date-time formats, the same two moments', ([x['values'] for x in r['columns']], len(r['columns'])), ([[ms(1914, 4, 27, 19, 54, 14), ms(1978, 1, 7, 6, 11, 24)]] * 20, 20))

# ---- names, shapes
r, c = read('longcolumnnames.jmp')
check('long column names (1400 and 2800 characters)', [x['name'] for x in r['columns']], [''.join(f'{i:010d}' for i in range(1, 141)), ''.join(f'{i:010d}' for i in range(1, 281))])
check('... and their values', [x['values'] for x in r['columns']], [[1, 1, 1], [2, 2, 2]])
r, c = read('singlecolumnsinglerow.jmp')
check('a single column and row', (r['rows'], [x['name'] for x in r['columns']], c['Column 1']['values']), (1, ['Column 1'], [1]))

# ---- byte integers, their missing values
r, c = read('byteintegers.jmp')
check('byte integers: 1, 2 and 4 bytes', (c['1-byte integer']['values'], c['2-byte integer']['values'], c['4-byte integer']['values']), ([0, 1, 0, 1, 0], [-187, -30, -18, 13, -55], [-28711, -16887, -26063, 13093, -44761]))
r, c = read('byteintegers_withmissing.jmp')
check('byte integers with a missing value', (c['1-byte integer']['values'], c['2-byte integer']['values'], c['4-byte integer']['values']), ([0, 1, 0, 1, 0, None], [-187, -30, -18, 13, -55, None], [-28711, -16887, -26063, 13093, -44761, None]))
r, c = read('byteintegers_notcompressed.jmp')
check('byte integers, not compressed: the extremes', (c['onebyte']['values'], c['twobyte']['values'], c['fourbyte']['values'], c['numeric']['values']),
      ([1, 2, -126, 127], [32767, None, 0, -32766], [None, 2147483647, -2147483646, None], [None, 2147483648, None, None]))

# ---- geographic, currencies
r, c = read('geographic.jmp')
check('geographic: longitudes', near(c['Longitude_DDD']['values'], [151.2099, 24.945831, -122.449], 1e-6), True)
check('geographic: missing latitudes', (c['Latitude_DDD']['values'][1], c['Latitude_DMM']['values'][2]), (None, None))
r, c = read('currencies.jmp')
check('currencies', (near(c['AUD']['values'], [1, 2, 2]), near(c['COP']['values'], [3.14, 2.78, 1.41])), (True, True))

# ---- row states: left out, and said so
r, c = read('rowstate.jmp')
check('row-state columns are left out, and the note says so', ('rowstate3' in c, 'Row-state columns left out' in r['note']), (False, True))

# ---- compact (pooled) text
r, c = read('compact.jmp')
data = ['aa', 'b', 'ccc', 'dd', 'dd']
check('compact text, as the normal kind', (c['normalsubtype']['values'], c['compactsubtype']['values']), (data, data))
check('compact text of 254, 255 and 256 characters, and an empty value', (c['longcompact']['values'][0], c['longcompact']['values'][1], c['longcompact']['values'][2], c['longcompact']['values'][3], c['longcompact']['values'][4]), ('x' * 254, 'y' * 255, None, 'z' * 256, 'z' * 256))
for f, n in (('compact_UInt8.jmp', 130), ('compact_UInt16.jmp', 32770), ('compact_UInt32.jmp', 65537)):
    r, c = read(f)
    check(f'{f}: {n} rows, the last value', (r['rows'], len(c['A']['values']), c['A']['values'][-1]), (n, n, f'a{n}'))

# ---- two tables that once went wrong
r, c = read('minusfour.jmp')
check('minusfour', c['Column 1']['values'], ['a', 'b', 'c'])
r, c = read('bugMWE4.jmp')
check('bugMWE4', (c['c']['values'][:3], c['d']['values'][:3], c['e']['values'][:3], c['f']['values'][15:18]),
      (['cat', 'cat', 'dolor sit amet'], ['bat', 'bat', 'consectetur adipiscing elit'], ['bird', 'bird', 'sed do eiusmod'], ['foo', 'bar', 'hello world']))

# ---- the table's scripts: the Source script JMP 18.2 wrote into three of the tables (an Open() of
# the text file each was imported from), and none in the others
for f in ('compact_UInt8.jmp', 'compact_UInt16.jmp', 'compact_UInt32.jmp'):
    r, _ = read(f)
    sc = r.get('scripts') or []
    check(f'{f}: one script, Source, its JSL the Open() of the file it came from',
          ([s['name'] for s in sc], sc[0]['jsl'].startswith('Open("/C:/Users/') if sc else None, sc[0]['jsl'].endswith('Year Rule("20xx")))') if sc else None), (['Source'], True, True))
    check(f'{f}: ... and the table note says so', 'table script (Source) came as JSL' in r['note'], True)
others = [f for f in sorted(os.listdir(LOCAL)) if f.endswith('.jmp') and not f.startswith('compact_UInt')]
check('the other tables have no scripts', {f: read(f)[0].get('scripts') for f in others}, {f: [] for f in others})

# The block as the reader takes it (jmp.py, _scripts): 03 00, its length (8 bytes), the number of
# scripts (2), and each a kind byte (03), its length (4) and its text. A copy of compact_UInt8.jmp
# with two scripts in the same room, so the columns' offsets stay: both come, the columns as before.
import struct  # noqa: E402
from smui import jmp  # noqa: E402

raw = open(os.path.join(LOCAL, 'compact_UInt8.jmp'), 'rb').read()
at = raw.find(b'\x03\x00', raw.find(b'Version'))
size = struct.unpack_from('<q', raw, at + 2)[0]
first = 'Distribution of A(Distribution(Nominal Distribution(Column(:A))))'
room = size - 2 - 2 * 5 - len(first)
second = 'Name("Source (old)")(Open("pooled.txt"' + ' ' * (room - len('Name("Source (old)")(Open("pooled.txt"))')) + '))'
payload = struct.pack('<H', 2) + b'\x03' + struct.pack('<I', len(first)) + first.encode() + b'\x03' + struct.pack('<I', len(second)) + second.encode()
check('the synthetic block fills the room of the original exactly', len(payload), size)
two = raw[:at + 10] + payload + raw[at + 10 + size:]
got = jmp.read('two.jmp', two)
check('two scripts: their names (plain, and Name("...")) and their JSL',
      [(s['name'], s['jsl'].replace(' ', '')) for s in got['scripts']], [('Distribution of A', 'Distribution(NominalDistribution(Column(:A)))'), ('Source (old)', 'Open("pooled.txt")')])
orig = jmp.read('compact_UInt8.jmp', raw)
check('... and the columns read as from the original', got['columns'] == orig['columns'], True)
bad = two[:at + 10] + struct.pack('<H', 3) + two[at + 12:]
got_bad = jmp.read('bad.jmp', bad)
check('a block whose lengths do not add up gives no scripts, and the table still reads', (got_bad['scripts'], got_bad['columns'] == orig['columns']), ([], True))
check('script names: plain, spaced, Name("..."), "..."n; not a call is none',
      [jmp._script_name(t) for t in ('Source(Open("x"))', 'Distribution  of height( Distribution( Y( :height ) ) )', 'Name("a (b)")(Bivariate(Y(:y), X(:x)))', '"q\\!"x"n(Oneway(Y(:y)))', 'NoParens', 'x(', 'a(b')],
      [('Source', 'Open("x")'), ('Distribution of height', 'Distribution( Y( :height ) )'), ('a (b)', 'Bivariate(Y(:y), X(:x))'), ('q"x', 'Oneway(Y(:y))'), None, None, None])

# ---- damaged tables: said in the reader's words, never held. Copies damaged
# field by field once kept the reader looping for ever on a part's length of
# -10, building billions of values for a damaged count of rows, unpacking a
# column without limit, and giving zlib's, numpy's and Python's own errors
# (KeyError: 3) as the reason. Each read here has ten seconds.
import gzip  # noqa: E402
import signal  # noqa: E402


def first_unpack(b, fn):
    """Where the reader first unpacks a number from the file in function fn."""
    at = []
    unpack = jmp._Bytes.unpack

    def spy(self, fmt, n=1):
        if not at and self.b is b and sys._getframe(1).f_code.co_name == fn:
            at.append(self.p)
        return unpack(self, fmt, n)
    jmp._Bytes.unpack = spy
    try:
        jmp.read('x.jmp', b)
    finally:
        jmp._Bytes.unpack = unpack
    return at[0]


def put(b, at, packed):
    return b[:at] + packed + b[at + len(packed):]


def said(data):
    """What the reader says of a file: 'read', its words, or that it held on."""
    def late(*_):
        raise TimeoutError
    old = signal.signal(signal.SIGALRM, late)
    signal.alarm(10)
    try:
        jmp.read('damaged.jmp', data)
        return 'read'
    except ValueError as e:
        return str(e)
    except TimeoutError:
        return 'held over 10 seconds'
    except Exception as e:                            # zlib.error, KeyError: not the reader's words
        return f'{type(e).__name__}: {e}'
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def with_stream(b, unpacked):
    """b, a table whose one column is its last, with that column's compressed
    bytes replaced by unpacked packed again, its two lengths set to match."""
    at = b.find(jmp.GZIP_START) + len(jmp.GZIP_START)
    gzlen = struct.unpack_from('<Q', b, at)[0]
    new = gzip.compress(unpacked, mtime=0)
    return b[:at] + struct.pack('<QQ', len(new), len(unpacked)) + new + b[at + 16 + gzlen:]


def stream_of(b):
    at = b.find(jmp.GZIP_START) + len(jmp.GZIP_START)
    gzlen = struct.unpack_from('<Q', b, at)[0]
    return gzip.decompress(b[at + 16:at + 16 + gzlen])


ex1 = open(os.path.join(LOCAL, 'example1.jmp'), 'rb').read()
part = first_unpack(ex1, '_column_info')
rows_at = first_unpack(ex1, '_metadata')
check('a part\'s length of -10, which led back to it for ever, is said', said(put(ex1, part, struct.pack('<q', -10))),
      'the file does not have the parts a JMP data table has')
check('2,147,483,647 rows in a table of four: said before anything is made for them',
      said(put(ex1, rows_at, struct.pack('<q', 2**31 - 1))),
      'column ints: it holds fewer values than the table has rows: a damaged JMP data table')
check('rows below zero are said, not a table of -2', said(put(ex1, rows_at, struct.pack('<q', -2))),
      'the table says it has fewer than no rows or columns: a damaged JMP data table')

one = open(os.path.join(LOCAL, 'singlecolumnsinglerow.jmp'), 'rb').read()
zat = one.find(jmp.GZIP_START) + len(jmp.GZIP_START)
crc = zat + 16 + struct.unpack_from('<Q', one, zat)[0] - 8      # the stream's check of what it unpacks to
check('a compressed column whose bytes are damaged: said in the reader\'s words, not zlib\'s',
      said(put(one, crc, bytes([one[crc] ^ 0xff]))),
      'column Column 1: its values are compressed, and the compressed bytes are damaged')
limit = jmp._MAX_UNPACKED
jmp._MAX_UNPACKED = 1 << 20
try:
    check('a column that unpacks to more than the page reads is refused as it unpacks (here 2 MB over 1 MB)',
          said(with_stream(one, b'\0' * (2 << 20))), 'column Column 1: its values unpack to more than the 1 GB this page reads')
finally:
    jmp._MAX_UNPACKED = limit
u8 = open(os.path.join(LOCAL, 'compact_UInt8.jmp'), 'rb').read()
pooled = stream_of(u8)
check('a pooled column whose indices are 3 bytes wide: said, where Python said "KeyError: 3"',
      said(with_stream(u8, pooled[:25] + b'\x03' + pooled[26:])), 'column A: an unknown width of pooled text indices (3)')

info = jmp._metadata(jmp._Bytes(one))
dt_at = info['offsets'][0] + 2 + struct.unpack_from('<h', one, info['offsets'][0])[0]
unknown = put(one, dt_at, b'\x05')
got = jmp.read('unknown.jmp', unknown)
check('a column of a kind the reader does not know: its row all missing, and said',
      (got['columns'][0]['values'], 'Columns of a kind the reader does not know' in got['note']), ([None], True))
check('... and with no column the reader knows to hold the rows, 2^40 of them are not made',
      said(put(unknown, first_unpack(one, '_metadata'), struct.pack('<q', 2**40))).startswith('the table says it has 1,099,511,627,776 rows, more than its file could hold'),
      True)

# ---- not a JMP table
try:
    registry.dispatch_bytes('datasets.read_file', json.dumps({'name': 'x.jmp'}), b'not a jmp file at all')
    said = ''
except ValueError as e:
    said = str(e)
check('a file that is not a JMP table is refused with a message', 'not a JMP data table' in said, True)

sys.exit(check.done())
