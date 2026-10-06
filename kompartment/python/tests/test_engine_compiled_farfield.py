"""A far-field path whose settings move, compiled against Python: the same run, to the last bit.

The rates of a path on cells are worked out again whenever a setting they
follow moves -- with the clock or with the state -- on matched layers laid
out at the run's first instant (``FarfPath.refresh``). The compiled path does
that in compiled code (``engine/compiled/farfield.py``), handing the path to
the Python refresh only to hold the layers it has just laid out, and where a
setting describes no path, which the Python refresh then raises. Every run
here is made on both paths and compared as test_engine_compiled compares
them -- states, statistics, recorders, series and failures, bit for bit --
and the refresh itself is compared call for call on settings drawn at random.
"""

from __future__ import annotations

import math
import unittest
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

import numpy as np

import test_engine_compiled as tec
from helpers import example
from test_engine_compiled import HAVE_NUMBA, farfield, needs_numba

from kompartment.engine.builder import build_system
from kompartment.engine.farfield import FARF_NUCLIDE_KEYS, FarfError, _js_pow
from kompartment.engine.project import Project, ValidationError
from kompartment.engine.runner import run

if HAVE_NUMBA:
    from kompartment.engine.compiled import farfield as cf
    from kompartment.engine.compiled.model import HOOK_REFRESH, HOOKS, CompiledModel

#: A setting of every kind following the clock, as the path's block gives it.
CLOCK = {
    'tw': {'tw': '50 * (1 + 0.5 * rampUp(time, 1e3, 1e4))'},
    'f': {'f': '1e5 * (1 + interpolationUseEndValues(time, 0, 0, 2e4, 1))'},
    'aw': {'surface': 'aw', 'aw': '2000 * (1 + rampUp(time, 1e3, 1e4))'},
    'aperture': {'surface': 'aperture', 'aperture': '0.001 * (1 + rampUp(time, 1e3, 1e4))'},
    'kd_f': {'kd_f': '1e-4 * rampUp(time, 1e3, 1e4)'},
    'kd_m': {'kd_m': 'Kd_matrix * (1 + rampUp(time, 1e3, 1e4))'},
    'de_m': {'de_m': 'De_matrix * (1 + rampUp(time, 1e3, 1e4))'},
    'eps_m': {'eps_m': '0.0018 * (1 + rampUp(time, 1e3, 1e4))'},
    'rho_m': {'rho_m': '2700 * (1 + 0.5 * rampUp(time, 1e3, 1e4))'},
    'pe': {'pe': '10 * (1 + rampUp(time, 1e3, 1e4))'},
    'pen_dep': {'pen_dep': '12.5 * (1 + rampUp(time, 1e3, 1e4))'},
    'pen_dep_0': {'pen_dep_0': '0.001 * (1 + rampUp(time, 1e3, 1e4))'},
}
#: Settings following the state: one the nuclides share, one each has.
STATE = {
    'tw': {'tw': '50 * (1 + Vault[U-238] / 1e12)'},
    'kd_m': {'kd_m': 'Kd_matrix * (1 + Well / (1e3 + Well))'},
}
GRIDS = ('matched', 'reference')


def path(solver: str = 'ndf', sim: Optional[Dict[str, Any]] = None, **block: Any) -> Project:
    """The far-field example as test_engine_compiled shortens it, on 6 x 6
    cells unless ``block`` says otherwise, run with ``solver`` and the
    simulation settings in ``sim``."""
    raw = farfield(**{'n_f': 6, 'n_m': 6, **block}).to_json()
    raw['simulation'].update(solver=solver, **(sim or {}))
    return Project(raw)


def mild(**block: Any) -> Project:
    """The example made mild enough for Dormand-Prince: a well flushed once
    a year, not a thousand times, 4 x 4 cells and a century."""
    raw = path('dp45', n_f=4, n_m=4, **block).to_json()
    raw['simulation']['end_time'] = 100
    for prm in raw['parameters']:
        if prm['name'] == 'well_flow':
            prm['value'] = 1
    return Project(raw)


