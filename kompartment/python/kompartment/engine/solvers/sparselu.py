"""The application's sparse LUs, compiled with numba.

``src/ode/core/sparse.js`` factorises a sparse iteration matrix Mass - a*J with
one of three LUs, and chooses between them on one real factorisation of each:
Gilbert-Peierls with partial pivoting, in the model's own column order or in
reverse Cuthill-McKee's (``SparseLU``); an LU that keeps its pivots from one
factorisation to the next (``refactor.js``, ``RefactorLU``); and that LU a
block at a time, where the matrix falls into blocks one way round
(``blocks.js``, ``BlockLU``). This module is those three LUs and that choice,
step for step -- the same pivots, the same eliminations in the same order,
one rounding per operation -- so a sparse matrix is factorised and solved
with as the application does it, to the last bit.

They run where the solver's loop runs. The compiled NDF and Rosenbrock (2,3)
loops (``..compiled.solvers``) form and solve with them in place, so a sparse
run no longer goes back to Python for every factorisation and every solve, as
it did with SuperLU; the Python solvers reach them through
:class:`.matrix.IterationMatrix`. A matrix's state is a numba ``structref``,
which both can hold, and which keeps the arrays the kept-pivot LU grows when
it chooses its pivots again in the middle of a run.

numba is needed; without it :mod:`.matrix` keeps to SuperLU.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

import numpy as np
from numba import njit, types
from numba.experimental import structref
from numba.typed import List

from ..compiled import guard_numba_cache

guard_numba_cache()

_OPTS = dict(cache=True, nogil=True, error_model='numpy')

#: ``refactor.js``: a pivot is chosen among the entries at least this share
#: of the largest in their column, and kept while none below it is more than
#: 1/KEEP_THRESHOLD times it; the SEARCH_COLUMNS sparsest columns are
#: searched; and past REORDER_GROWTH times the work of the last choice made
#: from the start, the pivots are chosen from the start again.
PIVOT_THRESHOLD = 0.1
KEEP_THRESHOLD = 0.01
SEARCH_COLUMNS = 16
REORDER_GROWTH = 1.2
#: ``refactor.js``: the record holds one index per multiply-add, and past this
#: many ``auto`` leaves the matrix to the Gilbert-Peierls LU.
OPS_BUDGET = 4e6

#: What a matrix is factorised with: the caller's dense LU (``auto`` chose
#: it), the Gilbert-Peierls LU, the kept-pivot LU whole, or a block at a time.
DENSE, SPARSE, WHOLE, BLOCKS = 0, 1, 2, 3
#: The column orders, as ``info.ordering`` names them.
ORDERINGS = ('natural', 'reverse Cuthill-McKee', 'threshold Markowitz', 'natural columns, threshold rows',
             'reverse Cuthill-McKee columns, threshold rows', 'block triangular, threshold Markowitz')
_NATURAL, _RCM, _MARKOWITZ, _NATURAL_COLUMNS, _RCM_COLUMNS, _BLOCKED = range(6)
#: The modes ``iterationMatrix`` takes a sparse LU in.
MODES = {'auto': 0, 'refactor': 1, 'sparse': 2}
_AUTO, _REFACTOR = 0, 1
#: Which LU the latest factorisation is in: the kept-pivot one, or what a
#: matrix it declined went to -- or none, the latest formation having failed
#: (or none made yet, where there was no trial), which no solve reads.
_KEPT, _BY_SPARSE, _BY_DENSE, _NONE_MADE = 0, 1, 2, 3
#: A formation's outcome: factorised, singular, or a value not a number.
OK, SINGULAR, NONFINITE = 0, 1, 2

_i = types.int64
_f = types.float64
_I = types.int64[::1]
_A = types.float64[::1]
_M = types.float64[:, ::1]


def _plain(fields: Any) -> Any:
    return tuple((name, types.unliteral(typ)) for name, typ in fields)


@structref.register
class SparseLUType(types.StructRef):
    def preprocess_fields(self, fields: Any) -> Any:
        return _plain(fields)


@structref.register
class RefactorLUType(types.StructRef):
    def preprocess_fields(self, fields: Any) -> Any:
        return _plain(fields)


@structref.register
class BlockLUType(types.StructRef):
    def preprocess_fields(self, fields: Any) -> Any:
        return _plain(fields)


@structref.register
class SparseMatrixType(types.StructRef):
    def preprocess_fields(self, fields: Any) -> Any:
        return _plain(fields)


class SparseLUState(structref.StructRefProxy):
    """A Gilbert-Peierls LU as Python holds it."""


class RefactorLUState(structref.StructRefProxy):
    """A kept-pivot LU as Python holds it."""


class BlockLUState(structref.StructRefProxy):
    """A block-at-a-time LU as Python holds it."""


class SparseMatrixState(structref.StructRefProxy):
    """A sparse iteration matrix as Python holds it: see :func:`decide`."""


structref.define_boxing(SparseLUType, SparseLUState)
structref.define_boxing(RefactorLUType, RefactorLUState)
structref.define_boxing(BlockLUType, BlockLUState)
structref.define_boxing(SparseMatrixType, SparseMatrixState)

#: ``SparseLU``: the row each step pivots on (pinv by row, perm by step), the
#: column order (qcol, used where has_q), the depth-first search's work, L by
#: columns with the unit diagonal first and U with the pivot last, a solve's
#: work, and how the latest factorisation went.
GP_T = SparseLUType(fields=(
    ('n', _i), ('pinv', _I), ('perm', _I), ('qcol', _I), ('has_q', _i),
    ('x', _A), ('xi', _I), ('stack', _I), ('pstack', _I), ('mark', _I), ('stamp', _i),
    ('Lp', _I), ('Li', _I), ('Lx', _A), ('Up', _I), ('Ui', _I), ('Ux', _A), ('t', _A),
    ('lnz', _i), ('unz', _i), ('flops', _i), ('singular', _i), ('nonfinite', _i), ('over', _i),
    ('fail_column', _i), ('fail_original', _i)))

#: ``RefactorLU``: the slots (every entry of the matrix and its fill, by
#: row and column, the pattern's and the diagonal's places among them), the
#: record of the steps, the factor as a solve reads it, and the work of
#: choosing -- each row's and column's slots in one pool, a list each.
RF_T = RefactorLUType(fields=(
    ('n', _i), ('nnzj', _i), ('columns', _I), ('has_columns', _i),
    ('slot_row', _I), ('slot_col', _I), ('jslot', _I), ('dslot', _I), ('nbase', _i), ('nslots', _i), ('V', _A),
    ('pr', _I), ('pc', _I), ('pslot', _I), ('lstart', _I), ('ustart', _I), ('tstart', _I), ('fill_start', _I),
    ('lslot', _I), ('lrow', _I), ('uslot', _I), ('ucol', _I), ('T', _I),
    ('lval', _A), ('lstep', _I), ('uval', _A), ('ustep', _I), ('dval', _A), ('row_step', _I), ('col_step', _I),
    ('valid', _i), ('ops', _i), ('nnz', _i), ('repivots', _i), ('full_ops', _i), ('limit', _f),
    ('row_active', _I), ('col_active', _I), ('rc', _I), ('cc', _I), ('head', _I), ('nxt', _I), ('prv', _I),
    ('at', _I), ('at_stamp', _I),
    ('row_start', _I), ('row_len', _I), ('row_cap', _I), ('col_start', _I), ('col_len', _I), ('col_cap', _I),
    ('pool', _I), ('pool_top', _i), ('z', _A)))

#: ``BlockLU``: the blocks and their states, the entries between blocks, a
#: kept-pivot LU for each block of more than one state (lu_of, -1 for one of
#: one state) and where J holds its entries, and the factor laid out by step
#: in the order the solve takes the blocks.
BK_T = BlockLUType(fields=(
    ('n', _i), ('nblocks', _i), ('start', _I), ('member', _I),
    ('off_ptr', _I), ('off_row', _I), ('off_pos', _I), ('diag_pos', _I), ('lu_of', _I),
    ('lus', types.ListType(RF_T)), ('pos_ptr', _I), ('pos', _I), ('b_values', _A), ('b_mass', _A),
    ('base', _I), ('row_of_step', _I), ('col_of_step', _I), ('step_of_row', _I), ('seg_start', _I),
    ('seg_block', _I), ('Lp', _I), ('Up', _I), ('Li', _I), ('Lx', _A), ('Ui', _I), ('Ux', _A), ('D', _A),
    ('off_p', _I), ('off_step', _I), ('off_at', _I), ('off_x', _A), ('zs', _A),
    ('laid_out', _i), ('valid', _i), ('ops', _i), ('limit', _f), ('nnz', _i)))

#: ``iterationMatrix``: J's pattern, the structure of Mass - a*J in CSC
#: (``makeMiterBuilder``), the Gilbert-Peierls LU and its column order, the
#: kept-pivot LU (whole, or a block at a time), the dense LU a declined
#: matrix goes to where the factor fills in, and ``info``.
SW_T = SparseMatrixType(fields=(
    ('n', _i), ('kind', _i), ('colptr', _I), ('rowidx', _I), ('masked', _A), ('mass', _A), ('has_mass', _i),
    ('mp', _I), ('mi', _I), ('mx', _A), ('jtom', _I), ('diag_pos', _I),
    ('gp', GP_T), ('q', _I), ('has_q', _i), ('whole', RF_T), ('blocks', BK_T), ('fills_in', _i),
    ('current', _i), ('dense', _M), ('dpiv', _I),
    ('fill', _i), ('repivots', _i), ('fallbacks', _i), ('trial_repivots', _i), ('ordering', _i),
    ('fail_column', _i), ('fail_value', _f), ('fail_nonfinite', _i)))


# --- room -------------------------------------------------------------------------------------------


@njit(**_OPTS)
def _room_i(a, need):
    """``a``, or a copy of it with room for ``need`` (``room`` in refactor.js)."""
    if need <= a.size:
        return a
    cap = max(a.size, 64)
    while cap < need:
        cap *= 2
    b = np.zeros(cap, np.int64)
    b[:a.size] = a
    return b


@njit(**_OPTS)
def _room_f(a, need):
    if need <= a.size:
        return a
    cap = max(a.size, 64)
    while cap < need:
        cap *= 2
    b = np.zeros(cap)
    b[:a.size] = a
    return b


# --- Mass - a*J in CSC (``makeMiterBuilder``) --------------------------------------------------------


@njit(**_OPTS)
def miter_structure(n, colptr, rowidx):
    """The pattern of Mass - a*J -- J's with the diagonal, each column's rows
    in order -- and where J's entries (jtom) and the diagonal sit in it."""
    nzj = colptr[n]
    mp = np.zeros(n + 1, np.int64)
    mi = np.zeros(nzj + n, np.int64)
    k = 0
    for j in range(n):
        m = colptr[j + 1] - colptr[j]
        rows = np.empty(m + 1, np.int64)
        for p in range(m):
            rows[p] = rowidx[colptr[j] + p]
        rows[m] = j
        rows.sort()
        mp[j] = k
        last = -1
        for r in rows:
            if r != last:
                mi[k] = r
                k += 1
                last = r
    mp[n] = k
    mi = mi[:k].copy()
    pos = np.full(n, -1, np.int64)
    jtom = np.zeros(nzj, np.int64)
    diag = np.full(n, -1, np.int64)
    for j in range(n):
        for p in range(mp[j], mp[j + 1]):
            pos[mi[p]] = p
        for p in range(colptr[j], colptr[j + 1]):
            jtom[p] = pos[rowidx[p]]
        diag[j] = pos[j]
        for p in range(mp[j], mp[j + 1]):
            pos[mi[p]] = -1
    return mp, mi, jtom, diag


