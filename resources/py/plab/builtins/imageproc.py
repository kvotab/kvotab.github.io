"""Image processing: resizing, rotating, cropping and translating
(imresize, imrotate, imcrop, imtranslate), filters (imfilter, fspecial,
imgaussfilt, medfilt2), edges (edge), contrast (imadjust, stretchlim,
histeq, imhist, imcomplement), thresholds (graythresh, imbinarize),
morphology (strel, imdilate, imerode, imopen, imclose, imfill), connected
components (bwlabel, bwconncomp, regionprops) and tiles of images (imtile,
montage).

Pixels are at whole coordinates: column x and row y, from 1, each pixel
the square from x - 0.5 to x + 0.5. Filters work on the values as they are
and give the image's class back (rounded and saturated for the integer
classes); thresholds and contrast work on the values scaled from 0 to 1.
"""
import math

import numpy as np

from . import bi as _register
from ._util import err, nargchk, out, num, opt_str, is_str, darr
from .imagecolor import _image, _unit, _as_class, _RANGE
from ..values import MError, Obj, Char, Cell, Struct, EMPTY, numel, py_str
from .. import runtime as R


def bi(*names, **kw):
    """Registered as builtins are, with what NumPy or SciPy refuses told as the function's own error."""
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError, MemoryError) as e:
                raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _opts(args, names):
    low = {n.lower(): n for n in names}
    got, rest = {}, []
    i = 0
    while i < len(args):
        s = opt_str(args[i])
        if s is not None and s.lower() in low and i + 1 < len(args):
            got[low[s.lower()]] = args[i + 1]
            i += 2
            continue
        rest.append(args[i])
        i += 1
    return got, rest


def _back(x, dtype):
    """Values computed in float given back in the image's class (rounded and saturated for integers)."""
    dtype = np.dtype(dtype)
    if dtype == bool:
        return x.astype(float)
    if dtype.kind in 'iu':
        info = np.iinfo(dtype)
        with np.errstate(invalid='ignore'):
            return np.clip(np.round(np.nan_to_num(x, nan=0.0)), info.min, info.max).astype(dtype)
    if dtype == np.float32:
        return x.astype(np.float32)
    return x.astype(float)


def _planes(a):
    """An image as 2-D planes (the third and later dimensions in turn) and how to put them back."""
    if a.ndim <= 2:
        return [a.reshape(a.shape[0], -1) if a.ndim == 2 else a.reshape(-1, 1)], lambda ps: ps[0]
    rest = a.shape[2:]
    flat = a.reshape(a.shape[0], a.shape[1], -1, order='F')
    return [flat[:, :, k] for k in range(flat.shape[2])], lambda ps: np.stack(ps, axis=2).reshape(ps[0].shape + rest, order='F')


def _size2(v, fn, what='size'):
    s = darr(v, fn).reshape(-1)
    if s.size == 1:
        return int(s[0]), int(s[0])
    if s.size == 2:
        return int(s[0]), int(s[1])
    raise err(f'MATLAB:{fn}:size', f'The {what} is a number or [rows cols].', fn)


# ---- resampling ------------------------------------------------------------------------------------------------------------

def _cubic(x):
    a = np.abs(x)
    return np.where(a <= 1, 1.5 * a ** 3 - 2.5 * a ** 2 + 1, np.where(a < 2, -0.5 * a ** 3 + 2.5 * a ** 2 - 4 * a + 2, 0.0))


def _lanczos(n):
    def k(x):
        with np.errstate(all='ignore'):
            v = np.sinc(x) * np.sinc(x / n)
        return np.where(np.abs(x) < n, v, 0.0)
    return k


_KERNELS = {
    'nearest': (lambda x: ((x >= -0.5) & (x < 0.5)).astype(float), 1.0),
    'box': (lambda x: ((x >= -0.5) & (x < 0.5)).astype(float), 1.0),
    'bilinear': (lambda x: np.maximum(1 - np.abs(x), 0.0), 2.0),
    'triangle': (lambda x: np.maximum(1 - np.abs(x), 0.0), 2.0),
    'bicubic': (_cubic, 4.0), 'cubic': (_cubic, 4.0),
    'lanczos2': (_lanczos(2), 4.0), 'lanczos3': (_lanczos(3), 6.0),
}


def _weights(n_in, n_out, scale, kernel, width, antialias):
    """The resampling matrix (n_out by n_in) of one dimension: each output sample's weights over the input, the input
    mirrored at its ends; when shrinking with antialiasing the kernel is stretched by 1/scale."""
    if scale < 1 and antialias:
        h = lambda x: scale * kernel(scale * x)  # noqa: E731
        width = width / scale
    else:
        h = kernel
    u = np.arange(1, n_out + 1, dtype=float)
    x = u / scale + 0.5 * (1 - 1 / scale)
    left = np.floor(x - width / 2)
    P = int(math.ceil(width)) + 2
    idx = left[:, None] + np.arange(P)[None, :]
    w = h(x[:, None] - idx)
    s = w.sum(axis=1, keepdims=True)
    w = np.divide(w, s, out=np.zeros_like(w), where=s != 0)
    aux = np.concatenate([np.arange(n_in), np.arange(n_in - 1, -1, -1)])
    j = aux[np.mod(idx.astype(int) - 1, aux.size)]
    M = np.zeros((n_out, n_in))
    np.add.at(M, (np.repeat(np.arange(n_out), P), j.reshape(-1)), w.reshape(-1))
    return M


@bi('imresize')
def imresize(nargout, *args):
    """B = imresize(A, scale), imresize(A, [rows cols]), imresize(..., method, 'Antialiasing', tf): an image made larger or smaller."""
    nargchk(args, 2, 8, 'imresize')
    opts, rest = _opts(list(args[1:]), ('Method', 'Antialiasing', 'OutputSize', 'Scale', 'Colormap', 'Dither'))
    a = _image(args[0], 'imresize')
    method = py_str(opts['Method']).lower() if 'Method' in opts else 'bicubic'
    size = None
    scale = None
    for r in rest:
        if is_str(r):
            method = py_str(r).lower()
        elif size is None and scale is None:
            v = darr(r, 'imresize').reshape(-1)
            if v.size == 1:
                scale = float(v[0])
            elif v.size == 2:
                size = v.astype(float)
            else:
                raise err('MATLAB:imresize:size', 'The size is a scale or [rows cols].', 'imresize')
    if 'Scale' in opts:
        scale = float(darr(opts['Scale']).flat[0])
    if 'OutputSize' in opts:
        size = darr(opts['OutputSize']).reshape(-1).astype(float)
    if method not in _KERNELS:
        raise err('MATLAB:imresize:method', f"The method is one of {', '.join(sorted(_KERNELS))}.", 'imresize')
    m, n = a.shape[0], a.shape[1]
    if size is not None:
        if np.isnan(size[0]) and np.isnan(size[1]):
            raise err('MATLAB:imresize:size', 'Give at least one of the rows and the columns.', 'imresize')
        if np.isnan(size[0]):
            sc = size[1] / n
            size = np.array([math.ceil(m * sc), size[1]])
        elif np.isnan(size[1]):
            sc = size[0] / m
            size = np.array([size[0], math.ceil(n * sc)])
        rows, cols = int(size[0]), int(size[1])
        sr, scl = rows / m, cols / n
    else:
        if scale is None or scale <= 0:
            raise err('MATLAB:imresize:scale', 'The scale is a positive number.', 'imresize')
        rows, cols = int(math.ceil(m * scale)), int(math.ceil(n * scale))
        sr = scl = scale
    anti = bool(num(opts['Antialiasing'])) if 'Antialiasing' in opts else method != 'nearest'
    kernel, width = _KERNELS[method]
    Mr = _weights(m, rows, sr, kernel, width, anti)
    Mc = _weights(n, cols, scl, kernel, width, anti)
    planes, put = _planes(a)
    res = [Mr @ p.astype(float) @ Mc.T for p in planes]
    y = put(res)
    if a.dtype == bool:
        return y > 0.5 if method != 'nearest' else y > 0.5
    return _back(y, a.dtype)


