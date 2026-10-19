"""The analytic Jacobian worked out compiled (``engine/compiled/jacobian.py``).

The Python one (``engine/analytic.py``) is the reference: the compiled one
must give its numbers to the last bit -- at many states of every bundled
example, and of made-up models that reach every function with a derivative
rule, numpy's short cuts in its powers, tables read at the state, every
availability scheme, the recorders, a far-field path on cells and the clock's
ends -- and decline where it declines. A run whose loop works it out is then
the Python run, to the last bit; one it does not take is called back, and
says why.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, Callable, Dict

import numpy as np

from helpers import EXAMPLES, audit_model, example

import kompartment as kp
from kompartment.engine.builder import build_system
from kompartment.engine.project import Project
from kompartment.engine.runner import run

try:
    import numba  # noqa: F401
    from kompartment.engine.compiled import jacobian as cj
    from kompartment.engine.compiled.run import compiled_model
    NUMBA = True
except ImportError:  # pragma: no cover - numba is optional
    NUMBA = False

needs_numba = unittest.skipUnless(NUMBA, 'needs numba')

#: Every function with a derivative rule, applied to the state, each in an
#: expression of its own -- so that a slot's gradient is that one rule's
#: tangent, which a sum would round a last-bit difference out of -- and the
#: staircases and the functions without a rule, where no derivative goes
#: through them.
RULES = {
    'abs': 'abs(A - 0.5)', 'sqrt': 'sqrt(1 + A)', 'exp': 'exp(-A)', 'log': 'log(1 + A)', 'log10': 'log10(2 + A)',
    'log2': 'log2(3 + A)', 'hypot': 'hypot(A, B + 1)', 'hypot2': 'hypot(2, A)', 'sin': 'sin(A)', 'cos': 'cos(A)',
    'tan': 'tan(0.5 * A)', 'asin': 'asin(A / (2 + A))', 'acos': 'acos(A / (3 + A))', 'atan': 'atan(A)',
    'atan2': 'atan2(A, 1 + B)', 'atan2b': 'atan2(1 + B, A)', 'sinh': 'sinh(A)', 'cosh': 'cosh(A)',
    'tanh': 'tanh(3 * A)', 'asinh': 'asinh(A)', 'acosh': 'acosh(1.5 + A)', 'atanh': 'atanh(0.5 * A / (1 + A))',
    'erf': 'erf(A)', 'erfc': 'erfc(A)', 'mod': 'mod(A + time, 0.7)', 'mod2': 'mod(3, 1 + A)',
    'rem': 'rem(A + 1, 0.3)', 'rem2': 'rem(2, 1 + A)', 'ulp': 'ulp(A) * 1e10', 'rampdown': 'rampDown(A, 0.2, 0.9)',
    'rampup': 'rampUp(A, 0.9, 0.1)', 'smoothdown': 'smoothDown(A, 0.5, 2)', 'smoothup': 'smoothUp(A + 0.1, 0.5, 0.25)',
    'bq2mole': 'bq2mole(A + 1, 30) * 1e20', 'bq2mole2': 'bq2mole(30, A + 1) * 1e20',
    'mole2bq': 'mole2bq(A + 1, 1e5) * 1e-20', 'mole2bq2': 'mole2bq(B + 1e-12, 1e5 + A) * 1e-20',
    'power': 'power(A + 1, 2.5)', 'cube': '(A + 1)^3', 'pk2': '(A + 1)^k2', 'exponent': '2^A',
    'both': '(A + 1)^(1 + A)', 'recip': 'power(A + 1, -1)', 'root': '(A + 1)^0.5', 'one': '(A + 1)^1',
    'zero': '(A + 1)^0', 'square': '(A + 1)^2', 'pkh': 'power(B + 1, kh)', 'min': 'min(A, 0.5, B)',
    'max': 'max(A * A, 0.3)', 'sum': 'sum(A, B, 1)', 'mean': 'mean(A, B * B)', 'prod': 'prod(A, 1 + B, 2)',
    'prod2': 'prod(2, A, B)', 'neg': '-A * A', 'quot': '1 / (1 + A)', 'diff': '(1 - A) * (2 - B)',
    'stairs': 'ceil(A) + floor(2 * A) + round(A * 3) + fix(A - 0.5) + sign(A - 0.5) + not(A > 0.5) '
              '+ and(A > 0.2, B < 1) + or(A > 2, B > 0.1) + nand(A, B) + nor(A, 0) + xor(A > 0.5, B > 0.2, 1)',
    'others': 'percentile(30, time, 2, 0.5) * A + factorial(3) * A + binomial(5, 2) * B',
    'cond': 'if(time > 3, A, B) + if(A > 0.5, A * A, 2 * B)',
    'compare': '(A < 0.4) * B + (A >= 0.3) + (A == 1) + (A ~= 1)',
}


def rules(nuclides: bool = False, **sim: Any) -> Project:
    """RULES read by a transfer's rate; with ``nuclides``, every block over three of them."""
    m = kp.Model.new('Rules')
    m.simulation.update(end_time=20, **sim)
    if nuclides:
        m.add_nuclides(['Cs-137', 'Sr-90', 'I-129'])
    m.add_compartment('A', initial='1')
    m.add_compartment('B')
    if nuclides:
        m['A'].set_value('2', at='Sr-90')
    m.add_parameter('k', 0.3)
    m.add_parameter('k2', 2)
    m.add_parameter('kh', 0.5)
    for name, eq in RULES.items():
        m.add_expression(f'f_{name}', eq)
    total = ' + '.join(f'1e-3 * f_{n}' for n in RULES)
    m.add_transfer('A', 'B', rate=f'k * (1 + 0.01 * ({total}))')
    return m.project()


