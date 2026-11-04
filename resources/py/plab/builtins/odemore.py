"""More differential equations: boundary value problems (bvp4c, bvp5c,
bvpinit, bvpset, bvpget, bvpxtend), delay differential equations (dde23,
ddesd, ddeset, ddeget), parabolic and elliptic PDEs in one space variable
(pdepe, pdeval), and the ode object (ode, solve, solutionFcn, the results
it gives).

bvp4c is SciPy's solve_bvp, a fourth-order collocation with control of the
residual. bvp5c is PyLAB's own: the four-stage Lobatto IIIA collocation
(fifth order), solved by Newton's method with a sparse Jacobian, the mesh
refined where the residual of its piecewise polynomial is too large. dde23
and ddesd step with the Bogacki-Shampine 3(2) pair, the delayed values
taken from the cubic Hermite interpolant of the steps already taken (and
of the step being taken, by iteration, when a delay is shorter than a
step); dde23 steps to the points where a constant delay carries a jump of
the history's derivative. pdepe is a finite-volume method of lines: the
equation integrated over a cell about each node (x^m dx), its coefficients
at the midpoints of the mesh's intervals, solved in time by ode15s."""
import math

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, num, is_str, darr, out
from ..values import MError, Obj, FH, Char, Struct, EMPTY, numel, py_str
from .. import runtime as R
from .funfun import _struct_opts, _opt, _fn, _ode, _DenseHolder, _ODE_METHOD


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        return _register(*names, **kw)(f)
    return deco


def _col(v):
    return out(np.asarray(v, float).reshape(-1, 1))


def _vec(v, n=None, what='The function', fn=''):
    a = np.asarray(darr(v), float).reshape(-1)
    if n is not None and a.size != n:
        raise err(f'MATLAB:{fn}:size', f'{what} gives {a.size} values; {n} are wanted.', fn)
    return a


def _options(names, args):
    base = {}
    i = 0
    if args and type(args[0]) is Struct:
        base = _struct_opts(args[0])
        i = 1
    for n in names:
        base.setdefault(n, EMPTY())
    while i + 1 < len(args):
        k = py_str(args[i])
        base[next((n for n in base if n.lower() == k.lower()), k)] = args[i + 1]
        i += 2
    if i < len(args):
        raise err('MATLAB:set:pairs', 'Options come as names and values.', 'set')
    return Struct.scalar(base)


def _get(args):
    opts = _struct_opts(args[0])
    v = _opt(opts, py_str(args[1]))
    if v is None:
        return args[2] if len(args) > 2 else EMPTY()
    return v


class _Holder(_DenseHolder):
    """A solution's interpolant for deval: values, and derivatives when asked."""
    __slots__ = ('dfn',)

    def __init__(self, fn, dfn):
        super().__init__(fn)
        self.dfn = dfn


# ---- boundary value problems --------------------------------------------------------------------------------------------------------

BVP_OPTS = ('RelTol', 'AbsTol', 'SingularTerm', 'FJacobian', 'BCJacobian', 'Stats', 'NMax', 'Vectorized')


@bi('bvpset')
def bvpset(nargout, *args):
    """options = bvpset('name', value, ...), bvpset(old, 'name', value, ...): options of bvp4c and bvp5c."""
    return _options(BVP_OPTS, args)


@bi('bvpget')
def bvpget(nargout, *args):
    """v = bvpget(options, 'name'), bvpget(options, 'name', default): an option of bvp4c and bvp5c."""
    nargchk(args, 2, 3, 'bvpget')
    return _get(args)


@bi('bvpinit')
def bvpinit(nargout, *args):
    """solinit = bvpinit(xmesh, yinit), bvpinit(xmesh, yinit, parameters), bvpinit(sol, [anew bnew]): a first guess for bvp4c and bvp5c."""
    nargchk(args, 2, 4, 'bvpinit')
    if type(args[0]) is Struct and 'x' in args[0].keys and 'y' in args[0].keys:
        sol = args[0]
        x = _vec(sol.get1('x'))
        Y = np.asarray(darr(sol.get1('y')), float)
        ab = _vec(args[1])
        if ab.size != 2:
            raise err('MATLAB:bvpinit:interval', 'bvpinit(sol, [anew bnew]) takes the new interval.', 'bvpinit')
        xs, ys = list(x), [Y[:, k] for k in range(x.size)]
        if ab[0] < x[0]:
            xs.insert(0, ab[0])
            ys.insert(0, Y[:, 0])
        elif ab[0] > x[0]:
            raise err('MATLAB:bvpinit:shrink', 'The new interval holds the old one.', 'bvpinit')
        if ab[1] > x[-1]:
            xs.append(ab[1])
            ys.append(Y[:, -1])
        elif ab[1] < x[-1]:
            raise err('MATLAB:bvpinit:shrink', 'The new interval holds the old one.', 'bvpinit')
        fields = {'x': out(np.array(xs).reshape(1, -1)), 'y': out(np.column_stack(ys))}
        p = args[2] if len(args) > 2 else (sol.get1('parameters') if 'parameters' in sol.keys else None)
        if p is not None and numel(p):
            fields['parameters'] = _col(_vec(p)) if numel(p) > 1 else float(_vec(p)[0])
        return Struct.scalar(fields)
    x = _vec(args[0])
    if x.size < 2 or np.any(np.diff(x) < 0) or x[0] == x[-1]:
        raise err('MATLAB:bvpinit:mesh', 'The mesh is a vector of two or more points, from a to b, in order.', 'bvpinit')
    yi = args[1]
    if isinstance(yi, FH):
        Y = np.column_stack([_vec(yi.scall(1, float(xx), *args[3:])) for xx in x])
    else:
        y0 = _vec(yi)
        Y = np.tile(y0.reshape(-1, 1), (1, x.size))
    fields = {'x': out(x.reshape(1, -1)), 'y': out(Y)}
    if len(args) > 2 and numel(args[2]):
        fields['parameters'] = _col(_vec(args[2])) if numel(args[2]) > 1 else float(_vec(args[2])[0])
    fields['yinit'] = yi
    return Struct.scalar(fields)


@bi('bvpxtend')
def bvpxtend(nargout, *args):
    """solinit = bvpxtend(sol, xnew), bvpxtend(sol, xnew, ynew): a guess on an interval made longer to xnew (beyond a or b), y there extrapolated (or ynew)."""
    nargchk(args, 2, 4, 'bvpxtend')
    sol = args[0]
    if type(sol) is not Struct or 'x' not in sol.keys:
        raise err('MATLAB:bvpxtend:sol', 'bvpxtend takes a solution from bvp4c or bvp5c.', 'bvpxtend')
    x = _vec(sol.get1('x'))
    Y = np.asarray(darr(sol.get1('y')), float)
    xn = float(num(args[1]))
    if x[0] < xn < x[-1]:
        raise err('MATLAB:bvpxtend:inside', 'xnew lies outside the solution\'s interval.', 'bvpxtend')
    if len(args) > 2 and numel(args[2]) and not is_str(args[2]):
        yn = _vec(args[2], Y.shape[0], 'ynew', 'bvpxtend')
    else:
        k = 0 if xn < x[0] else -1
        yp = np.asarray(darr(sol.get1('yp')), float) if 'yp' in sol.keys else np.zeros_like(Y)
        yn = Y[:, k] + yp[:, k] * (xn - x[k])
    if xn < x[0]:
        x2, Y2 = np.concatenate([[xn], x]), np.column_stack([yn, Y])
    else:
        x2, Y2 = np.concatenate([x, [xn]]), np.column_stack([Y, yn])
    fields = {'x': out(x2.reshape(1, -1)), 'y': out(Y2)}
    if 'parameters' in sol.keys:
        fields['parameters'] = sol.get1('parameters')
    return Struct.scalar(fields)


