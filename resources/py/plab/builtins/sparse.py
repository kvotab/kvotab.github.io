"""Sparse matrices: making them (sparse, speye, sprand, spdiags, spconvert,
...), asking about them (issparse, nnz, nzmax, nonzeros) and turning them
full. They are values.Sparse, held by SciPy (sparsemat.py has their
operators)."""
import math

import numpy as np

from . import bi
from ._util import err, nargchk, arr, darr, out, num, ival, opt_str
from ..values import F64, C128, numel, class_of, Sparse, shape_of, is_numeric
from .. import sparsemat as SPM


def _sp():
    import scipy.sparse as sp
    return sp


def _size_args(args, fn):
    if len(args) == 1 and numel(args[0]) == 2:
        m, n = (int(v) for v in np.asarray(darr(args[0]), F64).reshape(-1))
    else:
        m = ival(args[0])
        n = ival(args[1]) if len(args) > 1 else m
    return max(m, 0), max(n, 0)


@bi('sparse')
def sparse(nargout, *args):
    """sparse(A), sparse(m, n), sparse(i, j, v), sparse(i, j, v, m, n) and
    sparse(i, j, v, m, n, nz): values at (i, j), those at one place summed
    (logical ones combined by or)."""
    nargchk(args, 1, 6, 'sparse')
    if len(args) == 1:
        v = args[0]
        if type(v) is Sparse:
            return v
        return SPM.to_sparse(v)
    if len(args) == 2:
        return SPM.zeros(*_size_args(args, 'sparse'))
    if len(args) == 4:
        raise err('MATLAB:sparse:nargin', 'sparse takes 1, 2, 3, 5 or 6 inputs.', 'sparse')
    for a in args[:3]:
        if class_of(a) not in ('double', 'logical', 'char'):
            raise err('MATLAB:sparse:InvalidClass', 'The indices and values must be double or logical.', 'sparse')
    vv = args[2]
    logical = class_of(vv) == 'logical'
    i = np.asarray(arr(args[0])).reshape(-1, order='F').astype(F64)
    j = np.asarray(arr(args[1])).reshape(-1, order='F').astype(F64)
    v = (SPM.full(vv) if type(vv) is Sparse else np.asarray(arr(vv))).reshape(-1, order='F')
    n_ = max(i.size, j.size, v.size)
    sizes = [x.size for x in (i, j, v) if x.size != 1]
    if any(s != n_ for s in sizes):
        raise err('MATLAB:sparse:ThreeVectorsSameLength', 'Vectors must be the same lengths.', 'sparse')
    i, j, v = (np.repeat(x, n_) if x.size == 1 else x for x in (i, j, v))
    if n_ and (np.any(i < 1) or np.any(j < 1) or np.any(i != np.floor(i)) or np.any(j != np.floor(j))):
        raise err('MATLAB:sparse:InvalidIndex', 'Index into matrix must be positive.', 'sparse')
    m = ival(args[3]) if len(args) > 3 else (int(i.max()) if n_ else 0)
    n = ival(args[4]) if len(args) > 4 else (int(j.max()) if n_ else 0)
    if n_ and (i.max() > m or j.max() > n):
        raise err('MATLAB:sparse:IndexExceedsMatrixDimensions', 'Index exceeds matrix dimensions.', 'sparse')
    ii, jj = i.astype(np.int64) - 1, j.astype(np.int64) - 1
    if logical:
        mat = _sp().csc_matrix((v.astype(F64) != 0, (ii, jj)), shape=(m, n), dtype=F64)
        return SPM.make(mat != 0, logical=True)
    if v.dtype.kind not in 'fc':
        v = v.astype(F64)
    mat = _sp().coo_matrix((v, (ii, jj)), shape=(m, n)).tocsc()      # duplicates summed
    return SPM.make(mat)


@bi('full')
def full(nargout, *args):
    nargchk(args, 1, 1, 'full')
    v = args[0]
    if type(v) is Sparse:
        return SPM._value(v.dense())
    return v


@bi('issparse')
def issparse(nargout, *args):
    nargchk(args, 1, 1, 'issparse')
    return type(args[0]) is Sparse


@bi('speye')
def speye(nargout, *args):
    """The sparse identity, m-by-n."""
    nargchk(args, 0, 2, 'speye')
    if not args:
        return SPM.make(np.eye(1))
    if (len(args) == 1 and numel(args[0]) not in (1, 2)) or (len(args) == 2 and (numel(args[0]) != 1 or numel(args[1]) != 1)):
        raise err('MATLAB:speye:InvalidSize', 'The sizes must be scalars, or one vector of two.', 'speye')
    m, n = _size_args(args, 'speye')
    return SPM.make(_sp().eye(m, n, format='csc'))


@bi('spzeros')
def spzeros(nargout, *args):
    nargchk(args, 1, 2, 'spzeros')
    return SPM.zeros(*_size_args(args, 'spzeros'))


@bi('spalloc')
def spalloc(nargout, *args):
    """An all-zero sparse matrix (the room for nz nonzeros is not reserved:
    SciPy makes room as it is filled)."""
    nargchk(args, 2, 3, 'spalloc')
    if any(float(num(a)) < 0 for a in args):
        raise err('MATLAB:spalloc:Negative', 'The sizes and the room for nonzeros must not be negative.', 'spalloc')
    return SPM.zeros(ival(args[0]), ival(args[1]))


@bi('spones')
def spones(nargout, *args):
    """Ones where S has nonzeros."""
    nargchk(args, 1, 1, 'spones')
    s = SPM.to_sparse(args[0])
    m = s.m.astype(np.bool_).astype(F64)
    m.data[:] = 1.0
    return SPM.make(m)


def _rand_pattern(m, n, density, fn):
    """About density*m*n distinct positions (row, col), drawn from rand's generator."""
    from .elmat import RNG
    if not 0 <= density <= 1:
        raise err(f'MATLAB:{fn}:InvalidDensity', 'The density must be from 0 to 1.', fn)
    total = m * n
    k = int(round(density * total))
    if k == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    if total <= 1 << 24:
        pos = np.sort(RNG.rs.choice(total, size=k, replace=False))
    else:
        pos = np.unique(RNG.rs.randint(0, total, size=k, dtype=np.int64))
    return pos % m, pos // m


@bi('sprand')
def sprand(nargout, *args):
    """sprand(m, n, density): about density*m*n uniform values in (0, 1) at
    random places; sprand(S): S's pattern with uniform values."""
    from .elmat import RNG
    nargchk(args, 1, 4, 'sprand')
    if len(args) == 1:
        s = SPM.to_sparse(args[0])
        m = s.m.astype(np.bool_).astype(F64)
        m.data = RNG.rs.random_sample(m.data.size)
        return SPM.make(m)
    m, n, d = ival(args[0]), ival(args[1]), float(num(args[2]))
    r, c = _rand_pattern(m, n, d, 'sprand')
    vals = RNG.rs.random_sample(r.size)
    return SPM.make(_sp().csc_matrix((vals, (r, c)), shape=(m, n)))


@bi('sprandn')
def sprandn(nargout, *args):
    """sprandn(m, n, density): normal values at random places; sprandn(S): S's pattern."""
    from .elmat import RNG
    nargchk(args, 1, 4, 'sprandn')
    if len(args) == 1:
        s = SPM.to_sparse(args[0])
        m = s.m.astype(np.bool_).astype(F64)
        m.data = RNG.rs.standard_normal(m.data.size)
        return SPM.make(m)
    m, n, d = ival(args[0]), ival(args[1]), float(num(args[2]))
    r, c = _rand_pattern(m, n, d, 'sprandn')
    vals = RNG.rs.standard_normal(r.size)
    return SPM.make(_sp().csc_matrix((vals, (r, c)), shape=(m, n)))


@bi('sprandsym')
def sprandsym(nargout, *args):
    """sprandsym(n, density): a symmetric matrix of normal values, the lower
    triangle drawn and mirrored; sprandsym(S): the lower triangle of S's
    pattern, mirrored."""
    from .elmat import RNG
    nargchk(args, 1, 4, 'sprandsym')
    sp = _sp()
    if len(args) == 1 and numel(args[0]) > 1:
        s = SPM.to_sparse(args[0])
        L = sp.tril(s.m.astype(np.bool_)).tocsc().astype(F64)
        L.data = RNG.rs.standard_normal(L.data.size)
    else:
        if numel(args[0]) != 1:
            raise err('MATLAB:sprandsym:InvalidSize', 'n must be a scalar (or S the only input).', 'sprandsym')
        n, d = ival(args[0]), float(num(args[1])) if len(args) > 1 else 0.1
        if not 0 <= d <= 1:
            raise err('MATLAB:sprandsym:InvalidDensity', 'The density must be from 0 to 1.', 'sprandsym')
        target = int(round(d * n * n))
        if n * (n + 1) // 2 <= 1 << 24:
            # places on and below the diagonal in a random order, taken until they fill
            # density*n^2 places (one off the diagonal fills two, with its mirror)
            tri = n * (n + 1) // 2
            order = RNG.rs.permutation(tri)
            rows = (np.floor((np.sqrt(8.0 * order + 1) - 1) / 2)).astype(np.int64)
            cols = order - rows * (rows + 1) // 2
            cost = np.where(rows == cols, 1, 2)
            filled = np.cumsum(cost)
            take = filled <= target
            r, c = rows[take], cols[take]
        else:
            r, c = _rand_pattern(n, n, d, 'sprandsym')
            keep = r >= c
            r, c = r[keep], c[keep]
        L = sp.csc_matrix((RNG.rs.standard_normal(r.size), (r, c)), shape=(n, n))
    return SPM.make(L + sp.tril(L, -1).T)


