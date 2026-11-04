"""Image geometry and transforms: 2-D transformation objects (affine2d,
projective2d, affinetform2d, projtform2d, rigidtform2d, simtform2d,
transltform2d) with transformPointsForward, transformPointsInverse,
invert and outputLimits; imref2d; imwarp; fitgeotrans and fitgeotform2d;
imregcorr; the Hough transform (hough, houghpeaks, houghlines) and circles
(imfindcircles); the Radon transform (radon, iradon) and phantom; dct2,
idct2 and dctmtx.

Points are [x y]: x along the columns, y down the rows, pixel centres at
whole numbers from 1. The legacy objects (affine2d, projective2d) keep T
for row vectors ([x y 1]*T); the others keep A for column vectors
(A*[x; y; 1])."""
import math

import numpy as np

from . import bi as _register
from . import REG
from ._util import err, nargchk, out, num, opt_str, opt_lower, is_str, darr, arr
from .imagecolor import _image, _unit, _as_class
from .imageproc import _back, _planes, _sample, _opts, _method3
from ..values import MError, Char, Cell, Struct, Str, Obj, numel, py_str, EMPTY, F64
from ..graphics_base import HArr
from .. import runtime as R


def bi(*names, **kw):
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError, MemoryError) as e:
                raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0]) from None
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _outs(nargout, *vals):
    return vals[:max(nargout, 1)] if nargout > 1 else vals[0]


def _mat(v, fn):
    return np.asarray(darr(v), F64)


# ---- transformation objects -----------------------------------------------------------------------------------------

class Tform(Obj):
    """A 2-D transformation: A (3-by-3, for column vectors) and its kind."""
    is_handle = False

    def __init__(self, kind, A):
        self.kind = kind
        self.A = np.asarray(A, F64)

    @property
    def cls(self):
        return self.kind

    @property
    def shape(self):
        return (1, 1)

    def value_copy(self):
        return self

    @property
    def projective(self):
        return self.kind in ('projective2d', 'projtform2d')

    def forward(self, P):
        H = np.column_stack([P, np.ones(P.shape[0])]) @ self.A.T
        return H[:, :2] / H[:, 2:3]

    def inverse(self, P):
        H = np.column_stack([P, np.ones(P.shape[0])]) @ np.linalg.inv(self.A).T
        return H[:, :2] / H[:, 2:3]

    def getprop(self, name):
        k = name.lower()
        A = self.A
        if k == 'dimensionality':
            return 2.0
        if k == 't' and self.kind in ('affine2d', 'projective2d'):
            return A.T.copy()
        if k == 'a' and self.kind not in ('affine2d', 'projective2d'):
            return A.copy()
        if self.kind in ('rigidtform2d', 'simtform2d', 'transltform2d'):
            s = math.hypot(A[0, 0], A[1, 0])
            if k == 'translation':
                return A[:2, 2].reshape(1, 2).copy()
            if k == 'r' and self.kind != 'transltform2d':
                return A[:2, :2] / (s if self.kind == 'simtform2d' else 1.0)
            if k == 'rotationangle' and self.kind != 'transltform2d':
                return math.degrees(math.atan2(A[1, 0], A[0, 0]))
            if k == 'scale' and self.kind == 'simtform2d':
                return s
        if name in TFORM_METHODS:
            from ..classdef import BoundBuiltin
            return BoundBuiltin(self, name)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{self.kind}'.")

    def setprop(self, name, value):
        k = name.lower()
        M = np.asarray(darr(value), F64)
        if k == 't' and self.kind in ('affine2d', 'projective2d'):
            self.A = _check(M.T, self.kind)
        elif k == 'a' and self.kind not in ('affine2d', 'projective2d'):
            self.A = _check(M, self.kind)
        else:
            raise MError('MATLAB:class:SetProhibited', f"You cannot set the property '{name}' of {self.kind} here.")

    def propnames(self):
        base = {'affine2d': ['T', 'Dimensionality'], 'projective2d': ['T', 'Dimensionality'], 'affinetform2d': ['A', 'Dimensionality'],
                'projtform2d': ['A', 'Dimensionality'], 'rigidtform2d': ['Dimensionality', 'RotationAngle', 'Translation', 'R', 'A'],
                'simtform2d': ['Dimensionality', 'Scale', 'RotationAngle', 'Translation', 'R', 'A'],
                'transltform2d': ['Dimensionality', 'Translation', 'A']}
        return base[self.kind]

    def display_lines(self):
        from ..display import summary
        names = self.propnames()
        w = max(len(n) for n in names)
        lines = [f'  {self.kind} with properties:', '']
        for n in names:
            v = self.getprop(n)
            if isinstance(v, np.ndarray) and v.shape == (3, 3):
                lines.append(f'    {n.rjust(w)}: [3×3 double]')
            else:
                lines.append(f'    {n.rjust(w)}: {summary(v)}')
        return lines


TFORM_METHODS = {'transformPointsForward', 'transformPointsInverse', 'invert', 'outputLimits', 'isTranslation', 'isRigid', 'isSimilarity'}


def _check(A, kind):
    if A.shape != (3, 3) or not np.all(np.isfinite(A)):
        raise err(f'MATLAB:{kind}:matrix', 'The transformation is a 3-by-3 matrix of finite numbers.', kind)
    if kind not in ('projective2d', 'projtform2d') and not np.allclose(A[2], [0, 0, 1]):
        raise err(f'MATLAB:{kind}:affine', f'An affine transformation\'s matrix ends in [0 0 1] ({"its last column" if kind == "affine2d" else "its last row"}).', kind)
    if abs(np.linalg.det(A)) < 1e-14 * max(1.0, np.abs(A).max() ** 3):
        raise err(f'MATLAB:{kind}:singular', 'The transformation is not invertible.', kind)
    return A


def _rot(theta_deg):
    t = math.radians(theta_deg)
    return np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])


@bi('affine2d', arr=False)
def affine2d(nargout, *args):
    """tform = affine2d(T): a 2-D affine transformation for row vectors, [u v 1] = [x y 1]*T (T 3-by-3, its last column [0; 0; 1]; eye(3) by default)."""
    nargchk(args, 0, 1, 'affine2d')
    T = _mat(args[0], 'affine2d') if args else np.eye(3)
    return Tform('affine2d', _check(T.T, 'affine2d'))


@bi('projective2d', arr=False)
def projective2d(nargout, *args):
    """tform = projective2d(T): a 2-D projective transformation for row vectors, [up vp w] = [x y 1]*T, u = up/w, v = vp/w."""
    nargchk(args, 0, 1, 'projective2d')
    T = _mat(args[0], 'projective2d') if args else np.eye(3)
    return Tform('projective2d', _check(T.T, 'projective2d'))


@bi('affinetform2d', arr=False)
def affinetform2d(nargout, *args):
    """tform = affinetform2d(A): a 2-D affine transformation for column vectors, [u; v; 1] = A*[x; y; 1] (its last row [0 0 1]); or one made from another transformation."""
    nargchk(args, 0, 1, 'affinetform2d')
    if args and isinstance(args[0], Tform):
        if args[0].projective:
            raise err('MATLAB:affinetform2d:projective', 'A projective transformation is not affine.', 'affinetform2d')
        return Tform('affinetform2d', args[0].A.copy())
    A = _mat(args[0], 'affinetform2d') if args else np.eye(3)
    return Tform('affinetform2d', _check(A, 'affinetform2d'))


