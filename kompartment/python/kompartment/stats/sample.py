"""Drawing values from the distributions on a model, as Kompartment draws them.

A port of the application's ``src/domain/sample.js``. :mod:`.pdf` holds the
distributions; this holds the other half: given one and a number between 0 and
1, which value does it stand for. Everything is an inverse CDF rather than a
sampler of its own, which buys reproducibility (a run is a seed and nothing
else), truncation (the same inverse CDF fed a uniform confined to
``[F(lo), F(hi)]``) and Latin hypercube sampling (a statement about the
uniforms, not the shapes) at once.

**The same numbers as the application.** The generator is mulberry32, as the
application's, and its output is bit for bit the application's for the same
seed; so is every stream (:func:`stream_for`, one per sampled input, seeded
from the run's seed and the input's name) and every column of uniforms
(:func:`uniforms`). The values drawn from them go through :mod:`.pdf`'s
quantiles, which do V8's arithmetic, so a probabilistic run here draws the
application's sample: exactly for the uniform, triangular and log-shaped
kinds, and to the last bit or two where a normal CDF or quantile is involved
(see :mod:`.pdf`).

:func:`cdf_at`, :func:`quantile` and :func:`phi` are re-exported from
:mod:`.pdf`, as the application's ``sample.js`` re-exports them.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Mapping

from .pdf import (
    _jmax, _jmin, _js_str, _meta, _nullish, _prop, _string_to_number, _to_number, _truthy,
    cdf_at, complete, phi, probability_cuts, quantile,
)

# `hash` is left out: a star import would shadow the built-in of that name.
__all__ = ['stream_for', 'rng', 'Mulberry32', 'value_at_probability', 'uniforms',
           'distributed_slots', 'cdf_at', 'quantile', 'phi']

_M32 = 0xFFFFFFFF
_STEP = 0x6D2B79F5


def _to_uint32(v: Any) -> int:
    """``v >>> 0``: JavaScript's ToUint32."""
    x = _to_number(v)
    if x != x or math.isinf(x):
        return 0
    return int(x) % 4294967296


class Mulberry32:
    """A small, fast, seeded generator: mulberry32, the application's.

    Thirty-two bits of state, a period of 2**32, and good enough
    equidistribution for Monte Carlo over parameters; not a cryptographic
    generator. Calling it gives the next number in [0, 1), exactly as the
    application's ``rng(seed)()`` does -- the same 32-bit arithmetic, so the
    same bits.

    The state is a counter stepped by a constant, so :meth:`take` can draw many
    numbers at once (with numpy) and still give exactly what as many calls
    would.
    """

    __slots__ = ('_a',)

    def __init__(self, seed: Any = 1) -> None:
        self._a = _to_uint32(seed) or 1

    def __call__(self) -> float:
        a = (self._a + _STEP) & _M32
        self._a = a
        t = ((a ^ (a >> 15)) * (a | 1)) & _M32
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & _M32)) & _M32
        return ((t ^ (t >> 14)) & _M32) / 4294967296

    def take(self, n: int) -> Any:
        """The next ``n`` numbers as a float64 numpy array, as ``n`` calls would give them."""
        import numpy as np
        n = int(n)
        if n <= 0:
            return np.empty(0, dtype=np.float64)
        m = np.uint64(_M32)
        k = np.arange(1, n + 1, dtype=np.uint64)
        a = (np.uint64(self._a) + k * np.uint64(_STEP)) & m
        self._a = int(a[-1])
        t = ((a ^ (a >> np.uint64(15))) * (a | np.uint64(1))) & m
        t ^= (t + (((t ^ (t >> np.uint64(7))) * (t | np.uint64(61))) & m)) & m
        return ((t ^ (t >> np.uint64(14))) & m).astype(np.float64) / 4294967296.0

    @property
    def state(self) -> int:
        """The 32-bit state, for a test that wants to see it."""
        return self._a

    def __repr__(self) -> str:
        return f'Mulberry32(state={self._a})'


def rng(seed: Any = 1) -> Mulberry32:
    """A generator seeded with ``seed``: the application's ``rng``. A seed of 0 is taken as 1.

    Not ``random``: a probabilistic result that cannot be reproduced is a
    number nobody can check.
    """
    return Mulberry32(seed)


