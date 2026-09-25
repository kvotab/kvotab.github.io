"""Fitting a model to numbers somebody already knows: the optimisers.

A port of the application's ``src/domain/optimise.js``. The question this
answers is the other way round from a run: not *what does this model give*,
but *what would the inputs have to be for it to give this*. A measured
concentration, a dose an assessment has to match, a release rate calibrated
against a field study -- each is one or more endpoints with a value they are
supposed to come out at, and a handful of parameters allowed to move between
bounds until they do. :mod:`kompartment.engine.calibrate` is the other half:
what one evaluation of the model *is*.

**What is minimised** is the sum of weighted squared residuals
(:func:`objective_of`), each residual measured on the target's own
:data:`SCALES` -- ``absolute`` (got - want), ``relative`` (divided by the
target; the default) or ``log`` (the log of the ratio).

**The algorithms** (:data:`METHODS`), all derivative-free in the model,
bound-constrained, deterministic given a seed, and reporting after every
evaluation:

* :func:`nelder_mead` -- a simplex of ``n + 1`` points; local, few evaluations;
* :func:`levenberg_marquardt` -- least squares on a finite-difference
  Jacobian of the residuals; fastest near a solution;
* :func:`differential_evolution` -- ``rand/1/bin``; slow, and the only
  global one.

**The same numbers as the application.** Every step is the application's
arithmetic in the application's order: the simplex, the Gauss elimination and
the population are plain double-precision loops, the random stream is
:func:`kompartment.stats.sample.rng` (mulberry32, bit for bit), a point is
recognised as seen before by the same ``toPrecision(12)`` text, and the
logarithmic space and scale use V8's own ``Math.log`` and ``Math.exp``. Run on
the same function, the three methods here visit the same points in the same
order and stop at the same evaluation as the application's.

Faithful to a fault, too; what the application does that it probably should
not is done here as well and listed in :data:`KNOWN_QUIRKS`.

References: Nelder & Mead 1965; Marquardt 1963; Storn & Price 1997.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ..errors import KompartmentError
from .pdf import (
    _MISSING, _exp, _is_finite_num, _is_num, _js_str, _log, _prop, _to_number, _to_precision, _truthy,
)
from .sample import rng

__all__ = ['OptimiseError', 'SCALES', 'SPACES', 'METHODS', 'objective_of', 'entry_of', 'nelder_mead',
           'levenberg_marquardt', 'differential_evolution', 'KNOWN_QUIRKS']

#: What the application does here that it perhaps should not, and this port
#: does as well (so that a run here is a run there).
KNOWN_QUIRKS = (
    'Nelder-Mead keeps the unclamped points in its simplex (only the evaluation is '
    'clamped), so its centroid can lie outside the box.',
)


class OptimiseError(KompartmentError):
    """An optimisation that cannot start ('Nothing to vary.'), or -- inside the
    optimisers, where it is caught -- one being stopped ('stopped', 'budget')."""


def _lookup(table: Mapping[str, Any], key: Any) -> Any:
    """``entryOf(table, key)``: the table's own entry for the key made a string,
    or ``_MISSING`` -- never a member every JavaScript object inherits, which is
    how a scale named 'toString' used to be found and then fail."""
    k = key if isinstance(key, str) else _js_str(key)
    return table[k] if k in table else _MISSING


def entry_of(table: Mapping[str, Any], key: Any) -> Any:
    """``entryOf``: the table's own entry for ``key``, or None."""
    found = _lookup(table, key)
    return None if found is _MISSING else found


def _member(entry: Any, name: str, what: str) -> Any:
    """``entry.name`` for an entry found by :func:`_lookup`."""
    return entry[name]


def _aborted(signal: Any) -> bool:
    """``signal?.aborted``: an object with an ``aborted`` attribute, a mapping with
    that key, or a callable answering whether to stop."""
    if signal is None or signal is _MISSING:
        return False
    if callable(signal):
        return _truthy(signal())
    if isinstance(signal, Mapping):
        return _truthy(signal.get('aborted'))
    return _truthy(getattr(signal, 'aborted', False))


# ---------------------------------------------------------------------------
# How a residual is measured, and how a variable moves.
# ---------------------------------------------------------------------------

def _relative(got: float, want: float) -> float:
    if want == 0:
        return got
    return (got - want) / abs(want)