def powers(**sim: Any) -> Project:
    """Powers numpy works out by a short cut where the exponent is one value
    for every element -- a square root, a reciprocal, a square -- and by the C
    library's pow where there is one per element, on 400 nuclides: which of
    the two a tangent takes shows in about one argument in a thousand. Their
    tangents read them where a square root or a smooth step is taken of a
    power, and where the exponent less one is 0.5 or -1."""
    names = [f'Qa-{100 + i}' for i in range(400)]
    exprs = {
        'sq': 'sqrt((A + 1)^k05) + sqrt((A + 1)^kv05)',
        'rec': 'sqrt((A + 1)^km1) + sqrt((A + 1)^kvm1)',
        'p15': '(A + 1)^k15', 'pv15': '(A + 1)^kv15', 'p0': '(A + 1)^k0', 'pv0': '(A + 1)^kv0',
        'cpower': 'power(A + 1, k15) + power(A + 1, kv15)',
        'smooth': 'smoothDown(A + 1, 1.5, ks) + smoothDown(A + 1, 1.5, kvs) + smoothUp(A + 0.5, 1.2, 0.25)',
        'lit': 'sqrt((A + 1)^0.5) + sqrt((A + 1)^-1) + sqrt((A + 1)^(0.5 + 0 * kv05))',
    }
    scalar = {'k05': 0.5, 'km1': -1, 'k15': 1.5, 'k0': 0, 'ks': 0.25, 'k': 0.1}
    vector = {'kv05': 0.5, 'kvm1': -1, 'kv15': 1.5, 'kv0': 0, 'kvs': 0.25}
    raw = {
        'name': 'Powers', 'nuclides': names, 'half_lives': {n: 1 + 0.037 * i for i, n in enumerate(names)},
        'chains': [],
        'simulation': {'start_time': 0, 'end_time': 30, 'output_points': 31, 'solver': 'ndf', 'rtol': 1e-8,
                       'abstol': 1e-14, 'time_unit': 'year', **sim},
        'parameters': ([{'name': n, 'value': v, 'index_lists': []} for n, v in scalar.items()]
                       + [{'name': n, 'value': v, 'index_lists': ['Radionuclides']} for n, v in vector.items()]),
        'compartments': [{'name': 'A', 'initial': '1', 'index_lists': ['Radionuclides']},
                         {'name': 'B', 'initial': '0', 'index_lists': ['Radionuclides']}],
        'expressions': [{'name': n, 'equation': eq, 'index_lists': ['Radionuclides']} for n, eq in exprs.items()],
        'transfers': [{'name': 'T', 'from': 'A', 'to': 'B', 'index_lists': ['Radionuclides'],
                       'rate': f'k * (1 + 1e-3 * ({" + ".join(exprs)}))'}],
    }
    return Project(raw)


