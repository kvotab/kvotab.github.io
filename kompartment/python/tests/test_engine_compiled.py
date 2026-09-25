"""The compiled path against the Python path: the same run, to the last bit.

A compiled run (``compiled=True``) is the derivative and the solver's loop
compiled with numba; the Python path (``compiled=False``) is what every other
test runs. The two take the same steps with the same arithmetic, so their
states, their statistics and their failures must be identical -- not close.
The models are the bundled examples and made-up ones.
"""

from __future__ import annotations

import unittest
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np

from helpers import example

import kompartment as kp
from kompartment.engine.builder import build_system
from kompartment.engine.project import Project
from kompartment.engine.runner import run
from kompartment.engine.solvers import SolverError

try:
    import numba  # noqa: F401
    HAVE_NUMBA = True
except Exception:  # noqa: BLE001 - optional
    HAVE_NUMBA = False

needs_numba = unittest.skipUnless(HAVE_NUMBA, 'the compiled path needs numba')

STATS = ('nsteps', 'nfailed', 'nfevals', 'npds', 'ndecomps', 'nsolves', 'nbelowtol', 'negative', 'points')


def settings(m: kp.Model, sim: Dict[str, Any], **defaults: Any) -> None:
    defaults.update(sim)
    m.simulation.update(**defaults)


def chain(n: int = 5, k: float = 0.3, **sim: Any) -> kp.Model:
    """100 units passed down a chain of n compartments at rate k."""
    m = kp.Model.new('Chain')
    settings(m, sim, end_time=50, output_points=26, rtol=1e-6, abstol=1e-10)
    names = [f'C{i}' for i in range(n)]
    for i, name in enumerate(names):
        m.add_compartment(name, initial='100' if i == 0 else '0')
    m.add_parameter('k', k)
    for a, b in zip(names, names[1:]):
        m.add_transfer(a, b, rate='k')
    return m


def drained(**sim: Any) -> kp.Model:
    """A pushed below zero by a constant outflow from t = 1: held at zero by
    the NDF and Rosenbrock; Dormand-Prince, which does not hold, crawls along
    zero in steps of the tolerance until its step budget runs out."""
    m = kp.Model.new('Drained')
    settings(m, sim, end_time=5, output_points=11, rtol=1e-6, abstol=1e-9, max_steps=20000)
    m.add_compartment('A', initial='1', dydt='-1')
    m.add_compartment('B', initial='0', dydt='1')
    return m


def peaked(**sim: Any) -> kp.Model:
    """A min/max read by a rate: its history kept by the compiled run, and an
    analytic Jacobian (called back in Python) that reads it."""
    m = kp.Model.new('Peaked')
    settings(m, sim, end_time=30, output_points=31, rtol=1e-6, abstol=1e-10)
    m.add_compartment('A', initial='100')
    m.add_compartment('B')
    m.add_compartment('C')
    m.add_parameter('k', 0.2)
    m.add_transfer('A', 'B', rate='k')
    m.add_min_max('Peak', target='B')
    m.add_transfer('B', 'C', rate='0.05*Peak/(1+Peak)')
    return m


def blowup(**sim: Any) -> kp.Model:
    """A = 1/(2 - t): no step size gets past t = 2."""
    m = kp.Model.new('Blow-up')
    settings(m, sim, end_time=5, output_points=11, rtol=1e-6, abstol=1e-10, max_steps=20000)
    m.add_compartment('A', initial='0.5', dydt='1/(2-time)^2', non_negative=False)
    return m


def both(project: Project, tweak: Optional[Callable[[Any], None]] = None,
         **kw: Any) -> Tuple[Tuple[str, Any], Tuple[str, Any]]:
    """The same run on each path, each on a system of its own: ('ok', results)
    or ('error', the exception). The second is 'auto', so that a run the
    compiled path turns down still runs, and says why."""
    out = []
    for compiled in (False, 'auto'):
        system = build_system(Project(project.to_json()))
        if tweak is not None:
            tweak(system)
        try:
            out.append(('ok', run(project, system=system, compiled=compiled, **kw)))
        except Exception as e:  # noqa: BLE001 - compared below
            out.append(('error', e))
    return out[0], out[1]