@bi('projtform2d', arr=False)
def projtform2d(nargout, *args):
    """tform = projtform2d(A): a 2-D projective transformation for column vectors, [up; vp; w] = A*[x; y; 1]."""
    nargchk(args, 0, 1, 'projtform2d')
    if args and isinstance(args[0], Tform):
        return Tform('projtform2d', args[0].A.copy())
    A = _mat(args[0], 'projtform2d') if args else np.eye(3)
    return Tform('projtform2d', _check(A, 'projtform2d'))


@bi('rigidtform2d', arr=False)
def rigidtform2d(nargout, *args):
    """tform = rigidtform2d(theta, t), rigidtform2d(R, t) or rigidtform2d(A): a rotation by theta degrees (counterclockwise as the axes go, x right and y down) and a translation t = [tx ty]."""
    nargchk(args, 0, 2, 'rigidtform2d')
    A = np.eye(3)
    if len(args) == 1:
        A = _check(_mat(args[0], 'rigidtform2d'), 'rigidtform2d')
    elif len(args) == 2:
        r = _mat(args[0], 'rigidtform2d')
        A[:2, :2] = _rot(float(r.reshape(-1)[0])) if r.size == 1 else r
        A[:2, 2] = _mat(args[1], 'rigidtform2d').reshape(-1)[:2]
    if not np.allclose(A[:2, :2].T @ A[:2, :2], np.eye(2), atol=1e-8) or np.linalg.det(A[:2, :2]) < 0:
        raise err('MATLAB:rigidtform2d:rotation', 'The rotation is a proper rotation matrix.', 'rigidtform2d')
    return Tform('rigidtform2d', A)


@bi('simtform2d', arr=False)
def simtform2d(nargout, *args):
    """tform = simtform2d(scale, theta, t), simtform2d(scale, R, t) or simtform2d(A): a scaling, rotation by theta degrees and translation."""
    nargchk(args, 0, 3, 'simtform2d')
    A = np.eye(3)
    if len(args) == 1:
        A = _check(_mat(args[0], 'simtform2d'), 'simtform2d')
    elif len(args) == 3:
        s = float(num(args[0]))
        r = _mat(args[1], 'simtform2d')
        A[:2, :2] = s * (_rot(float(r.reshape(-1)[0])) if r.size == 1 else r)
        A[:2, 2] = _mat(args[2], 'simtform2d').reshape(-1)[:2]
    elif args:
        raise err('MATLAB:simtform2d:nargin', 'simtform2d takes scale, theta and t, or A.', 'simtform2d')
    return Tform('simtform2d', A)


@bi('transltform2d', arr=False)
def transltform2d(nargout, *args):
    """tform = transltform2d(t) or transltform2d(tx, ty): a translation."""
    nargchk(args, 0, 2, 'transltform2d')
    A = np.eye(3)
    if len(args) == 1:
        v = _mat(args[0], 'transltform2d')
        if v.shape == (3, 3):
            A = _check(v, 'transltform2d')
        else:
            A[:2, 2] = v.reshape(-1)[:2]
    elif len(args) == 2:
        A[:2, 2] = [float(num(args[0])), float(num(args[1]))]
    return Tform('transltform2d', A)


def _pts(args, fn):
    """(P as n-by-2, how to give it back) from x, y or an n-by-2 matrix."""
    if len(args) == 1:
        P = _mat(args[0], fn)
        if P.ndim != 2 or P.shape[1] != 2:
            raise err(f'MATLAB:{fn}:points', 'The points are an n-by-2 matrix, or x and y.', fn)
        return P, None
    x, y = _mat(args[0], fn), _mat(args[1], fn)
    if x.shape != y.shape:
        raise err(f'MATLAB:{fn}:points', 'x and y are the same size.', fn)
    return np.column_stack([x.reshape(-1, order='F'), y.reshape(-1, order='F')]), x.shape


def _points_out(nargout, Q, shape):
    if shape is None:
        return Q
    return _outs(nargout, Q[:, 0].reshape(shape, order='F'), Q[:, 1].reshape(shape, order='F'))


def _method(name, fn, cls):
    info = REG.get(name)
    if info is None:
        @bi(name, nout=4, arr=False)
        def own(nargout, *args):
            if args and isinstance(args[0], cls):
                return fn(nargout, *args)
            raise err('MATLAB:UndefinedFunction', f"Undefined function '{name}' for these inputs.", name)
        return
    orig = info.fn
    if info.aw:
        async def f(*a):
            args = a[2:] if info.ws else a[1:]
            if args and isinstance(args[0], cls):
                return fn(a[1] if info.ws else a[0], *args)
            return await orig(*a)
    else:
        def f(*a):
            args = a[2:] if info.ws else a[1:]
            if args and isinstance(args[0], cls):
                return fn(a[1] if info.ws else a[0], *args)
            return orig(*a)
    info.fn = f
    if info.nout != 99:
        info.nout = max(info.nout, 4)


def _tpf(nargout, T, *args):
    P, shape = _pts(args, 'transformPointsForward')
    return _points_out(nargout, T.forward(P), shape)


def _tpi(nargout, T, *args):
    P, shape = _pts(args, 'transformPointsInverse')
    return _points_out(nargout, T.inverse(P), shape)


def _invert(nargout, T, *args):
    return Tform(T.kind, np.linalg.inv(T.A) / (np.linalg.inv(T.A)[2, 2] if T.projective else 1.0))


def _outlim(nargout, T, *args):
    if len(args) != 2:
        raise err('MATLAB:outputLimits:nargin', 'outputLimits takes xLimitsIn and yLimitsIn.', 'outputLimits')
    xl, yl = _mat(args[0], 'outputLimits').reshape(-1), _mat(args[1], 'outputLimits').reshape(-1)
    t = np.linspace(0, 1, 51 if T.projective else 2)
    edges = np.vstack([np.column_stack([xl[0] + t * (xl[1] - xl[0]), np.full(t.size, y)]) for y in yl] +
                      [np.column_stack([np.full(t.size, x), yl[0] + t * (yl[1] - yl[0])]) for x in xl])
    Q = T.forward(edges)
    return _outs(nargout, np.array([[Q[:, 0].min(), Q[:, 0].max()]]), np.array([[Q[:, 1].min(), Q[:, 1].max()]]))


def _is(kind):
    def f(nargout, T, *args):
        L = T.A[:2, :2]
        if T.projective and not np.allclose(T.A[2], [0, 0, 1]):
            return False
        if kind == 'translation':
            return bool(np.allclose(L, np.eye(2)))
        s = math.sqrt(abs(np.linalg.det(L)))
        Q = L / s if s else L
        ok = np.allclose(Q.T @ Q, np.eye(2), atol=1e-9) and np.linalg.det(L) > 0
        return bool(ok and (kind == 'similarity' or abs(s - 1) < 1e-9))
    return f


for _n, _f in (('transformPointsForward', _tpf), ('transformPointsInverse', _tpi), ('invert', _invert), ('outputLimits', _outlim),
               ('isTranslation', _is('translation')), ('isRigid', _is('rigid')), ('isSimilarity', _is('similarity'))):
    _method(_n, _f, Tform)


# ---- spatial referencing ----------------------------------------------------------------------------------------------

