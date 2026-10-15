"""Steps that end on the turns of a table rather than pass over a pulse
(``kompartment.engine.landing``; ``src/sim/landing.js`` in the application).

A table read at the clock that rises and falls back between two steps used to
go unseen under every solver but ``auto``: a pulse after a time of none arrived
as nothing, a spike on a steady release as the steady release alone. These
tests pin the rule (where a step ends, by interpolation rule, and that a wiggle
does not move it), that the application ends every step at the same time on
the same tables, that every solver now delivers what the table puts out, and
that the compiled loops land where the Python ones do, to the last bit.
"""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import numpy as np

from helpers import HERE, NODE, SRC, example, needs_app

import kompartment as kp
from kompartment.engine.builder import build_system
from kompartment.engine.landing import table_landing
from kompartment.engine.project import Project

try:
    import numba  # noqa: F401
    from kompartment.engine.compiled import loop_refusal
    HAVE_NUMBA = loop_refusal() is None
except Exception:  # noqa: BLE001 - optional
    HAVE_NUMBA = False

needs_numba = unittest.skipUnless(HAVE_NUMBA, 'the compiled path needs numba 0.62 or later')

SOLVERS = ('ndf', 'ros23', 'dp45', 'auto', 'auto_julia', 'rodas5p', 'radau5', 'fbdf', 'fbdf_krylov', 'qndf',
           'kencarp4', 'trbdf2', 'rosenbrock23', 'tsit5', 'vern7')

PULSES = (
    ('a pulse at 1e4 after none', [[0, 0], [1e4, 0], [1e4 + 10, 1], [1e4 + 20, 0], [1e6, 0]]),
    ('a pulse at 3e5 after none', [[0, 0], [3e5, 0], [3e5 + 10, 1], [3e5 + 20, 0], [1e6, 0]]),
    ('a spike on a steady release', [[0, 1e-6], [1e4, 1e-6], [1e4 + 10, 1], [1e4 + 20, 1e-6], [1e6, 1e-6]]),
)


def pulse_model(points: List[List[float]], solver: str) -> Dict[str, Any]:
    """Feed -> A at the table's rate, A -> Out slowly: whatever the table puts
    out is in A and Out at the end."""
    return {
        'name': 'pulse',
        'simulation': {'start_time': 0, 'end_time': 1e6, 'output_points': 50, 'spacing': 'log',
                       'solver': solver, 'rtol': 1e-6, 'abstol': 1e-9, 'time_unit': 'year'},
        'lookups': [{'name': 'release', 'interpolation': 'linear', 'points': points}],
        'compartments': [{'name': 'Feed', 'initial': '1000'}, {'name': 'A', 'initial': '0'},
                         {'name': 'Out', 'initial': '0'}],
        'transfers': [{'name': 'in', 'from': 'Feed', 'to': 'A', 'rate': 'release', 'multiply_by_donor': False},
                      {'name': 'drain', 'from': 'A', 'to': 'Out', 'rate': '1e-3'}],
    }


def integral(points: List[List[float]]) -> float:
    return sum((points[i][0] - points[i - 1][0]) * (points[i][1] + points[i - 1][1]) / 2
               for i in range(1, len(points)))


def run_model(model: Dict[str, Any], compiled: bool) -> Any:
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'model.json'
        path.write_text(json.dumps(model), encoding='utf-8')
        return kp.run(kp.load(str(path)), compiled=compiled)


