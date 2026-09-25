"""The engine against the application's: projects, built systems, and runs.

Every bundled example is built and run by both, and compared:

* the Project the model loads into, field by field;
* the built system's layout (every state, parameter and algebraic slot at the
  same offset, the same dependency order, the same slot classes), and its
  values: parameters, initial state, algebraic slots and the derivative at
  random states and times;
* a run: the same number of solver steps, to within a percent, and every
  reported series within a small multiple of the run's own tolerance.

A run cannot be the application's to the last bit even where its derivative
is: the solvers choose each step size with a power, ``(rtol/err)**(1/(k+1))``,
and V8's ``Math.pow`` rounds differently from the C library's in the last
place for about one argument in ten. The step sequences part in the last
digits after a few steps and usually end on the same count, not always.
"""

from __future__ import annotations

import math
import unittest
from typing import Any, Dict, List

import numpy as np

from helpers import example, needs_app
from test_engine_lang import engine, number

from kompartment.engine.builder import build_system
from kompartment.engine.project import BLOCK_COLLECTIONS, Project
from kompartment.engine.runner import run

EXAMPLES = ['four-compartment', 'decay-chain', 'biosphere', 'lookup-driver', 'post-processing', 'scenarios',
            'landscape', 'recorders', 'farfield', 'waste-packages']

#: Examples whose derivative cannot be the application's to the last bit: the
#: far-field path's transport coefficients go through exp and sqrt, which V8
#: and the C library round differently in the last place for some arguments.
NOT_BIT_IDENTICAL = {'farfield'}


def steps_agree(mine: int, theirs: int) -> bool:
    """The same number of solver steps, give or take a percent (see above)."""
    return abs(mine - theirs) <= max(2, 0.01 * theirs)


def numbers(values: List[Any]) -> np.ndarray:
    return np.array([number(v) for v in values], dtype=float)


def close(a: np.ndarray, b: np.ndarray, rtol: float) -> bool:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.shape != b.shape:
        return False
    same = (a == b) | (np.isnan(a) & np.isnan(b))
    scale = np.maximum(np.abs(a), np.abs(b))
    return bool(np.all(same | (np.abs(a - b) <= rtol * scale)))