@bi('spdiags', nout=2)
def spdiags(nargout, *args):
    """[B, d] = spdiags(A) takes the nonzero diagonals of A as the columns of
    B; spdiags(B, d, m, n) and spdiags(B, d, A) put columns of B on the
    diagonals d (a column aligned by the column of A when m >= n, else by its
    row): a sparse result."""
    nargchk(args, 1, 4, 'spdiags')
    if len(args) <= 2:
        A = SPM.to_sparse(args[0]).m
        m, n = A.shape
        if len(args) == 2:
            d = darr(args[1]).reshape(-1).astype(int)
        else:
            coo = A.tocoo()
            d = np.unique(coo.col - coo.row).astype(int)
        B = np.zeros((min(m, n), d.size), dtype=C128 if A.dtype.kind == 'c' else F64)
        for c, off in enumerate(d):
            diag = A.diagonal(off)
            for t, val in enumerate(diag):
                i = max(0, -off) + t
                row = i + off if m >= n else i
                if 0 <= row < B.shape[0]:
                    B[row, c] = val
        Bv = out(B)
        return (Bv, out(d.astype(F64).reshape(-1, 1))) if nargout >= 2 else Bv
    B = np.asarray(SPM.full(args[0]) if type(args[0]) is Sparse else arr(args[0]))
    d = darr(args[1]).reshape(-1).astype(int)
    if len(args) == 3:
        base = SPM.to_sparse(args[2]).m.tolil()
        m, n = base.shape
    else:
        m, n = ival(args[2]), ival(args[3])
        base = _sp().lil_matrix((m, n), dtype=C128 if B.dtype.kind == 'c' else F64)
    if B.dtype.kind == 'c' and base.dtype.kind != 'c':
        base = base.astype(C128)
    if B.ndim == 2 and B.shape[1] != d.size and B.shape[0] == d.size:
        B = B.T
    if B.ndim == 1 or B.shape[1] != d.size:
        B = B.reshape(-1, d.size)
    for k, off in enumerate(d):
        i = np.arange(max(0, -off), min(m, n - off))
        if i.size == 0:
            continue
        j = i + off
        idx = j if m >= n else i
        ok = idx < B.shape[0]
        base[i[ok], j[ok]] = B[idx[ok], k]
    return SPM.make(base.tocsc())


@bi('nzmax')
def nzmax(nargout, *args):
    """The room a sparse matrix has for nonzeros (here its nonzeros: SciPy
    keeps no more); numel for a full array."""
    nargchk(args, 1, 1, 'nzmax')
    v = args[0]
    if type(v) is Sparse:
        return float(max(v.nnz, 1))
    return float(numel(v))


@bi('nonzeros')
def nonzeros(nargout, *args):
    """The nonzero elements in column order, a full column."""
    nargchk(args, 1, 1, 'nonzeros')
    v = args[0]
    if type(v) is Sparse:
        coo = v.m.tocoo()
        order = np.lexsort((coo.row, coo.col))
        d = coo.data[order]
        return out(d.reshape(-1, 1) if d.dtype != np.bool_ else d.reshape(-1, 1))
    a = np.asarray(arr(v)).reshape(-1, order='F')
    return out(a[a != 0].reshape(-1, 1))


@bi('spconvert')
def spconvert(nargout, *args):
    """A sparse matrix from rows [i j v] (or [i j re im]); a last row [m n 0]
    gives the size."""
    nargchk(args, 1, 1, 'spconvert')
    if type(args[0]) is Sparse:
        return args[0]
    D = darr(args[0])
    if D.ndim != 2 or D.shape[1] not in (3, 4):
        raise err('MATLAB:spconvert:WrongSize', 'The rows must be [i j v] or [i j re im].', 'spconvert')
    i, j = D[:, 0], D[:, 1]
    v = D[:, 2] if D.shape[1] == 3 else D[:, 2] + 1j * D[:, 3]
    m, n = int(i.max()) if i.size else 0, int(j.max()) if j.size else 0
    return SPM.make(_sp().coo_matrix((v, (i.astype(np.int64) - 1, j.astype(np.int64) - 1)), shape=(m, n)).tocsc())


@bi('spfun', aw=True)
async def spfun(nargout, *args):
    """spfun(f, S): f applied to the nonzero elements of S, the zeros kept; a
    sparse result."""
    nargchk(args, 2, 2, 'spfun')
    from ..values import FH
    f, S = args
    if opt_str(f) is not None:
        from .. import runtime as R
        f = R.NamedFH(opt_str(f).strip())
    if not isinstance(f, FH):
        raise err('MATLAB:spfun:InvalidFunction', 'The first input must be a function handle or a function name.', 'spfun')
    if class_of(S) not in ('double', 'logical', 'single') and not (class_of(S) in ('int8', 'uint8', 'int16', 'uint16', 'int32', 'uint32', 'int64', 'uint64')):
        raise err('MATLAB:spfun:InvalidInput', 'The second input must be numeric or logical.', 'spfun')
    s = SPM.to_sparse(S)
    coo = s.m.tocoo()
    order = np.lexsort((coo.row, coo.col))
    rows, cols, vals = coo.row[order], coo.col[order], coo.data[order]
    arg = out(vals.reshape(-1, 1)) if vals.size != 1 else (complex(vals[0]) if vals.dtype.kind == 'c' else float(vals[0]))
    r = await f.acall(1, arg)
    r = np.asarray(arr(r[0] if isinstance(r, tuple) else r)).reshape(-1)
    if r.size != vals.size:
        raise err('MATLAB:spfun:WrongSize', 'The function must give one value per nonzero element.', 'spfun')
    return SPM.make(_sp().csc_matrix((r.astype(np.result_type(r.dtype, F64)), (rows, cols)), shape=s.shape))


# ---- builtins that keep matrices sparse ---------------------------------------------------------------------
# A builtin written for full arrays reads a sparse matrix full (arr). The
# ones below give sparse results for sparse inputs, as the language does:
# wrappers around the registered functions, made when this module loads
# (after elfun, elmat, datafun and matfun have registered theirs).

from . import REG, Info  # noqa: E402
from ..values import Char, Cell, Struct, Str, FH  # noqa: E402


def _rewrap(name, make_fn):
    old = REG.get(name)
    if old is None or old.aw or old.ws:
        return
    REG[name] = Info(old.name, make_fn(old.fn), old.ws, old.aw, old.nout, old.arr)


def _has_sparse(args):
    return any(type(a) is Sparse for a in args)


def _dense_args(args):
    return tuple(SPM._value(a.dense()) if type(a) is Sparse else a for a in args)


def _sparse_result(v):
    """A full numeric or logical 2-D result made sparse; anything else as it is."""
    c = class_of(v)
    if c in ('double', 'logical') and type(v) is not Sparse and len(shape_of(v)) == 2 and not isinstance(v, (Char, Cell, Struct, Str, FH)):
        return SPM.make(np.asarray(arr(v)), logical=c == 'logical')
    return v


def _elementwise(orig):
    """f(S, ...): on the stored values alone when f(0) is 0 (the zeros stay
    zeros), else on the full matrix; sparse either way."""
    def f(nargout, *args):
        if not _has_sparse(args):
            return orig(nargout, *args)
        if type(args[0]) is Sparse and not _has_sparse(args[1:]) and nargout <= 1:
            s = args[0]
            rest = args[1:]
            z = np.asarray(arr(orig(1, 0.0, *rest))).reshape(-1)
            if z.size == 1 and z[0] == 0:
                coo = s.m.tocoo()
                vals = coo.data.astype(F64) if coo.data.dtype == np.bool_ else coo.data
                col = out(vals.reshape(-1, 1)) if vals.size != 1 else (complex(vals[0]) if vals.dtype.kind == 'c' else float(vals[0]))
                r = orig(1, col, *rest)
                rv = np.asarray(arr(r)).reshape(-1)
                logical = class_of(r) == 'logical'
                return SPM.make(_sp().csc_matrix((rv, (coo.row, coo.col)), shape=s.shape), logical=logical)
        r = orig(nargout, *_dense_args(args))
        if type(args[0]) is not Sparse:
            return r
        if isinstance(r, tuple):
            return (_sparse_result(r[0]),) + tuple(r[1:])
        return _sparse_result(r)
    return f


_ELEMENTWISE = '''abs sign sqrt realsqrt exp expm1 log log10 log1p log2 reallog sin cos tan sec csc cot asin acos atan asec acsc
acot sinh cosh tanh sech csch coth asinh acosh atanh asech acsch acoth sind cosd tand secd cscd cotd asind acosd atand
asecd acscd acotd sinpi cospi deg2rad rad2deg floor ceil fix round real imag conj angle isnan isinf isfinite mod rem
hypot atan2 nthroot erf erfc erfinv erfcinv gamma gammaln pow2 power times plus minus rdivide ldivide uminus uplus
eq ne lt le gt ge and or xor not'''.split()
for _n in _ELEMENTWISE:
    _rewrap(_n, _elementwise)


def _keep_sparse(orig):
    """Functions of a matrix that give a matrix (cumsum, flip, circshift,
    chol, ...): worked on the full matrix, the first output made sparse
    again when the first input was sparse."""
    def f(nargout, *args):
        if not _has_sparse(args):
            return orig(nargout, *args)
        r = orig(nargout, *_dense_args(args))
        if type(args[0]) is not Sparse:
            return r
        if isinstance(r, tuple):
            return tuple(_sparse_result(x) if k == 0 or (shape_of(x) == shape_of(r[0]) and len(shape_of(x)) == 2 and min(shape_of(x)) > 1) else x for k, x in enumerate(r))
        return _sparse_result(r)
    return f