def _sample(img, X, Y, method, fill=0.0):
    """img (2-D) at the points (X, Y) in pixel coordinates (from 1): nearest, bilinear or bicubic (Keys, a = -0.5); fill
    outside the image."""
    m, n = img.shape
    p = np.pad(img.astype(float), 2, constant_values=fill)
    if method == 'nearest':
        c, r = np.round(X).astype(int), np.round(Y).astype(int)
        inside = (c >= 1) & (c <= n) & (r >= 1) & (r <= m)
        v = p[np.clip(r, -1, m + 2) + 1, np.clip(c, -1, n + 2) + 1]
        return np.where(inside, v, fill)
    inside = (X >= 0.5) & (X <= n + 0.5) & (Y >= 0.5) & (Y <= m + 0.5)
    X = np.clip(X, -0.5, n + 1.5)
    Y = np.clip(Y, -0.5, m + 1.5)
    if method == 'bilinear':
        offs, k = (0, 1), lambda t: np.maximum(1 - np.abs(t), 0.0)  # noqa: E731
    else:
        offs, k = (-1, 0, 1, 2), _cubic
    c0, r0 = np.floor(X).astype(int), np.floor(Y).astype(int)
    v = np.zeros(X.shape)
    for dr in offs:
        rr = r0 + dr
        wr = k(Y - rr)
        for dc in offs:
            cc = c0 + dc
            v += wr * k(X - cc) * p[np.clip(rr, -1, m + 2) + 1, np.clip(cc, -1, n + 2) + 1]
    return np.where(inside, v, fill)


def _method3(m, fn):
    m = m.lower()
    m = {'linear': 'bilinear', 'cubic': 'bicubic'}.get(m, m)
    if m not in ('nearest', 'bilinear', 'bicubic'):
        raise err(f'MATLAB:{fn}:method', "The method is 'nearest', 'bilinear' or 'bicubic'.", fn)
    return m


@bi('imrotate')
def imrotate(nargout, *args):
    """B = imrotate(A, angle, method, bbox): the image turned counterclockwise by angle degrees ('nearest' unless asked;
    'loose' keeps all of it, 'crop' the size of A)."""
    nargchk(args, 2, 4, 'imrotate')
    a = _image(args[0], 'imrotate')
    ang = float(darr(args[1]).flat[0])
    words = [py_str(x).lower() for x in args[2:] if is_str(x)]
    method = _method3(next((w for w in words if w not in ('loose', 'crop')), 'nearest'), 'imrotate')
    crop = 'crop' in words
    m, n = a.shape[0], a.shape[1]
    planes, put = _planes(a)
    q = ang / 90
    if q == round(q):
        k = int(round(q)) % 4
        res = [np.rot90(p, k) for p in planes]
        if crop and k % 2 == 1 and m != n:
            # the turned image centred in A's size, cut or padded with zeros
            res = [_center(p, m, n) for p in res]
        y = put(res)
        return y if a.dtype == bool else _back(y, a.dtype) if a.dtype.kind in 'iu' else y.astype(a.dtype)
    t = math.radians(ang)
    ct, st = math.cos(t), math.sin(t)
    if crop:
        M, N = m, n
    else:
        W = abs(n * ct) + abs(m * st)
        H = abs(n * st) + abs(m * ct)
        M, N = int(math.ceil(H - 1e-9)), int(math.ceil(W - 1e-9))
    yy, xx = np.mgrid[1:M + 1, 1:N + 1].astype(float)
    dx, dy = xx - (N + 1) / 2, yy - (M + 1) / 2
    X = ct * dx - st * dy + (n + 1) / 2
    Y = st * dx + ct * dy + (m + 1) / 2
    res = [_sample(p.astype(float), X, Y, method) for p in planes]
    y = put(res)
    if a.dtype == bool:
        return y > 0.5
    return _back(y, a.dtype)


def _center(p, m, n):
    out_ = np.zeros((m, n), p.dtype)
    pm, pn = p.shape
    r0, c0 = (pm - m) // 2, (pn - n) // 2
    for i in range(m):
        si = i + r0
        if 0 <= si < pm:
            j0, j1 = max(0, -c0), min(n, pn - c0)
            out_[i, j0:j1] = p[si, j0 + c0:j1 + c0]
    return out_


@bi('imcrop', nout=2)
def imcrop(nargout, *args):
    """[J, rect] = imcrop(A, rect): the part of the image in rect = [xmin ymin width height] (pixels whose centres lie in it)."""
    nargchk(args, 1, 3, 'imcrop')
    if len(args) < 2:
        raise err('MATLAB:imcrop:rect', 'Give the rectangle to crop: imcrop(A, [xmin ymin width height]) (choosing it with the mouse is not made here).', 'imcrop')
    a = arr_image(args[0], 'imcrop')
    rect = darr(args[-1], 'imcrop').reshape(-1).astype(float)
    if rect.size != 4:
        raise err('MATLAB:imcrop:rect', 'The rectangle is [xmin ymin width height].', 'imcrop')
    m, n = a.shape[0], a.shape[1]
    c0, c1 = int(round(rect[0])), int(round(rect[0] + rect[2]))
    r0, r1 = int(round(rect[1])), int(round(rect[1] + rect[3]))
    c0, r0 = max(c0, 1), max(r0, 1)
    c1, r1 = min(c1, n), min(r1, m)
    J = a[r0 - 1:r1, c0 - 1:c1] if r1 >= r0 and c1 >= c0 else a[0:0, 0:0]
    J = np.ascontiguousarray(J)
    return (J, out(rect.reshape(1, -1))) if nargout > 1 else J


def arr_image(v, fn):
    return _image(v, fn)


@bi('imtranslate', nout=2)
def imtranslate(nargout, *args):
    """B = imtranslate(A, [tx ty], method, 'FillValues', v, 'OutputView', 'same'|'full'): the image moved tx columns right and ty rows down."""
    nargchk(args, 2, 7, 'imtranslate')
    opts, rest = _opts(list(args[2:]), ('FillValues', 'OutputView'))
    a = _image(args[0], 'imtranslate')
    t = darr(args[1], 'imtranslate').reshape(-1).astype(float)
    if t.size < 2:
        raise err('MATLAB:imtranslate:translation', 'The translation is [tx ty].', 'imtranslate')
    method = _method3(py_str(rest[0]) if rest and is_str(rest[0]) else 'linear', 'imtranslate')
    fill = float(darr(opts['FillValues']).flat[0]) if 'FillValues' in opts else 0.0
    view = py_str(opts['OutputView']).lower() if 'OutputView' in opts else 'same'
    m, n = a.shape[0], a.shape[1]
    tx, ty = t[0], t[1]
    if view == 'full':
        x0, x1 = min(1.0, 1 + tx), max(float(n), n + tx)
        y0, y1 = min(1.0, 1 + ty), max(float(m), m + ty)
        N, M = int(math.ceil(x1 - x0 + 1 - 1e-9)), int(math.ceil(y1 - y0 + 1 - 1e-9))
        xs, ys = x0 + np.arange(N), y0 + np.arange(M)
    else:
        xs, ys = np.arange(1, n + 1, dtype=float), np.arange(1, m + 1, dtype=float)
    X, Y = np.meshgrid(xs - tx, ys - ty)
    planes, put = _planes(a)
    if tx == round(tx) and ty == round(ty):
        method = 'nearest'
    res = [_sample(p.astype(float), X, Y, method, fill) for p in planes]
    y = put(res)
    y = y > 0.5 if a.dtype == bool else _back(y, a.dtype)
    return (y, out(np.array([[xs[0] - 0.5, xs[-1] + 0.5], [ys[0] - 0.5, ys[-1] + 0.5]]))) if nargout > 1 else y


# ---- filters ----------------------------------------------------------------------------------------------------------------

_PAD = {'symmetric': 'symmetric', 'replicate': 'edge', 'circular': 'wrap'}


