"""Sparse matrices, held dense: the functions accept the same arguments and
give the same numbers, without the memory saving."""
import numpy as np

from . import bi
from ._util import err, nargchk, arr, darr, out, num, ival
from ..values import F64


@bi('sparse')
def sparse(nargout, *args):
    nargchk(args, 1, 6, 'sparse')
    if len(args) == 1:
        return out(darr(args[0]))
    if len(args) == 2:
        return out(np.zeros((ival(args[0]), ival(args[1]))))
    i = darr(args[0]).reshape(-1).astype(np.int64)
    j = darr(args[1]).reshape(-1).astype(np.int64)
    v = darr(args[2]).reshape(-1)
    n = max(i.size, j.size, v.size)
    i, j, v = np.resize(i, n), np.resize(j, n), np.resize(v, n)
    m = ival(args[3]) if len(args) > 3 else int(i.max()) if n else 0
    k = ival(args[4]) if len(args) > 4 else int(j.max()) if n else 0
    A = np.zeros((m, k), dtype=v.dtype if v.dtype.kind == 'c' else F64)
    np.add.at(A, (i - 1, j - 1), v)
    return out(A)


@bi('full')
def full(nargout, *args):
    return args[0]


@bi('speye')
def speye(nargout, *args):
    m = ival(args[0])
    n = ival(args[1]) if len(args) > 1 else m
    return out(np.eye(m, n))


@bi('spzeros')
def spzeros(nargout, *args):
    m = ival(args[0])
    n = ival(args[1]) if len(args) > 1 else m
    return out(np.zeros((m, n)))


@bi('spones')
def spones(nargout, *args):
    a = darr(args[0])
    return out((a != 0).astype(F64))


@bi('sprand', 'sprandn')
def sprand(nargout, *args):
    from .elmat import RNG
    m, n, d = ival(args[0]), ival(args[1]), num(args[2])
    a = RNG.uniform((m, n))
    mask = RNG.uniform((m, n)) < d
    return out(np.where(mask, a, 0.0))


@bi('spdiags', nout=2)
def spdiags(nargout, *args):
    """Diagonals as the columns of B, aligned as the language does: by the
    column of A when A has at least as many rows as columns, else by the row."""
    nargchk(args, 1, 4, 'spdiags')
    if len(args) <= 2:
        A = darr(args[0])
        m, n = A.shape[0], A.shape[1]
        if len(args) == 2:
            d = darr(args[1]).reshape(-1).astype(int)
        else:
            d = np.array([k for k in range(-(m - 1), n) if np.any(np.diagonal(A, k))], int)
        B = np.zeros((min(m, n), d.size), dtype=A.dtype)
        for c, off in enumerate(d):
            for i in range(max(0, -off), min(m, n - off)):
                B[i + off if m >= n else i, c] = A[i, i + off]
        return (out(B), out(d.astype(F64).reshape(-1, 1))) if nargout >= 2 else out(B)
    B = darr(args[0])
    d = darr(args[1]).reshape(-1).astype(int)
    if len(args) == 3:
        A = darr(args[2]).copy()
        m, n = A.shape[0], A.shape[1]
        if B.dtype.kind == 'c':
            A = A.astype(B.dtype)
    else:
        m, n = ival(args[2]), ival(args[3])
        A = np.zeros((m, n), dtype=B.dtype)
    if B.ndim == 2 and B.shape[1] != d.size and B.shape[0] == d.size:
        B = B.T
    for k, off in enumerate(d):
        for i in range(m):
            j = i + off
            if 0 <= j < n:
                # columns of B are indexed by the column of A for m >= n
                idx = j if m >= n else i
                if idx < B.shape[0]:
                    A[i, j] = B[idx, k]
    return out(A)


@bi('spalloc')
def spalloc(nargout, *args):
    return out(np.zeros((ival(args[0]), ival(args[1]))))


@bi('nzmax')
def nzmax(nargout, *args):
    return float(np.count_nonzero(arr(args[0])))
