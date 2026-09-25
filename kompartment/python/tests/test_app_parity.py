"""The package against the application: the same model, the same edit, the same file.

Every test here runs the application's own code (``src/domain/edit.js`` and
friends) through Node beside this package, and compares what the two make of
the model -- as JSON text, so key order counts too.
"""

from __future__ import annotations

import math
import random
import unittest
from typing import Any, Callable, List

from helpers import EXAMPLES, app, differences, example, needs_app

import kompartment as kp
from kompartment.decay import default_chains, known_nuclides
from kompartment.jsonio import dumps, js_number


@needs_app
class OpeningAFile(unittest.TestCase):
    def test_every_example_opens_as_the_application_opens_it(self):
        for path in sorted(EXAMPLES.glob('*.json')):
            with self.subTest(example=path.name):
                raw = example(path.stem)
                py = kp.Model(raw).raw
                js = app('normalise', model=raw)['model']
                self.assertEqual(differences(py, js), [])
                self.assertEqual(dumps(py), dumps(js))

    def test_older_spellings_open_the_same(self):
        raw = {
            'name': 'Old', 'nuclides': ['Cs-137', 'Sr-90'],
            'simulation': {'startTime': 0, 'endTime': 100, 'solver': 'ode15s'},
            'compartments': [
                {'name': 'A', 'initial': {'Cs-137': '5', 'Sr-90': 2}, 'handleDecay': True},
                {'name': 'B', 'default': '3', 'perNuclide': False},
            ],
            'parameters': [{'name': 'k', 'valuesByNuclide': {'Cs-137': 0.1, 'Sr-90': '0.2'}}],
            'transfers': [{'name': 'AB', 'from': 'A', 'to': 'B', 'rate': 'k', 'multiplyByDonor': True}],
            'sources': [{'name': 'In', 'to': 'A', 'rate': '1'}],
            'discrete_events': [], 'aggregates': [],
        }
        py = kp.Model(raw).raw
        js = app('normalise', model=raw)['model']
        self.assertEqual(differences(py, js), [])

    def test_a_single_material_list_is_split_as_the_application_splits_it(self):
        raw = {
            'name': 'One list',
            'index_lists': [{'name': 'Nuclide', 'for_materials': True, 'indices': ['Cs-137', 'I-129']},
                            {'name': 'Element', 'mapping': {'to': 'Nuclide', 'pairs': []}, 'indices': []}],
            'compartments': [{'name': 'A', 'initial': '1', 'index_lists': ['Nuclide']}],
        }
        py = kp.Model(raw).raw
        js = app('normalise', model=raw)['model']
        self.assertEqual(differences(py, js), [])

    def test_a_new_model_is_the_application_s_new_model(self):
        from kompartment.simulation import DEFAULTS
        blank = {
            'name': 'New model', 'description': '', 'simulation': dict(DEFAULTS, end_time=1000),
            'parameters': [], 'compartments': [], 'transfers': [], 'expressions': [], 'inflows': [],
        }
        js = app('normalise', model=blank)['model']
        self.assertEqual(dumps(kp.Model.new().raw), dumps(js))

    def test_state_counts_agree(self):
        for path in sorted(EXAMPLES.glob('*.json')):
            with self.subTest(example=path.name):
                raw = example(path.stem)
                self.assertEqual(kp.Model(raw).state_count(), app('count', model=raw)['count'])


