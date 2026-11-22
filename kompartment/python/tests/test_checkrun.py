"""Check the run against the application's own (``src/sim/checkrun.js``).

The application's code runs through Node (``tests/node/checkrun.mjs``) beside
:mod:`kompartment.engine.checkrun`. What involves no run is compared exactly:
what each state is called on every bundled example, the careful run's model,
and the comparison of two runs -- on the application's own two runs of an
example, and on runs made up to reach every rule (a state not a number in one
run, infinite in one, in both, a careful run at other times, a state under the
run's absolute tolerance, shares that tie). A check made here, with runs of its
own, is compared to the margin the runs agree to: the verdict and the states
named exactly, the worst share to 1e-2 relatively (the careful runs' steps can
part, and a share is a difference of two runs over a state's size).
"""

from __future__ import annotations

import json
import math
import subprocess
import unittest
from pathlib import Path
from typing import Any, Dict, List

from helpers import EXAMPLES, NODE, SRC, example, needs_app

from kompartment.engine.builder import build_system
from kompartment.engine.checkrun import CAREFUL, HOLDS, NEARLY, RTOL_FLOOR, check_run, compare_runs, state_labels, \
    tighten_tolerances
from kompartment.engine.project import Project
from kompartment.engine.runner import run

SCRIPT = Path(__file__).resolve().parent / 'node' / 'checkrun.mjs'
_SPECIAL = {'NaN': math.nan, 'Infinity': math.inf, '-Infinity': -math.inf}


def _enc(x: Any) -> Any:
    if isinstance(x, float):
        if x != x:
            return {'$': 'NaN'}
        if math.isinf(x):
            return {'$': 'Infinity' if x > 0 else '-Infinity'}
        return x
    if isinstance(x, (list, tuple)):
        return [_enc(v) for v in x]
    if isinstance(x, dict):
        return {k: _enc(v) for k, v in x.items()}
    return x


def _dec(x: Any) -> Any:
    if isinstance(x, list):
        return [_dec(v) for v in x]
    if isinstance(x, dict):
        if list(x) == ['$']:
            return _SPECIAL[x['$']]
        return {k: _dec(v) for k, v in x.items()}
    return x


