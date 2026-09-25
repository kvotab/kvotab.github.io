"""The Ecolego exporter against the application's: the same model, the same file.

Every model here is exported by the application's own exporter
(``src/io/ecoexport.js``, run by ``tests/node/eco_export.mjs``) and by
:mod:`kompartment.io.ecoexport`, and the two are compared byte for byte -- the
archive, its ``model.xml`` and the report. Then the export is read back, by
this package's importer and by the application's, and what comes back is
compared with the model that went out: as the application's own canonical form
of a model (``canonicalModel`` in ``test/eco-export-fixture.js``, built from
``Project`` and ``valueAt``), leaving out only what the report says was left
out or written in another form.

The models are the repository's bundled examples and the made-up ones in
``test/eco-export-fixture.js``; nothing here comes from a real project.
"""

from __future__ import annotations

import base64
import datetime as dt
import io
import json
import math
import random
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from helpers import EXAMPLES, HERE, NODE, SRC, differences, needs_app

import kompartment as kp
from kompartment.importers.eco import import_eco_file
from kompartment.io.ecoexport import ExportError, export_eco, export_model_xml, guid_for, java_double, seconds_for
from kompartment.jsonio import dumps

#: The solver the importer reads back from the name an export writes.
SOLVER_BACK = {
    'radau5': 'ndf', 'qndf': 'ndf', 'fbdf': 'ndf', 'trbdf2': 'ros23', 'rodas5p': 'ros23', 'kencarp4': 'ndf',
    'scipy_bdf': 'ndf', 'scipy_radau': 'ndf', 'scipy_lsoda': 'ndf',
}


def js(requests: List[Dict[str, Any]]) -> List[Any]:
    """Asks the application's exporter and importer (see tests/node/eco_export.mjs)."""
    assert NODE is not None
    proc = subprocess.run([NODE, str(HERE / 'node' / 'eco_export.mjs'), str(SRC)],
                          input=json.dumps({'task': 'batch', 'requests': requests}),
                          capture_output=True, text=True, timeout=900, encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return json.loads(proc.stdout)


@lru_cache(maxsize=1)
def models() -> Dict[str, Dict[str, Any]]:
    """Every bundled example, and the made-up models of test/eco-export-fixture.js."""
    out = {path.name: json.loads(path.read_text('utf-8')) for path in sorted(EXAMPLES.glob('*.json'))}
    out.update(js([{'task': 'fixtures'}])[0]['models'])
    return out


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=False)


