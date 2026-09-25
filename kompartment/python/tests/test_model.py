"""The API on its own: building, editing, reading back and writing out a model."""

from __future__ import annotations

import gzip
import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path

from helpers import EXAMPLES, example, needs_app

import kompartment as kp
from kompartment import distributions as dist


def two_boxes() -> kp.Model:
    m = kp.Model.new('Two boxes')
    m.add_nuclides(['Cs-137', 'Sr-90'])
    m.add_compartment('Soil', initial='1e10')
    m.add_compartment('Well')
    m.add_parameter('k', 0.05, unit='1/year')
    m.add_transfer('Soil', 'Well', rate='k')
    return m


class Building(unittest.TestCase):
    def test_a_model_from_nothing(self):
        m = two_boxes()
        self.assertEqual(m.nuclides, ['Cs-137', 'Sr-90'])
        self.assertEqual(m.materials, ['Cs-137', 'Sr-90'])
        self.assertEqual(m['Soil'].index_lists, ['Radionuclides'])
        self.assertEqual(m['k'].index_lists, [])
        t = m['Soil_Well']
        self.assertIsInstance(t, kp.Transfer)
        self.assertEqual((t.source, t.target, t.rate, t.multiply_by_donor), ('Soil', 'Well', 'k', True))
        self.assertEqual(t.unit, '1/year')
        self.assertEqual(m.state_count(), 4)
        self.assertEqual(m.check(), [])

    def test_default_names_follow_the_application(self):
        m = kp.Model.new()
        self.assertEqual(m.add_compartment().name, 'C')
        self.assertEqual(m.add_compartment().name, 'C1')
        self.assertEqual(m.add_expression().name, 'E')
        self.assertEqual(m.add_parameter().name, 'p')
        self.assertEqual(m.add_transfer('C', None).name, 'T')
        self.assertEqual(m.add_transfer('C', 'C1').name, 'C_C1')
        self.assertEqual(m.add_transfer('C', 'C1').name, 'C_C11')

    def test_names_are_checked(self):
        m = two_boxes()
        for bad in ('1abc', 'a-b', 'exp', '__proto__', 'Soil', ''):
            with self.subTest(name=bad), self.assertRaises(kp.EditError):
                m.add_parameter(bad, 1)

    def test_a_failed_add_leaves_nothing_behind(self):
        m = two_boxes()
        before = m.to_json()
        with self.assertRaises(kp.EditError):
            m.add_parameter('q', 'not a number')
        with self.assertRaises(kp.EditError):
            m.add_lookup('L', points=[[0, 1], ['x', 2]])
        with self.assertRaises(kp.EditError):
            m.add_index_reduction('R', 'Nothing')
        self.assertEqual(m.to_json(), before)

    def test_per_index_values(self):
        m = two_boxes()
        soil = m['Soil']
        soil.set_value('5e9', at='Cs-137')
        soil.set_entry('Sr-90', initial='2', abstol=1e-3)
        self.assertEqual(soil.value_at('Cs-137'), '5e9')
        self.assertEqual(soil.value_at({'Radionuclides': 'Sr-90'}), '2')
        self.assertEqual(soil.value_at('Sr-90', key='abstol'), 1e-3)
        self.assertEqual(soil.value, '1e10')
        self.assertEqual(soil.overrides(), [({'Radionuclides': 'Cs-137'}, '5e9'), ({'Radionuclides': 'Sr-90'}, '2')])
        soil.clear_value('Cs-137')
        self.assertEqual(soil.value_at('Cs-137'), '1e10')
        with self.assertRaises(kp.EditError):
            soil.set_value('1', at='U-238')
        with self.assertRaises(kp.EditError):
            soil.set_value('1', at='Cs-137', key='rate')
        self.assertEqual(soil.combinations(), [{'Radionuclides': 'Cs-137'}, {'Radionuclides': 'Sr-90'}])

    def test_two_dimensions(self):
        m = two_boxes()
        m.add_index_list('Object', ['Lake', 'Mire'])
        followed = m.set_dimensions('Soil', ['Radionuclides', 'Object'])
        self.assertIn('Soil_Well', followed)
        # The ends no longer correspond, so the flux takes the union and would
        # have to sum over Object at Well: the application's rule.
        self.assertEqual(m['Soil_Well'].index_lists, ['Radionuclides', 'Object'])
        kd = m.add_parameter('Kd', 0, index_lists=['Radionuclides', 'Object'])
        kd.set_value(0.03, at={'Radionuclides': 'Cs-137', 'Object': 'Lake'})
        kd.set_value(0.01, at=('Sr-90', 'Mire'))
        self.assertEqual(kd.value_at(('Cs-137', 'Lake')), 0.03)
        self.assertEqual(kd.value_at(('Cs-137', 'Mire')), 0)
        self.assertEqual(len(kd.combinations()), 4)
        kd.set_value(1, at='Lake')  # one index names its list when only one list has it
        self.assertEqual(kd.value_at(('Sr-90', 'Lake')), 1)
        with self.assertRaises(kp.EditError):
            m.set_dimensions('Kd', ['Radionuclides', 'Contaminants'])  # a sub-set and its root

    def test_distributions(self):
        m = two_boxes()
        p = m['k']
        p.distribution = dist.log_triangular(0.01, 0.1, 0.05)
        self.assertEqual(p.distribution['kind'], 'logt')
        with self.assertRaises(dist.DistributionError):
            dist.log_uniform(-1, 1)
        with self.assertRaises(dist.DistributionError):
            dist.uniform(2, 1)
        m.set_dimensions('k', ['Radionuclides'])
        p.set_distribution('norm', at='Cs-137', mean=0.05, sd=0.01, trmin=0)
        self.assertEqual(p.distribution_at('Cs-137')['params'], {'mean': 0.05, 'sd': 0.01})
        self.assertEqual(p.distribution_at('Sr-90')['kind'], 'logt')
        self.assertIn('log-triangular', dist.describe(p.distribution))

    def test_lookups(self):
        m = two_boxes()
        q = m.add_lookup('Q', [[0, 1], [100, 2]], interpolation='nearest', argument='x')
        self.assertEqual(q.points, [[0, 1], [100, 2]])
        self.assertEqual(q.argument, 'x')
        flat = m.add_lookup('Flat')
        self.assertEqual(flat.points, [[0, 0], [1000, 0]])
        with self.assertRaises(kp.EditError):
            q.interpolation = 'cubic'
        q.set_point_distribution(1, 'unif', min=1.5, max=2.5)
        self.assertEqual(q.points[1][2]['kind'], 'unif')

    def test_every_kind(self):
        m = two_boxes()
        m.add_expression('Conc', 'Well / 10')
        m.add_index_reduction('Total', 'Conc')
        m.add_block_reduction('Both', ['Soil', 'Well'], operation='max')
        m.add_function('twice', ['x'], 'x * 2')
        m.add_trigger('High', 'Conc', '1e3')
        m.add_min_max('Peak', 'Conc', reset_trigger='High')
        m.add_running_mean('Mean', 'Conc', start_trigger='High')
        m.add_snapshot('Snap', 'time', 'High', initial='-1')
        m.add_delay('Late', 'Conc', 100)
        path = m.add_farfield('Rock', n_f=10, kd_m='0.1')
        m.set_release('Rock', 'Well')
        pk = m.add_waste_package('Pkgs', failure='weibull', fail_start=1000, fail_scale=5e4, fail_shape=2,
                                 inventory='1e12')
        m.add_compartment('Near')
        pk.set_release('Near')
        ev = m.add_event('Quake', timing='poisson', rate='1e-5')
        ev.add_fail_action('Pkgs', 0.05)
        ev.add_move_action('Well', None, '0.5')
        self.assertEqual(path.n_f, 10)
        self.assertEqual(path.release.target, 'Well')
        self.assertTrue(path.release.is_release)
        self.assertEqual(m['Total'].index_lists, [])
        self.assertEqual(m['Total'].over, 'Radionuclides')
        self.assertEqual(m['Peak'].index_lists, ['Radionuclides'])
        self.assertEqual(m['Snap'].index_lists, [])
        self.assertEqual(m.check(), [])
        with self.assertRaises(kp.EditError):
            m.add_transfer('Rock', 'Near')  # one release per path

    def test_decay(self):
        m = kp.Model.new()
        m.add_nuclides(['U-238', 'U-234', 'Th-230'])
        pairs = {p[:2]: p[2] for p in m.decay_chains}
        self.assertAlmostEqual(pairs[('U-238', 'U-234')], 1, places=6)  # through Th-234 and Pa-234m
        self.assertIn(('U-234', 'Th-230'), pairs)
        self.assertFalse(m.has_own_chains)
        self.assertAlmostEqual(m.half_life('U-238'), 4.468e9, delta=1e7)
        with self.assertRaises(kp.EditError):
            m.add_decay_pair('Th-230', 'U-238')  # a loop
        m.set_decay_ratio('U-238', 'U-234', 0.99)
        self.assertTrue(m.has_own_chains)
        m.reset_decay_chains()
        self.assertFalse(m.has_own_chains)
        m.add_nuclides(['Xx-1'])
        self.assertEqual(m.half_life('Xx-1'), math.inf)
        m.set_half_life('Xx-1', 12.5)
        self.assertEqual(m.half_life('Xx-1'), 12.5)
        m.remove_nuclide('Xx-1')
        self.assertNotIn('Xx-1', m.raw.get('half_lives', {}))
        m.add_material('Water', unit='m3')
        self.assertEqual(m.material_unit('Water'), 'm3')
        with self.assertRaises(kp.EditError):
            m.set_material_unit('U-238', 'kg')
        m.decay_unit = 'mol'
        self.assertEqual(m.material_unit('U-238'), 'mol')

    def test_scenarios(self):
        m = two_boxes()
        m.add_scenarios(['Base', 'Wet'])
        self.assertEqual(m.scenario, 'Base')
        m.scenario = 'Wet'
        m.index_list('Scenarios').rename_index('Wet', 'Humid')
        self.assertEqual(m.scenario, 'Humid')
        with self.assertRaises(kp.EditError):
            m.scenario = 'Dry'

    def test_sub_systems_and_transports(self):
        m = two_boxes()
        m.add_system('Near')
        self.assertEqual(m.add_system('Near'), 'Near1')  # numbered, as the application does
        m.move_block('Soil', 'Near')
        self.assertEqual(m['Near.Soil_Well'].system, 'Near')  # a transfer lives with its donor
        self.assertEqual(m['Near.Soil'].qualified_name, 'Near.Soil')
        m.rename_system('Near', 'Nearfield')
        self.assertEqual(m['Nearfield.Soil_Well'].source, 'Nearfield.Soil')
        tube = m.add_transport('Tube', number='10')
        m.add_transfer('Nearfield.Soil', tube)
        self.assertEqual(m.transports, ['Tube'])
        with self.assertRaises(kp.EditError):
            m.delete_block('Tube.Begin')
        with self.assertRaises(kp.EditError):
            m.delete_system('Tube')  # its parts cannot be let out
        m.delete_system('Tube', contents='delete')
        self.assertNotIn('Tube', m.systems)
        m.set_system_enabled('Nearfield', False)
        self.assertFalse(m['Nearfield.Soil'].effectively_enabled)
        self.assertEqual(m.check(), [])

    def test_follows_availability_operands(self):
        # The application's own rename misses these; this package does not.
        m = two_boxes()
        m.add_parameter('Lim', 5)
        m['Soil_Well'].set_availability('limit', limit='Lim * 2')
        m.rename_block('Lim', 'Solubility')
        self.assertEqual(m['Soil_Well'].availability['limit'], 'Solubility * 2')
        with self.assertRaises(kp.EditError):
            m.delete_block('Solubility')

    def test_review(self):
        m = two_boxes()
        m.review_tracking = True
        m.record_review('k', by='me', reviewer='you', at='2026-01-01T00:00:00.000Z')
        m.record_review('Soil_Well', at='2026-01-01T00:00:00.000Z')
        status = m.review_status()
        self.assertEqual(status['k'], 'approved')
        self.assertEqual(status['Soil_Well'], 'review')  # it reads Soil and Well, never reviewed
        m['k'].value = 0.06
        self.assertEqual(m.review_status()['k'], 'stale')

    def test_view_shapes_derived(self):
        m = two_boxes()
        m.view.show_parameters = True
        self.assertTrue(m.view.show_parameters)
        with self.assertRaises(kp.EditError):
            m.view.connection_label = 'bold'
        s = m.add_shape('sticky', 10, 20, text='Look here')
        self.assertEqual((s.fill, s.text_font, s.text), ('amber', 'scribble', 'Look here'))
        with self.assertRaises(kp.EditError):
            s.update(fill='pink')
        s.delete()
        self.assertEqual(m.shapes, [])
        m.add_derived('Peak dose', 'max', 'Well [Cs-137]')
        with self.assertRaises(kp.EditError):
            m.add_derived('Annual', 'period_mean', 'Well [Cs-137]')
        m['Soil'].position = (100, 50.4)
        self.assertEqual(m['Soil'].position, (100, 50))
        m.rename_block('Soil', 'Topsoil')
        self.assertEqual(m['Topsoil'].position, (100, 50))

    def test_simulation_settings(self):
        m = two_boxes()
        sim = m.simulation
        sim.update(end_time=1e6, rtol=1e-6, solver='radau5', max_order=3)
        self.assertEqual((sim.end_time, sim.rtol, sim.solver), (1e6, 1e-6, 'radau5'))
        for key, value in (('rtol', 0), ('solver', 'euler'), ('time_unit', 'week'), ('spacing', 'cubic'),
                           ('output_points', 1), ('max_order', 7), ('split', 'maybe')):
            with self.subTest(key=key), self.assertRaises(kp.EditError):
                sim.set(key, value)
        sim.spacing = 'series'
        self.assertEqual(sim.output_series[0].kind, 'log')
        sim.add_output_series('times', times=[5, 1, 3])
        self.assertEqual(sim.output_series[1].times, [1, 3, 5])


