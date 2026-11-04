"""More image processing: histograms and thresholds (adapthisteq,
imhistmatch, otsuthresh, multithresh, imquantize, im2bw), gradients,
binary morphology (bwareaopen, bwareafilt, bwpropfilt, bwperim, bwdist,
bwskel, bwconvhull, bweuler, bwarea, bwselect, bwlabeln,
bwtraceboundary), reconstruction (imreconstruct, imclearborder, regional
and extended extrema, imhmax, imhmin, imimposemin, watershed), top-hats,
labels shown in colour, colour spaces (Lab, XYZ, YCbCr), arithmetic,
noise, sharpening, fusing, quality measures (corr2, immse, psnr, ssim,
entropy), local filters, deconvolution, padding and blocks.

Images are as imageproc.py takes them: pixels at whole coordinates from
1, values worked on in double and given back in the image's class
(rounded and saturated for integers)."""
import math

import numpy as np

from . import bi as _register
from . import REG
from ._util import err, nargchk, out, num, opt_str, opt_lower, is_str, darr, arr
from .imagecolor import _image, _unit, _as_class, _RANGE
from .imageproc import _back, _planes, _label, _morph, _opts, _trace, _sample, _se, Strel
from ..values import MError, Char, Cell, Struct, Str, Obj, FH, numel, py_str, EMPTY, F64
from .. import runtime as R


def bi(*names, **kw):
    def deco(f):
        if kw.get('aw'):
            async def g(*a):
                try:
                    return await f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError, MemoryError) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0]) from None
        else:
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


def _img2(v, fn, what='image'):
    a = _image(v, fn, what)
    if a.ndim != 2:
        raise err(f'MATLAB:{fn}:dims', f'{fn} takes a 2-D {what}.', fn)
    return a


def _gray(v, fn):
    """A grayscale image (an RGB one converted), as given."""
    a = _image(v, fn)
    if a.ndim == 3 and a.shape[2] == 3:
        return np.asarray(darr(REG['rgb2gray'].fn(1, v)))
    return a


def _bw(v, fn):
    a = _image(v, fn)
    return a != 0


def _struct8(conn, ndim=2):
    from scipy import ndimage
    if isinstance(conn, np.ndarray):
        return conn.astype(bool)
    if ndim == 2:
        return np.ones((3, 3), bool) if conn == 8 else np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool)
    rank = {6: 1, 18: 2, 26: 3}.get(conn)
    if rank is None:
        raise err('MATLAB:images:conn', 'In 3-D the connectivity is 6, 18 or 26.', 'conn')
    return ndimage.generate_binary_structure(3, rank)


def _conn_arg(args, k, fn, default=8, ndim=2):
    if len(args) > k and numel(args[k]):
        v = args[k]
        a = np.asarray(darr(v))
        if a.size > 1:
            return a != 0
        c = int(a.reshape(-1)[0])
        if ndim == 2 and c not in (4, 8):
            raise err(f'MATLAB:{fn}:conn', 'The connectivity is 4 or 8 (6, 18 or 26 in 3-D).', fn)
        return c
    return default if ndim == 2 else 26


def _label_any(bw, conn):
    """Labels numbered by their first pixel down the columns, any number of dimensions."""
    from scipy import ndimage
    if bw.ndim == 2 and conn in (4, 8):
        L, n = _label(bw, conn)
        return L, n
    st = _struct8(conn, bw.ndim)
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


def _shifts(conn, ndim=2):
    """The neighbour offsets of a connectivity."""
    st = _struct8(conn, ndim) if not isinstance(conn, np.ndarray) else conn
    c = np.array(st.shape) // 2
    return [tuple(np.array(p) - c) for p in zip(*np.nonzero(st)) if tuple(np.array(p) - c) != (0,) * st.ndim]


def _shift(a, off, fill):
    """a moved by off (the value at x is a[x + off]), fill outside."""
    res = np.full(a.shape, fill, dtype=a.dtype)
    src, dst = [], []
    for o, n in zip(off, a.shape):
        if o >= 0:
            src.append(slice(o, n))
            dst.append(slice(0, n - o))
        else:
            src.append(slice(0, n + o))
            dst.append(slice(-o, n))
    res[tuple(dst)] = a[tuple(src)]
    return res


# ---- histograms and thresholds -----------------------------------------------------------------------------------

@bi('otsuthresh', nout=2)
def otsuthresh(nargout, *args):
    """[T, EM] = otsuthresh(counts): Otsu's threshold of a histogram, from 0 to 1 over its bins, and how well it separates."""
    nargchk(args, 1, 1, 'otsuthresh')
    p = np.asarray(darr(args[0]), F64).reshape(-1)
    if p.size < 2 or np.any(p < 0) or not np.all(np.isfinite(p)):
        raise err('MATLAB:otsuthresh:counts', 'counts is a vector of at least two nonnegative counts.', 'otsuthresh')
    total = p.sum()
    if total == 0:
        return _outs(nargout, 0.0, 0.0)
    p = p / total
    k = np.arange(1, p.size + 1)
    omega = np.cumsum(p)
    mu = np.cumsum(p * k)
    with np.errstate(divide='ignore', invalid='ignore'):
        sb = (mu[-1] * omega - mu) ** 2 / (omega * (1 - omega))
    sb = np.where(np.isfinite(sb), sb, -1)
    mx = sb.max()
    if mx <= 0:
        return _outs(nargout, 0.0, 0.0)
    kk = float(np.mean(np.flatnonzero(sb == mx) + 1))
    st = np.sum(p * (k - mu[-1]) ** 2)
    return _outs(nargout, (kk - 1) / (p.size - 1), float(mx / st) if st > 0 else 0.0)


@bi('multithresh', nout=2)
def multithresh(nargout, *args):
    """[thresh, metric] = multithresh(A, N): N thresholds (1) in A's values
    splitting a 256-bin histogram of its range by Otsu's criterion (largest
    between-class variance, found exactly by dynamic programming); metric is
    that variance over the total."""
    nargchk(args, 1, 2, 'multithresh')
    a = _image(args[0], 'multithresh').astype(F64)
    N = int(num(args[1])) if len(args) > 1 else 1
    if not 1 <= N <= 20:
        raise err('MATLAB:multithresh:N', 'N is a whole number from 1 to 20.', 'multithresh')
    v = a[np.isfinite(a)].reshape(-1)
    if v.size == 0:
        return _outs(nargout, out(np.full((1, N), np.nan)), 0.0)
    lo, hi = float(v.min()), float(v.max())
    if hi == lo:
        return _outs(nargout, out(np.full((1, N), lo)), 0.0)
    L = 256
    idx = np.clip(np.round((v - lo) / (hi - lo) * (L - 1)).astype(int), 0, L - 1)
    p = np.bincount(idx, minlength=L).astype(F64)
    p /= p.sum()
    k = np.arange(L, dtype=F64)
    P = np.concatenate([[0], np.cumsum(p)])
    S = np.concatenate([[0], np.cumsum(p * k)])

    def cost(i, j):                     # the class of bins i..j-1: w*mu^2 = S^2/w
        w = P[j] - P[i]
        s = S[j] - S[i]
        with np.errstate(divide='ignore', invalid='ignore'):
            return np.where(w > 0, s * s / np.where(w > 0, w, 1), 0.0)
    best = np.full((N + 2, L + 1), -np.inf)
    arg = np.zeros((N + 2, L + 1), int)
    best[1, 1:] = cost(np.zeros(L, int), np.arange(1, L + 1))
    for c in range(2, N + 2):
        for j in range(c, L + 1):
            i = np.arange(c - 1, j)
            vals = best[c - 1, i] + cost(i, np.full(i.size, j))
            t = int(np.argmax(vals))
            best[c, j] = vals[t]
            arg[c, j] = i[t]
    cuts = []
    j = L
    for c in range(N + 1, 1, -1):
        j = arg[c, j]
        cuts.append(j)
    cuts = sorted(cuts)                      # each a first bin of a class: the threshold is the bin before it
    thresh = lo + (np.array(cuts, F64) - 1) / (L - 1) * (hi - lo)
    mu_t = S[-1]
    st = float(np.sum(p * (k - mu_t) ** 2))
    metric = (float(best[N + 1, L]) - mu_t ** 2) / st if st > 0 else 0.0
    return _outs(nargout, out(thresh.reshape(1, -1)), metric)


@bi('imquantize', nout=2)
def imquantize(nargout, *args):
    """[quantA, index] = imquantize(A, levels, values): A in N + 1 classes by
    the sorted thresholds levels: 1 up to levels(1), k up to levels(k), N + 1
    above; with values, values(k) for class k."""
    nargchk(args, 2, 3, 'imquantize')
    a = np.asarray(darr(args[0]), F64)
    lv = np.sort(np.asarray(darr(args[1]), F64).reshape(-1))
    idx = np.searchsorted(lv, a, side='left') + 1.0
    if len(args) > 2:
        vals = np.asarray(darr(args[2])).reshape(-1)
        if vals.size != lv.size + 1:
            raise err('MATLAB:imquantize:values', 'values has one more element than levels.', 'imquantize')
        q = vals[idx.astype(int) - 1]
        return _outs(nargout, out(q), out(idx))
    return _outs(nargout, out(idx), out(idx))


@bi('im2bw')
def im2bw(nargout, *args):
    """BW = im2bw(I, level) or im2bw(X, map, level): true where the image (gray, RGB as gray, indexed through its map) is above level (0.5) on a scale from 0 to 1."""
    nargchk(args, 1, 3, 'im2bw')
    a = _image(args[0], 'im2bw')
    level = 0.5
    if len(args) == 3 or (len(args) == 2 and np.asarray(darr(args[1])).ndim == 2 and np.asarray(darr(args[1])).shape[-1] == 3
                          and np.asarray(darr(args[1])).size > 3):
        rgb = np.asarray(darr(REG['ind2rgb'].fn(1, args[0], args[1])))
        g = np.asarray(darr(REG['rgb2gray'].fn(1, rgb)))
        level = float(num(args[2])) if len(args) == 3 else 0.5
        return g > level
    if len(args) == 2:
        level = float(num(args[1]))
    if not 0 <= level <= 1:
        raise err('MATLAB:im2bw:level', 'level is from 0 to 1.', 'im2bw')
    if a.ndim == 3 and a.shape[2] == 3:
        a = np.asarray(darr(REG['rgb2gray'].fn(1, args[0])))
    return _unit(a) > level


def _clahe_map(hist, numpix, nbins, clip, dist, alpha):
    h = hist.astype(F64).copy()
    if clip < numpix:
        excess = np.sum(np.maximum(h - clip, 0))
        h = np.minimum(h, clip)
        for _ in range(20):                         # the clipped excess spread evenly, again for what spills over
            if excess <= 0:
                break
            h += excess / nbins
            excess = np.sum(np.maximum(h - clip, 0))
            h = np.minimum(h, clip)
    cdf = np.cumsum(h) / max(np.sum(h), 1)
    if dist == 'uniform':
        return cdf
    c = np.clip(cdf, 0, 1 - 1e-12)
    if dist == 'rayleigh':
        m = np.sqrt(2 * alpha ** 2 * np.log(1 / (1 - c)))
    else:
        m = -np.log(1 - c) / alpha
    return np.clip(m / max(m.max(), 1e-12), 0, 1)


@bi('adapthisteq')
def adapthisteq(nargout, *args):
    """J = adapthisteq(I, 'NumTiles', [8 8], 'ClipLimit', 0.01, 'NBins', 256,
    'Range', 'full', 'Distribution', 'uniform', 'Alpha', 0.4): contrast-limited
    adaptive histogram equalization (Zuiderveld): each tile's histogram
    clipped (from ceil(pixels/bins) at ClipLimit 0 up to the whole tile at
    1, the excess spread over the bins) and equalized, the tiles' mappings
    blended bilinearly between their centres."""
    nargchk(args, 1, 13, 'adapthisteq')
    a = _img2(args[0], 'adapthisteq', 'grayscale image')
    o, rest = _opts(list(args[1:]), ('NumTiles', 'ClipLimit', 'NBins', 'Range', 'Distribution', 'Alpha'))
    if rest:
        raise err('MATLAB:adapthisteq:option', 'The options are NumTiles, ClipLimit, NBins, Range, Distribution and Alpha.', 'adapthisteq')
    nt = np.asarray(darr(o['NumTiles']), int).reshape(-1) if 'NumTiles' in o else np.array([8, 8])
    if nt.size == 1:
        nt = np.array([nt[0], nt[0]])
    if np.any(nt < 2):
        raise err('MATLAB:adapthisteq:tiles', 'NumTiles is at least [2 2].', 'adapthisteq')
    cl = float(num(o['ClipLimit'])) if 'ClipLimit' in o else 0.01
    nb = int(num(o['NBins'])) if 'NBins' in o else 256
    dist = opt_lower(o['Distribution']) if 'Distribution' in o else 'uniform'
    if dist not in ('uniform', 'rayleigh', 'exponential'):
        raise err('MATLAB:adapthisteq:dist', "Distribution is 'uniform', 'rayleigh' or 'exponential'.", 'adapthisteq')
    alpha = float(num(o['Alpha'])) if 'Alpha' in o else 0.4
    rng = opt_lower(o['Range']) if 'Range' in o else 'full'
    u = np.clip(_unit(a), 0, 1)
    m, n = u.shape
    th, tw = int(math.ceil(m / nt[0])), int(math.ceil(n / nt[1]))
    if th < 2 or tw < 2:
        raise err('MATLAB:adapthisteq:small', 'The image is too small for that many tiles.', 'adapthisteq')
    pad = np.pad(u, ((0, th * nt[0] - m), (0, tw * nt[1] - n)), mode='symmetric')
    numpix = th * tw
    minclip = math.ceil(numpix / nb)
    clip = minclip + round(cl * (numpix - minclip))
    bins = np.clip((pad * (nb - 1) + 0.5).astype(int), 0, nb - 1)
    maps = np.zeros((nt[0], nt[1], nb))
    for i in range(nt[0]):
        for j in range(nt[1]):
            t = bins[i * th:(i + 1) * th, j * tw:(j + 1) * tw]
            maps[i, j] = _clahe_map(np.bincount(t.reshape(-1), minlength=nb), numpix, nb, clip, dist, alpha)
    # bilinear blending between tile centres
    rc = (np.arange(m) + 0.5) / th - 0.5
    cc = (np.arange(n) + 0.5) / tw - 0.5
    r0 = np.clip(np.floor(rc).astype(int), 0, nt[0] - 1)
    c0 = np.clip(np.floor(cc).astype(int), 0, nt[1] - 1)
    r1, c1 = np.clip(r0 + 1, 0, nt[0] - 1), np.clip(c0 + 1, 0, nt[1] - 1)
    wr = np.clip(rc - r0, 0, 1)[:, None]
    wc = np.clip(cc - c0, 0, 1)[None, :]
    b = bins[:m, :n]
    R0, C0, R1, C1 = r0[:, None], c0[None, :], r1[:, None], c1[None, :]
    v = ((1 - wr) * (1 - wc) * maps[R0, C0, b] + (1 - wr) * wc * maps[R0, C1, b] + wr * (1 - wc) * maps[R1, C0, b] + wr * wc * maps[R1, C1, b])
    if rng == 'original':
        lo, hi = float(u.min()), float(u.max())
        v = lo + v * (hi - lo)
    return _as_class(v, a.dtype) if a.dtype != bool else v


