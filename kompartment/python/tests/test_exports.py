"""The result and data exports against the application's own.

Every bundled example (``examples/*.json``) is exported by the application's
modules through Node (``tests/node/exports.mjs``) and by this package, and the
two are compared:

* **HDF5 result files** (``io/resultfile.py``): fed the application's own
  times, descriptors and series, the file is the application's byte for byte;
  from a run of the Python engine, the tree is the same -- every path, every
  attribute, every datatype -- and the values agree to the runs' own round-off.
* **Results archives** (``io/dataset.py``): an archive the application wrote
  opens here as a live run whose series are the application's, and written
  back from here it is the application's archive to the byte (stored) or entry
  for entry (deflated); an archive written here opens in the application, and
  here, as the run it came from. The refusals say what the application says.
* **Data tables** (``datatable.py``): the rows collected from every example
  are the application's, and rows applied back -- as collected, changed, read
  back from a file, or naming blocks that are not there -- leave the model as
  the application leaves it and report what it reports.
* **Data files** (``io/datafile.py``): workbooks and HDF5 data files are the
  application's bytes, and each reads the other's alike, hand-made files with
  samples in them included.
* **The run log** (``engine/runlog.py``): the same payload is the same text.
* **Several scenarios, and a probabilistic run** (``io/resultfile.py``): the
  file the page writes of a table holding several scenarios, and the one
  *Save → Realisations* writes -- every run, their mean, or one of them --
  alike in shape, and to the byte when fed the same numbers.
"""

from __future__ import annotations

import base64
import copy
import datetime as dt
import json
import math
import os
import struct
import subprocess
import unittest
import zlib
from array import array
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from helpers import EXAMPLES, NODE, SRC, differences, example, needs_app

from kompartment import datatable as dtab
from kompartment.engine import runlog
from kompartment.engine.atstart import run_scenarios
from kompartment.engine.builder import build_system
from kompartment.engine.probabilistic import run_probabilistic
from kompartment.engine.project import Project
from kompartment.engine.runner import run
from kompartment.io import datafile, dataset, hdf5, resultfile
from kompartment.io.xlsx import _zip
from kompartment.jsonio import dumps
from kompartment.names import qualified_name

SCRIPT = Path(__file__).resolve().parent / 'node' / 'exports.mjs'
NAMES = sorted(p.stem for p in EXAMPLES.glob('*.json'))
NOW = [2026, 9, 13, 20, 30, 0]
STAMP = '2026-09-16T00:00:00.000Z'
LOG = ['Kompartment run log — build test', '', 'settings', '  solver: ndf']
TYPED = {'Float64Array': 'd', 'Float32Array': 'f', 'Int32Array': 'i', 'Uint8Array': 'B'}
DT_NAMES = {hdf5.F64: 'F64', hdf5.F32: 'F32', hdf5.I32: 'I32', hdf5.STR: 'STR'}

#: The worst differences seen, by test, for the report at the end of a run.
WORST: Dict[str, float] = {}


# --- talking to the application -----------------------------------------------

