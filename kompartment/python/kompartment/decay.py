"""Radionuclide data: half-lives, elements and the decay chains between them.

The data is ICRP Publication 107 as Kompartment carries it (see
``data/icrp107.json``, written from the application's own table by
``tools/gen_data.mjs``). Three things are worked out from it here, the same way
the application works them out:

* :func:`half_life` -- a nuclide's half-life in years, ``math.inf`` for a
  stable one and ``None`` for a name the database does not know;
* :func:`element_of` -- the element a nuclide belongs to (``Cs-137`` -> ``Cs``),
  which is what Kompartment's element list groups the materials by;
* :func:`default_chains` -- the decay pairs among a set of nuclides when a
  model does not state its own: each modelled nuclide's daughters, with the
  branching that actually reaches them through the members that are *not*
  modelled. A port of ``collapse`` in ``src/domain/decaydb.js``.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from importlib import resources
from typing import Dict, Iterable, List, Optional, Tuple

Pair = Tuple[str, str, float]

# What a stable nuclide is written as in a project file. JSON has no infinity,
# and a null there would read back as "no half-life at all".
STABLE = 'stable'


@lru_cache(maxsize=1)
def _table() -> Dict[str, Tuple[float, List[Tuple[str, float]]]]:
    text = resources.files(__package__).joinpath('data', 'icrp107.json').read_text('utf-8')
    rows = json.loads(text)['nuclides']
    out: Dict[str, Tuple[float, List[Tuple[str, float]]]] = {}
    for name, half, progeny in rows:
        out[name] = (math.inf if half is None else float(half),
                     [(d, float(b)) for d, b in progeny])
    return out


@lru_cache(maxsize=1)
def _order() -> Dict[str, int]:
    """Each nuclide's position in the database: by Z, then by A."""
    return {name: k for k, name in enumerate(_table())}


def known_nuclides() -> List[str]:
    """Every nuclide the database has, in its own order (by Z, then A)."""
    return list(_table())


def is_known(name: str) -> bool:
    """Whether ICRP 107 has heard of a nuclide."""
    return name in _table()


def half_life(name: str) -> Optional[float]:
    """Half-life in years; ``math.inf`` when stable, ``None`` when unknown."""
    row = _table().get(name)
    return row[0] if row else None


def means_stable(value: object) -> bool:
    """Whether a half-life as a file may write it means "does not decay"."""
    if isinstance(value, float) and math.isinf(value):
        return True
    return isinstance(value, str) and re.fullmatch(r'stable|inf(inity)?', value.strip(), re.I) is not None


_SYMBOL = re.compile(r'^([A-Za-z]{1,3})(?=$|[-\s0-9])')


def element_of(nuclide: str) -> Optional[str]:
    """The element symbol of a nuclide's name, capitalised as a symbol is.

    ``Cs-137`` -> ``Cs``, ``c-14`` -> ``C``. ``None`` when the name does not
    start with one -- such a material is its own element in Kompartment.
    """
    m = _SYMBOL.match(str(nuclide or '').strip())
    if not m:
        return None
    s = m.group(1)
    return s[0].upper() + s[1:].lower()


def _distribution(name: str, keep: set, memo: Dict[str, Dict[str, float]],
                  ceiling: float) -> Dict[str, float]:
    """What one decay of ``name`` reaches among the kept nuclides, and how often."""
    if name in memo:
        return memo[name]
    out: Dict[str, float] = {}
    memo[name] = out  # before the walk, so a cycle cannot recurse forever
    table = _table()
    for daughter, branching in table.get(name, (0.0, []))[1]:
        if daughter in keep:
            out[daughter] = out.get(daughter, 0.0) + branching
            continue
        half = half_life(daughter)
        if half is None or math.isinf(half):
            continue  # the activity leaves the chain
        if half > ceiling:
            continue  # a sink within any assessment's span
        for target, share in _distribution(daughter, keep, memo, ceiling).items():
            out[target] = out.get(target, 0.0) + branching * share
    return out


def _locale_key(name: str) -> Tuple[str, str]:
    # JavaScript's `localeCompare`, for the names this sorts: letters compared
    # without regard to case first, lower case before upper on a tie.
    return (name.casefold(), name.swapcase())


def default_chains(nuclides: Iterable[str], ceiling: float = math.inf,
                   min_branching: float = 1e-9) -> List[Pair]:
    """The decay pairs a set of nuclides makes, as Kompartment works them out.

    ``[parent, daughter, branching]``, the effective branching being the total
    probability that one decay of the parent reaches the daughter through
    nuclides that are not in the set. A daughter longer-lived than ``ceiling``
    years is a sink rather than passed through. Names the database does not
    know take no part.
    """
    wanted = list(dict.fromkeys(nuclides))
    table = _table()
    keep = {n for n in wanted if n in table}
    memo: Dict[str, Dict[str, float]] = {}
    pairs: List[Pair] = []
    for name in table:  # the database's order, whatever order was asked for
        if name not in keep:
            continue
        for daughter, branching in _distribution(name, keep, memo, ceiling).items():
            if branching < min_branching:
                continue
            pairs.append((name, daughter, branching))
    pairs.sort(key=lambda p: (_locale_key(p[0]), -p[2]))
    return pairs