class Editing(unittest.TestCase):
    def test_rename_follows_every_reference(self):
        m = kp.Model(example('recorders'))
        m.rename_block('Dose', 'DoseRate')
        self.assertEqual(m['Peak_dose'].target, 'DoseRate')
        self.assertEqual(m['Below_limit'].first, 'DoseRate')
        m.rename_block('Below_limit', 'Crossing')
        self.assertEqual(m['Year_below_limit'].trigger, 'Crossing')
        self.assertEqual(m['Mean_dose_after'].start_trigger, 'Crossing')
        self.assertEqual(m.references_to('Crossing'), ['Mean_dose_after', 'Year_below_limit'])

    def test_delete_refuses_while_read(self):
        m = kp.Model(example('four-compartment'))
        with self.assertRaises(kp.EditError) as ctx:
            m.delete_block('C4')
        self.assertIn('Outflow', ctx.exception.detail)
        self.assertEqual(sorted(m.delete_blocks(['C4', 'Outflow'])), ['C4', 'Outflow', 'TCOut'])

    def test_index_edits_reach_equations(self):
        m = kp.Model(example('biosphere'))
        m.add_expression('Only', 'Soil[I-129] * 2', index_lists=[])
        m.rename_index('Radionuclides', 'I-129', 'I129')
        self.assertEqual(m['Only'].equation, 'Soil[I129] * 2')
        self.assertIn('I129', m.materials)

    def test_move_blocks_is_all_or_nothing(self):
        m = kp.Model(example('four-compartment'))
        m.add_system('Sub')
        before = m.to_json()
        with self.assertRaises(kp.EditError):
            m.move_blocks(['C3', 'Nothing'], 'Sub')
        self.assertEqual(m.to_json(), before)


