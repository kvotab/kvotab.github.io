"""The file formats against the application: the same tree, the same bytes.

Every tree, workbook and table here is made up, or is one of the repository's
own fixtures (``test/fixtures/*.h5``). Each is written -- or read -- by the
application's own modules through Node (``tests/node/io_formats.mjs``) and by
this package, and the two are compared: HDF5 files byte for byte, what the two
readers make of a file value for value (key order included), workbooks byte
for byte where the application's output does not depend on the platform's
deflate, and entry for entry where it does, CSV as text.

With h5py installed, h5py also reads the files written here, and writes files
in the dialects the application has to read (version 1 groups, chunked and
compressed datasets, big-endian numbers, fixed-length strings, ...), which the
two readers must then read alike.
"""

from __future__ import annotations

import base64
import datetime as dt
import io
import json
import math
import random
import struct
import subprocess
import tempfile
import unittest
import zipfile
import zlib
from array import array
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from helpers import NODE, SRC, differences, needs_app

from kompartment.io import csv as kcsv
from kompartment.io import hdf5, xlsx
from kompartment.io.hdf5read import HDF5ReadError, read_hdf5

try:
    import numpy
except ImportError:  # pragma: no cover
    numpy = None
try:
    import h5py
except ImportError:  # pragma: no cover
    h5py = None

SCRIPT = Path(__file__).resolve().parent / 'node' / 'io_formats.mjs'
FIXTURES = SRC.parent / 'test' / 'fixtures'

needs_h5py = unittest.skipUnless(h5py is not None and numpy is not None, 'needs h5py')
needs_numpy = unittest.skipUnless(numpy is not None, 'needs numpy')

NAN = {'$num': 'NaN'}
INF = {'$num': 'Infinity'}
NINF = {'$num': '-Infinity'}
NEG0 = {'$num': '-0'}
TYPECODES = {'Float64Array': 'd', 'Float32Array': 'f', 'Int32Array': 'i', 'Uint8Array': 'B'}


# --- talking to the application -----------------------------------------------