def tables(nuclides: bool = False, **sim: Any) -> Project:
    """Lookup tables read at the state: linear, extrapolated, a step, cyclic
    and, with ``nuclides``, one per nuclide."""
    m = kp.Model.new('Tables')
    m.simulation.update(end_time=20, **sim)
    if nuclides:
        m.add_nuclides(['Cs-137', 'Sr-90', 'I-129'])
    m.add_compartment('A', initial='1')
    m.add_compartment('B')
    if nuclides:
        m['A'].set_value('2', at='Sr-90')
    m.add_lookup('Kd', [[0, 0.1], [0.5, 0.5], [1.0, 0.3], [1.5, 0.05], [3, 0.2]], argument='x')
    m.add_lookup('Ke', [[0, 0.1], [1.0, 0.4], [2.0, 0.6]], interpolation='extrapolate', argument='x')
    m.add_lookup('Ks', [[0, 0.1], [1.0, 0.4], [2.0, 0.6]], interpolation='below', argument='x')
    m.add_lookup('Kc', [[0, 0.1], [0.7, 0.4], [2.0, 0.6]], cyclic=True, argument='x')
    equation = 'Kd(A) + Ke(2 * A - 1) + Ks(A) + Kc(3 * A) + Kd(time / 10) * A'
    if nuclides:
        m.add_lookup('Kn', [[0, 0.1], [0.7, 0.4], [2.0, 0.6]], argument='x', index_lists=['Radionuclides'])
        equation += ' + Kn(A) + Kn(time / 10) * A'
    m.add_expression('r', equation)
    m.add_parameter('k', 0.3)
    m.add_transfer('A', 'B', rate='k * r')
    return m.project()


def availability(scheme: str, **sim: Any) -> Project:
    """A transfer of the biosphere example limited by what is available
    (``scheme``), or one of waste-packages' shared over its nuclides."""
    shared = scheme.startswith('shared')
    raw = example('waste-packages' if shared else 'biosphere')
    raw['simulation'].update(sim)
    raw['parameters'] += [{'name': 'Lim', 'value': 1e3 if shared else 0.02, 'index_lists': []},
                          {'name': 'Cap', 'value': 0.5, 'index_lists': []},
                          {'name': 'Bot', 'value': 2.0, 'index_lists': []}]
    schemes = {'limit': {'scheme': 'limit', 'limit': 'Lim * 2'},
               'unavailable': {'scheme': 'limit', 'limit': 'Lim', 'unavailable': True},
               'langmuir': {'scheme': 'langmuir', 'top': 'Cap', 'bottom': 'Bot'},
               'shared_limit': {'scheme': 'shared_limit', 'limit': 'Lim', 'over': 'Radionuclides'},
               'shared_langmuir': {'scheme': 'shared_langmuir', 'top': 'Cap', 'bottom': 'Bot',
                                   'over': 'Radionuclides'}}
    if shared:
        t = next(t for t in raw['transfers']
                 if t.get('from') and t['from'] != 'Canisters' and t.get('index_lists'))
    else:
        t = raw['transfers'][2]
    t['availability'] = schemes[scheme]
    return Project(raw)