def app(task: str, **request: Any) -> Any:
    """Asks the application (see ``tests/node/checkrun.mjs``)."""
    proc = subprocess.run([NODE, str(SCRIPT), str(SRC)], input=json.dumps(_enc({'task': task, **request})),
                          capture_output=True, text=True, timeout=900, encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(proc.stderr[-3000:])
    return _dec(json.loads(proc.stdout))


class _Run:
    """A run as the comparison reads one: the project and system, the times and a row per time."""

    def __init__(self, project: Any, system: Any, t: List[float], y: List[List[float]]) -> None:
        self.project, self.system, self.t, self.y, self.stats = project, system, t, y, {}


def same(a: Any, b: Any) -> bool:
    """Equal, NaN equal to NaN, a number by its value whatever its type."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return (a != a and b != b) or float(a) == float(b)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(same(a[k], b[k]) for k in a)
    return a == b


REPORT_KEYS = ('verdict', 'worst', 'moved', 'states', 'times', 'sameTimes')


class Standalone(unittest.TestCase):
    def test_the_careful_run_is_a_hundred_times_tighter(self) -> None:
        m = {'simulation': {'rtol': 1e-6, 'abstol': 1e-9, 'max_steps': 5000},
             'compartments': [{'name': 'A', 'abstol': 1e-3, 'entries': [{'abstol': '1e-4'}, {'abstol': ''}]}]}
        said = tighten_tolerances(m)
        self.assertEqual(said, {'rtol': 1e-6 / CAREFUL, 'abstol': 1e-9 / CAREFUL, 'floor': False})
        self.assertEqual((m['simulation']['max_steps'], m['compartments'][0]['abstol']), (50000.0, 1e-3 / CAREFUL))
        self.assertEqual([e['abstol'] for e in m['compartments'][0]['entries']], [1e-4 / CAREFUL, ''])
        self.assertTrue(tighten_tolerances({'simulation': {'rtol': 1e-11, 'abstol': 1}})['floor'])
        self.assertEqual(tighten_tolerances({'simulation': {'rtol': 1e-11, 'abstol': 1}})['rtol'], RTOL_FLOOR)
        self.assertEqual((HOLDS, NEARLY), (1e-3, 1e-2))

    def test_a_run_without_its_states_is_refused(self) -> None:
        held = run(Project(example('four-compartment')))
        held.y = held.y[:-1]
        with self.assertRaisesRegex(ValueError, 'does not carry its states'):
            check_run(held, lambda p: run(p))

    def test_a_run_set_against_itself_holds_exactly(self) -> None:
        held = run(Project(example('decay-chain')))
        r = compare_runs(held, held)
        self.assertEqual((r['verdict'], r['worst'], r['moved'], r['sameTimes']), ('holds', 0.0, [], True))


@needs_app
class AgainstTheApplication(unittest.TestCase):
    def test_what_each_state_is_called(self) -> None:
        names = sorted(f.stem for f in EXAMPLES.glob('*.json'))
        models = [example(n) for n in names]
        theirs = app('labels', models=models)['labels']
        for name, model, want in zip(names, models, theirs):
            with self.subTest(example=name):
                self.assertEqual(state_labels(build_system(Project(model)).layout), want)

    def test_the_careful_runs_model(self) -> None:
        sim = {'rtol': 1e-3, 'abstol': 1e-6}
        models = [
            {'simulation': dict(sim)},
            {'simulation': {**sim, 'max_steps': 5000}},
            {'simulation': {**sim, 'max_steps': '700'}},
            {'simulation': {**sim, 'max_steps': ''}},
            {'simulation': {**sim, 'max_steps': 0}},
            {'simulation': {**sim, 'max_steps': -3}},
            {'simulation': {**sim, 'max_steps': 'abc'}},
            {'simulation': {**sim, 'max_steps': 12.25}},
            {'simulation': {'rtol': 1e-11, 'abstol': 1e-20}},
            {'simulation': {'rtol': '1e-4', 'abstol': '1e-8'}},
            {'simulation': {'abstol': 1e-8}},
            {'simulation': {'rtol': None, 'abstol': None}},
            {},
            {'simulation': dict(sim),
             'compartments': [{'name': 'A', 'abstol': 1e-3}, {'name': 'B', 'abstol': '2e-5'}, {'name': 'C', 'abstol': ''},
                              {'name': 'D', 'abstol': 0}, {'name': 'E', 'abstol': None}, {'name': 'F', 'abstol': 'x'},
                              {'name': 'G', 'entries': [{'abstol': 1e-2}, {'abstol': '-1'}, {}, None]}],
             'waste_packages': [{'name': 'W', 'abstol': 4e-6, 'entries': [{'abstol': '3e-7'}]}]},
        ]
        theirs = app('tighten', models=models)['cases']
        for model, want in zip(models, theirs):
            with self.subTest(model=model):
                mine = json.loads(json.dumps(model))
                said = tighten_tolerances(mine)
                self.assertTrue(same(said, want['said']), (said, want['said']))
                self.assertTrue(same(mine, want['model']), (mine, want['model']))

    def test_two_runs_compared_as_the_application_compares_them(self) -> None:
        """On the application's own run of an example and its careful run: the
        same report, to the bit."""
        for name in ('four-compartment', 'waste-packages', 'farfield', 'landscape'):
            with self.subTest(example=name):
                m = example(name)
                js = app('check', model=m)
                project = Project(m)
                system = build_system(project)
                held = _Run(project, system, js['held']['t'], js['held']['y'])
                careful = _Run(project, system, js['careful']['t'], js['careful']['y'])
                mine = compare_runs(held, careful)
                self.assertTrue(same(mine, {k: js['report'][k] for k in REPORT_KEYS}), (mine, js['report']))

    def test_runs_made_up_to_reach_every_rule(self) -> None:
        """A state not a number in one run, infinite in one, in both; one that
        never moves; one under the absolute tolerance over the relative; shares
        that tie; and a careful run whose times are not the run's."""
        m = {'name': 'made up', 'simulation': {'start_time': 0, 'end_time': 3, 'output_points': 4, 'spacing': 'linear',
                                                'rtol': 1e-3, 'abstol': 1e-6},
             'compartments': [{'name': n, 'initial': '1', 'unit': 'Bq', 'index_lists': []}
                              for n in ('A', 'B', 'C', 'D', 'E', 'F', 'G', 'H')]}
        nan, inf = math.nan, math.inf
        t = [0.0, 1.0, 2.0, 3.0]
        held = [[1, 2, 3, 1e-5, 0, 5, 5, 1],
                [1, 2, nan, 2e-5, 0, 5, 5, inf],
                [1, nan, 3, 1e-5, 0, 6, 6, inf],
                [1, 2, nan, 1e-5, 0, 7, 7, 1]]
        careful = [[1, 2, 3, 1e-5, 0, 5, 5, 1],
                   [1.001, 2, 3, 2.0001e-5, 0, 5.5, 5.5, 1],
                   [1, 2, nan, 1e-5, 0, 6, 6, inf],
                   [1, 2, 4, 3e-5, 0, 7, 7, 2]]
        project = Project(m)
        system = build_system(project)
        cases = [
            (t, held, t, careful),
            # Times the careful run does not have, read at the nearest it does.
            (t, held, [0.0, 0.9, 1.6, 2.4, 3.0], careful + [careful[-1]]),
            (t, held, [0.0, 1.5, 3.0], [careful[0], careful[1], careful[3]]),
        ]
        for ht, hy, ct, cy in cases:
            with self.subTest(careful_times=ct):
                theirs = app('compare', model=m, held={'t': ht, 'y': hy}, careful={'t': ct, 'y': cy})['report']
                mine = compare_runs(_Run(project, system, ht, hy), _Run(project, system, ct, cy))
                self.assertTrue(same(mine, theirs), (mine, theirs))

    def test_a_check_made_here_beside_the_applications(self) -> None:
        for name in ('four-compartment', 'decay-chain', 'biosphere'):
            with self.subTest(example=name):
                m = example(name)
                # Solved whole, as the application solves it here: a split into
                # parts follows what earlier runs measured, and takes other steps.
                m['simulation']['split'] = 'off'
                js = app('check', model=m)['report']
                mine = check_run(run(Project(m)), lambda p: run(p))
                self.assertEqual(mine['verdict'], js['verdict'])
                self.assertEqual([x['label'] for x in mine['moved']], [x['label'] for x in js['moved']])
                self.assertLess(abs(mine['worst'] - js['worst']), 1e-2 * max(mine['worst'], js['worst']))
                for key in ('rtol', 'abstol', 'floor', 'maxSteps'):
                    self.assertTrue(same(mine['careful'][key], js['careful'][key]), key)
                self.assertTrue(same(mine['run']['rtol'], js['run']['rtol']))
                self.assertEqual((mine['states'], mine['times'], mine['sameTimes']),
                                 (js['states'], js['times'], js['sameTimes']))


if __name__ == '__main__':
    unittest.main()
