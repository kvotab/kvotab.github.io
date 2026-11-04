"""Images and colours: the image classes (im2double, im2uint8, ...), RGB to
gray, HSV and lightness, indexed images (ind2rgb, ind2gray, gray2ind,
rgb2ind with minimum variance quantization and Floyd-Steinberg dithering),
mat2gray and imsplit.

An image is an M-by-N (gray, indexed) or M-by-N-by-3 (RGB) array; a
colormap a c-by-3 array of values from 0 to 1. Images of class double and
single hold values from 0 to 1, uint8, uint16 and int16 images the whole
range of their class. Indexed images of class double count colours from 1,
of uint8 and uint16 from 0."""
import numpy as np

from . import bi
from ._util import err, nargchk, out, num, opt_str, arr

# the weights rgb2gray gives red, green and blue (the luma of NTSC's YIQ, from the inverse of its matrix)
_GRAY = np.array([0.298936021293775, 0.587043074451121, 0.114020904255103])
_RANGE = {np.dtype(np.uint8): (0.0, 255.0), np.dtype(np.uint16): (0.0, 65535.0), np.dtype(np.int16): (-32768.0, 32767.0)}


def _image(v, fn, what='image'):
    a = arr(v, fn)
    if a.dtype.kind == 'c':
        raise err(f'MATLAB:{fn}:invalidType', f'The {what} must be real.', fn)
    if a.dtype.kind not in 'fbiu':
        raise err(f'MATLAB:{fn}:invalidType', f'The {what} must be numeric or logical.', fn)
    return a


def _unit(a):
    """An image's values as float64 from 0 to 1 (double and single as they are)."""
    if a.dtype == bool:
        return a.astype(float)
    if a.dtype in _RANGE:
        lo, hi = _RANGE[a.dtype]
        return (a.astype(float) - lo) / (hi - lo)
    if a.dtype.kind in 'iu':
        info = np.iinfo(a.dtype)
        return (a.astype(float) - info.min) / (float(info.max) - info.min)
    return a.astype(float)


def _as_class(d, dtype):
    """Values from 0 to 1 as an image of the class (rounded and clipped for the integer classes)."""
    dtype = np.dtype(dtype)
    if dtype in _RANGE:
        lo, hi = _RANGE[dtype]
        with np.errstate(invalid='ignore'):
            x = np.round(np.clip(np.nan_to_num(d, nan=0.0), 0, 1) * (hi - lo) + lo)
        return x.astype(dtype)
    if dtype == np.float32:
        return d.astype(np.float32)
    return d.astype(float)


def _class_of(a):
    return a.dtype if a.dtype in _RANGE or a.dtype == np.float32 else np.dtype(float)


def _map(v, fn):
    m = _image(v, fn, 'colormap')
    if m.ndim != 2 or m.shape[1] != 3:
        raise err(f'MATLAB:{fn}:invalidColormap', 'The colormap must be a c-by-3 array.', fn)
    m = m.astype(float)
    if m.size and (np.any(m < 0) or np.any(m > 1) or not np.all(np.isfinite(m))):
        raise err(f'MATLAB:{fn}:invalidColormap', 'The colormap values must be from 0 to 1.', fn)
    return m


def _rgb_or_map(v, fn):
    """('image', array) for an M-by-N-by-3 image, ('map', array) for a c-by-3 colormap."""
    a = _image(v, fn)
    if a.ndim == 3 and a.shape[2] == 3:
        return 'image', a
    if a.ndim == 2 and a.shape[1] == 3:
        return 'map', a
    raise err(f'MATLAB:{fn}:invalidInput', 'The input must be an M-by-N-by-3 image or a c-by-3 colormap.', fn)


# ---- the image classes -----------------------------------------------------------------------------------

def _indexed(args, fn):
    if len(args) > 1:
        o = opt_str(args[1])
        if o is None or o.lower() != 'indexed':
            raise err(f'MATLAB:{fn}:invalidOption', "The option is 'indexed'.", fn)
        return True
    return False


@bi('im2double')
def im2double(nargout, *args):
    """im2double(I): the image as double, values from 0 to 1; im2double(X, 'indexed') counts colours from 1."""
    nargchk(args, 1, 2, 'im2double')
    a = _image(args[0], 'im2double')
    if _indexed(args, 'im2double'):
        return out(a.astype(float) + (1.0 if a.dtype.kind in 'iub' else 0.0))
    return out(_unit(a))


