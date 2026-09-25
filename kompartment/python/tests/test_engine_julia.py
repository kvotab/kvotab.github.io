"""The six ported DifferentialEquations.jl solvers against the application's.

``kompartment.engine.solvers.julia`` ports ``src/ode/julia/`` and its adapter
``src/ode/julia-solvers.js``. Four kinds of check, all against the
application's own code run in Node:

* ``Tables``: what has no floating point to argue about -- the tableaux, the
  reverse Cuthill-McKee ordering, the colouring of the Jacobian's columns --
  is the application's exactly.
* ``Problems``: test problems defined in ``tests/node/julia_solvers.mjs`` and
  mirrored here expression for expression, so that ``f`` and the Jacobian are
  the same functions to the last bit (Robertson, a decay chain with Bateman's
  closed form, van der Pol, HIRES, terminal events, non-negative states, a
  clock-driven forcing, a chain restarted late in a run just after a jump),
  through all six methods and a spread of options:
  every count the adapter reports, the rows, where a run stopped, the errors.
* ``BitIdentity``: the same runs, and two bundled examples through the
  runner, with the two things this port does differently from the package
  put back -- a transcription of the package's dense LU in place of LAPACK's,
  and V8's own ``Math.pow`` values (asked of Node for every argument a run
  meets) in place of the C library's ``pow`` -- are the application's step
  for step, bit for bit.
* ``Examples``: every bundled example with each of the six ids, through the
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

from helpers import HERE, NODE, SRC, example, needs_app

from kompartment.engine.jacobian import Pattern
from kompartment.engine.project import Project
from kompartment.engine.runner import run as run_project
from kompartment.engine.solvers import SolverError
from kompartment.engine.solvers import julia as ported
from kompartment.engine.solvers.julia import _js, controller, linalg, newton
from kompartment.engine.solvers.julia.jacobian import colour_columns
from kompartment.engine.solvers.julia.linalg import reverse_cuthill_mckee
from kompartment.engine.solvers.julia.methods import fbdf as fbdf_module
from kompartment.engine.solvers.julia.methods import qndf as qndf_module
from kompartment.engine.solvers.julia.methods import radau as radau_module
from kompartment.engine.solvers.julia.methods import tableaus

SOLVERS = ('fbdf', 'qndf', 'rodas5p', 'radau5', 'kencarp4', 'trbdf2')
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


def within(mine: float, theirs: float, share: float, least: float) -> bool:
    return abs(mine - theirs) <= max(least, share * abs(theirs))


def counts_agree(mine: Dict[str, Any], theirs: Dict[str, Any]) -> List[str]:
    """What is outside the margin: steps within max(2, 1 %), and every other
    count within the same share or two steps' worth of it."""
    bad = []
    steps = theirs['nsteps'] or 1
    for key in COUNTS:
        a, b = mine[key], theirs[key]
        per_step = abs(b) / steps
        least = 2 if key == 'nsteps' else 2 * max(1.0, per_step)
        if not within(a, b, 0.01, least):
            bad.append(f'{key} {a} against {b}')
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

    patches = [mock.patch.object(m, 'jpow', v8_pow)
               for m in (_js, controller, newton, fbdf_module, qndf_module, radau_module)]
    patches += [mock.patch.object(linalg.DenseLU, 'factor', PackageDenseLU.factor),
                mock.patch.object(linalg.DenseLU, 'solve', PackageDenseLU.solve)]
    for p in patches:
        p.start()
    try:
        yield missing
    finally:
        for p in reversed(patches):
            p.stop()


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
    """Every problem with every method, then the options the adapter maps."""
    runs = [(name, s, dict(opts)) for name, opts in BASE.items() for s in SOLVERS]
    rob = BASE['robertson']
    variants: List[Tuple[str, Tuple[str, ...], Dict[str, Any]]] = [
        ('robertson', SOLVERS, {**rob, 'errorNorm': 'max'}),
        ('robertson', SOLVERS, {'rtol': 1e-5, 'abstol': [1e-8, 1e-12, 1e-8]}),
        ('hires', SOLVERS, {**BASE['hires'], 'autoUpdateAbsTol': True}),
        ('chain', SOLVERS, {**BASE['chain'], 'matrix': 'dense'}),
        ('hires', SOLVERS, {**BASE['hires'], 'matrix': 'sparse'}),
        ('hires', SOLVERS, {**BASE['hires'], 'matrix': 'refactor'}),
        ('chain', SOLVERS, {**BASE['chain'], 'jacobian': 'none'}),
        ('chain', SOLVERS, {**BASE['chain'], 'jacobian': 'declined'}),
        ('vdp', SOLVERS, {**BASE['vdp'], 'jacobian': 'none'}),
        ('vdp', SOLVERS, {**BASE['vdp'], 'hmax': 0.05}),
        ('robertson', SOLVERS, {**rob, 'h0': 1e-5}),
        ('robertson', ('fbdf', 'qndf'), {**rob, 'maxOrder': 3}),
        ('robertson', ('fbdf', 'qndf'), {**rob, 'minOrder': 2, 'maxOrder': 4.0}),
        ('robertson', ('qndf', 'fbdf'), {**rob, 'bdf': True}),
        ('hires', NEWTON, {**BASE['hires'], 'newtonKappa': 1e-2}),
        ('hires', NEWTON, {**BASE['hires'], 'maxJacAge': 5}),
        ('robertson', SOLVERS, {**rob, 'belowTolRun': 3}),
        ('robertson', SOLVERS, {**rob, 'endsOnly': True}),
        ('event', SOLVERS, {**BASE['event'], 'endsOnly': True}),
        ('robertson', SOLVERS, {**rob, 'maxSteps': 40}),
        ('hires', SOLVERS, {**BASE['hires'], 'abortAfter': 7}),
        ('robertson', ('rodas5p', 'fbdf'), {**rob, 'grid': [0.5, 0.5]}),
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
                'trbdf2': tableaus.TRBDF2, 'kencarp4': tableaus.KENCARP4}
        snake = {'errorOrder': 'error_order', 'interpOrder': 'interp_order'}
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
                self.assertEqual(mine['stats']['fill'], theirs['stats']['fill'])
                self.assertEqual(counts_agree(mine['stats'], theirs['stats']), [])
                exact += all(mine['stats'][k] == theirs['stats'][k] for k in COUNTS)
        # The margin is for the runs a last-bit difference reaches (see the
        # module's docstring); most runs are the application's exactly -- 96 %
        # when this was written -- and a port that had drifted would not be.
        self.assertGreater(total, 150)
        self.assertGreaterEqual(exact / total, 0.85, f'{exact} of {total} runs have every count the same')

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
                tol = 1e-4 if solver == 'trbdf2' else 1e-6
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
        self.assertEqual(seen, 6)

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
        self.assertEqual(failures, 6 + 6 + 2)

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

    def test_bundled_examples_through_the_runner(self) -> None:
        """The whole path: the runner's options, the Jacobian it hands over,
        non-negative compartments, a lookup table's corners, a terminal event
        and the segment after it, the recorders fed from the accepted steps."""
        cases = (('four-compartment', 'fbdf'), ('lookup-driver', 'rodas5p'),
                 ('recorders', 'rodas5p'), ('recorders', 'kencarp4'))
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
                outs = res.outputs()
                self.assertEqual([o['label'] for o in outs], js['labels'])
                self.assertEqual(res.t.tolist(), js['t'])
                for o, mine, theirs in zip(outs, res.series_many(outs), js['columns']):
                    if o['kind'] == 'compartment':
                        self.assertEqual(mine.tolist(), theirs, o['label'])


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

# farfield (1266 states) only with the two quick methods: the application's
# RadauIIA5 takes half a minute there (its complex half is dense) and its
# TRBDF2 more than twenty-five.
FARFIELD = ('rodas5p', 'kencarp4')


@needs_app
class Examples(unittest.TestCase):
    def test_every_example_with_every_method(self) -> None:
        names = sorted(p.stem for p in (HERE.parent.parent / 'examples').glob('*.json'))
        self.assertIn('farfield', names)
        for name in names:
            model = example(name)
            rtol = float(model['simulation'].get('rtol', 1e-3))
            for solver in (FARFIELD if name == 'farfield' else SOLVERS):
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
                        share = STEP_SHARE.get(name, STEP_SHARE['default'])
                        self.assertTrue(within(res.stats['nsteps'], n_js, share, 3),
                                        f"{res.stats['nsteps']} steps against {n_js}")
                        for key in ('sparse', 'fill'):
                            if key in js['stats']:
                                self.assertEqual(res.stats.get(key), js['stats'][key], key)
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
                    bound = (10 if same else 200) * rtol
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
