#!/usr/bin/env python3
"""JMP data tables (.jmp) read in the engine (datasets.read_file, jmp.py),
checked against what JMPReader.jl, which jmp.py is a port of, expects of
its own test tables (its test/runtests.jl at the commit ported). The tables
are not ours: fetch-jmp-fixtures.py puts them in local/jmp/ (git-ignored);
without them the checks are skipped.

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

# ---- not a JMP table
try:
    registry.dispatch_bytes('datasets.read_file', json.dumps({'name': 'x.jmp'}), b'not a jmp file at all')
    said = ''
except ValueError as e:
    said = str(e)
check('a file that is not a JMP table is refused with a message', 'not a JMP data table' in said, True)

sys.exit(check.done())
