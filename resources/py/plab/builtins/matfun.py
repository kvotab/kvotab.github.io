"""Linear algebra: inverses and determinants, decompositions, norms,
subspaces, matrix functions; and the operators as named functions (plus,
mtimes and the rest)."""
import math

import numpy as np

from . import bi
from ._util import (err, nargchk, noout, maxout, arr, darr, out, opt_str, opt_lower, sval, ival, num, is_str, bool_out,
                    like_class, first_dim, dim_arg, reduce, expand_dims, strip_flags)
from ..ops import finish, align
from ..values import (MError, Char, Cell, Struct, F64, C128, class_of, shape_of, numel, _2d, EMPTY, py_str, Sparse)
from .. import ops as O
from .. import runtime as R


def _sq(a, fn):
    if a.ndim != 2 or a.shape[0] != a.shape[1]:
        raise err('MATLAB:square', 'Matrix must be square.', fn)


def _mat(v, fn):
    a = darr(v, fn)
    if a.ndim != 2:
        raise err('MATLAB:' + fn + ':inputMustBe2D', 'Input must be 2-D.', fn)
    return a


def _rcond(a):
    from scipy.linalg import lu_factor
    from scipy.linalg.lapack import get_lapack_funcs
    try:
        lu, piv = lu_factor(a, check_finite=False)
        gecon, = get_lapack_funcs(('gecon',), (lu,))
        rc, info = gecon(lu, np.linalg.norm(a, 1), norm='1')
        return float(rc), lu, piv
    except Exception:
        return 0.0, None, None


@bi('inv')
def inv(nargout, *args):
    nargchk(args, 1, 1, 'inv')
    a = _mat(args[0], 'inv')
    _sq(a, 'inv')

    def back(r):
        return like_class(r, args[0]) if class_of(args[0]) == 'single' else out(r)
    if a.size == 0:
        return back(a.copy())
    if a.size == 1:
        # a scalar's inverse is 1/x: inv(-0) is -Inf, inv(Inf) is 0
        z = a.reshape(-1)[0]
        if z == 0:
            R.warn('MATLAB:singularMatrix', 'Matrix is singular to working precision.')
        with np.errstate(all='ignore'):
            if np.iscomplexobj(a):
                r = 0j if np.isinf(z) else (np.nan + np.nan * 1j if np.isnan(z) else (np.inf if z == 0 else 1 / z))
            else:
                r = 1 / z
        return back(np.array([[r]]))
    if not np.all(np.isfinite(a)):
        R.warn('MATLAB:illConditionedMatrix', 'Matrix is singular, close to singular or badly scaled. Results may be inaccurate. RCOND = NaN.')
        return back(np.full(a.shape, np.nan))
    rc, lu, piv = _rcond(a)
    if lu is not None and np.any(np.diag(lu) == 0):
        R.warn('MATLAB:singularMatrix', 'Matrix is singular to working precision.')
        return back(np.full(a.shape, np.inf))
    with np.errstate(all='ignore'):
        r = np.linalg.inv(a)
    if rc < np.finfo(float).eps:
        R.warn('MATLAB:nearlySingularMatrix', f'Matrix is close to singular or badly scaled. Results may be inaccurate. RCOND =  {rc:.6e}.')
    return back(r)


@bi('det')
def det(nargout, *args):
    nargchk(args, 1, 1, 'det')
    a = _mat(args[0], 'det')
    _sq(a, 'det')
    if a.size == 0:
        return 1.0
    return out(np.array(np.linalg.det(a)))


@bi('trace')
def trace(nargout, *args):
    a = _mat(args[0], 'trace')
    _sq(a, 'trace')
    return out(np.array(np.trace(a)))


@bi('rank')
def rank(nargout, *args):
    nargchk(args, 1, 2, 'rank')
    a = _mat(args[0], 'rank')
    if a.size == 0:
        return 0.0
    s = np.linalg.svd(a, compute_uv=False)
    tol = num(args[1]) if len(args) > 1 else max(a.shape) * np.spacing(s.max() if s.size else 0)
    return float(np.sum(s > tol))


@bi('norm')
def norm(nargout, *args):
    nargchk(args, 1, 2, 'norm')
    v0 = args[0]
    a = _mat(v0, 'norm')
    p = args[1] if len(args) > 1 else 2.0
    ps = opt_str(p)
    vec = a.shape[0] == 1 or a.shape[1] == 1
    fin = (lambda x: finish(np.array([[x]], np.float32), 'single')) if class_of(v0) == 'single' else float
    if a.size == 0:
        return fin(0.0)
    if ps is not None:
        ps = ps.lower()
        p = {'fro': 'fro', 'inf': math.inf, '+inf': math.inf, '-inf': -math.inf}.get(ps)
        if p is None:
            raise err('MATLAB:norm:unknownNorm', "The norm is a number, Inf, -Inf or 'fro'.", 'norm')
    else:
        p = num(p)
    with np.errstate(all='ignore'):
        x = np.abs(a.astype(C128 if a.dtype.kind == 'c' else F64))
        if np.any(np.isnan(x)):
            return fin(math.nan)

        def scaled(v, q):
            # the p-norm of v, scaled by its largest element so that it neither overflows nor underflows
            m = np.max(v)
            if m == 0 or not np.isfinite(m):
                return float(m)
            return float(m * np.sum((v / m) ** q) ** (1.0 / q))
        if p == 'fro':
            return fin(scaled(x.reshape(-1), 2.0))
        if vec:
            v = x.reshape(-1)
            if p == math.inf:
                return fin(float(np.max(v)))
            if p == -math.inf:
                return fin(float(np.min(v)))
            if p == 0:
                return fin(float(np.count_nonzero(v)))
            if p < 0:
                return fin(float(np.sum(v ** p) ** (1.0 / p)))
            return fin(scaled(v, float(p)))
        if p == 2:
            if np.any(np.isinf(x)):
                return fin(math.inf)
            return fin(float(np.linalg.svd(a, compute_uv=False)[0]))
        if p == 1:
            return fin(float(np.max(np.sum(x, axis=0))))
        if p == math.inf:
            return fin(float(np.max(np.sum(x, axis=1))))
    raise err('MATLAB:norm:unknownNorm', "The norms of a matrix are 1, 2, Inf and 'fro'.", 'norm')


@bi('vecnorm')
def vecnorm(nargout, *args):
    a = darr(args[0])
    p = num(args[1]) if len(args) > 1 else 2.0
    dim = dim_arg(args[2], 'vecnorm') if len(args) > 2 else first_dim(a.shape)
    A = expand_dims(a, dim)
    with np.errstate(all='ignore'):
        if p == math.inf:
            r = np.max(np.abs(A), axis=dim, keepdims=True)
        else:
            r = np.sum(np.abs(A) ** p, axis=dim, keepdims=True) ** (1 / p)
    return out(r)


@bi('cond')
def cond(nargout, *args):
    a = _mat(args[0], 'cond')
    p = args[1] if len(args) > 1 else 2.0
    ps = opt_str(p)
    if (ps is None and numel(p) != 1) or (ps is not None and ps.lower() not in ('fro', 'inf')):
        raise err('MATLAB:cond:InvalidP', "p is 1, 2, Inf or 'fro'.", 'cond')
    if ps is None and num(p) != 2:
        _sq(a, 'cond')
    if ps is None and num(p) == 2:
        s = np.linalg.svd(a, compute_uv=False)
        with np.errstate(all='ignore'):
            return float(s[0] / s[-1]) if s[-1] != 0 else math.inf
    pp = 'fro' if ps == 'fro' else (np.inf if ps == 'inf' or (ps is None and num(p) == math.inf) else num(p))
    with np.errstate(all='ignore'):
        return float(np.linalg.cond(a, pp))


@bi('rcond')
def rcond(nargout, *args):
    a = _mat(args[0], 'rcond')
    _sq(a, 'rcond')
    rc, _, _ = _rcond(a)
    return rc


@bi('condest')
def condest(nargout, *args):
    a = _mat(args[0], 'condest')
    _sq(a, 'condest')
    with np.errstate(all='ignore'):
        return float(np.linalg.cond(a, 1))


@bi('eig', nout=3)
def eig(nargout, *args):
    nargchk(args, 1, 3, 'eig')
    import scipy.linalg as sla
    a = _mat(args[0], 'eig')
    _sq(a, 'eig')
    rest, flags = strip_flags(args[1:], ('vector', 'matrix', 'nobalance', 'balance', 'chol', 'qz'))
    b = _mat(rest[0], 'eig') if rest else None
    if b is not None and b.shape != a.shape:
        raise err('MATLAB:eig:SizeMismatch', 'A and B must be square matrices of the same size.', 'eig')
    if not np.all(np.isfinite(a)):
        raise err('MATLAB:eig:matrixWithNaNInf', 'Input to EIG must not contain NaN or Inf.', 'eig')
    herm = b is None and np.allclose(a, a.conj().T, rtol=0, atol=0)
    want_vec = nargout >= 2
    if herm:
        if want_vec:
            w, V = np.linalg.eigh(a)
        else:
            w = np.linalg.eigvalsh(a)
    else:
        if b is not None:
            if want_vec:
                w, V = sla.eig(a, b)
            else:
                w = sla.eigvals(a, b)
        else:
            if want_vec:
                w, V = np.linalg.eig(a)
            else:
                w = np.linalg.eigvals(a)
    if not want_vec:
        return out(np.asarray(w).reshape(-1, 1))
    as_vec = 'vector' in flags
    D = np.asarray(w).reshape(-1, 1) if as_vec else np.diag(w)
    res = [out(V), out(D)]
    if nargout >= 3:
        if b is None:
            wl, Wl = (np.linalg.eigh(a) if herm else sla.eig(a, left=True, right=False))
            res.append(out(Wl))
        else:
            res.append(out(sla.eig(a, b, left=True, right=False)[1]))
    return tuple(res)


