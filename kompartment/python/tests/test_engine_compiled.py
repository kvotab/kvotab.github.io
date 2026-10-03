"""The compiled path against the Python path: the same run, to the last bit.

A compiled run (``compiled=True``) is the derivative and the solver's loop
compiled with numba; the Python path (``compiled=False``) is what every other
test runs. The two take the same steps with the same arithmetic, so their
states, their statistics, their recorders, every series and their failures
must be identical -- not close. The models are the bundled examples and
made-up ones that between them use every function of the language, every
block that remembers, discrete events, the clock worked out every
min_change_time, far-field paths of every kind and every solver.
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

STATS = ('nsteps', 'nfailed', 'nfevals', 'npds', 'ndecomps', 'nsolves', 'nbelowtol', 'negative', 'points', 'events',
         'restarts', 'jumps')


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


#: An expression for every function of the language that the code writer
#: leaves to a call, some read at the clock alone and some at the state.
FUNCTION_EXPRESSIONS = {
    'fac': 'factorial(2 + mod(floor(time), 5))',
    'bin': 'binomial(6, 1 + mod(floor(time), 4))',
    'hyp': 'asinh(time) + acosh(1 + time) + atanh(0.5 * time / (1 + time))',
    'logic': 'and(time > 1, A > 0.1) + 2*or(time > 3, A < 0) + 4*nand(time > 2, 1) + 8*nor(time > 5, 0) '
             '+ 16*xor(time > 1, time > 2, time > 3)',
    'pct': 'percentile(30, A, B, time, 2, 0.5) + percentile(50, A, B, time) + percentile(99, 1, A)',
    'ilin': 'interpolationUseEndValues(time, 0, 1, 2, 3, 5, 0.5, 5, 2, 8, 1)',
    'iext': 'interpolationExtrapolation(time, 1, 0.1, 3, 0.3) + interpolationExtrapolation(A, 0, 0, 1, 2)',
    'conv': 'bq2mole(A + 1, 30) * 1e20 + mole2bq(B + 1e-12, 1e5) * 1e-20',
    'ramps': 'rampDown(time, 2, 6) + rampUp(time, 7, 3) + smoothDown(time, 4, 2) + smoothUp(A, 0.5, 3)',
    'trp': 'transport_point(1, 2, 3, 4, min(1, time / 10)) + transport_sum(1, 2, 3, 4, 0.1, min(1, time / 10)) '
           '+ transport_mean(4, 3, 2, 1, 0, min(1, time/10))',
    'misc': 'round(time / 3) + fix(-time / 4) + rem(time, 3) + ulp(time) * 1e10 + erf(time / 5) + erfc(A)',
}


def functions(nuclides: bool = False, **sim: Any) -> kp.Model:
    """Every function in FUNCTION_EXPRESSIONS, read by a transfer rate; with
    ``nuclides``, every block indexed by three of them, so that each call
    is made on arrays."""
    m = kp.Model.new('Functions')
    settings(m, sim, end_time=10, output_points=21, rtol=1e-6, abstol=1e-10)
    if nuclides:
        m.add_nuclides(['Cs-137', 'Sr-90', 'I-129'])
    m.add_compartment('A', initial='1')
    m.add_compartment('B')
    if nuclides:
        m['A'].set_value('2', at='Sr-90')
    for name, eq in FUNCTION_EXPRESSIONS.items():
        m.add_expression(name, eq)
    m.add_parameter('k', 0.3)
    total = ' + '.join(f'1e-3 * {n}' for n in FUNCTION_EXPRESSIONS)
    m.add_transfer('A', 'B', rate=f'k * (1 + 0.01 * ({total}))')
    return m


def failing(equation: str, **sim: Any) -> kp.Model:
    """A transfer that reads ``equation``, which raises at some point of the run."""
    m = kp.Model.new('Failing')
    settings(m, sim, end_time=10, output_points=11)
    m.add_compartment('A', initial='1')
    m.add_compartment('B')
    m.add_expression('e', equation)
    m.add_transfer('A', 'B', rate='0.1 + 0 * e')
    return m


def oscillating(**sim: Any) -> kp.Model:
    """A tank fed 1 + sin(t): triggers both ways on sin(t), every half
    period, and on the tank crossing a level; a min/max reset by one and one
    started and stopped by them, running means started, stopped and reset,
    snapshots, a delay -- all read back into a rate."""
    m = kp.Model.new('Oscillating')
    settings(m, sim, end_time=40, output_points=81, rtol=1e-6, abstol=1e-10)
    m.add_compartment('Tank', initial='1')
    m.add_compartment('Sink')
    m.add_parameter('k', 0.2)
    m.add_inflow('Tank', rate='1 + sin(time)')
    m.add_transfer('Tank', 'Sink', rate='k')
    m.add_trigger('Up', first='sin(time)', second='0', direction='rising')
    m.add_trigger('Down', first='sin(time)', second='0', direction='falling')
    m.add_trigger('Either', first='Tank', second='4', direction='both')
    m.add_min_max('Peak', target='Tank', reset_trigger='Up')
    m.add_min_max('Low', target='Tank', operation='min', start_trigger='Down', stop_trigger='Up')
    m.add_running_mean('Mean', target='Tank', start_trigger='Up', stop_trigger='Down', reset_trigger='Either')
    m.add_running_mean('Mean_all', target='Tank')
    m.add_snapshot('At_up', target='Tank', trigger='Up', initial='-1')
    m.add_snapshot('When_either', target='time', trigger='Either', initial='0')
    m.add_delay('Lagged', target='Tank', delay='2.5')
    m.add_transfer('Sink', None, rate='0.01 * (Peak + Low + Mean + Mean_all + At_up + Lagged) / (1 + Peak)')
    return m


def resting(**sim: Any) -> kp.Model:
    """A trigger whose two sides start equal -- the crossing search's
    'resting' start -- and one, with its recorders, over nuclides."""
    m = kp.Model.new('Resting')
    settings(m, sim, end_time=10, output_points=21, rtol=1e-6, abstol=1e-10)
    m.add_nuclides(['Cs-137', 'Sr-90'])
    m.add_compartment('A', initial='10')
    m['A'].set_value('20', at='Sr-90')
    m.add_compartment('B')
    m.add_transfer('A', 'B', rate='0.3')
    m.add_trigger('Start', first='time', second='0', direction='rising')
    m.add_trigger('Half', first='A', second='5', direction='falling')
    m.add_snapshot('When_half', target='time', trigger='Half', initial='-1', index_lists=['Radionuclides'])
    m.add_min_max('Peak_B', target='B', reset_trigger='Half', index_lists=['Radionuclides'])
    m.add_running_mean('Mean_B', target='B', start_trigger='Half', index_lists=['Radionuclides'])
    m.add_transfer('B', None, rate='0.01 * (1 + When_half + Peak_B + Mean_B)')
    return m


def clocked(**sim: Any) -> kp.Model:
    """Rates read from a table and functions of the clock, for min_change_time."""
    m = kp.Model.new('Clocked')
    settings(m, sim, end_time=50, output_points=26, rtol=1e-6, abstol=1e-10)
    m.add_compartment('A', initial='100')
    m.add_compartment('B')
    m.add_lookup('Flow', [[0, 0.1], [10, 0.5], [20, 0.05], [35, 0.3], [50, 0.2]])
    m.add_expression('Wobble', '0.1 + 0.05 * sin(time / 3) + interpolationUseEndValues(time, 0, 0, 25, 0.2, 50, 0)')
    m.add_transfer('A', 'B', rate='Flow * (1 + Wobble)')
    m.add_transfer('B', None, rate='0.05 * Wobble')
    m.add_min_max('Peak', target='B')
    return m


def farfield(**block: Any) -> Project:
    """The bundled far-field example, shortened, its path changed by ``block``."""
    raw = example('farfield')
    raw['farfields'][0].update(block)
    raw['simulation'].update(end_time=2e4)
    return Project(raw)


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
        # What the recorders kept, and every series worked out from the run.
        for ra, rb in zip(a.system.MEM, b.system.MEM):
            self.assertEqual(ra.history.t, rb.history.t)
            self.assertEqual(ra.history.v, rb.history.v)
            self.assertEqual((ra.recording, ra.total_time, ra.last_time, ra.reset_sum),
                             (rb.recording, rb.total_time, rb.last_time, rb.reset_sum))
        for label in a.labels:
            self.assertTrue(np.array_equal(np.asarray(a[label]).view(np.int64), np.asarray(b[label]).view(np.int64)),
                            label)
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

    def test_every_function_of_the_language(self) -> None:
        for nuclides in (False, True):
            for solver in ('ndf', 'ros23', 'dp45'):
                with self.subTest(nuclides=nuclides, solver=solver):
                    self.same(functions(nuclides, solver=solver).project())

    def test_what_the_equations_raise_is_raised_alike(self) -> None:
        # The same exception, with the same message, at the same evaluation.
        cases = {
            'transport_point(1, 2, 3, time/5 - 0.2)': 'lower than zero',
            'transport_point(1, 2, 3, time/2)': 'higher than one',
            'transport_sum(1, 2, 3, 0.5 - time/4, 0.6)': 'starts at',
            'transport_mean(1, 2, 3, 0.2, 0.9 + time/50)': 'ends at',
            'interpolationUseEndValues(time, 1, 2, 3)': 'x, y pairs',
            'interpolationUseEndValues(time, 1, 2, A/0 - A/0, 3)': 'no x value',
        }
        for equation, said in cases.items():
            for solver in ('ndf', 'ros23', 'dp45'):
                with self.subTest(equation=equation, solver=solver):
                    e = self.same(failing(equation, solver=solver).project())
                    self.assertIsInstance(e, ValueError)
                    self.assertIn(said, str(e))

    def test_recorders_and_discrete_events(self) -> None:
        for solver in ('ndf', 'ros23', 'dp45'):
            raw = example('recorders')
            raw['simulation']['solver'] = solver
            with self.subTest(model='recorders', solver=solver):
                a, _ = self.same(Project(raw))
                self.assertEqual(a.stats['events'], 1)
            with self.subTest(model='oscillating', solver=solver):
                a, _ = self.same(oscillating(solver=solver).project())
                self.assertGreater(a.stats['events'], 10)
            with self.subTest(model='resting', solver=solver):
                self.same(resting(solver=solver).project())

    def test_events_with_the_solvers_settings_and_output(self) -> None:
        for spacing in ('both', 'solver'):
            for solver in ('ndf', 'ros23', 'dp45'):
                with self.subTest(spacing=spacing, solver=solver):
                    self.same(oscillating(solver=solver, spacing=spacing).project())
        for extra in (dict(auto_abstol=True), dict(jacobian='numeric'), dict(matrix='dense'), dict(non_negative=False)):
            with self.subTest(**extra):
                self.same(oscillating(solver='ndf', **extra).project())

    def test_recorders_that_outgrow_their_room(self) -> None:
        from kompartment.engine.compiled import model as compiled_model
        was = compiled_model.HISTORY_CAPACITY
        compiled_model.HISTORY_CAPACITY = 4
        try:
            for solver in ('ndf', 'dp45', 'radau5'):
                with self.subTest(solver=solver):
                    self.same(oscillating(solver=solver).project())
        finally:
            compiled_model.HISTORY_CAPACITY = was

    def test_the_clock_worked_out_every_min_change_time(self) -> None:
        for interval in (0.7, 5.0):
            for solver in ('ndf', 'ros23', 'dp45'):
                with self.subTest(interval=interval, solver=solver):
                    self.same(clocked(solver=solver, min_change_time=interval).project())
        # Switch times and jumps: each segment counts its intervals from where it starts.
        for name, interval in (('lookup-driver', 3.0), ('waste-packages', 3.0), ('recorders', 50.0)):
            raw = example(name)
            raw['simulation']['min_change_time'] = interval
            with self.subTest(name=name):
                self.same(Project(raw))

    def test_farfield_paths_of_every_kind(self) -> None:
        cases = {
            'cells': {},
            'semi-analytical': {'method': 'semi-analytical'},
            # Settings that follow the clock: the rates worked out again as they move.
            'moving': {'tw': '50 * (1 + 0.5 * rampUp(time, 1e3, 1e4))', 'n_f': 8, 'n_m': 8},
            'moving, reference grid': {'f': '1e5 * (1 + interpolationUseEndValues(time, 0, 0, 2e4, 1))',
                                       'grid': 'reference', 'n_f': 6, 'n_m': 6},
        }
        for label, block in cases.items():
            with self.subTest(path=label):
                self.same(farfield(**block))

    def test_solvers_with_a_loop_of_their_own(self) -> None:
        # The six Julia-derived methods first ported run on a compiled loop of
        # their own (test_engine_compiled_julia.py takes them further); SciPy's
        # run theirs in Python, on the compiled model, and so do the five that
        # came with the default algorithm, whose loop is not compiled yet.
        later = ('auto', 'fbdf_krylov', 'rosenbrock23', 'tsit5', 'vern7')
        for solver in ('fbdf', 'qndf', 'rodas5p', 'radau5', 'kencarp4', 'trbdf2', 'scipy_bdf', 'scipy_radau',
                       'scipy_lsoda') + later:
            models = [chain, peaked]
            if not solver.startswith('scipy'):
                models.append(oscillating)
            for model in models:
                with self.subTest(solver=solver, model=model.__name__):
                    _, b = self.same(model(solver=solver).project())
                    looped = not solver.startswith('scipy') and solver not in later
                    self.assertEqual(b.stats['compiled_loop'], looped)
                    if not looped:
                        self.assertIn(f"the solver '{solver}' keeps the loop of its own", b.stats['compiled_loop_why'])
            with self.subTest(solver=solver, model='clocked'):
                self.same(clocked(solver=solver, min_change_time=0.7).project())

    def test_a_matrix_too_large_to_form_fails_alike(self) -> None:
        # More states than the application's dense LU takes, and the room for
        # a dense matrix made smaller than they need.
        from kompartment.engine.solvers import matrix
        was = matrix.DENSE_MAX_BYTES
        matrix.DENSE_MAX_BYTES = 1000

        def no_pattern(system: Any) -> None:
            system.jacobian = None
        try:
            for solver in ('ndf', 'ros23'):
                with self.subTest(solver=solver):
                    e = self.same(chain(n=250, solver=solver).project(), no_pattern)
                    self.assertIn('without a sparsity pattern', str(e))
        finally:
            matrix.DENSE_MAX_BYTES = was


@needs_numba
class Behaviour(unittest.TestCase):
    def test_every_run_takes_the_compiled_path(self) -> None:
        # Discrete events, the recorders, min_change_time and every solver
        # included: compiled=True never says no. (SciPy refuses discrete events.)
        cases = {'recorders': ('ndf', 'dp45', 'radau5', 'auto'),
                 'farfield': ('ndf', 'radau5', 'scipy_bdf', 'scipy_lsoda'),
                 'waste-packages': ('ndf', 'dp45', 'radau5', 'scipy_lsoda', 'auto', 'rosenbrock23')}
        for name, solvers in cases.items():
            for solver in solvers:
                raw = example(name)
                raw['simulation'].update(solver=solver, end_time=min(raw['simulation']['end_time'], 2e4))
                with self.subTest(name=name, solver=solver):
                    project = Project(raw)
                    res = run(project, system=build_system(project), compiled=True)
                    self.assertTrue(res.stats['compiled'])
                    self.assertNotIn('compiled_why', res.stats)
                    self.assertEqual(res.stats['compiled_loop'],
                                     not solver.startswith('scipy') and solver not in ('auto', 'rosenbrock23'))

    def test_no_array_is_frozen_into_the_compiled_code(self) -> None:
        # Every array a model's code reads is handed in at run time: an array
        # global to the compiled code would be copied into it, which makes a
        # large model slow to compile and stops numba from caching it.
        from kompartment.engine.compiled.run import compiled_model
        project = chain(n=300).project()
        cm = compiled_model(build_system(project))
        frozen = [k for k, v in vars(cm.module).items() if isinstance(v, np.ndarray)]
        self.assertEqual(frozen, [])

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


class Scipy(unittest.TestCase):
    def test_lsoda_takes_a_large_stiff_sparse_model(self) -> None:
        # LSODA is given a dense Jacobian whatever the model: ODEPACK
        # factorises full or banded matrices only, and the sparse one the
        # other SciPy methods take for 60 states or more failed every LSODA
        # run that turned stiff ("setting an array element with a sequence",
        # said as a derivative gone non-finite).
        from kompartment.engine.solvers.scipy_driver import jacobian_form
        sparse = {'density': 0.02}
        self.assertEqual([jacobian_form(m, sparse, 80) for m in ('BDF', 'Radau', 'LSODA')],
                         ['sparse', 'sparse', 'dense'])
        self.assertEqual((jacobian_form('BDF', sparse, 59), jacobian_form('BDF', {'density': 0.3}, 80)),
                         ('dense', 'dense'))
        self.assertEqual(jacobian_form('LSODA', None, 80), 'none')
        bdf = run(chain(80, k=1000, solver='scipy_bdf').project(), compiled=False)
        self.assertIs(bdf.stats['sparse'], True)
        for compiled in (False, 'auto'):
            with self.subTest(compiled=compiled):
                res = run(chain(80, k=1000, solver='scipy_lsoda').project(), compiled=compiled)
                self.assertIs(res.stats['sparse'], False)
                self.assertGreater(res.stats['npds'], 0)  # stiff: it did take the Jacobian
                self.assertTrue(np.allclose(res.y, bdf.y, rtol=1e-4, atol=1e-6))


if __name__ == '__main__':
    unittest.main()