for _n in '''cumsum cumprod cummax cummin diff flip fliplr flipud rot90 circshift permute ipermute squeeze mean median prod var std
chol qr expm sqrtm logm funm pinv null orth tril triu'''.split():
    _rewrap(_n, _keep_sparse)


def _native(name):
    """Register fn as name's sparse path: it is called for sparse inputs and
    returns NotImplemented to hand the call to the full-array function."""
    def deco(fn):
        old = REG.get(name)
        if old is None:
            return fn
        prev = old.fn

        def f(nargout, *args):
            if _has_sparse(args):
                r = fn(nargout, *args)
                if r is not NotImplemented:
                    return r
                return _keep_sparse(prev)(nargout, *args)
            return prev(nargout, *args)
        REG[name] = Info(old.name, f, old.ws, old.aw, old.nout, old.arr)
        return fn
    return deco


def _dim_of(args, k, s):
    """The dimension argument k (0-based dims 0 or 1), None when not given;
    'all' as 'all'."""
    if len(args) <= k or numel(args[k]) == 0:
        return None
    o = opt_str(args[k])
    if o is not None:
        return 'all' if o.lower() == 'all' else NotImplemented
    d = int(num(args[k])) - 1
    return d if d in (0, 1) else NotImplemented


def _first_dim(s):
    return 1 if s.shape[0] == 1 else 0


def _row_or_col(mat, dim):
    """SciPy's sum along an axis (an np.matrix) as a sparse row or column."""
    return SPM.make(np.asarray(mat))


@_native('sum')
def _sum(nargout, *args):
    s = args[0]
    if type(s) is not Sparse or len(args) > 2:
        return NotImplemented
    dim = _dim_of(args, 1, s)
    if dim is NotImplemented or (dim is None and s.shape == (0, 0)):
        return NotImplemented
    m = s.m.astype(F64) if s.m.dtype == np.bool_ else s.m
    if dim == 'all':
        return SPM.make(np.array([[m.sum()]]))
    if dim is None:
        dim = _first_dim(s)
    return _row_or_col(m.sum(axis=dim), dim)


def _count_along(s, dim):
    return np.asarray((s.m != 0).sum(axis=dim))


@_native('any')
def _any(nargout, *args):
    s = args[0]
    if type(s) is not Sparse or len(args) > 2:
        return NotImplemented
    dim = _dim_of(args, 1, s)
    if dim is NotImplemented or (dim is None and s.shape == (0, 0)):
        return NotImplemented
    if dim == 'all':
        return SPM.make(np.array([[s.nnz > 0]]), logical=True)
    if dim is None:
        dim = _first_dim(s)
    return SPM.make(_count_along(s, dim) > 0, logical=True)


@_native('all')
def _all(nargout, *args):
    s = args[0]
    if type(s) is not Sparse or len(args) > 2:
        return NotImplemented
    dim = _dim_of(args, 1, s)
    if dim is NotImplemented or (dim is None and s.shape == (0, 0)):
        return NotImplemented
    r, c = s.shape
    if dim == 'all':
        return SPM.make(np.array([[s.nnz == r * c]]), logical=True)
    if dim is None:
        dim = _first_dim(s)
    return SPM.make(_count_along(s, dim) == s.shape[dim], logical=True)


def _minmax_native(is_max):
    def fn(nargout, *args):
        s = args[0]
        if type(s) is not Sparse or s.m.dtype.kind == 'c' or nargout > 1:
            return NotImplemented
        if len(args) == 1:
            dim = _first_dim(s)
        elif len(args) == 3 and numel(args[1]) == 0:
            dim = _dim_of(args, 2, s)
            if dim is NotImplemented or dim == 'all' or dim is None:
                return NotImplemented
        else:
            return NotImplemented
        m = s.m.astype(F64) if s.m.dtype == np.bool_ else s.m
        if np.any(np.isnan(m.data)) or s.shape[dim] == 0:
            return NotImplemented
        r = m.max(axis=dim) if is_max else m.min(axis=dim)
        return SPM.make(r.toarray() if hasattr(r, 'toarray') else np.asarray(r))
    return fn


_native('max')(_minmax_native(True))
_native('min')(_minmax_native(False))


@_native('find')
def _find(nargout, *args):
    s = args[0]
    if type(s) is not Sparse:
        return NotImplemented
    r, c = s.shape
    coo = s.m.tocoo()
    order = np.lexsort((coo.row, coo.col))
    rows, cols, vals = coo.row[order], coo.col[order], coo.data[order]
    if len(args) > 1:
        k = ival(args[1])
        last = len(args) > 2 and (opt_str(args[2]) or '').lower() == 'last'
        rows, cols, vals = (x[-k:] if last else x[:k] for x in (rows, cols, vals)) if k > 0 else (x[:0] for x in (rows, cols, vals))
    shape = (1, -1) if r == 1 and c != 1 else (-1, 1)
    if r * c in (0, 1) and rows.size == 0:
        shape = (0, 0)
    if nargout <= 1:
        lin = (cols.astype(F64) * r + rows + 1)
        return out(lin.reshape(shape)) if lin.size else np.zeros((0, 0) if shape == (0, 0) else ((1, 0) if shape[0] == 1 else (0, 1)))

    def col(x):
        return out(np.asarray(x).reshape(shape)) if np.asarray(x).size else np.zeros((0, 0) if shape == (0, 0) else ((1, 0) if shape[0] == 1 else (0, 1)))
    res = [col(rows.astype(F64) + 1), col(cols.astype(F64) + 1), col(vals)]
    return tuple(res[:nargout])


@_native('reshape')
def _reshape(nargout, *args):
    s = args[0]
    if type(s) is not Sparse:
        return NotImplemented
    dims = [a for a in args[1:]]
    if len(dims) == 1:
        d = np.asarray(arr(dims[0])).reshape(-1)
        if d.size != 2:
            raise err('MATLAB:sparse:NDArray', 'Sparse matrices are 2-D: they reshape to two dimensions.', 'reshape')
        p, q = int(d[0]), int(d[1])
    elif len(dims) == 2:
        total = s.shape[0] * s.shape[1]
        if numel(dims[0]) == 0:
            q = ival(dims[1])
            p = total // q if q else 0
        elif numel(dims[1]) == 0:
            p = ival(dims[0])
            q = total // p if p else 0
        else:
            p, q = ival(dims[0]), ival(dims[1])
    else:
        raise err('MATLAB:sparse:NDArray', 'Sparse matrices are 2-D: they reshape to two dimensions.', 'reshape')
    if p * q != s.shape[0] * s.shape[1]:
        raise err('MATLAB:getReshapeDims:notSameNumel', 'Number of elements must not change. Use [] as one of the size inputs to automatically calculate the appropriate size for that dimension.', 'reshape')
    return SPM.make(s.m.reshape((p, q), order='F'))


@_native('diag')
def _diag(nargout, *args):
    s = args[0]
    if type(s) is not Sparse:
        return NotImplemented
    k = ival(args[1]) if len(args) > 1 else 0
    r, c = s.shape
    sp = _sp()
    if r == 1 or c == 1:
        v = s.m.toarray().reshape(-1) if s.nnz else np.zeros(r * c, s.m.dtype)
        n = v.size + abs(k)
        return SPM.make(sp.diags([v], [k], shape=(n, n), format='csc'), logical=s.m.dtype == np.bool_)
    d = s.m.diagonal(k)
    return SPM.make(d.reshape(-1, 1), logical=s.m.dtype == np.bool_)


@_native('tril')
def _tril(nargout, *args):
    s = args[0]
    if type(s) is not Sparse:
        return NotImplemented
    k = ival(args[1]) if len(args) > 1 else 0
    return SPM.make(_sp().tril(s.m, k, format='csc'), logical=s.m.dtype == np.bool_)


@_native('triu')
def _triu(nargout, *args):
    s = args[0]
    if type(s) is not Sparse:
        return NotImplemented
    k = ival(args[1]) if len(args) > 1 else 0
    return SPM.make(_sp().triu(s.m, k, format='csc'), logical=s.m.dtype == np.bool_)


@_native('kron')
def _kron(nargout, *args):
    a, b = (SPM.to_sparse(x).m for x in args[:2])
    return SPM.make(_sp().kron(a.astype(F64) if a.dtype == np.bool_ else a, b.astype(F64) if b.dtype == np.bool_ else b, format='csc'))


@_native('repmat')
def _repmat(nargout, *args):
    s = args[0]
    if type(s) is not Sparse:
        return NotImplemented
    if len(args) == 2:
        d = np.asarray(arr(args[1])).reshape(-1)
        p, q = (int(d[0]), int(d[0])) if d.size == 1 else (int(d[0]), int(d[1]))
        if d.size > 2 and np.any(d[2:] != 1):
            return NotImplemented
    else:
        p, q = ival(args[1]), ival(args[2])
    m = s.m
    sp = _sp()
    rows = sp.vstack([m] * p, format='csc') if p > 0 else sp.csc_matrix((0, m.shape[1]), dtype=m.dtype)
    full_ = sp.hstack([rows] * q, format='csc') if q > 0 else sp.csc_matrix((rows.shape[0], 0), dtype=m.dtype)
    return SPM.make(full_, logical=m.dtype == np.bool_)