@bi('im2single')
def im2single(nargout, *args):
    """im2single(I): the image as single, values from 0 to 1."""
    nargchk(args, 1, 2, 'im2single')
    a = _image(args[0], 'im2single')
    if _indexed(args, 'im2single'):
        return out((a.astype(float) + (1.0 if a.dtype.kind in 'iub' else 0.0)).astype(np.float32))
    return out(_unit(a).astype(np.float32))


def _to_int_image(args, fn, dtype):
    nargchk(args, 1, 2, fn)
    a = _image(args[0], fn)
    top = 255 if dtype == np.uint8 else 65535
    if _indexed(args, fn):
        x = a.astype(float) - (1.0 if a.dtype.kind == 'f' else 0.0)
        if x.size and (np.any(x < 0) or np.any(x > top) or np.any(x != np.round(x))):
            raise err(f'MATLAB:{fn}:tooManyColors', f'An indexed image of class {np.dtype(dtype).name} counts at most {top + 1} colours, from 0.', fn)
        return out(x.astype(dtype))
    if a.dtype == np.dtype(dtype):
        return out(a)
    return out(_as_class(_unit(a), dtype))


@bi('im2uint8')
def im2uint8(nargout, *args):
    """im2uint8(I): the image as uint8, values from 0 to 255; im2uint8(X, 'indexed') counts colours from 0."""
    return _to_int_image(args, 'im2uint8', np.uint8)


@bi('im2uint16')
def im2uint16(nargout, *args):
    """im2uint16(I): the image as uint16, values from 0 to 65535."""
    return _to_int_image(args, 'im2uint16', np.uint16)


# ---- gray ----------------------------------------------------------------------------------------------

def _gray_of(a):
    """The weighted sum of the last dimension's three values, in float64 on the values as they are."""
    return a.astype(float) @ _GRAY


@bi('rgb2gray')
def rgb2gray(nargout, *args):
    """rgb2gray(RGB): the gray image, 0.2989 R + 0.5870 G + 0.1140 B, of the
    same class; rgb2gray(map): the gray colormap."""
    nargchk(args, 1, 1, 'rgb2gray')
    kind, a = _rgb_or_map(args[0], 'rgb2gray')
    if kind == 'map':
        m = _map(a, 'rgb2gray')
        g = np.clip(_gray_of(m), 0, 1)
        return out(np.repeat(g[:, None], 3, axis=1))
    if a.dtype == bool:
        a = a.astype(float)
    g = _gray_of(a)
    if a.dtype in _RANGE:
        lo, hi = _RANGE[a.dtype]
        return out(np.clip(np.round(g), lo, hi).astype(a.dtype))
    return out(g.astype(a.dtype if a.dtype == np.float32 else float))


@bi('im2gray')
def im2gray(nargout, *args):
    """im2gray(I): an RGB image made gray as rgb2gray does; a gray image as it is."""
    nargchk(args, 1, 1, 'im2gray')
    a = _image(args[0], 'im2gray')
    if a.ndim == 2:
        return out(a)
    if a.ndim == 3 and a.shape[2] == 3:
        return rgb2gray(1, a)
    raise err('MATLAB:im2gray:invalidInput', 'The image must be M-by-N (gray) or M-by-N-by-3 (RGB).', 'im2gray')


@bi('cmap2gray')
def cmap2gray(nargout, *args):
    """cmap2gray(map): the colormap made gray, each colour's gray level in all three columns."""
    nargchk(args, 1, 1, 'cmap2gray')
    m = _map(args[0], 'cmap2gray')
    return out(np.repeat(np.clip(_gray_of(m), 0, 1)[:, None], 3, axis=1))


