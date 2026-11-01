"""Making and reshaping arrays: zeros, ones, rand, linspace, repmat,
reshape, meshgrid, find, flips and permutations, class conversions."""
import math
import numpy as np

from . import bi
from ._util import (err, nargchk, noout, maxout, arr, darr, out, opt_str, sval, ival, num, is_str, dims_from,
                    np_dtype, make, first_dim, dim_arg, bool_out, NUMERIC_CLASSES, strip_flags, like_class)
from ..values import (MError, NOVAL, COLON, Char, Cell, Struct, Str, FH, Obj, F64, C128, INT_TYPES, INT_RANGE,
                      DTYPE_CLASS, class_of, shape_of, numel, py_str, share, share_all, EMPTY, _2d, scalar_out)
from ..ops import finish, to_int_class, INT_CLASSES, colon as _colon, cat as _cat
from .. import runtime as R


# ---- filled arrays -------------------------------------------------------------------

def _filled(args, value, fn):
    shape, klass, cplx = dims_from(args, fn)
    a = np.full(shape, value, np_dtype(klass, cplx))
    return make(a, klass)


@bi('zeros')
def zeros(nargout, *args):
    return _filled(args, 0, 'zeros')


@bi('ones')
def ones(nargout, *args):
    return _filled(args, 1, 'ones')


@bi('Inf', 'inf')
def inf_(nargout, *args):
    if not args:
        return math.inf
    return _filled(args, math.inf, 'Inf')


@bi('NaN', 'nan')
def nan_(nargout, *args):
    if not args:
        return math.nan
    return _filled(args, math.nan, 'NaN')


@bi('pi')
def pi(nargout, *args):
    if not args:
        return math.pi
    return _filled(args, math.pi, 'pi')


@bi('true')
def true_(nargout, *args):
    if not args:
        return True
    shape, _, _ = dims_from(args, 'true', allow_class=False)
    return out(np.ones(shape, bool))


@bi('false')
def false_(nargout, *args):
    if not args:
        return False
    shape, _, _ = dims_from(args, 'false', allow_class=False)
    return out(np.zeros(shape, bool))


@bi('i', 'j')
def imag_unit(nargout, *args):
    return complex(0, 1)


@bi('eps')
def eps(nargout, *args):
    if not args:
        return float(np.finfo(float).eps)
    s = opt_str(args[0])
    if s is not None:
        return float(np.finfo(np.float32 if s == 'single' else float).eps) if s != 'single' else finish(np.array([[np.finfo(np.float32).eps]], np.float32), 'single')
    a = arr(args[0])
    if a.dtype == np.float32:
        return finish(np.spacing(np.abs(a)).astype(np.float32), 'single')
    with np.errstate(all='ignore'):
        r = np.spacing(np.abs(a.astype(F64)))
        r = np.where(np.isfinite(a), r, np.nan)
    return out(r)


@bi('realmax')
def realmax(nargout, *args):
    if args and opt_str(args[0]) == 'single':
        return finish(np.array([[np.finfo(np.float32).max]], np.float32), 'single')
    return float(np.finfo(float).max)


@bi('realmin')
def realmin(nargout, *args):
    if args and opt_str(args[0]) == 'single':
        return finish(np.array([[np.finfo(np.float32).tiny]], np.float32), 'single')
    return float(np.finfo(float).tiny)


@bi('flintmax')
def flintmax(nargout, *args):
    if args and opt_str(args[0]) == 'single':
        return finish(np.array([[2.0 ** 24]], np.float32), 'single')
    return 2.0 ** 53


@bi('intmax')
def intmax(nargout, *args):
    c = opt_str(args[0]) if args else 'int32'
    if c not in INT_TYPES:
        raise err('MATLAB:intmax:invalidClassName', 'Invalid class name.', 'intmax')
    return np.array([[INT_RANGE[c][1]]], INT_TYPES[c])


@bi('intmin')
def intmin(nargout, *args):
    c = opt_str(args[0]) if args else 'int32'
    if c not in INT_TYPES:
        raise err('MATLAB:intmin:invalidClassName', 'Invalid class name.', 'intmin')
    return np.array([[INT_RANGE[c][0]]], INT_TYPES[c])