@_native('blkdiag')
def _blkdiag(nargout, *args):
    mats = [SPM.to_sparse(a).m for a in args]
    logical = all(m.dtype == np.bool_ for m in mats)
    mats = [m if logical else m.astype(C128 if m.dtype.kind == 'c' else F64) for m in mats]
    return SPM.make(_sp().block_diag(mats, format='csc'), logical=logical)


_ISEQUAL_FULL = REG['isequal'].fn if 'isequal' in REG else None


@_native('isequal')
def _isequal(nargout, *args):
    vals = list(args)
    first = vals[0]
    for v in vals[1:]:
        if shape_of(v) != shape_of(first):
            return False
        if type(first) is Sparse and type(v) is Sparse:
            d = first.m.astype(C128 if first.m.dtype.kind == 'c' or v.m.dtype.kind == 'c' else F64) - v.m.astype(C128 if first.m.dtype.kind == 'c' or v.m.dtype.kind == 'c' else F64)
            if d.nnz and np.any(d.data != 0) or np.any(np.isnan(first.m.data)) or np.any(np.isnan(v.m.data)):
                return False
        else:
            a = SPM.full(first) if type(first) is Sparse else first
            b = SPM.full(v) if type(v) is Sparse else v
            if not _ISEQUAL_FULL(1, SPM._value(a) if type(a) is np.ndarray else a, SPM._value(b) if type(b) is np.ndarray else b):
                return False
    return True


@_native('trace')
def _trace(nargout, *args):
    s = args[0]
    if type(s) is not Sparse or s.shape[0] != s.shape[1]:
        return NotImplemented
    t = s.m.diagonal().sum()
    return complex(t) if s.m.dtype.kind == 'c' else float(t)


@_native('double')
def _double(nargout, *args):
    s = args[0]
    return SPM.make(s.m.astype(F64) if s.m.dtype == np.bool_ else s.m)


@_native('logical')
def _logical(nargout, *args):
    s = args[0]
    if s.m.dtype.kind == 'c':
        raise err('MATLAB:nologicalcomplex', 'Complex values cannot be converted to logicals.', 'logical')
    if s.m.dtype != np.bool_ and np.any(np.isnan(s.m.data)):
        raise err('MATLAB:nologicalnan', 'NaN values cannot be converted to logicals.', 'logical')
    return SPM.make(s.m != 0, logical=True)


def _no_sparse(name):
    @_native(name)
    def fn(nargout, *args):
        raise err(f'MATLAB:{name}:sparse', f'Sparse matrices are double or logical: converting one to {name} is not supported. Use full first.', name)
    return fn


for _n in ('single', 'int8', 'uint8', 'int16', 'uint16', 'int32', 'uint32', 'int64', 'uint64', 'char'):
    _no_sparse(_n)


# ---- linear algebra -----------------------------------------------------------------------------------------

def _float_m(s):
    m = s.m
    return m.astype(F64) if m.dtype == np.bool_ else m


def _square(s, fn):
    if s.shape[0] != s.shape[1]:
        raise err(f'MATLAB:{fn}:square', 'Matrix must be square.', fn)


def _warn(ident, msg):
    from .. import runtime as R
    R.warn(ident, msg)


def _splu(m, natural=False):
    import scipy.sparse.linalg as SL
    opts = dict(permc_spec='NATURAL', diag_pivot_thresh=1.0) if natural else {}
    return SL.splu(m.tocsc(), **opts)


@_native('inv')
def _inv(nargout, *args):
    s = args[0]
    _square(s, 'inv')
    n = s.shape[0]
    m = _float_m(s)
    try:
        lu = _splu(m)
        X = lu.solve(np.eye(n, dtype=C128 if m.dtype.kind == 'c' else F64))
    except RuntimeError:
        _warn('MATLAB:singularMatrix', 'Matrix is singular to working precision.')
        return SPM.make(np.full((n, n), np.inf))
    return SPM.make(X)


def _perm_sign(p):
    """The sign of a permutation (by its cycles)."""
    p = np.asarray(p)
    seen = np.zeros(p.size, bool)
    sign = 1
    for i in range(p.size):
        if not seen[i]:
            j, length = i, 0
            while not seen[j]:
                seen[j] = True
                j = p[j]
                length += 1
            if length % 2 == 0:
                sign = -sign
    return sign


@_native('det')
def _det(nargout, *args):
    s = args[0]
    _square(s, 'det')
    if s.shape[0] == 0:
        return 1.0
    m = _float_m(s)
    try:
        lu = _splu(m)
    except RuntimeError:
        return 0.0
    d = np.prod(lu.U.diagonal()) * _perm_sign(lu.perm_r) * _perm_sign(lu.perm_c)
    return complex(d) if np.iscomplexobj(d) and d.imag != 0 else float(np.real(d))


@_native('lu')
def _lu(nargout, *args):
    """[L, U] = lu(S) (L the row-permuted lower factor, S = L*U), [L, U, P]
    (P*S = L*U, partial pivoting, no column ordering) and [L, U, P, Q] (P*S*Q
    = L*U with SuperLU's COLAMD ordering): sparse factors by SuperLU; a
    singular or non-square matrix by a full LU, its factors made sparse.
    'vector' gives the permutations as vectors."""
    s = args[0]
    vector = any(opt_str(a) is not None and opt_str(a).lower() == 'vector' for a in args[1:])
    if nargout > 4:
        raise err('MATLAB:TooManyOutputs', 'Too many output arguments.', 'lu')
    r, c = s.shape
    m = _float_m(s)
    sp = _sp()
    lu = None
    if r == c and r:
        try:
            lu = _splu(m, natural=nargout < 4)
        except RuntimeError:
            lu = None
    if lu is not None:
        L, U = lu.L.tocsc(), lu.U.tocsc()
        # SuperLU: Pr * A * Pc = L * U with Pr[perm_r[i], i] = 1 and Pc[i, perm_c[i]] = 1
        pr = np.argsort(lu.perm_r)          # row k of P*S is row pr[k] of S
        pc = np.asarray(lu.perm_c)          # column k of S*Q is column pc[k] of S
    else:
        import scipy.linalg as sla
        P, L, U = sla.lu(m.toarray())
        L, U = sp.csc_matrix(L), sp.csc_matrix(U)
        pr = np.argmax(P, axis=0) if r else np.zeros(0, int)
        pc = np.arange(c)
    Pr = sp.csc_matrix((np.ones(r), (np.arange(r), pr)), shape=(r, r))
    if nargout <= 1:
        if r != c:
            return NotImplemented
        return SPM.make(L - sp.identity(r, format='csc') + U)
    if nargout == 2:
        return SPM.make(Pr.T @ L), SPM.make(U)
    Pout = out((pr + 1.0).reshape(1, -1)) if vector else SPM.make(Pr)
    if nargout == 3:
        return SPM.make(L), SPM.make(U), Pout
    Qout = out((pc + 1.0).reshape(1, -1)) if vector else SPM.make(sp.csc_matrix((np.ones(c), (pc, np.arange(c))), shape=(c, c)))
    return SPM.make(L), SPM.make(U), Pout, Qout


@_native('expm')
def _expm(nargout, *args):
    import scipy.sparse.linalg as SL
    s = args[0]
    _square(s, 'expm')
    return SPM.make(SL.expm(_float_m(s).tocsc()))


@_native('norm')
def _norm(nargout, *args):
    """1, Inf and 'fro' norms from the stored values; the 2-norm of a vector
    the same way, of a matrix by its largest singular value (svds)."""
    s = args[0]
    p = args[1] if len(args) > 1 else 2.0
    ps = opt_str(p)
    m = _float_m(s)
    r, c = s.shape
    a = abs(m)
    if r == 1 or c == 1:
        v = a.data
        if ps is not None:
            ps = ps.lower()
            if ps == 'fro':
                return float(np.sqrt(np.sum(v ** 2)))
            if ps == 'inf':
                return float(v.max()) if v.size else 0.0
            return NotImplemented
        q = float(num(p))
        if q == math.inf:
            return float(v.max()) if v.size else 0.0
        if q == -math.inf:
            return float(v.min()) if v.size == r * c else 0.0
        return float(np.sum(v ** q) ** (1 / q)) if v.size else 0.0
    if ps is not None:
        ps = ps.lower()
        if ps == 'fro':
            return float(np.sqrt(np.sum(a.data ** 2)))
        if ps == 'inf':
            return float(np.asarray(a.sum(axis=1)).max()) if r and c else 0.0
        return NotImplemented
    q = float(num(p))
    if q == 1:
        return float(np.asarray(a.sum(axis=0)).max()) if r and c else 0.0
    if q == math.inf:
        return float(np.asarray(a.sum(axis=1)).max()) if r and c else 0.0
    if q == 2:
        if min(r, c) <= 200:
            return float(np.linalg.norm(m.toarray(), 2))
        import scipy.sparse.linalg as SL
        return float(SL.svds(m, k=1, return_singular_vectors=False)[0])
    return NotImplemented


def _normest_impl(A, tol=1e-6, maxit=100):
    """The 2-norm by the power method on A'*A."""
    x = np.asarray(abs(A).sum(axis=0)).reshape(-1)
    e = np.linalg.norm(x)
    if e == 0:
        return 0.0, 0
    x = x / e
    e0 = 0.0
    it = 0
    while abs(e - e0) > tol * e and it < maxit:
        e0 = e
        Ax = A @ x
        if np.count_nonzero(Ax) == 0:
            Ax = np.random.RandomState(0).random_sample(Ax.shape)
        x = A.conj().T @ Ax
        normx = np.linalg.norm(x)
        e = normx / np.linalg.norm(Ax)
        x = x / normx
        it += 1
    return float(e), it