class Ref2d(Obj):
    """imref2d: an image's size and where it lies in world coordinates."""
    cls = 'imref2d'
    is_handle = False

    def __init__(self, size, xl, yl):
        self.size = (int(size[0]), int(size[1]))
        self.xl = np.asarray(xl, F64).reshape(2)
        self.yl = np.asarray(yl, F64).reshape(2)

    @property
    def shape(self):
        return (1, 1)

    def value_copy(self):
        return Ref2d(self.size, self.xl.copy(), self.yl.copy())

    @property
    def dx(self):
        return (self.xl[1] - self.xl[0]) / self.size[1]

    @property
    def dy(self):
        return (self.yl[1] - self.yl[0]) / self.size[0]

    def w2i(self, x, y):
        return 0.5 + (x - self.xl[0]) / self.dx, 0.5 + (y - self.yl[0]) / self.dy

    def i2w(self, xi, yi):
        return self.xl[0] + (xi - 0.5) * self.dx, self.yl[0] + (yi - 0.5) * self.dy

    def getprop(self, name):
        k = name.lower()
        m, n = self.size
        vals = {'xworldlimits': self.xl.reshape(1, 2).copy(), 'yworldlimits': self.yl.reshape(1, 2).copy(),
                'imagesize': np.array([[float(m), float(n)]]), 'pixelextentinworldx': float(self.dx),
                'pixelextentinworldy': float(self.dy), 'imageextentinworldx': float(self.xl[1] - self.xl[0]),
                'imageextentinworldy': float(self.yl[1] - self.yl[0]), 'xintrinsiclimits': np.array([[0.5, n + 0.5]]),
                'yintrinsiclimits': np.array([[0.5, m + 0.5]])}
        if k in vals:
            return vals[k]
        if name in REF_METHODS:
            from ..classdef import BoundBuiltin
            return BoundBuiltin(self, name)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class 'imref2d'.")

    def setprop(self, name, value):
        k = name.lower()
        v = np.asarray(darr(value), F64).reshape(-1)
        if k == 'xworldlimits' and v.size == 2 and v[0] < v[1]:
            self.xl = v.copy()
        elif k == 'yworldlimits' and v.size == 2 and v[0] < v[1]:
            self.yl = v.copy()
        elif k == 'imagesize' and v.size >= 2:
            dx, dy = self.dx, self.dy
            self.size = (int(v[0]), int(v[1]))
            self.xl = np.array([self.xl[0], self.xl[0] + dx * self.size[1]])
            self.yl = np.array([self.yl[0], self.yl[0] + dy * self.size[0]])
        else:
            raise MError('MATLAB:class:SetProhibited', f"The property '{name}' of imref2d cannot be set to that.")

    def propnames(self):
        return ['XWorldLimits', 'YWorldLimits', 'ImageSize', 'PixelExtentInWorldX', 'PixelExtentInWorldY', 'ImageExtentInWorldX',
                'ImageExtentInWorldY', 'XIntrinsicLimits', 'YIntrinsicLimits']

    def display_lines(self):
        from ..display import summary
        return ['  imref2d with properties:', ''] + [f'    {n.rjust(19)}: {summary(self.getprop(n))}' for n in self.propnames()]


REF_METHODS = {'worldToIntrinsic', 'intrinsicToWorld', 'worldToSubscript', 'contains', 'sizesMatch'}


@bi('imref2d', arr=False)
def imref2d(nargout, *args):
    """R = imref2d(imageSize), imref2d(imageSize, xWorldLimits, yWorldLimits) or
    imref2d(imageSize, pixelExtentInWorldX, pixelExtentInWorldY): an image's
    place in the world: by default pixel (r, c) is at x = c, y = r, the
    world limits [0.5 n+0.5] and [0.5 m+0.5]."""
    nargchk(args, 0, 3, 'imref2d')
    size = np.asarray(darr(args[0]), F64).reshape(-1)[:2] if args else np.array([2.0, 2.0])
    if size.size == 1:
        size = np.array([size[0], size[0]])
    m, n = int(size[0]), int(size[1])
    xl, yl = np.array([0.5, n + 0.5]), np.array([0.5, m + 0.5])
    if len(args) == 3:
        a, b = np.asarray(darr(args[1]), F64).reshape(-1), np.asarray(darr(args[2]), F64).reshape(-1)
        if a.size == 2:
            xl, yl = a, b
        else:
            xl, yl = np.array([0.5 * a[0], (n + 0.5) * a[0]]), np.array([0.5 * b[0], (m + 0.5) * b[0]])
    elif len(args) == 2:
        raise err('MATLAB:imref2d:nargin', 'imref2d takes the size, then both x and y world limits or pixel extents.', 'imref2d')
    return Ref2d((m, n), xl, yl)


def _w2i(nargout, Rf, *args):
    x, y = _mat(args[0], 'worldToIntrinsic'), _mat(args[1], 'worldToIntrinsic')
    return _outs(nargout, *Rf.w2i(x, y))


def _i2w(nargout, Rf, *args):
    x, y = _mat(args[0], 'intrinsicToWorld'), _mat(args[1], 'intrinsicToWorld')
    return _outs(nargout, *Rf.i2w(x, y))


def _w2s(nargout, Rf, *args):
    x, y = _mat(args[0], 'worldToSubscript'), _mat(args[1], 'worldToSubscript')
    xi, yi = Rf.w2i(x, y)
    m, n = Rf.size
    c, r = np.round(xi), np.round(yi)
    ok = (c >= 1) & (c <= n) & (r >= 1) & (r <= m)
    return _outs(nargout, np.where(ok, r, np.nan), np.where(ok, c, np.nan))


def _contains(nargout, Rf, *args):
    x, y = _mat(args[0], 'contains'), _mat(args[1], 'contains')
    return (x >= Rf.xl[0]) & (x <= Rf.xl[1]) & (y >= Rf.yl[0]) & (y <= Rf.yl[1])


def _sizes(nargout, Rf, *args):
    a = np.asarray(arr(args[0], 'sizesMatch'))
    return a.shape[:2] == Rf.size


for _n, _f in (('worldToIntrinsic', _w2i), ('intrinsicToWorld', _i2w), ('worldToSubscript', _w2s), ('contains', _contains), ('sizesMatch', _sizes)):
    _method(_n, _f, Ref2d)