@bi('eigs', nout=3)
def eigs(nargout, *args):
    a = darr(args[0])
    k = ival(args[1]) if len(args) > 1 else 6
    w, V = np.linalg.eig(a)
    order = np.argsort(-np.abs(w), kind='stable')[:k]
    w = w[order]
    V = V[:, order]
    if nargout >= 2:
        return out(V), out(np.diag(w))
    return out(w.reshape(-1, 1))


@bi('svd', nout=3)
def svd(nargout, *args):
    nargchk(args, 1, 3, 'svd')
    a = _mat(args[0], 'svd')
    if not np.all(np.isfinite(a)):
        raise err('MATLAB:svd:matrixWithNaNInf', 'Input to SVD must not contain NaN or Inf.', 'svd')
    econ = len(args) > 1 and (opt_str(args[1]) == 'econ' or (opt_str(args[1]) is None and num(args[1]) == 0))
    if nargout <= 1:
        s = np.linalg.svd(a, compute_uv=False)
        return out(s.reshape(-1, 1))
    m, n = a.shape
    U, s, Vh = np.linalg.svd(a, full_matrices=not econ)
    if econ:
        k = min(m, n)
        if len(args) > 1 and opt_str(args[1]) is None and m < n:
            # svd(A, 0) trims only for tall matrices
            U, s, Vh = np.linalg.svd(a, full_matrices=True)
            S = np.zeros((m, n))
            S[:len(s), :len(s)] = np.diag(s)
            return (out(U), out(S), out(Vh.conj().T))[:nargout]
        S = np.diag(s)
    else:
        S = np.zeros((m, n), dtype=s.dtype)
        S[:len(s), :len(s)] = np.diag(s)
    return (out(U), out(S), out(Vh.conj().T))[:nargout]


@bi('svds', nout=3)
def svds(nargout, *args):
    a = darr(args[0])
    k = ival(args[1]) if len(args) > 1 else 6
    U, s, Vh = np.linalg.svd(a, full_matrices=False)
    k = min(k, len(s))
    if nargout <= 1:
        return out(s[:k].reshape(-1, 1))
    return (out(U[:, :k]), out(np.diag(s[:k])), out(Vh[:k].conj().T))[:nargout]


@bi('qr', nout=3)
def qr(nargout, *args):
    nargchk(args, 1, 3, 'qr')
    import scipy.linalg as sla
    v0 = args[0]
    a = _mat(v0, 'qr')
    rest = list(args[1:])
    B = None
    if rest and opt_str(rest[0]) is None and not (numel(rest[0]) == 1 and num(rest[0]) == 0):
        B = darr(rest.pop(0))           # [C, R] = qr(A, B): C = Q'*B
        if B.shape[0] != a.shape[0]:
            raise err('MATLAB:qr:BSize', 'A and B must have the same number of rows.', 'qr')
    words = [opt_lower(r) if opt_str(r) is not None else 'zero' for r in rest]
    econ = 'econ' in words or 'zero' in words
    vector = 'vector' in words or 'zero' in words          # qr(A, 0): the permutation as a vector
    mode = 'economic' if econ else 'full'
    m, n = a.shape
    fin = (lambda r: finish(np.asarray(r), 'single')) if class_of(v0) == 'single' else (lambda r: out(np.asarray(r)))
    if a.size == 0:
        k = min(m, n) if econ else m
        Q, Rm = np.eye(m)[:, :k], np.zeros((k, n))
        P = np.arange(n)
    elif nargout >= 3:
        Q, Rm, P = sla.qr(a, mode=mode, pivoting=True)
    else:
        Q, Rm = sla.qr(a, mode=mode)
        P = None
    if B is not None:
        C = Q.conj().T @ B
        res = (fin(C), fin(Rm)) + ((fin(np.eye(n)[:, P]) if not vector else out((P + 1.0).reshape(1, -1))),) if nargout >= 3 else (fin(C), fin(Rm))
        return res[:max(nargout, 1)] if nargout > 1 else fin(Rm)
    if nargout <= 1:
        return fin(np.triu(Rm))
    if nargout == 2:
        return fin(Q), fin(Rm)
    if vector:
        return fin(Q), fin(Rm), out((np.asarray(P) + 1.0).reshape(1, -1))
    Pm = np.zeros((n, n))
    Pm[P, np.arange(n)] = 1
    return fin(Q), fin(Rm), out(Pm)


@bi('lu', nout=4)
def lu(nargout, *args):
    nargchk(args, 1, 3, 'lu')
    import scipy.linalg as sla
    a = _mat(args[0], 'lu')
    vector = len(args) > 1 and opt_str(args[-1]) == 'vector'
    P, L, U = sla.lu(a)
    Pm = P.T
    if nargout <= 1:
        Y = L + U - np.eye(*L.shape) if L.shape[0] == L.shape[1] else U
        Y = np.tril(L, -1)[:, :min(a.shape)] if False else Y
        return out(np.triu(U) + np.tril(L, -1)[:, :U.shape[0]] @ np.eye(U.shape[0], U.shape[1]) if L.shape[1] == U.shape[0] else U)
    if nargout == 2:
        return out(Pm.T @ L), out(U)
    if vector:
        perm = np.argmax(Pm, axis=1) + 1
        return out(L), out(U), out(perm.astype(F64).reshape(-1, 1))
    return out(L), out(U), out(Pm)


@bi('chol', nout=3)
def chol(nargout, *args):
    nargchk(args, 1, 2, 'chol')
    a = _mat(args[0], 'chol')
    _sq(a, 'chol')
    lower = len(args) > 1 and opt_str(args[1]) == 'lower'
    try:
        L = np.linalg.cholesky(a if not np.iscomplexobj(a) else a)
        p = 0
    except np.linalg.LinAlgError:
        if nargout < 2:
            raise err('MATLAB:posdef', 'Matrix must be positive definite.', 'chol')
        # the leading part that is positive definite
        p = 0
        n = a.shape[0]
        L = None
        for q in range(n, 0, -1):
            try:
                L = np.linalg.cholesky(a[:q, :q])
                p = q + 1
                break
            except np.linalg.LinAlgError:
                continue
        if L is None:
            L = np.zeros((0, 0))
            p = 1
    Rm = L.conj().T
    res = out(L if lower else Rm)
    if nargout >= 2:
        return res, float(p)
    return res


@bi('schur', nout=2)
def schur(nargout, *args):
    import scipy.linalg as sla
    a = _mat(args[0], 'schur')
    _sq(a, 'schur')
    kind = opt_str(args[1]) if len(args) > 1 else ('complex' if np.iscomplexobj(a) else 'real')
    if kind not in ('real', 'complex'):
        raise err('MATLAB:schur:InvalidFlag', "The flag is 'real' or 'complex'.", 'schur')
    T, Z = sla.schur(a, output=kind)
    return (out(Z), out(T)) if nargout >= 2 else out(T)


@bi('hess', nout=2)
def hess(nargout, *args):
    import scipy.linalg as sla
    a = _mat(args[0], 'hess')
    _sq(a, 'hess')
    H, Q = sla.hessenberg(a, calc_q=True)
    return (out(Q), out(H)) if nargout >= 2 else out(H)


@bi('pinv')
def pinv(nargout, *args):
    a = _mat(args[0], 'pinv')
    if a.size == 0:
        return out(np.zeros((a.shape[1], a.shape[0])))
    U, s, Vh = np.linalg.svd(a, full_matrices=False)
    tol = num(args[1]) if len(args) > 1 else max(a.shape) * np.spacing(s.max() if s.size else 0)
    r = np.sum(s > tol)
    S = 1.0 / s[:r]
    return out((Vh[:r].conj().T * S) @ U[:, :r].conj().T)


@bi('null')
def null(nargout, *args):
    a = _mat(args[0], 'null')
    if len(args) > 1 and opt_str(args[1]) == 'r':
        R_, piv = _rref(a.copy(), None)
        m, n = a.shape
        r = len(piv)
        nopiv = [j for j in range(n) if j not in piv]
        Z = np.zeros((n, n - r))
        for k, j in enumerate(nopiv):
            Z[j, k] = 1
            for i, pj in enumerate(piv):
                Z[pj, k] = -R_[i, j]
        return out(Z)
    if a.size == 0:
        return out(np.eye(a.shape[1]))
    U, s, Vh = np.linalg.svd(a, full_matrices=True)
    tol = max(a.shape) * np.spacing(s.max() if s.size else 0)
    r = int(np.sum(s > tol))
    return out(Vh[r:].conj().T)