def enc(v: Any) -> Any:
    """A Python value as the tagged JSON the bridge reads (see exports.mjs)."""
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float):
        if math.isnan(v):
            return {'$num': 'NaN'}
        if math.isinf(v):
            return {'$num': 'Infinity' if v > 0 else '-Infinity'}
        if v == 0 and math.copysign(1, v) < 0:
            return {'$num': '-0'}
        return v
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, array):
        name = {'d': 'Float64Array', 'f': 'Float32Array', 'i': 'Int32Array', 'B': 'Uint8Array'}[v.typecode]
        return {'$typed': name, 'v': [enc(x) for x in v]}
    if isinstance(v, np.ndarray):
        name = {'f': 'Float32Array', 'i': 'Int32Array'}.get(v.dtype.kind, 'Float64Array')
        if v.dtype == np.float64:
            name = 'Float64Array'
        return {'$typed': name, 'v': [enc(x) for x in v.reshape(-1).tolist()]}
    if isinstance(v, dict):
        return {k: enc(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [enc(x) for x in v]
    raise TypeError(f'{type(v).__name__} cannot go to the application')


def dec(v: Any) -> Any:
    """What the bridge answered, as the Python value that means the same."""
    if isinstance(v, list):
        return [dec(x) for x in v]
    if isinstance(v, dict):
        if '$num' in v:
            return -0.0 if v['$num'] == '-0' else float(v['$num'].replace('Infinity', 'inf'))
        if '$undef' in v:
            return None
        if '$typed' in v:
            return array(TYPED[v['$typed']], [dec(x) for x in v['v']])
        if '$map' in v:
            return {dec(k): dec(x) for k, x in v['$map']}
        return {k: dec(x) for k, x in v.items()}
    return v


def js(*requests: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Asks the application's own modules, all the requests in one Node run."""
    assert NODE is not None
    env = dict(os.environ, LANG='en_US.UTF-8', LC_ALL='en_US.UTF-8')
    proc = subprocess.run([NODE, str(SCRIPT), str(SRC)],
                          input=json.dumps({'task': 'batch', 'requests': [enc(r) for r in requests]}),
                          capture_output=True, text=True, timeout=1800, encoding='utf-8', env=env)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return json.loads(proc.stdout)['results']


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def unb64(text: str) -> bytes:
    return base64.b64decode(text)


# --- comparing ---------------------------------------------------------------

def canon(x: Any) -> Any:
    """One comparable shape: every number a float, the special ones tagged, a
    typed array tagged, whatever it was held in."""
    if isinstance(x, np.generic):
        x = x.item()
    if x is None or isinstance(x, (bool, str)):
        return x
    if isinstance(x, (int, float)):
        f = float(x)
        if math.isnan(f):
            return {'$num': 'NaN'}
        if math.isinf(f):
            return {'$num': 'Infinity' if f > 0 else '-Infinity'}
        if f == 0 and math.copysign(1, f) < 0:
            return {'$num': '-0'}
        return f
    if isinstance(x, (array, np.ndarray)):
        return {'$typed': [canon(v) for v in (x.reshape(-1).tolist() if isinstance(x, np.ndarray) else x)]}
    if isinstance(x, dict):
        return {k: canon(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [canon(v) for v in x]
    return x


def row_out(r: Dict[str, Any]) -> Dict[str, Any]:
    """A row as the bridge sends one: the block by its qualified name."""
    return {k: (qualified_name(v) if k == 'block' and isinstance(v, dict) else v) for k, v in r.items()}


def same_rows(test: unittest.TestCase, mine: List[Dict[str, Any]], theirs: List[Any], what: str) -> None:
    diff = differences(canon([row_out(r) for r in mine]), canon(dec(theirs)))
    test.assertEqual(diff, [], f'{what}: ' + '; '.join(diff[:8]))


def dump_tree(root: Any) -> List[Dict[str, Any]]:
    """A tree, depth first, as the bridge dumps the application's."""
    out: List[Dict[str, Any]] = []

    def walk(n: Any, p: str) -> None:
        if n.kind == 'group':
            out.append({'path': p or '/', 'kind': 'group', 'attrs': dict(n.attrs)})
            for name, child in n.children.items():
                walk(child, f'{p}/{name}')
            return
        data = n.data.tolist() if hasattr(n.data, 'tolist') else list(n.data)
        out.append({'path': p, 'kind': 'dataset', 'attrs': dict(n.attrs), 'dt': DT_NAMES[n.dt],
                    'dims': list(n.dims) if n.dims is not None else None, 'data': data})

    walk(root, '')
    return out


def tree_shape(entries: List[Dict[str, Any]]) -> List[Any]:
    """A dumped tree without its numbers: what is where, and what it says it is.
    An attribute of nothing is left out, as the writer leaves it out."""
    return canon([{'path': e['path'], 'kind': e['kind'], 'dt': e.get('dt'),
                   'attrs': {k: v for k, v in e['attrs'].items() if v is not None}} for e in entries])


def worst_relative(a: Any, b: Any) -> float:
    """The largest difference between two series over the scale of the second,
    as the engine's own parity test measures a run."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    same = (a == b) | (np.isnan(a) & np.isnan(b))
    if same.all():
        return 0.0
    finite = np.isfinite(b)
    scale = np.max(np.abs(b[finite])) if finite.any() else 0.0
    diff = np.abs(a - b)[~same]
    if not np.isfinite(diff).all():
        return math.inf
    return float(diff.max() / scale) if scale > 0 else math.inf


def note_worst(key: str, value: float) -> None:
    WORST[key] = max(WORST.get(key, 0.0), value)


def zip_layout(data: bytes) -> Dict[str, Any]:
    """Everything in a ZIP but the compressed bytes: every header field, and
    each entry's data as it comes out."""
    entries = []
    p = 0
    while data[p:p + 4] == b'PK\x03\x04':
        (_, need, flags, method, time, date, crc, csize, usize, nlen, xlen) = struct.unpack_from(
            '<IHHHHHIIIHH', data, p)
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


def opened_models() -> Dict[str, Dict[str, Any]]:
    """Every example as the application holds it once opened."""
    got = js(*[{'task': 'normalise', 'model': example(n)} for n in NAMES])
    return {n: g['model'] for n, g in zip(NAMES, got)}


_OPENED: Optional[Dict[str, Dict[str, Any]]] = None


def opened() -> Dict[str, Dict[str, Any]]:
    global _OPENED
    if _OPENED is None:
        _OPENED = opened_models()
    return _OPENED


# --- result files ------------------------------------------------------------

@needs_app
class ResultFiles(unittest.TestCase):
    """HDF5 result files, as the page's Export to HDF5 writes them."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.answers = dict(zip(NAMES, js(*[{'task': 'result', 'model': example(n), 'now': NOW} for n in NAMES])))

    def test_the_same_numbers_make_the_same_file(self) -> None:
        for name in NAMES:
            with self.subTest(example=name):
                got = self.answers[name]
                self.assertNotIn('error', got, got.get('error'))
                cols = dec(got['columns'])
                tree = resultfile.result_tree(
                    t=dec(got['t']), outputs=dec(got['outputs']), column=lambda i, cols=cols: cols[i],
                    which=got['which'], project=got['project'], index_lists=got['indexLists'],
                    now=dt.datetime(*NOW))
                self.assertEqual(differences(canon(dump_tree(tree)), canon(dec(got['tree']))), [])
                self.assertEqual(hdf5.write_hdf5(tree), unb64(got['data']))

    def test_a_python_run_makes_the_application_s_tree(self) -> None:
        grids_differ = []
        for name in NAMES:
            with self.subTest(example=name):
                got = self.answers[name]
                res = run(Project(got['project']))
                tree = resultfile.results_tree(res, project=got['project'], index_lists=got['indexLists'],
                                               now=dt.datetime(*NOW))
                mine, theirs = dump_tree(tree), dec(got['tree'])
                # Every path, every attribute, every datatype: exactly.
                diff = differences(tree_shape(mine), tree_shape(theirs))
                self.assertEqual(diff, [], '; '.join(diff[:6]))
                t_js = dec(got['t'])
                same_grid = len(res.t) == len(t_js) and worst_relative(res.t, t_js) < 1e-9
                if not same_grid:
                    grids_differ.append(name)
                rtol = float(got['project']['simulation'].get('rtol', 1e-3))
                for a, b in zip(mine, theirs):
                    if a['kind'] != 'dataset':
                        continue
                    # On two different output grids only what does not move
                    # over the run can be compared value for value.
                    if not same_grid and (a['path'] == '/time' or a['attrs'].get('time_dependent') is not False):
                        continue
                    self.assertEqual(a['dims'], b['dims'], a['path'])
                    if a['dt'] == 'STR':
                        self.assertEqual(a['data'], b['data'], a['path'])
                        continue
                    w = worst_relative(a['data'], b['data'])
                    note_worst(f'result tree, Python run ({name})', w)
                    self.assertLess(w, 10 * rtol, a['path'])
        # The one run whose output times are the solver's own steps: the
        # sparse ordering is chosen by timing, in both engines, so its steps
        # -- and with them its grid -- can differ from one run to the next.
        # Its tree is compared in full, its values where they do not move.
        self.assertLessEqual(set(grids_differ), {'farfield'})

    def test_the_file_reads_back_as_the_application_reads_it(self) -> None:
        from kompartment.io.hdf5read import read_hdf5
        got = self.answers['biosphere']
        res = run(Project(got['project']))
        data = resultfile.write_results_hdf5(res, project=got['project'], index_lists=got['indexLists'],
                                             now=dt.datetime(*NOW))
        mine = read_hdf5(data)
        theirs = read_hdf5(unb64(got['data']))
        self.assertEqual([d['path'] for d in mine['datasets']], [d['path'] for d in theirs['datasets']])
        self.assertEqual([d['attrs'] for d in mine['datasets']], [d['attrs'] for d in theirs['datasets']])
        self.assertEqual(mine['problems'], [])

    def test_realisations_and_samples_are_written_alike(self) -> None:
        t = array('d', [0.0, 10.0, 20.0])
        outputs = [
            {'label': 'Dose [I-129]', 'block': 'Dose', 'kind': 'expression', 'unit': 'Sv/year',
             'dims': ['Radionuclides'], 'index': ['I-129'], 'nuclide': 'I-129'},
            {'label': 'Kd', 'block': 'Kd', 'kind': 'parameter', 'unit': 'm^3/kg', 'dims': [], 'index': [],
             'timeDependent': False},
            {'label': 'bio.Soil [Cs-137, North]', 'block': 'bio.Soil', 'kind': 'compartment', 'unit': 'Bq',
             'dims': ['Radionuclides', 'Areas'], 'index': ['Cs-137', 'North'], 'nuclide': 'Cs-137'},
            {'label': 'rate', 'block': 'rate', 'kind': 'expression', 'unit': '', 'timeDependent': False},
        ]
        columns = [array('d', [1.5, 2.5, 3.5]), array('d', [0.25, 0.25, 0.25]), array('d', [7.0, 8.0, 9.0]),
                   array('d', [4.0, 4.0, 4.0])]
        matrices = {0: array('f', [0.1 * k for k in range(12)]), 1: array('f', [0.5, 0.6, 0.7, 0.8]),
                    3: array('f', [9.0, 8.0, 7.0, 6.0] * 3)}
        project = {'name': 'p', 'description': 'Two lines\nand <one> & more', 'simulation': {'time_unit': 'day'}}
        lists = [{'name': 'Radionuclides', 'elements': ['I-129', 'Cs-137']},
                 {'name': 'Areas', 'indices': [{'name': 'North'}, {'name': 'South', 'enabled': False}, 'West']}]
        cases = [
            {'realisations': {'iterations': 4, 'matrices': {str(k): v for k, v in matrices.items()}}},
            {'sample': {'iterations': 4, 'of': 'mean'}},
            {'sample': {'iterations': 1000, 'of': 7}},
            {'realisations': {'iterations': 4, 'matrices': {'0': matrices[0]}}, 'sample': {'iterations': 4, 'of': 2}},
            {},
        ]
        answers = js(*[{'task': 'tree', 't': t, 'outputs': outputs, 'columns': columns, 'which': [0, 1, 2, 3],
                        'project': project, 'indexLists': lists, 'now': NOW, **case} for case in cases])
        for case, got in zip(cases, answers):
            with self.subTest(case=list(case)):
                self.assertNotIn('error', got, got.get('error'))
                realisations = None
                if 'realisations' in case:
                    mats = {int(k): v for k, v in case['realisations']['matrices'].items()}
                    realisations = {'iterations': case['realisations']['iterations'],
                                    'matrix_for': lambda i, mats=mats: mats.get(i)}
                tree = resultfile.result_tree(t=t, outputs=outputs, column=lambda i: columns[i], which=[0, 1, 2, 3],
                                              project=project, index_lists=lists, now=dt.datetime(*NOW),
                                              realisations=realisations, sample=case.get('sample'))
                self.assertEqual(differences(canon(dump_tree(tree)), canon(dec(got['tree']))), [])
                self.assertEqual(hdf5.write_hdf5(tree), unb64(got['data']))

    def test_awkward_names_are_placed_alike(self) -> None:
        outputs = [
            {'label': 'a', 'block': 'kg/m2', 'unit': ''},
            {'label': 'b', 'block': 'kg/m2', 'unit': ''},
            {'label': 'c', 'block': '', 'unit': 0},
            {'label': 'd', 'block': None, 'unit': 'x'},
            {'label': 'e', 'unit': 'y', 'dims': ['L'], 'index': ['..'], 'block': 'B.  .C'},
            {'label': 'f', 'unit': 'y', 'dims': ['L', 'M'], 'index': ['p/q', ' '], 'nuclide': 'nope', 'block': 'B'},
            {'label': 'g', 'unit': 'z', 'dims': ['L', 'M'], 'index': ['p/q', 'r'], 'nuclide': 'p/q', 'block': 'B'},
            {'label': 'h', 'unit': 'y', 'dims': ['L'], 'index': ['s'], 'block': 'B.p⁄q'},
            {'label': 'i', 'block': 'time', 'unit': 's'},
        ]
        t = array('d', [0.0, 1.0])
        columns = [array('d', [k, k + 0.5]) for k in range(len(outputs))]
        which = list(range(len(outputs)))
        got = js({'task': 'tree', 't': t, 'outputs': outputs, 'columns': columns, 'which': which,
                  'project': {}, 'now': NOW})[0]
        self.assertNotIn('error', got, got.get('error'))
        tree = resultfile.result_tree(t=t, outputs=outputs, column=lambda i: columns[i], which=which, project={},
                                      now=dt.datetime(*NOW))
        self.assertEqual(differences(canon(dump_tree(tree)), canon(dec(got['tree']))), [])
        self.assertEqual(hdf5.write_hdf5(tree), unb64(got['data']))

    def test_descriptions_become_the_same_markup(self) -> None:
        texts = ['Line one\nline two\n\nA <later> one & more', '  ', None, '\r\nx\r\n\r\n\r\ny\rz', 5,
                 ' tabs\tand lines ', '&amp;', 'a\n\n\n\nb']
        got = js({'task': 'html', 'texts': texts})[0]
        self.assertEqual([resultfile.description_html(s) for s in texts], got['html'])


# --- results archives --------------------------------------------------------

def _series_agree(test: unittest.TestCase, labels: List[str], mine: List[Any], theirs: List[Any],
                  outputs: List[Dict[str, Any]], key: str) -> None:
    """States exactly, since they are the stored numbers; everything worked out
    from them to round-off, since two engines work them out."""
    for label, a, b, o in zip(labels, mine, theirs, outputs):
        if o['source'] == 'y':
            test.assertEqual(canon(list(np.asarray(a, dtype=float))), canon(list(np.asarray(b, dtype=float))), label)
            continue
        w = worst_relative(a, b)
        note_worst(key, w)
        test.assertLess(w, 1e-11, label)


@needs_app
class Archives(unittest.TestCase):
    """A model and its run in one archive, both ways."""

    @classmethod
    def setUpClass(cls) -> None:
        requests = []
        for n in NAMES:
            requests.append({'task': 'dataset', 'model': example(n), 'inner': f'{n}.json', 'stamp': STAMP,
                             'log': LOG, 'store': True})
        for n in ('recorders', 'waste-packages', 'post-processing'):
            requests.append({'task': 'dataset', 'model': example(n), 'inner': f'{n}.json', 'stamp': STAMP,
                             'log': LOG, 'store': False})
        got = js(*requests)
        cls.stored = dict(zip(NAMES, got[:len(NAMES)]))
        cls.deflated = dict(zip(('recorders', 'waste-packages', 'post-processing'), got[len(NAMES):]))

    def test_an_application_archive_opens_here_as_its_run(self) -> None:
        for name in NAMES:
            with self.subTest(example=name):
                got = self.stored[name]
                self.assertNotIn('error', got, got.get('error'))
                entries = dataset.unzip(unb64(got['archive']))
                self.assertEqual(list(entries), [f'{name}.json', *[e[0] for e in got['entries']]])
                self.assertTrue(dataset.is_dataset(entries))
                data = dataset.read_dataset(entries)
                res = dataset.restore_results(got['model'], None, data)
                outs = res.outputs()
                self.assertEqual([o['label'] for o in outs], got['labels'])
                _series_agree(self, got['labels'], res.series_many(outs), dec(got['columns']), outs,
                              'archive written by the application, read here')
                self.assertEqual(res.held_at_zero() and [(h['label'], h['steps']) for h in res.held_at_zero()],
                                 got['heldAtZero'] and [(h['label'], h['steps']) for h in got['heldAtZero']])
                stats = dec(got['stats'])
                self.assertEqual(canon({k: v for k, v in res.stats.items() if k != 'held' and v is not None}),
                                 canon({k: v for k, v in stats.items() if k != 'held' and v is not None}))

    def test_written_back_from_here_it_is_the_application_s_archive(self) -> None:
        for name in NAMES:
            with self.subTest(example=name):
                got = self.stored[name]
                archive = unb64(got['archive'])
                res = dataset.restore_results(got['model'], None, dataset.read_dataset(dataset.unzip(archive)))
                again = dataset.dataset_archive(res, project=got['model'], inner=f'{name}.json', stamp=STAMP, log=LOG,
                                                compress=False)
                if again != archive:
                    a, b = zip_layout(again), zip_layout(archive)
                    for x, y in zip(a['entries'], b['entries']):
                        self.assertEqual(x['content'], y['content'], x['name'])
                self.assertEqual(again, archive)
                entries = dataset.dataset_entries(got['model'], res, f'{name}.json', stamp=STAMP, log=LOG)
                self.assertEqual([[e['name'], b64(e['bytes'])] for e in entries], got['entries'])

    def test_deflated_it_is_the_application_s_archive_entry_for_entry(self) -> None:
        for name, got in self.deflated.items():
            with self.subTest(example=name):
                archive = unb64(got['archive'])
                res = dataset.restore_results(got['model'], None, dataset.read_dataset(dataset.unzip(archive)))
                again = dataset.dataset_archive(res, project=got['model'], inner=f'{name}.json', stamp=STAMP, log=LOG)
                mine, theirs = zip_layout(again), zip_layout(archive)
                self.assertEqual([e['name'] for e in mine['entries']], [e['name'] for e in theirs['entries']])
                for a, b in zip(mine['entries'], theirs['entries']):
                    self.assertEqual(a, b, a['name'])
                self.assertEqual(mine['central'], theirs['central'])
                self.assertEqual(mine['count'], theirs['count'])

    def test_an_archive_written_here_opens_in_the_application(self) -> None:
        models = opened()
        runs, archives = {}, []
        for name in NAMES:
            res = run(Project(models[name]))
            runs[name] = res
            archives.append(dataset.dataset_archive(res, project=models[name], stamp=STAMP, compress=name != 'farfield'))
        answers = js(*[{'task': 'restore', 'archive': b64(a)} for a in archives])
        for name, archive, got in zip(NAMES, archives, answers):
            with self.subTest(example=name):
                self.assertNotIn('error', got, got.get('error'))
                res = runs[name]
                outs = res.outputs()
                self.assertEqual(got['labels'], [o['label'] for o in outs])
                _series_agree(self, got['labels'], res.series_many(outs), dec(got['columns']), outs,
                              'archive written here, read by the application')
                stats = dec(got['stats'])
                mine = {({'solver_points': 'solverPoints', 'thinned_by': 'thinnedBy'}).get(k, k): v
                        for k, v in res.stats.items()}
                self.assertEqual(canon(stats), canon(mine))
                self.assertEqual(dec(got['timing']), {'buildMs': res.timing['build_ms'],
                                                      'solveMs': res.timing['solve_ms'],
                                                      **({'totalMs': res.timing['total_ms']}
                                                         if 'total_ms' in res.timing else {})})
                meta = got['meta']
                self.assertEqual(meta['stamp'], STAMP)
                self.assertEqual(meta['log'][0], f"Kompartment run log — build Python {__import__('kompartment').__version__}")
                self.assertEqual(meta['signature'], dataset.layout_signature(res.system))

    def test_an_archive_written_here_opens_here_as_the_same_run(self) -> None:
        for name in ('recorders', 'biosphere', 'post-processing', 'scenarios', 'waste-packages'):
            with self.subTest(example=name):
                res = run(Project(example(name)))
                back = dataset.load_results(dataset.dataset_archive(res, stamp=STAMP))
                outs = res.outputs()
                self.assertEqual([o['label'] for o in back.outputs()], [o['label'] for o in outs])
                for label, a, b in zip(res.labels, res.series_many(outs), back.series_many(back.outputs())):
                    self.assertEqual(canon(list(a)), canon(list(b)), label)
                self.assertTrue(back.timing['opened'])
                self.assertEqual(back.held_at_zero(), res.held_at_zero())

    def test_the_signatures_are_the_application_s(self) -> None:
        answers = js(*[{'task': 'signature', 'model': example(n)} for n in NAMES])
        models = opened()
        for name, got in zip(NAMES, answers):
            with self.subTest(example=name):
                system = build_system(Project(models[name]), jacobian=False)
                self.assertEqual(dataset.layout_signature(system), got['signature'])

    def test_what_is_refused_is_refused_alike(self) -> None:
        got = self.stored['biosphere']
        entries = dataset.unzip(unb64(got['archive']))
        meta = json.loads(entries[dataset.META])
        cases = {
            'truncated': {**entries, 'results/y.f64': entries['results/y.f64'][:64]},
            'newer': {**entries, dataset.META: json.dumps({**meta, 'format': 2}).encode()},
            'string format': {**entries, dataset.META: json.dumps({**meta, 'format': '7'}).encode()},
            'no run': {k: v for k, v in entries.items() if not k.startswith('results/')},
            'odd bytes': {**entries, 'results/t.f64': entries['results/t.f64'] + b'\x01\x02\x03'},
            'no held, short mem': {k: v for k, v in entries.items() if k != 'results/held.i32'},
            'states as text': {**entries, dataset.META: json.dumps({**meta, 'states': '16'}).encode()},
            'recorders odd': {**entries, dataset.META: json.dumps({**meta, 'recorders': [{'kind': 'x', 'n': None},
                                                                                        {'kind': 'y'}]}).encode()},
        }
        answers = js(*[{'task': 'readdataset', 'entries': [[k, b64(v)] for k, v in c.items()]}
                       for c in cases.values()])
        for (what, c), theirs in zip(cases.items(), answers):
            with self.subTest(case=what):
                try:
                    mine: Any = dataset.read_dataset(c)
                except dataset.DatasetError as e:
                    mine = {'error': str(e)}
                if 'error' in theirs:
                    self.assertEqual(mine, {'error': theirs['error']})
                elif theirs.get('none'):
                    self.assertIsNone(mine)
                else:
                    theirs = dec(theirs)
                    self.assertEqual(canon(mine['meta']), canon(theirs['meta']))
                    self.assertEqual(canon(mine['t']), canon(theirs['t']))
                    self.assertEqual(canon(list(mine['flat'])), canon(list(theirs['flat'])))
                    self.assertEqual(canon(None if mine['held'] is None else list(mine['held'])),
                                     canon(None if theirs['held'] is None else list(theirs['held'])))
                    self.assertEqual(canon(mine['memory']), canon(theirs['memory']))
        # A model whose state vector is another shape.
        wider = copy.deepcopy(got['model'])
        wider['compartments'].append({'name': 'Extra', 'initial': '0', 'index_lists': []})
        theirs = js({'task': 'restore', 'archive': got['archive'], 'project': wider})[0]
        with self.assertRaises(dataset.DatasetError) as caught:
            dataset.restore_results(wider, None, dataset.read_dataset(entries))
        self.assertEqual(str(caught.exception), theirs['error'])

    def test_what_is_in_the_file_is_described_alike(self) -> None:
        metas = [
            {'stamp': '2026-09-16T00:00:00Z', 'times': 400, 'states': 16, 'stats': {'solver': 'ros23'}},
            {'stamp': None, 'times': 1, 'states': 1, 'stats': {}},
            {'times': 1234567, 'states': 0},
            {'stamp': 'not a date', 'times': 2, 'states': 3, 'stats': {'solver': 'NDF'}},
            {'stamp': '2026-09-16T13:05:09.123+02:00', 'times': 5, 'states': 2},
            {'stamp': '2026-01-16T23:59:59', 'times': 5, 'states': 2},
            {'stamp': '2026-09-16', 'times': 5, 'states': 2},
            {'stamp': 1757980800000, 'times': 5, 'states': 2},
            None,
        ]
        got = js({'task': 'describedataset', 'metas': metas})[0]
        self.assertEqual([dataset.describe_dataset(m) for m in metas], got['lines'])


# --- data tables -------------------------------------------------------------

def file_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rows as a file reader hands them over: no block, no index."""
    return [{k: r[k] for k in ('id', 'unit', 'time', 'value', 'pdf', 'note')} for r in rows]


def changed(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The collected rows, changed every way a file can change them."""
    out = []
    for k, r in enumerate(file_rows(rows)):
        r = dict(r)
        if isinstance(r['value'], (int, float)) and not isinstance(r['value'], bool):
            r['value'] = r['value'] * 2 + 1
        if k % 3 == 1:
            r['pdf'] = None
        if k % 5 == 2:
            r.pop('pdf')
        if k % 7 == 3 and isinstance(r.get('pdf'), dict):
            r['pdf'] = {**r['pdf'], 'params': {}}
        if k % 4 == 3:
            r['unit'] = 'changed'
        out.append(r)
    return out


EXTRA_ROWS = [
    {'id': 'nowhere.at.all', 'unit': '', 'time': None, 'value': 3, 'pdf': None},
    {'id': 'Sub.newParam', 'unit': 'kg', 'time': None, 'value': 5},
    {'id': 'A.B.table', 'unit': 'm', 'time': 10, 'value': 2},
    {'id': 'A.B.table', 'unit': 'm', 'time': 0, 'value': 1, 'pdf': {'kind': 'unif', 'params': {'min': 0, 'max': 2},
                                                                    'values': None, 'trmin': None, 'trmax': None}},
    {'id': '9XY.Tank', 'unit': '', 'time': None, 'value': 2, 'pdf': None},
    {'id': '...', 'unit': '', 'time': None, 'value': 4},
    {'id': 'exp', 'unit': '', 'time': None, 'value': '7'},
    {'id': 'label.Zz', 'unit': '', 'time': None, 'value': 'LABEL7', 'pdf': None},
    {'id': 'twice', 'time': 0, 'value': 1},
    {'id': 'twice', 'time': 0, 'value': 2},
    {'id': 'untimed', 'time': 5, 'value': None},
    {'id': 'sampled', 'time': None, 'value': 1,
     'pdf': {'kind': 'pg', 'params': {}, 'values': array('d', [1.0, 2.0, 3.0]), 'trmin': None, 'trmax': None,
             'pmin': None, 'pmax': None, 'group': 'G', 'inorder': True, 'pos': 0}},
    {'id': 'a b.c-d.Ångström', 'time': None, 'value': 1},
    {'id': '', 'time': None, 'value': 1},
    {'id': 'x.y', 'time': 1, 'value': 1, 'pdf': {'kind': 'pg', 'params': {}, 'values': array('d', [5.0, 6.0])}},
    {'id': 'x.y', 'time': 2, 'value': 3, 'pdf': {}},
]


def extra_for(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rows that name what a model has in ways the collected ones do not."""
    rows = list(EXTRA_ROWS)
    first = next((b for b in model.get('parameters') or []), None)
    comp = next((b for b in model.get('compartments') or []), None)
    if first is not None:
        q = qualified_name(first)
        rows += [
            {'id': q, 'time': 3, 'value': 1},  # a parameter given times
            {'id': f' {q} ', 'time': None, 'value': q},  # a value naming a block
            {'id': f'{q}._', 'time': None, 'value': 'nothing_called_this'},
        ]
    if comp is not None:
        rows.append({'id': qualified_name(comp), 'time': None, 'value': 1})  # a compartment is not data
    for lk in model.get('lookups') or []:
        rows.append({'id': qualified_name(lk), 'time': None, 'value': 9})  # a table given no times
        break
    return rows


#: A made-up model with what the bundled examples do not have: an expression
#: for a value, Ecolego's text for a distribution, a sample, index lists with
#: bare-string, switched-off and no indices, per-index lookup tables, a spread
#: on a table's point, sub-systems, and a compartment of a parameter's name.
SINK: Dict[str, Any] = {
    'name': 'Kitchen sink',
    'simulation': {'start_time': 0, 'end_time': 100, 'time_unit': 'year', 'spacing': 'linear', 'output_points': 5},
    'index_lists': [
        {'name': 'RN', 'for_contaminants': True,
         'indices': ['Cs-137', {'name': 'Sr-90', 'enabled': False}, {'name': 'I-129'}]},
        {'name': 'Area', 'indices': [{'name': 'North'}, {'name': 'South', 'enabled': True}]},
        {'name': 'Empty', 'indices': []},
    ],
    'systems': ['Bio', 'Bio.Soil'],
    'transports': [{'name': 'Tube'}],
    'parameters': [
        {'name': 'k', 'value': '2 * j', 'unit': '1/year', 'pdf': 'logu(min=1e-3,max=1e-1)'},
        {'name': 'j', 'value': 0.5, 'system': 'Bio', 'index_lists': ['RN', 'Area'], 'comment': 'per nuclide and area',
         'entries': [{'index': {'RN': 'Cs-137'}, 'value': 1, 'pdf': 'unif(min=0.5,max=1.5)'},
                     {'index': {'RN': 'I-129', 'Area': 'South'}, 'value': '3',
                      'pdf': {'kind': 'norm', 'params': {'mean': 3, 'sd': 1}, 'values': None, 'trmin': 0,
                              'trmax': None, 'pmin': None, 'pmax': None, 'group': 'G', 'inorder': True, 'pos': 0}},
                     {'index': {'Area': 'North'}, 'value': 'x'},
                     {'index': {'RN': 'I-129'}, 'pdf': 'triang(min=1,max=3)'}]},
        {'name': 'e', 'index_lists': ['Empty'], 'value': 4},
        {'name': 'noval', 'index_lists': ['Area']},
        {'name': 'd', 'system': 'Bio.Soil', 'value': 1e21,
         'pdf': {'kind': 'pg', 'params': {}, 'values': [1, 2, 3], 'trmin': None, 'trmax': None, 'pmin': None,
                 'pmax': None, 'group': None, 'inorder': True, 'pos': 0}},
        {'name': 'w', 'value': True, 'unit': None, 'comment': None},
    ],
    'lookups': [
        {'name': 'L', 'unit': 'm', 'interpolation': 'linear',
         'points': [[0, 1], [10, 2, {'kind': 'unif', 'params': {'min': 1, 'max': 3}, 'values': None}], [20, '3']]},
        {'name': 'M', 'system': 'Bio', 'index_lists': ['RN'], 'points': [[0, 0]],
         'entries': [{'index': {'RN': 'I-129'}, 'points': [[0, 5], [50, 6]]}]},
        {'name': 'N', 'points': []},
        {'name': 'O', 'index_lists': ['Area']},
    ],
    'compartments': [{'name': 'j', 'system': 'Bio.Soil', 'initial': '0'},
                     {'name': 'Clash', 'initial': '0'}],
}


@needs_app
class DataTables(unittest.TestCase):
    """collect, resolve and apply, on every example."""

    def test_every_example_collects_the_application_s_rows(self) -> None:
        models = opened()
        variants = [(n, 'opened', models[n]) for n in NAMES] + [(n, 'as saved', example(n)) for n in NAMES]
        answers = js(*[{'task': 'collect', 'model': m, 'opened': True} for _, _, m in variants])
        for (name, how, model), got in zip(variants, answers):
            with self.subTest(example=name, model=how):
                self.assertNotIn('error', got, got.get('error'))
                mine = copy.deepcopy(model)
                rows = dtab.collect(mine)
                same_rows(self, rows, got['rows'], f'{name} ({how})')
                self.assertEqual(dumps(mine, 2), got['modelText'])

    def test_rows_applied_back_are_applied_alike(self) -> None:
        models = opened()
        cases = []
        for name in NAMES:
            model = models[name]
            rows = dtab.collect(copy.deepcopy(model))
            cases.append((name, 'as collected', file_rows(rows), None))
            cases.append((name, 'changed', changed(rows), None))
            cases.append((name, 'with extras', changed(rows) + extra_for(model), False))
            cases.append((name, 'creating', changed(rows) + extra_for(model), True))
        answers = js(*[{'task': 'apply', 'model': models[n], 'opened': True, 'rows': rows,
                        **({} if create is None else {'create': create})} for n, _, rows, create in cases])
        for (name, how, rows, create), got in zip(cases, answers):
            with self.subTest(example=name, rows=how):
                self.assertNotIn('error', got, got.get('error'))
                mine = copy.deepcopy(models[name])
                rep = dtab.apply(mine, copy.deepcopy(rows), create=create)
                self.assertEqual(canon(rep.as_dict()), canon(dec(got['report'])))
                self.assertEqual(dtab.describe(rep), got['describe'])
                self.assertEqual(dtab.describe(rep.as_dict()), got['describe'])
                self.assertEqual(dumps(mine, 2), got['modelText'])

    def test_rows_read_back_from_files_are_applied_alike(self) -> None:
        models = opened()
        cases = []
        for name in NAMES:
            rows = dtab.collect(copy.deepcopy(models[name]))
            if not rows:
                continue
            for how, back in (('xlsx', datafile.read_data_workbook(datafile.write_data_workbook(rows, name='d'))),
                              ('h5', datafile.read_data_hdf5(datafile.write_data_hdf5(rows, root=name)))):
                self.assertEqual(back['problems'], [])
                cases.append((name, how, back['rows']))
        answers = js(*[{'task': 'apply', 'model': models[n], 'opened': True, 'rows': rows} for n, _, rows in cases])
        for (name, how, rows), got in zip(cases, answers):
            with self.subTest(example=name, file=how):
                mine = copy.deepcopy(models[name])
                rep = dtab.apply(mine, rows)
                self.assertEqual(canon(rep.as_dict()), canon(dec(got['report'])))
                self.assertEqual(dumps(mine, 2), got['modelText'])

    def test_ids_resolve_alike(self) -> None:
        models = opened()
        requests, cases = [], []
        for name in NAMES:
            ids = [r['id'] for r in dtab.collect(copy.deepcopy(models[name]))]
            ids += ['nothing.of.the.sort', '', '...', ' . ', 'leachRate._', ' leachRate . I-129 ', 'leachRate._._',
                    'leachRate.I-129.extra', '9XY.Tank', 5, None]
            requests.append({'task': 'resolve', 'model': models[name], 'opened': True, 'ids': ids})
            cases.append((name, ids))
        for (name, ids), got in zip(cases, js(*requests)):
            with self.subTest(example=name):
                model = copy.deepcopy(models[name])
                mine = []
                for rid in ids:
                    hit = dtab.resolve(model, rid)
                    mine.append(None if hit is None else {**hit, 'block': qualified_name(hit['block'])})
                self.assertEqual(canon(mine), canon(dec(got['hits'])))

    def test_a_made_up_model_with_everything_collects_and_applies_alike(self) -> None:
        mine = copy.deepcopy(SINK)
        rows = dtab.collect(mine)
        more = changed(rows) + extra_for(SINK) + [
            {'id': 'Bio.j.I-129.South', 'value': 9, 'pdf': None},
            {'id': 'Bio.j._._', 'value': '0.25', 'unit': 'kg'},
            {'id': 'Bio.j.Cs-137', 'value': 2, 'pdf': {'kind': 'logu', 'params': {'min': 1, 'max': 2}}},
            {'id': 'Bio.M.I-129', 'time': 1, 'value': 7, 'unit': 'g'},
            {'id': 'Bio.M.I-129', 'time': 3, 'value': 8, 'pdf': {'kind': 'triang', 'params': {'min': 1, 'max': 9,
                                                                                            'mode': 8}}},
            {'id': 'Bio.M.Cs-137', 'time': None, 'value': 1},
            {'id': 'O.North', 'time': 0, 'value': 1},
            {'id': 'Bio.Soil.j', 'value': 1},
            {'id': 'Tube.x', 'value': 1},
            {'id': 'Clash.y', 'value': 1},
        ]
        requests = [{'task': 'collect', 'model': SINK, 'opened': True}]
        for create in (None, False, True):
            requests.append({'task': 'apply', 'model': SINK, 'opened': True, 'rows': file_rows(rows),
                             **({} if create is None else {'create': create})})
            requests.append({'task': 'apply', 'model': SINK, 'opened': True, 'rows': more,
                             **({} if create is None else {'create': create})})
        requests += [{'task': 'xlsxwrite', 'model': SINK, 'opened': True, 'name': 'sink', 'store': True},
                     {'task': 'h5write', 'model': SINK, 'opened': True, 'root': 'sink'},
                     {'task': 'sheet', 'model': SINK, 'opened': True}]
        got = js(*requests)
        same_rows(self, rows, got[0]['rows'], 'collect')
        self.assertEqual(dumps(mine, 2), got[0]['modelText'])
        k = 1
        for create in (None, False, True):
            for given in (file_rows(rows), more):
                with self.subTest(create=create, rows=len(given)):
                    theirs = got[k]
                    k += 1
                    self.assertNotIn('error', theirs, theirs.get('error'))
                    model = copy.deepcopy(SINK)
                    rep = dtab.apply(model, copy.deepcopy(given), create=create)
                    self.assertEqual(canon(rep.as_dict()), canon(dec(theirs['report'])))
                    self.assertEqual(dtab.describe(rep), theirs['describe'])
                    self.assertEqual(dumps(model, 2), theirs['modelText'])
        self.assertEqual(datafile.write_data_workbook(rows, name='sink', compress=False), unb64(got[k]['data']))
        self.assertEqual(datafile.write_data_hdf5(rows, root='sink'), unb64(got[k + 1]['data']))
        self.assertEqual(canon(datafile.to_sheet(rows)), canon(dec(got[k + 2]['grid'])))
        back = js({'task': 'xlsxread', 'data': got[k]['data']}, {'task': 'h5read', 'data': got[k + 1]['data']})
        same_rows(self, datafile.read_data_workbook(unb64(got[k]['data']))['rows'], back[0]['rows'], 'xlsx')
        same_rows(self, datafile.read_data_hdf5(unb64(got[k + 1]['data']))['rows'], back[1]['rows'], 'h5')

    def test_names_are_made_legal_alike(self) -> None:
        segments = ['9XY', 'Tank', 'a b', '', None, 'Å', '\U0001F600x', '_x', '9', 'x-y.z', 12, 'ok_1']
        got = js({'task': 'legal', 'segments': segments})[0]
        self.assertEqual([dtab.legal_name(s) for s in segments], got['names'])

    def test_creating_follows_the_model_s_sub_systems(self) -> None:
        model = {
            'name': 'systems',
            'simulation': {'start_time': 5, 'end_time': 2},
            'systems': ['Near'],
            'transports': ['Tube'],
            'compartments': [{'name': 'Clash', 'system': 'Near', 'initial': '0'}],
            'parameters': [{'name': 'k', 'value': '1', 'system': 'Near'}],
        }
        rows = [
            {'id': 'Near.fresh', 'value': 1},
            {'id': 'Near.Clash.inside', 'value': 2},
            {'id': 'Tube.inside', 'value': 3},
            {'id': 'Far.Deep.table', 'time': 1, 'value': 1},
            {'id': 'Far.Deep.table', 'time': 2, 'value': 2},
            {'id': 'Near.k', 'value': 4, 'unit': 'kg'},
            {'id': 'p', 'value': 9},
            {'id': '..', 'value': 8},
            {'id': 'Near.Clash', 'value': 7},
        ]
        got = js({'task': 'apply', 'model': model, 'opened': True, 'rows': rows, 'create': True})[0]
        mine = copy.deepcopy(model)
        rep = dtab.apply(mine, copy.deepcopy(rows), create=True)
        self.assertEqual(canon(rep.as_dict()), canon(dec(got['report'])))
        self.assertEqual(dumps(mine, 2), got['modelText'])
        self.assertEqual(dtab.describe(rep), got['describe'])


# --- data files --------------------------------------------------------------

@needs_app
class DataFiles(unittest.TestCase):
    """The model's data as workbooks and HDF5 files, both ways."""

    @classmethod
    def setUpClass(cls) -> None:
        models = opened()
        cls.rows = {n: dtab.collect(copy.deepcopy(models[n])) for n in NAMES}
        requests = []
        for n in NAMES:
            requests += [{'task': 'xlsxwrite', 'model': models[n], 'opened': True, 'name': n[:31], 'store': True},
                         {'task': 'xlsxwrite', 'model': models[n], 'opened': True, 'name': n[:31], 'store': False},
                         {'task': 'h5write', 'model': models[n], 'opened': True, 'root': n},
                         {'task': 'sheet', 'model': models[n], 'opened': True}]
        got = js(*requests)
        cls.written = {n: got[4 * k:4 * k + 4] for k, n in enumerate(NAMES)}

    def test_every_example_s_sheet_is_the_application_s(self) -> None:
        for name in NAMES:
            with self.subTest(example=name):
                self.assertEqual(canon(datafile.to_sheet(self.rows[name])), canon(dec(self.written[name][3]['grid'])))

    def test_every_example_s_workbook_is_the_application_s(self) -> None:
        for name in NAMES:
            with self.subTest(example=name):
                stored, deflated = self.written[name][0], self.written[name][1]
                self.assertNotIn('error', stored, stored.get('error'))
                self.assertEqual(datafile.write_data_workbook(self.rows[name], name=name[:31], compress=False),
                                 unb64(stored['data']))
                mine = zip_layout(datafile.write_data_workbook(self.rows[name], name=name[:31]))
                theirs = zip_layout(unb64(deflated['data']))
                self.assertEqual(mine['entries'], theirs['entries'])
                self.assertEqual(mine['central'], theirs['central'])

    def test_every_example_s_hdf5_file_is_the_application_s(self) -> None:
        for name in NAMES:
            with self.subTest(example=name):
                got = self.written[name][2]
                self.assertNotIn('error', got, got.get('error'))
                tree = datafile.to_tree(self.rows[name], root=name)
                self.assertEqual(differences(canon(dump_tree(tree)), canon(dec(got['tree']))), [])
                self.assertEqual(datafile.write_data_hdf5(self.rows[name], root=name), unb64(got['data']))

    def test_each_reads_the_other_s_files(self) -> None:
        requests, cases = [], []
        for name in NAMES:
            theirs_x = unb64(self.written[name][1]['data'])
            theirs_h = unb64(self.written[name][2]['data'])
            mine_x = datafile.write_data_workbook(self.rows[name], name=name[:31])
            mine_h = datafile.write_data_hdf5(self.rows[name], root=name)
            for kind, theirs, mine in (('xlsx', theirs_x, mine_x), ('h5', theirs_h, mine_h)):
                requests += [{'task': f'{kind}read', 'data': b64(theirs)}, {'task': f'{kind}read', 'data': b64(mine)}]
                cases.append((name, kind, theirs, mine))
        answers = js(*requests)
        for k, (name, kind, theirs, mine) in enumerate(cases):
            with self.subTest(example=name, file=kind):
                js_theirs, js_mine = answers[2 * k], answers[2 * k + 1]
                read = datafile.read_data_workbook if kind == 'xlsx' else datafile.read_data_hdf5
                here_theirs, here_mine = read(theirs), read(mine)
                same_rows(self, here_theirs['rows'], js_theirs['rows'], 'Python reading the application')
                same_rows(self, here_mine['rows'], js_mine['rows'], 'the application reading Python')
                same_rows(self, here_mine['rows'], js_theirs['rows'], 'each reading its own')
                self.assertEqual(here_theirs['problems'], js_theirs['problems'])

    def test_samples_and_hand_written_hdf5_files_read_alike(self) -> None:
        files = hand_written_hdf5()
        answers = js(*[{'task': 'h5read', 'data': b64(data)} for data in files.values()])
        for (name, data), got in zip(files.items(), answers):
            with self.subTest(file=name):
                try:
                    mine = datafile.read_data_hdf5(data)
                except TypeError as e:
                    self.assertEqual(str(e), got.get('error'))
                    continue
                self.assertNotIn('error', got, got.get('error'))
                same_rows(self, mine['rows'], got['rows'], name)
                self.assertEqual(mine['problems'], got['problems'])

    def test_hand_made_sheets_read_alike(self) -> None:
        grids = hand_made_grids()
        answers = js(*[{'task': 'fromsheet', 'grid': g, 'sheet': s} for g, s in grids])
        for (grid, sheet), got in zip(grids, answers):
            with self.subTest(grid=grid[:1], sheet=sheet):
                try:
                    mine = datafile.from_sheet(grid, sheet=sheet)
                except TypeError as e:
                    self.assertEqual(str(e), got.get('error'))
                    continue
                self.assertNotIn('error', got, got.get('error'))
                same_rows(self, mine['rows'], got['rows'], 'fromSheet')
                self.assertEqual(mine['problems'], got['problems'])

    def test_made_up_rows_write_alike(self) -> None:
        rows = [
            {'id': 'k', 'unit': '1/year', 'time': None, 'value': 0.5, 'pdf': None, 'note': 'a note'},
            {'id': 'table', 'unit': 'm3/year', 'time': 10, 'value': 2, 'pdf': None},
            {'id': 'table', 'unit': 'm3/year', 'time': 0, 'value': 1,
             'pdf': {'kind': 'triang', 'params': {'min': 0.5, 'max': 3, 'mode': 1}, 'group': 'G2',
                     'trmin': 0.6, 'trmax': None, 'pmin': 0.05, 'pmax': None}},
            {'id': 'table', 'time': -1e-300, 'value': None},
            {'id': 'label.Zz', 'unit': '', 'time': None, 'value': 'LABEL7', 'pdf': None},
            {'id': 'a/b.c', 'unit': None, 'value': True, 'note': ''},
            {'id': 'n', 'value': math.nan, 'pdf': {'kind': 'norm', 'params': {'mean': 5, 'sd': 1}, 'trmin': 0,
                                                   'trmax': 9}},
            {'id': 'g', 'value': 1e21, 'pdf': {'kind': 'Logn4', 'params': {'gm': 2, 'gsd': 3}, 'trmin': None,
                                               'trmax': None, 'pmin': 0.01, 'pmax': 0.99, 'group': 'G1'}},
            {'id': 'u', 'value': -0.0, 'pdf': {'kind': 'unif', 'params': {'min': 1, 'max': 2}, 'trmin': 1,
                                               'trmax': 1.5}},
            {'id': 'l', 'value': 2, 'pdf': {'kind': 'logn', 'params': {'mean': 1, 'sd': 2}}},
            {'id': 'pg', 'value': 2, 'pdf': {'kind': 'pg', 'values': [1, 2]}},
            {'id': 'dt', 'value': 0.35, 'pdf': {'kind': 'dtriang', 'params': {'min': 0.2, 'max': 0.9, 'mode': None}}},
            {'id': 'Ångström µ', 'value': 3, 'unit': 'µg'},
        ]
        got = js({'task': 'xlsxwrite', 'rows': rows, 'name': 'made up', 'store': True},
                 {'task': 'h5write', 'rows': rows, 'root': 'm/odel'},
                 {'task': 'sheet', 'rows': rows},
                 {'task': 'h5write', 'rows': rows})
        self.assertEqual(datafile.write_data_workbook(rows, name='made up', compress=False), unb64(got[0]['data']))
        self.assertEqual(datafile.write_data_hdf5(rows, root='m/odel'), unb64(got[1]['data']))
        self.assertEqual(canon(datafile.to_sheet(rows)), canon(dec(got[2]['grid'])))
        self.assertEqual(datafile.write_data_hdf5(rows), unb64(got[3]['data']))

    def test_the_distribution_helpers_agree(self) -> None:
        columns = [
            {'Type': 'unif', 'Min': 1, 'Max': 3}, {'Type': 'NORM', 'Mean': 5, 'Std': 1, 'Min': 0, 'Max': 9},
            {'Type': ' logn ', 'GM': 2, 'GSD': 3, 'Pmin': 0.05, 'Pmax': '0.95', 'Group': ' G1 '},
            {'Type': 'triang', 'Min': 3, 'Max': 40, 'Value': 10}, {'Type': 'wobble'}, {'Type': ''},
            {'Type': 'logt', 'Min': '7e-12', 'Max': ' ', 'Mean': 'x'}, {'Type': 'dtriang', 'Min': 0, 'Max': 0.02},
            {'Type': 'Constructor'}, {'Type': '__proto__'}, {'Type': 'toString'}, {'Type': 5},
        ]
        specs = [
            None, {'kind': 'unif', 'params': {'min': 1, 'max': 2}, 'trmin': 1, 'trmax': 2},
            {'kind': 'Logn4', 'params': {'gm': 2, 'gsd': None}, 'group': 'G', 'pmin': 0.1},
            {'kind': 'norm', 'params': {'mean': 0, 'sd': 1}, 'trmin': -1, 'trmax': 1, 'group': ''},
            {'kind': 'logn', 'params': {'mean': 1, 'sd': 1}}, {'kind': 'pg', 'values': [1, 2], 'params': {}},
            {'kind': 'toString'}, {'kind': 'logdt', 'params': {'min': 0.7, 'max': 20, 'mode': 3}},
            {'kind': 'pg', 'values': []}, {'kind': 'triang', 'params': {'min': 1, 'max': 2}},
        ]
        jsons = [
            '{"type": "dtriang", "a": 0.2, "b": 0.9, "m": 0.35, "trmin": 0.2, "trmax": 0.9}',
            '{"type": "logdt", "a": 1.5, "b": 30, "m": 4, "trmin": 1.5, "trmax": 30, "group": "G1"}',
            ' unif(min=1,max=2) ', '[{"type":"unif","a":1,"b":2}]', '', '{broken', '{"type": "Wobble"}',
            '{"type": "norm", "mean": 1, "std": 2, "sd": 3, "trmin": "0"}', '{"type": "unif", "min": 1, "max": 2}',
            5, [1, 2], {'type': 'unif', 'a': 1, 'b': 2}, '{"type": "constructor"}', 'NaN',
        ]
        lists = ['[{"type":"unif","a":1,"b":2}, null, "logu(min=1,max=10)"]', '{"type":"unif"}', '[1, 2]',
                 ['{"type":"unif","a":1,"b":2}'], None, ' [ ] ', '[broken']
        got = js({'task': 'pdfs', 'columns': columns, 'specs': specs, 'jsons': jsons, 'lists': lists})[0]

        def safe(fn: Any) -> Any:
            try:
                return canon(fn())
            except TypeError as e:
                return {'error': str(e), 'name': 'TypeError'}

        self.assertEqual([safe(lambda c=c: datafile.pdf_from_columns(lambda name, c=c: c.get(name))) for c in columns],
                         canon(dec(got['fromColumns'])))
        self.assertEqual([safe(lambda s=s: datafile.columns_from_pdf(s)) for s in specs], canon(dec(got['toColumns'])))
        self.assertEqual([safe(lambda s=s: datafile.pdf_to_json(s)) for s in specs], canon(dec(got['toJSON'])))
        self.assertEqual([safe(lambda s=s: datafile.usable(s)) for s in specs], canon(dec(got['usable'])))
        self.assertEqual([safe(lambda s=s: datafile.pdf_from_json(s)) for s in jsons], canon(dec(got['fromJSON'])))
        self.assertEqual([safe(lambda s=s: datafile.pdf_list_from_json(s)) for s in lists],
                         canon(dec(got['fromList'])))


def hand_written_hdf5() -> Dict[str, bytes]:
    """Data files as other tools write them: samples, clocks, index strings."""
    h = hdf5
    raw = h.group({'source': 'made up'})
    h.put(raw, ['time'], h.dataset([0.0, 10.0, 20.0], h.F64, {'unit': 'year'}))
    h.put(raw, ['IndexLists', 'Radionuclides'], h.dataset(['Cs-137'], h.STR))
    h.put(raw, ['lonely'], h.dataset([1.0], h.F64))
    h.put(raw, ['m', 'inventory'], h.dataset([100.0, 1.0, 2.0, 3.0, 4.0], h.F64,
                                               {'pdf': '{"type": "raw", "include_deterministic": true}',
                                                'unit': 'Bq', 'reference': ' R1 '}))
    h.put(raw, ['m', 'column'], h.dataset([3.0, 1.0, math.nan, 2.0], h.F64, {'probabilistic': 'TRUE'}))
    h.put(raw, ['m', 'release'], h.dataset([float(k) for k in range(12)], h.F64, {'probabilistic': True}, [3, 4]))
    h.put(raw, ['m', 'rel2'], h.dataset([float(k) for k in range(8)], h.F64,
                                          {'probabilistic': 1.0, 'index': '5 6'}, [2, 4]))
    h.put(raw, ['m', 'rel3'], h.dataset([float(k) for k in range(8)], h.F64, {'pdf': '{"type":"RAW"}'}, [4, 2]))
    h.put(raw, ['m', 'flat'], h.dataset([float(k) for k in range(8)], h.F64, {'probabilistic': 'FALSE'}, [2, 4]))
    h.put(raw, ['m', 'tab'], h.dataset([1.0, 2.0, 3.0], h.F64, {'lookup_table': 'true', 'index': '0,5,10,'}))
    h.put(raw, ['m', 'tab2'], h.dataset([1.0, 2.0], h.F64, {
        'lookup_table': 'True', 'index': [0.0, 500.0], 'unit': 'unitless',
        'pdf': '[{"type": "triang", "a": 3, "b": 40, "m": 10, "group": "G2"}, null]'}))
    h.put(raw, ['m', 'tab3'], h.dataset([1.0, 2.0], h.F64, {'lookup_table': 'false', 'index': '0, 1'}))
    h.put(raw, ['m', 'p'], h.dataset([2.5], h.F64, {'pdf': ' unif(min=1,max=4) '}))
    h.put(raw, ['m', 'q'], h.dataset([2.5], h.F64, {'pdf': '{"type":"logn","gm":2,"gsd":3,"trmin":0.1}'}))
    h.put(raw, ['m', 's'], h.dataset(['LABEL7'], h.STR, {'unit': ['a', 'b']}))
    h.put(raw, ['m', 'empty'], h.dataset([], h.F64))
    h.put(raw, ['m', 'sub', 'deep', 'x'], h.dataset([1.0, 2.0], h.F32, {'unit': 3.0}))
    h.put(raw, ['m', 'col2'], h.dataset([7.0], h.F64, {'probabilistic': 'yes', 'lookup_table': 'no'}))
    clockless = h.group({})
    h.put(clockless, ['Time'], h.dataset([1.0, 2.0], h.F64))
    h.put(clockless, ['m', 'curve'], h.dataset([1.0, 2.0, 3.0, 4.0], h.F64, {'probabilistic': 'TRUE'}, [2, 2]))
    words = h.group({})
    h.put(words, ['m', 'names'], h.dataset(['a', 'b', 'c'], h.STR,
                                             {'pdf': '{"type": "raw", "include_deterministic": true}'}))
    words_middle = h.group({})
    h.put(words_middle, ['m', 'names'], h.dataset(['a', 'b'], h.STR, {'probabilistic': 'TRUE'}))
    ctor = h.group({})
    h.put(ctor, ['m', 'x'], h.dataset([1.0], h.F64, {'pdf': '{"type": "constructor"}'}))
    return {'samples': h.write_hdf5(raw), 'clockless': h.write_hdf5(clockless), 'words': h.write_hdf5(words),
            'words, middle': h.write_hdf5(words_middle), 'constructor': h.write_hdf5(ctor)}


def hand_made_grids() -> List[Any]:
    """Sheets as people make them."""
    return [
        ([['ID', 'Value', 'Unit'], ['k', 0.5, 'm'], [], None, ['  ', 2], ['j', '  3 ', None]], 'Sheet1'),
        ([['Subsystem', 'Name', 'Species', 'Value', 'Time'], ['Bio', 'Kd', 'Cs', 1.5, ' '], ['', 'Kd', '', '2', 4]], None),
        ([['Name', 'ID'], ['x', 'y']], ''),
        ([['Value'], [1]], 'Named'),
        ([['Value'], [1]], None),
        ([], 7),
        ([[' ID ', 'ID', 'Type', 'Min', 'Max', 'Value', 'Group', 'Reference'],
          ['a', 'b', 'triang', 1, 3, 2, ' G ', 'ref'], ['c', None, 'wobble', 1, 2, 3], ['d', None, 'UNIF', '1', '2']],
         'S'),
        ([['ID', 'Type'], ['x', 'constructor']], 'S'),
        ([['ID', 'Value', 'Time'], ['t', True, 'x'], ['u', 'LABEL7', 1e300], ['v', 'NaN', '-0']], 'S'),
    ]


#: A made-up model with a sampled rate, a value that cannot change over the run
#: (``twoK``) and one that can (``ramp``).
SAMPLED: Dict[str, Any] = {
    'name': 'Sampled boxes',
    'simulation': {'start_time': 0, 'end_time': 50, 'time_unit': 'year', 'spacing': 'linear', 'output_points': 6,
                   'solver': 'ndf', 'rtol': 1e-8, 'abstol': 1e-12},
    'compartments': [{'name': 'A', 'initial': '100', 'unit': 'Bq'}, {'name': 'B', 'initial': '0', 'unit': 'Bq'}],
    'parameters': [{'name': 'k', 'value': 0.05, 'unit': '1/year',
                    'pdf': {'kind': 'unif', 'params': {'min': 0.01, 'max': 0.1}, 'values': None, 'trmin': None,
                            'trmax': None, 'pmin': None, 'pmax': None, 'group': None, 'inorder': True, 'pos': 0}}],
    'expressions': [{'name': 'twoK', 'equation': '2 * k', 'unit': '1/year'},
                    {'name': 'ramp', 'equation': 'time * k', 'unit': ''}],
    'transfers': [{'name': 'flow', 'from': 'A', 'to': 'B', 'rate': 'k'}],
}


def _same_values(test: unittest.TestCase, mine: List[Dict[str, Any]], theirs: List[Dict[str, Any]], rtol: float,
                 key: str) -> None:
    for a, b in zip(mine, theirs):
        if a['kind'] != 'dataset':
            continue
        test.assertEqual(a['dims'], b['dims'], a['path'])
        if a['dt'] == 'STR':
            test.assertEqual(a['data'], b['data'], a['path'])
            continue
        w = worst_relative(a['data'], b['data'])
        note_worst(key, w)
        test.assertLess(w, rtol, a['path'])


@needs_app
class ScenarioAndSampleFiles(unittest.TestCase):
    """Several scenarios in one file, and a probabilistic run's file."""

    def test_scenarios_side_by_side_are_the_page_s_file(self) -> None:
        got = js({'task': 'scenarios', 'model': example('scenarios'), 'now': NOW})[0]
        self.assertNotIn('error', got, got.get('error'))
        runs = run_scenarios(got['project'])
        self.assertEqual(list(runs), got['names'])
        tree = resultfile.scenarios_tree(runs, active=got['active'], project=got['project'],
                                         index_lists=got['indexLists'], now=dt.datetime(*NOW))
        mine, theirs = dump_tree(tree), dec(got['tree'])
        diff = differences(tree_shape(mine), tree_shape(theirs))
        self.assertEqual(diff, [], '; '.join(diff[:6]))
        _same_values(self, mine, theirs, 1e-7, 'scenarios side by side')
        # The scenario list is written by its names, and is the extra index.
        lists = {e['path']: e['data'] for e in mine if e['path'].startswith('/IndexLists/')}
        self.assertEqual(lists['/IndexLists/Climate'], got['names'])
        # One run alone is that run's file.
        alone = resultfile.scenarios_tree({got['active']: runs[got['active']]}, project=got['project'],
                                          index_lists=got['indexLists'], now=dt.datetime(*NOW))
        self.assertEqual(hdf5.write_hdf5(alone),
                         resultfile.write_results_hdf5(runs[got['active']], project=got['project'],
                                                       index_lists=got['indexLists'], now=dt.datetime(*NOW)))

    def test_a_curve_is_read_onto_another_run_s_times_as_the_page_reads_it(self) -> None:
        cases = [([0, 1, 2, 4], [0, 0.5, 2, 3, 4, 5, -1], [1, 3, 5, 9]), ([0, 1], [0, 1], [7, 8]),
                 ([0, 2, 2, 3], [1, 2, 2.5, 3], [1, 2, 3, 4]), ([5], [4, 5, 6], [2]), ([0, 1, 2], [0.25], [0, 4, 8])]
        got = js(*[{'task': 'onto', 'from': array('d', f), 'to': array('d', t), 'values': array('d', v)}
                   for f, t, v in cases])
        for (f, t, v), theirs in zip(cases, got):
            with self.subTest(frm=f, to=t):
                mine = resultfile._onto_axis(f, t)(v)
                self.assertEqual(canon(list(np.asarray(mine, dtype=float))),
                                 canon(list(np.asarray(dec(theirs['values']), dtype=float))))

    def test_a_probabilistic_run_is_the_page_s_realisations_file(self) -> None:
        wants = ['all', 'mean', 3, 99, 0]
        answers = js(*[{'task': 'realisations', 'model': SAMPLED, 'iterations': 5, 'seed': 4, 'want': w, 'now': NOW}
                       for w in wants])
        prob = run_probabilistic(Project(answers[0]['project']), iterations=5, seed=4)
        for want, got in zip(wants, answers):
            with self.subTest(want=want):
                self.assertNotIn('error', got, got.get('error'))
                self.assertEqual([o['label'] for o in prob.outputs], [o['label'] for o in dec(got['outputs'])])
                tree = resultfile.probabilistic_tree(prob, want, project=got['project'], index_lists=got['indexLists'],
                                                     now=dt.datetime(*NOW), inputs=False)
                mine, theirs = dump_tree(tree), dec(got['tree'])
                diff = differences(tree_shape(mine), tree_shape(theirs))
                self.assertEqual(diff, [], '; '.join(diff[:6]))
                _same_values(self, mine, theirs, 1e-6, 'realisations file, Python run')

    def test_the_same_realisations_make_the_same_file(self) -> None:
        prob = run_probabilistic(Project(SAMPLED), iterations=4, seed=2)
        project = {'name': 'Sampled boxes', 'simulation': SAMPLED['simulation']}
        t = array('d', prob.t)
        outputs = [dict(o) for o in prob.outputs]
        n = prob.values[0].shape[0]
        times = len(t)
        requests, cases = [], []
        for want in ('all', 'mean', 2):
            if want == 'all':
                mats = {}
                for k, o in enumerate(outputs):
                    m = np.asarray(prob.values[k], dtype=np.float32)
                    mats[str(k)] = array('f', (m[:, 0] if o.get('timeDependent') is False else m.T.ravel()).tolist())
                extra = {'realisations': {'iterations': n, 'matrices': mats}}
                columns = [array('d', [math.nan] * times) for _ in outputs]
            elif want == 'mean':
                extra = {'sample': {'iterations': n, 'of': 'mean'}}
                columns = [array('d', resultfile._finite_mean(prob.values[k]).tolist()) for k in range(len(outputs))]
            else:
                extra = {'sample': {'iterations': n, 'of': want}}
                columns = [array('d', np.asarray(prob.values[k][want - 1], dtype=float).tolist())
                           for k in range(len(outputs))]
            requests.append({'task': 'tree', 't': t, 'outputs': outputs, 'columns': columns,
                             'which': list(range(len(outputs))), 'project': project, 'indexLists': [], 'now': NOW,
                             **extra})
            cases.append(want)
        for want, got in zip(cases, js(*requests)):
            with self.subTest(want=want):
                self.assertNotIn('error', got, got.get('error'))
                mine = resultfile.write_probabilistic_hdf5(prob, want=want, project=project, index_lists=[],
                                                           now=dt.datetime(*NOW), inputs=False)
                self.assertEqual(mine, unb64(got['data']))
                self.assertEqual(prob.to_hdf5(want=want, project=project, index_lists=[], now=dt.datetime(*NOW),
                                              inputs=False), mine)
        # The varied parameter goes out too, one value per realisation.
        from kompartment.io.hdf5read import read_hdf5
        data = prob.to_hdf5(project=project, now=dt.datetime(*NOW))
        k = next(d for d in read_hdf5(data)['datasets'] if d['path'] == '/k')
        self.assertEqual(k['dims'], [n])
        self.assertEqual(list(k['values']), list(np.asarray(prob.samples[0], dtype=np.float32).astype(float)))


@needs_app
class ArchiveAllowance(unittest.TestCase):
    """What the reader will not inflate, the writer does not deflate."""

    def test_an_archive_past_the_reader_s_allowance_is_stored_and_opens(self) -> None:
        entries = [(f'results/p{k}.f64', bytes([k]) * 40000) for k in (1, 2, 3)]
        mine = _zip(entries, inflate_limit=100000)
        self.assertEqual([e['method'] for e in zip_layout(mine)['entries']], [8, 8, 0])
        back = dataset.unzip(mine, inflate_limit=100000)
        self.assertEqual(list(back.items()), entries)
        with self.assertRaises(dataset.DatasetError):
            dataset.unzip(_zip(entries), inflate_limit=100000)
        got = js({'task': 'zip', 'entries': [[n, b64(b)] for n, b in entries], 'inflateLimit': 100000},
                 {'task': 'zip', 'entries': [[n, b64(b)] for n, b in entries], 'inflateLimit': 100000, 'store': True})
        theirs = zip_layout(unb64(got[0]['data']))
        ours = zip_layout(mine)
        self.assertEqual(ours['entries'], theirs['entries'])
        self.assertEqual(ours['central'], theirs['central'])
        self.assertEqual(_zip(entries, compress=False, inflate_limit=100000), unb64(got[1]['data']))


# --- the run log -------------------------------------------------------------

AT = '2026-09-16T12:00:00.000Z'


def _at() -> dt.datetime:
    return dt.datetime(2026, 9, 16, 12, 0, 0, tzinfo=dt.timezone.utc)


@needs_app
class RunLogs(unittest.TestCase):
    """The run log, from the same payload and from a run here."""

    @classmethod
    def setUpClass(cls) -> None:
        models = opened()
        cls.runs = dict(zip(NAMES, js(*[{'task': 'run', 'model': models[n], 'opened': True} for n in NAMES])))

    def test_the_same_payload_makes_the_same_log(self) -> None:
        models = opened()
        answers = js(*[{'task': 'runlog', 'project': models[n], 'payload': self.runs[n]['payload'], 'build': 'test',
                        'at': AT} for n in NAMES])
        for name, got in zip(NAMES, answers):
            with self.subTest(example=name):
                self.assertNotIn('error', got, got.get('error'))
                lines = runlog.run_log_lines(models[name], dec(self.runs[name]['payload']), build='test', at=_at())
                self.assertEqual(lines, got['lines'])
                self.assertEqual(runlog.run_log_text(lines + [None]), got['text'])

    def test_replays_scenarios_and_probabilistic_runs_are_logged_alike(self) -> None:
        project = {'name': 'p', 'description': ' spread \n\t over   lines ' + 'x' * 300,
                   'simulation': {'time_unit': 'year', 'start_time': 0, 'end_time': 1e6, 'spacing': 'series',
                                  'solver': 'ros23', 'rtol': 1e-6, 'abstol': 1e-12, 'non_negative': False,
                                  'mass_balance': True, 'auto_abstol': 1, 'decay_unit': 'mol',
                                  'decay_ceiling': '1e9'}}
        payload = {
            'stats': {'nsteps': 1000, 'nfailed': 3, 'nfevals': 3000, 'nbelowtol': 2, 'events': 1, 'jumps': 0,
                      'split': {'used': True, 'jobs': [{'materials': ['Cs-137', None], 'states': 4, 'nsteps': 99,
                                                        'buildMs': 1.25, 'solveMs': 10.5},
                                                       {'materials': [], 'states': 2, 'buildMs': 0.05}],
                                'workers': 2, 'mode': 'auto', 'why': 'independent', 'gain': 1.75}},
            'timing': {'buildMs': 0.05, 'solveMs': 2.5, 'reused': False},
            'jacobian': {'available': True, 'sparse': True, 'colours': 5, 'constant': True},
            'heldAtZero': [{'label': f'C{k}', 'steps': k, 'fraction': k / 1000} for k in range(25)],
            'stateCount': 12, 'outputs': ['a', 'b'], 't': [0, 1, 2],
            'massBalance': {'closed': False, 'worst': 0.0123, 'at': 12345.678, 'worstFamily': 'Cs-137',
                            'families': [{'name': 'Cs-137', 'idle': False, 'relative': 0.0123, 'at': 0.5,
                                          'final': {'start': 1e9, 'in': 0.25, 'out': 1e-4, 'decay': 123.456,
                                                    'ingrowth': 0, 'explicit': -2.5, 'between': math.nan,
                                                    'inventory': 999999.5, 'residual': -1e-12}},
                                         {'name': 'Sr-90', 'idle': True, 'unresolved': True, 'scale': 2.5e-13,
                                          'floor': 1e-9},
                                         {'name': 'not by nuclide', 'idle': True}]},
        }
        replays = [None, {'index': 733, 'iterations': 1000, 'seed': 7,
                          'values': [{'name': 'Kd[I-129]', 'value': 0.02, 'held': False},
                                     {'name': 'x', 'value': math.inf, 'held': True}]},
                   {'tornado': True, 'index': 4, 'iterations': 30}]
        probs = [None, {'iterations': 60, 'plan': [], 'stats': {
            'seed': 1, 'latin': True, 'sampled': 15, 'correlated': 6, 'correlationAdjusted': 0.00125,
            'correlationProblems': ['x is not a sampled input'], 'workers': 9, 'ms': 300, 'failed': 1,
            'trouble': ['realisation 12: stiff']}, 'screen': {'counts': [17, 43], 'kept': 43}},
            {'iterations': 30, 'plan': [1, 2], 'stats': {'tornado': {'low': 0.05, 'high': 0.945}, 'ms': 1250}}]
        scenarios = [None, [{'name': 'A', 'error': 'broke'}, {'name': 'B', 'running': True},
                            {'name': 'C', 'r': {'stats': {'nsteps': 5, 'split': {'used': True, 'jobs': [1, 2],
                                                                                 'workers': 3}},
                                                'timing': {'buildMs': 2.25, 'solveMs': 0.5}}},
                            {'name': 'D', 'r': {'stats': {}, 'timing': {'reused': True}}}, {'name': 'E'}]]
        variants = []
        for k, replayed in enumerate(replays):
            variants.append({'project': project, 'payload': payload, 'replayed': replayed, 'prob': probs[k],
                             'active': 'Base', 'scenarios': scenarios[k % 2], 'build': '' if k else 'b1'})
        variants.append({'project': {'name': None}, 'payload': {'stats': {'integrated': False, 'split': {'mode': 'off', 'why': 'no'}},
                                                               'timing': {'reused': True}}, 'build': 'x'})
        variants.append({'project': {}, 'payload': {}, 'build': None})
        answers = js(*[{'task': 'runlog', 'at': AT, **v} for v in variants])
        for v, got in zip(variants, answers):
            with self.subTest(variant=v.get('build')):
                self.assertNotIn('error', got, got.get('error'))
                lines = runlog.run_log_lines(v['project'], v['payload'], replayed=v.get('replayed'),
                                             build=v.get('build') or '', at=_at())
                self.assertEqual(lines, got['lines'])
                self.assertEqual(runlog.scenario_log_lines(v.get('active'), v.get('scenarios')), got['scenario'])
                self.assertEqual(runlog.probabilistic_log_lines(v.get('prob')), got['prob'])

    def test_a_python_run_logs_what_the_application_logs(self) -> None:
        models = opened()
        answers = js(*[{'task': 'runlog', 'project': models[n], 'payload': self.runs[n]['payload'], 'build': 'test',
                        'at': AT} for n in NAMES])
        for name, got in zip(NAMES, answers):
            with self.subTest(example=name):
                res = run(Project(models[name]))
                lines = runlog.run_log_lines(models[name], runlog.payload_of(res), build='test', at=_at())
                theirs = got['lines']
                # Everything down to the run itself, and the counts that are the model's.
                upto = theirs.index('run')
                self.assertEqual(lines[:upto + 1], theirs[:upto + 1])
                for prefix in ('  states:', '  series:', '  jumps:', '  events:', '  nothing integrated'):
                    self.assertEqual([x for x in lines if x.startswith(prefix)],
                                     [x for x in theirs if x.startswith(prefix)], prefix)
                if name != 'farfield':
                    self.assertEqual([x for x in lines if x.startswith('  output points:')],
                                     [x for x in theirs if x.startswith('  output points:')])
                self.assertEqual(runlog.run_log(res, project=models[name], build='test', at=_at()),
                                 runlog.run_log_text(lines))

    def test_the_mass_balance_audit_reads_alike(self) -> None:
        model = {
            'name': 'audit', 'simulation': {'time_unit': 'year', 'start_time': 0, 'end_time': 200, 'output_points': 40,
                                            'spacing': 'linear', 'solver': 'ndf', 'rtol': 1e-6, 'abstol': 1e-9,
                                            'mass_balance': True},
            'nuclides': ['Sr-90', 'Y-90', 'Cs-137'],
            'index_lists': [{'name': 'RN', 'for_contaminants': True,
                             'indices': [{'name': 'Sr-90'}, {'name': 'Y-90'}, {'name': 'Cs-137'}]}],
            'compartments': [
                {'name': 'Soil', 'index_lists': ['RN'], 'initial': '0',
                 'entries': [{'index': {'RN': 'Sr-90'}, 'initial': '1000'}, {'index': {'RN': 'Cs-137'}, 'initial': '500'}]},
                {'name': 'Water', 'index_lists': ['RN'], 'initial': '0'},
                {'name': 'Tank', 'index_lists': [], 'initial': '10'},
            ],
            'parameters': [{'name': 'k', 'value': 0.05}],
            'transfers': [{'name': 'Leach', 'from': 'Soil', 'to': 'Water', 'rate': 'k'},
                          {'name': 'Out', 'from': 'Water', 'to': None, 'rate': 'k / 2'}],
        }
        got = js({'task': 'run', 'model': model})[0]
        self.assertNotIn('error', got, got.get('error'))
        payload = dec(got['payload'])
        audit = payload['massBalance']
        self.assertIsNotNone(audit)
        theirs = js({'task': 'audit', 'audit': audit, 'timeUnit': 'year'}, {'task': 'audit', 'audit': audit})
        self.assertEqual(runlog.describe_audit(audit, 'year'), theirs[0]['lines'])
        self.assertEqual(runlog.describe_audit(audit), theirs[1]['lines'])
        opened_model = js({'task': 'normalise', 'model': model})[0]['model']
        res = run(Project(opened_model))
        mine = runlog.describe_audit(res.mass_balance(), 'year')
        self.assertEqual(len(mine), len(theirs[0]['lines']))
        self.assertEqual([x.split(':')[0] for x in mine], [x.split(':')[0] for x in theirs[0]['lines']])
        log = runlog.run_log(res, build='test', at=_at())
        self.assertIn('  mass-balance audit: on', log)


def tearDownModule() -> None:
    if WORST and os.environ.get('KOMPARTMENT_TEST_REPORT'):
        for key, value in sorted(WORST.items()):
            print(f'{key}: worst relative difference {value:.3g}')


if __name__ == '__main__':
    unittest.main()