def _correlate(p, h, boundary, full=False):
    """The correlation of the plane p with the kernel h, its centre at floor((size+1)/2), the plane padded by the boundary rule."""
    from scipy.signal import correlate
    kr, kc = h.shape
    cr, cc = (kr + 1) // 2, (kc + 1) // 2
    if full:
        before, after = (kr - 1, kc - 1), (kr - 1, kc - 1)
    else:
        before, after = (cr - 1, cc - 1), (kr - cr, kc - cc)
    q = np.pad(p.astype(float), ((before[0], after[0]), (before[1], after[1])),
               **({'mode': _PAD[boundary]} if isinstance(boundary, str) else {'mode': 'constant', 'constant_values': boundary}))
    method = 'direct' if h.size <= 225 else 'auto'
    return correlate(q, h.astype(float), mode='valid', method=method)


def _boundary(rest, fn):
    boundary, full, conv = 0.0, False, False
    for r in rest:
        if is_str(r):
            w = py_str(r).lower()
            if w in _PAD:
                boundary = w
            elif w == 'full':
                full = True
            elif w == 'same':
                full = False
            elif w == 'conv':
                conv = True
            elif w == 'corr':
                conv = False
            else:
                raise err(f'MATLAB:{fn}:option', f"'{py_str(r)}' is not an option: 'symmetric', 'replicate', 'circular', 'same', 'full', 'corr' or 'conv'.", fn)
        else:
            boundary = float(darr(r).flat[0])
    return boundary, full, conv


@bi('imfilter')
def imfilter(nargout, *args):
    """B = imfilter(A, h, options...): A filtered by the kernel h (correlation unless 'conv'), the edge by zeros or
    'symmetric', 'replicate', 'circular' or a value, the size of A unless 'full'."""
    nargchk(args, 2, 6, 'imfilter')
    a = _image(args[0], 'imfilter')
    h = darr(args[1], 'imfilter').astype(float)
    if h.ndim > 2:
        raise err('MATLAB:imfilter:kernel', 'The kernel is a matrix (2-D).', 'imfilter')
    h = h.reshape(h.shape[0], -1) if h.ndim == 2 else h.reshape(1, -1)
    boundary, full, conv = _boundary(args[2:], 'imfilter')
    if conv:
        # convolution: correlation with the kernel turned half round (its centre found again by the same rule)
        h = h[::-1, ::-1]
    planes, put = _planes(a)
    y = put([_correlate(p, h, boundary, full) for p in planes])
    return _back(y, a.dtype)


def _hsize(v, default):
    if v is None:
        return default
    s = darr(v).reshape(-1)
    return (int(s[0]), int(s[0])) if s.size == 1 else (int(s[0]), int(s[1]))


def _disk(r):
    """The share of each pixel inside the circle of radius r (exact areas), normalized."""
    from scipy.integrate import quad
    R_ = int(math.ceil(r - 0.5))
    k = np.zeros((2 * R_ + 1, 2 * R_ + 1))

    def area(x0, x1, y0, y1):
        def f(x):
            s = math.sqrt(max(r * r - x * x, 0.0))
            return max(0.0, min(y1, s) - max(y0, -s))
        lo, hi = max(x0, -r), min(x1, r)
        if hi <= lo:
            return 0.0
        pts = [x for x in (math.sqrt(max(r * r - y * y, 0)) for y in (y0, y1)) for x in (x, -x) if lo < x < hi]
        return quad(f, lo, hi, points=pts or None, limit=200, epsabs=1e-13, epsrel=1e-12)[0]
    for i in range(-R_, R_ + 1):
        for j in range(-R_, R_ + 1):
            k[i + R_, j + R_] = area(j - 0.5, j + 0.5, i - 0.5, i + 0.5)
    return k / k.sum()


def _motion(length, theta):
    """A line of the length through the centre at theta degrees counterclockwise: each pixel weighted by the length
    of the line inside it (Liang-Barsky clipping), normalized."""
    t = math.radians(theta)
    half = length / 2
    dx, dy = half * math.cos(t), -half * math.sin(t)   # rows grow downwards
    R_ = int(math.ceil(max(abs(dx), abs(dy)) - 0.5 + 1e-9))
    R_ = max(R_, 0)
    k = np.zeros((2 * R_ + 1, 2 * R_ + 1))
    x0, y0, x1, y1 = -dx, -dy, dx, dy
    for i in range(-R_, R_ + 1):
        for j in range(-R_, R_ + 1):
            u0, u1 = 0.0, 1.0
            ok = True
            for p, q in ((-(x1 - x0), x0 - (j - 0.5)), (x1 - x0, (j + 0.5) - x0), (-(y1 - y0), y0 - (i - 0.5)), (y1 - y0, (i + 0.5) - y0)):
                if p == 0:
                    if q < 0:
                        ok = False
                        break
                    continue
                r = q / p
                if p < 0:
                    u0 = max(u0, r)
                else:
                    u1 = min(u1, r)
            if ok and u1 > u0:
                k[i + R_, j + R_] = (u1 - u0) * length
    k[k < 1e-12] = 0
    keep_r = np.flatnonzero(k.any(axis=1))
    keep_c = np.flatnonzero(k.any(axis=0))
    k = k[keep_r.min():keep_r.max() + 1, keep_c.min():keep_c.max() + 1]
    return k / k.sum()


@bi('fspecial')
def fspecial(nargout, *args):
    """h = fspecial(type, ...): a filter kernel: 'average', 'disk', 'gaussian', 'laplacian', 'log', 'motion', 'prewitt', 'sobel' or 'unsharp'."""
    nargchk(args, 1, 3, 'fspecial')
    t = py_str(args[0]).lower()
    p1 = args[1] if len(args) > 1 else None
    p2 = args[2] if len(args) > 2 else None
    if t == 'average':
        r, c = _hsize(p1, (3, 3))
        return np.full((r, c), 1.0 / (r * c))
    if t == 'disk':
        r = float(darr(p1).flat[0]) if p1 is not None else 5.0
        if r <= 0:
            raise err('MATLAB:fspecial:radius', 'The radius is positive.', 'fspecial')
        return _disk(r)
    if t in ('gaussian', 'log'):
        r, c = _hsize(p1, (3, 3) if t == 'gaussian' else (5, 5))
        sigma = float(darr(p2).flat[0]) if p2 is not None else 0.5
        y, x = np.mgrid[-(r - 1) / 2:(r - 1) / 2 + 0.1:1, -(c - 1) / 2:(c - 1) / 2 + 0.1:1]
        h = np.exp(-(x * x + y * y) / (2 * sigma * sigma))
        h[h < np.finfo(float).eps * h.max()] = 0
        h = h / h.sum()
        if t == 'gaussian':
            return h
        h1 = h * (x * x + y * y - 2 * sigma ** 2) / sigma ** 4
        return h1 - h1.sum() / h1.size
    if t in ('laplacian', 'unsharp'):
        a = float(darr(p1).flat[0]) if p1 is not None else 0.2
        if not 0 <= a <= 1:
            raise err('MATLAB:fspecial:alpha', 'alpha is from 0 to 1.', 'fspecial')
        if t == 'laplacian':
            return 4 / (a + 1) * np.array([[a / 4, (1 - a) / 4, a / 4], [(1 - a) / 4, -1, (1 - a) / 4], [a / 4, (1 - a) / 4, a / 4]])
        return np.array([[-a, a - 1, -a], [a - 1, a + 5, a - 1], [-a, a - 1, -a]]) / (a + 1)
    if t == 'motion':
        length = float(darr(p1).flat[0]) if p1 is not None else 9.0
        theta = float(darr(p2).flat[0]) if p2 is not None else 0.0
        return _motion(max(length, 1.0), theta)
    if t == 'prewitt':
        return np.array([[1.0, 1, 1], [0, 0, 0], [-1, -1, -1]])
    if t == 'sobel':
        return np.array([[1.0, 2, 1], [0, 0, 0], [-1, -2, -1]])
    raise err('MATLAB:fspecial:type', "The type is 'average', 'disk', 'gaussian', 'laplacian', 'log', 'motion', 'prewitt', 'sobel' or 'unsharp'.", 'fspecial')