def clocks(**sim: Any) -> Project:
    """A rate that reads the run's start and end with the state."""
    raw = {
        'name': 'Clocks', 'nuclides': [], 'chains': [],
        'simulation': {'start_time': 5, 'end_time': 30, 'output_points': 31, 'solver': 'ndf', 'time_unit': 'year',
                       **sim},
        'parameters': [{'name': 'k', 'value': 0.1, 'index_lists': []}],
        'compartments': [{'name': 'A', 'initial': '1', 'index_lists': []},
                         {'name': 'B', 'initial': '0', 'index_lists': []}],
        'expressions': [{'name': 'e', 'equation': 'A * start_time() + A * A * end_time() / (1 + time)',
                         'index_lists': []}],
        'transfers': [{'name': 'T', 'from': 'A', 'to': 'B', 'index_lists': [], 'rate': 'k * (1 + e)'}],
    }
    return Project(raw)


def made_up() -> Dict[str, Callable[[], Project]]:
    from test_engine_compiled import chain, clocked, farfield, oscillating, peaked, resting
    models: Dict[str, Callable[[], Project]] = {
        'rules': rules, 'rules over nuclides': lambda: rules(True), 'powers': powers, 'tables': tables,
        'tables over nuclides': lambda: tables(True), 'clocks': clocks, 'audit': lambda: Project(audit_model()),
        'peaked': lambda: peaked().project(), 'oscillating': lambda: oscillating().project(),
        'resting': lambda: resting().project(), 'clocked': lambda: clocked().project(),
        'chain': lambda: chain().project(), 'far field on cells': farfield,
    }
    for scheme in ('limit', 'unavailable', 'langmuir', 'shared_limit', 'shared_langmuir'):
        models[f'availability: {scheme}'] = (lambda s: lambda: availability(s))(scheme)
    return models


def program_of(project: Project) -> Any:
    """(system, the analytic Jacobian, the compiled model, the program, why not)."""
    system = build_system(project)
    jac = system.jacobian
    if not jac.get('available'):
        return system, None, None, None, jac.get('reason')
    an = jac['evaluate'].__self__
    cm = compiled_model(system)
    system.prime_recorders(system.start_time, system.initial_state())
    cm.load()
    jp, why = cj.program(an, cm)
    return system, an, cm, jp, why


@needs_numba
class SameNumbers(unittest.TestCase):
    def check(self, project: Project, states: int = 30, seed: int = 0) -> int:
        """The program against the Python Jacobian at ``states`` states; how many were compared."""
        system, an, cm, jp, why = program_of(project)
        self.assertIsNotNone(an, why)
        self.assertIsNotNone(jp, why)
        rng = np.random.default_rng(seed)
        y0 = system.initial_state()
        t0, t1 = system.start_time, system.end_time
        compared = 0
        for k in range(states):
            t = t0 + (t1 - t0) * rng.uniform() if k else t0
            y = y0 * rng.uniform(0.2, 2, y0.size) + 10 ** rng.uniform(-3, 1, y0.size) * rng.uniform(0, 1, y0.size)
            if k == 0:
                y = y0.copy()
            if k % 5 == 4:
                y[rng.integers(0, y.size)] = 0.0
            system._clock_at = np.nan
            want = an.evaluate(t, y)
            X = system.X.copy()
            with np.errstate(all='ignore'):
                want_g = an._gradients(y, X, t) if an.g_nnz else np.zeros(0)
            got = cj.jacobian(jp, t, y, X, system.P, cm.W, cm.IW)
            # The gradients first: a last-bit difference in one rule's tangent
            # can round away in the sums the matrix makes of them.
            got_g = cj.gradients(jp)
            differ = np.flatnonzero(want_g.view(np.int64) != got_g.view(np.int64))
            self.assertEqual(differ.size, 0, f'state {k}: gradient entry {differ[:1]} is {got_g[differ[:1]]}, '
                                             f'the Python one\'s {want_g[differ[:1]]}')
            self.assertEqual(got is None, want is None, f'declined at state {k}')
            if want is None:
                continue
            differ = np.flatnonzero(want.view(np.int64) != got.view(np.int64))
            self.assertEqual(differ.size, 0, f'state {k}: entry {differ[:1]} is {got[differ[:1]]}, '
                                             f'the Python Jacobian\'s {want[differ[:1]]}')
            compared += 1
        return compared

    def test_every_example(self) -> None:
        for path in sorted(EXAMPLES.glob('*.json')):
            project = Project(json.loads(path.read_text('utf-8')))
            if not build_system(project).jacobian.get('available'):
                continue
            with self.subTest(example=path.stem):
                self.assertGreater(self.check(project), 20)

    def test_made_up_models(self) -> None:
        for label, make in made_up().items():
            with self.subTest(model=label):
                self.assertGreater(self.check(make()), 20)

    def test_the_clocks_ends_are_read(self) -> None:
        # d/dA of k*(1 + A*T0 + A^2*T1/(1 + t))*A, which reads the run's start and end.
        system, an, cm, jp, _ = program_of(clocks())
        t, y = 7.0, np.array([1.3, 0.2])
        J = cj.jacobian(jp, t, y, (system.evaluate_for_derivative(t, y)).copy(), system.P, cm.W, cm.IW)
        a = y[0]
        e = a * 5 + a * a * 30 / (1 + t)
        exact = 0.1 * (1 + e) + 0.1 * a * (5 + 2 * a * 30 / (1 + t))
        pattern = system.jacobian['pattern']
        at = [p for p in range(pattern.nnz) if pattern.row_idx[p] == 0 and pattern.col_of[p] == 0][0]
        self.assertAlmostEqual(-J[at], exact, places=12)