@bi('mat2gray')
def mat2gray(nargout, *args):
    """mat2gray(A): A scaled from its least (0) to its largest (1);
    mat2gray(A, [amin amax]) from amin to amax, values beyond clipped."""
    nargchk(args, 1, 2, 'mat2gray')
    a = _image(args[0], 'mat2gray', 'matrix').astype(float)
    if len(args) > 1 and np.asarray(arr(args[1], 'mat2gray')).size:
        lim = np.asarray(arr(args[1], 'mat2gray'), float).reshape(-1)
        if lim.size != 2:
            raise err('MATLAB:mat2gray:invalidLimits', 'The limits are [amin amax].', 'mat2gray')
        lo, hi = float(lim[0]), float(lim[1])
    else:
        fin = a[np.isfinite(a)]
        lo, hi = (float(fin.min()), float(fin.max())) if fin.size else (0.0, 1.0)
    if hi == lo:
        # no range to scale over: the values as they are, clipped to 0 to 1
        return out(np.clip(a, 0, 1))
    return out(np.clip((a - lo) / (hi - lo), 0, 1))


# ---- HSV and lightness ---------------------------------------------------------------------------------------

def _float_class(a):
    return np.float32 if a.dtype == np.float32 else float


def _three(args, fn):
    """The three planes of rgb2hsv(R, G, B) or hsv2rgb(H, S, V) as one array, of their class when they share one."""
    parts = [np.asarray(arr(x, fn)) for x in args]
    if any(p.shape != parts[0].shape for p in parts):
        raise err(f'MATLAB:{fn}:sizeMismatch', 'The three inputs must be the same size.', fn)
    if any(p.dtype != parts[0].dtype for p in parts):
        parts = [_unit(p) for p in parts]
    return np.stack(parts, axis=-1)


@bi('rgb2hsv')
def rgb2hsv(nargout, *args):
    """rgb2hsv(RGB) or rgb2hsv(map): hue, saturation and value, each from 0 to 1."""
    nargchk(args, 1, 3, 'rgb2hsv')
    if len(args) == 3:
        a = _three(args, 'rgb2hsv')
        kind = 'split'
    else:
        kind, a = _rgb_or_map(args[0], 'rgb2hsv')
    cls = _float_class(a)
    c = _unit(a)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    v = c.max(axis=-1)
    d = v - c.min(axis=-1)
    with np.errstate(invalid='ignore', divide='ignore'):
        s = np.where(v > 0, d / np.where(v > 0, v, 1), 0.0)
        h = np.zeros_like(v)
        dd = np.where(d > 0, d, 1)
        h = np.where(b == v, 4 + (r - g) / dd, h)
        h = np.where(g == v, 2 + (b - r) / dd, h)
        h = np.where(r == v, (g - b) / dd, h)
        h = np.where(d > 0, (h / 6) % 1.0, 0.0)
    res = np.stack([h, s, v], axis=-1).astype(cls)
    if kind == 'split' and nargout > 1:
        return out(res[..., 0]), out(res[..., 1]), out(res[..., 2])
    return out(res)


@bi('hsv2rgb')
def hsv2rgb(nargout, *args):
    """hsv2rgb(HSV) or hsv2rgb(map): red, green and blue from hue, saturation and value (each from 0 to 1)."""
    nargchk(args, 1, 3, 'hsv2rgb')
    if len(args) == 3:
        a = _three(args, 'hsv2rgb')
        kind = 'split'
    else:
        kind, a = _rgb_or_map(args[0], 'hsv2rgb')
    cls = _float_class(a)
    c = _unit(a)                           # an integer image's values scaled to 0 to 1
    h, s, v = c[..., 0], c[..., 1], c[..., 2]
    h6 = (h % 1.0) * 6
    i = np.floor(h6).astype(int) % 6
    f = h6 - np.floor(h6)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    res = np.stack([r, g, b], axis=-1).astype(cls)
    if kind == 'split' and nargout > 1:
        return out(res[..., 0]), out(res[..., 1]), out(res[..., 2])
    return out(res)


# the row of sRGB's matrix (D65) that gives the luminance Y
_Y = np.array([0.2126729, 0.7151522, 0.0721750])


@bi('rgb2lightness')
def rgb2lightness(nargout, *args):
    """rgb2lightness(rgb): the lightness L* (0 to 100) of CIE 1976 L*a*b* of
    sRGB colours (D65 white): an M-by-N image's of an M-by-N-by-3 image, a
    column of a c-by-3 colormap's."""
    nargchk(args, 1, 1, 'rgb2lightness')
    kind, a = _rgb_or_map(args[0], 'rgb2lightness')
    cls = _float_class(a)
    c = _unit(a)
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    Y = lin @ _Y
    e = (6 / 29) ** 3
    f = np.where(Y > e, np.cbrt(np.maximum(Y, 0)), Y / (3 * (6 / 29) ** 2) + 4 / 29)
    L = 116 * f - 16
    return out(L.astype(cls) if kind == 'image' else L.reshape(-1, 1).astype(cls))