@bi('imwarp', nout=2)
def imwarp(nargout, *args):
    """[B, RB] = imwarp(A, tform, interp, 'OutputView', Rout, 'FillValues', v):
    A transformed: each output pixel takes the value at the inverse image of
    its centre ('linear' by default, 'nearest' or 'cubic'), FillValues (0)
    outside; the output covers the transformed image (outputLimits, the
    input's pixel extent) unless OutputView says where. imwarp(A, RA, tform)
    places A by RA; imwarp(A, D) moves by a displacement field D (m-by-n-by-2:
    the output pixel (x, y) takes A at (x + D(:,:,1), y + D(:,:,2)))."""
    nargchk(args, 2, 9, 'imwarp')
    a = _image(args[0], 'imwarp')
    rest = list(args[1:])
    RA = None
    if isinstance(rest[0], Ref2d):
        RA = rest.pop(0)
    t = rest.pop(0) if rest else None
    interp = 'linear'
    if rest and is_str(rest[0]) and opt_lower(rest[0]) in ('linear', 'nearest', 'cubic', 'bilinear', 'bicubic'):
        interp = opt_lower(rest.pop(0))
    o, _ = _opts(rest, ('OutputView', 'FillValues', 'SmoothEdges', 'InterpolationMethod'))
    if 'InterpolationMethod' in o:
        interp = opt_lower(o['InterpolationMethod'])
    method = _method3(interp, 'imwarp')
    fill = float(num(o['FillValues'])) if 'FillValues' in o else 0.0
    m, n = a.shape[:2]
    if RA is None:
        RA = Ref2d((m, n), [0.5, n + 0.5], [0.5, m + 0.5])
    planes, back = _planes(a.astype(F64))
    if not isinstance(t, Tform):
        D = np.asarray(darr(t), F64)
        if D.shape != (m, n, 2):
            raise err('MATLAB:imwarp:tform', 'The second input is a geometric transformation or an m-by-n-by-2 displacement field.', 'imwarp')
        Y, X = np.mgrid[1:m + 1, 1:n + 1].astype(F64)
        res = [_sample(p, X + D[:, :, 0], Y + D[:, :, 1], method, fill) for p in planes]
        return _outs(nargout, _back(back(res), a.dtype), RA.value_copy())
    if 'OutputView' in o:
        RB = o['OutputView']
        if not isinstance(RB, Ref2d):
            raise err('MATLAB:imwarp:view', 'OutputView is an imref2d.', 'imwarp')
    else:
        xl, yl = _outlim(2, t, out(RA.xl), out(RA.yl))
        xl, yl = np.asarray(xl).reshape(-1), np.asarray(yl).reshape(-1)
        dx, dy = RA.dx, RA.dy
        nx = max(1, int(round((xl[1] - xl[0]) / dx - 1e-9)) if abs((xl[1] - xl[0]) / dx - round((xl[1] - xl[0]) / dx)) < 1e-6 else int(math.ceil((xl[1] - xl[0]) / dx)))
        ny = max(1, int(round((yl[1] - yl[0]) / dy - 1e-9)) if abs((yl[1] - yl[0]) / dy - round((yl[1] - yl[0]) / dy)) < 1e-6 else int(math.ceil((yl[1] - yl[0]) / dy)))
        RB = Ref2d((ny, nx), [xl[0], xl[0] + nx * dx], [yl[0], yl[0] + ny * dy])
    mo, no = RB.size
    Yi, Xi = np.mgrid[1:mo + 1, 1:no + 1].astype(F64)
    Xw, Yw = RB.i2w(Xi, Yi)
    P = t.inverse(np.column_stack([Xw.reshape(-1), Yw.reshape(-1)]))
    xs, ys = RA.w2i(P[:, 0], P[:, 1])
    xs, ys = xs.reshape(mo, no), ys.reshape(mo, no)
    res = [_sample(p, xs, ys, method, fill) for p in planes]
    return _outs(nargout, _back(back(res), a.dtype if a.dtype != bool else F64) if a.dtype != bool else back(res) > 0.5, RB)


# ---- fitting transformations ---------------------------------------------------------------------------------------------

def _norm(P):
    c = P.mean(axis=0)
    d = np.sqrt(((P - c) ** 2).sum(axis=1)).mean()
    s = math.sqrt(2) / d if d > 0 else 1.0
    T = np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1]])
    return T


def _fit(mov, fix, kind, fn):
    n = mov.shape[0]
    need = {'nonreflectivesimilarity': 2, 'similarity': 2, 'affine': 3, 'projective': 4, 'rigid': 2, 'translation': 1}.get(kind)
    if need is None:
        raise err(f'MATLAB:{fn}:type', f"The transformation type '{kind}' is not fitted here.", fn)
    if n < need:
        raise err(f'MATLAB:{fn}:points', f"A '{kind}' transformation needs at least {need} pairs of points.", fn)
    x, y = mov[:, 0], mov[:, 1]
    u, v = fix[:, 0], fix[:, 1]
    if kind == 'translation':
        A = np.eye(3)
        A[:2, 2] = (fix - mov).mean(axis=0)
        return A
    if kind == 'affine':
        M = np.column_stack([x, y, np.ones(n)])
        sol, *_ = np.linalg.lstsq(M, np.column_stack([u, v]), rcond=None)
        A = np.eye(3)
        A[:2, :] = sol.T
        return A
    if kind == 'projective':
        Tm, Tf = _norm(mov), _norm(fix)
        pm = np.column_stack([mov, np.ones(n)]) @ Tm.T
        pf = np.column_stack([fix, np.ones(n)]) @ Tf.T
        rows = []
        for (a1, b1, _), (a2, b2, _) in zip(pm, pf):
            rows.append([a1, b1, 1, 0, 0, 0, -a2 * a1, -a2 * b1, -a2])
            rows.append([0, 0, 0, a1, b1, 1, -b2 * a1, -b2 * b1, -b2])
        _, _, Vt = np.linalg.svd(np.array(rows))
        H = Vt[-1].reshape(3, 3)
        H = np.linalg.inv(Tf) @ H @ Tm
        return H / H[2, 2]
    if kind in ('nonreflectivesimilarity', 'similarity', 'rigid'):
        # least squares in closed form (Umeyama), a reflection allowed for 'similarity' when it fits better
        mx, mf = mov.mean(axis=0), fix.mean(axis=0)
        X, F = mov - mx, fix - mf
        Sxy = F.T @ X / n
        U, D, Vt = np.linalg.svd(Sxy)
        best = None
        for refl in ((1.0,) if kind != 'similarity' else (1.0, -1.0)):
            S = np.diag([1.0, np.sign(np.linalg.det(U @ Vt)) * refl if refl > 0 else -np.sign(np.linalg.det(U @ Vt))])
            Rm = U @ S @ Vt
            if refl > 0 and np.linalg.det(Rm) < 0 and kind != 'similarity':
                S = np.diag([1.0, -1.0]) if np.linalg.det(U @ Vt) > 0 else np.eye(2)
                Rm = U @ S @ Vt
            var = (X ** 2).sum() / n
            scale = 1.0 if kind == 'rigid' else (np.trace(np.diag(D) @ S) / var if var > 0 else 1.0)
            t = mf - scale * Rm @ mx
            A = np.eye(3)
            A[:2, :2] = scale * Rm
            A[:2, 2] = t
            res = np.sum((mov @ A[:2, :2].T + t - fix) ** 2)
            if best is None or res < best[0] - 1e-12:
                best = (res, A)
        return best[1]


@bi('fitgeotrans', arr=False)
def fitgeotrans(nargout, *args):
    """tform = fitgeotrans(movingPoints, fixedPoints, type): the transformation (an affine2d, or projective2d) taking the moving points to the fixed ones by least squares: 'nonreflectivesimilarity', 'similarity' (a reflection allowed), 'affine' or 'projective'."""
    nargchk(args, 3, 3, 'fitgeotrans')
    mov, fix = _mat(args[0], 'fitgeotrans'), _mat(args[1], 'fitgeotrans')
    if mov.shape != fix.shape or mov.ndim != 2 or mov.shape[1] != 2:
        raise err('MATLAB:fitgeotrans:points', 'The moving and fixed points are n-by-2 matrices of the same size.', 'fitgeotrans')
    kind = opt_lower(args[2])
    A = _fit(mov, fix, kind, 'fitgeotrans')
    return Tform('projective2d' if kind == 'projective' else 'affine2d', A)