class Files(unittest.TestCase):
    def test_every_example_round_trips(self):
        for path in sorted(EXAMPLES.glob('*.json')):
            with self.subTest(example=path.name):
                m = kp.Model.load(path)
                again = kp.Model.from_json(m.to_json())
                self.assertEqual(again.to_json(), m.to_json())

    def test_json_gz_and_zip(self):
        m = two_boxes()
        with tempfile.TemporaryDirectory() as d:
            for name in ('m.json', 'm.json.gz', 'm.zip'):
                p = m.save(Path(d) / name)
                self.assertEqual(kp.Model.load(p).to_json(), m.to_json(), name)
            self.assertEqual(gzip.decompress((Path(d) / 'm.json.gz').read_bytes())[:1], b'{')
            with zipfile.ZipFile(Path(d) / 'm.zip') as z:
                self.assertEqual(z.namelist(), ['two-boxes.json'])

    def test_unnormalised_is_left_exactly(self):
        raw = {'name': 'x', 'nuclides': ['Cs-137'], 'compartments': [{'name': 'A', 'initial': '1'}]}
        m = kp.Model(raw, normalise=False)
        self.assertEqual(json.loads(kp.dumps(m.raw)), raw)

    def test_copy_is_independent(self):
        m = two_boxes()
        c = m.copy()
        c.rename_block('Soil', 'Topsoil')
        self.assertIn('Soil', m)
        self.assertNotIn('Soil', c)


class Checking(unittest.TestCase):
    def test_check_finds_what_raw_edits_break(self):
        m = two_boxes()
        m.raw['expressions'].append({'name': 'Bad', 'equation': 'Nothing * 2 +', 'index_lists': []})
        m.raw['transfers'][0]['to'] = 'Nowhere'
        m['Soil'].raw['index_lists'] = ['Radionuclides', 'Missing']
        problems = m.check()
        self.assertTrue(any("'Nothing'" in p for p in problems), problems)
        self.assertTrue(any('Nowhere' in p for p in problems), problems)
        self.assertTrue(any('Missing' in p for p in problems), problems)

    @needs_app
    def test_validate_through_the_application(self):
        m = two_boxes()
        self.assertEqual(m.validate(), [])
        m.add_expression('Bad', 'exp(1, 2)', index_lists=[])
        with self.assertRaises(kp.ValidationError) as ctx:
            m.validate()
        self.assertTrue(any('exp' in p for p in ctx.exception.problems))

    @needs_app
    def test_every_example_validates(self):
        for path in sorted(EXAMPLES.glob('*.json')):
            with self.subTest(example=path.name):
                kp.Model.load(path).validate()


if __name__ == '__main__':
    unittest.main()