# ---- indexed images ---------------------------------------------------------------------------------------

def _indices(X, ncolors, fn):
    """0-based colour numbers of an indexed image, clipped to the colormap."""
    x = _image(X, fn, 'indexed image')
    if x.dtype.kind == 'f':
        k = np.floor(x.astype(float)) - 1
    else:
        k = x.astype(float)
    k = np.where(np.isfinite(k), k, 0)
    return np.clip(k, 0, max(ncolors - 1, 0)).astype(np.intp), x


@bi('ind2rgb')
def ind2rgb(nargout, *args):
    """ind2rgb(X, map): the RGB image (double) of an indexed image."""
    nargchk(args, 2, 2, 'ind2rgb')
    m = _map(args[1], 'ind2rgb')
    if not m.shape[0]:
        raise err('MATLAB:ind2rgb:emptyColormap', 'The colormap has no colours.', 'ind2rgb')
    k, x = _indices(args[0], m.shape[0], 'ind2rgb')
    if x.ndim > 2:
        raise err('MATLAB:ind2rgb:invalidImage', 'The indexed image must be M-by-N.', 'ind2rgb')
    return out(m[k])


@bi('ind2gray')
def ind2gray(nargout, *args):
    """ind2gray(X, map): the gray image of an indexed image, each colour's
    gray level as rgb2gray gives it, of the class of X."""
    nargchk(args, 2, 2, 'ind2gray')
    m = _map(args[1], 'ind2gray')
    if not m.shape[0]:
        raise err('MATLAB:ind2gray:emptyColormap', 'The colormap has no colours.', 'ind2gray')
    k, x = _indices(args[0], m.shape[0], 'ind2gray')
    g = np.clip(_gray_of(m), 0, 1)[k]
    return out(_as_class(g, _class_of(x) if x.dtype != bool else float))


@bi('gray2ind', nout=2)
def gray2ind(nargout, *args):
    """[X, map] = gray2ind(I, n): a gray or binary image as an indexed image of
    n gray levels (64 for a gray image, 2 for a binary one), map = gray(n)."""
    nargchk(args, 1, 2, 'gray2ind')
    a = _image(args[0], 'gray2ind')
    if a.ndim != 2:
        raise err('MATLAB:gray2ind:invalidImage', 'The image must be M-by-N.', 'gray2ind')
    n = 2 if a.dtype == bool else 64
    if len(args) > 1:
        n = num(args[1])
        if n != int(n) or not 1 <= n <= 65536:
            raise err('MATLAB:gray2ind:invalidN', 'n must be a whole number from 1 to 65536.', 'gray2ind')
        n = int(n)
    d = np.clip(np.nan_to_num(_unit(a), nan=0.0), 0, 1)
    X = np.round(d * (n - 1)).astype(np.uint8 if n <= 256 else np.uint16)
    g = np.linspace(0, 1, n) if n > 1 else np.zeros(1)
    m = np.repeat(g[:, None], 3, axis=1)
    return (out(X), out(m)) if nargout > 1 else out(X)


@bi('imsplit', nout=99)
def imsplit(nargout, *args):
    """[c1, c2, ...] = imsplit(I): each channel (I(:,:,k)) of a multichannel image."""
    nargchk(args, 1, 1, 'imsplit')
    a = _image(args[0], 'imsplit')
    if a.ndim > 3:
        raise err('MATLAB:imsplit:invalidImage', 'The image must be M-by-N-by-C.', 'imsplit')
    a3 = a if a.ndim == 3 else a[:, :, None]
    k = a3.shape[2]
    want = max(nargout, 1)
    if want > k:
        raise err('MATLAB:TooManyOutputs', f'The image has {k} channels: ask for at most {k} outputs.', 'imsplit')
    chans = [out(a3[:, :, j].copy()) for j in range(k)]
    return tuple(chans[:want]) if want > 1 else chans[0]


# ---- rgb2ind: quantization and dithering -----------------------------------------------------------------