@bi('normest', nout=2)
def normest(nargout, *args):
    """[n, count] = normest(S, tol): an estimate of the 2-norm by the power
    method on S'*S (tolerance 1e-6 unless given)."""
    nargchk(args, 1, 2, 'normest')
    A = SPM.to_sparse(args[0]).m if type(args[0]) is Sparse else np.asarray(darr(args[0]))
    if type(args[0]) is Sparse and A.dtype == np.bool_:
        A = A.astype(F64)
    tol = float(num(args[1])) if len(args) > 1 else 1e-6
    e, it = _normest_impl(A, tol)
    if it >= 100:
        _warn('MATLAB:normest:notconverge', f'normest did not converge in 100 iterations (tolerance {tol:g}).')
    return (e, float(it)) if nargout > 1 else e


@_native('condest')
def _condest(nargout, *args):
    """The 1-norm condition number: norm(S, 1) times SciPy's onenormest of
    the inverse, applied through SuperLU's factors."""
    import scipy.sparse.linalg as SL
    s = args[0]
    _square(s, 'condest')
    m = _float_m(s)
    n = s.shape[0]
    try:
        lu = _splu(m)
    except RuntimeError:
        return math.inf
    inv = SL.LinearOperator((n, n), matvec=lu.solve, rmatvec=lambda x: lu.solve(x, trans='T'), dtype=m.dtype)
    a1 = float(np.asarray(abs(m).sum(axis=0)).max()) if n else 0.0
    return a1 * float(SL.onenormest(inv))


def _eig_sort(w, sigma):
    """The order eigs and svds give: by the size the sigma asks for."""
    if isinstance(sigma, str):
        key = {'largestabs': -np.abs(w), 'lm': -np.abs(w), 'smallestabs': np.abs(w), 'sm': np.abs(w),
               'largestreal': -w.real, 'lr': -w.real, 'la': -w.real, 'smallestreal': w.real, 'sr': w.real, 'sa': w.real,
               'largestimag': -w.imag, 'li': -w.imag, 'smallestimag': w.imag, 'si': w.imag}.get(sigma)
        if key is None:
            raise err('MATLAB:eigs:InvalidSigma', f"Unknown sigma '{sigma}'.", 'eigs')
        return np.argsort(key, kind='stable')
    return np.argsort(np.abs(w - sigma), kind='stable')


_EIGS_OPTS = {'tolerance': 'tol', 'tol': 'tol', 'maxiterations': 'maxit', 'maxit': 'maxit', 'startvector': 'v0', 'v0': 'v0',
              'subspacedimension': 'p', 'p': 'p', 'issymmetricdefinite': 'spd', 'display': None, 'disp': None,
              'failuretreatment': None, 'isfunctionsymmetric': 'issym', 'issym': 'issym', 'isreal': None, 'cholb': None, 'permb': None}


def _eigs_options(rest):
    """The options after k and sigma: a struct (opts.tol, ...) or name-value
    pairs, as ARPACK's settings."""
    o = {}
    if rest and type(rest[0]) is Struct:
        st = rest.pop(0)
        pairs = [(k, st.get1(k)) for k in st.keys]
    else:
        pairs = list(zip(rest[0::2], rest[1::2]))
        pairs = [(opt_str(k) or '', v) for k, v in pairs]
    for k, v in pairs:
        key = _EIGS_OPTS.get(k.lower(), 'bad')
        if key == 'bad':
            raise err('MATLAB:eigs:InvalidOption', f"'{k}' is not an option of eigs.", 'eigs')
        if key == 'v0':
            o['v0'] = np.asarray(darr(v)).reshape(-1)
        elif key in ('tol',):
            o['tol'] = float(num(v))
        elif key in ('maxit', 'p'):
            o['maxiter' if key == 'maxit' else 'ncv'] = int(num(v))
        elif key == 'issym':
            o['issym'] = bool(num(v))
    return o


def _eigs_impl(nargout, args):
    """d = eigs(A, k, sigma, opts) and [V, D, flag]: a full eigendecomposition
    for small matrices, ARPACK (scipy.sparse.linalg.eigs, eigsh for symmetric
    ones) for large ones and for a function handle; k eigenvalues (6) picked
    by sigma ('largestabs')."""
    import scipy.linalg as sla
    import scipy.sparse.linalg as SL
    rest = list(args[1:])
    A = args[0]
    fh = isinstance(A, FH)
    if fh:
        if not rest:
            raise err('MATLAB:eigs:nargin', 'eigs with a function needs the size n.', 'eigs')
        n = ival(rest.pop(0))
    B = None
    if not fh and rest and not is_text(rest[0]) and type(rest[0]) is not Struct and numel(rest[0]) > 1:
        B = rest.pop(0)
    k = 6
    if rest and not is_text(rest[0]) and type(rest[0]) is not Struct:
        k = ival(rest.pop(0)) if numel(rest[0]) else (rest.pop(0), 6)[1]
    sigma = 'largestabs'
    if rest and type(rest[0]) is not Struct:
        o = opt_str(rest[0])
        if o is None:
            x = num(rest.pop(0))
            sigma = complex(x) if isinstance(x, complex) else float(x)
        elif o.lower() not in _EIGS_OPTS:
            sigma = o.lower()
            rest.pop(0)
    if isinstance(sigma, str):
        _eig_sort(np.zeros(0), sigma)
    opts = _eigs_options(rest)
    if fh:
        def apply(x):
            return np.asarray(arr(A.scall(1, out(np.asarray(x).reshape(-1, 1))))).reshape(-1)
        op = SL.LinearOperator((n, n), matvec=apply, dtype=F64)
        k = min(k, n - 2) if n > 2 else n
        kw = dict(k=k, tol=opts.get('tol', 0), maxiter=opts.get('maxiter'), v0=opts.get('v0'), ncv=opts.get('ncv'))
        if isinstance(sigma, str) and sigma not in ('smallestabs', 'sm'):
            sym = opts.get('issym', False)
            which = _ARPACK_WHICH(sigma, sym)
            call = SL.eigsh if sym else SL.eigs
            run = lambda: call(op, which=which, **kw)
        else:
            # the function gives (A - sigma*I)\x: ARPACK's shift-invert with it as OPinv
            sg = 0.0 if isinstance(sigma, str) else sigma
            sym = opts.get('issym', False)
            ident = SL.LinearOperator((n, n), matvec=lambda x: x, dtype=F64)
            call = SL.eigsh if sym else SL.eigs
            run = lambda: call(ident, sigma=sg, OPinv=op, which='LM', **kw)
        try:
            w, V = run()
            flag = 0.0
        except SL.ArpackNoConvergence as e:
            w, V = e.eigenvalues, e.eigenvectors
            flag = 1.0
        order = _eig_sort(w, sigma)
        w, V = w[order], V[:, order]
        return _eigs_out(nargout, w, V, flag)
    M = _float_m(A) if type(A) is Sparse else np.asarray(darr(A))
    n = M.shape[0]
    if M.shape[0] != M.shape[1]:
        raise err('MATLAB:eigs:NonSquareMatrix', 'Matrix must be square.', 'eigs')
    k = min(k, n)
    Bm = None if B is None else (_float_m(B) if type(B) is Sparse else np.asarray(darr(B)))
    if n <= 600 or k >= n - 1:
        Md = M.toarray() if hasattr(M, 'toarray') else M
        Bd = None if Bm is None else (Bm.toarray() if hasattr(Bm, 'toarray') else Bm)
        if not np.all(np.isfinite(Md)):
            raise err('MATLAB:eigs:matrixWithNaNInf', 'Input matrix must not contain NaN or Inf.', 'eigs')
        w, V = sla.eig(Md, Bd)
        order = _eig_sort(w, sigma)[:k]
        w, V = w[order], V[:, order]
        nv = np.linalg.norm(V, axis=0)
        V = V / np.where(nv == 0, 1, nv)
        return _eigs_out(nargout, w, V, 0.0)
    if hasattr(M, 'nnz'):
        sym = (abs(M - M.conj().T) > 1e-14 * abs(M).max()).nnz == 0
    else:
        sym = np.allclose(M, M.conj().T)
    sym = opts.get('issym', sym)
    kw = dict(k=k, M=Bm, tol=opts.get('tol', 0), maxiter=opts.get('maxiter'), v0=opts.get('v0'), ncv=opts.get('ncv'))
    if isinstance(sigma, str):
        if sigma in ('smallestabs', 'sm'):
            kw.update(sigma=0.0, which='LM')
        else:
            kw.update(which=_ARPACK_WHICH(sigma, sym))
    else:
        kw.update(sigma=sigma, which='LM')
    call = SL.eigsh if sym and M.dtype.kind != 'c' and not isinstance(sigma, complex) and kw['which'] not in ('LI', 'SI') else SL.eigs
    try:
        try:
            w, V = call(M, **kw)
        except RuntimeError:
            if 'sigma' not in kw:
                raise
            # sigma is an eigenvalue: A - sigma*I cannot be factored, so shift it a little
            kw['sigma'] += 1e-10 * max(1.0, abs(kw['sigma']))
            w, V = call(M, **kw)
        flag = 0.0
    except SL.ArpackNoConvergence as e:
        w, V = e.eigenvalues, e.eigenvectors
        flag = 1.0
    order = _eig_sort(w, sigma)
    return _eigs_out(nargout, w[order], V[:, order], flag)