@njit(**_OPTS)
def miter_update(a, values, mass, has_mass, mx, jtom, diag):
    """mx := the values of Mass - a*J (``update``)."""
    for p in range(mx.size):
        mx[p] = 0.0
    for p in range(jtom.size):
        mx[jtom[p]] = -a * values[p]
    if has_mass:
        for i in range(diag.size):
            mx[diag[i]] += mass[i]
    else:
        for i in range(diag.size):
            mx[diag[i]] += 1.0


# --- Gilbert-Peierls LU (``SparseLU``) ---------------------------------------------------------------


@njit(**_OPTS)
def gp_new(n):
    g = structref.new(GP_T)
    g.n = n
    g.pinv = np.zeros(n, np.int64)
    g.perm = np.zeros(n, np.int64)
    g.qcol = np.zeros(0, np.int64)
    g.has_q = 0
    g.x = np.zeros(n)
    g.xi = np.zeros(n, np.int64)
    g.stack = np.zeros(n, np.int64)
    g.pstack = np.zeros(n, np.int64)
    g.mark = np.full(n, -1, np.int64)
    g.stamp = 0
    cap = max(4 * n, 64)
    g.Lp = np.zeros(n + 1, np.int64)
    g.Li = np.zeros(cap, np.int64)
    g.Lx = np.zeros(cap)
    g.Up = np.zeros(n + 1, np.int64)
    g.Ui = np.zeros(cap, np.int64)
    g.Ux = np.zeros(cap)
    g.t = np.zeros(n)
    g.lnz = 0
    g.unz = 0
    g.flops = 0
    g.singular = 0
    g.nonfinite = 0
    g.over = 0
    g.fail_column = -1
    g.fail_original = -1
    return g


@njit(**_OPTS)
def _gp_reach(g, ap, ai, col):
    """The rows x of L*x = A(:,col) can be nonzero in, into xi[top..n-1] in
    the order the solve takes them (``_reach``): an iterative depth-first
    search, marks stamped rather than cleared."""
    n = g.n
    xi = g.xi
    stack = g.stack
    pstack = g.pstack
    mark = g.mark
    pinv = g.pinv
    Lp = g.Lp
    Li = g.Li
    g.stamp += 1
    stamp = g.stamp
    top = n
    for sp in range(ap[col], ap[col + 1]):
        start = ai[sp]
        if mark[start] == stamp:
            continue
        head = 0
        stack[0] = start
        while head >= 0:
            j = stack[head]
            J = pinv[j]
            if mark[j] != stamp:
                mark[j] = stamp
                pstack[head] = 0 if J < 0 else Lp[J] + 1
            pend = 0 if J < 0 else Lp[J + 1]
            done = True
            for p in range(pstack[head], pend):
                w = Li[p]
                if mark[w] == stamp:
                    continue
                pstack[head] = p
                head += 1
                stack[head] = w
                done = False
                break
            if done:
                head -= 1
                top -= 1
                xi[top] = j
    return top


@njit(**_OPTS)
def _gp_spsolve(g, ap, ai, ax, col):
    """L*x = A(:,col) for the sparse x, over the reach only (``_spsolve``)."""
    n = g.n
    top = _gp_reach(g, ap, ai, col)
    xi = g.xi
    x = g.x
    pinv = g.pinv
    Lp = g.Lp
    Li = g.Li
    Lx = g.Lx
    for p in range(top, n):
        x[xi[p]] = 0.0
    for p in range(ap[col], ap[col + 1]):
        x[ai[p]] = ax[p]
    flops = 0
    for px in range(top, n):
        j = xi[px]
        J = pinv[j]
        if J < 0:
            continue
        flops += Lp[J + 1] - Lp[J] - 1
        xj = x[j]
        if xj == 0:
            continue
        for p in range(Lp[J] + 1, Lp[J + 1]):
            x[Li[p]] -= Lx[p] * xj
    g.flops += flops
    return top


@njit(**_OPTS)
def gp_factorize(g, ap, ai, ax, q, has_q, limit):
    """P*A*Q = L*U, Q the column order q where has_q (``factorize``); stops
    as soon as L and U hold more than ``limit`` entries, ``over`` set."""
    n = g.n
    g.qcol = q
    g.has_q = 1 if has_q else 0
    g.over = 0
    g.singular = 0
    g.nonfinite = 0
    g.fail_column = -1
    g.fail_original = -1
    pinv = g.pinv
    perm = g.perm
    mark = g.mark
    x = g.x
    xi = g.xi
    Lp = g.Lp
    Up = g.Up
    for i in range(n):
        pinv[i] = -1
        mark[i] = -1
        x[i] = 0.0
    g.stamp = 0
    g.flops = 0
    lnz = 0
    unz = 0
    for k in range(n):
        Lp[k] = lnz
        Up[k] = unz
        # A column holds at most n entries.
        if lnz + n > g.Li.size:
            cap = g.Li.size
            while cap < lnz + n:
                cap *= 2
            Li = np.zeros(cap, np.int64)
            Li[:g.Li.size] = g.Li
            g.Li = Li
            Lx = np.zeros(cap)
            Lx[:g.Lx.size] = g.Lx
            g.Lx = Lx
        if unz + n > g.Ui.size:
            cap = g.Ui.size
            while cap < unz + n:
                cap *= 2
            Ui = np.zeros(cap, np.int64)
            Ui[:g.Ui.size] = g.Ui
            g.Ui = Ui
            Ux = np.zeros(cap)
            Ux[:g.Ux.size] = g.Ux
            g.Ux = Ux
        Li = g.Li
        Lx = g.Lx
        Ui = g.Ui
        Ux = g.Ux
        col = q[k] if has_q else k
        top = _gp_spsolve(g, ap, ai, ax, col)
        # The pivot: the largest of the rows not yet pivotal; the rows that
        # are belong to U.
        ipiv = -1
        best = -1.0
        for p in range(top, n):
            i = xi[p]
            if pinv[i] < 0:
                t = abs(x[i])
                if t > best:
                    best = t
                    ipiv = i
            else:
                Ui[unz] = pinv[i]
                Ux[unz] = x[i]
                unz += 1
        if ipiv == -1 or not (best > 0) or not math.isfinite(best):
            g.singular = 1
            g.nonfinite = 1 if best == np.inf else 0
            g.fail_column = k
            g.fail_original = col
            g.lnz = lnz
            g.unz = unz
            for kk in range(k, n + 1):
                Lp[kk] = lnz
                Up[kk] = unz
            return
        pivot = x[ipiv]
        Ui[unz] = k
        Ux[unz] = pivot
        unz += 1
        pinv[ipiv] = k
        Li[lnz] = ipiv
        Lx[lnz] = 1.0
        lnz += 1
        for p in range(top, n):
            i = xi[p]
            if pinv[i] < 0:
                Li[lnz] = i
                Lx[lnz] = x[i] / pivot
                lnz += 1
            x[i] = 0.0
        if lnz + unz > limit:
            g.over = 1
            g.lnz = lnz
            g.unz = unz
            return
    Lp[n] = lnz
    Up[n] = unz
    g.lnz = lnz
    g.unz = unz
    Li = g.Li
    for p in range(lnz):
        Li[p] = pinv[Li[p]]
    for i in range(n):
        perm[pinv[i]] = i