# Each scenario: an example, the edits as edit.js spells them, and the same
# edits through this package.
Scenario = Callable[[kp.Model], Any]
SCENARIOS: List[Any] = [
    ('four-compartment', 'rename a compartment',
     [['renameBlock', 'C2', 'Middle']], lambda m: m.rename_block('C2', 'Middle')),
    ('four-compartment', 'rename a transfer an equation reads',
     [['renameBlock', 'TCOut', 'Out']], lambda m: m.rename_block('TCOut', 'Out')),
    ('four-compartment', 'rename a parameter',
     [['renameBlock', 'p12', 'k12']], lambda m: m.rename_block('p12', 'k12')),
    ('four-compartment', 'delete a transfer',
     [['deleteBlock', 'T3']], lambda m: m.delete_block('T3')),
    ('four-compartment', 'delete a compartment with its transfers, refused while read',
     [['deleteBlock', 'C4']], lambda m: m.delete_block('C4')),
    ('four-compartment', 'delete two blocks that read each other',
     [['deleteBlocks', ['C4', 'Outflow']]], lambda m: m.delete_blocks(['C4', 'Outflow'])),
    ('four-compartment', 'a sub-system, and a compartment moved into it',
     [['addSystem', {'name': 'Sub'}], ['moveBlock', 'C3', 'Sub']],
     lambda m: (m.add_system('Sub'), m.move_block('C3', 'Sub'))),
    ('four-compartment', 'move, rename and dissolve a sub-system',
     [['addSystem', {'name': 'Sub'}], ['moveBlock', 'C3', 'Sub'], ['moveBlock', 'p34', 'Sub'],
      ['renameSystem', 'Sub', 'Inner'], ['addSystem', {'name': 'Outer'}], ['moveSystem', 'Inner', 'Outer'],
      ['deleteSystem', 'Outer', {'contents': 'move'}]],
     lambda m: (m.add_system('Sub'), m.move_block('C3', 'Sub'), m.move_block('p34', 'Sub'),
                m.rename_system('Sub', 'Inner'), m.add_system('Outer'), m.move_system('Inner', 'Outer'),
                m.delete_system('Outer', contents='move'))),
    ('four-compartment', 'delete a sub-system with its contents, refused while read',
     [['addSystem', {'name': 'Sub'}], ['moveBlock', 'C3', 'Sub'], ['deleteSystem', 'Sub', {'contents': 'delete'}]],
     lambda m: (m.add_system('Sub'), m.move_block('C3', 'Sub'), m.delete_system('Sub', contents='delete'))),
    ('four-compartment', 'a name taken where a block moves is numbered',
     [['addSystem', {'name': 'Sub'}], ['addCompartment', {'name': 'C1', 'system': 'Sub'}], ['moveBlock', 'C1', 'Sub']],
     lambda m: (m.add_system('Sub'), m.add_compartment('C1', system='Sub'), m.move_block('C1', 'Sub'))),
    ('four-compartment', 'a shadowed spelling is refused',
     [['addSystem', {'name': 'Sub'}], ['moveBlock', 'T1', 'Sub'], ['addParameter', {'name': 'p12', 'system': 'Sub'}],
      ['moveBlock', 'C1', 'Sub']],
     lambda m: (m.add_system('Sub'), m.move_block('T1', 'Sub'), m.add_parameter('p12', system='Sub'),
                m.move_block('C1', 'Sub'))),
    ('four-compartment', 'transfers added and re-attached',
     [['addTransfer', 'C4', None, {'rate': '0.1'}], ['addTransfer', 'C1', 'C4', {}],
      ['setConnectionEnd', 'T3', 'to', 'C4'], ['setConnectionEnd', 'T', 'from', 'C2']],
     lambda m: (m.add_transfer('C4', None, '0.1'), m.add_transfer('C1', 'C4'),
                m.set_connection_end('T3', 'to', 'C4'), m.set_connection_end('T', 'from', 'C2'))),
    ('four-compartment', 'every kind of block added',
     [['addCompartment', {'name': 'C5'}], ['addExpression', {'name': 'E1', 'equation': 'C5*2'}],
      ['addParameter', {'name': 'q', 'value': 3}], ['addLookup', {'name': 'L1'}],
      ['addIndexOperation', {'name': 'Tot', 'target': 'C5'}],
      ['addAggregate', {'name': 'All', 'targets': ['C1', 'C2']}],
      ['addFunction', {'name': 'f', 'parameters': ['x', 'y'], 'equation': 'x*y'}],
      ['addRecorder', 'min_max', {'name': 'Peak', 'target': 'E1'}],
      ['addRecorder', 'trigger', {'name': 'Hit', 'first': 'E1', 'second': '5'}],
      ['addRecorder', 'snapshot', {'name': 'Snap', 'target': 'E1', 'trigger': 'Hit'}],
      ['addRecorder', 'running_mean', {'name': 'Avg', 'target': 'E1'}],
      ['addRecorder', 'delay', {'name': 'Late', 'target': 'E1', 'delay': '10'}],
      ['addSource', {'name': 'Feed', 'to': 'C5', 'rate': '1'}],
      ['addWastePackage', {'name': 'Pk'}], ['addDisruption', {'name': 'Ev'}]],
     lambda m: (m.add_compartment('C5'), m.add_expression('E1', 'C5*2'), m.add_parameter('q', 3),
                m.add_lookup('L1'), m.add_index_reduction('Tot', 'C5'),
                m.add_block_reduction('All', ['C1', 'C2']), m.add_function('f', ['x', 'y'], 'x*y'),
                m.add_min_max('Peak', 'E1'), m.add_trigger('Hit', 'E1', '5'),
                m.add_snapshot('Snap', 'E1', 'Hit'), m.add_running_mean('Avg', 'E1'),
                m.add_delay('Late', 'E1', '10'), m.add_inflow('C5', '1', name='Feed'),
                m.add_waste_package('Pk'), m.add_event('Ev'))),
    ('biosphere', 'a new dimension, a compartment on it, and what follows',
     [['addIndexList', {'name': 'Object', 'indices': ['A', 'B']}],
      ['setBlockDimensions', 'Soil', ['Radionuclides', 'Object']]],
     lambda m: (m.add_index_list('Object', ['A', 'B']), m.set_dimensions('Soil', ['Radionuclides', 'Object']))),
    ('biosphere', 'rename a radionuclide',
     [['renameIndex', 'Radionuclides', 'Cs-137', 'Cs137']],
     lambda m: m.rename_index('Radionuclides', 'Cs-137', 'Cs137')),
    ('biosphere', 'remove a material',
     [['removeIndex', 'Contaminants', 'Cs-137']], lambda m: m.remove_index('Contaminants', 'Cs-137')),
    ('biosphere', 'switch a nuclide off',
     [['setIndexEnabled', 'Radionuclides', 'Cs-137', False]],
     lambda m: m.set_index_enabled('Radionuclides', 'Cs-137', False)),
    ('biosphere', 'add nuclides',
     [['addIndex', 'Radionuclides', 'Ra-226'], ['addIndex', 'Radionuclides', 'Xx-999'],
      ['addIndex', 'Contaminants', 'Water']],
     lambda m: (m.add_index('Radionuclides', 'Ra-226'), m.add_index('Radionuclides', 'Xx-999'),
                m.add_material('Water'))),
    ('biosphere', 'per-index values',
     [['setEntryValue', 'Kd', {'Radionuclides': 'I-129'}, 'value', 3.5],
      ['setEntryValue', 'Soil', {'Radionuclides': 'Tc-99'}, 'initial', '5e9'],
      ['setEntryValue', 'Soil', {'Radionuclides': 'I-129'}, 'initial', '7'],
      ['clearEntryValue', 'Soil', {'Radionuclides': 'Tc-99'}, 'initial']],
     lambda m: (m['Kd'].set_value(3.5, at='I-129'), m['Soil'].set_value('5e9', at='Tc-99'),
                m['Soil'].set_value('7', at={'Radionuclides': 'I-129'}), m['Soil'].clear_value('Tc-99'))),
    ('decay-chain', 'decay pairs and half-lives',
     [['addDecayPair', 'Pu-241', 'U-233', 0.5], ['setDecayRatio', 'Pu-241', 'U-233', 0.25],
      ['removeDecayPair', 'Am-241', 'Np-237'], ['setHalfLife', 'Np-237', 1000], ['setHalfLife', 'U-233', 'stable']],
     lambda m: (m.add_decay_pair('Pu-241', 'U-233', 0.5), m.set_decay_ratio('Pu-241', 'U-233', 0.25),
                m.remove_decay_pair('Am-241', 'Np-237'), m.set_half_life('Np-237', 1000),
                m.set_half_life('U-233', 'stable'))),
    ('decay-chain', 'a loop is refused',
     [['addDecayPair', 'Np-237', 'Pu-241', 1]], lambda m: m.add_decay_pair('Np-237', 'Pu-241', 1)),
    ('decay-chain', 'the decay unit',
     [['setDecayUnit', 'mol']], lambda m: setattr(m, 'decay_unit', 'mol')),
    ('scenarios', 'rename the live scenario, and pick another',
     [['renameIndex', 'Climate', 'Present', 'Today'], ['setScenario', 'Drier']],
     lambda m: (m.rename_index('Climate', 'Present', 'Today'), setattr(m, 'scenario', 'Drier'))),
    ('landscape', 'rename an index list',
     [['renameIndexList', 'Object', 'Site']], lambda m: m.rename_index_list('Object', 'Site')),
    ('landscape', 'a list in use cannot be deleted',
     [['deleteIndexList', 'Wetland']], lambda m: m.delete_index_list('Wetland')),
    ('landscape', 'rename a compartment reductions read',
     [['renameBlock', 'Water', 'Lakewater']], lambda m: m.rename_block('Water', 'Lakewater')),
    ('landscape', 'a reduction follows its target',
     [['setBlockDimensions', 'Water', ['Radionuclides']]], lambda m: m.set_dimensions('Water', ['Radionuclides'])),
    ('recorders', 'rename a trigger recorders are driven by',
     [['renameBlock', 'Below_limit', 'Crossing']], lambda m: m.rename_block('Below_limit', 'Crossing')),
    ('recorders', 'rename what the recorders watch',
     [['renameBlock', 'Dose', 'DoseRate']], lambda m: m.rename_block('Dose', 'DoseRate')),
    ('waste-packages', 'rename packages an event fails',
     [['renameBlock', 'Canisters', 'Pkgs']], lambda m: m.rename_block('Canisters', 'Pkgs')),
    ('waste-packages', 'the release moved',
     [['setRelease', 'Canisters', 'Geosphere']], lambda m: m.set_release('Canisters', 'Geosphere')),
    ('waste-packages', 'packages an event acts on cannot be deleted',
     [['deleteBlock', 'Canisters']], lambda m: m.delete_block('Canisters')),
    ('waste-packages', 'a second release is refused',
     [['addTransfer', 'Canisters', 'Biosphere', {}]], lambda m: m.add_transfer('Canisters', 'Biosphere')),
    ('lookup-driver', 'rename a lookup table read as a function',
     [['renameBlock', 'Q_gw', 'Q']], lambda m: m.rename_block('Q_gw', 'Q')),
    ('farfield', 'switch a path release off, refused while read',
     [['setRelease', 'Rock', None]], lambda m: m.set_release('Rock', None)),
    ('farfield', 'rename a path',
     [['renameBlock', 'Rock', 'Path']], lambda m: m.rename_block('Rock', 'Path')),
    ('four-compartment', 'a transport, connected at both ends',
     [['addTransport', {'name': 'Tube'}], ['addTransfer', 'C1', 'Tube', {}], ['addTransfer', 'Tube', 'C4', {}],
      ['addTransportOperation', {'system': 'Tube', 'operation': 'sum'}]],
     lambda m: (m.add_transport('Tube'), m.add_transfer('C1', 'Tube'), m.add_transfer('Tube', 'C4'),
                m.add_transport_operation('Tube', operation='sum'))),
    ('four-compartment', 'a transport part cannot be deleted alone',
     [['addTransport', {'name': 'Tube'}], ['deleteBlock', 'Tube.Begin']],
     lambda m: (m.add_transport('Tube'), m.delete_block('Tube.Begin'))),
    ('four-compartment', 'a transport deleted whole',
     [['addTransport', {'name': 'Tube'}], ['deleteSystem', 'Tube', {'contents': 'delete'}]],
     lambda m: (m.add_transport('Tube'), m.delete_system('Tube', contents='delete'))),
    ('four-compartment', 'a sub-system switched off, and on again',
     [['addSystem', {'name': 'Sub'}], ['setSystemEnabled', 'Sub', False], ['setSystemEnabled', 'Sub', True]],
     lambda m: (m.add_system('Sub'), m.set_system_enabled('Sub', False), m.set_system_enabled('Sub', True))),
]