def hash(text: str) -> int:  # noqa: A001 -- the application's name for it
    """FNV-1a over a name's UTF-16 code units, as the application hashes it: a 32-bit integer.

    Small, stable, and not a cryptographic claim. Code units, as JavaScript's
    ``charCodeAt`` reads them, so a character outside the Basic Multilingual
    Plane counts as its two surrogates. A number has no length there, so it
    hashes as nothing; anything else that is not a string fails, as there.
    """
    if isinstance(text, (int, float)):
        return 2166136261
    if not isinstance(text, str):
        raise TypeError(f'a name to hash is a string, not {type(text).__name__}')
    h = 2166136261
    data = text.encode('utf-16-le', 'surrogatepass')
    for i in range(0, len(data), 2):
        h = ((h ^ (data[i] | (data[i + 1] << 8))) * 16777619) & _M32
    return h


def _mix(a: int, b: int) -> int:
    """Two 32-bit values into one, well enough that neighbours do not collide."""
    h = (a ^ (((b ^ (b >> 16)) * 2246822507) & _M32)) & _M32
    h = ((h ^ (h >> 13)) * 3266489909) & _M32
    return (h ^ (h >> 16)) & _M32


def stream_for(seed: Any, name: Any) -> Mulberry32:
    """A stream of its own for one named thing: the run's seed mixed with a hash of the name.

    Why every sampled input gets its own: drawn from one stream split across
    the plan in order, adding a distribution to one parameter moved every
    parameter after it onto different numbers. With a stream per name, the
    same seed gives the same sample for everything that has not changed --
    the property that lets a re-run after a review be compared at all, and
    what makes a partial run a comparison rather than a new experiment.

    ``name`` is what is drawn for, as the application spells it: ``slotName``,
    so ``Kd[Tc-99]`` and ``Kd[I-129]`` are separate streams; a correlation
    group's name for its members; ``correlation:<name>`` for a correlation's
    scores; ``<event>#occurrences#<i>`` for a disruptive event's dice.
    """
    return Mulberry32(_mix(_to_uint32(seed), hash(_js_str('' if _nullish(name) else name))))


def _element(values: Any, index: float) -> Any:
    """``values[index]`` as JavaScript reads it: NaN (``undefined``) unless a whole index in range."""
    if index != index or math.isinf(index) or index != math.floor(index):
        return math.nan
    i = int(index)
    if i < 0 or i >= len(values):
        return math.nan
    v = values[i]
    if hasattr(v, 'item'):
        v = v.item()
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v


def _list_index(pos: Any, at: Any, length: int) -> float:
    """``((spec.pos ?? 0) + at) % length``, with JavaScript's ``+`` and ``%``."""
    if _nullish(pos):
        pos = 0
    if isinstance(pos, str):  # JavaScript's `+` joins a string: '3' + 1 is '31'
        total = _string_to_number(pos + _js_str(at))
    else:
        total = _to_number(pos) + _to_number(at)
    if total != total or math.isinf(total):
        return math.nan
    return math.fmod(total, length)


def value_at_probability(spec: Any, u: float, at: int = 0) -> Any:
    """One value from ``spec`` for the uniform ``u``; NaN where the distribution is not filled in.

    A list (``pg``) is not drawn from: in order (``inorder``, the default) it
    hands out value ``(pos + at) % n`` to realisation ``at``, which is how a
    model reproduces somebody else's run exactly; out of order it takes the
    value at ``u``. Every other kind is its quantile at ``u`` read between the
    two probabilities its truncation leaves (:func:`probability_cuts`), never
    exactly 0 or 1, and clamped to a value truncation that the round trip
    through the CDF misses by a billionth.
    """
    if not _truthy(spec) or _meta(_prop(spec, 'kind')) is None or not complete(spec):
        return math.nan
    if spec['kind'] == 'pg':
        v = _prop(spec, 'values')
        if _nullish(v) or not len(v):
            return math.nan
        if _prop(spec, 'inorder') is False:
            x = _to_number(u) * len(v)
            return _element(v, _jmin(len(v) - 1, math.floor(x) if math.isfinite(x) else x))
        return _element(v, _list_index(_prop(spec, 'pos'), at, len(v)))
    # Truncation is the same curve read between two probabilities rather than
    # between 0 and 1 -- never by rejection, which has no bound on how many
    # draws a curve truncated to its own tail would take.
    cuts = probability_cuts(spec)
    lo, hi = cuts['lo'], cuts['hi']
    # Never exactly 0 or 1: the quantile of either is infinite for a curve with
    # unbounded tails, and one infinite parameter ruins a whole run.
    q = _jmin(1 - 1e-12, _jmax(1e-12, lo + _to_number(u) * (hi - lo)))
    v = quantile(spec, q)
    if cuts['reversed']:
        return v
    trmin = _prop(spec, 'trmin')
    trmax = _prop(spec, 'trmax')
    if not _nullish(trmin) and v < _to_number(trmin):
        return _to_number(trmin)
    if not _nullish(trmax) and v > _to_number(trmax):
        return _to_number(trmax)
    return v