@bi('imgaussfilt')
def imgaussfilt(nargout, *args):
    """B = imgaussfilt(A, sigma, 'FilterSize', s, 'Padding', p): A smoothed by a Gaussian (sigma 0.5 unless given)."""
    nargchk(args, 1, 6, 'imgaussfilt')
    opts, rest = _opts(list(args[1:]), ('FilterSize', 'Padding', 'FilterDomain'))
    a = _image(args[0], 'imgaussfilt')
    s = darr(rest[0]).reshape(-1).astype(float) if rest else np.array([0.5])
    sr, sc = (s[0], s[0]) if s.size == 1 else (s[0], s[1])
    if sr <= 0 or sc <= 0:
        raise err('MATLAB:imgaussfilt:sigma', 'sigma is positive.', 'imgaussfilt')
    if 'FilterSize' in opts:
        fr, fc = _hsize(opts['FilterSize'], None)
    else:
        fr, fc = 2 * int(math.ceil(2 * sr)) + 1, 2 * int(math.ceil(2 * sc)) + 1
    if fr % 2 == 0 or fc % 2 == 0:
        raise err('MATLAB:imgaussfilt:size', 'The filter size is odd.', 'imgaussfilt')
    pad = opts.get('Padding', Char.of('replicate'))
    boundary = py_str(pad).lower() if is_str(pad) else float(darr(pad).flat[0])

    def g(n, s_):
        x = np.arange(n) - (n - 1) / 2
        v = np.exp(-x * x / (2 * s_ * s_))
        return v / v.sum()
    h = np.outer(g(fr, sr), g(fc, sc))
    planes, put = _planes(a)
    return _back(put([_correlate(p, h, boundary) for p in planes]), a.dtype)


@bi('medfilt2')
def medfilt2(nargout, *args):
    """B = medfilt2(A, [m n], padopt): each pixel the median of its m-by-n neighbourhood (3-by-3, zeros beyond the edge, unless asked)."""
    nargchk(args, 1, 3, 'medfilt2')
    a = _image(args[0], 'medfilt2')
    if a.ndim > 2:
        raise err('MATLAB:medfilt2:dims', 'medfilt2 takes a 2-D image.', 'medfilt2')
    size = (3, 3)
    pad = 'zeros'
    for r in args[1:]:
        if is_str(r):
            pad = py_str(r).lower()
        else:
            size = _size2(r, 'medfilt2')
    m, n = size
    cr, cc = (m + 1) // 2, (n + 1) // 2
    widths = ((cr - 1, m - cr), (cc - 1, n - cc))
    x = a.astype(float)
    if pad == 'symmetric':
        q = np.pad(x, widths, mode='symmetric')
    elif pad in ('zeros', 'indexed'):
        q = np.pad(x, widths, constant_values=1.0 if (pad == 'indexed' and a.dtype.kind == 'f') else 0.0)
    else:
        raise err('MATLAB:medfilt2:padopt', "The padding is 'zeros', 'symmetric' or 'indexed'.", 'medfilt2')
    from numpy.lib.stride_tricks import sliding_window_view
    win = sliding_window_view(q, (m, n))
    y = np.median(win.reshape(win.shape[0], win.shape[1], -1), axis=2)
    if a.dtype == bool:
        return y > 0.5
    return _back(y, a.dtype)


# ---- edges -------------------------------------------------------------------------------------------------------------------

def _thin(b, bx, by, cutoff):
    """Edge pixels: above the cutoff and a local maximum across the edge (along x where the x gradient is the larger)."""
    m, n = b.shape
    p = np.pad(b, 1, mode='edge')
    left, right, up, down = p[1:-1, :-2], p[1:-1, 2:], p[:-2, 1:-1], p[2:, 1:-1]
    ax, ay = np.abs(bx), np.abs(by)
    return (b > cutoff) & (((ax >= ay) & (b > left) & (b >= right)) | ((ay >= ax) & (b > up) & (b >= down)))


def _canny(a, thresh, sigma):
    from scipy import ndimage
    n = 8 * int(math.ceil(sigma))
    x = np.arange(-n, n + 1, dtype=float)
    g = np.exp(-x * x / (2 * sigma * sigma))
    g /= g.sum()
    dg = -x * g / (sigma * sigma)
    dg /= np.sum(np.abs(dg)) / 2
    sm = ndimage.correlate1d(ndimage.correlate1d(a, g, axis=0, mode='nearest'), g, axis=1, mode='nearest')
    dx = ndimage.correlate1d(sm, dg, axis=1, mode='nearest')
    dy = ndimage.correlate1d(sm, dg, axis=0, mode='nearest')
    mag = np.hypot(dx, dy)
    mx = mag.max()
    if mx > 0:
        mag = mag / mx
    if thresh is None:
        counts, _ = np.histogram(mag, bins=64, range=(0, 1))
        k = int(np.searchsorted(np.cumsum(counts), 0.7 * mag.size, side='right'))
        high = (k + 1) / 64
        low = 0.4 * high
    else:
        t = np.asarray(thresh, float).reshape(-1)
        high, low = (t[0], 0.4 * t[0]) if t.size == 1 else (t[1], t[0])
    # non-maximum suppression along the gradient, the neighbours interpolated
    m, nn = mag.shape
    p = np.pad(mag, 1)
    ang = np.arctan2(dy, dx)
    ux, uy = np.cos(ang), np.sin(ang)
    yy, xx = np.mgrid[0:m, 0:nn].astype(float)

    def at(xs, ys):
        x0, y0 = np.floor(xs).astype(int), np.floor(ys).astype(int)
        fx, fy = xs - x0, ys - y0

        def g_(r, c):
            return p[np.clip(r, -1, m) + 1, np.clip(c, -1, nn) + 1]
        return (g_(y0, x0) * (1 - fx) * (1 - fy) + g_(y0, x0 + 1) * fx * (1 - fy) + g_(y0 + 1, x0) * (1 - fx) * fy + g_(y0 + 1, x0 + 1) * fx * fy)
    keep = (mag >= at(xx + ux, yy + uy)) & (mag >= at(xx - ux, yy - uy)) & (mag > 0)
    strong = keep & (mag > high)
    weak = keep & (mag > low)
    lab, nlab = ndimage.label(weak, structure=np.ones((3, 3)))
    good = np.unique(lab[strong])
    good = good[good > 0]
    return np.isin(lab, good) & weak, np.array([[low, high]])


@bi('edge', nout=2)
def edge(nargout, *args):
    """[BW, threshOut] = edge(I, method, threshold, ...): edges of a gray image: 'sobel' (unless asked), 'prewitt', 'roberts', 'log', 'zerocross', 'canny' or 'approxcanny'."""
    nargchk(args, 1, 6, 'edge')
    a0 = _image(args[0], 'edge')
    if a0.ndim != 2:
        raise err('MATLAB:edge:dims', 'edge takes a 2-D (gray) image.', 'edge')
    a = _unit(a0)
    rest = list(args[1:])
    method = py_str(rest.pop(0)).lower() if rest and is_str(rest[0]) else 'sobel'
    thresh = None
    if rest and not is_str(rest[0]):
        t = darr(rest.pop(0)).reshape(-1)
        thresh = t if t.size else None
    words = [py_str(r).lower() for r in rest if is_str(r)]
    nums = [r for r in rest if not is_str(r)]
    if method in ('sobel', 'prewitt', 'roberts'):
        if method == 'sobel':
            op = np.array([[-1.0, -2, -1], [0, 0, 0], [1, 2, 1]]) / 8
            by, bx = _correlate(a, op, 'replicate'), _correlate(a, op.T, 'replicate')
        elif method == 'prewitt':
            op = np.array([[-1.0, -1, -1], [0, 0, 0], [1, 1, 1]]) / 6
            by, bx = _correlate(a, op, 'replicate'), _correlate(a, op.T, 'replicate')
        else:
            bx = _correlate(a, np.array([[1.0, 0], [0, -1]]) / 2, 'replicate')
            by = _correlate(a, np.array([[0.0, 1], [-1, 0]]) / 2, 'replicate')
        direction = next((w for w in words if w in ('both', 'horizontal', 'vertical')), 'both')
        if direction == 'horizontal':
            bx = np.zeros_like(bx)
        elif direction == 'vertical':
            by = np.zeros_like(by)
        b = bx * bx + by * by
        cutoff = 4 * b.mean() if thresh is None else float(thresh[0]) ** 2
        if 'nothinning' in words:
            e = b > cutoff
        else:
            e = _thin(b, bx, by, cutoff)
        t_out = math.sqrt(cutoff)
        return (e, t_out) if nargout > 1 else e
    if method in ('log', 'zerocross'):
        if method == 'log':
            sigma = float(darr(nums[0]).flat[0]) if nums else 2.0
            size = int(math.ceil(sigma * 3)) * 2 + 1
            h = fspecial(1, Char.of('log'), float(size), sigma)
        else:
            if not nums:
                raise err('MATLAB:edge:filter', "'zerocross' needs the filter: edge(I, 'zerocross', thresh, h).", 'edge')
            h = darr(nums[0]).astype(float)
        b = _correlate(a, h, 'replicate')
        t = 0.75 * np.mean(np.abs(b)) if thresh is None else float(thresh[0])
        e = np.zeros(b.shape, bool)
        m, n = b.shape
        # a sign change to a neighbour (right or below, either way) with a jump above the threshold, marked at the side nearer zero
        for (s0, s1) in (((slice(None), slice(0, n - 1)), (slice(None), slice(1, n))), ((slice(0, m - 1), slice(None)), (slice(1, m), slice(None)))):
            u, v = b[s0], b[s1]
            cross = ((u < 0) & (v > 0) | (u > 0) & (v < 0)) & (np.abs(u - v) > t)
            nearer_u = np.abs(u) <= np.abs(v)
            e[s0] |= cross & nearer_u
            e[s1] |= cross & ~nearer_u
        return (e, t) if nargout > 1 else e
    if method in ('canny', 'approxcanny'):
        sigma = float(darr(nums[0]).flat[0]) if nums else math.sqrt(2)
        e, t = _canny(a, thresh, sigma)
        return (e, out(t)) if nargout > 1 else e
    raise err('MATLAB:edge:method', "The method is 'sobel', 'prewitt', 'roberts', 'log', 'zerocross', 'canny' or 'approxcanny'.", 'edge')


