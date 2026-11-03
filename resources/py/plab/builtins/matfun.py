"""Linear algebra: inverses and determinants, decompositions, norms,
subspaces, matrix functions; and the operators as named functions (plus,
mtimes and the rest)."""
import math

import numpy as np

from . import bi
from ._util import (err, nargchk, noout, maxout, arr, darr, out, opt_str, sval, ival, num, is_str, bool_out,
                    like_class, first_dim, dim_arg, reduce, expand_dims, strip_flags)
from ..ops import finish
from ..values import (MError, Char, Cell, Struct, F64, C128, class_of, shape_of, numel, _2d, EMPTY)
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
    if a.size == 0:
        return out(a.copy())
    if not np.all(np.isfinite(a)):
        R.warn('MATLAB:illConditionedMatrix', 'Matrix is singular, close to singular or badly scaled. Results may be inaccurate. RCOND = NaN.')
        return out(np.full(a.shape, np.nan))
    rc, lu, piv = _rcond(a)
    if lu is not None and np.any(np.diag(lu) == 0):
        R.warn('MATLAB:singularMatrix', 'Matrix is singular to working precision.')
        return out(np.full(a.shape, np.inf))
    with np.errstate(all='ignore'):
        r = np.linalg.inv(a)
    if rc < np.finfo(float).eps:
        R.warn('MATLAB:nearlySingularMatrix', f'Matrix is close to singular or badly scaled. Results may be inaccurate. RCOND =  {rc:.6e}.')
    return like_class(r, args[0]) if class_of(args[0]) == 'single' else out(r)


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
    words = [opt_str(r).lower() if opt_str(r) is not None else 'zero' for r in rest]
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
    kind = opt_str(args[1]) if len(args) > 1 else ('complex' if np.iscomplexobj(a) else 'real')
    T, Z = sla.schur(a, output=kind)
    return (out(Z), out(T)) if nargout >= 2 else out(T)


@bi('hess', nout=2)
def hess(nargout, *args):
    import scipy.linalg as sla
    a = _mat(args[0], 'hess')
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
    f = args[1]
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
    return out(np.sum(np.conj(a) * b, axis=dim, keepdims=True))


@bi('linsolve', nout=2)
def linsolve(nargout, *args):
    x = O.mldivide(args[0], args[1])
    if nargout >= 2:
        a = _mat(args[0], 'linsolve')
        rc = _rcond(a)[0] if a.shape[0] == a.shape[1] else float(np.linalg.matrix_rank(a))
        return x, rc
    return x


@bi('balance', nout=2)
def balance(nargout, *args):
    import scipy.linalg as sla
    a = _mat(args[0], 'balance')
    B, T = sla.matrix_balance(a)
    return (out(T), out(B)) if nargout >= 2 else out(B)


@bi('givens')
def givens(nargout, *args):
    x, y = num(args[0]), num(args[1])
    r = math.hypot(x, y)
    if r == 0:
        return out(np.eye(2))
    c, s = x / r, y / r
    return out(np.array([[c, s], [-s, c]]))


@bi('planerot', nout=2)
def planerot(nargout, *args):
    x = darr(args[0]).reshape(-1)
    G = darr(givens(1, x[0], x[1]))
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