def _log_ratio(got: float, want: float) -> float:
    if not (got > 0) or not (want > 0):
        return math.nan
    return _log(got) - _log(want)


#: How a residual is measured, by the key a target stores.
SCALES: Dict[str, Dict[str, Any]] = {
    'absolute': {
        'label': 'absolute',
        'blurb': 'got − want. For a quantity whose own scale is the point.',
        'of': lambda got, want: got - want,
    },
    'relative': {
        'label': 'relative',
        'blurb': 'divided by the target, so endpoints in different units weigh alike.',
        'of': _relative,
    },
    'log': {
        'label': 'logarithmic',
        'blurb': ('the ratio, so being out by a factor of two counts the same at 1e−9 '
                  'as at 1e3. Needs both to be above zero.'),
        'of': _log_ratio,
    },
}

#: How a variable moves between its bounds, by the key a variable stores.
SPACES: Dict[str, Dict[str, Any]] = {
    'linear': {
        'label': 'linear',
        'to': lambda v: v,
        'from': lambda u: u,
        'ok': lambda *_: True,
    },
    'log': {
        'label': 'logarithmic',
        'blurb': ('searched in the logarithm, which is how a rate constant known only '
                  'to within orders of magnitude has to be searched.'),
        'to': _log,
        'from': _exp,
        'ok': lambda lo, hi: lo > 0 and hi > 0,
    },
}


def _reading(readings: Sequence[Any], i: int) -> float:
    """``readings[i]`` as arithmetic reads it: missing is NaN."""
    if i >= len(readings):
        return math.nan
    v = readings[i]
    return float(v) if _is_num(v) else _to_number(v)