def _ARPACK_WHICH(sigma, sym):
    w = {'largestabs': 'LM', 'lm': 'LM', 'largestreal': 'LR', 'lr': 'LR', 'la': 'LR', 'smallestreal': 'SR', 'sr': 'SR',
         'sa': 'SR', 'largestimag': 'LI', 'li': 'LI', 'smallestimag': 'SI', 'si': 'SI'}[sigma]
    if sym:
        w = {'LR': 'LA', 'SR': 'SA'}.get(w, w)
    return w


def _eigs_out(nargout, w, V, flag):
    w = np.real_if_close(np.asarray(w), tol=1000)
    if nargout <= 1:
        return out(w.reshape(-1, 1))
    V = np.real_if_close(np.asarray(V), tol=1000) if w.dtype.kind != 'c' else np.asarray(V)
    return (out(V), out(np.diag(w)), flag)[:nargout]


def _svds_impl(nargout, args):
    """s = svds(A, k, sigma) and [U, S, V, flag]: a full SVD for small
    matrices, ARPACK (scipy.sparse.linalg.svds) for large ones; k (6) values
    picked by sigma ('largest', 'smallest', 'smallestnz' or a number)."""
    A = args[0]
    k = ival(args[1]) if len(args) > 1 and numel(args[1]) else 6
    sigma = 'largest'
    if len(args) > 2:
        o = opt_str(args[2])
        sigma = o.lower() if o is not None else float(num(args[2]))
        if isinstance(sigma, str) and sigma not in ('largest', 'smallest', 'smallestnz'):
            raise err('MATLAB:svds:InvalidSigma', "sigma is 'largest', 'smallest', 'smallestnz' or a number.", 'svds')
    M = _float_m(A) if type(A) is Sparse else np.asarray(darr(A))
    r, c = M.shape
    k = min(k, r, c)
    if min(r, c) <= 600 or k >= min(r, c) - 1:
        Md = M.toarray() if hasattr(M, 'toarray') else M
        U, s, Vh = np.linalg.svd(Md, full_matrices=False)
        if sigma == 'largest':
            order = np.arange(s.size)
        elif sigma == 'smallest':
            order = np.argsort(s, kind='stable')
        elif sigma == 'smallestnz':
            nz = np.flatnonzero(s > max(r, c) * np.finfo(float).eps * (s.max() if s.size else 0))
            order = nz[np.argsort(s[nz], kind='stable')]
        else:
            order = np.argsort(np.abs(s - sigma), kind='stable')
        order = order[:k]
        U, s, V = U[:, order], s[order], Vh.conj().T[:, order]
        flag = 0.0
    elif isinstance(sigma, float):
        # the singular values nearest sigma: eigenvalues of [0 A; A' 0] (which are +-s) nearest it
        import scipy.sparse.linalg as SL
        sp = _sp()
        Ms = sp.csc_matrix(M)
        Bm = sp.bmat([[None, Ms], [Ms.conj().T, None]], format='csc')
        try:
            w, X = SL.eigsh(Bm, k=min(2 * k, r + c - 1), sigma=sigma, which='LM')
        except RuntimeError:
            w, X = SL.eigsh(Bm, k=min(2 * k, r + c - 1), sigma=sigma + 1e-10 * max(1.0, abs(sigma)), which='LM')
        keep = np.flatnonzero(w > 0)
        keep = keep[np.argsort(np.abs(w[keep] - sigma), kind='stable')][:k]
        s = w[keep]
        U, V = np.sqrt(2) * X[:r, keep], np.sqrt(2) * X[r:, keep]
        flag = 0.0
    else:
        import scipy.sparse.linalg as SL
        which = 'SM' if sigma in ('smallest', 'smallestnz') else 'LM'
        U, s, Vh = SL.svds(M, k=k, which=which)
        order = np.argsort(-s if which == 'LM' else s, kind='stable')
        U, s, V = U[:, order], s[order], Vh.conj().T[:, order]
        flag = 0.0
    if nargout <= 1:
        return out(s.reshape(-1, 1))
    return (out(U), out(np.diag(s)), out(V), flag)[:nargout]


def _replace(name, impl, nout):
    REG[name] = Info(name, lambda nargout, *args: impl(nargout, args), False, False, nout, True)


from ..values import is_text  # noqa: E402
_replace('eigs', _eigs_impl, 3)
_replace('svds', _svds_impl, 4)


# ---- orderings, structure and incomplete factors -------------------------------------------------------------

def _pattern(v, symmetric=False):
    """The nonzero pattern as a CSC matrix of ones (made symmetric: S + S')."""
    m = SPM.to_sparse(v).m.astype(np.bool_).astype(F64)
    if symmetric:
        m = (m + m.T).tocsc()
        m.data[:] = 1.0
    return m


def _perm_out(p):
    return out((np.asarray(p, F64) + 1).reshape(1, -1))


@bi('symrcm')
def symrcm(nargout, *args):
    """The reverse Cuthill-McKee ordering of S + S' (scipy.sparse.csgraph),
    which brings the nonzeros near the diagonal."""
    nargchk(args, 1, 1, 'symrcm')
    from scipy.sparse.csgraph import reverse_cuthill_mckee
    m = _pattern(args[0], True)
    if m.shape[0] != m.shape[1]:
        raise err('MATLAB:symrcm:square', 'Matrix must be square.', 'symrcm')
    return _perm_out(reverse_cuthill_mckee(m.tocsr(), symmetric_mode=True))


def _min_degree(G):
    """A minimum degree ordering of a symmetric pattern (adjacency sets):
    eliminate a node of least degree, joining its neighbours, until none is
    left; ties go to the lower index."""
    n = len(G)
    adj = [set(x) for x in G]
    alive = [True] * n
    order = []
    import heapq
    heap = [(len(adj[i]), i) for i in range(n)]
    heapq.heapify(heap)
    while heap:
        d, i = heapq.heappop(heap)
        if not alive[i] or d != len(adj[i]):
            continue
        alive[i] = False
        order.append(i)
        nb = adj[i]
        for a in nb:
            adj[a].discard(i)
        nb = list(nb)
        for a in nb:
            adj[a].update(b for b in nb if b != a)
            heapq.heappush(heap, (len(adj[a]), a))
        adj[i] = set()
    return order


def _adjacency(m):
    m = m.tocsr()
    n = m.shape[0]
    return [set(int(j) for j in m.indices[m.indptr[i]:m.indptr[i + 1]] if j != i) for i in range(n)]


@bi('amd', 'symamd')
def amd(nargout, *args):
    """A fill-reducing ordering of a symmetric pattern (S + S'): minimum
    degree, eliminating a node of least degree at a time (exact degrees, not
    the approximate ones AMD keeps)."""
    nargchk(args, 1, 2, 'amd')
    if len(args) > 1 and type(args[1]) is not Struct:
        raise err('MATLAB:amd:InvalidOptions', 'The options must be a struct.', 'amd')
    m = _pattern(args[0], True)
    if m.shape[0] != m.shape[1]:
        raise err('MATLAB:amd:square', 'Matrix must be square.', 'amd')
    return _perm_out(_min_degree(_adjacency(m)))


@bi('colamd')
def colamd(nargout, *args):
    """A column ordering for a sparse LU or QR of S: minimum degree on the
    pattern of S'*S."""
    nargchk(args, 1, 2, 'colamd')
    if len(args) > 1 and not (numel(args[1]) == 0 or is_numeric(args[1])):
        raise err('MATLAB:colamd:InvalidOptions', 'The options must be a numeric vector.', 'colamd')
    m = _pattern(args[0])
    g = (m.T @ m).tocsc()
    return _perm_out(_min_degree(_adjacency(g)))


@bi('etree', nout=2)
def etree(nargout, *args):
    """[p, q] = etree(A): the elimination tree of A (its upper triangle taken
    as symmetric): p(j) is the parent of column j (0 for a root), q a
    postorder."""
    nargchk(args, 1, 2, 'etree')
    kind = 'sym'
    if len(args) > 1:
        kind = (opt_str(args[1]) or '').lower()
        if kind not in ('sym', 'col'):
            raise err('MATLAB:etree:InvalidType', "The type is 'sym' or 'col'.", 'etree')
    m = SPM.to_sparse(args[0]).m.tocsc()
    if kind == 'col':
        # the column elimination tree: the tree of A'*A
        b = m.astype(np.bool_).astype(F64)
        m = (b.T @ b).tocsc()
    n = m.shape[1]
    parent = np.full(n, -1)
    ancestor = np.full(n, -1)
    for j in range(n):
        for i in m.indices[m.indptr[j]:m.indptr[j + 1]]:
            i = int(i)
            while i != -1 and i < j:
                nxt = ancestor[i]
                ancestor[i] = j
                if nxt == -1:
                    parent[i] = j
                i = nxt
    p = out((parent + 1).astype(F64).reshape(1, -1))
    if nargout < 2:
        return p
    kids = [[] for _ in range(n)]
    roots = []
    for j in range(n):
        (kids[parent[j]] if parent[j] >= 0 else roots).append(j)
    post = []
    stack = [(r, False) for r in reversed(roots)]
    while stack:
        node, done = stack.pop()
        if done:
            post.append(node)
            continue
        stack.append((node, True))
        stack.extend((c, False) for c in reversed(kids[node]))
    return p, _perm_out(post)


def _matching(m):
    from scipy.sparse.csgraph import maximum_bipartite_matching
    return maximum_bipartite_matching(m.tocsr().astype(np.int8) if m.nnz else m.tocsr(), perm_type='row')