@bi('orth')
def orth(nargout, *args):
    a = _mat(args[0], 'orth')
    U, s, Vh = np.linalg.svd(a, full_matrices=False)
    tol = max(a.shape) * np.spacing(s.max() if s.size else 0)
    r = int(np.sum(s > tol))
    return out(U[:, :r])


def _rref(A, tol):
    m, n = A.shape
    if tol is None:
        tol = max(m, n) * np.finfo(float).eps * (np.linalg.norm(A, np.inf) if A.size else 0)
    piv = []
    i = 0
    for j in range(n):
        if i >= m:
            break
        k = int(np.argmax(np.abs(A[i:, j]))) + i
        p = abs(A[k, j])
        if p <= tol:
            A[i:, j] = 0
            continue
        piv.append(j)
        A[[i, k], j:] = A[[k, i], j:]
        A[i, j:] = A[i, j:] / A[i, j]
        for r in range(m):
            if r != i:
                A[r, j:] = A[r, j:] - A[r, j] * A[i, j:]
        i += 1
    return A, piv


@bi('rref', nout=2)
def rref(nargout, *args):
    a = _mat(args[0], 'rref').copy()
    tol = num(args[1]) if len(args) > 1 else None
    Rr, piv = _rref(a, tol)
    if nargout >= 2:
        return out(Rr), out((np.array(piv, F64) + 1).reshape(1, -1))
    return out(Rr)


def _matfun(name, fn):
    def f(nargout, *args):
        import scipy.linalg as sla
        a = _mat(args[0], name)
        _sq(a, name)
        with np.errstate(all='ignore'):
            r = fn(sla, a)
        if isinstance(r, tuple):
            r = r[0]
        return out(r)
    f.__name__ = name
    bi(name)(f)


_matfun('expm', lambda sla, a: sla.expm(a))
_matfun('logm', lambda sla, a: sla.logm(a, disp=False))
_matfun('sqrtm', lambda sla, a: sla.sqrtm(a, disp=False))


@bi('funm')
def funm(nargout, *args):
    import scipy.linalg as sla
    a = _mat(args[0], 'funm')
    _sq(a, 'funm')
    f = args[1]
    if is_str(f):
        f = R.NamedFH(py_str(f))
    if not hasattr(f, 'scall'):
        raise err('MATLAB:funm:InvalidFunction', 'The second input is a function handle or name.', 'funm')
    name = f.name() if hasattr(f, 'name') else ''
    simple = {'exp': np.exp, 'log': np.log, 'sin': np.sin, 'cos': np.cos, 'sqrt': np.sqrt, 'sinh': np.sinh, 'cosh': np.cosh}
    fn = simple.get(name)
    if fn is None:
        fn = lambda x: np.asarray(darr(f.scall(1, out(np.asarray(x)))))
    return out(sla.funm(a, fn))


@bi('cross')
def cross(nargout, *args):
    nargchk(args, 2, 3, 'cross')
    a = darr(args[0])
    b = darr(args[1])
    if a.shape != b.shape:
        raise err('MATLAB:cross:InputSizeMismatch', 'A and B must be of the same size.', 'cross')
    if len(args) > 2:
        dim = dim_arg(args[2], 'cross')
    else:
        dims = [i for i, d in enumerate(a.shape) if d == 3]
        if not dims:
            raise err('MATLAB:cross:InvalidDimAorB', 'A and B must have at least one dimension of length 3.', 'cross')
        dim = dims[0]
    return out(np.cross(a, b, axis=dim))


@bi('dot')
def dot(nargout, *args):
    nargchk(args, 2, 3, 'dot')
    a = darr(args[0])
    b = darr(args[1])
    if a.size != b.size and not (len(args) > 2):
        raise err('MATLAB:dot:InputSizeMismatch', 'A and B must be the same size.', 'dot')
    if (a.ndim == 2 and 1 in a.shape) and (b.ndim == 2 and 1 in b.shape) and len(args) < 3:
        return out(np.array(np.sum(np.conj(a.reshape(-1)) * b.reshape(-1))))
    dim = dim_arg(args[2], 'dot') if len(args) > 2 else first_dim(a.shape)
    a, b = align(a, b)
    if dim != 'all' and dim >= a.ndim:
        # a dimension past the arrays' own: each element with itself
        return out(np.conj(a) * b)
    return out(np.sum(np.conj(a) * b, axis=dim, keepdims=True))


_LINSOLVE_OPTS = ('LT', 'UT', 'UHESS', 'SYM', 'POSDEF', 'RECT', 'TRANSA')


@bi('linsolve', nout=2)
def linsolve(nargout, *args):
    """A\\b; with opts, UT or LT take only that triangle of A and TRANSA solves with A' (the other kinds
    only say what A\\b finds for itself)."""
    nargchk(args, 2, 3, 'linsolve')
    A = args[0]
    if len(args) == 3:
        o = args[2]
        if not isinstance(o, Struct) or numel(o) != 1:
            raise err('MATLAB:linsolve:OptsNotStruct', 'opts must be a scalar structure.', 'linsolve')
        flags = {}
        for k in o.keys:
            if k not in _LINSOLVE_OPTS:
                raise err('MATLAB:linsolve:UnknownOption', f"Unknown option '{k}': the options are {', '.join(_LINSOLVE_OPTS)}.", 'linsolve')
            flags[k] = bool(num(o.get1(k)))
        if flags.get('UT') or flags.get('LT'):
            a = _mat(A, 'linsolve')
            A = out(np.triu(a) if flags.get('UT') else np.tril(a))
        if flags.get('TRANSA'):
            A = O.ctranspose(A)
    x = O.mldivide(A, args[1])
    if nargout >= 2:
        a = _mat(A, 'linsolve')
        rc = _rcond(a)[0] if a.shape[0] == a.shape[1] else float(np.linalg.matrix_rank(a))
        return x, rc
    return x


@bi('balance', nout=2)
def balance(nargout, *args):
    import scipy.linalg as sla
    a = _mat(args[0], 'balance')
    _sq(a, 'balance')
    B, T = sla.matrix_balance(a)
    return (out(T), out(B)) if nargout >= 2 else out(B)


def _givens(x, y):
    r = math.hypot(x, y)
    if r == 0:
        return np.eye(2)
    c, s = x / r, y / r
    return np.array([[c, s], [-s, c]])


@bi('givens')
def givens(nargout, *args):
    return out(_givens(num(args[0]), num(args[1])))


@bi('planerot', nout=2)
def planerot(nargout, *args):
    x = darr(args[0]).reshape(-1)
    if x.size != 2:
        raise err('MATLAB:planerot:InvalidInput', 'x must have two elements.', 'planerot')
    G = _givens(float(x[0]), float(x[1]))
    return (out(G), out((G @ x).reshape(-1, 1))) if nargout >= 2 else out(G)


# ---- the operators as functions ----------------------------------------------------------

def _opfn(name, fn, nary=False):
    def f(nargout, *args):
        if nary and len(args) > 2:
            r = args[0]
            for b in args[1:]:
                r = fn(r, b)
            return r
        nargchk(args, 2, 2, name)
        return fn(args[0], args[1])
    f.__name__ = name
    bi(name)(f)


_opfn('plus', O.plus, True)
_opfn('minus', O.minus)
_opfn('times', O.times, True)
_opfn('rdivide', O.rdivide)
_opfn('ldivide', O.ldivide)
_opfn('mtimes', O.mtimes, True)
_opfn('mrdivide', O.mrdivide)
_opfn('mldivide', O.mldivide)
_opfn('power', O.power)
_opfn('mpower', O.mpower)
_opfn('eq', O.eq)
_opfn('ne', O.ne)
_opfn('lt', O.lt)
_opfn('le', O.le)
_opfn('gt', O.gt)
_opfn('ge', O.ge)


@bi('uminus')
def uminus(nargout, *args):
    return O.uminus(args[0])


@bi('uplus')
def uplus(nargout, *args):
    return O.uplus(args[0])


@bi('transpose')
def transpose(nargout, *args):
    return O.transpose(args[0])


@bi('ctranspose')
def ctranspose(nargout, *args):
    return O.ctranspose(args[0])


# ---- structure tests ----------------------------------------------------------------------------------------

def _struct_mat(v, fn):
    """The matrix a structure test reads: a sparse one as SciPy's CSC."""
    if class_of(v) in ('cell', 'struct', 'string') or isinstance(v, (Cell, Struct)):
        raise err(f'MATLAB:{fn}:invalidInput', 'The input must be a numeric or logical matrix.', fn)
    if type(v) is Sparse:
        m = v.m
        return m.astype(F64) if m.dtype == np.bool_ else m
    a = np.asarray(darr(v, fn))
    if a.ndim != 2:
        raise err(f'MATLAB:{fn}:inputMustBe2D', 'Input must be 2-D.', fn)
    return a


