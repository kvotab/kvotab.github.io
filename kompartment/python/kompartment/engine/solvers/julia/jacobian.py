"""df/du, and the matrix the solvers invert (``core/jacobian.js``).

``JacobianCache`` produces J -- from the caller's Jacobian, which may decline
a point, or by forward differences through the package's own colouring of the
pattern -- and ``WFactorization`` forms W = I - gh*J (or I/(gh) - J) from it,
factorises it, and knows when it may reuse the factor or must re-evaluate J.
"""

from __future__ import annotations

import math
from typing import Callable, List, Optional, Tuple

import numpy as np

from ._js import SQRT_EPS
from .linalg import DenseLU, SparseLU, csc_from_triplets, dense_pattern, reverse_cuthill_mckee

Pattern = Tuple[np.ndarray, np.ndarray]


def colour_columns(n: int, col_ptr: np.ndarray, row_idx: np.ndarray) -> List[np.ndarray]:
    """Groups of columns that share no row: greedy, largest degree first, a
    stable sort (``colourColumns``). Each group lists its columns ascending."""
    cp = np.asarray(col_ptr, dtype=np.int64)
    ri = np.asarray(row_idx, dtype=np.int64)
    # rows -> the columns that touch them
    row_count = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(np.bincount(ri, minlength=n), out=row_count[1:])
    col_of = np.repeat(np.arange(n, dtype=np.int64), np.diff(cp))
    by_row = np.argsort(ri, kind='stable')
    row_cols = col_of[by_row].tolist()
    rc = row_count.tolist()
    cpl = cp.tolist()
    ril = ri.tolist()
    degree = np.diff(cp).tolist()
    order = sorted(range(n), key=lambda j: -degree[j])
    colour = [-1] * n
    taken = [False] * (n + 1)
    count = 0
    for j in order:
        touched = []
        for k in range(cpl[j], cpl[j + 1]):
            i = ril[k]
            for p in range(rc[i], rc[i + 1]):
                c = colour[row_cols[p]]
                if c >= 0 and not taken[c]:
                    taken[c] = True
                    touched.append(c)
        c = 0
        while taken[c]:
            c += 1
        colour[j] = c
        if c + 1 > count:
            count = c + 1
        for t in touched:
            taken[t] = False
    colours = np.array(colour, dtype=np.int64)
    by_colour = np.argsort(colours, kind='stable')
    sizes = np.bincount(colours, minlength=count) if n else np.zeros(0, dtype=np.int64)
    return np.split(by_colour, np.cumsum(sizes)[:-1]) if count else []


class JacobianCache:
    """J = df/du at (t, u) (``JacobianCache``).

    ``user_jac(t, u, cache)`` fills ``cache.values`` (sparse) or ``cache.J``
    (dense) and answers False to have this one point differenced instead.
    """

    def __init__(self, n: int, user_jac: Optional[Callable[..., bool]], jac_pattern: Optional[Pattern],
                 matrix: Optional[str], central: bool) -> None:
        self.n = n
        self.user_jac = user_jac
        self.central = bool(central)
        self.pattern = jac_pattern
        self.nf = 0
        self.njac = 0
        want = matrix or 'auto'
        nnz = int(jac_pattern[0][n]) if jac_pattern is not None else n * n
        self.sparse = want in ('sparse', 'refactor') or (want == 'auto' and jac_pattern is not None
                                                          and nnz < 0.25 * n * n)
        if self.pattern is None and (self.sparse or user_jac is None):
            self.pattern = dense_pattern(n)
        if self.sparse:
            self.values = np.zeros(int(self.pattern[0][n]))
            self.J: Optional[np.ndarray] = None
        else:
            self.values = None  # type: ignore[assignment]
            self.J = np.zeros((n, n))
        self.diff_pattern = self.pattern
        self.groups: Optional[List[np.ndarray]] = None
        self._plan: Optional[list] = None
        if self.pattern is not None:
            self._set_groups(colour_columns(n, self.pattern[0], self.pattern[1]))

    def _set_groups(self, groups: List[np.ndarray]) -> None:
        """The colouring, and per group the pattern entries it fills."""
        self.groups = groups
        col_ptr, row_idx = self.diff_pattern  # type: ignore[misc]
        plan = []
        lens = np.diff(col_ptr)
        for g in groups:
            glens = lens[g]
            total = int(glens.sum())
            starts = np.asarray(col_ptr, dtype=np.int64)[g]
            first = np.zeros(g.size, dtype=np.int64)
            if g.size:
                np.cumsum(glens[:-1], out=first[1:])
            entries = np.repeat(starts, glens) + (np.arange(total, dtype=np.int64) - np.repeat(first, glens))
            which = np.repeat(np.arange(g.size, dtype=np.int64), glens)
            plan.append((g, entries, np.asarray(row_idx, dtype=np.int64)[entries], which))
        self._plan = plan

    @property
    def group_count(self) -> int:
        return len(self.groups) if self.groups is not None else 0

    def evaluate(self, f: Callable[[float, np.ndarray], np.ndarray], t: float, u: np.ndarray, fu: np.ndarray) -> None:
        self.njac += 1
        if self.user_jac is not None and self.user_jac(t, u, self) is not False:
            return
        if self.groups is None:
            self.diff_pattern = dense_pattern(self.n)
            self._set_groups(colour_columns(self.n, self.diff_pattern[0], self.diff_pattern[1]))
        n = self.n
        if self.sparse:
            vals = self.values
            vals.fill(0.0)
        else:
            self.J.fill(0.0)  # type: ignore[union-attr]
            vals = None
        for g, entries, rows, which in self._plan:  # type: ignore[union-attr]
            upert = u.copy()
            ug = u[g]
            d = SQRT_EPS * np.maximum(np.abs(ug), 1e-5)
            upert[g] = ug + d
            self.nf += 1
            fpert = f(t, upert)
            if self.central:
                upert[g] = ug - d
                self.nf += 1
                back = f(t, upert)
                scale = 1.0 / (2.0 * d)
            else:
                back = fu
                scale = 1.0 / d
            v = (fpert[rows] - back[rows]) * scale[which]
            if vals is not None:
                vals[entries] = v
            else:
                self.J[rows, g[which]] = v  # type: ignore[index]