def engine(task: str, **request: Any) -> Dict[str, Any]:
    """Asks the application's engine (see tests/node/engine.mjs)."""
    def enc(x: Any) -> Any:
        if isinstance(x, float) and not math.isfinite(x):
            return 'NaN' if x != x else ('Infinity' if x > 0 else '-Infinity')
        if isinstance(x, dict):
            return {k: enc(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [enc(v) for v in x]
        return x

    def dec(x: Any) -> Any:
        if x == 'NaN':
            return math.nan
        if x == 'Infinity':
            return math.inf
        if x == '-Infinity':
            return -math.inf
        if isinstance(x, dict):
            return {k: dec(v) for k, v in x.items()}
        if isinstance(x, list):
            return [dec(v) for v in x]
        return x

    assert NODE is not None
    proc = subprocess.run([NODE, str(HERE / 'node' / 'engine.mjs'), str(SRC)],
                          input=json.dumps(enc({'task': task, **request})), capture_output=True, text=True,
                          timeout=900, encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return dec(json.loads(proc.stdout))


def table(points: List[List[float]], interpolation: str = 'linear') -> Any:
    return SimpleNamespace(x=[p[0] for p in points], y=[p[1] for p in points], interpolation=interpolation)


def same(a: float, b: float) -> bool:
    return (a != a and b != b) or a == b


class TheRule(unittest.TestCase):
    """Where a step ends: the application's test of ``tableLanding``, in Python."""

    def test_where_a_step_ends(self) -> None:
        pulse = [[0, 0], [10, 0], [20, 1], [30, 0], [100, 0]]
        land = table_landing([table(pulse)], 1e-3)
        self.assertEqual(land(0, 1000), 20)
        self.assertTrue(math.isnan(land(0, 25)), 'a step that ends inside the pulse sees it')
        self.assertEqual(land(15, 1000), 30, 'the pulse meets zero again: a turn of its own')
        self.assertTrue(math.isnan(land(25, 1000)))
        self.assertTrue(math.isnan(land(1000, 0)), 'a step backwards lands nowhere')
        self.assertEqual(table_landing([table(pulse, 'below')], 1e-3)(0, 1000), 25)
        self.assertEqual(table_landing([table(pulse, 'above')], 1e-3)(0, 1000), 15)
        self.assertEqual(table_landing([table(pulse, 'nearest')], 1e-3)(0, 1000), 20)
        self.assertEqual(table_landing([table([[0, 1], [10, 1], [20, 0], [30, 1], [100, 1]])], 1e-3)(0, 1000), 20,
                         'a dip')
        land = table_landing([table([[0, 1], [10, 1], [20, 1 + 1e-7], [30, 1], [1e4, 1]])], 1e-3)
        self.assertTrue(math.isnan(land(0, 1e4)), 'a wiggle')
        land = table_landing([table([[0, 0], [500, 0], [510, 1], [520, 0]]), table(pulse)], 1e-3)
        self.assertEqual((land(0, 1000), land(25, 1000)), (20, 510))
        noisy = [[0.0, 1.0]] + [[float(i), 1 + (1e-6 if i % 2 else 0.0)] for i in range(1, 401)]
        noisy += [[410, 1], [420, 50], [430, 1], [1000, 1]]
        land = table_landing([table(noisy)], 1e-3)
        self.assertEqual(land(0, 1000), 420)
        self.assertTrue(math.isnan(land(0, 405)), 'only the small turns')
        self.assertIsNone(table_landing([table([[0, 0], [10, 1], [20, 2]]), table([[0, 5], [1, 5]])], 1e-3))

    def test_a_model_gets_one_only_where_a_table_turns(self) -> None:
        base = {'name': 'turns', 'simulation': {'start_time': 0, 'end_time': 100, 'output_points': 11,
                                                'spacing': 'linear', 'rtol': 1e-6, 'abstol': 1e-9},
                'compartments': [{'name': 'A', 'initial': '1'}],
                'transfers': [{'name': 'T', 'from': 'A', 'to': None, 'rate': '1e-3'}]}
        self.assertIsNone(build_system(Project(base), jacobian=False).table_landing(1e-6))
        base['transfers'] = [{'name': 'T', 'from': 'A', 'to': None, 'rate': 'L * 1e-3'}]
        rising = {**base, 'lookups': [{'name': 'L', 'interpolation': 'linear', 'points': [[0, 1], [50, 2], [100, 3]]}]}
        self.assertIsNone(build_system(Project(rising), jacobian=False).table_landing(1e-6))
        turning = {**base, 'lookups': [{'name': 'L', 'interpolation': 'linear', 'points': [[0, 1], [50, 9], [100, 1]]}]}
        self.assertEqual(build_system(Project(turning), jacobian=False).table_landing(1e-6)(0, 100), 50)
        cyclic = {**base, 'lookups': [{**turning['lookups'][0], 'cyclic': True}]}
        self.assertIsNone(build_system(Project(cyclic), jacobian=False).table_landing(1e-6))


@needs_app
class TheApplications(unittest.TestCase):
    """Every step ends where the application's would, on the same tables."""

    def test_the_same_times(self) -> None:
        noisy = [[0.0, 1.0]] + [[float(i), 1 + (1e-6 if i % 2 else 0.0)] for i in range(1, 401)]
        noisy += [[410, 1], [420, 50], [430, 1], [1000, 1]]
        model = {
            'name': 'landing', 'simulation': {'start_time': 0, 'end_time': 1000, 'output_points': 11,
                                              'spacing': 'linear', 'rtol': 1e-6, 'abstol': 1e-9},
            'compartments': [{'name': 'A', 'initial': '1'}],
            'transfers': [{'name': 'T', 'from': 'A', 'to': None,
                           'rate': '(L1 + L2 + L3 + L4 + L5 + L6) * 1e-3'}],
            'lookups': [
                {'name': 'L1', 'interpolation': 'linear', 'points': [[0, 0], [10, 0], [20, 1], [30, 0], [100, 0]]},
                {'name': 'L2', 'interpolation': 'below', 'points': [[0, 0], [40, 0], [50, 3], [60, 0], [200, 0]]},
                {'name': 'L3', 'interpolation': 'above', 'points': [[0, 2], [70, 2], [80, 0.5], [90, 2], [300, 2]]},
                {'name': 'L4', 'interpolation': 'nearest', 'points': [[0, 1], [5, 1], [15, 4], [25, 1], [99, 1]]},
                {'name': 'L5', 'interpolation': 'extrapolate', 'points': noisy},
                {'name': 'L6', 'interpolation': 'linear', 'cyclic': True, 'points': [[0, 0], [10, 1], [25, 0]]},
            ],
        }
        steps = [[0, 1000], [0, 25], [15, 1000], [25, 1000], [0, 405], [45, 1000], [55, 1000], [60, 75],
                 [0, 0.5], [419, 1000], [1000, 0], [-50, 2000], [100, 100], [0, 1e9]]
        for rtol in (1e-3, 1e-6, 1e-9):
            with self.subTest(rtol=rtol):
                js = engine('landing', model=model, rtol=rtol, steps=steps)['landing']
                land = build_system(Project(json.loads(json.dumps(model))), jacobian=False).table_landing(rtol)
                mine = [land(t, tn) for t, tn in steps]
                self.assertTrue(all(same(a, b) for a, b in zip(mine, js)), f'{mine}\n{js}')
        for name in ('lookup-driver', 'recorders', 'post-processing'):
            with self.subTest(model=name):
                m = example(name)
                end = float(m['simulation']['end_time'])
                start = float(m['simulation'].get('start_time') or 0)
                spans = [[start + (end - start) * i / 40, start + (end - start) * (i + j) / 40]
                         for i in range(40) for j in (1, 3, 9, 40)]
                js = engine('landing', model=m, rtol=1e-6, steps=spans)['landing']
                land = build_system(Project(json.loads(json.dumps(m))), jacobian=False).table_landing(1e-6)
                if js is None:
                    self.assertIsNone(land)
                    continue
                mine = [land(t, tn) for t, tn in spans]
                self.assertTrue(all(same(a, b) for a, b in zip(mine, js)), f'{mine}\n{js}')


class EverySolver(unittest.TestCase):
    """What a table puts out reaches the model, under every solver."""

    def test_the_pulses_arrive(self) -> None:
        for what, points in PULSES:
            total = integral(points)
            for solver in SOLVERS:
                with self.subTest(what=what, solver=solver):
                    r = run_model(pulse_model(points, solver), compiled=False)
                    got = float(r.series('A')[-1]) + float(r.series('Out')[-1])
                    self.assertLess(abs(got / total - 1), 1e-3, f'{got} of {total}')


@needs_numba
class Compiled(unittest.TestCase):
    """The compiled loops end their steps where the Python ones do."""

    def test_the_same_runs(self) -> None:
        for what, points in PULSES:
            for solver in SOLVERS:
                with self.subTest(what=what, solver=solver):
                    model = pulse_model(points, solver)
                    a = run_model(model, compiled=False)
                    b = run_model(model, compiled=True)
                    self.assertTrue(b.stats.get('compiled_loop'), b.stats.get('compiled_loop_why'))
                    self.assertEqual(a.stats['nsteps'], b.stats['nsteps'])
                    for block in ('Feed', 'A', 'Out'):
                        self.assertTrue(np.array_equal(np.asarray(a.series(block)), np.asarray(b.series(block))),
                                        block)


if __name__ == '__main__':
    unittest.main()