@njit(**_OPTS)
def gp_solve(g, b, out):
    """A*x = b into ``out``: P b, then L \\ ., then U \\ ., through Q (``solve``)."""
    n = g.n
    perm = g.perm
    t = g.t
    Lp = g.Lp
    Li = g.Li
    Lx = g.Lx
    Up = g.Up
    Ui = g.Ui
    Ux = g.Ux
    for k in range(n):
        t[k] = b[perm[k]]
    for j in range(n):
        xj = t[j]
        if xj == 0:
            continue
        for p in range(Lp[j] + 1, Lp[j + 1]):
            t[Li[p]] -= Lx[p] * xj
    for j in range(n - 1, -1, -1):
        d = Ux[Up[j + 1] - 1]
        xj = t[j] / d
        t[j] = xj
        if xj == 0:
            continue
        for p in range(Up[j], Up[j + 1] - 1):
            t[Ui[p]] -= Ux[p] * xj
    if g.has_q:
        qcol = g.qcol
        for k in range(n):
            out[qcol[k]] = t[k]
    else:
        for k in range(n):
            out[k] = t[k]


# --- reverse Cuthill-McKee, and the blocks --------------------------------------------------------------


@njit(**_OPTS)
def rcm_order(n, colptr, rowidx):
    """Reverse Cuthill-McKee on the pattern of A + A' (``reverseCuthillMcKee``):
    each component from its node of least degree, neighbours by degree, ties
    by number."""
    deg = np.zeros(n, np.int64)
    for j in range(n):
        for p in range(colptr[j], colptr[j + 1]):
            i = rowidx[p]
            if i == j:
                continue
            deg[i] += 1
            deg[j] += 1
    ptr = np.zeros(n + 1, np.int64)
    for i in range(n):
        ptr[i + 1] = ptr[i] + deg[i]
    nxt = ptr[:n].copy()
    adj = np.zeros(ptr[n], np.int64)
    for j in range(n):
        for p in range(colptr[j], colptr[j + 1]):
            i = rowidx[p]
            if i == j:
                continue
            adj[nxt[i]] = j
            nxt[i] += 1
            adj[nxt[j]] = i
            nxt[j] += 1
    seen = np.full(n, -1, np.int64)
    dptr = np.zeros(n + 1, np.int64)
    dadj = np.zeros(ptr[n], np.int64)
    k = 0
    for i in range(n):
        dptr[i] = k
        for p in range(ptr[i], ptr[i + 1]):
            w = adj[p]
            if seen[w] == i:
                continue
            seen[w] = i
            dadj[k] = w
            k += 1
    dptr[n] = k
    degree = np.zeros(n, np.int64)
    keys = np.zeros(n, np.int64)
    for i in range(n):
        degree[i] = dptr[i + 1] - dptr[i]
        keys[i] = degree[i] * n + i
    by_degree = np.argsort(keys)
    visited = np.zeros(n, np.uint8)
    order = np.zeros(n, np.int64)
    queue = np.zeros(n, np.int64)
    nb = np.zeros(n, np.int64)
    nbk = np.zeros(n, np.int64)
    filled = 0
    for si in range(n):
        seed = by_degree[si]
        if visited[seed] != 0:
            continue
        head = 0
        tail = 0
        queue[tail] = seed
        tail += 1
        visited[seed] = 1
        while head < tail:
            v = queue[head]
            head += 1
            order[filled] = v
            filled += 1
            m = 0
            for p in range(dptr[v], dptr[v + 1]):
                u = dadj[p]
                if visited[u] == 0:
                    nb[m] = u
                    nbk[m] = degree[u] * n + u
                    m += 1
            idx = np.argsort(nbk[:m])
            for t in range(m):
                u = nb[idx[t]]
                visited[u] = 1
                queue[tail] = u
                tail += 1
    rev = np.zeros(n, np.int64)
    for i in range(n):
        rev[i] = order[n - 1 - i]
    return rev


@njit(**_OPTS)
def block_triangular(n, colptr, rowidx):
    """The strongly connected components of the pattern's graph, an edge from
    column j to row i for each entry (i, j) off the diagonal, numbered in the
    order Tarjan's algorithm closes them (``blockTriangular``): block upper
    triangular. Without recursion."""
    index = np.full(n, -1, np.int64)
    low = np.zeros(n, np.int64)
    on_stack = np.zeros(n, np.uint8)
    stack = np.zeros(n, np.int64)
    path = np.zeros(n, np.int64)
    nxt = np.zeros(n, np.int64)
    block = np.zeros(n, np.int64)
    counter = 0
    top = 0
    nblocks = 0
    for s in range(n):
        if index[s] >= 0:
            continue
        depth = 0
        path[0] = s
        index[s] = counter
        low[s] = counter
        counter += 1
        nxt[s] = colptr[s]
        stack[top] = s
        top += 1
        on_stack[s] = 1
        while depth >= 0:
            v = path[depth]
            if nxt[v] < colptr[v + 1]:
                w = rowidx[nxt[v]]
                nxt[v] += 1
                if w == v:
                    continue
                if index[w] < 0:
                    index[w] = counter
                    low[w] = counter
                    counter += 1
                    nxt[w] = colptr[w]
                    stack[top] = w
                    top += 1
                    on_stack[w] = 1
                    depth += 1
                    path[depth] = w
                elif on_stack[w] != 0 and index[w] < low[v]:
                    low[v] = index[w]
                continue
            if low[v] == index[v]:
                while True:
                    top -= 1
                    w = stack[top]
                    on_stack[w] = 0
                    block[w] = nblocks
                    if w == v:
                        break
                nblocks += 1
            depth -= 1
            if depth >= 0:
                u = path[depth]
                if low[v] < low[u]:
                    low[u] = low[v]
    return nblocks, block


# --- the LU that keeps its pivots (``RefactorLU``) ------------------------------------------------------


@njit(**_OPTS)
def rf_new(n, colptr, rowidx, columns, has_columns):
    """For J's pattern; ``columns`` a fixed column order where has_columns,
    else columns chosen by threshold Markowitz as well."""
    nnz = colptr[n]
    r = structref.new(RF_T)
    r.n = n
    r.nnzj = nnz
    r.columns = columns
    r.has_columns = 1 if has_columns else 0
    slot_row = np.zeros(nnz + n, np.int64)
    slot_col = np.zeros(nnz + n, np.int64)
    jslot = np.zeros(nnz, np.int64)
    dslot = np.zeros(n, np.int64)
    mark = np.full(n, -1, np.int64)
    ns = 0
    for j in range(n):
        for p in range(colptr[j], colptr[j + 1]):
            i = rowidx[p]
            slot_row[ns] = i
            slot_col[ns] = j
            jslot[p] = ns
            mark[i] = ns
            ns += 1
        if mark[j] >= 0:
            dslot[j] = mark[j]
        else:
            slot_row[ns] = j
            slot_col[ns] = j
            dslot[j] = ns
            ns += 1
        for p in range(colptr[j], colptr[j + 1]):
            mark[rowidx[p]] = -1
    r.slot_row = slot_row
    r.slot_col = slot_col
    r.jslot = jslot
    r.dslot = dslot
    r.nbase = ns
    r.nslots = ns
    r.V = np.zeros(ns)
    r.pr = np.zeros(n, np.int64)
    r.pc = np.zeros(n, np.int64)
    r.pslot = np.zeros(n, np.int64)
    r.lstart = np.zeros(n + 1, np.int64)
    r.ustart = np.zeros(n + 1, np.int64)
    r.tstart = np.zeros(n + 1, np.int64)
    r.fill_start = np.zeros(n + 1, np.int64)
    r.lslot = np.zeros(64, np.int64)
    r.lrow = np.zeros(64, np.int64)
    r.uslot = np.zeros(64, np.int64)
    r.ucol = np.zeros(64, np.int64)
    r.T = np.zeros(64, np.int64)
    r.lval = np.zeros(64)
    r.lstep = np.zeros(64, np.int64)
    r.uval = np.zeros(64)
    r.ustep = np.zeros(64, np.int64)
    r.dval = np.zeros(n)
    r.row_step = np.zeros(n, np.int64)
    r.col_step = np.zeros(n, np.int64)
    r.valid = 0
    r.ops = 0
    r.nnz = 0
    r.repivots = 0
    r.full_ops = 0
    r.limit = np.inf
    r.row_active = np.zeros(n, np.int64)
    r.col_active = np.zeros(n, np.int64)
    r.rc = np.zeros(n, np.int64)
    r.cc = np.zeros(n, np.int64)
    r.head = np.zeros(n + 2, np.int64)
    r.nxt = np.zeros(n, np.int64)
    r.prv = np.zeros(n, np.int64)
    r.at = np.zeros(n, np.int64)
    r.at_stamp = np.zeros(n, np.int64)
    r.row_start = np.zeros(n, np.int64)
    r.row_len = np.zeros(n, np.int64)
    r.row_cap = np.zeros(n, np.int64)
    r.col_start = np.zeros(n, np.int64)
    r.col_len = np.zeros(n, np.int64)
    r.col_cap = np.zeros(n, np.int64)
    r.pool = np.zeros(64, np.int64)
    r.pool_top = 0
    r.z = np.zeros(n)
    return r


