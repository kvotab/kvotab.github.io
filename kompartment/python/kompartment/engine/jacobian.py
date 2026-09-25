"""df/dy for the implicit solvers: its structure, a colouring, and its values.

The application generates an analytic Jacobian by differentiating its
generated code; what the solvers need most from it is the *pattern* -- which
entries can be non-zero -- because that is what makes a colouring (a handful
of derivative evaluations instead of one per state) and a sparse
factorisation possible. The pattern here is read off the same statements the
derivative is made of: which states each contribution reads, directly or
through the algebraic slots that read the state. It is structural, never
probed, so a coefficient that happens to be zero at the start is not taken
for a structural zero.

The values are then either assembled analytically (see :func:`build_jacobian`)
or differenced through the pattern, one evaluation per colour.

The rows of the mass-balance budgets are left at the diagonal, as the
application leaves them for the NDF: nothing reads a budget, so the Newton
iteration needs nothing more of those rows.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import scipy.sparse as sp

from . import codegen

EPS = 2.0 ** -52
SQRT_EPS = math.sqrt(EPS)


class Pattern:
    """A square sparsity pattern in compressed columns."""

    def __init__(self, n: int, rows: np.ndarray, cols: np.ndarray) -> None:
        m = sp.csc_matrix((np.ones(rows.size, dtype=np.int8), (rows, cols)), shape=(n, n))
        m.sum_duplicates()
        m.sort_indices()
        self.n = n
        self.col_ptr = m.indptr.astype(np.int64)
        self.row_idx = m.indices.astype(np.int64)
        self.nnz = int(self.row_idx.size)
        # For each entry, its column.
        self.col_of = np.repeat(np.arange(n, dtype=np.int64), np.diff(self.col_ptr))

    def matrix(self, values: np.ndarray) -> sp.csc_matrix:
        return sp.csc_matrix((values, self.row_idx, self.col_ptr), shape=(self.n, self.n))


def colour_columns(pattern: Pattern) -> List[np.ndarray]:
    """Groups of columns that share no row: greedy, largest degree first
    (``colourColumns``)."""
    n = pattern.n
    col_ptr, row_idx = pattern.col_ptr, pattern.row_idx
    csr = sp.csr_matrix((np.ones(row_idx.size, dtype=np.int8), row_idx, col_ptr), shape=(n, n)).T.tocsr()
    # csr of the transpose of (columns x rows)... rows -> columns that touch them:
    rows_cols = sp.csc_matrix((np.ones(row_idx.size, dtype=np.int8), row_idx, col_ptr), shape=(n, n)).tocsr()
    del csr
    row_ptr, row_cols = rows_cols.indptr, rows_cols.indices
    degree = np.diff(col_ptr)
    order = sorted(range(n), key=lambda j: -int(degree[j]))  # stable, as Array.sort is
    colour = np.full(n, -1, dtype=np.int64)
    used = np.full(n + 1, -1, dtype=np.int64)
    ncolours = 0
    for j in order:
        for k in range(col_ptr[j], col_ptr[j + 1]):
            r = row_idx[k]
            others = row_cols[row_ptr[r]:row_ptr[r + 1]]
            cs = colour[others]
            cs = cs[cs >= 0]
            used[cs] = j
        c = 0
        while used[c] == j:
            c += 1
        colour[j] = c
        ncolours = max(ncolours, c + 1)
    return [np.nonzero(colour == c)[0].astype(np.int64) for c in range(ncolours)]


def difference_increment(y: np.ndarray, threshold: np.ndarray) -> np.ndarray:
    """sqrt(eps) times the larger of |y_j| and the threshold, rounded to what
    the addition actually changed."""
    dl = SQRT_EPS * np.maximum(np.abs(y), threshold)
    dl = np.where(dl == 0, SQRT_EPS, dl)
    moved = (y + dl) - y
    return np.where(moved == 0, dl, moved)


def difference_jacobian(f: Any, t: float, y: np.ndarray, f0: np.ndarray, pattern: Pattern,
                        groups: Sequence[np.ndarray], threshold: np.ndarray,
                        out: Optional[np.ndarray] = None) -> np.ndarray:
    """One-sided differences through the pattern, one evaluation per colour,
    into the pattern's values (``differenceJacobian``)."""
    out = np.zeros(pattern.nnz) if out is None else out
    dl = difference_increment(y, threshold)
    col_of = pattern.col_of
    row_idx = pattern.row_idx
    entries_of_group = _group_entries(pattern, groups)
    for g, entries in zip(groups, entries_of_group):
        ytry = y.copy()
        ytry[g] += dl[g]
        fg = f(t, ytry)
        cols = col_of[entries]
        rows = row_idx[entries]
        out[entries] = (fg[rows] - f0[rows]) / dl[cols]
    return out