@bi('imhistmatch', nout=2)
def imhistmatch(nargout, *args):
    """J = imhistmatch(A, ref, nbins): A's values remapped so its histogram
    (of nbins, 64) matches ref's: each value goes to the reference value at the
    same place in the cumulative histogram."""
    nargchk(args, 2, 3, 'imhistmatch')
    a = _image(args[0], 'imhistmatch')
    r = _image(args[1], 'imhistmatch', 'reference image')
    nb = int(num(args[2])) if len(args) > 2 else 64
    ua, ur = np.clip(_unit(a), 0, 1), np.clip(_unit(r), 0, 1)
    levels = np.linspace(0, 1, nb)
    href = np.bincount(np.clip(np.round(ur * (nb - 1)).astype(int), 0, nb - 1).reshape(-1), minlength=nb).astype(F64)
    cref = np.cumsum(href) / max(href.sum(), 1)
    order = np.argsort(ua.reshape(-1), kind='stable')
    ranks = np.empty(order.size)
    ranks[order] = (np.arange(order.size) + 0.5) / order.size
    k = np.clip(np.searchsorted(cref, ranks, side='left'), 0, nb - 1)
    v = levels[k].reshape(ua.shape)
    hist = np.bincount(k, minlength=nb).astype(F64)
    return _outs(nargout, _as_class(v, a.dtype) if a.dtype != bool else v, out(hist.reshape(-1, 1)))


# ---- gradients -----------------------------------------------------------------------------------------------------

def _gradxy(a, method, fn):
    from .imageproc import _correlate
    a = a.astype(F64)
    if method in ('sobel', 'prewitt'):
        w = 2.0 if method == 'sobel' else 1.0
        hy = np.array([[-1, -w, -1], [0, 0, 0], [1, w, 1]], F64)
        gy = _correlate(a, hy, 'replicate')
        gx = _correlate(a, hy.T, 'replicate')
    elif method == 'central':
        gy, gx = np.gradient(a) if min(a.shape) > 1 else (np.zeros(a.shape), np.zeros(a.shape))
    elif method == 'intermediate':
        gx = np.zeros(a.shape)
        gy = np.zeros(a.shape)
        gx[:, :-1] = np.diff(a, axis=1)
        gy[:-1, :] = np.diff(a, axis=0)
    else:
        raise err(f'MATLAB:{fn}:method', "The method is 'sobel', 'prewitt', 'central' or 'intermediate'.", fn)
    return gx, gy


@bi('imgradientxy', nout=2)
def imgradientxy(nargout, *args):
    """[Gx, Gy] = imgradientxy(I, method): the directional gradients, x to the right and y down: 'sobel' (default) or 'prewitt' kernels (with the border replicated), 'central' or 'intermediate' differences."""
    nargchk(args, 1, 2, 'imgradientxy')
    a = _img2(args[0], 'imgradientxy')
    method = opt_lower(args[1]) if len(args) > 1 else 'sobel'
    gx, gy = _gradxy(a, method, 'imgradientxy')
    return _outs(nargout, gx, gy)


@bi('imgradient', nout=2)
def imgradient(nargout, *args):
    """[Gmag, Gdir] = imgradient(I, method) or imgradient(Gx, Gy): the gradient's magnitude, and its direction in degrees counterclockwise from the x axis (-180 to 180, y up)."""
    nargchk(args, 1, 2, 'imgradient')
    if len(args) == 2 and not is_str(args[1]):
        gx, gy = np.asarray(darr(args[0]), F64), np.asarray(darr(args[1]), F64)
        if gx.shape != gy.shape:
            raise err('MATLAB:imgradient:size', 'Gx and Gy are the same size.', 'imgradient')
    else:
        a = _img2(args[0], 'imgradient')
        method = opt_lower(args[1]) if len(args) > 1 else 'sobel'
        gx, gy = _gradxy(a, method, 'imgradient')
    return _outs(nargout, np.hypot(gx, gy), np.degrees(np.arctan2(-gy, gx)))


# ---- binary images -------------------------------------------------------------------------------------------------

@bi('bwlabeln', nout=2)
def bwlabeln(nargout, *args):
    """[L, n] = bwlabeln(BW, conn): connected components in any number of dimensions (26-connected in 3-D, 8 in 2-D, or 6, 18, 4 or a 3-by-3-by-3 array), numbered by their first pixel down the columns."""
    nargchk(args, 1, 2, 'bwlabeln')
    bw = _bw(args[0], 'bwlabeln')
    conn = _conn_arg(args, 1, 'bwlabeln', default=(8 if bw.ndim <= 2 else 26), ndim=bw.ndim if bw.ndim > 2 else 2)
    L, n = _label_any(bw, conn)
    return _outs(nargout, L, float(n))


def _components(bw, conn):
    L, n = _label_any(bw, conn)
    sizes = np.bincount(L.astype(int).reshape(-1), minlength=n + 1)
    return L.astype(int), n, sizes


@bi('bwareaopen')
def bwareaopen(nargout, *args):
    """BW2 = bwareaopen(BW, P, conn): the objects of fewer than P pixels removed (8-connected unless conn)."""
    nargchk(args, 2, 3, 'bwareaopen')
    bw = _bw(args[0], 'bwareaopen')
    P = float(num(args[1]))
    conn = _conn_arg(args, 2, 'bwareaopen', default=8 if bw.ndim <= 2 else 26, ndim=min(bw.ndim, 3) if bw.ndim > 2 else 2)
    L, n, sizes = _components(bw, conn)
    keep = sizes >= P
    keep[0] = False
    return keep[L]


@bi('bwareafilt')
def bwareafilt(nargout, *args):
    """BW2 = bwareafilt(BW, range) or bwareafilt(BW, n, keep, conn): the objects whose area is within range, or the n largest ('largest') or smallest."""
    nargchk(args, 2, 4, 'bwareafilt')
    bw = _bw(args[0], 'bwareafilt')
    if bw.ndim != 2:
        raise err('MATLAB:bwareafilt:dims', 'bwareafilt takes a 2-D image.', 'bwareafilt')
    rest = list(args[1:])
    sel = np.asarray(darr(rest.pop(0)), F64).reshape(-1)
    keep_kind = 'largest'
    if rest and is_str(rest[0]):
        keep_kind = opt_lower(rest.pop(0))
        if keep_kind not in ('largest', 'smallest'):
            raise err('MATLAB:bwareafilt:keep', "keep is 'largest' or 'smallest'.", 'bwareafilt')
    conn = _conn_arg(rest, 0, 'bwareafilt')
    L, n, sizes = _components(bw, conn)
    keep = np.zeros(n + 1, bool)
    if sel.size == 2:
        keep[1:] = (sizes[1:] >= sel[0]) & (sizes[1:] <= sel[1])
    else:
        k = int(sel[0])
        order = np.argsort(-sizes[1:] if keep_kind == 'largest' else sizes[1:], kind='stable')[:k]
        keep[order + 1] = True
    return keep[L]


@bi('bwpropfilt')
def bwpropfilt(nargout, *args):
    """BW2 = bwpropfilt(BW, attrib, range) or bwpropfilt(BW, attrib, n, keep, conn), or (BW, I, attrib, ...) for intensity properties: the objects whose regionprops property is within range, or the n with the largest ('largest') or smallest."""
    nargchk(args, 3, 6, 'bwpropfilt')
    bw = _bw(args[0], 'bwpropfilt')
    rest = list(args[1:])
    I = None
    if not is_str(rest[0]):
        I = rest.pop(0)
    prop = py_str(rest.pop(0))
    sel = np.asarray(darr(rest.pop(0)), F64).reshape(-1)
    keep_kind = 'largest'
    if rest and is_str(rest[0]):
        keep_kind = opt_lower(rest.pop(0))
    conn = _conn_arg(rest, 0, 'bwpropfilt')
    L, n, _ = _components(bw, conn)
    if n == 0:
        return bw
    pr = REG['regionprops'].fn(1, out(L.astype(F64)), *([I] if I is not None else []), Char.of(prop))
    vals = np.array([float(np.asarray(darr(pr.elem(i)[pr.keys[0]])).reshape(-1)[0]) for i in range(pr.size)])
    keep = np.zeros(n + 1, bool)
    if sel.size == 2:
        keep[1:] = (vals >= sel[0]) & (vals <= sel[1])
    else:
        k = int(sel[0])
        order = np.argsort(-vals if keep_kind == 'largest' else vals, kind='stable')[:k]
        keep[order + 1] = True
    return keep[L]


@bi('bwperim')
def bwperim(nargout, *args):
    """BW2 = bwperim(BW, conn): the objects' perimeter pixels: on, with a neighbour off (4-connected neighbours unless conn is 8; outside the image counts as off)."""
    nargchk(args, 1, 2, 'bwperim')
    bw = _bw(args[0], 'bwperim')
    conn = _conn_arg(args, 1, 'bwperim', default=4 if bw.ndim <= 2 else 6, ndim=2 if bw.ndim <= 2 else 3)
    if bw.ndim == 2 and conn in (4, 8):
        nb = 4 if conn == 4 else 8
        conn = nb
    offs = _shifts(conn, bw.ndim)
    inner = bw.copy()
    for o in offs:
        inner &= _shift(bw, o, False)
    return bw & ~inner


@bi('bwdist', nout=2)
def bwdist(nargout, *args):
    """[D, idx] = bwdist(BW, method): for each pixel the distance to the nearest on pixel, 'euclidean' (default), 'cityblock', 'chessboard' or 'quasi-euclidean', and that pixel's linear index."""
    nargchk(args, 1, 2, 'bwdist')
    from scipy import ndimage
    bw = _bw(args[0], 'bwdist')
    method = opt_lower(args[1]) if len(args) > 1 else 'euclidean'
    if not bw.any():
        D = np.full(bw.shape, np.inf)
        return _outs(nargout, D.astype(np.float32), np.zeros(bw.shape, np.uint32))
    if method == 'euclidean':
        D, ind = ndimage.distance_transform_edt(~bw, return_indices=True)
    elif method in ('cityblock', 'chessboard'):
        D, ind = ndimage.distance_transform_cdt(~bw, metric='taxicab' if method == 'cityblock' else 'chessboard', return_indices=True)
        D = D.astype(F64)
    elif method == 'quasi-euclidean':
        if bw.ndim != 2:
            raise err('MATLAB:bwdist:quasi', "'quasi-euclidean' is for 2-D images here.", 'bwdist')
        D, ind = _chamfer(bw)
    else:
        raise err('MATLAB:bwdist:method', "The method is 'euclidean', 'cityblock', 'chessboard' or 'quasi-euclidean'.", 'bwdist')
    lin = np.ravel_multi_index(tuple(ind), bw.shape, order='F') + 1
    return _outs(nargout, D.astype(np.float32), lin.astype(np.uint32))


def _chamfer(bw):
    """Quasi-Euclidean distance (steps of 1 and sqrt(2)) by two raster passes, with the nearest on pixel."""
    m, n = bw.shape
    D = np.where(bw, 0.0, np.inf)
    R = np.where(bw, np.arange(m)[:, None], -1).astype(int) * np.ones((1, n), int)
    C = np.where(bw, np.arange(n)[None, :], -1).astype(int) * np.ones((m, 1), int)
    s2 = math.sqrt(2)
    fwd = ((-1, -1, s2), (-1, 0, 1.0), (-1, 1, s2), (0, -1, 1.0))
    bwd = ((1, 1, s2), (1, 0, 1.0), (1, -1, s2), (0, 1, 1.0))
    for passes, rows, cols in ((fwd, range(m), range(n)), (bwd, range(m - 1, -1, -1), range(n - 1, -1, -1))):
        for i in rows:
            for j in cols:
                best = D[i, j]
                for di, dj, w in passes:
                    ii, jj = i + di, j + dj
                    if 0 <= ii < m and 0 <= jj < n and D[ii, jj] + w < best:
                        best = D[ii, jj] + w
                        R[i, j], C[i, j] = R[ii, jj], C[ii, jj]
                D[i, j] = best
    return D, (R, C)


@bi('bwskel')
def bwskel(nargout, *args):
    """B = bwskel(BW, 'MinBranchLength', len): the skeleton, objects thinned
    to lines one pixel wide (Zhang and Suen's thinning until nothing
    changes); branches shorter than len (0) pruned from their end points."""
    nargchk(args, 1, 3, 'bwskel')
    bw = _bw(args[0], 'bwskel')
    if bw.ndim != 2:
        raise err('MATLAB:bwskel:dims', 'bwskel takes a 2-D image here.', 'bwskel')
    o, _ = _opts(list(args[1:]), ('MinBranchLength',))
    sk = np.asarray(darr(REG['bwmorph'].fn(1, bw, Char.of('thin'), np.inf))) != 0
    L = float(num(o['MinBranchLength'])) if 'MinBranchLength' in o else 0
    if L > 0:
        sk = _prune(sk, L)
    return sk


