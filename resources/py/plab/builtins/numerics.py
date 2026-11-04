"""Numerical functions of the language's core: uniquetol and ismembertol,
lsqminnorm, decomposition objects, sylvester, lscov, normest1, subspace,
condeig, cdf2rdf, hadamard, griddatan, delaunayn, convhulln, nufft and
nufftn, colperm, symbfact, rmse and mape."""
import math

import numpy as np

from . import bi as _register
from ._util import err, nargchk, out, num, opt_str, opt_lower, is_str, darr, arr
from ..values import MError, Char, Cell, Struct, Str, Obj, Sparse, numel, py_str, EMPTY, F64, C128
from .. import runtime as R


def bi(*names, **kw):
    """Register, with Python's own errors given as the language's."""
    def deco(fn):
        def wrapped(*a):
            try:
                return fn(*a)
            except MError:
                raise
            except np.linalg.LinAlgError as e:
                raise err(f'MATLAB:{names[0]}:LinAlgError', str(e), names[0]) from None
            except (ValueError, TypeError, IndexError, KeyError, OverflowError, ZeroDivisionError) as e:
                raise err(f'MATLAB:{names[0]}:InvalidInput', str(e) or 'The input is not valid.', names[0]) from None
        wrapped.__name__ = fn.__name__
        wrapped.__doc__ = fn.__doc__
        return _register(*names, **kw)(wrapped)
    return deco


def _outs(nargout, *vals):
    return vals[:max(nargout, 1)] if nargout > 1 else vals[0]


def _dense(v, fn, what='A'):
    if isinstance(v, Sparse):
        return np.asarray(v.m.toarray())
    if isinstance(v, (Cell, Struct, Char, Str)) or isinstance(v, Obj):
        raise err(f'MATLAB:{fn}:InvalidInput', f'{what} is a numeric array.', fn)
    a = np.asarray(arr(v, fn))
    if a.dtype == bool:
        a = a.astype(F64)
    if a.dtype.kind not in 'fc':
        a = a.astype(F64)
    return a


def _mat2(v, fn, what='A'):
    a = _dense(v, fn, what)
    if a.ndim != 2:
        raise err(f'MATLAB:{fn}:InvalidInput', f'{what} is a matrix.', fn)
    return a


def _opts(rest, fn, names):
    """Name-value options (names lowercase) into a dict."""
    if len(rest) % 2:
        raise err(f'MATLAB:{fn}:nargin', 'The options come as names and values.', fn)
    o = {}
    for i in range(0, len(rest), 2):
        k = opt_lower(rest[i])
        if k is None:
            raise err(f'MATLAB:{fn}:BadOption', 'Each option is named by text.', fn)
        match = [n for n in names if n.lower() == k]
        if not match:
            raise err(f'MATLAB:{fn}:BadOption', f"'{py_str(rest[i])}' is not an option of {fn}. The options are {', '.join(names)}.", fn)
        o[match[0]] = rest[i + 1]
    return o


def _tf(v):
    return bool(np.all(np.asarray(darr(v)) != 0)) if not is_str(v) else opt_lower(v) in ('on', 'true')


# ---- equal within a tolerance ---------------------------------------------------------------------------------------

def _tol_and_rest(args, k, single, default_d, default_s, fn):
    rest = list(args[k:])
    tol = default_s if single else default_d
    if rest and not is_str(rest[0]):
        tol = float(num(rest.pop(0)))
        if not tol >= 0:
            raise err(f'MATLAB:{fn}:InvalidTol', 'The tolerance is a number from 0.', fn)
    return tol, rest


def _finite_max(*arrays, axis=None):
    """The largest finite magnitude: of everything, or of each column (axis 0)."""
    a = np.concatenate([np.abs(x).reshape(-1, x.shape[-1]) if axis == 0 else np.abs(x).reshape(-1) for x in arrays], axis=0)
    a = np.where(np.isfinite(a), a, 0)
    if axis == 0:
        return a.max(axis=0) if a.shape[0] else np.zeros(a.shape[1])
    return float(a.max()) if a.size else 0.0


@bi('uniquetol', nout=3, arr=False)
def uniquetol(nargout, *args):
    """[C, IA, IC] = uniquetol(A, tol, ...): the values of A, sorted, those
    within tol*DataScale of one kept (the smallest of each group); A ≈ C(IC)
    and C = A(IA). DataScale is max(abs(A(:))) (each column's for 'ByRows').
    tol is 1e-6 (1e-4 for single). Options ByRows, OutputAllIndices,
    DataScale."""
    nargchk(args, 1, 8, 'uniquetol')
    A0 = args[0]
    a = _dense(A0, 'uniquetol')
    if np.iscomplexobj(a):
        raise err('MATLAB:uniquetol:Complex', 'A is real.', 'uniquetol')
    single = a.dtype == np.float32
    tol, rest = _tol_and_rest(args, 1, single, 1e-6, 1e-4, 'uniquetol')
    o = _opts(rest, 'uniquetol', ('ByRows', 'OutputAllIndices', 'DataScale'))
    rows = _tf(o['ByRows']) if 'ByRows' in o else False
    allidx = _tf(o['OutputAllIndices']) if 'OutputAllIndices' in o else False
    x = a.astype(F64)
    if rows:
        if x.ndim != 2:
            raise err('MATLAB:uniquetol:ByRows', "'ByRows' takes a matrix.", 'uniquetol')
        ds = np.asarray(darr(o['DataScale']), F64).reshape(-1) if 'DataScale' in o else _finite_max(x, axis=0)
        ds = np.broadcast_to(ds, (x.shape[1],))
        order = np.lexsort(x.T[::-1]) if x.shape[0] else np.zeros(0, int)
        reps, groups = [], np.zeros(x.shape[0], int)
        members = []
        for i in order:
            r = x[i]
            hit = None
            for g in range(len(reps) - 1, -1, -1):
                if np.all(np.abs(r - x[reps[g]]) <= tol * ds):
                    hit = g
                    break
            if hit is None:
                reps.append(i)
                members.append([i])
                groups[i] = len(reps) - 1
            else:
                members[hit].append(i)
                groups[i] = hit
        C = a[np.array(reps, int)] if reps else a[:0]
        IA = np.array(reps, F64).reshape(-1, 1) + 1
    else:
        v = x.reshape(-1, order='F')
        ds = float(num(o['DataScale'])) if 'DataScale' in o else _finite_max(v)
        order = np.argsort(v, kind='stable')
        reps, members = [], []
        groups = np.zeros(v.size, int)
        last = None
        for i in order:
            if last is not None and not np.isnan(v[i]) and abs(v[i] - v[last]) <= tol * ds:
                members[-1].append(i)
            else:
                reps.append(i)
                members.append([i])
                last = i
            groups[i] = len(reps) - 1
        vals = a.reshape(-1, order='F')[np.array(reps, int)] if reps else a.reshape(-1)[:0]
        row = a.ndim == 2 and a.shape[0] == 1 and a.shape[1] > 0
        C = vals.reshape(1, -1) if row else vals.reshape(-1, 1)
        IA = np.array(reps, F64).reshape(-1, 1) + 1
    IC = (groups.astype(F64) + 1).reshape(-1, 1)
    if allidx:
        IA = Cell.of_list([np.sort(np.array(m, F64) + 1).reshape(-1, 1) for m in members], (len(members), 1)) if members else Cell.empty((0, 1))
    return _outs(nargout, out(C), IA if allidx else out(IA), out(IC))