#: The entries of each colour, for the last few (pattern, groups) asked about.
#: The two are held as well as their entries: compared by identity, and kept
#: alive so that an id cannot be reused for another pattern while cached.
_ENTRY_CACHE: List[Tuple[Pattern, Sequence[np.ndarray], List[np.ndarray]]] = []
_ENTRY_CACHE_SIZE = 8


def _group_entries(pattern: Pattern, groups: Sequence[np.ndarray]) -> List[np.ndarray]:
    for p, g, splits in _ENTRY_CACHE:
        if p is pattern and g is groups:
            return splits
    colour = np.empty(pattern.n, dtype=np.int64)
    for c, g in enumerate(groups):
        colour[g] = c
    entry_colour = colour[pattern.col_of]
    order = np.argsort(entry_colour, kind='stable')
    counts = np.bincount(entry_colour, minlength=len(groups))
    splits = np.split(order, np.cumsum(counts)[:-1])
    _ENTRY_CACHE.append((pattern, groups, splits))
    del _ENTRY_CACHE[:-_ENTRY_CACHE_SIZE]
    return splits


# --- the structure ------------------------------------------------------------------

def _leaf_indices(index: Any, width: int) -> np.ndarray:
    if np.ndim(index) == 0:
        return np.full(width, int(index), dtype=np.int64)
    return np.asarray(index, dtype=np.int64)


def state_dependencies(system: Any) -> Dict[int, np.ndarray]:
    """For every algebraic slot that reads the state: the states it depends on,
    directly or through other such slots."""
    b = system.builder
    deps: Dict[int, np.ndarray] = {}
    moving = b.slot_class
    empty = np.zeros(0, dtype=np.int64)

    def of_x(idx: int) -> np.ndarray:
        return deps.get(idx, empty) if moving[idx] == 2 else empty

    for a in b.algebraic:
        if a.cls != 2:
            continue
        for s in b.alg_stmts[a.name]:
            if s.code is not None:
                _special_dependencies(b, a, deps, of_x)
                continue
            W = max(1, s.width)
            outs = _leaf_indices(s.out, W)
            ys: List[np.ndarray] = []
            xs: List[np.ndarray] = []
            for leaf in codegen.leaves(s.tree):
                if leaf.kind == 'y':
                    ys.append(_leaf_indices(leaf.index, W))
                elif leaf.kind == 'X':
                    xs.append(_leaf_indices(leaf.index, W))
            if s.multiply:
                xs.append(outs)
            for i in range(W):
                parts = [col[i:i + 1] for col in ys]
                for col in xs:
                    parts.append(of_x(int(col[i])))
                if s.multiply and int(outs[i]) in deps:
                    parts.append(deps[int(outs[i])])
                deps[int(outs[i])] = np.unique(np.concatenate(parts)) if parts else empty
    return deps


def _special_dependencies(b: Any, a: Any, deps: Dict[int, np.ndarray], of_x: Any) -> None:
    if a.kind == 'farfield':
        F = b.FARF[a.farf_index]
        for s in range(F.slots):
            parts = [F.rel_idx[s]] + [of_x(int(x)) for x in F.setting_idx[s]]
            deps[int(F.release_slots[s])] = np.unique(np.concatenate(parts))
        return
    rec = a.get('recorder')
    if rec is None:
        return
    for off in range(a.width):
        parts: List[np.ndarray] = []
        if rec.kind == 'min_max':
            parts.append(of_x(rec.aux['target'].base + off))
        elif rec.kind == 'running_mean':
            parts.append(np.array([rec.state.base + off], dtype=np.int64))
            parts.append(of_x(rec.aux['target'].base + off))
        elif rec.kind == 'delay':
            parts.append(of_x(rec.aux['delay'].base + off))
        deps[a.base + off] = np.unique(np.concatenate(parts)) if parts else np.zeros(0, dtype=np.int64)