@needs_app
class TheSameBytes(unittest.TestCase):
    """The archive, its model.xml and the report, as the application writes them."""

    maxDiff = None

    def test_every_model_exports_to_the_application_s_bytes(self):
        names = list(models())
        answers = js([{'task': 'export', 'model': models()[n]} for n in names])
        for name, answer in zip(names, answers):
            with self.subTest(model=name):
                self.assertNotIn('error', answer)
                out = export_eco(models()[name])
                self.assertEqual(out.xml, answer['xml'])
                self.assertEqual(differences(out.report.to_dict(), answer['report']), [])
                self.assertEqual(json_text(out.report.to_dict()), json_text(answer['report']))
                self.assertEqual(out.bytes, base64.b64decode(answer['base64']))

    def test_a_dated_export_is_the_application_s_too(self):
        model = models()['EVERY_KIND']
        answer = js([{'task': 'export', 'model': model, 'modified': [2024, 5, 17, 10, 30, 12]}])[0]
        out = export_eco(model, modified=dt.datetime(2024, 5, 17, 10, 30, 12))
        self.assertIn('<modification-date>', out.xml)
        self.assertEqual(out.xml, answer['xml'])
        self.assertEqual(out.bytes, base64.b64decode(answer['base64']))

    def test_a_model_exports_as_the_file_it_saves_to(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('biosphere.json', 'landscape.json', 'recorders.json'):
                with self.subTest(model=name):
                    m = kp.Model.load(EXAMPLES / name)
                    answer = js([{'task': 'export', 'model': json.loads(m.to_json())}])[0]
                    out = m.to_eco()
                    self.assertEqual(out.bytes, base64.b64decode(answer['base64']))
                    self.assertIs(m.export_report, out.report)
                    path = m.save(Path(tmp) / f'{name}.eco')
                    self.assertEqual(path.read_bytes(), out.bytes)
                    # And it is a project this package opens.
                    back = kp.Model.from_eco(path)
                    self.assertTrue(back.import_report.summary().startswith('Imported '))

    def test_numbers_are_written_as_the_application_writes_them(self):
        rng = random.Random(20260925)
        values = [0.0, 1.0, 1000.0, 0.001, 1e-4, 1e7, 9999999.0, 123.456, -2.5e-12, -792842341234.23404823434,
                  0.30000000000000004, 1.7976931348623157e308, 5e-324, 30.08, 2.552 / 60 / 60 / 24 / 365.25]
        values += [(rng.random() - 0.5) * 10 ** rng.randint(-30, 30) for _ in range(1500)]
        answer = js([{'task': 'numbers', 'values': values}])[0]
        self.assertEqual([java_double(v) for v in values], answer['java'])
        self.assertEqual([java_double(seconds_for(v)) if v > 0 else None for v in values], answer['seconds'])
        # And the ones JSON cannot carry.
        self.assertEqual([java_double(v) for v in (math.nan, math.inf, -math.inf, -0.0)],
                         ['NaN', 'Infinity', '-Infinity', '-0.0'])
        for v in values:
            self.assertEqual(float(java_double(v)), v)


@needs_app
class ReadBack(unittest.TestCase):
    """An export imported again is the model that went out, by both importers."""

    maxDiff = None

    def test_this_package_s_export_imports_back_as_the_same_model(self):
        names = list(models())
        requests = []
        exports = {}
        for name in names:
            out = export_eco(models()[name])
            back = import_eco_file(out.bytes)
            exclude = [s['name'] for s in out.report.skipped] + [s['name'] for s in out.report.rewritten]
            exports[name] = out
            requests.append({'task': 'canonical', 'model': models()[name], 'exclude': exclude})
            requests.append({'task': 'canonical', 'model': json.loads(dumps(back.project)), 'exclude': exclude,
                             'imported': True})
        answers = js(requests)
        for k, name in enumerate(names):
            with self.subTest(model=name):
                want = answers[2 * k]['canonical']
                got = answers[2 * k + 1]['canonical']
                solver = want['simulation']['solver']
                want['simulation']['solver'] = SOLVER_BACK.get(solver, solver)
                if name == 'PER_INDEX_DIRECTION':
                    # The file says it index by index; the importer keeps the block's own.
                    self.assertTrue(any("'Either' fires in a different direction" in w
                                        for w in exports[name].report.warnings))
                    next(b for b in want['blocks'] if b['q'] == 'Either')['grid']['Sr-90']['direction'] = 'rising'
                self.assertEqual(differences(got, want), [])

    def test_both_importers_read_an_export_alike(self):
        names = list(models())
        answers = js([{'task': 'roundtrip', 'model': models()[n]} for n in names])
        for name, answer in zip(names, answers):
            with self.subTest(model=name):
                out = export_eco(models()[name])
                self.assertEqual(out.bytes, base64.b64decode(answer['base64']))
                back = import_eco_file(out.bytes)
                self.assertEqual(differences(json.loads(dumps(back.project)), answer['project']), [])
                self.assertEqual(dumps(back.project), dumps(answer['project']))
                self.assertEqual(json_text(back.report.to_dict()), json_text(answer['imported']))

    def test_the_archive_and_its_xml_are_what_any_reader_takes(self):
        for name, model in models().items():
            with self.subTest(model=name):
                out = export_eco(model)
                root = ET.fromstring(out.xml.encode('utf-8'))
                self.assertEqual(root.tag, 'data-model')
                with zipfile.ZipFile(io.BytesIO(out.bytes)) as z:
                    self.assertIsNone(z.testzip())
                    self.assertEqual(z.namelist(), ['.version', 'model.xml', 'views.xml'])
                    self.assertTrue(all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist()))
                    self.assertEqual(z.read('model.xml').decode('utf-8'), out.xml)
                    self.assertTrue(z.read('.version').decode('utf-8').startswith('version=6.5\n'))
                # Every block has an id, a GUID of its own, and a sub-system that is declared.
                blocks = root.find('block-model')
                systems = {e.findtext('id') for e in root.find('hierarchy-model') if e.findtext('id')}
                guids = [e.findtext('guid') for e in root.iter() if e.find('guid') is not None]
                self.assertEqual(len(guids), len(set(guids)))
                for c in list(blocks):
                    self.assertTrue(c.findtext('id'))
                    if c.findtext('sub-system'):
                        self.assertIn(c.findtext('sub-system'), systems)

    def test_what_has_no_equivalent_is_left_out_and_named(self):
        out = export_eco(models()['NO_EQUIVALENT'])
        skipped = {f"{s['type']}:{s['name']}" for s in out.report.skipped}
        for key in ('far-field pathway:Path', 'waste package:Canisters', 'event:Quake', 'transfer:Discharge',
                    'transfer:Shared', 'parameter:per_transfer', 'expression:Ends', 'function:Zero',
                    'expression:Reads_that', 'distribution:k', 'distribution:Kd', 'correlation group:grouped',
                    'correlation:1 pair(s)'):
            self.assertIn(key, skipped)
        self.assertTrue(any(w.startswith('The diagram is this tool’s own and is not written (its layout)')
                            for w in out.report.warnings))
        rewritten = {s['name']: s['how'] for s in out.report.rewritten}
        self.assertIn('narrowed onto Wetland', rewritten['WetlandLoss'])
        self.assertIn('written into its rate', rewritten['Leach'])
        self.assertIn('RADAU5', rewritten['radau5'])
        self.assertFalse(out.report.ok)
        xml, report = export_model_xml(models()['NO_EQUIVALENT'])
        self.assertEqual(xml, out.xml)
        self.assertNotIn('Reads_path', xml)

    def test_something_that_is_not_a_model_is_refused(self):
        with self.assertRaises(ExportError):
            export_eco([1, 2])

    def test_what_would_come_back_under_another_name_is_said(self):
        clash = {
            'name': 'Clash', 'index_lists': [{'name': 'Region', 'indices': ['North, upper', 'South']}],
            'systems': ['max'],
            'parameters': [
                {'name': 'Region', 'index_lists': ['Region'], 'value': 1,
                 'entries': [{'index': {'Region': 'North, upper'}, 'value': 2}]},
                {'name': 'k', 'system': 'max', 'value': 2},
            ],
        }
        out = export_eco(clash)
        answer = js([{'task': 'export', 'model': clash}])[0]
        self.assertEqual(out.bytes, base64.b64decode(answer['base64']))
        self.assertEqual(json_text(out.report.to_dict()), json_text(answer['report']))
        self.assertTrue(any(w.startswith("'Region' (index list, parameter)") for w in out.report.warnings))
        self.assertTrue(any(w.startswith("'max' is a sub-system named after a function") for w in out.report.warnings))
        back = import_eco_file(out.bytes)
        self.assertIn({'from': 'Region', 'to': 'Region_1'}, back.report.renamed)

    def test_guids_are_deterministic_and_shaped_as_uuids(self):
        a = guid_for('Model', 'block:Soil')
        self.assertEqual(a, guid_for('Model', 'block:Soil'))
        self.assertNotEqual(a, guid_for('Other model', 'block:Soil'))
        self.assertRegex(a, r'^[0-9A-F]{8}-[0-9A-F]{4}-8[0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}$')