# ---- contrast and thresholds -------------------------------------------------------------------------------------------------

def _nbins(a):
    return 65536 if a.dtype in (np.dtype(np.uint16), np.dtype(np.int16)) else 256


def _hist(u, n):
    """Counts of the values (0 to 1) in n bins centred at (0:n-1)/(n-1)."""
    idx = np.clip(np.round(u.reshape(-1) * (n - 1)), 0, n - 1).astype(int)
    idx = idx[np.isfinite(u.reshape(-1))] if u.dtype.kind == 'f' else idx
    return np.bincount(idx, minlength=n).astype(float)


@bi('stretchlim')
def stretchlim(nargout, *args):
    """lowhigh = stretchlim(I, tol): the limits leaving out the darkest tol(1) and brightest 1 - tol(2) of the pixels (1 % each unless asked), per colour."""
    nargchk(args, 1, 2, 'stretchlim')
    a = _image(args[0], 'stretchlim')
    tol = darr(args[1]).reshape(-1).astype(float) if len(args) > 1 else np.array([0.01, 0.99])
    if tol.size == 1:
        tol = np.array([tol[0], 1 - tol[0]])
    n = _nbins(a)
    planes = [a] if a.ndim == 2 else [a[:, :, k] for k in range(a.shape[2])]
    res = []
    for p in planes:
        cdf = np.cumsum(_hist(_unit(p), n))
        cdf = cdf / cdf[-1] if cdf[-1] else cdf
        lo = int(np.argmax(cdf > tol[0]))
        hi = int(np.argmax(cdf >= tol[1]))
        res.append([0.0, 1.0] if lo == hi else [lo / (n - 1), hi / (n - 1)])
    return np.array(res, float).T


@bi('imadjust')
def imadjust(nargout, *args):
    """J = imadjust(I, [low_in high_in], [low_out high_out], gamma): intensities mapped between limits (from stretchlim unless given), with a gamma curve."""
    nargchk(args, 1, 4, 'imadjust')
    a = _image(args[0], 'imadjust')
    u = _unit(a)
    nc = a.shape[2] if a.ndim == 3 else 1

    def lim(i, default):
        if len(args) > i and numel(args[i]):
            v = darr(args[i]).astype(float)
            return v.reshape(2, -1) if v.size > 2 else v.reshape(2, 1)
        return default
    lin = lim(1, None)
    if lin is None:
        lin = darr(stretchlim(1, a)).reshape(2, -1) if nc in (1, 3) else np.array([[0.0], [1.0]])
    lout = lim(2, np.array([[0.0], [1.0]]))
    gamma = darr(args[3]).reshape(-1).astype(float) if len(args) > 3 else np.array([1.0])
    planes = [u] if a.ndim == 2 else [u[:, :, k] for k in range(nc)]
    res = []
    for k, p in enumerate(planes):
        li, hi_ = lin[:, min(k, lin.shape[1] - 1)]
        lo, ho = lout[:, min(k, lout.shape[1] - 1)]
        g = gamma[min(k, gamma.size - 1)]
        if hi_ <= li:
            raise err('MATLAB:imadjust:limits', 'low_in is less than high_in.', 'imadjust')
        x = (np.clip(p, li, hi_) - li) / (hi_ - li)
        res.append(lo + (ho - lo) * x ** g)
    y = res[0] if a.ndim == 2 else np.stack(res, axis=2)
    return _as_class(y, a.dtype) if a.dtype != bool else y


@bi('imhist', nout=2)
def imhist(nargout, *args):
    """[counts, binLocations] = imhist(I, n): the image's histogram in n bins (256 unless asked); with no output, drawn."""
    nargchk(args, 1, 2, 'imhist')
    a = _image(args[0], 'imhist')
    n = int(darr(args[1]).flat[0]) if len(args) > 1 else (2 if a.dtype == bool else 256)
    counts = _hist(_unit(a), n)
    lo, hi = _RANGE.get(a.dtype, (0.0, 1.0))
    locs = lo + (hi - lo) * np.arange(n) / (n - 1)
    if nargout == 0:
        R._builtin('stem', locs.reshape(-1, 1), counts.reshape(-1, 1), Char.of('Marker'), Char.of('none'))
        R._builtin('xlim', np.array([[lo, hi]]))
        return None
    return (counts.reshape(-1, 1), locs.reshape(-1, 1)) if nargout > 1 else counts.reshape(-1, 1)


@bi('histeq', nout=2)
def histeq(nargout, *args):
    """[J, T] = histeq(I, n): the intensities spread to n levels (64 unless asked) so that their histogram is about flat."""
    nargchk(args, 1, 2, 'histeq')
    a = _image(args[0], 'histeq')
    if a.ndim > 2:
        raise err('MATLAB:histeq:dims', 'histeq takes a gray image (rgb2gray first, or each plane).', 'histeq')
    n = int(darr(args[1]).flat[0]) if len(args) > 1 else 64
    nb = _nbins(a)
    u = _unit(a)
    cdf = np.cumsum(_hist(u, nb))
    cdf = cdf / cdf[-1] if cdf[-1] else cdf
    T = np.round(cdf * (n - 1)) / (n - 1)
    idx = np.clip(np.round(u * (nb - 1)), 0, nb - 1).astype(int)
    y = T[idx]
    J = _as_class(y, a.dtype) if a.dtype != bool else y
    return (J, out(T.reshape(1, -1))) if nargout > 1 else J


@bi('graythresh', nout=2)
def graythresh(nargout, *args):
    """[level, EM] = graythresh(I): the threshold (0 to 1) of Otsu's method over a 256-bin histogram, and how well it separates."""
    nargchk(args, 1, 1, 'graythresh')
    a = _image(args[0], 'graythresh')
    p = _hist(np.clip(_unit(a), 0, 1), 256)
    total = p.sum()
    if total == 0:
        return (0.0, 0.0) if nargout > 1 else 0.0
    p = p / total
    omega = np.cumsum(p)
    mu = np.cumsum(p * np.arange(1, 257))
    mu_t = mu[-1]
    with np.errstate(divide='ignore', invalid='ignore'):
        sb = (mu_t * omega - mu) ** 2 / (omega * (1 - omega))
    sb = np.where(np.isfinite(sb), sb, -1)
    mx = sb.max()
    if mx <= 0:
        return (0.0, 0.0) if nargout > 1 else 0.0
    k = float(np.mean(np.flatnonzero(sb == mx) + 1))
    level = (k - 1) / 255
    if nargout > 1:
        st = np.sum(p * (np.arange(1, 257) - mu_t) ** 2)
        return level, float(mx / st) if st > 0 else 0.0
    return level