@njit(**_OPTS)
def rf_load(r, a, values, mass, has_mass):
    """Mass - a*J into V; False where a value is not finite (``load``)."""
    n = r.n
    V = r.V
    jslot = r.jslot
    dslot = r.dslot
    for s in range(r.nslots):
        V[s] = 0.0
    finite = True
    for p in range(r.nnzj):
        v = -a * values[p]
        if not math.isfinite(v):
            finite = False
        V[jslot[p]] = v
    if has_mass:
        for i in range(n):
            V[dslot[i]] += mass[i]
    else:
        for i in range(n):
            V[dslot[i]] += 1.0
    return finite


@njit(**_OPTS)
def rf_order(r):
    """The rows of L and the columns of U as the steps that pivot on them, after every choice (``_order``)."""
    n = r.n
    pr = r.pr
    pc = r.pc
    row_step = r.row_step
    col_step = r.col_step
    for s in range(n):
        row_step[pr[s]] = s
        col_step[pc[s]] = s
    nl = r.lstart[n]
    nu = r.ustart[n]
    r.lstep = _room_i(r.lstep, nl)
    r.ustep = _room_i(r.ustep, nu)
    r.lval = _room_f(r.lval, nl)
    r.uval = _room_f(r.uval, nu)
    lstep = r.lstep
    ustep = r.ustep
    lrow = r.lrow
    ucol = r.ucol
    for k in range(nl):
        lstep[k] = row_step[lrow[k]]
    for u in range(nu):
        ustep[u] = col_step[ucol[u]]


@njit(**_OPTS)
def rf_pack(r):
    """L's, U's and the pivots' values in step order, after every factorisation (``_pack``)."""
    n = r.n
    V = r.V
    nl = r.lstart[n]
    nu = r.ustart[n]
    lslot = r.lslot
    uslot = r.uslot
    pslot = r.pslot
    lval = r.lval
    uval = r.uval
    dval = r.dval
    for k in range(nl):
        lval[k] = V[lslot[k]]
    for u in range(nu):
        uval[u] = V[uslot[u]]
    for s in range(n):
        dval[s] = V[pslot[s]]


@njit(**_OPTS)
def rf_refactor(r):
    """Replays the record on V: -1, or the first step whose pivot fails (``refactor``)."""
    n = r.n
    V = r.V
    pslot = r.pslot
    lstart = r.lstart
    ustart = r.ustart
    tstart = r.tstart
    lslot = r.lslot
    uslot = r.uslot
    T = r.T
    bound = 1 / KEEP_THRESHOLD
    for s in range(n):
        piv = V[pslot[s]]
        ap = abs(piv)
        if not (ap > 0) or ap == np.inf:
            return s
        lim = bound * ap
        l0 = lstart[s]
        l1 = lstart[s + 1]
        for k in range(l0, l1):
            if not (abs(V[lslot[k]]) <= lim):
                return s
        u0 = ustart[s]
        u1 = ustart[s + 1]
        t = tstart[s]
        for k in range(l0, l1):
            ls = lslot[k]
            f = V[ls] / piv
            V[ls] = f
            if f == 0:
                t += u1 - u0
                continue
            for u in range(u0, u1):
                V[T[t]] -= f * V[uslot[u]]
                t += 1
    return -1


@njit(**_OPTS)
def _bucket_out(head, nxt, prv, cc, j):
    if prv[j] >= 0:
        nxt[prv[j]] = nxt[j]
    else:
        head[cc[j]] = nxt[j]
    if nxt[j] >= 0:
        prv[nxt[j]] = prv[j]


@njit(**_OPTS)
def _bucket_in(head, nxt, prv, cc, j):
    c = cc[j]
    prv[j] = -1
    nxt[j] = head[c]
    if head[c] >= 0:
        prv[head[c]] = j
    head[c] = j


@njit(**_OPTS)
def _lists_from_slots(r):
    """Each active row's and column's slots, in slot order, in the pool: room
    for twice as many again before a list moves (``rowSlots``, ``colSlots``)."""
    n = r.n
    row_active = r.row_active
    col_active = r.col_active
    slot_row = r.slot_row
    slot_col = r.slot_col
    row_start = r.row_start
    row_len = r.row_len
    row_cap = r.row_cap
    col_start = r.col_start
    col_len = r.col_len
    col_cap = r.col_cap
    for i in range(n):
        row_len[i] = 0
        col_len[i] = 0
    nslots = r.nslots
    for s in range(nslots):
        i = slot_row[s]
        j = slot_col[s]
        if row_active[i] == 0 or col_active[j] == 0:
            continue
        row_len[i] += 1
        col_len[j] += 1
    top = 0
    for i in range(n):
        row_cap[i] = 2 * row_len[i] + 2
        row_start[i] = top
        top += row_cap[i]
    for j in range(n):
        col_cap[j] = 2 * col_len[j] + 2
        col_start[j] = top
        top += col_cap[j]
    r.pool = _room_i(r.pool, top)
    r.pool_top = top
    pool = r.pool
    for i in range(n):
        row_len[i] = 0
        col_len[i] = 0
    for s in range(nslots):
        i = slot_row[s]
        j = slot_col[s]
        if row_active[i] == 0 or col_active[j] == 0:
            continue
        pool[row_start[i] + row_len[i]] = s
        row_len[i] += 1
        pool[col_start[j] + col_len[j]] = s
        col_len[j] += 1


@njit(**_OPTS)
def _push(r, row, idx, val):
    """``val`` onto row (or column) ``idx``'s list, moving the list to the
    end of the pool with twice the room when it is full."""
    start = r.row_start if row else r.col_start
    length = r.row_len if row else r.col_len
    cap = r.row_cap if row else r.col_cap
    ln = length[idx]
    if ln == cap[idx]:
        grown = 2 * cap[idx] + 2
        top = r.pool_top
        r.pool = _room_i(r.pool, top + grown)
        pool = r.pool
        s0 = start[idx]
        for k in range(ln):
            pool[top + k] = pool[s0 + k]
        start[idx] = top
        cap[idx] = grown
        r.pool_top = top + grown
    pool = r.pool
    pool[start[idx] + ln] = val
    length[idx] = ln + 1


@njit(**_OPTS)
def _new_slot(r, i, j):
    """A fill slot at (i, j) (``_newSlot``): the caller has made room in V and the slot arrays."""
    s = r.nslots
    r.nslots = s + 1
    r.V[s] = 0.0
    r.slot_row[s] = i
    r.slot_col[s] = j
    _push(r, True, i, s)
    _push(r, False, j, s)
    r.rc[i] += 1
    r.cc[j] += 1
    return s


