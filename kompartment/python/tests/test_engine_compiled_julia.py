"""The Julia-derived solvers' compiled loop against their Python loop.

``engine/compiled/julia.py`` ports the loop of ``fbdf``, ``qndf``,
``rodas5p``, ``radau5``, ``kencarp4`` and ``trbdf2`` (``engine/solvers/julia``)
to numba, and that of the six that came with the default algorithm (``NEW``):
``rosenbrock23``, ``tsit5``, ``vern7``, ``fbdf_krylov`` (GMRES, in
``compiled/krylov.py``), DifferentialEquations.jl's switch itself
(``auto_julia``) and ``auto``, whose explicit start hands the run to the
compiled NDF. A compiled run (``compiled='auto'``) and a Python one
(``compiled=False``) take the same steps with the same arithmetic, so their
states, counts, recorders, series and failures must be identical -- the
comparison is ``test_engine_compiled``'s, on its models and the bundled
examples, through every option the adapter maps.

What the compiled loop leaves to Python is checked here too: SuperLU through
the Python solver's own ``SparseLU`` (the chains of 70 states and the
examples), LAPACK called at SciPy's own addresses (bit for bit against
``lu_factor`` and ``lu_solve``), the analytic Jacobian, progress and stopping;
and a Python solver given other arithmetic -- as ``test_engine_julia``'s
``BitIdentity`` gives it the application's ``pow`` -- keeps its own loop.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, Callable, Dict, Optional, Tuple
from unittest import mock

import numpy as np

from helpers import example

import kompartment as kp
import test_engine_compiled as base
from kompartment.engine.builder import build_system
from kompartment.engine.project import Project, ValidationError
from kompartment.engine.runner import run
from kompartment.engine.solvers import SolverError

SOLVERS = ('rodas5p', 'kencarp4', 'trbdf2', 'fbdf', 'qndf', 'radau5')
#: The multistep methods, which read ``simulation.bdf``: QNDF runs QBDF, FBDF is a BDF already.
BDF = ('qndf', 'fbdf')
#: The six that came with the default algorithm.
NEW = ('auto', 'auto_julia', 'fbdf_krylov', 'rosenbrock23', 'tsit5', 'vern7')
#: Explicit throughout: too slow for a stiff model.
EXPLICIT = ('tsit5', 'vern7')
needs_numba = base.needs_numba


def stiff(n: int = 3, **sim: Any) -> kp.Model:
    """n compartments exchanging with their neighbours at 1e3 a year and the
    last draining slowly: stiff for as long as anything is left, so that the
    switching solvers turn to their stiff side -- Rosenbrock23 up to 50
    states (Rodas5P below a relative tolerance of 1e-6), FBDF up to 500,
    FBDF by GMRES above, ``auto`` to the NDF at every size."""
    m = kp.Model.new('Stiff')
    base.settings(m, sim, end_time=20, output_points=21, spacing='linear', rtol=1e-6, abstol=1e-10)
    for i in range(n):
        m.add_compartment(f'C{i}', initial='100' if i == 0 else '0')
    for i in range(n - 1):
        m.add_transfer(f'C{i}', f'C{i + 1}', rate='1e3')
        m.add_transfer(f'C{i + 1}', f'C{i}', rate='1e3')
    m.add_transfer(f'C{n - 1}', None, rate='0.5')
    return m


def ticking(solver: str, **sim: Any) -> kp.Model:
    """``stiff`` with a discrete event at t = 5, at which the runner starts
    the solver again: the switching solvers go on as they ended."""
    m = stiff(solver=solver, **sim)
    m.add_trigger('Tick', first='time', second='5', direction='rising')
    m.add_snapshot('At_tick', target='C1', trigger='Tick', initial='0')
    return m


def cornered(points: int, **sim: Any) -> kp.Model:
    """A flow read from a table of ``points`` corners: ``auto``'s explicit
    methods land on each, or, past a hundred, leave the run to the NDF."""
    m = kp.Model.new('Cornered')
    base.settings(m, sim, end_time=50, output_points=26, rtol=1e-6, abstol=1e-10)
    m.add_compartment('A', initial='100')
    m.add_compartment('B')
    m.add_lookup('Flow', [[50 * i / (points - 1), 0.1 + 0.05 * (i % 3)] for i in range(points)])
    m.add_transfer('A', 'B', rate='Flow')
    m.add_transfer('B', None, rate='0.02')
    return m


def per_state_tolerances(**sim: Any) -> kp.Model:
    """A chain of 12 whose every third compartment asks for its own abstol."""
    m = kp.Model.new('Per-state')
    base.settings(m, sim, end_time=50, output_points=26, rtol=1e-6, abstol=1e-10)
    for i in range(12):
        m.add_compartment(f'C{i}', initial='100' if i == 0 else '0', abstol=1e-14 if i % 3 == 0 else None)
    m.add_parameter('k', 0.3)
    for i in range(11):
        m.add_transfer(f'C{i}', f'C{i + 1}', rate='k')
    return m


def no_pattern(system: Any) -> None:
    system.jacobian = None


@needs_numba
class Identical(unittest.TestCase):
    #: test_engine_compiled's comparison, every number to the last bit.
    _same = base.Identical.same

    def same(self, project: Project, tweak: Optional[Callable[[Any], None]] = None, **kw: Any) -> Any:
        out = self._same(project, tweak, **kw)
        if isinstance(out, tuple):
            a, b = out
            # The loop itself ran compiled, not the Python solver's.
            self.assertTrue(b.stats['compiled_loop'], b.stats.get('compiled_loop_why'))
            for key in ('sparse', 'fill', 'solver'):
                self.assertEqual(a.stats.get(key), b.stats.get(key), key)
        return out

    def raw(self, name: str, solver: str, **sim: Any) -> Project:
        raw = example(name)
        raw['simulation'].update(solver=solver, **sim)
        return Project(raw)

    def test_made_up_models(self) -> None:
        for solver in SOLVERS:
            for label, model in (('chain', base.chain), ('drained', base.drained), ('peaked', base.peaked),
                                 ('resting', base.resting)):
                with self.subTest(model=label, solver=solver):
                    self.same(model(solver=solver).project())

    def test_every_function_of_the_language(self) -> None:
        for nuclides in (False, True):
            for solver in SOLVERS:
                with self.subTest(nuclides=nuclides, solver=solver):
                    self.same(base.functions(nuclides, solver=solver).project())

    def test_discrete_events(self) -> None:
        for solver in SOLVERS:
            with self.subTest(solver=solver):
                # 21 events, 19 for the methods whose larger steps carry a
                # pair of the tank's crossings inside one step.
                a, _ = self.same(base.oscillating(solver=solver).project())
                self.assertEqual(a.stats['events'], 19 if solver in ('rodas5p', 'kencarp4', 'radau5') else 21)
            with self.subTest(solver=solver, model='recorders'):
                a, _ = self.same(self.raw('recorders', solver))
                self.assertEqual(a.stats['events'], 1)
            for spacing in ('both', 'solver'):
                with self.subTest(solver=solver, spacing=spacing):
                    self.same(base.oscillating(solver=solver, spacing=spacing).project())

    def test_the_clock_worked_out_every_min_change_time(self) -> None:
        for solver in SOLVERS:
            with self.subTest(solver=solver):
                self.same(base.clocked(solver=solver, min_change_time=0.7).project())

    def test_bundled_examples(self) -> None:
        for name in ('biosphere', 'decay-chain', 'landscape', 'waste-packages', 'lookup-driver', 'four-compartment',
                     'scenarios'):
            for solver in SOLVERS:
                with self.subTest(name=name, solver=solver):
                    self.same(self.raw(name, solver))

    def test_farfield(self) -> None:
        # 1581 states, sparse. Radau's complex half is dense, as in the
        # Python solver, which takes it minutes to 2e4: it runs a shorter span.
        for solver in SOLVERS:
            with self.subTest(solver=solver):
                a, _ = self.same(self.raw('farfield', solver, end_time=2e3 if solver == 'radau5' else 2e4))
                self.assertTrue(a.stats['sparse'])

    def test_farfield_paths_of_every_kind(self) -> None:
        cases = {
            'semi-analytical': {'method': 'semi-analytical'},
            'moving': {'tw': '50 * (1 + 0.5 * rampUp(time, 1e3, 1e4))', 'n_f': 8, 'n_m': 8},
            'moving, reference grid': {'f': '1e5 * (1 + interpolationUseEndValues(time, 0, 0, 2e4, 1))',
                                       'grid': 'reference', 'n_f': 6, 'n_m': 6},
        }
        for label, block in cases.items():
            for solver in ('rodas5p', 'kencarp4', 'qndf'):
                raw = json.loads(json.dumps(base.farfield(**block).to_json()))
                raw['simulation']['solver'] = solver
                with self.subTest(path=label, solver=solver):
                    self.same(Project(raw))

    def test_solver_settings(self) -> None:
        settings = [dict(auto_abstol=True), dict(matrix='dense'), dict(matrix='sparse'), dict(jacobian='numeric'),
                    dict(max_order=2), dict(max_order=3.0, min_order=2), dict(initial_step=1e-3), dict(max_step=0.5),
                    dict(error_norm='max'), dict(newton_kappa=1e-2), dict(max_jac_age=3), dict(below_tol_run=3),
                    dict(non_negative=False)]
        for solver in SOLVERS:
            for extra in settings + ([dict(bdf=True)] if solver in BDF else []):
                for label, model in (('chain', base.chain), ('drained', base.drained)):
                    with self.subTest(model=label, solver=solver, **extra):
                        # (drained runs the multistep methods out of steps, alike.)
                        out = self.same(model(solver=solver, **extra).project())
                        if extra.get('bdf') and solver == 'qndf' and isinstance(out, tuple):
                            self.assertEqual(out[0].stats['solver'], 'qbdf')

    def test_tolerances_per_state(self) -> None:
        for solver in SOLVERS:
            for auto in (False, True):
                with self.subTest(solver=solver, auto_abstol=auto):
                    self.same(per_state_tolerances(solver=solver, auto_abstol=auto).project())
            with self.subTest(solver=solver, model='biosphere'):
                self.same(self.raw('biosphere', solver, auto_abstol=True, error_norm='max'))

    def test_matrices_python_factorises_sparsely(self) -> None:
        # 70 states in a chain: W is SuperLU's, which the compiled loop calls
        # back to factorise and to solve with, as the Python solver does.
        for solver in SOLVERS:
            with self.subTest(solver=solver):
                a, b = self.same(base.chain(n=70, solver=solver).project())
                self.assertTrue(a.stats['sparse'])
                self.assertIsNotNone(a.stats['fill'])
                self.same(base.chain(n=70, solver=solver, matrix='dense').project())
                self.same(base.chain(n=70, solver=solver, jacobian='numeric').project())

    def test_a_jacobian_differenced_without_a_pattern(self) -> None:
        for solver in SOLVERS:
            with self.subTest(solver=solver):
                self.same(base.chain(solver=solver).project(), no_pattern)
                self.same(base.peaked(solver=solver).project(), no_pattern)
                self.same(base.chain(n=70, solver=solver, matrix='sparse').project(), no_pattern)

    def test_histories_that_outgrow_their_room(self) -> None:
        from kompartment.engine.compiled import model as compiled_model
        was = compiled_model.HISTORY_CAPACITY
        compiled_model.HISTORY_CAPACITY = 4
        try:
            for solver in SOLVERS:
                with self.subTest(solver=solver):
                    a, b = self.same(base.peaked(solver=solver).project())
                    self.assertGreater(len(b.system.MEM[0].history.t), 4)
                    self.same(base.oscillating(solver=solver).project())
        finally:
            compiled_model.HISTORY_CAPACITY = was

    def test_failures_say_the_same(self) -> None:
        for solver in SOLVERS:
            with self.subTest(solver=solver, failure='steps'):
                e = self.same(base.chain(solver=solver, max_steps=20).project())
                self.assertIsInstance(e, SolverError)
                self.assertEqual(e.code, 'steps')
            with self.subTest(solver=solver, failure='blow-up'):
                e = self.same(base.blowup(solver=solver).project())
                self.assertIsInstance(e, SolverError)
                self.assertEqual(e.code, 'tolerance')

    def test_what_the_equations_raise_is_raised_alike(self) -> None:
        # The model's own error, handed on by the adapter as a SolverError.
        cases = {
            'transport_point(1, 2, 3, time/5 - 0.2)': 'lower than zero',
            'transport_sum(1, 2, 3, 0.5 - time/4, 0.6)': 'starts at',
            'interpolationUseEndValues(time, 1, 2, 3)': 'x, y pairs',
            'interpolationUseEndValues(time, 1, 2, A/0 - A/0, 3)': 'no x value',
        }
        for equation, said in cases.items():
            for solver in SOLVERS:
                with self.subTest(equation=equation, solver=solver):
                    e = self.same(base.failing(equation, solver=solver).project())
                    self.assertIsInstance(e, SolverError)
                    self.assertEqual(e.code, 'failed')
                    self.assertIn(said, str(e))


@needs_numba
class Behaviour(unittest.TestCase):
    def runs(self, project: Project, **kw: Any) -> Tuple[Any, Any]:
        out = []
        for compiled in (False, 'auto'):
            try:
                out.append(('ok', run(project, system=build_system(project), compiled=compiled, **kw)))
            except Exception as e:  # noqa: BLE001 - compared by the caller
                out.append(('error', e))
        return out[0], out[1]

    def test_progress_is_told_the_same(self) -> None:
        for solver in SOLVERS:
            project = base.chain(solver=solver, end_time=5000, rtol=1e-9).project()
            seen: Dict[Any, list] = {False: [], 'auto': []}
            for compiled in seen:
                res = run(project, system=build_system(project), compiled=compiled,
                          on_progress=lambda fraction, t, c=compiled: seen[c].append((fraction, t)))
                self.assertEqual(res.stats['compiled'], compiled == 'auto')
            with self.subTest(solver=solver):
                self.assertTrue(seen[False])
                self.assertEqual(seen[False], seen['auto'])

    def test_stopping_stops_at_the_same_step(self) -> None:
        for solver in SOLVERS:
            project = base.chain(solver=solver, end_time=5000, rtol=1e-9).project()
            for after in (1, 7, 50):
                asked = {False: [0], 'auto': [0]}
                caught = {}
                for compiled in asked:
                    def signal(c: Any = compiled) -> bool:
                        asked[c][0] += 1
                        return asked[c][0] > after
                    with self.assertRaises(SolverError) as ctx:
                        run(project, system=build_system(project), compiled=compiled, on_progress=lambda f, t: None,
                            signal=signal)
                    caught[compiled] = (str(ctx.exception), ctx.exception.code, ctx.exception.t, asked[compiled][0])
                with self.subTest(solver=solver, after=after):
                    self.assertEqual(caught[False], caught['auto'])
                    self.assertEqual(caught['auto'][1], 'aborted')

    def test_an_error_in_the_progress_is_handed_on_alike(self) -> None:
        def boom(fraction: float, t: float) -> None:
            if t > 1:
                raise KeyError('from the progress')
        for solver in SOLVERS:
            project = base.chain(solver=solver, end_time=5000, rtol=1e-9).project()
            (ka, a), (kb, b) = self.runs(project, on_progress=boom)
            with self.subTest(solver=solver):
                self.assertEqual((ka, kb), ('error', 'error'))
                self.assertEqual((type(a), str(a), a.code, a.t), (type(b), str(b), b.code, b.t))

    def test_an_analytic_jacobian_that_raises(self) -> None:
        # The model's Jacobian, worked out in Python and called back: what it
        # raises is handed on as the adapter hands it on.
        def failing_jacobian(system: Any) -> None:
            evaluate = system.jacobian['evaluate']

            def evaluated(t: float, y: np.ndarray) -> Any:
                if t > 2:
                    raise ZeroDivisionError('from the Jacobian')
                return evaluate(t, y)
            system.jacobian = dict(system.jacobian, evaluate=evaluated)
        for solver in SOLVERS:
            project = base.chain(n=12, solver=solver).project()
            out = []
            for compiled in (False, 'auto'):
                system = build_system(project)
                failing_jacobian(system)
                with self.assertRaises(SolverError) as ctx:
                    run(project, system=system, compiled=compiled)
                out.append((str(ctx.exception), ctx.exception.code, ctx.exception.t))
            with self.subTest(solver=solver):
                self.assertEqual(out[0], out[1])
                self.assertEqual(out[1][:2], ('from the Jacobian', 'failed'))

    def test_every_julia_run_takes_the_compiled_loop(self) -> None:
        for solver in SOLVERS:
            project = base.chain(solver=solver).project()
            res = run(project, system=build_system(project), compiled=True)
            with self.subTest(solver=solver):
                self.assertTrue(res.stats['compiled'])
                self.assertTrue(res.stats['compiled_loop'])
                self.assertNotIn('compiled_loop_why', res.stats)

    def test_other_arithmetic_keeps_the_python_loop(self) -> None:
        # A Python solver whose pow or dense LU has been replaced -- as
        # test_engine_julia's BitIdentity puts the application's in -- is no
        # longer the one the loop ports: the run takes the Python loop, on the
        # compiled model, and computes as it was told.
        from kompartment.engine.solvers.julia import controller, linalg
        jpow, factor = controller.jpow, linalg.DenseLU.factor
        replacements = {'pow': (controller, 'jpow', lambda x, y: jpow(x, y)),
                        'dense LU': (linalg.DenseLU, 'factor', lambda lu, a: factor(lu, a))}
        project = base.chain(solver='rodas5p').project()
        for label, (target, name, value) in replacements.items():
            with self.subTest(replaced=label), mock.patch.object(target, name, value):
                res = run(project, system=build_system(project), compiled=True)
                self.assertTrue(res.stats['compiled'])
                self.assertFalse(res.stats['compiled_loop'])
        res = run(project, system=build_system(project), compiled=True)
        self.assertTrue(res.stats['compiled_loop'])

    def test_orders_that_are_not_whole_numbers_are_refused(self) -> None:
        # An order is which formula a step takes, and 2.5 is none: refused as
        # it is set and as a model is loaded, so that no loop ever meets one.
        for key in ('min_order', 'max_order'):
            said = f"'2.5' is not a {key.replace('_', ' ')}: a whole number between 1 and 5"
            with self.subTest(key=key):
                with self.assertRaises(kp.EditError) as caught:
                    base.chain(solver='qndf', **{key: 2.5})
                self.assertEqual(str(caught.exception), said)
                with self.assertRaises(ValidationError) as loaded:
                    base.chain(solver='qndf').project(**{key: 2.5})
                self.assertEqual(str(loaded.exception), said)
                self.assertTrue(run(base.chain(solver='qndf', **{key: 3.0}).project()).stats['compiled_loop'])


@needs_numba
class DefaultAlgorithm(unittest.TestCase):
    """What came with the default algorithm, on the compiled loop: the
    explicit methods, Rosenbrock23, GMRES, the switch between methods and
    ``auto``'s hand-off to the compiled NDF -- every run the Python loop's,
    to the last bit."""

    same = Identical.same
    _same = base.Identical.same

    def raw(self, name: str, solver: str, **sim: Any) -> Project:
        raw = example(name)
        raw['simulation'].update(solver=solver, **sim)
        return Project(raw)

    def test_made_up_models(self) -> None:
        for solver in NEW:
            for label, model in (('chain', base.chain), ('peaked', base.peaked), ('resting', base.resting),
                                 ('drained', base.drained)):
                if label == 'drained' and solver in EXPLICIT:
                    continue
                with self.subTest(model=label, solver=solver):
                    self.same(model(solver=solver).project())

    def test_every_function_of_the_language(self) -> None:
        for nuclides in (False, True):
            for solver in NEW:
                with self.subTest(nuclides=nuclides, solver=solver):
                    self.same(base.functions(nuclides, solver=solver).project())

    def test_discrete_events(self) -> None:
        for solver in NEW:
            with self.subTest(solver=solver):
                # The explicit methods take larger steps, which carry a pair
                # of the tank's crossings inside one step: 19 events, not 21.
                a, _ = self.same(base.oscillating(solver=solver).project())
                self.assertEqual(a.stats['events'], 21 if solver in ('fbdf_krylov', 'rosenbrock23') else 19)
            with self.subTest(solver=solver, model='recorders'):
                a, _ = self.same(self.raw('recorders', solver))
                self.assertEqual(a.stats['events'], 1)
            for spacing in ('both', 'solver'):
                with self.subTest(solver=solver, spacing=spacing):
                    self.same(base.oscillating(solver=solver, spacing=spacing).project())

    def test_the_clock_worked_out_every_min_change_time(self) -> None:
        for solver in NEW:
            with self.subTest(solver=solver):
                self.same(base.clocked(solver=solver, min_change_time=0.7).project())

    def test_bundled_examples(self) -> None:
        for name in ('biosphere', 'decay-chain', 'landscape', 'waste-packages', 'lookup-driver', 'four-compartment',
                     'scenarios', 'recorders'):
            for solver in NEW:
                if solver in EXPLICIT and name == 'biosphere':
                    continue
                with self.subTest(name=name, solver=solver):
                    self.same(self.raw(name, solver))

    def test_farfield(self) -> None:
        # 1581 states: `auto` hands the run to the NDF, sparse; the switch
        # takes FBDF by GMRES, as the matrix-free FBDF itself, on a shorter span.
        a, _ = self.same(self.raw('farfield', 'auto', end_time=2e4))
        self.assertTrue(a.stats['sparse'])
        self.assertEqual(list(a.stats['steps_by']), ['Vern7', 'NDF'])
        for solver in ('auto_julia', 'fbdf_krylov'):
            with self.subTest(solver=solver):
                a, _ = self.same(self.raw('farfield', solver, end_time=50))
                self.assertGreater(a.stats['krylov_iters'], 0)
                self.assertEqual((a.stats['npds'], a.stats['ndecomps'], a.stats['sparse']), (0, 0, False))

    def test_the_switch_on_each_stiff_side(self) -> None:
        """DifferentialEquations.jl's switch to each of its stiff methods, by
        the size of the system and the tolerance, and back: steps by
        method, switches, which method the carry says it ended on."""
        cases = [(3, {}, ['Tsit5', 'Rosenbrock23']), (12, {'rtol': 1e-7}, ['Vern7', 'Rodas5P']),
                 (70, {}, ['Tsit5', 'FBDF']), (600, {'end_time': 2}, ['Tsit5', 'KrylovFBDF'])]
        for n, sim, methods in cases:
            with self.subTest(n=n, **sim):
                a, _ = self.same(stiff(n, solver='auto_julia', **sim).project())
                self.assertEqual(list(a.stats['steps_by']), methods)
                self.assertGreaterEqual(a.stats['switches'], 1)
                self.assertEqual(sum(a.stats['steps_by'].values()), a.stats['nsteps'] - a.stats['nfailed'])

    def test_auto_hands_the_run_to_the_ndf(self) -> None:
        """``auto``: the explicit start, the hand-off where it turns stiff and
        the compiled NDF over the rest -- rows, counts and the steps as output
        put together as the adapter puts them; the NDF from the start after
        an event (the carry) and where the tables turn more than a hundred
        times; the explicit methods landing on the tables' corners."""
        for n in (3, 70, 600):
            with self.subTest(n=n):
                a, _ = self.same(stiff(n, solver='auto', end_time=2 if n == 600 else 20).project())
                self.assertEqual((list(a.stats['steps_by'])[1], a.stats['switches']), ('NDF', 1))
        for spacing in ('both', 'solver'):
            with self.subTest(spacing=spacing):
                a, _ = self.same(stiff(solver='auto', spacing=spacing).project())
                self.assertGreater(a.stats['solver_points'], 50)
        for extra in (dict(bdf=True), dict(max_order=2), dict(norm_control=True), dict(stagnation_tol=1e-3),
                      dict(error_norm='max'), dict(auto_abstol=True), dict(initial_step=1e-4), dict(max_step=0.5),
                      dict(jacobian='numeric'), dict(matrix='dense'), dict(non_negative=False)):
            with self.subTest(**extra):
                a, _ = self.same(stiff(solver='auto', **extra).project())
                self.assertEqual(list(a.stats['steps_by'])[-1], 'BDF' if extra.get('bdf') else 'NDF')
        with self.subTest(model='ticking'):
            a, _ = self.same(ticking('auto').project())
            self.assertEqual((a.stats['events'], a.stats['switches']), (1, 1))
        for points, by in ((12, ['Vern7']), (150, ['NDF'])):
            with self.subTest(corners=points):
                a, _ = self.same(cornered(points, solver='auto').project())
                self.assertEqual(list(a.stats['steps_by']), by)
        with self.subTest(model='ticking', solver='auto_julia'):
            a, _ = self.same(ticking('auto_julia').project())
            self.assertEqual(list(a.stats['steps_by']), ['Tsit5', 'Rosenbrock23'])

    def test_solver_settings(self) -> None:
        settings = [dict(auto_abstol=True), dict(matrix='dense'), dict(matrix='sparse'), dict(jacobian='numeric'),
                    dict(max_order=2), dict(initial_step=1e-3), dict(max_step=0.5), dict(error_norm='max'),
                    dict(newton_kappa=1e-2), dict(max_jac_age=3), dict(below_tol_run=3), dict(non_negative=False)]
        for solver in NEW:
            for extra in settings:
                with self.subTest(solver=solver, **extra):
                    self.same(base.chain(solver=solver, **extra).project())
                    if solver not in EXPLICIT:
                        self.same(stiff(solver=solver, **extra).project())

    def test_the_audit(self) -> None:
        # The budgets' rows whole for the Rosenbrocks and the switch, at the
        # diagonal for the NDF and `auto`: the matrix the compiled loops are
        # handed, and its colouring, follow the run's solver.
        from helpers import audit_model
        for solver in ('ndf', 'ros23', 'auto', 'auto_julia', 'rosenbrock23', 'rodas5p', 'fbdf', 'kencarp4'):
            for extra in ({}, {'jacobian': 'numeric'}):
                raw = audit_model(solver)
                raw['simulation'].update(extra)
                with self.subTest(solver=solver, **extra):
                    a, b = self._same(Project(raw))
                    self.assertTrue(b.stats['compiled_loop'])
                    self.assertEqual(a.jacobian.get('budgetRows'), 'diagonal' if solver in ('ndf', 'auto') else 'exact')

    def test_histories_that_outgrow_their_room(self) -> None:
        # Made again from the start with more room: `auto`'s carry starts
        # afresh with the run, as on the Python path, which never restarts.
        from kompartment.engine.compiled import model as compiled_model
        was = compiled_model.HISTORY_CAPACITY
        compiled_model.HISTORY_CAPACITY = 4
        try:
            for solver in NEW:
                with self.subTest(solver=solver):
                    a, b = self.same(base.peaked(solver=solver).project())
                    self.assertGreater(len(b.system.MEM[0].history.t), 4)
                    self.same(base.oscillating(solver=solver).project())
            for solver in ('auto', 'auto_julia'):
                with self.subTest(solver=solver, model='ticking'):
                    self.same(ticking(solver).project())
        finally:
            compiled_model.HISTORY_CAPACITY = was

    def test_failures_say_the_same(self) -> None:
        for solver in NEW:
            with self.subTest(solver=solver, failure='steps'):
                # `auto`'s NDF is handed what the explicit start left of the budget.
                e = self.same(stiff(solver=solver, max_steps=60).project())
                self.assertIsInstance(e, SolverError)
                self.assertEqual(e.code, 'steps')
            with self.subTest(solver=solver, failure='blow-up'):
                e = self.same(base.blowup(solver=solver).project())
                self.assertIsInstance(e, SolverError)

    def test_what_the_equations_raise_is_raised_alike(self) -> None:
        # The model's own error: handed on by the adapter as a SolverError,
        # or, from `auto`'s NDF, as the NDF hands it on.
        cases = {
            'transport_point(1, 2, 3, time/5 - 0.2)': 'lower than zero',
            'interpolationUseEndValues(time, 1, 2, 3)': 'x, y pairs',
        }
        for equation, said in cases.items():
            for solver in NEW:
                with self.subTest(equation=equation, solver=solver):
                    e = self.same(base.failing(equation, solver=solver).project())
                    self.assertIn(said, str(e))

    def test_progress_and_stopping(self) -> None:
        # The progress told, and a stop asked for, at the same points: in the
        # explicit start and in the NDF after it, whose fractions are of the
        # whole span.
        for solver in NEW:
            for label, project in (('chain', base.chain(solver=solver, end_time=5000, rtol=1e-9).project()),
                                   ('stiff', stiff(solver=solver, rtol=1e-8).project())):
                if label == 'stiff' and solver in EXPLICIT:
                    continue
                seen: Dict[Any, list] = {False: [], 'auto': []}
                for compiled in seen:
                    run(project, system=build_system(project), compiled=compiled,
                        on_progress=lambda fraction, t, c=compiled: seen[c].append((fraction, t)))
                with self.subTest(solver=solver, model=label):
                    self.assertTrue(seen[False])
                    self.assertEqual(seen[False], seen['auto'])
                for after in (3, 40):
                    asked = {False: [0], 'auto': [0]}
                    caught = {}
                    for compiled in asked:
                        def signal(c: Any = compiled) -> bool:
                            asked[c][0] += 1
                            return asked[c][0] > after
                        with self.assertRaises(SolverError) as ctx:
                            run(project, system=build_system(project), compiled=compiled,
                                on_progress=lambda f, t: None, signal=signal)
                        caught[compiled] = (str(ctx.exception), ctx.exception.code, ctx.exception.t, asked[compiled][0])
                    with self.subTest(solver=solver, model=label, after=after):
                        self.assertEqual(caught[False], caught['auto'])
                        self.assertEqual(caught['auto'][1], 'aborted')

    def test_every_run_takes_the_compiled_loop(self) -> None:
        for solver in NEW:
            project = stiff(solver=solver).project()
            res = run(project, system=build_system(project), compiled=True)
            with self.subTest(solver=solver):
                self.assertTrue(res.stats['compiled'])
                self.assertTrue(res.stats['compiled_loop'])
                self.assertNotIn('compiled_loop_why', res.stats)

    def test_v8s_log10(self) -> None:
        # The starting step's p-th root goes through V8's Math.log10, ported
        # to the compiled loop from kompartment.jsmath: the same bits.
        from kompartment import jsmath
        from kompartment.engine.compiled import julia as cj
        rng = np.random.default_rng(20261003)
        xs = np.concatenate([10.0 ** rng.uniform(-320, 308, 20000), rng.uniform(0, 4, 5000),
                             2.0 ** np.arange(-1074, 1024),
                             [0.0, -0.0, 1.0, 10.0, 1e-308, 5e-324, np.inf, -1.0, np.nan, 0.99999999999999989]])
        mine = np.array([cj._v8_log10(float(x)) for x in xs])
        theirs = np.array([jsmath.log10(float(x)) for x in xs])
        self.assertTrue(np.array_equal(mine, theirs, equal_nan=True))
        self.assertTrue(np.array_equal(np.signbit(mine), np.signbit(theirs)))