@bi('fitgeotform2d', arr=False)
def fitgeotform2d(nargout, *args):
    """tform = fitgeotform2d(movingPoints, fixedPoints, type): the transformation fitted by least squares: 'rigid' (rigidtform2d), 'similarity' (simtform2d), 'affine' (affinetform2d) or 'projective' (projtform2d)."""
    nargchk(args, 3, 3, 'fitgeotform2d')
    mov, fix = _mat(args[0], 'fitgeotform2d'), _mat(args[1], 'fitgeotform2d')
    if mov.shape != fix.shape or mov.ndim != 2 or mov.shape[1] != 2:
        raise err('MATLAB:fitgeotform2d:points', 'The moving and fixed points are n-by-2 matrices of the same size.', 'fitgeotform2d')
    kind = opt_lower(args[2])
    k2 = {'rigid': 'rigid', 'similarity': 'nonreflectivesimilarity', 'affine': 'affine', 'projective': 'projective'}.get(kind)
    if k2 is None:
        raise err('MATLAB:fitgeotform2d:type', "The type is 'rigid', 'similarity', 'affine' or 'projective'.", 'fitgeotform2d')
    A = _fit(mov, fix, k2, 'fitgeotform2d')
    return Tform({'rigid': 'rigidtform2d', 'similarity': 'simtform2d', 'affine': 'affinetform2d', 'projective': 'projtform2d'}[kind], A)


def _phase_peak(a, b, window):
    """The shift d with b(x) ~ a(x - d), by phase correlation with a parabolic peak."""
    if window:
        w = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
        a, b = a * w, b * w
    Fa, Fb = np.fft.fft2(a), np.fft.fft2(b)
    X = Fb * np.conj(Fa)
    X /= np.maximum(np.abs(X), 1e-12)
    c = np.real(np.fft.ifft2(X))
    i, j = np.unravel_index(int(np.argmax(c)), c.shape)
    m, n = c.shape

    def para(v_m, v0, v_p):
        d = v_m - 2 * v0 + v_p
        return 0.5 * (v_m - v_p) / d if d != 0 else 0.0
    di = para(c[(i - 1) % m, j], c[i, j], c[(i + 1) % m, j])
    dj = para(c[i, (j - 1) % n], c[i, j], c[i, (j + 1) % n])
    sy, sx = i + di, j + dj
    if sy > m / 2:
        sy -= m
    if sx > n / 2:
        sx -= n
    return sx, sy, float(c[i, j])


def _logpolar(F, nr, nt):
    m, n = F.shape
    cy, cx = m / 2, n / 2
    rmax = min(cx, cy)
    r = np.exp(np.linspace(0, np.log(rmax), nr))
    t = np.linspace(0, np.pi, nt, endpoint=False)
    R_, T_ = np.meshgrid(r, t, indexing='xy')
    X = cx + R_ * np.cos(T_) + 1
    Y = cy + R_ * np.sin(T_) + 1
    return _sample(F, X, Y, 'bilinear', 0.0), np.log(rmax) / (nr - 1)


@bi('imregcorr', nout=2)
def imregcorr(nargout, *args):
    """[tform, peakcorr] = imregcorr(moving, fixed, transformType, 'Window', tf):
    the transformation taking moving onto fixed by phase correlation:
    'translation' (subpixel, by a parabola through the peak), 'rigid' or
    'similarity' (the rotation and scale first, from the log-polar
    magnitude spectra, Fourier-Mellin), as a transltform2d, rigidtform2d or
    simtform2d. 'Window' (true) tapers the images first."""
    nargchk(args, 2, 5, 'imregcorr')
    mv = _image(args[0], 'imregcorr').astype(F64)
    fx = _image(args[1], 'imregcorr').astype(F64)
    if mv.ndim != 2 or fx.ndim != 2:
        raise err('MATLAB:imregcorr:dims', 'imregcorr takes 2-D images.', 'imregcorr')
    rest = list(args[2:])
    kind = 'similarity'
    if rest and is_str(rest[0]) and opt_lower(rest[0]) in ('translation', 'rigid', 'similarity'):
        kind = opt_lower(rest.pop(0))
    o, _ = _opts(rest, ('Window',))
    window = bool(np.all(np.asarray(darr(o['Window'])) != 0)) if 'Window' in o else True
    m, n = max(mv.shape[0], fx.shape[0]), max(mv.shape[1], fx.shape[1])
    A = np.zeros((m, n))
    B = np.zeros((m, n))
    A[:mv.shape[0], :mv.shape[1]] = mv
    B[:fx.shape[0], :fx.shape[1]] = fx
    ang, scale = 0.0, 1.0
    if kind != 'translation':
        def mag(p):
            w = np.outer(np.hanning(m), np.hanning(n))
            Fm = np.abs(np.fft.fftshift(np.fft.fft2(p * w)))
            # a high-pass emphasis, so the centre does not dominate
            yy, xx = np.meshgrid(np.cos(np.pi * (np.arange(m) / m - 0.5)), np.cos(np.pi * (np.arange(n) / n - 0.5)), indexing='ij')
            return Fm * (1 - yy * xx) * (2 - yy * xx)
        nr, nt = max(m, n), 360
        LA, step = _logpolar(mag(A), nr, nt)
        LB, _ = _logpolar(mag(B), nr, nt)
        sx, sy, _ = _phase_peak(LA, LB, False)
        ang = sy * 180.0 / nt
        scale = math.exp(sx * step) if kind == 'similarity' else 1.0
        best = None
        for a_ in (ang, ang + 180.0):
            T0 = np.eye(3)
            c = np.array([(n + 1) / 2, (m + 1) / 2])
            Rm = scale * _rot(a_)
            T0[:2, :2] = Rm
            T0[:2, 2] = c - Rm @ c
            Bw = np.asarray(darr(imwarp(1, out(A), Tform('affinetform2d', T0), Char.of('OutputView'), Ref2d((m, n), [0.5, n + 0.5], [0.5, m + 0.5]))))
            tx, ty, pk = _phase_peak(Bw, B, window)
            if best is None or pk > best[0]:
                best = (pk, a_, T0, tx, ty)
        pk, ang, T0, tx, ty = best
        Tt = np.eye(3)
        Tt[:2, 2] = [tx, ty]
        Af = Tt @ T0
        res = Tform('simtform2d' if kind == 'similarity' else 'rigidtform2d', Af)
        return _outs(nargout, res, pk)
    tx, ty, pk = _phase_peak(A, B, window)
    At = np.eye(3)
    At[:2, 2] = [tx, ty]
    return _outs(nargout, Tform('transltform2d', At), pk)


# ---- Hough transform -------------------------------------------------------------------------------------------------------