def structure(system: Any) -> Pattern:
    """Which entries of df/dy can be non-zero."""
    b = system.builder
    n = system.nstate
    deps = state_dependencies(system)
    moving = b.slot_class
    budget_rows = np.zeros(n, dtype=bool)
    if b.budget is not None:
        budget_rows[b.budget['base']:b.budget['base'] + len(b.budget['terms']) * b.budget['nfam']] = True
    rows: List[np.ndarray] = [np.arange(n, dtype=np.int64)]
    cols: List[np.ndarray] = [np.arange(n, dtype=np.int64)]
    empty = np.zeros(0, dtype=np.int64)

    def x_deps(x: int) -> np.ndarray:
        return deps.get(x, empty) if moving[x] == 2 else empty

    def add(row: int, dep: np.ndarray) -> None:
        if dep.size and not budget_rows[row]:
            rows.append(np.full(dep.size, row, dtype=np.int64))
            cols.append(dep)

    def add_many(tgt: np.ndarray, src: np.ndarray) -> None:
        keep = ~budget_rows[tgt]
        rows.append(tgt[keep])
        cols.append(src[keep])

    for ph in b.phases:
        kind = ph[0]
        if kind == 'transfers':
            _, tgt, flux, _sign = ph
            src_of_flux = np.full(b.nflux, -1, dtype=np.int64)
            src_of_flux[b.flux_mbd] = b.flux_mbd_src
            has = src_of_flux[flux] >= 0
            add_many(tgt[has], src_of_flux[flux][has])
            rate = b.flux_rate[flux]
            for r, x in zip(tgt, rate):
                add(int(r), x_deps(int(x)))
        elif kind == 'x':
            _, tgt, xs = ph
            for r, x in zip(tgt, xs):
                add(int(r), x_deps(int(x)))
        elif kind == 'waste':
            _, p_idx, m_idx, h, r_idx, _budget = ph
            add_many(p_idx, p_idx)
            add_many(m_idx, p_idx)
            for p, m, r in zip(p_idx, m_idx, r_idx):
                add(int(p), x_deps(h))
                add(int(m), x_deps(h))
                add(int(m), x_deps(int(r)))
        elif kind == 'move':
            _, a_idx, second, lam_slot, share_slot = ph
            extra = np.unique(np.concatenate([x_deps(lam_slot), x_deps(share_slot)]))
            add_many(a_idx, a_idx)
            if second is not None:
                add_many(second, a_idx)
            for r in a_idx:
                add(int(r), extra)
            if second is not None:
                for r in second:
                    add(int(r), extra)
        elif kind == 'mean':
            _, s_idx, t_idx, _mem = ph
            for r, x in zip(s_idx, t_idx):
                add(int(r), x_deps(int(x)))
        elif kind == 'coef':
            _, tgt, _coef, src = ph
            add_many(tgt, src)
        elif kind == 'farf':
            F = system.FARF[ph[1]]
            add_many(F.row_flat, F.col_flat)
            settings = np.unique(np.concatenate([x_deps(int(x)) for x in F.setting_idx.ravel()])) \
                if F.setting_idx.size else empty
            if settings.size:
                for r in np.unique(F.row_flat):
                    add(int(r), settings)
    r = np.concatenate(rows)
    c = np.concatenate(cols)
    return Pattern(n, r, c)


def build_jacobian(system: Any) -> Dict[str, Any]:
    """The Jacobian the solvers are handed: its pattern and colouring, and --
    where the model allows -- its values."""
    try:
        pattern = structure(system)
    except MemoryError:
        return {'available': False, 'reason': 'the pattern is too large to hold'}
    groups = colour_columns(pattern)
    n = system.nstate
    info: Dict[str, Any] = {
        'available': False,
        'reason': 'differenced through its pattern',
        'pattern': pattern,
        'groups': groups,
        'constant': False,
        'evaluate': None,
        'nnz': pattern.nnz,
        'colours': len(groups),
        'density': pattern.nnz / max(1, n * n),
        'budget_rows': 'diagonal' if system.builder.budget is not None else None,
    }
    try:
        from .analytic import analytic_jacobian
        analytic = analytic_jacobian(system, pattern)
    except ImportError:
        analytic = None
    if analytic is not None:
        info.update(analytic)
    return info