@bi('imbinarize')
def imbinarize(nargout, *args):
    """BW = imbinarize(I), imbinarize(I, T), imbinarize(I, 'global'): pixels brighter than Otsu's threshold (or T, from 0 to 1, a number or an image)."""
    nargchk(args, 1, 6, 'imbinarize')
    a = _image(args[0], 'imbinarize')
    u = _unit(a)
    rest = list(args[1:])
    if rest and is_str(rest[0]):
        m = py_str(rest[0]).lower()
        if m == 'adaptive':
            raise err('MATLAB:imbinarize:adaptive', "PyLAB's imbinarize thresholds the whole image: Otsu's level ('global'), or a level or an image of levels you give.", 'imbinarize')
        if m != 'global':
            raise err('MATLAB:imbinarize:method', "The method is 'global' (or give the threshold).", 'imbinarize')
        rest = rest[1:]
    if rest and not is_str(rest[0]):
        T = darr(rest[0]).astype(float)
        return u > (T if T.size > 1 else float(T.flat[0]))
    return u > graythresh(1, a)


@bi('imcomplement')
def imcomplement(nargout, *args):
    """J = imcomplement(I): the negative image: the class's top less each value (1 - I for double, ~I for logical)."""
    nargchk(args, 1, 1, 'imcomplement')
    a = _image(args[0], 'imcomplement')
    if a.dtype == bool:
        return ~a
    if a.dtype.kind in 'iu':
        info = np.iinfo(a.dtype)
        return (int(info.max) + int(info.min) - a.astype(np.int64)).astype(a.dtype)
    return (1 - a).astype(a.dtype)


# ---- morphology ---------------------------------------------------------------------------------------------------------------

class Strel(Obj):
    cls = 'strel'
    is_handle = False

    def __init__(self, nhood, shape='arbitrary'):
        self.nhood = np.asarray(nhood, bool)
        self.shape = shape

    def display_lines(self):
        h = self.nhood
        return [f'strel is a {self.shape} shaped structuring element with properties:', '',
                f'      Neighborhood: [{h.shape[0]}×{h.shape[1]} logical]', '    Dimensionality: 2']

    def getprop(self, name):
        n = name.lower()
        if n == 'neighborhood':
            return self.nhood.copy()
        if n == 'dimensionality':
            return 2.0
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'strel'.")

    def propnames(self):
        return ['Neighborhood', 'Dimensionality']


def _line_se(length, deg):
    t = math.radians(deg)
    half = (length - 1) / 2
    k = np.linspace(-half, half, max(int(round(length)), 1))
    xs, ys = np.round(k * math.cos(t)).astype(int), np.round(-k * math.sin(t)).astype(int)
    R_ = max(np.abs(xs).max(), np.abs(ys).max())
    h = np.zeros((2 * R_ + 1, 2 * R_ + 1), bool)
    h[ys + R_, xs + R_] = True
    keep_r, keep_c = np.flatnonzero(h.any(axis=1)), np.flatnonzero(h.any(axis=0))
    # trimmed symmetrically so that the centre stays the middle
    tr = min(keep_r.min(), 2 * R_ - keep_r.max())
    tc = min(keep_c.min(), 2 * R_ - keep_c.max())
    return h[tr:2 * R_ + 1 - tr, tc:2 * R_ + 1 - tc]


@bi('strel')
def strel(nargout, *args):
    """SE = strel(shape, ...): a flat structuring element: 'disk' r, 'square' w, 'rectangle' [m n], 'diamond' r, 'line' len deg, 'octagon' r, or a logical neighbourhood."""
    nargchk(args, 1, 3, 'strel')
    if not is_str(args[0]):
        return Strel(darr(args[0], 'strel') != 0)
    s = py_str(args[0]).lower()
    p = [darr(v).reshape(-1).astype(float) for v in args[1:] if not is_str(v)]
    if s == 'arbitrary':
        return Strel(darr(args[1], 'strel') != 0)
    if s == 'disk':
        r = int(p[0][0])
        y, x = np.mgrid[-r:r + 1, -r:r + 1]
        return Strel(x * x + y * y <= r * r, 'disk')
    if s == 'square':
        w = int(p[0][0])
        return Strel(np.ones((w, w), bool), 'square')
    if s == 'rectangle':
        return Strel(np.ones((int(p[0][0]), int(p[0][1])), bool), 'rectangle')
    if s == 'diamond':
        r = int(p[0][0])
        y, x = np.mgrid[-r:r + 1, -r:r + 1]
        return Strel(np.abs(x) + np.abs(y) <= r, 'diamond')
    if s == 'line':
        return Strel(_line_se(p[0][0], p[1][0] if len(p) > 1 else 0.0), 'line')
    if s == 'octagon':
        r = int(p[0][0])
        if r % 3:
            raise err('MATLAB:strel:octagon', 'The octagon\'s r is a multiple of 3.', 'strel')
        k = r // 3 * 2   # the corner cut
        y, x = np.mgrid[-r:r + 1, -r:r + 1]
        return Strel(np.abs(x) + np.abs(y) <= 2 * r - k, 'octagon')
    raise err('MATLAB:strel:shape', "The shape is 'disk', 'square', 'rectangle', 'diamond', 'line', 'octagon' or 'arbitrary'.", 'strel')


def _se(v, fn):
    if isinstance(v, Strel):
        return v.nhood
    return darr(v, fn) != 0


def _morph(a, h, dilate):
    """Flat dilation (max over the reflected neighbourhood) or erosion (min over it); outside the image -inf or +inf."""
    kr, kc = h.shape
    cr, cc = (kr + 1) // 2 - 1, (kc + 1) // 2 - 1
    x = a.astype(float)
    m, n = x.shape
    pad = max(kr, kc)
    fill = -np.inf if dilate else np.inf
    p = np.pad(x, pad, constant_values=fill)
    res = np.full(x.shape, fill)
    for i, j in zip(*np.nonzero(h)):
        di, dj = i - cr, j - cc
        if dilate:
            di, dj = -di, -dj
        res = (np.maximum if dilate else np.minimum)(res, p[pad + di:pad + di + m, pad + dj:pad + dj + n])
    return res


def _morph_out(a, y):
    if a.dtype == bool:
        return y > 0.5
    if a.dtype.kind in 'iu':
        info = np.iinfo(a.dtype)
        return np.clip(y, info.min, info.max).astype(a.dtype)
    return y.astype(a.dtype)


def _morph_fn(name, ops):
    @bi(name)
    def f(nargout, *args):
        nargchk(args, 2, 2, name)
        a = _image(args[0], name)
        if a.ndim > 2:
            raise err(f'MATLAB:{name}:dims', f'{name} takes a 2-D image.', name)
        h = _se(args[1], name)
        y = a
        for d in ops:
            y = _morph_out(a, _morph(y, h, d))
        return y
    f.__doc__ = f'{name}(A, SE): ' + {'imdilate': 'the image dilated by the structuring element (the largest value under it).',
                                      'imerode': 'the image eroded by the structuring element (the smallest value under it).',
                                      'imopen': 'erosion then dilation: bright details smaller than the element taken away.',
                                      'imclose': 'dilation then erosion: dark gaps smaller than the element filled.'}[name]
    return f


_morph_fn('imdilate', (True,))
_morph_fn('imerode', (False,))
_morph_fn('imopen', (False, True))
_morph_fn('imclose', (True, False))