@bi('hough', nout=3)
def hough(nargout, *args):
    """[H, theta, rho] = hough(BW, 'RhoResolution', 1, 'Theta', -90:89): the
    standard Hough transform: for each on pixel (x, y counted from 0) and
    angle theta, a vote at rho = x*cosd(theta) + y*sind(theta), rho from
    -D to D in steps of RhoResolution, D the image's diagonal rounded up to a
    whole step."""
    nargchk(args, 1, 5, 'hough')
    bw = np.asarray(_image(args[0], 'hough')) != 0
    o, _ = _opts(list(args[1:]), ('RhoResolution', 'Theta'))
    res = float(num(o['RhoResolution'])) if 'RhoResolution' in o else 1.0
    th = np.asarray(darr(o['Theta']), F64).reshape(-1) if 'Theta' in o else np.arange(-90.0, 90.0)
    if np.any(th < -90) or np.any(th >= 90):
        raise err('MATLAB:hough:theta', 'Theta lies in [-90, 90).', 'hough')
    M, N = bw.shape
    D = math.sqrt((M - 1) ** 2 + (N - 1) ** 2)
    q = math.ceil(D / res)
    nrho = 2 * q + 1
    rho = np.linspace(-q * res, q * res, nrho)
    y, x = np.nonzero(bw)
    H = np.zeros((nrho, th.size))
    t = np.radians(th)
    for k in range(th.size):
        r = x * math.cos(t[k]) + y * math.sin(t[k])
        idx = np.round((r + q * res) / res).astype(int)
        np.add.at(H[:, k], idx, 1)
    return _outs(nargout, H, th.reshape(1, -1), rho.reshape(1, -1))


@bi('houghpeaks')
def houghpeaks(nargout, *args):
    """peaks = houghpeaks(H, numpeaks, 'Threshold', t, 'NHoodSize', s, 'Theta', theta):
    up to numpeaks (1) [row col] of the largest values of H at least t
    (half the largest), each found then its neighbourhood (the smallest odd
    size at least size(H)/50) set to 0, wrapping in theta with rho reversed."""
    nargchk(args, 1, 8, 'houghpeaks')
    H = np.asarray(darr(args[0]), F64).copy()
    rest = list(args[1:])
    k = 1
    if rest and not is_str(rest[0]):
        k = int(num(rest.pop(0)))
    o, _ = _opts(rest, ('Threshold', 'NHoodSize', 'Theta'))
    thr = float(num(o['Threshold'])) if 'Threshold' in o else 0.5 * float(H.max()) if H.size else 0.0
    if 'NHoodSize' in o:
        hs = np.asarray(darr(o['NHoodSize']), int).reshape(-1)
    else:
        hs = np.array([max(2 * math.ceil(H.shape[0] / 100) + 1, 1), max(2 * math.ceil(H.shape[1] / 100) + 1, 1)])
    hr, hc = int(hs[0]) // 2, int(hs[1]) // 2
    peaks = []
    nr, nc = H.shape
    while len(peaks) < k:
        i, j = np.unravel_index(int(np.argmax(H)), H.shape)
        if H[i, j] < thr or H[i, j] <= 0:
            break
        peaks.append((i + 1.0, j + 1.0))
        for di in range(-hr, hr + 1):
            for dj in range(-hc, hc + 1):
                r, c = i + di, j + dj
                if c < 0 or c >= nc:
                    c = c % nc
                    r = nr - 1 - r
                if 0 <= r < nr:
                    H[r, c] = 0
    return np.array(peaks, F64).reshape(-1, 2)


@bi('houghlines')
def houghlines(nargout, *args):
    """lines = houghlines(BW, theta, rho, peaks, 'FillGap', 20, 'MinLength', 40):
    the line segments of BW along each peak's line: its on pixels near the
    line, ordered along it, joined across gaps up to FillGap pixels, kept
    when at least MinLength long; a struct array of point1 and point2 ([x y]),
    theta and rho."""
    nargchk(args, 4, 8, 'houghlines')
    bw = np.asarray(_image(args[0], 'houghlines')) != 0
    th = np.asarray(darr(args[1]), F64).reshape(-1)
    rho = np.asarray(darr(args[2]), F64).reshape(-1)
    pk = np.asarray(darr(args[3]), F64).reshape(-1, 2)
    o, _ = _opts(list(args[4:]), ('FillGap', 'MinLength'))
    gap = float(num(o['FillGap'])) if 'FillGap' in o else 20.0
    minlen = float(num(o['MinLength'])) if 'MinLength' in o else 40.0
    y, x = np.nonzero(bw)
    res = (rho[-1] - rho[0]) / (rho.size - 1) if rho.size > 1 else 1.0
    lines = []
    for r_i, t_i in pk.astype(int) - 1:
        t, r = th[t_i], rho[r_i]
        c, s = math.cos(math.radians(t)), math.sin(math.radians(t))
        near = np.abs(x * c + y * s - r) <= res / 2 + 1e-9
        px, py = x[near], y[near]
        if px.size == 0:
            continue
        along = -px * s + py * c
        order = np.argsort(along, kind='stable')
        px, py = px[order], py[order]
        d = np.hypot(np.diff(px), np.diff(py))
        cuts = np.flatnonzero(d > gap)
        starts = np.concatenate([[0], cuts + 1])
        ends = np.concatenate([cuts, [px.size - 1]])
        for a_, b_ in zip(starts, ends):
            L = math.hypot(px[b_] - px[a_], py[b_] - py[a_])
            if L >= minlen:
                lines.append({'point1': np.array([[px[a_] + 1.0, py[a_] + 1.0]]), 'point2': np.array([[px[b_] + 1.0, py[b_] + 1.0]]),
                              'theta': float(t), 'rho': float(r)})
    S = Struct.empty((1, len(lines)) if lines else (1, 0), ('point1', 'point2', 'theta', 'rho'))
    for i, ln in enumerate(lines):
        for k_, v in ln.items():
            S.f[k_][0, i] = v
    return S