def js(*requests: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Asks the application's own modules, all the requests in one Node run."""
    assert NODE is not None
    proc = subprocess.run([NODE, str(SCRIPT), str(SRC)],
                          input=json.dumps({'task': 'batch', 'requests': list(requests)}),
                          capture_output=True, text=True, timeout=600, encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return json.loads(proc.stdout)['results']


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def unb64(text: str) -> bytes:
    return base64.b64decode(text)


# --- the values both sides are given --------------------------------------------

def dec(v: Any) -> Any:
    """A tagged value (see io_formats.mjs) as the Python value that means the same."""
    if isinstance(v, list):
        return [dec(x) for x in v]
    if isinstance(v, dict):
        if '$num' in v:
            return -0.0 if v['$num'] == '-0' else float(v['$num'].replace('Infinity', 'inf'))
        if '$undef' in v:
            return None
        if '$typed' in v:
            return array(TYPECODES[v['$typed']], dec(v['v']))
        if '$gen' in v:
            if v['$gen'] == 'strings':
                return [f"{v.get('prefix', '')}{i}" for i in range(v['n'])]
            return [((i * 7919) % 1000) / 7 - 50 for i in range(v['n'])]
        return {k: dec(x) for k, x in v.items()}
    return v


def canon(x: Any) -> Any:
    """A value in one comparable shape: every number a float, the specials tagged."""
    if x is None or isinstance(x, (bool, str)):
        return x
    if isinstance(x, int):
        return float(x)
    if isinstance(x, float):
        if math.isnan(x):
            return NAN
        if math.isinf(x):
            return INF if x > 0 else NINF
        if x == 0 and math.copysign(1, x) < 0:
            return NEG0
        return x
    if isinstance(x, array):
        name = {v: k for k, v in TYPECODES.items()}[x.typecode]
        return {'$typed': name, 'v': [canon(v) for v in x]}
    if isinstance(x, dict):
        if set(x) == {'$undef'}:
            return None  # Python has one nothing, not two
        if set(x) == {'$num'}:
            return x
        if set(x) == {'$typed', 'v'}:
            return {'$typed': x['$typed'], 'v': [canon(v) for v in x['v']]}
        return {k: canon(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [canon(v) for v in x]
    raise TypeError(type(x).__name__)


def same(test: unittest.TestCase, py: Any, js_value: Any, what: str = '') -> None:
    """Equal as values, types, specials and key order."""
    a, b = canon(py), canon(js_value)
    if json.dumps(a) != json.dumps(b):
        diff = differences(a, b)[:12] or [json.dumps(a)[:400], json.dumps(b)[:400]]
        test.fail(f'{what}: Python and the application differ:\n  ' + '\n  '.join(diff))


# --- HDF5 trees, described once, built by both ------------------------------------

def ds(data: Any, dt_: str = 'F64', attrs: Optional[dict] = None, dims: Optional[list] = None,
       array_: Optional[str] = None) -> Dict[str, Any]:
    return {'kind': 'dataset', 'data': data, 'dt': dt_, 'attrs': attrs or {}, 'dims': dims, 'array': array_}


def grp(attrs: Optional[dict] = None) -> Dict[str, Any]:
    return {'kind': 'group', 'attrs': attrs or {}}


def as_js(value: Any) -> Any:
    """``value`` as the application receives it: through JSON, which also joins
    a surrogate pair written as two escapes into the one character it is."""
    return json.loads(json.dumps(value))


def build(spec: Dict[str, Any]) -> hdf5.Group:
    """The tree a spec describes, through this package's API."""
    spec = as_js(spec)
    root = hdf5.group(dec(spec.get('attrs', {})))
    for where, node in spec.get('puts', []):
        if node['kind'] == 'group':
            made: Any = hdf5.group(dec(node.get('attrs', {})))
        else:
            data = dec(node['data'])
            if node.get('array'):
                data = array(TYPECODES[node['array']], data)
            made = hdf5.dataset(data, getattr(hdf5, node.get('dt', 'F64')), dec(node.get('attrs', {})),
                                node.get('dims'))
        hdf5.put(root, where, made)
    return root


def gen_strings(n: int, prefix: str = 's') -> Dict[str, Any]:
    return {'$gen': 'strings', 'n': n, 'prefix': prefix}


def gen_numbers(n: int) -> Dict[str, Any]:
    return {'$gen': 'numbers', 'n': n}


TREES: Dict[str, Dict[str, Any]] = {
    'nothing at all': {'attrs': {}, 'puts': []},
    'root attributes of every kind': {
        'attrs': {
            'model': 'Two ponds', 'made': 2026, 'x': 0.1, 'tiny': 5e-324, 'big': 1.7976931348623157e308,
            'ok': True, 'off': False, 'span': [0, 100], 'odd': [NAN, INF, NINF, NEG0],
            'names': ['Cs-137', 'H-3'], 'mixed': [1, 'a', True, None, 2.5, NAN],
            'nested': [[1, 2], 'x'], 'objects': [{'a': 1}, 'x'], 'lonely': [None], 'empty': [],
            'typed': {'$typed': 'Float32Array', 'v': [0.1, 2.5]}, 'unset': None,
            'Information': '<p>Where it came from<br>What it is</p>', 'µ-unit': 'µg/m³',
        },
        'puts': [],
    },
    'attribute keys in JavaScript order': {
        'attrs': {'b': 1, '10': 2, 'a': 3, '2': 4, '01': 5, '4294967295': 6, '4294967294': 7, '-1': 8, '0': 9},
        'puts': [[['d'], ds([1], attrs={'z': 'last', '3': 'first', 'y': 'middle',
                                          '__proto__': 'written, and not read back'})]],
    },
    'numbers as the application converts them': {
        'puts': [
            [['f64'], ds([0, 1.5, -2.25, 1e-300, 5e-324, NAN, INF, NINF, NEG0, 1.7976931348623157e308])],
            [['f64 from text'], ds(['1.5', ' 2 ', '0x10', '1e3', 'abc', '', None, True, False, '1_000', 'inf'])],
            [['f64 typed'], ds([0.1, 0.2, 0.30000000000000004], array_='Float64Array')],
            [['f32'], ds([0.1, 2.1, 1e39, -1e39, 1e-46, 3.4028235677973366e38, 3.4028234663852886e38,
                          NAN, INF, NEG0, 1.401298464324817e-45], 'F32')],
            [['f32 typed'], ds([0.1, 2.1, 16777217], 'F32', array_='Float32Array')],
            [['f64 from f32'], ds([0.1, 2.1], 'F64', array_='Float32Array')],
            [['i32'], ds([7, -8, 2147483647, 2147483648, -2147483649, 1e10, -1e10, 3.7, -3.7, NAN, INF,
                          '12', None, True, 4294967296 * 3 + 5], 'I32')],
            [['i32 typed'], ds([7, -8, 2147483647, -2147483648], 'I32', array_='Int32Array')],
            [['bytes as numbers'], ds([1, 2, 255], 'F64', array_='Uint8Array')],
        ],
    },
    'scalars and matrices': {
        'puts': [
            [['scalar'], ds([42.5], dims=[])],
            [['scalar string'], ds(['alone'], 'STR', dims=[])],
            [['matrix'], ds(list(range(12)), 'F32', dims=[3, 4], array_='Float32Array')],
            [['matrix f64'], ds([1, 2, 3, 4, 5, 6], dims=[2, 3])],
            [['column'], ds([1, 2, 3], dims=[3, 1])],
            [['strings matrix'], ds(['a', 'b', 'c', 'd'], 'STR', dims=[2, 2])],
            [['empty matrix'], ds([], dims=[0, 5])],
        ],
    },
    'strings, pooled and not': {
        'puts': [
            [['IndexLists', 'Radionuclides'], ds(['H-3', 'C-14-org', 'Cs-137', 'H-3'], 'STR',
                                                 {'name': 'Radionuclides', 'members': 4})],
            [['unicode'], ds(['Ångström µ 中文', '😀', '', ' padded ', 'tab\tnew\nline', 'a\0b'], 'STR')],
            [['lone surrogate'], ds(['\ud800', 'x\udfffy', '😀'], 'STR', {'u': '\udc00'})],
            [['not strings'], ds([1, 2.5, None, True, NAN, INF], 'STR')],
            [['long'], ds(['x' * 5000, 'y' * 4081, 'z' * 4080], 'STR')],
        ],
    },
    'names': {
        'puts': [
            [['Ångström µ 中文'], ds([2], attrs={'unit': 'µg'})],
            [['n' * 300], ds([1])],
            [['é' * 200, 'deeper'], ds([3])],
            [['with space', 'k.eff', 'C-14-org'], ds([4])],
            [['', 'skipped', '', 'empty parts'], ds([5])],
        ],
    },
    'deep': {'puts': [[[f'level{i}' for i in range(60)], ds([1.5])]]},
    'empty things': {
        'puts': [
            [['none'], ds([])], [['no strings'], ds([], 'STR')], [['no floats'], ds([], 'F32')],
            [['no ints'], ds([], 'I32')], [['nothing'], grp({'note': 'empty'})],
            [['bare group'], grp()], [['number, not a list'], ds(5)],
        ],
    },
    'many children': {'puts': [[['many', f's{i}'], ds([i], attrs={'unit': 'Bq', 'time_dependent': True})]
                               for i in range(300)]},
    'more heap objects than one collection holds': {
        'puts': [[['IndexLists', 'Big'], ds(gen_strings(60005), 'STR')],
                 [['after'], ds(['s60004', 'fresh'], 'STR', {'unit': 's1'})]],
    },
    'large datasets': {
        'puts': [[['doubles'], ds(gen_numbers(200000))], [['floats'], ds(gen_numbers(150001), 'F32')],
                 [['ints'], ds(gen_numbers(50000), 'I32')]],
    },
    'an attribute past 64 KiB': {'attrs': {'huge': gen_numbers(9000)}, 'puts': [[['x'], ds([1])]]},
    'a result file': {
        'attrs': {'model': 'Two ponds', 'created_time': '2026-09-13 20:30:00', 'source': 'Kompartment',
                  'time_unit': 'year', 'start_time': 0, 'end_time': 100, 'solver': 'ndf', 'series': 3,
                  'probabilistic': False, 'Information': None},
        'puts': [
            [['time'], ds([0, 10, 20], attrs={'unit': 'year', 'name': 'time', 'probabilistic': False})],
            [['IndexLists', 'Radionuclides'], ds(['Cs-137', 'H-3'], 'STR', {'name': 'Radionuclides', 'members': 2})],
            [['Lake', 'North', 'Cs-137'], ds([100, 90, 81], attrs={'unit': 'Bq', 'time_dependent': True,
                                                                   'index': ['Lake [Cs-137, North]']})],
            [['Lake', 'North', 'H-3'], ds([100, 57, 32], attrs={'unit': 'Bq', 'time_dependent': True})],
            [['bio', 'Dose'], ds(list(range(12)), 'F32', {'n_iter': 4, 'probabilistic': True}, [3, 4],
                                 'Float32Array')],
            [['k'], ds([0.02], attrs={'time_dependent': False})],
        ],
    },
}


# --- the HDF5 writer ------------------------------------------------------------------

@needs_app
class HDF5Written(unittest.TestCase):
    """The same tree, written by the application and by this package."""

    def test_every_tree_is_written_byte_for_byte_alike(self):
        names = list(TREES)
        answers = js(*[{'task': 'h5write', 'tree': TREES[n]} for n in names])
        for name, got in zip(names, answers):
            with self.subTest(tree=name):
                self.assertNotIn('error', got, got.get('error'))
                want = unb64(got['data'])
                mine = hdf5.write_hdf5(build(TREES[name]))
                self.assertEqual(len(mine), len(want))
                if mine != want:
                    first = next(i for i, (a, b) in enumerate(zip(mine, want)) if a != b)
                    self.fail(f'first difference at byte {first} of {len(want)}')

    @needs_numpy
    def test_numpy_arrays_write_the_bytes_their_lists_do(self):
        spec = {'puts': [
            [['f64'], ds([0.1, 2.5, NAN], array_='Float64Array')],
            [['f32'], ds([0.1, 1e39, 2.1], 'F32')],
            [['ints'], ds([1, -2, 2147483648], 'I32')],
            [['matrix'], ds([float(i) / 3 for i in range(12)], 'F32', dims=[3, 4])],
            [['strings'], ds(['a', 'b'], 'STR')],
        ]}
        want = unb64(js({'task': 'h5write', 'tree': spec})[0]['data'])
        root = hdf5.group()
        hdf5.put(root, ['f64'], hdf5.dataset(numpy.array([0.1, 2.5, math.nan])))
        hdf5.put(root, ['f32'], hdf5.dataset(numpy.array([0.1, 1e39, 2.1]), hdf5.F32))
        hdf5.put(root, ['ints'], hdf5.dataset(numpy.array([1, -2, 2147483648], dtype='int64'), hdf5.I32))
        # A two-dimensional array gives its shape.
        hdf5.put(root, ['matrix'], hdf5.dataset(numpy.arange(12).reshape(3, 4) / 3, hdf5.F32))
        hdf5.put(root, ['strings'], hdf5.dataset(numpy.array(['a', 'b']), hdf5.STR))
        self.assertEqual(hdf5.write_hdf5(root), want)

    def test_refusals_say_what_the_application_says(self):
        cases = {
            'a slash in a name': {'puts': [[['a/b'], ds([1])]]},
            'a slash on the way': {'puts': [[['a/b', 'c'], ds([1])]]},
            'two things at one path': {'puts': [[['time'], ds([1])], [['time'], ds([2])]]},
            'inside a dataset': {'puts': [[['time'], ds([1])], [['time', 'inside'], ds([2])]]},
            'at the root itself': {'puts': [[['', ''], ds([1])]]},
            'a shape that does not fit': {'puts': [[['m'], ds([1, 2, 3, 4, 5], dims=[2, 3])]]},
            'a shape of text': {'puts': [[['m'], ds([1, 2, 3, 4, 5, 6], dims=['2', 3])]]},
        }
        answers = js(*[{'task': 'h5write', 'tree': spec} for spec in cases.values()])
        for (name, spec), got in zip(cases.items(), answers):
            with self.subTest(case=name):
                try:
                    mine: Any = b64(hdf5.write_hdf5(build(spec)))
                except hdf5.HDF5Error as e:
                    mine = str(e)
                self.assertEqual(mine, got.get('error', got.get('data')))

    def test_lookup3_is_libhdf5_s(self):
        self.assertEqual(hdf5.lookup3(bytes([1, 2, 3, 4, 5])), 4166341796)
        rnd = random.Random(7)
        cases = []
        for n in list(range(0, 40)) + [100, 1000, 4097]:
            data = bytes(rnd.randrange(256) for _ in range(n))
            start = rnd.randrange(max(1, n // 3)) if n else 0
            cases.append((data, start, n - start))
            cases.append((data, 0, n))
        answers = js(*[{'task': 'lookup3', 'data': b64(d), 'from': s, 'length': ln} for d, s, ln in cases])
        for (data, start, length), got in zip(cases, answers):
            self.assertEqual(hdf5.lookup3(data, start, length), got['value'], (len(data), start, length))


class HDF5WrittenAlone(unittest.TestCase):
    """What the writer promises that needs no application to check."""

    def test_the_tree_is_put_together_as_asked(self):
        root = hdf5.group({'model': 'm'})
        leaf = hdf5.put(root, ['a', 'b', 'c'], hdf5.dataset([1.0]))
        self.assertIs(root.children['a'].children['b'].children['c'], leaf)
        self.assertEqual(list(root.children['a'].children), ['b'])
        with self.assertRaises(hdf5.HDF5Error):
            hdf5.put(root, ['a', 'b', 'c'], hdf5.dataset([2.0]))
        with self.assertRaises(TypeError):
            hdf5.put(root, 'a/b', hdf5.dataset([2.0]))
        with self.assertRaises(hdf5.HDF5Error):
            hdf5.write_hdf5(hdf5.dataset([1.0]))

    def test_strings_are_pooled(self):
        root = hdf5.group()
        for i in range(50):
            hdf5.put(root, [f'd{i}'], hdf5.dataset([1.0], hdf5.F64, {'unit': 'Bq', 'time_dependent': True}))
        self.assertEqual(hdf5.write_hdf5(root).count(b'TRUE'), 1)

    def test_a_generator_is_read_into_a_list(self):
        a = hdf5.write_hdf5(self._one(hdf5.dataset(x / 2 for x in range(5))))
        b = hdf5.write_hdf5(self._one(hdf5.dataset([x / 2 for x in range(5)])))
        self.assertEqual(a, b)

    @staticmethod
    def _one(node: hdf5.Dataset) -> hdf5.Group:
        root = hdf5.group()
        hdf5.put(root, ['x'], node)
        return root


# --- the HDF5 reader ------------------------------------------------------------------

def py_read(data: bytes) -> Dict[str, Any]:
    """What this package's reader makes of a file, or the error it raises."""
    try:
        got = read_hdf5(data)
    except Exception as e:  # noqa: BLE001
        return {'error': str(e)}
    return {'datasets': got['datasets'], 'problems': got['problems']}


def js_outcome(answer: Dict[str, Any]) -> Dict[str, Any]:
    return {'error': answer['error']} if 'error' in answer else answer


CHUNK = 'a chunk could not be read — '


def inflater_words_aside(outcome: Dict[str, Any]) -> Dict[str, Any]:
    """An outcome with what the inflater said about a damaged chunk left out.

    The application inflates with its own code and this package with zlib; the
    faults with one name in both are translated, and the rest are said in
    different words about the same chunk.
    """
    if 'problems' in outcome:
        outcome = dict(outcome, problems=[p.split(CHUNK)[0] + CHUNK if CHUNK in p else p
                                          for p in outcome['problems']])
    return outcome


@needs_app
class HDF5Read(unittest.TestCase):
    """What the two readers make of the same bytes."""

    def test_everything_written_reads_back_alike(self):
        files = {name: hdf5.write_hdf5(build(spec)) for name, spec in TREES.items()}
        answers = js(*[{'task': 'h5read', 'data': b64(data)} for data in files.values()])
        for (name, data), got in zip(files.items(), answers):
            with self.subTest(tree=name):
                same(self, py_read(data), js_outcome(got), name)

    def test_what_was_written_is_what_is_read(self):
        got = read_hdf5(hdf5.write_hdf5(build(TREES['a result file'])))
        by = {d['path']: d for d in got['datasets']}
        self.assertEqual(got['problems'], [])
        self.assertEqual(list(by['/time']['values']), [0.0, 10.0, 20.0])
        self.assertEqual(by['/time']['attrs'], {'unit': 'year', 'name': 'time', 'probabilistic': 'FALSE'})
        self.assertEqual(by['/IndexLists/Radionuclides']['values'], ['Cs-137', 'H-3'])
        self.assertEqual(by['/bio/Dose']['dims'], [3, 4])
        self.assertEqual(by['/Lake/North/Cs-137']['attrs']['index'], 'Lake [Cs-137, North]')
        self.assertIsInstance(by['/k']['values'], array)

    def test_the_repository_fixtures_read_alike(self):
        for name in ('chunked-samples.h5', 'v1-symbol-table.h5'):
            with self.subTest(fixture=name):
                data = (FIXTURES / name).read_bytes()
                got = js({'task': 'h5read', 'data': b64(data)})[0]
                mine = py_read(data)
                same(self, mine, js_outcome(got), name)
                self.assertEqual(mine['problems'], [])

    def test_the_fixtures_hold_what_the_application_s_tests_say(self):
        got = read_hdf5(FIXTURES / 'v1-symbol-table.h5')
        by = {d['path']: d for d in got['datasets']}
        self.assertEqual(len(by), 4)
        one = by['/demo/Atmosphere/height/L1']
        self.assertEqual((one['values'][0], one['attrs']['unit']), (10.0, 'm'))
        table = by['/demo/lobj/area/aqu']
        self.assertEqual((len(table['values']), table['values'][0]), (3, 9.74e6))
        self.assertEqual(list(table['attrs']['index']), [0.0, 500.0, 1000.0])

    def test_damaged_files_are_reported_alike(self):
        sources = [hdf5.write_hdf5(build(TREES['a result file'])),
                   hdf5.write_hdf5(build(TREES['strings, pooled and not'])),
                   (FIXTURES / 'v1-symbol-table.h5').read_bytes(),
                   (FIXTURES / 'chunked-samples.h5').read_bytes()]
        rnd = random.Random(2026)
        damaged = []
        for data in sources:
            for cut in sorted({rnd.randrange(8, len(data)) for _ in range(40)} | {9, 48, len(data) - 1}):
                damaged.append(data[:cut])
            for _ in range(120):
                b = bytearray(data)
                for _ in range(rnd.choice((1, 1, 2, 4))):
                    b[rnd.randrange(len(b))] = rnd.randrange(256)
                damaged.append(bytes(b))
        damaged.append(bytes(range(1, 10)))
        answers = js(*[{'task': 'h5read', 'data': b64(d)} for d in damaged])
        for i, (data, got) in enumerate(zip(damaged, answers)):
            with self.subTest(variant=i):
                same(self, inflater_words_aside(py_read(data)), inflater_words_aside(js_outcome(got)),
                     f'variant {i}')

    def test_a_file_that_is_not_one_says_so(self):
        with self.assertRaises(HDF5ReadError) as caught:
            read_hdf5(bytes(range(1, 10)))
        self.assertIn('not an HDF5 file', str(caught.exception))

    @needs_h5py
    def test_files_h5py_writes_read_alike(self):
        files = h5py_files()
        answers = js(*[{'task': 'h5read', 'data': b64(data)} for data in files.values()])
        for (name, data), got in zip(files.items(), answers):
            with self.subTest(file=name):
                mine = py_read(data)
                same(self, mine, js_outcome(got), name)
                if name in H5PY_READABLE:
                    self.assertEqual(len(mine['datasets']), H5PY_READABLE[name], name)


def h5py_files() -> Dict[str, bytes]:
    """Files in the dialects h5py writes, full of made-up values."""
    out: Dict[str, bytes] = {}
    np = numpy
    with tempfile.TemporaryDirectory() as tmp:
        def write(name: str, fill: Any, **kw: Any) -> None:
            path = Path(tmp) / f'{len(out)}.h5'
            with h5py.File(path, 'w', **kw) as f:
                fill(f)
            out[name] = path.read_bytes()

        def kinds(f: Any) -> None:
            # No group past eight links, which is where libhdf5's new-style
            # groups move their links to a fractal heap (see 'dense links').
            g = f.create_group('model/Atmosphere')
            g.attrs['note'] = 'made up'
            g.attrs['height'] = 10.0
            for i, dtype in enumerate(('<f8', '<f4', '>f8', '>f4', '<i1', '<i2', '<i4', '>i2', '>i4', '<u1',
                                       '<u2', '<u4', '>u2', '>u4', '<i8', '<u8')):
                last = 5 if dtype.endswith('8') and dtype[1] == 'i' else 3 if dtype[1] == 'u' else -1
                values = np.array([0, 1, 2, 100, last], dtype=dtype)
                f.create_dataset(f'numbers/set{i // 8}/{dtype.replace("<", "le").replace(">", "be")}', data=values)
            f.create_dataset('numbers/int64/negative', data=np.array([-1, 3], dtype='<i8'))
            f.create_dataset('numbers/int64/very negative', data=np.array([-2, 3], dtype='<i8'))
            f.create_dataset('text/fixed', data=np.array([b'ab', b'cde\0', b'fghij'], dtype='S5'))
            f.create_dataset('text/utf8 fixed', data=np.array(['Å µ'.encode('utf-8')], dtype='S8'))
            f.create_dataset('text/vlen', data=['one', 'two', 'Ångström'], dtype=h5py.string_dtype())
            f.create_dataset('text/scalar vlen', data='alone', dtype=h5py.string_dtype())
            f.create_dataset('misc/flags', data=np.array([True, False, True]))
            f.create_dataset('misc/scalar', data=3.25)
            f.create_dataset('misc/matrix', data=np.arange(12.0).reshape(3, 4))
            f.create_dataset('misc/cube', data=np.zeros((2, 2, 2)))
            f.create_dataset('misc/empty', data=np.zeros((0,)))
            f.create_dataset('misc/compound', data=np.zeros(2, dtype=[('a', '<f8'), ('b', '<i4')]))
            d = f['misc/matrix']
            d.attrs['unit'] = 'Bq'
            d.attrs['index'] = np.array([0.0, 500.0, 1000.0])
            d.attrs['lookup_table'] = True
            d.attrs['count'] = np.int32(7)
            d.attrs['names'] = np.array(['a', 'bb'], dtype=h5py.string_dtype())
            d.attrs['fixed'] = np.bytes_(b'fixed!')
            d.attrs['empty'] = h5py.Empty('f8')
            d.attrs['reference'] = 'A made-up reference, long enough to need a second block: ' + 'x' * 900
            links = f.create_group('links')
            links.create_dataset('target', data=[4.5])
            links['hard'] = links['target']
            links['soft'] = h5py.SoftLink('/links/target')
            links['external'] = h5py.ExternalLink('elsewhere.h5', '/x')

        def chunked(f: Any) -> None:
            data = np.arange(40.0) * 1.5
            f.create_dataset('gzip', data=data, chunks=(8,), compression='gzip')
            f.create_dataset('shuffle gzip', data=data, chunks=(7,), shuffle=True, compression='gzip',
                             compression_opts=9)
            f.create_dataset('fletcher', data=data, chunks=(16,), fletcher32=True)
            f.create_dataset('all three', data=data.astype('<f4'), chunks=(9,), shuffle=True,
                             compression='gzip', fletcher32=True)
            f.create_dataset('matrix', data=np.arange(30.0).reshape(6, 5), chunks=(4, 3), compression='gzip')
            f.create_dataset('ints', data=np.arange(20, dtype='<i2'), chunks=(6,), shuffle=True)
            f.create_dataset('strings', data=['a', 'b', 'c'], dtype=h5py.string_dtype(), chunks=(2,))
            f.create_dataset('whole', data=np.arange(10.0), chunks=(10,), compression='gzip')

        def many(f: Any) -> None:
            g = f.create_group('group of many')
            for i in range(150):
                g.create_dataset(f'd{i:03d}', data=[float(i)])
            f.create_group('empty group').attrs['n'] = 0

        def compact(f: Any) -> None:
            space = h5py.h5s.create_simple((4,))
            dcpl = h5py.h5p.create(h5py.h5p.DATASET_CREATE)
            dcpl.set_layout(h5py.h5d.COMPACT)
            h5py.h5d.create(f.id, b'compact', h5py.h5t.IEEE_F64LE, space, dcpl=dcpl).write(
                h5py.h5s.ALL, h5py.h5s.ALL, np.array([1.0, 2.0, 3.0, 4.0]))
            f.create_dataset('contiguous', data=[5.0, 6.0])

        def ordered(f: Any) -> None:
            g = f.create_group('ordered', track_order=True)
            for name in ('z', 'a', 'm'):
                g.create_dataset(name, data=[1.0])
            for i in range(12):
                g.attrs[f'attr{i}'] = i

        write('every kind (earliest)', kinds)
        write('every kind (latest)', kinds, libver='latest')
        write('chunked (earliest)', chunked)
        # Layout version 3 with a version 2 filter pipeline, whose descriptions
        # the application reads two bytes out of step (see the report).
        write('chunked (1.8 format)', chunked, libver=('v108', 'v108'))
        # Layout version 4, which the application reads as version 3: the whole
        # read fails, in both.
        write('chunked (latest)', chunked, libver='latest')
        write('many links (earliest)', many)
        # Past eight links a new-style group keeps them in a fractal heap, which
        # the application does not read: the group comes back empty, unreported.
        write('dense links (latest)', many, libver='latest')
        write('compact layout', compact)
        write('tracked order', ordered, libver='latest')
        # Addresses are relative to the superblock, which the application takes
        # as the start of the file.
        write('a user block', lambda f: f.create_dataset('x', data=[1.0, 2.0]), userblock_size=512)
    return out


#: The h5py files the application reads something out of, and how many datasets.
H5PY_READABLE = {'every kind (earliest)': 26, 'every kind (latest)': 26, 'chunked (earliest)': 8,
                 'many links (earliest)': 150, 'compact layout': 2, 'tracked order': 3}


@needs_h5py
class H5pyReadsWhatIsWritten(unittest.TestCase):
    """libhdf5 itself, through h5py, on the files this package writes."""

    def test_h5py_reads_every_tree(self):
        for name, spec in TREES.items():
            if name == 'an attribute past 64 KiB':
                continue  # corrupt in the application too: see the report of JS oddities
            with self.subTest(tree=name):
                data = hdf5.write_hdf5(build(spec))
                ours = {d['path']: d for d in read_hdf5(data)['datasets']}
                with h5py.File(io.BytesIO(data), 'r') as f:
                    for key in f.attrs:
                        f.attrs[key]  # every root attribute h5py sees has to be readable
                    seen: List[str] = []
                    f.visititems(lambda path, obj: seen.append('/' + path) if isinstance(obj, h5py.Dataset) else None)
                    for path in seen:
                        d = f[path]
                        mine = ours[path]
                        self.assertEqual(list(d.shape), mine['dims'], path)
                        if d.dtype.kind == 'O':
                            got = [x.decode('utf-8') if isinstance(x, bytes) else x
                                   for x in numpy.asarray(d[()]).reshape(-1).tolist()]
                            # libhdf5 hands a variable-length string over as a C
                            # string, so it ends at a NUL the string holds.
                            self.assertEqual(got, [s.split('\0')[0] for s in mine['values']], path)
                        else:
                            got = numpy.asarray(d[()], dtype='f8').reshape(-1)
                            numpy.testing.assert_array_equal(got, numpy.asarray(mine['values'], dtype='f8'))
                        for key in d.attrs:
                            if key == '__proto__':
                                continue  # written, and left out on reading as the application leaves it
                            self.assertIn(key, mine['attrs'], path)
                            self._same_attr(d.attrs[key], mine['attrs'][key], f'{path}@{key}')

    def _same_attr(self, theirs: Any, mine: Any, where: str) -> None:
        """h5py's value and ours alike, as lists: ours unboxes a list of one."""
        listed = theirs.reshape(-1).tolist() if isinstance(theirs, numpy.ndarray) else [theirs]
        listed = [x.decode('utf-8') if isinstance(x, bytes) else x.item() if isinstance(x, numpy.generic) else x
                  for x in listed]
        ours = list(mine) if isinstance(mine, (list, array)) else [mine]
        self.assertEqual(len(listed), len(ours), where)
        for a, b in zip(listed, ours):
            if isinstance(a, float) and math.isnan(a):
                self.assertTrue(isinstance(b, float) and math.isnan(b), where)
            else:
                self.assertEqual(a, b, where)


# --- workbooks -------------------------------------------------------------------------

BOOK = {'sheets': [
    {'name': 'data', 'rows': [
        ['ID', 'Unit', 'Value', 'Flag', 'Note'],
        ['k', '1/year', 0.05, True, None],
        ['Soil.Kd [Cs-137, Lake]', 'm3/kg', 1e-7, False, ''],
        [None, '', NAN, INF, NINF],
        ['<&>"\'', ' leading and trailing ', 1e21, NEG0, 123456789012],
        ['ctrl\x01\x0b\x1f kept\ttab\nline\rcr', 'µ Ångström 中文 😀', 0.1 + 0.2, -1.5e-300, 5e-324],
        ['lone \ud800 surrogate'],
        [],
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28],
    ]},
    {'name': 'Sheet: 1/2 [x]*?\\', 'rows': [[1, 2, 3]], 'header': False},
    {'name': 'data', 'rows': [['a second data']]},
    {'name': 'DATA', 'rows': [['and a third']]},
    {'name': 'x' * 40, 'rows': [['long']]},
    {'name': 'x' * 40, 'rows': [['long again']]},
    {'name': '   ', 'rows': [['blank']]},
    {'name': None, 'rows': [['none']]},
    {'name': 12.5, 'rows': [[]]},
    {'name': 'no rows'},
    {'name': 'not a list', 'rows': 'abc'},
    {'name': '😀' * 20, 'rows': [['astral']]},
    {'name': 'a' * 30 + '😀', 'rows': [['split']]},
    {'name': 'header off', 'rows': [['h', 1], ['v', 2]], 'header': False},
    {'name': 'header zero', 'rows': [['h', 1]], 'header': 0},
]}


def zip_layout(data: bytes) -> Dict[str, Any]:
    """Everything in a ZIP but the compressed bytes: every header field, and
    each entry's data as it comes out."""
    entries = []
    p = 0
    while data[p:p + 4] == b'PK\x03\x04':
        (_, need, flags, method, time, date, crc, csize, usize, nlen, xlen) = struct.unpack_from('<IHHHHHIIIHH', data, p)
        name = data[p + 30:p + 30 + nlen]
        body = data[p + 30 + nlen + xlen:p + 30 + nlen + xlen + csize]
        content = zlib.decompress(body, -15) if method == 8 else body
        entries.append({'name': name.decode(), 'need': need, 'flags': flags, 'method': method, 'time': time,
                        'date': date, 'crc': crc, 'usize': usize, 'extra': xlen, 'content': content})
        p += 30 + nlen + xlen + csize
    central = []
    while data[p:p + 4] == b'PK\x01\x02':
        fields = struct.unpack_from('<IHHHHHHIIIHHHHHII', data, p)
        nlen, xlen, clen = fields[10], fields[11], fields[12]
        central.append(fields[1:7] + fields[7:8] + fields[9:10] + fields[10:16])
        p += 46 + nlen + xlen + clen
    eocd = struct.unpack_from('<IHHHHIIH', data, p)
    return {'entries': entries, 'central': central, 'count': eocd[1:6], 'rest': data[p + 22:]}


@needs_app
class Workbooks(unittest.TestCase):
    """Workbooks written and read by the application and by this package."""

    def test_a_stored_workbook_is_byte_for_byte_the_application_s(self):
        for modified in (None, [2026, 9, 25, 13, 45, 31], [1975, 6, 15, 0, 0, 0], [2107, 12, 31, 23, 59, 59]):
            with self.subTest(modified=modified):
                got = js({'task': 'xlsxwrite', 'book': BOOK, 'modified': modified, 'store': True})[0]
                when = dt.datetime(*modified) if modified else None
                self.assertEqual(xlsx.write_workbook(dec(as_js(BOOK)), modified=when, compress=False), unb64(got['data']))

    def test_a_deflated_workbook_is_the_application_s_entry_for_entry(self):
        got = js({'task': 'xlsxwrite', 'book': BOOK, 'modified': None, 'store': False})[0]
        want = zip_layout(unb64(got['data']))
        mine = zip_layout(xlsx.write_workbook(dec(as_js(BOOK))))
        self.assertEqual([e['name'] for e in mine['entries']], [e['name'] for e in want['entries']])
        for a, b in zip(mine['entries'], want['entries']):
            self.assertEqual(a, b, a['name'])
        # Every field of the central directory but the compressed sizes and the offsets.
        self.assertEqual(mine['central'], want['central'])
        self.assertEqual(mine['count'], want['count'])
        self.assertTrue(all(e['method'] == 8 for e in mine['entries']))

    def test_each_reads_the_other_s_workbooks(self):
        for store in (True, False):
            with self.subTest(stored=store):
                written = unb64(js({'task': 'xlsxwrite', 'book': BOOK, 'store': store})[0]['data'])
                mine = xlsx.write_workbook(dec(as_js(BOOK)), compress=not store)
                a, b, c = js({'task': 'xlsxread', 'data': b64(written)}, {'task': 'xlsxread', 'data': b64(mine)},
                             {'task': 'xlsxread', 'data': b64(mine)})
                same(self, xlsx.read_workbook(written), a, 'Python reading the application')
                same(self, b, a, 'the application reading Python')
                same(self, xlsx.read_workbook(mine), c, 'Python reading Python')

    def test_workbooks_from_elsewhere_read_alike(self):
        books = hand_made_workbooks()
        answers = js(*[{'task': 'xlsxread', 'data': b64(data)} for data in books.values()])
        for (name, data), got in zip(books.items(), answers):
            with self.subTest(workbook=name):
                try:
                    mine: Any = xlsx.read_workbook(data)
                except xlsx.XLSXError as e:
                    mine = {'error': str(e)}
                same(self, mine, js_outcome(got), name)

    def test_a_workbook_needs_a_sheet(self):
        for book in ({'sheets': []}, {'sheets': [{'name': 'x'}]}, {}):
            got = js({'task': 'xlsxwrite', 'book': book})[0]
            with self.assertRaises(xlsx.XLSXError) as caught:
                xlsx.write_workbook(book)
            self.assertEqual(str(caught.exception), got['error'])

    def test_the_helpers_agree(self):
        escapes = [['a&b<c>"d"', False], ['a&b<c>"d"', True], ["it's", True], [None, False], [12.5, False],
                   [True, True], ['\x00\x08\x0b\x0c\x0e\x1f\t\n\r kept', False], [[1, 'a'], False], [NAN, False]]
        refs = ['A1', 'B7', 'Z9', 'AA1', 'AZ3', 'XFD1048576', 'b7', '', '7B', 'A', 'ÅA1', 'A😀']
        columns = [0, 1, 25, 26, 27, 51, 52, 701, 702, 16383, -5, 2.7, -0.5, NAN, NINF]
        got = js({'task': 'xlsxhelp', 'escapes': escapes, 'refs': refs, 'columns': columns})[0]
        self.assertEqual([xlsx.xml_escape(dec(s), attr) for s, attr in escapes], got['escaped'])
        self.assertEqual([xlsx.column_of(r) for r in refs], got['columnOf'])
        self.assertEqual([xlsx.column_name(dec(i)) for i in columns], got['columnName'])


def _zip_of(parts: Dict[str, Any], stored: Tuple[str, ...] = ()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            data = text if isinstance(text, bytes) else text.encode('utf-8')
            z.writestr(zipfile.ZipInfo(name) if name.endswith('/') else name, data,
                       compress_type=zipfile.ZIP_STORED if name in stored or name.endswith('/') else None)
    return buf.getvalue()


def _patched(data: bytes, name: bytes, *, flags: Optional[int] = None, method: Optional[int] = None) -> bytes:
    """A ZIP with one entry's flags or method changed, in both its headers."""
    b = bytearray(data)
    p = 0
    while True:
        p = b.find(name, p + 1)
        if p < 0:
            return bytes(b)
        for sig, base, name_at in ((b'PK\x03\x04', p - 30, 26), (b'PK\x01\x02', p - 46, 28)):
            if base >= 0 and b[base:base + 4] == sig and struct.unpack_from('<H', b, base + name_at)[0] == len(name):
                at = base + (6 if sig == b'PK\x03\x04' else 8)
                if flags is not None:
                    struct.pack_into('<H', b, at, flags)
                if method is not None:
                    struct.pack_into('<H', b, at + 2, method)


NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def hand_made_workbooks() -> Dict[str, bytes]:
    """Workbooks the way other programs write them, and ways they go wrong."""
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="/xl/worksheets/first.xml"/>'
            '<Relationship Id="rId2" Target="./worksheets/second.xml"/>'
            '<Relationship Id="rId3" Target="worksheets/missing.xml"/>'
            "<Relationship Id='rId9' Target='../outside.xml'/></Relationships>")
    workbook = (f'\ufeff<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE workbook><workbook {NS} {RNS}>'
                '<!-- a comment --><sheets>'
                '<sheet name="First &amp;amp; best" sheetId="1" r:id="rId1"/>'
                '<sheet name="Second" sheetId="2" r:id="rId2"/>'
                '<sheet name="Gone" sheetId="3" r:id="rId3"/>'
                '<sheet sheetId="4"/>'
                '<sheet name="Outside" r:id="rId9"/>'
                '<sheet name="By relationship:id" relationship:id="rId2"/>'
                '</sheets></workbook>')
    shared = (f'<sst {NS} count="6">'
              '<si><t>plain</t></si>'
              '<si><r><rPr><b/></rPr><t>Bold</t></r><r><t xml:space="preserve"> and not</t></r></si>'
              '<si>\n  <t>pretty</t>\n  </si>'
              '<si><t>ruby</t><rPh sb="0" eb="1"><t>RU</t></rPh></si>'
              '<si><t><![CDATA[<cdata & stuff>]]></t></si>'
              '<si><t>&lt;&#65;&#x42;&#1a;&#a1;&#x110000;&#xD800;&unknown;&apos;</t></si>'
              '</sst>')
    first = (f'<worksheet {NS}><sheetData>'
             '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>1</v></c><c r="D1" t="s"><v>2</v></c>'
             '<c r="E1" t="s"><v>3</v></c><c r="F1" t="s"><v>4</v></c><c r="G1" t="s"><v>5</v></c></row>'
             '<row r="3"><c r="A3" t="s"><v> 1 </v></c><c r="B3" t="s"><v>1.5</v></c><c r="C3" t="s"><v>99</v></c>'
             '<c r="D3" t="s"><v>0x1</v></c><c r="E3" t="s"><v>-0</v></c><c r="F3" t="s"></c></row>'
             '<row r="2"><c r="A2" t="b"><v>1</v></c><c r="B2" t="b"><v>0</v></c><c r="C2" t="b"><v>true</v></c>'
             '<c r="D2" t="str"><v>&amp;lt;twice&amp;gt;</v></c><c r="E2" t="e"><v>#DIV/0!</v></c>'
             '<c r="F2" t="inlineStr"><is><t>inline</t><r><t> run</t></r></is></c><c r="G2" t="inlineStr"/></row>'
             '<row r="5"><c r="A5"><v>1e5</v></c><c r="B5"><v> 42 </v></c><c r="C5"><v>0x1F</v></c>'
             '<c r="D5"><v>abc</v></c><c r="E5"><v></v></c><c r="F5"><v>Infinity</v></c><c r="G5"><v>1_000</v></c>'
             '<c r="H5" t="n"><v>-2.5e-3</v></c><c r="I5" t="d"><v>2026-09-25T00:00:00</v></c>'
             '<c r="J5"><v>0b101</v></c><c r="K5"><v>.5</v></c><c r="L5"><v>5.</v></c><c r="M5"><v>+7</v></c></row>'
             '<row r="4"><c><v>no ref</v></c><c r="b4"><v>lower</v></c><c r="4B"><v>digit first</v></c>'
             '<c r="AB4"><v>far</v></c><c r="B4"><v>1</v></c><c r="B4"><v>2</v></c></row>'
             '<row><c r="A1"><v>no row number</v></c></row>'
             '<row r="0"><c r="A1"><v>row zero</v></c></row>'
             '<row r="2.5"><c r="Z1"><v>half a row</v></c></row>'
             '<row r="3"><c r="A3"><v>row three again</v></c></row>'
             '</sheetData><sheetData><row r="12"><c r="B12"><v>second sheetData</v></c></row></sheetData>'
             '</worksheet>')
    second = (f"<?xml version='1.0'?><worksheet {NS}>\n  <sheetData>\n    <row r='1'>\n"
              "      <c r='A1' t='inlineStr'><is><t xml:space='preserve'>  spaced  </t></is></c>\n"
              "    </row>\n  </sheetData>\n</worksheet>")
    fourth = f'<worksheet {NS}><sheetData><row r="1"><c r="A1"><v>by position</v></c></row></sheetData></worksheet>'
    good = {
        '[Content_Types].xml': '<Types/>', 'xl/': b'', 'xl/workbook.xml': workbook,
        'xl/_rels/workbook.xml.rels': rels, 'xl/sharedStrings.xml': shared,
        'xl/worksheets/first.xml': first, 'xl/worksheets/second.xml': second,
        'xl/worksheets/sheet4.xml': fourth, 'xl/worksheets/sheet6.xml': fourth,
    }
    books = {
        'from elsewhere': _zip_of(good, stored=('xl/worksheets/second.xml',)),
        'invalid UTF-8 in a string': _zip_of(dict(good, **{'xl/sharedStrings.xml': shared.encode()
                                                           .replace(b'plain', b'pl\xff\xfein\xe2\x82')})),
        'no relationships': _zip_of({'xl/workbook.xml': f'<workbook {NS}><sheets><sheet name="A"/>'
                                                        '<sheet name="B"/></sheets></workbook>',
                                     'xl/worksheets/sheet2.xml': fourth}),
        'prefixed names': _zip_of({'xl/workbook.xml': '<x:workbook xmlns:x="u"><x:sheets><x:sheet name="A"/>'
                                                      '</x:sheets></x:workbook>',
                                   'xl/worksheets/sheet1.xml': fourth}),
        'not a zip': b'hello, this is not a workbook',
        'no workbook part': _zip_of({'xl/other.xml': '<a/>'}),
        'an empty workbook part': _zip_of({'xl/workbook.xml': ''}),
        'no sheets listed': _zip_of({'xl/workbook.xml': f'<workbook {NS}><sheets/></workbook>'}),
        'no sheet held': _zip_of({'xl/workbook.xml': f'<workbook {NS}><sheets><sheet name="A"/></sheets></workbook>'}),
        'unclosed element': _zip_of(dict(good, **{'xl/worksheets/first.xml': f'<worksheet {NS}><sheetData>'})),
        'mismatched tags': _zip_of(dict(good, **{'xl/worksheets/first.xml': '<worksheet><row></worksheet>'})),
        'an unquoted attribute': _zip_of(dict(good, **{'xl/workbook.xml': '<workbook a=b/>'})),
        'two roots': _zip_of(dict(good, **{'xl/workbook.xml': '<a/><b/>'})),
        'an empty sheet part': _zip_of(dict(good, **{'xl/worksheets/second.xml': ''})),
        'an unterminated comment': _zip_of(dict(good, **{'xl/worksheets/second.xml': '<a><!-- never</a>'})),
    }
    base = _zip_of(good)
    books['an encrypted entry'] = _patched(base, b'xl/worksheets/second.xml', flags=0x0001)
    books['an encrypted directory'] = _patched(base, b'xl/', flags=0x0001)
    books['bzip2'] = _patched(base, b'xl/worksheets/sheet6.xml', method=12)
    return books


# --- CSV ---------------------------------------------------------------------------------

AWKWARD = ['plain', 'Soil [Cs-137, Lake]', 'say "hi"', 'a\nb', 'a\rb', 'a\r\nb', '"', ',', '', ' ', 'µ 中文 😀',
           'tab\tseparated', 0, 1, -1, 0.1, 0.30000000000000004, 1e21, 1e-7, 123456789012345680000, 1e300,
           5e-324, -1.5e-10, 100000, 0.000001, 1234.5678, NAN, INF, NINF, NEG0, None, {'$undef': True}, True,
           False, [1, 'a,b', None], [[1, 2], [3]], [], {'a': 1}, 2 ** 53 + 1, 10 ** 22, 10 ** 400]


@needs_app
class CSV(unittest.TestCase):
    """Cells, rows and whole tables as the application writes them."""

    def test_cells(self):
        got = js({'task': 'csvcells', 'values': AWKWARD})[0]
        self.assertEqual([kcsv.csv_cell(dec(v)) for v in AWKWARD], got['cells'])

    def test_rows(self):
        rows = [AWKWARD[:12], AWKWARD[12:30], AWKWARD[30:], [], [None], [0.5, 'x,y', NAN]]
        got = js({'task': 'csvrows', 'rows': rows})[0]
        self.assertEqual([kcsv.csv_row(dec(r)) for r in rows], got['lines'])

    def test_a_table(self):
        t = [0, 0.5, 1e-7, 1e21, 100000, 3]
        labels = ['Soil [Cs-137, Lake]', 'say "x"', 'plain', 'µ', 'line\nbreak']
        columns = [
            {'$typed': 'Float32Array', 'v': [2.1, NAN, 3, INF, 0.1, 7]},
            [1, 2],
            [0.1, 0.2, 0.30000000000000004, NEG0, NINF, 1e-300],
            {'$typed': 'Float64Array', 'v': [1, 2, 3, 4, 5, 6, 7]},
            [],
        ]
        got = js({'task': 'csvtable', 't': t, 'labels': labels, 'columns': columns})[0]
        self.assertEqual(kcsv.to_csv(dec(t), labels, dec(columns)), got['text'])
        lines = list(kcsv.csv_lines(dec(t), labels, dec(columns)))
        self.assertEqual(len(lines), len(t) + 1)
        self.assertEqual('\n'.join(lines), got['text'])

    @needs_numpy
    def test_numpy_values_are_written_as_their_numbers(self):
        values = [numpy.float32(2.1), numpy.float64(0.1), numpy.int64(7), numpy.bool_(True), numpy.array([1.5, 2])]
        want = js({'task': 'csvcells', 'values': [2.0999999046325684, 0.1, 7, True, [1.5, 2]]})[0]
        self.assertEqual([kcsv.csv_cell(v) for v in values], want['cells'])


class CSVAlone(unittest.TestCase):
    """The conversions, where JavaScript and Python part ways."""

    def test_js_string(self):
        self.assertEqual([kcsv.js_string(v) for v in (1.0, 1e21, 1e-7, math.nan, -math.inf, None, True, [1, None])],
                         ['1', '1e+21', '1e-7', 'NaN', '-Infinity', 'null', 'true', '1,'])

    def test_js_to_number(self):
        cases = {'': 0.0, ' 12 ': 12.0, '0x1F': 31.0, '0b101': 5.0, '1e3': 1000.0, '.5': 0.5, '5.': 5.0,
                 '-Infinity': -math.inf}
        for text, want in cases.items():
            self.assertEqual(kcsv.js_to_number(text), want, text)
        for text in ('inf', 'nan', '1_000', 'abc', '0x', '1e', '--1', '+0x1'):
            self.assertTrue(math.isnan(kcsv.js_to_number(text)), text)
        self.assertEqual(kcsv.js_to_number(None), 0.0)
        self.assertEqual(kcsv.js_to_number([5]), 5.0)


if __name__ == '__main__':
    unittest.main()