def _sym_test(name, conj):
    @bi(name)
    def f(nargout, *args):
        """True when A equals its transpose (A' for ishermitian), or minus it
        with 'skew'; with a tolerance, when norm(A - A.', inf) is within tol
        of norm(A, inf)."""
        nargchk(args, 1, 3, name)
        a = _struct_mat(args[0], name)
        skew, tol = False, None
        for x in args[1:]:
            s = opt_str(x)
            if s is not None:
                if s.lower() not in ('skew', 'nonskew'):
                    raise err(f'MATLAB:{name}:invalidOption', "The option is 'skew' or 'nonskew'.", name)
                skew = s.lower() == 'skew'
            else:
                tol = float(num(x))
        if a.shape[0] != a.shape[1]:
            return False
        t = a.conj().T if conj else a.T
        d = a + t if skew else a - t
        if hasattr(d, 'nnz'):
            d = d.tocsc()
            d.eliminate_zeros()
            if tol is None:
                return d.nnz == 0 and not np.any(np.isnan(a.data))
            na = float(abs(a).sum(axis=1).max()) if a.shape[0] else 0.0
            nd = float(abs(d).sum(axis=1).max()) if d.shape[0] else 0.0
            return bool(nd <= tol * na)
        if tol is None:
            return bool(np.all(d == 0))
        with np.errstate(all='ignore'):
            na = np.max(np.sum(np.abs(a), axis=1)) if a.size else 0.0
            nd = np.max(np.sum(np.abs(d), axis=1)) if d.size else 0.0
        return bool(nd <= tol * na)
    return f


_sym_test('issymmetric', False)
_sym_test('ishermitian', True)


def _band(a):
    """The lower and upper bandwidths: how far the nonzeros reach below and above the diagonal."""
    if hasattr(a, 'nnz'):
        c = a.tocoo()
        i, j = c.row.astype(np.int64), c.col.astype(np.int64)
    else:
        i, j = np.nonzero(a)
    if i.size == 0:
        return 0, 0
    return int(max(0, np.max(i - j))), int(max(0, np.max(j - i)))


@bi('istril')
def istril(nargout, *args):
    nargchk(args, 1, 1, 'istril')
    return _band(_struct_mat(args[0], 'istril'))[1] == 0


@bi('istriu')
def istriu(nargout, *args):
    nargchk(args, 1, 1, 'istriu')
    return _band(_struct_mat(args[0], 'istriu'))[0] == 0


@bi('isbanded')
def isbanded(nargout, *args):
    nargchk(args, 3, 3, 'isbanded')
    lo, up = _band(_struct_mat(args[0], 'isbanded'))
    return lo <= num(args[1]) and up <= num(args[2])


@bi('bandwidth', nout=2)
def bandwidth(nargout, *args):
    """[lower, upper] = bandwidth(A), or bandwidth(A, 'lower') or 'upper'."""
    nargchk(args, 1, 2, 'bandwidth')
    lo, up = _band(_struct_mat(args[0], 'bandwidth'))
    if len(args) > 1:
        t = (opt_str(args[1]) or '').lower()
        if t not in ('lower', 'upper'):
            raise err('MATLAB:bandwidth:invalidType', "The type is 'lower' or 'upper'.", 'bandwidth')
        return float(lo if t == 'lower' else up)
    return (float(lo), float(up)) if nargout > 1 else float(lo)


# ---- iterative solvers --------------------------------------------------------------------------------------------

def _operator(v, n, fn, transposable=False):
    """A matrix, or a function handle computing A*x (and A'*x when asked with
    'transp'), as SciPy's LinearOperator."""
    from scipy.sparse.linalg import LinearOperator
    from ..values import FH
    if isinstance(v, FH):
        def mv(x):
            args = (out(np.asarray(x).reshape(-1, 1)),) + (('notransp',) if transposable else ())
            if transposable:
                args = (args[0], Char.of('notransp'))
            return np.asarray(arr(v.scall(1, *args))).reshape(-1)

        def rmv(x):
            return np.asarray(arr(v.scall(1, out(np.asarray(x).reshape(-1, 1)), Char.of('transp')))).reshape(-1)
        return LinearOperator((n, n), matvec=mv, rmatvec=rmv if transposable else None, dtype=F64), None
    a = _sparse_or_mat(v, fn)
    if a.shape[0] != a.shape[1] and fn != 'lsqr':
        raise err(f'MATLAB:{fn}:NonSquareMatrix', 'The matrix must be square.', fn)
    return a, a


def _precond(M1, M2, n, fn):
    """MATLAB's preconditioner M = M1*M2 (whose system M y = r is solved) as
    SciPy's M (which applies an approximation of inv(A))."""
    from scipy.sparse.linalg import LinearOperator
    if M1 is None:
        return None
    parts = [_factored(M, fn) for M in (M1, M2) if M is not None and numel(M)]

    def apply(r):
        y = np.asarray(r).reshape(-1)
        for solve, _ in parts:
            y = solve(y)
        return y

    def apply_t(r):
        # the transpose, for qmr: the factors transposed, in the other order
        y = np.asarray(r).reshape(-1)
        for _, solve_t in reversed(parts):
            y = solve_t(y)
        return y
    if not parts:
        return None
    return LinearOperator((n, n), matvec=apply, rmatvec=apply_t, dtype=F64)


def _sparse_or_mat(v, fn):
    """A matrix as the solvers take it: a sparse one as SciPy's CSC."""
    if type(v) is Sparse:
        m = v.m
        return m.astype(F64) if m.dtype == np.bool_ else m
    return _mat(v, fn)


def _factored(M, fn):
    """y -> M \\ y and y -> M.' \\ y for a matrix M (factored once: SuperLU
    for a sparse one, LAPACK's LU for a full one) or a function handle."""
    from ..values import FH
    if isinstance(M, FH):
        return (lambda y: np.asarray(arr(M.scall(1, out(y.reshape(-1, 1))))).reshape(-1),
                lambda y: np.asarray(arr(M.scall(1, out(y.reshape(-1, 1)), Char.of('transp')))).reshape(-1))
    a = _sparse_or_mat(M, fn)
    if hasattr(a, 'nnz'):
        from scipy.sparse.linalg import splu
        try:
            f = splu(a.tocsc())
        except RuntimeError:
            raise err(f'MATLAB:{fn}:SingularPreconditioner', 'The preconditioner is singular.', fn)
        return (lambda y: f.solve(np.asarray(y, dtype=np.result_type(y, a.dtype))),
                lambda y: f.solve(np.asarray(y, dtype=np.result_type(y, a.dtype)), trans='T'))
    from scipy.linalg import lu_factor, lu_solve
    with np.errstate(all='ignore'):
        f = lu_factor(a, check_finite=False)
    return (lambda y: lu_solve(f, y, check_finite=False), lambda y: lu_solve(f, y, trans=1, check_finite=False))


def _solver_args(args, fn, has_restart=False):
    """A, b, (restart,) tol, maxit, M1, M2, x0 in the language's order, with
    the defaults: tol 1e-6, maxit min(n, 20)."""
    b = darr(args[1]).reshape(-1)
    n = b.size
    rest = list(args[2:]) + [None] * 8
    restart = None
    if has_restart:
        r = rest.pop(0)
        restart = int(num(r)) if r is not None and numel(r) else None
    tol = rest[0]
    tol = 1e-6 if tol is None or not numel(tol) else float(num(tol))
    maxit = rest[1]
    maxit = None if maxit is None or not numel(maxit) else int(num(maxit))
    M1 = rest[2] if rest[2] is not None and numel(rest[2]) else None
    M2 = rest[3] if rest[3] is not None and numel(rest[3]) else None
    x0 = rest[4]
    x0 = np.zeros(n) if x0 is None or not numel(x0) else darr(x0).reshape(-1).astype(F64)
    return b, n, restart, tol, maxit, M1, M2, x0


_SOLVERS = {'pcg': 'cg', 'bicg': 'bicg', 'bicgstab': 'bicgstab', 'cgs': 'cgs', 'minres': 'minres', 'qmr': 'qmr', 'tfqmr': 'tfqmr', 'gmres': 'gmres'}


def _run_solver(name, solver, A, b, tol, restart, kw, cb, resvec, nb):
    with np.errstate(all='ignore'):
        if name == 'gmres':
            def cbg(rk):
                resvec.append(float(rk) * nb)
            return solver(A, b, rtol=tol, atol=0.0, restart=restart, callback=cbg, callback_type='pr_norm', **kw)
        if name in ('minres', 'symmlq'):
            return solver(A, b, rtol=tol, callback=cb, **kw)
        return solver(A, b, rtol=tol, atol=0.0, callback=cb, **kw)