@bi('imfindcircles', nout=3)
def imfindcircles(nargout, *args):
    """[centers, radii, metric] = imfindcircles(A, radius or [rmin rmax],
    'ObjectPolarity', 'bright', 'Sensitivity', 0.85, 'EdgeThreshold', t):
    circles by a circular Hough transform: each strong edge pixel (Sobel
    gradient above t, Otsu's threshold of the gradient by default) votes
    along its gradient for centres at every radius in the range (towards the
    brighter side, or the darker for 'dark'); peaks of the smoothed votes
    whose support (the fraction of a full circle's votes) is at least
    1 - Sensitivity are centres, each radius the most common distance of the
    voting edge pixels. Sorted by that support, the metric. PyLAB's own
    two-stage method."""
    nargchk(args, 2, 10, 'imfindcircles')
    from scipy import ndimage
    a = _image(args[0], 'imfindcircles')
    if a.ndim == 3:
        a = np.asarray(darr(REG['rgb2gray'].fn(1, args[0])))
    I = np.clip(_unit(a), 0, 1) if a.dtype.kind in 'iub' else a.astype(F64)
    rr = np.asarray(darr(args[1]), F64).reshape(-1)
    rmin, rmax = (rr[0], rr[0]) if rr.size == 1 else (rr[0], rr[1])
    o, _ = _opts(list(args[2:]), ('ObjectPolarity', 'Sensitivity', 'EdgeThreshold', 'Method'))
    pol = opt_lower(o['ObjectPolarity']) if 'ObjectPolarity' in o else 'bright'
    sens = float(num(o['Sensitivity'])) if 'Sensitivity' in o else 0.85
    hy = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], F64)
    gy = ndimage.correlate(I, hy, mode='nearest')
    gx = ndimage.correlate(I, hy.T, mode='nearest')
    mag = np.hypot(gx, gy)
    if 'EdgeThreshold' in o:
        et = float(num(o['EdgeThreshold'])) * mag.max()
    else:
        mm = mag / mag.max() if mag.max() > 0 else mag
        et = float(REG['graythresh'].fn(1, out(mm))) * mag.max()
    ys, xs = np.nonzero(mag > et)
    if xs.size == 0:
        e = np.zeros((0, 2))
        return _outs(nargout, e, np.zeros((0, 1)), np.zeros((0, 1)))
    ux, uy = gx[ys, xs] / mag[ys, xs], gy[ys, xs] / mag[ys, xs]
    sgn = 1.0 if pol == 'bright' else -1.0
    radii = np.arange(rmin, rmax + 0.5, 1.0) if rmax > rmin else np.array([rmin])
    M, N = I.shape
    acc = np.zeros((M, N))
    for r in radii:
        cx = xs + sgn * r * ux
        cy = ys + sgn * r * uy
        ix, iy = np.round(cx).astype(int), np.round(cy).astype(int)
        ok = (ix >= 0) & (ix < N) & (iy >= 0) & (iy < M)
        np.add.at(acc, (iy[ok], ix[ok]), 1.0 / r)
    sm = ndimage.gaussian_filter(acc, 1.0)
    cand = (sm == ndimage.maximum_filter(sm, size=max(3, int(rmin) | 1))) & (sm >= 0.1 * sm.max())
    py, px = np.nonzero(cand)
    edge = ndimage.binary_dilation(mag > et, iterations=1)
    found = []
    for y0, x0 in zip(py, px):
        d = np.hypot(xs - x0, ys - y0)
        dirs = (x0 - xs) * ux + (y0 - ys) * uy
        good = (d >= rmin - 1) & (d <= rmax + 1) & (sgn * dirs > 0.5 * d)
        if not good.any():
            continue
        h, edges = np.histogram(d[good], bins=np.arange(rmin - 1, rmax + 1.51, 0.5))
        k = int(np.argmax(h))
        band = good & (d >= edges[k] - 0.5) & (d < edges[k + 1] + 0.5)
        rad = float(np.mean(d[band])) if band.any() else float(edges[k] + 0.25)
        # the support: the share of points round the circle that lie on an edge
        K = max(16, int(round(2 * math.pi * rad)))
        phi = np.linspace(0, 2 * math.pi, K, endpoint=False)
        qx = np.round(x0 + rad * np.cos(phi)).astype(int)
        qy = np.round(y0 + rad * np.sin(phi)).astype(int)
        inside = (qx >= 0) & (qx < N) & (qy >= 0) & (qy < M)
        support = float(np.mean(edge[qy[inside], qx[inside]])) * inside.mean() if inside.any() else 0.0
        if support >= 1 - sens:
            found.append((support, x0 + 1.0, y0 + 1.0, rad))
    found.sort(key=lambda t: -t[0])
    kept = []
    for f in found:                          # one circle where several candidates crowd together
        if all(math.hypot(f[1] - g[1], f[2] - g[2]) > max(2.0, 0.5 * min(f[3], g[3])) for g in kept):
            kept.append(f)
    found = kept
    C = np.array([[f[1], f[2]] for f in found]).reshape(-1, 2)
    Rr = np.array([f[3] for f in found]).reshape(-1, 1)
    Mt = np.array([f[0] for f in found]).reshape(-1, 1)
    return _outs(nargout, C, Rr, Mt)


# ---- Radon transform ----------------------------------------------------------------------------------------------------

