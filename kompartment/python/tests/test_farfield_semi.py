"""A far-field path worked out semi-analytically: the engine against the application, and against
its own analytic answers.

The application's ``LaplaceFarfPath`` (src/sim/farfield-laplace.js) and the engine's
(:mod:`kompartment.engine.farfield_semi`) record the same history and convolve it with the same
responses; the engine sums the history with numpy, so the two agree to rounding rather than to the
bit, and a run to within the solver's own tolerance. Every model here is made up.
"""

from __future__ import annotations

import copy
import math
import unittest
from typing import Any, Dict, Tuple

import numpy as np

from helpers import example, needs_app
from test_engine_lang import engine, number

from kompartment.engine import farfield_laplace as L
from kompartment.engine.builder import BuildError, build_system
from kompartment.engine.project import Project
from kompartment.engine.runner import Results, run


def semi_model(**changes: Any) -> Dict[str, Any]:
    """Waste packages failing at once into a near field that leaches into the path, a source
    switched on part way, a branching chain with sorption on the fracture surfaces, and a
    compartment downstream."""
    m: Dict[str, Any] = {
        'name': 'semi',
        'simulation': {'start_time': 0, 'end_time': 3e4, 'output_points': 40, 'spacing': 'log',
                       'solver': 'ndf', 'rtol': 1e-8, 'abstol': 1e-16, 'time_unit': 'year'},
        'nuclides': ['Aa-1', 'Bb-2', 'Cc-3'], 'half_lives': {'Aa-1': 2000, 'Bb-2': 800, 'Cc-3': 5000},
        'chains': [['Aa-1', 'Bb-2', 0.6], ['Aa-1', 'Cc-3', 0.4]], 'decay_unit': 'mol',
        'waste_packages': [{'name': 'Pack', 'index_lists': ['Radionuclides'], 'failure': 'at', 'fail_at': '700',
                            'inventory': '0', 'irf': '0.2', 'degradation_rate': '2e-3', 'handle_decay': True,
                            'entries': [{'index': {'Radionuclides': 'Aa-1'}, 'inventory': '1000'}]}],
        'compartments': [{'name': 'Near', 'initial': '0', 'index_lists': ['Radionuclides']},
                         {'name': 'Down', 'initial': '0', 'index_lists': ['Radionuclides']}],
        'transfers': [{'name': 'Carrier', 'from': 'Pack', 'to': 'Near', 'rate': 'Pack', 'multiply_by_donor': False,
                       'index_lists': ['Radionuclides']},
                      {'name': 'Leach', 'from': 'Near', 'to': 'Rock', 'rate': '1e-3', 'multiply_by_donor': True},
                      {'name': 'Out', 'from': 'Rock', 'to': 'Down', 'rate': 'Rock', 'multiply_by_donor': False,
                       'index_lists': ['Radionuclides']}],
        'inflows': [{'name': 'Drip', 'to': 'Rock', 'rate': '1e-3 * (time() > 2000)',
                     'index_lists': ['Radionuclides']}],
        'farfields': [{'name': 'Rock', 'index_lists': ['Radionuclides'], 'method': 'semi-analytical',
                       'surface': 'f', 'tw': '50', 'f': '5e4', 'kd_f': '2e-4', 'kd_m': '1e-3', 'de_m': '1e-4',
                       'eps_m': '0.005', 'rho_m': '2700', 'pe': '10', 'pen_dep': '0.1', 'pen_dep_0': '',
                       'n_f': 20, 'n_m': 20, 'o_b': 4, 'n_b': '', 'grid': 'matched', 'handle_decay': True,
                       'report_cells': False,
                       'entries': [{'index': {'Radionuclides': 'Bb-2'}, 'kd_f': '5e-4', 'kd_m': '3e-3',
                                    'de_m': '2e-4'},
                                   {'index': {'Radionuclides': 'Cc-3'}, 'kd_f': '1e-4', 'kd_m': '5e-4'}]}],
    }
    for key, value in changes.items():
        m[key] = value
    return m