@njit(**_OPTS)
def rf_choose(r, s0):
    """Chooses the pivots of steps s0.. from V as the kept steps before s0
    left it, eliminating as it goes (``choose``); False when no acceptable
    pivot remains, a value is not finite, or the work passes ``limit``."""
    n = r.n
    pr = r.pr
    pc = r.pc
    pslot = r.pslot
    lstart = r.lstart
    ustart = r.ustart
    tstart = r.tstart
    fill_start = r.fill_start
    row_active = r.row_active
    col_active = r.col_active
    rc = r.rc
    cc = r.cc
    head = r.head
    nxt = r.nxt
    prv = r.prv
    at = r.at
    at_stamp = r.at_stamp
    row_start = r.row_start
    row_len = r.row_len
    col_start = r.col_start
    col_len = r.col_len
    has_fixed = r.has_columns != 0
    columns = r.columns
    limit = r.limit
    # The pattern and the fill of the kept steps stay; the rest goes.
    r.nslots = fill_start[s0] if s0 > 0 else r.nbase
    for i in range(n):
        row_active[i] = 1
        col_active[i] = 1
    for s in range(s0):
        row_active[pr[s]] = 0
        col_active[pc[s]] = 0
    _lists_from_slots(r)
    for i in range(n):
        rc[i] = row_len[i]
        cc[i] = col_len[i]
    for c in range(head.size):
        head[c] = -1
    for j in range(n):
        if col_active[j] != 0:
            _bucket_in(head, nxt, prv, cc, j)
    for j in range(n):
        at_stamp[j] = 0
    stamp = 0
    lp = lstart[s0]
    up = ustart[s0]
    tp = tstart[s0]
    for s in range(s0, n):
        if head[0] >= 0:
            return False                     # a column with nothing left in it
        V = r.V
        slot_row = r.slot_row
        slot_col = r.slot_col
        pool = r.pool
        # The search: the SEARCH_COLUMNS sparsest columns with a candidate, or
        # the one column the fixed order names.
        best = np.inf
        best_ratio = 0.0
        bslot = -1
        examined = 0
        fixed = columns[s] if has_fixed else -1
        cmax = 1 if fixed >= 0 else n - s
        c = 1
        while c <= cmax and examined < SEARCH_COLUMNS and best > 0:
            j = fixed if fixed >= 0 else head[c]
            while j >= 0 and examined < SEARCH_COLUMNS and best > 0:
                # Scanned once for the largest, dropping the rows eliminated since.
                st = col_start[j]
                ln = col_len[j]
                m = 0.0
                keep = 0
                for k in range(ln):
                    sl = pool[st + k]
                    if row_active[slot_row[sl]] == 0:
                        continue
                    pool[st + keep] = sl
                    keep += 1
                    v = abs(V[sl])
                    if not (v < np.inf):
                        return False         # NaN or infinite
                    if v > m:
                        m = v
                if keep < ln:
                    col_len[j] = keep
                if m > 0:
                    examined += 1
                    thr = PIVOT_THRESHOLD * m
                    cj = 1 if fixed >= 0 else c - 1
                    for k in range(keep):
                        sl = pool[st + k]
                        v = abs(V[sl])
                        if v < thr:
                            continue
                        cost = (rc[slot_row[sl]] - 1) * cj
                        ratio = v / m
                        if cost < best or (cost == best and ratio > best_ratio):
                            best = cost
                            best_ratio = ratio
                            bslot = sl
                j = -1 if fixed >= 0 else nxt[j]
            c += 1
        if bslot < 0:
            return False
        p = slot_row[bslot]
        q = slot_col[bslot]
        pr[s] = p
        pc[s] = q
        pslot[s] = bslot
        fill_start[s] = r.nslots
        row_active[p] = 0
        col_active[q] = 0
        _bucket_out(head, nxt, prv, cc, q)
        # Its column below and its row to the right, among what is active.
        lst = col_start[q]
        lln = col_len[q]
        ust = row_start[p]
        uln = row_len[p]
        r.lslot = _room_i(r.lslot, lp + lln)
        r.lrow = _room_i(r.lrow, lp + lln)
        r.uslot = _room_i(r.uslot, up + uln)
        r.ucol = _room_i(r.ucol, up + uln)
        lslot = r.lslot
        lrow = r.lrow
        uslot = r.uslot
        ucol = r.ucol
        lstart[s] = lp
        ustart[s] = up
        tstart[s] = tp
        for k in range(lln):
            sl = pool[lst + k]
            i = slot_row[sl]
            if row_active[i] != 0:
                lslot[lp] = sl
                lrow[lp] = i
                lp += 1
        for k in range(uln):
            sl = pool[ust + k]
            j = slot_col[sl]
            if col_active[j] != 0:
                uslot[up] = sl
                ucol[up] = j
                up += 1
        l0 = lstart[s]
        u0 = ustart[s]
        most = (lp - l0) * (up - u0)
        r.T = _room_i(r.T, tp + most)
        r.V = _room_f(r.V, r.nslots + most)
        r.slot_row = _room_i(r.slot_row, r.nslots + most)
        r.slot_col = _room_i(r.slot_col, r.nslots + most)
        T = r.T
        V = r.V
        slot_col = r.slot_col
        for u in range(u0, up):
            _bucket_out(head, nxt, prv, cc, ucol[u])
        piv = V[bslot]
        for k in range(l0, lp):
            i = lrow[k]
            f = V[lslot[k]] / piv
            V[lslot[k]] = f
            # Where row i already has an entry, by column.
            stamp += 1
            pool = r.pool
            st = row_start[i]
            ln = row_len[i]
            keep = 0
            for rr in range(ln):
                sl = pool[st + rr]
                j = slot_col[sl]
                if col_active[j] == 0:
                    continue
                pool[st + keep] = sl
                keep += 1
                at[j] = sl
                at_stamp[j] = stamp
            if keep < ln:
                row_len[i] = keep
            for u in range(u0, up):
                j = ucol[u]
                # Fill is structure whatever its value now: a later matrix
                # may put a number there.
                if at_stamp[j] == stamp:
                    t = at[j]
                else:
                    t = _new_slot(r, i, j)
                T[tp] = t
                tp += 1
                if f != 0:
                    V[t] -= f * V[uslot[u]]
        for k in range(l0, lp):
            rc[lrow[k]] -= 1
        for u in range(u0, up):
            j = ucol[u]
            cc[j] -= 1
            _bucket_in(head, nxt, prv, cc, j)
        if tp > limit:
            return False
    lstart[n] = lp
    ustart[n] = up
    tstart[n] = tp
    fill_start[n] = r.nslots
    r.ops = tp
    r.nnz = r.nslots
    return True


@njit(**_OPTS)
def rf_factor(r, a, values, mass, has_mass):
    """Factorises Mass - a*J; False when it cannot be done with pivots that pass the test (``factor``)."""
    if r.valid == 0:
        r.nslots = r.nbase
    if not rf_load(r, a, values, mass, has_mass):
        r.valid = 0
        return False
    frm = 0
    if r.valid != 0:
        frm = rf_refactor(r)
        if frm < 0:
            rf_pack(r)
            return True
    r.repivots += 1
    if not rf_choose(r, frm):
        r.valid = 0
        return False
    if frm == 0:
        r.full_ops = r.ops
    elif r.ops > REORDER_GROWTH * r.full_ops:
        rf_load(r, a, values, mass, has_mass)
        if not rf_choose(r, 0):
            r.valid = 0
            return False
        r.full_ops = r.ops
    r.valid = 1
    rf_order(r)
    rf_pack(r)
    return True


@njit(**_OPTS)
def rf_solve(r, b, out):
    """Against the latest factorisation, into ``out`` (``solve``)."""
    n = r.n
    pr = r.pr
    pc = r.pc
    lstart = r.lstart
    ustart = r.ustart
    lval = r.lval
    lstep = r.lstep
    uval = r.uval
    ustep = r.ustep
    dval = r.dval
    z = r.z
    for s in range(n):
        z[s] = b[pr[s]]
    for s in range(n):
        zs = z[s]
        if zs == 0:
            continue
        for k in range(lstart[s], lstart[s + 1]):
            z[lstep[k]] -= lval[k] * zs
    for s in range(n - 1, -1, -1):
        t = z[s]
        for u in range(ustart[s], ustart[s + 1]):
            t -= uval[u] * z[ustep[u]]
        z[s] = t / dval[s]
    for s in range(n):
        out[pc[s]] = z[s]


# --- a block at a time (``BlockLU``) ------------------------------------------------------------------