def _prune(sk, L):
    m, n = sk.shape
    nb = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    def neighbours(r, c):
        return [(r + a, c + b) for a, b in nb if 0 <= r + a < m and 0 <= c + b < n and sk[r + a, c + b]]
    changed = True
    while changed:
        changed = False
        ends = [(r, c) for r, c in zip(*np.nonzero(sk)) if len(neighbours(r, c)) == 1]
        for e in ends:
            path = [e]
            prev, cur = None, e
            while True:
                nxt = [p for p in neighbours(*cur) if p != prev and p not in path]
                if len(neighbours(*cur)) > 2 or not nxt:
                    break
                prev, cur = cur, nxt[0]
                path.append(cur)
            if len(neighbours(*cur)) > 2 and len(path) - 1 < L:
                for p in path[:-1]:
                    sk[p] = False
                changed = True
    return sk


@bi('bwconvhull')
def bwconvhull(nargout, *args):
    """CH = bwconvhull(BW, 'union') or bwconvhull(BW, 'objects', conn): the pixels inside the convex hull of all the on pixels (as squares), or of each object."""
    nargchk(args, 1, 3, 'bwconvhull')
    bw = _bw(args[0], 'bwconvhull')
    if bw.ndim != 2:
        raise err('MATLAB:bwconvhull:dims', 'bwconvhull takes a 2-D image.', 'bwconvhull')
    method = opt_lower(args[1]) if len(args) > 1 else 'union'
    if method not in ('union', 'objects'):
        raise err('MATLAB:bwconvhull:method', "The method is 'union' or 'objects'.", 'bwconvhull')
    m, n = bw.shape
    rr, cc = np.mgrid[0:m, 0:n]
    centres = np.column_stack([cc.reshape(-1) + 1.0, rr.reshape(-1) + 1.0])

    def hull_of(mask):
        r, c = np.nonzero(mask)
        if r.size == 0:
            return np.zeros(mask.shape, bool)
        pts = np.concatenate([np.column_stack([c + 1 + dx, r + 1 + dy]) for dx in (-0.5, 0.5) for dy in (-0.5, 0.5)])
        from scipy.spatial import ConvexHull, QhullError
        try:
            h = ConvexHull(pts)
        except QhullError:
            return mask.copy()
        A, b = h.equations[:, :2], h.equations[:, 2]
        inside = np.all(centres @ A.T + b <= 1e-9, axis=1)
        return inside.reshape(m, n)
    if method == 'union':
        return hull_of(bw)
    conn = _conn_arg(args, 2, 'bwconvhull')
    L, k, _ = _components(bw, conn)
    res = np.zeros(bw.shape, bool)
    for i in range(1, k + 1):
        res |= hull_of(L == i)
    return res


@bi('bweuler')
def bweuler(nargout, *args):
    """eul = bweuler(BW, n): the Euler number, objects less holes (objects n-connected, 8 by default, holes the other way)."""
    nargchk(args, 1, 2, 'bweuler')
    bw = _bw(args[0], 'bweuler')
    if bw.ndim != 2:
        raise err('MATLAB:bweuler:dims', 'bweuler takes a 2-D image.', 'bweuler')
    conn = _conn_arg(args, 1, 'bweuler')
    _, nobj = _label_any(bw, conn)
    bg = np.pad(~bw, 1, constant_values=True)
    _, nbg = _label_any(bg, 4 if conn == 8 else 8)
    return float(nobj - (nbg - 1))


@bi('bwarea')
def bwarea(nargout, *args):
    """total = bwarea(BW): the area of the on pixels estimated from each 2-by-2 neighbourhood (Pratt): one pixel on counts 1/4, two side by side 1/2, two diagonal 3/4, three 7/8, four 1."""
    nargchk(args, 1, 1, 'bwarea')
    bw = _bw(args[0], 'bwarea').astype(int)
    if bw.ndim != 2:
        raise err('MATLAB:bwarea:dims', 'bwarea takes a 2-D image.', 'bwarea')
    p = np.pad(bw, 1)
    a, b, c, d = p[:-1, :-1], p[:-1, 1:], p[1:, :-1], p[1:, 1:]
    s = a + b + c + d
    diag = ((a & d) | (b & c)).astype(bool) & (s == 2) & ~(((a & b) | (c & d) | (a & c) | (b & d)).astype(bool))
    w = np.select([s == 1, (s == 2) & ~diag, (s == 2) & diag, s == 3, s == 4], [0.25, 0.5, 0.75, 0.875, 1.0], 0.0)
    return float(w.sum())


@bi('bwselect', nout=2)
def bwselect(nargout, *args):
    """[BW2, idx] = bwselect(BW, c, r, n): the objects holding the pixels (c, r), n-connected (8)."""
    nargchk(args, 3, 4, 'bwselect')
    bw = _bw(args[0], 'bwselect')
    cs = np.round(np.asarray(darr(args[1]), F64).reshape(-1)).astype(int) - 1
    rs = np.round(np.asarray(darr(args[2]), F64).reshape(-1)).astype(int) - 1
    conn = _conn_arg(args, 3, 'bwselect')
    L, n, _ = _components(bw, conn)
    keep = np.zeros(n + 1, bool)
    for r, c in zip(rs, cs):
        if 0 <= r < bw.shape[0] and 0 <= c < bw.shape[1] and L[r, c] > 0:
            keep[L[r, c]] = True
    res = keep[L]
    return _outs(nargout, res, out((np.flatnonzero(res.reshape(-1, order='F')) + 1.0).reshape(-1, 1)))


_STEPS = {'n': (-1, 0), 'ne': (-1, 1), 'e': (0, 1), 'se': (1, 1), 's': (1, 0), 'sw': (1, -1), 'w': (0, -1), 'nw': (-1, -1)}


@bi('bwtraceboundary')
def bwtraceboundary(nargout, *args):
    """B = bwtraceboundary(BW, P, fstep, conn, N, dir): the boundary of the
    object through the boundary pixel P = [row col], traced (8-connected,
    clockwise unless dir is 'counterclockwise') from P, at most N points
    (Inf); fstep, the first direction looked in, is taken but the trace
    starts from the outside of the object."""
    nargchk(args, 3, 6, 'bwtraceboundary')
    bw = _bw(args[0], 'bwtraceboundary')
    P = np.asarray(darr(args[1]), F64).reshape(-1).astype(int) - 1
    step = opt_lower(args[2])
    if step not in _STEPS:
        raise err('MATLAB:bwtraceboundary:fstep', "fstep is 'N', 'NE', 'E', 'SE', 'S', 'SW', 'W' or 'NW'.", 'bwtraceboundary')
    conn = int(num(args[3])) if len(args) > 3 else 8
    nmax = float(num(args[4])) if len(args) > 4 else np.inf
    direction = opt_lower(args[5]) if len(args) > 5 else 'clockwise'
    r, c = P
    if not (0 <= r < bw.shape[0] and 0 <= c < bw.shape[1]) or not bw[r, c]:
        return np.zeros((0, 2))
    L, _, _ = _components(bw, conn)
    mask = L == L[r, c]
    # the object's first pixel down the columns starts the tracer; the path is turned to start at P
    first = np.argwhere(mask.T)[0][::-1]
    path = _trace(mask, (int(first[0]), int(first[1])), conn)[:-1]
    if direction == 'counterclockwise':
        path = path[::-1]
    hit = np.flatnonzero((path[:, 0] == r + 1) & (path[:, 1] == c + 1))
    if hit.size == 0:
        return np.zeros((0, 2))
    path = np.roll(path, -int(hit[0]), axis=0)
    path = np.vstack([path, path[:1]])
    if np.isfinite(nmax):
        path = path[:int(nmax)]
    return path


# ---- reconstruction and extrema --------------------------------------------------------------------------------------

def _reconstruct(marker, mask, conn):
    """Grey reconstruction by dilation: marker dilated within mask until it stops changing."""
    J = np.minimum(marker, mask).astype(F64)
    M = mask.astype(F64)
    offs = _shifts(conn, M.ndim)
    for _ in range(10 * sum(M.shape) + 10):
        prev = J
        D = J.copy()
        for o in offs:
            D = np.maximum(D, _shift(J, o, -np.inf))
        J = np.minimum(D, M)
        if np.array_equal(J, prev):
            break
    return J


def _reconstruct_bin(marker, mask, conn):
    L, n = _label_any(mask, conn)
    L = L.astype(int)
    keep = np.zeros(n + 1, bool)
    keep[np.unique(L[marker & mask])] = True
    keep[0] = False
    return keep[L]


@bi('imreconstruct')
def imreconstruct(nargout, *args):
    """IM = imreconstruct(marker, mask, conn): morphological reconstruction of marker under mask (the marker dilated, kept under the mask, until it stops changing; for binary images the mask's objects that the marker touches)."""
    nargchk(args, 2, 3, 'imreconstruct')
    mk = _image(args[0], 'imreconstruct', 'marker')
    ms = _image(args[1], 'imreconstruct', 'mask')
    if mk.shape != ms.shape:
        raise err('MATLAB:imreconstruct:size', 'marker and mask are the same size.', 'imreconstruct')
    conn = _conn_arg(args, 2, 'imreconstruct', default=8 if ms.ndim <= 2 else 26, ndim=2 if ms.ndim <= 2 else 3)
    if ms.dtype == bool and mk.dtype == bool:
        return _reconstruct_bin(mk, ms, conn)
    return _back(_reconstruct(mk.astype(F64), ms.astype(F64), conn), ms.dtype)


def _conn_default(a, args, k, fn):
    return _conn_arg(args, k, fn, default=8 if a.ndim <= 2 else 26, ndim=2 if a.ndim <= 2 else 3)


def _step(a):
    """A height smaller than any difference between values (1 for integers)."""
    if a.dtype.kind in 'iub':
        return 1.0
    u = np.unique(a[np.isfinite(a)])
    d = np.diff(u)
    return float(d.min()) if d.size else 1.0


def _regmax(a, conn):
    x = a.astype(F64)
    h = _step(a)
    Rr = _reconstruct(x - h, x, conn)
    return (x - Rr) > h / 2


@bi('imregionalmax')
def imregionalmax(nargout, *args):
    """BW = imregionalmax(I, conn): the regional maxima: plateaus of pixels whose neighbours all lie lower (8-connected)."""
    nargchk(args, 1, 2, 'imregionalmax')
    a = _image(args[0], 'imregionalmax')
    return _regmax(a, _conn_default(a, args, 1, 'imregionalmax'))


@bi('imregionalmin')
def imregionalmin(nargout, *args):
    """BW = imregionalmin(I, conn): the regional minima: plateaus whose neighbours all lie higher (8-connected)."""
    nargchk(args, 1, 2, 'imregionalmin')
    a = _image(args[0], 'imregionalmin')
    return _regmax(-a.astype(F64), _conn_default(a, args, 1, 'imregionalmin'))


@bi('imhmax')
def imhmax(nargout, *args):
    """I2 = imhmax(I, H, conn): maxima whose height is less than H taken down: the reconstruction of I - H under I."""
    nargchk(args, 2, 3, 'imhmax')
    a = _image(args[0], 'imhmax')
    H = float(num(args[1]))
    x = a.astype(F64)
    return _back(_reconstruct(x - H, x, _conn_default(a, args, 2, 'imhmax')), a.dtype)


@bi('imhmin')
def imhmin(nargout, *args):
    """I2 = imhmin(I, H, conn): minima shallower than H filled: the reconstruction of I + H from above."""
    nargchk(args, 2, 3, 'imhmin')
    a = _image(args[0], 'imhmin')
    H = float(num(args[1]))
    x = a.astype(F64)
    return _back(-_reconstruct(-x - H, -x, _conn_default(a, args, 2, 'imhmin')), a.dtype)


@bi('imextendedmax')
def imextendedmax(nargout, *args):
    """BW = imextendedmax(I, H, conn): the regional maxima of imhmax(I, H)."""
    nargchk(args, 2, 3, 'imextendedmax')
    a = _image(args[0], 'imextendedmax')
    conn = _conn_default(a, args, 2, 'imextendedmax')
    x = a.astype(F64)
    hm = _reconstruct(x - float(num(args[1])), x, conn)
    return _regmax(hm, conn)


@bi('imextendedmin')
def imextendedmin(nargout, *args):
    """BW = imextendedmin(I, H, conn): the regional minima of imhmin(I, H)."""
    nargchk(args, 2, 3, 'imextendedmin')
    a = _image(args[0], 'imextendedmin')
    conn = _conn_default(a, args, 2, 'imextendedmin')
    x = a.astype(F64)
    hm = -_reconstruct(-x - float(num(args[1])), -x, conn)
    return _regmax(-hm, conn)


@bi('imimposemin')
def imimposemin(nargout, *args):
    """J = imimposemin(I, BW, conn): I changed so its only regional minima are where BW is on (-Inf there for floating images, the class's least value for integers): a reconstruction by erosion."""
    nargchk(args, 2, 3, 'imimposemin')
    a = _image(args[0], 'imimposemin')
    bw = _bw(args[1], 'imimposemin')
    if bw.shape != a.shape:
        raise err('MATLAB:imimposemin:size', 'I and BW are the same size.', 'imimposemin')
    conn = _conn_default(a, args, 2, 'imimposemin')
    x = a.astype(F64)
    h = _step(a) if a.dtype.kind in 'iub' else (float(np.nanmax(x) - np.nanmin(x)) / 1000 or 1e-3)
    fm = np.where(bw, -np.inf, np.inf)
    g = np.minimum(x + h, fm)
    J = -_reconstruct(-fm, -g, conn)
    if a.dtype.kind in 'iu':
        lo = np.iinfo(a.dtype).min
        J = np.where(np.isinf(J), lo, J - h)
        return _back(J, a.dtype)
    return J.astype(a.dtype if a.dtype.kind == 'f' else F64)


