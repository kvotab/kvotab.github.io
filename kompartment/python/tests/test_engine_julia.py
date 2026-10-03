"""The ported DifferentialEquations.jl solvers against the application's.

``kompartment.engine.solvers.julia`` ports ``src/ode/julia/`` and its adapter
``src/ode/julia-solvers.js``: the six methods first ported (``SOLVERS``) and
the six that came with the default algorithm (``NEW``) -- the switching
solvers ``auto`` (the explicit methods, then the NDF from where the run turns
stiff) and ``auto_julia`` (DifferentialEquations.jl's default as it is), the
matrix-free ``fbdf_krylov``, ``rosenbrock23``, and the explicit ``tsit5`` and
``vern7``. Seven kinds of check, all against the application's own code run
in Node:

* ``Tables``: what has no floating point to argue about -- the tableaux, the
  reverse Cuthill-McKee ordering, the colouring of the Jacobian's columns --
  is the application's exactly.
* ``Problems``: test problems defined in ``tests/node/julia_solvers.mjs`` and
  mirrored here expression for expression, so that ``f`` and the Jacobian are
  the same functions to the last bit (Robertson, a decay chain with Bateman's
  closed form, van der Pol, HIRES, terminal events, non-negative states, a
  clock-driven forcing, a chain restarted late in a run just after a jump),
  through all eleven methods -- the explicit ones not on Robertson, which is
  too stiff for them -- and a spread of options: every count the adapter
  reports, the switching solver's account of its methods and GMRES's
  iterations, the rows, where a run stopped, the errors.
* ``Switching``, ``Krylov`` and ``Explicit``: what came with the default
  algorithm, on its own -- which method took every saved row, the switch's
  options, the carry from one solve of a run to the next, the run log's
  line; GMRES, and the matrix-free FBDF on 600 states; Vern7's lazy stages,
  an explicit method forming no matrix, OrdinaryDiffEq's starting step.
* ``HandOff``: ``auto`` -- the package stopping where it would have switched
  to a stiff method, the NDF going on from there with one row at every time
  asked, the corners of the clock-read tables landed on, the run handed to the
  NDF from the start.
* ``BitIdentity``: the same runs, and bundled examples through the runner,
  with the two things this port does differently from the package put back
  -- a transcription of the package's dense LU in place of LAPACK's, and V8's
  own ``Math.pow`` values (asked of Node for every argument a run meets) in
  place of the C library's ``pow`` -- are the application's step for step,
  bit for bit.
* ``Examples``: every bundled example with each of the ids, through the
  application's runner and this engine's.

Why the counts carry a margin. ``BitIdentity`` shows that the port's own
arithmetic is the package's. Left as it ships, the port factorises with
LAPACK and SuperLU and raises to powers with the platform's ``pow``, and each
differs from the application in the last bit of some results -- V8's ``pow``
agrees with the C library's on about 91 % of the arguments these controllers
meet. Most runs never notice. Where an error estimate sits at rounding level
(Rodas5P on Robertson's first transient, FBDF on a long plateau, anything
stepping over a lookup table's corners) a last-bit difference moves the next
step size and the two step sequences part; the counts then differ by a few
per cent while both runs are equally good. So: steps within max(2, 1 %), as
``test_engine_parity.py`` allows, and every count scaled from that; on the
bundled examples, a margin per example, each measured and explained below.
"""

from __future__ import annotations

import json
import math
import struct
import subprocess
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from unittest import mock

import numpy as np

from helpers import HERE, NODE, SRC, audit_model, example, needs_app

from kompartment.engine.jacobian import Pattern
from kompartment.engine.project import Project
from kompartment.engine.runner import run as run_project
from kompartment.engine.solvers import SolverError
from kompartment.engine.solvers import julia as ported
from kompartment.engine.solvers.julia import _js, controller, linalg, methods, newton
from kompartment.engine.solvers.julia.adapter import _jacobian_for
from kompartment.engine.solvers.julia.integrator import ODEError, ODEProblem
from kompartment.engine.solvers.julia.integrator import solve as package_solve
from kompartment.engine.solvers.julia.jacobian import colour_columns
from kompartment.engine.solvers.julia.linalg import reverse_cuthill_mckee
from kompartment.engine.solvers.julia.methods import fbdf as fbdf_module
from kompartment.engine.solvers.julia.methods import qndf as qndf_module
from kompartment.engine.solvers.julia.methods import radau as radau_module
from kompartment.engine.solvers.julia.methods import tableaus

SOLVERS = ('fbdf', 'qndf', 'rodas5p', 'radau5', 'kencarp4', 'trbdf2')
# The six that came with the default algorithm (2026-10-03): the switching
# solvers -- this tool's, which hands the stiff part to the NDF, and
# DifferentialEquations.jl's own -- the matrix-free FBDF, and the three
# methods the second switches between.
NEW = ('auto', 'auto_julia', 'fbdf_krylov', 'rosenbrock23', 'tsit5', 'vern7')
EVERY = SOLVERS + NEW
# Held to the edge of their stability on a stiff problem.
EXPLICIT = ('tsit5', 'vern7')
STIFF = SOLVERS + ('auto', 'auto_julia', 'fbdf_krylov', 'rosenbrock23')
# The ones a matrix or a Jacobian setting means anything to.
MATRIX = SOLVERS + ('auto', 'auto_julia', 'rosenbrock23')
# Too stiff for an explicit method: Robertson it cannot cross in any number of
# steps worth taking, and on HIRES it runs at the edge of its stability, where
# whether a step is rejected is decided in the last bits (Vern7: 2 rejections
# in 7540 steps here against 5 in the application, the same run bit for bit
# with V8's pow).
TOO_STIFF = ('robertson', 'hires')
COUNTS = ('nsteps', 'nfailed', 'nfevals', 'npds', 'ndecomps', 'nsolves')

# The application's option names, as the bridge takes them, and this engine's.
OPTION_NAMES = {
    'rtol': 'rtol', 'abstol': 'abstol', 'hmax': 'hmax', 'h0': 'h0', 'maxSteps': 'max_steps',
    'maxOrder': 'max_order', 'minOrder': 'min_order', 'bdf': 'bdf', 'errorNorm': 'error_norm',
    'newtonKappa': 'newton_kappa', 'maxJacAge': 'max_jac_age', 'belowTolRun': 'below_tol_run',
    'matrix': 'matrix', 'autoUpdateAbsTol': 'auto_abstol', 'nonNegative': 'non_negative',
    'endsOnly': 'ends_only',
}


# --- talking to the application ----------------------------------------------------------