def _radon_size(shape):
    m, n = shape
    c = np.array([(m + 1) // 2, (n + 1) // 2], F64)          # the centre, 1-based
    rad = math.ceil(math.hypot(m - c[0], n - c[1])) + 1
    return c, rad


@bi('radon', nout=2)
def radon(nargout, *args):
    """[R, xp] = radon(I, theta): line integrals of I along lines at the angles
    theta (degrees, 0:179) counterclockwise from the x axis: each pixel split
    into four subpixels whose values are binned linearly by their distance
    xp from the centre floor((size+1)/2) along the angle's direction."""
    nargchk(args, 1, 2, 'radon')
    a = _image(args[0], 'radon').astype(F64)
    if a.ndim != 2:
        raise err('MATLAB:radon:dims', 'radon takes a 2-D image.', 'radon')
    th = np.asarray(darr(args[1]), F64).reshape(-1) if len(args) > 1 else np.arange(180.0)
    m, n = a.shape
    c, rad = _radon_size((m, n))
    xp = np.arange(-rad, rad + 1, dtype=F64)
    Rr = np.zeros((xp.size, th.size))
    rows, cols = np.nonzero(a)
    vals = a[rows, cols] / 4
    xs = cols + 1 - c[1]
    ys = c[0] - (rows + 1)
    for k, t in enumerate(np.radians(th)):
        ct, st = math.cos(t), math.sin(t)
        for dx in (-0.25, 0.25):
            for dy in (-0.25, 0.25):
                p = (xs + dx) * ct + (ys + dy) * st + rad
                i0 = np.floor(p).astype(int)
                w = p - i0
                np.add.at(Rr[:, k], i0, vals * (1 - w))
                np.add.at(Rr[:, k], np.minimum(i0 + 1, xp.size - 1), vals * w)
    return _outs(nargout, Rr, xp.reshape(-1, 1))


def _ramp(name, n, d):
    """The filter's frequency response on n points (n a power of 2), frequency scaled by d."""
    k = np.arange(n // 2 + 1)
    # the ramp built in space and transformed, so its zero frequency is right (Kak and Slaney)
    h = np.zeros(n)
    h[0] = 0.25
    odd = np.arange(1, n // 2 + 1, 2)
    h[odd] = -1 / (np.pi * odd) ** 2
    h[n - odd] = -1 / (np.pi * odd) ** 2
    filt = 2 * np.real(np.fft.fft(h))[:n // 2 + 1]
    w = 2 * np.pi * k / n
    if name in ('ram-lak', 'ramlak'):
        pass
    elif name == 'shepp-logan':
        filt[1:] = filt[1:] * np.sin(w[1:] / (2 * d)) / (w[1:] / (2 * d))
    elif name == 'cosine':
        filt[1:] = filt[1:] * np.cos(w[1:] / (2 * d))
    elif name == 'hamming':
        filt[1:] = filt[1:] * (0.54 + 0.46 * np.cos(w[1:] / d))
    elif name == 'hann':
        filt[1:] = filt[1:] * (1 + np.cos(w[1:] / d)) / 2
    elif name == 'none':
        filt = np.ones(n // 2 + 1)
    else:
        raise err('MATLAB:iradon:filter', "The filter is 'Ram-Lak', 'Shepp-Logan', 'Cosine', 'Hamming', 'Hann' or 'None'.", 'iradon')
    filt[w > np.pi * d] = 0
    return np.concatenate([filt, filt[-2:0:-1]])


@bi('iradon', nout=2)
def iradon(nargout, *args):
    """[I, H] = iradon(R, theta, interp, filter, frequency_scaling, output_size):
    filtered back projection: each projection filtered (Ram-Lak by default,
    or Shepp-Logan, Cosine, Hamming, Hann, None; frequencies above
    frequency_scaling cut) and spread back across the image ('linear'
    interpolation, or 'nearest'), times pi/(2*number of angles); the size
    2*floor(size(R,1)/(2*sqrt(2))) unless given. theta is the angles, or
    their step."""
    nargchk(args, 2, 6, 'iradon')
    Rr = np.asarray(darr(args[0]), F64)
    if Rr.ndim == 1:
        Rr = Rr.reshape(-1, 1)
    th = np.asarray(darr(args[1]), F64).reshape(-1)
    if th.size == 1 and Rr.shape[1] > 1:
        th = th[0] * np.arange(Rr.shape[1])
    if th.size != Rr.shape[1]:
        raise err('MATLAB:iradon:theta', 'theta has an angle for each column of R.', 'iradon')
    interp, filt, d, size = 'linear', 'ram-lak', 1.0, None
    numbers = []
    for r in args[2:]:
        if is_str(r):
            s_ = opt_lower(r)
            if s_ in ('linear', 'nearest', 'spline', 'pchip', 'cubic', 'v5cubic'):
                interp = s_
            else:
                filt = s_
        else:
            numbers.append(float(num(r)))
    # the numbers after the words: frequency_scaling, then output_size (one alone is the scaling if at most 1)
    if len(numbers) == 2:
        d, size = numbers[0], int(numbers[1])
    elif len(numbers) == 1:
        if numbers[0] <= 1:
            d = numbers[0]
        else:
            size = int(numbers[0])
    L = Rr.shape[0]
    if size is None:
        size = 2 * int(math.floor(L / (2 * math.sqrt(2))))
    npad = max(64, 2 ** int(math.ceil(math.log2(2 * L))))
    H = _ramp(filt, npad, d)
    P = np.zeros((npad, Rr.shape[1]))
    P[:L] = Rr
    Pf = np.real(np.fft.ifft(np.fft.fft(P, axis=0) * H[:, None], axis=0))[:L]
    c = (size + 1) // 2 - 1                          # the centre at floor((size+1)/2), as radon's
    xs = np.arange(size) - c
    X, Y = np.meshgrid(xs, -xs)
    ctr = (L + 1) // 2 - 1
    img = np.zeros((size, size))
    for k, t in enumerate(np.radians(th)):
        p = X * math.cos(t) + Y * math.sin(t) + ctr
        col = Pf[:, k]
        if interp == 'nearest':
            idx = np.round(p).astype(int)
            ok = (idx >= 0) & (idx < L)
            img[ok] += col[idx[ok]]
        else:
            i0 = np.floor(p).astype(int)
            w = p - i0
            ok = (i0 >= 0) & (i0 + 1 < L)
            img[ok] += (1 - w[ok]) * col[i0[ok]] + w[ok] * col[i0[ok] + 1]
    img *= np.pi / (2 * th.size)
    return _outs(nargout, img, H[:npad // 2 + 1].reshape(-1, 1))


_SHEPP = np.array([[2, .69, .92, 0, 0, 0], [-.98, .6624, .8740, 0, -.0184, 0], [-.02, .1100, .3100, .22, 0, -18],
                   [-.02, .1600, .4100, -.22, 0, 18], [.01, .2100, .2500, 0, .35, 0], [.01, .0460, .0460, 0, .1, 0],
                   [.01, .0460, .0460, 0, -.1, 0], [.01, .0460, .0230, -.08, -.605, 0], [.01, .0230, .0230, 0, -.606, 0],
                   [.01, .0230, .0460, .06, -.605, 0]])
_MODIFIED = _SHEPP.copy()
_MODIFIED[:, 0] = [1, -.8, -.2, -.2, .1, .1, .1, .1, .1, .1]


@bi('phantom', nout=2)
def phantom(nargout, *args):
    """[P, E] = phantom(type, n) or phantom(E, n): the Shepp-Logan head
    phantom ('Modified Shepp-Logan' by default, with more contrast, or
    'Shepp-Logan'), n-by-n (256): ellipses [A a b x0 y0 phi] on [-1, 1],
    their intensities A added."""
    nargchk(args, 0, 2, 'phantom')
    a = list(args)
    E = _MODIFIED
    n = 256
    if a and is_str(a[0]):
        k = opt_lower(a.pop(0))
        if k in ('shepp-logan',):
            E = _SHEPP
        elif k not in ('modified shepp-logan',):
            raise err('MATLAB:phantom:type', "The type is 'Shepp-Logan' or 'Modified Shepp-Logan'.", 'phantom')
    elif a and np.asarray(darr(a[0])).ndim == 2 and np.asarray(darr(a[0])).shape[1:] == (6,):
        E = np.asarray(darr(a.pop(0)), F64)
    if a:
        n = int(num(a[0]))
    xs = (np.arange(n) - (n - 1) / 2) / ((n - 1) / 2)
    X, Y = np.meshgrid(xs, -xs)
    P = np.zeros((n, n))
    for A, ea, eb, x0, y0, phi in E:
        t = math.radians(phi)
        xr = (X - x0) * math.cos(t) + (Y - y0) * math.sin(t)
        yr = -(X - x0) * math.sin(t) + (Y - y0) * math.cos(t)
        P[(xr / ea) ** 2 + (yr / eb) ** 2 <= 1] += A
    return _outs(nargout, P, E.copy())


# ---- discrete cosine transform -----------------------------------------------------------------------------------------

@bi('dct2')
def dct2(nargout, *args):
    """B = dct2(A, m, n) or dct2(A, [m n]): the two-dimensional discrete cosine transform (DCT-II, orthonormal), A padded with zeros or cut to m-by-n first."""
    nargchk(args, 1, 3, 'dct2')
    from scipy.fft import dctn
    a = np.asarray(darr(args[0]), F64)
    if len(args) > 1:
        s = np.asarray(darr(args[1]), int).reshape(-1)
        m, n = (int(s[0]), int(s[1])) if s.size == 2 else (int(s[0]), int(num(args[2])))
        b = np.zeros((m, n))
        b[:min(m, a.shape[0]), :min(n, a.shape[1])] = a[:m, :n]
        a = b
    if a.ndim == 2 and 1 in a.shape:
        return dctn(a, type=2, norm='ortho', axes=(0 if a.shape[1] == 1 else 1,))
    return dctn(a, type=2, norm='ortho', axes=(0, 1))


@bi('idct2')
def idct2(nargout, *args):
    """A = idct2(B, m, n) or idct2(B, [m n]): the inverse two-dimensional discrete cosine transform (orthonormal), B padded or cut first."""
    nargchk(args, 1, 3, 'idct2')
    from scipy.fft import idctn
    b = np.asarray(darr(args[0]), F64)
    if len(args) > 1:
        s = np.asarray(darr(args[1]), int).reshape(-1)
        m, n = (int(s[0]), int(s[1])) if s.size == 2 else (int(s[0]), int(num(args[2])))
        c = np.zeros((m, n))
        c[:min(m, b.shape[0]), :min(n, b.shape[1])] = b[:m, :n]
        b = c
    if b.ndim == 2 and 1 in b.shape:
        return idctn(b, type=2, norm='ortho', axes=(0 if b.shape[1] == 1 else 1,))
    return idctn(b, type=2, norm='ortho', axes=(0, 1))


@bi('dctmtx')
def dctmtx(nargout, *args):
    """D = dctmtx(n): the n-by-n orthonormal DCT matrix: D*A*D' is dct2(A) for an n-by-n A."""
    nargchk(args, 1, 1, 'dctmtx')
    n = int(num(args[0]))
    if n < 1:
        raise err('MATLAB:dctmtx:n', 'n is a positive whole number.', 'dctmtx')
    k = np.arange(n)[:, None]
    i = np.arange(n)[None, :]
    D = np.sqrt(2 / n) * np.cos(np.pi * (2 * i + 1) * k / (2 * n))
    D[0] /= math.sqrt(2)
    return D