@bi('eye')
def eye(nargout, *args):
    shape, klass, cplx = dims_from(args, 'eye')
    if len(shape) > 2:
        raise err('MATLAB:eye:tooManyDims', 'N-dimensional arrays are not supported.', 'eye')
    return make(np.eye(shape[0], shape[1], dtype=np_dtype(klass, cplx)), klass)


# ---- random numbers -----------------------------------------------------------------------

class _RNG:
    def __init__(self):
        self.seed(0)

    def seed(self, s):
        self.s = int(s)
        # seed 0 is the generator's default state
        self.rs = np.random.RandomState(5489 if self.s == 0 else self.s)
        self.kind = 'twister'

    def uniform(self, shape):
        n = int(np.prod(shape)) if shape else 1
        v = self.rs.random_sample(n)
        return v.reshape(shape, order='F')


RNG = _RNG()


def rng_impl(nargout, *args):
    prev = Struct.scalar({'Type': Char.of('twister'), 'Seed': float(RNG.s), 'State': np.array([[0.0]])})
    if not args:
        return prev
    a = args[0]
    s = opt_str(a)
    if type(a) is Struct:
        RNG.seed(int(num(a.get1('Seed'))))
        RNG.rs.set_state(a.get1('_state')) if '_state' in a.f else None
        return prev if nargout else None
    if s is not None:
        if s == 'default':
            RNG.seed(0)
        elif s == 'shuffle':
            import time
            RNG.seed(int(time.time() * 1000) % (2 ** 32))
        else:
            raise err('MATLAB:rng:badFirstOpt', f"Unknown option '{s}'.", 'rng')
    else:
        x = num(a)
        if x < 0 or x != int(x) or x >= 2 ** 32:
            raise err('MATLAB:rng:badSeed', 'The seed must be a nonnegative integer less than 2^32.', 'rng')
        RNG.seed(int(x))
    return prev if nargout else None


def _rand_args(args, fn):
    args = list(args)
    if args and opt_str(args[0]) in ('twister', 'seed', 'state', 'v4', 'v5uniform', 'v5normal'):
        RNG.seed(int(num(args[1])) if len(args) > 1 else 0)
        return None
    return dims_from(args, fn)


@bi('rand')
def rand(nargout, *args):
    r = _rand_args(args, 'rand')
    if r is None:
        return None
    shape, klass, _ = r
    a = RNG.uniform(shape)
    if klass == 'single':
        return finish(a.astype(np.float32), 'single')
    return out(a)


@bi('randn')
def randn(nargout, *args):
    r = _rand_args(args, 'randn')
    if r is None:
        return None
    shape, klass, cplx = r
    n = int(np.prod(shape))
    a = RNG.rs.standard_normal(n).reshape(shape, order='F')
    if cplx:
        a = a + 1j * RNG.rs.standard_normal(n).reshape(shape, order='F')
    if klass == 'single':
        return finish(a.astype(np.float32), 'single')
    return out(a)


@bi('randi')
def randi(nargout, *args):
    nargchk(args, 1, None, 'randi')
    lim = arr(args[0]).reshape(-1)
    if lim.size == 1:
        lo, hi = 1, int(lim[0])
    else:
        lo, hi = int(lim[0]), int(lim[1])
    if hi < lo:
        raise err('MATLAB:randi:invalidLimits', 'The first input must be a positive scalar integer value IMAX, or a 2-element vector [IMIN IMAX] of integer values with IMIN less than or equal to IMAX.' if True else '', 'randi')
    shape, klass, _ = dims_from(args[1:], 'randi')
    u = RNG.uniform(shape)
    a = np.floor(u * (hi - lo + 1)) + lo
    return make(a, klass) if klass != 'double' else out(a)


@bi('randperm')
def randperm(nargout, *args):
    nargchk(args, 1, 2, 'randperm')
    n = ival(args[0], 'n', 'randperm')
    k = ival(args[1], 'k', 'randperm') if len(args) > 1 else n
    if k > n:
        raise err('MATLAB:randperm:inputKTooLarge', 'K must be less than or equal to N.', 'randperm')
    u = RNG.uniform((1, n))
    p = np.argsort(u.reshape(-1), kind='stable')[:k] + 1
    return out(p.astype(F64).reshape(1, -1))


# ---- ranges ---------------------------------------------------------------------------

