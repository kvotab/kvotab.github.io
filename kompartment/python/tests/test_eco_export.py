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
import sys
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
from kompartment.io.ecoequation import ecolego_equation, reads_of, unsupported_calls
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

    def test_an_app_is_counted_as_the_application_counts_it_however_it_nests(self):
        # The line saying the app is left out counts every part, inside panels
        # and tabs too, and stops where the application's walk stops.
        deep: Any = {'type': 'text', 'text': 'bottom'}
        for i in range(12):
            deep = {'type': 'panel' if i % 2 else 'tabs', 'components': [deep, 3],
                    'tabs': [{'name': 't', 'components': [deep]}, None]}
        model = dict(models()['EVERY_KIND'])
        model['app'] = {'pages': [{'components': [
            {'type': 'panel', 'components': [{'type': 'slider'}, {'type': 'tabs', 'tabs': [
                {'components': [{'type': 'chart'}, {'type': 'value'}]}, {'components': [{'type': 'image'}]}]}]},
            deep,
        ]}, {'components': 'not a list'}]}
        answer = js([{'task': 'export', 'model': model}])[0]
        self.assertNotIn('error', answer)
        out = export_eco(model)
        line = [w for w in out.report.warnings if w.startswith('The app built on the model')]
        self.assertEqual(len(line), 1)
        self.assertEqual(line, [w for w in answer['report']['warnings'] if w.startswith('The app built on the model')])

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
        self.assertEqual([java_double(seconds_for(v, 'day')) if v > 0 else None for v in values], answer['days'])
        # And the ones JSON cannot carry.
        self.assertEqual([java_double(v) for v in (math.nan, math.inf, -math.inf, -0.0)],
                         ['NaN', 'Infinity', '-Infinity', '-0.0'])
        for v in values:
            self.assertEqual(float(java_double(v)), v)


    def test_equations_are_spelled_as_the_application_spells_them(self):
        texts = EQUATIONS + _random_equations(random.Random(20260927), 4000)
        answer = js([{'task': 'equations', 'texts': texts, 'wraps': WRAPS}])[0]['equations']
        for text, theirs in zip(texts, answer):
            with self.subTest(equation=text):
                ours = ecolego_equation(text, WRAPS.get)
                self.assertEqual([ours.text, ours.units, ours.written_out, ours.respelled],
                                 [theirs['text'], theirs['units'], theirs['writtenOut'], theirs['respelled']])
                self.assertEqual(unsupported_calls(text), theirs['unsupported'])
                names, time = reads_of(text)
                self.assertEqual([names, time], [theirs['reads']['names'], theirs['reads']['time']])
        # The battery reaches the rules: most of it is written again, and some
        # of it only reprinted as it was.
        changed = sum(1 for a in answer[:len(EQUATIONS)] if a['respelled'])
        self.assertGreater(changed, len(EQUATIONS) // 2)
        self.assertTrue(any(not a['respelled'] for a in answer[:len(EQUATIONS)]))


#: A transfer by its donor but for one index, which says otherwise.
MIXED = {
    'name': 'Mixed',
    'index_lists': [{'name': 'Objects', 'indices': [{'name': 'A'}, {'name': 'B'}]}],
    'compartments': [{'name': 'Pond', 'index_lists': ['Objects'], 'initial': '100'}],
    'transfers': [{'name': 'Out', 'from': 'Pond', 'to': None, 'index_lists': ['Objects'], 'rate': '0.1',
                   'entries': [{'index': {'Objects': 'B'}, 'rate': '2', 'multiply_by_donor': False}]}],
    'simulation': {'start_time': 0, 'end_time': 10, 'output_points': 11, 'spacing': 'linear', 'solver': 'ndf',
                   'rtol': 1e-10, 'abstol': 1e-12, 'time_unit': 'year'},
}

#: Equations each rule of ``io/ecoequation.py`` is for, and some it has to
#: leave as they are -- not least the ones that do not parse.
EQUATIONS = [
    # Nothing to do.
    'k * 2', '1e-3 + x', '(a + b) * c', 'Sys.X / 2', 'C[Cs-137] * 2', 'M[_Ra-226][] + M[][Pb-210]',
    'exp(-lambda * time)', '', '   ', '7', '1.50E+3 * k', 'a.*b ./ c', 'a .^ 2',
    # A sign after an operator, and powers.
    'a - -b', 'a * -b', 'a / +b', 'a+-b', '2^-k', '-2^2', '(-2)^2', '2^3^2', 'a^(b^c)', '-a^b', '2^-2^2',
    'a - (b - c)', 'a / (b * c)', 'a / b * c', '(a)', '((a))', 'a - -(-b)', '--a', '-(-a)', '2^-k - -k',
    # Tests as numbers, and as conditions.
    'a > b', '(a > b) * 2', 'a == b', 'a != b', 'a >= b && c < d', 'a || b', 'a ~= b', '3 && 2', 'x == 1 == 1',
    '1 < 2 == 1', 'x ? 1 : 2', 'a > 0 ? b : c > 0 ? d : e', '(1 > 0) ? (2 < 1) : 7',
    '(time > 5) * 2 + (k != 0 ? 1 : 2)',
    'if(a > b, 1, 2)', 'if(a, 1, 2)', 'if(a && b, 1)', 'if(not(a), 1, 2)', 'if(if(a, 1, 0), 2, 3)',
    'if(x ? 1 : 0, 2, 3)', 'if(c, 1, 2) > 1', 'if(-a, 1, 2)', 'if(a > b || c < d && e == f, 1, 2)',
    'if((a || b) && c, 1, 2)', 'if(and(a, or(b, c)), 1, 2)', 'if(-a > -b, -1, -2)', 'if(a ~= 0, a, 1)',
    'k * if(time > 2 && Store > 0, 1, 0.5)',
    # The logical functions.
    'and(a, b)', 'or(a > 0, b)', 'not(a)', 'nand(1, 0, 1)', 'nor(a, b)', 'xor(a, b, c)', 'xor(k, 0)',
    'and(k > 0, n0 > 0, T > 0) + xor(k, 0) + nand(1, k)', 'not(not(a))', 'or(and(a, b), c)', 'and(or(a, b), c)',
    # mod, with and without a divisor that may be zero.
    'mod(7, 0)', 'mod(a, b)', 'mod(a, 3)', 'mod(a, -2)', 'mod(a, 0.0)', 'mod(a, -0)', 'rem(a, b)',
    'mod(time, k - k) + mod(time, 3)', 'mod(mod(a, b), c)',
    # Spellings Ecolego lacks, and aggregates of one value.
    'ln(2)', 'fabs(-k)', 'pow(a, b)', 'sgn(x)', 'product(a, b)', 'max(5)', 'min(a)', 'sum(a)', 'mean(a)',
    'prod(a)', 'max(k) + ln(2) + fabs(-k)', 'max(a, b)', 'min(-a, b, c)',
    # What is written out as arithmetic.
    'mole2bq(n, T)', 'bq2mole(a, T)', 'mole2bq(n0, T) / 2', 'ulp(-3e7)', 'ulp(x)', 'rampUp(time, 1, 5)',
    'rampDown(t, 1, 5)', 'smoothUp(time, 5, 2)', 'smoothDown(time, 5, 2)',
    'rampUp(time, 1, 5) * smoothDown(time, 5, 2) + ulp(k)', 'asinh(x)', 'acosh(x)', 'atanh(x)', 'asinh(-2 * k)',
    'acosh(1 + k)^2', '-atanh(k / 2)',
    # What has no counterpart.
    'percentile(50, k, n0, T)', 'percentile(50, k, n0, T) + 1', 'transport_sum(a, b, c)', 'transport_point(a, b)',
    # Units.
    '1[m] * 3', '0.01[m]', '1.5[m] * k', 'x + 2[Bq]', 'Inventory / 2 + 1[Bq]', '1[m/s]', '-2[kg] * a',
    # The model's own functions and tables.
    'f(x) + 1', 'Retardation(3) + Sorption[Lake]', 'Retardation(-x)', 'Retardation(Retardation(x))', 'Other(2)',
    'Shifted(time) * 2', 'Shifted(1.5e3)', 'Retardation(3 - 0.0)', 'Retardation(a, b)',
    # Not equations: left as they are.
    '1 +', 'foo(', '#', ')', '1 2', 'a ? b', 'if(', 'mod(1)', 'exp()', 'a[', '*a',
]

#: The tables that repeat over their range in ``EQUATIONS``, with it.
WRAPS = {'Retardation': {'first': '0.0', 'span': '10.0'}, 'Shifted': {'first': '-2.5', 'span': '5.0'}}


def _random_equations(rng: random.Random, n: int) -> List[str]:
    """Equations made up at random from what the rules are about, wrong
    arities and all."""
    names = ['k', 'a', 'b', 'T', 'Sys.X', 'C[Cs-137]', 'time', 'Retardation(k)', 'Shifted(-a)', 'f(a, 2)']
    numbers = ['0', '2', '0.5', '1e-3', '3.0E2', '7', '-1', '1[m]', '2.5[Bq]', '0.0']
    calls = ['if', 'and', 'or', 'not', 'nand', 'nor', 'xor', 'mod', 'rem', 'min', 'max', 'sum', 'mean', 'prod',
             'ln', 'log', 'exp', 'sqrt', 'abs', 'fabs', 'pow', 'sgn', 'sign', 'product', 'mole2bq', 'bq2mole',
             'ulp', 'rampUp', 'rampDown', 'smoothUp', 'smoothDown', 'asinh', 'acosh', 'atanh', 'percentile',
             'Retardation', 'Shifted', 'f']
    binary = ['+', '-', '*', '/', '^', '<', '<=', '>', '>=', '==', '!=', '~=', '&&', '||', '.*', './']

    def expr(depth: int) -> str:
        roll = rng.random()
        if depth <= 0 or roll < 0.25:
            return rng.choice(names if rng.random() < 0.5 else numbers)
        if roll < 0.5:
            return f'{expr(depth - 1)} {rng.choice(binary)} {expr(depth - 1)}'
        if roll < 0.58:
            return f'-{expr(depth - 1)}'
        if roll < 0.66:
            return f'({expr(depth - 1)})'
        if roll < 0.72:
            return f'{expr(depth - 1)} ? {expr(depth - 1)} : {expr(depth - 1)}'
        args = ', '.join(expr(depth - 1) for _ in range(rng.choice([1, 2, 2, 3, 3, 4])))
        return f'{rng.choice(calls)}({args})'

    return [expr(rng.randint(1, 4)) for _ in range(n)]


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
            # What the report names, and the sub-systems a far-field path was written as.
            exclude = ([s['name'] for s in out.report.skipped] + [s['name'] for s in out.report.rewritten]
                       + [s['into'] for s in out.report.rewritten if 'into' in s])
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
        for key in ('far-field pathway:Idle', 'waste package:Canisters', 'event:Quake', 'transfer:Discharge',
                    'transfer:Shared', 'parameter:per_transfer', 'expression:Ends', 'function:Zero',
                    'expression:Reads_that', 'distribution:k', 'distribution:Kd', 'correlation group:grouped',
                    'correlation:1 pair(s)'):
            self.assertIn(key, skipped)
        self.assertTrue(any(w.startswith('The diagram is this tool’s own and is not written (its layout)')
                            for w in out.report.warnings))
        rewritten = {s['name']: s['how'] for s in out.report.rewritten}
        # A path that runs goes out as its cells; the one switched off cannot be laid out.
        self.assertIn('written as the sub-system Path_cells', rewritten['Path'])
        self.assertIn('Path_cells.F1', rewritten['ToPath'])
        self.assertNotIn('far-field pathway:Path', skipped)
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

    def test_a_transfer_that_is_both_goes_out_row_by_row_and_comes_back_as_two(self):
        # Multiplying by the donor is one setting of a transfer. A model that
        # says otherwise at one index is refused, written as it says -- row by
        # row, as Ecolego reads it -- and read back as two transfers.
        from kompartment.engine.project import Project, ValidationError
        with self.assertRaises(ValidationError) as refused:
            Project(kp.Model(MIXED).raw)
        self.assertTrue(str(refused.exception).startswith(
            'Out: It multiplies its rate by the donor, and B says otherwise. That is one setting'), refused.exception)
        self.assertEqual(kp.Model(MIXED).check(), [
            'Out: B says otherwise about multiplying by the donor, which is one setting for the whole transfer; '
            'make it two transfers, one by the donor and one an absolute flux'])
        answer = js([{'task': 'export', 'model': MIXED}])[0]
        out = export_eco(MIXED)
        self.assertEqual(base64.b64encode(out.bytes).decode('ascii'), answer['base64'])
        self.assertEqual(json_text(out.report.to_dict()), json_text(answer['report']))
        self.assertTrue(any(w.startswith("'Out' multiplies by its donor at some indices") for w in out.report.warnings))
        back = import_eco_file(out.bytes).project
        said = [f"{t['name']}:{t['multiply_by_donor']}:{t['rate']}:"
                + '/'.join(f"{e['index']['Objects']}={e['rate']}" for e in t.get('entries', []))
                for t in back['transfers']]
        self.assertEqual(said, ['Out:True:0.1:B=0', 'Out_absolute:False:0:B=2'])
        run = _engine()
        if isinstance(run, str):
            return
        r = run(kp.Model(back).raw)
        series = {o['label']: r.series(o) for o in r.outputs()}
        for i, t in enumerate(r.t):
            self.assertAlmostEqual(series['Pond [A]'][i] / (100 * math.exp(-0.1 * t)), 1, delta=1e-7)
            self.assertAlmostEqual(series['Pond [B]'][i], 100 - 2 * t, delta=1e-7)

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


def _half_lives(raw: Dict[str, Any]) -> Dict[str, float]:
    """The half-lives a run of a model uses, in years."""
    from kompartment.engine.project import Project
    return Project(raw).half_lives


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
                # A half-life that no double of seconds divides back to exactly
                # comes back a step off -- Y-90's, in Ecolego's year -- and a
                # delay reads the step as a history a hair apart, a few parts in
                # a billion. Compared at the tolerance the model was solved to.
                was, now = _half_lives(kp.Model(model).raw), _half_lives(kp.Model(back.project).raw)
                stepped = any(n in now and was[n] != now[n] and abs(was[n] - now[n]) <= sys.float_info.epsilon * was[n]
                              for n in was)
                tol = 1e-7 if stepped else 1e-12
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
                    self.assertLessEqual(worst, tol * scale, o['label'])


if __name__ == '__main__':
    unittest.main()