def two_paths(grid: str) -> Project:
    """The example over a second index list -- a short and a long path, each
    with its own travel time -- so that the block has two combinations of
    three nuclides in a decay chain, each laid out on its own."""
    raw = example('farfield')
    raw['simulation'].update(end_time=2e4)
    raw['index_lists'] = [{'name': 'Paths', 'indices': [{'name': 'Short', 'enabled': True},
                                                        {'name': 'Long', 'enabled': True}]}]
    raw['farfields'][0].update(n_f=6, n_m=6, grid=grid, index_lists=['Radionuclides', 'Paths'],
                               tw='TW_path * (1 + 0.5 * rampUp(time, 1e3, 1e4))')
    for c in raw['compartments']:
        c['index_lists'] = ['Radionuclides', 'Paths']
    for t in raw['transfers']:
        if t.get('index_lists'):
            t['index_lists'] = ['Radionuclides', 'Paths']
    raw['parameters'].append({'name': 'TW_path', 'value': 50, 'index_lists': ['Paths'],
                              'entries': [{'index': {'Paths': 'Long'}, 'value': 120}]})
    raw['expressions'] = []
    return Project(raw)


def handed_over(project: Project, **kw: Any) -> List[float]:
    """The times a compiled run of ``project`` handed its path to the Python
    refresh, through the callback."""
    times: List[float] = []
    hook = CompiledModel._hook

    def counted(self: Any, t: float, code: float) -> int:
        if int(code) % HOOKS == HOOK_REFRESH:
            times.append(t)
        return hook(self, t, code)
    with mock.patch.object(CompiledModel, '_hook', counted):
        res = run(project, system=build_system(project), compiled=True, **kw)
    assert res.stats['compiled']
    return times