@bi('imfill')
def imfill(nargout, *args):
    """BW2 = imfill(BW, 'holes'), imfill(BW, locations, conn): the holes of a binary image filled (background not reached from the edge), or the background flooded from the locations."""
    nargchk(args, 2, 3, 'imfill')
    from scipy import ndimage
    a = _image(args[0], 'imfill')
    if a.ndim > 2:
        raise err('MATLAB:imfill:dims', 'imfill takes a 2-D image.', 'imfill')
    if a.dtype != bool and not np.all((a == 0) | (a == 1)):
        raise err('MATLAB:imfill:binary', 'imfill takes a binary (logical) image here.', 'imfill')
    bw = a != 0
    conn = 4
    if len(args) > 2 and not is_str(args[2]):
        conn = int(darr(args[2]).flat[0])
    st = np.ones((3, 3), bool) if conn == 8 else np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool)
    if is_str(args[1]):
        if py_str(args[1]).lower() != 'holes':
            raise err('MATLAB:imfill:option', "imfill(BW, 'holes') or imfill(BW, locations).", 'imfill')
        return ndimage.binary_fill_holes(bw, structure=st)
    loc = darr(args[1]).astype(int)
    m, n = bw.shape
    if loc.ndim == 2 and loc.shape[1] == 2 and loc.size > 1:
        idx = [(int(r) - 1, int(c) - 1) for r, c in loc]
    else:
        idx = [divmod(int(k) - 1, m)[::-1] for k in loc.reshape(-1)]
    lab, _ = ndimage.label(~bw, structure=st)
    fill = np.zeros_like(bw)
    for r, c in idx:
        if 0 <= r < m and 0 <= c < n and lab[r, c] > 0:
            fill |= lab == lab[r, c]
    return bw | fill


# ---- connected components ------------------------------------------------------------------------------------------------------

def _label(bw, conn):
    """Labels of the connected components numbered in the order their first pixel comes down the columns."""
    from scipy import ndimage
    st = np.ones((3, 3), bool) if conn == 8 else np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool)
    lab, n = ndimage.label(bw, structure=st)
    if n == 0:
        return lab.astype(float), 0
    flat = lab.reshape(-1, order='F')
    first = np.full(n + 1, flat.size)
    nz = np.flatnonzero(flat)
    np.minimum.at(first, flat[nz], nz)
    order = np.argsort(first[1:], kind='stable')
    remap = np.zeros(n + 1)
    remap[order + 1] = np.arange(1, n + 1)
    return remap[lab], n


def _conn(args, k, fn):
    c = int(darr(args[k]).flat[0]) if len(args) > k else 8
    if c not in (4, 8):
        raise err(f'MATLAB:{fn}:conn', 'The connectivity is 4 or 8.', fn)
    return c


@bi('bwlabel', nout=2)
def bwlabel(nargout, *args):
    """[L, n] = bwlabel(BW, conn): the connected components numbered 1, 2, ... (8-connected unless 4)."""
    nargchk(args, 1, 2, 'bwlabel')
    a = _image(args[0], 'bwlabel')
    if a.ndim > 2:
        raise err('MATLAB:bwlabel:dims', 'bwlabel takes a 2-D image.', 'bwlabel')
    L, n = _label(a != 0, _conn(args, 1, 'bwlabel'))
    return (L, float(n)) if nargout > 1 else L


@bi('bwconncomp')
def bwconncomp(nargout, *args):
    """CC = bwconncomp(BW, conn): the connected components: Connectivity, ImageSize, NumObjects and PixelIdxList."""
    nargchk(args, 1, 2, 'bwconncomp')
    a = _image(args[0], 'bwconncomp')
    conn = _conn(args, 1, 'bwconncomp')
    L, n = _label(a != 0, conn)
    flat = L.reshape(-1, order='F')
    lists = Cell.empty((1, n))
    for k in range(n):
        lists.a[0, k] = (np.flatnonzero(flat == k + 1) + 1).astype(float).reshape(-1, 1)
    return Struct.scalar({'Connectivity': float(conn), 'ImageSize': np.array([[float(a.shape[0]), float(a.shape[1])]]),
                          'NumObjects': float(n), 'PixelIdxList': lists})


_BASIC = ('Area', 'Centroid', 'BoundingBox')
_SHAPE = ('Area', 'Centroid', 'BoundingBox', 'MajorAxisLength', 'MinorAxisLength', 'Eccentricity', 'Orientation', 'EquivDiameter',
          'Extent', 'PixelIdxList', 'PixelList', 'FilledArea', 'ConvexArea', 'Solidity')
_INTENSITY = ('MeanIntensity', 'MaxIntensity', 'MinIntensity', 'WeightedCentroid', 'PixelValues')


def _region(rows, cols, shape, props, I):
    m = shape[0]
    d = {}
    A = rows.size
    x, y = cols + 1.0, rows + 1.0
    xb, yb = x.mean(), y.mean()
    if 'Area' in props:
        d['Area'] = float(A)
    if 'Centroid' in props:
        d['Centroid'] = np.array([[xb, yb]])
    bb = np.array([[x.min() - 0.5, y.min() - 0.5, x.max() - x.min() + 1, y.max() - y.min() + 1]])
    if 'BoundingBox' in props:
        d['BoundingBox'] = bb
    if {'MajorAxisLength', 'MinorAxisLength', 'Eccentricity', 'Orientation'} & set(props):
        xc, yc = x - xb, -(y - yb)
        uxx = np.mean(xc * xc) + 1 / 12
        uyy = np.mean(yc * yc) + 1 / 12
        uxy = np.mean(xc * yc)
        common = math.sqrt((uxx - uyy) ** 2 + 4 * uxy ** 2)
        major = 2 * math.sqrt(2) * math.sqrt(uxx + uyy + common)
        minor = 2 * math.sqrt(2) * math.sqrt(max(uxx + uyy - common, 0))
        if 'MajorAxisLength' in props:
            d['MajorAxisLength'] = major
        if 'MinorAxisLength' in props:
            d['MinorAxisLength'] = minor
        if 'Eccentricity' in props:
            d['Eccentricity'] = 2 * math.sqrt(max((major / 2) ** 2 - (minor / 2) ** 2, 0)) / major
        if 'Orientation' in props:
            if uyy > uxx:
                nu, de = uyy - uxx + common, 2 * uxy
            else:
                nu, de = 2 * uxy, uxx - uyy + common
            d['Orientation'] = 0.0 if nu == 0 and de == 0 else math.degrees(math.atan(nu / de)) if de != 0 else 90.0
    if 'EquivDiameter' in props:
        d['EquivDiameter'] = math.sqrt(4 * A / math.pi)
    if 'Extent' in props:
        d['Extent'] = A / (bb[0, 2] * bb[0, 3])
    if 'PixelIdxList' in props:
        d['PixelIdxList'] = np.sort(cols * m + rows + 1.0).reshape(-1, 1)
    if 'PixelList' in props:
        o = np.argsort(cols * m + rows, kind='stable')
        d['PixelList'] = np.column_stack([x[o], y[o]])
    if {'FilledArea'} & set(props):
        from scipy import ndimage
        r0, c0 = rows.min(), cols.min()
        sub = np.zeros((rows.max() - r0 + 1, cols.max() - c0 + 1), bool)
        sub[rows - r0, cols - c0] = True
        d['FilledArea'] = float(ndimage.binary_fill_holes(sub, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool)).sum())
    if {'ConvexArea', 'Solidity'} & set(props):
        ca = _convex_area(x, y)
        if 'ConvexArea' in props:
            d['ConvexArea'] = ca
        if 'Solidity' in props:
            d['Solidity'] = A / ca if ca else 1.0
    if I is not None:
        v = I[rows, cols].astype(float)
        if 'MeanIntensity' in props:
            d['MeanIntensity'] = float(v.mean())
        if 'MaxIntensity' in props:
            d['MaxIntensity'] = float(v.max())
        if 'MinIntensity' in props:
            d['MinIntensity'] = float(v.min())
        if 'WeightedCentroid' in props:
            s = v.sum()
            d['WeightedCentroid'] = np.array([[np.sum(x * v) / s, np.sum(y * v) / s]]) if s else np.array([[np.nan, np.nan]])
        if 'PixelValues' in props:
            o = np.argsort(cols * m + rows, kind='stable')
            d['PixelValues'] = v[o].reshape(-1, 1)
    return d