@bi('ismembertol', nout=2, arr=False)
def ismembertol(nargout, *args):
    """[LIA, LocB] = ismembertol(A, B, tol, ...): whether each value of A is
    within tol*DataScale of a value of B, and the lowest index of such a value
    (0 when none). DataScale is max(abs([A(:); B(:)])); tol is 1e-12 (1e-6 for
    single). Options ByRows, OutputAllIndices, DataScale."""
    nargchk(args, 2, 9, 'ismembertol')
    a = _dense(args[0], 'ismembertol', 'A')
    b = _dense(args[1], 'ismembertol', 'B')
    if np.iscomplexobj(a) or np.iscomplexobj(b):
        raise err('MATLAB:ismembertol:Complex', 'A and B are real.', 'ismembertol')
    single = a.dtype == np.float32 or b.dtype == np.float32
    tol, rest = _tol_and_rest(args, 2, single, 1e-12, 1e-6, 'ismembertol')
    o = _opts(rest, 'ismembertol', ('ByRows', 'OutputAllIndices', 'DataScale'))
    rows = _tf(o['ByRows']) if 'ByRows' in o else False
    allidx = _tf(o['OutputAllIndices']) if 'OutputAllIndices' in o else False
    x, y = a.astype(F64), b.astype(F64)
    if rows:
        if x.ndim != 2 or y.ndim != 2 or x.shape[1] != y.shape[1]:
            raise err('MATLAB:ismembertol:ByRows', "With 'ByRows' A and B have as many columns.", 'ismembertol')
        ds = np.asarray(darr(o['DataScale']), F64).reshape(-1) if 'DataScale' in o else _finite_max(np.vstack([x, y]), axis=0)
        ds = np.broadcast_to(ds, (x.shape[1],))
        near = np.all(np.abs(x[:, None, :] - y[None, :, :]) <= tol * ds, axis=2) if x.size and y.size else np.zeros((x.shape[0], y.shape[0]), bool)
        shape = (x.shape[0], 1)
    else:
        xv, yv = x.reshape(-1, order='F'), y.reshape(-1, order='F')
        ds = float(num(o['DataScale'])) if 'DataScale' in o else _finite_max(xv, yv)
        T = tol * ds
        near = np.zeros((xv.size, yv.size), bool)
        if xv.size and yv.size:
            order = np.argsort(yv, kind='stable')
            ys = yv[order]
            lo = np.searchsorted(ys, xv - T, side='left')
            hi = np.searchsorted(ys, xv + T, side='right')
            for i in range(xv.size):
                if hi[i] > lo[i]:
                    near[i, order[lo[i]:hi[i]]] = True
        shape = a.shape
    lia = near.any(axis=1)
    loc = np.where(lia, np.argmax(near, axis=1) + 1, 0).astype(F64)
    LIA = lia.reshape(shape, order='F')
    if allidx:
        cells = [np.nonzero(near[i])[0].astype(F64).reshape(-1, 1) + 1 if lia[i] else np.zeros((1, 1)) for i in range(near.shape[0])]
        Loc = Cell.of_list(cells, shape)
    else:
        Loc = out(loc.reshape(shape, order='F'))
    return _outs(nargout, LIA, Loc)


# ---- least squares and factorizations --------------------------------------------------------------------------

def _cod(A, tol=None):
    """A complete orthogonal decomposition A*P = Q*[T 0; 0 0]*Z': (Q_r, T, Z, perm, r, tol)."""
    import scipy.linalg as sla
    m, n = A.shape
    if A.size == 0:
        return np.zeros((m, 0), A.dtype), np.zeros((0, 0), A.dtype), np.zeros((n, 0), A.dtype), np.arange(n), 0, 0.0
    Q, Rr, P = sla.qr(A, mode='economic', pivoting=True)
    d = np.abs(np.diag(Rr))
    if tol is None:
        tol = max(m, n) * np.spacing(d[0]) if d.size and d[0] > 0 else 0.0
    r = int(np.sum(d > tol))
    R1 = Rr[:r, :]                                   # r x n, upper trapezoidal
    Z, T = np.linalg.qr(R1.conj().T)                 # R1' = Z*T: n x r and r x r
    return Q[:, :r], T, Z, P, r, tol


def _cod_solve(dec, B):
    Qr, T, Z, P, r, _ = dec
    n = P.size
    if r == 0:
        return np.zeros((n, B.shape[1]), np.result_type(Qr, B))
    import scipy.linalg as sla
    y = sla.solve_triangular(T.conj().T, Qr.conj().T @ B, lower=True)
    xp = Z @ y
    x = np.zeros((n, B.shape[1]), xp.dtype)
    x[P] = xp
    return x


@bi('lsqminnorm', arr=False)
def lsqminnorm(nargout, *args):
    """X = lsqminnorm(A, B, tol, 'warn'/'nowarn'): the least-squares solution
    of A*X = B with the smallest norm, through a complete orthogonal
    decomposition (QR with column pivoting, the rank where |R(k,k)| > tol;
    tol = max(size(A))*eps(|R(1,1)|) by default). 'warn' warns when A is
    rank deficient. 'RegularizationFactor', lambda solves the problem with
    lambda^2*norm(X)^2 added instead."""
    nargchk(args, 2, 6, 'lsqminnorm')
    A = _mat2(args[0], 'lsqminnorm', 'A')
    B = _dense(args[1], 'lsqminnorm', 'B')
    vec = B.ndim == 1
    B = B.reshape(-1, 1) if B.ndim == 1 else B
    if B.shape[0] != A.shape[0]:
        raise err('MATLAB:lsqminnorm:SizeMismatch', 'A and B have as many rows.', 'lsqminnorm')
    tol, warn, lam = None, True, None
    rest = list(args[2:])
    i = 0
    while i < len(rest):
        s = opt_lower(rest[i])
        if s is None:
            if numel(rest[i]):
                tol = float(num(rest[i]))
            i += 1
        elif s in ('warn', 'nowarn'):
            warn = s == 'warn'
            i += 1
        elif s == 'regularizationfactor' and i + 1 < len(rest):
            lam = float(num(rest[i + 1]))
            i += 2
        else:
            raise err('MATLAB:lsqminnorm:BadOption', f"'{py_str(rest[i])}' is not an option of lsqminnorm.", 'lsqminnorm')
    if lam:
        n = A.shape[1]
        Aa = np.vstack([A, lam * np.eye(n)])
        Ba = np.vstack([B, np.zeros((n, B.shape[1]), B.dtype)])
        A, B = Aa, Ba
    dec = _cod(A, tol)
    if warn and dec[4] < min(A.shape):
        R.warn('MATLAB:rankDeficientMatrix', f'Rank deficient, rank = {dec[4]}, tol = {dec[5]:.6e}.')
    X = _cod_solve(dec, B)
    if np.isrealobj(A) and np.isrealobj(B):
        X = X.real
    if _dense(args[0], 'lsqminnorm').dtype == np.float32 or B.dtype == np.float32:
        X = X.astype(np.float32)
    return out(X)


