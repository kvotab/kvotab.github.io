#!/usr/bin/env python3
"""Fixtures for the Julia port of Kompartment's HDF5 result-file writer.

Builds HDF5 trees with the Python package's ``kompartment.io.hdf5`` and
``kompartment.io.resultfile``, writes each one's bytes, and describes how each
was built as JSON, so ``test/io/test_hdf5.jl`` can build the same tree with the
Julia API (``h5group``/``h5dataset``/``h5put``, ``result_tree``,
``probabilistic_tree``, ``scenarios_tree``, ``results_tree``) and compare the
bytes::

    PYTHONPATH=kompartment/python python3 kompartment/julia/tools/hdf5_fixtures.py OUTDIR
    julia --project=kompartment/julia kompartment/julia/test/io/test_hdf5.jl OUTDIR

Writes ``OUTDIR/cases.json``, one ``OUTDIR/<case>.h5`` per case (the Python
package's bytes) and ``OUTDIR/<case>-<n>.bin`` for large arrays. Nothing here
belongs in the repository: OUTDIR is a scratch directory.

Values in the JSON keep what JSON would lose: ``{"$float": "NaN"}`` (and the
infinities), ``{"$ndarray": {dtype, shape, hex | file}}`` (C order),
``{"$f32": x}``, ``{"$tuple": [...]}``, ``{"$dict": [[k, v], ...]}`` for a
dictionary with keys that are not all strings, ``{"$codepoints": [...]}`` for
a string holding surrogates, ``{"$datetime": [y, m, d, H, M, S, us]}``. Indices
the Julia API takes 1-based (``which``, an input's ``k``, ``matrix_for``'s
argument) are written 1-based.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import random
import sys
import tempfile
import time
import types
from pathlib import Path

import numpy as np

from kompartment.io import csv as kcsv, hdf5, resultfile

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else
           os.environ.get('KOMPARTMENT_H5_FIXTURES') or Path(tempfile.gettempdir()) / 'kompartment-h5fixtures')
OUT.mkdir(parents=True, exist_ok=True)
EXAMPLES = Path(__file__).resolve().parents[2] / 'examples'

DT_NAME = {hdf5.F64: 'F64', hdf5.F32: 'F32', hdf5.I32: 'I32', hdf5.STR: 'STR'}
NOW = dt.datetime(2026, 10, 10, 9, 5, 7)

_bin_count = [0]
CASE = ['']


def _has_surrogate(s: str) -> bool:
    return any(0xD800 <= ord(c) <= 0xDFFF for c in s)


def enc(v):
    """A value as JSON the Julia test decodes back into the same value."""
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, str):
        return {'$codepoints': [ord(c) for c in v]} if _has_surrogate(v) else v
    if isinstance(v, np.ndarray):
        arr = np.ascontiguousarray(v)
        le = arr.astype(arr.dtype.newbyteorder('<'), copy=False)
        spec = {'dtype': str(arr.dtype), 'shape': list(arr.shape)}
        raw = le.tobytes()
        if len(raw) > 1 << 16:
            _bin_count[0] += 1
            name = f'{CASE[0]}-{_bin_count[0]}.bin'
            (OUT / name).write_bytes(raw)
            spec['file'] = name
        else:
            spec['hex'] = raw.hex()
        return {'$ndarray': spec}
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.float32):
        return {'$f32': enc(float(v))}
    if isinstance(v, float):  # numpy's float64 too
        if math.isnan(v):
            return {'$float': 'NaN'}
        if math.isinf(v):
            return {'$float': 'Infinity' if v > 0 else '-Infinity'}
        return float(v)
    if isinstance(v, int):
        if -(1 << 63) <= v < (1 << 63):
            return v
        return {'$bigint': str(v)}
    if isinstance(v, list):
        return [enc(x) for x in v]
    if isinstance(v, tuple):
        return {'$tuple': [enc(x) for x in v]}
    if isinstance(v, range):
        return {'$range': [v.start, v.stop, v.step]}
    if isinstance(v, (bytes, bytearray)):
        return {'$bytes': bytes(v).hex()}
    if isinstance(v, dict):
        if all(isinstance(k, str) and not k.startswith('$') for k in v):
            return {k: enc(x) for k, x in v.items()}
        return {'$dict': [[enc(k), enc(x)] for k, x in v.items()]}
    if isinstance(v, dt.datetime):
        return {'$datetime': [v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond]}
    raise TypeError(f'cannot encode {type(v)}')


def hexfloats(values) -> dict:
    return enc(np.asarray(values, dtype=np.float64))


# --- recording a tree as it is built ------------------------------------------------------------

class Rec:
    """Builds a tree with the Python API and records each step for the Julia test."""

    def __init__(self) -> None:
        self.ops = []
        self.nodes = []

    def _add(self, node, op) -> int:
        self.nodes.append(node)
        self.ops.append(op)
        return len(self.nodes) - 1

    def group(self, attrs=None) -> int:
        return self._add(hdf5.group(attrs), {'op': 'group', 'id': len(self.nodes), 'attrs': enc(attrs)})

    def dataset(self, data, dtype=hdf5.F64, attrs=None, dims=None) -> int:
        if isinstance(data, types.GeneratorType):  # read once, by both
            items = list(data)
            spec = {'$generator': enc(items)}
            data = iter(items)
        else:
            spec = enc(data)
        op = {'op': 'dataset', 'id': len(self.nodes), 'data': spec, 'dt': DT_NAME[dtype],
              'attrs': enc(attrs), 'dims': enc(dims)}
        return self._add(hdf5.dataset(data, dtype, attrs, dims), op)

    def put(self, root: int, path, node: int) -> None:
        hdf5.put(self.nodes[root], path, self.nodes[node])
        self.ops.append({'op': 'put', 'root': root, 'path': list(path), 'node': node})

    def at(self, root: int, path) -> int:
        """The node at ``path`` (a group ``put`` made on the way), as a node of its own."""
        node = self.nodes[root]
        for p in path:
            node = node.children[p]
        return self._add(node, {'op': 'at', 'id': len(self.nodes), 'root': root, 'path': list(path)})

    def set_attr(self, node: int, key, value) -> None:
        self.nodes[node].attrs[key] = value
        self.ops.append({'op': 'set_attr', 'node': node, 'key': enc(key), 'value': enc(value)})


CASES = []


def emit(name: str, kind: str, data: bytes, **spec) -> None:
    (OUT / f'{name}.h5').write_bytes(data)
    CASES.append({'name': name, 'kind': kind, 'expected': f'{name}.h5', 'size': len(data), **spec})
    print(f'{name:28s} {len(data):>10d} bytes')


def tree_case(name: str, build) -> None:
    CASE[0] = name
    rec = Rec()
    root = build(rec)
    emit(name, 'ops', hdf5.write_hdf5(rec.nodes[root]), ops=rec.ops, root=root)


# --- raw trees ----------------------------------------------------------------------------------

def build_empty(rec):
    return rec.group()


def build_root_attrs(rec):
    attrs = {
        'name': 'Two boxes',
        '17': 'seventeen',
        'count': 3,
        '0': 'zero',
        'ratio': 0.1,
        '3': 3.5,
        '01': 'not an index',
        'flag': True,
        'off': False,
        '4294967294': 'the largest index',
        '4294967295': 'not an index',
        'none': None,
        'list': [1, 2.5, -3],
        'strings': ['a', 'b', 'a'],
        'mixed': [1, 'two', None, 3.25, 1e21, 1e-7, True],
        'bools': [True, False, True],
        'nulls_and_numbers': [None, 1, None],
        'empty_list': [],
        'nan': math.nan,
        'inf': math.inf,
        'ninf': -math.inf,
        'negzero': -0.0,
        'big': 2 ** 53 + 1,
        'huge': 1.7976931348623157e308,
        'tiny': 5e-324,
        'numeric_string': '5',
        'dict': {'a': 1},
        'nested': [[1, 2], [3]],
        'nested_text': ['x', [1, 2], [3, None]],
        'tuple': (1, 2),
        'np_f64': np.array([0.1, 0.2, np.nan]),
        'np_f32': np.array([0.1, 1e39, -2.5]).astype(np.float32),
        'np_i32': np.array([1, -2, 3], dtype=np.int32),
        'np_bool': np.array([True, False]),
        'np_2d': np.arange(6, dtype=np.float64).reshape(2, 3),
        'np_scalar_f64': np.float64(2.5),
        'np_scalar_i64': np.int64(7),
        'np_scalar_bool': np.bool_(False),
        'np_scalar_f32': np.float32(0.1),
        'range': range(3),
        'bytes': b'\x01\x02\xff',
        'åäö': 'non-ASCII name',
        'value åäö 日本 😀': 'non-ASCII value åäö 日本 😀',
        'empty': '',
        'spaces': '  padded  ',
        'number_texts': [100000, 0.000015, 1e-7, 1e21, 1.5e300, -0.0, 123456789012345680.0, 0.1 + 0.2],
        'number_texts_str': ['n', 100000, 0.000015, 1e-7, 1e21, 1.5e300, -0.0, 123456789012345680.0, 0.1 + 0.2,
                             5e-324, 2 ** 70, -1e-7, 1e-6, 123e-20, 1e20, 2 ** 53 + 1, math.nan, -math.inf],
    }
    return rec.group(attrs)


def build_int_keys(rec):
    # Keys that are not strings are written as String() writes them; a key
    # seen twice keeps its first place and its last value.
    root = rec.group({1: 'int one', 'b': 'bee', '1': 'str one', 2.5: 'two and a half', 10: 'ten', 2: 'two'})
    return root


def build_nested(rec):
    root = rec.group({'model': 'nested'})
    leaf = rec.dataset([1.0, 2.0, 3.0], hdf5.F64, {'unit': 'Bq'})
    rec.put(root, ['a', 'b', 'c', 'd', 'e'], leaf)
    rec.put(root, ['', 'a', '', 'x'], rec.dataset([4.0], hdf5.F64, {'unit': 'kg'}))
    rec.put(root, ['a', 'b', 'y'], rec.dataset(['p', 'q'], hdf5.STR))
    g = rec.group({'kind': 'explicit'})
    rec.put(root, ['a', 'g'], g)
    rec.put(root, ['a', 'g', 'z'], rec.dataset([7, 8, 9], hdf5.I32))
    # attributes set on groups put made, after they were made
    rec.set_attr(rec.at(root, ['a']), 'IndexLists', ['Radionuclides'])
    b = rec.at(root, ['a', 'b'])
    rec.set_attr(b, 'time_dependent', True)
    rec.set_attr(b, '0', 'first')
    rec.set_attr(b, 'time_dependent', False)       # set again: keeps its place
    return root


def build_many_children(rec):
    root = rec.group({'children': 400})
    rnd = random.Random(400)
    for k in range(400):
        name = f'child {k:03d} {"åäö"[k % 3]}'
        if k % 7 == 0:
            node = rec.group({'k': k, 'even': k % 2 == 0})
            rec.put(root, [name], node)
            rec.put(root, [name, 'inner'], rec.dataset([rnd.random() for _ in range(k % 5)], hdf5.F64))
        else:
            data = [rnd.uniform(-1, 1) * 10 ** rnd.randint(-30, 30) for _ in range(k % 11)]
            rec.put(root, [name], rec.dataset(data, hdf5.F64, {'unit': ['Bq', 'kg', 'm'][k % 3], 'k': k}))
    return root


def build_datasets(rec):
    root = rec.group({'model': 'datasets'})
    put = lambda name, *args: rec.put(root, [name], rec.dataset(*args))
    put('f64', [0.0, 1.0, -1.5, 1e300, 5e-324, -0.0, math.nan, math.inf, -math.inf, 2 ** 53 + 1, 7])
    put('f64_empty', [], hdf5.F64, {'note': 'nothing'})
    put('f64_from_text', ['5', ' 0x10 ', '', None, True, 'abc', '1e999', '1e-400', 'Infinity', '-Infinity',
                          'infinity', '1_000', '.5', '5.', '+3', '0b101', '0o17', ' 5﻿', '\x855'],
        hdf5.F64)
    put('f64_str_data', 'abc', hdf5.F64)
    put('f64_number_data', 5.0, hdf5.F64)
    put('f64_np_i64', np.array([1, 2, 3, 2 ** 53 + 1], dtype=np.int64), hdf5.F64)
    put('f64_np_f32', np.array([0.1, 3.4e38], dtype=np.float32), hdf5.F64)
    put('f64_tuple', (1.5, 2.5), hdf5.F64)
    put('f64_iterator', (x * 0.5 for x in range(4)), hdf5.F64)
    put('f32', [0.1, 1e39, -1e39, 3.4028235677973366e38, 3.4028235677973362e38, -1e-50, 16777217, math.nan,
                1.401298464324817e-45, 7e-46, 2 ** 60 + 2 ** 36 + 1, None, '2.5'], hdf5.F32)
    put('f32_np', np.array([0.1, 1e39, 2.5], dtype=np.float64), hdf5.F32)
    put('i32', [2 ** 31, -2 ** 31 - 1, 4294967296 + 5, 1.9, -1.9, math.nan, math.inf, -math.inf, 1e20, '12', None,
                True, -0.5, 2 ** 53 + 1, -4294967297], hdf5.I32)
    put('i32_np', np.array([1, -1, 2 ** 31 - 1], dtype=np.int64), hdf5.I32)
    put('str', ['Cs-137', 'åäö', '日本', '😀', '', 'Cs-137', 'åäö', 1, 1.5, 1e21, None, True, False,
                [1, 2], {'a': 1}, 'TRUE'], hdf5.STR, {'unit': 'Cs-137', 'flag': True})
    put('str_empty', [], hdf5.STR)
    put('str_text_data', 'xyz', hdf5.STR)
    put('matrix_f64', np.arange(12, dtype=np.float64).reshape(3, 4) / 7.0, hdf5.F64, {'shape': [3, 4]})
    put('matrix_f32', np.arange(6, dtype=np.float64).reshape(2, 3) / 3.0, hdf5.F32)
    put('matrix_given_dims', np.arange(6, dtype=np.float64).reshape(2, 3), hdf5.F64, None, [3, 2])
    put('cube', np.arange(24, dtype=np.float64).reshape(2, 3, 4), hdf5.F64)
    put('flat_dims', [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], hdf5.F32, {'n_iter': 3}, [2, 3])
    put('dims_float_text', [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], hdf5.F64, None, [2.0, '3'])
    put('scalar', [42.0], hdf5.F64, None, [])
    put('scalar_str', ['one'], hdf5.STR, None, [])
    put('dims_zero', [], hdf5.F64, None, [0, 5])
    put('np_bool', np.array([True, False, True]), hdf5.F64)
    return root


def build_names(rec):
    root = rec.group({'model': 'names'})
    long = 'L' * 300
    rec.put(root, [long], rec.dataset([1.0], hdf5.F64, {long: 'long attribute name'}))
    rec.put(root, ['å' * 200], rec.dataset([2.0]))           # 400 bytes: a long link
    rec.put(root, ['x' * 255], rec.dataset([3.0]))           # exactly 255
    rec.put(root, ['y' * 256], rec.dataset([4.0]))           # just over
    rec.put(root, ['with space', 'Cs-137'], rec.dataset([5.0]))
    rec.put(root, ['k.eff'], rec.dataset([6.0]))
    rec.put(root, ['Söil ⁄ Lake'], rec.dataset([7.0]))
    return root


def build_surrogates(rec):
    root = rec.group({'lone': '\ud800', 'pair': '😀', 'joined': '😀'})
    rec.put(root, ['s'], rec.dataset(['\ud800', 'a\udc00b', '😀', '😀', '\udc00\ud800', '😀'], hdf5.STR))
    return root


def build_two_collections(rec):
    # More strings than one global heap collection holds (60000): the second
    # collection, and heap IDs that point into both.
    root = rec.group({'first': 'string 0', 'last': 'string 69999'})
    strings = [f'string {k}' for k in range(70000)]
    rec.put(root, ['strings'], rec.dataset(strings, hdf5.STR))
    rec.put(root, ['again'], rec.dataset(['string 59999', 'string 60000', 'new one', 'string 5'], hdf5.STR,
                                         {'unit': 'string 65000', 'other': 'after them all'}))
    return root


def build_big(rec):
    root = rec.group({'model': 'big'})
    rng = np.random.default_rng(1)
    rec.put(root, ['time'], rec.dataset(np.linspace(0.0, 1e4, 1000), hdf5.F64, {'unit': 'year'}))
    rec.put(root, ['big'], rec.dataset(rng.standard_normal(1_000_000) * 1e5, hdf5.F64, {'unit': 'Bq'}))
    rec.put(root, ['big32'], rec.dataset(rng.standard_normal(100_000), hdf5.F32))
    return root


# --- result trees -------------------------------------------------------------------------------

def o(label, block=..., kind='compartment', nuclide=None, index=None, dims=None, unit='Bq', **extra):
    d = {'kind': kind, 'block': label.split(' [')[0] if block is ... else block, 'nuclide': nuclide,
         'index': index, 'dims': dims if dims is not None else [], 'label': label, 'unit': unit, 'source': 'y',
         'offset': 0}
    d.update(extra)
    return d


def demo_outputs():
    outs = [
        o('Soil [Cs-137]', nuclide='Cs-137', index=['Cs-137'], dims=['Radionuclides']),
        o('Soil [H-3]', nuclide='H-3', index=['H-3'], dims=['Radionuclides']),
        o('NearField.Flux', kind='expression', unit='Bq/y'),
        o('Dose [Lake, Cs-137]', kind='expression', nuclide='Cs-137', index=['Lake', 'Cs-137'],
          dims=['Areas', 'Radionuclides'], unit='Sv/y'),
        o('Dose [Lake, H-3]', kind='expression', nuclide='H-3', index=['Lake', 'H-3'],
          dims=['Areas', 'Radionuclides'], unit='Sv'),
        o('Dose [Mire, Cs-137]', kind='expression', nuclide='Cs-137', index=['Mire', 'Cs-137'],
          dims=['Areas', 'Radionuclides'], unit='Sv/y'),
        o('Flow [A, x]', kind='transfer', index=['A', 'x'], dims=['L1', 'L2'], unit='m3/y'),
        o('Flow [B, x]', kind='transfer', nuclide='Pu-239', index=['B', 'x'], dims=['L1', 'L2'], unit='m3/y'),
        o('porosity', kind='parameter', unit='unitless', source='P', timeDependent=False),
        o('Kd [Cs-137]', kind='parameter', nuclide='Cs-137', index=['Cs-137'], dims=['Radionuclides'],
          unit='m3/kg', source='P', timeDependent=False),
        o('a/b [x]', block='a/b', index=['x/y'], dims=['L2'], unit=None),
        o(' spaced ', block='  spaced  ', unit=0),
        o('dot', block='.'),
        o('empty block', block=''),
        o('dots', block='sys..sub.Block'),
        o('quote "x", y\nz', block='Odd', unit='Bq'),
        o('Söil [Cs-137]', nuclide='Cs-137', index=['Cs-137'], dims=['Radionuclides']),
        {'kind': 'compartment', 'block': None, 'label': None, 'unit': 'Bq'},
        {'kind': None, 'unit': 'Bq'},
        {'unit': 'Bq'},
        o('Numbers [1, 2]', index=[1, 2], dims=['N', 'M'], nuclide=2),
        o('Short dims [Lake, Cs-137]', nuclide='Cs-137', index=['Lake', 'Cs-137'], dims=['Radionuclides']),
        o('Null dims [p, q]', index=['p', 'q'], dims=[None, None]),
        o('NearField', kind='expression', unit='Bq'),
        o('Pair [Lake, Cs-137]', nuclide=None, index=['Lake', 'Cs-137'], dims=['Areas', '']),
        o('Bool unit', unit=True),
        o('Number nuclide [Cs-137]', nuclide=137, index=['Cs-137'], dims=['Radionuclides']),
    ]
    return outs


def demo_columns(n_out, times, seed=3):
    rnd = random.Random(seed)
    cols = []
    for k in range(n_out):
        col = [rnd.uniform(0, 1) * 10 ** rnd.randint(-20, 20) for _ in range(times)]
        if k % 5 == 0:
            col[1] = math.nan
        if k % 7 == 0:
            col[-1] = math.inf
        cols.append(col)
    return cols


DESCRIPTION = 'Line one & <two>\r\nline three\r\n\r\n\r\nSecond paragraph\rwith a CR.\n\n  '

PROJECT = {
    'name': 'Demo model', 'description': DESCRIPTION,
    'simulation': {'time_unit': 'day', 'start_time': '5', 'end_time': None, 'solver': 'bdf'},
    'index_lists': [{'name': 'Cases', 'for_scenarios': True, 'indices': ['A', 'B']}],
}

INDEX_LISTS = [
    {'name': 'Radionuclides', 'indices': [{'name': 'Cs-137', 'enabled': True}, {'name': 'H-3', 'enabled': False},
                                          'Bare', None, {'name': None}, ['x'], {'name': 137}]},
    {'name': 'Areas', 'elements': ['Lake', 'Mire', None]},
    {'name': 'Empty', 'indices': []},
    {'name': 'a/b', 'elements': ['x']},
    {'elements': ['y']},
    {'name': 'Radionuclides', 'elements': ['dup']},
    {'name': None, 'indices': [{'name': 'n1'}]},
    {'name': 'Chars', 'elements': 'xyz'},
    {'name': 'Off', 'indices': [{'name': 'gone', 'enabled': False}]},
    {'name': 'Keys', 'indices': {'k1': 1, 'k2': 2}},
]


def result_tree_case(name, *, t, outputs, columns, which, project=None, index_lists=None, now=NOW,
                     realisations=None, sample=None, real_object=False):
    CASE[0] = name
    mats = None
    if realisations is not None:
        mats = realisations['matrices']

        def matrix_for(i):
            return mats.get(i)

        rz = types.SimpleNamespace(iterations=realisations['iterations'], matrixFor=matrix_for) if real_object \
            else {'iterations': realisations['iterations'], 'matrix_for': matrix_for}
    else:
        rz = None
    tree = resultfile.result_tree(t=np.asarray(t, dtype=float), outputs=outputs,
                                  column=lambda i: np.asarray(columns[i], dtype=float), which=which,
                                  project=project, index_lists=index_lists, now=now, realisations=rz,
                                  sample=types.SimpleNamespace(**sample) if isinstance(sample, dict) and real_object
                                  else sample)
    spec = {'t': hexfloats(t), 'outputs': enc(outputs), 'columns': [hexfloats(c) for c in columns],
            'which': [i + 1 for i in which], 'project': enc(project), 'index_lists': enc(index_lists),
            'now': enc(now), 'sample': enc(sample), 'object_form': real_object,
            'realisations': None if realisations is None else {
                'iterations': enc(realisations['iterations']),
                'matrices': [[i + 1, enc(m)] for i, m in mats.items()]}}
    emit(name, 'result_tree', hdf5.write_hdf5(tree), **spec)


def result_tree_cases():
    outs = demo_outputs()
    t = [0.0, 1.0, 2.5, 10.0, 1e3, 1e5]
    cols = demo_columns(len(outs), len(t))
    every = list(range(len(outs)))
    result_tree_case('rt_basic', t=t, outputs=outs, columns=cols, which=every, project=PROJECT,
                     index_lists=INDEX_LISTS)
    result_tree_case('rt_subset', t=t, outputs=outs, columns=cols, which=[3, 0, 3, 8, 8, 2, 23],
                     project={'name': 7, 'simulation': {'time_unit': ['a', 'b'], 'start_time': 'x',
                                                        'end_time': 1e21, 'solver': 3}},
                     index_lists=None)
    result_tree_case('rt_epoch', t=t[:3], outputs=outs[:3], columns=[c[:3] for c in cols[:3]], which=[0, 1, 2],
                     project=None, now=1760000000.75)
    result_tree_case('rt_empty_t', t=[], outputs=outs[:2], columns=[[], []], which=[0, 1],
                     project={'name': None, 'description': '   ', 'simulation': None})

    # every realisation: n = 5 at 4 times; a still series given more values than
    # realisations (cut), one that was not part of the run (None: its curve).
    rt_t = [0.0, 1.0, 2.0, 3.0]
    n = 5
    rng = np.random.default_rng(5)
    routs = [outs[0], outs[1], outs[8], outs[9], outs[2], outs[3]]
    rcols = demo_columns(len(routs), len(rt_t), seed=9)
    mats = {0: (rng.standard_normal(len(rt_t) * n) * 1e3).astype(np.float32),
            1: rng.standard_normal(len(rt_t) * n),               # float64, rounded to float32 when written
            2: rng.standard_normal(n).astype(np.float32),
            3: rng.standard_normal(n + 3).astype(np.float32),     # cut to n
            5: rng.standard_normal(len(rt_t) * n).astype(np.float32)}
    result_tree_case('rt_realisations', t=rt_t, outputs=routs, columns=rcols, which=list(range(len(routs))),
                     project=PROJECT, index_lists=INDEX_LISTS[:2], realisations={'iterations': n, 'matrices': mats})
    result_tree_case('rt_realisations_object', t=rt_t, outputs=routs, columns=rcols, which=list(range(len(routs))),
                     project=PROJECT, realisations={'iterations': n, 'matrices': mats},
                     sample={'iterations': 99, 'of': 3}, real_object=True)
    result_tree_case('rt_sample_mean', t=t, outputs=outs, columns=cols, which=every[:12], project=PROJECT,
                     sample={'iterations': 100, 'of': 'mean'})
    result_tree_case('rt_sample_k', t=t, outputs=outs, columns=cols, which=every[:12], project=PROJECT,
                     sample={'iterations': 100, 'of': 7}, real_object=True)
    result_tree_case('rt_sample_odd', t=t, outputs=outs[:3], columns=cols[:3], which=[0, 1, 2], project=PROJECT,
                     sample={'of': '12'})


# --- probabilistic runs -------------------------------------------------------------------------

class FakeProject:
    def __init__(self, raw, index_lists):
        self._raw = raw
        self.index_lists = index_lists


class FakeProb:
    def __init__(self, t, outputs, values, samples, ran, iterations, inputs):
        self.t, self.outputs, self.values, self.samples = t, outputs, values, samples
        self.ran, self.iterations, self.inputs = ran, iterations, inputs


def project_spec(p):
    if isinstance(p, FakeProject):
        return {'$project': {'raw': enc(p._raw), 'index_lists': enc(p.index_lists)}}
    return enc(p)


def make_prob(n, times, seed, precision=np.float64):
    rng = np.random.default_rng(seed)
    t = np.linspace(0.0, 100.0, times)
    outs = [o('Soil [Cs-137]', nuclide='Cs-137', index=['Cs-137'], dims=['Radionuclides']),
            o('Soil [H-3]', nuclide='H-3', index=['H-3'], dims=['Radionuclides']),
            o('Peak', kind='expression', unit='Bq', timeDependent=False),
            o('Flux', kind='expression', unit='Bq/y')]
    values = []
    for k in range(len(outs)):
        m = (rng.standard_normal((n, times)) * 10.0 ** rng.integers(-5, 5)).astype(precision)
        m[rng.random((n, times)) < 0.05] = np.nan
        if k == 3 and n > 2:
            m[1, :] = np.inf
        values.append(m)
    ran = np.ones(n, dtype=np.uint8)
    if n > 3:
        ran[2] = 0
        for m in values:
            m[2, :] = np.nan
    samples = rng.lognormal(0.0, 2.0, size=(3, n))
    samples[1, 0] = np.inf
    inputs = [{'output': o('porosity', kind='parameter', unit='unitless', source='P', timeDependent=False), 'k': 0},
              {'output': o('Kd [Cs-137]', kind='parameter', nuclide='Cs-137', index=['Cs-137'],
                           dims=['Radionuclides'], unit='m3/kg', source='P', timeDependent=False), 'k': 2},
              {'output': o('Flux', kind='parameter', source='P', timeDependent=False), 'k': 1}]  # label taken
    return FakeProb(t, outs, values, samples, ran, n, inputs)


def prob_spec(p):
    return {'t': hexfloats(p.t), 'outputs': enc(p.outputs), 'values': [enc(v) for v in p.values],
            'samples': enc(p.samples), 'ran': enc(p.ran), 'iterations': p.iterations,
            'inputs': [{'output': enc(i['output']), 'k': i['k'] + 1} for i in p.inputs]}


def prob_case(name, prob, want, *, which=None, project=None, index_lists=None, inputs=True, now=NOW):
    CASE[0] = name
    tree = resultfile.probabilistic_tree(prob, want, which=which, project=project, index_lists=index_lists,
                                         now=now, inputs=inputs)
    which_spec = None if which is None else [w + 1 if isinstance(w, int) else enc(w) for w in which]
    emit(name, 'probabilistic_tree', hdf5.write_hdf5(tree), prob=prob_spec(prob), want=enc(want),
         which=which_spec, project=project_spec(project), index_lists=enc(index_lists), inputs=inputs,
         now=enc(now))


def prob_cases():
    lists = [{'name': 'Radionuclides', 'indices': [{'name': 'Cs-137', 'enabled': True},
                                                   {'name': 'H-3', 'enabled': True}]}]
    proj = FakeProject(PROJECT, lists)
    p13 = make_prob(13, 6, 11)
    prob_case('prob_all', p13, 'all', project=proj)
    prob_case('prob_mean', p13, 'mean', project=proj)
    prob_case('prob_k', p13, 7, project=proj)
    prob_case('prob_k_clamped_low', p13, 0, project=proj, inputs=False)
    prob_case('prob_k_clamped_high', p13, 1e9, project=proj)
    prob_case('prob_k_text', p13, '3', project=proj, which=['Soil [H-3]', 3, 'porosity'])
    prob_case('prob_k_nan', p13, math.nan, project=proj)
    p300 = make_prob(300, 5, 12, np.float32)
    prob_case('prob_mean_300_f32', p300, 'mean', project=proj)
    prob_case('prob_all_300_f32', p300, 'all', project=proj)
    p1 = make_prob(150, 1, 13)
    prob_case('prob_mean_one_time', p1, 'mean', project=proj)
    prob_case('prob_dict_project', p13, 'mean', project={'name': 'Dict', 'nuclides': ['Cs-137', 'H-3'],
                                                         'compartments': [{'name': 'Soil'}, {'name': 'Lake'}],
                                                         'transfers': [{'name': 'Leach'}]})
    prob_case('prob_no_ran', FakeProb(p13.t, p13.outputs, p13.values, p13.samples, None, 13, p13.inputs), 'mean',
              project=proj, index_lists=[])


# --- scenarios ----------------------------------------------------------------------------------

class FakeResults:
    """What the result writers read of a run: t, outputs(), series_many(), series(), project."""

    def __init__(self, t, outs, cols, project):
        self.t = np.asarray(t, dtype=float)
        self._outs = outs
        self._cols = [np.asarray(c, dtype=float) for c in cols]
        self.project = project

    def outputs(self):
        return self._outs

    def series_many(self, outs):
        return [self._cols[next(k for k, x in enumerate(self._outs) if x is o)] for o in outs]

    def series(self, o):
        return self.series_many([o])[0]


def results_spec(r):
    return {'t': hexfloats(r.t), 'outputs': enc(r.outputs()), 'columns': [hexfloats(c) for c in r._cols],
            'project': project_spec(r.project)}


def scenario_case(name, runs, which=None, **kw):
    CASE[0] = name
    tree = resultfile.scenarios_tree(runs, which, now=NOW, **kw)
    spec = {'runs': [[k, results_spec(r)] for k, r in runs.items()],
            'which': None if which is None else [w + 1 if isinstance(w, int) else enc(w) for w in which],
            'active': kw.get('active'), 'project': project_spec(kw.get('project')),
            'index_lists': enc(kw.get('index_lists'))}
    emit(name, 'scenarios_tree', hdf5.write_hdf5(tree), **spec)


def scenario_cases():
    outs_a = [o('Soil [Cs-137]', nuclide='Cs-137', index=['Cs-137'], dims=['Radionuclides']),
              o('Soil [H-3]', nuclide='H-3', index=['H-3'], dims=['Radionuclides']),
              o('Flux', kind='expression', unit='Bq/y'),
              o('porosity', kind='parameter', unit='unitless', source='P', timeDependent=False)]
    outs_b = [o('Flux', kind='expression', unit='Bq/y'),
              o('Soil [Cs-137]', nuclide='Cs-137', index=['Cs-137'], dims=['Radionuclides']),
              o('Flux', kind='expression', unit='Bq/h'),                          # the last of a label wins
              o('porosity', kind='parameter', unit='unitless', source='P', timeDependent=False)]
    ta = [0.0, 1.0, 2.0, 5.0, 10.0]
    tb = [0.5, 1.0, 4.0, 4.0, 8.0, 9.0]
    proj_a = FakeProject({'name': 'Scenario model', 'description': 'Two scenarios.',
                          'simulation': {'time_unit': 'year', 'start_time': 0, 'end_time': 10},
                          'index_lists': [{'name': 'Cases', 'for_scenarios': True, 'indices': ['A', 'B']}]},
                         [{'name': 'Radionuclides', 'indices': [{'name': 'Cs-137', 'enabled': True},
                                                                {'name': 'H-3', 'enabled': True}]},
                          {'name': 'Cases', 'for_scenarios': True, 'indices': [{'name': 'A', 'enabled': True},
                                                                              {'name': 'B', 'enabled': True}]}])
    a = FakeResults(ta, outs_a, demo_columns(4, len(ta), seed=21), proj_a)
    b = FakeResults(tb, outs_b, demo_columns(4, len(tb), seed=22), proj_a)
    c = FakeResults(ta, outs_a, demo_columns(4, len(ta), seed=23), proj_a)
    scenario_case('scen_two', {'A': a, 'B': b})
    scenario_case('scen_active_b', {'A': a, 'B': b, 'C': c}, active='B')
    scenario_case('scen_which', {'A': a, 'C': c}, which=['Soil [H-3]', 0, 'porosity'])
    scenario_case('scen_one', {'A': a})
    proj_plain = FakeProject({'name': 'No list'}, [])
    d = FakeResults(ta, outs_a, demo_columns(4, len(ta), seed=24), proj_plain)
    e = FakeResults(ta, outs_a, demo_columns(4, len(ta), seed=25), proj_plain)
    scenario_case('scen_default_list', {'Base': d, 'Alt': e}, project={'name': 'Given'},
                  index_lists=[{'name': 'L', 'elements': ['x']}])


# --- through real runs --------------------------------------------------------------------------

def real_results_spec(res):
    outs = res.outputs()
    cols = res.series_many(outs)
    return {'t': hexfloats(res.t), 'outputs': enc(outs), 'columns': [hexfloats(c) for c in cols],
            'project': {'$project': {'raw': enc(res.project._raw), 'index_lists': enc(res.project.index_lists)}}}


def real_cases():
    import kompartment as kp
    CASE[0] = 'e2e_biosphere'
    res = kp.Model.load(str(EXAMPLES / 'biosphere.json')).run()
    spec = real_results_spec(res)
    emit('e2e_biosphere', 'results_tree', resultfile.write_results_hdf5(res, now=NOW), results=spec, which=None)
    outs = res.outputs()
    which = [outs[5]['label'], 3, outs[0], outs[-1]['label'], 0]
    CASE[0] = 'e2e_biosphere_which'
    emit('e2e_biosphere_which', 'results_tree', resultfile.write_results_hdf5(res, None, which, now=NOW),
         results=spec, which=[w + 1 if isinstance(w, int) else {'$output': outs.index(w) + 1}
                              if isinstance(w, dict) else w for w in which])
    CASE[0] = 'e2e_scenarios'
    runs = kp.Model.load(str(EXAMPLES / 'scenarios.json')).run_scenarios()
    emit('e2e_scenarios', 'scenarios_tree', resultfile.write_scenarios_hdf5(runs, now=NOW),
         runs=[[k, real_results_spec(r)] for k, r in runs.items()], which=None, active=None, project=None,
         index_lists=None)


def perf_case(series=20000, times=250):
    """A large file, for timing: the Julia test writes the same and compares."""
    CASE[0] = 'perf'
    rng = np.random.default_rng(99)
    t = np.linspace(0.0, 1e5, times)
    nuclides = [f'N-{k}' for k in range(50)]
    outs = []
    for k in range(series):
        nuc = nuclides[k % 50]
        block = f'Block{k // 50}'
        outs.append(o(f'{block} [{nuc}]', block=block, nuclide=nuc, index=[nuc], dims=['Radionuclides']))
    cols = rng.standard_normal((series, times))
    r = FakeResults(t, outs, [], FakeProject({'name': 'perf', 'simulation': {'time_unit': 'year'}},
                                             [{'name': 'Radionuclides',
                                               'indices': [{'name': n, 'enabled': True} for n in nuclides]}]))
    r._cols = cols
    index = {id(x): k for k, x in enumerate(outs)}
    r.series_many = lambda os_: [cols[index[id(x)]] for x in os_]
    started = time.perf_counter()
    data = resultfile.write_results_hdf5(r, now=NOW)
    took = time.perf_counter() - started
    emit('perf', 'perf', data, series=series, times=times, seconds=took,
         t=hexfloats(t), columns=enc(cols), nuclides=nuclides)
    print(f'  python wrote {series} series of {times} in {took:.2f} s')


# --- the CSV helpers and the two conversions ----------------------------------------------------

CSV_VALUES = [
    None, True, False, 0, -0.0, 1, -7, 1.5, 0.1 + 0.2, 100000, 1e21, 1e-7, 0.000015, 123e-20, 2 ** 53 + 1,
    2 ** 70, 5e-324, 1.7976931348623157e308, math.nan, math.inf, -math.inf,
    '', ' ', '5', ' 0x10 ', '0X1f', '0o17', '0b101', '0b2', '1e999', '-1e999', '1e-400', '2.4703282292062327e-324',
    'Infinity', '-Infinity', '+Infinity', 'infinity', 'inf', 'nan', 'NaN', '1_000', '.5', '5.', '+3', '-.5e-3',
    '1e', 'e5', '\u00a0 5 \ufeff', '\x855', '\u20285\u2029', '\u30005', '\u180e5', '12abc', '0x', '00012',
    'a,b', 'say "hi"', 'line\nbreak', 'cr\rhere', 'plain', 'åäö',
    [], [5], ['5'], [1, 2], [None], [True], [[1]], [[1, 2], [3]], [1.5, None, 'x'], {'a': 1}, {}, (1, 2),
    np.float32(0.1), np.int64(3), np.bool_(True), np.array([1.5, 2.5]), np.array([[1, 2], [3, 4]]),
]


def csv_cases():
    rows = []
    for v in CSV_VALUES:
        rows.append({'value': enc(v), 'js_string': kcsv.js_string(v), 'js_to_number': enc(kcsv.js_to_number(v)),
                     'csv_cell': kcsv.csv_cell(v)})
    t = [0.0, 1e-7, 2.5, 1e21]
    labels = ['Soil [Cs-137, Lake]', 'say "hi"', 'plain', None, 3]
    columns = [[1.0, math.nan, math.inf, -0.0], [1, 2], [], ['x', None, True, 1e-7], [0.5, 0.25, 0.125, 0.0625]]
    table = {'t': enc(t), 'labels': enc(labels), 'columns': enc(columns),
             'csv': kcsv.to_csv(t, labels, columns), 'row': kcsv.csv_row([1, None, 'a,b', 1e21, math.nan]),
             'header': kcsv.csv_header(labels)}
    return {'values': rows, 'table': table}


def main():
    for name, build in [('empty_root', build_empty), ('root_attrs', build_root_attrs), ('int_keys', build_int_keys),
                        ('nested', build_nested), ('many_children', build_many_children),
                        ('datasets', build_datasets), ('names', build_names), ('surrogates', build_surrogates),
                        ('two_collections', build_two_collections), ('big', build_big)]:
        tree_case(name, build)
    result_tree_cases()
    prob_cases()
    scenario_cases()
    real_cases()
    if os.environ.get('KOMPARTMENT_H5_PERF', '1') != '0':
        perf_case()
    (OUT / 'cases.json').write_text(json.dumps({'cases': CASES, 'csv': csv_cases()}, ensure_ascii=True))
    print(f'{len(CASES)} cases in {OUT}')


if __name__ == '__main__':
    main()