def _wu_quantize(pix, n):
    """Wu's minimum variance quantization (Graphics Gems II): the colour cube
    in 32 slices a side, boxes cut where the summed variance falls most, the
    box of largest variance cut next. pix: P-by-3 values from 0 to 1. The
    colormap of at most n colours (the boxes' means)."""
    q = np.minimum((pix * 32).astype(np.intp), 31) + 1
    shape = (33, 33, 33)
    flat = np.ravel_multi_index((q[:, 0], q[:, 1], q[:, 2]), shape)
    size = 33 ** 3
    wt = np.bincount(flat, minlength=size).astype(float).reshape(shape)
    mr = np.bincount(flat, weights=pix[:, 0], minlength=size).reshape(shape)
    mg = np.bincount(flat, weights=pix[:, 1], minlength=size).reshape(shape)
    mb = np.bincount(flat, weights=pix[:, 2], minlength=size).reshape(shape)
    m2 = np.bincount(flat, weights=(pix ** 2).sum(axis=1), minlength=size).reshape(shape)
    moments = [wt, mr, mg, mb, m2]
    for i, M in enumerate(moments):
        moments[i] = M.cumsum(0).cumsum(1).cumsum(2)
    wt, mr, mg, mb, m2 = moments

    def vol(b, M):
        r0, r1, g0, g1, b0, b1 = b
        return (M[r1, g1, b1] - M[r1, g1, b0] - M[r1, g0, b1] + M[r1, g0, b0]
                - M[r0, g1, b1] + M[r0, g1, b0] + M[r0, g0, b1] - M[r0, g0, b0])

    def var(b):
        w = vol(b, wt)
        if w <= 0:
            return 0.0
        r, g, bb = vol(b, mr), vol(b, mg), vol(b, mb)
        return vol(b, m2) - (r * r + g * g + bb * bb) / w

    def cut(b):
        """The best cut of box b: (gain, axis, position) or None."""
        whole = [vol(b, M) for M in (wt, mr, mg, mb)]
        if whole[0] <= 0:
            return None
        best = None
        for axis in range(3):
            lo, hi = b[2 * axis], b[2 * axis + 1]
            for pos in range(lo + 1, hi):
                half = list(b)
                half[2 * axis + 1] = pos
                h = [vol(half, M) for M in (wt, mr, mg, mb)]
                o = [whole[i] - h[i] for i in range(4)]
                if h[0] <= 0 or o[0] <= 0:
                    continue
                gain = (h[1] ** 2 + h[2] ** 2 + h[3] ** 2) / h[0] + (o[1] ** 2 + o[2] ** 2 + o[3] ** 2) / o[0]
                if best is None or gain > best[0]:
                    best = (gain, axis, pos)
        return best

    boxes = [(0, 32, 0, 32, 0, 32)]
    variances = [var(boxes[0])]
    while len(boxes) < n:
        order = np.argsort(variances)[::-1]
        done = False
        for k in order:
            if variances[k] <= 0:
                break
            c = cut(boxes[k])
            if c is None:
                variances[k] = 0.0
                continue
            _, axis, pos = c
            b = list(boxes[k])
            a2 = list(b)
            b[2 * axis + 1] = pos
            a2[2 * axis] = pos
            boxes[k] = tuple(b)
            boxes.append(tuple(a2))
            variances[k] = var(boxes[k])
            variances.append(var(boxes[-1]))
            done = True
            break
        if not done:
            break
    cmap = []
    for b in boxes:
        w = vol(b, wt)
        if w > 0:
            cmap.append([vol(b, mr) / w, vol(b, mg) / w, vol(b, mb) / w])
    return np.clip(np.array(cmap, float).reshape(-1, 3), 0, 1)


def _nearest(pix, cmap):
    from scipy.spatial import cKDTree
    return cKDTree(cmap).query(pix)[1]