def uniforms(n: int, next: Callable[[], float], latin: bool = True) -> Any:  # noqa: A002
    """``n`` uniforms in (0, 1) from ``next``, stratified or not: a float64 numpy array.

    Latin hypercube (``latin``, the default): one from each of ``n`` equal
    slices, in an order shuffled by Fisher-Yates, so the draws cover the range
    evenly and which slice a realisation gets is independent of every other
    parameter. Otherwise ``n`` independent draws. The numbers are the
    application's for the same ``next`` -- a :class:`Mulberry32` from
    :func:`stream_for` or :func:`rng` -- which is drawn from in the same order.
    """
    import numpy as np
    n = int(n)
    if n < 0:
        raise ValueError('Invalid typed array length: a column cannot hold fewer than no uniforms')
    fast = isinstance(next, Mulberry32)
    if not latin:
        if fast:
            return next.take(n)
        return np.array([next() for _ in range(n)], dtype=np.float64)
    first = next.take(n) if fast else np.array([next() for _ in range(n)], dtype=np.float64)
    out = ((np.arange(n, dtype=np.float64) + first) / n).tolist()
    # Fisher-Yates: otherwise every parameter would rise together through the
    # run and the sample would lie on a diagonal.
    if n > 1:
        if fast:
            picks = np.floor(next.take(n - 1) * np.arange(n, 1, -1, dtype=np.float64)).astype(np.int64).tolist()
        else:
            picks = None
        for step, i in enumerate(range(n - 1, 0, -1)):
            j = picks[step] if picks is not None else math.floor(next() * (i + 1))
            out[i], out[j] = out[j], out[i]
    return np.array(out, dtype=np.float64)


def _field(obj: Any, *names: str) -> Any:
    """``obj.name ?? obj.other_name ?? null``, from a dictionary or an object's attributes."""
    for name in names:
        if isinstance(obj, Mapping):
            v = obj.get(name)
        else:
            v = getattr(obj, name, None)
        if v is not None:
            return v
    return None


def distributed_slots(layout: Any, effective: Callable[[Any, str, Dict[str, str]], Any],
                      tuple_at: Callable[[Any, List[str], int], Dict[str, str]]) -> List[Dict[str, Any]]:
    """Every distributed value in the model, and where it lives in ``P``.

    ``layout`` is the built system's layout: its lookup-table points that
    carry a distribution (``lookupPoints``, each ``{slot, name, at, index,
    spec}``), its parameters (``parameters``, each ``{block, name, dims, base,
    width}``) and its index space (``indexSpace``); snake_case spellings of the
    three are read too, from a dictionary or an object's attributes.
    ``effective(block, 'pdf', index)`` reads a parameter's distribution at one
    index -- the entry's own or the block's -- and ``tuple_at(index_space,
    dims, offset)`` says which index an offset is.

    Returns ``[{'slot', 'name', 'index', 'spec'}]``: the table points first,
    named ``<table>@<time>``, then every parameter slot whose distribution is
    filled in, in the layout's order.
    """
    out: List[Dict[str, Any]] = []
    # A lookup table's point that carries its own spread is a distributed value
    # like any other; the time is part of its name.
    for pt in _field(layout, 'lookupPoints', 'lookup_points') or []:
        spec = _field(pt, 'spec')
        if not _truthy(spec) or not complete(spec):
            continue
        index = _field(pt, 'index')
        out.append({
            'slot': _field(pt, 'slot'),
            'name': f"{_js_str(_field(pt, 'name'))}@{_js_str(_field(pt, 'at'))}",
            'index': {} if index is None else index,
            'spec': spec,
        })
    space = _field(layout, 'indexSpace', 'index_space')
    for entry in _field(layout, 'parameters') or []:
        block = _field(entry, 'block')
        dims = _field(entry, 'dims') or []
        base = _field(entry, 'base')
        width = _field(entry, 'width') or 0
        for off in range(int(width)):
            tup = tuple_at(space, dims, off) if len(dims) else {}
            spec = effective(block, 'pdf', tup)
            if not _truthy(spec) or not complete(spec):
                continue
            out.append({'slot': base + off, 'name': _field(entry, 'name'), 'index': tup, 'spec': spec})
    return out
