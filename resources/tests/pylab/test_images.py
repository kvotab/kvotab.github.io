"""Image processing, run natively (CPython with numpy, scipy and Pillow):
resizing (against Pillow's resampling inside the image), rotating,
cropping and translating, filters (against correlation written out here),
fspecial's kernels, edges, contrast and thresholds (Otsu written out),
morphology, filling, connected components and their measurements, and
tiles of images.

    python3 test_images.py          (from any folder)
"""
import asyncio
import math
import os
import sys
import tempfile

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-images-')


def run(code):
    R.BASE.clear()
    R.take_output()
    asyncio.run(R.execute(f"cd('{TMP}');\n" + code))
    return dict(R.BASE), R.take_output()


class Checks:
    def __init__(self):
        self.n = 0
        self.failed = []

    def __call__(self, label, ok, detail=''):
        self.n += 1
        if not ok:
            self.failed.append(label)
            print(f'FAIL  {label}  {detail}')
        return ok

    def done(self):
        print(f'\n{self.n - len(self.failed)} of {self.n} checks passed')
        return 1 if self.failed else 0


C = Checks()


def a(x):
    if isinstance(x, tuple):
        parts = [np.asarray(v, dtype=float).reshape(-1) for v in x]
        return np.concatenate(parts) if parts else np.zeros(0)
    return np.asarray(x, dtype=float)