@needs_numba
class Runs(unittest.TestCase):
    def same(self, project: Project, solver: str) -> Any:
        raw = project.to_json()
        raw['simulation']['solver'] = solver
        out = []
        for compiled in (False, True):
            out.append(run(Project(raw), system=build_system(Project(raw)), compiled=compiled))
        a, b = out
        self.assertTrue(np.array_equal(a.t, b.t))
        ya, yb = np.array(a.y), np.array(b.y)
        self.assertTrue(np.array_equal(ya.view(np.int64), yb.view(np.int64)),
                        f'largest difference {np.max(np.abs(ya - yb))}')
        for key in ('nsteps', 'nfailed', 'nfevals', 'npds', 'ndecomps', 'nsolves'):
            self.assertEqual(a.stats.get(key), b.stats.get(key), key)
        return b

    def test_the_loops_work_it_out(self) -> None:
        models = {'oregonator': lambda: Project(example('oregonator')), 'rules': rules, 'tables': tables,
                  'clocks': clocks, 'availability: langmuir': lambda: availability('langmuir'),
                  'recorders': lambda: Project(example('recorders'))}
        for label, make in models.items():
            # SciPy's solvers take no model with events, and the recorders example has one.
            for solver in ('ndf', 'ros23', 'rodas5p', 'fbdf') + (() if label == 'recorders' else ('scipy_bdf',)):
                with self.subTest(model=label, solver=solver):
                    b = self.same(make(), solver)
                    self.assertTrue(b.stats.get('compiled_jacobian'), b.stats.get('compiled_jacobian_why'))

    def test_what_it_does_not_take_is_called_back(self) -> None:
        from test_engine_compiled import farfield
        cases = {'semi-analytical': ({'method': 'semi-analytical'}, 'semi-analytical'),
                 'moving': ({'tw': '50 * (1 + 0.5 * rampUp(time, 1e3, 1e4))', 'n_f': 8, 'n_m': 8}, 'settings move')}
        for label, (block, said) in cases.items():
            with self.subTest(path=label):
                b = self.same(farfield(**block), 'ndf')
                self.assertIs(b.stats.get('compiled_jacobian'), False)
                self.assertIn(said, b.stats.get('compiled_jacobian_why'))

    def test_a_differenced_jacobian_says_nothing_of_it(self) -> None:
        raw = example('oregonator')
        raw['simulation']['jacobian'] = 'numeric'
        b = self.same(Project(raw), 'ndf')
        self.assertNotIn('compiled_jacobian', b.stats)


if __name__ == '__main__':
    unittest.main()