@bi('linspace')
def linspace(nargout, *args):
    nargchk(args, 2, 3, 'linspace')
    a = num(args[0]) if type(args[0]) is not complex else args[0]
    b = num(args[1]) if type(args[1]) is not complex else args[1]
    n = 100 if len(args) < 3 else num(args[2])
    n = int(math.floor(n)) if n == n else 0
    if n < 1:
        return np.zeros((1, 0))
    if n == 1:
        return b if type(b) is float else out(np.array([[b]]))
    k = np.arange(n, dtype=F64)
    r = a + k * (b - a) / (n - 1)
    r[-1] = b
    return out(r.reshape(1, -1))


@bi('logspace')
def logspace(nargout, *args):
    nargchk(args, 2, 3, 'logspace')
    a = num(args[0])
    b = num(args[1])
    n = int(num(args[2])) if len(args) > 2 else 50
    if b == math.pi:
        b = math.log10(math.pi)
    k = np.arange(n, dtype=F64)
    e = a + k * (b - a) / (n - 1) if n > 1 else np.array([b])
    return out((10.0 ** e).reshape(1, -1))


@bi('colon')
def colon_fn(nargout, *args):
    nargchk(args, 2, 3, 'colon')
    return _colon(*args)


# ---- shape -------------------------------------------------------------------------------

def _apply_obj(v, fn):
    """Apply a numpy reshaping function to any array-like value."""
    t = type(v)
    if t is float or t is bool or t is complex:
        return out(fn(np.array([[v]])))
    if t is np.ndarray:
        r = fn(v)
        return out(r) if r.dtype.kind in 'fbc' and r.dtype in (np.dtype(F64), np.dtype(bool), np.dtype(C128)) else _2d(r)
    if t is Char:
        return Char(_2d(fn(v.a)))
    if t is Cell:
        r = _2d(fn(v.a))
        r = r.copy()
        share_all(r)
        return Cell(r)
    if t is Str:
        return Str(_2d(fn(v.a)))
    if t is Struct:
        pos = np.arange(v.size).reshape(v.shape, order='F')
        sel = _2d(fn(pos))
        f = {}
        for k, a in v.f.items():
            flat = a.reshape(-1, order='F')
            r = flat[sel.reshape(-1, order='F')].reshape(sel.shape, order='F')
            share_all(r)
            f[k] = r
        return Struct(sel.shape, f)
    if isinstance(v, Obj) and hasattr(v, 'a'):
        from ..graphics_base import HArr
        return HArr(_2d(fn(v.a)))
    raise err('MATLAB:invalidType', f'This function does not support values of class {class_of(v)}.')


@bi('reshape')
def reshape(nargout, *args):
    nargchk(args, 2, None, 'reshape')
    v = args[0]
    n = numel(v)
    if len(args) == 2:
        dims = [int(x) for x in arr(args[1]).reshape(-1)]
    else:
        dims = []
        empty_at = None
        for k, a in enumerate(args[1:]):
            if type(a) is np.ndarray and a.size == 0:
                if empty_at is not None:
                    raise err('MATLAB:getReshapeDims:unknownDim', 'Size can only have one unknown dimension.', 'reshape')
                empty_at = k
                dims.append(-1)
            else:
                dims.append(int(num(a)))
        if empty_at is not None:
            p = 1
            for d in dims:
                if d != -1:
                    p *= d
            if p == 0 or n % p:
                raise err('MATLAB:getReshapeDims:notDivisible', f'Product of known dimensions, {p}, not divisible into total number of elements, {n}.', 'reshape')
            dims[empty_at] = n // p
    p = 1
    for d in dims:
        p *= d
    if p != n:
        raise err('MATLAB:getReshapeDims:notSameNumel', 'Number of elements must not change. Use [] as one of the size inputs to automatically calculate the appropriate size for that dimension.', 'reshape')
    if len(dims) < 2:
        dims = dims + [1]
    while len(dims) > 2 and dims[-1] == 1:
        dims.pop()
    return _apply_obj(v, lambda a: a.reshape(dims, order='F'))


@bi('squeeze')
def squeeze(nargout, *args):
    nargchk(args, 1, 1, 'squeeze')
    v = args[0]
    sh = shape_of(v)
    if len(sh) <= 2:
        return v
    dims = [d for d in sh if d != 1]
    if len(dims) == 0:
        dims = [1, 1]
    elif len(dims) == 1:
        dims = [dims[0], 1]
    return _apply_obj(v, lambda a: a.reshape(dims, order='F'))


