"""The package's sparse LU (``SparseLU`` in ``src/ode/julia/core/linalg.js``), compiled with numba.

A left-looking LU with partial pivoting (Gilbert and Peierls) behind a column
ordering: column k of the factorised matrix is column ``perm[k]`` of W. Step
for step the package's -- the same depth-first search, the same eliminations
in the same order, the same pivots (the first largest, in the order the search
leaves the rows), one rounding per operation, numba fusing no multiply and add
-- so W is factorised and solved with as the application does it, to the last
bit, where SciPy's SuperLU agreed with it to rounding.

The Julia-derived solvers take it for a sparse W (:mod:`.linalg`); their
compiled loop (``engine/compiled/julia.py``) factorises and solves with it in
place, its state a numba ``structref`` the loop takes as an argument, where it
called SuperLU back in Python for every factorisation and every solve.
Without numba the solvers keep to SuperLU.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
from numba import njit, types
from numba.experimental import structref

from ...compiled import guard_numba_cache

guard_numba_cache()

_OPTS = dict(cache=True, nogil=True, error_model='numpy')

_i = types.int64
_I = types.int64[::1]
_A = types.float64[::1]


@structref.register
class PackageLUType(types.StructRef):
    def preprocess_fields(self, fields: Any) -> Any:
        return tuple((name, types.unliteral(typ)) for name, typ in fields)


class PackageLUState(structref.StructRefProxy):
    """The package's sparse LU as Python holds it."""


structref.define_boxing(PackageLUType, PackageLUState)

#: W's pattern, the column order, the work of one column (its dense
#: accumulator, the rows the search marked, its stacks and the rows it found),
#: the pivots, L by columns without its unit diagonal, U by columns with the
#: pivot last, and how the latest factorisation went.
LU_T = PackageLUType(fields=(
    ('n', _i), ('colptr', _I), ('rowidx', _I), ('perm', _I), ('has_perm', _i), ('x', _A), ('mark', _I),
    ('stack', _I), ('pstack', _I),
    ('pattern', _I), ('piv', _I), ('pinv', _I), ('Lp', _I), ('Li', _I), ('Lx', _A), ('Up', _I), ('Ui', _I),
    ('Ux', _A), ('singular', _i), ('fill', _i)))


@njit(**_OPTS)
def lu_new(n, colptr, rowidx, perm, has_perm):
    """``new SparseLU(n, colPtr, rowIdx, perm)``: the factor starts at a few
    times the matrix's entries and doubles as it needs to."""
    lu = structref.new(LU_T)
    lu.n = n
    lu.colptr = colptr
    lu.rowidx = rowidx
    lu.perm = perm
    lu.has_perm = has_perm
    lu.x = np.zeros(n)
    lu.mark = np.full(n, -1, np.int64)
    lu.stack = np.zeros(n, np.int64)
    lu.pstack = np.zeros(n, np.int64)
    lu.pattern = np.zeros(n, np.int64)
    lu.piv = np.zeros(n, np.int64)
    lu.pinv = np.full(n, -1, np.int64)
    guess = max(4 * colptr[n] + n, 16)
    lu.Lp = np.zeros(n + 1, np.int64)
    lu.Li = np.zeros(guess, np.int64)
    lu.Lx = np.zeros(guess)
    lu.Up = np.zeros(n + 1, np.int64)
    lu.Ui = np.zeros(guess, np.int64)
    lu.Ux = np.zeros(guess)
    lu.singular = 0
    lu.fill = 0
    return lu


@njit(**_OPTS)
def _grow_l(lu, need):
    if need <= lu.Li.size:
        return
    cap = max(need, lu.Li.size * 2)
    Li = np.zeros(cap, np.int64)
    Li[:lu.Li.size] = lu.Li
    lu.Li = Li
    Lx = np.zeros(cap)
    Lx[:lu.Lx.size] = lu.Lx
    lu.Lx = Lx


@njit(**_OPTS)
def _grow_u(lu, need):
    if need <= lu.Ui.size:
        return
    cap = max(need, lu.Ui.size * 2)
    Ui = np.zeros(cap, np.int64)
    Ui[:lu.Ui.size] = lu.Ui
    lu.Ui = Ui
    Ux = np.zeros(cap)
    Ux[:lu.Ux.size] = lu.Ux
    lu.Ux = Ux


@njit(**_OPTS)
def _reach(lu, j, top0):
    """``_reach``: every row column j can fill, by depth-first search over the
    graph of L, written into ``pattern`` in topological order (last first);
    where they start."""
    colptr = lu.colptr
    rowidx = lu.rowidx
    stack = lu.stack
    pstack = lu.pstack
    pattern = lu.pattern
    mark = lu.mark
    pinv = lu.pinv
    Lp = lu.Lp
    Li = lu.Li
    top = top0
    for p in range(colptr[j], colptr[j + 1]):
        i = rowidx[p]
        if mark[i] == j:
            continue
        head = 0
        stack[0] = i
        while head >= 0:
            i = stack[head]
            pi = pinv[i]
            if mark[i] != j:
                mark[i] = j
                pstack[head] = 0 if pi < 0 else Lp[pi]
            start = pstack[head]
            done = True
            end = 0 if pi < 0 else Lp[pi + 1]
            for k in range(start, end):
                child = Li[k]
                if mark[child] == j:
                    continue
                pstack[head] = k + 1
                head += 1
                stack[head] = child
                done = False
                break
            if done:
                head -= 1
                top -= 1
                pattern[top] = i
    return top