@needs_numba
class Identical(unittest.TestCase):
    def same(self, project: Project, tweak: Optional[Callable[[Any], None]] = None, compiled: bool = True,
             **kw: Any) -> Any:
        (ka, a), (kb, b) = both(project, tweak, **kw)
        self.assertEqual(ka, kb, f'python: {a!r}, compiled: {b!r}')
        if ka == 'error':
            self.assertIs(type(a), type(b))
            self.assertEqual(str(a), str(b))
            self.assertEqual(getattr(a, 'code', None), getattr(b, 'code', None))
            self.assertEqual(getattr(a, 't', None), getattr(b, 't', None))
            return a
        self.assertEqual(bool(b.stats.get('compiled')), compiled, b.stats.get('compiled_why'))
        self.assertFalse(a.stats.get('compiled'))
        self.assertTrue(np.array_equal(a.t, b.t))
        ya, yb = np.array(a.y), np.array(b.y)
        self.assertEqual(ya.shape, yb.shape)
        self.assertTrue(np.array_equal(ya.view(np.int64), yb.view(np.int64)),
                        f'largest difference {np.max(np.abs(ya - yb))}')
        for key in STATS:
            self.assertEqual(a.stats.get(key), b.stats.get(key), key)
        ha, hb = a.stats.get('held'), b.stats.get('held')
        self.assertEqual(ha is None, hb is None)
        if ha is not None:
            self.assertTrue(np.array_equal(ha, hb))
        return a, b

    def test_bundled_examples(self) -> None:
        cases = {'four-compartment': ('ndf', 'ros23', 'dp45'), 'decay-chain': ('ndf', 'ros23'),
                 'biosphere': ('ndf', 'ros23'), 'lookup-driver': ('ndf', 'ros23', 'dp45'),
                 'scenarios': ('ndf', 'ros23', 'dp45'), 'landscape': ('ndf', 'ros23', 'dp45'),
                 'waste-packages': ('ndf', 'dp45')}
        for name, solvers in cases.items():
            for solver in solvers:
                with self.subTest(name=name, solver=solver):
                    raw = example(name)
                    raw['simulation']['solver'] = solver
                    self.same(Project(raw))

    def test_made_up_models_on_every_solver(self) -> None:
        for solver in ('ndf', 'ros23', 'dp45'):
            for label, model in (('chain', chain), ('drained', drained), ('peaked', peaked)):
                with self.subTest(model=label, solver=solver):
                    self.same(model(solver=solver).project())

    def test_the_constraint_holds_the_same(self) -> None:
        a, _ = self.same(drained(solver='ndf').project())
        self.assertGreater(a.stats['negative'], 0)
        self.assertGreater(int(np.sum(a.stats['held'])), 0)

    def test_solver_settings(self) -> None:
        for extra in (dict(auto_abstol=True), dict(norm_control=True), dict(error_norm='rms'), dict(bdf=True),
                      dict(max_order=2), dict(initial_step=1e-3), dict(max_step=0.5), dict(below_tol_run=3),
                      dict(stagnation_tol=0.5), dict(matrix='dense'), dict(jacobian='numeric')):
            for label, model in (('chain', chain), ('drained', drained)):
                with self.subTest(model=label, **extra):
                    self.same(model(solver='ndf', **extra).project())

    def test_a_jacobian_differenced_without_a_pattern(self) -> None:
        def no_pattern(system: Any) -> None:
            system.jacobian = None
        for solver in ('ndf', 'ros23'):
            with self.subTest(solver=solver):
                self.same(chain(solver=solver).project(), no_pattern)
                self.same(peaked(solver=solver).project(), no_pattern)

    def test_the_solvers_own_steps_as_output(self) -> None:
        for spacing in ('both', 'solver'):
            for solver in ('ndf', 'ros23', 'dp45'):
                with self.subTest(spacing=spacing, solver=solver):
                    self.same(chain(solver=solver, spacing=spacing).project())

    def test_failures_say_the_same(self) -> None:
        for solver in ('ndf', 'ros23', 'dp45'):
            with self.subTest(solver=solver, failure='steps'):
                e = self.same(chain(solver=solver, max_steps=20).project())
                self.assertIsInstance(e, SolverError)
                self.assertEqual(e.code, 'steps')
            with self.subTest(solver=solver, failure='blow-up'):
                e = self.same(blowup(solver=solver).project())
                self.assertIsInstance(e, SolverError)
                self.assertEqual(e.code, 'tolerance')

    def test_a_matrix_python_would_factorise_sparsely(self) -> None:
        # 70 states in a chain: SuperLU, which the compiled loop calls back
        # to form the matrix and to solve with, as the Python solver does.
        for solver in ('ndf', 'ros23'):
            with self.subTest(solver=solver):
                a, b = self.same(chain(n=70, solver=solver).project())
                self.assertTrue(a.stats['sparse'])
                self.assertEqual(a.stats['fill'], b.stats['fill'])
        self.same(chain(n=70, solver='ndf', matrix='dense').project())
        self.same(chain(n=240, solver='ndf', matrix='dense').project())  # LAPACK, past the application's LU

    def test_a_history_that_outgrows_its_room(self) -> None:
        from kompartment.engine.compiled import model as compiled_model
        was = compiled_model.HISTORY_CAPACITY
        compiled_model.HISTORY_CAPACITY = 4
        try:
            a, b = self.same(peaked(solver='ndf').project())
        finally:
            compiled_model.HISTORY_CAPACITY = was
        self.assertGreater(b.system.MEM[0].history.t.__len__(), 4)
        self.assertEqual(a.system.MEM[0].history.t, b.system.MEM[0].history.t)
        self.assertEqual(a.system.MEM[0].history.v, b.system.MEM[0].history.v)
        self.assertTrue(np.array_equal(a['Peak'], b['Peak']))