@needs_numba
class Moving(unittest.TestCase):
    same = tec.Identical.same

    def test_every_setting_following_the_clock(self) -> None:
        for grid in GRIDS:
            for key, block in CLOCK.items():
                with self.subTest(grid=grid, setting=key):
                    project = path(grid=grid, **block)
                    system = build_system(project)
                    F = system.FARF[0]
                    self.assertTrue(np.all(system.slot_class[F.setting_idx[:, F.keys.index(key)]] == 1))
                    self.same(project)

    def test_settings_following_the_state(self) -> None:
        for grid in GRIDS:
            for key, block in STATE.items():
                with self.subTest(grid=grid, setting=key):
                    self.same(path(grid=grid, **block))

    def test_two_combinations_of_a_decay_chain(self) -> None:
        for grid in GRIDS:
            with self.subTest(grid=grid):
                project = two_paths(grid)
                F = build_system(project).FARF[0]
                self.assertEqual((F.other_width, F.nnuc), (2, 3))
                self.same(project)

    def test_every_solver(self) -> None:
        # Rosenbrock (2,3) takes tens of thousands of steps at the example's
        # tolerance, each a minute's worth on the Python path in the end: a
        # looser one, and output at the example's own times alone.
        series = {'spacing': 'series', 'rtol': 1e-6}
        cases = {'matched': CLOCK['tw'], 'reference': CLOCK['f']}
        for solver in ('ros23', 'radau5', 'scipy_bdf'):
            for grid, block in cases.items():
                with self.subTest(solver=solver, grid=grid):
                    self.same(path(solver, series if solver == 'ros23' else None, grid=grid, **block))
        for grid in GRIDS:
            with self.subTest(solver='dp45', grid=grid):
                self.same(mild(grid=grid, tw='50 * (1 + 0.5 * rampUp(time, 10, 80))'))
        with self.subTest(solver='ros23', setting='the state'):
            self.same(path('ros23', series, grid='reference', **STATE['tw']))

    def test_with_recorders_and_the_clock_every_min_change_time(self) -> None:
        # A recorder: the Python passes lay the layers out at the first
        # instant, priming it, before the compiled run takes the path over
        # -- and hand the path back before an analytic Jacobian reads it.
        for grid in GRIDS:
            raw = path(grid=grid, **CLOCK['tw']).to_json()
            raw['min_maxes'] = [{'name': 'Peak', 'target': 'Total_concentration', 'operation': 'max'}]
            with self.subTest(grid=grid, recorder='min/max'):
                self.same(Project(raw))
            raw = path(grid=grid, **CLOCK['tw']).to_json()
            raw['simulation']['min_change_time'] = 500
            with self.subTest(grid=grid, min_change_time=500):
                self.same(Project(raw))

    def test_runs_one_after_another_on_one_system(self) -> None:
        # As a probabilistic run makes them: X left where the last run
        # ended, a parameter changed, and the layers laid out again at the
        # next run's first instant -- never from what X holds as it starts.
        for grid in GRIDS:
            for key in ('tw', 'pen_dep'):
                project = path(grid=grid, **CLOCK[key])

                def before(system: Any, project: Project = project) -> None:
                    run(project, system=system, compiled='auto')
                    system.P[system.builder.param_by_name['De_matrix'].base] *= 2
                    system.evaluate_invariant()
                with self.subTest(grid=grid, setting=key):
                    self.same(project, before)

    def test_a_setting_that_turns_bad_partway(self) -> None:
        # The same exception, with the same message, at the same evaluation.
        # A sorption on the coating below zero is refused however little
        # below: -1/2000 made 1 + K_d,f a_w zero, and -1e-9 ran.
        cases = {
            'pe': ({'pe': '10 - 20 * (time > 1e4)'}, GRIDS, ('ndf', 'ros23', 'radau5', 'scipy_bdf'), 'Peclet'),
            'kd_f': ({'kd_f': '-(time > 1e4) / 2000'}, GRIDS, ('ndf',),
                     'The sorption on the fracture coating K_d,f must be zero or positive (got -0.0005)'),
            'kd_f, a little': ({'kd_f': '-(time > 1e4) * 1e-9'}, GRIDS, ('ndf',),
                               'The sorption on the fracture coating K_d,f must be zero or positive (got -1e-9)'),
            'eps_m': ({'eps_m': '0.0018 - 0.002 * (time > 1e4)'}, GRIDS, ('ndf',),
                      'The porosity of the rock matrix \u03b5_m must be zero or positive'),
            'de_m': ({'de_m': 'De_matrix * (1 - 2 * (time > 1e4))'}, GRIDS, ('ndf',),
                     'The effective diffusivity in the rock matrix D_e,m must be zero or positive'),
            'pen_dep_0': ({'pen_dep_0': '0.5 * (1 + 4 * (time > 1e4))'}, ('reference',), ('ndf', 'ros23'),
                          'cannot add up'),
            'tw': ({'tw': '50 - 100 * (time > 1e4)'}, ('matched',), ('ndf',), 'F/TW must be positive'),
        }
        for key, (block, grids, solvers, said) in cases.items():
            for grid in grids:
                for solver in solvers:
                    with self.subTest(setting=key, grid=grid, solver=solver):
                        e = self.same(path(solver, grid=grid, **block))
                        self.assertIsInstance(e, Exception)
                        self.assertIn(said, str(e))
                        if solver in ('ndf', 'ros23'):
                            self.assertIsInstance(e, FarfError)

    def test_settings_no_path_has_from_the_start(self) -> None:
        # The layers cannot be laid out at all: a sorption on the coating
        # below zero, refused before the layers are sized by it (it used to
        # reach the penetration scale's square root as a 'math domain error').
        # Written as a number, the model is refused as it is loaded.
        e = self.same(path(kd_f='-1 * (time >= 0)', **CLOCK['tw']))
        self.assertIsInstance(e, FarfError)
        self.assertEqual(str(e), 'The sorption on the fracture coating K_d,f must be zero or positive (got -1)')
        with self.assertRaises(ValidationError) as caught:
            path(kd_f='-1', **CLOCK['tw'])
        self.assertIn('the sorption on the fracture coating K_d,f must be zero or positive (got -1)',
                      str(caught.exception))
        # Laid out once and held: a first layer that no longer fits is never
        # read again on the matched layers, and the run goes on to its end.
        self.same(path(pen_dep_0='0.5 * (1 + 4 * (time > 1e4))'))

    def test_a_refresh_that_succeeds_stays_compiled(self) -> None:
        # Handed to Python once a run on the matched layers -- at the first
        # instant, to hold the layers laid out there -- and never on the
        # reference ones; with a recorder primed in Python, not even once.
        self.assertEqual(handed_over(path(**CLOCK['tw'])), [0.0])
        self.assertEqual(handed_over(path(grid='reference', **CLOCK['f'])), [])
        raw = path(**CLOCK['tw']).to_json()
        raw['min_maxes'] = [{'name': 'Peak', 'target': 'Total_concentration', 'operation': 'max'}]
        self.assertEqual(handed_over(Project(raw)), [])

    def test_no_array_is_frozen_into_the_compiled_code(self) -> None:
        from kompartment.engine.compiled.run import compiled_model
        cm = compiled_model(build_system(two_paths('matched')))
        self.assertEqual(sorted(cm.layout['farf_moving']), [0])
        self.assertEqual([k for k, v in vars(cm.module).items() if isinstance(v, np.ndarray)], [])