def leaching_model(k: float = 1e-3, lam_half: float = 3000.0) -> Dict[str, Any]:
    """One nuclide leaching out of a compartment into the path: the inflow is k A0 e^-(k+lambda)t."""
    return {
        'name': 'leaching',
        'simulation': {'start_time': 0, 'end_time': 2e4, 'spacing': 'series',
                       'output_times': [{'kind': 'times', 'times': [100 * 200 ** (q / 29) for q in range(30)]}],
                       'solver': 'ndf', 'rtol': 1e-9, 'abstol': 1e-16, 'time_unit': 'year'},
        'nuclides': ['Xx-1'], 'half_lives': {'Xx-1': lam_half}, 'decay_unit': 'mol',
        'compartments': [{'name': 'Near', 'initial': '1000', 'index_lists': ['Radionuclides']},
                         {'name': 'Down', 'initial': '0', 'index_lists': ['Radionuclides']}],
        'transfers': [{'name': 'Leach', 'from': 'Near', 'to': 'Rock', 'rate': repr(k), 'multiply_by_donor': True},
                      {'name': 'Out', 'from': 'Rock', 'to': 'Down', 'rate': 'Rock', 'multiply_by_donor': False,
                       'index_lists': ['Radionuclides']}],
        'farfields': [{'name': 'Rock', 'index_lists': ['Radionuclides'], 'method': 'semi-analytical',
                       'surface': 'f', 'tw': '40', 'f': '4e4', 'kd_f': '5e-4', 'kd_m': '1e-3', 'de_m': '1e-4',
                       'eps_m': '0.005', 'rho_m': '2700', 'pe': '12', 'pen_dep': '0.2', 'pen_dep_0': '',
                       'n_f': 20, 'n_m': 20, 'o_b': 4, 'n_b': '', 'grid': 'matched', 'handle_decay': True,
                       'report_cells': False}],
    }


def numbers(values: Any) -> np.ndarray:
    return np.array([number(v) for v in values], dtype=float)