@bi('permute')
def permute(nargout, *args):
    nargchk(args, 2, 2, 'permute')
    order = [int(x) - 1 for x in arr(args[1]).reshape(-1)]
    v = args[0]
    nd = len(shape_of(v))
    if sorted(order) != list(range(len(order))) or len(order) < nd:
        raise err('MATLAB:permute:badIndex', 'ORDER must have at least N elements for an N-D array.' if len(order) < nd else 'ORDER contains an invalid permutation index.', 'permute')

    def f(a):
        a2 = a.reshape(a.shape + (1,) * (len(order) - a.ndim)) if a.ndim < len(order) else a
        return np.transpose(a2, order).copy()
    return _apply_obj(v, f)


@bi('ipermute')
def ipermute(nargout, *args):
    order = [int(x) - 1 for x in arr(args[1]).reshape(-1)]
    inv = np.argsort(order) + 1
    return permute(nargout, args[0], np.array([inv], F64))


@bi('repmat')
def repmat(nargout, *args):
    nargchk(args, 2, None, 'repmat')
    v = args[0]
    if len(args) == 2:
        r = arr(args[1]).reshape(-1)
        reps = [int(x) for x in r] if r.size > 1 else [int(r[0]), int(r[0])]
    else:
        reps = [int(num(a)) for a in args[1:]]
    reps = [max(0, x) for x in reps]

    def f(a):
        nd = max(a.ndim, len(reps))
        a2 = a.reshape(a.shape + (1,) * (nd - a.ndim))
        rr = reps + [1] * (nd - len(reps))
        return np.tile(a2, rr)
    return _apply_obj(v, f)


@bi('cat')
def cat(nargout, *args):
    nargchk(args, 1, None, 'cat')
    d = ival(args[0], 'dimension', 'cat')
    vals = list(args[1:])
    if d <= 2:
        return _cat(d - 1, vals)
    # along a higher dimension
    vals = [v for v in vals if not (type(v) is np.ndarray and v.shape == (0, 0))]
    if not vals:
        return EMPTY()
    if all(type(v) in (float, bool, complex, np.ndarray, Char) for v in vals):
        from ..ops import _num_cat_class, _as_np
        klass = _num_cat_class(vals)
        arrs = []
        for v in vals:
            a = _as_np(v)
            a = a.reshape(a.shape + (1,) * (d - a.ndim)) if a.ndim < d else a
            arrs.append(a)
        base = arrs[0].shape[:d - 1]
        for a in arrs:
            if a.shape[:d - 1] != base:
                raise err('MATLAB:catenate:dimensionMismatch', 'Dimensions of arrays being concatenated are not consistent.', 'cat')
        r = np.concatenate([a.astype(np_dtype(klass if klass != 'char' else 'char', any(x.dtype.kind == 'c' for x in arrs))) for a in arrs], axis=d - 1)
        return make(r, klass)
    if all(type(v) is Cell for v in vals):
        arrs = [v.a.reshape(v.a.shape + (1,) * (d - v.a.ndim)) for v in vals]
        r = np.concatenate(arrs, axis=d - 1)
        share_all(r)
        return Cell(_2d(r))
    raise err('MATLAB:catenate:invalidType', 'These values cannot be concatenated along that dimension.', 'cat')


@bi('horzcat')
def horzcat(nargout, *args):
    return _cat(1, list(args)) if args else EMPTY()


@bi('vertcat')
def vertcat(nargout, *args):
    return _cat(0, list(args)) if args else EMPTY()


@bi('diag')
def diag(nargout, *args):
    nargchk(args, 1, 2, 'diag')
    v = args[0]
    k = ival(args[1], 'k', 'diag') if len(args) > 1 else 0
    a = arr(v)
    if a.ndim > 2:
        raise err('MATLAB:diag:firstInputMustBe2D', 'First input must be 2-D.', 'diag')
    if a.shape[0] == 1 or a.shape[1] == 1:
        r = np.diag(a.reshape(-1), k)
    else:
        r = np.diag(a, k).reshape(-1, 1).copy()
    return like_class(r, v) if type(v) is not Char else Char(_2d(r))