def _dither(img, cmap):
    """Floyd-Steinberg error diffusion of an M-by-N-by-3 image (0 to 1) onto
    the colormap; the nearest colour of each corrected value from a table of
    32 slices a side (the inverse colormap). The 0-based colour numbers."""
    H, W = img.shape[:2]
    centres = (np.indices((32, 32, 32)).reshape(3, -1).T + 0.5) / 32
    lut = _nearest(centres, cmap).astype(np.intp).tolist()
    cm = cmap.tolist()
    res = np.zeros((H, W), np.intp)
    nxt = [[0.0, 0.0, 0.0] for _ in range(W + 2)]
    for y in range(H):
        cur = nxt
        nxt = [[0.0, 0.0, 0.0] for _ in range(W + 2)]
        row = img[y].tolist()
        out_row = [0] * W
        for x in range(W):
            e = cur[x + 1]
            r = row[x][0] + e[0]
            g = row[x][1] + e[1]
            b = row[x][2] + e[2]
            ri = 0 if r <= 0 else 31 if r >= 1 else int(r * 32)
            gi = 0 if g <= 0 else 31 if g >= 1 else int(g * 32)
            bi_ = 0 if b <= 0 else 31 if b >= 1 else int(b * 32)
            k = lut[(ri * 32 + gi) * 32 + bi_]
            out_row[x] = k
            c = cm[k]
            er, eg, eb = r - c[0], g - c[1], b - c[2]
            t = cur[x + 2]
            t[0] += er * 0.4375
            t[1] += eg * 0.4375
            t[2] += eb * 0.4375
            for dx, w in ((0, 0.1875), (1, 0.3125), (2, 0.0625)):
                t = nxt[x + dx]
                t[0] += er * w
                t[1] += eg * w
                t[2] += eb * w
        res[y] = out_row
    return res


@bi('rgb2ind', nout=2)
def rgb2ind(nargout, *args):
    """[X, map] = rgb2ind(RGB, n): an RGB image as an indexed image of at most
    n colours, by minimum variance quantization; rgb2ind(RGB, tol) by
    uniform quantization (floor(1/tol)+1 levels a channel, the colours not
    used left out); X = rgb2ind(RGB, map) onto a colormap given. Dithered
    (Floyd-Steinberg) unless 'nodither'."""
    nargchk(args, 2, 3, 'rgb2ind')
    a = _image(args[0], 'rgb2ind')
    if not (a.ndim == 3 and a.shape[2] == 3):
        raise err('MATLAB:rgb2ind:invalidImage', 'The image must be M-by-N-by-3.', 'rgb2ind')
    dither = True
    if len(args) > 2:
        o = (opt_str(args[2]) or '').lower()
        if o not in ('dither', 'nodither'):
            raise err('MATLAB:rgb2ind:invalidOption', "The option is 'dither' or 'nodither'.", 'rgb2ind')
        dither = o == 'dither'
    img = np.clip(np.nan_to_num(_unit(a), nan=0.0), 0, 1)
    H, W = img.shape[:2]
    pix = img.reshape(-1, 3)
    second = _image(args[1], 'rgb2ind', 'second input')
    drop_unused = False
    if second.size == 1:
        v = float(second.reshape(-1)[0])
        if 0 < v < 1:
            L = int(np.floor(1 / v)) + 1
            g = np.linspace(0, 1, L)
            rr, gg, bb = np.meshgrid(g, g, g, indexing='ij')
            cmap = np.column_stack([rr.ravel(), gg.ravel(), bb.ravel()])
            drop_unused = True
        elif v >= 1 and v == int(v):
            if v > 65536:
                raise err('MATLAB:rgb2ind:tooManyColors', 'n must be at most 65536.', 'rgb2ind')
            cmap = _wu_quantize(pix, int(v)) if pix.size else np.zeros((0, 3))
        else:
            raise err('MATLAB:rgb2ind:invalidInput', 'The second input is a number of colours n, a tolerance from 0 to 1, or a colormap.', 'rgb2ind')
    else:
        cmap = _map(second, 'rgb2ind')
    if not cmap.shape[0]:
        X = np.zeros((H, W), np.uint8)
        return (out(X), out(cmap)) if nargout > 1 else out(X)
    if dither and H * W:
        k = _dither(img, cmap)
    else:
        k = _nearest(pix, cmap).reshape(H, W) if H * W else np.zeros((H, W), np.intp)
    if drop_unused:
        used = np.unique(k)
        remap = np.zeros(cmap.shape[0], np.intp)
        remap[used] = np.arange(used.size)
        k = remap[k]
        cmap = cmap[used]
    X = k.astype(np.uint8 if cmap.shape[0] <= 256 else np.uint16)
    return (out(X), out(cmap)) if nargout > 1 else out(X)