class Decomposition(Obj):
    """A matrix factored once, to solve with \\ and / many times."""
    cls = 'decomposition'
    is_handle = False

    def __init__(self, A, kind, check=True, ranktol=None, lower=None, upper=None):
        import scipy.linalg as sla
        self.A = A
        self.check = check
        self.ct = False
        self.sparse = False
        m, n = A.shape
        self.size = (m, n)
        if kind == 'auto':
            kind = self._choose(A)
        self.kind = kind
        self.rcond_ = None
        if kind in ('lu', 'banded'):
            self._need_square()
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')          # a singular matrix is found by rcond and warned of when solving
                self.f = sla.lu_factor(A, check_finite=False)
        elif kind == 'chol':
            self._need_square()
            try:
                self.f = sla.cho_factor(A, lower=False, check_finite=False)
            except np.linalg.LinAlgError:
                raise err('MATLAB:decomposition:NotPositiveDefinite', 'The matrix is not positive definite, so chol cannot factor it.', 'decomposition') from None
        elif kind == 'ldl':
            self._need_square()
            lu, d, perm = sla.ldl(A, lower=True, hermitian=np.iscomplexobj(A))
            self.f = (lu, d, perm)
        elif kind == 'hermitian':
            self._need_square()
            try:
                self.f = sla.cho_factor(A, lower=False, check_finite=False)
                self.kind_used = 'chol'
            except np.linalg.LinAlgError:
                lu, d, perm = sla.ldl(A, lower=True, hermitian=True)
                self.f = (lu, d, perm)
                self.kind_used = 'ldl'
        elif kind in ('triangular', 'permutedTriangular'):
            self._need_square()
            if lower is None:
                lower = bool(np.allclose(np.triu(A, 1), 0)) and not np.allclose(np.tril(A, -1), 0)
            self.lower = lower
        elif kind == 'diagonal':
            self._need_square()
        elif kind == 'qr':
            self.f = np.linalg.qr(A, mode='reduced') if m >= n else None
            if m < n:
                self.kind = 'cod'
                self.f = _cod(A, ranktol)
        elif kind == 'cod':
            self.f = _cod(A, ranktol)
        else:
            raise err('MATLAB:decomposition:BadType', f"'{kind}' is not a type of decomposition: auto, banded, chol, cod, diagonal, hermitian, ldl, lu, permutedTriangular, qr or triangular.", 'decomposition')

    def _need_square(self):
        if self.size[0] != self.size[1]:
            raise err('MATLAB:decomposition:NotSquare', f"A '{self.kind}' decomposition needs a square matrix.", 'decomposition')

    @staticmethod
    def _choose(A):
        m, n = A.shape
        if m != n:
            return 'qr'
        if np.allclose(A, np.diag(np.diag(A))):
            return 'diagonal'
        if np.allclose(np.tril(A, -1), 0) or np.allclose(np.triu(A, 1), 0):
            return 'triangular'
        if np.allclose(A, A.conj().T) and np.all(np.real(np.diag(A)) > 0):
            import scipy.linalg as sla
            try:
                sla.cholesky(A, check_finite=False)
                return 'chol'
            except np.linalg.LinAlgError:
                return 'ldl'
        return 'lu'

    def value_copy(self):
        return self

    @property
    def shape(self):
        return (1, 1)

    def rcond(self):
        if self.rcond_ is None:
            A = self.A
            if A.shape[0] != A.shape[1] or A.size == 0:
                self.rcond_ = float('nan')
            else:
                try:
                    Ai = np.linalg.inv(A)
                    self.rcond_ = float(1.0 / (np.linalg.norm(A, 1) * np.linalg.norm(Ai, 1)))
                except np.linalg.LinAlgError:
                    self.rcond_ = 0.0
        return self.rcond_

    def ill(self):
        if self.kind == 'cod':
            return self.f[4] < min(self.size)
        if self.kind == 'qr':
            R_ = self.f[1]
            d = np.abs(np.diag(R_))
            return bool(d.size and d.min() <= np.spacing(1.0) * d.max())
        return self.rcond() < np.spacing(1.0)

    def solve(self, B, transposed):
        """A\\B, or A'\\B when transposed."""
        import scipy.linalg as sla
        A, k = self.A, self.kind
        if self.check and self.ill():
            if k in ('cod',):
                pass
            elif k == 'qr':
                R.warn('MATLAB:rankDeficientMatrix', 'Rank deficient, rank = %d.' % int(np.sum(np.abs(np.diag(self.f[1])) > np.spacing(1.0) * np.abs(self.f[1]).max())))
            else:
                R.warn('MATLAB:nearlySingularMatrix', f'Matrix is close to singular or badly scaled. Results may be inaccurate. RCOND = {self.rcond():.6e}.')
        trans = 'C' if np.iscomplexobj(A) else 'T'
        if k in ('lu', 'banded'):
            return sla.lu_solve(self.f, B, trans=2 if transposed else 0, check_finite=False)
        if k == 'chol' or (k == 'hermitian' and getattr(self, 'kind_used', '') == 'chol'):
            return sla.cho_solve(self.f, B, check_finite=False)       # A' = A
        if k in ('ldl', 'hermitian'):
            # A = L*D*L' with L = lu, lower triangular once its rows are put in perm's order; A' = A
            lu, d, perm = self.f
            Lt = lu[perm]
            y = sla.solve_triangular(Lt, B[perm], lower=True, unit_diagonal=True, check_finite=False)
            z = np.linalg.solve(d, y)
            w = sla.solve_triangular(Lt.conj().T, z, lower=False, unit_diagonal=True, check_finite=False)
            x = np.empty_like(w)
            x[perm] = w
            return x
        if k in ('triangular', 'permutedTriangular'):
            if k == 'permutedTriangular':
                return np.linalg.solve(A.conj().T if transposed else A, B)
            return sla.solve_triangular(A, B, lower=self.lower, trans=trans if transposed else 'N', check_finite=False)
        if k == 'diagonal':
            d = np.diag(A)
            d = d.conj() if transposed else d
            with np.errstate(divide='ignore', invalid='ignore'):
                return B / d[:, None]
        if k == 'qr':
            if transposed:
                return _cod_solve(_cod(A.conj().T), B)
            Q, R_ = self.f
            return sla.solve_triangular(R_, Q.conj().T @ B, check_finite=False)
        if k == 'cod':
            return _cod_solve(_cod(A.conj().T) if transposed else self.f, B)
        raise err('MATLAB:decomposition:BadType', 'Unknown decomposition.', 'decomposition')

    def mldivide(self, B):
        B = _dense(B, 'mldivide', 'B')
        vec = B.ndim == 1
        Bm = B.reshape(-1, 1) if vec else B
        rows = self.size[1] if self.ct else self.size[0]
        if Bm.shape[0] != rows:
            raise err('MATLAB:dimagree', 'Matrix dimensions must agree.', 'mldivide')
        X = self.solve(Bm, self.ct)
        if np.isrealobj(self.A) and np.isrealobj(Bm):
            X = np.real(X)
        return out(X)

    def mrdivide(self, B):
        # B / dA = (dA' \ B')'
        B = _dense(B, 'mrdivide', 'B')
        Bm = B.reshape(1, -1) if B.ndim == 1 else B
        cols = self.size[0] if self.ct else self.size[1]
        if Bm.shape[1] != cols:
            raise err('MATLAB:dimagree', 'Matrix dimensions must agree.', 'mrdivide')
        X = self.solve(Bm.conj().T, not self.ct).conj().T
        if np.isrealobj(self.A) and np.isrealobj(Bm):
            X = np.real(X)
        return out(X)

    def getprop(self, name):
        k = name.lower()
        m, n = self.size
        if k == 'matrixsize':
            return np.array([[float(n), float(m)]]) if self.ct else np.array([[float(m), float(n)]])
        if k == 'type':
            return Char.of(self.kind)
        if k == 'isconjugatetransposed':
            return self.ct
        if k == 'issparse':
            return self.sparse
        if k == 'checkcondition':
            return self.check
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class 'decomposition'.")

    def setprop(self, name, value):
        raise MError('MATLAB:class:SetProhibited', f"You cannot set the read-only property '{name}' of decomposition.")

    def propnames(self):
        return ['MatrixSize', 'Type', 'IsConjugateTransposed', 'IsSparse', 'CheckCondition']

    def display_lines(self):
        m, n = self.size
        if self.ct:
            m, n = n, m
        return ['  decomposition with properties:', '', f'    MatrixSize: [{m} {n}]', f"          Type: '{self.kind}'",
                '', '  Show all properties']

    def transposed(self):
        import copy
        d = copy.copy(self)
        d.ct = not self.ct
        return d