# --- the refresh, call for call -------------------------------------------------------------------

#: Settings a path could have, by key, drawn on log scales across what real
#: paths use and well past it.
GOOD = {
    'tw': lambda r: 10 ** r.uniform(0, 3),
    'f': lambda r: 10 ** r.uniform(3, 7),
    'aw': lambda r: 10 ** r.uniform(1, 4),
    'aperture': lambda r: 10 ** r.uniform(-4, -2),
    'kd_f': lambda r: 0.0 if r.random() < 0.3 else 10 ** r.uniform(-7, -3),  # below zero is one no path has
    'kd_m': lambda r: 0.0 if r.random() < 0.2 else 10 ** r.uniform(-5, -1),
    'de_m': lambda r: 10 ** r.uniform(-6, -3),
    'eps_m': lambda r: 10 ** r.uniform(-4, -1),
    'rho_m': lambda r: r.uniform(1000, 3000),
    'pe': lambda r: 10 ** r.uniform(-0.5, 2.5),
    'pen_dep': lambda r: 10 ** r.uniform(-2, 2),
    'pen_dep_0': lambda r: 0.0 if r.random() < 0.5 else 10 ** r.uniform(-6, 0),
}
#: ...and ones no path has.
BAD = (0.0, -0.0, -1.0, math.nan, math.inf, -math.inf)


def draw(r: np.random.Generator, F: Any, X: np.ndarray, keys: Any = None, bad: float = 0.03) -> None:
    """Settings for every slot of path F into X -- each of ``keys`` (all by
    default) drawn afresh, now and then one no path has."""
    for k, key in enumerate(F.keys):
        if keys is not None and key not in keys:
            continue
        for slot in range(F.slots):
            v = GOOD[key](r) if r.random() >= bad else BAD[int(r.integers(len(BAD)))]
            X[F.setting_idx[slot, k]] = v


def flat(F: Any) -> Tuple[np.ndarray, np.ndarray, int, Dict[str, int], np.ndarray]:
    """W and a directory for path F alone, laid out as compile_model lays a
    path out, its rates in a matrix of their own."""
    at = cf.state_layout(F, 1)
    data = at['end']
    pos = np.arange(F.slots * F.nnz, dtype=np.int64)
    return np.zeros(data + pos.size), cf.directory(F, data, at, pos), data, at, pos


def bits_equal(a: Any, b: Any) -> bool:
    """The same doubles, bit for bit -- NaN as NaN, whatever its payload."""
    a = np.ascontiguousarray(a, dtype=float).ravel()
    b = np.ascontiguousarray(b, dtype=float).ravel()
    if a.shape != b.shape:
        return False
    nan = np.isnan(a)
    return bool(np.array_equal(nan, np.isnan(b)) and np.array_equal(a[~nan].view(np.int64), b[~nan].view(np.int64)))


