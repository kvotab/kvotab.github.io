"""The linear algebra the stiff solvers need (``core/linalg.js``).

The package factorises W with three LUs of its own: a dense one, a complex
dense one for Radau, and a left-looking sparse one (Gilbert-Peierls) behind a
reverse Cuthill-McKee column ordering. Here the dense factorisations are
LAPACK's, through SciPy, and the sparse one is the package's own, compiled
with numba (:mod:`.packagelu`) -- or, without numba, SuperLU's. What the
package decides around them is kept:

* the ordering: the package's reverse Cuthill-McKee order of the columns, which
  SuperLU, its own ordering switched off, eliminates in the same
  column-by-column way with partial pivoting, so the fill it reports is the
  package's;
* ``fill``: the non-zeros of L below the diagonal plus those of U, counted
  numerically as the package counts them;
* singular means what it means there: a pivot column that is exactly zero.

Pivots are the largest entry in all of them (LAPACK's ``izamax`` measures a
complex entry by ``|re| + |im|``, as the package does). The package's sparse
LU gives its factors and solutions to the last bit; LAPACK's and SuperLU's
agree with the package's to rounding, their accumulation order being theirs.
"""

from __future__ import annotations

import warnings
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import scipy.linalg as la
import scipy.sparse as sp
import scipy.sparse.linalg as spla