@bi('magic')
def magic(nargout, *args):
    nargchk(args, 1, 1, 'magic')
    n = ival(args[0], 'n', 'magic')
    if n < 1:
        return EMPTY()
    if n == 1:
        return 1.0
    if n == 2:
        return np.array([[4.0, 3.0], [1.0, 2.0]])
    if n % 2 == 1:
        # the siamese method: start in the middle of the top row
        J, I = np.meshgrid(np.arange(1, n + 1), np.arange(1, n + 1))
        A = np.mod(I + J - (n + 3) // 2, n)
        Bm = np.mod(I + 2 * J - 2, n)
        M = n * A + Bm + 1
        return M.astype(F64)
    if n % 4 == 0:
        J, I = np.meshgrid(np.arange(1, n + 1), np.arange(1, n + 1))
        K = (np.mod(I, 4) // 2) == (np.mod(J, 4) // 2)
        M = np.arange(1, n * n + 1).reshape(n, n).astype(F64)
        M[K] = n * n + 1 - M[K]
        return M
    # singly even: LUX-style construction from four odd squares
    p = n // 2
    Mp = magic(1, float(p))
    M = np.block([[Mp, Mp + 2 * p * p], [Mp + 3 * p * p, Mp + p * p]])
    i = np.arange(p)
    k = (n - 2) // 4
    j = list(range(k)) + list(range(n - k + 1, n))
    for col in j:
        tmp = M[i, col].copy()
        M[i, col] = M[i + p, col]
        M[i + p, col] = tmp
    for col in (0, k):
        r = k
        tmp = M[r, col]
        M[r, col] = M[r + p, col]
        M[r + p, col] = tmp
    return M.astype(F64)


@bi('meshgrid', nout=3)
def meshgrid(nargout, *args):
    nargchk(args, 1, 3, 'meshgrid')
    x = arr(args[0]).reshape(-1)
    y = arr(args[1]).reshape(-1) if len(args) > 1 else x
    if len(args) == 3 or nargout == 3:
        z = arr(args[2]).reshape(-1) if len(args) > 2 else x
        X, Y, Z = np.meshgrid(x, y, z)
        res = (out(X.astype(F64) if X.dtype.kind not in 'fc' else X), out(Y.astype(F64) if Y.dtype.kind not in 'fc' else Y), out(Z.astype(F64) if Z.dtype.kind not in 'fc' else Z))
        return res[:max(nargout, 1)] if nargout > 1 else res[0]
    X, Y = np.meshgrid(x, y)
    X = X.astype(F64) if X.dtype.kind not in 'fc' else X
    Y = Y.astype(F64) if Y.dtype.kind not in 'fc' else Y
    if nargout <= 1:
        return out(X)
    return out(X), out(Y)


@bi('ndgrid', nout=99)
def ndgrid(nargout, *args):
    nargchk(args, 1, None, 'ndgrid')
    vecs = [arr(a).reshape(-1).astype(F64) if arr(a).dtype.kind != 'c' else arr(a).reshape(-1) for a in args]
    n = max(nargout, 1)
    if len(vecs) == 1:
        vecs = vecs * max(n, 2)
    grids = np.meshgrid(*vecs[:max(n, len(vecs))], indexing='ij')
    if n == 1:
        return out(grids[0])
    return tuple(out(g) for g in grids[:n])


@bi('sub2ind')
def sub2ind(nargout, *args):
    nargchk(args, 2, None, 'sub2ind')
    sz = [int(x) for x in arr(args[0]).reshape(-1)]
    subs = [arr(a).astype(F64) for a in args[1:]]
    shape = subs[0].shape
    for s in subs:
        if s.shape != shape:
            raise err('MATLAB:sub2ind:SubscriptVectorSize', 'The subscript vectors must all be of the same size.', 'sub2ind')
    nd = len(subs)
    if nd < len(sz):
        p = 1
        for d in sz[nd - 1:]:
            p *= d
        sz = sz[:nd - 1] + [p]
    sz = sz + [1] * (nd - len(sz))
    idx = np.zeros(shape)
    mult = 1
    for k in range(nd):
        s = subs[k]
        if np.any(s < 1) or np.any(s > sz[k]) or np.any(s != np.floor(s)):
            raise err('MATLAB:sub2ind:IndexOutOfRange', 'Index exceeds array dimensions.', 'sub2ind')
        idx = idx + (s - 1) * mult
        mult *= sz[k]
    return out(idx + 1)


@bi('ind2sub', nout=99)
def ind2sub(nargout, *args):
    nargchk(args, 2, 2, 'ind2sub')
    sz = [int(x) for x in arr(args[0]).reshape(-1)]
    ind = arr(args[1]).astype(F64)
    n = max(nargout, 1)
    total = 1
    for d in sz:
        total *= d
    if np.any(ind < 1) or np.any(ind > total):
        raise err('MATLAB:ind2sub:IndexOutOfRange', 'Index exceeds number of array elements.', 'ind2sub')
    if n < len(sz):
        p = 1
        for d in sz[n - 1:]:
            p *= d
        sz = sz[:n - 1] + [p]
    sz = sz + [1] * (n - len(sz))
    k = (ind - 1).astype(np.int64)
    outs = []
    for d in sz[:n]:
        outs.append(out((k % d + 1).astype(F64)))
        k = k // d
    return outs[0] if n == 1 else tuple(outs)


@bi('find', nout=3)
def find(nargout, *args):
    nargchk(args, 1, 3, 'find')
    v = args[0]
    a = arr(v)
    k = None
    direction = 'first'
    if len(args) > 1:
        k = ival(args[1], 'k', 'find')
    if len(args) > 2:
        direction = sval(args[2], 'direction', 'find').lower()
    flat = a.reshape(-1, order='F')
    nz = np.flatnonzero(flat != 0)
    if k is not None:
        nz = nz[:k] if direction == 'first' else nz[-k:] if k > 0 else nz[:0]
    rowvec = a.ndim == 2 and a.shape[0] == 1 and a.shape[1] != 1
    if nargout <= 1:
        r = (nz + 1).astype(F64)
        if rowvec:
            r = r.reshape(1, -1)
        else:
            r = r.reshape(-1, 1)
        if a.shape == (0, 0) or (a.size == 0 and False):
            return np.zeros((0, 0))
        return out(r)
    rows = a.shape[0] if a.ndim >= 1 else 1
    r = (nz % rows + 1).astype(F64)
    c = (nz // rows + 1).astype(F64)
    shape = (1, -1) if rowvec else (-1, 1)
    res = [out(r.reshape(shape)), out(c.reshape(shape))]
    if nargout >= 3:
        vals = flat[nz]
        res.append(like_class(vals.reshape(shape), v) if type(v) is not Char else out(vals.reshape(shape).astype(F64)))
    return tuple(res[:nargout])


@bi('nnz')
def nnz(nargout, *args):
    nargchk(args, 1, 1, 'nnz')
    return float(np.count_nonzero(arr(args[0])))


@bi('nonzeros')
def nonzeros(nargout, *args):
    a = arr(args[0])
    flat = a.reshape(-1, order='F')
    return like_class(flat[flat != 0].reshape(-1, 1), args[0])


@bi('fliplr')
def fliplr(nargout, *args):
    nargchk(args, 1, 1, 'fliplr')
    return _apply_obj(args[0], lambda a: a[:, ::-1].copy())


@bi('flipud')
def flipud(nargout, *args):
    nargchk(args, 1, 1, 'flipud')
    return _apply_obj(args[0], lambda a: a[::-1].copy())


@bi('flip')
def flip(nargout, *args):
    nargchk(args, 1, 2, 'flip')
    v = args[0]
    if len(args) > 1:
        d = ival(args[1], 'dimension', 'flip') - 1
    else:
        d = first_dim(shape_of(v))

    def f(a):
        if d >= a.ndim:
            return a.copy()
        return np.flip(a, d).copy()
    return _apply_obj(v, f)


@bi('rot90')
def rot90(nargout, *args):
    nargchk(args, 1, 2, 'rot90')
    k = ival(args[1], 'k', 'rot90') if len(args) > 1 else 1
    return _apply_obj(args[0], lambda a: np.rot90(a, k).copy())


@bi('circshift')
def circshift(nargout, *args):
    nargchk(args, 2, 3, 'circshift')
    v = args[0]
    sh = [int(x) for x in arr(args[1]).reshape(-1)]
    if len(args) > 2:
        d = ival(args[2], 'dimension', 'circshift') - 1
        shifts, axes = [sh[0]], [d]
    elif len(sh) == 1:
        d = first_dim(shape_of(v))
        shifts, axes = sh, [d]
    else:
        shifts, axes = sh, list(range(len(sh)))

    def f(a):
        nd = max(a.ndim, max(axes) + 1)
        a2 = a.reshape(a.shape + (1,) * (nd - a.ndim))
        return np.roll(a2, shifts, axes)
    return _apply_obj(v, f)


@bi('tril')
def tril(nargout, *args):
    k = ival(args[1], 'k', 'tril') if len(args) > 1 else 0
    a = arr(args[0])
    return like_class(np.tril(a, k), args[0])


@bi('triu')
def triu(nargout, *args):
    k = ival(args[1], 'k', 'triu') if len(args) > 1 else 0
    a = arr(args[0])
    return like_class(np.triu(a, k), args[0])


@bi('kron')
def kron(nargout, *args):
    nargchk(args, 2, 2, 'kron')
    return out(np.kron(darr(args[0]), darr(args[1])))


@bi('blkdiag')
def blkdiag(nargout, *args):
    import scipy.linalg as sla
    arrs = [darr(a) for a in args]
    return out(sla.block_diag(*arrs)) if arrs else EMPTY()


@bi('toeplitz')
def toeplitz(nargout, *args):
    import scipy.linalg as sla
    c = darr(args[0]).reshape(-1)
    r = darr(args[1]).reshape(-1) if len(args) > 1 else c.conj()
    return out(sla.toeplitz(c, r))


@bi('hankel')
def hankel(nargout, *args):
    import scipy.linalg as sla
    c = darr(args[0]).reshape(-1)
    r = darr(args[1]).reshape(-1) if len(args) > 1 else None
    return out(sla.hankel(c, r))


@bi('vander')
def vander(nargout, *args):
    v = darr(args[0]).reshape(-1)
    n = ival(args[1]) if len(args) > 1 else v.size
    return out(np.vander(v, n))


@bi('hilb')
def hilb(nargout, *args):
    n = ival(args[0], 'n', 'hilb')
    i = np.arange(1, n + 1)
    return out(1.0 / (i[:, None] + i[None, :] - 1))


@bi('invhilb')
def invhilb(nargout, *args):
    import scipy.linalg as sla
    n = ival(args[0], 'n', 'invhilb')
    return out(sla.invhilbert(n))


@bi('pascal')
def pascal(nargout, *args):
    import scipy.linalg as sla
    n = ival(args[0], 'n', 'pascal')
    return out(sla.pascal(n).astype(F64))


@bi('compan')
def compan(nargout, *args):
    import scipy.linalg as sla
    return out(sla.companion(darr(args[0]).reshape(-1)))


@bi('wilkinson')
def wilkinson(nargout, *args):
    n = ival(args[0], 'n', 'wilkinson')
    m = (n - 1) / 2
    e = np.ones(n - 1)
    return out(np.diag(np.abs(np.arange(-m, m + 1))) + np.diag(e, 1) + np.diag(e, -1))


@bi('rosser')
def rosser(nargout, *args):
    return out(np.array([[611, 196, -192, 407, -8, -52, -49, 29], [196, 899, 113, -192, -71, -43, -8, -44],
                         [-192, 113, 899, 196, 61, 49, 8, 52], [407, -192, 196, 611, 8, 44, 59, -23],
                         [-8, -71, 61, 8, 411, -599, 208, 208], [-52, -43, 49, 44, -599, 411, 208, 208],
                         [-49, -8, 8, 59, 208, 208, 99, -911], [29, -44, 52, -23, 208, 208, -911, 99]], F64))


@bi('accumarray')
def accumarray(nargout, *args):
    nargchk(args, 2, 6, 'accumarray')
    subs = arr(args[0]).astype(np.int64)
    vals = arr(args[1])
    if subs.ndim == 2 and subs.shape[1] == 1 or subs.shape[0] == 1 and subs.ndim == 2 and subs.shape[1] != 1 and False:
        subs = subs.reshape(-1, 1)
    if subs.ndim == 2 and subs.shape[0] == 1 and subs.shape[1] > 1 and vals.size == subs.shape[1]:
        subs = subs.reshape(-1, 1)
    n = subs.shape[0]
    v = vals.reshape(-1, order='F').astype(F64) if vals.dtype.kind != 'c' else vals.reshape(-1, order='F')
    if v.size == 1:
        v = np.full(n, v[0])
    sz = None
    if len(args) > 2 and not (type(args[2]) is np.ndarray and args[2].size == 0):
        sz = [int(x) for x in arr(args[2]).reshape(-1)]
    func = args[3] if len(args) > 3 and not (type(args[3]) is np.ndarray and args[3].size == 0) else None
    fill = num(args[4]) if len(args) > 4 and not (type(args[4]) is np.ndarray and args[4].size == 0) else 0.0
    ncol = subs.shape[1]
    if sz is None:
        sz = [int(subs[:, k].max()) for k in range(ncol)] if n else [0] * ncol
        if ncol == 1:
            sz = [sz[0], 1]
    shape = tuple(sz)
    lin = np.ravel_multi_index(tuple(subs[:, k] - 1 for k in range(ncol)), shape[:ncol] if ncol > 1 else (shape[0],), order='F') if n else np.zeros(0, int)
    total = int(np.prod(shape))
    if func is None:
        res = np.zeros(total, v.dtype)
        np.add.at(res, lin, v)
        if fill != 0:
            seen = np.zeros(total, bool)
            seen[lin] = True
            res[~seen] = fill
    else:
        res = np.full(total, fill, dtype=F64)
        groups = {}
        for i, L in enumerate(lin):
            groups.setdefault(int(L), []).append(v[i])
        for L, g in groups.items():
            r = func.scall(1, out(np.array(g).reshape(-1, 1)))
            res[L] = float(arr(r).reshape(-1)[0])
    return out(res.reshape(shape, order='F'))


# ---- class conversion -----------------------------------------------------------------------

def _to_class(v, klass, fn):
    t = type(v)
    if t is Str:
        if klass == 'double':
            r = np.empty(v.a.shape)
            for i, s in enumerate(v.a.flat):
                try:
                    r.flat[i] = float(s.replace('i', 'j')) if s is not None else math.nan
                except Exception:
                    r.flat[i] = math.nan
            return out(r)
        raise err('MATLAB:invalidConversion', f'Conversion to {klass} from string is not possible.', fn)
    if t is Cell:
        raise err('MATLAB:invalidConversion', f'Conversion to {klass} from cell is not possible.', fn)
    if t is Struct:
        raise err('MATLAB:invalidConversion', f'Conversion to {klass} from struct is not possible.', fn)
    if isinstance(v, Obj):
        h = getattr(v, 'number_value', None)
        if h is not None:
            return float(h()) if klass == 'double' else finish(np.array([[h()]]), klass)
        if hasattr(v, 'a'):
            return out(np.array([[float(x.number_value()) for x in row] for row in v.a]))
        raise err('MATLAB:invalidConversion', f'Conversion to {klass} from {v.cls} is not possible.', fn)
    a = arr(v, fn)
    if klass == 'double':
        if a.dtype == F64 or a.dtype == C128:
            return v if t in (float, complex, np.ndarray) else out(a)
        return out(a.astype(C128 if a.dtype.kind == 'c' else F64))
    if klass == 'single':
        return finish(a.astype(np.complex64 if a.dtype.kind == 'c' else np.float32), 'single')
    if klass == 'logical':
        if a.dtype.kind == 'c':
            raise err('MATLAB:nologicalcomplex', 'Complex values cannot be converted to logicals.', fn)
        if a.dtype.kind == 'f' and np.isnan(a).any():
            raise err('MATLAB:nologicalnan', "NaN's cannot be converted to logicals.", fn)
        return out(a != 0)
    if a.dtype.kind == 'c':
        a = a.real
    return finish(a, klass)


for _c in ('double', 'single', 'logical') + tuple(INT_TYPES):
    def _mk(c):
        def f(nargout, *args):
            nargchk(args, 1, 1, c)
            return _to_class(args[0], c, c)
        f.__name__ = c
        return f
    bi(_c)(_mk(_c))


@bi('cast')
def cast(nargout, *args):
    nargchk(args, 2, 3, 'cast')
    c = sval(args[1], 'class', 'cast') if not (len(args) > 2) else class_of(args[2])
    if len(args) > 2 and opt_str(args[1]) == 'like':
        c = class_of(args[2])
    if c == 'char':
        from .strfun import char as _char
        return _char(1, args[0])
    return _to_class(args[0], c, 'cast')


@bi('typecast')
def typecast(nargout, *args):
    a = arr(args[0])
    c = sval(args[1], 'class', 'typecast')
    dt = np_dtype(c)
    r = a.reshape(-1, order='F').view(dt)
    shape = (1, -1) if a.shape[0] == 1 else (-1, 1)
    return make(r.reshape(shape).copy(), c)