def system_for(grid: str, surface: str = 'f', paths: bool = False, **cells: Any) -> Any:
    block = {'grid': grid, 'surface': surface, 'n_f': 4, 'n_m': 6, **cells}
    if surface != 'f':
        block[surface] = '2000' if surface == 'aw' else '0.001'
    if paths:
        raw = two_paths(grid).to_json()
        raw['farfields'][0].update(block)
        return build_system(Project(raw))
    return build_system(path(**block))


class PythonRefresh(unittest.TestCase):
    def test_the_reference_layers_once_for_a_combination(self) -> None:
        # They follow from settings every nuclide of a combination shares:
        # worked out with its first slot's rates and used for the rest, as the
        # compiled refresh works them out -- not again for every nuclide --
        # and the rates are what each slot's own layers give, bit for bit.
        from kompartment.engine import farfield as ff
        system = system_for('reference', paths=True)
        F = system.FARF[0]
        self.assertGreater(F.nnuc, 1)
        self.assertGreater(F.other_width, 1)
        X = np.zeros(system.X.size)
        draw(np.random.default_rng(3), F, X, bad=0.0)
        made: List[Any] = []
        real = ff.layer_depths

        def counted(*args: Any) -> Any:
            made.append(args)
            return real(*args)

        F.restart()
        with mock.patch.object(ff, 'layer_depths', counted):
            F.refresh(X)
        self.assertEqual(len(made), F.other_width)
        for slot in range(F.slots):
            own = np.zeros(F.nnz)
            ff.cell_values(F.structure, ff.coefficients(F._setting(X, slot)), own)
            self.assertTrue(bits_equal(F.vals[slot], own), slot)