def csc_from_triplets(n: int, rows: np.ndarray, cols: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """A CSC pattern from (row, col) pairs, rows sorted in each column and
    duplicates folded (``cscFromTriplets``, for the structure only)."""
    rows = np.asarray(rows, dtype=np.int64)
    cols = np.asarray(cols, dtype=np.int64)
    order = np.lexsort((rows, cols))
    r = rows[order]
    c = cols[order]
    if r.size:
        keep = np.ones(r.size, dtype=bool)
        keep[1:] = (r[1:] != r[:-1]) | (c[1:] != c[:-1])
        r = r[keep]
        c = c[keep]
    col_ptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(np.bincount(c, minlength=n), out=col_ptr[1:])
    return col_ptr, r


def dense_pattern(n: int) -> Tuple[np.ndarray, np.ndarray]:
    """A full n x n pattern (``densePattern``)."""
    col_ptr = np.arange(n + 1, dtype=np.int64) * n
    row_idx = np.tile(np.arange(n, dtype=np.int64), n)
    return col_ptr, row_idx


def pattern_key(n: int, col_ptr: Sequence[int], row_idx: Sequence[int]) -> Tuple[int, bytes, bytes]:
    """A pattern as a key: what an ordering or a colouring of it is kept by."""
    return (n, np.ascontiguousarray(col_ptr, dtype=np.int64).tobytes(),
            np.ascontiguousarray(row_idx, dtype=np.int64).tobytes())


#: The orderings of the patterns met last: a run made of many spans, or many
#: realisations, builds the solver again for each, on the same pattern.
_RCM_KEPT: Dict[Tuple[int, bytes, bytes], np.ndarray] = {}
KEPT_PATTERNS = 8


def reverse_cuthill_mckee(n: int, col_ptr: Sequence[int], row_idx: Sequence[int]) -> np.ndarray:
    """Reverse Cuthill-McKee on the symmetrised pattern, new -> old
    (``reverseCuthillMcKee``, as fixed on 2026-09-25: the leftovers of the first
    sweep are ordered after it); kept for the patterns met last."""
    key = pattern_key(n, col_ptr, row_idx)
    kept = _RCM_KEPT.get(key)
    if kept is None:
        kept = _reverse_cuthill_mckee(n, col_ptr, row_idx)
        if len(_RCM_KEPT) >= KEPT_PATTERNS:
            _RCM_KEPT.pop(next(iter(_RCM_KEPT)))
        _RCM_KEPT[key] = kept
    return kept.copy()


def _reverse_cuthill_mckee(n: int, col_ptr: Sequence[int], row_idx: Sequence[int]) -> np.ndarray:
    cp = [int(v) for v in col_ptr]
    ri = [int(v) for v in row_idx]
    deg = [0] * n
    for j in range(n):
        for k in range(cp[j], cp[j + 1]):
            i = ri[k]
            if i == j:
                continue
            deg[i] += 1
            deg[j] += 1
    start = [0] * (n + 1)
    for j in range(n):
        start[j + 1] = start[j] + deg[j]
    adj = [0] * start[n]
    at = list(start)
    for j in range(n):
        for k in range(cp[j], cp[j + 1]):
            i = ri[k]
            if i == j:
                continue
            adj[at[i]] = j
            at[i] += 1
            adj[at[j]] = i
            at[j] += 1

    order = [0] * n
    seen = [False] * n
    # The least degree at or after a position, first on ties, as the scan finds
    # it; a seen vertex is out of the running.
    big = np.iinfo(np.int64).max
    open_degree = np.array(deg, dtype=np.int64)
    w = 0

    def mark(v: int) -> None:
        seen[v] = True
        open_degree[v] = big

    def component(frm: int) -> None:
        nonlocal w
        root = frm + int(np.argmin(open_degree[frm:]))
        mark(root)
        order[w] = root
        w += 1
        head = w - 1
        while head < w:
            v = order[head]
            head += 1
            nbrs: List[int] = []
            for k in range(start[v], start[v + 1]):
                u = adj[k]
                if not seen[u]:
                    mark(u)
                    nbrs.append(u)
            nbrs.sort(key=lambda a: deg[a])
            for u in nbrs:
                order[w] = u
                w += 1

    for s in range(n):
        if seen[s]:
            continue
        component(s)
    for s in range(n):
        if w >= n:
            break
        while not seen[s]:
            component(s)
    return np.array(order[::-1], dtype=np.int64)


def _quiet_lu_factor(a: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return la.lu_factor(a, check_finite=False)


class DenseLU:
    """LU with partial pivoting of a dense matrix (``DenseLU``)."""

    def __init__(self, n: int) -> None:
        self.n = n
        self._lu: Optional[Tuple[np.ndarray, np.ndarray]] = None
        self.singular = False

    def factor(self, a: np.ndarray) -> bool:
        lu, piv = _quiet_lu_factor(a)
        # The package stops at the first pivot column that is exactly zero;
        # LAPACK records it as a zero on the diagonal of U and carries on.
        if np.any(np.diagonal(lu) == 0):
            self.singular = True
            return False
        self.singular = False
        self._lu = (lu, piv)
        return True

    def solve(self, b: np.ndarray) -> np.ndarray:
        return la.lu_solve(self._lu, b, check_finite=False)


class ComplexDenseLU(DenseLU):
    """The same over the complex numbers, for Radau's second half
    (``ComplexDenseLU``)."""


class SuperSparseLU:
    """Sparse LU with partial pivoting behind a column ordering (``SparseLU``),
    by SuperLU: where numba is not installed (see :data:`SparseLU`).

    ``perm`` is new -> old: column k of the factorised matrix is column
    ``perm[k]`` of W, and the solution is scattered back through it.
    """

    def __init__(self, n: int, col_ptr: np.ndarray, row_idx: np.ndarray, perm: Optional[np.ndarray]) -> None:
        self.n = n
        self.perm = perm
        order = perm if perm is not None else np.arange(n, dtype=np.int64)
        lens = np.diff(col_ptr)[order]
        self._indptr = np.zeros(n + 1, dtype=np.int64)
        np.cumsum(lens, out=self._indptr[1:])
        # Where each entry of the reordered matrix comes from in W's values.
        starts = np.asarray(col_ptr, dtype=np.int64)[order]
        offsets = np.arange(int(self._indptr[n]), dtype=np.int64) - np.repeat(self._indptr[:-1], lens)
        self._gather = np.repeat(starts, lens) + offsets
        self._indices = np.asarray(row_idx, dtype=np.int64)[self._gather]
        self._lu = None
        self.singular = False
        self._fill: Optional[int] = None

    def factor(self, values: np.ndarray) -> bool:
        a = sp.csc_matrix((values[self._gather], self._indices, self._indptr), shape=(self.n, self.n))
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                lu = spla.splu(a, permc_spec='NATURAL', diag_pivot_thresh=1.0)
        except RuntimeError:
            self.singular = True
            return False
        self.singular = False
        self._lu = lu
        self._fill = None
        return True

    @property
    def fill(self) -> int:
        """Non-zeros in L below the diagonal and in U, as the package counts
        them after each factorisation (read off the latest one)."""
        if self._fill is None:
            if self._lu is None:
                return 0
            L = self._lu.L
            U = self._lu.U
            self._fill = int(np.count_nonzero(L.data)) - self.n + int(np.count_nonzero(U.data))
        return self._fill

    def solve(self, b: np.ndarray) -> np.ndarray:
        y = self._lu.solve(np.asarray(b, dtype=float))
        if self.perm is None:
            return y
        x = np.empty(self.n)
        x[self.perm] = y
        return x


try:
    #: The package's sparse LU itself (:mod:`.packagelu`), where numba is installed.
    from .packagelu import SparseLU
except Exception:  # noqa: BLE001 - numba is optional (or does not compile here): SuperLU then
    SparseLU = SuperSparseLU  # type: ignore[misc,assignment]