@needs_app
class EditingAModel(unittest.TestCase):
    def test_the_edits_the_application_makes(self):
        for name, what, ops, edit in SCENARIOS:
            with self.subTest(example=name, edit=what):
                raw = example(name)
                js = app('edit', model=raw, ops=ops)
                m = kp.Model(raw)
                try:
                    edit(m)
                    refused = None
                except kp.EditError as e:
                    refused = str(e)
                if 'error' in js:
                    self.assertIsNotNone(refused, f"the application refused this ({js['error']}); Python did not")
                    continue
                self.assertIsNone(refused, f'Python refused what the application did: {refused}')
                # The application can write a sub-system path twice after a rename
                # (harmless: it reads the list as a set); this package writes it once.
                if isinstance(js['model'].get('systems'), list):
                    js['model']['systems'] = list(dict.fromkeys(js['model']['systems']))
                self.assertEqual(differences(m.to_dict(), js['model']), [])


@needs_app
class TheSameArithmetic(unittest.TestCase):
    def test_numbers_are_written_as_javascript_writes_them(self):
        rng = random.Random(7)
        values: List[float] = [0.0, -0.0, 1.0, 0.1, 1e21, 1e-7, 1.5e-5, 123456789012345680000.0, 5e-324,
                               1.7976931348623157e308, 100.0, 2 ** 53, 0.000001, 0.0000001, 1e20, 1e22]
        values += [rng.uniform(-1, 1) * 10 ** rng.randint(-30, 30) for _ in range(2000)]
        values += [float(rng.randint(-10 ** 6, 10 ** 6)) for _ in range(200)]
        strings = app('numbers', values=values)['strings']
        for v, s in zip(values, strings):
            self.assertEqual(js_number(v), s, v)

    def test_default_decay_chains(self):
        rng = random.Random(11)
        pool = known_nuclides()
        cases = [['U-238', 'U-234', 'Th-230', 'Ra-226', 'Pb-210', 'Po-210'],
                 ['Pu-241', 'Am-241', 'Np-237', 'U-233', 'Th-229'], ['Cs-137'], ['Xx-1', 'Cs-137']]
        cases += [rng.sample(pool, rng.randint(2, 40)) for _ in range(25)]
        for nuclides in cases:
            for ceiling in (math.inf, 1e6):
                with self.subTest(nuclides=nuclides[:4], ceiling=ceiling):
                    js = app('chains', nuclides=nuclides, ceiling=None if math.isinf(ceiling) else ceiling)['chains']
                    py = default_chains(nuclides, ceiling)
                    self.assertEqual(len(py), len(js))
                    for (p1, d1, b1), (p2, d2, b2) in zip(py, js):
                        self.assertEqual((p1, d1), (p2, d2))
                        self.assertAlmostEqual(b1, b2, delta=1e-15 * max(1.0, abs(b2)))

    def test_review_stamps(self):
        for path in sorted(EXAMPLES.glob('*.json')):
            with self.subTest(example=path.name):
                raw = example(path.stem)
                m = kp.Model(raw)
                js = app('stamps', model=raw)['stamps']
                for b in m.blocks():
                    self.assertEqual(m.review_stamp(b), js[b.qualified_name], b.qualified_name)


if __name__ == '__main__':
    unittest.main()