def _iterative(name):
    @bi(name, nout=5)
    def f(nargout, *args):
        """[x, flag, relres, iter, resvec] by SciPy's scipy.sparse.linalg solver."""
        nargchk(args, 2, 8, name)
        import scipy.sparse.linalg as SL
        b, n, restart, tol, maxit, M1, M2, x0 = _solver_args(args, name, name == 'gmres')
        A, dense = _operator(args[0], n, name, transposable=name in ('bicg', 'qmr'))
        if dense is not None and dense.shape[0] != n:
            raise err(f'MATLAB:{name}:WrongSize', 'b must have one element per row of A.', name)

        def Ax(x):
            return A @ x if dense is not None else A.matvec(x)
        if name == 'gmres':
            restart = n if restart is None else min(restart, n)
            outer = maxit if maxit is not None else min(max(n // restart, 1), 10)
            maxiter = outer
        else:
            maxiter = maxit if maxit is not None else min(n, 20)
        M = _precond(M1, M2, n, name)
        nb = float(np.linalg.norm(b))
        if nb == 0:
            x = np.zeros(n)
            res = (out(x.reshape(-1, 1)), 0.0, 0.0, 0.0, out(np.zeros((1, 1))))
            return res[0] if nargout <= 1 else res[:nargout]
        resvec = [float(np.linalg.norm(b - Ax(x0)))]
        count = [0]
        best = [resvec[0], x0.copy(), 0]    # the iterate with the smallest residual, and its step

        def cb(xk):
            count[0] += 1
            xk = np.asarray(xk).reshape(-1)
            r = float(np.linalg.norm(b - Ax(xk)))
            resvec.append(r)
            if r < best[0]:
                best[:] = [r, xk.copy(), count[0]]
        if name == 'qmr':
            # SciPy's qmr takes a left and a right preconditioner together: the right one is I
            from scipy.sparse.linalg import LinearOperator
            ident = LinearOperator((n, n), matvec=lambda r: np.asarray(r).reshape(-1), rmatvec=lambda r: np.asarray(r).reshape(-1), dtype=F64)
            kw = dict(x0=x0, maxiter=maxiter) if M is None else dict(x0=x0, maxiter=maxiter, M1=M, M2=ident)
        else:
            kw = dict(x0=x0, maxiter=maxiter, M=M)
        solver = _SOLVERS[name] if callable(_SOLVERS[name]) else getattr(SL, _SOLVERS[name])
        try:
            x, info = _run_solver(name, solver, A, b, tol, restart, kw, cb, resvec, nb)
        except (ValueError, np.linalg.LinAlgError, ZeroDivisionError, FloatingPointError):
            # a singular or not finite preconditioner stops the method: flag 2
            x, info = x0.copy(), -2
        inner = [len(resvec) - 1]           # gmres: its inner steps, one residual each
        it = float(count[0])
        if not isinstance(x, np.ndarray):
            x, it = best[1], float(best[2])  # SciPy 1.13's bicg and cgs give back a function, not x, when they break down
        x = np.asarray(x).reshape(-1)
        if not np.all(np.isfinite(x)):
            x, info = x0.copy(), -2
        relres = float(np.linalg.norm(b - Ax(x)) / nb)
        if name != 'gmres' and relres > tol * (1 + 1e-8) and best[0] / nb < relres:
            # stopped short of the tolerance: the iterate with the smallest residual, and the step that made it
            x, relres, it = best[1], best[0] / nb, float(best[2])
        # a breakdown just after the residual fell within the tolerance still leaves a solution
        flag = 0.0 if info != -2 and relres <= tol * (1 + 1e-8) else (1.0 if info >= 0 else (2.0 if info == -2 else 4.0))
        if name == 'gmres':
            k = inner[0]
            it = out(np.array([[float(max(1, math.ceil(k / restart)) if k else 0), float((k - 1) % restart + 1) if k else 0.0]]))
        res = (out(x.reshape(-1, 1)), flag, relres, it, out(np.array(resvec).reshape(-1, 1)))
        return res[0] if nargout <= 1 else res[:nargout]
    return f


for _n in _SOLVERS:
    _iterative(_n)


@bi('lsqr', nout=5)
def lsqr(nargout, *args):
    """[x, flag, relres, iter, resvec] = lsqr(A, b, tol, maxit, M1, M2, x0):
    least squares by scipy.sparse.linalg.lsqr, its atol and btol the
    tolerance."""
    nargchk(args, 2, 7, 'lsqr')
    import scipy.sparse.linalg as SL
    b, n, _, tol, maxit, M1, M2, x0 = _solver_args(args, 'lsqr')
    from ..values import FH
    if isinstance(args[0], FH):
        raise err('MATLAB:lsqr:FunctionHandle', 'lsqr takes a matrix here.', 'lsqr')
    A = _sparse_or_mat(args[0], 'lsqr')
    if A.shape[0] != b.size:
        raise err('MATLAB:lsqr:WrongSize', 'b must have one element per row of A.', 'lsqr')
    if len(args) < 7 or not numel(args[6]):
        x0 = np.zeros(A.shape[1])          # x has one element per column of A
    if M1 is not None:
        # the right preconditioner P = M1*M2: lsqr on A*inv(P), x = P \ y
        parts = [(M, _factored(M, 'lsqr')) for M in (M1, M2) if M is not None and numel(M)]

        def P_solve(y):
            for _, (solve, _t) in parts:
                y = solve(y)
            return y

        def P_solve_t(y):
            for _, (_s, solve_t) in reversed(parts):
                y = solve_t(y)
            return y

        def P_mul(x):
            for M, _ in reversed(parts):
                m = _sparse_or_mat(M, 'lsqr')
                x = m @ x
            return np.asarray(x).reshape(-1)
        Ap = SL.LinearOperator(A.shape, matvec=lambda y: A @ P_solve(np.asarray(y).reshape(-1)),
                               rmatvec=lambda z: P_solve_t(np.asarray(A.T @ np.asarray(z).reshape(-1)).reshape(-1)), dtype=F64)
    else:
        Ap, P_solve, P_mul = A, None, None
    maxit = maxit if maxit is not None else min(min(A.shape), 20)
    y0 = x0 if P_mul is None else P_mul(x0)
    r = SL.lsqr(Ap, b, atol=tol, btol=tol, iter_lim=maxit, x0=y0)
    y, istop, itn = r[0], r[1], r[2]
    x = y if P_solve is None else P_solve(y)
    nb = float(np.linalg.norm(b))
    relres = float(np.linalg.norm(b - A @ x) / nb) if nb else 0.0
    flag = 0.0 if istop in (0, 1, 2, 4, 5) else (1.0 if istop == 7 else 4.0)
    res = (out(x.reshape(-1, 1)), flag, relres, float(itn), out(np.array([[float(np.linalg.norm(b - A @ x0))], [float(np.linalg.norm(b - A @ x))]])))
    return res[0] if nargout <= 1 else res[:nargout]


# ---- updating factorizations -----------------------------------------------------------------------------------

@bi('cholupdate', nout=2)
def cholupdate(nargout, *args):
    """[R1, p] = cholupdate(R, x, op): the Cholesky factor of R'*R + x*x'
    ('+', the default) or R'*R - x*x' ('-'); p is 1 when the downdated
    matrix is not positive definite (R1 is then R)."""
    nargchk(args, 2, 3, 'cholupdate')
    from scipy.linalg import cholesky, LinAlgError
    R0 = _mat(args[0], 'cholupdate')
    x = darr(args[1]).reshape(-1)
    op = py_str(args[2]) if len(args) > 2 else '+'
    if op not in ('+', '-'):
        raise err('MATLAB:cholupdate:InvalidOp', "The operation is '+' or '-'.", 'cholupdate')
    if R0.shape[0] != R0.shape[1] or x.size != R0.shape[0]:
        raise err('MATLAB:cholupdate:SizeMismatch', 'R must be square and x have one element per row.', 'cholupdate')
    G = R0.conj().T @ R0 + (1 if op == '+' else -1) * np.outer(x, x.conj())
    try:
        R1 = cholesky(G, lower=False)
        p = 0.0
    except LinAlgError:
        if nargout < 2:
            raise err('MATLAB:cholupdate:NotPositiveDefinite', 'The downdated matrix is not positive definite.', 'cholupdate')
        R1, p = R0, 1.0
    return (out(R1), p) if nargout > 1 else out(R1)


@bi('qrupdate', nout=2)
def qrupdate(nargout, *args):
    """[Q1, R1] = qrupdate(Q, R, u, v): the QR factors of Q*R + u*v'
    (scipy.linalg.qr_update)."""
    nargchk(args, 4, 4, 'qrupdate')
    from scipy.linalg import qr_update
    Q, Rm = _mat(args[0], 'qrupdate'), _mat(args[1], 'qrupdate')
    u, w = darr(args[2]).reshape(-1), darr(args[3]).reshape(-1)
    cplx = any(np.iscomplexobj(a) for a in (Q, Rm, u, w))
    t = C128 if cplx else F64
    Q1, R1 = qr_update(Q.astype(t), Rm.astype(t), u.astype(t), w.conj().astype(t))
    return (out(Q1), out(R1)) if nargout > 1 else out(Q1)


@bi('qrinsert', nout=2)
def qrinsert(nargout, *args):
    """[Q1, R1] = qrinsert(Q, R, j, x, 'col' or 'row'): the QR factors with x
    inserted before column (or row) j (scipy.linalg.qr_insert)."""
    nargchk(args, 4, 5, 'qrinsert')
    from scipy.linalg import qr_insert
    Q, Rm = _mat(args[0], 'qrinsert'), _mat(args[1], 'qrinsert')
    j = ival(args[2]) - 1
    x = darr(args[3]).reshape(-1)
    which = (opt_str(args[4]) or 'col').lower() if len(args) > 4 else 'col'
    if which not in ('col', 'row'):
        raise err('MATLAB:qrinsert:InvalidOrient', "The orientation is 'col' or 'row'.", 'qrinsert')
    t = C128 if any(np.iscomplexobj(a) for a in (Q, Rm, x)) else F64
    Q1, R1 = qr_insert(Q.astype(t), Rm.astype(t), x.astype(t), j, which=which)
    return (out(Q1), out(R1)) if nargout > 1 else out(Q1)


@bi('qrdelete', nout=2)
def qrdelete(nargout, *args):
    """[Q1, R1] = qrdelete(Q, R, j, 'col' or 'row'): the QR factors without
    column (or row) j (scipy.linalg.qr_delete)."""
    nargchk(args, 3, 4, 'qrdelete')
    from scipy.linalg import qr_delete
    Q, Rm = _mat(args[0], 'qrdelete'), _mat(args[1], 'qrdelete')
    if Q.shape[0] != Q.shape[1] or Rm.shape[0] != Q.shape[1]:
        raise err('MATLAB:qrdelete:SizeMismatch', 'Q must be square, with as many columns as R has rows.', 'qrdelete')
    j = ival(args[2]) - 1
    which = (opt_str(args[3]) or 'col').lower() if len(args) > 3 else 'col'
    if which not in ('col', 'row'):
        raise err('MATLAB:qrdelete:InvalidOrient', "The orientation is 'col' or 'row'.", 'qrdelete')
    t = C128 if any(np.iscomplexobj(a) for a in (Q, Rm)) else F64
    Q1, R1 = qr_delete(Q.astype(t), Rm.astype(t), j, 1, which=which)
    return (out(Q1), out(R1)) if nargout > 1 else out(Q1)


# ---- generalized and ordered Schur forms ----------------------------------------------------------------------

@bi('qz', nout=6)
def qz(nargout, *args):
    """[AA, BB, Q, Z, V, W] = qz(A, B, flag): Q*A*Z = AA and Q*B*Z = BB, upper
    triangular ('complex', the default) or quasi-triangular ('real'), by
    scipy.linalg.qz; V and W the right and left generalized eigenvectors."""
    nargchk(args, 2, 3, 'qz')
    from scipy.linalg import qz as _qz, eig as _eig
    A, B = _mat(args[0], 'qz'), _mat(args[1], 'qz')
    if A.shape != B.shape or A.shape[0] != A.shape[1]:
        raise err('MATLAB:qz:SizeMismatch', 'A and B must be square matrices of the same size.', 'qz')
    if len(args) > 2 and opt_str(args[2]) is None:
        raise err('MATLAB:qz:InvalidFlag', "The flag must be text: 'complex' or 'real'.", 'qz')
    flag = opt_lower(args[2]) if len(args) > 2 else 'complex'
    if flag not in ('complex', 'real'):
        raise err('MATLAB:qz:InvalidFlag', "The flag is 'complex' or 'real'.", 'qz')
    if flag == 'real' and (np.iscomplexobj(A) or np.iscomplexobj(B)):
        flag = 'complex'
    AA, BB, Qs, Zs = _qz(A, B, output=flag)
    res = [out(AA), out(BB), out(Qs.conj().T), out(Zs)]
    if nargout > 4:
        w, vl, vr = _eig(A, B, left=True, right=True)
        vr = vr / np.where(np.linalg.norm(vr, axis=0) == 0, 1, np.linalg.norm(vr, axis=0))
        vl = vl / np.where(np.linalg.norm(vl, axis=0) == 0, 1, np.linalg.norm(vl, axis=0))
        res += [out(vr), out(vl)]
    return res[0] if nargout <= 1 else tuple(res[:nargout])


def _schur_select(T, sel):
    """A select vector for LAPACK: both eigenvalues of a real 2-by-2 block in or out together."""
    n = T.shape[0]
    s = np.asarray(sel, bool).copy()
    if not np.iscomplexobj(T):
        k = 0
        while k < n - 1:
            if T[k + 1, k] != 0:
                s[k] = s[k + 1] = s[k] or s[k + 1]
                k += 2
            else:
                k += 1
    return s.astype(np.int32)


@bi('ordschur', nout=2)
def ordschur(nargout, *args):
    """[US, TS] = ordschur(U, T, select): the Schur form reordered so that the
    selected eigenvalues come first (LAPACK's trsen); select may instead be
    keys, the clusters then in order of decreasing key."""
    nargchk(args, 3, 3, 'ordschur')
    import scipy.linalg.lapack as L
    U, T = _mat(args[0], 'ordschur'), _mat(args[1], 'ordschur')
    n = T.shape[0]
    key = np.asarray(arr(args[2])).reshape(-1)
    if key.size != n:
        raise err('MATLAB:ordschur:SelectSize', 'select must have one element per eigenvalue.', 'ordschur')
    cplx = np.iscomplexobj(T) or np.iscomplexobj(U)
    t = C128 if cplx else F64
    U, T = U.astype(t), T.astype(t)
    fn = L.ztrsen if cplx else L.dtrsen
    if key.dtype == bool:
        levels = [None]
    else:
        levels = sorted(set(key.tolist()), reverse=True)[:-1][::-1]
    key = key.copy()
    for lev in levels:
        sel = _schur_select(T, key if lev is None else key >= lev).astype(bool)
        r = fn(sel.astype(np.int32), T, U, job='N')
        T, U, info = r[0], r[1], r[-1]
        if info != 0:
            raise err('MATLAB:ordschur:Reorder', 'The eigenvalues could not be reordered (they are too close).', 'ordschur')
        # the selected eigenvalues now come first, each part in its old order: the keys follow
        key = np.concatenate([key[sel], key[~sel]])
    return (out(U), out(T)) if nargout > 1 else out(U)


def _pencil_eigs(AA, BB):
    """The eigenvalues of a (quasi-)triangular pencil, one per diagonal place
    (a real 2-by-2 block giving its pair to both of its places)."""
    from scipy.linalg import eigvals
    n = AA.shape[0]
    ev = np.zeros(n, complex)
    k = 0
    while k < n:
        if k < n - 1 and not np.iscomplexobj(AA) and AA[k + 1, k] != 0:
            ev[k:k + 2] = sorted(eigvals(AA[k:k + 2, k:k + 2], BB[k:k + 2, k:k + 2]), key=lambda z: -z.imag)
            k += 2
        else:
            with np.errstate(all='ignore'):
                ev[k] = AA[k, k] / BB[k, k] if BB[k, k] != 0 else (math.inf if AA[k, k] != 0 else math.nan)
            k += 1
    return ev


@bi('ordqz', nout=4)
def ordqz(nargout, *args):
    """[AAS, BBS, QS, ZS] = ordqz(AA, BB, Q, Z, select): the QZ form of qz
    reordered so that the selected eigenvalues come first (LAPACK's tgsen),
    QS*A*ZS = AAS and QS*B*ZS = BBS. select is logical, a keyword ('lhp',
    'rhp', 'udi', 'udo': real part below or above zero, inside or outside
    the unit disk), or keys, the clusters then in order of decreasing key."""
    nargchk(args, 5, 5, 'ordqz')
    import scipy.linalg.lapack as L
    AA, BB, Q, Z = (_mat(a, 'ordqz') for a in args[:4])
    n = AA.shape[0]
    if any(m.shape != (n, n) for m in (AA, BB, Q, Z)):
        raise err('MATLAB:ordqz:SizeMismatch', 'AA, BB, Q and Z must be square matrices of one size.', 'ordqz')
    cplx = any(np.iscomplexobj(m) for m in (AA, BB, Q, Z))
    t = C128 if cplx else F64
    AA, BB, Q, Z = (m.astype(t) for m in (AA, BB, Q, Z))
    word = opt_str(args[4])
    if word is not None:
        ev = _pencil_eigs(AA, BB)
        tests = {'lhp': lambda e: e.real < 0, 'rhp': lambda e: e.real > 0, 'udi': lambda e: np.abs(e) < 1, 'udo': lambda e: np.abs(e) > 1}
        if word.lower() not in tests:
            raise err('MATLAB:ordqz:InvalidKeyword', "The keyword is 'lhp', 'rhp', 'udi' or 'udo'.", 'ordqz')
        key = tests[word.lower()](ev)
    else:
        key = np.asarray(arr(args[4])).reshape(-1)
    if key.size != n:
        raise err('MATLAB:ordqz:SelectSize', 'select must have one element per eigenvalue.', 'ordqz')
    fn = L.ztgsen if cplx else L.dtgsen
    levels = [None] if key.dtype == bool else sorted(set(key.tolist()), reverse=True)[:-1][::-1]
    key = key.copy()
    # LAPACK's Q is the transpose of the language's: A = Ql*AA*Z'
    Ql = Q.conj().T
    for lev in levels:
        sel = _schur_select(AA, key if lev is None else key >= lev).astype(bool)
        r = fn(sel.astype(np.int32), AA, BB, Ql, Z, ijob=0)
        AA, BB, Ql, Z, info = r[0], r[1], r[-7], r[-6], r[-1]
        if info != 0:
            raise err('MATLAB:ordqz:Reorder', 'The eigenvalues could not be reordered (they are too close).', 'ordqz')
        key = np.concatenate([key[sel], key[~sel]])
    res = (out(AA), out(BB), out(Ql.conj().T), out(Z))
    return res[0] if nargout <= 1 else res[:nargout]


@bi('rsf2csf', nout=2)
def rsf2csf(nargout, *args):
    """[U, T] = rsf2csf(U, T): a real Schur form (quasi-triangular T, U*T*U' the
    matrix) turned complex, T upper triangular (scipy.linalg.rsf2csf)."""
    nargchk(args, 2, 2, 'rsf2csf')
    import scipy.linalg as sla
    U, T = _mat(args[0], 'rsf2csf'), _mat(args[1], 'rsf2csf')
    n = T.shape[0]
    if T.shape != (n, n) or U.shape != (n, n):
        raise err('MATLAB:rsf2csf:SizeMismatch', 'U and T must be square matrices of one size.', 'rsf2csf')
    if np.iscomplexobj(U) or np.iscomplexobj(T):
        raise err('MATLAB:rsf2csf:NotReal', 'U and T must be real.', 'rsf2csf')
    T2, Z2 = sla.rsf2csf(T, U)
    return (out(Z2), out(T2)) if nargout > 1 else out(Z2)


def _completed(Q):
    """Q (orthonormal columns) with columns added to make it square and unitary."""
    m, k = Q.shape
    if k >= m:
        return Q
    full, _ = np.linalg.qr(np.hstack([Q, np.eye(m, dtype=Q.dtype)]))
    # the added columns: orthogonal to Q's
    rest = full[:, k:m]
    rest = rest - Q @ (Q.conj().T @ rest)
    rest, _ = np.linalg.qr(rest)
    return np.hstack([Q, rest[:, :m - k]])


@bi('gsvd', nout=5)
def gsvd(nargout, *args):
    """[U, V, X, C, S] = gsvd(A, B): A = U*C*X', B = V*S*X', C'*C + S'*S = I,
    U and V unitary; sigma = gsvd(A, B) the generalized singular values
    sqrt(diag(C'*C)./diag(S'*S)), in increasing order. From the QR
    factorization of [A; B] and the CS decomposition of its Q
    (scipy.linalg.cossin); gsvd(A, B, 0) or 'econ' the economy size."""
    nargchk(args, 2, 3, 'gsvd')
    import scipy.linalg as sla
    single = 'single' in (class_of(args[0]), class_of(args[1]))
    A, B = _mat(args[0], 'gsvd'), _mat(args[1], 'gsvd')
    if A.shape[1] != B.shape[1]:
        raise err('MATLAB:gsvd:ColumnMismatch', 'A and B must have the same number of columns.', 'gsvd')
    econ = len(args) > 2
    if econ and not (opt_str(args[2]) == 'econ' or (opt_str(args[2]) is None and numel(args[2]) == 1 and num(args[2]) == 0)):
        raise err('MATLAB:gsvd:InvalidFlag', "The third input is 0 or 'econ'.", 'gsvd')
    m, n = A.shape
    p = B.shape[0]
    t = C128 if (np.iscomplexobj(A) or np.iscomplexobj(B)) else F64
    A, B = A.astype(t), B.astype(t)
    q = min(m + p, n)
    Q, Rm = np.linalg.qr(np.vstack([A, B]), mode='reduced')       # (m+p)-by-q, q-by-n
    if m == 0 or p == 0:
        # one of them empty: the other's part of Q has orthonormal columns, all cosine (or all sine)
        M = Q[:m] if m else Q[m:]
        Uq, sv, Zh = np.linalg.svd(M, full_matrices=True)
        Z = Zh.conj().T
        vals = np.pad(np.round(sv, 15), (0, q - sv.size))
        rows = list(range(sv.size)) + [-1] * (q - sv.size)
        none = np.zeros(q)
        if m:
            U, V, cvals, svals, rows_c, rows_s = Uq, np.zeros((0, 0), t), vals, none, rows, [-1] * q
        else:
            U, V, cvals, svals, rows_c, rows_s = np.zeros((0, 0), t), Uq, none, vals, [-1] * q, rows
    elif q == m + p:
        # Q square: its rows are orthonormal, so Z = [Q2' Q1'] makes Q1*Z = [0 I] and Q2*Z = [I 0]
        Z = np.hstack([Q[m:].conj().T, Q[:m].conj().T])
        U, V = np.eye(m, dtype=t), np.eye(p, dtype=t)
        cvals = np.concatenate([np.zeros(p), np.ones(m)])
        svals = np.concatenate([np.ones(p), np.zeros(m)])
        rows_c = [-1] * p + list(range(m))
        rows_s = list(range(p)) + [-1] * m
    else:
        W = _completed(Q)
        u, cs, vdh = sla.cossin(W, p=m, q=q)
        U, V = u[:m, :m], u[m:, m:]
        Z = vdh[:q, :q].conj().T
        Cp, Sp = cs[:m, :q], cs[m:, :q]
        cvals, svals, rows_c, rows_s = np.zeros(q), np.zeros(q), [], []
        for j in range(q):
            ic = np.flatnonzero(np.abs(Cp[:, j]) > 1e-15)
            js = np.flatnonzero(np.abs(Sp[:, j]) > 1e-15)
            rows_c.append(int(ic[0]) if ic.size else -1)
            rows_s.append(int(js[0]) if js.size else -1)
            cvals[j] = Cp[ic[0], j].real if ic.size else 0.0
            svals[j] = Sp[js[0], j].real if js.size else 0.0
            # each nonzero positive: its sign goes into U's or V's column
            if cvals[j] < 0:
                U[:, rows_c[j]] = -U[:, rows_c[j]]
                cvals[j] = -cvals[j]
            if svals[j] < 0:
                V[:, rows_s[j]] = -V[:, rows_s[j]]
                svals[j] = -svals[j]
    # the order: generalized singular values c/s increasing (all-sine first, all-cosine last)
    with np.errstate(divide='ignore', invalid='ignore'):
        sig = np.where(svals > 0, cvals / np.where(svals > 0, svals, 1), np.inf)
    order = np.argsort(sig, kind='stable')
    k = max(0, q - m)
    Unew = np.zeros((m, m), t)
    Vnew = np.zeros((p, p), t)
    usedU, usedV = set(), set()
    for newj, j in enumerate(order):
        if rows_c[j] >= 0 and cvals[j] > 0:
            Unew[:, newj - k] = U[:, rows_c[j]]
            usedU.add(rows_c[j])
        if rows_s[j] >= 0 and svals[j] > 0:
            Vnew[:, newj] = V[:, rows_s[j]]
            usedV.add(rows_s[j])
    # the columns of U and V that meet only zeros fill the rest, in their order
    fill = [i for i in range(m) if i not in usedU]
    empty = [i for i in range(m) if not np.any(Unew[:, i])]
    for i, src in zip(empty, fill):
        Unew[:, i] = U[:, src]
    fill = [i for i in range(p) if i not in usedV]
    empty = [i for i in range(p) if not np.any(Vnew[:, i])]
    for i, src in zip(empty, fill):
        Vnew[:, i] = V[:, src]
    C = np.zeros((m, q))
    S = np.zeros((p, q))
    for newj, j in enumerate(order):
        if cvals[j] > 0:
            C[newj - k, newj] = cvals[j]
        if svals[j] > 0:
            S[newj, newj] = svals[j]
    Z = Z[:, order]
    X = Rm.conj().T @ Z                                              # A = U*C*X', X' = Z'*R
    if nargout <= 1:
        with np.errstate(divide='ignore', invalid='ignore'):
            sigma = np.sort(np.where(svals > 0, cvals / np.where(svals > 0, svals, 1), np.inf))
        return finish(sigma.reshape(-1, 1), 'single') if single else out(sigma.reshape(-1, 1))
    if econ:
        Unew, C = Unew[:, :min(m, q)], C[:min(m, q), :]
        Vnew, S = Vnew[:, :min(p, q)], S[:min(p, q), :]
    fin = (lambda r: finish(np.asarray(r), 'single')) if single else out
    return tuple(fin(r) for r in (Unew, Vnew, X, C, S))[:nargout]


@bi('ordeig')
def ordeig(nargout, *args):
    """The eigenvalues of a (quasi-)triangular T in the order they stand on its
    diagonal (a real 2-by-2 block giving its pair), or of a pencil AA, BB."""
    nargchk(args, 1, 2, 'ordeig')
    T = _mat(args[0], 'ordeig')
    B = _mat(args[1], 'ordeig') if len(args) > 1 else None
    if T.shape[0] != T.shape[1] or (B is not None and B.shape != T.shape):
        raise err('MATLAB:ordeig:SizeMismatch', 'The matrices must be square and of the same size.', 'ordeig')
    n = T.shape[0]
    ev, k = [], 0
    while k < n:
        if k < n - 1 and not np.iscomplexobj(T) and T[k + 1, k] != 0:
            blk = T[k:k + 2, k:k + 2]
            if B is not None:
                from scipy.linalg import eigvals
                pair = eigvals(blk, B[k:k + 2, k:k + 2])
            else:
                pair = np.linalg.eigvals(blk)
            pair = sorted(pair, key=lambda z: -z.imag)
            ev += list(pair)
            k += 2
        else:
            with np.errstate(all='ignore'):
                ev.append(T[k, k] / B[k, k] if B is not None else T[k, k])
            k += 1
    return out(np.array(ev).reshape(-1, 1))


@bi('polyeig', nout=3)
def polyeig(nargout, *args):
    """[X, e] = polyeig(A0, A1, ..., Ap): the eigenvalues of the matrix
    polynomial (A0 + e*A1 + ... + e^p*Ap) x = 0 from the companion pencil
    (scipy.linalg.eig), with the eigenvectors as unit columns; s, the third
    output, the eigenvalues' condition numbers."""
    nargchk(args, 1, None, 'polyeig')
    from scipy.linalg import eig as _eig
    As = [_mat(a, 'polyeig') for a in args]
    n = As[0].shape[0]
    if any(a.shape != (n, n) for a in As):
        raise err('MATLAB:polyeig:SizeMismatch', 'The matrices must be square and of one size.', 'polyeig')
    p = len(As) - 1
    t = C128 if any(np.iscomplexobj(a) for a in As) else F64
    if p == 0:
        e = np.zeros((0, 1))
        return out(e) if nargout <= 1 else (np.zeros((n, 0)), out(e), np.zeros((0, 1)))[:nargout]
    N = n * p
    Abig = np.zeros((N, N), t)
    Bbig = np.eye(N, dtype=t)
    Abig[:N - n, n:] = np.eye(N - n)
    for k in range(p):
        Abig[N - n:, k * n:(k + 1) * n] = -As[k]
    Bbig[N - n:, N - n:] = As[p]
    w, vl, vr = _eig(Abig, Bbig, left=True, right=True)
    X = vr[:n, :]
    X = X / np.where(np.linalg.norm(X, axis=0) == 0, 1, np.linalg.norm(X, axis=0))
    if nargout <= 1:
        return out(w.reshape(-1, 1))
    res = [out(X), out(w.reshape(-1, 1))]
    if nargout > 2:
        # relative condition numbers: (sum |e|^k ||A_k||) ||x|| ||y|| / (|e| |y' P'(e) x|)
        Y = vl[N - n:, :]
        s = np.empty(w.size)
        norms = [np.linalg.norm(a, 2) for a in As]
        for j, lam in enumerate(w):
            x, y = X[:, j], Y[:, j]
            if not np.isfinite(lam):
                s[j] = np.inf
                continue
            dP = sum(k * lam ** (k - 1) * As[k] for k in range(1, p + 1))
            num_ = sum(abs(lam) ** k * norms[k] for k in range(p + 1)) * np.linalg.norm(x) * np.linalg.norm(y)
            den = abs(lam) * abs(y.conj() @ dP @ x)
            s[j] = num_ / den if den else np.inf
        res.append(out(s.reshape(-1, 1)))
    return tuple(res[:nargout])


# ---- pages and tensors ----------------------------------------------------------------------------------

def _trim(shape):
    """A shape without its trailing ones (kept at least 2-D)."""
    s = list(shape)
    while len(s) > 2 and s[-1] == 1:
        s.pop()
    return tuple(s)


def _pages(a, tr):
    """a with its pages first and each page (dims 1 and 2) last, turned as asked."""
    a = np.asarray(a)
    a = a.reshape(a.shape + (1,) * (2 - a.ndim)) if a.ndim < 2 else a
    p = np.moveaxis(a, (0, 1), (-2, -1))
    if tr in ('transpose', 'ctranspose'):
        p = np.swapaxes(p, -1, -2)
        if tr == 'ctranspose':
            p = np.conj(p)
    return p


def _unpage(p):
    return np.moveaxis(p, (-2, -1), (0, 1))


@bi('pagemtimes')
def pagemtimes(nargout, *args):
    """pagemtimes(X, Y), pagemtimes(X, transpX, Y, transpY): each page (the
    first two dimensions) of X times the matching page of Y; pages of size 1
    are used against all of the other's."""
    nargchk(args, 2, 4, 'pagemtimes')
    if len(args) == 4:
        X, tx, Y, ty = args[0], opt_lower(args[1], 'pagemtimes'), args[2], opt_lower(args[3], 'pagemtimes')
    elif len(args) == 2:
        X, tx, Y, ty = args[0], 'none', args[1], 'none'
    else:
        raise err('MATLAB:minrhs', 'pagemtimes takes X and Y, or X, transpX, Y and transpY.', 'pagemtimes')
    for t in (tx, ty):
        if t not in ('none', 'transpose', 'ctranspose'):
            raise err('MATLAB:pagemtimes:transpose', "The transposition must be 'none', 'transpose' or 'ctranspose'.", 'pagemtimes')
    A, B = _pages(darr(X, 'pagemtimes'), tx), _pages(darr(Y, 'pagemtimes'), ty)
    if A.shape[-1] != B.shape[-2]:
        raise err('MATLAB:innerdim', f'The pages do not fit: {A.shape[-2]}x{A.shape[-1]} times {B.shape[-2]}x{B.shape[-1]}.', 'pagemtimes')
    n = max(A.ndim, B.ndim)
    A = A.reshape((1,) * (n - A.ndim) + A.shape)
    B = B.reshape((1,) * (n - B.ndim) + B.shape)
    try:
        r = np.matmul(A, B)
    except ValueError:
        raise err('MATLAB:sizeDimensionsMustMatch', 'The pages of X and Y must be as many in each dimension, or 1.', 'pagemtimes')
    r = _unpage(r)
    return out(r.reshape(_trim(r.shape)))


def _page_turn(a):
    nd = len(shape_of(a))
    return R._builtin('permute', a, np.array([[2.0, 1.0] + [float(k) for k in range(3, nd + 1)]]))


@bi('pagetranspose')
def pagetranspose(nargout, *args):
    """Each page (the first two dimensions) turned: permute(A, [2 1 3 ...])."""
    nargchk(args, 1, 1, 'pagetranspose')
    return _page_turn(args[0])


@bi('pagectranspose')
def pagectranspose(nargout, *args):
    """Each page turned, its complex numbers conjugated."""
    nargchk(args, 1, 1, 'pagectranspose')
    return R._builtin('conj', _page_turn(args[0]))


@bi('tensorprod')
def tensorprod(nargout, *args):
    """tensorprod(A, B) (outer product), tensorprod(A, B, dims), tensorprod(A,
    B, dimA, dimB) (sums over those dimensions, numbered from 1) and
    tensorprod(A, B, 'all') (over all of them). The result has A's other
    dimensions, then B's."""
    nargchk(args, 2, 4, 'tensorprod')
    A, B = darr(args[0], 'tensorprod'), darr(args[1], 'tensorprod')
    if len(args) == 3 and is_str(args[2]):
        if opt_lower(args[2], 'tensorprod') != 'all':
            raise err('MATLAB:tensorprod:option', "The third input is the dimensions to sum over, or 'all'.", 'tensorprod')
        if _trim(A.shape) != _trim(B.shape):
            raise err('MATLAB:tensorprod:sizeMismatch', "With 'all', A and B must be the same size.", 'tensorprod')
        return out(np.sum(A * B))
    if len(args) == 2:
        da = db = ()
    else:
        da = tuple(int(x) for x in arr(args[2]).reshape(-1))
        db = tuple(int(x) for x in arr(args[3]).reshape(-1)) if len(args) == 4 else da
    if len(da) != len(db):
        raise err('MATLAB:tensorprod:dims', 'As many dimensions of A as of B are summed over.', 'tensorprod')
    na = max(A.ndim, max(da, default=0))
    nb = max(B.ndim, max(db, default=0))
    A = A.reshape(A.shape + (1,) * (na - A.ndim))
    B = B.reshape(B.shape + (1,) * (nb - B.ndim))
    for x, y in zip(da, db):
        if A.shape[x - 1] != B.shape[y - 1]:
            raise err('MATLAB:tensorprod:sizeMismatch', f'Dimension {x} of A ({A.shape[x - 1]}) and {y} of B ({B.shape[y - 1]}) must be as long.', 'tensorprod')
    if not da:
        # the outer product: A's dimensions without its trailing ones, then B's
        A = A.reshape(_trim(A.shape))
        r = np.tensordot(A, B, axes=0)
    else:
        r = np.tensordot(A, B, axes=([x - 1 for x in da], [y - 1 for y in db]))
    if r.ndim == 0:
        return out(r)
    if r.ndim == 1:
        r = r.reshape(-1, 1)
    return out(r.reshape(_trim(r.shape)))