class WFactorization:
    """W = I - gh*J, or I/(gh) - J with ``transform``, formed and factorised
    (``WFactorization``)."""

    def __init__(self, n: int, jac_cache: JacobianCache, max_jac_age: Optional[float] = None,
                 reorder: bool = True) -> None:
        self.n = n
        self.jac_cache = jac_cache
        self.sparse = jac_cache.sparse
        self.nfactor = 0
        self.nsolve = 0
        # Whether a sparse factorisation has been attempted: the package's
        # `fill` is null until then, and the latest successful factor's after.
        self._factored = False
        self.ordering = 'none'
        if self.sparse:
            j_ptr, j_row = jac_cache.pattern  # type: ignore[misc]
            j_ptr = np.asarray(j_ptr, dtype=np.int64)
            j_row = np.asarray(j_row, dtype=np.int64)
            j_col = np.repeat(np.arange(n, dtype=np.int64), np.diff(j_ptr))
            diag = np.arange(n, dtype=np.int64)
            w_ptr, w_row = csc_from_triplets(n, np.concatenate([j_row, diag]), np.concatenate([j_col, diag]))
            self.w_ptr = w_ptr
            self.w_row = w_row
            w_col = np.repeat(np.arange(n, dtype=np.int64), np.diff(w_ptr))
            keys = w_col * n + w_row
            self.j_to_w = np.searchsorted(keys, j_col * n + j_row)
            self.diag_w = np.searchsorted(keys, diag * n + diag)
            self.w_values = np.zeros(w_row.size)
            perm = None if reorder is False else reverse_cuthill_mckee(n, w_ptr, w_row)
            self.ordering = 'reverse Cuthill-McKee' if perm is not None else 'natural'
            self.lu = SparseLU(n, w_ptr, w_row, perm)
        else:
            self.W = np.zeros((n, n))
            self._diag = np.arange(n)
            self.lu = DenseLU(n)  # type: ignore[assignment]
        self.gamma_dt = math.nan
        self.transform = False
        self.jac_t = math.nan
        self.jac_stale = True
        self.have_factor = False
        self.age = 0
        self.max_age = max_jac_age if max_jac_age is not None else 20

    def mark_stale(self) -> None:
        self.jac_stale = True

    def age_plus(self) -> None:
        self.age += 1

    @property
    def too_old(self) -> bool:
        return self.age >= self.max_age

    def is_current(self, t: float) -> bool:
        return not self.jac_stale and self.jac_t == t

    def form(self, f: Callable[[float, np.ndarray], np.ndarray], t: float, u: np.ndarray, fu: np.ndarray,
             gamma_dt: float, transform: bool, force_jac: bool = False) -> bool:
        if force_jac or self.jac_stale or self.too_old:
            self.jac_cache.evaluate(f, t, u, fu)
            self.jac_t = t
            self.jac_stale = False
            self.age = 0
            self.have_factor = False
        elif self.have_factor and self.gamma_dt == gamma_dt and self.transform == transform:
            return True
        jc = self.jac_cache
        if self.sparse:
            w = self.w_values
            w.fill(0.0)
            if transform:
                d = 1 / gamma_dt
                w[self.j_to_w] = -jc.values
                w[self.diag_w] += d
            else:
                w[self.j_to_w] = -gamma_dt * jc.values
                w[self.diag_w] += 1
            self.nfactor += 1
            ok = self.lu.factor(w)  # type: ignore[call-arg]
            self._factored = True
            self.have_factor = ok
            self.gamma_dt = gamma_dt
            self.transform = transform
            return ok
        W = self.W
        if transform:
            d = 1 / gamma_dt
            np.negative(jc.J, out=W)
            W[self._diag, self._diag] += d
        else:
            np.multiply(jc.J, -gamma_dt, out=W)
            W[self._diag, self._diag] += 1
        self.nfactor += 1
        ok = self.lu.factor(W)
        self.have_factor = ok
        self.gamma_dt = gamma_dt
        self.transform = transform
        return ok

    @property
    def fill(self) -> Optional[int]:
        """The package's ``fill``: null for a dense W or before the first
        factorisation, else the latest successful sparse factor's."""
        if not self.sparse or not self._factored:
            return None
        return self.lu.fill  # type: ignore[union-attr]

    def solve(self, b: np.ndarray) -> np.ndarray:
        self.nsolve += 1
        return self.lu.solve(b)