@bi('watershed')
def watershed(nargout, *args):
    """L = watershed(A, conn): the catchment basins of A labelled 1, 2, ...
    (by the order of their minima's first pixels down the columns), the
    ridges between them 0: Meyer's flooding from the regional minima (8- or
    26-connected unless conn)."""
    nargchk(args, 1, 2, 'watershed')
    import heapq
    a = _image(args[0], 'watershed').astype(F64)
    conn = _conn_default(a, args, 1, 'watershed')
    minima = _regmax(-a, conn)
    L, n = _label_any(minima, conn)
    L = L.astype(np.int64)
    shape = a.shape
    flat_a = a.reshape(-1, order='F')
    lab = L.reshape(-1, order='F')
    offs = _shifts(conn, a.ndim)
    # each pixel's neighbours as flat indices (column order), worked out once
    idx = np.arange(flat_a.size).reshape(shape, order='F')
    cols = []
    for o in offs:
        cols.append(_shift(idx, o, -1).reshape(-1, order='F'))
    nb = np.stack(cols, axis=1).tolist()
    UNSEEN, QUEUED = -1, -2
    state = np.where(lab > 0, lab, UNSEEN).tolist()
    vals = flat_a.tolist()
    heap = []
    cnt = 0
    push = heapq.heappush
    for i in np.flatnonzero(lab > 0).tolist():
        for j in nb[i]:
            if j >= 0 and state[j] == UNSEEN:
                state[j] = QUEUED
                push(heap, (vals[j], cnt, j))
                cnt += 1
    while heap:
        _, _, i = heapq.heappop(heap)
        found = 0
        ridge = False
        for j in nb[i]:
            if j >= 0:
                s_ = state[j]
                if s_ > 0:
                    if found and s_ != found:
                        ridge = True
                    found = s_
        state[i] = 0 if (ridge or not found) else found
        if state[i] > 0:
            for j in nb[i]:
                if j >= 0 and state[j] == UNSEEN:
                    state[j] = QUEUED
                    push(heap, (vals[j], cnt, j))
                    cnt += 1
    st = np.array(state, F64)
    st[st < 0] = 0
    return st.reshape(shape, order='F')


@bi('imclearborder')
def imclearborder(nargout, *args):
    """I2 = imclearborder(I, conn): the objects (light structures) touching the image's border taken away: I less the reconstruction of its border pixels."""
    nargchk(args, 1, 2, 'imclearborder')
    a = _image(args[0], 'imclearborder')
    conn = _conn_default(a, args, 1, 'imclearborder')
    border = np.zeros(a.shape, bool)
    for ax in range(a.ndim):
        idx = [slice(None)] * a.ndim
        idx[ax] = 0
        border[tuple(idx)] = True
        idx[ax] = -1
        border[tuple(idx)] = True
    if a.dtype == bool:
        return a & ~_reconstruct_bin(a & border, a, conn)
    x = a.astype(F64)
    lo = float(np.min(x)) if x.size else 0.0
    marker = np.where(border, x, lo)
    Rr = _reconstruct(marker, x, conn)
    return _back(x - Rr + lo, a.dtype)


@bi('imtophat')
def imtophat(nargout, *args):
    """J = imtophat(I, SE): the white top-hat, I less its opening by SE."""
    nargchk(args, 2, 2, 'imtophat')
    a = _image(args[0], 'imtophat')
    op = np.asarray(darr(REG['imopen'].fn(1, args[0], args[1])), F64)
    return _back(a.astype(F64) - op, a.dtype) if a.dtype != bool else (a & ~(op != 0))


@bi('imbothat')
def imbothat(nargout, *args):
    """J = imbothat(I, SE): the black (bottom) top-hat, the closing by SE less I."""
    nargchk(args, 2, 2, 'imbothat')
    a = _image(args[0], 'imbothat')
    cl = np.asarray(darr(REG['imclose'].fn(1, args[0], args[1])), F64)
    return _back(cl - a.astype(F64), a.dtype) if a.dtype != bool else ((cl != 0) & ~a)


# ---- labels in colour --------------------------------------------------------------------------------------------------

def _colormap(spec, n, fn):
    from ..colormaps import colormap_by_name, as_colormap
    if spec is None:
        return colormap_by_name('jet', max(n, 1))
    if isinstance(spec, FH):
        from ..runtime import run_sync
        return np.asarray(darr(run_sync(spec.acall(1, float(n)))), F64)
    s = opt_str(spec)
    if s is not None:
        return colormap_by_name(s, max(n, 1))
    return np.asarray(as_colormap(spec), F64)


def _color3(v, fn):
    from ..graphics_base import to_color
    return np.array(to_color(v), F64)


@bi('label2rgb')
def label2rgb(nargout, *args):
    """RGB = label2rgb(L, map, zerocolor, order): a label matrix as an RGB
    image (uint8): label k in colour k of the colormap (jet, as many colours
    as labels; a name, a matrix or a function), 0 in zerocolor (white);
    'shuffle' mixes the colours (by rng's generator)."""
    nargchk(args, 1, 4, 'label2rgb')
    L = np.asarray(darr(args[0]), F64)
    if L.ndim != 2 or np.any(L < 0) or np.any(L != np.round(L)):
        raise err('MATLAB:label2rgb:labels', 'L is a 2-D matrix of whole numbers from 0.', 'label2rgb')
    n = int(L.max()) if L.size else 0
    cmap = _colormap(args[1] if len(args) > 1 and numel(args[1]) else None, n, 'label2rgb')
    if cmap.shape[0] < n:
        raise err('MATLAB:label2rgb:map', f'The colormap has a colour for each of the {n} labels.', 'label2rgb')
    zero = _color3(args[2], 'label2rgb') if len(args) > 2 and numel(args[2]) else np.ones(3)
    if len(args) > 3:
        order = opt_lower(args[3])
        if order == 'shuffle':
            from .elmat import RNG
            cmap = cmap[RNG.rs.permutation(cmap.shape[0])]
        elif order != 'noshuffle':
            raise err('MATLAB:label2rgb:order', "order is 'noshuffle' or 'shuffle'.", 'label2rgb')
    table = np.vstack([zero, cmap[:max(n, 0)]])
    rgb = table[L.astype(int)]
    return np.round(np.clip(rgb, 0, 1) * 255).astype(np.uint8)


def _rgb_uint8(a):
    u = np.clip(_unit(a), 0, 1)
    if u.ndim == 2:
        u = np.stack([u] * 3, axis=2)
    return u


@bi('labeloverlay')
def labeloverlay(nargout, *args):
    """B = labeloverlay(A, L, 'Colormap', map, 'Transparency', t, 'IncludedLabels', ids): the labels' colours laid over the image (uint8), t (0.5) of the image showing through; label 0 untouched."""
    nargchk(args, 2, 8, 'labeloverlay')
    a = _image(args[0], 'labeloverlay')
    L = np.asarray(darr(args[1]), F64)
    o, rest = _opts(list(args[2:]), ('Colormap', 'Transparency', 'IncludedLabels'))
    if L.dtype == bool or L.shape != a.shape[:2]:
        L = L.astype(F64)
    if L.shape != a.shape[:2]:
        raise err('MATLAB:labeloverlay:size', 'A and L are the same size.', 'labeloverlay')
    n = int(L.max()) if L.size else 0
    cmap = _colormap(o.get('Colormap'), n, 'labeloverlay')
    t = float(num(o['Transparency'])) if 'Transparency' in o else 0.5
    base = _rgb_uint8(a)
    inc = np.asarray(darr(o['IncludedLabels']), F64).reshape(-1) if 'IncludedLabels' in o else np.arange(1, n + 1)
    mask = np.isin(L, inc) & (L > 0)
    col = np.zeros(base.shape)
    li = np.clip(L.astype(int) - 1, 0, max(cmap.shape[0] - 1, 0))
    col[mask] = cmap[li[mask]]
    res = np.where(mask[..., None], t * base + (1 - t) * col, base)
    return np.round(np.clip(res, 0, 1) * 255).astype(np.uint8)


@bi('imoverlay')
def imoverlay(nargout, *args):
    """B = imoverlay(A, BW, color): the image (made RGB) with the pixels where BW is on painted color (yellow), in A's class."""
    nargchk(args, 2, 3, 'imoverlay')
    a = _image(args[0], 'imoverlay')
    bw = _bw(args[1], 'imoverlay')
    if bw.shape != a.shape[:2]:
        raise err('MATLAB:imoverlay:size', 'A and BW are the same size.', 'imoverlay')
    col = _color3(args[2], 'imoverlay') if len(args) > 2 else np.array([1.0, 1.0, 0.0])
    base = _rgb_uint8(a)
    base[bw] = col
    return _as_class(base, a.dtype) if a.dtype != bool else base


# ---- colour spaces --------------------------------------------------------------------------------------------------

_M_SRGB = np.array([[0.412456439089692, 0.357576077643909, 0.180437483266399],
                    [0.212672851405623, 0.715152155287818, 0.072174993306559],
                    [0.019333895582330, 0.119192025881303, 0.950304078536368]])
_M_ADOBE = np.array([[0.5767309, 0.1855540, 0.1881852], [0.2973769, 0.6273491, 0.0752741], [0.0270343, 0.0706872, 0.9911085]])
_WHITES = {'d65': (0.95047, 1.0, 1.08883), 'd50': (0.96422, 1.0, 0.82521), 'a': (1.09850, 1.0, 0.35585), 'c': (0.98074, 1.0, 1.18232),
           'e': (1.0, 1.0, 1.0), 'icc': (0.9642, 1.0, 0.8249), 'd55': (0.95682, 1.0, 0.92149)}


def _space(o, fn):
    cs = opt_lower(o['ColorSpace']) if 'ColorSpace' in o else 'srgb'
    if cs not in ('srgb', 'adobe-rgb-1998', 'linear-rgb'):
        raise err(f'MATLAB:{fn}:space', "ColorSpace is 'srgb', 'adobe-rgb-1998' or 'linear-rgb'.", fn)
    return cs


def _white(o, fn):
    if 'WhitePoint' not in o:
        return np.array(_WHITES['d65'])
    w = o['WhitePoint']
    s = opt_lower(w) if is_str(w) else None
    if s is not None:
        if s not in _WHITES:
            raise err(f'MATLAB:{fn}:white', f"WhitePoint is one of {', '.join(_WHITES)} or [X Y Z].", fn)
        return np.array(_WHITES[s])
    return np.asarray(darr(w), F64).reshape(-1)[:3]


def _to_linear(c, cs):
    if cs == 'srgb':
        return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    if cs == 'adobe-rgb-1998':
        return np.sign(c) * np.abs(c) ** 2.19921875
    return c


def _from_linear(c, cs):
    if cs == 'srgb':
        return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.abs(c) ** (1 / 2.4) - 0.055)
    if cs == 'adobe-rgb-1998':
        return np.sign(c) * np.abs(c) ** (1 / 2.19921875)
    return c


def _rgb_in(v, fn):
    a = _image(v, fn)
    if not ((a.ndim == 3 and a.shape[2] == 3) or (a.ndim == 2 and a.shape[1] == 3)):
        raise err(f'MATLAB:{fn}:invalidInput', 'The input is an M-by-N-by-3 image or a c-by-3 colormap.', fn)
    return a, _unit(a).astype(F64) if a.dtype.kind in 'iub' else a.astype(F64)


def _xyz(rgb, cs):
    M = _M_ADOBE if cs == 'adobe-rgb-1998' else _M_SRGB
    return _to_linear(rgb, cs) @ M.T


def _lab_f(t):
    d = 6 / 29
    return np.where(t > d ** 3, np.cbrt(t), t / (3 * d * d) + 4 / 29)


def _lab_finv(t):
    d = 6 / 29
    return np.where(t > d, t ** 3, 3 * d * d * (t - 4 / 29))


@bi('rgb2xyz')
def rgb2xyz(nargout, *args):
    """XYZ = rgb2xyz(RGB, 'ColorSpace', cs, 'WhitePoint', w): RGB (sRGB by default, 'adobe-rgb-1998' or 'linear-rgb') as CIE 1931 XYZ, Y from 0 to 1 for white."""
    nargchk(args, 1, 5, 'rgb2xyz')
    o, _ = _opts(list(args[1:]), ('ColorSpace', 'WhitePoint'))
    a, c = _rgb_in(args[0], 'rgb2xyz')
    X = _xyz(c, _space(o, 'rgb2xyz'))
    return X.astype(np.float32) if a.dtype == np.float32 else X


@bi('xyz2rgb')
def xyz2rgb(nargout, *args):
    """RGB = xyz2rgb(XYZ, 'ColorSpace', cs, 'OutputType', type): CIE XYZ back as RGB (sRGB by default), clipped to 0 to 1 for the integer types."""
    nargchk(args, 1, 7, 'xyz2rgb')
    o, _ = _opts(list(args[1:]), ('ColorSpace', 'WhitePoint', 'OutputType'))
    X = np.asarray(darr(args[0]), F64)
    cs = _space(o, 'xyz2rgb')
    M = _M_ADOBE if cs == 'adobe-rgb-1998' else _M_SRGB
    rgb = _from_linear(X @ np.linalg.inv(M).T, cs)
    t = opt_lower(o['OutputType']) if 'OutputType' in o else 'double'
    return _as_class(rgb, np.dtype({'double': F64, 'single': np.float32, 'uint8': np.uint8, 'uint16': np.uint16}[t])) if t != 'double' else rgb


@bi('rgb2lab')
def rgb2lab(nargout, *args):
    """lab = rgb2lab(RGB, 'ColorSpace', cs, 'WhitePoint', w): RGB as CIE 1976 L*a*b* (L from 0 to 100), through XYZ, white D65 unless given."""
    nargchk(args, 1, 5, 'rgb2lab')
    o, _ = _opts(list(args[1:]), ('ColorSpace', 'WhitePoint'))
    a, c = _rgb_in(args[0], 'rgb2lab')
    X = _xyz(c, _space(o, 'rgb2lab')) / _white(o, 'rgb2lab')
    f = _lab_f(X)
    lab = np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)
    return lab.astype(np.float32) if a.dtype == np.float32 else lab


@bi('lab2rgb')
def lab2rgb(nargout, *args):
    """RGB = lab2rgb(lab, 'ColorSpace', cs, 'WhitePoint', w, 'OutputType', type): L*a*b* back as RGB (doubles, out-of-gamut values kept; clipped for the integer types)."""
    nargchk(args, 1, 7, 'lab2rgb')
    o, _ = _opts(list(args[1:]), ('ColorSpace', 'WhitePoint', 'OutputType'))
    lab = np.asarray(darr(args[0]), F64)
    if lab.shape[-1] != 3:
        raise err('MATLAB:lab2rgb:invalidInput', 'The input is an M-by-N-by-3 image or a c-by-3 colormap.', 'lab2rgb')
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    X = np.stack([_lab_finv(fx), _lab_finv(fy), _lab_finv(fz)], axis=-1) * _white(o, 'lab2rgb')
    cs = _space(o, 'lab2rgb')
    M = _M_ADOBE if cs == 'adobe-rgb-1998' else _M_SRGB
    rgb = _from_linear(X @ np.linalg.inv(M).T, cs)
    t = opt_lower(o['OutputType']) if 'OutputType' in o else 'double'
    if t not in ('double', 'single', 'uint8', 'uint16'):
        raise err('MATLAB:lab2rgb:type', "OutputType is 'double', 'single', 'uint8' or 'uint16'.", 'lab2rgb')
    return _as_class(rgb, np.dtype({'double': F64, 'single': np.float32, 'uint8': np.uint8, 'uint16': np.uint16}[t])) if t != 'double' else rgb


