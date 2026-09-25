"""The running half of the public API, end to end, without the application.

What the parity tests compare number by number with the application is here
used the way a script uses it: a made-up model built, run, calibrated, its
data written out and read back, its run saved and opened again. The models
are made up or the bundled examples.
"""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from helpers import example

import kompartment as kp


def two_boxes(k: float = 0.1) -> kp.Model:
    """100 units draining from A to B at rate k over ten years: B(10) = 100 (1 - e^-10k)."""
    m = kp.Model.new('Two boxes')
    m.simulation.update(end_time=10, output_points=21, rtol=1e-8, abstol=1e-10, solver='ros23')
    m.add_compartment('A', initial='100')
    m.add_compartment('B')
    m.add_parameter('k', k, unit='1/year')
    m.add_transfer('A', 'B', rate='k')
    return m


class Running(unittest.TestCase):
    def test_a_run_is_the_analytic_answer(self) -> None:
        res = two_boxes().run()
        t = res.t
        self.assertTrue(np.allclose(res['B'], 100 * (1 - np.exp(-0.1 * t)), rtol=1e-6, atol=1e-8))
        self.assertIn('B', res.labels)
        self.assertEqual(res.max('A')['value'], 100.0)
        self.assertTrue(res.jacobian['available'])
        self.assertIn('Kompartment run log', res.run_log())
        csv = res.to_csv()
        self.assertEqual(len(csv.strip().splitlines()), t.size + 1)

    def test_simulation_settings_for_one_run(self) -> None:
        m = two_boxes()
        res = m.run(end_time=20, solver='ndf')
        self.assertEqual(res.t[-1], 20.0)
        self.assertEqual(res.stats['solver'], 'ndf')
        self.assertEqual(m.simulation.end_time, 10)  # the model itself is untouched

    def test_values_at_the_start(self) -> None:
        m = two_boxes()
        self.assertEqual(m.values_at_start('A')['own'][0]['value'], 100.0)
        self.assertEqual(m.values_at_start('k')['own'][0]['value'], 0.1)
        self.assertIsNone(m.values_at_start('Nothing'))

    def test_every_scenario_in_one_process_or_several(self) -> None:
        m = kp.Model.from_dict(example('scenarios'))
        one = m.run_scenarios()
        two = m.run_scenarios(workers=2)
        self.assertEqual(list(one), list(two))
        self.assertGreater(len(one), 1)
        for name in one:
            for a, b in zip(one[name].series_many(one[name].outputs()), two[name].series_many(two[name].outputs())):
                self.assertTrue(np.array_equal(a, b, equal_nan=True), name)


class Probabilistic(unittest.TestCase):
    def test_the_answer_does_not_depend_on_the_workers(self) -> None:
        m = kp.Model.from_dict(example('biosphere'))
        m.simulation.update(output_points=20)
        a = m.run_probabilistic(12, seed=3, keep=['Dose'])
        b = m.run_probabilistic(12, seed=3, keep=['Dose'], workers=2)
        label = a.labels[0]
        self.assertEqual(a.realisations(label).shape, (12, 20))
        self.assertTrue(np.array_equal(a.realisations(label), b.realisations(label), equal_nan=True))
        q = a.quantiles(label)
        self.assertEqual(len(q), 3)


class SensitivityAndCalibration(unittest.TestCase):
    def test_local_sensitivity_is_the_derivative(self) -> None:
        s = two_boxes().local_sensitivity(['k'])
        t = np.asarray(s['t'])
        b = next(st.base for st in s['states'] if st.name == 'B')  # the state's place in y
        # dB/dk = 100 t e^-kt
        got = np.asarray(s['sens'][0][b])
        want = 100 * t * np.exp(-0.1 * t)
        self.assertTrue(np.allclose(got, want, rtol=1e-4, atol=1e-6))

    def test_calibration_finds_the_rate(self) -> None:
        m = two_boxes(k=1.0)
        want = 100 * (1 - math.exp(-1.0))  # what k = 0.1 gives
        cal = m.calibrate([{'output': 'B', 'when': 'end', 'value': want}],
                          [{'key': 'k', 'lower': 1e-3, 'upper': 10, 'space': 'log'}],
                          max_evals=200, apply=True)
        self.assertTrue(cal['matched'], cal)
        self.assertAlmostEqual(m['k'].value, 0.1, delta=1e-3)

    def test_put_values(self) -> None:
        m = kp.Model.from_dict(example('biosphere'))
        self.assertEqual(m.put_values([{'key': 'Kd[I-129]', 'value': 0.25}, {'key': 'geoTransit', 'value': 7},
                                       {'key': 'Missing', 'value': 1}, {'key': 'Kd[I-129]', 'value': math.nan}]), 2)
        self.assertEqual(float(m['Kd'].value_at('I-129')), 0.25)
        self.assertEqual(float(m['geoTransit'].value), 7.0)


class Files(unittest.TestCase):
    def test_a_saved_run_opens_again(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            res = kp.Model.from_dict(example('recorders')).run()
            res.save(Path(d) / 'run.zip')
            back = kp.load_results(Path(d) / 'run.zip')
            for label in res.labels:
                self.assertTrue(np.array_equal(back[label], res[label], equal_nan=True), label)
            data = res.to_hdf5(Path(d) / 'run.h5')
            self.assertEqual(data[:8], b'\x89HDF\r\n\x1a\n')
            self.assertEqual((Path(d) / 'run.h5').read_bytes(), data)

    def test_data_goes_out_and_comes_back(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            m = kp.Model.from_dict(example('biosphere'))
            for suffix in ('.xlsx', '.h5'):
                path = Path(d) / f'data{suffix}'
                m.export_data(path)
                edited = kp.Model.from_dict(example('biosphere'))
                edited['Kd'].set_value(99.0, at='I-129')
                report = edited.import_data(path)
                self.assertEqual(report.values, len(m.data_rows()), suffix)
                self.assertEqual(float(edited['Kd'].value_at('I-129')), float(m['Kd'].value_at('I-129')))
                self.assertIn('values', str(report))
            with self.assertRaises(kp.EditError):
                m.export_data(Path(d) / 'data.csv')


if __name__ == '__main__':
    unittest.main()
