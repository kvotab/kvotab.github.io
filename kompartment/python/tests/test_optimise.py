"""The optimisers, local sensitivities and calibration against the application's own.

The application's ``src/domain/optimise.js``, ``src/sim/localsens.js`` and
``src/sim/calibrate.js`` run through Node (``tests/node/optimise.mjs``) beside
this package's ports -- :mod:`kompartment.stats.optimise`,
:mod:`kompartment.engine.localsens` and :mod:`kompartment.engine.calibrate` --
on the same inputs, and the answers are compared.

What has to match exactly, because no run is involved: every point the three
optimisers evaluate on the test functions, in order, with its value and the
best so far; the evaluation counts and the reasons they stop; the objective
and its residuals; the ``toPrecision(12)`` text a point is recognised by; the
parameter slots, their labels and values; the elasticity; and a calibration's
counts, reasons and verdict. The test functions below are written in the same
arithmetic on both sides (``+ - * /`` and V8's ``Math.exp``).

What is compared to a margin, and why: wherever a run is inside the loop. The
engine's runs agree with the application's to round-off, not to the bit --
V8's ``Math.pow`` rounds differently from the C library's on about one
argument in ten, and the NDF's step size is a power, so step sequences can
part in the last digits. So the states and ``dy/dp`` of a sensitivity run are
compared to 10 x the run's rtol (the augmented system itself, point by point,
to 1e-13 in the states and 1e-10 in dy/dp); a calibration's readings and objectives to 10 x rtol, the points it
tries to 1e-9 (the same decisions give the same points), and
Levenberg-Marquardt's answer -- whose Jacobian is a difference over 1e-6 of a
variable's range, and so turns round-off in the runs into differences in the
points it tries -- to 1e-4, on a valley flat enough that its own objective
cannot tell those points apart. The largest difference seen in each area is
printed at the end.

The tests in :class:`Standalone` need nothing but this package.
"""

from __future__ import annotations

import json
import math
import subprocess
import importlib
import unittest
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
from helpers import NODE, SRC, example, needs_app

from kompartment.engine.builder import build_system
from kompartment.engine.paramtangent import build_param_tangent
from kompartment.engine.project import Project
from kompartment.engine.runner import run
from kompartment.stats import optimise as O
from kompartment.stats.pdf import _exp, _to_precision

# By module name: `kompartment.engine` exports functions called `calibrate`
# and `run_sensitivity`, and the first shadows the module of the same name.
C = importlib.import_module('kompartment.engine.calibrate')
L = importlib.import_module('kompartment.engine.localsens')

SCRIPT = Path(__file__).resolve().parent / 'node' / 'optimise.mjs'
WORST: Dict[str, float] = {}


def _note(area: str, value: float) -> None:
    if value == value:
        WORST[area] = max(WORST.get(area, 0.0), value)


def tearDownModule() -> None:  # noqa: N802 - unittest's name
    if WORST:
        print('\nLargest differences from the application:')
        for area, value in sorted(WORST.items()):
            print(f'  {area}: {value:.3g}')


# --- talking to the application ---------------------------------------------------------

_SPECIAL = {'NaN': math.nan, 'Infinity': math.inf, '-Infinity': -math.inf, '-0': -0.0, 'undefined': None}


def _enc(x: Any) -> Any:
    if x is None or isinstance(x, (bool, str)):
        return x
    if isinstance(x, (np.integer, np.floating)):
        x = x.item()
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        if x != x:
            return {'$': 'NaN'}
        if math.isinf(x):
            return {'$': 'Infinity' if x > 0 else '-Infinity'}
        if x == 0 and math.copysign(1.0, x) < 0:
            return {'$': '-0'}
        return x
    if isinstance(x, np.ndarray):
        return [_enc(v) for v in x.tolist()]
    if isinstance(x, (list, tuple)):
        return [_enc(v) for v in x]
    if isinstance(x, dict):
        return {str(k): _enc(v) for k, v in x.items()}
    raise TypeError(f'cannot send {type(x).__name__} to the script')


def _dec(x: Any) -> Any:
    if isinstance(x, list):
        return [_dec(v) for v in x]
    if isinstance(x, dict):
        if list(x) == ['$']:
            return _SPECIAL[x['$']]
        return {k: _dec(v) for k, v in x.items()}
    return x