class _BVP:
    """A boundary value problem as both solvers see it: f(x, y, p) for many x at once, bc(ya, yb, p)."""

    def __init__(self, fn, args):
        nargchk(args, 3, None, fn)
        self.fn = fn
        self.f = _fn(args[0])
        self.bcf = _fn(args[1], 'boundary condition function')
        si = args[2]
        if type(si) is not Struct or 'x' not in si.keys or 'y' not in si.keys:
            raise err(f'MATLAB:{fn}:solinit', 'The guess is a struct with x and y, as bvpinit makes it.', fn)
        self.x = _vec(si.get1('x'))
        self.Y = np.asarray(darr(si.get1('y')), float)
        if self.Y.ndim != 2 or self.Y.shape[1] != self.x.size:
            raise err(f'MATLAB:{fn}:solinit', 'The guess has a column of y for each point of x.', fn)
        if np.any(np.diff(self.x) == 0):
            raise err(f'MATLAB:{fn}:multipoint', 'Problems with conditions at interior points (a mesh point given twice) are not solved here.', fn)
        if np.any(np.diff(self.x) < 0):
            raise err(f'MATLAB:{fn}:mesh', 'The mesh goes from a to b in order.', fn)
        self.n = self.Y.shape[0]
        self.p0 = _vec(si.get1('parameters')) if 'parameters' in si.keys and numel(si.get1('parameters')) else np.zeros(0)
        self.k = self.p0.size
        self.opts = _struct_opts(args[3]) if len(args) > 3 and type(args[3]) is Struct else {}
        self.extra = args[4:] if len(args) > 3 and type(args[3]) is Struct else args[3:]
        rt, at = _opt(self.opts, 'RelTol'), _opt(self.opts, 'AbsTol')
        self.rtol = float(num(rt)) if rt is not None else 1e-3
        self.atol = float(np.max(_vec(at))) if at is not None else 1e-6
        nm = _opt(self.opts, 'NMax')
        self.nmax = int(num(nm)) if nm is not None else max(int(10000 // self.n), 50)
        vz = _opt(self.opts, 'Vectorized')
        self.vectorized = vz is not None and (py_str(vz).lower() == 'on' if is_str(vz) else bool(np.all(vz)))
        self.nf = self.nbc = 0

    def _pargs(self, p):
        return ((_col(p) if p.size > 1 else float(p[0])),) if self.k else ()

    def f_many(self, x, Y, p):
        """f at each point: x (m,), Y (n, m) -> (n, m)."""
        if self.vectorized and x.size > 1:
            self.nf += 1
            r = np.asarray(darr(self.f.scall(1, out(x.reshape(1, -1)), out(Y), *self._pargs(p), *self.extra)), float)
            return r.reshape(self.n, x.size)
        res = np.empty((self.n, x.size))
        for j in range(x.size):
            self.nf += 1
            res[:, j] = _vec(self.f.scall(1, float(x[j]), _col(Y[:, j]), *self._pargs(p), *self.extra), self.n, 'The ODE function', self.fn)
        return res

    def bc(self, ya, yb, p):
        self.nbc += 1
        return _vec(self.bcf.scall(1, _col(ya), _col(yb), *self._pargs(p), *self.extra), self.n + self.k, 'The boundary condition function', self.fn)

    def solution(self, x, Y, YP, p, holder, maxres, fn):
        fields = {'solver': Char.of(fn), 'x': out(x.reshape(1, -1)), 'y': out(Y), 'yp': out(YP)}
        if self.k:
            fields['parameters'] = _col(p) if p.size > 1 else float(p[0])
        fields['stats'] = Struct.scalar({'nmeshpoints': float(x.size), 'maxres': float(maxres), 'nODEevals': float(self.nf), 'nBCevals': float(self.nbc)})
        fields['idata'] = holder
        st = _opt(self.opts, 'Stats')
        if st is not None and is_str(st) and py_str(st).lower() == 'on':
            R.write(f'The solution was obtained on a mesh of {x.size} points.\nThe maximum residual is {maxres:10.3e}.\n'
                    f'There were {self.nf} calls to the ODE function.\nThere were {self.nbc} calls to the BC function.\n')
        return Struct.scalar(fields)


@bi('bvp4c')
def bvp4c(nargout, *args):
    """sol = bvp4c(odefun, bcfun, solinit), bvp4c(odefun, bcfun, solinit, options): y' = f(x, y) (or f(x, y, p) with unknown parameters p) from a to b with conditions bc(y(a), y(b)) = 0."""
    from scipy.integrate import solve_bvp
    P = _BVP('bvp4c', args)
    S = _opt(P.opts, 'SingularTerm')
    kw = {}
    if S is not None:
        kw['S'] = np.asarray(darr(S), float)
        if P.x[0] != 0:
            raise err('MATLAB:bvp4c:SingularTerm', 'A singular term S/x needs the interval to start at 0.', 'bvp4c')
    fj = _opt(P.opts, 'FJacobian')
    if isinstance(fj, FH):
        def fun_jac(x, Y, p=None):
            pp = p if p is not None else np.zeros(0)
            J = np.empty((P.n, P.n, x.size))
            Jp = np.empty((P.n, P.k, x.size)) if P.k else None
            for j in range(x.size):
                r = fj.scall(2 if P.k else 1, float(x[j]), _col(Y[:, j]), *P._pargs(pp), *P.extra)
                if P.k:
                    J[:, :, j] = np.asarray(darr(r[0]), float).reshape(P.n, P.n)
                    Jp[:, :, j] = np.asarray(darr(r[1]), float).reshape(P.n, P.k)
                else:
                    J[:, :, j] = np.asarray(darr(r), float).reshape(P.n, P.n)
            return (J, Jp) if P.k else J
        kw['fun_jac'] = fun_jac

    def fun(x, Y, p=None):
        return P.f_many(x, Y, p if p is not None else np.zeros(0))

    def bc(ya, yb, p=None):
        return P.bc(ya, yb, p if p is not None else np.zeros(0))
    try:
        res = solve_bvp(fun, bc, P.x, P.Y, p=P.p0 if P.k else None, tol=P.rtol, max_nodes=P.nmax, **kw)
    except (ValueError, np.linalg.LinAlgError) as e:
        raise err('MATLAB:bvp4c:Failed', f'Unable to solve the collocation equations: {e}.', 'bvp4c')
    if res.status == 2:
        raise err('MATLAB:bvp4c:SingJac', 'Unable to solve the collocation equations: a singular Jacobian was met. A better guess (solinit) may help.', 'bvp4c')
    maxres = float(np.max(res.rms_residuals)) if res.rms_residuals.size else 0.0
    if res.status == 1:
        R.warn('MATLAB:bvp4c:RelTolNotMet', f'The tolerance could not be met with {P.nmax} mesh points or fewer. The solution on the last mesh, of {res.x.size} points, is given; '
               f'its largest residual is {maxres:g}, the tolerance {P.rtol:g}.')
    elif res.status == 3:
        R.warn('MATLAB:bvp4c:BCTolNotMet', 'The boundary conditions are not met to the tolerance.')
    pp = res.sol
    holder = _Holder(lambda xq: pp(np.asarray(xq, float)), lambda xq: pp.derivative()(np.asarray(xq, float)))
    return P.solution(res.x, res.y, res.yp, res.p if res.p is not None else np.zeros(0), holder, maxres, 'bvp4c')


def _lobatto():
    """The four-stage Lobatto IIIA collocation: its points c, and for u(x0 + s h) = y0 + h * sum_j F_j L_j(s),
    the coefficients of L_j (integrals of the Lagrange polynomials) and of their derivatives; A[j, k] = L_k(c_j)."""
    r5 = math.sqrt(5.0)
    c = np.array([0.0, (5 - r5) / 10, (5 + r5) / 10, 1.0])
    V = np.vander(c, 4, increasing=True)
    ell = np.linalg.inv(V)          # column k: the coefficients (increasing powers) of the Lagrange polynomial for c_k
    Lc = np.zeros((5, 4))
    for k in range(4):
        for q in range(4):
            Lc[q + 1, k] = ell[q, k] / (q + 1)
    A = np.array([[sum(Lc[q, k] * c[j] ** q for q in range(5)) for k in range(4)] for j in range(4)])
    return c, ell, Lc, A


_LOB = _lobatto()


@bi('bvp5c')
def bvp5c(nargout, *args):
    """sol = bvp5c(odefun, bcfun, solinit), bvp5c(..., options): a boundary value problem as bvp4c takes it, by a fifth-order collocation (four-stage Lobatto IIIA)."""
    import scipy.sparse as sps
    import scipy.sparse.linalg as spl
    P = _BVP('bvp5c', args)
    if _opt(P.opts, 'SingularTerm') is not None:
        raise err('MATLAB:bvp5c:SingularTerm', "bvp5c takes no 'SingularTerm': bvp4c does.", 'bvp5c')
    c, ell, Lc, A = _LOB
    n, k = P.n, P.k
    x = P.x.copy()
    Ynodes = P.Y.copy()
    p = P.p0.copy()
    # stage guesses: between the nodes, linearly
    S2 = Ynodes[:, :-1] + c[1] * np.diff(Ynodes, axis=1)
    S3 = Ynodes[:, :-1] + c[2] * np.diff(Ynodes, axis=1)

    def stage_points(x):
        h = np.diff(x)
        return x[:-1] + c[1] * h, x[:-1] + c[2] * h

    def residual(x, Yn, S2, S3, p):
        h = np.diff(x)
        x2, x3 = stage_points(x)
        Fn = P.f_many(x, Yn, p)
        F2 = P.f_many(x2, S2, p)
        F3 = P.f_many(x3, S3, p)
        F = [Fn[:, :-1], F2, F3, Fn[:, 1:]]
        St = [Yn[:, :-1], S2, S3, Yn[:, 1:]]
        R_ = []
        for j in (1, 2, 3):
            R_.append(St[j] - Yn[:, :-1] - h * sum(A[j, q] * F[q] for q in range(4)))
        bcr = P.bc(Yn[:, 0], Yn[:, -1], p)
        return R_, bcr, (Fn, F2, F3)

    def jac_f(xs, Ys, Fs, p):
        """df/dy at each point by differences: (m, n, n); df/dp (m, n, k)."""
        m = xs.size
        J = np.empty((m, n, n))
        for q in range(n):
            d = 1e-7 * np.maximum(1.0, np.abs(Ys[q]))
            Yp = Ys.copy()
            Yp[q] += d
            J[:, :, q] = ((P.f_many(xs, Yp, p) - Fs) / d).T
        Jp = np.empty((m, n, k))
        for q in range(k):
            d = 1e-7 * max(1.0, abs(p[q]))
            pp = p.copy()
            pp[q] += d
            Jp[:, :, q] = ((P.f_many(xs, Ys, pp) - Fs) / d).T
        return J, Jp

    def flat(Yn, S2, S3, p):
        return np.concatenate([Yn.T.reshape(-1), S2.T.reshape(-1), S3.T.reshape(-1), p])

    def unflat(z, N):
        a = n * (N + 1)
        b = a + n * N
        cc = b + n * N
        return z[:a].reshape(N + 1, n).T, z[a:b].reshape(N, n).T, z[b:cc].reshape(N, n).T, z[cc:]

    def rvec(R_, bcr):
        return np.concatenate([np.concatenate([R_[0].T, R_[1].T, R_[2].T], axis=1).reshape(-1), bcr])

    def newton(x, Yn, S2, S3, p):
        N = x.size - 1
        h = np.diff(x)
        z = flat(Yn, S2, S3, p)
        for it in range(40):
            Yn, S2, S3, p = unflat(z, N)
            R_, bcr, (Fn, F2, F3) = residual(x, Yn, S2, S3, p)
            r = rvec(R_, bcr)
            x2, x3 = stage_points(x)
            Jn, Jnp = jac_f(x, Yn, Fn, p)
            J2, J2p = jac_f(x2, S2, F2, p)
            J3, J3p = jac_f(x3, S3, F3, p)
            rows, cols, vals = [], [], []
            I = np.eye(n)
            nodecol = lambda i: i * n                       # noqa: E731
            s2col = lambda i: n * (N + 1) + i * n           # noqa: E731
            s3col = lambda i: n * (N + 1) + n * N + i * n   # noqa: E731
            pcol = n * (N + 1) + 2 * n * N
            for i in range(N):
                Js = [Jn[i], J2[i], J3[i], Jn[i + 1]]
                Jps = [Jnp[i], J2p[i], J3p[i], Jnp[i + 1]]
                colsets = [nodecol(i), s2col(i), s3col(i), nodecol(i + 1)]
                for jj, j in enumerate((1, 2, 3)):
                    r0 = i * 3 * n + jj * n
                    for q in range(4):
                        blk = -h[i] * A[j, q] * Js[q]
                        if q == j:
                            blk = blk + I
                        if q == 0:
                            blk = blk - I
                        rr, cc = np.nonzero(np.ones((n, n)))
                        rows.append(r0 + rr)
                        cols.append(colsets[q] + cc)
                        vals.append(blk[rr, cc])
                    if k:
                        blk = -h[i] * sum(A[j, q] * Jps[q] for q in range(4))
                        rr, cc = np.nonzero(np.ones((n, k)))
                        rows.append(r0 + rr)
                        cols.append(pcol + cc)
                        vals.append(blk[rr, cc])
            # the boundary conditions, by differences
            b0 = 3 * n * N
            ya, yb = Yn[:, 0], Yn[:, -1]
            for q in range(n):
                for which, col in ((0, nodecol(0) + q), (1, nodecol(N) + q)):
                    d = 1e-7 * max(1.0, abs((ya if which == 0 else yb)[q]))
                    a2, b2 = ya.copy(), yb.copy()
                    (a2 if which == 0 else b2)[q] += d
                    col_v = (P.bc(a2, b2, p) - bcr) / d
                    rows.append(b0 + np.arange(n + k))
                    cols.append(np.full(n + k, col))
                    vals.append(col_v)
            for q in range(k):
                d = 1e-7 * max(1.0, abs(p[q]))
                pp = p.copy()
                pp[q] += d
                rows.append(b0 + np.arange(n + k))
                cols.append(np.full(n + k, pcol + q))
                vals.append((P.bc(ya, yb, pp) - bcr) / d)
            size = z.size
            Jm = sps.csc_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(size, size))
            try:
                with np.errstate(all='ignore'):
                    dz = spl.spsolve(Jm, -r)
            except Exception:
                return None
            if not np.all(np.isfinite(dz)):
                return None
            lam = 1.0
            r_norm = np.linalg.norm(r)
            for _ in range(8):
                z_try = z + lam * dz
                Yt, S2t, S3t, pt = unflat(z_try, N)
                Rt, bct, _ = residual(x, Yt, S2t, S3t, pt)
                if np.linalg.norm(rvec(Rt, bct)) <= (1 - 0.25 * lam) * r_norm or r_norm < 1e-14:
                    break
                lam /= 2
            z = z_try
            if np.max(np.abs(lam * dz) / (1 + np.abs(z))) < 1e-10:
                return unflat(z, N)
        return None

    def poly_eval(x, Yn, F, xq, deriv=False):
        """The collocation polynomial (or its derivative) at xq; F the four stage derivatives of each interval."""
        xq = np.asarray(xq, float).reshape(-1)
        i = np.clip(np.searchsorted(x, xq, side='right') - 1, 0, x.size - 2)
        h = x[i + 1] - x[i]
        s = (xq - x[i]) / h
        outv = np.empty((n, xq.size))
        for idx in range(xq.size):
            ii, ss = i[idx], s[idx]
            Fi = [F[q][:, ii] for q in range(4)]
            if deriv:
                w = [sum(ell[q, kk] * ss ** q for q in range(4)) for kk in range(4)]
                outv[:, idx] = sum(w[kk] * Fi[kk] for kk in range(4))
            else:
                w = [sum(Lc[q, kk] * ss ** q for q in range(5)) for kk in range(4)]
                outv[:, idx] = Yn[:, ii] + h[idx] * sum(w[kk] * Fi[kk] for kk in range(4))
        return outv

    gauss = np.array([0.5 - math.sqrt(0.15), 0.5, 0.5 + math.sqrt(0.15)])
    gw = np.array([5, 8, 5]) / 18
    for _round in range(30):
        res = newton(x, Ynodes, S2, S3, p)
        if res is None:
            raise err('MATLAB:bvp5c:SingJac', 'Unable to solve the collocation equations: Newton\'s method did not converge. A better guess (solinit), or a coarser tolerance, may help.', 'bvp5c')
        Ynodes, S2, S3, p = res
        x2, x3 = stage_points(x)
        Fn = P.f_many(x, Ynodes, p)
        F = [Fn[:, :-1], P.f_many(x2, S2, p), P.f_many(x3, S3, p), Fn[:, 1:]]
        h = np.diff(x)
        # the residual of the collocation polynomial, scaled, by Gauss quadrature on each interval
        xs = (x[:-1, None] + gauss[None, :] * h[:, None]).reshape(-1)
        U = poly_eval(x, Ynodes, F, xs)
        Up = poly_eval(x, Ynodes, F, xs, deriv=True)
        Fu = P.f_many(xs, U, p)
        rr = (Up - Fu) / (1 + np.abs(Fu))
        rms = np.sqrt(np.sum((rr ** 2).reshape(n, -1, 3) * gw[None, None, :], axis=2)).max(axis=0)
        maxres = float(rms.max()) if rms.size else 0.0
        bad = rms > P.rtol
        if not np.any(bad):
            break
        new_x = [x[0]]
        for i in range(x.size - 1):
            if bad[i]:
                parts = 3 if rms[i] > 100 * P.rtol else 2
                new_x += list(x[i] + h[i] * np.arange(1, parts) / parts)
            new_x.append(x[i + 1])
        new_x = np.array(new_x)
        if new_x.size > P.nmax:
            R.warn('MATLAB:bvp5c:RelTolNotMet', f'The tolerance could not be met with {P.nmax} mesh points or fewer. The solution on the last mesh, of {x.size} points, is given; '
                   f'its largest residual is {maxres:g}, the tolerance {P.rtol:g}.')
            break
        Yn_new = poly_eval(x, Ynodes, F, new_x)
        nx2, nx3 = stage_points(new_x)
        S2 = poly_eval(x, Ynodes, F, nx2)
        S3 = poly_eval(x, Ynodes, F, nx3)
        x, Ynodes = new_x, Yn_new
    xf, Yf, Ff = x.copy(), Ynodes.copy(), [a.copy() for a in F]
    holder = _Holder(lambda xq: poly_eval(xf, Yf, Ff, xq), lambda xq: poly_eval(xf, Yf, Ff, xq, deriv=True))
    YP = P.f_many(xf, Yf, p)
    return P.solution(xf, Yf, YP, p, holder, maxres, 'bvp5c')


# ---- delay differential equations ---------------------------------------------------------------------------------------------------------

DDE_OPTS = ('RelTol', 'AbsTol', 'NormControl', 'Events', 'InitialStep', 'MaxStep', 'OutputFcn', 'OutputSel', 'Stats', 'InitialY', 'Jumps')


@bi('ddeset')
def ddeset(nargout, *args):
    """options = ddeset('name', value, ...), ddeset(old, 'name', value, ...): options of dde23 and ddesd."""
    return _options(DDE_OPTS, args)


@bi('ddeget')
def ddeget(nargout, *args):
    """v = ddeget(options, 'name'), ddeget(options, 'name', default): an option of dde23 and ddesd."""
    nargchk(args, 2, 3, 'ddeget')
    return _get(args)


def _hermite(t0, t1, y0, y1, f0, f1, s, deriv=False):
    h = t1 - t0
    th = (s - t0) / h
    if deriv:
        dh00 = 6 * th ** 2 - 6 * th
        dh10 = 3 * th ** 2 - 4 * th + 1
        dh01 = -6 * th ** 2 + 6 * th
        dh11 = 3 * th ** 2 - 2 * th
        return (dh00 * y0 + dh01 * y1) / h + dh10 * f0 + dh11 * f1
    h00 = 2 * th ** 3 - 3 * th ** 2 + 1
    h10 = th ** 3 - 2 * th ** 2 + th
    h01 = -2 * th ** 3 + 3 * th ** 2
    h11 = th ** 3 - th ** 2
    return h00 * y0 + h10 * h * f0 + h01 * y1 + h11 * h * f1


class _Mesh:
    """The steps taken: times, solutions and derivatives, interpolated by cubic Hermite pieces; before t0 the history."""

    def __init__(self, history, t0, n, extra):
        self.T, self.Y, self.F = [], [], []
        self.t0 = t0
        self.n = n
        self.extra = extra
        self.hist_sol = None
        if type(history) is Struct and 'idata' in history.keys:
            self.hist_sol = history
            self.hist = None
        elif isinstance(history, FH):
            self.hist = history
        else:
            self.hist = None
            self.const = _vec(history)
            if self.const.size != n and n:
                raise err('MATLAB:dde:history', f'The history gives {self.const.size} values; {n} are wanted.', 'dde23')
        self.trial = None         # the step being taken: (t0, t1, y0, y1, f0, f1)

    def history(self, s):
        if self.hist_sol is not None:
            return np.asarray(self.hist_sol.get1('idata').fn(np.array([s])), float).reshape(-1)
        if self.hist is not None:
            return _vec(self.hist.scall(1, float(s), *self.extra))
        return self.const

    def at(self, s):
        if s < self.t0 or (s == self.t0 and not self.T):
            return self.history(s)
        T = self.T
        if self.trial is not None and s > T[-1]:
            a, b, ya, yb, fa, fb = self.trial
            return _hermite(a, b, ya, yb, fa, fb, s)
        if len(T) == 1 or s <= T[0]:
            return self.Y[0] if s >= T[0] else self.history(s)
        if s >= T[-1]:
            if len(T) >= 2:
                # beyond the last step (a delay shorter than the step, first guess): the last piece extended
                return _hermite(T[-2], T[-1], self.Y[-2], self.Y[-1], self.F[-2], self.F[-1], s)
            return self.Y[-1] + (s - T[-1]) * self.F[-1]
        i = int(np.searchsorted(T, s, side='right')) - 1
        return _hermite(T[i], T[i + 1], self.Y[i], self.Y[i + 1], self.F[i], self.F[i + 1], s)

    def interp(self, xq, deriv=False):
        T = np.array(self.T)
        Y = np.array(self.Y).T
        Fm = np.array(self.F).T
        xq = np.asarray(xq, float).reshape(-1)
        res = np.empty((self.n, xq.size))
        for j, s in enumerate(xq):
            if s < T[0] and not deriv:
                res[:, j] = self.history(s)
                continue
            i = min(max(int(np.searchsorted(T, s, side='right')) - 1, 0), T.size - 2)
            res[:, j] = _hermite(T[i], T[i + 1], Y[:, i], Y[:, i + 1], Fm[:, i], Fm[:, i + 1], s, deriv)
        return res


def _dde(fn, nargout, args):
    """dde23 and ddesd: the method of steps with the Bogacki-Shampine 3(2) pair."""
    nargchk(args, 4, None, fn)
    f = _fn(args[0])
    dl = args[1]
    tspan = _vec(args[3])
    if tspan.size < 2 or tspan[-1] <= tspan[0]:
        raise err(f'MATLAB:{fn}:tspan', 'The time span runs forward, [t0 tf].', fn)
    t0, tf = float(tspan[0]), float(tspan[-1])
    opts = _struct_opts(args[4]) if len(args) > 4 and type(args[4]) is Struct else {}
    extra = args[5:] if len(args) > 4 else ()
    state_dep = fn == 'ddesd' and isinstance(dl, FH)
    lags = np.zeros(0) if state_dep else _vec(dl)
    if lags.size and np.any(lags < 0):
        raise err(f'MATLAB:{fn}:lags', 'The delays are not negative.', fn)
    if fn == 'dde23' and lags.size and np.any(lags == 0):
        raise err('MATLAB:dde23:lags', 'dde23 takes positive delays.', fn)
    hist = args[2]
    probe = _vec(hist.scall(1, t0, *extra)) if isinstance(hist, FH) else (np.asarray(hist.get1('y'), float)[:, -1] if type(hist) is Struct else _vec(hist))
    n = probe.size
    M = _Mesh(hist, t0, n, extra)
    iy = _opt(opts, 'InitialY')
    y = _vec(iy, n, 'InitialY', fn) if iy is not None else (probe if type(hist) is not Struct else np.asarray(hist.get1('y'), float)[:, -1])
    rt, at = _opt(opts, 'RelTol'), _opt(opts, 'AbsTol')
    rtol = float(num(rt)) if rt is not None else 1e-3
    atol = _vec(at) if at is not None else np.array([1e-6])
    ms = _opt(opts, 'MaxStep')
    hmax = float(num(ms)) if ms is not None else 0.1 * (tf - t0)
    nfe = [0]

    def delayed(t, yv):
        if state_dep:
            d = _vec(dl.scall(1, float(t), _col(yv), *extra))
            if np.any(d > t + 1e-12 * max(1.0, abs(t))):
                raise err('MATLAB:ddesd:DelayInFuture', f'A delay function value lies after t = {t:g}: the delays are times t - tau with tau >= 0.', fn)
            times = d
        else:
            times = t - lags
        if times.size == 0:
            return out(np.zeros((n, 0)))
        Z = np.column_stack([M.at(s) for s in times])
        return out(Z)

    def F(t, yv):
        nfe[0] += 1
        r = _vec(f.scall(1, float(t), _col(yv), delayed(t, yv), *extra))
        if r.size != n:
            raise err(f'MATLAB:{fn}:size', f'The function gives {r.size} values; the history has {n}.', fn)
        return r

    # the points where a constant delay carries a jump of the history (or of its derivative) forward
    jumps = [t0]
    ju = _opt(opts, 'Jumps')
    if ju is not None:
        jumps += list(_vec(ju))
    if type(hist) is Struct and 'discont' in hist.keys:
        # an earlier solution carried on: its own jumps travel on too
        jumps += list(_vec(hist.get1('discont')))
    disc = set()
    if lags.size:
        level = sorted(set(jumps))
        for _ in range(3):
            nxt = sorted(set(round(p + L, 14) for p in level for L in lags if p + L < tf))
            disc.update(nxt)
            level = nxt
    disc = sorted(d for d in disc if t0 < d < tf)
    events = _opt(opts, 'Events')
    t = t0
    M.T, M.Y = [t0], [y.copy()]
    f0 = F(t0, y)
    M.F = [f0]
    span = tf - t0
    fi = _opt(opts, 'InitialStep')
    h = float(num(fi)) if fi is not None else min(hmax, 0.01 * span, *(list(lags[lags > 0]) if lags.size else [math.inf]))
    nsteps = nfail = 0
    te, ye, ie = [], [], []
    ev_prev = None
    if isinstance(events, FH):
        ev_prev = np.asarray(darr(events.scall(3, t0, _col(y), delayed(t0, y), *extra)[0]), float).reshape(-1)
    stop = False
    while t < tf and not stop:
        h = min(h, hmax, tf - t)
        nxt_d = next((d for d in disc if d > t + 1e-12 * span), None)
        if nxt_d is not None and t + h > nxt_d:
            h = nxt_d - t
        if h < 16 * np.finfo(float).eps * max(abs(t), 1.0):
            R.warn(f'MATLAB:{fn}:IntegrationTolNotMet', f'Failure at t={t:e}: the step size became too small to meet the tolerances.')
            break
        # a step, the delayed values in it taken from its own interpolant when a delay is shorter than the step
        guess = None
        for _ in range(6):
            M.trial = guess
            k1 = f0
            k2 = F(t + h / 2, y + h / 2 * k1)
            k3 = F(t + 3 * h / 4, y + 3 * h / 4 * k2)
            ynew = y + h * (2 / 9 * k1 + 1 / 3 * k2 + 4 / 9 * k3)
            k4 = F(t + h, ynew)
            short = (lags.size and np.any(lags < h)) or state_dep
            if not short:
                break
            if guess is not None and np.max(np.abs(ynew - guess[3]) / (atol + rtol * np.abs(ynew))) < 1e-3:
                break
            guess = (t, t + h, y, ynew, f0, k4)
        M.trial = None
        errv = h * (-5 / 72 * k1 + 1 / 12 * k2 + 1 / 9 * k3 - 1 / 8 * k4)
        scale = atol + rtol * np.maximum(np.abs(y), np.abs(ynew))
        enorm = float(np.max(np.abs(errv) / scale))
        if enorm > 1:
            nfail += 1
            h *= max(0.1, 0.8 * enorm ** (-1 / 3))
            continue
        tn = t + h
        # events between t and tn, found on the step's interpolant
        if isinstance(events, FH):
            evn = events.scall(3, tn, _col(ynew), delayed(tn, ynew), *extra)
            v1 = np.asarray(darr(evn[0]), float).reshape(-1)
            term = np.asarray(darr(evn[1]), float).reshape(-1)
            dirs = np.asarray(darr(evn[2]), float).reshape(-1)
            hits = []
            for j in range(v1.size):
                a_, b_ = ev_prev[j], v1[j]
                if (a_ < 0 <= b_ or a_ > 0 >= b_ or (b_ == 0 and a_ != 0)) and (dirs.size <= j or dirs[j] == 0 or np.sign(b_ - a_) == np.sign(dirs[j])):
                    from scipy.optimize import brentq

                    def g(s, j=j):
                        ys = _hermite(t, tn, y, ynew, f0, k4, s)
                        return float(np.asarray(darr(events.scall(3, s, _col(ys), delayed(s, ys), *extra)[0]), float).reshape(-1)[j])
                    try:
                        ts = brentq(g, t, tn, xtol=1e-12 * max(1.0, abs(tn))) if a_ != 0 else t
                    except ValueError:
                        ts = tn
                    hits.append((ts, j))
            for ts, j in sorted(hits):
                ys = _hermite(t, tn, y, ynew, f0, k4, ts)
                te.append(ts)
                ye.append(ys)
                ie.append(j + 1)
                if term.size > j and term[j]:
                    ynew = ys
                    tn = ts
                    k4 = F(tn, ynew)
                    stop = True
                    break
            ev_prev = v1
        nsteps += 1
        M.T.append(tn)
        M.Y.append(ynew.copy())
        M.F.append(k4.copy())
        t, y, f0 = tn, ynew, k4
        h *= min(5.0, max(0.2, 0.8 * max(enorm, 1e-10) ** (-1 / 3)))
    T = np.array(M.T)
    fields = {'solver': Char.of(fn), 'history': args[2], 'discont': out(np.array([t0] + disc).reshape(1, -1)),
              'x': out(T.reshape(1, -1)), 'y': out(np.array(M.Y).T), 'yp': out(np.array(M.F).T),
              'stats': Struct.scalar({'nsteps': float(nsteps), 'nfailed': float(nfail), 'nfevals': float(nfe[0])})}
    if fn == 'dde23':
        fields['discont'] = out(np.array([t0] + disc).reshape(1, -1))
    if isinstance(events, FH):
        fields['xe'] = out(np.array(te).reshape(1, -1))
        fields['ye'] = out(np.array(ye).T.reshape(n, -1))
        fields['ie'] = out(np.array(ie, float).reshape(1, -1))
    fields['idata'] = _Holder(lambda xq: M.interp(xq), lambda xq: M.interp(xq, True))
    st = _opt(opts, 'Stats')
    if st is not None and is_str(st) and py_str(st).lower() == 'on':
        R.write(f'{nsteps} successful steps\n{nfail} failed attempts\n{nfe[0]} function evaluations\n')
    return Struct.scalar(fields)


@bi('dde23')
def dde23(nargout, *args):
    """sol = dde23(ddefun, lags, history, tspan), dde23(..., options): y'(t) = f(t, y(t), Z), Z(:, j) = y(t - lags(j)), constant delays."""
    return _dde('dde23', nargout, args)


@bi('ddesd')
def ddesd(nargout, *args):
    """sol = ddesd(ddefun, delays, history, tspan), ddesd(..., options): delays that may depend on t and y: delays(t, y) gives the times at which y is taken (each at most t), or a vector of constant delays."""
    return _dde('ddesd', nargout, args)


# ---- parabolic and elliptic equations in one space variable -----------------------------------------------------------------------------

@bi('pdepe', nout=5, aw=True)
async def pdepe(nargout, *args):
    """sol = pdepe(m, pdefun, icfun, bcfun, xmesh, tspan), pdepe(..., options): c u_t = x^-m (x^m f)_x + s with p + q f = 0 at both ends; sol(i, j, k) is u_k at tspan(i), xmesh(j)."""
    from scipy.integrate import solve_ivp
    from .. import odesolvers as S
    nargchk(args, 6, None, 'pdepe')
    m = float(num(args[0]))
    if m not in (0.0, 1.0, 2.0):
        raise err('MATLAB:pdepe:InvalidM', 'm is 0 (slab), 1 (cylinder) or 2 (sphere).', 'pdepe')
    pdefun, icfun, bcfun = _fn(args[1]), _fn(args[2]), _fn(args[3])
    x = _vec(args[4])
    tspan = _vec(args[5])
    opts = _struct_opts(args[6]) if len(args) > 6 and type(args[6]) is Struct else {}
    extra = args[7:] if len(args) > 6 else ()
    if x.size < 3 or np.any(np.diff(x) <= 0):
        raise err('MATLAB:pdepe:MeshTooShort', 'xmesh has at least three points, increasing.', 'pdepe')
    if tspan.size < 3 or np.any(np.diff(tspan) <= 0):
        raise err('MATLAB:pdepe:TspanTooShort', 'tspan has at least three times, increasing.', 'pdepe')
    if m > 0 and x[0] < 0:
        raise err('MATLAB:pdepe:NegXMesh', 'With m > 0, the mesh starts at 0 or after.', 'pdepe')
    N = x.size
    U0 = np.column_stack([_vec(icfun.scall(1, float(xx), *extra)) for xx in x])     # npde x N
    npde = U0.shape[0]
    xm = (x[:-1] + x[1:]) / 2
    dx = np.diff(x)
    pw = lambda a: a ** m if m else np.ones_like(a)          # noqa: E731

    def vol(a, b):
        return (b ** (m + 1) - a ** (m + 1)) / (m + 1)
    VR = vol(x[:-1], xm)          # node i, its right half (i < N-1)
    VL = vol(xm, x[1:])           # node i+1, its left half
    sym = m > 0 and x[0] == 0
    nfe = [0]

    def coeffs(t, U):
        Um = (U[:, :-1] + U[:, 1:]) / 2
        Ux = (U[:, 1:] - U[:, :-1]) / dx
        C = np.empty((npde, N - 1))
        Fl = np.empty((npde, N - 1))
        Sr = np.empty((npde, N - 1))
        for k in range(N - 1):
            nfe[0] += 1
            c, f_, s_ = pdefun.scall(3, float(xm[k]), float(t), _col(Um[:, k]), _col(Ux[:, k]), *extra)
            C[:, k] = _vec(c, npde, 'c', 'pdepe')
            Fl[:, k] = _vec(f_, npde, 'f', 'pdepe')
            Sr[:, k] = _vec(s_, npde, 's', 'pdepe')
        pl, ql, pr, qr = bcfun.scall(4, float(x[0]), _col(U[:, 0]), float(x[-1]), _col(U[:, -1]), float(t), *extra)
        return C, Fl, Sr, _vec(pl, npde, 'pl', 'pdepe'), _vec(ql, npde, 'ql', 'pdepe'), _vec(pr, npde, 'pr', 'pdepe'), _vec(qr, npde, 'qr', 'pdepe')

    C0, _, _, _, ql0, _, qr0 = coeffs(float(tspan[0]), U0)
    dir_l = (ql0 == 0) & (not sym)
    dir_r = qr0 == 0

    def parts(t, yv):
        U = yv.reshape(N, npde).T
        C, Fl, Sr, pl, ql, pr, qr = coeffs(t, U)
        Fm = pw(xm) * Fl
        rhs = np.zeros((npde, N))
        mass = np.zeros((npde, N))
        rhs[:, 1:-1] = Fm[:, 1:] - Fm[:, :-1] + VL[:-1] * Sr[:, :-1] + VR[1:] * Sr[:, 1:]
        mass[:, 1:-1] = VL[:-1] * C[:, :-1] + VR[1:] * C[:, 1:]
        with np.errstate(divide='ignore', invalid='ignore'):
            fb_l = np.where(ql != 0, -pl / np.where(ql != 0, ql, 1), 0.0)
            fb_r = np.where(qr != 0, -pr / np.where(qr != 0, qr, 1), 0.0)
        left_flux = 0.0 if sym else pw(np.array([x[0]]))[0] * fb_l
        rhs[:, 0] = Fm[:, 0] - left_flux + VR[0] * Sr[:, 0]
        mass[:, 0] = VR[0] * C[:, 0]
        rhs[:, -1] = pw(np.array([x[-1]]))[0] * fb_r - Fm[:, -1] + VL[-1] * Sr[:, -1]
        mass[:, -1] = VL[-1] * C[:, -1]
        rhs[dir_l, 0] = -pl[dir_l]
        mass[dir_l, 0] = 0.0
        rhs[dir_r, -1] = -pr[dir_r]
        mass[dir_r, -1] = 0.0
        return rhs.T.reshape(-1), mass.T.reshape(-1)

    def fun(t, yv):
        return parts(t, yv)[0]

    def mass_fn(t, yv):
        return np.diag(parts(t, yv)[1])

    def jac(t, yv):
        """By differences, columns three nodes apart at once (the equations of a node reach its neighbours only)."""
        n = yv.size
        f0 = fun(t, yv)
        J = np.zeros((n, n))
        for r in range(3):
            for q in range(npde):
                cols = [k * npde + q for k in range(r, N, 3)]
                d = 1e-7 * np.maximum(1.0, np.abs(yv[cols]))
                y2 = yv.copy()
                y2[cols] += d
                df = fun(t, y2) - f0
                for ci, col in enumerate(cols):
                    node = col // npde
                    lo, hi = max(0, node - 1) * npde, min(N, node + 2) * npde
                    J[lo:hi, col] = df[lo:hi] / d[ci]
        return J
    rt, at, msx = _opt(opts, 'RelTol'), _opt(opts, 'AbsTol'), _opt(opts, 'MaxStep')
    kw = {'rtol': float(num(rt)) if rt is not None else 1e-3, 'atol': float(np.max(_vec(at))) if at is not None else 1e-6,
          'max_step': float(num(msx)) if msx is not None else 0.1 * float(tspan[-1] - tspan[0])}
    fs = _opt(opts, 'InitialStep')
    if fs is not None:
        kw['first_step'] = float(num(fs))
    y0 = U0.T.reshape(-1)
    try:
        res = solve_ivp(fun, (float(tspan[0]), float(tspan[-1])), y0, method=S.NDF, t_eval=tspan, mass=mass_fn, jac=jac, **kw)
    except S.SolverError as e:
        raise err('MATLAB:pdepe:Solver', str(e), 'pdepe')
    if res.status == -1 or res.t.size < tspan.size:
        R.warn('MATLAB:pdepe:TimeIntegrationFailed', f'The time integration stopped at t = {res.t[-1] if res.t.size else tspan[0]:g}: '
               'the tolerances could not be met. The solution up to there is given.')
    nt = res.t.size
    sol = res.y.T.reshape(nt, N, npde)
    result = out(sol[:, :, 0]) if npde == 1 else out(sol)
    if nargout > 1:
        return (result, out(res.t.reshape(-1, 1))) + ((EMPTY(),) * (nargout - 2))
    return result


@bi('pdeval', nout=2)
def pdeval(nargout, *args):
    """[uout, duoutdx] = pdeval(m, xmesh, ui, xout): a pdepe solution at one time (ui = sol(j, :, k)) between the mesh points, and its slope, linearly."""
    nargchk(args, 4, 4, 'pdeval')
    x = _vec(args[1])
    u = _vec(args[2])
    if u.size != x.size:
        raise err('MATLAB:pdeval:size', 'ui has a value for each point of xmesh.', 'pdeval')
    xo = np.asarray(darr(args[3]), float)
    shp = xo.shape
    xo = xo.reshape(-1)
    if np.any(xo < x[0]) or np.any(xo > x[-1]):
        raise err('MATLAB:pdeval:outside', 'xout lies within xmesh.', 'pdeval')
    i = np.clip(np.searchsorted(x, xo, side='right') - 1, 0, x.size - 2)
    slope = (u[i + 1] - u[i]) / (x[i + 1] - x[i])
    uo = u[i] + slope * (xo - x[i])
    res = (out(uo.reshape(shp)), out(slope.reshape(shp)))
    return res if nargout > 1 else res[0]


# ---- the ode object -----------------------------------------------------------------------------------------------------------------------

ODE_PROPS = ('ODEFcn', 'InitialTime', 'InitialValue', 'Parameters', 'Jacobian', 'MassMatrix', 'NonNegativeVariables', 'AbsoluteTolerance',
             'RelativeTolerance', 'Solver', 'SolverOptions', 'EquationType')


class OdeProblem(Obj):
    """ode: an initial value problem, its options and the solver chosen."""
    cls = 'ode'

    def __init__(self):
        self.p = {'ODEFcn': EMPTY(), 'InitialTime': 0.0, 'InitialValue': EMPTY(), 'Parameters': EMPTY(), 'Jacobian': EMPTY(),
                  'MassMatrix': EMPTY(), 'NonNegativeVariables': EMPTY(), 'AbsoluteTolerance': 1e-6, 'RelativeTolerance': 1e-3,
                  'Solver': Char.of('auto'), 'SolverOptions': EMPTY(), 'EquationType': Char.of('standard')}

    def value_copy(self):
        o = OdeProblem()
        o.p = dict(self.p)
        return o

    def key(self, name):
        k = next((x for x in ODE_PROPS + ('SelectedSolver',) if x.lower() == name.lower()), None)
        if k is None:
            raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'ode'.")
        return k

    def selected(self):
        s = py_str(self.p['Solver']).lower()
        if s in ('auto', 'nonstiff'):
            return 'ode15s' if (s == 'auto' and numel(self.p['MassMatrix'])) else 'ode45'
        if s == 'stiff':
            return 'ode15s'
        return s

    def getprop(self, name):
        k = self.key(name)
        if k == 'SelectedSolver':
            return Char.of(self.selected())
        return self.p[k]

    def setprop(self, name, value):
        k = self.key(name)
        if k == 'SelectedSolver':
            raise MError('MATLAB:class:SetProhibited', "SelectedSolver follows from Solver: set Solver.")
        if k == 'ODEFcn' and not isinstance(value, FH):
            raise MError('MATLAB:ode:ODEFcn', 'ODEFcn is a function handle, @(t, y) ... (or @(t, y, p) ... with Parameters).')
        if k == 'Solver':
            s = py_str(value).lower()
            if s not in ('auto', 'stiff', 'nonstiff') and s not in _ODE_METHOD:
                raise MError('MATLAB:ode:Solver', f"Solver is 'auto', 'stiff', 'nonstiff' or one of {', '.join(_ODE_METHOD)}.")
            value = Char.of(s)
        if k == 'EquationType' and py_str(value).lower() != 'standard':
            raise MError('MATLAB:ode:EquationType', "Only 'standard' equations (y' = f(t, y), with a mass matrix perhaps) are solved by the ode object here; ode15i solves implicit ones.")
        if k == 'InitialValue':
            value = _col(_vec(value)) if numel(value) > 1 else value
        self.p[k] = value

    def propnames(self):
        return list(ODE_PROPS) + ['SelectedSolver']

    def display_lines(self):
        from ..display import summary
        w = 20
        show = lambda k: f'    {k.rjust(w)}: {summary(self.getprop(k))}'      # noqa: E731
        lines = ['  ode with properties:', '', '   Problem definition']
        lines += [show(k) for k in ('ODEFcn', 'InitialTime', 'InitialValue', 'Parameters', 'Jacobian', 'MassMatrix', 'NonNegativeVariables')]
        lines += ['', '   Solver properties'] + [show(k) for k in ('AbsoluteTolerance', 'RelativeTolerance', 'Solver', 'SelectedSolver')]
        return lines

    def options(self):
        o = {'RelTol': float(num(self.p['RelativeTolerance'])), 'AbsTol': self.p['AbsoluteTolerance']}
        if numel(self.p['Jacobian']):
            o['Jacobian'] = self.p['Jacobian']
        if numel(self.p['MassMatrix']):
            o['Mass'] = self.p['MassMatrix']
        if numel(self.p['NonNegativeVariables']):
            o['NonNegative'] = self.p['NonNegativeVariables']
        so = self.p['SolverOptions']
        if type(so) is Struct and so.size == 1:
            for k in so.keys:
                v = so.get1(k)
                if numel(v):
                    o[k] = v
        return Struct.scalar(o)

    def call_args(self, tspan):
        if not isinstance(self.p['ODEFcn'], FH):
            raise err('MATLAB:ode:noODEFcn', 'The ode has no ODEFcn.', 'solve')
        if not numel(self.p['InitialValue']):
            raise err('MATLAB:ode:noInitialValue', 'The ode has no InitialValue.', 'solve')
        a = [self.p['ODEFcn'], out(np.asarray(tspan, float).reshape(1, -1)), self.p['InitialValue'], self.options()]
        if numel(self.p['Parameters']):
            a.append(self.p['Parameters'])
        return a


class OdeResults(Obj):
    cls = 'ODEResults'

    def __init__(self, T, Y):
        self.p = {'Time': T, 'Solution': Y}

    def getprop(self, name):
        k = next((x for x in self.p if x.lower() == name.lower()), None)
        if k is None:
            raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'ODEResults'.")
        return self.p[k]

    def propnames(self):
        return list(self.p)

    def display_lines(self):
        from ..display import summary
        return ['  ODEResults with properties:', ''] + [f'    {k.rjust(8)}: {summary(v)}' for k, v in self.p.items()]


@bi('ode')
def ode(nargout, *args):
    """F = ode, ode(Name=Value, ...): an initial value problem y' = f(t, y): ODEFcn, InitialValue, InitialTime, Parameters, Solver and the rest, set by name; solve(F, ...) solves it."""
    if len(args) % 2:
        raise err('MATLAB:ode:pairs', 'ode takes names and values (ODEFcn=@(t, y) ..., InitialValue=y0, ...).', 'ode')
    F = OdeProblem()
    for i in range(0, len(args), 2):
        F.setprop(py_str(args[i]), args[i + 1])
    return F


async def _ode_solve(nargout, F, *rest):
    """S = solve(F, tf), solve(F, t0, tf), solve(F, tspan), with 'Refine', k: the solution from InitialTime, at the solver's steps
    (or at the times of tspan when it has more than two)."""
    a = list(rest)
    refine = None
    if len(a) >= 2 and is_str(a[-2]) and py_str(a[-2]).lower() == 'refine':
        refine = a.pop()
        a.pop()
    t0 = float(num(F.p['InitialTime']))
    if len(a) == 1 and numel(a[0]) == 1:
        tspan = np.array([t0, float(num(a[0]))])
    elif len(a) == 1:
        tspan = _vec(a[0])
    elif len(a) == 2:
        tspan = np.array([float(num(a[0])), float(num(a[1]))])
    else:
        raise err('MATLAB:ode:solve', 'solve(F, tf), solve(F, t0, tf) or solve(F, tspan).', 'solve')
    if tspan[0] != t0:
        raise err('MATLAB:ode:InitialTime', f'The times start at InitialTime ({t0:g}).', 'solve')
    call = F.call_args(tspan)
    if refine is not None:
        call[3].f['Refine'] = np.empty((1, 1), object)
        call[3].f['Refine'][0, 0] = refine
    T, Y = await _ode(F.selected(), 2, call)
    T = np.asarray(T, float).reshape(-1)
    Y = np.asarray(Y).reshape(T.size, -1)
    return OdeResults(out(T.reshape(1, -1)), out(Y.T))


@bi('solutionFcn', aw=True)
async def solutionFcn(nargout, *args):
    """f = solutionFcn(F, t0, tf): a function handle giving the solution of an ode at times in [t0, tf] (a column for each time)."""
    nargchk(args, 3, 99, 'solutionFcn')
    F = args[0]
    if not isinstance(F, OdeProblem):
        raise err('MATLAB:solutionFcn:ode', 'solutionFcn takes an ode object.', 'solutionFcn')
    t0, tf = float(num(args[1])), float(num(args[2]))
    if t0 != float(num(F.p['InitialTime'])):
        raise err('MATLAB:ode:InitialTime', 'The interval starts at InitialTime.', 'solutionFcn')
    sol = await _ode(F.selected(), 1, F.call_args(np.array([t0, tf])))
    holder = sol.get1('idata')

    class _Sol(FH):
        def text(self):
            return f'@(t) the solution on [{t0:g}, {tf:g}]'

        def name(self):
            return 'solutionFcn'

        async def acall(self, nargout, *a):
            return self.scall(nargout, *a)

        def scall(self, nargout, *a):
            tq = _vec(a[0])
            if np.any(tq < min(t0, tf) - 1e-12) or np.any(tq > max(t0, tf) + 1e-12):
                raise MError('MATLAB:solutionFcn:outside', f'The times lie within [{t0:g}, {tf:g}].')
            return out(np.asarray(holder.fn(tq), float))
    return _Sol()


def _wrap_solve():
    info = REG['solve']
    orig = info.fn
    ws, aw = info.ws, info.aw

    async def f(*a):
        args = a[2:] if ws else a[1:]
        if args and isinstance(args[0], OdeProblem):
            return await _ode_solve(a[1] if ws else a[0], *args)
        r = orig(*a)
        return (await r) if aw else r
    info.fn = f
    info.aw = True


_wrap_solve()


def _wrap_deval():
    """deval's second output (the derivative) for the solutions that keep one."""
    info = REG['deval']
    orig = info.fn

    def f(nargout, *args):
        if nargout > 1:
            sol, xq = (args[0], args[1]) if type(args[0]) is Struct else (args[1], args[0])
            holder = sol.get1('idata') if type(sol) is Struct and 'idata' in sol.keys else None
            if isinstance(holder, _Holder):
                x = np.asarray(darr(xq), float).reshape(-1)
                idx = [int(i) - 1 for i in _vec(args[2])] if len(args) > 2 else None
                Y, YP = np.asarray(holder.fn(x), float), np.asarray(holder.dfn(x), float)
                if idx is not None:
                    Y, YP = Y[idx], YP[idx]
                return out(Y), out(YP)
        return orig(nargout, *args)
    info.fn = f
    info.nout = max(info.nout, 2)


_wrap_deval()