@bi('dmperm')
def dmperm(nargout, *args):
    """p = dmperm(A): a maximum matching, p(j) the row matched to column j (0
    for none), by scipy.sparse.csgraph.maximum_bipartite_matching."""
    nargchk(args, 1, 1, 'dmperm')
    if nargout > 1:
        raise err('MATLAB:dmperm:outputs', 'Only the matching (one output) is given here.', 'dmperm')
    m = _pattern(args[0])
    match = _matching(m)
    return out((np.asarray(match) + 1).astype(F64).reshape(1, -1))


@bi('sprank')
def sprank(nargout, *args):
    """The structural rank: the size of a maximum matching of the pattern."""
    nargchk(args, 1, 1, 'sprank')
    m = _pattern(args[0])
    return float(np.count_nonzero(np.asarray(_matching(m)) >= 0))


def _opts_of(args, k, fn, known):
    """The options struct args[k] as a dict of lower-case names (text values lower-case too)."""
    if len(args) <= k:
        return {}
    o = args[k]
    if type(o) is not Struct:
        raise err(f'MATLAB:{fn}:InvalidOptions', 'The options must be a struct.', fn)
    res = {}
    for name in o.keys:
        key = name.lower()
        if key not in known:
            raise err(f'MATLAB:{fn}:InvalidOption', f"'{name}' is not an option of {fn}.", fn)
        v = o.get1(name)
        t = opt_str(v)
        res[key] = t.lower() if t is not None else v
    return res


def _real_opt(o, key, default, fn):
    if key not in o:
        return default
    v = o[key]
    if isinstance(v, str) or numel(v) != 1 or isinstance(num(v), complex) or not float(num(v)) >= 0:
        raise err(f'MATLAB:{fn}:Invalid{key.capitalize()}', f'opts.{key} must be a real number, not negative.', fn)
    return float(num(v))


def _columns(m):
    """A CSC matrix as a list of {row: value} per column."""
    m = m.tocsc()
    return [dict(zip(m.indices[m.indptr[j]:m.indptr[j + 1]].tolist(), m.data[m.indptr[j]:m.indptr[j + 1]].tolist()))
            for j in range(m.shape[1])]


def _from_columns(cols, n, dtype):
    r, c, v = [], [], []
    for j, col in enumerate(cols):
        for i, x in col.items():
            r.append(i)
            c.append(j)
            v.append(x)
    return _sp().csc_matrix((np.array(v, dtype=dtype), (np.array(r, np.intp), np.array(c, np.intp))), shape=(n, n))


@bi('ichol')
def ichol(nargout, *args):
    """L = ichol(A, opts): the incomplete Cholesky factor, L*L' close to A
    (read from its lower triangle). opts.type 'nofill' (A's pattern) or
    'ict' (any pattern, entries below droptol*norm(A(j:end, j), 1)
    dropped), opts.michol 'on' (what is dropped added to the diagonal, so
    that L*L' keeps A's row sums), opts.diagcomp alpha (A +
    alpha*diag(diag(A)) factored), opts.shape 'upper' (L' returned)."""
    nargchk(args, 1, 2, 'ichol')
    o = _opts_of(args, 1, 'ichol', ('type', 'droptol', 'michol', 'diagcomp', 'shape'))
    kind = o.get('type', 'nofill')
    if kind not in ('nofill', 'ict'):
        raise err('MATLAB:ichol:InvalidType', "opts.type is 'nofill' or 'ict'.", 'ichol')
    droptol = _real_opt(o, 'droptol', 0.0, 'ichol')
    michol = o.get('michol', 'off')
    shape = o.get('shape', 'lower')
    if michol not in ('on', 'off') or shape not in ('lower', 'upper'):
        raise err('MATLAB:ichol:InvalidOption', "opts.michol is 'on' or 'off', opts.shape 'lower' or 'upper'.", 'ichol')
    alpha = _real_opt(o, 'diagcomp', 0.0, 'ichol')
    s = SPM.to_sparse(args[0])
    _square(s, 'ichol')
    n = s.shape[0]
    sp = _sp()
    A = sp.tril(_float_m(s)).tocsc()
    if shape == 'upper':
        A = sp.tril(_float_m(s).conj().T).tocsc()
    if alpha:
        A = (A + alpha * sp.diags(A.diagonal())).tocsc()
    cplx = A.dtype.kind == 'c'
    acols = _columns(A)
    colnorm = [sum(abs(x) for x in col.values()) for col in acols]
    Lcols = [dict() for _ in range(n)]
    lrows = [[] for _ in range(n)]          # lrows[i]: (k, L(i,k)) for the columns k < i done so far
    pend = [0.0] * n                        # what michol adds to the diagonal still to come
    for k in range(n):
        c = dict(acols[k])
        c[k] = c.get(k, 0.0) + pend[k]
        pattern = acols[k]
        for j, lkj in lrows[k]:
            ck = lkj.conjugate() if cplx else lkj
            for i, lij in Lcols[j].items():
                if i < k:
                    continue
                # on the diagonal |L(k,j)|^2, exactly real (a complex product can round its imaginary part away from 0)
                u = (lij.real * lij.real + lij.imag * lij.imag) if i == k and cplx else lij * ck
                if kind == 'ict' or i in pattern or i == k:
                    c[i] = c.get(i, 0.0) - u
                elif michol == 'on':
                    # the fill at (i, k) is not kept: its update goes to both diagonals
                    c[k] -= u
                    pend[i] -= u
        if kind == 'ict' and droptol > 0:
            tol = droptol * colnorm[k]
            for i in [i for i, x in c.items() if i != k and abs(x) < tol]:
                x = c.pop(i)
                if michol == 'on':
                    c[k] += x
                    pend[i] += x
        p = c.get(k, 0.0)
        if cplx and isinstance(p, complex) and p.imag != 0:
            raise err('MATLAB:ichol:NonRealPivot', 'Encountered a pivot that is not real.', 'ichol')
        p = p.real if isinstance(p, complex) else p
        if not p > 0:
            raise err('MATLAB:ichol:Breakdown', 'Encountered nonpositive pivot.', 'ichol')
        d = math.sqrt(p)
        col = {k: d}
        for i, x in c.items():
            if i != k and x != 0:
                col[i] = x / d
                lrows[i].append((k, col[i]))
        Lcols[k] = col
    L = _from_columns(Lcols, n, C128 if cplx else F64)
    return SPM.make(L.conj().T if shape == 'upper' else L)


def py_str_(v):
    from ..values import py_str
    return py_str(v)


def _ilu_columns(A, kind, droptol, thresh, milu, udiag):
    """Incomplete LU column by column (left-looking): column j is solved
    against the columns of L so far, its small entries dropped (droptol times
    norm(A(:, j)); for 'nofill' those outside A's pattern), with 'col' what
    is dropped added to the pivot, and for 'ilutp' the pivot taken from the
    rows not yet used: row j unless another is larger than it by more than
    1/thresh. Returns the columns of L (by original row), of U (by step), and
    the row chosen at each step."""
    import heapq
    n = A.shape[0]
    acols = _columns(A)
    Lcols = [None] * n
    Ucols = [None] * n
    pivrow = [-1] * n
    step_of = {}                              # original row -> the step it was the pivot of
    for j in range(n):
        x = dict(acols[j])
        pattern = acols[j]
        tol = droptol * math.sqrt(sum(abs(v) ** 2 for v in acols[j].values()))
        dropped = 0.0
        heap = [step_of[i] for i in x if i in step_of]
        heapq.heapify(heap)
        seen = set(heap)
        u = {}
        while heap:
            k = heapq.heappop(heap)
            ukj = x.pop(pivrow[k], 0.0)
            if ukj == 0:
                continue
            if droptol > 0 and abs(ukj) < tol:
                dropped += ukj              # dropped before it is used, so that L*U misses only this value
                continue
            u[k] = ukj
            for i, lik in Lcols[k].items():
                d = lik * ukj
                if kind == 'nofill' and i not in pattern:
                    dropped -= d
                    continue
                x[i] = x.get(i, 0.0) - d
                kk = step_of.get(i)
                if kk is not None and kk not in seen:
                    seen.add(kk)
                    heapq.heappush(heap, kk)
        # the candidates for the pivot: rows not used yet
        cand = {i: v for i, v in x.items() if i not in step_of}
        if kind == 'ilutp' and cand:
            big = max(cand, key=lambda i: (abs(cand[i]), -i))
            p = j if (j in cand and j not in step_of and abs(cand[j]) >= thresh * abs(cand[big])) else big
            if j not in cand and abs(cand[big]) == 0:
                p = j if j not in step_of else big
        else:
            p = j
        if droptol > 0:
            for i in [i for i, v in cand.items() if i != p and abs(v) < tol]:
                dropped += cand.pop(i)
        piv = cand.pop(p, 0.0)
        if milu == 'col':
            piv += dropped
        if piv == 0:
            if udiag:
                piv = tol if tol else 0.0
            if piv == 0:
                raise err('MATLAB:ilu:ZeroPivot', 'Encountered a zero pivot.', 'ilu')
        u[j] = piv
        pivrow[j] = p
        step_of[p] = j
        Lcols[j] = {i: v / piv for i, v in cand.items() if v != 0}
        Ucols[j] = u
    return Lcols, Ucols, pivrow