@needs_numba
class Lapack(unittest.TestCase):
    def test_the_factorisations_are_scipys(self) -> None:
        # The compiled loop factorises a dense W, and Radau's complex one, by
        # LAPACK at the addresses SciPy publishes: bit for bit what lu_factor
        # and lu_solve give the Python solver, at any alignment of the arrays.
        import scipy.linalg as la

        from kompartment.engine.compiled import julia as cj
        rng = np.random.default_rng(20261002)
        trans = np.array([ord('N')], dtype=np.uint8)
        for n in (1, 2, 5, 16, 33, 100):
            for rep in range(4):
                A = rng.standard_normal((n, n)) * np.exp(2 * rng.standard_normal((n, n)))
                A[rng.random((n, n)) < 0.5] = 0.0
                A += np.diag(10 * rng.standard_normal(n))
                b = rng.standard_normal(n)
                lints = np.array([n, 0, 1], dtype=np.int32)
                ipiv = np.zeros(n, dtype=np.int32)
                for real in (True, False):
                    M = A if real else A + 1j * np.diag(rng.standard_normal(n))
                    v = b if real else b + 1j * rng.standard_normal(n)
                    lu, piv = la.lu_factor(M, check_finite=False)
                    x = la.lu_solve((lu, piv), v, check_finite=False)
                    # Held by columns, from an offset into a larger buffer.
                    raw = np.zeros(n * n + rep, dtype=M.dtype)
                    a = raw[rep:].reshape(n, n)
                    a[:] = M.T
                    xs = v.copy()
                    with self.subTest(n=n, rep=rep, real=real):
                        self.assertTrue((cj._getrf if real else cj._zgetrf)(a, ipiv, lints))
                        (cj._getrs if real else cj._zgetrs)(a, ipiv, lints, trans, xs)
                        self.assertTrue(np.array_equal(np.ascontiguousarray(a.T).view(np.int64),
                                                       np.ascontiguousarray(lu).view(np.int64)))
                        self.assertEqual((ipiv - 1).tolist(), piv.tolist())
                        self.assertTrue(np.array_equal(xs.view(np.int64), x.view(np.int64)))

    def test_a_zero_pivot_is_singular(self) -> None:
        from kompartment.engine.compiled import julia as cj
        a = np.array([[1.0, 2.0], [2.0, 4.0]])
        self.assertFalse(cj._getrf(np.ascontiguousarray(a.T), np.zeros(2, dtype=np.int32),
                                   np.array([2, 0, 1], dtype=np.int32)))


if __name__ == '__main__':
    unittest.main()