@needs_numba
class Behaviour(unittest.TestCase):
    def test_why_a_run_is_not_compiled(self) -> None:
        res = kp.Model.from_dict(example('recorders')).run()
        self.assertFalse(res.stats['compiled'])
        self.assertIn('discrete events', res.stats['compiled_why'])
        project = Project(example('recorders'))
        from kompartment.engine.compiled import NotCompiled
        with self.assertRaises(NotCompiled):
            run(project, system=build_system(project), compiled=True)

    def test_off_means_python(self) -> None:
        project = chain().project()
        res = run(project, system=build_system(project), compiled=False)
        self.assertFalse(res.stats['compiled'])
        self.assertNotIn('compiled_why', res.stats)

    def test_progress_and_stopping(self) -> None:
        project = chain(solver='ndf', end_time=5000, rtol=1e-9).project()
        seen = []
        res = run(project, system=build_system(project), compiled=True,
                  on_progress=lambda fraction, t: seen.append(fraction))
        self.assertTrue(res.stats['compiled'])
        self.assertTrue(seen)
        self.assertEqual(seen, sorted(seen))
        with self.assertRaises(SolverError) as caught:
            run(project, system=build_system(project), compiled=True, on_progress=lambda f, t: None,
                signal=lambda: True)
        self.assertEqual(caught.exception.code, 'aborted')

    def test_an_error_in_the_progress_is_the_callers(self) -> None:
        project = chain(solver='ndf', end_time=5000, rtol=1e-9).project()

        def boom(fraction: float, t: float) -> None:
            raise KeyError('from the progress')
        with self.assertRaises(KeyError):
            run(project, system=build_system(project), compiled=True, on_progress=boom)

    def test_probabilistic_runs_agree(self) -> None:
        m = chain(solver='ndf')
        m['k'].distribution = kp.distributions.uniform(0.1, 0.5)
        a = m.run_probabilistic(12, seed=3, compiled=False)
        b = m.run_probabilistic(12, seed=3, compiled=True)
        self.assertEqual(len(a.data['values']), len(b.data['values']))
        for va, vb in zip(a.data['values'], b.data['values']):
            self.assertTrue(np.array_equal(va, vb))


if __name__ == '__main__':
    unittest.main()