@lru_cache(maxsize=1)
def _engine() -> Any:
    """The package's solver -- or, where it needs a module this interpreter does
    not have, the reason it cannot run here."""
    try:
        kp.run({'name': 'probe', 'compartments': [{'name': 'A', 'initial': '1', 'index_lists': []}],
                'simulation': {'end_time': 1, 'output_points': 3}})
        return kp.run
    except ImportError as e:  # pragma: no cover - depends on what the interpreter has installed
        return f'the package’s engine cannot run in this interpreter: {e}'


def _without(project: Dict[str, Any], names: List[str]) -> Dict[str, Any]:
    """A model with some of its blocks taken out: what an export that left them out means."""
    gone = set(names)
    out = json.loads(json.dumps(project))
    for key, value in list(out.items()):
        if not isinstance(value, list) or key in ('index_lists', 'chains', 'systems', 'transports'):
            continue
        def qname(b: Dict[str, Any]) -> Any:
            return f"{b['system']}.{b.get('name')}" if b.get('system') else b.get('name')
        out[key] = [b for b in value if not (isinstance(b, dict) and qname(b) in gone)]
    return out


@needs_app
class Runs(unittest.TestCase):
    """What comes back runs to the numbers the model it came from gives."""

    def test_a_re_imported_model_runs_to_the_same_results(self):
        run = _engine()
        if isinstance(run, str):
            self.skipTest(run)
        for name in ('biosphere.json', 'landscape.json', 'recorders.json', 'EVERY_KIND', 'TRANSPORT', 'SWITCHES'):
            with self.subTest(model=name):
                model = models()[name]
                out = export_eco(model)
                back = import_eco_file(out.bytes)
                a = run(_without(kp.Model(model).raw, [s['name'] for s in out.report.skipped]))
                b = run(kp.Model(back.project).raw)
                self.assertEqual(len(a.t), len(b.t))
                for x, y in zip(a.t, b.t):
                    self.assertLessEqual(abs(x - y), 1e-12 * abs(x))
                theirs = {o['label']: o for o in b.outputs()}
                for o in a.outputs():
                    p = theirs.get(o['label'])
                    self.assertIsNotNone(p, o['label'])
                    xs, ys = a.series(o), b.series(p)
                    scale = max((abs(v) for v in xs), default=0.0) or 1.0
                    worst = max((abs(u - v) for u, v in zip(xs, ys)), default=0.0)
                    self.assertLessEqual(worst, 1e-12 * scale, o['label'])


if __name__ == '__main__':
    unittest.main()