@needs_numba
class Refresh(unittest.TestCase):
    """``farfield.refresh`` against ``FarfPath.refresh``, from the same state
    on the same settings: the same rates, weights, settings seen and layers,
    bit for bit -- and ASK_PYTHON exactly where the Python one raises."""

    def same_state(self, F: Any, W: np.ndarray, data: int, at: Dict[str, int], pos: np.ndarray) -> None:
        self.assertTrue(bits_equal(W[data + pos], F.vals), 'rates')
        self.assertTrue(bits_equal(W[at['relw']:at['seen']], F.rel_w), 'release weights')
        self.assertTrue(bits_equal(W[at['seen']:at['laid']], F.seen), 'settings seen')
        self.assertTrue(np.array_equal(W[at['laid']:at['layers']] != 0, F.laid_out), 'laid out')
        if F.grid == 'matched':
            nm = F.structure['n_m']
            for o in np.flatnonzero(F.laid_out):
                a = at['layers'] + o * (2 * nm + 1)
                lay = F.layers[o]
                self.assertTrue(bits_equal(W[a:a + 2 * nm + 1], np.concatenate([lay['d'], lay['h'], [lay['q']]])),
                                'layers')

    def compare(self, F: Any, X: np.ndarray, W: np.ndarray, fd: np.ndarray, data: int, at: Dict[str, int],
                pos: np.ndarray, laying: bool) -> bool:
        """One refresh on each, from the same state: True when it succeeded."""
        try:
            with np.errstate(all='ignore'):
                F.refresh(X)
            raised = None
        except Exception as e:  # noqa: BLE001 - compared below
            raised = e
        answer = cf.refresh(X, W, fd)
        if raised is not None:
            self.assertEqual(answer, cf.ASK_PYTHON, f'Python raised {raised!r}')
            return False
        self.assertEqual(answer, cf.LAID_OUT if laying else cf.DONE)
        self.same_state(F, W, data, at, pos)
        return True

    def test_settings_drawn_at_random(self) -> None:
        r = np.random.default_rng(20261002)
        configs = [dict(grid=g, surface=s) for g in GRIDS for s in ('f', 'aw', 'aperture')]
        configs += [dict(grid=g, paths=True) for g in GRIDS]
        configs += [dict(grid=g, n_f=2, n_m=160) for g in GRIDS]
        for config in configs:
            system = system_for(**config)
            F = system.FARF[0]
            W, fd, data, at, pos = flat(F)
            ok = raised = 0
            for _ in range(24 if F.structure['n_m'] > 100 else 150):
                X = np.zeros(system.X.size)
                draw(r, F, X)
                F.restart()
                cf.take(F, W, data, at, pos)
                if not self.compare(F, X, W, fd, data, at, pos, F.grid == 'matched'):
                    raised += 1
                    continue
                ok += 1
                # Some settings moved, the rest as they were: only the
                # slots that saw a change worked out again, on the same layers.
                for keys in (FARF_NUCLIDE_KEYS, ('tw', 'pe', 'rho_m'), F.keys):
                    draw(r, F, X, keys, bad=0.01)
                    if not self.compare(F, X, W, fd, data, at, pos, False):
                        break
            with self.subTest(**config):
                self.assertGreater(ok, 0)

    def test_settings_that_make_python_raise(self) -> None:
        # Each the first time round, from a path whose other settings are
        # fine: a FarfError, a sorption on the coating below zero included.
        bad = {'pe': -1.0, 'tw': 0.0, 'eps_m': -10.0, 'pen_dep': math.nan, 'pen_dep_0': 5.0, 'kd_f': -1 / 2000}
        for grid in GRIDS:
            system = system_for(grid)
            F = system.FARF[0]
            W, fd, data, at, pos = flat(F)
            for key, value in bad.items():
                X = np.zeros(system.X.size)
                for k, name in enumerate(F.keys):
                    X[F.setting_idx[:, k]] = {'tw': 50.0, 'f': 1e5, 'kd_f': 0.0, 'kd_m': 1e-3, 'de_m': 3e-5,
                                              'eps_m': 2e-3, 'rho_m': 2700.0, 'pe': 10.0, 'pen_dep': 12.5,
                                              'pen_dep_0': 0.0}[name]
                X[F.setting_idx[:, F.keys.index(key)]] = value
                F.restart()
                cf.take(F, W, data, at, pos)
                with self.subTest(grid=grid, setting=key):
                    with self.assertRaises(FarfError):
                        F.refresh(X)
                    self.assertEqual(cf.refresh(X, W, fd), cf.ASK_PYTHON)
        # kd_f making 1 + kd_f a_w negative: refused before the matched
        # layers' penetration scale takes its square root.
        system = system_for('matched')
        F = system.FARF[0]
        W, fd, data, at, pos = flat(F)
        X = np.zeros(system.X.size)
        for k, name in enumerate(F.keys):
            X[F.setting_idx[:, k]] = {'tw': 50.0, 'f': 1e5, 'kd_f': -1.0, 'kd_m': 1e-3, 'de_m': 3e-5, 'eps_m': 2e-3,
                                      'rho_m': 2700.0, 'pe': 10.0, 'pen_dep': 12.5, 'pen_dep_0': 0.0}[name]
        F.restart()
        cf.take(F, W, data, at, pos)
        with self.assertRaises(FarfError):
            F.refresh(X)
        self.assertEqual(cf.refresh(X, W, fd), cf.ASK_PYTHON)

    def test_what_numba_has_its_own_version_of(self) -> None:
        # np.spacing: numba's signs a zero's like the zero, numpy's does not.
        r = np.random.default_rng(7)
        values = [0.0, -0.0, 5e-324, -5e-324, 2.2e-308, 1e-310, 1.0, -1.0, 2.5, 1e300, 1.7976931348623157e308,
                  -1.7976931348623157e308, math.inf, -math.inf, math.nan]
        values += list(10 ** r.uniform(-320, 308, 200) * np.where(r.random(200) < 0.5, -1, 1))
        with np.errstate(all='ignore'):
            for x in values:
                self.assertTrue(bits_equal(cf._spacing(float(x)), float(np.spacing(x))), x)
        # Python's q ** j: its special cases, and Infinity for an OverflowError.
        qs = [0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 1.5, -1.5, 99.99, 100.0, -100.0, math.inf, -math.inf, math.nan]
        qs += list(1 + 10 ** r.uniform(-12, 2, 100))
        for q in qs:
            for j in (0, 1, 2, 3, 7, 154, 155, 159, 160, 1001):
                self.assertTrue(bits_equal(cf._js_pow(float(q), j), _js_pow(float(q), j)), (q, j))