@bi('ilu', nout=3)
def ilu(nargout, *args):
    """[L, U, P] = ilu(A, opts): incomplete LU factors, L unit lower and U
    upper with L*U close to P*A. opts.type 'nofill' (A's pattern, the
    default), 'crout' (no pivoting) or 'ilutp' (threshold pivoting,
    opts.thresh, 1 by default), opts.droptol (0), opts.milu 'row', 'col'
    or 'off', opts.udiag (a zero pivot replaced by the drop tolerance). With
    two outputs L carries P's rows; with one, L + U - I."""
    nargchk(args, 1, 2, 'ilu')
    o = _opts_of(args, 1, 'ilu', ('type', 'droptol', 'milu', 'udiag', 'thresh'))
    kind = o.get('type', 'nofill')
    if kind not in ('nofill', 'crout', 'ilutp'):
        raise err('MATLAB:ilu:InvalidType', "opts.type is 'nofill', 'crout' or 'ilutp'.", 'ilu')
    droptol = _real_opt(o, 'droptol', 0.0, 'ilu') if kind != 'nofill' else 0.0
    thresh = _real_opt(o, 'thresh', 1.0, 'ilu')
    if thresh > 1:
        raise err('MATLAB:ilu:InvalidThresh', 'opts.thresh must be from 0 to 1.', 'ilu')
    milu = o.get('milu', 'off')
    if milu not in ('row', 'col', 'off'):
        raise err('MATLAB:ilu:InvalidMilu', "opts.milu is 'row', 'col' or 'off'.", 'ilu')
    if milu == 'row' and kind == 'ilutp':
        raise err('MATLAB:ilu:MiluRow', "opts.milu 'row' is computed with type 'nofill' or 'crout'.", 'ilu')
    udiag = bool(num(o['udiag'])) if 'udiag' in o and not isinstance(o['udiag'], str) else False
    if type(args[0]) is not Sparse:
        raise err('MATLAB:ilu:NotSparse', 'A must be a sparse square matrix.', 'ilu')
    s = args[0]
    _square(s, 'ilu')
    n = s.shape[0]
    sp = _sp()
    if n == 0:
        e = SPM.zeros(0, 0)
        return e if nargout <= 1 else (e, e, e)[:nargout]
    m = _float_m(s).tocsc()
    cplx = m.dtype.kind == 'c'
    dt = C128 if cplx else F64
    if milu == 'row':
        # the row sums kept: the column version on A.', its factors turned back
        Lc, Uc, piv = _ilu_columns(m.T.tocsc(), kind, droptol, thresh, 'col', udiag)
        Lt = _from_columns(Lc, n, dt) + sp.identity(n, dtype=dt, format='csc')
        Ut = _from_columns(Uc, n, dt)
        D = Ut.diagonal()
        L = (Ut.T @ sp.diags(1 / D)).tocsc()
        U = (sp.diags(D) @ Lt.T).tocsc()
        perm = np.arange(n)
    else:
        Lc, Uc, piv = _ilu_columns(m, kind, droptol, thresh, milu, udiag)
        perm = np.asarray(piv)
        Lo = _from_columns(Lc, n, dt)               # rows by original index
        U = _from_columns(Uc, n, dt)
        # row i of L belongs at the step whose pivot it is: P*A = L*U with P(k, perm(k)) = 1
        step = np.empty(n, np.intp)
        step[perm] = np.arange(n)
        L = (sp.csc_matrix((np.ones(n), (step, np.arange(n))), shape=(n, n)) @ Lo).tocsc() + sp.identity(n, dtype=dt, format='csc')
    P = sp.csc_matrix((np.ones(n), (np.arange(n), perm)), shape=(n, n))
    if nargout <= 1:
        return SPM.make(L - sp.identity(n, format='csc') + U)
    if nargout == 2:
        return SPM.make(P.T @ L), SPM.make(U)
    return SPM.make(L), SPM.make(U), SPM.make(P)


@bi('spaugment')
def spaugment(nargout, *args):
    """[c*I A; A' 0]: the augmented system of a least-squares problem, c the
    second input (max(max(abs(A)))/1000 unless given)."""
    nargchk(args, 1, 2, 'spaugment')
    s = SPM.to_sparse(args[0])
    m = _float_m(s)
    c = float(num(args[1])) if len(args) > 1 else (float(abs(m).max()) / 1000 if m.nnz else 1.0)
    sp = _sp()
    r, k = m.shape
    return SPM.make(sp.bmat([[c * sp.identity(r), m], [m.T, None]], format='csc'))


_SPPARMS_KEYS = ['spumoni', 'thr_rel', 'thr_abs', 'exact_d', 'supernd', 'rreduce', 'wh_frac', 'autommd', 'autoamd', 'piv_tol',
                 'bandden', 'umfpack', 'sym_tol', 'ldl_tol', 'cholmod']
_SPPARMS_DEFAULT = [0, 1.1, 1, 0, 3, 3, 0.5, 1, 1, 0.1, 0.5, 1, 0.001, 0.01, 1]
_SPPARMS = list(_SPPARMS_DEFAULT)


@bi('spparms', nout=2)
def spparms(nargout, *args):
    """The sparse solvers' settings, kept and read back: SciPy's SuperLU and
    ARPACK are called with their own, so the settings change nothing."""
    nargchk(args, 0, 2, 'spparms')
    keys = _SPPARMS_KEYS
    if not args:
        if nargout >= 2:
            return Char.rows(keys), out(np.array(_SPPARMS, F64).reshape(-1, 1))
        if nargout == 1:
            return out(np.array(_SPPARMS, F64).reshape(-1, 1))
        from .. import runtime as R
        R.write(''.join(f'{k:>8}: {v:g}\n' for k, v in zip(keys, _SPPARMS)))
        return None
    key = opt_str(args[0])
    if len(args) == 1:
        if key is not None:
            k = key.lower()
            if k == 'default':
                _SPPARMS[:] = _SPPARMS_DEFAULT
                return None
            if k == 'tight':
                return None
            if k not in keys:
                raise err('MATLAB:spparms:UnknownKey', f"'{key}' is not a setting of spparms.", 'spparms')
            return float(_SPPARMS[keys.index(k)])
        if not is_numeric(args[0]):
            raise err('MATLAB:spparms:InvalidInput', 'The input is a setting name or a vector of values.', 'spparms')
        vals = np.asarray(darr(args[0]), F64).reshape(-1)
        if vals.size > len(keys):
            raise err('MATLAB:spparms:TooManyValues', f'There are {len(keys)} settings, so at most {len(keys)} values.', 'spparms')
        _SPPARMS[:vals.size] = [float(v) for v in vals]
        return None
    if key is None:
        raise err('MATLAB:spparms:InvalidKey', 'The first input must be a setting name.', 'spparms')
    if key.lower() not in keys:
        raise err('MATLAB:spparms:UnknownKey', f"'{key}' is not a setting of spparms.", 'spparms')
    if not is_numeric(args[1]) or numel(args[1]) != 1:
        raise err('MATLAB:spparms:InvalidValue', 'The value must be a number.', 'spparms')
    _SPPARMS[keys.index(key.lower())] = float(num(args[1]))
    return None


def _like_sparse(fn):
    """zeros, ones, eye, true and false with 'like' and a sparse value: the
    result sparse, made by the full function."""
    def f(nargout, *args):
        if len(args) >= 2 and type(args[-1]) is Sparse and (opt_str(args[-2]) or '').lower() == 'like':
            proto = args[-1]
            r = fn(nargout, *args[:-1], out(np.zeros((0, 0), np.bool_ if proto.m.dtype == np.bool_ else proto.m.dtype)))
            if numel(r) and len(shape_of(r)) > 2:
                raise err('MATLAB:sparse:NDArray', 'Sparse matrices are 2-D.', 'zeros')
            return SPM.to_sparse(r if type(r) is not bool else out(np.array([[r]])))
        return fn(nargout, *args)
    return f


def _like_logical(fn):
    """true and false with 'like' and a logical value."""
    def f(nargout, *args):
        if len(args) >= 2 and (opt_str(args[-2]) or '').lower() == 'like':
            proto = args[-1]
            if class_of(proto) != 'logical':
                raise err('MATLAB:true:likeClass', "'like' needs a logical value here.", 'true')
            r = fn(nargout, *args[:-2]) if len(args) > 2 else fn(nargout, 1.0)
            if type(proto) is Sparse:
                if len(shape_of(r)) > 2:
                    raise err('MATLAB:sparse:NDArray', 'Sparse matrices are 2-D.', 'true')
                return SPM.to_sparse(r if type(r) is not bool else out(np.array([[r]])))
            return r
        return fn(nargout, *args)
    return f


for _n in ('zeros', 'ones', 'eye'):
    _rewrap(_n, _like_sparse)
for _n in ('true', 'false'):
    _rewrap(_n, _like_logical)


@bi('spy', arr=False)
def spy(nargout, *args):
    """spy(S): a marker at each nonzero, row down and column across (axis ij),
    and nz = the count under the axes."""
    nargchk(args, 1, 3, 'spy')
    s = SPM.to_sparse(args[0])
    coo = s.m.tocoo()
    from .. import runtime as R
    from .graphics import newplot
    rest = list(args[1:])
    spec = Char.of('.')
    size = None
    for a in rest:
        if opt_str(a) is not None:
            spec = a
        else:
            size = float(num(a))
    newplot(None)
    pairs = [Char.of('MarkerSize'), size] if size is not None else []
    h = R.BUILTINS['plot'].fn(1, out(coo.col.astype(F64).reshape(-1, 1) + 1), out(coo.row.astype(F64).reshape(-1, 1) + 1), spec, *pairs)
    r, c = s.shape
    R.BUILTINS['axis'].fn(0, out(np.array([[0.0, c + 1.0, 0.0, r + 1.0]])))
    R.BUILTINS['axis'].fn(0, Char.of('ij'))
    R.BUILTINS['xlabel'].fn(0, Char.of(f'nz = {s.nnz}'))
    return h if nargout else None