def _encode(x: Any) -> Any:
    if isinstance(x, float) and not math.isfinite(x):
        return 'NaN' if x != x else ('Infinity' if x > 0 else '-Infinity')
    if isinstance(x, dict):
        return {k: _encode(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_encode(v) for v in x]
    return x


def _decode(x: Any) -> Any:
    if isinstance(x, str) and x in ('NaN', 'Infinity', '-Infinity'):
        return {'NaN': math.nan, 'Infinity': math.inf, '-Infinity': -math.inf}[x]
    if isinstance(x, dict):
        return {k: _decode(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_decode(v) for v in x]
    return x


def bridge(task: str, **request: Any) -> Dict[str, Any]:
    """Asks the application's solvers (see tests/node/julia_solvers.mjs)."""
    assert NODE is not None
    proc = subprocess.run([NODE, str(HERE / 'node' / 'julia_solvers.mjs'), str(SRC)],
                          input=json.dumps(_encode({'task': task, **request})), capture_output=True, text=True,
                          timeout=900, encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return _decode(json.loads(proc.stdout))


def engine(task: str, **request: Any) -> Dict[str, Any]:
    """Asks the application's engine (see tests/node/engine.mjs)."""
    assert NODE is not None
    proc = subprocess.run([NODE, str(HERE / 'node' / 'engine.mjs'), str(SRC)],
                          input=json.dumps(_encode({'task': task, **request})), capture_output=True, text=True,
                          timeout=900, encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return _decode(json.loads(proc.stdout))


# --- the problems, mirrored from the bridge -----------------------------------------------

_PROBLEMS: Optional[Dict[str, Any]] = None


def problems() -> Dict[str, Any]:
    """Each problem's n, y0, grid, CSC pattern (and the chain's rates, which are
    V8's ``10 ** (-i / 4)`` and so are read rather than recomputed)."""
    global _PROBLEMS
    if _PROBLEMS is None:
        _PROBLEMS = bridge('problems')
    return _PROBLEMS


def functions(name: str) -> Tuple[Callable[[float, np.ndarray], np.ndarray], Callable[[float, np.ndarray], np.ndarray]]:
    """``f`` and the dense Jacobian, written as the bridge writes them."""
    info = problems()[name]
    n = info['n']
    if name == 'robertson':
        def f(t: float, y: np.ndarray) -> np.ndarray:
            d = np.empty(3)
            d[0] = -0.04 * y[0] + 1e4 * y[1] * y[2]
            d[1] = 0.04 * y[0] - 1e4 * y[1] * y[2] - 3e7 * y[1] * y[1]
            d[2] = 3e7 * y[1] * y[1]
            return d

        def jac(t: float, y: np.ndarray) -> np.ndarray:
            return np.array([[-0.04, 1e4 * y[2], 1e4 * y[1]],
                             [0.04, -1e4 * y[2] - 6e7 * y[1], -1e4 * y[1]],
                             [0.0, 6e7 * y[1], 0.0]])
    elif name in ('chain', 'nonneg'):
        k = info['rates']

        def f(t: float, y: np.ndarray) -> np.ndarray:
            d = np.empty(n)
            d[0] = -k[0] * y[0]
            for i in range(1, n):
                d[i] = k[i - 1] * y[i - 1] - k[i] * y[i]
            return d

        def jac(t: float, y: np.ndarray) -> np.ndarray:
            m = np.zeros((n, n))
            for c in range(n):
                m[c, c] = -k[c]
                if c + 1 < n:
                    m[c + 1, c] = k[c]
            return m
    elif name == 'vdp':
        mu = 10

        def f(t: float, y: np.ndarray) -> np.ndarray:
            return np.array([y[1], mu * (1 - y[0] * y[0]) * y[1] - y[0]])

        def jac(t: float, y: np.ndarray) -> np.ndarray:
            return np.array([[0.0, 1.0], [-2 * mu * y[0] * y[1] - 1, mu * (1 - y[0] * y[0])]])
    elif name == 'hires':
        def f(t: float, y: np.ndarray) -> np.ndarray:
            d = np.empty(8)
            d[0] = -1.71 * y[0] + 0.43 * y[1] + 8.32 * y[2] + 0.0007
            d[1] = 1.71 * y[0] - 8.75 * y[1]
            d[2] = -10.03 * y[2] + 0.43 * y[3] + 0.035 * y[4]
            d[3] = 8.32 * y[1] + 1.71 * y[2] - 1.12 * y[3]
            d[4] = -1.745 * y[4] + 0.43 * y[5] + 0.43 * y[6]
            d[5] = -280 * y[5] * y[7] + 0.69 * y[3] + 1.71 * y[4] - 0.43 * y[5] + 0.69 * y[6]
            d[6] = 280 * y[5] * y[7] - 1.81 * y[6]
            d[7] = -280 * y[5] * y[7] + 1.81 * y[6]
            return d

        def jac(t: float, y: np.ndarray) -> np.ndarray:
            return np.array([
                [-1.71, 0.43, 8.32, 0, 0, 0, 0, 0],
                [1.71, -8.75, 0, 0, 0, 0, 0, 0],
                [0, 0, -10.03, 0.43, 0.035, 0, 0, 0],
                [0, 8.32, 1.71, -1.12, 0, 0, 0, 0],
                [0, 0, 0, 0, -1.745, 0.43, 0.43, 0],
                [0, 0, 0, 0.69, 1.71, -280 * y[7] - 0.43, 0.69, -280 * y[5]],
                [0, 0, 0, 0, 0, 280 * y[7], -1.81, 280 * y[5]],
                [0, 0, 0, 0, 0, -280 * y[7], 1.81, -280 * y[5]]], dtype=float)
    elif name in ('event', 'two_events', 'event_rising'):
        def f(t: float, y: np.ndarray) -> np.ndarray:
            return np.array([-y[0], y[0] - 0.1 * y[1]])

        def jac(t: float, y: np.ndarray) -> np.ndarray:
            return np.array([[-1.0, 0.0], [1.0, -0.1]])
    elif name == 'forced':
        def f(t: float, y: np.ndarray) -> np.ndarray:
            return np.array([-50 * (y[0] - t / (1 + 0.1 * t * t))])

        def jac(t: float, y: np.ndarray) -> np.ndarray:
            return np.array([[-50.0]])
    elif name == 'jump':
        def f(t: float, y: np.ndarray) -> np.ndarray:
            return np.array([-1e-4 * y[0], 1e-4 * y[0] - 0.01 * y[1],
                             0.01 * y[1] - 1e-3 * y[2], 1e-3 * y[2]])

        def jac(t: float, y: np.ndarray) -> np.ndarray:
            return np.array([[-1e-4, 0, 0, 0], [1e-4, -0.01, 0, 0],
                             [0, 0.01, -1e-3, 0], [0, 0, 1e-3, 0]], dtype=float)
    elif name == 'vdp1000':
        def f(t: float, y: np.ndarray) -> np.ndarray:
            return np.array([y[1], 1000 * ((1 - y[0] * y[0]) * y[1]) - y[0]])

        def jac(t: float, y: np.ndarray) -> np.ndarray:
            return np.array([[0.0, 1.0], [-2000 * y[0] * y[1] - 1, 1000 * (1 - y[0] * y[0])]])
    elif name == 'kepler':
        def f(t: float, y: np.ndarray) -> np.ndarray:
            r2 = y[0] * y[0] + y[1] * y[1]
            r3 = r2 * math.sqrt(r2)
            return np.array([y[2], y[3], -y[0] / r3, -y[1] / r3])

        def jac(t: float, y: np.ndarray) -> np.ndarray:
            r2 = y[0] * y[0] + y[1] * y[1]
            r = math.sqrt(r2)
            r3 = r2 * r
            r5 = r3 * r2
            return np.array([[0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0],
                             [-1 / r3 + 3 * y[0] * y[0] / r5, 3 * y[0] * y[1] / r5, 0.0, 0.0],
                             [3 * y[0] * y[1] / r5, -1 / r3 + 3 * y[1] * y[1] / r5, 0.0, 0.0]])
    elif name == 'idle':
        def f(t: float, y: np.ndarray) -> np.ndarray:
            return np.array([y[1], -y[0], 0.0])

        def jac(t: float, y: np.ndarray) -> np.ndarray:
            return np.array([[0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
    elif name == 'heat':
        dx = 1 / (n + 1)
        c = 1 / (dx * dx)

        def f(t: float, y: np.ndarray) -> np.ndarray:
            left = np.concatenate([[0.0], y[:-1]])
            right = np.concatenate([y[1:], [0.0]])
            return (left - 2 * y + right) / (dx * dx)

        def jac(t: float, y: np.ndarray) -> np.ndarray:
            return np.diag(np.full(n, -2 * c)) + np.diag(np.full(n - 1, c), 1) + np.diag(np.full(n - 1, c), -1)
    elif name in ('chain120', 'long_chain'):
        k = np.array(info['rates'], dtype=float)

        def f(t: float, y: np.ndarray) -> np.ndarray:
            d = np.empty(n)
            d[0] = -k[0] * y[0]
            d[1:] = k[:-1] * y[:-1] - k[1:] * y[1:]
            return d

        def jac(t: float, y: np.ndarray) -> np.ndarray:
            return np.diag(-k) + np.diag(k[:-1], -1)
    else:
        raise KeyError(name)
    return f, jac


def events_for(name: str) -> Any:
    if name == 'event':
        return SimpleNamespace(n=1, direction=np.array([-1], dtype=np.int8),
                               fun=lambda t, y: np.array([y[0] - 0.25]))
    if name == 'two_events':
        return SimpleNamespace(n=2, direction=np.array([-1, 1], dtype=np.int8),
                               fun=lambda t, y: np.array([y[0] - 0.25, t - 0.5]))
    if name == 'event_rising':
        return SimpleNamespace(n=1, direction=np.array([0], dtype=np.int8),
                               fun=lambda t, y: np.array([y[1] - 0.3]))
    return None


def corners_of(times: List[float]) -> Callable[..., Optional[List[float]]]:
    """``table_corners`` over a list of times, as the bridge's ``cornersOf``:
    those strictly inside the span, or None past the limit."""
    def corners(frm: float, to: float, limit: float = math.inf) -> Optional[List[float]]:
        lo, hi = min(frm, to), max(frm, to)
        inside = [float(c) for c in times if lo < c < hi]
        return None if len(inside) > limit else inside
    return corners


def run_here(name: str, solver: str, opts: Dict[str, Any]) -> Dict[str, Any]:
    """One run through the port, in the bridge's request shape and answer shape."""
    info = problems()[name]
    n = info['n']
    f, jac = functions(name)
    o = dict(opts)
    how = o.pop('jacobian', 'analytic')
    abort_after = o.pop('abortAfter', None)
    collect = o.pop('collect', True)
    grid = o.pop('grid', info['grid'])
    corners = o.pop('corners', None)
    col_ptr = np.array(info['colPtr'], dtype=np.int64)
    rows = np.array(info['rowIdx'], dtype=np.int64)
    pattern = Pattern(n, rows, np.repeat(np.arange(n), np.diff(col_ptr)))
    jacobian = None
    if how == 'declined':
        jacobian = {'pattern': pattern, 'available': True, 'evaluate': lambda t, y: None}
    elif how == 'analytic':
        jacobian = {'pattern': pattern, 'available': True,
                    'evaluate': lambda t, y: jac(t, y)[pattern.row_idx, pattern.col_of]}
    here = {OPTION_NAMES[k]: v for k, v in o.items()}
    if isinstance(here.get('abstol'), list):
        here['abstol'] = np.array(here['abstol'], dtype=float)
    here['jacobian'] = jacobian
    if 'non_negative' not in here and info['nonNegative'] is not None:
        here['non_negative'] = info['nonNegative']
    here['events'] = events_for(name)
    if corners is not None:
        here['table_corners'] = corners_of(corners)
    accepted: List[float] = []
    calls = [0]
    if collect:
        here['on_accepted'] = lambda t, y: accepted.append(float(t))
    if abort_after is not None:
        def on_step(fraction: float, nsteps: int, t: float) -> bool:
            calls[0] += 1
            return calls[0] < abort_after
        here['on_step'] = on_step
    try:
        r = getattr(ported, solver)(f, np.array(grid, dtype=float), np.array(info['y0'], dtype=float), here)
    except SolverError as e:
        return {'error': str(e), 'code': e.code, 't': e.t, 'accepted': accepted, 'calls': calls[0]}
    stopped = r['stopped']
    return {'t': [float(v) for v in r['t']], 'y': [row.tolist() for row in r['y']], 'stats': r['stats'],
            'stopped': ({'t': stopped['t'], 'y': stopped['y'].tolist(), 'which': list(stopped['which'])}
                        if stopped else None),
            'accepted': accepted, 'calls': calls[0]}


# The package's algorithms by the bridge's names (``MAKE`` in julia_solvers.mjs),
# and the package's options in the port's spelling.
PACKAGE_ALGORITHMS: Dict[str, Callable[..., Any]] = {
    'Tsit5': methods.Tsit5, 'Vern7': methods.Vern7, 'Rosenbrock23': methods.Rosenbrock23,
    'Rodas5P': methods.Rodas5P, 'FBDF': methods.FBDF, 'DefaultODEAlgorithm': methods.DefaultODEAlgorithm,
    'DefaultImplicitODEAlgorithm': methods.DefaultImplicitODEAlgorithm,
    'AutoTsit5Rodas5P': lambda **o: methods.AutoAlgSwitch(methods.Tsit5(), methods.Rodas5P(), **o),
}
PACKAGE_NAMES = {'saveEverystep': 'save_everystep', 'nonNegative': 'non_negative', 'stillIsStiff': 'still_is_stiff',
                 'handOff': 'hand_off',
                 'firstPredictor': 'first_predictor', 'maxOrder': 'max_order', 'minOrder': 'min_order',
                 'autoAbstol': 'auto_abstol', 'belowTolRun': 'below_tol_run', 'maxSteps': 'max_steps'}


def run_package(name: str, alg: str, alg_options: Optional[Dict[str, Any]] = None,
                opts: Optional[Dict[str, Any]] = None, jacobian: bool = True) -> Dict[str, Any]:
    """The package's own solve with one of its algorithms, as the bridge's
    ``package`` task runs it: t, u, stats (the package's), retcode, message
    and the method of every saved row."""
    info = problems()[name]
    n = info['n']
    f, jac = functions(name)
    col_ptr = np.array(info['colPtr'], dtype=np.int64)
    rows = np.array(info['rowIdx'], dtype=np.int64)
    pattern = Pattern(n, rows, np.repeat(np.arange(n), np.diff(col_ptr)))
    handed = (_jacobian_for({'pattern': pattern,
                             'evaluate': lambda t, y: jac(t, y)[pattern.row_idx, pattern.col_of]})
              if jacobian else None)
    problem = ODEProblem(f, np.array(info['y0'], dtype=float), (info['grid'][0], info['grid'][-1]), jac=handed,
                         jac_pattern=(col_ptr, rows))
    made = PACKAGE_ALGORITHMS[alg](**{PACKAGE_NAMES.get(k, k): v for k, v in (alg_options or {}).items()})
    settings = {PACKAGE_NAMES.get(k, k): v for k, v in (opts or {}).items()}
    try:
        with np.errstate(all='ignore'):
            sol = package_solve(problem, made, settings)
    except ODEError as e:
        return {'error': str(e)}
    handed = sol.hand_off
    return {'t': [float(v) for v in sol.t], 'u': [row.tolist() for row in sol.u], 'stats': sol.stats,
            'retcode': sol.retcode, 'message': sol.message,
            'algChoice': None if sol.alg_choice is None else sol.alg_choice.tolist(),
            'handOff': None if handed is None else {**handed, 'u': handed['u'].tolist()}}


def within(mine: float, theirs: float, share: float, least: float) -> bool:
    return abs(mine - theirs) <= max(least, share * abs(theirs))


# The matrix-free FBDF's work is GMRES's iterations, one f each, and how many a
# solve takes turns on whether a residual falls under its threshold: a step
# size a last bit apart moves that by an iteration here and there while the
# steps stay the same. Measured on the problems: the same steps, f evaluations
# up to 3.5 % apart and GMRES iterations up to 5.3 % (two_events: 419 f
# against 434, 143 iterations against 151), every one of them the
# application's run bit for bit with V8's pow.
GMRES_SHARE = 0.05
GMRES_ITERATIONS_SHARE = 0.1


def counts_agree(mine: Dict[str, Any], theirs: Dict[str, Any]) -> List[str]:
    """What is outside the margin: steps within max(2, 1 %), and every other
    count within the same share or two steps' worth of it -- f evaluations of
    a run that solved by GMRES within GMRES_SHARE, and its iterations too."""
    bad = []
    steps = theirs['nsteps'] or 1
    gmres = theirs.get('krylovIters') is not None
    for key in COUNTS:
        a, b = mine[key], theirs[key]
        per_step = abs(b) / steps
        least = 2 if key == 'nsteps' else 2 * max(1.0, per_step)
        share = GMRES_SHARE if (gmres and key == 'nfevals') else 0.01
        if not within(a, b, share, least):
            bad.append(f'{key} {a} against {b}')
    if gmres and not within(mine.get('krylov_iters') or 0, theirs['krylovIters'], GMRES_ITERATIONS_SHARE, 2):
        bad.append(f"GMRES iterations {mine.get('krylov_iters')} against {theirs['krylovIters']}")
    return bad


def worst_relative(mine: List[List[float]], theirs: List[List[float]]) -> float:
    """The largest difference, per component relative to that component's
    largest magnitude in the application's rows."""
    a = np.array(mine, dtype=float)
    b = np.array(theirs, dtype=float)
    if a.shape != b.shape:
        return math.inf
    scale = np.max(np.abs(b), axis=0)
    scale[scale == 0] = 1.0
    return float(np.max(np.abs(a - b) / scale)) if a.size else 0.0


# --- the package's own LU and V8's pow, for BitIdentity -----------------------------------

class PackageDenseLU:
    """``DenseLU`` and ``ComplexDenseLU`` of ``src/ode/julia/core/linalg.js``,
    operation for operation (right-looking, first largest pivot, whole-row
    interchanges, the complex reciprocal by the scaled form). A test fixture:
    the port itself factorises with LAPACK, as it is meant to."""

    def factor(self, a: np.ndarray) -> bool:
        a = np.array(a)
        n = a.shape[0]
        piv = np.zeros(n, dtype=np.int64)
        cplx = np.iscomplexobj(a)
        for k in range(n):
            col = a[k:, k]
            mag = np.abs(col.real) + np.abs(col.imag) if cplx else np.abs(col)
            big = mag[0]
            p = k
            for i in range(1, mag.size):
                if mag[i] > big:
                    big = mag[i]
                    p = k + i
            piv[k] = p
            if big == 0:
                return False
            if p != k:
                a[[k, p], :] = a[[p, k], :]
            if cplx:
                dr, di = a[k, k].real, a[k, k].imag
                if abs(dr) >= abs(di):
                    r = di / dr
                    den = dr + di * r
                    inv_r, inv_i = 1 / den, -r / den
                else:
                    r = dr / di
                    den = dr * r + di
                    inv_r, inv_i = r / den, -1 / den
                ar = a[k + 1:, k].real.copy()
                ai = a[k + 1:, k].imag.copy()
                a[k + 1:, k] = (ar * inv_r - ai * inv_i) + 1j * (ar * inv_i + ai * inv_r)
                for j in range(k + 1, n):
                    br, bi = a[k, j].real, a[k, j].imag
                    if br == 0 and bi == 0:
                        continue
                    lr = a[k + 1:, k].real
                    li = a[k + 1:, k].imag
                    a[k + 1:, j] = (a[k + 1:, j].real - (lr * br - li * bi)) \
                        + 1j * (a[k + 1:, j].imag - (lr * bi + li * br))
            else:
                a[k + 1:, k] *= 1 / a[k, k]
                nz = np.nonzero(a[k, k + 1:] != 0)[0] + k + 1
                if nz.size:
                    a[k + 1:, nz] -= np.outer(a[k + 1:, k], a[k, nz])
        self._pkg = (a, piv, cplx)
        return True

    def solve(self, b: np.ndarray) -> np.ndarray:
        a, piv, cplx = self._pkg
        n = a.shape[0]
        if cplx:
            br = np.array(b.real, dtype=float)
            bi = np.array(b.imag, dtype=float)
            for k in range(n):
                p = piv[k]
                if p != k:
                    br[k], br[p] = br[p], br[k]
                    bi[k], bi[p] = bi[p], bi[k]
            for k in range(n):
                xr, xi = br[k], bi[k]
                if xr == 0 and xi == 0:
                    continue
                ar = a[k + 1:, k].real
                ai = a[k + 1:, k].imag
                br[k + 1:] -= ar * xr - ai * xi
                bi[k + 1:] -= ar * xi + ai * xr
            for k in range(n - 1, -1, -1):
                dr, di = a[k, k].real, a[k, k].imag
                xr, xi = br[k], bi[k]
                if abs(dr) >= abs(di):
                    r = di / dr
                    den = dr + di * r
                    qr, qi = (xr + xi * r) / den, (xi - xr * r) / den
                else:
                    r = dr / di
                    den = dr * r + di
                    qr, qi = (xr * r + xi) / den, (xi * r - xr) / den
                br[k], bi[k] = qr, qi
                if qr == 0 and qi == 0:
                    continue
                ar = a[:k, k].real
                ai = a[:k, k].imag
                br[:k] -= ar * qr - ai * qi
                bi[:k] -= ar * qi + ai * qr
            out = np.empty(n, dtype=complex)
            out.real = br
            out.imag = bi
            return out
        x = np.array(b, dtype=float)
        for k in range(n):
            p = piv[k]
            if p != k:
                x[k], x[p] = x[p], x[k]
        for k in range(n):
            bk = x[k]
            if bk != 0:
                x[k + 1:] -= a[k + 1:, k] * bk
        for k in range(n - 1, -1, -1):
            x[k] /= a[k, k]
            bk = x[k]
            if bk != 0:
                x[:k] -= a[:k, k] * bk
        return x


_V8_POW: Dict[Tuple[bytes, bytes], float] = {}


def _key(x: float, y: float) -> Tuple[bytes, bytes]:
    return struct.pack('<d', float(x)), struct.pack('<d', float(y))


def _package_patches(pow_fn: Callable[[float, float], float]) -> List[Any]:
    """The pow given in every module that takes one, and the package's dense LU."""
    patches = [mock.patch.object(m, 'jpow', pow_fn)
               for m in (_js, controller, newton, fbdf_module, qndf_module, radau_module)]
    patches += [mock.patch.object(linalg.DenseLU, 'factor', PackageDenseLU.factor),
                mock.patch.object(linalg.DenseLU, 'solve', PackageDenseLU.solve)]
    return patches


@contextmanager
def as_the_package_computes() -> Iterator[Dict[Tuple[bytes, bytes], Tuple[float, float]]]:
    """The package's dense LU, and V8's pow wherever it is known; the
    arguments whose V8 value is not yet known are collected."""
    missing: Dict[Tuple[bytes, bytes], Tuple[float, float]] = {}
    platform_pow = _js.jpow

    def v8_pow(x: float, y: float) -> float:
        k = _key(x, y)
        if k in _V8_POW:
            return _V8_POW[k]
        missing[k] = (float(x), float(y))
        return platform_pow(x, y)

    patches = _package_patches(v8_pow)
    for p in patches:
        p.start()
    try:
        yield missing
    finally:
        for p in reversed(patches):
            p.stop()


@contextmanager
def asking_v8_at_every_call() -> Iterator[None]:
    """The package's dense LU, and V8's pow asked of a Node process
    (tests/node/v8_pow.mjs) at every call it has not answered before: one
    pass however long the run, where until_known can need a round for each
    argument on which V8's pow and the platform's differ (1249 along the
    9751 steps of the chain of 120 at reltol 1e-6)."""
    assert NODE is not None
    oracle = subprocess.Popen([NODE, str(HERE / 'node' / 'v8_pow.mjs')],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    assert oracle.stdin is not None and oracle.stdout is not None
    ask, answer = oracle.stdin, oracle.stdout

    def v8_pow(x: float, y: float) -> float:
        k = _key(x, y)
        v = _V8_POW.get(k)
        if v is None:
            ask.write(k[0].hex().encode() + b' ' + k[1].hex().encode() + b'\n')
            ask.flush()
            v = _V8_POW[k] = struct.unpack('<d', bytes.fromhex(answer.readline().decode().strip()))[0]
        return v

    patches = _package_patches(v8_pow)
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in reversed(patches):
            p.stop()
        ask.close()
        oracle.wait(timeout=60)
        answer.close()


def until_known(attempts: List[Callable[[], Any]], passes: int = 400) -> List[Any]:
    """Runs each attempt as the package computes, asking V8 for the pow values
    they met and did not know -- all of them at once, one question a round --
    until every attempt runs through meeting none. Each round moves the first
    difference further along a run, so a run of a thousand steps takes a few
    dozen rounds."""
    results: List[Any] = [None] * len(attempts)
    pending = list(range(len(attempts)))
    for _ in range(passes):
        wanted: Dict[Tuple[bytes, bytes], Tuple[float, float]] = {}
        still = []
        for i in pending:
            with as_the_package_computes() as missing:
                results[i] = attempts[i]()
            if missing:
                wanted.update(missing)
                still.append(i)
        if not still:
            return results
        pairs = list(wanted.values())
        values = bridge('pow', pairs=[list(p) for p in pairs])['values']
        for (x, y), v in zip(pairs, values):
            _V8_POW[_key(x, y)] = float(v)
        pending = still
    raise AssertionError(f'still meeting new pow arguments after {passes} rounds')


# --- the tests ------------------------------------------------------------------------------

BASE = {
    'robertson': {'rtol': 1e-6, 'abstol': 1e-10},
    'chain': {'rtol': 1e-6, 'abstol': 1e-12},
    'vdp': {'rtol': 1e-6, 'abstol': 1e-8},
    'hires': {'rtol': 1e-6, 'abstol': 1e-10},
    'event': {'rtol': 1e-7, 'abstol': 1e-10},
    'two_events': {'rtol': 1e-7, 'abstol': 1e-10},
    'event_rising': {'rtol': 1e-7, 'abstol': 1e-10},
    'nonneg': {'rtol': 1e-3, 'abstol': 1e-6},
    'forced': {'rtol': 1e-6, 'abstol': 1e-9},
    'jump': {'rtol': 1e-6, 'abstol': 1e-6},
}

NEWTON = ('fbdf', 'qndf', 'radau5', 'kencarp4', 'trbdf2')


def _runs() -> List[Tuple[str, str, Dict[str, Any]]]:
    """Every problem with every method -- the explicit ones not where they
    cannot get through -- then the options the adapter maps, each with the
    methods that read it."""
    runs = [(name, s, dict(opts)) for name, opts in BASE.items() for s in EVERY
            if not (s in EXPLICIT and name in TOO_STIFF)]
    rob = BASE['robertson']
    variants: List[Tuple[str, Tuple[str, ...], Dict[str, Any]]] = [
        ('robertson', STIFF, {**rob, 'errorNorm': 'max'}),
        ('vdp', EXPLICIT, {**BASE['vdp'], 'errorNorm': 'max'}),
        ('robertson', STIFF, {'rtol': 1e-5, 'abstol': [1e-8, 1e-12, 1e-8]}),
        ('hires', STIFF, {**BASE['hires'], 'autoUpdateAbsTol': True}),
        ('chain', EXPLICIT, {**BASE['chain'], 'autoUpdateAbsTol': True}),
        ('chain', MATRIX, {**BASE['chain'], 'matrix': 'dense'}),
        ('hires', MATRIX, {**BASE['hires'], 'matrix': 'sparse'}),
        ('hires', MATRIX, {**BASE['hires'], 'matrix': 'refactor'}),
        ('chain', MATRIX, {**BASE['chain'], 'jacobian': 'none'}),
        ('chain', MATRIX, {**BASE['chain'], 'jacobian': 'declined'}),
        ('vdp', MATRIX, {**BASE['vdp'], 'jacobian': 'none'}),
        ('vdp', EVERY, {**BASE['vdp'], 'hmax': 0.05}),
        ('robertson', STIFF, {**rob, 'h0': 1e-5}),
        ('robertson', ('fbdf', 'qndf', 'fbdf_krylov', 'auto', 'auto_julia'), {**rob, 'maxOrder': 3}),
        ('robertson', ('fbdf', 'qndf', 'fbdf_krylov'), {**rob, 'minOrder': 2, 'maxOrder': 4.0}),
        ('robertson', ('qndf', 'fbdf'), {**rob, 'bdf': True}),
        # The NDF `auto` hands a run to, with its BDF switch on. (Not on
        # Robertson, where plain BDF is round-off chaotic: rtol nudged by 1e-9
        # relative takes the application's run from 424 to 478 steps.)
        ('chain', ('auto',), {**BASE['chain'], 'bdf': True}),
        ('vdp', ('auto',), {**BASE['vdp'], 'bdf': True}),
        ('hires', NEWTON + ('fbdf_krylov',), {**BASE['hires'], 'newtonKappa': 1e-2}),
        ('hires', NEWTON, {**BASE['hires'], 'maxJacAge': 5}),
        ('robertson', STIFF, {**rob, 'belowTolRun': 3}),
        ('robertson', STIFF, {**rob, 'endsOnly': True}),
        ('event', EVERY, {**BASE['event'], 'endsOnly': True}),
        ('robertson', EVERY, {**rob, 'maxSteps': 40}),
        ('hires', EVERY, {**BASE['hires'], 'abortAfter': 7}),
        ('robertson', ('rodas5p', 'fbdf', 'auto'), {**rob, 'grid': [0.5, 0.5]}),
        # `auto` handed the corners of a model's clock-read tables: three to
        # land on, through an event, and more than it lands on (the NDF's
        # run from the start).
        ('forced', ('auto',), {**BASE['forced'], 'corners': [2.5, 5.0, 7.5]}),
        ('event', ('auto',), {**BASE['event'], 'corners': [0.3, 0.7, 2.0]}),
        ('vdp', ('auto',), {**BASE['vdp'], 'corners': [0.2 * i for i in range(1, 150)]}),
    ]
    for name, solvers, opts in variants:
        runs += [(name, s, dict(opts)) for s in solvers]
    return runs


def _as_floats(x: Any) -> Any:
    if isinstance(x, (list, tuple)):
        return [_as_floats(v) for v in x]
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    return x


def _number_free(message: str) -> Tuple[str, List[float]]:
    """A message with its numbers taken out, and the numbers."""
    import re
    pattern = re.compile(r'-?\d+(?:\.\d+)?(?:e[+-]?\d+)?')
    return pattern.sub('#', message), [float(v) for v in pattern.findall(message)]


@needs_app
class Tables(unittest.TestCase):
    def test_the_tableaux_are_the_packages(self) -> None:
        js = bridge('tableaus')
        mine = {'rodas5p': tableaus.RODAS5P, 'radau5': tableaus.RADAU_IIA5,
                'trbdf2': tableaus.TRBDF2, 'kencarp4': tableaus.KENCARP4,
                'tsit5': tableaus.TSIT5, 'vern7': tableaus.VERN7}
        self.assertEqual(sorted(js), sorted(mine))
        snake = {'errorOrder': 'error_order', 'interpOrder': 'interp_order', 'stabilitySize': 'stability_size',
                 'extraC': 'extra_c', 'extraA': 'extra_a', 'interpStages': 'interp_stages'}
        for key, table in js.items():
            for field, value in table.items():
                if field == 'stifflyAccurate':
                    continue
                with self.subTest(tableau=key, field=field):
                    here = getattr(mine[key], snake.get(field, field))
                    # == on floats: the same double or it fails (JSON writes the
                    # application's 1 where Python has 1.0; the value is what counts).
                    self.assertEqual(_as_floats(here), _as_floats(value))

    def test_orderings_and_colourings_are_the_packages(self) -> None:
        rng = np.random.default_rng(20260925)
        patterns = []
        for n, density in ((1, 1.0), (2, 0.5), (7, 0.3), (12, 0.15), (30, 0.08), (60, 0.03), (90, 0.2)):
            full = rng.random((n, n)) < density
            np.fill_diagonal(full, rng.random(n) < 0.7)
            patterns.append(full)
        # A connected block followed by isolated vertices: what the package's
        # reverseCuthillMcKee got wrong before 2026-09-25 (it skipped vertices).
        block = np.zeros((10, 10), dtype=bool)
        block[:4, :4] = True
        patterns.append(block)
        patterns.append(np.ones((6, 6), dtype=bool))
        patterns.append(np.eye(5, dtype=bool))
        for name in ('robertson', 'chain', 'hires', 'vdp'):
            info = problems()[name]
            m = np.zeros((info['n'], info['n']), dtype=bool)
            cp = info['colPtr']
            for j in range(info['n']):
                m[info['rowIdx'][cp[j]:cp[j + 1]], j] = True
            patterns.append(m)
        csc = []
        for m in patterns:
            rows, cols = np.nonzero(m)
            order = np.lexsort((rows, cols))
            col_ptr = np.zeros(m.shape[0] + 1, dtype=np.int64)
            np.cumsum(np.bincount(cols, minlength=m.shape[0]), out=col_ptr[1:])
            csc.append((m.shape[0], col_ptr, rows[order]))
        js = bridge('orderings', patterns=[{'n': n, 'colPtr': cp.tolist(), 'rowIdx': ri.tolist()}
                                           for n, cp, ri in csc])['results']
        for (n, cp, ri), theirs in zip(csc, js):
            with self.subTest(n=n, nnz=int(cp[-1])):
                self.assertEqual(reverse_cuthill_mckee(n, cp, ri).tolist(), theirs['rcm'])
                self.assertEqual(sorted(reverse_cuthill_mckee(n, cp, ri).tolist()), list(range(n)))
                self.assertEqual([g.tolist() for g in colour_columns(n, cp, ri)], theirs['groups'])


@needs_app
class Problems(unittest.TestCase):
    runs: List[Tuple[str, str, Dict[str, Any]]] = []
    theirs: List[Dict[str, Any]] = []
    mine: List[Dict[str, Any]] = []

    @classmethod
    def setUpClass(cls) -> None:
        cls.runs = _runs()
        cls.theirs = bridge('solve', runs=[{'problem': n, 'solver': s, 'opts': o} for n, s, o in cls.runs])['runs']
        cls.mine = [run_here(n, s, o) for n, s, o in cls.runs]

    def pairs(self) -> Iterator[Tuple[str, str, Dict[str, Any], Dict[str, Any], Dict[str, Any]]]:
        for (name, solver, opts), theirs, mine in zip(self.runs, self.theirs, self.mine):
            yield name, solver, opts, theirs, mine

    def test_every_count_is_the_applications(self) -> None:
        exact = total = 0
        for name, solver, opts, theirs, mine in self.pairs():
            if 'error' in theirs or 'error' in mine:
                continue
            with self.subTest(problem=name, solver=solver, opts=opts):
                total += 1
                self.assertEqual(mine['stats']['solver'], theirs['stats']['solver'])
                self.assertEqual(mine['stats']['sparse'], theirs['stats']['sparse'])
                # The NDF that `auto` hands a run to factorises a sparse
                # matrix with SuperLU here and with the application's own LU
                # there, which fill in differently (hires sparse: 35 against 27).
                if 'NDF' in (mine['stats'].get('steps_by') or {}):
                    self.assertEqual(mine['stats']['fill'] is None, theirs['stats']['fill'] is None)
                else:
                    self.assertEqual(mine['stats']['fill'], theirs['stats']['fill'])
                self.assertEqual(counts_agree(mine['stats'], theirs['stats']), [])
                exact += all(mine['stats'][k] == theirs['stats'][k] for k in COUNTS)
        # The margin is for the runs a last-bit difference reaches (see the
        # module's docstring); most runs are the application's exactly -- 96 %
        # when this was written -- and a port that had drifted would not be.
        self.assertGreater(total, 150)
        self.assertGreaterEqual(exact / total, 0.85, f'{exact} of {total} runs have every count the same')

    def test_the_switch_and_gmres_give_the_applications_account(self) -> None:
        """The switching solver's steps by method and its switches, and the
        matrix-free FBDF's GMRES iterations, under this engine's names: the
        application's where the two took the same steps, and adding up
        either way."""
        switched = krylov = 0
        for name, solver, opts, theirs, mine in self.pairs():
            if 'error' in theirs or 'error' in mine:
                continue
            with self.subTest(problem=name, solver=solver, opts=opts):
                js, here = theirs['stats'], mine['stats']
                self.assertEqual('steps_by' in here, js.get('stepsBy') is not None)
                self.assertEqual('krylov_iters' in here, js.get('krylovIters') is not None)
                self.assertNotIn('stepsBy', here)
                if js.get('stepsBy') is not None:
                    switched += 1
                    self.assertIn(solver, ('auto', 'auto_julia'))
                    # Every accepted step is one method's.
                    self.assertEqual(sum(here['steps_by'].values()), here['nsteps'] - here['nfailed'])
                    self.assertEqual(list(here['steps_by']), list(js['stepsBy']))
                    if all(here[k] == js[k] for k in COUNTS):
                        self.assertEqual(here['steps_by'], js['stepsBy'])
                        self.assertEqual(here['switches'], js['switches'])
                if js.get('krylovIters') is not None:
                    krylov += 1
                    self.assertEqual(solver, 'fbdf_krylov')
                    self.assertEqual((here['npds'], here['ndecomps']), (0, 0))
        self.assertGreater(switched, 10)
        self.assertGreater(krylov, 10)

    def test_the_rows_are_the_applications(self) -> None:
        for name, solver, opts, theirs, mine in self.pairs():
            if 'error' in theirs or 'error' in mine:
                continue
            with self.subTest(problem=name, solver=solver, opts=opts):
                self.assertEqual(len(mine['t']), len(theirs['t']))
                if theirs['stopped'] is None:
                    self.assertEqual(mine['t'], theirs['t'])
                else:
                    self.assertEqual(mine['t'][:-1], theirs['t'][:-1])
                # The same method held to the same tolerance. With every count
                # the same, the two took the same steps and differ by rounding:
                # held to rtol (0.25 rtol at worst when written). Where the counts
                # part, they are two step sequences each carrying its own global
                # error -- on van der Pol at t = 30 that is 20 to 40 rtol for
                # Rodas5P and KenCarp4, measured against a reference -- and their
                # difference (4.9 rtol, Rodas5P, 529 steps against 530) is held
                # to 10 rtol.
                same = all(mine['stats'][k] == theirs['stats'][k] for k in COUNTS)
                bound = opts['rtol'] * (1 if same else 10)
                self.assertLess(worst_relative(mine['y'], theirs['y']), bound)

    def test_they_stop_where_the_application_stops(self) -> None:
        for name, solver, opts, theirs, mine in self.pairs():
            if 'error' in theirs or 'error' in mine:
                continue
            with self.subTest(problem=name, solver=solver, opts=opts):
                if theirs['stopped'] is None:
                    self.assertIsNone(mine['stopped'])
                    continue
                self.assertIsNotNone(mine['stopped'])
                self.assertEqual(mine['stopped']['which'], theirs['stopped']['which'])
                self.assertLess(abs(mine['stopped']['t'] - theirs['stopped']['t']), 10 * opts['rtol'])
                self.assertEqual(mine['t'][-1], mine['stopped']['t'])
        # And the stops are where the problem says: y = e^-t reaches 0.25 at ln 4.
        for name, solver, opts, theirs, mine in self.pairs():
            if name == 'event' and 'error' not in mine:
                # The two second-order methods are held to less: 5.4e-6 at
                # worst when written, Rosenbrock23's.
                tol = 1e-4 if solver == 'trbdf2' else 1e-5 if solver == 'rosenbrock23' else 1e-6
                self.assertLess(abs(mine['stopped']['t'] - math.log(4)), tol, solver)

    def test_the_earlier_of_two_events_stops_the_run(self) -> None:
        """Two event functions with a direction each: y falls through 0.25 at
        ln 4, the clock rises through 0.5 first, and that one stops the run."""
        seen = 0
        for name, solver, opts, theirs, mine in self.pairs():
            if name != 'two_events' or 'error' in mine:
                continue
            seen += 1
            with self.subTest(solver=solver, opts=opts):
                self.assertEqual(theirs['stopped']['which'], [1])
                self.assertEqual(mine['stopped']['which'], [1])
                self.assertLess(abs(mine['stopped']['t'] - 0.5), 1e-9)
        self.assertGreaterEqual(seen, 6)

    def test_a_late_start_after_a_jump_runs_to_the_end(self) -> None:
        """The chain restarted at t = 5000.123456789, one member rising from
        zero at 1e10 a unit of time: every method runs to the end, here and in
        the application, and to the closed form. FBDF stopped on its first step
        (it predicted no change, so its error estimate was h f) or a few steps
        later (its history's times were the clock's rounded readings)."""
        info = problems()['jump']
        tau = np.array(info['grid'], dtype=float) - info['grid'][0]
        k = [1e-4, 0.01, 1e-3]
        m0, b0 = info['y0'][0], info['y0'][1]

        def bateman(first: int, member: int) -> np.ndarray:
            rates = k[first:member + 1]
            out = np.zeros(tau.size)
            for i, ki in enumerate(rates):
                others = [kj for j, kj in enumerate(rates) if j != i]
                out += np.prod(rates[:-1]) * np.exp(-ki * tau) / np.prod([kj - ki for kj in others])
            return out
        exact = np.array([m0 * bateman(0, 0), m0 * bateman(0, 1) + b0 * bateman(1, 1),
                          m0 * bateman(0, 2) + b0 * bateman(1, 2)]).T
        seen = 0
        for name, solver, opts, theirs, mine in self.pairs():
            if name != 'jump':
                continue
            seen += 1
            with self.subTest(solver=solver):
                self.assertNotIn('error', theirs, theirs.get('error'))
                self.assertNotIn('error', mine, mine.get('error'))
                # After the first row, which is the start (and where the closed
                # form's terms cancel to 1e-4 of nothing). 3e-5 at worst when
                # written, TRBDF2's, which is second order.
                y = np.array(mine['y'], dtype=float)[1:, :3]
                self.assertLess(np.max(np.abs(y - exact[1:]) / np.abs(exact[1:])), 1e-4)
        self.assertEqual(seen, len(EVERY))

    def test_they_fail_as_the_application_fails(self) -> None:
        failures = 0
        for name, solver, opts, theirs, mine in self.pairs():
            if 'error' not in theirs and 'error' not in mine:
                continue
            failures += 1
            with self.subTest(problem=name, solver=solver, opts=opts):
                self.assertIn('error', theirs, mine.get('error'))
                self.assertIn('error', mine, theirs.get('error'))
                # The same words; the time in them is where the run gave up, an
                # accepted step's, which parts in the last digits as the step
                # sequences do (4e-6 relative when written).
                text, numbers = _number_free(mine['error'])
                text_js, numbers_js = _number_free(theirs['error'])
                self.assertEqual(text, text_js)
                for a, b in zip(numbers, numbers_js):
                    self.assertLessEqual(abs(a - b), 1e-4 * max(abs(a), abs(b), 1.0))
                if 'abortAfter' in opts:
                    self.assertEqual(mine['error'], 'Simulation aborted')
                    self.assertEqual(mine['calls'], theirs['calls'])
                    self.assertEqual(mine['code'], 'aborted')
                elif 'maxSteps' in opts:
                    self.assertEqual(mine['code'], 'steps')
                elif opts.get('grid') == [0.5, 0.5]:
                    self.assertEqual(mine['error'], 'Simulation start and end time are equal')
                    self.assertEqual(mine['code'], 'span')
        # The step budget and the stop, with every method; equal ends, with three.
        self.assertEqual(failures, 2 * len(EVERY) + 3)

    def test_the_chain_is_batemans(self) -> None:
        """Absolute accuracy, not only agreement: the decay chain against its
        closed form, every member, at every output time."""
        info = problems()['chain']
        k = np.array(info['rates'])
        grid = np.array(info['grid'], dtype=float)
        exact = np.zeros((grid.size, k.size))
        for j in range(k.size):
            for i in range(j + 1):
                others = np.delete(k[:j + 1], i)
                exact[:, j] += np.prod(k[:j]) * np.exp(-k[i] * grid) / np.prod(others - k[i])
        for name, solver, opts, theirs, mine in self.pairs():
            if name != 'chain' or 'error' in mine:
                continue
            with self.subTest(solver=solver, opts=opts):
                y = np.array(mine['y'], dtype=float)
                # Every method reads its rows off its own interpolant, held to
                # the tolerance's scale; TRBDF2 is second order.
                bound = 1e-4 if solver == 'trbdf2' else 1e-5
                self.assertLess(np.max(np.abs(y - exact)), bound)
                self.assertLess(np.max(np.abs(y[-1] - exact[-1])), 1e-4)


# The package-level runs of the switch, each a problem, an algorithm and the
# package's options: stiff from the start and small (Robertson, HIRES, a
# chain of twelve), stiff with non-stiff stretches (van der Pol at mu = 1000,
# seven switches), not stiff at all (Kepler), a state at rest beside an
# oscillator, and the switch's options. On every one the port takes the
# application's steps with the platform's pow: the switch is decided on
# verdicts with room to spare.
SWITCH_RUNS: List[Dict[str, Any]] = [
    {'problem': 'robertson', 'alg': 'DefaultODEAlgorithm', 'opts': {'reltol': 1e-6, 'abstol': 1e-10}},
    {'problem': 'robertson', 'alg': 'DefaultODEAlgorithm', 'opts': {'reltol': 1e-3, 'abstol': 1e-6}},
    {'problem': 'robertson', 'alg': 'DefaultODEAlgorithm', 'opts': {'reltol': 1e-8, 'abstol': 1e-10}},
    {'problem': 'vdp1000', 'alg': 'DefaultODEAlgorithm', 'opts': {'reltol': 1e-3, 'abstol': 1e-6}},
    {'problem': 'vdp1000', 'alg': 'DefaultODEAlgorithm', 'opts': {'reltol': 1e-6, 'abstol': 1e-8}},
    {'problem': 'hires', 'alg': 'DefaultODEAlgorithm', 'opts': {'reltol': 1e-3, 'abstol': 1e-6}},
    {'problem': 'hires', 'alg': 'DefaultODEAlgorithm', 'opts': {'reltol': 1e-8, 'abstol': 1e-10}},
    {'problem': 'kepler', 'alg': 'DefaultODEAlgorithm', 'opts': {'reltol': 1e-3, 'abstol': 1e-6}},
    {'problem': 'kepler', 'alg': 'DefaultODEAlgorithm', 'opts': {'reltol': 1e-8, 'abstol': 1e-10}},
    {'problem': 'chain', 'alg': 'DefaultODEAlgorithm', 'opts': {'reltol': 1e-6, 'abstol': 1e-12}},
    {'problem': 'idle', 'alg': 'DefaultODEAlgorithm', 'opts': {}},
    {'problem': 'idle', 'alg': 'DefaultODEAlgorithm', 'algOptions': {'stillIsStiff': True}, 'opts': {}},
    {'problem': 'vdp1000', 'alg': 'DefaultImplicitODEAlgorithm', 'opts': {}},
    {'problem': 'vdp1000', 'alg': 'AutoTsit5Rodas5P', 'opts': {}},
    {'problem': 'vdp1000', 'alg': 'DefaultODEAlgorithm', 'algOptions': {'maxstiffstep': 2, 'maxnonstiffstep': 1},
     'opts': {}},
    # FBDF in the switch, factorising: a chain of 120 compartments.
    {'problem': 'chain120', 'alg': 'DefaultODEAlgorithm', 'opts': {'reltol': 1e-3, 'abstol': 1e-6}},
]


def runs_of(choice: List[int]) -> List[Tuple[int, int]]:
    """A choice per row as runs of (method, rows)."""
    out: List[List[int]] = []
    for a in choice:
        if out and out[-1][0] == a:
            out[-1][1] += 1
        else:
            out.append([a, 1])
    return [(a, k) for a, k in out]


@needs_app
class Switching(unittest.TestCase):
    """The default algorithm's switch: which method took every saved row, the
    steps each took, the log of switches, and its options -- the
    application's, run for run; then the carry from one solve of a run to the
    next, and the run log's account."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.theirs = bridge('package', runs=SWITCH_RUNS)['runs']
        cls.mine = [run_package(r['problem'], r['alg'], r.get('algOptions'), r.get('opts')) for r in SWITCH_RUNS]

    def test_every_row_was_taken_by_the_applications_method(self) -> None:
        for r, js, mine in zip(SWITCH_RUNS, self.theirs, self.mine):
            with self.subTest(**r):
                self.assertNotIn('error', js)
                self.assertEqual(mine['retcode'], js['retcode'], mine['message'])
                self.assertEqual(mine['algChoice'], js['algChoice'])
                for key in ('naccept', 'nreject', 'nf', 'njacs', 'nw', 'nsolve', 'stepsBy', 'switches', 'lastAlg',
                            'algorithms'):
                    self.assertEqual(mine['stats'][key], js['stats'][key], key)
                self.assertEqual([(e['from'], e['to']) for e in mine['stats']['switchLog']],
                                 [(e['from'], e['to']) for e in js['stats']['switchLog']])
                # The same steps, each a last bit apart in size -- a step size
                # goes through a pow -- and so at times up to 3e-6 apart
                # (Robertson at 1e-8, 5e-7 at a switch on the chain), with the
                # states at the end round-off apart (6.5e-5 tolerance units at
                # worst when written).
                for a, b in zip(mine['stats']['switchLog'], js['stats']['switchLog']):
                    self.assertLessEqual(abs(a['t'] - b['t']), 1e-5 * max(1.0, abs(b['t'])))
                self.assertEqual(len(mine['t']), len(js['t']))
                self.assertEqual(mine['t'][-1], js['t'][-1])
                rtol, atol = r['opts'].get('reltol', 1e-3), r['opts'].get('abstol', 1e-6)
                end, end_js = np.array(mine['u'][-1]), np.array(js['u'][-1])
                self.assertLess(float(np.max(np.abs(end - end_js) / (atol + rtol * np.abs(end_js)))), 1e-3)

    def test_the_switch_does_what_it_says(self) -> None:
        by = {(r['problem'], r['alg'], json.dumps(r.get('algOptions')), json.dumps(r['opts'])): m
              for r, m in zip(SWITCH_RUNS, self.mine)}

        def run(problem: str, alg: str = 'DefaultODEAlgorithm', options: Any = None, **opts: Any) -> Dict[str, Any]:
            return by[(problem, alg, json.dumps(options), json.dumps(opts))]
        # Every accepted step is one method's, and every saved row says whose.
        for m in self.mine:
            self.assertEqual(sum(m['stats']['stepsBy'].values()), m['stats']['naccept'])
            self.assertEqual(len(m['algChoice']), len(m['t']))
            self.assertEqual(m['stats']['switches'], len(m['stats']['switchLog']))
        # Van der Pol at mu = 1000: seven switches between Tsit5 and
        # Rosenbrock23, as OrdinaryDiffEq makes them.
        vdp = run('vdp1000', reltol=1e-3, abstol=1e-6)
        self.assertEqual(vdp['stats']['switches'], 7)
        self.assertEqual(set(vdp['algChoice']), {1, 3})
        self.assertEqual((vdp['stats']['switchLog'][0]['from'], vdp['stats']['switchLog'][0]['to']),
                         ('Tsit5', 'Rosenbrock23'))
        # Below a relative tolerance of 1e-6 the pair is Vern7 and Rodas5P.
        self.assertEqual(set(run('robertson', reltol=1e-8, abstol=1e-10)['stats']['stepsBy']), {'Vern7', 'Rodas5P'})
        kepler = run('kepler', reltol=1e-8, abstol=1e-10)
        self.assertEqual((list(kepler['stats']['stepsBy']), kepler['stats']['switches']), (['Vern7'], 0))
        # The stiff side first, and the stiff side throughout.
        implicit = run('vdp1000', 'DefaultImplicitODEAlgorithm')
        self.assertEqual((implicit['algChoice'][0], implicit['stats']['switches']), (3, 0))
        pair = run('vdp1000', 'AutoTsit5Rodas5P')
        self.assertEqual(list(pair['stats']['stepsBy']), ['Tsit5', 'Rodas5P'])
        self.assertGreaterEqual(pair['stats']['switches'], 2)
        # A state at rest does not make a non-stiff problem stiff -- unless
        # read as Julia reads it.
        self.assertEqual(run('idle')['stats']['switches'], 0)
        self.assertGreater(run('idle', options={'stillIsStiff': True})['stats']['switches'], 0)
        # The thresholds are the switch's: three stiff verdicts switch, not eleven.
        eager = run('vdp1000', options={'maxstiffstep': 2, 'maxnonstiffstep': 1})
        self.assertLess(runs_of(eager['algChoice'])[0][1], runs_of(vdp['algChoice'])[0][1])

    def test_a_run_restarted_goes_on_with_the_method_it_had(self) -> None:
        """The carry: one dict for every solve of a run, in which
        ``auto_julia`` keeps whether it ended stiff and ``auto`` whether it
        has handed the run to the NDF -- through the adapter, as the
        application's, and through the runner, where a run restarts at its
        events."""
        grids = [[0, 1, 10, 100], [100, 1e3, 1e4]]
        runs = [{'problem': 'robertson', 'solver': s, 'opts': {'rtol': 1e-6, 'abstol': 1e-10}, 'grids': grids}
                for s in ('auto_julia', 'auto')]
        js = bridge('carry', runs=runs)
        f, jac = functions('robertson')
        info = problems()['robertson']
        n = info['n']
        col_ptr = np.array(info['colPtr'], dtype=np.int64)
        pattern = Pattern(n, np.array(info['rowIdx'], dtype=np.int64), np.repeat(np.arange(n), np.diff(col_ptr)))
        jacobian = {'pattern': pattern, 'available': True,
                    'evaluate': lambda t, y: jac(t, y)[pattern.row_idx, pattern.col_of]}

        def solves(solver: str, carried: bool) -> List[Dict[str, Any]]:
            carry: Dict[str, Any] = {}
            y = np.array(info['y0'], dtype=float)
            out = []
            for grid in grids:
                opts = {'rtol': 1e-6, 'abstol': 1e-10, 'jacobian': jacobian, 'carry': carry if carried else {}}
                r = getattr(ported, solver)(f, np.array(grid, dtype=float), y, opts)
                out.append({'stats': r['stats'], 'carry': dict(carry), 'y': r['y']})
                y = r['y'][-1]
            return out
        for solver, theirs in zip(('auto_julia', 'auto'), (r['solves'] for r in js['runs'])):
            mine = solves(solver, True)
            for k, (a, b) in enumerate(zip(mine, theirs)):
                with self.subTest(solver=solver, solve=k):
                    self.assertEqual(a['carry'], b['carry'])
                    self.assertEqual(a['stats']['steps_by'], b['stats']['stepsBy'])
                    self.assertEqual(a['stats']['switches'], b['stats']['switches'])
                    self.assertEqual(counts_agree(a['stats'], b['stats']), [])
            if solver == 'auto_julia':
                # Stiff after the first, so the second starts there: no Tsit5 at all.
                self.assertTrue(mine[0]['carry']['stiff'])
                self.assertGreater(mine[0]['stats']['steps_by']['Tsit5'], 0)
                self.assertNotIn('Tsit5', mine[1]['stats']['steps_by'])
                self.assertEqual(mine[1]['stats']['switches'], 0)
                # Without the carry each solve starts on Tsit5 again.
                self.assertGreater(solves(solver, False)[1]['stats']['steps_by']['Tsit5'], 0)
            else:
                # Vern7 at a tenth of 1e-6, then the NDF; the NDF throughout after.
                self.assertEqual(mine[0]['carry'], {'ndf': True})
                self.assertEqual(list(mine[0]['stats']['steps_by']), ['Vern7', 'NDF'])
                self.assertEqual(mine[0]['stats']['switches'], 1)
                self.assertEqual(list(mine[1]['stats']['steps_by']), ['NDF'])
                self.assertEqual(mine[1]['stats']['switches'], 0)
                self.assertGreater(solves(solver, False)[1]['stats']['steps_by']['Vern7'], 0)

        # Through the runner: a stiff model restarted by a discrete event at
        # t = 5. The solve after it goes on as the one before ended -- with
        # Rosenbrock23, or the NDF -- as the application's; handed a fresh
        # carry, it would start on the explicit method again and take another
        # path altogether.
        from kompartment.engine import solverset
        for solver in ('auto_julia', 'auto'):
            with self.subTest(solver=solver, through='the runner'):
                m = kp_model_restarted(solver)
                js_run = engine('run', model=m, overrides={})
                res = run_project(Project(json.loads(json.dumps(m))), compiled=False)
                self.assertEqual(res.stats['events'], 1)
                self.assertEqual(res.stats['steps_by'], js_run['stats']['stepsBy'])
                self.assertEqual(res.stats['switches'], js_run['stats']['switches'])
                handed = solverset.SOLVERS[solver]
                with mock.patch.dict(solverset.SOLVERS,
                                     {solver: lambda f, tspan, y0, opts, h=handed: h(f, tspan, y0,
                                                                                     {**opts, 'carry': {}})}):
                    fresh = run_project(Project(json.loads(json.dumps(m))), compiled=False)
                self.assertNotEqual(fresh.stats['steps_by'], res.stats['steps_by'])

    def test_a_chain_of_120_at_a_tight_tolerance(self) -> None:
        """The chain of 120 at reltol 1e-6: Tsit5 and FBDF, back and forth
        hundreds of times in the application too (OrdinaryDiffEq's FBDF rides
        through steps the port rejects, and stays stiff; see problems-default.mjs).
        Which way each verdict goes is decided in the last bits, so the counts
        are held to the spread of the application's own runs: nudging reltol
        by 1e-9 relative takes it from 9330 to 10 620 steps and 943 to 1101
        switches (ten nudges, measured 2026-10-03), and the port's runs lie in
        the same band (9394 to 9983). Run dense, with V8's pow and the
        package's LU, the port's run is the application's step for step
        (BitIdentity.test_runs_too_long_for_until_known)."""
        opts = {'rtol': 1e-6, 'abstol': 1e-9}
        js = bridge('solve', runs=[{'problem': 'chain120', 'solver': 'auto_julia', 'opts': opts}])['runs'][0]
        mine = run_here('chain120', 'auto_julia', opts)
        here, there = mine['stats'], js['stats']
        self.assertEqual(list(here['steps_by']), ['Tsit5', 'FBDF'])
        self.assertEqual(list(there['stepsBy']), ['Tsit5', 'FBDF'])
        self.assertEqual(sum(here['steps_by'].values()), here['nsteps'] - here['nfailed'])
        self.assertTrue(within(here['nsteps'], there['nsteps'], 0.15, 2), f"{here['nsteps']} against {there['nsteps']}")
        self.assertTrue(within(here['switches'], there['switches'], 0.15, 2),
                        f"{here['switches']} against {there['switches']}")
        # Each run carries its own error: the two 1.7 to 10.2 tolerance units
        # apart over the ten nudges.
        a, b = np.array(mine['y']), np.array(js['y'])
        self.assertLess(float(np.max(np.abs(a - b) / (opts['abstol'] + opts['rtol'] * np.abs(b)))), 50)

    def test_the_run_log_says_which_methods_took_the_steps(self) -> None:
        from kompartment.engine import runlog
        # At a tenth of 1e-6, Vern7 until the run turns stiff, and the NDF from
        # there; DifferentialEquations.jl's own takes Tsit5 and Rosenbrock23.
        for solver, pattern in (('auto', r'^Vern7 \d+ steps?, NDF \d+; 1 switch$'),
                                ('auto_julia', r'^Tsit5 \d+ steps?, Rosenbrock23 \d+; \d+ switch(es)?$')):
            with self.subTest(solver=solver):
                model = example('biosphere')
                model['simulation']['solver'] = solver
                res = run_project(Project(json.loads(json.dumps(model))))
                by = res.stats['steps_by']
                self.assertEqual(sum(by.values()), res.stats['nsteps'] - res.stats['nfailed'])
                line = runlog.describe_method_steps(runlog.payload_of(res)['stats'])
                self.assertRegex(line, pattern)
                log = runlog.run_log(res, build='test')
                self.assertIn(f'\n  methods: {line}\n', log)
                self.assertIn(f'methods: {line}', res.summary())
                self.assertEqual(runlog.payload_of(res)['stats']['stepsBy'], by)
                # And the application's run of it, logged by both.
                js_run = engine('run', model=example('biosphere'), overrides={'solver': solver})
                if all(res.stats.get(k) == js_run['stats'].get(k) for k in COUNTS):
                    self.assertEqual(line, runlog.describe_method_steps(js_run['stats']))
        # Every other solver is one method, and says nothing of the kind.
        model['simulation']['solver'] = 'ndf'
        ndf = run_project(Project(json.loads(json.dumps(model))))
        self.assertNotIn('steps_by', ndf.stats)
        self.assertNotIn('methods:', runlog.run_log(ndf, build='test'))
        self.assertIsNone(runlog.describe_method_steps(ndf.stats))


def kp_model_restarted(solver: str = 'auto_julia') -> Dict[str, Any]:
    """Two compartments exchanging at 1e4 a year and draining slowly, stiff
    for as long as anything is left in them, and a discrete event at t = 5,
    at which the runner starts the solver again."""
    import kompartment as kp
    m = kp.Model.new('Stiff and restarted')
    m.simulation.update(end_time=20, output_points=21, spacing='linear', rtol=1e-6, abstol=1e-10, solver=solver)
    m.add_compartment('A', initial='1')
    m.add_compartment('B')
    m.add_compartment('C')
    m.add_transfer('A', 'B', rate='1e4')
    m.add_transfer('B', 'A', rate='1e4')
    m.add_transfer('B', 'C', rate='0.5')
    m.add_trigger('Tick', first='time', second='5', direction='rising')
    m.add_snapshot('At_tick', target='B', trigger='Tick', initial='0')
    return json.loads(json.dumps(m.to_dict()))


@needs_app
class Krylov(unittest.TestCase):
    """GMRES, and the FBDF whose Newton iterations it solves without a matrix."""

    def test_gmres_solves_what_a_dense_lu_solves(self) -> None:
        from kompartment.engine.solvers.julia.krylov import GMRES, sym_givens
        rng = np.random.default_rng(7)
        n = 60
        A = rng.random((n, n)) - 0.5 + 6 * np.eye(n)
        b = rng.random(n) - 0.5
        exact = np.linalg.solve(A, b)

        def op(v: np.ndarray) -> np.ndarray:
            return A @ v
        g = GMRES(n)
        x = g.solve(op, b, atol=0.0, rtol=1e-12, itmax=n)
        self.assertTrue(g.stats['solved'])
        self.assertLess(np.max(np.abs(x - exact)), 1e-9)
        w = 10.0 ** ((np.arange(n) % 9) - 4)
        x2 = g.solve(op, b, atol=0.0, rtol=1e-12, itmax=n, left=w, right=w)
        self.assertTrue(g.stats['solved'])
        self.assertLess(np.max(np.abs(x2 - exact)), 1e-9)
        # Started from the answer, with the cold start's threshold, it stops at once.
        x3 = g.solve(op, b, atol=1e-12 * float(np.linalg.norm(b)), rtol=0.0, itmax=n, x0=exact)
        self.assertEqual((g.stats['solved'], g.stats['niter']), (True, 0))
        self.assertLess(np.max(np.abs(x3 - exact)), 1e-12)
        # A basis at its memory cap fails rather than growing.
        tight = GMRES(n, memory=5, max_bytes=8 * n * 5)
        tight.solve(op, b, atol=0.0, rtol=1e-14, itmax=n)
        self.assertFalse(tight.stats['solved'])
        self.assertIn('cap', tight.stats['status'])
        c, s, rho = sym_givens(3.0, 4.0)
        self.assertLess(abs(s * 3 - c * 4), 1e-15)
        self.assertLess(abs(rho - 5), 1e-15)

    def test_the_matrix_free_fbdf_on_600_states(self) -> None:
        """Diffusion on 600 points, through the adapter: the matrix-free
        FBDF, and the switch, which takes it above 500 states -- and the
        switch on a chain of 600 compartments, rates from 1e4 down to 1e-4,
        the shape of a compartment model. No Jacobian, no factorisation; the
        application's steps, and its GMRES iterations within
        GMRES_ITERATIONS_SHARE."""
        cases = [('heat', 'fbdf_krylov', {'rtol': 1e-6, 'abstol': 1e-8}),
                 ('heat', 'auto_julia', {'rtol': 1e-3, 'abstol': 1e-6}),
                 ('heat', 'auto_julia', {'rtol': 1e-6, 'abstol': 1e-9}),
                 ('long_chain', 'auto_julia', {'rtol': 1e-3, 'abstol': 1e-6})]
        theirs = bridge('solve', runs=[{'problem': n, 'solver': s, 'opts': o} for n, s, o in cases])['runs']
        for (name, solver, opts), js in zip(cases, theirs):
            with self.subTest(solver=solver):
                mine = run_here(name, solver, opts)
                self.assertNotIn('error', js)
                self.assertNotIn('error', mine)
                here, there = mine['stats'], js['stats']
                self.assertEqual(counts_agree(here, there), [])
                self.assertEqual((here['npds'], here['ndecomps'], here['sparse'], here['fill']), (0, 0, False, None))
                self.assertGreater(here['krylov_iters'], here['nsolves'])
                # In units of the tolerance: down the chain most states sit far
                # below abstol, where a relative difference says nothing (1e-4
                # units at worst when written, GMRES's left-over residual).
                a, b = np.array(mine['y']), np.array(js['y'])
                self.assertLess(float(np.max(np.abs(a - b) / (opts['abstol'] + opts['rtol'] * np.abs(b)))), 0.1)
                if solver == 'auto_julia':
                    self.assertEqual(list(here['steps_by']), ['Tsit5', 'KrylovFBDF'])
                    self.assertEqual(here['steps_by'], there['stepsBy'])
                    # One switch, as OrdinaryDiffEq makes it. On diffusion
                    # at 1e-6 this was 26 516 steps and 3147 switches while
                    # the switch counted every FBDF rejection as a verdict
                    # and FBDF predicted its first step from the last value
                    # (the application now takes 88 steps and rejects 8).
                    self.assertEqual((here['switches'], there['switches']), (1, 1))
                    if name == 'heat':
                        self.assertLess(here['nsteps'], 200)

    def test_the_problems_own_jvp_is_used(self) -> None:
        """J*v from the problem itself, where it has one: no f spent on
        differencing it, and the same answer within the tolerance."""
        info = problems()['heat']
        n = info['n']
        f, _ = functions('heat')
        dx = 1 / (n + 1)
        calls = [0]

        def jvp(t: float, u: np.ndarray, v: np.ndarray, fu: np.ndarray) -> np.ndarray:
            calls[0] += 1
            left = np.concatenate([[0.0], v[:-1]])
            right = np.concatenate([v[1:], [0.0]])
            return (left - 2 * v + right) / (dx * dx)
        y0 = np.array(info['y0'], dtype=float)
        opts = {'reltol': 1e-4, 'abstol': 1e-6}
        with np.errstate(all='ignore'):
            plain = package_solve(ODEProblem(f, y0, (0.0, 0.1)), methods.FBDF(linsolve='gmres'), opts)
            exact = package_solve(ODEProblem(f, y0, (0.0, 0.1), jvp=jvp), methods.FBDF(linsolve='gmres'), opts)
        self.assertEqual((plain.retcode, exact.retcode), ('Success', 'Success'))
        self.assertGreater(calls[0], 0)
        self.assertEqual(exact.stats['krylovJvps'], calls[0])
        self.assertLess(exact.stats['nf'], plain.stats['nf'] / 3)
        self.assertEqual((exact.stats['njacs'], exact.stats['nw']), (0, 0))
        scale = 1e-6 + 1e-4 * np.abs(plain.u[-1])
        self.assertLess(float(np.max(np.abs(exact.u[-1] - plain.u[-1]) / scale)), 50)


@needs_app
class Explicit(unittest.TestCase):
    """What came with the explicit methods: no matrix, Vern7's lazy stages, f
    taken again at a clamped state, OrdinaryDiffEq's starting step."""

    def test_an_explicit_method_forms_no_matrix(self) -> None:
        # 300 000 states: a dense W would be 720 GB.
        n = 300000
        rate = 1 + (np.arange(n) % 7) / 7

        def f(t: float, u: np.ndarray) -> np.ndarray:
            return -u * rate
        for make in (methods.Tsit5, methods.Vern7, methods.DefaultODEAlgorithm):
            with self.subTest(method=make.__name__):
                sol = package_solve(ODEProblem(f, np.ones(n), (0.0, 1.0)), make(), {'save_everystep': False})
                self.assertEqual(sol.retcode, 'Success')
                self.assertEqual((sol.stats['njacs'], sol.stats['nw']), (0, 0))

    def test_vern7_works_out_its_interpolation_stages_only_for_a_row(self) -> None:
        """Ten evaluations a step either way, plus six for each step a saved
        row falls inside -- and the application's count of them."""
        grid = [0.5 * i for i in range(41)]
        opts = {'reltol': 1e-8, 'abstol': 1e-10}
        runs = [{'problem': 'kepler', 'alg': 'Vern7', 'opts': opts},
                {'problem': 'kepler', 'alg': 'Vern7', 'opts': {**opts, 'saveat': grid}}]
        theirs = bridge('package', runs=runs)['runs']
        plain, rows = [run_package(r['problem'], r['alg'], None, r['opts']) for r in runs]
        self.assertEqual(plain['stats']['naccept'], rows['stats']['naccept'])
        ts = plain['t']
        inside = set()
        for g in grid[1:-1]:
            j = 1
            while j < len(ts) and ts[j] < g:
                j += 1
            if ts[j] != g:
                inside.add(j)
        self.assertEqual(rows['stats']['nf'] - plain['stats']['nf'], 6 * len(inside))
        for mine, js in zip((plain, rows), theirs):
            self.assertEqual(mine['stats']['nf'], js['stats']['nf'])
            self.assertEqual(len(mine['t']), len(js['t']))
            # The same steps a last bit apart in size (see Switching).
            self.assertLess(max(abs(a - b) / max(1.0, abs(b)) for a, b in zip(mine['t'], js['t'])), 1e-6)
        # The saved rows are at the same times on both sides.
        self.assertLess(worst_relative(rows['u'], theirs[1]['u']), 1e-6)

    def test_f_is_taken_again_where_clamping_moved_the_solution(self) -> None:
        # u' = -1 - u falls through zero at ln 2, and is held there.
        for make in (methods.Tsit5, methods.Rosenbrock23):
            with self.subTest(method=make.__name__):
                calls: List[Tuple[float, float]] = []

                def f(t: float, u: np.ndarray) -> np.ndarray:
                    calls.append((t, float(u[0])))
                    return np.array([-1 - u[0]])
                clamped_at: List[float] = []

                def on_accepted(t: float, u: np.ndarray) -> None:
                    if not clamped_at and u[0] == 0:
                        clamped_at.append(t)
                sol = package_solve(ODEProblem(f, [1.0], (0.0, 2.0)), make(),
                                    {'non_negative': True, 'reltol': 1e-4, 'abstol': 1e-8,
                                     'on_accepted': on_accepted})
                self.assertEqual(sol.retcode, 'Success')
                self.assertTrue(clamped_at)
                self.assertIn((clamped_at[0], 0.0), calls)

    def test_ordinarydiffeqs_starting_step(self) -> None:
        from kompartment.engine.solvers.julia.controller import eps_of, initial_step_sciml

        def flat(t: float, u: np.ndarray) -> np.ndarray:
            return np.array([1.0])
        one = np.array([1.0])
        # f does not change: a hundred times the first probe, (d0/d1)/100.
        self.assertLess(abs(initial_step_sciml(flat, 0.0, one, one, 1.0, 5, 1e-3, 1e-6, 10.0) - 1), 1e-15)
        # dtmax bounds the first probe; the integrator holds the answer to it.
        self.assertLess(abs(initial_step_sciml(flat, 0.0, one, one, 1.0, 5, 1e-3, 1e-6, 0.005) - 0.5), 1e-15)
        self.assertEqual((eps_of(1.0), eps_of(0.0), eps_of(-2.0)), (_js.EPS, _js.MIN_VALUE, 2 * _js.EPS))
        # Its log10 is V8's: the application's to the bit wherever the power is.
        xs = [1e-300, 5e-324, 0.3, 123.456, 2.5e7, 1e15, 7.0000000000000001e-3]
        theirs = bridge('log10', values=xs)['values']
        from kompartment import jsmath
        self.assertEqual([jsmath.log10(x) for x in xs], theirs)


# The default algorithm told to hand off every stiff method, as ``auto`` tells
# it: problems stiff from the first steps, stiff after a non-stiff stretch,
# never stiff; and started on the stiff side, where it stops before a step.
HAND_OFF = ['Rosenbrock23', 'Rodas5P', 'FBDF', 'KrylovFBDF']
HAND_OFF_RUNS: List[Dict[str, Any]] = [
    {'problem': 'robertson', 'alg': 'DefaultODEAlgorithm', 'algOptions': {'handOff': HAND_OFF},
     'opts': {'reltol': 1e-7, 'abstol': 1e-11}},
    {'problem': 'vdp1000', 'alg': 'DefaultODEAlgorithm', 'algOptions': {'handOff': HAND_OFF},
     'opts': {'reltol': 1e-4, 'abstol': 1e-7}},
    {'problem': 'hires', 'alg': 'DefaultODEAlgorithm', 'algOptions': {'handOff': HAND_OFF},
     'opts': {'reltol': 1e-4, 'abstol': 1e-7}},
    {'problem': 'chain120', 'alg': 'DefaultODEAlgorithm', 'algOptions': {'handOff': HAND_OFF},
     'opts': {'reltol': 1e-4, 'abstol': 1e-7}},
    {'problem': 'kepler', 'alg': 'DefaultODEAlgorithm', 'algOptions': {'handOff': HAND_OFF},
     'opts': {'reltol': 1e-7, 'abstol': 1e-9}},
    {'problem': 'vdp1000', 'alg': 'DefaultODEAlgorithm', 'algOptions': {'handOff': ['Rosenbrock23'],
                                                                        'stiffalgfirst': True}, 'opts': {}},
    {'problem': 'vdp1000', 'alg': 'DefaultODEAlgorithm', 'algOptions': {'handOff': ['KrylovFBDF']}, 'opts': {}},
]


@needs_app
class HandOff(unittest.TestCase):
    """``auto``: the default algorithm stopping where it would have turned
    stiff, the NDF going on from there, and the corners of the clock-read
    tables the explicit methods land on."""

    def test_the_package_stops_where_it_would_have_switched(self) -> None:
        theirs = bridge('package', runs=HAND_OFF_RUNS)['runs']
        mine = [run_package(r['problem'], r['alg'], r.get('algOptions'), r['opts']) for r in HAND_OFF_RUNS]
        handed = 0
        for r, js, here in zip(HAND_OFF_RUNS, theirs, mine):
            with self.subTest(**r):
                self.assertNotIn('error', js)
                self.assertEqual(here['retcode'], js['retcode'])
                self.assertEqual(here['stats']['stepsBy'], js['stats']['stepsBy'])
                self.assertEqual(here['stats']['switches'], js['stats']['switches'])
                self.assertEqual(len(here['t']), len(js['t']))
                if js['handOff'] is None:
                    self.assertIsNone(here['handOff'])
                    continue
                handed += 1
                self.assertEqual(here['stats']['switches'], 0)
                a, b = here['handOff'], js['handOff']
                self.assertEqual((a['from'], a['to']), (b['from'], b['to']))
                self.assertEqual(here['message'].split(' at t = ')[0], js['message'].split(' at t = ')[0])
                # The same steps a last bit apart in size (see Switching): on
                # Robertson, where the explicit method runs at the edge of its
                # stability, 1e-6 apart at the hand-off, and the states there
                # 1.2e-9 of the largest (BitIdentity has them bit for bit).
                self.assertLessEqual(abs(a['t'] - b['t']), 1e-5 * max(1.0, abs(b['t'])))
                u, u_js = np.array(a['u']), np.array(b['u'])
                self.assertLess(float(np.max(np.abs(u - u_js)) / np.max(np.abs(u_js))), 1e-6)
        self.assertEqual(handed, 5)
        by = {(r['problem'], json.dumps(r['algOptions'])): m for r, m in zip(HAND_OFF_RUNS, mine)}
        # Stopped where the default algorithm would have switched: its run up
        # to there, the same rows, and the state at its last accepted step.
        whole = run_package('vdp1000', 'DefaultODEAlgorithm', None, {'reltol': 1e-4, 'abstol': 1e-7})
        cut = by[('vdp1000', json.dumps({'handOff': HAND_OFF}))]
        first = whole['stats']['switchLog'][0]
        self.assertEqual((cut['handOff']['t'], cut['handOff']['from'], cut['handOff']['to']),
                         (first['t'], 'Tsit5', 'Rosenbrock23'))
        k = sum(1 for t in whole['t'] if t <= first['t'])
        self.assertEqual(cut['t'], whole['t'][:k])
        self.assertEqual(cut['u'], whole['u'][:k])
        # Started on a method it hands off: before a step, at the start.
        start = by[('vdp1000', json.dumps({'handOff': ['Rosenbrock23'], 'stiffalgfirst': True}))]
        self.assertEqual((start['retcode'], start['stats']['nsteps'], start['handOff']['t'],
                          start['handOff']['from']), ('HandedOff', 0, 0.0, None))
        self.assertEqual(start['handOff']['u'], problems()['vdp1000']['y0'])
        # A method it never chooses is no reason to stop.
        other = by[('vdp1000', json.dumps({'handOff': ['KrylovFBDF']}))]
        plain = run_package('vdp1000', 'DefaultODEAlgorithm', None, {})
        self.assertEqual((other['retcode'], other['t'], other['u']), ('Success', plain['t'], plain['u']))

    def test_the_explicit_steps_land_on_the_corners(self) -> None:
        """y' = s(t), s rising until 3.7 and falling after: y has a corner in
        its slope there that only the table says. A step ends on it, and the
        rows are the closed form's; with more corners than it lands on, the
        run is the NDF's from the start and from then on."""
        corner = 3.7

        def s(t: float) -> float:
            return t if t < corner else 2 * corner - t

        def exact(t: float) -> float:
            if t < corner:
                return t * t / 2
            return corner * corner / 2 + 2 * corner * (t - corner) - (t * t - corner * corner) / 2

        grid = np.arange(11, dtype=float)
        steps: List[float] = []
        r = ported.auto(lambda t, y: np.array([s(t)]), grid, np.zeros(1),
                        {'rtol': 1e-3, 'abstol': 1e-3, 'table_corners': lambda a, b, limit: [corner],
                         'on_accepted': lambda t, y: steps.append(float(t))})
        self.assertIn(corner, steps)
        self.assertLess(max(abs(r['y'][k][0] - exact(t)) for k, t in enumerate(r['t'])), 1e-6)
        carry: Dict[str, Any] = {}
        many = ported.auto(lambda t, y: np.array([s(t)]), grid, np.zeros(1),
                           {'rtol': 1e-3, 'abstol': 1e-3, 'carry': carry,
                            'table_corners': lambda a, b, limit: None if limit < 150 else []})
        self.assertEqual((list(many['stats']['steps_by']), many['stats']['switches'], carry), (['NDF'], 0,
                                                                                             {'ndf': True}))
        self.assertEqual(many['stats']['solver'], 'auto')

    def test_a_handed_run_has_a_row_at_every_time_once(self) -> None:
        """Robertson: Vern7 for a few steps, then the NDF, inside the grid --
        a row at every time asked, the recorders told of each once, every step
        someone's, and the answer the NDF's own to its tolerance."""
        f, jac = functions('robertson')
        grid = np.array([0, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 0.1, 1, 10, 100, 1000])
        outputs = [0]
        def told(t: float, y: np.ndarray) -> None:
            outputs[0] += 1
        r = ported.auto(f, grid, np.array([1.0, 0.0, 0.0]), {'rtol': 1e-6, 'abstol': 1e-10, 'on_output': told})
        self.assertEqual((r['stats']['switches'], list(r['stats']['steps_by'])), (1, ['Vern7', 'NDF']))
        self.assertEqual(r['t'].tolist(), grid.tolist())
        self.assertEqual((len(r['y']), outputs[0]), (grid.size, grid.size - 1))
        self.assertEqual(sum(r['stats']['steps_by'].values()), r['stats']['nsteps'] - r['stats']['nfailed'])
        from kompartment.engine.solverset import variable_order
        ref = variable_order(f, grid, np.array([1.0, 0.0, 0.0]), {'rtol': 1e-10, 'abstol': 1e-14})
        for k in range(grid.size):
            d = np.abs(r['y'][k] - ref['y'][k]) / (1e-10 + 1e-6 * np.abs(ref['y'][k]))
            self.assertLess(float(np.max(d)), 50, f't = {grid[k]}')

    def test_the_runner_hands_auto_the_tables_corners(self) -> None:
        """Through the runner, as the application's: a table of 12 points, the
        explicit methods landing on every corner, and one of 150, more than
        they land on, the NDF's run from the start -- that NDF run itself,
        here and there, which steps over the corners and is held to the
        application's as the NDF is (2.7 % apart in steps when written: 1814
        against 1864, the plain ndf's own difference on this model)."""
        import kompartment as kp

        def model(points: int, solver: str) -> Dict[str, Any]:
            m = kp.Model.new('Cornered')
            m.simulation.update(end_time=50, output_points=26, spacing='linear', rtol=1e-6, abstol=1e-10,
                                solver=solver)
            m.add_compartment('A', initial='100')
            m.add_compartment('B')
            m.add_lookup('Flow', [[50 * i / (points - 1), 0.1 + 0.05 * (i % 3)] for i in range(points)])
            m.add_transfer('A', 'B', rate='Flow')
            m.add_transfer('B', None, rate='0.02')
            return json.loads(json.dumps(m.to_dict()))
        for points, expected in ((12, ['Vern7']), (150, ['NDF'])):
            raw = model(points, 'auto')
            with self.subTest(points=points):
                js = engine('run', model=raw, overrides={})
                res = run_project(Project(json.loads(json.dumps(raw))), compiled=False)
                self.assertEqual(list(res.stats['steps_by']), expected)
                self.assertEqual(list(js['stats']['stepsBy']), expected)
                if points == 12:
                    self.assertEqual({k: res.stats[k] for k in COUNTS[:3]}, {k: js['stats'][k] for k in COUNTS[:3]})
                else:
                    plain = model(points, 'ndf')
                    js_ndf = engine('run', model=plain, overrides={})
                    ndf = run_project(Project(json.loads(json.dumps(plain))), compiled=False)
                    for stats, by, of in ((res.stats, res.stats['steps_by'], ndf.stats),
                                          (js['stats'], js['stats']['stepsBy'], js_ndf['stats'])):
                        self.assertEqual(stats['nsteps'], of['nsteps'] + of['nfailed'])
                        self.assertEqual(by['NDF'], of['nsteps'])
                    self.assertTrue(within(ndf.stats['nsteps'], js_ndf['stats']['nsteps'], 0.05, 2))
                outs = res.outputs()
                for o, mine, theirs in zip(outs, res.series_many(outs), js['columns']):
                    if o['kind'] == 'compartment':
                        theirs = np.array(theirs, dtype=float)
                        self.assertLess(float(np.max(np.abs(mine - theirs))) / float(np.max(np.abs(theirs))), 1e-5)

    def test_the_table_corners_are_the_applications(self) -> None:
        """``System.table_corners`` against the application's ``tableCorners``:
        linear, nearest, cyclic, a function of its argument, the limit, two
        points a rounding apart -- and the bundled examples."""
        from kompartment.engine.builder import build_system
        raw = {
            'name': 'corners', 'simulation': {'start_time': 0, 'end_time': 100, 'output_points': 11,
                                              'spacing': 'linear', 'rtol': 1e-6, 'abstol': 1e-9},
            'index_lists': [], 'expressions': [], 'inflows': [], 'parameters': [],
            'compartments': [{'name': 'A', 'initial': '1', 'index_lists': []}],
            'transfers': [{'name': 'T', 'from': 'A', 'to': None, 'rate': 'L1 * 1e-3 + L2 * 1e-3 + L3 * 1e-3',
                           'index_lists': []}],
            'lookups': [
                {'name': 'L1', 'interpolation': 'linear', 'points': [[0, 1], [10, 2], [20, 1.5]]},
                {'name': 'L2', 'interpolation': 'nearest', 'points': [[10, 1], [30, 2]]},
                {'name': 'L3', 'interpolation': 'linear', 'cyclic': True, 'points': [[0, 0], [10, 1], [25, 0]]},
                {'name': 'F', 'interpolation': 'linear', 'argument': 'x', 'points': [[0, 0], [33, 1], [66, 0]]},
            ],
        }
        spans = [[0, 100, None], [100, 0, None], [15, 55, None], [0, 100, 7], [0, 100, 8], [-60, 260, None],
                 [-60, 260, 30], [0.5, 1e4, 1000]]
        stepped = json.loads(json.dumps(raw))
        stepped['lookups'][0]['points'] = [[0, 1], [10, 2], [10 + 1e-12, 2.5], [20, 1.5]]
        models = [raw, stepped] + [example(n) for n in ('lookup-driver', 'recorders', 'post-processing')]
        for model in models:
            with self.subTest(model=model['name']):
                js = engine('corners', model=model, spans=spans)['corners']
                system = build_system(Project(json.loads(json.dumps(model))), jacobian=False)
                mine = [system.table_corners(a, b, math.inf if limit is None else limit) for a, b, limit in spans]
                self.assertEqual(mine, js)
        system = build_system(Project(json.loads(json.dumps(raw))), jacobian=False)
        self.assertEqual(system.table_corners(0, 100), [10, 20, 25, 35, 50, 60, 75, 85])
        self.assertIsNone(system.table_corners(0, 100, 7))


@needs_app
class BitIdentity(unittest.TestCase):
    """With the package's dense LU and V8's pow put back, a run is the
    application's to the last bit: every count, every accepted step, every row."""

    def test_the_problems(self) -> None:
        cases = [(name, s, dict(BASE[name])) for name in ('robertson', 'vdp', 'hires', 'event', 'event_rising',
                                                          'two_events', 'forced') for s in SOLVERS]
        cases += [('nonneg', s, {**BASE['nonneg'], 'matrix': 'dense'}) for s in SOLVERS]
        cases += [('robertson', s, {**BASE['robertson'], 'errorNorm': 'max', 'autoUpdateAbsTol': True})
                  for s in SOLVERS]
        theirs = bridge('solve', runs=[{'problem': n, 'solver': s, 'opts': o} for n, s, o in cases])['runs']
        runs = until_known([(lambda n=n, s=s, o=o: run_here(n, s, o)) for n, s, o in cases])
        for (name, solver, opts), js, mine in zip(cases, theirs, runs):
            with self.subTest(problem=name, solver=solver, opts=opts):
                self.assertEqual({k: mine['stats'][k] for k in COUNTS}, {k: js['stats'][k] for k in COUNTS})
                self.assertEqual(mine['accepted'], js['accepted'])
                self.assertEqual(mine['t'], js['t'])
                self.assertEqual(mine['y'], js['y'])
                self.assertEqual(mine['stopped'] and mine['stopped']['t'], js['stopped'] and js['stopped']['t'])

    def test_what_came_with_the_default_algorithm(self) -> None:
        """The five new methods the same way, the switch's own account and
        GMRES's iterations included; and, through the package itself, the
        switch taking the matrix-free FBDF on 600 states."""
        # Rosenbrock23 only where it takes few steps: each round of until_known
        # takes a run one pow further along, and at rtol 1e-6 this
        # second-order method takes 2700 steps on van der Pol and 15 900 on
        # the forcing, more than its rounds reach (the next test has them).
        cases = [(name, s, dict(BASE[name])) for name in ('two_events', 'event_rising') for s in NEW if s != 'auto']
        cases += [(name, s, dict(BASE[name])) for name in ('vdp', 'forced') for s in NEW
                  if s not in ('auto', 'rosenbrock23')]
        cases += [('robertson', s, dict(BASE['robertson'])) for s in ('auto_julia', 'fbdf_krylov', 'rosenbrock23')]
        cases += [('hires', s, dict(BASE['hires'])) for s in ('auto_julia', 'fbdf_krylov')]
        # The chains dense, as nonneg is above: sparse, they would be
        # factorised by SuperLU here and by the package's own sparse LU there.
        # The chain of 120 switches 23 times at 1e-3 (Switching has it at 1e-6).
        cases += [('vdp1000', 'auto_julia', {'rtol': 1e-3, 'abstol': 1e-6}),
                  ('chain', 'auto_julia', {**BASE['chain'], 'matrix': 'dense'}),
                  ('chain120', 'auto_julia', {'rtol': 1e-3, 'abstol': 1e-6, 'matrix': 'dense'}),
                  ('kepler', 'vern7', {'rtol': 1e-8, 'abstol': 1e-10}),
                  ('nonneg', 'auto_julia', {**BASE['nonneg'], 'matrix': 'dense'}),
                  ('robertson', 'auto_julia', {**BASE['robertson'], 'errorNorm': 'max', 'autoUpdateAbsTol': True})]
        theirs = bridge('solve', runs=[{'problem': n, 'solver': s, 'opts': o} for n, s, o in cases])['runs']
        packaged = [{'problem': 'heat', 'alg': 'DefaultODEAlgorithm', 'opts': {'reltol': 1e-6, 'abstol': 1e-9}},
                    {'problem': 'idle', 'alg': 'DefaultODEAlgorithm', 'algOptions': {'stillIsStiff': True},
                     'opts': {'matrix': 'dense'}}]
        their_packaged = bridge('package', runs=packaged)['runs']
        attempts = [(lambda n=n, s=s, o=o: run_here(n, s, o)) for n, s, o in cases]
        attempts += [(lambda r=r: run_package(r['problem'], r['alg'], r.get('algOptions'), r['opts']))
                     for r in packaged]
        runs = until_known(attempts)
        for (name, solver, opts), js, mine in zip(cases, theirs, runs):
            with self.subTest(problem=name, solver=solver, opts=opts):
                self.assertEqual({k: mine['stats'][k] for k in COUNTS}, {k: js['stats'][k] for k in COUNTS})
                self.assertEqual(mine['stats'].get('steps_by'), js['stats'].get('stepsBy'))
                self.assertEqual(mine['stats'].get('switches'), js['stats'].get('switches'))
                self.assertEqual(mine['stats'].get('krylov_iters'), js['stats'].get('krylovIters'))
                self.assertEqual(mine['accepted'], js['accepted'])
                self.assertEqual(mine['t'], js['t'])
                self.assertEqual(mine['y'], js['y'])
                self.assertEqual(mine['stopped'] and mine['stopped']['t'], js['stopped'] and js['stopped']['t'])
        for r, js, mine in zip(packaged, their_packaged, runs[len(cases):]):
            with self.subTest(**r):
                self.assertEqual(mine['algChoice'], js['algChoice'])
                for key in ('naccept', 'nreject', 'nf', 'nsolve', 'stepsBy', 'switches', 'switchLog', 'krylovIters'):
                    self.assertEqual(mine['stats'].get(key), js['stats'].get(key), key)
                self.assertEqual(mine['t'], js['t'])
                self.assertEqual(mine['u'], js['u'])

    def test_what_auto_hands_the_ndf_is_the_applications(self) -> None:
        """``auto``: the package stopping for the NDF, where and with what
        state; a run that stays explicit, corners and events included, bit
        for bit; and a run handed on, up to the hand-off. From there it is the
        NDF's, whose arithmetic is this engine's own (ndf.py's ``**`` and
        LU), held to the application's by Problems and Examples."""
        packaged = HAND_OFF_RUNS[:5]
        their_packaged = bridge('package', runs=packaged)['runs']
        explicit = [('forced', 'auto', {**BASE['forced'], 'corners': [2.5, 5.0, 7.5]}),
                    ('event', 'auto', {**BASE['event'], 'corners': [0.3, 0.7, 2.0]}),
                    ('two_events', 'auto', dict(BASE['two_events']))]
        handed = [('robertson', 'auto', dict(BASE['robertson'])),
                  ('vdp1000', 'auto', {'rtol': 1e-3, 'abstol': 1e-6}),
                  ('chain', 'auto', {**BASE['chain'], 'matrix': 'dense'}),
                  ('nonneg', 'auto', {**BASE['nonneg'], 'matrix': 'dense'})]
        cases = explicit + handed
        theirs = bridge('solve', runs=[{'problem': n, 'solver': s, 'opts': o} for n, s, o in cases])['runs']
        attempts = [(lambda r=r: run_package(r['problem'], r['alg'], r.get('algOptions'), r['opts']))
                    for r in packaged]
        attempts += [(lambda n=n, s=s, o=o: run_here(n, s, o)) for n, s, o in cases]
        runs = until_known(attempts)
        for r, js, mine in zip(packaged, their_packaged, runs):
            with self.subTest(**r):
                for key in ('naccept', 'nreject', 'nf', 'stepsBy', 'switches'):
                    self.assertEqual(mine['stats'].get(key), js['stats'].get(key), key)
                self.assertEqual((mine['retcode'], mine['message']), (js['retcode'], js['message']))
                self.assertEqual(mine['handOff'], js['handOff'])
                self.assertEqual(mine['t'], js['t'])
                self.assertEqual(mine['u'], js['u'])
        for (name, solver, opts), js, mine in zip(cases, theirs, runs[len(packaged):]):
            with self.subTest(problem=name, opts=opts):
                by, by_js = mine['stats']['steps_by'], js['stats']['stepsBy']
                if (name, solver, opts) in explicit:
                    self.assertEqual(len(by), 1)
                    self.assertEqual({k: mine['stats'][k] for k in COUNTS}, {k: js['stats'][k] for k in COUNTS})
                    self.assertEqual(by, by_js)
                    self.assertEqual(mine['accepted'], js['accepted'])
                    self.assertEqual(mine['t'], js['t'])
                    self.assertEqual(mine['y'], js['y'])
                    continue
                # Handed on: the explicit method's steps, and every row up to
                # the hand-off, which is its last accepted step.
                first = list(by)[0]
                self.assertEqual((list(by)[1], list(by_js)), ('NDF', [first, 'NDF']))
                self.assertEqual(by[first], by_js[first])
                k = by[first]
                self.assertEqual(mine['accepted'][:k], js['accepted'][:k])
                at = mine['accepted'][k - 1]
                rows = sum(1 for t in mine['t'] if t <= at)
                self.assertEqual(mine['t'], js['t'])
                self.assertEqual(mine['y'][:rows], js['y'][:rows])

    def test_the_audit_s_rows_whole(self) -> None:
        """With the mass-balance audit on, the methods that are handed its
        budgets' rows whole -- a Rosenbrock, FBDF, Radau, DifferentialEquations.jl's
        switch -- on matrices that hold them, the application's runs step for
        step and bit for bit (dense, as the chains above)."""
        cases = [('decay-chain', 'fbdf'), ('decay-chain', 'auto_julia'), ('decay-chain', 'radau5'),
                 ('audit', 'rodas5p'), ('audit', 'auto_julia')]
        models = []
        for name, solver in cases:
            m = audit_model(solver) if name == 'audit' else example(name)
            m['simulation'].update(mass_balance=True, solver=solver, matrix='dense')
            models.append(m)
        with asking_v8_at_every_call():
            results = [run_project(Project(json.loads(json.dumps(m))), compiled=False) for m in models]
        for (name, solver), m, res in zip(cases, models, results):
            with self.subTest(model=name, solver=solver):
                self.assertEqual(res.jacobian['budgetRows'], 'exact')
                js = engine('run', model=m, overrides={})
                for key in ('nsteps', 'nfailed', 'nfevals', 'npds', 'ndecomps', 'nsolves'):
                    self.assertEqual(res.stats.get(key), js['stats'].get(key), key)
                outs = res.outputs()
                for o, mine, theirs in zip(outs, res.series_many(outs), js['columns']):
                    if o['kind'] == 'compartment':
                        self.assertEqual(mine.tolist(), theirs, o['label'])

    def test_runs_too_long_for_until_known(self) -> None:
        """Rosenbrock23 where it takes thousands of steps, and the chain of
        120 at reltol 1e-6 switching near a thousand times (Switching holds
        the platform's run of it to the application's spread), with V8's pow
        asked at every call."""
        cases = [(name, 'rosenbrock23', dict(BASE[name])) for name in ('vdp', 'forced', 'hires')]
        cases += [('chain120', 'auto_julia', {'rtol': 1e-6, 'abstol': 1e-9, 'matrix': 'dense'})]
        theirs = bridge('solve', runs=[{'problem': n, 'solver': s, 'opts': o} for n, s, o in cases])['runs']
        # Arguments no run meets, so that the answers are the Node process's.
        probe = [(1.2345678912345, 0.3141592653589793), (3.3e-7, 0.123456789), (0.987654321, -7.25)]
        told = bridge('pow', pairs=[list(p) for p in probe])['values']
        with asking_v8_at_every_call():
            self.assertEqual([_js.jpow(x, y) for x, y in probe], [float(v) for v in told])
            runs = [run_here(n, s, o) for n, s, o in cases]
        for (name, solver, opts), js, mine in zip(cases, theirs, runs):
            with self.subTest(problem=name, solver=solver, opts=opts):
                self.assertNotIn('error', mine)
                self.assertEqual({k: mine['stats'][k] for k in COUNTS}, {k: js['stats'][k] for k in COUNTS})
                self.assertEqual(mine['stats'].get('steps_by'), js['stats'].get('stepsBy'))
                self.assertEqual(mine['stats'].get('switches'), js['stats'].get('switches'))
                self.assertEqual(mine['accepted'], js['accepted'])
                self.assertEqual(mine['t'], js['t'])
                self.assertEqual(mine['y'], js['y'])
        self.assertGreater(runs[-1]['stats']['switches'], 500)

    def test_bundled_examples_through_the_runner(self) -> None:
        """The whole path: the runner's options, the Jacobian it hands over,
        non-negative compartments, a lookup table's corners, a terminal event
        and the segment after it, the recorders fed from the accepted steps."""
        cases = (('four-compartment', 'fbdf'), ('lookup-driver', 'rodas5p'),
                 ('recorders', 'rodas5p'), ('recorders', 'kencarp4'),
                 # The new ones: Vern7 and its event (the run Examples holds
                 # to 500 rtol is this one exactly), Rosenbrock23 over the
                 # corners, the switch deciding by verdicts at its threshold,
                 # GMRES on the landscape's 28 states.
                 ('recorders', 'auto_julia'), ('lookup-driver', 'rosenbrock23'), ('decay-chain', 'auto_julia'),
                 ('landscape', 'fbdf_krylov'),
                 # This tool's switching solver: Vern7 throughout, landing on
                 # the tables' corners; and Vern7 handing the run to the NDF.
                 ('lookup-driver', 'auto'), ('recorders', 'auto'), ('decay-chain', 'auto'),
                 ('waste-packages', 'auto'))
        models = []
        for name, solver in cases:
            model = example(name)
            model['simulation']['solver'] = solver
            models.append(model)
        results = until_known([(lambda m=m: run_project(Project(json.loads(json.dumps(m))))) for m in models])
        for (name, solver), res in zip(cases, results):
            with self.subTest(example=name, solver=solver):
                js = engine('run', model=example(name), overrides={'solver': solver})
                for key in ('nsteps', 'nfailed', 'nfevals', 'npds', 'ndecomps', 'nsolves', 'events'):
                    self.assertEqual(res.stats.get(key), js['stats'].get(key), key)
                self.assertEqual(res.stats.get('steps_by'), js['stats'].get('stepsBy'))
                self.assertEqual(res.stats.get('switches'), js['stats'].get('switches'))
                self.assertEqual(res.stats.get('krylov_iters'), js['stats'].get('krylovIters'))
                outs = res.outputs()
                self.assertEqual([o['label'] for o in outs], js['labels'])
                self.assertEqual(res.t.tolist(), js['t'])
                # A run `auto` handed to the NDF is the application's to the
                # hand-off and takes its steps after it, read off this
                # engine's own NDF arithmetic: 5e-13 apart when written.
                handed = 'NDF' in (res.stats.get('steps_by') or {})
                for o, mine, theirs in zip(outs, res.series_many(outs), js['columns']):
                    if o['kind'] != 'compartment':
                        continue
                    if not handed:
                        self.assertEqual(mine.tolist(), theirs, o['label'])
                        continue
                    theirs = np.array(theirs, dtype=float)
                    scale = float(np.max(np.abs(theirs))) or 1.0
                    self.assertLess(float(np.max(np.abs(np.asarray(mine) - theirs))) / scale, 1e-10, o['label'])


# The share of the application's steps each example may differ by, and why.
# Measured 2026-09-25 under Python 3.12 (numpy 2.3, scipy 1.16) and 3.9 (numpy
# 1.26, scipy 1.12); each of the runs that differed was put through
# BitIdentity's machinery and came out the application's step for step.
STEP_SHARE = {
    # FBDF differs by 2 % (641 against 654): its order and step come from
    # error estimates read off the history, which sit at rounding level on the
    # long plateau of a million-year run.
    'default': 0.03,
    # The lookup table's corners are stepped over, not stopped at: many
    # rejected steps (95 of 228 for Rodas5P), each decided on an estimate that
    # a last-bit difference moves. Up to 8.7 % measured (KenCarp4 under 3.9).
    'lookup-driver': 0.12,
    # FBDF has two step sequences here, about 920 steps and about 1300: in the
    # longer its order stays at 2 and 3 through the first fifty years. Which
    # one a run takes turns on the last bits -- in the application, 1 of 24
    # tolerances within 3e-8 of 1e-7 relative took the longer -- so the port
    # may take the other: 1305 against 915 when written (and 928 against
    # 1301 before 2026-09-25's changes to FBDF).
    'recorders': 0.45,
}

# The methods that came with the default algorithm, where one needs more than
# its example's share, measured 2026-10-03 (Python 3.12, numpy 2.3, scipy
# 1.16) and put through BitIdentity's machinery: the application's run.
NEW_STEP_SHARE = {
    # The switch from Vern7 to Rodas5P is decided by verdicts at its
    # threshold, and a last bit moves which: 403 steps against 447 (397 of
    # Vern7's and 4 of Rodas5P's against 322 and 121).
    ('decay-chain', 'auto_julia'): 0.2,
}

# The rows of a run that took other steps than the application's are held to
# 200 rtol; where one needs more, measured, explained and checked the same way.
ROW_BOUND = {
    # Vern7 -- and the switch, which is Vern7 here, at rtol 1e-7 -- steps over
    # the release's corner at t = 140. The port's run at exactly 1e-7 put a
    # step across it whose polynomial reads the next row 2e-5 out, 212 rtol
    # from the application's, which is 2.7e-6 out; nudged by 3e-9 relative,
    # thirty runs here and eight there all land between 7e-7 and 4e-6.
    ('recorders', 'vern7'): 500,
    ('recorders', 'auto_julia'): 500,
}

# farfield (1266 states) only with the quick methods: the application's
# RadauIIA5 takes half a minute there (its complex half is dense) and its
# TRBDF2 more than twenty-five; the switch and the matrix-free FBDF spend
# 200 000 evaluations of f in GMRES, half a minute there and most of one here.
FARFIELD = ('rodas5p', 'kencarp4', 'rosenbrock23', 'auto')

# Stiff from the first steps, where an explicit method needs over a million.
STIFF_EXAMPLES = ('biosphere', 'farfield')


def example_solvers(name: str) -> Tuple[str, ...]:
    """The methods an example is run with: every one, less those it takes too long."""
    if name == 'farfield':
        return FARFIELD
    return tuple(s for s in EVERY if not (s in EXPLICIT and name in STIFF_EXAMPLES))


@needs_app
class Examples(unittest.TestCase):
    def test_every_example_with_every_method(self) -> None:
        names = sorted(p.stem for p in (HERE.parent.parent / 'examples').glob('*.json'))
        self.assertIn('farfield', names)
        for name in names:
            model = example(name)
            rtol = float(model['simulation'].get('rtol', 1e-3))
            for solver in example_solvers(name):
                with self.subTest(example=name, solver=solver):
                    js = engine('run', model=model, overrides={'solver': solver})
                    m = json.loads(json.dumps(model))
                    m['simulation']['solver'] = solver
                    try:
                        res = run_project(Project(m))
                    except SolverError as e:
                        self.assertIn('error', js, str(e))
                        self.assertEqual(str(e), js['error'])
                        continue
                    self.assertNotIn('error', js)
                    if js['stats'].get('solver') is not None or res.stats.get('solver') is not None:
                        self.assertEqual(res.stats.get('solver'), js['stats'].get('solver'))
                    n_js = js['stats'].get('nsteps')
                    if n_js is not None:
                        share = NEW_STEP_SHARE.get((name, solver), STEP_SHARE.get(name, STEP_SHARE['default']))
                        self.assertTrue(within(res.stats['nsteps'], n_js, share, 3),
                                        f"{res.stats['nsteps']} steps against {n_js}")
                        # The NDF `auto` hands a run to factorises sparsely
                        # with SuperLU here and its own LU there, and above
                        # 24 states rather than 64: its own matter, held to
                        # the application's in test_engine_parity.py.
                        handed = 'NDF' in (res.stats.get('steps_by') or {})
                        for key in ('sparse', 'fill'):
                            if key in js['stats'] and not handed:
                                self.assertEqual(res.stats.get(key), js['stats'][key], key)
                    # The switch used the same methods, every solve of the run summed.
                    if js['stats'].get('stepsBy') is not None or 'steps_by' in res.stats:
                        self.assertEqual(list(res.stats['steps_by']), list(js['stats']['stepsBy']))
                    outs = res.outputs()
                    self.assertEqual([o['label'] for o in outs], js['labels'])
                    self.assertEqual((res.t[0], res.t[-1]), (js['t'][0], js['t'][-1]))
                    if Project(model).solver_points:
                        # The rows include the solver's own steps: as many as it
                        # took, at times that part in the last digits.
                        share = STEP_SHARE.get(name, STEP_SHARE['default'])
                        self.assertTrue(within(len(res.t), len(js['t']), share, 3))
                    else:
                        # The requested times exactly; and an event's row, where each
                        # run located the crossing on its own step's interpolant --
                        # two step sequences put it within a few tolerances of each
                        # other (1.4e-6 relative at rtol 1e-7, Rodas5P under 3.9).
                        self.assertEqual(len(res.t), len(js['t']))
                        asked = set(Project(model).time_grid().tolist())
                        for mine_t, their_t in zip(res.t.tolist(), js['t']):
                            if their_t in asked:
                                self.assertEqual(mine_t, their_t)
                            else:
                                self.assertLessEqual(abs(mine_t - their_t), 100 * rtol * abs(their_t))
                    # Every row of every compartment. Each method reads its rows
                    # off its own interpolant, so two runs that took the same
                    # steps agree to rounding, and two whose step sequences
                    # parted each carry their own global error. The same count
                    # is not quite the same steps: over lookup-driver's corners
                    # a pow in the last bit moves a few of them, and Radau's rows
                    # there are 1.4 rtol apart at 113 steps each (the rest 0.14
                    # at most), held to 10; runs that took different numbers of
                    # steps are 57 rtol apart at worst (the same model,
                    # KenCarp4), held to 200. A run that also reports the
                    # solver's own steps is compared at the times asked for.
                    same = n_js is None or res.stats.get('nsteps') == n_js
                    bound = (10 if same else ROW_BOUND.get((name, solver), 200)) * rtol
                    mine_t = res.t.tolist()
                    if Project(model).solver_points:
                        common = set(Project(model).time_grid().tolist()) & set(mine_t) & set(js['t'])
                        rows_mine = [i for i, t in enumerate(mine_t) if t in common]
                        rows_theirs = [i for i, t in enumerate(js['t']) if t in common]
                    else:
                        rows_mine = rows_theirs = list(range(len(js['t'])))
                    for o, mine, theirs in zip(outs, res.series_many(outs), js['columns']):
                        if o['kind'] != 'compartment':
                            continue
                        theirs = np.array(theirs, dtype=float)[rows_theirs]
                        mine = np.asarray(mine, dtype=float)[rows_mine]
                        scale = np.max(np.abs(theirs[np.isfinite(theirs)])) if np.isfinite(theirs).any() else 0.0
                        if scale == 0:
                            continue
                        self.assertLess(float(np.max(np.abs(mine - theirs))) / scale, bound, o['label'])


if __name__ == '__main__':
    unittest.main()