@njit(**_OPTS)
def lu_factor(lu, values):
    """``factor``: the matrix of ``values`` over W's pattern; False (and
    ``singular``) where a column has no pivot, or only a zero."""
    n = lu.n
    colptr = lu.colptr
    rowidx = lu.rowidx
    x = lu.x
    mark = lu.mark
    pattern = lu.pattern
    piv = lu.piv
    pinv = lu.pinv
    for i in range(n):
        mark[i] = -1
        pinv[i] = -1
    lnz = 0
    unz = 0
    lu.singular = 0
    for k in range(n):
        lu.Lp[k] = lnz
        lu.Up[k] = unz
        _grow_l(lu, lnz + n)
        _grow_u(lu, unz + n)
        j = lu.perm[k] if lu.has_perm else k
        top = _reach(lu, j, n)
        # Column j of A, scattered into the accumulator.
        for t in range(top, n):
            x[pattern[t]] = 0.0
        for p in range(colptr[j], colptr[j + 1]):
            x[rowidx[p]] = values[p]
        # The sparse triangular solve against the columns already done.
        Lp = lu.Lp
        Li = lu.Li
        Lx = lu.Lx
        for t in range(top, n):
            i = pattern[t]
            pi = pinv[i]
            if pi < 0:
                continue
            xi = x[i]
            if xi == 0:
                continue
            for p in range(Lp[pi], Lp[pi + 1]):
                x[Li[p]] -= Lx[p] * xi
        # The largest entry not yet in U, the first of equals.
        ipiv = -1
        big = 0.0
        for t in range(top, n):
            i = pattern[t]
            if pinv[i] >= 0:
                continue
            v = abs(x[i])
            if v > big:
                big = v
                ipiv = i
        if ipiv < 0 or big == 0:
            lu.singular = 1
            return False
        pivot = x[ipiv]
        pinv[ipiv] = k
        piv[k] = ipiv
        Ui = lu.Ui
        Ux = lu.Ux
        for t in range(top, n):
            i = pattern[t]
            pi = pinv[i]
            if pi < 0 or pi == k:
                continue
            if x[i] != 0:
                Ui[unz] = pi
                Ux[unz] = x[i]
                unz += 1
        Ui[unz] = k
        Ux[unz] = pivot
        unz += 1
        for t in range(top, n):
            i = pattern[t]
            if pinv[i] >= 0:
                continue
            if x[i] != 0:
                Li[lnz] = i
                Lx[lnz] = x[i] / pivot
                lnz += 1
    lu.Lp[n] = lnz
    lu.Up[n] = unz
    lu.fill = lnz + unz
    return True


@njit(**_OPTS)
def lu_solve(lu, b):
    """``solve``: L U x = P b, in place in ``b``."""
    n = lu.n
    piv = lu.piv
    x = lu.x
    Lp = lu.Lp
    Li = lu.Li
    Lx = lu.Lx
    Up = lu.Up
    Ui = lu.Ui
    Ux = lu.Ux
    for i in range(n):
        x[i] = b[i]
    for k in range(n):
        i = piv[k]
        xk = x[i]
        if xk == 0:
            continue
        for p in range(Lp[k], Lp[k + 1]):
            x[Li[p]] -= Lx[p] * xk
    y = b
    for k in range(n):
        y[k] = x[piv[k]]
    for k in range(n - 1, -1, -1):
        end = Up[k + 1] - 1
        y[k] /= Ux[end]
        yk = y[k]
        if yk == 0:
            continue
        for p in range(Up[k], end):
            y[Ui[p]] -= Ux[p] * yk
    if lu.has_perm:
        for k in range(n):
            x[k] = y[k]
        for k in range(n):
            b[lu.perm[k]] = x[k]
    return b


@njit(**_OPTS)
def lu_state(lu):
    return lu.singular, lu.fill


class SparseLU:
    """``SparseLU`` as :mod:`.linalg`'s callers take it: ``factor(values)``,
    ``solve(b)``, and ``fill`` and ``singular`` after the latest
    factorisation, here or in a compiled loop handed ``state``."""

    def __init__(self, n: int, col_ptr: np.ndarray, row_idx: np.ndarray, perm: Optional[np.ndarray]) -> None:
        self.n = n
        self.perm = perm
        p = np.ascontiguousarray(perm, dtype=np.int64) if perm is not None else np.zeros(0, dtype=np.int64)
        self.state = lu_new(n, np.ascontiguousarray(col_ptr, dtype=np.int64),
                            np.ascontiguousarray(row_idx, dtype=np.int64), p, perm is not None)

    def factor(self, values: np.ndarray) -> bool:
        return bool(lu_factor(self.state, np.ascontiguousarray(values, dtype=float)))

    @property
    def singular(self) -> bool:
        return bool(lu_state(self.state)[0])

    @property
    def fill(self) -> int:
        """Non-zeros in L below the diagonal and in U, after the latest
        successful factorisation (the package's ``fill``)."""
        return int(lu_state(self.state)[1])

    def solve(self, b: np.ndarray) -> np.ndarray:
        x = np.array(b, dtype=float)
        lu_solve(self.state, x)
        return x


_NONE: list = []


def none() -> Any:
    """An LU of no states: what the compiled loop is handed when it does not factorise with one."""
    if not _NONE:
        empty = np.zeros(0, dtype=np.int64)
        _NONE.append(lu_new(0, np.zeros(1, dtype=np.int64), empty, empty, False))
    return _NONE[0]


__all__ = ('LU_T', 'SparseLU', 'lu_factor', 'lu_new', 'lu_solve', 'none')