#: The U-238 chain of TR-19-06 down to Po-210 on its representative path, as the application's
#: test of the same name has it ('matched layers that grow coarse at depth are said'): Po-210's
#: half-life sizes the first layer by its decay, and twelve layers have to grow by 3.4 each.
CHAIN = ['U-238', 'U-234', 'Th-230', 'Ra-226', 'Pb-210', 'Po-210']
#: What the application says of it, word for word.
COARSE = ('the 12 matrix layers grow by 3.39 from a first layer of 4.68 µm, which is coarse at depth: '
          '20 layers would keep the growth to 2')


def chain_path(nm: int, grid: str = 'matched') -> Project:
    kd = [2e-4, 2e-4, 5.3e-2, 4.5e-4, 2.5e-2, 2.5e-2]
    de = [2.7e-7, 2.7e-7, 2.7e-7, 8.5e-7, 8.5e-7, 2.7e-7]
    return Project({
        'name': 'chain',
        'simulation': {'start_time': 0, 'end_time': 1e4, 'output_points': 10, 'spacing': 'log',
                       'solver': 'ndf', 'rtol': 1e-6, 'abstol': 1e-20, 'time_unit': 'year'},
        'nuclides': CHAIN,
        'half_lives': {'U-238': 4.468e9, 'U-234': 245500, 'Th-230': 75386, 'Ra-226': 1600, 'Pb-210': 22.3,
                       'Po-210': 0.379},
        'chains': [[CHAIN[i], CHAIN[i + 1], 1] for i in range(len(CHAIN) - 1)],
        'decay_unit': 'Bq',
        'compartments': [{'name': 'Out', 'initial': '0', 'index_lists': ['Radionuclides']}],
        'inflows': [{'name': 'In', 'to': 'Rock', 'rate': '1', 'index_lists': ['Radionuclides']}],
        'transfers': [{'name': 'Release', 'from': 'Rock', 'to': 'Out', 'rate': 'Rock', 'multiply_by_donor': False,
                       'index_lists': ['Radionuclides']}],
        'farfields': [{'name': 'Rock', 'index_lists': ['Radionuclides'], 'tw': '235.2', 'f': '80090', 'kd_f': '0',
                       'kd_m': '0', 'de_m': '1e-4', 'eps_m': '0.0019', 'rho_m': '2700', 'pe': '10', 'pen_dep': '4.5',
                       'pen_dep_0': '', 'n_f': 20, 'n_m': nm, 'o_b': 4, 'n_b': '', 'grid': grid,
                       'entries': [{'index': {'Radionuclides': n}, 'kd_m': str(kd[i]), 'de_m': str(de[i])}
                                   for i, n in enumerate(CHAIN)]}],
    })


class CoarseLayers(unittest.TestCase):
    """Matched layers that grow coarse at depth are said with the run (``stats.layers``), in the
    application's words, on the Python path and the compiled one alike -- the compiled run hands
    its layers back to the path, and they are read off there."""

    def test_said_as_the_application_says_it(self) -> None:
        from kompartment.engine.runlog import run_log_lines
        for compiled in (False, True) if HAVE_NUMBA else (False,):
            with self.subTest(compiled=compiled):
                res = run(chain_path(12), compiled=compiled)
                self.assertEqual(res.stats.get('layers'), [{'block': 'Rock', 'message': COARSE}])
                lines = run_log_lines({'name': 'chain', 'simulation': {}}, {'stats': res.stats})
                self.assertIn('far-field matrix layers: 1 path grows coarse at depth', lines)
                self.assertIn(f'  Rock: {COARSE}', lines)
                # Twenty grow by 2.0; the reference layers grow by e as a rule, and are a choice.
                self.assertNotIn('layers', run(chain_path(20), compiled=compiled).stats)
                self.assertNotIn('layers', run(chain_path(12, 'reference'), compiled=compiled).stats)


if __name__ == '__main__':
    unittest.main()