def app(task: str, **request: Any) -> Any:
    """Asks the application (see ``tests/node/optimise.mjs``)."""
    proc = subprocess.run([NODE, str(SCRIPT), str(SRC)], input=json.dumps(_enc({'task': task, **request})),
                          capture_output=True, text=True, timeout=900, encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return _dec(json.loads(proc.stdout))


def same(a: Any, b: Any) -> bool:
    """Equal, key order included: numbers as doubles (JSON writes 1.0 as 1),
    NaN equal to NaN, -0 not equal to +0, a boolean only to a boolean."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        a, b = float(a), float(b)
        if a != a or b != b:
            return a != a and b != b
        return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return list(a) == list(b) and all(same(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def relative(a: Any, b: Any) -> float:
    """``|a - b| / max(|a|, |b|)``, 0 where they are equal (NaN and infinities included)."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.shape != b.shape:
        return math.inf
    equal = (a == b) | (np.isnan(a) & np.isnan(b))
    scale = np.maximum(np.abs(a), np.abs(b))
    with np.errstate(all='ignore'):
        r = np.where(equal, 0.0, np.abs(a - b) / scale)
    return float(np.max(r)) if r.size else 0.0


def series_difference(a: Any, b: Any) -> float:
    """The largest difference between two series, over the larger one's peak."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.shape != b.shape:
        return math.inf
    scale = max(float(np.max(np.abs(a))) if a.size else 0.0, float(np.max(np.abs(b))) if b.size else 0.0)
    if scale == 0:
        return 0.0
    return float(np.max(np.abs(a - b))) / scale


# --- the test functions: the same arithmetic as optimise.mjs's ------------------------------

C4 = [0.3, -1.2, 2.5, 0.7]
MM_T = [0.5, 1, 2, 4, 8, 16]
MM_Y = [0.9, 1.5, 2.2, 2.9, 3.3, 3.6]
EXP_T = [0, 1, 2, 3, 5, 8]
EXP_Y = [5.1, 3.1, 1.8, 1.1, 0.42, 0.09]


def _rosenbrock(x: List[float]) -> float:
    a = x[1] - x[0] * x[0]
    b = 1 - x[0]
    return 100 * a * a + b * b


def _sphere(x: List[float]) -> float:
    s = 0.0
    for k in range(len(x)):
        d = x[k] - C4[k]
        s += d * d
    return s


def _himmelblau(x: List[float]) -> float:
    a = x[0] * x[0] + x[1] - 11
    b = x[0] + x[1] * x[1] - 7
    return a * a + b * b


def _holes(x: List[float]) -> float:
    if x[0] < 0:
        return math.nan
    if x[1] > 1.5:
        return math.inf
    return (x[0] - 1) * (x[0] - 1) + (x[1] - 0.5) * (x[1] - 0.5)


OBJECTIVES = {
    'rosenbrock': _rosenbrock,
    'sphere': _sphere,
    'himmelblau': _himmelblau,
    'holes': _holes,
    'outside': lambda x: (x[0] - 5) * (x[0] - 5) + (x[1] + 3) * (x[1] + 3),
    'flat': lambda x: 3,
    'well': lambda x: -1 / (1 + x[0] * x[0] + x[1] * x[1]),
    'line': lambda x: (x[0] - 0.25) * (x[0] - 0.25),
}

RESIDUALS = {
    'rosenbrock': lambda x: [10 * (x[1] - x[0] * x[0]), 1 - x[0]],
    'mm': lambda x: [(x[0] * t) / (x[1] + t) - MM_Y[i] for i, t in enumerate(MM_T)],
    'expdecay': lambda x: [x[0] * _exp(-x[1] * t) - EXP_Y[i] for i, t in enumerate(EXP_T)],
    'big': lambda x: [x[0] - 1000000.004, (x[1] - 2) * 3],
    'nanres': lambda x: [math.nan if x[0] > 2 else x[0] - 1, x[1] - 2],
    'line': lambda x: [x[0] - 0.25],
}


def _sum_squares(res: Any) -> Any:
    def f(x: List[float]) -> float:
        s = 0.0
        for r in res(x):
            s += r * r
        return s
    return f


def objective_named(fn: str) -> Any:
    return _sum_squares(RESIDUALS[fn[3:]]) if fn.startswith('ss:') else OBJECTIVES[fn]


def REFUSAL_MODELS() -> List[Any]:  # noqa: N802 - a constant, made fresh each time
    """(model, parameters, why): made-up models the sensitivity equations cannot carry."""
    def base() -> Dict[str, Any]:
        return {
            'name': 'refusals',
            'simulation': {'start_time': 0, 'end_time': 100, 'output_points': 5, 'spacing': 'linear',
                           'solver': 'ndf', 'rtol': 1e-8, 'abstol': 1e-12, 'time_unit': 'year'},
            'parameters': [{'name': 'k', 'value': 0.01, 'unit': '1/year', 'index_lists': []},
                           {'name': 't_on', 'value': 40, 'unit': 'year', 'index_lists': []}],
            'compartments': [{'name': 'A', 'initial': '1', 'index_lists': []},
                             {'name': 'B', 'initial': '0', 'index_lists': []}],
            'transfers': [{'name': 'a2b', 'from': 'A', 'to': 'B', 'rate': 'k', 'index_lists': []}],
        }
    jump = base()
    jump['events'] = [{'name': 'Flood', 'timing': 'at', 'at': '50', 'index_lists': [],
                       'actions': [{'kind': 'move', 'from': 'A', 'to': None, 'fraction': '0.5'}]}]
    path = base()
    path['min_maxes'] = [{'name': 'Top', 'target': 'B', 'operation': 'max', 'index_lists': []}]
    path['transfers'][0]['rate'] = 'k * (1 + Top)'
    lagged = base()
    lagged['delays'] = [{'name': 'Lagged', 'target': 'B', 'delay': '5', 'index_lists': []}]
    lagged['transfers'][0]['rate'] = 'k / (1 + Lagged)'
    corner = base()
    corner['simulation']['switch_times'] = ['t_on']
    corner['inflows'] = [{'name': 'In', 'to': 'A', 'rate': 'if(time() >= t_on, 1, 0)', 'index_lists': []}]
    return [(jump, ['k'], "'Flood' makes the state jump at t=50"),
            (path, ['k'], "'Top' remembers the path of the run"),
            (lagged, ['k'], "'Lagged' remembers the path of the run"),
            (corner, ['t_on'], "'t_on' places a corner of the run")]


class _Stop:
    """The signal a case stops on: aborted once ``after`` evaluations have been reported."""

    def __init__(self, after: int, trace: List[Any]) -> None:
        self.after = after
        self.trace = trace

    @property
    def aborted(self) -> bool:
        return len(self.trace) >= self.after


_OPT_NAMES = {'maxEvals': 'max_evals', 'popSize': 'pop_size', 'onProgress': 'on_progress'}


def optimise_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """One case of the ``optimise`` task, run here."""
    trace: List[Dict[str, Any]] = []
    opts = {_OPT_NAMES.get(k, k): v for k, v in (case.get('opts') or {}).items()}
    if 'lower' in case:
        opts['lower'] = case['lower']
    if 'upper' in case:
        opts['upper'] = case['upper']
    opts['on_step'] = lambda p: trace.append({'evals': p['evals'], 'fx': p['fx'], 'best': p['best'],
                                              'x': list(p['x']), 'bestX': list(p['bestX']) if p['bestX'] else None})
    if case.get('stopAfter') is not None:
        opts['signal'] = _Stop(case['stopAfter'], trace)
    method, fn = case['method'], case['fn']
    try:
        if method.startswith('METHODS.'):
            ctx = {'start': case.get('start'), 'objective': objective_named(fn),
                   'residuals': RESIDUALS[fn[3:] if fn.startswith('ss:') else fn]}
            result = O.METHODS[method[8:]]['run'](ctx, opts)
        elif method == 'nelder':
            result = O.nelder_mead(objective_named(fn), case['start'], **opts)
        elif method == 'lm':
            result = O.levenberg_marquardt(RESIDUALS[fn], case['start'], **opts)
        else:
            if 'start' in case:
                opts['start'] = case['start']
            result = O.differential_evolution(objective_named(fn), **opts)
    except O.OptimiseError as e:
        return {'error': str(e), 'type': 'OptimiseError'}
    return {'result': result, 'trace': trace}


BOX2 = {'lower': [-2, -2], 'upper': [2, 2]}

OPTIMISER_CASES: List[Dict[str, Any]] = [
    # Nelder-Mead
    {'method': 'nelder', 'fn': 'rosenbrock', 'start': [-1.2, 1], **BOX2, 'opts': {'maxEvals': 400}},
    {'method': 'nelder', 'fn': 'sphere', 'start': [0, 0, 0, 0], 'lower': [-5] * 4, 'upper': [5] * 4},
    {'method': 'nelder', 'fn': 'holes', 'start': [0.2, 1.4], 'lower': [-1, -1], 'upper': [3, 3],
     'opts': {'maxEvals': 200}},
    {'method': 'nelder', 'fn': 'outside', 'start': [1, 1], 'lower': [0, 0], 'upper': [2, 2],
     'opts': {'maxEvals': 150}},
    {'method': 'nelder', 'fn': 'rosenbrock', 'start': [3, -3], **BOX2, 'opts': {'maxEvals': 150}},
    {'method': 'nelder', 'fn': 'flat', 'start': [0.5, 0.5], **BOX2},
    {'method': 'nelder', 'fn': 'sphere', 'start': [0.5, 1], 'lower': [0, 1], 'upper': [1, 1],
     'opts': {'maxEvals': 120}},
    {'method': 'nelder', 'fn': 'rosenbrock', 'start': [-1.2, 1], **BOX2, 'stopAfter': 5},
    {'method': 'nelder', 'fn': 'rosenbrock', 'start': [-1.2, 1], **BOX2, 'opts': {'maxEvals': 7}},
    {'method': 'nelder', 'fn': 'rosenbrock', 'start': [-1.2, 1], **BOX2, 'opts': {'maxEvals': None}},
    {'method': 'nelder', 'fn': 'line', 'start': [0.9], 'lower': [0], 'upper': [1]},
    {'method': 'nelder', 'fn': 'rosenbrock', 'start': [0, 0], **BOX2, 'opts': {'tol': 1e-3}},
    {'method': 'nelder', 'fn': 'well', 'start': [1.5, -1], **BOX2},
    {'method': 'nelder', 'fn': 'ss:mm', 'start': [1, 1], 'lower': [0, 0], 'upper': [10, 10]},
    {'method': 'nelder', 'fn': 'ss:expdecay', 'start': [1, 0.1], 'lower': [0.1, 0.01], 'upper': [20, 5]},
    {'method': 'nelder', 'fn': 'rosenbrock', 'start': [], **BOX2},
    # Levenberg-Marquardt
    {'method': 'lm', 'fn': 'rosenbrock', 'start': [-1.2, 1], **BOX2},
    {'method': 'lm', 'fn': 'mm', 'start': [1, 1], 'lower': [0, 0], 'upper': [10, 10]},
    {'method': 'lm', 'fn': 'expdecay', 'start': [1, 0.1], 'lower': [0.1, 0.01], 'upper': [20, 5]},
    # the stale-residuals quirk: a difference step that rounds onto a point already seen
    {'method': 'lm', 'fn': 'big', 'start': [1000000, 1], 'lower': [999999.99, 0], 'upper': [1000000.01, 4]},
    {'method': 'lm', 'fn': 'nanres', 'start': [1.5, 0], 'lower': [0, -1], 'upper': [3, 3]},
    # the upper-bound quirk: a variable on its upper bound gets a zero column
    {'method': 'lm', 'fn': 'mm', 'start': [10, 1], 'lower': [0, 0], 'upper': [10, 10]},
    {'method': 'lm', 'fn': 'mm', 'start': [1, 1], 'lower': [0, 0], 'upper': [10, 10], 'stopAfter': 4},
    {'method': 'lm', 'fn': 'mm', 'start': [1, 1], 'lower': [0, 0], 'upper': [10, 10], 'opts': {'maxEvals': 5}},
    {'method': 'lm', 'fn': 'line', 'start': [0.9], 'lower': [0], 'upper': [1]},
    {'method': 'lm', 'fn': 'mm', 'start': [1, 1], 'lower': [0, 0], 'upper': [10, 10], 'opts': {'tol': 1e-3}},
    # Differential evolution
    {'method': 'de', 'fn': 'rosenbrock', **BOX2, 'opts': {'maxEvals': 600, 'seed': 3}},
    {'method': 'de', 'fn': 'himmelblau', 'lower': [-5, -5], 'upper': [5, 5], 'opts': {'maxEvals': 500}},
    {'method': 'de', 'fn': 'sphere', 'start': [1, 1, 1, 1], 'lower': [-5] * 4, 'upper': [5] * 4,
     'opts': {'maxEvals': 300, 'popSize': 5, 'F': 0.5, 'CR': 0.3, 'seed': 12345}},
    {'method': 'de', 'fn': 'holes', 'lower': [-1, -1], 'upper': [3, 3], 'opts': {'maxEvals': 300, 'seed': 7}},
    {'method': 'de', 'fn': 'flat', **BOX2, 'opts': {'seed': 9}},
    {'method': 'de', 'fn': 'rosenbrock', **BOX2, 'opts': {'seed': 4}, 'stopAfter': 10},
    {'method': 'de', 'fn': 'line', 'lower': [0], 'upper': [1], 'opts': {'seed': 0}},
    {'method': 'de', 'fn': 'ss:mm', 'start': [20, -3], 'lower': [0, 0], 'upper': [10, 10],
     'opts': {'maxEvals': 200, 'seed': '5', 'popSize': 6.5}},
    {'method': 'de', 'fn': 'rosenbrock', 'lower': [], 'upper': []},
    # through the table, as calibrate calls them
    {'method': 'METHODS.nelder', 'fn': 'ss:mm', 'start': [1, 1], 'lower': [0, 0], 'upper': [10, 10],
     'opts': {'maxEvals': 90, 'seed': 3, 'onProgress': None}},
    {'method': 'METHODS.lm', 'fn': 'ss:mm', 'start': [1, 1], 'lower': [0, 0], 'upper': [10, 10],
     'opts': {'maxEvals': 90, 'seed': 3, 'onProgress': None}},
    {'method': 'METHODS.de', 'fn': 'ss:mm', 'start': [1, 1], 'lower': [0, 0], 'upper': [10, 10],
     'opts': {'maxEvals': 90, 'seed': 3, 'onProgress': None}},
]

OBJECTIVE_CASES: List[Dict[str, Any]] = [
    {'readings': [1.0, 2.0, 3.0], 'targets': [{'value': 2, 'scale': 'absolute'}, {'value': 1},
                                              {'value': 30, 'scale': 'log'}]},
    {'readings': [5.0, -2.0, 0.0], 'targets': [{'value': 0}, {'value': -4, 'scale': 'relative'},
                                               {'value': 0, 'scale': 'log'}]},
    {'readings': [-1.0, 3.0], 'targets': [{'value': 2, 'scale': 'log'}, {'value': -3, 'scale': 'log'}]},
    {'readings': [2.0] * 7, 'targets': [{'value': 1, 'weight': 4}, {'value': 1, 'weight': '4'},
                                        {'value': 1, 'weight': -2}, {'value': 1, 'weight': 0},
                                        {'value': 1, 'weight': math.nan}, {'value': 1, 'weight': math.inf},
                                        {'value': 1, 'weight': True}]},
    {'readings': [2.0, 2.0, 2.0], 'targets': [{'value': 1, 'scale': 'foo'}, {'value': 1, 'scale': None},
                                              {'value': 1, 'scale': 'absolute', 'weight': 0.25}]},
    {'readings': [2.0, 2.0, 2.0], 'targets': [{'value': '2.5'}, {}, {'value': None, 'scale': 'absolute'}]},
    {'readings': [math.nan, math.inf, 1.0], 'targets': [{'value': 1}, {'value': 1}, {'value': 1}, {'value': 1}]},
    {'readings': [1e-300, 1e300], 'targets': [{'value': 1e300, 'scale': 'log'}, {'value': 1e-300, 'scale': 'log'}]},
    {'readings': [1.0], 'targets': [{'value': 1, 'scale': 'toString'}]},
    {'readings': [1.0], 'targets': [{'value': 1, 'scale': 'constructor'}]},
]


# ---------------------------------------------------------------------------------------------

class Standalone(unittest.TestCase):
    """What the ports do, without the application to compare with."""

    def test_nelder_mead_walks_to_the_bottom(self) -> None:
        out = O.nelder_mead(_rosenbrock, [-1.2, 1], lower=[-2, -2], upper=[2, 2], max_evals=400)
        self.assertEqual(out['reason'], 'converged')
        self.assertLess(abs(out['x'][0] - 1), 1e-6)
        self.assertLess(abs(out['x'][1] - 1), 1e-6)

    def test_levenberg_marquardt_fits_least_squares(self) -> None:
        out = O.levenberg_marquardt(RESIDUALS['mm'], [1, 1], lower=[0, 0], upper=[10, 10])
        self.assertEqual(out['reason'], 'converged')
        # The normal equations of the fit, at the answer: J^T r = 0.
        a, b = out['x']
        r = RESIDUALS['mm'](out['x'])
        ga = sum(ri * t / (b + t) for ri, t in zip(r, MM_T))
        gb = sum(-ri * a * t / (b + t) ** 2 for ri, t in zip(r, MM_T))
        self.assertLess(abs(ga) + abs(gb), 1e-6)

    def test_differential_evolution_is_its_seed(self) -> None:
        box = dict(lower=[-5, -5], upper=[5, 5], max_evals=1000)
        one = O.differential_evolution(_himmelblau, seed=11, **box)
        two = O.differential_evolution(_himmelblau, seed=11, **box)
        other = O.differential_evolution(_himmelblau, seed=12, **box)
        self.assertEqual(one, two)
        self.assertNotEqual(one['x'], other['x'])
        self.assertLess(one['fx'], 1e-2)

    def test_every_evaluation_is_reported_and_none_twice(self) -> None:
        seen: List[Dict[str, Any]] = []
        out = O.nelder_mead(OBJECTIVES['flat'], [0.5, 0.5], lower=[0, 0], upper=[1, 1], on_step=seen.append)
        self.assertEqual(out['reason'], 'converged')
        self.assertEqual(out['evals'], 3)
        self.assertEqual([p['evals'] for p in seen], [1, 2, 3])
        keys = {','.join(_to_precision(v, 12) for v in p['x']) for p in seen}
        self.assertEqual(len(keys), 3)

    def test_stopped_and_out_of_budget(self) -> None:
        seen: List[Any] = []
        out = O.nelder_mead(_rosenbrock, [-1.2, 1], lower=[-2, -2], upper=[2, 2], on_step=seen.append,
                            signal=lambda: len(seen) >= 4)
        self.assertEqual((out['reason'], out['evals']), ('stopped', 4))
        out = O.levenberg_marquardt(RESIDUALS['mm'], [1, 1], lower=[0, 0], upper=[10, 10], max_evals=5)
        self.assertEqual((out['reason'], out['evals']), ('budget', 5))
        out = O.differential_evolution(_rosenbrock, lower=[-2, -2], upper=[2, 2], signal={'aborted': True})
        self.assertEqual((out['reason'], out['evals'], out['x']), ('stopped', 0, None))

    def test_nothing_to_vary(self) -> None:
        with self.assertRaisesRegex(O.OptimiseError, 'Nothing to vary'):
            O.nelder_mead(_rosenbrock, [], lower=[], upper=[])
        with self.assertRaisesRegex(O.OptimiseError, 'Nothing to vary'):
            O.levenberg_marquardt(RESIDUALS['line'], [], lower=[], upper=[])
        with self.assertRaisesRegex(O.OptimiseError, 'Nothing to vary'):
            O.differential_evolution(_rosenbrock, lower=[], upper=[])

    def test_objective(self) -> None:
        got = O.objective_of([2.0, math.nan, 0.5, 3.0],
                             [{'value': 1}, {'value': 1}, {'value': 1, 'scale': 'log', 'weight': 4},
                              {'value': 0}])
        self.assertEqual(got['residuals'][0], 1.0)
        self.assertEqual(got['residuals'][1], 1e6)
        self.assertAlmostEqual(got['residuals'][2], 2 * math.log(0.5), places=15)
        self.assertEqual(got['residuals'][3], 3.0)
        self.assertEqual(got['objective'], sum(r * r for r in got['residuals']))
        # A name every JavaScript object has is no scale, and falls back to
        # relative (it used to be found, and fail).
        for name in ('valueOf', 'toString', 'constructor', '__proto__'):
            self.assertEqual(O.objective_of([2.0], [{'value': 1, 'scale': name}])['residuals'], [1.0])

    def test_spaces(self) -> None:
        log, linear = O.SPACES['log'], O.SPACES['linear']
        for v in (1e-9, 3.7e-5, 1.0, 42.0, 6.02e23):
            self.assertLessEqual(abs(log['from'](log['to'](v)) / v - 1), 4e-16 * max(1.0, abs(math.log(v))))
            self.assertEqual(linear['from'](linear['to'](v)), v)
        self.assertTrue(log['ok'](1e-9, 1))
        self.assertFalse(log['ok'](0, 1))
        self.assertTrue(linear['ok'](-1, 1))

    def test_levenberg_marquardt_steps_far_enough_to_be_told_apart(self) -> None:
        # 1e-6 of a range of 0.02 on a variable of 1e6 is the same point to
        # the twelve figures the budget knows a point by; the difference step
        # is kept above that now (1e-9 of the value), and a point answered
        # from memory comes back with its own residuals. It used to stay put.
        x0, h = 1000000.0, (1000000.01 - 999999.99) * 1e-6
        self.assertEqual(_to_precision(x0 + h, 12), _to_precision(x0, 12))
        out = O.levenberg_marquardt(RESIDUALS['big'], [x0, 1], lower=[999999.99, 0], upper=[1000000.01, 4])
        self.assertLess(abs(out['x'][0] - 1000000.004), 1e-7)
        self.assertLess(out['fx'], 1e-18)

    def test_levenberg_marquardt_leaves_an_upper_bound(self) -> None:
        # From a start on its upper bound it differences backwards; forwards,
        # clamped, the column was zero and it stopped at 8.65 against 0.0065.
        inside = O.levenberg_marquardt(RESIDUALS['mm'], [1, 1], lower=[0, 0], upper=[10, 10])
        bound = O.levenberg_marquardt(RESIDUALS['mm'], [10, 1], lower=[0, 0], upper=[10, 10])
        self.assertLess(bound['x'][0], 10)
        self.assertLess(abs(bound['fx'] / inside['fx'] - 1), 1e-6)

    def test_none_is_the_default(self) -> None:
        # An option given as None takes its default, as one left out does; a
        # budget of None used to be a budget of 0.
        nm = O.nelder_mead(_rosenbrock, [-1.2, 1], lower=[-2, -2], upper=[2, 2], max_evals=None, tol=None)
        self.assertEqual(nm, O.nelder_mead(_rosenbrock, [-1.2, 1], lower=[-2, -2], upper=[2, 2]))
        de = O.differential_evolution(_rosenbrock, lower=[-2, -2], upper=[2, 2], max_evals=200, seed=4, F=None,
                                      CR=None)
        self.assertEqual(de, O.differential_evolution(_rosenbrock, lower=[-2, -2], upper=[2, 2], max_evals=200,
                                                      seed=4))

    def test_slot_labels(self) -> None:
        self.assertEqual(L.slot_label({'name': 'p', 'index': {}}), 'p')
        self.assertEqual(L.slot_label({'name': 'Kd', 'index': {'Radionuclides': 'I-129'}}), 'Kd[I-129]')
        # Integer-like list names first, as JavaScript enumerates an object's keys.
        self.assertEqual(L.slot_label({'name': 'q', 'index': {'b': 'x', '2': 'y', 'a': 'z'}}), 'q[y][x][z]')

    def test_elasticity(self) -> None:
        e = L.elasticity([2.0, 0.0, -4.0], [1.0, 5.0, 2.0], 3.0)
        self.assertEqual(e[0], 1.5)
        self.assertTrue(math.isnan(e[1]))
        self.assertEqual(e[2], -1.5)

    def test_sensitivity_of_a_linear_chain(self) -> None:
        # C1' = -(p12 + p13 + lambda) C1, so dC1/dp12 = -t C1 exactly: by the
        # generated df/dp and by the differenced one.
        for differenced in (False, True):
            r = L.run_sensitivity(example('four-compartment'), ['p12[Fo-42]'], differenced=differenced)
            t, c1, s = r['t'], r['y'][0], r['sens'][0][0]
            live = c1 > 1e-3 * c1[0]
            exact = -t[live] * c1[live]
            # The global error of a solve at rtol 1e-6: a small multiple of it.
            self.assertLess(float(np.max(np.abs(s[live] - exact))) / float(np.max(np.abs(exact))), 5e-5)
            self.assertEqual(r['chosen'][0]['label'], 'p12[Fo-42]')
            self.assertEqual(r['stats']['states'], 8)
            self.assertEqual([x['label'] for x in r['series']], ['C1 [Fo-42]', 'C2 [Fo-42]', 'C3 [Fo-42]',
                                                                  'C4 [Fo-42]'])

    def test_df_dp_is_generated_where_the_model_allows(self) -> None:
        # A(t) with A' = -k A: df/dk = -A, at any state.
        model = {'name': 'decay',
                 'simulation': {'start_time': 0, 'end_time': 30, 'output_points': 4, 'spacing': 'linear',
                                'solver': 'ndf', 'rtol': 1e-10, 'abstol': 1e-14, 'time_unit': 'year'},
                 'parameters': [{'name': 'k', 'value': 0.11, 'index_lists': []}],
                 'compartments': [{'name': 'A', 'initial': '5', 'index_lists': []}],
                 'transfers': [{'name': 'out', 'from': 'A', 'to': None, 'rate': 'k', 'index_lists': []}]}
        system = build_system(Project(model))
        tangent = build_param_tangent(system)
        self.assertTrue(tangent['available'], tangent.get('reason'))
        self.assertEqual(tangent['pvp'](3.0, np.array([2.5]), np.ones(1)).tolist(), [-2.5])
        for name, word in (('farfield', 'far-field'), ('waste-packages', 'waste package'),
                           ('decay-chain', 'no parameters')):
            got = build_param_tangent(build_system(Project(example(name))))
            self.assertFalse(got['available'])
            self.assertIn(word, got['reason'])

    def test_a_sensitivity_run_is_a_run_of_the_model(self) -> None:
        # Progress and stop reach it.
        model = {'name': 'decay',
                 'simulation': {'start_time': 0, 'end_time': 1e5, 'output_points': 11, 'spacing': 'linear',
                                'solver': 'ndf', 'rtol': 1e-10, 'abstol': 1e-14, 'time_unit': 'year'},
                 'parameters': [{'name': 'k', 'value': 1e-4, 'index_lists': []}],
                 'compartments': [{'name': 'A', 'initial': '1', 'index_lists': []}],
                 'transfers': [{'name': 'out', 'from': 'A', 'to': None, 'rate': 'k', 'index_lists': []}]}
        heard: List[Any] = []
        L.run_sensitivity(model, ['k'], on_progress=lambda f, at: heard.append((f, at)))
        self.assertTrue(heard and all(0 < f <= 1 and 0 < at <= 1e5 for f, at in heard), heard[:3])
        asked = [0]

        def stop() -> bool:
            asked[0] += 1
            return asked[0] > 1

        with self.assertRaisesRegex(Exception, 'bort'):
            L.run_sensitivity(model, ['k'], signal=stop)
        # Each compartment's own floor: A = 1 - q t, allowed below zero.
        drain = {'name': 'draining',
                 'simulation': {'start_time': 0, 'end_time': 3, 'output_points': 4, 'spacing': 'linear',
                                'solver': 'ndf', 'rtol': 1e-10, 'abstol': 1e-12, 'time_unit': 'year'},
                 'parameters': [{'name': 'q', 'value': 1, 'index_lists': []}],
                 'compartments': [{'name': 'A', 'initial': '1', 'non_negative': False, 'index_lists': []}],
                 'transfers': [{'name': 'out', 'from': 'A', 'to': None, 'rate': 'q', 'multiply_by_donor': False,
                                'index_lists': []}]}
        r = L.run_sensitivity(drain, ['q'])
        self.assertLess(float(np.max(np.abs(r['y'][0] - (1 - r['t'])))), 1e-8)
        self.assertLess(float(np.max(np.abs(r['sens'][0][0] + r['t']))), 1e-8)
        # The run's restarts: a thousandth of a year of source at year 5,000.
        pulse = {'name': 'pulse',
                 'simulation': {'start_time': 0, 'end_time': 10000, 'output_points': 11, 'spacing': 'linear',
                                'solver': 'ndf', 'rtol': 1e-8, 'abstol': 1e-12, 'time_unit': 'year',
                                'switch_times': [5000, 5000.001]},
                 'parameters': [{'name': 'k', 'value': 1e-4, 'index_lists': []}],
                 'compartments': [{'name': 'A', 'initial': '0', 'index_lists': []}],
                 'inflows': [{'name': 'In', 'to': 'A', 'rate': 'if(time() >= 5000 && time() < 5000.001, 1000, 0)',
                              'index_lists': []}],
                 'transfers': [{'name': 'out', 'from': 'A', 'to': None, 'rate': 'k', 'index_lists': []}]}
        r = L.run_sensitivity(pulse, ['k'])
        plain = run(Project(pulse), on_grid=True)
        self.assertGreaterEqual(r['stats']['restarts'], 2)
        self.assertLess(float(np.max(np.abs(r['y'][0] - np.array(plain.y)[:, 0]))), 1e-6)
        self.assertLess(abs(r['sens'][0][0][-1] / (-(r['t'][-1] - 5000.0005) * r['y'][0][-1]) - 1), 1e-5)
        # And its settings: held to steps of 10 over 1,000 years.
        limited = {'name': 'decay',
                   'simulation': {'start_time': 0, 'end_time': 1000, 'output_points': 5, 'spacing': 'linear',
                                  'solver': 'ndf', 'rtol': 1e-4, 'abstol': 1e-9, 'time_unit': 'year',
                                  'max_step': 10},
                   'parameters': [{'name': 'k', 'value': 1e-3, 'index_lists': []}],
                   'compartments': [{'name': 'A', 'initial': '1', 'index_lists': []}],
                   'transfers': [{'name': 'out', 'from': 'A', 'to': None, 'rate': 'k', 'index_lists': []}]}
        self.assertGreaterEqual(L.run_sensitivity(limited, ['k'])['stats']['nsteps'], 100)

    def test_sensitivity_refusals(self) -> None:
        with self.assertRaisesRegex(L.SensitivityError, 'no compartments to differentiate'):
            L.run_sensitivity(example('post-processing'), ['Dilution'])
        with self.assertRaisesRegex(L.SensitivityError, 'Name at least one parameter'):
            L.run_sensitivity(example('four-compartment'), ['nothing'])
        with self.assertRaisesRegex(L.SensitivityError, 'Choose at most 1'):
            L.run_sensitivity(example('four-compartment'), ['p12[Fo-42]', 'p34[Fo-42]'], most=1)
        # What the sensitivity equations cannot carry.
        with self.assertRaisesRegex(L.SensitivityError, "'Glaciation' makes the state jump at t=100000"):
            L.run_sensitivity(example('waste-packages'), ['matrix_rate'])
        for model, parameters, why in REFUSAL_MODELS():
            with self.subTest(why=why):
                with self.assertRaisesRegex(L.SensitivityError, why):
                    L.run_sensitivity(model, parameters)
        # A min/max that only reports is no reason to refuse: run, with the
        # event's instant a row of its own as the run has it.
        self.assertEqual(len(L.run_sensitivity(example('recorders'), ['k_out[Cs-137]'])['t']),
                         len(run(Project(example('recorders')), on_grid=True).t))

    def test_calibration_finds_a_value_it_was_given(self) -> None:
        model = example('lookup-driver')
        truth = 3.1e-4
        m2 = json.loads(json.dumps(model))
        next(p for p in m2['parameters'] if p['name'] == 'k_sed')['value'] = truth
        want = float(run(Project(m2), on_grid=True).series('Dose [I-129]')[-1])
        out = C.calibrate(model, targets=[{'output': 'Dose [I-129]', 'when': 'end', 'value': want}],
                          variables=[{'key': 'k_sed', 'lower': 1e-5, 'upper': 1e-3, 'space': 'log'}],
                          method='nelder', max_evals=60)
        self.assertTrue(out['ok'])
        self.assertTrue(out['matched'])
        self.assertLess(abs(out['values'][0]['value'] / truth - 1), 1e-3)
        self.assertEqual(out['values'][0]['was'], 2e-4)

    def test_calibration_units_stops_and_bounds(self) -> None:
        units = {v['key']: v['unit'] for v in C.variables_of(example('biosphere'))}
        self.assertEqual((units['Kd[I-129]'], units['wellVolume']), ('m^3/kg', 'm^3'))
        post = {'name': 'post', 'simulation': {'start_time': 0, 'end_time': 10, 'output_points': 3, 'spacing': 'linear'},
                'parameters': [{'name': 'd', 'value': 2, 'unit': '', 'index_lists': []}],
                'expressions': [{'name': 'Dose', 'equation': 'd * 3', 'index_lists': []}]}
        seen: List[Any] = []
        out = C.calibrate(post, targets=[{'output': 'Dose', 'when': 'end', 'value': 9}],
                          variables=[{'key': 'd', 'lower': 0.1, 'upper': 10}], method='nelder', max_evals=50,
                          signal=lambda: len(seen) >= 4, on_progress=seen.append)
        self.assertEqual(out['reason'], 'stopped')
        self.assertEqual(out['targets'][0]['got'], 3 * out['values'][0]['value'])

        def at(value: float) -> Dict[str, Any]:
            return C.calibrate(post, targets=[{'output': 'Dose', 'when': 'end', 'value': value, 'scale': 'absolute'}],
                               variables=[{'key': 'd', 'lower': 0, 'upper': 10}], method='nelder',
                               max_evals=200)['values'][0]

        self.assertEqual(at(3e-4)['pinned'], 'lower')
        self.assertIsNone(at(9)['pinned'])
        self.assertEqual(at(60)['pinned'], 'upper')
        # A space or a method named like a property of every object falls back.
        got = C.calibrate(post, targets=[{'output': 'Dose', 'when': 'end', 'value': 9}],
                          variables=[{'key': 'd', 'lower': 0.1, 'upper': 10, 'space': 'constructor'}],
                          method='toString', max_evals=60)
        self.assertTrue(got['ok'] and got['matched'])
        self.assertEqual(got['method'], 'toString')

    def test_calibration_refusals(self) -> None:
        model = example('four-compartment')
        var = {'key': 'p34[Fo-42]', 'lower': 1e-6, 'upper': 1e-4}
        tgt = {'output': 'C4 [Fo-42]', 'when': 'end', 'value': 1}
        with self.assertRaisesRegex(O.OptimiseError, 'No endpoint has been given a target value'):
            C.calibrate(model, targets=[{'output': '', 'value': 1}], variables=[var])
        with self.assertRaisesRegex(O.OptimiseError, 'No parameter has been allowed to vary'):
            C.calibrate(model, targets=[tgt], variables=[])
        with self.assertRaisesRegex(O.OptimiseError, "'nope' is not a parameter of this model"):
            C.calibrate(model, targets=[tgt], variables=[{**var, 'key': 'nope'}])
        with self.assertRaisesRegex(O.OptimiseError, r"has no range: 0\.0001 to 0\.000001\."):
            C.calibrate(model, targets=[tgt], variables=[{**var, 'lower': 1e-4, 'upper': 1e-6}])
        with self.assertRaisesRegex(O.OptimiseError, 'searched in the logarithm'):
            C.calibrate(model, targets=[tgt], variables=[{**var, 'lower': 0, 'space': 'log'}])

    def test_readings(self) -> None:
        res = run(Project(example('four-compartment')), on_grid=True)
        v = res.series('C2 [Fo-42]')
        self.assertEqual(C.reading_of(res, {'output': 'C2 [Fo-42]', 'when': 'peak'}), float(np.max(v)))
        self.assertEqual(C.reading_of(res, {'output': 'C2 [Fo-42]', 'when': 'end'}), float(v[-1]))
        k = int(np.argmin(np.abs(res.t - 1234.5)))
        self.assertEqual(C.reading_of(res, {'output': 'C2 [Fo-42]', 'when': 'at', 'time': 1234.5}), float(v[k]))
        self.assertTrue(math.isnan(C.reading_of(res, {'output': 'nothing', 'when': 'end'})))


# ---------------------------------------------------------------------------------------------

@needs_app
class OptimiserParity(unittest.TestCase):
    def test_every_point_the_optimisers_visit(self) -> None:
        theirs = app('optimise', cases=OPTIMISER_CASES)['results']
        for case, js in zip(OPTIMISER_CASES, theirs):
            with self.subTest(case=json.dumps(case, default=str)):
                mine = optimise_case(case)
                if 'error' in js:
                    self.assertEqual(mine.get('error'), js['error'])
                    self.assertEqual(mine.get('type'), js['type'])
                    continue
                self.assertTrue(same(mine['result'], js['result']), f"{mine['result']} != {js['result']}")
                self.assertEqual(len(mine['trace']), len(js['trace']))
                for a, b in zip(mine['trace'], js['trace']):
                    self.assertTrue(same(a, b), f'{a} != {b}')

    def test_objective(self) -> None:
        theirs = app('objective', cases=OBJECTIVE_CASES)['results']
        for case, js in zip(OBJECTIVE_CASES, theirs):
            with self.subTest(case=json.dumps(_enc(case))):
                if 'error' in js:
                    self.assertEqual(js['type'], 'TypeError')
                    with self.assertRaises(TypeError):
                        O.objective_of(case['readings'], case['targets'])
                    continue
                mine = O.objective_of(case['readings'], case['targets'])
                self.assertTrue(same(mine, js), f'{mine} != {js}')

    def test_the_text_a_point_is_known_by(self) -> None:
        rng = np.random.default_rng(3)
        values = [0.0, -0.0, 1.0, -1.0, 0.1, 1 / 3, 2 / 3, 1e-7, 1.23456789012345e-7, 123456789012.5,
                  1234567890125.0, 1000000000005.0, 999999999999.5, 9.9999999999995, 1e21, 1.5e300, 5e-324,
                  math.nan, math.inf, -math.inf, 1000000.00000002, 0.5, 2.0 ** 53, 2.0 ** 53 + 2,
                  12345678901234567890.0, 999999.9999995, 0.0000012345678901250]
        values += (rng.standard_normal(300) * 10.0 ** rng.integers(-12, 13, 300)).tolist()
        values += [float(k) * 10 ** e + 5 for k in (123456789012, 999999999999, 100000000000) for e in (1, 2)]
        theirs = app('precision', values=values)['results']
        for v, js in zip(values, theirs):
            self.assertEqual(_to_precision(v, 12), js, repr(v))


@needs_app
class SlotParity(unittest.TestCase):
    def test_every_example_offers_the_same_slots(self) -> None:
        for name in ('four-compartment', 'biosphere', 'landscape', 'lookup-driver', 'post-processing', 'scenarios',
                     'recorders', 'farfield', 'waste-packages', 'decay-chain'):
            with self.subTest(example=name):
                model = example(name)
                js = app('slots', model=model)['slots']
                mine = L.parameter_slots(build_system(Project(model), jacobian=False))
                self.assertEqual(len(mine), len(js))
                for a, b in zip(mine, js):
                    self.assertEqual(L.slot_label(a), b['label'])
                    self.assertEqual(list(a['index']), b['keys'])
                    self.assertEqual((a['slot'], a['name'], a['index'], a['unit']),
                                     (b['slot'], b['name'], b['index'], b['unit']))
                    self.assertTrue(same(a['value'], float(b['value'])), f"{a['value']} != {b['value']}")
                vs = app('variables', model=model)['variables']
                self.assertTrue(same(C.variables_of(model), [{**v, 'value': float(v['value'])} for v in vs]))


# (example, parameters, differenced, whether the step counts have been
# identical): see test_states_and_their_derivatives. The default is the
# generated df/dp, as in the application.
SENSITIVITY_CASES = [
    ('four-compartment', ['p13[Fo-42]', 'p34[Fo-42]'], False, True),
    ('four-compartment', ['p13[Fo-42]', 'p34[Fo-42]'], True, True),
    ('recorders', ['k_out[Cs-137]'], False, True),
    ('landscape', ['Kd[Tc-99]', 'discharge[Mire]'], False, True),
    ('scenarios', ['Flush', 'Runoff'], False, True),
    ('lookup-driver', ['k_sed', 'V_lake[I-129]', 'V_rego'], False, False),
]

# The augmented system is compared point by point on more models than are
# solved: biosphere's Kd takes 169,000 steps, four-compartment's p12 is
# ill-conditioned (its sensitivities of C3 and C4 are the rounding noise of a
# quantity of 1e9, and the step-size controller chases different noise on
# each side), and scenarios and farfield take tens of thousands of steps here
# -- but what is integrated is the same, and that is quick to compare.
AUGMENTED_CASES = [
    ('four-compartment', ['p12[Fo-42]', 'p34[Fo-42]']),
    ('lookup-driver', ['k_sed', 'V_lake[I-129]', 'V_rego']),
    ('landscape', ['Kd[Tc-99]', 'discharge[Mire]']),
    ('recorders', ['k_out[Cs-137]', 'Volume[Cs-137]']),
    ('biosphere', ['Kd[I-129]', 'geoTransit', 'leachRate[Tc-99]']),
    ('scenarios', ['Flush', 'Runoff']),
    ('farfield', ['leach_rate[U-238]', 'Kd_matrix[Th-230]']),
]


@needs_app
class SensitivityParity(unittest.TestCase):
    def test_the_generated_df_dp(self) -> None:
        """The application's ``paramTangent`` and this package's, at the same
        states, times and seeds: whether each is offered, why not, and every
        value -- to the last bit or two. The chain rule is summed leaf by leaf
        here and in one generated pass there, so a slot reached along several
        paths (and the seed of ones, which sums every parameter) can round
        differently in its last place; most values are identical, and the
        share that is is printed."""
        rng = np.random.default_rng(11)
        for name in ('four-compartment', 'lookup-driver', 'scenarios', 'recorders', 'biosphere', 'landscape',
                     'waste-packages', 'farfield', 'decay-chain', 'post-processing'):
            with self.subTest(example=name):
                model = example(name)
                system = build_system(Project(model))
                mine = build_param_tangent(system)
                points = []
                for frac in (0.0, 0.01, 0.4):
                    y = (rng.uniform(0, 10, system.nstate) * 10 ** rng.uniform(-3, 3, system.nstate)).tolist()
                    t = system.start_time + (system.end_time - system.start_time) * frac
                    for slot in range(system.nparam):
                        seed = [0.0] * system.nparam
                        seed[slot] = 1.0
                        points.append({'t': t, 'y': y, 'seed': seed})
                    points.append({'t': t, 'y': y, 'seed': [1.0] * max(1, system.nparam)})
                js = app('pvp', model=model, points=points)
                self.assertEqual(mine['available'], js['available'])
                if not js['available']:
                    self.assertEqual(mine['reason'], js['reason'])
                    continue
                exact = total = 0
                for p, q in zip(points, js['points']):
                    got = mine['pvp'](p['t'], np.array(p['y']), np.array(p['seed']))
                    theirs = np.array(q, dtype=float)
                    exact += int(np.sum(got == theirs))
                    total += got.size
                    d = relative(got, theirs)
                    _note('sensitivity: generated df/dp, relative', d)
                    self.assertLess(d, 1e-14, f'{got.tolist()} != {q}')
                WORST['sensitivity: generated df/dp, share identical'] = min(
                    WORST.get('sensitivity: generated df/dp, share identical', 1.0), exact / max(1, total))

    def test_the_same_augmented_system(self) -> None:
        """What is integrated: the right-hand side of [y, dy/dp...] and its
        iteration Jacobian at the same points, the initial values, the
        tolerances, the pattern and its colouring -- with df/dp generated, as
        by default, and differenced."""
        rng = np.random.default_rng(5)
        for (name, parameters), differenced in [(c, d) for c in AUGMENTED_CASES for d in (False, True)]:
            with self.subTest(example=name, differenced=differenced):
                model = example(name)
                problem = L.sensitivity_problem(model, parameters, differenced=differenced)
                generated = not differenced and build_param_tangent(problem['system'])['available']
                n, m = problem['n'], problem['m']
                sim = problem['project'].simulation
                t0, t1 = float(sim['start_time']), float(sim['end_time'])
                points = [{'t': t0, 'Y': problem['y0'].tolist()}]
                for frac in (0.001, 0.3, 0.9):
                    y = rng.uniform(0, 10, n) * 10 ** rng.uniform(-3, 3, n)
                    s = rng.standard_normal(n * m) * 10 ** rng.uniform(-2, 6, n * m)
                    points.append({'t': t0 + (t1 - t0) * frac, 'Y': np.concatenate([y, s]).tolist()})
                js = app('augmented', model=model, opts={'parameters': parameters, 'differenced': differenced},
                         points=points)
                self.assertTrue(same(problem['y0'].tolist(), js['y0']))
                self.assertTrue(same(problem['abstol'].tolist(), js['atol']))
                pattern = problem['jacobian']['pattern']
                self.assertEqual(pattern.col_ptr.tolist(), js['pattern']['colPtr'])
                self.assertEqual(pattern.row_idx.tolist(), js['pattern']['rowIdx'])
                groups = problem['jacobian']['groups']
                self.assertEqual(None if groups is None else [g.tolist() for g in groups], js['groups'])
                for p, q in zip(points, js['points']):
                    Y = np.array(p['Y'])
                    f = problem['dydt'](p['t'], Y)
                    fj = np.array(q['f'], dtype=float)
                    # Per block of the vector, over the block's largest entry.
                    # The states' block is the model's derivative, which the
                    # engine computes as the application does. A block of
                    # dy/dp is J·S -- summed over the Jacobian's columns here,
                    # term by term in the generated tangent there, so a row of
                    # several terms can differ in its last bit or two -- plus
                    # the one-sided difference (f(p + h) - f(p)) / h, which
                    # divides whatever last-bit difference there is in f by
                    # h ~ 1.5e-8 max(|p|, 1): the far field's derivative, the
                    # one the engine does not compute in the same order, comes
                    # out 1e-12 apart after that division. Generated, df/dp is
                    # the application's to the bit (test_the_generated_df_dp),
                    # and only the J·S sum is left.
                    for b in range(1 + m):
                        part = slice(b * n, (b + 1) * n)
                        d = series_difference(f[part], fj[part])
                        area = 'states' if b == 0 else ('dy/dp' if generated else 'dy/dp, differenced')
                        _note('sensitivity: the augmented right-hand side, ' + area, d)
                        self.assertLess(d, 1e-13 if b == 0 else (1e-12 if generated else 1e-10))
                    J = problem['jacobian']['evaluate'](p['t'], Y)
                    if q['J'] is None:
                        self.assertIsNone(J)
                    else:
                        d = relative(J, q['J'])
                        _note('sensitivity: the iteration Jacobian', d)
                        self.assertLess(d, 1e-13)

    def test_states_and_their_derivatives(self) -> None:
        """The solve. The augmented system is the same to the last bit or two
        (above), but the engine's NDF does not factorise it exactly as the
        application does (LAPACK, or -- with numba -- the application's own
        dense LU, formed a little differently), so the solves are the same
        only to round-off, and the step-size controller turns a last-bit
        difference into a slightly different sequence of steps -- as does
        V8's Math.pow, which rounds differently from the C library's on about
        one argument in ten and chooses every step size: lookup-driver's first
        differs in the 17th digit of t, at step 250, and ends 1-2% longer
        depending on which LU ran. So: the step count within 5% (it has been
        the same on four-compartment, and that is printed), and every series
        within 10 x rtol of its block's peak, as the engine's own run
        comparison allows. The worst seen are printed."""
        for name, parameters, differenced, same_steps in SENSITIVITY_CASES:
            with self.subTest(example=name, differenced=differenced):
                model = example(name)
                js = app('sensitivity', model=model, opts={'parameters': parameters, 'differenced': differenced})
                mine = L.run_sensitivity(model, parameters, differenced=differenced)
                rtol = float(model['simulation'].get('rtol', 1e-3))
                apart = abs(mine['stats']['nsteps'] / js['stats']['nsteps'] - 1)
                _note('sensitivity: step count, relative', apart)
                if same_steps:
                    _note('sensitivity: step count where it has been the same', apart)
                # The augmented solve's step count follows the round-off of its
                # LU: landscape's takes 2,169, 2,270 or 2,263 steps with SuperLU
                # in the natural, COLAMD or MMD order, against the
                # application's 2,289 -- 0.8 to 5.2 per cent from one choice of
                # column order alone.
                self.assertLess(apart, 0.08)
                self.assertEqual(mine['stats']['states'], js['stats']['states'])
                # The grid to the bit; a discrete event's instant, a row of its
                # own, is located by the solver and so to its round-off.
                self.assertLess(relative(mine['t'], js['t']), 1e-9)
                self.assertEqual([(s.name, s.base, s.width, s.kind) for s in mine['states']],
                                 [(s['name'], s['base'], s['width'], s['kind']) for s in js['states']])
                self.assertTrue(same(mine['chosen'], [{**c, 'value': float(c['value'])} for c in js['chosen']]))
                # Every state named as the application names it, the dialog's list.
                self.assertTrue(same(mine['series'], js['series']))
                self.assertEqual(mine['stats']['restarts'], js['stats']['restarts'])
                worst_y = series_difference(mine['y'], js['y'])
                worst_s = max(series_difference(mine['sens'][k], js['sens'][k]) for k in range(len(parameters)))
                _note('sensitivity: states, over the peak, in rtol', worst_y / rtol)
                _note('sensitivity: dy/dp, over the block\'s peak, in rtol', worst_s / rtol)
                self.assertLess(worst_y, 10 * rtol)
                self.assertLess(worst_s, 10 * rtol)
                # The elasticity itself, on the application's own numbers: exact.
                for k, c in enumerate(js['chosen']):
                    for i, (yr, sr) in enumerate(zip(js['y'], js['sens'][k])):
                        self.assertTrue(same(L.elasticity(yr, sr, c['value']).tolist(), js['elasticity'][k][i]))

    def test_refusals(self) -> None:
        cases = [
            (example('post-processing'), {'parameters': ['Dilution']}),
            (example('four-compartment'), {'parameters': []}),
            (example('four-compartment'), {'parameters': ['nothing', 'p12']}),
            (example('four-compartment'), {'parameters': ['p12[Fo-42]', 'p34[Fo-42]'], 'most': 1}),
            (example('four-compartment'), {'parameters': ['p12[Fo-42]', 'p34[Fo-42]'], 'most': '1'}),
            # What the sensitivity equations cannot carry, in the same words.
            (example('waste-packages'), {'parameters': ['matrix_rate', 'flush_rate']}),
            *((model, {'parameters': parameters}) for model, parameters, _ in REFUSAL_MODELS()),
        ]
        for model, opts in cases:
            with self.subTest(opts=opts):
                js = app('sensitivity', model=model, opts=opts)
                self.assertIn('error', js)
                with self.assertRaises(L.SensitivityError) as caught:
                    L.run_sensitivity(model, opts['parameters'], most=opts.get('most'))
                self.assertEqual(str(caught.exception), js['error'])


FOUR_TARGETS = [{'output': 'C4 [Fo-42]', 'when': 'at', 'time': 100000, 'value': 3e9},
                {'output': 'Outflow [Fo-42]', 'when': 'peak', 'value': 2e4, 'scale': 'log'}]
FOUR_VARIABLES = [{'key': 'p34[Fo-42]', 'lower': 1e-6, 'upper': 1e-4, 'space': 'log'},
                  {'key': 'p12[Fo-42]', 'lower': 2e-6, 'upper': 5e-5}]

# `runs`: how far the engine's runs of the model are from the application's,
# in the model's rtol -- 10 as the engine's own run comparison allows. The
# NDF's runs of lookup-driver are at present two steps off the application's
# (test_engine_parity says so too), and its readings up to 13 x rtol apart;
# the points tried are still the same, and are compared exactly.
CALIBRATION_CASES: List[Dict[str, Any]] = [
    {'model': 'four-compartment', 'opts': {'targets': FOUR_TARGETS, 'variables': FOUR_VARIABLES,
                                           'method': 'nelder', 'maxEvals': 40}},
    # p12 on its upper bound, differenced backwards there: Levenberg-Marquardt
    # works along a valley flat in p34 for its whole budget -- the objective
    # agrees to 2e-6 where p34 differs by 2e-5 -- and how far each side gets
    # along it follows the round-off of its LU (5e-6 with the application's
    # own, compiled; 2e-5 with LAPACK). Hence 100 x rtol here, and 1e-4 on
    # the values below.
    {'model': 'four-compartment', 'runs': 100, 'opts': {'targets': FOUR_TARGETS, 'variables': FOUR_VARIABLES,
                                                        'method': 'lm', 'maxEvals': 30}},
    {'model': 'four-compartment', 'opts': {'targets': FOUR_TARGETS, 'variables': FOUR_VARIABLES,
                                           'method': 'de', 'maxEvals': 30, 'seed': 2}},
    {'model': 'four-compartment', 'stopAfter': 5, 'opts': {
        'targets': FOUR_TARGETS, 'variables': FOUR_VARIABLES, 'method': 'de', 'maxEvals': 30}},
    {'model': 'scenarios', 'opts': {
        'targets': [{'output': 'Peak_dose', 'when': 'end', 'value': 5e-4, 'weight': 2},
                    {'output': None, 'value': 3}, {'output': 'Conc', 'when': 'peak', 'value': 0}],
        'variables': [{'key': 'Flush', 'lower': 0.01, 'upper': 1}],
        'method': 'simplex', 'maxEvals': 12}},
    {'model': 'landscape', 'opts': {
        'targets': [{'output': 'Downstream [Tc-99]', 'when': 'end', 'value': 1e12},
                    {'output': 'Water [Tc-99, Mire]', 'when': 'at', 'time': 3000, 'value': 1e9, 'scale': 'log'}],
        'variables': [{'key': 'discharge[Mire]', 'lower': 0.005, 'upper': 0.1, 'space': 'log'},
                      {'key': 'Kd[Tc-99]', 'lower': 0.01, 'upper': 1, 'start': 'x'}],
        'method': 'nelder', 'maxEvals': 3}},
    # Nothing to integrate, and stopped: the runner stops such a model once it
    # is done, so the best point is re-read as NaN (see calibrate.KNOWN_QUIRKS).
    {'model': 'post-processing', 'stopAfter': 6, 'opts': {
        'targets': [{'output': 'Dose_total', 'when': 'peak', 'value': 1e-5},
                    {'output': 'Conc [Ni-59]', 'when': 'at', 'time': 6000, 'value': 1, 'scale': 'absolute'}],
        'variables': [{'key': 'Dilution', 'lower': 1e5, 'upper': 1e7, 'space': 'log'},
                      {'key': 'Fraction[Ni-59]', 'lower': 0.1, 'upper': 1}],
        'method': 'de', 'maxEvals': 20, 'seed': 8}},
    {'model': 'post-processing', 'opts': {
        'targets': [{'output': 'Dose_total', 'when': 'peak', 'value': 1e-5}],
        'variables': [{'key': 'Dilution', 'lower': 1e5, 'upper': 1e7, 'space': 'log'}],
        'method': 'lm'}},
    # A space and a method named like a property of every object: the defaults.
    {'model': 'post-processing', 'opts': {
        'targets': [{'output': 'Dose_total', 'when': 'peak', 'value': 1e-5, 'scale': 'toString'}],
        'variables': [{'key': 'Fraction[Ni-59]', 'lower': 0, 'upper': 1, 'space': 'constructor'}],
        'method': 'toString', 'maxEvals': 25}},
    {'model': 'lookup-driver', 'runs': 100, 'opts': {
        'targets': [{'output': 'Dose [I-129]', 'when': 'end', 'value': 0.01},
                    {'output': 'Lake [I-129]', 'when': 'at', 'time': 5000, 'value': 5e9, 'weight': 0.5}],
        'variables': [{'key': 'k_sed', 'lower': 1e-5, 'upper': 1e-3, 'space': 'log', 'start': 5e-4},
                      {'key': 'V_lake[I-129]', 'lower': 5000, 'upper': 50000, 'start': 'x'}],
        'method': 'nelder', 'maxEvals': 3}},
]


def _calibrate_here(case: Dict[str, Any]) -> Dict[str, Any]:
    o = case['opts']
    progress: List[Dict[str, Any]] = []
    signal = _Stop(case['stopAfter'], progress) if case.get('stopAfter') is not None else None
    result = C.calibrate(example(case['model']), targets=o.get('targets'), variables=o.get('variables'),
                         method=o.get('method'), max_evals=o.get('maxEvals'), seed=o.get('seed'),
                         on_progress=progress.append, signal=signal)
    del result['ms']
    return {'result': result, 'progress': progress}


@needs_app
class CalibrationParity(unittest.TestCase):
    def test_calibrations(self) -> None:
        """Every evaluation is a run, and runs agree with the application's to
        round-off, not to the bit: V8's Math.pow rounds differently from the
        C library's on about one argument in ten, the NDF's step-size choice
        is a power, so step sequences can part in the last digits and the
        readings with them (lookup-driver's are 10-20 x rtol apart). So
        nothing that passes through a run is compared bit for bit:

        * the readings, the objective and every evaluation's value, to 10 x
          the run's rtol (the engine's own run comparison) -- 100 x for a
          model whose runs are further apart (``runs``);
        * the values of the variables, final and at every evaluation, to 1e-9
          relatively. While the search takes the same decisions its points
          are the same arithmetic on the same numbers and agree exactly (they
          do, on every case here); the margin is for the last digit, not for
          a different path;
        * Levenberg-Marquardt differences the runs over 1e-6 of a variable's
          range, which turns their round-off into its points, and every
          iteration builds on the last: its values to 1e-4 (four-compartment,
          whose p12 sits on its upper bound and is differenced backwards there,
          works along a flat valley for its whole budget and ends 5e-6 to 2e-5
          apart, depending on the LU), and its evaluations only counted.

        What does not pass through a run is exact: the counts, the reasons,
        whether it matched, and the objective recomputed from each side's own
        readings. A count or a reason that differed would be a search that
        took another decision -- a real difference, even if round-off started
        it; the cases are chosen so that no two values it compares are within
        the runs' disagreement of each other."""
        for case in CALIBRATION_CASES:
            with self.subTest(model=case['model'], method=case['opts'].get('method')):
                model = example(case['model'])
                rtol = float(model['simulation'].get('rtol', 1e-3))
                allow = case.get('runs', 10) * rtol
                js = app('calibrate', model=model, opts=case['opts'], stopAfter=case.get('stopAfter'))
                mine = _calibrate_here(case)
                a, b = mine['result'], js['result']
                lm = case['opts'].get('method') == 'lm'
                for key in ('ok', 'matched', 'method', 'reason', 'evals'):
                    self.assertEqual(a[key], b[key], key)
                self.assertEqual([p['evals'] for p in mine['progress']], [p['evals'] for p in js['progress']])
                # The objective, from the application's readings: exact.
                targets = [t for t in case['opts']['targets'] if t.get('output')]
                if b['targets'] and all(t['got'] is not None for t in b['targets']):
                    theirs = O.objective_of([t['got'] for t in b['targets']], targets)['objective']
                    self.assertTrue(same(theirs, b['objective']))
                    ours = O.objective_of([t['got'] for t in a['targets']], targets)['objective']
                    self.assertTrue(same(ours, a['objective']))
                for u, v in zip(a['targets'], b['targets']):
                    self.assertEqual((u['output'], u['scale']), (v['output'], v['scale']))
                    self.assertTrue(same(u['want'], float(v['want'])))
                    d = relative(u['got'], v['got'])
                    _note('calibration: readings, in rtol' + (' (lm)' if lm else ''), d / rtol)
                    self.assertLess(d, allow)
                self.assertEqual([(v['key'], v['pinned']) for v in a['values']],
                                 [(v['key'], v['pinned']) for v in b['values']])
                for u, v in zip(a['values'], b['values']):
                    # What the model held and the bounds: read, not run.
                    self.assertTrue(same(u['was'], float(v['was'])))
                    for key in ('lower', 'upper'):
                        self.assertTrue(same(u[key], float(v[key])), key)
                    d = relative(u['value'], v['value'])
                    _note('calibration: final values' + (' (lm)' if lm else ''), d)
                    self.assertLess(d, 1e-4 if lm else 1e-9)
                if lm:
                    continue
                # Every point the search tried, and its value.
                for p, q in zip(mine['progress'], js['progress']):
                    self.assertEqual(p['values'] is None, q['values'] is None)
                    if p['values'] is not None:
                        d = relative(p['values'], q['values'])
                        _note('calibration: every point tried', d)
                        self.assertLess(d, 1e-9)
                    d = max(relative(p['fx'], q['fx']), relative(p['best'], q['best']))
                    _note('calibration: every evaluation\'s objective, in rtol', d / rtol)
                    self.assertLess(d, allow)

    def test_readings(self) -> None:
        model = example('four-compartment')
        targets = [{'output': 'C2 [Fo-42]', 'when': 'peak'}, {'output': 'C2 [Fo-42]', 'when': 'end'},
                   {'output': 'Outflow [Fo-42]', 'when': 'at', 'time': 1234.5},
                   {'output': 'Outflow [Fo-42]', 'time': 'soon'}, {'output': 'p12 [Fo-42]', 'when': 'end'},
                   {'output': 'nothing', 'when': 'end'}]
        js = app('reading', model=model, targets=targets)['readings']
        res = run(Project(model), on_grid=True)
        mine = [C.reading_of(res, t) for t in targets]
        d = relative(mine, js)
        _note('readings', d)
        self.assertLess(d, 1e-12)

    def test_refusals(self) -> None:
        model = example('four-compartment')
        var = {'key': 'p34[Fo-42]', 'lower': 1e-6, 'upper': 1e-4}
        tgt = {'output': 'C4 [Fo-42]', 'when': 'end', 'value': 1}
        cases = [
            {'targets': [], 'variables': [var]},
            {'targets': [{'value': 3}], 'variables': [var]},
            {'targets': [tgt], 'variables': []},
            {'targets': [tgt], 'variables': [{**var, 'key': 'nope'}]},
            {'targets': [tgt], 'variables': [{**var, 'key': None}]},
            {'targets': [tgt], 'variables': [{**var, 'lower': 1e-4, 'upper': 1e-6}]},
            {'targets': [tgt], 'variables': [{**var, 'lower': 'a'}]},
            {'targets': [tgt], 'variables': [{**var, 'lower': 0, 'space': 'log'}]},
        ]
        for opts in cases:
            with self.subTest(opts=opts):
                js = app('calibrate', model=model, opts=opts)
                self.assertEqual(js.get('type'), 'OptimiseError')
                with self.assertRaises(O.OptimiseError) as caught:
                    C.calibrate(model, targets=opts['targets'], variables=opts['variables'])
                self.assertEqual(str(caught.exception), js['error'])


if __name__ == '__main__':
    unittest.main()
