"""The iteration matrix Mass - a*J: formed, factorised, solved with.

The application carries LUs of its own: a dense one, and for a sparse matrix a
searching Gilbert-Peierls LU and one that keeps its pivots, whole or a block
at a time. With numba, these are what factorise here. A sparse matrix is
factorised by the application's sparse LUs (``sparselu.py``), chosen as it
chooses them, on one real factorisation of each, and to its last bit. A dense one is
factorised by its dense LU (``kernels.py``) up to ``APP_LU_MAX`` states --
the application's arithmetic, and quicker than any library call on a small
system -- and by LAPACK beyond. Which is used follows the application's rule:
dense for small systems or where the sparse factor fills in past a share of
n^2, sparse otherwise. Without numba a dense matrix is LAPACK's and a sparse
one SuperLU's, through SciPy.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import scipy.linalg as la
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from ..jacobian import Pattern
from . import kernels as _k

# LAPACK's LU straight, without scipy.linalg's checking wrappers: on a small
# model the wrappers cost more than the factorisation.
_getrf, _getrs = la.lapack.get_lapack_funcs(('getrf', 'getrs'), (np.zeros(1),))

DENSE_MAX_BYTES = 2 * 1024 ** 3
#: Up to this many states a dense matrix is factorised by the application's
#: LU (when numba is installed); beyond it LAPACK's blocked one is quicker.
APP_LU_MAX = 200
#: ``auto`` factorises densely below this many states. The application goes
#: sparse from 24; the Julia engine goes sparse from here too, so that below
#: it the two engines' runs are the same to the bit (above it, KLU and the
#: application's sparse LUs agree to round-off).
DENSE_BELOW = 64
DENSE_FILL = 0.15
#: The column orderings SuperLU is tried with, the model's own first.
ORDERINGS = ('NATURAL', 'COLAMD', 'MMD_AT_PLUS_A')
#: The model's own order is kept while its factors fill in no more than this
#: times the least of the others'. SuperLU works faster in it at equal fill --
#: no permutation, the diagonal kept as the pivots -- by about two on a
#: landscape model of 8,000 states whose own order filled in 13% more than
#: COLAMD's; a model declared in a scattered order fills in several times
#: more, and is reordered.
NATURAL_MARGIN = 1.5


def _matrix_name(mass: Optional[np.ndarray]) -> str:
    return 'M - h*J' if mass is not None else 'I - h*J'


def singular_message(mass: Optional[np.ndarray], column: int, hint: Optional[str]) -> str:
    if mass is not None and mass[column] == 0:
        return (f'The iteration matrix M - h*J is singular at the algebraic variable in column {column}: its '
                'constraint does not determine it. Check that the constraint depends on its own variable, that no '
                'two constraints say the same thing, and that the system is index 1.')
    base = f'The iteration matrix {_matrix_name(mass)} is singular at column {column}'
    return f'{base}. {hint}' if hint else base


def non_finite_message(mass: Optional[np.ndarray], column: int, value: float) -> str:
    return (f'The iteration matrix {_matrix_name(mass)} has an entry that is not a number ({value}) at column '
            f'{column}: the Jacobian has a non-finite entry there.')


class IterationMatrix:
    """``form(a, J, held)`` factorises Mass - a*J with the rows ``held`` marks
    as rows of the identity; ``solve(rhs)`` answers for the latest one.

    ``J`` is the pattern's values (a flat array) when there is a pattern, and a
    dense (n, n) array otherwise.
    """

    def __init__(self, n: int, pattern: Optional[Pattern], values: Any, mode: str = 'auto',
                 mass: Optional[np.ndarray] = None, hints: Optional[Dict[str, str]] = None,
                 dense_below: int = DENSE_BELOW, dense_fill: float = DENSE_FILL) -> None:
        self.n = n
        self.pattern = pattern
        self.mass = mass
        self.hints = hints or {}
        self._info: Dict[str, Any] = {'sparse': False, 'lu': 'dense', 'fill': None, 'ordering': 'natural',
                                      'nnz': pattern.nnz if pattern else n * n, 'repivots': 0, 'fallbacks': 0}
        too_big = n * n * 8 > DENSE_MAX_BYTES
        #: The application's sparse LUs' matrix, where they take it (``sparselu``).
        self._sw: Any = None
        self._lu: Any = None
        self._diag = np.arange(n)
        self._kernels = n <= APP_LU_MAX and _k.available()
        if self._kernels:
            self._lu_buf = np.zeros((n, n))
            self._piv = np.zeros(n, dtype=np.int64)
            self._fail = np.zeros(2)
            self._no_held = np.zeros(n, dtype=np.bool_)
            self._mass_diag = np.ones(n) if mass is None else np.asarray(mass, dtype=float)
            if pattern is not None:
                self._col_ptr = np.ascontiguousarray(pattern.col_ptr, dtype=np.int64)
                self._row_idx = np.ascontiguousarray(pattern.row_idx, dtype=np.int64)
            self._form_pattern = _k.kernel('pattern')
            self._form_dense = _k.kernel('dense')
            self._solve_kernel = _k.kernel('solve')
        if pattern is None:
            if too_big:
                raise RuntimeError(f'This model has {n} states, and without a sparsity pattern the solver would '
                                   f'have to hold the iteration matrix as {n} by {n} numbers -- '
                                   f'{n * n * 8 / 1073741824:.1f} GB. ' + (self.hints.get('noPattern') or ''))
            self.sparse = False
            return
        if pattern is not None:
            self._diag_entries = self._find_diagonal(pattern)
            self._union_structure(pattern)
        if mode == 'dense' and not too_big:
            self.sparse = False
            return
        if mode == 'auto' and n < dense_below and not too_big:
            self.sparse = False
            return
        sparse_lu = _sparse_lu()
        if sparse_lu is not None:
            sw = sparse_lu.decide(n, pattern.col_ptr, pattern.row_idx, values, mode, mass, dense_fill, too_big)
            got = sparse_lu.state(sw)
            self._info.update(fill=got['fill'], ordering=got['ordering'])
            if got['kind'] == sparse_lu.DENSE:
                self.sparse = False
                return
            self._sw = sw
            self.sparse = True
            self._info.update(sparse=True, lu=got['lu'])
            return
        self.sparse = True
        self._permc = 'COLAMD'
        if not too_big:
            # Which column ordering, and whether to be sparse at all, decided
            # on real factorisations of the first matrix rather than on the
            # pattern's promise -- the application's rule, and by its measure,
            # the fill of the factors. The model's own order is kept unless
            # another fills in far less (see NATURAL_MARGIN). Never by time:
            # a choice made on the clock changes with the machine's load, and
            # with it the round-off of every solve and the steps a run takes.
            fills: Dict[str, int] = {}
            M = self._sparse_matrix(1e-3, values, None).tocsc()
            for spec in ORDERINGS:
                try:
                    trial = spla.splu(M, permc_spec=spec)
                except RuntimeError:
                    continue
                fills[spec] = int(trial.L.nnz + trial.U.nnz)
            if fills:
                least = min(fills.values())
                if 'NATURAL' in fills and fills['NATURAL'] <= NATURAL_MARGIN * least:
                    self._permc = 'NATURAL'
                else:
                    self._permc = min(fills, key=lambda k: (fills[k], ORDERINGS.index(k)))
                self._info['fill'] = fills[self._permc]
                if mode == 'auto' and fills[self._permc] > dense_fill * n * n:
                    self.sparse = False
        if self.sparse:
            self._info.update(sparse=True, lu='SuperLU', ordering=self._permc)

    @property
    def info(self) -> Dict[str, Any]:
        """Which LU, how full its factor is, and how often the kept pivots were
        chosen again or a matrix went elsewhere -- the application's ``info``."""
        if self._sw is not None:
            got = _sparse_lu().state(self._sw)  # type: ignore[union-attr]
            self._info.update(fill=got['fill'], repivots=got['repivots'], fallbacks=got['fallbacks'])
        return self._info

    @staticmethod
    def _find_diagonal(pattern: Pattern) -> np.ndarray:
        """Where each column's diagonal entry sits among the values (-1 for none)."""
        n = pattern.n
        out = np.full(n, -1, dtype=np.int64)
        rows = pattern.row_idx
        cols = pattern.col_of
        hit = np.nonzero(rows == cols)[0]
        out[cols[hit]] = hit
        return out

    def _masked(self, J: np.ndarray, held: Optional[np.ndarray]) -> np.ndarray:
        if held is None:
            return J
        use = J.copy()
        use[held[self.pattern.row_idx].astype(bool)] = 0.0  # type: ignore[union-attr]
        return use

    def _union_structure(self, p: Pattern) -> None:
        """The structure of Mass - a*J -- the pattern and the diagonal, in
        compressed columns -- worked out once, with where each of the
        pattern's entries and each diagonal entry sits in it; every matrix
        formed afterwards only fills its values in."""
        n = self.n
        rows = np.concatenate([p.row_idx, np.arange(n, dtype=np.int64)])
        cols = np.concatenate([p.col_of, np.arange(n, dtype=np.int64)])
        u = sp.csc_matrix((np.ones(rows.size), (rows, cols)), shape=(n, n))
        u.sum_duplicates()
        u.sort_indices()
        self._u_indptr = u.indptr
        self._u_indices = u.indices
        # Position of (row, col) in the union: the entries are in column-major
        # order, sorted within a column, so col * n + row is increasing.
        keys = np.repeat(np.arange(n, dtype=np.int64), np.diff(u.indptr)) * n + u.indices

        def where(r: np.ndarray, c: np.ndarray) -> np.ndarray:
            return np.searchsorted(keys, np.asarray(c, dtype=np.int64) * n + np.asarray(r, dtype=np.int64))

        self._u_pattern = where(p.row_idx, p.col_of)
        self._u_diag = where(np.arange(n), np.arange(n))
        self._u_diag_add = np.ones(n) if self.mass is None else np.asarray(self.mass, dtype=float)

    def _sparse_matrix(self, a: float, J: np.ndarray, held: Optional[np.ndarray]) -> sp.csc_matrix:
        # The values of -a*J scattered into the union, and the diagonal added
        # to them: the same two roundings as forming -a*J and adding
        # diag(Mass) to it as matrices, without building two matrices.
        data = np.zeros(self._u_indices.size)
        data[self._u_pattern] = -a * self._masked(J, held)
        data[self._u_diag] += self._u_diag_add
        return sp.csc_matrix((data, self._u_indices, self._u_indptr), shape=(self.n, self.n))

    def _form_with_kernel(self, a: float, J: Any, held: Optional[np.ndarray]) -> None:
        h = self._no_held if held is None else np.asarray(held, dtype=np.bool_)
        values = np.ascontiguousarray(J, dtype=float)
        if self.pattern is None:
            status = self._form_dense(float(a), values, h, self._mass_diag, self._lu_buf, self._piv, self._fail)
        else:
            status = self._form_pattern(float(a), self._col_ptr, self._row_idx, values, h, self._mass_diag,
                                        self._lu_buf, self._piv, self._fail)
        if status:
            col, value = int(self._fail[0]), float(self._fail[1])
            if status == -_k.NONFINITE or status == _k.NONFINITE:
                raise RuntimeError(non_finite_message(self.mass, col, value))
            raise RuntimeError(singular_message(self.mass, col, self.hints.get('singular')))
        self._lu = 'kernel'
        self._dense = True

    def form(self, a: float, J: Any, held: Optional[np.ndarray] = None) -> None:
        n = self.n
        mass = self.mass
        if self._sw is not None:
            splu = _sparse_lu()
            status = splu.form(self._sw, a, J, held)  # type: ignore[union-attr]
            if status:
                got = splu.state(self._sw)  # type: ignore[union-attr]
                if status == splu.NONFINITE:  # type: ignore[union-attr]
                    raise RuntimeError(non_finite_message(mass, got['column'], got['value']))
                raise RuntimeError(singular_message(mass, got['column'], self.hints.get('singular')))
            return
        if self._kernels and not self.sparse:
            self._form_with_kernel(a, J, held)
            return
        if self.pattern is None:
            W = -a * np.asarray(J, dtype=float)
            if held is not None:
                W[held.astype(bool), :] = 0.0
        else:
            vals = self._masked(np.asarray(J, dtype=float), held)
            bad = ~np.isfinite(vals)
            if bad.any():
                k = int(np.nonzero(bad)[0][0])
                raise RuntimeError(non_finite_message(mass, int(self.pattern.col_of[k]), float(vals[k])))
            if self.sparse:
                M = self._sparse_matrix(a, vals, None)
                try:
                    self._lu = spla.splu(M, permc_spec=self._permc)
                except RuntimeError:
                    raise RuntimeError(singular_message(mass, self._singular_column(M), self.hints.get('singular'))) \
                        from None
                self._dense = False
                return
            W = np.zeros((n, n))
            p = self.pattern
            W[p.row_idx, p.col_of] = -a * vals
        W[self._diag, self._diag] += 1.0 if mass is None else mass
        if not np.all(np.isfinite(W)):
            bad = np.argwhere(~np.isfinite(W))[0]
            raise RuntimeError(non_finite_message(mass, int(bad[1]), float(W[bad[0], bad[1]])))
        lu, piv, info = _getrf(W, overwrite_a=True)
        if info > 0 or (info == 0 and np.any(np.diag(lu) == 0)):
            col = info - 1 if info > 0 else int(np.nonzero(np.diag(lu) == 0)[0][0])
            raise RuntimeError(singular_message(mass, col, self.hints.get('singular')))
        self._lu = (lu, piv)
        self._dense = True

    def _singular_column(self, M: sp.csc_matrix) -> int:
        try:
            dense = M.toarray()
            lu, piv = la.lu_factor(dense, check_finite=False)
            zero = np.nonzero(np.abs(np.diag(lu)) == 0)[0]
            return int(zero[0]) if zero.size else 0
        except Exception:  # noqa: BLE001 - only for the message
            return 0

    def solve(self, rhs: np.ndarray) -> np.ndarray:
        if self._sw is not None:
            return _sparse_lu().solve(self._sw, rhs)  # type: ignore[union-attr]
        if self._dense:
            if self._lu == 'kernel':
                return self._solve_kernel(self._lu_buf, self._piv, np.ascontiguousarray(rhs, dtype=float),
                                          np.empty(self.n))
            x, _ = _getrs(self._lu[0], self._lu[1], rhs)
            return x
        return self._lu.solve(rhs)


_SPARSE_LU: list = []


def _sparse_lu() -> Any:
    """The application's sparse LUs (:mod:`.sparselu`), compiled and tried
    once on a small matrix; None without numba, or where they would not
    compile, and a sparse matrix is then SuperLU's."""
    if not _SPARSE_LU:
        mod = None
        if _k.available():
            try:
                from . import sparselu as mod
                # Each mode, with blocks and without, once with rows held.
                col_ptr = np.array([0, 2, 4, 5], dtype=np.int64)
                row_idx = np.array([0, 1, 0, 1, 2], dtype=np.int64)
                values = np.array([-1.0, 0.5, 0.25, -2.0, -1.0])
                for mode in ('auto', 'refactor', 'sparse'):
                    for blocks in (True, False):
                        sw = mod.decide(3, col_ptr, row_idx, values, mode, None, 0.15, False, blocks)
                        mod.form(sw, 0.5, values)
                        mod.form(sw, 0.5, values, np.array([0, 0, 1]))
                        mod.solve(sw, np.ones(3))
                        mod.state(sw)
            except Exception:  # noqa: BLE001 - numba refusing: SuperLU, as without it
                mod = None
        _SPARSE_LU.append(mod)
    return _SPARSE_LU[0]