_YCC = np.array([[65.481, 128.553, 24.966], [-37.797, -74.203, 112.0], [112.0, -93.786, -18.214]])
_YOFF = np.array([16.0, 128.0, 128.0])


@bi('rgb2ycbcr')
def rgb2ycbcr(nargout, *args):
    """YCBCR = rgb2ycbcr(RGB): ITU-R BT.601 Y'CbCr: Y from 16 to 235 and Cb, Cr from 16 to 240 (over 255 for doubles), in the input's class."""
    nargchk(args, 1, 1, 'rgb2ycbcr')
    a, c = _rgb_in(args[0], 'rgb2ycbcr')
    y = (c @ _YCC.T + _YOFF) / 255
    return _as_class(y, a.dtype) if a.dtype.kind in 'iu' else y.astype(a.dtype if a.dtype.kind == 'f' else F64)


@bi('ycbcr2rgb')
def ycbcr2rgb(nargout, *args):
    """RGB = ycbcr2rgb(YCBCR): ITU-R BT.601 Y'CbCr back as RGB, in the input's class."""
    nargchk(args, 1, 1, 'ycbcr2rgb')
    a, c = _rgb_in(args[0], 'ycbcr2rgb')
    rgb = (c * 255 - _YOFF) @ np.linalg.inv(_YCC).T
    return _as_class(rgb, a.dtype) if a.dtype.kind in 'iu' else rgb.astype(a.dtype if a.dtype.kind == 'f' else F64)


@bi('im2int16')
def im2int16(nargout, *args):
    """J = im2int16(I): an image as int16, its range mapped onto -32768 to 32767 (doubles from 0 to 1, rounded)."""
    nargchk(args, 1, 2, 'im2int16')
    a = _image(args[0], 'im2int16')
    if a.dtype == np.int16:
        return a.copy()
    if a.dtype == bool:
        return np.where(a, 32767, -32768).astype(np.int16)
    return _as_class(np.clip(_unit(a), 0, 1), np.int16)


# ---- arithmetic ---------------------------------------------------------------------------------------------------------

def _out_class(a, args, k, fn):
    if len(args) > k:
        s = opt_lower(args[k])
        if s not in ('double', 'single', 'uint8', 'uint16', 'uint32', 'int8', 'int16', 'int32', 'logical'):
            raise err(f'MATLAB:{fn}:class', 'The output class is a numeric class.', fn)
        return np.dtype({'double': F64, 'single': np.float32, 'logical': bool}.get(s, s))
    return a.dtype if a.dtype != bool else np.dtype(F64)


def _arith(name, op):
    @bi(name)
    def f(nargout, *args):
        nargchk(args, 2, 3, name)
        a = _image(args[0], name, 'first image')
        b = np.asarray(arr(args[1], name))
        y = op(a.astype(F64), b.astype(F64))
        return _back(y, _out_class(a, args, 2, name))
    f.__doc__ = f'Z = {name}(X, Y, outputClass): the images (or an image and a number) {name[2:]}ed in double, in X\'s class (rounded and saturated) unless outputClass.'
    return f


_arith('imadd', np.add)
_arith('imsubtract', np.subtract)
_arith('immultiply', np.multiply)


@bi('imdivide')
def imdivide(nargout, *args):
    """Z = imdivide(X, Y): X./Y in double, in X's class (rounded and saturated)."""
    nargchk(args, 2, 2, 'imdivide')
    a = _image(args[0], 'imdivide')
    b = np.asarray(arr(args[1], 'imdivide')).astype(F64)
    with np.errstate(divide='ignore', invalid='ignore'):
        y = a.astype(F64) / b
    return _back(y, a.dtype if a.dtype != bool else F64)


@bi('imabsdiff')
def imabsdiff(nargout, *args):
    """Z = imabsdiff(X, Y): abs(X - Y) in double, in X's class."""
    nargchk(args, 2, 2, 'imabsdiff')
    a = _image(args[0], 'imabsdiff')
    b = np.asarray(arr(args[1], 'imabsdiff'))
    if b.shape != a.shape and b.size != 1:
        raise err('MATLAB:imabsdiff:size', 'X and Y are the same size.', 'imabsdiff')
    return _back(np.abs(a.astype(F64) - b.astype(F64)), a.dtype if a.dtype != bool else F64)


@bi('imlincomb')
def imlincomb(nargout, *args):
    """Z = imlincomb(K1, A1, K2, A2, ..., K, outputClass): K1*A1 + K2*A2 + ... + K in double, in A1's class unless outputClass."""
    a = list(args)
    cls = None
    if a and is_str(a[-1]):
        cls = opt_lower(a.pop())
    if len(a) < 2:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'imlincomb')
    const = float(num(a.pop())) if len(a) % 2 else 0.0
    first = None
    total = None
    for i in range(0, len(a), 2):
        k = float(num(a[i]))
        img = np.asarray(arr(a[i + 1], 'imlincomb'))
        first = img if first is None else first
        total = k * img.astype(F64) if total is None else total + k * img.astype(F64)
    total = total + const
    dt = np.dtype({'double': F64, 'single': np.float32}.get(cls, cls)) if cls else (first.dtype if first.dtype != bool else np.dtype(F64))
    return _back(total, dt)


# ---- noise, sharpening, fusing ----------------------------------------------------------------------------------------------

@bi('imnoise')
def imnoise(nargout, *args):
    """J = imnoise(I, type, ...): noise added on the 0-to-1 scale, the result
    clipped and in I's class: 'gaussian' (mean 0, variance 0.01),
    'localvar' (a variance per pixel, or per intensity), 'poisson' (each
    value a Poisson count: integers as they are, doubles scaled by 1e12),
    'salt & pepper' (density 0.05), 'speckle' (I + n.*I, n uniform with
    variance 0.05). The numbers come from rng's generator."""
    nargchk(args, 1, 4, 'imnoise')
    from .elmat import RNG
    a = _image(args[0], 'imnoise')
    kind = opt_lower(args[1]) if len(args) > 1 else 'gaussian'
    u = np.clip(_unit(a), 0, 1) if a.dtype.kind in 'iub' else a.astype(F64)
    p = [float(num(x)) if numel(x) == 1 else np.asarray(darr(x), F64) for x in args[2:]]
    shape = u.shape

    def randn():
        return RNG.rs.standard_normal(int(np.prod(shape))).reshape(shape, order='F')

    def rand():
        return RNG.uniform(shape)
    if kind == 'gaussian':
        m = p[0] if p else 0.0
        v = p[1] if len(p) > 1 else 0.01
        y = u + m + np.sqrt(v) * randn()
    elif kind == 'localvar':
        if len(p) == 1:
            y = u + np.sqrt(np.asarray(p[0], F64)) * randn()
        elif len(p) == 2:
            lv, var = np.asarray(p[0], F64).reshape(-1), np.asarray(p[1], F64).reshape(-1)
            y = u + np.sqrt(np.interp(u, lv, var)) * randn()
        else:
            raise err('MATLAB:imnoise:localvar', "'localvar' takes the variances, or intensities and their variances.", 'imnoise')
    elif kind == 'poisson':
        if a.dtype.kind in 'iub':
            lo, hi = _RANGE.get(a.dtype, (0.0, 1.0))
            vals = a.astype(F64)
            y = RNG.rs.poisson(np.clip(vals, 0, None)).astype(F64)
            return _back(y, a.dtype) if a.dtype != bool else y > 0
        y = RNG.rs.poisson(np.clip(u, 0, None) * 1e12) / 1e12
    elif kind in ('salt & pepper', 'salt and pepper'):
        d = p[0] if p else 0.05
        x = rand()
        y = u.copy()
        y[x < d / 2] = 0
        y[(x >= d / 2) & (x < d)] = 1
    elif kind == 'speckle':
        v = p[0] if p else 0.05
        y = u + np.sqrt(12 * v) * u * (rand() - 0.5)
    else:
        raise err('MATLAB:imnoise:type', "The type is 'gaussian', 'localvar', 'poisson', 'salt & pepper' or 'speckle'.", 'imnoise')
    y = np.clip(y, 0, 1)
    if a.dtype.kind in 'iu':
        return _as_class(y, a.dtype)
    if a.dtype == bool:
        return y > 0.5
    return y.astype(a.dtype)