@njit(**_OPTS)
def bk_new(n, colptr, rowidx, nblocks, block):
    bk = structref.new(BK_T)
    bk.n = n
    bk.nblocks = nblocks
    start = np.zeros(nblocks + 1, np.int64)
    for i in range(n):
        start[block[i] + 1] += 1
    for b in range(nblocks):
        start[b + 1] += start[b]
    member = np.zeros(n, np.int64)
    local = np.zeros(n, np.int64)
    filled = start[:nblocks].copy()
    for i in range(n):
        b = block[i]
        local[i] = filled[b] - start[b]
        member[filled[b]] = i
        filled[b] += 1
    bk.start = start
    bk.member = member
    # The entries between blocks, by column: their rows, and where J holds them.
    off_ptr = np.zeros(n + 1, np.int64)
    for j in range(n):
        c = 0
        for p in range(colptr[j], colptr[j + 1]):
            if block[rowidx[p]] != block[j]:
                c += 1
        off_ptr[j + 1] = off_ptr[j] + c
    noff = off_ptr[n]
    off_row = np.zeros(noff, np.int64)
    off_pos = np.zeros(noff, np.int64)
    e = 0
    for j in range(n):
        for p in range(colptr[j], colptr[j + 1]):
            if block[rowidx[p]] == block[j]:
                continue
            off_row[e] = rowidx[p]
            off_pos[e] = p
            e += 1
    bk.off_ptr = off_ptr
    bk.off_row = off_row
    bk.off_pos = off_pos
    # A block of one state: where J holds its diagonal (-1: nowhere). A larger
    # one: its pattern in its own numbering, where J holds each of its
    # entries, and its LU.
    diag_pos = np.full(nblocks, -1, np.int64)
    lu_of = np.full(nblocks, -1, np.int64)
    nlus = 0
    total = 0
    for b in range(nblocks):
        s0 = start[b]
        size = start[b + 1] - s0
        if size == 1:
            i = member[s0]
            for p in range(colptr[i], colptr[i + 1]):
                if rowidx[p] == i:
                    diag_pos[b] = p
            continue
        for lc in range(size):
            j = member[s0 + lc]
            for p in range(colptr[j], colptr[j + 1]):
                if block[rowidx[p]] == b:
                    total += 1
        nlus += 1
    lus = List.empty_list(RF_T)
    pos_ptr = np.zeros(nlus + 1, np.int64)
    pos = np.zeros(total, np.int64)
    most = 0
    most_entries = 0
    li = 0
    k = 0
    for b in range(nblocks):
        s0 = start[b]
        size = start[b + 1] - s0
        if size == 1:
            continue
        cp = np.zeros(size + 1, np.int64)
        count = 0
        for lc in range(size):
            j = member[s0 + lc]
            for p in range(colptr[j], colptr[j + 1]):
                if block[rowidx[p]] == b:
                    count += 1
            cp[lc + 1] = count
        ri = np.zeros(count, np.int64)
        pos_ptr[li] = k
        kk = 0
        for lc in range(size):
            j = member[s0 + lc]
            for p in range(colptr[j], colptr[j + 1]):
                if block[rowidx[p]] != b:
                    continue
                ri[kk] = local[rowidx[p]]
                pos[k] = p
                kk += 1
                k += 1
        lus.append(rf_new(size, cp, ri, np.zeros(0, np.int64), False))
        lu_of[b] = li
        li += 1
        if size > most:
            most = size
        if count > most_entries:
            most_entries = count
    pos_ptr[nlus] = k
    bk.diag_pos = diag_pos
    bk.lu_of = lu_of
    bk.lus = lus
    bk.pos_ptr = pos_ptr
    bk.pos = pos
    bk.b_values = np.zeros(most_entries)
    bk.b_mass = np.zeros(most)
    # The steps in the order the solve takes them, the last block first, in
    # segments: one block of more than one state, or a run of blocks of one
    # state each.
    base = np.zeros(nblocks, np.int64)
    row_of_step = np.zeros(n, np.int64)
    col_of_step = np.zeros(n, np.int64)
    step_of_row = np.zeros(n, np.int64)
    seg_start = np.zeros(nblocks + 1, np.int64)
    seg_block = np.zeros(nblocks, np.int64)
    nseg = 0
    g = 0
    for b in range(nblocks - 1, -1, -1):
        size = start[b + 1] - start[b]
        base[b] = g
        if size == 1:
            i = member[start[b]]
            row_of_step[g] = i
            col_of_step[g] = i
            step_of_row[i] = g
            if nseg > 0 and seg_block[nseg - 1] < 0:
                seg_start[nseg] = g + 1
            else:
                seg_block[nseg] = -1
                nseg += 1
                seg_start[nseg] = g + 1
        else:
            seg_block[nseg] = b
            nseg += 1
            seg_start[nseg] = g + size
        g += size
    bk.base = base
    bk.row_of_step = row_of_step
    bk.col_of_step = col_of_step
    bk.step_of_row = step_of_row
    bk.seg_start = seg_start[:nseg + 1].copy()
    bk.seg_block = seg_block[:nseg].copy()
    bk.Lp = np.zeros(n + 1, np.int64)
    bk.Up = np.zeros(n + 1, np.int64)
    bk.Li = np.zeros(0, np.int64)
    bk.Lx = np.zeros(0)
    bk.Ui = np.zeros(0, np.int64)
    bk.Ux = np.zeros(0)
    bk.D = np.zeros(n)
    bk.off_p = np.zeros(n + 1, np.int64)
    bk.off_step = np.zeros(noff, np.int64)
    bk.off_at = np.zeros(noff, np.int64)
    bk.off_x = np.zeros(noff)
    bk.zs = np.zeros(n)
    bk.laid_out = -1
    bk.valid = 0
    bk.ops = 0
    bk.limit = np.inf
    bk.nnz = 0
    return bk


@njit(**_OPTS)
def bk_repivots(bk):
    """Times a block's pivots were chosen again, over every block."""
    r = 0
    for lu in bk.lus:
        r += lu.repivots
    return r


@njit(**_OPTS)
def _bk_layout(bk):
    """The larger blocks' steps, L's and U's entries by step, and the entries
    between blocks by the steps of their column and their row (``_layout``)."""
    n = bk.n
    nblocks = bk.nblocks
    start = bk.start
    member = bk.member
    base = bk.base
    lu_of = bk.lu_of
    lus = bk.lus
    row_of_step = bk.row_of_step
    col_of_step = bk.col_of_step
    step_of_row = bk.step_of_row
    Lp = bk.Lp
    Up = bk.Up
    nl = 0
    nu = 0
    for lu in lus:
        nl += lu.lstart[lu.n]
        nu += lu.ustart[lu.n]
    if bk.Li.size < nl:
        bk.Li = np.zeros(nl, np.int64)
        bk.Lx = np.zeros(nl)
    if bk.Ui.size < nu:
        bk.Ui = np.zeros(nu, np.int64)
        bk.Ux = np.zeros(nu)
    Li = bk.Li
    Ui = bk.Ui
    lq = 0
    uq = 0
    for k in range(nblocks - 1, -1, -1):
        s0 = start[k]
        m = start[k + 1] - s0
        g0 = base[k]
        li = lu_of[k]
        if li < 0:
            Lp[g0] = lq
            Up[g0] = uq
            continue
        lu = lus[li]
        pr = lu.pr
        pc = lu.pc
        lstart = lu.lstart
        lstep = lu.lstep
        ustart = lu.ustart
        ustep = lu.ustep
        for s in range(m):
            i = member[s0 + pr[s]]
            row_of_step[g0 + s] = i
            col_of_step[g0 + s] = member[s0 + pc[s]]
            step_of_row[i] = g0 + s
            Lp[g0 + s] = lq
            for q in range(lstart[s], lstart[s + 1]):
                Li[lq] = g0 + lstep[q]
                lq += 1
            Up[g0 + s] = uq
            for u in range(ustart[s], ustart[s + 1]):
                Ui[uq] = g0 + ustep[u]
                uq += 1
    Lp[n] = lq
    Up[n] = uq
    off_ptr = bk.off_ptr
    off_row = bk.off_row
    off_pos = bk.off_pos
    off_p = bk.off_p
    off_step = bk.off_step
    off_at = bk.off_at
    e = 0
    for g in range(n):
        off_p[g] = e
        j = col_of_step[g]
        for f in range(off_ptr[j], off_ptr[j + 1]):
            off_step[e] = step_of_row[off_row[f]]
            off_at[e] = off_pos[f]
            e += 1
    off_p[n] = e


@njit(**_OPTS)
def _bk_values(bk, a, values):
    """The factor's values in that layout, after every factorisation, and the
    entries between blocks from J; False where one is not a number (``_values``)."""
    nblocks = bk.nblocks
    start = bk.start
    base = bk.base
    lu_of = bk.lu_of
    lus = bk.lus
    Lx = bk.Lx
    Ux = bk.Ux
    D = bk.D
    lq = 0
    uq = 0
    for k in range(nblocks - 1, -1, -1):
        li = lu_of[k]
        if li < 0:
            continue
        lu = lus[li]
        m = start[k + 1] - start[k]
        g0 = base[k]
        lval = lu.lval
        uval = lu.uval
        dval = lu.dval
        nl = lu.lstart[m]
        nu = lu.ustart[m]
        for q in range(nl):
            Lx[lq] = lval[q]
            lq += 1
        for u in range(nu):
            Ux[uq] = uval[u]
            uq += 1
        for s in range(m):
            D[g0 + s] = dval[s]
    off_x = bk.off_x
    off_at = bk.off_at
    for e in range(off_x.size):
        v = -a * values[off_at[e]]
        if not math.isfinite(v):
            return False
        off_x[e] = v
    return True


@njit(**_OPTS)
def bk_factor(bk, a, values, mass, has_mass):
    """Factorises Mass - a*J a block at a time (``factor``); False when a
    block cannot be done with pivots that pass the test, or a value is not a
    number."""
    nblocks = bk.nblocks
    start = bk.start
    member = bk.member
    base = bk.base
    D = bk.D
    lu_of = bk.lu_of
    diag_pos = bk.diag_pos
    pos_ptr = bk.pos_ptr
    pos = bk.pos
    b_values = bk.b_values
    b_mass = bk.b_mass
    lus = bk.lus
    limit = bk.limit
    bk.valid = 0
    ops = 0
    nnz = bk.off_x.size
    for b in range(nblocks):
        s0 = start[b]
        li = lu_of[b]
        if li < 0:
            i = member[s0]
            p = diag_pos[b]
            d = (-a * values[p] if p >= 0 else 0.0) + (mass[i] if has_mass else 1.0)
            if not (abs(d) > 0) or not math.isfinite(d):
                return False
            D[base[b]] = d
            nnz += 1
            continue
        size = start[b + 1] - s0
        p0 = pos_ptr[li]
        for k in range(pos_ptr[li + 1] - p0):
            b_values[k] = values[pos[p0 + k]]
        if has_mass:
            for lc in range(size):
                b_mass[lc] = mass[member[s0 + lc]]
        lu = lus[li]
        lu.limit = np.inf if limit == np.inf else limit - ops
        ok = rf_factor(lu, a, b_values, b_mass, has_mass)
        lu.limit = np.inf
        if not ok:
            return False
        ops += lu.ops
        nnz += lu.nnz
        if ops > limit:
            return False
    bk.ops = ops
    bk.nnz = nnz
    chosen = bk_repivots(bk)
    if chosen != bk.laid_out:
        _bk_layout(bk)
        bk.laid_out = chosen
    if not _bk_values(bk, a, values):
        return False
    bk.valid = 1
    return True