def fix(x: Any) -> Any:
    if isinstance(x, float) and not math.isfinite(x):
        return 'NaN' if x != x else ('Infinity' if x > 0 else '-Infinity')
    if isinstance(x, dict):
        return {k: fix(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [fix(v) for v in x]
    if hasattr(x, 'tolist'):
        return fix(x.tolist())
    if isinstance(x, set):
        return sorted(x)
    return x


@needs_app
class ProjectParity(unittest.TestCase):
    def test_every_example_loads_into_the_same_project(self) -> None:
        for name in EXAMPLES:
            with self.subTest(example=name):
                js = engine('project', model=example(name))['project']
                p = Project(example(name))
                mine = fix({
                    'simulation': p.simulation, 'index_lists': p.index_lists, 'chains': p.chains,
                    'materialListName': p.material_list_name, 'nuclideListName': p.nuclide_list_name,
                    'scenario': p.scenario, 'disabled': sorted(p.disabled), 'systems': p.systems,
                    'decayModel': p.decay_model(),
                    'blocks': {c: p.blocks[c] for c in BLOCK_COLLECTIONS},
                })
                for key in ('simulation', 'index_lists', 'chains', 'materialListName', 'nuclideListName',
                            'scenario', 'disabled', 'systems', 'decayModel', 'blocks'):
                    self.assertEqual(mine[key], js[key], key)
                self.assertTrue(close(p.time_grid(), numbers(js['timeGrid']), 1e-15))


@needs_app
class BuildParity(unittest.TestCase):
    def test_every_example_builds_the_same_system(self) -> None:
        for name in EXAMPLES:
            with self.subTest(example=name):
                model = example(name)
                js = engine('layout', model=model)
                s = build_system(Project(model), jacobian=False)
                self.assertEqual((s.nstate, s.nalg, s.nparam), (js['nstate'], js['nalg'], js['nparam']))
                self.assertEqual([(e.name, e.base, e.width, list(e.dims), e.kind) for e in s.layout.states],
                                 [(e['name'], e['base'], e['width'], e['dims'], e['kind']) for e in js['states']])
                self.assertEqual([(a.name, a.base, a.width, list(a.dims), a.kind, list(a.reads_alg))
                                  for a in s.layout.algebraic],
                                 [(a['name'], a['base'], a['width'], a['dims'], a['kind'], a['readsAlg'])
                                  for a in js['algebraic']])
                self.assertEqual(list(s.slot_class[:s.nalg]), js['slotClass'][:js['nalg']])
                self.assertTrue(close(s.P[:s.nparam], numbers(js['P'])[:js['nparam']], 0))
                y0 = s.initial_state()
                self.assertTrue(close(y0, numbers(js['y0']), 1e-14))
                X = s.evaluate_algebraic(s.start_time, y0)
                self.assertTrue(close(X[:s.nalg], numbers(js['X'])[:js['nalg']], 1e-13))

    def test_df_dy_is_generated_and_constant_where_the_applications_is(self) -> None:
        for name in EXAMPLES:
            with self.subTest(example=name):
                model = example(name)
                js = engine('jacobian', model=model)
                j = build_system(Project(model)).jacobian
                self.assertEqual(bool(j.get('available')), js['available'], j.get('reason'))
                if js['available']:
                    self.assertEqual(bool(j.get('constant')), js['constant'])
                    self.assertEqual(j['pattern'].nnz, js['nnz'])
                    self.assertEqual(len(j['groups']), js['colours'])

    def test_a_jacobian_infinite_at_the_start_is_refused(self) -> None:
        # The application's refuseNonFinite: d/dB of k*sqrt(B)*B at an empty B.
        import kompartment as kp
        m = kp.Model.new('Root')
        m.simulation.update(end_time=10, output_points=5)
        for name, initial in (('A', '1'), ('B', '0'), ('C', '0')):
            m.add_compartment(name, initial=initial)
        m.add_parameter('k', 0.1)
        m.add_transfer('A', 'B', rate='k')
        m.add_transfer('B', 'C', rate='k*sqrt(B)')
        model = m.to_dict()
        js = engine('jacobian', model=model)
        j = build_system(Project(model)).jacobian
        self.assertFalse(js['available'])
        self.assertFalse(j['available'])
        self.assertEqual(j['reason'], js['reason'])
        self.assertEqual(j['pattern'].nnz, js['nnz'])
        self.assertEqual(len(j['groups']), js['colours'])

    def test_the_derivative_is_the_applications(self) -> None:
        for name in EXAMPLES:
            model = example(name)
            s = build_system(Project(model), jacobian=False)
            if not s.nstate:
                continue
            rng = np.random.default_rng(7)
            points = []
            for k, frac in enumerate((0.0, 0.001, 0.3, 0.9)):
                y = rng.uniform(0, 10, s.nstate) * 10 ** rng.uniform(-3, 3, s.nstate)
                points.append({'t': s.start_time + (s.end_time - s.start_time) * frac, 'y': y.tolist()})
            js = engine('dydt', model=model, points=points)
            for p, q in zip(points, js['points']):
                with self.subTest(example=name, t=p['t']):
                    y = np.array(p['y'])
                    X = s.evaluate_algebraic(p['t'], y).copy()
                    d = s.dydt(p['t'], y)
                    self.assertTrue(close(X[:s.nalg], numbers(q['X'])[:s.nalg], 1e-12))
                    self.assertTrue(close(d, numbers(q['dydt']), 1e-12))


@needs_app
class RunParity(unittest.TestCase):
    def test_every_example_runs_as_the_application_runs_it(self) -> None:
        for name in EXAMPLES:
            with self.subTest(example=name):
                model = example(name)
                js = engine('run', model=model)
                res = run(Project(model))
                if res.stats.get('nsteps') is None:
                    self.assertIsNone(js['stats'].get('nsteps'))
                else:
                    self.assertTrue(steps_agree(res.stats['nsteps'], js['stats']['nsteps']),
                                    (res.stats['nsteps'], js['stats']['nsteps']))
                outs = res.outputs()
                self.assertEqual([o['label'] for o in outs], js['labels'])
                cols = res.series_many(outs)
                tj = numbers(js['t'])
                rtol = float(model['simulation'].get('rtol', 1e-3))
                if res.t.shape == tj.shape and close(res.t, tj, 1e-12):
                    mine, theirs = cols, [numbers(c) for c in js['columns']]
                else:
                    common = np.intersect1d(np.round(res.t, 9), np.round(tj, 9))
                    mi = np.isin(np.round(res.t, 9), common)
                    ji = np.isin(np.round(tj, 9), common)
                    mine = [c[mi] for c in cols]
                    theirs = [numbers(c)[ji] for c in js['columns']]
                for label, a, b in zip(js['labels'], mine, theirs):
                    scale = np.max(np.abs(b[np.isfinite(b)])) if np.isfinite(b).any() else 0.0
                    diff = np.abs(a - b)
                    diff = diff[np.isfinite(diff)]
                    worst = diff.max() / scale if diff.size and scale > 0 else 0.0
                    self.assertLess(worst, 10 * rtol, label)

    def test_every_scenario_runs_as_the_application_runs_it(self) -> None:
        from kompartment.engine.atstart import run_scenarios
        model = example('scenarios')
        mine = run_scenarios(model)
        self.assertEqual(list(mine), Project(model).scenarios)
        for name, res in mine.items():
            with self.subTest(scenario=name):
                js = engine('run', model={**model, 'scenario': name})
                self.assertTrue(steps_agree(res.stats['nsteps'], js['stats']['nsteps']))
                self.assertEqual(res.labels, js['labels'])
                rtol = float(model['simulation'].get('rtol', 1e-3))
                for label, a, b in zip(js['labels'], res.series_many(res.outputs()), js['columns']):
                    b = numbers(b)
                    scale = np.max(np.abs(b)) if b.size else 0.0
                    self.assertLessEqual(np.max(np.abs(a - b)) if b.size else 0.0, 10 * rtol * scale, label)
        # The same runs over processes: the recorders' histories travel back
        # with the solution, so every series is the one run in this process.
        pooled = run_scenarios(model, workers=2)
        for name, res in pooled.items():
            for a, b in zip(res.series_many(res.outputs()), mine[name].series_many(mine[name].outputs())):
                self.assertTrue(close(a, b, 0), name)


@needs_app
class AtStartParity(unittest.TestCase):
    def test_values_at_the_start_are_the_applications(self) -> None:
        from kompartment.engine.atstart import values_at_start
        for name in EXAMPLES:
            with self.subTest(example=name):
                model = example(name)
                p = Project(model)
                names = [b['name'] for c in BLOCK_COLLECTIONS for b in p.blocks[c]] + ['No such block']
                js = engine('atstart', model=model, names=names)
                v = values_at_start(p)
                self.assertEqual(v.size, js['size'])
                for n in names:
                    a, b = v.of(n), js['of'][n]
                    if b is None:
                        self.assertIsNone(a, n)
                        continue
                    self.assertEqual((a['kind'], a['dims']), (b['kind'], b['dims']), n)
                    self.assertEqual(list(a['fields']), list(b['fields']), n)
                    pairs = [(a['own'], b['own'])] + [(a['fields'][k], b['fields'][k]) for k in b['fields']]
                    for mine, theirs in pairs:
                        if theirs is None:
                            self.assertIsNone(mine, n)
                            continue
                        self.assertEqual([(r['index'], r['label'], r['unit']) for r in mine],
                                         [(r['index'], r['label'], r['unit']) for r in theirs], n)
                        self.assertTrue(close([r['value'] for r in mine], numbers([r['value'] for r in theirs]),
                                              1e-13), n)


if __name__ == '__main__':
    unittest.main()