def _gauss(p, sigma, mode='nearest'):
    from scipy import ndimage
    size = 2 * math.ceil(2 * sigma) + 1
    return ndimage.gaussian_filter(p, sigma, mode=mode, truncate=(size // 2) / sigma)


@bi('imsharpen')
def imsharpen(nargout, *args):
    """B = imsharpen(A, 'Radius', 1, 'Amount', 0.8, 'Threshold', 0): unsharp
    masking: A + Amount*(A - its Gaussian blur of standard deviation Radius),
    only where that difference exceeds Threshold (of the full range); an RGB
    image is sharpened in its L*a*b* lightness."""
    nargchk(args, 1, 7, 'imsharpen')
    a = _image(args[0], 'imsharpen')
    o, _ = _opts(list(args[1:]), ('Radius', 'Amount', 'Threshold'))
    rad = float(num(o['Radius'])) if 'Radius' in o else 1.0
    amt = float(num(o['Amount'])) if 'Amount' in o else 0.8
    thr = float(num(o['Threshold'])) if 'Threshold' in o else 0.0

    def sharpen(p, scale):
        d = p - _gauss(p, rad)
        return p + amt * d * (np.abs(d) > thr * scale)
    if a.ndim == 3 and a.shape[2] == 3:
        lab = np.asarray(darr(rgb2lab(1, out(np.clip(_unit(a), 0, 1)))))
        lab[..., 0] = np.clip(sharpen(lab[..., 0], 100.0), 0, 100)
        rgb = np.asarray(darr(lab2rgb(1, out(lab))))
        return _as_class(np.clip(rgb, 0, 1), a.dtype) if a.dtype != bool else rgb
    u = np.clip(_unit(a), 0, 1) if a.dtype.kind in 'iub' else a.astype(F64)
    y = sharpen(u, 1.0)
    return _as_class(np.clip(y, 0, 1), a.dtype) if a.dtype.kind in 'iu' else y.astype(a.dtype if a.dtype.kind == 'f' else F64)


def _fit2(a, b):
    """Both images (gray, 0 to 1) on a canvas the size of the larger, top-left aligned, zeros outside."""
    def gray(x):
        u = np.clip(_unit(x), 0, 1) if x.dtype.kind in 'iub' else x.astype(F64)
        if u.ndim == 3:
            u = u[..., :3] @ np.array([0.298936021293775, 0.587043074451121, 0.114020904255103])
        return u
    ga, gb = gray(a), gray(b)
    m, n = max(ga.shape[0], gb.shape[0]), max(ga.shape[1], gb.shape[1])
    A = np.zeros((m, n))
    B = np.zeros((m, n))
    A[:ga.shape[0], :ga.shape[1]] = ga
    B[:gb.shape[0], :gb.shape[1]] = gb
    return A, B


def _scale01(x):
    lo, hi = float(x.min()), float(x.max())
    return (x - lo) / (hi - lo) if hi > lo else np.zeros(x.shape)


@bi('imfuse', nout=2)
def imfuse(nargout, *args):
    """C = imfuse(A, B, method, 'Scaling', s, 'ColorChannels', c): two images
    as one RGB uint8 image to compare: 'falsecolor' (default; A green, B
    magenta: ColorChannels [2 1 2], or 'red-cyan'), 'blend' (half each),
    'diff' (the absolute difference), 'checkerboard' (squares of each, 8 by 8
    of them) or 'montage' (side by side); 'Scaling' 'independent' (each to its
    full range, default), 'joint' or 'none'."""
    nargchk(args, 2, 7, 'imfuse')
    a = _image(args[0], 'imfuse')
    b = _image(args[1], 'imfuse')
    rest = list(args[2:])
    method = 'falsecolor'
    if rest and is_str(rest[0]) and opt_lower(rest[0]) in ('falsecolor', 'blend', 'diff', 'checkerboard', 'montage'):
        method = opt_lower(rest.pop(0))
    o, _ = _opts(rest, ('Scaling', 'ColorChannels'))
    if method == 'montage':
        A = np.clip(_unit(a), 0, 1) if a.dtype.kind in 'iub' else a.astype(F64)
        B = np.clip(_unit(b), 0, 1) if b.dtype.kind in 'iub' else b.astype(F64)
        A3 = A if A.ndim == 3 else np.stack([A] * 3, axis=2)
        B3 = B if B.ndim == 3 else np.stack([B] * 3, axis=2)
        m = max(A3.shape[0], B3.shape[0])
        canvas = np.zeros((m, A3.shape[1] + B3.shape[1], 3))
        canvas[:A3.shape[0], :A3.shape[1]] = A3
        canvas[:B3.shape[0], A3.shape[1]:] = B3
        return np.round(np.clip(canvas, 0, 1) * 255).astype(np.uint8)
    A, B = _fit2(a, b)
    sc = opt_lower(o['Scaling']) if 'Scaling' in o else 'independent'
    if sc == 'independent':
        A, B = _scale01(A), _scale01(B)
    elif sc == 'joint':
        lo, hi = min(A.min(), B.min()), max(A.max(), B.max())
        A, B = (A - lo) / (hi - lo or 1), (B - lo) / (hi - lo or 1)
    elif sc != 'none':
        raise err('MATLAB:imfuse:scaling', "Scaling is 'independent', 'joint' or 'none'.", 'imfuse')
    if method == 'falsecolor':
        cc = o.get('ColorChannels')
        if cc is None or (is_str(cc) and opt_lower(cc) == 'green-magenta'):
            ch = [2, 1, 2]
        elif is_str(cc) and opt_lower(cc) == 'red-cyan':
            ch = [1, 2, 2]
        else:
            ch = [int(x) for x in np.asarray(darr(cc)).reshape(-1)]
        planes = [A if k == 1 else B if k == 2 else np.zeros(A.shape) for k in ch]
        C = np.stack(planes, axis=2)
    elif method == 'blend':
        C = np.stack([(A + B) / 2] * 3, axis=2)
    elif method == 'diff':
        d = np.abs(A - B)
        C = np.stack([_scale01(d) if sc != 'none' else d] * 3, axis=2)
    else:
        m, n = A.shape
        rr = (np.arange(m) * 8 // max(m, 1))[:, None]
        cc_ = (np.arange(n) * 8 // max(n, 1))[None, :]
        pick = ((rr + cc_) % 2) == 0
        C = np.stack([np.where(pick, A, B)] * 3, axis=2)
    return np.round(np.clip(C, 0, 1) * 255).astype(np.uint8)


@bi('imshowpair', arr=False)
def imshowpair(nargout, *args):
    """h = imshowpair(A, B, method, ...): imfuse's comparison of the two images shown."""
    C = imfuse(1, *args)
    return REG['imshow'].fn(nargout, C)


# ---- quality measures ---------------------------------------------------------------------------------------------------

def _pair(args, fn):
    a = np.asarray(arr(args[0], fn))
    b = np.asarray(arr(args[1], fn))
    if a.shape != b.shape:
        raise err(f'MATLAB:{fn}:size', 'The two images are the same size.', fn)
    if a.dtype != b.dtype and not (a.dtype.kind == 'f' and b.dtype.kind == 'f'):
        raise err(f'MATLAB:{fn}:class', 'The two images are of the same class.', fn)
    return a, b


@bi('corr2')
def corr2(nargout, *args):
    """r = corr2(A, B): the correlation coefficient of two matrices of the same size."""
    nargchk(args, 2, 2, 'corr2')
    a = np.asarray(darr(args[0]), F64)
    b = np.asarray(darr(args[1]), F64)
    if a.shape != b.shape:
        raise err('MATLAB:corr2:size', 'A and B are the same size.', 'corr2')
    da, db = a - a.mean(), b - b.mean()
    den = math.sqrt(float(np.sum(da * da)) * float(np.sum(db * db)))
    return float(np.sum(da * db) / den) if den > 0 else float('nan')


@bi('immse')
def immse(nargout, *args):
    """err = immse(X, Y): the mean squared error between two images (in double; single stays single)."""
    nargchk(args, 2, 2, 'immse')
    a, b = _pair(args, 'immse')
    e = float(np.mean((a.astype(F64) - b.astype(F64)) ** 2))
    return np.float32(e) if a.dtype == np.float32 else e


def _peak(a):
    if a.dtype.kind in 'iu':
        info = np.iinfo(a.dtype)
        return float(info.max - info.min) if info.min < 0 else float(info.max)
    return 1.0


@bi('psnr', nout=2)
def psnr(nargout, *args):
    """[peaksnr, snr] = psnr(A, ref, peakval): the peak signal-to-noise ratio
    in dB, 10*log10(peakval^2/mse) (peakval 1 for floating images, the class's
    largest value for integers), and the signal-to-noise ratio
    10*log10(mean(ref.^2)/mse)."""
    nargchk(args, 2, 3, 'psnr')
    a, b = _pair(args, 'psnr')
    peak = float(num(args[2])) if len(args) > 2 else _peak(a)
    mse = float(np.mean((a.astype(F64) - b.astype(F64)) ** 2))
    with np.errstate(divide='ignore'):
        p = 10 * math.log10(peak ** 2 / mse) if mse > 0 else math.inf
        s = 10 * math.log10(float(np.mean(b.astype(F64) ** 2)) / mse) if mse > 0 else math.inf
    return _outs(nargout, p, s)


@bi('ssim', nout=2)
def ssim(nargout, *args):
    """[ssimval, ssimmap] = ssim(A, ref, 'Radius', 1.5, 'DynamicRange', L,
    'Exponents', [1 1 1], 'RegularizationConstants', [C1 C2 C3]): the
    structural similarity index: local means, variances and covariance by a
    Gaussian of standard deviation Radius (2*ceil(3*Radius)+1 wide, the
    border replicated), C1 = (0.01*L)^2, C2 = (0.03*L)^2, C3 = C2/2; ssimval
    the mean of the map."""
    nargchk(args, 2, 10, 'ssim')
    a, b = _pair(args, 'ssim')
    o, _ = _opts(list(args[2:]), ('Radius', 'DynamicRange', 'Exponents', 'RegularizationConstants'))
    rad = float(num(o['Radius'])) if 'Radius' in o else 1.5
    L = float(num(o['DynamicRange'])) if 'DynamicRange' in o else _peak(a)
    ex = np.asarray(darr(o['Exponents']), F64).reshape(-1) if 'Exponents' in o else np.ones(3)
    if 'RegularizationConstants' in o:
        C1, C2, C3 = (float(x) for x in np.asarray(darr(o['RegularizationConstants']), F64).reshape(-1)[:3])
    else:
        C1, C2 = (0.01 * L) ** 2, (0.03 * L) ** 2
        C3 = C2 / 2
    from scipy import ndimage
    x, y = a.astype(F64), b.astype(F64)
    half = math.ceil(3 * rad)

    def g(p):
        return ndimage.gaussian_filter(p, rad, mode='nearest', truncate=half / rad)
    mx, my = g(x), g(y)
    sxx = np.maximum(g(x * x) - mx * mx, 0)
    syy = np.maximum(g(y * y) - my * my, 0)
    sxy = g(x * y) - mx * my
    if np.allclose(ex, 1) and abs(C3 - C2 / 2) < 1e-15 * max(C2, 1):
        smap = ((2 * mx * my + C1) * (2 * sxy + C2)) / ((mx * mx + my * my + C1) * (sxx + syy + C2))
    else:
        sx, sy = np.sqrt(sxx), np.sqrt(syy)
        lum = (2 * mx * my + C1) / (mx * mx + my * my + C1)
        con = (2 * sx * sy + C2) / (sxx + syy + C2)
        st = (sxy + C3) / (sx * sy + C3)
        smap = np.sign(lum) * np.abs(lum) ** ex[0] * np.abs(con) ** ex[1] * np.sign(st) * np.abs(st) ** ex[2]
    val = float(np.mean(smap))
    if a.dtype == np.float32:
        return _outs(nargout, np.float32(val), smap.astype(np.float32))
    return _outs(nargout, val, smap)


def _counts256(a):
    if a.dtype == bool:
        return np.bincount(a.reshape(-1).astype(int), minlength=2).astype(F64)
    u8 = _as_class(np.clip(_unit(a), 0, 1), np.uint8) if a.dtype != np.uint8 else a
    return np.bincount(u8.reshape(-1).astype(int), minlength=256).astype(F64)


@bi('entropy')
def entropy(nargout, *args):
    """e = entropy(I): -sum(p.*log2(p)) over the image's 256-bin histogram (the image as uint8; 2 bins for logical)."""
    nargchk(args, 1, 1, 'entropy')
    a = _image(args[0], 'entropy')
    c = _counts256(a)
    p = c[c > 0] / c.sum() if c.sum() else np.zeros(0)
    return float(-np.sum(p * np.log2(p)))


def _nhood(args, k, default, fn):
    if len(args) > k:
        h = np.asarray(darr(args[k])) != 0
        if h.ndim != 2 or h.shape[0] % 2 == 0 or h.shape[1] % 2 == 0:
            raise err(f'MATLAB:{fn}:nhood', 'The neighbourhood is a logical array of odd size.', fn)
        return h
    return np.ones(default, bool)


@bi('entropyfilt')
def entropyfilt(nargout, *args):
    """J = entropyfilt(I, nhood): each pixel's local entropy over its 9-by-9 neighbourhood (or nhood), the image as uint8, the border mirrored."""
    nargchk(args, 1, 2, 'entropyfilt')
    from scipy import ndimage
    a = _image(args[0], 'entropyfilt')
    h = _nhood(args, 1, (9, 9), 'entropyfilt')
    planes, back = _planes(a)
    res = []
    for p in planes:
        if a.dtype == bool:
            q = p.astype(int)
            levels = (0, 1)
        else:
            q = _as_class(np.clip(_unit(p), 0, 1), np.uint8).astype(int) if a.dtype != np.uint8 else p.astype(int)
            levels = np.unique(q)
        n = h.sum()
        E = np.zeros(q.shape)
        for v in levels:
            cnt = ndimage.correlate((q == v).astype(F64), h.astype(F64), mode='reflect')
            pr = cnt / n
            with np.errstate(divide='ignore', invalid='ignore'):
                E -= np.where(pr > 0, pr * np.log2(np.where(pr > 0, pr, 1)), 0)
        res.append(E)
    return back(res)


@bi('stdfilt')
def stdfilt(nargout, *args):
    """J = stdfilt(I, nhood): each pixel's local standard deviation (normalized by n - 1) over its 3-by-3 neighbourhood (or nhood), the border mirrored."""
    nargchk(args, 1, 2, 'stdfilt')
    from scipy import ndimage
    a = _image(args[0], 'stdfilt')
    h = _nhood(args, 1, (3, 3), 'stdfilt').astype(F64)
    n = h.sum()
    planes, back = _planes(a)
    res = []
    for p in planes:
        x = p.astype(F64)
        s1 = ndimage.correlate(x, h, mode='reflect')
        s2 = ndimage.correlate(x * x, h, mode='reflect')
        res.append(np.sqrt(np.maximum((s2 - s1 * s1 / n) / max(n - 1, 1), 0)))
    return back(res)


@bi('rangefilt')
def rangefilt(nargout, *args):
    """J = rangefilt(I, nhood): each pixel's local range (largest less smallest) over its 3-by-3 neighbourhood (or nhood), outside the image ignored, in I's class."""
    nargchk(args, 1, 2, 'rangefilt')
    a = _image(args[0], 'rangefilt')
    h = _nhood(args, 1, (3, 3), 'rangefilt')
    planes, back = _planes(a)
    res = [_morph(p, h, True) - _morph(p, h, False) for p in planes]
    y = back(res)
    if a.dtype == bool:
        return y > 0.5
    return _back(y, a.dtype)


@bi('imboxfilt')
def imboxfilt(nargout, *args):
    """B = imboxfilt(A, filterSize, 'Padding', p, 'NormalizationFactor', f): the mean over a box (3-by-3, odd sizes), the border replicated unless 'circular', 'symmetric' or a number; f 1/prod(filterSize) unless given."""
    nargchk(args, 1, 6, 'imboxfilt')
    from scipy import ndimage
    a = _image(args[0], 'imboxfilt')
    rest = list(args[1:])
    sz = (3, 3)
    if rest and not is_str(rest[0]):
        s = np.asarray(darr(rest.pop(0)), int).reshape(-1)
        sz = (int(s[0]), int(s[-1]))
    if sz[0] % 2 == 0 or sz[1] % 2 == 0:
        raise err('MATLAB:imboxfilt:size', 'The filter size is odd.', 'imboxfilt')
    o, _ = _opts(rest, ('Padding', 'NormalizationFactor'))
    pad = o.get('Padding')
    mode, cval = 'nearest', 0.0
    if pad is not None:
        if is_str(pad):
            mode = {'replicate': 'nearest', 'circular': 'wrap', 'symmetric': 'reflect'}.get(opt_lower(pad))
            if mode is None:
                raise err('MATLAB:imboxfilt:padding', "Padding is 'replicate', 'circular', 'symmetric' or a number.", 'imboxfilt')
        else:
            mode, cval = 'constant', float(num(pad))
    f = float(num(o['NormalizationFactor'])) if 'NormalizationFactor' in o else 1.0 / (sz[0] * sz[1])
    planes, back = _planes(a)
    res = [ndimage.uniform_filter(p.astype(F64), size=sz, mode=mode, cval=cval) * (sz[0] * sz[1]) * f for p in planes]
    return _back(back(res), a.dtype if a.dtype != bool else F64)


@bi('integralImage')
def integralImage(nargout, *args):
    """J = integralImage(I): the sums of I over the rectangles from its corner, a row and a column of zeros first: sum(I(r1:r2, c1:c2)) = J(r2+1,c2+1) - J(r1,c2+1) - J(r2+1,c1) + J(r1,c1)."""
    nargchk(args, 1, 2, 'integralImage')
    a = np.asarray(arr(args[0], 'integralImage'), F64)
    if a.ndim > 2:
        return np.stack([integralImage(1, out(a[:, :, k])) for k in range(a.shape[2])], axis=2)
    J = np.zeros((a.shape[0] + 1, a.shape[1] + 1))
    J[1:, 1:] = np.cumsum(np.cumsum(a, axis=0), axis=1)
    return J


@bi('imguidedfilter')
def imguidedfilter(nargout, *args):
    """B = imguidedfilter(A, G, 'NeighborhoodSize', [5 5], 'DegreeOfSmoothing', d): He's guided filter: A smoothed while following G's edges (G = A by default), with box means and d = 0.01*diff(range of G's class)^2."""
    nargchk(args, 1, 6, 'imguidedfilter')
    from scipy import ndimage
    a = _image(args[0], 'imguidedfilter')
    rest = list(args[1:])
    g = a
    if rest and not is_str(rest[0]):
        g = _image(rest.pop(0), 'imguidedfilter', 'guide')
    o, _ = _opts(rest, ('NeighborhoodSize', 'DegreeOfSmoothing'))
    ns = np.asarray(darr(o['NeighborhoodSize']), int).reshape(-1) if 'NeighborhoodSize' in o else np.array([5, 5])
    ns = (int(ns[0]), int(ns[-1]))
    rng_ = (_RANGE.get(g.dtype, (0.0, 1.0)))
    eps_ = float(num(o['DegreeOfSmoothing'])) if 'DegreeOfSmoothing' in o else 0.01 * (rng_[1] - rng_[0]) ** 2

    def box(p):
        return ndimage.uniform_filter(p, size=ns, mode='reflect')
    A = a.astype(F64)
    G = g.astype(F64)
    if G.ndim == 3:
        G = G.mean(axis=2)
    planes, back = _planes(A)
    res = []
    for p in planes:
        mI, mp = box(G), box(p)
        cov = box(G * p) - mI * mp
        var = box(G * G) - mI * mI
        aa = cov / (var + eps_)
        bb = mp - aa * mI
        res.append(box(aa) * G + box(bb))
    return _back(back(res), a.dtype if a.dtype != bool else F64)


@bi('imbilatfilt')
def imbilatfilt(nargout, *args):
    """J = imbilatfilt(I, degreeOfSmoothing, spatialSigma, 'NeighborhoodSize', s, 'Padding', p): the bilateral filter: each pixel the mean of its neighbours weighted by a Gaussian of distance (spatialSigma, 1) and of intensity difference (variance degreeOfSmoothing, 0.01*diff(range)^2); neighbourhood 2*ceil(2*spatialSigma)+1, the border replicated."""
    nargchk(args, 1, 7, 'imbilatfilt')
    a = _image(args[0], 'imbilatfilt')
    rest = list(args[1:])
    rng_ = _RANGE.get(a.dtype, (0.0, 1.0))
    dos = 0.01 * (rng_[1] - rng_[0]) ** 2
    ss = 1.0
    if rest and not is_str(rest[0]):
        dos = float(num(rest.pop(0)))
    if rest and not is_str(rest[0]):
        ss = float(num(rest.pop(0)))
    o, _ = _opts(rest, ('NeighborhoodSize', 'Padding'))
    w = int(num(o['NeighborhoodSize'])) if 'NeighborhoodSize' in o else 2 * math.ceil(2 * ss) + 1
    r = w // 2
    planes, back = _planes(a)
    res = []
    for p in planes:
        x = p.astype(F64)
        P = np.pad(x, r, mode='edge')
        num_, den = np.zeros(x.shape), np.zeros(x.shape)
        for di in range(-r, r + 1):
            for dj in range(-r, r + 1):
                q = P[r + di:r + di + x.shape[0], r + dj:r + dj + x.shape[1]]
                wgt = math.exp(-(di * di + dj * dj) / (2 * ss * ss)) * np.exp(-(q - x) ** 2 / (2 * dos))
                num_ += wgt * q
                den += wgt
        res.append(num_ / den)
    return _back(back(res), a.dtype if a.dtype != bool else F64)


@bi('imdiffusefilt')
def imdiffusefilt(nargout, *args):
    """J = imdiffusefilt(I, 'GradientThreshold', K, 'NumberOfIterations', 5,
    'Connectivity', 'maximal', 'ConductionMethod', 'exponential'): Perona and
    Malik's anisotropic diffusion: each step adds the differences to the
    neighbours (8, diagonals at half weight, or 4 for 'minimal') times the
    conduction exp(-(d/K)^2) ('quadratic': 1/(1 + (d/K)^2)); K is a tenth of
    the image's range unless given."""
    nargchk(args, 1, 9, 'imdiffusefilt')
    a = _image(args[0], 'imdiffusefilt')
    o, _ = _opts(list(args[1:]), ('GradientThreshold', 'NumberOfIterations', 'Connectivity', 'ConductionMethod'))
    x = a.astype(F64)
    K = float(num(o['GradientThreshold'])) if 'GradientThreshold' in o else 0.1 * (float(x.max() - x.min()) or 1.0)
    iters = int(num(o['NumberOfIterations'])) if 'NumberOfIterations' in o else 5
    conn = opt_lower(o['Connectivity']) if 'Connectivity' in o else 'maximal'
    meth = opt_lower(o['ConductionMethod']) if 'ConductionMethod' in o else 'exponential'
    nbrs = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0)]
    if conn == 'maximal':
        nbrs += [(-1, -1, 0.5), (-1, 1, 0.5), (1, -1, 0.5), (1, 1, 0.5)]
    dt = 1 / 7 if conn == 'maximal' else 1 / 4
    for _ in range(iters):
        P = np.pad(x, 1, mode='edge')
        acc = np.zeros(x.shape)
        for di, dj, wgt in nbrs:
            d = P[1 + di:1 + di + x.shape[0], 1 + dj:1 + dj + x.shape[1]] - x
            c = np.exp(-(d / K) ** 2) if meth == 'exponential' else 1 / (1 + (d / K) ** 2)
            acc += wgt * c * d
        x = x + dt * acc
    return _back(x, a.dtype if a.dtype != bool else F64)


@bi('imgaussfilt3')
def imgaussfilt3(nargout, *args):
    """B = imgaussfilt3(A, sigma, 'FilterSize', s, 'Padding', p): a 3-D Gaussian filter (sigma 0.5, a number or one for each dimension), 2*ceil(2*sigma)+1 wide, the border replicated."""
    nargchk(args, 1, 6, 'imgaussfilt3')
    from scipy import ndimage
    a = _image(args[0], 'imgaussfilt3')
    rest = list(args[1:])
    sig = np.array([0.5, 0.5, 0.5])
    if rest and not is_str(rest[0]):
        s = np.asarray(darr(rest.pop(0)), F64).reshape(-1)
        sig = np.broadcast_to(s, (3,)).astype(F64)
    o, _ = _opts(rest, ('FilterSize', 'Padding'))
    size = np.asarray(darr(o['FilterSize']), F64).reshape(-1) if 'FilterSize' in o else 2 * np.ceil(2 * sig) + 1
    size = np.broadcast_to(size, (3,))
    mode = {'replicate': 'nearest', 'circular': 'wrap', 'symmetric': 'reflect'}.get(opt_lower(o['Padding']) if 'Padding' in o else 'replicate', 'nearest')
    x = a.astype(F64)
    if x.ndim < 3:
        x = x.reshape(x.shape + (1,) * (3 - x.ndim))
    y = ndimage.gaussian_filter(x, sig, mode=mode, truncate=float(np.min((size // 2) / sig)))
    return _back(y.reshape(a.shape), a.dtype if a.dtype != bool else F64)


@bi('ordfilt2')
def ordfilt2(nargout, *args):
    """B = ordfilt2(A, order, domain, padopt): each pixel the order-th smallest of its neighbours where domain is true (its centre at floor((size+1)/2)); outside zeros, or 'symmetric'."""
    nargchk(args, 3, 5, 'ordfilt2')
    from scipy import ndimage
    a = _img2(args[0], 'ordfilt2')
    order = int(num(args[1]))
    dom = np.asarray(darr(args[2])) != 0
    if len(args) > 3 and not is_str(args[3]):
        raise err('MATLAB:ordfilt2:offsets', 'Nonflat offsets (S) are not taken here.', 'ordfilt2')
    pad = opt_lower(args[-1]) if len(args) > 3 and is_str(args[-1]) else 'zeros'
    k = int(dom.sum())
    if not 1 <= order <= k:
        raise err('MATLAB:ordfilt2:order', f'order is from 1 to the {k} pixels of the domain.', 'ordfilt2')
    origin = [((s + 1) // 2 - 1) - s // 2 for s in dom.shape]
    y = ndimage.rank_filter(a.astype(F64), order - 1, footprint=dom, mode='reflect' if pad == 'symmetric' else 'constant', cval=0.0, origin=origin)
    return _back(y, a.dtype if a.dtype != bool else F64) if a.dtype != bool else y > 0.5


@bi('wiener2', nout=2)
def wiener2(nargout, *args):
    """[J, noise] = wiener2(I, [m n], noise): adaptive Wiener filtering: the local mean plus (local variance less the noise power)/(local variance) of the difference, over m-by-n (3-by-3) neighbourhoods (zeros outside); the noise power the mean local variance unless given."""
    nargchk(args, 1, 3, 'wiener2')
    from scipy import ndimage
    a = _img2(args[0], 'wiener2')
    rest = list(args[1:])
    sz = (3, 3)
    noise = None
    if rest and numel(rest[0]) == 2:
        s = np.asarray(darr(rest.pop(0)), int).reshape(-1)
        sz = (int(s[0]), int(s[1]))
    if rest:
        noise = float(num(rest.pop(0)))
    x = a.astype(F64) if a.dtype.kind == 'f' else _unit(a)
    k = np.ones(sz) / (sz[0] * sz[1])
    origin = [((s + 1) // 2 - 1) - s // 2 for s in sz]
    mu = ndimage.correlate(x, k, mode='constant', origin=origin)
    var = ndimage.correlate(x * x, k, mode='constant', origin=origin) - mu * mu
    if noise is None:
        noise = float(np.mean(var))
    with np.errstate(divide='ignore', invalid='ignore'):
        y = mu + np.where(np.maximum(var, noise) > 0, np.maximum(var - noise, 0) / np.maximum(var, noise), 0) * (x - mu)
    res = _as_class(np.clip(y, 0, 1), a.dtype) if a.dtype.kind in 'iu' else y.astype(a.dtype if a.dtype.kind == 'f' else F64)
    return _outs(nargout, res, noise)


# ---- deconvolution --------------------------------------------------------------------------------------------------------

def _psf2otf(psf, shape):
    p = np.zeros(shape)
    psf = np.asarray(psf, F64)
    p[tuple(slice(0, s) for s in psf.shape)] = psf
    for ax, s in enumerate(psf.shape):
        p = np.roll(p, -(s // 2), axis=ax)
    return np.fft.fftn(p)


@bi('psf2otf')
def psf2otf(nargout, *args):
    """OTF = psf2otf(PSF, outSize): the optical transfer function: the PSF padded to outSize, its centre moved to the first element, transformed by fftn."""
    nargchk(args, 1, 2, 'psf2otf')
    psf = np.asarray(darr(args[0]), F64)
    shape = tuple(int(x) for x in np.asarray(darr(args[1])).reshape(-1)) if len(args) > 1 else psf.shape
    if len(shape) < psf.ndim or any(s < p for s, p in zip(shape, psf.shape)):
        raise err('MATLAB:psf2otf:size', 'outSize is no smaller than the PSF.', 'psf2otf')
    otf = _psf2otf(psf, shape)
    n_ops = np.sum(np.array(psf.shape) * np.log2(np.maximum(psf.shape, 2)))
    if np.max(np.abs(otf.imag)) / max(np.max(np.abs(otf)), 1e-300) <= n_ops * np.spacing(1.0):
        otf = otf.real
    return out(otf)


@bi('otf2psf')
def otf2psf(nargout, *args):
    """PSF = otf2psf(OTF, outSize): the point-spread function of an optical transfer function (ifftn, centred, cropped to outSize)."""
    nargchk(args, 1, 2, 'otf2psf')
    otf = np.asarray(darr(args[0]))
    shape = tuple(int(x) for x in np.asarray(darr(args[1])).reshape(-1)) if len(args) > 1 else otf.shape
    p = np.fft.ifftn(otf)
    for ax, s in enumerate(shape):
        p = np.roll(p, s // 2, axis=ax)
    p = p[tuple(slice(0, s) for s in shape)]
    return out(p.real if np.max(np.abs(p.imag)) < 1e-10 * max(np.max(np.abs(p)), 1e-300) else p)


@bi('deconvwnr')
def deconvwnr(nargout, *args):
    """J = deconvwnr(I, PSF, NSR): Wiener deconvolution, I's spectrum times conj(H)./(abs(H).^2 + NSR) (NSR 0 by default: the plain inverse where H is not 0), the blur taken as circular."""
    nargchk(args, 2, 4, 'deconvwnr')
    a = _image(args[0], 'deconvwnr')
    psf = np.asarray(darr(args[1]), F64)
    nsr = np.asarray(darr(args[2]), F64) if len(args) > 2 else np.array(0.0)
    if len(args) > 3:
        nsr = np.asarray(darr(args[2]), F64) / np.maximum(np.asarray(darr(args[3]), F64), 1e-300)
    x = a.astype(F64) if a.dtype.kind == 'f' else _unit(a)
    planes, back = _planes(x)
    res = []
    for p in planes:
        H = _psf2otf(psf, p.shape)
        den = np.abs(H) ** 2 + nsr
        with np.errstate(divide='ignore', invalid='ignore'):
            G = np.where(den > 0, np.conj(H) / np.where(den > 0, den, 1), 0)
        res.append(np.real(np.fft.ifft2(G * np.fft.fft2(p))))
    y = back(res)
    return _as_class(np.clip(y, 0, 1), a.dtype) if a.dtype.kind in 'iu' else y.astype(a.dtype if a.dtype.kind == 'f' else F64)


@bi('deconvlucy')
def deconvlucy(nargout, *args):
    """J = deconvlucy(I, PSF, numit): Richardson-Lucy deconvolution, numit (10) plain multiplicative steps J = J.*(H'*(I./(H*J))) with the blur circular (no acceleration or damping here)."""
    nargchk(args, 2, 6, 'deconvlucy')
    a = _image(args[0], 'deconvlucy')
    psf = np.asarray(darr(args[1]), F64)
    psf = psf / psf.sum()
    it = int(num(args[2])) if len(args) > 2 and numel(args[2]) else 10
    x = a.astype(F64) if a.dtype.kind == 'f' else _unit(a)
    planes, back = _planes(x)
    res = []
    for p in planes:
        H = _psf2otf(psf, p.shape)
        J = p.copy()
        for _ in range(it):
            est = np.real(np.fft.ifft2(H * np.fft.fft2(J)))
            ratio = np.where(est > 0, p / np.where(est > 0, est, 1), 0)
            J = J * np.real(np.fft.ifft2(np.conj(H) * np.fft.fft2(ratio)))
        res.append(J)
    y = back(res)
    return _as_class(np.clip(y, 0, 1), a.dtype) if a.dtype.kind in 'iu' else y.astype(a.dtype if a.dtype.kind == 'f' else F64)


# ---- padding and blocks ---------------------------------------------------------------------------------------------------

@bi('padarray')
def padarray(nargout, *args):
    """B = padarray(A, padsize, padval, direction): A padded by padsize along
    each dimension, with padval (0) or 'circular', 'replicate' or 'symmetric',
    'both' (default), 'pre' or 'post'."""
    nargchk(args, 2, 4, 'padarray')
    a = np.asarray(arr(args[0], 'padarray'))
    ps = np.asarray(darr(args[1]), F64).reshape(-1)
    if np.any(ps < 0) or np.any(ps != np.round(ps)):
        raise err('MATLAB:padarray:padsize', 'padsize holds whole numbers from 0.', 'padarray')
    rest = list(args[2:])
    val, method, direction = 0, None, 'both'
    for r in rest:
        s = opt_lower(r) if is_str(r) else None
        if s in ('circular', 'replicate', 'symmetric'):
            method = s
        elif s in ('both', 'pre', 'post'):
            direction = s
        elif s is None:
            val = np.asarray(darr(r)).reshape(-1)[0]
        else:
            raise err('MATLAB:padarray:option', "The method is a value, 'circular', 'replicate' or 'symmetric'; the direction 'both', 'pre' or 'post'.", 'padarray')
    nd = max(a.ndim, ps.size)
    a2 = a.reshape(a.shape + (1,) * (nd - a.ndim))
    p = np.concatenate([ps, np.zeros(nd - ps.size)]).astype(int)
    widths = [((x if direction in ('both', 'pre') else 0), (x if direction in ('both', 'post') else 0)) for x in p]
    if method is None:
        return np.pad(a2, widths, mode='constant', constant_values=val)
    return np.pad(a2, widths, mode={'circular': 'wrap', 'replicate': 'edge', 'symmetric': 'symmetric'}[method])


def _block(v, fn):
    s = np.asarray(darr(v), F64).reshape(-1).astype(int)
    if s.size != 2 or np.any(s < 1):
        raise err(f'MATLAB:{fn}:block', 'The block size is [m n], positive.', fn)
    return int(s[0]), int(s[1])


@bi('im2col')
def im2col(nargout, *args):
    """B = im2col(A, [m n], 'sliding' or 'distinct'): each m-by-n block of A as a column (in column order, the blocks too); 'distinct' blocks tile A (padded with zeros), 'sliding' ones are every position (the default)."""
    nargchk(args, 2, 3, 'im2col')
    a = np.asarray(arr(args[0], 'im2col'))
    if a.ndim != 2:
        raise err('MATLAB:im2col:dims', 'im2col takes a 2-D matrix.', 'im2col')
    m, n = _block(args[1], 'im2col')
    kind = opt_lower(args[2]) if len(args) > 2 else 'sliding'
    M, N = a.shape
    if kind == 'distinct':
        pm, pn = -(-M // m) * m, -(-N // n) * n
        p = np.zeros((pm, pn), a.dtype)
        p[:M, :N] = a
        cols = [p[i:i + m, j:j + n].reshape(-1, order='F') for j in range(0, pn, n) for i in range(0, pm, m)]
    elif kind == 'sliding':
        if m > M or n > N:
            return np.zeros((m * n, 0), a.dtype)
        cols = [a[i:i + m, j:j + n].reshape(-1, order='F') for j in range(N - n + 1) for i in range(M - m + 1)]
    else:
        raise err('MATLAB:im2col:kind', "The block type is 'sliding' or 'distinct'.", 'im2col')
    return np.column_stack(cols) if cols else np.zeros((m * n, 0), a.dtype)


@bi('col2im')
def col2im(nargout, *args):
    """A = col2im(B, [m n], [mm nn], 'distinct' or 'sliding'): columns back into an mm-by-nn image: each a block ('distinct'), or B a row of values, one for each sliding position ('sliding', the default)."""
    nargchk(args, 3, 4, 'col2im')
    b = np.asarray(arr(args[0], 'col2im'))
    m, n = _block(args[1], 'col2im')
    M, N = _block(args[2], 'col2im')
    kind = opt_lower(args[3]) if len(args) > 3 else 'sliding'
    if kind == 'sliding':
        return b.reshape(M - m + 1, N - n + 1, order='F')
    pm, pn = -(-M // m) * m, -(-N // n) * n
    out_ = np.zeros((pm, pn), b.dtype)
    k = 0
    for j in range(0, pn, n):
        for i in range(0, pm, m):
            out_[i:i + m, j:j + n] = b[:, k].reshape(m, n, order='F')
            k += 1
    return out_[:M, :N]


def _fh(v, fn):
    if isinstance(v, FH):
        return v
    if is_str(v):
        return R.NamedFH(py_str(v))
    raise err(f'MATLAB:{fn}:fun', 'fun is a function handle.', fn)


@bi('blockproc', aw=True)
async def blockproc(nargout, *args):
    """B = blockproc(A, [m n], fun, 'BorderSize', [v h], 'TrimBorder', tf,
    'PadPartialBlocks', tf, 'PadMethod', p): fun applied to each m-by-n block
    (a struct of data, location, blockSize, border and imageSize), the
    results put together in the blocks' places; a border of v rows and h
    columns of the neighbours (or of padding, PadMethod 0, 'replicate' or
    'symmetric') comes with each block, trimmed from the result unless
    TrimBorder is false; partial blocks at the edges are padded only with
    PadPartialBlocks."""
    nargchk(args, 3, 13, 'blockproc')
    a = np.asarray(arr(args[0], 'blockproc'))
    m, n = _block(args[1], 'blockproc')
    f = _fh(args[2], 'blockproc')
    o, _ = _opts(list(args[3:]), ('BorderSize', 'TrimBorder', 'PadPartialBlocks', 'PadMethod', 'UseParallel', 'DisplayWaitbar'))
    bs = np.asarray(darr(o['BorderSize']), int).reshape(-1) if 'BorderSize' in o else np.array([0, 0])
    trim = bool(np.all(np.asarray(darr(o['TrimBorder'])) != 0)) if 'TrimBorder' in o else True
    padpart = bool(np.all(np.asarray(darr(o['PadPartialBlocks'])) != 0)) if 'PadPartialBlocks' in o else False
    pm = o.get('PadMethod', 0.0)
    M, N = a.shape[:2]
    bv, bh = int(bs[0]), int(bs[1])
    rest_shape = a.shape[2:]
    if is_str(pm):
        mode = {'replicate': 'edge', 'symmetric': 'symmetric'}.get(opt_lower(pm))
        padded = np.pad(a, ((bv, bv), (bh, bh)) + ((0, 0),) * len(rest_shape), mode=mode)
    else:
        padded = np.pad(a, ((bv, bv), (bh, bh)) + ((0, 0),) * len(rest_shape), constant_values=float(num(pm)))
    rows = []
    for i in range(0, M, m):
        row = []
        for j in range(0, N, n):
            hgt, wid = min(m, M - i), min(n, N - j)
            data = padded[i:i + hgt + 2 * bv, j:j + wid + 2 * bh]
            if padpart and (hgt < m or wid < n):
                extra = ((0, m - hgt), (0, n - wid)) + ((0, 0),) * len(rest_shape)
                data = np.pad(data, extra, constant_values=float(num(pm)) if not is_str(pm) else 0.0)
            bsx = Struct.scalar({'data': out(np.ascontiguousarray(data)), 'location': np.array([[i + 1.0, j + 1.0]]),
                                 'blockSize': np.array([[float(hgt), float(wid)]]), 'border': np.array([[float(bv), float(bh)]]),
                                 'imageSize': np.array([[float(x) for x in a.shape]])})
            r = await f.acall(1, bsx)
            y = np.asarray(arr(r, 'blockproc')) if r is not None else np.zeros((0, 0))
            if y.ndim < 2:
                y = y.reshape(1, -1) if y.ndim == 1 else y.reshape(1, 1)
            if trim and (bv or bh) and y.shape[0] >= 2 * bv + 1 and y.shape[1] >= 2 * bh + 1 and y.shape[:2] == data.shape[:2]:
                y = y[bv:y.shape[0] - bv, bh:y.shape[1] - bh]
            row.append(y)
            if R.tk():
                await R.H(None, 0, '')
        rows.append(np.concatenate(row, axis=1))
    return np.concatenate(rows, axis=0) if rows else np.zeros((0, 0))


@bi('nlfilter', aw=True)
async def nlfilter(nargout, *args):
    """B = nlfilter(A, [m n], fun): fun applied to the m-by-n neighbourhood of every pixel (zeros outside; 'indexed' pads a double image with 1), its scalar result the pixel's value."""
    nargchk(args, 3, 4, 'nlfilter')
    a = np.asarray(arr(args[0], 'nlfilter'))
    rest = list(args[1:])
    indexed = False
    if is_str(rest[0]) and opt_lower(rest[0]) == 'indexed':
        indexed = True
        rest.pop(0)
    m, n = _block(rest[0], 'nlfilter')
    f = _fh(rest[1], 'nlfilter')
    cm, cn = (m - 1) // 2, (n - 1) // 2
    padv = 1.0 if indexed and a.dtype.kind == 'f' else 0.0
    p = np.pad(a.astype(F64) if a.dtype.kind != 'f' else a, ((cm, m - 1 - cm), (cn, n - 1 - cn)), constant_values=padv)
    res = np.zeros(a.shape)
    for j in range(a.shape[1]):
        for i in range(a.shape[0]):
            v = await f.acall(1, out(p[i:i + m, j:j + n].astype(a.dtype if a.dtype.kind == 'f' else F64)))
            res[i, j] = float(num(v))
        if R.tk():
            await R.H(None, 0, '')
    return _back(res, a.dtype) if a.dtype.kind in 'iu' else res


@bi('colfilt', aw=True)
async def colfilt(nargout, *args):
    """B = colfilt(A, [m n], 'sliding' or 'distinct', fun): fun applied to the blocks as columns at once (im2col): 'sliding' (each pixel's neighbourhood, zeros outside) wants a row of one value per column back, 'distinct' a matrix the size of its input."""
    nargchk(args, 4, 5, 'colfilt')
    a = np.asarray(arr(args[0], 'colfilt'))
    m, n = _block(args[1], 'colfilt')
    kind = opt_lower(args[2])
    f = _fh(args[3], 'colfilt')
    M, N = a.shape
    if kind == 'sliding':
        cm, cn = (m - 1) // 2, (n - 1) // 2
        p = np.pad(a.astype(F64), ((cm, m - 1 - cm), (cn, n - 1 - cn)))
        cols = np.asarray(darr(im2col(1, out(p), np.array([[float(m), float(n)]]), Char.of('sliding'))), F64)
        r = np.asarray(darr(await f.acall(1, out(cols))), F64).reshape(-1)
        if r.size != M * N:
            raise err('MATLAB:colfilt:result', 'For sliding blocks fun gives a row with a value for each column.', 'colfilt')
        return r.reshape(M, N, order='F')
    if kind == 'distinct':
        cols = np.asarray(darr(im2col(1, out(a.astype(F64)), np.array([[float(m), float(n)]]), Char.of('distinct'))), F64)
        r = np.asarray(darr(await f.acall(1, out(cols))), F64)
        if r.shape != cols.shape:
            raise err('MATLAB:colfilt:result', 'For distinct blocks fun gives a matrix the size of its input.', 'colfilt')
        return col2im(1, out(r), np.array([[float(m), float(n)]]), np.array([[float(M), float(N)]]), Char.of('distinct'))
    raise err('MATLAB:colfilt:kind', "The block type is 'sliding' or 'distinct'.", 'colfilt')


_PYR = np.array([0.0625, 0.25, 0.375, 0.25, 0.0625])


@bi('impyramid')
def impyramid(nargout, *args):
    """B = impyramid(A, 'reduce' or 'expand'): one level of a Gaussian pyramid (Burt and Adelson's 5-tap kernel, a = 0.375, the border replicated): half the size (ceil(M/2)) or twice less one (2M - 1)."""
    nargchk(args, 2, 2, 'impyramid')
    from scipy import ndimage
    a = _image(args[0], 'impyramid')
    d = opt_lower(args[1])
    planes, back = _planes(a)
    res = []
    for p in planes:
        x = p.astype(F64)
        if d == 'reduce':
            y = ndimage.correlate1d(ndimage.correlate1d(x, _PYR, axis=0, mode='nearest'), _PYR, axis=1, mode='nearest')
            res.append(y[::2, ::2])
        elif d == 'expand':
            M, N = x.shape
            up = np.zeros((2 * M - 1, 2 * N - 1))
            up[::2, ::2] = x
            y = ndimage.correlate1d(ndimage.correlate1d(up, 2 * _PYR, axis=0, mode='constant'), 2 * _PYR, axis=1, mode='constant')
            res.append(y)
        else:
            raise err('MATLAB:impyramid:direction', "The direction is 'reduce' or 'expand'.", 'impyramid')
    return _back(back(res), a.dtype if a.dtype != bool else F64)


@bi('improfile', nout=5)
def improfile(nargout, *args):
    """c = improfile(I, xi, yi, n, method); [cx, cy, c, xi, yi] = improfile(...):
    the values along the path through the points (xi, yi), sampled at n
    evenly spaced points (about one per pixel of its length when not given),
    'nearest' (default), 'bilinear' or 'bicubic'; NaN off the image. With
    no output the profile is plotted."""
    nargchk(args, 3, 5, 'improfile')
    a = _image(args[0], 'improfile')
    xi = np.asarray(darr(args[1]), F64).reshape(-1)
    yi = np.asarray(darr(args[2]), F64).reshape(-1)
    rest = list(args[3:])
    nsamp = None
    method = 'nearest'
    for r in rest:
        if is_str(r):
            method = opt_lower(r)
        else:
            nsamp = int(num(r))
    from .imageproc import _method3
    method = _method3(method, 'improfile')
    seg = np.hypot(np.diff(xi), np.diff(yi))
    total = float(seg.sum())
    if nsamp is None:
        nsamp = max(int(math.ceil(total)) + 1, 2)
    cum = np.concatenate([[0], np.cumsum(seg)])
    s = np.linspace(0, total, nsamp)
    cx = np.interp(s, cum, xi)
    cy = np.interp(s, cum, yi)
    planes, _ = _planes(a.astype(F64))
    vals = []
    for p in planes:
        v = _sample(p, cx, cy, method, np.nan)
        vals.append(v)
    c = np.column_stack(vals) if len(vals) > 1 else vals[0].reshape(-1, 1)
    if nargout == 0:
        REG['plot'].fn(0, out(c))
        return None
    if nargout <= 1:
        return out(c)
    return _outs(nargout, out(cx.reshape(-1, 1)), out(cy.reshape(-1, 1)), out(c), out(xi.reshape(-1, 1)), out(yi.reshape(-1, 1)))


@bi('imcontour', nout=2)
def imcontour(nargout, *args):
    """imcontour(I, n or v, LineSpec), [C, h] = imcontour(...): the image's contour lines (n levels, or at v) drawn in its own orientation: rows down, square pixels."""
    nargchk(args, 1, 5, 'imcontour')
    a = _image(args[0], 'imcontour')
    res = REG['contour'].fn(max(nargout, 2), out(a.astype(F64)), *args[1:])
    REG['axis'].fn(0, Char.of('ij'))
    REG['axis'].fn(0, Char.of('image'))
    if nargout == 0:
        return None
    return res if nargout > 1 else res[0]