def common_rows(t_mine: np.ndarray, t_theirs: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """The rows of two runs at the times both have: a solver's own steps are not the other's."""
    a = np.round(np.asarray(t_mine, dtype=float), 9)
    b = np.round(np.asarray(t_theirs, dtype=float), 9)
    common = np.intersect1d(a, b)
    return np.isin(a, common), np.isin(b, common)


def worst_against(res: Results, js: Dict[str, Any], labels: Any = None) -> float:
    """The largest difference over the common rows, relative to each series' largest value."""
    mi, ji = common_rows(res.t, numbers(js['t']))
    worst = 0.0
    for label, a, b in zip(js['labels'], res.series_many(res.outputs()), js['columns']):
        if labels is not None and not any(s in label for s in labels):
            continue
        b = numbers(b)[ji]
        a = np.asarray(a)[mi]
        scale = float(np.max(np.abs(b))) if b.size else 0.0
        if scale > 0:
            worst = max(worst, float(np.max(np.abs(a - b))) / scale)
    return worst


@needs_app
class SemiParity(unittest.TestCase):
    def test_the_layout_and_the_derivative_are_the_applications(self) -> None:
        m = semi_model()
        js = engine('layout', model=m)
        self.assertNotIn('error', js, js.get('error'))
        s = build_system(Project(m), jacobian=False)
        self.assertEqual((s.nstate, s.nalg), (js['nstate'], js['nalg']))
        self.assertEqual([(e.name, e.base, e.width, e.kind) for e in s.layout.states],
                         [(e['name'], e['base'], e['width'], e['kind']) for e in js['states']])
        self.assertEqual([a.name for a in s.layout.algebraic], [a['name'] for a in js['algebraic']])
        self.assertEqual(list(np.asarray(s.layout.slot_class[:s.nalg])), list(js['slotClass'][:s.nalg]))
        # One state per nuclide for what the path holds.
        held = next(e for e in s.layout.states if e.kind == 'farfield')
        self.assertEqual(held.width, 3)
        rng = np.random.default_rng(11)
        points = [{'t': t, 'y': (rng.uniform(0, 1, s.nstate) * 10 ** rng.uniform(-3, 2, s.nstate)).tolist()}
                  for t in (0.0, 900.0, 2.5e3)]
        jd = engine('dydt', model=m, points=points)
        for p, q in zip(points, jd['points']):
            y = np.array(p['y'])
            X = s.evaluate_algebraic(p['t'], y).copy()
            np.testing.assert_allclose(X[:s.nalg], numbers(q['X'])[:s.nalg], rtol=1e-12, atol=0)
            np.testing.assert_allclose(s.dydt(p['t'], y), numbers(q['dydt']), rtol=1e-12, atol=1e-300)

    def test_df_dy_is_the_applications(self) -> None:
        m = semi_model()
        js = engine('jacobian', model=m)
        j = build_system(Project(m)).jacobian
        self.assertTrue(js['available'])
        self.assertEqual(bool(j.get('available')), js['available'], j.get('reason'))
        # The current inflow's weight changes from step to step: never constant.
        self.assertFalse(j.get('constant'))
        self.assertEqual(bool(j.get('constant')), js['constant'])
        self.assertEqual(j['pattern'].nnz, js['nnz'])
        self.assertEqual(len(j['groups']), js['colours'])

    def test_a_run_with_a_jump_a_switch_and_a_branch_is_the_applications(self) -> None:
        m = semi_model()
        js = engine('run', model=m)
        self.assertNotIn('error', js, js.get('error'))
        res = run(Project(m))
        self.assertEqual([o['label'] for o in res.outputs()], js['labels'])
        self.assertTrue(abs(res.stats['nsteps'] - js['stats']['nsteps']) <= max(2, 0.01 * js['stats']['nsteps']),
                        (res.stats['nsteps'], js['stats']['nsteps']))
        self.assertEqual(res.stats.get('jumps'), 1)
        self.assertLess(worst_against(res, js), 1e-8)

    def test_the_example_worked_out_semi_analytically_is_the_applications(self) -> None:
        m = example('farfield')
        m['farfields'][0]['method'] = 'semi-analytical'
        js = engine('run', model=m)
        self.assertNotIn('error', js, js.get('error'))
        res = run(Project(m))
        self.assertEqual([o['label'] for o in res.outputs()], js['labels'])
        self.assertLess(worst_against(res, js, labels=('Rock', 'Well', 'Vault')), 1e-10)

    def test_what_it_cannot_do_is_refused_as_the_application_refuses_it(self) -> None:
        cases = []
        clock = semi_model()
        clock['farfields'][0]['tw'] = '50 + time() / 1000'
        cases.append(('a travel time that follows the clock', clock, 'Tw follows the clock'))
        state = semi_model()
        state['farfields'][0]['f'] = '5e4 * (1 + Down[Aa-1])'
        cases.append(('a resistance that follows a compartment', state, 'F follows the state of the model'))
        half = semi_model()
        half['farfields'][0]['entries'][0]['de_m'] = '0'
        cases.append(('a daughter that does not diffuse', half, 'does not diffuse into the matrix'))
        loop = semi_model()
        loop['inflows'] = [{'name': 'Drip', 'to': 'Rock', 'rate': 'Rock * 0.5', 'index_lists': ['Radionuclides']}]
        cases.append(('an inflow that reads the release', loop, 'reads its own release at the same instant'))
        for what, m, said in cases:
            with self.subTest(what):
                js = engine('layout', model=m)
                self.assertIn('error', js, what)
                with self.assertRaises(BuildError) as caught:
                    build_system(Project(m))
                self.assertEqual(caught.exception.block_name, 'Rock')
                self.assertIn(said, str(caught.exception))
                self.assertEqual(str(caught.exception), js['error'])

    def test_a_split_run_is_refused_as_the_application_refuses_it(self) -> None:
        from kompartment.engine.localsens import uncarried
        from kompartment.engine.partition import partition_of
        m = semi_model()
        js = engine('partition', model=m)
        project = Project(m)
        system = build_system(project)
        p = partition_of(system)
        self.assertFalse(p['ok'])
        self.assertIn('semi-analytically', p['refusal'])
        self.assertEqual(p['refusal'], js['refusal'])
        # dy/dp: said for the path (the jump above would be said first).
        plain = Project(leaching_model())
        self.assertIn('semi-analytically', uncarried(plain, build_system(plain), []) or '')

    def test_a_sampled_travel_time_is_the_applications(self) -> None:
        from kompartment.engine.probabilistic import run_probabilistic
        m = leaching_model()
        m['parameters'] = [{'name': 'Tw', 'value': 50, 'index_lists': [],
                            'pdf': {'kind': 'unif', 'params': {'min': 30, 'max': 90}, 'values': None,
                                    'trmin': None, 'trmax': None, 'inorder': True, 'pos': 0}}]
        m['farfields'][0]['tw'] = 'Tw'
        js = engine('probabilistic', model=m, opts={'iterations': 3, 'seed': 7}, keep=['Rock'])
        self.assertNotIn('error', js, js.get('error'))
        mine = run_probabilistic(m, iterations=3, seed=7, keep=['Rock'])
        drawn = np.ravel(np.asarray(mine.samples, dtype=float))
        np.testing.assert_allclose(drawn, numbers(np.ravel(js['samples'])), rtol=1e-15)
        k = mine.labels.index('Rock [Xx-1]')
        kj = js['labels'].index('Rock [Xx-1]')
        a = np.ravel(np.asarray(mine.values[k], dtype=float))
        b = numbers(np.ravel(js['values'][kj]))
        self.assertEqual(a.shape, b.shape)
        # Three travel times, three sets of responses, each realisation the application's.
        self.assertEqual(len(set(drawn.tolist())), 3)
        self.assertLess(float(np.max(np.abs(a - b)) / np.max(np.abs(b))), 1e-7)


def plug_model() -> Dict[str, Any]:
    """Plug flow into a matrix without end (both written 1/0), fed by a leaching
    compartment: the response is mostly a point mass a hair after the delay."""
    times = [60 * (2e4 / 60) ** (q / 24) for q in range(25)]
    return {
        'name': 'plug flow',
        'simulation': {'start_time': 0, 'end_time': 2e4, 'spacing': 'series',
                       'output_times': [{'kind': 'times', 'times': times}],
                       'solver': 'ndf', 'rtol': 1e-9, 'abstol': 1e-16, 'time_unit': 'year'},
        'nuclides': ['Dd-1'], 'half_lives': {'Dd-1': 8.216e5}, 'decay_unit': 'mol',
        'compartments': [{'name': 'Near', 'initial': '1000', 'index_lists': ['Radionuclides']},
                         {'name': 'Down', 'initial': '0', 'index_lists': ['Radionuclides']}],
        'transfers': [{'name': 'Leach', 'from': 'Near', 'to': 'Rock', 'rate': '1e-3', 'multiply_by_donor': True},
                      {'name': 'Out', 'from': 'Rock', 'to': 'Down', 'rate': 'Rock', 'multiply_by_donor': False,
                       'index_lists': ['Radionuclides']}],
        'farfields': [{'name': 'Rock', 'index_lists': ['Radionuclides'], 'method': 'semi-analytical',
                       'surface': 'aw', 'tw': '50.27', 'aw': '0.3922', 'kd_f': '0', 'kd_m': '0', 'de_m': '1.508e-6',
                       'eps_m': '1.888e-4', 'rho_m': '2700', 'pe': '1/0', 'pen_dep': '1/0', 'pen_dep_0': '',
                       'n_f': 20, 'n_m': 20, 'o_b': 4, 'n_b': '', 'grid': 'matched', 'handle_decay': True,
                       'report_cells': False}],
    }


@needs_app
class PointMass(unittest.TestCase):
    def test_plug_flow_releases_its_point_mass_as_the_application_does(self) -> None:
        m = plug_model()
        js = engine('run', model=m)
        self.assertNotIn('error', js, js.get('error'))
        res = run(Project(m))
        self.assertLess(worst_against(res, js, labels=('Rock', 'Down', 'Near')), 1e-8)


class SemiEngine(unittest.TestCase):
    def test_the_compiled_path_says_why_it_is_not_taken(self) -> None:
        try:
            import numba  # noqa: F401
        except ImportError:
            self.skipTest('numba is not installed')
        from kompartment.engine.compiled import NotCompiled
        from kompartment.engine.compiled.run import prepare
        system = build_system(Project(leaching_model()))
        with self.assertRaises(NotCompiled) as caught:
            prepare(system, 'ndf', {})
        self.assertIn("'Rock' is worked out semi-analytically", str(caught.exception))
        res = run(Project(leaching_model()))
        self.assertFalse(res.stats['compiled'])
        self.assertIn('semi-analytically', res.stats['compiled_why'])

    def test_a_single_nuclide_is_its_inflow_convolved_exactly(self) -> None:
        k = 1e-3
        lam = math.log(2) / 3000
        res = run(Project(leaching_model(k)))
        path = L.prepare_path({'tw': 40, 'f': 4e4, 'rho_m': 2700, 'pe': 12, 'pen_dep': 0.2, 'kd_f': 5e-4,
                               'eps_m': 0.005, 'kd_m': 1e-3, 'de_m': 1e-4}, L.decay_table([lam]))
        r = L.unit_response(path, 0, 0, t_max=3e4)
        t = np.asarray(r['t'])
        h, dh, d2h = (np.asarray(r[key]) for key in ('h', 'dh', 'd2h'))
        x5 = np.array([-0.906179845938664, -0.5384693101056831, 0.0, 0.5384693101056831, 0.906179845938664])
        w5 = np.array([0.23692688505618908, 0.47862867049936647, 0.5688888888888889, 0.47862867049936647,
                       0.23692688505618908])

        def convolved(at: float) -> float:
            # Gauss-Legendre on each piece of the tabulated response, split finely enough for the
            # inflow's own exponential.
            total = 0.0
            for q in range(t.size - 1):
                a, b = t[q], min(t[q + 1], at)
                if not b > a:
                    break
                parts = max(1, int(math.ceil((b - a) * (k + lam) / 0.25)))
                d = t[q + 1] - t[q]
                for p in range(parts):
                    lo = a + (b - a) * p / parts
                    hi = a + (b - a) * (p + 1) / parts
                    u = 0.5 * (lo + hi) + 0.5 * (hi - lo) * x5
                    xx = (u - t[q]) / d
                    h0 = 1 - 10 * xx ** 3 + 15 * xx ** 4 - 6 * xx ** 5
                    h1 = xx - 6 * xx ** 3 + 8 * xx ** 4 - 3 * xx ** 5
                    h2 = 0.5 * (xx ** 2 - 3 * xx ** 3 + 3 * xx ** 4 - xx ** 5)
                    h4 = -4 * xx ** 3 + 7 * xx ** 4 - 3 * xx ** 5
                    h5 = 0.5 * (xx ** 3 - 2 * xx ** 4 + xx ** 5)
                    hv = (h0 * h[q] + d * h1 * dh[q] + d * d * h2 * d2h[q] + (1 - h0) * h[q + 1]
                          + d * h4 * dh[q + 1] + d * d * h5 * d2h[q + 1])
                    inflow = k * 1000 * np.exp(-(k + lam) * (at - u))
                    total += float(np.sum(0.5 * (hi - lo) * w5 * hv * inflow))
            return total

        out = next(o for o in res.outputs() if o['block'] == 'Rock')
        got = res.series(out)
        want = np.array([convolved(float(tt)) for tt in res.t])
        big = want > 1e-4 * want.max()
        self.assertGreater(int(big.sum()), 10)
        self.assertLess(float(np.max(np.abs(got[big] / want[big] - 1))), 1e-6)

    def test_plug_flow_releases_its_point_mass_exactly(self) -> None:
        # 29 % of the response comes before the first time it is tabulated
        # at: a point mass, released from the recorded inflow
        lam = math.log(2) / 8.216e5
        k = 1e-3
        res = run(Project(plug_model()))
        path = L.prepare_path({'surface': 'aw', 'aw': 0.3922, 'tw': 50.27, 'rho_m': 2700, 'pe': math.inf,
                               'pen_dep': math.inf, 'kd_f': 0, 'eps_m': 1.888e-4, 'kd_m': 0, 'de_m': 1.508e-6},
                              L.decay_table([lam]))
        r = L.unit_response(path, 0, 0, t_max=2e4)
        self.assertGreater(r['m0'], 0.2 * r['T0'])
        # the inflow as a piecewise-linear stand-in for the exponential, fine
        # enough (every half year) to be good to 3e-8
        ser = L.inflow_series([[0.5 * q, k * 1000 * math.exp(-(k + lam) * 0.5 * q)] for q in range(40001)])
        out = next(o for o in res.outputs() if o['block'] == 'Rock')
        got = res.series(out)
        want = [L.convolve(r, ser, float(t)) for t in res.t]
        big = [q for q, v in enumerate(want) if v > 1e-6 * max(want)]
        self.assertLess(max(abs(got[q] / want[q] - 1) for q in big), 1e-6)

    def test_a_response_that_misses_its_mass_balance_is_said(self) -> None:
        from kompartment.engine.runlog import run_log_lines
        path = L.prepare_path({'tw': 50, 'f': 5e4, 'rho_m': 2700, 'pe': 10, 'pen_dep': 0.1, 'kd_f': 2e-4,
                               'eps_m': 0.005, 'kd_m': 1e-3, 'de_m': 1e-4}, L.decay_table([math.log(2) / 3000]))
        good = L.unit_response(path, 0, 0)
        self.assertTrue(good['balanced'] and good['rel'] < 1e-8, good['rel'])
        bad = L.unit_response(path, 0, 0, per_decade=1, max_pts=12)
        self.assertTrue(bad['balanced'] is False and bad['rel'] > 1e-5, bad['rel'])
        system = build_system(Project(leaching_model()))
        F = system.laplace[0]
        F.combos = [{'kernels': [], 'pairs': 0,
                     'misses': [{'i': 0, 'j': 0, 'integral': 0.5, 'expected': 0.9, 'T0': 1.0, 'rel': 0.4, 'until': 1e4}]}]
        said = F.balance_warnings()
        self.assertEqual(said, [{'block': 'Rock', 'message': 'the unit response of Xx-1 to Xx-1 integrates to 0.5000, '
                                 'but 0.9000 of a pulse leaves the path by 1.000e+4 (T(0) = 1.000): the inversion '
                                 'failed there, and the release worked out from it is not reliable'}])
        lines = run_log_lines({'name': 'x', 'simulation': {}}, {'stats': {'farfield': said}})
        self.assertIn('semi-analytical far-field paths: 1 unit response missed its mass balance', lines)
        self.assertIn(f"  Rock: {said[0]['message']}", lines)

    def test_what_is_held_delivered_and_left_upstream_add_up(self) -> None:
        # Stable species, so nothing decays: the packages held 1000 of Aa-1, and the drip adds
        # 1e-3 a year of each of the three after 2000 years. Every amount is somewhere.
        m = semi_model(half_lives={'Aa-1': 'stable', 'Bb-2': 'stable', 'Cc-3': 'stable'}, chains=[])
        res = run(Project(m))
        total = np.zeros(res.t.size)
        for o in res.outputs():
            if o['block'] in ('Pack intact', 'Pack exposed', 'Near', 'Down', 'Rock held'):
                total += res.series(o)
        want = 1000 + 3e-3 * np.maximum(res.t - 2000, 0)
        self.assertLess(float(np.max(np.abs(total / want - 1))), 1e-7)
        # ...and it is not trivially so: by the end most of it has come through.
        down = sum(res.series(o)[-1] for o in res.outputs() if o['block'] == 'Down')
        self.assertGreater(down, 500)

    def test_a_run_read_back_in_another_system_reports_the_same_release(self) -> None:
        project = Project(semi_model())
        res = run(project)
        state = res.system.run_state()
        other = build_system(Project(semi_model()))
        other.restore_run_state(state)
        again = Results(Project(semi_model()), other, {'t': res.t, 'y': res.y, 'stats': dict(res.stats)}, {})
        for o in res.outputs():
            if o['block'] != 'Rock':
                continue
            a = res.series(o)
            b = again.series(next(x for x in again.outputs() if x['label'] == o['label']))
            np.testing.assert_allclose(b, a, rtol=1e-12, atol=1e-300)


if __name__ == '__main__':
    unittest.main()