@njit(**_OPTS)
def bk_solve(bk, b, out):
    """Against the latest factorisation, the blocks from the last to the
    first, each one's entries between blocks taken off the right-hand side as
    soon as its unknown is known (``solve``)."""
    n = bk.n
    row_of_step = bk.row_of_step
    col_of_step = bk.col_of_step
    Lp = bk.Lp
    Li = bk.Li
    Lx = bk.Lx
    Up = bk.Up
    Ui = bk.Ui
    Ux = bk.Ux
    D = bk.D
    off_p = bk.off_p
    off_step = bk.off_step
    off_x = bk.off_x
    zs = bk.zs
    seg_start = bk.seg_start
    seg_block = bk.seg_block
    for g in range(n):
        zs[g] = b[row_of_step[g]]
    for r in range(seg_block.size):
        g0 = seg_start[r]
        g1 = seg_start[r + 1]
        if seg_block[r] < 0:
            for g in range(g0, g1):
                xg = zs[g] / D[g]
                zs[g] = xg
                out[col_of_step[g]] = xg
                if xg == 0:
                    continue
                for e in range(off_p[g], off_p[g + 1]):
                    zs[off_step[e]] -= off_x[e] * xg
            continue
        for g in range(g0, g1):
            zg = zs[g]
            if zg == 0:
                continue
            for q in range(Lp[g], Lp[g + 1]):
                zs[Li[q]] -= Lx[q] * zg
        for g in range(g1 - 1, g0 - 1, -1):
            t = zs[g]
            for u in range(Up[g], Up[g + 1]):
                t -= Ux[u] * zs[Ui[u]]
            xg = t / D[g]
            zs[g] = xg
            out[col_of_step[g]] = xg
            if xg == 0:
                continue
            for e in range(off_p[g], off_p[g + 1]):
                zs[off_step[e]] -= off_x[e] * xg


# --- the iteration matrix (``iterationMatrix``) -----------------------------------------------------------


@njit(**_OPTS)
def _trial(n, colptr, rowidx, values, mass, has_mass, columns, has_columns, most):
    """A kept-pivot LU tried on the start's matrix, stopping once its work
    passes ``most``: (whether it was made, it)."""
    lu = rf_new(n, colptr, rowidx, columns, has_columns)
    if most < 0:
        return False, lu
    lu.limit = most
    ok = rf_factor(lu, 1e-3, values, mass, has_mass)
    lu.limit = np.inf
    return ok, lu


@njit(**_OPTS)
def sw_new(n, colptr, rowidx, values, mass, has_mass, mode, dense_fill, too_big, blocks):
    """The sparse iteration matrix ``iterationMatrix`` makes in ``mode``
    (``MODES``) from J's pattern and its values at the start -- or, its kind
    DENSE, the word that ``auto`` would factorise it densely. One real
    factorisation of each candidate decides: reverse Cuthill-McKee's column
    order or the model's own, by fill; the kept-pivot LU a block at a time,
    whole by threshold Markowitz, or whole in that column order, where it
    costs no more than the alternative; the dense LU where the searching
    factor fills in; the Gilbert-Peierls LU otherwise."""
    sw = structref.new(SW_T)
    sw.n = n
    sw.colptr = colptr
    sw.rowidx = rowidx
    sw.masked = np.zeros(colptr[n])
    sw.mass = mass
    sw.has_mass = 1 if has_mass else 0
    mp, mi, jtom, diag = miter_structure(n, colptr, rowidx)
    sw.mp = mp
    sw.mi = mi
    sw.jtom = jtom
    sw.diag_pos = diag
    mx = np.zeros(mi.size)
    sw.mx = mx
    gp = gp_new(n)
    sw.gp = gp
    sw.dense = np.zeros((1, 1))
    sw.dpiv = np.zeros(1, np.int64)
    sw.current = _KEPT
    sw.repivots = 0
    sw.fallbacks = 0
    sw.trial_repivots = 0
    sw.fail_column = -1
    sw.fail_value = 0.0
    sw.fail_nonfinite = 0
    empty = np.zeros(0, np.int64)
    whole = rf_new(0, np.zeros(1, np.int64), empty, empty, False)
    blocked = bk_new(0, np.zeros(1, np.int64), empty, 0, empty)
    # Reverse Cuthill-McKee first, and the model's own order stopped as soon
    # as it fills in past that.
    miter_update(1e-3, values, mass, has_mass, mx, jtom, diag)
    rcm = rcm_order(n, mp, mi)
    gp_factorize(gp, mp, mi, mx, rcm, True, np.inf)
    rcm_fill = np.inf if gp.singular else float(gp.lnz + gp.unz)
    gp_factorize(gp, mp, mi, mx, rcm, False, rcm_fill)
    best = np.inf if (gp.singular or gp.over) else float(gp.lnz + gp.unz)
    has_q = False
    if rcm_fill < best:
        best = rcm_fill
        has_q = True
    # Both singular says nothing about the fill: sparse, in the order that
    # suits these graphs, and the formations say whether it is singular.
    if best == np.inf:
        best = float(mp[n])
        has_q = True
    sw.q = rcm
    sw.has_q = 1 if has_q else 0
    sw.fill = int(best)
    sw.ordering = _RCM if has_q else _NATURAL
    fills_in = (not too_big) and best > dense_fill * n * n
    sw.fills_in = 1 if fills_in else 0
    kind = SPARSE
    if mode == _REFACTOR or mode == _AUTO:
        gp_factorize(gp, mp, mi, mx, rcm, has_q, np.inf)
        alternative = 0.25 * n * n * n / 3 if fills_in else float(gp.flops)
        limit = np.inf if mode == _REFACTOR else min(OPS_BUDGET, alternative)
        # A block at a time first, where the matrix falls into more than one
        # block: a whole trial is then kept only where it costs less.
        by_blocks = False
        if blocks:
            nb, block = block_triangular(n, colptr, rowidx)
            if nb > 1:
                bk = bk_new(n, colptr, rowidx, nb, block)
                bk.limit = limit
                ok = bk_factor(bk, 1e-3, values, mass, has_mass)
                bk.limit = np.inf
                if ok:
                    blocked = bk
                    by_blocks = True
                    limit = min(limit, float(bk.ops - 1))
        m_ok, by_m = _trial(n, colptr, rowidx, values, mass, has_mass, empty, False, limit)
        cols = rcm if has_q else np.arange(n)
        c_ok, by_c = _trial(n, colptr, rowidx, values, mass, has_mass, cols, True,
                            min(limit, float(by_m.ops)) if m_ok else limit)
        chosen = 0                          # 0 none, 1 by Markowitz, 2 in the column order
        if c_ok and ((not m_ok) or by_c.ops < by_m.ops):
            whole = by_c
            chosen = 2
        elif m_ok:
            whole = by_m
            chosen = 1
        if by_blocks and (chosen == 0 or blocked.ops <= whole.ops):
            kind = BLOCKS
            sw.ordering = _BLOCKED
            sw.fill = blocked.nnz if blocked.valid else -1
            sw.trial_repivots = bk_repivots(blocked)
        elif chosen != 0:
            kind = WHOLE
            sw.ordering = (_RCM_COLUMNS if has_q else _NATURAL_COLUMNS) if chosen == 2 else _MARKOWITZ
            sw.fill = whole.nnz if whole.valid else -1
            sw.trial_repivots = whole.repivots
        elif mode == _REFACTOR:
            whole = rf_new(n, colptr, rowidx, empty, False)
            kind = WHOLE
            sw.ordering = _MARKOWITZ
            sw.fill = -1
    if kind == SPARSE and mode == _AUTO and fills_in:
        kind = DENSE
    sw.kind = kind
    sw.whole = whole
    sw.blocks = blocked
    if kind == SPARSE:
        sw.current = _BY_SPARSE
    elif (kind == WHOLE and whole.valid != 0) or (kind == BLOCKS and blocked.valid != 0):
        sw.current = _KEPT
    else:
        sw.current = _NONE_MADE
    return sw


@njit(**_OPTS)
def sw_none():
    """A matrix of no states: what the compiled loops are handed when they
    factorise otherwise. Made without the trials, so that a run that never
    goes sparse never loads them."""
    empty = np.zeros(0, np.int64)
    start = np.zeros(1, np.int64)
    sw = structref.new(SW_T)
    sw.n = 0
    sw.kind = DENSE
    sw.colptr = start
    sw.rowidx = empty
    sw.masked = np.zeros(0)
    sw.mass = np.zeros(0)
    sw.has_mass = 0
    sw.mp = start
    sw.mi = empty
    sw.mx = np.zeros(0)
    sw.jtom = empty
    sw.diag_pos = empty
    sw.gp = gp_new(0)
    sw.q = empty
    sw.has_q = 0
    sw.whole = rf_new(0, start, empty, empty, False)
    sw.blocks = bk_new(0, start, empty, 0, empty)
    sw.fills_in = 0
    sw.current = _NONE_MADE
    sw.dense = np.zeros((1, 1))
    sw.dpiv = np.zeros(1, np.int64)
    sw.fill = -1
    sw.repivots = 0
    sw.fallbacks = 0
    sw.trial_repivots = 0
    sw.ordering = _NATURAL
    sw.fail_column = -1
    sw.fail_value = 0.0
    sw.fail_nonfinite = 0
    return sw