def _convex_area(x, y):
    """The number of pixels whose centres lie in the convex hull of the region's pixel squares."""
    from scipy.spatial import ConvexHull, QhullError
    pts = np.concatenate([np.column_stack([x + dx, y + dy]) for dx in (-0.5, 0.5) for dy in (-0.5, 0.5)])
    try:
        hull = ConvexHull(pts)
    except (QhullError, ValueError):
        return float(x.size)
    eq = hull.equations
    xs, ys = np.meshgrid(np.arange(x.min(), x.max() + 1), np.arange(y.min(), y.max() + 1))
    P = np.column_stack([xs.reshape(-1), ys.reshape(-1)])
    inside = np.all(P @ eq[:, :2].T + eq[:, 2] <= 1e-9, axis=1)
    return float(inside.sum())


@bi('regionprops')
def regionprops(nargout, *args):
    """stats = regionprops(BW or L or CC, I, properties...), regionprops('table', ...): measurements of each region
    ('basic' gives Area, Centroid and BoundingBox)."""
    nargchk(args, 1, 30, 'regionprops')
    args = list(args)
    as_table = False
    if is_str(args[0]) and py_str(args[0]).lower() == 'table':
        as_table = True
        args = args[1:]
    src = args[0]
    I = None
    rest = args[1:]
    if rest and not is_str(rest[0]) and type(rest[0]) is not Cell:
        I = darr(rest[0], 'regionprops')
        rest = rest[1:]
    names = []
    for r in rest:
        names += [py_str(x) for x in (r.a.reshape(-1) if type(r) is Cell else [r])]
    allp = {p.lower(): p for p in _SHAPE + _INTENSITY}
    props = []
    for nm in names or ['basic']:
        k = nm.lower()
        if k == 'basic':
            props += list(_BASIC)
        elif k == 'all':
            props += list(_SHAPE) + (list(_INTENSITY) if I is not None else [])
        elif k in allp:
            if allp[k] in _INTENSITY and I is None:
                raise err('MATLAB:regionprops:intensity', f'{allp[k]} needs the intensity image: regionprops(L, I, ...).', 'regionprops')
            props.append(allp[k])
        else:
            raise err('MATLAB:regionprops:property', f"'{nm}' is not a property here: one of {', '.join(_SHAPE + _INTENSITY)}, 'basic' or 'all'.", 'regionprops')
    props = list(dict.fromkeys(props))
    if isinstance(src, Struct) and 'PixelIdxList' in src.f:
        shape = tuple(int(v) for v in darr(src.get1('ImageSize')).reshape(-1)[:2])
        lists = [np.asarray(darr(c)).reshape(-1).astype(int) - 1 for c in src.get1('PixelIdxList').a.reshape(-1)]
        regions = [(k % shape[0], k // shape[0]) for k in lists]
    else:
        a = _image(src, 'regionprops')
        if a.ndim > 2:
            raise err('MATLAB:regionprops:dims', 'regionprops takes a 2-D image.', 'regionprops')
        shape = a.shape
        if a.dtype == bool:
            L, n = _label(a, 8)
        else:
            L = a.astype(float)
            n = int(L.max()) if L.size else 0
        regions = []
        for k in range(1, n + 1):
            r, c = np.nonzero(L == k)
            regions.append((r, c))
    recs = []
    for r, c in regions:
        if r.size == 0:
            recs.append({p: (EMPTY() if p not in ('Area',) else 0.0) for p in props})
        else:
            recs.append(_region(np.asarray(r), np.asarray(c), shape, props, I))
    if as_table:
        from .tables import Table
        vars_ = []
        for p in props:
            vals = [rc[p] for rc in recs]
            if all(np.ndim(v) == 0 or (isinstance(v, np.ndarray) and v.shape[0] == 1) for v in vals) and not p.endswith('List') and p != 'PixelValues':
                vars_.append(np.vstack([np.atleast_2d(np.asarray(v, float)) for v in vals]) if vals else np.zeros((0, 1)))
            else:
                cc = Cell.empty((len(vals), 1))
                for i, v in enumerate(vals):
                    cc.a[i, 0] = v
                vars_.append(cc)
        return Table(vars_, props, None, len(recs))
    return _records(recs, props)


def _records(recs, keys):
    """A struct array (a column) of the records."""
    s = Struct.empty((len(recs), 1), keys)
    for i, rc in enumerate(recs):
        for k in keys:
            s.f[k][i, 0] = rc[k]
    return s


# ---- tiles of images ------------------------------------------------------------------------------------------------------------

def _frames(v, fn):
    """Images from a cell array or an M-by-N-by-1-or-3-by-K array (an M-by-N-by-K array: K gray images)."""
    if type(v) is Cell:
        return [_image(x, fn) for x in v.a.reshape(-1, order='F')]
    a = _image(v, fn)
    if a.ndim == 4:
        return [a[:, :, :, k] if a.shape[2] == 3 else a[:, :, 0, k] for k in range(a.shape[3])]
    if a.ndim == 3 and a.shape[2] != 3:
        return [a[:, :, k] for k in range(a.shape[2])]
    return [a]


@bi('imtile')
def imtile(nargout, *args):
    """out = imtile(images, 'GridSize', [rows cols], 'BorderSize', b, 'BackgroundColor', c): images side by side in one image, row by row."""
    nargchk(args, 1, 9, 'imtile')
    opts, rest = _opts(list(args[1:]), ('GridSize', 'BorderSize', 'BackgroundColor', 'ThumbnailSize', 'Frames'))
    ims = _frames(args[0], 'imtile')
    if 'Frames' in opts:
        ims = [ims[int(k) - 1] for k in darr(opts['Frames']).reshape(-1)]
    K = len(ims)
    if not K:
        return np.zeros((0, 0))
    color = any(x.ndim == 3 for x in ims)
    dtype = np.result_type(*[x.dtype for x in ims]) if len({x.dtype for x in ims}) > 1 else ims[0].dtype
    if dtype == bool:
        dtype = np.dtype(np.uint8) if color else np.dtype(bool)
    if 'ThumbnailSize' in opts:
        th, tw = _size2(opts['ThumbnailSize'], 'imtile')
    else:
        th, tw = ims[0].shape[0], ims[0].shape[1]
    if 'GridSize' in opts:
        g = darr(opts['GridSize']).reshape(-1).astype(float)
        gr, gc = g[0], g[1]
        if np.isnan(gr):
            gr = math.ceil(K / gc)
        if np.isnan(gc):
            gc = math.ceil(K / gr)
        gr, gc = int(gr), int(gc)
    else:
        gc = int(math.ceil(math.sqrt(K * th / tw)))
        gr = int(math.ceil(K / gc))
    b = _size2(opts['BorderSize'], 'imtile') if 'BorderSize' in opts else (0, 0)
    H, Wd = gr * th + (gr + 1) * b[0] if b[0] else gr * th, gc * tw + (gc + 1) * b[1] if b[1] else gc * tw
    nc = 3 if color else 1
    canvas = np.zeros((H, Wd, nc))
    if 'BackgroundColor' in opts:
        bg = darr(opts['BackgroundColor']).reshape(-1).astype(float)
        canvas[:] = bg[:nc] if bg.size >= nc else bg[0]
    for k, im in enumerate(ims[:gr * gc]):
        u = _unit(im)
        if im.shape[0] != th or im.shape[1] != tw:
            u = imresize(1, u, np.array([[float(th), float(tw)]]))
        if u.ndim == 2:
            u = np.repeat(u[:, :, None], nc, axis=2) if nc == 3 else u[:, :, None]
        i, j = divmod(k, gc)
        r0 = i * th + (i + 1) * b[0] if b[0] else i * th
        c0 = j * tw + (j + 1) * b[1] if b[1] else j * tw
        canvas[r0:r0 + th, c0:c0 + tw, :] = u
    y = canvas if color else canvas[:, :, 0]
    return _as_class(y, dtype) if dtype != bool else y > 0.5


@bi('montage', arr=False)
def montage(nargout, *args):
    """montage(images, ...): the images shown side by side in one image (imtile's options); h = montage(...) gives the image object."""
    nargchk(args, 1, 9, 'montage')
    rest = list(args[1:])
    if rest and not is_str(rest[0]):
        rest = rest[1:]      # a colormap for indexed images: shown as gray here
    tiled = imtile(1, args[0], *rest)
    h = R._builtin('imshow', tiled)
    return h if nargout else None
