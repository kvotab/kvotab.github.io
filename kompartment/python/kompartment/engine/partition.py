"""Cutting a model into parts that cannot see each other.

A port of the application's ``src/sim/partition.js``. A large assessment is
rarely one problem: its radionuclides fall into groups with no path between
them -- each decay chain held together by its own ingrowth and nothing joining
one chain to the next -- and solved as one system every state moves at the
step size the worst of them needs. This finds those groups; what to do with
them is :mod:`kompartment.engine.split`'s business.

**The graph is the Jacobian's pattern.** Two states belong together when one
can reach the other, and ``df/dy`` is exactly that relation: an entry at
(i, j) when the derivative of state i reads state j, through however many
expressions and rates. It is undirected here -- a path either way puts two
states together, since solving them apart needs them not to reach each other
in either direction.

**Where the pattern is not enough, the model is refused.** A snapshot and a
delay report the past, which no present state can move, so the Jacobian gives
them no column; an event moves a state its condition never mentions. A
dependency through any of them is invisible to the pattern, and a partition
that misses one does not run slowly -- it returns a different answer, quietly.
So a model with one is not split (:func:`why_not_split`). A min/max and a
running mean are not in that list: the Jacobian gives both a column through
their target, so the pattern already carries them.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

__all__ = ['state_partition', 'why_not_split', 'partition_of']


def state_partition(pattern: Any) -> Dict[str, Any]:
    """The states of each part, from a sparsity pattern (``statePartition``).

    ``{'count', 'of', 'sizes', 'largest'}``: ``of[i]`` is the part state ``i``
    belongs to, numbered from 0 in the order the states first appear, so part
    0 holds state 0 -- a property of the model rather than of how the
    components were found.
    """
    n = int(getattr(pattern, 'n', 0) or 0) if pattern is not None else 0
    if n == 0:
        return {'count': 0, 'of': np.zeros(0, dtype=np.int64), 'sizes': np.zeros(0, dtype=np.int64), 'largest': 0}
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components
    col_ptr = np.asarray(pattern.col_ptr, dtype=np.int64)
    row_idx = np.asarray(pattern.row_idx, dtype=np.int64)
    graph = sp.csc_matrix((np.ones(row_idx.size, dtype=np.int8), row_idx, col_ptr), shape=(n, n))
    # The components of the undirected graph -- the application finds the same
    # ones by union-find -- then numbered in the order each one's first state
    # appears, which is the application's numbering and depends on nothing
    # but the model.
    count, labels = connected_components(graph, directed=True, connection='weak')
    first = np.full(count, n, dtype=np.int64)
    np.minimum.at(first, labels, np.arange(n, dtype=np.int64))
    renumber = np.empty(count, dtype=np.int64)
    renumber[np.argsort(first, kind='stable')] = np.arange(count, dtype=np.int64)
    of = renumber[labels].astype(np.int64)
    sizes = np.bincount(of, minlength=count).astype(np.int64)
    return {'count': count, 'of': of, 'sizes': sizes, 'largest': int(sizes.max()) if count else 0}


#: The blocks whose dependency the Jacobian pattern deliberately leaves out.
UNSEEN = {
    'delay': ('a delay reports the past, which no present state can move, so the Jacobian gives it no column '
              'and a dependency through it is invisible to this partition'),
    'snapshot': ('a snapshot reports the past, which no present state can move, so the Jacobian gives it no '
                 'column and a dependency through it is invisible to this partition'),
    'trigger': ('an event moves a state its condition never mentions, which is not a derivative and so is not '
                'in the Jacobian'),
}


def why_not_split(system: Any) -> Optional[str]:
    """Why this system may not be split, or None when it may (``whyNotSplit``).
    It names the first thing it cannot account for rather than guessing."""
    jac = getattr(system, 'jacobian', None) or {}
    if not jac.get('available'):
        return 'the model has no analytic Jacobian, so there is no sparsity pattern to read the parts off'
    pattern = jac.get('pattern')
    if pattern is None or not getattr(pattern, 'n', 0):
        return 'the model has no states to split'
    for rec in getattr(system, 'recorders', None) or []:
        why = UNSEEN.get(rec.kind)
        if why:
            return f"'{rec.name}' is a {rec.kind.replace('_', ' ')}: {why}"
    # A semi-analytical path's release is a convolution over what flowed into
    # it during the run, and the series of a split run are worked out
    # afterwards on the whole model's system, which never saw that history.
    layout = getattr(system, 'layout', None)
    for p in (layout.get('farfields') if layout is not None else None) or []:
        if p.farf.laplace:
            return (f"'{p.name}' is worked out semi-analytically: its release is a convolution over what flowed "
                    'into it during the run, which the whole model the series are worked out on afterwards does '
                    'not have')
    events = getattr(system, 'events', None)
    if events is not None and getattr(events, 'n', 0):
        many = 'an event' if events.n == 1 else f'{events.n} events'
        return (f'the model has {many}, and an event moves a state its condition never mentions, which is not a '
                'derivative and so is not in the Jacobian')
    return None


def partition_of(system: Any) -> Dict[str, Any]:
    """The partition, with the reason when there is not one (``partitionOf``):
    ``{'ok', 'refusal', 'count', 'of', 'sizes', 'largest'}``."""
    refusal = why_not_split(system)
    if refusal:
        return {'ok': False, 'refusal': refusal, 'count': 1, 'of': None, 'sizes': None, 'largest': 0}
    p = state_partition(system.jacobian['pattern'])
    return {'ok': True, 'refusal': None, **p}