@njit(**_OPTS)
def _sw_sparse(sw, a, values):
    """By the Gilbert-Peierls LU in the chosen order (``sparseForm``)."""
    miter_update(a, values, sw.mass, sw.has_mass != 0, sw.mx, sw.jtom, sw.diag_pos)
    g = sw.gp
    gp_factorize(g, sw.mp, sw.mi, sw.mx, sw.q, sw.has_q != 0, np.inf)
    if g.singular:
        sw.fail_column = g.fail_original
        sw.fail_value = np.inf if g.nonfinite else 0.0
        sw.fail_nonfinite = g.nonfinite
        return NONFINITE if g.nonfinite else SINGULAR
    return OK


@njit(**_OPTS)
def _sw_dense(sw, a, values):
    """By the dense LU of ``linalg.js`` (``formAndFactor``), where a matrix the
    kept-pivot LU declined goes when the searching factor fills in."""
    n = sw.n
    if sw.dense.shape[0] != n:
        sw.dense = np.zeros((n, n))
        sw.dpiv = np.zeros(n, np.int64)
    lu = sw.dense
    piv = sw.dpiv
    colptr = sw.colptr
    rowidx = sw.rowidx
    for i in range(n):
        for j in range(n):
            lu[i, j] = 0.0
    bad = -1
    bad_value = 0.0
    for j in range(n):
        for p in range(colptr[j], colptr[j + 1]):
            v = -a * values[p]
            if bad < 0 and not math.isfinite(v):
                bad = j
                bad_value = v
            lu[rowidx[p], j] = v
    if bad >= 0:
        sw.fail_column = bad
        sw.fail_value = bad_value
        sw.fail_nonfinite = 1
        return NONFINITE
    mass = sw.mass
    if sw.has_mass:
        for i in range(n):
            lu[i, i] += mass[i]
    else:
        for i in range(n):
            lu[i, i] += 1.0
    for i in range(n):
        piv[i] = i
    for k in range(n):
        p = k
        max_abs = abs(lu[k, k])
        for i in range(k + 1, n):
            v = abs(lu[i, k])
            if v > max_abs:
                max_abs = v
                p = i
        if not (max_abs > 0) or not math.isfinite(max_abs):
            sw.fail_column = k
            sw.fail_value = max_abs
            sw.fail_nonfinite = 1 if max_abs != 0 else 0
            return NONFINITE if max_abs != 0 else SINGULAR
        if p != k:
            for j in range(n):
                tmp = lu[p, j]
                lu[p, j] = lu[k, j]
                lu[k, j] = tmp
            t = piv[p]
            piv[p] = piv[k]
            piv[k] = t
        pivot = lu[k, k]
        for i in range(k + 1, n):
            f = lu[i, k] / pivot
            if f == 0:
                continue
            lu[i, k] = f
            for j in range(k + 1, n):
                lu[i, j] -= f * lu[k, j]
    return OK


@njit(**_OPTS)
def sw_form(sw, a, values, held, any_held):
    """Factorises Mass - a*J, the rows ``held`` marks (where any_held) as rows
    of the identity: OK, SINGULAR or NONFINITE, with the column (and the
    value) in fail_column and fail_value. A matrix the kept-pivot LU declines
    goes to the LU that would otherwise have been used, whose answer is final."""
    use = values
    if any_held:
        use = sw.masked
        colptr = sw.colptr
        rowidx = sw.rowidx
        for p in range(use.size):
            use[p] = values[p]
        for j in range(sw.n):
            for p in range(colptr[j], colptr[j + 1]):
                if held[rowidx[p]] != 0:
                    use[p] = 0.0
    kind = sw.kind
    if kind == SPARSE:
        st = _sw_sparse(sw, a, use)
        sw.current = _BY_SPARSE if st == OK else _NONE_MADE
        return st
    has_mass = sw.has_mass != 0
    if kind == WHOLE:
        lu = sw.whole
        ok = rf_factor(lu, a, use, sw.mass, has_mass)
        nnz = lu.nnz
        repivots = lu.repivots
    else:
        bk = sw.blocks
        ok = bk_factor(bk, a, use, sw.mass, has_mass)
        nnz = bk.nnz
        repivots = bk_repivots(bk)
    if ok:
        sw.current = _KEPT
        sw.fill = nnz
        st = OK
    else:
        sw.fallbacks += 1
        if sw.fills_in:
            st = _sw_dense(sw, a, use)
            by = _BY_DENSE
        else:
            st = _sw_sparse(sw, a, use)
            by = _BY_SPARSE
        sw.current = by if st == OK else _NONE_MADE
    if st == OK:
        sw.repivots = repivots - sw.trial_repivots
    return st


@njit(**_OPTS)
def sw_solve(sw, b, out):
    """Against the latest formation, into ``out``: NaN after one that failed,
    which the solvers stop at -- the application's answer there is whatever
    a half-made factor gives."""
    current = sw.current
    if current == _NONE_MADE:
        for i in range(out.size):
            out[i] = np.nan
    elif current == _BY_SPARSE:
        gp_solve(sw.gp, b, out)
    elif current == _BY_DENSE:
        lu = sw.dense
        piv = sw.dpiv
        n = sw.n
        for i in range(n):
            out[i] = b[piv[i]]
        for i in range(1, n):
            s = out[i]
            for j in range(i):
                s -= lu[i, j] * out[j]
            out[i] = s
        for i in range(n - 1, -1, -1):
            s = out[i]
            for j in range(i + 1, n):
                s -= lu[i, j] * out[j]
            out[i] = s / lu[i, i]
    elif sw.kind == WHOLE:
        rf_solve(sw.whole, b, out)
    else:
        bk_solve(sw.blocks, b, out)


@njit(**_OPTS)
def _sw_state(sw, out):
    out[0] = sw.kind
    out[1] = sw.fill
    out[2] = sw.repivots
    out[3] = sw.fallbacks
    out[4] = sw.ordering
    out[5] = sw.fail_column
    out[6] = sw.fail_nonfinite
    out[7] = sw.current
    return sw.fail_value


# --- Python's side ----------------------------------------------------------------------------------


def decide(n: int, col_ptr: np.ndarray, row_idx: np.ndarray, values: np.ndarray, mode: str,
           mass: Optional[np.ndarray], dense_fill: float, too_big: bool, blocks: bool = True) -> Any:
    """The sparse iteration matrix the application makes for J's pattern
    (``col_ptr``, ``row_idx``) and its values at the start, in ``mode`` --
    'auto', 'refactor' or 'sparse' -- or, its kind DENSE (see :func:`state`),
    the word that ``auto`` factorises it densely."""
    m = np.ones(n) if mass is None else np.ascontiguousarray(mass, dtype=float)
    return sw_new(n, np.ascontiguousarray(col_ptr, dtype=np.int64), np.ascontiguousarray(row_idx, dtype=np.int64),
                  np.ascontiguousarray(values, dtype=float), m, mass is not None, MODES.get(mode, MODES['sparse']),
                  float(dense_fill), bool(too_big), bool(blocks))


def state(sw: Any) -> Dict[str, Any]:
    """What the matrix is and how its latest formation went: ``kind``,
    ``info`` as the application's has it (``lu``, ``fill``, ``ordering``,
    ``repivots``, ``fallbacks``) and, after a formation that failed,
    ``column``, ``value`` and ``nonfinite``."""
    out = np.zeros(8, dtype=np.int64)
    value = float(_sw_state(sw, out))
    kind = int(out[0])
    return {'kind': kind, 'lu': 'refactor' if kind in (WHOLE, BLOCKS) else ('sparse' if kind == SPARSE else 'dense'),
            'fill': None if out[1] < 0 else int(out[1]), 'repivots': int(out[2]), 'fallbacks': int(out[3]),
            'ordering': ORDERINGS[int(out[4])], 'column': int(out[5]), 'nonfinite': bool(out[6]), 'value': value}


_NO_HELD = np.zeros(0, dtype=np.int64)


def form(sw: Any, a: float, values: np.ndarray, held: Optional[np.ndarray] = None) -> int:
    """Factorises Mass - a*J (see :func:`sw_form`): OK, SINGULAR or NONFINITE."""
    if held is None:
        return int(sw_form(sw, float(a), np.ascontiguousarray(values, dtype=float), _NO_HELD, False))
    return int(sw_form(sw, float(a), np.ascontiguousarray(values, dtype=float),
                       np.ascontiguousarray(held, dtype=np.int64), True))


def solve(sw: Any, b: np.ndarray) -> np.ndarray:
    out = np.zeros(len(b))
    sw_solve(sw, np.ascontiguousarray(b, dtype=float), out)
    return out


_NONE: list = []


def none() -> Any:
    """The matrix of no states the compiled loops are handed when they factorise otherwise."""
    if not _NONE:
        _NONE.append(sw_none())
    return _NONE[0]


__all__ = ('BLOCKS', 'DENSE', 'MODES', 'NONFINITE', 'OK', 'ORDERINGS', 'SINGULAR', 'SPARSE', 'SW_T', 'WHOLE',
           'decide', 'form', 'none', 'solve', 'state', 'sw_form', 'sw_solve')