def objective_of(readings: Sequence[Any], targets: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The objective, from one set of endpoint readings: ``{'objective': sum of
    squares, 'residuals': [...]}``.

    Each target is ``{value, scale, weight}``: ``scale`` a key of
    :data:`SCALES` (relative when it names none), ``weight`` a positive number
    (1 otherwise) that multiplies the square. A residual that is not a number
    -- a model that did not produce one there -- counts as a miss of 1e6
    rather than as NaN, which would make every comparison false and the search
    wander.
    """
    total = 0.0
    residuals: List[float] = []
    for i, t in enumerate(targets):
        found = _lookup(SCALES, _prop(t, 'scale'))
        scale = SCALES['relative'] if found is _MISSING else found
        w = _prop(t, 'weight')
        weight = w if _is_finite_num(w) and w > 0 else 1
        r = _member(scale, 'of', 'scale')(_reading(readings, i), _to_number(_prop(t, 'value')))
        use = math.sqrt(weight) * r if _is_finite_num(r) else 1e6
        residuals.append(use)
        total += use * use
    return {'objective': total, 'residuals': residuals}


# ---------------------------------------------------------------------------
# What every method shares.
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float, hi: float) -> float:
    """Into the bounds, whatever was asked for."""
    return lo if v < lo else (hi if v > hi else v)


def _clamp_all(x: Sequence[float], lower: Sequence[float], upper: Sequence[float]) -> List[float]:
    return [_clamp(x[i], lower[i], upper[i]) for i in range(len(x))]


def _numbers(values: Sequence[Any], n: int) -> List[float]:
    """``Float64Array.from(values)``, read to length ``n``: past the end is NaN,
    as an ``undefined`` element behaves in the arithmetic."""
    out = [_to_number(v) for v in list(values)[:n]]
    return out + [math.nan] * (n - len(out))


def _bounds(lower: Any, upper: Any, n: int) -> Any:
    if lower is None or upper is None:
        raise TypeError('lower and upper bounds are required')
    return _numbers(lower, n), _numbers(upper, n)


class _Budget:
    """Wraps an objective so it is counted, stoppable and never asked twice for
    the same point (``budgeted``).

    ``keep``, where given, is asked after each evaluation for whatever else of it
    the caller needs -- the residual vector Levenberg-Marquardt differences --
    and that is stored with the point and handed back by :meth:`kept` after
    every call, the remembered ones included.
    """

    def __init__(self, f: Callable[[List[float]], Any], max_evals: Any, on_step: Any, signal: Any,
                 keep: Optional[Callable[[], Any]] = None) -> None:
        self.f = f
        self.max_evals = _to_number(max_evals)
        self.on_step = on_step
        self.signal = signal
        self.keep = keep
        self.evals = 0
        self.best = math.inf
        self.best_x: Optional[List[float]] = None
        self.seen: Dict[str, Any] = {}
        self._kept: Any = None

    def call(self, x: Sequence[float]) -> float:
        if _aborted(self.signal):
            raise OptimiseError('stopped')
        if self.evals >= self.max_evals:
            raise OptimiseError('budget')
        # A simplex revisits a vertex it already knows; so does a population
        # that converged. Each of those is a whole integration.
        key = ','.join(_to_precision(v, 12) for v in x)
        had = self.seen.get(key)
        if had is not None:
            self._kept = had[1]
            return had[0]
        self.evals += 1
        fx = self.f(list(x))
        use = float(fx) if _is_finite_num(fx) else math.inf
        self._kept = self.keep() if self.keep is not None else None
        self.seen[key] = (use, self._kept)
        if use < self.best:
            self.best = use
            self.best_x = [float(v) for v in x]
        if self.on_step is not None:
            self.on_step({'evals': self.evals, 'fx': use, 'best': self.best, 'x': [float(v) for v in x],
                          'bestX': self.best_x})
        return use

    def kept(self) -> Any:
        """What ``keep`` gave for the point the last call was about."""
        return self._kept

    def done(self, reason: str) -> Dict[str, Any]:
        return {'x': list(self.best_x) if self.best_x is not None else None, 'fx': self.best,
                'evals': self.evals, 'reason': reason}


# ---------------------------------------------------------------------------
# Nelder-Mead.
# ---------------------------------------------------------------------------

def nelder_mead(f: Callable[[List[float]], float], start: Sequence[float], *, lower: Sequence[float] = None,
                upper: Sequence[float] = None, max_evals: Any = None, tol: Optional[float] = None,
                on_step: Optional[Callable[[Dict[str, Any]], Any]] = None, signal: Any = None) -> Dict[str, Any]:
    """Nelder-Mead, with the bounds applied by clamping (``nelderMead``).

    The textbook coefficients (reflect 1, expand 2, contract 0.5, shrink 0.5).
    The initial simplex steps each coordinate by 5% of its range, which for a
    bounded problem is a size that means something. Converged when the
    simplex's values agree to ``tol``, relatively.

    Returns ``{'x', 'fx', 'evals', 'reason'}``: the best point seen (``None``
    if none was), its value, how many evaluations it took, and why it stopped
    -- 'converged', 'budget' or 'stopped'. An option left out or given as
    None takes its default (400 evaluations, a tolerance of 1e-8).
    """
    n = len(start)
    if not n:
        raise OptimiseError('Nothing to vary.')
    max_evals = 400 if max_evals is None else max_evals
    tol = 1e-8 if tol is None else tol
    lower, upper = _bounds(lower, upper, n)
    budget = _Budget(f, max_evals, on_step, signal)

    def at(x: Sequence[float]) -> float:
        return budget.call(_clamp_all(x, lower, upper))

    raw_start = list(start)
    s0 = _numbers(raw_start, n)
    try:
        # The simplex: the start, then one step along each axis.
        simplex = [list(s0)]
        for i in range(n):
            x = list(s0)
            span = upper[i] - lower[i]
            step = span * 0.05 if span > 0 else abs(x[i]) * 0.05 + 1e-6
            x[i] = _clamp(x[i] + step, lower[i], upper[i])
            # A vertex that landed on top of another is no vertex: step the
            # other way rather than starting with a degenerate simplex.
            if _is_num(raw_start[i]) and x[i] == raw_start[i]:
                x[i] = _clamp(float(raw_start[i]) - step, lower[i], upper[i])
            simplex.append(x)
        fs = [at(x) for x in simplex]

        while True:
            # Sorted by value: the best first, the worst last. A stable sort,
            # as the application's comparator makes it.
            order = sorted(range(n + 1), key=lambda i: fs[i])
            simplex = [simplex[i] for i in order]
            fs = [fs[i] for i in order]

            # Converged when the simplex has collapsed onto one value.
            spread = abs(fs[n] - fs[0]) / (abs(fs[0]) + abs(fs[n]) + 1e-300)
            if spread < tol:
                return budget.done('converged')

            # The centroid of all but the worst.
            mid = [0.0] * n
            for i in range(n):
                for k in range(n):
                    mid[k] += simplex[i][k] / n

            def along(t: float) -> List[float]:
                return [mid[k] + t * (mid[k] - simplex[n][k]) for k in range(n)]

            xr = along(1)
            fr = at(xr)
            if fr < fs[0]:
                xe = along(2)
                fe = at(xe)
                if fe < fr:
                    simplex[n], fs[n] = xe, fe
                else:
                    simplex[n], fs[n] = xr, fr
                continue
            if fr < fs[n - 1]:
                simplex[n], fs[n] = xr, fr
                continue
            # Contract, on whichever side is better.
            xc = along(0.5) if fr < fs[n] else along(-0.5)
            fc = at(xc)
            if fc < min(fr, fs[n]):
                simplex[n], fs[n] = xc, fc
                continue
            # Nothing helped: pull everything halfway towards the best.
            for i in range(1, n + 1):
                x = [simplex[0][k] + 0.5 * (simplex[i][k] - simplex[0][k]) for k in range(n)]
                simplex[i] = _clamp_all(x, lower, upper)
                fs[i] = at(simplex[i])
    except OptimiseError as e:
        return budget.done(str(e))


# ---------------------------------------------------------------------------
# Levenberg-Marquardt.
# ---------------------------------------------------------------------------

def _solve(A: List[List[float]], b: List[float]) -> Optional[List[float]]:
    """Gauss with partial pivoting. None where the matrix is singular."""
    n = len(b)
    M = [list(A[i][:n]) + [b[i]] for i in range(n)]
    for c in range(n):
        p = c
        for i in range(c + 1, n):
            if abs(M[i][c]) > abs(M[p][c]):
                p = i
        if not (abs(M[p][c]) > 1e-300):
            return None
        M[c], M[p] = M[p], M[c]
        for i in range(c + 1, n):
            k = M[i][c] / M[c][c]
            if k == 0:
                continue
            row, pivot = M[i], M[c]
            for j in range(c, n + 1):
                row[j] -= k * pivot[j]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = M[i][n]
        for j in range(i + 1, n):
            s -= M[i][j] * x[j]
        x[i] = s / M[i][i]
    return x


def levenberg_marquardt(residuals: Callable[[List[float]], Sequence[float]], start: Sequence[float], *,
                        lower: Sequence[float] = None, upper: Sequence[float] = None, max_evals: Any = None,
                        tol: Optional[float] = None, on_step: Optional[Callable[[Dict[str, Any]], Any]] = None,
                        signal: Any = None) -> Dict[str, Any]:
    """Levenberg-Marquardt on a finite-difference Jacobian (``levenbergMarquardt``).

    ``residuals(x)`` gives the vector whose squares are being summed. Each
    iteration differences it once per variable, forward, by ``1e-6`` of the
    variable's range (or of ``|x| + 1`` for a variable with none), solves the
    damped normal equations ``(JᵀJ + λ·diag(JᵀJ)) dx = Jᵀr`` by Gauss
    elimination, and slides ``λ`` down by ten when a step helps and up by ten
    when it does not. Converged when a step gains less than ``tol``
    relatively, or no step helps.

    Returns ``{'x', 'fx', 'evals', 'reason'}``, as :func:`nelder_mead`. On an
    upper bound the difference is taken backwards, and never with a step the
    budget could not tell from the point itself (1e-9 of it).
    """
    n = len(start)
    if not n:
        raise OptimiseError('Nothing to vary.')
    max_evals = 400 if max_evals is None else max_evals
    tol = 1e-10 if tol is None else tol
    lower, upper = _bounds(lower, upper, n)
    last: List[Any] = [None]

    def f(x: List[float]) -> float:
        last[0] = residuals(x)
        s = 0.0
        for r in last[0]:
            s += r * r
        return s if _is_finite_num(s) else math.inf

    # The residuals are kept with the point they belong to, so a point the
    # budget answers from memory comes back with its own.
    budget = _Budget(f, max_evals, on_step, signal,
                     keep=lambda: [_to_number(v) for v in last[0]] if last[0] is not None else None)

    def eval_at(x: Sequence[float]) -> Any:
        fx = budget.call(_clamp_all(x, lower, upper))
        kept = budget.kept()
        return fx, (list(kept) if kept is not None else None)

    try:
        x = _clamp_all(_numbers(start, n), lower, upper)
        fx, r = eval_at(x)
        if r is None:
            return budget.done('no residuals')
        m = len(r)
        lam = 1e-3

        while True:
            # The Jacobian, column by column: one extra evaluation each.
            J: List[List[float]] = []
            for k in range(n):
                span = upper[k] - lower[k]
                h = max((span if span > 0 else abs(x[k]) + 1) * 1e-6, abs(x[k]) * 1e-9)
                xp = list(x)
                xp[k] = _clamp(x[k] + h, lower[k], upper[k])
                if xp[k] == x[k]:
                    xp[k] = _clamp(x[k] - h, lower[k], upper[k])
                step = xp[k] - x[k]
                if step == 0:
                    J.append([0.0] * m)
                    continue
                _, got_r = eval_at(xp)
                J.append([(_index(got_r, i) - r[i]) / step for i in range(m)])

            # JᵀJ and Jᵀr, which are n x n and n however long the residual
            # vector is.
            A = [[0.0] * n for _ in range(n)]
            g = [0.0] * n
            for a in range(n):
                for b in range(a, n):
                    s = 0.0
                    Ja, Jb = J[a], J[b]
                    for i in range(m):
                        s += Ja[i] * Jb[i]
                    A[a][b] = s
                    A[b][a] = s
                s = 0.0
                Ja = J[a]
                for i in range(m):
                    s += Ja[i] * r[i]
                g[a] = s

            stepped = False
            for _tries in range(12):
                M = []
                for a in range(n):
                    copy = list(A[a])
                    # Marquardt's own scaling: the damping follows the
                    # curvature rather than being the same in every direction.
                    copy[a] += lam * (A[a][a] if A[a][a] > 0 else 1)
                    M.append(copy)
                dx = _solve(M, g)
                if dx is None:
                    lam *= 10
                    continue
                trial = [x[k] - dx[k] for k in range(n)]
                got_fx, got_r = eval_at(trial)
                if got_fx < fx:
                    gain = (fx - got_fx) / (abs(fx) + 1e-300)
                    x = _clamp_all(trial, lower, upper)
                    fx = got_fx
                    r = got_r
                    lam = max(lam / 10, 1e-12)
                    stepped = True
                    if gain < tol:
                        return budget.done('converged')
                    break
                lam *= 10
                if lam > 1e12:
                    return budget.done('converged')
            if not stepped:
                return budget.done('converged')
    except OptimiseError as e:
        return budget.done(str(e))


def _index(values: Sequence[float], i: int) -> float:
    """``values[i]``, NaN past the end (``undefined`` in the arithmetic)."""
    return values[i] if i < len(values) else math.nan


# ---------------------------------------------------------------------------
# Differential evolution.
# ---------------------------------------------------------------------------

def differential_evolution(f: Callable[[List[float]], float], *, lower: Sequence[float] = None,
                           upper: Sequence[float] = None, start: Optional[Sequence[float]] = None,
                           pop_size: Any = 0, max_evals: Any = None, seed: Any = 1, F: Optional[float] = None,
                           CR: Optional[float] = None, on_step: Optional[Callable[[Dict[str, Any]], Any]] = None,
                           signal: Any = None) -> Dict[str, Any]:
    """Differential evolution, ``rand/1/bin`` (``differentialEvolution``).

    A population spread over the whole box -- ``pop_size``, or ten per
    variable between 8 and 60 -- each member crossed with another plus ``F``
    times the difference between two more, coordinate by coordinate with
    probability ``CR`` (and always in one). The start, where there is one, is
    the first member. The random stream is :func:`~kompartment.stats.sample.rng`
    seeded with ``seed``, so a run is the application's run. Converged when
    the whole population agrees to 1e-10, relatively.

    Returns ``{'x', 'fx', 'evals', 'reason'}``, as :func:`nelder_mead`.
    """
    if lower is None:
        raise TypeError('lower and upper bounds are required')
    n = len(lower)
    if not n:
        raise OptimiseError('Nothing to vary.')
    lower, upper = _bounds(lower, upper, n)
    max_evals = 2000 if max_evals is None else max_evals
    F = 0.7 if F is None else F
    CR = 0.9 if CR is None else CR
    # Ten per variable is the usual advice, floored so a one-variable problem
    # still has a population and capped so a ten-variable one still finishes.
    size = _to_number(pop_size)
    N = size if size > 3 else min(60, max(8, 10 * n))
    nxt = rng(seed)
    budget = _Budget(f, max_evals, on_step, signal)

    try:
        pop: List[List[float]] = []
        fit: List[float] = []
        first = _numbers(start, n) if _truthy(start) else None
        i = 0
        while i < N:
            if i == 0 and first is not None:
                x = [_clamp(first[k], lower[k], upper[k]) for k in range(n)]
            else:
                x = [lower[k] + nxt() * (upper[k] - lower[k]) for k in range(n)]
            pop.append(x)
            fit.append(budget.call(x))
            i += 1

        while True:
            i = 0
            while i < N:
                a = b = c = i
                while a == i:
                    a = math.floor(nxt() * N)
                while b == i or b == a:
                    b = math.floor(nxt() * N)
                while c == i or c == a or c == b:
                    c = math.floor(nxt() * N)
                # At least one coordinate always comes from the mutant, or a
                # trial could be its own parent and the population stall.
                must = math.floor(nxt() * n)
                pa, pb, pc, pi = pop[a], pop[b], pop[c], pop[i]
                trial = [0.0] * n
                for k in range(n):
                    if k == must or nxt() < CR:
                        trial[k] = _clamp(pa[k] + F * (pb[k] - pc[k]), lower[k], upper[k])
                    else:
                        trial[k] = pi[k]
                ft = budget.call(trial)
                if ft <= fit[i]:
                    pop[i] = trial
                    fit[i] = ft
                i += 1
            # Converged when the whole population agrees.
            lo = min(fit)
            hi = max(fit)
            if hi - lo <= abs(lo) * 1e-10:
                return budget.done('converged')
    except OptimiseError as e:
        return budget.done(str(e))


# ---------------------------------------------------------------------------
# The three, by the key a file stores.
# ---------------------------------------------------------------------------

_NM_KEYS = ('lower', 'upper', 'max_evals', 'tol', 'on_step', 'signal')
_LM_KEYS = _NM_KEYS
_DE_KEYS = ('lower', 'upper', 'start', 'pop_size', 'max_evals', 'seed', 'F', 'CR', 'on_step', 'signal')


def _only(opts: Optional[Mapping[str, Any]], keys: Sequence[str]) -> Dict[str, Any]:
    """The options a method reads; the rest are ignored, as the application's
    destructuring ignores them."""
    return {k: v for k, v in (opts or {}).items() if k in keys}


def _run_nelder(ctx: Mapping[str, Any], opts: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    return nelder_mead(ctx['objective'], ctx['start'], **_only(opts, _NM_KEYS))


def _run_lm(ctx: Mapping[str, Any], opts: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    return levenberg_marquardt(ctx['residuals'], ctx['start'], **_only(opts, _LM_KEYS))


def _run_de(ctx: Mapping[str, Any], opts: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    return differential_evolution(ctx['objective'], **{**_only(opts, _DE_KEYS), 'start': ctx['start']})


#: The methods, by the key a file stores. ``run(ctx, opts)`` takes ``ctx`` =
#: ``{'start', 'objective', 'residuals'}`` and the options by their Python
#: names (``lower``, ``upper``, ``max_evals``, ``seed``, ``on_step``,
#: ``signal``...); what a method does not read it ignores.
METHODS: Dict[str, Dict[str, Any]] = {
    'nelder': {
        'label': 'Nelder–Mead',
        'blurb': ('A simplex walking downhill. Few evaluations, no derivatives, and the '
                  'right first thing to try on a handful of parameters. Finds the bottom '
                  'of the valley it starts in.'),
        'global': False,
        'run': _run_nelder,
    },
    'lm': {
        'label': 'Levenberg–Marquardt',
        'blurb': ('The classic for least squares, and this is one. Costs one extra '
                  'evaluation per variable each iteration to build a Jacobian, and is the '
                  'fastest of the three once it is near. Wants a decent starting guess.'),
        'global': False,
        'run': _run_lm,
    },
    'de': {
        'label': 'Differential evolution',
        'blurb': ('A population crossed with its own differences. Much the slowest, and '
                  'the only one that climbs out of a local minimum — which is what to '
                  'reach for when the parameters range over decades.'),
        'global': True,
        'run': _run_de,
    },
}