def _decomp_ops(op, *xs):
    if op == 'mldivide' and isinstance(xs[0], Decomposition):
        return xs[0].mldivide(xs[1])
    if op == 'mrdivide' and isinstance(xs[1], Decomposition):
        return xs[1].mrdivide(xs[0])
    if op == 'ctranspose' and len(xs) == 1:
        return xs[0].transposed()
    if op == 'transpose' and len(xs) == 1:
        if np.iscomplexobj(xs[0].A):
            raise err('MATLAB:decomposition:transpose', "A complex decomposition is transposed with ' (its conjugate transpose).", 'decomposition')
        return xs[0].transposed()
    raise err('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for decomposition objects; solve with \\ and /.", 'decomposition')


def _install_ops():
    from .. import ops
    ops.OBJ_OPS[Decomposition] = _decomp_ops


_install_ops()


@bi('decomposition', arr=False)
def decomposition(nargout, *args):
    """dA = decomposition(A, type, ...): A factored once (type 'auto' picks:
    diagonal, triangular, chol, ldl or lu for square A, qr otherwise; or
    'lu', 'qr', 'chol', 'ldl', 'cod', 'triangular', 'permutedTriangular',
    'banded', 'diagonal', 'hermitian'); then dA\\b and b/dA solve with it,
    dA' is A'. 'CheckCondition' (true) warns of an ill-conditioned A,
    'RankTolerance' sets cod's rank, 'upper'/'lower' a triangle."""
    nargchk(args, 1, 8, 'decomposition')
    A = _mat2(args[0], 'decomposition', 'A')
    if A.dtype == np.float32:
        A = A.astype(F64)
    rest = list(args[1:])
    kind = 'auto'
    if rest and is_str(rest[0]) and (opt_str(rest[0]) or '') in ('auto', 'banded', 'chol', 'cod', 'diagonal', 'hermitian', 'ldl', 'lu',
                                                              'permutedTriangular', 'qr', 'triangular'):
        kind = opt_str(rest.pop(0))
    lower = None
    if rest and opt_lower(rest[0]) in ('upper', 'lower'):
        lower = opt_lower(rest.pop(0)) == 'lower'
    o = _opts(rest, 'decomposition', ('CheckCondition', 'RankTolerance'))
    check = _tf(o['CheckCondition']) if 'CheckCondition' in o else True
    tol = float(num(o['RankTolerance'])) if 'RankTolerance' in o else None
    if not np.all(np.isfinite(A)):
        raise err('MATLAB:decomposition:NonFinite', 'The matrix has Inf or NaN values.', 'decomposition')
    return Decomposition(A, kind, check, tol, lower)


@bi('isIllConditioned', arr=False)
def isIllConditioned(nargout, *args):
    """tf = isIllConditioned(dA): whether the factored matrix is ill conditioned (rcond below eps, or rank deficient)."""
    nargchk(args, 1, 1, 'isIllConditioned')
    if not isinstance(args[0], Decomposition):
        raise err('MATLAB:isIllConditioned:InvalidInput', 'The input is a decomposition.', 'isIllConditioned')
    return bool(args[0].ill())


def wrap_builtins():
    """rcond and rank of a decomposition: in front of the matrix versions."""
    from . import REG
    for name, fn in (('rcond', lambda d: d.rcond()), ('rank', lambda d: float(d.f[4]) if d.kind == 'cod' else
                                                         float(np.linalg.matrix_rank(d.A)))):
        info = REG.get(name)
        if info is None:
            continue
        orig = info.fn

        def make(orig, fn):
            def f(nargout, *args):
                if args and isinstance(args[0], Decomposition):
                    return fn(args[0])
                return orig(nargout, *args)
            return f
        info.fn = make(orig, fn)


wrap_builtins()


@bi('sylvester', arr=False)
def sylvester(nargout, *args):
    """X = sylvester(A, B, C): the solution of A*X + X*B = C (Bartels-Stewart, through SciPy)."""
    nargchk(args, 3, 3, 'sylvester')
    import scipy.linalg as sla
    A, B, C = (_mat2(v, 'sylvester', w) for v, w in zip(args, 'ABC'))
    if A.shape[0] != A.shape[1] or B.shape[0] != B.shape[1]:
        raise err('MATLAB:sylvester:NotSquare', 'A and B are square.', 'sylvester')
    if C.shape != (A.shape[0], B.shape[0]):
        raise err('MATLAB:sylvester:SizeMismatch', f'C is {A.shape[0]}-by-{B.shape[0]}: as many rows as A and columns as B.', 'sylvester')
    X = sla.solve_sylvester(A, B, C)
    if all(np.isrealobj(x) for x in (A, B, C)):
        X = np.real(X)
    return out(X)


@bi('lscov', nout=4, arr=False)
def lscov(nargout, *args):
    """[x, stdx, mse, S] = lscov(A, b, w or V, alg): weighted (w, a vector)
    or generalized (V, a covariance matrix) least squares: x minimizes
    (b - A*x)'*inv(V)*(b - A*x); mse is the residual's weighted sum of squares
    over m - n, S = mse*inv(A'*inv(V)*A) and stdx its diagonal's square root.
    A rank-deficient A gives a basic solution (zeros where the rank runs out)."""
    nargchk(args, 2, 4, 'lscov')
    import scipy.linalg as sla
    A = _mat2(args[0], 'lscov', 'A')
    b = _dense(args[1], 'lscov', 'b')
    b = b.reshape(-1, 1) if b.ndim == 1 else b
    m, n = A.shape
    if b.shape[0] != m:
        raise err('MATLAB:lscov:InputSizeMismatch', 'A and b have as many rows.', 'lscov')
    Aw, bw = A.astype(np.result_type(A, F64)), b.astype(np.result_type(b, F64))
    if len(args) > 2 and numel(args[2]) and not is_str(args[2]):
        W = _dense(args[2], 'lscov', 'w or V')
        if W.size == m and (W.ndim == 1 or 1 in W.shape) and not (m == 1 and W.shape == (1, 1) and False):
            w = W.reshape(-1).real
            if np.any(w < 0):
                raise err('MATLAB:lscov:NegativeWeights', 'The weights are not negative.', 'lscov')
            s = np.sqrt(w)
            Aw, bw = Aw * s[:, None], bw * s[:, None]
        elif W.shape == (m, m):
            try:
                L = np.linalg.cholesky(W)
            except np.linalg.LinAlgError:
                raise err('MATLAB:lscov:NotPosDef', 'V is a symmetric positive definite matrix.', 'lscov') from None
            Aw = sla.solve_triangular(L, Aw, lower=True)
            bw = sla.solve_triangular(L, bw, lower=True)
        else:
            raise err('MATLAB:lscov:WeightsSize', f'The third input is a vector of {m} weights or an {m}-by-{m} covariance matrix.', 'lscov')
    if len(args) > 3:
        alg = opt_lower(args[3])
        if alg not in ('chol', 'orth'):
            raise err('MATLAB:lscov:BadAlg', "The algorithm is 'chol' or 'orth'.", 'lscov')
    Q, Rr, P = sla.qr(Aw, mode='economic', pivoting=True)
    d = np.abs(np.diag(Rr))
    tol = max(m, n) * np.spacing(d[0]) if d.size and d[0] > 0 else 0.0
    r = int(np.sum(d > tol))
    if r < n:
        R.warn('MATLAB:lscov:RankDefDesignMat', 'A is rank deficient to within machine precision.')
    x = np.zeros((n, bw.shape[1]), np.result_type(Aw, bw))
    if r:
        x[P[:r]] = sla.solve_triangular(Rr[:r, :r], (Q[:, :r].conj().T @ bw), check_finite=False)
    res = bw - Aw @ x
    dof = m - r
    mse = (np.sum(np.abs(res) ** 2, axis=0) / dof) if dof > 0 else np.zeros(bw.shape[1])
    Ri = np.zeros((n, n))
    if r:
        Rinv = sla.solve_triangular(Rr[:r, :r], np.eye(r), check_finite=False)
        C = Rinv @ Rinv.conj().T                     # inv(R'R) on the pivot columns
        Ri[np.ix_(P[:r], P[:r])] = C.real
    stdx = np.sqrt(np.outer(np.diag(Ri), mse))
    if bw.shape[1] == 1:
        S = Ri * mse[0]
    else:
        S = np.stack([Ri * mm for mm in mse], axis=2)
    if np.isrealobj(A) and np.isrealobj(b):
        x = x.real
    return _outs(nargout, out(x), out(stdx), out(mse.reshape(1, -1) if mse.size > 1 else float(mse[0])), out(S))


@bi('normest1', nout=3, arr=False)
def normest1(nargout, *args):
    """[c, v, w] = normest1(A, t, X0): an estimate of norm(A, 1) by Higham and
    Tisseur's block method with t columns (2), through SciPy's onenormest; v
    and w with w = A*v and norm(w,1) = c*norm(v,1). Exact for n <= 4."""
    nargchk(args, 1, 3, 'normest1')
    from scipy.sparse.linalg import onenormest
    if isinstance(args[0], Sparse):
        A = args[0].m
        n = A.shape[0]
    else:
        if not isinstance(args[0], (np.ndarray, float)) and not hasattr(args[0], 'shape'):
            raise err('MATLAB:normest1:InvalidInput', 'A is a square matrix (a function handle for A is not taken here).', 'normest1')
        A = _mat2(args[0], 'normest1', 'A')
        n = A.shape[0]
    if A.shape[0] != A.shape[1]:
        raise err('MATLAB:normest1:NotSquare', 'A is a square matrix.', 'normest1')
    t = int(num(args[1])) if len(args) > 1 and numel(args[1]) else 2
    if n <= 4 or t >= n:
        D = A.toarray() if hasattr(A, 'toarray') else A
        cs = np.sum(np.abs(D), axis=0)
        j = int(np.argmax(cs)) if cs.size else 0
        v = np.zeros((n, 1))
        if n:
            v[j] = 1.0
        w = D @ v
        return _outs(nargout, float(cs.max()) if cs.size else 0.0, out(v), out(w))
    est, v, w = onenormest(A, t=t, compute_v=True, compute_w=True)
    return _outs(nargout, float(est), out(np.asarray(v).reshape(-1, 1)), out(np.asarray(w).reshape(-1, 1)))


@bi('subspace', arr=False)
def subspace(nargout, *args):
    """theta = subspace(A, B): the largest principal angle between the column spaces of A and B, in radians."""
    nargchk(args, 2, 2, 'subspace')
    A = _mat2(args[0], 'subspace', 'A')
    B = _mat2(args[1], 'subspace', 'B')
    if A.shape[0] != B.shape[0]:
        raise err('MATLAB:subspace:SizeMismatch', 'A and B have as many rows.', 'subspace')
    import scipy.linalg as sla
    QA = sla.orth(A) if A.size else np.zeros((A.shape[0], 0))
    QB = sla.orth(B) if B.size else np.zeros((B.shape[0], 0))
    if QA.shape[1] < QB.shape[1]:
        QA, QB = QB, QA
    Bp = QB - QA @ (QA.conj().T @ QB)
    s = np.linalg.norm(Bp, 2) if Bp.size else 0.0
    return float(math.asin(min(1.0, s)))


@bi('condeig', nout=3, arr=False)
def condeig(nargout, *args):
    """c = condeig(A): the condition number of each eigenvalue,
    norm(w_i)*norm(v_i)/abs(w_i'*v_i) for its left and right eigenvectors;
    [V, D, s] = condeig(A) also gives eig's V and D."""
    nargchk(args, 1, 1, 'condeig')
    A = _mat2(args[0], 'condeig', 'A')
    if A.shape[0] != A.shape[1]:
        raise err('MATLAB:condeig:NotSquare', 'A is a square matrix.', 'condeig')
    VD = _REG('eig')(2, args[0])
    V = np.asarray(darr(VD[0]))
    D = VD[1]
    try:
        Wh = np.linalg.inv(V)                         # rows: the left eigenvectors' conjugates, scaled so w_i'*v_i = 1
        c = np.linalg.norm(Wh, axis=1) * np.linalg.norm(V, axis=0)
    except np.linalg.LinAlgError:
        c = np.full(A.shape[0], np.inf)
    c = c.reshape(-1, 1)
    if nargout > 1:
        return _outs(nargout, VD[0], D, out(c))
    return out(c)


@bi('cdf2rdf', nout=2, arr=False)
def cdf2rdf(nargout, *args):
    """[V, D] = cdf2rdf(V, D): eig's complex diagonal form as a real block
    diagonal one: each pair a +- bi becomes the block [a b; -b a] (b of the
    first of the pair) and its two vectors the real and imaginary parts of
    the first one's, so A*V = V*D still holds."""
    nargchk(args, 2, 2, 'cdf2rdf')
    V = _mat2(args[0], 'cdf2rdf', 'V').astype(C128)
    D = _mat2(args[1], 'cdf2rdf', 'D').astype(C128)
    n = D.shape[0]
    if D.shape != (n, n) or V.shape[1] != n:
        raise err('MATLAB:cdf2rdf:SizeMismatch', 'D is square, with as many columns as V.', 'cdf2rdf')
    lam = np.diag(D)
    Vr = np.zeros(V.shape)
    Dr = np.zeros((n, n))
    j = 0
    while j < n:
        l = lam[j]
        if abs(l.imag) > 0:
            if j + 1 >= n or not np.isclose(lam[j + 1], np.conj(l), rtol=1e-10, atol=1e-12 * max(1.0, abs(l))):
                raise err('MATLAB:cdf2rdf:NotPaired', 'The complex eigenvalues come in conjugate pairs, next to each other.', 'cdf2rdf')
            a, b = l.real, l.imag
            Dr[j:j + 2, j:j + 2] = [[a, b], [-b, a]]
            Vr[:, j] = V[:, j].real
            Vr[:, j + 1] = V[:, j].imag
            j += 2
        else:
            Dr[j, j] = l.real
            Vr[:, j] = V[:, j].real
            j += 1
    return _outs(nargout, out(Vr), out(Dr))


def _h12():
    from scipy.linalg import toeplitz
    T = toeplitz([-1, -1, 1, -1, -1, -1, 1, 1, 1, -1, 1], [-1, 1, -1, 1, 1, 1, -1, -1, -1, 1, -1])
    return np.block([[np.ones((1, 12))], [np.ones((11, 1)), T]])


def _h20():
    from scipy.linalg import hankel
    H = hankel([-1, -1, 1, 1, -1, -1, -1, -1, 1, -1, 1, -1, 1, 1, 1, 1, -1, -1, 1],
               [1, -1, -1, 1, 1, -1, -1, -1, -1, 1, -1, 1, -1, 1, 1, 1, 1, -1, -1])
    return np.block([[np.ones((1, 20))], [np.ones((19, 1)), H]])


@bi('hadamard', arr=False)
def hadamard(nargout, *args):
    """H = hadamard(n, classname): a Hadamard matrix (entries 1 and -1,
    H'*H = n*I) for n, n/12 or n/20 a power of 2, by Sylvester's doubling
    [H H; H -H] from 1, 12 or 20."""
    nargchk(args, 1, 2, 'hadamard')
    n = float(num(args[0]))
    cls = opt_lower(args[1]) if len(args) > 1 else 'double'
    if cls not in ('double', 'single'):
        raise err('MATLAB:hadamard:BadClass', "The class is 'double' or 'single'.", 'hadamard')
    base = None
    for b, H0 in ((1, lambda: np.ones((1, 1))), (12, _h12), (20, _h20)):
        k = math.log2(n / b) if n >= b else -1
        if k >= 0 and k == int(k):
            base, kk = H0(), int(k)
            break
    if base is None:
        raise err('MATLAB:hadamard:Invalid', 'n is 2^k, 12*2^k or 20*2^k.', 'hadamard')
    H = base
    for _ in range(kk):
        H = np.block([[H, H], [H, -H]])
    return H.astype(np.float32 if cls == 'single' else F64)


# ---- scattered data in n dimensions ------------------------------------------------------------------------------

def _qhull_opts(v, d):
    if v is None:
        # Qz keeps cocircular points (a square's corners) triangulable
        return 'Qt Qbb Qc Qz' + (' Qx' if d >= 4 else '')
    if isinstance(v, Cell):
        return ' '.join(str(x) for x in (py_str(c) for c in v.a.reshape(-1)))
    if isinstance(v, np.ndarray) and v.size == 0:
        return ''
    return py_str(v)


@bi('delaunayn', arr=False)
def delaunayn(nargout, *args):
    """T = delaunayn(X, options): the Delaunay triangulation of the points (rows of X) in n dimensions, a row of n+1 point indices per simplex (Qhull options as a cell of text)."""
    nargchk(args, 1, 2, 'delaunayn')
    from scipy.spatial import Delaunay
    X = _mat2(args[0], 'delaunayn', 'X').real.astype(F64)
    if X.shape[0] <= X.shape[1]:
        raise err('MATLAB:delaunayn:TooFewPoints', f'There are at least {X.shape[1] + 1} points in {X.shape[1]} dimensions.', 'delaunayn')
    try:
        T = Delaunay(X, qhull_options=_qhull_opts(args[1] if len(args) > 1 else None, X.shape[1])).simplices
    except Exception as e:
        raise err('MATLAB:delaunayn:Qhull', f'Qhull could not triangulate the points: {str(e).splitlines()[0] if str(e) else "degenerate points"}.', 'delaunayn') from None
    return out(T.astype(F64) + 1)


@bi('convhulln', nout=2, arr=False)
def convhulln(nargout, *args):
    """[K, V] = convhulln(X, options): the convex hull of points in n dimensions, a row of point indices per facet, and its volume."""
    nargchk(args, 1, 2, 'convhulln')
    from scipy.spatial import ConvexHull
    X = _mat2(args[0], 'convhulln', 'X').real.astype(F64)
    opts = None
    if len(args) > 1:
        opts = _qhull_opts(args[1], X.shape[1])
    try:
        h = ConvexHull(X, qhull_options=opts or None)
    except Exception as e:
        raise err('MATLAB:convhulln:Qhull', f'Qhull could not find the hull: {str(e).splitlines()[0] if str(e) else "degenerate points"}.', 'convhulln') from None
    return _outs(nargout, out(h.simplices.astype(F64) + 1), float(h.volume))


@bi('griddatan', arr=False)
def griddatan(nargout, *args):
    """vq = griddatan(X, v, xq, method): v at the points X (rows) interpolated
    at the rows of xq: 'linear' (default) within the Delaunay simplices or
    'nearest'; NaN outside the convex hull."""
    nargchk(args, 3, 5, 'griddatan')
    from scipy.spatial import Delaunay, cKDTree
    X = _mat2(args[0], 'griddatan', 'X').real.astype(F64)
    v = _dense(args[1], 'griddatan', 'v').reshape(-1)
    Q = _mat2(args[2], 'griddatan', 'xq').real.astype(F64)
    if v.size != X.shape[0]:
        raise err('MATLAB:griddatan:SizeMismatch', 'v has a value for each row of X.', 'griddatan')
    if Q.shape[1] != X.shape[1]:
        raise err('MATLAB:griddatan:SizeMismatch', 'xq has as many columns as X.', 'griddatan')
    method = opt_lower(args[3]) if len(args) > 3 and numel(args[3]) else 'linear'
    if method not in ('linear', 'nearest'):
        raise err('MATLAB:griddatan:BadMethod', "The method is 'linear' or 'nearest'.", 'griddatan')
    opts = _qhull_opts(args[4] if len(args) > 4 else None, X.shape[1])
    try:
        tri = Delaunay(X, qhull_options=opts)
    except Exception as e:
        raise err('MATLAB:griddatan:Qhull', 'Qhull could not triangulate the points.', 'griddatan') from None
    s = tri.find_simplex(Q)
    res = np.full(Q.shape[0], np.nan, dtype=np.result_type(v, F64))
    inside = s >= 0
    if method == 'nearest':
        _, j = cKDTree(X).query(Q[inside])
        res[inside] = v[j]
    else:
        d = X.shape[1]
        T = tri.transform[s[inside]]
        bary = np.einsum('ijk,ik->ij', T[:, :d, :], Q[inside] - T[:, d, :])
        w = np.column_stack([bary, 1 - bary.sum(axis=1)])
        res[inside] = np.sum(w * v[tri.simplices[s[inside]]], axis=1)
    return out(res.reshape(-1, 1))


# ---- nonuniform Fourier transforms ---------------------------------------------------------------------------------

def _first_dim(shape):
    for i, s in enumerate(shape):
        if s != 1:
            return i
    return 0


@bi('nufft', arr=False)
def nufft(nargout, *args):
    """Y = nufft(X, t, f, dim): the nonuniform discrete Fourier transform
    Y(k) = sum_j X(j)*exp(-2*pi*i*t(j)*f(k)) along dim (the first that is not
    1): sample points t (0:n-1) and frequencies f ((0:n-1)/n), each [] for
    its default. Summed directly."""
    nargchk(args, 1, 4, 'nufft')
    X = _dense(args[0], 'nufft', 'X')
    X2 = X if X.ndim >= 2 else X.reshape(1, -1)
    dim = int(num(args[3])) - 1 if len(args) > 3 and numel(args[3]) else _first_dim(X2.shape)
    if dim < 0:
        raise err('MATLAB:nufft:BadDim', 'dim is a positive whole number.', 'nufft')
    shape = list(X2.shape) + [1] * max(0, dim + 1 - X2.ndim)
    Xn = X2.reshape(shape)
    n = shape[dim]
    t = np.arange(n, dtype=F64) if len(args) < 2 or not numel(args[1]) else _dense(args[1], 'nufft', 't').real.reshape(-1).astype(F64)
    f = np.arange(n, dtype=F64) / max(n, 1) if len(args) < 3 or not numel(args[2]) else _dense(args[2], 'nufft', 'f').real.reshape(-1).astype(F64)
    if t.size != n:
        raise err('MATLAB:nufft:SizeMismatch', f't has a point for each of the {n} samples along dimension {dim + 1}.', 'nufft')
    Xm = np.moveaxis(Xn, dim, 0).reshape(n, -1).astype(C128)
    Y = np.empty((f.size, Xm.shape[1]), C128)
    step = max(1, int(4e6 // max(n, 1)))
    for a in range(0, f.size, step):
        E = np.exp(-2j * np.pi * np.outer(f[a:a + step], t))
        Y[a:a + step] = E @ Xm
    rest = [s for i, s in enumerate(shape) if i != dim]
    Y = np.moveaxis(Y.reshape([f.size] + rest), 0, dim)
    if X.dtype == np.float32 or X.dtype == np.complex64:
        Y = Y.astype(np.complex64)
    return out(Y)


@bi('nufftn', arr=False)
def nufftn(nargout, *args):
    """Y = nufftn(X, t, f): the n-dimensional nonuniform DFT
    Y(k) = sum_j X(j)*exp(-2*pi*i*f(k)·t(j)): t and f as matrices of points
    (a row per point) or cell arrays of vectors (the grid they span);
    defaults are X's grid 0:n-1 and frequencies (0:n-1)/n in each
    dimension. A grid of frequencies gives an array, points a column."""
    nargchk(args, 1, 3, 'nufftn')
    X = _dense(args[0], 'nufftn', 'X')

    def grid(v, default):
        if v is None or (not isinstance(v, Cell) and not numel(v)):
            return default, True
        if isinstance(v, Cell):
            vs = [np.asarray(darr(c), F64).reshape(-1) for c in v.a.reshape(-1)]
            G = np.meshgrid(*vs, indexing='ij')
            return np.column_stack([g.reshape(-1, order='F') for g in G]), [x.size for x in vs]
        P = _mat2(v, 'nufftn', 'the points').real.astype(F64)
        return P, None
    dims = list(X.shape) if X.ndim >= 2 else [1, X.size]
    if X.ndim == 2 and 1 in X.shape and (len(args) < 2 or not isinstance(args[1], Cell)):
        dims = [X.size]
    G = np.meshgrid(*[np.arange(d, dtype=F64) for d in dims], indexing='ij')
    t_def = np.column_stack([g.reshape(-1, order='F') for g in G])
    Gf = np.meshgrid(*[np.arange(d, dtype=F64) / d for d in dims], indexing='ij')
    f_def = np.column_stack([g.reshape(-1, order='F') for g in Gf])
    t, tg = grid(args[1] if len(args) > 1 else None, t_def)
    if tg is True:
        tg = dims
    f, fg = grid(args[2] if len(args) > 2 else None, f_def)
    if fg is True:
        fg = dims
    if t.shape[1] != f.shape[1]:
        raise err('MATLAB:nufftn:SizeMismatch', 't and f have as many dimensions.', 'nufftn')
    x = X.reshape(-1, order='F').astype(C128)
    if t.shape[0] != x.size:
        raise err('MATLAB:nufftn:SizeMismatch', f't has a point for each of the {x.size} values of X.', 'nufftn')
    Y = np.empty(f.shape[0], C128)
    step = max(1, int(4e6 // max(t.shape[0], 1)))
    for a in range(0, f.shape[0], step):
        Y[a:a + step] = np.exp(-2j * np.pi * (f[a:a + step] @ t.T)) @ x
    if fg is not None:
        shape = list(fg) if len(fg) > 1 else ([fg[0], 1] if X.ndim == 2 and X.shape[1] == 1 or (X.ndim == 2 and X.shape[0] != 1) else [1, fg[0]])
        Y = Y.reshape(shape, order='F')
    else:
        Y = Y.reshape(-1, 1)
    return out(Y)


# ---- sparse orderings ----------------------------------------------------------------------------------------------

@bi('colperm', arr=False)
def colperm(nargout, *args):
    """j = colperm(S): the columns ordered by how many nonzeros they hold, fewest first (ties in order)."""
    nargchk(args, 1, 1, 'colperm')
    v = args[0]
    if isinstance(v, Sparse):
        cnt = np.diff(v.m.tocsc().indptr)
    else:
        a = _mat2(v, 'colperm', 'S')
        cnt = np.count_nonzero(a, axis=0)
    return out(np.argsort(cnt, kind='stable').astype(F64).reshape(1, -1) + 1)


def _pattern(v, fn):
    import scipy.sparse as sp
    if isinstance(v, Sparse):
        M = v.m.tocsc()
    else:
        M = sp.csc_matrix(_mat2(v, fn, 'A'))
    M = M.copy()
    M.data = np.ones_like(M.data, dtype=F64)
    M.eliminate_zeros()
    return M


@bi('symbfact', nout=5, arr=False)
def symbfact(nargout, *args):
    """[count, h, parent, post, R] = symbfact(A, type): the structure of the
    Cholesky factor R of A without computing it: the nonzeros in each row of
    R, the elimination tree's height, its parent of each node, a postorder,
    and R's structure (ones). type 'sym' (the upper triangle of A, default),
    'col' (A'*A), 'row' (A*A') or 'lo' (the lower triangle)."""
    nargchk(args, 1, 3, 'symbfact')
    import scipy.sparse as sp
    M = _pattern(args[0], 'symbfact')
    kind = opt_lower(args[1]) if len(args) > 1 and numel(args[1]) else 'sym'
    if kind == 'sym':
        if M.shape[0] != M.shape[1]:
            raise err('MATLAB:symbfact:NotSquare', 'A is square.', 'symbfact')
        U = sp.triu(M, 1)
        Lp = U.T.tocsc()
    elif kind == 'lo':
        if M.shape[0] != M.shape[1]:
            raise err('MATLAB:symbfact:NotSquare', 'A is square.', 'symbfact')
        Lp = sp.tril(M, -1).tocsc()
    elif kind == 'col':
        Lp = sp.tril((M.T @ M).tocsc(), -1).tocsc()
    elif kind == 'row':
        Lp = sp.tril((M @ M.T).tocsc(), -1).tocsc()
    else:
        raise err('MATLAB:symbfact:BadType', "The type is 'sym', 'col', 'row' or 'lo'.", 'symbfact')
    n = Lp.shape[0]
    cols = []
    parent = np.zeros(n, int) - 1
    children = [[] for _ in range(n)]
    for j in range(n):
        s = set(Lp.indices[Lp.indptr[j]:Lp.indptr[j + 1]].tolist())
        for c in children[j]:
            s |= cols[c]
        s.discard(j)
        s = {i for i in s if i > j}
        cols.append(s)
        if s:
            p = min(s)
            parent[j] = p
            children[p].append(j)
    count = np.array([1 + len(c) for c in cols], F64)
    # postorder: children before parents, roots in order
    post, depth = [], np.zeros(n, int)
    for root in [j for j in range(n) if parent[j] < 0]:
        stack = [(root, 0)]
        while stack:
            node, i = stack.pop()
            kids = sorted(children[node])
            if i < len(kids):
                stack.append((node, i + 1))
                stack.append((kids[i], 0))
            else:
                post.append(node)
    for j in range(n - 1, -1, -1):
        depth[j] = 1 if parent[j] < 0 else depth[parent[j]] + 1
    h = float(depth.max()) if n else 0.0
    rows, colsj = [], []
    for j in range(n):
        rows.append(j)
        colsj.append(j)
        for i in cols[j]:
            rows.append(j)
            colsj.append(i)                          # R = L': row j holds column j's below-diagonal entries
    from .. import sparsemat as SPM
    Rm = SPM.make(sp.csc_matrix((np.ones(len(rows)), (rows, colsj)), shape=(n, n)))
    par = (parent + 1).astype(F64).reshape(1, -1)
    return _outs(nargout, out(count.reshape(-1, 1)), h, out(par), out(np.array(post, F64).reshape(1, -1) + 1), Rm)


# ---- errors of a prediction -----------------------------------------------------------------------------------------

def _error_measure(name, args, fn):
    """name(F, A, dims..., nanflag, 'Weights', w) through mean."""
    nargchk(args, 2, 6, name)
    F, A = args[0], args[1]
    for v, w in ((F, 'F'), (A, 'A')):
        if isinstance(v, (Cell, Struct, Char, Str)) or isinstance(v, Obj):
            raise err(f'MATLAB:{name}:InvalidInput', f'{w} is a numeric array.', name)
    E = fn(F, A)
    return _REG('mean')(1, E, *args[2:])


def _REG(name):
    from . import REG
    return REG[name].fn


@bi('rmse', arr=False)
def rmse(nargout, *args):
    """E = rmse(F, A, dim or vecdim or 'all', nanflag, 'Weights', w): the root-mean-square error sqrt(mean(abs(F - A).^2))."""
    from .. import ops
    m = _error_measure('rmse', args, lambda F, A: ops.power(_REG('abs')(1, ops.minus(F, A)), 2.0))
    return _REG('sqrt')(1, m)


@bi('mape', arr=False)
def mape(nargout, *args):
    """E = mape(F, A, dim or vecdim or 'all', nanflag, 'Weights', w): the mean absolute percentage error, 100*mean(abs((A - F)./A))."""
    from .. import ops
    m = _error_measure('mape', args, lambda F, A: _REG('abs')(1, ops.rdivide(ops.minus(A, F), A)))
    return ops.times(m, 100.0)