def near(label, got, want, tol=1e-10):
    g, w = a(got), a(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {np.round(g, 6).tolist() if g.size < 30 else g.shape}, want {np.round(w, 6).tolist() if w.size < 30 else w.shape}')


def same(label, got, want):
    return C(label, got == want, f'got {got!r}, want {want!r}')


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = W['e'].str() if isinstance(W['e'], Char) else str(W['e'])
    return C(f'refused: {code}', words in msg, msg)


def save(name, arr):
    np.savetxt(os.path.join(TMP, name), arr, fmt='%.17g')


def corr(A, h, pad, full=False):
    """Correlation written out: out(i, j) = sum h(u, v) A(i + u - c, j + v - c), A padded as asked."""
    kr, kc = h.shape
    cr, cc = (kr + 1) // 2, (kc + 1) // 2
    m, n = A.shape
    if full:
        b, af = (kr - 1, kc - 1), (kr - 1, kc - 1)
    else:
        b, af = (cr - 1, cc - 1), (kr - cr, kc - cc)
    mode = {'zeros': 'constant', 'symmetric': 'symmetric', 'replicate': 'edge', 'circular': 'wrap'}[pad]
    P = np.pad(A.astype(float), ((b[0], af[0]), (b[1], af[1])), mode=mode)
    out = np.zeros((P.shape[0] - kr + 1, P.shape[1] - kc + 1))
    for i in range(out.shape[0]):
        for j in range(out.shape[1]):
            out[i, j] = np.sum(P[i:i + kr, j:j + kc] * h)
    return out


rng = np.random.default_rng(3)
I0 = rng.random((40, 40))
save('img.txt', I0)
U8 = (rng.random((12, 15)) * 255).round()
save('u8.txt', U8)

# ---- resizing -----------------------------------------------------------------------------------------------------
W, _ = run("I = load('img.txt'); s = imresize(I, 0.5); b = imresize(I, 1.5, 'bilinear'); one = imresize(I, 1); "
           "U = uint8(load('u8.txt')); n2 = imresize(U, 2, 'nearest'); cls = class(imresize(U, 0.7)); r = size(imresize(U, [6 NaN])); "
           "q = imresize(U, [5 7], 'bilinear', 'Antialiasing', false);")
pil = lambda a_, size, how: np.asarray(Image.fromarray(a_.astype(np.float32), 'F').resize(size, how), float)  # noqa: E731
inner = (slice(3, -3), slice(3, -3))
near('imresize 0.5 bicubic with antialiasing: Pillow\'s bicubic inside the image', a(W['s'])[inner], pil(I0, (20, 20), Image.BICUBIC)[inner], 1e-5)
near('imresize 1.5 bilinear: Pillow\'s bilinear inside the image', a(W['b'])[inner], pil(I0, (60, 60), Image.BILINEAR)[inner], 1e-5)
near('imresize by 1 gives the image back', W['one'], I0, 1e-12)
near("'nearest' by 2 repeats each pixel", W['n2'], np.kron(U8, np.ones((2, 2))))
same('the class kept; NaN keeps the aspect ratio', (W['cls'].str(), a(W['r']).tolist()), ('uint8', [[6.0, 8.0]]))
W, _ = run("q = imresize(1:15, [1 30], 'bilinear');")
xq = np.arange(1, 31) / 2 + 0.25
inside = (xq >= 1) & (xq <= 15)
near("bilinear: each output the input interpolated at u/scale + (1 - 1/scale)/2 (a ramp stays a ramp)", a(W['q']).reshape(-1)[inside], xq[inside], 1e-12)

# ---- rotating, cropping, translating ---------------------------------------------------------------------------------------
W, _ = run("U = uint8(load('u8.txt')); r90 = imrotate(U, 90); r180 = imrotate(U, -180); c90 = size(imrotate(U, 90, 'nearest', 'crop')); "
           "r30 = size(imrotate(U, 30)); c30 = size(imrotate(U, 30, 'bilinear', 'crop')); P = zeros(11); P(6, 6) = 1; p45 = imrotate(P, 45, 'bilinear', 'crop'); "
           "K = ones(20); k = imrotate(K, 17, 'bicubic', 'crop'); [J, rc] = imcrop(U, [2 3 4 5]); t = imtranslate(U, [2 1]); h = imtranslate([0 0 0 0; 0 2 4 0], [0.5 0]);")
near('imrotate by 90 and -180: rot90 exactly', (W['r90'], W['r180']), (np.rot90(U8), np.rot90(U8, 2)))
th = math.radians(30)
same("sizes: 'crop' keeps A's; 'loose' holds the turned corners", (a(W['c90']).tolist(), a(W['r30']).tolist(), a(W['c30']).tolist()),
     ([[12.0, 15.0]], [[float(math.ceil(15 * math.sin(th) + 12 * math.cos(th) - 1e-9)), float(math.ceil(15 * math.cos(th) + 12 * math.sin(th) - 1e-9))]], [[12.0, 15.0]]))
same('a pixel at the centre stays there', np.unravel_index(np.argmax(a(W['p45'])), (11, 11)), (5, 5))
near('a constant image stays constant away from the corners', a(W['k'])[7:13, 7:13], np.ones((6, 6)), 1e-12)
near('imcrop [xmin ymin width height]: the pixels whose centres lie in it', (W['J'], W['rc']), (U8[2:8, 1:6], [2, 3, 4, 5]))
want = np.zeros_like(U8)
want[1:, 2:] = U8[:-1, :-2]
near('imtranslate by whole pixels: moved, zeros behind; by half a pixel: averages', (W['t'], W['h']), (want, [[0, 0, 0, 0], [0, 1, 3, 2]]))

# ---- filters -----------------------------------------------------------------------------------------------------------------
A = np.arange(1, 37, dtype=float).reshape(6, 6) ** 1.3 % 17
save('a.txt', A)
h = np.array([[1.0, 2, 0.5], [0, -1, 3]])
save('h.txt', h)
W, _ = run("A = load('a.txt'); h = load('h.txt'); z = imfilter(A, h); s = imfilter(A, h, 'symmetric'); r = imfilter(A, h, 'replicate'); "
           "c = imfilter(A, h, 'circular'); f = imfilter(A, h, 'full'); v = imfilter(A, h, 5); cv = imfilter(A, h, 'conv'); c2 = conv2(A, h, 'same'); "
           "u = imfilter(uint8([10 200; 30 250]), [1 1; 1 1]); rgb = imfilter(cat(3, A, 2*A), h);")
near('imfilter with zeros beyond the edge: correlation written out, centre at floor((size + 1)/2)', W['z'], corr(A, h, 'zeros'))
near("'symmetric', 'replicate' and 'circular' edges", (W['s'], W['r'], W['c']), (corr(A, h, 'symmetric'), corr(A, h, 'replicate'), corr(A, h, 'circular')))
near("'full' size, and a constant value beyond the edge", (W['f'], W['v']), (corr(A, h, 'zeros', True), corr(A - 5, h, 'zeros') + 5 * h.sum()))
near("'conv' is conv2's 'same'", W['cv'], W['c2'], 1e-12)
near('integer images rounded and saturated; colour planes alike', (W['u'], a(W['rgb'])[:, :, 1]), ([[255, 255], [255, 250]], 2 * corr(A, h, 'zeros')))

W, _ = run("av = fspecial('average'); g = fspecial('gaussian', [3 5], 0.8); d5 = fspecial('disk', 5); d1 = fspecial('disk', 1); lp = fspecial('laplacian'); "
           "lg = fspecial('log'); m0 = fspecial('motion', 9, 0); m45 = fspecial('motion', 5, 45); sb = fspecial('sobel'); pw = fspecial('prewitt'); us = fspecial('unsharp');")
yy, xx = np.mgrid[-1:2, -2:3]
gg = np.exp(-(xx ** 2 + yy ** 2) / (2 * 0.8 ** 2))
near("'average' and 'gaussian' (normalized, [3 5], sigma 0.8)", (W['av'], W['g']), (np.ones((3, 3)) / 9, gg / gg.sum()))
d5 = a(W['d5'])
near("'disk': exact areas: a pixel wholly inside weighs 1/(pi r^2), the kernel symmetric", (d5[5, 5], d5, d5.sum()), (1 / (25 * math.pi), d5.T, 1.0), 1e-9)
d1 = a(W['d1'])
from scipy.integrate import quad  # noqa: E402
area_corner = quad(lambda x: max(0.0, min(1.5, math.sqrt(max(1 - x * x, 0))) - 0.5), 0.5, 1)[0]
near("'disk' 1: corner pixel area by quadrature, over pi", d1[0, 0], area_corner / math.pi, 1e-9)
near("'laplacian' 0.2 and 'unsharp' 0.2 (their 3-by-3 forms)", (W['lp'], W['us']),
     (4 / 1.2 * np.array([[0.05, 0.2, 0.05], [0.2, -1, 0.2], [0.05, 0.2, 0.05]]), np.array([[-0.2, -0.8, -0.2], [-0.8, 5.2, -0.8], [-0.2, -0.8, -0.2]]) / 1.2))
near("'log' adds up to 0; 'motion' 9 0 is ones(1, 9)/9", (np.sum(a(W['lg'])), W['m0']), (0.0, np.ones((1, 9)) / 9), 1e-12)
m45 = a(W['m45'])
C("'motion' 5 at 45 degrees: up to the right, symmetric about the centre, adding up to 1",
  np.isclose(m45.sum(), 1) and np.allclose(m45, m45[::-1, ::-1]) and m45[0, -1] > 0 and m45[-1, 0] > 0 and m45[0, 0] == 0, m45)
near("'sobel' and 'prewitt'", (W['sb'], W['pw']), ([[1, 2, 1], [0, 0, 0], [-1, -2, -1]], [[1, 1, 1], [0, 0, 0], [-1, -1, -1]]))

W, _ = run("I = load('img.txt'); g = imgaussfilt(I, 1.2); f = imfilter(I, fspecial('gaussian', 2*ceil(2*1.2)+1, 1.2), 'replicate'); "
           "m = medfilt2(I(1:9, 1:8)); m34 = medfilt2(I(1:9, 1:8), [3 4]); ms = medfilt2(I(1:9, 1:8), [3 3], 'symmetric');")
near('imgaussfilt: imfilter of fspecial gaussian with replicated edges', W['g'], W['f'], 1e-12)


def med(A_, m, n, mode):
    cr, cc = (m + 1) // 2, (n + 1) // 2
    P = np.pad(A_, ((cr - 1, m - cr), (cc - 1, n - cc)), mode='constant' if mode == 'zeros' else 'symmetric')
    return np.array([[np.median(P[i:i + m, j:j + n]) for j in range(A_.shape[1])] for i in range(A_.shape[0])])


near('medfilt2 3-by-3 with zeros, 3-by-4 (centre floor((size + 1)/2)), and mirrored edges', (W['m'], W['m34'], W['ms']),
     (med(I0[:9, :8], 3, 3, 'zeros'), med(I0[:9, :8], 3, 4, 'zeros'), med(I0[:9, :8], 3, 3, 'symmetric')))

# ---- edges ----------------------------------------------------------------------------------------------------------------------
W, _ = run("I = zeros(30); I(9:22, 9:22) = 1; [e, t] = edge(I); c = edge(I, 'canny'); l = edge(I, 'log'); p = edge(I, 'prewitt'); "
           "r = edge(I, 'roberts'); h = edge(I, 'sobel', [], 'horizontal'); n = nnz(edge(I, 'sobel', 0.01, 'nothinning')); z = edge(zeros(10));")
sq = np.zeros((30, 30), bool)
sq[8:22, 8:22] = True
ring = sq ^ ndimage.binary_erosion(sq)
ring_out = ndimage.binary_dilation(sq) ^ sq
for nm in ('e', 'c', 'l', 'p', 'r'):
    e_ = a(W[nm]).astype(bool)
    C(f"edge '{dict(e='sobel', c='canny', l='log', p='prewitt', r='roberts')[nm]}': edges only beside the square's border, along all four sides",
      e_.any() and not (e_ & ~ndimage.binary_dilation(ring | ring_out, iterations=1)).any() and all(e_[k].any() for k in (np.s_[6:10, 12:18], np.s_[20:24, 12:18], np.s_[12:18, 6:10], np.s_[12:18, 20:24])),
      np.argwhere(e_)[:5])
hz = a(W['h']).astype(bool)
C("'horizontal': the top and bottom sides only", hz[7:10, 12:18].any() and not hz[12:18, 6:11].any(), np.argwhere(hz)[:5])
C('a threshold is given back; no thinning marks more; a flat image has no edges', float(W['t']) > 0 and float(W['n']) > np.count_nonzero(a(W['e'])) and not a(W['z']).any(), W['t'])

# ---- contrast and thresholds ------------------------------------------------------------------------------------------------------
W, _ = run("u = uint8(0:255); s = stretchlim(u); j = imadjust(u); jg = imadjust([0 0.25 0.5 1], [0 1], [0 1], 2); [c, x] = imhist(u, 4); ch = imhist(uint8([0 0 255 128]))'; "
           "h = histeq(uint8([0 0 0 10 10 200 255 255]), 4); I = load('img.txt'); lv = graythresh(I); bw = imbinarize(I); bt = imbinarize(I, 0.3); "
           "c8 = imcomplement(uint8([0 10 255])); cdd = imcomplement([0.25 1]); cl = imcomplement([true false]); ci = imcomplement(int16([0 -5]));")
near('stretchlim of 0..255: the 1 % and 99 % points', W['s'], [[2 / 255], [253 / 255]])
uu = np.arange(256) / 255
near('imadjust maps stretchlim\'s limits to 0 and 1; gamma bends the curve', (W['j'], W['jg']),
     (np.round(np.clip((uu - 2 / 255) / (251 / 255), 0, 1) * 255), [0, 0.0625, 0.25, 1]))
near('imhist: counts in n bins over the class range, and the bins\' places', (W['c'], W['x'], W['ch']), ([43, 85, 85, 43], [0, 85, 170, 255], np.bincount([0, 0, 255, 128], minlength=256)))
hv = a(W['h']).reshape(-1)
C('histeq: at most n levels, in the same order as the input', len(set(hv.tolist())) <= 4 and np.all(np.diff(hv) >= 0), hv)


def otsu(img):
    p = np.bincount(np.clip(np.round(img.reshape(-1) * 255), 0, 255).astype(int), minlength=256) / img.size
    best, ks = -1, []
    for k in range(256):
        w0, w1 = p[:k + 1].sum(), p[k + 1:].sum()
        if w0 == 0 or w1 == 0:
            continue
        m0 = (np.arange(k + 1) * p[:k + 1]).sum() / w0
        m1 = (np.arange(k + 1, 256) * p[k + 1:]).sum() / w1
        v = w0 * w1 * (m0 - m1) ** 2
        if v > best + 1e-15:
            best, ks = v, [k]
        elif abs(v - best) <= 1e-15:
            ks.append(k)
    return np.mean(ks) / 255


near("graythresh: Otsu's level, the between-class variance written out", W['lv'], otsu(I0), 1e-12)
near('imbinarize: brighter than Otsu\'s level, or than the level given', (W['bw'], W['bt']), (I0 > otsu(I0), I0 > 0.3))
near('imcomplement for uint8, double, logical and int16', (W['c8'], W['cdd'], W['cl'], W['ci']), ([255, 245, 0], [0.75, 0], [0, 1], [-1, 4]))

# ---- morphology ------------------------------------------------------------------------------------------------------------------
B = np.zeros((12, 12), bool)
B[3:8, 2:9] = True
B[5, 5] = False
B[9, 9] = True
save('b.txt', B.astype(float))
W, _ = run("B = logical(load('b.txt')); d = imdilate(B, strel('disk', 1)); e = imerode(B, strel('square', 3)); o = imopen(B, strel('square', 2)); "
           "oo = imopen(o, strel('square', 2)); cl = imclose(B, strel('diamond', 1)); I = load('img.txt'); gd = imdilate(I(1:10, 1:10), strel('square', 3)); "
           "ge = imerode(I(1:10, 1:10), ones(1, 3)); n1 = nnz(strel('disk', 2).Neighborhood); n2 = nnz(getfield(strel('diamond', 2), 'Neighborhood')); "
           "ln = strel('line', 5, 0); l5 = ln.Neighborhood; oc = strel('octagon', 3); o3 = oc.Neighborhood; se = strel([1 0 1])")
cross = ndimage.generate_binary_structure(2, 1)
near('imdilate by a disk of 1: binary dilation by the cross', W['d'], ndimage.binary_dilation(B, cross))
near('imerode by a square: binary erosion (outside counts as set)', W['e'], ndimage.binary_erosion(B, np.ones((3, 3)), border_value=1))
near('imopen twice is imopen once; imclose by a diamond', (W['oo'], W['cl']), (W['o'], ndimage.binary_erosion(ndimage.binary_dilation(B, cross), cross, border_value=1)))
near('grey dilation and erosion: the max and min under the element', (W['gd'], W['ge']),
     (ndimage.maximum_filter(I0[:10, :10], size=3, mode='constant', cval=-np.inf), ndimage.minimum_filter(I0[:10, :10], size=(1, 3), mode='constant', cval=np.inf)))
near('strel shapes: disk 2 and diamond 2 have 13 pixels; a line of 5; an octagon cut at the corners', (W['n1'], W['n2'], W['l5'], a(W['o3'])[0, 0], a(W['o3'])[0, 3], a(W['o3'])[3, 0]),
     (13, 13, np.ones((1, 5)), 0, 1, 1))
W, out = run("se = strel('disk', 3)")
C('a strel is shown with its neighbourhood', 'strel is a disk shaped structuring element' in out and 'Neighborhood' in out, out)

H = np.zeros((9, 9), bool)
H[1:8, 1:8] = True
H[3:6, 3:6] = False
H[4, 0] = False
save('hole.txt', H.astype(float))
W, _ = run("H = logical(load('hole.txt')); f = imfill(H, 'holes'); g = imfill(~H, [1 1]); bw = imfill(H, [5 5]);")
near("imfill 'holes': background cut off from the edge filled", W['f'], ndimage.binary_fill_holes(H))
near('imfill at a location: that background region flooded', W['bw'], H | (ndimage.label(~H, cross)[0] == ndimage.label(~H, cross)[0][4, 4]))

# ---- connected components --------------------------------------------------------------------------------------------------------
Q = np.array([[1, 1, 0, 0, 1], [0, 0, 0, 1, 0], [1, 0, 0, 0, 0], [1, 0, 1, 1, 0]], bool)
save('q.txt', Q.astype(float))
W, _ = run("Q = logical(load('q.txt')); [L, n] = bwlabel(Q); [L4, n4] = bwlabel(Q, 4); cc = bwconncomp(Q); k = cc.NumObjects; p2 = cc.PixelIdxList{2};")
same('bwlabel: 8-connected components numbered by their first pixel down the columns', (a(W['L']).astype(int).tolist(), W['n']),
     ([[1, 1, 0, 0, 4], [0, 0, 0, 4, 0], [2, 0, 0, 0, 0], [2, 0, 3, 3, 0]], 4.0))
same('4-connectivity splits the diagonal pair', W['n4'], 5.0)
near('bwconncomp: objects and their linear indices (down the columns)', (W['k'], W['p2']), (4, [[3], [4]]))
R_ = np.zeros((10, 12), bool)
R_[2:5, 1:9] = True       # 3 rows by 8 columns
R_[7, 10] = True
save('r.txt', R_.astype(float))
W, _ = run("R = logical(load('r.txt')); s = regionprops(R, 'Area', 'Centroid', 'BoundingBox', 'MajorAxisLength', 'MinorAxisLength', 'Orientation', 'Eccentricity', "
           "'Extent', 'EquivDiameter', 'ConvexArea', 'Solidity', 'FilledArea'); a1 = s(1).Area; c1 = s(1).Centroid; b1 = s(1).BoundingBox; mj = s(1).MajorAxisLength; "
           "mn = s(1).MinorAxisLength; or1 = s(1).Orientation; ec = s(1).Eccentricity; ex = s(1).Extent; ed = s(2).EquivDiameter; ca = s(1).ConvexArea; "
           "T = regionprops('table', R, 'Area'); ta = T.Area; L = double(R); L(8, 11) = 2; I = magic(12); I = I(1:10, :); m = regionprops(L, I, 'MeanIntensity', 'MaxIntensity'); "
           "mi = [m.MeanIntensity]; v1 = mean(mean(I(3:5, 2:9))); v2 = I(8, 11); ns = numel(regionprops(R));")
near('regionprops: Area, Centroid [x y], BoundingBox from the pixel edges', (W['a1'], W['c1'], W['b1']), (24, [5.5, 4], [1.5, 2.5, 8, 3]))
near('the ellipse of the same second moments: 2w/sqrt(3) and 2h/sqrt(3) for a w-by-h block, Orientation 0',
     (W['mj'], W['mn'], W['or1'], W['ec']), (16 / math.sqrt(3), 6 / math.sqrt(3), 0, math.sqrt(1 - (3 / 8) ** 2)), 1e-12)
near('Extent, EquivDiameter, ConvexArea of a block', (W['ex'], W['ed'], W['ca']), (1, math.sqrt(4 / math.pi), 24))
near("'table' gives a table; intensity measures with a label matrix", (W['ta'], W['mi']), ([[24], [1]], (W['v1'], W['v2'])))
same('regions of a logical image are its components', W['ns'], 2.0)

# ---- tiles ---------------------------------------------------------------------------------------------------------------------------
W, _ = run("a = ones(2, 3); t = imtile({a/4, a/2, 3*a/4, a}); g = imtile({a, a, a}, 'GridSize', [1 3]); s = size(imtile(rand(4, 5, 7)));")
near('imtile: row by row in a square-ish grid; GridSize', (W['t'], np.shape(W['g'])), (np.block([[np.ones((2, 3)) / 4, np.ones((2, 3)) / 2], [np.ones((2, 3)) * 3 / 4, np.ones((2, 3))]]), (2, 9)))
near('a stack of 7 gray images in a grid', W['s'], [[12, 15]])
W, _ = run("close all; h = montage({ones(4), zeros(4)}); k = class(h); close all")
same('montage shows the tiles as an image', W['k'].str(), 'matlab.graphics.primitive.Image')

raises('imresize(ones(3), 0)', 'positive')
raises("imrotate(ones(3), 10, 'spline')", 'method is')
raises("imfilter(ones(3), ones(2), 'mirror')", 'not an option')
raises("fspecial('wiener')", 'The type is')
raises("strel('ball', 3)", 'The shape is')
raises("imbinarize(rand(4), 'adaptive')", 'thresholds the whole image')
raises('imcrop(ones(4))', 'Give the rectangle')
raises("regionprops(true(3), 'Perimeterish')", 'not a property')

sys.exit(C.done())
